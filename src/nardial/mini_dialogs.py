from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Optional, List, cast, Dict
import re
from time import monotonic

from nardial.moves import MOVE_SAY, MOVE_ASK_YESNO, MOVE_ASK_OPEN, MOVE_ASK_OPTIONS, MOVE_PLAY_AUDIO, MOVE_MOTION_SEQUENCE, \
    MOVE_ANIMATION, \
    MoveAskYesNo, MoveAskOpen, MoveAskOptions, MovePlayAudio, MoveMotionSequence, MoveAnimation, MoveBranch, \
    MOVE_ANSWER_OPEN, MOVE_ANSWER_YESNO, MOVE_ANSWER_OPTIONS, MoveAskLLM, MOVE_ASK_LLM, MOVE_ANSWER_LLM, \
    MOVE_LLM_FOLLOWUP, MOVE_BRANCH

from enum import Enum


class DialogType(Enum):
    NARRATIVE = "narrative"
    CHITCHAT = "chitchat"
    FUNCTIONAL = "functional"
    LLM_BASED = "llm_based"


MAX_LLM_TURNS = 5
# Default ElevenLabs values used when character voice settings omit voice/model details.
DEFAULT_ELEVENLABS_VOICE_ID = "yO6w2xlECAQRFP6pX7Hw"
DEFAULT_ELEVENLABS_MODEL_ID = "eleven_flash_v2_5"


class MiniDialog:
    def __init__(self, dialog_id, moves, dependencies=None, variable_dependencies=None, characters=None):
        """
        dialog_id: str, unique identifier (e.g. 'pineapple_on_pizza')
        moves: list of dicts, each representing a dialog move
        attributes: dict, extra attributes depending on dialog type
        """
        self.dialog_id = dialog_id
        self.moves = moves
        self.dependencies = dependencies or []
        self.variable_dependencies = variable_dependencies or []
        self.characters = dict(characters or {})

        self.conversation_agent = None
        self.session_history = []
        self.topics_of_interest = []
        self.user_model = {}
        self.current_outcome = None
        self._default_tts_conf = None
        self._default_language = None

    def set_conversation_config(self, agent, session_history, topics_of_interest, user_model):
        self.conversation_agent = agent
        self.session_history = session_history if session_history is not None else []
        self.topics_of_interest = topics_of_interest if topics_of_interest is not None else []
        self.user_model = user_model if user_model is not None else {}
        orchestrator = getattr(agent, "orchestrator", None)
        if orchestrator is not None:
            self._default_tts_conf = getattr(orchestrator, "tts_conf", None)
            interaction_conf = getattr(orchestrator, "interaction_conf", None)
            self._default_language = getattr(interaction_conf, "language", None) if interaction_conf is not None else None

    # Helper to read either dict-style or attribute-style moves (supports MoveSay objects)
    @staticmethod
    def _get(move, key, default=None):
        try:
            if isinstance(move, dict):
                return move.get(key, default)
            # Fallback to attribute access for move objects
            return getattr(move, key, default)
        except Exception:
            return default

    @staticmethod
    def add_interest(topics_of_interest, topic):
        if topics_of_interest is None or not topic:
            return
        t = str(topic).strip()
        if not t:
            return
        low = t.lower()
        if all(low != str(x).lower() for x in topics_of_interest):
            topics_of_interest.append(t)

    def _record_robot(self, type_name: str, text: str, **extra):
        entry = {"role": "robot", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _record_user(self, type_name: str, text: str, **extra):
        entry = {"role": "user", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _record_system(self, type_name: str, text: str, **extra):
        entry = {"role": "system", "type": type_name, "text": text}
        entry.update(extra)
        self.session_history.append(entry)

    def _store_set_variable(self, move, answer: str):
        if not answer:
            return
        if getattr(move, 'set_variable', None):
            self.user_model[move.set_variable] = self.extract_open_value(answer)

    def _store_interests(self, move, answer: str):
        if answer and getattr(move, 'add_interest_from_answer', False):
            self.add_interest(self.topics_of_interest, answer)
        if getattr(move, 'add_interest_from_variable', None):
            val = self.user_model.get(move.add_interest_from_variable)
            if val:
                self.add_interest(self.topics_of_interest, val)

    @staticmethod
    def extract_open_value(answer: str) -> str:
        """
        General-purpose cleaner for open answers used with set_variable.
        Heuristics (language-agnostic):
        - If quoted text is present, return the first quoted segment.
        - Otherwise, return the last alphabetic token (e.g., 'zebra' from 'my favorite animal is a zebra').
        - Fallback to trimmed original answer if nothing matches.
        """
        if not answer:
            return ""
        text = str(answer).strip()
        # Prefer explicitly quoted content
        m = re.search(r'["\']([^"\']+)["\']', text)
        if m:
            return m.group(1).strip()
        # Fallback: pick the last alphabetic-ish token
        tokens = re.findall(r"[A-Za-z][A-Za-z\-']+", text)
        if tokens:
            return tokens[-1]
        return text

    def run(self, agent, session_history=None, topics_of_interest=None, user_model=None):
        # Execute mini dialogs, sending speech to the device and logging events.
        self.set_conversation_config(agent, session_history, topics_of_interest, user_model)

        idx = 0

        while idx < len(self.moves):
            move = self.moves[idx]
            self._dispatch_move(move)
            idx += 1

    def _resolve_outcome(self, move, answer) -> None:
        """Resolve and store ``current_outcome`` from the declarative outcome fields.

        Resolution order:
        1. Exact match: if ``answer`` appears as a key in ``outcomes``, use that label.
        2. Wildcard: if ``"*"`` is a key in ``outcomes`` and ``answer`` is non-empty,
           use that label (useful for free-text ``ask_open`` answers).
        3. Default: ``default_outcome`` is used when the answer is empty/None, or
           when no exact or wildcard match is found.
        """
        outcomes = self._get(move, 'outcomes') or {}
        default_outcome = self._get(move, 'default_outcome')
        if answer and answer in outcomes:
            self.current_outcome = outcomes[answer]
        elif answer and "*" in outcomes:
            self.current_outcome = outcomes["*"]
        else:
            self.current_outcome = default_outcome

    def handle_move_branch(self, move) -> None:
        """Execute the sub-moves for the matching case of a ``branch`` move."""
        move = MoveBranch.from_dict(move)
        if move.on == "outcome":
            key = self.current_outcome
        else:
            key = self.user_model.get(move.on)
        case_moves = move.cases.get(key, [])
        for sub_move in case_moves:
            self._dispatch_move(sub_move)

    def _dispatch_move(self, move) -> None:
        """Execute a single move dict."""
        move_type = self._get(move, 'type')
        if move_type == MOVE_BRANCH:
            self.handle_move_branch(move)
            return

        with self._character_voice_context(move):
            if move_type == MOVE_SAY:
                self.handle_move_say(move)
            elif move_type == MOVE_ASK_YESNO:
                answer = self.handle_move_ask_yesno(move)
                self._resolve_outcome(move, answer)
            elif move_type == MOVE_ASK_OPEN:
                answer = self.handle_move_ask_open(move)
                self._resolve_outcome(move, answer)
            elif move_type == MOVE_ASK_OPTIONS:
                answer = self.handle_move_ask_options(move)
                self._resolve_outcome(move, answer)
            elif move_type == MOVE_PLAY_AUDIO:
                self.handle_move_play_audio(move)
            elif move_type == MOVE_MOTION_SEQUENCE:
                self.handle_move_motion_sequence(move)
            elif move_type == MOVE_ANIMATION:
                self.handle_move_animation(move)
            elif move_type == MOVE_ASK_LLM:
                self.handle_move_ask_llm(move)

    @staticmethod
    def _infer_tts_type_from_conf(tts_conf: Optional[Any]) -> Optional[str]:
        if tts_conf is None:
            return None
        try:
            from nardial.tts_manager import GoogleTTSConf, ElevenLabsTTSConf, NaoqiTTSConf
            if isinstance(tts_conf, ElevenLabsTTSConf):
                return "elevenlabs"
            if isinstance(tts_conf, GoogleTTSConf):
                return "google"
            if isinstance(tts_conf, NaoqiTTSConf):
                return "naoqi"
        except ImportError:
            pass

        class_name = type(tts_conf).__name__.lower()
        if "elevenlabs" in class_name:
            return "elevenlabs"
        if "google" in class_name:
            return "google"
        if "naoqi" in class_name:
            return "naoqi"
        return None

    @staticmethod
    def _map_voice_settings_to_tts_conf(voice_settings: Dict[str, Any], fallback_tts_conf: Optional[Any]) -> Optional[Any]:
        if not isinstance(voice_settings, dict):
            return None

        GoogleTTSConf = None
        ElevenLabsTTSConf = None
        NaoqiTTSConf = None
        try:
            from nardial import tts_manager
            GoogleTTSConf = tts_manager.GoogleTTSConf
            ElevenLabsTTSConf = tts_manager.ElevenLabsTTSConf
            NaoqiTTSConf = tts_manager.NaoqiTTSConf
        except ImportError:
            pass

        default_tts_type = MiniDialog._infer_tts_type_from_conf(fallback_tts_conf)
        voice_tts_type = (voice_settings.get("tts_type") or "").strip().lower()
        if voice_tts_type and not default_tts_type:
            raise ValueError(
                f"Character voice_settings.tts_type '{voice_tts_type}' requires a known default interaction tts_type"
            )
        if voice_tts_type and default_tts_type and voice_tts_type != default_tts_type:
            raise ValueError(
                f"Character voice_settings.tts_type '{voice_tts_type}' must match default interaction tts_type '{default_tts_type}'"
            )
        tts_type = default_tts_type or voice_tts_type

        speaking_rate = voice_settings.get("speaking_rate")
        voice_id = voice_settings.get("voice_id")
        if voice_id is not None and not isinstance(voice_id, str):
            raise ValueError("voice_settings.voice_id must be a string when provided")

        if tts_type == "elevenlabs":
            default_model_id = getattr(fallback_tts_conf, "model_id", DEFAULT_ELEVENLABS_MODEL_ID)
            payload = {
                "speaking_rate": speaking_rate,
                "voice_id": voice_id or getattr(fallback_tts_conf, "voice_id", DEFAULT_ELEVENLABS_VOICE_ID),
                "model_id": voice_settings.get("model_id", default_model_id),
            }
            if ElevenLabsTTSConf is not None:
                return ElevenLabsTTSConf(**payload)
            return SimpleNamespace(**payload)
        if tts_type == "google":
            payload = {
                "speaking_rate": speaking_rate if speaking_rate is not None else getattr(fallback_tts_conf, "speaking_rate", 1.0),
                "google_tts_voice_name": voice_id or getattr(fallback_tts_conf, "google_tts_voice_name", "en-US-Standard-C"),
                "google_tts_voice_gender": voice_settings.get("voice_gender", getattr(fallback_tts_conf, "google_tts_voice_gender", "FEMALE")),
            }
            if GoogleTTSConf is not None:
                return GoogleTTSConf(**payload)
            return SimpleNamespace(**payload)
        if tts_type == "naoqi":
            language = voice_settings.get("language") or getattr(fallback_tts_conf, "language", "English")
            if NaoqiTTSConf is not None:
                return NaoqiTTSConf(language=language)
            return SimpleNamespace(language=language)
        return None

    @contextmanager
    def _character_voice_context(self, move):
        character_id = self._get(move, "character")
        if not character_id:
            yield
            return

        # Keep runtime checks for programmatically constructed dialogs that bypass authoring validation.
        if character_id not in self.characters:
            raise ValueError(f"Move references unknown character '{character_id}' in dialog '{self.dialog_id}'")
        character = self.characters.get(character_id)
        if not isinstance(character, dict):
            raise ValueError(f"Character '{character_id}' must be an object")
        voice_settings = character.get("voice_settings")
        if not isinstance(voice_settings, dict):
            raise ValueError(f"Character '{character_id}' must define a voice_settings object")

        orchestrator = getattr(self.conversation_agent, "orchestrator", None)
        if orchestrator is None:
            yield
            return

        interaction_conf = getattr(orchestrator, "interaction_conf", None)
        original_tts_conf = getattr(orchestrator, "tts_conf", None)
        original_interaction_tts = getattr(interaction_conf, "tts_conf", None) if interaction_conf is not None else None
        original_language = getattr(interaction_conf, "language", None) if interaction_conf is not None else None

        mapped_tts_conf = self._map_voice_settings_to_tts_conf(voice_settings, self._default_tts_conf or original_tts_conf)
        if mapped_tts_conf is not None:
            orchestrator.tts_conf = mapped_tts_conf
            if interaction_conf is not None:
                interaction_conf.tts_conf = mapped_tts_conf
        language = voice_settings.get("language")
        if interaction_conf is not None and language:
            interaction_conf.language = language

        try:
            yield
        finally:
            orchestrator.tts_conf = original_tts_conf
            if interaction_conf is not None:
                interaction_conf.tts_conf = original_interaction_tts
                interaction_conf.language = original_language

    def _generate_llm_followup(self, user_answer: str, system_prompt: str):
        """Call the LLM to generate a contextual followup to the user's answer and speak it."""
        context_messages = [
            entry.get("text", "") for entry in self.session_history if entry.get("text") is not None
        ]
        llm_text = self.conversation_agent.ask_llm(
            user_prompt=user_answer,
            context_messages=context_messages,
            system_prompt=system_prompt,
        )
        if llm_text:
            self.conversation_agent.say(llm_text)
            self._record_robot(MOVE_LLM_FOLLOWUP, llm_text)

    def handle_move_say(self, move):
        text = self._get(move, 'text')
        for var, value in self.user_model.items():
            text = text.replace(f"%{var}%", str(value))
        self.conversation_agent.say(text)
        self._record_robot(MOVE_SAY, text)

    def handle_move_ask_yesno(self, move):
        move = MoveAskYesNo.from_dict(move)
        answer = self.conversation_agent.ask_yesno(move.text)
        self._record_robot(MOVE_ASK_YESNO, move.text)
        self._record_user(MOVE_ANSWER_YESNO, answer)
        print(f"User answered: {answer}")

        # store answer and interest if configured
        self._store_set_variable(move, answer)
        if answer == "yes" and getattr(move, 'add_interest', None):
            self.add_interest(self.topics_of_interest, move.add_interest)

        # Optional LLM-generated followup response
        if move.llm_followup:
            self._generate_llm_followup(user_answer=answer or "", system_prompt=move.llm_followup)

        return answer

    def handle_move_ask_open(self, move):
        move = MoveAskOpen.from_dict(move)
        answer = self.conversation_agent.ask_open(move.text)
        self._record_robot(MOVE_ASK_OPEN, move.text)
        self._record_user(MOVE_ANSWER_OPEN, answer)
        print(f"User answered: {answer}")

        # store answer and interests if configured
        self._store_set_variable(move, answer)
        self._store_interests(move, answer)

        # Optional LLM-generated followup response
        if move.llm_followup:
            self._generate_llm_followup(user_answer=answer or "", system_prompt=move.llm_followup)

        return answer

    def handle_move_ask_options(self, move):
        move = MoveAskOptions.from_dict(move)
        answer = self.conversation_agent.ask_options(move.text, move.options)
        self._record_robot(MOVE_ASK_OPTIONS, move.text, options=move.options)
        self._record_user(MOVE_ANSWER_OPTIONS, answer)
        print(f"User answered: {answer}")

        # store answer if configured
        self._store_set_variable(move, answer)
        self._store_interests(move, answer)

        # Optional LLM-generated followup response
        if move.llm_followup:
            self._generate_llm_followup(user_answer=answer or "", system_prompt=move.llm_followup)

        return answer

    def handle_move_play_audio(self, move):
        move = MovePlayAudio.from_dict(move)
        self.conversation_agent.play_audio(move.audio_file)
        self._record_robot(MOVE_PLAY_AUDIO, "Played audio. ", audio_file=move.audio_file)

    def handle_move_motion_sequence(self, move):
        move = MoveMotionSequence.from_dict(move)
        self.conversation_agent.play_motion_sequence(move.sequence_file)
        self._record_robot(MOVE_MOTION_SEQUENCE, "Played motion sequence.", motion_sequence_file=move.sequence_file)

    def handle_move_animation(self, move):
        move = MoveAnimation.from_dict(move)
        self.conversation_agent.play_animation(move.animation_name)
        self._record_robot(MOVE_ANIMATION, "Played animation. ", animation_name=move.animation_name)

    def handle_move_ask_llm(self, move):
        move = MoveAskLLM.from_dict(move)
        self._run_llm_exchange(
            prompt=move.prompt,
            max_turns=move.max_turns or MAX_LLM_TURNS,
            set_variable=move.set_variable,
            quit_phrases=move.quit_phrases,
            quit_signal=move.quit_signal,
        )

    def _run_llm_exchange(self, prompt: str, max_turns: int, set_variable: Optional[str] = None,
                          quit_phrases: Optional[List[str]] = None, quit_signal: Optional[str] = None,
                          speak_first: bool = True, duration: Optional[float] = None,
                          rag_enabled: bool = False, rag_index_name: Optional[str] = None):
        dialog_history = []
        user_input = ""
        start_time = monotonic()

        def remaining_time():
            if duration is None:
                return None
            return max(0.0, duration - (monotonic() - start_time))

        agent = cast(Any, self.conversation_agent)
        if not speak_first:
            timeout = remaining_time()
            if timeout is not None and timeout <= 0:
                return
            reply, _ = agent.orchestrator.listen(timeout=timeout or 10)
            user_input = reply or ""
            self._record_user(MOVE_ANSWER_LLM, user_input)

        for _ in range(max_turns or MAX_LLM_TURNS):
            timeout = remaining_time()
            if timeout is not None and timeout <= 0:
                return
            llm_text = agent.ask_llm(
                user_prompt=user_input,
                context_messages=dialog_history,
                system_prompt=prompt,
                rag_enabled=rag_enabled,
                rag_index_name=rag_index_name,
            )
            if llm_text is None:
                continue

            # If the LLM embeds a quit signal, speak any remaining content and stop
            if quit_signal and quit_signal in llm_text:
                clean = llm_text.replace(quit_signal, "").strip()
                if clean:
                    agent.say(clean)
                    self._record_robot(MOVE_SAY, clean)
                return

            # Ask the user the LLM's text and listen for reply
            agent.say(llm_text)
            timeout = remaining_time()
            if timeout is not None and timeout <= 0:
                return
            user_input, _ = agent.orchestrator.listen(timeout=timeout or 10)
            if not user_input:
                user_input = ""

            # Record the exchange using the provided record types
            self._record_robot(MOVE_ASK_LLM, llm_text)
            self._record_user(MOVE_ANSWER_LLM, user_input)

            # Optionally store a variable from user's answer
            if set_variable and user_input:
                self.user_model[set_variable] = self.extract_open_value(user_input)

            # If the user said a configured quit phrase, stop early
            quit_happened = False
            for qp in (quit_phrases or []):
                if not qp:
                    continue
                if qp.lower() in user_input.lower():
                    quit_happened = True
                    break
            if quit_happened:
                return

            dialog_history.append(user_input)


class FunctionalType(Enum):
    GREETING = "greeting"
    FAREWELL = "farewell"


class FunctionalDialog(MiniDialog):
    def __init__(self, dialog_id, moves, type, dependencies=None, characters=None):
        # Functional dialogs are utility blocks such as greeting and farewell.
        super().__init__(dialog_id, moves, dependencies, characters=characters)
        self.type = type

    def is_greeting_dialog(self):
        return self.type == FunctionalType.GREETING

    def is_farewell_dialog(self):
        return self.type == FunctionalType.FAREWELL


class NarrativeDialog(MiniDialog):
    def __init__(self, dialog_id, moves, thread, position, dependencies=None, variable_dependencies=None, characters=None):
        # Narrative dialogs belong to a thread and have an explicit position (order).
        super().__init__(dialog_id, moves, dependencies, variable_dependencies, characters=characters)
        self.thread = thread
        self.position = position


class ChitchatDialog(MiniDialog):
    def __init__(self, dialog_id, moves, theme, topics=None, dependencies=None, variable_dependencies=None, characters=None):
        # Chitchat dialogs are short, theme-based interactions that can be biased by topics.
        super().__init__(dialog_id, moves, dependencies, variable_dependencies, characters=characters)
        self.theme = theme
        self.topics = topics or []


class LLMDialog(MiniDialog):
    def __init__(self, dialog_id, moves, prompt, max_turns=None, dependencies=None,
                 variable_dependencies=None, quit_phrases: Optional[List[str]] = None, quit_signal: Optional[str] = None,
                 speak_first: bool = True, duration: Optional[float] = None,
                 rag_enabled: bool = False, rag_index_name: Optional[str] = None, characters=None):
        super().__init__(dialog_id, moves, dependencies, variable_dependencies, characters=characters)
        self.prompt = prompt
        self.max_turns = max_turns or MAX_LLM_TURNS
        self.speak_first = speak_first
        self.duration = duration
        self.rag_enabled = rag_enabled
        self.rag_index_name = rag_index_name
        # Quit phrases (user utterances) and quit signal (LLM-inserted token)
        self.quit_phrases = [p for p in (quit_phrases or []) if p]
        self.quit_signal = quit_signal if quit_signal is not None else "<<QUIT>>"

    def run(self, agent, session_history, topics_of_interest, user_model):
        self.set_conversation_config(agent, session_history, topics_of_interest, user_model)

        self._run_llm_exchange(
            prompt=self.prompt,
            max_turns=self.max_turns,
            set_variable=None,
            quit_phrases=self.quit_phrases,
            quit_signal=self.quit_signal,
            speak_first=self.speak_first,
            duration=self.duration,
            rag_enabled=self.rag_enabled,
            rag_index_name=self.rag_index_name,
        )
