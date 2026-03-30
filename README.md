# NarDialPy

Python implementation of the **Narrative Dialog Management System** — a framework for building structured, multi-turn robot conversations. Dialogs are composed of typed *moves* (say, ask, play audio, animate…) and are grouped into *narrative*, *chitchat*, and *functional* categories. The `DialogLogic` scheduler assembles session-level dialog blocks from a shared dialog pool and tracks per-participant continuity across sessions.

---

## Table of Contents

1. [Concepts](#concepts)
2. [Project Structure](#project-structure)
3. [Installation](#installation)
4. [Quick Start](#quick-start)
5. [Dialog JSON Format](#dialog-json-format)
   - [Dialog Types](#dialog-types)
   - [Move Types](#move-types)
   - [Variable Substitution](#variable-substitution)
   - [Branching](#branching)
6. [Authoring Tools](#authoring-tools)
   - [Loading & Saving Dialogs](#loading--saving-dialogs)
   - [Web-based Dialog Editor](#web-based-dialog-editor)
   - [HTML Report Export](#html-report-export)
7. [Session Scheduling](#session-scheduling)
8. [ConversationState](#conversationstate)
9. [ConversationAgent](#conversationagent)
10. [Running Tests](#running-tests)
11. [Demo Setup (Full Robot)](#demo-setup-full-robot)

---

## Concepts

NarDialPy organises robot conversations into **mini-dialogs** — self-contained interaction units that the robot can execute with a user. Each dialog contains an ordered list of **moves** describing what the robot says or does and how it reacts to user responses.

| Concept | Description |
|---|---|
| **Move** | A single step in a dialog (say text, ask a question, play audio, …) |
| **MiniDialog** | A named, ordered sequence of moves |
| **FunctionalDialog** | Utility dialogs: greeting, farewell |
| **NarrativeDialog** | Story-driven dialogs grouped into *threads* with explicit ordering |
| **ChitchatDialog** | Short topic-driven conversations grouped by *theme* |
| **LLMDialog** | Open-ended LLM-driven exchanges with a configurable system prompt |
| **DialogLogic** | Stateless scheduler that selects a session block from the dialog pool |
| **ConversationState** | Persistent, per-participant conversation tracker |
| **ConversationAgent** | Device abstraction wrapping TTS, ASR (Dialogflow), and LLM |

---

## Project Structure

```
NarDialPy/
├── src/
│   ├── moves.py                 # Move classes and type constants
│   ├── mini_dialogs.py          # MiniDialog and subclasses; move execution
│   ├── dialog.py                # DialogLogic: session scheduling helpers
│   ├── conversation_state.py    # Per-participant state & transcripts
│   ├── conversation_agent.py    # Robot device wrapper (TTS/ASR/LLM)
│   └── authoring/
│       ├── factory.py           # MoveFactory & DialogFactory (validate/create/serialize)
│       ├── loader.py            # load_dialogs / save_dialogs helpers
│       └── export_html.py       # Export dialogs.json → HTML report
├── assets/
│   └── dialogs/dialogs.json     # Sample dialog pool
├── web/
│   └── authoring/               # Browser-based dialog editor
├── tests/                       # pytest test suite
├── demos/                       # Runnable demo scripts
└── robotstories_en/             # Example dialog JSON files (English)
```

---

## Installation

```bash
# Core library (no robot hardware needed for authoring/testing)
pip install pytest

# Full robot support (NAO/Pepper/Desktop + TTS + Dialogflow + GPT)
pip install --upgrade social-interaction-cloud[dialogflow,google-tts,openai-gpt]
```

---

## Quick Start

### 1 — Define dialogs in JSON

Create a file `my_dialogs.json` (see [Dialog JSON Format](#dialog-json-format) below):

```json
[
  {
    "id": "hello",
    "type": "functional",
    "functional_type": "greeting",
    "moves": [
      { "type": "say", "text": "Hello! I am your robot companion." }
    ]
  },
  {
    "id": "pizza_chat",
    "type": "chitchat",
    "theme": "food",
    "topics": ["pizza", "food"],
    "moves": [
      { "type": "say", "text": "I have heard that humans love pizza." },
      {
        "type": "ask_yesno",
        "text": "Do you like pineapple on pizza?",
        "set_variable": "likes_pineapple"
      }
    ]
  },
  {
    "id": "goodbye",
    "type": "functional",
    "functional_type": "farewell",
    "moves": [
      { "type": "say", "text": "It was lovely talking to you. Goodbye!" }
    ]
  }
]
```

### 2 — Load, schedule, and run

```python
from src.authoring.loader import load_dialogs
from src.dialog import DialogLogic

dialogs, errors = load_dialogs("my_dialogs.json")
if errors:
    print("Load errors:", errors)

# Select a session block (greeting → chitchat → farewell)
session = DialogLogic.select_session_block(
    dialogs,
    theme="food",
    topics_of_interest=["pizza"],
)

# Run each dialog with your agent
for dialog in session:
    dialog.run(agent=my_agent)
```

---

## Dialog JSON Format

A `dialogs.json` file is a **JSON array** where every element represents one dialog. Each dialog **must** have:

| Field | Type | Description |
|---|---|---|
| `id` | `string` | Unique identifier for the dialog (e.g. `"pizza_chat"`) |
| `type` | `string` | One of `"functional"`, `"narrative"`, `"chitchat"` |
| `moves` | `array` | Ordered list of move objects |
| `dependencies` | `string[]` *(optional)* | IDs of dialogs that must be completed first |
| `variable_dependencies` | `string[]` or `{variable, required}[]` *(optional)* | User-model variables that must exist before this dialog runs |

### Dialog Types

#### `functional`

Utility dialogs such as greeting and farewell.

| Extra Field | Type | Description |
|---|---|---|
| `functional_type` | `string` | `"greeting"` or `"farewell"` |

```json
{
  "id": "hello",
  "type": "functional",
  "functional_type": "greeting",
  "moves": [{ "type": "say", "text": "Hi there!" }]
}
```

#### `narrative`

Story-driven dialogs grouped into named *threads* and ordered by *position*.

| Extra Field | Type | Description |
|---|---|---|
| `thread` | `string` | Thread name (e.g. `"dreams"`) |
| `position` | `integer` | Order within the thread (lower = earlier) |

```json
{
  "id": "dream_intro",
  "type": "narrative",
  "thread": "dreams",
  "position": 1,
  "moves": [{ "type": "say", "text": "Did you know I can dream?" }]
}
```

#### `chitchat`

Short, theme-based interactions. Can be biased toward a user's topics of interest.

| Extra Field | Type | Description |
|---|---|---|
| `theme` | `string` | Theme name (e.g. `"animals"`) |
| `topics` | `string[]` *(optional)* | Topics that match this dialog to user interests |

```json
{
  "id": "favorite_animal",
  "type": "chitchat",
  "theme": "animals",
  "topics": ["animals", "pets"],
  "moves": [
    {
      "type": "ask_open",
      "text": "What is your favourite animal?",
      "set_variable": "fav_animal",
      "add_interest_from_answer": true
    }
  ]
}
```

### Move Types

All moves are JSON objects with at minimum a `"type"` field.

#### `say`

The robot says a text string.

```json
{ "type": "say", "text": "Hello, nice to meet you!" }
```

| Field | Required | Description |
|---|---|---|
| `text` | ✅ | Text for the robot to speak. Supports `%variable%` substitution. |
| `branch` | ❌ | Execute this move only when the active branch matches this label. |

#### `ask_yesno`

Ask a yes/no question and branch on the answer.

```json
{
  "type": "ask_yesno",
  "text": "Do you like pizza?",
  "set_variable": "likes_pizza",
  "add_interest": "pizza",
  "next": { "success": "yes_branch", "fail": "no_branch" }
}
```

| Field | Required | Description |
|---|---|---|
| `text` | ✅ | Question text. |
| `set_variable` | ❌ | Store the answer (`"yes"` / `"no"` / `"dontknow"`) in `user_model[set_variable]`. |
| `add_interest` | ❌ | Add this topic to `topics_of_interest` when the user answers `"yes"`. |
| `next` | ❌ | Map `{"success": "<branch>", "fail": "<branch>"}` to jump to a labeled section. |
| `branch` | ❌ | Only execute this move when the active branch matches this label. |

#### `ask_open`

Ask an open-ended question and capture the user's free-text answer.

```json
{
  "type": "ask_open",
  "text": "What is your favourite food?",
  "set_variable": "fav_food",
  "add_interest_from_answer": true,
  "personalize_followup": true
}
```

| Field | Required | Description |
|---|---|---|
| `text` | ✅ | Question text. |
| `set_variable` | ❌ | Store an extracted keyword from the answer in `user_model`. |
| `add_interest_from_answer` | ❌ | Add the answer as a topic of interest (`true`/`false`). |
| `add_interest_from_variable` | ❌ | Add the value of this `user_model` variable as a topic of interest. |
| `personalize_followup` | ❌ | Generate a GPT-powered personalised follow-up (`true`/`false`). |
| `next` | ❌ | Branch map `{"success": "...", "fail": "..."}`. |
| `branch` | ❌ | Conditional execution label. |

#### `ask_options`

Ask a multiple-choice question.

```json
{
  "type": "ask_options",
  "text": "Which do you prefer: cats or dogs?",
  "options": ["cats", "dogs"],
  "set_variable": "preferred_pet"
}
```

| Field | Required | Description |
|---|---|---|
| `text` | ✅ | Question text. |
| `options` | ✅ | List of allowed answer strings. |
| `set_variable` | ❌ | Store the chosen option in `user_model`. |
| `add_interest_from_variable` | ❌ | Add the stored variable's value as a topic of interest. |
| `next` | ❌ | Branch map. |
| `branch` | ❌ | Conditional execution label. |

#### `ask_llm`

Open-ended LLM-driven exchange embedded inside a dialog.

```json
{
  "type": "ask_llm",
  "prompt": "You are a friendly robot. Talk about space for 2-3 turns.",
  "max_turns": 3,
  "quit_phrases": ["goodbye", "stop"],
  "set_variable": "space_topic"
}
```

| Field | Required | Description |
|---|---|---|
| `prompt` | ✅ | System prompt for the LLM. |
| `max_turns` | ❌ | Maximum back-and-forth turns (default: 5). |
| `quit_phrases` | ❌ | User utterances that end the LLM exchange early. |
| `quit_signal` | ❌ | Token the LLM embeds to signal termination (default: `"<<QUIT>>"`). |
| `set_variable` | ❌ | Store a keyword from the last user answer in `user_model`. |
| `branch` | ❌ | Conditional execution label. |

#### `play`

Play an audio file.

```json
{ "type": "play", "audio": "path/to/sound.wav" }
```

| Field | Required | Description |
|---|---|---|
| `audio` | ✅ | Path to a 16-bit WAV file. |

#### `motion_sequence`

Play a recorded motion sequence (NAO/Pepper only; silently skipped on desktop).

```json
{ "type": "motion_sequence", "motion_sequence": "path/to/sequence" }
```

#### `animation`

Trigger a named built-in animation (NAO/Pepper only).

```json
{ "type": "animation", "animation_name": "animations/Stand/Gestures/Yes_1" }
```

### Variable Substitution

In any `say` or `ask_*` text field, wrap a `user_model` key in `%` signs to substitute its value at runtime:

```json
{ "type": "say", "text": "So your favourite animal is a %fav_animal%!" }
```

If `user_model["fav_animal"] == "giraffe"`, the robot will say *"So your favourite animal is a giraffe!"*.

### Branching

Use the `next` map on question moves and the `branch` field on subsequent moves to build conditional flows within a single dialog.

```json
{
  "moves": [
    {
      "type": "ask_yesno",
      "text": "Have you ever seen a shooting star?",
      "next": { "success": "yes_path", "fail": "no_path" }
    },
    { "type": "say", "text": "Amazing! Make a wish!", "branch": "yes_path" },
    { "type": "say", "text": "Perhaps one day you will.", "branch": "no_path" }
  ]
}
```

When the user answers `"yes"`, `branch` is set to `"yes_path"` and only moves labelled `"yes_path"` execute next. When `branch` returns to `None` (an unlabelled move is reached), linear execution resumes.

---

## Authoring Tools

### Loading & Saving Dialogs

```python
from src.authoring.loader import load_dialogs, save_dialogs, save_dialogs_to_dir

# Load from a single JSON file or a directory of JSON files
dialogs, errors = load_dialogs("assets/dialogs/dialogs.json")

# Save all dialogs back to one file
save_dialogs("output/dialogs.json", dialogs)

# Save each dialog to its own file in a directory
save_dialogs_to_dir("output/dialogs/", dialogs)
```

`load_dialogs` validates every dialog via `DialogFactory` and returns a list of `(MiniDialog, errors)`. Validation errors are collected in the `errors` list and do not raise exceptions.

### Validating and Creating Dialogs Programmatically

```python
from src.authoring.factory import DialogFactory, MoveFactory

# Validate a raw dialog document (returns a list of error strings)
errors = DialogFactory.validate_doc({
    "id": "my_dialog",
    "type": "narrative",
    "thread": "demo",
    "position": 1,
    "moves": [{"type": "say", "text": "Hello!"}]
})

# Create a MiniDialog object from a raw dict
dialog = DialogFactory.from_json({
    "id": "my_dialog",
    "type": "chitchat",
    "theme": "space",
    "moves": [{"type": "say", "text": "Space is fascinating."}]
})

# Serialize back to a JSON-ready dict
doc = DialogFactory.to_json(dialog)
```

### Web-based Dialog Editor

A lightweight browser-based editor is included in `web/authoring/`. Open `web/authoring/index.html` directly in a browser — **no server required**.

Features:
- Load an existing `dialogs.json` via the file picker
- Browse and search dialogs by ID or type
- Edit all dialog fields and moves inline
- Add / delete moves with the move editor
- Create new Functional, Narrative, or Chitchat dialogs
- Delete dialogs
- Save the result back as a `dialogs.json` file

### HTML Report Export

Generate a printable HTML overview of a `dialogs.json` file:

```bash
# Default: reads assets/dialogs/dialogs.json → web/authoring/dialogs_report.html
python src/authoring/export_html.py

# Custom paths
python src/authoring/export_html.py path/to/dialogs.json path/to/report.html
```

---

## Session Scheduling

`DialogLogic` provides stateless helper methods to select and order a set of dialogs for a single robot session.

```python
from src.authoring.loader import load_dialogs
from src.dialog import DialogLogic

dialogs, _ = load_dialogs("assets/dialogs/dialogs.json")

# Load per-participant continuity (dialogs already seen, topics)
completed_ids, topics = DialogLogic.load_participant_continuity("participant_42")

# Build a session block:
#   greeting → narrative_1 → chitchat_1 → narrative_2 → chitchat_2 → farewell
session = DialogLogic.select_session_block(
    dialogs,
    thread="dreams",          # Preferred narrative thread
    theme="animals",          # Preferred chitchat theme
    topics_of_interest=topics,
    completed_ids=completed_ids,
)

for dialog in session:
    dialog.run(agent=my_agent, session_history=history,
               topics_of_interest=topics, user_model=user_model)
```

`select_session_block` respects:
- **Dependencies**: a dialog is only selected when all its `dependencies` have been completed.
- **Variable dependencies**: a dialog is only selected when required `user_model` variables are present.
- **Thread ordering**: narrative dialogs in the same thread run in ascending `position` order.
- **Topic matching**: chitchat dialogs are scored higher when their `topics` overlap with `topics_of_interest`.
- **Continuity**: `completed_ids` from previous sessions are respected so dialogs are not repeated.

---

## ConversationState

`ConversationState` tracks everything about a participant's conversation history across multiple sessions and writes per-participant JSON files to the `participants/` directory.

```python
from src.conversation_state import ConversationState

state = ConversationState("conversation_state.json")
state.load()  # read persisted data

# Start a session
session_id = state.start_session(participant_id="participant_42")

# … run dialogs, collect session_history, user_model, topics …

# Finalise
state.end_session(
    session_id,
    completed_ids={d.dialog_id for d in session},
    user_model=user_model,
    topics_of_interest=topics,
)
state.save()  # persist to disk
```

The participant file at `participants/participant_42.json` records all sessions, all seen dialog IDs, and accumulated topics of interest. This file is read back by `DialogLogic.load_participant_continuity()` to avoid replaying already-seen dialogs.

---

## ConversationAgent

`ConversationAgent` wraps a Social Interaction Cloud (SIC) device with Google Text-to-Speech, Google Dialogflow, and OpenAI GPT. It is required to **run** dialogs on real hardware; tests use a mock agent instead.

```python
from sic_framework.devices.desktop import Desktop
from src.conversation_agent import ConversationAgent

agent = ConversationAgent(
    device_manager=Desktop(),
    google_keyfile_path="conf/dialogflow/google_keyfile.json",
    openai_key_path="conf/openai/.openai_env",
)

agent.say("Hello!")
answer = agent.ask_yes_no("Do you like robots?")
open_answer = agent.ask_open("What is your name?")
```

Key methods:

| Method | Description |
|---|---|
| `say(text)` | Synthesise and play text via Google TTS |
| `ask_yes_no(question)` | Say question and recognise yes/no/dontknow via Dialogflow |
| `ask_open(question)` | Say question and return transcribed free-text reply |
| `ask_options(question, options)` | Say question and match reply against a list of options |
| `play_audio(path)` | Play a 16-bit WAV file through the device speaker |
| `play_motion_sequence(path)` | Replay a recorded NAO/Pepper motion (no-op on Desktop) |
| `play_animation(name)` | Trigger a built-in NAO/Pepper animation (no-op on Desktop) |
| `ask_llm(user_prompt, context_messages, system_prompt)` | Single GPT request |
| `personalize(robot_input, user_age, user_input)` | Generate a GPT follow-up line for a child patient |
| `extract_topics_with_gpt(raw_topics)` | Condense raw topic phrases into 1–2 keywords via GPT |

---

## Running Tests

```bash
pytest tests/
```

The test suite uses mock agents — no real robot or cloud credentials are needed.

---

## Demo Setup (Full Robot)

[Here](./src/demo_general_conversation.py) is a demo showcasing an agent-driven conversation utilizing Google Dialogflow, Google TTS, and OpenAI's GPT4.

First, you need to set-up Google Cloud Console with Dialogflow and Google TTS:

1. Dialogflow: https://socialrobotics.atlassian.net/wiki/spaces/CBSR/pages/2205155343/Getting+a+google+dialogflow+key
2. TTS: https://console.cloud.google.com/apis/api/texttospeech.googleapis.com/
   **Note:** you need to set-up a paid account with a credit card. You get $300 free tokens, which is more than enough for testing.
3. Create a keyfile as instructed in (1) and save it as `conf/dialogflow/google_keyfile.json`
   **_(Never share the keyfile online!)_**

Secondly, configure your Dialogflow agent:

4. In your empty Dialogflow agent:
   - Remove all default intents
   - Go to Settings → Import and Export → and import `resources/droomrobot_dialogflow_agent.zip`

Thirdly, you need an OpenAI key:

5. Generate your personal OpenAI API key here: https://platform.openai.com/api-keys
6. Either add your OpenAI key to your system variables or create a `.openai_env` file in `conf/openai/` and add:
   ```
   OPENAI_API_KEY="your key"
   ```

Fourthly, start the required services:

7. Install dependencies:
   ```bash
   pip install --upgrade social-interaction-cloud[dialogflow,google-tts,openai-gpt]
   ```
8. Start the Redis server:
   ```bash
   conf/redis/redis-server.exe conf/redis/redis.conf
   ```
9. In a new terminal, run Dialogflow:
   ```bash
   run-dialogflow
   ```
10. In a new terminal, run Google TTS:
    ```bash
    run-google-tts
    ```
11. In a new terminal, run GPT:
    ```bash
    run-gpt
    ```
12. Connect a device (desktop, NAO, Pepper, AlphaMini).
13. Run [the demo script](./src/demo_general_conversation.py) in a new terminal.

---