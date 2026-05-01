# NarDialPy

**NarDialPy** is a Python framework for building and running **narrative-driven dialog systems**.

It enables you to design structured conversations using declarative dialog definitions, while integrating with modern voice, NLU, and LLM services.

---

## Features

NarDialPy combines:

- **Dialog blocks (JSON-based)**  
  Define conversations declaratively using JSON files, specifying moves like `say`, `ask_open`, `ask_yesno`, `ask_options`, and branching logic. 

- **Session Manager**  
  Executes dialog agendas and controls conversation flow.

- **Service integrations** (via `social-interaction-cloud`)
  - Dialogflow (NLU)
  - Google TTS (speech synthesis)
  - OpenAI GPT (LLM-based responses)

- **Ready-to-run demos**  
  Explore complete example conversations in the `examples/` directory. You can find additional demos in the [SIC Applications repository](https://github.com/Social-AI-VU/sic_applications/tree/main/demos/nardial)

---

## Prerequisites

Before you begin, make sure you have:

### 1. A Python IDE
Recommended options: [PyCharm](https://www.jetbrains.com/help/pycharm/installation-guide.html) (Professional or Community Edition) and [VS Code](https://code.visualstudio.com/download) (free and open-source)

### 2. Python
- Version: **3.10 ≤ Python ≤ 3.12**
- Download: https://www.python.org/downloads/
- ⚠️ Ensure Python is added to your system `PATH`

### 3. Social Interaction Cloud (SIC)

NarDialPy relies on `social-interaction-cloud` for services such as Speech-to-Text, Text-to-Speech,  NLU, and Redis-based communication. 
**Installation guide:**
https://social-ai-vu.github.io/social-interaction-cloud/tutorials/1_installation.html#installation-guide

---

## Using NarDialPy

This section shows how to build and run a custom conversation using NarDialPy.

At a high level, you will:
1. Select a device/robot (e.g., Desktop or Pepper)
2. Configure interaction settings (speech, APIs, etc.)
3. Create a `ConversationAgent`
4. Define a session agenda (conversation flow)
5. Provide dialog definitions (JSON)
6. Run the session

---

### Example: Minimal Conversation Setup

```python
from sic_framework.devices.common_desktop.desktop_speakers import SpeakersConf
from sic_framework.devices.desktop import Desktop

from nardial.conversation_agent import ConversationAgent
from nardial.interaction_orchestrator import InteractionConfig
from nardial.session_manager import SessionManager

# 1. Select device (Desktop uses your mic + speakers)
device = Desktop(speakers_conf=SpeakersConf(sample_rate=22050))

# 2. Configure interaction
interaction_config = InteractionConfig(google_keyfile_path="conf/google/google_keyfile.json")

# 3. Create agent
agent = ConversationAgent(device_manager=device, int_config=interaction_config)

# 4. Define conversation flow (dialogs to run in order)
session_agenda = ["welcome_and_name", "plan_activity", "structured_goodbye"]

# 5. Create session manager
session_manager = SessionManager(
    session_agenda=session_agenda,
    agent=agent,
    dialog_json_path="dialogs.json",
    participant_id="user_1"
)

# 6. Run the conversation
session_manager.run()
```
---

###  Dialog Definitions (JSON)

Dialogs are defined declaratively in a JSON file. Each dialog contains:

* An `id`
* A `type` (`functional`, `chitchat`, `narrative`, `llm`)
* A sequence of **moves**

Example:

```json
[
  {
    "id": "welcome_and_name",
    "type": "functional",
    "functional_type": "greeting",
    "moves": [
      { "type": "say", "text": "Hi! I am your planning assistant." },
      {
        "type": "ask_open",
        "text": "What is your name?",
        "set_variable": "first_name",
        "outcomes": { "*": "name_provided" }
      },
    ]
  }
]
```

---

### Core Concepts

#### 1. Session Agenda

Defines the order of dialogs:

```python
session_agenda = ["welcome_and_name", "plan_activity", "structured_goodbye"]
```

#### 2. Moves

Basic building blocks of dialogs:

* `say` — speak text
* `ask_open` — open question
* `ask_yesno` — yes/no question
* `ask_options` — multiple choice
* `branch` — conditional logic
* `ask_llm` — generate responses using GPT
* `play` — play audio
* `animation` / `motion_sequence` — robot behaviors

#### 3. Variables

You can store and reuse user input:

```json
{ "set_variable": "first_name" }
```

Then reuse it later:

```json
"Hello %first_name%!"
```

---

### Customization Options

You can easily adapt behavior:

* Change language:

  ```python
  InteractionConfig(language="nl")
  ```

* Use microphone instead of keyboard:

  ```python
  keyboard_input=False
  ```

* Adjust voice and speech settings (via Google TTS config)

* Enable robot behaviors (animations, gestures)

---

### Advanced Features

NarDialPy also supports:

* Dynamic branching based on user state
* Topic tracking and personalization
* LLM-generated follow-ups
* Dialog dependencies and sequencing
* Audio + motion integration (for robots like Pepper)

---

### Tip

Keep your dialog logic in JSON and your execution logic in Python.
This separation makes your system:

* Easier to maintain
* Easier to iterate on
* Accessible to non-programmers



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
   - Setup guide: https://socialrobotics.atlassian.net/wiki/spaces/CBSR/pages/2205155343/Getting+a+google+dialogflow+key
2. Create an OpenAI API key and save to:
   `conf/openai/.openai_env`
   - API keys: https://platform.openai.com/api-keys

Example `.openai_env`:

```bash
OPENAI_API_KEY="your key"
```

> Never commit or share credential files.

### 3) Configure the Dialogflow agent

In your Dialogflow agent:
- Remove default intents.
- Go to **Settings → Import and Export**.
- Import `resources/droomrobot_dialogflow_agent.zip` to load the intents/entities used by the demo.

### 4) Start required services

In separate terminals:

```bash
conf/redis/redis-server.exe conf/redis/redis.conf
run-dialogflow
run-google-tts
run-gpt
```

### 5) Run the demo conversation

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

---
