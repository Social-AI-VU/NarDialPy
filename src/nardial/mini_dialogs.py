from typing import Any, Optional, List, cast
import re
from time import monotonic
import asyncio
import random

from nardial.dialog_types import register_dialog_type
from nardial.eligibility import DependencyMetRule, ExcludeIfSeenRule, NarrativeOrderingRule, VariableDependencyMetRule
from nardial.events import EventBus
from nardial.moves import MOVE_SAY, MOVE_SAY_OPTIONS, MOVE_ASK_YESNO, MOVE_ASK_OPEN, MOVE_ASK_OPTIONS, MOVE_PLAY_AUDIO, MOVE_MOTION_SEQUENCE, \
    MOVE_ANIMATION, \
    MoveAskYesNo, MoveAskOpen, MoveAskOptions, MovePlayAudio, MoveMotionSequence, MoveAnimation, MoveBranch, \
    MOVE_ANSWER_OPEN, MOVE_ANSWER_YESNO, MOVE_ANSWER_OPTIONS, MoveAskLLM, MOVE_ASK_LLM, MOVE_ANSWER_LLM, \
    MOVE_LLM_FOLLOWUP, MOVE_BRANCH, MOVE_TIMED_WAIT, MOVE_WAIT_FOR_WEB_INPUT, MOVE_WAIT_FOR_BUTTON, MOVE_SHOW_IMAGE, MOVE_SHOW_VIDEO, MOVE_SHOW_IFRAME, MOVE_SHOW_HTML, MOVE_BLACK_SCREEN, MOVE_KEYBOARD_INPUT, \
    MoveTimedWait, MoveWaitForWebInput, MoveWaitForButton, MoveShowImage, MoveShowVideo, MoveShowIframe, MoveShowHtml, MoveSayOptions, MoveKeyboardInput, \
    MOVE_GO_TO_DIALOG, \
    MoveGoToDialog

from enum import Enum

from nardial.providers import Message


class DialogType(Enum):
    NARRATIVE = "narrative"
    CHITCHAT = "chitchat"
    FUNCTIONAL = "functional"
    LLM_BASED = "llm_based"


MAX_LLM_TURNS = 5


class MiniDialog:
    _function_registry = {}
     # JSON "type" string; set by `@register_dialog_type` (see `dialog_types.py`).
    TYPE_NAME: Optional[str] = None

    def __init__(self, dialog_id, moves, dependencies=None, variable_dependencies=None, characters=None, prerequisites=None):
        """
        dialog_id: str, unique identifier (e.g. 'pineapple_on_pizza')
        moves: list of dicts, each representing a dialog move
        attributes: dict, extra attributes depending on dialog type
        """
        self.dialog_id = dialog_id
        self.moves = moves
        self.dependencies = dependencies or []
        self.variable_dependencies = variable_dependencies or []
        self.characters = characters or {}
        self.prerequisites = prerequisites or None
        # self.function_registry = {}

        # Use a session-shared EventBus when wired; The SessionManager or caller
        # should call `set_event_bus()` to wire the shared bus before running.
        self._bus: EventBus | None = None
        self.conversation_agent = None
        self.session_history = []
        self.topics_of_interest = []
        self.user_model = {}
        self.current_outcome = None

    def set_event_bus(self, bus: EventBus) -> None:
        """Wire a shared EventBus into this MiniDialog.

        The dialog's move-level subscriptions use ``self._bus``; if no bus is
        wired the web-input wait move resolves immediately to the default outcome.
        """
        self._bus = bus

    # --- authoring hooks used by `DialogFactory` ---
    # Subclasses extend these (calling `super()`) to add their own JSON fields.

    @classmethod
    def validate_doc(cls, doc: dict) -> List[str]:
        """Return errors for this type's own fields; shared fields are validated by `DialogFactory`."""
        return []

    @classmethod
    def from_doc(cls, doc: dict, **common) -> "MiniDialog":
        """Build an instance from a validated doc. `common` holds the shared, already-normalized
        fields: `dialog_id`, `moves`, `dependencies`, `variable_dependencies`, `characters`."""
        return cls(**common)

    def to_doc(self) -> dict:
        """Return this type's own JSON fields (the inverse of `from_doc`)."""
        return {}

    def set_conversation_config(self, agent, session_history, topics_of_interest, user_model):
        self.conversation_agent = agent
        self.session_history = session_history if session_history is not None else []
        self.topics_of_interest = topics_of_interest if topics_of_interest is not None else []
        self.user_model = user_model if user_model is not None else {}

    @classmethod
    def register(cls, name):
        """Decorator to register a function into the central dictionary."""

        def decorator(func):
            cls._function_registry[name] = func
            return func

        return decorator

    def _execute_prerequisites(self):
        if not self.prerequisites:
            return

        for prerequisite in self.prerequisites:
            if prerequisite.get('execute'):
                try:
                    func_name = prerequisite.get('execute')
                    args = prerequisite.get('args')
                    func = MiniDialog._function_registry.get(func_name)
                    if args is None:
                        func()
                    elif isinstance(args, list):
                        func(*args)
                    else:
                        func(args)
                except Exception as e:
                    print(f"[ERROR] Could not execute {func_name}: {e}")
                    if prerequisite.get('skip_dialog'):
                        print(f"[INFO]: Skipped dialog {self.dialog_id}")
                        return False
            elif prerequisite.get('set_variable'):
                try:
                    self.user_model.update(prerequisite.get('set_variable'))
                except Exception as e:
                    print(f"[ERROR] Could not set variable {prerequisite.get('set_variable')}: {e}")
                    if prerequisite.get('skip_dialog'):
                        print(f"[INFO]: Skipped dialog {self.dialog_id}")
                        return False
        return True

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

    def _get_voice_settings(self, move):
        """
        Resolve voice settings for a move by looking up the "character" field and returning the corresponding settings
        from self.characters.
        Returns a dict or None.
        """
        character = self._get(move, "character")
        if character:
            # If a character is explicitly referenced but characters mapping doesn't contain it,
            # treat this as an error rather than silently falling back.
            if not isinstance(self.characters, dict) or character not in self.characters:
                raise ValueError(f"Unknown character: {character}")
            char_settings = self.characters.get(character)
            voice_settings = char_settings.get("voice_settings") if isinstance(char_settings, dict) else None
            if voice_settings:
                return voice_settings

        return None

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

    def _replace_variables(self, text):
        for var, value in self.user_model.items():
            text = text.replace(f"%{var}%", str(value))
        return text

    async def run(self, agent, session_history=None, topics_of_interest=None, user_model=None, registry=None):
        # Execute mini dialogs, sending speech to the device and logging events.
        self.set_conversation_config(agent, session_history, topics_of_interest, user_model)
        self.registry = registry

        if self.prerequisites:
            completed_prerequisites = self._execute_prerequisites()
            if not completed_prerequisites:
                return

        idx = 0

        while idx < len(self.moves):
            move = self.moves[idx]
            await self._dispatch_move(move)
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

    async def handle_move_branch(self, move) -> None:
        """Execute the sub-moves for the matching case of a ``branch`` move."""
        move = MoveBranch.from_dict(move)
        if move.on == "outcome":
            key = self.current_outcome
        elif move.on == "variables":
            variable_1 = self.user_model.get(move.variables[0])
            variable_2 = self.user_model.get(move.variables[1])
            if variable_1 == variable_2:
                key = "true"
            else:
                key = "false"
        else:
            key = self.user_model.get(move.on)
        case_moves = move.cases.get(key, [])
        for sub_move in case_moves:
            await self._dispatch_move(sub_move)

    async def _dispatch_move(self, move) -> None:
        """Execute a single move dict."""
        move_type = self._get(move, 'type')
        if move_type == MOVE_SAY:
            await self.handle_move_say(move)
        elif move_type == MOVE_SAY_OPTIONS:
            await self.handle_move_say_options(move)
        elif move_type == MOVE_ASK_YESNO:
            answer = await self.handle_move_ask_yesno(move)
            self._resolve_outcome(move, answer)
        elif move_type == MOVE_ASK_OPEN:
            answer = await self.handle_move_ask_open(move)
            self._resolve_outcome(move, answer)
        elif move_type == MOVE_ASK_OPTIONS:
            answer = await self.handle_move_ask_options(move)
            self._resolve_outcome(move, answer)
        elif move_type == MOVE_BRANCH:
            await self.handle_move_branch(move)
        elif move_type == MOVE_PLAY_AUDIO:
            await self.handle_move_play_audio(move)
        elif move_type == MOVE_MOTION_SEQUENCE:
            await self.handle_move_motion_sequence(move)
        elif move_type == MOVE_ANIMATION:
            await self.handle_move_animation(move)
        elif move_type == MOVE_ASK_LLM:
            await self.handle_move_ask_llm(move)
        elif move_type == MOVE_TIMED_WAIT:
            await self.handle_move_timed_wait(move)
        elif move_type == MOVE_WAIT_FOR_WEB_INPUT:
            answer = await self.handle_move_wait_for_web_input(move)
            self._resolve_outcome(move, answer)
        elif move_type == MOVE_WAIT_FOR_BUTTON:
            answer = await self.handle_move_wait_for_button(move)
            self._resolve_outcome(move, answer)
        elif move_type == MOVE_SHOW_IMAGE:
            await self.handle_move_show_image(move)
        elif move_type == MOVE_SHOW_VIDEO:
            await self.handle_move_show_video(move)
        elif move_type == MOVE_SHOW_IFRAME:
            await self.handle_move_show_iframe(move)
        elif move_type == MOVE_SHOW_HTML:
            await self.handle_move_show_html(move)

        elif move_type == MOVE_BLACK_SCREEN:
            await self.handle_move_black_screen(move)
        elif move_type == MOVE_KEYBOARD_INPUT:
            await self.handle_move_keyboard_input(move)
        elif move_type == MOVE_GO_TO_DIALOG:
            await self.handle_move_go_to_dialog(move)

    async def _generate_llm_followup(self, user_answer: str, system_prompt: str, voice_settings=None):
        """Call the LLM to generate a contextual followup to the user's answer and speak it."""
        context_messages = [
            entry.get("text", "") for entry in self.session_history if entry.get("text") is not None
        ]
        llm_text = await self.conversation_agent.ask_llm(
            user_prompt=user_answer,
            context_messages=context_messages,
            system_prompt=system_prompt,
        )
        if llm_text:
            # Respect per-move voice settings when speaking the generated followup
            await self.conversation_agent.say(llm_text, voice_settings=voice_settings)
            self._record_robot(MOVE_LLM_FOLLOWUP, llm_text)

    async def handle_move_say(self, move):
        text = self._replace_variables(self._get(move, 'text'))
        voice_settings = self._get_voice_settings(move)
        await self.conversation_agent.say(text, voice_settings=voice_settings)
        self._record_robot(MOVE_SAY, text)

    async def handle_move_say_options(self, move):
        move = MoveSayOptions.from_dict(move)
        options = move.options
        if not isinstance(options, list) or not options:
            raise ValueError("say_options moves require a non-empty options list")
        choice = random.choice(options)
        if not isinstance(choice, str):
            raise ValueError("say_options options must be strings")
        choice = self._replace_variables(choice)
        voice_settings = self._get_voice_settings(move)
        await self.conversation_agent.say(choice, voice_settings=voice_settings)
        self._record_robot(MOVE_SAY_OPTIONS, choice, options=options)

    async def handle_move_ask_yesno(self, move):
        move = MoveAskYesNo.from_dict(move)
        voice_settings = self._get_voice_settings(move)
        # Pass voice settings into the ask call so the device speaks with the correct character voice
        text = self._replace_variables(self._get(move, 'text'))
        answer = await self.conversation_agent.ask_yesno(text, voice_settings=voice_settings)
        self._record_robot(MOVE_ASK_YESNO, text)
        self._record_user(MOVE_ANSWER_YESNO, answer)
        print(f"User answered: {answer}")

        # store answer and interest if configured
        self._store_set_variable(move, answer)
        if answer == "yes" and getattr(move, 'add_interest', None):
            self.add_interest(self.topics_of_interest, move.add_interest)

        # Optional LLM-generated followup response, speak with same voice as the move if provided
        if move.llm_followup:
            await self._generate_llm_followup(user_answer=answer or "", system_prompt=move.llm_followup,
                                              voice_settings=voice_settings)

        return answer

    async def handle_move_ask_open(self, move):
        move = MoveAskOpen.from_dict(move)
        voice_settings = self._get_voice_settings(move)
        text = self._replace_variables(self._get(move, 'text'))
        answer = await self.conversation_agent.ask_open(text, voice_settings=voice_settings)
        self._record_robot(MOVE_ASK_OPEN, text)
        self._record_user(MOVE_ANSWER_OPEN, answer)
        print(f"User answered: {answer}")

        # store answer and interests if configured
        self._store_set_variable(move, answer)
        self._store_interests(move, answer)

        # Optional LLM-generated followup response
        if move.llm_followup:
            await self._generate_llm_followup(user_answer=answer or "", system_prompt=move.llm_followup,
                                              voice_settings=voice_settings)

        return answer

    async def handle_move_ask_options(self, move):
        move = MoveAskOptions.from_dict(move)
        voice_settings = self._get_voice_settings(move)
        text = self._replace_variables(self._get(move, 'text'))
        options = self._get(move, 'options')
        for i in range(len(options)):
            options[i] = self._replace_variables(options[i])
        answer = await self.conversation_agent.ask_options(text, move.options, voice_settings=voice_settings)
        self._record_robot(MOVE_ASK_OPTIONS, text, options=move.options)
        self._record_user(MOVE_ANSWER_OPTIONS, answer)
        print(f"User answered: {answer}")

        # store answer if configured
        self._store_set_variable(move, answer)
        self._store_interests(move, answer)

        # Optional LLM-generated followup response
        if move.llm_followup:
            await self._generate_llm_followup(user_answer=answer or "", system_prompt=move.llm_followup,
                                              voice_settings=voice_settings)

        return answer

    async def handle_move_play_audio(self, move):
        move = MovePlayAudio.from_dict(move)
        self.conversation_agent.play_audio(move.audio_file)
        self._record_robot(MOVE_PLAY_AUDIO, "Played audio. ", audio_file=move.audio_file)

    async def handle_move_motion_sequence(self, move):
        move = MoveMotionSequence.from_dict(move)
        self.conversation_agent.play_motion_sequence(move.sequence_file)
        self._record_robot(MOVE_MOTION_SEQUENCE, "Played motion sequence.", motion_sequence_file=move.sequence_file)

    async def handle_move_animation(self, move):
        move = MoveAnimation.from_dict(move)
        self.conversation_agent.play_animation(move.animation_name)
        self._record_robot(MOVE_ANIMATION, "Played animation. ", animation_name=move.animation_name)

    async def handle_move_ask_llm(self, move):
        move = MoveAskLLM.from_dict(move)
        voice_settings = self._get_voice_settings(move)
        await self._run_llm_exchange(
            prompt=move.prompt,
            max_turns=move.max_turns or MAX_LLM_TURNS,
            set_variable=move.set_variable,
            quit_phrases=move.quit_phrases,
            quit_signal=move.quit_signal,
            speak_first=move.speak_first if hasattr(move, "speak_first") else True,
            duration=move.duration if hasattr(move, "duration") else None,
            rag_enabled=move.rag_enabled if hasattr(move, "rag_enabled") else False,
            index_name=move.index_name if hasattr(move, "index_name") else None,
            voice_settings=voice_settings,
        )

    async def _run_llm_exchange(self, prompt: str, max_turns: int, set_variable: Optional[str] = None,
                          quit_phrases: Optional[List[str]] = None, quit_signal: Optional[str] = None,
                          speak_first: bool = True, duration: Optional[float] = None,
                          rag_enabled: bool = False, index_name: Optional[str] = None, voice_settings=None):
        dialog_history = []
        user_input = ""
        start_time = monotonic()
        prompt = self._replace_variables(prompt)
        for i in range(len(quit_phrases)):
            quit_phrases[i] = self._replace_variables(quit_phrases[i])

        def remaining_time():
            if duration is None:
                return None
            return max(0.0, duration - (monotonic() - start_time))

        agent = cast(Any, self.conversation_agent)
        if not speak_first:
            timeout = remaining_time()
            if timeout is not None and timeout <= 0:
                return
            result = await agent.orchestrator.listen(timeout=timeout or 10)
            user_input = result.transcript or ""
            self._record_user(MOVE_ANSWER_LLM, user_input)

        for _ in range(max_turns or MAX_LLM_TURNS):
            timeout = remaining_time()
            if timeout is not None and timeout <= 0:
                return
            llm_text = await agent.ask_llm(
                user_prompt=user_input,
                context_messages=dialog_history,
                system_prompt=prompt,
                rag_enabled=rag_enabled,
                index_name=index_name,
            )
            if llm_text is None:
                continue

            # If the LLM embeds a quit signal, speak any remaining content and stop
            if quit_signal and quit_signal in llm_text:
                clean = llm_text.replace(quit_signal, "").strip()
                if clean:
                    # speak with the move's voice settings if provided
                    await agent.say(clean, voice_settings=voice_settings)
                    self._record_robot(MOVE_SAY, clean)
                return

            # Ask the user the LLM's text and listen for reply
            await agent.say(llm_text, voice_settings=voice_settings)
            timeout = remaining_time()
            if timeout is not None and timeout <= 0:
                return
            result = await agent.orchestrator.listen(timeout=timeout or 10)
            user_input = result.transcript or ""

            # Record the exchange using the provided record types
            self._record_robot(MOVE_ASK_LLM, llm_text)
            dialog_history.append(Message(role="assistant", content=llm_text))
            self._record_user(MOVE_ANSWER_LLM, user_input)
            dialog_history.append(Message(role="user", content=user_input))

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

    async def handle_move_timed_wait(self, move):
        move = MoveTimedWait.from_dict(move)
        await asyncio.sleep(move.duration_seconds)
        self._record_system(
            MOVE_TIMED_WAIT,
            f"Waited {move.duration_seconds} seconds",
            duration_seconds=move.duration_seconds,
        )

    async def handle_move_wait_for_web_input(self, move):
        """Wait for a web-input event whose value is in ``move.options``, or until timeout.

        If a screen provider is configured and ``move.options`` is non-empty, buttons
        are shown before waiting and hidden after resolution (match or timeout).
        If no event bus is wired up, resolves immediately to ``move.default_outcome``.
        """
        move = MoveWaitForWebInput.from_dict(move)
        sp = self.conversation_agent.orchestrator.screen_provider

        # Show buttons on screen before waiting (only when options are declared).
        if sp is not None and move.options:
            options = self._get(move, 'options')
            for i in range(len(options)):
                options[i] = self._replace_variables(options[i])
            await sp.show_buttons(options)

        if self._bus is None:
            self._record_system(
                MOVE_WAIT_FOR_WEB_INPUT,
                "No event bus available, resolving to default outcome.",
                default_outcome=move.default_outcome,
            )
            if sp is not None:
                await sp.hide_input()
            return None

        value = None

        def _predicate(ev: Any) -> bool:
            return (
                    ev.type == "web_input"
                    and isinstance(ev.data, dict)
                    and ev.data.get("value") in options
            )

        sub = self._bus.subscribe(_predicate)
        try:
            ev = await asyncio.wait_for(sub.get(), timeout=move.timeout)
            value = ev.data.get("value")
            self._record_system(
                MOVE_WAIT_FOR_WEB_INPUT,
                f"Received web input: {value}",
                value=value,
            )
            self._store_set_variable(move, value)
        except asyncio.TimeoutError:
            self._record_system(
                MOVE_WAIT_FOR_WEB_INPUT,
                f"Timed out after {move.timeout} seconds waiting for web input. Resolving to default outcome.",
                timeout=move.timeout,
                default_outcome=move.default_outcome,
            )
        finally:
            self._bus.unsubscribe(sub)
            # Hide input after resolution regardless of outcome (match or timeout).
            if sp is not None:
                await sp.hide_input()

        return value

    async def handle_move_wait_for_button(self, move):
        """Show buttons and wait for the user to click one, or until timeout.

        Resolves to the clicked button label (used as outcome key), or
        ``move.default_outcome`` on timeout or when no event bus is wired up.
        """
        move = MoveWaitForButton.from_dict(move)
        sp = self.conversation_agent.orchestrator.screen_provider

        if sp is not None and move.options:
            await sp.show_buttons(move.options)

        if self._bus is None:
            self._record_system(
                MOVE_WAIT_FOR_BUTTON,
                "No event bus available, resolving to default outcome.",
                default_outcome=move.default_outcome,
            )
            if sp is not None:
                await sp.hide_input()
            return None

        value = None

        def _predicate(ev: Any) -> bool:
            return (
                ev.type == "web_input"
                and isinstance(ev.data, dict)
                and ev.data.get("value") in move.options
            )

        sub = self._bus.subscribe(_predicate)
        try:
            ev = await asyncio.wait_for(sub.get(), timeout=move.timeout)
            value = ev.data.get("value")
            self._record_system(
                MOVE_WAIT_FOR_BUTTON,
                f"Button clicked: {value}",
                value=value,
            )
        except asyncio.TimeoutError:
            self._record_system(
                MOVE_WAIT_FOR_BUTTON,
                f"Timed out after {move.timeout}s waiting for button click. Resolving to default outcome.",
                timeout=move.timeout,
                default_outcome=move.default_outcome,
            )
        finally:
            self._bus.unsubscribe(sub)
            if sp is not None:
                await sp.hide_input()

        return value

    async def handle_move_show_image(self, move):
        """Display an image on the screen.

        Skipped with a warning if no screen provider is configured on the agent.
        """
        move = MoveShowImage.from_dict(move)
        sp = self.conversation_agent.orchestrator.screen_provider
        if sp is None:
            self._record_system(
                MOVE_SHOW_IMAGE,
                "No screen provider configured, cannot show image.",
                src=move.src,
            )
            return

        await sp.show_image(move.src)
        self._record_system(
            MOVE_SHOW_IMAGE,
            "Showed image on screen.",
            src=move.src,
        )

    async def handle_move_show_video(self, move):
        """Display a video on the screen.

                Skipped with a warning if no screen provider is configured.
                """
        move = MoveShowVideo.from_dict(move)
        sp = self.conversation_agent.orchestrator.screen_provider
        if sp is None:
            self._record_system(
                MOVE_SHOW_VIDEO,
                "No screen provider configured, cannot show video.",
                src=move.src,
            )
            return
        await sp.show_video(move.src)
        self._record_system(
            MOVE_SHOW_VIDEO,
            "Showed video on screen.",
            src=move.src,
        )

    async def handle_move_show_iframe(self, move):
        """Embed an external URL in an iframe on the screen.

        Skipped with a warning if no screen provider is configured.
        """
        move = MoveShowIframe.from_dict(move)
        sp = self.conversation_agent.orchestrator.screen_provider
        if sp is None:
            self._record_system(
                MOVE_SHOW_IFRAME,
                "No screen provider configured, cannot show iframe.",
                url=move.url,
            )
            return
        await sp.show_iframe(move.url)
        self._record_system(
            MOVE_SHOW_IFRAME,
            "Showed iframe on screen.",
            url=move.url,
        )

    async def handle_move_show_html(self, move):
        """Render a raw HTML snippet on the screen.

        Skipped with a warning if no screen provider is configured.
        """
        move = MoveShowHtml.from_dict(move)
        sp = self.conversation_agent.orchestrator.screen_provider
        if sp is None:
            self._record_system(
                MOVE_SHOW_HTML,
                "No screen provider configured, cannot show HTML.",
                html_length=len(move.html) if move.html else 0,
            )
            return
        html = self._replace_variables(self._get(move, 'html'))
        await sp.show_html(html)
        self._record_system(
            MOVE_SHOW_HTML,
            "Showed HTML on screen.",
            html_length=len(move.html) if move.html else 0,
        )

    async def handle_move_black_screen(self, move):
        """Set the screen to black/blank.

        Skipped with a warning if no screen provider is configured.
        """
        sp = self.conversation_agent.orchestrator.screen_provider
        if sp is None:
            self._record_system(
                MOVE_BLACK_SCREEN,
                "No screen provider configured, cannot set black screen.",
            )
            return
        await sp.black()
        self._record_system(
            MOVE_BLACK_SCREEN,
            "Set black screen.",
        )

    async def handle_move_keyboard_input(self, move):
        """Wait for a web-input event containing text, or until timeout.

        If a screen provider is configured, a text input field is shown.
        If no event bus is wired up, resolves immediately to ``move.default_outcome``.
        """

        move = MoveKeyboardInput.from_dict(move)
        sp = self.conversation_agent.orchestrator.screen_provider

        # Show buttons on screen before waiting
        if sp is not None:
            await sp.show_text_input(move.prompt)

        if self._bus is None:
            self._record_system(
                MOVE_KEYBOARD_INPUT,
                "No event bus available, resolving to default outcome.",
                default_outcome=move.default_outcome,
            )
            if sp is not None:
                await sp.hide_input()
            return move.default_outcome

        value = None

        def _predicate(ev: Any) -> bool:
            return (
                    ev.type == "web_input"
                    and isinstance(ev.data, dict)
                    and "value" in ev.data
                    and isinstance(ev.data.get("value"), str)
            )

        sub = self._bus.subscribe(_predicate)
        try:
            ev = await asyncio.wait_for(sub.get(), timeout=move.timeout)
            value = ev.data.get("value")

            self._record_system(
                MOVE_KEYBOARD_INPUT,
                f"Received text input: {value}",
                value=value,
            )
            self._store_set_variable(move, value)

        except asyncio.TimeoutError:
            self._record_system(
                MOVE_KEYBOARD_INPUT,
                f"Timed out after {move.timeout} seconds waiting for text input.",
                timeout=move.timeout,
                default_outcome=move.default_outcome,
            )
            value = move.default_outcome
        finally:
            self._bus.unsubscribe(sub)
            if sp is not None:
                await sp.hide_input()

        return value

    async def handle_move_go_to_dialog(self, move):
        dialog_id = move.get("dialog_id")
        dialog = self.registry.get_by_id(dialog_id)

        dialog.set_event_bus(self._bus)
        await dialog.run(
            agent=self.conversation_agent,
            session_history=self.session_history,
            topics_of_interest=self.topics_of_interest,
            user_model=self.user_model,
            registry=self.registry,
        )


@register_dialog_type(DialogType.FUNCTIONAL.value)
class FunctionalDialog(MiniDialog):
    DIALOG_TYPE = DialogType.FUNCTIONAL
    INDEX_ATTRS = ["functional_type"]
    # Deliberately no ExcludeIfSeenRule: greetings/farewells should re-run every session.
    DEFAULT_ELIGIBILITY: list = [DependencyMetRule()]

    def __init__(self, dialog_id, moves, type, dependencies=None, variable_dependencies=None, characters=None, prerequisites=None):
        # Functional dialogs are utility blocks such as greeting and farewell.
        super().__init__(dialog_id, moves, dependencies, variable_dependencies, characters=characters, prerequisites=prerequisites)
        self.type = type

    @classmethod
    def validate_doc(cls, doc: dict) -> List[str]:
        errs = super().validate_doc(doc)
        if not isinstance(doc.get("functional_type"), str):
            errs.append("functional_type must be string for functional dialogs")
        return errs

    @classmethod
    def from_doc(cls, doc: dict, **common) -> "MiniDialog":
        return cls(type=doc["functional_type"], **common)

    def to_doc(self) -> dict:
        return {**super().to_doc(), "functional_type": getattr(self, "type", "")}

    @property
    def functional_type(self):
        return self.type

    def is_greeting_dialog(self):
        return self.type == FunctionalType.GREETING.value

    def is_farewell_dialog(self):
        return self.type == FunctionalType.FAREWELL.value


@register_dialog_type(DialogType.NARRATIVE.value)
class NarrativeDialog(MiniDialog):
    DIALOG_TYPE = DialogType.NARRATIVE
    INDEX_ATTRS = ["thread"]
    DEFAULT_ELIGIBILITY: list = [
        ExcludeIfSeenRule(),
        DependencyMetRule(),
        VariableDependencyMetRule(),
        NarrativeOrderingRule(),
    ]

    def __init__(self, dialog_id, moves, thread, position, dependencies=None, variable_dependencies=None, characters=None, prerequisites=None):
        # Narrative dialogs belong to a thread and have an explicit position (order).
        super().__init__(dialog_id, moves, dependencies, variable_dependencies, characters=characters, prerequisites=prerequisites)
        self.thread = thread
        self.position = position

    @classmethod
    def validate_doc(cls, doc: dict) -> List[str]:
        errs = super().validate_doc(doc)
        if not isinstance(doc.get("thread"), str):
            errs.append("thread must be string for narrative dialogs")
        try:
            int(doc.get("position"))
        except Exception:
            errs.append("position must be integer for narrative dialogs")
        return errs

    @classmethod
    def from_doc(cls, doc: dict, **common) -> "MiniDialog":
        return cls(thread=doc["thread"], position=int(doc["position"]), **common)

    def to_doc(self) -> dict:
        return {
            **super().to_doc(),
            "thread": getattr(self, "thread", ""),
            "position": int(getattr(self, "position", 0)),
        }


@register_dialog_type(DialogType.CHITCHAT.value)
class ChitchatDialog(MiniDialog):
    DIALOG_TYPE = DialogType.CHITCHAT
    INDEX_ATTRS = ["topics"]
    DEFAULT_ELIGIBILITY: list = [ExcludeIfSeenRule(), DependencyMetRule(), VariableDependencyMetRule()]

    def __init__(self, dialog_id, moves, topics=None, dependencies=None, variable_dependencies=None, characters=None, prerequisites=None):
        # Chitchat dialogs are short, topic-based interactions.
        super().__init__(dialog_id, moves, dependencies, variable_dependencies, characters=characters, prerequisites=prerequisites)
        self.topics = topics or []

    @classmethod
    def validate_doc(cls, doc: dict) -> List[str]:
        errs = super().validate_doc(doc)
        topics = doc.get("topics")
        if topics is not None and (not isinstance(topics, list) or not all(isinstance(x, str) for x in topics)):
            errs.append("topics must be a list of strings for chitchat dialogs")
        return errs

    @classmethod
    def from_doc(cls, doc: dict, **common) -> "MiniDialog":
        return cls(topics=list(doc.get("topics") or []), **common)

    def to_doc(self) -> dict:
        return {**super().to_doc(), "topics": list(getattr(self, "topics", []) or [])}


@register_dialog_type(DialogType.LLM_BASED.value)
class LLMDialog(MiniDialog):
    DIALOG_TYPE = DialogType.LLM_BASED
    INDEX_ATTRS: list = []
    DEFAULT_ELIGIBILITY: list = [ExcludeIfSeenRule(), DependencyMetRule(), VariableDependencyMetRule()]

    def __init__(self, dialog_id, moves, prompt, max_turns=None, dependencies=None,
                 variable_dependencies=None, quit_phrases: Optional[List[str]] = None, quit_signal: Optional[str] = None,
                 speak_first: bool = True, duration: Optional[float] = None,
                 rag_enabled: bool = False, index_name: Optional[str] = None, characters=None, prerequisites=None):
        super().__init__(dialog_id, moves, dependencies, variable_dependencies, characters=characters, prerequisites=prerequisites)
        self.prompt = prompt
        self.max_turns = max_turns or MAX_LLM_TURNS
        self.speak_first = speak_first
        self.duration = duration
        self.rag_enabled = rag_enabled
        self.index_name = index_name
        # Quit phrases (user utterances) and quit signal (LLM-inserted token)
        self.quit_phrases = [p for p in (quit_phrases or []) if p]
        self.quit_signal = quit_signal if quit_signal is not None else "<<QUIT>>"

    @classmethod
    def validate_doc(cls, doc: dict) -> List[str]:
        errs = super().validate_doc(doc)
        if not isinstance(doc.get("prompt"), str):
            errs.append("prompt must be string for llm_based dialogs")
        if "max_turns" in doc and not isinstance(doc.get("max_turns"), int):
            errs.append("max_turns must be integer for llm_based dialogs")
        if "speak_first" in doc and not isinstance(doc.get("speak_first"), bool):
            errs.append("speak_first must be boolean for llm_based dialogs")
        if "duration" in doc and not isinstance(doc.get("duration"), (int, float)):
            errs.append("duration must be numeric seconds for llm_based dialogs")
        if "rag_enabled" in doc and not isinstance(doc.get("rag_enabled"), bool):
            errs.append("rag_enabled must be boolean for llm_based dialogs")
        quit_phrases = doc.get("quit_phrases")
        if quit_phrases is not None and (
                not isinstance(quit_phrases, list) or not all(isinstance(x, str) for x in quit_phrases)):
            errs.append("quit_phrases must be a list of strings for llm_based dialogs")
        if "quit_signal" in doc and not isinstance(doc.get("quit_signal"), str):
            errs.append("quit_signal must be string for llm_based dialogs")
        return errs

    @classmethod
    def from_doc(cls, doc: dict, **common) -> "MiniDialog":
        return cls(
            prompt=doc["prompt"],
            max_turns=doc.get("max_turns"),
            quit_phrases=doc.get("quit_phrases"),
            quit_signal=doc.get("quit_signal"),
            speak_first=doc.get("speak_first", True),
            duration=doc.get("duration"),
            rag_enabled=doc.get("rag_enabled", False),
            index_name=doc.get("index_name"),
            **common,
        )

    def to_doc(self) -> dict:
        return {
            **super().to_doc(),
            "prompt": getattr(self, "prompt", ""),
            "max_turns": getattr(self, "max_turns", None),
            "quit_phrases": list(getattr(self, "quit_phrases", []) or []),
            "quit_signal": getattr(self, "quit_signal", None),
            "speak_first": getattr(self, "speak_first", True),
            "duration": getattr(self, "duration", None),
            "rag_enabled": getattr(self, "rag_enabled", False),
            "index_name": getattr(self, "index_name", None),
        }

    async def run(self, agent, session_history=None, topics_of_interest=None, user_model=None, registry=None):
        self.set_conversation_config(agent, session_history, topics_of_interest, user_model)
        if self.prerequisites:
            self._execute_prerequisites()

        await self._run_llm_exchange(
            prompt=self.prompt,
            max_turns=self.max_turns,
            set_variable=None,
            quit_phrases=self.quit_phrases,
            quit_signal=self.quit_signal,
            speak_first=self.speak_first,
            duration=self.duration,
            rag_enabled=self.rag_enabled,
            index_name=self.index_name,
        )


# small helper enum used by FunctionalDialog
class FunctionalType(Enum):
    GREETING = "greeting"
    FAREWELL = "farewell"
