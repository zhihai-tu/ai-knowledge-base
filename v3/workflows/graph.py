"""LangGraph 工作流编排。

组装 collect → analyze → organize → review → save 流水线；review 之后按
``review_passed`` 条件分支：True 进入 save 结束，False 带反馈回到 organize
重做（配合 nodes.py 的审核重做循环与强制通过机制）。

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

from workflows.nodes import analyze_node, collect_node, organize_node, save_node
from workflows.reviewer import review_node
from workflows.state import KBState


def _review_router(state: KBState) -> str:
    """review 之后的下一步：通过则保存，否则回到 organize 修正。"""
    return "save" if state.get("review_passed") else "organize"


def build_graph():
    """构建并编译 LangGraph 工作流，返回可调用的编译后 app。"""
    graph = StateGraph(KBState)

    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    # graph.add_node("review", review_node_test)
    graph.add_node("save", save_node)

    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "organize")
    graph.add_edge("organize", "review")
    graph.add_conditional_edges(
        "review",
        _review_router,
        {"save": "save", "organize": "organize"},
    )
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
