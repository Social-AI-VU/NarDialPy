import json
import os
from typing import Any, Dict, List, Tuple, Type

from nardial.authoring.factory import DialogFactory, DialogTypeFactory
from nardial.dialog_registry import DialogRegistry
from nardial.dialog_types import get_dialog_type
from nardial.mini_dialogs import MiniDialog


def _load_json_file(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError(f"Unsupported JSON root in {path}: {type(data)}")


def _read_docs(path_or_dir: str, errors: List[str]) -> List[Tuple[str, Any]]:
    """Read every doc from a JSON file or all .json files in a directory, as (source path, doc) pairs."""
    if os.path.isdir(path_or_dir):
        paths = [os.path.join(path_or_dir, fn) for fn in os.listdir(path_or_dir) if fn.lower().endswith(".json")]
    else:
        paths = [path_or_dir]

    entries: List[Tuple[str, Any]] = []
    for p in paths:
        try:
            entries.extend((p, doc) for doc in _load_json_file(p))
        except Exception as e:
            errors.append(f"{p}: {e}")
    return entries


def _define_types(definitions: List[Tuple[str, Any]], errors: List[str]) -> List[Type[MiniDialog]]:
    """Register every `define_type` doc, parents before children, regardless of file/doc order."""
    defined: List[Type[MiniDialog]] = []
    pending = list(definitions)
    while pending:
        ready = [(p, doc) for p, doc in pending
                 if isinstance(doc.get("extends"), str) and get_dialog_type(doc["extends"]) is not None]
        if not ready:
            break
        for entry in ready:
            pending.remove(entry)
            p, doc = entry
            try:
                defined.append(DialogTypeFactory.from_json(doc))
            except Exception as e:
                errors.append(f"{p}: {e}")

    # Whatever is left extends an unknown type (or is part of a cycle); report why.
    for p, doc in pending:
        try:
            defined.append(DialogTypeFactory.from_json(doc))
        except Exception as e:
            errors.append(f"{p}: {e}")
    return defined


def load_dialog_types(path_or_dir: str) -> Tuple[List[Type[MiniDialog]], List[str]]:
    """Register the dialog types defined in a JSON file or all .json files in a directory.

    Every doc must be a `define_type` doc (see `DialogTypeFactory`); types
    may extend each other in any file/doc order. Must run before loading
    dialogs that use these types.

    Returns (registered type classes, errors).
    """
    errors: List[str] = []
    definitions: List[Tuple[str, Any]] = []
    for p, doc in _read_docs(path_or_dir, errors):
        if DialogTypeFactory.is_type_definition(doc):
            definitions.append((p, doc))
        else:
            errors.append(f"{p}: not a dialog type definition (missing 'define_type'); "
                          f"dialogs belong in a separate dialog file")
    return _define_types(definitions, errors), errors


def load_dialogs(path_or_dir: str) -> Tuple[List[MiniDialog], List[str]]:
    """Load dialogs from a JSON file or all .json files in a directory.

    Custom dialog types must already be registered (see `load_dialog_types`);
    a `define_type` doc here is reported as an error.

    Returns (dialogs, errors).
    """
    dialogs: List[MiniDialog] = []
    errors: List[str] = []

    for p, doc in _read_docs(path_or_dir, errors):
        if DialogTypeFactory.is_type_definition(doc):
            errors.append(f"{p}: dialog type definition {doc.get('define_type')!r} found in a dialog file; "
                          f"type definitions belong in a separate file, loaded with load_dialog_types()")
            continue
        try:
            dialogs.append(DialogFactory.from_json(doc))
        except Exception as e:
            errors.append(f"{p}: {e}")

    return dialogs, errors


def load_dialog_registry(path_or_dir: str) -> Tuple[DialogRegistry, List[str]]:
    """Load dialogs from a JSON file or directory and build a DialogRegistry.

    Returns (registry, errors); per-file/per-doc errors are collected the
    same way as `load_dialogs` and never raise.
    """
    dialogs, errors = load_dialogs(path_or_dir)
    registry = DialogRegistry.build(dialogs)
    return registry, errors


def dialog_to_doc(d: MiniDialog) -> Dict[str, Any]:
    """Serialize a dialog object back to a JSON-ready dict (round-trip)."""
    return DialogFactory.to_json(d)


def save_dialogs(path: str, dialogs: List[MiniDialog]) -> None:
    """Save a list of dialog objects to a single JSON file (array root)."""
    docs = [dialog_to_doc(d) for d in dialogs]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(docs, f, indent=2, ensure_ascii=False)


def save_dialogs_to_dir(directory: str, dialogs: List[MiniDialog]) -> None:
    """Save each dialog to its own JSON file inside directory."""
    os.makedirs(directory, exist_ok=True)
    for d in dialogs:
        did = getattr(d, "dialog_id", None) or "untitled"
        safe_id = "".join(c for c in did if c.isalnum() or c in ("_", "-"))
        path = os.path.join(directory, f"{safe_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dialog_to_doc(d), f, indent=2, ensure_ascii=False)
