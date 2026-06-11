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
    "1. Bug 检测: 逻辑错误、边界条件、资源泄漏、并发问题等（不包含空指针检查）\n"
    "2. 代码风格: 命名规范、代码格式、注释质量、代码组织\n"
    "3. 性能问题: 算法复杂度、内存泄漏、不必要的计算、大数据量处理\n"
    "4. 最佳实践: 设计模式、代码复用、错误处理、日志规范\n"
    "5. 文档完整: 函数文档、参数说明、返回值说明、复杂逻辑注释\n"
    "\n"
    "5. window.location 读取 vs 修改——不要混淆\n"
    "- 读取 location 属性（如 window.location.protocol, .host, .pathname, .href）是正常操作，没有安全风险，不要报\n"
    "- 只有显式赋值给 location 才是跳转/修改行为：window.location = url, window.location.href = url\n"
    "- 反例: val = window.location.protocol + '//' + val → 这是读取 protocol，报 warning 直接修改全局 location 存在安全风险 → 误报\n"
    "\n"
    "6. 不要假设业务场景来报问题\n"
    "- 不要基于你猜测的业务场景（如金融、医疗、支付等）来报问题\n"
    "- 只根据代码本身的事实报问题，不要脑补业务背景\n"
    "- 反例: money函数将0视为falsy值直接返回原值，但在金融场景中0是有效数据 → 用户没说是金融场景，这是 AI 脑补的 → 误报\n"
    "\n"
    "7. 不要建议给函数参数加防御性类型检查\n"
    "- 函数参数（如 idx、row、item）视为合法传入的值，不要建议添加 typeof、isNaN、Number.isInteger 等防御性检查\n"
    "- 除非代码中已经出现了因该参数导致的实际 Bug（如 for 循环用非整数索引崩溃），否则不要报\n"
    "- 反例: 函数 addSlotArr(arr, idx) 中 AI 报 warning: 建议添加类型检查确保传入有效值 → 无实际 Bug 证据 → 误报\n"
    "\n"
    "8. 空指针检查——只有明显的才报\n"
    "- 默认不审核空指针问题，除非代码中存在明显的空指针\n"
    "- 明显的空指针包括：\n"
    "  a) 显式 null 赋值后使用：let x = null; x.foo()\n"
    "  b) 调用链中已知为 null 的节点：obj.a.b.c 其中 obj.a 在前面已被赋值为 null\n"
    "  c) 可选链与直接访问矛盾：已用 obj?.a 但后面写 obj.a.b（没考虑 obj 为 null 的情况）\n"
    "- 不是明显的空指针 → 不报，尤其是函数参数、外部传入的变量\n"
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
