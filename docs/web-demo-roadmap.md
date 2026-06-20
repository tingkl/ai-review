# Web Demo 方案 + 案例市场规划

## Web Demo（在线体验）

### 目标
不用安装，粘贴代码就能体验 AI 审核效果，降低尝试门槛。

### 功能

```
┌──────────────────────────────────────────────┐
│  commit-ai-guardian 在线体验                  │
│                                               │
│  [粘贴代码]                                   │
│  ┌──────────────────────────────────────┐   │
│  │ function getUser(id) {               │   │
│  │   const sql = `SELECT * FROM users   │   │
│  │   WHERE id = ${id}`;                 │   │
│  │   return db.query(sql);              │   │
│  │ }                                    │   │
│  └──────────────────────────────────────┘   │
│                                               │
│  语言: [JavaScript ▼]  模型: [MiniMax ▼]    │
│                                               │
│  [🔍 开始审核]                                │
│                                               │
│  ┌──────────────────────────────────────┐   │
│  │ ⚠️  警告  🔒 安全  第 2 行            │   │
│  │ SQL 拼接存在注入风险                   │   │
│  │ 建议使用参数化查询                     │   │
│  └──────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
```

### 技术方案

**方案 A：纯前端（推荐）**
- 用户填自己的 API Key，直接在浏览器调用 AI API
- 无后端，无服务器成本
- 代码不离开用户设备

**方案 B：轻量后端**
- 提供有限的免费体验额度（每日 10 次）
- 需要服务器，有成本
- 可以收集使用数据

**推荐方案 A**，零成本上线。

### 实现

用纯 HTML + JavaScript 实现，部署到 GitHub Pages：

```
docs/demo/
├── index.html
├── style.css
└── app.js
```

用户输入 API Key（存在 localStorage），直接 fetch AI API。

### 文件位置

`/mnt/agents/output/ai-review/docs/demo/index.html`

---

## 案例市场

### 目标
提供预置的案例集，用户一键下载使用。

### 案例集规划

| 案例集 | 覆盖内容 | 适用场景 |
|--------|----------|----------|
| `frontend-vue` | Vue 组件规范、Composition API 最佳实践、性能优化 | Vue 项目 |
| `frontend-react` | Hooks 规范、状态管理、性能优化 | React 项目 |
| `backend-java` | Spring Boot 规范、异常处理、日志规范 | Java 项目 |
| `backend-python` | PEP8、类型注解、异步编程 | Python 项目 |
| `security-base` | SQL 注入、XSS、CSRF、敏感信息泄露 | 所有项目 |
| `mobile-flutter` | Widget 规范、状态管理、性能优化 | Flutter 项目 |

### 安装方式

```bash
# 查看可用案例集
cag cases list

# 安装前端 Vue 案例集
cag cases install frontend-vue

# 安装多个
cag cases install security-base backend-java

# 更新
cag cases update frontend-vue

# 卸载
cag cases remove frontend-vue
```

### 存储

案例集存到 `.ai-review/cases/market/` 目录，跟用户自定义案例 `.ai-review/cases/` 分开：

```
.ai-review/cases/
├── my-rule.md           # 用户自定义
├── team-standard.md     # 用户自定义
└── market/              # 案例市场（工具管理）
    ├── frontend-vue/
    │   ├── component-naming.md
    │   ├── props-validation.md
    │   └── performance.md
    └── security-base/
        ├── sql-injection.md
        └── xss-prevention.md
```

### 案例集格式

每个案例集是一个 Git 仓库，结构：

```
frontend-vue/
├── README.md            # 案例集说明
├── cases/               # 案例文件
│   ├── 01-component-naming.md
│   ├── 02-props-validation.md
│   └── 03-composition-api.md
└── manifest.yaml        # 元数据
```

`manifest.yaml`：

```yaml
name: frontend-vue
version: 1.0.0
description: Vue 前端开发规范案例集
author: tingkl
cases:
  - file: cases/01-component-naming.md
    title: 组件命名规范
    languages: [vue, javascript, typescript]
  - file: cases/02-props-validation.md
    title: Props 校验规范
    languages: [vue, javascript, typescript]
```

### 优先级

| 阶段 | 内容 | 时间 |
|------|------|------|
| P0 | 在线 Demo（方案 A，纯前端） | 本周 |
| P1 | security-base + frontend-vue 案例集 | 下周 |
| P2 | backend-java + backend-python 案例集 | 第 3 周 |
| P3 | `cag cases` 命令实现 | 第 3-4 周 |
| P4 | 社区贡献案例集机制 | 第 4 周+ |
