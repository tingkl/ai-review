"""案例文件格式校验器

用法：
    commit-ai-guardian validate-cases

检查 .ai-review/cases/ 下的所有 .md 文件，验证格式是否正确。
支持 Markdown + YAML frontmatter 格式。
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    yaml = None

from .case_loader import parse_frontmatter, extract_examples, extract_check_points


VALID_SEVERITIES = {"critical", "error", "warning", "info"}
VALID_CATEGORIES = {"Bug检测", "安全", "代码风格", "性能", "最佳实践", "文档"}

# frontmatter 必填字段
REQUIRED_FIELDS = ["title", "severity", "category"]


def validate_case_file(filepath: Path) -> Tuple[bool, List[str]]:
    """校验单个案例文件（Markdown 格式）
    
    Returns:
        (是否通过, 错误信息列表)
    """
    errors = []
    
    # 1. 读取并解析
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        errors.append(f"文件读取失败: {e}")
        return False, errors
    
    if not content.strip():
        errors.append("文件为空")
        return False, errors
    
    # 2. 检查是否有 frontmatter
    if not content.startswith("---"):
        errors.append("缺少 YAML frontmatter（文件开头必须是 ---）")
        return False, errors
    
    # 3. 解析 frontmatter
    frontmatter, body = parse_frontmatter(content)
    
    if not frontmatter:
        errors.append("frontmatter 解析失败或为空")
        return False, errors
    
    # 4. 检查必填字段
    for field in REQUIRED_FIELDS:
        if field not in frontmatter:
            errors.append(f"缺少必填字段: '{field}'")
    
    # 5. 检查字段值
    if "severity" in frontmatter:
        sev = frontmatter["severity"]
        if sev not in VALID_SEVERITIES:
            errors.append(f"severity 必须是 {'/'.join(sorted(VALID_SEVERITIES))} 之一，当前: '{sev}'")
    
    if "category" in frontmatter:
        cat = frontmatter["category"]
        if cat not in VALID_CATEGORIES:
            errors.append(f"category 必须是 {'/'.join(sorted(VALID_CATEGORIES))} 之一，当前: '{cat}'")
    
    # 6. 检查正文结构
    if "## 问题描述" not in body:
        errors.append("缺少 '## 问题描述' 章节")
    
    if "## 坏代码" not in body and "## 坏代码 ❌" not in body:
        errors.append("缺少 '## 坏代码' 章节")
    
    if "## 好代码" not in body and "## 好代码 ✅" not in body:
        errors.append("缺少 '## 好代码' 章节")
    
    if "## 检查清单" not in body:
        errors.append("缺少 '## 检查清单' 章节")
    
    # 7. 检查是否能提取到示例
    bad_examples, good_examples = extract_examples(body)
    if not bad_examples:
        errors.append("未提取到坏代码示例（需要 ### 标签 + ``` 代码块）")
    
    if not good_examples:
        errors.append("未提取到好代码示例（需要 ### 标签 + ``` 代码块）")
    
    return len(errors) == 0, errors


def validate_all_cases(cases_dir: Optional[Path] = None) -> Dict[str, Tuple[bool, List[str]]]:
    """校验目录下所有案例文件"""
    if cases_dir is None:
        cases_dir = Path(".ai-review") / "cases"
    
    results = {}
    
    if not cases_dir.exists():
        print(f"❌ 案例目录不存在: {cases_dir}")
        print(f"   先运行: commit-ai-guardian install")
        return results
    
    case_files = sorted(cases_dir.glob("*.md"))
    
    if not case_files:
        print(f"⚠️ 案例目录为空: {cases_dir}")
        print(f"   从 example/ 复制案例: cp .ai-review/example/*.md .ai-review/cases/")
        return results
    
    print(f"检查 {len(case_files)} 个案例文件...\n")
    
    for case_file in case_files:
        passed, errors = validate_case_file(case_file)
        results[case_file.name] = (passed, errors)
        
        if passed:
            print(f"  ✅ {case_file.name}")
        else:
            print(f"  ❌ {case_file.name}")
            for err in errors:
                print(f"     - {err}")
    
    return results


def print_summary(results: Dict[str, Tuple[bool, List[str]]]) -> bool:
    """打印汇总信息"""
    if not results:
        return False
    
    total = len(results)
    passed = sum(1 for ok, _ in results.values() if ok)
    
    print(f"\n{'='*40}")
    print(f"总计: {total} 个文件 | 通过: {passed} | 失败: {total - passed}")
    
    if passed == total:
        print("全部通过 ✅")
        return True
    else:
        print("请修复上面的错误后重试")
        return False
