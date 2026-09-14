# The Agenda System, for Application Developers

This guide explains NarDialPy's **conversational agenda system** in plain language, for people authoring dialog JSON and wiring up a `SessionManager` — not for people changing the runtime itself (for that, see [Developer Flow](DEVELOPER_README.md)).

Every code example on this page is a verbatim excerpt of [`examples/demo_agenda_system.py`](../examples/demo_agenda_system.py), a runnable demo that uses every mechanism described here. The section numbers below match that script's own `# === N. ... ===` banner comments, so you can always jump to the real file to see a piece in its full context.

## The problem this solves

The simplest way to run a conversation is a fixed list of dialog ids: "run the greeting, then the story, then the goodbye." That works until it doesn't — you want to skip a topic the participant already covered last week, only reveal chapter 3 of a story after chapter 2 actually happened, pick whichever small-talk topic best matches what the participant just said, or run a slightly different agenda for session 1 versus session 5.

The agenda system is how NarDialPy handles that without you writing that branching logic by hand. Instead of always naming one specific dialog, an agenda entry can be a **request** — "give me the greeting," "give me the next step of this story," "give me whichever chitchat topic fits best" — and NarDialPy figures out which authored dialog actually satisfies it, checking a set of rules along the way.

## The building blocks

### The dialog registry

Whatever dialog JSON you point `SessionManager` at gets loaded once and indexed automatically — by id, by dialog type, and by fields like `topics` or `thread`. You don't do anything to set this up; it's why agenda entries can say "give me a chitchat dialog about this topic" instead of "run dialog id `chitchat_042`."

### Eligibility rules — "is this dialog allowed to run right now?"

Every dialog is checked against a small set of rules before it's offered. In plain terms:

| Rule | Plain-language question | Applies to |
|---|---|---|
| Already seen | Has this exact dialog already run (for this participant, or already in this session)? | Narrative, chitchat, LLM dialogs — **not** functional dialogs like greetings/farewells, which are allowed to repeat every session on purpose |
| Dependencies met | Have the other dialogs this one lists in `dependencies` already completed? | Every dialog type |
| Variables present | Does the user model already have the information this dialog needs (from `variable_dependencies`)? | Every dialog type |
| Story order | Is it this dialog's turn — have all earlier steps in its `thread` completed? | Narrative dialogs only |

A dialog only gets offered when it passes all the rules that apply to it. This is what makes "give me the next step of this story" safe to ask for repeatedly — the system only ever hands you a step whose prerequisites are actually met.

### Agenda items — the "slots" in your session

An agenda entry is either a plain dialog id (always run *that* dialog, ignoring eligibility — you're the one vouching it's fine) or one of five "slot" types, each phrasing a different kind of request:

| I want... | Agenda item | JSON `type` |
|---|---|---|
| ...exactly this dialog, by id | `DialogRef` (or just write the id as a bare string) | `dialog_ref` |
| ...the next not-yet-done step of a story thread | `NarrativeSlot` | `narrative_slot` |
| ...whichever small-talk topic best matches the participant's interests | `ChitchatSlot` | `chitchat_slot` |
| ...a dialog of a given functional role (e.g. "the greeting") without naming a specific id | `FunctionalSlot` | `functional_slot` |
| ...a specific LLM-driven dialog, optionally with a different turn limit or time limit for just this run | `LLMDialogRef` | `llm_dialog_ref` |

### How many times can a slot repeat?

By default, a slot resolves exactly once — you get one dialog out of it, then the agenda moves on. If you want a slot to keep giving you dialogs until some condition is met (e.g. "walk the whole story thread in one go"), give it `bounds`:

- `count_min` / `duration_min` — a floor: keep going until at least this many runs, or this much time, has happened.
- `count_max` / `duration_max` — a hard ceiling: never exceed this, even if the floor isn't met yet.

### Session Plans — a different agenda per session number

Instead of one fixed agenda, a `SessionPlan` lets you author a different agenda for session 1, session 2, and so on — say, a full introduction the first time, then a lighter check-in every time after. Sessions without their own explicit entry fall back to whichever template has the highest session number, so you don't have to author one for every future session — just the ones that differ from your steady state.

## Walking through the example

Open [`examples/demo_agenda_system.py`](../examples/demo_agenda_system.py) alongside this section — it's a single, runnable "planning a camping trip" conversation that exercises every mechanism above.

### 1. Providers (no cloud services needed)

```python
desktop = Desktop()
device = DesktopAdapter(desktop)

tts = NullTTSProvider()
nlu = WrittenKeywordNLUProvider()

# EchoLLMProvider just returns your last message back to you -- it exists
# so ask_llm/llm_based dialogs are demoable with zero setup. Swap in
# OpenAIGPTProvider(api_key=...) for real LLM responses; nothing else in
# this script needs to change.
llm = EchoLLMProvider()
```

Nothing about the agenda system requires any particular provider — this demo picks providers that need no credentials so you can run it immediately. `EchoLLMProvider` stands in for a real LLM: it just repeats what you typed, which is enough to see the multi-turn `ask_llm` exchange loop actually working.

### 2. Create the ConversationAgent

```python
agent = ConversationAgent(
    device=device,
    tts_provider=tts,
    nlu_provider=nlu,
    llm_provider=llm,
)
```

Same `ConversationAgent` every other demo uses — the agenda system lives entirely in how you build `session_agenda` and call `SessionManager`, below.

### 3. The session agenda — all five agenda-item types

```python
session_agenda = [
    # FunctionalSlot: picks a random eligible FunctionalDialog with
    # functional_type == "greeting". FunctionalDialog has no
    # ExcludeIfSeenRule, so greetings/farewells stay eligible every
    # session -- only DependencyMetRule applies to them.
    {"type": "functional_slot", "functional_type": "greeting"},

    # NarrativeSlot: picks the lowest-position not-yet-completed dialog
    # in the "camping_trip" thread (NarrativeOrderingRule +
    # ExcludeIfSeenRule + VariableDependencyMetRule). The thread has
    # three positions (camp_intro, camp_choice, camp_wrapup); a
    # SlotBounds(count_min=3, count_max=3) tells resolve_agenda() to
    # keep re-resolving this same slot until all three have run, rather
    # than the default "resolve exactly once".
    {
        "type": "narrative_slot",
        "thread": "camping_trip",
        "bounds": {"count_min": 3, "count_max": 3},
    },

    # ChitchatSlot: picks the eligible ChitchatDialog whose topics
    # overlap the most with topics_of_interest. camp_choice (above)
    # captured your answer as an interest via add_interest_from_answer,
    # so whichever of chitchat_hiking/chitchat_food/chitchat_weather
    # best matches what you said gets picked.
    #
    # Note: chitchat_food additionally declares
    # variable_dependencies: ["favorite_activity"] in the JSON -- had
    # camp_choice not run yet (and so favorite_activity not been set),
    # VariableDependencyMetRule would have excluded it from
    # consideration entirely, regardless of topic overlap.
    {"type": "chitchat_slot"},

    # LLMDialogRef: pins a specific LLMDialog by id, with optional
    # per-call overrides. The dialog is authored with max_turns: 3;
    # this slot overrides it down to 2 just for this run (a shallow
    # copy -- the original dialog in the registry is untouched).
    {"type": "llm_dialog_ref", "id": "campfire_stories", "max_turns": 2},

    # FunctionalSlot again, this time for functional_type == "summary".
    # trip_summary declares dependencies: ["campfire_stories"], so
    # DependencyMetRule keeps it ineligible until that dialog above has
    # actually completed -- which it has, by the time resolve_agenda()
    # reaches this entry.
    {"type": "functional_slot", "functional_type": "summary"},

    # A bare dialog id is a DialogRef -- it resolves to exactly that
    # dialog, ignoring eligibility entirely (SessionManager's final
    # is_dialog_eligible() safety-net check still applies before it
    # actually runs).
    "farewell",
]
```

This is the heart of the demo — six agenda entries, five different item types, one coherent conversation. Two things worth calling out explicitly, since they don't visibly "do" anything in a normal run of this script and could otherwise look like dead code:

- **`chitchat_food`'s `variable_dependencies: ["favorite_activity"]`** only ever matters if you reach the chitchat slot *before* `camp_choice` has set `favorite_activity` — which can't happen in this agenda, since the narrative slot runs first. The rule is there so that if you reordered the agenda (or reused `chitchat_food` in a different session), it still couldn't be offered before the information it needs actually exists.
- **`trip_summary`'s `dependencies: ["campfire_stories"]`** is the same idea: it's a safety property of the dialog's authoring, not something you'll see block anything in this particular script, since `campfire_stories` always runs first in this agenda.

Both are here specifically so you can see the JSON authoring pattern (`variable_dependencies`, `dependencies`) even though this particular agenda order never exercises the "not yet eligible" branch.

### 4. Run the session

```python
session_manager = SessionManager(
    session_agenda=session_agenda,
    agent=agent,
    dialog_json_path=str(DIALOG_JSON_PATH),
    participant_id="agenda_demo_participant",
)
session_manager.run()
```

Same shape as every other demo's `SessionManager` call — the only difference is what `session_agenda` contains. `SessionManager` walks it via `resolve_agenda()`, checking eligibility as it goes.

### 5. Alternative: a SessionPlan for multi-session arcs

```python
# session_manager = SessionManager(
#     session_agenda=[],  # ignored: session_plan_path overrides it
#     agent=agent,
#     dialog_json_path=str(DIALOG_JSON_PATH),
#     participant_id="agenda_demo_participant",
#     session_plan_path=str(SESSION_PLAN_PATH),
# )
# session_manager.run()
```

This block is commented out in the script (uncomment it, and remove the `sys.exit()` above it, to try it yourself). It points at [`examples/dialog_json/agenda_system_session_plan.json`](../examples/dialog_json/agenda_system_session_plan.json), which authors two templates: `session_index: 1` is the same full agenda from section 3 above, and `session_index: 2` is a shorter steady-state check-in:

```json
{
  "session_index": 2,
  "agenda": [
    {"type": "functional_slot", "functional_type": "greeting"},
    {"type": "chitchat_slot"},
    "farewell"
  ]
}
```

Run the script twice with the same `participant_id` and `session_plan_path` set, and the second run picks up this shorter `session_index: 2` agenda automatically — no code change needed, just a different session number.

`SessionManager` also accepts `session_index`, `reset_history_from_session`, and `resume` constructor parameters. These are session-management concerns rather than agenda-system ones (they don't change how an agenda resolves, only which session number it resolves *for*), so this guide and the demo intentionally leave them alone — in short: `session_index` overrides the auto-detected session number used above, `reset_history_from_session` destructively truncates a participant's history from a given session onward, and `resume` continues an interrupted session instead of starting a new one. See the `SessionManager` docstring in `src/nardial/session_manager.py` for details.

## Run it yourself

No API keys or credentials needed — just Redis running locally:

```bash
# Windows
conf/redis/redis-server.exe conf/redis/redis.conf

# macOS / Linux
redis-server conf/redis/redis.conf
```

Then, from the repository root:

```bash
python examples/demo_agenda_system.py
```

Type your replies in the terminal when prompted. For the campfire-story exchange, type "stop" (or "bye" / "that's enough") to end it early instead of waiting for the turn limit.

## Where to go deeper

- **Authoring dialog JSON** (all fields, all move types): [README.md § Defining Dialogs in JSON](../README.md#defining-dialogs-in-json)
- **How the runtime actually implements all of this** (`DialogRegistry`, `EligibilityPolicy`, `resolve_agenda()`, and the rest of the pipeline): [Developer Flow](DEVELOPER_README.md), specifically the "Dialog Eligibility," "Dialog Registry," "Agenda Items and Resolution," and "Session Plans" sections.
