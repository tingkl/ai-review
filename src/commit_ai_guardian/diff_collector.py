"""Git Diff 采集与解析模块

负责：
- 执行 `git diff --cached` 获取暂存区变更
- 解析 diff 文本，提取文件名、变更类型、行号
- 过滤二进制文件、大文件、忽略模式匹配的文件
- 推断编程语言

输出：FileDiff 对象列表（每个文件一个），供 AI 引擎审核
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

gitpython_available = True
try:
    from git import Repo
    from git.exc import InvalidGitRepositoryError
except ImportError:
    gitpython_available = False
    Repo = None
    InvalidGitRepositoryError = Exception


@dataclass
class FileDiff:
    """单个文件的 Diff 信息（AI 审核引擎 review_file() 的输入）"""
    filename: str = ""       # 文件相对路径，如 "src/auth.py"
    status: str = ""         # 变更类型：added / modified / deleted / renamed
    additions: int = 0       # 新增行数（用于统计展示）
    deletions: int = 0       # 删除行数（用于统计展示）
    diff_content: str = ""   # 完整 diff 文本（含上下文，传给 AI 审核）
    full_content: str = ""   # 文件的完整内容（diff_mode=full 时使用）
    language: str = ""       # 编程语言（从扩展名推断，用于 prompt 中的代码高亮）
    line_numbers: List[int] = field(default_factory=list)  # 变更涉及的行号（AI 指出问题时用）


# 编程语言映射表
EXTENSION_LANGUAGE_MAP = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
    '.jsx': 'jsx', '.tsx': 'tsx', '.java': 'java',
    '.go': 'go', '.rs': 'rust', '.cpp': 'cpp',
    '.cc': 'cpp', '.cxx': 'cpp', '.c': 'c',
    '.h': 'c', '.hpp': 'cpp', '.cs': 'csharp',
    '.rb': 'ruby', '.php': 'php', '.swift': 'swift',
    '.kt': 'kotlin', '.kts': 'kotlin', '.scala': 'scala',
    '.r': 'r', '.m': 'objective-c', '.mm': 'objective-c',
    '.sh': 'bash', '.bash': 'bash', '.zsh': 'zsh',
    '.ps1': 'powershell', '.pl': 'perl', '.lua': 'lua',
    '.vim': 'vim', '.el': 'elisp', '.clj': 'clojure',
    '.hs': 'haskell', '.erl': 'erlang', '.ex': 'elixir',
    '.exs': 'elixir', '.fs': 'fsharp', '.fsx': 'fsharp',
    '.dart': 'dart', '.jl': 'julia', '.groovy': 'groovy',
    '.vue': 'vue', '.svelte': 'svelte', '.html': 'html',
    '.css': 'css', '.scss': 'scss', '.sass': 'sass',
    '.less': 'less', '.sql': 'sql', '.yaml': 'yaml',
    '.yml': 'yaml', '.xml': 'xml', '.toml': 'toml',
    '.ini': 'ini', '.cfg': 'ini', '.conf': 'ini',
    '.dockerfile': 'dockerfile', '.makefile': 'makefile',
    '.cmake': 'cmake', '.graphql': 'graphql', '.proto': 'protobuf',
    '.tf': 'terraform', '.puppet': 'puppet', '.ansible': 'ansible',
}

# 常见二进制文件扩展名
BINARY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg',
    '.mp3', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.wav',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar',
    '.exe', '.dll', '.so', '.dylib', '.bin',
    '.o', '.a', '.lib', '.class', '.jar', '.war', '.ear',
    '.pkl', '.pickle', '.model', '.onnx', '.pb', '.npy', '.npz',
    '.parquet', '.arrow', '.feather', '.orc', '.avro',
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
    '.db', '.sqlite', '.sqlite3',
}


class DiffCollector:
    """Git Diff 采集器
    
    核心方法：get_staged_diffs()
    执行 git diff --cached 并解析结果，返回 FileDiff 列表。
    """
    
    def __init__(self, repo_path: str = "."):
        """初始化
        
        Args:
            repo_path: Git 仓库路径（默认当前目录）
            
        Raises:
            RuntimeError: GitPython 未安装 或 路径不是有效 Git 仓库
        """
        self.repo_path = Path(repo_path).resolve()
        self.repo = None
        
        # 检查 GitPython 是否安装（用户可能忘了 uv sync）
        if not gitpython_available:
            raise RuntimeError("GitPython 未安装，请运行: pip install gitpython")
        
        # 用 GitPython 打开仓库，后续操作都通过这个对象
        try:
            self.repo = Repo(self.repo_path)
        except InvalidGitRepositoryError:
            raise RuntimeError(f"'{repo_path}' 不是有效的 Git 仓库")
    
    def get_staged_diffs(self, include_patterns: Optional[List[str]] = None,
                         ignore_patterns: Optional[List[str]] = None,
                         max_file_size: int = 500) -> List[FileDiff]:
        """获取暂存区（staged）的所有变更
        
        执行流程：
        1. git diff --cached --unified=5 --diff-filter=ACMRT
        2. 按文件拆分 diff
        3. 逐个解析 + 多层过滤（include/二进制/大文件/忽略模式）
        
        Args:
            include_patterns: 要审核的文件模式列表（glob 格式，如 ["src/**", "app/**"]）
                             默认 ["*"] 表示审核所有
            ignore_patterns: 忽略的文件模式列表（glob 格式，如 ["*.lock", "*.json"]）
            max_file_size: 最大文件大小限制（KB），超过的文件跳过
            
        Returns:
            FileDiff 列表（可能为空，表示暂存区没有可审核的文件）
        """
        if include_patterns is None:
            include_patterns = ["*"]
        if ignore_patterns is None:
            ignore_patterns = []
        
        file_diffs = []
        
        try:
            # 获取暂存区 diff
            diff_output = self.repo.git.diff('--cached', '--unified=5', '--diff-filter=ACMRT')
            
            if not diff_output.strip():
                return file_diffs
            
            # 按文件拆分 diff
            raw_diffs = self._split_diff_by_file(diff_output)
            
            for raw_diff in raw_diffs:
                file_diff = self._parse_file_diff(raw_diff)
                if not file_diff.filename:
                    continue
                
                # 检查二进制文件
                if self._is_binary_file(file_diff.filename):
                    continue
                
                # 检查 include 模式（不在白名单内的跳过）
                if not self._matches_patterns(file_diff.filename, include_patterns):
                    continue
                
                # 检查文件大小
                file_path = self.repo_path / file_diff.filename
                if file_path.exists():
                    file_size_kb = file_path.stat().st_size / 1024
                    if file_size_kb > max_file_size:
                        continue
                
                # 检查忽略模式
                if self._matches_patterns(file_diff.filename, ignore_patterns):
                    continue
                
                # 推断编程语言
                file_diff.language = self._get_file_language(file_diff.filename)
                
                file_diffs.append(file_diff)
        
        except Exception as e:
            print(f"[警告] 获取 diff 时出错: {e}")
        
        return file_diffs
    
    def get_commit_message(self) -> str:
        """
        获取已保存的 commit message
        
        Returns:
            commit message 内容，如果没有则返回空字符串
        """
        commit_msg_path = self.repo_path / ".git" / "COMMIT_EDITMSG"
        if commit_msg_path.exists():
            return commit_msg_path.read_text(encoding='utf-8').strip()
        return ""
    
    def _split_diff_by_file(self, diff_output: str) -> List[str]:
        """
        按文件拆分 diff 输出
        
        Args:
            diff_output: git diff 的完整输出
            
        Returns:
            每个文件的 diff 字符串列表
        """
        # 按 diff --git 分割，保留每个文件的内容
        pattern = r'(?=diff --git a/)'
        parts = re.split(pattern, diff_output)
        return [p.strip() for p in parts if p.strip().startswith('diff --git')]
    
    def _parse_file_diff(self, raw_diff: str) -> FileDiff:
        """
        解析单个文件的 diff
        
        Args:
            raw_diff: 单个文件的 diff 字符串
            
        Returns:
            FileDiff 对象
        """
        file_diff = FileDiff(diff_content=raw_diff)
        
        # 提取文件名
        # 格式: diff --git a/path/file b/path/file
        match = re.search(r'diff --git a/(.+?) b/(.+)', raw_diff)
        if match:
            file_diff.filename = match.group(1)
        
        # 检测文件状态
        if 'new file mode' in raw_diff:
            file_diff.status = 'added'
        elif 'deleted file mode' in raw_diff:
            file_diff.status = 'deleted'
        elif 'rename from' in raw_diff and 'rename to' in raw_diff:
            file_diff.status = 'renamed'
            # 提取新文件名
            rename_match = re.search(r'rename to (.+)', raw_diff)
            if rename_match:
                file_diff.filename = rename_match.group(1)
        else:
            file_diff.status = 'modified'
        
        # 解析 hunk 行号
        file_diff.line_numbers = self._parse_line_numbers(raw_diff)
        
        # 统计新增/删除行数
        file_diff.additions = raw_diff.count('\n+') - raw_diff.count('\n+++')
        file_diff.deletions = raw_diff.count('\n-') - raw_diff.count('\n---')
        
        return file_diff
    
    def _parse_line_numbers(self, raw_diff: str) -> List[int]:
        """
        解析 diff hunk 头中的行号信息
        
        Args:
            raw_diff: diff 字符串
            
        Returns:
            变更涉及的行号列表
        """
        line_numbers = []
        # hunk 头格式: @@ -start,count +start,count @@
        hunk_pattern = r'@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@'
        
        for match in re.finditer(hunk_pattern, raw_diff):
            start_line = int(match.group(1))
            # 收集该 hunk 涉及的所有行号
            hunk_end = raw_diff.find('\n@@', match.end())
            if hunk_end == -1:
                hunk_end = len(raw_diff)
            hunk_content = raw_diff[match.end():hunk_end]
            
            current_line = start_line
            for line in hunk_content.split('\n'):
                if line.startswith('+'):
                    line_numbers.append(current_line)
                    current_line += 1
                elif line.startswith('-'):
                    continue  # 删除的行不加入新文件的行号
                elif line.startswith('\\'):
                    continue  # "\ No newline at end of file"
                else:
                    current_line += 1
        
        return sorted(set(line_numbers))
    
    def _get_file_language(self, filename: str) -> str:
        """
        根据文件扩展名推断编程语言
        
        Args:
            filename: 文件名
            
        Returns:
            编程语言名称
        """
        ext = Path(filename).suffix.lower()
        return EXTENSION_LANGUAGE_MAP.get(ext, 'unknown')
    
    def _is_binary_file(self, filename: str) -> bool:
        """
        检查文件是否为二进制文件
        
        Args:
            filename: 文件名
            
        Returns:
            True 如果是二进制文件
        """
        # 检查扩展名
        ext = Path(filename).suffix.lower()
        if ext in BINARY_EXTENSIONS:
            return True
        
        # 检查文件内容
        file_path = self.repo_path / filename
        if file_path.exists():
            try:
                with open(file_path, 'rb') as f:
                    chunk = f.read(8192)
                    if b'\x00' in chunk:
                        return True
                    # 检查是否包含大量非文本字节
                    non_text = sum(1 for b in chunk if b > 127)
                    if len(chunk) > 0 and non_text / len(chunk) > 0.3:
                        return True
            except OSError:
                pass
        
        return False
    
    def _matches_patterns(self, filename: str, patterns: List[str]) -> bool:
        """
        检查文件名是否匹配任何 glob 模式
        
        同时用于 include_patterns 和 ignore_patterns：
        - include: 不匹配任何模式 → 跳过
        - ignore: 匹配任何模式 → 跳过
        
        匹配策略：
        1. 完整路径匹配（如 "src/main.py" 匹配 "src/**"、"src/*.py"）
        2. basename 匹配（如 "src/main.py" 匹配 "*.py"、"main.*"）
        任一方式匹配即命中。
        
        Args:
            filename: 文件名（相对路径，如 "src/auth.py"）
            patterns: glob 模式列表
            
        Returns:
            True 如果匹配任何模式
        """
        from fnmatch import fnmatch
        basename = filename.split('/')[-1] if '/' in filename else filename
        for pattern in patterns:
            if fnmatch(filename, pattern):
                return True
            if fnmatch(basename, pattern):
                return True
        return False
    
    def get_repo_root(self) -> str:
        """获取仓库根目录路径"""
        return str(self.repo_path)
    
def collect_staged_diffs(repo_path: str = ".", include_patterns: Optional[List[str]] = None,
                         ignore_patterns: Optional[List[str]] = None,
                         max_file_size: int = 500) -> List[FileDiff]:
    """
    便捷函数：获取暂存区 diff
    
    Args:
        repo_path: Git 仓库路径
        include_patterns: 要审核的文件模式（glob）
        ignore_patterns: 忽略的文件模式
        max_file_size: 最大文件大小（KB）
        
    Returns:
        FileDiff 列表
    """
    collector = DiffCollector(repo_path)
    return collector.get_staged_diffs(
        include_patterns=include_patterns,
        ignore_patterns=ignore_patterns,
        max_file_size=max_file_size
    )
