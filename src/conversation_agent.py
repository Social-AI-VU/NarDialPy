import re
import asyncio
import json
import wave
from os import environ
import numpy as np
from threading import Thread
from dotenv import load_dotenv

import mini.mini_sdk as MiniSdk
from sic_framework.core.message_python2 import AudioRequest
from sic_framework.devices import Nao, Pepper
from sic_framework.devices.alphamini import Alphamini
from sic_framework.devices.common_naoqi.naoqi_motion import NaoqiAnimationRequest
from sic_framework.devices.common_naoqi.naoqi_motion_recorder import NaoqiMotionRecording, PlayRecording
from sic_framework.devices.device import SICDeviceManager
from sic_framework.services.google_tts.google_tts import Text2Speech, Text2SpeechConf, GetSpeechRequest, SpeechResult
from sic_framework.devices.common_desktop.desktop_speakers import SpeakersConf
from sic_framework.services.llm.openai_gpt import GPT
from sic_framework.services.llm import GPTConf, GPTRequest
from src.configs import DialogFlowConfig, GoogleTTSConfig, OpenAIConfig

from sic_framework.devices.desktop import Desktop
from sic_framework.services.dialogflow.dialogflow import (
    Dialogflow,
    DialogflowConf,
    GetIntentRequest,
)


class ConversationAgent:
    def __init__(self, device_manager: SICDeviceManager, dialogflow_config: DialogFlowConfig, google_tts_config: GoogleTTSConfig, openai_config: OpenAIConfig):
        self.tts = None
        self.gpt = None
        self.mic = None
        self.device = None
        self.speaker = None
        self.mini_api = None
        self.request_id = None
        self.dialogflow = None
        self.tts_sample_rate = None

        # Background thread and event loop for miniSDK connection (to avoid blocking main thread)
        self.background_loop = asyncio.new_event_loop()
        self.background_thread = Thread(target=self._start_loop, daemon=True)
        self.background_thread.start()

        self.setup_device_manager(device_manager)
        self.setup_gpt_client(openai_config)
        self.setup_google_tts_client(google_tts_config)
        self.setup_dialogflow_client(dialogflow_config)

    def setup_device_manager(self, device_manager):
        if isinstance(device_manager, Pepper) or isinstance(device_manager, Nao):
            self.device = device_manager
            self.speaker = device_manager.speaker
        elif isinstance(device_manager, Desktop):
            self.device = Desktop(speakers_conf=SpeakersConf(sample_rate=self.tts_sample_rate))
            self.speaker = self.device.speakers
        elif isinstance(device_manager, Alphamini):
            self.device = device_manager
            self.speaker = self.device.speaker
            self.connect_to_mini_sdk()
        else:
            raise ValueError(f"DeviceManager {device_manager} is currently not supported")
        self.mic = self.device.mic
        print("Device connected")

    def setup_gpt_client(self, openai_config):
        if openai_config.openai_key_path:
            load_dotenv(openai_config.openai_key_path)
        conf = GPTConf(openai_key=environ["OPENAI_API_KEY"])
        self.gpt = GPT(conf=conf)
        print("OpenAI GPT4 Ready")

    def setup_google_tts_client(self, google_tts_config):
        self.tts = Text2Speech(conf=Text2SpeechConf(
            keyfile_json=json.load(open(google_tts_config.google_keyfile_path)),
            speaking_rate=google_tts_config.default_speaking_rate)
        )
        init_reply = self.tts.request(GetSpeechRequest(
            text="I am initializing",
            voice_name=google_tts_config.google_tts_voice_name,
            ssml_gender=google_tts_config.google_tts_voice_gender)
        )
        self.tts_sample_rate = init_reply.sample_rate
        print("Google TTS ready")

    def setup_dialogflow_client(self, dialogflow_config):
        dialogflow_conf = DialogflowConf(keyfile_json=json.load(open(dialogflow_config.google_keyfile_path)),
                                         sample_rate_hertz=dialogflow_config.sample_rate_dialogflow_hertz, language=dialogflow_config.dialogflow_language)
        self.dialogflow = Dialogflow(ip="localhost", conf=dialogflow_conf, input_source=self.mic)
        # flag to signal when the app should listen (i.e. transmit to dialogflow)
        self.request_id = np.random.randint(10000)
        print("Dialogflow Ready")

    def connect_to_mini_sdk(self):
        # Create asyncio event loop to keep connection open to miniSDK.
        connect_to_mini_sdk_future = asyncio.run_coroutine_threadsafe(self._connect_once(), self.background_loop)
        try:
            connect_to_mini_sdk_future.result()
        except Exception as e:
            print(f"Failed to connect to miniSDK: {e}")

    def _start_loop(self):
        asyncio.set_event_loop(self.background_loop)
        self.background_loop.run_forever()

    async def _connect_once(self):
        if not self.mini_api:
            self.mini_api = await MiniSdk.get_device_by_name(self.device.mini_id, 10)
            await MiniSdk.connect(self.mini_api)

    def generate_new_diaologflow_request_id(self):
        """Generate a fresh Dialogflow request_id for a new session/run."""
        self.request_id = np.random.randint(1000000)
        try:
            print(f"[DEBUG] New session request_id={self.request_id}")
        except Exception:
            pass

    def say(self, text, speaking_rate=1.0):
        print('Saying', text)
        reply = self.tts.request(GetSpeechRequest(text=text,
                                                  voice_name=self.google_tts_voice_name,
                                                  ssml_gender=self.google_tts_voice_gender,
                                                  speaking_rate=speaking_rate))
        print(f'Speech generated with sample rate: {reply.sample_rate}')
        self.speaker.request(AudioRequest(reply.waveform, reply.sample_rate))
        print('Sent to device speaker')

    def play_audio(self, audio_file):
        with wave.open(audio_file, 'rb') as wf:
            # Get parameters
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()

            # Ensure format is 16-bit (2 bytes per sample)
            if sample_width != 2:
                raise ValueError("WAV file is not 16-bit audio. Sample width = {} bytes.".format(sample_width))

            audio = wf.readframes(n_frames)
            self.speaker.request(AudioRequest(audio, framerate))

    def play_motion_sequence(self, motion_sequence_file):
        if not (isinstance(self.device, Nao) or isinstance(self.device, Pepper)):
            return
        try:
            recording = NaoqiMotionRecording.load(motion_sequence_file)
            self.device.motion_record.request(PlayRecording(recording))
        except Exception as e:
            print(f"Exception: {e}")

    def play_animation(self, animation_name):
        # TODO: support animations on Alphamini via miniSDK
        if not (isinstance(self.device, Nao) or isinstance(self.device, Pepper)):
            return
        try:
            self.device.motion.request(NaoqiAnimationRequest(animation_name), block=True)
        except Exception as e:
            print(f"Failed to play animation: {animation_name}", e)

    def ask_yesno(self, question, max_attempts=2):
        attempts = 0
        while attempts < max_attempts:
            # ask question
            tts_reply = self.tts.request(GetSpeechRequest(text=question,
                                                          voice_name=self.google_tts_voice_name,
                                                          ssml_gender=self.google_tts_voice_gender))
            self.speaker.request(AudioRequest(tts_reply.waveform, tts_reply.sample_rate))

            # listen for answer
            # TODO: Wrap this listening logic in reusable `listen()` function(s).
            reply = self.dialogflow.request(GetIntentRequest(self.request_id, {'answer_yesno': 1}))

            print("The detected intent:", reply.intent)

            # return answer
            if reply.intent:
                if "yesno_yes" in reply.intent:
                    return "yes"
                elif "yesno_no" in reply.intent:
                    return "no"
                elif "yesno_dontknow" in reply.intent:
                    return "dontknow"
            attempts += 1
        return None

    def ask_entity(self, question, context, target_intent, target_entity, max_attempts=2):
        attempts = 0

        while attempts < max_attempts:
            # ask question
            tts_reply = self.tts.request(GetSpeechRequest(text=question,
                                                          voice_name=self.google_tts_voice_name,
                                                          ssml_gender=self.google_tts_voice_gender))
            self.speaker.request(AudioRequest(tts_reply.waveform, tts_reply.sample_rate))

            # listen for answer
            # TODO: Wrap this listening logic in reusable `listen()` function(s).
            reply = self.dialogflow.request(GetIntentRequest(self.request_id, context))

            print("The detected intent:", reply.intent)

            # Return entity
            if reply.intent:
                if target_intent in reply.intent:
                    if reply.response.query_result.parameters and target_entity in reply.response.query_result.parameters:
                        return reply.response.query_result.parameters[target_entity]
            attempts += 1
        return None

    def ask_open(self, question, max_attempts=2):
        attempts = 0

        while attempts < max_attempts:
            # ask question
            tts_reply = self.tts.request(GetSpeechRequest(text=question,
                                                          voice_name=self.google_tts_voice_name,
                                                          ssml_gender=self.google_tts_voice_gender))
            self.speaker.request(AudioRequest(tts_reply.waveform, tts_reply.sample_rate))

            # listen for answer
            # TODO: Wrap this listening logic in reusable `listen()` function(s).
            reply = self.dialogflow.request(GetIntentRequest(self.request_id))

            print("The detected intent:", reply.intent)

            # Return entity
            if reply.response.query_result.query_text:
                return reply.response.query_result.query_text
            attempts += 1
        return None

    def ask_options(self, question, options, max_attempts=2):
        """
        Ask a multiple-choice question and return the chosen option as a string.
        Uses ask_open under the hood and matches the answer to one of the options.
        """
        attempts = 0
        options_lower = [opt.lower() for opt in options]
        while attempts < max_attempts:
            answer = self.ask_open(question)
            if answer:
                answer_lower = answer.lower()
                for opt in options_lower:
                    if opt in answer_lower:
                        return opt
            attempts += 1
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
            resp = self.gpt.request(GPTRequest(prompt))
            text = (resp.response or "").strip()
            data = json.loads(text)
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

    def personalize(self, robot_input: str, user_age: int | str, user_input: str, language: str = "en") -> str:
        """
        Generate a short, supportive, age-aware follow-up line based on the robot's last question and the user's reply.

        Inputs:
        - robot_input: what the robot just asked/said
        - user_age: age of the child (int or string)
        - user_input: user's reply as captured
        - language: only English ('en') is used; parameter kept for compatibility

        Returns one sentence (<= 25 words). Falls back to a simple template on failure.
        """
        try:
            age_txt = str(user_age).strip()
            # Always use English prompt for consistency
            system_preamble = (
                f"You are a social robot talking to a child aged {age_txt}. "
                "The child is in the hospital. Your goal is to be warm, positive, and brief. "
                "Use simple words, be encouraging, and you may ask one short follow-up question. "
                "Respond in exactly one sentence (max 25 words)."
            )
            prompt = (
                f"Context: {system_preamble}\n"
                f"Robot asked/said: {robot_input}\n"
                f"Child replied: \"{user_input}\"\n"
                "Now generate an appropriate one-sentence response."
            )

            resp = self.gpt.request(GPTRequest(prompt))
            text = (resp.response or "").strip()
            # Trim surrounding quotes/newlines if present
            text = re.sub(r'^[\s\"\']+|[\s\"\']+$', "", text)
            # Ensure it ends with a period/question mark for TTS prosody
            if text and text[-1] not in ".!?":
                text += "."
            # Keep it reasonably short
            words = text.split()
            if len(words) > 28:
                text = " ".join(words[:28]) + "…"
            return text or "Thanks for sharing. Would you like to tell me a bit more?"
        except Exception:
            return "Thanks for sharing. Would you like to tell me a bit more?"

    def ask_llm(self, user_prompt, context_messages, system_prompt):
        try:
            return self.gpt.request(GPTRequest(prompt=user_prompt, context_messages=context_messages, system_message=system_prompt))
        except Exception as e:
            print(f"Exception: {e}")
            return None

    def greet(self):
        self.say("Hello, I am your companion robot")
