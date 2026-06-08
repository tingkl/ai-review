# Commit AI Guardian

Git 提交前的 AI 代码审核工具。

**两种用法：**
- `install` + `git commit` —— 自动审核暂存区的代码变更
- `review` —— 手动审核指定文件或目录的完整代码

---

## 安装

依赖：Python 3.8+、[uv](https://github.com/astral-sh/uv)

```bash
git clone ssh://git@124.223.189.152:7022/tingkl/ai-review.git
cd ai-review
uv sync
uv pip install -e .
```

以下命令中的 `<项目路径>` 指 `ai-review` 的绝对路径，例如 `/Users/awesome/work/ai/ai-review`。

---

## 配置 API Key

```bash
uv run --project <项目路径> commit-ai-guardian configure
```

按提示输入：

| 项 | 说明 | 默认 |
|---|---|---|
| `api_key` | 你的 API Key（必填） | — |
| `api_base` | API 地址 | `https://api.openai.com/v1` |
| `model` | 模型名 | `gpt-4o-mini` |
| `severity_threshold` | 阻断级别：`info`/`warning`/`error`/`critical` | `warning` |
| `timeout` | 请求超时（秒） | `60` |

配置文件保存在 `~/.commit-ai-guardian/config.yaml`，可直接编辑。

---

## 用法一：git commit 自动审核

在你要审核的代码仓库里执行：

```bash
cd your-code-repo
uv run --project <项目路径> commit-ai-guardian install
```

之后每次 `git commit` 会自动触发 AI 审核。发现问题时 `commit` 会被阻断，按提示修复或加 `--no-verify` 跳过。

```bash
# 卸载 hook
uv run --project <项目路径> commit-ai-guardian uninstall

# 查看状态
uv run --project <项目路径> commit-ai-guardian status
```

---

## 用法二：手动审核文件/目录

```bash
# 审核单个文件
uv run --project <项目路径> commit-ai-guardian review -f src/auth.py

# 审核目录（递归）
uv run --project <项目路径> commit-ai-guardian review -d src/

# 审核多个目录
uv run --project <项目路径> commit-ai-guardian review -d src/ -d tests/

# glob 模式
uv run --project <项目路径> commit-ai-guardian review -p 'src/**/*.py'

# 组合使用
uv run --project <项目路径> commit-ai-guardian review -d src/ -f config.yaml
```

| 选项 | 说明 |
|---|---|
| `-f, --file` | 指定文件，可多次使用 |
| `-d, --dir` | 指定目录，默认递归 |
| `-p, --pattern` | glob 模式，如 `src/**/*.py` |
| `--no-recursive` | 不递归子目录 |
| `--max-files` | 最大审核文件数，默认 50 |

---

## 全局安装（可选）

不想每次写 `--project` 可以全局安装：

```bash
cd ai-review
uv tool install -e .
```

之后直接：

```bash
commit-ai-guardian install
commit-ai-guardian review -d src/
```

---

## 审核维度

- **Bug 检测** — 逻辑错误、空指针、边界条件
- **安全漏洞** — SQL 注入、XSS、敏感信息泄露
- **代码风格** — 命名规范、格式、注释
- **性能问题** — 复杂度、内存泄漏
- **最佳实践** — 设计模式、错误处理
- **文档完整** — 函数文档、参数说明
