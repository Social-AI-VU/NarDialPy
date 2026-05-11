import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timezone
import os
import json
import re

from pydantic import BaseModel, Field

from .user_model import UserModel

logger = logging.getLogger(__name__)


class Session(BaseModel):
    """
    Represents a single conversation session.

    A session contains:
    - Metadata about the interaction (participant, run_id, timestamps)
    - The ordered sequence of events (dialog execution history)
    - Dialog IDs executed during the session
    - A summary (e.g., extracted topics, user model updates)

    Attributes
    ----------
    session_id : str
        Unique identifier for the session (e.g., "sess_0001").
    participant_id : str, optional
        Identifier of the user participating in the session.
    run_id : str, optional
        Identifier for this execution run (useful for experiments/logging).
    metadata : dict, optional
        Arbitrary metadata associated with the session.
    started_at : str
        ISO timestamp when the session started (auto-generated on construction).
    ended_at : str, optional
        ISO timestamp when the session ended.
    events : list of dict
        Event history (e.g., dialog start/end, user/system actions).
    dialog_ids : list of str
        Ordered list of dialog IDs executed in this session.
    summary : dict
        Aggregated session-level information (topics, user model, etc.).
    """

    session_id: str
    participant_id: Optional[str] = None
    run_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ended_at: Optional[str] = None
    events: List[Dict[str, Any]] = Field(default_factory=list)
    dialog_ids: List[str] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)


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
        self.participants_dir = self.base_dir / "participants"
        self.participants_dir.mkdir(parents=True, exist_ok=True)

        if self.use_json_file:
            self.load_state_from_json()

        self.user_model = UserModel(participant_id=self.participant_id)

        if self.participant_id is not None:
            self.restore_participant_state()

    def restore_participant_state(self) -> None:
        """Load continuity data (completed dialogs, topics) for the current participant.

        Reads from Redis (default) or the shared JSON file (when ``use_json_file=True``).
        Called automatically from ``__init__`` when a ``participant_id`` is provided.
        """
        logger.info("Using participant_id=%s", self.participant_id)
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
        """Load shared continuity state from the JSON file at ``self.path``.

        Only called when ``use_json_file=True``.  Falls back to an empty state
        when the file does not exist or is corrupt.
        """
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
        self.sessions = [Session.model_validate(s) for s in data.get("sessions", [])]

    def _initialize_empty_state(self) -> None:
        """Reset in-memory state to empty and, when ``use_json_file=True``, write a blank file."""
        self.completed_dialogs = []
        self.topics_of_interest = []
        self.sessions = []

        if self.use_json_file:
            self.save_state_to_json()  # create file immediately

    def save_state_to_json(self) -> None:
        """Write shared continuity state to ``self.path``.

        No-op when ``use_json_file=False``.
        """
        if not self.use_json_file:
            return
        data = {
            "completed_dialogs": self.completed_dialogs,
            "topics_of_interest": self.topics_of_interest,
            "sessions": [s.model_dump() for s in self.sessions],
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
        session = Session(session_id=sid, participant_id=participant_id, run_id=run_id, metadata=metadata or {})
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
        sess.ended_at = datetime.now(timezone.utc).isoformat()
        user_model_snapshot: Dict[str, Any] = {}
        if isinstance(user_model, dict):
            user_model_snapshot = dict(user_model)
        elif isinstance(user_model, UserModel):
            try:
                user_model_snapshot = dict(user_model.as_dict())
            except Exception as exc:
                logger.warning("end_session: failed to snapshot UserModel: %s", exc)
                user_model_snapshot = {}
        elif user_model is not None:
            try:
                user_model_snapshot = dict(user_model)
            except Exception as exc:
                logger.warning("end_session: failed to convert user_model to dict: %s", exc)
                user_model_snapshot = {}

        sess.summary = {
            "user_model": user_model_snapshot,
            "topics_of_interest": topics_of_interest or [],
            **(extra_summary or {})
        }

        if completed_ids is None and not sess.dialog_ids:
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

        # Use the accumulated completed_dialogs / topics_of_interest as the
        # authoritative source so that cross-session continuity is preserved
        # even when prior sessions are not held in memory.
        payload = {
            "participant_id": participant_id if participant_id is not None else target_id,
            "sessions": [s.model_dump() for s in sessions],
            "summary": {
                "total_sessions": sum(1 for s in sessions if s.ended_at is not None),
                "dialog_ids_seen": list(self.completed_dialogs),
                "topics_of_interest": list(self.topics_of_interest),
                "last_updated": datetime.now(timezone.utc).isoformat(),
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

    # ── Session-plan helpers ──────────────────────────────────────────────────

    def _load_participant_json(self) -> Dict[str, Any]:
        """Load the raw participant JSON, returning an empty dict if unavailable.

        Used by session-plan helpers that need the full session list even when
        the in-memory ``sessions`` list is empty (the default when
        ``use_json_file=False``).
        """
        if self.participant_id is None:
            return {}
        safe_id = self._sanitize_participant_id(self.participant_id)
        path = self.participants_dir / f"{safe_id}.json"
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception as exc:
            logger.warning("Could not read participant JSON for %r: %s", self.participant_id, exc)
            return {}

    def count_completed_sessions(self) -> int:
        """Return the number of completed (ended) sessions from the participant JSON.

        Reads the persisted transcript rather than the in-memory ``sessions``
        list so the count is accurate even when the file backend is not loaded
        (``use_json_file=False``).  Returns 0 when no participant data exists.

        Returns
        -------
        int
        """
        data = self._load_participant_json()
        return data.get("summary", {}).get("total_sessions", 0)

    def find_incomplete_session(self) -> Optional["Session"]:
        """Check whether the participant's last session is incomplete.

        A session is incomplete when its ``ended_at`` field is ``None``.
        Loads the participant JSON to inspect the last session.

        Returns
        -------
        Session or None
            The incomplete session, or ``None`` if the last session is complete
            or no sessions exist.
        """
        data = self._load_participant_json()
        sessions_data = data.get("sessions", [])
        if not sessions_data:
            return None
        try:
            last = Session.model_validate(sessions_data[-1])
        except Exception as exc:
            logger.warning("find_incomplete_session: could not parse last session: %s", exc)
            return None
        return last if last.ended_at is None else None

    def truncate_from_session(self, from_session: int) -> None:
        """Remove sessions from session N onward and recompute persistent state.

        Loads the participant JSON to get the full session list (which may not
        be in the in-memory ``sessions`` list when ``use_json_file=False``),
        retains only the sessions whose 1-based index is strictly less than
        *from_session*, recomputes ``completed_dialogs`` and
        ``topics_of_interest`` from the retained sessions, and writes the
        truncated transcript back to disk.

        Parameters
        ----------
        from_session : int
            1-based session number.  Sessions at this index and beyond are
            removed.  ``from_session=2`` keeps only the first session.
        """
        data = self._load_participant_json()
        all_sessions_data = data.get("sessions", [])
        try:
            all_sessions = [Session.model_validate(s) for s in all_sessions_data]
        except Exception as exc:
            logger.warning("truncate_from_session: could not parse session list: %s", exc)
            return

        retained = all_sessions[: from_session - 1]
        self.sessions = retained
        self.completed_dialogs = self._collect_dialog_ids(retained)
        self.topics_of_interest = self._collect_topics_from_summaries(retained)

        # Persist the truncated state.
        self.save_participant_transcript(self.participant_id)
        if self.use_json_file:
            self.save_state_to_json()

        # Mirror the truncated state to Redis so subsequent sessions read
        # the correct completed_dialogs regardless of which backend is active.
        if self.participant_id is not None:
            self.user_model.save_continuity(
                completed_dialogs=list(self.completed_dialogs),
                topics_of_interest=list(self.topics_of_interest),
            )

        logger.info(
            "History truncated to %d session(s); completed_dialogs=%s",
            len(retained),
            self.completed_dialogs,
        )

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
                return obj.model_dump()
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Type not serializable: {type(obj)}")

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=_serialize)

        os.replace(tmp_path, path)

        logger.info("Saved conversation state to %s", path)