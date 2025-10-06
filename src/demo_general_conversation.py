import json
import wave
import sys
from os import environ
from os.path import abspath, join
import os

import random

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



# def can_run(mini_dialog, completed_dialogs):
#     # only run a mini-dialog if all its required previous dialogs have already been completed
#     return all(dep in completed_dialogs for dep in mini_dialog.dependencies)

def can_run(mini_dialog, completed_dialogs, user_model):
    # dialog dependencies
    if not all(dep in completed_dialogs for dep in mini_dialog.dependencies):
        return False
    # variable dependencies
    for var_dep in getattr(mini_dialog, "variable_dependencies", []):
        var = var_dep["variable"]
        required = var_dep.get("required", True)
        if required and not user_model.get(var):
            return False
    return True

def select_session_block(mini_dialogs, thread="narrative", theme="chitchat"):
    session_block = []
    available_dialogs = mini_dialogs.copy()
    greetings = next((d for d in available_dialogs if d.dialog_type=="functional" and d.dialog_id == "greeting"), None)
    if greetings:
        session_block.append(greetings)
        available_dialogs.remove(greetings)
        
    narratives = [d for d in available_dialogs if d.dialog_type=="narrative" and d.attributes.get("thread")==thread]
    narratives = sorted(narratives, key=lambda d: mini_dialogs.index(d))  # preserve original order
    chitchats = [d for d in available_dialogs if d.dialog_type=="chitchat" and d.attributes.get("theme")==theme]
    farewells = next((d for d in available_dialogs if d.dialog_type=="functional" and d.dialog_id == "goodbye"), None)
    if narratives:
        session_block.append(narratives[0])
        available_dialogs.remove(narratives[0]) 
    if chitchats:
        session_block.append(random.choice(chitchats))
        available_dialogs.remove(session_block[-1])
    if len(narratives) > 1:
        session_block.append(narratives[1])
        available_dialogs.remove(narratives[1])
    chitchats = [d for d in available_dialogs if d.dialog_type=="chitchat" and d.attributes.get("theme")==theme]
    if chitchats:
        session_block.append(random.choice(chitchats))
        available_dialogs.remove(session_block[-1])
    if farewells:
        session_block.append(farewells)
    return session_block


from mini_dialogs import mini_dialogs


# ALL_HISTORY_FILE = "all_sessions_history.json"
# # Load previous sessions history if file exists
# if os.path.exists(ALL_HISTORY_FILE):
#     with open(ALL_HISTORY_FILE, "r") as f:
#         all_sessions_history = json.load(f)
# else:
#     all_sessions_history = []



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

    # result = demo.ask_yesno("Do you like robots?")
    # print("User answered:", result)
    # if result == "yes":
    #     demo.say("That's great! I like you too.")
    # elif result == "no":
    #     demo.say("Oh, that's okay! Maybe I can change your mind.")
    # elif result == "dontknow":
    #     demo.say("That's fine! You can decide later.")
    # else:
    #     demo.say("I didn't catch that. Let's try again.")

    # open_answer = demo.ask_open("What is your favorite thing to do?")
    # print("User said:", open_answer)
    # if open_answer:
    #     demo.say(f"That sounds fun! I like {open_answer} too.")
    # else:
    #     demo.say("I didn't catch that. Let's try again another time.")


    # mini_dialogs[0].run(demo)  # greeting
    # mini_dialogs[3].run(demo)  # place_in_nature


    # # Run only selected dialogs, respecting dependencies
    completed_dialogs = set()
    user_model = {}

    # dialog_order = [
    #     "greeting",
    #     # "place_in_nature",
    #     # "robot_want_to_be",
    #     # "robot_favorite_feature",
    #     # "ask_favorite_animal",
    #     # "favorite_animal_fact",
    #     "hero_can_dream_1", 
    #     "goodbye"
    # ]
    # for dialog_id in dialog_order:
    #     dialog = next((d for d in mini_dialogs if d.dialog_id == dialog_id), None)
    #     if dialog and can_run(dialog, completed_dialogs, user_model):
    #         dialog.run(demo, session_history, user_model)
    #         completed_dialogs.add(dialog.dialog_id)
    session_block = select_session_block(mini_dialogs, thread="dreams", theme="nature")

    for dialog in session_block:
        if can_run(dialog, completed_dialogs, user_model):
            dialog.run(demo, session_history, user_model)
            completed_dialogs.add(dialog.dialog_id)




    # mini_dialogs[0].run(demo, session_history)  # greeting
    # mini_dialogs[3].run(demo, session_history)  # place_in_nature
    # mini_dialogs[4].run(demo, session_history)  # robot_want_to_be
    # mini_dialogs[-1].run(demo, session_history)  # goodbye
    print(json.dumps(session_history, indent=2))



    # all_sessions_history.append(session_history)
    # # Save all sessions history to file
    # with open(ALL_HISTORY_FILE, "w") as f:
    #     json.dump(all_sessions_history, f, indent=2)
    # print(f"All sessions history saved to {ALL_HISTORY_FILE}")

    sys.exit()
