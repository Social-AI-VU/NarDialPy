from typing import Any, Dict, List, Optional, Union
from datetime import datetime
import os
import json
import re

class ConversationState:
    """
    Minimal conversation history manager with per-participant transcripts:
    - continuity: completed_dialogs, user_model, topics_of_interest
    - per-session history: events (your session_history), metadata
    - session-level dialog_ids: ordered, unique IDs used in the session
    - per-participant transcript files under participants/{participant_id}.json
    """

    def __init__(self, path: str = "conversation_state.json"):
        self.path = path
        # continuity
        self.completed_dialogs: List[str] = []
        self.user_model: Dict[str, Any] = {}
        self.topics_of_interest: List[str] = []
        # all sessions (append-only)
        self.sessions: List[Dict[str, Any]] = []
        # where per-participant files go
        self.participants_dir: str = os.path.join(os.path.dirname(path) or ".", "participants")

    def load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        self.completed_dialogs = data.get("completed_dialogs", [])
        self.user_model = data.get("user_model", {})
        self.topics_of_interest = data.get("topics_of_interest", [])
        self.sessions = data.get("sessions", [])

    def save(self) -> None:
        data = {
            "completed_dialogs": self.completed_dialogs,
            "user_model": self.user_model,
            "topics_of_interest": self.topics_of_interest,
            "sessions": self.sessions,
        }
        self._atomic_write_json(self.path, data)

    # ---------- per-session ----------
    def start_session(self, metadata: Optional[Dict[str, Any]] = None, *, participant_id: Optional[str] = None, run_id: Optional[str] = None) -> str:
        sid = f"sess_{len(self.sessions)+1:04d}"
        self.sessions.append({
            "session_id": sid,
            "participant_id": participant_id,
            "run_id": run_id,
            "metadata": metadata or {},
            "started_at": datetime.utcnow().isoformat(),
            "ended_at": None,
            "events": [],
            "dialog_ids": [],   # you can fill this during run, or it will be derived at end
            "summary": {},
        })
        return sid

    def add_events(self, session_id: str, events: List[Dict[str, Any]]) -> None:
        sess = self._get_session(session_id)
        sess["events"].extend(list(events or []))

    def add_dialog_id(self, session_id: str, dialog_id: str) -> None:
        """Use this if you want to record dialog IDs during the run."""
        sess = self._get_session(session_id)
        lst = sess.setdefault("dialog_ids", [])
        if dialog_id not in lst:
            lst.append(dialog_id)

    def end_session(self,
                    session_id: str,
                    completed_ids: Optional[Union[List[str], set]] = None,
                    user_model: Optional[Dict[str, Any]] = None,
                    topics_of_interest: Optional[List[str]] = None,
                    extra_summary: Optional[Dict[str, Any]] = None) -> None:
        """Finalize a session, merge continuity, and derive dialog_ids if needed."""
        sess = self._get_session(session_id)
        sess["ended_at"] = datetime.utcnow().isoformat()
        sess["summary"] = {
            "user_model": user_model or {},
            "topics_of_interest": topics_of_interest or [],
            **(extra_summary or {})
        }

        # If caller didn't pass completed_ids, derive dialog_ids once from events
        if not completed_ids and not sess.get("dialog_ids"):
            self._derive_dialog_ids_from_events(sess)

        # Continuity merges
        if completed_ids:
            self._merge_completed(completed_ids)
        elif sess.get("dialog_ids"):
            self._merge_completed(sess["dialog_ids"])
        if user_model:
            self.user_model.update(user_model)
        if topics_of_interest:
            self._merge_interests(topics_of_interest)

        # Write/update per-participant transcript if participant_id present
        pid = sess.get("participant_id")
        if pid:
            self.save_participant_transcript(pid)

    # ---------- helpers ----------
    def _get_session(self, session_id: str) -> Dict[str, Any]:
        for s in self.sessions:
            if s.get("session_id") == session_id:
                return s
        raise KeyError(f"Session {session_id} not found")

    def _merge_completed(self, completed_ids: Union[List[str], set]) -> None:
        prev = set(self.completed_dialogs)
        self.completed_dialogs = list(prev.union(set(completed_ids)))

    def _merge_interests(self, topics: List[str]) -> None:
        seen = {str(x).strip().lower() for x in self.topics_of_interest}
        for t in topics or []:
            k = str(t).strip().lower()
            if k and k not in seen:
                self.topics_of_interest.append(t)
                seen.add(k)

    def _derive_dialog_ids_from_events(self, sess: Dict[str, Any]) -> None:
        """Build ordered unique dialog_ids from system events in the session history."""
        ids: List[str] = []
        seen = set()
        for ev in sess.get("events") or []:
            if ev.get("type") in {"dialog_start", "dialog_end"}:
                did = ev.get("dialog_id")
                if isinstance(did, str):
                    k = did.strip()
                    if k and k not in seen:
                        ids.append(k)
                        seen.add(k)
        if ids:
            sess["dialog_ids"] = ids

    # ---------- per-participant transcripts ----------
    def save_participant_transcript(self, participant_id: str) -> None:
        """Write all sessions for this participant to participants/{participant_id}.json."""
        os.makedirs(self.participants_dir, exist_ok=True)
        safe_id = self._sanitize_participant_id(participant_id)
        path = os.path.join(self.participants_dir, f"{safe_id}.json")
        sessions = [s for s in self.sessions if s.get("participant_id") == participant_id]
        payload = {
            "participant_id": participant_id,
            "sessions": sessions,
            "summary": {
                "total_sessions": len(sessions),
                "dialog_ids_seen": self._collect_dialog_ids(sessions),
                "topics_of_interest": self._collect_topics_from_summaries(sessions),
                "last_updated": datetime.utcnow().isoformat(),
            },
        }
        self._atomic_write_json(path, payload)

    @staticmethod
    def _sanitize_participant_id(participant_id: str) -> str:
        s = str(participant_id).strip()
        s = re.sub(r"\s+", "_", s)
        s = re.sub(r"[^A-Za-z0-9._-]", "_", s)
        reserved = {"CON","PRN","AUX","NUL","COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9","LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9"}
        if s.upper() in reserved:
            s = f"_{s}"
        return s or "participant"

    @staticmethod
    def _collect_dialog_ids(sessions: List[Dict[str, Any]]) -> List[str]:
        seen, ids = set(), []
        for s in sessions:
            for did in s.get("dialog_ids") or []:
                k = str(did).strip()
                if k and k not in seen:
                    ids.append(k)
                    seen.add(k)
        return ids

    @staticmethod
    def _collect_topics_from_summaries(sessions: List[Dict[str, Any]]) -> List[str]:
        seen, topics = set(), []
        for s in sessions:
            for t in (s.get("summary") or {}).get("topics_of_interest") or []:
                if isinstance(t, str):
                    k = t.strip().lower()
                    if k and k not in seen:
                        topics.append(t)
                        seen.add(k)
        return topics

    # ---------- safe write ----------
    def _atomic_write_json(self, path: str, data: Dict[str, Any]) -> None:
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)