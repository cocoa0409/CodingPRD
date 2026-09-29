## Step 1: Create task directory — 2026-09-05T02:07:51.443368505Z

Created tasks/task_2819_office_coffee_service_equipment_program/ and its workspace/ subdirectory. Index 2819 pre-assigned by the orchestrating command; no auto-allocation performed.


## Step 2: Generate scaffold — 2026-09-05T04:14:31.166Z

All three scaffold artifacts for task 2819 are complete and lint clean.

## Output files
`/home/ubuntu/github/CodingPRD/tasks/task_2819_office_coffee_service_equipment_program/`
- `SCAFFOLD.yaml` — 2860 lines (top-level keys: scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles; neither forbidden design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2210 lines, single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4147 lines, single top-level key `scaffold_corner_design`

The temporary `.scratch/` dir was removed; `worklog.md` was not touched.

## Counts
- §1.0–1.7: 13 entities, 60 endpoints, 10 state machines (parallel shape), 12 calculations, 51 validations (priority 1–51), 62 errors, 5 roles (peer_roles; RouteTechnician entity_backed:Route, CustomerContact entity_backed:Account), 2 concurrency rules, `api_prefix: /ocs`, envelope `$.data`.
- §1.8: 9 rules — dual_variant_calc(2), combinatorial_formula(3), non_linear_state_machine(3), transitive_cascade(2), priority_pair_validation_conflict(3), boundary_precision_check(3), cross_entity_state_dependency(3), resource_temporal_overlap(2), compensating_invariant(2) — **23 instances, all 23 non-stub** (full test_recipe each).
- §1.9: **9 sections, 72 instances, 48 non-stub / 24 stubs**: entities 11 (1 stub), state_machines 13 (6), calculations 12 (6), validations 13 (3), endpoints 5 (2), errors 8 (2), rbac 3 (0), cross_cutting_complexity_layers 5 (3), consistency_model 2 (1).

## Coverage notes
- All nine claim-extraction-guide sections are represented; claim_types are drawn from the guide's row labels (errors has no row table, so its instances use `error_triggerable`; rbac uses the `peer_roles` role-model row).
- **Every one of the 62 error codes is referenced by at least one §1.8 or §1.9 instance** (verified programmatically; zero unreferenced). The 13 distinct 404 codes get a dedicated per-path-segment instance, plus a body-FK instance that pins priority 5 > 6 > 15 ordering.
- Both `concurrency_rules` entries have their own OCC instance (stale `expected_site_version` → 412, stale `expected_account_version` → 412, each with a successful re-read retry); the account-OCC instance also asserts the completion-time price snapshot is reused at invoice time.
- All 24 stubs cite a real §1.8 instance name (verified against the union of §1.8 names), carry `claim_type` + `grounds` + `excluded_because{difficulty_instance, rationale}`, and carry no `test_recipe`.
- Every numeric assertion was pre-computed as a literal (e.g. 324/29/59/24 re-plan chain, 42.5 escalation score, 9000+2500=11500 invoice, 1200 bps adjustment and the 11200 factor, 32/180 modeled draws clamped by `min()`), and hazards were designed around: REPAIR instead of PREVENTIVE work orders so ERR_DESCALE_OVERDUE can't mask a target error, `/complete` (not `POST /ocs/service-visits`) used to reach ERR_SITE_NOT_SERVICEABLE since priority 11 doesn't apply to `/complete`, and headcounts kept inside the catalogued brewer's 30-cup capacity except in the instance that deliberately triggers ERR_NO_MODEL_FITS_HEADCOUNT.

## Lint
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(Coverage line from the same run: §1.5 endpoints 60, §1.1 entities 13, §1.8 instances 23, §1.9 instances 48, calls scanned 1142.)

**Orchestrator note:** the scaffold generator copied the difficulty directive line ("Generate task harder than expert level!") into SCAFFOLD.yaml's `scenario:` key, from which it would reach PRD.md. The orchestrator stripped that single line from `scenario:` immediately after this step; a repo-wide grep for the phrase under the task dir now returns nothing. No other scaffold content was altered.

## Step 3: Copy shared files — 2026-09-05T04:14:34.900083683Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T04:30:12.268Z

The PRD is complete and verified.

**Output:** `workspace/PRD.md` — **510 lines**, ending on the final row of the §5 two-column error table (a clean section boundary; not mid-sentence, not mid-table).

**Section list**
- `# Office Coffee Service & Equipment Program API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Actors, Identity Headers and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Timestamps and Revision Counters · 2.5 The Logical Clock and the Green Coffee Market Quote · 2.6 Money, Quantities and Rounding Discipline · 2.7 Stale-Read Protection on Placement and Invoice Creation · 2.8 The Request Admission Ladder · 2.9 Reference Resolution: Path First, Then Body · 2.10 Parallel State Dimensions and Cascade Discipline
- `## 3. Business Logic & Workflows` — 3.1 Account Onboarding, Program Posture and Cancellation · 3.2 Break-Room Sites, Demand Modelling and Par Planning · 3.3 Fleet Assets, Brewer Placement and Asset Recovery · 3.4 Route Capacity and Replenishment Scheduling · 3.5 Visit Completion, the Shelf Ledger and the Escalation Chain · 3.6 Brewer Maintenance, Descale Discipline and Loaner Circulation · 3.7 Minimum-Purchase Compliance and Equipment Program Charges · 3.8 Invoice Assembly, Issuance and Credits · 3.9 Green Coffee Repricing and the Negotiation Cycle
- `## 4. Endpoint Definitions` (60-row, 4-column table)
- `## 5. Error Code Catalogue` (62-row, 2-column table)

**Coverage (documented / scaffold total):** Endpoints 60/60 · Validations (priority-ordered ladder, §2.8) 51/51 · Error codes 62/62 · Calculations 15/15 · State machines / transitions 10/10, 54/54 · Roles 5/5 · Entities 13/13 · Concurrency rules 2/2.

**Hard Contracts — all PASS (re-verified after final edits)**
- **Contract 1 (Field-Name Coverage):** `entities[].fields: 118 required, 118 present, 0 missing` · `request_body: 70/70` · `query_params: 33/33` · `path_params: 13/13` · `nested/derived: 19/19` · `errors[].id: 62/62` · `roles[].name: 5/5`
- **Contract 2 (Rule Coverage):** every validation, error trigger, calculation formula, transition and side effect traced. One genuine gap found and fixed: Site `ESCALATED -> SUSPENDED` also recomputes `Account.escalated_site_count`, now stated in §3.1's cancellation cascade.
- **Contract 3 (§3 Path Purity):** 955 backtick tokens scanned in §3 — 0 slash-leading paths, 0 bare HTTP methods, 0 method+path pairs, 0 raw `/ocs` occurrences.

Supporting checks: 79/79 enum-and-state values present; 46/46 constant values present in prose; all 62 errors named in §2/§3 before the catalogue; no forbidden OCC framing ("simultaneously", "race", "first-writer-wins"); no fuzzy hedges (three " around " hits inspected — all "around the cycle", not approximations).

**Three scaffold ambiguities resolved conservatively** (flagged here, not silently): visit-void's "no non-VOID invoice covers the window" precondition has no `error_id` in the scaffold, attributed to `ERR_VISIT_STATE_INVALID` / 409 and stated explicitly; validations 19 vs 20 on `/respond` made jointly satisfiable (`ACCEPTED`/`DISPUTED` -> `ERR_ADJUSTMENT_STATE_INVALID`, `DEFERRED` -> `ERR_ADJUSTMENT_DEFERRED`); `green_price_factor_bps` documented in the absolute form `:= 10000 + adjustment_pct_bps` (entity field, state-machine side effect and endpoint side effect all agree against one trailing `+=` comment). Note also that the task brief said 12 calculations — the scaffold actually holds 15, and all 15 are documented.

**Orchestrator verification (truncation guard):** independently confirmed 510 lines, `## `-section count 5, 60 endpoint data rows in §4, 62 `ERR_` rows in §5, and that the file's last line is a complete table row. No regeneration needed. Grep for the difficulty directive and for any `scaffold_difficulty`/`scaffold_corner`/`test_recipe` token in PRD.md returns nothing.

## Step 5: Generate unit tests — 2026-09-05T06:16:00.000Z

Done. The suite is complete and every gate passes.

## Files written (task root — nothing under `workspace/`)

`test_helpers/`: `__init__.py` 39 · `api_client.py` 311 · `api_errors.py` 159 · `assertions.py` 328 · `constants.py` 160 · `factories.py` 294 · `fixtures.py` 930 · `test_users.py` 70 · `types.py` 413

`test_suite/` (lines / tests / file): 57 / – / `conftest.py` · 284 / 4 / `test_01_demand_planning_variants.py` · 251 / 4 / `test_02_equipment_program_charges.py` · 369 / 6 / `test_03_green_index_negotiation.py` · 301 / 4 / `test_04_invoice_assembly_arithmetic.py` · 251 / 4 / `test_05_route_capacity_and_windows.py` · 493 / 6 / `test_06_shelf_ledger_and_escalation.py` · 620 / 8 / `test_07_maintenance_and_loaners.py` · 551 / 6 / `test_08_cancellation_and_recovery.py` · 329 / 4 / `test_09_admission_ladder_precedence.py` · 639 / 10 / `test_10_entity_contracts.py` · 631 / 7 / `test_11_initial_states_and_transitions.py` · 542 / 6 / `test_12_calculation_kernels.py` · 947 / 10 / `test_13_validation_families.py` · 281 / 3 / `test_14_endpoint_surface.py` · 387 / 3 / `test_15_role_boundaries.py` · 582 / 6 / `test_16_error_surface.py` · 312 / 3 / `test_17_concurrency_and_visibility.py`

10,531 lines total across both directories. `__pycache__` removed; scratch confined to `.scratch/`.

## Coverage
- **94 tests**, every one carrying exactly one trailing `Design:` line (verified by AST: tests-per-file == tags-per-file, and no test has 0 or 2 tags).
- **Queue A (difficulty): 23/23 instances translated, 46 tests** — every instance at exactly 2, none below the >=2 floor.
- **Queue B (corner): 48/48 non-stub instances translated, 48 tests** — every instance at >=1. The 24 stub instances (`excluded_because`, no `test_recipe`) correctly produced no test.
- **Instances SKIPPED: 0.** Every live instance survived the PRD-first two-condition filter, so there are no gaps-left-as-gaps.
- Tag audit against both yamls: 0 unknown, 0 malformed, 0 dual-tagged.

## Verification passes
- `py_compile` + `pyflakes` clean on all 17 test modules (the only pyflakes output is the intentional re-export block in `test_helpers/__init__.py`).
- Every test module was actually **imported** in-process, which proves all 200+ helper/factory names resolve; a static sweep also confirmed every `api_client.*` and `f.*` attribute used anywhere exists.
- **PRD-citation pass:** all 244 docstring quotes checked verbatim against `workspace/PRD.md` after whitespace normalisation — 0 mismatches. Four were repaired during this pass:
  - `test_07` sanitation-hold quote began with an elision -> replaced with the full 3.6 sentence.
  - `test_08` cancellation quote elided hop two mid-sentence -> restored the contiguous hop-one-through-hop-three run.
  - `test_08` depreciation quote elided the residual-floor clause -> restored the contiguous run.
  - `test_13` transition-field quote was a paraphrase that does not exist in the PRD -> replaced with the real 3.6 sentence ("The two conditionally-required transition fields are checked **after** the descale gate and after the cycle cap. ...").
- **Scaffold-citation pass:** no occurrence of "scaffold" in any generated file. The eight section references all sit inside verbatim PRD quotations (the PRD cross-references its own sections), never in the generator's own prose.

## Design-index defects found (test asserts the PRD, not the index)
1. `corner_an_invoice_period_with_no_activity_is_rejected_rather_than_written_empty` asserts `allied_category_count == 1` for a COFFEE-only invoice. 3.8 step 3 counts distinct categories **other than** COFFEE, so it is 0. Test asserts 0.
2. Same instance asserts a rejected plan leaves `forecast_cups_per_week == null` and zero par rows. PRD gives the birth value as **0**, not null, and never states that a rejected planning request rolls back partial writes. The test asserts only `recommended_model_id is None`, `brew_style is None` and an unchanged `version`; the zero-par-rows assertion is kept only for the TRAILING_USAGE room, where `ERR_NO_TRAILING_USAGE` provably precedes par computation.
3. `corner_placement_creation_rejects_a_stale_site_version_and_succeeds_after_a_re_read` names the enum value "MEETING"; the real value is `MEETING_MINIMUM`.

## PRD gaps
None blocking. Two spots required care rather than a skip: RENT-line proration in the two OCC/visibility invoices resolves to 0 days (`max(period_start, placed_at)` and `min(period_end, now)` land on the same date), so `line_count == 2` is derivable rather than assumed; and the `loaner_asset_id` 404 is the shared `ERR_ASSET_NOT_FOUND` per 2.9, not a dedicated loaner code.

**Orchestrator note (process deviation, recorded for honesty):** the skill requires Steps 5 and 6 to be launched concurrently in a single assistant message, which also gives the implementation generator *physical* isolation from `test_suite/` (the directory does not exist when it starts). The orchestrator mistakenly launched Step 5 alone and waited for it, so `test_helpers/` and `test_suite/` were already on disk before Step 6 began. Mitigation applied before spawning Step 6: both directories were moved out of the repository entirely (to `/home/ubuntu/.prd_bench_hold_2819/`), leaving the task root with no test artifacts, and were moved back only after Step 6 returned. The Step 6 subagent was additionally instructed in writing not to read `workspace/implementation/`'s sibling test dirs or any test artifact. Physical isolation was therefore preserved in substance, at the cost of the throughput the concurrent launch would have given.

## Step 6: Generate implementation — 2026-09-05T07:00:53.191Z

The implementation is complete, verified, and the task directory is clean (scratch dir and all `__pycache__` removed; nothing written outside `workspace/implementation/`).

## Modules — `workspace/implementation/`

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | reads `$PORT` (default 10000), guarded `pip install`, `exec python3 app.py` — foreground, binds 0.0.0.0 |
| `requirements.txt` | 1 | `flask==3.1.3` |
| `app.py` | 69 | app factory, 11 blueprints, `ApiError`/404/405/400/500 handlers |
| `timeutil.py` | 75 | instant/date parsing, 3-digit-fraction `Z` formatting, weekday, minute alignment |
| `numbers_util.py` | 51 | `Fraction` helpers, round-half-up / ceil / floor, bps, micros->cents |
| `errors.py` | 79 | all 62 error ids -> HTTP status, `ApiError` |
| `store.py` | 97 | in-memory dicts, logical clock, green index, `insert`/`snapshot`/`touch`/`bump` |
| `envelope.py` | 46 | meta/response_type/data envelope, pagination meta |
| `shape.py` | 186 | rung-4 request-shape validation (all failures -> `ERR_VALIDATION`) |
| `authz.py` | 75 | rungs 1-3, route-owner and account-contact checks |
| `serializers.py` | 152 | explicit per-entity field tuples |
| `lookup.py` | 104 | 13 path/FK resolvers, listing + equality filters |
| `calc.py` | 467 | all 15 calculations in exact rational arithmetic |
| `cascade.py` | 177 | four-hop replenishment and cancellation chains, lazy fleet promotions |
| `routes/catalog.py` | 202 | routes, models, assets, products, day-load |
| `routes/accounts.py` | 85 | accounts, cancel, recompute-allied-attachment |
| `routes/sites.py` | 198 | sites, size-and-plan, evaluate-service-posture |
| `routes/parlevels.py` | 80 | manual par lines + reads |
| `routes/placements.py` | 165 | placement, evaluate-compliance, retrieve |
| `routes/visits.py` | 354 | schedule, reschedule, lines, complete, void |
| `routes/workorders.py` | 250 | advance, loaner-swap, loaner-return |
| `routes/invoices.py` | 432 | staged-mutation assembly, issue, credit |
| `routes/invoicelines.py` | 34 | line list/read |
| `routes/adjustments.py` | 146 | propose, respond, revise |
| `routes/testing.py` | 31 | clock and green-index setters |
| `routes/__init__.py` | 0 | package marker |

**3566 lines total. 60/60 endpoints implemented** (verified by diffing Flask's `url_map` against SCAFFOLD's `endpoints:` block — no missing, no extra), 62/62 error codes with matching HTTP statuses, 13 entities, in-memory dicts only, zero seeding (asserted against a freshly booted server).

## Verification
Six smoke suites, 159 assertions, all passing on a freshly booted server chain (server killed by exact port-listener PID afterwards; no broad pkill was ever used). Coverage included hand-computed sizing math, invoice totals/tiers/freight/credits, the full work-order + loaner lifecycle, the escalation -> AT_RISK -> adjustment-deferral chain, void unwinding all four hops back, and the cancellation -> closure cascade.

One environment note worth recording: a server launched as `bash start.sh &` does **not** always leave `$!` as the listening PID, so the generator switched to resolving the PID from the port via `ss -ltnp` before killing.

## Genuinely ambiguous PRD passages and the readings chosen
1. **`ERR_NO_BILLABLE_LINES` scope** (3.8 step 8) — keyed on the four *billable* line types (`PRODUCT`, `RENT`, `SHORTFALL`, `UNRETURNED_ASSET`). Keying it on all rows would make the error unreachable, since a sub-50000-cent invoice always gets a `FREIGHT` line.
2. **Descale predicate boundary** — SCAFFOLD uses non-strict `<=` for the 3.5 escalation term but strict `>` for the 3.6 PREVENTIVE-resolve gate. Implemented as two predicates: an asset exactly at its interval scores 15 points yet can still sign off.
3. **`returned_on` before `loaner_out_date`** — no dedicated code exists, so `ERR_VALIDATION` (400).
4. **Work order on an asset with no ACTIVE placement** — `ERR_ASSET_NOT_AVAILABLE` (409), and this necessarily precedes route-ownership since `site_id` is only reachable through the placement.
5. **Loaner-swap on a RESOLVED work order** — `ERR_WORK_ORDER_STATE_INVALID`.
6. **Late loaner return** — the OUT->OVERDUE promotion and the RETURNED transition are applied under a single version bump.
7. **`FREIGHT` line `site_id`** — null (it is an invoice-level charge); a `CREDIT` line inherits its target's `site_id`.
8. **Issuance and account posture** — 3.8 says only *not `CLOSED`*, so a `CANCELLATION_PENDING` account still reaches the invoice's own state gate; once `CLOSED`, rung 11 outranks rung 18.
9. **Enum-valued query filters** — matched by exact equality with no enum validation (an unknown value yields an empty page, not a 400).
10. **Unknown `product_id` inside `delivered_lines`** — `ERR_DELIVERED_EXCEEDS_REQUESTED` (422).
11. **Negative `days_active` in rent proration** — implemented literally as `min(30, days_active)` with no floor at 0.
12. **`api_request_timestamp`** — renders the logical clock, never wall-clock.
13. **Reschedule** — excludes the visit itself from both collision and day-capacity computations.
14. **`requested_units` / `index_micros`** — no declared range, so no bound is enforced.

**Orchestrator note:** after Step 6 returned, `test_helpers/` and `test_suite/` were moved back from `/home/ubuntu/.prd_bench_hold_2819/` to the task root and the hold directory was removed. Layout verified: 9 files in `test_helpers/`, 18 in `test_suite/`, 15 entries in `workspace/implementation/`.

## Step 7: Run tests and iterate — 2026-09-05T07:43:21.299Z

All 8 rounds of a single sweep are green: **94/94 in every round.**

## Summary

**Iterations run:** 4 sweeps (8 concurrent rounds each, `setsid nohup`, per-test-server isolation).
Progression: 52/94 -> 92/94 -> 93/94 -> **94/94** in all 8 rounds.

**Tests deleted:** none. No failure traced to PRD silence or non-unique derivability — every one was either a test artifact contradicting a verbatim PRD sentence or a real implementation gap.

**Fixes applied to `test_helpers/`**

| File | What | Why |
|---|---|---|
| `test_helpers/api_client.py` | New `ApiClient._request` override + `_canonical_instants()`: drops a zero-millisecond suffix (`...T09:00:00.000Z` -> `...T09:00:00Z`) from response instants, **excluding** `created_at`, `updated_at`, `api_request_timestamp` | PRD 2.4/2.2 pin "exactly three fractional-second digits" on those three keys **only**; every other instant (`window_start`, `last_service_at`, `price_protection_until`, `parts_eta`, `reconditioning_until`, `loaner_*`, `issued_at`, `completed_at`, ...) is unspecified, so the two renderings are the same instant. This alone was 41 of the 42 failures — every one aborted on its first instant comparison, masking everything after it. |

**Fixes applied to `test_suite/`** (all three: test contradicted a verbatim PRD sentence)

| File | Test | Fix |
|---|---|---|
| `test_15_role_boundaries.py` | `test_an_entity_backed_identity_is_checked_for_presence_resolution_then_ownership` | expected `201` from `POST /service-visits/{id}/lines` -> `200`. PRD "Status codes": "Appending a requested line to a service visit is **not** a resource creation — it mutates the visit's `lines` array and returns the visit with 200 OK." |
| `test_13_validation_families.py` | `test_the_price_protection_window_blocks_a_reproposal_until_it_lapses` | boundary was asserted inclusively (refused *at* `price_protection_until`, accepted one second later). PRD: "No new adjustment may be proposed while `price_protection_until` is still **ahead of** the current instant" — strict. Now: refused at `07:59:59Z`, accepted at `08:00:00Z`; the `total_count == 2` invariant is preserved. |
| `test_01_demand_planning_variants.py` | `test_replan_under_the_other_variant_rewrites_only_par_and_reorder` | (a) `stock_status == "IN_STOCK"` for on_hand 20 vs reorder 26 -> `"LOW"` per PRD "`LOW` when `on_hand_units` is above 0 and at or below `reorder_point_units`" (added the explicit `reorder_point_units == 26` anchor). (b) `version == planned_version + 1` -> measured against the version read immediately before the PATCH, since the intervening completed stop legitimately mutated the site's own `escalation_score` (cascade hop two + 2.4 "increments by exactly 1 on each mutation"). |

**Fixes applied to `implementation/`**

| File | Function | Why |
|---|---|---|
| `workspace/implementation/routes/sites.py` | `_write_forecast_par_line` | Re-derives `stock_status` after a replan rewrites `reorder_point_units`. PRD: "`stock_status` is always derived, never supplied: ... `LOW` when `on_hand_units` is above 0 and at or below `reorder_point_units`, and `IN_STOCK` otherwise." Planning's "leaves every other member alone" protects the *stored* ledger members (source, on_hand, both cumulative counters, `last_service_at`); a derived field left stale against a new reorder point breaks the invariant the suite checks on every par-line read (`assert_stock_status_derived`). No new endpoint, field, header or seeded state was introduced; storage remains in-memory only. |

**Final per-round counts:** rounds 1-8 all `passed 94 / total 94`, `failed 0`, `errors 0`.

**Artifacts on disk:** all 8 files present and non-empty valid JSON at `workspace/implementation/results.{1..8}.json` (~28.7 KB each, 07:35).

`worklog.md` was not read or written by the subagent. No sibling task directory was touched. No broad `pkill` was ever issued.

**Orchestrator independent verification of Step 7 (not taken on faith):** parsed all 8 `results.$i.json` directly — every round reports `passed 94 / failed 0 / total 94 / errors 0`. The 8 files have 8 distinct md5sums and differing per-test `duration_seconds` (e.g. 1.873 s vs 1.880 s on the first test), so they are 8 real runs, not one file copied. Independent audit of the suite: 94 `def test_` functions and exactly 94 `Design:` tags (confirming zero deletions and one tag per test); zero occurrences of `pytest.mark.skip` / `pytest.mark.xfail` in either test directory; and zero SQLite / shelve / pickle / `json.dump(` / file-write calls anywhere in `implementation/`, confirming in-memory-only storage.

## Step 8: Finalize PRD — 2026-09-05T07:47:44.115Z

Step 8 ran (not skipped): Step 7 applied 1 `implementation/` fix, so the skip condition (0 deletions, 0 test_suite fixes, 0 test_helpers fixes, 0 implementation fixes) did not hold.

Done. Two edits, both single-line in-place revisions.

## Counts
- `PRD.md`: 510 lines / 107,616 bytes
- `PRD_FINALIZED.md`: 510 lines / 109,026 bytes
- Line delta: **0%** (both 510); byte delta **+1.31%**

## Changes
- **2.4 (Resource Identity, Timestamps and Revision Counters), line 88 — revise** — Pinned the rendering of *every* instant-valued resource member (not just `created_at`/`updated_at`) to exactly three fractional-second digits + `Z`, regardless of the precision the client supplied; added the readback example, the null case, an explicit note that this is rendering-only (comparisons use the instant as supplied), and an explicit carve-out for the date-valued day-load `service_date`. — `implementation/serializers.py:80-84` (`_value` -> `fmt_instant` for every `datetime`), `implementation/timeutil.py:46-54` (`fmt_instant`)
- **3.2 (Par lines), line 188 — revise** — Planning's rewrite of an existing `FORECAST` par line now also re-derives `stock_status` against the rewritten `reorder_point_units`; the "leaves every other member alone" clause was re-scoped to enumerate the stored ledger members that really are untouched (`source`, `on_hand_units`, both cumulative counters, `last_service_at`) plus the `updated_at`/`version` bump. — `implementation/routes/sites.py:133-145`

## Per-edit pre-edit search log

**Edit 1 — subject: rendering format of every instant-valued field on every response.**
(b) Paths enumerated / read:
- `serializers.py` in full — `_value()`, `_render()`, and all 13 field tuples; enumerated every instant-valued member: `created_at`, `updated_at`, `placed_at`, `retrieval_due_by` (Account **and** Placement), `cancelled_at`, `price_protection_until`, `last_descale_at`, `reconditioning_until`, `last_service_at`, `window_start`, `window_end`, `completed_at`, `parts_eta`, `loaner_out_date`, `loaner_due_back_date`, `loaner_returned_on`, `period_start`, `period_end`, `issued_at`, `effective_at`, `accepted_at`. All flow through `fmt_instant`.
- `timeutil.py` — `fmt_instant` (hard-coded `%03d` from `microsecond // 1000`), `fmt_date`, `parse_instant`, `parse_date_only`.
- `envelope.py` — `_meta()` uses `fmt_instant(now())` for `api_request_timestamp`; success, created, collection and error bodies.
- `shape.py:103-113` — `fields.instant()` returns a parsed aware `datetime`, so nothing is ever stored as a raw string that would bypass `fmt_instant`.
- grep for `fmt_date` / `parse_date_only` / `.date(` across all of `routes/` — the **only** date-formatted output in the whole surface is `routes/catalog.py:72` `service_date` on the day-load read; `loaner_out_date` / `loaner_due_back_date` / `loaner_returned_on` / `effective_at` are stored as full instants (`routes/workorders.py:172-173, 211-212, 241`; `routes/adjustments.py:32,57`) and only cast to a date transiently for comparison, never for storage.
- `routes/workorders.py:165-250` — confirmed `loaner_out_date` is stored verbatim as supplied (no midnight truncation), so the three-digit readback claim holds even for the "date granularity" fields.

(c) Adjustment made: two. First, the initial draft said the rule "neither truncates nor rounds the stored instant" — dropped, because `fmt_instant` *does* truncate sub-millisecond precision in the rendering; replaced with the weaker, verifiable "this is a rendering rule and nothing more: the value the rules of 3 compare against is the instant as supplied". Second, scoped the universal claim to *instant-valued* members and added an explicit exclusion for day-load's `service_date`, which `routes/catalog.py:72` renders as `YYYY-MM-DD` and would have been mis-described by an unqualified "every temporal field" phrasing.

**Edit 2 — subject: par-line `stock_status` derivation and the set of members a replan touches.**
(b) Paths enumerated / read:
- `routes/sites.py:133-157` (`_write_forecast_par_line`: MANUAL early-return, existing-FORECAST rewrite + `calc.stock_status` + `bump`, new-line insert with hard-coded `STOCKOUT`) and `:160-202` (`size_and_plan` callsite, per-product loop, `bump(site)`).
- `calc.py:16-23` (`stock_status`) — matches PRD 3.2's existing derivation sentence verbatim, so no edit was needed there.
- `routes/parlevels.py:30-46` (MANUAL create, initial `STOCKOUT` with `on_hand` 0) and `:64-80` (PATCH override: pins `source` MANUAL, recomputes `stock_status`, bumps).
- `routes/visits.py:238-250` (completion cascade hop one: recompute after re-deriving `on_hand_units`) and `:332-343` (void: recompute after decrementing the cumulative counters).
- Grep for every `stock_status` assignment in the tree — five sites total, all four mutating ones derive from `(on_hand_units, reorder_point_units)`; no path anywhere leaves it stale.

(c) Adjustment made: replaced the blanket "leaves every other member alone" with an enumerated list of the stored ledger members, and added the explicit `updated_at`/`version` clause — `_write_forecast_par_line` calls `bump(existing)` unconditionally on the rewrite, so an unqualified "every other member" would have been a false universal against the very code path the Step 7 fix lives in. Justified the re-derivation by reference to the derivation rule already stated four sentences later, rather than restating the STOCKOUT/LOW/IN_STOCK thresholds (which would have duplicated — and risked contradicting — PRD line 192).

No edit was made for the three `test_suite/` fixes: PRD already determines all three verbatim, and the implementation matches. Confirmed directly — `routes/visits.py:167` returns `ok(...)` (200) from the line-append (PRD 4 "Status codes"), and `routes/adjustments.py:35-38` gates price protection with a strict `protection > now()` (PRD 3.9 "still ahead of").

**Orchestrator verification:** `PRD_FINALIZED.md` exists, is not byte-identical to `PRD.md`, and `diff` reports exactly two changed lines (`88c88`, `188c188`) — 4 changed lines total counting both sides, matching the reported two in-place revisions. Both files are 510 lines.

## Step 9: Complete PRD — 2026-09-05T08:16:49.856Z

Step 9 always runs. Per the known failure mode (a single-pass scan over a 3566-line implementation silently under-scans and can leave `PRD_COMPLETED.md` byte-identical to its source), the orchestrator split the scan into **three sequential passes partitioned by implementation module**, all editing one shared `workspace/PRD_COMPLETED.md`. Pass 1 performed the `cp`; passes 2 and 3 were explicitly forbidden from re-copying so earlier edits could not be destroyed. Partition sizes were balanced at ~1170-1220 impl lines each.

### Pass 1 — global/core layer (`app.py`, `envelope.py`, `errors.py`, `store.py`, `shape.py`, `authz.py`, `serializers.py`, `lookup.py`, `timeutil.py`, `numbers_util.py`, `routes/testing.py`, `routes/catalog.py`)

`cp` performed. PRD_FINALIZED.md 510 lines / 109,026 chars -> PRD_COMPLETED.md 510 lines / 113,041 chars (+3,990). 17 changes on 16 existing lines, all in-paragraph; line numbering preserved for later passes. **15 ambiguity-pins, 2 mismatch-revisions.**

- 1 (11) — insert — ambiguity — service is entirely in-memory and seeds nothing (fresh boot = empty page for every listing); trailing slash addresses the same endpoint — `store.py:26`, `app.py:33`
- 2.1 (17) — insert — ambiguity — a present-but-empty identity header counts as absent -> `ERR_MISSING_AUTH_HEADERS` — `authz.py:49`
- 2.2 (48) — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A-Z/0-9, minted per response — `envelope.py:17-18`
- 2.2 (49) — insert — ambiguity — `api_request_timestamp` reads the logical clock, not wall time — `envelope.py:22`
- 2.2 (56) — revise — mismatch — error envelope covers 5xx too, not only 4xx — `app.py:55-59`
- 2.3 (78) — insert — ambiguity — non-base-10 `limit`/`offset` is `ERR_VALIDATION`; `offset` >= `total_count` returns 200, empty array, `has_more` false — `shape.py:129-148`, `envelope.py:39`
- 2.3 (80) — insert — ambiguity — equal `created_at` ties break by write order (earliest first); the newest-first route listing reverses the tie-break too — `store.py:91-97`
- 2.4 (88) — insert — ambiguity — instant *input* leniency: with/without fractional seconds, numeric offset converted to UTC, no zone read as UTC, bare `YYYY-MM-DD` = midnight UTC — `timeutil.py:12-28`
- 2.4 (88) — revise — mismatch — "Ten of the thirteen resource types carry all four" -> "Eleven" — `serializers.py:11`, `store.py:55`
- 2.5 (96) — insert — ambiguity — `index_micros` must be an integer but has no range bound; zero/negative accepted — `routes/testing.py:29`
- 2.6 (104) — insert — ambiguity — `escalation_score` serializes as a JSON number always carrying a fractional part (`0.0`, `3.0`), never a string — `serializers.py:101`
- 2.8 rung 4 (123) — insert — ambiguity — explicit JSON `null` treated as omitted; absent/unparseable body treated as `{}`; non-object body is itself `ERR_VALIDATION` — `shape.py:17-23,51-55`
- 3.2 (176) — insert — ambiguity — `max_headcount` below `min_headcount` (and `max_headcount` >= 1) is plain `ERR_VALIDATION` — `routes/catalog.py:88-92`
- 3.4 (232) — insert — ambiguity — day-load returns exactly four members; `service_date` required, echoed as `YYYY-MM-DD`, full instant accepted with only its UTC date used, and its validation precedes an unknown `route_id` — `routes/catalog.py:65-76`, `timeutil.py:31-43`
- 3.4 (236) — insert — ambiguity — a serialized visit line always carries all six members and no id of its own, the four delivery-side ones `null` before completion — `serializers.py:55-58,129-130`
- 4 (376) — insert — ambiguity — filter values compared raw, never validated against the field's value set (unknown value => empty page, not an error); boolean filter accepts `true/false/1/0` case-insensitively — `lookup.py:85-104`
- 5 (445) — insert — ambiguity — three out-of-table failures: undeclared path -> 404 `ERR_NOT_FOUND`, unsupported method -> 405 `ERR_METHOD_NOT_ALLOWED`, unexpected failure -> 500 `ERR_INTERNAL` — `app.py:42-59`

Verified no change needed: all 62 error ids and statuses in 5 match `errors.py` exactly and in order (checked programmatically); every catalog endpoint's authorized-role list matches the 4 table; catalog field ranges/defaults, initial states, uniqueness-last ordering and the rung 1->2->3 order already pinned.

Left unpinned by pass 1: `store.touch()` vs `store.bump()` (call sites all in later partitions — deferred to pass 2 to avoid a false universal); `calc.booked_minutes_on_date` (pass 2); human-readable `message` texts (PRD leaves wording free); whitespace tolerance in limit/offset parsing and JSON key ordering (not observable).

### Pass 2 — calculation kernel, cascade engine, account/site/par/placement (`calc.py`, `cascade.py`, `routes/accounts.py`, `routes/sites.py`, `routes/parlevels.py`, `routes/placements.py`)

Did NOT re-copy; 13 surgical Edits. 510 lines / 113,041 chars -> 510 lines / 116,937 chars. Line count preserved. All 17 of pass 1's edits verified surviving (5 distinct markers spot-checked). **12 ambiguity-pins, 1 mismatch-revision.**

- 3.1 — insert — ambiguity — the `escalated_site_count` recompute runs on *every* site-posture evaluation, and the account's `version` moves only when `escalated_site_count` or `program_posture` actually changed — `cascade.py:41-56`
- 3.1 — insert — ambiguity — `cancel_reason` must be non-empty, `retrieval_due_by` is required and need not be in the future — `routes/accounts.py:67-69`
- 3.1 — insert — ambiguity — cancellation hops two/three reach only sites owning an `ACTIVE` placement; cancelling out of `AT_RISK` leaves `DEFERRED` adjustments deferred — `cascade.py:111-131`
- 3.1 — insert — ambiguity — allied-attachment refresh has no posture gate and bumps `version` only when the figure actually changed — `routes/accounts.py:81-84`
- 3.2 — revise — **mismatch** — site PATCH: PRD claimed `version` "increments by 1"; impl uses conditional `touch`, so a no-op PATCH leaves `updated_at`/`version` unmoved — `routes/sites.py:101` + `store.py:71`
- 3.2 — insert — ambiguity — planning's two feasibility rejections are ladder-ordered (model fit ahead of trailing usage); site `version` bumps unconditionally on success — `routes/sites.py:174-185,201`
- 3.2 — insert — ambiguity — under `TRAILING_USAGE`, a product with no observed delivery gets par 0 / reorder 0 and its line is still written; the rejection is keyed on site history, not per-product — `routes/sites.py:182,197`
- 3.2 — insert — ambiguity — a `FORECAST` line rewrite bumps `version` unconditionally even when the recomputed numbers are identical; lines visited in catalog registration order — `routes/sites.py:144,193`
- 3.2 — insert — ambiguity — par-line override is **not** subject to creation's `reorder_point_units <= par_units` rule; an empty-body override is accepted and still pins `MANUAL` + bumps `version` — `routes/parlevels.py:64-79`
- 3.2 — insert — ambiguity — the model selector's residual `created_at` tie is broken by registration order — `calc.py:88-89`
- 3.5 — insert — ambiguity — the elapsed-day count is signed, so a `window_start` before `last_service_at` yields negative `consumed_units`; the `min()` against `on_hand_units` does not lift it to zero — `calc.py:197-206`
- 3.5 — insert — ambiguity — `evaluate-service-posture` has no posture gate: a `SUSPENDED`/`CLOSED` site has its `escalation_score` rewritten while posture and `version` stay put — `routes/sites.py:105-111` + `cascade.py:75-77`
- 3.7 — insert — ambiguity — a third+ consecutive miss from `SHORTFALL_BILLED` is a holding pattern: status stays, `shortfall_fee_cents` is not re-derived, only `trailing_purchase_cents` refreshes — `routes/placements.py:123-130`
- 3.7 — insert — ambiguity — rental proration days are capped above at 30 but **not** floored at zero, so a `placed_at` after the period end yields negative rent — `calc.py:348-352`

Left unpinned by pass 2: `calc.route_booked_minutes_total` is dead code; `calc.months_in_service` with a future anchor already uniquely determined by existing 3.3 prose; microsecond truncation absorbed by a surrounding floor in every reachable case; site `version` in cascade hop two (call sites are pass 3's); undeclared body members silently ignored (pass 1's `shape.py`); `min_term_months` and `service_minutes_estimate` stored and serialized but consulted by no rule; par-line *processing* order (deferred to pass 3); `active_placement_of_asset` (pass 3); unreachable defensive branches.

### Pass 3 — visit / work-order / invoice / adjustment surface (`routes/visits.py`, `routes/workorders.py`, `routes/invoices.py`, `routes/invoicelines.py`, `routes/adjustments.py`)

Did NOT re-copy; 23 surgical Edits, no Write. 510 lines / 116,937 chars -> 510 lines / 125,812 chars, every edit in-paragraph. Passes 1+2 verified surviving via 8 spot-checked markers. **19 ambiguity-pins, 4 mismatch-revisions** (23 edits over 22 lines).

- 3.4 — insert — ambiguity — scheduling increments the route's own `version` by 1 — `routes/visits.py:83-84`
- 3.4 — insert — ambiguity — reschedule excludes the visit's own `planned_minutes` from the day's booked total (so an in-date move always fits) and bumps `version` even for an identical window — `routes/visits.py:131-136`
- 3.4 — insert — ambiguity — `requested_units` carries no declared bound; 0 and negatives accepted at append — `routes/visits.py:145`
- 4 — insert — ambiguity — the visit `service_date` filter is not a stored member: it matches `window_start`'s UTC date, accepts a date or an instant, matches nothing if unparseable — `routes/visits.py:88-104`
- 3.5 — insert — ambiguity — `delivered_lines` element shape violations are `ERR_VALIDATION` at rung 4, ahead of the visit's existence; a repeated `product_id` resolves last-wins — `routes/visits.py:170-195`
- 3.5 — insert — ambiguity — each touched par line's `version` increments by exactly 1 unconditionally at completion — `routes/visits.py:247`
- 3.5 — revise — ambiguity — void: `void_reason` non-empty; par `version` +1 unconditionally; "most recent" pinned as greatest `window_start` with write-order tie-break and "touched" = carries a line for the product; route `version` +1; shortfall streak walked in `completed_at` order as the trailing unbroken run — `routes/visits.py:286-352`
- 3.6 — insert — ambiguity — an asset with no `ACTIVE` placement is `ERR_ASSET_NOT_AVAILABLE` (409), evaluated **before** route ownership because the site is unknown until the placement is found; at most one `ACTIVE` placement per asset — `routes/workorders.py:58-63`
- 3.6 — insert — ambiguity — `parts_eta` / `resolution_note` shapes are checked unconditionally at rung 4 even on transitions that ignore them — `routes/workorders.py:105-106`
- 3.6 — revise — **mismatch** — loaner dates are ordinary instants stored verbatim (not truncated to midnight UTC); only the UTC date is compared — `routes/workorders.py:172-173,198-199`
- 3.6 — insert — ambiguity — the swap imposes no `asset_status` precondition beyond the sanitation hold; the lazy `RECONDITIONING`->`IN_STOCK` release is a mutation, so the asset's `version` moves by 2 — `routes/workorders.py:179-216`
- 3.6 — insert — ambiguity — `returned_on` before `loaner_out_date` is `ERR_VALIDATION` evaluated *after* the `loaner_status` gate; no upper bound against the clock — `routes/workorders.py:228-233`
- 3.8 — insert — ambiguity — the overlap test narrows to one site only when the account is `PER_SITE` **and** `site_id` was sent, so it can fire ahead of `ERR_BILLING_MODE_MISMATCH` — `routes/invoices.py:248-251`
- 3.8 — insert — ambiguity — assembly is the sole writer of stored `rent_charge_cents` after creation, writing it to every billable `RENTAL` placement including zero/negative results, with a conditional `version` bump — `routes/invoices.py:117-128`
- 3.8 — revise — **mismatch** — `amount_cents` is not "positive for the rest": `RENT` is genuinely signed via the negative proration of 3.7 — `routes/invoices.py:117-120`
- 3.8 — revise — **mismatch** — the empty-invoice rejection is keyed on the four billable line types (not `line_count`) and runs before the total/discount/freight; a refusal commits nothing at all, since every line and side effect is staged — `routes/invoices.py:268-329`
- 3.8 — insert — ambiguity — the line write order (four charge groups, loaner group ordered by work-order `created_at` across scope, discounts, freight last) and that it is what the listing reports — `routes/invoices.py:274-327`
- 3.8 — insert — ambiguity — issue gates ordered posture -> lifecycle -> line count; account `version` +1 unconditionally — `routes/invoices.py:353-371`
- 3.8 — revise — ambiguity — `credit_reason` must be non-empty — `routes/invoices.py:387`
- 3.9 — insert — **mismatch** — `effective_at` is inert (repricing lands at acceptance whatever it says); proposing carries no program-posture gate — `routes/adjustments.py:32-57`
- 3.9 — insert — ambiguity — a proposal raised while the account is *already* `AT_RISK` is born `PROPOSED` and respondable; only the `ACTIVE`->`AT_RISK` transition defers — `routes/adjustments.py:48-59`
- 3.9 — insert — ambiguity — `dispute_reason` is never cleared; it survives revision and acceptance — `routes/adjustments.py:100-121`
- 3.9 — insert — ambiguity — revision changes nothing but the three fields; the index snapshots and `movement_bps` are not re-read — `routes/adjustments.py:142-145`

Deferred-item verdicts: **site `version` in cascade hop two** — confirmed correct as written; both call sites pass a `snapshot` taken before the shortfall-counter write (`visits.py:220`, `visits.py:351`) into `cascade.apply_site_posture`, which ends in `touch(site, before)`, so 2.10's conditional wording is exactly right, no edit. **Par-line processing order at completion** — confirmed result-neutral; `_par_sort_key`'s `_seq` tie-break and its "missing par sorts last" branch are unobservable since each line owns a distinct par row, so no tie-break prose was added. **`active_placement_of_asset`** — its unordered first-match scan is deterministic because an asset must be `IN_STOCK` to be placed and leaves `IN_STOCK` on placement, so at most one `ACTIVE` placement can reference it; the invariant was pinned in 3.6 rather than a scan order. No pass 1/2 sentence was reverted or narrowed; the 4 and 3.4 line-236 edits are pure appends after their text.

Left unpinned by pass 3, with reasons: **zero/negative green index baseline -> HTTP 500** — accepting an adjustment re-bases `green_index_baseline_micros` to `index_current_micros`, which 2.5 permits to be 0 or negative; a later proposal then divides by it in `calc.movement_bps` and raises, surfacing as `ERR_INTERNAL`. Reachable, but documenting a crash as contract is worse than leaving it loose, and 5 already declares `ERR_INTERNAL` for unexpected server-side failures — flagged as a genuine implementation fragility rather than a doc gap. **Same `SHORTFALL` accrual on two drafts** — two non-overlapping-period drafts for one account each emit a `SHORTFALL` line for the same accrual; existing wording already determines this uniquely. **Micro string-length bounds** on identifier-shaped body fields — uniformly `min_len=1`, a global `shape.py` convention rather than a 3 behavior; only the two prose-visible reason strings were pinned.

### Pass 3 structural check (post-edit)
`## ` sections: 5 (lines 3, 13, 156, 372, 443) · 4 endpoint table: 60 data rows · 5 error table: 62 data rows · final line 510 is a complete table row (`| ERR_CREDIT_EXCEEDS_INVOICE_TOTAL | 422 |`), nothing mid-sentence.

### Orchestrator independent verification of Step 9
`PRD_COMPLETED.md` exists at 510 lines / 125,812 chars, is **not** byte-identical to `PRD_FINALIZED.md` (the tell that the scan never ran), and `diff` reports 48 changed-line hunks against it — consistent with the three passes' cumulative 47 edits across 49 lines. Structure re-checked independently: 5 `## ` sections, 60 endpoint rows in 4, 62 `ERR_` rows in 5, final line a complete table row. Also confirmed Steps 8 and 9 were documentation-only: every file under `workspace/implementation/` has an mtime at or before 07:32 (the Step 7 fix to `routes/sites.py`), i.e. no code was touched after the green 07:35 sweep, and no file under `test_suite/` or `test_helpers/` was modified after it either. `__pycache__` directories and the `.scratch/` directory were removed.

## Pipeline complete
All nine steps finished. Final state: 94/94 tests passing in all 8 rounds of the last stability sweep, 0 tests deleted, `PRD.md` -> `PRD_FINALIZED.md` (2 revisions) -> `PRD_COMPLETED.md` (47 further pins/revisions).
