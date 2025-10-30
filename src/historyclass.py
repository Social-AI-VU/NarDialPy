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

    # ---------- persistence ----------
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
    def start_session(self, metadata: Optional[Dict[str, Any]] = None, *, participant_id: Optional[str] = None) -> str:
        sid = f"sess_{len(self.sessions)+1:04d}"
        self.sessions.append({
            "session_id": sid,
            "participant_id": participant_id,
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



# """
# Conversation history and continuity manager.

# This module provides the ConversationState class, a single place to:
# - persist continuity across runs (STORES completed_dialogs, user_model, topics_of_interest),
# - store per-session event histories (what happened during a run),
# - optionally track per-participant transcripts in separate files,
# - and keep a resume pointer per participant to continue from the last move after a restart.

# All data is stored in a JSON file, Per-participant transcripts are written under
# "participants/{participant_id}.json".
# """

# class ConversationState:
#     """ kEEPS:
#     - Continuity: completed_dialogs, user_model, topics_of_interest
#     - Sessions: append-only list of sessions with metadata, events, summary
#     - Participants: per-participant transcript files
#     - Resume pointers: track the current move for a participant so you can resume
#       exactly where you left off.
#         - Narrative progress: track last position per narrative thread per participant
#             so stories can resume in-context next time.
#     """
#     def __init__(self, path: str = "conversation_state.json"):
#         # file path; WHERE EVERYTHING IS SAVED
#         self.path = path
#         # continuity
#         self.completed_dialogs: List[str] = []
#         self.user_model: Dict[str, Any] = {}
#         self.topics_of_interest: List[str] = []
#         # multi-session history
#         self.sessions: List[Dict[str, Any]] = []
#         # fast lookup for sessions by id (ephemeral, rebuilt on load)
#         self._session_index: Dict[str, Dict[str, Any]] = {}
#         # directory to persist per-participant transcripts (sibling to state file)
#         self.participants_dir: str = os.path.join(os.path.dirname(path) or ".", "participants")
#         # resume pointers: participant_id -> {session_id, dialog_id, move_index, branch, timestamp}
#         self.resume_pointers: Dict[str, Dict[str, Any]] = {}
#         # narrative progress: participant_id -> thread_id -> {last_dialog_id, move_index?, timestamp}
#         self.narrative_progress: Dict[str, Dict[str, Any]] = {}

#     # ------------ persistence ------------
#     # Load and save state to/from JSON file
#     def load(self) -> None:
#         """Load continuity and sessions from disk if the state file exists."""
#         if not os.path.exists(self.path):
#             return
#         with open(self.path, "r", encoding="utf-8") as f:
#             data = json.load(f) or {}
#         self.completed_dialogs = data.get("completed_dialogs", [])
#         self.user_model = data.get("user_model", {})
#         self.topics_of_interest = data.get("topics_of_interest", [])
#         self.sessions = data.get("sessions", [])
#         self.resume_pointers = data.get("resume_pointers", {})
#         self.narrative_progress = data.get("narrative_progress", {})
#         # rebuild index
#         self._session_index = {s.get("session_id"): s for s in self.sessions if s.get("session_id")}


#    
#     def add_events(self, session_id: str, events: List[Dict[str, Any]]) -> None:
#         """Append events to a session, preserving a running index.

#         We store the FULL event dict you provide (questions, responses, and any
#         extra metadata), plus an added "index" field. This ensures the transcript
#         contains everything your runtime captured.

#         If an event has type "move" or "move_progress" and includes a move_index,
#         this will also update the resume pointer for the associated participant
#         automatically.
#         """
#         sess = self._get_session(session_id)
#         base_index = len(sess.get("events", []))
#         for i, ev in enumerate(events):
#             record = dict(ev)  # keep all fields from the original event
#             record["index"] = base_index + i
#             sess.setdefault("events", []).append(record)
#             # If the event describes move progress, auto-update the resume pointer
#             if ev.get("type") in {"move", "move_progress"}:
#                 move_index = ev.get("move_index")
#                 dialog_id = ev.get("dialog_id") or ev.get("dialog")
#                 if isinstance(move_index, int) and dialog_id:
#                     self.update_current_move(
#                         participant_id=sess.get("participant_id"),
#                         session_id=session_id,
#                         dialog_id=dialog_id,
#                         move_index=move_index,
#                         branch=ev.get("branch")
#                     )
#             # If the event closes a narrative step, update narrative progress
#             if ev.get("type") == "dialog_end":
#                 participant_id = sess.get("participant_id")
#                 thread_id = ev.get("thread") or (sess.get("metadata") or {}).get("thread")
#                 # Consider it narrative if explicitly marked or a thread is present
#                 is_narrative = bool(ev.get("narrative") or ev.get("category") == "narrative" or thread_id)
#                 if participant_id and is_narrative and thread_id:
#                     self.update_narrative_progress(
#                         participant_id=participant_id,
#                         thread_id=str(thread_id),
#                         dialog_id=ev.get("dialog_id") or ev.get("dialog") or "",
#                         move_index=None,
#                         auto_save=False,
#                     )

#             completed_ids: Dialog IDs completed this session (merged into continuity).
#             user_model: Updated user model fields from this session (merged).
#             topics_of_interest: New topics learned (merged with de-duplication).
#             extra_summary: Any additional per-session summary you want to store.
#         """
#         # finalize session summary
#         sess = self._get_session(session_id)
#         sess["ended_at"] = datetime.utcnow().isoformat()
#         sess["summary"] = {
#             "user_model": user_model or {},
#             "topics_of_interest": topics_of_interest or [],
#             **(extra_summary or {})
#         }
#         # update continuity
#         if completed_ids:
#             self._merge_completed(completed_ids)
#         elif sess.get("dialog_ids"):
#             # If caller didn't pass explicit completed_ids, merge what was recorded
#             # at session level so we avoid repeating dialogs across sessions.
#             self._merge_completed(sess.get("dialog_ids", []))
#         if user_model:
#             self.user_model.update(user_model)
#         if topics_of_interest:
#             self._merge_interests(topics_of_interest)

#         # persist a per-participant transcript if a participant_id is present
#         participant_id = sess.get("participant_id")
#         if participant_id:
#             try:
#                 self.save_participant_transcript(participant_id)
#             except Exception as e:
#                 # Avoid hard failure on transcript write; caller still controls main save()
#                 print(f"Warning: failed to write participant transcript for {participant_id}: {e}")

#     # ------------ narrative progress (story arcs) ------------
#     def update_narrative_progress(self, *, participant_id: Optional[str], thread_id: str, dialog_id: str, move_index: Optional[int] = None, extra: Optional[Dict[str, Any]] = None, auto_save: bool = True) -> None:
#         """Record last known position in a narrative thread for a participant.

#         Args:
#             participant_id: Who this progress belongs to.
#             thread_id: Narrative thread identifier (e.g., "dreams", "school").
#             dialog_id: The last dialog executed within this thread.
#             move_index: Optional move offset within that dialog (if you resume inside it).
#             extra: Optional dict for custom fields (e.g., scene, chapter).
#         """
#         if not participant_id or not thread_id:
#             return
#         per_user = self.narrative_progress.setdefault(participant_id, {})
#         rec = {
#             "last_dialog_id": dialog_id,
#             "move_index": move_index,
#             "timestamp": datetime.utcnow().isoformat(),
#         }
#         if extra:
#             rec.update(extra)
#         per_user[str(thread_id)] = rec
#         if auto_save:
#             self.save()

#     def get_narrative_progress(self, participant_id: str) -> Dict[str, Any]:
#         """Return all narrative thread progress for a participant (may be empty)."""
#         return self.narrative_progress.get(participant_id, {})

#     def get_thread_progress(self, participant_id: str, thread_id: str) -> Optional[Dict[str, Any]]:
#         """Return the saved pointer for a specific thread of a participant."""
#         return (self.narrative_progress.get(participant_id) or {}).get(str(thread_id))

#     def clear_thread_progress(self, participant_id: str, thread_id: str) -> None:
#         """Clear narrative progress for one thread (e.g., after finishing the story)."""
#         per_user = self.narrative_progress.get(participant_id)
#         if per_user and str(thread_id) in per_user:
#             del per_user[str(thread_id)]
#             self.save()

#     # ------------ resume pointers (current move tracking) ------------
#     def update_current_move(self, *, participant_id: Optional[str], session_id: Optional[str], dialog_id: str, move_index: int, branch: Optional[str] = None, auto_save: bool = True) -> None:
#         """Update the current execution point for a participant.

#         Call this after each successfully executed move so that if the process
#         stops unexpectedly, you can resume at the exact move.

#         Stores (dialog_id, move_index[, branch]) for the participant. With
#         auto_save=True, it immediately persists the state file.
#         """
#         if not participant_id:
#             return
#         self.resume_pointers[participant_id] = {
#             "session_id": session_id,
#             "dialog_id": dialog_id,
#             "move_index": int(move_index),
#             "branch": branch,
#             "timestamp": datetime.utcnow().isoformat(),
#         }
#         if auto_save:
#             self.save()

#     def get_resume_position(self, participant_id: str) -> Optional[Dict[str, Any]]:
#         """Return the last known execution point for this participant, or None."""
#         return self.resume_pointers.get(participant_id)

#     def clear_resume_position(self, participant_id: str) -> None:
#         """Clear the stored execution point for a participant.

#         Use this when a dialog finishes or when you intentionally reset progress.
#         """
#         if participant_id in self.resume_pointers:
#             del self.resume_pointers[participant_id]
#             self.save()
