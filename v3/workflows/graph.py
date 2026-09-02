"""LangGraph 工作流编排。

组装 collect → analyze → organize → review 流水线；review 之后按
``route_after_review`` 三路分支：

- 通过（review_passed=True）→ save 结束
- 未通过且 ``iteration < MAX_ITERATIONS`` → revise 按反馈改写 analyses 后
  回到 review（形成审核重做循环）
- 未通过且 ``iteration >= MAX_ITERATIONS`` → human_flag 写入
  pending_review/ 人工介入（异常终点）

用法::

    from workflows.graph import build_graph

    app = build_graph()
    result = app.invoke({"sources": [], "iteration": 0})
"""

from langgraph.graph import END, StateGraph

import os
import sys
import textwrap

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflows.human_flag import human_flag_node
from workflows.nodes import analyze_node, collect_node, organize_node, save_node
from workflows.reviewer import review_node
from workflows.reviser import revise_node
from workflows.state import KBState, MAX_ITERATIONS


def route_after_review(state: KBState) -> str:
    """review 之后的三路分支：通过 → save；未通过且未超限 → revise；未通过已达上限 → human_flag。"""
    if state.get("review_passed"):
        return "save"
    if (state.get("iteration") or 0) < MAX_ITERATIONS:
        return "revise"
    return "human_flag"


def build_graph():
    """构建并编译 LangGraph 工作流，返回可调用的编译后 app。"""
    graph = StateGraph(KBState)

    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    graph.add_node("revise", revise_node)
    graph.add_node("human_flag", human_flag_node)
    # graph.add_node("review", review_node_test)
    graph.add_node("save", save_node)

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

    graph.set_entry_point("collect")

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


if __name__ == "__main__":
    app = build_graph()
    first_block = True
    for step, outputs in enumerate(app.stream({"iteration": 0}), start=1):
        for node, update in outputs.items():
            if not update:
                continue
            if not first_block:
                print()
            first_block = False
            print(f"--- step {step} | {node} 完成 ---")
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
    print()
