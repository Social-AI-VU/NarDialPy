import asyncio
import functools
import json
import queue
import wave
from os.path import exists
from pathlib import Path
from threading import Thread
from time import strftime

from sic_framework.core import sic_logging
from sic_framework.core.sic_application import SICApplication

from nardial.providers.device import DeviceAdapter, AnimationStyle
from nardial.providers.tts import TTSProvider, _amplify_audio
from nardial.providers.nlu import NLUProvider, NLUResult
from nardial.providers.llm import LLMProvider, Message
from nardial.providers.vector_store import VectorStoreProvider
from nardial.providers.screen import ScreenProvider


class InteractionConfig:
    """
    Configuration class for managing behavioral parameters of the interaction orchestrator.
    Service-specific configuration (TTS, NLU, LLM, vector store) is handled by the respective providers.
    """

    def __init__(self, language="en", post_speech_delay=None,
                 signal_listening_behavior=True):
        self.language = language
        self.post_speech_delay = post_speech_delay
        self.signal_listening_behavior = signal_listening_behavior
        self.animated = True
        self.animation_style = AnimationStyle.EXPLANATORY
        self.always_regenerate = False
        self.chunk_audio = True

    @staticmethod
    def apply_config_defaults(config_attr, param_names):
        """
        Decorator factory that injects default values from a configuration object
        into function arguments when they are not explicitly provided.
        """
        def decorator(func):
            @functools.wraps(func)
            async def wrapper(self, *args, **kwargs):
                config = getattr(self, config_attr)
                for name in param_names:
                    if kwargs.get(name) is None:
                        kwargs[name] = getattr(config, name)
                return await func(self, *args, **kwargs)
            return wrapper
        return decorator


class InteractionOrchestrator:
    def __init__(self, device: DeviceAdapter, tts_provider: TTSProvider,
                 nlu_provider: NLUProvider, llm_provider: LLMProvider | None = None,
                 vector_store: VectorStoreProvider | None = None,
                 screen_provider: ScreenProvider | None = None,
                 int_config: InteractionConfig = None):

        if int_config is None:
            int_config = InteractionConfig()

        # Development Logging
        self.app = SICApplication()
        self.logger = self.app.get_app_logger()
        self.app.set_log_level(sic_logging.DEBUG)
        self.app.set_log_file_path("./logs")

        self.logger.info("SETTING UP BASIC PROCESSING")

        # Data logging
        self._log_queue = None
        self._log_thread = None

        # Interaction configuration
        self.interaction_conf = int_config

        self.logger.info("SETTING UP LLM")
        self.llm_provider = llm_provider
        self.logger.info('Complete')

        self.logger.info("SETTING UP VECTOR STORE")
        self.vector_store = vector_store
        self.logger.info('Complete')

        self.logger.info("SETTING UP SCREEN PROVIDER")
        self.screen_provider = screen_provider
        self.logger.info('Complete')

        self.logger.info("SETTING UP TTS")
        self.tts_provider = tts_provider
        self.logger.info('Complete')

        self.logger.info("SETTING UP DEVICE")
        self.device = device
        device.setup(self.logger)
        self.logger.info("Complete")

        self.logger.info("SETTING UP NLU")
        self.nlu_provider = nlu_provider
        self.logger.info("Complete and ready for interaction!")

    def start_logging(self, log_id, init_data: dict):
        folder = Path("logs")
        folder.mkdir(parents=True, exist_ok=True)
        log_path = folder / f"{log_id}.log"
        self._log_queue = queue.Queue()
        self._log_thread = Thread(target=self.log_writer, args=(log_path,), daemon=True)
        self._log_thread.start()

        timestamp = strftime("%Y-%m-%d %H:%M:%S")
        self._log_queue.put(f'[{timestamp}] ### START NEW LOG ###')
        self._log_queue.put(', '.join(f"{k}: {v}" for k, v in init_data.items()))

    def stop_logging(self):
        if self._log_queue:
            self._log_queue.put(None)
        if self._log_thread:
            self._log_thread.join()

    def log_writer(self, log_path):
        with open(log_path, 'a', encoding='utf-8') as f:
            while True:
                item = self._log_queue.get()
                if item is None:
                    break  # Exit signal
                f.write(item + '\n')
                f.flush()

    def log_utterance(self, speaker, text):
        if self._log_queue:
            timestamp = strftime("%Y-%m-%d %H:%M:%S")
            self._log_queue.put(f"[{timestamp}] {speaker}: {text}")

    def log_recognition_result(self, recognition_result):
        if self._log_queue:
            timestamp = strftime("%Y-%m-%d %H:%M:%S")
            self._log_queue.put(f"[{timestamp}] recognition result: {recognition_result}")

    async def _push_transcript(self, text: str) -> None:
        """Push the robot's spoken text to the screen's conversation log.

        Called by :meth:`say` after every TTS call.  Both bundled implementations
        (``NullScreenProvider``, ``SICScreenAdapter``) are non-blocking — the
        ``await`` returns immediately.
        """
        if self.screen_provider is not None:
            await self.screen_provider.show_transcript(text)

    async def _push_user_transcript(self, text: str) -> None:
        """Push the user's recognised speech to the screen's conversation log.

        Called by :meth:`listen` when a non-empty transcript is returned by the
        NLU provider.  Lets the screen show both sides of the conversation.
        """
        if self.screen_provider is not None:
            await self.screen_provider.show_user_transcript(text)

    @InteractionConfig.apply_config_defaults('interaction_conf', ['post_speech_delay', 'animated', 'always_regenerate', 'chunk_audio'])
    async def say(self, text, post_speech_delay=None, animated=False, amplified=False, always_regenerate=False, chunk_audio=False,
            voice_settings=None):
        if animated:
            self.device.play_speaking_animation(self.interaction_conf.animation_style)
        try:
            await asyncio.to_thread(
                self.tts_provider.speak, text,
                amplified=amplified,
                always_regenerate=always_regenerate,
                chunk_audio=chunk_audio,
                voice_settings=voice_settings,
            )
        except asyncio.CancelledError:
            self.tts_provider.cancel()
            raise
        self.log_utterance(speaker='robot', text=text)
        await self._push_transcript(text)
        if post_speech_delay and post_speech_delay > 0:
            await asyncio.sleep(post_speech_delay)

    async def listen(self, context=None, timeout=10) -> NLUResult:
        if self.interaction_conf.signal_listening_behavior:
            self.device.signal_listening(start=True)
        try:
            result = await asyncio.to_thread(
                self.nlu_provider.listen, context=context, timeout=timeout
            )
        except asyncio.CancelledError:
            self.nlu_provider.cancel()
            raise
        if self.interaction_conf.signal_listening_behavior:
            self.device.signal_listening(start=False)
        if result.transcript:
            self.log_utterance(speaker='user', text=result.transcript)
            await self._push_user_transcript(result.transcript)
        return result

    async def request_from_llm(self, user_prompt=None, context_messages=None, system_prompt=None,
                         json_response=False, rag_enabled: bool = False, index_name: str | None = None):
        if self.llm_provider is None:
            self.logger.warning("No LLM provider configured")
            return None

        if rag_enabled and self.vector_store is not None and user_prompt is not None and str(user_prompt).strip():
            snippets = self.vector_store.query(str(user_prompt).strip(), index_name=index_name)
            if snippets:
                rag_prefix = (
                    "Use the following retrieved knowledge as supporting context. "
                    "If it conflicts with conversation context, note uncertainty instead of inventing facts.\n\n"
                    + "\n\n".join(snippets)
                )
                system_prompt = f"{system_prompt}\n\n{rag_prefix}" if system_prompt else rag_prefix

        messages: list[Message] = []
        if context_messages:
            for msg in context_messages:
                if isinstance(msg, Message):
                    messages.append(msg)
                elif isinstance(msg, dict):
                    messages.append(Message(role=msg.get("role", "user"), content=msg.get("content", "")))
                elif isinstance(msg, str):
                    messages.append(Message(role="user", content=msg))
        if user_prompt is not None:
            messages.append(Message(role="user", content=str(user_prompt)))

        try:
            text = await asyncio.to_thread(
                self.llm_provider.complete, messages, system_prompt=system_prompt or ""
            )
            if json_response:
                return json.loads(text)
            return text
        except Exception as e:
            print(f"Exception: {e}")
            return None

    def play_audio(self, audio_file, amplified=False, log=True):
        if not exists(audio_file):
            self.logger.error(f"Audio file not found: {audio_file}")
            return
        with wave.open(audio_file, 'rb') as wf:
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            if sample_width != 2:
                raise ValueError("WAV file is not 16-bit audio. Sample width = {} bytes.".format(sample_width))
            audio = wf.readframes(n_frames)
            if amplified:
                audio = _amplify_audio(audio)
            self.device.play_audio_bytes(audio, framerate)
            if log:
                self.log_utterance(speaker='robot', text=f'plays {audio_file}')

    def play_animation(self, animation_name, run_async=False):
        self.device.play_animation(animation_name, run_async=run_async)

    def play_motion(self, motion_name):
        self.device.play_motion_sequence(motion_name)

    def disconnect(self):
        self.tts_provider.close()
        self.device.disconnect()
        if self.vector_store is not None:
            self.vector_store.close()
        if self.screen_provider is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.screen_provider.close())
            except RuntimeError:
                asyncio.run(self.screen_provider.close())

    def set_interaction_conf(self, interaction_conf: InteractionConfig):
        self.interaction_conf = interaction_conf
