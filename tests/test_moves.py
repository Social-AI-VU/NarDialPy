from unittest.mock import Mock

from nardial.mini_dialogs import MiniDialog, RunContext
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
    # Build a minimal agent with the same interface used by MiniDialog but mocked behaviors
    agent = Mock()
    agent.say = Mock()
    agent.ask_yesno = Mock(return_value='no')
    agent.ask_open = Mock(return_value='answer')
    agent.ask_options = Mock(return_value='dreaming')
    agent.play_audio = Mock()
    agent.play_motion_sequence = Mock()
    agent.play_animation = Mock()
    agent.personalize = Mock(return_value=None)
    return agent


def test_move_say():
    moves = [
        MoveSay(text="Testing Move Say..."),
        MoveSay(text="Testing Move Say Again..."),
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent(), context=RunContext())


def test_move_ask_yesno():
    set_variable = "likes_pineapple_pizza"
    moves = [
        MoveAskYesNo(
            text="Do you like pineapple on pizza?",
            add_interest="pizza",
            set_variable=set_variable,
        )
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent(), context=RunContext())

    assert set_variable in dialog.user_model


def test_move_ask_open():
    set_variable = "favorite_sea_thing"
    moves = [
        MoveAskOpen(
            text="What do you like most about the sea?",
            set_variable=set_variable,
            add_interest_from_answer=True,
        )
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent(), context=RunContext())

    assert set_variable in dialog.user_model


def test_move_ask_options():
    set_variable = "what_is_dreaming"
    moves = [
        MoveAskOptions(
            text="What is it called when you sleep and experience all sorts of things and then suddenly wake up?",
            options=["dreaming", "sleeping", "resting"],
            set_variable=set_variable,
        )
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent(), context=RunContext())

    assert set_variable in dialog.user_model


def test_move_play_audio():
    moves = [MovePlayAudio(audio="audio_test.wav")]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent(), context=RunContext())


def test_move_play_motion():
    moves = [MoveMotionSequence(motion_sequence="motion_test")]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent(), context=RunContext())


def test_move_animation():
    moves = [MoveAnimation(animation_name="animations/Stand/Gestures/No_1")]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent(), context=RunContext())
