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

### 三级优先级

```
加载案例时按优先级选择来源：

1. 项目级别: <repo>/.ai-review/cases/*.md  （最高）
2. 全局级别: ~/.commit-ai-guardian/cases-repo/ （远程 Git 拉取）
3. 无内置默认！找不到就退回通用规则
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

### 容错原则

```
任何环节失败 → 返回 passed=True → 不阻断 commit

具体场景：
  - API Key 未配置 → passed=True, "未配置 API Key"
  - 客户端初始化失败 → passed=True, "客户端未初始化"
  - API 调用失败 → passed=True, "审核失败: ..."
  - JSON 解析失败 → passed=True, "解析失败"
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
