# Worklog — task_2956_physician_practice_acquisition_integration

## Step 1: Create task directory — 2026-09-05T21:57:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2956_physician_practice_acquisition_integration` and its `workspace/` subdirectory. Index 2956 was pre-assigned by the orchestration prompt; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-05T23:46:18.000Z

All three scaffold artifacts are complete and lint-clean.

## Deliverables

| File | Lines |
|---|---|
| `.../SCAFFOLD.yaml` | 2871 |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1898 |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 5408 |

`SCAFFOLD.yaml` holds §1.0–§1.7 only (no design keys); each design file has exactly its single top-level key.

## Domain model

A health system's practice-acquisition desk runs one deal end-to-end across 12 flat entities: `Acquisition` (the aggregate root, carrying two independent state dimensions — a cyclic `deal_status` PROSPECT→DILIGENCE↔BOARD_REVIEW→SIGNED→CLOSED plus a `compliance_clearance` PENDING/CLEARED/FLAGGED/SUSPENDED gate), `Physician`, `ValuationOpinion` (FMV and commercial-reasonableness, each with its own DRAFT→SUBMITTED→ACCEPTED/REJECTED/SUPERSEDED cycle and an `is_pinned` flag), `CompensationPlan` (DRAFT→SUBMITTED→APPROVED→EXECUTED with a COMPLIANCE_HOLD/WITHDRAWN return cycle capped at two revisions), `LiabilityItem`, `PayerContract`, `CredentialingPackage`, `EhrMigrationBatch`, `PatientNotice`, `StaffTransitionOffer`, `BillingConversion`, `ReadinessTask` and `PerformanceReport` — 11 state machines and 48 endpoints in total. Six roles (`DealLead`, `ValuationAnalyst`, `CompensationDesigner`, `ComplianceOfficer`, `IntegrationManager`, and an entity-backed `PracticePhysician`) partition the writes under a segregation-of-duties model: the officer who accepted the pinned opinion cannot approve the plan, a designer cannot approve its own plan, and only the physician named on a plan may execute it. The 19 calculations are integer-cents / basis-point / ROUND_HALF_UP arithmetic over a settable logical clock (default `2026-08-01T00:00:00Z`): dual-variant `fmv_concluded_value` (income Gordon-growth vs. market multiple), `deal_net_consideration` with a synergy tier pinned to gross, dual-basis `compensation_benchmark_percentile` (total cash comp vs. comp-per-wRVU) feeding a 90th-percentile Stark safe harbour, `staff_offer_wage_harmonization` and clamped `retention_bonus_award` drawing on a finite retention pool, an escrow ledger, `comp_true_up`, `credentialing_committee_cycle_key`/`credentialing_projected_effective_date` against per-payer lead-day tables, floored `ehr_reconciliation_match_rate` (9950 bps threshold) and `patient_notice_coverage`, `malpractice_tail_premium`, `hr_staffing_coverage` and the derived `acquisition_readiness_posture`. 47 prioritised validations and a 46-code error catalog enforce the compliance gates; complexity layers are dual-variant calculation, cascading side effects, optimistic concurrency (two `expected_acquisition_version` rules → `ERR_STALE_ACQUISITION_VERSION` 412) and rate/threshold triggers, under `consistency_model: immediate` and `difficulty_level: expert_plus`.

## Instance counts

- **§1.8 difficulty index: 20 instances** across all 9 rule blocks — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.
- **§1.9 corner index: 100 instances (90 full test recipes + 10 stubs)** across all 9 guide sections — entities 16, state_machines 16, calculations 17 (7 stubs), validations 9, endpoints 7 (1 stub), errors 16, rbac 9, cross_cutting_complexity_layers 8 (2 stubs), consistency_model 2.

## Verification

- `scaffold_lint.py` → **`VERDICT: clean lint`** (48 endpoints, 12 entities, 20 §1.8 + 90 §1.9 instances, **957 calls scanned**).
- All three files parse under PyYAML; instance names are unique across the union of both design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name; every stub lacks a `test_recipe` and every non-stub has one; no keys outside the §1.9 schema.
- Error coverage: **all 46 catalog codes are triggered or asserted**, with zero unknown/typo `ERR_` references.
- Forbidden concurrency vocabulary: zero hits. Two pre-existing descriptive uses of "in parallel" (describing the second state dimension, not concurrent requests) were reworded to "independently of" and the file re-linted clean.
- `.scratch/step2/` removed; the parent `.scratch/`, `worklog.md` and `workspace/` were left untouched.

## Flag

The meta-directive line **"Generate task harder than expert level!"** was intentionally **omitted from `scenario:`** — it is an instruction to the generator, not domain content, and would leak verbatim into the downstream PRD (this is a known failure mode). The `scenario:` value is the task-2956 description alone, and the difficulty target is encoded structurally as `complexity_profile.difficulty_level: expert_plus` with four complexity layers, a cyclic state-machine shape, a segregation-of-duties role model and 20 §1.8 difficulty instances.

**Orchestrator verification**: all three files present with the reported line counts; `grep` for "harder than expert" across all three scaffold files returns no hits (directive did not leak); `worklog.md` and `workspace/` survived the subagent intact.

## Step 3: Copy Shared Files — 2026-09-05T23:46:23.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes). No subagent.

## Step 4: Generate PRD — 2026-09-06T00:03:03.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **502 lines**, 113,865 bytes, built as one `Write` plus seven `cat >>` appends (no single-call truncation risk).

**Section outline (headings only)**
```
# Practice Acquisition Integration API — Product Requirements Document
## 1. Introduction
## 2. Global Specifications & System-Wide Principles
### 2.1. User Identity, Roles and the Segregation of Duties
### 2.2. API Response Structure
### 2.3. Pagination
### 2.4. Common Resource Properties and Mutation Semantics
### 2.5. URL Shape and Path Parameter Resolution
### 2.6. The Logical Clock
### 2.7. Optimistic Concurrency on the Acquisition Aggregate
### 2.8. Money, Rates, Precision and Rounding
### 2.9. The Three Dimensions of an Acquisition
### 2.10. The Compliance-Clearance Freeze
### 2.11. Ledger Conservation
### 2.12. Rejection Precedence
## 3. Business Logic & Workflows  (3.1–3.11)
## 4. Endpoint Definitions
## 5. Error Codes
```

**Coverage confirmation** (counts mechanically extracted from SCAFFOLD.yaml, 2871 lines):
- **12 / 12 entities** documented (all `common_fields: false` — only `id` and `created_at`; PerformanceReport's immutability called out).
- **11 / 11 state machines, 78 / 78 transitions** documented.
- **19 / 19 calculations** documented; every calculation output field name appears in backticks and every embedded constant is stated numerically (INTEGRATION_RESERVE_BPS 350, tier ceilings 800,000,000 / 1,500,000,000 / 2,500,000,000 cents with 0/150/275/400 bps, all four specialty benchmark quartile tables, the 99.00 percentile cap and 90.00 safe harbour, TAIL_MIN_MONTHS 60, PATIENT_NOTICE_LEAD_DAYS 30, the 9950-bps reconciliation floor, retry allowance 2, retention tiers/multipliers/floor/cap, payer lead times, retro-billing windows).
- **47 / 47 validations** documented as a single strict-precedence numbered list in §2.12, each with error ID, HTTP status and `applies_to` method+path scope.
- **46 / 46 errors** in the §5 table, all also referenced in prose.
- **48 / 48 endpoints** in the §4 four-column table.
- **6 / 6 roles** documented, with `PracticePhysician` singled out as the only entity-backed identity.
- **2 / 2 concurrency rules** (`expected_acquisition_version` / `ERR_STALE_ACQUISITION_VERSION` / 412) in §2.7 and at both call sites.

**Contract 1 — Field-Name Coverage: PASS.** 169 unique required identifiers (146 entity field names ∪ 117 endpoint input/path/OCC identifiers); 0 missing. A second broader pass over entity fields, enum values, state names, role names, calculation outputs and error IDs also returned 0 missing.

**Contract 2 — Rule Coverage: PASS.** All 47 priority ranks; both OCC rules; all cross-entity side effects and cascades (FMV pinning, plan supersession, `returned_count` increments, clearance FLAG/SUSPEND fan-out, payer denial → credentialing + readiness cascade, batch abort → readiness FAILED, offer accept → coverage → HR task, notices → PATIENT_NOTIFICATION task, close → opinion supersession); every `applies_to` scope; field-level enums/defaults/nullability/ranges; sibling-branch symmetry (the two `→ WAIVED` branches, the three RECONCILE branches, the two failure branches, every escrow-release path). The one Zero-Silence gap in the scaffold — preconditions with no dedicated code (physician-registered, `compliance_clearance` CLEARED at sign/close) — is resolved explicitly to `ERR_INVALID_STATE_TRANSITION` (409) at rank 14.

**Contract 3 — §3 Path Purity: PASS.** 0 backticked path/method tokens in §3 (lines 208–393).

**Mandatory self-check.** `wc -l` = 502. File ends at a real section boundary — the last row of the §5 error table. Verbatim final line: `| ERR_INVALID_REPORT_PERIOD | 422 |`

§2.2 is byte-identical to the doc-generator skill's canonical response-structure file. No fuzzy language. No leak of difficulty/test-targeting vocabulary. The two withheld design files were never opened, grepped, or referenced.

**Orchestrator verification (anti-truncation gate)**: independently ran `wc -l` (502) and `tail -25` on PRD.md — it terminates with a complete `| ERR_INVALID_REPORT_PERIOD | 422 |` table row at a real section boundary, not mid-sentence. Grep for `harder than expert`, `expert_plus`, `test_recipe`, `scaffold_difficulty`, `scaffold_corner` in PRD.md: no hits. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-06T00:43:03.000Z

Implementation is complete, smoke-verified, and the smoke server (PID 3513792) has been killed.

## Files written

`workspace/implementation/` — 25 files, **3913 lines total**:
start.sh 10 | requirements.txt 1 | app.py 101 | clock.py 92 | envelope.py 59 | errors.py 113 | store.py 151 | calc.py 531 | validate.py 249 | machines.py 299 | services.py 237 | serialize.py 137 | enums.py 63 | routes_reads.py 136 | routes_acquisitions.py 294 | routes_physicians.py 51 | routes_valuations.py 164 | routes_comp_plans.py 195 | routes_payers.py 133 | routes_credentialing.py 145 | routes_migration.py 147 | routes_staff.py 115 | routes_billing.py 138 | routes_readiness.py 103 | routes_performance.py 138

`__pycache__` removed; `.scratch/step6/` removed (siblings step5/7/8/9 untouched).

## Coverage (machine-verified where countable)

- **Endpoints 48/48** — Flask `url_map` reports exactly 24 GET + 24 POST (incl. `POST /_clock/set_current_utc`), no extras.
- **Entities 12/12** — `store.KINDS` has 12 in-memory tables.
- **State machines 11/11** — `DEAL_STATUS`, `CLEARANCE`, `OPINION_STATUS`, `PLAN_STATUS`, `NOVATION`, `PACKAGE_STATUS`, `BATCH_STATUS`, `OFFER_STATUS`, `CONVERSION_STATUS`, `TASK_STATUS`, `DISPOSITION`.
- **Calculations 19/19** — all in `calc.py`, Decimal-only with per-component `quantize`.
- **Validations 47/47** — enforced in the PRD §2.12 total order; anything without a dedicated code funnels to rank 14 `ERR_INVALID_STATE_TRANSITION` 409.
- **Error codes 46/46** — `errors.ERROR_STATUS` has 46 entries with PRD §4 statuses.
- **Roles 6/6** — `validate.ROLES`; `PracticePhysician` is entity-backed (`X-User-ID` == `Physician.id`).

Storage is plain dicts only — a grep for `sqlite3`/file writes/`pickle`/`shelve`/`json.dump` found nothing, and there is no seeding anywhere.

## Smoke transcript (PORT=41871, launched with `bash start.sh`)

Auth/schema: no headers → 401 `ERR_UNAUTHENTICATED`; unrecognised role → 401 (per §2.1); wrong role → 403 `ERR_FORBIDDEN_ROLE` before body parsing; empty body → 400 `ERR_INVALID_REQUEST`; `limit=0` and `offset=-1` → 400 (never clamped); unknown id → 404.

Create-then-read: `POST /acquisitions` → 201, `SOURCING`/`PENDING`/`BLOCKED`, `version=1`, `tail_coverage_required=true`, `tail_premium_cents=null`; `GET /acquisitions/{id}` → 200 identical; filtered list → `total_count=1`.

End-to-end deal: DILIGENCE blocked with no physician (409 rank 14) then allowed after `POST /physicians`; duplicate NPI → 409 `ERR_DUPLICATE_NPI`; 3-digit NPI → 400. OCC stale version → 412; `FMV`+`NARRATIVE` → 422 `ERR_OPINION_METHOD_MISMATCH`. FMV market approach: `concluded_value_cents=975000000`, `expires_on=2027-07-01`. Preparer self-accept → 403 `ERR_SEGREGATION_OF_DUTIES`. BOARD_REVIEW consideration chain: price 975000000, reserve 34125000 (350 bps), gross 1036125000, synergy 150 bps → 15541875, net 1020583125, tail 27000000 — arithmetic re-checked by hand against §3.3. Comp plan: total 55800000, per-wRVU 9000, basis `TOTAL_CASH_COMP`, percentile 51.54; SoD reuse of the FMV acceptor → 403; non-owner EXECUTED → 403 `ERR_NOT_PLAN_OWNER`; physician version bumped on both APPROVED and EXECUTED (derived `employment_status` cascade). Staff offer: uplift 432000 (RN 600 bps), PTO 138462, floor not applied, offered 7770462, bonus 777046; EXTENDED committed the pool (available 4222954, coverage 25.0) and RESCINDED released it back to 5000000/0.0. Liability: `ASSUMED` on a `STARK_SELF_DISCLOSURE` asset deal → 422 `ERR_LIABILITY_DISPOSITION_NOT_PERMITTED`; `INDEMNIFIED` with no cap → 400; `ESCROWED` moved escrow to 250000/59750000. Readiness: duplicate code → 409, blank waiver justification → 422, posture walked BLOCKED → READY → AT_RISK exactly per §3.10. Clock: bad instant → 400; set → `{"current_utc": "2026-09-15T08:30:00.000Z"}` (fixed 3-digit sub-second width everywhere). Freeze: `FLAGGED` blocked `POST /liability-items` with 403 `ERR_COMPLIANCE_CLEARANCE_BLOCKED` while exempt `POST /readiness-tasks` still returned 201. Pagination: `limit=1` → 1 row of `total_count=2`; `limit=1&offset=1` → `has_more=false`.

Two deliberate spec-conflict decisions worth flagging to Step 7 if any test disagrees: (1) the clock endpoint returns `{"current_utc": ...}` (§2.6 and SCAFFOLD say so; §4 calls the data object empty); (2) rank 19 safe-harbour is evaluated for target `APPROVED` and `EXECUTED` per §2.12, which is provably a no-op for `APPROVED → EXECUTED`.

**Orchestrator note**: Steps 5 and 6 were launched back-to-back as background agents so they ran concurrently; the impl generator was additionally given an explicit hard prohibition on reading `test_suite/`, `test_helpers/`, or either SCAFFOLD design index, since those files could materialise on disk mid-run.

## Step 5: Generate Unit Tests — 2026-09-06T02:28:36.000Z

Step 5 is complete. `test_18_immediate_consistency.py` is finished and the whole suite passes the full verification battery.

## Files written (all at the task root, none under `workspace/`)

`test_helpers/` — `__init__.py` 96 | `api_client.py` 358 | `api_errors.py` 165 | `assertions.py` 285 | `constants.py` 374 | `factories.py` 425 | `fixtures.py` 639 | `test_users.py` 132 | `types.py` 282

`test_suite/` (file | lines | tests | instances):
`conftest.py` 72 | – | – ; `test_01_valuation_and_benchmark_variants.py` 236 | 6 | A×2 ; `test_02_money_composition_formulas.py` 255 | 6 | A×3 ; `test_03_lifecycle_state_machines.py` 308 | 8 | A×3 ; `test_04_cascading_side_effects.py` 357 | 8 | A×2 ; `test_05_rejection_precedence_conflicts.py` 272 | 5 | A×2 ; `test_06_boundary_precision.py` 275 | 8 | A×2 ; `test_07_cross_entity_gates.py` 289 | 6 | A×2 ; `test_08_temporal_overlap_and_capacity.py` 359 | 8 | A×2 ; `test_09_ledger_invariants.py` 334 | 7 | A×2 ; `test_10_entity_shapes_and_defaults.py` 610 | 16 | B×16 entities ; `test_11_state_machine_transitions.py` 781 | 17 | B×16 state_machines ; `test_12_derived_calculations.py` 903 | 18 | B×10 calculations ; `test_13_request_validation_precedence.py` 848 | 21 | B×9 validations ; `test_14_endpoint_behaviour_and_listing.py` 656 | 12 | B×6 endpoints ; `test_15_error_conditions.py` 1862 | 36 | B×16 errors ; `test_16_role_authorisation.py` 714 | 13 | B×7 rbac ; `test_17_concurrency_and_ledger_layers.py` 1034 | 12 | B×6 cross_cutting ; `test_18_immediate_consistency.py` 421 | 4 | B×2 consistency_model

**211 tests, 13,342 lines total.** `pytest --collect-only` collects all 211 with no collection errors; `pyflakes` is clean except the six intentional fixture re-exports in `conftest.py`.

## Design-index coverage

- **Queue A (difficulty): 20/20 non-stub instances translated, 0 skipped** → 62 tests.
- **Queue B (corner): 88/90 non-stub instances translated** (100 total, 10 stubs correctly untagged) → 149 tests. Per section: entities 16/16, state_machines 16/16, calculations 10/10, validations 9/9, endpoints 6/6, errors 16/16, **rbac 7/9**, cross_cutting 6/6, consistency_model 2/2.

Two principled skips, both in `rbac`, both because the yaml's asserted outcome contradicts the PRD:
- `deal_lead_cannot_read_the_staff_transition_offers` — PRD lines 432–433 explicitly authorise `DealLead` on `GET /staff-transition-offers` and the detail read, so the asserted `ERR_FORBIDDEN_ROLE` is not PRD-derivable.
- `compensation_designer_cannot_approve_its_own_plan` — PRD line 418 authorises `CompensationDesigner` on `POST /compensation-plans/{planId}/status`; the PRD declares no per-target-status role gate on that endpoint, so the asserted endpoint-gate 403 is not uniquely derivable.

## Sub-assertions reshaped or dropped (instance still covered)

- `test_14` (endpoints): the clock endpoint's own response shape is self-contradictory in the PRD; asserted only the stamping effect on later writes.
- `test_15` (errors): dropped one board-review `ERR_INVALID_STATE_TRANSITION` assertion the PRD does not uniquely derive.
- `test_16` (rbac): three intra-instance sub-assertions dropped as not uniquely derivable.
- `test_17`: instance 3's absolute version chain replaced with relative `assert_version_bumped_by` anchored on reads (physician-create's effect is unspecified); instance 5's "60.00 before the trigger" ordering fixed (coverage counts `EXTENDED` seats, so the yaml order was self-contradictory); instance 6's "SUSPENDED → FLAGGED restores the blocked writes" replaced with the §2.10-consistent claim that only `FLAGGED → CLEARED` restores them.
- `test_18`: dropped the yaml's "posture drops to BLOCKED in the response of the transition that caused it" — the `DENY` response body is a `PayerContract`, not the acquisition; asserted instead that the very next acquisition read and the `readiness_posture=BLOCKED` filter both report `BLOCKED`.

## Helper fixes worth flagging to Step 7

`api_client.py` carries `canonical_instant` plus a `_request` override that canonicalises query-string booleans to `true`/`false` (both list-filter and timestamp-width hazards are handled there, so sub-second width never decides a test). All `list_*` methods are `(self, params, headers)`. Money is sent as JSON integers, instants as full `...Z` instants, blank headers as `""`, and `validate_success`'s `data` is never double-unwrapped.

## Location proof

`test_helpers/` and `test_suite/` both resolve at the TASK ROOT; `ls -a workspace/` shows only `INSTRUCTION.md PRD.md implementation sweep.sh`; `find workspace -maxdepth 3 -type d -name test_helpers -o -name test_suite` → no output. `worklog.md`, `SCAFFOLD*.yaml`, `PRD.md`, `INSTRUCTION.md` and `workspace/implementation/` were never touched. Scratch confined to `.scratch/step5/`.

## Step 7: Run Tests and Iterate — 2026-09-06T02:58:56.000Z

Done. All 8 rounds are green at 211/211.

## Iterations run
2 full 8-round sweeps. Iteration 1: 205/211 in every round with the **same 6 deterministic failures** (no flakiness, no load noise). Iteration 2 after fixes: **211/211 in all 8 rounds**.

## Tests deleted
**None.** Every failure traced to a test-artifact bug or a non-derivable assertion within an otherwise-fair test, so all six were fixed in place rather than removed (STEP 1c partial-coverage split in one case).

## Fixes applied to `test_helpers/`
**None.** No shared fixture, factory, or header builder was at fault — the money/instant/header/unwrap signatures from prior pipelines were all already clean.

## Fixes applied to `test_suite/`

1. **`test_04_cascading_side_effects.py`** — `test_the_cascade_leaves_the_deal_status_and_the_posture_alone`: asserted `employment_status == EMPLOYED` after the safe-harbour trip. §3.1 states the field "is derived from that physician's compensation plans and is recomputed every time one of them moves… `EMPLOYED` when one of the physician's plans is in `EXECUTED`… and `PROSPECTIVE` otherwise". The cascade moves the only executed plan to `COMPLIANCE_HOLD` and returns the pending one to `DRAFT`, so no plan is left in `EXECUTED`/`APPROVED`/`WITHDRAWN` and `PROSPECTIVE` is uniquely determined. Assertion corrected to `PROSPECTIVE` (import swapped, docstring given the governing PRD quote).

2. **`test_08_temporal_overlap_and_capacity.py`** — `test_seats_are_counted_per_cycle_bucket_not_per_contract`: setup died on `ERR_DUPLICATE_CREDENTIALING_PACKAGE`. It reused `physician_b`, who already held a live `SUBMITTED` package on that contract, violating §3.6 ("if another package for the same `physician_id` and `payer_contract_id` is in `DRAFT`, `SUBMITTED`, `IN_REVIEW`, or `APPROVED`, the create is rejected"). All three helper physicians hold live packages, so a fourth provider was added for the next-cycle filing. **Implementation was right; the PRD-required uniqueness check was left intact.**

3. **`test_11_state_machine_transitions.py`** — `test_escrowed_money_can_only_leave_by_the_one_declared_unwind`: probed `ESCROWED → INDEMNIFIED` on an item created with no `indemnity_cap_cents`, so §2.12 rank 3 (`ERR_INVALID_REQUEST`) correctly answered ahead of rank 14 (`ERR_INVALID_STATE_TRANSITION`). The cap is now supplied at creation so the request clears the schema rank and is judged on the undeclared transition — the point the test exists to make. The `ASSUMED` half of the loop was already correct.

4. **`test_13_request_validation_precedence.py`** — both failures shared one helper, `_deal_whose_version_moved_under_the_analyst`, which used `second_physician()` to advance the acquisition `version`. Registering a physician inserts a `Physician` row and does not mutate the acquisition, so per §2.4 ("increases by exactly 1 on every mutation of **that row**") no version moved — `assert 2 > 2`, and the follow-on test then got the rank-22 error where it expected rank 13. Replaced with a `ComplianceOfficer` clearance move (a genuine mutation of the acquisition row); `CLEARED` rather than `FLAGGED` so the §2.10 freeze does not pre-empt the ranks under test. Unused `second_physician` import swapped for `set_clearance`.

5. **`test_16_role_authorisation.py`** — `test_each_deal_dimension_answers_to_the_role_that_owns_it`: asserted the clock reply's `data == {}`. This is the flagged PRD self-contradiction (§2.6 "returns the new value as `current_utc`" vs §4 "returns HTTP 200 with an empty `data` object"), so the body shape is **not uniquely derivable** — both implementations are PRD-faithful. STEP 1c split: the uncovered shape assertion was dropped, the covered assertion (that `IntegrationManager` is granted the endpoint, per the §4 authorised-role list) was kept as `validate_success(...)`.

## Fixes applied to `implementation/`
**None.** All 6 failures were test-artifact defects; the implementation was PRD-faithful on every one, including the two decisions Step 6 flagged. No PRD-required check was weakened and no endpoint, field, or side effect was added.

## Final tally
**211 / 211 passing in all 8 rounds** (`results.1.json` … `results.8.json`, each `passed == total == 211`, 0 failed, 0 errors), left in place in `workspace/implementation/`. `worklog.md`, `PRD.md`, `INSTRUCTION.md`, and `SCAFFOLD*.yaml` untouched; `.scratch/step7/` removed, sibling scratch dirs intact.

**Orchestrator verification**: independently parsed all 8 `results.$i.json` — every round reports `passed == total == 211`. The iteration-1 baseline was also independently confirmed at 205/211 identically in all 8 rounds, which rules out sweep reaping and load noise as the cause of those 6 failures. Step 8 is NOT skipped: the skip condition requires a clean FIRST sweep with zero fixes of any kind, and Step 7 ran a second iteration with 5 `test_suite/` fixes — including one (item 5) that is an explicit PRD self-contradiction Step 8 must pin.

## Step 8: Finalize PRD — 2026-09-06T03:09:36.000Z

Done. `PRD_FINALIZED.md` written with two minimal edits.

## Line counts
- `PRD.md`: 502 lines / `PRD_FINALIZED.md`: 504 lines (+2 lines, +0.40%). One paragraph inserted, one sentence revised in place. Ends at the real final boundary: `| ERR_INVALID_REPORT_PERIOD | 422 |`.

## Changes
- **§4 (endpoint-definitions preamble, line 398)** — *revise* — resolved the PRD self-contradiction on the clock reply in favour of the implementation: "returns HTTP 200 with an empty `data` object" → returns `response_type` `object` with `data` = `{"current_utc": "…"}` carrying the instant the clock now holds, ISO 8601 UTC with three fractional digits — `implementation/routes_acquisitions.py:27-32` (`envelope.object_response({"current_utc": clock.CLOCK.instant_str()})`), formatting from `implementation/clock.py:19-26`. Traces to step_7 item 5 (`test_16` STEP 1c split) and the carried-forward clock note.
- **§2.4 (common resource properties, new paragraph after line 89)** — *insert* — pins what counts as a mutation for `version`/`updated_at`: only a real change to one of the row's own stored fields; one bump per request per row, not per field; creating a child row is not a mutation of the parent acquisition (`POST /physicians` leaves the acquisition's `version`/`updated_at` alone), the two §2.7 creates being the specified exception; any change to a stored acquisition field including derived ones does advance it; a recompute landing on the value already stored advances nothing — `implementation/store.py:117-155` (`set_field` marks only on change, `commit` bumps once per dirty row, skips fresh rows), `implementation/routes_physicians.py:41-44` (no `mark(acquisition)`), `implementation/routes_valuations.py:103` and `implementation/routes_comp_plans.py:78` (the two explicit marks). Traces to step_7 item 4 (`test_13` helper `_deal_whose_version_moved_under_the_analyst`, `assert 2 > 2`).

## Pre-edit search log
**Edit 1 — clock reply shape.** (a) Subject: the body of `POST /_clock/set_current_utc` and the envelope's "2xx with no data" rule. (b) Enumerated: `grep -rn "current_utc\|_clock"` over `implementation/` → only `routes_acquisitions.py:27-32,286`; read `envelope.py` (all three response builders), `clock.py` (`format_instant`, `parse_instant` — accepts `Z` and `±00:00`, stores microseconds, prints milliseconds), `routes_reads.py` (all 24 GETs return a serialized row), `services.respond` (all action endpoints return the row) — no endpoint anywhere returns an empty `data`; `grep -n "empty object"` on the PRD → only §2.2 line 51. Also re-read §2.6 line 104, which already names `current_utc`. (c) Adjustment: left §2.2 line 51's generic "for 2xx responses with no data, it contains an empty object" verbatim (now vacuously true rather than false), and phrased the new clause as agreeing with §2.6 instead of restating clock semantics; said "the instant the clock now holds" rather than "the instant supplied", because the impl echoes the normalised/millisecond-rendered stored value.

**Edit 2 — when a row's `version` moves.** (a) Subject: every path that can advance an acquisition's `version`/`updated_at`. (b) Enumerated and read: `store.py` (`insert`, `mark`, `set_field`, `commit`); `grep -rn "store.mark\|mark(acquisition)"` → only `routes_valuations.py:103`, `routes_comp_plans.py:78`; `grep -rn "recompute_posture\|recompute_escrow\|recompute_retention_pool\|recompute_hr_coverage"` → `routes_acquisitions.py:140,146`, `routes_readiness.py:44,95`, `routes_staff.py:96-106`, `routes_liability.py:99,102`, `routes_payers.py:126`, `routes_credentialing.py:105`, `routes_migration.py:105,129,140`, `routes_billing.py:127,129`, `services.py:172-173`; read `routes_physicians.py`, `routes_liability.py`, `routes_readiness.py`, `routes_staff.py`, `routes_valuations.py`, `routes_comp_plans.py`, `routes_performance.py`, `services.py` in full; confirmed the other seven creates (payer contract, credentialing package, batch, offer, conversion, liability item, readiness task) never `mark` the acquisition, and that `POST /readiness-tasks` can still bump it indirectly when the recomputed posture differs. (c) Adjustments: dropped a first draft that said "only the two §2.7 creates advance the acquisition's version" (false — `POST /readiness-tasks` bumps via a posture change) and replaced it with "no create advances it *merely because a new child now points at it*", then added the explicit "what does advance it" list (dimensions, consideration fields, ledger balances, `hr_staffing_coverage_pct`, a *different* `readiness_posture`) plus the no-op-recompute clause, so every enumerated cascade path stays correctly described.

**Orchestrator verification**: `wc -l` confirms 502 → 504; `cmp` confirms PRD_FINALIZED.md is NOT byte-identical to PRD.md; `tail` confirms it still ends at the real §5 table boundary (`| ERR_INVALID_REPORT_PERIOD | 422 |`), so no truncation occurred.

## Step 9: Complete PRD — 2026-09-06T03:48:47.000Z

Step 9 was run as **three sequential passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module** rather than as a single subagent. Rationale (orchestrator decision, no user available to consult): the implementation is 24 modules / ~3900 lines, and a single agent asked to exhaustively scan all of it against a 504-line PRD reliably under-scans — the known failure signature being a `PRD_COMPLETED.md` that comes back byte-identical to its source. Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from running any `cp`/`mv`/`>`/`truncate` against the file so they could not destroy earlier passes' edits. Every pass was required to re-verify the four structural gates (final boundary, 46 error rows, 48 endpoint rows, not byte-identical to source) before exiting.

**Aggregate result: 62 changes — 47 ambiguity-pins, 15 mismatch-revisions. 504 lines / 115,167 chars → 516 lines / 139,669 chars (+12 lines, +24,502 chars, +21.3%).**

### Pass 1 — cross-cutting layer (app, envelope, errors, store, clock, enums, serialize, validate, machines, services, routes_reads)
18 changes (12 ambiguity-pins, 6 mismatch-revisions). 504 → 516 lines.
- §2.1 — revise — mismatch — whitespace-only header counts as empty; role trimmed + case-sensitive; `X-User-ID` recorded verbatim; unrouted path/unsupported method is `ERR_RESOURCE_NOT_FOUND` 404 *before* any header is read — validate.py:37-48, app.py:70-87
- §2.1 — insert — mismatch — PRD said `PracticePhysician` may "read their own records"; no GET is identity-scoped, so it reads every row in an authorised collection — routes_reads.py:122-128
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — envelope.py:10-14
- §2.2 — revise — mismatch — `api_request_timestamp` is the host's **real** UTC clock, not the §2.6 logical clock — envelope.py:20, clock.py:91
- §2.2 — revise — ambiguity — the four pagination keys are **absent** from `meta` (not null) on non-list responses — envelope.py:17-24
- §2.3 — revise — ambiguity — non-integer/empty/fractional `limit`/`offset` are 400; `offset` beyond `total_count` yields an empty page — validate.py:193-217, envelope.py:50-59
- §2.3 — revise — mismatch — PRD called the `created_at` tie "unspecified"; impl sorts by `(created_at, insertion sequence)` → pinned to creation order — store.py:115-117
- §2.3 — revise — ambiguity — unknown query params ignored; enum/boolean filters reject bad values with 400; identifier filters verbatim with no existence check — validate.py:220-249
- §2.4 — revise — ambiguity — canonical lowercase UUID4; `created_at`/`updated_at` from the logical clock, equal at insert; client-sent `id`/`version`/timestamps ignored; every declared field always present, unset renders `null` — store.py:63-79, serialize.py:12-16,132
- §2.4 — revise — ambiguity — one `updated_at` stamp shared by every row a request touches; a row inserted by the same request is exempt from the bump — store.py:140-151
- §2.4 — revise — ambiguity — `PerformanceReport`'s `updated_at`/`version` are absent not null; never bumped — serialize.py:107-114
- §2.5 — revise — ambiguity — id lookup is exact string equality (wrong-entity-type id is a plain 404); trailing slash accepted — store.py:82-95, app.py:59
- §2.6 — revise — ambiguity — clock mutates nothing, may move backwards; accepted input shapes (1–9 fractional digits, `Z`/`z`/`±00:00`/`+0000`, `T`/`t`); emitted instants always `.sssZ` with sub-ms **truncated** — clock.py:12-24,31-49
- §2.7 — revise — mismatch — other endpoints ignore `expected_acquisition_version` silently as an unknown key rather than rejecting it — routes_valuations.py:31, routes_comp_plans.py:20
- §2.8 — revise — ambiguity — `_cents`/`_bps` as JSON integers; two-decimal quantities as JSON numbers with no trailing-zero preservation — serialize.py:6-9, calc.py:32-36
- §2.10 — revise — mismatch — the novation endpoint is unaffected by the freeze; the sixteen-op list is exhaustive (verified: exactly 16 `check_freeze` sites) — services.py:18-25
- §2.12 rank 3 — insert — ambiguity — body must be a JSON object; empty body ≡ `{}`; **`null` ≡ absent**; unknown keys ignored; strict types (bool ≠ int, `"5"` ≠ 5) — validate.py:64-150
- §2.12 rank 14 — revise — mismatch — added **rank 14a "Transition actor"**: per-transition actor list yields `ERR_FORBIDDEN_ROLE` 403 after state legality, before the freeze; cascade-only transitions are rank-14 rejections — machines.py:271-292
- §4 preamble — revise — ambiguity — action bodies serialised *after* commit and contain only the addressed resource, never cascaded rows — services.py:229-237

Verified already-correct, no edit: all 46 error codes/statuses vs `errors.py`; all 12 filter sets and 24 GET role lists; all 11 machines' transitions; every enum member spelling.

### Pass 2 — calculations + deal core (calc, acquisitions, physicians, valuations, comp_plans, liability)
18 changes (11 ambiguity-pins, 7 mismatch-revisions). 516 → 516 lines (all in-paragraph).
- §3.1 — revise — mismatch — "Its **five** consideration fields" → "six" — routes_acquisitions.py:77-82
- §3.1 — insert — ambiguity — `DILIGENCE/BOARD_REVIEW → ABANDONED` also recomputes `hr_staffing_coverage_pct` after rescinding `EXTENDED` offers — services.py:167-173
- §3.1 — revise — mismatch — `CLEARED → FLAGGED` does not unconditionally return `SUBMITTED` plans to `DRAFT`; it runs the bounded revision cycle and withdraws a plan already at `returned_count` 2 — services.py:143-153
- §3.1 — insert — ambiguity — `clearance_note` accepted but never stored or echoed — routes_acquisitions.py:254
- §3.2 — insert — ambiguity — the `discount_rate_bps > terminal_growth_bps` check fires whenever both fields are present, whatever the method, and not at all when either is absent; the four `_bps` inputs are unbounded signed integers — routes_valuations.py:35-51
- §3.2 — insert — ambiguity — a negative rate is accepted; half-up rounding of a negative half-cent goes away from zero — calc.py:25-29,189
- §3.2 — insert — ambiguity — `review_note` on an opinion decision accepted but not stored — routes_valuations.py:112
- §3.3 — insert — ambiguity — the "exactly one ACCEPTED FMV opinion" precondition has no dedicated code and reports `ERR_INVALID_STATE_TRANSITION`, not `ERR_FMV_OPINION_NOT_ACCEPTED` — routes_acquisitions.py:119-121
- §3.3 — insert — ambiguity — `tail_premium_cents` is **not** cleared by `BOARD_REVIEW → DILIGENCE` — routes_acquisitions.py:241-247
- §3.3 — revise — mismatch — the revert's plan-return effect branches to `WITHDRAWN` on an exhausted allowance — services.py:143-147
- §3.4 — insert — mismatch — cascaded returns branch on the allowance exactly as direct requests do — services.py:132-140
- §3.4 — revise — ambiguity — approval applies peer-`EXECUTED` supersession first, then `approved_by_user_id`, then the `employment_status` recompute — routes_comp_plans.py:174-180
- §3.4 — revise — mismatch — `APPROVED → EXECUTED` carries **three** preconditions: the safe harbour is enforced at execution too — routes_comp_plans.py:145-146
- §3.4 — revise — mismatch — the compliance-hold → `FLAGGED` cascade withdraws rather than redrafts plans that used both returns — services.py:150-153
- §3.4 — insert — ambiguity — every plan transition except a return landing in `DRAFT` recomputes `employment_status`; plan `review_note` not stored — routes_comp_plans.py:187-188
- §3.5 — insert ×2 — ambiguity — a new liability item's `disposition_note` is null; an omitted or null note on update leaves the existing note untouched rather than clearing it — routes_liability.py:43,94-95
- §3.10 — insert ×2 — mismatch — at signing and closing the clearance precondition splits: `PENDING` → `ERR_INVALID_STATE_TRANSITION` (rank 14) while `FLAGGED`/`SUSPENDED` → `ERR_COMPLIANCE_CLEARANCE_BLOCKED` (rank 15, 403) — routes_acquisitions.py:97-101,128
- §3.11 — revise — mismatch — the same plan-return branch on the post-close safe-harbour flag cascade — services.py:150-153

Verified already-correct, no edit: the full income/market rounding sequences, tail-premium single-rounding, the five-step consideration chain and gross-keyed synergy tier boundaries, zero-denominator rules, five-band percentile interpolation with its 99 ceiling and exact-90.00 safe-harbour inclusivity, wage harmonisation (unrounded hourly, independent component rounding, floor-last), retention bonus (tier bands, multiplier on the rounded raw, floor-then-cap), HR coverage, the five-step `comp_true_up` including annualisation, revision-cap counters, committee-cycle lower-inclusivity, closed-interval overlap, truncated match-rate and notice-coverage, retention-years max rule, readiness-posture ordering.

### Pass 3 — integration domains (payers, credentialing, migration, staff, billing, readiness, performance)
26 changes (24 ambiguity-pins, 2 mismatch-revisions). 516 → 516 lines.
- §3.6 — insert ×5 — ambiguity — novation `note` stored nowhere (only `DENY` reads it); `DENY` withdraws packages in `created_at` order with `failure_reason` = the note else a generated sentence naming the payer; `submitted_on` may be any date, never compared to the clock; package-status `note` discarded and the `novation_status` filing precondition is rank-14 `ERR_INVALID_STATE_TRANSITION` ahead of the freeze and the three coded gates; no withdrawal or package denial touches the `PAYER_CREDENTIALING` line or recomputes posture — only `IN_REVIEW → APPROVED` does — routes_payers.py:75,112,117-125; routes_credentialing.py:26,80,90-93,100-106
- §3.7 — insert ×7 — ambiguity — `batch_label` uniqueness counts every batch whatever its status (`RECONCILED`/`ABORTED` never release a label); `youngest_patient_age_years` is range-checked, stored and echoed but unused when `contains_minor_records` is false; `note`/`validated_count`/`defect_count` accepted on every action but only `RECONCILE` reads the counts; both counts default 0, so a bare reconcile yields 0 bps and fails; the abort branch's `failure_reason` names the rate and the 9950 floor; `ABORT` recomputes posture but never fails/completes the `IT_DATA_MIGRATION` line and `REQUEUE` touches neither; `ABORT` does not increment `retry_count` — only the two failing reconcile branches do — routes_migration.py:25,37-42,54,73-76,98-105,132-139
- §3.8 — insert ×3 — ambiguity — `offer_expires_on` unchecked at drafting (a lapsed offer is creatable but unextendable); no uniqueness on `staff_member_name`; extension recomputes coverage only — never completes `HR_STAFFING_PLAN` nor recomputes posture even when it is the extension that crosses 80.00; the three releasing exits likewise never recompute posture nor reopen the HR line, so a `COMPLETE` line survives coverage falling back below 80.00 — routes_staff.py:27-30,62,94-97,104-106
- §3.9 — insert ×2, **revise ×2 (both mismatches)** — `notified_patient_count` unbounded, notification figures immutable post-registration, no uniqueness on `site_name`; **mismatch**: PRD implied the derived trio is "re-derived whenever the figures are re-examined" — since all four inputs are immutable, re-derivation always reproduces the registration values and never version-bumps (also pinned: coverage uncapped above 10000, `notice_lead_days` signed); conversion `note` discarded, the `ATTESTED` precondition is rank-14, `attested_on` is its only side effect; **mismatch**: PRD narrated the `CONVERTED` deal-status precondition second, after the Medicare-novation check, but impl evaluates it first at rank 14 so it wins when both fail, and `CONVERTED` has no side effect at all — routes_billing.py:18-27,37-39,70,78-86,91,105-121; calc.py:506-509
- §3.10 — insert ×5 — ambiguity — `due_on` compared against neither the clock nor `target_close_on`; the one-line-per-code rule counts every line whatever its status (`WAIVED`/`FAILED` reserve a code permanently); the `HR_STAFFING_PLAN` coverage gate is rank-14 `ERR_INVALID_STATE_TRANSITION`; `failure_reason` optional and stored null when omitted, each free-text field read only by its own target; `FAILED → IN_PROGRESS` leaves `verified_by_user_id` as the failure left it — routes_readiness.py:22,26-30,53-54,63-65,90-93
- §3.11 — insert ×2 — ambiguity — `actual_collections_cents` stored and echoed but enters no derivation; aggregation spans every report on the plan including the new one regardless of period contiguity or order; the safe-harbour hold's cascade order is physician `employment_status` first, then the `CLEARED → FLAGGED` flag, then the plan returns, each `WITHDRAWN` landing recomputing its own physician, and the trip cannot re-fire on a plan already in `COMPLIANCE_HOLD` — routes_performance.py:74,105-107,127-133; services.py:86-97

### Orchestrator verification of the final artifact
- Line counts: PRD.md 502 → PRD_FINALIZED.md 504 → **PRD_COMPLETED.md 516**. Sizes 113,865 → 115,167 → **139,669 bytes**.
- `cmp` gates: PRD_COMPLETED.md is byte-different from **both** PRD_FINALIZED.md and PRD.md — the scan demonstrably landed (the known failure mode is a byte-identical output).
- Structure intact: **46** `ERR_*` table rows, **31** headings (unchanged — no sections added), file ends at the real final boundary `| ERR_INVALID_REPORT_PERIOD | 422 |`.
- Leak gate: grep for `harder than expert`, `expert_plus`, `test_recipe`, `scaffold_difficulty`, `scaffold_corner`, `SCAFFOLD` in PRD_COMPLETED.md → no hits. The Step 2 difficulty directive never reached any PRD.
- Housekeeping: pass 3 flagged an orphan `python3 app.py` (pid 3513794) left over from Step 6's smoke test. I confirmed via `/proc/3513794/cwd` that it belonged to **this** task's `workspace/implementation` — not another pipeline — and reaped it by that single PID. No broad `pkill` was ever issued.
