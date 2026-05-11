"""
=========================
Demo - Pre-run Setup
=========================
Before running this demo, make sure you have completed the required setup steps.
This demo depends on external services for speech, language understanding, and LLM responses.
-------------------------
1. Install dependencies
-------------------------
From the repository root:
    pip install -e .
    pip install --upgrade "social-interaction-cloud[dialogflow,google-tts,openai-gpt]"
-------------------------
2. Configure credentials
-------------------------
You MUST create the following files:

- Dialogflow / Google credentials: conf/dialogflow/google_keyfile.json
- OpenAI API key: conf/.env
Example `.env` file:
    OPENAI_API_KEY="your key"

WARNING: Never commit these files to version control.
-------------------------
3. Start required services
-------------------------
You MUST run these in separate terminals BEFORE starting the demo:

    conf/redis/redis-server.exe conf/redis/redis.conf
    run-dialogflow
    run-google-tts
    run-gpt
=========================
What this demo shows
=========================
This demo exercises the full branching and intent-recognition pipeline:

  - ask_open, ask_yesno, and ask_options all feeding into branch moves
  - branch on outcome — up to a 5-way branch driven by Dialogflow intents
  - branch on variable — routing based on a value persisted from a prior dialog
  - Three levels of nested branching (branch → ask → branch → ask → branch)
  - Narrative thread with two sequential positions and variable_dependencies
  - %variable% substitution across dialogs
  - llm_followup on an open-ended question

Session flow (participant ID: "3"):
  1. profile_greeting    — collect name + lifestyle (outdoor / indoor)
  2. lifestyle_interests — 5-way hobby options, branch on both lifestyle variable and outcome
  3. hobby_deep_dive     — yesno + nested open question, then branch on lifestyle variable
  4. hobby_reflection    — ask_open with llm_followup; stores next_goal
  5. profile_goodbye     — personalised farewell with %first_name% and %hobby%
=========================
"""
import json
import sys
from os.path import abspath, join

from dotenv import load_dotenv
from sic_framework.devices.common_desktop.desktop_speakers import SpeakersConf
from sic_framework.devices.desktop import Desktop
from sic_framework.services.dialogflow.dialogflow import DialogflowConf

from nardial.providers.device.desktop import DesktopAdapter
from nardial.providers.tts.google import GoogleTTSProvider, GoogleTTSConf
from nardial.providers.nlu.dialogflow import DialogflowNLUProvider
from nardial.providers.llm.openai_gpt import OpenAIGPTProvider
from nardial.conversation_agent import ConversationAgent
from nardial.interaction_orchestrator import InteractionConfig
from nardial.session_manager import SessionManager

# Load OPENAI_API_KEY and other secrets from conf/.env
load_dotenv(abspath(join("..", "conf", ".env")))

# Path to your Google / Dialogflow credentials
google_keyfile_path = abspath(join("..", "conf", "google", "google_keyfile.json"))

if __name__ == '__main__':
    # =========================
    # 1. SELECT DEVICE
    # =========================
    desktop = Desktop(
        speakers_conf=SpeakersConf(
            sample_rate=22050
        )
    )
    device = DesktopAdapter(desktop)

    # Uncomment to use Pepper instead:
    # from nardial.providers.device.pepper import PepperAdapter
    # from sic_framework.devices import Pepper
    # device = PepperAdapter(Pepper(ip="10.0.0.148"))

    # =========================
    # 2. CONFIGURE PROVIDERS
    # =========================

    # --- TTS ---
    tts_conf = GoogleTTSConf(
        # speaking_rate=1.0,
        # google_tts_voice_name="en-US-Neural2-C",
    )
    tts = GoogleTTSProvider(conf=tts_conf, device=device, keyfile_path=google_keyfile_path)

    # --- NLU ---
    # Dialogflow detects intents from live speech — required for branching on
    # ask_yesno (yes/no/dontknow intents) and ask_options (option-matched intents).
    dialogflow_conf = DialogflowConf(keyfile_json=json.load(open(google_keyfile_path)))
    nlu = DialogflowNLUProvider(conf=dialogflow_conf, mic=device.get_mic())

    # --- LLM ---
    # Required by hobby_reflection's llm_followup to generate a personalised
    # encouraging response after the user shares their next goal.
    # Reads OPENAI_API_KEY from the environment (loaded via dotenv above).
    llm = OpenAIGPTProvider()

    # --- Behavioral config ---
    interaction_config = InteractionConfig(
        # language="nl",          # change Dialogflow language context
        # post_speech_delay=0.5,  # pause after agent speech (seconds)
    )

    # =========================
    # 3. CREATE AGENT
    # =========================
    agent = ConversationAgent(
        device=device,
        tts_provider=tts,
        nlu_provider=nlu,
        llm_provider=llm,
        interaction_config=interaction_config,
    )

    # =========================
    # 4. DEFINE SESSION
    # =========================
    # Each dialog ID must exist in branching_dialogflow_dialogs.json.
    # The agenda runs in order; eligibility checks (dependencies, variable_dependencies)
    # are enforced by the session manager before each dialog runs.
    session_agenda = [
        "profile_greeting",     # functional/greeting — sets first_name and lifestyle
        "lifestyle_interests",  # chitchat — branch on lifestyle variable, 5-way outcome branch
        "hobby_deep_dive",      # narrative thread=hobbies pos=1 — nested branch + branch on lifestyle
        "hobby_reflection",     # narrative thread=hobbies pos=2 — ask_open with llm_followup
        "profile_goodbye",      # functional/farewell — %first_name% and %hobby% substitution
    ]

    # =========================
    # 5. RUN SESSION
    # =========================
    session_manager = SessionManager(
        session_agenda=session_agenda,
        agent=agent,
        dialog_json_path=abspath(join("..", "examples", "branching_dialogflow_dialogs.json")),
        participant_id="3",
    )

    session_manager.run()

    # =========================
    # 6. CLEAN EXIT
    # =========================
    sys.exit()
