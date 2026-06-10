"""文件采集器

用于 review 命令（直接审核指定文件/目录），不依赖 Git。

功能：
- collect_file()    → 单文件
- collect_dir()     → 目录（递归/非递归）
- collect_pattern() → glob 模式
- collect()         → 综合采集（文件+目录+模式，自动去重）

过滤机制：二进制文件、超大文件、ignore_patterns 匹配的文件都会被跳过。
"""

import os
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterator, List, Optional


# 编程语言映射表（与 diff_collector 保持一致）
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


@dataclass
class SourceFile:
    """源代码文件信息（AI 审核引擎 review_source() 的输入）
    
    与 FileDiff 的区别：FileDiff 存的是 diff 片段，SourceFile 存的是完整文件内容。
    """
    filename: str = ""       # 文件绝对/相对路径
    language: str = ""       # 编程语言（从扩展名推断，用于 prompt 代码高亮）
    content: str = ""        # 完整文件内容（传给 AI 审核）
    line_count: int = 0      # 行数（用于 prompt 显示）
    file_size: int = 0       # 文件大小（bytes，用于日志）


class FileCollector:
    """文件采集器
    
    使用示例：
        c = FileCollector()
        sources = c.collect(files=["a.py"], dirs=["src/"], patterns=["tests/*.py"])
    
    collect() 方法支持同时从三种来源采集，自动去重。
    """
    
    def __init__(self,
                 include_patterns: Optional[List[str]] = None,
                 ignore_patterns: Optional[List[str]] = None,
                 max_file_size: int = 500):
        """初始化
        
        Args:
            include_patterns: 要审核的模式列表（glob 格式），如 ["src/**", "app/**"]
                              默认 ["*"] 表示审核所有
            ignore_patterns: 忽略模式列表（glob 格式），如 ["*.lock", "*.json"]
            max_file_size: 最大文件大小（KB），超过的文件会被跳过
        """
        self.include_patterns = include_patterns or ["*"]
        self.ignore_patterns = ignore_patterns or []
        self.max_file_size = max_file_size * 1024  # KB → bytes
    
    def collect_file(self, file_path: str) -> Optional[SourceFile]:
        """
        采集单个文件
        
        Args:
            file_path: 文件路径（相对或绝对）
            
        Returns:
            SourceFile 对象，如果文件无效则返回 None
        """
        path = Path(file_path)
        
        if not path.exists():
            print(f"[警告] 文件不存在: {file_path}")
            return None
        
        if not path.is_file():
            print(f"[警告] 不是文件: {file_path}")
            return None
        
        if self._is_binary_file(path):
            print(f"[跳过] 二进制文件: {file_path}")
            return None
        
        if self._is_too_large(path):
            print(f"[跳过] 文件过大: {file_path}")
            return None
        
        # 检查 include_patterns（不在白名单内的跳过）
        if not self._matches_include_patterns(str(path)):
            return None
        
        if self._matches_ignore_patterns(str(path)):
            return None
        
        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            print(f"[跳过] 无法以 UTF-8 读取: {file_path}")
            return None
        except OSError as e:
            print(f"[错误] 读取文件失败 {file_path}: {e}")
            return None
        
        return SourceFile(
            filename=str(path),
            language=self._get_file_language(str(path)),
            content=content,
            line_count=content.count('\n') + 1,
            file_size=path.stat().st_size,
        )
    
    def collect_dir(self, dir_path: str, recursive: bool = True) -> List[SourceFile]:
        """
        采集目录下的所有代码文件
        
        Args:
            dir_path: 目录路径
            recursive: 是否递归子目录
            
        Returns:
            SourceFile 列表
        """
        path = Path(dir_path)
        
        if not path.exists():
            print(f"[警告] 目录不存在: {dir_path}")
            return []
        
        if not path.is_dir():
            print(f"[警告] 不是目录: {dir_path}")
            return []
        
        results = []
        
        if recursive:
            iterator = path.rglob('*')
        else:
            iterator = path.iterdir()
        
        for item in iterator:
            if item.is_file():
                source_file = self.collect_file(str(item))
                if source_file:
                    results.append(source_file)
        
        return results
    
    def collect_pattern(self, pattern: str) -> List[SourceFile]:
        """
        使用 glob 模式采集文件
        
        Args:
            pattern: glob 模式，如 "src/**/*.py", "tests/*.py"
            
        Returns:
            SourceFile 列表
        """
        import glob
        
        paths = glob.glob(pattern, recursive=True)
        results = []
        
        for p in sorted(paths):
            if os.path.isfile(p):
                source_file = self.collect_file(p)
                if source_file:
                    results.append(source_file)
        
        return results
    
    def collect(self,
                files: Optional[List[str]] = None,
                dirs: Optional[List[str]] = None,
                patterns: Optional[List[str]] = None,
                recursive: bool = True) -> List[SourceFile]:
        """综合采集 - 同时支持文件、目录、模式三种方式，自动去重
        
        去重机制：用 set 记录已处理的文件名，同一个文件通过多种方式指定也只审核一次。
        
        Args:
            files: 单文件路径列表，如 ["src/main.py", "src/auth.py"]
            dirs: 目录路径列表，如 ["src/", "tests/"]
            patterns: glob 模式列表，如 ["src/**/*.py"]
            recursive: 目录是否递归子目录（默认 True）
            
        Returns:
            去重后的 SourceFile 列表
        """
        seen = set()
        results = []
        
        # 采集单文件
        if files:
            for f in files:
                source = self.collect_file(f)
                if source and source.filename not in seen:
                    seen.add(source.filename)
                    results.append(source)
        
        # 采集目录
        if dirs:
            for d in dirs:
                sources = self.collect_dir(d, recursive=recursive)
                for source in sources:
                    if source.filename not in seen:
                        seen.add(source.filename)
                        results.append(source)
        
        # 采集模式匹配
        if patterns:
            for pattern in patterns:
                sources = self.collect_pattern(pattern)
                for source in sources:
                    if source.filename not in seen:
                        seen.add(source.filename)
                        results.append(source)
        
        return results
    
    def _get_file_language(self, filename: str) -> str:
        """根据文件扩展名推断编程语言"""
        ext = Path(filename).suffix.lower()
        return EXTENSION_LANGUAGE_MAP.get(ext, 'unknown')
    
    def _is_binary_file(self, path: Path) -> bool:
        """检查是否为二进制文件"""
        ext = path.suffix.lower()
        if ext in BINARY_EXTENSIONS:
            return True
        
        try:
            with open(path, 'rb') as f:
                chunk = f.read(8192)
                if b'\x00' in chunk:
                    return True
                non_text = sum(1 for b in chunk if b > 127)
                if len(chunk) > 0 and non_text / len(chunk) > 0.3:
                    return True
        except OSError:
            pass
        
        return False
    
    def _is_too_large(self, path: Path) -> bool:
        """检查文件是否过大"""
        try:
            return path.stat().st_size > self.max_file_size
        except OSError:
            return True
    
    def _matches_include_patterns(self, filename: str) -> bool:
        """检查是否匹配 include 模式（白名单，支持 ** 递归目录匹配）
        
        同时支持路径模式和后缀模式：
        - "src/**/*.py" → 匹配 src/ 下所有 .py 文件（含子目录和根层）
        - "**/*.py" → 匹配所有 .py 文件（任意目录）
        - "*.py" → 匹配任意目录下的 .py 文件（通过后缀匹配）
        
        ** 语义：递归匹配任意层目录，包括 0 层（标准 glob 行为）
        """
        from commit_ai_guardian.diff_collector import _match_with_globstar
        basename = filename.split('/')[-1] if '/' in filename else filename
        for pattern in self.include_patterns:
            if _match_with_globstar(filename, pattern):
                return True
            if _match_with_globstar(basename, pattern):
                return True
        return False
    
    def _matches_ignore_patterns(self, filename: str) -> bool:
        """检查是否匹配忽略模式（支持 ** 递归目录匹配）
        
        匹配策略与 include 一致：完整路径 + basename 双重匹配。
        """
        from commit_ai_guardian.diff_collector import _match_with_globstar
        basename = filename.split('/')[-1] if '/' in filename else filename
        for pattern in self.ignore_patterns:
            if _match_with_globstar(filename, pattern):
                return True
            if _match_with_globstar(basename, pattern):
                return True
        return False
    
    def collect_git_history(self, repo_path: str, commit_hash: str,
                           file_path: Optional[str] = None) -> List[SourceFile]:
        """
        采集 Git 历史 commit 中的文件内容
        
        Args:
            repo_path: Git 仓库路径
            commit_hash: commit hash（如 HEAD~1）
            file_path: 可选，只采集指定文件
            
        Returns:
            SourceFile 列表
        """
        try:
            from git import Repo
            repo = Repo(repo_path)
            commit = repo.commit(commit_hash)
            
            results = []
            
            for item in commit.tree.traverse():
                if item.type != 'blob':
                    continue
                
                blob = item
                
                # 如果指定了文件路径，只匹配该文件
                if file_path and blob.path != file_path:
                    continue
                
                # 过滤二进制和大文件
                if blob.size > self.max_file_size:
                    continue
                
                # 过滤不在 include_patterns 内的文件
                if not self._matches_include_patterns(blob.path):
                    continue
                
                # 过滤匹配 ignore_patterns 的文件
                if self._matches_ignore_patterns(blob.path):
                    continue
                
                try:
                    content = blob.data_stream.read().decode('utf-8')
                except UnicodeDecodeError:
                    continue
                
                results.append(SourceFile(
                    filename=blob.path,
                    language=self._get_file_language(blob.path),
                    content=content,
                    line_count=content.count('\n') + 1,
                    file_size=blob.size,
                ))
            
            return results
        
        except ImportError:
            print("[错误] GitPython 未安装，无法使用 collect_git_history")
            return []
        except Exception as e:
            print(f"[错误] 获取 Git 历史失败: {e}")
            return []
