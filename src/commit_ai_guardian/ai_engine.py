"""AI 审核引擎 - 调用大语言模型对代码变更进行审核."""

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
    """AI 代码审核引擎"""
    
    def __init__(self, config: Any):
        """
        初始化 AI 审核引擎
        
        Args:
            config: Config 配置对象，需包含 api_key, api_base, model, timeout, proxy 字段
        """
        self.config = config
        self.client = None
        
        if openai is None:
            raise RuntimeError("openai 包未安装，请运行: pip install openai")
        
        # 配置 httpx 客户端（支持代理）
        http_kwargs = {}
        if config.proxy:
            http_kwargs["proxies"] = config.proxy
        
        http_kwargs["timeout"] = httpx.Timeout(config.timeout if hasattr(config, 'timeout') else 60)
        
        try:
            self.client = openai.OpenAI(
                api_key=config.api_key,
                base_url=getattr(config, 'api_base', 'https://api.openai.com/v1'),
                http_client=httpx.Client(**http_kwargs) if httpx else None,
            )
        except Exception as e:
            print(f"[警告] OpenAI 客户端初始化失败: {e}")
            self.client = None
    
    def review_file(self, file_diff: Any) -> ReviewResult:
        """
        对单个文件进行 AI 审核
        
        Args:
            file_diff: FileDiff 对象，需包含 filename, language, status, diff_content 字段
            
        Returns:
            ReviewResult 审核结果
        """
        if self.client is None:
            return ReviewResult(
                filename=getattr(file_diff, 'filename', 'unknown'),
                summary="AI 客户端未初始化，无法审核",
                passed=True,  # 不阻止提交
                raw_response="",
            )
        
        if not getattr(self.config, 'api_key', None):
            return ReviewResult(
                filename=getattr(file_diff, 'filename', 'unknown'),
                summary="未配置 API Key，跳过审核",
                passed=True,
                raw_response="",
            )
        
        prompt = self._build_prompt(file_diff)
        
        try:
            response = self._call_api(prompt)
            return self._parse_response(response, getattr(file_diff, 'filename', 'unknown'))
        except Exception as e:
            print(f"[错误] 审核文件 {getattr(file_diff, 'filename', 'unknown')} 失败: {e}")
            return ReviewResult(
                filename=getattr(file_diff, 'filename', 'unknown'),
                summary=f"审核失败: {str(e)}",
                passed=True,  # 审核失败不阻止提交
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
        构建审核提示词
        
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
        
        prompt = f"""你是一位资深代码审核专家。请对以下代码变更进行严格审核。

## 审核维度
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
- 尽量给出具体的修复建议，不要泛泛而谈"""
        
        return prompt
    
    def _call_api(self, prompt: str) -> str:
        """
        调用 AI API，包含重试逻辑
        
        Args:
            prompt: 提示词
            
        Returns:
            API 响应文本
            
        Raises:
            RuntimeError: API 调用失败
        """
        model = getattr(self.config, 'model', 'gpt-4o-mini')
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "你是一位专业的代码审核专家，擅长发现代码中的问题并给出改进建议。请严格按照要求的 JSON 格式输出。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=2048,
                )
                return response.choices[0].message.content or ""
            
            except openai.RateLimitError:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"[信息] API 速率限制，{wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    raise RuntimeError("API 速率限制，已达到最大重试次数")
            
            except openai.APITimeoutError:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"[信息] API 超时，{wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    raise RuntimeError("API 调用超时")
            
            except openai.APIError as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"[信息] API 错误 ({e})，{wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    raise RuntimeError(f"API 调用失败: {e}")
            
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"[信息] 调用失败 ({e})，{wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    raise RuntimeError(f"API 调用失败: {e}")
        
        raise RuntimeError("API 调用失败，已达到最大重试次数")
    
    def _parse_response(self, response: str, filename: str) -> ReviewResult:
        """
        解析 AI 响应为结构化 ReviewResult
        
        Args:
            response: API 响应文本
            filename: 文件名
            
        Returns:
            ReviewResult 对象
        """
        result = ReviewResult(filename=filename, raw_response=response)
        
        if not response or not response.strip():
            result.summary = "API 返回空响应"
            result.passed = True
            return result
        
        # 尝试从 markdown 代码块中提取 JSON
        json_str = None
        
        # 尝试匹配 ```json ... ```
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # 尝试直接解析整个响应
            json_str = response.strip()
        
        if not json_str:
            result.summary = "无法从响应中解析 JSON"
            result.passed = True
            return result
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # 尝试修复常见 JSON 问题后重新解析
            # 1. 去除可能的 BOM
            json_str = json_str.lstrip('\ufeff')
            # 2. 替换单引号为双引号（但要小心嵌套）
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                result.summary = "JSON 解析失败"
                result.passed = True
                return result
        
        # 提取 summary
        result.summary = data.get('summary', '审核完成')
        
        # 提取 passed
        result.passed = bool(data.get('passed', True))
        
        # 提取 issues
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
