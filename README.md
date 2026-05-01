# NarDialPy

**NarDialPy** is a Python package for building and running **narrative-driven, structured dialog systems** — designed for social robots and conversational agents.

It lets you author complete conversations declaratively in JSON, then drive them from Python using voice, NLU, and LLM services. The package handles session flow, branching logic, topic tracking, and personalization so you can focus on what the robot says and how conversations unfold.

---

## Table of Contents

1. [What is nardial?](#what-is-nardial)
2. [Prerequisites & Setup](#prerequisites--setup)
3. [Defining Dialogs in JSON](#defining-dialogs-in-json)
   - [Dialog Structure](#dialog-structure)
   - [Dialog Types](#dialog-types)
   - [Move Types](#move-types)
   - [Key JSON Attributes](#key-json-attributes)
4. [Running a Session](#running-a-session)
5. [Demos](#demos)
6. [Development](#development)

---

## What is nardial?

The `nardial` package provides the building blocks for authoring and executing multi-turn conversations:

| Component | Description |
|---|---|
| **Dialog JSON** | Conversations are written as structured JSON files. Each file holds one or more *dialogs*, each containing a sequence of *moves* that the robot performs. |
| **Session Manager** | Loads your dialog JSON, resolves a session agenda, and runs dialogs in order — checking dependencies and tracking state. |
| **ConversationAgent** | The runtime bridge to the hardware: it calls TTS, STT, LLM, and motion services on your chosen device. |
| **Dialog Logic** | Checks eligibility rules (dependencies, variable requirements) before executing each dialog. |

Typical use case:

- A social robot (Pepper, NAO, desktop agent) runs a structured conversation with a child or adult participant.
- The conversation is broken into named dialog blocks (greeting, story, chitchat, goodbye) authored in JSON.
- Python code wires up the device, credentials, and agenda — the JSON drives the actual content and branching.

Additional community demos are in the [SIC Applications repository](https://github.com/Social-AI-VU/sic_applications/tree/main/demos/nardial).

---

## Prerequisites & Setup

### 1. Python IDE

Recommended: [PyCharm](https://www.jetbrains.com/help/pycharm/installation-guide.html) or [VS Code](https://code.visualstudio.com/download)

### 2. Python

- Version: **3.10 ≤ Python ≤ 3.12**
- Download: https://www.python.org/downloads/
- ⚠️ Ensure Python is added to your system `PATH`

### 3. Social Interaction Cloud (SIC)

NarDialPy relies on `social-interaction-cloud` for Speech-to-Text, Text-to-Speech, NLU, and Redis-based communication.

**Installation guide:** https://social-ai-vu.github.io/social-interaction-cloud/tutorials/1_installation.html

### 4. Install NarDialPy

From the repository root:

```bash
pip install -e .
```

Install the cloud integrations needed for the demos:

```bash
pip install --upgrade social-interaction-cloud[dialogflow,google-tts,openai-gpt]
```

### 5. Configure Credentials

**Google / Dialogflow credentials** — save to `conf/google/google_keyfile.json`:
- Setup guide: https://socialrobotics.atlassian.net/wiki/spaces/CBSR/pages/2205155343/Getting+a+google+dialogflow+key

**OpenAI API key** — create `conf/openai/.openai_env`:

```bash
OPENAI_API_KEY="your key"
```

> ⚠️ Never commit credential files to version control.

**Dialogflow agent** — import intents/entities used by the demos:
- Remove default intents in your Dialogflow project.
- Go to **Settings → Import and Export**.
- Import `resources/droomrobot_dialogflow_agent.zip`.

### 6. Start Required Services

Run these in separate terminals before starting any demo:

```bash
# Windows
conf/redis/redis-server.exe conf/redis/redis.conf

# macOS / Linux
redis-server conf/redis/redis.conf
```

```bash
run-dialogflow
run-google-tts
run-gpt
```

---

## Defining Dialogs in JSON

All conversation content lives in a JSON file (or directory of JSON files). The file is a JSON array of dialog objects.

### Dialog Structure

Every dialog has the following shared fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | ✅ | Unique identifier referenced in `session_agenda` and `dependencies` |
| `type` | string | ✅ | Dialog type: `"functional"`, `"chitchat"`, `"narrative"`, or `"llm_based"` |
| `moves` | array | ✅ | Ordered list of move objects the robot will perform |
| `dependencies` | array of strings | | Dialog IDs that must have been completed before this dialog may run |
| `variable_dependencies` | array | | Variables that must exist in the user model before this dialog may run |

```json
{
  "id": "greeting",
  "type": "functional",
  "functional_type": "greeting",
  "moves": [
    { "type": "say", "text": "Hi! I am your robot assistant." }
  ]
}
```

---

### Dialog Types

#### `functional`

Utility dialogs for session management — greetings, farewells, and structural transitions.

| Extra field | Type | Required | Description |
|---|---|---|---|
| `functional_type` | string | ✅ | `"greeting"` or `"farewell"` |

```json
{
  "id": "welcome",
  "type": "functional",
  "functional_type": "greeting",
  "moves": [
    { "type": "say", "text": "Hello! What is your name?" },
    {
      "type": "ask_open",
      "text": "Please tell me your name.",
      "set_variable": "first_name",
      "outcomes": { "*": "name_provided" },
      "default_outcome": "name_missing"
    }
  ]
}
```

---

#### `chitchat`

Short, theme-based conversations on everyday topics. Chitchat dialogs can be seeded with topics of interest so the system selects contextually relevant ones.

| Extra field | Type | Required | Description |
|---|---|---|---|
| `theme` | string | ✅ | Broad category (e.g. `"nature"`, `"animals"`, `"robots"`) |
| `topics` | array of strings | | Specific keywords used for relevance matching |

```json
{
  "id": "favorite_animal",
  "type": "chitchat",
  "theme": "animals",
  "topics": ["animals", "pets"],
  "moves": [
    {
      "type": "ask_open",
      "text": "What is your favorite animal?",
      "set_variable": "favorite_animal",
      "add_interest_from_answer": true
    },
    { "type": "say", "text": "I like %favorite_animal% too!" }
  ]
}
```

---

#### `narrative`

Story-based dialogs that belong to a named thread and must be delivered in a specific order. Use `position` to sequence them and `dependencies` to enforce ordering.

| Extra field | Type | Required | Description |
|---|---|---|---|
| `thread` | string | ✅ | Story thread name (e.g. `"dreams"`) — groups related narrative dialogs |
| `position` | integer | ✅ | Order within the thread (1, 2, 3, …) |

```json
{
  "id": "dream_intro",
  "type": "narrative",
  "thread": "dreams",
  "position": 1,
  "moves": [
    { "type": "say", "text": "Sometimes I make up stories when I'm turned off." },
    {
      "type": "ask_yesno",
      "text": "Do you ever dream?",
      "set_variable": "dreams_yesno",
      "outcomes": { "yes": "dreams_yes" },
      "default_outcome": "dreams_no"
    },
    {
      "type": "branch",
      "on": "outcome",
      "cases": {
        "dreams_yes": [
          { "type": "say", "text": "That's great! Dreams are fascinating." }
        ],
        "dreams_no": [
          { "type": "say", "text": "No problem, I'll tell you about mine!" }
        ]
      }
    }
  ]
}
```

---

#### `llm_based`

A fully LLM-driven dialog where the robot and user engage in a free-form multi-turn exchange guided by a system prompt. No `moves` array is needed — the LLM generates all responses.

| Extra field | Type | Required | Description |
|---|---|---|---|
| `prompt` | string | ✅ | System prompt guiding the LLM's behavior |
| `max_turns` | integer | | Maximum back-and-forth turns (default: 5) |
| `speak_first` | boolean | | If `true` (default), the robot speaks first; if `false`, it listens first |
| `duration` | number | | Time limit in seconds for the whole exchange |
| `quit_phrases` | array of strings | | User utterances that end the exchange early |
| `quit_signal` | string | | Token the LLM can embed to signal it wants to end (default: `"<<QUIT>>"`) |
| `rag_enabled` | boolean | | Enable Retrieval-Augmented Generation (RAG). When `true`, the LLM retrieves context from a vector index before generating responses. Requires configuring a compatible RAG backend through `social-interaction-cloud`. |
| `index_name` | string | Required when `rag_enabled` is `true` | Name of the RAG index to query |

```json
{
  "id": "free_chat",
  "type": "llm_based",
  "prompt": "You are a friendly robot. Chat warmly with the child about their day. Ask follow-up questions. End with <<QUIT>> when the topic is exhausted.",
  "max_turns": 6,
  "speak_first": true,
  "quit_signal": "<<QUIT>>",
  "quit_phrases": ["goodbye", "stop", "done"],
  "moves": []
}
```

---

### Move Types

Moves are the individual steps inside a dialog's `moves` array. The robot executes them in order.

---

#### `say`

Speaks a piece of text. Variable placeholders (`%variable_name%`) are replaced at runtime.

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | ✅ | `"say"` |
| `text` | string | ✅ | Text to speak. Use `%var%` to insert stored variables. |

```json
{ "type": "say", "text": "Nice to meet you, %first_name%!" }
```

---

#### `ask_open`

Asks a free-text question and listens for any spoken reply. The answer can be stored in a variable and used to drive branching.

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | ✅ | `"ask_open"` |
| `text` | string | ✅ | The question to ask |
| `set_variable` | string | | Stores the extracted answer in the user model under this name |
| `outcomes` | object | | Maps answer values to outcome labels. Use `"*"` as a wildcard for any non-empty answer. |
| `default_outcome` | string | | Outcome label when no answer or no match is found |
| `add_interest_from_answer` | boolean | | If `true`, adds the answer to the user's topics of interest |
| `llm_followup` | string | | System prompt for an LLM-generated follow-up sentence after the user replies |

```json
{
  "type": "ask_open",
  "text": "What is your favorite color?",
  "set_variable": "favorite_color",
  "add_interest_from_answer": true,
  "outcomes": { "*": "got_color" },
  "default_outcome": "no_color"
}
```

---

#### `ask_yesno`

Asks a yes/no question. The detected intent (`"yes"`, `"no"`, `"dontknow"`) drives branching.

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | ✅ | `"ask_yesno"` |
| `text` | string | ✅ | The yes/no question to ask |
| `set_variable` | string | | Stores the answer in the user model |
| `outcomes` | object | | Maps `"yes"` / `"no"` / `"dontknow"` to outcome labels |
| `default_outcome` | string | | Outcome label used as fallback |
| `add_interest` | string | | Topic added to interest list when the user answers `"yes"` |
| `llm_followup` | string | | System prompt for an LLM-generated follow-up sentence |

```json
{
  "type": "ask_yesno",
  "text": "Do you like dogs?",
  "set_variable": "likes_dogs",
  "add_interest": "dogs",
  "outcomes": { "yes": "likes_dogs_yes" },
  "default_outcome": "likes_dogs_no"
}
```

---

#### `ask_options`

Presents a multiple-choice question. The selected option drives branching and can be stored as a variable.

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | ✅ | `"ask_options"` |
| `text` | string | ✅ | The question to ask |
| `options` | array of strings | ✅ | The choices presented to the user |
| `set_variable` | string | | Stores the selected option in the user model |
| `outcomes` | object | | Maps option values to outcome labels |
| `default_outcome` | string | | Outcome label when nothing matches |
| `add_interest_from_variable` | string | | After storing, adds the named variable's value as a topic of interest |
| `llm_followup` | string | | System prompt for an LLM-generated follow-up sentence |

```json
{
  "type": "ask_options",
  "text": "Which activity do you prefer — reading, walking, or cooking?",
  "options": ["reading", "walking", "cooking"],
  "set_variable": "preferred_activity",
  "outcomes": {
    "reading": "chose_reading",
    "walking": "chose_walking",
    "cooking": "chose_cooking"
  },
  "default_outcome": "chose_other"
}
```

---

#### `ask_llm`

Starts a multi-turn LLM-driven exchange *within* an otherwise scripted dialog. Useful for a single free-form segment inside a structured conversation.

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | ✅ | `"ask_llm"` |
| `prompt` | string | ✅ | System prompt for the LLM |
| `max_turns` | integer | | Maximum turns (default: 5) |
| `set_variable` | string | | Stores the user's last reply in the user model |
| `quit_phrases` | array of strings | | User phrases that end the exchange early |
| `quit_signal` | string | | Token the LLM emits to signal it wants to stop |

```json
{
  "type": "ask_llm",
  "prompt": "Ask one follow-up question to help the user commit to their plan for today. Keep it short and friendly.",
  "max_turns": 1,
  "set_variable": "plan_commitment"
}
```

---

#### `branch`

Selects and executes a list of sub-moves based on the current outcome or the value of a user model variable.

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | ✅ | `"branch"` |
| `on` | string | ✅ | `"outcome"` to branch on the last question's result, or a variable name to branch on its stored value |
| `cases` | object | ✅ | Maps condition values to arrays of sub-moves |

```json
{
  "type": "branch",
  "on": "outcome",
  "cases": {
    "chose_reading": [
      { "type": "say", "text": "Reading is a wonderful way to relax." }
    ],
    "chose_walking": [
      { "type": "say", "text": "A walk sounds refreshing!" }
    ]
  }
}
```

Branching on a stored variable (e.g. to react to an answer from an earlier dialog):

```json
{
  "type": "branch",
  "on": "energy_level",
  "cases": {
    "high": [{ "type": "say", "text": "Start with a longer session." }],
    "low":  [{ "type": "say", "text": "Begin with just 10 calm minutes." }]
  }
}
```

---

#### `play`

Plays an audio file through the device's speakers.

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | ✅ | `"play"` |
| `audio` | string | ✅ | Path to the audio file (`.wav` or `.mp3`) |

```json
{ "type": "play", "audio": "audio/chime.wav" }
```

---

#### `motion_sequence`

Plays a predefined motion sequence on the robot (Pepper / NAO).

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | ✅ | `"motion_sequence"` |
| `motion_sequence` | string | ✅ | Path or name of the motion sequence file |

```json
{ "type": "motion_sequence", "motion_sequence": "motions/Stand/Emotions/Positive/Happy_1" }
```

---

#### `animation`

Triggers a named animation behavior on the robot.

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | ✅ | `"animation"` |
| `animation_name` | string | ✅ | Name of the animation to play |

```json
{ "type": "animation", "animation_name": "animations/Stand/Gestures/Enthusiastic_4" }
```

---

### Key JSON Attributes

| Attribute | Where used | Description |
|---|---|---|
| `id` | dialog | Unique dialog identifier |
| `type` | dialog | Dialog type: `functional`, `chitchat`, `narrative`, `llm_based` |
| `functional_type` | functional dialog | `"greeting"` or `"farewell"` |
| `thread` | narrative dialog | Story thread name |
| `position` | narrative dialog | Order within the thread |
| `theme` | chitchat dialog | Broad topic category |
| `topics` | chitchat dialog | Keywords for relevance matching |
| `prompt` | llm_based dialog / `ask_llm` | LLM system prompt |
| `moves` | dialog | Ordered list of move objects |
| `dependencies` | dialog | Dialog IDs that must be completed first |
| `variable_dependencies` | dialog | Variables that must exist in the user model |
| `set_variable` | move | Saves the user's answer into the user model |
| `outcomes` | move | Maps answers/intents to outcome labels for branching |
| `default_outcome` | move | Fallback outcome when no match is found |
| `add_interest` | `ask_yesno` move | Adds a fixed topic when user says yes |
| `add_interest_from_answer` | `ask_open` move | Adds the spoken answer as a topic of interest |
| `add_interest_from_variable` | `ask_open` / `ask_options` move | Adds the stored variable's value as a topic |
| `llm_followup` | ask moves | System prompt for an inline LLM follow-up response |
| `%variable%` | `text` values | Placeholder replaced at runtime with the stored variable value |

---

## Running a Session

A minimal Python script wires up the device, loads the dialog JSON, and runs the session:

```python
from sic_framework.devices.common_desktop.desktop_speakers import SpeakersConf
from sic_framework.devices.desktop import Desktop

from nardial.conversation_agent import ConversationAgent
from nardial.interaction_orchestrator import InteractionConfig
from nardial.session_manager import SessionManager

# 1. Select device (Desktop uses your mic + speakers)
device = Desktop(speakers_conf=SpeakersConf(sample_rate=22050))

# 2. Configure interaction (speech, APIs, language)
interaction_config = InteractionConfig(
    google_keyfile_path="conf/google/google_keyfile.json",
    keyboard_input=True,   # Set False to use microphone
    # language="nl",       # change language for TTS + ASR + Dialogflow
)

# 3. Create the conversational agent
agent = ConversationAgent(device_manager=device, int_config=interaction_config)

# 4. Define the session agenda — ordered list of dialog IDs to run
session_agenda = ["welcome_and_name", "plan_activity", "structured_goodbye"]

# 5. Create the session manager — loads dialogs and tracks state
session_manager = SessionManager(
    session_agenda=session_agenda,
    agent=agent,
    dialog_json_path="dialogs.json",
    participant_id="user_1"
)

# 6. Run the conversation
session_manager.run()
```

**SessionManager** handles:
- Loading dialogs from JSON
- Checking dependency and variable eligibility before each dialog
- Tracking session history, topics of interest, and the user model
- Persisting conversation state between sessions

---

## Demos

Two ready-to-run demos are included in the `examples/` directory:

### Demo 1 — General Conversation (`demo_general_conversation.py`)

A simple four-step conversation using a mix of narrative and functional dialogs:

```python
session_agenda = ["greeting", "hero_can_dream_1", "dream12", "goodbye"]
```

Dialog content comes from `examples/dialogs.json`, which showcases `say`, `ask_open`, `ask_yesno`, `ask_options`, and `branch` moves. Edit the JSON to change what the robot says without touching Python.

**Run from `examples/`:**

```bash
python demo_general_conversation.py
```

---

### Demo 2 — Structured Conversation (`demo_structured_conversation.py`)

A more complete example that demonstrates all dialog types and move types, including `ask_llm`, `play`, `motion_sequence`, and `animation`:

```python
session_agenda = [
    "welcome_and_name",        # functional greeting — collects user name
    "plan_activity",           # chitchat — options + branching + llm_followup
    "adapt_to_user_energy",    # narrative — variable branching + robot motion
    "structured_goodbye",      # functional farewell — uses stored variables
]
```

Dialog content comes from `examples/structured_conversation_dialogs.json`.

**Run from `examples/`:**

```bash
python demo_structured_conversation.py
```

---

## Development

Run tests from the repository root:

```bash
python -m pytest -q
```

---
