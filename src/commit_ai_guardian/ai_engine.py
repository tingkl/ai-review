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

结果状态：
- AI 审核发现 issues → passed=False（阻断提交，由 severity_threshold 控制）
- AI 审核无问题 → passed=True（放行）
- JSON 解析失败 → passed=False（让用户知道出问题了，需检查配置）
- 配置 enabled=false → passed=True（跳过审核，直接放行）
- API 调用失败 → passed=False（网络/配置问题，需排查）
"""

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    
    # 最后策略：JSON 可能被截断，尝试补全闭合括号
    stripped = json_str.strip()
    if stripped.startswith('{'):
        # 统计未闭合的 {, [, ", '
        open_braces = stripped.count('{') - stripped.count('}')
        open_brackets = stripped.count('[') - stripped.count(']')
        # 简单补全（从末尾开始尝试逐步补全）
        fixed = stripped
        for _ in range(open_brackets):
            fixed += ']'
        for _ in range(open_braces):
            fixed += '}'
        try:
            parsed = json.loads(fixed)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    
    return None


def _read_file_full_content(repo_path: str, filename: str) -> str:
    """读取文件的完整内容（diff_mode=full 时使用）
    
    从 repo_path 下读取文件的当前版本内容。
    文件不存在或读取失败返回空字符串。
    
    Args:
        repo_path: 仓库根目录路径
        filename: 文件相对路径（如 src/main.py）
        
    Returns:
        文件完整内容字符串
    """
    if not repo_path:
        return ""
    
    file_path = Path(repo_path) / filename
    try:
        return file_path.read_text(encoding='utf-8')
    except Exception:
        return ""


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
        # AI 可能返回范围格式如 "80-81"，提取第一个数字
        if self.line_number is not None:
            try:
                line_str = str(self.line_number).strip()
                # 提取第一个数字序列（如 "80-81" → "80"，"60" → "60"）
                match = re.search(r'\d+', line_str)
                if match:
                    self.line_number = int(match.group())
                else:
                    self.line_number = None
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
    first_line_number: Optional[int] = None  # diff 模式下第一个变更的行号
    cache_md5: str = ""  # 缓存 key 的 MD5 短码（文件名头显示用）


def parse_ai_response(response: str, filename: str = "unknown") -> ReviewResult:
    """解析 AI 的原始响应文本为结构化的 ReviewResult（纯函数，不依赖 AIEngine）

    用于 debug-log 命令：用户保存 AI 原始响应到文件，本地解析看结果，
    无需重新调用 AI（不花钱、不耗时间）。

    解析策略（层层降级）：
    1. 从 <result> 标签中提取 JSON（prompt 要求 AI 必须用 <result> 包裹）
    2. 过滤 <think> 标签
    3. 从 markdown 代码块 ```json ... ``` 中提取 JSON（兼容旧格式）
    4. 找第一个 {...}
    5. 尝试修复常见问题（BOM、单引号等）
    6. 最后都失败 → passed=False（让用户知道出问题了）

    Args:
        response: AI 返回的原始文本（从 ai.log 文件读取的内容）
        filename: 被审核的文件名（用于展示）

    Returns:
        ReviewResult。完整复用 AIEngine._parse_response 的解析逻辑
    """
    result = ReviewResult(filename=filename, raw_response=response)

    # 防御：空响应
    if not response or not response.strip():
        result.summary = "API 返回空响应"
        result.passed = True
        return result

    # ===== JSON 提取策略（层层降级） =====

    # 策略 0（最优先）：从 <result> 标签中提取 JSON
    # prompt 已要求 AI 把 JSON 包裹在 <result></result> 中，这是最可靠的提取方式
    json_str = None
    result_match = re.search(r'<result>(.*?)</result>', response, re.DOTALL)
    if result_match:
        json_str = result_match.group(1).strip()

    # 策略 1：过滤 <think> 标签后，从 ```json ... ``` 代码块中提取（兼容旧格式）
    if json_str is None:
        # 过滤 DeepSeek 等模型的 <think>...</think> 推理标签
        filtered_response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
        if filtered_response != response:
            response = filtered_response
            print(f"[信息] 已过滤 <think> 推理标签")

        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()

    # 策略 2：从响应中找第一个 {...}（非贪婪，可能因 code_snippet 中的花括号而提取不完整）
    if json_str is None:
        brace_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTALL)
        if brace_match:
            json_str = brace_match.group(0).strip()

    # 策略 3：直接解析整个响应（去掉常见的前缀废话）
    if json_str is None:
        cleaned = response.strip()
        for prefix in ['以下是', '这是', '审核结果', '结果如下', 'JSON 如下', '返回结果']:
            if prefix in cleaned and '{' in cleaned:
                idx = cleaned.find('{')
                if idx > 0:
                    cleaned = cleaned[idx:]
                    break
        json_str = cleaned

    if not json_str:
        result.summary = "无法从响应中解析 JSON"
        result.passed = False
        return result

    # 策略 4：正常 JSON 解析（含多种修复尝试）
    data = _try_parse_json(json_str)

    if data is None:
        result.summary = "JSON 解析失败"
        result.passed = False
        return result

    # 提取各字段
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
        
        # 初始化缓存目录（.ai-review/cache/）
        self._cache_dir = Path(repo_path) / ".ai-review" / "cache" if repo_path else None
        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化日志目录（.ai-review/logs/）
        self._logs_dir = Path(repo_path) / ".ai-review" / "logs" if repo_path else None
        if self._logs_dir:
            self._logs_dir.mkdir(parents=True, exist_ok=True)
        
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
            ReviewResult。审核正常返回 AI 结果，异常返回 passed=False
        """
        filename = getattr(file_diff, 'filename', 'unknown')
        
        # 检查 enabled 配置
        if not getattr(self.config, 'enabled', True):
            return ReviewResult(
                filename=filename,
                summary="AI 审核已禁用（enabled=false），跳过审核",
                passed=True,  # 禁用时不阻断
                raw_response="",
            )
        
        # 防御：客户端初始化失败
        if self.client is None:
            return ReviewResult(
                filename=filename,
                summary="AI 客户端未初始化，无法审核",
                passed=False,  # ← 让用户知道出问题了
                raw_response="",
            )
        
        # 防御：API Key 未配置
        if not getattr(self.config, 'api_key', None):
            return ReviewResult(
                filename=filename,
                summary="未配置 API Key，跳过审核",
                passed=False,
                raw_response="",
            )
        
        diff_content = getattr(file_diff, 'diff_content', '')
        
        # 根据 diff_mode 决定审核策略
        diff_mode = getattr(self.config, 'diff_mode', 'full')
        
        # 检查缓存
        if diff_mode == 'full':
            # full 模式：用完整文件内容做缓存 key
            full_content = _read_file_full_content(self.repo_path, filename)
            cache_key = hashlib.md5(full_content.encode('utf-8')).hexdigest()
        else:
            # diff 模式：用 diff 内容做缓存 key
            full_content = ""
            cache_key = hashlib.md5(diff_content.encode('utf-8')).hexdigest()
        
        cached = self._check_cache(cache_key)
        if cached:
            cached.filename = filename
            cached.cache_md5 = cache_key[:8]
            print(f"[信息] 缓存命中: {filename}，跳过 AI 审核")
            return cached
        
        # 构建 Prompt：根据 diff_mode 选择策略
        if diff_mode == 'full' and full_content:
            # full 模式：审核完整文件内容，但标注变更部分
            prompt = self._build_full_file_prompt_for_diff(filename, full_content, diff_content, file_diff)
        else:
            # diff 模式：只审核变更内容
            prompt = self._build_prompt(file_diff)
        
        try:
            response = self._call_api(prompt, filename=filename)
            result = self._parse_response(response, filename)
            # diff 模式下：把第一个变更行号和 MD5 赋给结果（文件名头显示用）
            line_numbers = getattr(file_diff, 'line_numbers', [])
            if line_numbers:
                result.first_line_number = line_numbers[0]
            result.cache_md5 = cache_key[:8]
            # 审核成功，保存到缓存
            self._save_cache(cache_key, result)
            return result
        except Exception as e:
            # API 调用异常 → 让用户知道出问题了
            print(f"[错误] 审核文件 {filename} 失败: {e}")
            return ReviewResult(
                filename=filename,
                summary=f"审核失败: {str(e)}",
                passed=False,  # ← 异常时标记未通过，需排查
                raw_response=str(e),
            )
    

    def _parse_cache_ttl(self) -> Optional[float]:
        """解析 cache_ttl 配置为秒数

        支持的格式:
            "1d"  → 86400 秒
            "12h" → 43200 秒
            "30m" → 1800 秒
            "0"   → None（不缓存）

        Returns:
            秒数，或 None（不缓存/解析失败）
        """
        ttl = getattr(self.config, 'cache_ttl', '1d')
        if not ttl or ttl == '0':
            return None

        ttl = str(ttl).strip().lower()
        try:
            if ttl.endswith('d'):
                return float(ttl[:-1]) * 86400
            elif ttl.endswith('h'):
                return float(ttl[:-1]) * 3600
            elif ttl.endswith('m'):
                return float(ttl[:-1]) * 60
            else:
                return float(ttl)  # 纯数字视为秒
        except (ValueError, TypeError):
            return 86400  # 解析失败默认 1 天

    def _clean_expired_cache(self) -> None:
        """清理过期的缓存文件

        在批量检查缓存前调用，删除超过 cache_ttl 的 .json 缓存文件。
        """
        if not self._cache_dir or not self._cache_dir.exists():
            return
        
        ttl_seconds = self._parse_cache_ttl()
        if ttl_seconds is None:
            return  # 不缓存，不清理

        now = time.time()
        cleaned = 0
        for cache_file in self._cache_dir.glob('*.json'):
            try:
                if now - cache_file.stat().st_mtime > ttl_seconds:
                    cache_file.unlink()
                    cleaned += 1
            except Exception:
                pass

        if cleaned > 0:
            print(f"[信息] 清理 {cleaned} 个过期缓存文件")

    def _parse_log_ttl(self) -> Optional[float]:
        """解析 log_ttl 配置为秒数

        支持的格式:
            "1h"  → 3600 秒
            "30m" → 1800 秒
            "0"   → None（不清理）

        Returns:
            秒数，或 None（不清理/解析失败）
        """
        ttl = getattr(self.config, 'log_ttl', '1h')
        if not ttl or ttl == '0':
            return None

        ttl = str(ttl).strip().lower()
        try:
            if ttl.endswith('h'):
                return float(ttl[:-1]) * 3600
            elif ttl.endswith('m'):
                return float(ttl[:-1]) * 60
            elif ttl.endswith('d'):
                return float(ttl[:-1]) * 86400
            else:
                return float(ttl)  # 纯数字视为秒
        except (ValueError, TypeError):
            return 3600  # 解析失败默认 1 小时

    def _clean_old_logs(self) -> None:
        """清理过期的日志文件

        在批量审核前调用，删除超过 log_ttl 的 .ai-review/logs/ 下日志文件。
        控制台打印清理数量和总大小。
        """
        if not self._logs_dir or not self._logs_dir.exists():
            return

        ttl_seconds = self._parse_log_ttl()
        if ttl_seconds is None:
            return  # 不清理

        now = time.time()
        cleaned = 0
        total_size = 0
        for log_file in self._logs_dir.glob('*.log'):
            try:
                stat = log_file.stat()
                if now - stat.st_mtime > ttl_seconds:
                    total_size += stat.st_size
                    log_file.unlink()
                    cleaned += 1
            except Exception:
                pass

        if cleaned > 0:
            size_kb = total_size / 1024
            print(f"[信息] 清理 {cleaned} 个过期日志文件（{size_kb:.1f} KB）")

    def _get_cache_key_for_file(self, file_diff: Any) -> Optional[str]:
        """计算文件的缓存 key（用于批量缓存检查）
        
        diff_mode=full 时用完整文件内容 MD5，diff 模式用 diff 内容 MD5。
        不需要缓存的返回 None。
        
        Args:
            file_diff: FileDiff 对象
            
        Returns:
            MD5 字符串，或 None
        """
        filename = getattr(file_diff, 'filename', 'unknown')
        diff_mode = getattr(self.config, 'diff_mode', 'full')
        
        if diff_mode == 'full':
            full_content = _read_file_full_content(self.repo_path, filename)
            if full_content:
                return hashlib.md5(full_content.encode('utf-8')).hexdigest()
            return None
        else:
            diff_content = getattr(file_diff, 'diff_content', '')
            if diff_content:
                return hashlib.md5(diff_content.encode('utf-8')).hexdigest()
            return None
    
    def _review_file_no_cache(self, file_diff: Any) -> ReviewResult:
        """审核文件（不检查缓存，直接调 AI）
        
        供 review_batch 在第二阶段调用（只对未命中缓存的文件）。
        
        Args:
            file_diff: FileDiff 对象
            
        Returns:
            ReviewResult
        """
        filename = getattr(file_diff, 'filename', 'unknown')
        print(f"\n[信息] AI 审核中: {filename}")
        
        diff_content = getattr(file_diff, 'diff_content', '')
        diff_mode = getattr(self.config, 'diff_mode', 'full')
        
        # 构建 Prompt
        if diff_mode == 'full':
            full_content = _read_file_full_content(self.repo_path, filename)
            if full_content:
                prompt = self._build_full_file_prompt_for_diff(filename, full_content, diff_content, file_diff)
                cache_key = hashlib.md5(full_content.encode('utf-8')).hexdigest()
            else:
                prompt = self._build_prompt(file_diff)
                cache_key = hashlib.md5(diff_content.encode('utf-8')).hexdigest()
        else:
            prompt = self._build_prompt(file_diff)
            cache_key = hashlib.md5(diff_content.encode('utf-8')).hexdigest()
        
        try:
            response = self._call_api(prompt, filename=filename)
            result = self._parse_response(response, filename)
            # diff 模式下：把第一个变更行号和 MD5 赋给结果
            line_numbers = getattr(file_diff, 'line_numbers', [])
            if line_numbers:
                result.first_line_number = line_numbers[0]
            result.cache_md5 = cache_key[:8]
            # 保存到缓存
            self._save_cache(cache_key, result)
            return result
        except Exception as e:
            print(f"[错误] 审核文件 {filename} 失败: {e}")
            return ReviewResult(
                filename=filename,
                summary=f"审核失败: {str(e)}",
                passed=False,  # ← 异常时标记未通过
                raw_response=str(e),
            )
    
    def review_batch(self, file_diffs: List[Any]) -> List[ReviewResult]:
        """
        批量审核多个文件（先检查缓存，再并发调 AI）
        
        两阶段设计：
        1. 先批量检查缓存 → 命中的直接打印并收集结果
        2. 再对没命中的文件并发调 AI → 统一在 spinner 中执行
        
        这样缓存命中的打印不会和 AI 调用的日志交错。
        
        Args:
            file_diffs: FileDiff 对象列表
            
        Returns:
            ReviewResult 列表（按原始文件顺序）
        """
        if not file_diffs:
            return []
        
        # 单文件直接走原有逻辑
        if len(file_diffs) == 1:
            return [self.review_file(file_diffs[0])]
        
        results: List[Optional[ReviewResult]] = [None] * len(file_diffs)
        
        # 先清理过期缓存和日志
        self._clean_expired_cache()
        self._clean_old_logs()

        # ===== 第一阶段：批量检查缓存 =====
        # 分离命中和未命中的文件索引
        cache_hit_indices: List[int] = []
        cache_miss_indices: List[int] = []
        
        for i, file_diff in enumerate(file_diffs):
            cache_key = self._get_cache_key_for_file(file_diff)
            if cache_key:
                cached = self._check_cache(cache_key)
                if cached:
                    cached.filename = getattr(file_diff, 'filename', 'unknown')
                    results[i] = cached
                    cache_hit_indices.append(i)
                    continue
            cache_miss_indices.append(i)
        
        # 打印缓存命中信息（在 spinner 之前）
        if cache_hit_indices:
            for idx in cache_hit_indices:
                filename = getattr(file_diffs[idx], 'filename', 'unknown')
                cache_key = self._get_cache_key_for_file(file_diffs[idx]) or ""
                print(f"[信息] 缓存命中: {filename}，跳过 AI 审核")
                if cache_key:
                    cache_path = Path(self.repo_path) / ".ai-review" / "cache" / f"{cache_key}.json"
                    print(f"  💾 {cache_path}")
        
        # ===== 第二阶段：并发调 AI（只处理未命中的文件）=====
        if cache_miss_indices:
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_index = {
                    executor.submit(self._review_file_no_cache, file_diffs[idx]): idx
                    for idx in cache_miss_indices
                }
                
                for future in as_completed(future_to_index):
                    idx = future_to_index[future]
                    try:
                        results[idx] = future.result()
                    except Exception as e:
                        filename = getattr(file_diffs[idx], 'filename', 'unknown')
                        print(f"[错误] 审核文件 {filename} 并发执行失败: {e}")
                        results[idx] = ReviewResult(
                            filename=filename,
                            summary=f"并发审核失败: {str(e)}",
                            passed=True,
                            raw_response=str(e),
                        )
        
        return results
    
    @staticmethod
    def _annotate_diff_with_line_numbers(diff_content: str) -> str:
        """给 diff 的每行加上正确的行号前缀
        
        解析 @@ hunk 头，给 + 行和上下文行标注新文件的行号，
        让 AI 直接看到正确的行号，不受 prompt 前面说明文字的影响。
        
        格式:
            + 145 | +const x = ...   ← 新增行，145 是新文件行号
              146 |   context line    ← 上下文行
              147 |   context line
        
        Args:
            diff_content: git diff 原始文本
            
        Returns:
            带行号前缀的 diff 文本
        """
        if not diff_content:
            return ""
        
        lines = diff_content.split('\n')
        result = []
        current_line = 0  # 新文件的当前行号
        
        for line in lines:
            if line.startswith('@@'):
                # 解析 hunk 头: @@ -old_start,old_count +new_start,new_count @@
                match = re.search(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
                if match:
                    current_line = int(match.group(1))
                result.append(line)
            elif line.startswith('diff --git'):
                # diff 元信息行：不加行号
                result.append(line)
            elif line.startswith('index '):
                # diff 元信息行：不加行号
                result.append(line)
            elif line.startswith('--- '):
                # diff 元信息行（旧文件路径）：不加行号
                result.append(line)
            elif line.startswith('+++ '):
                # diff 元信息行（新文件路径）：不加行号
                # ⚠️ 必须以空格结尾，避免和 "+++ b/..." 被误判为新增代码行
                result.append(line)
            elif line.startswith('+'):
                # 新增代码行，使用新文件行号
                result.append(f"+{current_line:4d} | {line}")
                current_line += 1
            elif line.startswith('-'):
                # 删除代码行，不增加新文件行号
                result.append(f"     | {line}")
            elif line.startswith('\\'):
                # "\ No newline at end of file"
                result.append(f"     | {line}")
            else:
                # 上下文代码行，使用新文件行号
                result.append(f" {current_line:4d} | {line}")
                current_line += 1
        
        return '\n'.join(result)
    
    @staticmethod
    def _annotate_content_with_line_numbers(content: str) -> str:
        """给文件内容的每行加上行号前缀
        
        让 AI 直接看到正确的行号，不受 prompt 前面说明文字的影响。
        
        格式:
            145 | let resourceId: number | null = null;
            146 | const resource = ...
        
        Args:
            content: 文件完整内容
            
        Returns:
            带行号前缀的文件内容
        """
        if not content:
            return ""
        
        lines = content.split('\n')
        result = []
        for i, line in enumerate(lines, 1):
            result.append(f"{i:4d} | {line}")
        return '\n'.join(result)
    
    @staticmethod
    def _smart_truncate_content(content: str, line_numbers: List[int], max_chars: int = 8000) -> tuple:
        """智能截断文件内容，优先保留变更行号附近的上下文
        
        策略：
        1. 文件 <= max_chars → 不截断
        2. 变更都在前面 → 截断前 max_chars（简单截断）
        3. 变更在后面 → 提取变更区域 + 前后各 30 行上下文
        
        Args:
            content: 文件完整内容
            line_numbers: 变更行号列表
            max_chars: 最大字符数
            
        Returns:
            (截断后的内容, 是否截断, 截断说明)
        """
        if len(content) <= max_chars:
            return content, False, ""
        
        if not line_numbers:
            # 没有行号信息，简单截断
            return content[:max_chars], True, f"只显示前 {max_chars} 字符"
        
        lines = content.split('\n')
        
        # 检查所有变更行是否都在前 max_chars 内
        # 找到前 max_chars 对应的行号
        prefix = content[:max_chars]
        prefix_lines = prefix.count('\n') + 1
        
        if all(ln <= prefix_lines for ln in line_numbers):
            # 所有变更都在前面，简单截断即可
            return content[:max_chars], True, f"只显示前 {prefix_lines} 行"
        
        # 有变更在后面，需要智能截断
        # 提取变更区域 + 前后各 30 行上下文
        context_lines = 30
        include_lines: set = set()
        
        for ln in line_numbers:
            start = max(0, ln - context_lines - 1)
            end = min(len(lines), ln + context_lines)
            include_lines.update(range(start, end))
        
        # 按顺序构建结果，添加省略标记
        result_lines = []
        last_included = -1
        for i in sorted(include_lines):
            if i > last_included + 1 and result_lines:
                result_lines.append(f"    ... ({i - last_included - 1} 行省略) ...")
            result_lines.append(lines[i])
            last_included = i
        
        truncated_content = '\n'.join(result_lines)
        
        # 如果还是超长，强制截断
        if len(truncated_content) > max_chars:
            truncated_content = truncated_content[:max_chars]
            return truncated_content, True, f"保留变更区域上下文，共 {len(result_lines)} 行"
        
        return truncated_content, True, f"保留变更区域上下文，共 {len(result_lines)} 行"
    
    def _build_full_file_prompt_for_diff(self, filename: str, full_content: str,
                                          diff_content: str, file_diff: Any) -> str:
        """构建 full 模式的 diff 审核 prompt（审核完整文件，标注变更部分）
        
        diff_mode=full 时使用。给 AI 看完整文件内容（带行号），
        并在开头说明哪些行号是本次变更的，让 AI 重点检查。
        
        Args:
            filename: 文件名
            full_content: 文件完整内容
            diff_content: diff 文本（用于提取变更行号）
            file_diff: FileDiff 对象
            
        Returns:
            完整的 prompt 字符串
        """
        language = getattr(file_diff, 'language', 'unknown')
        
        # 提取变更行号列表
        line_numbers = getattr(file_diff, 'line_numbers', [])
        
        # full 模式：不截断文件，传完整内容
        # 超长时依赖 max_tokens 配置，截断时 AI 会提示
        annotated_content = self._annotate_content_with_line_numbers(full_content)
        
        # 提取变更行号列表
        line_numbers = getattr(file_diff, 'line_numbers', [])
        change_lines_str = ", ".join(str(n) for n in line_numbers[:20])
        if len(line_numbers) > 20:
            change_lines_str += f" 等共 {len(line_numbers)} 行"
        
        language_display = {
            'python': 'Python', 'javascript': 'JavaScript', 'typescript': 'TypeScript',
            'java': 'Java', 'go': 'Go', 'rust': 'Rust', 'cpp': 'C++',
            'c': 'C', 'csharp': 'C#', 'ruby': 'Ruby', 'php': 'PHP',
        }.get(language, language)
        
        # 加载案例
        cases = self.case_loader.get_cases_for_language(language)
        cases_text = self.case_loader.format_cases_for_prompt(cases)
        
        # 加载模板
        template = self.prompt_loader.load_diff_review_template()
        prompt = template.replace("{{filename}}", filename)
        prompt = prompt.replace("{{language}}", language)
        prompt = prompt.replace("{{language_display}}", language_display)
        prompt = prompt.replace("{{status}}", getattr(file_diff, 'status', 'modified'))
        prompt = prompt.replace("{{diff_content}}", annotated_content)
        prompt = prompt.replace("{{cases_text}}", cases_text)
        
        # 变更行号说明（简洁版，避免和模板中其他"注意"重复）
        change_note = f"""
## 本次变更的行号
{change_lines_str}

- 以上是完整文件内容（带行号），**重点检查行号 {change_lines_str}**
- 也要检查变更对周围代码的影响
"""
        cases_instruction = _build_cases_check_instruction() if cases_text else "- 按通用审核维度进行检查"
        prompt = prompt.replace("{{cases_note}}", cases_instruction + "\n" + change_note)
        
        self._write_debug_log(filename, prompt)
        return prompt
    
    def _build_prompt(self, file_diff: Any) -> str:
        """
        构建 diff 审核提示词（用于 Git pre-commit 场景）
        
        从 .ai-review/prompts/diff_review.md 加载模板，
        找不到就用内置默认模板。
        
        diff 内容会加上行号前缀，AI 返回的 line_number 就是正确的文件行号。
        
        Args:
            file_diff: FileDiff 对象
            
        Returns:
            完整的 prompt 字符串
        """
        filename = getattr(file_diff, 'filename', 'unknown')
        language = getattr(file_diff, 'language', 'unknown')
        status = getattr(file_diff, 'status', 'modified')
        diff_content = getattr(file_diff, 'diff_content', '')
        
        # 给 diff 加上行号前缀（关键：让 AI 看到正确的文件行号）
        diff_content = self._annotate_diff_with_line_numbers(diff_content)
        
        # 截断过长的 diff，并记录最后可见行号
        max_diff_length = 8000
        last_visible_line = None
        if len(diff_content) > max_diff_length:
            # 找到截断位置前的最后一个行号
            truncated_part = diff_content[:max_diff_length]
            # 从末尾向前搜索行号（格式: " 123 |" 或 "+ 123 |"）
            for match in re.finditer(r'\b(\d+)\s+\|', truncated_part):
                last_visible_line = int(match.group(1))
            diff_content = truncated_part + f"\n... (内容已截断，只显示到第 {last_visible_line or '?'} 行)"
        
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
    
    @staticmethod
    def _sanitize_log_filename(filename: str) -> str:
        """把文件路径转成安全的日志文件名
        
        把 / 替换为 _，去掉开头的 ./，去掉 .ai-review/logs/ 前缀
        
        如:
            src/auth.ts              → src_auth_ts
            ./src/auth.ts            → src_auth_ts
            .ai-review/logs/test.ts  → test_ts
        
        Args:
            filename: 原始文件路径
            
        Returns:
            安全的日志文件名（不含扩展名，不含路径分隔符）
        """
        name = filename
        for prefix in ['.ai-review/logs/', './']:
            if name.startswith(prefix):
                name = name[len(prefix):]
        return name.replace('/', '_').replace('\\', '_').replace('.', '_')
    
    def _write_debug_log(self, filename: str, content: str, append: bool = False) -> None:
        """将 prompt 写入 .ai-review/logs/{filename}.prompt.log
        
        每个文件有独立的 prompt log，避免并发时互相覆盖。
        
        Args:
            filename: 被审核的文件名（用于生成日志文件名和头部标识）
            content: 要写入的内容
            append: True=追加，False=覆盖
        """
        if not self.repo_path:
            return
        
        logs_dir = Path(self.repo_path) / ".ai-review" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        safe_name = self._sanitize_log_filename(filename)
        prompt_log = logs_dir / f"{safe_name}.prompt.log"
        try:
            from datetime import datetime
            
            if append:
                separator = f"\n\n# --- [{datetime.now().strftime('%H:%M:%S')}] {filename} ---\n\n"
                existing = prompt_log.read_text(encoding='utf-8') if prompt_log.exists() else ""
                prompt_log.write_text(existing + separator + content, encoding='utf-8')
            else:
                header = f"""# ================================================
# Prompt Log
# 文件: {filename}
# 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# ================================================

"""
                prompt_log.write_text(header + content, encoding='utf-8')
        except Exception:
            pass
    
    def _write_ai_response_log(self, filename: str, response: str) -> None:
        """将 AI 审核返回的原始响应写入 .ai-review/logs/{filename}.ai.log
        
        每个文件有独立的 AI response log，避免并发时互相覆盖。
        
        Args:
            filename: 被审核的文件名
            response: AI 返回的原始响应文本
        """
        if not self.repo_path:
            return
        
        logs_dir = Path(self.repo_path) / ".ai-review" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        safe_name = self._sanitize_log_filename(filename)
        ai_log = logs_dir / f"{safe_name}.ai.log"
        try:
            from datetime import datetime
            header = f"""# ================================================
# AI Response Log
# 文件: {filename}
# 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# ================================================

"""
            ai_log.write_text(header + response, encoding='utf-8')
        except Exception:
            pass
    
    def _check_cache(self, content_md5: str) -> Optional[ReviewResult]:
        """检查缓存是否存在
        
        缓存文件路径: .ai-review/cache/{md5}.json
        
        Args:
            content_md5: 文件内容（diff 或完整内容）的 MD5 哈希
            
        Returns:
            ReviewResult（缓存命中），或 None（缓存未命中）
        """
        if not self._cache_dir:
            return None
        
        cache_file = self._cache_dir / f"{content_md5}.json"
        if not cache_file.exists():
            return None
        
        try:
            data = json.loads(cache_file.read_text(encoding='utf-8'))
            issues = []
            for issue_data in data.get('issues', []):
                if isinstance(issue_data, dict):
                    issues.append(ReviewIssue(
                        severity=issue_data.get('severity', 'info'),
                        category=issue_data.get('category', 'best-practice'),
                        line_number=issue_data.get('line_number'),
                        message=issue_data.get('message', ''),
                        suggestion=issue_data.get('suggestion', ''),
                        code_snippet=issue_data.get('code_snippet', ''),
                    ))
            return ReviewResult(
                filename=data.get('filename', ''),
                issues=issues,
                summary=data.get('summary', ''),
                passed=data.get('passed', True),
                raw_response=data.get('raw_response', ''),
            )
        except Exception:
            # 缓存文件损坏，删除它
            try:
                cache_file.unlink()
            except Exception:
                pass
            return None
    
    def _save_cache(self, content_md5: str, result: ReviewResult) -> None:
        """将审核结果保存到缓存
        
        缓存文件路径: .ai-review/cache/{md5}.json
        
        Args:
            content_md5: 文件内容（diff 或完整内容）的 MD5 哈希
            result: ReviewResult 审核结果
        """
        if not self._cache_dir:
            return
        
        cache_file = self._cache_dir / f"{content_md5}.json"
        try:
            data = {
                'filename': result.filename,
                'summary': result.summary,
                'passed': result.passed,
                'raw_response': result.raw_response,
                'issues': [
                    {
                        'severity': issue.severity,
                        'category': issue.category,
                        'line_number': issue.line_number,
                        'message': issue.message,
                        'suggestion': issue.suggestion,
                        'code_snippet': issue.code_snippet,
                    }
                    for issue in result.issues
                ],
            }
            cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            # 缓存写入失败不报错
            pass
    
    def _call_api(self, prompt: str, filename: str = "unknown") -> str:
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
            filename: 被审核的文件名（用于 ai.log 标识）
            
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
                    max_tokens=getattr(self.config, 'max_tokens', 4096),  # 从配置读取，默认 4096
                )
                raw_content = response.choices[0].message.content or ""
                
                # 检测 AI 响应是否可能被截断（JSON 不完整）
                stripped = raw_content.strip()
                if stripped and not stripped.endswith('}'):
                    current_max = getattr(self.config, 'max_tokens', 4096)
                    print(f"\n⚠️  AI 返回内容可能被截断（当前 max_tokens={current_max}）")
                    print(f"    建议: 运行 'commit-ai-guardian configure' 增加 max_tokens 值")
                    print(f"    或:   直接修改 .ai-review/config.yaml 中的 max_tokens\n")
                
                # 将 AI 返回的原始响应写入 ai.log（不打印到控制台）
                self._write_ai_response_log(filename, raw_content)
                return raw_content
            
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
        
        委托给模块级函数 parse_ai_response()，复用同一套解析逻辑。
        
        Args:
            response: AI 返回的原始文本（含 markdown 代码块）
            filename: 被审核的文件名
            
        Returns:
            ReviewResult。解析失败返回 passed=False（让用户知道出问题了）
        """
        result = parse_ai_response(response, filename)
        
        # 解析失败时打印日志提示（线上运行时帮助定位问题）
        if not result.passed and result.issues == [] and result.raw_response:
            if "无法从响应中解析 JSON" in result.summary:
                print(f"\n⚠️  JSON 解析失败，完整响应见 .ai-review/logs/{filename.replace('/', '_')}.ai.log")
            elif "JSON 解析失败" in result.summary:
                print(f"\n⚠️  JSON 解析失败，完整响应见 .ai-review/logs/{filename.replace('/', '_')}.ai.log")
                print(f"    可能原因: 1.max_tokens 不够(JSON被截断) 2.AI未按JSON格式输出")
        
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
        filename = getattr(source_file, 'filename', 'unknown')
        
        # 检查 enabled 配置
        if not getattr(self.config, 'enabled', True):
            return ReviewResult(
                filename=filename,
                summary="AI 审核已禁用（enabled=false），跳过审核",
                passed=True,  # 禁用时不阻断
                raw_response="",
            )
        
        # 先检查 API Key（更友好的错误提示）
        if not getattr(self.config, 'api_key', None):
            return ReviewResult(
                filename=filename,
                summary="未配置 API Key，跳过审核",
                passed=False,
                raw_response="",
            )
        
        if self.client is None:
            return ReviewResult(
                filename=getattr(source_file, 'filename', 'unknown'),
                summary="AI 客户端未初始化，无法审核",
                passed=True,
                raw_response="",
            )
        
        filename = getattr(source_file, 'filename', 'unknown')
        content = getattr(source_file, 'content', '')
        
        # 检查缓存：用 content 的 MD5 做 key
        content_md5 = hashlib.md5(content.encode('utf-8')).hexdigest()
        cached = self._check_cache(content_md5)
        if cached:
            cached.filename = filename
            cached.cache_md5 = content_md5[:8]
            print(f"[信息] 缓存命中: {filename}，跳过 AI 审核")
            return cached
        
        prompt = self._build_full_file_prompt(source_file)
        
        try:
            response = self._call_api(prompt, filename=filename)
            result = self._parse_response(response, filename)
            result.cache_md5 = content_md5[:8]
            # 审核成功，保存到缓存
            self._save_cache(content_md5, result)
            return result
        except Exception as e:
            print(f"[错误] 审核文件 {filename} 失败: {e}")
            return ReviewResult(
                filename=filename,
                summary=f"审核失败: {str(e)}",
                passed=False,  # ← 异常时标记未通过
                raw_response=str(e),
            )
    
    def _get_cache_key_for_source(self, source_file: Any) -> Optional[str]:
        """计算 SourceFile 的缓存 key
        
        Args:
            source_file: SourceFile 对象
            
        Returns:
            MD5 字符串，或 None
        """
        content = getattr(source_file, 'content', '')
        if content:
            return hashlib.md5(content.encode('utf-8')).hexdigest()
        return None
    
    def _review_source_no_cache(self, source_file: Any) -> ReviewResult:
        """审核完整文件（不检查缓存，直接调 AI）
        
        供 review_source_batch 在第二阶段调用。
        
        Args:
            source_file: SourceFile 对象
            
        Returns:
            ReviewResult
        """
        filename = getattr(source_file, 'filename', 'unknown')
        print(f"\n[信息] AI 审核中: {filename}")
        
        content = getattr(source_file, 'content', '')
        cache_key = hashlib.md5(content.encode('utf-8')).hexdigest()
        
        try:
            prompt = self._build_full_file_prompt(source_file)
            response = self._call_api(prompt, filename=filename)
            result = self._parse_response(response, filename)
            self._save_cache(cache_key, result)
            return result
        except Exception as e:
            print(f"[错误] 审核文件 {filename} 失败: {e}")
            return ReviewResult(
                filename=filename,
                summary=f"审核失败: {str(e)}",
                passed=False,  # ← 异常时标记未通过
                raw_response=str(e),
            )
    
    def review_source_batch(self, source_files: List[Any]) -> List[ReviewResult]:
        """
        批量审核完整文件（先检查缓存，再并发调 AI）
        
        两阶段设计：
        1. 先批量检查缓存 → 命中的直接打印并收集结果
        2. 再对没命中的文件并发调 AI
        
        Args:
            source_files: SourceFile 对象列表
            
        Returns:
            ReviewResult 列表（按原始文件顺序）
        """
        if not source_files:
            return []
        
        if len(source_files) == 1:
            return [self.review_source(source_files[0])]
        
        results: List[Optional[ReviewResult]] = [None] * len(source_files)
        
        # 先清理过期缓存和日志
        self._clean_expired_cache()
        self._clean_old_logs()
        
        # ===== 第一阶段：批量检查缓存 =====
        cache_hit_indices: List[int] = []
        cache_miss_indices: List[int] = []
        
        for i, source_file in enumerate(source_files):
            cache_key = self._get_cache_key_for_source(source_file)
            if cache_key:
                cached = self._check_cache(cache_key)
                if cached:
                    cached.filename = getattr(source_file, 'filename', 'unknown')
                    results[i] = cached
                    cache_hit_indices.append(i)
                    continue
            cache_miss_indices.append(i)
        
        # 打印缓存命中信息
        if cache_hit_indices:
            for idx in cache_hit_indices:
                filename = getattr(source_files[idx], 'filename', 'unknown')
                cache_key = self._get_cache_key_for_source(source_files[idx]) or ""
                print(f"[信息] 缓存命中: {filename}，跳过 AI 审核")
                if cache_key:
                    cache_path = Path(self.repo_path) / ".ai-review" / "cache" / f"{cache_key}.json"
                    print(f"  💾 {cache_path}")
        
        # ===== 第二阶段：并发调 AI =====
        if cache_miss_indices:
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_index = {
                    executor.submit(self._review_source_no_cache, source_files[idx]): idx
                    for idx in cache_miss_indices
                }
                
                for future in as_completed(future_to_index):
                    idx = future_to_index[future]
                    try:
                        results[idx] = future.result()
                    except Exception as e:
                        filename = getattr(source_files[idx], 'filename', 'unknown')
                        print(f"[错误] 审核文件 {filename} 并发执行失败: {e}")
                        results[idx] = ReviewResult(
                            filename=filename,
                            summary=f"并发审核失败: {str(e)}",
                            passed=True,
                            raw_response=str(e),
                        )
        
        return results
    
    def _build_full_file_prompt(self, source_file: Any) -> str:
        """
        构建完整文件审核的提示词
        
        从 .ai-review/prompts/full_file_review.md 加载模板，
        找不到就用内置默认模板。
        
        文件内容会加上行号前缀（如 "145 | let x = ..."），
        让 AI 返回正确的 line_number，不受 prompt 前面说明文字的影响。
        
        Args:
            source_file: SourceFile 对象
            
        Returns:
            完整的 prompt 字符串
        """
        filename = getattr(source_file, 'filename', 'unknown')
        language = getattr(source_file, 'language', 'unknown')
        content = getattr(source_file, 'content', '')
        line_count = getattr(source_file, 'line_count', 0)
        
        # review 模式没有变更行号，简单截断前 8000 字符
        # 保留文件头部（通常包含重要逻辑：import、类定义等）
        max_content_length = 8000
        truncated = False
        truncate_note = ""
        if len(content) > max_content_length:
            content = content[:max_content_length]
            truncated = True
            truncate_note = f"保留文件头部（前 8000 字符），尾部省略"
        
        # 给文件内容加上行号前缀（关键：让 AI 看到正确的文件行号）
        content = self._annotate_content_with_line_numbers(content)
        
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
            f"- 注意: {truncate_note}" if truncated else "")
        prompt = prompt.replace("{{cases_note}}",
            _build_cases_check_instruction() if cases_text
            else "- 按通用审核维度进行检查")
        
        # 将生成的 prompt 写入 debug.log，方便用户调试
        self._write_debug_log(filename, prompt)
        
        return prompt
