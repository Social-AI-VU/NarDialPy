from dialogs import Dialog, LLMDialog
from moves import MOVE_ASK_LLM, MOVE_ANSWER_LLM


def test_run_llm_exchange_happy_path(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(
        ask_llm_side_effect=["LLM Q1", "LLM Q2"],
        ask_open_side_effect=["My favorite is 'pizza'", "I like cats"]
    )

    md = Dialog('test', moves=[])
    md.set_conversation_config(agent, session_history, topics_of_interest, user_model)

    md._run_llm_exchange(prompt="p", max_turns=2, set_variable='favorite')

    assert agent.ask_llm.call_count == 2
    assert agent.ask_open.call_count == 2

    types = [entry['type'] for entry in session_history]
    assert MOVE_ASK_LLM in types
    assert MOVE_ANSWER_LLM in types

    assert 'favorite' in user_model
    assert user_model['favorite'] == 'cats' or user_model['favorite'] == "I like cats"


def test_run_llm_exchange_quit_phrase_stops_early(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(
        ask_llm_side_effect=["LLM Q1", "LLM Q2"],
        ask_open_side_effect=["stop please"]
    )

    md = Dialog('test', moves=[])
    md.set_conversation_config(agent, session_history, topics_of_interest, user_model)

    md._run_llm_exchange(prompt="p", max_turns=3, set_variable=None, quit_phrases=["stop"])

    assert agent.ask_llm.call_count == 1
    assert agent.ask_open.call_count == 1


def test_run_llm_exchange_quit_signal(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(
        ask_llm_side_effect=["finished <<QUIT>>"],
        ask_open_side_effect=[]
    )

    md = Dialog('test', moves=[])
    md.set_conversation_config(agent, session_history, topics_of_interest, user_model)

    md._run_llm_exchange(prompt="p", max_turns=3, set_variable=None, quit_phrases=None, quit_signal="<<QUIT>>")

    assert agent.ask_llm.call_count == 1
    agent.say.assert_called_once()
    say_arg = agent.say.call_args[0][0]
    assert "<<QUIT>>" not in say_arg
    assert "finished" in say_arg


def test_handle_move_ask_llm_calls_run(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(
        ask_llm_side_effect=["LLM Q1"],
        ask_open_side_effect=["ans"]
    )

    move = {'prompt': 'hello', 'max_turns': 1, 'set_variable': 'fav', 'quit_phrases': None, 'quit_signal': None}

    md = Dialog('test', moves=[])
    md.set_conversation_config(agent, session_history, topics_of_interest, user_model)

    md.handle_move_ask_llm(move)

    assert agent.ask_llm.call_count >= 1
    assert agent.ask_open.call_count >= 1
    assert any(entry['type'] == MOVE_ASK_LLM for entry in session_history)
    assert any(entry['type'] == MOVE_ANSWER_LLM for entry in session_history)


def test_llm_dialog_run_respects_max_turns(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(
        ask_llm_side_effect=["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"],
        ask_open_side_effect=["a1", "a2", "a3", "a4", "a5"]
    )

    dialog = LLMDialog('d1', moves=[], prompt='p', max_turns=3)
    dialog.set_conversation_config(agent, session_history, topics_of_interest, user_model)

    dialog.run(agent, session_history, topics_of_interest, user_model)

    assert agent.ask_llm.call_count <= 3
    assert agent.ask_open.call_count <= 3
