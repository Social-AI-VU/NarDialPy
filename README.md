# NarDialPy

NarDialPy is a Python framework for building and running **narrative social-robot conversations**.

It combines:
- **Dialog blocks** written as JSON (`functional`, `narrative`, and `chitchat` dialogs)
- **A session manager** that executes a chosen dialog agenda
- **Voice / NLU / LLM services** (Dialogflow, Google TTS, OpenAI GPT via `social-interaction-cloud`)

The repository includes a complete demo conversation in the `examples/` folder that shows how these parts work together.

## Repository layout

- `src/nardial/` – core runtime (dialog loading, move execution, session flow)
- `examples/demo_general_conversation.py` – runnable demo entrypoint
- `examples/dialogs.json` – demo dialogs (conversation content)
- `web/authoring/` – browser-based dialog authoring UI
- `tests/` – unit tests for move handling and dialog behavior

## How the demo conversation works

The demo script (`examples/demo_general_conversation.py`) creates a `ConversationAgent`, then runs a fixed agenda through `SessionManager`:

```python
session_agenda = ["greeting", "hero_can_dream_1", "dream12", "goodbye"]
```

Those dialog IDs are resolved from `examples/dialogs.json`, which contains declarative move sequences such as:
- `say`
- `ask_open`
- `ask_yesno`
- `ask_options`
- `branch` (outcome-based branching)

This makes it easy to edit conversation behavior without changing Python code.

## Quick start (demo)

### 1) Install

From the repository root:

```bash
pip install -e .
```

Install/update cloud integrations used by the demo:

```bash
pip install --upgrade social-interaction-cloud[dialogflow,google-tts,openai-gpt]
```

### 2) Configure credentials

1. Create Dialogflow credentials and save to:
   `conf/dialogflow/google_keyfile.json`
2. Create an OpenAI API key and save to:
   `conf/openai/.openai_env`

Example `.openai_env`:

```bash
OPENAI_API_KEY="your key"
```

> Never commit or share credential files.

### 3) Start required services

In separate terminals:

```bash
conf/redis/redis-server.exe conf/redis/redis.conf
run-dialogflow
run-google-tts
run-gpt
```

### 4) Run the demo conversation

From `examples/`:

```bash
python demo_general_conversation.py
```

Use a supported device configuration in the script (desktop by default).

## Customizing conversations

- Edit `examples/dialogs.json` to add or modify dialog blocks.
- Update the `session_agenda` in `examples/demo_general_conversation.py` to change the order/content of a run.
- Use `web/authoring/` if you prefer editing dialogs through the browser UI.

## Development

Run tests from the repository root:

```bash
python -m pytest -q
```
