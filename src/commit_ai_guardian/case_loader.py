"""案例加载器

从 cases/ 目录加载 YAML 案例文件，审核时注入 Prompt 作为参照。

案例文件格式（YAML）：
    title: "SQL 注入"
    description: "..."
    severity: "critical"
    category: "security"
    languages: ["python", "java"]
    bad_example: "坏代码..."
    good_example: "好代码..."
    check_points: ["检查点1", "检查点2"]

用法：
    loader = CaseLoader()
    cases = loader.get_cases_for_language("python")  # 只取 Python 相关案例
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None


# 内置案例目录（随工具代码一起发布）
BUILTIN_CASES_DIR = Path(__file__).parent / "cases"


class CaseLoader:
    """加载和管理审核案例
    
    优先级：远程案例（Git 仓库拉取的）> 内置案例
    """
    
    def __init__(self, cases_dir: Optional[Path] = None):
        """初始化
        
        Args:
            cases_dir: 案例目录路径。None 则使用内置案例。
                        传入远程仓库路径则使用远程案例（优先级更高）。
        """
        self.cases_dir = cases_dir or BUILTIN_CASES_DIR
        self._cases: List[Dict[str, Any]] = []
    
    def load_all(self) -> List[Dict[str, Any]]:
        """加载所有案例文件
        
        Returns:
            案例字典列表
        """
        if self._cases:
            return self._cases
        
        if yaml is None:
            print("[警告] PyYAML 未安装，无法加载审核案例")
            return []
        
        if not self.cases_dir.exists():
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
        
        如果案例的 languages 列表包含该语言（或为空表示通用），则匹配。
        
        Args:
            language: 编程语言，如 "python"
            
        Returns:
            匹配的案例列表
        """
        all_cases = self.load_all()
        if not language or language == "unknown":
            return all_cases
        
        matched = []
        for case in all_cases:
            langs = case.get("languages", [])
            # languages 为空 或 包含目标语言 都匹配
            if not langs or language.lower() in [l.lower() for l in langs]:
                matched.append(case)
        
        return matched
    
    def format_cases_for_prompt(self, cases: List[Dict[str, Any]]) -> str:
        """将案例列表格式化为 Prompt 文本
        
        Args:
            cases: 案例字典列表
            
        Returns:
            适合插入 Prompt 的文本
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
