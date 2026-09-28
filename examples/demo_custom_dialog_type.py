"""
Custom Dialog Type Demo
=======================

Shows how to create your own dialog types and use them in a session.

A dialog type decides *when* its dialogs may run, through a list of
eligibility rules. You can make a new type by taking an existing one and
adding or removing rules. This demo does both of the things you usually
need for that:

1. Write your own rule in Python and register it under a name
   (`user_model_is`, below).
2. Define new dialog types in JSON, in a file of their own
   (dialog_types/custom_dialog_types.json):

   - `every_session_chitchat` extends `chitchat`. A normal chitchat dialog
     runs only once per participant, ever. This type swaps that rule for
     "once per session", so the dialog comes back every session.
   - `pet_owner_chitchat` extends `every_session_chitchat` and adds the
     custom rule, so its dialogs only run for participants who said they
     have a pet.

Dialogs then use the new type names as their `"type"`, with the same fields
as the type they extend (e.g. `topics`). The dialogs live in a separate file
(dialog_json/custom_dialog_type_dialogs.json): type definitions and dialogs
are never mixed in one file.

No cloud services are required: spoken text is printed to the terminal
(NullTTSProvider) and your answers are typed on the keyboard
(WrittenKeywordNLUProvider).

Setup
-----
1. Start Redis in a separate terminal:

       # Windows
       conf/redis/redis-server.exe conf/redis/redis.conf

       # macOS / Linux
       redis-server conf/redis/redis.conf

2. Run this script:

       python examples/demo_custom_dialog_type.py

3. Answer "yes" to the pet question and the robot asks about your pet.
   Answer "no" and that dialog is skipped. Run the script again: the
   `every_session_chitchat` dialogs (the pet question and the weather chat)
   run again, where normal chitchat dialogs would not.
"""

import sys
from pathlib import Path

from sic_framework.devices.desktop import Desktop

from nardial.conversation_agent import ConversationAgent
from nardial.dialog_types import get_dialog_type
from nardial.eligibility import EligibilityRule, register_rule
from nardial.providers.device.desktop import DesktopAdapter
from nardial.providers.nlu.written_keyword import WrittenKeywordNLUProvider
from nardial.providers.tts.null import NullTTSProvider
from nardial.session_manager import SessionManager

BASE_DIR = Path(__file__).resolve().parent
DIALOG_TYPES_PATH = BASE_DIR / "dialog_types" / "custom_dialog_types.json"
DIALOG_JSON_PATH = BASE_DIR / "dialog_json" / "custom_dialog_type_dialogs.json"


# =========================
# 1. A CUSTOM ELIGIBILITY RULE
# =========================
# A rule answers one question: may this dialog run right now? Registering it
# under a name lets JSON type definitions use it in "add_rules". The other
# keys of a rule spec in JSON are passed to the constructor, so
#     { "rule": "user_model_is", "variable": "has_pet", "value": "yes" }
# becomes UserModelIsRule(variable="has_pet", value="yes").
#
# Besides `context.user_model`, a rule can read `context.completed_ids`,
# `context.session_completed_ids`, `context.session_index` and
# `context.registry`. Keep rules stateless: one instance is shared by every
# dialog of the type.
@register_rule("user_model_is")
class UserModelIsRule(EligibilityRule):
    def __init__(self, variable, value):
        self.variable = variable
        self.value = value

    def is_eligible(self, dialog, context):
        return context.user_model.get(self.variable) == self.value

    # Optional: turns the rule back into its JSON form (used for printing below).
    def to_dict(self):
        return {**super().to_dict(), "variable": self.variable, "value": self.value}


if __name__ == "__main__":
    # =========================
    # 2. PROVIDERS (no cloud services needed)
    # =========================
    desktop = Desktop()
    device = DesktopAdapter(desktop)

    agent = ConversationAgent(
        device=device,
        tts_provider=NullTTSProvider(),
        nlu_provider=WrittenKeywordNLUProvider(),
    )

    # =========================
    # 3. THE SESSION AGENDA
    # =========================
    session_agenda = [
        "greeting",
        # Type every_session_chitchat: asked again in every session.
        "ask_pet",
        # Type pet_owner_chitchat: SessionManager checks the dialog's rules
        # before running it, so this is skipped unless you answered "yes".
        "pet_chat",
        # Custom types still count as their base type, so a chitchat slot
        # picks this every_session_chitchat dialog like any chitchat.
        {"type": "chitchat_slot", "topics_filter": ["weather"]},
        "farewell",
    ]

    # =========================
    # 4. LOAD AND RUN
    # =========================
    # SessionManager loads the type definitions from dialog_types_path first,
    # then the dialogs that use them from dialog_json_path. The rule above is
    # registered when this script is imported, so it exists before either.
    session_manager = SessionManager(
        session_agenda=session_agenda,
        agent=agent,
        dialog_types_path=str(DIALOG_TYPES_PATH),
        dialog_json_path=str(DIALOG_JSON_PATH),
        participant_id="custom_type_demo_participant",
    )

    for type_name in ("chitchat", "every_session_chitchat", "pet_owner_chitchat"):
        rules = [rule.to_dict() for rule in get_dialog_type(type_name).DEFAULT_ELIGIBILITY]
        print(f"[INFO] Rules of {type_name!r}: {rules}")

    session_manager.run()

    sys.exit()
