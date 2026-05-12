"""Integration tests for branch-move routing inside a full SessionManager run.

These tests verify that outcome-driven and variable-driven branch moves
correctly route through a live dialog execution, including the full
SessionManager → MiniDialog → Move chain.

No Redis or SIC services are required.

Run with::

    pytest tests/integration/test_branch_session.py --integration
"""
import json
import pytest
from unittest.mock import AsyncMock, Mock

from nardial.session_manager import SessionManager


# ── Dialog fixtures ───────────────────────────────────────────────────────────

BRANCH_ON_YESNO = [
    {
        "id": "sports_quiz",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [
            {
                "type": "ask_yesno",
                "text": "Do you enjoy sports?",
                "set_variable": "likes_sports",
                "outcomes": {"yes": "sports_yes", "no": "sports_no"},
                "default_outcome": "sports_no",
            },
            {
                "type": "branch",
                "on": "outcome",
                "cases": {
                    "sports_yes": [{"type": "say", "text": "Great, sports are fun!"}],
                    "sports_no": [{"type": "say", "text": "That's okay too."}],
                },
            },
            {"type": "say", "text": "Thanks for sharing."},
        ],
    },
]

BRANCH_ON_VARIABLE = [
    {
        "id": "mood_check",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [
            {
                "type": "ask_open",
                "text": "How are you feeling today?",
                "set_variable": "mood",
            },
            {
                "type": "branch",
                "on": "mood",
                "cases": {
                    "happy": [{"type": "say", "text": "Wonderful!"}],
                    "sad": [{"type": "say", "text": "I'm sorry to hear that."}],
                },
            },
        ],
    },
]

NESTED_BRANCH = [
    {
        "id": "nested",
        "type": "functional",
        "functional_type": "greeting",
        "moves": [
            {
                "type": "ask_yesno",
                "text": "Outer question?",
                "outcomes": {"yes": "outer_yes"},
                "default_outcome": "outer_no",
            },
            {
                "type": "branch",
                "on": "outcome",
                "cases": {
                    "outer_yes": [
                        {
                            "type": "ask_yesno",
                            "text": "Inner question?",
                            "outcomes": {"yes": "inner_yes"},
                            "default_outcome": "inner_no",
                        },
                        {
                            "type": "branch",
                            "on": "outcome",
                            "cases": {
                                "inner_yes": [{"type": "say", "text": "Both yes!"}],
                                "inner_no": [{"type": "say", "text": "Outer yes, inner no."}],
                            },
                        },
                    ],
                    "outer_no": [{"type": "say", "text": "Outer no."}],
                },
            },
        ],
    },
]


@pytest.fixture
def sports_dialogs_file(tmp_path):
    p = tmp_path / "sports.json"
    p.write_text(json.dumps(BRANCH_ON_YESNO))
    return str(p)


@pytest.fixture
def mood_dialogs_file(tmp_path):
    p = tmp_path / "mood.json"
    p.write_text(json.dumps(BRANCH_ON_VARIABLE))
    return str(p)


@pytest.fixture
def nested_dialogs_file(tmp_path):
    p = tmp_path / "nested.json"
    p.write_text(json.dumps(NESTED_BRANCH))
    return str(p)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBranchOnOutcome:
    def test_yes_answer_routes_to_yes_arm(self, sports_dialogs_file):
        agent = Mock()
        agent.say = AsyncMock()
        agent.ask_yesno = AsyncMock(return_value="yes")
        agent.ask_open = AsyncMock(return_value=None)
        agent.ask_options = Mock(return_value=None)
        agent.extract_topics_with_llm = AsyncMock(return_value=[])

        sm = SessionManager(
            session_agenda=["sports_quiz"],
            agent=agent,
            dialog_json_path=sports_dialogs_file,
        )
        sm.run()

        spoken = [c.args[0] for c in agent.say.call_args_list]
        assert "Great, sports are fun!" in spoken
        assert "That's okay too." not in spoken
        assert "Thanks for sharing." in spoken

    def test_no_answer_routes_to_no_arm(self, sports_dialogs_file):
        agent = Mock()
        agent.say = AsyncMock()
        agent.ask_yesno = AsyncMock(return_value="no")
        agent.ask_open = AsyncMock(return_value=None)
        agent.ask_options = Mock(return_value=None)
        agent.extract_topics_with_llm = AsyncMock(return_value=[])

        sm = SessionManager(
            session_agenda=["sports_quiz"],
            agent=agent,
            dialog_json_path=sports_dialogs_file,
        )
        sm.run()

        spoken = [c.args[0] for c in agent.say.call_args_list]
        assert "That's okay too." in spoken
        assert "Great, sports are fun!" not in spoken

    def test_no_matching_arm_speaks_nothing_for_branch(self, sports_dialogs_file):
        """An answer that maps to a default_outcome not present in cases is silent."""
        agent = Mock()
        agent.say = AsyncMock()
        agent.ask_yesno = AsyncMock(return_value="dontknow")  # → default "sports_no"
        agent.ask_open = AsyncMock(return_value=None)
        agent.ask_options = Mock(return_value=None)
        agent.extract_topics_with_llm = AsyncMock(return_value=[])

        sm = SessionManager(
            session_agenda=["sports_quiz"],
            agent=agent,
            dialog_json_path=sports_dialogs_file,
        )
        sm.run()

        spoken = [c.args[0] for c in agent.say.call_args_list]
        # "dontknow" → default_outcome "sports_no" → branch arm "sports_no" fires
        assert "That's okay too." in spoken


class TestBranchOnUserModelVariable:
    def test_happy_mood_routes_to_happy_arm(self, mood_dialogs_file):
        agent = Mock()
        agent.say = AsyncMock()
        agent.ask_yesno = AsyncMock(return_value="yes")
        agent.ask_open = AsyncMock(return_value="'happy'")  # extract_open_value → "happy"
        agent.ask_options = Mock(return_value=None)
        agent.extract_topics_with_llm = AsyncMock(return_value=[])

        sm = SessionManager(
            session_agenda=["mood_check"],
            agent=agent,
            dialog_json_path=mood_dialogs_file,
        )
        sm.run()

        spoken = [c.args[0] for c in agent.say.call_args_list]
        assert "Wonderful!" in spoken
        assert "I'm sorry to hear that." not in spoken

    def test_sad_mood_routes_to_sad_arm(self, mood_dialogs_file):
        agent = Mock()
        agent.say = AsyncMock()
        agent.ask_yesno = AsyncMock(return_value="yes")
        agent.ask_open = AsyncMock(return_value="'sad'")
        agent.ask_options = Mock(return_value=None)
        agent.extract_topics_with_llm = AsyncMock(return_value=[])

        sm = SessionManager(
            session_agenda=["mood_check"],
            agent=agent,
            dialog_json_path=mood_dialogs_file,
        )
        sm.run()

        spoken = [c.args[0] for c in agent.say.call_args_list]
        assert "I'm sorry to hear that." in spoken
        assert "Wonderful!" not in spoken

    def test_unknown_mood_is_silent(self, mood_dialogs_file):
        """A variable value with no matching case produces no extra speech."""
        agent = Mock()
        agent.say = AsyncMock()
        agent.ask_yesno = AsyncMock(return_value="yes")
        agent.ask_open = AsyncMock(return_value="'indifferent'")
        agent.ask_options = Mock(return_value=None)
        agent.extract_topics_with_llm = AsyncMock(return_value=[])

        sm = SessionManager(
            session_agenda=["mood_check"],
            agent=agent,
            dialog_json_path=mood_dialogs_file,
        )
        sm.run()

        spoken = [c.args[0] for c in agent.say.call_args_list]
        assert "Wonderful!" not in spoken
        assert "I'm sorry to hear that." not in spoken


class TestNestedBranch:
    def test_both_yes_reaches_inner_yes_arm(self, nested_dialogs_file):
        agent = Mock()
        agent.say = AsyncMock()
        agent.ask_yesno = AsyncMock(return_value="yes")  # both outer and inner answer "yes"
        agent.ask_open = AsyncMock(return_value=None)
        agent.ask_options = Mock(return_value=None)
        agent.extract_topics_with_llm = AsyncMock(return_value=[])

        sm = SessionManager(
            session_agenda=["nested"],
            agent=agent,
            dialog_json_path=nested_dialogs_file,
        )
        sm.run()

        spoken = [c.args[0] for c in agent.say.call_args_list]
        assert "Both yes!" in spoken

    def test_outer_no_skips_inner_branch(self, nested_dialogs_file):
        agent = Mock()
        agent.say = AsyncMock()
        agent.ask_yesno = AsyncMock(return_value="no")
        agent.ask_open = AsyncMock(return_value=None)
        agent.ask_options = Mock(return_value=None)
        agent.extract_topics_with_llm = AsyncMock(return_value=[])

        sm = SessionManager(
            session_agenda=["nested"],
            agent=agent,
            dialog_json_path=nested_dialogs_file,
        )
        sm.run()

        spoken = [c.args[0] for c in agent.say.call_args_list]
        assert "Outer no." in spoken
        assert "Both yes!" not in spoken
        assert "Outer yes, inner no." not in spoken
