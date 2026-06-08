"""AI 审核引擎

核心职责：
- 构建 Prompt（代码 + 审核维度 + 案例参照 → 发给 AI）
- 调用 OpenAI API（含重试、超时、错误处理）
- 解析 AI 的 JSON 响应为结构化数据（ReviewResult）

双模式设计：
- review_file()     → 审核 Git diff（只关注变更部分）
- review_source()   → 审核完整文件（扫描存量代码）

案例系统（新功能）：
- 从 cases/ 目录加载 YAML 案例（坏代码示例 + 好代码示例）
- 审核时把匹配编程语言的案例注入 Prompt
- AI 参照这些具体案例做对比检查，审核更精准

容错原则：任何环节失败都返回 passed=True，绝不阻断用户提交。
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import openai
    import httpx
except ImportError:
    openai = None
    httpx = None


@dataclass
class ReviewIssue:
    """单个审核问题"""
    severity: str = "info"  # critical / error / warning / info
    category: str = "best-practice"  # bug / security / style / performance / best-practice / documentation
    line_number: Optional[int] = None
    message: str = ""
    suggestion: str = ""
    code_snippet: str = ""
    
    def __post_init__(self):
        """验证字段值"""
        valid_severities = ["critical", "error", "warning", "info"]
        if self.severity not in valid_severities:
            self.severity = "info"
        
        valid_categories = ["bug", "security", "style", "performance", "best-practice", "documentation"]
        if self.category not in valid_categories:
            self.category = "best-practice"
        
        # 确保 line_number 是整数或 None
        if self.line_number is not None:
            try:
                self.line_number = int(self.line_number)
            except (ValueError, TypeError):
                self.line_number = None


@dataclass
class ReviewResult:
    """单个文件的审核结果"""
    filename: str = ""
    issues: List[ReviewIssue] = field(default_factory=list)
    summary: str = ""
    passed: bool = True
    raw_response: str = ""


class AIEngine:
    """AI 代码审核引擎
    
    封装了与 OpenAI API 的所有交互，包括：
    - Prompt 构建（审核维度 + 案例参照 + 代码内容）
    - API 调用（含指数退避重试）
    - 响应解析（JSON 提取 + 容错）
    """
    
    def __init__(self, config: Any):
        """初始化
        
        Args:
            config: Config 对象，需要 api_key, api_base, model, timeout, proxy 等字段
        """
        self.config = config
        self.client = None
        
        # 初始化案例加载器（cases/ 目录下的 YAML 案例）
        from .case_loader import CaseLoader
        self.case_loader = CaseLoader()
        
        # 检查 openai 包是否安装
        if openai is None:
            raise RuntimeError("openai 包未安装，请运行: pip install openai")
        
        # 配置 httpx 客户端（支持代理和超时）
        http_kwargs = {}
        if config.proxy:
            http_kwargs["proxies"] = config.proxy  # 设置代理（用于内网/翻墙）
        
        http_kwargs["timeout"] = httpx.Timeout(config.timeout if hasattr(config, 'timeout') else 60)
        
        # 初始化 OpenAI 客户端（兼容第三方 API：Azure、Gemini、本地部署等）
        try:
            self.client = openai.OpenAI(
                api_key=config.api_key,
                base_url=getattr(config, 'api_base', 'https://api.openai.com/v1'),
                http_client=httpx.Client(**http_kwargs) if httpx else None,
            )
        except Exception as e:
            # 初始化失败不抛异常，后续调用时返回降级结果
            print(f"[警告] OpenAI 客户端初始化失败: {e}")
            self.client = None
    
    def review_file(self, file_diff: Any) -> ReviewResult:
        """审核单个文件的 diff（pre-commit 场景）
        
        流程：构建 diff Prompt → 调用 API → 解析响应
        
        Args:
            file_diff: FileDiff 对象，需包含 filename, language, diff_content
            
        Returns:
            ReviewResult。任何失败都返回 passed=True（不阻断提交）
        """
        # 防御：客户端初始化失败
        if self.client is None:
            return ReviewResult(
                filename=getattr(file_diff, 'filename', 'unknown'),
                summary="AI 客户端未初始化，无法审核",
                passed=True,  # ← 不阻止提交
                raw_response="",
            )
        
        # 防御：API Key 未配置
        if not getattr(self.config, 'api_key', None):
            return ReviewResult(
                filename=getattr(file_diff, 'filename', 'unknown'),
                summary="未配置 API Key，跳过审核",
                passed=True,
                raw_response="",
            )
        
        # 构建 Prompt 并调用 AI
        prompt = self._build_prompt(file_diff)
        
        try:
            response = self._call_api(prompt)
            return self._parse_response(response, getattr(file_diff, 'filename', 'unknown'))
        except Exception as e:
            # 任何异常都返回降级结果，不阻断用户
            print(f"[错误] 审核文件 {getattr(file_diff, 'filename', 'unknown')} 失败: {e}")
            return ReviewResult(
                filename=getattr(file_diff, 'filename', 'unknown'),
                summary=f"审核失败: {str(e)}",
                passed=True,  # ← 审核失败也不阻止提交
                raw_response=str(e),
            )
    
    def review_batch(self, file_diffs: List[Any]) -> List[ReviewResult]:
        """
        批量审核多个文件
        
        Args:
            file_diffs: FileDiff 对象列表
            
        Returns:
            ReviewResult 列表
        """
        results = []
        for file_diff in file_diffs:
            result = self.review_file(file_diff)
            results.append(result)
        return results
    
    def _build_prompt(self, file_diff: Any) -> str:
        """
        构建 diff 审核提示词（用于 Git pre-commit 场景）
        
        Args:
            file_diff: FileDiff 对象
            
        Returns:
            完整的 prompt 字符串
        """
        filename = getattr(file_diff, 'filename', 'unknown')
        language = getattr(file_diff, 'language', 'unknown')
        status = getattr(file_diff, 'status', 'modified')
        diff_content = getattr(file_diff, 'diff_content', '')
        
        # 截断过长的 diff
        max_diff_length = 8000
        if len(diff_content) > max_diff_length:
            diff_content = diff_content[:max_diff_length] + "\n... (内容已截断)"
        
        language_display = {
            'python': 'Python', 'javascript': 'JavaScript', 'typescript': 'TypeScript',
            'java': 'Java', 'go': 'Go', 'rust': 'Rust', 'cpp': 'C++',
            'c': 'C', 'csharp': 'C#', 'ruby': 'Ruby', 'php': 'PHP',
        }.get(language, language)
        
        # 加载与当前编程语言匹配的案例
        cases = self.case_loader.get_cases_for_language(language)
        cases_text = self.case_loader.format_cases_for_prompt(cases)

        prompt = f"""你是一位资深代码审核专家。请对以下代码变更进行严格审核。

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
- 文件: {filename}
- 语言: {language_display}
- 变更类型: {status}

## 代码变更内容
```{language}
{diff_content}
```
{cases_text}
## 输出格式
请以 JSON 格式输出，不要包含任何其他文字:
```json
{{
  "summary": "总体评价（2-3句话）",
  "passed": true/false,
  "issues": [
    {{
      "severity": "warning",
      "category": "style",
      "line_number": 15,
      "message": "问题描述",
      "suggestion": "修复建议",
      "code_snippet": "相关代码"
    }}
  ]
}}
```

注意:
- 如无问题，issues 为空数组，passed 为 true
- line_number 为变更代码中的行号
- 只关注本次变更引入的问题，不要审核已有代码
- **重点参照上面的"问题模式"案例进行对比检查**
- 尽量给出具体的修复建议，不要泛泛而谈"""
        
        return prompt
    
    def _call_api(self, prompt: str) -> str:
        """调用 AI API，含指数退避重试
        
        重试策略（最多3次）：
        - 第1次失败：等 1 秒重试
        - 第2次失败：等 2 秒重试  
        - 第3次失败：等 4 秒重试
        - 第3次仍失败：抛异常
        
        覆盖的错误类型：
        - RateLimitError（API 限流）
        - APITimeoutError（请求超时）
        - APIError（服务端错误）
        
        Args:
            prompt: 完整的审核 Prompt（含代码 + 审核维度说明）
            
        Returns:
            AI 的文本响应（JSON 格式，markdown 包裹）
            
        Raises:
            RuntimeError: 3 次重试后仍失败
        """
        model = getattr(self.config, 'model', 'gpt-4o-mini')
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        # system 消息设定 AI 的角色和行为约束
                        {"role": "system", "content": "你是一位专业的代码审核专家，擅长发现代码中的问题并给出改进建议。请严格按照要求的 JSON 格式输出。"},
                        # user 消息是真正的审核请求
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,     # 低温度 = 输出更确定、更可预测
                    max_tokens=2048,     # 限制响应长度（防止超长输出）
                )
                return response.choices[0].message.content or ""
            
            except openai.RateLimitError:  # API 限流（429）
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 指数退避：1, 2, 4
                    print(f"[信息] API 速率限制，{wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    raise RuntimeError("API 速率限制，已达到最大重试次数")
            
            except openai.APITimeoutError:  # 请求超时
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"[信息] API 超时，{wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    raise RuntimeError("API 调用超时")
            
            except openai.APIError as e:  # 其他 API 错误
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"[信息] API 错误 ({e})，{wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    raise RuntimeError(f"API 调用失败: {e}")
            
            except Exception as e:  # 兜底：网络断开等
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"[信息] 调用失败 ({e})，{wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    raise RuntimeError(f"API 调用失败: {e}")
        
        raise RuntimeError("API 调用失败，已达到最大重试次数")
    
    def _parse_response(self, response: str, filename: str) -> ReviewResult:
        """解析 AI 的响应文本为结构化的 ReviewResult
        
        解析策略（层层降级，保证不崩）：
        1. 从 markdown 代码块 ```json ... ``` 中提取 JSON
        2. 如果不行，直接解析整个响应
        3. 如果还不行，尝试修复常见问题（BOM、单引号等）
        4. 最后都失败 → 返回空结果（passed=True）
        
        Args:
            response: AI 返回的原始文本（含 markdown 代码块）
            filename: 被审核的文件名（用于 ReviewResult.filename）
            
        Returns:
            ReviewResult。解析失败也返回 passed=True（不阻断提交）
        """
        result = ReviewResult(filename=filename, raw_response=response)
        
        # 防御：空响应
        if not response or not response.strip():
            result.summary = "API 返回空响应"
            result.passed = True
            return result
        
        # 策略 1：从 ```json ... ``` 或 ``` ... ``` 代码块中提取
        json_str = None
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # 策略 2：直接解析整个响应（AI 没加代码块的情况）
            json_str = response.strip()
        
        if not json_str:
            result.summary = "无法从响应中解析 JSON"
            result.passed = True
            return result
        
        # 策略 3：正常 JSON 解析
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # 策略 4：尝试修复常见 JSON 问题
            json_str = json_str.lstrip('\ufeff')  # 去除 BOM 头
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                # 所有策略都失败了 → 返回空结果
                result.summary = "JSON 解析失败"
                result.passed = True
                return result
        
        # 提取各字段（用 .get() 防止字段缺失时报错）
        result.summary = data.get('summary', '审核完成')
        result.passed = bool(data.get('passed', True))
        
        # 解析 issues 列表
        issues_data = data.get('issues', [])
        if isinstance(issues_data, list):
            for issue_data in issues_data:
                if isinstance(issue_data, dict):
                    issue = ReviewIssue(
                        severity=issue_data.get('severity', 'info'),
                        category=issue_data.get('category', 'best-practice'),
                        line_number=issue_data.get('line_number'),
                        message=issue_data.get('message', ''),
                        suggestion=issue_data.get('suggestion', ''),
                        code_snippet=issue_data.get('code_snippet', ''),
                    )
                    result.issues.append(issue)
        
        return result
    
    def review_source(self, source_file: Any) -> ReviewResult:
        """
        对完整文件内容进行 AI 审核（非 diff 模式）
        
        适用于直接审核指定文件/目录的场景，不依赖 Git diff。
        
        Args:
            source_file: SourceFile 对象或类似对象，需包含 filename, language, content 字段
            
        Returns:
            ReviewResult 审核结果
        """
        # 先检查 API Key（更友好的错误提示）
        if not getattr(self.config, 'api_key', None):
            return ReviewResult(
                filename=getattr(source_file, 'filename', 'unknown'),
                summary="未配置 API Key，跳过审核",
                passed=True,
                raw_response="",
            )
        
        if self.client is None:
            return ReviewResult(
                filename=getattr(source_file, 'filename', 'unknown'),
                summary="AI 客户端未初始化，无法审核",
                passed=True,
                raw_response="",
            )
        
        prompt = self._build_full_file_prompt(source_file)
        
        try:
            response = self._call_api(prompt)
            return self._parse_response(response, getattr(source_file, 'filename', 'unknown'))
        except Exception as e:
            print(f"[错误] 审核文件 {getattr(source_file, 'filename', 'unknown')} 失败: {e}")
            return ReviewResult(
                filename=getattr(source_file, 'filename', 'unknown'),
                summary=f"审核失败: {str(e)}",
                passed=True,
                raw_response=str(e),
            )
    
    def review_source_batch(self, source_files: List[Any]) -> List[ReviewResult]:
        """
        批量审核完整文件
        
        Args:
            source_files: SourceFile 对象列表
            
        Returns:
            ReviewResult 列表
        """
        results = []
        for source_file in source_files:
            result = self.review_source(source_file)
            results.append(result)
        return results
    
    def _build_full_file_prompt(self, source_file: Any) -> str:
        """
        构建完整文件审核的提示词
        
        Args:
            source_file: SourceFile 对象
            
        Returns:
            完整的 prompt 字符串
        """
        filename = getattr(source_file, 'filename', 'unknown')
        language = getattr(source_file, 'language', 'unknown')
        content = getattr(source_file, 'content', '')
        line_count = getattr(source_file, 'line_count', 0)
        
        # 截断过长的文件（保留文件头部，通常包含重要逻辑）
        max_content_length = 8000
        truncated = False
        if len(content) > max_content_length:
            content = content[:max_content_length]
            truncated = True
        
        language_display = {
            'python': 'Python', 'javascript': 'JavaScript', 'typescript': 'TypeScript',
            'java': 'Java', 'go': 'Go', 'rust': 'Rust', 'cpp': 'C++',
            'c': 'C', 'csharp': 'C#', 'ruby': 'Ruby', 'php': 'PHP',
        }.get(language, language)
        
        # 加载与当前编程语言匹配的案例
        cases = self.case_loader.get_cases_for_language(language)
        cases_text = self.case_loader.format_cases_for_prompt(cases)

        prompt = f"""你是一位资深代码审核专家。请对以下完整代码文件进行全面审核。

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
- 文件: {filename}
- 语言: {language_display}
- 总行数: {line_count}
{f"- 注意: 文件内容已截断（超过 8000 字符），只审核前 {max_content_length} 字符" if truncated else ""}

## 完整代码内容
```{language}
{content}
```
{cases_text}
## 输出格式
请以 JSON 格式输出，不要包含任何其他文字:
```json
{{
  "summary": "总体评价（2-3句话）",
  "passed": true/false,
  "issues": [
    {{
      "severity": "warning",
      "category": "style",
      "line_number": 15,
      "message": "问题描述",
      "suggestion": "修复建议",
      "code_snippet": "相关代码"
    }}
  ]
}}
```

注意:
- 如无问题，issues 为空数组，passed 为 true
- line_number 为问题所在的行号
- 对整个文件进行全面审核，不限于变更部分
- **重点参照上面的"问题模式"案例进行对比检查**
- 尽量给出具体的修复建议，不要泛泛而谈"""
        
        return prompt
