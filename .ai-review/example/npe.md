---
title: 空指针/None 引用
severity: 7
level: error
category: bug
tags: [空指针, NPE, 判空]
languages: [python, java, javascript, go]
---

## 问题描述

未检查空值就直接使用对象属性或方法

## 为什么这是个问题

对象可能为 None/null 时，直接访问属性或调用方法会抛出异常，导致程序崩溃。

## 不修复的后果

- 程序运行时崩溃
- 用户体验差（500 错误）
- 可能丢失未保存的数据

---

## 坏代码 ❌

### 直接访问可能为 None 的属性

```python
name = user.name  # user 可能为 None
```

### 直接访问可能为空的列表

```python
first = items[0]  # items 可能为空
```

---

## 好代码 ✅

### 判空后使用

```python
name = user.name if user else "anonymous"
```

### 检查列表长度

```python
first = items[0] if items else None
```

---

## 检查清单

- [ ] 使用对象前是否检查了 None/null？
  - 关注函数返回值、数据库查询结果
- [ ] 列表/字典索引前是否检查了长度？
  - 访问 `[0]` 前确认列表非空
