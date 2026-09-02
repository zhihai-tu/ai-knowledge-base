"""HumanFlag Agent — 人工介入节点（异常终点）。

审核循环超过上限仍未通过时，说明问题不在「质量」而在「数据」，需要人工判断。
本节点把问题条目连同最后反馈写入 ``knowledge/pending_review/`` 独立目录，
不污染主知识库 articles/。

用法示例::

    from workflows.human_flag import human_flag_node

    updates = human_flag_node(state)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from workflows.state import KBState

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PENDING_DIR = PROJECT_ROOT / "knowledge" / "pending_review"


def human_flag_node(state: KBState) -> dict:
    """审核循环超过上限时的兜底 —— 写入 pending_review/ 目录。

    把当前 analyses、已消耗的迭代次数与最后一条审核反馈落盘，
    返回 ``{"needs_human_review": True}`` 标记人工介入（异常终点）。
    """
    analyses = state.get("analyses") or []
    iteration = state.get("iteration", 0)
    feedback = state.get("review_feedback") or ""

    print(f"[HumanFlag] ⚠️ 达到 {iteration} 次审核仍未通过")
    print(f"[HumanFlag] 最后反馈: {feedback[:200]}")

    PENDING_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    filepath = PENDING_DIR / f"pending-{today}.json"
    with filepath.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": today,
                "iterations_used": iteration,
                "last_feedback": feedback,
                "analyses": analyses,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"[HumanFlag] 已保存到 {filepath}")
    return {"needs_human_review": True}