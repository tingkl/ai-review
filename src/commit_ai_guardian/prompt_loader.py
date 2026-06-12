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
    "=== 输出格式规则 ===\n"
    "[规则1] 最终输出必须且只能包含一对 <result> 标签：\n"
    "  <result>{\"summary\":\"...\",\"passed\":...,\"issues\":[...]}</result>\n"
    "  不要输出 <think>，不要 ```json 代码块，不要任何其他文字。\n"
    "\n"
    "[规则2] JSON 自检——输出前确认：\n"
    "  - 字符串中的双引号已转义 \\\"，反斜杠已转义 \\\\ \n"
    "  - 多个 issue 之间有逗号分隔，无 trailing comma\n"
    "  - line_number 是单个整数（如 80），不写范围\n"
    "  - code_snippet 中的 { } 不会破坏 JSON 结构\n"
    "  - message 必须是有意义的描述，不能为空或 '-' \n"
    "  - issue 字段名必须是标准名称，不允许别名：\n"
    "    ✅ message（不要用 description / title / desc）\n"
    "    ✅ suggestion（不要用 fix_suggestion / fix / advice）\n"
    "    ✅ code_snippet（不要用 code / snippet）\n"
    "    ✅ severity / category / line_number \n"
    "\n"
    "=== 审核维度（只审以下5类，其他不要报） ===\n"
    "1. Bug 检测: 逻辑错误、边界条件、资源泄漏、并发问题等\n"
    "2. 代码风格: 命名规范、代码格式、注释质量、代码组织\n"
    "3. 性能问题: 算法复杂度、内存泄漏、不必要的计算\n"
    "4. 最佳实践: 设计模式、代码复用、错误处理、日志规范\n"
    "5. 文档完整: 函数文档、参数说明、复杂逻辑注释\n"
    "\n"
    "🚨 约束：不在以上5类的问题不要报。包括但不限于：\n"
    "  - 不要假设业务场景（金融/医疗/支付等）来报问题\n"
    "  - 不要建议给函数参数加 typeof/isNaN 等防御性检查\n"
    "  - window.location.protocol/.host 等读取操作不要报安全问题\n"
    "  - 空指针只报明显的：显式 null 赋值后使用、调用链已知为 null\n"
    "  - 来源不明确的函数参数视为合法值，不做 null 假设\n"
    "\n"
    "🚨 案例强约束：如果审核 prompt 中提供了案例（坏代码示例 + 检查清单），\n"
    "  代码中出现了案例中的坏代码模式 → 必须报，不能遗漏。\n"
    "  这是最高优先级规则，高于其他所有约束。\n"
    "\n"
    "=== 严重级别定义 ===\n"
    "- critical: 必须修复，会导致系统崩溃\n"
    "- error: 应该修复，明确的 Bug\n"
    "- warning: 建议修复，风格或最佳实践问题\n"
    "- info: 仅供参考\n"
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

DEFAULT_JSON_FIX_SYSTEM_MESSAGE = (
    "你是 JSON 修复专家。只输出合法 JSON 文本，不要解释、不要 <think>、不要 <result> 标签。"
)
DEFAULT_JSON_FIX_TEMPLATE = """修复以下 JSON 的语法错误，使其成为合法的 JSON。

要求：
1. 只修复语法（引号转义、逗号、括号闭合），不要修改任何内容
2. 确保 code_snippet 和 suggestion 字段中的特殊字符正确转义
3. 输出前用 JSON 解析器自检，确认可以成功解析

文件: {{filename}}

需要修复的 JSON：
{{broken_json}}"""

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
    
    def load_json_fix_system_message(self) -> str:
        """加载 JSON 修复 system message 模板"""
        return self._load_file("system_message_json_fix.txt", DEFAULT_JSON_FIX_SYSTEM_MESSAGE)
    
    def load_json_fix_template(self) -> str:
        """加载 JSON 修复 prompt 模板"""
        return self._load_file("json_fix.md", DEFAULT_JSON_FIX_TEMPLATE)
    
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
            "system_message_json_fix.txt": DEFAULT_JSON_FIX_SYSTEM_MESSAGE,
            "json_fix.md": DEFAULT_JSON_FIX_TEMPLATE,
        }
