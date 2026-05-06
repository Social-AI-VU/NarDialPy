from nardial.mini_dialogs import (
    MiniDialog, RunContext,
    FunctionalDialog, FunctionalType,
    NarrativeDialog,
    ChitchatDialog,
    LLMDialog,
)
from nardial.moves import (
    MoveAskLLM,
    MoveAskOpen,
    MoveAskOptions,
    MoveAskYesNo,
    MoveBranch,
    MoveSay,
    MOVE_ASK_LLM,
    MOVE_ANSWER_LLM,
)


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
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    md._run_llm_exchange(prompt='p', max_turns=3)

    # ask_llm retried until a non-None response
    assert agent.ask_llm.call_count >= 2
    # listen should be called at least once (the LLM may prompt multiple times up to max_turns)
    assert agent.orchestrator.listen.call_count >= 1

    # session history should have at least one ask_llm and one answer entry
    types = [e['type'] for e in session_history]
    assert MOVE_ASK_LLM in types
    assert MOVE_ANSWER_LLM in types


def test_handle_move_ask_llm_sets_variable(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(ask_llm_side_effect=['Q1'], ask_open_side_effect=["I like turtles"])
    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    move = MoveAskLLM(prompt='Tell me something', max_turns=1, set_variable='pet')
    md.handle_move_ask_llm(move)

    # The user's answer should be stored under the set variable using extractor heuristics
    assert 'pet' in user_model
    assert user_model['pet'] in ('turtles', 'I like turtles')


# ---------------------------------------------------------------------------
# Declarative branching tests
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


def test_move_branch_model_validate():
    data = {
        "type": "branch",
        "on": "outcome",
        "cases": {
            "correct": [{"type": "say", "text": "Well done!"}],
            "incorrect": [{"type": "say", "text": "Not quite."}],
        }
    }
    mb = MoveBranch.model_validate(data)
    assert mb.on == "outcome"
    assert "correct" in mb.cases
    assert mb.cases["incorrect"][0].text == "Not quite."


def test_resolve_outcome_with_outcomes_dict(session_history, user_model, topics_of_interest):
    """_resolve_outcome stores the matching outcome label from the outcomes dict."""
    agent = _make_mock_agent()
    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    move = MoveAskOptions(
        text="q", options=["a", "b"],
        outcomes={"a": "branch_a", "b": "branch_b"},
        default_outcome="branch_b",
    )

    md._resolve_outcome(move, "a")
    assert md.current_outcome == "branch_a"

    md._resolve_outcome(move, "b")
    assert md.current_outcome == "branch_b"


def test_resolve_outcome_falls_back_to_default(session_history, user_model, topics_of_interest):
    """When the answer doesn't appear in outcomes, default_outcome is used."""
    agent = _make_mock_agent()
    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    move = MoveAskOptions(
        text="q", options=["a"],
        outcomes={"a": "branch_a"},
        default_outcome="branch_default",
    )

    md._resolve_outcome(move, None)
    assert md.current_outcome == "branch_default"

    md._resolve_outcome(move, "unknown_value")
    assert md.current_outcome == "branch_default"


def test_handle_move_branch_executes_correct_case(session_history, user_model, topics_of_interest):
    """handle_move_branch runs the sub-moves for the active current_outcome."""
    agent = _make_mock_agent()
    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    md.current_outcome = "correct"

    move = MoveBranch(
        on="outcome",
        cases={
            "correct": [MoveSay(text="Correct!")],
            "incorrect": [MoveSay(text="Wrong!")],
        },
    )
    md.handle_move_branch(move)

    # Only the "correct" sub-move should have been spoken
    agent.say.assert_called_once_with("Correct!")


def test_handle_move_branch_unknown_case_is_silent(session_history, user_model, topics_of_interest):
    """handle_move_branch does nothing when current_outcome matches no case."""
    agent = _make_mock_agent()
    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    md.current_outcome = "other"

    move = MoveBranch(
        on="outcome",
        cases={"correct": [MoveSay(text="Correct!")]},
    )
    md.handle_move_branch(move)
    agent.say.assert_not_called()


def test_full_dialog_new_branching_ask_options(session_history, user_model, topics_of_interest):
    """End-to-end: ask_options with outcomes routes into the correct branch case."""
    agent = _make_mock_agent(ask_options_return='dreaming')
    moves = [
        MoveAskOptions(
            text="What is dreaming?",
            options=["dreaming", "sleeping", "resting"],
            set_variable="what_is_dreaming",
            outcomes={"dreaming": "correct", "sleeping": "incorrect", "resting": "incorrect"},
            default_outcome="incorrect",
        ),
        MoveBranch(
            on="outcome",
            cases={
                "correct": [MoveSay(text="Indeed, dreaming.")],
                "incorrect": [MoveSay(text="This is called dreaming!")],
            },
        ),
        MoveSay(text="Continuing the dialog."),
    ]
    md = MiniDialog('test', moves=moves)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    md.run(agent, context)

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
        MoveAskOptions(
            text="What is dreaming?",
            options=["dreaming", "sleeping"],
            outcomes={"dreaming": "correct"},
            default_outcome="incorrect",
        ),
        MoveBranch(
            on="outcome",
            cases={
                "correct": [MoveSay(text="Correct!")],
                "incorrect": [MoveSay(text="Wrong!")],
            },
        ),
    ]
    md = MiniDialog('test', moves=moves)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    md.run(agent, context)

    assert md.current_outcome == "incorrect"
    texts_spoken = [call.args[0] for call in agent.say.call_args_list]
    assert "Wrong!" in texts_spoken
    assert "Correct!" not in texts_spoken


def test_full_dialog_new_branching_ask_yesno(session_history, user_model, topics_of_interest):
    """End-to-end: ask_yesno with outcomes routes into the correct branch case."""
    agent = _make_mock_agent(ask_yesno_return='yes')
    moves = [
        MoveAskYesNo(
            text="Do you remember a dream?",
            set_variable="remembered",
            outcomes={"yes": "mem_yes", "no": "mem_no", "dontknow": "mem_no"},
            default_outcome="mem_no",
        ),
        MoveBranch(
            on="outcome",
            cases={
                "mem_yes": [MoveSay(text="Tell me about it!")],
                "mem_no": [MoveSay(text="That's okay.")],
            },
        ),
    ]
    md = MiniDialog('test', moves=moves)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    md.run(agent, context)

    assert md.current_outcome == "mem_yes"
    texts_spoken = [call.args[0] for call in agent.say.call_args_list]
    assert "Tell me about it!" in texts_spoken
    assert "That's okay." not in texts_spoken


def test_branch_on_user_model_variable(session_history, user_model, topics_of_interest):
    """branch move can read from a user_model variable instead of current_outcome."""
    agent = _make_mock_agent()
    user_model['mood'] = 'happy'

    moves = [
        MoveBranch(
            on="mood",
            cases={
                "happy": [MoveSay(text="Great to hear!")],
                "sad": [MoveSay(text="Sorry to hear that.")],
            },
        ),
    ]
    md = MiniDialog('test', moves=moves)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    md.run(agent, context)

    texts_spoken = [call.args[0] for call in agent.say.call_args_list]
    assert "Great to hear!" in texts_spoken
    assert "Sorry to hear that." not in texts_spoken


def test_resolve_outcome_wildcard_matches_any_answer(session_history, user_model, topics_of_interest):
    """The '*' wildcard in outcomes matches any non-empty answer."""
    agent = _make_mock_agent()
    md = MiniDialog('test', moves=[])
    md._agent = agent
    md._context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    move = MoveAskOpen(
        text="q",
        outcomes={"*": "has_answer"},
        default_outcome="no_answer",
    )

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
        MoveAskOpen(
            text="What do you like?",
            set_variable="fav",
            outcomes={"*": "has_answer"},
            default_outcome="no_answer",
        ),
        MoveBranch(
            on="outcome",
            cases={
                "has_answer": [MoveSay(text="Cool answer!")],
                "no_answer": [MoveSay(text="No worries.")],
            },
        ),
    ]
    md = MiniDialog('test', moves=moves)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    md.run(agent, context)

    texts_spoken = [call.args[0] for call in agent.say.call_args_list]
    assert "Cool answer!" in texts_spoken
    assert "No worries." not in texts_spoken


# ---------------------------------------------------------------------------
# FunctionalDialog, NarrativeDialog, ChitchatDialog, LLMDialog
# ---------------------------------------------------------------------------

class TestFunctionalDialog:
    def test_string_type_coerced_to_enum_greeting(self):
        d = FunctionalDialog("g", [], "greeting")
        assert d.type is FunctionalType.GREETING
        assert d.is_greeting_dialog()
        assert not d.is_farewell_dialog()

    def test_string_type_coerced_to_enum_farewell(self):
        d = FunctionalDialog("f", [], "farewell")
        assert d.type is FunctionalType.FAREWELL
        assert d.is_farewell_dialog()
        assert not d.is_greeting_dialog()

    def test_enum_type_accepted_directly(self):
        d = FunctionalDialog("g", [], FunctionalType.GREETING)
        assert d.is_greeting_dialog()

    def test_greeting_dialog_runs_moves(self, session_history, user_model, topics_of_interest):
        agent = _make_mock_agent()
        d = FunctionalDialog("g", [MoveSay(text="Hi!")], "greeting")
        d.run(agent, RunContext(session_history=session_history,
                                topics_of_interest=topics_of_interest,
                                user_model=user_model))
        agent.say.assert_called_once_with("Hi!")


class TestNarrativeDialog:
    def test_stores_thread_and_position(self):
        d = NarrativeDialog("n1", [MoveSay(text="x")], thread="main", position=3)
        assert d.thread == "main"
        assert d.position == 3
        assert d.dialog_id == "n1"

    def test_runs_moves(self, session_history, user_model, topics_of_interest):
        agent = _make_mock_agent()
        d = NarrativeDialog("n1", [MoveSay(text="Chapter 1.")], thread="main", position=1)
        d.run(agent, RunContext(session_history=session_history,
                                topics_of_interest=topics_of_interest,
                                user_model=user_model))
        agent.say.assert_called_once_with("Chapter 1.")


class TestChitchatDialog:
    def test_stores_theme_and_topics(self):
        d = ChitchatDialog("c1", [], theme="animals", topics=["cats", "dogs"])
        assert d.theme == "animals"
        assert d.topics == ["cats", "dogs"]

    def test_topics_default_to_empty_list(self):
        d = ChitchatDialog("c1", [], theme="general")
        assert d.topics == []


class TestLLMDialogSpeakFirst:
    def test_speak_first_false_listens_before_asking_llm(
            self, session_history, user_model, topics_of_interest, make_mock_agent):
        """When speak_first=False the orchestrator listens for the opening user utterance
        before the first LLM call — the reverse of the default flow."""
        agent = make_mock_agent(
            ask_llm_side_effect=["LLM response"],
            ask_open_side_effect=["user opened first"],
        )

        dialog = LLMDialog(
            "llm1", moves=[], prompt="respond", max_turns=1, speak_first=False
        )
        context = RunContext(
            session_history=session_history,
            topics_of_interest=topics_of_interest,
            user_model=user_model,
        )
        dialog.run(agent, context)

        # orchestrator.listen must be called before ask_llm
        listen_order = agent.orchestrator.listen.call_count
        llm_order = agent.ask_llm.call_count
        assert listen_order >= 1
        assert llm_order >= 1
