# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

NarDialPy (`nardial`) is a Python package for authoring and running narrative-driven, structured dialog systems for social robots and conversational agents. Conversations are authored declaratively in JSON files and executed at runtime by Python code that drives voice, NLU, LLM, motion, and browser-based screen services. Package published to PyPI as `nardial`.

## Commands

Install for development (editable, with test deps):

```bash
pip install -e ".[dev]"
```

Run the full test suite (from repo root):

```bash
python -m pytest -q
```

Run a single test file or test:

```bash
python -m pytest tests/test_moves.py -q
python -m pytest tests/test_moves.py::test_name -q
```

`pytest-asyncio` is set to `asyncio_mode = "auto"` (see `pyproject.toml`), so `async def test_...` functions run without needing `@pytest.mark.asyncio`.

`tests/conftest.py` stubs out `sic_framework` module internals and forces `UserModel` into in-memory mode (no live Redis needed) via an autouse fixture — tests do not require Redis, Dialogflow, or other live services to run. It also provides `make_mock_agent`, a factory for a mocked `ConversationAgent` used across move/dialog tests.

There is no configured linter/formatter (no ruff/black/flake8 config in `pyproject.toml`) — match existing code style.

CI (`.github/workflows/publish.yml`) runs `python -m pytest -q` on release and only then builds/publishes to PyPI on tagged releases (`vX.Y.Z`).

## Architecture

Full details: `docs/DEVELOPER_README.md` (read this before making runtime/architecture changes — it documents the eligibility rules, event bus, and extension points in depth). The README's "Defining Dialogs in JSON" section is the authoritative reference for dialog/move JSON schema.

### Runtime pipeline

```
JSON dialog files
  -> authoring loader/factory   (src/nardial/authoring/loader.py, factory.py)
  -> MiniDialog objects with move dictionaries  (src/nardial/mini_dialogs.py)
  -> DialogRegistry indexed by id/type/attrs    (src/nardial/dialog_registry.py)
  -> SessionManager: resolve_agenda() over the session agenda  (src/nardial/agenda/resolver.py)
  -> EligibilityPolicy / eligibility rules       (src/nardial/eligibility.py)
  -> MiniDialog.run() -> move dispatch handlers
  -> ConversationAgent convenience API            (src/nardial/conversation_agent.py)
  -> InteractionOrchestrator                      (src/nardial/interaction_orchestrator.py)
  -> providers: device, TTS, NLU, LLM, vector store, screen  (src/nardial/providers/**)
  -> ConversationState persistence                 (src/nardial/conversation_state.py)
```

Key design point: dialog JSON moves are **not** parsed into move objects at load time — they stay as plain dicts on `MiniDialog.moves`. Individual move handlers convert a move dict via `MoveX.from_dict()` (from `moves.py`) only when they need typed access. The dispatcher is `MiniDialog._dispatch_move()`, which reads `move["type"]` and calls a handler like `handle_move_say()`, `handle_move_ask_open()`, `handle_move_show_image()`.

Four dialog types (`functional`, `chitchat`, `narrative`, `llm_based`) map to runtime classes `FunctionalDialog`, `ChitchatDialog`, `NarrativeDialog`, `LLMDialog`, each requiring type-specific fields (`functional_type`; `topics`; `thread`/`position`; `prompt`).

Dialog types are looked up in a registry (`src/nardial/dialog_types.py`, `@register_dialog_type`); each class owns its type-specific JSON via `validate_doc()`/`from_doc()`/`to_doc()`, and `DialogFactory` only handles shared fields. Custom types are subclasses, registered in Python or declared in JSON with a `define_type` doc (`DialogTypeFactory` in `authoring/factory.py`). Type definitions live in separate files from dialogs and are loaded first via `load_dialog_types()` / `SessionManager(dialog_types_path=...)`; `load_dialogs()` rejects `define_type` docs. Eligibility rules are likewise registered by name (`register_rule`/`build_rule` in `eligibility.py`) so JSON can reference them.

Dialog eligibility is a composable `EligibilityPolicy` of `EligibilityRule`s (`src/nardial/eligibility.py`), evaluated by the free function `is_dialog_eligible(dialog, context, policy=None)` against an `AgendaContext`/`EligibilityContext`. Each dialog class declares its own default rules via `DEFAULT_ELIGIBILITY` (see `mini_dialogs.py`), gating on: not already completed (except functional dialogs, which skip this), all `dependencies` completed, all `variable_dependencies` present in the user model, and — for narrative dialogs — all earlier `position`s in the same `thread` completed. A session agenda is a list of dialog ids / agenda item dicts / `AgendaItem` instances (`src/nardial/agenda/items.py`: `DialogRef`, `NarrativeSlot`, `ChitchatSlot`, `FunctionalSlot`, `LLMDialogRef`); `resolve_agenda()` walks it yielding dialogs, and `SessionManager.run_async()` re-checks `is_dialog_eligible()` as a final safety-net gate before running each one. The same mutable `session_history`, `topics_of_interest`, and `user_model` objects are threaded through every dialog in a session, so moves in one dialog affect later eligibility/personalization/persistence.

### Providers are swappable protocol implementations

Each provider role (`device`, `tts`, `nlu`, `llm`, `vector_store`, `screen`) has a protocol defined in `src/nardial/providers/<role>/__init__.py`, with one or more concrete adapters beside it (e.g. `DesktopAdapter`/`PepperAdapter`/`NaoAdapter`/`AlphaminiAdapter` for device; `GoogleTTSProvider`/`ElevenLabsTTSProvider`/`NaoqiTTSProvider`/`NullTTSProvider` for TTS). `ConversationAgent` and `InteractionOrchestrator` should only depend on protocol methods, never on a specific implementation — this is what lets the same dialog JSON run unmodified on desktop vs. Pepper, or Google TTS vs. ElevenLabs. New move/dialog code should go through `ConversationAgent`/`InteractionOrchestrator`, not import a concrete provider directly.

### Screen/web input uses an EventBus

`wait_for_web_input` moves show buttons via the screen provider, subscribe to a session-scoped `EventBus` (`src/nardial/events/bus.py`) for `web_input` events matching accepted values, and resolve on event or timeout. The browser-side counterpart lives in `src/nardial/providers/screen/web/static/screen.js`.

### Adding a new move type

1. Add the move type constant / typed helper class in `moves.py`.
2. Add it to `ALLOWED_MOVE_TYPES` in `authoring/factory.py` and extend `MoveFactory.validate()`.
3. Add a branch in `MiniDialog._dispatch_move()` and implement `handle_move_<name>()` in `mini_dialogs.py`.
4. Update README.md's move-type table and add tests.

### Adding a new provider

Implement the role's protocol from `src/nardial/providers/<role>/__init__.py`, keep credentials/config in the constructor, return protocol-level types (`NLUResult`, `Message`), and implement safe `cancel()`/`close()` where relevant.

## Credentials / local services

Credentials live under `conf/` (`conf/google/google_keyfile.json`, `conf/openai/.openai_env`) and are gitignored — never commit them. Some demos/integration paths expect Redis (`conf/redis/redis-server.exe conf/redis/redis.conf`) and SIC services (`run-dialogflow`, `run-google-tts`, `run-gpt`) running locally; unit tests under `tests/` do not need any of this (see conftest stubbing above).
