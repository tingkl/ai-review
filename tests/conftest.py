"""共享测试 fixtures

所有测试模块共享的 setup/teardown。
"""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """创建临时目录，测试结束后自动清理"""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def git_repo(temp_dir):
    """创建带 .git/ 的临时仓库目录"""
    git_dir = temp_dir / ".git"
    git_dir.mkdir()
    return temp_dir


@pytest.fixture
def sample_config():
    """返回一个配置完整的 Config 对象"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from commit_ai_guardian.config import Config
    return Config(
        api_key="test-key",
        api_base="https://api.example.com/v1",
        model="gpt-4o",
        language="zh-CN",
        enabled=True,
        severity_threshold="warning",
        diff_mode="full",
        max_file_size=1024,
        cache_ttl="1d",
        timeout=60,
        max_tokens=4096,
    )


@pytest.fixture
def mock_file_diff():
    """返回一个模拟的 FileDiff 对象"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from commit_ai_guardian.diff_collector import FileDiff
    return FileDiff(
        filename="src/main.py",
        status="modified",
        diff_content="@@ -1,3 +1,4 @@\n def hello():\n+    pass\n     return 'world'",
        language="python",
        line_numbers=[2],
    )


@pytest.fixture
def mock_source_file():
    """返回一个模拟的 SourceFile 对象"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from commit_ai_guardian.file_collector import SourceFile
    return SourceFile(
        filename="src/main.py",
        language="python",
        content="def hello():\n    return 'world'\n",
        line_count=2,
        file_size=30,
    )


@pytest.fixture
def mock_ai_response():
    """返回一个模拟的AI完整响应（含<result>标签）"""
    return (
        '<think>审核完成</think>\n'
        '<result>{"summary":"代码质量良好","passed":true,"issues":[]}</result>'
    )


@pytest.fixture
def mock_ai_response_with_issues():
    """返回一个模拟的AI响应（含问题）"""
    return (
        '<think>发现问题</think>\n'
        '<result>'
        '{"summary":"发现1个问题","passed":false,'
        '"issues":['
        '{"severity":"warning","category":"style","line_number":10,'
        '"message":"函数过长","suggestion":"拆分函数","code_snippet":"def long():"}'
        ']}'
        '</result>'
    )


@pytest.fixture
def mock_ai_response_truncated():
    """返回一个被截断的AI响应"""
    return '<result>{"summary":"代码","passed":true,"issues":['


@pytest.fixture
def mock_ai_response_no_result_tag():
    """返回没有<result>标签的旧格式响应"""
    return '{"summary":"旧格式","passed":true,"issues":[]}'


@pytest.fixture
def mock_ai_response_with_tool_call():
    """返回被tool_call包裹的响应"""
    return (
        '<minimax:tool_call>'
        '<result>{"summary":"代码良好","passed":true,"issues":[]}</result>'
        '</minimax:tool_call>'
    )
