"""
=========================
Demo - Keyword shortcut for short answers
=========================
Asks four yes/no questions and one ask_options question, and prints after each answer how long
it took from the moment you stopped speaking until the dialog had the answer. Run it with and
without the shortcut to compare:

    python demo_keyword_shortcut.py                  # shortcut on (default)
    python demo_keyword_shortcut.py --no-shortcut    # Dialogflow decides on its own
    python demo_keyword_shortcut.py --english        # English questions and synonyms
    python demo_keyword_shortcut.py --null-tts       # print the questions instead of speaking them

With the shortcut, short answers ("ja", "nee", "weet ik niet", "ijs") are accepted about 0.3 s
after you stop speaking. Without it, Dialogflow often waits until the listen timeout (10 s).
Longer answers ("ja maar eigenlijk niet") always go to Dialogflow.

-------------------------
1. Install dependencies
-------------------------
From the repository root:
    pip install -e .
    pip install --upgrade "social-interaction-cloud[dialogflow,google-tts]"
-------------------------
2. Configure credentials
-------------------------
- Google credentials for a Dialogflow agent with the yesno_yes / yesno_no / yesno_dontknow intents
  (input context answer_yesno) and Text-to-Speech enabled: conf/google/google_keyfile.json
-------------------------
3. Start required services
-------------------------
In separate terminals, BEFORE starting the demo:

    conf/redis/redis-server.exe conf/redis/redis.conf
    run-dialogflow
    run-google-tts          (not needed with --null-tts)
=========================
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from sic_framework.devices.common_desktop.desktop_speakers import SpeakersConf
from sic_framework.devices.desktop import Desktop
from sic_framework.services.dialogflow.dialogflow import DialogflowConf

from nardial.conversation_agent import ConversationAgent
from nardial.interaction_orchestrator import InteractionConfig
from nardial.providers.device.desktop import DesktopAdapter
from nardial.providers.nlu.dialogflow import DialogflowNLUProvider
from nardial.providers.tts.google import GoogleTTSConf, GoogleTTSProvider
from nardial.providers.tts.null import NullTTSProvider

NARDIAL_ROOT = Path(__file__).resolve().parent.parent
GOOGLE_KEYFILE_PATH = NARDIAL_ROOT / "conf" / "google" / "google_keyfile.json"

QUESTIONS = {
    "nl": {
        "voice": "nl-NL-Standard-D",
        "yesno": ["Vind je honden leuk?", "Ben je vandaag al buiten geweest?", "Heb je honger?",
                  "Zullen we doorgaan?"],
        "options_question": "Wat eet je liever: ijs, taart of fruit?",
        "options": ["ijs", "taart", "fruit"],
    },
    "en": {
        "voice": "en-US-Neural2-C",
        "yesno": ["Do you like dogs?", "Have you been outside today?", "Are you hungry?", "Shall we continue?"],
        "options_question": "What would you rather eat: ice cream, cake or fruit?",
        "options": ["ice cream", "cake", "fruit"],
    },
}


class TimedDialogflowNLUProvider(DialogflowNLUProvider):
    """Dialogflow provider that remembers when the transcript last changed (roughly when you stopped speaking)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_change = None
        self._last_text = None

    def listen(self, *args, **kwargs):
        self.last_change, self._last_text = None, None
        return super().listen(*args, **kwargs)

    def _on_dialog(self, message):
        if message.response:
            text = message.response.recognition_result.transcript
            if text and text != self._last_text:
                self._last_text, self.last_change = text, time.monotonic()
        super()._on_dialog(message)


def report(nlu, answer):
    if nlu.last_change is None:
        print(f"==> answer: {answer!r} (no speech heard)\n")
    else:
        print(f"==> answer: {answer!r}, {time.monotonic() - nlu.last_change:.2f} s after you stopped speaking\n")


async def main(args):
    language = "en" if args.english else "nl"
    questions = QUESTIONS[language]

    device = DesktopAdapter(Desktop(speakers_conf=SpeakersConf(sample_rate=22050)))
    if args.null_tts:
        tts = NullTTSProvider()
    else:
        tts = GoogleTTSProvider(conf=GoogleTTSConf(google_tts_voice_name=questions["voice"]), device=device,
                                keyfile_path=str(GOOGLE_KEYFILE_PATH))
    dialogflow_conf = DialogflowConf(keyfile_json=json.load(open(GOOGLE_KEYFILE_PATH)), language=language)
    nlu = TimedDialogflowNLUProvider(conf=dialogflow_conf, mic=device.get_mic())

    agent = ConversationAgent(device=device, tts_provider=tts, nlu_provider=nlu, int_config=InteractionConfig(
        language=language,  # selects the Dutch or English yes/no synonyms
        keyword_shortcut=not args.no_shortcut,
        signal_listening_behavior=False,
    ))
    print(f"\n*** keyword shortcut {'OFF' if args.no_shortcut else 'ON'} ***\n")
    try:
        for question in questions["yesno"]:
            report(nlu, await agent.ask_yesno(question))
        report(nlu, await agent.ask_options(questions["options_question"], questions["options"], max_attempts=1))
    finally:
        agent.orchestrator.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare answering speed with and without the keyword shortcut.")
    parser.add_argument("--no-shortcut", action="store_true", help="turn the keyword shortcut off")
    parser.add_argument("--english", action="store_true", help="English questions and synonyms")
    parser.add_argument("--null-tts", action="store_true", help="print the questions instead of speaking them")
    asyncio.run(main(parser.parse_args()))
