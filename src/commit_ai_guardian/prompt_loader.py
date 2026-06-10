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
DEFAULT_SYSTEM_MESSAGE = """你是一位专业的代码审核专家，擅长发现代码中的问题并给出改进建议。

🚨🚨🚨 输出格式规则（违反会导致解析失败，审核结果作废）🚨🚨🚨

【规则1 - 最高优先级】最终输出必须且只能包含一对 <result> 标签，JSON 必须包裹其中：
  ✅ 正确: <result>{"summary":"...","passed":...,"issues":[...]}</result>
  ❌ 错误: {"summary":"...","passed":...}                    （缺少 <result> 标签）
  ❌ 错误: ```json {...}```                                    （用了代码块标记）
  ❌ 错误: <result>{...}</result> 之外还有任何其他文字       （有额外文字）

【规则2】可以先用 <think> 标签写思考过程，但 <think> 和 <result> 必须分开：
  ✅ 正确: <think>思考...</think>\n<result>{...}</result>
  ❌ 错误: 把 JSON 放在 <think> 标签内

【规则3】不要添加任何解释、前言、总结——<result> 标签外除了 <think> 之外不要有任何文字。"""

DEFAULT_DIFF_REVIEW_TEMPLATE = """你是一位资深代码审核专家。请对以下代码变更进行严格审核。

## 审核维度（通用规则）
1. **Bug 检测**: 逻辑错误、空指针、边界条件、资源泄漏、并发问题等
2. **安全漏洞**: SQL注入、XSS、敏感信息泄露、硬编码密码、不安全的反序列化等
3. **代码风格**: 命名规范、代码格式、注释质量、代码组织
4. **性能问题**: 算法复杂度、内存泄漏、不必要的计算、大数据量处理
5. **最佳实践**: 设计模式、代码复用、错误处理、日志规范
6. **文档完整**: 函数文档、参数说明、返回值说明、复杂逻辑注释

## 严重级别定义
- **critical**: 必须修复，会导致系统崩溃或严重安全漏洞
- **error**: 应该修复，明确的 Bug 或安全问题
- **warning**: 建议修复，风格或最佳实践问题
- **info**: 仅供参考，轻微改进建议

## 代码信息
- 文件: {{filename}}
- 语言: {{language_display}}
- 变更类型: {{status}}

## 代码变更内容
```{{language}}
{{diff_content}}
```
{{cases_text}}
## 🚨 输出格式（不遵守会导致审核失败）

【必须】把 JSON 包裹在 <result></result> 标签中，除此之外不要有任何其他文字：

✅ 正确示例（无问题）：
<result>{"summary":"总体评价（2-3句话）","passed":true,"issues":[]}</result>

✅ 正确示例（有问题）：
<result>{"summary":"...","passed":false,"issues":[{"severity":"warning","category":"style","line_number":15,"message":"问题描述","suggestion":"修复建议","code_snippet":"相关代码"}]}</result>

❌ 错误示例（不要这样输出）：
- 直接输出裸 JSON: {"passed":false,...}
- 用 ```json 包裹: ```json\n{"passed":false,...}\n```
- <result> 标签外还有解释文字

severity 只能是 critical/error/warning/info，category 只能是 bug/security/style/performance/best-practice/documentation
- 如无问题，issues 为空数组，passed 为 true
- line_number 为代码左侧标注的行号（如 " 145 | +const x = ..." 中的 145）
- 只关注本次变更引入的问题，不要审核已有代码
{{cases_note}}
- 尽量给出具体的修复建议，不要泛泛而谈"""

DEFAULT_FULL_FILE_TEMPLATE = """你是一位资深代码审核专家。请对以下完整代码文件进行全面审核。

## 审核维度（通用规则）
1. **Bug 检测**: 逻辑错误、空指针、边界条件、资源泄漏、并发问题等
2. **安全漏洞**: SQL注入、XSS、敏感信息泄露、硬编码密码、不安全的反序列化等
3. **代码风格**: 命名规范、代码格式、注释质量、代码组织
4. **性能问题**: 算法复杂度、内存泄漏、不必要的计算、大数据量处理
5. **最佳实践**: 设计模式、代码复用、错误处理、日志规范
6. **文档完整**: 函数文档、参数说明、返回值说明、复杂逻辑注释

## 严重级别定义
- **critical**: 必须修复，会导致系统崩溃或严重安全漏洞
- **error**: 应该修复，明确的 Bug 或安全问题
- **warning**: 建议修复，风格或最佳实践问题
- **info**: 仅供参考，轻微改进建议

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
## 🚨 输出格式（不遵守会导致审核失败）

【必须】把 JSON 包裹在 <result></result> 标签中，除此之外不要有任何其他文字：

✅ 正确示例（无问题）：
<result>{"summary":"总体评价（2-3句话）","passed":true,"issues":[]}</result>

✅ 正确示例（有问题）：
<result>{"summary":"...","passed":false,"issues":[{"severity":"warning","category":"style","line_number":15,"message":"问题描述","suggestion":"修复建议","code_snippet":"相关代码"}]}</result>

❌ 错误示例（不要这样输出）：
- 直接输出裸 JSON: {"passed":false,...}
- 用 ```json 包裹: ```json\n{"passed":false,...}\n```
- <result> 标签外还有解释文字

severity 只能是 critical/error/warning/info，category 只能是 bug/security/style/performance/best-practice/documentation
- 如无问题，issues 为空数组，passed 为 true
- line_number 为代码左侧标注的行号（如 "145 | const x = ..." 中的 145）
- 对整个文件进行全面审核，不限于变更部分
{{cases_note}}
- 尽量给出具体的修复建议，不要泛泛而谈"""

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
