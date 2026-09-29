# Worklog — task_2879_essential_air_service_subsidy_program

## Step 1: Create task directory — 2026-09-05T10:38:45.803034696Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2879_essential_air_service_subsidy_program and its workspace/ subdirectory. Index 2879 was pre-assigned by the orchestrating prompt; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-05T12:20:14.878718220Z

All three scaffold artifacts for task 2879 are complete and lint-clean.

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2879_essential_air_service_subsidy_program/`)
- `SCAFFOLD.yaml` — 3034 lines (§1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2668 lines (single top-level `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4316 lines (single top-level `scaffold_corner_design`)

**Lint verdict** (`scaffold_lint.py <task dir>`), verbatim:
```
Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  1210

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Scaffold shape** — domain `essential-air-service-subsidy`, prefix `/eas`, flat topology, `multi_party_negotiation` + `ledger_reconciliation`, cyclic state machines, role model `segregation_of_duties`, layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / selector_policy`, consistency `immediate`.
- **14 entities**: Community, Carrier, AircraftType, FuelIndex, EligibilityDetermination, Solicitation, Proposal, CommunityPreference, ServiceAgreement, ServicePeriod, SubsidyPayment, PerformanceReview, TerminationPetition, RateRenegotiation.
- **51 endpoints** (25 GET / 26 POST), **10 state machines / 69 transitions**, 2 OCC rules (`preference-filing-stale-solicitation`, `period-amend-stale-agreement`), 2 invariants, 32 validations, 54 errors, 5 roles (3 opaque + `entity_backed:Community`, `entity_backed:Carrier`).
- **10 calculations**, key rules: eligibility bands (70/210-mile thresholds, 200.00 per-passenger cap, avg-daily-enplanement floor of 10 on the rounded value); `subsidy_payment_amount` as a dual variant (COMPLETED_FLIGHT_PRORATION vs SCHEDULED_FLIGHT_FLAT) with the per-departure rate rounded to cents *before* multiplication, a 5% weather credit, a 2% carrier allowance at a 0.50 penalty rate capped at 25% of the monthly entitlement, and tiered withholding 0/2/5/10% on the period completion factor; `hold_in_premium` tiered on the *pre-premium* net; `carrier_selection_ranking` weighted 0.40 preference / 0.35 subsidy / 0.25 service with components rounded to 4dp before the weighted sum and a cost-first tie-break; `renegotiated_annual_subsidy` (fuel pass-through gallons → justified delta → ceiling → facial 1.25× cap, 180-day cooling-off); `agreement_obligation_ledger` (total_committed = annual×term/12, obligated_remaining identity).

**Instance counts** — §1.8: **25** difficulty instances across 9 rule groups. §1.9: **71** corner instances (54 with full `test_recipe`, 17 `excluded_because` stubs) over the nine mandated sections: entities 13, state_machines 16, calculations 11, validations 10, endpoints 6, errors 5, rbac 4, complexity_layers 5, consistency_model 1. All names unique across both files; every stub's `difficulty_instance` resolves (`rule_id / name` form, as in SKILL.md §1.9); **all 54 error ids are triggered somewhere** across §1.8+§1.9 (verified programmatically). Every money/score literal was pinned with Decimal/ROUND_HALF_UP scripts under `/tmp/task_2879_scaffold/`.

**Orchestrator post-step action**: the subagent reported that `SCAFFOLD.yaml`'s `scenario:` block still opened with the difficulty directive line `Generate task harder than expert level!`. The orchestrator deleted that line and the blank line after it (SCAFFOLD.yaml lines 4-5) before Step 3, and verified via `grep -rn "harder than expert"` across the task dir that no copy remains anywhere. SCAFFOLD.yaml is now 3032 lines.

## Step 3: Copy shared files — 2026-09-05T12:20:14.892232308Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (53 lines).

## Step 4: Generate PRD — 2026-09-05T12:33:47.87125080Z

PRD generation complete.

**Deliverable:** `workspace/PRD.md` — **457 lines / 91,687 bytes**. Nothing else was written into `workspace/`; scratch work stayed in `/tmp/task_2879_prd/`. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

**Section list**
```
# Essential Air Service Subsidy API — Product Requirements Document
## 1. Introduction
## 2. Global Specifications & Program-Wide Principles
### 2.1. User and Role-Based Access Control
### 2.2. API Response Structure  (#### Standard Success Response Format / #### Standard Error Response Format)
### 2.3. Pagination and List Ordering
### 2.4. Common Resource Properties and Nested Path Resolution
### 2.5. The Program's Logical Clock
### 2.6. Validation Order and Rejection Precedence
### 2.7. Numeric Precision and Pinned Rounding Order
### 2.8. Stale-View Protection on Superseding Writes
### 2.9. Segregation of Duties in the Program Office
### 2.10. The Obligation Ledger and Its Conservation Identities
### 2.11. Cascade Discipline
## 3. Business Logic & Workflows
### 3.1. Program Registers and Reference Data
### 3.2. Community Eligibility and the Per-Passenger Cap
### 3.3. Solicitation Rounds and the Proposal Pipeline
### 3.4. Community Preference Filings
### 3.5. The Selection Order, the Award and Agreement Booking
### 3.6. Monthly Service Reporting and Departure Reconciliation
### 3.7. Certification, Subsidy Computation and Cash Movement
### 3.8. Performance Review, Carrier Standing and Enforcement
### 3.9. Termination Petitions, the Hold-In Requirement and Agreement Release
### 3.10. Rate Renegotiation on Fuel and Cost Grounds
## 4. Endpoint Definitions
## 5. Error Code Catalogue
```

**Coverage (all mechanically verified against SCAFFOLD.yaml)**
- Endpoints: **51/51** rows in §4 (exactly 4 columns: Method, Path, Description, Authorized Role(s)); every scaffold path present.
- Errors: **54/54** rows in §5 (exactly 2 columns: Error ID, HTTP Status Code), and all 54 IDs are also raised in §3 prose at their triggering condition.
- Calculations: **10/10** documented as prose formulas, including both dual-variant pairs (`subsidy_payment_amount`: COMPLETED_FLIGHT_PRORATION vs SCHEDULED_FLIGHT_FLAT; `carrier_completion_factor`: STRICT vs ADJUSTED) and the 4 pinned rounding orders in §2.7.
- Entities 14/14 — **133/133** distinct entity field names appear verbatim in backticks (0 missing).
- Endpoint inputs: 59/59 body fields + 21/21 query parameters present verbatim (0 missing).
- State machines 10/10, all 69 transitions; **every enum value and state name appears verbatim** (0 missing after fixing the last gap — `ACCEPTED`, the terminal `RateRenegotiation` state, is now named in §3.10).
- Validations 32/32; roles 5/5 named.

**Hard Contracts**
- Contract 1 (Field-Name Coverage): PASS — 133 entity fields, 59 body inputs, 21 query params, 13 preview output-shape fields, 0 missing.
- Contract 2 (Rule Coverage): PASS — validation precedence ladder (§2.6), both OCC rules with `expected_solicitation_version` / `expected_agreement_version` → `ERR_STALE_VERSION` 412 (§2.8), cascades (§2.11), both named invariants `program_obligation_conservation` and `departure_count_conservation` (§2.10), logical clock default `2026-08-01T00:00:00Z` (§2.5).
- Contract 3 (§3 Path Purity): PASS — 787 backticked tokens scanned in §3, 0 `/`-leading tokens, 0 bare HTTP methods, 0 method+path pairs.

No Hard Contract/PASS text was written into PRD.md (grep count 0).

**Three scaffold ambiguities resolved deterministically in prose** (worth knowing for test generation): (a) eligibility determinations are admissible only from `REGISTERED`/`ELIGIBLE`/`INELIGIBLE`, otherwise `ERR_COMMUNITY_NOT_ELIGIBLE`; (b) `distance_band` and `latest_determination_outcome` refresh on every determination while `subsidy_per_passenger_cap_usd` refreshes only on an eligible outcome; (c) a direct TERMINATE over an unsettled `REPORTED`/`CERTIFIED` month is refused with `ERR_AGREEMENT_NOT_ACTIVE` (the scaffold nominated no dedicated error).

**Orchestrator truncation check (per the known doc-generator failure mode):** independently verified — file is 456 lines / 91,687 bytes, §4 contains 51 endpoint rows plus 2 table-header rows, §5 contains 54 `ERR_` rows, and the last line is the final `| ERR_OBLIGATION_EXCEEDED | 422 |` table row, i.e. a real section boundary rather than a mid-sentence cut. No regeneration needed. Also grepped PRD.md for `harder than expert`, `scaffold`, and `test_recipe` — zero hits, so the difficulty directive did not leak.

## Step 6: Generate implementation — 2026-09-05T13:04:49.537619298Z

The implementation is complete, byte-compiles, boots clean from a fresh process, and passes an end-to-end smoke test across every module.

## Modules (all under `.../task_2879_essential_air_service_subsidy_program/workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `app.py` | 78 | app factory, 7 blueprint registrations, `ApiError` + 400/404/405/415/500 envelope handlers, `PORT` bind |
| `errors.py` | 153 | 57 error IDs, `HTTP_STATUS` map, `fail()` |
| `db.py` | 201 | in-memory `Store` (14 tables), logical clock default `2026-08-01T00:00:00Z`, ISO-8601 3-digit formatter/parser, month arithmetic, `Decimal` quantizers, `base_row`/`touch` |
| `response.py` | 122 | envelope, `req_` ids, pagination (limit 1–100 default 10) |
| `validation.py` | 163 | body parse with `parse_float=Decimal`, typed field readers, absent-vs-null rules |
| `auth.py` | 74 | header auth, 5 roles, `endpoint()` decorator (ladder rungs 1–2), `require_owner` |
| `serializers.py` | 169 | field-ordered projections for all 14 registers |
| `calc.py` | 417 | all 9 named calculations with the 4 pinned rounding orders |
| `lookups.py` | 110 | rung-4 resolvers, one 404 per register |
| `cascades.py` | 123 | replacement solicitations, obligation release, hold-in chain, carrier headline/streak, count ±1 |
| `routes/reference.py` | 338 | clock + communities, determinations, carriers, aircraft types, fuel indices (15 endpoints) |
| `routes/solicitations.py` | 345 | rounds, preference filings, ranking preview, selection order + agreement booking (7) |
| `routes/proposals.py` | 173 | proposals and the gated SUBMIT (5) |
| `routes/agreements.py` | 175 | status actions, performance reviews + enforcement (5) |
| `routes/periods.py` | 381 | periods, report/amend, dual-variant preview, certify, payment actions (10) |
| `routes/petitions.py` | 173 | termination petitions, hold-in vs immediate grant (5) |
| `routes/renegotiations.py` | 233 | fuel/cost renegotiation, action-level role split, ACCEPT ledger re-booking (4) |

Plus `requirements.txt` (Flask) and `start.sh` (reads `$PORT`, guarded pip install, `exec python3 app.py` in the foreground). Total 3428 lines. No `__pycache__`, no data files — storage is dicts only, nothing seeded.

**Endpoints wired: 51** — enumerated from `app.url_map`, matching the PRD §4 table and the SCAFFOLD endpoint block exactly (`/_clock/set_current_utc` + 50 under `/eas`).

## Smoke test (fresh server on a random high port, killed by exact PID)

Full happy path plus failure ladder, all correct:
- clock default reads `2026-08-01T00:00:00.000Z`; `set_current_utc` moves it
- 401 unauthenticated / 403 wrong role / 403 `ERR_FORBIDDEN_RESOURCE_OWNER` on a carrier acting for another carrier
- community create → determination (`UNCAPPED`, avg daily 13.70, `ELIGIBLE`, community v1→v2) → 409 duplicate `code` → 400 bad `code` → 404 not found → pagination meta and 400 on `limit=500`
- carrier, aircraft type, fuel index; solicitation → proposal (projected pax 14040, per-pax 128.21) → SUBMIT → preference filing (v2) → 412 `ERR_STALE_VERSION` on replay → 409 award-before-close → `ERR_SEGREGATION_OF_DUTIES` when the certifying analyst's id issues the order → award books the agreement (min_monthly_seats 3120, annual_block_hours 1872.0, committed 1800000.00, obligated 1800000.00)
- period open → 409 `ERR_PERIOD_SEQUENCE_GAP` for 2026-10 → 422 unbalanced counts → report (factor 0.9400, cumulatives updated) → preview both variants → certify emits the payment (entitlement 150000.00, rate 1500.00, credited 97, gross 145500.00, adjustment 750.00, withholding 2% = 2895.00, net 141855.00) → APPROVE → 403 same-user DISBURSE → DISBURSE by a second admin moves the ledger to disbursed 141855.00 / obligated 1658145.00 (conservation invariant holds)
- performance review: STRICT tier `WATCH`, quality 93.51, carrier headline + `consecutive_watch_count` 1, `action_taken` `NONE`
- petition FILED → UNDER_REVIEW → DENIED with note and `decided_by_user_id`
- renegotiation: 422 cooling-off before day 180, 400 on the facial 1.25× cap, 422 `ERR_MISSING_FUEL_INDEX` for an unpublished month, filing, 409 already-open, `ERR_UNAUTHORIZED` both ways on the COUNTER/REVISE role split, COUNTER → REVISE (revision_count 1) → ACCEPT (approved = min(ceiling, requested), `rate_effective_from` advanced, `rate_effective_to` untouched)
- TERMINATE releases the obligation (committed → 141855.00 = disbursed, obligated → 0.00) and settles the community back to `ELIGIBLE` with `active_agreement_count` 0
- 404 unknown path and 405 bad method both return the error envelope

Two notes on deliberate spec readings: where PRD prose conflicts with the §2.6 ladder the ladder wins (carrier standing before retired aircraft before window closed; departure balance before no-scheduled-departures), and `GRANT_IMMEDIATE` deliberately does **not** release the obligation ledger (per the SCAFFOLD side-effect list) — only direct TERMINATE and the hold-in release chain do. Test isolation was maintained throughout: only `INSTRUCTION.md`, `SCAFFOLD.yaml` and `PRD.md` were read, and `worklog.md` was not touched.

**Orchestrator note:** Steps 5 and 6 were launched as concurrent background subagents. Step 6 finished first and reported cleanly; it never had `test_suite/` available to read (the directory was still empty at its start), so physical test isolation held.

## Step 5: Generate unit tests — 2026-09-05T13:33:45.363380278Z

All 17 test files are on disk, verified, and the suite is internally consistent.

## Important correction to the premise I was given
The six translation subagents were **not** dead — they were alive and productive the whole time. Between 13:06 and 13:27 they wrote the 15 files I had been told to re-author, and all six returned full completion reports. I had already written `test_01`/`test_02`; re-writing `test_03`–`test_17` myself would have clobbered files they were mid-append on, so I stopped, let them finish, and did the finish-condition verification plus two mechanical repairs instead.

## `test_suite/`

| file | lines | tests |
|---|---|---|
| test_01_payment_and_completion_variants.py | 219 | 5 |
| test_02_combinatorial_formulas.py | 297 | 8 |
| test_03_non_linear_state_machines.py | 563 | 9 |
| test_04_transitive_cascades.py | 428 | 8 |
| test_05_priority_pair_conflicts.py | 277 | 6 |
| test_06_boundary_precision.py | 403 | 9 |
| test_07_cross_entity_state_dependency.py | 347 | 8 |
| test_08_resource_temporal_overlap.py | 298 | 6 |
| test_09_compensating_invariants.py | 412 | 7 |
| test_10_entity_registers.py | 527 | 15 |
| test_11_state_machine_paths.py | 944 | 21 |
| test_12_calculation_corners.py | 531 | 11 |
| test_13_validation_corners.py | 894 | 22 |
| test_14_endpoint_corners.py | 673 | 11 |
| test_15_error_catalogue.py | 530 | 10 |
| test_16_rbac_and_segregation.py | 559 | 11 |
| test_17_complexity_and_consistency.py | 386 | 6 |

**173 tests.** Queue A (Difficulty) **66**, Queue B (Corner) **107**. Per rule: dual_variant 5, combinatorial 8, non_linear_state_machine 9, transitive_cascade 8, priority_pair 6, boundary_precision 9, cross_entity 8, resource_temporal 6, compensating_invariant 7; entities 15, state_machines 21, calculations 11, validations 22, endpoints 11, errors 10, rbac 11, complexity_layers 4, consistency_model 2.

## Verification I ran myself
- **79 / 79 non-stub instances covered** (25 Difficulty + 54 Corner), every Difficulty instance has >=2 tests, every Corner instance >=1.
- Every file `ast.parse`s and imports cleanly with the task dir on `sys.path`; **`pyflakes` is clean on all 17 files** (no undefined or unused names).
- 173 tests, 173 `Design:` tags — exactly one per test, always the last docstring line, every tag resolving 1:1 to a real yaml `name:`; **no `excluded_because:` stub translated**.
- Every one of the 173 citations verified byte-for-byte present in `workspace/PRD.md`, single physical line, no ellipsis. No section-sign, "scaffold", "design index", `xfail` or skip mark anywhere.
- No duplicate test-function name across the suite. `conftest.py`, `test_helpers/` and `worklog.md` untouched; nothing written under `workspace/`; `__pycache__` cleaned.

## Two repairs I made
1. **31 citations were wrapped across physical lines** (10 in test_12, 21 in test_13), which breaks the `grep -F` greppability rule. I joined each onto one line after asserting the de-wrapped text is verbatim in the PRD — text unchanged.
2. **9 files used `from test_helpers.constants import *`** (plus 5 unused `import pytest`). Replaced with explicit name lists derived from actual use; pyflakes then went clean.

## Skipped instances
None by the PRD-first filter — every non-stub instance passed. The only exclusions are the **17 `excluded_because:` corner stubs**, left untranslated as instructed: 1 in entities, 5 in state_machines, 6 across calculations/validations, 2 in endpoints, 3 in complexity_layers.

## PRD-first overrides Step 7 should know about (yaml was wrong, PRD asserted)
- `rate_effective_to` for a 24-month term from 2026-08-01 is **2028-08-01T00:00:00Z** (yaml said 2027).
- Renegotiation trigger-field incoherence -> **`ERR_MISSING_FUEL_INDEX` / 422** (yaml said 400 `ERR_INVALID_REQUEST`).
- Certify is an **action returning 200** with the mutated period, not a 201 creation; payments are fetched via `GET /eas/subsidy-payments?service_period_id=...`.
- The yaml's cooling-off recipe was self-refuting (filed at the award instant); rewritten to measure from `rate_effective_from` — 2027-01-27 refused / 2027-01-28 admitted.
- `proposal_withdrawal_leaves_evaluation_dimension_frozen`: runner-up scores **80.0000**, not the yaml's 60.0000 (the filing ranks it 2 of 2, so preference points are 50.0000, not 0).
- Reporting against a non-ACTIVE/HOLD_IN agreement is `ERR_AGREEMENT_NOT_ACTIVE` at **409**; four invalid four-character community codes replaced with legal three-letter codes; a 0/0 load-factor month re-based to `seats_offered=114` so the division is defined.

## One flakiness caveat
`test_01_payment_and_completion_variants.py::test_adjusted_basis_excuses_weather_and_lifts_the_carrier_to_compliant` creates the STRICT and ADJUSTED reviews at the same logical instant, so its trailing carrier-headline assertions rest on a `created_at` tie. If it flakes in Step 7 the fix is to advance the clock between the two reviews or split the arm into its own test — not to weaken the assertion.

**Orchestrator note on the mid-step intervention:** at 13:03 the Step 5 agent returned having delegated to six children, and `test_suite/` then held only `conftest.py`, which matched the known "generator died mid-run" signature. Per the resume-rather-than-respawn rule the orchestrator SendMessage'd the SAME agent a computed to-do list instead of spawning a fresh one. The agent's diagnosis above is correct — its children were in fact still alive and writing — and because it was resumed rather than replaced it was able to detect that and stand down rather than clobber in-flight files. Both test directories are at the task root (`<task_dir>/test_helpers/`, `<task_dir>/test_suite/`), not under `workspace/`; verified by `ls`.

## Step 7: Run tests and iterate — 2026-09-05T14:02:34.31253522Z

Clean sweep achieved.

## Summary

**Iterations run:** 2 (iteration 1 = baseline diagnosis; iteration 2 = verification after fixes).

Iteration 1 was fully deterministic — all 8 rounds reported identical `148 passed / 25 failed / 173 total`, so there was no flakiness to chase, only 25 real defects. The union of failures collapsed into four root causes.

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence and survived the unique-derivability check.

**Fixes applied to `implementation/`** (both in `workspace/implementation/routes/periods.py`):

1. `certify_period()` — was returning `response.created(serializers.payment(payment))` (201 + the payment row). PRD 4 says creation endpoints answer 201 and "*Action endpoints that drive a state machine return the mutated resource in `data`*", naming exactly two exceptions (preference filing, selection order); certify is not one of them. Changed to `response.ok(serializers.period(period))`. This single bug caused **22 of the 25 failures**: 8 surfaced directly as `Expected 200, got 201`, and 14 more surfaced as the misleading `AssertionError: No subsidy payment found for period <id>` — the fixture `certified_month()` assigns the certify response to `period`, so it was then passing the *payment's* id into `payment_for_period()` and filtering `service_period_id` against a nonexistent period.
2. `create_period()` — the duplicate-month check ran *after* the sequence check, so re-opening an existing month always answered `ERR_PERIOD_SEQUENCE_GAP` and `ERR_DUPLICATE_PERIOD` was unreachable dead code. PRD 3.6 states both outcomes in one sentence ("*Any other month is refused with `ERR_PERIOD_SEQUENCE_GAP`, and re-opening a month that the agreement already has is refused with `ERR_DUPLICATE_PERIOD`*"), and since an already-recorded month can never be the month immediately following the greatest recorded month, the duplicate check must precede the sequence check for the catalogued error to be reachable at all. Reordered.

**Fixes applied to `test_suite/`** (test bugs per STEP 2, both made the test *more* faithful to PRD):

3. `test_15_error_catalogue.py::test_unknown_ids_return_the_resource_specific_not_found_error` — asserted `response.json()["success"] is False`, raising `KeyError: 'success'`. PRD 2.2's error envelope has exactly three top-level keys (`meta`, `response_type`, `data`) and no `success` field. Replaced with the PRD-backed `response_type == "error"` assertion; the surrounding distinct-not-found-id assertions were untouched.
4. `test_13_validation_corners.py::test_trigger_type_and_its_companion_field_must_agree` — two calls passed the same argument both positionally and by keyword (`fuel_renegotiation_payload(..., "2027-01", ..., fuel_index_month=None)`), a hard `TypeError` before any request was issued. Rebuilt those two payloads through the factory and `.pop()`ed the field being omitted, preserving the intended "omits the required field" shape.

**Fixes applied to `test_helpers/`:** none needed.

**Final tally:** 173 / 173 passing in **all 8 parallel rounds** (`results.1.json` ... `results.8.json`, each `passed 173 / failed 0 / errors 0`). The flakiness risk the generator flagged — `test_adjusted_basis_excuses_weather_and_lifts_the_carrier_to_compliant` and its `created_at` tie between the STRICT and ADJUSTED reviews — passed in all 8 rounds and needed no intervention. `worklog.md` was not touched.

**Orchestrator verification:** independently confirmed from the eight `results.$i.json` files on disk that every round reports `passed == total == 173`. The sweeps ran via the pre-staged `workspace/sweep.sh` under `setsid nohup`, so no round was reaped; iteration 1's failure set being byte-identical across all 8 rounds is itself the proof that the failures were deterministic defects rather than CPU-contention artifacts. Step 8 will NOT be skipped: Step 7 applied 2 `implementation/` fixes, so PRD silences exist at those sites.

## Step 8: Finalize PRD — 2026-09-05T14:05:13.713123536Z

`PRD_FINALIZED.md` written. **456 lines -> 456 lines (0.0% line delta)**; 3 lines revised in place, no lines added or removed, no new sections.

### Changes

- **2.6 (validation ladder, rungs 20-21)** — revise — swapped the two rungs so `ERR_DUPLICATE_PERIOD` (now 20) precedes `ERR_PERIOD_SEQUENCE_GAP` (now 21) — `routes/periods.py:56-65`
- **3.6 (opening a month)** — revise — reworded the one sentence that states both outcomes so the duplicate-month check is explicitly evaluated *before* the sequencing check; kept both error codes and the "expected next month" definition intact — `routes/periods.py:56-65`
- **3.7 (certification)** — insert — one appended clause pinning that certification, despite creating a payment row, answers **200 OK with the mutated service period** in `data`, and the payment is read back through the subsidy-payment endpoints — `routes/periods.py:291`

`<step_7_diff>` items 3 and 4 (the `success`-key assertion in `test_15_error_catalogue.py` and the duplicate positional/keyword argument `TypeError` in `test_13_validation_corners.py`) produced **no PRD edit** — both are pure test/fixture bugs against behavior PRD.md already determines verbatim (2.2's three-key error envelope; 3.10's trigger-field coherence).

### Per-edit pre-edit search log

**Edit 1+2 (ladder swap + 3.6 wording) — one subject, two sites**
- (a) Subject: relative precedence of `ERR_DUPLICATE_PERIOD` vs `ERR_PERIOD_SEQUENCE_GAP` when opening a service period.
- (b) Paths enumerated: `grep -rn "DUPLICATE_PERIOD\|PERIOD_SEQUENCE_GAP\|DUPLICATE_RESOURCE" --include=*.py` over the whole implementation. Exactly one raise site each, both in `create_period()` (`routes/periods.py:60`, `:64`); read the full function including `lookups.periods_of_agreement`, `month_add`, `month_of` usage. Confirmed the duplicate scan is scoped to *the same agreement only*, and that `ERR_DUPLICATE_RESOURCE` (`routes/reference.py:61,188,276,321` — community `code`, carrier `certificate_number`, aircraft `code`, fuel `index_month`) is a wholly separate rung 22 untouched by the swap. Verified the swap is adjacent-only, so no other rung's relative order moves.
- (c) Wording adjustment: avoided saying the duplicate check is "the first check" (validation, path lookup and body FK resolution all still precede it in `create_period`); scoped the claim to precedence *over the sequencing check* only. Also avoided asserting the duplicate scan is global — kept it as "a month that the agreement already has", matching the per-agreement scope.

**Edit 3 (certify returns 200 + period)**
- (a) Subject: HTTP status and `data` payload of `POST /eas/service-periods/{id}/certify`, and by extension the 4 creation-vs-action classification.
- (b) Paths enumerated: `grep -rn "response\.created\|response\.ok(" routes/ *.py` — full census of all 52 return sites, plus `response.py:56-70` (`ok`/`created`/`listing`). The 13 `201` sites are proposal draft, solicitation open, **preference filing** (`solicitations.py:165`, returns solicitation), **selection order** (`solicitations.py:345`, returns agreement), period open, community, determination, carrier, aircraft type, fuel index, renegotiation filing, petition filing, **performance review** (`agreements.py:175`). Also checked the parallel cases of *actions that create rows but answer 200*: petition `GRANT_WITH_HOLD_IN` (`routes/petitions.py:137`) creates a replacement solicitation yet returns the petition at 200, and payment `DISBURSE`/`REVERSE` (`periods.py:363,386`) return the payment. This confirms "creates a row" does not imply 201 anywhere in this codebase, so certify's 200 is the house pattern rather than an exception.
- (c) Wording adjustment: phrased the clause as a local statement about certification ("certification is an action on the period rather than a creation endpoint") instead of amending 4's global "Creation endpoints answer 201" sentence or its "two deliberate exceptions" count — editing 4 would have implied a third exception and risked mis-describing the preference-filing and selection-order 201s that Step 7 never touched.

**Orchestrator verification:** confirmed PRD_FINALIZED.md exists and is NOT byte-identical to PRD.md — both files are 456 lines, PRD.md 91,687 bytes vs PRD_FINALIZED.md 92,106 bytes, and `diff` reports 8 changed lines (4 revised lines in place, not the 3 the subagent counted; line count and section structure are unchanged either way). Step 8 was correctly not skipped since Step 7 applied 2 `implementation/` fixes.

## Step 9: Complete PRD — 2026-09-05T14:37:19.837279245Z

Step 9 was deliberately executed as **three sequential passes partitioned by implementation module**, all editing the one shared `workspace/PRD_COMPLETED.md`. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying and each was handed the list of what earlier passes had already pinned, so the three never duplicated or contradicted each other. Partition: pass 1 = app/errors/db/response/validation/auth/serializers/lookups + routes/reference; pass 2 = calc/cascades + routes/solicitations + routes/proposals; pass 3 = routes/periods + routes/agreements + routes/petitions + routes/renegotiations.

Cumulative size: `PRD_FINALIZED.md` 456 lines / 92,106 bytes -> `PRD_COMPLETED.md` **460 lines / 116,608 bytes** (+4 lines, +24,502 bytes). 29 headers and all 54 error-catalogue rows intact; no new sections. Totals across the three passes: **54 ambiguity-pins, 9 mismatch-revisions**.

### Pass 1 (transport, envelope, validation, serialization, reference data) — 19 pins / 2 mismatches
- 2.1 — insert — ambiguity — both auth headers whitespace-trimmed before use (spaces-only = empty -> 401), role must match one of the five spellings exactly and case-sensitively, trimmed `X-User-ID` is the value used for ownership/audit/SoD — `auth.py:27-38`
- 2.2 — insert — ambiguity — `api_request_id` = `req_` + exactly 20 chars from `A-Z0-9` (24 total), regenerated per response incl. errors — `response.py:22-23,73-78`
- 2.2 — revise — **mismatch** — `api_request_timestamp` is read from the machine's real clock, not the logical clock of 2.5 (which 2.5 blanket-forbade), and is never compared to a stored stamp — `response.py:26-31`
- 2.2 — insert — ambiguity — `message` is diagnostic only, never contractual — `errors.py:142-148`
- 2.2 — insert — ambiguity — every response carries `Content-Type: application/json` and the three keys `meta`/`response_type`/`data` in that order; request bodies parsed as JSON regardless of request `Content-Type` — `response.py:51-53`, `validation.py:26-32`
- 2.2 — insert — ambiguity — the three transport-level uses of `ERR_INVALID_REQUEST` at non-400 statuses (unknown path -> 404, bad method -> 405, uncatalogued -> 400), they precede the 2.6 ladder, and the server never answers 5xx — `app.py:38-67`
- 2.3 — insert — ambiguity — `limit`/`offset` must parse as integers (empty string, `2.5`, non-numeric rejected; whitespace trimmed); undeclared query params ignored — `response.py:85-109`
- 2.3 — insert — ambiguity — creation sequence is the final tie-break behind every declared ordering (logical-clock `created_at` ties are the norm) — `db.py:200-201`, `routes/reference.py:100,337`
- 2.3 — insert — ambiguity — filters are exact case-sensitive equality applied before `total_count`; an unmatched or out-of-enum value yields an empty page rather than an error; `filing_sequence` is the one integer filter — `routes/reference.py:94-99,155-157,167-172`, `routes/solicitations.py:174-177`
- 2.4 — insert — ambiguity — `created_at` always rendered with trailing `Z`; sub-millisecond precision in a set clock truncated (not rounded) in stamps while the clock keeps full precision for comparisons — `db.py:59-64,75-90`
- 2.4 — insert — ambiguity — projections are fixed and total: `id`, own fields, `created_at`, then `updated_at`/`version` where applicable; unset fields as explicit JSON `null`; no extra keys projected — `serializers.py:9-17`
- 2.5 — insert — ambiguity — `to_iso8601` required and parsed like any instant; answers 200 with the one-key object `{"current_utc": ...}` at three fractional digits; clock may move backwards; creates/mutates/versions nothing — `routes/reference.py:34-40`
- 2.6 rung 3 — insert — ambiguity — uniform body parsing: absent/empty body = empty object; non-object or invalid JSON malformed; JSON `null` == absent; undeclared fields ignored; numbers must be JSON numbers (no numeric strings); integer fields reject `21.0`; booleans never accepted for numerics; decimal width is an at-most bound; datetimes need `Z` or `+00:00` — `validation.py:25-149`
- 2.7 — insert — ambiguity — figures are exact decimals internally but emitted as JSON numbers with insignificant trailing zeros stripped (200.00 -> `200.0`), so clients must compare numerically — `response.py:41-48`, `db.py:130-156`
- 2.9 — insert — ambiguity — "latest determination" ties on `created_at` broken by creation sequence — `lookups.py:97-103`
- 3.1 — insert — ambiguity — all fourteen registers boot empty with the clock at its default; nothing seeded, no delete/reset capability — `db.py:38-42`, `app.py:1-5`
- 3.1 — insert — ambiguity — retire takes no body; `note` <=2000 chars accepted but never stored or projected; retirement idempotent and a repeat retire still bumps `updated_at`/`version`; nothing un-retires — `routes/reference.py:299-307`
- 3.1 — revise — **mismatch** — fuel `price_per_gallon_usd` is "at most four decimal places" (PRD said "exactly four"; impl accepts `3.5`, rejects a fifth digit) — `routes/reference.py:318`, `validation.py:101-102`
- 3.2 — insert — ambiguity — `latest_determination_outcome` ties on `created_at` resolved by later creation sequence — `lookups.py:97-103`
- 3.8 — insert — ambiguity — standing `note` <=2000 chars accepted but not stored/projected; endpoint answers with the mutated carrier — `routes/reference.py:218,254`
- 3.8 — insert — ambiguity — manual SUSPEND cascade stops at agreements (community `status`/`active_agreement_count` untouched, no replacement solicitation, unlike the DEFICIENT review branch); DEBAR reaches only DRAFT proposals — `routes/reference.py:227-245`
- 4 intro — insert — ambiguity — trailing slash equivalent to none; the table is exhaustive and off-table paths/methods resolve per the end of 2.2 — `app.py:21`

Pass 1 also machine-diffed `errors.py`'s HTTP_STATUS against the 5 table: 54/54 ids, zero status mismatches, table left untouched. Every claim was verified against a live server instance (started on port 8791, killed by its own pid).

### Pass 2 (calculations, cascades, solicitations, proposals) — 13 pins / 1 mismatch
- 2.7 — insert — ambiguity — round-half-up on a *negative* quantity is away from zero (-50.005 -> -50.01); reachable via a falling fuel index — `calc.py:386-398`, `db.py:143`
- 3.1 — insert — ambiguity — `active_agreement_count` floored at 0: a decrement against a counter already at 0 leaves it at 0 — `cascades.py:35-37`
- 3.2 — insert — ambiguity — the enplanement floor is compared against the **recorded two-decimal** `avg_daily_enplanements`, not the raw quotient (9.997 -> 10.00 clears it) — `calc.py:73,77`
- 3.3 — insert — ambiguity — `closes_at` re-rendered into the API stamp format on store (sub-ms truncated, `+00:00` reads back as `Z`), and a `closes_at` already behind the clock is accepted — `solicitations.py:34,42`, `db.py:59`
- 3.3 — insert — ambiguity — drafting a proposal is ungated beyond shape/existence/ownership: any solicitation status, any carrier standing, a retired aircraft type, a sub-minimum bid — all gates land on submission — `proposals.py:42-48`
- 3.3 — revise — **mismatch** — the SUBMIT gate narrative listed `closes_at` *before* carrier standing and retired equipment; impl (and 2.6 rungs 8/12/16) evaluate standing -> retired -> window. Reordered and added the explicit precedence note — `proposals.py:108-134`
- 3.4 — insert — ambiguity — filing shape rules: `expected_solicitation_version` non-negative integer, each `rankings` entry a JSON object with non-empty `proposal_id` and `rank` >= 1, `rationale` <= 2000 chars — all `ERR_INVALID_REQUEST` (rung 3), *not* `ERR_INVALID_PREFERENCE_RANKING` — `solicitations.py:107-118`
- 3.4 — insert — ambiguity — filing has **no solicitation state gate** (admissible from OPEN/CLOSED/AWARDED/CANCELLED); with zero submitted proposals an empty `rankings` array succeeds, creating no row but still bumping `preference_filing_count` and `version`; body-FK existence precedes ownership — `solicitations.py:120-165`
- 3.5 — insert — ambiguity — ranking preview: `excluded_proposal_ids` in creation order; admissible at any solicitation status; an empty candidate set is **not** an error there — `candidate_count` 0, `top_proposal_id`/`top_composite_score` `null`, `ranked_proposal_ids` empty — `solicitations.py:185-202`, `calc.py:124-138,152`
- 3.5 — insert — ambiguity — `rate_effective_to` preserves day-of-month except where the target month is too short (then its last day); `baseline_fuel_index_usd` is `null` when no index exists for the award month, which is not an award-time error but later blocks a fuel renegotiation — `solicitations.py:251,307-308`, `db.py:97-102`, `calc.py:378-381`
- 3.5 — insert — ambiguity — the re-entry buffer takes the **greatest** `terminated_at` when the winning carrier holds several terminated agreements for the community; agreements without a stamp are skipped; other communities/carriers never enter the sweep — `solicitations.py:264-274`
- 3.5 — insert — ambiguity — the hold-in release does **not** decrement `active_agreement_count` a second time and does **not** run the 3.9 fall-back settlement; the award's +1 is the whole counter arithmetic — `cascades.py:87-93`, `solicitations.py:338-343`
- 3.8 — insert — ambiguity — `load_factor` is 0.0000 when summed `seats_offered` is zero — `calc.py:329-332`
- 3.9 — insert — ambiguity — the release settlement fires **only** from `status` exactly `SUBSIDIZED`; a community already in `HOLD_IN` stays there; when the settlement is a no-op the community row is still mutated and version-bumped by the count decrement — `cascades.py:53-63`

Pass 2 observation left deliberately unchanged: 2.6 orders rungs 18/19 (rate-interval overlap, re-entry buffer) ahead of rung 27 (`ERR_NO_ELIGIBLE_PROPOSALS`), while `solicitations.py` necessarily raises 27 first — both later checks need the winner, so the two conditions can never both be live and there is no observable conflict.

### Pass 3 (periods, agreements, petitions, renegotiations) — 22 pins / 6 mismatches
- 2.6 rung 3 — revise — **mismatch** — the 1.25x facial-subsidy check cannot run before identifier resolution, so it alone is evaluated after `agreement_id` resolves (unknown id still -> `ERR_AGREEMENT_NOT_FOUND`) while still preceding ownership; rung 3's closing "before any identifier is resolved" sentence qualified — `renegotiations.py:48-49,142-143`
- 3.8 enforcement — revise — **mismatch** — `action_taken` follows tier+streak alone: PRD read as if a non-`ACTIVE` carrier records `NONE`; impl records `CARRIER_PLACED_ON_PROBATION` on a 3rd consecutive `WATCH` while leaving an already-probationary/suspended carrier's standing alone; the agreement is version-bumped only from `ACTIVE`; a non-`SUBSIDIZED` community keeps its status while still being decremented and bumped — `agreements.py:156-174`
- 3.10 — revise — **mismatch** — removed "floored at zero so a negative submission cannot cut the rate": a negative `documented_cost_increase_pct` is rejected at rung 3, so the floor is unreachable; the 0.10 cap is what binds (over-cap submissions are capped, not refused) — `renegotiations.py:45-46`, `calc.py:390-395`
- 3.7 para 1 + 4 preview row — revise — **mismatch** — the preview is not gated on period status ("for a reported month"/"for a reported period" softened) — `periods.py:199-218`
- 2.8 — insert — ambiguity — `expected_agreement_version` is an integer >= 0; negative/non-integer is rung-3 `ERR_INVALID_REQUEST`, not 412 — `periods.py:167`
- 3.6 — insert — ambiguity — opening a month is ungated on agreement status and touches only the new period (agreement `version` unmoved) — `periods.py:41-82`
- 3.6 — insert — ambiguity — the six counts are non-negative integers (rung 3, before the period resolves); `ERR_PERIOD_NOT_REPORTABLE` wins over `ERR_AGREEMENT_NOT_ACTIVE` — `periods.py:106-146`
- 3.6 — insert — ambiguity — unbalanced beats zero-scheduled; all-zero balances trivially -> `ERR_NO_SCHEDULED_DEPARTURES`; seats/passengers cumulated nowhere; a report bumps the agreement's `version` — `periods.py:113-158`
- 3.6 — insert — ambiguity — amendment is ungated on agreement status; same non-negative-integer shape — `periods.py:163-193`
- 3.7 — insert — ambiguity — `divergence_usd` is the absolute difference; six keys are the whole payload; degenerate `scheduled_departures` 0 -> rate 0.00, credited 0, missing factor scored as 0 (steepest 0.10 tier) — `periods.py:199-218`, `calc.py:216-246`
- 3.7 — insert — ambiguity — `certification_note` accepted but stored/projected nowhere (body optional); only an `OPEN` earlier month blocks; certification ungated on agreement status — `periods.py:227-241`
- 3.7 — insert — ambiguity — certification writes exactly two rows (payment + period); the agreement is read-only there — `periods.py:264-291`
- 3.7 — insert — ambiguity — `reversal_reason_code` required only on REVERSE (validated-then-ignored elsewhere, stored nowhere); reversal records no acting user and carries no segregation-of-duties rule — `periods.py:320-386`
- 3.8 — insert — ambiguity — start>end is `ERR_INVALID_REQUEST` before the agreement resolves; a review may be run whatever the agreement's status — `agreements.py:130-137`
- 3.8 — insert — ambiguity — the new review is part of its own streak history; every review bumps the carrier's `version` even when `COMPLIANT`/unchanged — `agreements.py:150-174`, `cascades.py:96-118`
- 3.8 — insert — ambiguity — `note` accepted but not stored; manual suspension has no community cascade; rung 6 before rung 8 on reinstate; reinstate's community move is conditional and never re-increments the count — `agreements.py:46-81`
- 3.9 — insert — ambiguity — a foreign agreement gives `ERR_FORBIDDEN_RESOURCE_OWNER`; `requested_effective_at` re-rendered into the API stamp format, accepted either side of the clock; filing ungated on agreement status and unlimited per agreement — `petitions.py:33-55`
- 3.9 — insert — ambiguity — the note replaces `decision_note` (omission leaves it `null`); `OPEN_REVIEW` discards it; return-for-info leaves `decided_by_user_id` — `petitions.py:85-109`
- 3.9 — insert — ambiguity — `withdraw_note` not stored; ownership precedes the status check; decision fields untouched — `petitions.py:157-173`
- 3.9 — insert — ambiguity — the immediate grant leaves the obligation ledger exactly as it stands; only direct termination releases it — `petitions.py:130-132` vs `cascades.py:66-76`
- 3.10 — insert — ambiguity — filing ungated on agreement status (only ACCEPT requires live) — `renegotiations.py:35-100`
- 3.10 — insert — ambiguity — `action_note` accepted but not stored — `renegotiations.py:138`
- 3.10 — insert — ambiguity — the revised figure is bounded, strictly positive, 2dp, and subject to the same 1.25x cap measured against the rate in force, refused before state is examined; all four derived figures recomputed on stored trigger inputs — `renegotiations.py:136-179`
- 3.10 — insert — ambiguity — the renegotiation's own state is tested before the agreement's status — `renegotiations.py:182-201`
- 3.10 — insert — ambiguity — remaining months floored at zero (pro-rated delta 0.00) — `renegotiations.py:208-215`

**Deliberate residual gaps declared by pass 3** (all unreachable code paths, so pinning them would document behavior the API cannot exhibit): the `seat_fulfillment` zero-denominator branch in `calc.review_figures` (`min_monthly_seats` is always >= 8 at award); direct termination of a `HOLD_IN` agreement with an `ACTIVE` successor (the award cascade already terminates the predecessor); and `renegotiation_figures`' missing-aircraft-type fallback (`burn = 0`).

**Orchestrator verification:** `PRD_COMPLETED.md` is 460 lines / 116,608 bytes and is **not** byte-identical to `PRD_FINALIZED.md` (456 lines / 92,106 bytes) — the partitioned scan genuinely ran, which is the failure mode this split was designed to prevent. Structure preserved: 29 headings and all 54 `ERR_` catalogue rows still present, file still ends on the final error-table row. `find -newermt` confirms no `.py` file under `implementation/`, `test_suite/`, or `test_helpers/` was modified after the final green sweep, so Step 9 was documentation-only and the 8/8 green result at 173/173 still describes the artifact on disk.

## Pipeline complete
All nine steps finished. Final state: 173 tests, 0 deleted; 8/8 sweep rounds at 173/173; PRD.md -> PRD_FINALIZED.md -> PRD_COMPLETED.md.
