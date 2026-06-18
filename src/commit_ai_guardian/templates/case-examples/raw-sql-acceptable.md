---
title: 原生 SQL 查询（MyBatis/JPA）
severity: 0
level: info
category: 最佳实践
tags: [sql, mybatis, jpa, orm]
languages: [java]
---

## 问题描述

使用 MyBatis 或 JPA 的原生 SQL 查询是正常的开发方式，不要误报为 SQL 注入风险。

---

## 可接受代码 🆗（白名单）

### MyBatis 注解方式

```java
@Select("SELECT * FROM users WHERE status = #{status}")
List<User> findByStatus(@Param("status") Integer status);
```

### MyBatis XML 方式

```xml
<select id="findById" resultType="User">
    SELECT * FROM users WHERE id = #{id}
</select>
```

### JPA Native Query

```java
@Query(value = "SELECT * FROM orders WHERE create_time > ?1", nativeQuery = true)
List<Order> findRecentOrders(LocalDateTime since);
```

### MyBatis-Plus QueryWrapper

```java
// 使用框架提供的条件构造器，参数自动转义
queryWrapper.eq("status", status)
            .like("name", keyword);
```

---

## 检查清单

- [ ] SQL 中是否使用了 `#{}` 或 `?` 占位符？
  - 使用占位符 → 安全，可接受，不要报
  - 使用 `${}` 拼接 → 有注入风险，应该报
- [ ] 动态 SQL 的参数是否来自用户输入且未转义？
  - 未转义直接拼接 → 有注入风险，应该报
