from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, TypedDict


DEFAULT_MAX_TURNS = 6
DEFAULT_QUIT_SIGNAL = "<<STOP_IMPROV>>"
DEFAULT_SPEECH_CLEANER_PROMPT = (
    "You rewrite text into exactly what a social robot should say out loud. "
    "Remove any metadata, role labels, transcript wrappers, or formatting noise. "
    "Return only the final spoken utterance, plain text, no prefixes, no quotes, no explanation."
)


def _build_runtime_prompt(system_prompt: str, topics_of_interest: List[str], user_model: Dict[str, Any]) -> str:
    topics_text = ", ".join(str(t) for t in (topics_of_interest or []) if str(t).strip())
    model_text = ", ".join(f"{k}={v}" for k, v in (user_model or {}).items())

    return (
        f"{system_prompt}\n\n"
        "Runtime context:\n"
        f"- topics_of_interest: [{topics_text}]\n"
        f"- user_model: {{{model_text}}}\n\n"
        "Behavior constraints:\n"
        "- Keep responses concise and conversational.\n"
        "- Output ONLY the exact words the robot should speak next. Do not prefix with "
        "\"Robot:\", \"Assistant:\", or any role label.\n"
        f"- If stop condition is met, include token {DEFAULT_QUIT_SIGNAL} in your response."
    )


def _normalize_spoken_text(text: str, quit_signal: str | None = None) -> str:
    """Minimal safety normalization after LLM verification."""
    if not text:
        return ""
    t = text.strip()
    if quit_signal:
        t = t.replace(quit_signal, " ")
    return t.strip()


def _history_as_context_messages(session_history: List[Dict[str, Any]]) -> List[str]:
    """Build LLM context"""
    context_messages: List[str] = []
    for entry in session_history or []:
        role = entry.get("role", "unknown")
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        if role == "user":
            context_messages.append(f"User said: {text}")
        elif role == "robot":
            context_messages.append(f"Robot's last spoken line was: {text}")
        else:
            context_messages.append(f"{role}: {text}")
    return context_messages


def _record_event(session_history: List[Dict[str, Any]], role: str, type_name: str, text: str, **extra: Any) -> None:
    item: Dict[str, Any] = {"role": role, "type": type_name, "text": text}
    item.update(extra)
    session_history.append(item)


def _stop_by_phrase(text: str, stop_phrases: List[str]) -> bool:
    lowered = (text or "").lower()
    for phrase in stop_phrases:
        if phrase and phrase.lower() in lowered:
            return True
    return False


class ImprovisationState(TypedDict):
    user_input: str
    turn_idx: int
    max_turns: int
    started_at: float
    time_limit_seconds: float | None
    stop_phrases: List[str]
    quit_signal: str
    runtime_prompt: str
    last_llm_text: str
    spoken_text: str
    stop_reason: str


def _import_state_graph():
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception as e:
        raise ImportError(
            "LangGraph is required. Install with `pip install langgraph`."
        ) from e
    return END, START, StateGraph


def build_improvisation_state_graph(
        plan_response: Callable[[ImprovisationState], ImprovisationState],
        verify_spoken_text: Callable[[ImprovisationState], ImprovisationState],
        speak_and_listen: Callable[[ImprovisationState], ImprovisationState],
        check_stop: Callable[[ImprovisationState], ImprovisationState],
):
    """Wire nodes and edges; compile with `.compile()` when ready."""
    END, START, StateGraph = _import_state_graph()

    def route_after_check(state: ImprovisationState) -> Literal["plan_response", "stop"]:
        return "stop" if state["stop_reason"] else "plan_response"

    graph = StateGraph(ImprovisationState)
    graph.add_node("plan_response", plan_response)
    graph.add_node("verify_spoken_text", verify_spoken_text)
    graph.add_node("speak_and_listen", speak_and_listen)
    graph.add_node("check_stop", check_stop)
    graph.add_edge(START, "plan_response")
    graph.add_edge("plan_response", "verify_spoken_text")
    graph.add_edge("verify_spoken_text", "speak_and_listen")
    graph.add_edge("speak_and_listen", "check_stop")
    graph.add_conditional_edges("check_stop", route_after_check, {"plan_response": "plan_response", "stop": END})
    return graph


def _noop_improvisation_node(_state: ImprovisationState) -> ImprovisationState:
    """Placeholder nodes: same topology as the live graph for export/visualization."""
    return {}


def compile_improvisation_graph_for_visualization():
    """Compiled graph with no-op nodes — use `get_graph().draw_mermaid()` etc."""
    return build_improvisation_state_graph(
        _noop_improvisation_node,
        _noop_improvisation_node,
        _noop_improvisation_node,
        _noop_improvisation_node,
    ).compile()


def improvisation_graph_mermaid(*, xray: bool = False) -> str:
    """Return Mermaid source for the improvisation StateGraph (structure only)."""
    app = compile_improvisation_graph_for_visualization()
    return app.get_graph(xray=xray).draw_mermaid()


def save_improvisation_graph_mermaid(output_path: str | Path) -> Path:
    """Write `improvisation_graph.mmd` (or similar); open in VS Code Mermaid preview or mermaid.live."""
    path = Path(output_path)
    path.write_text(improvisation_graph_mermaid(), encoding="utf-8")
    return path


def save_improvisation_graph_png(output_path: str | Path) -> Path | None:
    """
    Try to render the graph to PNG via LangGraph (often uses mermaid.ink; may require network).
    Returns the path on success, or None if rendering failed.
    """
    try:
        app = compile_improvisation_graph_for_visualization()
        png_bytes = app.get_graph().draw_mermaid_png()
    except Exception:
        return None
    path = Path(output_path)
    path.write_bytes(png_bytes)
    return path


def _normalize_stop_condition(stop_condition: Dict[str, Any] | None) -> tuple[int, float | None, List[str], str]:
    condition = stop_condition or {}
    max_turns = int(condition.get("max_turns", DEFAULT_MAX_TURNS))
    time_limit_seconds_raw = condition.get("time_limit_seconds")
    time_limit_seconds = float(time_limit_seconds_raw) if time_limit_seconds_raw is not None else None
    stop_phrases = [p for p in (condition.get("stop_phrases") or []) if p]
    quit_signal = condition.get("quit_signal") or DEFAULT_QUIT_SIGNAL
    return max_turns, time_limit_seconds, stop_phrases, quit_signal


def compile_improvisation_app(
        conversation_agent: Any,
        session_history: List[Dict[str, Any]],
        topics_of_interest: List[str],
        user_model: Dict[str, Any],
        system_prompt: str,
        stop_condition: Dict[str, Any] | None = None,
) -> tuple[Any, str, Dict[str, Any]]:
    """
    Build and compile the improvisation LangGraph

    Returns (compiled_app, runtime_prompt, stop_condition_dict) for use with
    invoke_compiled_improvisation_app().
    """
    condition = dict(stop_condition or {})
    max_turns, time_limit_seconds, stop_phrases, quit_signal = _normalize_stop_condition(condition)

    runtime_prompt = _build_runtime_prompt(
        system_prompt=system_prompt or "You are a helpful conversational improvisation agent.",
        topics_of_interest=topics_of_interest,
        user_model=user_model,
    )

    def plan_response(state: ImprovisationState) -> ImprovisationState:
        if state["stop_reason"]:
            return {}
        context_messages = _history_as_context_messages(session_history)
        llm_text = conversation_agent.ask_llm(
            user_prompt=state["user_input"],
            context_messages=context_messages,
            system_prompt=state["runtime_prompt"],
        )
        if llm_text is None:
            return {"stop_reason": "llm_returned_none"}
        return {"last_llm_text": llm_text}

    def verify_spoken_text(state: ImprovisationState) -> ImprovisationState:
        if state["stop_reason"]:
            return {}
        raw_llm_text = state["last_llm_text"] or ""
        if not raw_llm_text:
            return {"stop_reason": "llm_returned_none"}

        base_spoken = _normalize_spoken_text(raw_llm_text, quit_signal=quit_signal)
        if not base_spoken and state["quit_signal"] not in raw_llm_text:
            return {"stop_reason": "llm_returned_none"}

        # Ask the model to self-clean into pure spoken text.
        verifier_input = base_spoken or raw_llm_text
        verifier_output = conversation_agent.ask_llm(
            user_prompt=verifier_input,
            context_messages=None,
            system_prompt=DEFAULT_SPEECH_CLEANER_PROMPT,
        )
        verified_spoken = _normalize_spoken_text(verifier_output or "", quit_signal=quit_signal)
        final_spoken = verified_spoken or base_spoken
        if not final_spoken and state["quit_signal"] not in raw_llm_text:
            return {"stop_reason": "llm_returned_none"}
        return {"spoken_text": final_spoken}

    def speak_and_listen(state: ImprovisationState) -> ImprovisationState:
        if state["stop_reason"]:
            return {}
        llm_text = state["last_llm_text"]
        to_speak = state.get("spoken_text", "")
        if state["quit_signal"] in llm_text:
            clean = to_speak or _normalize_spoken_text(llm_text, quit_signal=quit_signal)
            if clean:
                conversation_agent.say(clean)
                _record_event(session_history, "robot", "improvisation_ask", clean)
            return {"stop_reason": "quit_signal"}
        if not to_speak:
            # Keep conversation moving even if sanitization removes wrapper-only output.
            return {"stop_reason": "llm_returned_none"}
        user_input = conversation_agent.ask_open(to_speak) or ""
        turn = state["turn_idx"] + 1
        _record_event(session_history, "robot", "improvisation_ask", to_speak, turn=turn)
        _record_event(session_history, "user", "improvisation_answer", user_input, turn=turn)
        return {"user_input": user_input, "turn_idx": turn}

    def check_stop(state: ImprovisationState) -> ImprovisationState:
        if state["stop_reason"]:
            return {}
        if state["turn_idx"] >= state["max_turns"]:
            return {"stop_reason": "max_turns_reached"}
        if state["time_limit_seconds"] is not None and (time.time() - state["started_at"]) >= state["time_limit_seconds"]:
            return {"stop_reason": "time_limit_reached"}
        if _stop_by_phrase(state["user_input"], state["stop_phrases"]):
            return {"stop_reason": "stop_phrase"}
        return {}

    app = build_improvisation_state_graph(
        plan_response,
        verify_spoken_text,
        speak_and_listen,
        check_stop,
    ).compile()
    return app, runtime_prompt, condition


def invoke_compiled_improvisation_app(
        compiled_app: Any,
        runtime_prompt: str,
        stop_condition: Dict[str, Any] | None,
        session_history: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Run one full improvisation pass on a graph from compile_improvisation_app()."""
    max_turns, time_limit_seconds, stop_phrases, quit_signal = _normalize_stop_condition(stop_condition)

    final_state = compiled_app.invoke({
        "user_input": "",
        "turn_idx": 0,
        "max_turns": max_turns,
        "started_at": time.time(),
        "time_limit_seconds": time_limit_seconds,
        "stop_phrases": stop_phrases,
        "quit_signal": quit_signal,
        "runtime_prompt": runtime_prompt,
        "last_llm_text": "",
        "spoken_text": "",
        "stop_reason": "",
    })

    stop_reason = final_state.get("stop_reason")
    if stop_reason == "llm_returned_none":
        _record_event(session_history, "system", "error", "llm_returned_none", stage="improvisation")
    elif stop_reason:
        _record_event(session_history, "system", "improvisation_stop", stop_reason)
    return final_state


def run_improvisation_graph(
        conversation_agent: Any,
        session_history: List[Dict[str, Any]],
        topics_of_interest: List[str],
        user_model: Dict[str, Any],
        system_prompt: str,
        stop_condition: Dict[str, Any] | None = None) -> None:
    """
    Run improvisation via an actual LangGraph StateGraph.

    stop_condition examples:
    {
      "max_turns": 6,
      "time_limit_seconds": 120,
      "stop_phrases": ["stop", "that's enough"],
      "quit_signal": "<<STOP_IMPROV>>"
    }
    """
    app, runtime_prompt, cond = compile_improvisation_app(
        conversation_agent,
        session_history,
        topics_of_interest,
        user_model,
        system_prompt,
        stop_condition,
    )
    invoke_compiled_improvisation_app(app, runtime_prompt, cond, session_history)
