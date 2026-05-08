"""
=========================
Demo - Pre-run Setup
=========================
Before running this demo, make sure you have completed the required setup steps.
This demo depends on ElevenLabs for TTS, Dialogflow for NLU, and OpenAI for LLM responses.
-------------------------
1. Install dependencies
-------------------------
From the repository root:
    pip install -e .
    pip install --upgrade "social-interaction-cloud[elevenlabs,dialogflow,openai-gpt]"
-------------------------
2. Configure credentials
-------------------------
You MUST create the following files:

- Dialogflow / Google credentials: conf/dialogflow/google_keyfile.json
- OpenAI + ElevenLabs API keys: conf/.env
Example `.env` file:
    OPENAI_API_KEY="your key"
    ELEVENLABS_API_KEY="your key"

WARNING: Never commit these files to version control.
-------------------------
3. Configure ElevenLabs voice
-------------------------
Set your preferred voice by changing the ELEVENLABS_VOICE_ID constant below.
You can find available voice IDs in your ElevenLabs account or via their API.
The default is Rachel (a warm, clear English voice).
-------------------------
4. Start required services
-------------------------
You MUST run these in separate terminals BEFORE starting the demo:

    conf/redis/redis-server.exe conf/redis/redis.conf
    run-dialogflow
    run-elevenlabs-tts
    run-gpt
=========================
What this demo shows
=========================
This demo exercises the ElevenLabs TTS provider and the full LLM integration surface:

  - ElevenLabsTTSProvider with audio caching (TTSCacher)
  - llm_based dialog type (LLMDialog) — fully autonomous LLM conversation loop
    with speak_first, max_turns, and quit_phrases
  - ask_llm move within a scripted chitchat dialog — LLM generates the question
  - llm_followup on ask_open — inline LLM-generated response to the user's answer
  - %variable% substitution using creative_topic from the greeting dialog

Session flow (participant ID: "4"):
  1. creative_greeting  — ask_open with llm_followup; stores creative_topic
  2. free_creative_chat — llm_based: autonomous 4-turn creative conversation
  3. story_moment       — ask_llm generates a question; ask_open + branch on outcome
  4. creative_goodbye   — ask_llm gives personalised advice; fixed farewell say
=========================
"""
import json
import os
import sys
from os.path import abspath, join

from dotenv import load_dotenv
from sic_framework.devices.common_desktop.desktop_speakers import SpeakersConf
from sic_framework.devices.desktop import Desktop
from sic_framework.services.dialogflow.dialogflow import DialogflowConf
from sic_framework.services.elevenlabs_tts.elevenlabs_tts import ElevenLabsTTSConf

from nardial.providers.device.desktop import DesktopAdapter
from nardial.providers.tts.elevenlabs import ElevenLabsTTSProvider
from nardial.providers.tts.cacher import TTSCacher
from nardial.providers.nlu.dialogflow import DialogflowNLUProvider
from nardial.providers.llm.openai_gpt import OpenAIGPTProvider
from nardial.conversation_agent import ConversationAgent
from nardial.interaction_orchestrator import InteractionConfig
from nardial.session_manager import SessionManager

# Load OPENAI_API_KEY, ELEVENLABS_API_KEY, and other secrets from conf/.env
load_dotenv(abspath(join("..", "conf", ".env")))

# Path to your Google / Dialogflow credentials
google_keyfile_path = abspath(join("..", "conf", "google", "google_keyfile.json"))

# ElevenLabs voice configuration.
# Rachel (21m00Tcm4TlvDq8ikWAM) is a warm, clear English voice available on all plans.
# Browse voices at: https://elevenlabs.io/voice-library
ELEVENLABS_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"

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

    # --- TTS: ElevenLabs ---
    # ElevenLabsTTSProvider wraps the SIC ElevenLabs service.
    # TTSCacher stores synthesised audio to disk so repeated phrases are not re-synthesised
    # on subsequent runs — important when testing iteratively after changes.
    #
    # api_key must be passed explicitly: the service runs in a separate process where
    # dotenv is not loaded, so the key cannot be read from the environment there.
    # It is forwarded to the service via Redis as part of the conf object.
    elevenlabs_conf = ElevenLabsTTSConf(
        api_key=os.environ.get("ELEVENLABS_API_KEY"),
        voice_id=ELEVENLABS_VOICE_ID,
        model_id="eleven_flash_v2_5",  # current recommended model; "eleven_multilingual_v2" for multilingual
        speaking_rate=0.95,            # slightly slower than default for clarity (0.7–1.2)
    )
    tts = ElevenLabsTTSProvider(
        conf=elevenlabs_conf,
        device=device,
        tts_cacher=TTSCacher(tts_cache_dir=abspath(join("..", "examples", "tts_cache"))),
    )

    # --- NLU: Dialogflow ---
    # Handles both yes/no intents (for ask_yesno) and free-speech transcription
    # (for ask_open inside the LLM dialogs).
    dialogflow_conf = DialogflowConf(keyfile_json=json.load(open(google_keyfile_path)))
    nlu = DialogflowNLUProvider(conf=dialogflow_conf, mic=device.get_mic())

    # --- LLM: OpenAI GPT ---
    # Drives llm_followup inline responses, the ask_llm moves, and the llm_based dialog.
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
        int_config=interaction_config,
    )

    # =========================
    # 4. DEFINE SESSION
    # =========================
    # Each dialog ID must exist in elevenlabs_llm_dialogs.json.
    session_agenda = [
        "creative_greeting",   # functional/greeting — llm_followup on ask_open; stores creative_topic
        "free_creative_chat",  # llm_based — autonomous 4-turn LLM conversation loop
        "story_moment",        # chitchat — ask_llm generates a question; ask_open + branch
        "creative_goodbye",    # functional/farewell — ask_llm for personalised advice + fixed say
    ]

    # =========================
    # 5. RUN SESSION
    # =========================
    session_manager = SessionManager(
        session_agenda=session_agenda,
        agent=agent,
        dialog_json_path=abspath(join("..", "examples", "elevenlabs_llm_dialogs.json")),
        participant_id="4",
    )

    session_manager.run()

    # =========================
    # 6. CLEAN EXIT
    # =========================
    sys.exit()
