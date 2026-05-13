import asyncio
import json
from json import load
import queue
import re
import wave
import logging
from enum import Enum
from os import environ, fsync
from os.path import exists, abspath, join
from pathlib import Path
import random as rand
from threading import Thread
from time import sleep, strftime, monotonic

import numpy as np
import mini.mini_sdk as MiniSdk

from mini import MouthLampColor, MouthLampMode
from mini.apis.api_action import PlayAction
from mini.apis.api_expression import SetMouthLamp, PlayExpression
from google.cloud import dialogflow as gdialogflow
from google.oauth2.service_account import Credentials
from sic_framework.core import sic_logging
from sic_framework.core.message_python2 import AudioRequest
from sic_framework.core.sic_application import SICApplication
from sic_framework.devices import Pepper, Nao
from sic_framework.devices.alphamini import Alphamini
from sic_framework.devices.common_naoqi.naoqi_leds import NaoFadeRGBRequest
from sic_framework.devices.common_naoqi.naoqi_motion import NaoqiAnimationRequest
from sic_framework.devices.common_naoqi.naoqi_motion_recorder import NaoqiMotionRecording, PlayRecording
from sic_framework.devices.common_naoqi.naoqi_text_to_speech import NaoqiTextToSpeechRequest
from sic_framework.devices.desktop import Desktop
from sic_framework.devices.device import SICDeviceManager
from sic_framework.services.dialogflow.dialogflow import (
    Dialogflow,
    DialogflowConf,
    GetIntentRequest,
)
from sic_framework.services.google_tts.google_tts import (
    GetSpeechRequest,
    Text2Speech,
    Text2SpeechConf,
)
from sic_framework.services.llm.openai_gpt import GPT
from sic_framework.services.llm import GPTConf, GPTRequest
from sic_framework.services.datastore.redis_datastore import (
    RedisDatastoreConf,
    RedisDatastore,
    IngestVectorDocsRequest,
    QueryVectorDBRequest,
    VectorDBResultsMessage,
)
from dotenv import load_dotenv
from typing import Optional, Union

from nardial.tts_manager import NaoqiTTSConf, TTSConf, GoogleTTSConf, ElevenLabsTTSConf, ElevenLabsTTS, TTSCacher
from elevenlabs import ElevenLabs


class AnimationType(Enum):
    """
    Enumeration of animation types supported by the system.
    """
    ACTION = 1
    EXPRESSION = 2


class AnimationStyle(Enum):
    """
    Enumeration of animation styles for robot behavior.
    """
    EXPRESSIVE = 1
    EXPLANATORY = 2


def resolve_log_level(log_level: Optional[Union[str, int]], sic=sic_logging):
    """
    Map ``InteractionConfig.log_level`` to a level accepted by ``SICApplication.set_log_level``.

    ``None`` preserves the previous default (DEBUG). Names are case-insensitive (e.g. ``"INFO"``).
    """
    if log_level is None:
        return sic.DEBUG
    if isinstance(log_level, int):
        return log_level
    name = str(log_level).strip().upper()
    if hasattr(sic, name):
        return getattr(sic, name)
    raise ValueError(
        f"Unknown log_level {log_level!r}; use None or an int, or one of: "
        f"{', '.join(sorted(k for k in dir(sic) if k.isupper() and not k.startswith('_')))}"
    )


def find_project_root(start: Path) -> Path:
    """
    Locate the project root directory by searching upward
    for a folder containing a 'conf' directory.

    Args:
        start (Path): Starting directory for the search.

    Returns:
        Path: Path to the project root directory.

    Raises:
        FileNotFoundError: If no 'conf' directory is found.
    """
    for path in [start] + list(start.parents):
        if (path / "conf").exists():
            return path
    raise FileNotFoundError("Could not find 'conf' directory")


class InteractionConfig:
    """
    Configuration class for managing interaction settings,
    including TTS, API keys, and behavioral parameters.
    """

    def __init__(self, language="en", tts_conf: TTSConf = None, microphone_device=None, google_keyfile_path=None,
                 env_file_path=None, post_speech_delay=None, signal_listening_behavior=True, keyboard_input=False,
                 dialogflow: bool = True,
                 rag: bool = False, ingest_docs: bool = False, input_path: str = "", index_name: str = "",
                 embedding_model: str = "", chunk_chars: int = 1200, chunk_overlap: int = 150,
                 override_existing: bool = False, force_recreate_index: bool = False,
                 log_level: Optional[Union[str, int]] = None, detailed_transcript: bool = False,
                 langgraph: bool = False):
        """
        Initialize interaction configuration.

        Args:
            language (str): Language code (default: 'en').
            tts_conf (TTSConf, optional): Text-to-speech configuration.
            microphone_device: Optional external microphone device.
            google_keyfile_path (str, optional): Path to Google credentials file.
            env_file_path (str, optional): Path to environment variable file.
            post_speech_delay (float, optional): Delay after speech playback.
            signal_listening_behavior (bool): Whether to show listening indicators.
            log_level (str | int | None): SIC / app log level name (e.g. ``\"INFO\"``) or numeric level.
                ``None`` defaults to DEBUG (matches prior hard-coded behavior).
            detailed_transcript (bool): When True, store detailed session transcript metadata
                (timing metrics and full user/robot events).
            langgraph (bool): If True, route LLM calls through LangChain ChatOpenAI
                (LangSmith tracing compatible) instead of the SIC GPT service.
        """
        self.language = language
        self.keyboard_input = keyboard_input
        self.dialogflow = bool(dialogflow)

        self.tts_conf = tts_conf
        if not tts_conf:
            self.tts_conf = GoogleTTSConf(
                google_tts_voice_name="en-US-Standard-C",
                speaking_rate=1.0
            )

        self.microphone_device = microphone_device
        self.google_keyfile_path = google_keyfile_path
        self.env_file_path = env_file_path
        if not self.google_keyfile_path:
            self.google_keyfile_path = abspath(join(find_project_root(Path.cwd()), "conf", "google", "google_keyfile.json"))
        if not self.env_file_path:
            project_root = find_project_root(Path.cwd())
            default_env_file_path = abspath(join(project_root, "conf", ".env"))
            legacy_openai_env_path = abspath(join(project_root, "conf", "openai", ".openai_env"))
            self.env_file_path = legacy_openai_env_path if exists(legacy_openai_env_path) else default_env_file_path

        self.post_speech_delay = post_speech_delay
        self.signal_listening_behavior = signal_listening_behavior  # if True, the robot will show a visual behavior when it is listening for user input
        self.rag = rag
        self.ingest_docs = ingest_docs
        self.input_path = input_path
        self.index_name = index_name
        self.embedding_model = embedding_model
        self.chunk_chars = chunk_chars
        self.chunk_overlap = chunk_overlap
        self.override_existing = override_existing
        self.force_recreate_index = force_recreate_index
        self.animated = True
        self.animation_style = AnimationStyle.EXPLANATORY
        self.always_regenerate = False  # if True, the TTS audio will always be regenerated instead of loading from cache
        self.chunk_audio = True
        self.log_level = log_level
        self.detailed_transcript = bool(detailed_transcript)
        self.langgraph = bool(langgraph)
        self._validate_rag_config()

        self.dialogflow_conf = self.dialogflow_conf = DialogflowConf(
            keyfile_json=json.load(open(self.google_keyfile_path)),
            sample_rate_hertz=44100,
            language=language
        )

    def _validate_rag_config(self):
        if not self.rag:
            return
        if not isinstance(self.ingest_docs, bool):
            raise ValueError("InteractionConfig.ingest_docs must be a bool when rag=True")
        if not self.embedding_model:
            raise ValueError("InteractionConfig.embedding_model is required when rag=True")
        if self.ingest_docs:
            required_fields = {
                "input_path": self.input_path,
                "index_name": self.index_name,
                "embedding_model": self.embedding_model,
            }
            missing = [k for k, v in required_fields.items() if not v]
            if missing:
                raise ValueError(
                    "Missing required InteractionConfig fields when rag=True and ingest_docs=True: "
                    + ", ".join(missing)
                )
            if not isinstance(self.chunk_chars, int) or self.chunk_chars <= 0:
                raise ValueError("InteractionConfig.chunk_chars must be a positive int when ingest_docs=True")
            if not isinstance(self.chunk_overlap, int) or self.chunk_overlap < 0:
                raise ValueError("InteractionConfig.chunk_overlap must be a non-negative int when ingest_docs=True")
            if not isinstance(self.override_existing, bool):
                raise ValueError("InteractionConfig.override_existing must be bool when ingest_docs=True")
            if not isinstance(self.force_recreate_index, bool):
                raise ValueError("InteractionConfig.force_recreate_index must be bool when ingest_docs=True")

    @staticmethod
    def apply_config_defaults(config_attr, param_names):
        """
        Decorator factory that injects default values from a configuration object
        into function arguments when they are not explicitly provided.

        Args:
            config_attr (str): Name of the attribute containing the config object.
            param_names (list[str]): List of parameter names to fill from config.

        Returns:
            callable: Decorator that wraps a function to apply defaults.
        """
        def decorator(func):
            """
            Decorator that applies configuration defaults to a function.
            """
            def wrapper(self, *args, **kwargs):
                """
                Wrapper function that fills missing keyword arguments
                with values from the configuration object.

                Args:
                    *args: Positional arguments.
                    **kwargs: Keyword arguments.

                Returns:
                    Any: Result of the wrapped function.
                """
                config = getattr(self, config_attr)
                for name in param_names:
                    if kwargs.get(name) is None:
                        kwargs[name] = getattr(config, name)
                return func(self, *args, **kwargs)

            return wrapper

        return decorator


class InteractionOrchestrator:
    def __init__(self, device_manager: SICDeviceManager, int_config: InteractionConfig):

        print("\n SETTING UP BASIC PROCESSING")
        # Development Logging
        self.app = SICApplication()
        self.logger = self.app.get_app_logger()
        _sic_level = resolve_log_level(int_config.log_level)
        self.app.set_log_level(_sic_level)
        if isinstance(_sic_level, int):
            for _name in ("nardial", "droomrobot"):
                logging.getLogger(_name).setLevel(_sic_level)
        self.app.set_log_file_path("./logs")

        # Data logging
        self._log_queue = None
        self._log_thread = None
        self.last_robot_speech_start_monotonic = None
        self.last_llm_usage = None

        # Interaction configuration
        self.interaction_conf = int_config

        # Background loop
        self.background_loop = asyncio.new_event_loop()
        self.background_thread = Thread(target=self._start_loop, daemon=True)
        self.background_thread.start()
        print('Complete')

        print("\n SETTING UP OPENAI")
        self.gpt = None
        self.langchain_chat = None
        self.datastore = None
        self.rag_enabled = bool(self.interaction_conf.rag)
        if self.interaction_conf.env_file_path:
            load_dotenv(self.interaction_conf.env_file_path)
        openai_key = environ.get("OPENAI_API_KEY")
        try:
            self.gpt = GPT(conf=GPTConf(openai_key=environ["OPENAI_API_KEY"]))
        except KeyError:
            self.logger.warning("No openAI key available")
        if self.interaction_conf.langgraph:
            try:
                from langchain_openai import ChatOpenAI
                self.langchain_chat = ChatOpenAI(
                    model=environ.get("NARDIAL_OPENAI_MODEL", "gpt-4o-mini"),
                )
                self.logger.info(
                    "LangChain LLM enabled via InteractionConfig.langgraph=True using model %s",
                    environ.get("NARDIAL_OPENAI_MODEL", "gpt-4o-mini"),
                )
            except Exception as e:
                self.logger.warning(
                    "Failed to initialize LangChain ChatOpenAI; falling back to GPT service: %s",
                    e,
                )
        if self.rag_enabled:
            self._setup_rag(openai_key=openai_key)
        print('Complete')

        print("\n SETTING UP TTS")
        self.tts = None
        self.sample_rate = None
        self.elevenlabs = None
        self.tts_conf = self.interaction_conf.tts_conf
        self.tts_cacher = TTSCacher()
        if isinstance(self.tts_conf, GoogleTTSConf):
            self.activate_google_tts()
        elif isinstance(self.tts_conf, ElevenLabsTTSConf):
            self.activate_elevenlabs_tts()
        elif isinstance(self.tts_conf, NaoqiTTSConf):
            pass
        else:
            raise ValueError(f"Unknown tts_conf {self.tts_conf}")
        print("Complete")

        print("\n SETTING UP DEVICE MANAGER")
        self.device_manager = device_manager
        self.mic = self.device_manager.mic
        self.speaker = None
        self.mini_api = None
        self.animation_futures = []
        if self.interaction_conf.microphone_device:
            print("\n Additional Microphone Device Detected")
            self.mic = self.interaction_conf.microphone_device.mic
        if isinstance(self.device_manager, Alphamini):
            self.setup_alphamini()
        elif isinstance(self.device_manager, Pepper):
            self.setup_pepper()
        elif isinstance(self.device_manager, Nao):
            self.setup_nao()
        elif isinstance(self.device_manager, Desktop):
            self.setup_desktop()
        else:
            raise ValueError(f"DeviceManager {self.device_manager} is currently not supported")
        print("Complete")

        print("\n SETTING UP DIALOGFLOW")
        self.request_id = np.random.randint(10000)
        self.dialogflow = None
        self._dialogflow_text_client = None
        if self.interaction_conf.dialogflow:
            df_input = None if self.interaction_conf.keyboard_input else getattr(self, 'mic', None)
            self.dialogflow = Dialogflow(ip="localhost", conf=self.interaction_conf.dialogflow_conf, input_source=df_input)
            self.dialogflow.register_callback(self._on_dialog)
            print("Complete and ready for interaction!")
        else:
            print("Skipped (dialogflow disabled in InteractionConfig).")

    def _detect_intent_from_text(self, text, context=None):
        if not text:
            return None
        try:
            if self._dialogflow_text_client is None:
                credentials = Credentials.from_service_account_info(self.interaction_conf.dialogflow_conf.keyfile_json)
                self._dialogflow_text_client = gdialogflow.SessionsClient(credentials=credentials)

            project_id = self.interaction_conf.dialogflow_conf.project_id
            session_path = self._dialogflow_text_client.session_path(project_id, str(self.request_id))
            query_input = gdialogflow.QueryInput(
                text=gdialogflow.TextInput(
                    text=text,
                    language_code=self.interaction_conf.dialogflow_conf.language_code,
                )
            )

            contexts = []
            for context_name, lifespan in (context or {}).items():
                context_id = f"projects/{project_id}/agent/sessions/{self.request_id}/contexts/{context_name}"
                contexts.append(gdialogflow.Context(name=context_id, lifespan_count=lifespan))
            query_params = gdialogflow.QueryParameters(contexts=contexts) if contexts else None

            request = {"session": session_path, "query_input": query_input}
            if query_params:
                request["query_params"] = query_params

            reply = self._dialogflow_text_client.detect_intent(request=request)
            if reply and reply.query_result and reply.query_result.intent:
                return reply.query_result.intent.display_name
            return None
        except Exception as e:
            self.logger.warning("Dialogflow text intent detection failed: %s", e)
            return None

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

    def activate_google_tts(self):
        if self.interaction_conf.google_keyfile_path is None:
            raise ValueError("Google TTS requires a google keyfile to initialize")
        google_tts_conf = Text2SpeechConf(
            keyfile_json=json.load(open(self.interaction_conf.google_keyfile_path)),
            speaking_rate=self.tts_conf.speaking_rate
        )
        self.tts = Text2Speech(conf=google_tts_conf)
        init_reply = self.tts.request(GetSpeechRequest(text="Ik am initializing",
                                                       voice_name=self.tts_conf.google_tts_voice_name,
                                                       ssml_gender=self.tts_conf.google_tts_voice_gender))
        self.sample_rate = init_reply.sample_rate
        print('Google TTS activated')

    def activate_elevenlabs_tts(self):
        if "ELEVENLABS_API_KEY" not in environ:
            raise ValueError("ElevenLabs TTS requires an ELEVENLABS_API_KEY environment variable to initialize")
        self.sample_rate = 22050
        self.tts = ElevenLabsTTS(
            elevenlabs_key=environ["ELEVENLABS_API_KEY"],
            voice_id=self.tts_conf.voice_id,
            model_id=self.tts_conf.model_id,
            sample_rate=self.sample_rate,
            speaking_rate=self.tts_conf.speaking_rate
        )
        connect_to_elevenlabs_future = asyncio.run_coroutine_threadsafe(self.tts.connect(), self.background_loop)
        try:
            connect_to_elevenlabs_future.result()
            asyncio.run_coroutine_threadsafe(self.tts.speak("Initializing text to speech"), self.background_loop).result()
            self.elevenlabs = ElevenLabs(api_key=environ["ELEVENLABS_API_KEY"])
            print('Elevenlabs TTS activated')
        except Exception as e:
            self.logger.error("Failed to connect to elevenlabs", exc_info=e)

    def setup_alphamini(self):
        print("\n Device is ALPHAMINI")
        print("Connecting to miniSDK")
        self.speaker = self.device_manager.speaker
        # Create asyncio event loop to keep connection open to miniSDK.
        connect_to_mini_sdk_future = asyncio.run_coroutine_threadsafe(self._connect_once(), self.background_loop)
        try:
            connect_to_mini_sdk_future.result()
            self.animate_alphamini(AnimationType.ACTION, "009")  # Wake up
            self.animate_alphamini(AnimationType.EXPRESSION, "codemao20")  # Blink
        except Exception as e:
            self.logger.error("Failed to connect to mini device", exc_info=e)

    def setup_pepper(self):
        self.speaker = self.device_manager.speaker
        print("\n Device is PEPPER")

    def setup_nao(self):
        self.speaker = self.device_manager.speaker
        print("\n Device is NAO")

    def setup_desktop(self):
        print("\n Device is COMPUTER")
        self.speaker = self.device_manager.speakers

    @InteractionConfig.apply_config_defaults('interaction_conf', ['post_speech_delay', 'animated', 'always_regenerate', 'chunk_audio'])
    def say(self, text, post_speech_delay=None, animated=False, amplified=False, always_regenerate=False, chunk_audio=False):
        self.last_robot_speech_start_monotonic = monotonic()
        if animated:
            self.animation()

        if isinstance(self.tts_conf, NaoqiTTSConf):
            self.naoqi_say(text, post_speech_delay=post_speech_delay, animated=animated)
        elif isinstance(self.tts_conf, GoogleTTSConf):
            self.google_say(text, post_speech_delay=post_speech_delay, amplified=amplified, always_regenerate=always_regenerate)
        elif isinstance(self.tts_conf, ElevenLabsTTSConf):
            self.elevenlabs_say(text, post_speech_delay=post_speech_delay, amplified=amplified, always_regenerate=always_regenerate, chunking=chunk_audio)
        else:
            raise ValueError(f'Unsupported tts_conf type: {type(self.tts_conf)}')


    def naoqi_say(self, text, post_speech_delay=None, animated=False):
        if not isinstance(self.device_manager, Pepper) and not isinstance(self.device_manager, Nao):
            return

        self.device_manager.tts.request(NaoqiTextToSpeechRequest(text, animated=animated, language=self.interaction_conf.language))

        if post_speech_delay and post_speech_delay > 0:
            sleep(post_speech_delay)

    def google_say(self, text, post_speech_delay=None, amplified=False, always_regenerate=False):
        # Generate cache key and load cached speech audio if available.
        tts_key = self.tts_cacher.make_tts_key(text, self.tts_conf)
        audio_file = self.tts_cacher.load_audio_file(tts_key)

        # If requested and available play cached speech audio
        if not always_regenerate and audio_file:
            self.log_utterance(speaker='robot', text=f'{text} (cache)')
            self.play_audio(audio_file, log=False)
        else:  # Else generate new speech audio
            reply = self.tts.request(GetSpeechRequest(
                text=text,
                voice_name=self.tts_conf.google_tts_voice_name,
                ssml_gender=self.tts_conf.google_tts_voice_gender,
                speaking_rate=self.tts_conf.speaking_rate
            ))
            audio_bytes = reply.waveform
            sample_rate = reply.sample_rate

            # Amplify audio if needed
            if audio_bytes and amplified:
                audio_bytes = self._amplify_audio(audio_bytes)

            # Play audio
            self.speaker.request(AudioRequest(audio_bytes, sample_rate))
            self.log_utterance(speaker='robot', text=text)

            # Save to cache file
            self.tts_cacher.save_audio_file(tts_key, audio_bytes, sample_rate)

        # Sleep if requested
        if post_speech_delay and post_speech_delay > 0:
            sleep(post_speech_delay)

    def elevenlabs_say(self, text, post_speech_delay=None, amplified=False, always_regenerate=False, chunking=True):
        if not chunking or self.interaction_conf.tts_conf.model_id == 'eleven_v3':
            text_chunks = [text]
        else:
            text_chunks = self._split_text(text, max_len=80)

        for chunk in text_chunks:
            # Normalize and hash text
            tts_key = self.tts_cacher.make_tts_key(chunk, self.tts_conf)

            if not always_regenerate:
                audio_file = self.tts_cacher.load_audio_file(tts_key)
                if audio_file:
                    self.log_utterance(speaker='robot', text=f'{chunk} (cache)')
                    self.play_audio(audio_file, log=False)
                    continue

            # Generate new audio
            audio_bytes = self.elevenlabs_generate_chunk_audio(chunk, amplified)
            if not audio_bytes:
                self.logger.error("ElevenLabs returned no audio for chunk; skipping playback.")
                continue

            # Play audio
            self.speaker.request(AudioRequest(audio_bytes, self.sample_rate))
            self.log_utterance(speaker='robot', text=f'{chunk}')

            # Sleep if requested
            if post_speech_delay and post_speech_delay > 0:
                sleep(post_speech_delay)

    def elevenlabs_generate_chunk_audio(self, text, amplified=False):
        # Normalize and hash text
        tts_key = self.tts_cacher.make_tts_key(text, self.tts_conf)

        # ElevenLabs TTS returns bytes
        audio_bytes = asyncio.run_coroutine_threadsafe(self.tts.speak(text), self.background_loop).result()
        if not audio_bytes:
            return None

        if audio_bytes and amplified:
            audio_bytes = self._amplify_audio(audio_bytes)

        # Save to cache file
        self.tts_cacher.save_audio_file(tts_key, audio_bytes, self.sample_rate)

        return audio_bytes

    def listen(self, context=None, timeout=10, detect_intent=True):
        """Collect user input and optionally map it to a Dialogflow-style intent.

        When ``keyboard_input`` is True and ``detect_intent`` is False, skips
        :meth:`_detect_intent_from_text` so open routing (e.g. hybrid LLM router
        turns) does not pay intent classification; use ``detect_intent=True`` for
        yes/no and other moves that need intents.

        On keyboard input, Ctrl+D (EOF) raises ``EOFError`` from ``input``; that
        is returned as the pair ``(None, "__stdin_eof__")`` so callers can exit loops
        without treating it like an empty line (which returns ``(None, None)``).
        """

        if self.interaction_conf.signal_listening_behavior:
            self.signal_listening_behavior(start=True)
        if self.interaction_conf.keyboard_input:
            try:
                line = input("Your reply: ").strip()
            except EOFError:
                return None, "__stdin_eof__"
            if not line:
                return None, None
            self.log_utterance(speaker="child", text=line)
            intent = None
            if self.interaction_conf.dialogflow and detect_intent:
                intent = self._detect_intent_from_text(line, context=context)
                print("The detected intent:", intent)
            return line, intent
        else:
            if not self.interaction_conf.dialogflow or self.dialogflow is None:
                self.logger.warning("listen() called with keyboard_input=False while dialogflow is disabled")
                return None, None
            try:
                reply = self.dialogflow.request(GetIntentRequest(self.request_id, context), timeout=timeout)
                print("The detected intent:", reply.intent)
                intent = reply.intent if reply.intent else None
                if not detect_intent:
                    intent = None
                if reply.response.query_result.query_text:
                    return reply.response.query_result.query_text, intent
                return None, intent
            except TimeoutError as e:
                print("Error:", e)
        if self.interaction_conf.signal_listening_behavior:
            self.signal_listening_behavior(start=False)

        return response, intent

    def play_audio(self, audio_file, amplified=False, log=True):
        if not exists(audio_file):
            self.logger.error(f"Audio file not found: {audio_file}")
            return
        with wave.open(audio_file, 'rb') as wf:
            # Get parameters
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()

            # Ensure format is 16-bit (2 bytes per sample)
            if sample_width != 2:
                raise ValueError("WAV file is not 16-bit audio. Sample width = {} bytes.".format(sample_width))

            audio = wf.readframes(n_frames)
            if amplified:
                audio = self._amplify_audio(audio)

            self.speaker.request(AudioRequest(audio, framerate))
            if log:
                self.log_utterance(speaker='robot', text=f'plays {audio_file}')

    def request_from_gpt(self, user_prompt=None, context_messages=None, system_prompt=None, json_response=False,
                         rag_enabled=None, rag_index_name=None):
        self.last_llm_usage = None
        use_rag = self.rag_enabled if rag_enabled is None else bool(rag_enabled)
        if use_rag and not rag_index_name and not self.interaction_conf.index_name:
            raise ValueError("RAG-enabled LLM requests require an index name")

        if use_rag and user_prompt is not None and str(user_prompt).strip():
            rag_context = self._retrieve_rag_context(
                str(user_prompt).strip(),
                index_name=rag_index_name or self.interaction_conf.index_name,
                raise_on_error=True,
            )
            if rag_context:
                rag_prefix = (
                    "Use the following retrieved knowledge as supporting context. "
                    "If it conflicts with conversation context, note uncertainty instead of inventing facts.\n\n"
                    f"{rag_context}"
                )
                if system_prompt:
                    system_prompt = f"{system_prompt}\n\n{rag_prefix}"
                else:
                    system_prompt = rag_prefix
        try:
            if self.interaction_conf.langgraph and self.langchain_chat is not None:
                from langchain_core.messages import SystemMessage, HumanMessage
                messages = []
                if system_prompt:
                    messages.append(SystemMessage(content=str(system_prompt)))
                if context_messages:
                    context_blob = "\n".join(str(m) for m in context_messages if m is not None)
                    if context_blob.strip():
                        messages.append(
                            SystemMessage(content=f"Conversation context:\n{context_blob}")
                        )
                messages.append(HumanMessage(content=str(user_prompt or "")))
                resp = self.langchain_chat.invoke(messages)
                text_content = getattr(resp, "content", "")
                if isinstance(text_content, str):
                    text = text_content.strip()
                elif isinstance(text_content, list):
                    text = "".join(
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in text_content
                    ).strip()
                else:
                    text = str(text_content or "").strip()
                usage = getattr(resp, "usage_metadata", None) or getattr(resp, "response_metadata", {}).get("token_usage", {})
                self.last_llm_usage = {
                    "provider": "langchain_openai",
                    "model": environ.get("NARDIAL_OPENAI_MODEL", "gpt-4o-mini"),
                    "input_tokens": usage.get("input_tokens") or usage.get("prompt_tokens"),
                    "output_tokens": usage.get("output_tokens") or usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                }
            else:
                resp = self.gpt.request(GPTRequest(prompt=user_prompt, context_messages=context_messages, system_message=system_prompt))
                text = (resp.response or "").strip()
            if json_response:
                return json.loads(text)
            return text
        except Exception as e:
            print(f"Exception: {e}")
            return None

    def _setup_rag(self, openai_key=None):
        if not openai_key:
            self.logger.warning("RAG is enabled, but OPENAI_API_KEY is unavailable")
            return

        redis_conf = RedisDatastoreConf(
            host="127.0.0.1",
            port=6379,
            password=environ.get("DB_PASS", "changemeplease"),
            namespace="nardial_rag",
            version="v1",
            developer_id=0,
        )
        self.datastore = RedisDatastore(conf=redis_conf)

        if self.interaction_conf.ingest_docs:
            self._ingest_rag_documents(openai_key=openai_key)

    def _ingest_rag_documents(self, openai_key):
        result = self.datastore.request(
            IngestVectorDocsRequest(
                input_path=self.interaction_conf.input_path,
                openai_api_key=openai_key,
                index_name=self.interaction_conf.index_name,
                partition="default",
                chunk_chars=self.interaction_conf.chunk_chars,
                chunk_overlap=self.interaction_conf.chunk_overlap,
                embedding_model=self.interaction_conf.embedding_model,
                override_existing=self.interaction_conf.override_existing,
                force_recreate_index=self.interaction_conf.force_recreate_index,
            )
        )
        if isinstance(result, VectorDBResultsMessage) and result.payload.get("ok"):
            for item in result.payload.get("results", []):
                self.logger.info(
                    "RAG ingested %s files into %s (%s chunks)",
                    item.get("files", 0),
                    item.get("index", self.interaction_conf.index_name),
                    item.get("chunks", 0),
                )
            return
        self.logger.warning("RAG ingestion returned an unexpected response: %s", result)

    def _retrieve_rag_context(self, query_text, k=5, index_name=None, raise_on_error=False):
        if not self.datastore:
            if raise_on_error:
                raise RuntimeError("RAG datastore is not initialized")
            return ""

        openai_key = environ.get("OPENAI_API_KEY")
        if not openai_key:
            if raise_on_error:
                raise RuntimeError("Cannot retrieve RAG context without OPENAI_API_KEY")
            self.logger.warning("Cannot retrieve RAG context without OPENAI_API_KEY")
            return ""

        query_index_name = index_name or self.interaction_conf.index_name
        if not query_index_name:
            raise ValueError("RAG retrieval requires an index name")

        try:
            result = self.datastore.request(
                QueryVectorDBRequest(
                    index_name=query_index_name,
                    query_text=query_text,
                    openai_api_key=openai_key,
                    k=k,
                    partition="default",
                    embedding_model=self.interaction_conf.embedding_model,
                )
            )
        except Exception as e:
            if raise_on_error:
                raise
            self.logger.warning("RAG retrieval failed: %s", e)
            return ""

        if not isinstance(result, VectorDBResultsMessage):
            return ""

        snippets = []
        for idx, item in enumerate(result.payload.get("results", []), start=1):
            content = (item.get("content") or "").strip()
            if not content:
                continue
            source = Path(item.get("doc_path") or "unknown").name
            snippets.append(f"[{idx}] {source}\n{content}")
        return "\n\n".join(snippets)

    def animate_alphamini(self, animation_type: AnimationType, animation_id: str, run_async=False):
        if not isinstance(self.device_manager, Alphamini):
            print(f'Animation played: {animation_type} [{animation_id}]')
            return

        try:
            future = asyncio.run_coroutine_threadsafe(self.alphamini_animation_action(animation_id, animation_type), self.background_loop)
        except Exception as e:
            self.logger.error(f'Animation {animation_id} failed: {e}', exc_info=e)
            return

        self.animation_futures.append(future)
        if not run_async:
            future.result()

    def animate_naoqi(self, animation: str, block=True):
        try:
            self.device_manager.motion.request(NaoqiAnimationRequest(animation), block=block)
        except Exception as e:
            self.logger.error(f"Failed to play pepper animation: {animation}", exc_info=e)

    def animate_naoqi_leds(self, r=0, g=0, b=0, name="FaceLeds"):
        if isinstance(self.device_manager, Pepper):
            self.device_manager.leds.request(NaoFadeRGBRequest(name, r, g, b, 0))

    async def alphamini_animation_action(self, action_name, animation_type):
        try:
            if animation_type == AnimationType.ACTION:
                action: PlayAction = PlayAction(action_name=action_name)
                await action.execute()
            elif animation_type == AnimationType.EXPRESSION:
                action: PlayExpression = PlayExpression(express_name=action_name)
                await action.execute()
        except Exception as e:
            self.logger.error(f'Animation action {action_name} failed {e}', exc_info=e)
            self.logger.info('Reconnecting to Mini')
            connect_to_mini_sdk_future = asyncio.run_coroutine_threadsafe(self._connect_once(), self.background_loop)
            try:
                connect_to_mini_sdk_future.result()
            except Exception as e:
                self.logger.error("Failed to connect to mini device", exc_info=e)

    def set_alphamini_mouth_lamp(self, color: MouthLampColor, mode: MouthLampMode, duration=-1, breath_duration=1000, run_async=False):
        if not isinstance(self.device_manager, Alphamini):
            print(f"Set mouth lamp: {color} {mode} {duration} {breath_duration}")
            return

        future = asyncio.run_coroutine_threadsafe(
            self.alphamini_mouth_lamp_expression(color, mode, duration, breath_duration),
            self.background_loop)
        self.animation_futures.append(future)

        if not run_async:
            future.result()

    @staticmethod
    async def alphamini_mouth_lamp_expression(color: MouthLampColor, mode: MouthLampMode, duration=-1, breath_duration=1000):
        if mode == MouthLampMode.BREATH:
            mouth_lamp_action: SetMouthLamp = SetMouthLamp(color=color, mode=MouthLampMode.BREATH,
                                                           breath_duration=breath_duration)
        else:
            mouth_lamp_action: SetMouthLamp = SetMouthLamp(color=color, mode=MouthLampMode.NORMAL, duration=duration)
        await mouth_lamp_action.execute()

    def disconnect(self):
        if isinstance(self.tts_conf, ElevenLabsTTSConf):
            disconnect_elevenlabs_future = asyncio.run_coroutine_threadsafe(self.tts.disconnect(), self.background_loop)
            disconnect_elevenlabs_future.result()

        if self.device_name == 'alphamini':
            for fut in self.animation_futures:
                fut.cancel()

            # Disconnect from miniSDK
            disconnect_alphamini_future = asyncio.run_coroutine_threadsafe(self._disconnect_alphamini_api(),
                                                                           self.background_loop)
            disconnect_alphamini_future.result()

        # Schedule loop shutdown
        if self.background_loop.is_running():
            self.background_loop.call_soon_threadsafe(self.background_loop.stop)
        # Wait for the thread to finish
        self.background_thread.join()

    def _on_dialog(self, message):
        if message.response:
            transcript = message.response.recognition_result.transcript
            print("Transcript:", transcript)
            if message.response.recognition_result.is_final:
                self.log_utterance(speaker='child', text=transcript)

    def _start_loop(self):
        asyncio.set_event_loop(self.background_loop)
        self.background_loop.run_forever()

    async def _connect_once(self):
        if not self.mini_api:
            self.mini_api = await MiniSdk.get_device_by_name(self.mini_id, 10)
            await MiniSdk.connect(self.mini_api)

    @staticmethod
    async def _disconnect_alphamini_api():
        await MiniSdk.release()

    def set_interaction_conf(self, interaction_conf: InteractionConfig):
        self.interaction_conf = interaction_conf

    def signal_listening_behavior(self, start=True):
        if start:
            if isinstance(self.device_manager, Alphamini):
                self.set_alphamini_mouth_lamp(MouthLampColor.GREEN, MouthLampMode.NORMAL)
            elif isinstance(self.device_manager, Nao) or isinstance(self.device_manager, Pepper):
                self.animate_naoqi_leds(g=1)
        else:
            if isinstance(self.device_manager, Alphamini):
                self.set_alphamini_mouth_lamp(MouthLampColor.WHITE, MouthLampMode.BREATH)
            elif isinstance(self.device_manager, Nao) or isinstance(self.device_manager, Pepper):
                self.animate_naoqi_leds()

    def animation(self):
        if isinstance(self.device_manager, Alphamini):
            self.animate_alphamini(AnimationType.EXPRESSION, self.random_alphamini_speaking_eye_expression(), run_async=True)
            self.animate_alphamini(AnimationType.ACTION, self.random_alphamini_speaking_act(), run_async=True)
        elif isinstance(self.device_manager, Pepper) or isinstance(self.device_manager, Nao):
            self.device_manager.motion.request(NaoqiAnimationRequest(self.random_pepper_animation()), block=False)

    def play_motion(self, motion_name):
        if not isinstance(self.device_manager, Pepper) and not isinstance(self.device_manager, Nao):
            return
        try:
            # Play the recording
            self.logger.info(f"Playing motion {motion_name}")
            recording = NaoqiMotionRecording.load(motion_name)
            self.device_manager.motion_record.request(PlayRecording(recording))
        except Exception as e:
            self.logger.error(f"Exception: {e}")

    @staticmethod
    def random_alphamini_speaking_act():
        speaking_acts = [
            "speakingAct1",
            "speakingAct2",
            "speakingAct3",
            "speakingAct4",
            "speakingAct5",
            "speakingAct6",
            "speakingAct7",
            "speakingAct8",
            "speakingAct9",
            "speakingAct10",
            "speakingAct11",
            "speakingAct12",
            "speakingAct13",
            "speakingAct14",
            "speakingAct15",
            "speakingAct16",
            "speakingAct17"
        ]
        return rand.choice(speaking_acts)

    @staticmethod
    def random_alphamini_speaking_eye_expression():
        speaking_expressions = [
            "codemao1", "codemao2", "codemao3", "codemao4", "codemao5",
            "codemao6", "codemao7", "codemao8", "codemao9", "codemao10",
            "codemao11", "codemao12", "codemao13", "codemao14", "codemao15",
            "codemao16", "codemao17", "codemao18", "codemao19", "codemao20"]
        return rand.choice(speaking_expressions)

    def random_pepper_animation(self):
        if self.interaction_conf.animation_style == AnimationStyle.EXPRESSIVE:
            animations = [
                "animations/Stand/Emotions/Positive/Happy_4",
                "animations/Stand/Emotions/Positive/Peaceful_1",
                "animations/Stand/Gestures/But_1",
                "animations/Stand/Gestures/CalmDown_6",
                "animations/Stand/Gestures/Enthusiastic_4",
                "animations/Stand/Gestures/Everything_3",
                "animations/Stand/Gestures/Everything_4",
                "animations/Stand/Gestures/Explain_1",
                "animations/Stand/Gestures/Explain_10",
                "animations/Stand/Gestures/Explain_11",
                "animations/Stand/Gestures/Far_1",
                "animations/Stand/Gestures/Far_2",
                "animations/Stand/Gestures/Far_3",
                "animations/Stand/Gestures/ShowSky_1",
                "animations/Stand/Gestures/ShowSky_5",
                "animations/Stand/Gestures/ShowSky_7",
                "animations/Stand/Gestures/ShowSky_8",
                "animations/Stand/Gestures/IDontKnow_1",
                "animations/Stand/Gestures/IDontKnow_2",
                "animations/Stand/Gestures/No_1",
                "animations/Stand/Gestures/No_2",
                "animations/Stand/Gestures/No_9",
                "animations/Stand/Gestures/Yes_1",
                "animations/Stand/Gestures/Yes_2",
            ]
        else:
            animations = [
                "animations/Stand/Gestures/Everything_2",
                "animations/Stand/Gestures/Explain_1",
                "animations/Stand/Gestures/Explain_10",
                "animations/Stand/Gestures/Explain_2",
                "animations/Stand/Gestures/Explain_4",
                "animations/Stand/Gestures/Explain_5",
                "animations/Stand/Gestures/Give_3",
                "animations/Stand/Gestures/Give_5",
                "animations/Stand/Gestures/IDontKnow_1",
                "animations/Stand/Gestures/IDontKnow_2",
                "animations/Stand/Gestures/Me_1",
                "animations/Stand/Gestures/Me_4",
                "animations/Stand/Gestures/No_1",
                "animations/Stand/Gestures/No_2",
                "animations/Stand/Gestures/No_9",
                "animations/Stand/Gestures/ShowFloor_3",
                "animations/Stand/Gestures/ShowFloor_4",
                "animations/Stand/Gestures/ShowSky_6",
                "animations/Stand/Gestures/Thinking_1",
                "animations/Stand/Gestures/Thinking_3",
                "animations/Stand/Gestures/Thinking_6",
                "animations/Stand/Gestures/Yes_1",
                "animations/Stand/Gestures/Yes_2",
                "animations/Stand/Gestures/YouKnowWhat_2",
                "animations/Stand/Gestures/You_1"
            ]
        return rand.choice(animations)

    @staticmethod
    def _amplify_audio(waveform_bytes, compression_strength=2.0, target_level=0.9):
        """
        Amplify audio by normalizing and applying dynamic range compression.

        :param waveform_bytes: Raw PCM audio data as bytes (int16)
        :param compression_strength: Compression strength (1.0=minimal, 2.0=moderate, 5.0=heavy)
        :param target_level: Final output level (0.0-1.0, recommend 0.9 to avoid clipping)
        :return: Processed audio as bytes (int16)
        """
        # Convert bytes to numpy array
        audio_data = np.frombuffer(waveform_bytes, dtype=np.int16)
        audio_float = audio_data.astype(np.float32) / 32767.0

        # Step 1: Initial normalization to [-1, 1] range
        max_val = np.max(np.abs(audio_float))
        if max_val > 0:
            audio_normalized = audio_float / max_val
        else:
            audio_normalized = audio_float

        # Step 2: Apply logarithmic compression to boost quiet parts
        sign = np.sign(audio_normalized)
        magnitude = np.abs(audio_normalized)
        compressed_magnitude = np.log1p(magnitude * compression_strength) / np.log1p(compression_strength)
        compressed_audio = sign * compressed_magnitude

        # Step 3: Final normalization and scaling to target level
        final_max = np.max(np.abs(compressed_audio))
        if final_max > 0:
            compressed_audio = compressed_audio / final_max * target_level

        # Convert back to int16 bytes
        audio_int16 = (compressed_audio * 32767).astype(np.int16)
        return audio_int16.tobytes()

    @staticmethod
    def _split_text(text: str, max_len: int = 80, min_tail: int = 20):
        """
            Split text into natural chunks of ~max_len characters.
            - First, split by sentence boundaries (.?!)
            - Then, split long sentences further at commas or spaces
              while avoiding tiny fragments at the end.
            """
        text = text.strip()

        if len(text) <= max_len:
            return [text]

        chunks = []

        # Step 1: split at sentence boundaries, including no-space cases
        sentences = re.split(r'(?<=[,.?!])(?=\s|[A-Z])', text)

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            while len(sentence) > max_len:
                # Try to find a good split point
                chunk = sentence[:max_len]

                # Prefer splitting at last comma or space in chunk
                break_pos = max(chunk.rfind(','), chunk.rfind(' '))

                if break_pos == -1 or break_pos < max_len // 3:
                    # fallback: just split at max_len
                    break_pos = max_len

                # Avoid leaving tiny tail
                if len(sentence) - break_pos < min_tail:
                    break_pos = len(sentence)

                chunks.append(sentence[:break_pos].strip())
                sentence = sentence[break_pos:].strip()

            if sentence:
                chunks.append(sentence)

        return chunks
