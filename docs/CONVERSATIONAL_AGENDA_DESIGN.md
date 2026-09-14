# Conversational Agenda — Design & Implementation Plan

## Context

PR #114 ("Conversational agenda") attempted to build this entire feature — a pluggable, JSON-configurable system for deciding which dialog runs next, replacing the hardcoded `build_dialog_session()` template — in one ~9,800-line branch. It was closed unmerged on 2026-09-08 without ever landing on `main`. None of that code exists in the repo today.

The feature is still wanted, and it's already broken into 16 open GitHub issues (#94–#109, #115) that describe each piece individually, in roughly dependency order. Four further issues (#110 validation CLI, #111 dry-run mode, #112 semantic topic matching, #113 LLM-driven agenda rewriting) are deliberately **out of scope** for this plan — later follow-ups once the core system exists.

Goal: re-implement the same design, **one PR per issue, in dependency order**, each small enough to actually review and merge — avoiding the fate of #114. Two decisions are locked in:

1. **Four PRs, not sixteen.** The original plan was one PR per issue, to mitigate the #114 disaster by keeping every review small. In practice a single-issue PR turned out to be too small to review meaningfully on its own — e.g. step 1 alone ships class-attribute scaffolding (`DEFAULT_ELIGIBILITY` placeholders) that nothing reads until step 2 exists. PRs are now grouped into four along the plan's own dependency checkpoints (see "PR grouping" below); each of the 16 issues still lands as its own **commit**, in the same order and with the same scope as before — only the review/merge unit changed, not the implementation granularity. Each commit still ships with its own tests, and the full suite must stay green after every commit, not just at PR boundaries.
2. **No Pydantic.** The current codebase (`Move` classes in `moves.py`, `MiniDialog` subclasses in `mini_dialogs.py`, `DialogFactory` in `authoring/factory.py`) uses plain Python classes with manual `__init__`, `from_dict()`/`to_dict()`, and hand-written `validate()` returning lists of error strings — zero Pydantic anywhere today. The issue bodies spec the new types as Pydantic `BaseModel`s; this plan replaces that throughout with the same manual-class convention already used everywhere else, including a `coerce_agenda_item()` dispatcher that mirrors `DialogFactory.from_json()`'s type-string dispatch instead of a Pydantic discriminated union.

This plan was grounded in the **current** state of the code (read directly, not assumed from the old PR, which predates recent work like the `MoveSayOptions` addition) — see "Divergences" below for where the issues' assumptions don't match reality.

## Divergences from the issues' assumptions (verified against current code)

- **No `BaseDialog` exists.** `MiniDialog` (plain class, not ABC) is the sole base for `FunctionalDialog`/`NarrativeDialog`/`ChitchatDialog`/`LLMDialog`. Every issue's `BaseDialog` type hint becomes `MiniDialog` throughout.
- **`FunctionalDialog` stores its type as `self.type`**, not `self.functional_type` — but `DialogRegistry`/`FunctionalSlot` need to index/query by `functional_type`. Fixed with a read-only `functional_type` property alias (step 1), not a constructor rename (which would break `DialogFactory.from_json` and `is_greeting_dialog`/`is_farewell_dialog`).
- **`build_dialog_session()` is dead code today** — `SessionManager` never calls it (the session agenda is currently always supplied externally as a plain ID list). Nothing currently breaks when it's deleted (step 13).
- **Two known bugs, unrelated to each other:**
  - `FunctionalDialog.is_greeting_dialog()`/`is_farewell_dialog()` (`mini_dialogs.py`) compare `self.type` (a string) against a bare `FunctionalType` enum member — always `False`. Low-risk one-line fix, bundled into step 1 since that step already touches `FunctionalDialog`.
  - `MoveKeyboardInput.type` is set to `MOVE_WAIT_FOR_WEB_INPUT` instead of `MOVE_KEYBOARD_INPUT` (`moves.py`). **Unrelated to this feature** — no agenda issue touches `moves.py`. Recommend as a separate standalone one-line bugfix PR, not part of this plan.
- **`test_dialog_logic.py` and `src/nardial/agenda/*.py` don't exist** — only stale `.pyc` files remain in `__pycache__` from an earlier, fully-deleted local prototype (the `.pyc` names hint at module names like `agenda/rules.py`, which this plan deliberately never recreates — see step 2).
- **`FunctionalDialog.__init__` has no `variable_dependencies` param**, unlike its siblings — added in step 2 (backward-compatible, keyword-only) so `variable_dependencies` authored on functional dialogs stops being silently discarded by the factory.
- **Logging**: the current codebase uses `print("[INFO]/[WARN]/[ERROR] ...")` everywhere, not the `logging` module the issues assume. Since several agenda components require "warn + skip, don't crash" behavior that tests need to assert on, this plan introduces `logging.getLogger(__name__)` starting in the new `eligibility.py`/`agenda/` modules (step 1–2 onward) — a deliberate, visible deviation from repo convention, called out in those PR descriptions rather than silently drifting.

## PR grouping

16 steps, 4 PRs. Each PR is one branch; each step below lands as its own commit on that branch, in order, with that step's own tests included in the same commit (not deferred to a final PR-closing commit). Full test suite (`python -m pytest -q`) must stay green after every commit.

| PR | Branch | Steps | Issues closed |
|---|---|---|---|
| 1. Dialog classification & eligibility | `agenda/registry-eligibility` | 1–2 | #94, #95, #115 |
| 2. Agenda item types & resolver | `agenda/items-resolver` | 3–10 | #101, #96, #97, #105, #98, #99, #100, #102 |
| 3. Wire `SessionManager`, session plans, cleanup | `session/wire-plan-cleanup` | 11–13 | #103, #104, #106 |
| 4. Integration tests, session history & resume | `session/integration-resume` | 14–16 | #107, #108, #109 |

PR boundaries were chosen at the plan's natural dependency checkpoints, not by issue count:
- **PR 1** ends where the next unit of work (agenda item types) starts touching a new file/abstraction (`agenda/items.py`) instead of dialog classification.
- **PR 2** is everything additive with **no dependency on `SessionManager`** — the whole point of steps 1–10 in the original plan — so it's the largest PR but also the lowest-risk one, since it can't regress any running demo.
- **PR 3** is the cutover: this is where `SessionManager`'s actual runtime behavior changes, `list[str]`-agenda backward compatibility is verified, and the legacy `dialog_logic.py` module is deleted.
- **PR 4** is verification and the last two runtime features (crash-resume, history reset), which only make sense once PR 3 has landed.

## Sequenced steps (commits within each PR)

---

**1. `DialogRegistry` + loader + class-attribute scaffolding** — closes **#94**
Commit 1 on `agenda/registry-eligibility`.
- New `src/nardial/dialog_registry.py`: `DialogRegistry` with `by_id`, `by_type`, `indexes` dicts; `build(dialogs)` classmethod reads each dialog's `DIALOG_TYPE` and `INDEX_ATTRS` class attributes (new — see below), indexing list-valued attrs (e.g. `ChitchatDialog.topics`) element-wise; `get_by_id`/`get_by_type`/`get_by_attr` (return `[]`/`None` on miss, never raise).
- `mini_dialogs.py`: add `INDEX_ATTRS`, `DIALOG_TYPE` (a `DialogType` enum value — new class attribute, needed so the registry never needs an `isinstance` chain), and a placeholder `DEFAULT_ELIGIBILITY: list = []` to each of the four dialog subclasses. Add `FunctionalDialog.functional_type` property (`return self.type`). Fix the `is_greeting_dialog`/`is_farewell_dialog` enum-comparison bug.
- `authoring/loader.py`: add `load_dialog_registry(path_or_dir) -> (DialogRegistry, errors)` on top of the existing `load_dialogs()` (already does per-file error isolation — no new error handling needed).
- Tests: new `tests/test_dialog_registry.py` — build from mixed dialog fixtures, `get_by_attr("topics", "pizza")` matches multi-topic dialogs, `get_by_attr("functional_type", "greeting")` works via the property, `load_dialog_registry` against a temp dir with one malformed file.

**2. `EligibilityPolicy` + rules, built directly in `eligibility.py`** — closes **#95 + #115** (merged: build straight into the flat root module `eligibility.py` from the start, so there's never an `agenda/rules.py` to migrate away from)
Commit 2 on `agenda/registry-eligibility`.
- New `src/nardial/eligibility.py` — no runtime import of `agenda/` or `mini_dialogs.py` (only `TYPE_CHECKING`). `EligibilityScope` enum (`SESSION`/`PARTICIPANT`); `EligibilityRule` ABC; `ExcludeIfSeenRule(scope=PARTICIPANT)`, `DepsMetRule`, `VariableDepsMetRule` (uses `getattr(dialog, "variable_dependencies", [])` defensively — makes it safe for `FunctionalDialog` even before/without the constructor change below), `NarrativeOrderingRule` (duck-types via `getattr(dialog, "thread"/"position", None)` and looks up siblings through `context.registry.get_by_attr(...)`, never `isinstance(NarrativeDialog)` — this *is* what avoids the circular import #115 describes); `EligibilityPolicy(rules)`.
- `mini_dialogs.py`: import the rule classes at module level (safe — no cycle), populate each dialog class's `DEFAULT_ELIGIBILITY` from step 1's placeholder. `FunctionalDialog.DEFAULT_ELIGIBILITY = [DepsMetRule()]` — deliberately **no** `ExcludeIfSeenRule`, so greetings/farewells re-run every session (a real, intentional behavior change). Add `variable_dependencies=None` param to `FunctionalDialog.__init__`, wire through `authoring/factory.py`'s functional branches.
- `dialog_logic.py`: `is_dialog_eligible()` gains an optional `policy=` kwarg (defaults to `EligibilityPolicy(type(dialog).DEFAULT_ELIGIBILITY)`), builds a small local eligibility context internally. Fix the `user_model={}` bug in `insert_chitchat_into_session()` while the file is open (still present until step 13 deletes it).
- Tests: new `tests/test_eligibility_rules.py` (all rules, both `ExcludeIfSeenRule` scopes, `NarrativeOrderingRule` via a real registry) and new `tests/test_dialog_logic.py` (didn't exist before) covering `is_dialog_eligible()` with/without an explicit policy.

**3. `SlotBounds`** — closes **#101** (sequenced here, ahead of its issue number, since #97–#99 depend on it)
Commit 3 on `agenda/items-resolver`.
- New `src/nardial/agenda/__init__.py` (package created here) + `src/nardial/agenda/slot_bounds.py`: `SlotBounds(count_min=1, count_max=1, duration_min=None, duration_max=None)`, `from_dict`/`to_dict`/`validate()` (error-list style, matching `MoveFactory.validate`).
- Tests: new `tests/test_slot_bounds.py` — default = exactly-once, JSON round trip, `validate()` catches inverted bounds.

**4. `AgendaItem` base, `DialogRef`, `AgendaContext`, `coerce_agenda_item`** — closes **#96**
Commit 4 on `agenda/items-resolver`.
- New `src/nardial/agenda/items.py`: `AgendaItem` ABC (`resolve(context) -> MiniDialog | None`); `AgendaContext` dataclass (`registry`, `completed_ids`, `session_completed_ids`, `user_model`, `topics_of_interest`, `mark_completed(dialog_id)`); `DialogRef(id)` (warns + returns `None` on missing ID); `coerce_agenda_item(item: str|dict|AgendaItem)` — manual if/elif dispatch on `item["type"]`, mirroring `DialogFactory.from_json`; only `"dialog_ref"` registered here, each later step (5–9) adds its own branch.
- `dialog_logic.py`: swap the step-2 local eligibility context for the real `AgendaContext` now that it exists.
- Tests: new `tests/test_agenda_items.py` — string/dict coercion, `DialogRef` hit/miss, `AgendaContext.mark_completed()`.

**5. `NarrativeSlot`** — closes **#97**
Commit 5 on `agenda/items-resolver`.
- `agenda/items.py`: `NarrativeSlot(thread, bounds=None, eligibility_policy=None)` — lowest eligible `position` wins, random tiebreak. Add `"narrative_slot"` to `coerce_agenda_item`.
- Tests: extend `tests/test_agenda_items.py` — lowest-position wins, seeded random tiebreak, no-candidate → `None` + warning (assert via `caplog`).

**6. Remove `theme` from `ChitchatDialog`** — closes **#105** (independent of the agenda system, but sequenced right before `ChitchatSlot` since #98 depends on the topics-only model)
Commit 6 on `agenda/items-resolver`.
- `mini_dialogs.py`: drop `theme` from `ChitchatDialog.__init__`.
- `authoring/factory.py`: drop `theme` from `DialogFactory.validate_doc`/`from_json`/`to_json`'s chitchat branches. (Note: there is no `authoring/schemas.py` — that file doesn't exist; all the equivalent logic already lives in `factory.py`.)
- `dialog_logic.py`: drop `theme` param from `sort_chitchat_dialogs()`, update its one call site.
- `examples/dialog_json/*.json`: strip `"theme"` from chitchat blocks; verify all demo scripts still load their JSON without validation errors.
- Tests: update any fixture constructing `ChitchatDialog(..., theme=...)`.

**7. `ChitchatSlot`** — closes **#98**
Commit 7 on `agenda/items-resolver`.
- `agenda/items.py`: `ChitchatSlot(bounds=None, topics_filter=None, eligibility_policy=None)` — filters by `DialogType.CHITCHAT` + eligibility + optional `topics_filter`, shuffle-then-sort by topic-overlap with `context.topics_of_interest` (shuffle-before-stable-sort gives a random tiebreak). This is where the long-standing `user_model={}` bug actually gets fixed at its source, since `VariableDepsMetRule` now sees the real `context.user_model`. Add `"chitchat_slot"` to `coerce_agenda_item`.
- Tests: extend `tests/test_agenda_items.py` — highest overlap wins, `topics_filter` restricts candidates, a regression test proving a `VariableDepsMetRule` correctly blocks selection using a real (non-empty) `user_model`.

**8. `FunctionalSlot`** — closes **#99**
Commit 8 on `agenda/items-resolver`.
- `agenda/items.py`: `FunctionalSlot(functional_type, bounds=None, eligibility_policy=None)` — queries the registry via the `functional_type` property from step 1, random choice among all eligible. Add `"functional_slot"` to `coerce_agenda_item`.
- Tests: extend `tests/test_agenda_items.py` — correct type resolved, **still resolves even when already completed** (regression test for the no-`ExcludeIfSeenRule` behavior from step 2), no-candidate case.

**9. `LLMDialogRef`** — closes **#100**
Commit 9 on `agenda/items-resolver`.
- `agenda/items.py`: `LLMDialogRef(id, max_turns=None, duration=None)` — pins by ID, warns + returns `None` on missing/wrong-type ID (never crashes), shallow-copies the dialog when overrides are set so the registry's original is untouched. Add `"llm_dialog_ref"` to `coerce_agenda_item`.
- Tests: extend `tests/test_agenda_items.py` — hit, missing-ID warning, wrong-type warning, override produces a distinct copied object.

**10. `resolve_agenda()` generator** — closes **#102**
Commit 10 on `agenda/items-resolver`.
- New `src/nardial/agenda/resolver.py`: `resolve_agenda(items, context)` — deque-based generator; tracks per-item run-count/start-time in local dicts keyed by `id(item)` (not mutated attributes on the `AgendaItem` instances, which keeps them effectively immutable); re-queues (`appendleft`) based on `SlotBounds` (`count_min`/`duration_min` as floors, `count_max`/`duration_max` as hard ceilings); items with no `bounds` attribute (`DialogRef`, `LLMDialogRef`) always resolve exactly once; `None`-resolving items are skipped, not re-queued. Caller calls `context.mark_completed()` between yields.
- Tests: new `tests/test_agenda_resolver.py` — flat string list yields in order; a `NarrativeSlot(bounds=SlotBounds(count_min=2))` requires two `mark_completed()` calls to see updated state on its second resolve; `None`-resolving items don't loop forever; `duration_max` hard-stops even with `count_min` unmet.

**11. Wire `SessionManager` to `resolve_agenda()`** — closes **#103**
Commit 11 on `session/wire-plan-cleanup`.
- `session_manager.py`: `__init__` gains `session_plan_path=None`, `session_index=None`, `reset_history_from_session=None`, `resume=False` — **stored but not yet acted on** (stubs only, so steps 12/15/16 don't need to re-touch the constructor signature; keeps this step scoped strictly to resolver wiring). Replace dialog loading with `load_dialog_registry()` (step 1). Remove `build_session_block()`. Add `_build_agenda_context()`. `run_async()`'s loop becomes `for dialog in resolve_agenda(self.session_agenda, context)`, keeping the existing `DialogLogic.is_dialog_eligible(...)` call as a final safety-net gate (per the issue's own design), then existing run/persist bookkeeping, then `context.mark_completed(...)` alongside (not instead of) the existing `conversation_state.completed_dialogs` append.
- Tests: new `tests/test_session_manager.py` — a plain `list[str]` agenda still behaves identically (backward-compat regression test using `make_mock_agent`); a mixed string+dict agenda resolves end to end against a small in-memory registry.
- **Backward compatibility:** all `examples/demo_*.py` scripts pass `session_agenda` as `list[str]` — unaffected, no demo script changes needed.

**12. `SessionPlan` / `SessionTemplate`** — closes **#104**
Commit 12 on `session/wire-plan-cleanup`.
- New `src/nardial/agenda/session_plan.py`: `SessionTemplate(session_index, agenda)`, `SessionPlan(plan_id, sessions)` with `get_template(session_number)` (exact match, else the highest-indexed template as steady-state fallback), `validate()`, `load_session_plan(path)`.
- `session_manager.py`: implement behavior behind the `session_plan_path` stub from step 11 — compute `session_number` correctly (watch the off-by-one: `ConversationState.sessions` may already include the just-started current session at this point — get this right and cover it with a test).
- Tests: new `tests/test_session_plan.py` — exact match, fallback, JSON round trip, and an end-to-end `SessionManager(session_plan_path=...)` test asserting the right template is picked (the off-by-one regression test).

**13. Delete `dialog_logic.py` entirely** — closes **#106** (scope extended beyond the issue text, per discussion: the issue says "keep `is_dialog_eligible` etc. as utilities," but by this point every remaining function is superseded — `is_dialog_eligible` itself relocates rather than staying behind)
Commit 13 on `session/wire-plan-cleanup`.
- `eligibility.py`: add `is_dialog_eligible(dialog, context, policy=None)` as a free function operating on the real `AgendaContext` (replaces the legacy `(completed_ids, user_model, all_dialogs)` signature).
- `session_manager.py`: update its safety-gate call site to the new signature/import.
- **Delete** `src/nardial/dialog_logic.py` — `select_next_narrative`, `sort_chitchat_dialogs`, `matches_user_interests`, `select_active_thread`, `build_dialog_session`, `insert_chitchat_into_session` are all fully superseded (`NarrativeSlot`/`ChitchatSlot` from steps 5/7) with no remaining callers (verify via `grep -r "dialog_logic\|DialogLogic"`).
- Update `docs/DEVELOPER_README.md` (the whole "Dialog Eligibility" section and the runtime-pipeline table row) and `CLAUDE.md`'s pipeline diagram (`DialogLogic eligibility checks` → `agenda resolver / EligibilityPolicy`).
- Tests: move any surviving `is_dialog_eligible` coverage from `test_dialog_logic.py` (step 2) into `test_eligibility_rules.py`; delete the rest.

**14. Integration tests for the full pipeline** — closes **#107** (reframed: unit tests ship with each step above; this step is purely integration-level, only meaningful once everything is wired)
Commit 14 on `session/integration-resume`.
- New `tests/integration/test_agenda_session_integration.py` (directory already exists, currently empty): full `SessionManager.run()` with a mixed `session_agenda` against a small fixture dialog set (narrative thread, chitchat with topics, greeting/farewell, one LLM dialog) using `make_mock_agent`; assert correct `ConversationState` persistence; a second `SessionManager` run against the same `participant_id` correctly excludes already-completed narrative dialogs (end-to-end `ExcludeIfSeenRule(scope=participant)` check); a two-session `SessionPlan`-driven run selecting different templates per session.

**15. `session_index` override + `reset_history_from_session`** — closes **#108**
Commit 15 on `session/integration-resume`.
- `conversation_state.py`: `count_completed_sessions()` (sessions with `ended_at is not None`), `truncate_from_session(n)` — keeps sessions before `n`, recomputes `completed_dialogs`, and **must call `self.user_model.save_continuity(...)`** at the end (this was a real bug fixed mid-review in the old PR — don't reintroduce it; mirrors the existing pattern in `end_session()`).
- `session_manager.py`: implement behavior behind the step-11 stubs — `session_index` overrides auto-detected session number for `SessionPlan.get_template()`; `reset_history_from_session` logs a clear destructive warning, then calls `truncate_from_session()` before the new session starts.
- Tests: extend `tests/test_conversation_state.py` (truncation correctness + the Redis-sync call, using a spy) and `tests/test_session_manager.py` (override + reset behavior).

**16. `resume=True` crash recovery** — closes **#109**
Commit 16 on `session/integration-resume`.
- `conversation_state.py`: `find_incomplete_session()` — returns the last session if `ended_at is None` (already correctly `None`-until-`end_session()` today — confirmed, just needs a test, no fix).
- `session_manager.py`: implement behind the step-11 `resume` stub — when resuming, reuse the incomplete session's ID instead of starting a new one (restructure the unconditional `start_session()` call in `__init__`), pre-populate `AgendaContext.session_completed_ids` from the incomplete session's already-run dialog IDs (without touching persisted cross-session `completed_dialogs`), log the resume info message.
- Tests: extend `tests/test_session_manager.py` — resume skips already-run dialogs and appends to the same session record; `resume=True` with nothing to resume behaves like `resume=False`; `resume=False` (default) is fully unaffected.

---

## Notes on sequencing

- Step count is still **16** — regrouping into 4 PRs changed the review/merge unit, not the implementation granularity. Each step is still its own commit, closes its own issue(s), and ships with its own tests in that commit.
- Within PR 1, #95+#115 remain merged into a single commit (step 2) for the structural reason described there (avoiding an `agenda/rules.py` that would immediately need migrating away from) — that merge predates and is independent of the 4-PR regrouping.
- Steps 1–10 (PRs 1 and 2: registry, eligibility, slot bounds, all agenda item types, resolver) have **no dependency on `SessionManager`** and are purely additive — this is exactly why they group cleanly into two low-risk PRs that can't regress any running demo.
- Steps 11 onward (PRs 3 and 4) are the only ones that touch `SessionManager`'s actual runtime behavior; backward compatibility with existing `list[str]` agendas and all `examples/demo_*.py` scripts is verified in PR 3 and holds for every commit after.
- Because each PR now bundles multiple steps, review should still proceed commit-by-commit (`git log --oneline`, review each commit's diff in order) rather than treating the PR as one undifferentiated diff — the commit boundaries are exactly the old PR boundaries and carry the same reasoning.

## Verification

- After every commit (not just every PR): `python -m pytest -q` from the repo root must stay green (existing suite + that commit's new tests).
- Step 6 (theme removal) and step 11 (SessionManager wiring): additionally load every file in `examples/dialog_json/*.json` through `load_dialogs()`/`load_dialog_registry()` and confirm zero validation errors, since these are the closest thing to a "does authored content still work" smoke test without needing live TTS/NLU/robot services.
- Step 13 (dialog_logic.py deletion): `grep -r "dialog_logic\|DialogLogic\|build_dialog_session\|insert_chitchat_into_session" .` must return nothing outside of git history/docs being updated in the same commit.
- Step 14 (integration tests): this is the end-to-end functional check for the whole feature — a full mocked session run producing correct persisted state is the closest thing to "does the agenda system actually work" without live hardware.
- Final state: all 16 issues closed via 4 merged PRs (16 commits total), `docs/DEVELOPER_README.md` and `CLAUDE.md` reflect the new architecture (no more `DialogLogic`/`build_dialog_session` references), full test suite green.
