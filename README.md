# Commit AI Guardian

基于 AI 的 Git pre-commit 代码审查工具，在每次提交前自动拦截代码风险，守护代码质量。

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)
[![PyPI](https://img.shields.io/pypi/v/commit-ai-guardian)](https://pypi.org/project/commit-ai-guardian/)

> **📚 学习笔记**：[STUDY.md](STUDY.md) — 设计原理与常见问题解答（适合初学者）  
> **🔧 技术细节**：[TECHNICAL.md](TECHNICAL.md) — 架构设计、实现原理、Prompt 工程等（适合开发者）

---

## 目录

- [安装与升级](#安装与升级)
- [项目初始化](#项目初始化)
- [配置](#配置)
- [命令参考](#命令参考)
- [使用技巧](#使用技巧)
- [常见问题](#常见问题)
- [License](#license)

---

## 安装与升级

### 安装

#### 从 PyPI 安装（推荐）

```bash
uv tool install commit-ai-guardian
```

#### 从 GitHub 安装

```bash
uv tool install git+https://github.com/tingkl/ai-review.git
```

#### 从 GitLab 安装（公司内部）

```bash
uv tool install git+ssh://git@124.223.189.152:7022/gaoq/ai-review.git
```

### 三种方式对比

| | PyPI | GitHub | GitLab |
|---|---|---|---|
| 安装源 | 公开包仓库 | 公开 GitHub | 内部 GitLab |
| 协议 | HTTPS | HTTPS | SSH |
| 代码版本 | 发布的稳定版 | 最新 main 分支 | 最新 main 分支 |
| 适用场景 | 普通用户、生产环境 | 外部开发者贡献 | 公司内部开发 |
| 当前状态 | ✅ **推荐** | ✅ 可用 | ✅ 可用 |

### 升级

无论通过哪种方式安装，升级命令都相同（uv 内部自动追踪安装来源）：

```bash
# 方式一：使用 uv（推荐）
uv tool upgrade commit-ai-guardian

# 方式二：使用封装命令
# cag upgrade

# 方式三：使用完整 Git URL（GitLab 安装时）
# uv tool upgrade git+ssh://git@124.223.189.152:7022/gaoq/ai-review.git
```

**本地开发模式**（修改源码后重装）：

```bash
uv pip install --reinstall -e .
```

# 升级
uv tool upgrade commit-ai-guardian
```

**适用场景**：
- 普通用户安装稳定版本
- 生产环境部署（固定版本，经过充分测试）
- 没有内网 GitLab 访问权限

**特点**：
- 从 PyPI 下载预发布的稳定版本
- 不需要 SSH key，公开网络可安装
- 版本固定，升级可控

---

## 项目初始化

进入任意 Git 仓库，运行：

```bash
cag install
```

**`--force` 选项**：已安装过或存在其他 hook 时强制覆盖

| 场景 | `cag install` | `cag install --force` |
|------|--------------|----------------------|
| 全新安装 | ✅ 正常安装 | ✅ 正常安装 |
| 已安装过（有 cag marker） | ⚠️ 提示已安装，不覆盖 | ✅ 去掉旧的，重新安装 |
| 有其他自定义 hook（如 lint-staged） | ❌ 报错，不覆盖 | ✅ 备份原 hook，覆盖安装 |
| config.yaml 补全新字段 | ❌ 不补全 | ✅ 自动补全缺失字段 |

**如何判断"有其他 hook"**：

cag 在 hook 文件中写入特定的 marker 标记来识别：

| hook 文件 | cag 的 marker 标记 |
|-----------|-------------------|
| `.git/hooks/pre-commit` | `# === commit-ai-guardian ===` |
| `.husky/pre-commit` | `# === commit-ai-guardian ===` |

判断逻辑：文件存在但 **不含上述 marker** → 视为"有其他自定义 hook"（如 lint-staged、husky 默认模板、用户手写脚本等）。

此命令会在当前项目中创建以下结构：

| 文件/目录 | 说明 |
|-----------|------|
| `.git/hooks/pre-commit` | Git pre-commit 钩子脚本 |
| `.ai-review/config.yaml` | 项目级配置文件 |
| `.ai-review/prompts/` | 自定义审核规则模板目录 |
| `.ai-review/cases/` | 项目案例库目录 |

**备份命名规则**：`{原文件名}.backup`

| 被覆盖的文件 | 备份路径 |
|-------------|---------|
| `.git/hooks/pre-commit` | `.git/hooks/pre-commit.backup` |
| `.husky/pre-commit` | `.husky/pre-commit.backup` |
| `.ai-review/prompts/{file}` | `.ai-review/prompts/{file}.backup` |

**prompts 覆盖规则**：

| 场景 | 操作 |
|------|------|
| 文件不存在 | 直接写入 |
| 文件存在，**内容一样** | **跳过** |
| 文件存在，**内容不一样** | 备份 `.backup` 后覆盖 |

> 提示：自定义过 prompts 的用户，升级 cag 后检查 `.backup` 文件，合并自己的修改。

---

## 配置

### 配置方式

采用**两级配置**机制：全局配置 `~/.commit-ai-guardian/config.yaml` + 项目配置 `.ai-review/config.yaml`，项目配置优先级更高，会覆盖同名全局配置。

> 🔧 配置字段的详细说明见 [TECHNICAL.md](TECHNICAL.md#13-配置文件)

### 常用配置项

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `api_key` | AI API 密钥 | `""` |
| `model` | 模型名称（如 `gpt-4o-mini`、`deepseek-chat`） | `gpt-4o-mini` |
| `api_base` | API 服务地址 | `https://api.openai.com/v1` |
| `language` | 审核输出语言（`zh-CN` / `en-US`） | `zh-CN` |
| `enabled` | 是否启用审查 | `true` |
| `severity_threshold` | 阻断阈值（`info` / `warning` / `error`） | `warning` |
| `diff_mode` | 审核范围（`full` 全部文件 / `diff` 仅变更） | `full` |
| `use_cache` | 是否启用结果缓存 | `true` |
| `include_patterns` | 审核文件范围（glob 数组） | `["*"]` |
| `case_format` | 案例输出格式（`default` / `compact` / `minimal`） | `compact` |
| `max_tokens` | AI 最大返回长度（token 数） | `8192` |
| `max_file_size` | 最大审核文件大小，**单位 KB** | `500` |
| `temperature` | AI 随机性（0=最保守, 0.3=平衡, 0.7=灵活） | `0.3` |
| `json_fix_history_mode` | JSON 修复 AI 上下文策略（`full` / `last`） | `full` |

> **temperature 设计说明**：
> - 主审核 AI（`0.3`）：需要一定灵活性发现不同角度的问题，太小容易思维僵化
> - JSON 修复 AI（`0.0`，固定）：纯格式转换（补全字段、修复引号/括号），不需要任何随机性，完全确定性输出更可靠

### 配置示例

`.ai-review/config.yaml`：

```yaml
api_key: "sk-xxx"
model: "gpt-4o-mini"
max_tokens: 8192
max_file_size: 500          # 单位 KB，超过 500KB 的文件跳过审核
temperature: 0.3             # 0=最保守, 0.3=平衡(默认), 0.7=更灵活
language: "zh-CN"
severity_threshold: "warning"
diff_mode: "diff"
use_cache: true
include_patterns:
  - "src/**/*.ts"
  - "src/**/*.vue"
```

### 主流模型 max_tokens 参考

`max_tokens` 限制的是 **AI 输出长度**（JSON 响应），不是输入。不同模型默认值差异很大，建议显式配置：

| 服务商 | 模型 | 默认 max_tokens | 最大可设 | 建议值 |
|--------|------|----------------|---------|--------|
| **DeepSeek** | deepseek-chat | 4,096 | 8,192 (8K) | **8K** |
| **DeepSeek** | deepseek-reasoner | 4,096 | 8,192 (8K) | **8K** |
| **Kimi** | kimi-k2 | 32,768 | 128K | **16K** |
| **Kimi** | kimi-k2.5 | 32,768 | 128K | **16K** |
| **Kimi** | kimi-k2-thinking | 32,768 | 128K | **16K** |
| **MiniMax** | MiniMax-M3 | 很小（不设会截断） | 128K | **16K** |
| **MiniMax** | MiniMax-M2.7 | 很小 | 128K | **16K** |
| **MiniMax** | MiniMax-M2.5 | 很小 | 128K | **16K** |
| **MiniMax** | MiniMax-M2.1 | 很小 | 128K | **16K** |
| **OpenAI** | gpt-4o | ~4,096 | 16,384 (16K) | **8K** |
| **OpenAI** | gpt-4o-mini | ~4,096 | 16,384 (16K) | **8K** |
| **OpenAI** | gpt-3.5-turbo | ~4,096 | 4,096 (4K) | **4K** |

> **为什么要配置**：MiniMax 如果不设 max_tokens，默认很小，JSON 几乎一定会被截断。默认值 `8192` 覆盖 95% 场景，使用 MiniMax 时可适当提高。
>
> **支持简写**：`4K` = 4096，`8K` = 8192，`16k` = 16384，纯数字也可以。

### 查看配置状态

```bash
cag status
```

---

## 命令参考

| 命令 | 说明 |
|------|------|
| `cag install` | 在当前 Git 仓库安装 pre-commit 钩子 |
| `cag install --force` | 强制覆盖安装（已存在 hook 时备份后覆盖） |
| `cag uninstall` | 卸载当前仓库的 pre-commit 钩子 |
| `cag audit` | 手动触发全量代码审查 |
| `cag review` | 审查当前暂存区的变更 |
| `cag configure` | 交互式配置（设置 API Key、模型等） |
| `cag status` | 查看当前配置与运行状态 |
| `cag validate-cases` | 验证 `.ai-review/cases/` 下的案例格式 |
| `cag debug-log` | 查看最近一次审查的详细日志 |
| `cag upgrade` | 升级到最新版本（`uv tool upgrade` 封装） |

---

## 使用技巧

### 跳过本次审查

```bash
git commit -m "docs: update readme" --no-verify
```

### 自定义审核规则

编辑 `.ai-review/prompts/` 下的模板文件，即可覆盖默认审查规则。修改后下次提交自动生效。

### 编写案例

在 `.ai-review/cases/` 目录下添加 Markdown 文件，增强 AI 对项目特定场景的理解。

格式要求：**Markdown + YAML frontmatter**：

```yaml
---
title: "SQL 注入防护规范"
category: "security"
severity: "error"
---

## 场景描述
用户输入直接拼接到 SQL 查询中...

## 正确做法
使用参数化查询...

## 错误示例
```python
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
```
```

### 双仓库推送（GitLab + GitHub）

```bash
# 添加 GitLab 远程（默认推送目标）
git remote add origin https://gitlab.example.com/your/project.git

# 添加 GitHub 远程（额外推送目标）
git remote add github https://github.com/your/project.git

# 同时推送
git push origin main && git push github main
```

### 配置网络代理（HTTP Proxy）

如果你的网络需要代理才能访问 AI API（例如公司内网、或 Clash/V2Ray 规则模式），可以配置代理地址。

**怎么判断是否需要配 proxy：**

先不配 proxy 直接运行 `cag review`，能正常返回结果就不需要；如果报连接超时 / `Connection refused`，再配置。

**配置方式：**

```bash
# 方式一：交互式配置
cag configure
# 提示输入 proxy 时填写：http://127.0.0.1:7890

# 方式二：直接编辑配置文件
vim ~/.commit_ai_guardian/config.yaml
# proxy: "http://127.0.0.1:7890"
```

**常见代理地址：**

| 工具 | 默认地址 |
|------|----------|
| Clash | `http://127.0.0.1:7890` |
| V2RayN | `http://127.0.0.1:10809` |
| Surge | `http://127.0.0.1:6152` |

> 如果你的 Clash 开了**全局/TUN 模式**，系统所有流量自动走代理，不需要额外配置。只在**规则模式**下需要配置 proxy，因为 Python 不会自动读取系统代理设置。
>
> proxy 只影响命令行工具，不影响 Git hook（hook 继承 shell 环境变量）。

---

## 常见问题

**1. 为什么审查没有触发？**

确认已执行 `cag install`，且当前分支未被配置排除。运行 `cag status` 检查运行状态。

**2. API Key 如何获取？**

访问你的 AI 服务商控制台（如 OpenAI、DeepSeek 等），在 API 管理页面创建 Key。

**3. 提交被 AI 拦截了怎么办？**

根据 AI 反馈修改代码后重新提交。若确认无风险，使用 `git commit --no-verify` 强制跳过。

**4. 支持哪些编程语言？**

默认支持所有文本文件，包括 Python、JavaScript、Java、Go、Markdown 等。

**5. 如何更新版本？**

```bash
# 升级（uv 自动追踪安装来源，GitLab/GitHub/PyPI 都支持）
uv tool upgrade commit-ai-guardian
# 或
cag upgrade

# 本地开发模式（修改源码后重装）
uv pip install --reinstall -e .
```

> **命令说明**：
> - `uv tool upgrade commit-ai-guardian`：升级已安装的工具（uv 内部记录 Git 或 PyPI 来源）
> - `cag upgrade`：同上，封装命令
> - `uv pip install --reinstall -e .`：在项目源码上可编辑安装，修改后立即生效，适合开发者

> 更多问答（如「二进制文件怎么判断的」「为什么并发异常要阻断 commit」等）：查看 [STUDY.md](STUDY.md)

---

## License

MIT
