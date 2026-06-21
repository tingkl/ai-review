# V2EX 帖子

## 标题

**[分享创造] 写了个 AI 代码审查工具，git commit 前自动拦截 Bug，已发 PyPI，有在线 Demo**

## 正文

用了一段时间了，团队 20 人，效果比预期好。分享一下。

**问题**：Code Review 流于形式，低级 Bug 反复进主干。空指针、SQL 注入、重复代码……人眼会疲劳，AI 不会。

**方案**：`commit-ai-guardian`（`cag`），git commit 前自动调用 AI 审查代码，有问题直接阻断提交。

```
$ git commit -m "feat: add login"

🔍 AI 代码审核报告

┌─ src/auth.ts ──────────────────────────────┐
│  ⚠️  警告  🔒 安全  src/auth.ts:45          │
│       >> SQL 拼接存在注入风险               │
│       💡 使用参数化查询                     │
│       📍  const sql = `SELECT * FROM ...`  │
└──────────────────────────────────────────────┘

❌ 审核未通过
```

修复后重新 commit，通过。整个过程自动，不需要额外操作。

**核心能力**：
- 5 大审核维度（Bug/风格/性能/最佳实践/文档）
- **自定义审核规则**（system prompt，可切换标准/安全优先/性能优先视角）
- **自定义案例系统**（团队规范写成 Markdown 案例，AI 按案例精准审核）
- 四级 JSON 容错（本地修复 → AI 修复 3 次 → Schema 校验 → 兜底阻断）
- 缓存机制（相同内容不重复审核）
- 支持 OpenAI/MiniMax/DeepSeek/Kimi（**推荐 DeepSeek V4，1M 上下文**）

**在线体验**（不用安装，粘贴代码就能试）：
https://tingkl.github.io/ai-review/demo/

**安装**（一行搞定）：
```bash
uv tool install commit-ai-guardian
cd your-project
cag install
cag configure  # 配 API Key，推荐 DeepSeek
```

**项目地址**：https://github.com/tingkl/ai-review
**PyPI**：https://pypi.org/project/commit-ai-guardian

找几个团队试用，收集反馈迭代。有兴趣的留言或 Star，有问题提 Issue。

---

**为什么做这个而不是用现有的？**

现有工具要么太重（SonarQube 要搭服务器），要么太轻（只是语法检查）。我想要的是：
1. 能理解业务逻辑的 AI 审查
2. **既能自定义审核视角（prompt），又能自定义具体规则（案例）**
3. 安装简单，一行搞定
4. 不花钱（用自己的 API Key，按需付费）

欢迎试用，欢迎拍砖。
