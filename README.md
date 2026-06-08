# Commit AI Guardian

Git commit 前的 AI 代码审核工具。

## 安装（一次）

```bash
git clone ssh://git@124.223.189.152:7022/tingkl/ai-review.git
cd ai-review
uv sync && uv pip install -e .
uv run commit-ai-guardian configure   # 输入 API Key
```

## 使用

### 方式一：commit 时自动审核

在代码仓库里执行：

```bash
cd your-code-repo
uv run --project /path/to/ai-review commit-ai-guardian install
```

之后每次 `git commit` 自动触发审核。不通过则阻断提交，加 `--no-verify` 可跳过。

### 方式二：审核指定文件/目录

```bash
# 单个文件
uv run --project /path/to/ai-review commit-ai-guardian review -f src/main.py

# 整个目录
uv run --project /path/to/ai-review commit-ai-guardian review -d src/

# glob 模式
uv run --project /path/to/ai-review commit-ai-guardian review -p 'src/**/*.py'
```

把 `/path/to/ai-review` 换成 ai-review 的实际绝对路径。
