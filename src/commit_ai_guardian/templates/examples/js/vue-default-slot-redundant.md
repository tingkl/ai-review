---
title: Vue 默认插槽冗余使用 <template #default>
severity: warning
category: 代码风格
tags: [vue, slot, default, 冗余]
languages: [vue, javascript]
---

## 问题描述

组件只使用默认插槽时，显式包裹 `<template #default>` 是冗余的。默认插槽内容可直接写在组件标签内。

> **限定范围：仅针对单一默认插槽，且无具名插槽混用的场景。**

---

## 坏代码 ❌

```vue
<vxe-form-item title="任务标题" span="24">
  <template #default>
    {{ form.title }}
  </template>
</vxe-form-item>
```

---

## 好代码 ✅

```vue
<vxe-form-item title="任务标题" span="24">
  {{ form.title }}
</vxe-form-item>
```

---

## 检查清单

- [ ] 组件内部是否只使用了 `<template #default>` 一个插槽？
- [ ] 移除后语义是否不变？
- [ ] 是否存在具名插槽混用？若存在可保留。