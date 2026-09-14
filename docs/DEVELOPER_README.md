# NarDialPy Developer Flow

This document explains how NarDialPy turns authored JSON files into a running conversation. It is intended for developers who need to change the runtime, add move types, add dialog selection logic, or implement new providers.

## End-to-end Runtime Path

At a high level, a session moves through these layers:

```text
JSON dialog files
  -> authoring loader/factory
  -> MiniDialog objects with move dictionaries
  -> DialogRegistry (indexed by id / type / attrs)
  -> SessionManager: resolve_agenda() over the session agenda
  -> EligibilityPolicy / eligibility rules (per-slot + final safety-net gate)
  -> MiniDialog.run()
  -> move dispatch handlers
  -> ConversationAgent convenience API
  -> InteractionOrchestrator
  -> providers: device, TTS, NLU, LLM, vector store, screen
  -> ConversationState persistence
```

The most important files are:

| Area | Main files |
| --- | --- |
| JSON loading and validation | `src/nardial/authoring/loader.py`, `src/nardial/authoring/factory.py` |
| Move constants and move data classes | `src/nardial/moves.py` |
| Runtime dialog classes and move execution | `src/nardial/mini_dialogs.py` |
| Dialog registry (indexed lookup) | `src/nardial/dialog_registry.py` |
| Eligibility rules and policy | `src/nardial/eligibility.py` |
| Agenda items, resolver, session plans | `src/nardial/agenda/*.py` |
| Session execution and persistence | `src/nardial/session_manager.py`, `src/nardial/conversation_state.py` |
| High-level agent API | `src/nardial/conversation_agent.py` |
| Provider orchestration | `src/nardial/interaction_orchestrator.py` |
| Provider protocols and implementations | `src/nardial/providers/**` |
| Web/screen events | `src/nardial/events/**`, `src/nardial/providers/screen/**` |

## JSON Files to Dialog Objects

Dialog authors write one dialog object, or an array of dialog objects, in JSON. Examples live in `examples/dialog_json/` and `robotstories_en/`.

`load_dialogs(path_or_dir)` in `authoring/loader.py` accepts either a single JSON file or a directory. If a directory is passed, it loads every `.json` file directly inside that directory. Each JSON object is sent to `DialogFactory.from_json()`.

`DialogFactory` validates the document, normalizes `variable_dependencies`, keeps moves as dictionaries, and creates one of the runtime dialog classes:

| JSON `type` | Runtime class | Required type-specific fields |
| --- | --- | --- |
| `functional` | `FunctionalDialog` | `functional_type` |
| `narrative` | `NarrativeDialog` | `thread`, `position` |
| `chitchat` | `ChitchatDialog` | optional `topics` |
| `llm_based` | `LLMDialog` | `prompt`, optional LLM settings |

Important design detail: normal move JSON is not converted into move objects at load time. It stays as dictionaries in `MiniDialog.moves`. Individual handlers convert a move dictionary with `MoveX.from_dict()` when they need typed access.

## Moves

Moves are the steps inside a dialog. Move type constants and typed helper classes are defined in `moves.py`.

The runtime dispatcher is `MiniDialog._dispatch_move()` in `mini_dialogs.py`. It reads the move `type` and calls a handler such as `handle_move_say()`, `handle_move_ask_open()`, or `handle_move_show_image()`.

Common move families:

| Move family | JSON types | Runtime behavior |
| --- | --- | --- |
| Speech | `say`, `say_options` | Speak fixed text or a random option through `ConversationAgent.say()` |
| Questions | `ask_yesno`, `ask_open`, `ask_options` | Speak a question, listen through NLU, store answer/history, optionally set user-model variables |
| LLM | `ask_llm` | Run a bounded multi-turn LLM exchange |
| Branching | `branch` | Run nested moves based on `current_outcome` or a user-model variable |
| Device/media | `play`, `motion_sequence`, `animation` | Play audio or trigger device motion/animation |
| Timing | `timed_wait` | Wait for a number of seconds |
| Screen output | `show_image`, `show_video`, `show_iframe`, `show_html`, `black_screen` | Call the configured screen provider |
| Screen input | `wait_for_web_input` | Show buttons, subscribe to web input events, resolve by button value or timeout |

Question moves can update runtime state:

- `set_variable` stores an extracted answer in `user_model`.
- `add_interest` or `add_interest_from_answer` appends to `topics_of_interest`.
- `outcomes` and `default_outcome` set `MiniDialog.current_outcome`.
- `llm_followup` asks the LLM for a follow-up and speaks it.

Branching depends on these values. A `branch` move chooses `cases[current_outcome]` by default, or `cases[user_model[on]]` when `on` names another variable.

## Dialog Eligibility

Eligibility is expressed as small, composable `EligibilityRule`s in `eligibility.py`: `ExcludeIfSeenRule` (participant- or session-scoped), `DependencyMetRule`, `VariableDependencyMetRule`, `NarrativeOrderingRule`. Each dialog class declares its own `DEFAULT_ELIGIBILITY` list of rules (see `mini_dialogs.py`) -- e.g. `FunctionalDialog` deliberately omits `ExcludeIfSeenRule` so greetings/farewells re-run every session.

An `EligibilityPolicy` bundles rules together and evaluates them against a context exposing `registry`/`completed_ids`/`session_completed_ids`/`user_model` -- either the full `AgendaContext` (`agenda/items.py`) or the lighter `EligibilityContext`. The free function `is_dialog_eligible(dialog, context, policy=None)` in `eligibility.py` is the single entry point: it falls back to the dialog's own `DEFAULT_ELIGIBILITY` when no explicit `policy` is given.

By default, a dialog is eligible only when:

- Its `dialog_id` has not already been completed (except functional dialogs, which have no `ExcludeIfSeenRule`).
- Every `dependencies` entry appears in the completed dialog IDs.
- Every required `variable_dependencies` entry exists in the user model.
- For `NarrativeDialog`, all earlier dialogs in the same `thread` with lower `position` are completed.

`SessionManager.run_async()` calls `is_dialog_eligible()` as a final safety-net gate on every dialog `resolve_agenda()` yields. It's a genuine gate, not a redundant check: a plain dialog-id agenda entry resolves via `DialogRef`, which ignores eligibility entirely, so this is what actually skips already-completed dialogs for a `list[str]` agenda. Slot-based agenda items (see below) additionally check eligibility themselves while picking a candidate.

## Dialog Registry

`DialogRegistry.build(dialogs)` (`dialog_registry.py`) indexes a flat list of `MiniDialog` objects by `dialog_id`, by `DIALOG_TYPE`, and by each class's declared `INDEX_ATTRS` (e.g. `ChitchatDialog.topics`, `NarrativeDialog.thread`, `FunctionalDialog.functional_type` via a property). `get_by_id`/`get_by_type`/`get_by_attr` never raise -- they return `None`/`[]` on a miss. `load_dialog_registry(path_or_dir)` in `authoring/loader.py` builds one directly from JSON, isolating per-file/per-doc load errors the same way `load_dialogs()` does.

## Agenda Items and Resolution

`SessionManager` receives:

- `session_agenda`: an ordered list whose entries can be a plain dialog id string, an agenda item dict, or an `AgendaItem` instance.
- `agent`: a configured `ConversationAgent`.
- `dialog_json_path`: a JSON file or directory containing dialog definitions.
- `participant_id`: optional persistent user identifier.
- `session_plan_path`: optional path to a `SessionPlan` that picks a per-session-number agenda instead (see below).

During initialization: dialog JSON is loaded into a `DialogRegistry`; `ConversationState` is created and prior participant continuity is restored when possible; a new session ID is created; if `session_plan_path` is set, it overrides `session_agenda` with the template for this session number.

`coerce_agenda_item()` (`agenda/items.py`) normalizes any raw agenda entry into an `AgendaItem`, mirroring `DialogFactory.from_json()`'s manual type-string dispatch:

| JSON `type` | Class | Resolves to |
| --- | --- | --- |
| `dialog_ref` (or a bare string) | `DialogRef` | the dialog with that id, or `None` if missing (ignores eligibility) |
| `narrative_slot` | `NarrativeSlot` | the lowest-position eligible dialog in `thread` (random tiebreak) |
| `chitchat_slot` | `ChitchatSlot` | the eligible `ChitchatDialog` with the most topic overlap with `topics_of_interest` |
| `functional_slot` | `FunctionalSlot` | a random eligible `FunctionalDialog` of `functional_type` |
| `llm_dialog_ref` | `LLMDialogRef` | a specific `LLMDialog` by id, optionally with `max_turns`/`duration` overrides (shallow-copied) |

Each slot type carries a `SlotBounds` (`agenda/slot_bounds.py`: `count_min`/`count_max`/`duration_min`/`duration_max`, default "resolve exactly once") controlling how many times it may resolve within one agenda pass; `DialogRef`/`LLMDialogRef` have no `bounds` and always resolve at most once.

`resolve_agenda(items, context)` (`agenda/resolver.py`) is a generator that walks the coerced agenda in order, re-queueing bounded items until their `count_max`/`duration_max` ceiling is hit or their `count_min`/`duration_min` floor is met -- ceilings always win over floors. A `None` resolution is skipped, never re-queued. The caller (`SessionManager.run_async()`) calls `context.mark_completed(dialog.dialog_id)` between yields so a re-queued item sees updated eligibility next time.

If `session_agenda` is empty, `SessionManager` runs every loaded dialog in loaded order.

## Session Plans

`SessionPlan`/`SessionTemplate` (`agenda/session_plan.py`) let a `SessionManager` pick a different agenda per session number instead of a single fixed `session_agenda`. `load_session_plan(path)` loads one from JSON (never raises; returns `(plan, errors)`). `SessionPlan.get_template(session_number)` picks the exact `session_index` match, or falls back to the highest-indexed template as a steady-state agenda once `session_number` exceeds every authored template.

## Running Eligible Dialogs

`SessionManager.run()` wraps `run_async()` with setup and cleanup.

Inside `run_async()`:

1. A session-scoped `EventBus` is created and bound to the running asyncio loop.
2. If a screen provider supports `set_event_bus()`, the bus is passed into it.
3. `resolve_agenda(session_agenda, context)` yields dialogs one at a time; each is checked with `is_dialog_eligible()` as a final safety-net gate (see "Dialog Eligibility" above).
4. Eligible dialogs are marked in `ConversationState` and receive the shared event bus.
5. `dialog.run(agent, session_history, topics_of_interest, user_model)` is awaited.
6. Dialog start/end events are appended to `session_history`.
7. The dialog ID is added to `completed_dialogs`, and `context.mark_completed()` keeps the `AgendaContext` in sync so re-queued slot items see it.
8. At the end, topics are condensed through the LLM when available, events are stored, the session is ended, and state is saved.

The same mutable `session_history`, `topics_of_interest`, and `user_model` objects are passed into each dialog. That is how moves in one dialog can affect later eligibility, personalization, and final persistence.

## MiniDialog Runtime

`MiniDialog.run()` is the core move loop:

```text
for each move in self.moves:
    await self._dispatch_move(move)
```

The dialog keeps runtime references to:

- `conversation_agent`: the high-level agent for speech, NLU, LLM, media, motion, and screen helpers.
- `session_history`: list of robot/user/system events.
- `topics_of_interest`: participant interests accumulated during this session.
- `user_model`: participant variables used for personalization and eligibility.
- `current_outcome`: the last resolved outcome for branching.
- `_bus`: the session event bus used by web input moves.

Text personalization happens in `handle_move_say()` and `handle_move_say_options()` by replacing `%variable%` placeholders with values from `user_model`.

Character voices are resolved per move through the optional top-level JSON `characters` object. A move can set `character`, and `_get_voice_settings()` passes the character's `voice_settings` into TTS through the agent/orchestrator.

## ConversationAgent

`ConversationAgent` is a small high-level wrapper around `InteractionOrchestrator`. Dialog code should usually call the agent, not providers directly.

It exposes task-level methods:

- `say(text, **kwargs)`
- `ask_yesno(question, max_attempts=1, **kwargs)`
- `ask_open(question, max_attempts=2, **kwargs)`
- `ask_options(question, options, max_attempts=2, **kwargs)`
- `ask_llm(user_prompt, context_messages, system_prompt, rag_enabled=False, index_name=None)`
- `play_audio()`, `play_motion_sequence()`, `play_animation()`
- screen helpers such as `show_image()`, `show_buttons()`, `hide_input()`, `black()`

Question helpers combine speech and listening. For example, `ask_open()` says the question, then calls `orchestrator.listen()` and returns the transcript. `ask_yesno()` additionally maps NLU intents to `"yes"`, `"no"`, or `"dontknow"`.

## InteractionOrchestrator

`InteractionOrchestrator` is the boundary between dialog logic and concrete services.

It owns:

- `device`
- `tts_provider`
- `nlu_provider`
- optional `llm_provider`
- optional `vector_store`
- optional `screen_provider`
- `InteractionConfig`

`say()` sends text to `tts_provider.speak()` in a worker thread, optionally triggers device speaking animation, logs the utterance, and pushes the robot transcript to the screen provider.

`listen()` signals listening state on the device, calls `nlu_provider.listen()` in a worker thread, logs any transcript, and pushes user transcript to the screen provider.

`request_from_llm()` builds provider-agnostic `Message` objects, optionally adds retrieved snippets from the vector store when RAG is enabled, calls `llm_provider.complete()`, and optionally parses JSON output.

`disconnect()` closes TTS, device, vector store, and screen resources.

## Providers

Providers are protocol-based adapters. Each provider role has a small required interface in `src/nardial/providers/<role>/__init__.py`, with concrete implementations beside it.

| Role | Protocol responsibility | Examples |
| --- | --- | --- |
| Device | Hardware setup, microphone, audio playback, animations, LEDs, listening signals, disconnect | `DesktopAdapter`, `PepperAdapter`, `NaoAdapter`, `AlphaminiAdapter` |
| TTS | Convert text into speech/audio and play it on the configured device | `GoogleTTSProvider`, `ElevenLabsTTSProvider`, `NaoqiTTSProvider`, `NullTTSProvider` |
| NLU | Listen for user input and return `NLUResult(transcript, intent, confidence)` | `DialogflowNLUProvider`, `WrittenKeywordNLUProvider` |
| LLM | Complete a list of chat-like `Message` objects under a system prompt | `OpenAIGPTProvider`, `EchoLLMProvider` |
| Vector store | Ingest/query retrieval snippets for RAG | `RedisVectorStoreProvider`, `NullVectorStoreProvider` |
| Screen | Display transcripts/media/HTML and collect browser input | `SICScreenAdapter`, `PepperTabletScreenAdapter`, `NullScreenProvider` |

Providers should hide service-specific details. The rest of the runtime should only rely on the protocol methods.

## Screen Input and EventBus

The screen system uses `EventBus` for web input.

For `wait_for_web_input`:

1. The move handler shows buttons through `screen_provider.show_buttons(options)`.
2. It subscribes to the session bus with a predicate matching `Event.type == "web_input"` and `data["value"] in options`.
3. The screen provider emits web input events when the browser UI is clicked or submitted.
4. The move waits until an event arrives or the timeout expires.
5. It hides input and resolves the move outcome.

The event bus also supports queued session-level events with interrupt levels, but the currently active runtime path mainly uses move-level subscriptions for web input.

## Conversation State

`ConversationState` tracks continuity and transcripts.

It stores:

- sessions and their events
- ordered dialog IDs per session
- completed dialog IDs across sessions
- persistent user model data
- topics of interest

Participant transcripts are written under `participants/<participant_id>.json` in the current working directory by default. When a `participant_id` is provided, continuity is restored through `UserModel` and saved back at the end of the session.

## Adding a New Move Type

To add a new JSON move:

1. Add a move type constant and optional typed move class in `moves.py`.
2. Add the type to `ALLOWED_MOVE_TYPES` in `authoring/factory.py`.
3. Extend `MoveFactory.validate()` with required fields.
4. Add a branch in `MiniDialog._dispatch_move()`.
5. Implement `MiniDialog.handle_move_<name>()`.
6. Update README/docs and add tests in `tests/`.

If the move talks to hardware or a service, prefer going through `ConversationAgent` or `InteractionOrchestrator` rather than importing a concrete provider.

## Adding a New Provider

To add a provider:

1. Read the role protocol in `src/nardial/providers/<role>/__init__.py`.
2. Implement the required methods in a new module under that provider package.
3. Keep credentials and service-specific configuration in the provider constructor.
4. Return protocol-level types such as `NLUResult` or `Message`.
5. Make cancellation/cleanup safe where relevant (`cancel()`, `close()`).
6. Add tests using a local/null implementation pattern where possible.

Provider implementations should be swappable. A session should not need different dialog JSON when switching from desktop to Pepper, from Google TTS to ElevenLabs, or from terminal NLU to Dialogflow.

## Common Extension Points

- Change dialog authoring schema: `authoring/factory.py`
- Change move runtime behavior: `mini_dialogs.py`
- Change eligibility rules: `eligibility.py`
- Change agenda item types, resolution, or session plans: `agenda/*.py`
- Change persistence and continuity: `conversation_state.py`, `user_model.py`
- Change speech/listening/LLM orchestration: `conversation_agent.py`, `interaction_orchestrator.py`
- Add hardware/service integrations: `providers/**`
- Add screen behavior: `providers/screen/**`, `events/**`, `providers/screen/web/static/screen.js`
