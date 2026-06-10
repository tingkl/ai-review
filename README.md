# 🤖 Commit AI Guardian

<p align="center">
  <strong>Git Pre-commit Hook AI 代码审核系统</strong><br>
  每次 commit 前，让 AI 帮你把关代码质量
</p>

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/build-passing-brightgreen" alt="Build Status"></a>
  <a href="#"><img src="https://img.shields.io/badge/coverage-85%25-green" alt="Coverage"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9+"></a>
  <a href="#"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
  <a href="#"><img src="https://img.shields.io/badge/pypi-v0.1.0-orange" alt="PyPI"></a>
</p>

---

## 目录

- [功能概览](#功能概览)
- [快速开始](#快速开始)
- [安装](#安装)
- [命令参考](#命令参考)
- [配置说明](#配置说明)
- [案例驱动审核](#案例驱动审核)
- [工作原理](#工作原理)
- [常见问题](#常见问题)
- [开源协议](#开源协议)

---

## 功能概览

| 特性 | 说明 |
|------|------|
| 🔍 **自动审核** | `git commit` 前自动触发 AI 代码审核，发现问题阻断提交 |
| 📁 **手动审核** | 指定文件或目录随时审核，不依赖 git 流程 |
| 📚 **案例驱动** | 自定义"坏代码/好代码"案例，AI 按你的标准检查 |
| ⚙️ **项目级配置** | 每个仓库独立配置规则，团队协作一致 |
| 🏠 **两级配置** | 全局配置 + 项目配置，项目覆盖全局 |
| ⚡ **并发审核** | 多文件变更时并行调用 AI，减少等待 |
| 💾 **智能缓存** | 审核过的文件自动缓存，内容未变直接复用结果 |
| 🛡️ **严格阻断** | API 异常、配置缺失、解析失败均阻断 commit，确保问题不被遗漏 |

---

## 快速开始

```bash
# 1. 安装工具
uv tool install git+ssh://git@124.223.189.152:7022/tingkl/ai-review.git

# 2. 进入你的项目，初始化
commit-ai-guardian install

# 3. 配置 API 密钥
commit-ai-guardian configure

# 4. 正常提交代码，AI 自动审核

git add .
git commit -m "feat: add new feature"
# AI 审核通过 → 提交成功
# AI 发现问题 → 阻断提交，输出修改建议
```

---

## 安装

### 方式一：uv 安装（推荐）

```bash
uv tool install git+ssh://git@124.223.189.152:7022/tingkl/ai-review.git
```

### 方式二：pip 安装（PyPI）

```bash
pip install commit-ai-guardian
```

### 方式三：源码安装

```bash
git clone ssh://git@124.223.189.152:7022/tingkl/ai-review.git
cd ai-review
pip install -e .
```

### 项目初始化

```bash
# 进入目标项目目录
cd your-project

# 安装 hook 并创建配置目录
commit-ai-guardian install
```

安装后目录结构：

```
your-project/
├── .ai-review/
│   ├── cases/          # 启用的审核案例
│   ├── example/        # 示例模板
│   ├── prompts/        # Prompt 模板（可自定义）
│   └── config.yaml     # 项目级配置
└── .git/hooks/pre-commit  # 自动安装的 hook 脚本
```

---

## 命令参考

| 命令 | 说明 |
|------|------|
| `commit-ai-guardian install` | 安装 pre-commit hook，创建 `.ai-review/` 目录 |
| `commit-ai-guardian install --force` | 强制重新安装，补全缺失配置 |
| `commit-ai-guardian uninstall` | 卸载 hook |
| `commit-ai-guardian audit` | 审核暂存区变更（hook 自动调用） |
| `commit-ai-guardian review -f <文件>` | 审核指定文件 |
| `commit-ai-guardian review -d <目录>` | 审核指定目录 |
| `commit-ai-guardian configure` | 交互式配置向导 |
| `commit-ai-guardian status` | 查看当前配置状态 |
| `commit-ai-guardian validate-cases` | 校验案例文件格式 |
| `commit-ai-guardian debug-log <ai.log>` | 调试 AI 响应日志（本地解析，不调用 AI） |

---

## 配置说明

### 两级配置体系

**全局配置** `~/.commit-ai-guardian/config.yaml` —— 默认基准配置

**项目配置** `.ai-review/config.yaml` —— 项目专属规则，优先级高于全局

### 配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `api_key` | AI API 密钥 | `""` |
| `api_base` | API 地址 | `https://api.openai.com/v1` |
| `model` | 模型名称 | `gpt-4o-mini` |
| `language` | 审核语言 | `zh-CN` |
| `severity_threshold` | 阻断级别（`critical`/`warning`/`info`） | `warning` |
| `diff_mode` | 审核模式（`full` 全文件 / `diff` 仅变更） | `full` |
| `max_tokens` | AI 最大返回 token 数 | `4096` |
| `cache_ttl` | 缓存存活时间 | `1d` |
| `include_patterns` | 指定要审核的目录/文件（glob 模式） | `["*"]` |
| `ignore_patterns` | 忽略的文件模式 | 见默认列表 |

### 快速配置

```bash
# 交互式配置向导
commit-ai-guardian configure

# 查看当前状态
commit-ai-guardian status
```

---

### 指定审核目录（include_patterns）

默认审核所有变更文件。通过 `include_patterns` 配置**只审核指定目录或文件类型**，支持 glob 通配符（含 `**` 递归匹配）。

#### 通配符说明

| 通配符 | 含义 | 示例 |
|--------|------|------|
| `*` | 匹配任意字符（不含 `/`） | `*.py` 匹配 `main.py` |
| `**` | 递归匹配任意层目录（含 0 层） | `src/**/*.py` 匹配 `src/main.py` 和 `src/a/b/main.py` |
| `?` | 匹配单个字符 | `test_?.py` 匹配 `test_a.py` |

> **重要**：`**` 是递归匹配，可以跨任意层目录。`src/**/*.py` 匹配 `src/` 下所有 `.py` 文件，但不会匹配 `mcn/src/main.py`（要求以 `src/` 开头）。要匹配任意位置的 `src/`，用 `**/src/**/*.py`。

#### 配置示例

```yaml
# .ai-review/config.yaml

# 只审核 src/ 下的 Python 文件（含子目录）
include_patterns:
  - "src/**/*.py"

# 审核 src/ 下一级子目录的 Python 文件（不含孙目录）
include_patterns:
  - "src/*/*.py"

# 审核多个后缀
include_patterns:
  - "**/*.py"
  - "**/*.js"
  - "**/*.vue"

# 审核多个指定目录
include_patterns:
  - "frontend/**"
  - "backend/**"

# 匹配任意位置的 src/ 目录（如 mcn/src/、packages/core/src/）
include_patterns:
  - "**/src/**/*.py"
```

#### include_patterns + ignore_patterns 配合使用

两者是**叠加关系**：先匹配 `include_patterns` 的白名单，再排除 `ignore_patterns` 的内容。

```yaml
# .ai-review/config.yaml
# 审核 src/ 下的 Python 文件，但排除测试和废弃代码
include_patterns:
  - "src/**/*.py"
ignore_patterns:
  - "**/test/**"
  - "**/tests/**"
  - "**/deprecated/**"
  - "**/__pycache__/**"
```

#### 典型场景

**场景 1：前后端分离，只审核后端**

```yaml
include_patterns:
  - "backend/**"
  - "server/**"
```

**场景 2：Monorepo，只审核指定包**

```yaml
include_patterns:
  - "packages/core/**"
  - "packages/shared/**"
```

**场景 3：按技术栈分类审核**

```yaml
# Python 项目
include_patterns:
  - "**/*.py"

# Vue 前端项目
include_patterns:
  - "src/**/*.vue"
  - "src/**/*.js"
  - "src/**/*.ts"

# Java 后端项目
include_patterns:
  - "src/main/**/*.java"
```

---

### 调试 AI 响应（debug-log）

无需 API Key，不花钱，本地解析 AI 响应文件看结果。

```bash
# 基本用法
commit-ai-guardian debug-log ai.log

# 指定模拟的文件名（展示用）
commit-ai-guardian debug-log ai.log --filename src/main.py
```

**使用场景：**
- 线上 JSON 解析失败，本地排查 `<think>` 标签、截断、格式错误
- 调整展示格式后验证效果
- 开发新功能时mock AI响应

**ai.log 获取方式：**

```bash
# 方式1：从日志目录复制
cp .ai-review/logs/xxx.ai.log ~/debug.ai.log

# 方式2：手动保存 AI 的原始响应到文件
echo 'AI返回的原始文本...' > ai.log
```

---

## 案例驱动审核

Commit AI Guardian 的核心设计理念是**案例驱动**。你可以在 `.ai-review/cases/` 下编写案例，AI 会参照这些案例来检查代码。

### 案例文件格式

案例使用 **Markdown + YAML frontmatter** 格式：

```markdown
---
title: "SQL 注入"
severity: 9
level: critical
category: "安全漏洞"
tags: [SQL, 注入]
languages: [python, java]
---

## 问题描述
直接拼接用户输入到 SQL 语句，存在 SQL 注入风险。

## 坏代码

### 场景1
```python
query = f"SELECT * FROM users WHERE id = {user_id}"
```

## 好代码

### 场景1
```python
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
```

## 检查清单
- [ ] 是否有字符串拼接构建 SQL
  - 使用参数化查询替代字符串拼接
```

### 案例字段说明

| 字段 | 说明 |
|------|------|
| `title` | 案例标题 |
| `severity` | 严重程度（1-10） |
| `level` | 阻断级别：`critical` / `warning` / `info` |
| `category` | 分类名称 |
| `tags` | 标签列表 |
| `languages` | 适用的编程语言 |

### 验证案例格式

```bash
commit-ai-guardian validate-cases
```

---

## 工作原理

```
git commit
    │
    ▼
┌─────────────────┐
│  pre-commit hook │  ← 自动触发
│  (commit-ai-guardian audit)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  获取暂存区 diff  │
│  (git diff --cached)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  缓存检查         │  ← 已审核且未变更 → 直接返回
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  加载项目配置     │  ← .ai-review/config.yaml
│  加载审核案例     │  ← .ai-review/cases/
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  AI 审核（并发）  │  ← 调用 LLM API
│  对比案例检查代码 │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
 通过 ✓     阻断 ✗
    │         │
    ▼         ▼
 提交成功   输出修改建议
           用户修改后重新提交
```

### 阻断原则

> **审核发现问题或系统异常时阻断 commit，确保代码质量。**
>
> 以下情况会阻断提交：
> - AI 发现 severity >= threshold 的问题
> - API Key 未配置
> - API 调用失败、JSON 解析失败
> - 其他运行时异常
>
> 只有以下情况不阻断：enabled=false（主动禁用）、暂存区无变更。

需要临时跳过审核？使用：

```bash
git commit --no-verify
```

---

## 常见问题

### Q: 安装后为什么没有生效？

确认 hook 已正确安装：

```bash
ls -la .git/hooks/pre-commit
commit-ai-guardian status
```

如果缺失，重新安装：

```bash
commit-ai-guardian install --force
```

### Q: 如何跳过 AI 审核？

```bash
git commit --no-verify
```

### Q: 支持哪些 AI 模型？

任何兼容 OpenAI API 格式的模型均可，包括但不限于：

- OpenAI: `gpt-4o`, `gpt-4o-mini`
- 自定义: 填写 `api_base` 指向你的 API 网关

### Q: 项目配置和全局配置如何共存？

项目配置 `.ai-review/config.yaml` 会**覆盖**全局配置 `~/.commit-ai-guardian/config.yaml` 的同名项。建议：

- **全局配置**：放 API 密钥、模型等通用项
- **项目配置**：放 severity_threshold、language 等项目专属规则

### Q: 缓存文件存在哪里？

缓存存储在全局配置目录下，默认 TTL 为 1 天。可通过 `cache_ttl` 配置项调整。

### Q: 如何自定义审核 Prompt？

编辑 `.ai-review/prompts/` 目录下的模板文件即可。项目初始化时会自动创建默认模板。

---

## 开源协议

[MIT License](LICENSE)

---

<p align="center">
  Made with ❤️ by tingkl
</p>
