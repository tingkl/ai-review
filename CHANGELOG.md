# Changelog

所有版本更新记录。

## [0.2.5] - 2025-06-21

### 改进
- Demo 页面 textarea 高度增大，方便查看完整内容
- 预设案例切换格式不再清空内容
- JSON 修复 AI 支持最多 3 次重试（跟实际工具一致）

### 修复
- 移除已停用模型 deepseek-chat/deepseek-reasoner
- 统一使用 deepseek-v4-pro 作为 DeepSeek 默认模型

## [0.2.4] - 2025-06-21

### 改进
- hook_installer.py 补全缺失的 json_fix_history_mode 配置字段
- README.md 和 technical.md 同步更新 json_fix_history_mode 说明

## [0.2.3] - 2025-06-21

### 新增
- Demo 页面完整配置面板（api/model/language/threshold/max_tokens/temperature）
- Demo 模型下拉列表（按服务商联动）
- Demo 自定义案例面板（SQL注入/Vue命名/空指针规范）
- Demo 自定义审核规则面板（标准/安全优先/性能优先）
- docs/technical.md 技术文档

### 改进
- README.md proxy 配置详细说明
- 统一 hook marker 格式

## [0.2.2] - 2025-06-21

### 新增
- GitHub Actions workflow for PyPI Trusted Publishing

### 改进
- README.md 更新 PyPI 发布状态

## [0.2.1] - 2025-06-21

### 改进
- case_format 默认值改为 compact
- configure 命令新增 case_format 交互配置

### 修复
- cag status 显示不全的问题

## [0.2.0] - 2025-06-20

### 新增
- PyPI 首次发布
- 案例系统（按语言子目录组织）
- 自定义 prompt 模板
- 四级 JSON 容错修复
- 缓存机制

### 改进
- 取消输入端截断策略
- max_tokens 默认提高到 8192
- 文件路径改为相对路径

## [0.1.0] - 2025-06-15

### 新增
- 初始版本
- Git pre-commit hook 安装/卸载
- AI 代码审核（5大维度）
- 两级配置系统（全局+项目）
- 终端彩色输出
