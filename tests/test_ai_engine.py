"""Tests for commit_ai_guardian.ai_engine module

Covers parse_ai_response, _check_prerequisites, _sanitize_log_filename,
ReviewIssue.__post_init__, and _try_parse_json.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commit_ai_guardian.ai_engine import (
    AIEngine,
    ReviewIssue,
    ReviewResult,
    _try_parse_json,
    parse_ai_response,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_config():
    """A minimal config-like object for AIEngine construction."""
    return SimpleNamespace(
        api_key="test-api-key",
        api_base="https://api.example.com/v1",
        model="gpt-4o-mini",
        timeout=60,
        max_tokens=4096,
        proxy=None,
        enabled=True,
        diff_mode="full",
    )


@pytest.fixture
def mock_engine(mock_config, tmp_path):
    """Return an AIEngine with all external deps mocked out."""
    # Bypass __init__ (which imports openai/httpx/CaseLoader/PromptLoader)
    # and manually set only the attributes that _check_prerequisites needs.
    with patch.object(AIEngine, "__init__", lambda self, **kw: None):
        engine = AIEngine.__new__(AIEngine)
        engine.config = mock_config
        engine.client = MagicMock()  # pretend we have a valid client
        engine.repo_path = str(tmp_path)
        engine._logs_dir = tmp_path / ".ai-review" / "logs"
        engine._logs_dir.mkdir(parents=True, exist_ok=True)
        yield engine


@pytest.fixture
def ai_response_with_issues():
    return (
        '<result>'
        '{"summary":"发现1个问题","passed":false,'
        '"issues":['
        '{"severity":"warning","category":"style","line_number":10,'
        '"message":"函数过长","suggestion":"拆分函数","code_snippet":"def long():"}'
        ']}'
        '</result>'
    )


# ---------------------------------------------------------------------------
# 1. parse_ai_response()
# ---------------------------------------------------------------------------

class TestParseAiResponse:
    """Verify parse_ai_response handles various AI response formats."""

    def test_empty_response_returns_passed_true(self):
        result = parse_ai_response("")
        assert result.passed is True
        assert result.summary == "API 返回空响应"
        assert result.issues == []

    def test_whitespace_only_response_returns_passed_true(self):
        result = parse_ai_response("   \n\t  ")
        assert result.passed is True
        assert result.summary == "API 返回空响应"

    def test_none_response_is_not_directly_callable(self):
        """Defensive: function checks 'if not response' so None acts like empty."""
        # parse_ai_response expects a string; passing None would error on .strip()
        # This test documents the boundary.
        pass

    def test_result_tag_with_valid_json(self):
        raw = '<result>{"summary":"代码良好","passed":true,"issues":[]}</result>'
        result = parse_ai_response(raw)
        assert result.passed is True
        assert result.summary == "代码良好"
        assert result.issues == []

    def test_result_tag_with_single_issue(self, ai_response_with_issues):
        result = parse_ai_response(ai_response_with_issues)
        assert result.passed is False
        assert result.summary == "发现1个问题"
        assert len(result.issues) == 1
        issue = result.issues[0]
        assert issue.severity == "warning"
        assert issue.category == "style"
        assert issue.line_number == 10
        assert issue.message == "函数过长"

    def test_result_tag_with_multiple_issues(self):
        raw = (
            '<result>'
            '{"summary":"发现2个问题","passed":false,'
            '"issues":['
            '{"severity":"error","category":"bug","line_number":5,"message":"空指针","suggestion":"检查null","code_snippet":"foo.bar"},'
            '{"severity":"info","category":"style","line_number":20,"message":"命名不规范","suggestion":"用snake_case","code_snippet":"varName"}'
            ']}'
            '</result>'
        )
        result = parse_ai_response(raw)
        assert len(result.issues) == 2
        assert result.issues[0].severity == "error"
        assert result.issues[1].severity == "info"

    def test_old_format_without_result_tag(self):
        raw = '{"summary":"旧格式结果","passed":true,"issues":[]}'
        result = parse_ai_response(raw)
        assert result.passed is True
        assert result.summary == "旧格式结果"

    def test_old_format_inside_code_block(self):
        raw = '```json\n{"summary":"代码块包裹","passed":true,"issues":[]}\n```'
        result = parse_ai_response(raw)
        assert result.passed is True
        assert result.summary == "代码块包裹"

    def test_tool_call_wrapped_response(self):
        raw = (
            '<minimax:tool_call>'
            '<result>{"summary":"工具调用","passed":true,"issues":[]}</result>'
            '</minimax:tool_call>'
        )
        result = parse_ai_response(raw)
        assert result.passed is True
        assert result.summary == "工具调用"

    def test_truncated_response_brace_completion(self):
        """Truncated JSON with unmatched braces – _try_parse_json should attempt repair."""
        raw = '<result>{"summary":"被截断","passed":true,"issues":[</result>'
        result = parse_ai_response(raw)
        # _try_parse_json attempts brace closing; result depends on repair success
        # The key assertion: it does not crash and returns a ReviewResult
        assert isinstance(result, ReviewResult)
        # With the raw response containing broken JSON inside <result>,
        # the regex extracts the inner content and _try_parse_json tries to fix it.

    def test_think_tag_is_filtered_before_parsing(self):
        raw = (
            '<think>这是推理过程</think>\n'
            '```json\n{"summary":"过滤think标签","passed":true,"issues":[]}\n```'
        )
        result = parse_ai_response(raw)
        assert result.passed is True
        assert result.summary == "过滤think标签"

    def test_filename_is_set_in_result(self):
        raw = '<result>{"summary":"","passed":true,"issues":[]}</result>'
        result = parse_ai_response(raw, filename="src/app.py")
        assert result.filename == "src/app.py"

    def test_raw_response_is_preserved(self):
        raw = '<result>{"summary":"x","passed":true,"issues":[]}</result>'
        result = parse_ai_response(raw)
        assert result.raw_response == raw

    def test_unparseable_response_returns_failed(self):
        raw = "这绝对不是 JSON"
        result = parse_ai_response(raw)
        assert result.passed is False
        # When no braces are found, strategy 3 sets json_str = entire text;
        # _try_parse_json then fails, yielding "JSON 解析失败"
        assert result.summary in ("JSON 解析失败", "无法从响应中解析 JSON")

    def test_braces_in_code_snippet_dont_break_extraction(self):
        """Code snippets with braces inside should not confuse extraction."""
        raw = (
            '<result>'
            '{"summary":"brace test","passed":false,'
            '"issues":['
            '{"severity":"warning","message":"bad","code_snippet":"if (x) { y(); }"}'
            ']}'
            '</result>'
        )
        result = parse_ai_response(raw)
        assert len(result.issues) == 1


# ---------------------------------------------------------------------------
# 2. _check_prerequisites()
# ---------------------------------------------------------------------------

class TestCheckPrerequisites:
    """Verify _check_prerequisites guards fire independently."""

    def test_enabled_false_returns_passed_true(self, mock_engine):
        mock_engine.config.enabled = False
        result = mock_engine._check_prerequisites("test.py")
        assert result is not None
        assert result.passed is True
        assert "已禁用" in result.summary

    def test_client_none_returns_passed_false(self, mock_engine):
        mock_engine.client = None
        result = mock_engine._check_prerequisites("test.py")
        assert result is not None
        assert result.passed is False
        assert "客户端未初始化" in result.summary

    def test_empty_api_key_returns_passed_false(self, mock_engine):
        mock_engine.config.api_key = ""
        result = mock_engine._check_prerequisites("test.py")
        assert result is not None
        assert result.passed is False
        assert "未配置 API Key" in result.summary

    def test_all_prerequisites_pass_returns_none(self, mock_engine):
        mock_engine.config.enabled = True
        mock_engine.config.api_key = "valid-key"
        # client is already set by the fixture
        result = mock_engine._check_prerequisites("test.py")
        assert result is None

    def test_filename_is_preserved_in_result(self, mock_engine):
        mock_engine.config.enabled = False
        result = mock_engine._check_prerequisites("src/main.py")
        assert result.filename == "src/main.py"

    def test_missing_enabled_attribute_defaults_to_true(self, mock_engine):
        """If config has no 'enabled', getattr defaults to True → continues checking."""
        del mock_engine.config.enabled
        mock_engine.config.api_key = ""
        result = mock_engine._check_prerequisites("test.py")
        assert result is not None
        assert result.passed is False  # fails on api_key, not enabled

    def test_missing_api_key_attribute_treated_as_empty(self, mock_engine):
        del mock_engine.config.api_key
        result = mock_engine._check_prerequisites("test.py")
        assert result is not None
        assert result.passed is False
        assert "未配置 API Key" in result.summary


# ---------------------------------------------------------------------------
# 3. _sanitize_log_filename()
# ---------------------------------------------------------------------------

class TestSanitizeLogFilename:
    """Verify _sanitize_log_filename produces safe file names."""

    def test_simple_filename_unchanged_except_extension(self):
        result = AIEngine._sanitize_log_filename("main.py")
        assert result == "main_py"

    def test_nested_path_replaces_separators(self):
        result = AIEngine._sanitize_log_filename("src/utils/helper.py")
        assert result == "src_utils_helper_py"

    def test_leading_dot_slash_removed(self):
        result = AIEngine._sanitize_log_filename("./src/auth.ts")
        assert result == "src_auth_ts"

    def test_ai_review_logs_prefix_removed(self):
        result = AIEngine._sanitize_log_filename(".ai-review/logs/test.ts")
        assert result == "test_ts"

    def test_windows_backslash_replaced(self):
        result = AIEngine._sanitize_log_filename("src\\auth.ts")
        assert result == "src_auth_ts"

    def test_multiple_dots_replaced(self):
        result = AIEngine._sanitize_log_filename("some.file.name.py")
        assert result == "some_file_name_py"

    def test_empty_string_returns_empty(self):
        result = AIEngine._sanitize_log_filename("")
        assert result == ""


# ---------------------------------------------------------------------------
# 4. ReviewIssue.__post_init__
# ---------------------------------------------------------------------------

class TestReviewIssuePostInit:
    """Verify ReviewIssue field validation in __post_init__."""

    def test_valid_severity_preserved(self):
        for valid in ["critical", "error", "warning", "info"]:
            issue = ReviewIssue(severity=valid)
            assert issue.severity == valid

    def test_invalid_severity_fallback_to_info(self):
        issue = ReviewIssue(severity="unknown")
        assert issue.severity == "info"

    def test_valid_category_preserved(self):
        for valid in ["bug", "security", "style", "performance", "best-practice", "documentation"]:
            issue = ReviewIssue(category=valid)
            assert issue.category == valid

    def test_invalid_category_fallback_to_best_practice(self):
        issue = ReviewIssue(category="unknown")
        assert issue.category == "best-practice"

    def test_integer_line_number_preserved(self):
        issue = ReviewIssue(line_number=42)
        assert issue.line_number == 42

    def test_string_line_number_converted_to_int(self):
        issue = ReviewIssue(line_number="80")
        assert issue.line_number == 80

    def test_line_number_range_extracts_first_number(self):
        """AI may return "80-81"; we keep the first number."""
        issue = ReviewIssue(line_number="80-81")
        assert issue.line_number == 80

    def test_none_line_number_stays_none(self):
        issue = ReviewIssue(line_number=None)
        assert issue.line_number is None

    def test_non_numeric_string_line_number_becomes_none(self):
        issue = ReviewIssue(line_number="not-a-number")
        assert issue.line_number is None

    def test_all_default_fields(self):
        issue = ReviewIssue()
        assert issue.severity == "info"
        assert issue.category == "best-practice"
        assert issue.line_number is None
        assert issue.message == ""
        assert issue.suggestion == ""
        assert issue.code_snippet == ""

    def test_line_number_with_whitespace_extracted(self):
        issue = ReviewIssue(line_number="  123  ")
        assert issue.line_number == 123

    def test_empty_string_line_number_becomes_none(self):
        issue = ReviewIssue(line_number="")
        assert issue.line_number is None


# ---------------------------------------------------------------------------
# 5. _try_parse_json()
# ---------------------------------------------------------------------------

class TestTryParseJson:
    """Verify _try_parse_json repair strategies."""

    def test_none_returns_none(self):
        assert _try_parse_json(None) is None

    def test_empty_string_returns_none(self):
        assert _try_parse_json("") is None

    def test_whitespace_only_returns_none(self):
        assert _try_parse_json("   \n  ") is None

    def test_valid_json_parses_directly(self):
        data = _try_parse_json('{"key": "value"}')
        assert data == {"key": "value"}

    def test_bom_prefix_is_stripped(self):
        data = _try_parse_json('\ufeff{"key": "value"}')
        assert data == {"key": "value"}

    def test_single_quotes_replaced_with_double_quotes(self):
        data = _try_parse_json("{'key': 'value'}")
        assert data == {"key": "value"}

    def test_trailing_comma_removed(self):
        data = _try_parse_json('{"items": [1, 2,],}')
        assert data == {"items": [1, 2]}

    def test_inline_comment_removed(self):
        data = _try_parse_json('{"key": "value" // this is a comment\n}')
        assert data == {"key": "value"}

    def test_returns_none_for_gibberish(self):
        assert _try_parse_json("not json at all") is None

    def test_truncated_json_with_unclosed_braces_attempts_repair(self):
        """If JSON starts with { but braces are unbalanced, tries to close them."""
        data = _try_parse_json('{"key": "value"')
        # The repair logic appends missing } and attempts parse
        assert data is not None
        assert data.get("key") == "value"

    def test_truncated_json_with_unclosed_bracket_attempts_repair(self):
        data = _try_parse_json('{"items": [1, 2')
        assert data is not None
        assert "items" in data

    def test_list_json_returns_none_not_dict(self):
        """_try_parse_json returns dict or None; a bare list is not a dict."""
        assert _try_parse_json('[1, 2, 3]') is None

    def test_nested_json_parses_correctly(self):
        data = _try_parse_json('{"outer": {"inner": 42}}')
        assert data == {"outer": {"inner": 42}}

    def test_json_with_unicode_parses(self):
        data = _try_parse_json('{"message": "代码审核"}')
        assert data == {"message": "代码审核"}
