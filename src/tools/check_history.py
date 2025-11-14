import argparse
import json
import os
from typing import Any, Dict, List


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_history(data: Dict[str, Any]) -> List[str]:
    errs: List[str] = []
    # top-level keys
    for k, typ in (
        ("completed_dialogs", list),
        ("user_model", dict),
        ("topics_of_interest", list),
        ("sessions", list),
    ):
        if not isinstance(data.get(k), typ):
            errs.append(f"missing or invalid '{k}' (expected {typ.__name__})")

    # sessions
    sessions = data.get("sessions") or []
    seen_ids = set()
    for i, s in enumerate(sessions):
        if not isinstance(s, dict):
            errs.append(f"session[{i}] not an object")
            continue
        sid = s.get("session_id")
        if not isinstance(sid, str) or not sid:
            errs.append(f"session[{i}] missing session_id")
        elif sid in seen_ids:
            errs.append(f"duplicate session_id: {sid}")
        else:
            seen_ids.add(sid)
        if not isinstance(s.get("metadata"), dict):
            errs.append(f"session[{i}] metadata missing or not an object")
        if not isinstance(s.get("events"), list):
            errs.append(f"session[{i}] events missing or not a list")
        if not isinstance(s.get("dialog_ids"), list):
            errs.append(f"session[{i}] dialog_ids missing or not a list")
        # Basic event sanity
        for j, ev in enumerate(s.get("events") or []):
            if not isinstance(ev, dict):
                errs.append(f"session[{i}].events[{j}] not an object")
                continue
            if "type" not in ev:
                errs.append(f"session[{i}].events[{j}] missing 'type'")
            if "role" in ev and ev["role"] not in {"robot", "user", "system"}:
                errs.append(f"session[{i}].events[{j}] has unknown role {ev['role']!r}")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate conversation_state.json structure")
    ap.add_argument("path", nargs="?", default="conversation_state.json", help="Path to conversation_state.json")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print(f"[FAIL] File not found: {args.path}")
        return 2
    try:
        data = load_json(args.path)
    except Exception as e:
        print(f"[FAIL] Could not parse {args.path}: {e}")
        return 2

    errs = check_history(data)
    if errs:
        print("[FAIL] History validation errors:")
        for e in errs:
            print(" -", e)
        return 2
    print(
        f"[OK] sessions={len(data.get('sessions') or [])}, "
        f"completed={len(data.get('completed_dialogs') or [])}, "
        f"topics={len(data.get('topics_of_interest') or [])}, "
        f"user_vars={len((data.get('user_model') or {}).keys())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
