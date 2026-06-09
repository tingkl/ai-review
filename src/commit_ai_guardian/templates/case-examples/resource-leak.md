---
title: 资源泄漏
severity: 6
level: error
category: bug
tags: [资源, 连接, 文件]
languages: [python, java, javascript, go, rust]
---

## 问题描述

文件、数据库连接、锁等未正确释放

## 为什么这是个问题

打开的资源如果不关闭，会持续占用系统资源。高并发时可能导致资源耗尽，系统无法响应。

## 不修复的后果

- 文件句柄耗尽，无法打开新文件
- 数据库连接池耗尽
- 内存泄漏

---

## 坏代码 ❌

### 手动 open/close（异常时不关闭）

```python
f = open("data.txt")
data = f.read()
f.close()  # 如果上面抛异常，这里不会执行
```

---

## 好代码 ✅

### with 语句自动关闭

```python
with open("data.txt") as f:
    data = f.read()
```

---

## 检查清单

- [ ] 文件打开是否用了 `with`/`try-finally`？
  - 搜索 `open(` 但不包含 `with` 的地方
- [ ] 数据库连接是否正确关闭？
  - 检查 `conn.close()` 是否在 `finally` 中
