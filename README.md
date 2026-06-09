# Commit AI Guardian

Git commit 前的 AI 代码审核工具。

## 推荐用法

### 1. 安装工具（全局，一次）

**方式一：从 Git 仓库直接安装（推荐）**

```bash
# SSH
uv tool install git+ssh://git@124.223.189.152:7022/tingkl/ai-review.git

# 或 HTTP（如果 SSH 不可用）
uv tool install git+http://124.223.189.152:7080/tingkl/ai-review.git
```

**方式二：先 clone 再安装（开发调试）**

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

安装后自动创建 `.ai-review/` 目录结构：

```
your-code-repo/
└── .ai-review/
    ├── cases/      ← 启用审核的案例放这里（用户自己添加）
    └── example/    ← 示例模板（不参与审核，仅参考）
        ├── sql-injection.md
        ├── xss.md
        └── ...
```

**启用案例**：从 `example/` 复制需要的 `.md` 文件到 `cases/`：

```bash
cp .ai-review/example/sql-injection.md .ai-review/cases/
cp .ai-review/example/xss.md .ai-review/cases/
# 只复制你项目需要的
```

### 4. 日常使用

```bash
git add .
git commit -m "xxx"
# 自动触发 AI 审核，不通过会阻断提交
```

## 案例文件格式

`.ai-review/cases/` 下的 `.md` 文件，格式为 **Markdown + YAML frontmatter**：

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
- [ ] 是否使用了参数化查询
  - 确认所有用户输入都通过参数绑定
```

## 其他用法

### 手动审核指定文件/目录（不经过 git）

```bash
commit-ai-guardian review -f src/auth.ts
commit-ai-guardian review -d src/
commit-ai-guardian review -p 'src/**/*.ts'
```

### 查看状态 / 卸载 Hook

```bash
commit-ai-guardian status       # 查看配置和 hook 状态
commit-ai-guardian uninstall    # 卸载当前仓库的 hook
```
