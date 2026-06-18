---
title: VXE 组件 size 属性冗余或与全局配置不一致
severity: 3
level: warning
category: style
tags: [vxe, size, 全局配置, 冗余, 一致性]
languages: [vue, javascript]
---

## 问题描述

项目全局已在 `vxe.use.js` 中配置 `VxeUI.setConfig({ size: 'mini' })`。VXE 组件标签上再写 `size` 会破坏全局统一：

- 值与全局不一致 → 同一页面控件尺寸参差不齐。
- 值与全局一致 → 冗余代码，后续全局调整尺寸时会被遗漏。

> **限定范围：仅针对 VXE 系列组件（标签名以 `vxe-` 开头）**

---

## 坏代码 ❌

### 与全局配置不一致（全局为 `mini`）

```vue
<vxe-button type="primary" size="small" @click="openTemplateForm(null)">
  创建模板
</vxe-button>
```

```vue
<vxe-input
  v-model="myTemplateSearch"
  placeholder="搜索模板名称"
  size="small"
  clearable
/>
```

```vue
<vxe-textarea
  v-model="templateForm.description"
  placeholder="请输入模板描述（可选）"
  :rows="2"
  size="medium"
/>
```

### 与全局配置一致，但冗余

```vue
<vxe-button size="mini" :icon="$icon.刷新" @click="reloadStoreProducts">
  刷新
</vxe-button>
```

---

## 好代码 ✅

移除 `size` 属性，由全局配置统一接管。

```vue
<vxe-button type="primary" @click="openTemplateForm(null)">创建模板</vxe-button>
```

```vue
<vxe-input v-model="myTemplateSearch" placeholder="搜索模板名称" clearable />
```

```vue
<vxe-textarea
  v-model="templateForm.description"
  placeholder="请输入模板描述（可选）"
  :rows="2"
/>
```

```vue
<vxe-button :icon="$icon.刷新" @click="reloadStoreProducts">刷新</vxe-button>
```

---

## 检查清单

- [ ] 仅限 VXE 组件（`vxe-button`、`vxe-input`、`vxe-textarea`、`vxe-select`、`vxe-number-input`、`vxe-date-picker` 等）是否仍显式声明了 `size` 属性？
- [ ] 无论 `size` 值与全局配置一致还是不一致，均建议移除，由全局统一控制。