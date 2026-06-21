<div align="center">

# 🛡️ Commit AI Guardian

**AI 驱动的 Git pre-commit 代码审查工具**

在每次 `git commit` 前自动拦截代码风险，守护代码质量

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python)](https://python.org)
[![PyPI](https://img.shields.io/pypi/v/commit-ai-guardian?style=for-the-badge&logo=pypi&color=green)](https://pypi.org/project/commit-ai-guardian/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

</div>

---

## 🚀 30 秒快速开始

```bash
# 1. 安装
uv tool install commit-ai-guardian

# 2. 进入项目初始化
cd your-project
cag install

# 3. 配置 API Key
cag configure

# 4. 完成！以后每次 git commit 自动审查
```

> 💡 **无需修改任何代码**，安装即生效

---

## ✨ 核心能力

### 🔍 5 大审核维度

| 维度 | 检查内容 | 典型问题 |
|------|----------|----------|
| 🐛 **Bug 检测** | 逻辑错误、边界条件、资源泄漏 | 空指针、死循环、数组越界 |
| 🎨 **代码风格** | 命名规范、格式、注释 | 变量命名不清、缺少注释 |
| ⚡ **性能问题** | 算法复杂度、内存、缓存 | N+1 查询、内存泄漏 |
| 🛡️ **最佳实践** | 设计模式、错误处理、安全 | 未处理异常、SQL 注入 |
| 📝 **文档完整** | 函数文档、参数说明 | 复杂函数无注释 |

### 📝 自定义审核规则（Prompt）

决定 **"怎么审"** —— 切换 AI 的审核视角：

- **📐 标准审核**：全面检查 5 大维度（默认）
- **🔒 安全优先**：专注 SQL 注入、XSS、权限绕过
- **⚡ 性能优先**：专注算法复杂度、N+1 查询、内存泄漏

```
.ai-review/prompts/
├── default.md    # 标准审核
├── security.md   # 安全优先
└── performance.md # 性能优先
```

### 📚 自定义案例系统

决定 **"查什么"** —— 让 AI 按你的团队规范审核：

```yaml
---
title: "Vue 组件命名规范"
category: "代码风格"
severity: "warning"
---

## 正确
UserProfile.vue

## 错误
user-profile.vue
```

> 🎯 相当于 **把团队规范编程化**，AI 参考案例精准审核

### 🔄 四级 JSON 容错

AI 返回 JSON 经常出问题，内置四层容错不卡死：

```
┌─────────────────────────────────────────────────────┐
│  L1 本地修复 → L2 修复 AI → L3 Schema → L4 兜底     │
│                                                      │
│  过滤think标签    最多重试3次    字段校验    日志记录  │
│  代码块匹配       带对话历史     类型检查    不阻断    │
│  括号补全                                        │
└─────────────────────────────────────────────────────┘
```

---

## 📦 安装

### 推荐方式：PyPI

```bash
uv tool install commit-ai-guardian
```

### 其他方式

```bash
# GitHub（最新开发版）
uv tool install git+https://github.com/tingkl/ai-review.git

# GitLab（公司内部）
uv tool install git+ssh://git@124.223.189.152:7022/gaoq/ai-review.git
```

| 方式 | 场景 | 稳定性 |
|------|------|--------|
| PyPI | 普通用户、生产环境 | ⭐⭐⭐⭐⭐ |
| GitHub | 开发者贡献 | ⭐⭐⭐ |
| GitLab | 公司内部 | ⭐⭐⭐ |

---

## ⚙️ 配置

### 两级配置机制

```
全局配置 ~/.commit_ai_guardian/config.yaml
         │
         ▼ 项目配置覆盖全局
         
项目配置 .ai-review/config.yaml  ← 优先级更高
```

### 常用配置

```yaml
api_key: "sk-xxx"                    # API 密钥
model: "deepseek-v4-pro"             # 模型（推荐 DeepSeek V4，1M上下文）
api_base: "https://api.deepseek.com/v1"
language: "zh-CN"                    # 审核语言
severity_threshold: "warning"        # 阻断阈值
case_format: "compact"               # 案例格式
temperature: 0.3                     # 随机性
max_tokens: 8192                     # 最大返回长度
```

### 模型推荐

| 服务商 | 推荐模型 | 上下文 | 特点 |
|--------|----------|--------|------|
| **DeepSeek** | `deepseek-v4-pro` | 1M | 最强代码能力，推荐 |
| **Kimi** | `kimi-k2.6` | 256K | 最新版本 |
| **MiniMax** | `MiniMax-M3` | 128K | 编程专项 |
| **OpenAI** | `gpt-4o` | 128K | 通用能力强 |

---

## 🖥️ 在线体验

不用安装，浏览器直接体验完整功能：

**👉 [https://tingkl.github.io/ai-review/demo/](https://tingkl.github.io/ai-review/demo/)**

支持：选择模型 ✓ 配置审核规则 ✓ 加载案例 ✓ 自定义 Prompt ✓

---

## 📖 命令参考

```bash
cag install          # 安装 pre-commit 钩子
cag install --force  # 强制覆盖（备份原 hook）
cag uninstall        # 卸载
cag configure        # 交互式配置
cag status           # 查看配置状态
cag review           # 手动审查暂存区
cag audit            # 全量审查
cag upgrade          # 升级版本
```

---

## 📝 案例格式

```markdown
---
title: "SQL 注入防护"
category: "安全"
severity: "error"
---

## 场景描述
用户输入直接拼接到 SQL...

## 正确做法
使用参数化查询

## 错误示例
const sql = `SELECT * FROM users WHERE id = ${id}`
```

> 📂 放在 `.ai-review/cases/` 下，支持子目录按语言组织

---

## 🔧 网络代理

公司内网或 Clash/V2Ray 规则模式需要配置：

```yaml
# ~/.commit_ai_guardian/config.yaml
proxy: "http://127.0.0.1:7890"   # Clash
proxy: "http://127.0.0.1:10809"  # V2RayN
proxy: "http://127.0.0.1:6152"  # Surge
```

> Clash 开 **全局/TUN 模式** 不需要配置

---

## ❓ 常见问题

**Q: 为什么审查没有触发？**
A: 确认已执行 `cag install`，运行 `cag status` 检查状态。

**Q: API Key 怎么获取？**
A: 访问 AI 服务商控制台（DeepSeek/OpenAI 等），在 API 管理页面创建。

**Q: 提交被拦截了怎么办？**
A: 根据 AI 反馈修改代码后重提交。确认无风险可用 `git commit --no-verify` 跳过。

**Q: 支持哪些语言？**
A: 所有文本文件，Python/JS/Java/Go/Vue/Markdown 等。

---

## 📚 更多文档

| 文档 | 内容 | 适合 |
|------|------|------|
| [STUDY.md](STUDY.md) | 设计原理与常见问题 | 初学者 |
| [TECHNICAL.md](TECHNICAL.md) | 架构设计、Prompt 工程 | 开发者 |

---

<div align="center">

**[GitHub](https://github.com/tingkl/ai-review)** · **[PyPI](https://pypi.org/project/commit-ai-guardian/)** · **[在线 Demo](https://tingkl.github.io/ai-review/demo/)**

MIT License

</div>
