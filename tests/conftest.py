import sys
import os
import pytest
from unittest.mock import Mock

# Ensure tests can import modules from the src/ directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))


@pytest.fixture
def session_history():
    return []


@pytest.fixture
def user_model():
    return {}


@pytest.fixture
def topics_of_interest():
    return []


@pytest.fixture
def make_mock_agent():
    """Factory to create a simple mock ConversationAgent with configurable side-effects.

    Usage:
        agent = make_mock_agent(ask_llm_side_effect=[...], ask_open_side_effect=[...])
    The side-effect lists are wrapped so that if the mock is called more times than the
    provided sequence length, the last value is returned repeatedly instead of raising StopIteration.
    """
    def _wrap_side_effect(seq):
        if seq is None:
            return None
        seq_list = list(seq)
        if not seq_list:
            return lambda *a, **k: None
        last = seq_list[-1]

        def fn(*a, **k):
            if seq_list:
                return seq_list.pop(0)
            return last

        return fn

    def _make(ask_llm_side_effect=None, ask_open_side_effect=None,
              ask_yes_no_side_effect=None, ask_options_side_effect=None):
        agent = type('Agent', (), {})()
        llm_effect = _wrap_side_effect(ask_llm_side_effect)
        open_effect = _wrap_side_effect(ask_open_side_effect)
        yesno_effect = _wrap_side_effect(ask_yes_no_side_effect)
        options_effect = _wrap_side_effect(ask_options_side_effect)
        agent.ask_llm = Mock(side_effect=llm_effect) if ask_llm_side_effect is not None else Mock(return_value=None)
        agent.ask_open = Mock(side_effect=open_effect) if ask_open_side_effect is not None else Mock(return_value=None)
        agent.ask_yes_no = Mock(side_effect=yesno_effect) if ask_yes_no_side_effect is not None else Mock(return_value='no')
        agent.ask_options = Mock(side_effect=options_effect) if ask_options_side_effect is not None else Mock(return_value=None)
        agent.say = Mock()
        agent.play_audio = Mock()
        agent.play_motion_sequence = Mock()
        agent.play_animation = Mock()
        agent.personalize = Mock(return_value=None)
        return agent

    return _make
