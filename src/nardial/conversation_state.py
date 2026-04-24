from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
import os
import json
import re

from .user_model import UserModel


class Session:
    """
    Represents a single conversation session.

    A session contains:
    - Metadata about the interaction (participant, run_id, timestamps)
    - The ordered sequence of events (dialog execution history)
    - Dialog IDs executed during the session
    - A summary (e.g., extracted topics, user model updates)

    Parameters
    ----------
    session_id : str
        Unique identifier for the session (e.g., "sess_0001").
    participant_id : str, optional
        Identifier of the user participating in the session.
    run_id : str, optional
        Identifier for this execution run (useful for experiments/logging).
    metadata : dict, optional
        Arbitrary metadata associated with the session.
    started_at : str, optional
        ISO timestamp when the session started (auto-generated if not provided).
    ended_at : str, optional
        ISO timestamp when the session ended.
    events : list of dict, optional
        Event history (e.g., dialog start/end, user/system actions).
    dialog_ids : list of str, optional
        Ordered list of dialog IDs executed in this session.
    summary : dict, optional
        Aggregated session-level information (topics, user model, etc.).
    """

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
    Manages persistent conversation state across sessions and participants.

    This class provides:
    - Session tracking (start/end, events, dialog execution)
    - Cross-session continuity:
        * completed_dialogs
        * user_model (arbitrary structured data)
        * topics_of_interest
    - Persistent storage of per-participant transcripts

    Data is stored as JSON files under:
        <base_dir>/participants/{participant_id}.json

    If no participant_id is provided, a shared anonymous transcript is used.

    Attributes
    ----------
    participant_id : str or None
        Current participant identifier.
    completed_dialogs : list of str
        Dialog IDs that have been completed across sessions.
    user_model : dict
        Accumulated user-specific information.
    topics_of_interest : list of str
        Extracted topics from past interactions.
    sessions : list of Session
        All sessions associated with the current participant.

    Notes
    -----
    - State is automatically loaded on initialization.
    - State must be explicitly saved (via `save()` or `end_session()`).
    - Dialog continuity is maintained across sessions.
    """

    # Shared transcript key used when participant_id is None.
    ANONYMOUS_PARTICIPANT_ID = "__unknown__"

    def __init__(
            self,
            base_dir: Optional[str] = None,
            participant_id: Optional[str] = None,
            use_json_file: bool = False,
    ) -> None:
        """
        Initialize the conversation state manager.

        Parameters
        ----------
        base_dir : str, optional
            Base directory for storing participant transcripts.
            Defaults to the current working directory.
        participant_id : str, optional
            Identifier for the current user.
        use_json_file : bool, optional
            If True, persist/load shared continuity JSON in addition to participant transcripts.
            If False (default), continuity is backed by UserModel.
        """
        self.participant_id = participant_id
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.use_json_file = use_json_file

        # Optional shared continuity file.
        self.path = self.base_dir / "conversation_state.json"
        if self.use_json_file:
            self.path.parent.mkdir(parents=True, exist_ok=True)

        self.completed_dialogs: List[str] = []
        self.topics_of_interest: List[str] = []
        self.sessions: List[Session] = []

        # participants folder inside caller's project
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.participants_dir = self.base_dir / "participants"
        self.participants_dir.mkdir(parents=True, exist_ok=True)

        if self.use_json_file:
            self.load_state_from_json()

        self.user_model = UserModel(participant_id=self.participant_id)

        if self.participant_id is not None:
            self.restore_participant_state()

    def restore_participant_state(self) -> None:
        print(f"[INFO] Using participant_id={self.participant_id}")
        self.user_model.set_participant(self.participant_id)

        # Load continuity from Redis (default) or JSON file (opt-in).
        if self.use_json_file:
            pid_completed, pid_topics = self.load_participant_continuity(participant_id=self.participant_id)
            self.completed_dialogs = list(pid_completed or [])
            self.topics_of_interest = pid_topics or []
        else:
            self.completed_dialogs = list(self.user_model.get_completed_dialogs())
            self.topics_of_interest = self.user_model.get_topics_of_interest()

    def load_participant_continuity(self, participant_id: Optional[str]) -> tuple[set[str], List[str]]:
        safe_id = self._sanitize_participant_id(participant_id)
        path = self.participants_dir / f"{safe_id}.json"
        if not path.exists():
            return set(), []

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}

            summary = data.get("summary") or {}
            completed = set(summary.get("dialog_ids_seen") or [])
            topics = list(summary.get("topics_of_interest") or [])

            return completed, topics
        except Exception:
            return set(), []

    def load_state_from_json(self) -> None:
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
        self.topics_of_interest = data.get("topics_of_interest", [])
        self.sessions = [Session(**s) for s in data.get("sessions", [])]

    def _initialize_empty_state(self) -> None:
        self.completed_dialogs = []
        self.topics_of_interest = []
        self.sessions = []

        if self.use_json_file:
            self.save_state_to_json()  # create file immediately

    def save_state_to_json(self) -> None:
        if not self.use_json_file:
            return
        data = {
            "completed_dialogs": self.completed_dialogs,
            "topics_of_interest": self.topics_of_interest,
            "sessions": [s.__dict__ for s in self.sessions],
        }
        self._atomic_write_json(self.path, data)

    # Backward-compatible wrapper for existing callers/tests.
    def save(self) -> None:
        self.save_participant_transcript(self.participant_id)

    def start_session(self, metadata: Optional[Dict[str, Any]] = None, *, participant_id: Optional[str] = None, run_id: Optional[str] = None) -> str:
        """
        Create and register a new session.

        Parameters
        ----------
        metadata : dict, optional
            Additional session metadata.
        participant_id : str, optional
            Override participant ID for this session.
        run_id : str, optional
            Identifier for this run.

        Returns
        -------
        str
            The generated session ID.
        """
        sid = f"sess_{len(self.sessions) + 1:04d}"
        session = Session(session_id=sid, participant_id=participant_id, run_id=run_id, metadata=metadata)
        self.sessions.append(session)
        return sid

    def add_events(self, session_id: str, events: List[Dict[str, Any]]) -> None:
        """
        Append events to a session.

        Parameters
        ----------
        session_id : str
            Target session ID.
        events : list of dict
            Events to append (e.g., dialog start/end markers).
        """
        sess = self._get_session(session_id)
        sess.events.extend(list(events or []))

    def add_dialog_id(self, session_id: str, dialog_id: str) -> None:
        """
        Record a dialog ID executed during a session.

        Ensures uniqueness while preserving order.

        Parameters
        ----------
        session_id : str
            Target session ID.
        dialog_id : str
            Dialog identifier.
        """
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
        """
        Finalize a session and merge results into global state.

        Parameters
        ----------
        session_id : str
            Session to finalize.
        completed_ids : list or set, optional
            Dialog IDs completed during the session.
        user_model : dict, optional
            Updates to the persistent user model.
        topics_of_interest : list of str, optional
            Topics extracted from the session.
        extra_summary : dict, optional
            Additional summary fields.

        Behavior
        --------
        - Sets session end timestamp
        - Updates session summary
        - Merges dialog continuity across sessions
        - Updates user model and interests
        - Saves transcript to disk
        """
        sess = self._get_session(session_id)
        sess.ended_at = datetime.utcnow().isoformat()
        user_model_snapshot: Dict[str, Any] = {}
        if isinstance(user_model, dict):
            user_model_snapshot = dict(user_model)
        elif isinstance(user_model, UserModel):
            try:
                user_model_snapshot = dict(user_model.as_dict())
            except Exception:
                user_model_snapshot = {}
        elif user_model is not None:
            try:
                user_model_snapshot = dict(user_model)
            except Exception:
                user_model_snapshot = {}

        sess.summary = {
            "user_model": user_model_snapshot,
            "topics_of_interest": topics_of_interest or [],
            **(extra_summary or {})
        }

        if not completed_ids and not sess.dialog_ids:
            self._derive_dialog_ids_from_events(sess)

        if completed_ids:
            normalized_completed_ids = [str(did).strip() for did in completed_ids if str(did).strip()]
            if not sess.dialog_ids:
                sess.dialog_ids = normalized_completed_ids
            self._merge_completed(normalized_completed_ids)
        elif sess.dialog_ids:
            self._merge_completed(sess.dialog_ids)

        if user_model:
            self.user_model.update(user_model)
        if topics_of_interest:
            self._merge_interests(topics_of_interest)

        # Persist continuity to Redis (always, regardless of use_json_file).
        pid = sess.participant_id
        if pid:
            self.user_model.set_participant(pid)
            self.user_model.save_continuity(
                completed_dialogs=list(self.completed_dialogs),
                topics_of_interest=list(self.topics_of_interest),
            )

        # Write per-participant JSON transcript.
        target_participant_id = sess.participant_id if sess.participant_id is not None else self.participant_id
        self.save_participant_transcript(target_participant_id)

    def _get_session(self, session_id: str) -> Session:
        """Retrieve a session by ID."""
        for s in self.sessions:
            if s.session_id == session_id:
                return s
        raise KeyError(f"Session {session_id} not found")

    def _merge_completed(self, completed_ids: Union[List[str], set]) -> None:
        """Merge completed dialog IDs into global state."""
        prev = set(self.completed_dialogs)
        self.completed_dialogs = list(prev.union(set(completed_ids)))

    def _merge_interests(self, topics: List[str]) -> None:
        """Merge and deduplicate topics of interest."""
        seen = {str(x).strip().lower() for x in self.topics_of_interest}
        for t in topics or []:
            k = str(t).strip().lower()
            if k and k not in seen:
                self.topics_of_interest.append(t)
                seen.add(k)

    @staticmethod
    def _derive_dialog_ids_from_events(sess: Session) -> None:
        """
        Derive dialog IDs from session events if not explicitly recorded.

        Looks for 'dialog_start' and 'dialog_end' events.
        """
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

    def save_participant_transcript(self, participant_id: Optional[str]) -> None:
        """
        Save all sessions for a participant to a JSON transcript file.

        Parameters
        ----------
        participant_id : str or None
            Target participant identifier.
        """
        target_id = self._sanitize_participant_id(participant_id)
        path = Path(self.participants_dir) / f"{target_id}.json"

        sessions = [
            s for s in self.sessions
            if self._sanitize_participant_id(s.participant_id) == target_id
        ]

        payload = {
            "participant_id": participant_id if participant_id is not None else target_id,
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
    def _sanitize_participant_id(participant_id: Optional[str]) -> str:
        """
        Normalize participant IDs to safe filesystem names.
        """
        if participant_id is None:
            return ConversationState.ANONYMOUS_PARTICIPANT_ID
        s = str(participant_id).strip()
        s = re.sub(r"\s+", "_", s)
        s = re.sub(r"[^A-Za-z0-9._-]", "_", s)
        reserved = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}
        if s.upper() in reserved:
            s = f"_{s}"
        return s or "participant"

    @staticmethod
    def _collect_dialog_ids(sessions: List[Session]) -> List[str]:
        """Collect unique dialog IDs across sessions."""
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
        """Collect unique topics across session summaries."""
        seen, topics = set(), []
        for s in sessions:
            for t in (s.summary or {}).get("topics_of_interest") or []:
                if isinstance(t, str):
                    k = t.strip().lower()
                    if k and k not in seen:
                        topics.append(t)
                        seen.add(k)
        return topics

    @staticmethod
    def _atomic_write_json(path: Union[str, Path], data: Dict[str, Any]) -> None:
        """
        Safely write JSON to disk using an atomic replace.

        Prevents file corruption if the process is interrupted.
        """
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

        print(f"[INFO] Saved conversation state to {path}")