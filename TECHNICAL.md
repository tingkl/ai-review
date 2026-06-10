# Commit AI Guardian — 技术文档

## 系统架构

```
用户命令（cli.py）
    │
    ├── install ──→ hook_installer.py ──→ 写入 .git/hooks/pre-commit
    │                                    ──→ 创建 .ai-review/cases/ + example/
    │
    ├── audit ────→ diff_collector.py ──→ 获取 Git staged diff
    │             ──→ ai_engine.py ──────→ 调用 AI API
    │             ──→ result_formatter.py ──→ 终端展示
    │
    ├── review ───→ file_collector.py ──→ 读取文件系统
    │             ──→ ai_engine.py
    │             ──→ result_formatter.py
    │
    ├── configure ──→ config.py ──→ 读写 ~/.commit-ai-guardian/config.yaml
    │
    ├── validate-cases ──→ case_validator.py ──→ 校验 .md 格式
    │
    └── status ──→ 显示配置和安装状态
```

## 核心数据流

### audit 命令（Git diff 审核）

```
git commit
    │
    ▼
.git/hooks/pre-commit（bash 脚本）
    │
    ▼
python -m commit_ai_guardian audit --repo <path>
    │
    ├── 1. ConfigManager.load()
    │        读取 ~/.commit-ai-guardian/config.yaml
    │        不存在则创建默认配置
    │
    ├── 2. DiffCollector.get_staged_diffs()
    │        执行 git diff --cached
    │        解析 diff 文本 → FileDiff 列表
    │        过滤二进制/大文件/忽略模式
    │
    ├── 3. AIEngine.review_batch()
    │        逐个文件构建 Prompt
    │        调用 OpenAI API（含重试）
    │        解析 JSON 响应 → ReviewResult 列表
    │
    ├── 4. ResultFormatter.format_and_display()
    │        Rich 库渲染终端输出
    │        汇总统计
    │
    └── 5. 判断退出码
             exit 0 → commit 放行
             exit 1 → commit 阻断
```

## Git Diff 采集详解

### 使用的命令

```bash
git diff --cached --unified=5 --diff-filter=ACMRT
```

| 参数 | 含义 |
|------|------|
| `--cached` | 对比暂存区（staged）和 HEAD，获取已 `git add` 但未 commit 的变更 |
| `--unified=5` | Unified diff 格式，显示变更前后各 5 行上下文 |
| `--diff-filter=ACMRT` | 只包含 Added/Copied/Modified/Renamed/Type-changed 的文件，**排除 Deleted** |

### 输出示例

```
diff --git a/src/auth.ts b/src/auth.ts
index 3a4f2b..8c7e1d 100644
--- a/src/auth.ts
+++ b/src/auth.ts
@@ -10,7 +10,7 @@ import { UserService } from './user.service';
  * 用户认证模块
  */
 export class AuthService {
-  private timeout = 30000;
+  private timeout = 60000;

   async login(username: string, password: string) {
     const user = await this.userService.findOne(username);
```

### 解析流程

```
git diff --cached --unified=5 --diff-filter=ACMRT
    │
    ▼
diff_output（完整的 unified diff 文本）
    │
    ├── _split_diff_by_file() → 按 "diff --git a/" 分割
    │      得到: ["diff --git a/src/auth.ts...", "diff --git a/src/api.ts..."]
    │
    └── _parse_file_diff()（逐个文件解析）
           │
           ├── 文件名 → diff --git a/(...) b/(...)
           │
           ├── 状态 → added / modified / deleted / renamed
           │
           ├── 行号 → 从 @@ hunk 头解析
           │      @@ -10,7 +10,7 @@  → 新文件从第 10 行开始
           │      遍历 + 行 → 记录行号（这些是新增/修改的行）
           │      遍历 - 行 → 跳过（删除的行不属于新文件）
           │
           └── 统计 → additions / deletions 计数
           │
           ▼
    FileDiff(
        filename="src/auth.ts",
        status="modified",
        diff_content="完整的 diff 文本",
        line_numbers=[15],      ← 第 15 行是本次变更
        additions=1,
        deletions=1,
    )
```

### 行号解析原理

从 `@@` hunk 头提取起始行号，然后逐行遍历 hunk 内容：

| 行前缀 | 处理 | 行号变化 |
|--------|------|---------|
| `+`（空格后） | 记录当前行号（**新增/修改的行**） | `current_line += 1` |
| `-`（空格后） | 跳过（删除的行不属于新文件） | 不变 |
| ` `（空格，上下文行） | 跳过 | `current_line += 1` |
| `\` | 跳过（"No newline at end of file"） | 不变 |

示例中的 `+  private timeout = 60000;` 对应新文件第 15 行，所以 `line_numbers = [15]`。

### 传给 AI 的 diff_content

原始 diff 文本经过 `_annotate_diff_with_line_numbers()` 加上行号前缀后发给 AI：

```
   1 | <template>
   2 |   <!-- {{ proxy }} -->
  15 |     :loading="loading"
  16 |     popup-class-name="bus-remote-select"
+  99 | {{ this.$filter.PlatformLabel(option.platformId) }}
```

格式说明：
- ` 145 | context line` — 上下文行，显示原文件行号
- `+ 145 | +added line` — 新增行，显示新文件行号
- `     | -deleted line` — 删除行，不显示行号

AI 根据左侧行号返回 `line_number`，不受 prompt 前面说明文字的影响。

### review 命令（文件审核）

```
commit-ai-guardian review -f src/main.py
    │
    ├── 1. ConfigManager.load()
    │
    ├── 2. FileCollector.collect()
    │        支持三种来源：--file / --dir / --pattern
    │        自动去重（set 记录已处理文件名）
    │        过滤二进制/大文件/忽略模式
    │
    ├── 3. AIEngine.review_source_batch()
    │        完整文件内容审核（非 diff 模式）
    │
    └── 4. ResultFormatter.format_and_display()
             永远 exit 0（不阻断任何操作）
```

## Prompt 构建原理

### 输入

- 代码内容（diff 或完整文件）
- 案例库（.ai-review/cases/ 下的 .md 文件）

### 处理流程

```
代码文件
    │
    ├── 文件元信息 ──→ 文件名、语言、行数
    │
    └── 代码内容 ────→ 截断到 8000 字符（防止超长）

案例文件
    │
    ├── parse_frontmatter() ──→ 提取 YAML 元数据
    │
    ├── extract_examples() ───→ 提取坏代码/好代码
    │
    ├── extract_check_points() ──→ 提取检查清单
    │
    └── format_cases_for_prompt() ──→ 拼成 AI 可读文本

最终 Prompt = 审核维度说明 + 严重级别定义 + 代码信息 + 代码内容 + 案例参照 + 输出格式要求
```

### Prompt 结构示例

```
你是一位资深代码审核专家...

## 审核维度（通用规则）
1. Bug 检测...
2. 安全漏洞...
...

## 严重级别定义
critical / error / warning / info

## 代码信息
- 文件: src/auth.py
- 语言: Python
- 变更类型: modified

## 代码变更内容
```python
（代码）
```

## 重点检查以下问题模式（参照案例）
（解析后的案例文本）

## 输出格式
```json
{...}
```
```

## Prompt 设计要点

### 1. 约束放最前面

系统消息（system message）的第一行就是输出格式规则，用 `🚨🚨🚨` 醒目标记。模型对消息开头的注意力最强，约束放在前面比放在 prompt 末尾遵守率高出数倍。

### 2. 用标签包裹 JSON，不用代码块

**为什么用 `<result>` 标签而不是 ` ```json `：**

- 代码块标记（```）中的花括号 `{}` 容易被模型的格式化逻辑干扰
- `<result>` 是自定义标签，模型不会对其内容进行特殊处理，JSON 原样保留
- 提取时正则匹配 `<result>(.*?)</result>` 即可，不受内部结构影响

### 3. 正例 + 反例（Few-shot）

每条规则都附 ✅ 正确示例和 ❌ 错误示例。纯文本规则模型容易忽略，但具体示例的约束力强得多。

例如规则3（issue 之间必须有逗号）：
```
❌ 错误示例：
   "code_snippet":"if(x){}"}{"severity":...    ← 漏了逗号
✅ 正确：
   "code_snippet":"if(x){}"}, {"severity":...
```

### 4. 思考与结果分离

- `<think>`：分析过程，长度控制在 500 字以内，只写结论性要点
- `<result>`：最终输出，必须是合法 JSON

分离的好处：
- `<think>` 即使写得不好也不影响 JSON 解析
- 可以在代码层面过滤掉 `<think>` 标签
- 给 `<result>` 留出充足的 token 空间

### 5. JSON 自检要求

在规则末尾加入自检清单，要求模型输出前确认：
1. 字符串中的 `"` 和 `\` 已正确转义
2. `code_snippet` 含 `{` `}` 时不破坏 JSON 结构
3. 多个 issue 之间有逗号 `}, {`
4. 无 trailing comma
5. `line_number` 是单个整数

自检要求比单纯说"输出合法 JSON"有效得多——模型在生成时会有意识地进行检查。

### 6. 防御性编程规则

空指针检测采用"不假设、不掩盖"原则：
- 来源不明确的参数 → **不报**（避免误报）
- 显式 null、未传参、可选链矛盾 → **正常报**
- **不报**"加个 if 判断"之类的防御性建议，追问根本原因

### 7. Prompt 模板可覆盖

默认模板内嵌在 `prompt_loader.py` 中，`install` 命令会把模板写入 `.ai-review/prompts/`。用户可以直接编辑这些文件来自定义审核行为，不需要改代码。

### 8. System/User 角色分工

API 调用时 messages 分为 system 和 user 两个 role，内容不能混放。

**system message 只放规则约束：**
- 角色定义（"你是代码审核专家"）
- 输出格式规则（`<result>` 标签、JSON 结构）
- `<think>` 长度限制和位置约束
- JSON 自检清单（5 条检查项 + 常见错误示例）

**user message 只放任务内容：**
- 要审核的代码（`{{diff_content}}` 或 `{{content}}`）
- 审核维度说明（Bug/安全/风格/性能/最佳实践/文档）
- 空指针检测规则（具体业务规则，不是格式规则）
- 案例参考（`{{cases_text}}`）
- 严重级别定义

**为什么这样分：**
- 模型对 system 的注意力权重更高，格式约束放在这里遵守率更好
- 代码内容每次都不同，放 user 中，避免 system 过长导致 KV cache 失效
- 两边不重复——system 中的 JSON 格式约束不在 user 中重复，节省 token

**user message 中的输出格式提示：**

不需要再在 user 中写完整的 `<result>` 示例和 JSON 格式说明。只需一行引用：

```
## 输出要求
输出格式规则已在 system message 中说明，此处不再重复。请严格遵守。
```

保留 `⚠️ JSON 自检` 作为最后提醒（双重保险）。

---

## 案例文件解析逻辑

### 文件格式

Markdown + YAML frontmatter：

```markdown
---
title: SQL 注入
severity: 9
level: critical
category: 安全漏洞
tags: [SQL, 注入]
languages: [python, java]
---

## 问题描述
...

## 坏代码 ❌
### 场景名
```python
代码
```

## 好代码 ✅
### 场景名
```python
代码
```

## 检查清单
- [ ] 问题？
  - 提示
```

### 解析步骤

**Step 1: parse_frontmatter()**

```
输入: 整个 .md 文件字符串
正则: ^---\s*\n(.*?)\n---\s*\n
输出:
  frontmatter = {title, severity, level, category, ...}  (字典)
  body = "## 问题描述\n..."  (字符串)
```

**Step 2: extract_examples(body)**

```
输入: body 字符串

Step 2a: 找到 ## 坏代码 和 ## 好代码 之间的内容
正则: ##\s*坏代码.*?\n(.*?)##\s*(好代码|检查清单)

Step 2b: 提取每个 ### 标签 + ```代码```
正则: ###\s*(.+?)\n\s*```\w*\n(.*?)\n\s*```

输出:
  bad_examples = [{"label": "...", "code": "..."}, ...]
  good_examples = [{"label": "...", "code": "..."}, ...]
```

**Step 3: extract_check_points(body)**

```
输入: body 字符串

Step 3a: 找到 ## 检查清单 部分
正则: ##\s*检查清单\s*\n(.*)

Step 3b: 匹配 - [ ] 问题 + 缩进提示
正则: -\s*\[\s*\]\s*(.+?)(?:\n\s+-\s*(.+?))?(?=\n\s*-\s*\[|$)

输出:
  check_points = [{"question": "...", "hint": "..."}, ...]
```

### 两级优先级

```
加载案例时按优先级选择来源：

1. 项目级别: <repo>/.ai-review/cases/*.md  （最高）
2. 无内置默认！找不到就退回通用规则
```

## Git Hook 机制

### pre-commit 脚本

位置: `.git/hooks/pre-commit`

内容: 调用 `python -m commit_ai_guardian audit --repo <路径>`

### 执行逻辑

```bash
git commit -m "xxx"
    │
    ▼
Git 发现 .git/hooks/pre-commit 存在
    │
    ▼
执行脚本
    │
    ├── 脚本返回 0 ──→ commit 成功
    │
    └── 脚本返回非 0 ──→ commit 失败，提示修复或 --no-verify 跳过
```

### 安全机制

- 脚本内含 `HOOK_MARKER` 标识，区分"本工具生成"和"用户自定义"
- 覆盖用户 hook 前自动备份为 `.backup`
- 卸载时恢复备份

### 跳过审核

`--no-verify` 是 Git 原生选项，跳过所有 pre-commit hook：

```bash
git commit --no-verify -m "xxx"   # 绕过 AI 审核，直接提交
```

我们的 hook 脚本在审核失败时会提示这个命令：

```
提示: 使用 git commit --no-verify 跳过 AI 审核（不推荐）
```

适用场景：紧急修复、已知误报、hook 本身出问题时使用。

## API 调用与容错

### 重试策略

```
最多 3 次，指数退避：
  第 1 次失败 → 等 1 秒
  第 2 次失败 → 等 2 秒
  第 3 次失败 → 等 4 秒
  第 3 次仍失败 → 抛异常
```

### 覆盖的错误类型

- `RateLimitError` — API 限流（429）
- `APITimeoutError` — 请求超时
- `APIError` — 服务端错误
- 其他异常 — 网络断开等

### 阻断原则

```
审核发现问题或系统异常 → 返回 passed=False → 阻断 commit

阻断场景：
  - AI 发现 severity >= threshold 的问题 → 阻断
  - API Key 未配置 → 阻断（exit 2）
  - API 调用失败 → passed=False → 阻断
  - JSON 解析失败 → passed=False → 阻断
  - 客户端初始化失败 → passed=False → 阻断
  - 运行时异常 → 阻断

不阻断场景：
  - enabled=false（用户主动禁用）→ exit 0
  - 暂存区没有变更文件 → exit 0
  - 全部文件审核通过 → exit 0
```

## 配置文件

### 位置

```
~/.commit-ai-guardian/config.yaml
```

### 内容

```yaml
api_key: ""                         # AI API 密钥
api_base: "https://api.openai.com/v1"  # API 地址
model: "gpt-4o-mini"                # 模型名称
language: "zh-CN"                   # 审核报告语言
severity_threshold: "warning"       # 阻断级别
cases_repo: ""                      # 远程案例库 Git 地址
max_file_size: 500                  # 最大审核文件大小（KB）
timeout: 60                         # API 超时（秒）
proxy: null                         # HTTP 代理
```

### 加载逻辑

```
load()
    │
    ├── 文件不存在 ──→ 创建默认配置 ──→ 保存 ──→ 返回
    │
    └── 文件存在 ──→ 解析 YAML ──→ 过滤非法字段 ──→ 返回
                       ↑
                  解析失败 ──→ 打印警告 ──→ 使用默认配置
```

### severity_threshold（阻断级别）

控制"什么级别的问题会阻断 git commit"：

| 级别 | 含义 | 阻断条件 |
|------|------|---------|
| `info` | 任何问题都提示 | error/critical 阻断 commit |
| `warning` | warning 及以上提示 | error/critical 阻断 commit |
| `error` | **默认** error 及以上提示 | error/critical 阻断 commit |
| `critical` | 只有 critical 提示 | 只有 critical 阻断 commit |

注意：实际阻断 commit 的只有 `error` 和 `critical` 级别的问题。
`info` 和 `warning` 只会在报告中显示，不会阻止提交。

`critical` 最宽松（只有最严重的问题才阻断），`error` 是默认设置。

## 目录结构

```
ai-review/                          # 项目根
├── src/
│   └── commit_ai_guardian/
│       ├── __init__.py             # 包版本
│       ├── __main__.py             # python -m 入口
│       ├── cli.py                  # CLI 命令定义
│       ├── config.py               # 配置管理
│       ├── hook_installer.py       # Git Hook 安装/卸载
│       ├── diff_collector.py       # Git diff 采集解析
│       ├── file_collector.py       # 文件采集
│       ├── ai_engine.py            # AI 审核引擎
│       ├── result_formatter.py     # 终端报告格式化
│       ├── case_loader.py          # 案例加载器
│       ├── case_validator.py       # 案例格式校验
│       ├── cases_updater.py        # 远程案例更新
│       └── templates/
│           ├── pre-commit-hook-template   # Hook 脚本模板
│           └── case-examples/             # 示例案例
│               ├── sql-injection.md
│               ├── xss.md
│               └── ...
├── pyproject.toml
├── uv.lock
├── README.md
└── TECHNICAL.md                    # 本文件
```

目标仓库中创建的结构：

```
your-code-repo/
├── .ai-review/                     # install 命令创建
│   ├── cases/                      # 启用的案例（用户自己放）
│   └── example/                    # 示例模板（仅参考）
│       ├── sql-injection.md
│       └── ...
└── .git/hooks/pre-commit          # install 命令写入
```
