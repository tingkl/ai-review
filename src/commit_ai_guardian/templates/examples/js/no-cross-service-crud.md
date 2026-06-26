---
title: 禁止跨 Service 调用其他 Service 的 `_` 私有方法
severity: warning
category: 最佳实践
tags: [TypeScript, NestJS, Service, 私有方法, 架构]
languages: [typescript]
---

## 问题描述

跨 Service 调用其他 Service 的 `_` 开头私有方法（如 `_updateById`、`_find`），会导致业务逻辑散落在调用方，破坏模块边界。

> 调用非 `_` 开头的公共业务方法（如 `notifyByWechatTransfer`、`findMonitoring`）完全允许。

## 坏代码 ❌

```typescript
await this.orderNoService._updateById(orderId, { dailyAudit: 1 } as any);
```

## 好代码 ✅

```typescript
// order-no.service.ts
async markDailyAudited(orderId: number) {
  await this._updateById(orderId, { dailyAudit: 1 });
}

// daily-settlement.service.ts
await this.orderNoService.markDailyAudited(orderId);
```

## 检查清单

- [ ] 被调用的方法是否以 `_` 开头？不是则不要报
- [ ] 是否携带 `as any` 绕过类型？是则更可能是私有方法滥用
- [ ] 被修改的字段是否有业务状态语义？应封装到目标 Service 的公共业务方法中
