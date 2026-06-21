# AI 代码审核工具 commit-ai-guardian：让每次提交都经得起审查

> **一句话介绍**：在 git commit 前自动调用 AI 审查代码，发现问题直接阻断提交，帮你把 Bug 挡在代码库门外。

---

## 01 为什么做这个工具

我在一个 20 人的研发团队带项目。Code Review 是有的，但大家都忙，CR 往往流于形式——扫两眼就过了。结果上线后 Bug 频出，低级错误反复出现：

- 空指针没判，生产环境炸了
- SQL 拼接没转义，差点被注入
- 函数改了签名，调用方没同步改，编译都没过就合进去了
- 重复代码复制粘贴了七八份，重构时想死

这些问题，**AI 比人更适合发现**。AI 不会累，不会敷衍，不会"这行代码一看就没问题"。

所以我做了 `commit-ai-guardian`（简称 `cag`）：**每次 git commit 前，自动让 AI 审查代码，有问题直接阻断提交**。

---

## 02 它怎么工作

安装只要一行：

```bash
uv tool install commit-ai-guardian
```

进入你的 Git 仓库，初始化：

```bash
cag install
```

配置 API Key（支持 OpenAI、MiniMax、DeepSeek、Kimi 等）：

```bash
cag configure
```

然后正常写代码、git add、git commit。在 commit 前，工具会自动：

1. **采集 diff** —— 获取暂存区的代码变更
2. **调用 AI 审查** —— 把代码 + 审核维度发给大模型
3. **解析结果** —— AI 返回 JSON 格式的问题列表
4. **阻断或放行** —— 有问题就阻断 commit，没问题直接通过

```
$ git commit -m "feat: add login"

🔍 AI 代码审核报告
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─ src/auth.ts ──────────────────────────────┐
│  有警告                                       │
│                                               │
│  ⚠️  警告  🔒 安全  src/auth.ts:45           │
│       >> SQL 拼接存在注入风险                 │
│       💡 使用参数化查询：                     │
│          db.query("SELECT * FROM users WHERE  │
│          id = ?", [userId])                   │
│       📍  const sql = `SELECT * FROM users   │
│          WHERE id = ${req.params.id}`         │
└──────────────────────────────────────────────┘

❌ 审核未通过
1 个文件存在问题，请修复后重试
```

修复后重新 commit，通过了：

```
✅ 审核通过
所有文件符合代码质量标准
```

---

## 03 核心能力

### 🔍 5 大审核维度

| 维度 | 检查内容 |
|------|----------|
| Bug 检测 | 逻辑错误、边界条件、资源泄漏、并发问题 |
| 代码风格 | 命名规范、代码格式、注释质量、代码组织 |
| 性能问题 | 算法复杂度、内存泄漏、不必要的计算 |
| 最佳实践 | 设计模式、代码复用、错误处理、日志规范 |
| 文档完整 | 函数文档、参数说明、复杂逻辑注释 |

### 📝 自定义案例系统

每个团队的规范不同。你可以在 `.ai-review/cases/` 下放 Markdown 案例文件，AI 会参考这些案例来审核：

```yaml
---
title: "SQL 注入防护规范"
category: "安全"
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

案例按编程语言分类，支持 JS/TS、Java、Python、Vue 等。

### ⚡ 缓存机制

同一个文件的相同内容不会重复审核，命中缓存直接跳过，省时间省钱。

### 🔧 灵活配置

- **severity_threshold**：设置阻断阈值（info/warning/error）
- **diff_mode**：审核完整文件或只审变更
- **json_fix_history_mode**：JSON 修复 AI 的上下文策略
- **case_format**：案例注入格式（default/compact/minimal）

---

## 04 技术亮点

### 四层容错，JSON 解析不死

AI 返回的 JSON 经常有问题：引号没转义、括号没闭合、字段缺失、类型错误……工具内置了四层容错：

1. **本地修复** —— 多种策略提取 JSON（过滤 think 标签、代码块匹配、括号补全）
2. **AI 修复** —— 本地修不好时，调用专门的 JSON 修复 AI，带完整对话历史
3. **Schema 校验** —— 校验字段名、类型、必填项
4. **兜底阻断** —— 所有修复都失败时，passed=False，阻断提交（避免未知风险进入代码库）

### 两级配置

全局配置 `~/.commit-ai-guardian/config.yaml` + 项目配置 `.ai-review/config.yaml`，项目配置覆盖全局。方便不同项目用不同模型、不同规则。

---

## 05 适合谁用

- **小团队** —— 没有专人做 CR，AI 替代 80% 的审查工作
- **大团队** —— CR 流于形式，AI 做第一道把关，人审更有针对性
- **个人开发者** —— 提交前自检，避免低级错误
- **开源项目** —— 保证贡献代码的质量底线

---

## 06 安装使用

```bash
# 安装
uv tool install commit-ai-guardian

# 进入项目，初始化
cd your-project
cag install

# 配置 API Key
cag configure

# 完成！以后每次 git commit 自动审查
```

项目地址：[github.com/tingkl/ai-review](https://github.com/tingkl/ai-review)

PyPI：[pypi.org/project/commit-ai-guardian](https://pypi.org/project/commit-ai-guardian)

---

## 07 写在最后

这个工具不是替代人工 CR，而是**把低级、重复的问题交给 AI，让人去关注架构、业务逻辑、设计决策**。

用完你会发现：AI 比同事更仔细，而且不会嫌你代码写得烂。
