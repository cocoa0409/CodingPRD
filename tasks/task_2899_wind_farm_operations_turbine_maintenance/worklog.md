## Step 1: Create task directory — 2026-09-05T13:24:54.679Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2899_wind_farm_operations_turbine_maintenance and its workspace/ subdirectory. Index 2899 was pre-assigned by the orchestrating prompt (no ./tasks/ scan performed, since up to 32 pipelines run concurrently on this host and auto-allocation would collide).

## Step 2: Generate Scaffold — 2026-09-05T14:57:31.147648221Z

All three scaffold artifacts for task 2899 are complete and pass `scaffold_lint.py` in task-dir form.

**Final lint verdict (task-dir invocation, all three files present):**
```
Coverage
  §1.5 endpoints declared:    73
  §1.1 entities declared:     15
  §1.8 instances scanned:     24
  §1.9 instances scanned:     38
  Calls scanned (§1.8+§1.9):  769

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2899_wind_farm_operations_turbine_maintenance/`, each parses as complete YAML, no truncation):
- `SCAFFOLD.yaml` — 3219 lines / 165 KB. §1.0–§1.7 only (verified: no `scaffold_difficulty_design`, no `scaffold_corner_design`). 15 entities, 73 endpoints, 10 state machines, 2 concurrency rules (`expected_wind_farm_version` on landowner-settlement create, `expected_turbine_version` on curtailment-order create), 9 calculations, 38 validations, 41 error codes, 6 roles. Profile: temporal_windowing + ledger_reconciliation, layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers`, graph topology, parallel state-machine shape, segregation_of_duties, immediate consistency. The `scenario:` key is the verbatim 2899 text with no difficulty directive leak.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2662 lines. Single top-level key. All nine rule_ids with >=2 instances, 24 total: `dual_variant_calc` 2, `combinatorial_formula` 3, `non_linear_state_machine` 3, `transitive_cascade` 2, `priority_pair_validation_conflict` 3, `boundary_precision_check` 3, `cross_entity_state_dependency` 3, `resource_temporal_overlap` 3, `compensating_invariant` 2.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2749 lines. Single top-level key. 9 sections drawn only from the claim-extraction guide — `entities` (12), `state_machines` (14), `calculations` (9), `validations` (5), `endpoints` (4), `errors` (1), `rbac` (5), `cross_cutting_complexity_layers` (4), `consistency_model` (1) — 55 instances total: 38 full `test_recipe` instances + 17 `excluded_because` stubs. Every stub's `difficulty_instance` was verified to match a §1.8 name exactly; no name collides across the two design files.

**Error triggerability:** all 41 declared codes now have at least one triggering instance across §1.8+§1.9 (verified programmatically). The 17 that §1.8 left uncovered are picked up by corners for auth (401/403 family incl. `ERR_SEGREGATION_OF_DUTIES` on both guarded endpoints and `ERR_CREW_NOT_ASSIGNED` via the entity-backed CrewLead), the four path-not-found codes plus the `ERR_PATH_RESOURCE_NOT_FOUND` fallback, both OCC 412s, the three invalid-state families, `ERR_TURBINE_DECOMMISSIONED`, `ERR_RESET_NOT_PERMITTED`, `ERR_RESET_QUOTA_EXHAUSTED`, `ERR_CREW_CERTIFICATION_MISSING`, `ERR_CREW_FARM_MISMATCH` and `ERR_NO_TURBINES_IN_SERVICE`.

**Scaffold defects found and fixed while designing (all in SCAFFOLD.yaml, all re-linted):** curtailment-release formula contradiction between state machine and endpoint; an unreachable same-reason-overlap precondition with no error code (deleted); `ERR_RESET_NOT_PERMITTED` structurally unreachable plus `requires_dispatch` consulted but never pinned (added `FaultEvent.requires_dispatch_pinned`, widened validation 70 to triage); `ERR_RESET_QUOTA_EXHAUSTED` unreachable (FAILED reset is now a `RESET_PENDING` self-loop with escalation via a `triage disposition=DISPATCH` edge); pagination unexpressible under lint check (c) (`limit?`/`offset?` added to all 15 list endpoints); and a three-way inconsistency on `Turbine.effective_power_limit_kw`, canonicalised to the `TurbineModel.rated_power_kw` nameplate fallback.

Scratch files used: `/tmp/task_2899_scaffold/` only (task-scoped); no sibling task directory was read at any point.

Orchestrator verification: all three files present; `grep -rn "harder than expert"` over the task dir returns nothing, so the difficulty directive did not leak into any scaffold artifact.

## Step 3: Copy Shared Files — 2026-09-05T14:57:36.187896303Z

Copied ./INSTRUCTION.md to /home/ubuntu/github/CodingPRD/tasks/task_2899_wind_farm_operations_turbine_maintenance/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T15:11:29.780416937Z

PRD generation complete.

**Output:** `workspace/PRD.md` — **465 lines**, built in 9 incremental chunks (1 `Write` + 8 `cat >>` heredocs); no single-Write truncation risk. File ends cleanly at the final row of the §5 table (`ERR_NO_TURBINES_IN_SERVICE | 422`), with no audit footer.

**Structure**
- `## 1. Introduction` — 3 paragraphs (three revenue-loss channels, operational-ledger framing, `/wind-ops` mount + segregation of duties).
- `## 2. Global Specifications & System-Wide Principles` — 12 domain-derived subsections: 2.1 Operating Personnel and RBAC, 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Logical Clock, 2.5 Interval Conventions, 2.6 Precision/Rounding/Money, 2.7 Stale-Version Guards, 2.8 The Rejection Ladder (18 rungs covering all 38 validation priorities), 2.9 Path and Reference Resolution, 2.10 Two Conserved Ledgers, 2.11 A Turbine Has Two Independent State Dimensions, 2.12 Cascade Discipline and Recomputation.
- `## 3. Business Logic & Workflows` — 9 subsections: 3.1 site standup, 3.2 control room/telemetry/triage/remote reset, 3.3 forecast windows + work-order loop, 3.4 crew commitment, 3.5 start/complete/abandon, 3.6 blade inspection programme, 3.7 stock/cranes/two execution branches, 3.8 curtailment, 3.9 availability guarantees + LDs + landowner payments.
- `## 4. API Endpoint Definitions` — status-code paragraph + 73-row table, exactly 4 columns.
- `## 5. Error Code Definitions` — lead-in + 41-row table, exactly 2 columns.

**Hard Contract reports**
- **Contract 1 — Field-Name Coverage: PASS.** Verified mechanically against the scaffold (not a cached list): 163/163 `entities[].fields[].name` and 117/117 endpoint `request_body`/`input`/`query_params`/`path_params` identifiers (optional `?` markers stripped) appear verbatim in backticks. 0 missing.
- **Contract 2 — Rule Coverage: PASS.** 58/58 state-machine transitions across all 10 machines are described (52 with explicit `FROM -> TO` arrow phrasing; the remaining 6 — WorkOrder `SUBMITTED`/`SCHEDULED` -> `CANCELLED`, the FaultEvent `RESET_PENDING` self-loop on a `FAILED` reset, ComponentReplacement `PLANNED`/`CRANE_RESERVED` -> `CANCELLED`, and WeatherWindow `CONFIRMED` -> `EXPIRED` by clock advance — are covered by multi-state prose enumerations, individually re-verified). All 9 calculations have full arithmetic including the two divergent rounding orders (priority score: sum-then-round-once; blade severity: per-term-then-sum). All 37 validation `error_id`s plus the 4 systemic ones are explained in §2/§3 body text, not only in the §5 table. Both OCC rules, both conserved-ledger identities, all cross-entity cascades, all `applies_to` scopes, and both sibling forks (crane-lift vs up-tower; TIME_BASED vs ENERGY_BASED; METERED_ONLY vs DEEMED_INCLUSIVE) are written with equal density.
- **Contract 3 — §3 Path Purity: PASS.** Scanned every backtick token between `## 3.` and `## 4.`: 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combinations. All paths are confined to §2.7, §2.9 and the §4 table.

**Other checks:** §2.2 is byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md`; no fuzzy words (`approximately`/`roughly`/`conservatively`/`etc.`) anywhere; all 73 endpoint paths and all 41 error ids present. The two forbidden design YAMLs were never opened, grepped or referenced. Scratch work stayed in `/tmp/task_2899_prd/`.

**One scaffold inconsistency worth flagging to the orchestrator:** `CurtailmentOrder.lost_energy_kwh`'s *field description* gives `curtailed_hours x (expected_kwh_per_hour - power_limit_kw)` floored at 0, while both the state-machine transition side-effect and the release endpoint's `side_effects` give `curtailed_hours x deemed_kwh_per_hour`. I followed the two behavioural specs (`deemed_kwh_per_hour`) since they are the operative contract and agree with each other; the PRD states only that formula.

Orchestrator anti-truncation verification: `wc -l` = 465; `tail -25` shows the file terminating on a complete §5 table row; all five top-level sections (1-5) and all 30 subsection headings present. Not truncated — no regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-05T17:03:36.533695377Z

Generation complete. Task 2899's test infrastructure and suite are finished and verified.

## Output (all at the task root, nothing under `workspace/`)

**test_helpers/** (Stage 1) — `__init__.py` 19, `api_client.py` 714, `api_errors.py` 115, `assertions.py` 308, `constants.py` 232, `factories.py` 465, `fixtures.py` 3107, `test_users.py` 119, `types.py` 253

**test_suite/** (Stage 2) — `conftest.py` 52; `test_01_variant_calculations.py` 175 (4 tests), `test_02_combinatorial_formulas.py` 229 (6), `test_03_state_machine_dimensions.py` 292 (6), `test_04_transitive_cascades.py` 239 (4), `test_05_rejection_ladders.py` 319 (6), `test_06_boundary_precision.py` 356 (6), `test_07_cross_entity_state.py` 406 (6), `test_08_temporal_overlap.py` 473 (6), `test_09_conserved_ledgers.py` 403 (4), `test_10_entity_surface.py` 698 (12), `test_11_state_machine_surface.py` 702 (8), `test_12_derived_calculations.py` 193 (3), `test_13_gate_ladders_and_endpoints.py` 456 (6), `test_14_access_control_surface.py` 458 (6), `test_15_concurrency_and_visibility.py` 322 (3)

**86 tests total; 11,105 lines.**

## Instance coverage

- **§1.8 (queue A, difficulty): 24/24 instances translated, 2 tests each = 48 tests.** No instance skipped.
- **§1.9 (queue B, corner): 38/38 non-stub instances translated = 38 tests.** The other 17 of the yaml's 55 entries carry `excluded_because:` (stubs that point back to a §1.8 instance) and are correctly not emitted.
- **0 instances dropped by the PRD-first two-condition filter** — every non-stub instance had verbatim PRD coverage and a uniquely-derived outcome.

## Verification run

- `python3 -m py_compile` clean over all 25 modules; `pytest --collect-only` collects exactly 86 tests with no import errors.
- Custom AST checker: **all citations verbatim** against the normalized PRD, **all `Design:` tags resolve** to real instances, exactly one tag as the last docstring line of every test; **0 unused imports** across all modules.
- No inline infrastructure: every payload comes from `factories.py`, every setup from `fixtures.py`, every header set from `test_users.py`.

## Known design-yaml defects worked around (documented for Step 7 triage)

- Instance 1979 asserted a second `demobilize` succeeding while its replacement was still `CRANE_RESERVED`, which §3.7 forbids — the test executes the replacement first.
- `uptower_labor_hours: 0.0` (invalid, §3.7 requires > 0) omitted; `damage_type: "COATING_LOSS"` (undeclared) replaced with declared types.
- Instances 2236 ("labor_cost_cents still null") and 1486 ("availability pcts still null") contradict §3.3/§3.9, which open both at 0 — tests assert 0.
- Instance 2336's `recorded_by_user` is `recorded_by_user_id` in the PRD.
- PRD §4 names `ERR_ROLE_NOT_PERMITTED` while §2.1/§2.8/§5 name `ERR_UNAUTHORIZED`; tests use `ERR_UNAUTHORIZED` (the only code `api_errors.py` declares).

`worklog.md` was not touched, `workspace/implementation/` was not touched, and no server was started (so no process was killed).

Orchestrator verification: `test_helpers/` (9 modules) and `test_suite/` (16 files) both landed at the task root; no stray copies under `workspace/`.

## Step 6: Generate Implementation — 2026-09-05T17:03:36.533695377Z

The implementation is complete and verified.

## Files written (all under `workspace/implementation/`)

| file | lines |
|---|---|
| `app.py` | 58 |
| `auth.py` | 34 |
| `calc.py` | 264 |
| `enums.py` | 85 |
| `envelope.py` | 152 |
| `errors.py` | 103 |
| `ladder.py` | 84 |
| `store.py` | 120 |
| `svc.py` | 536 |
| `validate.py` | 186 |
| `routes/__init__.py` | 0 |
| `routes/setup.py` | 311 |
| `routes/control.py` | 261 |
| `routes/planning.py` | 554 |
| `routes/major.py` | 402 |
| `routes/commercial.py` | 485 |
| `start.sh` (executable) | 10 |
| `requirements.txt` | 1 |
| **total** | **3646** |

## Endpoints

**73 of 73 declared endpoints registered** (enumerated from `app.url_map`, exact match against the SCAFFOLD `endpoints` block: clock 1, farms 3, turbine-models 3, turbines 5, crews 3, fault-code-rules 4, fault-events 6, weather-windows 4, work-orders 9, crane-mobilizations 4, spare-parts 4, component-replacements 7, blade-damages 5, service-agreements 5, curtailment-orders 5, landowner-settlements 5).

## Verification

- `python3 -m py_compile` clean over all 16 `.py` files.
- Two smoke suites (`/tmp/task_2899_impl/smoke.py`, `smoke2.py`) run against `PORT=18299 bash start.sh`, both **0 failures**, killed by exact PID (no pattern kills). Coverage included: the fault-event loop with remote reset + close (downtime 3.0 h / lost energy 9000.0 kWh), the full work-order chain (submit -> schedule -> start -> complete) with labour cost, crane tiered pricing (`subtotal 7,000,000` -> 3 % credit `210,000`, `lift_days=2`), buffer conflict at 96 h spacing (409), the 4-hop replacement cancellation with the 40 % cancellation fee (`1,200,000`), the up-tower fork (`estimated_hours` 8 -> 11, spend `2,850,000` = 3 h x 950,000), blade severity banding + SoD (403 for the recorder), the curtailment stack (`FORCED_STOP` -> `UNCONSTRAINED`, limit restored to nameplate 4000), stale-version 412s, the settlement telemetry freeze (`ERR_AGREEMENT_IN_SETTLEMENT`), and settlement approve/void with the farm opex ledger invariant exact before and after reversal.
- Fresh-boot isolation confirmed: after a restart `GET /farms` returns `[]` — no seeding, in-memory only.
- Envelope confirmed against the scaffold: `meta.api_request_id` / `meta.api_request_timestamp` (logical clock), `response_type`, errors as `data.error_id` + `message`, pagination fields in `meta`. Instants are always 3 fractional digits + `Z`; money is JSON integers, decimals are JSON numbers.

Two spec conflicts were resolved in the PRD's favour, per the skill's precedence rule: `CurtailmentOrder.lost_energy_kwh` uses `curtailed_hours x deemed_kwh_per_hour` (PRD §3.8) rather than the entity note's `expected - power_limit`; and landowner approve/void post `road_levy + road_damage_assessment` to the road reserve so the opex identity holds exactly. Undeclared-error cases (uniqueness collisions, crane-class insufficiency for GEARBOX/BLADE, the settle clock gate, demobilize preconditions) map to `ERR_INVALID_REQUEST` / `ERR_INVALID_STATE`.

Note: Steps 5 and 6 were launched concurrently in a single orchestrator message, so the implementation generator started before `test_suite/` existed on disk — physical isolation from the tests was guaranteed, not merely instructed.

## Step 7: Run Tests and Iterate — 2026-09-05T17:17:34.497254567Z

Clean 8-round sweep. Done.

## Summary

**Iterations run:** 2. Iteration 1 = 82/86 in all 8 rounds (4 deterministic failures, zero flakiness). Iteration 2 = **86/86 in all 8 rounds**, `SWEEP_COMPLETE` present.

All four failures were test bugs. No implementation change was needed, and no test was deleted — every asserted rule was verbatim in PRD and uniquely derivable; in each case the *test* had mis-translated it.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**

1. `test_01_variant_calculations.py` — `test_deemed_inclusive_royalty_scales_the_same_curtailment_into_the_payment`: asserted `deemed_kwh == 43200` (i.e. the released order's accrued `curtailed_hours` of 24 h). PRD §3.9 computes deemed energy from *"that order's hours of overlap with the half-open settlement period"*, and the order's span is `start_utc`->`end_utc` — declared in §2.5 (*"curtailment intervals (`start_utc` to `end_utc`)"*) and spelled out verbatim in the sibling counted-downtime clause one paragraph earlier (*"the hours of overlap between that order's span from `start_utc` to `end_utc` and the measurement period"*). The order spans 2026-06-10->06-12 wholly inside June, so 48 h x 1800 = 86400. Corrected to `deemed_kwh == 86400`, `royalty_cents`/`payment_cents` == 260736 (1 086 400 kWh x 6 c x 4 %). The "strictly larger than METERED_ONLY" assertion still holds (240 000).

2. `test_08_temporal_overlap.py` — `test_the_crane_pad_closes_at_the_touch_point_on_both_of_its_edges`: the test had the boundary inverted on both edges, treating *padded*-interval adjacency as a conflict. PRD §3.7 refuses only when the padded interval **overlaps**, and §2.5's normative overlap test excludes adjacency; the one stated exception is that *raw* adjacency conflicts *because* the pads then overlap by 96 h. Anchor pad is [09-08, 09-14). Rewrote the four cases to the true boundaries: raw adjacency (start 09-12, the PRD's own 96-hour worked example) -> refused; start 09-15T23:59:59 (one second inside the upper pad edge) -> refused; start 09-16T00:00:00 (pads touch) -> 201; end 09-06T00:00:01 (one second inside the lower pad edge) -> refused; end 09-06T00:00:00 (pads touch) -> 201. Final `total_count == 3` assertion unchanged. Net effect: coverage went *up* — the test now also pins the PRD's explicit raw-adjacency example, which it previously never exercised.

3. `test_10_entity_surface.py` — `test_the_replacement_junction_is_reachable_in_reverse_through_all_three_filters`: created the child order as `BLADE_REPAIR` with no `blade_damage_id`, which PRD §3.3 makes **required** for that work type, so the PRD-faithful server correctly returned `ERR_INVALID_REQUEST`. Switched the child to `MAJOR_COMPONENT` — the work type with no mandatory link, and the one the test's own quoted PRD sentence names as the typical `parent_work_order_id` carrier — so the test isolates the self-reference it is actually about. Dropped the now-unused `WORK_TYPE_BLADE_REPAIR` import.

4. `test_14_access_control_surface.py` — `test_an_absent_empty_or_undeclared_role_header_is_answered_before_anything_else`: `assert_version_unchanged` compared against `site["farm"]`, the creation-time snapshot at version 1, but `base_site` then commissions a turbine, which per §3.1/§2.4 legitimately mutates the farm row (`turbine_count`, `installed_capacity_kw`) and advances its `version` to 2. Now reads a `baseline` farm row after fixture setup and compares the post-401 read against that, which is what "a rejected request writes nothing" actually claims.

**Fixes applied to `implementation/`:** none. Both flagged Step 5/6 ambiguities held up: `ERR_UNAUTHORIZED` is the right choice for role-authorisation failures (§2.1/§2.8/§5 agree; §4's `ERR_ROLE_NOT_PERMITTED` is the outlier), and `CurtailmentOrder.lost_energy_kwh = curtailed_hours x deemed_kwh_per_hour` matches §3.8. Worth noting for the record: the `deemed_kwh` fix above confirms the settlement-side and order-side energy figures are *deliberately different quantities* — the order accrues on `released_at`, the landowner settlement clips the full declared span — which is exactly the trap the test had fallen into.

**worklog.md:** untouched by the subagent, as instructed.

Orchestrator verification (not taken on faith): all 8 `workspace/implementation/results.{1..8}.json` exist, timestamped 17:16, each parsed independently -> `passed=86 total=86 failed=0`; `workspace/sweep.log` ends in `SWEEP_COMPLETE`. The sweep was driven by the orchestrator-authored `workspace/sweep.sh`, which wraps the 8 rounds in `setsid nohup` and embeds the required `cd .../implementation && bash start.sh`, so no reaping and no inline-quoting failure was possible.

## Step 8: Finalize PRD — 2026-09-05T17:21:16.215609441Z

`PRD_FINALIZED.md` written. One sentence changed; three of the four Step 7 sites needed no PRD patch.

**Line counts:** PRD.md 465 lines / PRD_FINALIZED.md 465 lines — 0.00% line delta; exactly one sentence rewritten in §3.9 (verified by sentence-level diff: 1 of 930 sentence-lines differs).

## Change

- **§3.9 (landowner royalty chain, `deemed_kwh`) — revise —** pinned the interval a `RELEASED` compensable curtailment order contributes to `deemed_kwh` as its declared span `start_utc` -> `end_utc`, explicitly *not* `start_utc` -> `released_at`, so the settlement clips the full declared span even for an early release — `implementation/svc.py:441-444` (`royalty_figures`, `calc.overlap_hours(c["start_utc"], c["end_utc"], period_start, period_end)`).

## Per-edit pre-edit search log

**Edit 1 — §3.9 `deemed_kwh` span**
- (a) **Subject:** which interval of a curtailment order is clipped against a period, and specifically what a `RELEASED` order's span is for settlement purposes.
- (b) **Impl paths enumerated / read:** `svc.py:426-461` `royalty_figures` (the Step 7 site — `start_utc`/`end_utc`); `svc.py:380-398` `clipped_downtime` (service-agreement counted downtime, curtailment leg — also `start_utc`/`end_utc`, and already stated verbatim in PRD, left untouched); `routes/commercial.py:320-345` release handler (`curtailed_hours = hours_between(start_utc, released_at)`, `lost_energy_kwh = curtailed_hours x deemed_kwh_per_hour` — the *other* quantity, which my wording must not redescribe); `routes/control.py:78-95` decommission cascade (releases `ACTIVE` orders by state only, leaving `released_at` unset and `curtailed_hours` at 0 — so any wording that made the settlement depend on `released_at` would be unimplementable for cascade-released orders); `svc.py:288` `recompute_curtailment_dimension` (reads `power_limit_kw` on `ACTIVE` orders, no intervals); `calc.py:111-124` `overlap_hours`/`overlaps`. Grepped `deemed` and `curtailment_orders` repo-wide to confirm no fourth consumer of a curtailment interval.
- (c) **Wording adjustment:** scoped the clause to the landowner settlement's own sentence and phrased the exclusion as a negation of `released_at` *for this figure only* (mirroring §3.8's own "not from `start_utc` to the order's `end_utc`" style) rather than making any general statement about a released order's span — §3.8's `curtailed_hours`/`lost_energy_kwh` accrual and the decommission cascade both remain correctly described. Used "declared span" rather than redefining §2.5.

## Sites deliberately left byte-identical (PRD already uniquely determines the impl behavior)

- **Item 2, crane pad boundaries (§3.7).** `routes/major.py:43-54` pads both sides by 48 h and compares with `start < o_end and end > o_start` — strict half-open overlap on the *padded* intervals, i.e. touching pads do not conflict. §3.7 ("refused ... when its padded interval **overlaps** the equally padded interval") plus §2.5's normative overlap test (adjacency does not overlap) plus §3.7's stated single exception (raw adjacency conflicts because the pads then overlap by 96 h) already fix all four boundaries the test got wrong. Pure test bug.
- **Item 3, `blade_damage_id` required for `BLADE_REPAIR` (§3.3).** `routes/planning.py:140-151` raises `ERR_INVALID_REQUEST` when it is absent on a `BLADE_REPAIR` order and when it is present on any other work type; `parent_work_order_id` is unconditionally optional (`planning.py:125-126, 155`). §3.3 states "required when `work_type` is `BLADE_REPAIR`", §2.8 rung 5 maps a missing required field to `ERR_INVALID_REQUEST`, and §2.9 lists `parent_work_order_id` among body FKs. Pure fixture bug.
- **Item 4, farm `version` advancing on turbine commissioning (§3.1/§2.4).** `routes/setup.py:168-169` calls `recompute_farm_capacity(farm)` then `DB.touch(farm)`; the mirror path `routes/control.py:98-100` does the same on decommission. §3.1 says commissioning increments `turbine_count` and `installed_capacity_kw`, and §2.4 says `version` increments by exactly 1 on every mutation "including mutations that reach the row by cascade from an operation that named a different resource". Determined; the test had simply snapshotted the farm too early.

No implementation divergence from PRD.md was found at any of the four sites, and no PRD wording was narrowed.

Orchestrator verification: `PRD_FINALIZED.md` exists (105,903 bytes vs PRD.md's 105,712); `diff` shows exactly one changed line (line 333, the §3.9 royalty-chain paragraph), matching the reported single edit.

## Step 9: Complete PRD — 2026-09-05T17:59:40.721082653Z

Run as **three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`** rather than a single scan, because one agent cannot exhaustively walk a 3,646-line implementation in one context and a single-pass Step 9 tends to return a near-identical file (i.e. the scan never really ran). Pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying and edited in place.

**Partition:** pass 1 = `app.py`, `auth.py`, `enums.py`, `envelope.py`, `errors.py`, `ladder.py`, `store.py`, `validate.py`, `routes/setup.py`. Pass 2 = `routes/control.py`, `routes/planning.py`, `calc.py`. Pass 3 = `routes/major.py`, `routes/commercial.py`, `svc.py`.

**Cumulative size:** `PRD_FINALIZED.md` 465 lines / 105,903 chars -> `PRD_COMPLETED.md` 465 lines / 121,485 chars (**+15,582 chars, +14.7%**), 0 line delta — every one of the 69 edits was an in-paragraph insert/revision or a table-row rewrite. No new sections, no new paragraphs.

**Totals: 69 edits — 54 ambiguity-pins, 15 mismatch-revisions.**

### Pass 1 (core + setup) — 22 edits: 18 ambiguity-pins, 4 mismatch-revisions
- §2.1 — revise — ambiguity — a header carrying only whitespace counts as empty for `ERR_UNAUTHENTICATED` — `auth.py:26`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `envelope.py:13,17`
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, so responses without an intervening clock advance share it — `envelope.py:20-24`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` also `ERR_INVALID_REQUEST`; `offset` has no upper bound and over-range yields an empty page with `has_more` false — `envelope.py:92-112,72`
- §2.3 — insert — ambiguity — `created_at` ties break by ascending insertion order — `store.py:94`
- §2.3 — insert — ambiguity — every filter's query-param name is its field name, matched by exact equality; enum filters accept any declared member else `ERR_INVALID_REQUEST`; boolean filters accept `true/false/1/0` any case; undeclared params ignored — `envelope.py:115-152` (verified against all 15 `listing()` call sites)
- §2.6 — insert — ambiguity — decimal fields serialize as JSON floats, so trailing zeros are not preserved — `envelope.py:27-34`
- §2.4 — insert — ambiguity — a supplied instant with >3 fractional digits is retained sub-millisecond for comparisons but rendered truncated (not rounded) to 3 — `validate.py:49`, `store.py:41-49`
- §2.4 — revise — ambiguity — the clock endpoint accepts a backwards move and answers 200 with `data` = `{current_utc}`, not a resource — `routes/setup.py:21-27`
- §2.8 rung 5 — revise — ambiguity — body must be a JSON object; integer fields reject fractional/boolean, decimal fields reject numeric strings; `+00:00`/`-00:00`/`+0000` accepted as `Z`, non-zero offsets rejected; explicit null on an optional field = omission; undeclared body fields ignored — `validate.py:29-39,42-62,96-128,165-179`
- §2.8 — insert — ambiguity — uniqueness violations yield `ERR_INVALID_REQUEST` but are compared only after path + body-reference resolution — `ladder.py:75-79`
- §2.9 — insert — ambiguity — unrouted path and undeclared method both answer `ERR_PATH_RESOURCE_NOT_FOUND`/404; trailing slash tolerated — `app.py:22,34-41`
- §2.9 — revise — **mismatch** — body-FK list corrected: `fault_code_rule_id` is never a body input; added `wind_farm_id`, `work_order_id`, and the `fault_code` -> rule resolution — `ladder.py:37-46`
- §2.12 — insert — **mismatch** — a pure recomputation cascade landing on the value already held leaves the row entirely untouched (no `updated_at`, no `version`), scoped to the four `DB.apply` projections — `store.py:103-117`
- §3.1 — revise — ambiguity — `region_code` "uppercase" means unchanged-by-uppercasing; `grid_operator_code` min length 1; farm `name` need not be unique — `routes/setup.py:36-38`
- §3.1 — insert — ambiguity — duplicate `certifications` members are accepted, collapsed, first-occurrence order preserved — `routes/setup.py:218-221`
- §4 intro — revise — **mismatch** — role rejection is `ERR_UNAUTHORIZED`; `ERR_ROLE_NOT_PERMITTED` does not exist in the catalogue — `auth.py:31`, `errors.py:9`
- §4 table (5 rows) — revise — **mismatch**/ambiguity — filter params named exactly for farms, turbine-models, turbines, fault-code-rules, crews — `routes/setup.py:74-76,113-117,182-191,245-252,287-294`

### Pass 2 (control + planning + calc) — 21 edits: 14 ambiguity-pins, 7 mismatch-revisions
- §2.6 — revise — **mismatch** — dropped the false "Operating-hour and crew-hour figures carry one decimal place"; hours/downtime are unrounded (`rhu(` is only ever called with places 2 or 4) — `calc.py:71-108`, `control.py:52-60`
- §2.8 rung 11 — revise — **mismatch** — "five operations" -> the actual seven `ERR_TURBINE_DECOMMISSIONED` sites, adding work-order submission and curtailment activation — `planning.py:240-244`, `commercial.py:297-301`
- §3.1 — revise — ambiguity — decommission requires a non-blank `decommission_reason` — `control.py:71`
- §3.1 — insert — ambiguity — the decommission curtailment cascade is bare state moves: released orders keep `curtailed_hours`/`lost_energy_kwh` at 0, `effective_power_limit_kw` left as-is, no projection/rescore fires — `control.py:83-101`
- §3.2 — insert — ambiguity — the three telemetry figures must be >=0; an all-zero post is accepted and still bumps `version` — `control.py:36-39,62`
- §3.2 — insert — ambiguity — the telemetry cascade stops at `live_projection`; no work order is rescored even if `at_risk_flag` flips — `control.py:63`
- §3.2 — insert — ambiguity — `downtime_hours` is a signed difference, never floored at 0 — `svc.py:258`
- §3.3 — insert — ambiguity — a linked event/finding in a non-eligible state gives `ERR_INVALID_STATE` *after* the decommissioning gate; none of the three links must belong to the named turbine — `planning.py:170-205`
- §3.3 — insert — ambiguity — the priority-score age term is capped at 1.0 but not floored at 0.0 — `calc.py:118-140`
- §3.3 — revise — ambiguity — request-revision requires a non-blank `revision_note` — `planning.py:284`
- §3.4 — insert — ambiguity — an `OFF_ROTATION` crew gets `ERR_INVALID_STATE`, after the certification gate and before the temporal conflicts — `planning.py:341-344`
- §3.4 — revise — ambiguity — either a crew rostered elsewhere or a window recorded against another farm yields `ERR_CREW_FARM_MISMATCH` — `planning.py:360-368`
- §3.4 — revise — ambiguity — **hand-off** — scheduling writes crew `status = ON_SHIFT` as a direct write that advances `version` even when already `ON_SHIFT` — `planning.py:376`
- §3.5 — insert — ambiguity — start refuses a turbine in any other availability state with `ERR_INVALID_STATE`, after the force-stop interlock — `planning.py:420-432`
- §3.5 — revise — ambiguity — **hand-off** — start's re-assertion of `ON_SHIFT` goes through the dirty-checking write, is always a no-op, and leaves the crew row untouched — `planning.py:436`
- §3.5 — insert — ambiguity — omitted `actual_hours` leaves it null and `labor_cost_cents` 0; a zero labour cost posts nothing to the site ledger — `planning.py:470-486`
- §3.5 — insert — ambiguity — a `FAULT_DISPATCH` completion also clears the turbine's `active_fault_code` to null — `planning.py:497`
- §3.5 — revise — **mismatch** — cancel: non-blank `cancellation_reason`; replacement cancellations run the full §3.7 cascade; **the window expires** `CONSUMED -> EXPIRED` when the decrement hits 0 (PRD had claimed unchanged); the four reservation fields are left standing, unlike the revision back-edge — `planning.py:520-554`
- §3.9 — insert — ambiguity — `time_based_availability_pct` is not floored at 0 — `calc.py:206-232`
- §4 table (4 rows) — revise — **mismatch** — corrected filter sets for fault-events, weather-windows, work-orders lists and the cancel row's admissible states — `control.py:158-166`, `planning.py:96-104,140-152,520-527`

### Pass 3 (major + commercial + svc) — 26 edits: 22 ambiguity-pins, 4 mismatch-revisions
- §3.1 — revise — **mismatch** — `landowner_budget_cap_cents` is a ceiling on the farm's `landowner_payable_cents`, not on a sum of settlement inputs; drafts consume no headroom, approval consumes it, void returns it — `commercial.py:389-396`
- §3.7 — insert — ambiguity — `part_number` non-blank, 1-60 chars — `major.py:127`
- §3.7 — insert — ambiguity — stock-status tests read in order, so `quantity_on_hand == 0` is `OUT_OF_STOCK` even when `reorder_point == 0`; `quantity_received` strictly > 0 — `svc.py:100-109`, `major.py:181`
- §3.7 — insert — ambiguity — demobilization blocked by a replacement outside `EXECUTED`/`CLOSED`/`CANCELLED` yields `ERR_INVALID_STATE` — `major.py:112`
- §3.7 — insert — ambiguity — a non-`MAJOR_COMPONENT` parent yields `ERR_INVALID_STATE`; the parent's own `state` is never examined — `major.py:204-208`
- §3.7 — insert — ambiguity — `uptower_labor_hours` stays null when omitted — `major.py:199`
- §3.7 — insert — ambiguity — a `DEMOBILIZED`/`CANCELLED` mobilization refuses reservation; the heavy-lift `crane_class` check fires after the crane-to-farm match — `major.py:271-274,292-299`
- §3.7 — insert — ambiguity — `ERR_UPTOWER_NOT_PERMITTED` covers either failing condition; the plan-uptower write bumps `version` but does not rescore `priority_score`, and writes nothing when `uptower_labor_hours` is null — `major.py:323-344`
- §3.7 — revise — **mismatch** — crane span dates are every UTC date whose own `00:00Z` falls in `[start, end)` (leading partial excluded, trailing included) — `svc.py:324` via `calc.py:127`
- §3.7 — insert — ambiguity — the workable-day gate runs only on reservation; a cancellation reprice never re-tests it — `major.py:278-283`
- §3.7 — insert — ambiguity — the waterfall rewrites `allocated_crane_cost_cents` on `EXECUTED`/`CLOSED` members too, with no compensating ledger posting — `svc.py:362-376`
- §3.7 — insert — ambiguity — waterfall remainder goes to the first member by `created_at`, with §2.3's insertion-order tie-break — `calc.py:207-228`
- §3.7 — insert — ambiguity — a zero-value crane or up-tower spend posting leaves the farm row untouched — `svc.py:126-131`
- §3.7 — insert — ambiguity — replacement `cancellation_reason` is required non-blank but persisted nowhere — `major.py:394`
- §3.7 — insert — ambiguity — cancellation keeps `estimated_lift_hours` and never reverses the `uptower_labor_hours` already added to the parent — `svc.py:491-494`
- §3.7 — insert — ambiguity — hop 3 reaches a mobilization only from `CRANE_RESERVED`; the no-survivors rewrite is partial, leaving `lift_days`, `standby_days`, `subtotal_cents`, `volume_credit_cents` stale — `svc.py:504-517`
- §3.7 — revise — **mismatch** — hop 4 nulls all four reservation fields and the §3.3 revision bound is not consulted, so `revision_round` may pass 3 — `svc.py:525-534`
- §3.8 — insert — ambiguity — `released_at` is unconstrained, so signed `curtailed_hours` may be negative — `commercial.py:329-343`
- §3.8 — revise — **mismatch** — the two-hop propagation runs on every release, compensable or not — `commercial.py:340-345`, `svc.py:219-222`
- §3.9 — insert — ambiguity — a premature settle yields `ERR_INVALID_STATE`; settlement writes only the three figures — `commercial.py:193-206`
- §3.9 — insert — ambiguity — live projection never refuses: a zero denominator writes shortfall `0.0000` and `at_risk_flag` false instead of raising `ERR_NO_TURBINES_IN_SERVICE` — `svc.py:135-173`
- §3.9 — insert — ambiguity — approval and the symmetric void always write the farm row, bumping `version` even when all four amounts are 0 — `svc.py:464-480`
- §3.9 — insert — ambiguity — `parcel_code` non-blank, 1-40 chars — `commercial.py:355`
- §4 — revise — ambiguity — crane-mobilizations list row names `wind_farm_id`, `state`, `crane_class` — `major.py:88-96`
- §4 — revise — ambiguity — six more list rows name their exact filter fields (spare-parts, component-replacements, blade-damages, service-agreements, curtailment-orders incl. `compensable`, landowner-settlements) — `major.py:168-175,249-258`, `commercial.py:79-88,173-181,274-283,440-449`
- §4 — revise — **mismatch** — component-replacement cancel row now reads "PLANNED, CRANE_RESERVED or UPTOWER_READY" — `major.py:396`

### Cross-pass coordination
Pass 1 handed pass 2 two items (the crew-status version-bump asymmetry between scheduling and start; the unenforced one-decimal-hours claim in §2.6), both resolved. Pass 2 handed pass 3 two items (`live_projection`'s zero-denominator corner; the curtailment-order `compensable` filter row), both resolved. Pass 2 had to touch one line in pass 3's territory (`commercial.py:299`) to avoid leaving a false enumeration in the §2.8 rung-11 list, and told pass 3 not to re-add it — pass 3 confirmed it did not. Pass 3 narrowly corrected one inherited §3.1 sentence that was wrong about `commercial.py`'s headroom gate. Step 8's §3.9 `deemed_kwh` span pin survived all three passes intact.

### Orchestrator verification
- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (70 changed lines, +15,582 chars) — the scan demonstrably ran, in contrast to the known single-pass failure mode.
- Integrity: all five top-level sections present; §4 table = 75 pipe lines (header + separator + **73 endpoint rows**); §5 table = **41 error rows**; file ends on the complete final row `| ERR_NO_TURBINES_IN_SERVICE | 422 |`.
- `find` over `workspace/implementation` for `*.py` newer than `results.1.json` returns nothing: no implementation file was modified after the clean 8-round sweep, so the recorded 8x 86/86 result still describes the shipped code.

Pipeline complete.

