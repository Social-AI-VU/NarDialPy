from nardial.mini_dialogs import MiniDialog, LLMDialog, RunContext
from nardial.moves import (
    MoveAskLLM,
    MoveAskOpen,
    MoveAskOptions,
    MoveAskYesNo,
    MOVE_ASK_LLM,
    MOVE_ANSWER_LLM,
    MOVE_LLM_FOLLOWUP,
    MOVE_ANSWER_OPEN,
    MOVE_ANSWER_YESNO,
    MOVE_ANSWER_OPTIONS,
)


def test_run_llm_exchange_happy_path(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(
        ask_llm_side_effect=["LLM Q1", "LLM Q2"],
        ask_open_side_effect=["My favorite is 'pizza'", "I like cats"]
    )

    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    md._run_llm_exchange(prompt="p", max_turns=2, set_variable='favorite')

    assert agent.ask_llm.call_count == 2
    assert agent.orchestrator.listen.call_count == 2

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

    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    md._run_llm_exchange(prompt="p", max_turns=3, set_variable=None, quit_phrases=["stop"])

    assert agent.ask_llm.call_count == 1
    assert agent.orchestrator.listen.call_count == 1


def test_run_llm_exchange_quit_signal(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(
        ask_llm_side_effect=["finished <<QUIT>>"],
        ask_open_side_effect=[]
    )

    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

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

    move = MoveAskLLM(prompt='hello', max_turns=1, set_variable='fav')

    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    md.handle_move_ask_llm(move)

    assert agent.ask_llm.call_count >= 1
    assert agent.orchestrator.listen.call_count >= 1
    assert any(entry['type'] == MOVE_ASK_LLM for entry in session_history)
    assert any(entry['type'] == MOVE_ANSWER_LLM for entry in session_history)


def test_llm_dialog_run_respects_max_turns(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(
        ask_llm_side_effect=["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"],
        ask_open_side_effect=["a1", "a2", "a3", "a4", "a5"]
    )

    dialog = LLMDialog('d1', moves=[], prompt='p', max_turns=3)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    dialog.run(agent, context)

    assert agent.ask_llm.call_count <= 3
    assert agent.orchestrator.listen.call_count <= 3


def test_ask_open_llm_followup_generates_response(
        session_history, user_model, topics_of_interest, make_mock_agent):
    """llm_followup on ask_open: after the user replies, the LLM generates a contextual followup."""
    agent = make_mock_agent(
        ask_open_side_effect=["I love hiking in the mountains."],
        ask_llm_side_effect=["That sounds wonderful! Mountains are so peaceful."],
    )

    move = MoveAskOpen(
        text='What did you do this weekend?',
        set_variable='weekend_activity',
        llm_followup='You are a friendly robot. Respond warmly to what the user just said.',
    )

    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    md.handle_move_ask_open(move)

    # LLM should have been called once with the user's answer as the prompt
    agent.ask_llm.assert_called_once()
    call_kwargs = agent.ask_llm.call_args.kwargs
    assert call_kwargs['user_prompt'] == "I love hiking in the mountains."
    assert 'friendly robot' in call_kwargs['system_prompt']

    # The LLM response should be spoken and recorded
    agent.say.assert_called_once_with("That sounds wonderful! Mountains are so peaceful.")
    assert any(entry['type'] == MOVE_LLM_FOLLOWUP for entry in session_history)

    # User's answer is still stored via set_variable (extract_open_value picks the last token)
    assert user_model.get('weekend_activity') == 'mountains'


def test_ask_open_llm_followup_receives_full_conversation_context(
        session_history, user_model, topics_of_interest, make_mock_agent):
    """llm_followup receives the full session history as context."""
    agent = make_mock_agent(
        ask_open_side_effect=["Pizza!"],
        ask_llm_side_effect=["Great choice, pizza is delicious!"],
    )

    # Pre-populate history so LLM receives context
    session_history.append({"role": "robot", "type": "say", "text": "Let's talk about food."})

    move = MoveAskOpen(
        text='What is your favorite food?',
        llm_followup='Be enthusiastic about the user choice.',
    )

    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    md.handle_move_ask_open(move)

    call_kwargs = agent.ask_llm.call_args.kwargs
    # Context should include prior history entries
    assert any("Let's talk about food." in msg for msg in call_kwargs['context_messages'])


def test_ask_yesno_llm_followup_generates_response(
        session_history, user_model, topics_of_interest, make_mock_agent):
    """llm_followup on ask_yesno: after the user replies yes/no, LLM generates a contextual followup."""
    agent = make_mock_agent(
        ask_yes_no_side_effect=["yes"],
        ask_llm_side_effect=["That's great, dogs are amazing companions!"],
    )

    move = MoveAskYesNo(
        text='Do you like dogs?',
        llm_followup='React warmly to the user answer about dogs.',
    )

    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    md.handle_move_ask_yesno(move)

    agent.ask_llm.assert_called_once()
    call_kwargs = agent.ask_llm.call_args.kwargs
    assert call_kwargs['user_prompt'] == "yes"
    agent.say.assert_called_once_with("That's great, dogs are amazing companions!")
    assert any(entry['type'] == MOVE_LLM_FOLLOWUP for entry in session_history)


def test_ask_options_llm_followup_generates_response(
        session_history, user_model, topics_of_interest, make_mock_agent):
    """llm_followup on ask_options: after the user picks an option, LLM generates a contextual followup."""
    agent = make_mock_agent(
        ask_options_side_effect=["forest"],
        ask_llm_side_effect=["Forests are so serene and full of life!"],
    )

    move = MoveAskOptions(
        text='Which place in nature do you prefer?',
        options=['sea', 'forest', 'mountains'],
        llm_followup='Share enthusiasm about the user chosen nature spot.',
    )

    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    md.handle_move_ask_options(move)

    agent.ask_llm.assert_called_once()
    call_kwargs = agent.ask_llm.call_args.kwargs
    assert call_kwargs['user_prompt'] == "forest"
    agent.say.assert_called_once_with("Forests are so serene and full of life!")
    assert any(entry['type'] == MOVE_LLM_FOLLOWUP for entry in session_history)


def test_ask_open_without_llm_followup_does_not_call_llm(
        session_history, user_model, topics_of_interest, make_mock_agent):
    """Without llm_followup, ask_open does not call the LLM."""
    agent = make_mock_agent(ask_open_side_effect=["I like cats."])

    move = MoveAskOpen(
        text='What is your favorite animal?',
        set_variable='favorite_animal',
    )

    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    md.handle_move_ask_open(move)

    agent.ask_llm.assert_not_called()
    assert not any(entry['type'] == MOVE_LLM_FOLLOWUP for entry in session_history)


def test_dispatcher_runs_llm_followup_within_ask_open(
        session_history, user_model, topics_of_interest, make_mock_agent):
    """The move dispatcher triggers llm_followup when running ask_open moves."""
    agent = make_mock_agent(
        ask_open_side_effect=["I enjoy painting."],
        ask_llm_side_effect=["Painting is a beautiful hobby!"],
    )

    moves = [
        MoveAskOpen(
            text='What is your hobby?',
            llm_followup='Respond positively to the user hobby.',
        )
    ]

    md = MiniDialog('test', moves=moves)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    md.run(agent, context)

    agent.ask_llm.assert_called_once()
    agent.say.assert_called_once_with("Painting is a beautiful hobby!")
    assert any(entry['type'] == MOVE_ANSWER_OPEN for entry in session_history)
    assert any(entry['type'] == MOVE_LLM_FOLLOWUP for entry in session_history)
