# 🛡️ Commit AI Guardian

Git Pre-commit Hook AI 代码审核系统。在每次 `git commit` 之前自动触发 AI 对代码变更进行审核，帮助团队提升代码质量、发现潜在 Bug 和安全漏洞。

## ✨ 功能特性

- 🤖 **AI 智能审核** — 基于大语言模型，支持 GPT-4o-mini 等多种模型
- 🔍 **多维度检查** — Bug 检测、安全漏洞、代码风格、性能问题、最佳实践、文档完整性
- 🚦 **智能阻断** — 根据严重程度配置自动阻断不合规的提交
- 🎨 **美观终端输出** — 使用 Rich 库提供彩色、结构化的审核报告
- ⚙️ **灵活配置** — 支持自定义审核规则、模型选择、忽略文件等
- 🔒 **安全友好** — 支持代理配置，兼容私有化部署和第三方 API

## 📦 安装

```bash
# 从 PyPI 安装 (推荐)
pip install commit-ai-guardian

# 或从源码安装
git clone https://github.com/yourusername/commit-ai-guardian.git
cd commit-ai-guardian
pip install -e .
```

## 🚀 快速开始

### 1. 配置 API Key

```bash
# 交互式配置
commit-ai-guardian configure
```

或直接编辑配置文件 `~/.commit-ai-guardian/config.yaml`：

```yaml
api_key: "sk-your-api-key-here"
api_base: "https://api.openai.com/v1"
model: "gpt-4o-mini"
language: "zh-CN"
severity_threshold: "warning"
max_file_size: 500
timeout: 60
```

### 2. 在 Git 仓库安装 Hook

```bash
cd your-git-repo
commit-ai-guardian install
```

### 3. 正常使用 Git

```bash
git add <files>
git commit -m "your message"
# 此时会自动触发 AI 代码审核！
```

## 📋 命令说明

| 命令 | 说明 |
|------|------|
| `commit-ai-guardian install` | 在当前仓库安装 pre-commit hook |
| `commit-ai-guardian install --force` | 强制覆盖已存在的 hook |
| `commit-ai-guardian uninstall` | 卸载 pre-commit hook |
| `commit-ai-guardian audit` | 手动运行代码审核 |
| `commit-ai-guardian configure` | 交互式配置管理 |
| `commit-ai-guardian status` | 查看配置和安装状态 |

## ⚙️ 配置项说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `api_key` | AI API 密钥 | — |
| `api_base` | API 基础地址 | `https://api.openai.com/v1` |
| `model` | 使用的模型 | `gpt-4o-mini` |
| `language` | 审核报告语言 | `zh-CN` |
| `severity_threshold` | 阻止提交的最低严重级别 | `warning` |
| `max_file_size` | 最大审核文件大小 (KB) | `500` |
| `ignore_patterns` | 忽略文件模式列表 | `*.lock, *.json, ...` |
| `timeout` | API 超时时间 (秒) | `60` |
| `proxy` | 代理地址 | — |

## 🔌 兼容的 API 提供商

- [OpenAI](https://platform.openai.com/)
- [Azure OpenAI](https://azure.microsoft.com/products/ai-services/openai-service)
- [Google Gemini (OpenAI compatible)](https://ai.google.dev/)
- [Anthropic Claude (via proxy)](https://www.anthropic.com/)
- [本地部署模型 (Ollama, vLLM 等)](https://ollama.com/)

## 🧩 审核维度

1. **🐛 Bug 检测** — 逻辑错误、空指针、边界条件、资源泄漏
2. **🔒 安全漏洞** — SQL注入、XSS、敏感信息泄露、硬编码密码
3. **🎨 代码风格** — 命名规范、代码格式、注释质量
4. **⚡ 性能问题** — 算法复杂度、内存泄漏、不必要计算
5. **📋 最佳实践** — 设计模式、代码复用、错误处理
6. **📝 文档完整** — 函数文档、参数说明、返回值说明

## 📊 审核报告示例

```
🔍 AI 代码审核报告
共审核 2 个文件

❌ src/auth.py
   发现 2 个问题
   
  级别    类别       行号  描述                            建议
  错误    🔒 安全    25   使用明文存储密码                使用 bcrypt/argon2 哈希密码
  警告    📋 实践    42   未处理异常可能导致信息泄露        添加 try-except 错误处理

✅ src/utils.py
   代码质量良好，未发现明显问题

📊 审核汇总
文件总数: 2  |  通过: 1  未通过: 1  问题总数: 2

问题严重级别分布
  错误: 1
  警告: 1

❌ 审核未通过 - 1 个文件存在问题
使用 git commit --no-verify 可跳过审核（不推荐）
```

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

## 📄 License

MIT License
