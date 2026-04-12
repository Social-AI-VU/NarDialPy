"""
Session orchestration as a LangGraph linear chain.

Exported diagrams (session_history=None) register a real nested improvisation subgraph so
get_graph(xray=True) shows plan_response / speak_and_listen / check_stop inside a subgraph box.
The live runnable graph still uses a single session node that invokes that subgraph internally.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from nardial.dialog_logic import DialogLogic
from nardial.improvisation_graph import (
    compile_improvisation_app,
    compile_improvisation_graph_for_visualization,
    invoke_compiled_improvisation_app,
)
from nardial.mini_dialogs import ImprovisationDialog

if TYPE_CHECKING:
    from nardial.session_manager import SessionManager


def _sanitize_node_name(dialog_id: str, index: int) -> str:
    safe = re.sub(r"[^0-9a-zA-Z_]+", "_", dialog_id).strip("_") or "dialog"
    return f"dlg_{index}_{safe}"


def _noop_dialog_node(_state: Dict[str, Any]) -> Dict[str, Any]:
    """Structure-only placeholder for diagram export."""
    return {}


def _make_dialog_node(
        dialog: Any,
        manager: "SessionManager",
        session_history: List[Dict[str, Any]],
        all_dialogs: List[Any],
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    did = dialog.dialog_id

    def run_dialog_node(_state: Dict[str, Any]) -> Dict[str, Any]:
        if not DialogLogic.is_dialog_eligible(
                dialog,
                manager.conversation_state.completed_dialogs,
                manager.conversation_state.user_model,
                all_dialogs,
        ):
            print(f"[DEBUG] Skipped {did} (cannot run now)")
            return {}
        manager.conversation_state.add_dialog_id(manager.session_id, did)
        session_history.append({"role": "system", "type": "dialog_start", "dialog_id": did})
        dialog.run(
            manager.agent,
            session_history,
            manager.conversation_state.topics_of_interest,
            manager.conversation_state.user_model,
        )
        session_history.append({"role": "system", "type": "dialog_end", "dialog_id": did})
        manager.conversation_state.completed_dialogs.append(did)
        return {}

    return run_dialog_node


def _make_improvisation_session_node(
        dialog: ImprovisationDialog,
        manager: "SessionManager",
        session_history: List[Dict[str, Any]],
        all_dialogs: List[Any],
) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    """Run eligibility + logging, then compile and invoke the improvisation subgraph (Phase B)."""
    did = dialog.dialog_id

    def run_improv_session_node(_state: Dict[str, Any]) -> Dict[str, Any]:
        if not DialogLogic.is_dialog_eligible(
                dialog,
                manager.conversation_state.completed_dialogs,
                manager.conversation_state.user_model,
                all_dialogs,
        ):
            print(f"[DEBUG] Skipped {did} (cannot run now)")
            return {}
        manager.conversation_state.add_dialog_id(manager.session_id, did)
        session_history.append({"role": "system", "type": "dialog_start", "dialog_id": did})
        app, runtime_prompt, cond = compile_improvisation_app(
            manager.agent,
            session_history,
            manager.conversation_state.topics_of_interest,
            manager.conversation_state.user_model,
            dialog.system_prompt,
            dialog.stop_condition,
        )
        invoke_compiled_improvisation_app(app, runtime_prompt, cond, session_history)
        session_history.append({"role": "system", "type": "dialog_end", "dialog_id": did})
        manager.conversation_state.completed_dialogs.append(did)
        return {}

    return run_improv_session_node


def _empty_session_node(_state: Dict[str, Any]) -> Dict[str, Any]:
    print("[INFO] Session block is empty; nothing to run.")
    return {}


def _import_state_graph():
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception as e:
        raise ImportError(
            "LangGraph is required for session graphs. Install with `pip install langgraph`."
        ) from e
    return END, START, StateGraph


def build_uncompiled_session_graph(
        manager: "SessionManager",
        session_history: Optional[List[Dict[str, Any]]],
) -> Any:
    """
    Build the StateGraph (not compiled). If session_history is None, every dialog node uses
    a no-op runnable (for Mermaid / structure export only).
    """
    END, START, StateGraph = _import_state_graph()

    block = manager.session_block
    all_dialogs = manager.dialogs

    graph = StateGraph(dict)

    if not block:
        graph.add_node("empty_session", _empty_session_node)
        graph.add_edge(START, "empty_session")
        graph.add_edge("empty_session", END)
        return graph

    names: List[str] = []
    for i, dialog in enumerate(block):
        name = _sanitize_node_name(dialog.dialog_id, i)
        names.append(name)
        if session_history is not None:
            if isinstance(dialog, ImprovisationDialog):
                handler = _make_improvisation_session_node(
                    dialog, manager, session_history, all_dialogs)
            else:
                handler = _make_dialog_node(dialog, manager, session_history, all_dialogs)
        else:
            # Diagram export: real nested subgraph for improvisation (see get_graph(xray=True)).
            if isinstance(dialog, ImprovisationDialog):
                handler = compile_improvisation_graph_for_visualization()
            else:
                handler = _noop_dialog_node
        graph.add_node(name, handler)

    graph.add_edge(START, names[0])
    for a, b in zip(names, names[1:]):
        graph.add_edge(a, b)
    graph.add_edge(names[-1], END)

    return graph


def build_session_graph(
        manager: "SessionManager",
        session_history: List[Dict[str, Any]],
) -> Any:
    """
    Build a compiled LangGraph that runs session_block in order.
    Returns compiled graph (invoke with {}).
    """
    return build_uncompiled_session_graph(manager, session_history).compile()


def session_graph_mermaid(manager: "SessionManager", *, xray: bool = True) -> str:
    """
    Mermaid source for the current session_block topology (no execution).

    With xray=True (default), nested improvisation subgraphs show inner nodes (plan_response,
    speak_and_listen, check_stop). Standard Mermaid viewers still do not support click-to-expand;
    the full inner structure is already visible in the exported diagram.
    """
    app = build_uncompiled_session_graph(manager, session_history=None).compile()
    return app.get_graph(xray=xray).draw_mermaid()


def save_session_graph_mermaid(
        manager: "SessionManager", output_path: str | Path, *, xray: bool = True) -> Path:
    """Write session graph topology as a .mmd file."""
    path = Path(output_path)
    path.write_text(session_graph_mermaid(manager, xray=xray), encoding="utf-8")
    return path


def save_session_graph_png(
        manager: "SessionManager", output_path: str | Path, *, xray: bool = True) -> Optional[Path]:
    """
    Try to render the session graph to PNG (may require network for mermaid.ink).
    Returns path on success, None on failure.
    """
    try:
        app = build_uncompiled_session_graph(manager, session_history=None).compile()
        png_bytes = app.get_graph(xray=xray).draw_mermaid_png()
    except Exception:
        return None
    path = Path(output_path)
    path.write_bytes(png_bytes)
    return path


def run_session_graph(manager: "SessionManager", session_history: List[Dict[str, Any]]) -> None:
    """Compile the session graph (from current session_block) and run one full pass."""
    app = build_session_graph(manager, session_history)
    app.invoke({})
