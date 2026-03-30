from os.path import abspath, join

# Replace the heavy sic_framework device-based agent with a simple mock agent for tests
from unittest.mock import Mock

from src.conversation_agent import ConversationAgent
from src.dialogs import Dialog
from src.moves import MoveSay, MOVE_ASK_YESNO, MOVE_ASK_OPEN, MOVE_ASK_OPTIONS, MOVE_PLAY_AUDIO, MOVE_ANIMATION, \
    MOVE_MOTION_SEQUENCE


def mock_agent():
    # Build a minimal agent with the same interface used by MiniDialog but mocked behaviors
    agent = Mock()
    agent.say = Mock()
    agent.ask_yes_no = Mock(return_value='no')
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
    dialog = Dialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent())


def test_move_ask_yesno():
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
    dialog = Dialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent())

    assert set_variable in dialog.user_model


def test_move_ask_open():
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
    dialog = Dialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent())

    assert set_variable in dialog.user_model


def test_move_ask_options():
    set_variable = "what_is_dreaming"
    moves = [
        {
            "type": MOVE_ASK_OPTIONS,
            "text": "What is it called when you sleep and experience all sorts of things and then suddenly wake up?",
            "options": ["dreaming", "sleeping", "resting"],
            "set_variable": set_variable
        }
    ]
    dialog = Dialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent())

    assert set_variable in dialog.user_model


def test_move_play_audio():
    moves = [
        {
            "type": MOVE_PLAY_AUDIO,
            "audio": "audio_test.wav"
        }
    ]
    dialog = Dialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent())


def test_move_play_motion():
    moves = [
        {
            "type": MOVE_MOTION_SEQUENCE,
            "motion_sequence": "motion_test"
        }
    ]
    dialog = Dialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent())


def test_move_animation():
    moves = [
        {
            "type": MOVE_ANIMATION,
            "animation_name": "animations/Stand/Gestures/No_1"
        }
    ]
    dialog = Dialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent())
