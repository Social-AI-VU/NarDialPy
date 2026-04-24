"""High-level conversational agent that wraps the interaction orchestrator.

This module provides :class:`ConversationAgent`, the main entry point for
dialog authors who want to drive a robot through spoken interaction without
dealing with low-level device management.
"""

import json
import re

from sic_framework.devices import Nao, Pepper
from sic_framework.devices.device import SICDeviceManager
from nardial.interaction_orchestrator import InteractionOrchestrator, InteractionConfig


class ConversationAgent:
    """High-level interface for controlling a social robot during a conversation.

    :class:`ConversationAgent` wraps an :class:`~nardial.interaction_orchestrator.InteractionOrchestrator`
    and exposes simple, dialog-oriented methods (say, listen, ask) so that
    :class:`~nardial.mini_dialogs.MiniDialog` subclasses do not need to interact
    with hardware or TTS services directly.

    Args:
        device_manager: A SIC device manager for the target robot (e.g. Desktop,
            Pepper, Nao, or Alphamini).
        int_config: Optional interaction configuration.  A default
            :class:`~nardial.interaction_orchestrator.InteractionConfig` is used when
            *None* is supplied.
    """

    def __init__(self, device_manager: SICDeviceManager, int_config: InteractionConfig = None):
        if int_config is None:
            int_config = InteractionConfig()
        self.orchestrator = InteractionOrchestrator(device_manager=device_manager, int_config=int_config)
        self.device = device_manager

    def say(self, text):
        """Synthesise and play *text* through the robot's speakers.

        Args:
            text: The utterance to speak aloud.
        """
        self.orchestrator.say(text)

    def play_audio(self, audio_file):
        """Play a pre-recorded WAV audio file through the robot's speakers.

        Args:
            audio_file: Absolute or relative path to the ``.wav`` file.
        """
        self.orchestrator.play_audio(audio_file)

    def play_motion_sequence(self, motion_sequence_file):
        """Replay a recorded motion sequence on the robot.

        Args:
            motion_sequence_file: Path to the motion-sequence recording file.
        """
        self.orchestrator.play_motion(motion_sequence_file)

    def play_animation(self, animation_name, block=False):
        """Play a named NaoQi animation on Pepper or Nao robots.

        The call is silently ignored on devices that do not support NaoQi
        animations (e.g. Desktop or Alphamini).

        Args:
            animation_name: NaoQi animation identifier string.
            block: If ``True``, wait for the animation to finish before
                returning.
        """
        if isinstance(self.device, Pepper) or isinstance(self.device, Nao):
            try:
                self.orchestrator.animate_naoqi(animation_name, block)
            except Exception as e:
                print(f"Failed to play animation: {animation_name}", e)

    def ask_yesno(self, question, max_attempts=1):
        """Ask a yes/no question and return the recognised intent.

        The agent speaks *question*, then listens for a yes/no/don't-know
        response via Dialogflow intent recognition.

        Args:
            question: The question to speak.
            max_attempts: Maximum number of listen attempts before giving up.

        Returns:
            ``"yes"``, ``"no"``, ``"dontknow"`` on a successful match, or
            ``None`` when no recognised intent is detected within
            *max_attempts*.
        """
        attempts = 0
        while attempts < max_attempts:
            self.say(question)
            reply, intent = self.orchestrator.listen(context={'answer_yesno': 1})

            if intent:
                print(f'context: answer_yesno, recognized_intent: {str(intent)}')
                if intent == "yesno_yes":
                    return "yes"
                elif intent == "yesno_no":
                    return "no"
                elif intent == "yesno_dontknow":
                    return "dontknow"

            attempts += 1
        return None

    def ask_open(self, question, max_attempts=2):
        """Ask an open-ended question and return the transcribed user reply.

        Args:
            question: The question to speak.
            max_attempts: Maximum number of listen attempts before giving up.

        Returns:
            The transcribed reply string, or ``None`` when no speech is
            detected within *max_attempts*.
        """
        attempts = 0
        while attempts < max_attempts:
            self.say(question)
            reply, _ = self.orchestrator.listen()
            if reply:
                return reply
            attempts += 1
        return None

    def ask_options(self, question, options, max_attempts=2):
        """Ask a question and match the reply against a list of valid options.

        The user's free-text response is compared (case-insensitively) against
        each item in *options*.  The first matching option is returned.

        Args:
            question: The question to speak.
            options: List of expected option strings to match against the reply.
            max_attempts: Maximum number of listen attempts before giving up.

        Returns:
            The matched option string, or ``None`` when no option is found in
            the reply.
        """
        answer = self.ask_open(question, max_attempts=max_attempts)
        if answer:
            answer_lower = answer.lower()
            for opt in options:
                if opt in answer_lower:
                    return opt
        return None

    def extract_topics_with_gpt(self, raw_topics):
        """Condense raw topics (often full sentences) into 1-2 single-word, lowercase keywords.

        Returns a de-duplicated list preserving order. Falls back to a simple local heuristic
        if the GPT response can't be parsed.
        """

        def _heuristic(lines):
            if not lines:
                return []
            stop = {
                "the", "a", "an", "and", "or", "but", "if", "then", "than", "that", "this", "these", "those",
                "i", "you", "he", "she", "it", "we", "they", "me", "my", "mine", "your", "yours", "his", "her", "its", "our", "ours", "their", "theirs",
                "to", "in", "on", "at", "from", "for", "with", "about", "as", "of", "is", "are", "was", "were", "be", "been", "am", "do", "does", "did",
                "yes", "no", "maybe", "okay", "ok", "yeah", "yep", "nope", "uh", "um", "favorite", "favourite", "because", "thing", "things", "think"
            }
            out, seen = [], set()
            for t in lines:
                words = re.findall(r"[A-Za-z]+", str(t).lower())
                picked = [w for w in words if len(w) > 2 and w not in stop]
                if not picked and words:
                    picked = [words[0]]
                # take up to 2 keywords per input line
                for w in picked[:2]:
                    if w not in seen:
                        out.append(w);
                        seen.add(w)
            return out

        raw_topics = [str(x) for x in (raw_topics or []) if str(x).strip()]
        if not raw_topics:
            return []
        try:
            prompt = (
                "You will receive a JSON array of phrases. For each item, extract 1-2 concise English keywords "
                "(single words, lowercase). Avoid function words; these are the topics of interest of the user; prefer specific nouns (e.g., 'oak', 'garden', 'dogs', 'elephants'). "
                "Return ONLY a JSON array of unique keywords (strings), no explanations.\n"
                f"INPUT: {json.dumps(raw_topics, ensure_ascii=False)}\nOUTPUT:"
            )
            data = self.orchestrator.request_from_gpt(system_prompt=prompt)
            if not isinstance(data, list):
                raise ValueError("GPT did not return a JSON list")
            out, seen = [], set()
            for item in data:
                if not isinstance(item, str):
                    continue
                w = re.sub(r"[^A-Za-z]+", "", item.lower())
                if len(w) > 2 and w not in seen:
                    out.append(w);
                    seen.add(w)
            return out or _heuristic(raw_topics)
        except Exception:
            return _heuristic(raw_topics)

    def ask_llm(self, user_prompt, context_messages, system_prompt):
        """Forward a prompt to the configured LLM and return the response text.

        Args:
            user_prompt: The user-turn text to send to the LLM.
            context_messages: List of previous conversation turns used as
                context for the request.
            system_prompt: System-level instruction string for the LLM.

        Returns:
            The LLM response string, or ``None`` if the request fails.
        """
        return self.orchestrator.request_from_gpt(user_prompt, context_messages, system_prompt)
