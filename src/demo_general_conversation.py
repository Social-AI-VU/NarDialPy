import json
import wave
import sys
from os import environ
from os.path import abspath, join
import os

import random
import re
from mini_dialogs import NarrativeDialog, ChitchatDialog, FunctionalDialog
from authoring.loader import load_dialogs
from historyclass import ConversationState


import numpy as np
from sic_framework.core.message_python2 import AudioMessage, AudioRequest
from sic_framework.devices import Nao
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


class ConversationAgent:  # renamed from ConversationDemo
    def __init__(self, device_info: dict, google_keyfile_path, sample_rate_dialogflow_hertz=44100, dialogflow_language="en",
                 google_tts_voice_name="en-US-Standard-C", google_tts_voice_gender="FEMALE", default_speaking_rate=1.0,
                 openai_key_path=None):

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
    def start_new_session(self):
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

    def extract_topics_with_gpt(self, raw_topics):
        """Condense raw topics (often full sentences) into 1-2 single-word, lowercase keywords.

        Returns a de-duplicated list preserving order. Falls back to a simple local heuristic
        if the GPT response can't be parsed.
        """
        def _heuristic(lines):
            if not lines:
                return []
            stop = {
                "the","a","an","and","or","but","if","then","than","that","this","these","those",
                "i","you","he","she","it","we","they","me","my","mine","your","yours","his","her","its","our","ours","their","theirs",
                "to","in","on","at","from","for","with","about","as","of","is","are","was","were","be","been","am","do","does","did",
                "yes","no","maybe","okay","ok","yeah","yep","nope","uh","um","favorite","favourite","because","thing","things","think"
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
                        out.append(w); seen.add(w)
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
                    out.append(w); seen.add(w)
            return out or _heuristic(raw_topics)
        except Exception:
            return _heuristic(raw_topics)

    # def personalize(self, robot_input, user_age, user_input):
    # gpt_response = self.gpt.request(
    #     GPTRequest(
    #         f'Je bent een sociale robot die praat met een kind van {str(user_age)} jaar oud.'
    #         f'Het kind ligt in het ziekenhuis.'
    #         f'Jij bent daar om het kind af te leiden met een leuk gesprek.'
    #         f'Als robot heb je zojuist het volgende gevraagd: {robot_input}'
    #         f'Het kind reageerde met het volgende: "{user_input}"'
    #         f'Genereer nu een passende reactie in 1 zin.'
    #     )
    # )
    # return gpt_response.response

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

    def run(self):
        self.say("Hello, I am your companion robot")
        # Example usage of personalize (pseudo-flow):
        # question = "What is your favorite animal?"
        # user_answer = self.ask_open(question)
        # if user_answer:
        #     follow_up = self.personalize(question, user_age=9, user_input=user_answer, language="en")
        #     self.say(follow_up)


# NEW LOGIC FOR NARRATIVE AND CHITCHAT DIALOGS
class DialogLogic:  # this is a new change
    @staticmethod
    def can_run(dialog, completed_ids, user_model, all_dialogs=None):
        # check if dialog can be run based on dependencies and user model variables
        # if narrative dialog, check position in thread and if previous narratives in thread have been completed
        # Block any dialog that is already completed (including greeting/farewell)
        if dialog.dialog_id in completed_ids:
            return False
                                # COMMENT ABOVE LINE TO
                            # Allow greeting/farewell every session even if seen before
            # if isinstance(dialog, FunctionalDialog) and getattr(dialog, "type", None) in {"greeting", "farewell"}:
            #     pass  # don't block functional open/close
            # else:
            #     return False
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
                all_dialogs = []
            for d in all_dialogs:
                if (isinstance(d, NarrativeDialog) and
                    d.thread == dialog.thread and
                    d.position < dialog.position and
                    d.dialog_id not in completed_ids):
                    return False
        return True

    @staticmethod
    def topic_match(dialog, topics_of_interest):
        # choose a dialog that matches the user's topics of interest list and it is prioritized for selection.
        # work in progress ; it needs testing
        if not topics_of_interest:
            return True
        interests = [str(t).lower() for t in topics_of_interest]
        dialog_topics = [str(t).lower() for t in getattr(dialog, "topics", [])]
        return any(topic in interests for topic in dialog_topics)

    @staticmethod
    def load_participant_continuity(participant_id: str):
        """
        Read participants/{participant_id}.json if present and return:
        (completed_dialogs_set, topics_of_interest_list).
        Falls back to empty if no file or unreadable.
        """
        try:
            pid = str(participant_id)
            path = os.path.join("participants", f"{pid}.json")
            if not os.path.exists(path):
                return set(), []
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            summary = data.get("summary") or {}
            completed = set(summary.get("dialog_ids_seen") or [])
            topics = list(summary.get("topics_of_interest") or [])
            return completed, topics
        except Exception:
            return set(), []

    @staticmethod  # this is a new change
    def prioritized_chitchat(pool, theme=None, topics_of_interest=None):
        """
        NEW: prioritize chitchat candidates by deps∧interests > interests > deps > others
        """
        cands = [d for d in pool if isinstance(d, ChitchatDialog) and (theme is None or d.theme == theme)]
        if not cands:
            return []
        random.shuffle(cands)  # randomize within same priority
        def score(d):
            has_deps = 1 if getattr(d, "dependencies", []) else 0
            has_interest = 1 if (topics_of_interest and DialogLogic.topic_match(d, topics_of_interest)) else 0  # this is a new change
            # tuple sorted descending: (deps&interest, interest, deps)
            return (has_deps & has_interest, has_interest, has_deps)
        return sorted(cands, key=score, reverse=True)

    @staticmethod  # this is a new change
    def auto_select_thread(mini_dialogs, preferred_thread, completed_ids, user_model):
        """
        Pick a narrative thread that still has a runnable next dialog.
        - Try the preferred_thread first.
        - Otherwise, scan all threads and pick the first with a runnable next narrative.
        Returns the chosen thread name, or None if no thread has pending items.
        """
        pool = list(mini_dialogs)
        # Try preferred first
        if preferred_thread:
            if DialogLogic.pick_next_narrative(pool, preferred_thread, completed_ids=completed_ids, user_model=user_model, all_dialogs=mini_dialogs):  # this is a new change
                return preferred_thread
        # Try any other thread
        threads = []
        for d in mini_dialogs:
            if isinstance(d, NarrativeDialog) and d.thread not in threads:
                threads.append(d.thread)
        # randomize to avoid always picking the same fallback
        random.shuffle(threads)
        for t in threads:
            if t == preferred_thread:
                continue
            if DialogLogic.pick_next_narrative(pool, t, completed_ids=completed_ids, user_model=user_model, all_dialogs=mini_dialogs):  # this is a new change
                return t
        return None

    @staticmethod  # this is a new change
    def schedule_chitchat(session, pool, theme=None, topics_of_interest=None, all_dialogs=None, completed_ids=None):
        """
        Try to schedule one chitchat into session from pool.
        Improvements:
        - Treat any executed greeting variant as satisfying a "greeting" dependency.
        - Consider continuity (completed_ids) so chitchats can run even if greeting
          isn't scheduled in this session because it was done in a previous run.
        """
        all_dialogs = all_dialogs or []
        cands = DialogLogic.prioritized_chitchat(pool, theme=theme, topics_of_interest=topics_of_interest)  # this is a new change
        if not cands:
            return False
        for c in cands:
            # Effective completion set: dialogs already in this session ∪ continuity
            completed_so_far = {d.dialog_id for d in session}
            effective_completed = set(completed_so_far)
            if completed_ids:
                effective_completed |= set(completed_ids)
            # If any greeting variant ran in-session, satisfy generic "greeting" deps
            greeted = any(isinstance(d, FunctionalDialog) and getattr(d, "type", None) == "greeting" for d in session)
            if greeted:
                effective_completed.add("greeting")

            if DialogLogic.can_run(c, effective_completed, user_model={}, all_dialogs=all_dialogs):  # this is a new change
                session.append(c); pool.remove(c)
                return True
            # try to insert one runnable dependency first, then the candidate
            for dep_id in getattr(c, "dependencies", []):
                dep = next((d for d in pool if d.dialog_id == dep_id), None)
                if not dep:
                    continue
                if DialogLogic.can_run(dep, effective_completed, user_model={}, all_dialogs=all_dialogs):  # this is a new change
                    session.append(dep); pool.remove(dep)
                    effective_completed.add(dep.dialog_id)
                    if DialogLogic.can_run(c, effective_completed, user_model={}, all_dialogs=all_dialogs):  # this is a new change
                        session.append(c); pool.remove(c)
                        return True
                    # if still not runnable, continue trying other candidates
        return False

    @staticmethod  # this is a new change
    def pick_next_narrative(pool, thread, completed_ids, user_model, all_dialogs):
        """
        Pick the next runnable narrative in thread (lowest position not yet completed).
        Returns a dialog or None.
        """
        candidates = [d for d in pool if isinstance(d, NarrativeDialog) and d.thread == thread]
        candidates.sort(key=lambda d: d.position)
        for d in candidates:
            if DialogLogic.can_run(d, completed_ids, user_model, all_dialogs=all_dialogs):  # this is a new change
                return d
        return None

    @staticmethod  # this is a new change
    def select_session_block(mini_dialogs, thread=None, theme=None, topics_of_interest=None, completed_ids=None):
        # we need to use the pick_next_narrative and pick_chitchat functions here
        session = []
        pool = list(mini_dialogs)
        completed_ids = set(completed_ids or set())
        # 1) Greeting: prefer a not-yet-used variant; otherwise include any greeting variant so we always greet
        greeting = next((d for d in pool if isinstance(d, FunctionalDialog) and d.type == "greeting" and d.dialog_id not in completed_ids), None)
        if not greeting:
            greeting = next((d for d in pool if isinstance(d, FunctionalDialog) and d.type == "greeting"), None)
        if greeting:
            session.append(greeting)
            pool.remove(greeting)
        # 2) First narrative in thread
        n1 = DialogLogic.pick_next_narrative(pool, thread, completed_ids=completed_ids, user_model={}, all_dialogs=mini_dialogs)  # this is a new change
        if n1:
            session.append(n1)
            pool.remove(n1)
        # 3) One themed chitchat (use continuity-aware scheduling); if none runnable, print notice
        added_c1 = DialogLogic.schedule_chitchat(session, pool, theme=theme, topics_of_interest=topics_of_interest, all_dialogs=mini_dialogs, completed_ids=completed_ids)  # this is a new change
        if not added_c1:
            # Try relaxing theme once before giving up for this slot
            added_c1 = DialogLogic.schedule_chitchat(session, pool, theme=None, topics_of_interest=topics_of_interest, all_dialogs=mini_dialogs, completed_ids=completed_ids)  # this is a new change
        if not added_c1:
            print("[INFO] Chitchats not available for this participant (after narrative 1).")
        # 4) Next narrative in same thread
        n2 = DialogLogic.pick_next_narrative(pool, thread, completed_ids=completed_ids.union({d.dialog_id for d in session}), user_model={}, all_dialogs=mini_dialogs)  # this is a new change
        if n2:
            session.append(n2)
            pool.remove(n2)
        # 5) Another themed chitchat; if none runnable, print notice
        added_c2 = DialogLogic.schedule_chitchat(session, pool, theme=None if topics_of_interest else theme, topics_of_interest=topics_of_interest, all_dialogs=mini_dialogs, completed_ids=completed_ids)  # this is a new change
        if not added_c2:
            added_c2 = DialogLogic.schedule_chitchat(session, pool, theme=theme, topics_of_interest=topics_of_interest, all_dialogs=mini_dialogs, completed_ids=completed_ids)  # this is a new change
        if not added_c2:
            print("[INFO] Chitchats not available for this participant (after narrative 2).")

        # 6) Goodbye: prefer a not-yet-used variant; otherwise include any farewell variant so we always close politely
        goodbye = next((d for d in pool if isinstance(d, FunctionalDialog) and d.type == "farewell" and d.dialog_id not in completed_ids), None)
        if not goodbye:
            goodbye = next((d for d in pool if isinstance(d, FunctionalDialog) and d.type == "farewell"), None)
        if goodbye:
            session.append(goodbye)
        return session


ALL_HISTORY_FILE = "all_sessions_history.json"
# Load previous sessions history if file exists
if os.path.exists(ALL_HISTORY_FILE):
    with open(ALL_HISTORY_FILE, "r", encoding="utf-8") as f:
        all_sessions_history = json.load(f)
else:
    all_sessions_history = []







if __name__ == '__main__':
    # Select your device
    device = {
        "type": "desktop"
    }
    # device = {
    #     "type": "nao",
    #     "ip": "xxx.xxx.xxx.xxx"
    # }

    demo = ConversationAgent(device, google_keyfile_path=abspath(join("conf", "dialogflow", "google_keyfile.json")),  # updated class name
                            openai_key_path=abspath(join("conf", "openai", ".openai_env")))

    history = ConversationState()
    history.load()
    session_history = []
    demo.run()

    # Seed from persisted continuity
    completed_dialogs = set(history.completed_dialogs)
    user_model = dict(history.user_model)
    topics_of_interest = list(history.topics_of_interest)

    # Start new history session (store thread/theme if you like)
    # Participant ID: set via environment variable PARTICIPANT_ID (optional)
    participant_id = os.environ.get("PARTICIPANT_ID") or None
    if participant_id:
        try:
            print(f"[INFO] Using participant_id={participant_id}")
        except Exception:
            pass

    # Override continuity per participant if an ID is provided
    if participant_id:
        pid_completed, pid_topics = DialogLogic.load_participant_continuity(participant_id)  # this is a new change
        # For a new participant (no file), this will be empty -> fresh run
        completed_dialogs = pid_completed or set()
        topics_of_interest = pid_topics or []
        user_model = {}  # avoid leaking variables across participants
        try:
            print(f"[DEBUG] Loaded participant continuity: completed={sorted(list(completed_dialogs))}, topics={topics_of_interest}")
        except Exception:
            pass
    # Create a run_id to group sessions that belong to a single experimental run
    run_id = os.environ.get("RUN_ID") or f"run_{np.random.randint(1_000_000):06d}"
    session_id = history.start_session(metadata={"thread": "dreams", "theme": "nature"}, participant_id=participant_id, run_id=run_id)
    # Ensure Dialogflow uses a fresh request id per session
    demo.start_new_session()
    try:
        print(f"[INFO] Started session_id={session_id} run_id={run_id}")
    except Exception:
        pass

    # Load dialogs from JSON if available, otherwise fall back to builtin Python list
    dialogs_json_path = abspath(join("assets", "dialogs", "dialogs.json"))
    try:
        all_dialogs_loaded, load_errs = load_dialogs(dialogs_json_path)
        if load_errs:
            print("[WARN] Issues while loading dialogs.json:")
            for e in load_errs:
                print(" -", e)
        if all_dialogs_loaded:
            all_dialogs = all_dialogs_loaded
            print(f"[INFO] Loaded {len(all_dialogs)} dialogs from {dialogs_json_path}")
        else:
            all_dialogs = []
            print("[WARN] No JSON dialogs loaded and builtin dialogs are unavailable. Proceeding with 0 dialogs.")
    except Exception as e:
        all_dialogs = []
        print(f"[WARN] Falling back to empty dialogs due to error: {e}")

    # Build a session plan (greeting → narrative → chitchat → narrative → chitchat → farewell)
    # Auto-pick a thread if the preferred one has no pending narratives
    preferred_thread = "dreams"
    chosen_thread = DialogLogic.auto_select_thread(all_dialogs, preferred_thread, completed_ids=completed_dialogs, user_model=user_model)  # this is a new change
    try:
        print(f"[DEBUG] Narrative thread chosen: {chosen_thread}")
    except Exception:
        pass
    session_block = DialogLogic.select_session_block(all_dialogs, thread=chosen_thread, theme="nature", topics_of_interest=topics_of_interest, completed_ids=completed_dialogs)  # this is a new change
    # Debug: show planned dialogs
    try:
        print("[DEBUG] Planned session block:", [d.dialog_id for d in session_block])
    except Exception:
        pass

    for dialog in session_block:
        if DialogLogic.can_run(dialog, completed_dialogs, user_model, all_dialogs=all_dialogs):  # this is a new change
            # record which dialog runs
            history.add_dialog_id(session_id, dialog.dialog_id)
            # optional lightweight markers in session_history
            session_history.append({"role": "system", "type": "dialog_start", "dialog_id": dialog.dialog_id})
            dialog.run(demo, session_history, user_model, topics_of_interest)
            session_history.append({"role": "system", "type": "dialog_end", "dialog_id": dialog.dialog_id})
            completed_dialogs.add(dialog.dialog_id)
        else:
            print(f"[DEBUG] Skipped {dialog.dialog_id} (cannot run now)")

    print(json.dumps(session_history, indent=2))
    print("Topics of interest:", topics_of_interest)

    # Condense topics_of_interest into single-word keywords via GPT (with a simple fallback)
    try:
        original_topics = list(topics_of_interest)
        condensed = demo.extract_topics_with_gpt(original_topics)
        topics_of_interest = condensed
        print(f"[DEBUG] Condensed topics: {topics_of_interest}")
    except Exception as e:
        print(f"[WARN] Topic condensation failed: {e}")

    # Keep your legacy file if desired
    all_sessions_history.append(session_history)
    with open(ALL_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(all_sessions_history, f, indent=2)
    print(f"All sessions history saved to {ALL_HISTORY_FILE}")

    # Persist via the new class
    history.add_events(session_id, session_history)
    history.end_session(session_id,
                        completed_ids=completed_dialogs,
                        user_model=user_model,
                        topics_of_interest=topics_of_interest)
    history.save()
    print("Conversation state saved.")

    sys.exit()