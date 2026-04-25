import json
import re

from nardial.interaction_orchestrator import InteractionOrchestrator, InteractionConfig


class ConversationAgent:
    """
    High-level interface for running conversational interactions with a user.

    This class wraps the lower-level `InteractionOrchestrator` and provides
    convenient methods for:
    - Speaking (`say`)
    - Playing audio and animations
    - Asking different types of questions (yes/no, open, options)
    - Calling LLMs (e.g., GPT) for reasoning or post-processing

    It abstracts device-specific behavior through a shared MCP interface and
    external services (Dialogflow, TTS, GPT).

    Parameters
    ----------
    device_mcp : module
        Device MCP module that handles I/O (listen, audio playback, etc.).
    int_config : InteractionConfig, optional
        Configuration for language, TTS, APIs, and interaction behavior.
        If not provided, a default configuration is used.

    Notes
    -----
    Most methods internally rely on:
    - Speech recognition (Dialogflow)
    - Text-to-speech (Google TTS or configured backend)
    - LLM calls (OpenAI GPT)

    Ensure required services are running before using this class.
    """

    def __init__(self, device_mcp, int_config: InteractionConfig = None):
        if int_config is None:
            int_config = InteractionConfig()
        self.orchestrator = InteractionOrchestrator(device_mcp=device_mcp, int_config=int_config)
        self.device_mcp = device_mcp

    def say(self, text):
        """
        Speak a piece of text using the configured TTS system.

        Parameters
        ----------
        text : str
            The text to be spoken aloud.
        """
        self.orchestrator.say(text)

    def play_audio(self, audio_file):
        """
        Play a pre-recorded audio file.

        Parameters
        ----------
        audio_file : str
            Path to an audio file.
        """
        self.orchestrator.play_audio(audio_file)

    def play_motion_sequence(self, motion_sequence_file):
        """
        Execute a predefined motion sequence (if supported by the device).

        Parameters
        ----------
        motion_sequence_file : str
            Path to a motion sequence file.
        """
        self.orchestrator.play_motion(motion_sequence_file)

    def play_animation(self, animation_name, block=False):
        """
        Trigger a built-in animation if supported by the MCP module.

        Parameters
        ----------
        animation_name : str
            Name of the animation.
        block : bool, optional
            Whether to block execution until the animation completes.

        """
        try:
            self.orchestrator.animate_naoqi(animation_name, block)
        except Exception as e:
            print(f"Failed to play animation: {animation_name}", e)

    def ask_yesno(self, question, max_attempts=1):
        """
        Ask a yes/no question and interpret the response using intent recognition.

        Parameters
        ----------
        question : str
            The question to ask the user.
        max_attempts : int, optional
            Number of retries if no valid answer is detected.

        Returns
        -------
        str or None
            One of: "yes", "no", "dontknow", or None if no valid response.

        Notes
        -----
        Requires Dialogflow intents:
        - yesno_yes
        - yesno_no
        - yesno_dontknow
        """
        attempts = 0
        while attempts < max_attempts:
            self.say(question)
            reply, intent = self.orchestrator.listen()

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
        """
        Ask an open-ended question and return the user's spoken response.

        Parameters
        ----------
        question : str
            The question to ask.
        max_attempts : int, optional
            Number of retries if no response is captured.

        Returns
        -------
        str or None
            The recognized user response, or None if no input is captured.
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
        """
        Ask a question and match the response against a set of predefined options.

        Parameters
        ----------
        question : str
            The question to ask.
        options : list of str
            List of expected keywords/options to match against the response.
        max_attempts : int, optional
            Number of retries.

        Returns
        -------
        str or None
            The matched option, or None if no match is found.

        Notes
        -----
        Matching is case-insensitive and based on substring presence.
        """
        answer = self.ask_open(question, max_attempts=max_attempts)
        if answer:
            answer_lower = answer.lower()
            for opt in options:
                if opt in answer_lower:
                    return opt
        return None

    def extract_topics_with_gpt(self, raw_topics):
        """
        Extract concise topic keywords from a list of raw user utterances.

        This method uses GPT to condense free-form text into 1–2 keyword(s)
        per input item. If GPT fails, a local heuristic fallback is used.

        Parameters
        ----------
        raw_topics : list of str
            Raw topic descriptions (often full sentences).

        Returns
        -------
        list of str
            De-duplicated list of lowercase topic keywords.

        Behavior
        --------
        - Prefers specific nouns (e.g., "dogs", "music", "travel")
        - Removes stopwords and short tokens
        - Ensures uniqueness and order preservation

        Fallback
        --------
        If GPT is unavailable or returns invalid output, a regex-based
        keyword extraction heuristic is applied locally.
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
                for w in picked[:2]:
                    if w not in seen:
                        out.append(w)
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
                    out.append(w)
                    seen.add(w)
            return out or _heuristic(raw_topics)
        except Exception:
            return _heuristic(raw_topics)

    def ask_llm(self, user_prompt, context_messages, system_prompt, rag_enabled=None, rag_index_name=None):
        """
        Send a request to the configured LLM (e.g., GPT) and return the response.

        Parameters
        ----------
        user_prompt : str
            The user's input or query.
        context_messages : list
            Conversation history or additional context.
        system_prompt : str
            Instruction defining the assistant's behavior.

        Returns
        -------
        Any
            The parsed response from the LLM (format depends on orchestrator).
        """
        return self.orchestrator.request_from_gpt(
            user_prompt,
            context_messages,
            system_prompt,
            rag_enabled=rag_enabled,
            rag_index_name=rag_index_name,
        )