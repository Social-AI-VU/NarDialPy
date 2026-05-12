from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, TypedDict
from datetime import datetime, timezone
from time import monotonic

from langgraph.graph import END, StateGraph

from nardial.utils import normalize_text


class HybridRouterState(TypedDict, total=False):
    turns: int
    done: bool
    action: str
    selected_dialog_id: str
    last_user_input: str
    completed_dialog_ids: List[str]


def _recent_context(session_history: List[Dict[str, Any]], max_items: int = 12) -> List[str]:
    lines: List[str] = []
    for item in session_history[-max_items:]:
        role = item.get("role")
        txt = item.get("text")
        if role and txt:
            lines.append(f"{role}: {txt}")
    return lines


def _safe_json_loads(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _is_dialog_eligible(dialog: Any, completed_ids: List[str], user_model: Dict[str, Any], all_dialogs: List[Any]) -> bool:
    # Lazy import avoids circular import at module-load time.
    from nardial.dialog_logic import DialogLogic
    return DialogLogic.is_dialog_eligible(dialog, completed_ids, user_model, all_dialogs)


def run_llm_router_graph(
        *,
        conversation_agent,
        session_history: List[Dict[str, Any]],
        topics_of_interest: List[str],
        user_model: Dict[str, Any],
        base_prompt: str,
        dialogs: List[Any],
        logger=None,
        done_phrases: Optional[List[str]] = None,
        rag_enabled: bool = True,
        rag_index_name: Optional[str] = None,
        max_turns: int = 100,
) -> None:
    dialog_map = {d.dialog_id: d for d in dialogs}
    done_markers = {normalize_text(x) for x in (done_phrases or ["done", "finish", "goodbye", "bye", "quit", "stop"]) if x}
    log = logger
    if log is None:
        try:
            log = conversation_agent.orchestrator.logger
        except Exception:
            log = None

    def _log_debug(msg: str):
        if log is not None:
            try:
                log.debug(msg)
                return
            except Exception:
                pass
        print(msg)

    def _log_info(msg: str):
        if log is not None:
            try:
                log.info(msg)
                return
            except Exception:
                pass
        print(msg)

    _log_info(f"[HYBRID_ROUTER] start dialog_candidates={list(dialog_map.keys())}")

    def _robot_timestamp_monotonic() -> float:
        try:
            ts = conversation_agent.orchestrator.last_robot_speech_start_monotonic
            if isinstance(ts, (int, float)):
                return float(ts)
        except Exception:
            pass
        return monotonic()

    def listen_node(state: HybridRouterState) -> HybridRouterState:
        turns = int(state.get("turns", 0))
        if turns >= max_turns:
            _log_info(f"[HYBRID_ROUTER] max_turns_reached={max_turns}")
            return {"done": True, "action": "DONE"}

        reply, _intent = conversation_agent.orchestrator.listen()
        user_text = (reply or "").strip()
        if user_text:
            session_history.append({
                "role": "user",
                "type": "answer_open",
                "text": user_text,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "timestamp_monotonic": monotonic(),
            })
        _log_debug(f"[HYBRID_ROUTER] user_input={user_text!r}")
        done = normalize_text(user_text) in done_markers
        return {"last_user_input": user_text, "done": done, "turns": turns + 1}

    def route_node(state: HybridRouterState) -> HybridRouterState:
        if state.get("done"):
            _log_info("[HYBRID_ROUTER] route_action=DONE (explicit done phrase)")
            return {"action": "DONE"}

        completed_ids = list(state.get("completed_dialog_ids") or [])
        available: List[Dict[str, str]] = []
        for d in dialogs:
            if not _is_dialog_eligible(d, completed_ids, user_model, dialogs):
                continue
            available.append({
                "id": d.dialog_id,
                "description": str(getattr(d, "description", "") or getattr(d, "theme", "") or d.dialog_id),
            })

        if not available:
            _log_info("[HYBRID_ROUTER] route_action=IMPROVISE (no eligible structured dialogs)")
            return {"action": "IMPROVISE"}

        router_prompt = (
            "You route user inputs to one of the available dialog ids.\n"
            "Return JSON ONLY with keys: action, dialog_id.\n"
            "Valid actions: RUN_DIALOG, IMPROVISE, DONE.\n"
            "Choose RUN_DIALOG only when one description clearly matches the user request.\n"
            "Choose IMPROVISE if nothing matches.\n"
            "Only choose DONE if the user explicitly says they are finished or wants to end the conversation.\n\n"
            f"Available dialogs: {json.dumps(available, ensure_ascii=False)}"
        )

        routed = conversation_agent.orchestrator.request_from_gpt(
            user_prompt=state.get("last_user_input", ""),
            context_messages=_recent_context(session_history),
            system_prompt=router_prompt,
            json_response=True,
            rag_enabled=False,
        )
        parsed = _safe_json_loads(routed)
        action = str(parsed.get("action", "IMPROVISE")).upper()
        dialog_id = str(parsed.get("dialog_id", "") or "")

        if action == "RUN_DIALOG" and dialog_id in dialog_map:
            _log_info(f"[HYBRID_ROUTER] route_action=RUN_DIALOG dialog_id={dialog_id}")
            return {"action": "RUN_DIALOG", "selected_dialog_id": dialog_id}
        if action == "DONE":
            _log_info("[HYBRID_ROUTER] route_action=DONE (router decided)")
            return {"action": "DONE", "done": True}
        _log_info("[HYBRID_ROUTER] route_action=IMPROVISE (router fallback)")
        return {"action": "IMPROVISE"}

    def run_dialog_node(state: HybridRouterState) -> HybridRouterState:
        did = state.get("selected_dialog_id", "")
        d = dialog_map.get(did)
        if not d:
            _log_info(f"[HYBRID_ROUTER] selected dialog missing: {did!r}, switching to IMPROVISE")
            return {"action": "IMPROVISE"}
        _log_info(f"[HYBRID_ROUTER] executing_dialog={did}")
        d.run(conversation_agent, session_history, topics_of_interest, user_model)

        completed = list(state.get("completed_dialog_ids") or [])
        if not bool(getattr(d, "repeatable", False)) and did not in completed:
            completed.append(did)
            _log_debug(f"[HYBRID_ROUTER] marked_completed={did}")
        return {"completed_dialog_ids": completed}

    def improvise_node(state: HybridRouterState) -> HybridRouterState:
        user_text = state.get("last_user_input", "")
        if not user_text:
            return {}
        _log_info("[HYBRID_ROUTER] improvising_with_rag_llm")
        text = conversation_agent.ask_llm(
            user_prompt=user_text,
            context_messages=_recent_context(session_history),
            system_prompt=base_prompt,
            rag_enabled=rag_enabled,
            rag_index_name=rag_index_name,
        )
        if text:
            conversation_agent.say(text)
            session_history.append({
                "role": "robot",
                "type": "ask_llm",
                "text": text,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "timestamp_monotonic": _robot_timestamp_monotonic(),
            })
            _log_debug(f"[HYBRID_ROUTER] improvised_response={text!r}")
        return {}

    def route_decision(state: HybridRouterState) -> str:
        action = str(state.get("action", "")).upper()
        if action == "DONE" or state.get("done"):
            return "end"
        if action == "RUN_DIALOG":
            return "run_dialog"
        return "improvise"

    graph = StateGraph(HybridRouterState)
    graph.add_node("listen", listen_node)
    graph.add_node("route", route_node)
    graph.add_node("run_dialog", run_dialog_node)
    graph.add_node("improvise", improvise_node)
    graph.set_entry_point("listen")
    graph.add_edge("listen", "route")
    graph.add_conditional_edges(
        "route",
        route_decision,
        {
            "run_dialog": "run_dialog",
            "improvise": "improvise",
            "end": END,
        },
    )
    graph.add_edge("run_dialog", "listen")
    graph.add_edge("improvise", "listen")
    app = graph.compile()
    app.invoke({"turns": 0, "done": False, "completed_dialog_ids": []})
    _log_info("[HYBRID_ROUTER] finished")
