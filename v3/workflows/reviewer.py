"""知识库审核节点：对 analyses 做 5 维度加权评分。

review_node 审核的对象是 ``state["analyses"]``（不是 articles，articles 在
organize 节点之后才存在）。评分维度与权重：

- summary_quality 摘要质量: 25%
- technical_depth 技术深度: 25%
- relevance 相关性: 20%
- originality 原创性: 15%
- formatting 格式规范: 15%

加权总分由代码重算（不信任模型算术），``>= 7.0`` 判定通过；审核全部
analyses；LLM 调用失败时自动通过，不阻塞流水线。

用法示例::

    from workflows.reviewer import review_node

    updates = review_node(state)
"""

import json
import logging

from workflows.model_client import (
    LLMProvider,
    accumulate_usage,
    chat_json,
    create_provider,
)
from workflows.state import KBState, MAX_ITERATIONS

logger = logging.getLogger(__name__)

REVIEW_TEMPERATURE = 0.1   # 低温度保证评分一致性
PASS_SCORE = 7.0           # 加权总分 >= 该值判定通过

WEIGHTS = {
    "summary_quality": 0.25,
    "technical_depth": 0.25,
    "relevance": 0.20,
    "originality": 0.15,
    "formatting": 0.15,
}

REVIEW_SYSTEM = (
    "你是知识库质量审核员。请从以下 5 个维度为给定的分析报告打分，每维 1-10"
    "（允许小数）：\n"
    "1. summary_quality 摘要质量：摘要是否准确、清晰、完整（150-300字）；\n"
    "2. technical_depth 技术深度：是否体现项目的技术内涵与关键亮点；\n"
    "3. relevance 相关性：与 AI/LLM/Agent 领域的相关程度；\n"
    "4. originality 原创性：观点、亮点或角度的独特性；\n"
    "5. formatting 格式规范：category 属于 llm|agent|rag|inference|training|tool，"
    "tags 为 1-3 个英文等字段是否规范合规。\n"
    "总分由系统按权重计算，你只需给出各维度分数，不要计算总分。\n"
    "只输出一个 JSON 对象，不要任何额外文字：\n"
    '{"scores": {"summary_quality": 8, "technical_depth": 7, "relevance": 9, '
    '"originality": 6, "formatting": 8}, '
    '"feedback": "具体改进建议(中文)"}'
)

_provider: LLMProvider | None = None


def _get_provider() -> LLMProvider:
    """懒加载全局 LLM Provider 单例。"""
    global _provider
    if _provider is None:
        _provider = create_provider()
    return _provider


def _to_score(value) -> float:
    """把任意值稳健转换为 1-10 分；缺失或非法返回 0（bool 视为非法）。"""
    if isinstance(value, bool):
        return 0.0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(1.0, min(10.0, v))


def _compact(analysis: dict) -> dict:
    """把一条分析报告压缩为审核所需的精简字段，控制 token 消耗。"""
    return {
        "title": analysis.get("title", ""),
        "source_url": analysis.get("source_url", ""),
        "summary": analysis.get("summary", ""),
        "tags": analysis.get("tags") or [],
        "category": analysis.get("category"),
        "score": analysis.get("score"),
        "score_reason": analysis.get("score_reason", ""),
    }


def _build_prompt(analyses: list[dict]) -> str:
    items = json.dumps(
        [_compact(a) for a in analyses], ensure_ascii=False, indent=2
    )
    return f"请审核以下 {len(analyses)} 条分析报告并输出 JSON：\n{items}"


def _weighted_overall(scores: dict) -> dict[str, float]:
    """用代码重算加权总分与各维度得分，不信任模型返回的总分。"""
    per_dim = {dim: _to_score(scores.get(dim)) for dim in WEIGHTS}
    overall = sum(WEIGHTS[d] * per_dim[d] for d in WEIGHTS)
    return {"overall": overall, "per_dim": per_dim}


def review_node(state: KBState) -> dict:
    """节点 4：对 analyses 做 5 维度加权审核；LLM 失败自动通过。

    - 加权总分 ``>= PASS_SCORE`` 判定通过，未通过时 iteration 递增供重做循环；
      通过或强制通过时保持当前值。
    - ``iteration >= MAX_ITERATIONS`` 时强制通过，避免重做死循环。
    - 调用失败 / 输出缺少 scores 时自动通过（不阻塞流程）。
    """
    iteration = state.get("iteration", 0)
    analyses = state.get("analyses") or []
    base_tracker = state.get("cost_tracker") or {}
    target = analyses
    print(
        f"[ReviewNode] 5维度加权审核（iteration={iteration}，"
        f"审核 {len(target)}/{len(analyses)} 条）..."
    )

    if iteration >= MAX_ITERATIONS:
        print("[ReviewNode] 已达最大审核轮次，强制通过。")
        return {
            "review_passed": True,
            "review_feedback": "已达最大审核轮次，强制通过。",
            "iteration": iteration,
            "cost_tracker": base_tracker,
        }

    if not target:
        print("[ReviewNode] 无条目待审核，通过。")
        return {
            "review_passed": True,
            "review_feedback": "无条目待审核。",
            "iteration": iteration,
            "cost_tracker": base_tracker,
        }

    provider = _get_provider()
    try:
        result, usage = chat_json(
            _build_prompt(target),
            system=REVIEW_SYSTEM,
            temperature=REVIEW_TEMPERATURE,
            provider=provider,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ReviewNode 审核调用失败，自动通过: %s", exc)
        print(f"[ReviewNode] 审核调用失败，自动通过: {exc}")
        return {
            "review_passed": True,
            "review_feedback": f"审核调用失败，自动通过: {exc}",
            "iteration": iteration,
            "cost_tracker": base_tracker,
        }
    tracker = accumulate_usage(base_tracker, usage, provider)

    scores = result.get("scores") if isinstance(result, dict) else None
    if not isinstance(scores, dict) or not scores:
        logger.warning("ReviewNode 审核输出缺少 scores，自动通过")
        print("[ReviewNode] 审核输出缺少 scores，自动通过。")
        return {
            "review_passed": True,
            "review_feedback": "审核输出缺少 scores 字段，自动通过。",
            "iteration": iteration,
            "cost_tracker": tracker,
        }

    ranked = _weighted_overall(scores)
    overall = ranked["overall"]
    per_dim = ranked["per_dim"]
    passed = overall >= PASS_SCORE

    model_feedback = str(result.get("feedback") or "").strip()
    dims_desc = ", ".join(f"{d}={per_dim[d]:.1f}" for d in WEIGHTS)
    feedback = (
        f"整体加权分 {overall:.2f}/10（通过线 {PASS_SCORE:.1f}）| "
        f"各维度: {dims_desc}"
        + (f" | 模型反馈: {model_feedback}" if model_feedback else "")
    )
    print(f"[ReviewNode] 加权总分 {overall:.2f}/10 passed={passed}")
    return {
        "review_passed": passed,
        "review_feedback": feedback,
        "iteration": iteration if passed else iteration + 1,
        "cost_tracker": tracker,
    }