"""
Minimal demo — runs entirely on your local machine without any cloud services.

Uses keyboard input (WrittenKeywordNLUProvider) so you can type replies in the terminal,
and NullTTSProvider so no audio setup is required.

Start Redis before running:
    conf/redis/redis-server.exe conf/redis/redis.conf
"""
import sys
from os.path import abspath, join

from sic_framework.devices.common_desktop.desktop_speakers import SpeakersConf
from sic_framework.devices.desktop import Desktop

from nardial.providers.device.desktop import DesktopAdapter
from nardial.providers.tts.null import NullTTSProvider
from nardial.providers.nlu.written_keyword import WrittenKeywordNLUProvider
from nardial.conversation_agent import ConversationAgent
from nardial.interaction_orchestrator import InteractionConfig
from nardial.session_manager import SessionManager

# setup key file paths
dialog_json_path = abspath(join("..", "examples", "dialogs.json"))

if __name__ == '__main__':
    # Select device
    desktop = Desktop(speakers_conf=SpeakersConf(sample_rate=22050))
    device = DesktopAdapter(desktop)
    # device = PepperAdapter(Pepper(ip="10.0.0.148"))

    # Create providers — swap NullTTSProvider for GoogleTTSProvider to enable speech output
    tts = NullTTSProvider()
    nlu = WrittenKeywordNLUProvider()

    # Create conversational agent
    interaction_config = InteractionConfig(post_speech_delay=0, signal_listening_behavior=False)
    agent = ConversationAgent(device=device, tts_provider=tts, nlu_provider=nlu, int_config=interaction_config)

    # all dialogs for now
    session_agenda = ["greeting", "hero_can_dream_1", "dream12", "goodbye"]

    session_manager = SessionManager(
        session_agenda=session_agenda,
        agent=agent,
        dialog_json_path=dialog_json_path,
        participant_id="1",
    )
    session_manager.run()

    sys.exit()
