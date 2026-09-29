# Worklog — task_2799_commercial_kitchen_food_waste_tracking_diversion

## Step 1: Create task directory — 2026-09-04T23:18:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2799_commercial_kitchen_food_waste_tracking_diversion` and its `workspace/` subdirectory. Index 2799 was pre-assigned by the caller; no scan/allocation of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-05T01:08:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Output** — `/home/ubuntu/github/CodingPRD/tasks/task_2799_commercial_kitchen_food_waste_tracking_diversion/`

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 3204 | §1.0–§1.7 only (no `scaffold_difficulty_design`, no `scaffold_corner_design`) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2086 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4841 | `scaffold_corner_design` |

**SCAFFOLD.yaml (§1.0–§1.7)** — difficulty `expert_plus`; archetypes compliance_audit / ledger_reconciliation; flat topology, cyclic state machines, immediate consistency.
- 15 entities, 12 state machines, 2 concurrency rules (`expected_entry_version` → ERR_STALE_ENTRY_VERSION, `expected_site_version` → ERR_STALE_SITE_VERSION, both 412)
- 13 calculations, 29 ordered validations (priority ladder 10 → 130), 68 endpoints (incl. `POST /_clock/set_current_utc`), 72 error codes, 6 roles with two X-User-ID duty separations (capture/void, prepare/publish)

**§1.8 difficulty design** — 9 rules × ~2.8 instances = **25 instances**, ~302 API calls.

**§1.9 corner design** — **137 instances** across all nine legal sections (102 with full `test_recipe`, 35 `excluded_because:` stubs citing §1.8 by name):
entities 19 · state_machines 35 · calculations 20 · validations 25 · endpoints 6 · errors 11 · rbac 11 · complexity_layers 8 · consistency_model 2.

**Verification**
- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1034 calls scanned across both design files)
- All 72 error codes are reachable from at least one §1.8 or §1.9 instance; zero dead codes
- Names unique across §1.8 ∪ §1.9; every stub's cited `difficulty_instance` resolves; no stub carries a `test_recipe`
- Difficulty directive text (`harder than expert level`) appears nowhere in SCAFFOLD.yaml; `scenario` begins at "2799. Commercial Kitchen Food Waste Tracking & Diversion"

Two defects found and fixed during the final audit pass: asserts referenced `Shift.total_waste_grams` (real field is `shift_waste_grams`, 7 occurrences) and a non-existent `CoachingAlert.acknowledged_at`; also renamed one instance from `..._returns_4XX` to `..._returns_403` because the linter's negative-test regex requires literal digits.

**Orchestrator verification**: all three files present; `SCAFFOLD.yaml` contains neither design key; each design file has exactly one top-level key; grep for "harder than expert" across all three scaffold files returns nothing (no difficulty-directive leak).

## Step 3: Copy shared files — 2026-09-05T01:09:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes). `workspace/` survived Step 2 intact.

## Step 4: Generate PRD — 2026-09-05T01:24:00.000Z

PRD complete at `workspace/PRD.md`.

**Line count:** 482 lines. Ends cleanly on the final row of the §5 error table (`| `ERR_ENTRY_ALREADY_CORRECTED` | 409 |`) — no truncation, no audit footer.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim fixed block, all four sentinel strings intact); 2.3 Pagination; 2.4 Resource Identity, Timestamps and the Logical Clock; 2.5 Weights, Money and Rounding Discipline; 2.6 Optimistic Concurrency on Parent Aggregates; 2.7 Derived Aggregates, Cascades and Compensation; 2.8 Site Scoping, Hauler Scoping and Segregation of Duties; 2.9 The Order in Which a Request Is Judged; 2.10 Flat Collections and Reverse Navigation
- §3 Business Logic & Workflows — 3.1 Catalog Foundations (Sites, Food Types, Recipe Costing); 3.2 Stations, Service Periods and the Capture of a Weighed Loss; 3.3 Coaching Alerts and the Site's Posture; 3.4 Flags, Voids and Corrections; 3.5 Closing a Service Period: Final Valuation and Leaderboard; 3.6 Baselines and Reduction Targets; 3.7 Haulers, Consignments and Allocations; 3.8 Weigh Tickets and Settlement Pricing; 3.9 Data Quality Assurance; 3.10 Corporate Reporting and the Publication Gate
- §4 API Endpoint Specifications (4-column table, 68 rows)
- §5 Error Handling (2-column table, 72 rows)

**Coverage of §1.1–§1.7 (verified mechanically)**
- **Entities/fields (§1.1):** 160/160 required identifiers appear verbatim in backticks — 145 distinct entity field names across all 15 entities, 7 endpoint-only inputs (`current_utc`, `expected_entry_version`, `expected_site_version`, `limit`, `offset`, `resolution`, `scan_date`), and 8 nested/output keys (`ingredient_name`, `quantity_kg`, `unit_cost_cents_per_kg`, `trim_loss_pct`, `target_id`, `site_diversion_rate_pct`, `reevaluated_target_ids`, `resolved_target_ids`). 0 missing.
- **State machines (§1.2):** all 45 transitions across 12 machines described with actor, preconditions, error, side effects; every state name present (the only two "unmatched" strings are the scaffold's compound `logistics_status=…, settlement_status=…` initial/terminal labels, whose component states are all covered). Every enum value of every enum field appears in backticks — 0 missing. Cyclic paths (`OPEN → ACKNOWLEDGED → RESOLVED`, flag/clear-flag, `TICKET_SUBMITTED → DISPUTED → TICKET_SUBMITTED`) and the parallel logistics/settlement axes are explicitly separated.
- **Concurrency (§1.2.1):** both OCC guards in §2.6 with their 412 errors.
- **Calculations (§1.3):** all 13 named calculations rendered in prose with pinned step order, constants and worked divergences (recipe 1029-vs-1028; provisional 1568 → final 2521 delta 953; intensity +10.00 % vs −12.50 %; settlement 15688-not-16132 tier trap). No pseudocode, no fuzzy quantifiers.
- **Validations (§1.4):** all 29 rules transcribed as a numbered priority ladder (10 → 130) in §2.9, each with its error id and scope.
- **Errors (§1.5):** all 72 error ids present in prose and in the §5 table with exact HTTP statuses. Noted scaffold inconsistency: the `ERR_INVALID_PAGINATION` narrative says "[1, 200]" while `pagination_defaults.max` and validation priority 35 both say 100 — resolved as **[1, 100]** (two agreeing sources).
- **RBAC (§1.6/§1.7):** six roles, entity-backed vs opaque identities, site/hauler scoping, both segregation-of-duties rules (self-void, self-publish), and per-endpoint role lists in the §4 table.

**Path purity:** §3 contains 1097 backtick tokens and zero that start with `/`, are a bare HTTP method, or combine method+path; no raw method verbs or URL fragments outside backticks either. Paths appear only in the §4 table.

**Orchestrator verification**: `tail -20` confirms the file ends on a complete error-table row at a real section boundary (no mid-sentence truncation); 27 headings present through §5; grep for "harder than expert" and "scaffold" in PRD.md returns nothing.

## Step 5: Generate unit tests — 2026-09-05T02:44:00.000Z

Verification gauntlet complete. All 13 test files plus infrastructure are on disk and validated.

## Deliverables

**`test_helpers/` — 2,298 lines, 9 files** (at task root, not under `workspace/`)

| File | Lines |
|---|---|
| `types.py` | 496 |
| `fixtures.py` | 506 |
| `assertions.py` | 311 |
| `api_client.py` | 288 |
| `factories.py` | 242 |
| `api_errors.py` | 158 |
| `__init__.py` | 148 |
| `constants.py` | 81 |
| `test_users.py` | 68 |

**`test_suite/` — 8,934 lines, 14 files**

| File | Lines | Tests |
|---|---|---|
| `conftest.py` | 77 | — |
| `test_01_valuation_variants.py` | 645 | 14 |
| `test_02_lifecycle_loops_and_cascades.py` | 1046 | 25 |
| `test_03_precedence_and_boundaries.py` | 989 | 21 |
| `test_04_preconditions_intervals_and_compensation.py` | 1087 | 31 |
| `test_05_catalog_and_resource_shapes.py` | 532 | 19 |
| `test_06_initial_states_and_capture_guards.py` | 523 | 13 |
| `test_07_terminal_and_repeat_transitions.py` | 624 | 12 |
| `test_08_derived_metric_computation.py` | 734 | 14 |
| `test_09_authentication_scope_and_precedence.py` | 343 | 11 |
| `test_10_business_guards_and_uniqueness.py` | 484 | 11 |
| `test_11_endpoint_surface_and_not_found_codes.py` | 290 | 8 |
| `test_12_role_authority_and_duty_separation.py` | 932 | 25 |
| `test_13_optimistic_concurrency_and_consistency.py` | 628 | 15 |

## Counts

- **219 test functions → 250 collected cases** (parametrization expands 31).
- **Queue A (difficulty): 91 tests** across all 25 instances, every instance carrying >=2 tests (most 3–5).
- **Queue B (corner): 128 tests** across all 102 non-stub instances, one-to-one plus multi-test coverage on the rbac refusals.
- **127 of 127 real design instances covered; 0 uncovered.** The 35 `excluded_because:` stubs were not translated.

## SKIPPED design instances

**None.** Every one of the 127 non-stub instances passed the PRD-first two-condition filter, so no PRD-silence category applies. Individual *sub-assertions* were dropped where the design index contradicted PRD.md (details below), but no whole instance was dropped and no `skip`/`xfail` marker exists anywhere in the suite.

## Verification performed

- `python3 -m py_compile` clean on all 23 generated `.py` files; `import test_helpers` exposes 143 symbols.
- `pytest --collect-only`: 250 tests, zero import/fixture/collection errors.
- Design tags: exactly one `Design:` line per test, always the last docstring line, every tag resolving to a real non-stub instance name byte-for-byte; zero untagged, zero dual-tagged.
- **465 `PRD Coverage:` quotations machine-checked as whitespace-normalized literal substrings of `workspace/PRD.md` — 0 misses.**
- No forbidden vocabulary (`scaffold`, §1.8, §1.9, queue names, rule terminology) outside the mandated `Design:` line.
- AST scan for `validate_paginated` tuple-vs-dict misuse across all files: 0 hits (one partition had caught and fixed 7 such sites in `test_04` before reporting).
- AST scan for identity-less `list_*`/`get_*` client calls (which would 401): 0 hits.
- Zero duplicate test-function names within any file or class.
- Nothing written under `workspace/`; `worklog.md` untouched; no `.md` reports created; all `__pycache__`/`.pytest_cache` removed.

## PRD-vs-design adjudications for Step 7 triage

All resolved PRD-first. Worth carrying forward: stored `capture_window_end` = `captured_at + capture_lock_seconds` only (the +60 s turnaround widens the occupancy interval, not the field); `ERR_CLOCK_NOT_MONOTONIC` is 422 not 409; a new reduction target opens `PROPOSED` not `DRAFT`; the data-quality scan answers 200 with a bare array and no pagination meta; the attainment read names the field `site_diversion_rate_pct`; `voided_by_user_id` does not exist in the PRD and was dropped; line deletion pinned at 200 with an empty data object; after a baseline rejection only the four integer metrics are pinned to 0 (the PRD says "null or zero"). One genuine ambiguity: correcting an already-superseded entry with a *current* version token — both `ERR_ENTRY_ALREADY_CORRECTED` and `ERR_INVALID_ENTRY_STATE` sit at §2.9 step 11; the test asserts the former per the "more specific error named for that situation" clause.

**Orchestrator verification**: `test_helpers/` (9 .py) and `test_suite/` (14 .py) are at the task root; no stray `workspace/test_suite` or `workspace/test_helpers`; only one `worklog.md` in the tree.

## Step 6: Generate implementation — 2026-09-05T02:16:00.000Z

Implementation complete and verified.

## Files (`workspace/implementation/`, 3,071 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 8 | guarded `pip install` (`if ! python3 -c "import flask"`) + `exec python3 app.py` |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `app.py` | 51 | app factory, blueprint registration, `ApiError`/`HTTPException`/500 handlers, `0.0.0.0:$PORT` (default 10000). No seeding. |
| `db.py` | 120 | in-memory dict store, logical clock (`2026-08-01T00:00:00Z`), `base_row`/`touch`/`serialize`/`sort_rows`, ISO-8601 with exactly 3 fractional digits |
| `errors.py` | 108 | all 72 error IDs -> HTTP status + default messages |
| `response.py` | 65 | `meta`/`response_type`/`data` envelope, `req_`-prefixed ids, pagination meta |
| `validation.py` | 237 | typed field readers, scale enforcement, `limit`/`offset` (10/0, 1..100) |
| `middleware.py` | 94 | `X-User-Role`/`X-User-ID`, 6 roles, entity-backed identity resolution, site/hauler scoping |
| `services/calc.py` | 196 | all 13 calculations, `Decimal` + `ROUND_HALF_UP` only |
| `services/derive.py` | 470 | full-recompute aggregates, cascades, coaching rules, valuation passes, attainment, rollups, data-quality scan |
| `routes/{common,catalog,ops,entries,baseline,diversion,quality}.py` | 35/257/185/337/250/413/253 | all endpoints |

**68 endpoints implemented** — a normalized method+path diff against the PRD §4 endpoint table is byte-identical (68 vs 68, zero diff).

## Notable interpretation decisions
- **§2.9 precedence wins over prose orderings.** Where a workflow subsection listed preconditions in a different order than the 29-step normative list (hauler window-capacity before channel-unsupported; posture->capacity->empty at staging; station occupancy before loss-reason mismatch; OCC before target-state on corrections; body schema before path-id existence), I implemented §2.9, which self-declares itself normative. Scaffold `validations[].priority` agrees in each case.
- **Cascade version bumps taken literally from §2.7** ("every row a cascade touches"): revalued entries at close, re-routed entries on line add/delete/cancel, recomputed targets at close/accept. `Site.version` bumps only on capture, void, period close and settlement, per §2.6.
- **Scaled decimals accepted as JSON number *or* exact decimal string** (`"9.500"` and `9.5` both accepted). The PRD fixes each quantity's scale but never its wire form; integer gram/cent fields stay strictly integers, since §2.5 states those are integers.
- **Empty baseline metrics are zero, not null** (`baseline_waste_kg` = 0.0 etc.); only intensity is null, by its own explicit divide-by-zero rule.
- **Rollup publication guard ignores `detected_at`** — §3.10 says any OPEN finding at an in-scope site blocks publication regardless of date (an earlier date-filtered version was corrected).
- **`POST /_clock/set_current_utc` skips authentication entirely** (not "any role"): §2.1 says it requires no identity headers and neither authentication error applies.
- Three identical weighings yield two duplicate findings (`break` after the first matching earlier capture, since the finding is reported on the later member of a pair).

## Smoke-test result
Booted twice from a fresh process via `PORT=21473/21474 bash start.sh`; both `py_compile` clean across all 17 modules. A 25-step end-to-end flow all passed: site->food type->station->shift->capture (201, OVERPRODUCTION_SPIKE alert raised)->close (leaderboard + valuation cascade)->hauler->approve->consignment->line->stage->dispatch->ticket->accept->baseline submit/certify->target create (OCC)->activate->attainment read->data-quality scan->rollup create->publish->clock advance (target resolved `ACTIVE -> ACHIEVED`, `reevaluated_target_ids`/`resolved_target_ids` populated). Negative cases confirmed: 401 missing role, 403 unrecognized entity-backed identity, 400 bad decimal, 409 duplicate `site_code`. Settlement math spot-checked (net 6000 g -> 0.0060 t, base 14812 -> 6% tier -> 889 -> subtotal 15701).  Both servers killed by captured PID; ports 21473/21474 confirmed free, no pattern kill used, `__pycache__` removed.

**Orchestrator verification**: `workspace/implementation/` contains `start.sh`, `app.py`, `requirements.txt`, 6 top-level modules, `routes/` and `services/`.

## Step 7: Run tests and iterate — 2026-09-05T02:51:00.000Z

All 8 rounds green. Sweep complete and verified from the per-round `results.$i.json` files (not `sweep.log`).

## Summary

**Iterations run: 2** (initial sweep -> one fix batch -> confirming sweep)

**Sweep 1:** all 8 rounds identical at 248/250 — deterministic, no timeouts, no connection errors, zero round-to-round variance, so not load-induced. Both failures were the same assertion mismatch: `Expected error_id 'ERR_ENTRY_ALREADY_CORRECTED', got 'ERR_INVALID_ENTRY_STATE'`, in `test_13_optimistic_concurrency_and_consistency.py::TestCorrectionUnderEntryVersionGuard`.

**Sweep 2 (after fix):** results.1–8 all `250 / 250` passed, 0 failed, 0 errors, 0 skipped (~447 s per round).

**Tests deleted:** none. Both failing tests were PRD-covered and uniquely derivable; the defect was an assertion mis-translation, not PRD silence.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful.

**Fixes applied to `test_suite/`** — `test_suite/test_13_optimistic_concurrency_and_consistency.py`:
1. `test_the_same_corrector_refreshed_to_the_current_version_is_refused_as_already_corrected` -> renamed to `..._is_refused_as_invalid_entry_state`; expectation changed from `ENTRY_ALREADY_CORRECTED` to `INVALID_ENTRY_STATE` (line 110), and its PRD-Coverage docstring re-quoted to §3.4's ordered preconditions plus §2.9's normativity sentence.
2. `test_neither_refused_correction_disturbs_the_supersession_or_the_period_total` — same expectation change at line 137; the surrounding stale-version assertion and all state/total assertions are untouched.

**Why the tests were wrong, not the implementation:** both tests aim the at-most-one-correction rule at a target whose status is already `SUPERSEDED`. PRD §3.4 lists "the target capture must be `RECORDED` or `FLAGGED`, refused otherwise with `ERR_INVALID_ENTRY_STATE`" as the *first* precondition, and §2.9 puts target-row state at step 11 versus uniqueness at step 24 with "This ordering is normative; reporting a later error in place of an earlier one is a defect even when both conditions genuinely hold." §2.9's own closing note ("a stale `expected_entry_version` against an already-superseded entry reports the stale-version error, not the invalid-state error") confirms that with a *matching* version the invalid-state error is what surfaces. Both edits keep exact `error_id` assertions — no weakening, no `validate_error_is_one_of`, no skip/xfail.

**`ERR_ENTRY_ALREADY_CORRECTED` coverage is preserved:** `test_04_preconditions_intervals_and_compensation.py::test_the_restored_capture_may_not_be_corrected_a_second_time` (line 1085) exercises the only reachable path — successor voided, predecessor restored `SUPERSEDED -> RECORDED`, second correction refused — and passed in all 8 rounds of both sweeps. The implementation's already-corrected check was left exactly as-is.

`worklog.md` untouched; no `.md` files created; no broad pattern kills used.

**Orchestrator verification**: all 8 `workspace/implementation/results.{1..8}.json` exist (~88 KB each, mtime 02:50:57, one round = 447 s) and every one reports `250 / 250 passed, failed=0, errors=0, skipped=0`. The results payload contains the renamed test `test_the_same_corrector_refreshed_to_the_current_version_is_refused_as_invalid_entry_state`, confirming the sweep ran against the post-fix suite (test file mtime 02:43 < results mtime 02:50). Sweep artifacts are real, not claimed.

**Step 8 decision**: Step 7 made 2 `test_suite/` fixes, so the "zero fixes of any kind" skip condition does not hold and Step 8 runs. Note for Step 8's benefit: there were 0 `implementation/` fixes and 0 deletions, so a byte-identical `PRD_FINALIZED.md` is a legitimate outcome here — the only Step 7 signal is an error-precedence ambiguity the PRD may already settle in §2.9/§3.4.

## Step 8: Finalize PRD — 2026-09-05T03:04:00.000Z

`workspace/PRD_FINALIZED.md` written: one line revised, nothing else.

## Line counts
- `PRD.md`: 482 lines. `PRD_FINALIZED.md`: 482 lines. Line-count delta 0 (+0.0%); one line (226) rewritten in place.

## Changes
- **§3.4 (Curating the Capture Record — correction preconditions) — revise —** two things: (a) the ordered precondition list had `ERR_INVALID_ENTRY_STATE` *before* `ERR_STALE_ENTRY_VERSION`, which contradicts §2.9 (step 10 concurrency, step 11 state), §2.9's own closing note, and the implementation; the two clauses are swapped and each tagged with its §2.9 step. (b) Added the precedence of the at-most-one-correction rule relative to the target-state check (step 24 vs step 11), plus the fact that a successor row counts regardless of its own status (including `VOIDED`) — `implementation/routes/entries.py:242-247` and `:267-270`.

## Pre-edit search log (single edit)
**(a) Subject identified:** error precedence inside the correction endpoint — where the `expected_entry_version` guard, the target-row state guard, and the already-has-a-successor uniqueness guard sit relative to each other, and what counts as "a successor".

**(b) Impl paths enumerated (read/grepped, not just the Step 7 site):**
- `routes/entries.py:224-271` `correct_entry` — full precondition sequence read: version (242) -> status (245) -> shift `OPEN` (249) -> recipe `PUBLISHED` (258) -> routed (261) -> timing (266, via `_check_timing`) -> already-corrected (267) -> loss-reason/station (271).
- `grep` for `STALE_ENTRY_VERSION|STALE_SITE_VERSION|expected_*_version|ALREADY_CORRECTED|corrects_entry_id` across all of `implementation/` — only two version-guarded endpoints exist.
- `routes/baseline.py:132-155` `create_target` (the parallel `expected_site_version` endpoint) — token check sits after existence checks and before `ERR_TARGET_WINDOW_BEFORE_BASELINE`, with no target-state check in play, so the §3.4-local wording cannot mis-describe it.
- `grep` for `INVALID_ENTRY_STATE` — other emitters are `flag_entry` (153), `clear_flag` (166), `void_entry` (181) and `routes/diversion.py:203` (line creation against a `VOIDED`/`SUPERSEDED` capture). All are different operations; the new sentences are explicitly scoped to "a correction", so none is touched.
- `routes/entries.py:195-199` (the void -> predecessor `SUPERSEDED -> RECORDED` restore edge) and the successor scan at 267-270 — the scan filters only on `corrects_entry_id`, with no status filter, and no code path ever deletes an entry row. This is what makes the restored-capture path the only reachable route to `ERR_ENTRY_ALREADY_CORRECTED`, and it is why the "whatever status it currently holds, including `VOIDED`" clause is accurate rather than a guess.
- Reachability cross-check of the new state-over-uniqueness claim against every status a successor-bearing predecessor can hold: `SUPERSEDED` (fresh correction) -> `INVALID_ENTRY_STATE`; `RECORDED` (restored) -> `ENTRY_ALREADY_CORRECTED`; `VOIDED` (restored then voided) -> `INVALID_ENTRY_STATE`. All three match the wording.

**(c) Wording adjustments made to stay consistent with every enumerated path:** the precedence sentence was scoped to "a correction aimed at a capture" rather than stated as a general rule about `ERR_INVALID_ENTRY_STATE`, so it cannot be read onto flag/clear-flag/void or onto `routes/diversion.py`'s line-creation guard. The ordered list was left otherwise verbatim — in particular I did **not** convert it into an exhaustive sequence, because the impl also runs an `ERR_RECIPE_NOT_PUBLISHED` check on the effective recipe between the shift-`OPEN` and routed guards (`entries.py:258`); that check is outside the Step 7 scope and a tighter "these four and only these, in this order" phrasing would have manufactured a new mismatch.

## Notes
The Step 7 diff contained zero `implementation/` fixes and zero test deletions, so the edit surface was genuinely tiny. The assertion Step 7 changed (`ERR_ENTRY_ALREADY_CORRECTED` -> `ERR_INVALID_ENTRY_STATE`) was already uniquely derivable from §2.9, so that alone would have justified a byte-identical output. The reason the file is not byte-identical is a real PRD-internal contradiction sitting at exactly the Step 7 site: §3.4's "in order" list put the state check ahead of the version check, while §2.9 (declared normative), §2.9's explicit closing note about this precise superseded-entry case, and the implementation all put the version check first. The two sibling tests in `TestCorrectionUnderEntryVersionGuard` exercise both sides of that pair, which is what surfaced it.

**Orchestrator verification**: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (226), both files 482 lines, and `PRD_FINALIZED.md` still ends on the complete final error-table row.

**Step 9 plan**: run as three sequential file-partitioned passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module, because a single agent cannot hold 3,071 lines of implementation plus a 482-line PRD and still scan exhaustively. Pass 1 does the `cp PRD_FINALIZED.md PRD_COMPLETED.md` and covers the global/plumbing + catalog layer; passes 2 and 3 must NOT re-copy. Partition: (1) `app.py`, `db.py`, `errors.py`, `response.py`, `validation.py`, `middleware.py`, `routes/common.py`, `routes/catalog.py`; (2) `services/calc.py`, `routes/ops.py`, `routes/entries.py`; (3) `services/derive.py`, `routes/baseline.py`, `routes/diversion.py`, `routes/quality.py`.

## Step 9: Complete PRD — 2026-09-05T03:53:00.000Z

Run as three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place and were explicitly forbidden to re-copy). Final file: 482 lines, 52 lines revised versus `PRD_FINALIZED.md`, 21 ambiguity-pins + mismatch-revisions per pass as recorded below. No new sections; every edit is in-paragraph.

### Pass 1 of 3 — global plumbing + catalog (`app.py`, `db.py`, `errors.py`, `response.py`, `validation.py`, `middleware.py`, `routes/common.py`, `routes/catalog.py`)

**Setup:** `cp PRD_FINALIZED.md PRD_COMPLETED.md` done by pass 1. 482 lines before, 482 after.

**Counts:** 21 edited lines — **16 ambiguity-pins, 2 mismatch-revisions** (plus 3 combined-subject lines).

- §2.1 — insert — ambiguity — whitespace-only `X-User-ID` counts as absent; role name matched exactly with no trim/case-fold; `X-User-ID` used verbatim (untrimmed) when recorded and when compared — `middleware.py:58,65,80`
- §2.2 `api_request_id` — insert — ambiguity — `req_` + exactly 20 chars from upper-case letters and digits — `response.py:9,13`
- §2.2 `api_request_timestamp` — revise — **mismatch** — read from the **logical clock**, not host wall clock, so responses without an intervening clock advance share a timestamp — `response.py:19`
- §2.2 pagination bullet — insert — ambiguity — pagination fields appear on list reads *only*; single-resource, empty-data and the scan's array carry only the two base meta fields — `response.py:23,50,36`
- §2.3 pagination — insert — ambiguity — integrality judged on canonical spelling (`5.0`/`+5`/`05`/empty rejected, whitespace tolerated); offset past the end is an empty page, not an error — `validation.py:180-197,201`
- §2.3 ordering — insert — ambiguity — tie-break on equal `created_at` is insertion order — `db.py:110-112`
- §2.4 identity — insert — ambiguity — `id` is a random v4 UUID, lower-case hyphenated; `created_at`/`updated_at` read the logical clock — `db.py:83,87-97,100`
- §2.4 timestamps — insert — ambiguity — supplied instants accept 0 or 1–9 fractional digits, stored truncated (not rounded) to 3 digits; the clock alone retains microsecond precision, so monotonicity can reject two values that render identically — `validation.py:12,136-145`, `db.py:15-37`
- §2.5 — insert — ambiguity — rounded fractions emitted as plain JSON numbers, trailing zeros not preserved (10.000 -> `10.0`) — `services/calc.py:52-56`
- §2.8 — insert — **mismatch** — both scoping rules bind writes/transitions only; no read is scoped and list reads are never auto-narrowed to the caller's site/hauler — `middleware.py:83-94`
- §2.9 step 4 — insert — ambiguity — five shared schema conventions: non-empty untrimmed strings; declared decimal scale is a maximum; scaled decimal as JSON number or decimal string while int/bool admit only their own type; optional `null` == omitted, required `null` == missing; unknown body fields ignored; absent/empty body read as `{}` — `validation.py:22-40,43-53,56-66,78-111`
- §2.9 step 24 — insert — ambiguity — all string uniqueness keys compared by exact, case-sensitive equality — `catalog.py:34-36,81-83,147-149,215-217`
- §2.10 — revise — **mismatch** — the path identifier is resolved *after* the body clears step 4 (was "before any body content is inspected") — `catalog.py:169-170`, `entries.py:149-151`, `baseline.py:100-101`, `diversion.py:115-117`, `quality.py:98-100`, `ops.py:65-70`
- §2.10 filters — insert — ambiguity — boolean filters accept only `true`/`false`, date filters only `YYYY-MM-DD`; id/free-text filters matched by equality and never existence-checked; unrecognised query params ignored — `validation.py:207-237`, `routes/common.py:23-35`
- §3.1 sites — insert — ambiguity — `region_code` free-form text, exact-match filtered; target intensity "at most" 3 decimals — `catalog.py:30-33`
- §3.1 food types — insert — ambiguity — the three eligibility booleans mandatory with no default; `donation_shelf_life_hours` whole hours — `catalog.py:76-80`
- §3.1 recipes — insert — ambiguity — `quantity_kg`/`trim_loss_pct` unscaled decimals, `unit_cost_cents_per_kg` whole cents; ingredient elements stored back with exactly the four declared fields in array order — `catalog.py:115-129`
- §3.1 costing pass — insert — ambiguity — a `usable_yield_kg` rounding to 0.000 skips the division and leaves `cost_per_kg_cents` null; all three figures computed at creation while `DRAFT` — `services/calc.py:70-75`, `catalog.py:132-137,161`
- §3.7 haulers — insert — ambiguity — a channel outside the four values or a repeated channel is `ERR_INVALID_REQUEST`; channels stored in supplied order; `rate_cents_per_tonne`/`stop_fee_cents` mandatory integers; `capacity_kg_per_pickup` a mandatory unscaled decimal kg — `catalog.py:203-214`
- §4 intro — insert — ambiguity — a trailing slash addresses the same endpoint — `app.py:16`
- §5 intro — insert — ambiguity — unknown path / disallowed method answer in the error envelope with `ERR_INVALID_REQUEST` but keep transport status 404/405 — `app.py:28-41`

**Left alone as already uniquely pinned:** the §5 error catalog (compared programmatically to `errors.py::ERROR_STATUS` — 72 entries each, identical names and statuses); the auth ladder (six role spellings, `ERR_UNAUTHENTICATED`, `ERR_UNAUTHORIZED`, `ERR_IDENTITY_NOT_RECOGNIZED`, clock endpoint exemption); envelope shapes and 201-on-create / 200-on-transition; pagination semantics; `version` starting at 1 and +1 per mutation with `ConsignmentLine` carrying neither; clock start `2026-08-01T00:00:00Z` and `ERR_CLOCK_NOT_MONOTONIC`; `site_code` 2–12 + duplicate error and the six site derived fields; food-type category enum and filters; recipe `DRAFT`->`PUBLISHED` freeze semantics and the per-line-then-sum rounding order; hauler `PENDING`->`APPROVED`, `max_concurrent_pickups` default 1; §4 role lists for every catalog and clock row.

### Pass 2 of 3 — calculations + stations/periods + captures (`services/calc.py`, `routes/ops.py`, `routes/entries.py`)

**Integrity:** no `cp` and no whole-file `Write`; surgical `Edit` only. Pass 1's edits verified still present. 482 lines before -> 482 after; 31 lines cumulatively differing from `PRD_FINALIZED.md`.

**Counts: 13 changes — 12 ambiguity-pins, 1 mismatch-revision.**

- §3.2 station install — revise — ambiguity — `calibration_due_at` accepted even when already behind the clock; `tare_grams` recorded for reference only, never subtracted from `weight_grams`; install accepts all three station statuses — `routes/ops.py:37-42,53-56`
- §3.2 station status change — revise — ambiguity — a replacement `calibration_due_at` is honoured *only* on `MAINTENANCE -> ACTIVE`; the optional `note` is validated then discarded — `routes/ops.py:67-76`
- §3.2 station retirement — insert — ambiguity — no status edge recomputes any period or site aggregate; only the station's own row is written — `routes/ops.py:71-79`
- §3.2 new service period — insert — ambiguity — the four derived figures are evaluated at creation: `shift_waste_grams` 0, intensity 0.0 when `meals_served` > 0 and null when 0, `pre_consumer_share_pct` null, `capture_compliance_pct` 0.0 with >=1 `ACTIVE` station and 1.0 with none — `routes/ops.py:116-131` via `services/derive.py:57-77`
- §3.2 capture request — insert — ambiguity — operator `note` stored verbatim, null when omitted; body identifiers resolved in the order `station_id`, `shift_id`, `food_type_id`, `recipe_id` — `routes/entries.py:72-79,131`
- §3.2 capture preconditions — revise — **mismatch** — prose listed the loss-reason pairing before the occupancy check while §2.9 and impl evaluate occupancy first; a capture violating both reports `ERR_STATION_OCCUPIED` — `routes/entries.py:101-103`
- §3.2 `capture_compliance_pct` — insert — ambiguity — the quotient is never capped at 1.0000; the numerator counts reporting stations whatever status they now hold — `services/calc.py:108-111`, `derive.py:64-67`
- §3.4 flag / clear-flag — insert — ambiguity — neither edge moves the period's or site's `updated_at`/`version` — `routes/entries.py:146-170`
- §3.4 correction body — insert — ambiguity — a replacement `weight_grams` is held to the same >0 / <=200000 bounds as an original capture — `routes/entries.py:229-230`
- §3.4 correction preconditions — insert — ambiguity — the effective recipe (supplied else original) must be `PUBLISHED` or `ERR_RECIPE_NOT_PUBLISHED`, checked between the shift-state and routed-grams checks — `routes/entries.py:256-260`
- §3.4 correcting record — insert — ambiguity — the successor leaves its own `note` and `flag_reason` null rather than inheriting either — `routes/entries.py:292,303`
- §3.4 correction checks / response — insert — ambiguity — station `ACTIVE` status and calibration deadline are not re-examined on a correction; the operation answers HTTP 201 with the new correcting capture in `data` — `routes/entries.py:264-271,315`
- §3.6 `intensity_reduction_pct` — insert — ambiguity — also null when the frozen baseline intensity is 0.000 — `services/calc.py:152-159`

**Left alone as already uniquely pinned:** every `calc.py` formula and constant (recipe four-step costing; capture valuation; intensity; pre-consumer share; compliance; the full leaderboard formula with its 4.0/kg penalty capped at 60.0, 25.0 compliance weight, 3.0 bonus at >=0.60, 100-base, floor-then-cap clamp; diversion rate; coaching posture ladder; `absolute_reduction_pct`; all seven settlement steps with the base-fee-keyed surcharge tiers, strictly-greater 5.00 % variance tolerance and 10 % credit; constants 60 s turnaround, 300 s duplicate window, 25000 g outlier, 5000 g spike, 12.000/18.000 coaching thresholds, 10.000 default target intensity); the four legal station transitions and `ERR_INVALID_STATION_STATE`; per-site `station_code` uniqueness; the shift uniqueness triple; the whole close-shift path (`ShiftLead`-only, `OPEN`-only, final valuation ordered by `captured_at` then `created_at`, `valuation_delta_cents`, the four closure hops, ACTIVE-target recompute); the nine capture preconditions; strict-inequality calibration lapse; the loss-reason/station-kind matrix; the inclusive occupancy stretch and `capture_window_end`; both cost-basis snapshots; the post-capture recompute chain with exactly one version bump each on period and site; void's guard order and four-hop cascade including the `INTENSITY_BREACH`-only auto-resolve; `SUPERSEDED -> RECORDED` restoration; the at-most-one-correction check at step 24.

### Pass 3 of 3 — derived aggregates + baseline/targets + diversion/settlement + quality/rollups (`services/derive.py`, `routes/baseline.py`, `routes/diversion.py`, `routes/quality.py`)

**Integrity:** no `cp`, no whole-file write; 21 surgical `Edit`s. Passes 1 and 2 verified surviving (§2.2 logical-clock sentence and §3.2 uncapped-quotient sentence both present; cumulative diff 52 lines = 31 + 21). 482 lines before -> 482 after; `tail -5` ends on the real final error-table row.

**Counts: 17 ambiguity-pins, 4 mismatch-revisions.**

- §2.7 — revise — **mismatch** — "every row a cascade **touches** has its `updated_at` refreshed and `version` incremented" was a false universal; now scoped to rows a cascade *changes*, with the site-level recompute on line insert/delete/cancel named as the exception that bumps nothing — `routes/diversion.py:162,244,262` vs `db.py:100`
- §3.3 — revise — ambiguity — an alert's `acknowledged_by_user_id`, `resolved_by_user_id`, `resolution_note`, `resolved_at` are all null at creation — `derive.py:142-158`
- §3.5 — revise — ambiguity — window-matching `ACTIVE` targets recomputed at shift close also get `updated_at`/`version` moved — `routes/ops.py:164-166`, `derive.py:257-269`
- §3.6 — revise — ambiguity — a fresh baseline period's five counters/sums read 0 and only `baseline_intensity_kg_per_1k_meals` is null — `routes/baseline.py:49-56`
- §3.6 — revise — ambiguity — rejection clears the metrics back to exactly those creation values — `derive.py:351-358`
- §3.6 — insert — ambiguity — target body FKs resolved `site_id` then `baseline_period_id`; the bound baseline need not belong to the target's site — `routes/baseline.py:148-149`
- §3.6 — revise — ambiguity — a `PROPOSED` target's `performance_intensity_kg_per_1k_meals` and all three reduction percentages are null — `routes/baseline.py:178-181`
- §3.6 — insert — ambiguity — `/attainment` recomputes live for a target in any status and writes nothing back — `routes/baseline.py:208-231`
- §3.6 — insert — ambiguity — on clock advance `reevaluated_target_ids` and `resolved_target_ids` always hold the same ids in the same order; a still-open window appears in neither — `routes/quality.py:236-248`
- §3.7 — revise — **mismatch** — consignment creation checks the hauler window before the channel support, so a double violation reports `ERR_HAULER_WINDOW_CAPACITY`; FK order `site_id` then `hauler_id` — `routes/diversion.py:45-66`
- §3.7 — insert — ambiguity — line FKs resolved `consignment_id` then `waste_entry_id` — `routes/diversion.py:195-197`
- §3.7 — revise — ambiguity — `allocated_weight_grams >= 1` is a step-4 schema floor (`ERR_INVALID_REQUEST`), not an allocation failure — `routes/diversion.py:194`, `validation.py:62`
- §3.7 — insert — ambiguity — line insert/delete bumps the capture and the consignment; the site is recomputed but its `updated_at`/`version` stay put — `routes/diversion.py:242-244,260-262`
- §3.7 — revise — ambiguity — cancellation's site recompute moves no figure and no site version; each affected capture's `version` does bump — `routes/diversion.py:146-162`
- §3.8 — insert — ambiguity — ticket filing resolves `consignment_id` before a supplied `hauler_id`, and an unknown supplied `hauler_id` is `ERR_HAULER_NOT_FOUND`, not the mismatch error — `routes/diversion.py:291-295`
- §3.8 — insert — ambiguity — on ticket acceptance every re-evaluated `ACTIVE` target bumps whether or not its state changed — `routes/diversion.py:376-377`
- §3.8 — revise — **mismatch** — dispute places no precondition on the consignment, leaves `logistics_status` as it stands rather than forcing `DISPATCHED`, and bumps the consignment's `version` alongside the ticket's — `routes/diversion.py:381-396`
- §3.9 — revise — ambiguity — the scan's in-scope shifts are matched on `shift_date` alone, whether `OPEN` or `CLOSED` — `derive.py:397-398`
- §3.9 — revise — ambiguity — `WEIGHT_OUTLIER` emits one finding per qualifying capture carrying its own `station_id`/`shift_id`/`waste_entry_id`; the `ACTIVE`-station restriction binds only the missed-capture sweep — `derive.py:450-460`
- §3.9 — revise — **mismatch** — finding resolution's `resolution_note` is validated then discarded; the finding row carries no such field — `routes/quality.py:100`
- §3.10 — revise — ambiguity — a `DRAFT` rollup recomputes on every single-resource and list read, before list filters are applied, and a read-time recompute never moves `updated_at`/`version` — `routes/quality.py:204-218`

**Pass 3 closing statement:** every behavior in the partition traces to a PRD sentence that admits only the implemented reading. Two deliberate non-pins, neither an ambiguity: multi-row processing orders that impl fixes but that produce identical observable state (target supersession order at proposal, `ACTIVE`-target order on ticket acceptance), and the guard evaluation orders inside `stage`/`create_line`, which the normative §2.9 ladder already pins rather than being restated locally.

**Orchestrator verification**: `workspace/PRD_COMPLETED.md` is 482 lines, differs from `PRD_FINALIZED.md` in 52 lines (NOT byte-identical, so the scan demonstrably ran), carries the same 28 headings as `PRD.md` (no sections added or lost), and ends on the complete final row of the §5 error table. Both cross-pass spot-check sentences survive, so no pass clobbered an earlier one. No `.py` file under `test_suite/`, `test_helpers/` or `workspace/implementation/` was modified after the green sweep at 02:50, so the 8×250/250 result still describes the shipped code and tests. `__pycache__`/`.pytest_cache` removed.

## Pipeline complete — 2026-09-05T03:55:00.000Z

Steps 1–9 all finished. Final state: 8/8 sweep rounds at 250/250 passing; `PRD.md` -> `PRD_FINALIZED.md` (1 line) -> `PRD_COMPLETED.md` (52 lines vs FINALIZED).
