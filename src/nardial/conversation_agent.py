import json
import re

from nardial.providers.device import DeviceAdapter
from nardial.providers.tts import TTSProvider
from nardial.providers.nlu import (
    NLUProvider,
    INTENT_YESNO_YES, INTENT_YESNO_NO, INTENT_YESNO_DONTKNOW,
)
from nardial.providers.llm import LLMProvider
from nardial.providers.vector_store import VectorStoreProvider
from nardial.providers.screen import ScreenProvider
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

    Parameters
    ----------
    device : DeviceAdapter
        The device adapter (e.g., DesktopAdapter, PepperAdapter) that handles I/O.
    tts_provider : TTSProvider
        The TTS provider used to synthesize and play speech.
    nlu_provider : NLUProvider
        The NLU provider used to capture and interpret user input.
    int_config : InteractionConfig, optional
        Configuration for behavioral parameters. If not provided, defaults are used.

    Notes
    -----
    Ensure all required external services are running before using this class.
    """

    def __init__(self, device: DeviceAdapter, tts_provider: TTSProvider,
                 nlu_provider: NLUProvider, llm_provider: LLMProvider | None = None,
                 vector_store: VectorStoreProvider | None = None,
                 screen_provider: ScreenProvider | None = None,
                 int_config: InteractionConfig = None):
        self.orchestrator = InteractionOrchestrator(
            device=device,
            tts_provider=tts_provider,
            nlu_provider=nlu_provider,
            llm_provider=llm_provider,
            vector_store=vector_store,
            screen_provider=screen_provider,
            int_config=int_config,
        )

    def say(self, text, **kwargs):
        """
        Speak a piece of text using the configured TTS provider.

        Parameters
        ----------
        text : str
            The text to be spoken aloud.
        """
        self.orchestrator.say(text, **kwargs)

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

    def play_animation(self, animation_name, run_async=False):
        """
        Trigger an animation on the current device. No-op on devices that do not
        support animations (e.g., Desktop).

        Parameters
        ----------
        animation_name : str
            Name of the animation (device-specific key).
        run_async : bool, optional
            Whether to run the animation without blocking execution.
        """
        self.orchestrator.play_animation(animation_name, run_async=run_async)

    def ask_yesno(self, question, max_attempts=1):
        """
        Ask a yes/no question and interpret the response via the NLU provider.

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
        """
        attempts = 0
        while attempts < max_attempts:
            self.say(question)
            result = self.orchestrator.listen()
            if result.intent:
                print(f'context: answer_yesno, recognized_intent: {result.intent}')
                if result.intent == INTENT_YESNO_YES:
                    return "yes"
                elif result.intent == INTENT_YESNO_NO:
                    return "no"
                elif result.intent == INTENT_YESNO_DONTKNOW:
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
            result = self.orchestrator.listen()
            if result.transcript:
                return result.transcript
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

    async def show_image(self, src: str, caption: str = "") -> None:
            """Display an image on the screen, if a screen provider is configured.

            Parameters
            ----------
            src : str
                Local file path (relative to the static directory) or a full URL.
            caption : str
                Optional caption text shown below the image.
            """
            if self.orchestrator.screen_provider is not None:
                await self.orchestrator.screen_provider.show_image(src, caption=caption)

    async def show_video(self, src: str) -> None:
            """Display a video on the screen, if a screen provider is configured.

            Parameters
            ----------
            src : str
                Local file path or an embeddable URL.
            """
            if self.orchestrator.screen_provider is not None:
                await self.orchestrator.screen_provider.show_video(src)

    async def show_iframe(self, url: str) -> None:
            """Embed a URL in an iframe on the screen, if a screen provider is configured.

            Parameters
            ----------
            url : str
                The URL to embed.
            """
            if self.orchestrator.screen_provider is not None:
                await self.orchestrator.screen_provider.show_iframe(url)

    async def show_html(self, html: str) -> None:
            """Render a raw HTML snippet on the screen, if a screen provider is configured.

            Parameters
            ----------
            html : str
                The HTML to inject into the display area.
            """
            if self.orchestrator.screen_provider is not None:
                await self.orchestrator.screen_provider.show_html(html)

    async def show_buttons(self, options: list[str]) -> None:
            """Display clickable buttons on the screen, if a screen provider is configured.

            Parameters
            ----------
            options : list of str
                Button labels.
            """
            if self.orchestrator.screen_provider is not None:
                await self.orchestrator.screen_provider.show_buttons(options)

    async def show_text_input(self, prompt: str = "") -> None:
            """Show a text-input field on the screen, if a screen provider is configured.

            Parameters
            ----------
            prompt : str
                Placeholder / hint text for the input field.
            """
            if self.orchestrator.screen_provider is not None:
                await self.orchestrator.screen_provider.show_text_input(prompt)

    async def hide_input(self) -> None:
            """Hide the current input widget on the screen, if a screen provider is configured."""
            if self.orchestrator.screen_provider is not None:
                await self.orchestrator.screen_provider.hide_input()

    async def black(self) -> None:
            """Set the screen to black/blank, if a screen provider is configured."""
            if self.orchestrator.screen_provider is not None:
                await self.orchestrator.screen_provider.black()

    def extract_topics_with_llm(self, raw_topics):
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
            data = self.orchestrator.request_from_llm(system_prompt=prompt)
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

    def ask_llm(self, user_prompt, context_messages, system_prompt, rag_enabled: bool = False,
                index_name: str | None = None):
        """
        Send a request to the configured LLM and return the response.

        Parameters
        ----------
        user_prompt : str
            The user's input or query.
        context_messages : list
            Conversation history or additional context.
        system_prompt : str
            Instruction defining the assistant's behavior.
        rag_enabled : bool, optional
            Whether to augment the request with context from the configured vector store.
        index_name : str, optional
            Vector store index to query. Overrides the provider's default when set.

        Returns
        -------
        Any
            The parsed response from the LLM.
        """
        return self.orchestrator.request_from_llm(
            user_prompt,
            context_messages,
            system_prompt,
            rag_enabled=rag_enabled,
            index_name=index_name,
        )
