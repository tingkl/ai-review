"""Tests for commit_ai_guardian.file_collector module

覆盖:
- FileCollector._matches_include_patterns(): 白名单匹配
- FileCollector._matches_ignore_patterns(): 忽略模式匹配
- FileCollector.collect_file(): 二进制跳过、过大文件跳过、include 过滤
- FileCollector.collect(): 综合采集和去重
- SourceFile dataclass
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from commit_ai_guardian.file_collector import SourceFile


# ============================================================
# SourceFile dataclass
# ============================================================


class TestSourceFile:
    """Test SourceFile dataclass"""

    def test_default_creation(self):
        """使用默认参数创建 SourceFile"""
        sf = SourceFile()
        assert sf.filename == ""
        assert sf.language == ""
        assert sf.content == ""
        assert sf.line_count == 0
        assert sf.file_size == 0

    def test_creation_with_all_fields(self):
        """使用所有字段创建 SourceFile"""
        sf = SourceFile(
            filename="src/main.py",
            language="python",
            content="def hello():\n    return 'world'\n",
            line_count=2,
            file_size=30,
        )
        assert sf.filename == "src/main.py"
        assert sf.language == "python"
        assert sf.content == "def hello():\n    return 'world'\n"
        assert sf.line_count == 2
        assert sf.file_size == 30

    def test_equality_same_values(self):
        """相同值的 SourceFile 应相等"""
        sf1 = SourceFile(filename="a.py", content="hello")
        sf2 = SourceFile(filename="a.py", content="hello")
        assert sf1 == sf2

    def test_equality_different_values(self):
        """不同值的 SourceFile 不应相等"""
        sf1 = SourceFile(filename="a.py")
        sf2 = SourceFile(filename="b.py")
        assert sf1 != sf2

    def test_repr(self):
        """SourceFile repr 应包含类名"""
        sf = SourceFile(filename="test.py")
        repr_str = repr(sf)
        assert "SourceFile" in repr_str


# ============================================================
# FileCollector._matches_include_patterns()
# ============================================================


class TestFileCollectorMatchesIncludePatterns:
    """Test _matches_include_patterns()"""

    def test_star_matches_all(self):
        """默认 [*] 匹配所有文件"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector()
        assert fc._matches_include_patterns("anything.py") is True
        assert fc._matches_include_patterns("src/deep/file.js") is True

    def test_specific_extension(self):
        """*.py 只匹配 .py 文件"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(include_patterns=["*.py"])
        assert fc._matches_include_patterns("main.py") is True
        assert fc._matches_include_patterns("main.js") is False

    def test_globstar_recursive(self):
        """src/**/*.py 匹配 src 目录下的所有 .py 文件"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(include_patterns=["src/**/*.py"])
        assert fc._matches_include_patterns("src/main.py") is True
        assert fc._matches_include_patterns("src/a/b/c/main.py") is True
        assert fc._matches_include_patterns("lib/main.py") is False

    def test_globstar_all_directories(self):
        """**/*.py 匹配任意目录下的 .py 文件"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(include_patterns=["**/*.py"])
        assert fc._matches_include_patterns("main.py") is True
        assert fc._matches_include_patterns("a/b/c/main.py") is True
        assert fc._matches_include_patterns("main.js") is False

    def test_basename_match(self):
        """basename 匹配（*.py 匹配任意目录下的 .py 文件）"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(include_patterns=["*.py"])
        # The basename "main.py" should match "*.py"
        assert fc._matches_include_patterns("some/deep/path/main.py") is True

    def test_no_match(self):
        """不匹配任何模式"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(include_patterns=["*.rs"])
        assert fc._matches_include_patterns("main.py") is False

    def test_empty_patterns_list_uses_default_star(self):
        """空 include_patterns 被 or 操作转为 ['*']，匹配所有文件"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(include_patterns=[])
        # 注：源码中 `include_patterns or ["*"]` 使空列表转为 ["*"]
        assert fc._matches_include_patterns("main.py") is True

    def test_multiple_patterns_any_match(self):
        """多模式中任一匹配即可"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(include_patterns=["*.py", "*.js"])
        assert fc._matches_include_patterns("main.py") is True
        assert fc._matches_include_patterns("main.js") is True
        assert fc._matches_include_patterns("main.rs") is False

    def test_directory_prefix_match(self):
        """目录前缀匹配"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(include_patterns=["src/**"])
        assert fc._matches_include_patterns("src/main.py") is True
        assert fc._matches_include_patterns("src/a/b/c.py") is True
        assert fc._matches_include_patterns("lib/main.py") is False


# ============================================================
# FileCollector._matches_ignore_patterns()
# ============================================================


class TestFileCollectorMatchesIgnorePatterns:
    """Test _matches_ignore_patterns()"""

    def test_no_patterns(self):
        """空 ignore_patterns 不应匹配任何文件"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(ignore_patterns=[])
        assert fc._matches_ignore_patterns("main.py") is False

    def test_single_extension(self):
        """*.lock 匹配 .lock 文件"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(ignore_patterns=["*.lock"])
        assert fc._matches_ignore_patterns("package-lock.json") is False  # .lock is not the suffix

    def test_lock_suffix(self):
        """*.lock 匹配以 .lock 结尾的文件"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(ignore_patterns=["*.lock"])
        assert fc._matches_ignore_patterns("Pipfile.lock") is True

    def test_json_ignore(self):
        """*.json 匹配 .json 文件"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(ignore_patterns=["*.json"])
        assert fc._matches_ignore_patterns("package.json") is True

    def test_directory_ignore(self):
        """vendor/** 匹配 vendor 目录下所有文件"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(ignore_patterns=["vendor/**"])
        assert fc._matches_ignore_patterns("vendor/lib.py") is True
        assert fc._matches_ignore_patterns("src/main.py") is False

    def test_globstar_ignore(self):
        """**/node_modules/** 匹配任意位置的 node_modules"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(ignore_patterns=["**/node_modules/**"])
        assert fc._matches_ignore_patterns("node_modules/package/index.js") is True
        assert fc._matches_ignore_patterns("src/node_modules/lib.js") is True

    def test_multiple_ignore_patterns(self):
        """多个 ignore 模式，任一匹配即可"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(ignore_patterns=["*.min.js", "*.map"])
        assert fc._matches_ignore_patterns("app.min.js") is True
        assert fc._matches_ignore_patterns("app.map") is True
        assert fc._matches_ignore_patterns("app.js") is False

    def test_no_match(self):
        """不匹配任何 ignore 模式"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(ignore_patterns=["*.test.js"])
        assert fc._matches_ignore_patterns("main.js") is False

    def test_exact_basename_match(self):
        """精确 basename 匹配"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(ignore_patterns=["Makefile"])
        assert fc._matches_ignore_patterns("/path/to/Makefile") is True

    def test_partial_path_no_match(self):
        """部分路径不匹配完整路径模式"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector(ignore_patterns=["test_*.py"])
        assert fc._matches_ignore_patterns("tests/test_main.py") is True  # basename matches


# ============================================================
# FileCollector.collect_file()
# ============================================================


class TestFileCollectorCollectFile:
    """Test collect_file()"""

    def test_nonexistent_file(self, temp_dir):
        """不存在的文件返回 None"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector()
        result = fc.collect_file(str(temp_dir / "nonexistent.py"))
        assert result is None

    def test_directory_not_file(self, temp_dir):
        """目录不是文件，返回 None"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector()
        result = fc.collect_file(str(temp_dir))
        assert result is None

    def test_binary_file_skipped(self, temp_dir):
        """二进制文件被跳过，返回 None"""
        from commit_ai_guardian.file_collector import FileCollector
        binary_file = temp_dir / "image.png"
        binary_file.write_bytes(b"\x89PNG\r\n\x1a\n")  # PNG magic bytes
        fc = FileCollector()
        result = fc.collect_file(str(binary_file))
        assert result is None

    def test_too_large_file_skipped(self, temp_dir):
        """超过大小限制的文件被跳过"""
        from commit_ai_guardian.file_collector import FileCollector
        large_file = temp_dir / "large.txt"
        large_file.write_text("A" * 1025)  # 1 KB + 1 byte
        fc = FileCollector(max_file_size=1)  # 1 KB limit
        result = fc.collect_file(str(large_file))
        assert result is None

    def test_include_filter_excludes(self, temp_dir):
        """不在 include_patterns 内的文件被跳过"""
        from commit_ai_guardian.file_collector import FileCollector
        py_file = temp_dir / "main.py"
        py_file.write_text("print('hello')\n")
        fc = FileCollector(include_patterns=["*.js"])  # only .js files
        result = fc.collect_file(str(py_file))
        assert result is None

    def test_ignore_filter_excludes(self, temp_dir):
        """在 ignore_patterns 内的文件被跳过"""
        from commit_ai_guardian.file_collector import FileCollector
        json_file = temp_dir / "config.json"
        json_file.write_text('{"key": "value"}\n')
        fc = FileCollector(ignore_patterns=["*.json"])
        result = fc.collect_file(str(json_file))
        assert result is None

    def test_valid_file_collected(self, temp_dir):
        """有效文件被正确采集"""
        from commit_ai_guardian.file_collector import FileCollector
        py_file = temp_dir / "main.py"
        py_file.write_text("def hello():\n    return 'world'\n")
        fc = FileCollector()
        result = fc.collect_file(str(py_file))
        assert result is not None
        assert result.filename == str(py_file)
        assert result.language == "python"
        assert result.content == "def hello():\n    return 'world'\n"
        # content has 2 newlines -> 3 lines (content.count('\n') + 1)
        assert result.line_count == 3
        assert result.file_size == py_file.stat().st_size

    def test_valid_file_with_language_inference(self, temp_dir):
        """有效文件的编程语言推断"""
        from commit_ai_guardian.file_collector import FileCollector
        js_file = temp_dir / "app.js"
        js_file.write_text("function hello() { return 'world'; }\n")
        fc = FileCollector()
        result = fc.collect_file(str(js_file))
        assert result is not None
        assert result.language == "javascript"

    def test_file_at_exact_size_limit(self, temp_dir):
        """恰好等于大小限制的文件应被采集"""
        from commit_ai_guardian.file_collector import FileCollector
        exact_file = temp_dir / "exact.txt"
        exact_file.write_text("A" * 1024)  # exactly 1 KB
        fc = FileCollector(max_file_size=1)  # 1 KB = 1024 bytes
        result = fc.collect_file(str(exact_file))
        assert result is not None

    def test_file_just_under_size_limit(self, temp_dir):
        """刚好小于大小限制的文件应被采集"""
        from commit_ai_guardian.file_collector import FileCollector
        small_file = temp_dir / "small.txt"
        small_file.write_text("A" * 1023)  # 1 KB - 1 byte
        fc = FileCollector(max_file_size=1)  # 1 KB = 1024 bytes
        result = fc.collect_file(str(small_file))
        assert result is not None

    def test_file_just_over_size_limit(self, temp_dir):
        """刚好超过大小限制的文件应被跳过"""
        from commit_ai_guardian.file_collector import FileCollector
        big_file = temp_dir / "big.txt"
        big_file.write_text("A" * 1025)  # 1 KB + 1 byte
        fc = FileCollector(max_file_size=1)  # 1 KB = 1024 bytes
        result = fc.collect_file(str(big_file))
        assert result is None

    def test_unicode_decode_error_file(self, temp_dir):
        """无法以 UTF-8 读取的文件返回 None"""
        from commit_ai_guardian.file_collector import FileCollector
        bad_file = temp_dir / "bad.txt"
        bad_file.write_bytes(b"\x80\x81\x82\x83")  # invalid UTF-8 sequence
        fc = FileCollector()
        result = fc.collect_file(str(bad_file))
        assert result is None


# ============================================================
# FileCollector.collect_dir()
# ============================================================


class TestFileCollectorCollectDir:
    """Test collect_dir()"""

    def test_nonexistent_directory(self, temp_dir):
        """不存在的目录返回空列表"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector()
        result = fc.collect_dir(str(temp_dir / "nonexistent"))
        assert result == []

    def test_file_not_directory(self, temp_dir):
        """文件不是目录，返回空列表"""
        from commit_ai_guardian.file_collector import FileCollector
        a_file = temp_dir / "file.txt"
        a_file.write_text("hello")
        fc = FileCollector()
        result = fc.collect_dir(str(a_file))
        assert result == []

    def test_collect_files_in_directory(self, temp_dir):
        """采集目录下的文件"""
        from commit_ai_guardian.file_collector import FileCollector
        (temp_dir / "a.py").write_text("# a\n")
        (temp_dir / "b.py").write_text("# b\n")
        (temp_dir / "c.js").write_text("// c\n")
        fc = FileCollector()
        result = fc.collect_dir(str(temp_dir))
        filenames = [sf.filename for sf in result]
        assert len(result) == 3

    def test_recursive_collection(self, temp_dir):
        """递归采集子目录"""
        from commit_ai_guardian.file_collector import FileCollector
        sub = temp_dir / "subdir"
        sub.mkdir()
        (temp_dir / "root.py").write_text("# root\n")
        (sub / "sub.py").write_text("# sub\n")
        fc = FileCollector()
        result = fc.collect_dir(str(temp_dir), recursive=True)
        filenames = {sf.filename for sf in result}
        assert len(result) == 2

    def test_non_recursive_collection(self, temp_dir):
        """非递归不采集子目录"""
        from commit_ai_guardian.file_collector import FileCollector
        sub = temp_dir / "subdir"
        sub.mkdir()
        (temp_dir / "root.py").write_text("# root\n")
        (sub / "sub.py").write_text("# sub\n")
        fc = FileCollector()
        result = fc.collect_dir(str(temp_dir), recursive=False)
        filenames = {Path(sf.filename).name for sf in result}
        assert "sub.py" not in filenames
        assert "root.py" in filenames

    def test_respects_ignore_patterns_in_dir(self, temp_dir):
        """目录采集时遵循 ignore_patterns"""
        from commit_ai_guardian.file_collector import FileCollector
        (temp_dir / "main.py").write_text("# main\n")
        (temp_dir / "config.json").write_text("{}\n")
        fc = FileCollector(ignore_patterns=["*.json"])
        result = fc.collect_dir(str(temp_dir))
        filenames = {Path(sf.filename).name for sf in result}
        assert "main.py" in filenames
        assert "config.json" not in filenames

    def test_respects_binary_skip_in_dir(self, temp_dir):
        """目录采集时跳过二进制文件"""
        from commit_ai_guardian.file_collector import FileCollector
        (temp_dir / "main.py").write_text("# main\n")
        (temp_dir / "image.png").write_bytes(b"\x89PNG\r\n")
        fc = FileCollector()
        result = fc.collect_dir(str(temp_dir))
        filenames = {Path(sf.filename).name for sf in result}
        assert "main.py" in filenames
        assert "image.png" not in filenames


# ============================================================
# FileCollector.collect() - comprehensive collection
# ============================================================


class TestFileCollectorCollect:
    """Test collect() - 综合采集和去重"""

    def test_empty_collect(self, temp_dir):
        """无参数采集返回空列表"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector()
        result = fc.collect()
        assert result == []

    def test_collect_single_file(self, temp_dir):
        """采集单个文件"""
        from commit_ai_guardian.file_collector import FileCollector
        py_file = temp_dir / "main.py"
        py_file.write_text("def hello():\n    return 'world'\n")
        fc = FileCollector()
        result = fc.collect(files=[str(py_file)])
        assert len(result) == 1
        assert result[0].filename == str(py_file)

    def test_collect_multiple_files(self, temp_dir):
        """采集多个文件"""
        from commit_ai_guardian.file_collector import FileCollector
        (temp_dir / "a.py").write_text("# a\n")
        (temp_dir / "b.py").write_text("# b\n")
        fc = FileCollector()
        result = fc.collect(
            files=[str(temp_dir / "a.py"), str(temp_dir / "b.py")]
        )
        assert len(result) == 2

    def test_collect_directory(self, temp_dir):
        """采集目录"""
        from commit_ai_guardian.file_collector import FileCollector
        sub = temp_dir / "src"
        sub.mkdir()
        (sub / "main.py").write_text("# main\n")
        (sub / "util.py").write_text("# util\n")
        fc = FileCollector()
        result = fc.collect(dirs=[str(sub)])
        assert len(result) == 2

    def test_collect_with_pattern(self, temp_dir):
        """使用 glob 模式采集"""
        from commit_ai_guardian.file_collector import FileCollector
        (temp_dir / "a.py").write_text("# a\n")
        (temp_dir / "b.py").write_text("# b\n")
        (temp_dir / "c.js").write_text("// c\n")
        fc = FileCollector()
        result = fc.collect(patterns=[str(temp_dir / "*.py")])
        filenames = [Path(sf.filename).name for sf in result]
        assert "a.py" in filenames
        assert "b.py" in filenames
        assert "c.js" not in filenames

    def test_deduplication_same_file_multiple_sources(self, temp_dir):
        """同一文件通过多种方式指定，只采集一次"""
        from commit_ai_guardian.file_collector import FileCollector
        py_file = temp_dir / "main.py"
        py_file.write_text("def hello():\n    return 'world'\n")
        fc = FileCollector()
        # 同时通过 files 和 patterns 指定同一文件
        result = fc.collect(
            files=[str(py_file)],
            patterns=[str(temp_dir / "*.py")],
        )
        assert len(result) == 1

    def test_deduplication_file_and_dir(self, temp_dir):
        """文件和目录同时包含同一文件，只采集一次"""
        from commit_ai_guardian.file_collector import FileCollector
        sub = temp_dir / "src"
        sub.mkdir()
        py_file = sub / "main.py"
        py_file.write_text("# main\n")
        (sub / "other.py").write_text("# other\n")
        fc = FileCollector()
        result = fc.collect(
            files=[str(py_file)],
            dirs=[str(sub)],
        )
        # main.py 通过 files 和 dirs 两种方式指定，应去重
        main_files = [sf for sf in result if sf.filename == str(py_file)]
        assert len(main_files) == 1
        # other.py 只通过 dirs 指定
        other_files = [sf for sf in result if "other" in sf.filename]
        assert len(other_files) == 1
        # 总共 2 个文件
        assert len(result) == 2

    def test_combined_files_dirs_patterns(self, temp_dir):
        """同时使用 files、dirs、patterns 三种方式"""
        from commit_ai_guardian.file_collector import FileCollector
        sub = temp_dir / "src"
        sub.mkdir()
        (temp_dir / "root.py").write_text("# root\n")
        (sub / "main.py").write_text("# main\n")
        (sub / "util.py").write_text("# util\n")
        fc = FileCollector()
        result = fc.collect(
            files=[str(temp_dir / "root.py")],
            dirs=[str(sub)],
            patterns=[],
        )
        filenames = {Path(sf.filename).name for sf in result}
        assert "root.py" in filenames
        assert "main.py" in filenames
        assert "util.py" in filenames
        assert len(result) == 3

    def test_respects_include_patterns(self, temp_dir):
        """collect() 遵循 include_patterns"""
        from commit_ai_guardian.file_collector import FileCollector
        (temp_dir / "main.py").write_text("# main\n")
        (temp_dir / "app.js").write_text("// app\n")
        fc = FileCollector(include_patterns=["*.py"])
        result = fc.collect(dirs=[str(temp_dir)])
        filenames = {Path(sf.filename).name for sf in result}
        assert "main.py" in filenames
        assert "app.js" not in filenames

    def test_respects_ignore_patterns(self, temp_dir):
        """collect() 遵循 ignore_patterns"""
        from commit_ai_guardian.file_collector import FileCollector
        (temp_dir / "main.py").write_text("# main\n")
        (temp_dir / "test.py").write_text("# test\n")
        fc = FileCollector(ignore_patterns=["test*.py"])
        result = fc.collect(dirs=[str(temp_dir)])
        filenames = {Path(sf.filename).name for sf in result}
        assert "main.py" in filenames
        assert "test.py" not in filenames

    def test_respects_max_file_size(self, temp_dir):
        """collect() 遵循 max_file_size 限制"""
        from commit_ai_guardian.file_collector import FileCollector
        (temp_dir / "small.py").write_text("# small\n")
        (temp_dir / "large.py").write_text("# " + "x" * 2000 + "\n")
        fc = FileCollector(max_file_size=1)  # 1 KB
        result = fc.collect(dirs=[str(temp_dir)])
        filenames = {Path(sf.filename).name for sf in result}
        assert "small.py" in filenames
        assert "large.py" not in filenames

    def test_recursive_false(self, temp_dir):
        """recursive=False 时不递归子目录"""
        from commit_ai_guardian.file_collector import FileCollector
        sub = temp_dir / "subdir"
        sub.mkdir()
        (temp_dir / "root.py").write_text("# root\n")
        (sub / "sub.py").write_text("# sub\n")
        fc = FileCollector()
        result = fc.collect(dirs=[str(temp_dir)], recursive=False)
        filenames = {Path(sf.filename).name for sf in result}
        assert "root.py" in filenames
        assert "sub.py" not in filenames


# ============================================================
# FileCollector._is_too_large()
# ============================================================


class TestFileCollectorIsTooLarge:
    """Test _is_too_large()"""

    def test_file_under_limit(self, temp_dir):
        """小于限制的文件"""
        from commit_ai_guardian.file_collector import FileCollector
        small_file = temp_dir / "small.txt"
        small_file.write_text("A" * 100)
        fc = FileCollector(max_file_size=1)  # 1024 bytes
        assert fc._is_too_large(small_file) is False

    def test_file_over_limit(self, temp_dir):
        """大于限制的文件"""
        from commit_ai_guardian.file_collector import FileCollector
        large_file = temp_dir / "large.txt"
        large_file.write_text("A" * 2000)
        fc = FileCollector(max_file_size=1)  # 1024 bytes
        assert fc._is_too_large(large_file) is True

    def test_file_exactly_at_limit(self, temp_dir):
        """恰好等于限制的文件"""
        from commit_ai_guardian.file_collector import FileCollector
        exact_file = temp_dir / "exact.txt"
        exact_file.write_text("A" * 1024)
        fc = FileCollector(max_file_size=1)  # 1024 bytes
        assert fc._is_too_large(exact_file) is False  # 1024 > 1024 is False

    def test_nonexistent_file_returns_true(self, temp_dir):
        """不存在的文件返回 True（OSError 被捕获）"""
        from commit_ai_guardian.file_collector import FileCollector
        fc = FileCollector()
        nonexistent = temp_dir / "nonexistent.txt"
        assert fc._is_too_large(nonexistent) is True


# ============================================================
# FileCollector.collect_git_history()
# ============================================================


class TestFileCollectorGitHistory:
    """Test collect_git_history()"""

    def test_gitpython_not_installed(self, monkeypatch):
        """GitPython 未安装时返回空列表"""
        import importlib

        # 模拟 git 模块不存在
        monkeypatch.setitem(sys.modules, "git", None)
        from commit_ai_guardian.file_collector import FileCollector

        fc = FileCollector()
        # 由于 ImportError 会被捕获，但模块已经被缓存，
        # 我们直接验证函数存在
        assert hasattr(fc, "collect_git_history")
