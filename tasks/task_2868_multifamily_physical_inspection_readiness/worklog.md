# Worklog — task_2868_multifamily_physical_inspection_readiness

## Step 1: Create task directory — 2026-09-05T08:22:54.622Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2868_multifamily_physical_inspection_readiness` and its `workspace/` subdirectory. Index 2868 was pre-assigned by the orchestrating command (no auto-allocation scan performed, per instruction, because up to 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-05T11:05:55.887Z

Subagent summary (verbatim):

Done — all three artifacts are in place and the lint is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2868_multifamily_physical_inspection_readiness/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2868_multifamily_physical_inspection_readiness/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2868_multifamily_physical_inspection_readiness/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     12
  §1.8 instances scanned:     26
  §1.9 instances scanned:     75
  Calls scanned (§1.8+§1.9):  972

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2868_multifamily_physical_inspection_readiness/`):

| file | lines |
|---|---|
| `SCAFFOLD.yaml` | 2844 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2401 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4163 |

`ls -la` shows only those three files plus the pre-existing `worklog.md` and `workspace/`; the task-scoped scratch dir `_scratch_2868/` was deleted, and no other task directory was touched or read.

**SCAFFOLD.yaml (§1.0–§1.7)** — 12 entities, 9 state machines, 3 §1.2.1 concurrency rules, 10 calculations, 38 validations, 59 endpoints, 62 error codes, 6 roles. `api_prefix: "/"`, complexity layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / selector_policy`, topology `flat`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`. Contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — single top-level key; all 9 rule ids, **26 instances** (>=2 each): dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 3, priority_pair_validation_conflict 3, boundary_precision_check 4, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 3.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — single top-level key; all **9 taxonomy sections**, **112 instances** (75 with full `test_recipe`, 37 `excluded_because` stubs citing §1.8 by name): entities 11, state_machines 15 (6 stubs), calculations 12 (7), validations 9 (6), endpoints 6 (3), errors 46 (13), rbac 7, cross_cutting_complexity_layers 5 (2), consistency_model 1. Every §1.6 error code is triggerable — 33 fresh error instances plus 13 stubs, with the 401/403 family in `rbac` and the three 412 stale-version codes in `cross_cutting_complexity_layers` (a comment in the errors section records which codes are driven by earlier sections). Names are unique across both design files, all stub citations resolve, no stub carries a recipe.

**Orchestrator post-step action:** the subagent noted the verbatim scenario copy left the difficulty directive `Generate task harder than expert level!` as line 2 of SCAFFOLD.yaml's `scenario:` block — a known leak path into PRD.md. The orchestrator deleted that line (and its blank line) with `sed -i '2,3d'`, re-verified the file parses as YAML with all 13 top-level keys intact, and confirmed zero remaining occurrences of the phrase in any of the three scaffold files.

## Step 3: Copy shared files — 2026-09-05T11:06:15.967Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes). No subagent.

## Step 4: Generate PRD — 2026-09-05T11:17:12.898Z

Subagent summary (verbatim):

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2868_multifamily_physical_inspection_readiness/workspace/PRD.md` — 514 lines / 106,060 bytes, ending cleanly at the last row of the §5 error table (no audit footer). `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened; no other task directory was read; `worklog.md` untouched; scratch dir removed.

## Section list

- **§1 Introduction** (3 paragraphs: regulatory pain point, four misaligned constituencies, three design commitments — pinning, posture-driven gating, explicit evaluation order)
- **§2 Global Specifications** — 2.1 Actors and RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Numeric Precision and Rounding · 2.7 Optimistic Concurrency on Parent Aggregates · 2.8 Readiness Posture: The Property-Wide Gate · 2.9 Cascade Discipline · 2.10 Resolution Order and Validation Precedence · 2.11 Segregation of Duties
- **§3 Business Logic** (9 subsections, lifecycle-ordered) — 3.1 Publishing an Inspection Standard and its Defect Catalogue · 3.2 The Property Portfolio and Unit Occupancy · 3.3 Self-Assessment Sweeps and the Work-Order Loop · 3.4 Scheduling an Inspection and Drawing the Unit Sample · 3.5 Tenant Notification, Access Coordination and Refusal Replacement · 3.6 Recording Deficiencies, Deductions and the Correction Clock · 3.7 Scoring, the Appeal Window and Rescoring · 3.8 Finalization, Corrective Action Plans and Follow-Up Inspections · 3.9 Capital Needs Planning and Reserve Allocation
- **§4 Endpoint Definitions** (4-column table) · **§5 Error Code Catalogue** (2-column table)

## Coverage verification (machine-checked against SCAFFOLD.yaml)

| Item | Result |
|---|---|
| Endpoints | 59 / 59 paths present in §4 table |
| Error codes | 62 / 62 present in §5 and each referenced in §2/§3 prose |
| Entities | 12 / 12 narrated |
| State machines | 9 / 9; all 41 transitions expressed with from/to, preconditions->error, side effects |
| Calculations | 10 / 10 expressed as precise prose (no pseudocode, no fuzzy words — grep for approximately/roughly/conservatively/etc. returns 0) |
| Validations | 38 / 38; priority ladder stated explicitly in §2.10 plus local orderings |
| Roles | 6 / 6 named; `PropertyOwner` rendered as `entity_backed:Property` with the full FK-reachability map, the other five as opaque operator ids |

**Contract 1 (Field-Name Coverage):** 140 required identifiers (129 entity fields + 71 body inputs + 30 query/path params, deduplicated) — 140 present as exact standalone backticked tokens, 0 missing. PASS.

**Contract 2 (Rule Coverage):** 3/3 `concurrency_rules` express write endpoint + `expected_inspection_version`/`expected_sweep_version`/`expected_property_version` + exact error id + 412; the four named cascade chains (deficiency-record 5 links, appeal-grant, closure-verification 4 links, capital-recompute) each stated link-by-link; sibling branches given equal density (finalize CAP_REQUIRED vs CLOSED, access GRANTED vs REFUSED, verify-closure PASSED vs FAILED, sweep CLOSED vs ABANDONED, PROVISIONAL vs FINAL score, INSPECTION_SCOPED vs CALENDAR_SCOPED). PASS.

**Contract 3 (§3 Path Purity):** 1,313 backtick tokens scanned in §3 — 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. PASS.

§2.2 confirmed byte-identical to `section-2.2-response-structure.md` (placeholders and empty `"data": { }` intact).

**Orchestrator verification (truncation guard):** `tail -15` shows the document ending on the final `ERR_ADJUSTMENT_EXCEEDS_POINTS | 422` table row — a real section boundary, not a mid-sentence cut. Section headings confirmed at lines 1/3/11/178/380/446. `grep -in "harder than expert|expert level|scaffold"` returns zero hits, so the Step 2 difficulty directive did not leak into the PRD.

## Step 6: Generate implementation — 2026-09-05T11:56:47.000Z

Launched concurrently with Step 5 in a single assistant message, so the implementation subagent could not read `test_suite/` (the directory did not exist when it started).

Subagent summary (verbatim):

Implementation complete and verified.

## Location
`/home/ubuntu/github/CodingPRD/tasks/task_2868_multifamily_physical_inspection_readiness/workspace/implementation/`

## Modules (3662 lines total, 21 .py files, all `py_compile` clean)

| file | lines | role |
|---|---|---|
| `app.py` | 119 | Flask factory, Decimal JSON provider, blueprint registration, error handlers (ApiError / 400 / 404 / 405 / catch-all 500) |
| `store.py` | 119 | 12 in-memory dicts, `_seq` counter, logical clock (epoch `2026-08-01T00:00:00Z`), instant formatting/parsing, id + request-id minting, `stamp_new`/`touch`/`public` |
| `errors.py` | 97 | all 62 error ids -> HTTP status + default message, `ApiError` |
| `auth.py` | 81 | 6 roles, `authenticate`, `require_owner` (PropertyOwner identity == `Property.id`), property-of-X resolvers |
| `shapes.py` | 196 | two-pass shape (prio 3) then enum (prio 4) validation, all 26 enums |
| `envelope.py` | 97 | object/array/paged/error envelopes, `limit` in [1,100] default 10, `offset` default 0, `total_count`/`has_more` |
| `calc.py` | 265 | all 10 calculations + every tuning constant, Decimal/ROUND_HALF_UP, tier ceil, waterfall reserve allocation |
| `derive.py` | 345 | counter recomputation, dual-variant scoring, posture derivation, symmetric work-order escalation, clock advance + OPEN->OVERDUE, sample candidate ranking |
| `routes/` | 2343 | `standards` 175, `portfolio` 163, `sweeps` 260, `workorders` 213, `inspections` 446, `selections` 204, `deficiencies` 118, `appeals` 238, `plans` 205, `capital` 151, `testing` 90, `common` 79, `__init__` 1 |

`start.sh` (executable): `set -euo pipefail`, `cd "$(dirname "$0")"`, `PORT="${PORT:-10000}"`, guarded flask install, `exec python3 app.py` bound to `0.0.0.0` in the foreground. `requirements.txt`: `flask>=2.2`.

## Coverage
- **Endpoints: 59 / 59** enumerated from `app.url_map`, and **59 / 59 actually exercised** at runtime (verified by replaying the werkzeug access log through the url_map adapter).
- **Error codes: 62 / 62** in `errors.ERROR_STATUS`.
- In-memory only: no file, SQLite, or /tmp persistence; zero seeded rows — a fresh boot has 12 empty collections and a clock reading exactly the epoch.

## Smoke test (port 43011, killed by PID afterwards; port now free)
Fresh boot ready in **0.61 s**. End-to-end run of the whole lifecycle plus negatives finished `SMOKE OK` with every step matching its expected status. Representative results:
- draw-sample on 40 units -> `sample_tier_value=8`, 8 slots; a REFUSED slot produced a `REPLACEMENT` slot at rank 9 with the back-pointer set.
- LT deficiency deduction `36.0` (10 x 3.0 severity x 1.0 area x 1.2 occupied-LT), posture flipped to `RESTRICTED` with `open_life_threatening_count=1`, and scoring was correctly blocked 409 until it was corrected/verified.
- scoring -> `provisional=97.4 final=97.4`, appeal deadline `2026-09-25T18:00:00.000Z` (360 h); a 2.00-point `SCORE_CORRECTION` grant rescored to `final=97.5`; finalize was blocked 409 while the appeal was pending.
- finalize -> `CAP_REQUIRED window=60d cap_due=2026-11-10T12:00:00.000Z followup_due=2026-11-20T12:00:00.000Z` (10-day LT follow-up offset off the rescore anchor).
- CAP reject -> resubmit -> approve -> schedule-follow-up (201, parent -> `FOLLOW_UP_SCHEDULED`); the follow-up scored 100.0, finalized `CLOSED` with `cap_required=false`, which then let the parent finalize `CLOSED` and completed the plan.
- capital recompute -> ranks 1/2 with priority `32.0`/`12.0` and cents `727273 + 272727 = 1000000` exactly; stale `expected_property_version` -> 412.
- clock advance to `2026-09-20` lazily flipped the MODERATE deficiency `OPEN -> OVERDUE` past its `2026-09-13T15:00` deadline; a VOID work order was excluded from `closure_verified_rate` (100.0).
- negatives: 403 role, 400 shape, 422 enum, 404 unknown id, 401 missing headers, 409 inspection-window conflict (and 201 for the same window once the conflicting inspection was CANCELLED).

Scratch dir and all `__pycache__` were removed; `worklog.md` and the test directories were never touched.

**Orchestrator audit of the two underscore-prefixed routes.** `routes/testing.py` registers only `POST /_clock/set_current_utc` and `POST /_inject/completed-inspection-history`. Both are verbatim PRD-declared: the clock capability at PRD.md:101-103 and §4 line 443, the history-seeding capability at PRD.md:378 and §4 line 444, with `PlatformAdmin` named as the authorised role for both at PRD.md:23. Neither is a test back-door, and the injection capability is client-driven through a declared endpoint rather than startup seeding, so the no-seeded-data rule holds.

## Step 5: Generate unit tests — 2026-09-05T12:53:24.285Z

Launched concurrently with Step 6 in a single assistant message. Logged after Step 6 because the test generator finished later; the two ran in parallel from 11:19Z.

Subagent summary (verbatim):

Step 5 complete. Full suite generated, audited, and verified.

## Output

**`/home/ubuntu/github/CodingPRD/tasks/task_2868_multifamily_physical_inspection_readiness/test_helpers/`** (9 files, 2736 lines)
`__init__.py` 65, `api_client.py` 421, `api_errors.py` 155, `assertions.py` 281, `constants.py` 277, `factories.py` 400, `fixtures.py` 770, `test_users.py` 122, `types.py` 245

**`.../test_suite/`** (14 test files + conftest, 6330 lines, **128 tests**)

| file | lines | tests |
|---|---|---|
| conftest.py | 53 | – |
| test_01_inspection_standards_and_defect_catalogue.py | 322 | 11 |
| test_02_unknown_identifier_reads.py | 161 | 10 |
| test_03_property_portfolio_and_units.py | 413 | 11 |
| test_04_sweep_planning_and_findings.py | 683 | 13 |
| test_05_work_order_repair_and_closure_verification.py | 717 | 12 |
| test_06_inspection_scheduling_and_windows.py | 244 | 5 |
| test_07_sampling_and_tier_policy.py | 350 | 7 |
| test_08_tenant_notice_and_access.py | 484 | 8 |
| test_09_deficiency_recording_and_deductions.py | 734 | 12 |
| test_10_correction_deadlines_and_the_clock.py | 296 | 7 |
| test_11_scoring_and_score_divergence.py | 319 | 5 |
| test_12_appeals_and_rescoring.py | 500 | 9 |
| test_13_finalization_and_corrective_action_plans.py | 607 | 11 |
| test_14_capital_needs_and_reserve_allocation.py | 447 | 7 |

## Design-index coverage

- **Queue A (difficulty): 26 / 26 instances used**, 53 tests, every instance carrying >=2 tests (one instance has 3).
- **Queue B (corner): 75 / 75 non-stub instances used**, 75 tests. All 37 `excluded_because:` stubs correctly left untranslated.
- **Skipped instances: none.** Every live instance passed the PRD-first two-condition filter, so there are no PRD-silent or not-uniquely-derivable gaps to report.

## Audit passes (both clean)

- **Design-citation:** 128 tests, 128 `Design:` lines, exactly one per test and always the last docstring line; 0 unknown tags; 0 unused live instances.
- **PRD-citation:** every test carries >=1 `PRD: "..."` quote that is a verbatim whitespace-normalised substring of `workspace/PRD.md` (0 non-verbatim, 0 under 8 words); all 61 distinct asserted `error_id`s appear verbatim in PRD prose; no `skip`/`xfail` anywhere.
- `python3 -m py_compile` passes on all 24 generated `.py` files and every test module imports cleanly.

## Bugs found and fixed in the helpers while writing files 13–14

- `factories.cap_resubmit_payload` was sending a `submitted_at` field the PRD's resubmit request does not define — removed.
- `fixtures.active_capital_items` filtered on `row["generation_status"]`, but the PRD names the `CapitalNeedItem` field `status`; the `CapitalNeedItem` TypedDict carried the same invented name. Both corrected (`status`, plus `computed_at` added to the TypedDict). This would have failed every capital-needs test with a `KeyError`.
- Added the `SEV_DOOR` blueprint and repointed `MOD_FLOOR` to `UNIT` / base `8.0` so the three capital instances' priority arithmetic (48.00 / 32.00 / 16.00) is reachable; `MOD_FLOOR` had no other consumer.
- Two PRD quotes in test_08 elided an em-dash clause and one in test_09 dropped a `§`, so they were not verbatim; all three corrected.

`_scratch_2868/` has been deleted, `worklog.md` was never touched, and `workspace/` contains no `test_helpers/` or `test_suite/` directory.

**Orchestrator layout verification:** `test_helpers/` and `test_suite/` both live at the task root; `find` confirms no duplicate copies under `workspace/` (a known Step 5 failure mode). `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/` and the orchestrator's `run_sweep.sh`. 14 test modules + conftest, 128 `def test_` functions counted independently. All `__pycache__` trees removed before the first sweep.

## Step 7: Run tests and iterate — 2026-09-05T13:20:00.000Z

Subagent summary (verbatim):

All 8 rounds are green: **128/128 passed, 0 failed, 0 errors** in every round.

## Summary

**Iterations run:** 2 sweeps (baseline + verification), plus targeted single-test smoke runs on a private port between them.

**Baseline:** identical 6 failures in all 8 rounds (122/128), so deterministic — no load-induced flakiness.

**Tests deleted:** none. Zero deletions — every failing assertion traced to a verbatim PRD sentence once the right one was located.

**Fixes to `test_helpers/`:**
- `test_helpers/factories.py` — `defect_definition_payload`: renamed the blueprint-selector parameter from `code` to `blueprint`. It previously doubled as both the `DEFINITION_BLUEPRINTS` key and the emitted `code` field, so any test wanting to base a payload on one blueprint while declaring a different catalogue `code` raised `TypeError: got multiple values for argument 'code'`. Fixed 2 failures (test_01 unknown-severity, LT-24h-deadline).
- `test_helpers/fixtures.py` — `draft_standard`: re-read the standard after creating its definitions. The fixture returned the creation-time snapshot (v1) while each definition creation recomputed `defect_definition_count` / `life_threatening_definition_count` and bumped the standard to v3 (PRD §3.1), so the caller's `draft_version` baseline was stale. Fixed 1 failure.

**Fixes to `test_suite/`:**
- `test_04_sweep_planning_and_findings.py::test_the_finding_response_carries_every_derived_consequence` — sweep version `+1` -> `+2`. PRD §3.3 gives the finding's own counter recompute +1, and §2.9 ("Every sweep that owns a work order touched by either direction ... has its own `version` incremented") gives a second increment when the resulting `RESTRICTED` posture escalates that same sweep's new work order — which the test's own `urgent_work_order_count == 1` assertion requires.
- `test_05_work_order_repair_and_closure_verification.py::test_a_verified_closure_demotes_an_unrelated_urgent_work_order` — two corrections. (a) The precondition asserted the unrelated SEVERE order was still `URGENT` after the life-threatening work order's completion; PRD §2.8 re-derives the posture "every time a deficiency ... changes status", and the completion bubbles that deficiency `OPEN -> CORRECTED`, so §2.9's demotion already fired. Corrected to `ROUTINE` + original `due_at`; the test now pins §2.9's escalate/demote symmetry and §3.3 link four's "judged on the posture as it stands, not on whether this request changed it" idempotence. (b) `urgent_work_order_count` expectation `0` -> `1`: PRD's completion narrative recomputes only `open_work_order_count` and `closure_verified_rate` while the void narrative *does* recompute `urgent_work_order_count`, which pins the predicate at `priority_tier == URGENT` among non-`VOID` rows rather than requiring `repair_status == OPEN`.

**Fixes to `implementation/`:**
- `workspace/implementation/derive.py` — `apply_posture_escalation`: `store.touch(work_order, bump_version=False)` -> `bump_version=True`. The function writes `priority_tier` and `due_at` directly, and PRD §2.4 makes `version` "a system-managed counter that increments by exactly 1 on every mutation of the row", with "none of them exempt". Fixed 1 failure (test_09).

**Notable dead end worth recording:** I initially read the implementation's property re-derivation at work-order completion (`routes/workorders.py::_rederive_owning_property`) as an unauthorised cascade, since §3.3's completion narrative enumerates only three rows for version increments. The decisive counter-evidence is the void path: PRD §3.3 likewise omits the property from the void enumeration, yet an already-passing test requires the property's counters to reflect a void. So §2.8's trigger list — not the §3 per-operation version enumerations — governs *when* the posture is re-derived, and the completion's `OPEN -> CORRECTED` bubble is squarely on that list. The implementation was correct; the test was not.

**Final per-round results:** round 1 – 128/128; round 2 – 128/128; round 3 – 128/128; round 4 – 128/128; round 5 – 128/128; round 6 – 128/128; round 7 – 128/128; round 8 – 128/128.

I did not touch `worklog.md`, and my scratch harness under `workspace/scratch_2868/` has been removed.

**Orchestrator independent verification of the sweep artifacts** (this check exists because a Step 7 subagent can report a clean sweep without leaving results files behind): all eight `workspace/implementation/results.{1..8}.json` exist, ~42 KB each, all timestamped 13:18Z. Re-parsed each with `json.load`: every round reports `passed=128 failed=0 errors=0 total=128`. Independently counted `def test_` across `test_suite/*.py` -> 128, matching the round totals, so no test was silently dropped to manufacture a green sweep. Step 7 made 1 `implementation/` fix, so Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-05T13:33:24.932Z

Not skipped: Step 7 applied 1 `implementation/` fix plus 2 `test_helpers/` and 2 `test_suite/` fixes, so the skip condition (zero fixes of every kind) did not hold.

Subagent summary (verbatim):

Done. Six surgical edits to `PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 514 lines / 106,060 bytes
- `PRD_FINALIZED.md`: 514 lines / 108,532 bytes (**+0.0% lines, +2.33% bytes**; every §-paragraph is one long line, so all edits are in-line)

## Changes (one bullet each)
- **§2.4** — revise — the sentence claiming the §3 narratives enumerate *exactly* which rows bump `version` now says those enumerations are read *together with* §2.8/§2.9: any posture re-derivation increments the property's `version`, and §2.9's sweep increments each work order it moves plus the owning sweep, whether or not the triggering §3 narrative repeats it — `derive.py:268-276`, `routes/workorders.py:25-31`
- **§2.9** — revise — escalation now applies only to `OPEN` orders **not already** `URGENT`; skipped rows are not written at all (no `due_at` drift, no `version` move) and every row actually moved has its `version` incremented by 1 — `derive.py:279-309` (esp. 287-288, 294, 303)
- **§3.3 (finding)** — insert — when the resulting §2.9 posture sweep moves a work order the filing sweep owns (including the one just created), that sweep's `version` advances by **2** across the request — `routes/sweeps.py:222-228` + `derive.py:305-309`
- **§3.3 (completion)** — revise + insert — the deficiency's `version` bumps only *when the bubble fired*; and the bubble carries the §2.8 re-derivation: cited unit recomputes `open_deficiency_count`, property recomputes its three counters, re-derives `readiness_posture` (+1 `version`) and runs §2.9's symmetric sweep; a completion with no bubble reaches neither unit nor property — `routes/workorders.py:70-97`
- **§3.3 (void)** — insert — defines `urgent_work_order_count` as the sweep's work orders whose `priority_tier` is `URGENT` with **no** filter on either status dimension, so an escalated row keeps `URGENT` (and stays counted) once repaired or voided — `derive.py:193-195`
- **§3.6 (fourth link)** — revise — same "not already `URGENT`" guard added to the record-cascade restatement of the escalation, deferring to §2.9 — `derive.py:279-303`

## Per-edit pre-edit search log
1. **§2.4** — (a) subject: which rows' `version` moves, and whether §3 enumerations are exhaustive. (b) enumerated all 8 `rederive_property` callsites (`routes/deficiencies.py:27`, `sweeps.py:228,251`, `appeals.py:197`, `inspections.py:310,351`, `workorders.py:31`, `derive.py:332`) — all pass `bump_version=True`; also checked non-callers: `routes/testing.py` seeding (no re-derive, matching §3.9's "posture left untouched") and appeal **denial** (`appeals.py:199-208`, no re-derive, matching §3.7). (c) phrased as conditional on a re-derivation *running* ("on one of the §2.8 triggers") rather than asserting §2.8's trigger list is mandatory, so the seeding carve-out and the denial path stay true; deliberately made no claim about **unit** `version` (units are touched with `bump_version=False` everywhere — pre-existing, out of scope).
2. **§2.9** — (a) subject: the escalate/demote pass semantics. (b) grepped every write of `priority_tier`/`due_at`: only creation (`routes/sweeps.py:209-210`, ROUTINE) and `derive.py:apply_posture_escalation`; read the escalate/demote branches and the `touched` sweep loop; cross-checked `test_09`'s surviving assertion that the escalated order's `version` is `before + 1` and `test_05`'s `SEV_ROUTINE_DUE_AT` round-trip. (c) wrote "each pass moves only the rows that are not already where it would put them ... is not written at all" so the statement covers both directions symmetrically (the demote branch already carried its own guard) instead of a one-sided "escalation only" claim.
3. **§3.3 finding** — (a) subject: the sweep's `version` arithmetic on a finding. (b) `routes/sweeps.py:file_finding` (222-228) plus `derive.rederive_property` -> `apply_posture_escalation` -> `recompute_sweep_counters` + `touch(sweep, True)` (305-309). (c) conditioned on "*does* move a work order this sweep owns" rather than "a life-threatening finding", because the second increment also fires on a demotion pass touching this sweep and does *not* fire when nothing moves.
4. **§3.3 completion** — (a) subject: the completion path's cascade and version enumeration. (b) `routes/workorders.py:complete_work_order` (65-98) and its `changed` guard, `_rederive_owning_property` (25-31), `derive.recompute_unit_open_count` (87-95); compared against the parallel `verify-closure` PASSED/FAILED paths (133-172) and the `void` path (188-212), which gate their property re-derivation the same way. (c) split the version enumeration ("of the work order, of the sweep and — when the bubble fired — of the deficiency") because the deficiency is only touched on the bubble; added the explicit no-bubble sentence; reused §3.6's existing "the cited unit recomputes `open_deficiency_count`" phrasing verbatim so no new claim about unit `version` is implied; left the void/FAILED narratives alone since §2.4's amended sentence already generalises their property re-derivation.
5. **§3.3 void / `urgent_work_order_count`** — (a) subject: the counter's predicate. (b) `derive.recompute_sweep_counters` (183-196) — `rows` is *all* the sweep's work orders and the urgent filter is `priority_tier == "URGENT"` alone, unlike `open_`/`void_` (repair) and `verified_` (verification); confirmed nothing resets `priority_tier` on void (`routes/workorders.py:188-190`); cross-checked `test_05`'s `assert_sweep_counters(sweep, 2, 1, 0, 1, 50.00)` where the sole urgent row is `REPAIRED`/`VERIFIED`. (c) dropped an earlier "...and never leaves the count" formulation — a `FAILED` verification returns `repair_status` to `OPEN`, which makes the row demotable again — leaving only the true statement that it stays counted while its repair status is not `OPEN`.
6. **§3.6 fourth link** — (a) subject: the record cascade's restatement of escalation. (b) same `apply_posture_escalation` body; also re-read §2.8's one-line escalation summary (it already defers "the mechanics are in §2.9", so no edit needed there) and §3.3's fourth link (already guarded on `priority_tier` `URGENT`). (c) added "on the terms of §2.9" rather than duplicating the skip/version rules, keeping one authoritative statement.

Two Step 7 items were confirmed as **pure fixture bugs with no PRD consequence**: the `factories.defect_definition_payload` `blueprint`/`code` split (both affected tests call `X.draft_standard(api, ())` with an empty catalogue, so no duplicate-code-vs-`ERR_LT_DEADLINE_MUST_BE_24H` precedence is exercised — `routes/standards.py:133-146` orders duplicate-code first, but nothing in Step 7 pins it), and the `fixtures.draft_standard` re-read (§3.1 already pins the standard's `version` +1 per definition).

**Orchestrator verification:** `PRD_FINALIZED.md` is 514 lines / 108,532 bytes versus PRD.md's 514 / 106,060 — `cmp` reports DIFFERS, so the patch is real (+2,472 bytes of in-paragraph inserts, no line-count change because each §-paragraph is a single long line). Tail confirms the file still ends on the final `ERR_ADJUSTMENT_EXCEEDS_POINTS` error-table row, i.e. no truncation.

## Step 9: Complete PRD — 2026-09-05T14:01:27.882Z

**Orchestrator decision (recorded per the autonomy directive).** Step 9 was run as THREE SEQUENTIAL module-partitioned passes over one shared `PRD_COMPLETED.md`, rather than as a single subagent. Rationale: a single agent asked to scan 3,662 lines of implementation against a 514-line PRD reliably under-scans and can emit a file byte-identical to its input, which would be a silent no-op. Partitioning by implementation module keeps each pass's read set small enough to be exhaustive. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying and were told the expected incoming size so they could verify they were editing in place rather than clobbering. Passes had to be sequential, not concurrent, because all three write the same file.

Partition: pass 1 = the cross-cutting infrastructure (`app.py`, `store.py`, `errors.py`, `auth.py`, `shapes.py`, `envelope.py`, `routes/common.py`, `routes/testing.py`). Pass 2 = calculations and derivations plus the standards/portfolio/sweeps/workorders routes (`calc.py`, `derive.py`, `routes/{standards,portfolio,sweeps,workorders}.py`). Pass 3 = the inspection lifecycle (`routes/{inspections,selections,deficiencies,appeals,plans,capital}.py`).

### Pass 1 summary (verbatim)

**cp performed** — `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` (verified `PRD_FINALIZED.md` existed).
- `PRD_FINALIZED.md`: 514 lines, 108,532 chars
- `PRD_COMPLETED.md` after my pass: 514 lines, 116,570 chars — 17 lines changed in place, all headings and all table rows byte-identical, no sections added or restructured (later passes can append freely).

**Counts:** 12 ambiguity-pins, 5 mismatch-revisions (17 edited lines).

- §2.1 actors/RBAC — revise — mismatch — a header present but empty now rejects with `ERR_UNAUTHENTICATED`, not just an absent one — `auth.py:29`
- §2.1 ownership enumeration — insert — ambiguity — added the missing `CapitalNeedItem` case (compared against the row's own `property_id`) — `routes/capital.py:138` + `auth.py:38`
- §2.2 `data` bullet — revise — mismatch — PRD claimed empty object for payload-less 2xx; clock-set actually returns `data: null` with `response_type: "object"` — `envelope.py:35`
- §2.2 pagination bullet — revise — ambiguity — the four pagination fields appear only on §2.3 collection listings; any other response (including `response_type: "array"`) carries only the two base meta fields — `envelope.py:41,50`
- §2.3 pagination — insert — ambiguity — `limit`/`offset` accept integer literals as bare numbers or strings; non-literal, out-of-range `limit` or negative `offset` -> `ERR_INVALID_REQUEST` 400; offset past the end is not an error — `envelope.py:74`
- §2.3 ordering — insert — ambiguity — ties on millisecond-resolution `created_at` (including rows minted by one request) break on the server's internal creation sequence — `store.py:118`
- §2.3 meta — insert — ambiguity — filters then owner-narrowing then paging; filters are exact string equality; out-of-enumeration filter values match nothing; undeclared query params ignored — `routes/common.py:55,73`
- §2.4 `version` bullet — revise — mismatch — starts at 1 and increments per the operation's own enumeration rather than on literally every write — `store.py:95,106`
- §2.4 cascade paragraph — insert — mismatch — the previously universal "every mutation increments version" is now qualified: some cascades refresh only `updated_at` (unit counter recomputes, and two other narrative-silent cascades) — `derive.py:95,114`
- §2.4 timestamps — insert — ambiguity — client instants echoed verbatim; the three server-minted instants (`created_at`, `updated_at`, `api_request_timestamp`) are real wall-clock, not the logical clock; `id` is canonical UUIDv4 — `store.py:97,107` + `envelope.py:17`
- §2.5 logical clock — insert — mismatch — clock-set returns `data: null`, accepts any instant with no monotonicity requirement, and the logical clock's authority is exactly three things (overdue sweep, `CALENDAR_SCOPED` window, `computed_at`) — `routes/testing.py:23`, `derive.py:315`, `routes/capital.py:39,109`
- §2.5 overdue sweep — insert — ambiguity — only `OPEN` rows are examined and the sweep is one-directional (`OVERDUE` never reverts, even on a backwards clock) — `derive.py:317-325`
- §2.6 precision — insert — ambiguity — decimals are emitted as JSON numbers, so trailing zeros are not preserved (`12.50` -> `12.5`, `0.00` -> `0.0`) — `app.py:50-54`
- §2.10 priority 3 — insert — ambiguity — bodyless/empty body = `{}`; non-object or unparseable body fails here; undeclared fields ignored; optional `null` = absent; numeric-string coercion; fractional value for an integer field fails; instant parsing accepts `Z`/offset/naive; first declared failure reported — `shapes.py:88-181`
- §2.10 priority 4 — insert — ambiguity — enum membership only after all shapes pass; a non-string enum value is a priority-3 failure; first declared bad enum wins; query values never enum-checked — `shapes.py:126,182`
- §3.9 seeding history — insert — ambiguity — pinned the injection end to end: empty `defect_definition_ids` allowed, body-FK resolution order, `scheduled_start`/`scheduled_end` both = `finalized_at`, exempt from the window-conflict test, no record cascade so area sums/counters stay 0 and `version` stays 1, per-deficiency field set and `points_deducted` via §3.6 with recurrence 1.0, no standard-membership or area/unit agreement check, `unit_id` attributed to every injected row, 201 with the inspection — `routes/testing.py:26-90`
- §4 endpoint intro — insert — ambiguity — trailing slashes accepted; unmatched path -> `ERR_INVALID_REQUEST` 404 and undeclared method -> `ERR_INVALID_REQUEST` 405 (the only non-400 uses of that id), neither preceded by authentication — `app.py:60,80,91`

Cross-checks that needed no change: `errors.py` `ERROR_STATUS` matches the §5 table exactly (62/62, no status divergence); every `authenticate()` role list matches the §4 table; owner narrowing is applied on every property-reachable listing and `require_owner` on every property-reachable single read, so §2.1's listing carve-out holds universally; all `rederive_property` calls do bump the property's `version`, so §2.4's §2.8/§2.9 claims stay true; the 30 enumerations in `shapes.py` match the PRD's prose enums. Nothing in `implementation/`, `test_suite/` or `test_helpers/` was modified, and I did not touch `worklog.md`.

### Pass 2 summary (verbatim)

Pass 1's edits are all intact. Pass 2 complete.

**File size:** started 514 lines / 116,570 chars -> finished **514 lines / 124,524 chars** (+7,954). Edited in place; all pass-1 markers verified still present (§2.4 version carve-out, §2.2 trailing-zeros, §2.10 empty-body, §2.1 owner narrowing, §2.5 clock epoch).

**Counts:** 19 edits — **13 ambiguity-pins, 6 mismatch-revisions.**

- §3.1 — revise — mismatch — `effective_date` is recorded and echoed but never compared against any instant by any rule; adoption alone makes a standard pinnable — `routes/standards.py:56` (no reader anywhere in impl)
- §3.1 — insert — ambiguity — the normalization test sums the values *as supplied* then rounds to 2dp, while each weight is rounded to 2dp independently for storage (33.333/33.333/33.334 passes, stores 33.33 each) — `routes/standards.py:34-39,55-57`
- §3.1 — insert — ambiguity — a defect definition may be added to a `DRAFT`, `ADOPTED` or `SUPERSEDED` standard alike; adoption status is not consulted — `routes/standards.py:132`
- §3.1 — insert — ambiguity — the duplicate-`code` check precedes the LT-24h-deadline check, so a doubly-bad definition reports `ERR_DUPLICATE_DEFECT_CODE` — `routes/standards.py:133-146`
- §3.2 — insert — ambiguity — `last_final_score` candidates require `scored_at` **and** `final_score` non-null, so seeded history never becomes the mirror; never returns to null — `derive.py:231-239`
- §3.2 — insert — ambiguity — an empty PATCH subset still succeeds and bumps `version`; no field can be cleared — `routes/portfolio.py:72-80`
- §3.2 — revise — mismatch — `occupant_display_name` is *not* coupled to `occupancy_status` (never required, never cleared); `owner_contact_email` gets no format validation — `routes/portfolio.py:112,159`
- §3.2 — insert — ambiguity — recomputing either unit counter refreshes `updated_at` but never bumps the unit's `version` — `derive.py:95,114`
- §3.2 — revise — mismatch — the property listing is exactly 4 roles; **`MaintenanceTechnician` is refused too** (old prose "four non-owner reviewing roles and the platform operator" implied 5) — `routes/portfolio.py:55`
- §3.3 — insert — ambiguity — area agreement precedes the scope test; a sweep `unit_id` need not belong to the sweep's property; `supersedes_deficiency_id` is existence-checked only — `routes/sweeps.py:139-176`
- §3.3 — insert — ambiguity — computed `correction_due_at`/`due_at` are emitted in canonical 3-fractional-digit `Z` form regardless of the supplied `observed_at`'s precision — `calc.py:258-261`
- §3.3 — insert — ambiguity — the completion bubble fires from `OPEN` only; an `OVERDUE` deficiency is never bubbled to `CORRECTED` — `routes/workorders.py:85`
- §3.3 — insert — ambiguity — segregation of duties is evaluated **before** state admissibility; skipped while `completed_by_user_id` is null — `routes/workorders.py:112-125`
- §3.3 — revise — mismatch — `VERIFIED` is also reachable from `REJECTED`; the deficiency bubble is taken from any status incl. `OVERDUE`; with a sibling unverified the chain stops after link one — `routes/workorders.py:133-149`
- §3.3 — revise — mismatch — `REJECTED` is reachable from `REJECTED`; **the property and unit are re-derived and the property's `version` increments** on a FAILED verification that returns the deficiency to `OPEN` (previously omitted) — `routes/workorders.py:157-171`
- §3.3 — insert — ambiguity — the work-order-void->`VOIDED` cascade also re-derives unit and property posture, and leaves the deficiency's `version` unchanged — `routes/workorders.py:204-212`
- §3.3 — revise — mismatch — sweep close does not blindly copy `closed_at` onto `last_sweep_closed_at`; it is re-derived as the latest `closed_at` over `CLOSED` sweeps — `routes/sweeps.py:250-251` vs `derive.py:241-246`
- §2.9 — insert — ambiguity — a sweep owning several moved work orders has its `version` incremented exactly once per pass — `derive.py:304-309`
- §3.4 — insert — ambiguity — "already holds" spans slots in **any** `selection_status` (a `REPLACED` slot still blocks its unit), and slots of other inspections are ignored entirely — `derive.py:339-347`

**Cross-partition note:** One edit landed outside my listed sections: **§3.6 "Being voided"** claimed *"The one route to `VOIDED` is a granted technical-error appeal"* — a false universal, since `routes/workorders.py:204` voids a `SELF_ASSESSMENT` deficiency when its last non-`VOID` work order is voided. The defect is in my module and invisible from pass 3's files (`deficiencies.py`), so I revised it to name both routes, verifying against `routes/appeals.py:66` that the appeal route reaches only `INSPECTION`-source deficiencies and the work-order route only `SELF_ASSESSMENT` ones. Pass 3 should keep that two-route wording if it touches the same paragraph.

### Pass 3 summary (verbatim)

Pass 3 complete. All edits were surgical `Edit` calls against the existing file — no `cp`, no rewrite.

**Size proof (edited in place)**
- **Start:** 514 lines / 124,524 chars
- **Finish:** 514 lines / 129,345 chars (+4,821 chars, zero line-count change — all inserts are in-paragraph)
- Section headings verified byte-identical to `PRD_FINALIZED.md`'s heading set.

**Pass 1 / pass 2 edits confirmed still present**
- §2.4 version carve-out — `"increments by exactly 1 on each mutation the acting operation is specified to count as one"` OK
- §2.6 trailing-zeros sentence — `"JSON numbers do not carry trailing zeros..."` OK
- §3.6 two-route `VOIDED` wording — `"The second reaches only a SELF_ASSESSMENT deficiency..."` OK (untouched)
- §3.4 slot-uniqueness wording — `'"Already holds" is read across every slot of this inspection...'` OK (untouched)
- §3.2 `last_final_score` mirror rule OK (I referenced it rather than restating it)

**Counts:** Ambiguity-pins: 17. Mismatch-revisions: 3.

- §3.4 — insert — ambiguity — draw-sample's response payload is the updated `Inspection`, not the created `SampleSelection` rows — `routes/inspections.py:181`
- §3.5 — revise — ambiguity — the notice's owning-inspection status check names `ERR_INSPECTION_INVALID_STATE` (409), and the slot's own state is tested first — `routes/selections.py:79,85`
- §3.5 — revise — ambiguity — the entry-window conflict scan spans slots of any inspection in any `access_status`, and ignores slots with no window recorded — `routes/selections.py:21-36`
- §3.5 — revise — ambiguity — `refusal_reason` is optional even on a refusal and ignored on `GRANTED`; both access branches name their errors (`ERR_SELECTION_INVALID_STATE` / `ERR_INSPECTION_INVALID_STATE`, slot first) and answer with the slot — `routes/selections.py:133,137,143,162,204`
- §3.6 — insert — ambiguity — `supersedes_deficiency_id` must resolve (`ERR_DEFICIENCY_NOT_FOUND`) but is otherwise unconstrained: no inspection, property, unit, definition or status agreement — `routes/inspections.py:233`
- §3.6 — revise — ambiguity — a correction's optional `note` overwrites the stored note when supplied, leaves it when omitted — `routes/deficiencies.py:85`
- §3.6 — revise — ambiguity — same `note` semantics on verification — `routes/deficiencies.py:114`
- §3.7 — revise — **mismatch** — `last_final_score` is re-derived by §3.2's mirror rule, not assigned the new `final_score` (a later-`scored_at` inspection keeps the mirror) — `derive.py:231-239` via `routes/inspections.py:351`
- §3.7 — insert — ambiguity — an unresolvable `contested_deficiency_id` reports `ERR_DEFICIENCY_NOT_FOUND` before the targeting rule — `routes/appeals.py:54-55`
- §3.7 — insert — ambiguity — every appeal decision writes `reviewer_note` as supplied, so omitting it stores null and clears an earlier note — `routes/appeals.py:171,203,212`
- §3.7 — revise — ambiguity — `granted_point_adjustment` is rounded half up to 2dp before the bounds test and stored rounded; `requested_point_adjustment` is stored verbatim and never bounded — `routes/appeals.py:161,163,173`; `shapes.py:146-160`
- §3.7 — insert — ambiguity — an appeal grant also recomputes the contested deficiency's unit's `open_deficiency_count` — `routes/appeals.py:186-189`
- §3.7 — insert — ambiguity — a grant increments the inspection's `version` unconditionally, withholding only the `APPEALED -> SCORED` return when another appeal is non-terminal — `routes/appeals.py:192-194`
- §3.7 — revise — **mismatch** — a denial increments the inspection's `version` only when the return to `SCORED` actually occurs (PRD claimed it always does) — `routes/appeals.py:205-207`
- §3.7 — insert — ambiguity — an appeal resubmission keeps the `reviewer_note` (unlike a plan resubmission) — `routes/appeals.py:233-236`
- §3.8 — insert — ambiguity — `ERR_APPEAL_PENDING` is tested before the inspection's status, so it wins over `ERR_INSPECTION_INVALID_STATE` — `routes/inspections.py:378-384`
- §3.8 — insert — ambiguity — plan submission requires no inspection status, permits a second plan on the same inspection, and skips the `target_completion_at` test while `cap_due_at` is null — `routes/plans.py:24-31,47-51`
- §3.8 — revise — ambiguity — a plan review's `reviewer_note` is written as supplied (null when omitted) — `routes/plans.py:110,117`
- §3.8 — revise — **mismatch** — the follow-up window-conflict test includes the parent inspection's own window, since `CAP_APPROVED` is live (PRD said "every *other*" window) — `routes/plans.py:178`; `routes/inspections.py:16,29`
- §3.8 — revise — ambiguity — schedule-follow-up answers with the new follow-up `Inspection`, not the plan; the plan's `version` increments when it reaches `COMPLETED` — `routes/plans.py:205`; `routes/inspections.py:444-446`
- §3.9 — revise — ambiguity — the capital recompute returns a `response_type` `array` in `allocation_rank` order, with no pagination `meta`, and an empty generation is a 200 with `data: []` — `routes/capital.py:111-131`; `envelope.py:41-47`

Ordering questions that impl resolves *consistently with §2.10*'s priority ladder (appeal status-before-targeting-before-window; follow-up conflict-before-timing) were left alone, since §2.10 is already normative for precedence and §3 prose order is not.

### Orchestrator final verification

- `PRD.md` 514 lines / 106,060 chars -> `PRD_FINALIZED.md` 514 / 108,532 -> `PRD_COMPLETED.md` 514 / 129,345. Net Step 9 delta +20,813 chars across 56 edits (42 ambiguity-pins, 14 mismatch-revisions).
- `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md`, so the scan genuinely ran (a byte-identical result would have meant a silent no-op and required re-running).
- All 5 `##` section headings present; the file still ends on the final `ERR_ADJUSTMENT_EXCEEDS_POINTS | 422` error-table row, so no pass truncated it.
- `grep -ic "scaffold|harder than expert"` over `PRD_COMPLETED.md` returns 0 — no scaffold reference and no difficulty-directive leak survived into the final contract.
- `find` over `workspace/implementation/`, `test_suite/` and `test_helpers/` for `.py` files newer than `results.1.json` returns nothing: Step 9 was documentation-only, so the Step 7 result (8 rounds x 128/128) still describes the shipped code.

**PIPELINE COMPLETE.** All nine steps executed; `workspace/PRD_COMPLETED.md` written.
