# NarDialPy

**NarDialPy** is a Python package for building and running **narrative-driven, structured dialog systems** — designed for social robots and conversational agents.

It lets you author complete conversations declaratively in JSON, then drive them from Python using voice, NLU, and LLM services. The package handles session flow, branching logic, topic tracking, and personalization so you can focus on what the robot says and how conversations unfold.

---

## Table of Contents

1. [What is nardial?](#what-is-nardial)
2. [Prerequisites & Setup](#prerequisites--setup)
3. [Providers & Initialization](#providers--initialization)
4. [Defining Dialogs in JSON](#defining-dialogs-in-json)
   - [Dialog Structure](#dialog-structure)
   - [Dialog Types](#dialog-types)
   - [Move Types](#move-types)
   - [Key JSON Attributes](#key-json-attributes)
5. [Demos / Creating a Session](#demos--creating-a-session)
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

- Version: **3.12**
- Download: https://www.python.org/downloads/release/python-3120/
- ⚠️ Ensure Python is added to your system `PATH`

### 3. In your project, create and activate your python virtual environment 
```bash
# Windows
cd your_project_folder
python -m venv venv_myproject
venv_myproject\Scripts\activate

# macOS / Linux
cd your_project_folder
python -m venv venv_myproject
source venv_myproject/bin/activate
```

### 4. Install NarDial

Install the core package, then add extras for each service you intend to use:

```bash
pip install nardial
```

| Extra | Enables | Install command |
|---|---|---|
| `google-tts` | Google Cloud Text-to-Speech | `pip install "nardial[google-tts]"` |
| `elevenlabs` | ElevenLabs Text-to-Speech | `pip install "nardial[elevenlabs]"` |
| `dialogflow` | Google Dialogflow NLU | `pip install "nardial[dialogflow]"` |
| `openai` | OpenAI GPT | `pip install "nardial[openai]"` |
| `all` | All of the above | `pip install "nardial[all]"` |

For robot devices, install the matching SIC device extra directly:

```bash
pip install "social-interaction-cloud[alphamini]"   # Alphamini
```

Pepper and NAO are included in the base SIC package.


### 5. Configure Credentials
 * Create a `conf` folder at the root of your project.
 * Create a Google cloud project (for Dialogflow and google-tts services) and save the generated keyfile to `conf/google/google_keyfile.json`. Instructions [here](https://socialrobotics.atlassian.net/wiki/spaces/CBSR/pages/2205155343/Getting+a+google+dialogflow+key).
 * Create an OpenAI account, and generate an [API key](https://developers.openai.com/api/docs/quickstart) and save it to `conf/openai/.openai_env` with the following content:
```bash
OPENAI_API_KEY="your key"
```

> ⚠️ Never commit credential files to version control.

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

## Providers & Initialization

NarDialPy is built around a set of provider protocols. Each protocol defines a role (device, TTS, NLU, LLM, vector store) and multiple concrete implementations are available. You pick one implementation per role, instantiate it, and pass everything into `ConversationAgent` or `SessionManager`.

### Available Providers

| Role | Provider | Import path | Requires |
|---|---|---|---|
| **Device** | `DesktopAdapter` | `nardial.providers.device.desktop` | base |
| | `PepperAdapter` | `nardial.providers.device.pepper` | base |
| | `NaoAdapter` | `nardial.providers.device.nao` | base |
| | `AlphaminiAdapter` | `nardial.providers.device.alphamini` | `social-interaction-cloud[alphamini]` |
| **TTS** | `GoogleTTSProvider` | `nardial.providers.tts.google` | `nardial[google-tts]` |
| | `ElevenLabsTTSProvider` | `nardial.providers.tts.elevenlabs` | `nardial[elevenlabs]` |
| | `NaoqiTTSProvider` | `nardial.providers.tts.naoqi` | base (uses device's built-in TTS) |
| | `NullTTSProvider` | `nardial.providers.tts.null` | base (prints to terminal) |
| **NLU** | `DialogflowNLUProvider` | `nardial.providers.nlu.dialogflow` | `nardial[dialogflow]` |
| | `WrittenKeywordNLUProvider` | `nardial.providers.nlu.written_keyword` | base (keyboard input) |
| **LLM** | `OpenAIGPTProvider` | `nardial.providers.llm.openai_gpt` | `nardial[openai]` |
| | `EchoLLMProvider` | `nardial.providers.llm.echo` | base (echoes user input) |
| **Vector store** | `RedisVectorStoreProvider` | `nardial.providers.vector_store.redis_store` | base + running Redis |
| | `NullVectorStoreProvider` | `nardial.providers.vector_store.null` | base |

---

### Minimal setup (no external services)

Good for local development and testing — all I/O goes through the terminal:

```python
import logging
from sic_framework.devices.desktop import Desktop

from nardial.providers.device.desktop import DesktopAdapter
from nardial.providers.tts.null import NullTTSProvider
from nardial.providers.nlu.written_keyword import WrittenKeywordNLUProvider
from nardial.conversation_agent import ConversationAgent

desktop = Desktop()
device = DesktopAdapter(desktop)
device.setup(logger=logging.getLogger())

agent = ConversationAgent(
    device=device,
    tts_provider=NullTTSProvider(),
    nlu_provider=WrittenKeywordNLUProvider(),
)
```

---

### Desktop with cloud services

```python
import json, logging
from sic_framework.devices.desktop import Desktop
from sic_framework.services.dialogflow.dialogflow import DialogflowConf

from nardial.providers.device.desktop import DesktopAdapter
from nardial.providers.tts.google import GoogleTTSProvider, GoogleTTSConf
from nardial.providers.tts.cacher import TTSCacher
from nardial.providers.nlu.dialogflow import DialogflowNLUProvider
from nardial.providers.llm.openai_gpt import OpenAIGPTProvider
from nardial.conversation_agent import ConversationAgent

desktop = Desktop()
device = DesktopAdapter(desktop)
device.setup(logger=logging.getLogger())

tts = GoogleTTSProvider(
    conf=GoogleTTSConf(speaking_rate=0.9, google_tts_voice_name="en-US-Neural2-F"),
    device=device,
    keyfile_path="conf/google/google_keyfile.json",
    tts_cacher=TTSCacher(tts_cache_dir="tts_cache"),
)

nlu = DialogflowNLUProvider(
    conf=DialogflowConf(keyfile_json=json.load(open("conf/google/google_keyfile.json"))),
    mic=desktop.mic,
)

llm = OpenAIGPTProvider(api_key="<YOUR_OPENAI_KEY>")

agent = ConversationAgent(
    device=device,
    tts_provider=tts,
    nlu_provider=nlu,
    llm_provider=llm,
)
```

---

### Pepper robot

Swap the device adapter and TTS provider — everything else stays the same:

```python
import logging
from sic_framework.devices import Pepper

from nardial.providers.device.pepper import PepperAdapter
from nardial.providers.tts.naoqi import NaoqiTTSProvider

pepper = Pepper(ip="<PEPPER_IP>")
device = PepperAdapter(pepper)
device.setup(logger=logging.getLogger())

tts = NaoqiTTSProvider(device=device, language="en")
```

Then pass `device` and `tts` to `ConversationAgent` as above.

---

### Using SessionManager

`SessionManager` wraps `ConversationAgent` and adds dialog loading, eligibility checking, and session state:

```python
from nardial.session_manager import SessionManager

manager = SessionManager(
    agent=agent,
    dialog_file="dialogs/my_dialogs.json",
    participant_id="user_42",
)
manager.run()
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

Example: 
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

#### 1.`functional`

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
    }
  ]
}
```

---

#### 2. `chitchat`

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

#### 3. `narrative`

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

#### 4. `llm_based`

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

## Demos / Creating a Session

All you need is a minimal Python script that wires up the device, loads the dialog JSON, and runs the session. You can follow the included demos to get started quickly.

Two ready-to-run demos are included in the `examples/` directory:
* Demo 1 — General Conversation (`demo_general_conversation.py`): A simple four-step conversation using a mix of narrative and functional dialogs
* Demo 2 — Structured Conversation (`demo_structured_conversation.py`): A more complete example that demonstrates all dialog types and move types, including `ask_llm`, `play`, `motion_sequence`, and `animation`

You can find additional demos in the [SIC Applications repository](https://github.com/Social-AI-VU/sic_applications/tree/main/demos/nardial)

---

## Development

Run tests from the repository root:

```bash
python -m pytest -q
```

---
