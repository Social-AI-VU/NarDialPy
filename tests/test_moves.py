from unittest.mock import AsyncMock, MagicMock

from nardial.dialog_runtime import DialogRuntime, RunContext
from nardial.mini_dialogs import MiniDialog
from nardial.moves import (
    MoveSay,
    MoveAskYesNo,
    MoveAskOpen,
    MoveAskOptions,
    MovePlayAudio,
    MoveAnimation,
    MoveMotionSequence,
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
    dialog = MiniDialog(dialog_id="1", moves=moves)
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
    dialog = MiniDialog(dialog_id="1", moves=moves)
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
    dialog = MiniDialog(dialog_id="1", moves=moves)
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
    dialog = MiniDialog(dialog_id="1", moves=moves)
    context = RunContext()
    await DialogRuntime(mock_agent()).run(dialog, context)

    assert set_variable in context.user_model


async def test_move_play_audio():
    moves = [MovePlayAudio(audio="audio_test.wav")]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    await DialogRuntime(mock_agent()).run(dialog, RunContext())


async def test_move_play_motion():
    moves = [MoveMotionSequence(motion_sequence="motion_test")]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    await DialogRuntime(mock_agent()).run(dialog, RunContext())


async def test_move_animation():
    moves = [MoveAnimation(animation_name="animations/Stand/Gestures/No_1")]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    await DialogRuntime(mock_agent()).run(dialog, RunContext())


async def test_move_say_substitutes_user_model_variables():
    """%var% placeholders in say text should be replaced with user_model values."""
    moves = [MoveSay(text="Hello, %name%! You are %age% years old.")]
    dialog = MiniDialog(dialog_id="1", moves=moves)
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
    dialog = MiniDialog(dialog_id="1", moves=moves)
    await DialogRuntime(agent).run(dialog, context)

    assert "pizza" not in context.topics_of_interest
