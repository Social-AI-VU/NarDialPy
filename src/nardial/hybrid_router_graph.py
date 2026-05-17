from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, TypedDict
from datetime import datetime, timezone
from time import monotonic

from langgraph.graph import END, StateGraph

from nardial.utils import normalize_text
from nardial.mini_dialogs import MiniDialog
from nardial.moves import MOVE_ANSWER_YESNO
from nardial.interaction_orchestrator import ConversationStdinEOF


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


def _dialog_has_repeat_prompt(dialog: Any) -> bool:
    return bool(getattr(dialog, "repeatable", False)) and bool(
        list(getattr(dialog, "repeat_moves", []) or [])
    )


def _user_confirmed_repeat(session_tail: List[Dict[str, Any]]) -> bool:
    """True if the latest ask_yesno answer in *session_tail* is affirmative (repeat main moves)."""
    yes_vals = {
        "yes", "y", "yeah", "yep", "sure", "please", "ok", "okay", "alright",
        "correct", "affirmative", "repeat", "go ahead",
    }
    for entry in reversed(session_tail or []):
        if entry.get("role") == "user" and entry.get("type") == MOVE_ANSWER_YESNO:
            ans = normalize_text(str(entry.get("text") or ""))
            return ans in yes_vals
    return False


def _is_dialog_eligible(dialog: Any, completed_ids: List[str], user_model: Dict[str, Any], all_dialogs: List[Any]) -> bool:
    # Lazy import avoids circular import at module-load time.
    from nardial.dialog_logic import DialogLogic
    cid = list(completed_ids or [])
    did = getattr(dialog, "dialog_id", None)
    if did and did in cid and _dialog_has_repeat_prompt(dialog):
        cid = [x for x in cid if x != did]
    return DialogLogic.is_dialog_eligible(dialog, cid, user_model, all_dialogs)


def run_llm_router_graph(
        *,
        conversation_agent,
        session_history: List[Dict[str, Any]],
        topics_of_interest: List[str],
        user_model: Dict[str, Any],
        base_prompt: str,
        dialogs: List[Any],
        logger=None,
        rag_enabled: bool = True,
        rag_index_name: Optional[str] = None,
        max_turns: int = 100,
) -> None:
    dialog_map = {d.dialog_id: d for d in dialogs}
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
        if state.get("done"):
            return {}
        turns = int(state.get("turns", 0))
        if turns >= max_turns:
            _log_info(f"[HYBRID_ROUTER] max_turns_reached={max_turns}")
            return {"done": True, "turns": turns + 1}

        reply, listen_meta = conversation_agent.orchestrator.listen(detect_intent=False)
        if listen_meta == "__stdin_eof__":
            _log_info("[HYBRID_ROUTER] stdin EOF (Ctrl+D); ending hybrid router loop")
            return {"last_user_input": "", "done": True, "turns": turns + 1}

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
        return {"last_user_input": user_text, "done": False, "turns": turns + 1}

    def route_node(state: HybridRouterState) -> HybridRouterState:
        def _append_router_event(
            *,
            router_action: str,
            router_dialog_id: Optional[str],
            token_usage: Optional[Dict[str, Any]],
            text: str,
            available_ids: Optional[List[str]] = None,
        ) -> None:
            session_history.append({
                "role": "system",
                "type": "hybrid_router_route",
                "text": text,
                "router_action": router_action,
                "router_dialog_id": router_dialog_id,
                "available_dialog_ids": available_ids,
                "token_usage": dict(token_usage) if isinstance(token_usage, dict) else token_usage,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "timestamp_monotonic": monotonic(),
            })

        if state.get("done"):
            _log_info("[HYBRID_ROUTER] route_action=END (max_turns or stdin EOF)")
            _append_router_event(
                router_action="END",
                router_dialog_id=None,
                token_usage=None,
                text="Hybrid router loop ending (Ctrl+D / EOF on keyboard input, or max_turns).",
                available_ids=None,
            )
            return {"action": "END"}

        completed_ids = list(state.get("completed_dialog_ids") or [])
        available: List[Dict[str, str]] = []
        for d in dialogs:
            if not _is_dialog_eligible(d, completed_ids, user_model, dialogs):
                continue
            available.append({
                "id": d.dialog_id,
                "description": str(getattr(d, "description", "") or getattr(d, "theme", "") or d.dialog_id),
            })

        available_ids = [a["id"] for a in available]

        if not available:
            _log_info("[HYBRID_ROUTER] route_action=IMPROVISE (no eligible structured dialogs)")
            _append_router_event(
                router_action="IMPROVISE",
                router_dialog_id=None,
                token_usage=None,
                text="No eligible structured dialogs; improvising.",
                available_ids=available_ids,
            )
            return {"action": "IMPROVISE"}

        router_prompt = (
            "You route user inputs to one of the available dialog ids.\n"
            "Return JSON ONLY with keys: action, dialog_id.\n"
            "Valid actions: RUN_DIALOG, IMPROVISE.\n"
            "Choose RUN_DIALOG when one description clearly matches the user request, including when the user repeats "
            "or rephrases the same question you already matched earlier in the interview. Same topic again should route "
            "to the same dialog_id again if it is still listed in Available dialogs.\n"
            "Choose IMPROVISE if nothing matches.\n"
            "Do not try to end the interview: there is no DONE action.\n\n"
            f"Available dialogs: {json.dumps(available, ensure_ascii=False)}"
        )

        routed = conversation_agent.orchestrator.request_from_gpt(
            user_prompt=state.get("last_user_input", ""),
            context_messages=_recent_context(session_history),
            system_prompt=router_prompt,
            json_response=True,
            rag_enabled=False,
            llm_call_purpose="hybrid_router",
        )
        # Snapshot immediately so a later LLM call (e.g. improvise) does not overwrite usage.
        router_token_usage = getattr(conversation_agent.orchestrator, "last_llm_usage", None)

        parsed = _safe_json_loads(routed)
        action = str(parsed.get("action", "IMPROVISE")).upper()
        dialog_id = str(parsed.get("dialog_id", "") or "")

        if action == "DONE":
            _log_info("[HYBRID_ROUTER] router returned legacy DONE; coercing to IMPROVISE (DONE is not supported)")
            action = "IMPROVISE"

        summary = f"Router LLM: action={action}"
        if dialog_id:
            summary += f", dialog_id={dialog_id}"
        _append_router_event(
            router_action=action,
            router_dialog_id=dialog_id or None,
            token_usage=router_token_usage,
            text=summary,
            available_ids=available_ids,
        )

        if action == "RUN_DIALOG" and dialog_id in dialog_map:
            _log_info(f"[HYBRID_ROUTER] route_action=RUN_DIALOG dialog_id={dialog_id}")
            return {"action": "RUN_DIALOG", "selected_dialog_id": dialog_id}
        _log_info("[HYBRID_ROUTER] route_action=IMPROVISE (router fallback)")
        return {"action": "IMPROVISE"}

    def run_dialog_node(state: HybridRouterState) -> HybridRouterState:
        """Run structured child dialogs under the LLM router.

        First time (dialog id not in ``completed_dialog_ids``): only ``moves`` run.
        If ``repeatable`` and ``repeat_moves`` are set, the id is recorded after that run.
        Later times: ``repeat_moves`` run first; if the user answers yes to repeat, the same
        ``moves`` list runs again unchanged.
        """
        did = state.get("selected_dialog_id", "")
        d = dialog_map.get(did)
        if not d:
            _log_info(f"[HYBRID_ROUTER] selected dialog missing: {did!r}, switching to IMPROVISE")
            return {"action": "IMPROVISE"}
        _log_info(f"[HYBRID_ROUTER] executing_dialog={did}")
        completed = list(state.get("completed_dialog_ids") or [])
        has_repeat_prompt = _dialog_has_repeat_prompt(d)

        try:
            if has_repeat_prompt and did in completed:
                repeat_moves = list(getattr(d, "repeat_moves", []) or [])
                prompt_dialog = MiniDialog(f"{did}__repeat_prompt", repeat_moves)
                _hist_len = len(session_history)
                prompt_dialog.run(
                    conversation_agent,
                    session_history,
                    topics_of_interest,
                    user_model,
                )
                if _user_confirmed_repeat(session_history[_hist_len:]):
                    d.run(conversation_agent, session_history, topics_of_interest, user_model)
                else:
                    _log_debug(f"[HYBRID_ROUTER] repeat_declined dialog_id={did!r}")
            else:
                d.run(conversation_agent, session_history, topics_of_interest, user_model)
                if has_repeat_prompt and did not in completed:
                    completed.append(did)
                    _log_debug(f"[HYBRID_ROUTER] marked_once_played={did!r} (repeat_prompt path)")

            if not bool(getattr(d, "repeatable", False)) and did not in completed:
                completed.append(did)
                _log_debug(f"[HYBRID_ROUTER] marked_completed={did}")
        except ConversationStdinEOF:
            _log_info("[HYBRID_ROUTER] stdin EOF (Ctrl+D) during structured dialog; ending router loop")
            return {"done": True, "completed_dialog_ids": completed}
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
            llm_call_purpose="hybrid_improvise",
        )
        if text:
            conversation_agent.say(text)
            session_history.append({
                "role": "robot",
                "type": "ask_llm",
                "text": text,
                "token_usage": getattr(conversation_agent.orchestrator, "last_llm_usage", None),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "timestamp_monotonic": _robot_timestamp_monotonic(),
            })
            _log_debug(f"[HYBRID_ROUTER] improvised_response={text!r}")
        return {}

    def route_decision(state: HybridRouterState) -> str:
        if state.get("done"):
            return "end"
        action = str(state.get("action", "")).upper()
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
