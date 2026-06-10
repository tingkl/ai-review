"""共享工具函数和常量

供 diff_collector、file_collector 等模块共用，避免重复定义。
"""

from pathlib import Path
from typing import Optional


# 编程语言映射表（从文件扩展名推断编程语言）
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


def get_file_language(filename: str) -> str:
    """根据文件扩展名推断编程语言"""
    ext = Path(filename).suffix.lower()
    return EXTENSION_LANGUAGE_MAP.get(ext, 'unknown')


def is_binary_file(filename: str, repo_path: Optional[str] = None) -> bool:
    """检查文件是否为二进制文件
    
    先检查扩展名，再检查文件内容（如果有 repo_path）。
    
    Args:
        filename: 文件名（相对路径）
        repo_path: 仓库根目录路径（可选，用于读取文件内容检查）
        
    Returns:
        True 如果是二进制文件
    """
    ext = Path(filename).suffix.lower()
    if ext in BINARY_EXTENSIONS:
        return True
    
    if repo_path:
        file_path = Path(repo_path) / filename
        if file_path.exists():
            try:
                with open(file_path, 'rb') as f:
                    chunk = f.read(8192)
                    if b'\x00' in chunk:
                        return True
                    non_text = sum(1 for b in chunk if b > 127)
                    if len(chunk) > 0 and non_text / len(chunk) > 0.3:
                        return True
            except OSError:
                pass
    
    return False
