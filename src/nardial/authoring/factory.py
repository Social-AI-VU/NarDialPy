import copy
import re
from typing import Any, Dict, List, Type

from nardial.dialog_types import dialog_type_names, get_dialog_type, register_dialog_type
from nardial.eligibility import build_rule
# Importing mini_dialogs registers the built-in dialog types.
from nardial.mini_dialogs import MiniDialog
from nardial.moves import (
    MOVE_SAY,
    MOVE_SAY_OPTIONS,
    MOVE_ASK_OPEN,
    MOVE_ASK_YESNO,
    MOVE_ASK_OPTIONS,
    MOVE_ASK_LLM,
    MOVE_PLAY_AUDIO,
    MOVE_MOTION_SEQUENCE,
    MOVE_ANIMATION,
    MOVE_BRANCH,
    MOVE_TIMED_WAIT,
    MOVE_WAIT_FOR_WEB_INPUT,
    MOVE_WAIT_FOR_BUTTON,
    MOVE_SHOW_IMAGE,
    MOVE_SHOW_VIDEO,
    MOVE_SHOW_IFRAME,
    MOVE_SHOW_HTML,
    MOVE_BLACK_SCREEN,
    MOVE_KEYBOARD_INPUT,
    MOVE_GO_TO_DIALOG
)

ALLOWED_MOVE_TYPES = {
    MOVE_SAY,
    MOVE_SAY_OPTIONS,
    MOVE_ASK_YESNO,
    MOVE_ASK_OPEN,
    MOVE_ASK_OPTIONS,
    MOVE_ASK_LLM,
    MOVE_PLAY_AUDIO,
    MOVE_MOTION_SEQUENCE,
    MOVE_ANIMATION,
    MOVE_BRANCH,
    MOVE_TIMED_WAIT,
    MOVE_WAIT_FOR_WEB_INPUT,
    MOVE_WAIT_FOR_BUTTON,
    MOVE_SHOW_IMAGE,
    MOVE_SHOW_VIDEO,
    MOVE_SHOW_IFRAME,
    MOVE_SHOW_HTML,
    MOVE_BLACK_SCREEN,
    MOVE_KEYBOARD_INPUT,
    MOVE_GO_TO_DIALOG
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
        if mt == MOVE_SAY:
            if not isinstance(move.get("text"), str):
                errs.append(f"moves[{idx}].text must be string for say")
        if mt == MOVE_SAY_OPTIONS:
            opts = move.get("options")
            if not isinstance(opts, list) or not opts or not all(isinstance(o, str) for o in opts):
                errs.append(f"moves[{idx}].options must be a non-empty list of strings for say_options")
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
        if mt == MOVE_WAIT_FOR_BUTTON:
            opts = move.get("options")
            if not isinstance(opts, list) or not opts or not all(isinstance(o, str) for o in opts):
                errs.append(f"moves[{idx}].options must be a non-empty list of strings for wait_for_button")
        if mt == MOVE_PLAY_AUDIO and not isinstance(move.get("audio"), str):
            errs.append(f"moves[{idx}].audio must be string for play")
        if mt == MOVE_MOTION_SEQUENCE and not isinstance(move.get("motion_sequence"), str):
            errs.append(f"moves[{idx}].motion_sequence must be string for motion_sequence")
        if mt == MOVE_ANIMATION and not isinstance(move.get("animation_name"), str):
            errs.append(f"moves[{idx}].animation_name must be string for animation")
        if "set_variable" in move and not isinstance(move.get("set_variable"), str):
            errs.append(f"moves[{idx}].set_variable must be string if present")
        if mt == MOVE_BRANCH:
            on_val = move.get("on")
            if not on_val:
                errs.append(f"moves[{idx}].on must specify what to branch on")
            if not isinstance(on_val, str):
                errs.append(f"moves[{idx}].on must be a string for branch")
            if on_val == "variables" and move.get("variables") is None:
                errs.append(f"moves[{idx}].variables must specify the variables to base branching on")
            elif on_val == "variables" and len(move.get("variables")) != 2:
                errs.append(f"moves[{idx}].variables must contain 2 variables")
            cases = move.get("cases")
            if not isinstance(cases, dict):
                errs.append(f"moves[{idx}].cases must be an object for branch")
            elif not all(isinstance(v, list) for v in cases.values()):
                errs.append(f"moves[{idx}].cases values must be lists of moves for branch")
        if mt == MOVE_GO_TO_DIALOG:
            dialog_id = move.get("dialog_id")
            if not isinstance(dialog_id, str):
                errs.append(f"moves[{idx}].dialog_id must be a string")
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
        dialog_cls = get_dialog_type(t) if isinstance(t, str) else None
        if dialog_cls is None:
            errs.append("type must be " + " | ".join(f"'{name}'" for name in dialog_type_names()))
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
        if dialog_cls is not None:
            errs.extend(dialog_cls.validate_doc(doc))

        characters = doc.get("characters")
        if characters is not None:
            if not isinstance(characters, dict):
                errs.append("characters must be an object")
            else:
                for character_name, character_cfg in characters.items():
                    if not isinstance(character_name, str) or not character_name:
                        errs.append("characters keys must be non-empty strings")
                    if not isinstance(character_cfg, dict):
                        errs.append(f"characters.{character_name} must be an object")
                        continue
                    if "voice_settings" not in character_cfg:
                        errs.append(f"characters.{character_name}.voice_settings is required")
                        continue
                    voice_settings = character_cfg.get("voice_settings")
                    if not isinstance(voice_settings, dict):
                        errs.append(f"characters.{character_name}.voice_settings must be an object")

        moves = doc.get("moves")
        if not isinstance(moves, list):
            errs.append("moves must be a list")
        else:
            for i, mv in enumerate(moves):
                errs.extend(MoveFactory.validate(mv, idx=i))
                if isinstance(mv, dict) and "character" in mv:
                    character_name = mv.get("character")
                    if not isinstance(character_name, str):
                        errs.append(f"moves[{i}].character must be string if present")
                    elif not isinstance(characters, dict) or character_name not in characters:
                        errs.append(f"moves[{i}].character references unknown character '{character_name}'")
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
        characters = dict(doc.get("characters") or {})
        prerequisites = list(doc.get("prerequisites") or [])

        return get_dialog_type(dtype).from_doc(
            doc,
            dialog_id=did,
            moves=moves,
            dependencies=deps,
            variable_dependencies=vdeps,
            characters=characters,
            prerequisites=prerequisites
        )

    @staticmethod
    def to_json(d: MiniDialog) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "id": getattr(d, "dialog_id", None),
            "dependencies": list(getattr(d, "dependencies", []) or []),
            "variable_dependencies": list(getattr(d, "variable_dependencies", []) or []),
            "moves": list(getattr(d, "moves", []) or []),
        }
        characters = dict(getattr(d, "characters", {}) or {})
        if characters:
            base["characters"] = characters
        base["type"] = getattr(d, "TYPE_NAME", None) or "unknown"
        base.update(d.to_doc())
        return base


class DialogTypeFactory:
    """Builds dialog types from `define_type` JSON documents.

    A definition derives a new type from a registered one (`extends`) by
    dropping some of its default eligibility rules (`remove_rules`, by rule
    name) and appending new ones (`add_rules`, rule specs as accepted by
    `eligibility.build_rule`). The result is a real subclass, registered
    under the new name, so dialogs of that type load, run and select exactly
    like dialogs of the parent type.
    """

    ALLOWED_KEYS = {"define_type", "extends", "description", "add_rules", "remove_rules"}

    @staticmethod
    def is_type_definition(doc: Any) -> bool:
        return isinstance(doc, dict) and "define_type" in doc

    @staticmethod
    def validate_doc(doc: Dict[str, Any]) -> List[str]:
        errs: List[str] = []
        name = doc.get("define_type")
        if not isinstance(name, str) or not name:
            errs.append("define_type must be non-empty string")
        for key in doc:
            if key not in DialogTypeFactory.ALLOWED_KEYS:
                errs.append(f"unknown key {key!r} in type definition")
        if "description" in doc and not isinstance(doc.get("description"), str):
            errs.append("description must be string")

        base_name = doc.get("extends")
        base = get_dialog_type(base_name) if isinstance(base_name, str) else None
        if base is None:
            errs.append("extends must be one of " + " | ".join(f"'{n}'" for n in dialog_type_names()))

        add_rules = doc.get("add_rules")
        if add_rules is not None:
            if not isinstance(add_rules, list):
                errs.append("add_rules must be a list")
            else:
                for idx, spec in enumerate(add_rules):
                    try:
                        build_rule(spec)
                    except ValueError as e:
                        errs.append(f"add_rules[{idx}]: {e}")

        remove_rules = doc.get("remove_rules")
        if remove_rules is not None:
            if not isinstance(remove_rules, list) or not all(isinstance(x, str) for x in remove_rules):
                errs.append("remove_rules must be a list of rule names")
            elif base is not None:
                base_rule_names = [rule.RULE_NAME for rule in base.DEFAULT_ELIGIBILITY]
                for idx, rule_name in enumerate(remove_rules):
                    if rule_name not in base_rule_names:
                        errs.append(f"remove_rules[{idx}]: {rule_name!r} is not a rule of {base_name!r} "
                                    f"(its rules: {', '.join(map(str, base_rule_names)) or 'none'})")
        return errs

    @staticmethod
    def from_json(doc: Dict[str, Any]) -> Type[MiniDialog]:
        """Create and register the type described by `doc`, returning its class.

        Loading the same definition again returns the already-registered
        class; a different definition under a taken name raises `ValueError`.
        """
        errors = DialogTypeFactory.validate_doc(doc)
        if errors:
            raise ValueError("; ".join(errors))

        name = doc["define_type"]
        existing = get_dialog_type(name)
        if existing is not None and getattr(existing, "TYPE_DEFINITION", None) == doc:
            return existing

        base = get_dialog_type(doc["extends"])
        removed = set(doc.get("remove_rules") or [])
        rules = [rule for rule in base.DEFAULT_ELIGIBILITY if rule.RULE_NAME not in removed]
        rules += [build_rule(spec) for spec in doc.get("add_rules") or []]

        class_name = "".join(part[:1].upper() + part[1:] for part in re.split(r"[^0-9A-Za-z]+", name) if part)
        if not class_name[:1].isalpha():
            class_name = "Dialog" + class_name
        cls = type(class_name, (base,), {
            "__doc__": doc.get("description") or f"Dialog type {name!r}, defined in JSON (extends {base.TYPE_NAME!r}).",
            "DEFAULT_ELIGIBILITY": rules,
            "TYPE_DEFINITION": copy.deepcopy(doc),
        })
        return register_dialog_type(name)(cls)
