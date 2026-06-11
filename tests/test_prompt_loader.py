"""Tests for commit_ai_guardian.prompt_loader module

覆盖:
- DEFAULT_SYSTEM_MESSAGE 内容完整性（包含所有5条规则）
- PromptLoader.render(): 变量替换、多变量、无变量
- get_default_template_files(): 返回3个模板
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from commit_ai_guardian.prompt_loader import (
    DEFAULT_DIFF_REVIEW_TEMPLATE,
    DEFAULT_FULL_FILE_TEMPLATE,
    DEFAULT_SYSTEM_MESSAGE,
    REPO_PROMPTS_DIR,
    PromptLoader,
)


# ============================================================
# DEFAULT_SYSTEM_MESSAGE 内容完整性
# ============================================================


class TestDefaultSystemMessage:
    """Test DEFAULT_SYSTEM_MESSAGE constant"""

    def test_not_empty(self):
        """DEFAULT_SYSTEM_MESSAGE 不应为空"""
        assert len(DEFAULT_SYSTEM_MESSAGE) > 0

    def test_is_string(self):
        """DEFAULT_SYSTEM_MESSAGE 应为字符串"""
        assert isinstance(DEFAULT_SYSTEM_MESSAGE, str)

    def test_contains_rule1(self):
        """包含规则1 - result 标签格式"""
        assert "规则1" in DEFAULT_SYSTEM_MESSAGE

    def test_contains_rule2(self):
        """包含规则2 - think 精简"""
        assert "规则2" in DEFAULT_SYSTEM_MESSAGE

    def test_contains_rule3(self):
        """包含规则3 - think 和 result 分开"""
        assert "规则3" in DEFAULT_SYSTEM_MESSAGE

    def test_contains_rule4(self):
        """包含规则4 - 无额外文字"""
        assert "规则4" in DEFAULT_SYSTEM_MESSAGE

    def test_contains_rule4_json_self_check(self):
        """包含规则4 - JSON 格式自检"""
        assert "JSON 格式自检" in DEFAULT_SYSTEM_MESSAGE

    def test_contains_result_tag(self):
        """包含 <result> 标签说明"""
        assert "<result>" in DEFAULT_SYSTEM_MESSAGE

    def test_contains_think_tag(self):
        """包含 <think> 标签说明"""
        assert "<think>" in DEFAULT_SYSTEM_MESSAGE

    def test_contains_correct_example(self):
        """包含正确示例标记"""
        assert "正确" in DEFAULT_SYSTEM_MESSAGE

    def test_contains_incorrect_example(self):
        """包含错误示例标记"""
        assert "错误" in DEFAULT_SYSTEM_MESSAGE

    def test_contains_json_escaped_quotes(self):
        """包含 JSON 引号转义说明"""
        assert "\\\"" in DEFAULT_SYSTEM_MESSAGE

    def test_contains_line_number_constraint(self):
        """包含 line_number 约束说明"""
        assert "line_number" in DEFAULT_SYSTEM_MESSAGE


# ============================================================
# DEFAULT_DIFF_REVIEW_TEMPLATE 内容
# ============================================================


class TestDefaultDiffReviewTemplate:
    """Test DEFAULT_DIFF_REVIEW_TEMPLATE constant"""

    def test_not_empty(self):
        """DEFAULT_DIFF_REVIEW_TEMPLATE 不应为空"""
        assert len(DEFAULT_DIFF_REVIEW_TEMPLATE) > 0

    def test_contains_filename_placeholder(self):
        """包含 {{filename}} 占位符"""
        assert "{{filename}}" in DEFAULT_DIFF_REVIEW_TEMPLATE

    def test_contains_language_placeholder(self):
        """包含 {{language}} 占位符"""
        assert "{{language}}" in DEFAULT_DIFF_REVIEW_TEMPLATE

    def test_contains_diff_content_placeholder(self):
        """包含 {{diff_content}} 占位符"""
        assert "{{diff_content}}" in DEFAULT_DIFF_REVIEW_TEMPLATE

    def test_contains_status_placeholder(self):
        """包含 {{status}} 占位符"""
        assert "{{status}}" in DEFAULT_DIFF_REVIEW_TEMPLATE

    def test_contains_language_display_placeholder(self):
        """包含 {{language_display}} 占位符"""
        assert "{{language_display}}" in DEFAULT_DIFF_REVIEW_TEMPLATE

    def test_contains_cases_text_placeholder(self):
        """包含 {{cases_text}} 占位符"""
        assert "{{cases_text}}" in DEFAULT_DIFF_REVIEW_TEMPLATE

    def test_contains_cases_note_placeholder(self):
        """包含 {{cases_note}} 占位符"""
        assert "{{cases_note}}" in DEFAULT_DIFF_REVIEW_TEMPLATE

    def test_contains_severity_levels_in_system(self):
        """严重级别定义已移到 system message"""
        assert "critical" in DEFAULT_SYSTEM_MESSAGE
        assert "error" in DEFAULT_SYSTEM_MESSAGE
        assert "warning" in DEFAULT_SYSTEM_MESSAGE
        assert "info" in DEFAULT_SYSTEM_MESSAGE
        assert "严重级别定义" in DEFAULT_SYSTEM_MESSAGE

    def test_contains_review_dimensions_in_system(self):
        """审核维度说明已移到 system message"""
        assert "Bug 检测" in DEFAULT_SYSTEM_MESSAGE
        assert "审核维度" in DEFAULT_SYSTEM_MESSAGE

    def test_template_refers_to_system_message(self):
        """模板提示 AI 参考 system message 中的规则"""
        assert "system message" in DEFAULT_DIFF_REVIEW_TEMPLATE.lower()


# ============================================================
# DEFAULT_FULL_FILE_TEMPLATE 内容
# ============================================================


class TestDefaultFullFileTemplate:
    """Test DEFAULT_FULL_FILE_TEMPLATE constant"""

    def test_not_empty(self):
        """DEFAULT_FULL_FILE_TEMPLATE 不应为空"""
        assert len(DEFAULT_FULL_FILE_TEMPLATE) > 0

    def test_contains_filename_placeholder(self):
        """包含 {{filename}} 占位符"""
        assert "{{filename}}" in DEFAULT_FULL_FILE_TEMPLATE

    def test_contains_language_placeholder(self):
        """包含 {{language}} 占位符"""
        assert "{{language}}" in DEFAULT_FULL_FILE_TEMPLATE

    def test_contains_content_placeholder(self):
        """包含 {{content}} 占位符"""
        assert "{{content}}" in DEFAULT_FULL_FILE_TEMPLATE

    def test_contains_line_count_placeholder(self):
        """包含 {{line_count}} 占位符"""
        assert "{{line_count}}" in DEFAULT_FULL_FILE_TEMPLATE

    def test_contains_language_display_placeholder(self):
        """包含 {{language_display}} 占位符"""
        assert "{{language_display}}" in DEFAULT_FULL_FILE_TEMPLATE

    def test_contains_truncation_note_placeholder(self):
        """包含 {{truncation_note}} 占位符"""
        assert "{{truncation_note}}" in DEFAULT_FULL_FILE_TEMPLATE

    def test_contains_cases_text_placeholder(self):
        """包含 {{cases_text}} 占位符"""
        assert "{{cases_text}}" in DEFAULT_FULL_FILE_TEMPLATE

    def test_contains_cases_note_placeholder(self):
        """包含 {{cases_note}} 占位符"""
        assert "{{cases_note}}" in DEFAULT_FULL_FILE_TEMPLATE


# ============================================================
# PromptLoader.render()
# ============================================================


class TestPromptLoaderRender:
    """Test PromptLoader.render() static method"""

    def test_single_variable_replacement(self):
        """单变量替换"""
        template = "Hello {{name}}!"
        result = PromptLoader.render(template, name="World")
        assert result == "Hello World!"

    def test_multiple_variable_replacement(self):
        """多变量替换"""
        template = "File: {{filename}}, Language: {{language}}"
        result = PromptLoader.render(
            template, filename="main.py", language="python"
        )
        assert result == "File: main.py, Language: python"

    def test_no_variables(self):
        """无变量的模板保持不变"""
        template = "Hello World!"
        result = PromptLoader.render(template)
        assert result == "Hello World!"

    def test_no_matching_variables(self):
        """提供的变量与模板中的不匹配，模板保持不变"""
        template = "Hello {{name}}!"
        result = PromptLoader.render(template, age=25)
        assert result == "Hello {{name}}!"

    def test_extra_variables_ignored(self):
        """多余的变量被忽略"""
        template = "Hello {{name}}!"
        result = PromptLoader.render(template, name="World", extra="ignored")
        assert result == "Hello World!"

    def test_empty_template(self):
        """空模板返回空字符串"""
        result = PromptLoader.render("")
        assert result == ""

    def test_empty_variable_value(self):
        """变量值为空字符串"""
        template = "Content: {{content}}"
        result = PromptLoader.render(template, content="")
        assert result == "Content: "

    def test_numeric_value_converted_to_string(self):
        """数值变量自动转为字符串"""
        template = "Count: {{count}}"
        result = PromptLoader.render(template, count=42)
        assert result == "Count: 42"

    def test_repeated_variable(self):
        """模板中同一变量出现多次"""
        template = "{{name}} says hello to {{name}}"
        result = PromptLoader.render(template, name="Alice")
        assert result == "Alice says hello to Alice"

    def test_render_with_system_message(self):
        """使用实际 system_message 模板渲染（无变量）"""
        result = PromptLoader.render(DEFAULT_SYSTEM_MESSAGE)
        assert result == DEFAULT_SYSTEM_MESSAGE

    def test_render_diff_review_template(self):
        """使用 diff_review 模板渲染变量"""
        result = PromptLoader.render(
            DEFAULT_DIFF_REVIEW_TEMPLATE,
            filename="src/main.py",
            language="python",
            language_display="Python",
            status="modified",
            diff_content="+print('hello')",
            cases_text="",
            cases_note="",
        )
        assert "src/main.py" in result
        assert "{{filename}}" not in result
        assert "{{language}}" not in result
        assert "{{diff_content}}" not in result

    def test_render_full_file_template(self):
        """使用 full_file 模板渲染变量"""
        result = PromptLoader.render(
            DEFAULT_FULL_FILE_TEMPLATE,
            filename="src/main.py",
            language="python",
            language_display="Python",
            line_count=42,
            content="def hello():\n    pass\n",
            truncation_note="",
            cases_text="",
            cases_note="",
        )
        assert "src/main.py" in result
        assert "def hello():" in result
        assert "{{content}}" not in result
        assert "{{filename}}" not in result

    def test_render_preserves_unmatched_placeholders(self):
        """未匹配的占位符保留在结果中"""
        template = "{{replaced}} and {{not_replaced}}"
        result = PromptLoader.render(template, replaced="yes")
        assert result == "yes and {{not_replaced}}"


# ============================================================
# PromptLoader.get_default_template_files()
# ============================================================


class TestPromptLoaderGetDefaultTemplateFiles:
    """Test get_default_template_files()"""

    def test_returns_dict(self):
        """返回字典类型"""
        result = PromptLoader.get_default_template_files()
        assert isinstance(result, dict)

    def test_returns_three_templates(self):
        """返回3个模板文件"""
        result = PromptLoader.get_default_template_files()
        assert len(result) == 3

    def test_contains_system_message(self):
        """包含 system_message.txt"""
        result = PromptLoader.get_default_template_files()
        assert "system_message.txt" in result

    def test_contains_diff_review(self):
        """包含 diff_review.md"""
        result = PromptLoader.get_default_template_files()
        assert "diff_review.md" in result

    def test_contains_full_file_review(self):
        """包含 full_file_review.md"""
        result = PromptLoader.get_default_template_files()
        assert "full_file_review.md" in result

    def test_system_message_content_matches(self):
        """system_message.txt 的内容与常量一致"""
        result = PromptLoader.get_default_template_files()
        assert result["system_message.txt"] == DEFAULT_SYSTEM_MESSAGE

    def test_diff_review_content_matches(self):
        """diff_review.md 的内容与常量一致"""
        result = PromptLoader.get_default_template_files()
        assert result["diff_review.md"] == DEFAULT_DIFF_REVIEW_TEMPLATE

    def test_full_file_review_content_matches(self):
        """full_file_review.md 的内容与常量一致"""
        result = PromptLoader.get_default_template_files()
        assert result["full_file_review.md"] == DEFAULT_FULL_FILE_TEMPLATE

    def test_all_values_are_strings(self):
        """所有模板值应为字符串"""
        result = PromptLoader.get_default_template_files()
        for key, value in result.items():
            assert isinstance(key, str)
            assert isinstance(value, str)
            assert len(value) > 0


# ============================================================
# PromptLoader initialization
# ============================================================


class TestPromptLoaderInit:
    """Test PromptLoader 初始化"""

    def test_init_default(self):
        """默认初始化（无 repo_path）"""
        loader = PromptLoader()
        assert loader.repo_path is None
        assert loader.prompts_dir is None

    def test_init_with_nonexistent_repo_path(self, temp_dir):
        """repo_path 不存在 .ai-review/prompts/"""
        loader = PromptLoader(repo_path=str(temp_dir))
        assert loader.repo_path == str(temp_dir)
        assert loader.prompts_dir is None

    def test_init_with_existing_prompts_dir(self, temp_dir):
        """repo_path 存在 .ai-review/prompts/"""
        prompts_dir = temp_dir / ".ai-review" / "prompts"
        prompts_dir.mkdir(parents=True)
        loader = PromptLoader(repo_path=str(temp_dir))
        assert loader.prompts_dir == prompts_dir

    def test_class_printed_set_exists(self):
        """类级别的 _printed 集合应存在"""
        assert hasattr(PromptLoader, "_printed")
        assert isinstance(PromptLoader._printed, set)


# ============================================================
# PromptLoader._load_file()
# ============================================================


class TestPromptLoaderLoadFile:
    """Test _load_file()"""

    def test_load_file_fallback_to_default(self, temp_dir):
        """模板文件不存在时使用默认内容"""
        loader = PromptLoader(repo_path=str(temp_dir))
        result = loader._load_file("nonexistent.txt", "default content")
        assert result == "default content"

    def test_load_file_from_prompts_dir(self, temp_dir):
        """从 prompts 目录加载模板文件"""
        prompts_dir = temp_dir / ".ai-review" / "prompts"
        prompts_dir.mkdir(parents=True)
        template_file = prompts_dir / "custom.txt"
        template_file.write_text("custom template content")
        loader = PromptLoader(repo_path=str(temp_dir))
        result = loader._load_file("custom.txt", "default")
        assert result == "custom template content"

    def test_load_file_custom_diff_review(self, temp_dir):
        """从 prompts 目录加载自定义 diff_review 模板"""
        prompts_dir = temp_dir / ".ai-review" / "prompts"
        prompts_dir.mkdir(parents=True)
        custom_template = "# Custom Diff Review\nFile: {{filename}}"
        template_file = prompts_dir / "diff_review.md"
        template_file.write_text(custom_template)
        loader = PromptLoader(repo_path=str(temp_dir))
        result = loader.load_diff_review_template()
        assert result == custom_template

    def test_load_file_custom_system_message(self, temp_dir):
        """从 prompts 目录加载自定义 system_message"""
        prompts_dir = temp_dir / ".ai-review" / "prompts"
        prompts_dir.mkdir(parents=True)
        custom_msg = "Custom system message"
        template_file = prompts_dir / "system_message.txt"
        template_file.write_text(custom_msg)
        loader = PromptLoader(repo_path=str(temp_dir))
        result = loader.load_system_message()
        assert result == custom_msg

    def test_load_file_custom_full_file(self, temp_dir):
        """从 prompts 目录加载自定义 full_file_review 模板"""
        prompts_dir = temp_dir / ".ai-review" / "prompts"
        prompts_dir.mkdir(parents=True)
        custom_template = "# Custom Full File Review"
        template_file = prompts_dir / "full_file_review.md"
        template_file.write_text(custom_template)
        loader = PromptLoader(repo_path=str(temp_dir))
        result = loader.load_full_file_template()
        assert result == custom_template

    def test_load_file_no_prompts_dir_uses_default(self, temp_dir):
        """无 prompts 目录时使用默认模板"""
        loader = PromptLoader(repo_path=str(temp_dir))
        result = loader.load_system_message()
        assert result == DEFAULT_SYSTEM_MESSAGE

    def test_load_file_default_without_repo_path(self):
        """无 repo_path 时使用默认模板"""
        loader = PromptLoader()
        result = loader.load_system_message()
        assert result == DEFAULT_SYSTEM_MESSAGE

    def test_load_file_default_diff_review_without_repo_path(self):
        """无 repo_path 时 diff_review 使用默认模板"""
        loader = PromptLoader()
        result = loader.load_diff_review_template()
        assert result == DEFAULT_DIFF_REVIEW_TEMPLATE

    def test_load_file_default_full_file_without_repo_path(self):
        """无 repo_path 时 full_file 使用默认模板"""
        loader = PromptLoader()
        result = loader.load_full_file_template()
        assert result == DEFAULT_FULL_FILE_TEMPLATE

    def test_load_file_handles_read_error(self, temp_dir, monkeypatch):
        """读取文件出错时使用默认内容"""
        prompts_dir = temp_dir / ".ai-review" / "prompts"
        prompts_dir.mkdir(parents=True)
        template_file = prompts_dir / "bad.txt"
        template_file.write_text("content")

        # Mock read_text to raise an exception
        def bad_read(*args, **kwargs):
            raise OSError("read error")

        monkeypatch.setattr(Path, "read_text", bad_read)
        loader = PromptLoader(repo_path=str(temp_dir))
        result = loader._load_file("bad.txt", "fallback")
        assert result == "fallback"


# ============================================================
# REPO_PROMPTS_DIR
# ============================================================


class TestRepoPromptsDir:
    """Test REPO_PROMPTS_DIR constant"""

    def test_is_path_object(self):
        """REPO_PROMPTS_DIR 应为 Path 对象"""
        assert isinstance(REPO_PROMPTS_DIR, Path)

    def test_correct_path(self):
        """REPO_PROMPTS_DIR 应为 .ai-review/prompts"""
        assert str(REPO_PROMPTS_DIR) == ".ai-review/prompts"
