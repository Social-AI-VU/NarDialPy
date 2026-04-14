"""
Phase C: scripted mini-dialogs run as a LangGraph state machine.

One graph node performs a single outer iteration of the former MiniDialog.run while-loop
(skip due to branch filter, or execute one move). A conditional edge loops until the dialog ends.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, TypedDict

from nardial.moves import (
    MOVE_ANIMATION,
    MOVE_ASK_LLM,
    MOVE_ASK_OPEN,
    MOVE_ASK_OPTIONS,
    MOVE_ASK_YESNO,
    MOVE_MOTION_SEQUENCE,
    MOVE_PLAY_AUDIO,
    MOVE_SAY,
)

if TYPE_CHECKING:
    from nardial.mini_dialogs import LLMDialog, MiniDialog


class MiniDialogGraphState(TypedDict):
    idx: int
    branch: Optional[str]
    finished: bool


def _import_state_graph():
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception as e:
        raise ImportError(
            "LangGraph is required for scripted mini-dialog graphs. Install with `pip install langgraph`."
        ) from e
    return END, START, StateGraph


def _mini_dialog_step(dialog: "MiniDialog", state: MiniDialogGraphState) -> MiniDialogGraphState:
    """Mirror one iteration of MiniDialog.run (while body)."""
    idx = state["idx"]
    branch = state["branch"]
    moves = dialog.moves
    n = len(moves)

    if idx >= n:
        return {"idx": idx, "branch": branch, "finished": True}

    move = moves[idx]
    move_type = dialog._get(move, "type")
    move_branch = dialog._get(move, "branch")

    if move_branch != branch:
        if branch is not None and move_branch is None:
            branch = None
            move_branch = dialog._get(move, "branch")
            if move_branch != branch:
                new_idx = idx + 1
                return {"idx": new_idx, "branch": branch, "finished": new_idx >= n}
        else:
            new_idx = idx + 1
            return {"idx": new_idx, "branch": branch, "finished": new_idx >= n}

    if move_type == MOVE_SAY:
        dialog.handle_move_say(move)
        new_idx = idx + 1
        return {"idx": new_idx, "branch": branch, "finished": new_idx >= n}
    if move_type == MOVE_ASK_YESNO:
        answer = dialog.handle_move_ask_yesno(move)
        new_branch = dialog.find_next_branch(branch, move, answer)
        new_idx = dialog.find_branch_start(new_branch, idx)
        return {"idx": new_idx, "branch": new_branch, "finished": new_idx >= n}
    if move_type == MOVE_ASK_OPEN:
        answer = dialog.handle_move_ask_open(move)
        new_branch = dialog.find_next_branch(branch, move, answer)
        new_idx = dialog.find_branch_start(new_branch, idx)
        return {"idx": new_idx, "branch": new_branch, "finished": new_idx >= n}
    if move_type == MOVE_ASK_OPTIONS:
        answer = dialog.handle_move_ask_options(move)
        new_branch = dialog.find_next_branch(branch, move, answer)
        new_idx = dialog.find_branch_start(new_branch, idx)
        return {"idx": new_idx, "branch": new_branch, "finished": new_idx >= n}
    if move_type == MOVE_PLAY_AUDIO:
        dialog.handle_move_play_audio(move)
        new_idx = idx + 1
        return {"idx": new_idx, "branch": branch, "finished": new_idx >= n}
    if move_type == MOVE_MOTION_SEQUENCE:
        dialog.handle_move_motion_sequence(move)
        new_idx = idx + 1
        return {"idx": new_idx, "branch": branch, "finished": new_idx >= n}
    if move_type == MOVE_ANIMATION:
        dialog.handle_move_animation(move)
        new_idx = idx + 1
        return {"idx": new_idx, "branch": branch, "finished": new_idx >= n}
    if move_type == MOVE_ASK_LLM:
        dialog.handle_move_ask_llm(move)
        new_idx = idx + 1
        return {"idx": new_idx, "branch": branch, "finished": new_idx >= n}

    new_idx = idx + 1
    return {"idx": new_idx, "branch": branch, "finished": new_idx >= n}


def _llm_dialog_step(dialog: "LLMDialog", state: MiniDialogGraphState) -> MiniDialogGraphState:
    dialog._run_llm_exchange(
        prompt=dialog.prompt,
        max_turns=dialog.max_turns,
        set_variable=None,
        quit_phrases=dialog.quit_phrases,
        quit_signal=dialog.quit_signal,
    )
    return {"idx": 0, "branch": None, "finished": True}


def compile_scripted_mini_dialog_graph(dialog: "MiniDialog") -> Any:
    """
    Compile a LangGraph that runs this dialog's scripted moves (or LLM-only exchange for LLMDialog).
    Invoke with {"idx": 0, "branch": None, "finished": False}.
    """
    END, START, StateGraph = _import_state_graph()

    from nardial.mini_dialogs import LLMDialog

    if isinstance(dialog, LLMDialog):

        def step_llm(s: MiniDialogGraphState) -> MiniDialogGraphState:
            return _llm_dialog_step(dialog, s)

        graph = StateGraph(MiniDialogGraphState)
        graph.add_node("llm_exchange", step_llm)
        graph.add_edge(START, "llm_exchange")
        graph.add_edge("llm_exchange", END)
        return graph.compile()

    def step(s: MiniDialogGraphState) -> MiniDialogGraphState:
        return _mini_dialog_step(dialog, s)

    def route(s: MiniDialogGraphState) -> Literal["continue", "done"]:
        if s.get("finished") or s["idx"] >= len(dialog.moves):
            return "done"
        return "continue"

    graph = StateGraph(MiniDialogGraphState)
    graph.add_node("step", step)
    graph.add_edge(START, "step")
    graph.add_conditional_edges("step", route, {"continue": "step", "done": END})
    return graph.compile()


def initial_mini_dialog_state() -> MiniDialogGraphState:
    return {"idx": 0, "branch": None, "finished": False}
