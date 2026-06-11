"""JSON 修复 AI 专项测试

覆盖:
1. load_json_fix_system_message() — 加载 system message 模板
2. load_json_fix_template() — 加载 user prompt 模板
3. _write_json_fix_log() — 写入 {md5}.json.log
4. _fix_json_with_ai() — AI 修复 JSON（mock）
5. 模板文件完整性
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commit_ai_guardian.config import Config
from commit_ai_guardian.prompt_loader import (
    DEFAULT_JSON_FIX_SYSTEM_MESSAGE,
    DEFAULT_JSON_FIX_TEMPLATE,
    PromptLoader,
)


# 延迟导入 AIEngine（避免模块级 openai 依赖问题）
from commit_ai_guardian.ai_engine import AIEngine


@pytest.fixture
def engine(tmp_path):
    """创建带临时仓库的 AIEngine（绕过 __init__ 避免 openai 依赖）"""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".ai-review").mkdir()
    (repo / ".ai-review" / "logs").mkdir(parents=True)
    with patch.object(AIEngine, "__init__", lambda self, **kw: None):
        eng = AIEngine.__new__(AIEngine)
        eng.config = Config(api_key="test", model="gpt-4o-mini")
        eng.repo_path = str(repo)
        eng._logs_dir = repo / ".ai-review" / "logs"
        eng._logs_dir.mkdir(parents=True, exist_ok=True)
        eng.client = None
        eng.prompt_loader = PromptLoader(repo_path=str(repo))
        yield eng


# ============================================================
# PromptLoader JSON 修复模板加载
# ============================================================

class TestJsonFixSystemMessage:
    """load_json_fix_system_message()"""

    def test_not_empty(self):
        assert len(DEFAULT_JSON_FIX_SYSTEM_MESSAGE) > 0

    def test_contains_json_expert(self):
        assert "JSON" in DEFAULT_JSON_FIX_SYSTEM_MESSAGE

    def test_contains_no_think_instruction(self):
        """包含禁止 <think> 的指令"""
        assert "不要" in DEFAULT_JSON_FIX_SYSTEM_MESSAGE
        assert "<think>" in DEFAULT_JSON_FIX_SYSTEM_MESSAGE

    def test_load_default(self):
        loader = PromptLoader()
        msg = loader.load_json_fix_system_message()
        assert msg == DEFAULT_JSON_FIX_SYSTEM_MESSAGE


class TestJsonFixTemplate:
    """load_json_fix_template()"""

    def test_not_empty(self):
        assert len(DEFAULT_JSON_FIX_TEMPLATE) > 0

    def test_contains_filename_placeholder(self):
        assert "{{filename}}" in DEFAULT_JSON_FIX_TEMPLATE

    def test_contains_broken_json_placeholder(self):
        assert "{{broken_json}}" in DEFAULT_JSON_FIX_TEMPLATE

    def test_contains_fix_requirements(self):
        assert "修复" in DEFAULT_JSON_FIX_TEMPLATE

    def test_load_default(self):
        loader = PromptLoader()
        tmpl = loader.load_json_fix_template()
        assert tmpl == DEFAULT_JSON_FIX_TEMPLATE

    def test_render_with_variables(self):
        result = PromptLoader.render(
            DEFAULT_JSON_FIX_TEMPLATE,
            filename="src/main.py",
            broken_json='{"broken": true}',
        )
        assert "src/main.py" in result
        assert '{{filename}}' not in result
        assert "{\"broken\": true}" in result
        assert '{{broken_json}}' not in result


# ============================================================
# _write_json_fix_log
# ============================================================

class TestWriteJsonFixLog:
    """_write_json_fix_log() — 写入 {md5}.json.log"""

    def test_creates_json_log_file(self, engine):
        engine._write_json_fix_log("src/main.py", "abc1234",
                                    "system msg", "user msg", "ai response")
        log_file = Path(engine.repo_path) / ".ai-review" / "logs" / "abc1234.json.log"
        assert log_file.exists()

    def test_contains_system_message_section(self, engine):
        engine._write_json_fix_log("a.py", "def5678",
                                    "you are json fixer", "fix this", '{"fixed":true}')
        log_file = Path(engine.repo_path) / ".ai-review" / "logs" / "def5678.json.log"
        content = log_file.read_text()
        assert "--- SYSTEM MESSAGE ---" in content
        assert "you are json fixer" in content

    def test_contains_user_message_section(self, engine):
        engine._write_json_fix_log("a.py", "def5678",
                                    "system", "fix this json", '{"fixed":true}')
        log_file = Path(engine.repo_path) / ".ai-review" / "logs" / "def5678.json.log"
        content = log_file.read_text()
        assert "--- USER MESSAGE ---" in content
        assert "fix this json" in content

    def test_contains_ai_response_section(self, engine):
        engine._write_json_fix_log("a.py", "def5678",
                                    "system", "user", '{"fixed":true}')
        log_file = Path(engine.repo_path) / ".ai-review" / "logs" / "def5678.json.log"
        content = log_file.read_text()
        assert "--- AI RESPONSE ---" in content
        assert '{"fixed":true}' in content

    def test_no_log_without_cache_md5(self, engine):
        """不传 cache_md5 时不写日志"""
        engine._write_json_fix_log("a.py", "",
                                    "system", "user", "response")
        log_dir = Path(engine.repo_path) / ".ai-review" / "logs"
        json_logs = list(log_dir.glob("*.json.log"))
        assert len(json_logs) == 0

    def test_filename_uses_md5_prefix(self, engine):
        engine._write_json_fix_log("src/main.py", "abc1234",
                                    "s", "u", "r")
        log_dir = Path(engine.repo_path) / ".ai-review" / "logs"
        files = list(log_dir.glob("*.json.log"))
        assert len(files) == 1
        assert files[0].name.startswith("abc1234")


# ============================================================
# _fix_json_with_ai (mock)
# ============================================================

class TestFixJsonWithAi:
    """_fix_json_with_ai() — AI 修复 JSON"""

    def test_no_client_returns_none(self, engine):
        """client 为 None 时返回 None"""
        engine.client = None
        result = engine._fix_json_with_ai('{"bad": json}', "a.py")
        assert result is None

    def test_successful_fix(self, engine):
        """mock 成功修复"""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '{"fixed": true}'
        mock_client.chat.completions.create.return_value = mock_resp
        engine.client = mock_client

        result = engine._fix_json_with_ai('{"bad" json}', "a.py", cache_md5="abc1234")

        assert result == '{"fixed": true}'
        # 验证调用了 API
        assert mock_client.chat.completions.create.called

    def test_api_error_returns_none(self, engine):
        """API 异常时返回 None"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("API Error")
        engine.client = mock_client

        result = engine._fix_json_with_ai('{"bad": json}', "a.py")
        assert result is None

    def test_writes_json_log_on_success(self, engine):
        """成功时写入 .json.log"""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '{"ok": true}'
        mock_client.chat.completions.create.return_value = mock_resp
        engine.client = mock_client

        engine._fix_json_with_ai('{"bad"}', "a.py", cache_md5="xyz7890")

        log_file = Path(engine.repo_path) / ".ai-review" / "logs" / "xyz7890.json.log"
        assert log_file.exists()

    def test_truncates_long_json(self, engine):
        """超长 JSON 截断到 6000 字符"""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '{"fixed": true}'
        mock_client.chat.completions.create.return_value = mock_resp
        engine.client = mock_client

        long_json = '{"key": "' + "x" * 10000 + '"}'
        engine._fix_json_with_ai(long_json, "a.py", cache_md5="abc1234")

        # 验证调用时的 prompt 包含截断标记
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs['messages']
        user_msg = messages[1]['content']
        assert "...（已截断）" in user_msg

    def test_uses_system_and_user_messages(self, engine):
        """验证 messages 包含 system + user"""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = '{"ok": true}'
        mock_client.chat.completions.create.return_value = mock_resp
        engine.client = mock_client

        engine._fix_json_with_ai('{"bad"}', "a.py")

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs['messages']
        assert len(messages) == 2
        assert messages[0]['role'] == 'system'
        assert messages[1]['role'] == 'user'


# ============================================================
# 模板文件完整性
# ============================================================

class TestJsonFixTemplateFiles:
    """get_default_template_files() 包含 JSON 修复模板"""

    def test_contains_system_message_json_fix(self):
        files = PromptLoader.get_default_template_files()
        assert "system_message_json_fix.txt" in files

    def test_contains_json_fix(self):
        files = PromptLoader.get_default_template_files()
        assert "json_fix.md" in files

    def test_total_five_templates(self):
        files = PromptLoader.get_default_template_files()
        assert len(files) == 5

    def test_system_message_not_empty(self):
        files = PromptLoader.get_default_template_files()
        assert len(files["system_message_json_fix.txt"]) > 0

    def test_json_fix_not_empty(self):
        files = PromptLoader.get_default_template_files()
        assert len(files["json_fix.md"]) > 0
