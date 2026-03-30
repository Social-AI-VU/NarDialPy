import json
import os
from typing import Any, Dict, List, Tuple

from src.authoring.factory import DialogFactory
from src.dialogs import Dialog


def _load_json_file(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError(f"Unsupported JSON root in {path}: {type(data)}")


def load_dialogs(path_or_dir: str) -> Tuple[List[Dialog], List[str]]:
    """Load dialogs from a JSON file or all .json files in a directory.

    Returns (dialogs, errors).
    """
    dialogs: List[Dialog] = []
    errors: List[str] = []

    try:
        if os.path.isdir(path_or_dir):
            for fn in os.listdir(path_or_dir):
                if not fn.lower().endswith(".json"):
                    continue
                p = os.path.join(path_or_dir, fn)
                try:
                    for doc in _load_json_file(p):
                        dialogs.append(DialogFactory.from_json(doc))
                except Exception as e:
                    errors.append(f"{p}: {e}")
        else:
            for doc in _load_json_file(path_or_dir):
                try:
                    dialogs.append(DialogFactory.from_json(doc))
                except Exception as e:
                    errors.append(f"{path_or_dir}: {e}")
    except Exception as e:
        errors.append(str(e))

    return dialogs, errors


def dialog_to_doc(d: Dialog) -> Dict[str, Any]:
    """Serialize a dialog object back to a JSON-ready dict (round-trip)."""
    return DialogFactory.to_json(d)


def save_dialogs(path: str, dialogs: List[Dialog]) -> None:
    """Save a list of dialog objects to a single JSON file (array root)."""
    docs = [dialog_to_doc(d) for d in dialogs]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(docs, f, indent=2, ensure_ascii=False)


def save_dialogs_to_dir(directory: str, dialogs: List[Dialog]) -> None:
    """Save each dialog to its own JSON file inside directory."""
    os.makedirs(directory, exist_ok=True)
    for d in dialogs:
        did = getattr(d, "dialog_id", None) or "untitled"
        safe_id = "".join(c for c in did if c.isalnum() or c in ("_", "-"))
        path = os.path.join(directory, f"{safe_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dialog_to_doc(d), f, indent=2, ensure_ascii=False)
