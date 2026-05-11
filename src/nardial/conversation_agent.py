import json
import logging
import re

from nardial.providers.device import DeviceAdapter
from nardial.providers.tts import TTSProvider
from nardial.providers.nlu import (
    NLUProvider,
    INTENT_YESNO_YES, INTENT_YESNO_NO, INTENT_YESNO_DONTKNOW,
)
from nardial.providers.llm import LLMProvider
from nardial.providers.vector_store import VectorStoreProvider
from nardial.interaction_orchestrator import InteractionOrchestrator, InteractionConfig


logger = logging.getLogger(__name__)


class ConversationAgent:
    """High-level async interface for running conversational interactions.

    Wraps :class:`~nardial.interaction_orchestrator.InteractionOrchestrator`
    and exposes convenient ``async`` methods for speech, listening, and LLM
    interaction.  All I/O methods are coroutines so the event loop is never
    blocked; blocking work is delegated to ``asyncio.to_thread`` inside the
    orchestrator.

    Parameters
    ----------
    device : DeviceAdapter
        Device adapter (Desktop, Pepper, Nao, AlphaMini) that handles I/O.
    tts_provider : TTSProvider
        Text-to-speech provider.
    nlu_provider : NLUProvider
        Natural-language understanding provider.
    llm_provider : LLMProvider, optional
        Large-language-model provider for generative responses.
    vector_store : VectorStoreProvider, optional
        Vector store for retrieval-augmented generation.
    interaction_config : InteractionConfig, optional
        Behavioural configuration.  Defaults are used when omitted.
    """

    def __init__(self, device: DeviceAdapter, tts_provider: TTSProvider,
                 nlu_provider: NLUProvider, llm_provider: LLMProvider | None = None,
                 vector_store: VectorStoreProvider | None = None,
                 interaction_config: InteractionConfig | None = None):
        self.orchestrator = InteractionOrchestrator(
            device=device,
            tts_provider=tts_provider,
            nlu_provider=nlu_provider,
            llm_provider=llm_provider,
            vector_store=vector_store,
            interaction_config=interaction_config,
        )

    # ------------------------------------------------------------------
    # Speech and playback
    # ------------------------------------------------------------------

    async def say(self, text) -> None:
        """Speak ``text`` using the configured TTS provider.

        Parameters
        ----------
        text : str
            Text to be spoken aloud.
        """
        await self.orchestrator.say(text)

    def play_audio(self, audio_file) -> None:
        """Play a pre-recorded audio file.

        Parameters
        ----------
        audio_file : str
            Path to an audio file.
        """
        self.orchestrator.play_audio(audio_file)

    def play_motion_sequence(self, motion_sequence_file) -> None:
        """Execute a predefined motion sequence (if supported by the device).

        Parameters
        ----------
        motion_sequence_file : str
            Path to a motion sequence file.
        """
        self.orchestrator.play_motion(motion_sequence_file)

    def play_animation(self, animation_name, run_async=False) -> None:
        """Trigger an animation on the current device.

        No-op on devices that do not support animations (e.g. Desktop).

        Parameters
        ----------
        animation_name : str
            Device-specific animation key.
        run_async : bool, optional
            If True, the animation runs without blocking execution.
        """
        self.orchestrator.play_animation(animation_name, run_async=run_async)

    # ------------------------------------------------------------------
    # Listening and questions
    # ------------------------------------------------------------------

    async def ask_yesno(self, question, max_attempts=1) -> str | None:
        """Ask a yes/no question and interpret the NLU response.

        Parameters
        ----------
        question : str
            The question to ask the user.
        max_attempts : int, optional
            Number of retries when no valid intent is detected.

        Returns
        -------
        str or None
            One of ``"yes"``, ``"no"``, ``"dontknow"``, or None.
        """
        attempts = 0
        while attempts < max_attempts:
            await self.say(question)
            result = await self.orchestrator.listen()
            if result.intent:
                logger.debug("answer_yesno: recognized_intent=%s", result.intent)
                if result.intent == INTENT_YESNO_YES:
                    return "yes"
                elif result.intent == INTENT_YESNO_NO:
                    return "no"
                elif result.intent == INTENT_YESNO_DONTKNOW:
                    return "dontknow"
            attempts += 1
        return None

    async def ask_open(self, question, max_attempts=2) -> str | None:
        """Ask an open-ended question and return the user's spoken response.

        Parameters
        ----------
        question : str
            The question to ask.
        max_attempts : int, optional
            Number of retries when no transcript is captured.

        Returns
        -------
        str or None
            The recognised user response, or None if no input is captured.
        """
        attempts = 0
        while attempts < max_attempts:
            await self.say(question)
            result = await self.orchestrator.listen()
            if result.transcript:
                return result.transcript
            attempts += 1
        return None

    async def ask_options(self, question, options, max_attempts=2) -> str | None:
        """Ask a question and match the response against a set of options.

        Matching is case-insensitive substring presence.

        Parameters
        ----------
        question : str
            The question to ask.
        options : list of str
            Expected keywords / option labels.
        max_attempts : int, optional
            Number of retries.

        Returns
        -------
        str or None
            The matched option, or None if no match is found.
        """
        answer = await self.ask_open(question, max_attempts=max_attempts)
        if answer:
            answer_lower = answer.lower()
            for opt in options:
                if opt.lower() in answer_lower:
                    return opt
        return None

    # ------------------------------------------------------------------
    # LLM integration
    # ------------------------------------------------------------------

    async def ask_llm(self, user_prompt, context_messages, system_prompt,
                      rag_enabled: bool = False,
                      index_name: str | None = None):
        """Send a request to the configured LLM and return the response.

        Parameters
        ----------
        user_prompt : str
            The user's input or query.
        context_messages : list
            Conversation history or additional context.
        system_prompt : str
            Instruction defining the assistant's behaviour.
        rag_enabled : bool, optional
            If True, augment the request with vector store context.
        index_name : str, optional
            Vector store index to query (overrides the provider default).

        Returns
        -------
        str or None
            The LLM response text, or None on failure.
        """
        return await self.orchestrator.request_from_llm(
            user_prompt,
            context_messages,
            system_prompt,
            rag_enabled=rag_enabled,
            index_name=index_name,
        )

    async def extract_topics_with_llm(self, raw_topics) -> list[str]:
        """Extract concise topic keywords from a list of raw user utterances.

        Uses the LLM to condense free-form text into 1–2 keywords per input
        item.  Falls back to a local heuristic if the LLM call fails.

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
            data = await self.orchestrator.request_from_llm(system_prompt=prompt)
            if not isinstance(data, list):
                raise ValueError("LLM did not return a JSON list")
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
