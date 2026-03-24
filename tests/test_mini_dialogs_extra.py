from mini_dialogs import MiniDialog
from moves import MoveAskLLM, MOVE_ASK_LLM, MOVE_ANSWER_LLM


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
    # ask_open should be called at least once (the LLM may prompt multiple times up to max_turns)
    assert agent.ask_open.call_count >= 1

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
