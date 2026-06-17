"""案例加载器

从目标仓库的 .ai-review/cases/ 加载案例。
没有内置默认案例！找不到就退回通用规则检查。

案例文件格式：Markdown + YAML frontmatter

```markdown
---
title: SQL 注入
severity: 9
level: critical
category: 安全漏洞
tags: [SQL, 注入]
languages: [python, java]
---

## 问题描述
...

## 坏代码

### 场景1
```python
# 坏代码
```

## 好代码

### 场景1
```python
# 好代码
```

## 检查清单
- [ ] 问题1
  - 提示
```

没有内置默认案例！如果两个都没有，审核退化为通用规则检查。
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    yaml = None


# 目标仓库中存放案例的目录名
REPO_CASES_DIR = Path(".ai-review") / "cases"


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """解析 Markdown 文件的 YAML frontmatter
    
    格式:
        ---
        title: xxx
        severity: 9
        ---
        ## 正文...
    
    Returns:
        (frontmatter_dict, markdown_body)
    """
    if not content.startswith("---"):
        return {}, content
    
    # 找到第二个 ---
    match = re.search(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if not match:
        return {}, content
    
    frontmatter_text = match.group(1)
    body = content[match.end():]
    
    if yaml is None:
        return {}, body
    
    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except Exception:
        frontmatter = {}
    
    return frontmatter, body


def extract_examples(body: str) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], List[Dict[str, str]]]:
    """从 Markdown 正文中提取坏代码、好代码和可接受代码示例
    
    匹配格式:
        ## 坏代码
        
        ### 场景名
        ```python
        代码
        ```
        
        ## 好代码
        
        ## 可接受代码（白名单）
        
    Returns:
        (bad_examples, good_examples, acceptable_examples)
    """
    bad_examples = []
    good_examples = []
    acceptable_examples = []
    
    # 提取 ## 坏代码 到下一个 ## 好代码/## 可接受代码/## 检查清单 之间的内容
    bad_match = re.search(r'##\s*坏代码.*?\n(.*?)##\s*(好代码|可接受代码|检查清单)', body, re.DOTALL | re.IGNORECASE)
    if bad_match:
        bad_section = bad_match.group(1)
        bad_examples = _extract_labeled_code_blocks(bad_section)
    
    # 提取 ## 好代码 到下一个 ## 可接受代码/## 检查清单 之间的内容
    good_match = re.search(r'##\s*好代码.*?\n(.*?)##\s*(可接受代码|检查清单)', body, re.DOTALL | re.IGNORECASE)
    if good_match:
        good_section = good_match.group(1)
        good_examples = _extract_labeled_code_blocks(good_section)
    
    # 提取 ## 可接受代码 到 ## 检查清单 之间的内容
    acceptable_match = re.search(r'##\s*可接受代码.*?\n(.*?)##\s*检查清单', body, re.DOTALL | re.IGNORECASE)
    if acceptable_match:
        acceptable_section = acceptable_match.group(1)
        acceptable_examples = _extract_labeled_code_blocks(acceptable_section)
    
    return bad_examples, good_examples, acceptable_examples


def _extract_labeled_code_blocks(section: str) -> List[Dict[str, str]]:
    """从 Markdown 节中提取带标签的代码块
    
    ### 标签名
    ```python
    代码
    ```
    
    Returns:
        [{"label": "标签名", "code": "代码"}, ...]
    """
    examples = []
    
    # 匹配 ### 标签 + ```...``` 代码块
    pattern = r'###\s*(.+?)\n\s*```\w*\n(.*?)\n\s*```'
    for match in re.finditer(pattern, section, re.DOTALL):
        label = match.group(1).strip()
        code = match.group(2).strip()
        examples.append({"label": label, "code": code})
    
    return examples


def extract_check_points(body: str) -> List[Dict[str, str]]:
    """从检查清单中提取问题 + 提示
    
    - [ ] 问题？
      - 提示内容
    
    Returns:
        [{"question": "问题", "hint": "提示"}, ...]
    """
    check_points = []
    
    # 找到 ## 检查清单 部分
    checklist_match = re.search(r'##\s*检查清单\s*\n(.*)', body, re.DOTALL | re.IGNORECASE)
    if not checklist_match:
        return check_points
    
    checklist_section = checklist_match.group(1)
    
    # 匹配 - [ ] 问题
    #        - 提示
    pattern = r'-\s*\[\s*\]\s*(.+?)(?:\n\s+-\s*(.+?))?(?=\n\s*-\s*\[|$)'
    for match in re.finditer(pattern, checklist_section, re.DOTALL):
        question = match.group(1).strip()
        hint = match.group(2).strip() if match.group(2) else ""
        check_points.append({"question": question, "hint": hint})
    
    return check_points


class CaseLoader:
    """加载和管理审核案例
    
    只从目标仓库的 .ai-review/cases/ 加载案例。
    没有内置默认案例！找不到就退回通用规则检查。
    """
    
    def __init__(self, repo_path: Optional[str] = None):
        """初始化
        
        Args:
            repo_path: 目标代码仓库路径（用于查找 .ai-review/cases/）
        """
        self.repo_path = repo_path
        
        self.cases_dir = self._resolve_cases_dir()
        self._cases: List[Dict[str, Any]] = []
        
        self._log_source()
    
    def _resolve_cases_dir(self) -> Optional[Path]:
        """查找项目案例目录"""
        if self.repo_path:
            local_cases = Path(self.repo_path) / REPO_CASES_DIR
            if local_cases.exists():
                return local_cases
        
        return None
    
    def _log_source(self) -> None:
        """打印当前使用的案例来源"""
        if self.cases_dir is None:
            print("[信息] 未找到案例库（运行 'commit-ai-guardian install' 初始化）")
        else:
            print(f"[信息] 使用项目案例: {self.cases_dir}")
    
    def load_all(self) -> List[Dict[str, Any]]:
        """加载所有案例文件（.md 格式）"""
        if self._cases:
            return self._cases
        
        if yaml is None:
            print("[警告] PyYAML 未安装，无法加载审核案例")
            return []
        
        if self.cases_dir is None or not self.cases_dir.exists():
            return []
        
        cases = []
        for case_file in sorted(self.cases_dir.glob("*.md")):
            try:
                with open(case_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                frontmatter, body = parse_frontmatter(content)
                bad_examples, good_examples, acceptable_examples = extract_examples(body)
                check_points = extract_check_points(body)
                
                # 组合成旧格式的结构（兼容 AI prompt）
                case = {
                    **frontmatter,
                    "_source": case_file.stem,
                    "bad_examples": bad_examples,
                    "good_examples": good_examples,
                    "acceptable_examples": acceptable_examples,
                    "check_points": check_points,
                    # 从正文中提取各部分内容
                    "description": self._extract_description(body),
                    "why_it_matters": self._extract_why_it_matters(body),
                    "consequences": self._extract_consequences(body),
                }
                cases.append(case)
            except Exception as e:
                print(f"[警告] 加载案例 {case_file.name} 失败: {e}")
        
        self._cases = cases
        return cases
    
    def _extract_description(self, body: str) -> str:
        """从 Markdown 正文中提取问题描述"""
        # 匹配 ## 问题描述 后面的内容
        match = re.search(r'##\s*问题描述\s*\n(.+?)(?=\n##|\Z)', body, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""
    
    @staticmethod
    def _collapse_list(text: str) -> str:
        """把 Markdown 列表文本合并为一行
        
        案例中的 why_it_matters / consequences 可能是多行列表：
          - 数据泄露
          - 数据被篡改
        
        转为结构化格式时合并为一行，用逗号分隔，避免重复前缀。
        
        Args:
            text: 可能含 Markdown 列表的多行文本
            
        Returns:
            合并后的单行文本
        """
        lines = []
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            # 去掉 Markdown 列表标记 '- ' 和 '* '
            if line.startswith('- '):
                line = line[2:]
            elif line.startswith('* '):
                line = line[2:]
            if line:
                lines.append(line)
        return '，'.join(lines) if lines else text
    
    def _extract_why_it_matters(self, body: str) -> str:
        """从 Markdown 正文中提取'为什么这是个问题'"""
        match = re.search(r'##\s*为什么这是个问题\s*\n(.+?)(?=\n##|\Z)', body, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""
    
    def _extract_consequences(self, body: str) -> str:
        """从 Markdown 正文中提取'不修复的后果'"""
        match = re.search(r'##\s*不修复的后果\s*\n(.+?)(?=\n##|\Z)', body, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""
    
    def get_cases_for_language(self, language: str) -> List[Dict[str, Any]]:
        """获取指定编程语言相关的案例"""
        all_cases = self.load_all()
        if not language or language == "unknown":
            return all_cases
        
        matched = []
        for case in all_cases:
            langs = case.get("languages", [])
            if not langs or language.lower() in [l.lower() for l in langs]:
                matched.append(case)
        
        return matched
    
    def format_cases_for_prompt(
        self,
        cases: List[Dict[str, Any]],
        case_format: str = "default"
    ) -> str:
        """将案例列表格式化为结构化 Prompt 文本（非 Markdown）

        支持三种格式级别，通过 case_format 参数控制：
        - default:  全部内容（结构化文本，保留所有字段）
        - compact:  精简（去掉 why + consequences，省 ~35% token）
        - minimal:  最小（只留 title + bad_examples + check_points，省 ~55% token）

        原始案例文件仍是 Markdown（用户友好），发给 AI 前转为结构化文本。
        """
        if not cases:
            return ""

        lines = ["\n重点检查以下问题模式:\n"]

        for i, case in enumerate(cases, 1):
            title = case.get("title", "未知")
            desc = case.get("description", "")
            severity = case.get("severity", "")
            level = case.get("level", "warning")

            # severity 可能是数字或字符串
            severity_label = f"{severity}/{level}" if isinstance(severity, int) else level

            lines.append(f"[案例{i}|{title}|{severity_label}]")

            # 非法值 fallback 到 default
            effective_format = case_format if case_format in ("default", "compact", "minimal") else "default"

            # minimal 模式下跳过 description
            if effective_format != "minimal" and desc:
                lines.append(f"说明: {desc}")

            # 坏代码示例（所有模式都保留）
            for be in case.get("bad_examples", []):
                label = be.get("label", "")
                code = be.get("code", "")
                if code:
                    lines.append(f"❌ 坏代码{f'({label})' if label else ''}:")
                    lines.append(code)

            # 好代码示例（minimal 模式去掉）
            if effective_format != "minimal":
                for ge in case.get("good_examples", []):
                    label = ge.get("label", "")
                    code = ge.get("code", "")
                    if code:
                        lines.append(f"✅ 好代码{f'({label})' if label else ''}:")
                        lines.append(code)

            # 可接受代码（白名单）—— minimal 模式去掉
            if effective_format != "minimal":
                for ae in case.get("acceptable_examples", []):
                    label = ae.get("label", "")
                    code = ae.get("code", "")
                    if code:
                        lines.append(f"🆗 可接受代码{f'({label})' if label else ''}（不要误报）:")
                        lines.append(code)

            # 原因 + 后果（仅 default 模式保留）
            if effective_format == "default":
                why = case.get("why_it_matters", "")
                if why:
                    lines.append(f"原因: {self._collapse_list(why)}")

                consequences = case.get("consequences", "")
                if consequences:
                    lines.append(f"后果: {self._collapse_list(consequences)}")

            # 检查点（所有模式都保留）
            for cp in case.get("check_points", []):
                question = cp.get("question", "")
                hint = cp.get("hint", "")
                if question:
                    lines.append(f"检查: {question}")
                    if hint:
                        lines.append(f"提示: {hint}")

            lines.append("")

        return "\n".join(lines)
