import json
import logging
import os
from typing import Any, Dict, Generator, List, Tuple

from nardial.authoring.factory import from_json, to_json
from nardial.mini_dialogs import MiniDialog  # base type — all dialogs are MiniDialog subclasses

logger = logging.getLogger(__name__)


def _load_json_file(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    raise ValueError(f"Unsupported JSON root in {path}: {type(data)}")


def _iter_dialog_docs(path_or_dir: str) -> Generator[tuple[str, Dict[str, Any]], None, None]:
    """Yield ``(source_path, doc_dict)`` for every dialog document in *path_or_dir*.

    If *path_or_dir* is a directory, all ``.json`` files are visited in sorted
    order so that load order is deterministic; per-file read errors are logged
    and skipped so one bad file doesn't abort the whole load.  If *path_or_dir*
    is a single file, read errors are re-raised so callers can handle them
    (``load_dialogs`` adds them to the errors list; ``load_dialog_registry`` logs
    them at the outer level).

    Parameters
    ----------
    path_or_dir : str
        Path to a JSON file or a directory of ``.json`` files.

    Yields
    ------
    tuple[str, dict]
        ``(source_path, doc_dict)`` for each top-level dialog document.
    """
    if os.path.isdir(path_or_dir):
        for fn in sorted(os.listdir(path_or_dir)):
            if not fn.lower().endswith(".json"):
                continue
            p = os.path.join(path_or_dir, fn)
            try:
                for doc in _load_json_file(p):
                    yield p, doc
            except Exception as exc:
                logger.error("Skipping %s — failed to read: %s", p, exc)
    else:
        # Let file-level errors propagate; callers decide how to surface them.
        for doc in _load_json_file(path_or_dir):
            yield path_or_dir, doc


def load_dialogs(path_or_dir: str) -> Tuple[List[MiniDialog], List[str]]:
    """Load dialogs from a JSON file or all .json files in a directory.

    Returns
    -------
    tuple[list[MiniDialog], list[str]]
        ``(dialogs, errors)`` — successfully parsed dialogs and error messages
        for any documents that failed to parse, validate, or be read at all.
    """
    dialogs: List[MiniDialog] = []
    errors: List[str] = []

    try:
        for source, doc in _iter_dialog_docs(path_or_dir):
            try:
                dialogs.append(from_json(doc))
            except Exception as e:
                errors.append(f"{source}: {e}")
    except Exception as e:
        errors.append(str(e))

    return dialogs, errors


def load_dialog_registry(path_or_dir: str):
    """Load all dialogs and return a ``DialogRegistry`` keyed for fast lookup.

    This is the primary production entry point for loading dialogs.  Each JSON
    document is isolated: a parse or validation error is logged and that document
    is skipped rather than aborting the entire load.

    Parameters
    ----------
    path_or_dir : str
        Path to a single JSON file or a directory of ``.json`` files.

    Returns
    -------
    DialogRegistry
        Indexed pool of all successfully loaded dialogs.
    """
    # Import here to avoid a circular dependency at module load time.
    from nardial.dialog_registry import DialogRegistry

    dialogs: List[MiniDialog] = []

    try:
        for source, doc in _iter_dialog_docs(path_or_dir):
            try:
                dialogs.append(from_json(doc))
            except Exception as exc:
                logger.error("Skipping entry in %s — failed to load: %s", source, exc)
    except Exception as exc:
        logger.error("Failed to read %s: %s", path_or_dir, exc)

    return DialogRegistry.build(dialogs)


def dialog_to_doc(d: MiniDialog) -> Dict[str, Any]:
    """Serialize a dialog object back to a JSON-ready dict (round-trip)."""
    return to_json(d)


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
