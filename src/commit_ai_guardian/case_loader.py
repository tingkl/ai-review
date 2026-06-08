"""案例加载器

支持两种来源：
1. 目标仓库的 .ai-review/cases/    ← 项目级别（优先级最高）
2. 远程 Git 仓库拉取的案例         ← 全局共享

没有内置默认案例！如果两个都没有，审核退化为通用规则检查。

初始化命令：
    commit-ai-guardian init    ← 在目标仓库创建 .ai-review/cases/ + 示例
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None


# 目标仓库中存放案例的目录名
REPO_CASES_DIR = ".ai-review" / "cases"


class CaseLoader:
    """加载和管理审核案例
    
    两级优先级（从高到低）：
    1. 目标仓库的 .ai-review/cases/  — 项目自己的规则
    2. 远程 Git 仓库拉取的案例       — 团队共享
    
    没有内置默认！找不到案例时返回空列表。
    """
    
    def __init__(self,
                 repo_path: Optional[str] = None,
                 remote_cases_dir: Optional[Path] = None):
        """初始化
        
        Args:
            repo_path: 目标代码仓库路径（用于查找 .ai-review/cases/）
            remote_cases_dir: 远程 Git 仓库拉取的案例目录路径
        """
        self.repo_path = repo_path
        self.remote_cases_dir = remote_cases_dir
        
        # 按优先级确定最终使用哪个目录
        self.cases_dir = self._resolve_cases_dir()
        self._cases: List[Dict[str, Any]] = []
        
        # 打印信息，让用户知道用的是哪套案例
        self._log_source()
    
    def _resolve_cases_dir(self) -> Optional[Path]:
        """按两级优先级确定案例目录
        
        Returns:
            案例目录 Path，或 None（两个来源都没有）
        """
        # === 优先级 1：目标仓库的 .ai-review/cases/ ===
        if self.repo_path:
            local_cases = Path(self.repo_path) / REPO_CASES_DIR
            if local_cases.exists():
                return local_cases
        
        # === 优先级 2：远程 Git 仓库拉取的案例 ===
        if self.remote_cases_dir and self.remote_cases_dir.exists():
            return self.remote_cases_dir
        
        # === 没有案例 ===
        return None
    
    def _log_source(self) -> None:
        """打印当前使用的案例来源"""
        if self.cases_dir is None:
            print("[信息] 未找到案例库（运行 'commit-ai-guardian init' 初始化项目案例）")
        elif self.repo_path and str(self.cases_dir).startswith(str(self.repo_path)):
            print(f"[信息] 使用项目案例: {self.cases_dir}")
        else:
            print(f"[信息] 使用远程案例: {self.cases_dir}")
    
    def load_all(self) -> List[Dict[str, Any]]:
        """加载所有案例文件
        
        Returns:
            案例字典列表（没有则返回空列表）
        """
        if self._cases:
            return self._cases
        
        if yaml is None:
            print("[警告] PyYAML 未安装，无法加载审核案例")
            return []
        
        if self.cases_dir is None or not self.cases_dir.exists():
            return []
        
        cases = []
        # 遍历 cases/ 目录下所有 .yaml/.yml 文件
        for case_file in sorted(self.cases_dir.glob("*.yaml")):
            try:
                with open(case_file, 'r', encoding='utf-8') as f:
                    case = yaml.safe_load(f)
                if case and isinstance(case, dict):
                    case["_source"] = case_file.stem  # 记录文件名，用于调试
                    cases.append(case)
            except Exception as e:
                print(f"[警告] 加载案例 {case_file.name} 失败: {e}")
        
        self._cases = cases
        return cases
    
    def get_cases_for_language(self, language: str) -> List[Dict[str, Any]]:
        """获取指定编程语言相关的案例
        
        Args:
            language: 编程语言，如 "python"
            
        Returns:
            匹配的案例列表（可能为空）
        """
        all_cases = self.load_all()
        if not language or language == "unknown":
            return all_cases
        
        matched = []
        for case in all_cases:
            langs = case.get("languages", [])
            if not langs or language.lower() in [l.lower() for l in langs]:
                matched.append(case)
        
        return matched
    
    def format_cases_for_prompt(self, cases: List[Dict[str, Any]]) -> str:
        """将案例列表格式化为 Prompt 文本
        
        Args:
            cases: 案例字典列表
            
        Returns:
            适合插入 Prompt 的文本（空列表则返回空字符串）
        """
        if not cases:
            return ""
        
        lines = ["\n## 重点检查以下问题模式（参照案例）\n"]
        
        for i, case in enumerate(cases, 1):
            title = case.get("title", "未知")
            desc = case.get("description", "")
            bad = case.get("bad_example", "").strip()
            good = case.get("good_example", "").strip()
            checks = case.get("check_points", [])
            severity = case.get("severity", "warning")
            
            lines.append(f"### {i}. {title} [{severity}]")
            if desc:
                lines.append(f"说明: {desc}")
            
            if bad:
                lines.append("坏代码:")
                lines.append(f"```\n{bad}\n```")
            
            if good:
                lines.append("好代码:")
                lines.append(f"```\n{good}\n```")
            
            if checks:
                lines.append("检查要点:")
                for cp in checks:
                    lines.append(f"  - {cp}")
            
            lines.append("")  # 空行分隔
        
        return "\n".join(lines)
