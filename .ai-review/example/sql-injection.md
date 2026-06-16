---
title: SQL 注入
severity: 9
level: critical
category: 安全漏洞
tags: [SQL, 注入, 数据库]
languages: [python, java, javascript, go, php]
---

## 问题描述

用户输入直接拼接到 SQL 语句中

## 为什么这是个问题

攻击者可以通过构造特殊的输入来改变 SQL 语句的语义，从而绕过认证、读取敏感数据、甚至删除数据库。

## 不修复的后果

- 数据泄露（用户信息、密码、交易记录）
- 数据被篡改或删除
- 系统被完全控制

## 参考

- [OWASP - SQL Injection](https://owasp.org/www-community/attacks/SQL_Injection)

---

## 坏代码 ❌

### f-string 拼接

```python
query = f"SELECT * FROM users WHERE id = {user_id}"
cursor.execute(query)
```

### format 方法

```python
query = "SELECT * FROM users WHERE id = {}".format(user_id)
cursor.execute(query)
```

---

## 好代码 ✅

### 参数化查询（推荐）

```python
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
```

### ORM 方式

```python
User.objects.filter(id=user_id).first()
```

---

## 检查清单

- [ ] 是否有字符串拼接构建 SQL？
  - 搜索 `+`、`format`、`f-string`、`%` 拼接 SQL 的地方
- [ ] 是否使用了参数化查询？
  - 确认 `execute()` 的第二个参数传了元组/列表
- [ ] ORM 的 `raw()` / `execute()` 是否传了用户输入？
  - 检查 Django ORM 的 `.raw()`、SQLAlchemy 的 `.execute()`
