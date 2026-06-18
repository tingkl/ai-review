---
title: 冗余的 number | null 联合类型声明
severity: 3
level: warning
category: style
tags: [TypeScript, 冗余, null, 联合类型, 可选链]
languages: [typescript]
---

## 问题描述

用 `let` 声明变量并显式标注 `number | null`，先初始化为 `null`，再通过条件分支赋值，属于冗余写法。`number` 变量在需要时自然可以承载 `null`，更地道的做法是用可选链和空值合并一次性表达可空语义。

## 为什么这是个问题

- 引入不必要的可变状态（`let`），增加心智负担
- `| null` 类型注解使签名冗长，且容易在多处复制
- 条件分支赋值可以被 `?.` / `??` 一行替代，意图更清晰

## 不修复的后果

- 代码风格拖沓，重复出现类似的防御性样板
- 后续维护者容易误改成更复杂的判空逻辑，扩大冗余范围

---

## 坏代码 ❌

### 显式声明 `number | null` 再条件赋值

```typescript
let resourceId: number | null = null;
const resource = await this.resourceService.findOneByBloggerId(
  bloggerId,
  platformId,
  'id',
);
if (resource) resourceId = resource.id;
```

---

## 好代码 ✅

### 用可选链 + 空值合并简化

```typescript
const resource = await this.resourceService.findOneByBloggerId(
  bloggerId,
  platformId,
  'id',
);
const resourceId = resource?.id ?? null;
```

### 如果下游允许 undefined，直接透传更简洁

```typescript
const resourceId = resource?.id;
```

---

## 检查清单

- [ ] 是否用 `let x: number | null = null` 再条件赋值的模式？
  - 优先改为 `const x = maybe?.field ?? null`
- [ ] 显式的 `| null` 是否带来了真正的类型安全，还是只是重复表达"可能不存在"？
  - 在 TypeScript 中，`number` 变量本身可以被赋值为 `null`，无需通过联合类型来强调
- [ ] 下游消费方是否可以接受 `undefined` 或 `null`？
  - 若可以，直接用可选属性透传，避免中间变量