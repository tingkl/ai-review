#!/usr/bin/env python3
"""
测试 json_fix.log 文件中 AI 响应的 JSON 提取是否正确。

用法:
    python test_json_extract.py <json_fix.log 路径>

示例:
    python test_json_extract.py .ai-review/logs/028548b.json_fix.log
    python test_json_extract.py /Users/.../.ai-review/logs/028548b.json_fix.log
"""

import re
import json
import sys
from pathlib import Path


def extract_json_str(response: str) -> str | None:
    """从 AI 响应中提取 JSON 字符串（复制自 ai_engine.py）"""
    # 先过滤 <think> 标签
    filtered = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()

    # 策略 0: 从 <result> 标签提取
    m = re.search(r'<result>(.*?)</result>', filtered, re.DOTALL)
    if m:
        return m.group(1).strip()

    # 策略 1: 从 ```json 代码块提取
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', filtered, re.DOTALL)
    if m:
        return m.group(1).strip()

    # 策略 2: 找第一个 {...}
    m = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', filtered, re.DOTALL)
    if m:
        return m.group(0).strip()

    return None


def try_parse_json(json_str: str):
    """尝试解析 JSON（复制自 ai_engine.py）"""
    if not json_str or not json_str.strip():
        return None

    candidates = [
        json_str.strip(),
        json_str.strip().lstrip('\ufeff'),
    ]

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            continue

    return None


def validate_schema(data: dict) -> list:
    """校验 schema（简化版）"""
    errors = []
    for field in ['summary', 'passed', 'issues']:
        if field not in data:
            errors.append(f"缺少顶层必填字段: '{field}'")
    return errors


def main():
    if len(sys.argv) < 2:
        print(f"用法: python {sys.argv[0]} <json_fix.log 路径>")
        print(f"示例: python {sys.argv[0]} .ai-review/logs/028548b.json_fix.log")
        sys.exit(1)

    log_path = Path(sys.argv[1])
    if not log_path.exists():
        # 尝试在项目 .ai-review/logs/ 下找
        alt_path = Path.cwd() / ".ai-review" / "logs" / log_path.name
        if alt_path.exists():
            log_path = alt_path
        else:
            print(f"❌ 文件不存在: {log_path}")
            sys.exit(1)

    print(f"📄 读取: {log_path}\n")
    content = log_path.read_text(encoding='utf-8')

    # 分割出每次尝试
    attempts = re.split(r'--- 尝试 (\d+) ---', content)

    for i in range(1, len(attempts), 2):
        attempt_num = attempts[i]
        attempt_content = attempts[i + 1] if i + 1 < len(attempts) else ""

        print(f"{'='*60}")
        print(f"尝试 {attempt_num}")
        print(f"{'='*60}")

        # 提取 JSON
        extracted = extract_json_str(attempt_content)
        if not extracted:
            print("❌ 未提取到 JSON")
            continue

        print(f"✅ 提取到 JSON ({len(extracted)} 字符)")
        print(f"   前100字符: {extracted[:100]}")

        # 解析
        data = try_parse_json(extracted)
        if not data:
            print("❌ JSON 解析失败")
            # 定位解析错误
            try:
                json.loads(extracted)
            except json.JSONDecodeError as e:
                print(f"   错误: {e}")
                print(f"   位置: col={e.colno}")
                start = max(0, e.pos - 20)
                end = min(len(extracted), e.pos + 20)
                print(f"   附近: {repr(extracted[start:end])}")
            continue

        print(f"✅ 解析成功: type=dict, keys={list(data.keys())}")

        # schema 校验
        errors = validate_schema(data)
        if errors:
            print(f"❌ Schema 校验失败: {errors}")
        else:
            print(f"✅ Schema 校验通过!")
            print(f"   summary={repr(data.get('summary'))}")
            print(f"   passed={data.get('passed')}")
            print(f"   issues数量={len(data.get('issues', []))}")

    # 检查是否有 "全部失败" 标记
    if "全部 3 次尝试均失败" in content:
        print(f"\n{'='*60}")
        print("⚠️ 日志显示: 全部 3 次尝试均失败")

    if "schema 有小问题" in content:
        print(f"\n{'='*60}")
        print("⚠️ 日志显示: schema 有小问题，但字段完整")


if __name__ == "__main__":
    main()
