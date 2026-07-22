#!/usr/bin/env python3
"""知识条目 5 维度质量评分。

用法:
    python hooks/check_quality.py <json_file> [json_file2 ...]
    python hooks/check_quality.py knowledge/**/*.json

存在 C 级条目返回 1，否则返回 0。
"""

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── 数据结构 ──────────────────────────────────────────────────────

@dataclass
class DimensionScore:
    name: str
    score: float
    max_score: float
    detail: str = ""


@dataclass
class QualityReport:
    file: str
    total: float
    grade: str
    dimensions: list[DimensionScore] = field(default_factory=list)


# ── 常量 ──────────────────────────────────────────────────────────

GRADE_THRESHOLDS = [
    ("A", 80),
    ("B", 60),
    ("C", 0),
]

STANDARD_TAGS = {
    "agent", "tool", "coding", "framework", "memory", "training",
    "voice", "inference", "llm", "transformers", "transformer",
    "tutorial", "fintech", "finance", "quant", "stock-analysis",
    "aiops", "monitoring", "kubernetes", "ebpf",
    "video-generation", "video-editing", "image-generation",
    "computer-vision", "visualization", "design",
    "moe", "embodied-ai", "pretraining",
    "self-supervised", "spatial-perception", "robotics",
    "claude", "claude-code",
    "multi-agent", "orchestration", "ai-agent", "ai-agents",
    "evaluation", "benchmarking",
    "ai-security", "compliance",
    "wechat", "content-analysis", "knowledge-base",
    "interpretability", "mechanistic-interpretability",
    "ai-writing", "chinese", "prompt-engineering",
    "apple-silicon", "mlx", "local-deployment",
    "ffmpeg",
    "agent", "tool", "coding",
}

BUZZWORDS_CN = [
    "赋能", "抓手", "闭环", "打通", "全链路",
    "底层逻辑", "颗粒度", "对齐", "拉通", "沉淀",
    "强大的", "革命性的",
]

BUZZWORDS_EN = [
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
    "state-of-the-art", "bleeding-edge", "industry-leading",
    "paradigm-shift", "world-class", "best-in-class",
]

TECH_KEYWORDS = [
    "AI", "LLM", "大模型", "深度学习", "机器学习",
    "transformer", "神经网络", "自然语言处理",
    "computer vision", "计算机视觉", "多模态",
    "agent", "multi-agent", "RAG", "检索增强",
    "fine-tuning", "微调", "推理", "inference",
    "embedding", "向量", "knowledge graph", "知识图谱",
    "分布式", "分布式系统", "微服务", "architecture",
    "kubernetes", "docker", "云原生", "devops",
    "GPU", "CUDA", "边缘计算", "端侧",
]

BAR_WIDTH = 30


# ── 工具函数 ──────────────────────────────────────────────────────

def grade_label(total: float) -> str:
    for g, threshold in GRADE_THRESHOLDS:
        if total >= threshold:
            return g
    return "C"


def progress_bar(percent: float) -> str:
    filled = int(BAR_WIDTH * percent / 100)
    bar = "█" * filled + "░" * (BAR_WIDTH - filled)
    return f"[{bar}] {percent:.0f}%"


def resolve_paths(raw_args: list[str]) -> list[Path]:
    paths: list[Path] = []
    for arg in raw_args:
        if "*" in arg:
            paths.extend(sorted(Path().glob(arg)))
        else:
            paths.append(Path(arg))
    return paths


# ── 维度评分函数 ──────────────────────────────────────────────────

def score_summary(item: dict) -> DimensionScore:
    max_s = 25
    text = item.get("summary", "")
    if not isinstance(text, str):
        return DimensionScore("摘要质量", 0, max_s, "缺少摘要")

    length = len(text)
    if length < 20:
        base = 0.0
    elif length < 50:
        base = 10.0 + (length - 20) * (10.0 / 30)
    else:
        base = 20.0

    bonus = 0.0
    text_lower = text.lower()
    for kw in TECH_KEYWORDS:
        if kw.lower() in text_lower:
            bonus = 5.0
            break

    total = min(max_s, base + bonus)
    detail_parts = [f"{length}字"]
    if bonus > 0:
        detail_parts.append("含技术关键词 +5")
    detail_parts.append(f"→ {total:.1f}分")
    return DimensionScore("摘要质量", total, max_s, "，".join(detail_parts))


def score_depth(item: dict) -> DimensionScore:
    max_s = 25
    raw = item.get("score")
    if raw is None:
        meta = item.get("metadata")
        if isinstance(meta, dict):
            raw = meta.get("score")
    if raw is None:
        return DimensionScore("技术深度", 0, max_s, "无 score 字段")
    if not isinstance(raw, (int, float)):
        return DimensionScore("技术深度", 0, max_s, f"score 类型错误: {type(raw).__name__}")

    s = max(1, min(10, float(raw)))
    total = s * 2.5
    return DimensionScore("技术深度", total, max_s, f"score={s} → {total:.1f}分")


def score_format(item: dict) -> DimensionScore:
    max_s = 20
    points = 0.0
    details: list[str] = []

    checks = [
        ("id", isinstance(item.get("id"), str)),
        ("title", isinstance(item.get("title"), str)),
        ("source_url", isinstance(item.get("source_url"), str)),
        ("status", isinstance(item.get("status"), str)),
    ]
    for name, ok in checks:
        if ok:
            points += 4
            details.append(f"{name} ✓")
        else:
            details.append(f"{name} ✗")

    ts_ok = False
    for ts_field in ("collected_at", "analyzed_at", "published_at"):
        v = item.get(ts_field)
        if isinstance(v, str) and v.strip():
            ts_ok = True
            break
    if ts_ok:
        points += 4
        details.append("时间戳 ✓")
    else:
        details.append("时间戳 ✗")

    return DimensionScore("格式规范", points, max_s, "，".join(details))


def score_tags(item: dict) -> DimensionScore:
    max_s = 15
    tags = item.get("tags")
    if not isinstance(tags, list) or len(tags) == 0:
        return DimensionScore("标签精度", 0, max_s, "无标签")

    count = len(tags)
    valid = sum(1 for t in tags if isinstance(t, str) and t in STANDARD_TAGS)
    invalid = count - valid

    if 1 <= count <= 3 and invalid == 0:
        total = 15.0
    elif 1 <= count <= 3 and invalid > 0:
        total = 10.0
    else:
        total = 5.0

    detail = f"{count}个标签，{valid}个标准，{invalid}个非标准 → {total:.0f}分"
    return DimensionScore("标签精度", total, max_s, detail)


def score_buzzwords(item: dict) -> DimensionScore:
    max_s = 15
    text = ""
    for field in ("summary", "title"):
        v = item.get(field)
        if isinstance(v, str):
            text += v + " "

    if not text.strip():
        return DimensionScore("空洞词检测", max_s, max_s, "无内容可检")

    found: list[str] = []
    text_lower = text.lower()
    for bw in BUZZWORDS_CN:
        if bw in text:
            found.append(bw)
    for bw in BUZZWORDS_EN:
        if bw in text_lower:
            found.append(bw)

    found = list(dict.fromkeys(found))
    deduction = min(max_s, len(found) * 3)
    total = max(0, max_s - deduction)

    if not found:
        detail = "未检出空洞词 ✓"
    else:
        detail = f"检出 {len(found)} 个: {'，'.join(found)}，扣 {deduction} 分 → {total:.0f}分"
    return DimensionScore("空洞词检测", total, max_s, detail)


# ── 单文件评分 ────────────────────────────────────────────────────

def evaluate(item: dict) -> QualityReport:
    dims = [
        score_summary(item),
        score_depth(item),
        score_format(item),
        score_tags(item),
        score_buzzwords(item),
    ]
    total = sum(d.score for d in dims)
    report = QualityReport(
        file=item.get("id", "unknown"),
        total=round(total, 1),
        grade=grade_label(total),
        dimensions=dims,
    )
    return report


# ── 主流程 ────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python hooks/check_quality.py <json_file> [json_file2 ...]")
        sys.exit(1)

    files = resolve_paths(sys.argv[1:])

    all_reports: list[tuple[Path, list[QualityReport]]] = []
    total_entries = 0
    c_count = 0

    for idx, path in enumerate(files):
        if not path.exists():
            print(f"\r{' ' * 80}\r", end="")
            print(f"✗ {path}: 文件不存在")
            continue

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception) as e:
            print(f"\r{' ' * 80}\r", end="")
            print(f"✗ {path}: JSON 解析失败 - {e}")
            continue

        items = data if isinstance(data, list) else [data]
        file_reports: list[QualityReport] = []

        for item in items:
            if not isinstance(item, dict):
                continue
            report = evaluate(item)
            file_reports.append(report)
            if report.grade == "C":
                c_count += 1

        all_reports.append((path, file_reports))
        total_entries += len(file_reports)

        percent = (idx + 1) / len(files) * 100
        sys.stdout.write(f"\r  正在评分... {progress_bar(percent)}")
        sys.stdout.flush()

    print()

    # 输出结果
    for path, reports in all_reports:
        for r in reports:
            total_color = "✗" if r.grade == "C" else ("!" if r.grade == "B" else "✓")
            print(f"\n{total_color} {path.name} (id={r.file})  总分: {r.total}/100  等级: {r.grade}")
            for d in r.dimensions:
                bar_filled = int(10 * d.score / d.max_score) if d.max_score > 0 else 0
                dim_bar = "█" * bar_filled + "░" * (10 - bar_filled)
                print(f"    {d.name:　<6} [{dim_bar}] {d.score:.1f}/{d.max_score}  {d.detail}")

    # 汇总
    print("\n" + "=" * 60)
    print("  汇总")
    print("=" * 60)
    print(f"  检查文件数 : {len(files)}")
    print(f"  条目总数   : {total_entries}")
    print(f"  C 级条目   : {c_count}")

    if c_count > 0:
        print("\n  存在 C 级条目，质量不达标。")
        sys.exit(1)
    else:
        print("\n  所有条目均达到 B 级及以上。")
        sys.exit(0)


if __name__ == "__main__":
    main()
