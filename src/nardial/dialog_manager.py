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

from tts_manager import NaoqiTTSConf, TTSConf, GoogleTTSConf, ElevenLabsTTSConf, ElevenLabsTTS, TTSCacher
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
                 openai_key_path=None, animation_style=AnimationStyle.EXPLANATORY):
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
        self.animation_style = animation_style

        self.dialogflow_conf = self.dialogflow_conf = DialogflowConf(
            keyfile_json=json.load(open(google_keyfile_path)),
            sample_rate_hertz=44100,
            language=language
        )


class DialogManager:
    def __init__(self, device_manager: SICDeviceManager, int_config: InteractionConfig):

        print("\n SETTING UP BASIC PROCESSING")
        # Development Logging
        self.app = SICApplication()
        self.logger = self.app.get_app_logger()
        self.app.set_log_level(sic_logging.DEBUG)  # can be DEBUG, INFO, WARNING, ERROR, CRITICAL
        self.app.set_log_file("./logs")

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
        self.speaker = self.device_manager.speaker
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
            keyfile_json=self.interaction_conf.google_keyfile_path,
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
        # Create asyncio event loop to keep connection open to miniSDK.
        connect_to_mini_sdk_future = asyncio.run_coroutine_threadsafe(self._connect_once(), self.background_loop)
        try:
            connect_to_mini_sdk_future.result()
            self.animate_alphamini(AnimationType.ACTION, "009")  # Wake up
            self.animate_alphamini(AnimationType.EXPRESSION, "codemao20")  # Blink
        except Exception as e:
            self.logger.error("Failed to connect to mini device", exc_info=e)

    @staticmethod
    def setup_pepper():
        print("\n Device is PEPPER")

    @staticmethod
    def setup_nao():
        print("\n Device is NAO")

    def setup_desktop(self):
        print("\n Device is COMPUTER")
        self.speaker = self.device_manager.speakers

    def say(self, text, speaking_rate=None, sleep_time=None, animated=None, amplified=False, always_regenerate=False, chunking=True):
        if animated:
            self.animation()

        if isinstance(self.tts_conf, NaoqiTTSConf):
            self.naoqi_say(text, sleep_time=sleep_time, animated=animated)
        elif isinstance(self.tts_conf, GoogleTTSConf):
            self.google_say(text, speaking_rate=speaking_rate, sleep_time=sleep_time, amplified=amplified, always_regenerate=always_regenerate)
        elif isinstance(self.tts_conf, ElevenLabsTTSConf):
            self.elevenlabs_say(text, sleep_time=sleep_time, amplified=amplified, always_regenerate=always_regenerate, chunking=chunking)
        else:
            raise ValueError(f'Unsupported tts_conf type: {type(self.tts_conf)}')

    def naoqi_say(self, text, sleep_time=None, animated=False):
        if not isinstance(self.device_manager, Pepper) and not isinstance(self.device_manager, Nao):
            return

        self.device_manager.tts.request(NaoqiTextToSpeechRequest(text, animated=animated, language=self.interaction_conf.language))

        if sleep_time and sleep_time > 0:
            sleep(sleep_time)

    def google_say(self, text, speaking_rate=None, sleep_time=None, amplified=False,  always_regenerate=False):
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
                speaking_rate=speaking_rate or self.tts_conf.speaking_rate
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
                    self.log_utterance(speaker='robot', text=f'{chunk} (cache)')
                    self.play_audio(audio_file, log=False)
                    continue

            # Generate new audio
            audio_bytes = self.elevenlabs_generate_chunk_audio(chunk, amplified)

            # Play audio
            self.speaker.request(AudioRequest(audio_bytes, self.sample_rate))
            self.log_utterance(speaker='robot', text=f'{chunk}')

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

    def listen(self):
        try:
            reply = self.dialogflow.request(GetIntentRequest(self.request_id), timeout=10)
            if reply.response.query_result.query_text:
                return reply.response.query_result.query_text
            return None
        except TimeoutError as e:
            print("Error:", e)

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

            self.speaker.request(AudioRequest(audio, framerate))
            if log:
                self.log_utterance(speaker='robot', text=f'plays {audio_file}')

    def ask_yesno(self, question, max_attempts=None, speaking_rate=None, animated=None):
        attempts = 0
        while attempts < max_attempts:
            # ask question
            self.say(question, speaking_rate=speaking_rate, animated=animated)

            # listen for answer
            reply = self.dialogflow.request(GetIntentRequest(self.request_id, {'answer_yesno': 1}))
            print("The detected intent:", reply.intent)

            # return answer
            if reply.intent:
                print(f'context: answer_yesno, recognized_intent: {str(reply.intent)}')
                self.log_recognition_result(f'context: answer_yesno, recognized_intent: {str(reply.intent)}')
                if reply.intent == "yesno_yes":
                    return "yes"
                elif reply.intent == "yesno_no":
                    return "no"
                elif reply.intent == "yesno_dontknow":
                    return "dontknow"

            self.log_recognition_result(f'context: answer_yesno, recognized_intent: None')
            attempts += 1
        self.log_recognition_result(f'context: answer_yesno, intent recognition failed')
        return None

    def ask_entity(self, question, context, target_intent, target_entity, max_attempts=None, speaking_rate=None,
                   animated=None):
        attempts = 0

        while attempts < max_attempts:
            # ask question
            self.say(question, speaking_rate=speaking_rate, animated=animated)
            # self.set_mouth_lamp(MouthLampColor.GREEN, MouthLampMode.NORMAL)
            # listen for answer
            reply = self.dialogflow.request(GetIntentRequest(self.request_id, context))
            # self.set_mouth_lamp(MouthLampColor.WHITE, MouthLampMode.BREATH)
            print("The detected intent:", reply.intent)

            # Return entity
            if reply.intent:
                if target_intent in reply.intent:
                    if reply.response.query_result.parameters and target_entity in reply.response.query_result.parameters:
                        result_entity = reply.response.query_result.parameters[target_entity]
                        self.log_recognition_result(f'context: {context}, target_intent: {target_intent}, '
                                                    f'target_entity: {target_entity}, recognized_entity: {str(result_entity)}')
                        return result_entity
            attempts += 1
            self.log_recognition_result(f'context: {context}, target_intent: {target_intent}, '
                                        f'target_entity: {target_entity}, recognized_intent: None')

        self.log_recognition_result(f'context: {context}, intent recognition failed')
        return None

    def ask_open(self, question, max_attempts=None, speaking_rate=None, animated=None, listening_behavior=False):
        attempts = 0

        while attempts < max_attempts:
            # ask question
            self.say(question, speaking_rate=speaking_rate, animated=animated)

            # self.set_mouth_lamp(MouthLampColor.GREEN, MouthLampMode.NORMAL)
            # listen for answer
            if listening_behavior:
                # self.animate_naoqi_leds(g=1)
                self.listening_behavior()
            reply = self.dialogflow.request(GetIntentRequest(self.request_id))
            if listening_behavior:
                # self.animate_naoqi_leds()
                self.listening_behavior(start=False)
            # self.set_mouth_lamp(MouthLampColor.WHITE, MouthLampMode.BREATH)

            print("The detected intent:", reply.intent)

            # Return entity
            if reply.response.query_result.query_text:
                return reply.response.query_result.query_text
            attempts += 1
        return None

    def ask_entity_llm(self, question, strict=False, max_attempts=None, speaking_rate=None, animated=None):
        attempts = 0

        while attempts < max_attempts:
            # ask question
            self.say(question, speaking_rate=speaking_rate, animated=animated)

            # self.set_mouth_lamp(MouthLampColor.GREEN, MouthLampMode.NORMAL)
            # listen for answer
            reply = self.dialogflow.request(GetIntentRequest(self.request_id))
            # self.set_mouth_lamp(MouthLampColor.WHITE, MouthLampMode.BREATH)

            strict_instruction = ''
            if strict:
                strict_instruction = (f'Zorg ervoor dat de entity gerelateerd aan de vraag. '
                                      f'Is dat niet het geval return dan "none"'
                                      f'Bijvoorbeeld als de reactie is "lust er iemand nog koffie"'
                                      f'dan is "koffie" niet gerelateerd aan de vraag.')
            # Return entity
            if reply.response.query_result.query_text:
                print(f'transcript is {reply.response.query_result.query_text}')
                gpt_response = self.gpt.request(
                    GPTRequest(f'Je bent een sociale robot die praat met een kind tussen de 6 en 9 jaar oud. '
                               f'De robot stelt een vraag over een interesse van het kind.'
                               f'Jouw taak is om de key entity er uit te filteren'
                               f'Bijvoorbeeld bij de vraag: "wat is je lievelingsdier?" '
                               f'en de reactie "mijn lievelingsdier is een hond" '
                               f'filter je alleen "hond" als key entity uit. '
                               f'{strict_instruction}'
                               # f'of bijvoorbeeld "wat is je superkracht?" en de reactie '
                               # f'is "mijn superkracht is heel hard rennen"'
                               # f'filter je "heel hard rennen" er uit.'
                               f'Als robot heb je net het volgende gevraagt {question}'
                               f'Dit is de reactie van het kind {reply.response.query_result.query_text}'
                               f'Return alleen de key entity string terug (of none).'))
                print(f'response is {gpt_response.response}')

                self.log_recognition_result(f'llm extracted entity: {gpt_response.response}')
                if gpt_response.response != 'none':
                    return gpt_response.response
            attempts += 1
        self.log_recognition_result('llm extracted entity: None')
        return None

    def ask_llm(self, user_prompt, context_messages, system_prompt):
        try:
            resp = self.gpt.request(GPTRequest(prompt=user_prompt, context_messages=context_messages, system_message=system_prompt))
            text = (resp.response or "").strip()
            return text
        except Exception as e:
            print(f"Exception: {e}")
            return None

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

    def listening_behavior(self, start=True):
        # has not yet been tested on noa and alphamini
        if start:
            if isinstance(self.device_manager, Alphamini):
                # taken from droomrobot code
                self.set_alphamini_mouth_lamp(MouthLampColor.GREEN, MouthLampMode.NORMAL)
            elif isinstance(self.device_manager, Nao):
                self.animate_naoqi_leds(g=1)
            elif isinstance(self.device_manager, Pepper):
                self.animate_naoqi_leds(g=1)
        else:
            if isinstance(self.device_manager, Alphamini):
                self.set_alphamini_mouth_lamp(MouthLampColor.WHITE, MouthLampMode.BREATH)
            elif isinstance(self.device_manager, Nao):
                self.animate_naoqi_leds()
            elif isinstance(self.device_manager, Pepper):
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
