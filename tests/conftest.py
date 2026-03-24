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
    """
    def _make(ask_llm_side_effect=None, ask_open_side_effect=None):
        agent = type('Agent', (), {})()
        agent.ask_llm = Mock(side_effect=ask_llm_side_effect) if ask_llm_side_effect is not None else Mock(return_value=None)
        agent.ask_open = Mock(side_effect=ask_open_side_effect) if ask_open_side_effect is not None else Mock(return_value=None)
        agent.ask_yes_no = Mock(return_value='no')
        agent.ask_options = Mock(return_value=None)
        agent.say = Mock()
        agent.play_audio = Mock()
        agent.play_motion_sequence = Mock()
        agent.play_animation = Mock()
        agent.personalize = Mock(return_value=None)
        return agent

    return _make
