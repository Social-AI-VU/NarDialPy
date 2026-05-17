from typing import Any, Dict, List

from nardial.mini_dialogs import (
    MiniDialog,
    NarrativeDialog,
    ChitchatDialog,
    FunctionalDialog,
    LLMDialog,
    LLMRouterDialog,
    IntentRouterDialog,
    DialogType,
)
from nardial.utils import normalize_text
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
        if t not in {"functional", "narrative", "chitchat", "llm_based", "llm_router", "intent_router"}:
            errs.append("type must be 'functional' | 'narrative' | 'chitchat' | 'llm_based' | 'llm_router' | 'intent_router'")
        # shared
        if "intent" in doc and not isinstance(doc.get("intent"), str):
            errs.append("intent must be string when provided")
        if "repeatable" in doc and not isinstance(doc.get("repeatable"), bool):
            errs.append("repeatable must be boolean when provided")
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
            if "description" in doc and not isinstance(doc.get("description"), str):
                errs.append("description must be string for chitchat dialogs")
            topics = doc.get("topics")
            if topics is not None and (not isinstance(topics, list) or not all(isinstance(x, str) for x in topics)):
                errs.append("topics must be a list of strings for chitchat dialogs")
            rm = doc.get("repeat_moves")
            if rm is not None:
                if not bool(doc.get("repeatable", False)):
                    errs.append("repeat_moves requires repeatable true for chitchat dialogs")
                if not isinstance(rm, list) or not rm:
                    errs.append("repeat_moves must be a non-empty list when provided for chitchat dialogs")
                else:
                    for i, mv in enumerate(rm):
                        errs.extend([f"repeat_moves[{i}]: {e}" for e in MoveFactory.validate(mv, idx=i)])
                    has_yesno = any(
                        isinstance(m, dict) and m.get("type") == MOVE_ASK_YESNO for m in rm
                    )
                    if not has_yesno:
                        errs.append("repeat_moves must include at least one ask_yesno move for chitchat dialogs")
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
        elif t == "llm_router":
            if not isinstance(doc.get("base_prompt"), str):
                errs.append("base_prompt must be string for llm_router dialogs")
            if "done_phrases" in doc and (
                    not isinstance(doc.get("done_phrases"), list) or not all(isinstance(x, str) for x in doc.get("done_phrases"))):
                errs.append("done_phrases must be a list of strings for llm_router dialogs")
            if "rag_enabled" in doc and not isinstance(doc.get("rag_enabled"), bool):
                errs.append("rag_enabled must be boolean for llm_router dialogs")
            if doc.get("rag_enabled") is True and not (
                    isinstance(doc.get("index_name"), str) and doc.get("index_name").strip()):
                errs.append("index_name must be a non-empty string when rag_enabled is true for llm_router dialogs")
            if "max_turns" in doc and not isinstance(doc.get("max_turns"), int):
                errs.append("max_turns must be integer for llm_router dialogs")
            sub_dialogs = doc.get("dialogs")
            if not isinstance(sub_dialogs, list) or not sub_dialogs:
                errs.append("dialogs must be a non-empty list for llm_router dialogs")
            else:
                for i, sub_doc in enumerate(sub_dialogs):
                    if not isinstance(sub_doc, dict):
                        errs.append(f"dialogs[{i}] must be an object")
                        continue
                    sub_errs = DialogFactory.validate_doc(sub_doc)
                    errs.extend([f"dialogs[{i}]: {e}" for e in sub_errs])
        elif t == "intent_router":
            sub_dialogs = doc.get("dialogs")
            if not isinstance(sub_dialogs, list) or not sub_dialogs:
                errs.append("dialogs must be a non-empty list for intent_router dialogs")
            else:
                for i, sub_doc in enumerate(sub_dialogs):
                    if not isinstance(sub_doc, dict):
                        errs.append(f"dialogs[{i}] must be an object")
                        continue
                    sub_errs = DialogFactory.validate_doc(sub_doc)
                    errs.extend([f"dialogs[{i}]: {e}" for e in sub_errs])

        moves = doc.get("moves")
        if t not in {"llm_router", "intent_router"}:
            if not isinstance(moves, list):
                errs.append("moves must be a list")
            else:
                for i, mv in enumerate(moves):
                    errs.extend(MoveFactory.validate(mv, idx=i))
        return errs

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

        if dtype == DialogType.NARRATIVE.value:
            dialog = NarrativeDialog(
                dialog_id=did,
                moves=moves,
                thread=doc["thread"],
                position=int(doc["position"]),
                dependencies=deps,
                variable_dependencies=vdeps,
            )
            setattr(dialog, "repeatable", bool(doc.get("repeatable", False)))
            setattr(dialog, "intent", doc.get("intent"))
            return dialog
        if dtype == DialogType.CHITCHAT.value:
            dialog = ChitchatDialog(
                dialog_id=did,
                moves=moves,
                theme=doc.get("theme") or "",
                topics=list(doc.get("topics") or []),
                dependencies=deps,
                variable_dependencies=vdeps,
                description=str(doc.get("description") or ""),
            )
            setattr(dialog, "repeatable", bool(doc.get("repeatable", False)))
            setattr(
                dialog,
                "repeat_moves",
                [MoveFactory.normalize(m) for m in (doc.get("repeat_moves") or [])],
            )
            setattr(dialog, "intent", doc.get("intent"))
            return dialog
        if dtype == DialogType.FUNCTIONAL.value:
            dialog = FunctionalDialog(
                dialog_id=did,
                moves=moves,
                type=doc["functional_type"],
                dependencies=deps,
            )
            setattr(dialog, "repeatable", bool(doc.get("repeatable", False)))
            setattr(dialog, "intent", doc.get("intent"))
            return dialog
        if dtype == DialogType.LLM_BASED.value:
            dialog = LLMDialog(
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
            )
            setattr(dialog, "repeatable", bool(doc.get("repeatable", False)))
            setattr(dialog, "intent", doc.get("intent"))
            return dialog
        if dtype == DialogType.HYBRID_ROUTER.value:
            routed_dialogs = [DialogFactory.from_json(sd) for sd in (doc.get("dialogs") or [])]
            dialog = LLMRouterDialog(
                dialog_id=did,
                base_prompt=doc.get("base_prompt") or "",
                dialogs=routed_dialogs,
                dependencies=deps,
                variable_dependencies=vdeps,
                done_phrases=doc.get("done_phrases"),
                rag_enabled=doc.get("rag_enabled", False),
                rag_index_name=doc.get("index_name"),
                max_turns=doc.get("max_turns", 100),
            )
            setattr(dialog, "repeatable", bool(doc.get("repeatable", False)))
            setattr(dialog, "intent", doc.get("intent"))
            return dialog
        if dtype == DialogType.INTENT_ROUTER.value:
            routed_dialogs = [DialogFactory.from_json(sd) for sd in (doc.get("dialogs") or [])]
            intent_routing = {}
            for child in routed_dialogs:
                intent_name = normalize_text(getattr(child, "intent", None))
                if intent_name:
                    intent_routing[intent_name] = child.dialog_id
            dialog = IntentRouterDialog(
                child_dialogs=routed_dialogs,
                intent_routing=intent_routing,
                block_exit_intents=doc.get("block_exit_intents"),
                dialog_id=did,
                dependencies=deps,
                variable_dependencies=vdeps,
            )
            setattr(dialog, "repeatable", bool(doc.get("repeatable", False)))
            setattr(dialog, "intent", doc.get("intent"))
            return dialog
        dialog = MiniDialog(did, moves, deps, vdeps)
        setattr(dialog, "repeatable", bool(doc.get("repeatable", False)))
        setattr(dialog, "intent", doc.get("intent"))
        return dialog

    @staticmethod
    def to_json(d: MiniDialog) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "id": getattr(d, "dialog_id", None),
            "dependencies": list(getattr(d, "dependencies", []) or []),
            "variable_dependencies": list(getattr(d, "variable_dependencies", []) or []),
            "moves": list(getattr(d, "moves", []) or []),
            "repeatable": bool(getattr(d, "repeatable", False)),
            "intent": getattr(d, "intent", None),
        }
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
            desc = getattr(d, "description", "") or ""
            if desc:
                base["description"] = desc
            rm = list(getattr(d, "repeat_moves", []) or [])
            if rm:
                base["repeat_moves"] = rm
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
        elif isinstance(d, LLMRouterDialog):
            base.update({
                "type": "llm_router",
                "base_prompt": getattr(d, "base_prompt", ""),
                "done_phrases": list(getattr(d, "done_phrases", []) or []),
                "rag_enabled": getattr(d, "rag_enabled", False),
                "index_name": getattr(d, "rag_index_name", None),
                "max_turns": int(getattr(d, "max_turns", 100)),
                "dialogs": [DialogFactory.to_json(sd) for sd in list(getattr(d, "dialogs", []) or [])],
            })
        elif isinstance(d, IntentRouterDialog):
            base.update({
                "type": "intent_router",
                "dialogs": [DialogFactory.to_json(sd) for sd in list(getattr(d, "child_dialogs", []) or [])],
                "block_exit_intents": list(getattr(d, "block_exit_intents", []) or []),
            })
        else:
            base.update({"type": "unknown"})
        return base
