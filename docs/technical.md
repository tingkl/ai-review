# commit-ai-guardian 技术文档

> 面向开发者和技术负责人的实现细节说明。如需快速上手，请参考 README.md。

## 目录

- [架构总览](#架构总览)
- [配置系统](#配置系统)
- [AI 引擎](#ai-引擎)
- [Hook 安装器](#hook-安装器)
- [案例系统](#案例系统)
- [网络代理](#网络代理)


## 架构总览

### 执行流程

一次 `git commit` 触发的完整流程：

| 步骤 | 阶段 | 说明 |
|------|------|------|
| 1 | git commit | 用户提交代码 |
| 2 | pre-commit hook | Git 调用 `.git/hooks/pre-commit` 或 `.husky/pre-commit` |
| 3 | 采集 diff | 读取暂存区变更，生成文件列表和代码内容 |
| 4 | 构建 prompt | system message + user prompt + 案例（可选） |
| 5 | 调用 AI | `openai.chat.completions.create()` 发送请求 |
| 6 | 解析结果 | 提取 `<result>` 中的 JSON，四级容错修复 |
| 7 | 终端展示 | Rich 库渲染彩色审核报告 |
| 8 | 阻断或放行 | 有问题 → 阻断 commit；无问题 → 通过 |

### 模块分工

| 模块 | 文件 | 核心职责 |
|------|------|----------|
| CLI | `cli.py` | Click 命令注册，交互式配置向导 |
| 配置管理 | `config.py` | 两级配置加载、merge、持久化到 YAML |
| AI 引擎 | `ai_engine.py` | API 调用、JSON 解析修复、缓存读写 |
| Hook 安装器 | `hook_installer.py` | pre-commit 钩子安装、卸载、冲突检测 |
| Prompt 加载 | `prompt_loader.py` | system message 模板、案例格式化渲染 |
| 结果格式化 | `result_formatter.py` | Rich 彩色终端输出，文件路径解析 |


## 配置系统

### 两级配置架构

```
全局配置（~/.commit_ai_guardian/config.yaml）
    │
    │   项目配置（.ai-review/config.yaml）
    │   只覆盖 YAML 中明确存在的字段
    ▼
合并后的最终配置
```

**merge 规则**：`explicit_fields` 机制确保项目配置中缺失的字段不会用默认值覆盖全局配置。

### Config 数据类

```python
@dataclass
class Config:
    api_key: str = ""                        # API 认证密钥
    api_base: str = "https://api.openai.com/v1"  # 服务端点
    model: str = "gpt-4o-mini"               # 模型名称
    review_language: str = "zh-CN"           # 审核报告语言
    severity_threshold: str = "warning"      # 阻断阈值: info/warning/error/critical
    diff_mode: str = "review"                # 审核模式: review/diff
    max_file_size: int = 0                   # 单文件大小限制 (0=不限)
    case_format: str = "compact"             # 案例格式: default/compact/minimal
    timeout: int = 60                        # API 超时秒数
    max_tokens: int = 8192                   # AI 最大返回 token 数
    temperature: float = 0.3                 # 随机性 (0~2)
    proxy: str = ""                          # HTTP 代理地址
    use_cache: bool = True                   # 是否启用缓存
    json_fix_history_mode: str = "full"      # JSON 修复 AI 上下文: full/last
```

**json_fix_history_mode 详解**：

控制 JSON 修复 AI 的上下文累积策略：

| 模式 | 行为 | 适用场景 |
|------|------|----------|
| `full` | 每次修复失败后，把 `[assistant(json), user(error)]` 追加到历史，后续 attempt 能看到完整过程 | JSON 结构复杂、多次不同错误时 |
| `last` | 每次只保留最近一次，清空之前的历史 | prompt 长度敏感、简单格式错误时 |

实现位置：`ai_engine.py` `_fix_json_with_ai()` 方法。

### 配置加载时序

```python
manager = ConfigManager(repo_path="/path/to/repo")
config = manager.load()
# 1. 加载全局配置
# 2. 加载项目配置，记录 explicit_fields（YAML 中实际存在的字段）
# 3. merge：项目配置只覆盖 explicit_fields 中的字段
# 4. __post_init__ 校验字段合法性
```


## AI 引擎

### Prompt 结构

一次 API 请求携带的完整消息：

```
system message  →  角色定义 + 输出格式 + 审核维度 + 约束规则
user message    →  代码信息 + 代码内容 + 输出要求
                →  （可选）格式化后的案例内容
```

system message 包含：5 大审核维度定义、severity 分级标准、案例强约束规则、JSON 格式要求。

### 请求示例

```python
import openai

client = openai.OpenAI(
    api_key="sk-xxx",
    base_url="https://api.deepseek.com/v1",
    http_client=httpx.Client(proxies="http://127.0.0.1:7890"),  # 可选
)

resp = client.chat.completions.create(
    model="deepseek-chat",
    messages=[
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_prompt},
    ],
    temperature=0.3,
    max_tokens=8192,
)
```

### 四级 JSON 容错

AI 返回的 JSON 经常损坏，引擎内置四层修复：

| 层级 | 触发条件 | 修复策略 |
|------|----------|----------|
| L1 提取 | 返回内容包含 think 标签、代码块等杂质 | 正则过滤 → 代码块匹配 → 括号补全 |
| L2 AI 修复 | L1 提取后仍不是合法 JSON | 调用 JSON 修复 AI，带完整对话历史重试 3 次 |
| L3 Schema 校验 | JSON 合法但字段缺失/类型错误 | 校验 summary/passed/issues/severity 等必填项 |
| L4 兜底 | 3 次 AI 修复均失败 | 从已提取的字典中直接组装可用结果，不阻断提交 |

### 缓存机制

- **位置**：`~/.commit_ai_guardian/cache/`
- **缓存键**：`文件名 + MD5(代码内容) + MD5(案例内容)`
- **行为**：命中缓存直接返回，跳过 API 调用；案例变更自动失效


## Hook 安装器

### 检测优先级

安装器按以下顺序检测，命中即停止：

1. `.husky/` 目录存在 → 安装到 `.husky/pre-commit`
2. 否则 → 安装到 `.git/hooks/pre-commit`

### 冲突处理

| 场景 | 处理方式 |
|------|----------|
| 已存在本工具的 marker | 提示已安装，建议 `--force` 覆盖 |
| 存在其他 hook 内容 | 备份原文件，追加本工具命令 |
| 空文件或不存在 | 直接写入 |

### 生成的 hook 脚本结构

```bash
#!/bin/bash
# === commit-ai-guardian ===

# 1. 检查 uv 是否安装
# 2. 检查是否在禁用状态
# 3. 调用 cag review 审查暂存区
# 4. 根据返回值决定阻断或放行
```

Marker `# === commit-ai-guardian ===` 用于识别本工具生成的 hook，`.git/hooks` 和 `.husky/pre-commit` 使用相同 marker。


## 案例系统

### 案例文件格式

案例是 Markdown 文件，前置 YAML frontmatter：

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

### 案例格式化级别

| 级别 | 注入内容 | token 占用 | 适用场景 |
|------|----------|-----------|----------|
| default | 完整案例（场景 + 正确做法 + 错误示例 + 检查清单） | 最多 | 复杂规则，AI 需要完整上下文 |
| compact | 检查清单 + 关键代码片段 | 中等 | **默认**，平衡效果和成本 |
| minimal | 仅检查清单 | 最少 | 简单规则，大批量使用时节省 token |

案例放在 `.ai-review/cases/` 目录，按语言分子目录（`js/`、`java/`、`python/` 等），支持子目录递归读取。


## 网络代理

### 技术实现

proxy 值传递给 OpenAI SDK 的 `http_client`，底层使用 `httpx.Client(proxies=cfg.proxy)`：

```python
import httpx
from openai import OpenAI

client = OpenAI(
    api_key="sk-xxx",
    base_url="https://api.deepseek.com/v1",
    http_client=httpx.Client(
        proxies="http://127.0.0.1:7890",  # 你的 proxy 配置
        timeout=60,
    ),
)
```

### Clash 代理模式速查

| 模式 | 是否需要配置 proxy | 原因 |
|------|-------------------|------|
| 全局 / TUN | **不需要** | 系统流量自动走代理，Python 继承系统路由 |
| 规则 | **需要** | Python 的 httpx 不读取系统代理设置 |

### 常见代理地址

| 工具 | 默认地址 |
|------|----------|
| Clash | `http://127.0.0.1:7890` |
| V2RayN | `http://127.0.0.1:10809` |
| Surge | `http://127.0.0.1:6152` |

### 配置方法

```bash
# 方式一：交互式
cag configure
# 提示输入 proxy 时填写 http://127.0.0.1:7890

# 方式二：直接编辑
vim ~/.commit_ai_guardian/config.yaml
# proxy: "http://127.0.0.1:7890"
```

proxy 只影响命令行工具，Git hook 继承 shell 环境变量自动生效。
