"""案例库更新器

负责从远程 Git 仓库拉取最新的案例文件。

流程：
1. 检查本地缓存目录 ~/.commit-ai-guardian/cases-repo/ 是否存在
2. 不存在 → git clone
3. 存在 → git pull
4. 用拉取下来的案例文件替换内置案例

配置：
    cases_repo: "git@github.com:yourteam/review-cases.git"
    或
    cases_repo: "https://github.com/yourteam/review-cases.git"
"""

import os
import subprocess
from pathlib import Path
from typing import Optional


# 案例库本地缓存路径
DEFAULT_CACHE_DIR = Path.home() / ".commit-ai-guardian" / "cases-repo"


class CasesUpdater:
    """案例库更新器
    
    从配置的 Git 仓库地址拉取最新案例。
    """
    
    def __init__(self, repo_url: str, cache_dir: Optional[Path] = None):
        """初始化
        
        Args:
            repo_url: Git 仓库地址（SSH 或 HTTPS）
            cache_dir: 本地缓存目录，默认 ~/.commit-ai-guardian/cases-repo/
        """
        self.repo_url = repo_url.strip()
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
    
    def update(self) -> bool:
        """拉取最新案例
        
        逻辑：
        1. 本地目录不存在 → git clone
        2. 本地目录存在 → git pull
        3. Git 命令失败 → 打印警告，继续使用旧案例
        
        Returns:
            True = 更新成功（或已有最新案例）
            False = 更新失败（但内置案例仍可用）
        """
        if not self.repo_url:
            # 未配置远程仓库，使用内置案例，无需更新
            return True
        
        try:
            if self.cache_dir.exists() and (self.cache_dir / ".git").exists():
                # 已存在，执行 git pull
                return self._pull()
            else:
                # 不存在，执行 git clone
                return self._clone()
        except Exception as e:
            print(f"[警告] 案例库更新失败: {e}")
            print(f"        继续使用已有案例（{self.cache_dir}）")
            return False
    
    def _clone(self) -> bool:
        """首次克隆仓库"""
        print(f"[信息] 首次克隆案例库: {self.repo_url}")
        print(f"        目标目录: {self.cache_dir}")
        
        # 确保父目录存在
        self.cache_dir.parent.mkdir(parents=True, exist_ok=True)
        
        result = subprocess.run(
            ["git", "clone", self.repo_url, str(self.cache_dir)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        if result.returncode == 0:
            print(f"[成功] 案例库克隆完成")
            return True
        else:
            print(f"[错误] git clone 失败: {result.stderr.strip()}")
            return False
    
    def _pull(self) -> bool:
        """拉取最新更新"""
        print(f"[信息] 更新案例库: {self.cache_dir}")
        
        result = subprocess.run(
            ["git", "-C", str(self.cache_dir), "pull"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        
        if result.returncode == 0:
            output = result.stdout.strip()
            if "Already up to date" in output or "已经是最新" in output:
                print(f"[信息] 案例库已是最新")
            else:
                print(f"[成功] 案例库已更新: {output}")
            return True
        else:
            print(f"[错误] git pull 失败: {result.stderr.strip()}")
            return False
    
    def get_cases_dir(self) -> Optional[Path]:
        """获取案例文件所在的目录
        
        优先返回远程仓库的案例目录（如果已拉取），
        否则返回 None（使用内置案例）。
        
        Returns:
            案例目录路径，或 None
        """
        if not self.repo_url:
            return None
        
        # 远程案例目录存在且有效
        if self.cache_dir.exists() and (self.cache_dir / ".git").exists():
            return self.cache_dir
        
        return None
