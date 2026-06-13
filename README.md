# Commit AI Guardian

<p align="center">
  <strong>Git Pre-commit Hook AI 代码审核系统</strong><br>
  每次 commit 前，让 AI 帮你把关代码质量
</p>

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/python-3.8%2B-blue" alt="Python 3.8+"></a>
  <a href="#"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
  <a href="#"><img src="https://img.shields.io/badge/version-0.2.0-orange" alt="Version"></a>
</p>

---

## 目录

- [功能概览](#功能概览)
- [快速开始](#快速开始)
- [安装](#安装)
- [命令参考](#命令参考)
- [配置说明](#配置说明)
- [审核规则](#审核规则)
- [案例驱动审核](#案例驱动审核)
- [日志系统](#日志系统)
- [工作原理](#工作原理)
- [常见问题](#常见问题)

---

## 功能概览

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

## 快速开始

```bash
# 1. 安装
uv tool install git+https://github.com/tingkl/ai-review.git@main

# 2. 进入项目，初始化
cag install

# 3. 配置 API 密钥
cag configure

# 4. 正常提交，AI 自动审核
git add .
git commit -m "feat: add new feature"
```

---

## 安装

### 从 GitHub 安装（推荐）

```bash
uv tool install git+https://github.com/tingkl/ai-review.git@main

# 升级
uv tool upgrade commit-ai-guardian
```

### 从 GitLab 安装（内网）

```bash
uv tool install git+ssh://git@124.223.189.152:7022/gaoq/ai-review.git
```

### 从 PyPI 安装

```bash
uv tool install commit-ai-guardian
```

> `uv tool install` 自动创建隔离环境并把 `cag` 命令链接到 PATH，`pip install` 需要手动管理虚拟环境。用 `uv pip install` 也行，但需要自己激活虚拟环境。

### 项目初始化

```bash
cd your-project
commit-ai-guardian install
```

安装后目录结构：

```
your-project/
├── .ai-review/
│   ├── cases/          # 启用的审核案例
│   ├── example/        # 示例模板
│   ├── prompts/        # Prompt 模板（可自定义）
│   │   ├── system_message.txt          # 主审核 system message
│   │   ├── diff_review.md              # diff 审核 user prompt
│   │   ├── full_file_review.md         # 完整文件审核 user prompt
│   │   ├── system_message_json_fix.txt # JSON 修复 AI system message
│   │   └── json_fix.md                 # JSON 修复 AI user prompt
│   └── config.yaml     # 项目级配置
└── .git/hooks/pre-commit
```

---

## 命令参考

| 命令 | 说明 |
|------|------|
| `cag install` | 安装 pre-commit hook |
| `cag install --force` | 强制重新安装 |
| `cag uninstall` | 卸载 hook |
| `cag audit` | 审核暂存区变更 |
| `cag review -f <文件>` | 审核指定文件 |
| `cag review -d <目录>` | 审核指定目录 |
| `cag configure` | 交互式配置向导 |
| `cag status` | 查看当前配置状态 |
| `cag validate-cases` | 校验案例文件格式 |
| `cag debug-log <ai.log>` | 本地解析 AI 响应日志 |

> `cag` 是 `commit-ai-guardian` 的短别名。

---

## 配置说明

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

### use_cache — 关闭缓存

```yaml
# .ai-review/config.yaml
use_cache: false  # 不检查缓存、不写入缓存，每次强制重新审核
```

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

### case_format — 案例格式化级别

| 级别 | 保留 | 去掉 | token 节省 |
|------|------|------|-----------|
| `default` | 全部 | - | 0% |
| `compact` | 说明 + 坏代码 + 好代码 + 检查点 | 原因 + 后果 | ~35% |
| `minimal` | 坏代码 + 检查点 | 其他全部 | ~55% |

---

## 审核规则

AI 审核只覆盖以下 5 个维度，不在此范围内的问题不报：

1. **Bug 检测**: 逻辑错误、边界条件、资源泄漏、并发问题（不包含空指针）
2. **代码风格**: 命名规范、代码格式、注释质量、代码组织
3. **性能问题**: 算法复杂度、内存泄漏、不必要的计算
4. **最佳实践**: 设计模式、代码复用、错误处理、日志规范
5. **文档完整**: 函数文档、参数说明、复杂逻辑注释

### 明确不报的问题

- 安全漏洞（SQL 注入、XSS 等）—— 普通代码中太常见，误报率高
- 空指针（除非非常明显：显式 null 赋值后使用、已知为 null 的调用链）
- 函数参数的防御性类型检查（typeof、isNaN 等）—— 来源不明的参数视为合法值
- 基于猜测的业务场景推断（金融、医疗等）
- window.location 属性读取（protocol、host 等）—— 正常操作

---

## 案例驱动审核

在 `.ai-review/cases/` 下编写案例，AI 会参照案例检查代码。

### 案例文件格式

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

### 验证案例格式

```bash
cag validate-cases
```

---

## 日志系统

审核过程产生的日志文件存放在 `.ai-review/logs/`，命名使用 MD5 前 7 位：

| 文件 | 说明 |
|------|------|
| `{md5}.ai.log` | 主审核 AI 的完整对话记录（system + user + AI response） |
| `{md5}.json.log` | JSON 修复 AI 的完整对话记录（system + user + AI response） |
| `{md5}.json` | 审核结果缓存文件 |

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

## 工作原理

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

### 阻断条件

- AI 发现 severity >= threshold 的问题
- API Key 未配置、API 调用失败
- JSON 解析失败（含 AI 修复后仍失败）
- 其他运行时异常

不阻断的情况：`enabled=false`、`暂存区无变更`。

临时跳过：`git commit --no-verify`

---

## 设计哲学

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
| 所有异常未处理 | **默认阻断** | 解析失败/修复失败/字段缺失 → `passed=False`，绝不静默放行 |

### 核心原则

1. **让 AI 做填空题（schema），不是作文题（自由文本）**
2. **Prompt 只放 AI 记不住的东西**（业务规则、案例），不放 AI 会自然遵守的东西（JSON 格式）
3. **代码兜底比 prompt 约束可靠 100 倍**
4. **所有异常默认阻断** — 解析失败、修复失败、字段缺失等任何异常都阻断提交，绝不静默放行

---

## 常见问题

### Q: 安装后为什么没有生效？

```bash
ls -la .git/hooks/pre-commit
cag status
# 缺失则重新安装
cag install --force
```

### Q: 如何跳过 AI 审核？

```bash
git commit --no-verify
```

### Q: 支持哪些 AI 模型？

任何兼容 OpenAI API 格式的模型：OpenAI GPT 系列、Azure OpenAI、自部署模型等。

#### Think 输出控制

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

### Q: 如何自定义审核 Prompt？

编辑 `.ai-review/prompts/` 下的模板文件：
- `system_message.txt` — 主审核 system message
- `diff_review.md` — diff 审核 user prompt
- `full_file_review.md` — 完整文件审核 user prompt
- `system_message_json_fix.txt` — JSON 修复 AI system message
- `json_fix.md` — JSON 修复 AI user prompt

### Q: 双 remote 推送（GitLab + GitHub）

```bash
# 分别推
git push origin main   # GitLab
git push github main   # GitHub

# 或配置 all 分组一次推两个
git remote add all git@github.com:tingkl/ai-review.git
git remote set-url --add --push all git@github.com:tingkl/ai-review.git
git remote set-url --add --push all http://124.223.189.152:7080/gaoq/ai-review.git
git push all main
```

---

## Pre-commit Hook 技术实现

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

工具检测到 husky 时，将命令追加到 `.husky/pre-commit`，与 lint-staged 等工具共存：

```bash
# .husky/pre-commit（多命令共存示例）
npx lint-staged                    # 先格式化代码

# === commit-ai-guardian ===       # 工具 marker，用于 uninstall 定位
commit-ai-guardian audit           # 再 AI 审核
EXIT_CODE=$?                       # 保存 exit code
if [ $EXIT_CODE -ne 0 ]; then      # 判断是否阻断
    echo ""
    echo "提示: 使用 git commit --no-verify 跳过 AI 审核（不推荐）"
    exit $EXIT_CODE                # 阻断 commit
fi
# === end commit-ai-guardian ===
```

**两种场景的阻断逻辑完全一致**：都是先存 `EXIT_CODE=$?`，再用 `if [ $EXIT_CODE -ne 0 ]` 判断，最后 `exit $EXIT_CODE` 传递给 Git。

### 为什么不用 `audit || exit $?`

`||` 写法虽然简洁，但 `exit $?` 中的 `$?` 存的是 `||` 左边命令的结果，如果中间有其他命令干扰会不准确。统一用 `EXIT_CODE=$?` + `if` 判断更直观可靠。

### 常见问题：husky 和本工具都安装了，但只执行了一个

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

## 开源协议

MIT License
