"""LangGraph 工作流编排。

节点连边与 ``build_graph()`` 一致（START 表示入口）::

    START -> plan -> collect -> analyze -> organize -> review
                                                        |
                                                        +-- [1] -> save -> END
                                                        |
                                                        +-- [2] -> revise -> review
                                                        |
                                                        +-- [3] -> human_flag -> END

review 的出边由 ``route_after_review`` 选择，每次只走一条：

- [1] 审核通过（review_passed 为真）时进入 save，再到 END；优先于次数判断。
- [2] 审核未通过且 ``iteration < max_iterations`` 时进入 revise，随后直接
  回到同一个 review 节点再次审核，形成循环，不重新经过 analyze 或 organize。
- [3] 审核未通过且 ``iteration >= max_iterations`` 时进入 human_flag，
  标记人工介入后到 END；此分支不经过 save。

``max_iterations`` 取自 ``plan.max_iterations``，未提供时默认 3。

用法::

    from workflows.graph import build_graph

    app = build_graph()
    result = app.invoke({"sources": [], "iteration": 0})
"""

from langgraph.graph import END, StateGraph

import os
import sys
import textwrap
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflows.human_flag import human_flag_node
from workflows.model_client import get_cost_guard
from workflows.nodes import analyze_node, collect_node, organize_node, save_node
from workflows.reviewer import review_node
from workflows.reviser import revise_node
from workflows.planner import planner_node
from workflows.state import KBState


def route_after_review(state: KBState) -> str:
    """review 之后的三路分支：通过 → save；未通过且 ``iteration <
    plan.max_iterations``（无 plan 默认 3）→ revise；达上限 → human_flag。"""
    plan = state.get("plan", {}) or {}
    max_iter = int(plan.get("max_iterations", 3))
    iteration = state.get("iteration", 0)
    if state.get("review_passed"):
        return "save"
    if iteration < max_iter:
        return "revise"
    return "human_flag"


def build_graph():
    """构建并编译 LangGraph 工作流，返回可调用的编译后 app。"""
    graph = StateGraph(KBState)

    graph.add_node("plan", planner_node)
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    graph.add_node("revise", revise_node)
    graph.add_node("human_flag", human_flag_node)
    graph.add_node("save", save_node)

    graph.add_edge("plan", "collect")
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "organize")
    graph.add_edge("organize", "review")
    graph.add_conditional_edges(
        "review",
        route_after_review,
        {"save": "save", "revise": "revise", "human_flag": "human_flag"},
    )
    graph.add_edge("revise", "review")
    graph.add_edge("human_flag", END)
    graph.add_edge("save", END)

    graph.set_entry_point("plan")

    return graph.compile()


def _show_review_feedback(feedback: str) -> None:
    """把 review_feedback 分段多行展示（按 | 分段，宽度 78 悬挂缩进）。"""
    for part in (feedback or "").split(" | "):
        part = part.strip()
        if not part:
            continue
        print(textwrap.fill(
            part, width=78,
            initial_indent="    - ", subsequent_indent="      ",
        ))


def _show_cost(cost: dict) -> None:
    """按 (provider/model) 分行展示成本汇总。"""
    for key, v in (cost or {}).items():
        print(f"    {key}: calls={v.get('calls', 0)} "
              f"in={v.get('prompt_tokens', 0)} out={v.get('completion_tokens', 0)} "
              f"$={v.get('cost_usd', 0):.6f}")


from tests.cost_guard import BudgetExceededError

if __name__ == "__main__":
    try:
        app = build_graph()
        first_block = True
        for step, outputs in enumerate(app.stream({"iteration": 0}), start=1):
            for node, update in outputs.items():
                if not first_block:
                    print()
                first_block = False
                if not update:
                    continue
                for key, value in update.items():
                    if key == "cost_tracker":
                        print(f"  cost_tracker:")
                        _show_cost(value)
                    elif key == "review_feedback":
                        print(f"  review_feedback:")
                        _show_review_feedback(str(value))
                    elif isinstance(value, list):
                        print(f"  {key}: {len(value)} 条")
                    else:
                        print(f"  {key}: {value}")
    except BudgetExceededError as exc:
        print(f"\n[CostGuard] ⚠️ {str(exc).rstrip('。')}，流程已中止。")
        sys.exit(1)
    finally:
        guard = get_cost_guard()
        report = guard.get_report()
        total_calls = len(report["records"])
        cost_by_node = {
            name: node["total_cost_yuan"] for name, node in report["nodes"].items()
        }
        print(f"\n[CostGuard] 总调用 {total_calls} 次 · 总成本 ¥{report['total_cost_yuan']:.6f}")
        print(f"[CostGuard] 按节点：{cost_by_node}")
        guard.save_report(Path(__file__).resolve().parents[1] / "knowledge" / "cost-report.json")
