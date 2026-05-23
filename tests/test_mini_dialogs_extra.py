import pytest

from nardial.mini_dialogs import MiniDialog
from nardial.moves import MoveAskLLM, MoveBranch, MOVE_ASK_LLM, MOVE_ANSWER_LLM


class _ElevenLabsTTSConfMock:
    def __init__(self):
        self.voice_id = "default_voice"
        self.model_id = "eleven_flash_v2_5"
        self.speaking_rate = 1.0


class _GoogleTTSConfMock:
    def __init__(self):
        self.google_tts_voice_name = "en-US-Standard-C"
        self.google_tts_voice_gender = "FEMALE"
        self.speaking_rate = 1.0


def test_extract_open_value_quotes_and_tokens():
    # Quoted content should be preferred
    assert MiniDialog.extract_open_value("I love 'apples' so much") == 'apples'
    assert MiniDialog.extract_open_value('She said "banana" is nice') == 'banana'

    # Last alphabetic token should be returned when no quotes
    assert MiniDialog.extract_open_value('My favorite animal is a zebra') == 'zebra'

    # If no alphabetic tokens, return trimmed original
    assert MiniDialog.extract_open_value('  12345  ') == '12345'


def test_run_llm_exchange_retries_on_none(session_history, user_model, topics_of_interest, make_mock_agent):
    # ask_llm returns None first (simulating transient LLM failure), then returns text
    agent = make_mock_agent(ask_llm_side_effect=[None, 'Hello LLM'], ask_open_side_effect=['hi'])
    md = MiniDialog('test', moves=[])
    md.set_conversation_config(agent, session_history, topics_of_interest, user_model)

    md._run_llm_exchange(prompt='p', max_turns=3)

    # ask_llm retried until a non-None response
    assert agent.ask_llm.call_count >= 2
    # listen should be called at least once (the LLM may prompt multiple times up to max_turns)
    assert agent.orchestrator.listen.call_count >= 1

    # session history should have at least one ask_llm and one answer entry
    types = [e['type'] for e in session_history]
    assert MOVE_ASK_LLM in types
    assert MOVE_ANSWER_LLM in types


def test_handle_move_ask_llm_from_dict_sets_variable(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(ask_llm_side_effect=['Q1'], ask_open_side_effect=["I like turtles"])
    md = MiniDialog('test', moves=[])
    md.set_conversation_config(agent, session_history, topics_of_interest, user_model)

    move_dict = {'prompt': 'Tell me something', 'max_turns': 1, 'set_variable': 'pet'}
    # handle_move_ask_llm accepts a dict and internally uses MoveAskLLM.from_dict
    md.handle_move_ask_llm(move_dict)

    # The user's answer should be stored under the set variable using extractor heuristics
    assert 'pet' in user_model
    assert user_model['pet'] in ('turtles', 'I like turtles')


# ---------------------------------------------------------------------------
# New declarative branching tests
# ---------------------------------------------------------------------------

def _make_mock_agent(ask_options_return='dreaming', ask_yesno_return='yes', ask_open_return='something'):
    from unittest.mock import Mock
    agent = Mock()
    agent.say = Mock()
    agent.ask_options = Mock(return_value=ask_options_return)
    agent.ask_yesno = Mock(return_value=ask_yesno_return)
    agent.ask_open = Mock(return_value=ask_open_return)
    agent.play_audio = Mock()
    agent.play_motion_sequence = Mock()
    agent.play_animation = Mock()
    agent.personalize = Mock(return_value=None)
    orchestrator = Mock()
    orchestrator.listen = Mock(return_value=(ask_open_return, None))
    agent.orchestrator = orchestrator
    return agent


def test_move_branch_class_from_dict():
    data = {
        "type": "branch",
        "on": "outcome",
        "cases": {
            "correct": [{"type": "say", "text": "Well done!"}],
            "incorrect": [{"type": "say", "text": "Not quite."}],
        }
    }
    mb = MoveBranch.from_dict(data)
    assert mb.on == "outcome"
    assert "correct" in mb.cases
    assert mb.cases["incorrect"][0]["text"] == "Not quite."


def test_resolve_outcome_with_outcomes_dict(session_history, user_model, topics_of_interest):
    """_resolve_outcome stores the matching outcome label from the outcomes dict."""
    agent = _make_mock_agent()
    md = MiniDialog('test', moves=[])
    md.set_conversation_config(agent, session_history, topics_of_interest, user_model)

    move = {"type": "ask_options", "text": "q", "options": ["a", "b"],
            "outcomes": {"a": "branch_a", "b": "branch_b"}, "default_outcome": "branch_b"}

    md._resolve_outcome(move, "a")
    assert md.current_outcome == "branch_a"

    md._resolve_outcome(move, "b")
    assert md.current_outcome == "branch_b"


def test_resolve_outcome_falls_back_to_default(session_history, user_model, topics_of_interest):
    """When the answer doesn't appear in outcomes, default_outcome is used."""
    agent = _make_mock_agent()
    md = MiniDialog('test', moves=[])
    md.set_conversation_config(agent, session_history, topics_of_interest, user_model)

    move = {"type": "ask_options", "text": "q", "options": ["a"],
            "outcomes": {"a": "branch_a"}, "default_outcome": "branch_default"}

    md._resolve_outcome(move, None)
    assert md.current_outcome == "branch_default"

    md._resolve_outcome(move, "unknown_value")
    assert md.current_outcome == "branch_default"


def test_handle_move_branch_executes_correct_case(session_history, user_model, topics_of_interest):
    """handle_move_branch runs the sub-moves for the active current_outcome."""
    agent = _make_mock_agent()
    md = MiniDialog('test', moves=[])
    md.set_conversation_config(agent, session_history, topics_of_interest, user_model)
    md.current_outcome = "correct"

    move = {
        "type": "branch",
        "on": "outcome",
        "cases": {
            "correct": [{"type": "say", "text": "Correct!"}],
            "incorrect": [{"type": "say", "text": "Wrong!"}],
        }
    }
    md.handle_move_branch(move)

    # Only the "correct" sub-move should have been spoken
    agent.say.assert_called_once_with("Correct!")


def test_handle_move_branch_unknown_case_is_silent(session_history, user_model, topics_of_interest):
    """handle_move_branch does nothing when current_outcome matches no case."""
    agent = _make_mock_agent()
    md = MiniDialog('test', moves=[])
    md.set_conversation_config(agent, session_history, topics_of_interest, user_model)
    md.current_outcome = "other"

    move = {
        "type": "branch",
        "on": "outcome",
        "cases": {
            "correct": [{"type": "say", "text": "Correct!"}],
        }
    }
    md.handle_move_branch(move)
    agent.say.assert_not_called()


def test_full_dialog_new_branching_ask_options(session_history, user_model, topics_of_interest):
    """End-to-end: ask_options with outcomes routes into the correct branch case."""
    agent = _make_mock_agent(ask_options_return='dreaming')
    moves = [
        {
            "type": "ask_options",
            "text": "What is dreaming?",
            "options": ["dreaming", "sleeping", "resting"],
            "set_variable": "what_is_dreaming",
            "outcomes": {
                "dreaming": "correct",
                "sleeping": "incorrect",
                "resting": "incorrect",
            },
            "default_outcome": "incorrect",
        },
        {
            "type": "branch",
            "on": "outcome",
            "cases": {
                "correct": [{"type": "say", "text": "Indeed, dreaming."}],
                "incorrect": [{"type": "say", "text": "This is called dreaming!"}],
            },
        },
        {"type": "say", "text": "Continuing the dialog."},
    ]
    md = MiniDialog('test', moves=moves)
    md.run(agent, session_history, topics_of_interest, user_model)

    assert md.current_outcome == "correct"
    texts_spoken = [call.args[0] for call in agent.say.call_args_list]
    assert "Indeed, dreaming." in texts_spoken
    assert "This is called dreaming!" not in texts_spoken
    assert "Continuing the dialog." in texts_spoken
    assert user_model.get("what_is_dreaming") == "dreaming"


def test_full_dialog_new_branching_ask_options_default(session_history, user_model, topics_of_interest):
    """End-to-end: unknown answer falls through to default_outcome."""
    agent = _make_mock_agent(ask_options_return=None)
    moves = [
        {
            "type": "ask_options",
            "text": "What is dreaming?",
            "options": ["dreaming", "sleeping"],
            "outcomes": {"dreaming": "correct"},
            "default_outcome": "incorrect",
        },
        {
            "type": "branch",
            "on": "outcome",
            "cases": {
                "correct": [{"type": "say", "text": "Correct!"}],
                "incorrect": [{"type": "say", "text": "Wrong!"}],
            },
        },
    ]
    md = MiniDialog('test', moves=moves)
    md.run(agent, session_history, topics_of_interest, user_model)

    assert md.current_outcome == "incorrect"
    texts_spoken = [call.args[0] for call in agent.say.call_args_list]
    assert "Wrong!" in texts_spoken
    assert "Correct!" not in texts_spoken


def test_full_dialog_new_branching_ask_yesno(session_history, user_model, topics_of_interest):
    """End-to-end: ask_yesno with outcomes routes into the correct branch case."""
    agent = _make_mock_agent(ask_yesno_return='yes')
    moves = [
        {
            "type": "ask_yesno",
            "text": "Do you remember a dream?",
            "set_variable": "remembered",
            "outcomes": {"yes": "mem_yes", "no": "mem_no", "dontknow": "mem_no"},
            "default_outcome": "mem_no",
        },
        {
            "type": "branch",
            "on": "outcome",
            "cases": {
                "mem_yes": [{"type": "say", "text": "Tell me about it!"}],
                "mem_no": [{"type": "say", "text": "That's okay."}],
            },
        },
    ]
    md = MiniDialog('test', moves=moves)
    md.run(agent, session_history, topics_of_interest, user_model)

    assert md.current_outcome == "mem_yes"
    texts_spoken = [call.args[0] for call in agent.say.call_args_list]
    assert "Tell me about it!" in texts_spoken
    assert "That's okay." not in texts_spoken


def test_branch_on_user_model_variable(session_history, user_model, topics_of_interest):
    """branch move can read from a user_model variable instead of current_outcome."""
    agent = _make_mock_agent()
    user_model['mood'] = 'happy'

    moves = [
        {
            "type": "branch",
            "on": "mood",
            "cases": {
                "happy": [{"type": "say", "text": "Great to hear!"}],
                "sad": [{"type": "say", "text": "Sorry to hear that."}],
            },
        },
    ]
    md = MiniDialog('test', moves=moves)
    md.run(agent, session_history, topics_of_interest, user_model)

    texts_spoken = [call.args[0] for call in agent.say.call_args_list]
    assert "Great to hear!" in texts_spoken
    assert "Sorry to hear that." not in texts_spoken


def test_resolve_outcome_wildcard_matches_any_answer(session_history, user_model, topics_of_interest):
    """The '*' wildcard in outcomes matches any non-empty answer."""
    agent = _make_mock_agent()
    md = MiniDialog('test', moves=[])
    md.set_conversation_config(agent, session_history, topics_of_interest, user_model)

    move = {"type": "ask_open", "text": "q",
            "outcomes": {"*": "has_answer"}, "default_outcome": "no_answer"}

    md._resolve_outcome(move, "some free text")
    assert md.current_outcome == "has_answer"

    md._resolve_outcome(move, None)
    assert md.current_outcome == "no_answer"

    md._resolve_outcome(move, "")
    assert md.current_outcome == "no_answer"


def test_full_dialog_wildcard_ask_open(session_history, user_model, topics_of_interest):
    """End-to-end: ask_open with '*' wildcard routes to the answered case."""
    agent = _make_mock_agent(ask_open_return='swimming')
    moves = [
        {
            "type": "ask_open",
            "text": "What do you like?",
            "set_variable": "fav",
            "outcomes": {"*": "has_answer"},
            "default_outcome": "no_answer",
        },
        {
            "type": "branch",
            "on": "outcome",
            "cases": {
                "has_answer": [{"type": "say", "text": "Cool answer!"}],
                "no_answer": [{"type": "say", "text": "No worries."}],
            },
        },
    ]
    md = MiniDialog('test', moves=moves)
    md.run(agent, session_history, topics_of_interest, user_model)

    texts_spoken = [call.args[0] for call in agent.say.call_args_list]
    assert "Cool answer!" in texts_spoken
    assert "No worries." not in texts_spoken


def test_move_character_switches_voice_and_falls_back_to_default(session_history, user_model, topics_of_interest):
    from unittest.mock import Mock

    agent = Mock()
    agent.play_audio = Mock()
    agent.play_motion_sequence = Mock()
    agent.play_animation = Mock()
    agent.ask_yesno = Mock(return_value="yes")
    agent.ask_open = Mock(return_value="hello")
    agent.ask_options = Mock(return_value="opt")
    observed = []

    class InteractionConf:
        def __init__(self):
            self.tts_conf = _ElevenLabsTTSConfMock()
            self.language = "en"

    class Orchestrator:
        def __init__(self):
            self.interaction_conf = InteractionConf()
            self.tts_conf = self.interaction_conf.tts_conf

    agent.orchestrator = Orchestrator()

    def _say_side_effect(text):
        conf = agent.orchestrator.tts_conf
        observed.append((text, getattr(conf, "voice_id", None), agent.orchestrator.interaction_conf.language))

    agent.say = Mock(side_effect=_say_side_effect)

    moves = [
        {"type": "say", "character": "narrator", "text": "line 1"},
        {"type": "say", "text": "line 2"},
    ]
    characters = {
        "narrator": {
            "voice_settings": {
                "tts_type": "elevenlabs",
                "voice_id": "narrator_voice",
                "language": "nl",
                "speaking_rate": 0.9,
            }
        }
    }
    md = MiniDialog("test", moves=moves, characters=characters)
    md.run(agent, session_history, topics_of_interest, user_model)

    assert observed[0] == ("line 1", "narrator_voice", "nl")
    assert observed[1] == ("line 2", "default_voice", "en")


def test_character_tts_backend_mismatch(session_history, user_model, topics_of_interest):
    from unittest.mock import Mock

    agent = Mock()
    agent.play_audio = Mock()
    agent.play_motion_sequence = Mock()
    agent.play_animation = Mock()
    agent.ask_yesno = Mock(return_value="yes")
    agent.ask_open = Mock(return_value="hello")
    agent.ask_options = Mock(return_value="opt")
    agent.say = Mock()

    class InteractionConf:
        def __init__(self):
            self.tts_conf = _GoogleTTSConfMock()
            self.language = "en"

    class Orchestrator:
        def __init__(self):
            self.interaction_conf = InteractionConf()
            self.tts_conf = self.interaction_conf.tts_conf

    agent.orchestrator = Orchestrator()

    moves = [{"type": "say", "character": "narrator", "text": "line 1"}]
    characters = {
        "narrator": {
            "voice_settings": {
                "tts_type": "elevenlabs",
                "voice_id": "narrator_voice",
            }
        }
    }
    md = MiniDialog("test", moves=moves, characters=characters)
    with pytest.raises(ValueError, match="must match default interaction tts_type 'google'"):
        md.run(agent, session_history, topics_of_interest, user_model)


def test_character_tts_type_requires_known_default_backend(session_history, user_model, topics_of_interest):
    from unittest.mock import Mock

    agent = Mock()
    agent.play_audio = Mock()
    agent.play_motion_sequence = Mock()
    agent.play_animation = Mock()
    agent.ask_yesno = Mock(return_value="yes")
    agent.ask_open = Mock(return_value="hello")
    agent.ask_options = Mock(return_value="opt")
    agent.say = Mock()

    class UnknownTTSConf:
        pass

    class InteractionConf:
        def __init__(self):
            self.tts_conf = UnknownTTSConf()
            self.language = "en"

    class Orchestrator:
        def __init__(self):
            self.interaction_conf = InteractionConf()
            self.tts_conf = self.interaction_conf.tts_conf

    agent.orchestrator = Orchestrator()

    moves = [{"type": "say", "character": "narrator", "text": "line 1"}]
    characters = {"narrator": {"voice_settings": {"tts_type": "elevenlabs", "voice_id": "narrator_voice"}}}
    md = MiniDialog("test", moves=moves, characters=characters)
    with pytest.raises(ValueError, match="requires a known default interaction tts_type"):
        md.run(agent, session_history, topics_of_interest, user_model)
