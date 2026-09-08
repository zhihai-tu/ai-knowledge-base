"""LangGraph 工作流的共享状态定义。

:class:`KBState` 以 :class:`typing.TypedDict` 描述知识采集流水线在
LangGraph ``StateGraph`` 中流转的全部字段。各节点按「报告式通信」原则
读写状态：字段是结构化摘要（可序列化的结构化报告），而不是未经加工的
原始数据，避免在节点间搬运大段原文。

典型流水线: plan → collect → analyze → organize → review → revise 审核
重做循环；未通过且 ``iteration < plan.max_iterations``（无 plan 时默认
3）时按反馈改写 analyses 后重审，达到上限仍未通过时转 human_flag 人工
介入（异常终点）。

用法示例::

    from workflows.state import KBState

    def collect_node(state: KBState) -> dict:
        return {"sources": collect_sources()}
"""

from typing import Any, TypedDict


class KBState(TypedDict):
    """规划 → 采集 → 分析 → 整理 → 审核 流水线的共享状态。

    LangGraph StateGraph 中，各节点返回本次要更新的字段，LangGraph
    默认以覆盖（overwrite）方式合并进共享状态。
    """

    plan: dict
    """Planner 节点输出的执行策略（结构化摘要）。

    由 planner_node 以 ``{"plan": {...}}`` 写入，下游 collector /
    organizer / reviewer 通过 ``state["plan"]`` 读取并按策略执行。
    字段：``tier``（lite/standard/full）、``target_count``、
    ``per_source_limit``、``relevance_threshold``、``max_iterations``、
    ``rationale``（选档理由），见 workflows/planner.py。
    """

    sources: list[dict[str, Any]]
    """采集到的原始数据。

    每个元素为一条采集报告（结构化摘要），如
    ``{"source_type": "github", "title": "...", "source_url": "...",
    "summary": "...", "collected_at": "..."}``。
    """

    analyses: list[dict[str, Any]]
    """LLM 分析后的结构化结果。

    每个元素对应一条 source 的分析报告，如
    ``{"source_id": "...", "summary": "...", "tags": [...],
    "category": "...", "score": 8, "score_reason": "..."}``。
    """

    articles: list[dict[str, Any]]
    """格式化、去重后的知识条目（最终输出）。

    每个元素为一条符合知识库 JSON 规范的条目（见 AGENTS.md），如
    ``{"id": "...", "title": "...", "source_url": "...", "tags": [...],
    "status": "review", ...}``。整理节点每次整体重建该列表（覆盖而非
    追加），避免审核重做轮次产生重复条目。
    """

    review_feedback: str
    """审核反馈意见。

    字符串形式的结构化反馈（改进建议），由审核节点写入；审核未通过时
    作为下一轮分析/整理节点的修正依据。
    """

    review_passed: bool
    """审核是否通过。

    布尔值；True 时进入 save 结束，False 且未达
    ``plan.max_iterations`` 时进入下一轮重做。
    """

    iteration: int
    """当前审核循环次数。

    从 0 开始递增，上限取 ``state["plan"]["max_iterations"]``（无 plan
    时默认 3）。未通过且未达上限时回 revise 重做；达到上限仍未通过时
    由路由转向 human_flag 人工介入（异常终点），不再强制通过。
    """

    needs_human_review: bool
    """是否需要人工介入。

    布尔值；审核循环超过上限时由 HumanFlag 节点置为 True，作为异常终点
    标记（问题条目已写到 knowledge/pending_review/，不进入主知识库）。
    """

    cost_tracker: dict[str, Any]
    """Token 用量追踪（结构化摘要）。

    以 ``"provider/model"`` 为键的汇总报告，如
    ``{"deepseek/deepseek-v4-flash": {"prompt_tokens": 1000,
    "completion_tokens": 200, "calls": 2, "cost_usd": 0.0006}}``。
    各节点整体覆盖当前累计值（读取旧值、并入本次增量后写回）。
    """
