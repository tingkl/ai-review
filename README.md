# Commit AI Guardian

基于 AI 的 Git Pre-commit 代码审查工具，在每次提交前自动拦截代码风险，守护代码质量。

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)

---

## 快速开始

```bash
# 1. 安装
curl -sSL https://install.example.com/cag | sh

# 2. 项目初始化
cag install

# 3. 正常提交代码，AI 会自动审查
git commit -m "feat: add new feature"
```

---

## 安装

### GitHub（推荐）

```bash
curl -sSL https://github.com/wmariuss/commit-ai-guardian/releases/download/v1.0.0/install.sh | sh
```

### GitLab（内部源）

```bash
export CAG_SOURCE=gitlab  # 使用内部源
curl -sSL https://gitlab.example.com/cag/install.sh | sh
```

### PyPI

```bash
# 推荐：使用 uv（更快、无全局环境依赖）
uv tool install commit-ai-guardian

# 或使用 pip
pip install commit-ai-guardian
```

---

## 项目初始化

进入任意 Git 仓库，运行：

```bash
cag install
```

此命令会在当前项目中创建：

| 文件 | 说明 |
|------|------|
| `.git/hooks/pre-commit` | Git pre-commit 钩子 |
| `.cag/config.yaml` | 项目级配置文件 |
| `.cag/prompts/` | 自定义提示词目录 |
| `.cag/cases/` | 案例库目录 |

---

## 命令参考

| 命令 | 说明 |
|------|------|
| `cag install` | 在当前 Git 仓库安装 pre-commit 钩子 |
| `cag uninstall` | 卸载当前仓库的 pre-commit 钩子 |
| `cag check` | 手动触发代码审查 |
| `cag config --api-key` | 设置 API Key |
| `cag config --model` | 切换 AI 模型 |
| `cag config --disable` | 临时关闭审查 |
| `cag config --enable` | 重新启用审查 |
| `cag status` | 查看当前配置状态 |
| `cag update` | 更新到最新版本 |

---

## 常用配置

### 设置 API Key

```bash
# 写入全局配置（推荐）
cag config --api-key "your-api-key"

# 或使用环境变量
export CAG_API_KEY="your-api-key"
```

### 临时关闭 / 开启审查

```bash
# 全局关闭
cag config --disable

# 全局开启
cag config --enable
```

### 单次跳过审查

```bash
# 使用 --no-verify 跳过本次 pre-commit 钩子
git commit -m "docs: update readme" --no-verify
```

### 自定义提示词

编辑 `.cag/prompts/custom.md`，支持覆盖默认审查规则。重新提交即可生效。

### 编写案例

在 `.cag/cases/` 目录下添加 Markdown 文件，用于增强 AI 对项目特定场景的理解：

```bash
.cag/cases/
  ├── security-best-practices.md   # 安全编码规范
  ├── project-conventions.md       # 项目约定
  └── and so on...
```

---

## 双仓库推送（GitLab + GitHub）

如需同时推送到 GitLab 和 GitHub，配置项目远程仓库：

```bash
# 添加 GitLab 远程（默认推送目标）
git remote add origin https://gitlab.example.com/your/project.git

# 添加 GitHub 远程（额外推送目标）
git remote add github https://github.com/your/project.git

# 同时推送
git push origin main && git push github main
```

或在 `.git/config` 中配置多仓库自动推送。

---

## 常见问题

**1. 为什么审查没有触发？**

确认已执行 `cag install`，且当前分支未被配置排除。运行 `cag status` 检查运行状态。

**2. API Key 如何获取？**

访问你的 AI 服务商控制台（如 OpenAI、DeepSeek 等），在 API 管理页面创建 Key。

**3. 提交被 AI 拦截了怎么办？**

根据 AI 反馈修改代码后重新提交。若确认无风险，可使用 `git commit --no-verify` 强制跳过。

**4. 支持哪些编程语言？**

默认支持所有文本文件，包括 Python、JavaScript、Java、Go、Markdown 等。

**5. 如何更新版本？**

运行 `cag update`，或重新执行安装命令覆盖旧版本。

---

## License

MIT
