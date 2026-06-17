---
title: Thread.sleep 误报
severity: 3
level: info
category: 最佳实践
tags: [并发, 线程, 轮询]
languages: [java]
---

## 问题描述

`Thread.sleep()` 在轮询/等待场景中是必要的，不要误报为性能问题。

## 为什么这不是问题

在某些业务场景下（如轮询检查任务状态、限流控制、定时重试），`Thread.sleep()` 是正确的做法。替换为 `ScheduledExecutorService` 等方式虽然更优雅，但并非必须。

## 参考

- [Java Concurrency - Timing](https://docs.oracle.com/javase/tutorial/essential/concurrency/sleep.html)

---

## 坏代码 ❌

### 无意义 sleep

```java
// 没有任何注释说明为什么 sleep
Thread.sleep(1000);
// 继续执行...
```

---

## 好代码 ✅

### 使用 ScheduledExecutorService

```java
ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(1);
scheduler.scheduleAtFixedRate(this::checkStatus, 0, 1, TimeUnit.SECONDS);
```

---

## 可接受代码 🆗（白名单）

### 轮询场景中的 sleep

```java
// 轮询检查任务完成状态，间隔 1 秒
while (!task.isCompleted()) {
    Thread.sleep(1000);  // 可接受：有明确注释说明用途
    log.debug("等待任务完成...");
}
```

### 限流控制中的 sleep

```java
// 控制 API 调用频率，避免触发限流
for (String id : idList) {
    callExternalApi(id);
    Thread.sleep(200);  // 可接受：每个请求间隔 200ms
}
```

---

## 检查清单

- [ ] Thread.sleep 是否有注释说明用途？
  - 有明确注释 → 可接受，不要报
  - 无注释且看不出目的 → 建议添加注释（info 级别）
- [ ] 是否在循环中 sleep 但没有退出条件？
  - 没有退出条件 → 可能死循环，应该报 warning
