"""Prompt 模板加载器

从项目仓库的 .ai-review/prompts/ 加载 prompt 模板。
找不到就用内置默认模板（容错）。

install 命令会在 .ai-review/ 下创建 prompts/ 目录，写入默认模板文件。
用户可以修改这些模板来自定义 AI 审核的行为和输出格式。

模板变量用 {{variable}} 占位，运行时替换为实际值。
"""

import re
from pathlib import Path
from typing import Optional


# 内置默认模板（模板不存在时的兜底）
DEFAULT_SYSTEM_MESSAGE = (
    "你是一位专业的代码审核专家，擅长发现代码中的问题并给出改进建议。\n"
    "\n"
    "=== 输出格式规则（违反会导致解析失败，审核结果作废） ===\n"
    "\n"
    "[规则1 - 最高优先级] 最终输出必须且只能包含一对 <result> 标签，JSON 必须包裹其中：\n"
    "  正确: <result>{\"summary\":\"...\",\"passed\":...,\"issues\":[...]}</result>\n"
    "  错误: {\"summary\":\"...\",\"passed\":...}                    （缺少 <result> 标签）\n"
    "  错误: ```json {...}```                                    （用了代码块标记）\n"
    "  错误: <result>{...}</result> 之外还有任何其他文字       （有额外文字）\n"
    "\n"
    "[规则2] 不要输出 <think>——直接输出 <result>：\n"
    "  - 错误: <think>让我分析...</think>\\n<result>{...}</result>（浪费token）\n"
    "  - 正确: <result>{...}</result>（直接输出结果）\n"
    "  - <think> 对用户没有价值，只会挤占 <result> 的 token 空间\n"
    "\n"
    "[规则3] 不要添加任何解释、前言、总结——<result> 标签外不要有任何文字。\n"
    "\n"
    "[规则4 - JSON 格式自检] 输出 <result> 前，必须确认 JSON 合法，以下是最常见错误：\n"
    "  1. 字符串值中的双引号必须转义（在 JSON 中写作 \\\"）\n"
    "  2. 字符串值中的反斜杠必须转义（在 JSON 中写作 \\\\）\n"
    "  3. code_snippet 含 { } 时，确保它被完整包裹在字符串引号内，不会破坏 JSON 结构\n"
    "  4. 多个 issue 之间必须有逗号 }, {\"severity\"...，不能写成 }{\"severity\"...（漏逗号）\n"
    "  5. 最后一个字段后不能有逗号（trailing comma）\n"
    "  6. line_number 必须是单个整数（如 80），不能写范围（如 80,81 或 80-81）\n"
    "\n"
    "  常见错误示例：\n"
    "     code_snippet 字段的值以 } 结尾时，后面必须有逗号和引号闭合\n"
    "     line_number 写成 80,81 是非法的，必须是单个整数如 80\n"
    "     message 字段包含双引号时必须转义，否则破坏 JSON 结构\n"
    "\n"
    "=== 审核维度（通用规则） ===\n"
    "1. Bug 检测: 逻辑错误、空指针、边界条件、资源泄漏、并发问题等\n"
    "2. 安全漏洞: SQL注入、XSS、敏感信息泄露、硬编码密码、不安全的反序列化等\n"
    "3. 代码风格: 命名规范、代码格式、注释质量、代码组织\n"
    "4. 性能问题: 算法复杂度、内存泄漏、不必要的计算、大数据量处理\n"
    "5. 最佳实践: 设计模式、代码复用、错误处理、日志规范\n"
    "6. 文档完整: 函数文档、参数说明、返回值说明、复杂逻辑注释\n"
    "\n"
    "=== 空指针检测规则（避免误判） ===\n"
    "\n"
    "原则: 不明确的不假设，明确的正常审。\n"
    "\n"
    "1. 来源不明确的参数 —— 不报\n"
    "对于外部传入、上下文无法确定类型的变量（如函数参数 row、me、options）：\n"
    "- 视为合法传入的值，不做 null/undefined/None 假设\n"
    "- 不要报可能为空、缺少 null 检查之类的问题\n"
    "\n"
    "2. 以下明确情况 —— 正常审核并报\n"
    "| 情况 | 示例 |\n"
    "|------|------|\n"
    "| 显式 null 赋值 | let x = null、const y = undefined |\n"
    "| null 判断但未处理分支 | if (x) { ... } 但 else 分支仍使用 x |\n"
    "| 调用链中已知可能返回 null | obj.a.b.c 其中 obj.a 可能为 null（代码中有相关判断或文档说明） |\n"
    "| 可选链/空值合并使用不当 | 已用 ?. 但仍直接访问属性等矛盾用法 |\n"
    "| 函数调用时明显未传参 | function b(a) {} 被调用为 b()（a 明确为 undefined） |\n"
    "\n"
    "以上情况正常报问题，不要放过。\n"
    "\n"
    "3. 怎么区分来源不明确和明确未传参\n"
    "- b(x) → x 来源不明确 → 不报\n"
    "- b() → 明显未传参，函数定义需要参数但没给 → 报\n"
    "\n"
    "4. 不要推荐防御性编程——暴露根本原因\n"
    "发现空指针/空值风险时，不要建议加 if (item)、if (x != null)、try-catch 之类的防御性代码来隐藏问题。应该：\n"
    "- 追问: 这个空值从哪里来？为什么会产生？\n"
    "- 推荐修复数据质量、接口契约、类型定义、输入校验等根本问题\n"
    "- 如果来源确实无法保证，才允许加防御性检查，但必须说明原因\n"
    "\n"
    "错误建议: 添加 if (item) 判断防止空指针\n"
    "正确建议: pricingList 可能包含 null 元素，建议排查数据来源，在赋值处过滤空值\n"
    "\n"
    "5. 来源不明确的空值风险——severity 最高 info\n"
    "对于参数可能为空但来源不明确、需要追根溯源的情况：\n"
    "- 允许报 info（提示关注），不允许报 warning/error\n"
    "- 示例: em(val, txt) 中 val 可能为空 → info: 函数参数 val 建议确认调用方是否可能传空值\n"
    "- 反例: 把上述情况报成 warning 函数缺少空值检查 → 误报，过度防御\n"
    "\n"
    "6. window.location 读取 vs 修改——不要混淆\n"
    "- 读取 location 属性（如 window.location.protocol, .host, .pathname, .href）是正常操作，没有安全风险，不要报\n"
    "- 只有显式赋值给 location 才是跳转/修改行为：window.location = url, window.location.href = url\n"
    "- 反例: val = window.location.protocol + '//' + val → 这是读取 protocol，报 warning 直接修改全局 location 存在安全风险 → 误报\n"
    "\n"
    "=== 严重级别定义 ===\n"
    "- critical: 必须修复，会导致系统崩溃或严重安全漏洞\n"
    "- error: 应该修复，明确的 Bug 或安全问题\n"
    "- warning: 建议修复，风格或最佳实践问题\n"
    "- info: 仅供参考，轻微改进建议\n"
)
DEFAULT_DIFF_REVIEW_TEMPLATE = """你是一位资深代码审核专家。请对以下代码变更进行严格审核。

审核维度、空指针检测规则、严重级别定义已在 system message 中说明，此处不再重复。

## 代码信息
- 文件: {{filename}}
- 语言: {{language_display}}
- 变更类型: {{status}}

## 代码变更内容
```{{language}}
{{diff_content}}
```
{{cases_text}}

## 输出要求
输出格式规则已在 system message 中说明，此处不再重复。请严格遵守。
{{cases_note}}
- 尽量给出具体的修复建议，不要泛泛而谈
- JSON 自检: 输出前确认字符串引号已转义、issue 之间有逗号、code_snippet 不破坏 JSON 结构"""

DEFAULT_FULL_FILE_TEMPLATE = """你是一位资深代码审核专家。请对以下完整代码文件进行全面审核。

审核维度、空指针检测规则、严重级别定义已在 system message 中说明，此处不再重复。

## 代码信息
- 文件: {{filename}}
- 语言: {{language_display}}
- 总行数: {{line_count}}
{{truncation_note}}

## 完整代码内容
```{{language}}
{{content}}
```
{{cases_text}}

## 输出要求
输出格式规则已在 system message 中说明，此处不再重复。请严格遵守。
{{cases_note}}
- 尽量给出具体的修复建议，不要泛泛而谈
- JSON 自检: 输出前确认字符串引号已转义、issue 之间有逗号、code_snippet 不破坏 JSON 结构"""

# 项目仓库中存放 prompt 模板的目录
REPO_PROMPTS_DIR = Path(".ai-review") / "prompts"


class PromptLoader:
    """Prompt 模板加载器
    
    从项目仓库的 .ai-review/prompts/ 加载模板文件。
    如果找不到，使用内置默认模板（不报错）。
    
    模板变量格式: {{variable_name}}
    """
    
    # 类级别：记录已打印过的模板路径，并发时避免重复打印
    _printed: set = set()
    
    def __init__(self, repo_path: Optional[str] = None):
        """初始化
        
        Args:
            repo_path: 目标代码仓库路径（用于查找 .ai-review/prompts/）
        """
        self.repo_path = repo_path
        self.prompts_dir = self._resolve_prompts_dir()
    
    def _resolve_prompts_dir(self) -> Optional[Path]:
        """查找项目模板目录"""
        if self.repo_path:
            prompts_dir = Path(self.repo_path) / REPO_PROMPTS_DIR
            if prompts_dir.exists():
                return prompts_dir
        return None
    
    def _load_file(self, filename: str, default_content: str) -> str:
        """加载模板文件，找不到返回默认内容
        
        加载成功时打印具体文件路径（每个路径只打印一次，并发安全）。
        
        Args:
            filename: 模板文件名（如 "diff_review.md"）
            default_content: 内置默认内容（兜底）
            
        Returns:
            模板内容字符串
        """
        if self.prompts_dir:
            file_path = self.prompts_dir / filename
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding='utf-8')
                    # 只打印一次（并发安全）
                    path_str = str(file_path)
                    if path_str not in PromptLoader._printed:
                        PromptLoader._printed.add(path_str)
                        print(f"[信息] 加载 prompt 模板: {file_path}")
                    return content
                except Exception as e:
                    print(f"[警告] 读取模板 {file_path} 失败: {e}，使用内置默认")
            else:
                path_str = str(file_path)
                if path_str not in PromptLoader._printed:
                    PromptLoader._printed.add(path_str)
                    print(f"[信息] 模板文件不存在: {file_path}，使用内置默认")
        else:
            msg = f"未找到 .ai-review/prompts/，使用内置默认 {filename}"
            if msg not in PromptLoader._printed:
                PromptLoader._printed.add(msg)
                print(f"[信息] {msg}")
        
        return default_content
    
    def load_system_message(self) -> str:
        """加载 system message 模板"""
        return self._load_file("system_message.txt", DEFAULT_SYSTEM_MESSAGE)
    
    def load_diff_review_template(self) -> str:
        """加载 diff 审核 prompt 模板"""
        return self._load_file("diff_review.md", DEFAULT_DIFF_REVIEW_TEMPLATE)
    
    def load_full_file_template(self) -> str:
        """加载完整文件审核 prompt 模板"""
        return self._load_file("full_file_review.md", DEFAULT_FULL_FILE_TEMPLATE)
    
    @staticmethod
    def render(template: str, **variables) -> str:
        """渲染模板，将 {{variable}} 替换为实际值
        
        Args:
            template: 模板字符串（含 {{variable}} 占位符）
            **variables: 要替换的变量名和值
            
        Returns:
            渲染后的完整字符串
            
        示例:
            rendered = PromptLoader.render(template, filename="main.py", language="python")
        """
        result = template
        for key, value in variables.items():
            placeholder = "{{" + key + "}}"
            result = result.replace(placeholder, str(value))
        return result
    
    @staticmethod
    def get_default_template_files() -> dict:
        """获取所有默认模板文件内容（用于 install 命令创建模板文件）
        
        Returns:
            dict: {filename: content}
        """
        return {
            "system_message.txt": DEFAULT_SYSTEM_MESSAGE,
            "diff_review.md": DEFAULT_DIFF_REVIEW_TEMPLATE,
            "full_file_review.md": DEFAULT_FULL_FILE_TEMPLATE,
        }
