# Worklog — task_2784_catalog_circulation_planning

## Step 1: Create task directory — 2026-09-04T20:43:55.272Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2784_catalog_circulation_planning` and `.../workspace`. Index 2784 was pre-assigned by the orchestrating prompt (no ./tasks/ scan, no auto-allocation) because up to 32 pipelines run concurrently on this host.

## Step 2: Generate Scaffold — 2026-09-04T22:33:00.000Z

All three scaffold artifacts are complete and the scaffold linter is clean.

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2784_catalog_circulation_planning/`)
- `SCAFFOLD.yaml` — 3012 lines / 164 KB, §1.0–§1.7, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2417 lines / 181 KB, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3284 lines / 254 KB, single key `scaffold_corner_design`

**Lint**: `VERDICT: clean lint` — 818 calls scanned across §1.8+§1.9, 55 endpoints, 13 entities, all §1.1 FKs reverse-reachable.

---

**Summary for worklog.md**

Task 2784 Catalog Circulation Planning — scaffold generated fresh from the scenario text plus the generator spec (no sibling task consulted).

Domain `catalog-circulation-planning`, prefix `/catalog-circulation`. Archetypes: quota_allocation over ledger_reconciliation; topology graph; state-machine shape cyclic (plus two parallel dimensions on Drop and a branching fork on MergePurgeRun); role model segregation_of_duties over peer roles; consistency immediate. Active complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

Scenario coverage — every clause is realised by named machinery: RFM segmentation with contact strategy (`segment_rfm_score`, 3 banded components, tier→strategy defaults, self-referential segment hierarchy with leaf-only rollups); prospect list rental and cooperative-database modeling (`rental_expected_response_rate`, coop decile lift bands including a negative bottom band); merge-purge dedup (`merge_purge_net_mailable_names`, coop-score processing order, first-list inter-list exemption, names-conservation invariant); circulation plan by drop with page counts, square-inch allocation and product placement (`drop_piece_weight`, `page_placement_space_productivity`, half-open page intervals); cost per book from printing/paper/postage with presort optimisation (`drop_provisional_cost_per_book`, `drop_cost_per_book` ESTIMATED_POSTAGE vs PRESORTED_ACTUAL, `drop_postage_total` with tier minimum fallback, weight surcharge and all-or-nothing automation discount); response and demand forecasting (`line_demand_forecast` PRE_MERGE_GROSS vs POST_MERGE_NET) with matchback attribution to online orders (`matchback_attribution` LAST_TOUCH_MAIL vs FRACTIONAL_MULTI_TOUCH, half-open window); contact fatigue and suppression across mail/email/digital (`contact_fatigue_score` decay bands + `SuppressionRule` caps by channel scope and priority); test design with holdout groups (`TestCell`, `test_cell_lift`, holdout carve-out in the waterfall); per-segment profitability (`line_profitability`, `plan_profitability_rollup`, `GET .../profitability`).

Counts — §1.1 13 entities; §1.2 8 state machines; §1.2.1 2 concurrency rules; §1.3 15 calculations; §1.4 28 validation rules (priority ladder 10→94); §1.5 55 endpoints (2 test-driving: logical clock, online-order feed); §1.6 47 error codes; §1.7 5 roles.

§1.8 — 9 difficulty rules, all present, 24 instances (2/3/3/2/3/3/3/2/3 across dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

§1.9 — 9 sections, 84 instances (53 live recipes + 31 `excluded_because` stubs pointing at the §1.8 instance that already covers the claim): entities 12, state_machines 17, calculations 15, validations 13, endpoints 6, errors 12, rbac 3, cross_cutting_complexity_layers 5, consistency_model 1. All 47 error codes are triggerable by at least one §1.8/§1.9 instance.

One SCAFFOLD.yaml correction was made during §1.9 authoring: `contact_fatigue_score` previously assigned the immutable ContactEvent row's own `channel_weight`/`decay_factor_bps`/`weighted_points` on every recompute, contradicting §1.5's "frozen at creation". The formula now derives decay locally from the current clock and the note pins that stored row values may disagree with a row's current contribution.

Orchestrator note: verified no "harder than expert" difficulty-directive text leaked into any of the three scaffold files (grep clean).

## Step 3: Copy Shared Files — 2026-09-04T22:34:46.334Z

Copied `./INSTRUCTION.md` → `tasks/task_2784_catalog_circulation_planning/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T22:52:00.000Z

PRD complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2784_catalog_circulation_planning/workspace/PRD.md` — 463 lines, written as 1 `Write` + 10 `cat >>` appends (no 64k truncation), ending cleanly at the final row of the §5 table.

**Section list**
- `# Catalog Circulation Planning API — Product Requirements Document`
- §1 Introduction
- §2 Global Specifications & System-Wide Principles: 2.1 RBAC · 2.2 API Response Structure (byte-identical copy of `section-2.2-response-structure.md`) · 2.3 Pagination and Deterministic Collection Ordering · 2.4 Resource Identity, Timestamps and Version Semantics · 2.5 The Season Rate Card · 2.6 Integer Money, Basis Points and Pinned Rounding · 2.7 Three Conserved Ledgers · 2.8 Nested Path Resolution and Foreign-Key Existence · 2.9 Optimistic Concurrency Control on Two Write Paths · 2.10 The Order in Which Requests Are Rejected (28-step ladder) · 2.11 The Logical Clock
- §3 Business Logic & Workflows (9 subsections): 3.1 Season Setup and the Housefile Segmentation Hierarchy · 3.2 Prospect List Procurement and Cooperative Modeling · 3.3 Building the Mailable Universe with Merge-Purge · 3.4 Drops, Book Weight and the Page-Space Ledger · 3.5 Audience Lines, Holdouts and the Allocation Waterfall · 3.6 Costing, Review, Approval and the Revision Cycle · 3.7 Postal Presort, Mailing, and the Five-Hop Fatigue Cascade · 3.8 Contact Governance, Fatigue Pressure and Sticky Suppression · 3.9 Reading the Result: Test Cells and Matchback Attribution
- §4 Endpoint Definitions — 4 columns (Method | Path | Description | Authorized Role(s)), 55 rows
- §5 Error Code Catalogue — 2 columns (Error ID | HTTP Status Code), 47 rows

**Scaffold coverage:** §1.0 response_envelope + pagination_defaults → §2.2/§2.3; §1.1 all 13 entities (150 field/param names) → §2.4–2.8, §3.1–3.9; §1.2 all 8 state machines (every state and transition string present) → §3.2–3.9; §1.2.1 both concurrency rules → §2.9 + §3.3/§3.9; §1.3 all 15 calculations → §2.6, §3.1–3.9; §1.4 all 28 validations → §2.10 ladder + in-context prose; §1.5 all 55 endpoints → §4; §1.6 all 47 errors → §5 (each also referenced in the narrative); §1.7 all 5 roles → §2.1 + §4. `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` and all sibling task directories were never opened or grepped.

**Hard Contract reports**

1. **Field-Name Coverage — PASS.** Programmatic diff of all 150 scaffold field names, request-body keys, query params and path params against the PRD's backticked token set (400 distinct): 0 missing. One gap was found and fixed during verification — `circulation_line_id` (TestCell FK) was absent and was added to §3.9 ("The cell records that owning line in its own `circulation_line_id`…").
2. **Rule Coverage — PASS.** All 8 state machines' states/transitions, both OCC rules with their observed-version echo fields, all 15 calculations (including pinned per-component rounding, the 232+22+52=306 print/paper/postage example, the 20000/3 → 6666/6668 attribution remainder, the 9000-bps all-or-nothing automation discount), all 28 validation priorities in exact order with their `applies_to` scopes, every field default and bound, the five-hop mail cascade, the rental-cancel five-step unwind, plan-cancel/request-revision side-effect sets, the automatic `COSTED → DRAFT` invalidation, and all three conserved ledgers are expressed in prose. All 47 error ids appear in the §2/§3 narrative, not only in the §5 table.
3. **§3 Path Purity — PASS.** No backticked token inside §3 begins with `/`, is a bare HTTP method, or combines method+path (automated scan of lines 171–348 returned none). All paths and methods live in §2 and §4 only. Also verified: no operator syntax (`==`, `&&`, `->`, `>=`, `floor(`, `min(`, `if (`) and no fuzzy quantifiers ("approximately", "roughly", "about N") anywhere in the document.

Orchestrator anti-truncation check: `wc -l` = 463; `tail` ends at the last §5 error row (`ERR_PLAN_CONTRIBUTION_NEGATIVE | 422`), a real section boundary — not truncated. All 5 top-level sections present. No difficulty-directive or "scaffold" leakage in PRD.md.

## Step 5: Generate Unit Tests — 2026-09-05T01:14:00.000Z

Stage 2 is complete. Everything is at the task root; nothing was written under `workspace/`.

## Files written

`test_suite/` — 51 test modules + `conftest.py` (48), **13,166 lines** of tests. The last three modules finished this session:

| file | lines | tests |
|---|---|---|
| `test_49_a_stale_plan_token_blocks_merge_purge.py` | 177 | 5 |
| `test_50_a_stale_drop_token_blocks_matchback.py` | 255 | 5 |
| `test_51_every_derived_field_settles_inside_the_request.py` | 392 | 8 |

`test_helpers/` — Stage 1: `__init__.py` 56, `api_client.py` 429, `api_errors.py` 107, `assertions.py` 435, `constants.py` 93, `factories.py` 232, `fixtures.py` 573, `test_users.py` 73, `types.py` 418.

## Instance coverage

- **Queue A (difficulty §1.8): 24/24 non-stub instances → 48 tests.** No stubs exist in that index.
- **Queue B (corner §1.9): 53/53 non-stub instances → 203 tests.** The 31 `excluded_because:` stubs were not translated (verified programmatically: no `Design:` tag resolves to a stub).
- **251 tests, 77 distinct instances, 297 PRD citations.** No instance was skipped — every non-stub instance in both indices passed the PRD-first two-condition filter.

## Verification run at the end

A validator walked every test function's docstring and checked it against the two design yamls and `workspace/PRD.md`:
- every test carries exactly one trailing `Design:` line; zero untagged, zero dual-tagged, zero tags pointing at a non-existent or stubbed instance;
- every `PRD §x: "…"` block is verbatim after whitespace normalisation (0 failures);
- `pyflakes` clean on all 52 files in `test_suite/`; `compileall` clean; `__pycache__` removed afterwards.

That sweep caught and fixed 9 pre-existing citation defects from earlier chunks, worth flagging since they were silent C1/C3 violations: `test_05`, `test_07` (x2), `test_11`, `test_33` and `test_37` each truncated a long PRD sentence at a semicolon or clause boundary and substituted a full stop, so the quote was not grep-survivable — each is now extended to the real sentence end. `test_16` fused two separate PRD bullets into one quote and is now split into two blocks; `test_31` had a second citation starting mid-line. One new citation was also caught: a §2.7 "budget identity" sentence that had been paraphrased does not exist, and it is replaced with the real text plus §2.7's closing sentence ("There is no read repair, no background reconciliation, and no eventual consistency…").

## Notes on the three new modules

- `test_49` / `test_50` pin both OCC paths as self-invalidating tokens, prove the refusal is inert (no run row, prior run not superseded, parent version unmoved), and show the guard is equality rather than a lower bound.
- `test_50`'s priority leg required a second drop under the same plan; since `POST /drops` demands an editable plan, drop 2 is opened while the plan is still `DRAFT`. The test asserts the borrowed token also mismatches drop 2's version before asserting the 409 wins, so the priority-9-over-priority-10 claim is genuinely exercised.
- `test_51` builds S_HOT primed to 90 fatigue points by three MAIL touches in the 7500-bps decay band; the mail cascade's own contact adds the full 40, landing on exactly 130 against the 100 threshold. It then asserts all five hops on the *first* read after `POST /mail` and repeats all five reads to show byte-identical results.

**Orchestrator deviation note (recorded per AUTONOMY, decision made without escalation):** the skill mandates launching Steps 5 and 6 in a single assistant message so that the implementation generator is *physically* unable to read `test_suite/` (the directory does not exist at its spawn time). I issued Step 5 alone, so Step 6 will start after `test_suite/` already exists on disk. Rather than delete and regenerate the tests (which would burn ~8.5h of generation for a purely procedural miss), I compensate by giving the Step 6 subagent an explicit, emphatic hard constraint forbidding it from reading, listing, grepping, or otherwise consulting `test_helpers/`, `test_suite/`, or either `SCAFFOLD_*_DESIGN.yaml` — its inputs are exactly `workspace/INSTRUCTION.md`, `SCAFFOLD.yaml`, and `workspace/PRD.md`. Verified afterwards: test dirs are at the task root (not under `workspace/`), 52 files in `test_suite/`, 251 test functions, 2416 lines of `test_helpers/`, and no test/conftest strays anywhere under `workspace/`.

## Step 6: Generate Implementation — 2026-09-05T01:43:41.541Z

Implementation complete and smoke-verified.

## What was built

`workspace/implementation/` — Python 3 + Flask, in-memory dicts only, zero seeded data, 3694 lines across 18 files:

| File | Lines | Role |
|---|---|---|
| `app.py` | 71 | factory, 7 blueprints under `/catalog-circulation`, `ApiError` + 400/404/405/500 handlers, `PORT` bind |
| `start.sh` | 10 | guarded launcher, `exec python3 app.py` in the foreground |
| `util.py` | 96 | `rhu_div` (exact integer half-up), `floor_div`, `whole_days`, 3-digit ISO formatting, `req_` ids |
| `db.py` | 75 | 14 in-memory tables, logical clock (`2026-08-01T00:00:00Z`), `touch`/`apply_changes`/`by_created` |
| `errors.py` | 115 | all 47 error codes + statuses |
| `response.py` | 71 | `meta`/`response_type`/`data` envelope, list `meta` pagination |
| `middleware.py` | 53 | 5-role RBAC, 401-before-403 |
| `validate.py` | 192 | schema coercion, pagination (10/1/100/0), filter parsing |
| `services/calc.py` | 252 | the 15 pinned calculations as pure kernels |
| `services/domain.py` | 817 | derived-field recomputes, 3 ledgers, merge-purge, waterfall, 5-hop mail cascade, rental unwind, matchback |
| `routes/{config,segments,rentals,plans,drops,lines,measure}.py` | 172/202/155/364/455/287/306 | the 55 endpoints |

Coverage verified mechanically: **55 routes registered** (exact match to §4's table), **47/47 error codes both catalogued and raised**, all 8 state machines, 15 calculations and the 28-step rejection ladder implemented in stated order (each guard is commented with its ladder step number).

## Smoke test

Booted from a fresh process on port 47913 via `PORT=47913 bash start.sh`, ran a 90-call end-to-end script (season → segments → rental lifecycle → merge-purge → drop → placements → lines → allocate → batches → cost → submit → approve → presort → mail → cascade → test cells → matchback → finalize → revision back-edge → plan cancel → rental-cancel unwind, plus RBAC/pagination/404/412/409/422 negatives): **0 failures**. Killed only that PID; no broad `pkill`.

Pinned numbers confirmed against the PRD's worked examples: cost components `232 + 22 + 55 = 309` (estimated) and `232 + 22 + 40 = 294` (presorted actual); placement `25200` forecast re-divided to `630`; automation share `9987` bps → qualified, postage `3201800` after the 2¢/piece discount; lift `3333` bps; all three ledger identities held after every mutation (asserted in-script).

## Findings worth flagging

- **PRD §2.10 step 8 makes `POST /drops/{id}/presort-batches` require an *editable* plan (DRAFT/COSTED), while `POST /drops/{id}/presort` requires the plan *APPROVED*.** Batches must therefore be recorded before approval; a batch added after approval is correctly rejected `ERR_PLAN_NOT_EDITABLE`. Implemented literally as specified.
- Where the PRD is silent, its explicit per-transition enumerations were applied as exhaustive: line creation does not bump the drop's version, costing bumps only the plan, presort bumps only the drop, the profitability read bumps nothing, and measuring a cell bumps only that cell (siblings are re-scored without a version bump).
- Judgement calls recorded in code comments: `attribution_window_days` defaults to 90 (no default is declared anywhere); a manual `POST /contact-events` that crosses the fatigue threshold runs the line-suppression hops too, on the strength of §3.7's "each caused by the hop before it rather than by the mail action itself"; `void` checks drop state before line state (matching §2.10's code ordering).

Test blindness was honoured: only `SKILL.md`, `INSTRUCTION.md`, `SCAFFOLD.yaml` and `PRD.md` were read. `test_helpers/`, `test_suite/`, both `SCAFFOLD_*_DESIGN.yaml` files and every sibling task directory were never opened.

## Step 7: Run Tests and Iterate — 2026-09-05T02:20:00.000Z

All green. Final report below.

## Summary

**Result: clean 8-round parallel sweep — 251/251 passed in every round** (`results.1.json` … `results.8.json`, `total: 251, passed: 251, failed: 0, errors: 0`). Zero flaky tests; the union of failures across all 8 rounds is empty.

**Iterations run:** 3 (two full single-round diagnostic passes + the final mandated 8-round `setsid nohup` sweep). Starting point was 15 failures across 7 files.

**Tests deleted:** none. Every failure traced to either a PRD-inconsistent fixture precondition or a genuine implementation gap; no test asserted a scaffold-only rule and none needed weakening.

### Fixes applied to `test_suite/` and `test_helpers/` (setup state made PRD-faithful)

1. **Presort batches recorded against a non-editable plan** (11 failing tests). PRD §2.10 item 8 lists `POST /catalog-circulation/drops/{id}/presort-batches` among the structural mutations requiring the owning plan in `DRAFT` or `COSTED`, while §3.7's `/presort` demands `APPROVED`. Six fixtures created their batch *after* `approve_plan`, so setup died with `ERR_PLAN_NOT_EDITABLE` (409). The suite's own `test_34::TestCoverageCannotBeRepairedAfterApproval` quotes §2.10 verbatim and asserts exactly that refusal, confirming the reading. Batch creation moved to before `cost_plan` in:
   - `test_helpers/fixtures.py::setup_presorted_drop` (rebuilt on `setup_allocated_drop`; operator identities preserved so segregation of duties still holds)
   - `test_suite/test_08_mail_fatigue_cascade.py::_two_drop_world`
   - `test_suite/test_11_boundary_thresholds.py` — `_two_approved_drops_batched_either_side_of_the_share` and `_mailed_drop_with_a_test_and_a_control_cell`
   - `test_suite/test_12_cross_entity_state_guards.py::_presorted_drop_waiting_for_the_mail_stream`
   - `test_suite/test_21_production_replay_and_measurement_locks.py::_approved_drop_with_its_mail_stream_recorded`
   - `test_suite/test_50_…::_a_mailed_drop_beside_a_still_planned_one`, `test_suite/test_51_…::_two_drops_over_one_fatigue_primed_segment`

2. **`test_34_presort_coverage_equality.py::_three_approved_drops_covered_short_over_and_exactly`** (6 failing tests) — ran merge-purge *before* registering any housefile segment. Per PRD §3.3 the run sums `housefile_count` over the season's leaf segments, so `net_mailable_names` was 0 and the run took the mandated `PENDING → FAILED` branch, leaving `allocate` to answer `ERR_MERGE_PURGE_REQUIRED`. All three segments are now registered before `run_merge_purge`.

3. **`test_18_immutability_parents_and_hierarchy.py::test_a_self_parent_a_two_hop_loop_and_a_foreign_season_all_fail`** — asserted `top["version"] == 1` / `mid["version"] == 1`, contradicting PRD §2.2: version "increments by exactly 1 on every mutation — including mutations the row's owner did not request, such as a cascade reaching it from another aggregate." Registering `S_LEAF` legitimately rewrites `is_leaf` and `rollup_housefile_count` on both ancestors. The assertions now capture each version *before* the three rejected PATCHes and assert they are unchanged — which is the invariant the test actually exists to prove, and is strictly stronger about the rejection path.

### Fixes applied to `implementation/`

1. **`routes/segments.py::amend_segment`** — an amendment re-scored `rfm_score`/`segment_tier` but never re-derived the tier's default `contact_strategy`, so a segment dropping `BEST → CORE` kept `PREMIUM_FULL`. PRD §3.1 ("An explicit `contact_strategy` in the amendment overrides the tier default") only makes sense if the default is re-applied absent an explicit value, and §3.1/§3.8 name exactly one carve-out. Now: explicit value wins, else the re-scored tier's default is applied, except that a segment already in `SUPPRESS_ONLY` is never reverted by a re-score.

2. **`services/domain.py::plan_structural_recompute`** — only bumped the plan's `version` on the `COSTED → DRAFT` edge, so a cascade that credited budget back and rewrote the three roll-ups on an `APPROVED` plan left `version` frozen. Per PRD §2.2 the plan row is mutated and must advance. It now tracks whether `recompute_plan_budget`/`recompute_plan_rollup` actually changed a field and touches the plan when they did (the profitability read still calls the recomputes directly, so §3.5's "pure read" guarantee is untouched).

**Notes:** `worklog.md` was not created, read, or modified. No broad `pkill` was used — the two orphan servers left behind were killed by pid after verifying `/proc/<pid>/cwd` matched this task's implementation directory. Diagnosis was taken only from per-round `results.$i.json`, never `sweep.log`.

**Orchestrator independent verification:** all 8 `workspace/implementation/results.$i.json` files exist (each ~82 KB, written 02:20) and each reports `total 251, passed 251, failed 0, errors 0`. The clean sweep is real, not merely claimed. Step 8 will therefore run (2 `implementation/` fixes ⇒ skip condition not met).

## Step 8: Finalize PRD — 2026-09-05T02:28:22.370Z

`PRD_FINALIZED.md` written. Three inline edits, no new sections, no reflow of untouched prose.

## Size
- PRD.md: 463 lines / 14,478 words / 105,487 bytes
- PRD_FINALIZED.md: 463 lines / 14,708 words / 106,953 bytes
- Delta: **lines 0.0%**, words +1.6%, bytes +1.39%

## Changes
- **§3.1 (segment amendment)** — *revise* — added that an amendment naming no `contact_strategy` re-applies the re-scored tier's default afresh (overwriting whatever the segment carried, including a value a planner named at registration), with the one carve-out that a segment whose `contact_strategy` is already `SUPPRESS_ONLY` keeps it — `routes/segments.py:148-156`.
- **§3.6 (the `COSTED → DRAFT` invalidation edge paragraph)** — *revise* — added that all five listed structural mutations refresh `uncommitted_budget_cents` alongside the three roll-ups, that the plan's `version` advances by exactly one iff one of those four figures actually moved or the status edge fired (and not otherwise), and corrected the claim that an `UNDER_REVIEW`/`APPROVED` plan is "unaffected because it rejects those mutations": it rejects the four planner-driven ones, but a rental-cancel or mailing cascade does reach it, refreshes the four figures and advances its `version` without moving its `status` — `services/domain.py:326-338`, callers `routes/drops.py:156`, `routes/lines.py:139,252,286`, `services/domain.py:393,686`.
- **§3.7 (presort repricing)** — *revise* — added "and it does **not** advance the plan's `version` either" to the existing "does not change the plan's `status`" clause, so the new §3.6 rule cannot be read as extending to presort — `routes/drops.py:405` (`recompute_plan_rollup` with no `touch(plan)`).

Two `<step_7_diff>` fixture items produced **no** PRD edit: presort-batch creation against a non-editable plan is already uniquely determined by §2.10 item 8 (which names the endpoint) versus §3.7's `APPROVED` gate on `/presort`, matching `routes/drops.py:317-330` vs `:371-381`; the merge-purge `PENDING → FAILED` branch with no registered segments is already determined by §3.3. The `test_18` version fix is likewise already determined by §2.4's cascade-version rule.

## Per-edit pre-edit search log

**Edit 1 — §3.1**
- (a) Subject: every write of `contact_strategy`, and what re-scoring does to it.
- (b) Enumerated via `grep -rn "contact_strategy\|score_segment\|TIER_STRATEGY_DEFAULT"` over `implementation/`: writers = `routes/segments.py:107-110` (create: explicit wins else tier default), `routes/segments.py:149-156` (amend: the Step 7 site), `services/domain.py:153-156` (`recompute_fatigue` forces `SUPPRESS_ONLY` + `suppressed_at`; called from `routes/measure.py:84` contact-event log and `services/domain.py:621` mail-cascade hop two/three). Readers = `routes/lines.py:86` (line-create guard), `routes/lines.py:205` (allocate guard), `services/domain.py:478` (merge-purge `suppressed_names`), `routes/segments.py:175-185` (list filter). `TIER_STRATEGY_DEFAULT` table read at `services/calc.py:14-20`. Also read PRD §3.1 creation prose and §3.8's stickiness paragraph for consistency.
- (c) Adjustment: the impl's carve-out keys on the *current value* being `SUPPRESS_ONLY`, not on the suppression's origin, so the carve-out is written that way rather than reusing §3.1's narrower "fatigue-imposed" phrasing (left verbatim, since it is a true special case). No claim was made about `suppressed_at` on amendment — impl never clears it and PRD is silent, so that was left untouched rather than risk a false universal.

**Edit 2 — §3.6**
- (a) Subject: when the plan row itself is versioned/`updated_at`-refreshed as a consequence of a drop/line mutation or a cascade, and which recomputes run.
- (b) Enumerated via `grep -rn "plan_structural_recompute\|recompute_plan_budget\|recompute_plan_rollup"` plus full reads of `routes/plans.py`, `routes/lines.py`, `routes/drops.py`, `services/domain.py`, `db.py` (`apply_changes`/`touch` semantics at `db.py:52-67`): `plan_structural_recompute` callers = `routes/drops.py:156` (amend drop), `routes/lines.py:139` (create line), `:252` (allocate, after a direct `recompute_plan_budget` at `:238`), `:286` (void), `services/domain.py:393` (hop five), `:686` (rental-cancel step five). Plan-rollup recomputes that bypass it = `routes/drops.py:405` (presort, no touch), `routes/plans.py:106` (profitability read, no touch), `:247` (cost), `:302` (request-revision from `APPROVED`), `:360-361` (cancel) — the last three touch the plan as part of their own status transition. Traced reachability of an `APPROVED`/`UNDER_REVIEW` plan through both cascades (neither checks plan status; `cascade_suppress_segment_lines` filters on the *drop* being `PLANNED`).
- (c) Adjustments: (i) scoped the version rule to the five enumerated mutations and made it conditional on a figure actually moving or the status edge firing, since `apply_changes` + the `changed` guard means an unchanged recompute leaves the row alone; (ii) replaced "is likewise unaffected — but only because it rejects those mutations outright" with a split statement (planner-driven mutations refused; cascades still land) because the original is false for both cascades; (iii) said "advances its `version` when they move, without ever touching its `status`" rather than a general "any recompute of the roll-up advances the version", because presort and the profitability read both rewrite/refresh roll-ups without a bump; (iv) added Edit 3 to pin presort explicitly so the new sentence cannot be generalised onto it.

**Edit 3 — §3.7**
- (a) Subject: whether `POST /drops/{id}/presort` versions the owning plan.
- (b) Enumerated: `routes/drops.py:371-408` (`presort_drop` mutates only the drop and calls `domain.recompute_plan_rollup(plan)` at `:405`, then `touch(drop)` at `:407` — no `touch(plan)` anywhere on the path); compared against every other plan-rollup callsite listed above; checked §3.6's existing "pure read" sentence for `/profitability` so the two negative statements do not overlap or conflict.
- (c) Adjustment: dropped a first draft's explanatory rationale ("because presort mutates the drop, not the plan") — amending a drop is also a drop mutation yet *does* advance the plan's version, so the rationale would have been a false general principle; kept the bare factual clause.

**Orchestrator verification:** `PRD_FINALIZED.md` exists and is NOT byte-identical to `PRD.md` (105,487 → 106,953 bytes), consistent with the three reported inline edits.

## Step 9: Complete PRD — 2026-09-05T02:56:08.230Z

Run as **three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`** (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to copy, so no pass overwrote another's work). Partition: pass 1 = `app.py`/`response.py`/`middleware.py`/`validate.py`/`errors.py`/`util.py`/`db.py`/`routes/{config,segments,rentals}.py`; pass 2 = `routes/{plans,drops}.py` + `services/calc.py`; pass 3 = `routes/{lines,measure}.py` + `services/domain.py` plus every carry-over item passes 1–2 flagged out of lane.

### Pass 1 (infra + config/segments/rentals)
Source `PRD_FINALIZED.md` 463 lines / 106,953 chars → 463 lines / 114,643 chars (**+7,690**). **17 ambiguity-pins, 4 mismatch-revisions** (21 changed passages).
- §1 (prefix) — insert — ambiguity — a path matches with or without a trailing slash — `app.py:30`
- §2.1 — insert — ambiguity — absent/empty/unknown `X-User-Role` is `ERR_FORBIDDEN_ROLE` (403), never 401 — `middleware.py:48-52`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars A–Z/0–9; `api_request_timestamp` from the host clock, not the logical clock — `util.py:11,23-24`, `response.py:13`
- §2.2 — revise — **mismatch** — error envelope covers 5xx as well as 4xx — `app.py:56-61`
- §2.3 — revise+insert — **mismatch** + ambiguity — `has_more` is `offset + len(page) < total_count`; `offset` unbounded above; filter semantics (enum/int/bool rejection with `ERR_INVALID_REQUEST`, bool accepts true/false/1/0 case-insensitively, identifier filters not existence-checked, empty-string filter treated as omitted) — `response.py:48`, `validate.py:139-192`
- §2.3 — insert — ambiguity — every ordering takes insertion sequence as final tie-break after `created_at` — `db.py:71`, `config.py:111`, `segments.py:188,206`, `rentals.py:92`
- §2.4 — insert — ambiguity — store starts empty, nothing seeded — `db.py:17-32`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` from host real clock; `updated_at == created_at` at creation — `db.py:44-48,57`
- §2.8 — revise — **mismatch** — enforced list also includes segment amendment and `_online-orders/ingest`; only non-empty-string references enter the FK pass; `season_id` resolves before `parent_segment_id` — `segments.py:60-67,122-126`, `config.py:133-140`
- §2.10 step 4 — revise — **mismatch** — adds `PATCH /housefile-segments/{id}` and `POST /_online-orders/ingest`; ingest sweeps all elements' FKs before any element schema — `config.py:133-140`, `segments.py:122-126`
- §2.10 step 5 — insert — ambiguity — absent body = `{}`; unparseable/non-object body = `ERR_INVALID_REQUEST` 422; JSON `null` ≡ omitted (except amendment `parent_segment_id`); integers reject bools/numeric strings/floats; undeclared keys ignored; lenient ISO-8601 parse normalised to UTC, rendered with 3 fractional digits — `validate.py:20-99`, `util.py:60-91`, `app.py:40-44`
- §2.11 — insert — ambiguity — clock endpoint returns a bare `{current_utc}` object, accepts any instant including an earlier one, recomputes nothing — `config.py:116-122`
- §3.1 — insert — ambiguity — `segment_code` at least one character — `segments.py:74`
- §3.1 — insert — ambiguity — whole-forest refresh; another segment's `version` advances by exactly one only when `is_leaf`/`rollup_housefile_count` actually changed; new segment stays at `version` 1 — `db.py:60-67`, `services/domain.py:111-129`, `segments.py:112`
- §3.1 — insert — ambiguity — `parent_segment_id: null` detaches; `season_id`/`segment_code` in the payload ignored; a no-op amendment still bumps `version` — `segments.py:128-158`
- §3.2 — insert — ambiguity — `list_source_name` ≥1 char, not unique in any scope — `rentals.py:46`
- §3.2 — insert — ambiguity — `delivered_gross_names` required, may be 0 — `rentals.py:135`
- §3.2 — insert — ambiguity — `reason` stored nowhere but must be a string when supplied — `rentals.py:149`
- §3.8 — insert — ambiguity — `rule_code` at least one character — `config.py:72`
- §3.9 — insert — ambiguity — `orders` required array (empty allowed), elements must be objects, `external_order_id` ≥1 char and is the upsert key, `demand_cents` non-negative, three-sweep atomicity, `ingested_count` counts overwrites, ids echoed in request order — `config.py:125-172`
- §5 — insert — ambiguity — `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500 sit outside the table; unparseable JSON reports `ERR_INVALID_REQUEST` 422 rather than 400 — `app.py:40-61`

Verified already correct (no change): the 47-entry error-id → status map matches `errors.py` exactly; all 11 rate-card defaults/bounds; §4 role lists for all 18 endpoints in the partition; the four ladder positions those routes exercise.

### Pass 2 (plans + drops + calc)
114,643 → 118,456 chars (**+3,786**), 463 lines unchanged. **14 ambiguity-pins, 2 mismatch-revisions.**
- §3.3 — revise — **mismatch** — `input_rental_ids` required (omitted/`null`/non-array → 422); a string element goes to the step-4 FK pass *without* an emptiness check, so an empty-string element reports `ERR_RENTAL_NOT_FOUND`, contradicting §2.8's empty-string rule; `expected_plan_version` pinned non-negative — `plans.py:122-138`
- §3.3 — insert — **mismatch** — each input rental's existence settles at ladder step 4, but the *same-season* half is tested only after the editability and version guards, so a foreign-season rental on a stale plan reports `ERR_STALE_PLAN_VERSION` — `plans.py:141-151`
- §3.3 — insert — ambiguity — `processing_order` and `housefile_leaf_segment_count` are persisted on the FAILED branch too — `plans.py:162-187`
- §3.6 — insert — ambiguity — `plan_code` ≥1 char — `plans.py:52`
- §3.6 — insert — ambiguity — the plan row is the only row costing advances: repriced drops and recomputed lines get figures rewritten with no `updated_at`/`version` movement; costing does not refresh `committed_cost_cents`/`uncommitted_budget_cents` — `plans.py:241-250`, `domain.py:274-286`
- §3.6 — insert — ambiguity — the contribution guard reads stored `planned_contribution_cents` as-is; approval recomputes no roll-up first — `plans.py:317`
- §3.6 — insert — ambiguity — each reverted `PRESORTED` drop's `ALLOCATED` lines get profitability re-derived without a line version bump; roll-up recompute only on the `APPROVED` back-edge; neither edge refreshes the budget ledger — `plans.py:299-304`
- §3.6 — insert — ambiguity — a drop cancelled out of `PRESORTED` keeps `postage_total_cents`, `automation_share_bps`, `automation_qualified`, `cost_basis` untouched and gets no quantity/cost re-derivation — `plans.py:343-350`
- §3.6 — insert — ambiguity — the profitability read writes its three refreshed figures through to the stored row; `updated_at` does not move; budget fields untouched — `plans.py:101-107`
- §3.4 — insert — ambiguity — the drop's `version` and the plan's ledger refresh / `COSTED → DRAFT` edge run on *every* accepted PATCH, including a no-op — `drops.py:143-157`
- §3.4 — revise — ambiguity — `product_sku`/`product_name` ≥1 char, `demand_per_sq_inch_cents` and `sq_in_offset` non-negative, `page_number` carries no schema bound — `drops.py:198-206,239`
- §3.4 — insert — ambiguity — a plan's drops are filterable by `production_status` and `measurement_status` — `drops.py:172-180`
- §3.7 — insert — ambiguity — recording a batch does not move the parent drop's `version`; batches filterable by `declared_tier`/`effective_tier` — `drops.py:337-351,359-365`
- §3.7 — insert — ambiguity — a `planned_quantity` of zero is rejected with `ERR_INVALID_DROP_STATE` — `drops.py:382-383`
- §3.7 — insert — ambiguity — the per-line recompute also rewrites `gross_margin_cents` and moves no line's `updated_at`/`version` — `drops.py:403`, `domain.py:274-286`
- §3.5 — insert — ambiguity — a `unit_cost_cents` of zero imposes no budget cap rather than dividing by zero — `calc.py:209-213`

Verified clean: all 15 `calc.py` kernels already match PRD prose exactly (RFM band edges and tier boundaries, coop lift bands, rental unit cost, rebate bands, single-rounding printing/paper formulas confirmed against §2.6's 94-page worked example 232.18/21.62/51.6 → 306, position multipliers, forecast/productivity re-division, tier minimums and rates, weight surcharge, automation share floor, forecast orders, gross margin, holdout floor, channel weights, decay bands, response rate and lift including half-away-from-zero on negative lift, and the 1000-name / 1500-bps significance constants).

### Pass 3 (lines + measure + domain + all carry-overs)
118,456 → **126,488 chars** (**+8,032**), 463 lines unchanged. **19 ambiguity-pins, 7 mismatch-revisions** (24 Edit calls).
- §2.3 — revise — mismatch — empty-string filter indulgence re-scoped to identifier-valued filters only; enum/int/bool reject `""` with `ERR_INVALID_REQUEST` — `validate.py:152-158,161-165,168-188`
- §2.4 — revise — mismatch — "every mutated entity bumps `version`" now excludes rows whose derived figures a recompute rewrites in place — `domain.py:274-286`
- §2.9 — insert — ambiguity — `expected_drop_version` may not be negative — `measure.py:222`
- §3.2 step two — revise — mismatch — a STALE recompute drops the rental from the *computation* and from `processing_order`, but `input_rental_ids` keeps it; no surviving rental's `net_names_delivered` is rewritten — `domain.py:648-660`
- §3.2 step five — insert — ambiguity — presorted drop with `planned_quantity` 0 takes `postage_cents_per_book` 0; surviving `ALLOCATED` lines re-derived in place without a version bump; voided lines' and affected drops' versions each +1 — `domain.py:209-213,679-684`
- §3.2 — revise — mismatch — the unwind spares no line for *any* drop production state (`PRESORTED`/`MAILED`/`DELIVERED`/`CANCELLED`), not just presorted — `domain.py:665-676`
- §3.2 — insert — mismatch — `cost_basis` preservation has one exception: a drop whose batch rows were deleted falls back to `ESTIMATED_POSTAGE` — `domain.py:208-217`
- §3.3 — revise — mismatch — same STALE-recompute correction; `housefile_leaf_segment_count` *is* re-derived — `domain.py:652-659`
- §3.5 — insert — ambiguity — line creation does not move the drop's `updated_at`/`version` — `lines.py:138`
- §3.5 — insert — ambiguity — the provisional freeze is detected by the stored value being non-zero, so a provisional of 0 is re-struck each allocate — `lines.py:224`
- §3.5 — insert — ambiguity — an unfunded walked line keeps its `allocation_rank`/`unit_cost_cents` and still takes one version bump — `domain.py:576-580`
- §3.5 — revise — ambiguity — the budget-exhausted guard reads only the top line and is skipped entirely when there is no `PROPOSED` line or its unit cost is 0 — `lines.py:229-232`
- §3.5 — revise — ambiguity — allocate's suppression/netting guards inspect only `PROPOSED` lines — `lines.py:197-213`
- §3.5 — revise — ambiguity — post-waterfall cost re-derived at the drop's *current* `cost_basis`; the committed view covers previously-allocated lines too and re-resolves `effective_response_bps` from the live audience row — `lines.py:239-247`, `domain.py:248-257`
- §3.5 — revise — ambiguity — exact version accounting (walked lines exactly once; previously-`ALLOCATED` lines once only if their figures moved); response carries the drop — `lines.py:243-254`
- §3.5 — revise — ambiguity — void's `reason` recorded nowhere, must be a string — `lines.py:267`
- §3.5 — insert — ambiguity — void leaves `allocation_rank`/`unit_cost_cents`/`effective_response_bps`/`gross_forecast_demand_cents` intact and re-derives sibling `ALLOCATED` lines' profitability in place without a version bump — `domain.py:346-355`, `lines.py:284`
- §3.7 hop two — insert — ambiguity — each affected segment's `version` +1 regardless of score movement — `domain.py:140-158`
- §3.7 hop five — insert — ambiguity — surviving `ALLOCATED` lines' profitability moves at the drop's current basis with no version bump — `domain.py:388-391`
- §3.8 — insert — ambiguity — the cap window is inclusive at exactly `window_days`; the count is taken over stored events only — `domain.py:449-461`
- §3.8 — insert — ambiguity — `suppressed_at` is re-stamped on every recompute that leaves the score at/above threshold, and the retirement hops re-run — `domain.py:153-156`, `measure.py:84-85`
- §3.9 — revise — ambiguity — re-scored sibling cells' figures are rewritten without their own `updated_at`/`version` moving — `measure.py:201-206`
- §3.9 — insert — ambiguity — `attribution_window_days` defaults to 90 — `measure.py:22,227`
- §3.9 — insert — ambiguity — a `MAIL` contact with no `drop_id` can win last touch and the credit lands on no drop; fractional credits accumulate by drop, one share per contact — `domain.py:786-810`
- §3.9 — revise — mismatch — the cents-conservation sentence is hedged for credits falling to a null `drop_id` — `domain.py:794,801`
- §3.9 — insert — ambiguity — the ≥1-cent floor is a real threshold; a floored 0 share is neither counted nor summed — `domain.py:812-813`

**Carry-over dispositions (all six closed):** (1) §2.3 vs `validate.py:152-158` empty-string enum filter — fixed by re-scoping to identifier-valued filters. (2) `lines.py:231` zero-unit-cost budget guard — fixed. (3) `lines.py:224` provisional-0 re-strike — fixed. (4) `lines.py:249` double-touch asymmetry — fixed; investigation showed the net effect is exactly one bump per line per allocate (walked → unconditional; previously-allocated → only if figures moved), which is what the PRD now states. (5) `domain.py:388-391` hop five — fixed. (6) `domain.py:812-813` ≥1-cent threshold — strengthened (§3.9 already said "at least one cent", so the fractional-share and zero-demand consequences were added).

### Totals and final verification
`PRD_FINALIZED.md` 463 lines / 106,953 chars → `PRD_COMPLETED.md` 463 lines / **126,488 chars** (**+19,535 chars, +18.3%**; line count unchanged because every edit was an in-paragraph insert or revision). Aggregate across the three passes: **50 ambiguity-pins, 13 mismatch-revisions**.

Orchestrator verification: `PRD_COMPLETED.md` exists, is NOT byte-identical to `PRD_FINALIZED.md` (so the scan genuinely ran), has all 5 top-level sections, 55 endpoint rows in §4, 47 error rows in §5, and ends at a real boundary (`| \`ERR_PLAN_CONTRIBUTION_NEGATIVE\` | 422 |`). No stray worklog files anywhere in the task tree; `__pycache__` directories removed. Step 9 changed documentation only — `implementation/`, `test_suite/` and `test_helpers/` are byte-for-byte as they stood at the clean 8-round sweep, so the 251/251 × 8 result still holds.

**Pipeline complete through Step 9.**
