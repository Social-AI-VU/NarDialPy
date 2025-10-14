import json
import wave
import sys
from os import environ
from os.path import abspath, join
import os

import random
from mini_dialogs import mini_dialogs, NarrativeDialog, ChitchatDialog, FunctionalDialog


import numpy as np
from sic_framework.core.message_python2 import AudioMessage, AudioRequest
from sic_framework.devices import Nao
from sic_framework.devices.device import SICDevice
from sic_framework.services.google_tts.google_tts import Text2Speech, Text2SpeechConf, GetSpeechRequest, SpeechResult
from sic_framework.devices.common_desktop.desktop_speakers import SpeakersConf
from sic_framework.services.openai_gpt.gpt import GPT, GPTConf, GPTRequest
from dotenv import load_dotenv

from sic_framework.devices.desktop import Desktop
from sic_framework.services.dialogflow.dialogflow import (
    Dialogflow,
    DialogflowConf,
    GetIntentRequest,
)

"""
This is a demo show casing a agent-driven conversation utalizating Google Dialogflow, Google TTS, and OpenAI's GTP4

IMPORTANT
First, you need to set-up Google Cloud Console with dialogflow and Google TTS:

1. Dialogflow: https://socialrobotics.atlassian.net/wiki/spaces/CBSR/pages/2205155343/Getting+a+google+dialogflow+key 
2. TTS: https://console.cloud.google.com/apis/api/texttospeech.googleapis.com/ 
2a. note: you need to set-up a paid account with a credit card. You get $300,- free tokens, which is more then enough
for testing this agent. So in practice it will not cost anything.
3. Create a keyfile as instructed in (1) and save it conf/dialogflow/google_keyfile.json
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

7. pip install --upgrade social-interaction-cloud[dialogflow,google-tts,openai-gpt]
8. run: conf/redis/redis-server.exe conf/redis/redis.conf
9. run in new terminal: run-dialogflow 
10. run in new terminal: run-google-tts
11. run in new terminal: run-gpt
12. connect a device e.g. desktop, nao, pepper, alphamini
13. Run this script
"""


class ConversationDemo:
    def __init__(self, device_info: dict, google_keyfile_path, sample_rate_dialogflow_hertz=44100, dialogflow_language="en",
                 google_tts_voice_name="en-US-Standard-C", google_tts_voice_gender="FEMALE", default_speaking_rate=1.0,
                 openai_key_path=None):

        print(openai_key_path)
        if openai_key_path:
            load_dotenv(openai_key_path)
        
        # Setup GPT client
        conf = GPTConf(openai_key=environ["OPENAI_API_KEY"])
        self.gpt = GPT(conf=conf)
        print("OpenAI GPT4 Ready")


        # Initialize TTS
        self.google_tts_voice_name = google_tts_voice_name
        self.google_tts_voice_gender = google_tts_voice_gender
        self.tts = Text2Speech(conf=Text2SpeechConf(keyfile_json=json.load(open(google_keyfile_path)),
                                                    speaking_rate=default_speaking_rate))
        init_reply = self.tts.request(GetSpeechRequest(text="I am initializing",
                                                       voice_name=self.google_tts_voice_name,
                                                       ssml_gender=self.google_tts_voice_gender))
        self.tts_sample_rate = init_reply.sample_rate
        print("Google TTS ready")

        # Placeholder for the selected device
        if "type" in device_info and device_info["type"] == "nao":
            self.device = Nao(ip=device_info["ip"])
            self.speaker = self.device.speaker
        else:
            self.device = Desktop(speakers_conf=SpeakersConf(sample_rate=self.tts_sample_rate))
            self.speaker = self.device.speakers
        self.mic = self.device.mic
              
        print("Device connected")

                # set up the config for dialogflow
        dialogflow_conf = DialogflowConf(keyfile_json=json.load(open(google_keyfile_path)),
                                         sample_rate_hertz=sample_rate_dialogflow_hertz, language=dialogflow_language)

        # initiate Dialogflow object
        self.dialogflow = Dialogflow(ip="localhost", conf=dialogflow_conf, input_source=self.mic)
                # flag to signal when the app should listen (i.e. transmit to dialogflow)
        self.request_id = np.random.randint(10000)
        print("Dialogflow Ready")
        

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

            self.speaker.request(AudioRequest(wf.readframes(n_frames), framerate))

    def ask_yesno(self, question, max_attempts=2):
        attempts = 0
        while attempts < max_attempts:
            # ask question
            tts_reply = self.tts.request(GetSpeechRequest(text=question,
                                                          voice_name=self.google_tts_voice_name,
                                                          ssml_gender=self.google_tts_voice_gender))
            self.speaker.request(AudioRequest(tts_reply.waveform, tts_reply.sample_rate))

            # listen for answer
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
            reply = self.dialogflow.request(GetIntentRequest(self.request_id))

            print("The detected intent:", reply.intent)

            # Return entity
            if reply.response.query_result.query_text:
                return reply.response.query_result.query_text
            attempts += 1
        return None

# ADD LISTEN DEFINITION

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

    # def personalize(self, robot_input, user_age, user_input):
    #     gpt_response = self.gpt.request(
    #         GPTRequest(f'Je bent een sociale robot die praat met een kind van {str(user_age)} jaar oud.'
    #                    f'Het kind ligt in het ziekenhuis.'
    #                    f'Jij bent daar om het kind af te leiden met een leuk gesprek.'
    #                    f'Als robot heb je zojuist het volgende gevraagd: {robot_input}'
    #                    f'Het kind reageerde met het volgende: "{user_input}"'
    #                    f'Genereer nu een passende reactie in 1 zin.'))
    #     return gpt_response.response

    def run(self):
        self.say("Hello, I am your companion robot")


# NEW LOGIC FOR NARRATIVE AND CHITCHAT DIALOGS

def can_run(dialog, completed_ids, user_model, all_dialogs=None):
    if dialog.dialog_id in completed_ids:
        return False
    for dep in getattr(dialog, "dependencies", []):
        if dep not in completed_ids:
            return False
    for var_dep in getattr(dialog, "variable_dependencies", []):
        var = var_dep["variable"]
        required = var_dep.get("required", True)
        if required and not user_model.get(var):
            return False
    if isinstance(dialog, NarrativeDialog):
        if all_dialogs is None:
            all_dialogs = mini_dialogs
        for d in all_dialogs:
            if (isinstance(d, NarrativeDialog) and
                d.thread == dialog.thread and
                d.position < dialog.position and
                d.dialog_id not in completed_ids):
                return False
    return True

def topic_match(dialog, topics_of_interest):
    if not topics_of_interest:
        return True
    interests = [str(t).lower() for t in topics_of_interest]
    dialog_topics = [str(t).lower() for t in getattr(dialog, "topics", [])]
    return any(topic in interests for topic in dialog_topics)


def select_session_block(mini_dialogs, thread=None, theme=None, topics_of_interest=None):
    session = []
    pool = list(mini_dialogs)

    greeting = next((d for d in pool if isinstance(d, FunctionalDialog) and d.type == "greeting"), None)
    if greeting:
        session.append(greeting)
        pool.remove(greeting)

    narratives = [d for d in pool if isinstance(d, NarrativeDialog) and d.thread == thread]
    narratives.sort(key=lambda d: d.position)
    if narratives:
        n1 = narratives.pop(0); session.append(n1); pool.remove(n1)

    chitchats = [d for d in pool if isinstance(d, ChitchatDialog) and d.theme == theme]
    if topics_of_interest:
        t_matched = [d for d in chitchats if topic_match(d, topics_of_interest)]
        if t_matched:
            chitchats = t_matched
    if chitchats:
        c1 = random.choice(chitchats); session.append(c1); pool.remove(c1); chitchats.remove(c1)
    
    
    if narratives:
        n2 = narratives.pop(0); session.append(n2); pool.remove(n2)

    chitchats2 = [d for d in pool if isinstance(d, ChitchatDialog) and d.theme == theme]
    if topics_of_interest:
        t_matched2 = [d for d in chitchats2 if topic_match(d, topics_of_interest)]
        if t_matched2:
            chitchats2 = t_matched2
    if chitchats2:
        c2 = random.choice(chitchats2); session.append(c2); pool.remove(c2)

    goodbye = next((d for d in pool if isinstance(d, FunctionalDialog) and d.type == "farewell"), None)
    if goodbye:
        session.append(goodbye)
    return session

# ALL_HISTORY_FILE = "all_sessions_history.json"
# # Load previous sessions history if file exists
# if os.path.exists(ALL_HISTORY_FILE):
#     with open(ALL_HISTORY_FILE, "r", encoding="utf-8") as f:
#         all_sessions_history = json.load(f)
# else:
#     all_sessions_history = []

# class history_file(object):
#     def __init__(self, filename):
#         self.filename = filename
#         if os.path.exists(self.filename):
#             with open(self.filename, "r", encoding="utf-8") as f:
#                 self.all_sessions_history = json.load(f)
#         else:
#             self.all_sessions_history = []

#     def save(self):
#         with open(self.filename, "w", encoding="utf-8") as f:
#             json.dump(self.all_sessions_history, f, indent=2)
#         print(f"All sessions history saved to {self.filename}")


if __name__ == '__main__':
    # Select your device
    device = {
        "type": "desktop"
    }
    # device = {
    #     "type": "nao",
    #     "ip": "xxx.xxx.xxx.xxx"
    # }

    demo = ConversationDemo(device, google_keyfile_path=abspath(join("conf", "dialogflow", "google_keyfile.json")),
                            openai_key_path=abspath(join("conf", "openai", ".openai_env")))
    session_history = []    
    demo.run()
    completed_dialogs = set()
    user_model = {}

    topics_of_interest = []  # separate interest list
    # session_block = select_session_block(
    #     mini_dialogs, thread="dreams", theme="nature",     # or None for any thread
    #     topics_of_interest=topics_of_interest,
    #     completed_ids=completed_dialogs,
    #     max_narratives=2,
    #     max_chitchats=2,
    #     exploration_rate=0.25
    # )


# NEW
    session_block = select_session_block(mini_dialogs, thread="dreams", theme="nature", topics_of_interest="animals")

    for dialog in session_block:
        if can_run(dialog, completed_dialogs, user_model, all_dialogs=mini_dialogs):
            dialog.run(demo, session_history, user_model)
            completed_dialogs.add(dialog.dialog_id)
        else:
            print(f"Skipped {dialog.dialog_id} (cannot run now)")
# NEW

    print(json.dumps(session_history, indent=2))

    # all_sessions_history.append(session_history)
    # # Save all sessions history to file
    # with open(ALL_HISTORY_FILE, "w", encoding="utf-8") as f:
    #     json.dump(all_sessions_history, f, indent=2)
    # print(f"All sessions history saved to {ALL_HISTORY_FILE}")

    sys.exit()

