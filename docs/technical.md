# commit-ai-guardian 技术文档

## 目录

1. [架构概述](#架构概述)
2. [配置系统](#配置系统)
3. [AI 引擎](#ai-引擎)
4. [Hook 安装器](#hook-安装器)
5. [案例系统](#案例系统)
6. [网络代理](#网络代理)

---

## 架构概述

```
git commit
    │
    ▼
pre-commit hook
    │
    ▼
收集暂存区 diff ──→ AI 审核引擎 ──→ 解析 JSON 结果
    │                                    │
    ▼                                    ▼
有问题 ──→ 阻断 commit              没问题 ──→ 放行
    │
    ▼
终端展示问题列表（文件 + 行号 + 建议）
```

核心模块：

| 模块 | 文件 | 职责 |
|------|------|------|
| CLI | `cli.py` | Click 命令注册与交互 |
| 配置管理 | `config.py` | 两级配置加载、合并、持久化 |
| AI 引擎 | `ai_engine.py` | API 调用、JSON 解析修复、缓存 |
| Hook 安装器 | `hook_installer.py` | pre-commit 钩子安装/卸载/检测 |
| Prompt 加载 | `prompt_loader.py` | system message、案例格式化 |
| 结果格式化 | `result_formatter.py` | 终端彩色输出 |

---

## 配置系统

### 两级配置架构

```
全局配置                    项目配置
~/.commit_ai_guardian/      .ai-review/
├── config.yaml             ├── config.yaml
└── cache/                  ├── cases/
                            └── prompts/

合并规则：项目配置覆盖全局配置（只覆盖 YAML 中明确存在的字段）
```

### Config 字段

```python
@dataclass
class Config:
    api_key: str = ""
    api_base: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    review_language: str = "zh-CN"
    severity_threshold: str = "warning"
    diff_mode: str = "review"
    max_file_size: int = 0
    case_format: str = "compact"
    timeout: int = 60
    max_tokens: int = 8192
    temperature: float = 0.3
    proxy: str = ""              # HTTP 代理地址
    use_cache: bool = True
    json_fix_history_mode: str = "full"
    include_patterns: list = None
    ignore_patterns: list = None
```

### 配置加载流程

1. `ConfigManager.load()` 调用 `_load_single()` 加载全局配置和项目配置
2. `_load_single()` 返回 `(Config, explicit_fields)`，记录 YAML 中实际存在的字段
3. `merge()` 只覆盖 `explicit_fields` 中的字段，避免缺失字段的默认值覆盖全局配置
4. `__post_init__()` 校验字段合法性（temperature 范围、case_format 枚举等）

---

## AI 引擎

### 请求流程

```
_build_prompt() ──→ _call_api_safe() ──→ parse_ai_response()
    │                       │                    │
    ▼                       ▼                    ▼
system message      openai.chat.completions    _extract_json_str()
+ user prompt       .create()                   _fix_json_with_ai()
+ 案例（可选）                              _validate_review_schema()
```

### 四级 JSON 容错

| 层级 | 函数 | 策略 |
|------|------|------|
| L1 提取 | `_extract_json_str()` | 过滤 think 标签、代码块匹配、括号补全 |
| L2 AI 修复 | `_fix_json_with_ai()` | 调用修复 AI，带完整对话历史 |
| L3 校验 | `_validate_review_schema()` | 字段名、类型、必填项校验 |
| L4 兜底 | `_fix_json_with_ai()` 3 次失败 | 提取可用字段直接返回 |

### 缓存机制

- 缓存位置：`~/.commit_ai_guardian/cache/`
- 缓存键：`(文件名, MD5(代码内容), 案例MD5)`
- 命中时直接返回缓存结果，跳过 API 调用

---

## Hook 安装器

### 支持的 Hook 类型

| 场景 | 路径 | Marker |
|------|------|--------|
| 标准 Git Hook | `.git/hooks/pre-commit` | `# === commit-ai-guardian ===` |
| Husky | `.husky/pre-commit` | `# === commit-ai-guardian ===` |

### 安装逻辑

1. 检测 `.husky/` 目录存在 → 优先安装到 husky
2. 否则安装到 `.git/hooks/`
3. 安装前检查：已有 marker → 提示已安装；有其他内容 → 备份后追加
4. 复制案例文件到 `.ai-review/cases/`

---

## 案例系统

### 案例格式

```yaml
---
title: "标题"
category: "类别"
severity: "info/warning/error"
---

## 场景描述
...

## 正确做法
...

## 错误示例
```代码```
```

### 格式化级别

| 级别 | 输出内容 | 适用场景 |
|------|----------|----------|
| default | 完整案例（描述 + 正确做法 + 错误示例） | 复杂规则，需要详细上下文 |
| compact | 精简格式（检查清单 + 关键代码） | 默认，平衡 token 和效果 |
| minimal | 最小格式（只保留检查清单） | 简单规则，节省 token |

---

## 网络代理

### 配置字段

```yaml
# ~/.commit_ai_guardian/config.yaml
proxy: "http://127.0.0.1:7890"
```

### 技术细节

- **作用**：HTTP/HTTPS 代理服务器地址，传递给 OpenAI SDK 的 `http_client`
- **适用场景**：公司内网、Clash/V2Ray 规则模式等需要显式指定代理的环境
- **实现方式**：通过 `httpx.Client(proxies=cfg.proxy)` 创建带代理的 HTTP 客户端
- **默认值**：空字符串，表示不走代理

### 全局模式 vs 规则模式

| Clash 模式 | 是否需要配置 proxy | 原因 |
|-----------|-------------------|------|
| 全局 / TUN | **不需要** | 系统所有流量自动走代理，Python 继承系统路由 |
| 规则 | **需要** | Python 的 `httpx` 不读取系统代理设置，需显式指定 |

### 检测方法

如果不确定是否需要配置 proxy，可以先不配置直接运行 `cag review`：
- 能正常返回结果 → 不需要 proxy
- 报连接超时 / Connection refused → 需要配置 proxy

### 常见代理地址

| 工具 | 默认地址 |
|------|----------|
| Clash | `http://127.0.0.1:7890` |
| V2RayN | `http://127.0.0.1:10809` |
| Surge | `http://127.0.0.1:6152` |

### 配置方式

**方式一：交互式配置**

```bash
cag configure
# 提示输入 proxy 时填写：http://127.0.0.1:7890
```

**方式二：直接编辑配置文件**

```bash
# 全局配置
vim ~/.commit_ai_guardian/config.yaml

# 或项目级配置
vim .ai-review/config.yaml
```

**方式三：环境变量（不推荐，会覆盖配置）**

```bash
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
```

### 注意事项

1. proxy 只影响命令行工具（`cag review` / `cag audit`），不影响 Git hook（hook 里调用的命令继承 shell 环境变量）
2. proxy 与 CORS 代理是完全不同的概念，前者用于命令行网络穿透，后者用于浏览器跨域（Demo 页面已移除 CORS 代理功能）
3. 如果配置了 proxy 但 API 仍然不通，检查代理工具是否正常运行、端口是否正确
