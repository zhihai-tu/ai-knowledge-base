#!/usr/bin/env python3
"""校验知识条目 JSON 文件。

用法:
    python hooks/validate_json.py <json_file> [json_file2 ...]
    python hooks/validate_json.py v2/knowledge/**/*.json

全部通过 exit 0，失败 exit 1。
"""

import json
import re
import sys
from pathlib import Path


REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

VALID_STATUSES = {"draft", "review", "published", "archived"}
VALID_AUDIENCES = {"beginner", "intermediate", "advanced"}

ID_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://\S+$")


def validate_item(item: object, index: int) -> list[str]:
    errors: list[str] = []
    prefix = f"  条目 [{index}]"

    if not isinstance(item, dict):
        errors.append(f"{prefix}: 应为对象，实际为 {type(item).__name__}")
        return errors

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in item:
            errors.append(f"{prefix}.{field}: 缺少必填字段")
            continue
        if not isinstance(item[field], expected_type):
            errors.append(
                f"{prefix}.{field}: 应为 {expected_type.__name__} 类型，"
                f"实际为 {type(item[field]).__name__}"
            )

    id_val = item.get("id")
    if isinstance(id_val, str) and not ID_PATTERN.match(id_val):
        errors.append(
            f"{prefix}.id: 格式错误 '{id_val}'"
            f"（应为 {{来源}}-{{YYYYMMDD}}-{{NNN}}）"
        )

    status_val = item.get("status")
    if isinstance(status_val, str) and status_val not in VALID_STATUSES:
        errors.append(
            f"{prefix}.status: 无效值 '{status_val}'"
            f"（必须为 {', '.join(sorted(VALID_STATUSES))} 之一）"
        )

    url_val = item.get("source_url")
    if isinstance(url_val, str) and not URL_PATTERN.match(url_val):
        errors.append(f"{prefix}.source_url: URL 格式无效 '{url_val}'")

    summary_val = item.get("summary")
    if isinstance(summary_val, str) and len(summary_val) < 20:
        errors.append(
            f"{prefix}.summary: 摘要过短（{len(summary_val)} 字，"
            f"最少 20 字）"
        )

    tags_val = item.get("tags")
    if isinstance(tags_val, list) and len(tags_val) < 1:
        errors.append(f"{prefix}.tags: 至少需要 1 个标签")

    score_val = item.get("score")
    if score_val is not None:
        if not isinstance(score_val, (int, float)):
            errors.append(
                f"{prefix}.score: 应为数值类型，"
                f"实际为 {type(score_val).__name__}"
            )
        elif not (1 <= score_val <= 10):
            errors.append(f"{prefix}.score: 必须在 1-10 范围内，当前为 {score_val}")

    audience_val = item.get("audience")
    if audience_val is not None:
        if not isinstance(audience_val, str):
            errors.append(
                f"{prefix}.audience: 应为字符串类型，"
                f"实际为 {type(audience_val).__name__}"
            )
        elif audience_val not in VALID_AUDIENCES:
            errors.append(
                f"{prefix}.audience: 无效值 '{audience_val}'"
                f"（必须为 {', '.join(sorted(VALID_AUDIENCES))} 之一）"
            )

    return errors


def validate_file(path: Path) -> tuple[int, list[str]]:
    entry_count = 0
    errors: list[str] = []

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        errors.append(f"  无法读取文件: {e}")
        return 0, errors

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        errors.append(f"  JSON 解析失败: {e}")
        return 0, errors

    items = data if isinstance(data, list) else [data]
    entry_count = len(items)

    for i, item in enumerate(items):
        errors.extend(validate_item(item, i))

    return entry_count, errors


def resolve_paths(raw_args: list[str]) -> list[Path]:
    paths: list[Path] = []
    for arg in raw_args:
        if "*" in arg:
            paths.extend(sorted(Path().glob(arg)))
        else:
            paths.append(Path(arg))
    return paths


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python hooks/validate_json.py <json_file> [json_file2 ...]")
        sys.exit(1)

    files = resolve_paths(sys.argv[1:])
    all_errors: list[str] = []
    total_files = 0
    total_entries = 0

    results: list[str] = []

    for path in files:
        total_files += 1
        if not path.exists():
            results.append(f"✗ {path}: 文件不存在")
            continue
        entry_count, errors = validate_file(path)
        total_entries += entry_count
        if errors:
            results.append(f"✗ {path}: {len(errors)} 个错误")
            for e in errors:
                results.append(e)
        else:
            results.append(f"✓ {path}: 通过")

    error_count = sum(1 for r in results if r.startswith("  "))

    if error_count > 0:
        print("校验失败")
        print()
        print("\n".join(results))
        print()
        print("--- 汇总 ---")
        print(f"  检查文件数 : {total_files}")
        print(f"  条目总数   : {total_entries}")
        print(f"  错误数     : {error_count}")
        sys.exit(1)
    else:
        print("校验通过")
        print()
        print("\n".join(results))
        print()
        print("--- 汇总 ---")
        print(f"  检查文件数 : {total_files}")
        print(f"  条目总数   : {total_entries}")
        sys.exit(0)


if __name__ == "__main__":
    main()
