# Commit AI Guardian

Git commit 前的 AI 代码审核工具。

## 推荐用法

### 1. 安装工具（全局，一次）

```bash
git clone ssh://git@124.223.189.152:7022/tingkl/ai-review.git ~/ai-review
cd ~/ai-review
uv sync && uv pip install -e .
uv tool install -e .
```

### 2. 配置 API Key（一次）

```bash
commit-ai-guardian configure
```

### 3. 给代码仓库装上 Hook（每个仓库一次）

```bash
cd your-code-repo
commit-ai-guardian install
```

`install` 会根据当前仓库的 hook 状态做不同处理：

| 场景 | 行为 |
|------|------|
| 没有 pre-commit | **创建** hook 文件 |
| 有 pre-commit，且是本工具安装的 | **替换**为最新版本 |
| 有 pre-commit，是其他工具或手动创建的 | **拒绝操作**，提示用 `--force` 覆盖（覆盖前会自动备份为 `.backup`） |

### 4. 日常使用

```bash
git add .
git commit -m "xxx"
# 自动触发 AI 审核，不通过会阻断提交
```

---

## 其他用法

### 手动审核指定文件/目录（不经过 git）

```bash
# 单个文件
commit-ai-guardian review -f src/auth.py

# 目录
commit-ai-guardian review -d src/

# glob 模式
commit-ai-guardian review -p 'src/**/*.py'
```

### 不想全局安装

不执行 `uv tool install`，每次用 `--project` 指定 ai-review 的路径：

```bash
cd your-code-repo
uv run --project ~/ai-review commit-ai-guardian install
```

### 查看状态 / 卸载 Hook

```bash
commit-ai-guardian status       # 查看配置和 hook 状态
commit-ai-guardian uninstall    # 卸载当前仓库的 hook
```
