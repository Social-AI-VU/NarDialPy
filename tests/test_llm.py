from nardial.mini_dialogs import ScriptedMiniDialog, LLMMiniDialog
from nardial.dialog_runtime import RunContext, DialogRuntime, _run_llm_exchange
from nardial.moves import (
    MoveAskLLM,
    MoveAskOpen,
    MoveAskOptions,
    MoveAskYesNo,
    MoveLLMSay,
    MOVE_ASK_LLM,
    MOVE_ANSWER_LLM,
    MOVE_LLM_FOLLOWUP,
    MOVE_LLM_SAY,
    MOVE_ANSWER_OPEN,
    MOVE_ANSWER_YESNO,
    MOVE_ANSWER_OPTIONS,
)


async def test_run_llm_exchange_happy_path(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(
        ask_llm_side_effect=["LLM Q1", "LLM Q2"],
        ask_open_side_effect=["My favorite is 'pizza'", "I like cats"]
    )
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    await _run_llm_exchange(agent, context, prompt="p", max_turns=2, set_variable='favorite')

    assert agent.ask_llm.call_count == 2
    assert agent.orchestrator.listen.call_count == 2

    types = [entry['type'] for entry in session_history]
    assert MOVE_ASK_LLM in types
    assert MOVE_ANSWER_LLM in types

    assert 'favorite' in user_model
    assert user_model['favorite'] == 'cats' or user_model['favorite'] == "I like cats"


async def test_run_llm_exchange_quit_phrase_stops_early(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(
        ask_llm_side_effect=["LLM Q1", "LLM Q2"],
        ask_open_side_effect=["stop please"]
    )
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    await _run_llm_exchange(agent, context, prompt="p", max_turns=3, set_variable=None, quit_phrases=["stop"])

    assert agent.ask_llm.call_count == 1
    assert agent.orchestrator.listen.call_count == 1


async def test_run_llm_exchange_quit_signal(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(
        ask_llm_side_effect=["finished <<QUIT>>"],
        ask_open_side_effect=[]
    )
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    await _run_llm_exchange(agent, context, prompt="p", max_turns=3, set_variable=None, quit_phrases=None, quit_signal="<<QUIT>>")

    assert agent.ask_llm.call_count == 1
    agent.say.assert_called_once()
    say_arg = agent.say.call_args[0][0]
    assert "<<QUIT>>" not in say_arg
    assert "finished" in say_arg


async def test_handle_move_ask_llm_calls_run(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(
        ask_llm_side_effect=["LLM Q1"],
        ask_open_side_effect=["ans"]
    )

    move = MoveAskLLM(prompt='hello', max_turns=1, set_variable='fav')
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    runtime = DialogRuntime(agent)
    await runtime._handle_ask_llm(move, context)

    assert agent.ask_llm.call_count >= 1
    assert agent.orchestrator.listen.call_count >= 1
    assert any(entry['type'] == MOVE_ASK_LLM for entry in session_history)
    assert any(entry['type'] == MOVE_ANSWER_LLM for entry in session_history)


async def test_llm_dialog_run_respects_max_turns(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(
        ask_llm_side_effect=["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"],
        ask_open_side_effect=["a1", "a2", "a3", "a4", "a5"]
    )

    dialog = LLMMiniDialog('d1', moves=[], prompt='p', max_turns=3)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    await DialogRuntime(agent).run(dialog, context)

    assert agent.ask_llm.call_count <= 3
    assert agent.orchestrator.listen.call_count <= 3


async def test_ask_open_llm_followup_generates_response(
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

    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    runtime = DialogRuntime(agent)
    await runtime._handle_ask_open(move, context)

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


async def test_ask_open_llm_followup_receives_full_conversation_context(
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

    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    runtime = DialogRuntime(agent)
    await runtime._handle_ask_open(move, context)

    call_kwargs = agent.ask_llm.call_args.kwargs
    # Context should include prior history entries
    assert any("Let's talk about food." in msg for msg in call_kwargs['context_messages'])


async def test_ask_yesno_llm_followup_generates_response(
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

    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    runtime = DialogRuntime(agent)
    await runtime._handle_ask_yesno(move, context)

    agent.ask_llm.assert_called_once()
    call_kwargs = agent.ask_llm.call_args.kwargs
    assert call_kwargs['user_prompt'] == "yes"
    agent.say.assert_called_once_with("That's great, dogs are amazing companions!")
    assert any(entry['type'] == MOVE_LLM_FOLLOWUP for entry in session_history)


async def test_ask_options_llm_followup_generates_response(
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

    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    runtime = DialogRuntime(agent)
    await runtime._handle_ask_options(move, context)

    agent.ask_llm.assert_called_once()
    call_kwargs = agent.ask_llm.call_args.kwargs
    assert call_kwargs['user_prompt'] == "forest"
    agent.say.assert_called_once_with("Forests are so serene and full of life!")
    assert any(entry['type'] == MOVE_LLM_FOLLOWUP for entry in session_history)


async def test_ask_open_without_llm_followup_does_not_call_llm(
        session_history, user_model, topics_of_interest, make_mock_agent):
    """Without llm_followup, ask_open does not call the LLM."""
    agent = make_mock_agent(ask_open_side_effect=["I like cats."])

    move = MoveAskOpen(
        text='What is your favorite animal?',
        set_variable='favorite_animal',
    )

    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    runtime = DialogRuntime(agent)
    await runtime._handle_ask_open(move, context)

    agent.ask_llm.assert_not_called()
    assert not any(entry['type'] == MOVE_LLM_FOLLOWUP for entry in session_history)


async def test_dispatcher_runs_llm_followup_within_ask_open(
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

    dialog = ScriptedMiniDialog('test', moves=moves)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    await DialogRuntime(agent).run(dialog, context)

    agent.ask_llm.assert_called_once()
    agent.say.assert_called_once_with("Painting is a beautiful hobby!")
    assert any(entry['type'] == MOVE_ANSWER_OPEN for entry in session_history)
    assert any(entry['type'] == MOVE_LLM_FOLLOWUP for entry in session_history)


# ---------------------------------------------------------------------------
# MoveLLMSay tests
# ---------------------------------------------------------------------------

async def test_llm_say_generates_and_speaks_utterance(
        session_history, user_model, topics_of_interest, make_mock_agent):
    """llm_say calls the LLM with the prompt and speaks the returned text."""
    agent = make_mock_agent(ask_llm_side_effect=["What a lovely day for a walk!"])

    move = MoveLLMSay(prompt="Generate a cheerful one-sentence remark about the weather.")

    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    runtime = DialogRuntime(agent)
    await runtime._handle_llm_say(move, context)

    agent.ask_llm.assert_called_once()
    agent.say.assert_called_once_with("What a lovely day for a walk!")
    assert any(entry['type'] == MOVE_LLM_SAY for entry in session_history)
    assert session_history[-1]['text'] == "What a lovely day for a walk!"


async def test_llm_say_substitutes_variables_in_prompt(
        session_history, user_model, topics_of_interest, make_mock_agent):
    """llm_say performs %variable% substitution on the prompt before the LLM call."""
    agent = make_mock_agent(ask_llm_side_effect=["Labradors are wonderful!"])
    user_model['favorite_animal'] = 'labrador'

    move = MoveLLMSay(prompt="The user loves %favorite_animal%. React warmly in one sentence.")

    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    runtime = DialogRuntime(agent)
    await runtime._handle_llm_say(move, context)

    call_kwargs = agent.ask_llm.call_args.kwargs
    assert 'labrador' in call_kwargs['system_prompt']
    assert '%favorite_animal%' not in call_kwargs['system_prompt']


async def test_llm_say_passes_session_history_as_context(
        session_history, user_model, topics_of_interest, make_mock_agent):
    """llm_say forwards existing session history as context_messages to the LLM."""
    agent = make_mock_agent(ask_llm_side_effect=["Interesting!"])
    session_history.append({"role": "robot", "type": "say", "text": "Let's talk about food."})
    session_history.append({"role": "user", "type": "answer_open", "text": "I love pizza."})

    move = MoveLLMSay(prompt="React to the conversation so far.")

    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    await DialogRuntime(agent)._handle_llm_say(move, context)

    call_kwargs = agent.ask_llm.call_args.kwargs
    assert any("Let's talk about food." in m for m in call_kwargs['context_messages'])
    assert any("I love pizza." in m for m in call_kwargs['context_messages'])


async def test_llm_say_skips_when_llm_returns_none(
        session_history, user_model, topics_of_interest, make_mock_agent):
    """llm_say does not call say() and records nothing when the LLM returns None."""
    agent = make_mock_agent(ask_llm_side_effect=[None])

    move = MoveLLMSay(prompt="Say something.")

    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    await DialogRuntime(agent)._handle_llm_say(move, context)

    agent.say.assert_not_called()
    assert not any(entry['type'] == MOVE_LLM_SAY for entry in session_history)


async def test_llm_say_uses_empty_user_prompt(
        session_history, user_model, topics_of_interest, make_mock_agent):
    """llm_say passes an empty string as user_prompt — the system prompt carries all context."""
    agent = make_mock_agent(ask_llm_side_effect=["Great!"])

    move = MoveLLMSay(prompt="Be enthusiastic.")

    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    await DialogRuntime(agent)._handle_llm_say(move, context)

    call_kwargs = agent.ask_llm.call_args.kwargs
    assert call_kwargs['user_prompt'] == ""


async def test_dispatcher_routes_llm_say(
        session_history, user_model, topics_of_interest, make_mock_agent):
    """The move dispatcher correctly routes llm_say moves."""
    agent = make_mock_agent(
        ask_open_side_effect=["Stargazing."],
        ask_llm_side_effect=["That sounds amazing under a clear night sky!"],
    )

    moves = [
        MoveAskOpen(text="What's your favorite activity?", set_variable="activity"),
        MoveLLMSay(prompt="The user enjoys %activity%. React with one warm sentence."),
    ]

    dialog = ScriptedMiniDialog('test', moves=moves)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    await DialogRuntime(agent).run(dialog, context)

    agent.ask_llm.assert_called_once()
    assert any(entry['type'] == MOVE_ANSWER_OPEN for entry in session_history)
    assert any(entry['type'] == MOVE_LLM_SAY for entry in session_history)
    assert session_history[-1]['text'] == "That sounds amazing under a clear night sky!"


async def test_llm_say_rag_enabled_forwarded(
        session_history, user_model, topics_of_interest, make_mock_agent):
    """rag_enabled and index_name are forwarded to the LLM provider."""
    agent = make_mock_agent(ask_llm_side_effect=["Here's what I know about that."])

    move = MoveLLMSay(prompt="Answer based on stored knowledge.", rag_enabled=True, index_name="facts")

    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    await DialogRuntime(agent)._handle_llm_say(move, context)

    call_kwargs = agent.ask_llm.call_args.kwargs
    assert call_kwargs['rag_enabled'] is True
    assert call_kwargs['index_name'] == "facts"
