---
title: 查询条件中空字符串过滤
severity: 0
level: info
category: 最佳实践
tags: [mongoose, mongodb, 查询条件, 空字符串, 过滤]
languages: [typescript, javascript]
---

## 问题描述

前端查询表单在清空或默认状态下，通常会把字段值回传为空字符串 `''`，其业务语义是「不限定 / 不筛选」。

如果后端直接把该字段赋值给 Mongoose 查询对象，就会变成精确匹配空字符串，导致结果集为空或不符合用户预期。因此需要先判断非空，再决定是否将条件加入查询对象。

> **限定范围**：来自前端、可能为空字符串的查询参数。

---

## 可接受代码 🆗（白名单）

### 空字符串过滤后再加入查询对象

```
    if (deviceSerial) {
      // 过滤掉deviceSerial是空字符串
      params.deviceSerial = deviceSerial;
    }
```

### 通用查询条件构建

```typescript
const params: any = {};
if (phone) {
  params.phone = phone;
}
if (deviceSerial) {
  params.deviceSerial = deviceSerial;
}
const list = await this._findWithPage(params, page, chainOptions);
```

### 数组字段空数组过滤

```typescript
if (tabs?.length) {
  params.tab = { $in: tabs };
}
```

### 同时排除字段不存在和空字符串

在 MongoDB 中，`{ $exists: true }` 只保证字段存在，不保证值非空；`{ $ne: '' }` 只保证值不为空字符串，不保证字段存在。两者语义不同，需要同时满足时应组合使用。

```132:134:mcn-cx/src/u2/u2-sms.service.ts
    const phoneList = await this.u2LogService._distinct('phone', {
      phone: { $exists: true, $ne: '' },
    });
```

等价展开：

```typescript
{ phone: { $exists: true, $ne: '' } }
// 语义：字段存在 且 值不是空字符串
```

---

## 检查清单

- [ ] 查询字段是否来自前端且可能为空字符串？
  - 是 → 建议使用 `if (value)` 或 `if (value !== '')` 判断后再加入查询对象
- [ ] 空字符串在业务上是否表示「不限定」而不是「精确匹配空值」？
  - 是 → 应过滤掉，不要报
- [ ] 是否确实需要查询空字符串？
  - 是 → 显式使用 `{ $eq: '' }` 或 `{ $in: ['', null] }` 等明确表达式，而不是直接赋值
  - 否 → 保留 `if (value)` 过滤逻辑
- [ ] 是否同时需要「字段存在」和「值非空字符串」？
  - 是 → 使用 `{ $exists: true, $ne: '' }` 是合理写法，不要报