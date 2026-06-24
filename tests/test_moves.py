# Replace the heavy sic_framework device-based agent with a simple mock agent for tests
from unittest.mock import Mock, AsyncMock

import pytest

from nardial.mini_dialogs import MiniDialog
from nardial.moves import MoveSay, MOVE_SAY_OPTIONS, MOVE_ASK_YESNO, MOVE_ASK_OPEN, MOVE_ASK_OPTIONS, MOVE_PLAY_AUDIO, MOVE_ANIMATION, \
    MOVE_MOTION_SEQUENCE


def mock_agent():
    # Build a minimal agent with the same interface used by MiniDialog but mocked behaviors
    agent = Mock()
    agent.say = AsyncMock()
    agent.ask_yesno = AsyncMock(return_value='no')
    agent.ask_open = AsyncMock(return_value='answer')
    agent.ask_options = AsyncMock(return_value='dreaming')
    agent.play_audio = Mock()
    agent.play_motion_sequence = Mock()
    agent.play_animation = Mock()
    agent.personalize = Mock(return_value=None)
    return agent


@pytest.mark.asyncio
async def test_move_say():
    moves = [
        MoveSay(text="Testing Move Say..."),
        MoveSay(text="Testing Move Say Again..."),
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    await dialog.run(agent=mock_agent())


@pytest.mark.asyncio
async def test_move_say_options(monkeypatch):
    monkeypatch.setattr("nardial.mini_dialogs.random.choice", lambda seq: seq[1])
    moves = [
        {
            "type": MOVE_SAY_OPTIONS,
            "options": ["Testing Move Say...", "Testing Move Say Again..."],
        }
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    agent = mock_agent()
    await dialog.run(agent=agent)

    agent.say.assert_called_once_with("Testing Move Say Again...", voice_settings=None)


@pytest.mark.asyncio
async def test_move_ask_yesno():
    add_interest = "pizza"
    set_variable = "likes_pineapple_pizza"
    moves = [
        {
            "type": MOVE_ASK_YESNO,
            "text": "Do you like pineapple on pizza?",
            "add_interest": add_interest,
            "set_variable": set_variable
        }
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    await dialog.run(agent=mock_agent())

    assert set_variable in dialog.user_model


@pytest.mark.asyncio
async def test_move_ask_open():
    set_variable = "favorite_sea_thing"
    add_interest_from_answer = True
    moves = [
        {
            "type": MOVE_ASK_OPEN,
            "text": "What do you like most about the sea?",
            "set_variable": set_variable,
            "add_interest_from_answer": add_interest_from_answer
        }
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    await dialog.run(agent=mock_agent())

    assert set_variable in dialog.user_model


@pytest.mark.asyncio
async def test_move_ask_options():
    set_variable = "what_is_dreaming"
    moves = [
        {
            "type": MOVE_ASK_OPTIONS,
            "text": "What is it called when you sleep and experience all sorts of things and then suddenly wake up?",
            "options": ["dreaming", "sleeping", "resting"],
            "set_variable": set_variable
        }
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    await dialog.run(agent=mock_agent())

    assert set_variable in dialog.user_model


@pytest.mark.asyncio
async def test_move_play_audio():
    moves = [
        {
            "type": MOVE_PLAY_AUDIO,
            "audio": "audio_test.wav"
        }
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    await dialog.run(agent=mock_agent())


@pytest.mark.asyncio
async def test_move_play_motion():
    moves = [
        {
            "type": MOVE_MOTION_SEQUENCE,
            "motion_sequence": "motion_test"
        }
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    await dialog.run(agent=mock_agent())


@pytest.mark.asyncio
async def test_move_animation():
    moves = [
        {
            "type": MOVE_ANIMATION,
            "animation_name": "animations/Stand/Gestures/No_1"
        }
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    await dialog.run(agent=mock_agent())
