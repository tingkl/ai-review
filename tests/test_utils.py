"""Tests for commit_ai_guardian.utils module

覆盖:
- get_file_language(): 已知扩展名、未知扩展名、无扩展名、大写扩展名
- is_binary_file(): 已知二进制扩展名、普通文本扩展名、含null字节文件、UTF-8中文文件
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from commit_ai_guardian.utils import (
    BINARY_EXTENSIONS,
    EXTENSION_LANGUAGE_MAP,
    get_file_language,
    is_binary_file,
)


# ============================================================
# get_file_language()
# ============================================================


class TestGetFileLanguage:
    """Test get_file_language() function"""

    def test_known_extensions(self):
        """已知扩展名应正确映射到语言"""
        test_cases = [
            ("main.py", "python"),
            ("app.js", "javascript"),
            ("App.tsx", "tsx"),
            ("Main.java", "java"),
            ("server.go", "go"),
            ("lib.rs", "rust"),
            ("main.cpp", "cpp"),
            ("header.h", "c"),
            ("program.cs", "csharp"),
            ("script.rb", "ruby"),
            ("index.php", "php"),
            ("view.swift", "swift"),
            ("App.kt", "kotlin"),
            ("app.groovy", "groovy"),
            ("page.vue", "vue"),
            ("index.html", "html"),
            ("style.css", "css"),
            ("style.scss", "scss"),
            ("config.yaml", "yaml"),
            ("data.yml", "yaml"),
            ("schema.xml", "xml"),
            ("config.toml", "toml"),
            ("settings.ini", "ini"),
            ("Dockerfile.dockerfile", "dockerfile"),
            ("Makefile.makefile", "makefile"),
            ("main.tf", "terraform"),
            ("api.graphql", "graphql"),
            ("service.proto", "protobuf"),
            ("script.sh", "bash"),
            ("script.bash", "bash"),
            ("script.zsh", "zsh"),
            ("main.ps1", "powershell"),
            ("main.hs", "haskell"),
            ("main.erl", "erlang"),
            ("main.ex", "elixir"),
            ("main.exs", "elixir"),
            ("main.fs", "fsharp"),
            ("main.fsx", "fsharp"),
            ("app.dart", "dart"),
            ("analysis.r", "r"),
            ("main.mm", "objective-c"),
            ("main.m", "objective-c"),
            ("main.pl", "perl"),
            ("main.lua", "lua"),
            ("config.vim", "vim"),
            ("main.clj", "clojure"),
            ("main.jl", "julia"),
        ]
        for filename, expected in test_cases:
            result = get_file_language(filename)
            assert result == expected, f"Expected {expected!r} for {filename!r}, got {result!r}"

    def test_unknown_extension(self):
        """未知扩展名应返回 'unknown'"""
        result = get_file_language("data.unknown_ext")
        assert result == "unknown"

    def test_no_extension(self):
        """无扩展名的文件应返回 'unknown'"""
        result = get_file_language("Makefile")
        assert result == "unknown"

    def test_uppercase_extension(self):
        """大写扩展名应被正确识别（转为小写后匹配）"""
        result = get_file_language("MAIN.PY")
        assert result == "python"

    def test_mixed_case_extension(self):
        """混合大小写扩展名应被正确识别"""
        result = get_file_language("App.Js")
        assert result == "javascript"

    def test_path_with_directory(self):
        """带目录路径的文件名应正确提取扩展名"""
        result = get_file_language("/home/user/project/src/main.py")
        assert result == "python"

    def test_path_with_multiple_dots(self):
        """文件名含多个点时，只取最后一部分作为扩展名"""
        result = get_file_language("some.file.name.py")
        assert result == "python"

    def test_dotfile_no_extension(self):
        """.gitignore 这类以点开头的文件名，suffix是空字符串"""
        result = get_file_language(".gitignore")
        assert result == "unknown"


# ============================================================
# is_binary_file()
# ============================================================


class TestIsBinaryFile:
    """Test is_binary_file() function"""

    def test_known_binary_extension_png(self):
        """已知二进制扩展名 .png 应返回 True"""
        result = is_binary_file("image.png")
        assert result is True

    def test_known_binary_extension_jpg(self):
        """已知二进制扩展名 .jpg 应返回 True"""
        result = is_binary_file("photo.jpg")
        assert result is True

    def test_known_binary_extension_pdf(self):
        """已知二进制扩展名 .pdf 应返回 True"""
        result = is_binary_file("document.pdf")
        assert result is True

    def test_known_binary_extension_zip(self):
        """已知二进制扩展名 .zip 应返回 True"""
        result = is_binary_file("archive.zip")
        assert result is True

    def test_known_binary_extension_exe(self):
        """已知二进制扩展名 .exe 应返回 True"""
        result = is_binary_file("program.exe")
        assert result is True

    def test_known_binary_extension_class(self):
        """已知二进制扩展名 .class 应返回 True"""
        result = is_binary_file("Main.class")
        assert result is True

    def test_known_binary_extension_jar(self):
        """已知二进制扩展名 .jar 应返回 True"""
        result = is_binary_file("library.jar")
        assert result is True

    def test_known_binary_extension_uppercase(self):
        """大写二进制扩展名 .PNG 应返回 True"""
        result = is_binary_file("image.PNG")
        assert result is True

    def test_text_extension_py(self):
        """普通文本扩展名 .py 不应被误判为二进制"""
        result = is_binary_file("main.py")
        assert result is False

    def test_text_extension_js(self):
        """普通文本扩展名 .js 不应被误判为二进制"""
        result = is_binary_file("app.js")
        assert result is False

    def test_text_extension_txt(self):
        """普通文本扩展名 .txt 不应被误判为二进制"""
        result = is_binary_file("readme.txt")
        assert result is False

    def test_text_extension_md(self):
        """普通文本扩展名 .md 不应被误判为二进制"""
        result = is_binary_file("README.md")
        assert result is False

    def test_text_extension_json(self):
        """.json 不在 BINARY_EXTENSIONS 中，应返回 False"""
        result = is_binary_file("package.json")
        assert result is False

    def test_text_extension_lock(self):
        """.lock 不在 BINARY_EXTENSIONS 中，应返回 False"""
        result = is_binary_file("package-lock.json")
        assert result is False

    def test_no_extension(self):
        """无扩展名的文件，且不提供 repo_path，应返回 False"""
        result = is_binary_file("Makefile")
        assert result is False

    def test_file_with_null_bytes(self, temp_dir):
        """含 null 字节的文件应被识别为二进制"""
        binary_file = temp_dir / "fake_binary.dat"
        binary_file.write_bytes(b"hello\x00world\x00\x01\x02\x03")
        result = is_binary_file("fake_binary.dat", repo_path=str(temp_dir))
        assert result is True

    def test_utf8_chinese_file_not_binary(self, temp_dir):
        """UTF-8 中文文件（非ASCII比例<30%）不应被误判为二进制"""
        chinese_file = temp_dir / "chinese.txt"
        # ASCII chars: 70+, non-ASCII: ~30 bytes of Chinese UTF-8 (<30%)
        chinese_file.write_text(
            "Hello world, this is a test file with some Chinese text. "
            "The ASCII content dominates the file so it should not be flagged as binary. "
            "Here is a little Chinese: \u4e2d\u6587\n",
            encoding="utf-8",
        )
        result = is_binary_file("chinese.txt", repo_path=str(temp_dir))
        assert result is False

    def test_utf8_japanese_file_not_binary(self, temp_dir):
        """UTF-8 日文文件（非ASCII比例<30%）不应被误判为二进制"""
        japanese_file = temp_dir / "japanese.txt"
        # ASCII chars dominate, only a small amount of Japanese
        japanese_file.write_text(
            "This file contains mostly ASCII text with a small amount of Japanese. "
            "The English content here ensures the non-ASCII ratio stays well below 30%. "
            "Here is some Japanese: \u65e5\u672c\u8a9e\n",
            encoding="utf-8",
        )
        result = is_binary_file("japanese.txt", repo_path=str(temp_dir))
        assert result is False

    def test_utf8_emoji_file_not_binary(self, temp_dir):
        """含少量 emoji 的 UTF-8 文件不应被误判为二进制"""
        emoji_file = temp_dir / "emoji.txt"
        # Lots of ASCII, only a few emoji bytes
        emoji_file.write_text(
            "Hello World! This is a regular text file with plenty of ASCII characters. "
            "The emoji content is minimal compared to all the English text here. "
            "Just one emoji: \U0001f600 and more text to keep ratio low.\n",
            encoding="utf-8",
        )
        result = is_binary_file("emoji.txt", repo_path=str(temp_dir))
        assert result is False

    def test_high_non_text_ratio_binary(self, temp_dir):
        """非文本字节比例超过 30% 应识别为二进制"""
        binary_file = temp_dir / "mostly_binary.dat"
        # 100 bytes 中 40 个是非ASCII（>127），比例 40% > 30%
        content = bytes([65] * 60 + [200] * 40)  # 60 ASCII + 40 non-ASCII
        binary_file.write_bytes(content)
        result = is_binary_file("mostly_binary.dat", repo_path=str(temp_dir))
        assert result is True

    def test_low_non_text_ratio_not_binary(self, temp_dir):
        """非文本字节比例低于 30% 不应识别为二进制"""
        text_file = temp_dir / "mostly_text.dat"
        # 100 bytes 中 10 个是非ASCII（>127），比例 10% < 30%
        content = bytes([65] * 90 + [200] * 10)
        text_file.write_bytes(content)
        result = is_binary_file("mostly_text.dat", repo_path=str(temp_dir))
        assert result is False

    def test_empty_file_not_binary(self, temp_dir):
        """空文件不应被识别为二进制（len(chunk) == 0 不触发比例检查）"""
        empty_file = temp_dir / "empty.txt"
        empty_file.write_bytes(b"")
        result = is_binary_file("empty.txt", repo_path=str(temp_dir))
        assert result is False

    def test_file_not_exist_no_repo_path(self):
        """文件不存在且不提供 repo_path，仅凭扩展名判断"""
        result = is_binary_file("nonexistent.py")
        assert result is False

    def test_file_not_exist_with_repo_path(self, temp_dir):
        """文件不存在但提供 repo_path，应返回 False（OSError 被捕获）"""
        result = is_binary_file("nonexistent.txt", repo_path=str(temp_dir))
        assert result is False

    def test_binary_extension_overrides_content_check(self, temp_dir):
        """二进制扩展名优先，即使文件内容是文本也返回 True"""
        fake_png = temp_dir / "fake.png"
        fake_png.write_text("This is actually a text file with .png extension")
        result = is_binary_file("fake.png", repo_path=str(temp_dir))
        # 扩展名检查优先于内容检查
        assert result is True

    def test_null_at_end_of_chunk(self, temp_dir):
        """null 字节在 chunk 末尾也应被检测到"""
        binary_file = temp_dir / "null_end.dat"
        content = b"A" * 8191 + b"\x00"
        binary_file.write_bytes(content)
        result = is_binary_file("null_end.dat", repo_path=str(temp_dir))
        assert result is True

    def test_null_at_start_of_chunk(self, temp_dir):
        """null 字节在 chunk 开头也应被检测到"""
        binary_file = temp_dir / "null_start.dat"
        content = b"\x00" + b"A" * 8191
        binary_file.write_bytes(content)
        result = is_binary_file("null_start.dat", repo_path=str(temp_dir))
        assert result is True

    def test_large_file_reads_only_8192_bytes(self, temp_dir):
        """大文件只读取前 8192 字节检查"""
        large_file = temp_dir / "large_file.dat"
        # 9000 bytes of ASCII text, no null, non_text ratio = 0
        content = b"A" * 9000
        large_file.write_bytes(content)
        result = is_binary_file("large_file.dat", repo_path=str(temp_dir))
        assert result is False


# ============================================================
# Module constants
# ============================================================


class TestModuleConstants:
    """Test module-level constants"""

    def test_extension_language_map_not_empty(self):
        """EXTENSION_LANGUAGE_MAP 不应为空"""
        assert len(EXTENSION_LANGUAGE_MAP) > 0

    def test_binary_extensions_not_empty(self):
        """BINARY_EXTENSIONS 不应为空"""
        assert len(BINARY_EXTENSIONS) > 0

    def test_binary_extensions_are_lowercase(self):
        """BINARY_EXTENSIONS 中的扩展名应为小写"""
        for ext in BINARY_EXTENSIONS:
            assert ext == ext.lower(), f"Extension {ext!r} is not lowercase"

    def test_extension_language_map_keys_have_dot(self):
        """EXTENSION_LANGUAGE_MAP 的键应以 . 开头"""
        for ext in EXTENSION_LANGUAGE_MAP:
            assert ext.startswith("."), f"Extension {ext!r} does not start with '.'"

    def test_extension_language_map_keys_are_lowercase(self):
        """EXTENSION_LANGUAGE_MAP 的键应为小写"""
        for ext in EXTENSION_LANGUAGE_MAP:
            assert ext == ext.lower(), f"Extension key {ext!r} is not lowercase"
