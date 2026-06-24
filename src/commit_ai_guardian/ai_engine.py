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

# JSON 错误关键词（用于判断是否需要调用修复 AI）
JSON_ERROR_KEYWORDS = (
    "JSON 解析失败",
    "无法从响应中解析 JSON",
    "JSON 字段缺失",
    "JSON 字段名错误",
    "JSON 类型错误",
)
import os
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
    
    本地修复策略（按顺序，层层降级）：
    1. 直接解析（标准 json.loads）
    2. 去除 BOM 头
    3. 单引号替换为双引号
    4. 去除 trailing commas（,} 和 ,]）
    5. 去除 // 行注释
    6. 修复非法转义（\\] \\' 等 JSON 不支持的转义）
    7. 括号补全（统计未闭合的 { [ 补齐）
    
    所有策略都失败 → 返回 None（交给上层调用修复 AI）
    
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
    
    # 修复非法 JSON 转义（AI 在正则表达式中常产生 \] \' 等非法转义）
    # JSON 标准只支持: \" \\ \/ \b \f \n \r \t \uXXXX
    fixed_escapes = json_str.strip().replace("\\'", "'")
    fixed_escapes = re.sub(r'\\([^"\\/bfnrtu])', r'\\\\\1', fixed_escapes)
    if fixed_escapes != json_str.strip():
        candidates.append(fixed_escapes)
    
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


def _extract_json(text: str) -> str:
    """从文本中提取 JSON 字符串（层层降级）

    内部会自动过滤 <think> 标签，调用方无需预处理。

    1. 过滤 <think> 标签
    2. 从 ```json ... ``` 代码块提取（取最长匹配，避免内部代码块截断）
    3. 从 <result> 标签提取
    4. 用栈计数找匹配的 {...}（处理嵌套 JSON）
    5. 整个文本作为 JSON

    Args:
        text: AI 返回的原始响应文本（可包含 <think> 标签）

    Returns:
        JSON 字符串（不会返回空字符串）
    """
    # 过滤 <think> 标签
    filtered = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    # 策略 0: 从 ```json 代码块提取（行级匹配）
    # 找到 ```json 后，匹配到第一个单独成行的 ```（前面只有空白字符）
    # suggestion 内部的 ``` 前面有代码内容，不是单独成行，因此不会被误判
    start_match = re.search(r'```json\s*(?:\n|$)', filtered)
    if start_match:
        start_idx = start_match.end()
        end_match = re.search(r'(?:^|\n)\s*```\s*(?:\n|$)', filtered[start_idx:])
        if end_match:
            return filtered[start_idx:start_idx + end_match.start()].strip()

    # 策略 1: 从 <result> 标签提取
    m = re.search(r'<result>\s*(.*?)\s*</result>', filtered, re.DOTALL)
    if m:
        return m.group(1).strip()

    # 策略 2: 用栈计数找匹配的 {} 边界（正确处理嵌套）
    first_brace = filtered.find('{')
    if first_brace != -1:
        brace_count = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(filtered[first_brace:], start=first_brace):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\':
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if not in_string:
                if ch == '{':
                    brace_count += 1
                elif ch == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        return filtered[first_brace:i + 1].strip()

    # 策略 3: 整个文本作为 JSON
    return filtered


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
        "- 【强约束 - 必须遵守】上方提供了具体的\"问题模式\"案例，包含坏代码示例、好代码示例和检查清单\n"
        "- 案例中的坏代码模式如果在审核代码中出现 → 必须报 issue，绝对不能遗漏\n"
        "- 逐条对照每个检查清单项（☐ 标记），在代码中逐一寻找匹配\n"
        "- 发现匹配时给出对应的好代码示例作为修复建议\n"
        "- 此约束优先级最高：即使其他规则说不要报，案例中的问题也必须报"
    )


@dataclass
class ReviewIssue:
    """单个审核问题"""
    severity: str = "info"  # critical / error / warning / info
    category: str = "最佳实践"  # Bug检测 / 安全 / 代码风格 / 性能 / 最佳实践 / 文档
    line_number: Optional[int] = None
    message: str = ""
    suggestion: str = ""
    code_snippet: str = ""
    



@dataclass
class ReviewResult:
    """单个文件的审核结果"""
    filename: str = ""
    issues: List[ReviewIssue] = field(default_factory=list)
    summary: str = ""
    passed: bool = False  # 默认阻断，只有明确通过时才设为 True
    raw_response: str = ""  # AI 原始响应（调试用）
    extracted_json: str = ""  # 从 raw_response 中提取的 JSON 字符串（给修复 AI 用）
    cache_md5: str = ""  # 缓存 key 的 MD5 前7位短码（cache 文件名也是前7位）


def _validate_issue_core(issue_data: dict, index: int) -> list:
    """校验单个 issue 的核心规则（message/severity/line_number）

    两边共用：parse_ai_response 首次解析 + _validate_review_schema 二次校验。
    返回错误列表（空列表表示校验通过）。

    Args:
        issue_data: 单个 issue 的字典
        index: issue 在数组中的索引（用于错误信息）

    Returns:
        错误信息列表（空表示通过）
    """
    errors = []

    # 必填字段存在性
    for field in ['severity', 'line_number', 'message']:
        if field not in issue_data:
            errors.append(f"issues[{index}] 缺少必填字段: '{field}'")

    # severity 枚举
    sev = issue_data.get('severity')
    if sev is not None and sev not in ('critical', 'error', 'warning', 'info'):
        errors.append(f"issues[{index}].severity 值非法: '{sev}'，必须是 critical/error/warning/info 之一")

    # line_number：尝试本地修复（字符串→整数），修不了才报错
    ln = issue_data.get('line_number')
    if ln is not None and not isinstance(ln, int):
        try:
            line_str = str(ln).strip()
            match = re.search(r'\d+', line_str)
            if match:
                issue_data['line_number'] = int(match.group())  # 就地修复
            else:
                errors.append(f"issues[{index}].line_number 必须是整数，当前值无法解析: {ln}")
        except (ValueError, TypeError):
            errors.append(f"issues[{index}].line_number 必须是整数，当前值无法解析: {ln}")

    # message 非空
    msg = issue_data.get('message')
    if msg is not None and (not isinstance(msg, str) or not msg.strip()):
        errors.append(f"issues[{index}].message 不能为空字符串")

    return errors


def parse_ai_response(response: str, filename: str = "unknown",
                       severity_threshold: str = "warning") -> ReviewResult:
    """解析 AI 的原始响应文本为结构化的 ReviewResult（纯函数，不依赖 AIEngine）

    用于 debug-log 命令：用户保存 AI 原始响应到文件，本地解析看结果，
    无需重新调用 AI（不花钱、不耗时间）。

    解析策略（层层降级）：
    1. 从 markdown 代码块 ```json ... ``` 中提取 JSON（兼容旧格式）
    2. 找第一个 {...}
    3. 整个响应作为 JSON
    4. 尝试修复常见问题（BOM、单引号等）
    5. 最后都失败 → passed=False（让用户知道出问题了）

    Args:
        response: AI 返回的原始文本（从 ai.log 文件读取的内容）
        filename: 被审核的文件名（用于展示）
        severity_threshold: 阻断级别 (info/warning/error/critical)

    Returns:
        ReviewResult。完整复用 AIEngine._parse_response 的解析逻辑
    """
    result = ReviewResult(filename=filename, raw_response=response, passed=False)

    # 防御：空响应
    if not response or not response.strip():
        result.summary = "API 返回空响应"
        result.passed = True
        return result

    # ===== JSON 提取（层层降级） =====
    # _extract_json 内部已过滤 <think> 标签，无需预处理
    json_str = _extract_json(response)
    result.extracted_json = json_str  # 保存提取后的 JSON，修复 AI 直接用

    if not json_str:
        result.summary = "无法从响应中解析 JSON"
        return result

    # 快速处理：空数组 [] = 审核通过（AI 认为没问题但忘了包装成对象）
    # 必须在 _try_parse_json 之前处理，因为该函数只返回 dict
    stripped = json_str.strip()
    if stripped == '[]':
        result.summary = "审核完成，未发现问题"
        result.passed = True
        return result
    
    # 快速处理：空对象 {} = 审核通过
    if stripped == '{}':
        result.summary = "审核完成，未发现问题"
        result.passed = True
        return result

    # 策略 4：正常 JSON 解析（含多种修复尝试）
    data = _try_parse_json(json_str)

    if data is None:
        result.summary = "JSON 解析失败"
        return result
    
    # AI 可能返回非空数组（如 [{issue1}, ...]）而不是对象
    if isinstance(data, list):
        # 非空数组 = 有 issues 但没有 summary/passed 包装，交给修复 AI 处理
        result.summary = f"JSON 类型错误: 期望对象 {{...}}，实际得到数组（{len(data)} 个元素）"
        return result
    
    if not isinstance(data, dict):
        result.summary = f"JSON 类型错误: 期望对象 {{...}}，实际得到 {type(data).__name__}"
        return result

    # 检查顶层必需字段（passed 由系统根据 severity 自动计算，不需要 AI 填写）
    _REQUIRED_TOP_FIELDS = {'summary', 'issues'}
    missing_top = _REQUIRED_TOP_FIELDS - set(data.keys())
    if missing_top:
        result.summary = f"JSON 字段缺失: 缺少顶层必填字段: {', '.join(sorted(missing_top))}"
        return result

    # 检查顶层字段类型
    if not isinstance(data.get('summary'), str):
        result.summary = "JSON 类型错误: 'summary' 必须是字符串"
        return result
    if not isinstance(data.get('issues'), list):
        result.summary = "JSON 类型错误: 'issues' 必须是数组"
        return result

    # 提取 summary（passed 由系统根据 severity 自动计算，不依赖 AI 填写）
    result.summary = data.get('summary', '审核完成')

    # 解析 issues 列表（用 _validate_issue_core 统一校验）
    issues_data = data.get('issues', [])
    _SEVERITY_ORDER = {'info': 0, 'warning': 1, 'error': 2, 'critical': 3}
    threshold_level = _SEVERITY_ORDER.get(severity_threshold, 1)
    has_severe_issue = False  # 有 severity >= threshold 的 issue
    if isinstance(issues_data, list):
        for i, issue_data in enumerate(issues_data):
            if isinstance(issue_data, dict):
                # 统一校验（message/severity/line_number）
                issue_errors = _validate_issue_core(issue_data, i)
                if issue_errors:
                    first_err = issue_errors[0]
                    if "缺少必填字段" in first_err or "不能为空字符串" in first_err:
                        result.summary = f"JSON 字段缺失: {first_err}"
                    else:
                        result.summary = f"JSON 类型错误: {first_err}"
                    return result
                
                severity = issue_data.get('severity', 'info')
                if _SEVERITY_ORDER.get(severity, 0) >= threshold_level:
                    has_severe_issue = True
                
                issue = ReviewIssue(
                    severity=severity,
                    category=issue_data.get('category', '最佳实践'),
                    line_number=issue_data.get('line_number'),
                    message=issue_data.get('message', ''),
                    suggestion=issue_data.get('suggestion', ''),
                    code_snippet=issue_data.get('code_snippet', ''),
                )
                result.issues.append(issue)
    
    # 根据 severity_threshold 修正 passed
    if has_severe_issue:
        pass  # 默认 False，不处理
    elif result.issues or issues_data == []:
        # issues 为空数组 或 所有 issue severity < threshold → passed = true
        result.passed = True

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
        
        # timeout <= 0 时用默认值 60（Config.__post_init__ 允许 0 通过 merge）
        timeout_val = getattr(config, 'timeout', 60)
        if timeout_val <= 0:
            timeout_val = 60
        http_kwargs["timeout"] = httpx.Timeout(timeout_val)
        
        # 调试模式：打印 API 配置（不脱敏 key，方便排查 401）
        import os
        if os.environ.get('CAG_DEBUG'):
            print(f"[DEBUG] api_base: {getattr(config, 'api_base', 'default')}")
            print(f"[DEBUG] api_key: {config.api_key[:15]}...{config.api_key[-4:]}")
            print(f"[DEBUG] model: {getattr(config, 'model', 'default')}")
        
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
    
    def _check_prerequisites(self, filename: str) -> Optional[ReviewResult]:
        """检查审核前置条件（enabled / client / api_key）
        
        三个条件任一不满足，返回对应的 ReviewResult（不再继续审核）。
        全部通过返回 None，调用方继续正常审核流程。
        
        Args:
            filename: 被审核的文件名（用于返回结果）
            
        Returns:
            ReviewResult（条件不满足时）或 None（全部通过）
        """
        if not getattr(self.config, 'enabled', True):
            return ReviewResult(
                filename=filename,
                summary="AI 审核已禁用（enabled=false），跳过审核",
                passed=True,
                raw_response="",
            )
        if self.client is None:
            return ReviewResult(
                filename=filename,
                summary="AI 客户端未初始化，无法审核",
                passed=False,
                raw_response="",
            )
        if not getattr(self.config, 'api_key', None):
            return ReviewResult(
                filename=filename,
                summary="未配置 API Key，跳过审核",
                passed=False,
                raw_response="",
            )
        return None
    
    def review_file(self, file_diff: Any) -> ReviewResult:
        """审核单个文件的 diff（pre-commit 场景）
        
        流程：构建 diff Prompt → 调用 API → 解析响应
        
        Args:
            file_diff: FileDiff 对象，需包含 filename, language, diff_content
            
        Returns:
            ReviewResult。审核正常返回 AI 结果，异常返回 passed=False
        """
        filename = getattr(file_diff, 'filename', 'unknown')
        
        # 检查前置条件
        prereq = self._check_prerequisites(filename)
        if prereq:
            return prereq
        
        diff_content = getattr(file_diff, 'diff_content', '')
        
        # 根据 diff_mode 决定审核策略
        diff_mode = getattr(self.config, 'diff_mode', 'full')
        
        # 计算缓存 key（MD5 前7位，用于缓存文件名和 ai.log 命名）
        # 注意：diff_content 为空时（如未 git add），禁用缓存避免空字符串 MD5 碰撞
        if diff_mode == 'full':
            full_content = _read_file_full_content(self.repo_path, filename)
            cache_key = hashlib.md5(full_content.encode('utf-8')).hexdigest()[:7] if full_content else None
        else:
            full_content = ""
            cache_key = hashlib.md5(diff_content.encode('utf-8')).hexdigest()[:7] if diff_content else None
        
        # 检查缓存（可配置关闭；diff_content 为空时禁用缓存）
        use_cache = getattr(self.config, 'use_cache', True) and cache_key is not None
        if use_cache:
            cached = self._check_cache(cache_key)
            if cached:
                cached.filename = filename
                cached.cache_md5 = cache_key
                print(f"[信息] 缓存命中: {filename}  跳过 AI 审核")
                cache_path = Path(self.repo_path) / ".ai-review" / "cache" / f"{cache_key}.json"
                print(f"  {os.path.relpath(cache_path)}")
                return cached
        
        # 构建 Prompt：根据 diff_mode 选择策略
        if diff_mode == 'full' and full_content:
            # full 模式：审核完整文件内容，但标注变更部分
            prompt = self._build_full_file_prompt_for_diff(filename, full_content, diff_content, file_diff, cache_key)
        else:
            # diff 模式：只审核变更内容
            prompt = self._build_prompt(file_diff, cache_key)
        
        try:
            response = self._call_api(prompt, filename=filename, cache_md5=cache_key)
            result = self._parse_response(response, filename, cache_md5=cache_key)
            result.cache_md5 = cache_key
            # 审核成功，保存到缓存（可配置关闭）
            if use_cache:
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
                cache_md5=cache_key,
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
        # 同时清理 .json 和 broken 缓存（{md5}_MMDDHHMMSS.json）
        for cache_file in list(self._cache_dir.glob('*.json')):
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
        """计算文件的缓存 key（MD5 前7位，用于缓存文件名）
        
        diff_mode=full 时用完整文件内容 MD5，diff 模式用 diff 内容 MD5。
        不需要缓存的返回 None。
        
        Args:
            file_diff: FileDiff 对象
            
        Returns:
            MD5 前7位字符串，或 None
        """
        filename = getattr(file_diff, 'filename', 'unknown')
        diff_mode = getattr(self.config, 'diff_mode', 'full')
        
        if diff_mode == 'full':
            full_content = _read_file_full_content(self.repo_path, filename)
            if full_content:
                return hashlib.md5(full_content.encode('utf-8')).hexdigest()[:7]
            return None
        else:
            diff_content = getattr(file_diff, 'diff_content', '')
            if diff_content:
                return hashlib.md5(diff_content.encode('utf-8')).hexdigest()[:7]
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
        print(f"[信息] AI 审核中: {filename}\n")
        
        diff_content = getattr(file_diff, 'diff_content', '')
        diff_mode = getattr(self.config, 'diff_mode', 'full')
        
        # 构建 Prompt（先算 cache_key，MD5 前7位用于日志命名）
        # diff_content 为空时 cache_key = None，避免空字符串 MD5 碰撞
        if diff_mode == 'full':
            full_content = _read_file_full_content(self.repo_path, filename)
            if full_content:
                cache_key = hashlib.md5(full_content.encode('utf-8')).hexdigest()[:7]
                prompt = self._build_full_file_prompt_for_diff(filename, full_content, diff_content, file_diff, cache_key)
            else:
                cache_key = hashlib.md5(diff_content.encode('utf-8')).hexdigest()[:7] if diff_content else None
                prompt = self._build_prompt(file_diff, cache_key)
        else:
            cache_key = hashlib.md5(diff_content.encode('utf-8')).hexdigest()[:7] if diff_content else None
            prompt = self._build_prompt(file_diff, cache_key)
        
        try:
            response = self._call_api(prompt, filename=filename, cache_md5=cache_key)
            result = self._parse_response(response, filename, cache_md5=cache_key)
            result.cache_md5 = cache_key
            # 保存到缓存（可配置关闭）
            if getattr(self.config, 'use_cache', True):
                self._save_cache(cache_key, result)
            return result
        except Exception as e:
            print(f"[错误] 审核文件 {filename} 失败: {e}")
            return ReviewResult(
                filename=filename,
                summary=f"审核失败: {str(e)}",
                passed=False,  # ← 异常时标记未通过
                raw_response=str(e),
                cache_md5=cache_key,
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

        # 检查是否启用缓存
        use_cache = getattr(self.config, 'use_cache', True)

        # ===== 第一阶段：批量检查缓存（可配置关闭）=====
        cache_hit_indices: List[int] = []
        cache_miss_indices: List[int] = list(range(len(file_diffs)))
        
        if use_cache:
            cache_hit_indices = []
            cache_miss_indices = []
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
                    print(f"[信息] 缓存命中: {filename}  跳过 AI 审核")
                    if cache_key:
                        cache_path = Path(self.repo_path) / ".ai-review" / "cache" / f"{cache_key}.json"
                        print(f"  {os.path.relpath(cache_path)}")
        
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
                            passed=False,  # 异常默认阻断
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
    
    def _build_full_file_prompt_for_diff(self, filename: str, full_content: str,
                                          diff_content: str, file_diff: Any,
                                          cache_md5: str = "") -> str:
        """构建 full 模式的 diff 审核 prompt（审核完整文件，标注变更部分）
        
        diff_mode=full 时使用。给 AI 看完整文件内容（带行号），
        并在开头说明哪些行号是本次变更的，让 AI 重点检查。
        
        Args:
            filename: 文件名
            full_content: 文件完整内容
            diff_content: diff 文本（用于提取变更行号）
            file_diff: FileDiff 对象
            cache_md5: MD5 前7位，用于日志文件名命名
            
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
        cases_text = self.case_loader.format_cases_for_prompt(
            cases,
            case_format=getattr(self.config, 'case_format', 'default')
        )
        
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
        
        return prompt
    
    def _build_prompt(self, file_diff: Any, cache_md5: str = "") -> str:
        """
        构建 diff 审核提示词（用于 Git pre-commit 场景）
        
        从 .ai-review/prompts/diff_review.md 加载模板，
        找不到就用内置默认模板。
        
        diff 内容会加上行号前缀，AI 返回的 line_number 就是正确的文件行号。
        
        Args:
            file_diff: FileDiff 对象
            cache_md5: MD5 前7位，用于日志文件名命名
            
        Returns:
            完整的 prompt 字符串
        """
        filename = getattr(file_diff, 'filename', 'unknown')
        language = getattr(file_diff, 'language', 'unknown')
        status = getattr(file_diff, 'status', 'modified')
        diff_content = getattr(file_diff, 'diff_content', '')
        
        # 给 diff 加上行号前缀（关键：让 AI 看到正确的文件行号）
        diff_content = self._annotate_diff_with_line_numbers(diff_content)
        
        # 注：已取消 diff 截断。MiniMax 等模型输入上下文 200K+，
        # 8000 字符（约 3000 token）不可能触及限制。
        # 如未来需要限制，可在此恢复截断逻辑。
        
        language_display = {
            'python': 'Python', 'javascript': 'JavaScript', 'typescript': 'TypeScript',
            'java': 'Java', 'go': 'Go', 'rust': 'Rust', 'cpp': 'C++',
            'c': 'C', 'csharp': 'C#', 'ruby': 'Ruby', 'php': 'PHP',
        }.get(language, language)
        
        # 加载与当前编程语言匹配的案例
        cases = self.case_loader.get_cases_for_language(language)
        cases_text = self.case_loader.format_cases_for_prompt(
            cases,
            case_format=getattr(self.config, 'case_format', 'default')
        )
        
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
        
        return prompt
    
    def _write_ai_response_log(self, filename: str, response: str,
                                cache_md5: str = "",
                                system_message: str = "",
                                user_message: str = "") -> Optional[Path]:
        """将 AI 审核的完整对话记录写入 .ai-review/logs/{cache_md5}.ai.log

        记录完整的 API 调用上下文：system message + user message + AI response，
        用分隔线清晰标注各部分，方便调试时定位问题。

        Args:
            filename: 被审核的文件名（用于日志头部标识）
            response: AI 返回的原始响应文本
            cache_md5: MD5 前7位，用于日志文件名
            system_message: system 角色的消息内容
            user_message: user 角色的消息内容
        """
        if not self.repo_path:
            return

        logs_dir = Path(self.repo_path) / ".ai-review" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        log_name = cache_md5 or filename.replace('/', '_')
        ai_log = logs_dir / f"{log_name}.ai.log"
        try:
            from datetime import datetime
            sep_line = "=" * 60

            display_name = filename
            repo_name = os.path.basename(self.repo_path)
            if display_name.startswith(repo_name + '/'):
                display_name = display_name[len(repo_name) + 1:]
            parts = [
                f"# ================================================\n"
                f"# AI Response Log\n"
                f"# 文件: {display_name}\n"
                f"# 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"# ================================================\n"
            ]

            if system_message:
                parts.append(
                    f"\n{sep_line}\n"
                    f"--- SYSTEM MESSAGE ---\n"
                    f"{sep_line}\n\n"
                    f"{system_message}"
                )

            if user_message:
                parts.append(
                    f"\n{sep_line}\n"
                    f"--- USER MESSAGE ---\n"
                    f"{sep_line}\n\n"
                    f"{user_message}"
                )

            if response:
                parts.append(
                    f"\n{sep_line}\n"
                    f"--- AI RESPONSE ---\n"
                    f"{sep_line}\n\n"
                    f"{response}"
                )

            ai_log.write_text("\n".join(parts), encoding='utf-8')
            return ai_log
        except Exception:
            return None


    def _check_cache(self, content_md5: str) -> Optional[ReviewResult]:
        """检查缓存是否存在
        
        缓存文件路径: .ai-review/cache/{md5前7位}.json
        用 MD5 前7位作为文件名（类似 git short hash），节省磁盘空间。
        
        如果存在 .json.broken 文件（上次 JSON 解析失败），当作缓存未命中，
        下次重新审核。
        
        Args:
            content_md5: 文件内容（diff 或完整内容）的 MD5 前7位
            
        Returns:
            ReviewResult（缓存命中），或 None（缓存未命中）
        """
        if not self._cache_dir:
            return None
        
        cache_file = self._cache_dir / f"{content_md5}.json"
        # broken 缓存格式: {md5}_MMDDHHMMSS.json
        broken_files = list(self._cache_dir.glob(f"{content_md5}_*.json"))
        
        # 上次 JSON 解析失败，当作缓存未命中，下次重新审核
        if broken_files:
            return None
        
        if not cache_file.exists():
            return None
        
        try:
            data = json.loads(cache_file.read_text(encoding='utf-8'))
            issues = []
            for issue_data in data.get('issues', []):
                if isinstance(issue_data, dict):
                    issues.append(ReviewIssue(
                        severity=issue_data.get('severity', 'info'),
                        category=issue_data.get('category', '最佳实践'),
                        line_number=issue_data.get('line_number'),
                        message=issue_data.get('message', ''),
                        suggestion=issue_data.get('suggestion', ''),
                        code_snippet=issue_data.get('code_snippet', ''),
                    ))
            # cache_md5 从 JSON 恢复，如果没有则用传入的 content_md5
            cache_md5 = data.get('cache_md5', content_md5)
            return ReviewResult(
                filename=data.get('filename', ''),
                issues=issues,
                summary=data.get('summary', ''),
                passed=data.get('passed', True),
                raw_response=data.get('raw_response', ''),
                extracted_json=data.get('extracted_json', ''),
                cache_md5=cache_md5,
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
        
        缓存文件路径: .ai-review/cache/{md5前7位}.json
        如果 JSON 解析失败（不是真正的审核结果），文件名加 .broken 后缀，
        这样 _check_cache 会跳过它，下次重新审核。
        
        Args:
            content_md5: 文件内容（diff 或完整内容）的 MD5 前7位
            result: ReviewResult 审核结果
        """
        if not self._cache_dir:
            return
        
        from datetime import datetime
        
        # 判断是否是 broken 缓存（JSON 解析失败，不是真正的审核结果）
        is_broken = not result.passed and any(
            kw in result.summary for kw in 
            ("JSON 解析失败", "JSON 字段缺失", "JSON 字段名错误", "JSON 类型错误")
        )
        
        # broken 缓存用时间戳标记：{md5}_MMDDHHMMSS.json
        if is_broken:
            ts = datetime.now().strftime("%m%d%H%M%S")
            cache_file = self._cache_dir / f"{content_md5}_{ts}.json"
        else:
            cache_file = self._cache_dir / f"{content_md5}.json"
        try:
            data = {
                'filename': result.filename,
                'summary': result.summary,
                'passed': result.passed,
                'raw_response': result.raw_response,
                'extracted_json': result.extracted_json,
                'cache_md5': result.cache_md5 or content_md5,
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
    
    # 审核结果的 JSON Schema，精确约束 AI 输出格式
    REVIEW_JSON_SCHEMA = {
        "name": "code_review_result",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "总体评价（2-3句话）"},
                "passed": {"type": "boolean", "description": "true=通过 false=不通过"},
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "severity": {
                                "type": "string",
                                "enum": ["critical", "error", "warning", "info"],
                                "description": "严重级别"
                            },
                            "category": {
                                "type": "string",
                                "enum": ["Bug检测", "安全", "代码风格", "性能", "最佳实践", "文档"],
                                "description": "问题类别"
                            },
                            "line_number": {"type": "integer", "description": "行号（单个整数）"},
                            "message": {"type": "string", "description": "问题描述（必填，不能为空）"},
                            "suggestion": {"type": "string", "description": "修复建议"},
                            "code_snippet": {"type": "string", "description": "相关代码片段"}
                        },
                        "required": ["severity", "category", "line_number", "message"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["summary", "passed", "issues"],
            "additionalProperties": False
        }
    }

    def _call_api_safe(self, **kwargs) -> Any:
        """调用 API，使用 JSON Schema 精确约束 AI 输出
        
        主流模型（GPT/Claude/DeepSeek/MiniMax/Moonshot 等）均支持 response_format，
        直接使用 json_schema 精确约束字段名、类型、必填项。
        不支持的模型会报错，需要用户升级模型或切换支持 schema 的模型。
        
        Args:
            **kwargs: 传给 chat.completions.create 的参数
            
        Returns:
            API 响应对象
        """
        kwargs_schema = {
            **kwargs,
            "response_format": {
                "type": "json_schema",
                "json_schema": self.REVIEW_JSON_SCHEMA
            }
        }
        return self.client.chat.completions.create(**kwargs_schema)

    def _get_disable_thinking_params(self, model: str) -> dict:
        """根据模型名称返回禁用 think/thinking 的 extra_api_params
        
        主流国产模型思考过程参数各不相同，在此统一适配。
        匹配不到的模型返回空 dict（不额外传参）。
        
        适配列表（已验证）：
        - DeepSeek: enable_thinking=false (boolean)
        
        待验证（暂不启用，避免 API 400 错误）：
        - MiniMax/Moonshot/Kimi/Qwen/GLM/混元/豆包 的 thinking 参数格式
          可能是对象格式 {"type": "disabled"} 而非 boolean
        """
        m = model.lower()
        
        # DeepSeek 系列 — 确认支持 enable_thinking (boolean)
        if 'deepseek' in m:
            return {"extra_body": {"enable_thinking": False}}
        
        # 其他模型暂不传入 thinking 参数（格式不确定，传入 boolean 会导致 API 400）
        # 如需适配其他模型，请先确认其 API 的 thinking 参数格式
        # 典型错误: Mismatch type ThinkingConfig with value bool
        return {}
    
    def _call_api(self, prompt: str, filename: str = "unknown", cache_md5: str = "") -> str:
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
            cache_md5: MD5 前7位，用于 ai.log 文件名命名
            
        Returns:
            AI 的文本响应（JSON 格式，markdown 包裹）
            
        Raises:
            RuntimeError: 3 次重试后仍失败
        """
        model = getattr(self.config, 'model', 'gpt-4o-mini')
        max_retries = 3
        # 根据模型名称获取禁用 think 的额外参数
        extra_params = self._get_disable_thinking_params(model)
        
        # 加载 system message（只加载一次，所有 retry 共用）
        system_msg = self.prompt_loader.load_system_message()

        for attempt in range(max_retries):
            try:
                response = self._call_api_safe(
                    model=model,
                    messages=[
                        # system 消息从模板加载（.ai-review/prompts/system_message.txt）
                        {"role": "system", "content": system_msg},
                        # user 消息是真正的审核请求（从模板渲染）
                        {"role": "user", "content": prompt}
                    ],
                    temperature=getattr(self.config, 'temperature', 0.3),  # 从配置读取，默认 0.3
                    max_tokens=getattr(self.config, 'max_tokens', 8192),   # 从配置读取，默认 8K
                    **extra_params,      # 主流模型禁用 think 的额外参数（如 enable_thinking=false）
                )
                raw_content = response.choices[0].message.content or ""
                # 将原始响应写入 ai.log（调试用），返回 ai.log 路径
                self._write_ai_response_log(filename, raw_content, cache_md5,
                                                      system_message=system_msg, user_message=prompt)
                
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
    
    def _write_json_fix_log(self, filename: str, cache_md5: str,
                             system_message: str, user_message: str,
                             ai_response: str) -> None:
        """将 JSON 修复 AI 的完整对话记录写入 .ai-review/logs/{md5}.json_fix.log

        每次调用 JSON 修复 AI 都会保存（无论修复成功与否），方便查看定位。
        格式与 ai.log 完全一致：header + system + user + ai response。

        Args:
            filename: 被审核的文件名
            cache_md5: MD5 前7位，用于日志文件名。为空时用时间戳替代
            system_message: system 角色消息
            user_message: user 角色消息
            ai_response: AI 返回的文本
        """
        if not self.repo_path:
            return

        logs_dir = Path(self.repo_path) / ".ai-review" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # cache_md5 为 None 时用文件名作为 fallback（如 diff_content 为空时）
        name = cache_md5 or filename.replace('/', '_')
        
        # 文件名格式: {md5}.json_fix.log，和 ai.log ({md5}.ai.log) 对应
        log_file = logs_dir / f"{name}.json_fix.log"
        try:
            from datetime import datetime
            sep_line = "=" * 60

            display_name = filename
            repo_name = os.path.basename(self.repo_path)
            if display_name.startswith(repo_name + '/'):
                display_name = display_name[len(repo_name) + 1:]
            parts = [
                f"# ================================================\n"
                f"# JSON Fix Log\n"
                f"# 文件: {display_name}\n"
                f"# MD5: {name}\n"
                f"# 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"# ================================================\n"
            ]

            if system_message:
                parts.append(
                    f"\n{sep_line}\n"
                    f"--- SYSTEM MESSAGE ---\n"
                    f"{sep_line}\n\n"
                    f"{system_message}"
                )

            if user_message:
                parts.append(
                    f"\n{sep_line}\n"
                    f"--- USER MESSAGE ---\n"
                    f"{sep_line}\n\n"
                    f"{user_message}"
                )

            if ai_response:
                parts.append(
                    f"\n{sep_line}\n"
                    f"--- AI RESPONSE ---\n"
                    f"{sep_line}\n\n"
                    f"{ai_response}"
                )

            log_file.write_text("\n".join(parts), encoding='utf-8')
        except Exception as e:
            print(f"[警告] 写入 json_fix.log 失败: {e}")

    def _fix_json_with_ai(self, broken_json: str, filename: str,
                           cache_md5: str = "") -> Optional[ReviewResult]:
        """AI 修复 JSON 语法错误

        本地所有修复策略都失败后，调用 AI 来修复 JSON。
        修复成功后直接用 parse_ai_response 解析为 ReviewResult。

        Args:
            broken_json: 有语法错误的 JSON 字符串
            filename: 被审核的文件名
            cache_md5: MD5 前7位，用于 json_fix 日志文件名

        Returns:
            修复并解析后的 ReviewResult，或 None（修复失败）
        """
        if not self.client:
            return None

        model = getattr(self.config, 'model', 'gpt-4o-mini')
        max_tokens = getattr(self.config, 'max_tokens', 8192)
        max_attempts = getattr(self.config, 'json_fix_max_attempts', 5)
        print(f"[信息] JSON 修复 AI 启动（最多 {max_attempts} 次尝试）")

        # 根据模型名称获取禁用 think 的额外参数
        extra_params = self._get_disable_thinking_params(model)
        
        # 从模板加载 system message 和 user prompt
        system_msg = self.prompt_loader.load_json_fix_system_message()
        template = self.prompt_loader.load_json_fix_template()
        fix_prompt = PromptLoader.render(template, filename=filename, broken_json=broken_json)

        # JSON 修复 AI 上下文策略
        # full = 累积所有失败的 attempt，last = 只保留最近一次
        history_mode = getattr(self.config, 'json_fix_history_mode', 'full')
        attempt_history = []  # 每次失败追加 [assistant(json), user(error)]

        all_attempts_log = []  # 收集所有尝试的日志
        
        for attempt in range(max_attempts):
            try:
                # 构造 messages：system + 原始修复请求 + 历史对话
                messages = [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": fix_prompt},
                    *attempt_history,
                ]

                resp = self._call_api_safe(
                    model=model,
                    messages=messages,
                    temperature=0.0,  # 纯格式转换，完全确定性输出
                    max_tokens=max_tokens,
                    **extra_params,
                )
                fixed = resp.choices[0].message.content or ""

                # 记录本次尝试
                all_attempts_log.append(f"--- 尝试 {attempt + 1} ---\n{fixed}")

                # 验证：用 parse_ai_response 做完整校验（提取 + 顶层类型 + issue 级别）
                severity_threshold = getattr(self.config, 'severity_threshold', 'warning')
                fixed_result = parse_ai_response(fixed, filename, severity_threshold)
                if not any(kw in fixed_result.summary for kw in JSON_ERROR_KEYWORDS):
                    # 校验通过，构建有意义的 summary
                    if fixed_result.issues:
                        issue_count = len(fixed_result.issues)
                        sev_counts = {}
                        for issue in fixed_result.issues:
                            sev_counts[issue.severity] = sev_counts.get(issue.severity, 0) + 1
                        sev_parts = [f"{c}个{s}" for s, c in sorted(sev_counts.items(), key=lambda x: -{'critical':4,'error':3,'warning':2,'info':1}.get(x[0],0))]
                        fixed_result.summary = f"发现 {issue_count} 个问题（{', '.join(sev_parts)}）"
                    elif not fixed_result.summary or fixed_result.summary in ('修复说明', ''):
                        fixed_result.summary = 'AI 审核完成，未发现问题'
                    # 兜底：确保 summary 不为空（AI 未提供有意义总结时使用）
                    if not fixed_result.summary:
                        fixed_result.summary = "AI 审核完成（未提供总结）"
                    # 写入日志（包含所有失败尝试），返回 ReviewResult
                    self._write_json_fix_log(filename, cache_md5,
                                             system_msg, fix_prompt, 
                                             "\n\n".join(all_attempts_log))
                    return fixed_result  # 校验通过，返回 ReviewResult

                # 校验失败，更新对话历史供下次使用
                error_msg = fixed_result.summary
                print(f"[信息] JSON 修复第 {attempt + 1} 次 schema 校验未通过：{fixed_result.summary}")
                if history_mode == "last":
                    attempt_history.clear()  # 只保留最后一次
                attempt_history.append({"role": "assistant", "content": fixed})
                attempt_history.append({"role": "user", "content": (
                    f"以上修复结果不满足 schema 要求，具体错误：\n{error_msg}\n"
                    f"\n请根据以上错误修正 JSON，确保满足 schema 约束。"
                )})

            except Exception as e:
                error_msg = f"处理异常: {e}"
                all_attempts_log.append(f"--- 尝试 {attempt + 1}（异常）---\n{str(e)}")
                if history_mode == "last":
                    attempt_history.clear()
                attempt_history.append({"role": "user", "content": (
                    f"修复处理异常：{error_msg}\n"
                    f"\n请重新修正 JSON，确保满足 schema 约束。"
                )})
                continue

        # 所有尝试都失败了，仍然写入日志（方便查看定位）
        self._write_json_fix_log(filename, cache_md5,
                                 system_msg, fix_prompt,
                                 "\n\n".join(all_attempts_log) + f"\n\n=== 最终结果：全部 {max_attempts} 次尝试均失败 ===")
        return None

    def _parse_response(self, response: str, filename: str, cache_md5: str = "") -> ReviewResult:
        """解析 AI 的响应文本为结构化的 ReviewResult

        解析策略（层层降级）：
        1. 本地解析（parse_ai_response）
        2. 本地修复（_try_parse_json 含多种策略）
        3. AI 修复 JSON（_fix_json_with_ai）
        4. 都失败 → passed=False

        Args:
            response: AI 返回的原始文本
            filename: 被审核的文件名
            cache_md5: MD5 前7位，用于解析失败时打印日志路径

        Returns:
            ReviewResult
        """
        # 获取用户配置的阻断级别
        severity_threshold = getattr(self.config, 'severity_threshold', 'warning')
        
        # ===== 阶段1: 本地解析 =====
        result = parse_ai_response(response, filename, severity_threshold)

        # ===== 阶段2: 解析或校验失败 → AI 修复 =====
        #
        # 为什么用关键词匹配？
        # passed=False 有两种完全不同的含义：
        #   1. JSON 本身有问题（语法错误、字段缺失、类型不对）→ 需要修复 AI 修 JSON
        #   2. JSON 合法，但审核发现代码有问题（有 warning/error issue）→ 不需要修复 JSON
        #
        # 这两种情况在 parse_ai_response 里都返回 passed=False，
        # 但 summary 文本不同。关键词匹配是区分它们的唯一方式。
        #
        # 关键词来源（parse_ai_response 中标准化生成的错误文本）：
        #   "JSON 解析失败"        → _try_parse_json 所有策略都失败
        #   "无法从响应中解析 JSON"  → 找不到任何 JSON 内容（花括号匹配、代码块提取都失败）
        #   "JSON 字段缺失"        → 顶层字段（summary/passed/issues）或 issue.message 缺失/为空
        #   "JSON 字段名错误"      → issue 使用了非标准字段名（如 description 而不是 message）
        #   "JSON 类型错误"        → severity 不在枚举中、line_number 不是整数等
        #
        # 如果 matched：说明 JSON 结构有问题，调用修复 AI
        # 如果 not matched：说明 JSON 合法，只是审核不通过，不调用修复 AI
        if not result.passed and any(kw in result.summary for kw in JSON_ERROR_KEYWORDS):
            broken_json = result.extracted_json

            if broken_json and self.client:
                print(f"[信息] JSON 本地解析失败，调用 AI 修复...")
                fixed_result = self._fix_json_with_ai(broken_json, filename, cache_md5=cache_md5)

                if fixed_result:
                    result = fixed_result
                    print(f"[信息] AI 修复 JSON 成功，解析通过")
                else:
                    print(f"[警告] AI 修复 JSON 失败")

            # 打印日志路径（帮助定位问题，用相对路径）
            md5_short = cache_md5 if cache_md5 else "unknown"
            cache_path = Path(self.repo_path) / ".ai-review" / "cache" / f"{md5_short}.json"
            ai_log = Path(self.repo_path) / ".ai-review" / "logs" / f"{md5_short}.ai.log"
            json_fix_log = Path(self.repo_path) / ".ai-review" / "logs" / f"{md5_short}.json_fix.log"
            print(f"    {os.path.relpath(cache_path)}")
            print(f"    {os.path.relpath(ai_log)}")
            print(f"    {os.path.relpath(json_fix_log)}")

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
        
        # 检查前置条件
        prereq = self._check_prerequisites(filename)
        if prereq:
            return prereq
        
        content = getattr(source_file, 'content', '')
        
        # 计算缓存 key（content 为空时禁用缓存避免空字符串 MD5 碰撞）
        cache_key = hashlib.md5(content.encode('utf-8')).hexdigest()[:7] if content else None
        
        # 检查缓存（可配置关闭；content 为空时禁用缓存）
        use_cache = getattr(self.config, 'use_cache', True) and cache_key is not None
        if use_cache:
            cached = self._check_cache(cache_key)
            if cached:
                cached.filename = filename
                cached.cache_md5 = cache_key
                print(f"[信息] 缓存命中: {filename}  跳过 AI 审核")
                cache_path = Path(self.repo_path) / ".ai-review" / "cache" / f"{cache_key}.json"
                print(f"  {os.path.relpath(cache_path)}")
                return cached
        
        prompt = self._build_full_file_prompt(source_file, cache_key)
        
        try:
            response = self._call_api(prompt, filename=filename, cache_md5=cache_key)
            result = self._parse_response(response, filename, cache_md5=cache_key)
            result.cache_md5 = cache_key
            # 审核成功，保存到缓存（可配置关闭）
            if use_cache:
                self._save_cache(cache_key, result)
            return result
        except Exception as e:
            print(f"[错误] 审核文件 {filename} 失败: {e}")
            return ReviewResult(
                filename=filename,
                summary=f"审核失败: {str(e)}",
                passed=False,  # ← 异常时标记未通过
                raw_response=str(e),
                cache_md5=cache_key,
            )
    
    def _get_cache_key_for_source(self, source_file: Any) -> Optional[str]:
        """计算 SourceFile 的缓存 key（MD5 前7位）
        
        Args:
            source_file: SourceFile 对象
            
        Returns:
            MD5 前7位字符串，或 None
        """
        content = getattr(source_file, 'content', '')
        if content:
            return hashlib.md5(content.encode('utf-8')).hexdigest()[:7]
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
        print(f"[信息] AI 审核中: {filename}\n")
        
        content = getattr(source_file, 'content', '')
        cache_key = hashlib.md5(content.encode('utf-8')).hexdigest()[:7] if content else None
        
        try:
            prompt = self._build_full_file_prompt(source_file, cache_key)
            response = self._call_api(prompt, filename=filename, cache_md5=cache_key)
            result = self._parse_response(response, filename, cache_md5=cache_key)
            if getattr(self.config, 'use_cache', True) and cache_key is not None:
                self._save_cache(cache_key, result)
            return result
        except Exception as e:
            print(f"[错误] 审核文件 {filename} 失败: {e}")
            return ReviewResult(
                filename=filename,
                summary=f"审核失败: {str(e)}",
                passed=False,  # ← 异常时标记未通过
                raw_response=str(e),
                cache_md5=cache_key,
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
        
        # 检查是否启用缓存
        use_cache = getattr(self.config, 'use_cache', True)

        # ===== 第一阶段：批量检查缓存（可配置关闭）=====
        cache_hit_indices: List[int] = []
        cache_miss_indices: List[int] = list(range(len(source_files)))
        
        if use_cache:
            cache_hit_indices = []
            cache_miss_indices = []
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
                    print(f"[信息] 缓存命中: {filename}  跳过 AI 审核")
                    if cache_key:
                        cache_path = Path(self.repo_path) / ".ai-review" / "cache" / f"{cache_key}.json"
                        print(f"  {os.path.relpath(cache_path)}")
        
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
                            passed=False,  # 异常默认阻断
                            raw_response=str(e),
                        )
        
        return results
    
    def _build_full_file_prompt(self, source_file: Any, cache_md5: str = "") -> str:
        """
        构建完整文件审核的提示词
        
        从 .ai-review/prompts/full_file_review.md 加载模板，
        找不到就用内置默认模板。
        
        文件内容会加上行号前缀（如 "145 | let x = ..."），
        让 AI 返回正确的 line_number，不受 prompt 前面说明文字的影响。
        
        Args:
            source_file: SourceFile 对象
            cache_md5: MD5 前7位，用于日志文件名命名
            
        Returns:
            完整的 prompt 字符串
        """
        filename = getattr(source_file, 'filename', 'unknown')
        language = getattr(source_file, 'language', 'unknown')
        content = getattr(source_file, 'content', '')
        line_count = getattr(source_file, 'line_count', 0)
        
        # 注：已取消文件截断。MiniMax 等模型输入上下文 200K+，
        # 完整文件（通常 < 50K 字符）不可能触及限制。
        truncated = False
        truncate_note = ""
        
        # 给文件内容加上行号前缀（关键：让 AI 看到正确的文件行号）
        content = self._annotate_content_with_line_numbers(content)
        
        language_display = {
            'python': 'Python', 'javascript': 'JavaScript', 'typescript': 'TypeScript',
            'java': 'Java', 'go': 'Go', 'rust': 'Rust', 'cpp': 'C++',
            'c': 'C', 'csharp': 'C#', 'ruby': 'Ruby', 'php': 'PHP',
        }.get(language, language)
        
        # 加载与当前编程语言匹配的案例
        cases = self.case_loader.get_cases_for_language(language)
        cases_text = self.case_loader.format_cases_for_prompt(
            cases,
            case_format=getattr(self.config, 'case_format', 'default')
        )
        
        # 加载模板并渲染
        template = self.prompt_loader.load_full_file_template()
        prompt = template.replace("{{filename}}", filename)
        prompt = prompt.replace("{{language}}", language)
        prompt = pr