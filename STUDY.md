# Commit AI Guardian 学习笔记

> 本文件记录学习过程中的问答，方便回顾和查漏补缺。

---

## 目录

- [第1课：基础数据结构](#第1课基础数据结构)
- [第2课：配置管理](#第2课配置管理)
- [第3课：模板加载](#第3课模板加载)
- [第4课：案例驱动审核](#第4课案例驱动审核)
- [第5课：核心引擎架构](#第5课核心引擎架构)
- [第6课：JSON解析的7种策略](#第6课json解析的7种策略)
- [第7课：AI修复JSON](#第7课ai修复json)
- [第8课：Hook安装与工具链集成](#第8课hook安装与工具链集成)
- [核心设计原则](#核心设计原则背诵)

---

## 第1课：基础数据结构

### Q: 二进制文件是怎么判断的？

**A:** 启发式检测，两个条件（只读前8KB）：

1. 包含空字节 `\0` → 二进制文件通常有，文本文件几乎没有
2. 非ASCII字符比例 > 30% → 二进制文件的"乱码"字节大多 > 127

局限：UTF-8中文文件如果中文比例很高可能误判。

---

## 第2课：配置管理

### Q: `use_cache: false` 时，系统还会计算 MD5 吗？

**A:** 会。MD5 有两个用途：
- **缓存键值** → `use_cache: false` 时跳过
- **日志文件名** → 始终使用（`{md5前7位}.ai.log`）

所以即使关闭缓存，MD5 仍用于标识日志文件。

### Q: `??` 和 `||` 有什么区别？

**A:**
- `??` — 仅对 `null` 和 `undefined` 使用默认值
- `||` — 对所有 falsy 值（0、""、false、null、undefined）使用默认值

代码中的选择逻辑：
```typescript
const model = this.config.model ?? "gpt-4o-mini";  // 只有 undefined 时用默认
const passed = Boolean(data.passed ?? true);          // 只有 undefined 时默认 true
```

### Q: temperature 配置有什么用？

**A:** 控制 AI 输出的随机性：

| 值 | 效果 | 适用场景 |
|-----|------|---------|
| 0.0 | 最确定，每次输出几乎一样 | JSON 修复 AI（固定） |
| 0.3 | 平衡，有一定灵活性 | 主审核 AI（默认） |
| 0.7 | 较灵活，可能发现更多问题 | 需要更激进审核时 |
| 1.0+ | 最随机，不推荐 | 不推荐用于代码审核 |

**设计说明**：
- 主审核 AI 用 `0.3`：需要一定灵活性发现不同角度的问题，太小容易思维僵化
- JSON 修复 AI 固定 `0.0`：纯格式转换不需要任何随机性，完全确定性输出更可靠

### Q: json_fix_history_mode 是什么？

**A:** 控制 JSON 修复 AI 的上下文策略：

| 模式 | 全称 | 行为 | 适用场景 |
|------|------|------|---------|
| `full` | 完整历史（默认） | 累积所有失败 attempt 的对话 | 复杂 JSON 修复 |
| `last` | 只带上次 | 只保留最近一次失败 | 简单修复，节省 token |

**full 模式对话流**：
```
Attempt 1: System → User(原始JSON) → Assistant(fixed_v1) → ❌
Attempt 2: System → User(原始JSON) → Assistant(fixed_v1) → User(错误1)
             → Assistant(fixed_v2) → ❌
Attempt 3: System → User(原始JSON) → Assistant(fixed_v1) → User(错误1)
             → Assistant(fixed_v2) → User(错误2) → Assistant(fixed_v3) → ✅
```

AI 能看到完整的修复过程，避免重复犯已修好的错误。

---

## 第3课：模板加载

### Q: 文件语言是怎么判断的？

**A:** 双策略：
1. Git diff 中的 `+++ b/src/xxx.vue` → 从后缀 `.vue` 判断
2. 后缀找不到 → 用 `linguist` 库分析内容

用于匹配对应语言的案例（`.ai-review/cases/{语言}/`）。

### Q: 为什么system message和user message要分离？

**A:**
- **system** → 通用规则（审核维度、格式约束、严重级别定义）— AI必须遵守
- **user** → 具体任务（代码、案例引用）— 每次请求不同

分离的好处：
1. system message 可复用（所有文件共用一套规则）
2. user message 只放"这次要审什么"
3. 符合 OpenAI 最佳实践

---

## 第4课：案例驱动审核

### Q: 案例文件格式是什么？

**A:** Markdown + YAML frontmatter：

```markdown
---
severity: error
category: bug
---

### 标题

说明文字...

**坏代码：**
```python
问题代码
```

**好代码：**
```python
正确代码
```

**检查点：**
- [ ] 是否xxx
```

### Q: 案例怎么控制prompt长度？

**A:** 三种级别：

| 级别 | 保留 | 去掉 | token节省 |
|------|------|------|-----------|
| `default` | 全部 | — | 0% |
| `compact` | 说明+坏代码+好代码+检查点 | 原因+后果 | ~35% |
| `minimal` | 坏代码+检查点 | 其他全部 | ~55% |

配置：`case_format: compact`（全局或项目级 config.yaml）

---

## 第5课：核心引擎架构

### Q: 审核引擎的整体架构是什么样的？

**A:**

```
┌─────────────────────────────────────────────────────────────┐
│  AIEngine（核心引擎）                                        │
│  ┌─────────────┐  ┌─────────────┐                          │
│  │ reviewFile()│  │reviewSource()│  双模式入口               │
│  │   (diff)    │  │  (full)     │                           │
│  └──────┬──────┘  └──────┬──────┘                           │
│         └────────┬────────┘                                  │
│                  ▼                                           │
│  ┌──────────────────────────────────────┐                   │
│  │  1. 构建 prompt（system + user）      │                   │
│  │  2. 检查缓存（MD5 命中 → 直接返回）    │                   │
│  │  3. 调用 OpenAI API（3次重试）         │                   │
│  │  4. 解析 JSON 响应（7种本地策略）      │                   │
│  │  5. AI 修复 JSON（3次尝试）            │                   │
│  │  6. 构建 ReviewResult（双重校验）      │                   │
│  └──────────────────────────────────────┘                   │
│                  ▼                                           │
│  ┌──────────────────────────────────────┐                   │
│  │  并发控制：Promise.all /              │                   │
│  │  ThreadPoolExecutor(4)               │                   │
│  │  —— 任一异常 → 全部阻断              │                   │
│  └──────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
```

双模式设计：
- **`reviewFile()`** — 审核 Git diff（增量，关注变更部分）
- **`reviewSource()`** — 审核完整文件（全量，扫描现有代码）

### Q: 审核一条代码的完整数据流是什么？

**A:**

```
Git diff / 文件内容
  → 构建 prompt
    ├── system message（通用规则：审核维度、格式约束）
    └── user message（具体任务：代码 + 案例 + 审核维度）
  → 计算 MD5 → 查缓存
    ├── 命中 → 返回缓存结果
    └── 未命中 → 调用 API
  → 调用 OpenAI API
    ├── 发送请求（temperature=0.3, max_tokens=8192）
    ├── 等待响应（带超时 + 3次重试）
    └── 写入 ai.log
  → 解析响应
    ├── 提取 <result> 标签内的 JSON
    ├── tryParseJson() — 7种本地修复策略
    └── 都失败 → _fixJsonWithAi() — AI修JSON
  → 构建 ReviewResult
    ├── 字段校验（severity、category、line_number）
    ├── passed 双重校验（AI返回值 + issues重算）
    └── 写入缓存
  → 返回 ReviewResult（passed决定commit是否阻断）
```

### Q: 并发审核是怎么工作的？

**A:** Node.js 用 `Promise.all()`，Python 用 `ThreadPoolExecutor(4)`。

核心原则：**任一异常 → 全部阻断**。并发中的单个文件审核失败，整个commit被阻断，防止"部分审核通过、部分漏审"。

实现要点：
- 不因为某个文件审核慢而阻塞其他文件
- 所有结果收集完后再统一判断 passed
- 异常文件 passed=False，但不影响其他正常文件的审核结果

### Q: 什么是JSON Schema约束？

**A:** 通过 OpenAI 的 `response_format.json_schema` 参数，强制 AI 返回固定格式的 JSON：

```python
REVIEW_JSON_SCHEMA = {
    "name": "code_review_result",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "passed": {"type": "boolean"},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": ["critical","error","warning","info"]},
                        "category": {"type": "string", "enum": ["Bug检测","安全","代码风格","性能","最佳实践","文档"]},
                        "line_number": {"type": "integer"},
                        "message": {"type": "string"},
                        "suggestion": {"type": "string"},
                        "code_snippet": {"type": "string"},
                    },
                    "required": ["severity", "category", "line_number", "message"],
                    "additionalProperties": False,
                }
            }
        },
        "required": ["summary", "passed", "issues"],
        "additionalProperties": False,
    }
}
```

作用：让 AI 做**填空题**而不是**作文题**，保证输出格式固定可解析。

### Q: AI API调用有哪些安全措施？

**A:**

1. **`_check_prerequisites()`** — 前置检查：
   - 未启用(enabled=False) → 直接通过
   - API key未配置 → 阻断并提示
   - OpenAI客户端未初始化 → 阻断并提示

2. **`_call_api_safe()`** — 安全调用包装：
   - 捕获所有异常
   - 3次重试（指数退避：1s → 2s → 4s）
   - JSON Schema约束：强制返回合规JSON格式

3. **模型特定参数**：
   - DeepSeek-R1：关闭thinking模式（`enable_thinking=false`）
   - 避免AI输出`<think>`标签浪费token

### Q: 阻断commit的双重检查是什么？

**A:**

1. **业务层阻断**：issue.severity >= threshold → 阻断（发现严重问题）
2. **系统异常兜底**：result.passed = False → 阻断（解析失败/网络错误/AI异常）

双重保险：即使业务层漏了，系统异常也能拦住。

---

## 第6课：JSON解析的7种策略

### Q: 为什么需要 tryParseJson？Schema 约束不够吗？

**A:** `response_format: { json_schema: REVIEW_JSON_SCHEMA }` 让 AI "尽量"按格式输出，但不是100%可靠。AI 仍可能产生：
- BOM 头（Windows 编辑器遗留）
- 单引号代替双引号
- Trailing comma（最后一个元素后多逗号）
- 注释（`//` 或 `/* */`）
- 非法转义序列（如 `\x`）
- 括号不匹配（流式输出被截断）

**原则**：本地修复成本低（正则替换），不要动不动就调用 AI 修 JSON（消耗 token + 延迟）。7 种策略都失败了，才交给 `_fixJsonWithAi()`。

### Q: 快速通道：空数组和空对象怎么处理的？

**A:** 在 `parseAiResponse()` 中，提取 JSON 字符串后、调用 `tryParseJson()` 之前先做快速检查：

```typescript
const trimmed = jsonStr.trim();
if (trimmed === "[]") {
  result.summary = "AI returned empty array [], treated as passed";
  result.passed = true;
  return result;
}
if (trimmed === "{}") {
  result.summary = "AI returned empty object {}, treated as passed";
  result.passed = true;
  return result;
}
```

**为什么要在 tryParseJson 之前拦截？**

`"[]"` 的问题链：
```
AI 返回 "[]"
  → tryParseJson("[]")
  → JSON.parse("[]") 成功，返回 []（数组！）
  → 检查 !Array.isArray([]) → false（是数组，不满足条件）
  → tryParseJson 返回 null
  → parseAiResponse 误判为 "JSON 解析失败" ❌
```

`"{}"` 能 parse 成功，但 `data.summary` 是 undefined，后续字段提取也出问题。提前拦截更干净。

### Q: 策略1-3（直接解析、BOM去除、单引号替换）怎么工作的？

**A:** 三个策略简单直接，一次性收集所有候选字符串：

```typescript
const candidates = [];
const trimmed = jsonStr.trim();

candidates.push(trimmed);                          // 策略1：原样解析
candidates.push(trimmed.replace(/^\uFEFF/, ""));   // 策略2：去除 BOM
const singleQuoted = trimmed.replace(/'/g, '"');
if (singleQuoted !== trimmed) candidates.push(singleQuoted);  // 策略3：单引号→双引号
```

**示例：**

| 策略 | 输入 | 处理后 | 说明 |
|------|------|--------|------|
| 1 | `{"passed":true}` | 原样 | 正常情况 |
| 2 | `\uFEFF{"passed":true}` | `{"passed":true}` | 去掉 BOM |
| 3 | `{'passed':true}` | `{"passed":true}` | 单引号变双引号 |

### Q: 策略4（去除 trailing comma）怎么工作的？

**A:** 正则匹配最后一个元素后面的多余逗号：

```typescript
const noTrailing = trimmed.replace(/,\s*([}\]])/g, "$1");
```

**正则解析：** `,\s*([}\]])`
- `,` — 匹配逗号
- `\s*` — 可选空白
- `([}\]])` — 捕获组：匹配 `}` 或 `]`
- `$1` — 用捕获组替换（只保留 `}` 或 `]`）

**示例：**

```json
// AI 可能返回（trailing comma）
{
  "passed": true,
  "issues": [],
}

// 修复后
{
  "passed": true,
  "issues": []
}
```

### Q: 策略5（去除注释）怎么工作的？

**A:** 分别去除行注释和块注释：

```typescript
const noComment = trimmed
  .replace(/\/\/.*?$/gm, "")           // 行注释 //...
  .replace(/\/\*[\s\S]*?\*\//g, "");   // 块注释 /* ... */
```

**示例：**

```json
// AI 可能返回
{
  "passed": true,  // 表示审核通过
  "issues": []     /* 没有问题 */
}

// 修复后
{
  "passed": true,
  "issues": []
}
```

### Q: 策略6（修复非法转义）怎么工作的？

**A:** 两步修复：

```typescript
// Step 1：\' → '（JSON 不需要转义单引号）
let fixedEscapes = trimmed.replace(/\\'/g, "'");

// Step 2：非法转义 → 双转义（把反斜杠本身也转义掉）
fixedEscapes = fixedEscapes.replace(
  /\\([^"\\\/bfnrtu])/g,
  "\\\\$1"
);
```

**正则 `\\([^"\\\/bfnrtu])` 解析：**
- `\\` — 匹配一个反斜杠
- `(...)` — 捕获组
- `[^...]` — 否定字符类：**不**匹配这些字符
- `"\\\/bfnrtu` — JSON 标准允许的转义字符

**示例：**

```json
// AI 可能写（非法转义 \U 和 \n）
{"message": "Error at C:\Users\name"}

// Step 2 修复后（\U → \\U，\n → \\n）
{"message": "Error at C:\\Users\\name"}
// \\ 表示字面意义的反斜杠，正确！
```

### Q: 策略7（括号补全）怎么工作的？为什么需要4个状态变量？

**A:** 处理流式输出被截断（网络超时或 max_tokens 不够）：

```typescript
if (trimmed.startsWith("{")) {
  let openBraces = 0;    // 未闭合的 {
  let openBrackets = 0;  // 未闭合的 [
  let inString = false;  // 是否在字符串内部
  let escaped = false;   // 当前字符是否被转义

  for (let i = 0; i < trimmed.length; i++) {
    const ch = trimmed[i];
    if (escaped) { escaped = false; continue; }
    if (ch === "\\") { escaped = true; continue; }
    if (ch === '"') { inString = !inString; continue; }
    if (inString) continue;  // 字符串内部的括号不算！
    if (ch === "{") openBraces++;
    else if (ch === "}") openBraces--;
    else if (ch === "[") openBrackets++;
    else if (ch === "]") openBrackets--;
  }

  let fixed = trimmed;
  for (let i = 0; i < openBrackets; i++) fixed += "]";
  for (let i = 0; i < openBraces; i++) fixed += "}";
}
```

**4个状态变量的作用：**

| 变量 | 如果不处理，会出什么错？ |
|------|------------------------|
| `inString` | `"缺少 { 符号"` 里的 `{` 会被误计为 openBraces++ |
| `escaped` | `"C:\\Users"` 里的 `\"` 会误切换 inString |

**示例：**

```json
// AI 返回（被截断！max_tokens 不够）
{
  "summary": "发现2个问题",
  "passed": false,
  "issues": [
    {"severity": "error", "message": "空指针风险",

// 状态机计数：openBraces=2, openBrackets=1
// 修复后：补全 ]}}
{
  "summary": "发现2个问题",
  "passed": false,
  "issues": [
    {"severity": "error", "message": "空指针风险",
  ]}
}
```

### Q: 7种策略都失败后怎么办？

**A:** `tryParseJson` 返回 `null`，整体降级链路继续：

```
AI 返回响应
  → parseAiResponse()
    ├── 快速通道："[]" / "{}" → 直接通过
    ├── tryParseJson() — 7种本地策略
    │     全部失败 → 返回 null
    → _parseResponse 检测到 "JSON parse failed"
    → _fixJsonWithAi() — 让另一个AI修JSON（最多3次）
    → 3次都失败 → passed=false（阻断commit）
```

---

## 第7课：AI修复JSON

### Q: AI修复JSON是怎么工作的？

**A:** `_fixJsonWithAi()` 方法，核心机制是**错误反馈循环**：

```
Attempt 1: 调用AI修复JSON
            ↓
        解析失败？收集具体的schema校验错误
            ↓
Attempt 2: 把错误信息反馈给AI（"上次修复后仍有以下错误：xxx"）
            ↓
        解析失败？继续收集错误
            ↓
Attempt 3: 再次反馈
            ↓
        还是失败 → 放弃，返回null
```

**关键点：**
- `all_attempts_log` 收集所有3次尝试（含失败），最后统一写入 `.json_fix.log`
- 每次反馈包含具体的schema校验错误（如"issues[0].severity值'高'不在枚举中"）
- 即使3次都失败，日志也保存完整的尝试链

### Q: AI修复时遇到空数组/空对象/空result怎么处理？

**A:** 与本地解析对应，AI修复端同样有特殊处理：

**空数组 `[]`**：
- `_fixJsonWithAi` 中也检测 `"[]"` → 视为无问题，直接通过（passed=True）
- 不浪费token调用修复AI

**`<result></result>`为空**：
- 视为审核通过（passed=True）
- AI认为没有发现问题但忘了输出JSON内容
- 避免误报为系统错误

### Q: `_build_result_from_dict`怎么处理各种边界情况？

**A:** 多层防御：

1. **AI返回数组**：
   - 空数组`[]` → passed=True（无问题）
   - 非空数组 → passed=False（类型错误）

2. **字段校验**：
   - `summary`为空 → 默认"审核完成"
   - `issues`缺失 → 默认空数组
   - `passed`缺失 → 默认True

3. **Issue字段校验**：
   - `message`为空字符串 → 跳过该issue（无效问题）
   - `severity`不在枚举中 → 默认"info"
   - `category`不在枚举中 → 默认"最佳实践"（Schema枚举已改为中文）

4. **Passed双重校验**（最重要）：
   - 先取AI返回的passed值
   - 再根据issue severity重算：
     - 有warning/error/critical → **强制passed=False**
     - 只有info或issues为空 → 保持原passed值

### Q: JSON修复模板的passed为什么去掉硬编码？

**A:** 原模板示例 `{"summary":"修复说明","passed":true,"issues":[]}` 导致AI总是返回passed=true。

改为：
- passed取决于issues内容（不硬编码）
- 有warning/error/critical → passed=false
- 只有info或issues为空 → passed=true
- summary要求有意义（"发现X个问题"而非"修复说明"）

### Q: JSON修复后summary为什么重新生成？

**A:** JSON修复AI返回的summary通常是"修复说明"等无意义文字。根据实际issues重新生成：
- 有issues → `发现N个问题（X个warning, Y个info）`
- 无issues → `AI审核完成，未发现问题`

### Q: JSON修复日志为什么每次尝试都保存？

**A:**
1. `all_attempts_log` 收集所有3次尝试（含失败），最后统一写入
2. 能看到哪次尝试了、为什么失败、错误反馈是什么
3. 3次都失败时，日志包含完整的尝试链，方便定位问题

### Q: `_write_json_fix_log` 为什么去掉 `cache_md5` 空值检查？

**A:** 调用方保证 `cache_md5` 一定有值（计算自内容MD5），不会为空。去掉多余的防御代码。

### Q: JSON修复成功后为什么打印 json_fix.log 路径？

**A:** 原来只打印 cache 和 ai.log 路径。JSON修复成功后额外打印 json_fix.log 的绝对路径，方便直接定位JSON修复AI的完整对话记录。

---

## 第8课：Hook安装与工具链集成

### Q: husky v9+怎么兼容？

**A:** 检测`core.hooksPath`，如果包含".husky"就追加到`.husky/pre-commit`，与lint-staged共存。

### Q: lint-staged的exit code怎么处理？

**A:** 检测lint-staged是否保存了exit code。如果简写版（`npx lint-staged`一行）没有保存，自动修正为完整版（保存exit code + if判断）。

---

## 核心设计原则（背诵）

1. 让AI做填空题（schema），不是作文题（自由文本）
2. Prompt只放AI记不住的东西（业务规则、案例）
3. 代码兜底比prompt约束可靠100倍
4. 所有异常默认阻断
