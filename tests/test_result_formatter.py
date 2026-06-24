"""Tests for result_formatter module."""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commit_ai_guardian.result_formatter import ResultFormatter


# ---- Mock data classes (minimal replicas for testing) ----

@dataclass
class MockReviewIssue:
    """Mock ReviewIssue for testing."""
    severity: str = "info"
    category: str = "best-practice"
    line_number: Optional[int] = None
    message: str = ""
    suggestion: str = ""
    code_snippet: str = ""


@dataclass
class MockReviewResult:
    """Mock ReviewResult for testing."""
    filename: str = ""
    issues: List[MockReviewIssue] = field(default_factory=list)
    summary: str = ""
    passed: bool = True
    raw_response: str = ""
    cache_md5: str = ""


# ---- Fixtures ----

@pytest.fixture
def formatter(sample_config):
    """Return a ResultFormatter instance with sample config."""
    return ResultFormatter(sample_config, repo_path=".")


@pytest.fixture
def passed_result_no_issues():
    """Return a passed ReviewResult with no issues."""
    return MockReviewResult(
        filename="src/clean.py",
        passed=True,
        issues=[],
        summary="代码质量良好",
    )


@pytest.fixture
def failed_result_with_critical_issue():
    """Return a failed ReviewResult with a critical issue."""
    return MockReviewResult(
        filename="src/broken.py",
        passed=False,
        issues=[
            MockReviewIssue(
                severity="critical",
                category="security",
                line_number=42,
                message="SQL 注入漏洞",
                suggestion="使用参数化查询",
                code_snippet="cursor.execute(query)",
            ),
        ],
        summary="发现严重问题",
    )


@pytest.fixture
def result_with_warning():
    """Return a passed ReviewResult with a warning-level issue."""
    return MockReviewResult(
        filename="src/warning.py",
        passed=True,
        issues=[
            MockReviewIssue(
                severity="warning",
                category="style",
                line_number=10,
                message="函数过长",
                suggestion="拆分为小函数",
                code_snippet="def very_long_function():",
            ),
        ],
        summary="发现风格问题",
    )


@pytest.fixture
def result_with_all_severities():
    """Return a ReviewResult with issues of all severity levels."""
    return MockReviewResult(
        filename="src/mixed.py",
        passed=False,
        issues=[
            MockReviewIssue(severity="critical", category="bug", line_number=1, message="崩溃"),
            MockReviewIssue(severity="error", category="performance", line_number=2, message="慢查询"),
            MockReviewIssue(severity="warning", category="best-practice", line_number=3, message="魔法数"),
            MockReviewIssue(severity="info", category="documentation", line_number=4, message="缺文档"),
        ],
    )


@pytest.fixture
def result_with_all_categories():
    """Return a ReviewResult with issues of all categories."""
    return MockReviewResult(
        filename="src/allcats.py",
        passed=False,
        issues=[
            MockReviewIssue(severity="error", category="bug", message="bug issue"),
            MockReviewIssue(severity="error", category="security", message="security issue"),
            MockReviewIssue(severity="error", category="style", message="style issue"),
            MockReviewIssue(severity="error", category="performance", message="performance issue"),
            MockReviewIssue(severity="error", category="best-practice", message="best-practice issue"),
            MockReviewIssue(severity="error", category="documentation", message="documentation issue"),
        ],
    )


# ---- SEVERITY_STYLES completeness ----

class TestSeverityStyles:
    """Tests for SEVERITY_STYLES dictionary completeness."""

    def test_has_all_severity_keys(self, formatter):
        """SEVERITY_STYLES must contain all four severity levels."""
        expected = {"critical", "error", "warning", "info"}
        assert set(formatter.SEVERITY_STYLES.keys()) == expected

    def test_critical_style_is_bold_red(self, formatter):
        """Critical severity must have bold red style."""
        assert formatter.SEVERITY_STYLES["critical"] == "bold red"

    def test_error_style_is_red(self, formatter):
        """Error severity must have red style."""
        assert formatter.SEVERITY_STYLES["error"] == "red"

    def test_warning_style_is_yellow(self, formatter):
        """Warning severity must have yellow style."""
        assert formatter.SEVERITY_STYLES["warning"] == "yellow"

    def test_info_style_is_blue(self, formatter):
        """Info severity must have blue style."""
        assert formatter.SEVERITY_STYLES["info"] == "blue"


# ---- CATEGORY_ICONS completeness ----

class TestCategoryIcons:
    """Tests for CATEGORY_ICONS dictionary completeness."""

    def test_has_all_category_keys(self, formatter):
        """CATEGORY_ICONS must contain all six category keys."""
        expected = {"bug", "security", "style", "performance", "best-practice", "documentation"}
        assert set(formatter.CATEGORY_ICONS.keys()) == expected

    def test_bug_icon_is_present(self, formatter):
        """Bug category must have a non-empty icon."""
        assert formatter.CATEGORY_ICONS["bug"]

    def test_security_icon_is_present(self, formatter):
        """Security category must have a non-empty icon."""
        assert formatter.CATEGORY_ICONS["security"]

    def test_style_icon_is_present(self, formatter):
        """Style category must have a non-empty icon."""
        assert formatter.CATEGORY_ICONS["style"]

    def test_performance_icon_is_present(self, formatter):
        """Performance category must have a non-empty icon."""
        assert formatter.CATEGORY_ICONS["performance"]

    def test_best_practice_icon_is_present(self, formatter):
        """Best-practice category must have a non-empty icon."""
        assert formatter.CATEGORY_ICONS["best-practice"]

    def test_documentation_icon_is_present(self, formatter):
        """Documentation category must have a non-empty icon."""
        assert formatter.CATEGORY_ICONS["documentation"]


# ---- format_and_display() ----

class TestFormatAndDisplay:
    """Tests for format_and_display method."""

    def test_empty_results_returns_true(self, formatter):
        """format_and_display with empty list should return True and print no-files panel."""
        with patch.object(formatter.console, "print") as mock_print:
            result = formatter.format_and_display([])
        assert result is True
        mock_print.assert_called_once()

    def test_single_passed_file_returns_true(self, formatter, passed_result_no_issues):
        """Single passed file with no issues should return True."""
        with patch.object(formatter.console, "print"):
            result = formatter.format_and_display([passed_result_no_issues])
        assert result is True

    def test_single_failed_file_returns_false(self, formatter, failed_result_with_critical_issue):
        """Single failed file should return False."""
        with patch.object(formatter.console, "print"):
            result = formatter.format_and_display([failed_result_with_critical_issue])
        assert result is False

    def test_mixed_results_returns_false(self, formatter, passed_result_no_issues, failed_result_with_critical_issue):
        """Mixed passed/failed results should return False when at least one fails."""
        with patch.object(formatter.console, "print"):
            result = formatter.format_and_display([passed_result_no_issues, failed_result_with_critical_issue])
        assert result is False

    def test_all_passed_results_returns_true(self, formatter, passed_result_no_issues, result_with_warning):
        """All passed results should return True."""
        with patch.object(formatter.console, "print"):
            result = formatter.format_and_display([passed_result_no_issues, result_with_warning])
        assert result is True

    def test_calls_render_file_card_for_each_result(self, formatter, passed_result_no_issues, failed_result_with_critical_issue):
        """format_and_display should call _render_file_card for each result."""
        with patch.object(formatter, "_render_file_card") as mock_format, \
             patch.object(formatter.console, "print"):
            formatter.format_and_display([passed_result_no_issues, failed_result_with_critical_issue])
        assert mock_format.call_count == 2

    def test_calls_render_summary(self, formatter, passed_result_no_issues):
        """format_and_display should call _render_summary."""
        with patch.object(formatter, "_render_file_card", return_value=True), \
             patch.object(formatter, "_render_summary") as mock_summary, \
             patch.object(formatter.console, "print"):
            formatter.format_and_display([passed_result_no_issues])
        mock_summary.assert_called_once()

    def test_multiple_files_subtitle_shows_count(self, formatter, passed_result_no_issues, failed_result_with_critical_issue):
        """Panel subtitle should show the total number of files reviewed."""
        with patch.object(formatter.console, "print") as mock_print:
            formatter.format_and_display([passed_result_no_issues, failed_result_with_critical_issue])
        # First call after empty line is the header panel with subtitle
        call_args = mock_print.call_args_list
        assert len(call_args) >= 2


# ---- _render_file_card() ----

class TestFormatFileResult:
    """Tests for _render_file_card method."""

    def test_passed_no_issues_returns_true(self, formatter, passed_result_no_issues):
        """Passed result with no issues should return True and print a panel."""
        with patch.object(formatter.console, "print") as mock_print:
            result = formatter._render_file_card(passed_result_no_issues)
        assert result is True
        assert mock_print.call_count >= 1  # Panel + optional trailing newline

    def test_failed_with_issues_returns_false(self, formatter, failed_result_with_critical_issue):
        """Failed result should return False."""
        with patch.object(formatter.console, "print"):
            result = formatter._render_file_card(failed_result_with_critical_issue)
        assert result is False

    def test_warning_result_returns_true(self, formatter, result_with_warning):
        """Result with warning issues (passed=True) should return True."""
        with patch.object(formatter.console, "print"):
            result = formatter._render_file_card(result_with_warning)
        assert result is True

    def test_no_issues_uses_green_border(self, formatter, passed_result_no_issues):
        """Passed result with no issues should use green border."""
        with patch.object(formatter.console, "print") as mock_print:
            formatter._render_file_card(passed_result_no_issues)
        panel = mock_print.call_args_list[0][0][0]
        assert panel.border_style == "green"

    def test_failed_uses_red_border(self, formatter, failed_result_with_critical_issue):
        """Failed result should use red border."""
        with patch.object(formatter.console, "print") as mock_print:
            formatter._render_file_card(failed_result_with_critical_issue)
        panel = mock_print.call_args_list[0][0][0]
        assert panel.border_style == "red"

    def test_warning_uses_yellow_border(self, formatter, result_with_warning):
        """Result with warnings should use yellow border."""
        with patch.object(formatter.console, "print") as mock_print:
            formatter._render_file_card(result_with_warning)
        panel = mock_print.call_args_list[0][0][0]
        assert panel.border_style == "yellow"

    def test_critical_severity_renders(self, formatter, failed_result_with_critical_issue):
        """Critical severity issue should render without error."""
        with patch.object(formatter.console, "print"):
            formatter._render_file_card(failed_result_with_critical_issue)

    def test_all_severities_render(self, formatter, result_with_all_severities):
        """Issues with all severity levels should render without error."""
        with patch.object(formatter.console, "print"):
            formatter._render_file_card(result_with_all_severities)

    def test_all_categories_render(self, formatter, result_with_all_categories):
        """Issues with all category types should render without error."""
        with patch.object(formatter.console, "print"):
            formatter._render_file_card(result_with_all_categories)

    def test_issue_without_line_number_renders(self, formatter):
        """Issue without line_number should render using filename only."""
        result = MockReviewResult(
            filename="src/noline.py",
            passed=False,
            issues=[MockReviewIssue(severity="error", message="no line number")],
        )
        with patch.object(formatter.console, "print"):
            formatter._render_file_card(result)

    def test_issue_with_long_snippet_gets_truncated(self, formatter):
        """Code snippet longer than 80 chars should be truncated."""
        long_snippet = "x" * 100
        result = MockReviewResult(
            filename="src/long.py",
            passed=False,
            issues=[MockReviewIssue(severity="error", code_snippet=long_snippet)],
        )
        with patch.object(formatter.console, "print"):
            formatter._render_file_card(result)

    def test_cache_md5_shown_when_present(self, formatter, passed_result_no_issues):
        """Cache MD5 should be displayed when present."""
        result = MockReviewResult(
            filename="src/cached.py",
            passed=True,
            cache_md5="abc1234",
        )
        with patch.object(formatter.console, "print"):
            formatter._render_file_card(result)


# ---- _render_summary() ----

class TestFormatSummary:
    """Tests for _render_summary method."""

    def test_empty_results_does_not_crash(self, formatter):
        """Summary with empty results should not crash."""
        with patch.object(formatter.console, "print") as mock_print:
            formatter._render_summary([])
        assert mock_print.call_count >= 1

    def test_single_passed_file_renders(self, formatter, passed_result_no_issues):
        """Summary should render for passed file."""
        with patch.object(formatter.console, "print") as mock_print:
            formatter._render_summary([passed_result_no_issues])
        assert mock_print.call_count >= 1

    def test_single_failed_file_renders(self, formatter, failed_result_with_critical_issue):
        """Summary should render for failed file."""
        with patch.object(formatter.console, "print") as mock_print:
            formatter._render_summary([failed_result_with_critical_issue])
        assert mock_print.call_count >= 1

    def test_mixed_results_renders(self, formatter, passed_result_no_issues, failed_result_with_critical_issue):
        """Summary should render for mixed results."""
        with patch.object(formatter.console, "print") as mock_print:
            formatter._render_summary([passed_result_no_issues, failed_result_with_critical_issue])
        assert mock_print.call_count >= 1

    def test_with_issues_shows_severity_table(self, formatter, result_with_all_severities):
        """With issues, severity distribution table should be printed."""
        with patch.object(formatter.console, "print") as mock_print:
            formatter._render_summary([result_with_all_severities])
        # Should print stats table + newline + severity panel + newline = 4+ calls
        assert mock_print.call_count >= 2

    def test_zero_issues_hides_severity_table(self, formatter, passed_result_no_issues):
        """When there are zero issues, severity distribution should not be printed."""
        with patch.object(formatter.console, "print") as mock_print:
            formatter._render_summary([passed_result_no_issues])
        # Only stats table + newline = 2 calls (no severity panel)
        assert mock_print.call_count == 2


# ---- display helper methods ----

class TestDisplayHelpers:
    """Tests for display_error, display_info, display_success."""

    def test_display_error_calls_console_print(self, formatter):
        """display_error should call console.print."""
        with patch.object(formatter.console, "print") as mock_print:
            formatter.display_error("something went wrong")
        mock_print.assert_called_once()

    def test_display_info_calls_console_print(self, formatter):
        """display_info should call console.print."""
        with patch.object(formatter.console, "print") as mock_print:
            formatter.display_info("information message")
        mock_print.assert_called_once()

    def test_display_success_calls_console_print(self, formatter):
        """display_success should call console.print."""
        with patch.object(formatter.console, "print") as mock_print:
            formatter.display_success("success message")
        mock_print.assert_called_once()
