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

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflows.nodes import analyze_node, collect_node, organize_node, review_node, save_node
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


if __name__ == "__main__":
    app = build_graph()
    for step, outputs in enumerate(app.stream({"iteration": 0}), start=1):
        for node, update in outputs.items():
            if update:
                print(f"--- step {step} | {node} ---")
                for key, value in update.items():
                    print(f"  {key}: {value if not isinstance(value, list) else len(value)} 条")
