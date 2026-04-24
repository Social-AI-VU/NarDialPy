"""Low-level interaction orchestrator for social robots.

This module provides:

* :class:`InteractionConfig` – runtime configuration (TTS backend, language,
  post-speech delay, animation flags, …).
* :class:`InteractionOrchestrator` – connects to the SIC device, sets up TTS,
  Dialogflow, and GPT, and exposes unified ``say``/``listen``/``animate``
  primitives used by :class:`~nardial.conversation_agent.ConversationAgent`.
"""

import asyncio
import json
from json import load
import queue
import re
import wave
from enum import Enum
from os import environ, fsync
from os.path import exists, abspath, join
from pathlib import Path
import random as rand
from threading import Thread
from time import sleep, strftime

import numpy as np
import mini.mini_sdk as MiniSdk

from mini import MouthLampColor, MouthLampMode
from mini.apis.api_action import PlayAction
from mini.apis.api_expression import SetMouthLamp, PlayExpression
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
from dotenv import load_dotenv

from nardial.tts_manager import NaoqiTTSConf, TTSConf, GoogleTTSConf, ElevenLabsTTSConf, ElevenLabsTTS, TTSCacher
from elevenlabs import ElevenLabs


class AnimationType(Enum):
    """Type of animation to request from the Alphamini robot SDK."""

    ACTION = 1
    EXPRESSION = 2


class AnimationStyle(Enum):
    """Speaking animation repertoire used when the robot talks.

    ``EXPRESSIVE`` enables a wider, more emotion-rich set of animations,
    while ``EXPLANATORY`` favours smaller, didactic gestures.
    """

    EXPRESSIVE = 1
    EXPLANATORY = 2


def find_project_root(start: Path) -> Path:
    """Walk up the directory tree from *start* until a ``conf/`` folder is found.

    Args:
        start: Directory from which to begin the search.

    Returns:
        The first ancestor directory (inclusive) that contains a ``conf``
        subdirectory.

    Raises:
        FileNotFoundError: If the ``conf`` directory cannot be located in any
            ancestor.
    """
    for path in [start] + list(start.parents):
        if (path / "conf").exists():
            return path
    raise FileNotFoundError("Could not find 'conf' directory")


class InteractionConfig:
    """Runtime configuration for :class:`InteractionOrchestrator`.

    Collects all knobs that control TTS backend, listening behaviour,
    post-speech delays, and animation style.  Default values are designed
    for English speech using Google TTS.

    Args:
        language: BCP-47 language tag used for TTS and Dialogflow
            (default ``"en"``).
        tts_conf: TTS backend configuration.  When ``None`` a
            :class:`~nardial.tts_manager.GoogleTTSConf` with a standard
            English voice is used.
        microphone_device: Optional separate SIC device to use as the
            microphone source.
        google_keyfile_path: Path to the Google service-account JSON key
            file.  Resolved automatically from the ``conf/google/`` folder
            when ``None``.
        openai_key_path: Path to a ``.env`` file that contains the
            ``OPENAI_API_KEY`` variable.  Resolved automatically from
            ``conf/openai/`` when ``None``.
        post_speech_delay: Seconds to pause after each utterance.
        signal_listening_behavior: When ``True``, the robot shows a visual
            cue (LED colour change) to indicate it is listening.
    """

    def __init__(self, language="en", tts_conf: TTSConf = None, microphone_device=None, google_keyfile_path=None,
                 openai_key_path=None, post_speech_delay=None, signal_listening_behavior=True):
        self.language = language

        self.tts_conf = tts_conf
        if not tts_conf:
            self.tts_conf = GoogleTTSConf(
                google_tts_voice_name="en-US-Standard-C",
                speaking_rate=1.0
            )

        self.microphone_device = microphone_device
        self.google_keyfile_path = google_keyfile_path
        self.openai_key_path = openai_key_path
        if not self.google_keyfile_path:
            self.google_keyfile_path = abspath(join(find_project_root(Path.cwd()), "conf", "google", "google_keyfile.json"))
        if not self.openai_key_path:
            self.openai_key_path = abspath(join(find_project_root(Path.cwd()), "conf", "openai", ".openai_env"))

        self.post_speech_delay = post_speech_delay
        self.signal_listening_behavior = signal_listening_behavior  # if True, the robot will show a visual behavior when it is listening for user input
        self.animated = True
        self.animation_style = AnimationStyle.EXPLANATORY
        self.always_regenerate = False  # if True, the TTS audio will always be regenerated instead of loading from cache
        self.chunk_audio = True

        self.dialogflow_conf = self.dialogflow_conf = DialogflowConf(
            keyfile_json=json.load(open(self.google_keyfile_path)),
            sample_rate_hertz=44100,
            language=language
        )

    @staticmethod
    def apply_config_defaults(config_attr, param_names):
        """Decorator that fills missing keyword arguments from an instance config object.

        When a decorated method is called without a keyword argument that
        appears in *param_names*, the value is pulled from the attribute
        ``getattr(self, config_attr)`` instead.

        Args:
            config_attr: Name of the instance attribute that holds the
                configuration object.
            param_names: List of parameter names to fill from the config.

        Returns:
            A decorator function.
        """
        def decorator(func):
            def wrapper(self, *args, **kwargs):
                config = getattr(self, config_attr)
                for name in param_names:
                    if kwargs.get(name) is None:
                        kwargs[name] = getattr(config, name)
                return func(self, *args, **kwargs)

            return wrapper

        return decorator


class InteractionOrchestrator:
    """Core engine that connects a SIC robot to TTS, ASR, and LLM services.

    On construction the orchestrator:

    1. Configures application-level logging.
    2. Connects to OpenAI GPT (if a key is available).
    3. Initialises the selected TTS backend (Google, ElevenLabs, or NaoQi).
    4. Sets up the robot-specific hardware (speaker, microphone, animations).
    5. Connects to Dialogflow for intent-based speech recognition.

    Args:
        device_manager: SIC device manager for the target robot.
        int_config: Interaction configuration instance that controls TTS
            backend, language, post-speech delay, and animation behaviour.
    """

    def __init__(self, device_manager: SICDeviceManager, int_config: InteractionConfig):

        print("\n SETTING UP BASIC PROCESSING")
        # Development Logging
        self.app = SICApplication()
        self.logger = self.app.get_app_logger()
        self.app.set_log_level(sic_logging.DEBUG)  # can be DEBUG, INFO, WARNING, ERROR, CRITICAL
        self.app.set_log_file_path("./logs")

        # Data logging
        self._log_queue = None
        self._log_thread = None

        # Interaction configuration
        self.interaction_conf = int_config

        # Background loop
        self.background_loop = asyncio.new_event_loop()
        self.background_thread = Thread(target=self._start_loop, daemon=True)
        self.background_thread.start()
        print('Complete')

        print("\n SETTING UP OPENAI")
        self.gpt = None
        if self.interaction_conf.openai_key_path:
            load_dotenv(self.interaction_conf.openai_key_path)
        try:
            self.gpt = GPT(conf=GPTConf(openai_key=environ["OPENAI_API_KEY"]))
        except KeyError:
            self.logger.warning("No openAI key available")
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
        self.dialogflow = Dialogflow(ip="localhost", conf=self.interaction_conf.dialogflow_conf, input_source=getattr(self, 'mic', None))
        # flag to signal when the app should listen (i.e. transmit to dialogflow)
        self.request_id = np.random.randint(10000)
        self.dialogflow.register_callback(self._on_dialog)
        print("Complete and ready for interaction!")

    def start_logging(self, log_id, init_data: dict):
        """Start an asynchronous log writer thread.

        Creates a ``logs/<log_id>.log`` file and begins writing log messages
        from an internal queue.

        Args:
            log_id: Base name (without extension) for the log file.
            init_data: Metadata dict whose key/value pairs are written as the
                first line of the log.
        """
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
        """Signal the log-writer thread to finish and wait for it to exit."""
        if self._log_queue:
            self._log_queue.put(None)
        if self._log_thread:
            self._log_thread.join()

    def log_writer(self, log_path):
        """Background thread target: drain the log queue and write to *log_path*.

        Runs until a ``None`` sentinel is received from the queue, then exits.

        Args:
            log_path: Path object pointing to the destination log file.
        """
        with open(log_path, 'a', encoding='utf-8') as f:
            while True:
                item = self._log_queue.get()
                if item is None:
                    break  # Exit signal
                f.write(item + '\n')
                f.flush()

    def log_utterance(self, speaker, text):
        """Append a timestamped utterance line to the log.

        Args:
            speaker: Label identifying who spoke (e.g. ``"robot"`` or
                ``"child"``).
            text: Transcription or TTS text to log.
        """
        if self._log_queue:
            timestamp = strftime("%Y-%m-%d %H:%M:%S")
            self._log_queue.put(f"[{timestamp}] {speaker}: {text}")

    def log_recognition_result(self, recognition_result):
        """Append a raw Dialogflow recognition result to the log.

        Args:
            recognition_result: The recognition result object or string
                returned by Dialogflow.
        """
        if self._log_queue:
            timestamp = strftime("%Y-%m-%d %H:%M:%S")
            self._log_queue.put(f"[{timestamp}] recognition result: {recognition_result}")

    def activate_google_tts(self):
        """Initialise the Google Cloud TTS service and verify connectivity.

        Sends a warm-up request to confirm the service is reachable and to
        determine the sample rate used by subsequent audio playback.

        Raises:
            ValueError: If no Google keyfile path has been configured.
        """
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
        """Initialise the ElevenLabs streaming TTS websocket.

        Connects to the ElevenLabs API, sends a warm-up phrase, and stores a
        synchronous ``ElevenLabs`` client for non-streaming calls.

        Raises:
            ValueError: If the ``ELEVENLABS_API_KEY`` environment variable is
                not set.
        """
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
        """Configure the Alphamini robot device, connect to the Mini SDK, and run wake-up animations."""
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
        """Configure the Pepper robot device."""
        self.speaker = self.device_manager.speaker
        print("\n Device is PEPPER")

    def setup_nao(self):
        """Configure the Nao robot device."""
        self.speaker = self.device_manager.speaker
        print("\n Device is NAO")

    def setup_desktop(self):
        """Configure a desktop computer as the audio output device."""
        print("\n Device is COMPUTER")
        self.speaker = self.device_manager.speakers

    @InteractionConfig.apply_config_defaults('interaction_conf', ['post_speech_delay', 'animated', 'always_regenerate', 'chunk_audio'])
    def say(self, text, post_speech_delay=None, animated=False, amplified=False, always_regenerate=False, chunk_audio=False):
        """Synthesise *text* with the configured TTS backend and play it.

        The appropriate backend (NaoQi, Google TTS, or ElevenLabs) is chosen
        automatically based on ``interaction_conf.tts_conf``.

        Args:
            text: Utterance to speak.
            post_speech_delay: Seconds to wait after speaking.  Defaults to
                the value in ``interaction_conf``.
            animated: If ``True``, trigger a speaking animation concurrently.
            amplified: If ``True``, apply dynamic-range compression before
                playback.
            always_regenerate: If ``True``, bypass the TTS cache and
                regenerate audio even if a cached file exists.
            chunk_audio: If ``True``, split long utterances into smaller
                chunks for more responsive playback (ElevenLabs only).
        """
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
        """Speak *text* using the NaoQi TTS service on Pepper or Nao.

        This method is a no-op on non-NaoQi devices.

        Args:
            text: Utterance text.
            post_speech_delay: Optional pause (seconds) after speaking.
            animated: If ``True``, request an animated TTS rendition.
        """
        if not isinstance(self.device_manager, Pepper) and not isinstance(self.device_manager, Nao):
            return

        self.device_manager.tts.request(NaoqiTextToSpeechRequest(text, animated=animated, language=self.interaction_conf.language))

        if post_speech_delay and post_speech_delay > 0:
            sleep(post_speech_delay)

    def google_say(self, text, post_speech_delay=None, amplified=False, always_regenerate=False):
        """Speak *text* using Google Cloud TTS, with optional caching.

        Args:
            text: Utterance text.
            post_speech_delay: Optional pause (seconds) after speaking.
            amplified: If ``True``, boost audio volume before playback.
            always_regenerate: If ``True``, skip the cache and request fresh
                audio from Google.
        """
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
        """Speak *text* using the ElevenLabs streaming TTS service.

        Args:
            text: Utterance text.
            post_speech_delay: Optional pause (seconds) after each chunk.
            amplified: If ``True``, boost audio volume before playback.
            always_regenerate: If ``True``, bypass the cache and regenerate all
                audio.
            chunking: If ``True``, split long text into shorter chunks for
                lower latency (disabled automatically for the ``eleven_v3``
                model).
        """
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

            # Play audio
            self.speaker.request(AudioRequest(audio_bytes, self.sample_rate))
            self.log_utterance(speaker='robot', text=f'{chunk}')

            # Sleep if requested
            if post_speech_delay and post_speech_delay > 0:
                sleep(post_speech_delay)

    def elevenlabs_generate_chunk_audio(self, text, amplified=False):
        """Generate and cache audio bytes for a single text chunk via ElevenLabs.

        Args:
            text: Text chunk to synthesise.
            amplified: If ``True``, apply dynamic-range compression to the
                returned audio.

        Returns:
            Raw PCM audio bytes (int16).
        """
        # Normalize and hash text
        tts_key = self.tts_cacher.make_tts_key(text, self.tts_conf)

        # ElevenLabs TTS returns bytes
        audio_bytes = asyncio.run_coroutine_threadsafe(self.tts.speak(text), self.background_loop).result()

        if audio_bytes and amplified:
            audio_bytes = self._amplify_audio(audio_bytes)

        # Save to cache file
        self.tts_cacher.save_audio_file(tts_key, audio_bytes, self.sample_rate)

        return audio_bytes

    def listen(self, context=None, timeout=10):
        """Listen for user speech and return the transcript and detected intent.

        Optionally signals listening behaviour (e.g. LED change) before and
        after the capture window.

        Args:
            context: Dialogflow context dict that biases intent recognition.
            timeout: Maximum seconds to wait for a response from Dialogflow.

        Returns:
            A tuple ``(transcript, intent)`` where *transcript* is the
            recognised text (or ``None``) and *intent* is the matched
            Dialogflow intent name (or ``None``).
        """
        if self.interaction_conf.signal_listening_behavior:
            self.signal_listening_behavior(start=True)
        try:
            reply = self.dialogflow.request(GetIntentRequest(self.request_id, context), timeout=timeout)
            print("The detected intent:", reply.intent)
            intent = reply.intent if reply.intent else None
            if reply.response.query_result.query_text:
                return reply.response.query_result.query_text, intent
            return None, intent
        except TimeoutError as e:
            print("Error:", e)
        if self.interaction_conf.signal_listening_behavior:
            self.signal_listening_behavior(start=False)
        return None, None

    def play_audio(self, audio_file, amplified=False, log=True):
        """Read and play a WAV audio file through the robot's speaker.

        Only 16-bit PCM WAV files are supported.

        Args:
            audio_file: Path to the ``.wav`` file to play.
            amplified: If ``True``, apply dynamic-range compression before
                playback.
            log: If ``True``, write a log entry noting which file was played.

        Raises:
            ValueError: If the WAV file is not in 16-bit format.
        """
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

    def request_from_gpt(self, user_prompt=None, context_messages=None, system_prompt=None, json_response=False):
        """Send a prompt to OpenAI GPT and return the response.

        Args:
            user_prompt: User-turn text to include in the request.
            context_messages: List of prior conversation messages for context.
            system_prompt: System-level instruction string.
            json_response: If ``True``, parse the response text as JSON and
                return the resulting Python object.

        Returns:
            The response text (or parsed JSON object when *json_response* is
            ``True``), or ``None`` if the request fails.
        """
        try:
            resp = self.gpt.request(GPTRequest(prompt=user_prompt, context_messages=context_messages, system_message=system_prompt))
            text = (resp.response or "").strip()
            if json_response:
                return json.loads(text)
            return text
        except Exception as e:
            print(f"Exception: {e}")
            return None

    def animate_alphamini(self, animation_type: AnimationType, animation_id: str, run_async=False):
        """Trigger an Alphamini animation action or expression.

        On non-Alphamini devices the call is printed to stdout and returns
        immediately (useful for development on desktop).

        Args:
            animation_type: Whether to run an :attr:`AnimationType.ACTION` or
                :attr:`AnimationType.EXPRESSION`.
            animation_id: ID string of the animation to play.
            run_async: If ``True``, schedule the animation without waiting for
                it to finish.
        """
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
        """Play a NaoQi animation on Pepper or Nao.

        Args:
            animation: NaoQi animation path string.
            block: If ``True``, wait for the animation to complete before
                returning.
        """
        try:
            self.device_manager.motion.request(NaoqiAnimationRequest(animation), block=block)
        except Exception as e:
            self.logger.error(f"Failed to play pepper animation: {animation}", exc_info=e)

    def animate_naoqi_leds(self, r=0, g=0, b=0, name="FaceLeds"):
        """Set a Pepper LED group to a specific RGB colour.

        This method is a no-op on non-Pepper devices.

        Args:
            r: Red channel intensity (0.0–1.0).
            g: Green channel intensity (0.0–1.0).
            b: Blue channel intensity (0.0–1.0).
            name: NaoQi LED group name (default ``"FaceLeds"``).
        """
        if isinstance(self.device_manager, Pepper):
            self.device_manager.leds.request(NaoFadeRGBRequest(name, r, g, b, 0))

    async def alphamini_animation_action(self, action_name, animation_type):
        """Coroutine that executes a single Alphamini action or expression.

        On failure the method logs the error and attempts to reconnect to the
        Mini SDK before returning.

        Args:
            action_name: Name of the action or expression to execute.
            animation_type: :attr:`AnimationType.ACTION` or
                :attr:`AnimationType.EXPRESSION`.
        """
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
        """Control the Alphamini mouth LED lamp.

        On non-Alphamini devices the parameters are printed to stdout.

        Args:
            color: Desired lamp colour (see :class:`mini.MouthLampColor`).
            mode: Lamp mode such as ``NORMAL`` or ``BREATH``.
            duration: Duration in milliseconds for ``NORMAL`` mode (``-1``
                means indefinite).
            breath_duration: Duration of one breath cycle in milliseconds.
            run_async: If ``True``, schedule without waiting for completion.
        """
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
        """Coroutine that executes a mouth-lamp command on the Alphamini.

        Args:
            color: Desired lamp colour.
            mode: Lamp mode (``NORMAL`` or ``BREATH``).
            duration: Duration in milliseconds (``NORMAL`` mode only).
            breath_duration: Duration of one breath cycle in milliseconds
                (``BREATH`` mode only).
        """
        if mode == MouthLampMode.BREATH:
            mouth_lamp_action: SetMouthLamp = SetMouthLamp(color=color, mode=MouthLampMode.BREATH,
                                                           breath_duration=breath_duration)
        else:
            mouth_lamp_action: SetMouthLamp = SetMouthLamp(color=color, mode=MouthLampMode.NORMAL, duration=duration)
        await mouth_lamp_action.execute()

    def disconnect(self):
        """Gracefully shut down all active connections and the background loop.

        Disconnects from ElevenLabs (if active), cancels pending Alphamini
        animation futures, releases the Mini SDK, and stops the asyncio event
        loop thread.
        """
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
        """Dialogflow callback that logs interim and final transcriptions.

        Args:
            message: Dialogflow recognition result message.
        """
        if message.response:
            transcript = message.response.recognition_result.transcript
            print("Transcript:", transcript)
            if message.response.recognition_result.is_final:
                self.log_utterance(speaker='child', text=transcript)

    def _start_loop(self):
        """Thread target: run the background asyncio event loop until stopped."""
        asyncio.set_event_loop(self.background_loop)
        self.background_loop.run_forever()

    async def _connect_once(self):
        """Coroutine that connects to the Alphamini device if not already connected."""
        if not self.mini_api:
            self.mini_api = await MiniSdk.get_device_by_name(self.mini_id, 10)
            await MiniSdk.connect(self.mini_api)

    @staticmethod
    async def _disconnect_alphamini_api():
        """Coroutine that releases the Alphamini Mini SDK connection."""
        await MiniSdk.release()

    def set_interaction_conf(self, interaction_conf: InteractionConfig):
        """Replace the current interaction configuration at runtime.

        Args:
            interaction_conf: New :class:`InteractionConfig` instance to use
                for subsequent interactions.
        """
        self.interaction_conf = interaction_conf

    def signal_listening_behavior(self, start=True):
        """Toggle the robot's visual listening indicator.

        On Alphamini, changes the mouth lamp colour; on Pepper/Nao, changes
        the face LED colour.

        Args:
            start: ``True`` to activate the "listening" indicator, ``False``
                to revert to the default idle indicator.
        """
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
        """Trigger a random speaking animation appropriate for the current device."""
        if isinstance(self.device_manager, Alphamini):
            self.animate_alphamini(AnimationType.EXPRESSION, self.random_alphamini_speaking_eye_expression(), run_async=True)
            self.animate_alphamini(AnimationType.ACTION, self.random_alphamini_speaking_act(), run_async=True)
        elif isinstance(self.device_manager, Pepper) or isinstance(self.device_manager, Nao):
            self.device_manager.motion.request(NaoqiAnimationRequest(self.random_pepper_animation()), block=False)

    def play_motion(self, motion_name):
        """Replay a recorded motion sequence on Pepper or Nao.

        This method is a no-op on non-NaoQi devices.

        Args:
            motion_name: Path to the NaoQi motion-sequence recording file.
        """
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
        """Return a randomly chosen Alphamini speaking-action animation ID.

        Returns:
            One of the ``speakingAct*`` animation IDs.
        """
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
        """Return a randomly chosen Alphamini speaking eye-expression ID.

        Returns:
            One of the ``codemao*`` expression IDs.
        """
        speaking_expressions = [
            "codemao1", "codemao2", "codemao3", "codemao4", "codemao5",
            "codemao6", "codemao7", "codemao8", "codemao9", "codemao10",
            "codemao11", "codemao12", "codemao13", "codemao14", "codemao15",
            "codemao16", "codemao17", "codemao18", "codemao19", "codemao20"]
        return rand.choice(speaking_expressions)

    def random_pepper_animation(self):
        """Return a randomly chosen Pepper animation path for the configured style.

        Returns:
            A NaoQi animation path string suitable for use with
            :meth:`animate_naoqi`.
        """
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
