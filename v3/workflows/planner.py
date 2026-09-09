"""采集策略规划节点：按目标采集量输出三档执行策略。

planner_node 作为流水线首个节点，根据 target_count 选择 lite / standard /
full 三档策略写入 ``state["plan"]``；下游 collector / organizer / reviewer
通过 ``state["plan"]`` 读取执行参数（per_source_limit、relevance_threshold、
max_iterations）。

用法示例::

    from workflows.planner import planner_node

    updates = planner_node(state)
"""

import os

from workflows.state import KBState


def plan_strategy(target_count: int | None = None) -> dict:
    """按目标采集量选择策略档位，返回策略 dict。

    - ``target_count < 10`` → lite：per_source_limit=5, relevance_threshold=0.7,
      max_iterations=1
    - ``10 <= target_count < 20`` → standard：10, 0.5, 2
    - ``target_count >= 20`` → full：20, 0.4, 3

    ``target_count`` 缺省时读环境变量 ``PLANNER_TARGET_COUNT``（默认 10）。
    """
    if target_count is None:
        raw = os.environ.get("PLANNER_TARGET_COUNT")
        target_count = int(raw) if raw else 10

    if target_count < 10:
        return {
            "tier": "lite",
            "target_count": target_count,
            "per_source_limit": 5,
            "relevance_threshold": 0.7,
            "max_iterations": 1,
            "rationale": (
                "目标量小（<10 条），宁缺毋滥：收紧单源上限（5）与相关度"
                "门槛（0.7）保质量；审核最多 1 轮，未通过即转人工，省 token。"
            ),
        }
    if target_count < 20:
        return {
            "tier": "standard",
            "target_count": target_count,
            "per_source_limit": 10,
            "relevance_threshold": 0.5,
            "max_iterations": 2,
            "rationale": (
                "目标量适中（10-19 条），质量与数量均衡：单源上限（10）与"
                "相关度门槛（0.5）取中；审核最多 2 轮（1 轮重做机会）。"
            ),
        }
    return {
        "tier": "full",
        "target_count": target_count,
        "per_source_limit": 20,
        "relevance_threshold": 0.4,
        "max_iterations": 3,
        "rationale": (
            "目标量大（>=20 条），先保数量：放宽单源上限（20）与相关度"
            "门槛（0.4）；审核最多 3 轮（2 轮重做机会）打磨质量。"
        ),
    }


def planner_node(state: KBState) -> dict:
    """节点 0：规划采集策略，返回 ``{"plan": plan}`` 写入共享状态。"""
    print("--- plan 开始 ---")
    plan = plan_strategy()
    print(
        f"[PlannerNode] tier={plan['tier']} target={plan['target_count']} "
        f"per_source_limit={plan['per_source_limit']} "
        f"relevance_threshold={plan['relevance_threshold']} "
        f"max_iterations={plan['max_iterations']}"
    )
    print("--- plan 完成 ---")
    return {"plan": plan}
