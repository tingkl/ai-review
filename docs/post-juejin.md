# 掘金帖子

## 标题

**git commit 前自动 AI 代码审查：commit-ai-guardian 实践分享**

## 正文

## 背景

我们团队 20 人，前端 Vue + 后端 Java。Code Review 是有的，但大家都忙，CR 往往扫两眼就过了。结果上线后 Bug 频出，复盘时发现 60% 的问题其实 CR 阶段就能发现。

问题不是人不行，是人会疲劳、会敷衍、会有"这行代码一看就没问题"的错觉。

所以我想：**能不能在 commit 前让 AI 先审一遍？**

## commit-ai-guardian 是什么

一个 Git pre-commit 钩子工具，每次 `git commit` 前自动：

1. 获取暂存区的代码变更
2. 调用大模型（OpenAI/MiniMax/DeepSeek/Kimi）审查
3. 发现问题直接阻断 commit
4. 没问题直接通过

```
$ git commit -m "feat: add login"
🔍 AI 代码审核报告
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
┌─ src/auth.ts ──────────────────────────────┐
│  ⚠️  警告  🔒 安全  src/auth.ts:45          │
│       >> SQL 拼接存在注入风险               │
│       💡 使用参数化查询                     │
│       📍  const sql = `SELECT * FROM ...`  │
└──────────────────────────────────────────────┘
❌ 审核未通过
```

## 核心设计

### 自定义案例系统

每个团队规范不同。我们在 `.ai-review/cases/` 下放了团队规范案例：

```yaml
---
title: "Vue 组件命名规范"
category: "代码风格"
severity: "warning"
---

## 正确
组件名使用大驼峰：UserProfile.vue

## 错误
user-profile.vue（Kebab case 在 Vue 项目中不推荐）
```

AI 会参考这些案例审核代码，相当于**把团队规范编程化了**。

### 四级 JSON 容错

AI 返回 JSON 经常出问题，我们做了四层容错：

| 层级 | 策略 | 作用 |
|------|------|------|
| L1 本地修复 | 过滤 think 标签、代码块匹配、括号补全 | 处理 80% 的格式问题 |
| L2 AI 修复 | 调用专门的 JSON 修复 AI，带完整对话历史 | 处理复杂语法错误 |
| L3 Schema 校验 | 校验字段名、类型、必填项 | 确保结构正确 |
| L4 兜底通过 | 所有修复失败时记录日志但不阻断 | 避免卡死提交 |

### 性能优化

- **缓存**：相同内容 MD5 命中缓存，不重复调 AI
- **并发**：多文件并发审核，4 个 worker
- **精简案例**：case_format=compact 时只注入检查清单，减少 token

## 实践效果

用了两个月，数据：

- AI 平均每次审查 2-3 个文件，耗时 3-5 秒
- 拦截了约 40% 的低级问题（空指针、未处理异常、SQL 注入等）
- 人工 CR 时间减少 50%，人更关注架构和设计
- 自定义了 15 个团队案例，覆盖 Vue/Java 常见规范

## 安装使用

```bash
# 安装（uv 推荐）
uv tool install commit-ai-guardian

# 项目初始化
cd your-project
cag install

# 配置 API Key
cag configure
```

项目地址：https://github.com/tingkl/ai-review
PyPI：https://pypi.org/project/commit-ai-guardian

## 写在最后

这个工具不是替代人工 CR，而是**把低级问题交给 AI，让人去关注更有价值的事**。

欢迎试用，欢迎提 Issue。
