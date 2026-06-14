# Commit AI Guardian — 技术文档

> 面向开发者的系统深度说明文档。涵盖架构设计、数据流、核心机制与实现细节。

---

## 目录

1. [功能概览](#1-功能概览)
2. [系统架构](#2-系统架构)
3. [目录结构](#3-目录结构)
4. [核心数据流](#4-核心数据流)
5. [Git Diff 采集详解](#5-git-diff-采集详解)
6. [Prompt 构建原理](#6-prompt-构建原理)
7. [Prompt 设计要点](#7-prompt-设计要点)
8. [审核规则](#8-审核规则)
9. [案例驱动审核](#9-案例驱动审核)
10. [案例文件解析逻辑](#10-案例文件解析逻辑)
11. [缓存系统](#11-缓存系统)
12. [日志系统](#12-日志系统)
13. [配置文件](#13-配置文件)
14. [Git Hook 机制](#14-git-hook-机制)
15. [Pre-commit Hook 技术实现](#15-pre-commit-hook-技术实现)
16. [API 调用与容错](#16-api-调用与容错)
17. [Think 输出控制](#17-think-输出控制)
18. [设计哲学](#18-设计哲学)

---

## 1. 功能概览

| 特性 | 说明 |
|------|------|
| **自动审核** | `git commit` 前自动触发 AI 代码审核，发现问题阻断提交 |
| **手动审核** | 指定文件或目录随时审核，不依赖 git 流程 |
| **案例驱动** | 自定义"坏代码/好代码"案例，AI 按你的标准检查 |
| **项目级配置** | 每个仓库独立配置规则，团队协作一致 |
| **两级配置** | 全局配置 + 项目配置，项目覆盖全局 |
| **并发审核** | 多文件变更时并行调用 AI，减少等待 |
| **智能缓存** | 审核过的文件自动缓存，内容未变直接复用结果 |
| **缓存可控** | `use_cache: false` 关闭缓存，每次强制重新审核 |
| **JSON 容错** | AI 返回的 JSON 语法错误时，自动调用 AI 修复再解析 |
| **严格阻断** | API 异常、配置缺失、解析失败均阻断 commit |

---

## 2. 系统架构

### 模块依赖图

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

### 完整数据流

```
git commit
    │
    ▼
pre-commit hook
    │
    ▼
获取暂存区 diff
    │
    ▼
缓存检查（use_cache=true 时）
    │ 命中 → 直接返回
    │ 未命中 → 继续
    ▼
加载配置 + 案例
    │
    ▼
AI 审核（并发 4 文件）
    │
    ▼
JSON 解析
    │ 成功 → 提取 issues
    │ 失败 → AI 修复 JSON → 再解析
    ▼
  通过 / 阻断
```

---

## 3. 目录结构

### 源码结构

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
│       ├── prompt_loader.py        # Prompt 模板加载
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

### 目标仓库中创建的结构

```
your-code-repo/
├── .ai-review/                     # install 命令创建
│   ├── cases/                      # 启用的案例（用户自己放）
│   ├── example/                    # 示例模板（仅参考）
│   ├── prompts/                    # Prompt 模板（可自定义）
│   │   ├── system_message.txt
│   │   ├── diff_review.md
│   │   ├── full_file_review.md
│   │   ├── system_message_json_fix.txt
│   │   └── json_fix.md
│   └── config.yaml                 # 项目级配置
└── .git/hooks/pre-commit          # install 命令写入
```

---

## 4. 核心数据流

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
    │        读取 .ai-review/config.yaml（存在则覆盖全局）
    │
    ├── 2. DiffCollector.get_staged_diffs()
    │        执行 git diff --cached
    │        解析 diff 文本 → FileDiff 列表
    │        过滤二进制/大文件/忽略模式
    │
    ├── 3. AIEngine.review_batch()
    │        逐个文件构建 Prompt（含案例、审核维度）
    │        并发调用 OpenAI API（含重试）
    │        解析 JSON 响应 → ReviewResult 列表
    │
    ├── 4. ResultFormatter.format_and_display()
    │        Rich 库渲染终端输出
    │        汇总统计
    │
    └── 5. 判断退出码
             exit 0 → commit 放行
             exit 1 → commit 阻断（发现问题或系统异常）
             exit 2 → commit 阻断（配置异常）
```

### review 命令（文件审核）

```
cag review -f src/main.py
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

---

## 5. Git Diff 采集详解

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

---

## 6. Prompt 构建原理

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
2. 代码风格...
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

---

## 7. Prompt 设计要点

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
- 审核维度说明（Bug/代码风格/性能/最佳实践/文档）
- 空指针检测规则（具体业务规则，不是格式规则）
- 案例参考（`{{cases_text}}`）
- 严重级别定义

**为什么这样分：**
- 模型对 system 的注意力权重更高，格式约束放在这里遵守率更好
- 代码内容每次都不同，放 user 中，避免 system 过长导致 KV cache 失效
- 两边不重复——system 中的 JSON 格式约束不在 user 中重复，节省 token

### 9. 案例格式化级别（case_format）

案例从 Markdown 转为结构化文本时，支持三种级别控制 prompt 长度：

| 级别 | 说明 | 节省 |
|------|------|------|
| `default` | 保留全部字段（说明 + 坏代码 + 好代码 + 原因 + 后果 + 检查点） | 0% |
| `compact` | 精简（去掉原因 + 后果） | ~35% |
| `minimal` | 最小（只留坏代码 + 检查点） | ~55% |

#### 格式化转换说明

案例文件本身是 Markdown（用户友好），`format_cases_for_prompt()` 在发给 AI 前根据 `case_format` 配置决定保留哪些字段：

- `case_format` 是 Config 的配置项，支持全局/项目两级配置
- 非法值自动 fallback 到 `default`
- 转换过程去掉 Markdown 符号（`###`、` ``` `、`☐`），用结构化标识（`[案例N|标题|级别]`、`❌`/`✅`）

> **为什么做这件事**：案例是 prompt 中最大的膨胀来源。10 个案例 Markdown 格式可能 3000+ 字，转为 minimal 后只剩 ~1500 字，显著减少 token 消耗。

---

## 8. 审核规则

### 五个审核维度

AI 审核只覆盖以下 5 个维度，不在此范围内的问题不报：

1. **Bug 检测**: 逻辑错误、边界条件、资源泄漏、并发问题（不包含空指针）
2. **代码风格**: 命名规范、代码格式、注释质量、代码组织
3. **性能问题**: 算法复杂度、内存泄漏、不必要的计算
4. **最佳实践**: 设计模式、代码复用、错误处理、日志规范
5. **文档完整**: 函数文档、参数说明、复杂逻辑注释

### 明确不报的问题

| 类型 | 说明 |
|------|------|
| 安全漏洞（SQL 注入、XSS 等） | 普通代码中太常见，误报率高 |
| 空指针 | 除非非常明显：显式 null 赋值后使用、已知为 null 的调用链 |
| 函数参数的防御性类型检查（typeof、isNaN 等） | 来源不明的参数视为合法值 |
| 基于猜测的业务场景推断（金融、医疗等） | 不做猜测性推断 |
| window.location 属性读取（protocol、host 等） | 正常操作，不误报 |

---

## 9. 案例驱动审核

### 案例文件格式

案例文件使用 **Markdown + YAML frontmatter** 格式，存放在 `.ai-review/cases/` 下：

```markdown
---
title: "SQL 注入"
severity: 9
level: critical
category: "安全漏洞"
tags: [SQL]
languages: [python, java]
---

## 问题描述
直接拼接用户输入到 SQL 语句。

## 坏代码
```python
query = f"SELECT * FROM users WHERE id = {user_id}"
```

## 好代码
```python
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
```

## 检查清单
- [ ] 是否有字符串拼接构建 SQL
```

### Language 筛选机制

案例通过 `languages` 字段控制适用的编程语言，不匹配当前文件语言的案例不会进入 prompt。

```yaml
---
# 方式1：指定语言——只给 Python 和 Java 文件使用此案例
languages: [python, java]

# 方式2：空数组或不写——适用于所有语言
languages: []
---
```

**匹配规则：**

| languages 字段 | 行为 |
|---------------|------|
| `[]`（空数组）或未指定 | 所有语言通用 |
| `[python, java]` | 只匹配 `python` 和 `java` 文件 |
| 含大写 | 大小写不敏感（`Python` == `python`） |

**原理**：审核时从文件扩展名推断语言（如 `.py` → `python`），调用 `get_cases_for_language(language)` 只加载匹配的案例，不匹配的自动过滤。无法识别语言的文件使用所有案例。

### 案例格式化级别

| 级别 | 保留 | 去掉 | token 节省 |
|------|------|------|-----------|
| `default` | 全部 | - | 0% |
| `compact` | 说明 + 坏代码 + 好代码 + 检查点 | 原因 + 后果 | ~35% |
| `minimal` | 坏代码 + 检查点 | 其他全部 | ~55% |

### 验证命令

```bash
cag validate-cases
```

---

## 10. 案例文件解析逻辑

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

---

## 11. 缓存系统

### MD5 的两种用途

每个文件审核前计算 MD5，有两个不同的用途，受 `use_cache` 配置影响：

| 用途 | 内容 | 长度 | use_cache=false 时的行为 | 说明 |
|------|------|------|-------------------------|------|
| **缓存 key** | 文件内容（full 模式）或 diff 内容（diff 模式） | 32 位完整 MD5 | 不检查缓存、不写入缓存 | 内容不变 → MD5 不变 → 直接复用上次结果 |
| **日志文件名** | 同上 | 前 7 位 | **始终使用**，不受影响 | 日志始终记录，方便调试 |

也就是说，关闭缓存只跳过缓存检查/写入，日志文件照常生成。

### 关闭缓存

```yaml
# .ai-review/config.yaml
use_cache: false  # 不检查缓存、不写入缓存，每次强制重新审核
```

---

## 12. 日志系统

### 日志文件

审核过程产生的日志文件存放在 `.ai-review/logs/`，命名使用 MD5 前 7 位：

| 文件 | 说明 |
|------|------|
| `{md5}.ai.log` | 主审核 AI 的完整对话记录（system + user + AI response） |
| `{md5}.json.log` | JSON 修复 AI 的完整对话记录（system + user + AI response） |
| `{md5}.json` | 审核结果缓存文件（use_cache=false 时不生成） |

### ai.log 格式

```
# AI Response Log
# 文件: src/main.py
# 时间: 2026-06-12 10:30:00
============================================================
--- SYSTEM MESSAGE ---
============================================================
[system message 内容]
============================================================
--- USER MESSAGE ---
============================================================
[user prompt 内容]
============================================================
--- AI RESPONSE ---
============================================================
<result>{"summary":"..."}</result>
```

### 调试日志

```bash
# 本地解析 ai.log，不调用 AI，不花钱
cag debug-log .ai-review/logs/abc1234.ai.log
```

---

## 13. 配置文件

### 两级配置体系

| 级别 | 路径 | 作用 |
|------|------|------|
| 全局 | `~/.commit-ai-guardian/config.yaml` | 默认基准配置 |
| 项目 | `.ai-review/config.yaml` | 项目专属规则，覆盖全局 |

### 配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `api_key` | AI API 密钥 | `""` |
| `api_base` | API 地址 | `https://api.openai.com/v1` |
| `model` | 模型名称 | `gpt-4o-mini` |
| `language` | 审核语言 | `zh-CN` |
| `enabled` | 是否启用 | `true` |
| `severity_threshold` | 阻断级别 | `warning` |
| `diff_mode` | 审核模式 (`full`/`diff`) | `full` |
| `max_tokens` | AI 最大返回 token 数 | `4096` |
| `max_file_size` | 最大文件大小 (KB) | `500` |
| `timeout` | API 超时 (秒) | `60` |
| `proxy` | HTTP 代理 | `null` |
| `cache_ttl` | 缓存存活时间 | `1d` |
| `log_ttl` | 日志存活时间 | `1h` |
| `use_cache` | 是否使用缓存 | `true` |
| `include_patterns` | 审核目录/文件 (glob) | `["*"]` |
| `ignore_patterns` | 忽略的文件模式 | 见默认列表 |
| `case_format` | 案例级别 (`default`/`compact`/`minimal`) | `default` |

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
| `error` | error 及以上提示 | error/critical 阻断 commit |
| `critical` | 只有 critical 提示 | 只有 critical 阻断 commit |

注意：实际阻断 commit 的只有 `error` 和 `critical` 级别的问题。`info` 和 `warning` 只会在报告中显示，不会阻止提交。

### include_patterns — 指定审核范围

支持 glob 通配符，包括 `**` 递归匹配。

```yaml
# 只审核 src/ 下的 Python 和 Vue 文件
include_patterns:
  - "src/**/*.py"
  - "src/**/*.vue"

# 审核多个指定目录
include_patterns:
  - "frontend/**"
  - "backend/**"
```

---

## 14. Git Hook 机制

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

适用场景：紧急修复、已知误报、hook 本身出问题时使用。

---

## 15. Pre-commit Hook 技术实现

### 阻断 commit 的原理

Git 的 pre-commit hook 是一个脚本，在 `git commit` 执行前运行。**脚本返回非 0 的 exit code，Git 就会阻断 commit**。利用这个机制，工具在 hook 中调用 `commit-ai-guardian audit`，根据审核结果返回不同的 exit code：

| Exit Code | 含义 | Git 行为 |
|-----------|------|---------|
| 0 | 审核通过 或 无变更 | 放行 commit |
| 1 | 发现问题，阻断提交 | 阻断 commit |
| 2 | 配置异常（如 API Key 未设置） | 阻断 commit |
| 其他 | 运行时异常 | 阻断 commit |

### 两种安装场景

#### 场景 A：无 husky（原生 hook）

安装位置：`.git/hooks/pre-commit`

```bash
#!/bin/bash
# ... 省略变量设置 ...

# 运行 AI 审核
commit-ai-guardian audit --repo "$REPO_ROOT"

# 保存 exit code（关键步骤，必须立即保存）
EXIT_CODE=$?

# 判断审核结果
if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "提示: 使用 git commit --no-verify 跳过 AI 审核（不推荐）"
    exit $EXIT_CODE   # 返回非 0，Git 阻断 commit
fi

exit 0  # 返回 0，Git 放行 commit
```

**关键点**：`EXIT_CODE=$?` 必须在 `commit-ai-guardian audit` 之后**立即**执行，因为 `$?` 只表示上一个命令的返回值。

#### 场景 B：有 husky v9+（兼容模式）

husky v9+ 设置 `core.hooksPath = .husky/_`，此时 Git 不再执行 `.git/hooks/pre-commit`，而是执行 `.husky/_/pre-commit`（husky 的入口脚本），该脚本会调用 `.husky/pre-commit`。

工具检测到 husky 时，将命令追加到 `.husky/pre-commit`，与 lint-staged 等工具共存。

### lint-staged 共存

**lint-staged 和 commit-ai-guardian 的 exit code 设计：**

| 工具 | Exit Code | 含义 | 触发条件 |
|------|-----------|------|---------|
| **lint-staged** | 0 | 所有文件 lint 通过 | eslint/prettier 全部成功 |
| | 1 | 有文件 lint 失败 | eslint 报错或 prettier 格式化失败 |
| **commit-ai-guardian** | 0 | 审核通过或无变更 | AI 认为代码没问题，或暂存区无变更 |
| | 1 | 发现问题，阻断提交 | AI 发现 severity >= threshold 的问题 |
| | 2 | 配置异常 | API Key 未设置、模型不可达、JSON 解析失败等 |
| | 130 | 用户取消 | Ctrl+C 中断 |

两个工具都遵循**"非 0 即阻断"**的约定，Git 收到非 0 exit code 就会停止 commit。

**commit-ai-guardian 返回 exit code 的代码（`cli.py`）：**

```python
# cli.py audit 命令的 exit code 逻辑

# exit 0 —— 审核已禁用，跳过
if not config.enabled:
    sys.exit(0)

# exit 2 —— API Key 未配置
if not config.api_key:
    sys.exit(2)

# exit 0 —— 暂存区无变更
if not file_diffs:
    sys.exit(0)

# exit 1 —— 系统异常（JSON解析失败/API异常等），阻断commit
if has_system_error:
    sys.exit(1)

# exit 1 —— 发现问题，阻断 commit
if has_blocking_issue:
    sys.exit(1)

# exit 0 —— 全部通过，放行
sys.exit(0)

# exit 2 —— 运行时异常（RuntimeError）
except RuntimeError:
    sys.exit(2)

# exit 130 —— 用户取消（Ctrl+C）
except KeyboardInterrupt:
    sys.exit(130)
```

lint-staged 的 `.husky/pre-commit`（完整版，lint-staged 和 AI 审核共存）：

```bash
#!/bin/sh

# 第1步：lint-staged（格式化代码 + 检查）
npx lint-staged
LINT_EXIT=$?                          # 保存 exit code（关键步骤）
if [ $LINT_EXIT -ne 0 ]; then       # lint 失败 → 阻断 commit
    echo "lint-staged 检查未通过"
    exit $LINT_EXIT                 # 把 lint-staged 的 exit code 传给 Git
fi

# === commit-ai-guardian ===
# 第2步：AI 审核
commit-ai-guardian audit
AUDIT_EXIT=$?                         # 保存 exit code（关键步骤）
if [ $AUDIT_EXIT -ne 0 ]; then      # 审核失败 → 阻断 commit
    echo ""
    echo "提示: 使用 git commit --no-verify 跳过 AI 审核（不推荐）"
    exit $AUDIT_EXIT                # 把 cag 的 exit code 传给 Git
fi
# === end commit-ai-guardian ===
```

### 为什么必须立即保存 `$?`

```bash
npx lint-staged
LINT_EXIT=$?           # ← 必须在下一行立即保存，因为 $? 只表示上一个命令

# 如果中间加了 echo 等其他命令，$? 就被覆盖了
npx lint-staged
echo "lint 完成"       # ← 这行会改变 $? 为 0
echo $?                # ← 输出 0（echo 的 exit code），不是 lint-staged 的
```

**和 lint-staged 的对比：**

lint-staged 的 `.husky/pre-commit` 是简化版（只有一行命令）：
```bash
#!/bin/sh
. "$(dirname "$0")/_/husky.sh"

npx lint-staged        # 最后一行命令，exit code 直接返回给 Git
```

lint-staged 没有显式的 `if` 判断，是因为 `npx lint-staged` 是脚本里**最后一行命令**，它的 exit code 直接成为整个脚本的返回值。但如果后面追加了其他命令（如本工具），lint-staged 的 exit code 就**不会自动返回给 Git 了**，必须显式保存和判断。

**三个关键步骤缺一不可**：
1. `npx lint-staged` — 运行命令
2. `LINT_EXIT=$?` — **立即**保存 exit code
3. `if [ $LINT_EXIT -ne 0 ]; then exit $LINT_EXIT; fi` — 判断是否阻断

### 为什么不用 `audit || exit $?`

`||` 写法虽然简洁，但 `exit $?` 中的 `$?` 存的是 `||` 左边命令的结果，如果中间有其他命令干扰会不准确。统一用 `EXIT_CODE=$?` + `if` 判断更直观可靠。

### husky 常见问题

**问题：husky 和本工具都安装了，但只执行了一个**

husky v9+ 设置 `core.hooksPath = .husky/_` 后，Git 完全忽略 `.git/hooks/` 目录。如果之前用本工具安装过原生 hook，它还在 `.git/hooks/pre-commit` 里，但不会被执行。

**解决方案**：
```bash
# 检测当前生效的 hooks 目录
git config core.hooksPath

# 如果输出 .husky/_ 或 .husky
# 说明 husky 在控制，本工具会自动安装到 .husky/pre-commit

# 如果输出为空
# 说明是原生 hook，本工具安装到 .git/hooks/pre-commit
```

---

## 16. API 调用与容错

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

### 阻断条件（双重检查机制）

```
审核发现问题或系统异常 → 返回 passed=False → 阻断 commit
```

**双重检查：**

1. **AI 发现问题**：`issue.severity >= severity_threshold`（如 warning/error/critical）
2. **系统异常兜底**：`result.passed = False` 时一律阻断（无论 issues 是否为空）
   - JSON 解析失败（含 AI 修复后仍失败）
   - API 调用超时、限流、网络异常
   - 并发执行异常
   - 字段缺失/类型错误等 schema 校验失败

**阻断场景：**
- AI 发现 severity >= threshold 的问题 → 阻断
- API Key 未配置 → 阻断（exit 2）
- API 调用失败 → passed=False → 阻断
- JSON 解析失败 → passed=False → 阻断
- 客户端初始化失败 → passed=False → 阻断
- 运行时异常 → 阻断

**不阻断场景：**
- `enabled=false`（用户主动禁用）→ exit 0
- 暂存区没有变更文件 → exit 0
- 全部文件审核通过 → exit 0

临时跳过：`git commit --no-verify`

---

## 17. Think 输出控制

工具会根据配置的 `model` 名称**自动**向 API 传入禁用 think 的参数，无需手动配置：

| 模型厂商 | 匹配关键字 | 传入参数 | 状态 |
|---------|-----------|---------|------|
| DeepSeek | `deepseek` | `enable_thinking: false` | ✅ 已验证 |
| MiniMax | `minimax` / `abab` | — | ⏳ 待验证（格式不确定） |
| Moonshot / Kimi | `moonshot` / `kimi` | — | ⏳ 待验证 |
| 通义千问 (Qwen) | `qwen` / `qwq` | — | ⏳ 待验证 |
| 智谱 (GLM) | `glm` / `chatglm` | — | ⏳ 待验证 |
| 腾讯混元 | `hunyuan` | — | ⏳ 待验证 |
| 字节豆包 | `doubao` | — | ⏳ 待验证 |
| 零一万物 (Yi) | `yi-` 开头 | — | ⏳ 待验证 |
| GPT / Claude | 以上都不匹配 | 不传额外参数 | ✅ 默认不输出 think |

**注意**：非 DeepSeek 模型的 `thinking` 参数格式不确定（可能是对象 `{"type": "disabled"}` 而非 boolean），直接传入 `thinking: false` 会导致 API 400 错误。如需适配其他模型，请先确认其 API 的 thinking 参数格式，再修改源码中 `_get_disable_thinking_params()` 方法。

---

## 18. 设计哲学

> **AI 写代码很强，通用对话不行。用工程手段弥补，而不是 prompt 工程。**

### 为什么不用 prompt 约束？

prompt 约束 AI 的效果有限：
- AI 会遗忘长 prompt 中的规则
- AI 对"不要 xxx"的遵守率远低于"必须 xxx"
- 不同模型对 prompt 的理解差异大

### 工程兜底策略

| AI 的短板 | 工程手段 | 说明 |
|-----------|---------|------|
| 输出格式不稳定 | **JSON Schema 硬约束** | `strict: true` + `additionalProperties: false`，字段名和类型强制校验 |
| 字段名乱用（description/fix_suggestion） | **`additionalProperties: false`** | schema 直接拒绝非标准字段 |
| message 为空 | **代码层必填校验** | `_validate_review_schema()` 检查 message 非空，缺失触发 JSON 修复 |
| 输出 think 挤占 token | **`enable_thinking: false`** | DeepSeek 等模型 API 参数禁用，不是 prompt 约束 |
| 不遵守 `<result>` 标签 | **多层提取降级** | `<result>` → `{...}` → 整段文本，层层兜底 |
| JSON 被截断 | **截断检测** | 过滤 think 后检查 JSON 完整性 |
| 重复犯同样格式错误 | **Schema 校验 + 错误反馈** | 告诉 AI 具体哪个字段错了，针对性修复 |
| prompt 太长导致遗忘 | **持续精简** | 去掉 schema/代码已约束的内容，只留 AI 真正需要记住的 |
| 阻断覆盖不全 | **双重检查 + 默认阻断** | cli.py 同时检查 `result.passed`（系统异常）和 `issue.severity`（业务问题），并发异常也返回 `passed=False` |

### 核心原则

1. **让 AI 做填空题（schema），不是作文题（自由文本）**
2. **Prompt 只放 AI 记不住的东西**（业务规则、案例），不放 AI 会自然遵守的东西（JSON 格式）
3. **代码兜底比 prompt 约束可靠 100 倍**
4. **所有异常默认阻断** — 解析失败、修复失败、字段缺失等任何异常都阻断提交，绝不静默放行
