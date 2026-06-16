---
title: XSS 跨站脚本攻击
severity: 9
level: critical
category: 安全漏洞
tags: [XSS, HTML, 前端]
languages: [javascript, python, java, php]
---

## 问题描述

用户输入未经转义直接输出到 HTML 页面

## 为什么这是个问题

攻击者可以注入恶意脚本，当其他用户浏览页面时执行，窃取 Cookie、伪造请求等。

## 不修复的后果

- 用户 Cookie 被盗，账号被劫持
- 页面内容被篡改
- 钓鱼攻击

## 参考

- [OWASP - XSS](https://owasp.org/www-community/attacks/xss/)

---

## 坏代码 ❌

### innerHTML 插入用户输入

```javascript
element.innerHTML = userInput;
```

---

## 好代码 ✅

### textContent 代替 innerHTML

```javascript
element.textContent = userInput;
```

---

## 检查清单

- [ ] `innerHTML`、`document.write` 是否插入了用户输入？
  - 搜索 `innerHTML =` 和 `document.write`
- [ ] 模板渲染是否使用了 `|safe` 或类似标记？
  - 检查是否绕过自动转义
