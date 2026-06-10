"""case_loader 测试 — 全面测试案例格式化各种情况

测试覆盖:
1. 空列表 → 返回空字符串
2. 完整案例（所有字段都有）→ 正确格式化
3. 缺少可选字段的案例 → 不输出缺失部分
4. severity 是数字(int) → 显示 severity/level
5. severity 是字符串 → 只显示 level
6. 多个坏代码/好代码示例 → 都输出
7. 多个检查点 → 都输出
8. why_it_matters/consequences 多行 → 每行前缀
9. 代码中有特殊字符 → 正确处理
10. 空字符串字段 → 跳过
11. 空列表字段 → 跳过
12. 没有 good_examples → 不输出 ✅ 部分
13. 没有 bad_examples → 不输出 ❌ 部分
14. check_point 只有 question 没有 hint → 只输出 question
15. 多个案例 → 依次编号
"""

import sys
from pathlib import Path

import pytest

# 设置导入路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commit_ai_guardian.case_loader import CaseLoader


@pytest.fixture
def loader():
    """CaseLoader 实例（不需要真实仓库路径）"""
    return CaseLoader(repo_path=".")


# ==================== 基础场景 ====================

class TestEmptyCases:
    """空案例列表"""

    def test_empty_list_returns_empty_string(self, loader):
        """空列表应返回空字符串"""
        result = loader.format_cases_for_prompt([])
        assert result == ""


class TestFullCase:
    """完整案例（所有字段都有）"""

    def test_all_fields_present(self, loader):
        """所有字段都有的案例 → 完整格式化"""
        case = {
            "title": "SQL注入",
            "description": "未对用户输入进行转义导致SQL注入",
            "severity": 9,
            "level": "critical",
            "bad_examples": [
                {"label": "直接拼接", "code": 'query = f"SELECT * FROM users WHERE id = {user_id}"'},
            ],
            "good_examples": [
                {"label": "参数化查询", "code": 'query = "SELECT * FROM users WHERE id = %s"\ncursor.execute(query, (user_id,))'},
            ],
            "why_it_matters": "恶意用户可注入任意SQL语句",
            "consequences": "数据泄露、数据损坏",
            "check_points": [
                {"question": "是否使用了参数化查询", "hint": "检查所有SQL拼接点"},
            ],
        }
        result = loader.format_cases_for_prompt([case])
        print(f"\n=== 完整案例输出 ===\n{result}")
        
        assert "重点检查以下问题模式:" in result
        assert "[案例1|SQL注入|9/critical]" in result
        assert "说明: 未对用户输入进行转义导致SQL注入" in result
        assert "❌ 坏代码(直接拼接):" in result
        assert 'query = f"SELECT * FROM users WHERE id = {user_id}"' in result
        assert "✅ 好代码(参数化查询):" in result
        assert "原因: 恶意用户可注入任意SQL语句" in result
        assert "后果: 数据泄露、数据损坏" in result
        assert "检查: 是否使用了参数化查询" in result
        assert "提示: 检查所有SQL拼接点" in result


# ==================== severity 格式 ====================

class TestSeverityFormat:
    """severity 字段格式（数字 vs 字符串）"""

    def test_severity_is_int(self, loader):
        """severity 是整数 → 显示 severity/level"""
        case = {
            "title": "测试",
            "severity": 9,
            "level": "critical",
        }
        result = loader.format_cases_for_prompt([case])
        assert "[案例1|测试|9/critical]" in result

    def test_severity_is_string(self, loader):
        """severity 是字符串 → 只显示 level"""
        case = {
            "title": "测试",
            "severity": "high",
            "level": "error",
        }
        result = loader.format_cases_for_prompt([case])
        assert "[案例1|测试|error]" in result
        # 不应显示 severity 值
        assert "high" not in result


# ==================== 可选字段缺失 ====================

class TestMissingOptionalFields:
    """可选字段缺失时应跳过对应部分"""

    def test_no_description(self, loader):
        """没有 description → 不输出说明行"""
        case = {
            "title": "测试",
            "level": "warning",
        }
        result = loader.format_cases_for_prompt([case])
        assert "说明:" not in result

    def test_no_why_it_matters(self, loader):
        """没有 why_it_matters → 不输出原因行"""
        case = {
            "title": "测试",
            "level": "warning",
        }
        result = loader.format_cases_for_prompt([case])
        assert "原因:" not in result

    def test_no_consequences(self, loader):
        """没有 consequences → 不输出后果行"""
        case = {
            "title": "测试",
            "level": "warning",
        }
        result = loader.format_cases_for_prompt([case])
        assert "后果:" not in result

    def test_no_bad_examples(self, loader):
        """没有 bad_examples → 不输出 ❌ 部分"""
        case = {
            "title": "测试",
            "level": "warning",
            "good_examples": [{"label": "好", "code": "good()"}],
        }
        result = loader.format_cases_for_prompt([case])
        assert "❌" not in result
        assert "✅" in result

    def test_no_good_examples(self, loader):
        """没有 good_examples → 不输出 ✅ 部分"""
        case = {
            "title": "测试",
            "level": "warning",
            "bad_examples": [{"label": "坏", "code": "bad()"}],
        }
        result = loader.format_cases_for_prompt([case])
        assert "✅" not in result
        assert "❌" in result

    def test_no_examples_at_all(self, loader):
        """没有坏代码也没有好代码 → 不输出代码部分"""
        case = {
            "title": "测试",
            "level": "warning",
            "description": "说明文字",
        }
        result = loader.format_cases_for_prompt([case])
        assert "❌" not in result
        assert "✅" not in result
        assert "说明: 说明文字" in result


# ==================== 多个示例 ====================

class TestMultipleExamples:
    """多个坏代码/好代码示例"""

    def test_multiple_bad_examples(self, loader):
        """多个坏代码示例 → 都输出"""
        case = {
            "title": "测试",
            "level": "warning",
            "bad_examples": [
                {"label": "场景1", "code": "bad1()"},
                {"label": "场景2", "code": "bad2()"},
            ],
        }
        result = loader.format_cases_for_prompt([case])
        assert result.count("❌") == 2
        assert "❌ 坏代码(场景1):" in result
        assert "❌ 坏代码(场景2):" in result

    def test_multiple_good_examples(self, loader):
        """多个好代码示例 → 都输出"""
        case = {
            "title": "测试",
            "level": "warning",
            "good_examples": [
                {"label": "方案A", "code": "good_a()"},
                {"label": "方案B", "code": "good_b()"},
            ],
        }
        result = loader.format_cases_for_prompt([case])
        assert result.count("✅") == 2
        assert "✅ 好代码(方案A):" in result
        assert "✅ 好代码(方案B):" in result

    def test_multiple_check_points(self, loader):
        """多个检查点 → 都输出"""
        case = {
            "title": "测试",
            "level": "warning",
            "check_points": [
                {"question": "检查A", "hint": "提示A"},
                {"question": "检查B", "hint": "提示B"},
            ],
        }
        result = loader.format_cases_for_prompt([case])
        assert "检查: 检查A" in result
        assert "提示: 提示A" in result
        assert "检查: 检查B" in result
        assert "提示: 提示B" in result


# ==================== 多行内容 ====================

class TestMultilineContent:
    """多行内容的处理"""

    def test_why_it_matters_multiline(self, loader):
        """why_it_matters 多行 → 合并为一行用逗号分隔"""
        case = {
            "title": "测试",
            "level": "warning",
            "why_it_matters": "第一行原因\n第二行原因\n\n  \n",  # 含空行和空白
        }
        result = loader.format_cases_for_prompt([case])
        # 多行合并为一行，用逗号分隔
        assert "原因: 第一行原因，第二行原因" in result
        # 只出现一次"原因:"前缀
        assert result.count("原因:") == 1

    def test_consequences_multiline(self, loader):
        """consequences 多行 → 合并为一行用逗号分隔"""
        case = {
            "title": "测试",
            "level": "warning",
            "consequences": "数据泄露\n系统崩溃",
        }
        result = loader.format_cases_for_prompt([case])
        assert "后果: 数据泄露，系统崩溃" in result
        assert result.count("后果:") == 1

    def test_consequences_markdown_list(self, loader):
        """consequences 是 Markdown 列表（- 开头）→ 去掉标记后合并"""
        case = {
            "title": "测试",
            "level": "warning",
            "consequences": "- 数据泄露\n- 系统崩溃\n- 权限失控",
        }
        result = loader.format_cases_for_prompt([case])
        assert "后果: 数据泄露，系统崩溃，权限失控" in result
        # 不应保留 - 标记
        assert "- 数据泄露" not in result


# ==================== 特殊字符和边界值 ====================

class TestSpecialCharacters:
    """代码中特殊字符的处理"""

    def test_code_with_backticks(self, loader):
        """代码含反引号 → 正确处理"""
        case = {
            "title": "测试",
            "level": "warning",
            "bad_examples": [
                {"label": "", "code": 'text = "`hello`"'},
            ],
        }
        result = loader.format_cases_for_prompt([case])
        assert 'text = "`hello`"' in result

    def test_code_with_braces(self, loader):
        """代码含花括号 → 正确处理（不影响 JSON）"""
        case = {
            "title": "测试",
            "level": "warning",
            "bad_examples": [
                {"label": "", "code": 'if(x){"a":1}'},
            ],
        }
        result = loader.format_cases_for_prompt([case])
        assert 'if(x){"a":1}' in result

    def test_code_with_chinese(self, loader):
        """代码含中文 → 正确处理"""
        case = {
            "title": "测试",
            "level": "warning",
            "bad_examples": [
                {"label": "中文标签", "code": 'print("你好")'},
            ],
        }
        result = loader.format_cases_for_prompt([case])
        assert 'print("你好")' in result

    def test_empty_code(self, loader):
        """code 为空字符串 → 跳过输出"""
        case = {
            "title": "测试",
            "level": "warning",
            "bad_examples": [
                {"label": "空的", "code": ""},
            ],
        }
        result = loader.format_cases_for_prompt([case])
        assert "❌" not in result

    def test_empty_label(self, loader):
        """label 为空字符串 → 不显示括号"""
        case = {
            "title": "测试",
            "level": "warning",
            "bad_examples": [
                {"label": "", "code": "bad()"},
            ],
        }
        result = loader.format_cases_for_prompt([case])
        assert "❌ 坏代码:" in result
        assert "❌ 坏代码():" not in result


# ==================== 多个案例 ====================

class TestMultipleCases:
    """多个案例的编号和分隔"""

    def test_multiple_cases_numbered(self, loader):
        """多个案例依次编号"""
        cases = [
            {"title": "SQL注入", "level": "critical"},
            {"title": "XSS", "level": "error"},
            {"title": "硬编码密码", "level": "warning"},
        ]
        result = loader.format_cases_for_prompt(cases)
        assert "[案例1|SQL注入|critical]" in result
        assert "[案例2|XSS|error]" in result
        assert "[案例3|硬编码密码|warning]" in result


# ==================== 检查点边界值 ====================

class TestCheckPointEdgeCases:
    """检查点各种边界情况"""

    def test_check_point_only_question(self, loader):
        """只有 question 没有 hint → 只输出 question"""
        case = {
            "title": "测试",
            "level": "warning",
            "check_points": [
                {"question": "是否检查了", "hint": ""},
            ],
        }
        result = loader.format_cases_for_prompt([case])
        assert "检查: 是否检查了" in result
        assert "提示:" not in result

    def test_check_point_empty_question(self, loader):
        """空 question → 跳过"""
        case = {
            "title": "测试",
            "level": "warning",
            "check_points": [
                {"question": "", "hint": "有提示"},
            ],
        }
        result = loader.format_cases_for_prompt([case])
        assert "检查:" not in result
        assert "提示:" not in result


# ==================== Markdown 符号不应出现 ====================

class TestNoMarkdownSymbols:
    """输出中不应出现 Markdown 格式符号"""

    def test_no_markdown_headings(self, loader):
        """不应出现 ### 标题"""
        case = {
            "title": "测试",
            "level": "warning",
            "description": "说明",
        }
        result = loader.format_cases_for_prompt([case])
        assert "###" not in result

    def test_no_code_blocks(self, loader):
        """不应出现 ``` 代码块标记"""
        case = {
            "title": "测试",
            "level": "warning",
            "bad_examples": [{"label": "", "code": "bad()"}],
        }
        result = loader.format_cases_for_prompt([case])
        assert "```" not in result

    def test_no_checkbox(self, loader):
        """不应出现 ☐ 检查框"""
        case = {
            "title": "测试",
            "level": "warning",
            "check_points": [{"question": "检查", "hint": "提示"}],
        }
        result = loader.format_cases_for_prompt([case])
        assert "☐" not in result


# ==================== 压缩率验证 ====================

class TestCompression:
    """验证结构化格式确实比 Markdown 格式短"""

    def test_structured_shorter_than_markdown(self, loader):
        """相同内容，结构化格式应比 Markdown 短"""
        case = {
            "title": "SQL注入",
            "description": "未对用户输入进行转义导致SQL注入",
            "severity": 9,
            "level": "critical",
            "bad_examples": [
                {"label": "直接拼接", "code": 'query = f"SELECT * FROM users WHERE id = {user_id}"'},
            ],
            "good_examples": [
                {"label": "参数化查询", "code": 'query = "SELECT * FROM users WHERE id = %s"\ncursor.execute(query, (user_id,))'},
            ],
            "why_it_matters": "恶意用户可注入任意SQL语句",
            "consequences": "数据泄露、数据损坏",
            "check_points": [
                {"question": "是否使用了参数化查询", "hint": "检查所有SQL拼接点"},
            ],
        }

        # 当前（结构化）格式
        structured = loader.format_cases_for_prompt([case])

        # 模拟旧的 Markdown 格式
        old_lines = ["\n## 重点检查以下问题模式（参照案例）\n"]
        old_lines.append("### 1. SQL注入 [9/critical]")
        old_lines.append("说明: 未对用户输入进行转义导致SQL注入")
        old_lines.append("\n坏代码 - 直接拼接:")
        old_lines.append(f"```\n{case['bad_examples'][0]['code']}\n```")
        old_lines.append("\n好代码 - 参数化查询:")
        old_lines.append(f"```\n{case['good_examples'][0]['code']}\n```")
        old_lines.append("\n为什么这是个问题:")
        old_lines.append("  恶意用户可注入任意SQL语句")
        old_lines.append("\n不修复的后果:")
        old_lines.append("  数据泄露、数据损坏")
        old_lines.append("\n☐ 是否使用了参数化查询")
        old_lines.append("  提示: 检查所有SQL拼接点")
        old_lines.append("")
        old_format = "\n".join(old_lines)

        print(f"\n结构化: {len(structured)} 字")
        print(f"Markdown: {len(old_format)} 字")
        print(f"压缩: {len(old_format) - len(structured)} 字 ({100 - len(structured) * 100 // len(old_format)}%)")

        assert len(structured) < len(old_format), \
            f"结构化格式({len(structured)}) 应比 Markdown({len(old_format)}) 短"


# ==================== 三种 case_format 模式 ====================

class TestCaseFormatModes:
    """测试三种 case_format 模式: default / compact / minimal"""

    @pytest.fixture
    def full_case(self):
        """包含所有字段的完整案例"""
        return {
            "title": "SQL注入",
            "description": "未对用户输入进行转义导致SQL注入",
            "severity": 9,
            "level": "critical",
            "bad_examples": [
                {"label": "直接拼接", "code": 'query = f"SELECT * FROM users WHERE id = {user_id}"'},
            ],
            "good_examples": [
                {"label": "参数化查询", "code": 'cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))'},
            ],
            "why_it_matters": "恶意用户可注入任意SQL语句",
            "consequences": "数据泄露、数据损坏",
            "check_points": [
                {"question": "是否使用了参数化查询", "hint": "检查所有SQL拼接点"},
            ],
        }

    def test_default_mode_has_all_fields(self, loader, full_case):
        """default 模式保留所有字段"""
        result = loader.format_cases_for_prompt([full_case], case_format="default")
        assert "说明:" in result
        assert "❌" in result
        assert "✅" in result
        assert "原因:" in result
        assert "后果:" in result
        assert "检查:" in result

    def test_compact_mode_removes_why_and_consequences(self, loader, full_case):
        """compact 模式去掉原因和后果"""
        result = loader.format_cases_for_prompt([full_case], case_format="compact")
        assert "说明:" in result
        assert "❌" in result
        assert "✅" in result
        assert "原因:" not in result
        assert "后果:" not in result
        assert "检查:" in result

    def test_compact_mode_shorter_than_default(self, loader, full_case):
        """compact 比 default 短"""
        default = loader.format_cases_for_prompt([full_case], case_format="default")
        compact = loader.format_cases_for_prompt([full_case], case_format="compact")
        assert len(compact) < len(default)

    def test_minimal_mode_removes_most_fields(self, loader, full_case):
        """minimal 模式只保留坏代码和检查点"""
        result = loader.format_cases_for_prompt([full_case], case_format="minimal")
        assert "❌" in result
        assert "检查:" in result
        # 这些不应该出现
        assert "说明:" not in result
        assert "✅" not in result
        assert "原因:" not in result
        assert "后果:" not in result

    def test_minimal_mode_shorter_than_compact(self, loader, full_case):
        """minimal 比 compact 短"""
        compact = loader.format_cases_for_prompt([full_case], case_format="compact")
        minimal = loader.format_cases_for_prompt([full_case], case_format="minimal")
        assert len(minimal) < len(compact)

    def test_invalid_format_falls_back_to_default(self, loader, full_case):
        """非法 case_format 值 → 按 default 处理"""
        result = loader.format_cases_for_prompt([full_case], case_format="invalid")
        # 按 default 处理，保留所有字段
        assert "原因:" in result
        assert "后果:" in result
        assert "✅" in result
