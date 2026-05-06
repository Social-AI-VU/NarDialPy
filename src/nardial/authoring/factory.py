from typing import Any, Dict, List

from nardial.mini_dialogs import MiniDialog, NarrativeDialog, ChitchatDialog, FunctionalDialog, LLMDialog, DialogType
from nardial.moves import (
    MOVE_SAY,
    MOVE_ASK_OPEN,
    MOVE_ASK_YESNO,
    MOVE_ASK_OPTIONS,
    MOVE_ASK_LLM,
    MOVE_PLAY_AUDIO,
    MOVE_MOTION_SEQUENCE,
    MOVE_ANIMATION,
    MOVE_BRANCH,
)
from nardial.tts_manager import DialogAgentConfig


ALLOWED_MOVE_TYPES = {
    MOVE_SAY,
    MOVE_ASK_YESNO,
    MOVE_ASK_OPEN,
    MOVE_ASK_OPTIONS,
    MOVE_ASK_LLM,
    MOVE_PLAY_AUDIO,
    MOVE_MOTION_SEQUENCE,
    MOVE_ANIMATION,
    MOVE_BRANCH,
}


class MoveFactory:
    @staticmethod
    def validate(move: Dict[str, Any], idx: int = 0) -> List[str]:
        errs: List[str] = []
        if not isinstance(move, dict):
            return [f"moves[{idx}] must be an object"]
        mt = move.get("type")
        if mt not in ALLOWED_MOVE_TYPES:
            errs.append(f"moves[{idx}].type must be one of {sorted(ALLOWED_MOVE_TYPES)}")
        if mt in {"say"}:
            if not isinstance(move.get("text"), str):
                errs.append(f"moves[{idx}].text must be string for say")
        if mt in {MOVE_ASK_YESNO, MOVE_ASK_OPEN, MOVE_ASK_OPTIONS}:
            if not isinstance(move.get("text"), str):
                errs.append(f"moves[{idx}].text must be string for {mt}")
        if mt == MOVE_ASK_LLM:
            if not isinstance(move.get("prompt"), str):
                errs.append(f"moves[{idx}].prompt must be string for ask_llm")
        if mt == "ask_options":
            opts = move.get("options")
            if not isinstance(opts, list) or not all(isinstance(o, str) for o in opts):
                errs.append(f"moves[{idx}].options must be a list of strings for ask_options")
        if mt == MOVE_PLAY_AUDIO and not isinstance(move.get("audio"), str):
            errs.append(f"moves[{idx}].audio must be string for play")
        if mt == MOVE_MOTION_SEQUENCE and not isinstance(move.get("motion_sequence"), str):
            errs.append(f"moves[{idx}].motion_sequence must be string for motion_sequence")
        if mt == MOVE_ANIMATION and not isinstance(move.get("animation_name"), str):
            errs.append(f"moves[{idx}].animation_name must be string for animation")
        if "set_variable" in move and not isinstance(move.get("set_variable"), str):
            errs.append(f"moves[{idx}].set_variable must be string if present")
        if mt == MOVE_BRANCH:
            on_val = move.get("on", "outcome")
            if not isinstance(on_val, str):
                errs.append(f"moves[{idx}].on must be a string for branch")
            cases = move.get("cases")
            if not isinstance(cases, dict):
                errs.append(f"moves[{idx}].cases must be an object for branch")
            elif not all(isinstance(v, list) for v in cases.values()):
                errs.append(f"moves[{idx}].cases values must be lists of moves for branch")
        return errs

    @staticmethod
    def normalize(move: Dict[str, Any]) -> Dict[str, Any]:
        # Keep as-is; runtime expects dict moves. We could strip unknown keys later if needed.
        return dict(move)


class DialogFactory:
    @staticmethod
    def _normalize_variable_dependencies(vdeps: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not vdeps:
            return out
        for item in vdeps:
            if isinstance(item, str):
                out.append({"variable": item, "required": True})
            elif isinstance(item, dict) and item.get("variable"):
                d = {"variable": str(item["variable"]), "required": bool(item.get("required", True))}
                out.append(d)
        return out

    @staticmethod
    def validate_doc(doc: Dict[str, Any]) -> List[str]:
        errs: List[str] = []
        t = doc.get("type")
        did = doc.get("id")
        if not isinstance(did, str) or not did:
            errs.append("id must be non-empty string")
        if t not in {"functional", "narrative", "chitchat", "llm_based"}:
            errs.append("type must be 'functional' | 'narrative' | 'chitchat' | 'llm_based'")
        # shared
        deps = doc.get("dependencies")
        if deps is not None and (not isinstance(deps, list) or not all(isinstance(x, str) for x in deps)):
            errs.append("dependencies must be a list of strings")
        # variable deps: allow list[str|obj]
        vdeps = doc.get("variable_dependencies")
        if vdeps is not None:
            if not isinstance(vdeps, list):
                errs.append("variable_dependencies must be a list")
            else:
                for idx, vd in enumerate(vdeps):
                    if isinstance(vd, str):
                        continue
                    if not isinstance(vd, dict) or "variable" not in vd:
                        errs.append(f"variable_dependencies[{idx}] must be string or object with 'variable'")
        # agent config (optional, nested under the "agent" key)
        agent = doc.get("agent")
        if agent is not None:
            if not isinstance(agent, dict):
                errs.append("agent must be an object")
            else:
                if "tts_type" in agent and agent["tts_type"] not in DialogAgentConfig.VALID_TTS_TYPES:
                    errs.append(f"agent.tts_type must be one of {sorted(DialogAgentConfig.VALID_TTS_TYPES)}")
                if "voice_id" in agent and not isinstance(agent["voice_id"], str):
                    errs.append("agent.voice_id must be a string")
                if "speaking_rate" in agent and not isinstance(agent["speaking_rate"], (int, float)):
                    errs.append("agent.speaking_rate must be a number")
                if "language" in agent and not isinstance(agent["language"], str):
                    errs.append("agent.language must be a string")
        # type-specific
        if t == "functional":
            if not isinstance(doc.get("functional_type"), str):
                errs.append("functional_type must be string for functional dialogs")
        elif t == "narrative":
            if not isinstance(doc.get("thread"), str):
                errs.append("thread must be string for narrative dialogs")
            try:
                int(doc.get("position"))
            except Exception:
                errs.append("position must be integer for narrative dialogs")
        elif t == "chitchat":
            if not isinstance(doc.get("theme"), str):
                errs.append("theme must be string for chitchat dialogs")
            topics = doc.get("topics")
            if topics is not None and (not isinstance(topics, list) or not all(isinstance(x, str) for x in topics)):
                errs.append("topics must be a list of strings for chitchat dialogs")
        elif t == "llm_based":
            if not isinstance(doc.get("prompt"), str):
                errs.append("prompt must be string for llm_based dialogs")
            if "max_turns" in doc and not isinstance(doc.get("max_turns"), int):
                errs.append("max_turns must be integer for llm_based dialogs")
            if "speak_first" in doc and not isinstance(doc.get("speak_first"), bool):
                errs.append("speak_first must be boolean for llm_based dialogs")
            if "duration" in doc and not isinstance(doc.get("duration"), (int, float)):
                errs.append("duration must be numeric seconds for llm_based dialogs")
            if "rag_enabled" in doc and not isinstance(doc.get("rag_enabled"), bool):
                errs.append("rag_enabled must be boolean for llm_based dialogs")
            if doc.get("rag_enabled") is True and not (
                    isinstance(doc.get("index_name"), str) and doc.get("index_name").strip()):
                errs.append("index_name must be a non-empty string when rag_enabled is true for llm_based dialogs")
            quit_phrases = doc.get("quit_phrases")
            if quit_phrases is not None and (
                    not isinstance(quit_phrases, list) or not all(isinstance(x, str) for x in quit_phrases)):
                errs.append("quit_phrases must be a list of strings for llm_based dialogs")
            if "quit_signal" in doc and not isinstance(doc.get("quit_signal"), str):
                errs.append("quit_signal must be string for llm_based dialogs")

        moves = doc.get("moves")
        if not isinstance(moves, list):
            errs.append("moves must be a list")
        else:
            for i, mv in enumerate(moves):
                errs.extend(MoveFactory.validate(mv, idx=i))
        return errs

    @staticmethod
    def _parse_agent_config(doc: Dict[str, Any]):
        """Extract dialog-level agent/TTS config from the ``"agent"`` key in *doc*.

        Returns a :class:`~nardial.tts_manager.DialogAgentConfig` when the
        ``"agent"`` key is present and is a non-empty dict, otherwise ``None``.

        Note: ``validate_doc`` is expected to have been called first; by the
        time this method runs, ``doc["agent"]`` is guaranteed to be a dict if
        it is present at all.
        """
        agent = doc.get("agent")
        if not isinstance(agent, dict):
            # Either absent or (past validate_doc) an unexpected type – skip.
            return None
        tts_type = agent.get("tts_type")
        voice_id = agent.get("voice_id")
        speaking_rate = agent.get("speaking_rate")
        language = agent.get("language")
        if any(v is not None for v in (tts_type, voice_id, speaking_rate, language)):
            return DialogAgentConfig(tts_type=tts_type, voice_id=voice_id, speaking_rate=speaking_rate, language=language)
        return None

    @staticmethod
    def from_json(doc: Dict[str, Any]) -> MiniDialog:
        errors = DialogFactory.validate_doc(doc)
        if errors:
            raise ValueError("; ".join(errors))

        dtype = doc.get("type")
        did = doc.get("id")
        deps = list(doc.get("dependencies") or [])
        vdeps = DialogFactory._normalize_variable_dependencies(doc.get("variable_dependencies"))
        moves = [MoveFactory.normalize(m) for m in (doc.get("moves") or [])]
        agent_config = DialogFactory._parse_agent_config(doc)

        if dtype == DialogType.NARRATIVE.value:
            return NarrativeDialog(
                dialog_id=did,
                moves=moves,
                thread=doc["thread"],
                position=int(doc["position"]),
                dependencies=deps,
                variable_dependencies=vdeps,
                agent_config=agent_config,
            )
        if dtype == DialogType.CHITCHAT.value:
            return ChitchatDialog(
                dialog_id=did,
                moves=moves,
                theme=doc.get("theme") or "",
                topics=list(doc.get("topics") or []),
                dependencies=deps,
                variable_dependencies=vdeps,
                agent_config=agent_config,
            )
        if dtype == DialogType.FUNCTIONAL.value:
            return FunctionalDialog(
                dialog_id=did,
                moves=moves,
                type=doc["functional_type"],
                dependencies=deps,
                agent_config=agent_config,
            )
        if dtype == DialogType.LLM_BASED.value:
            return LLMDialog(
                dialog_id=did,
                moves=moves,
                prompt=doc["prompt"],
                max_turns=doc.get("max_turns"),
                dependencies=deps,
                variable_dependencies=vdeps,
                quit_phrases=doc.get("quit_phrases"),
                quit_signal=doc.get("quit_signal"),
                speak_first=doc.get("speak_first", True),
                duration=doc.get("duration"),
                rag_enabled=doc.get("rag_enabled", False),
                rag_index_name=doc.get("index_name"),
                agent_config=agent_config,
            )
        return MiniDialog(did, moves, deps, vdeps, agent_config=agent_config)

    @staticmethod
    def to_json(d: MiniDialog) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "id": getattr(d, "dialog_id", None),
            "dependencies": list(getattr(d, "dependencies", []) or []),
            "variable_dependencies": list(getattr(d, "variable_dependencies", []) or []),
            "moves": list(getattr(d, "moves", []) or []),
        }
        # Serialize dialog-level agent config under the "agent" key when present.
        # agent_obj only receives keys that were explicitly set (mirrors _parse_agent_config
        # which only creates a DialogAgentConfig when at least one field is not None).
        agent_config = getattr(d, "agent_config", None)
        if agent_config is not None:
            agent_obj: Dict[str, Any] = {}
            if agent_config.tts_type is not None:
                agent_obj["tts_type"] = agent_config.tts_type
            if agent_config.voice_id is not None:
                agent_obj["voice_id"] = agent_config.voice_id
            if agent_config.speaking_rate is not None:
                agent_obj["speaking_rate"] = agent_config.speaking_rate
            if agent_config.language is not None:
                agent_obj["language"] = agent_config.language
            if agent_obj:
                base["agent"] = agent_obj
        if isinstance(d, NarrativeDialog):
            base.update({
                "type": "narrative",
                "thread": getattr(d, "thread", ""),
                "position": int(getattr(d, "position", 0)),
            })
        elif isinstance(d, ChitchatDialog):
            base.update({
                "type": "chitchat",
                "theme": getattr(d, "theme", ""),
                "topics": list(getattr(d, "topics", []) or []),
            })
        elif isinstance(d, FunctionalDialog):
            base.update({
                "type": "functional",
                "functional_type": getattr(d, "type", ""),
            })
        elif isinstance(d, LLMDialog):
            base.update({
                "type": "llm_based",
                "prompt": getattr(d, "prompt", ""),
                "max_turns": getattr(d, "max_turns", None),
                "quit_phrases": list(getattr(d, "quit_phrases", []) or []),
                "quit_signal": getattr(d, "quit_signal", None),
                "speak_first": getattr(d, "speak_first", True),
                "duration": getattr(d, "duration", None),
                "rag_enabled": getattr(d, "rag_enabled", False),
                "index_name": getattr(d, "rag_index_name", None),
            })
        else:
            base.update({"type": "unknown"})
        return base
