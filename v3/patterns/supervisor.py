"""Supervisor 监督模式：Worker 产出 + Supervisor 审核 + 反馈重做循环。

流程：

1. Worker Agent 接收任务，输出 JSON 格式的分析报告；
2. Supervisor Agent 从准确性 / 深度 / 格式三个维度（各 1-10）审核，
   输出 JSON: ``{"passed": bool, "score": int, "feedback": str}``；
3. 评分 ``>= 7`` 判定通过，直接返回结果；
   否则将审核反馈带回，要求 Worker 重做（最多 ``max_retries`` 轮）；
   重做次数耗尽仍未通过时强制返回并附带 warning。

统一入口::

    from patterns.supervisor import supervisor

    result = supervisor("请分析 RAG 检索增强生成的优缺点")
    # -> {"output": {...}, "attempts": 2, "final_score": 8}
"""

import json
import logging
import os
import re
import sys

# `python patterns/supervisor.py` 直接运行时，sys.path[0] 是 patterns/，
# 需把项目根目录加入 sys.path 才能导入同级 workflows 包。
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

from workflows.model_client import chat_with_retry, create_provider

logger = logging.getLogger(__name__)

PASS_SCORE = 7

WORKER_SYSTEM = (
    "你是一名资深 AI 数据分析师 Worker。请针对给定的任务撰写一份专业的分析报告。\n"
    "必须以严格的 JSON 对象输出，不要输出任何非 JSON 内容（包括 markdown 代码块标记）。\n"
    'JSON 结构（所有字段都必须有）：\n'
    '{\n'
    '  "title": "报告标题（简短中文）",\n'
    '  "summary": "对任务的总体分析，至少 150 字，包含核心观点与论据",\n'
    '  "key_points": ["要点1", "要点2", "要点3"],\n'
    '  "conclusion": "明确的分析结论"\n'
    '}\n'
    "报告必须内容充实、结论清晰、全部使用中文。"
)

SUPERVISOR_SYSTEM = (
    "你是质量审核 Supervisor，负责审查 Worker 提交的分析报告。\n"
    "请从以下三个维度评分（各 1-10）：\n"
    "1. 准确性 accuracy：信息是否准确、结论是否有依据；\n"
    "2. 深度 depth：分析是否深入、是否有洞察、覆盖是否充分；\n"
    "3. 格式 format：是否为合法 JSON 对象、字段是否完整、结构是否符合要求。\n"
    "最终 score = round((accuracy + depth + format) / 3)。\n"
    "passed = (score >= 7)。\n"
    "只输出一个 JSON 对象，不要输出任何其它内容：\n"
    '{"passed": true或false, "score": 整数, "feedback": "具体改进建议(中文)"}'
)

_provider = None


def _get_provider():
    """懒加载全局 LLM Provider 单例。"""
    global _provider
    if _provider is None:
        _provider = create_provider()
    return _provider


def _parse_json(text: str) -> tuple[object | None, str | None]:
    """解析模型输出的 JSON，容忍代码块标记与前后噪声，返回 (对象, 错误信息)。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if -1 < start < end:
        try:
            return json.loads(text[start : end + 1]), None
        except json.JSONDecodeError as exc:
            return None, str(exc)
    return None, "未找到 JSON 对象"


def _synthetic_review(feedback: str) -> dict:
    """构造一个审核失败的评审结果（用于 LLM 调用失败的降级处理）。"""
    return {"passed": False, "score": 0, "feedback": feedback}


def _run_worker(task: str, entries: list[dict]) -> str:
    """调用 Worker 生成分析报告，返回原始文本；LLM 异常向上抛出。"""
    messages: list[dict[str, str]] = [
        {"role": "system", "content": WORKER_SYSTEM},
        {"role": "user", "content": f"任务：{task}"},
    ]
    if entries:
        redo_parts = [
            f"第 {i + 1} 版输出：\n{e['worker_text']}\n"
            f"审核反馈：{e['review']['feedback']}"
            for i, e in enumerate(entries)
        ]
        redo_parts.append(
            "请根据上述审核反馈改进上一版报告，重新输出符合要求的 JSON。"
        )
        messages.append({"role": "user", "content": "\n\n".join(redo_parts)})

    response = chat_with_retry(_get_provider(), messages, temperature=0.4)
    return response.content


def _run_supervisor(task: str, worker_text: str) -> dict:
    """调用 Supervisor 审核 Worker 报告，返回规范化的评审结果。"""
    prompt = f"任务：{task}\n\nWorker 提交的分析报告：\n{worker_text}"
    try:
        response = chat_with_retry(
            _get_provider(),
            [
                {"role": "system", "content": SUPERVISOR_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Supervisor 调用失败: %s", exc)
        return _synthetic_review(f"Supervisor 审核调用失败: {exc}")

    review, err = _parse_json(response.content)
    if not isinstance(review, dict):
        return _synthetic_review(f"Supervisor 输出非法 JSON: {err or '非对象'}")
    score = review.get("score")
    if not isinstance(score, (int, float)):
        return _synthetic_review("Supervisor 输出缺少 score 字段")
    score = min(max(int(round(float(score))), 1), 10)
    feedback = str(review.get("feedback") or "").strip() or "无反馈"
    return {"passed": score >= PASS_SCORE, "score": score, "feedback": feedback}


def _worker_report(worker_text: str) -> dict:
    """把 Worker 文本解析为最终报告对象；解析失败时返回降级结构。"""
    parsed, err = _parse_json(worker_text)
    if isinstance(parsed, dict):
        return parsed
    return {"_parse_error": err or "输出不是合法 JSON 对象", "raw": worker_text}


def _build_rounds(entries: list[dict]) -> list[dict]:
    """从审核记录汇总每轮的 (轮次, 得分, 是否通过, 反馈)。"""
    return [
        {
            "attempt": i + 1,
            "score": e["review"]["score"],
            "passed": e["review"]["passed"],
            "feedback": e["review"]["feedback"],
        }
        for i, e in enumerate(entries)
    ]


def _preview(obj, limit: int = 120) -> str:
    """把输出对象压缩为单行摘要，超出 limit 时截断加省略号。"""
    text = "None" if obj is None else json.dumps(obj, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def supervisor(task: str, max_retries: int = 3) -> dict:
    """Supervisor 监督模式统一入口。

    Args:
        task: 交给 Worker 的分析任务。
        max_retries: 重做轮数上限（默认 3，即最多 1+3=4 次 Worker 产出）。

    Returns:
        dict，包含：
        - ``output``: Worker 最终的分析报告（JSON 对象）；
        - ``attempts``: 实际 Worker 产出次数；
        - ``final_score``: 最后一次审核得分（1-10）；
        - ``rounds``: 每轮审核记录，含 attempt / score / passed / feedback；
        - ``warning``: 可选，重做轮数耗尽强制返回时的提示。
    """
    task = (task or "").strip()
    if not task:
        return {
            "output": None,
            "attempts": 0,
            "final_score": 0,
            "rounds": [],
            "warning": "任务为空，未执行。",
        }

    entries: list[dict] = []
    last_score = 0
    for _ in range(max_retries + 1):
        attempt = len(entries) + 1
        try:
            worker_text = _run_worker(task, entries)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Worker 调用失败（第 %d 次）: %s", attempt, exc)
            worker_text = ""
            entries.append(
                {"worker_text": "", "review": _synthetic_review(f"Worker 调用失败: {exc}")}
            )
            last_score = 0
            continue

        review = _run_supervisor(task, worker_text)
        last_score = review["score"]
        entries.append({"worker_text": worker_text, "review": review})
        logger.info(
            "Supervisor 第 %d 轮审核: score=%d passed=%s",
            attempt, last_score, review["passed"],
        )
        if review["passed"]:
            return {
                "output": _worker_report(worker_text),
                "attempts": attempt,
                "final_score": last_score,
                "rounds": _build_rounds(entries),
            }

    return {
        "output": _worker_report(entries[-1]["worker_text"]),
        "attempts": len(entries),
        "final_score": last_score,
        "rounds": _build_rounds(entries),
        "warning": (
            f"超过 {max_retries} 轮重做仍未达到 {PASS_SCORE} 分（理想值），已强制返回。"
            f"最后审核反馈: {entries[-1]['review']['feedback']}"
        ),
    }


def main() -> None:
    """测试入口：支持命令行传入任务，否则跑内置样例。"""
    import sys

    # 控制台保持干净的可读输出，INFO 及以下日志（httpx / model_client）静默。
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        task = (
            "请分析大语言模型 Context Window 扩展技术（RoPE 外推、位置插值、"
            "YaRN 等）的现状、主要方案与各自优缺点。"
        )

    result = supervisor(task)
    print("=" * 50)
    print("Supervisor 监督模式测试")
    print("=" * 50)
    print(f"[任务] {task}")
    for r in result["rounds"]:
        print(f"  第 {r['attempt']} 轮审核: 得分 {r['score']}/10")
    print()
    print("最终结果:")
    print(f"  审核轮次: {result['attempts']}")
    print(f"  最终得分: {result['final_score']}/10")
    print(f"  输出预览: {_preview(result['output'])}")
    if result.get("warning"):
        print(f"  警告: {result['warning']}")


if __name__ == "__main__":
    main()