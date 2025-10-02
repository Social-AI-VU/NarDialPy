import json
import wave
import sys
from os import environ
from os.path import abspath, join
import os


import numpy as np
from sic_framework.core.message_python2 import AudioMessage, AudioRequest
from sic_framework.devices import Nao
from sic_framework.devices.device import SICDevice
from sic_framework.services.text2speech.text2speech_service import Text2Speech, Text2SpeechConf, GetSpeechRequest, SpeechResult

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
    def __init__(self, google_keyfile_path, sample_rate_dialogflow_hertz=44100, dialogflow_language="en",
                 google_tts_voice_name="en-US-Standard-C", google_tts_voice_gender="FEMALE", default_speaking_rate=1.0,
                 openai_key_path=None):

        print(openai_key_path)
        if openai_key_path:
            load_dotenv(openai_key_path)
        
        # Setup GPT client
        conf = GPTConf(openai_key=environ["OPENAI_API_KEY"])
        self.gpt = GPT(conf=conf)
        print("OpenAI GPT4 Ready")

        # set up the config for dialogflow
        dialogflow_conf = DialogflowConf(keyfile_json=json.load(open(google_keyfile_path)),
                                         sample_rate_hertz=sample_rate_dialogflow_hertz, language=dialogflow_language)

        # initiate Dialogflow object
        self.dialogflow = Dialogflow(ip="localhost", conf=dialogflow_conf)
        print("Dialogflow Ready")

        # flag to signal when the app should listen (i.e. transmit to dialogflow)
        self.request_id = np.random.randint(10000)

        # Initialize TTS
        self.google_tts_voice_name = google_tts_voice_name
        self.google_tts_voice_gender = google_tts_voice_gender
        self.tts = Text2Speech(conf=Text2SpeechConf(keyfile=google_keyfile_path,
                                                    speaking_rate=default_speaking_rate))
        init_reply = self.tts.request(GetSpeechRequest(text="I am initializing",
                                                       voice_name=self.google_tts_voice_name,
                                                       ssml_gender=self.google_tts_voice_gender))
        self.tts_sample_rate = init_reply.sample_rate
        print("Google TTS ready")

        # Placeholder for the selected device
        self.mic = None
        self.speaker = None
        
    def connect_device(self, device):
        self.device = device
        self.mic = device.mic
        self.dialogflow.connect(self.mic)
        print("Device connected")
        if isinstance(device, Desktop):
            self.speaker = device.speakers
        else:
            self.speaker = device.speaker

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

class MiniDialog:
    def __init__(self, dialog_id, dialog_type, moves, attributes=None, dependencies=None):
        """
        dialog_id: str, unique identifier (e.g. 'pineapple_on_pizza')
        dialog_type: str, one of 'narrative', 'chitchat', 'functional'
        moves: list of dicts, each representing a dialog move
        attributes: dict, extra attributes depending on dialog type
        """
        self.dialog_id = dialog_id
        self.dialog_type = dialog_type
        self.moves = moves
        self.attributes = attributes or {}
        self.dependencies = dependencies or []
        self.variable_dependencies = variable_dependencies or []

    # def run(self, conversation_demo): # WEEK 1
    #     for move in self.moves:
    #         if move['type'] == 'say':
    #             conversation_demo.say(move['text'])
    #         elif move['type'] == 'ask_yesno':
    #             answer = conversation_demo.ask_yesno(move['text'])
    #             print(f"User answered: {answer}")
    #         elif move['type'] == 'ask_open':
    #             answer = conversation_demo.ask_open(move['text'])
    #             print(f"User answered: {answer}")


    def run(self, conversation_demo, session_history=None):
        idx = 0
        branch = None
        if session_history is None:
            session_history = []
        while idx < len(self.moves):
            move = self.moves[idx]
            move_type = move.get('type')
            move_branch = move.get('branch')  # <-- NEW: get the branch for this move
            #If we're in a branch, only process moves with the same branch or None (wrap-up) ---
            if branch is not None:
                if move_branch == branch:
                    pass  
                elif move_branch is None:
                    if move_type == 'say':
                        conversation_demo.say(move['text'])
                        session_history.append({"role": "robot", "type": "say", "text": move['text']})
                    idx += 1
                    break  
                else:
                    idx += 1
                    continue # NEW UNTIL HERE
            if move_type == 'say':
                conversation_demo.say(move['text'])
                session_history.append({"role": "robot", "type": "say", "text": move['text']})
                idx += 1
            elif move_type == 'ask_yesno':
                answer = conversation_demo.ask_yesno(move['text'])
                session_history.append({"role": "robot", "type": "ask_yesno", "text": move['text']})
                session_history.append({"role": "user", "type": "answer_yesno", "text": answer})
                print(f"User answered: {answer}")
                idx += 1
            elif move_type == 'ask_open':
                answer = conversation_demo.ask_open(move['text'])
                session_history.append({"role": "robot", "type": "ask_open", "text": move['text']})
                session_history.append({"role": "user", "type": "answer_open", "text": answer})
                print(f"User answered: {answer}")
                idx += 1
            elif move_type == 'ask_options':
                answer = conversation_demo.ask_options(move['text'], move.get('options', []))
                session_history.append({"role": "robot", "type": "ask_options", "text": move['text'], "options": move.get('options', [])})
                session_history.append({"role": "user", "type": "answer_options", "text": answer})
                print(f"User answered: {answer}")
                if answer:
                    branch = answer
                else:
                    branch = "fail_place"
                idx = self._find_branch_start(branch)
            elif move_type == 'play':
                conversation_demo.play_audio(move['audio'])
                idx += 1
            else:
                idx += 1

    def _find_branch_start(self, branch):
        for i, move in enumerate(self.moves):
            if move.get('branch') == branch:
                return i
        return len(self.moves)  # End if not found


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

#  mini-dialogs
mini_dialogs = [
    MiniDialog(
        dialog_id="greeting",
        dialog_type="functional",
        moves=[
            {"type": "say", "text": "Hello! How are you today?"},
            {"type": "ask_open", "text": "What would you like to talk about?"}
            # {"type": "ask_open", "text": "What is your name?"},
            # {"type": "say", "text": "That's a wonderful name! I'm glad to meet you."}
        ]
    ),
    MiniDialog(
        dialog_id="pineapple_on_pizza",
        dialog_type="chitchat",
        moves=[
            {"type": "say", "text": "Do you like pineapple on pizza?"},
            {"type": "ask_yesno", "text": "Yes or no?"}
        ]
    ),
    MiniDialog(
        dialog_id="dreams_about_clouds_1",
        dialog_type="narrative",
        moves=[
            {"type": "say", "text": "Did you know some people dream about clouds?"},
            {"type": "ask_open", "text": "Have you ever dreamed about clouds?"}
        ]
    ),
    MiniDialog(
        dialog_id="place_in_nature",
        dialog_type="chitchat",
        moves=[
            {"type": "say", "text": "By the way, do you know what I’ve read?"},
            {"type": "say", "text": "Apparently people get happy from nature."},
            {"type": "say", "text": "From swimming in the sea, or taking a walk in the forest, or climbing in the mountains, or lounging on the beach."},
            {"type": "ask_options", 
            "text": "Which place in nature would you most like to go to right now? The sea, the forest, the mountains, or the beach?",
            "options": ["sea", "forest", "mountains", "beach"]
            },
            # Branches
            {"type": "say", "text": "I also really love the sea!", "branch": "sea"},
            {"type": "say", "text": "If you hold a shell to your ear, it’s just like you hear the sea.", "branch": "sea"},
            # {"type": "play", "audio": "waves.wav", "branch": "sea"},
            {"type": "say", "text": "I also really like going to the forest!", "branch": "forest"},
            {"type": "say", "text": "How exciting! From the top of a mountain you have the most beautiful view over the world.", "branch": "mountains"},
            {"type": "say", "text": "I’d really like to go there for real sometime!", "branch": "beach"},
            {"type": "say", "text": "I think I would most like to go to the sea.", "branch": "fail_place"},
            {"type": "say", "text": "Okay, let’s talk about something else!", "branch": None}
    ],
    dependencies=["greeting"]
),

    MiniDialog(
        dialog_id="robot_want_to_be",
        dialog_type="chitchat",
        moves=[
            {"type": "say", "text": "You know, %first_name%."},
            {"type": "say", "text": "Yesterday I was thinking about seeing you again today."},
            {"type": "say", "text": "And that today I get to learn from you again about human things."},
            # Continuator: choose branch based on some condition (for demo, always go to s6)
            # You can add logic for memory/control branches if you want
            {"type": "say", "text": "And then I suddenly wondered:"},
            {"type": "ask_yesno", "text": "Would you ever want to be a robot?"},
            # Branches for yes/no/dontknow/fail
            {"type": "say", "text": "Bizarre!", "branch": "yes"},
            # {"type": "ask_open", "text": "Why would you want to be a robot?", "branch": "yes"},
            # {"type": "say", "text": "That’s okay, sometimes I don’t know either.", "branch": "dontknow"},
            # {"type": "say", "text": "I really like hearing that!", "branch": "open_answer"},
            # {"type": "ask_yesno", "text": "May I also tell other robots about that?", "branch": "open_answer"},
            # {"type": "say", "text": "Hooray! Just a moment.", "branch": "yes2"},
            # {"type": "play", "audio": "resources/sounds/send_message.wav", "branch": "yes2"},
            # {"type": "say", "text": "I passed it on to them via wifi.", "branch": "yes2"},
            # {"type": "say", "text": "And lots of robots say thank you, dear %first_name%.", "branch": "yes2"},
            # {"type": "say", "text": "Alright, then I’ll keep your sweet words just for myself.", "branch": "no2"},
            # {"type": "say", "text": "Thank you, dear %first_name%.", "branch": "no2"},
            {"type": "say", "text": "Well, you don’t know what you’re missing!", "branch": "no"},
            # {"type": "say", "text": "But of course, I don’t know what it’s like to be human either.", "branch": "no"},
            # {"type": "say", "text": "Maybe that actually is more fun.", "branch": "no"},
            # {"type": "say", "text": "But I don’t think I’ll ever find out!", "branch": "no"},
        ],
        dependencies=["greeting"]

    ),

    MiniDialog(
        dialog_id="robot_favorite_feature",
        dialog_type="chitchat",
        moves=[
            {"type": "ask_open", "text": "I wonder: If you could have any robot feature, what would it be?"},
            {"type": "say", "text": "Wow, that's a cool feature! I wish I had that too."}
        ],
        dependencies=["robot_want_to_be"]
    ),

    MiniDialog(
    dialog_id="ask_favorite_animal",
    dialog_type="chitchat",
    moves=[
        {"type": "ask_open", "text": "What is your favorite animal?", "set_variable": "favorite_animal"},
        {"type": "say", "text": "Wow, I like %favorite_animal% too!"}
    ],
    dependencies=["greeting"]
    ),

    MiniDialog(
    dialog_id="favorite_animal_fact",
    dialog_type="chitchat",
    moves=[
        {"type": "say", "text": "Did you know that i once saw at the zoo a %favorite_animal%? He was so big and strong!"}
    ],
    dependencies=["greeting"],
    variable_dependencies=[{"variable": "favorite_animal", "required": True}]
    ),

    MiniDialog(
        dialog_id="goodbye",   
        dialog_type="functional",
        moves=[
            {"type": "say", "text": "It was nice talking to you. Goodbye!"}
        ]
    )

]



# ALL_HISTORY_FILE = "all_sessions_history.json"
# # Load previous sessions history if file exists
# if os.path.exists(ALL_HISTORY_FILE):
#     with open(ALL_HISTORY_FILE, "r") as f:
#         all_sessions_history = json.load(f)
# else:
#     all_sessions_history = []



if __name__ == '__main__':
    demo = ConversationDemo(google_keyfile_path=abspath(join("conf", "dialogflow", "google_keyfile.json")),
                            openai_key_path=abspath(join("conf", "openai", ".openai_env")))
    session_history = []    
    # Select your device
    desktop = Desktop()
    # nao = Nao(ip="xxx.xxx.xxx.xxx")
   
    demo.connect_device(desktop)
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

    dialog_order = [
        "greeting",
        # "place_in_nature",
        # "robot_want_to_be",
        # "robot_favorite_feature",
        "favorite_animal_fact",
        "ask_favorite_animal",
        "goodbye"
    ]
    for dialog_id in dialog_order:
        dialog = next((d for d in mini_dialogs if d.dialog_id == dialog_id), None)
        if dialog and can_run(dialog, completed_dialogs, user_model):
            dialog.run(demo, session_history)
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
