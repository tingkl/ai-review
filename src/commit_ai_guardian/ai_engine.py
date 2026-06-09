"""AI 审核引擎

核心职责：
- 构建 Prompt（代码 + 审核维度 + 案例参照 → 发给 AI）
- 调用 OpenAI API（含重试、超时、错误处理）
- 解析 AI 的 JSON 响应为结构化数据（ReviewResult）

双模式设计：
- review_file()     → 审核 Git diff（只关注变更部分）
- review_source()   → 审核完整文件（扫描存量代码）

案例系统：
- 从目标仓库的 .ai-review/cases/ 加载案例（项目自己的规则）
- 没有内置默认案例！找不到就退回通用规则检查
- 审核时把匹配编程语言的案例注入 Prompt

容错原则：任何环节失败都返回 passed=True，绝不阻断用户提交。
"""

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import openai
    import httpx
except ImportError:
    openai = None
    httpx = None

from .prompt_loader import PromptLoader


def _try_parse_json(json_str: str) -> Optional[Dict]:
    """尝试多种策略解析 JSON，返回 dict 或 None
    
    策略（按顺序）：
    1. 直接解析
    2. 去除 BOM 头
    3. 将单引号替换为双引号
    4. 去除 trailing commas
    5. 去除注释（// 和 /* */）
    
    Args:
        json_str: 可能不规范的 JSON 字符串
        
    Returns:
        解析后的 dict，或 None（所有策略都失败）
    """
    if not json_str or not json_str.strip():
        return None
    
    candidates = [
        json_str.strip(),
        json_str.strip().lstrip('\ufeff'),  # 去 BOM
    ]
    
    # 单引号变双引号（注意不替换引号内的单引号，这里做简单处理）
    single_quoted = json_str.strip().replace("'", '"')
    if single_quoted != json_str.strip():
        candidates.append(single_quoted)
    
    # 去除 trailing commas（}, 和 ], ）
    no_trailing = re.sub(r',(\s*[}\]])', r'\1', json_str.strip())
    if no_trailing != json_str.strip():
        candidates.append(no_trailing)
    
    # 去除 // 注释
    no_comment = re.sub(r'//.*?\n', '\n', json_str.strip())
    if no_comment != json_str.strip():
        candidates.append(no_comment)
    
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            continue
    
    return None


def _build_cases_check_instruction() -> str:
    """构建案例检查指令 — 要求 AI 逐条对照检查清单
    
    当 prompt 中注入了案例时，用这个强指令替代原来的一句话提示，
    确保 AI 真正逐条检查每个检查清单项。
    """
    return (
        "- 【重要】上方提供了具体的\"问题模式\"案例，包含坏代码示例、好代码示例和检查清单\n"
        "- 你必须逐条对照每个检查清单项（☐ 标记），在代码中逐一寻找匹配的问题\n"
        "- 发现坏代码示例中的模式时，必须报告问题，并给出对应的好代码作为修复建议\n"
        "- 不要遗漏任何检查清单项，这是审核的核心要求"
    )


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
    
    def __init__(self, config: Any, repo_path: str = "."):
        """初始化
        
        Args:
            config: Config 对象，需要 api_key, api_base, model, timeout, proxy 等字段
            repo_path: 目标代码仓库路径（用于加载 .ai-review/cases/ 项目级别案例）
        """
        self.config = config
        self.client = None
        self.repo_path = repo_path
        
        # 初始化案例加载器（传入 repo_path，加载 .ai-review/cases/）
        from .case_loader import CaseLoader
        self.case_loader = CaseLoader(repo_path=repo_path)
        
        # 初始化 prompt 模板加载器（传入 repo_path，加载 .ai-review/prompts/）
        self.prompt_loader = PromptLoader(repo_path=repo_path)
        
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
        
        从 .ai-review/prompts/diff_review.md 加载模板，
        找不到就用内置默认模板。
        
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
        
        # 加载模板并渲染
        template = self.prompt_loader.load_diff_review_template()
        prompt = template.replace("{{filename}}", filename)
        prompt = prompt.replace("{{language}}", language)
        prompt = prompt.replace("{{language_display}}", language_display)
        prompt = prompt.replace("{{status}}", status)
        prompt = prompt.replace("{{diff_content}}", diff_content)
        prompt = prompt.replace("{{cases_text}}", cases_text)
        prompt = prompt.replace("{{cases_note}}",
            _build_cases_check_instruction() if cases_text
            else "- 按通用审核维度进行检查")
        
        # 将生成的 prompt 写入 debug.log，方便用户调试
        self._write_debug_log(filename, prompt)
        
        return prompt
    
    def _write_debug_log(self, filename: str, content: str, append: bool = False) -> None:
        """将 debug 信息写入 .ai-review/prompts/debug.log
        
        默认覆盖写入（保留最近一次审查的 prompt）。
        append=True 时追加到文件末尾（用于记录解析错误等信息）。
        
        Args:
            filename: 被审核的文件名（用于日志头部标识）
            content: 要写入的内容
            append: True=追加，False=覆盖
        """
        if not self.repo_path:
            return
        
        debug_log = Path(self.repo_path) / ".ai-review" / "prompts" / "debug.log"
        try:
            from datetime import datetime
            
            if append:
                # 追加模式：添加分隔线和内容
                separator = f"\n\n# --- [{datetime.now().strftime('%H:%M:%S')}] {filename} ---\n\n"
                existing = debug_log.read_text(encoding='utf-8') if debug_log.exists() else ""
                debug_log.write_text(existing + separator + content, encoding='utf-8')
            else:
                # 覆盖模式：标准 prompt debug 头部
                header = f"""# ================================================
# Prompt Debug Log
# 文件: {filename}
# 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# ================================================

"""
                debug_log.write_text(header + content, encoding='utf-8')
        except Exception:
            # 写入失败不报错，不影响正常审核流程
            pass
    
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
                        # system 消息从模板加载（.ai-review/prompts/system_message.txt）
                        {"role": "system", "content": self.prompt_loader.load_system_message()},
                        # user 消息是真正的审核请求（从模板渲染）
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
        data = _try_parse_json(json_str)
        
        if data is None:
            # 策略 4：尝试从响应中提取最外层 {...} 之间的内容
            brace_match = re.search(r'\{.*\}', response, re.DOTALL)
            if brace_match:
                data = _try_parse_json(brace_match.group(0))
        
        if data is None:
            result.summary = "JSON 解析失败"
            result.passed = True
            # 把失败的响应追加到 debug.log 方便排查
            self._write_debug_log(
                f"{filename}.PARSE_ERROR",
                f"AI 返回的内容无法解析为 JSON:\n\n{response}\n\n提示: 请检查 .ai-review/prompts/ 下的模板是否正确要求 JSON 输出",
                append=True
            )
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
        
        从 .ai-review/prompts/full_file_review.md 加载模板，
        找不到就用内置默认模板。
        
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
        
        # 加载模板并渲染
        template = self.prompt_loader.load_full_file_template()
        prompt = template.replace("{{filename}}", filename)
        prompt = prompt.replace("{{language}}", language)
        prompt = prompt.replace("{{language_display}}", language_display)
        prompt = prompt.replace("{{line_count}}", str(line_count))
        prompt = prompt.replace("{{content}}", content)
        prompt = prompt.replace("{{cases_text}}", cases_text)
        prompt = prompt.replace("{{truncation_note}}",
            f"- 注意: 文件内容已截断（超过 8000 字符），只审核前 {max_content_length} 字符" if truncated
            else "")
        prompt = prompt.replace("{{cases_note}}",
            _build_cases_check_instruction() if cases_text
            else "- 按通用审核维度进行检查")
        
        # 将生成的 prompt 写入 debug.log，方便用户调试
        self._write_debug_log(filename, prompt)
        
        return prompt
