## Step 1: Create task directory — 2026-09-04T18:17:39.807408882Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2767_vineyard_management_custom_farming and its workspace/ subdirectory. Index 2767 pre-assigned by the invoking pipeline; no index scan performed.


## Step 2: Generate scaffold — 2026-09-04T19:56:05.503592012Z

All three scaffold artifacts are complete and lint-clean.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2767_vineyard_management_custom_farming/`):

| File | Lines | Content |
|---|---|---|
| `SCAFFOLD.yaml` | 2981 | §1.0–§1.7 only (contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2619 | single key `scaffold_difficulty_design`, 9 rule groups |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5230 | single key `scaffold_corner_design`, 9 sections |

**SCAFFOLD.yaml counts:** 12 entities, 48 endpoints, 8 state machines (incl. the parallel WorkOrder execution/payroll axes), 16 calculations, 50 ordered validations, 54 errors, 7 roles, 2 concurrency rules. `api_prefix: "/"`, `difficulty_level: expert_plus`, `role_model: segregation_of_duties`, `consistency_model: immediate`, complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

**§1.8 (difficulty):** 23 instances covering all nine §0.5 rules (3/3/2/2/3/3/3/2/2).

**§1.9 (corner):** 96 instances — 81 full test recipes plus 15 `excluded_because` stubs that cite the §1.8 instance already covering the corner. Per section: entities 13, state_machines 22, calculations 18, validations 20, endpoints 4, errors 3, rbac 8, complexity layers 7, consistency model 1.

**Verification run:**
```
Coverage
  §1.5 endpoints declared:    48
  §1.1 entities declared:     12
  §1.8 instances scanned:     23
  §1.9 instances scanned:     81
  Calls scanned (§1.8+§1.9):  1137

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional checks: all 119 instance names unique across the two design files; every design file parses with PyYAML; forbidden concurrency vocabulary absent (one stray "simultaneously" in the difficulty file was rewritten to "at once"); the scenario key holds the 2767 paragraph verbatim with no difficulty directive; no sibling task directory was read and nothing outside this task dir was touched.

Two fixes were needed during the final lint pass: `$.data.actual_start` captures on `POST /work-orders/{id}/start` were unresolvable — the §1.1 field is `started_at` — corrected in both affected instances, and a dangling ground `calculations.block_harvest_tolerance_ceiling` (no such calculation) was repointed to `entities.Block.fields.governing_estimate_tons`.

Orchestrator verification: all three files present, parse under PyYAML, and `grep -rn "harder than expert level"` over the task dir returns nothing — the difficulty directive did not leak into the scaffold.

## Step 3: Copy shared files — 2026-09-04T19:56:05.524042819Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to /home/ubuntu/github/CodingPRD/tasks/task_2767_vineyard_management_custom_farming/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T20:09:38.867128039Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **401 lines**, written incrementally (one `Write` + 8 `cat >>` heredoc appends + §2.2 copied verbatim from the skill's canonical file).

**Section list:** 1 Introduction · 2 Global Specifications (2.1 RBAC · 2.2 API Response Structure verbatim · 2.3 Pagination · 2.4 Resource Identity, Versioning and the Logical Clock · 2.5 Path Resolution and Reference Integrity Order · 2.6 Validation Precedence · 2.7 Money, Tonnage and Water Precision · 2.8 Optimistic Concurrency on Blocks and Delivery Windows · 2.9 Segregation of Duties · 2.10 Ledger Propagation and Cascade Discipline) · 3 Business Logic (3.1 Ranch Registration and Block Inventory · 3.2 Custom-Farming Agreements · 3.3 The Annual Farming Plan · 3.4 Crews, Work Orders and the Two Independent Axes of a Task · 3.5 Irrigation Scheduling and Deficit Water Accounting · 3.6 Pest Scouting, Spray Applications and Interval Compliance · 3.7 Yield Estimation and the Block Harvest Ledger · 3.8 Winery Delivery Windows, Load Booking and Weigh-Tag Settlement · 3.9 Period Settlement and Contract Closure) · 4 Endpoint Definitions · 5 Error Code Catalogue.

**Field coverage check:** entities[].fields 160/160; endpoints[].request_body 104/104; query_params 19/19; path_params 1/1; settle-period response fields 12/12. All 176 unique identifiers verified as exact standalone backticked tokens. Status: PASS.

**Rule coverage check:** 50/50 prioritised validations expressed (§2.6 renders the full ascending ladder with intra-rung sub-order); 2/2 OCC rejections; 8 machines / 19 transitions fully expressed; 16/16 calculations with constants, evaluation order and precision; all 54 error IDs appear in §2/§3; 48/48 endpoint side_effects/applies_to expressed (ERR_BLOCK_REMOVED's 12-endpoint scope and ERR_CREW_INACTIVE's 4-endpoint scope enumerated in full); 12 entities / 160 fields reconstructible (common_fields:false handled explicitly for PestObservation and YieldEstimate); 5/5 sibling-branch symmetry groups clean. Status: PASS.

**Path purity check (§3 only):** 994 backtick tokens scanned (320 unique); 0 starting with `/`; 0 bare HTTP-method tokens; 0 method+path combined tokens. Status: PASS.

Additional checks: §2.2 diffs byte-identical against the canonical section file; zero fuzzy/approximating words; zero operator-syntax leakage; §4 has exactly 48 endpoint rows; §5 has exactly 54 error rows.

**Tail verification:** `tail` ends on `| \`ERR_HARVEST_EXCEEDS_ESTIMATE\` | 409 |` — the final row of the §5 table, a complete section boundary. No truncation.

**Issue flagged by the generator:** SCAFFOLD.yaml referenced `ACTION_THRESHOLD_PCT` twice (the `PestObservation.action_threshold_pct` field and the pest-observation create side effect) but never supplied the per-pest numbers, so the generator correctly declined to invent them and the PRD described only the mechanism.

**Orchestrator repair (decided autonomously, no user available).** An undefined constant table makes `action_threshold_pct` and `exceeds_threshold` unimplementable in any determinate way: a PRD-only implementer cannot produce the field at all, and any test asserting a concrete threshold would have to be deleted in Step 7 as PRD-silent, costing several §1.9 pest-path instances. Rather than lose that coverage, the orchestrator pinned the table in both places — SCAFFOLD.yaml's `action_threshold_pct` field description and one clause inside the existing §3.6 sentence in PRD.md — as: POWDERY_MILDEW 5.0, VINE_MEALYBUG 2.0, BOTRYTIS 3.0, LEAFHOPPER 10.0. This is a system constant (a rule the implementer must have), not a worked-example outcome, so stating it in the PRD reveals no test answer beyond what the rule itself determines. Both edits are single in-place clauses; no section was added and no other prose changed. SCAFFOLD.yaml still parses under PyYAML and PRD.md remains 401 lines.

Leak check: `grep "harder than expert" workspace/PRD.md` returns 0 matches — the difficulty directive did not reach the PRD.

## Step 6: Generate implementation — 2026-09-04T20:39:38.943417138Z

Implementation complete and smoke-verified.

## Files written — `workspace/implementation/`

| file | lines | role |
|---|---|---|
| `common.py` | 249 | response envelope (`meta`/`response_type`/`data`), `ApiError` + all 54 default messages, Decimal helpers (`D/r2/r3/dec_out`), ISO datetime formatting/parsing, id generation |
| `store.py` | 109 | the 12 in-memory dicts, logical clock (`CLOCK_DEFAULT = 2026-08-01T00:00:00Z`), `new_row/touch/base_fields/find` |
| `validate.py` | 238 | rungs 1/2/3/8: header auth, role gate, declarative field schema (`F`) with unknown-field rejection, pagination |
| `calc.py` | 220 | all 16 formula constants and the pure calculations (vine geometry, labor/burden/overtime, cancellation pay, plan budget, irrigation waterfall, yield, net tons, postures, volume tier) |
| `derive.py` | 519 | every `source: computed` roll-up (block clearances, compliance posture, governing estimate, harvest ledger, contract aggregates, plan committed cost, window committed tons) plus one serializer per entity |
| `service.py` | 273 | shared plumbing: filtering/pagination, the 11 not-found lookups, ownership/state guards, crew conflict detection, the spray-apply cascade, block direct cost, settlement statement |
| `routes_core.py` | 433 | vineyards, blocks, block-nested pest observations & yield estimates, contracts (enroll/activate/settle) |
| `routes_plans.py` | 202 | farming-plan cycle (submit / return-for-revision / approve) and crews |
| `routes_work.py` | 330 | work orders (execution x payroll axes) and irrigation events |
| `routes_spray.py` | 155 | spray recommend / apply / verify |
| `routes_harvest.py` | 286 | delivery windows, harvest loads (dispatch/receive/reject), `POST /_clock/set_current_utc` |
| `app.py` | 64 | app factory, 5 blueprints, `ApiError`/HTTPException handlers, `PORT` env (default 10000) |
| `start.sh` | 16 | executable (`-rwxrwxr-x`), guarded `pip install`, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=3.0.0` |

All 12 modules pass `python3 -m py_compile`. The URL map contains exactly the 48 endpoints listed in SCAFFOLD.yaml (Flask's `/static` route is disabled via `static_folder=None`).

## Notable design decisions
- **Validation precedence**: PRD §2.6's enumerated 20-rung ladder is treated as authoritative over §3.x prose, so e.g. `ERR_BLOCK_REMOVED` precedes `ERR_SPRAY_NOT_RECOMMENDED`/`ERR_IRRIGATION_NOT_SCHEDULED`, crew-must-be-ACTIVE is last inside rung 15, and `ERR_DUPLICATE_BLOCK_CODE` precedes `ERR_VINEYARD_MISMATCH`. Nested list endpoints call `pagination()` *before* the path-id lookup so rung 8 fires ahead of rung 9.
- **OCC**: `expected_block_version` (spray apply, 412) and `expected_delivery_window_version` (harvest-load create, 412) are checked at rungs 13/14 — after reference resolution but before every state/safety/fiscal check.
- **Cascade**: spray apply recomputes block `rei/phi_clear_at` as the max over APPLIED|VERIFIED sprays, bumps the block, then auto-cancels SCHEDULED work orders starting inside the new REI held by non-`pest_certified` crews (`cancel_reason = REENTRY_RESTRICTION`, ordered by `(_start, created_at, _seq)`), which flows into plan `committed_cost` and `budget_posture`.
- **Version bumps** follow the scaffold's explicit `side_effects` only: enroll-block bumps block+contract; receipt bumps load+block+contract+window; rejection bumps load+block+window but never the contract; plan/crew are never bumped by ledger recomputes.
- **Money**: `Decimal` + ROUND_HALF_UP throughout; per-block settlement subtotals rounded before summing (never re-rounded), unrounded overhead share and unrounded posture ratios, 3dp water, truncation for vine geometry.
- **Clock**: `store.now_utc()` never falls back to wall time; `created_at`/`updated_at` deliberately use real wall time. Event entities (PestObservation, YieldEstimate) serialize `id` + `created_at` only — no `version`/`updated_at`.
- Storage is process-local dicts, nothing seeded, nothing written to disk.

## Smoke test (`PORT=18767`, killed by its own port PID — no pattern kills)
Ran a 40-call end-to-end script covering ranch -> block -> contract enroll/activate -> plan submit/return/re-submit/approve (with the ESTABLISHING->BEARING cascade) -> crews -> work order start/complete/payroll APPROVE->PAY (and the 409 repeat) -> schedule conflict 409 -> cancel with reporting-time pay -> irrigation create + record-applied -> observation -> spray apply (412 on a stale version, then 200) with the verified cascade (uncertified order CANCELLED/`REENTRY_RESTRICTION`, certified order untouched) -> SoD 409 on verify -> clock move -> yield estimate -> delivery window -> harvest load (409 outside window, then 201) -> dispatch/receive/reject -> both settlement variants. Result: **`SMOKE OK - no unexpected statuses`**.

Hand-checked figures matched the PRD/scaffold worked references: `total_budget` 14687.50, labor 3276.75 / 3167.53, cancellation 678.48, irrigation `target 0.660 / shortfall 0.691 / refill 0.346 / gross 0.906`, `water_cost` 481.31, yield 89.84 / 7.19, `net_tons` 19.80 with incentive 891.00, `direct_cost_total` 8969.34 (CANCELLED reporting-time pay correctly excluded, unrounded overhead share included), PROVISIONAL `total_billable` 15222.70 vs FINAL 16786.40 with ACTIVE->CLOSED. Error envelopes verified for 401 (missing/bogus role), 403 (role + ClientOwner ownership), 404 (entity and unknown path), 400 (bad enum, unknown field, bad email, `limit=0`, `limit=101`), 409, 412. A fresh `start.sh` boot returns `total_count 0` for all collections and the clock back at `2026-08-01T00:00:00Z`.

`test_suite/`, `test_helpers/`, the two design YAMLs, sibling tasks and `worklog.md` were not read or touched.

## Step 5: Generate unit tests — 2026-09-04T21:49:47.780077245Z

Test generation for task 2767 is complete. Both stages are written, compiled, and audited.

## Files written (all at the TASK ROOT)

`test_helpers/` — 9 files, 2,271 lines: `__init__.py` (39), `api_client.py` (234), `api_errors.py` (122), `assertions.py` (305), `constants.py` (68), `factories.py` (377), `fixtures.py` (587), `test_users.py` (82), `types.py` (457).

`test_suite/` — `conftest.py` (55) plus 11 test modules, 4,404 lines:

| file | lines | tests |
|---|---|---|
| test_01_ranch_and_block_inventory.py | 305 | 11 |
| test_02_agreement_lifecycle.py | 277 | 10 |
| test_03_farming_plan_review.py | 273 | 9 |
| test_04_labor_costing_and_scheduling.py | 413 | 12 |
| test_05_work_order_axes.py | 390 | 13 |
| test_06_irrigation_water_accounting.py | 252 | 6 |
| test_07_pest_compliance_and_spray_cascade.py | 631 | 17 |
| test_08_yield_estimation.py | 209 | 6 |
| test_09_harvest_windows_and_loads.py | 642 | 16 |
| test_10_settlement_and_closure.py | 440 | 14 |
| test_11_validation_precedence_and_access_control.py | 572 | 15 |

**129 tests total.** The last module covers identity-before-authorisation, the 1..100 pagination band, pay-structure coherence, plan/block charging integrity, the crew capability gate, body foreign-key resolution order, the logical clock, ranch-registration RBAC, and the three `priority_pair_validation_conflict` pairs (plan-state-before-budget, PHI-before-missing-estimate, eta-containment-before-window-capacity).

## Design-index accounting (mechanically audited)

- Queue A (difficulty): **48 tests over all 23 instances**, every instance >= 2 tests.
- Queue B (corner): **81 tests over all 81 non-stub instances**, every instance >= 1 test. The **15 stubs were not translated**.
- Every test has exactly one `Design:` line as the docstring's last line; all 129 tags resolve to a real instance name (0 unknown, 0 dual-tagged, 0 untagged, 0 stub-tagged).
- **Instances skipped: 0.** Every queue-A and non-stub queue-B instance passed the PRD-first two-condition filter.
- Every docstring citation was verified by literal grep of `workspace/PRD.md` (a >=8-word contiguous fragment, whitespace-normalised): **0 failures**.
- No `skip`/`xfail`/`skipif`, no mocking/monkeypatching, no mention of "scaffold" or any scaffold section reference anywhere in `test_suite/` or `test_helpers/`.

## Design-yaml defects corrected while translating

- Non-UUID literals (`b-0000...`, `c-0000...`, `cw-0000...`, `ct-0000...`) replaced with `MISSING_UUID_A/C` from `test_helpers/constants.py`.
- `severity_index: 2.0 / 3.0` sent as the ints `2` / `3` (PRD §3.6 requires a whole number 0-5).
- Free-text `cancel_reason` replaced by the enum values `WEATHER` / `CLIENT_REQUEST`; `variety: MERLOT` replaced by `ZINFANDEL`.
- One assertion substitution in file 09: the design's "no window row created" check is unobservable because the PRD publishes no delivery-window listing endpoint, so the freshly created sane window's declared opening state (committed 0.00 / remaining 40.00 / `OPEN` / version 1) is asserted instead.
- Pruned one unused import (`validate_success`) from `test_04`; pyflakes is now clean across `test_suite/`.

## Placement verification

`ls -la` confirms the 9 helper files and 12 suite files at the task root; `ls workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation` — **no stray `test_helpers/` or `test_suite/` copies**. `python3 -m compileall` passes on both directories, `__pycache__` removed. `workspace/implementation/` and `worklog.md` were never read or written.

Orchestrator note: Steps 5 and 6 ran concurrently as required; the impl generator finished while `test_suite/` was still empty, so it had no way to read the measuring instrument. Placement re-verified independently by the orchestrator — both test dirs sit at the task root, nothing stray under `workspace/`.

## Step 7: Run tests and iterate — 2026-09-04T22:11:07.934995825Z

Clean sweep. Done.

**Iterations run:** 2

**Tests deleted:** none. All 129 tests survived STEP 1 (PRD coverage + unique derivability) — the entire failure set traced to a single test_helpers defect, not to PRD silence.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — `block_payload_b14`, `block_payload_b16`, `hourly_crew_payload`: these three derived factories were implemented by calling their base factory with *explicit keyword arguments plus* `**overrides`, e.g. `block_payload(vineyard_id, rootstock="ROOTSTOCK_SO4", ..., **overrides)`. Any caller overriding one of the hard-coded keys therefore raised `TypeError: block_payload() got multiple values for keyword argument 'rootstock'` before a single HTTP request was issued. Refactored to extract `_block_defaults()` / `_crew_defaults()` and layer the variant specifics and then the caller's overrides through the existing `_merge()`, so overrides win and the `OMIT` sentinel still removes a key (verified for `crew_payload(crew_status=OMIT)` and `block_payload(variety=OMIT)`, the suite's only two OMIT users).

**Fixes applied to `implementation/`:** none. No implementation defect was found — the 11 failures were all `TypeError` in the fixture layer, identical in all 8 rounds of iteration 1, and every one of the affected tests' expected figures checks out against the PRD arithmetic (spot-verified: 43560/(7x9)=691 truncated and 691x3.6=2487 truncated per §3.1/§2.7; the 1-worker HOURLY crew at 100.00/hr over 6.4 h giving gross 640.00, burden 182.40, cost 822.40, and over 8.0 h giving exactly 1028.00 against a 1028.00 budget -> ratio 1.00 -> `AT_RISK` per §3.3/§3.4).

**Final sweep evidence** (all files under `workspace/implementation/`):

| round | passed/total |
| --- | --- |
| results.1.json | 129/129 |
| results.2.json | 129/129 |
| results.3.json | 129/129 |
| results.4.json | 129/129 |
| results.5.json | 129/129 |
| results.6.json | 129/129 |
| results.7.json | 129/129 |
| results.8.json | 129/129 |

Zero failures, zero errors, zero skips in every round. Iteration 1 for contrast was a flat 118/129 in all 8 rounds — the defect was fully deterministic, so no flakiness was masked. `worklog.md` was not touched; the only modified artifact is `test_helpers/factories.py`, and no test dirs leaked into `workspace/`.

Orchestrator verification: re-read all eight `results.$i.json` directly — every round reports 129/129, so the clean sweep is confirmed against the artifacts rather than only against the subagent's report.

Orchestrator decision on the Step 8 skip condition: Step 7 ran 2 iterations with 1 `test_helpers/` fix, so the skip condition (zero iterations beyond baseline) is not literally met and Step 8 will be run. Its expected yield is nil, however — the single fix was a Python `TypeError` in a factory's keyword layering, which reveals no PRD silence and no PRD/impl mismatch. A byte-identical `PRD_FINALIZED.md` is therefore the legitimate outcome here, and the substantive alignment work falls to Step 9's full scan.

## Step 8: Finalize PRD — 2026-09-04T22:19:03.892912666Z

**Result: `workspace/PRD_FINALIZED.md` created as a byte-identical copy of `PRD.md` — zero edits, which is the correct outcome here.**

Line counts: PRD.md 401 lines, PRD_FINALIZED.md 401 lines, delta 0.00% (md5 identical for both).

Change list: none.

Why zero edits is correct (traced strictly through `<step_7_diff>`):

The single Step 7 fix was in `test_helpers/factories.py` (`block_payload_b14`, `block_payload_b16`, `hourly_crew_payload`). It is a pure Python kwargs-layering defect: the derived factories passed hard-coded keywords *and* `**overrides` into the base factory, so any caller overriding one of those keys raised `TypeError: got multiple values for keyword argument` before an HTTP request was ever made. The refactor into `_block_defaults()` / `_crew_defaults()` + `_merge()` changes only how the dict is assembled, not what the server is asked to do or what is asserted. No implementation file was touched (impl mtimes all <= 20:30; factories fixed at 22:01), and no test was deleted or weakened per the diff.

The affected callers' expectations are all pinned by existing PRD prose, so there is nothing to pin:

- `fx.create_block_b16(..., rootstock=...)` / `create_block_b14(..., acres=4.0)` — geometry truncation 43560/(7x9)=691 and 691x3.6=2487; `implementation/calc.py:68-72` uses `int(...)` twice, exactly PRD §3.1/§2.7 ("discarding any fraction", "truncate rather than round"). Enum sets, initial `ESTABLISHING`/`CLEAR`/`NOT_ESTIMATED` and null contract fields are all enumerated in §3.1.
- `crew_payload(crew_status=OMIT)` — `routes_plans.py:192` `body.get("crew_status", "ACTIVE")`; PRD §3.4 already states the default explicitly.
- `block_payload(variety=OMIT)` — missing required field -> `ERR_INVALID_REQUEST`; PRD §2.6 rung 3.
- `create_hourly_crew(crew_size=1, base_hourly_rate=100.00, ...)` labor figures 640.00/182.40/822.40 and 1028.00 — `calc.py:80-97` splits at 8 h, applies the 1.5x overtime multiplier, the 16.50 worker-hour floor, rounds gross first, then 28.50% burden off the rounded gross; PRD §3.4 and §2.7 spell out every one of those steps including the round-then-burden ordering.
- Ratio exactly 1.00 -> `AT_RISK` — `calc.py:121-129` compares unrounded `committed <= total*1.00`, and handles `total_budget == 0` separately; PRD §3.3 states both edges inclusive, the exact-1.00 worked example, and the zero-budget carve-out.
- Budget gate equality — `routes_work.py:66-70` `r2(committed + estimated) > total_budget`; PRD §3.4 "rounded to two decimal places, must not exceed ... Equality is permitted."
- `create_hourly_crew(crew_status="INACTIVE")` gating — `service.py:135` `ERR_CREW_INACTIVE`; PRD §3.4/§2.6 rung 15.

Per the NO-NEW-MISMATCH rule the mandatory pre-edit enumeration was run for each candidate subject before deciding not to edit (subject -> paths read/grepped): vine geometry -> `calc.py:vine_geometry` + block-create callsite; crew registration defaults/pay coherence -> `routes_plans.py:156-195`, `derive.py:318-325`, `service.py:135`, grep of every `piece_rate_per_vine`/`crew_status` reference; labor cost -> `calc.py:labor_cost`/`cancellation_pay` and both variant callsites in `routes_work.py`; budget posture/gate -> `calc.py:budget_posture`, `derive.plan_committed_cost` callsite, `routes_work.py:66-70`; body-shape rejection -> `routes_plans.py` schema `F(...)` declarations. In every case the existing PRD sentence already describes the impl behavior verbatim, so no wording adjustment was needed and no edit was warranted.

Incidental observation, deliberately **not** acted on (out of Step 8 scope, flagged for Step 9): `calc.py:200-207` returns `FULL` for a zero-`capacity_tons` window and `calc.py:184-188` returns `0.00` tons/acre for zero `acres` — both PRD-silent but unreachable, since `capacity_tons` and `acres` are validated strictly greater than zero.

Orchestrator note: a byte-identical `PRD_FINALIZED.md` is legitimate at Step 8 when Step 7 made no implementation fixes; md5 equality re-verified by the orchestrator. Step 9 must NOT come out identical — it runs a full PRD-vs-impl scan and will be executed as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 performs the `cp`; passes 2 and 3 must not).

## Step 9: Complete PRD — 2026-09-04T22:42:25.243919117Z

Orchestrator decision: Step 9 was executed as **three sequential passes partitioned by implementation module**, all editing one shared `workspace/PRD_COMPLETED.md`. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to `cp` or `Write` the file and made targeted `Edit` calls only. A single-pass scan over a 12-module implementation reliably degrades into a shallow skim; partitioning guarantees every module is walked by an agent that has room to read it.

**Final artifact:** `workspace/PRD_COMPLETED.md` — 401 lines, md5 `4728f47f4f5ae2666228fa0dccec1c7f`, **39 changed lines vs `PRD_FINALIZED.md`** (md5 `7959387b...`), ends at `| ERR_HARVEST_EXCEEDS_ESTIMATE | 409 |`. Totals across the three passes: **36 ambiguity-pins, 4 mismatch-revisions**. No new sections, no whole-file rewrite.

### Pass 1 — common.py, store.py, validate.py, calc.py, app.py (7 pins, 3 mismatches)

- §2 preamble — insert — ambiguity — every collection starts empty on a fresh server; nothing seeded — store.py:15-41
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-letter/digit characters — common.py:214-218
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the real wall clock, never the logical clock — common.py:221-225
- §2.3 — insert — ambiguity — a pagination value is an optionally signed digit run, whitespace-padded accepted, `25.0`/empty/non-digit rejected — validate.py:206-215
- §2.4 — revise — ambiguity — `created_at`/`updated_at` come from the real wall clock at millisecond resolution (not the logical clock) and are strictly increasing, which totalises `created_at` ordering and its tie-breaks — common.py:67-81, store.py:73-91
- §2.4 — insert — ambiguity — three pins at once: the clock endpoint echoes the submitted `current_utc` verbatim; every instant-valued input accepts optional seconds/fraction and `Z`/numeric-offset/no-offset, naive read as UTC, offsets converted before comparison, stored field echoed as written; logical-clock-stamped and derived instants render to whole seconds absent a sub-second component and to exactly three fractional digits when present — common.py:58-118, routes_harvest.py:286
- §2.6 rung 3 — revise — **mismatch** — PRD listed "no unknown fields" last, but impl rejects unknown keys before any presence/type check; also pinned: number rejects quoted numeric strings and booleans, integer additionally rejects JSON floats (`3.0`), absent/empty body equals empty JSON object (empty-schema endpoints still reject unknown keys), explicit `null` on an optional field equals absent while on a required field it is `ERR_INVALID_REQUEST` — validate.py:77-198
- §2.7 — insert — ambiguity — decimal figures serialise as bare JSON numbers in shortest form, so trailing zeros do not survive (`12.40` -> `12.4`) — common.py:47-51
- §3.6 — revise — **mismatch** — PRD claimed the two clearance instants are rendered to whole seconds unconditionally; `fmt_dt` does so only when the instant has no sub-second component, and `applied_at` inherits sub-second precision from the clock — common.py:90-102
- §5 preamble — revise — **mismatch** — PRD claimed every failure carries a catalogued id; app.py also emits `ERR_NOT_FOUND` (404) for an unrouted path and `ERR_METHOD_NOT_ALLOWED` (405) for an undeclared method, and routing is trailing-slash-insensitive — app.py:23,36-48

Left unedited: all 16 `calc.py` constants and every formula are already uniquely pinned — all eight PRD worked examples were re-derived against impl and reproduce exactly. Unreachable guards (zero-`acres` yield, zero-`capacity_tons` window posture, the `ERR_INTERNAL` 500 and 415 handlers) were deliberately not documented, since prose would imply behaviour the API cannot exhibit. `getcontext().prec = 60` and `store.created_key`'s `_seq` component have no observable effect beyond what is already pinned. The 54 default error message strings stay unpinned — PRD requires only "a human-readable explanation".

### Pass 2 — routes_core.py, routes_plans.py, service.py (14 pins, 0 mismatches)

- §2.1 — insert — ambiguity — no read endpoint is crew-ownership-gated; a `CrewSupervisor` may read any crew/block/order/event/window/load — service.py:114 and every GET callsite
- §2.3 — insert — ambiguity — the two business-chronology listings tie-break by `created_at` descending — routes_core.py:205,278
- §2.3 — insert — ambiguity — filters are exact textual matches, never validated against an enum or existence (unmatched value yields an empty page, not 400), and undocumented query params are ignored — service.py:21-37
- §3.1 — revise — ambiguity — `client_contact_email` is non-blank with no maximum length — routes_core.py:36
- §3.1 — insert — ambiguity — the `block_code` uniqueness scan spans all `farming_status` values, so a `REMOVED` block never frees its code — routes_core.py:98-100
- §3.2 — revise — ambiguity — `contracted_acres` and `per_acre_fee_override` are each zero-or-more, and enrollment is not gated on `farming_status` — routes_core.py:353-377
- §3.2 — revise — ambiguity — `client_signature_name` is a non-blank string of 1 to 160 characters — routes_core.py:382
- §3.3 — insert — ambiguity — the three plan notes are at most 1000 chars (optional ones blank-able, `revision_note` non-blank) and none is persisted or serialized — routes_plans.py:84,104,124
- §3.4 — revise — ambiguity — `pest_certified` is a required boolean with no default — routes_plans.py:164
- §3.6 — insert — ambiguity — filing a pest observation does not increment the block's `version` — routes_core.py:173-194
- §3.7 — revise — ambiguity — `berries_per_cluster` is a whole number (a JSON float is rejected) — routes_core.py:218
- §3.9 — insert — ambiguity — `period_end_date` filters nothing in the roll-up; it only feeds the closure test — service.py:210-262
- §3.9 — insert — ambiguity — a zero `total_contracted_acres` makes each overhead share 0.00 rather than undefined — service.py:228-231
- §3.9 — revise — ambiguity — the contract listing is auto-scoped to a `ClientOwner`'s own ranch, and a foreign `vineyard_id` is 403 `ERR_VINEYARD_OWNERSHIP_REQUIRED`, not an empty page — routes_core.py:338-344

Left unedited: role lists for all 22 endpoints in this partition match §4 exactly; every in-handler rung-order decision is already pinned by the §2.6 ladder; return-for-revision's absence of an `ERR_BLOCK_REMOVED` gate is pinned by §3.1's positive enumeration; unreachable guards not documented.

### Pass 3 — routes_work.py, routes_spray.py, routes_harvest.py, derive.py (15 pins, 1 mismatch)

- §2.8 — insert — ambiguity — `expected_block_version` / `expected_delivery_window_version` are whole numbers of at least 1 — routes_spray.py:100, routes_harvest.py:73
- §2.10 — insert — ambiguity — recomputing a roll-up is not itself a mutation: a `FarmingPlan`'s `version` moves only on submit/return/approve, and a `LaborCrew` and a `Vineyard` are never mutated at all — verified by grepping every `store.touch` callsite
- §3.1 — insert — ambiguity — `vine_spacing_ft`/`row_spacing_ft` stored unquantised and echoed as bare numbers (`5` -> `5.0`), `vines_per_acre`/`vine_count` as bare integers — derive.py:148-153 (pass-2 hand-off 2)
- §3.4 — insert — ambiguity — `task_capabilities` echoed in the exact order supplied, not normalised or sorted — derive.py:323
- §3.4 — insert — ambiguity — exactly four operations consult `crew_status` (work-order schedule/start, load book/dispatch); complete, cancel, payroll and all irrigation operations do not — routes_work.py:45,130,158-218,314-321, routes_harvest.py:98,188
- §3.4 — revise — ambiguity — `actual_vines` zero or more, `actual_hours` strictly greater than zero; completion consults neither `crew_status` nor `farming_status` — routes_work.py:145-159
- §3.4 — insert — ambiguity — `payroll_note` at most 1,000 chars, may be blank, validated then discarded — routes_work.py:198
- §3.5 — insert — ambiguity — `applied_inches` is zero or more — routes_work.py:309
- §3.6 — insert — ambiguity — the threshold test is the only coherence check on `pest_observation_id`; the cited observation need not belong to the treated block — routes_spray.py:39-50
- §3.6 — revise — ambiguity — `applicator_license_no` non-blank 1-120 chars, `wind_speed_mph` zero or more — routes_spray.py:98-99
- §3.6 — revise — **mismatch** — the apply cascade's closing claim that "every one of those rows carries an incremented `version`" was false: only the spray record, the block and each auto-cancelled work order are bumped; the affected crews and the plan keep their existing `version` — routes_spray.py:131, service.py:180-202
- §3.6 — insert — ambiguity — `verification_note` at most 1,000 chars, may be blank, discarded rather than persisted — routes_spray.py:137
- §3.7 — insert — ambiguity — a filed estimate always emits all four method-conditional keys, the unused ones as null; §2.6's absence rules bind the request body only — derive.py:417-432 (pass-2 hand-off 1)
- §3.8 — revise — ambiguity — the exact eleven-key null-at-booking set spelled out — derive.py:498-518, routes_harvest.py:136-148 (pass-2 hand-off 3)
- §3.8 — revise — ambiguity — `gross_tons_at_dispatch` is zero or more — routes_harvest.py:175
- §3.8 — revise/insert — ambiguity — `gross_tons`, `tare_tons`, `brix_at_receipt` each zero or more; receipt is gated on `load_status` alone, so a load in transit when its agreement closed is still received and still credits (and version-bumps) the `CLOSED` agreement — routes_harvest.py:202-247
- §3.8 — revise — ambiguity — a rejected load keeps `gross_tons`, `tare_tons`, `mog_deduct_pct`, `brix_at_receipt`, `received_at` null, and a received load keeps `rejected_at`/`rejection_reason` null — routes_harvest.py:254-267

Left unedited: ladder ordering in every handler already matches §2.6 verbatim; §3.1's `ERR_BLOCK_REMOVED` enumeration already matches all eleven `require_block_live` callsites exactly; unreachable branches (the `new_rei is None` early return, `receive_load`'s null-contract path, `management_fee_base`'s null-`contracted_acres` fallback, `governing_estimate`'s `_seq` third tie-break) deliberately undocumented; the absent `GET /delivery-windows` is correctly omitted from §4 and its 405 is covered by the generic rule pass 1 pinned.

**Orchestrator verification:** `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (md5 `4728f47f...` vs `7959387b...`, 39 changed lines) — the scan demonstrably ran. Line count still 401, document ends at the final error-catalogue row, so no pass truncated it. Step 9 edited only the PRD; `implementation/`, `test_suite/` and `test_helpers/` are untouched since the clean sweep, so the eight passing `results.$i.json` files remain valid evidence for the final artifact set.

Pipeline complete: all nine steps finished, 129/129 tests passing in all 8 rounds, `workspace/PRD_COMPLETED.md` written.
