# Commit AI Guardian 学习笔记

> 本文件记录学习过程中的问答，方便回顾和查漏补缺。

---

## 目录

- [第1课：基础数据结构](#第1课基础数据结构)
- [第2课：配置管理](#第2课配置管理)
- [第3课：模板加载](#第3课模板加载)
- [第4课：案例驱动审核](#第4课案例驱动审核)
- [第5课：核心引擎](#第5课核心引擎)
- [第6课：Hook安装](#第6课hook安装)
- [核心设计原则](#核心设计原则)

---

## 第1课：基础数据结构 (types.ts / utils.ts)

### Q: 二进制文件是怎么判断的？

**A:** 启发式检测算法，两个条件：

1. 检测空字节 `\0` — 二进制文件通常包含 `\0`，文本文件几乎不会有
2. 检测非ASCII字符比例 > 30% — 二进制文件的"乱码"字节大多 > 127

只读前8KB，效率高。局限：UTF-8中文文件如果中文比例很高可能误判。

代码：

```typescript
const chunk = readFileSync(filePath);
if (chunk.includes(0)) return true;  // 条件1：有空字节
// 条件2：非ASCII比例 > 30%
```

---

## 第2课：配置管理 (config.ts)

### Q: `use_cache: false` 时，系统还会计算 MD5 吗？

**A:** 会！MD5有两个用途：

| 用途 | use_cache=false时的行为 |
|------|------------------------|
| 缓存key | 不检查、不写入 |
| 日志文件名 | **始终使用**，不受影响 |

关闭缓存只跳过缓存检查/写入，日志文件照常生成。

### Q: 案例格式化三种级别详细过程？

**A:** 三步：提取 → 选择 → 拼装

**Step 1: 从Markdown提取**
```
案例文件(Markdown)
├── YAML元数据（title, severity, level, languages）
└── Markdown正文
    ├── ## 问题描述      → description
    ├── ## 为什么是个问题 → why_it_matters
    ├── ## 不修复的后果   → consequences
    ├── ## 坏代码        → bad_examples
    ├── ## 好代码        → good_examples
    └── ## 检查清单      → check_points（question + hint）
```

**Step 2: 三种级别选择字段**

| 字段 | default | compact | minimal |
|------|---------|---------|---------|
| title | ✅ | ✅ | ✅ |
| description | ✅ | ✅ | ❌ |
| bad_examples | ✅ | ✅ | ✅ |
| good_examples | ✅ | ✅ | ❌ |
| why_it_matters | ✅ | ❌ | ❌ |
| consequences | ✅ | ❌ | ❌ |
| check_points | ✅ | ✅ | ✅ |
| token/案例 | ~300字 | ~200字 | ~135字 |

**Step 3: 拼装为结构化文本**
```
[案例1|SQL注入|9/critical]
说明: 直接拼接用户输入到SQL语句
❌ 坏代码:
cursor.execute(f"SELECT * FROM {user_id}")
✅ 好代码:
cursor.execute("SELECT * FROM ?", (user_id,))
原因: 数据泄露，数据被篡改
后果: 用户数据被盗，数据库被拖库
check_points: 是否有字符串拼接构建 SQL
提示: 使用参数化查询
```

**为什么设计三种级别？** 案例是prompt中最大的膨胀来源。10个案例default=3000字可能超token限制，minimal=1350字省55%。

### Q: `??` 和 `||` 有什么区别？

**A:**

- `??` — 空值合并运算符。左边是null/undefined才返回右边，`false`就返回`false`
- `||` — 逻辑或。左边是falsy（含false/0/""）就返回右边

用`??`可以区分"用户明确设置了false"和"用户没设置"。

---

## 第3课：模板加载 (prompt-loader.ts)

### Q: 文件语言是怎么判断的？

**A:** 通过文件后缀名查表 `EXTENSION_LANGUAGE_MAP`，55+种扩展名映射到语言。

```typescript
getFileLanguage("src/main.ts")  // → "typescript"
```

### Q: 为什么system message和user message要分离？

**A:**

- system放格式约束（你是谁、怎么输出）— 注意力权重更高
- user放具体任务（审什么代码）— 每次不同
- 两边不重复，节省token

---

## 第4课：案例驱动审核 (case-loader.ts)

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

## 第5课：核心引擎 (ai-engine.ts) — 最重要

### Q: JSON解析失败怎么处理？

**A:** 多层降级策略：

1. `<result>`标签提取
2. 过滤`<think>` + `` ```json ``代码块提取
3. 正则找第一个`{...}`
4. 本地修复（BOM/单引号/trailing comma/非法转义）
5. **AI修复JSON** — 调用另一个AI专门修JSON语法
6. 都失败 → passed=False阻断commit

### Q: 为什么并发异常要返回passed=False？

**A:** 所有异常默认阻断，防止系统异常时静默放行有问题的代码。

### Q: 阻断commit的双重检查是什么？

**A:**

1. issue.severity >= threshold → 阻断（业务问题）
2. result.passed = False → 阻断（系统异常兜底）

---

## 第6课：Hook安装 (hook-installer.ts)

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
