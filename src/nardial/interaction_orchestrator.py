import asyncio
import base64
import importlib.util
import json
from json import load
import re
import wave
from enum import Enum
from os import environ, fsync
from os.path import exists, abspath, join
from pathlib import Path
import random as rand
from threading import Thread
import time
from time import sleep, strftime
from typing import Any, Optional

import numpy as np

import mini.mini_sdk as MiniSdk
from sic_framework.devices.alphamini import Alphamini

from mini import MouthLampColor, MouthLampMode
from mini.apis.api_action import PlayAction
from mini.apis.api_expression import SetMouthLamp, PlayExpression

from sic_framework.core import sic_logging
from sic_framework.core.message_python2 import AudioRequest
from sic_framework.core.sic_application import SICApplication
from sic_framework.devices import Pepper, Nao
from sic_framework.devices.common_naoqi.naoqi_leds import NaoFadeRGBRequest
from sic_framework.devices.common_naoqi.naoqi_motion import NaoqiAnimationRequest
from sic_framework.devices.common_naoqi.naoqi_motion_recorder import NaoqiMotionRecording, PlayRecording
from sic_framework.devices.common_naoqi.naoqi_text_to_speech import NaoqiTextToSpeechRequest
from sic_framework.devices.desktop import Desktop
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
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from pydantic import SecretStr

from nardial.tts_manager import NaoqiTTSConf, TTSConf, GoogleTTSConf, ElevenLabsTTSConf, ElevenLabsTTS, TTSCacher
from elevenlabs import ElevenLabs

"""
Demo: AlphaMini recognizes user intent and replies using Dialogflow/Text-to-Speech and an LLM.

IMPORTANT
First, you need to set-up Google Cloud Console with dialogflow and Google TTS:

1. Dialogflow: https://socialrobotics.atlassian.net/wiki/spaces/CBSR/pages/2205155343/Getting+a+google+dialogflow+key 
2. TTS: https://console.cloud.google.com/apis/api/texttospeech.googleapis.com/ 
2a. note: you need to set-up a paid account with a credit card. You get $300,- free tokens, which is more then enough
for testing this agent. So in practice it will not cost anything.
3. Create a keyfile as instructed in (1) and save it conf/dialogflow/google-key.json
3a. note: never share the keyfile online. 

Secondly you need to configure your dialogflow agent.
4. In your empty dialogflow agent do the following things:
4a. remove all default intents
4b. go to settings -> import and export -> and import the resources/droomrobot_dialogflow_agent.zip into your
dialogflow agent. That gives all the necessary intents and entities that are part of this example (and many more)

Thirdly, you need an openAI key:
5. Generate your personal openai api key here: https://platform.openai.com/api-keys
6. Either add your openai key to your systems variables or
create a .openai_env file in the conf/openai folder and add your key there like this:
OPENAI_API_KEY="your key"

Forth, the redis server, Dialogflow, Google TTS and OpenAI gpt service need to be running:

7. pip install --upgrade social_interaction_cloud[dialogflow,google-tts,openai-gpt,alphamini]
8. run: conf/redis/redis-server.exe conf/redis/redis.conf
9. run in new terminal: run-dialogflow 
10. run in new terminal: run-google-tts
11. run in new terminal: run-gpt
12. add in the main: the ip address, id, and password of the alphamini and the ip-address of the redis server (= ip address of you laptop)
13. Run this script
"""


class AnimationType(Enum):
    ACTION = 1
    EXPRESSION = 2


class AnimationStyle(Enum):
    EXPRESSIVE = 1
    EXPLANATORY = 2


class InteractionConfig:

    def __init__(self, language="en", tts_conf: TTSConf = None, microphone_device=None, google_keyfile_path=None,
                 openai_key_path=None, signal_listening_behavior=True, keyboard_input: bool = False,
                 use_langgraph: bool = False, rag: bool = False, ingest_docs: bool = False,
                 input_path: str = "", index_name: str = "", embedding_model: str = "",
                 chunk_chars: int = 1200, chunk_overlap: int = 150,
                 override_existing: bool = False, force_recreate_index: bool = False,
                 device_mcp: Any = None):
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
        self.signal_listening_behavior = signal_listening_behavior  # if True, the robot will show a visual behavior when it is listening for user input
        self.keyboard_input = keyboard_input
        self.use_langgraph = use_langgraph
        self.rag = rag
        self.ingest_docs = ingest_docs
        self.input_path = input_path
        self.index_name = index_name
        self.embedding_model = embedding_model
        self.chunk_chars = chunk_chars
        self.chunk_overlap = chunk_overlap
        self.override_existing = override_existing
        self.force_recreate_index = force_recreate_index
        self.device_mcp = device_mcp
        self.animated = True
        self.animation_style = AnimationStyle.EXPLANATORY
        self.always_regenerate = False  # if True, the TTS audio will always be regenerated instead of loading from cache
        self.chunk_audio = True
        self._validate_rag_config()

        self.dialogflow_conf = self.dialogflow_conf = DialogflowConf(
            keyfile_json=json.load(open(google_keyfile_path)),
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
        def decorator(func):
            def wrapper(self, *args, **kwargs):
                config = getattr(self, config_attr)
                for name in param_names:
                    if kwargs.get(name) is None:
                        kwargs[name] = getattr(config, name)
                return func(self, *args, **kwargs)

            return wrapper

        return decorator


class InteractionOrchestrator(SICApplication):
    def __init__(self, device_mcp: Any = None, int_config: InteractionConfig = None):
        super().__init__()
        if int_config is None:
            int_config = InteractionConfig()

        # Development Logging
        self.logger = self.get_app_logger()
        self.logger.info("\n SETTING UP BASIC PROCESSING")
        self.set_log_level(sic_logging.DEBUG)  # can be DEBUG, INFO, WARNING, ERROR, CRITICAL
        self.set_log_file_path("./logs")

        # Interaction configuration
        self.interaction_conf = int_config
        self.mcp_device = None
        self.dialogflow = None

        # Background loop
        self.background_loop = asyncio.new_event_loop()
        self.background_thread = Thread(target=self._start_loop, daemon=True)
        self.background_thread.start()
        self.logger.info('Complete')

        self.logger.info("\n SETTING UP OPENAI")
        self.gpt = None
        self.llm = None
        self.datastore = None
        self.rag_enabled = bool(self.interaction_conf.rag)
        if self.interaction_conf.openai_key_path:
            load_dotenv(self.interaction_conf.openai_key_path)
        openai_key = environ.get("OPENAI_API_KEY")
        if not openai_key:
            self.logger.warning("No OPENAI_API_KEY available; LLM calls will be disabled")
        elif self.interaction_conf.use_langgraph:
            self.llm = ChatOpenAI(
                api_key=SecretStr(openai_key),
                model=environ.get("NARDIAL_OPENAI_MODEL", "gpt-4o-mini"),
                temperature=0.7,
            )
        else:
            self.gpt = GPT(conf=GPTConf(openai_key=openai_key))

        if self.rag_enabled:
            self._setup_rag(openai_key=openai_key)
        self.logger.info('Complete')

        self.logger.info("\n SETTING UP TTS")
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
        self.logger.info("Complete")

        self.logger.info("\n SETTING UP MCP I/O")
        self.device_mcp = device_mcp
        self.mic = None
        self.speaker = None
        self.mini_api = None
        self.animation_futures = []
        self.setup_mcp_io()
        self.logger.info("Complete")

        if self.interaction_conf.keyboard_input:
            self.logger.info("\n SKIPPING DIALOGFLOW (keyboard_input=True)")
            self.dialogflow = None
            self.request_id = np.random.randint(10000)
            self.logger.info("Ready for interaction (keyboard input mode)!")
        else:
            self.logger.info("\n USING DIALOGFLOW COMPONENT")
            self.request_id = np.random.randint(10000)
            self.logger.info("Complete and ready for interaction!")

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
        self.logger.info('Google TTS activated')

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
            self.logger.info('Elevenlabs TTS activated')
        except Exception as e:
            self.logger.error("Failed to connect to elevenlabs", exc_info=e)

    def setup_mcp_io(self):
        device_mcp = self.device_mcp or self.interaction_conf.device_mcp
        if device_mcp is None:
            try:
                from sic_framework.mcp import mcp_desktop
                device_mcp = mcp_desktop
            except Exception:
                mcp_dir = Path(__file__).resolve().parents[3] / "social-interaction-cloud" / "sic_framework" / "mcp"
                desktop_path = mcp_dir / "mcp_desktop.py"
                desktop_spec = importlib.util.spec_from_file_location("mcp_desktop_local", str(desktop_path))
                if desktop_spec is None or desktop_spec.loader is None:
                    raise RuntimeError(f"Unable to load MCP desktop module from {desktop_path}")
                mcp_desktop = importlib.util.module_from_spec(desktop_spec)
                desktop_spec.loader.exec_module(mcp_desktop)
                device_mcp = mcp_desktop

        self.mcp_device = device_mcp

        device_connect_reply = self.mcp_device.connect()
        self.logger.info("MCP Device connect reply: %s", device_connect_reply)

        self.dialogflow = Dialogflow(
            ip="localhost",
            conf=self.interaction_conf.dialogflow_conf,
            input_source=getattr(device_mcp, "mic", None),
        )
        self.dialogflow.register_callback(self._on_dialog)

    @InteractionConfig.apply_config_defaults('interaction_conf', ['animated', 'always_regenerate', 'chunk_audio'])
    def say(self, text, sleep_time=None, animated=False, amplified=False, always_regenerate=False, chunk_audio=False):
        if animated:
            self.animation()

        if isinstance(self.tts_conf, NaoqiTTSConf):
            self.naoqi_say(text, sleep_time=sleep_time, animated=animated)
        elif isinstance(self.tts_conf, GoogleTTSConf):
            self.google_say(text, sleep_time=sleep_time, amplified=amplified, always_regenerate=always_regenerate)
        elif isinstance(self.tts_conf, ElevenLabsTTSConf):
            self.elevenlabs_say(text, sleep_time=sleep_time, amplified=amplified, always_regenerate=always_regenerate, chunking=chunk_audio)
        else:
            raise ValueError(f'Unsupported tts_conf type: {type(self.tts_conf)}')

    def naoqi_say(self, text, sleep_time=None, animated=False):
        # Device-specific NAO/Pepper path is intentionally removed from orchestrator I/O.
        self.logger.warning("naoqi_say is not supported in MCP-only orchestrator mode.")

    def google_say(self, text, sleep_time=None, amplified=False,  always_regenerate=False):
        # Generate cache key and load cached speech audio if available.
        tts_key = self.tts_cacher.make_tts_key(text, self.tts_conf)
        audio_file = self.tts_cacher.load_audio_file(tts_key)

        # If requested and available play cached speech audio
        if not always_regenerate and audio_file:
            self.logger.info("robot: %s (cache)", text)
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
            self.mcp_device.play_audio_bytes(
                waveform_b64=base64.b64encode(audio_bytes).decode("ascii"),
                sample_rate=sample_rate,
            )
            self.logger.info("robot: %s", text)

            # Save to cache file
            self.tts_cacher.save_audio_file(tts_key, audio_bytes, sample_rate)

        # Sleep if requested
        if sleep_time and sleep_time > 0:
            sleep(sleep_time)

    def elevenlabs_say(self, text, sleep_time=None, amplified=False, always_regenerate=False, chunking=True):
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
                    self.logger.info("robot: %s (cache)", chunk)
                    self.play_audio(audio_file, log=False)
                    continue

            # Generate new audio
            audio_bytes = self.elevenlabs_generate_chunk_audio(chunk, amplified)

            # Play audio
            self.mcp_device.play_audio_bytes(
                waveform_b64=base64.b64encode(audio_bytes).decode("ascii"),
                sample_rate=self.sample_rate,
            )
            self.logger.info("robot: %s", chunk)

            # Sleep if requested
            if sleep_time and sleep_time > 0:
                sleep(sleep_time)

    def elevenlabs_generate_chunk_audio(self, text, amplified=False):
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
        if self.interaction_conf.keyboard_input:
            # Keyboard mode bypasses Dialogflow/STT and mirrors existing return contract.
            try:
                if context and context.get('answer_yesno'):
                    raw = input("You (yes/no/dontknow): ").strip()
                    low = raw.lower()
                    if low in ("y", "yes", "yeah", "yep", "sure", "ok", "okay"):
                        return "yes", "yesno_yes"
                    if low in ("n", "no", "nope", "nah"):
                        return "no", "yesno_no"
                    if low in ("maybe", "unsure", "not sure", "idk", "dunno", "dontknow"):
                        return "dontknow", "yesno_dontknow"
                    if "yes" in low:
                        return "yes", "yesno_yes"
                    if "no" in low:
                        return "no", "yesno_no"
                    return raw or None, None

                raw = input("You: ").strip()
                return raw or None, None
            except EOFError:
                return None, None

        return self._listen_via_dialogflow(context=context, timeout=timeout)

    def _listen_via_dialogflow(self, context=None, timeout=10):
        if self.dialogflow is None:
            self.logger.warning("Dialogflow is not initialized")
            return None, None

        self.interaction_conf.dialogflow_conf.timeout = max(1.0, float(timeout))
        reply = self.dialogflow.request(GetIntentRequest(int(self.request_id), context or {}))
        if reply is None:
            return None, None

        transcript = None
        intent = getattr(reply, "intent", None)
        if getattr(reply, "response", None) and getattr(reply.response, "query_result", None):
            transcript = reply.response.query_result.query_text
        return transcript, intent

    def play_audio(self, audio_file, amplified=False, log=True):
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

            self.mcp_device.play_audio_bytes(
                waveform_b64=base64.b64encode(audio).decode("ascii"),
                sample_rate=framerate,
            )
            if log:
                self.logger.info("robot: plays %s", audio_file)

    def request_from_gpt(self, user_prompt=None, context_messages=None, system_prompt=None, json_response=False):
        if self.rag_enabled and user_prompt is not None and str(user_prompt).strip():
            rag_context = self._retrieve_rag_context(str(user_prompt).strip())
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

        if self.interaction_conf.use_langgraph:
            return self._request_from_langchain(user_prompt, context_messages, system_prompt, json_response)
        return self._request_from_sic(user_prompt, context_messages, system_prompt, json_response)

    def _setup_rag(self, openai_key: str | None):
        if not openai_key:
            self.logger.warning("RAG requested but OPENAI_API_KEY is missing; RAG will be disabled")
            self.rag_enabled = False
            return

        rag_conf = RedisDatastoreConf(
            host=environ.get("NARDIAL_REDIS_HOST", "127.0.0.1"),
            port=int(environ.get("NARDIAL_REDIS_PORT", "6379")),
            password=environ.get("NARDIAL_REDIS_PASSWORD", "changemeplease"),
            namespace=environ.get("NARDIAL_REDIS_NAMESPACE", "nardial_rag"),
            version=environ.get("NARDIAL_REDIS_VERSION", "v1"),
            developer_id=environ.get("NARDIAL_REDIS_DEVELOPER_ID", "0"),
        )
        try:
            self.datastore = RedisDatastore(conf=rag_conf)
        except Exception as e:
            self.logger.warning("Failed to initialize RedisDatastore for RAG: %s", e)
            self.rag_enabled = False
            return

        if self.interaction_conf.ingest_docs:
            self._ingest_rag_documents(openai_key=openai_key)

    def _ingest_rag_documents(self, openai_key: str):
        cfg = self.interaction_conf
        try:
            result = self.datastore.request(
                IngestVectorDocsRequest(
                    input_path=cfg.input_path,
                    openai_api_key=openai_key,
                    index_name=cfg.index_name,
                    chunk_chars=cfg.chunk_chars,
                    chunk_overlap=cfg.chunk_overlap,
                    embedding_model=cfg.embedding_model,
                    override_existing=cfg.override_existing,
                    force_recreate_index=cfg.force_recreate_index,
                )
            )
            if isinstance(result, VectorDBResultsMessage):
                payload = result.payload or {}
                if payload.get("ok"):
                    self.logger.info("RAG ingestion completed for index '%s'", cfg.index_name)
                else:
                    self.logger.warning("RAG ingestion reported non-ok result: %s", payload)
            else:
                self.logger.warning("Unexpected response type during RAG ingestion: %s", type(result))
        except Exception as e:
            self.logger.warning("RAG ingestion failed: %s", e)

    def _retrieve_rag_context(self, query_text: str, k: int = 3) -> str:
        if not self.datastore:
            return ""
        cfg = self.interaction_conf
        if not cfg.index_name:
            self.logger.warning("RAG is enabled but index_name is empty; skipping retrieval")
            return ""

        openai_key = environ.get("OPENAI_API_KEY")
        if not openai_key:
            return ""

        try:
            result = self.datastore.request(
                QueryVectorDBRequest(
                    index_name=cfg.index_name,
                    query_text=query_text,
                    openai_api_key=openai_key,
                    k=k,
                    embedding_model=cfg.embedding_model,
                )
            )
            if not isinstance(result, VectorDBResultsMessage):
                return ""

            payload = result.payload or {}
            docs = payload.get("results", []) or []
            if not docs:
                return ""

            snippets = []
            for idx, item in enumerate(docs, start=1):
                content = str(item.get("content", "")).strip()
                if not content:
                    continue
                score = item.get("score")
                doc_path = str(item.get("doc_path", "unknown"))
                snippets.append(
                    f"[Doc {idx} | score={score} | source={doc_path}]\n{content}"
                )
            return "\n\n".join(snippets)
        except Exception as e:
            self.logger.warning("RAG retrieval failed: %s", e)
            return ""

    def _request_from_sic(self, user_prompt=None, context_messages=None, system_prompt=None, json_response=False):
        if self.gpt is None:
            self.logger.warning("LLM call requested but SIC GPT is not initialized")
            return None
        try:
            resp = self.gpt.request(
                GPTRequest(
                    prompt=user_prompt if user_prompt is not None else "",
                    context_messages=context_messages,
                    system_message=system_prompt,
                )
            )
            text = (resp.response or "").strip()
            if json_response:
                return json.loads(text)
            return text
        except Exception as e:
            self.logger.info(f"Exception: {e}")
            return None

    def _request_from_langchain(self, user_prompt=None, context_messages=None, system_prompt=None, json_response=False):
        if self.llm is None:
            self.logger.warning("LLM call requested but ChatOpenAI is not initialized")
            return None
        try:
            messages = []
            if system_prompt:
                messages.append(SystemMessage(content=str(system_prompt)))
            for msg in (context_messages or []):
                if msg is None:
                    continue
                text = str(msg).strip()
                if text:
                    messages.append(AIMessage(content=text))
            if user_prompt is not None and str(user_prompt).strip():
                messages.append(HumanMessage(content=str(user_prompt).strip()))

            resp = self.llm.invoke(messages)
            usage = {}
            try:
                usage = dict((resp.response_metadata or {}).get("token_usage") or {})
            except Exception:
                usage = {}
            if usage:
                self.logger.info(
                    "LLM usage prompt=%s completion=%s total=%s",
                    usage.get("prompt_tokens"),
                    usage.get("completion_tokens"),
                    usage.get("total_tokens"),
                )
            text = (resp.content or "").strip()
            if json_response:
                return json.loads(text)
            return text
        except Exception as e:
            self.logger.info(f"Exception: {e}")
            return None

    def animate_alphamini(self, animation_type: AnimationType, animation_id: str, run_async=False):
        self.logger.info(
            "Animation request ignored in MCP-only orchestrator mode: %s [%s]",
            animation_type,
            animation_id,
        )

    def animate_naoqi(self, animation: str, block=True):
        self.logger.info("Animation request ignored in MCP-only orchestrator mode: %s", animation)

    def animate_naoqi_leds(self, r=0, g=0, b=0, name="FaceLeds"):
        self.logger.info(
            "LED request ignored in MCP-only orchestrator mode: %s rgb=(%s,%s,%s)",
            name,
            r,
            g,
            b,
        )

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
        self.logger.info(
            "Mouth lamp request ignored in MCP-only orchestrator mode: %s %s",
            color,
            mode,
        )

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
            self.logger.info("Transcript:", transcript)
            if message.response.recognition_result.is_final:
                self.logger.info("child: %s", transcript)

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
        # Device-specific listening signals are intentionally outside MCP-only orchestrator.
        return

    def animation(self):
        return

    def play_motion(self, motion_name):
        self.logger.info("Motion request ignored in MCP-only orchestrator mode: %s", motion_name)

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
