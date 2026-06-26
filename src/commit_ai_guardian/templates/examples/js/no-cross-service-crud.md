---
title: 禁止跨 Service 直接调用其他 Service 的私有方法
severity: warning
category: 最佳实践
tags: [TypeScript, NestJS, Service, 架构, 业务边界, 私有方法]
languages: [typescript]
---

## 问题描述

一个 Service 在处理自身业务时，直接调用另一个 Service 的 `_` 开头的私有方法（如 `_updateById`、`_findById`、`_find`、`_create`、`_updateMany` 等底层 CRUD 方法），并携带强业务语义的数据。这会让业务动作散落在调用方，破坏模块边界，导致后续查找和修改困难。

> **注意**：调用其他 Service 暴露的公共业务方法（如 `userPaymentService.notifyByWechatTransfer`）是允许的，属于正常的服务编排。

## 为什么这是个问题

- `_` 私有方法属于数据访问层，不具备业务语义，调用方需要解释字段含义
- 强业务动作被隐藏在调用方，目标 Service 失去了对核心业务规则的封装
- 容易出现 `as any` 绕过类型检查，增加运行时风险
- 业务调整时需要全局搜索所有调用方，维护成本高

## 不修复的后果

- 业务规则散落在多个 Service 中，形成隐式依赖
- 字段含义、状态值、触发条件在调用方重复解释
- 修改一个业务状态需要多处同步，容易遗漏

---

## 可接受代码 🆗（白名单）

### 跨 Service 调用公共业务方法

```typescript
// wechat-transfer-notify.service.ts
return this.userPaymentService.notifyByWechatTransfer(decryptData);
```

`notifyByWechatTransfer` 是 `UserPaymentService` 暴露的公共业务方法，属于正常的服务编排。

---

## 坏代码 ❌

### 在 DailySettlementService 中直接调用 OrderNoService 的 `_updateById`

```typescript
await this.orderNoService._updateById(orderId, { dailyAudit: 1 } as any);
```

这里 `dailyAudit: 1` 是「订单已进入日结审核」的强业务状态，却被外部 Service 通过私有方法直接写入。

---

## 好代码 ✅

### 由 OrderNoService 暴露具有业务语义的方法

```typescript
// order-no.service.ts
async markDailyAudited(orderId: number): Promise<void> {
  await this._updateById(orderId, { dailyAudit: 1 });
}
```

### 调用方使用业务方法

```typescript
// daily-settlement.service.ts
await this.orderNoService.markDailyAudited(orderId);
```

---

## 检查清单

- [ ] 是否在对其他 Service 调用 `_updateById`、`_findById`、`_find`、`_create`、`_updateMany` 等 `_` 开头的私有方法？
  - 如果是强业务动作，应由目标 Service 提供语义化的公共业务方法
- [ ] 调用时是否使用了 `as any` 来绕过类型检查？
  - 这通常是私有方法不适合当前调用场景的信号
- [ ] 被修改的字段是否具有业务状态含义？
  - 如 `dailyAudit`、`status`、`payFlag` 等，应封装在所属 Service 内
- [ ] 是否需要跨 Service 批量查询数据？
  - 纯查询可接受暴露 `findByIds`、`findByConditions` 等受限查询方法，但仍应避免调用方直接拼条件修改数据