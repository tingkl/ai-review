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
    "=== 输出格式 ===\n"
    "输出包裹在 <result> 标签中：<result>{...}</result>\n"
    "不要 ```json 代码块，不要解释文字。\n"
    "\n"
    "[规则1] JSON 自检（schema 已约束字段名和类型，只需确认内容）：\n"
    "  - message 必须是有意义的描述，不能为空或 '-' \n"
    "  - line_number 是单个整数（如 80），不写范围\n"
    "  - 字符串中的双引号必须转义 \\\"\n"
    "  - code_snippet 中的 { } 必须在字符串引号内，不破坏 JSON 结构\n"
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
    "\n"
    "📌 空指针检查（仅作为提示，不阻断）：\n"
    "  - 明显的空指针可以报，但 severity 必须是 info，不能是 warning/error/critical\n"
    "  - 函数参数、外部传入的变量不做 null 假设\n"
    "  - info 级别仅供参考，不会阻断提交\n"
    "\n"
    "🚨 案例强约束：如果案例中提供了坏代码示例，\n"
    "  代码中出现了案例中的坏代码模式 → 必须报，不能遗漏。\n"
    "  这是最高优先级规则，高于其他所有约束。\n"
    "\n"
    "🆗 白名单约束：如果案例中标记了\"可接受代码\"（🆗），\n"
    "  这种代码虽然看起来和坏代码相似，但实际上是允许的、合法的 → 不要报。\n"
    "  白名单的优先级高于坏代码检测，避免误报。\n"
    "  有些案例可能只有可接受代码（没有坏代码），此时只作为白名单参考。\n"
    "\n"
    "=== 严重级别定义 ===\n"
    "- critical: 必须修复，会导致系统崩溃\n"
    "- error: 应该修复，明确的 Bug\n"
    "- warning: 建议修复，风格或最佳实践问题\n"
    "- info: 仅供参考\n"
    "\n"
    "⚠️ severity 使用建议（避免过度使用 warning）：\n"
    "  - 函数命名不够清晰、缺少注释 → info，不要报 warning\n"
    "  - warning 只用于有实际影响的问题（如性能下降、维护困难、潜在风险）\n"
)
DEFAULT_DIFF_REVIEW_TEMPLATE = """请对以下代码变更进行严格审核。

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
{{cases_note}}
- 尽量给出具体的修复建议，不要泛泛而谈"""

DEFAULT_FULL_FILE_TEMPLATE = """请对以下完整代码文件进行全面审核。

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
{{cases_note}}
- 尽量给出具体的修复建议，不要泛泛而谈"""

DEFAULT_JSON_FIX_SYSTEM_MESSAGE = (
    "你是 JSON 修复专家。严格按以下规则输出：\n"
    "\n"
    "[规则1] 输出格式——用 <result> 标签包裹完整对象：\n"
    "  <result>{\"summary\":\"...\",\"passed\":true/false,\"issues\":[...]}</result>\n"
    "  必须是对象 {}，不要返回数组 [] 或纯文本。\n"
    "  不要 ```json 代码块，不要解释文字。\n"
    "\n"
    "[规则2] 必须包含 3 个顶层字段（缺一不可）：\n"
    "  - summary: 字符串，有意义的内容（如\"发现X个问题\"），不要写\"修复说明\"\n"
    "  - passed: 布尔值（true/false），取决于 issues 的 severity\n"
    "  - issues: 数组，每个 issue 必须有 severity/category/line_number/message\n"
    "\n"
    "[规则3] passed 的值规则（不要硬编码）：\n"
    "  - 有 warning/error/critical 级别 issue → passed: false\n"
    "  - 只有 info 级别或 issues 为空 → passed: true\n"
    "\n"
    "[规则4] 修复语法为主，但为了满足 schema 可以修正字段值：\n"
    "  - 必须修复：引号转义、逗号缺失、括号闭合、trailing comma\n"
    "  - 可以修正字段值（如果原值不满足 schema）：\n"
    "      • line_number 必须是整数，不是整数时改为 0\n"
    "      • severity 必须是：critical/error/warning/info（或中文：致命/错误/警告/提示）\n"
    "      • category 必须是：Bug检测/安全/代码风格/性能/最佳实践/文档\n"
    "  - 禁止：删除 issue、改字段名、改 message/suggestion/code_snippet 的内容\n"
    "  - 特别小心 code_snippet 和 suggestion 中的 { } 不要破坏 JSON 结构\n"
    "\n"
    "[规则5] 截断检测——输出前自检：\n"
    "  - JSON 必须完整闭合（所有 { 有 }，所有 [ 有 ]）\n"
    "  - 最后一个字段后不能有逗号\n"
    "  - 字符串中的双引号必须转义 \\\"\n"
    "\n"
    "[规则6] 错误反馈——如果收到错误提示，针对性修复：\n"
    "  - 根据具体错误精准修复，不要忽略反馈\n"
    "  - 常见错误：字段缺失、类型不对、用了别名（description/fix_suggestion）"
)
DEFAULT_JSON_FIX_TEMPLATE = """修复以下 JSON 的语法错误。

文件: {{filename}}

需要修复的 JSON：
{{broken_json}}

修复要求：
1. 如果 JSON 是数组 [] 或不完整的对象，改为完整对象格式：
   {"summary":"...","passed":..., "issues":[...]}
   ⚠️ passed 的值取决于 issues 内容（不要硬编码）：
      - 如果有 warning/error/critical 级别的 issue → passed 为 false
      - 如果只有 info 级别或 issues 为空 → passed 为 true
   ⚠️ summary 要有意义（如"发现X个问题"或"审核通过"），不要写"修复说明"
2. 如果 JSON 语法错误（引号、逗号、括号），修复语法保持内容不变
3. 输出必须用 <result> 标签包裹修复后的 JSON"""

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
                        import os
                        print(f"[信息] 加载 prompt 模板: {os.path.relpath(file_path)}")
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
        """加载 system message 模板（含用户自定义规则）
        
        加载默认 system message，如果存在 custom_prompt.md 则追加到末尾。
        自定义规则优先级高于默认规则，可覆盖或补充默认约束。
        """
        base = self._load_file("system_message.txt", DEFAULT_SYSTEM_MESSAGE)
        custom = self.load_custom_prompt()
        if custom:
            return f"{base}\n\n=== 用户自定义规则 ===\n{custom}"
        return base
    
    def load_custom_prompt(self) -> str:
        """加载用户自定义 prompt（custom_prompt.md）
        
        从 .ai-review/prompts/custom_prompt.md 加载。
        如果文件不存在或为空，返回空字符串。
        
        Returns:
            自定义 prompt 内容，或空字符串
        """
        custom_path = self.prompts_dir / "custom_prompt.md"
        if not custom_path.exists():
            return ""
        content = custom_path.read_text(encoding='utf-8').strip()
        # 去掉 HTML 注释（<!-- ... -->）
        import re
        content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL).strip()
        return content
    
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
