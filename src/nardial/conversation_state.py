from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
import os
import json
import re

from .user_model_proxy import UserModelProxy


class Session:
    def __init__(self, session_id: str, participant_id: Optional[str] = None, run_id: Optional[str] = None,
                 metadata: Optional[Dict[str, Any]] = None, started_at: Optional[str] = None, ended_at: Optional[str] = None,
                 events: Optional[List[Dict[str, Any]]] = None, dialog_ids: Optional[List[str]] = None,
                 summary: Optional[Dict[str, Any]] = None) -> None:
        self.session_id = session_id
        self.participant_id = participant_id
        self.run_id = run_id
        self.metadata = metadata or {}
        self.started_at = started_at or datetime.utcnow().isoformat()
        self.ended_at = ended_at
        self.events: List[Dict[str, Any]] = events or []
        self.dialog_ids: List[str] = dialog_ids or []
        self.summary: Dict[str, Any] = summary or {}


class ConversationState:
    """
    Minimal conversation history manager with per-participant transcripts:
    - continuity: completed_dialogs, user_model, topics_of_interest
    - per-session history: events (your session_history), metadata
    - session-level dialog_ids: ordered, unique IDs used in the session
    - per-participant transcript files under participants/{participant_id}.json
    """

    def __init__(
            self,
            path: Optional[str] = None,
            base_dir: Optional[str] = None,
            participant_id: Optional[str] = None,
            datastore: Optional[Any] = None,
    ) -> None:
        # Determine base directory
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()

        # Default file location inside the caller's project
        self.path = Path(path) if path else self.base_dir / "conversation_state.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # optional datastore (duck-typed interface: .request(message) -> response)
        # ConversationState does not manage Redis details; the proxy will handle datastore construction and checks.
        # ConversationState no longer constructs a default Redis client; the proxy will handle that.
        # self.datastore = datastore

        # continuity
        self.completed_dialogs: List[str] = []
        # store local snapshot from file load in _local_user_model; expose user_model as proxy
        self._local_user_model: Dict[str, Any] = {}
        self.user_model: Any = {}
        self.topics_of_interest: List[str] = []

        # all sessions (append-only)
        self.sessions: List[Session] = []

        # participants folder inside caller's project
        self.participants_dir = self.base_dir / "participants"
        self.participants_dir.mkdir(parents=True, exist_ok=True)

        self.load()

        self.participant_id = participant_id
        # Create the user model proxy (uses local snapshot initially)
        # The proxy will decide whether to use the provided datastore or create a default Redis client.
        proxy_ds = datastore if datastore is not None else None
        self.user_model = UserModelProxy(initial=self._local_user_model, participant_id=self.participant_id, datastore=proxy_ds)

        if self.participant_id is not None:
            self.overwrite_with_participant_info()

    def overwrite_with_participant_info(self) -> None:
        print(f"[INFO] Using participant_id={self.participant_id}")
        pid_completed, pid_topics = self.load_participant_continuity(participant_id=self.participant_id)

        # For a new participant (no file), this will be empty -> fresh run
        self.completed_dialogs = pid_completed or set()
        self.topics_of_interest = pid_topics or []

        # Let the proxy know the participant id and attempt to load from remote if available.
        try:
            if hasattr(self.user_model, "set_participant"):
                self.user_model.set_participant(self.participant_id)
                # If the proxy reports remote availability, ask it to refresh its cache
                if hasattr(self.user_model, "remote_available") and self.user_model.remote_available(check=True):
                    if hasattr(self.user_model, "_ensure_loaded"):
                        self.user_model._ensure_loaded()
        except Exception:
            # ignore failures and continue with local snapshot
            pass

        print(
            f"[DEBUG] Loaded participant continuity: completed={sorted(list(self.completed_dialogs))}, "
            f"topics={self.topics_of_interest}")

    def load_participant_continuity(self, participant_id: str):
        try:
            safe_id = self._sanitize_participant_id(participant_id)
            path = self.participants_dir / f"{safe_id}.json"

            if not path.exists():
                return set(), []

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}

            summary = data.get("summary") or {}
            completed = set(summary.get("dialog_ids_seen") or [])
            topics = list(summary.get("topics_of_interest") or [])

            return completed, topics
        except Exception:
            return set(), []

    def load(self) -> None:
        if not self.path.exists():
            self._initialize_empty_state()
            return

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            # corrupted file fallback
            self._initialize_empty_state()
            return

        self.completed_dialogs = data.get("completed_dialogs", [])
        # keep local snapshot; the user_model proxy will be created later
        self._local_user_model = data.get("user_model", {})
        self.topics_of_interest = data.get("topics_of_interest", [])
        self.sessions = [Session(**s) for s in data.get("sessions", [])]

    def _initialize_empty_state(self) -> None:
        self.completed_dialogs = []
        self._local_user_model = {}
        self.topics_of_interest = []
        self.sessions = []

        self.save()  # create file immediately

    def save(self) -> None:
        # If a remote datastore is available, prefer it and avoid writing user_model into JSON.
        try:
            if hasattr(self.user_model, "remote_available") and self.user_model.remote_available(check=True):
                user_model_data = {}
            else:
                user_model_data = self.user_model.as_dict() if hasattr(self.user_model, "as_dict") else self.user_model
        except Exception:
            user_model_data = self._local_user_model or {}

        data = {
            "completed_dialogs": self.completed_dialogs,
            "user_model": user_model_data,
            "topics_of_interest": self.topics_of_interest,
            "sessions": [s.__dict__ for s in self.sessions],
        }
        self._atomic_write_json(self.path, data)

    # ---------- per-session ----------
    def start_session(self, metadata: Optional[Dict[str, Any]] = None, *, participant_id: Optional[str] = None, run_id: Optional[str] = None) -> str:
        sid = f"sess_{len(self.sessions) + 1:04d}"
        session = Session(session_id=sid, participant_id=participant_id, run_id=run_id, metadata=metadata)
        self.sessions.append(session)
        return sid

    def add_events(self, session_id: str, events: List[Dict[str, Any]]) -> None:
        sess = self._get_session(session_id)
        sess.events.extend(list(events or []))

    def add_dialog_id(self, session_id: str, dialog_id: str) -> None:
        """Use this if you want to record dialog IDs during the run."""
        sess = self._get_session(session_id)
        if sess.dialog_ids is None:
            sess.dialog_ids = []
        if dialog_id not in sess.dialog_ids:
            sess.dialog_ids.append(dialog_id)

    def end_session(self,
                    session_id: str,
                    completed_ids: Optional[Union[List[str], set]] = None,
                    user_model: Optional[Dict[str, Any]] = None,
                    topics_of_interest: Optional[List[str]] = None,
                    extra_summary: Optional[Dict[str, Any]] = None) -> None:
        """Finalize a session, merge continuity, and derive dialog_ids if needed."""
        sess = self._get_session(session_id)
        sess.ended_at = datetime.utcnow().isoformat()
        sess.summary = {
            "user_model": user_model or {},
            "topics_of_interest": topics_of_interest or [],
            **(extra_summary or {})
        }

        # If caller didn't pass completed_ids, derive dialog_ids once from events
        if not completed_ids and not sess.dialog_ids:
            self._derive_dialog_ids_from_events(sess)

        # Continuity merges
        if completed_ids:
            self._merge_completed(completed_ids)
        elif sess.dialog_ids:
            self._merge_completed(sess.dialog_ids)
        if user_model:
            try:
                # Prefer proxy update which will write to datastore if available
                if hasattr(self.user_model, "update"):
                    self.user_model.update(user_model)
                else:
                    self.user_model.update(user_model)
            except Exception:
                # Fallback to in-memory update
                try:
                    self.user_model.update(user_model)
                except Exception:
                    pass
        if topics_of_interest:
            self._merge_interests(topics_of_interest)

        # Write/update per-participant transcript if participant_id present
        pid = sess.participant_id
        if pid:
            # Ensure the proxy is aware of the participant id before saving transcript
            try:
                if hasattr(self.user_model, "set_participant"):
                    self.user_model.set_participant(pid)
            except Exception:
                pass
            self.save_participant_transcript(pid)

    # ---------- helpers ----------
    def _get_session(self, session_id: str) -> Session:
        for s in self.sessions:
            if s.session_id == session_id:
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

    @staticmethod
    def _derive_dialog_ids_from_events(sess: Session) -> None:
        """Build ordered unique dialog_ids from system events in the session history."""
        ids: List[str] = []
        seen = set()
        for ev in sess.events or []:
            if ev.get("type") in {"dialog_start", "dialog_end"}:
                did = ev.get("dialog_id")
                if isinstance(did, str):
                    k = did.strip()
                    if k and k not in seen:
                        ids.append(k)
                        seen.add(k)
        if ids:
            sess.dialog_ids = ids

    # ---------- per-participant transcripts ----------
    def save_participant_transcript(self, participant_id: str) -> None:
        safe_id = self._sanitize_participant_id(participant_id)
        path = Path(self.participants_dir) / f"{safe_id}.json"

        sessions = [s for s in self.sessions if s.participant_id == participant_id]

        payload = {
            "participant_id": participant_id,
            "sessions": [s.__dict__ for s in sessions],
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
        reserved = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}
        if s.upper() in reserved:
            s = f"_{s}"
        return s or "participant"

    @staticmethod
    def _collect_dialog_ids(sessions: List[Session]) -> List[str]:
        seen, ids = set(), []
        for s in sessions:
            for did in s.dialog_ids or []:
                k = str(did).strip()
                if k and k not in seen:
                    ids.append(k)
                    seen.add(k)
        return ids

    @staticmethod
    def _collect_topics_from_summaries(sessions: List[Session]) -> List[str]:
        seen, topics = set(), []
        for s in sessions:
            for t in (s.summary or {}).get("topics_of_interest") or []:
                if isinstance(t, str):
                    k = t.strip().lower()
                    if k and k not in seen:
                        topics.append(t)
                        seen.add(k)
        return topics

    # ---------- safe write ----------
    @staticmethod
    def _atomic_write_json(path: Union[str, Path], data: Dict[str, Any]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = path.with_suffix(path.suffix + ".tmp")

        def _serialize(obj):
            if isinstance(obj, Session):
                return obj.__dict__
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Type not serializable: {type(obj)}")

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=_serialize)

        os.replace(tmp_path, path)
