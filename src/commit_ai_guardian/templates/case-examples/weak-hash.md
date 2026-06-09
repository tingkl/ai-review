---
title: 弱哈希算法
severity: 8
level: error
category: 安全漏洞
tags: [哈希, 密码, 加密]
languages: [python, java, javascript, go, php]
---

## 问题描述

使用 MD5/SHA1 等不安全的哈希算法

## 为什么这是个问题

MD5 和 SHA1 已经被证明不安全，可以通过彩虹表或暴力破解。密码哈希必须使用带盐的慢哈希算法。

## 不修复的后果

- 密码被破解，用户账号被盗
- 数据库泄露后密码直接被还原

## 参考

- [OWASP - Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)

---

## 坏代码 ❌

### MD5 哈希密码

```python
import hashlib
password_hash = hashlib.md5(password.encode()).hexdigest()
```

---

## 好代码 ✅

### bcrypt 带盐哈希

```python
import bcrypt
password_hash = bcrypt.hashpw(password, bcrypt.gensalt())
```

---

## 检查清单

- [ ] 是否使用了 `md5()` 或 `sha1()`？
  - 搜索 `md5`、`sha1`、`hashlib.md5`
- [ ] 密码是否用了 `bcrypt`/`argon2`/`scrypt`？
  - 确认是慢哈希算法，不是快速哈希
