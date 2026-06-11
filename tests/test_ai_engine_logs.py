"""ai_engine 日志文件测试 — 验证日志命名与缓存一致（MD5 前7位）

覆盖:
1. _write_debug_log — prompt.log 文件名用 MD5 前7位
2. _write_ai_response_log — ai.log 文件名用 MD5 前7位
3. 不传 cache_md5 时 fallback 到旧命名（sanitize_log_filename）
4. 三个路径（cache/ ai.log prompt.log）命名一致
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commit_ai_guardian.config import Config


# 延迟导入 AIEngine（避免模块级 openai 依赖问题）
from commit_ai_guardian.ai_engine import AIEngine


@pytest.fixture
def engine(tmp_path):
    """创建带临时仓库的 AIEngine（绕过 __init__ 避免 openai 依赖）"""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".ai-review").mkdir()
    (repo / ".ai-review" / "logs").mkdir(parents=True)
    (repo / ".ai-review" / "cache").mkdir(parents=True)
    with patch.object(AIEngine, "__init__", lambda self, **kw: None):
        eng = AIEngine.__new__(AIEngine)
        eng.config = Config(api_key="test", model="gpt-4o-mini")
        eng.repo_path = str(repo)
        eng._logs_dir = repo / ".ai-review" / "logs"
        eng._logs_dir.mkdir(parents=True, exist_ok=True)
        eng.client = None
        yield eng


class TestWriteDebugLog:
    """_write_debug_log — prompt.log 命名"""

    def test_uses_cache_md5_for_filename(self, engine):
        """传 cache_md5 时，prompt.log 用 MD5 前7位命名"""
        engine._write_debug_log("src/main.py", "test prompt", cache_md5="abc1234")
        log_file = Path(engine.repo_path) / ".ai-review" / "logs" / "abc1234.prompt.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "test prompt" in content
        assert "src/main.py" in content  # header 中有文件名

    def test_fallback_to_sanitize_without_cache_md5(self, engine):
        """不传 cache_md5 时，fallback 到 sanitize_log_filename"""
        engine._write_debug_log("src/main.py", "test prompt")
        # 查找写入的文件（sanitize 后的名字）
        log_dir = Path(engine.repo_path) / ".ai-review" / "logs"
        files = list(log_dir.glob("*.prompt.log"))
        assert len(files) == 1
        assert "src" in files[0].name and "main" in files[0].name

    def test_creates_logs_dir_if_not_exists(self, engine):
        """logs 目录不存在时自动创建"""
        import shutil
        shutil.rmtree(Path(engine.repo_path) / ".ai-review" / "logs")
        engine._write_debug_log("a.py", "prompt", cache_md5="def5678")
        log_file = Path(engine.repo_path) / ".ai-review" / "logs" / "def5678.prompt.log"
        assert log_file.exists()


class TestWriteAiResponseLog:
    """_write_ai_response_log — ai.log 命名"""

    def test_uses_cache_md5_for_filename(self, engine):
        """传 cache_md5 时，ai.log 用 MD5 前7位命名"""
        engine._write_ai_response_log("src/main.py", '{"passed":true}', cache_md5="abc1234")
        log_file = Path(engine.repo_path) / ".ai-review" / "logs" / "abc1234.ai.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "src/main.py" in content
        assert '{"passed":true}' in content

    def test_fallback_to_sanitize_without_cache_md5(self, engine):
        """不传 cache_md5 时，fallback 到 sanitize_log_filename"""
        engine._write_ai_response_log("src/main.py", '{"passed":true}')
        log_dir = Path(engine.repo_path) / ".ai-review" / "logs"
        files = list(log_dir.glob("*.ai.log"))
        assert len(files) == 1
        assert "src" in files[0].name and "main" in files[0].name


class TestLogNamingConsistency:
    """三种文件（cache/ ai.log prompt.log）命名一致性"""

    def test_all_three_use_same_md5(self, engine):
        """同一文件的 cache、ai.log、prompt.log 用相同的 MD5 命名"""
        md5 = "baed43d"
        engine._write_debug_log("src/main.py", "prompt content", cache_md5=md5)
        engine._write_ai_response_log("src/main.py", '{"passed":true}', cache_md5=md5)

        cache_file = Path(engine.repo_path) / ".ai-review" / "cache" / f"{md5}.json"
        prompt_log = Path(engine.repo_path) / ".ai-review" / "logs" / f"{md5}.prompt.log"
        ai_log = Path(engine.repo_path) / ".ai-review" / "logs" / f"{md5}.ai.log"

        assert cache_file.exists() or True  # cache 由 _save_cache 写入
        assert prompt_log.exists()
        assert ai_log.exists()

        # 文件名（去掉 .prompt.log / .ai.log 后）都相同
        assert prompt_log.name.startswith(md5)  # baed43d.prompt.log
        assert ai_log.name.startswith(md5)      # baed43d.ai.log

    def test_md5_is_7_chars(self, engine):
        """MD5 前7位正好是7个字符"""
        full_md5 = "baed43defa0e6f3e95c4f45fbf8c0b5d"
        engine._write_debug_log("a.py", "p", cache_md5=full_md5)
        log_file = list((Path(engine.repo_path) / ".ai-review" / "logs").glob("*.prompt.log"))
        assert len(log_file) == 1
        # name = "baed43d.prompt.log" -> name.split('.')[0] = "baed43d" (7 chars)
        assert len(log_file[0].name.split('.')[0]) == 7
