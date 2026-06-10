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
| 🛡️ **容错设计** | 任何环节失败都不阻断 commit，绝不耽误提交 |

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

默认情况下，工具会审核所有变更文件。你可以通过 `include_patterns` 配置**只审核指定目录或文件**，支持 glob 通配符语法。

#### 在 `.ai-review/config.yaml` 中配置

```yaml
# 只审核 src/ 目录下的变更
include_patterns:
  - "src/**"

# 只审核特定模块
include_patterns:
  - "src/core/**"
  - "src/utils/**"

# 只审核特定类型的文件
include_patterns:
  - "**/*.py"
  - "**/*.js"

# 审核多个指定目录
include_patterns:
  - "frontend/**"
  - "backend/**"
```

#### 常用模式示例

| 模式 | 说明 |
|------|------|
| `["*"]` | 审核所有文件（默认） |
| `["src/**"]` | 只审核 `src/` 目录下所有文件 |
| `["**/*.py"]` | 只审核所有 Python 文件 |
| `["app/**", "lib/**"]` | 只审核 `app/` 和 `lib/` 两个目录 |
| `["packages/*/src/**"]` | 审核 `packages/` 下各包的 `src/` 目录 |

> **注意**：`include_patterns` 与 `ignore_patterns` 是**叠加关系**——先匹配 `include_patterns` 的目录，再排除 `ignore_patterns` 的内容。

#### 典型场景

**场景 1：前后端分离项目，只审核后端代码**

```yaml
# .ai-review/config.yaml
include_patterns:
  - "backend/**"
  - "server/**"
```

**场景 2：Monorepo 项目，只审核指定包**

```yaml
# .ai-review/config.yaml
include_patterns:
  - "packages/core/**"
  - "packages/shared/**"
```

**场景 3：混合项目，只审核源码目录**

```yaml
# .ai-review/config.yaml
include_patterns:
  - "src/**"
  - "lib/**"
ignore_patterns:
  - "*.test.js"
  - "*.spec.py"
  - "**/__tests__/**"
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

### 容错原则

> **任何环节失败都不阻断 commit。**
> 
> 如果 API 调用超时、配置缺失、或任何异常发生，工具会打印警告并允许提交继续进行，绝不会成为你的阻碍。

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
