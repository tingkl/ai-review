"""案例文件格式校验器

用法：
    commit-ai-guardian validate-cases

检查 .ai-review/cases/ 下的所有 .yaml 文件，验证格式是否正确。
输出每个文件的状态，以及具体的错误信息。
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    yaml = None


# 合法的枚举值
VALID_SEVERITIES = {"critical", "error", "warning", "info"}
VALID_CATEGORIES = {"bug", "security", "style", "performance", "best-practice", "documentation"}

# 必填字段
REQUIRED_FIELDS = ["title", "description", "severity", "category", "bad_examples", "good_examples"]


def validate_case_file(filepath: Path) -> Tuple[bool, List[str]]:
    """校验单个案例文件
    
    Args:
        filepath: .yaml 文件路径
        
    Returns:
        (是否通过, 错误信息列表)
    """
    errors = []
    
    # 1. 检查文件能否解析
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        errors.append(f"YAML 解析失败: {e}")
        return False, errors
    except Exception as e:
        errors.append(f"文件读取失败: {e}")
        return False, errors
    
    if data is None:
        errors.append("文件为空")
        return False, errors
    
    if not isinstance(data, dict):
        errors.append("根节点必须是字典（key: value 格式）")
        return False, errors
    
    # 2. 检查必填字段
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"缺少必填字段: '{field}'")
    
    # 3. 检查 severity 值
    if "severity" in data:
        sev = data["severity"]
        if isinstance(sev, int):
            if not (1 <= sev <= 10):
                errors.append(f"severity 数值必须在 1-10 之间，当前: {sev}")
        elif sev not in VALID_SEVERITIES:
            errors.append(f"severity 必须是 1-10 的数字或 {VALID_SEVERITIES} 之一，当前: '{sev}'")
    
    # 4. 检查 category 值
    if "category" in data:
        cat = data["category"]
        if cat not in VALID_CATEGORIES:
            errors.append(f"category 必须是 {VALID_CATEGORIES} 之一，当前: '{cat}'")
    
    # 5. 检查 bad_examples 格式
    if "bad_examples" in data:
        be = data["bad_examples"]
        if isinstance(be, list):
            for i, item in enumerate(be):
                if not isinstance(item, dict):
                    errors.append(f"bad_examples[{i}] 必须是字典（有 label 和 code）")
                elif "code" not in item:
                    errors.append(f"bad_examples[{i}] 缺少 'code' 字段")
        elif isinstance(be, str):
            # 兼容旧格式（字符串）
            pass
        else:
            errors.append("bad_examples 必须是列表或字符串")
    
    # 6. 检查 good_examples 格式
    if "good_examples" in data:
        ge = data["good_examples"]
        if isinstance(ge, list):
            for i, item in enumerate(ge):
                if not isinstance(item, dict):
                    errors.append(f"good_examples[{i}] 必须是字典（有 label 和 code）")
                elif "code" not in item:
                    errors.append(f"good_examples[{i}] 缺少 'code' 字段")
        elif isinstance(ge, str):
            # 兼容旧格式
            pass
        else:
            errors.append("good_examples 必须是列表或字符串")
    
    # 7. 检查 languages
    if "languages" in data:
        langs = data["languages"]
        if not isinstance(langs, list):
            errors.append("languages 必须是列表（如 [python, java]）")
    
    return len(errors) == 0, errors


def validate_all_cases(cases_dir: Optional[Path] = None) -> Dict[str, Tuple[bool, List[str]]]:
    """校验目录下所有案例文件
    
    Args:
        cases_dir: 案例目录，默认 .ai-review/cases/
        
    Returns:
        {文件名: (是否通过, 错误列表)}
    """
    if cases_dir is None:
        cases_dir = Path(".ai-review") / "cases"
    
    results = {}
    
    if not cases_dir.exists():
        print(f"❌ 案例目录不存在: {cases_dir}")
        print(f"   先运行: commit-ai-guardian install")
        return results
    
    case_files = sorted(cases_dir.glob("*.yaml"))
    
    if not case_files:
        print(f"⚠️ 案例目录为空: {cases_dir}")
        print(f"   从 example/ 复制案例: cp .ai-review/example/*.yaml .ai-review/cases/")
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
    """打印汇总信息
    
    Returns:
        True = 全部通过
    """
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
