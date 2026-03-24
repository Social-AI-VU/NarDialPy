from typing import Optional, List
import re

from moves import MOVE_SAY, MOVE_ASK_YESNO, MOVE_ASK_OPEN, MOVE_ASK_OPTIONS, MOVE_PLAY_AUDIO, MOVE_MOTION_SEQUENCE, \
    MOVE_ANIMATION, \
    MoveAskYesNo, MoveAskOpen, MoveAskOptions, MovePlayAudio, MoveMotionSequence, MoveAnimation, \
    MOVE_ANSWER_OPEN, MOVE_ANSWER_YESNO, MOVE_ANSWER_OPTIONS, MoveAskLLM, MOVE_ASK_LLM, MOVE_ANSWER_LLM

from enum import Enum


class DialogType(Enum):
    NARRATIVE = "narrative"
    CHITCHAT = "chitchat"
    FUNCTIONAL = "functional"
    LLM_BASED = "llm_based"


MAX_LLM_TURNS = 5


class MiniDialog:
    def __init__(self, dialog_id, moves, dependencies=None, variable_dependencies=None):
        """
        dialog_id: str, unique identifier (e.g. 'pineapple_on_pizza')
        moves: list of dicts, each representing a dialog move
        attributes: dict, extra attributes depending on dialog type
        """
        self.dialog_id = dialog_id
        self.moves = moves
        self.dependencies = dependencies or []
        self.variable_dependencies = variable_dependencies or []

        self.conversation_agent = None
        self.session_history = []
        self.topics_of_interest = []
        self.user_model = {}

    def set_conversation_config(self, agent, session_history, topics_of_interest, user_model):
        self.conversation_agent = agent
        self.session_history = session_history if session_history is not None else []
        self.topics_of_interest = topics_of_interest if topics_of_interest is not None else []
        self.user_model = user_model if user_model is not None else {}

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

    def run(self, agent, session_history, topics_of_interest, user_model):
        # Execute mini dialogs, sending speech to the device and logging events.
        self.set_conversation_config(agent, session_history, topics_of_interest, user_model)

        idx = 0
        branch = None

        while idx < len(self.moves):
            move = self.moves[idx]
            move_type = self._get(move, 'type')
            move_branch = self._get(move, 'branch')
            if move_branch != branch:
                if branch is not None and move_branch is None:
                    branch = None
                else:
                    idx += 1
                    continue

            if move_type == MOVE_SAY:
                self.handle_move_say(move)
                idx += 1
            elif move_type == MOVE_ASK_YESNO:
                answer = self.handle_move_ask_yesno(move)
                branch = self.find_next_branch(branch, move, answer)
                idx = self.find_branch_start(branch, idx)
            elif move_type == MOVE_ASK_OPEN:
                answer = self.handle_move_ask_open(move)
                branch = self.find_next_branch(branch, move, answer)
                idx = self.find_branch_start(branch, idx)
            elif move_type == MOVE_ASK_OPTIONS:
                answer = self.handle_move_ask_options(move)
                branch = self.find_next_branch(branch, move, answer)
                idx = self.find_branch_start(branch, idx)
            elif move_type == MOVE_PLAY_AUDIO:
                self.handle_move_play_audio(move)
                idx += 1
            elif move_type == MOVE_MOTION_SEQUENCE:
                self.handle_move_motion_sequence(move)
                idx += 1
            elif move_type == MOVE_ANIMATION:
                self.handle_move_animation(move)
                idx += 1
            else:
                idx += 1

    def find_next_branch(self, branch, move, answer):
        next_map = self._get(move, 'next', {}) or {}
        if next_map:
            if answer:
                branch = next_map.get("success", None)
            else:
                branch = next_map.get("fail", None)
        return branch

    def find_branch_start(self, branch, idx):
        if branch is None:  # continue to next move
            return idx + 1

        # Find the jump target for a branch; if it doesn’t exist, end the dialog.
        for i, move in enumerate(self.moves):
            if self._get(move, 'branch') == branch:
                return i

        return len(self.moves)  # End if not found

    def handle_move_say(self, move):
        text = self._get(move, 'text')
        for var, value in self.user_model.items():
            text = text.replace(f"%{var}%", str(value))
        self.conversation_agent.say(text)
        self._record_robot(MOVE_SAY, text)

    def handle_move_ask_yesno(self, move):
        move = MoveAskYesNo.from_dict(move)
        answer = self.conversation_agent.ask_yes_no(move.text)
        self._record_robot(MOVE_ASK_YESNO, move.text)
        self._record_user(MOVE_ANSWER_YESNO, answer)
        print(f"User answered: {answer}")

        # store answer and interest if configured
        self._store_set_variable(move, answer)
        if answer == "yes" and getattr(move, 'add_interest', None):
            self.add_interest(self.topics_of_interest, move.add_interest)

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

        # Optional automatic personalized follow-up
        if not move.personalize_followup:
            return answer

        try:
            age_val = self.user_model.get('user_age', self.user_model.get('age', 9))
            follow = self.conversation_agent.personalize(robot_input=move.text, user_age=age_val, user_input=(answer or ""), language="en")
            if follow:
                self.conversation_agent.say(follow)
                self._record_robot("personalize_followup", follow, source_question=move.text)
        except Exception as e:
            self._record_system("error", "Error during personalize follow-up", stage="personalize_followup", error=str(e))

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
                          quit_phrases: Optional[List[str]] = None, quit_signal: Optional[str] = None):
        dialog_history = []
        user_input = ""
        for _ in range(max_turns or MAX_LLM_TURNS):
            llm_text = self.conversation_agent.ask_llm(user_prompt=user_input, context_messages=dialog_history, system_prompt=prompt)
            if llm_text is None:
                continue

            # If the LLM embeds a quit signal, speak any remaining content and stop
            if quit_signal and quit_signal in llm_text:
                clean = llm_text.replace(quit_signal, "").strip()
                if clean:
                    self.conversation_agent.say(clean)
                    self._record_robot(MOVE_SAY, clean)
                return

            # Ask the user the LLM's text and listen for reply
            user_input = self.conversation_agent.ask_open(llm_text)
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
    def __init__(self, dialog_id, moves, type, dependencies=None):
        # Functional dialogs are utility blocks such as greeting and farewell.
        super().__init__(dialog_id, moves, dependencies)
        self.type = type

    def is_greeting_dialog(self):
        return self.type == FunctionalType.GREETING

    def is_farewell_dialog(self):
        return self.type == FunctionalType.FAREWELL


class NarrativeDialog(MiniDialog):
    def __init__(self, dialog_id, moves, thread, position, dependencies=None, variable_dependencies=None):
        # Narrative dialogs belong to a thread and have an explicit position (order).
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.thread = thread
        self.position = position


class ChitchatDialog(MiniDialog):
    def __init__(self, dialog_id, moves, theme, topics=None, dependencies=None, variable_dependencies=None):
        # Chitchat dialogs are short, theme-based interactions that can be biased by topics.
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.theme = theme
        self.topics = topics or []


class LLMDialog(MiniDialog):
    def __init__(self, dialog_id, moves, prompt, max_turns=None, dependencies=None,
                 variable_dependencies=None, quit_phrases: Optional[List[str]] = None, quit_signal: Optional[str] = None):
        super().__init__(dialog_id, moves, dependencies, variable_dependencies)
        self.prompt = prompt
        self.max_turns = max_turns or MAX_LLM_TURNS
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
        )
