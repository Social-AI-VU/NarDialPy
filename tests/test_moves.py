from os.path import abspath, join

from sic_framework.devices import Pepper
from sic_framework.devices.desktop import Desktop

from src.conversation_agent import ConversationAgent
from src.mini_dialogs import MiniDialog
from src.moves import MoveSay, MOVE_ASK_YESNO, MOVE_ASK_OPEN, MOVE_ASK_OPTIONS, MOVE_PLAY_AUDIO, MOVE_ANIMATION, \
    MOVE_MOTION_SEQUENCE


def mock_agent():
    device = Pepper(ip="10.0.0.148")
    google_keyfile_path = abspath(join("..", "conf", "dialogflow", "google_keyfile.json"))
    openai_key_path = abspath(join("..", "conf", "openai", ".openai_env"))
    return ConversationAgent(device_manager=device, google_keyfile_path=google_keyfile_path,
                             openai_key_path=openai_key_path)


def test_move_say():
    moves = [
        MoveSay(text="Testing Move Say..."),
        MoveSay(text="Testing Move Say Again..."),
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
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
    dialog = MiniDialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent())

    assert set_variable in dialog.user_model
    # TODO: find a way to assert that topics of interests have been updated if the user answers "yes"


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
    dialog = MiniDialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent())

    assert set_variable in dialog.user_model
    # TODO: find a way to assert that topics of interests have been updated with the user's answer


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
    dialog = MiniDialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent())

    assert set_variable in dialog.user_model
    # TODO: find a way to assert that topics of interests have been updated with the user's answer


def test_move_play_audio():
    moves = [
        {
            "type": MOVE_PLAY_AUDIO,
            "audio": "audio_test.wav"
        }
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent())


def test_move_play_motion():
    moves = [
        {
            "type": MOVE_MOTION_SEQUENCE,
            "motion_sequence": "motion_test"
        }
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent())


def test_move_animation():
    moves = [
        {
            "type": MOVE_ANIMATION,
            "animation_name": "animations/Stand/Gestures/No_1"
        }
    ]
    dialog = MiniDialog(dialog_id="1", moves=moves)
    dialog.run(agent=mock_agent())
