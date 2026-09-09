"""知识库修订节点：根据审核反馈改写 analyses。

revise_node 读取 ``state["analyses"]`` 与 ``state["review_feedback"]``，
把反馈注入修订 prompt，调用 LLM 返回改写后的 analyses 列表。
temperature=0.4 允许创造性改写；analyses 或 feedback 为空时跳过
（返回 ``{}``，不消耗 LLM）。

用法示例::

    from workflows.reviser import revise_node

    updates = revise_node(state)
"""

import json
import logging

from tests.cost_guard import BudgetExceededError
from workflows.model_client import (
    LLMProvider,
    accumulate_usage,
    chat_json,
    create_provider,
)
from workflows.state import KBState

logger = logging.getLogger(__name__)

REVISE_TEMPERATURE = 0.4   # 允许创造性改写

REVISE_SYSTEM = (
    "你是知识库修订员。根据审核反馈修正给定的分析报告 JSON 数组。\n"
    "要求：保留全部条目与每个条目的 source_id / source_url / title 不变，"
    "只修改内容（summary / tags / category / score / score_reason 等），"
    "结构与字段名不变。\n"
    "只输出修正后的完整 JSON 数组，不要任何额外文字。"
)

_provider: LLMProvider | None = None


def _get_provider() -> LLMProvider:
    """懒加载全局 LLM Provider 单例。"""
    global _provider
    if _provider is None:
        _provider = create_provider()
    return _provider


def _build_prompt(analyses: list[dict], feedback: str) -> str:
    items = json.dumps(analyses, ensure_ascii=False, indent=2)
    return (
        f"以下是 {len(analyses)} 条分析报告 JSON 数组：\n{items}\n\n"
        f"审核反馈：\n{feedback}\n\n"
        "请根据反馈逐条修正，输出修正后的完整 JSON 数组。"
    )


def _merge_improved(analyses: list[dict], improved: list[dict]) -> list[dict]:
    """按 source_id 合并改写结果：未返回的条目沿用原内容，保持原顺序。"""
    revised = {}
    for item in improved:
        if isinstance(item, dict) and item.get("source_id"):
            revised[item["source_id"]] = item
    result = []
    for a in analyses:
        item = revised.get(a.get("source_id"))
        if item is None:
            result.append(a)
            continue
        merged = {**a, **item}
        merged["source_id"] = a["source_id"]
        merged["source_url"] = a["source_url"]
        result.append(merged)
    return result


def revise_node(state: KBState) -> dict:
    """修订节点：根据审核反馈调用 LLM 改写 analyses。

    - analyses 或 review_feedback 为空时跳过（返回 ``{}``）。
    - temperature=0.4 允许创造性改写。
    - 普通调用失败或输出非法时保留原 analyses；超预算异常向上抛出。
    - token 用量累计进 ``state.cost_tracker``。
    """
    analyses = state.get("analyses") or []
    feedback = (state.get("review_feedback") or "").strip()
    if not analyses or not feedback:
        print("[ReviseNode] analyses 或反馈为空，跳过修订。")
        return {}

    print("--- revise 开始 ---")
    print(f"[ReviseNode] 根据审核反馈改写 {len(analyses)} 条分析...")
    provider = _get_provider()
    base_tracker = state.get("cost_tracker") or {}
    try:
        improved, usage = chat_json(
            _build_prompt(analyses, feedback),
            system=REVISE_SYSTEM,
            temperature=REVISE_TEMPERATURE,
            provider=provider,
            node_name="revise",
        )
    except BudgetExceededError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("ReviseNode 修订调用失败，保留原 analyses: %s", exc)
        print(f"[ReviseNode] 修订调用失败，保留原 analyses: {exc}")
        print("--- revise 完成 ---")
        return {"analyses": analyses, "cost_tracker": base_tracker}
    tracker = accumulate_usage(base_tracker, usage, provider)

    if not isinstance(improved, list):
        logger.warning("ReviseNode 修订输出非法，保留原 analyses")
        print("[ReviseNode] 修订输出非法，保留原 analyses。")
        print("--- revise 完成 ---")
        return {"analyses": analyses, "cost_tracker": tracker}

    result = _merge_improved(analyses, improved)
    print(f"[ReviseNode] 修订完成: {len(result)} 条")
    print("--- revise 完成 ---")
    return {"analyses": result, "cost_tracker": tracker}
