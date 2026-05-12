from unittest.mock import AsyncMock, MagicMock

from nardial.dialog_runtime import (
    DialogRuntime,
    RunContext,
    _run_llm_exchange,
    extract_open_value,
)
from nardial.mini_dialogs import (
    FunctionalDialog, FunctionalLabel,
    ScriptedMiniDialog,
    NarrativeDialog,
    ChitchatDialog,
    LLMMiniDialog,
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
    assert extract_open_value("I love 'apples' so much") == 'apples'
    assert extract_open_value('She said "banana" is nice') == 'banana'

    # Last alphabetic token should be returned when no quotes
    assert extract_open_value('My favorite animal is a zebra') == 'zebra'

    # If no alphabetic tokens, return trimmed original
    assert extract_open_value('  12345  ') == '12345'


async def test_run_llm_exchange_retries_on_none(session_history, user_model, topics_of_interest, make_mock_agent):
    # ask_llm returns None first (simulating transient LLM failure), then returns text
    agent = make_mock_agent(ask_llm_side_effect=[None, 'Hello LLM'], ask_open_side_effect=['hi'])
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    await _run_llm_exchange(agent, context, prompt='p', max_turns=3)

    # ask_llm retried until a non-None response
    assert agent.ask_llm.call_count >= 2
    # listen should be called at least once
    assert agent.orchestrator.listen.call_count >= 1

    # session history should have at least one ask_llm and one answer entry
    types = [e['type'] for e in session_history]
    assert MOVE_ASK_LLM in types
    assert MOVE_ANSWER_LLM in types


async def test_handle_move_ask_llm_sets_variable(session_history, user_model, topics_of_interest, make_mock_agent):
    agent = make_mock_agent(ask_llm_side_effect=['Q1'], ask_open_side_effect=["I like turtles"])
    runtime = DialogRuntime(agent)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    move = MoveAskLLM(prompt='Tell me something', max_turns=1, set_variable='pet')
    await runtime._handle_ask_llm(move, context)

    # The user's answer should be stored under the set variable using extractor heuristics
    assert 'pet' in user_model
    assert user_model['pet'] in ('turtles', 'I like turtles')


# ---------------------------------------------------------------------------
# Declarative branching tests
# ---------------------------------------------------------------------------

def _make_mock_agent(ask_options_return='dreaming', ask_yesno_return='yes', ask_open_return='something'):
    agent = MagicMock()
    agent.say = AsyncMock()
    agent.ask_options = AsyncMock(return_value=ask_options_return)
    agent.ask_yesno = AsyncMock(return_value=ask_yesno_return)
    agent.ask_open = AsyncMock(return_value=ask_open_return)
    agent.play_audio = MagicMock()
    agent.play_motion_sequence = MagicMock()
    agent.play_animation = MagicMock()
    agent.personalize = MagicMock(return_value=None)
    orchestrator = MagicMock()
    orchestrator.listen = AsyncMock(return_value=MagicMock(transcript=ask_open_return or ""))
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
    runtime = DialogRuntime(MagicMock())
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    move = MoveAskOptions(
        text="q", options=["a", "b"],
        outcomes={"a": "branch_a", "b": "branch_b"},
        default_outcome="branch_b",
    )

    runtime._resolve_outcome(move, "a", context)
    assert context.current_outcome == "branch_a"

    runtime._resolve_outcome(move, "b", context)
    assert context.current_outcome == "branch_b"


def test_resolve_outcome_falls_back_to_default(session_history, user_model, topics_of_interest):
    """When the answer doesn't appear in outcomes, default_outcome is used."""
    runtime = DialogRuntime(MagicMock())
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    move = MoveAskOptions(
        text="q", options=["a"],
        outcomes={"a": "branch_a"},
        default_outcome="branch_default",
    )

    runtime._resolve_outcome(move, None, context)
    assert context.current_outcome == "branch_default"

    runtime._resolve_outcome(move, "unknown_value", context)
    assert context.current_outcome == "branch_default"


async def test_handle_move_branch_executes_correct_case(session_history, user_model, topics_of_interest):
    """_handle_branch runs the sub-moves for the active current_outcome."""
    agent = _make_mock_agent()
    runtime = DialogRuntime(agent)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    context.current_outcome = "correct"

    move = MoveBranch(
        on="outcome",
        cases={
            "correct": [MoveSay(text="Correct!")],
            "incorrect": [MoveSay(text="Wrong!")],
        },
    )
    await runtime._handle_branch(move, context)

    agent.say.assert_called_once_with("Correct!")


async def test_handle_move_branch_unknown_case_is_silent(session_history, user_model, topics_of_interest):
    """_handle_branch does nothing when current_outcome matches no case."""
    agent = _make_mock_agent()
    runtime = DialogRuntime(agent)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    context.current_outcome = "other"

    move = MoveBranch(
        on="outcome",
        cases={"correct": [MoveSay(text="Correct!")]},
    )
    await runtime._handle_branch(move, context)
    agent.say.assert_not_called()


async def test_full_dialog_new_branching_ask_options(session_history, user_model, topics_of_interest):
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
    dialog = ScriptedMiniDialog('test', moves=moves)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    await DialogRuntime(agent).run(dialog, context)

    assert context.current_outcome == "correct"
    texts_spoken = [call.args[0] for call in agent.say.call_args_list]
    assert "Indeed, dreaming." in texts_spoken
    assert "This is called dreaming!" not in texts_spoken
    assert "Continuing the dialog." in texts_spoken
    assert user_model.get("what_is_dreaming") == "dreaming"


async def test_full_dialog_new_branching_ask_options_default(session_history, user_model, topics_of_interest):
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
    dialog = ScriptedMiniDialog('test', moves=moves)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    await DialogRuntime(agent).run(dialog, context)

    assert context.current_outcome == "incorrect"
    texts_spoken = [call.args[0] for call in agent.say.call_args_list]
    assert "Wrong!" in texts_spoken
    assert "Correct!" not in texts_spoken


async def test_full_dialog_new_branching_ask_yesno(session_history, user_model, topics_of_interest):
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
    dialog = ScriptedMiniDialog('test', moves=moves)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    await DialogRuntime(agent).run(dialog, context)

    assert context.current_outcome == "mem_yes"
    texts_spoken = [call.args[0] for call in agent.say.call_args_list]
    assert "Tell me about it!" in texts_spoken
    assert "That's okay." not in texts_spoken


async def test_branch_on_user_model_variable(session_history, user_model, topics_of_interest):
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
    dialog = ScriptedMiniDialog('test', moves=moves)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    await DialogRuntime(agent).run(dialog, context)

    texts_spoken = [call.args[0] for call in agent.say.call_args_list]
    assert "Great to hear!" in texts_spoken
    assert "Sorry to hear that." not in texts_spoken


def test_resolve_outcome_wildcard_matches_any_answer(session_history, user_model, topics_of_interest):
    """The '*' wildcard in outcomes matches any non-empty answer."""
    runtime = DialogRuntime(MagicMock())
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)

    move = MoveAskOpen(
        text="q",
        outcomes={"*": "has_answer"},
        default_outcome="no_answer",
    )

    runtime._resolve_outcome(move, "some free text", context)
    assert context.current_outcome == "has_answer"

    runtime._resolve_outcome(move, None, context)
    assert context.current_outcome == "no_answer"

    runtime._resolve_outcome(move, "", context)
    assert context.current_outcome == "no_answer"


async def test_full_dialog_wildcard_ask_open(session_history, user_model, topics_of_interest):
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
    dialog = ScriptedMiniDialog('test', moves=moves)
    context = RunContext(session_history=session_history, topics_of_interest=topics_of_interest, user_model=user_model)
    await DialogRuntime(agent).run(dialog, context)

    texts_spoken = [call.args[0] for call in agent.say.call_args_list]
    assert "Cool answer!" in texts_spoken
    assert "No worries." not in texts_spoken


# ---------------------------------------------------------------------------
# FunctionalDialog, NarrativeDialog, ChitchatDialog, LLMMiniDialog
# ---------------------------------------------------------------------------

class TestFunctionalDialog:
    def test_string_type_coerced_to_enum_greeting(self):
        d = FunctionalDialog("g", [], "greeting")
        assert d.type is FunctionalLabel.GREETING
        assert d.is_greeting_dialog()
        assert not d.is_farewell_dialog()

    def test_string_type_coerced_to_enum_farewell(self):
        d = FunctionalDialog("f", [], "farewell")
        assert d.type is FunctionalLabel.FAREWELL
        assert d.is_farewell_dialog()
        assert not d.is_greeting_dialog()

    def test_enum_type_accepted_directly(self):
        d = FunctionalDialog("g", [], FunctionalLabel.GREETING)
        assert d.is_greeting_dialog()

    async def test_greeting_dialog_runs_moves(self, session_history, user_model, topics_of_interest):
        agent = _make_mock_agent()
        d = FunctionalDialog("g", [MoveSay(text="Hi!")], "greeting")
        await DialogRuntime(agent).run(
            d,
            RunContext(session_history=session_history,
                       topics_of_interest=topics_of_interest,
                       user_model=user_model),
        )
        agent.say.assert_called_once_with("Hi!")


class TestNarrativeDialog:
    def test_stores_thread_and_position(self):
        d = NarrativeDialog("n1", [MoveSay(text="x")], thread="main", position=3)
        assert d.thread == "main"
        assert d.position == 3
        assert d.dialog_id == "n1"

    async def test_runs_moves(self, session_history, user_model, topics_of_interest):
        agent = _make_mock_agent()
        d = NarrativeDialog("n1", [MoveSay(text="Chapter 1.")], thread="main", position=1)
        await DialogRuntime(agent).run(
            d,
            RunContext(session_history=session_history,
                       topics_of_interest=topics_of_interest,
                       user_model=user_model),
        )
        agent.say.assert_called_once_with("Chapter 1.")


class TestChitchatDialog:
    def test_stores_topics(self):
        d = ChitchatDialog("c1", [], topics=["cats", "dogs"])
        assert d.topics == ["cats", "dogs"]

    def test_topics_default_to_empty_list(self):
        d = ChitchatDialog("c1", [])
        assert d.topics == []


class TestExtractOpenValueEdgeCases:
    """Edge cases not covered by the existing standalone test."""

    def test_empty_string_returns_empty(self):
        assert extract_open_value("") == ""

    def test_single_alphabetic_word_returned_verbatim(self):
        assert extract_open_value("Alice") == "Alice"

    def test_hyphenated_word_captured_as_last_token(self):
        # The regex [A-Za-z][A-Za-z\-']+ matches hyphenated tokens.
        assert extract_open_value("My name is Mary-Jane") == "Mary-Jane"

    def test_quoted_segment_preferred_over_token(self):
        # Double-quotes take precedence over the last-token heuristic.
        assert extract_open_value('call me "Alex" please') == "Alex"

    def test_exact_outcome_beats_wildcard(self):
        """When a specific key and '*' both exist, the exact key wins."""
        runtime = DialogRuntime(MagicMock())
        context = RunContext(session_history=[], topics_of_interest=[], user_model={})
        move = MoveAskYesNo(
            text="q",
            outcomes={"yes": "exact_yes", "*": "wildcard"},
            default_outcome="default",
        )
        runtime._resolve_outcome(move, "yes", context)
        assert context.current_outcome == "exact_yes"


class TestLLMMiniDialogSpeakFirst:
    async def test_speak_first_false_listens_before_asking_llm(
            self, session_history, user_model, topics_of_interest, make_mock_agent):
        """When speak_first=False the orchestrator listens for the opening user utterance
        before the first LLM call — the reverse of the default flow."""
        agent = make_mock_agent(
            ask_llm_side_effect=["LLM response"],
            ask_open_side_effect=["user opened first"],
        )

        dialog = LLMMiniDialog(
            "llm1", moves=[], prompt="respond", max_turns=1, speak_first=False
        )
        context = RunContext(
            session_history=session_history,
            topics_of_interest=topics_of_interest,
            user_model=user_model,
        )
        await DialogRuntime(agent).run(dialog, context)

        # orchestrator.listen must be called before ask_llm
        listen_order = agent.orchestrator.listen.call_count
        llm_order = agent.ask_llm.call_count
        assert listen_order >= 1
        assert llm_order >= 1
