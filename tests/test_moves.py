import pytest
from pydantic import ValidationError
from unittest.mock import AsyncMock, MagicMock

from nardial.dialog_runtime import DialogRuntime, RunContext
from nardial.mini_dialogs import ScriptedMiniDialog
from nardial.moves import (
    MoveSay,
    MoveAskYesNo,
    MoveAskOpen,
    MoveAskOptions,
    MovePlayAudio,
    MoveAnimation,
    MoveMotionSequence,
    MoveWaitForButton,
    MoveTimedWait,
    MoveWaitForWebInput,
)


def mock_agent():
    """Build a minimal async mock agent for DialogRuntime tests."""
    agent = MagicMock()
    agent.say = AsyncMock()
    agent.ask_yesno = AsyncMock(return_value='no')
    agent.ask_open = AsyncMock(return_value='answer')
    agent.ask_options = AsyncMock(return_value='dreaming')
    agent.play_audio = MagicMock()
    agent.play_motion_sequence = MagicMock()
    agent.play_animation = MagicMock()
    agent.personalize = MagicMock(return_value=None)
    return agent


async def test_move_say():
    moves = [
        MoveSay(text="Testing Move Say..."),
        MoveSay(text="Testing Move Say Again..."),
    ]
    dialog = ScriptedMiniDialog(dialog_id="1", moves=moves)
    await DialogRuntime(mock_agent()).run(dialog, RunContext())


async def test_move_ask_yesno():
    set_variable = "likes_pineapple_pizza"
    moves = [
        MoveAskYesNo(
            text="Do you like pineapple on pizza?",
            add_interest="pizza",
            set_variable=set_variable,
        )
    ]
    dialog = ScriptedMiniDialog(dialog_id="1", moves=moves)
    context = RunContext()
    await DialogRuntime(mock_agent()).run(dialog, context)

    assert set_variable in context.user_model


async def test_move_ask_open():
    set_variable = "favorite_sea_thing"
    moves = [
        MoveAskOpen(
            text="What do you like most about the sea?",
            set_variable=set_variable,
            add_interest_from_answer=True,
        )
    ]
    dialog = ScriptedMiniDialog(dialog_id="1", moves=moves)
    context = RunContext()
    await DialogRuntime(mock_agent()).run(dialog, context)

    assert set_variable in context.user_model


async def test_move_ask_options():
    set_variable = "what_is_dreaming"
    moves = [
        MoveAskOptions(
            text="What is it called when you sleep and experience all sorts of things and then suddenly wake up?",
            options=["dreaming", "sleeping", "resting"],
            set_variable=set_variable,
        )
    ]
    dialog = ScriptedMiniDialog(dialog_id="1", moves=moves)
    context = RunContext()
    await DialogRuntime(mock_agent()).run(dialog, context)

    assert set_variable in context.user_model


async def test_move_play_audio():
    moves = [MovePlayAudio(audio="audio_test.wav")]
    dialog = ScriptedMiniDialog(dialog_id="1", moves=moves)
    await DialogRuntime(mock_agent()).run(dialog, RunContext())


async def test_move_play_motion():
    moves = [MoveMotionSequence(motion_sequence="motion_test")]
    dialog = ScriptedMiniDialog(dialog_id="1", moves=moves)
    await DialogRuntime(mock_agent()).run(dialog, RunContext())


async def test_move_animation():
    moves = [MoveAnimation(animation_name="animations/Stand/Gestures/No_1")]
    dialog = ScriptedMiniDialog(dialog_id="1", moves=moves)
    await DialogRuntime(mock_agent()).run(dialog, RunContext())


async def test_move_say_substitutes_user_model_variables():
    """%var% placeholders in say text should be replaced with user_model values."""
    moves = [MoveSay(text="Hello, %name%! You are %age% years old.")]
    dialog = ScriptedMiniDialog(dialog_id="1", moves=moves)
    agent = mock_agent()
    context = RunContext(user_model={"name": "Alice", "age": "30"})
    await DialogRuntime(agent).run(dialog, context)
    agent.say.assert_called_once_with("Hello, Alice! You are 30 years old.")


async def test_move_ask_yesno_interest_not_added_when_answer_is_no():
    """add_interest should only be recorded when the user answers 'yes'."""
    context = RunContext()
    agent = mock_agent()
    agent.ask_yesno = AsyncMock(return_value="no")

    moves = [MoveAskYesNo(text="Do you like pizza?", add_interest="pizza")]
    dialog = ScriptedMiniDialog(dialog_id="1", moves=moves)
    await DialogRuntime(agent).run(dialog, context)

    assert "pizza" not in context.topics_of_interest


# ---------------------------------------------------------------------------
# Pydantic validation tests for new event wait move types
# ---------------------------------------------------------------------------

class TestMoveWaitForButton:
    def test_defaults(self):
        m = MoveWaitForButton(buttons=["chest_button"])
        assert m.type == "wait_for_button"
        assert m.buttons == ["chest_button"]
        assert m.timeout is None
        assert m.outcomes == {}
        assert m.default_outcome == "timeout"

    def test_with_all_fields(self):
        m = MoveWaitForButton(
            buttons=["chest_button", "head_middle"],
            timeout=30.0,
            outcomes={"chest_button": "path_a", "head_middle": "path_b"},
            default_outcome="no_press",
        )
        assert m.timeout == 30.0
        assert m.outcomes["chest_button"] == "path_a"
        assert m.default_outcome == "no_press"

    def test_requires_buttons(self):
        with pytest.raises(ValidationError):
            MoveWaitForButton()


class TestMoveTimedWait:
    def test_basic(self):
        m = MoveTimedWait(duration_seconds=5.0)
        assert m.type == "timed_wait"
        assert m.duration_seconds == 5.0

    def test_requires_duration(self):
        with pytest.raises(ValidationError):
            MoveTimedWait()

    def test_integer_duration_coerced_to_float(self):
        m = MoveTimedWait(duration_seconds=3)
        assert isinstance(m.duration_seconds, float)


class TestMoveWaitForWebInput:
    def test_defaults(self):
        m = MoveWaitForWebInput()
        assert m.type == "wait_for_web_input"
        assert m.prompt == ""
        assert m.options == []
        assert m.timeout is None
        assert m.outcomes == {}
        assert m.default_outcome == "timeout"

    def test_with_all_fields(self):
        m = MoveWaitForWebInput(
            prompt="Choose an option",
            options=["yes", "no"],
            timeout=60.0,
            outcomes={"yes": "confirmed", "no": "declined"},
            default_outcome="timed_out",
        )
        assert m.prompt == "Choose an option"
        assert m.options == ["yes", "no"]
        assert m.timeout == 60.0
        assert m.outcomes["no"] == "declined"
        assert m.default_outcome == "timed_out"
