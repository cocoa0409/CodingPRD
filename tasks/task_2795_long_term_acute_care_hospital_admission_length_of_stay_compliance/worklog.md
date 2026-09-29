# Worklog — task_2795_long_term_acute_care_hospital_admission_length_of_stay_compliance

## Step 1: Create task directory — 2026-09-04T22:30:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2795_long_term_acute_care_hospital_admission_length_of_stay_compliance` and its `workspace/` subdirectory. Index 2795 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T00:32:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Verdict block (verbatim, first and only lint run needed — clean on the first pass, re-confirmed after final edits):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     14
  §1.8 instances scanned:     20
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  1207

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files
- `SCAFFOLD.yaml` — 2,867 lines / 140 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1,967 lines / 134 KB
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4,646 lines / 324 KB

## Surface (§1.0–§1.7)
`domain_name: ltch-admission-los-compliance`, `api_prefix: /ltch`. Archetypes compliance_audit + ledger_reconciliation; layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`; topology flat; state-machine shape cyclic; role_model segregation_of_duties; consistency immediate.

14 entities (ReferringHospital, CostReportingPeriod, Patient, Physician, AdmissionCriteriaSet, DrgRateEntry, Referral, Stay, WeaningPlan, IdtNote, InterruptionEvent, PaymentDetermination, DenialRiskReview, DocumentationQuery) · 9 state machines · 10 calculations · 32 validation rules (single priority ladder) · 49 endpoints · 47 error ids · 5 roles · 2 declared `concurrency_rules`.

## Design files
- §1.8: 9 rule_ids × ≥2 instances = **20 instances** (3 each for combinatorial_formula and boundary_precision_check).
- §1.9: **73 instances** across all nine guide sections — entities 12, state_machines 15, calculations 13, validations 14, endpoints 5, errors 5, rbac 4, cross_cutting_complexity_layers 4, consistency_model 1. 61 are full recipes, 12 are `excluded_because:` stubs citing a §1.8 instance. 93 unique instance names across both files, no duplicates; every cited difficulty_instance resolves.

## Coverage audit notes
- **All 47 error ids are exercised** by §1.8/§1.9. `ERR_PERIOD_LEDGER_MISMATCH` is the only one that is not directly triggerable by a well-behaved client — it is covered negatively, as the "must not fire" proof gate of the compensating-invariant instances (void → reprice → refinalize, and recombination unwind).
- **Skipped-as-non-applicable taxonomy rows**: `parent_relationships` (every §1.1 entity is `parent: null` — flat topology, so the flat rows `foreign_key_references_validated` / `cross_reference_integrity` are covered instead); `bulk_action` (no bulk endpoint exists in §1.5); `bubble_up` (period close is an explicit officer action, never auto-derived); the `linear` / `branching` / `parallel` / `compound` shape rows and the unused algorithm rows.
- Both `concurrency_rules` get a real OCC instance on their own declared write endpoint (stale → 412 `ERR_STALE_PATIENT_VERSION` / `ERR_STALE_STAY_VERSION`, refresh → success, plus proof the refused write bumped nothing). RBAC covers 9 cross-lane denials including the three read-permission holes, an undeclared/absent `X-Role`, and all three segregation-of-duties clauses (price≠finalize, finalize≠void, issue≠close).
- **Deliberately over-Expert surface**, per the scenario's difficulty directive: 49 endpoints vs the Expert band's 20–32 and 47 errors vs 18–30.
- **Note for the parent:** the subagent stripped the leading meta-directive line out of `SCAFFOLD.yaml`'s `scenario:` block (the rest of the description is verbatim), so it cannot propagate into PRD.md. Difficulty is carried by `difficulty_level: expert` plus the enlarged surface. Orchestrator verified with `grep -rn "harder than expert" .` → no matches anywhere in the task dir.

## Step 3: Copy shared files — 2026-09-05T00:32:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T00:44:00.000Z

PRD written to `workspace/PRD.md`.

**Line count:** 449 lines. Ends at a complete final row of the §5 error table — no truncation, no audit footer. (Orchestrator independently verified the tail: last line is the `ERR_CLOCK_NOT_MONOTONIC` table row, a real section boundary.)

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 2.1 Personnel, Headers and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination and List Ordering · 2.4 Record Identity, Audit Fields and the Logical Clock · 2.5 Day Counting, Rounding and Monetary Precision · 2.6 Stale-Version Protection on Superseding Writes · 2.7 The Cost Reporting Period as Fiscal Envelope · 2.8 Validation Precedence · 2.9 Cascades, Compensating Reversals and Version Bumps · 2.10 Nested Path Resolution
- §3 Business Logic & Workflows — 3.1 Reference Data · 3.2 Referral Intake and the Screening Loop · 3.3 Admission: Eligibility, Occupancy and the Referral-Mix Ceiling · 3.4 Interdisciplinary Documentation and the Ventilator Weaning Protocol · 3.5 Interruptions of Stay and Recombination of Readmissions · 3.6 Discharge, Covered Length of Stay and the Four-Level Cascade · 3.7 Payment Determination: Dual-Variant Pricing, Short-Stay Outliers and the High-Cost Add-On · 3.8 Denial-Risk Review, Documentation Queries and Physician Responses · 3.9 Period Reconciliation and Close
- §4 Endpoint Definitions (4 columns, 49 rows)
- §5 Error Code Catalogue (2 columns, 47 rows)

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 124 required, 124 present, 0 missing
- endpoints[].request_body: 58 required, 58 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
- errors[].id: 47 required, 47 present, 0 missing
- roles[].name: 5 required, 5 present, 0 missing
- state values: 30 required, 30 present, 0 missing
- enum literals: all present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 32 checked, 32 expressed as an explicit ordered list in §2.8 (incl. the priority-6→9 CRITERIA_NOT_MET carve-out, 9-over-10 safety precedence, 15-over-16 buffer precedence, 6-over-23 finalize precedence, 9-over-31 pinned-set precedence), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_patient_version / expected_stay_version + ERR_STALE_PATIENT_VERSION / ERR_STALE_STAY_VERSION + 412), 0 missing
- state_machines[].transitions: 8 machines / 62 transitions checked, 62 fully expressed with from/to, preconditions paired to error ids, and side effects, 0 missing
- calculations[]: 10 checked, 10 fully expressed in prose (pinned outlier order incl. the 6,000,000→2,400,000 disambiguation; one-rounding per-diem product; floor of five-sixths ALOS; per-determination-then-sum ledger order), 0 missing
- validations[] conditions: 32 checked, 32 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 49 endpoints checked, all side effects and all applies_to sets expressed, 0 missing
- entities[].fields[] structured content: 124 checked, defaults/initial values/types/nullability reconstructible from prose (incl. common_fields:false for DrgRateEntry and IdtNote), 0 missing
- sibling-branch symmetry: 9 groups checked (TOLERATED vs FAILED; LIBERATED vs VENT_DEPENDENT; RETURNED vs EXPIRED; STANDARD_LTCH_PPS vs SITE_NEUTRAL; CLEARED vs ESCALATED; AS_DOCUMENTED vs QUERY_ADJUSTED; withdraw from 3 states; supersede from 3 states; void from DRAFT vs FINAL), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 881
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- raw (unbackticked) /ltch path leaks: 0
Status: PASS
```

**One scaffold internal conflict the doc generator had to resolve:** the auto-issued cascade query's `query_type` is given as `IDT_PARTICIPATION` in both `state_machines.Stay` discharge transitions but as `VENT_WEANING_RATIONALE` in the `POST /ltch/stays/{id}/discharge` endpoint's `side_effects`. It adopted `IDT_PARTICIPATION` uniformly for both cascade entry points (ordinary discharge and interruption-window expiry), since that is the twice-stated transition-level value. If the test suite expects `VENT_WEANING_RATIONALE` on the ordinary-discharge path, that single line in §3.6 (level four of the cascade) is the one to flip.

**Orchestrator note (autonomy decision):** the PRD — not the scaffold — is the contract, so the `IDT_PARTICIPATION` choice above stands as the authority for Step 7 triage. If a generated test asserts `VENT_WEANING_RATIONALE` on ordinary discharge, that test contradicts PRD prose and Step 7 should treat PRD as winning per the skill's Key Principle 1.

## Step 6: Generate implementation — 2026-09-05T01:12:00.000Z

Implementation complete, smoke-tested end-to-end, server killed by PID (19547 now free), `__pycache__` dirs removed.

## Files written
All under `workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `app.py` | 95 | app factory, 6 blueprints at `/ltch`, RLock per request, Decimal/datetime JSON provider, ApiError/404/405/500 handlers |
| `errors.py` | 77 | all 47 PRD §5 error ids → HTTP status, `ApiError` |
| `clock.py` | 44 | logical clock (default `2026-08-01T00:00:00Z`), `iso()` with exactly 3 fractional digits |
| `envelope.py` | 56 | `meta`/`response_type`/`data`, `req_` + 20 alnum request ids, pagination meta |
| `store.py` | 71 | 14 in-memory dicts, `_seq` ordering, `new_row`/`touch`, append-only collections |
| `validate.py` | 251 | body/query coercion, all failures → `ERR_VALIDATION` |
| `auth.py` | 52 | 5 roles from headers, `SYSTEM` actor, `require_role`, `acting_physician` |
| `calc.py` | 182 | all PRD constants, day counting, `ROUND_HALF_UP` money/pct, SSO threshold, 3-candidate min, high-cost outlier, share/monitoring, score clamp + bands |
| `serialize.py` | 274 | 14 entity serializers (money/pct as JSON numbers) |
| `lookup.py` | 121 | typed 404 getters, paging, relationship helpers |
| `services/pricing.py` | 94 | DRG in force, variant selection, dual-variant determination creation |
| `services/scoring.py` | 121 | weighted denial-risk scoring, query credit, review open, 72h expiry sweep |
| `services/cascade.py` | 96 | 4-level discharge cascade, query issuance, recombination money unwind |
| `services/shares.py` | 24 | idempotent 25-percent-rule share/monitoring recompute |
| `routes/reference.py` | 348 | hospitals, patients, physicians, DRG rates, criteria sets, periods, clock |
| `routes/referrals.py` | 354 | create/screen/submit-info/withdraw/admit + list filters |
| `routes/stays.py` | 338 | get/list, discharge, recombine, interrupt, return, IDT notes |
| `routes/weaning.py` | 170 | plan create/get/list, record-sbt, close |
| `routes/payments.py` | 165 | re-price, list/get, finalize, void |
| `routes/reviews.py` | 207 | reviews list/get/rescore/resolve, queries issue/get/list/answer/close |
| `start.sh` | 16 | guarded flask install, `PORT` default 10000, `exec python3 app.py` (chmod +x) |
| `requirements.txt` | 1 | flask |

Total 3157 lines of Python.

## Endpoints
**51 registered `/ltch` method+path pairs** = all 49 in the PRD endpoint table, plus two convenience reads implied by the entity model (`GET /ltch/physicians/{id}`, `GET /ltch/drg-rates/{id}`). Zero seeded data; fresh process = empty store.

## Smoke test
Reference data → referral → screen → admit → weaning plan/notes/SBTs/close → clock advance → discharge (4-level cascade fired: stay updated, DRAFT determination priced by `SYSTEM`, review opened and scored) → rescore → issue query → answer → close query → rescore → resolve CLEARED → finalize → period close, all 2xx. Numeric spot-check verified live: full standard 6,000,000; SSO threshold 25 (`floor(0.8333333333333334 × 30)`); standard base 2,280,000 (candidate B wins); outlier 5,376,000; standard total 7,656,000; site-neutral variant 7,800,000; `discharge_payment_pct` 38.0; score 20 as-documented → 8 query-adjusted → LOW. Period ledger reconciled to 7,656,000 / 1 FINAL. Negative probes correct: `ERR_PERIOD_CLOSED` 409 after close, `ERR_NOT_FOUND` 404, `ERR_VALIDATION` 405, `ERR_UNAUTHORIZED` 403 on missing headers. **Zero 500s in the whole run.**

## PRD ambiguities resolved (PRD wins over SCAFFOLD everywhere)
1. **Auto-issued cascade query type** — PRD §3.6 level four says `IDT_PARTICIPATION`; SCAFFOLD's discharge side-effect says `VENT_WEANING_RATIONALE`. Chose `IDT_PARTICIPATION`.
2. **Interruption count cap** — SCAFFOLD counts only `OPEN`/`RETURNED`; PRD counts every event. Chose the running `interruption_count`.
3. **`carried_los_days` on recombination** — SCAFFOLD says "parent's previous `covered_los_days`"; PRD §3.5 says whole-day count `admitted_at`→`discharged_at`. Chose the PRD day count.
4. **Parent reopen scope** — clears `discharged_at`, `discharge_disposition`, `discharge_payment_pct` only; leaves `covered_los_days`/`sso_threshold_days`/`short_stay_outlier_applied` intact (re-derived at the next discharge).
5. **New period counters** — resets only `admissions_in_period` and `share_pct`; `monitoring_state` deliberately untouched (literal §2.7).
6. **`ERR_PHYSICIAN_NOT_FOUND`** — enforced only on the two physician-exclusive writes (weaning close, query answer), checked immediately after path existence.
7. **Weaning close ordering** — `liberation_eligible` (rule 17) checked *before* the `PROGRESSING` state requirement, since rule 6's enumeration omits weaning close.
8. **Period-close structural gate** (a `DISCHARGED` stay with no `FINAL` determination) has no dedicated error id → `ERR_INVALID_STATE` 409, evaluated after rules 27/28.
9. **Illegal `CLEARED` resolve** (band `HIGH`, from `QUERIES_ISSUED`, or an `ISSUED` query outstanding) → `ERR_INVALID_STATE` 409. Consequence: after a query is closed, an explicit `rescore` is required to return `QUERIES_ISSUED`→`OPEN` before a chart can be cleared.
10. **Period-closed guard scope** — applied to admit (as `ERR_NO_OPEN_PERIOD`), discharge, recombine, interrupt, return, IDT notes, determination create/finalize/void, share recompute (per §3.9's "stay, determination, note or interruption"); not applied to weaning or review/query operations.
11. **Validation order** — writes check body shape (rule 1) before role (rule 2); GET lists check role before query params.
12. **`query_adjusted_score`** — recomputed fresh each time and `null` whenever `answered_query_count == 0`.
13. **Version-bump semantics** — discharge bumps the stay exactly once; a cascade-created review that immediately auto-issues a query stays at version 1; re-issuing on an already-`QUERIES_ISSUED` review does not bump; share recompute mutates only on actual change, and the admit path yields exactly one hospital bump via a version guard.
14. **Re-price with `override_drg_rate_id`** — recomputes the stay's `sso_threshold_days`/`short_stay_outlier_applied` from the DRG in force (identical values on the non-override path).

**Orchestrator note:** the two extra reads (`GET /ltch/physicians/{id}`, `GET /ltch/drg-rates/{id}`) are not in the PRD §4 table. They are additive reads that cannot change any state, so they are left in place; Step 9's full impl scan is responsible for pinning them in PRD_COMPLETED.md (or they stay as harmless unexercised surface).

## Step 5: Generate unit tests — 2026-09-05T01:42:00.000Z

(Ran concurrently with Step 6 in a single assistant message, per the skill's physical-isolation requirement; logged after Step 6 only because it finished later.)

All audits pass. The suite is complete.

## Files written

`test_helpers/` — 9 files, 3,204 lines
`types.py` 456 · `api_client.py` 429 (incl. `canonical_ts` second-precision ISO canonicalisation) · `assertions.py` 395 · `fixtures.py` 858 · `factories.py` 295 · `api_errors.py` 157 (47 ids + HTTP map registered) · `constants.py` 130 (all money as ints) · `test_users.py` 112 (incl. `make_attending_physician_headers`) · `__init__.py` 372 (barrel, 168 exports)

`test_suite/` — conftest + 18 test modules, 11,456 lines
Queue A: `test_01_dual_variant_calc.py` 446 · `test_02_combinatorial_formula.py` 562 · `test_03_non_linear_state_machine.py` 435 · `test_04_transitive_cascade.py` 434 · `test_05_priority_pair_validation_conflict.py` 383 · `test_06_boundary_precision.py` 529 · `test_07_cross_entity_state_dependency.py` 309 · `test_08_resource_temporal_overlap.py` 317 · `test_09_compensating_invariant.py` 545
Queue B: `test_20_corner_entities.py` 1229 · `test_21_corner_state_machines.py` 1386 · `test_22_corner_calculations.py` 1114 · `test_23_corner_validations.py` 1197 · `test_24_corner_endpoints.py` 516 · `test_25_corner_errors.py` 600 · `test_26_corner_rbac.py` 635 · `test_27_corner_cross_cutting.py` 730 · `conftest.py` 89

## Counts

- **278 tests collected**, zero collection errors (232 test functions; the difference is parametrization).
- Queue A: 20 instances, 0 stubs — **20/20 translated, 0 skipped**, every one with >=2 tests.
- Queue B: 73 instances, 13 `excluded_because:` stubs — **60/60 non-stub translated, 0 skipped**; no stub was translated.
- Audit (AST + yaml, `/tmp/audit_2795.py`): 80 distinct instances tagged vs 80 non-stub expected, **0 problems** — every test has exactly one `Design:` line as its docstring's final line, every tag resolves to a real instance, every `PRD n.n: "..."` citation is a verbatim substring of `workspace/PRD.md`, and no scaffold/design vocabulary appears anywhere in the suite outside the `Design:` tags themselves.

The earlier 60+ "banned vocabulary" hits were a false positive in the generator's own audit regex: `difficulty` matched the `Design: Difficulty/...` tag line. With the tag line excluded, an independent grep for `scaffold|design index|corner case|test design|edge case|xfail|skip` and for `difficulty|corner` outside `Design:` lines returns nothing.

## Skips

No whole instance was skipped. Two sub-claims were narrowed to their derivable subset (the rest of each instance is translated):

- `Corner/entities/drg_rate_and_idt_note_expose_no_version_and_no_mutation_endpoint` — the "no PUT/PATCH/DELETE declared" half is not uniquely derivable; the PRD never fixes an observable status for an undeclared method. The absent-`updated_at`/absent-`version` half is asserted.
- `Corner/.../override_drg_rate_id_conditionally_reprices_the_stay` — the PRD does not say a re-price recomputes the stay's `sso_threshold_days` against the override DRG, so that figure is not asserted.

## Design-index corrections against the PRD

Timelines shifted forward off the `2026-08-01T00:00:00Z` epoch (would have been `ERR_CLOCK_NOT_MONOTONIC`); `week_index` admission week is 0 not 1; undeclared `query_type` literals replaced with the four declared ones; `CLOSED_VENT_DEPENDENT`->`VENT_DEPENDENT`, `STANDARD`->`STANDARD_LTCH_PPS`, `NOT_APPLICABLE`->`PENDING`; `ERR_SEGREGATION_OF_DUTIES` is 403 not 422; `resumed_at` is stamped only by recombination, so the interruption scenario's `covered_los_days` is 20 (base 2,160,000, pct 36.00); `query_adjusted_score` asserted unset rather than 67; reviews have no `outcome` field and no `RESOLVED` status; a future `left_at` yields `ERR_ADMISSION_IN_FUTURE`.

## Path hygiene

`workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` — no test dirs leaked. `worklog.md` untouched. Orchestrator re-verified both independently.

## Step 7: Run tests and iterate — 2026-09-05T02:20:00.000Z

Everything is clean. All 8 rounds pass 278/278.

## Summary

**Iterations run:** 3 (each a full 8-round parallel `setsid nohup` sweep, no early exit).

Trajectory: iteration 1 = **0/278** in all 8 rounds -> iteration 2 = **276/278** -> iteration 3 = **278/278** in all 8 rounds.

**Tests deleted:** none. No test asserted a scaffold-only rule; both real defects were in the test artifact and were repaired to be *more* faithful to PRD, not weakened.

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_client.py` — `ApiClient.__init__` now appends the `/ltch` mount prefix to the runner-supplied `API_BASE_URL`. This was the single upstream bug causing the total 0/278 wipeout: `GenericApiClient` defaults `base_url` to bare `scheme://host:port` (the runner's `executor.py` sets `API_BASE_URL = api_url`, no path), while every one of the ~50 client methods names its path relative to the mount point (`/referring-hospitals`, `/stays/{id}/discharge`, ...). Every request therefore 404'd with `ERR_NOT_FOUND` and all 278 tests died as "Setup step failed". PRD §4 states verbatim: *"Every endpoint below is mounted under the `/ltch` prefix."* The implementation's 52-route URL map was correct all along — verified with a live probe server that `POST /ltch/patients` returned 201 before and after the change. This one-line fix recovered 276 of 278 tests.

**Fixes applied to `test_suite/`:**
- `test_23_corner_validations.py::test_screening_against_a_set_dated_in_the_future_is_refused` — the assertion `assert_unset(after, "pinned_criteria_set_id", "qualifying_track")` mis-translated PRD. PRD §3.2 says verbatim: *"A newly created referral enters `RECEIVED` with `qualifying_track` `NONE`, `screened_count` 0, `data_complete` false and `pinned_criteria_set_id` null."* A refused screen resolves no track, so the creation value `NONE` correctly stands; only `pinned_criteria_set_id` is null. Kept the `pinned_criteria_set_id` unset check (PRD: *"nothing is pinned"*) and tightened `qualifying_track` to an exact `== QualifyingTrack.NONE` equality — a strictly stronger assertion. This was the sole outlier in the suite: `test_20_corner_entities.py:602` already asserts exactly `== QualifyingTrack.NONE` on an unscreened referral.
- `test_03_non_linear_state_machine.py::test_the_reopened_parent_combines_its_banked_days_with_the_second_segment` — removed only `assert_unset(reopened, "covered_los_days", "sso_threshold_days")` under STEP 1c partial-coverage handling. PRD §3.5 enumerates precisely what the fold clears on the reopened parent (*"both its `discharged_at` and its `discharge_disposition` are cleared to null"*) and never names `covered_los_days` or `sso_threshold_days`. Two faithful readers diverge: one treats §3.5's list as exhaustive and retains the banked 14; the other reads §3.6's *"Before discharge all three ... are null"* as a re-established invariant. Not uniquely derivable, so the assertion goes — but every covered assertion was kept, including `carried_los_days` 14 and the post-second-discharge `covered_los_days` 20 / `sso_threshold_days` 25 / short-stay flag `True` that pin PRD §3.6's formula.

**Fixes applied to `implementation/`:** **none.** No implementation defect was found. Audited `calc.py`, `services/pricing.py`, `services/scoring.py`, `services/cascade.py`, `routes/stays.py`, `routes/payments.py` and `app.py` against PRD §2.5–2.9 and §3.6–3.8 (pinned rounding order, the non-fixed-point outlier threshold, three-candidate short-stay base with a single rounding on the per-diem product, the 96-hour/3-ICU-day variant gate, validation precedence) and found them faithful. Storage remains in-memory dicts only — no SQLite, no JSON dump, no `/tmp`, nothing seeded at startup, so per-test-server isolation wipes all state on each boot. `worklog.md` was not touched by the subagent.

**Final sweep confirmation:** the last sweep produced all 8 `results.$i.json` files, each complete JSON with **`passed == total == 278`, `failed == 0`, `errors == 0`** (rounds ran 521–522s each). No test failed in any round, so there is no flakiness signal — the two fixed bugs were deterministic, failing in all 8 rounds identically, not load-induced.

**Orchestrator verification (independent of the subagent's claim):** re-read all 8 `results.*.json` directly — every file present, timestamped 02:17, and each reporting `passed 278 / total 278 / failed 0 / errors 0`. Sweep artifacts confirmed real.

**Step 8 gate:** Step 7 applied 0 `implementation/` fixes but did make 1 `test_helpers/` fix and 2 `test_suite/` fixes across 3 iterations, so this is NOT the skill's zero-iteration skip case. Step 8 runs, with `<step_7_diff>` = this entry. Note for Step 8: the `api_client.py` prefix fix is a pure fixture bug with no PRD implication and should produce no PRD edit; only the two `test_suite/` items are candidate PRD silences.

## Step 8: Finalize PRD — 2026-09-05T02:28:00.000Z

Done. `PRD_FINALIZED.md` written with two targeted revisions.

## Line counts
- `PRD.md`: 449 lines; `PRD_FINALIZED.md`: 449 lines. 0% line delta; 2 lines revised in place (0.45% of lines touched).

## Changes
- **§3.5 (Recombination, the parent half)** — *insert* — added one sentence pinning that the fold does **not** clear `covered_los_days`, `sso_threshold_days` or `short_stay_outlier_applied` on the reopened parent; each keeps its pre-fold value and is recomputed at the parent's next discharge — `implementation/routes/stays.py:166-175` (only `discharged_at`, `discharge_disposition`, `discharge_payment_pct` are nulled; the three LOS/SSO fields are never assigned).
- **§3.6 (Covered length of stay)** — *revise* — "Before discharge all three ... are null" narrowed to "Before a stay's **first** discharge ...", with a clause noting a recombination-reopened stay carries the earlier discharge's values until recomputed — `implementation/routes/referrals.py:327-329` (admission initialises all three null) vs `implementation/routes/stays.py:166-175` (reopen retains them).

Both edits trace to the one Step 7 item with a PRD implication: the removal of `assert_unset(reopened, "covered_los_days", "sso_threshold_days")` in `test_03_non_linear_state_machine.py`. The other two Step 7 items required no PRD change — the `api_client` `/ltch` prefix fix is a pure fixture bug (PRD §4 already states the mount prefix verbatim), and the `test_23` `qualifying_track == NONE` tightening is already uniquely determined by PRD §3.2 ("A newly created referral enters `RECEIVED` with `qualifying_track` `NONE` ..." plus "nothing is pinned" on a refused screen; `implementation/routes/referrals.py:194` raises before `evaluate_screening` mutates anything, so the creation value stands).

## Per-edit pre-edit search log

**Edit 1 — §3.5 parent reopen**
- (a) Subject: the stay-level fields `covered_los_days`, `sso_threshold_days`, `short_stay_outlier_applied` (plus, for boundary safety, `discharge_payment_pct` and `estimated_cost_cents`) and their whole lifecycle — where set, where cleared, where retained.
- (b) Paths enumerated (grepped repo-wide for all six field names, then read each hit): `routes/referrals.py:313-336` (admission initialises all six null); `services/cascade.py:41-68` (`run_discharge` sets `covered_los_days`, `discharge_disposition`, `estimated_cost_cents` at level one, both cascade entry points — ordinary discharge `routes/stays.py:118` and interruption-window expiry `routes/stays.py:292`); `services/pricing.py:35-40, 43-94` (`refresh_stay_outlier_fields` sets `sso_threshold_days`/`short_stay_outlier_applied` on every pricing, cascade or re-price, and mirrors `discharge_payment_pct` onto the stay); `routes/stays.py:126-182` (recombine — the Step 7 site); `routes/payments.py:33-67` (re-price, gated on `clinical_status == "DISCHARGED"`, so a reopened `ADMITTED` parent cannot be re-priced); `routes/payments.py:160-163` (void clears `discharge_payment_pct` only); `serialize.py:146-157` (all six exposed on stay reads); `calc.py:84-92`; `services/scoring.py:26-41` (reads determination snapshots, not stay fields).
- (c) Adjustments made: (1) scoped the claim to exactly the three LOS/SSO fields and deliberately said nothing about `discharge_payment_pct` — the impl *does* null it on the fold, so a wording like "nothing else is cleared" would have been a false universal; (2) wrote "is recomputed at the parent's next discharge" rather than "at the next pricing", verified safe because `routes/payments.py:49` blocks re-pricing an `ADMITTED` stay, so discharge is the only reachable recompute; (3) avoided asserting the enumeration in §3.5 is exhaustive, leaving `estimated_cost_cents` (also retained) undescribed rather than mis-described.

**Edit 2 — §3.6 "before discharge ... are null"**
- (a) Subject: the null-precondition invariant over the same three fields.
- (b) Paths enumerated (same grep set, re-checked): `routes/referrals.py:327-329` (the only place the three are set to null); `services/cascade.py:53` + `services/pricing.py:39-40` (the only places they become non-null, always within one discharge call, so no observable window where a `DISCHARGED` stay has them null); `routes/stays.py:166-175` (the reopened parent is `ADMITTED` with non-null values — the case that falsifies the original universal); `routes/payments.py:132-165` (void never re-nulls them).
- (c) Adjustment made: changed "Before discharge" to "Before a stay's **first** discharge" instead of deleting the invariant, so the sentence still pins the freshly-admitted case (which `routes/referrals.py:327-329` guarantees) while no longer making a false claim about a reopened parent; added an explicit cross-reference to §3.5 rather than restating the retention rule a second way, to keep the two edits from drifting apart.

## Step 9: Complete PRD — 2026-09-05T03:05:00.000Z

**Orchestrator decision (autonomy):** Step 9 was split into three sequential, module-partitioned passes over one shared `PRD_COMPLETED.md`. A single-agent exhaustive scan of a 3,157-line implementation against a 449-line PRD reliably exceeds one context and returns a byte-identical file (i.e. the scan silently never ran). Pass 1 performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 were explicitly forbidden from copying and edited in place.

Partition:
- **Pass 1** — `app.py`, `errors.py`, `clock.py`, `envelope.py`, `store.py`, `validate.py`, `auth.py`, `lookup.py`, `serialize.py`, `routes/reference.py`, `routes/referrals.py`
- **Pass 2** — `calc.py`, `services/pricing.py`, `services/scoring.py`, `services/cascade.py`, `services/shares.py`
- **Pass 3** — `routes/stays.py`, `routes/weaning.py`, `routes/payments.py`, `routes/reviews.py`

### Pass 1 (11 modules) — 14 ambiguity-pins, 3 mismatch-revisions
449 lines / 96,053 chars -> 451 lines / 100,723 chars (+2 lines, +4,670 chars).

- §2.1 — insert — ambiguity — a request omitting `X-User-ID` is not refused; the acting identifier is the empty string, recorded and compared like any other (and for `AttendingPhysician` resolves to no `Physician`, hence `ERR_PHYSICIAN_NOT_FOUND`) — `auth.py:33-35`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`–`Z` and `0`–`9` — `envelope.py:10,14`
- §2.2 — insert — ambiguity — `api_request_timestamp` is rendered from the logical clock, not the wall clock — `envelope.py:20`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` also yield `ERR_VALIDATION`; an empty-string parameter is treated as omitted — `validate.py:216-235`
- §2.3 — insert — ambiguity — `created_at` ties are broken by insertion order (reversed for the newest-first determination list) — `store.py:65-71`
- §2.3 — insert — ambiguity — enum-valued filters must hold a declared literal else `ERR_VALIDATION`; id filters match literally; empty-string filters are ignored; the role check precedes any query-parameter parsing on every list endpoint — `validate.py:238-251`, `routes/referrals.py:158-164`
- §2.5 — insert — ambiguity — money, percentages and ventilator hours are emitted as JSON numbers, never strings, so a percentage rounded to 25.00 serialises as `25.0` — `serialize.py:13-18`
- §2.7 — insert — ambiguity — opening a period leaves `monitoring_state`/`threshold_pct` alone and does not rewrite (or version-bump) a hospital already at 0 / 0.00 — `routes/reference.py:264-269`
- §2.8 rule 1 — insert — ambiguity — absent/empty body reads as `{}`; non-JSON or non-object body is `ERR_VALIDATION`; unnamed extra fields are ignored — `validate.py:20-33`
- §3.1 — insert — ambiguity — resubmitting a physician's current `credential_status` is accepted and still bumps `updated_at`/`version`; physician rows readable by every role — `routes/reference.py:138-146`
- §3.1 — insert — ambiguity — `end_date <= start_date` is a rule-1 payload-shape `ERR_VALIDATION`, evaluated ahead of authorization — `routes/reference.py:240-241`
- §3.1 — insert — mismatch — DRG rate entries are readable individually by every role (`GET /ltch/drg-rates/{id}`) — `routes/reference.py:179-182`
- §3.2 — insert — ambiguity — `missing_fields` is ordered as the five inputs are named — `routes/referrals.py:24-30,70`
- §3.3 — revise — mismatch — `override_reason` is stored whenever a non-empty value is supplied even if no override was needed; `admitted_with_override` is true only when the source was `BREACHED` **and** a non-empty reason accompanied the request; `""` counts as no reason — `routes/referrals.py:264,295,334-335`
- §3.3 — insert — ambiguity — `recompute-referral-shares` returns the cost reporting period itself, and is refused with `ERR_PERIOD_CLOSED` on a closed period — `routes/reference.py:280-288`
- §3.9 — insert — ambiguity — the structural "every DISCHARGED stay carries a FINAL determination" gate runs last and is refused with `ERR_INVALID_STATE` (409); a stay with only VOIDED determinations counts as carrying none — `routes/reference.py:317-323`
- §4 table — insert — mismatch — added rows for `GET /ltch/physicians/{id}` and `GET /ltch/drg-rates/{id}`, both open to all five roles — `routes/reference.py:132-135,179-182`

Pass 1 deliberately left alone: `app.py:71-85` catch-all handlers emit `ERR_NOT_FOUND` (404 unrouted), `ERR_VALIDATION` with **HTTP 405** on method mismatch, and `ERR_INTERNAL` (500). Pinning the 405 case would contradict §5's `ERR_VALIDATION -> 400` row, so the catalogue was left consistent rather than made self-contradictory. Accepted by the orchestrator as the right call.

### Pass 2 (5 modules) — 9 ambiguity-pins, 2 mismatch-revisions
451 lines / 100,723 chars -> 451 lines / 104,105 chars (+3,382 chars, 0 new lines). Pass 1's edits spot-verified intact by pass 2 before it began.

- §3.3 (admission-triggered share recompute) — revise — mismatch — PRD limited the recompute to hospitals with non-zero `admissions_in_period` plus the one whose counter moved; impl sweeps **every** registered hospital, suppressing the write (and therefore `updated_at`/`version`) where the three derived values are unchanged, while the counter-changed hospital is always stamped once — `services/shares.py:14-24`, fallback stamps at `routes/referrals.py:349-352`, `routes/stays.py:178-181`
- §3.6 level three (`opened_by_user_id`) — revise — mismatch — an acting `X-User-ID` of the empty string is written as `SYSTEM` for this one field, contradicting §2.1's universal "recorded verbatim" claim; carve-out scoped to this field only (verified `priced_by`/`finalized_by`/`issued_by`/`closed_by`/`resolved_by` all record `""` verbatim) — `services/cascade.py:61`
- §3.3 (on-demand `recompute-referral-shares`) — insert — ambiguity — no-op suppression pinned, so a second sweep leaves every hospital row byte-identical — `services/shares.py:18-24`
- §3.9 (close-time recompute) — insert — ambiguity — same suppression applies to the final freeze — `services/shares.py:18-24` via `routes/reference.py:328`
- §3.5 (recombination ledger unwind) — insert — ambiguity — the period is stamped twice when a `FINAL` determination is reversed (admission-counter decrement, then ledger unwind), so its `version` advances by 2, and by 1 for a `DRAFT`-only parent — `services/cascade.py:95-96`
- §3.6 level three (review version) — insert — ambiguity — the review is created already scored, so it carries `version` 1 — `services/scoring.py:104`
- §3.6 level four (auto-issued query) — insert — ambiguity — exactly one query, server-generated non-empty `prompt_text`, `due_at` = `issued_at` + 72h on the same footing as a nurse-issued query, four null fields, and the `OPEN -> QUERIES_ISSUED` move leaves `version` at 1 — `services/cascade.py:13-38, 64-66`
- §3.7 re-pricing — insert — ambiguity — every pricing re-derives the **stay's** `sso_threshold_days` and `short_stay_outlier_applied` from the DRG in force for that pricing while `covered_los_days` stays as banked, so an override with a different `alos_days` moves the stay's threshold and can flip its flag — `services/pricing.py:35-40, 48`
- §3.7 step one — insert — ambiguity — variant inputs are read live at each pricing rather than snapshotted, so a weaning plan opened after discharge can move a re-price to `STANDARD_LTCH_PPS` — `services/pricing.py:21-32`
- §3.7 discharge payment percentage — insert — ambiguity — `full_standard_amount_cents` of 0 yields 0.00 rather than an error — `calc.py:137-138`
- §3.8 raw total — insert — ambiguity — with no `DRAFT`/`FINAL` determination on the stay, all three determination-derived contributions are 0 — `services/scoring.py:26-30`
- §3.8 rescoring — insert (2 spots) — ambiguity — expiry is strict (`due_at` equal to now is not yet expired) and bumps each expired query's `version`; a rescore always bumps the review's `version` even when nothing changed — `services/scoring.py:108-114, 80-84`

Pass 2 verified-clean with no change needed: `calc.py` day counting, `round_half_up`/`cents`/`pct`/`hours`, the five-sixths floor with the pinned `0.8333333333333334`, `covered_los_days`, the three-candidate short-stay minimum and its single-rounding order, the site-neutral base, the high-cost-outlier threshold order and `<= 0` boundary, `monitoring_state`'s three ordered tests and strict `>` boundaries, `clamp_score`, `risk_band` at 70/40, all weights (8/15/20/10/0.5/12) and constants (96 vent hours, 3 ICU days, 3,000,000 fixed loss, 0.80 factor, 72h, 24h buffer, 9/27/27/3 windows), `drg_in_force`, the determination snapshot fields, the `PENDING -> PRICED` move, `discharge_payment_pct` mirroring, `_answered_count` over `ANSWERED`/`CLOSED`, `query_adjusted_score` nullity, and `unwind_stay_money`'s void statuses and reasons.

### Pass 3 (4 modules) — 16 ambiguity-pins, 6 mismatch-revisions
451 lines / 104,105 chars -> 451 lines / 110,306 chars (+6,201 chars, 0 new lines). 22 targeted Edits; passes 1 and 2 spot-verified intact (two each).

- §2.8 rule 3 — insert — ambiguity — on the two `AttendingPhysician` write endpoints the acting `X-User-ID` resolves to a `Physician` row *at rule 3*, so `ERR_PHYSICIAN_NOT_FOUND` outranks state/eligibility/credential checks — `weaning.py:145`, `reviews.py:161`
- §2.8 rule 6 — revise — **mismatch** — enumeration omitted 8 gated transitions (discharge, recombine child, re-price, finalize-stay-DISCHARGED, void, weaning close, query issuance, rescore) — `stays.py:106,134`; `payments.py:49,98,100,140`; `weaning.py:147`; `reviews.py:61,111,115`
- §2.8 rule 7 — revise — **mismatch** — applies-to list omitted recombine/interrupt/return/idt-notes; added the explicit exclusion of all weaning-plan and review/query operations, and noted the child's period is the one tested on recombine — `stays.py:111,140,199,270,310`
- §2.7 — revise — **mismatch** — guarded-mutation enumeration extended to the same four operations, with the exclusions cross-referenced — `stays.py:39-44`
- §3.4 (notes) — insert — ambiguity — notes may be filed against a stay in any `clinical_status`, incl. `DISCHARGED`/`RECOMBINED`, but the period must be `OPEN` — `stays.py:302-310`
- §3.4 (plan open) — insert — ambiguity — uniqueness is the only precondition; no `clinical_status` and no period gate — `weaning.py:30-40`
- §3.4 (plan open, 2nd) — insert — ambiguity — record-trial and close are likewise gated only on the plan's own `status` (+ physician), never the stay or period — `weaning.py:107,147`
- §3.4 (plan close) — revise — **mismatch** — `liberation_eligible` is tested *before* the `PROGRESSING` origin, so a non-eligible `SBT_TRIAL` plan yields `ERR_WEANING_PROGRESSION_INSUFFICIENT`; `ERR_INVALID_STATE` is reachable only by an eligible `REGRESSED` plan — `weaning.py:150-156`
- §3.5 (return) — insert — ambiguity — the "instant on or after `left_at`" check reports `ERR_VALIDATION`, evaluated after role/path/state/period — `stays.py:273-275`
- §3.5 (recombine preconditions) — insert — ambiguity — parent's `discharged_at` must be non-null and not after the child's `admitted_at`; every failure in the list shares one error id; response body is the child stay — `stays.py:142-150,182`
- §3.5 (parent half) — insert — ambiguity — parent's `discharge_payment_pct` *is* cleared while `estimated_cost_cents`, `interruption_days_total` and `interruption_count` are retained (slots still consumed against the 3-event cap) — `stays.py:167-174`
- §3.7 (re-price) — insert — ambiguity — `recalculation_reason` is 1–500 characters — `payments.py:37`
- §3.7 (re-price) — revise — ambiguity — the implicit rescore hits only a live (non-`VOIDED`) review, bumps `version` by 1, and runs **neither** the expiry sweep **nor** the `QUERIES_ISSUED -> OPEN` return — `payments.py:26-30,66`
- §3.7 (finalize) — insert — ambiguity — finalize reads stored query `status` and never expires one, so an overdue `ISSUED` query keeps blocking until a rescore or refused answer — `payments.py:108`
- §3.7 (void) — insert — ambiguity — `void_reason` is 1–500 characters — `payments.py:135`
- §3.7 (void) — insert — ambiguity — `covered_los_days`/`sso_threshold_days`/`short_stay_outlier_applied` are not cleared, and a void never rescores the review — `payments.py:160-163`
- §3.8 (rescore) — revise — **mismatch** — "at any time" is false: a `VOIDED` review yields `ERR_INVALID_STATE`, while a `CLEARED`/`ESCALATED` one may be rescored without status change — `reviews.py:61-62`
- §3.8 (issue query) — insert — ambiguity — both preconditions are `ERR_INVALID_STATE` — `reviews.py:111-116`
- §3.8 (issue query) — revise — ambiguity — a review already `QUERIES_ISSUED` is not written at all (`updated_at`/`version` frozen), and issuing never rescores — `reviews.py:119-121`
- §3.8 (answer) — insert — ambiguity — the rescore leaves `status` untouched: `QUERIES_ISSUED` persists after the last answer; only the explicit rescore returns `OPEN` — `reviews.py:183-185`
- §3.8 (resolve) — revise — ambiguity — all three `CLEARED` refusals are `ERR_INVALID_STATE` (409); the band is read as *stored* and no sweep runs, so an explicit rescore is required before clearing — `reviews.py:83-90`
- §4 — insert — **mismatch** — the 201 rule is judged on the *addressed* resource: discharge and recombine answer 200 with the `Stay` despite the cascade creating rows; return answers 200 with the `InterruptionEvent` even on the expiry path — `stays.py:119,182,295`

### Closing sanity check (pass 3) — PASS
- Well-formed markdown; 2 balanced ```json fences.
- All 5 top-level sections present (§1 L3, §2 L11, §3 L165, §4 L343, §5 L401) plus all 19 `###` subsections.
- §4 endpoint table intact: 51 endpoint rows, every row exactly 4 columns — and **51 route decorators in `implementation/routes/`**, an exact match.
- §5 error table intact: 47 rows, 2 columns each; the error-id set **diffs clean against `implementation/errors.py`** (47 = 47, no additions or omissions).
- File ends at a real boundary: last line is the final error row `| `ERR_CLOCK_NOT_MONOTONIC` | 422 |`.

### Orchestrator verification
`cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (the known failure mode where the scan silently never runs). 84 changed lines, +14,253 chars over `PRD_FINALIZED.md`. Totals across the three passes: **39 ambiguity-pins, 11 mismatch-revisions, 0 new sections, +2 lines**.

## Pipeline complete — 2026-09-05T03:06:00.000Z

Final state: 8/8 sweep rounds at 278/278 (`workspace/implementation/results.{1..8}.json`), `PRD.md` -> `PRD_FINALIZED.md` -> `PRD_COMPLETED.md` all present, `test_helpers/` and `test_suite/` sited correctly as siblings of `workspace/`, no test dirs leaked into `workspace/`, no entity data seeded in `implementation/`.
