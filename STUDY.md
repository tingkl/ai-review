# Commit AI Guardian 学习笔记

> 本文件记录学习过程中的问答，方便回顾和查漏补缺。

---

## 目录

- [第1课：基础数据结构](#第1课基础数据结构)
- [第2课：配置管理](#第2课配置管理)
- [第3课：模板加载](#第3课模板加载)
- [第4课：案例驱动审核](#第4课案例驱动审核)
- [第5课：核心引擎 ai-engine.ts](#第5课核心引擎)
- [第6课：Hook安装](#第6课hook安装)
- [第7课：JSON修复与空数组处理](#第7课json修复与空数组处理)
- [核心设计原则](#核心设计原则)

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

**A:** 会！MD5有两个用途：

| 用途 | use_cache=false时的行为 |
|------|------------------------|
| 缓存key | 不检查、不写入 |
| 日志文件名 | **始终使用** |

### Q: `??` 和 `||` 有什么区别？

**A:**
- `??` — 空值合并。左边是null/undefined才返回右边，`false`就返回`false`
- `||` — 逻辑或。左边是falsy（含false/0/""）就返回右边

用`??`可以区分"用户明确设置了false"和"用户没设置"。

---

## 第3课：模板加载

### Q: 文件语言是怎么判断的？

**A:** 通过文件后缀名查表 `EXTENSION_LANGUAGE_MAP`，55+种扩展名映射到语言。

### Q: 为什么system message和user message要分离？

**A:**
- system放格式约束（你是谁、怎么输出）— 注意力权重更高
- user放具体任务（审什么代码）— 每次不同
- 两边不重复，节省token

---

## 第4课：案例驱动审核

### Q: 案例文件格式是什么？

**A:** Markdown + YAML frontmatter

### Q: 案例怎么控制prompt长度？

**A:** 三种级别：

| 级别 | 保留内容 | token节省 |
|------|---------|----------|
| default | 全部 | 0% |
| compact | 去掉原因+后果 | ~35% |
| minimal | 只留坏代码+检查点 | ~55% |

---

## 第5课：核心引擎

### Q: AI API调用有哪些安全措施？

**A:**

1. **_check_prerequisites()** — 前置检查：
   - 未启用(enabled=False) → 直接通过
   - API key未配置 → 阻断并提示
   - OpenAI客户端未初始化 → 阻断并提示

2. **_call_api_safe()** — 安全调用包装：
   - 捕获所有异常
   - 3次重试（指数退避：1s → 2s → 4s）
   - JSON Schema约束：强制返回合规JSON格式

3. **模型特定参数**：
   - DeepSeek-R1：关闭thinking模式（`enable_thinking=false`）
   - 避免AI输出`<think>`标签浪费token

### Q: 什么是JSON Schema约束？

**A:** 通过OpenAI的`response_format.json_schema`参数，强制AI返回固定格式的JSON：

```python
REVIEW_JSON_SCHEMA = {
    "name": "code_review_result",
    "strict": True,  # 严格模式，不允许额外字段
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
                        "category": {"type": "string", "enum": ["bug","security","style","performance","best-practice","documentation"]},
                        "line_number": {"type": "integer"},
                        "message": {"type": "string"},
                        "suggestion": {"type": "string"},
                        "code_snippet": {"type": "string"},
                    },
                    "required": ["severity", "category", "line_number", "message"],
                    "additionalProperties": False,  # 不允许额外字段
                }
            }
        },
        "required": ["summary", "passed", "issues"],
        "additionalProperties": False,
    }
}
```

作用：让AI做**填空题**而不是**作文题**，保证输出格式固定可解析。

### Q: JSON解析失败后怎么处理？

**A:** 6层降级策略：

1. `<result>`标签提取
2. 过滤`<think>` + `` ```json ``代码块提取
3. 正则找第一个`{...}`
4. 本地修复（BOM/单引号/trailing comma/非法转义）
5. **AI修复JSON** — 调用另一个AI专门修JSON语法（最多3次，含错误反馈）
6. 都失败 → passed=False阻断commit

### Q: AI修复JSON是怎么工作的？

**A:** `_fix_json_with_ai()` 方法：

**核心机制 — 错误反馈循环：**
```
Attempt 1: 调用AI修复JSON
            ↓
        解析失败？收集错误信息
            ↓
Attempt 2: 把错误信息反馈给AI（"上次修复后仍有以下错误：xxx"）
            ↓
        解析失败？收集错误信息
            ↓
Attempt 3: 再次反馈错误信息
            ↓
        还是失败 → 放弃，返回null
```

**关键点：**
- `all_attempts_log` 收集所有3次尝试（含失败），统一写入 `.json_fix.log`
- 每次反馈包含具体的schema校验错误（如"issues[0].severity值'高'不在枚举中"）
- 即使3次都失败，日志也保存完整的尝试链

### Q: AI返回空数组`[]`时怎么处理？

**A:** 直接视为审核通过（passed=True），不调用JSON修复AI。避免浪费token。

在 `parse_ai_response()` 和 `_fix_json_with_ai()` 两处都有处理：
- `parse_ai_response`：空数组 → passed=True，返回
- `_fix_json_with_ai`：空数组 → 视为无问题，直接通过

### Q: AI返回空对象`{}`时怎么处理？

**A:** 同样视为审核通过（passed=True）。

在 `parseAiResponse` / `parse_ai_response` 中，提取 JSON 后、调用 `tryParseJson` 之前先做快速检查：
- `jsonStr.trim() === "{}"` → passed=True，返回
- 避免 `tryParseJson` 返回 null 导致误判为解析失败

**为什么要放在 tryParseJson 之前？** 因为 `tryParseJson` 只返回对象（有 `!Array.isArray` 检查），但空对象 `{}` 虽然能通过 `JSON.parse()`，却在后续字段提取时产生问题（`data.summary` 为 undefined）。提前拦截更干净。

### Q: `<result></result>`为空时怎么处理？

**A:** 视为审核通过（passed=True）。AI认为没有发现问题但忘了输出JSON内容。避免误报为系统错误。

### Q: `_build_result_from_dict`怎么处理各种边界情况？

**A:** 多层防御：

1. **AI返回数组**：
   - 空数组`[]` → passed=True（无问题）
   - 非空数组 → passed=False（类型错误，需要修复）

2. **字段校验**：
   - `summary`为空 → 默认"审核完成"
   - `issues`缺失 → 默认空数组
   - `passed`缺失 → 默认True

3. **Issue字段校验**：
   - `message`为空字符串 → 跳过该issue（无效问题）
   - `severity`不在枚举中 → 默认"info"
   - `category`不在枚举中 → 默认"best-practice"

4. **Passed双重校验**（最重要）：
   - 先取AI返回的passed值
   - 再根据issue severity重算：
     - 有warning/error/critical → **强制passed=False**
     - 只有info或issues为空 → 保持原passed值

### Q: 为什么并发异常要返回passed=False？

**A:** 所有异常默认阻断，防止系统异常时静默放行有问题的代码。

### Q: 阻断commit的双重检查是什么？

**A:**

1. issue.severity >= threshold → 阻断（业务问题）
2. result.passed = False → 阻断（系统异常兜底）

---

## 第6课：Hook安装

### Q: husky v9+怎么兼容？

**A:** 检测`core.hooksPath`，如果包含".husky"就追加到`.husky/pre-commit`，与lint-staged共存。

### Q: lint-staged的exit code怎么处理？

**A:** 检测lint-staged是否保存了exit code。如果简写版（`npx lint-staged`一行）没有保存，自动修正为完整版（保存exit code + if判断）。

---

## 第7课：JSON修复与空数组处理

### Q: JSON修复模板的passed为什么去掉硬编码？

**A:** 原模板示例 `{"summary":"修复说明","passed":true,"issues":[]}` 导致AI总是返回passed=true。改为：
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

## 第8课：JSON解析的"急诊室" — tryParseJson 的7种修复策略

### Q: 为什么需要 tryParseJson？Schema 约束不够吗？

**A:** `response_format: { json_schema: REVIEW_JSON_SCHEMA }` 让 AI "尽量"按格式输出，但不是100%可靠。AI 仍可能产生：
- BOM 头（Windows 编辑器遗留）
- 单引号代替双引号
- Trailing comma（最后一个元素后多逗号）
- 注释（// 或 /* */）
- 非法转义序列（如 \x）
- 括号不匹配（流式输出被截断）

**原则**：本地修复成本低（正则替换），不要动不动就调用 AI 修 JSON（消耗 token + 延迟）。7 种策略都失败了，才交给 `_fixJsonWithAi()`。

---

### Q: 快速通道：空数组 `"[]"` 和空对象 `"{}"` 怎么处理的？

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

**为什么要放在 tryParseJson 之前？**

看 `"[]"` 的问题链：
```
AI 返回 "[]"
  → tryParseJson("[]")
  → JSON.parse("[]") 成功，返回 []（数组！）
  → 检查 !Array.isArray([]) → false（是数组，不满足条件）
  → 所有候选都返回 []，都不满足 "必须是对象"
  → tryParseJson 返回 null
  → parseAiResponse 误判为 "JSON 解析失败" ❌
```

而 `"{}"` 虽然能 parse 成功，但 `data.summary` 是 undefined，后续处理也会出问题。提前拦截更干净。

---

### Q: 策略1-3（直接解析、BOM去除、单引号替换）怎么工作的？

**A:** 这三个策略简单直接，一次性收集所有候选字符串：

```typescript
const candidates = [];
const trimmed = jsonStr.trim();

// 策略1：原样解析（最常见，直接成功）
candidates.push(trimmed);

// 策略2：去除 BOM 头（Windows 记事本保存的 UTF-8 文件可能带 \uFEFF）
candidates.push(trimmed.replace(/^\uFEFF/, ""));

// 策略3：单引号 → 双引号
const singleQuoted = trimmed.replace(/'/g, '"');
if (singleQuoted !== trimmed) candidates.push(singleQuoted);
```

**示例：**

| 策略 | 输入 | 处理后 | 说明 |
|------|------|--------|------|
| 1 | `{"passed":true}` | 原样 | 正常情况 |
| 2 | `\uFEFF{"passed":true}` | `{"passed":true}` | 去掉 BOM |
| 3 | `{'passed':true}` | `{"passed":true}` | 单引号变双引号 |

---

### Q: 策略4（去除 trailing comma）怎么工作的？

**A:** 用正则匹配最后一个元素后面的多余逗号：

```typescript
const noTrailing = trimmed.replace(/,\s*([}\]])/g, "$1");
```

**正则解析：** `,\s*([}\]])`
- `,` — 匹配逗号
- `\s*` — 可选的空白字符
- `([}\]])` — 捕获组：匹配 `}` 或 `]`
- `$1` — 用捕获组的内容替换整个匹配（即只保留 `}` 或 `]`）

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

**注意**：这个正则一次处理所有 trailing comma，全局替换（`g` 标志）。

---

### Q: 策略5（去除注释）怎么工作的？

**A:** 分别去除行注释和块注释：

```typescript
const noComment = trimmed
  .replace(/\/\/.*?$/gm, "")      // 行注释 //...
  .replace(/\/\*[\s\S]*?\*\//g, ""); // 块注释 /* ... */
```

**示例：**

```json
// AI 可能返回（"贴心"地加了注释）
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

---

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
- `(...)` — 捕获组（后面用 `$1` 引用）
- `[^...]` — 否定字符类：**不**匹配这些字符
- `"\\\/bfnrtu` — JSON 标准允许的转义字符（`\" \\ \/ \b \f \n \r \t \u`）

**示例：**

```json
// AI 可能写（非法转义 \x）
{"message": "Error at C:\Users\name"}
//                    ^^    ^
//                    \U 非法 \n 被当成换行！

// Step 1 后（无变化，没有 \'）
{"message": "Error at C:\Users\name"}

// Step 2 后（\U → \\U，\n → \\n）
{"message": "Error at C:\\Users\\name"}
// 现在 \\ 表示字面意义的反斜杠，正确！
```

---

### Q: 策略7（括号补全）怎么工作的？为什么需要4个状态变量？

**A:** 处理流式输出被截断的情况（网络超时或 max_tokens 不够）：

```typescript
if (trimmed.startsWith("{")) {
  let openBraces = 0;    // 未闭合的 {
  let openBrackets = 0;  // 未闭合的 [
  let inString = false;  // 是否在字符串内部
  let escaped = false;   // 当前字符是否被转义

  for (let i = 0; i < trimmed.length; i++) {
    const ch = trimmed[i];
    if (escaped) { escaped = false; continue; }  // 跳过转义字符
    if (ch === "\\") { escaped = true; continue; } // 下一字符被转义
    if (ch === '"') { inString = !inString; continue; } // 切换字符串状态
    if (inString) continue;  // 字符串内部的括号不算！
    if (ch === "{") openBraces++;
    else if (ch === "}") openBraces--;
    else if (ch === "[") openBrackets++;
    else if (ch === "]") openBrackets--;
  }

  // 补全缺失的括号
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
// AI 返回了（被截断了！max_tokens 不够）
{
  "summary": "发现2个问题",
  "passed": false,
  "issues": [
    {"severity": "error", "message": "空指针风险",

// 状态机计数结果：
// openBraces = 2（最外层 { + issues[0] 的 {）
// openBrackets = 1（issues 数组的 [）

// 修复后：补全 ]}}
{
  "summary": "发现2个问题",
  "passed": false,
  "issues": [
    {"severity": "error", "message": "空指针风险",
  ]}
}
// 虽然内容不完整，但至少能 parse 了！
```

---

### Q: 7种策略都失败后怎么办？

**A:** `tryParseJson` 返回 `null`，`parseAiResponse` 设置 `passed = false`，然后 `_parseResponse` 检测到错误关键词，调用 `_fixJsonWithAi()` —— 让另一个 AI 来修 JSON。

**整体降级链路：**

```
AI 返回响应
  → parseAiResponse()
    → 快速通道："[]" / "{}" → 直接通过
    → tryParseJson() 7种策略
      ├── 策略1：直接解析
      ├── 策略2：BOM去除
      ├── 策略3：单引号→双引号
      ├── 策略4：去除trailing comma
      ├── 策略5：去除注释
      ├── 策略6：修复非法转义
      └── 策略7：括号补全
    → 7种都失败 → tryParseJson 返回 null
    → parseAiResponse 标记 passed=false
  → _parseResponse 检测错误关键词
    → _fixJsonWithAi()（另一个AI修JSON，最多3次）
    → 3次都失败 → passed=false（阻断commit）
```

---

## 核心设计原则（背诵）

1. 让AI做填空题（schema），不是作文题（自由文本）
2. Prompt只放AI记不住的东西（业务规则、案例）
3. 代码兜底比prompt约束可靠100倍
4. 所有异常默认阻断
