from typing import Any, Dict, List

from src.mini_dialogs import MiniDialog, NarrativeDialog, ChitchatDialog, FunctionalDialog, LLMDialog, DialogType
from src.moves import MOVE_SAY, MOVE_ASK_OPEN, MOVE_ASK_YESNO, MOVE_ASK_OPTIONS, MOVE_PLAY_AUDIO


ALLOWED_MOVE_TYPES = {MOVE_SAY, MOVE_ASK_YESNO, MOVE_ASK_OPEN, MOVE_ASK_OPTIONS, MOVE_PLAY_AUDIO}


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
        if mt == "ask_options":
            opts = move.get("options")
            if not isinstance(opts, list) or not all(isinstance(o, str) for o in opts):
                errs.append(f"moves[{idx}].options must be a list of strings for ask_options")
        if "set_variable" in move and not isinstance(move.get("set_variable"), str):
            errs.append(f"moves[{idx}].set_variable must be string if present")
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
        if t not in {"functional", "narrative", "chitchat"}:
            errs.append("type must be 'functional' | 'narrative' | 'chitchat'")
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

        moves = doc.get("moves")
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
            return NarrativeDialog(
                dialog_id=did,
                moves=moves,
                thread=doc["thread"],
                position=int(doc["position"]),
                dependencies=deps,
                variable_dependencies=vdeps,
            )
        if dtype == DialogType.CHITCHAT.value:
            return ChitchatDialog(
                dialog_id=did,
                moves=moves,
                theme=doc.get("theme") or "",
                topics=list(doc.get("topics") or []),
                dependencies=deps,
                variable_dependencies=vdeps,
            )
        if dtype == DialogType.FUNCTIONAL.value:
            return FunctionalDialog(
                dialog_id=did,
                moves=moves,
                type=doc["functional_type"],
                dependencies=deps,
            )
        if dtype == DialogType.LLM_BASED.value:
            return LLMDialog(
                dialog_id=did,
                moves=moves,
                prompt=doc["prompt"],
                max_turns=doc["max_turns"],
                dependencies=deps,
                variable_dependencies=vdeps,
            )
        return MiniDialog(did, moves, deps, vdeps)

    @staticmethod
    def to_json(d: MiniDialog) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "id": getattr(d, "dialog_id", None),
            "dependencies": list(getattr(d, "dependencies", []) or []),
            "variable_dependencies": list(getattr(d, "variable_dependencies", []) or []),
            "moves": list(getattr(d, "moves", []) or []),
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
        elif isinstance(d, FunctionalDialog):
            base.update({
                "type": "functional",
                "functional_type": getattr(d, "type", ""),
            })
        else:
            base.update({"type": "unknown"})
        return base
