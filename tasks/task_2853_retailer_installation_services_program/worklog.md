# Worklog — task_2853_retailer_installation_services_program

## Step 1: Create task directory — 2026-09-05T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2853_retailer_installation_services_program` and its `workspace/` subdirectory. Index 2853 was pre-assigned by the invoking command; no index scan or allocation was performed (concurrent pipelines on this host).

## Step 2 — scaffold generation (complete)
- SCAFFOLD.yaml (§1.0–§1.7): 13 entities, 11 state machines, 4 concurrency rules, 8 calculations,
  38 ordered validations, 76 endpoints, 47 errors, 6 roles. Difficulty directive stripped from `scenario`.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8): 9 rule_ids / 22 instances.
- SCAFFOLD_CORNER_DESIGN.yaml (§1.9): 9 sections / 72 instances (58 full recipes + 14 stubs deferring to §1.8).
- scaffold_lint.py: VERDICT: clean lint (879 calls scanned).

## Step 2: Generate scaffold (subagent) — 2026-09-05T09:14:00.000Z

Verbatim subagent summary:

Task 2853 scaffold is complete and lint-clean.

## Files

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2853_retailer_installation_services_program/SCAFFOLD.yaml` | 4295 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2853_retailer_installation_services_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1998 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2853_retailer_installation_services_program/SCAFFOLD_CORNER_DESIGN.yaml` | 3763 |

## SCAFFOLD.yaml (§1.0–§1.7)
13 entities, 11 state machines, 4 §1.2.1 concurrency rules, 8 calculations, 38 ordered validations, 76 endpoints, 47 error codes, 6 roles. Top-level keys are only `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key is present.

## Design indices
- §1.8 `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: 9 rule_ids / **22 instances** (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2).
- §1.9 `SCAFFOLD_CORNER_DESIGN.yaml`: 9 sections / **72 instances** = entities 13, state_machines 17, calculations 10, validations 8, endpoints 6, errors 7, rbac 3, cross_cutting_complexity_layers 7, consistency_model 1. 58 carry full `test_recipe`s; 14 are `excluded_because` stubs, every one citing a real §1.8 `rule_id / instance_name`. All 94 instance names are unique across both files.

## Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    76
  §1.1 entities declared:     13
  §1.8 instances scanned:     22
  §1.9 instances scanned:     58
  Calls scanned (§1.8+§1.9):  879

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Notes worth relaying
- Finishing work this session: `cross_cutting_complexity_layers` (one `optimistic_concurrency` instance per §1.2.1 rule, each proving stale → 412 / fresh → success and that the rejected write bumps nothing; a `rate_threshold_triggers` instance landing the composite on exactly 78.00 = PROBATION_COMPOSITE_MAX and then resetting at 80.95; stubs for `cascading_side_effects` and `dual_variant_calculation`) plus the `consistency_model` `immediate` instance asserting the write response and the immediate read are field-for-field identical.
- Two asserted composites were re-derived against `installer_scorecard` and corrected before linting: 80.10 → **83.20** (3 events) and 81.25 → **82.50** (single CSAT-1 event).
- Fixed one lint violation: a `total_count` capture off a `ServiceCategory[]` list endpoint (pagination fields are not under `$.data` for array responses) — moved to a prose assert.
- Per the known leak hazard, the line `Generate task harder than expert level!` had been copied into `scenario:` by the scaffold pass; I stripped it, so the difficulty directive cannot reach PRD.md. Re-linted clean afterwards.
- `worklog.md` updated with a Step 2 completion entry (absolute path used).
- The no-peeking constraint was honoured: no sibling `task_*/` directory was listed, read, or grepped.

Orchestrator verification: all three files present (4295 / 1998 / 3763 lines); `grep -i "harder than expert|expert level"` over all three SCAFFOLD files returns zero matches; SCAFFOLD.yaml top-level keys confirmed to exclude both design keys; workspace/ intact.

## Step 3: Copy shared files — 2026-09-05T09:14:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-09-05T09:33:00.000Z

Verbatim subagent summary:

Done. PRD complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2853_retailer_installation_services_program/workspace/PRD.md` — **485 lines**, built in 11 chunked appends (no truncation; file ends on the final `ERR_NOT_CANCELLABLE` row of the §5 table, a real section boundary).

**Section list**
- §1 Introduction
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (byte-identical paste of `section-2.2-response-structure.md`, verified by substring match) · 2.3 Pagination · 2.4 Resource Identity, Version Counters and the Logical Clock · 2.5 Money, Units, Scores and Rounding Discipline · 2.6 Stale-Version Guards on the Four Program-Critical Writes · 2.7 Flat Addressing and Reverse Discovery · 2.8 The Rejection Ladder (all 38 ranks) · 2.9 Three Independent Status Dimensions and Cascades · 2.10 Two Conservation Invariants
- §3 Business Logic & Workflows, 9 subsections: 3.1 Programme Configuration · 3.2 Building the Installer Network · 3.3 Selling the Project (frozen quote + deposit) · 3.4 The Measurement Hinge and the Change-Order Loop · 3.5 Permitting and the Jurisdiction Inspection · 3.6 Material Delivery, the Install Window and the Invoice · 3.7 Quality, Punch List, Closing and Labour Warranty · 3.8 Cancellation, the Settlement Ladder and Reinstatement · 3.9 The Scorecard, Probation and Removal
- §4 Endpoint Definitions — 4-column table (Method, Path, Description, Authorized Role(s)), 76 rows
- §5 Error Code Catalogue — 2-column table (Error ID, HTTP Status Code), 47 rows

**Coverage verification (machine-checked against SCAFFOLD.yaml)**
- Endpoints: 76/76 present as backticked paths — **0 misses**
- Errors: 47/47 error ids present, statuses taken from the scaffold — **0 misses**
- Field names (Contract 1): 178-name required set (143 entity fields + all `input`/query/path params + computed-read output keys + envelope/pagination names) — **0 misses**
- State machines: 11/11, all 89 transitions narrated; every state enum value present — **0 misses**
- Calculations: 8/8 documented with full formulas, pinned rounding orders and worked figures; every declared constant value appears as a numeral — **0 misses**
- Validations: all 38 priority ranks enumerated in §2.8 with error id, HTTP status and `applies_to` scope
- Contract 3 (§3 path purity): scan of every backticked token in lines 186–349 found **0** tokens beginning with `/`, **0** bare HTTP methods, **0** method+path combinations, and **0** unbackticked method+path strings
- Table shapes: §4 uniformly 4 columns, §5 uniformly 2 columns

**Three scaffold internal inconsistencies resolved and stated unambiguously in the prose** (flagging in case the test suite assumes otherwise):
1. Inspection result — the state-machine table clears `inspection_slot_start`/`inspection_slot_end` on `FAILED` only, while the endpoint bullet clears them unconditionally. I followed the state machine and explained that a `PASSED` slot holds no capacity anyway.
2. Balance payment — the endpoint and the `project_total_due` worked example both say every deposit bucket is untouched, while the financial state machine says `amount_cents` is added to `deposit_paid_cents` and `deposit_applied_cents`. I followed the two-source majority (buckets untouched) and added an explicit rule that `balance_due_cents` goes to zero on settlement and is not reopened by later recomputation, closing the formula gap that choice creates.
3. Project close — validation rank 21 blocks only `OPEN`/`ESCALATED` items, while both the state machine and the endpoint require every punch item `VERIFIED`. I documented the stricter, two-source version.

Also note: reinstatement is documented as `ProgramAdmin`/`ProjectCoordinator` per the endpoint role list (the state machine names `ServiceManager` as actor), so §4 and §2.1 stay self-consistent.

Orchestrator verification: `wc -l` = 485; `tail -25` ends on the complete final row of the §5 error table (a real section boundary), so no truncation; grep for `harder than expert|expert level|SCAFFOLD|test_recipe` returns zero matches, so neither the difficulty directive nor scaffold references leaked into PRD.md.

## Step 6: Generate implementation (subagent) — 2026-09-05T10:15:00.000Z

Note: Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator could not see `test_suite/` (it did not exist at spawn time). Step 6 finished first; Step 5 was still running when this entry was written.

Verbatim subagent summary:

The Flask implementation for task 2853 is complete, boots cleanly, and passes an 80-check smoke test.

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_2853_retailer_installation_services_program/workspace/implementation/`

**Per-file line counts (3495 lines total, 23 files)**

| file | lines | file | lines |
|---|---|---|---|
| `start.sh` | 7 | `routes/config.py` | 176 |
| `requirements.txt` | 1 | `routes/network.py` | 359 |
| `app.py` | 66 | `routes/customers.py` | 45 |
| `store.py` | 121 | `routes/projects.py` | 447 |
| `errors.py` | 121 | `routes/measurements.py` | 136 |
| `envelope.py` | 86 | `routes/change_orders.py` | 215 |
| `fields.py` | 359 | `routes/deliveries.py` | 107 |
| `services/calc.py` | 505 | `routes/assignments.py` | 257 |
| `services/cascade.py` | 156 | `routes/punch.py` | 125 |
| `routes/helpers.py` | 24 | `routes/warranty.py` | 110 |
| `routes/clock.py` | 71 | `routes/__init__.py` | 1 |

**Endpoint coverage: exactly 76.** A census over `app.url_map` prints `TOTAL 76`, matching the PRD §4 endpoint table one-for-one (no extras, no gaps).

**Structure**
- *Errors* — `errors.py` holds one `ApiError` plus an `ERROR_STATUS` table of all 47 error IDs with their HTTP codes, a default-message map, and a per-collection `NOT_FOUND` map so id resolution raises the right entity-specific 404. `app.py` registers a single `ApiError` handler plus 404/405/500 fallbacks, so every response leaves through `envelope.error`.
- *Validations* — the 38-rank rejection ladder is realised positionally: `fields.auth` (1-2), `fields.validate` (3→4→5, three separate passes over the declared field order, each doing top-level then nested-array sub-passes so presence of every line item precedes any type check), `fields.occ` (9), `fields.need` (6-7), then per-endpoint state/business ranks written in ladder order inside each handler. First failure wins; terminal (13) and project-cancelled (14) are deliberately checked before the generic `ERR_INVALID_STATE` (12) so neither is dead code.
- *State machines* — all 11 live as explicit transition guards in their route module (deliveries use a literal `FROM_STATUS` table); the four named cascades (`SCOPE_CHANGE_PENDING`, `INSTALLER_SUSPENDED`, `INSTALLER_REMOVED`, `PROJECT_CANCELLED`) are centralised in `services/cascade.py` over a shared `release_assignments` primitive, and all 8 calculations plus every pinned constant live in `services/calc.py` using `Decimal` + ROUND_HALF_UP with integer cents only.
- *Storage* — module-level dicts in `store.py`. A grep audit confirms zero `open(`/`sqlite`/`json.dump`/`pickle` calls anywhere; nothing is seeded at startup.

**Smoke test (port 18853, killed afterwards by exact PID)** — 80 assertions, 79 PASS. Drove the full happy path: category/jurisdiction config → installer onboarding (credential → `DOCS_PENDING` → verify → background check → `VERIFIED` → activate) → customer → project → deposit → measurement completion → change order → delivery → window hold/confirm/start/complete → quality inspection with a SAFETY punch item → escalate/resolve/verify → inspection slot & result → pay balance → close → warranty claim → triage; plus the cancel/reinstate/settlement-preview branch, pagination meta, and negative cases (401 missing headers, 403 bad role, 403 non-owner, 403 wrong permit party, 412 stale OCC, 422 limit=0, 422 amount mismatch, 409 permit-blocked start, 409 SAFETY-resolve-from-OPEN, 409 already-terminal, 404 entity-specific code).

The single non-PASS was my harness's own wrong expectation (I predicted 3 ledger events; the correct answer is 4 — `ON_TIME_COMPLETION`, `PUNCH_SAFETY` from the quality inspection, a second `PUNCH_SAFETY` from the escalation per PRD line 304, and `WARRANTY_UPHELD`). Not an implementation defect.

**Pinned PRD figures all verified:** change-order upcharge **10546** (per-line round then sum, not 10547), provisional quote 187680 and deposit 56304, invoice 253942 + 10546 + 18500 = **282988** with balance **223986**, and all three worked settlement cases — (29501, 30000, 59501, tier NONE, clamp to 59002, FORFEITED), (14751, 15000, 29751, refund 29251, PARTIALLY_REFUNDED), and the ladder-order trap case at 48 h with `project_count` 4 correctly stopping at COOLING_OFF for a full 59002 refund rather than the wrong GOODWILL answer.

**Fresh-boot isolation verified:** after `kill <pid>` and relaunch on the same port, `GET /projects` returns an empty collection and `GET /_clock` is back to `2026-08-01T00:00:00.000Z`, so `per-test-server` isolation wipes every byte of state. Port 18853 confirmed free; `__pycache__` removed. No broad pkill was ever issued.

## Step 5: Generate unit tests (subagent) — 2026-09-05T11:50:00.000Z

Verbatim subagent summary:

Step 5 test infrastructure for task 2853 is complete.

## Output locations (task root — nothing under `workspace/`)
`/home/ubuntu/github/CodingPRD/tasks/task_2853_retailer_installation_services_program/test_helpers/` and `.../test_suite/`. Verified: `find workspace -name test_helpers -o -name test_suite` returns 0 hits; `workspace/implementation/` was never read or written.

## Line counts
**test_helpers/ (2820 lines):** `__init__.py` 137, `api_client.py` 436, `api_errors.py` 117, `assertions.py` 203, `constants.py` 109, `factories.py` 615, `fixtures.py` 553, `test_users.py` 91, `types.py` 559.

**test_suite/ (6948 lines):** `conftest.py` 65; `test_01` 240, `test_02` 216, `test_03` 164, `test_04` 333, `test_05` 200, `test_06` 225, `test_07` 211, `test_08` 306, `test_09` 235, `test_10` 141 (queue A); `test_11_entity_corners` 525, `test_12_state_machine_corners` 778, `test_13_calculation_corners` 561, `test_14_validation_corners` 581, `test_15_endpoint_corners` 476, `test_16_error_corners` 694, `test_17_rbac_corners` 379, `test_18_cross_cutting_corners` 504, `test_19_consistency_corners` 114 (queue B).

## Test count
**146 test functions**, expanding to **166 collected pytest items** via `@pytest.mark.parametrize`. `python3 -m pytest test_suite --collect-only -q` collects all 166 with zero errors. No `skip`/`xfail` anywhere; no file mentions "scaffold".

## Instance-to-test accounting
- **Queue A (difficulty): 22 / 22** instances → 40 tests (test_01–test_10).
- **Queue B (corner): 57 / 58** non-stub instances → 106 tests. Per section: entities 12/12, state_machines 11/12, calculations 6/6, validations 7/7, endpoints 5/5, errors 7/7, rbac 3/3, cross_cutting_complexity_layers 5/5, consistency_model 1/1. The 14 `EXCLUDED:` stubs correctly got no tests.
- Programmatic cross-check against both source indices: 79 unique `Design:` tags = 22 + 57; **zero** tags pointing at a non-existent instance, zero stubs covered, exactly one `Design:` line per docstring and always last, and every ≥40-char quoted span is a verbatim whitespace-normalised substring of `PRD.md`.

## Skipped instances (two-condition PRD filter)
1. `Corner/state_machines/failed_inspection_increments_the_attempt_count_and_releases_the_slot` — the instance asserts every inspection-result write nulls both slot instants, but PRD §3.5 says "The recorded slot instants are left in place on a pass", so the asserted outcome is not uniquely derivable from the PRD.

## Notable design/PRD reconciliations carried into the new files
- Operator-supplied `release_reason` is free text (PRD §3.6 "records the reason"), not a `ReleaseReason` enum value — the enum members only ever arise from the four cascades, so `test_18` asserts the literal string.
- HTTP statuses are always left to `validate_error`'s registered §5 map rather than the corner index's inline claims (the index is wrong on two of them).
- All five cross-cutting arithmetic chains were re-derived from the PRD before use: 71.25 → 70.00 on the removal ladder, and 85.00 → 83.20 → 78.00 → 80.95 across the inclusive probation ceiling.

Orchestrator verification: `find workspace -maxdepth 1 -name "test_*"` returns nothing, so both directories landed at the task root as required; `python3 -m pytest test_suite --collect-only -q` reports `166 tests collected in 0.60s` with zero errors.

## Step 7: Run tests and iterate (long-lived subagent) — 2026-09-05T13:05:00.000Z

Orchestrator note: the 8-round sweep was run from a pre-written script file (`workspace/run_sweep.sh`) launched under `setsid nohup`, rather than an inline `setsid nohup bash -c '...'` one-liner, because the inline form's shell quoting injects literal quotes into `--start-command` and kills all 8 rounds at t=0. The script also gives each round its own `round.$i.log` so no diagnosis depends on the spliced shared `sweep.log`. Orchestrator polling confirmed the baseline sweep at 164/166 in all 8 rounds and the verification sweep at 166/166 in all 8 rounds.

Verbatim subagent summary:

Done. All 8 rounds fully green.

## Summary

**Iterations run:** 2 sweeps (baseline diagnostic + verification). Baseline was 164/166 in all 8 rounds with 2 deterministic failures (no flakiness, no load artifacts, no missing results files).

**Tests deleted:** none. Both failures survived STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability), and STEP 2 found both tests faithful in setup, request identity and assertion — so both were genuine implementation defects.

**Fixes applied to `test_helpers/`:** none. The helpers were already correct on all the known repeat offenders: money is emitted as integer cents (`factories.py` even asserts it), instants are canonicalised to exactly three fractional digits in `api_client.canonicalise_instants`, `validate_success` is not double-unwrapped, and `test_users.py` gives each owner a distinct `X-User-ID` with entity-backed ids for `Installer`/`Customer`.

**Fixes applied to `implementation/`:**

1. `workspace/implementation/routes/projects.py`, `pay_balance()` — removed a blanket `financial_status != "BALANCE_DUE" → ERR_INVALID_STATE` gate that pre-empted rejection-ladder rank 36. PRD §3.6 states the balance gate purely as amount + balance + ownership: *"which must equal `balance_due_cents` **exactly** and which requires `balance_due_cents` to be greater than zero; any other figure, or a payment against a zero balance, is `ERR_BALANCE_AMOUNT_MISMATCH`."* The generic rank-12 reading rendered both that clause and rank 36's *"and `balance_due_cents` is greater than zero"* unreachable dead letters, since every non-`BALANCE_DUE` financial status carries a zero balance (confirmed in `calc.recompute_money`, which pins `SETTLED` to zero). Rank 36 now owns the case.

2. `workspace/implementation/services/cascade.py`, `release_assignments()` / `suspend_if_unlicensed()` / `remove_installer()` — added `skip_touch_installer_id` so the firm driving a cascade is not touched twice. The shared release primitive was touching the owning installer *and* the route handler was touching it again, giving `version + 2`. PRD §2.9 requires each affected row's *"`version` incremented by one"* per request, and §3.9 says a removal *"increments the firm's `version`"* — singular. Applied to the suspension path too, which carried the same latent double-increment.

**Key finding:** the double-increment only surfaced when the removed firm actually held a live `HELD`/`CONFIRMED` window, which is why a sibling removal test (`test_18` line 425, removal with no live window) passed throughout and masked the defect.

**Final sweep evidence** (all 8 results files present, md5-stable over 60s, `SWEEP_COMPLETE` with all rounds present):

| Round | Passed / Total | Failed | Errors | Skipped |
|---|---|---|---|---|
| 1 | 166 / 166 | 0 | 0 | 0 |
| 2 | 166 / 166 | 0 | 0 | 0 |
| 3 | 166 / 166 | 0 | 0 | 0 |
| 4 | 166 / 166 | 0 | 0 | 0 |
| 5 | 166 / 166 | 0 | 0 | 0 |
| 6 | 166 / 166 | 0 | 0 | 0 |
| 7 | 166 / 166 | 0 | 0 | 0 |
| 8 | 166 / 166 | 0 | 0 | 0 |

Union of non-passing tests across all 8 rounds: **0**. Storage remains in-memory only (no sqlite, file, or `/tmp` persistence), and `worklog.md` was not touched.

Step 8 skip condition NOT met (2 `implementation/` fixes), so Step 8 will run.

## Step 8: Finalize PRD (subagent) — 2026-09-05T13:15:00.000Z

Verbatim subagent summary:

PRD_FINALIZED.md is written. Only Step 7 diff item 1 (the `pay_balance` state gate) produced PRD edits; item 2 (the double `version` increment) was a pure implementation defect against text the PRD already pins, so it needed no patch.

## Line counts
- `PRD.md`: 485 lines / 121,666 bytes
- `PRD_FINALIZED.md`: 485 lines / 122,794 bytes — line delta 0.00%, byte delta **+0.93%** (3 in-paragraph insertions, no new sections, trailing §4 table and §5 error catalogue intact)

## Changes
- **§2.8 rank 12** — insert — appended that the balance payment sits outside the generic state-precondition rank, its financial dimension being examined only by rank 36, so it never answers `ERR_INVALID_STATE` — `routes/projects.py:186-205`
- **§2.8 rank 36** — insert — appended that rank 36 is the only check consulting the project's financial dimension on a balance payment — `routes/projects.py:199-201`
- **§3.6 "Settling the balance"** — insert — spelled out that there is no separate `financial_status` gate; since every non-`BALANCE_DUE` financial status carries a zero balance, `QUOTED`/`DEPOSIT_HELD`/`SETTLED`/`PARTIALLY_REFUNDED`/`REFUNDED`/`FORFEITED` (including a `CANCELLED` project, which is not a rank-14 child write) are all refused with `ERR_BALANCE_AMOUNT_MISMATCH`, while a `CLOSED` project is pre-empted by rank 13 with `ERR_ALREADY_TERMINAL` — `routes/projects.py:190-201`, `services/calc.py:473-488`

## Per-edit pre-edit search log

**Edit 1 & 2 (§2.8 ranks 12 and 36)**
- (a) Subject: which ladder rank governs the financial/state precondition of `POST /projects/{id}/pay-balance`, and whether `ERR_INVALID_STATE` is reachable there.
- (b) Enumerated/read: `routes/projects.py` `pay_balance()` (only raises `ERR_ALREADY_TERMINAL` via `_not_closed`, `ERR_NOT_RESOURCE_OWNER` via `owner_customer`, `ERR_BALANCE_AMOUNT_MISMATCH`), `_not_closed`/`_permit_not_closed` (projects.py:65-74), `routes/helpers.py` (`owner_customer`, `project_not_cancelled` — the latter is *not* called from `pay_balance`), plus grep of `balance_due_cents`/`BALANCE_AMOUNT_MISMATCH` across the tree (`services/calc.py:473-501`, `routes/assignments.py:207`).
- (c) Adjustment: scoped both sentences to "the balance payment" alone rather than payments generally, because the sibling `pay_deposit()` (projects.py:172-173) *does* carry an explicit `financial_status != "QUOTED"`/`CANCELLED` → `ERR_INVALID_STATE` gate; a generalised "payments carry no state gate" claim would have contradicted it.

**Edit 3 (§3.6 "Settling the balance")**
- (a) Subject: the set of project states a balance payment can be attempted from, and the error each yields.
- (b) Enumerated/read: `calc.recompute_money` (total is 0 whenever `final_labor_cents` is null; `SETTLED` pins balance to 0), `calc.deposit_waterfall`, every writer of `financial_status` — `pay_deposit` (`DEPOSIT_HELD`), `assignments.complete` (`BALANCE_DUE`/`SETTLED`, calc.recompute_money then waterfall), `cascade.cancel_project` (`REFUNDED`/`FORFEITED`/`PARTIALLY_REFUNDED` + `recompute_money`), reinstate (`DEPOSIT_HELD`), `pay_balance` (`SETTLED`) — and rank-14 callers of `project_not_cancelled` to confirm `pay-balance` is not among them.
- (c) Adjustments: (i) stated the implication one-way only ("anything other than `BALANCE_DUE` carries a zero balance") rather than an iff, because a post-completion accepted credit change order can leave `BALANCE_DUE` with a zero balance and that path also yields `ERR_BALANCE_AMOUNT_MISMATCH`; (ii) added the rank-13 `CLOSED` clause so the "already `SETTLED` → mismatch" claim does not mis-describe a closed project; (iii) replaced a first draft's "the only check that can pre-empt it is rank 13" with "stopped earlier still", since ranks 3-6 validation and the rank-29 ownership check also pre-empt.

**Item 2 (cascade `skip_touch_installer_id`) — searched, no edit**
- (a) Subject: how many times a firm's `version` moves in the suspension and removal cascades.
- (b) Enumerated/read: `services/cascade.py` `release_assignments` / `scope_change_pending` / `suspend_if_unlicensed` / `remove_installer` / `cancel_project`, and all four callsites (`routes/network.py:251` reject-driven suspension, `routes/network.py:285-302` removal, `routes/clock.py:30-47` expiry sweep, `routes/measurements.py:134` scope change). Removal and reject-driven suspension each now bump the firm exactly once (caller-owned touch); cancellation and scope-change paths touch the *other* firm once each, as before.
- (c) No wording added. §2.9 ("every affected row's `version` incremented by one"), §3.2 ("The firm's `version` increments") and §3.9 ("increments the firm's `version`") already determine the single increment, so the fix closed a PRD/impl mismatch rather than a PRD silence. I deliberately avoided writing any "exactly one per request" universal, because the clock sweep touches an installer once per expired credential (`routes/clock.py:47`), which such wording would have falsified.

Orchestrator verification: `cmp` reports PRD.md and PRD_FINALIZED.md DIFFER (a byte-identical PRD_FINALIZED.md would also have been legitimate here, but Step 7 did make implementation fixes and Step 8 patched them); both are 485 lines; `tail` confirms PRD_FINALIZED.md still ends on the final `ERR_NOT_CANCELLABLE` row of the §5 table, so no section was lost.

## Step 9 execution plan — 2026-09-05T13:16:00.000Z

Step 9 is run as FOUR sequential module-partitioned passes over one shared `PRD_COMPLETED.md`, not as a single monolithic scan. Rationale: a single agent asked to scan a 3495-line implementation against a 485-line PRD routinely returns a byte-identical file (the scan silently never happens). Partitioning by implementation module bounds each pass's reading load and makes the per-pass edit list auditable. Pass 1 performs the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2-4 must NOT re-copy, or they would discard the previous passes' edits. The passes run strictly sequentially (never concurrently) because they all edit the same file.

- Pass 1 (does the cp): `app.py`, `envelope.py`, `errors.py`, `fields.py`, `store.py`, `routes/helpers.py`, `routes/clock.py` — envelope/pagination shape, the 47-error table, the 38-rank field-validation ladder, OCC, id/version machinery, logical clock and its expiry sweep.
- Pass 2: `routes/config.py`, `routes/network.py`, `routes/customers.py` — service catalogue, jurisdictions, installer recruitment/credentials/background checks/insurance, activation, suspension, removal, scorecard.
- Pass 3: `routes/projects.py`, `routes/measurements.py`, `routes/change_orders.py`, `services/calc.py` — project lifecycle, deposit/balance, measurement hinge, change-order loop, and all 8 calculations.
- Pass 4: `routes/deliveries.py`, `routes/assignments.py`, `routes/punch.py`, `routes/warranty.py`, `services/cascade.py` — delivery sync, install-window calendar/capacity, quality inspection and punch list, labour warranty, and the four cascades.

## Step 9: Complete PRD — pass 1 of 4 (core machinery) — 2026-09-05T13:25:00.000Z

Verbatim subagent summary:

Pass 1 complete.

## Copy + integrity
- `cp PRD_FINALIZED.md PRD_COMPLETED.md` performed by me (pass 1).
- Line counts: **485 → 485** (all edits are in-place substitutions; no new lines, no new sections). Chars: **122,794 → 127,742 (+4,948)**.
- `tail -3` confirms the file still ends on `| ERR_NOT_CANCELLABLE | 409 |`. Diff hunks are exactly lines 51-53, 81, 85, 89, 95, 101, 117, 131, 133, 135, 352, 435.

## Counts
- Ambiguity pins: **13**
- Mismatch revisions: **1** (§4 "reached at `/projects` exactly" vs `strict_slashes=False`)

## Changes
- §2.2 success bullets — revise — ambiguity — `api_request_id` is `req_` + 32 lowercase hex UUID digits (the sample value is shape-only) — `envelope.py:13`
- §2.2 success bullets — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not host time — `envelope.py:14`
- §2.2 success bullets — insert — ambiguity — computed reads and both clock operations answer `response_type` `"object"` — `envelope.py:42-44`, `routes/clock.py:60,71`
- §2.3 ¶1 — insert — ambiguity — non-integer / empty `limit`/`offset` answer `ERR_FIELD_OUT_OF_RANGE` (not `ERR_INVALID_FIELD_TYPE`); whitespace trimmed; past-the-end offset gives an empty page — `fields.py:311-331`
- §2.3 ¶3 — insert — ambiguity — insertion order is the tie-break under the `created_at` default and the scorecard `occurred_at`/`created_at` ordering; filter values are never validated (empty string ignored, unmatched value → empty page, boolean filter reads `true`/`1`/`yes`) — `envelope.py:73-86`, `fields.py:334-359`
- §2.4 ¶1 — insert — ambiguity — `created_at`/`updated_at` and every server-stamped instant come from the logical clock — `store.py:84-101`
- §2.4 clock ¶ — insert — ambiguity — sweep tie-break is insertion order; the clock accepts earlier instants and the expiry sweep is one-directional; rescore covers every installer row so `installers_rescored_count` is the row total, and a no-op rescore does not bump `updated_at`/`version` — `routes/clock.py:29-58`
- §2.5 ¶2 — insert — ambiguity — non-money numerics (percentages, multipliers, scores, unit quantities) are JSON numbers, never strings (`79.6`, not `"79.60"`) — `envelope.py:18-27`
- §2.6 last ¶ — insert — ambiguity — a present-but-not-positive-integer OCC value also answers `ERR_MISSING_REQUIRED_FIELD`, and the OCC field sits outside ranks 3-5, checked only at rank 9 after ids resolve — `fields.py:303-308`, `routes/assignments.py:44-46`
- §2.8 rank 1 — insert — ambiguity — whitespace-only auth header counts as empty — `fields.py:81-84`
- §2.8 rank 3 — insert — ambiguity — absent/unparseable body is treated as `{}` (so rank 3 fires); a non-object JSON body is `ERR_INVALID_FIELD_TYPE` at every endpoint that reads a body (the five no-body actions never inspect it); optional null = absent; undeclared keys ignored — `fields.py:90-99,240-300`
- §2.8 rank 5 — insert — ambiguity — ranks 3/4/5 are complete passes in declared field order, top-level before nested array entries (entries in array order, non-object entry = rank-4 type error); every declared string incl. foreign keys has a 1-char floor, so an empty-string FK is rank-5 out-of-range, a numeric FK rank-4 type — `fields.py:240-300,119-120`
- §4 intro — revise — mismatch — trailing slash accepted as the same path — `app.py:33`
- §5 intro — insert — ambiguity — two out-of-catalogue codes precede any ladder: `ERR_NOT_FOUND` 404 (no matching path) and `ERR_METHOD_NOT_ALLOWED` 405 — `app.py:43-50`

## Modules scanned (all 7 of my partition)
`app.py`, `envelope.py`, `errors.py`, `fields.py`, `store.py`, `routes/helpers.py`, `routes/clock.py`. I read `services/calc.py`, `services/cascade.py`, `routes/*.py` spec blocks only as cross-reference for the global-consistency guard.

## Deliberately left to later passes
- `lines` cardinality 1-10 and `ERR_CHANGE_ORDER_SHAPE`: enforced entirely in `routes/change_orders.py` (pass 3) — no rank 5 vs rank 28 conflict exists, and I made no edit.
- Assignment creation's `window_end <= window_start` firing at rank 5 before `need("projects")` — `routes/assignments.py` (pass 4).
- The suspension cascade triggered by clock-driven expiry (`services/cascade.py`) and the scorecard arithmetic itself (`services/calc.py`) — passes 4 and 3.
- `errors.py` supplies no default `message` for the 12 not-found codes; left unpinned deliberately, since PRD treats `message` as free-form human prose.
- `ERR_INTERNAL` 500 catch-all in `app.py`: left undocumented as a safety net rather than contract.

## Step 9: Complete PRD — pass 2 of 4 (catalogue, jurisdictions, customers, installer network) — 2026-09-05T13:35:00.000Z

Verbatim subagent summary:

Pass 2 complete.

**No copy performed.** I edited `workspace/PRD_COMPLETED.md` in place with 13 targeted `Edit` calls. All 14 of pass 1's edits are verifiably still present (diff vs `PRD_FINALIZED.md` now shows 26 changed lines = pass 1's 14 lines + my 13 lines, minus the one line we both touched, §4 preamble).

- Before: 485 lines / 127,742 chars → After: 485 lines / 133,432 chars
- Tail check: file still ends on `| ERR_NOT_CANCELLABLE | 409 |`; `wc -l` unchanged at 485.
- Counts: **6 ambiguity-pins, 7 mismatch-revisions**.

Changes (one per bullet):

- §3.1 (service category) — revise — mismatch — the `code` uppercase/digit/hyphen charset is a convention the service does not enforce; only the 1–32 length bound is checked — `routes/config.py:17`
- §3.1 (category amendment) — insert — ambiguity — the programme's three PATCH endpoints treat the call itself as the mutation: a no-op/empty PATCH still bumps `updated_at` and `version` — `routes/config.py:120,175`, `routes/network.py:151`
- §3.1 (jurisdiction) — revise — mismatch — `code` charset likewise unenforced and uniqueness case-sensitive; `permit_required_trades` stored verbatim (order and duplicates kept); `permit_unit_threshold` is the one unit quantity with **no** two-decimal ceiling — `routes/config.py:41,43,47`
- §3.1 (duplicate keys ¶) — insert — ambiguity — declared field order for the rank 3–5 passes across §3.1/§3.2 writes: required fields first in introduction order, then optionals in introduction order (verified field-by-field against all 9 spec lists) — `routes/config.py:16-69`, `routes/network.py:18-57`
- §3.2 (recruitment) — revise — mismatch — `contact_email` is capped at 320 chars and the at-sign is not verified — `routes/network.py:27`
- §3.2 (licence filing) — revise — mismatch — the jurisdiction need only exist; its `ACTIVE` status is **not** checked (rank 15's list excludes credential filing) — `routes/network.py:160`
- §3.2 (licence filing) — insert — ambiguity — filing refused only for a `REMOVED` firm, at rank 13 behind the rank-8 duplicate test; the per-firm licence list accepts a `verification_status` filter — `routes/network.py:161-167,195`
- §3.2 (verification) — insert — ambiguity — `VERIFY` admitted only from `PENDING`; the full `ERR_INVALID_STATE` set (incl. expired-licence VERIFY and `REJECT` of `EXPIRED`/`REJECTED`); `REJECT` keeps `verified_at` and writes null reason when omitted; and the counter-only recomputation does **not** version the firm — `routes/network.py:225-252`
- §3.2 (background check) — insert — ambiguity — refilable in any status short of `REMOVED`, always bumping `version`; a `FAIL` never demotes a `VERIFIED`/`ACTIVE`/`PROBATION` firm — `routes/network.py:256-266`
- §3.2 (activation) — insert — ambiguity — lapsed insurance and non-`PASS` background both answer `ERR_INVALID_STATE` (not the rank-18/19 codes); `REMOVED` answers `ERR_ALREADY_TERMINAL`; admission runs `rescore` but **not** the probation transition — `routes/network.py:269-281`, `services/calc.py:263`
- §3.9 (event ledger) — insert — ambiguity — the `csat_score` cross-field test is rank 4, answered before the path installer is resolved; any status but `REMOVED` may be a target; `project_id` need only exist — `routes/network.py:305-320`
- §3.9 (removal) — revise — mismatch — `removal_reason` is 1–300 chars; the ladder is version → `ERR_ALREADY_TERMINAL` → rank 33's *three* conditions (status, `removal_eligible`, no `IN_PROGRESS` assignment), the wrong status answering `ERR_REMOVAL_NOT_ELIGIBLE` not `ERR_INVALID_STATE` — `routes/network.py:284-299`
- §3.9 (removal, terminality) — revise — mismatch — the universal "every later attempt … `ERR_ALREADY_TERMINAL`" was false: reads, `PATCH /installers/{id}` and a verification decision on its licences all still succeed, and assignment creation answers `ERR_INSTALLER_NOT_ASSIGNABLE` — `routes/network.py:143-152,217-253`, `routes/assignments.py:62`
- §4 preamble — revise — mismatch — narrowed the blanket `ERR_NOT_RESOURCE_OWNER` claim: ownership is tested only on the rank-29 writes, never on a read (grep-verified) — `routes/customers.py:44`, `routes/network.py:139`

**Modules scanned exhaustively:** `routes/config.py` (176 lines), `routes/network.py` (359), `routes/customers.py` (45).

**Deliberately left unpatched (other passes' subjects):** scorecard *arithmetic* (`services/calc.py`, pass 3); the `INSTALLER_SUSPENDED`/`INSTALLER_REMOVED` cascade hop details in `services/cascade.py` (pass 4); one residual tension noted but not touched — §2.8's rank-12 carve-out list does not mention installer activation/removal, whose `REMOVED` handling was instead pinned locally in §3.2/§3.9.

## Step 9: Complete PRD — pass 3 of 4 (projects, measurements, change orders, all 8 calculations) — 2026-09-05T13:55:00.000Z

Verbatim subagent summary:

PASS 3 complete.

**No copy performed.** `PRD_COMPLETED.md` was edited in place with 21 targeted `Edit` calls only — no `cp`, no full-file `Write`. All 27 prior edits from passes 1 and 2 are intact.

**Counts:** before 485 lines / 133432 chars → after **485 lines / 141856 chars** (+8424). `tail -3` confirms the file still ends on `| ERR_NOT_CANCELLABLE | 409 |`.

**Classification:** 13 ambiguity-pins, 8 mismatch-revisions.

- §2.8 rank 3 — revise — mismatch — carved the single exception out of pass 1's false universal "an unknown key is never rejected": `source_measurement_id` on a client-raised change order is rejected outright — `routes/change_orders.py:73`
- §2.8 rank 12 — insert — mismatch — pinned the close handler's inner order (punch → permit → `SETTLED` → execution dimension, `ERR_INVALID_STATE` last) and that ranks 13/14 precede the generic state check, with the deposit payment falling through to it — `routes/projects.py:307-324, 171-173`
- §2.9 — revise — mismatch — `DRAFT` is a declared-but-unreachable `fulfillment_status`; nothing writes it, so its rows in the cancellable set and forfeit table are dead — `routes/projects.py:94`, `services/calc.py:294`
- §3.3 — revise — ambiguity — `project_count` is *recomputed*, not incremented, and the customer row's `updated_at`/`version` move — `routes/projects.py:132-133`
- §3.3 — insert — ambiguity — every other creation default enumerated (`NONE` strings, zeroes, nulls) since the whole row is response-visible — `routes/projects.py:99-124`
- §3.3 — insert — ambiguity — deposit payment on a `CLOSED` project is `ERR_ALREADY_TERMINAL`, on a `CANCELLED` one `ERR_INVALID_STATE` (one combined generic check) — `routes/projects.py:171-173`
- §3.4 — insert — ambiguity — booking leaves the project at `MEASURE_PENDING`, so multiple `SCHEDULED` appointments are legal and all but one become uncompletable — `routes/measurements.py:40-57`
- §3.4 — insert — ambiguity — auto-CO opens with `net_primary_units_delta` 0 / `revision_count` 0 / nulls, and the completion response carries the appointment only, never the project — `routes/measurements.py:120-136`
- §3.4 — insert — mismatch — supersede target must be same-project and in one of the three statuses (`ERR_CHANGE_ORDER_SHAPE`); `source_measurement_id` rejected even as null; creation has no execution-dimension precondition — `routes/change_orders.py:73-77, 64-66`
- §3.4 — insert — ambiguity — credit cap bound is strict, tested on creation and submission, never on the variance order — `routes/change_orders.py:46-49, 80, 149`
- §3.4 — insert — ambiguity — a `lines` array on a `DRAFT` submission is ignored outright; on `REVISION_REQUESTED` it is required and answered after the terminal guard — `routes/change_orders.py:142-160`
- §3.4 — revise — ambiguity — `revision_note` stays optional on `REQUEST_REVISION`, recording null — `routes/change_orders.py:34, 212`
- §3.5 — revise — mismatch — permit party matching is on role alone, no identity comparison, and the filing is not rank-29 guarded; `permit_application_reference` required even on a resubmit and then discarded — `routes/projects.py:331-358`
- §3.5 — insert — ambiguity — `inspector_note` validated then discarded; `result` written to `inspection_result` — `routes/projects.py:61, 431-432`
- §3.7 — revise — mismatch — the permit gate bites only where `inspection_required` **and** `permit_responsibility != NOT_REQUIRED`; otherwise a project closes at `PENDING_APPLICATION`/`APPLIED`/`ISSUED`; `SETTLED` (`ERR_NOT_CANCELLABLE`) is tested before the execution dimension — `routes/projects.py:313-321`
- §3.8 — revise — mismatch — `cancel_reason` 1-300 chars; a `CLOSED` project answers `ERR_ALREADY_TERMINAL`, not `ERR_NOT_CANCELLABLE`, with the ownership check sitting between the two — `routes/projects.py:29, 216-219`
- §3.8 — insert — ambiguity — the restocking fee reads the **most recently created** delivery when several exist — `services/calc.py:303-309`
- §3.8 — insert — ambiguity — a variance decline runs the cascade as the deciding `Customer`, so `RETAILER_FAULT` can never match there — `routes/change_orders.py:206`
- §3.8 — insert — ambiguity — the preview has no state gate and no ownership gate; `labor_forfeit_pct` falls back to 0.00 outside the six statuses while `restocking_fee_cents`/`gross_retained_cents` stay live, and the step-six clamp against an emptied `deposit_held_cents` forces `retained`/`refund` to zero and `REFUNDED` — `routes/projects.py:154-163`, `services/calc.py:314, 346-354`
- §3.8 — revise — ambiguity — `reinstate_note` up to 300 chars, validated then discarded — `routes/projects.py:30, 228-229`
- §3.9 — revise — mismatch — the composite consumes the already-rounded **and clamped** dimension scores; `rolling_event_count`/`rolling_no_show_count` count in-window events only; the lifetime dimension scores are computed and discarded — `services/calc.py:198-204, 241-243, 263-272`

**Modules scanned exhaustively:** `routes/projects.py` (all 453 lines), `routes/measurements.py` (all 136), `routes/change_orders.py` (all 215), `services/calc.py` (all 505, all 8 calculations).

**Deliberately left unpatched:**
- calc.py calculations 6 and 7 (`delivery_slack_hours`, `delay_days`, `duration_minutes`, `window_conflict`, `recompute_committed_minutes`, the 4800-minute cap) — verified already fully and correctly pinned in §3.6; `lateness_excused`'s "any delivery" nuance handed to pass 4.
- `WARRANTY_LABOR_DAYS = 365` — already pinned in §3.7, and `warranty.py` is pass 4's.
- `cascade.scope_change_pending` firing from measurement completion — verified an unreachable no-op, so no pin invented.
- `latest_completed_measurement`'s `_seq` tie-break — verified unreachable.
- All four cascades' child sweeps and the `release_assignments` version-skip logic — pass 4's.

## Step 9: Complete PRD — pass 4 of 4 (deliveries, assignments, punch, warranty, cascades) — 2026-09-05T14:10:00.000Z

Verbatim subagent summary:

PASS 4 of 4 complete.

## Integrity

- **No copy was performed.** Every change was a targeted `Edit` against the existing `PRD_COMPLETED.md`, preserving all 48 prior-pass edits (verified by a `difflib` diff of `PRD_FINALIZED.md` → `PRD_COMPLETED.md` showing all 48 prior + all 17 of mine).
- **Before:** 485 lines / 141856 chars. **After:** 485 lines / 147791 chars (+5935).
- **§4 endpoint table: 76 rows** (unchanged). **§5 error table: 47 rows** (unchanged). File still ends on `| ERR_NOT_CANCELLABLE | 409 |`.
- No file other than `PRD_COMPLETED.md` was written. `worklog.md` untouched; no `SCAFFOLD*.yaml` and no sibling task dir read.

## Counts

**13 ambiguity-pins, 4 mismatch-revisions** (17 edits).

## Changes

- §2.9 — insert — ambiguity — the release sweep shared by all four cascades versions each affected installer and each affected project exactly once, however many of that row's windows the same sweep released — `services/cascade.py:41-75`
- §3.4 — insert — ambiguity — the `SCOPE_CHANGE_PENDING` cascade, previously named in §2.9 but described nowhere: HELD/CONFIRMED windows → RELEASED with that reason, installer `committed_minutes` recomputed and versioned once, project left at `CHANGE_PENDING` (not reverted), and honestly noted as declared-but-unreachable — `services/cascade.py:79-85`, `routes/measurements.py:134`
- §3.6 (planning a delivery) — insert — ambiguity — no execution-dimension precondition beyond ranks 13/14; any number of deliveries may be planned per project — `routes/deliveries.py:42-45`
- §3.6 (moving a delivery) — insert — ambiguity — the `DELIVERED`-requires-`actual_delivered_at` test fires before the delivery is resolved and before the path is checked; the field is discarded on other hops — `routes/deliveries.py:92-95`
- §3.6 (moving a delivery) — insert — ambiguity — `new_status` is typed against all five statuses; `PLANNED`/`RETURNED` targets and unoffered hops answer `ERR_INVALID_STATE`; a `RETURNED` source answers `ERR_ALREADY_TERMINAL` first; `DELIVERED` is not terminal; a hop versions only the delivery row — `routes/deliveries.py:96-107`
- §3.6 (holding a window) — insert — ambiguity — `fulfillment_status` must be exactly `MEASURED` (`ERR_INVALID_STATE`, rank 12, evaluated after 13/14), plus the rank-15 jurisdiction-`ACTIVE` / no-live-assignment pair — `routes/assignments.py:52-60`
- §3.6 (holding a window) — insert — ambiguity — the new assignment's neutral fields (`started_at`, `completed_at`, `on_time`, `release_reason` all null) — `routes/assignments.py:105-116`
- §3.6 (confirming) — **revise** — **mismatch** — the slack is measured against the **most recently created** row among the three eligible statuses; the PRD's "a `DELAYED` or `RETURNED` delivery blocks confirmation" was false — such rows are skipped over, and confirmation fails only when no eligible row exists at all — `routes/assignments.py:147-156`
- §3.6 (completing) — **revise** — **mismatch** — `on_time`'s excuse clause consults **any** delivery on the project, in whatever status including `RETURNED`, not "the project's material delivery" — `routes/assignments.py:196`, `services/calc.py:420-423`
- §3.6 (releasing) — insert — ambiguity — `release_reason` is 1 to 120 characters — `routes/assignments.py:25`
- §3.6 (releasing) — insert — ambiguity — the ordinary release path also moves the assignment, the installer and (when `SCHEDULED`) the project versions — `routes/assignments.py:241-256`
- §3.7 (resolving a punch item) — insert — ambiguity — an already-`RESOLVED` item answers `ERR_PUNCH_LIST_NOT_CLEARED`; a `VERIFIED` one answers `ERR_ALREADY_TERMINAL` — `routes/punch.py:58-60`
- §3.7 (signing off) — insert — ambiguity — `OPEN` and `ESCALATED` both answer `ERR_PUNCH_LIST_NOT_CLEARED`; sign-off versions only the item, and `escalated_punch_count` is not adjusted here — `routes/punch.py:86-92`
- §3.7 (escalating) — insert — ambiguity — an already-`ESCALATED` item answers `ERR_INVALID_STATE` — `routes/punch.py:102-103`
- §3.7 (filing a warranty claim) — **revise** — **mismatch** — a non-`CLOSED` project also answers `ERR_WARRANTY_EXPIRED`, never `ERR_INVALID_STATE` — `routes/warranty.py:37-39`
- §3.7 (triage) — insert — ambiguity — `denial_reason` is 1 to 300 characters; `DENY`'s conditional requirement is checked before the claim is resolved; `ESCALATE` leaves `triaged_at` null and discards `decision_note`; `escalation_level` never exceeds 1 because a second `ESCALATE` answers `ERR_INVALID_STATE` — `routes/warranty.py:22-26, 78-81, 105-108`
- §3.8 (cancellation child sweep) — **revise** — **mismatch** — **every** non-`RETURNED` delivery on the project is returned, not just the single row the restocking fee reads; released assignments' installers are versioned once each; no project is reverted on this path — `services/cascade.py:156-166`

## Prior-pass wording corrected as globally false

**None.** All three globally-false universals I revised were verified to be original PRD text, present verbatim in `PRD_FINALIZED.md` (`grep -c` = 1 each). I also re-checked every prior-pass insert that makes a universal claim touching my modules — all remain true under my five modules.

## Self-caught error worth noting

My planned §2.9 wording was going to say "exactly one version increment per row per request", which `routes/clock.py:25-47` falsifies — the expiry sweep calls `store.touch(installer)` once **per expired credential**, so a firm with two expiring licences moves +2 in one request. I narrowed the sentence to scope the claim to the cascade release sweep only.

## Partition coverage

All five assigned modules scanned exhaustively, each read in full. Both hand-offs from pass 3 are discharged. `services/calc.py`, `fields.py`, `store.py`, `routes/helpers.py`, `routes/measurements.py`, `routes/network.py` and `routes/clock.py` were read for cross-reference only and not edited.

## Pipeline complete — final orchestrator verification — 2026-09-05T14:12:00.000Z

Step 9 wrote `workspace/PRD_COMPLETED.md`. Aggregate over the four passes: **65 edits** (45 ambiguity-pins, 20 mismatch-revisions), no new sections, line count held at 485 throughout.

Orchestrator checks, all passing:
- `PRD.md` 485 lines / 121,666 bytes → `PRD_FINALIZED.md` 485 / 122,794 → `PRD_COMPLETED.md` 485 / 147,791 (+21.5% bytes over PRD.md).
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → DIFFERS (58 changed lines). A byte-identical Step 9 output would have meant the scan never ran; it did run.
- `PRD_COMPLETED.md` still ends on the final `ERR_NOT_CANCELLABLE` row of §5 — no trailing section lost to an output-cap truncation across four editing passes.
- §4 endpoint table: 76 rows. §5 error catalogue: 47 rows. Both intact.
- Final 8-round sweep artifacts present and green: `results.1..8.json` each 166/166, failed=0.
- Storage-purity re-audit of `implementation/`: zero hits for `sqlite|json.dump|pickle|open(` across all .py files, so state is in-memory only and `start.sh` re-invocation wipes it.
- Exactly one `worklog.md` in the task tree (at the task root) — no stray copy drifted into `workspace/` from a `cd`-shifted append.
