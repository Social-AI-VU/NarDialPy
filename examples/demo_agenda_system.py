"""
Agenda System Demo
===================

Demonstrates the full conversational agenda system: instead of a fixed
list of dialog ids, the session agenda below uses all five agenda-item
types (functional_slot, narrative_slot with repeat bounds, chitchat_slot,
llm_dialog_ref, and a plain dialog id) so SessionManager picks the right
dialog at each step based on eligibility rules, topic overlap, and story
order -- see docs/AGENDA_SYSTEM_GUIDE.md for a plain-language walkthrough
of every section below.

No cloud services are required: spoken text is printed to the terminal
(NullTTSProvider), NLU input is read from the keyboard
(WrittenKeywordNLUProvider), and the "LLM" for the campfire-stories
dialog is EchoLLMProvider, which just echoes back what you type -- enough
to see the multi-turn ask_llm loop working without needing API keys.

Setup
-----
1. Start Redis in a separate terminal:

       # Windows
       conf/redis/redis-server.exe conf/redis/redis.conf

       # macOS / Linux
       redis-server conf/redis/redis.conf

2. Run this script:

       python examples/demo_agenda_system.py

3. Type your replies in the terminal when prompted. For the campfire
   story exchange, type "stop" (or "bye" / "that's enough") to end it
   early instead of waiting for the turn limit.
"""

import sys
from pathlib import Path

from sic_framework.devices.desktop import Desktop

from nardial.providers.device.desktop import DesktopAdapter
from nardial.providers.tts.null import NullTTSProvider
from nardial.providers.nlu.written_keyword import WrittenKeywordNLUProvider
from nardial.providers.llm.echo import EchoLLMProvider
from nardial.conversation_agent import ConversationAgent
from nardial.session_manager import SessionManager

BASE_DIR = Path(__file__).resolve().parent
DIALOG_JSON_PATH = BASE_DIR / "dialog_json" / "agenda_system_dialogs.json"
SESSION_PLAN_PATH = BASE_DIR / "dialog_json" / "agenda_system_session_plan.json"

if __name__ == "__main__":
    # =========================
    # 1. PROVIDERS (no cloud services needed)
    # =========================
    desktop = Desktop()
    device = DesktopAdapter(desktop)

    tts = NullTTSProvider()
    nlu = WrittenKeywordNLUProvider()

    # EchoLLMProvider just returns your last message back to you -- it exists
    # so ask_llm/llm_based dialogs are demoable with zero setup. Swap in
    # OpenAIGPTProvider(api_key=...) for real LLM responses; nothing else in
    # this script needs to change.
    llm = EchoLLMProvider()

    # =========================
    # 2. CREATE THE CONVERSATION AGENT
    # =========================
    agent = ConversationAgent(
        device=device,
        tts_provider=tts,
        nlu_provider=nlu,
        llm_provider=llm,
    )

    # =========================
    # 3. THE SESSION AGENDA: all five agenda-item types
    # =========================
    # Each entry is either a plain dialog id (a DialogRef) or a dict that
    # coerce_agenda_item() turns into an AgendaItem. SessionManager resolves
    # this list one entry at a time via resolve_agenda(), checking each
    # dialog's eligibility rules as it goes.
    session_agenda = [
        # FunctionalSlot: picks a random eligible FunctionalDialog with
        # functional_type == "greeting". FunctionalDialog has no
        # ExcludeIfSeenRule, so greetings/farewells stay eligible every
        # session -- only DependencyMetRule applies to them.
        {"type": "functional_slot", "functional_type": "greeting"},

        # NarrativeSlot: picks the lowest-position not-yet-completed dialog
        # in the "camping_trip" thread (NarrativeOrderingRule +
        # ExcludeIfSeenRule + VariableDependencyMetRule). The thread has
        # three positions (camp_intro, camp_choice, camp_wrapup); a
        # SlotBounds(count_min=3, count_max=3) tells resolve_agenda() to
        # keep re-resolving this same slot until all three have run, rather
        # than the default "resolve exactly once".
        {
            "type": "narrative_slot",
            "thread": "camping_trip",
            "bounds": {"count_min": 3, "count_max": 3},
        },

        # ChitchatSlot: picks the eligible ChitchatDialog whose topics
        # overlap the most with topics_of_interest. camp_choice (above)
        # captured your answer as an interest via add_interest_from_answer,
        # so whichever of chitchat_hiking/chitchat_food/chitchat_weather
        # best matches what you said gets picked.
        #
        # Note: chitchat_food additionally declares
        # variable_dependencies: ["favorite_activity"] in the JSON -- had
        # camp_choice not run yet (and so favorite_activity not been set),
        # VariableDependencyMetRule would have excluded it from
        # consideration entirely, regardless of topic overlap.
        {"type": "chitchat_slot"},

        # LLMDialogRef: pins a specific LLMDialog by id, with optional
        # per-call overrides. The dialog is authored with max_turns: 3;
        # this slot overrides it down to 2 just for this run (a shallow
        # copy -- the original dialog in the registry is untouched).
        {"type": "llm_dialog_ref", "id": "campfire_stories", "max_turns": 2},

        # FunctionalSlot again, this time for functional_type == "summary".
        # trip_summary declares dependencies: ["campfire_stories"], so
        # DependencyMetRule keeps it ineligible until that dialog above has
        # actually completed -- which it has, by the time resolve_agenda()
        # reaches this entry.
        {"type": "functional_slot", "functional_type": "summary"},

        # A bare dialog id is a DialogRef -- it resolves to exactly that
        # dialog, ignoring eligibility entirely (SessionManager's final
        # is_dialog_eligible() safety-net check still applies before it
        # actually runs).
        "farewell",
    ]

    # =========================
    # 4. RUN THE SESSION
    # =========================
    session_manager = SessionManager(
        session_agenda=session_agenda,
        agent=agent,
        dialog_json_path=str(DIALOG_JSON_PATH),
        participant_id="agenda_demo_participant",
    )
    session_manager.run()

    sys.exit()

    # =========================
    # 5. ALTERNATIVE: a SessionPlan for multi-session arcs
    # =========================
    # Instead of a single fixed session_agenda, a SessionPlan picks a
    # different agenda per session number -- e.g. a full introduction the
    # first time a participant talks to you, and a lighter check-in from
    # then on. Uncomment this block (and remove the sys.exit() above) to
    # try it: run the script twice with the same participant_id and watch
    # session 2 use the shorter agenda from agenda_system_session_plan.json.
    #
    # session_manager = SessionManager(
    #     session_agenda=[],  # ignored: session_plan_path overrides it
    #     agent=agent,
    #     dialog_json_path=str(DIALOG_JSON_PATH),
    #     participant_id="agenda_demo_participant",
    #     session_plan_path=str(SESSION_PLAN_PATH),
    # )
    # session_manager.run()
    #
    # SessionManager also accepts session_index, reset_history_from_session,
    # and resume constructor parameters -- session-management concerns
    # (which session number you're on, discarding history, continuing after
    # a crash) rather than agenda-system ones, so they're intentionally left
    # out of this demo. See the SessionManager docstring for details.
