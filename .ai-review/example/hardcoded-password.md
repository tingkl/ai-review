---
title: 硬编码密码/密钥
severity: 9
level: critical
category: 安全漏洞
tags: [密码, 密钥, 配置]
languages: [python, java, javascript, go, rust, php]
---

## 问题描述

密码、API Key、密钥等敏感信息直接写在代码中

## 为什么这是个问题

代码会被提交到 Git 仓库，所有有权限的人都能看到。一旦泄露，攻击者可以直接使用这些凭证访问系统。

## 不修复的后果

- 生产环境凭证泄露
- 数据库/第三方服务被非法访问
- 数据被窃取或篡改

## 参考

- [OWASP - Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)

---

## 坏代码 ❌

### 明文密码

```python
DB_PASSWORD = "MyP@ssw0rd123"
API_KEY = "sk-abc123xyz789"
```

---

## 好代码 ✅

### 环境变量

```python
DB_PASSWORD = os.environ.get("DB_PASSWORD")
API_KEY = os.environ.get("API_KEY")
```

---

## 检查清单

- [ ] 代码中是否有明文密码、token、密钥？
  - 搜索 `password`、`secret`、`token`、`key` 等关键词
- [ ] 是否使用了环境变量或配置中心？
  - 生产环境配置应该与代码分离
