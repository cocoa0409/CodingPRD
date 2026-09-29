## Step 1: Create task directory — 2026-09-06T00:08:46.55823570Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2975_rheumatology_practice_biologic_therapy_coordination and its workspace/ subdirectory (pre-assigned path, index fixed by scenario number 2975; no index auto-allocation performed). Also created per-step scratch dirs under .scratch/.

## Step 2: Generate scaffold — 2026-09-06T01:45:51.554323858Z

All three scaffold artifacts are complete, parse as YAML, and the lint is clean.

## Files (line counts, all `yaml.safe_load` clean)

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 2744 | `scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (neither design key present) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1839 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4753 | `scaffold_corner_design` only |

`python3 -c "import yaml; yaml.safe_load(open(<path>))"` succeeds for all three (verified after every chunked append; the final run printed the key lists above with no exception).

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    45
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     67
  Calls scanned (§1.8+§1.9):  1104

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two violations were found and fixed on the way to clean: the consistency-model instance used a non-existent `POST /patients/{id}/screening-records` (correct endpoint is `POST /screening-records`, `InfusionNurse` only) and captured `$.data.total_count` off an array-output list endpoint plus an undeclared `is_current` field; both were rewritten to real endpoints/fields.

## Domain model

- **12 entities**: Patient, Clinician, Visit, Drug, PayerPlan, ScreeningRecord, MonitoringLab, TherapyEpisode, Authorization, AssistanceEnrollment, InfusionChair, InfusionAppointment. Topology flat, relationships one-to-many + self-referential (`TherapyEpisode.prior_episode_id`) + cross-aggregate.
- **45 endpoints** under one prefix, including two computed reads (`GET /therapy-episodes/{id}/cost-share-estimate`, `GET /patients/{id}/quality-report`), a deferred-action sweep (`POST /_ops/run-reauthorization-calendar`) and the logical clock (`POST /_clock/set_current_utc`).
- **6 state machines over 5 entities** (TherapyEpisode carries two: `therapy_state` PLANNED/ACTIVE/HELD/DISCONTINUED and `funding_state` UNFUNDED/PENDING_AUTH/AUTHORIZED/LAPSED), 5 of them non-linear: Visit, TherapyEpisode x2, Authorization (DRAFT<->SUBMITTED<->DENIED appeal cycling, APPROVED->EXPIRED), AssistanceEnrollment, InfusionAppointment.
- **15 calculations**, 2 of them dual-variant (`visit_disease_activity_score` CDAI vs DAS28_CRP; `episode_cost_share_estimate` PHARMACY vs MEDICAL with a hospital-outpatient multiplier), plus `assistance_benefit_application` (six strictly ordered steps), `screening_status_derivation` (TB/HBV ladders on a 365-day validity), `step_therapy_evaluation`, `quality_report_aggregation` (half-open window).
- **48 ordered validations / 46 error codes**, priorities 1-48: auth (1-4), existence (5-11), shape/reference (12-15), OCC (16-17), state gates (18-28), clinical prerequisites (29-35), policy (36-41), temporal/uniqueness/capacity (42-48).
- **7 roles**: Rheumatologist and InfusionNurse (entity_backed -> Clinician), PriorAuthCoordinator, PayerReviewer, BenefitsCounselor, RegistryAdmin (opaque), Patient (entity_backed, own-record read only). Role model is segregation_of_duties (`ERR_SEGREGATION_OF_DUTIES` on self-attesting an assistance enrollment).
- **Concurrency**: OCC only — 2 rules, `episode-create-stale-patient` (`ERR_STALE_PATIENT_VERSION` 412) and `authorization-create-stale-episode` (`ERR_STALE_EPISODE_VERSION` 412). No forbidden race vocabulary anywhere in the three files.

## Design-file counts

- **§1.8**: 9 difficulty rules x 2 instances = **18 instances**, all with executable `setup_api_calls` chains.
- **§1.9**: **85 corner instances** across all nine sections — entities 13, state_machines 15, calculations 20, validations 19, endpoints 5, errors 2, rbac 6, cross_cutting_complexity_layers 4, consistency_model 1. Of those, **67 carry full test recipes** and **18 are `excluded_because` stubs**, each citing one of the 18 §1.8 instances by name.
- Cross-file checks run: all `grounds` references resolve to real SCAFFOLD.yaml anchors (0 unresolved out of 103 instances), instance names unique across both design files (0 duplicates), no stub carries a `test_recipe`, no full instance has an empty `setup`/`setup_api_calls`/`trigger`/`assert`, and every call object has `call`/`payload`/`as`.

Orchestrator verification: all three files present; `grep -n "harder than expert"` across all three returns nothing, so the difficulty directive did not leak into the scaffold (and cannot reach PRD.md via the `scenario:` key, which holds only the verbatim scenario text). `workspace/` and `worklog.md` intact.

## Step 3: Copy shared files — 2026-09-06T01:45:51.568281991Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T02:04:34.801386905Z

Step 4 complete. `workspace/PRD.md` is written in full (built incrementally, 13 heredoc appends, no one-shot Write).

## Verification

**Final line count: 479** (104,755 bytes)

Heading outline:
```
1:# Rheumatology Biologic Coordination API — Product Requirements Document
3:## 1. Introduction
11:## 2. Global Specifications & System-Wide Principles
15:### 2.1. User and Role-Based Access Control
34:### 2.2. API Response Structure
36:#### Standard Success Response Format
61:#### Standard Error Response Format
83:### 2.3. Pagination
91:### 2.4. Resource Identity, Timestamps and Revision Counters
101:### 2.5. Addressing, Path Resolution and Reverse Reachability
109:### 2.6. Optimistic Concurrency on Patient and Episode Revisions
119:### 2.7. Numeric Precision, Currency and Percentage Rounding
127:### 2.8. Conserved-Quantity Ledgers
137:### 2.9. Cascade Discipline and the Two Independent Episode State Axes
145:### 2.10. Rejection Precedence
200:### 2.11. The Logical Clock and the Deferred Reauthorization Sweep
206:## 3. Business Logic & Workflows
208:### 3.1. Practice Reference Data, Drug Policy Attributes and the Chair Roster
222:### 3.2. The Clinic Visit: Booking, Check-In and Disease Activity Scoring
242:### 3.3. Screening Prerequisites and the Derived Infection Postures
254:### 3.4. Opening a Therapy Episode: Line of Therapy, Benefit Routing and Activation
274:### 3.5. Prior Authorization, Step Therapy and Formulary Exceptions
296:### 3.6. Periodic Monitoring, Toxicity Grading and the Automatic Safety Hold
310:### 3.7. Infusion Scheduling, the Member Cost Waterfall and Assistance Application
342:### 3.8. Assistance Programs, Segregation of Duties and the Reauthorization Calendar
358:### 3.9. Interrupting, Resuming and Ending Therapy, and Reporting on the Result
378:## 4. Endpoint Definitions
430:## 5. Error Code Catalogue
```

Last 3 lines verbatim (document ends on a complete table row of the final section):
```
| `ERR_SITE_OF_CARE_MISMATCH` | 422 |
| `ERR_REGISTRY_CONSENT_MISSING` | 422 |
| `ERR_QUALITY_PERIOD_NO_VISITS` | 422 |
```

## Hard Contracts

**Contract 1 — Field-Name Coverage: PASS.** Extracted all 131 `entities[].fields[].name` values plus all 143 distinct `input:` identifiers (request bodies, query params) and the single `{id}` path param; every one appears verbatim inside backticks in PRD.md (0 missing, verified by exact-literal search). A second, looser pass over all 198 multi-word snake_case tokens in the scaffold found only scaffold metadata keys (`side_effects`, `applies_to`, `common_fields`, calculation ids, category labels) and pseudocode locals (`deductible_pool`, `coverage_pct`, `gross_assistance_cents`, `in_window`, `elapsed_days`, `biosimilar_doses`) absent as literals — each is expressed in prose at the correct site. No persisted or wire field name is missing.

**Contract 2 — Rule Coverage: PASS.** §2.10 contains an explicit 1-48 ladder; a mechanical diff of `(priority, error_id)` against the scaffold's `validations:` block matches all 48 in order with zero deviations. All 32 transitions across the 6 state machines are narrated with their triggers, including the system-driven ones (`DRAFT->EXPIRED` on supersede, `APPROVED->EXPIRED` and `AUTHORIZED->LAPSED` from the sweep, `LAPSED->PENDING_AUTH` on reauthorization, `EXHAUSTED->ACTIVE` on release, `ADMINISTERED->SCHEDULED` reversal, `REAUTH_PENDING->TERMINATED`). Both `concurrency_rules` (OCC on `expected_patient_version`/`expected_episode_version` -> 412) are in §2.6. All 15 calculations are specified with their exact constants — every numeric constant in the scaffold's `calculations:` block appears in the PRD except five worked-example intermediate values (`138759`, `111007`, `27752`, `124883`, `13876`), deliberately omitted as test-targeting numbers. Both conserved-quantity ledgers and all four counter-movement directions are in §2.8; the four-level hold/discontinue cascade tails are enumerated at each origin.

**Contract 3 — §3 Path Purity: PASS.** All 336 distinct backticked tokens in §3 (lines 206-377) were extracted: none begins with `/`, none is a bare HTTP method, none combines method+path. No unbackticked path-like `/segment` string and no bare `GET|POST|PUT|PATCH|DELETE` token occurs anywhere in §3.

## Coverage audit

- **Entities (12/12):** `Patient`, `Clinician`, `Drug`, `PayerPlan`, `InfusionChair`, `Visit`, `ScreeningRecord`, `TherapyEpisode`, `Authorization`, `MonitoringLab`, `InfusionAppointment`, `AssistanceEnrollment`. §2.4 records that `ScreeningRecord` and `MonitoringLab` carry no `updated_at`/`version`.
- **Endpoints (45/45):** the §4 table diffs exactly against the scaffold on `(method, path)`, and a per-row role-set comparison against `endpoints[].roles` produced 0 mismatches. 201 on creation / 200 elsewhere stated in the intro paragraph; no request, response or side-effect columns.
- **Errors (46/46):** §5 matches the scaffold id->`http` map exactly (0 missing, 0 extra, 0 status mismatches), grouped by status, two columns only, no trigger column.
- **Roles (7/7):** all named in §2.1 with their identity translation (`entity_backed:Clinician` for `Rheumatologist`/`InfusionNurse`, `entity_backed:Patient` for `Patient`, opaque for `PriorAuthCoordinator`, `PayerReviewer`, `BenefitsCounselor`, `RegistryAdmin`) and the four ownership sites.
- **§2.2** is byte-identical to the doc-generator skill's `section-2.2-response-structure.md` (diff clean).
- **Deliberate omissions:** worked-example arithmetic results from the scaffold's calculation notes; `PROGRAM_CLOSED` is enumerated with an explicit note that no specified operation writes it.
- **Determinizations of scaffold self-contradictions** (each written as one unambiguous reading): `routing_frozen` set at episode creation and never recomputed; episode `version` untouched on a non-final authorization denial; resume precondition order follows the priority ladder (`HELD` -> funding -> monitoring -> protocol -> washout); the authorization selector's internal ordering overrides the general ladder for `ERR_AUTHORIZATION_UNITS_EXHAUSTED` vs `ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW` (stated as a caveat in §2.10); `therapy_exposure_weeks` is 0 for episodes discontinued out of `PLANNED`; chair-conflict interval pads both sides with the turnover buffer, upper bound exclusive; §2.4 adds the global rule that `version` advances only where the document says it advances.

Orchestrator verification (truncation guard): independently confirmed 479 lines, tail ends on a complete final table row of §5 (the last section), and a mechanical recount of §5 against SCAFFOLD.yaml `errors:` gives 46 in PRD vs 46 in scaffold, 0 missing / 0 extra. Not truncated — no regeneration needed. `grep -in "harder than expert|expert level"` over PRD.md returns nothing, so the Step 2 difficulty directive did not reach the PRD.

## Step 6: Generate implementation — 2026-09-06T02:34:49.488585638Z

Implementation complete and verified.

## Modules (21 files, 3582 lines) — all under `workspace/implementation/`

| file | lines | role |
|---|---|---|
| `app.py` | 48 | `create_app()`, blueprint registration, `ApiError`/`HTTPException` handlers, `PORT` bind |
| `store.py` | 187 | in-memory `Store` (12 dicts), logical clock, id/timestamp/date helpers, `sort_rows`, version stamping |
| `errors.py` | 125 | all 48 error ids -> fixed HTTP statuses, `ApiError`, `fail()` |
| `response.py` | 81 | meta/response_type/data envelope, pagination meta, Decimal encoding |
| `auth.py` | 78 | header auth, 7 roles, `endpoint(roles)` decorator, ownership helper |
| `validation.py` | 267 | body/query validators, `parse_float=Decimal` for decimal-width rules |
| `constants.py` | 145 | every enum tuple and named constant (washout matrix, tier bands, caps) |
| `calculations.py` | 566 | all 15 derivations: CDAI/DAS28, escalation, screening postures, line of therapy, benefit routing, monitoring status, lab grades, step therapy, cost-share waterfall, authorization selection, assistance application, quality report |
| `cascades.py` | 164 | the shared hold/discontinue/supersede unwinding tail |
| `serializers.py` | 260 | 12 resource serializers (drops private keys, recomputes derived postures at read) |
| `routes/__init__.py` | 27 | `BLUEPRINTS` |
| `routes/reference.py` | 230 | patients, clinicians, drugs, payer plans, chairs, quality report |
| `routes/visits.py` | 194 | book / check-in / score / read / list |
| `routes/screening.py` | 91 | screening records |
| `routes/episodes.py` | 294 | create, list/read, activate, hold, resume, discontinue, record-training, cost-share-estimate |
| `routes/authorizations.py` | 243 | create, attest-exception, submit, determination, read/list |
| `routes/labs.py` | 80 | monitoring labs + automatic safety hold |
| `routes/appointments.py` | 261 | schedule, administer, reverse, cancel, read/list |
| `routes/assistance.py` | 135 | enroll, attest, reauthorize, read/list |
| `routes/ops.py` | 65 | clock setter + reauthorization sweep |
| `routes/common.py` | 41 | resolve/paginate/uniqueness helpers |

Plus `start.sh` (reads `$PORT`, foreground `exec python3 app.py`, binds 0.0.0.0) and `requirements.txt` (`Flask==3.0.3`).

## Compile clean
`python3 -m compileall -q .` -> `COMPILE_OK`; `__pycache__` removed afterwards so the tree ships as source only.

## Endpoints
`app.url_map` enumerates **exactly 45 rules — all 45 PRD endpoints, none missing, none extra** (`static_folder=None` keeps Flask from adding `/static`). Full list verified against PRD §4.

## No seeding, in-memory only
At import time all 12 collections are empty. No SQLite, no file writes, no /tmp cache — grep-clean of `open(`/`sqlite`/`pickle` in the impl tree. Every fresh boot starts empty, and the clock starts at the PRD epoch `2026-08-01T00:00:00.000Z`.

## Smoke test (PORT=20980, pid 192979, killed by exact pid)
Nine checks all as documented: `POST /patients` -> **201** with the documented envelope and derived fields (`tb_screen_status":"MISSING"`, `hbv_screen_status":"INCOMPLETE"`, `target_status":"UNASSESSED"`, `version":1`); `GET /patients/{id}` -> **200** identical resource; no headers -> **401 ERR_UNAUTHENTICATED**; unknown id -> **404 ERR_PATIENT_NOT_FOUND**; bad enum -> **422 ERR_INVALID_REQUEST**; `Patient` role posting -> **403 ERR_FORBIDDEN_ROLE**; `GET /visits?limit=1` -> **200** with `limit/offset/total_count/has_more`; clock setter -> **200**; sweep -> **200** three zero counters. Process stopped cleanly.

## Additional end-to-end exercise (agent's own extra check)
`.scratch/step6/e2e.py` (+ `run_e2e.sh`), a 150-assertion driver covering the full workflow: reference data, visit capacity cap and abutment boundary, CDAI 33.0/HIGH/ESCALATE and DAS28 3.54/MODERATE arithmetic, screening postures, episode create with stale-version 412, draft supersede, step-therapy denial and appeal round, approval ledger and window defaults, lab grading and the automatic hold, activation gates, cost-share waterfall vector `[205000,125000,125000]`, appointment reserve/administer/reverse/cancel with both ledgers conserved, chair turnover-buffer conflict on both sides, assistance segregation-of-duties, hold cascade + washout resume, discontinue exposure freeze and enrollment termination, sweep expiry and idempotency, quality report, pagination and enum-filter 422s. Final run on a fresh boot: **FAILURES: 0**.

Three initial mismatches were all errors in the agent's own driver's expected values; re-reading the PRD confirmed the implementation was right in each case: PRD §3.5 lapses any AUTHORIZED episode on sweep regardless of `therapy_state` (a DISCONTINUED episode still counts in `episodes_lapsed`); §3.2 yields `OPTIMIZE_CURRENT` for MODERATE when no 90-day-old ACTIVE episode exists; and the coinsurance total is 280000 because the deductible absorbs part of dose 1 before coinsurance applies.

No `test_suite/`, `test_helpers/`, or sibling `task_*/` directory was read. Scratch confined to `.scratch/step6/`. `worklog.md`, `SCAFFOLD*.yaml`, `PRD.md`, `INSTRUCTION.md` untouched. No broad `pkill` was run — both smoke servers were killed by their exact captured pids.

## Step 5: Generate unit tests — 2026-09-06T02:54:26.383141316Z

All nine queue-A files are written and the whole suite verifies clean.

## Deliverables (both at the task root, not under `workspace/`)

`test_helpers/` — 2499 lines: `__init__.py` 28, `api_client.py` 212, `api_errors.py` 107, `assertions.py` 386, `constants.py` 201, `factories.py` 311, `fixtures.py` 678, `test_users.py` 79, `types.py` 497.

`test_suite/` — 7677 lines: `conftest.py` 108; queue A `test_01` 306, `test_02` 224, `test_03` 239, `test_04` 275, `test_05` 282, `test_06` 257, `test_07` 235, `test_08` 234, `test_09` 150; queue B (five partitioned subagents) `test_10` 457, `test_11` 445, `test_12` 558, `test_13` 505, `test_14` 516, `test_15` 711, `test_16` 456, `test_17` 620, `test_18` 463, `test_19` 636.

## Verification

- `python3 -m compileall -q test_helpers test_suite` -> clean; `__pycache__` removed afterwards.
- All 19 test modules plus the helpers import successfully (every `from`-import symbol resolves); an AST pass confirms every `api_client.*` / `ApiErrorId.*` / `assertions.*` / `factories.*` / `fixtures.*` / `constants.*` attribute exists.
- Tag audit over all 156 test functions: each docstring's **last** line is exactly one `Design:` tag; zero untagged, zero dual-tagged, zero tags naming a non-existent instance, zero tags pointing at a stub.
- Every `PRD §x: "..."` quote in the queue-A files was machine-checked as a verbatim (whitespace-normalised) substring of `workspace/PRD.md`.
- No `test_helpers/`/`test_suite/` anywhere under `workspace/`; the only `worklog.md` is the untouched one at the task root; scratch confined to `.scratch/step5/`. No pytest run, no `pkill`.

## Tests emitted

**156 test functions** (parametrisation in the corner files raises collected cases to roughly 190).

- **Queue A (§1.8): 18/18 live instances translated, every one with >=2 tests — 59 tests.** `dual_variant_calc` x2, `combinatorial_formula` x2, `compensating_invariant` x2, `resource_temporal_overlap` x2, `boundary_precision_check` x2, `non_linear_state_machine` x2, `transitive_cascade` x2, `cross_entity_state_dependency` x2, `priority_pair_validation_conflict` x2.
- **Queue B (§1.9): 67/67 live instances translated, every one with >=1 test — 97 tests.** The 18 stub instances were correctly left untranslated, and all their `difficulty_instance` pointers resolve to real §1.8 names.

## Skipped instances: none

Both queues fully translated; skip list empty. Judgements worth surfacing to Steps 7-9, all resolved PRD-first:

- **`chair_time_conflict_outranks_exhausted_authorization_units_on_scheduling`** looked unsatisfiable (§3.7 runs the authorization selector *before* the chair calendar). §2.10's second clarification limits the §3.7 override to the `ERR_AUTHORIZATION_UNITS_EXHAUSTED`-vs-`ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW` pair, so the ladder governs and `ERR_CHAIR_TIME_CONFLICT` (45) wins over 48. Test asserts the 409 chair conflict and explicitly `!=` the units error.
- **Two yaml/PRD status conflicts, PRD wins:** yaml says `ERR_REFERENCE_NOT_FOUND` is 422 (PRD §5/§3.2 and `api_errors.py` say **404**); yaml says `ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW` is 422 (PRD §3.7/§5 say **409**).
- **Sub-assertions dropped as not PRD-derivable** (instances kept, not weakened elsewhere): `activated_at` on `TherapyEpisode` (no such field in the PRD) in three §1.9 validation instances; the contested `episode.version + 1` on a second authorization intake; "no row exists afterwards" claims where §4 exposes no list/GET to prove them (substituted an equivalent duplicate-key retry proof); the `created_at` tie-break order inside a single-instant pagination page.
- Instant literals in the design yamls are bare-second while §2.4 mandates three fractional digits — all instant comparisons go through `assert_instant_equals`, which canonicalises width.

## Step 7: Run tests and iterate — 2026-09-06T03:16:00.909680643Z

Fully green. Cleanup done: `.scratch/step7/` removed, sibling scratch dirs intact, no stray listener, storage still in-memory only (the one `json.dumps` is response serialization, not persistence), and `worklog.md` untouched by the subagent.

## Summary

**Iterations run:** 1 beyond the baseline (baseline sweep -> 1 fix batch -> verification sweep).

**Final sweep evidence** — all 8 rounds green:

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 197/197 | 197/197 | 197/197 | 197/197 | 197/197 | 197/197 | 197/197 | 197/197 |

Baseline was 191/197 in every round — 6 deterministic failures, identical across all 8 rounds, so no load-induced flakiness was in play. Union of failures = 6 = total - passed, cross-checked on the `status` key.

**Tests deleted:** none. Both failure clusters survived STEP 1 (coverage + unique derivability), so neither was a PRD-silence case.

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py`, `open_planned_episode` — the helper passed `patient_id`/`drug_id`/`payer_plan_id` positionally into `create_therapy_episode_payload` while also forwarding `**overrides`, so any caller wanting a second molecule (`drug_id=...`) crashed with `TypeError: got multiple values for argument 'drug_id'` before issuing a request. The three body references (plus `expected_patient_version`, the same latent trap) are now popped from overrides and honoured by name. This was a pure test-artifact bug that accounted for 4 of the 6 failures across `test_03` and `test_15`.

**Fixes applied to `implementation/`:**
- `calculations.py`, `select_authorization` — now returns `(winner, error_id)` and neither raises nor mutates, so its outcome can be ranked by the caller.
- `routes/appointments.py`, `schedule_appointment` — reports the scheduling rejection by PRD §2.10 ladder position instead of by §3.7's narrative order.

**The judgement call worth flagging.** The two remaining failures asserted `ERR_CHAIR_TIME_CONFLICT` where the implementation returned `ERR_AUTHORIZATION_UNITS_EXHAUSTED`, and the PRD genuinely pulls in two directions here:

- §3.7 narrates the selector first ("The authorization selector then runs...") and the chair check second ("**Only then** is the chair's calendar consulted"), which is exactly what the implementation did.
- §2.10, the section titled *Rejection Precedence*, opens with a global law — "When a request violates more than one rule, exactly one error is returned... The server evaluates in the following order and stops at the first failure" — and ranks `ERR_CHAIR_TIME_CONFLICT` at 45, ahead of `ERR_AUTHORIZATION_UNITS_EXHAUSTED` at 48.

The tests were kept rather than relaxed to `validate_error_is_one_of`, on three grounds. First, §2.10 is where the PRD tells you to look for "which error when several are violated," and it claims that authority explicitly. Second, its carve-out is deliberately narrow — the §3.7 internal ordering "governs which of `ERR_AUTHORIZATION_UNITS_EXHAUSTED` and `ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW` is reported, overriding the relative positions **those two** occupy" — naming one pair and no other. Third, and decisively: under the §3.7-procedural reading the ladder's placement of 45 before 48 would be unobservable dead text, since chair conflict only arises on the very operation whose selector runs first. The carve-out's existence *and* its narrowness is the tell — the author flagged the one place the selector deviates from the ladder and left 45-before-48 standing.

So the harmonised rule now implemented is: §3.7's internal ordering settles which selector error applies (preserving window-before-units), then §2.10 ranks that outcome against the chair calendar — window (42) -> chair conflict (45) -> units exhausted (48). This does not regress the neighbouring `test_a_start_clear_of_the_buffer_isolates_the_unit_rule`, which must still report `UNITS_EXHAUSTED` when no chair conflict exists, and no test pairs a window violation with a chair conflict.

Incidental note: the runner has no `-k` selector, so the agent built a throwaway per-test-fresh-server spot-check harness in `.scratch/step7/` to shorten the diagnose loop (it confirmed all 7 relevant tests before spending a sweep cycle). It has since been deleted; the 8-round sweep remained the sole verification mechanism.

Orchestrator verification: independently read all 8 `workspace/implementation/results.$i.json` — every round reports `passed=197, total=197`. Baseline read (before the fix batch) independently showed 191/197 in all 8 rounds, matching the subagent's account. Step 8 is NOT skipped: Step 7 applied 1 `test_helpers/` fix and 2 `implementation/` fixes.

## Step 8: Finalize PRD — 2026-09-06T03:19:28.410822898Z

Done. `PRD_FINALIZED.md` written with three surgical revisions.

**Line counts:** PRD.md 479 -> PRD_FINALIZED.md 479 (no change in line count); 3 of 479 lines revised = **0.6% line delta**, all inserts within existing paragraphs. No new sections, no deletions. Tail verified: still ends with the complete §5 error table.

**Changes**

- **§2.10 (Rejection Precedence, the "two clarifications" paragraph, line 198)** — *revise (append clause)* — states that the §3.7 carve-out settles only `ERR_AUTHORIZATION_UNITS_EXHAUSTED` vs `ERR_APPOINTMENT_OUTSIDE_AUTH_WINDOW` against each other and admits no third error, and that the selector's outcome is then ranked against the chair-calendar check by ordinary ladder position: window (42) -> chair conflict (45) -> units exhausted (48) — `routes/appointments.py:86-99`.
- **§3.7 (authorization selector paragraph, line 316)** — *revise (append sentence)* — the selector only *computes* an outcome (winner, or the single error its own ordering arrives at) and writes nothing while running; the unit leaves `units_remaining` only after the chair check has also passed, so a refused scheduling request leaves every authorization's unit ledger untouched and persists no appointment — `calculations.py:414-449` (returns `(winner, error_id)`, no raise/mutate) and `routes/appointments.py:111-113, 139-141`.
- **§3.7 ("Only then is the chair's calendar consulted", line 318)** — *revise (clause inserted after the opening phrase)* — the narrated order of the two checks does not itself decide the error for a request violating both; §2.10's ladder does, so a window outcome is reported in preference to a chair conflict while a units-exhausted outcome yields to one — `routes/appointments.py:94-99`.

**Per-edit pre-edit search log**

1. **§2.10 edit.** (a) Subject: relative precedence of `ERR_CHAIR_TIME_CONFLICT` against the two selector errors. (b) Enumerated: `grep -rn "CHAIR_TIME_CONFLICT"` over `implementation/` — only `errors.py:37,92` (status/message tables) and `routes/appointments.py:87,97`; `_chair_conflict` (appointments.py:34) has exactly one callsite (line 87), and `administer`/`reverse`/`cancel` re-check only `ERR_CHAIR_CLOSED`, never chair overlap; verified the full scheduling gate sequence (`EPISODE_NOT_FOUND` -> `CHAIR_NOT_FOUND` -> 22 `EPISODE_NOT_ACTIVE` -> 27 `CHAIR_CLOSED` -> 40 `SITE_OF_CARE_MISMATCH` -> 42/45/48) is ladder-monotone, so the added claim does not contradict any earlier gate. (c) Adjustment: scoped the clause to "a scheduling request", and phrased rule 48 as reported "only when no chair conflict exists" rather than asserting any global reordering of the ladder.
2. **§3.7 selector edit.** (a) Subject: when the reserved unit actually moves, i.e. mutation timing of the unit ledger. (b) Enumerated every `units_reserved`/`units_remaining` write in the impl: `routes/appointments.py:111-112` (the only reservation site), `:168-169` (administer), `:209` (reverse), `cascades.py:33-34` (`release_authorization_unit`, used by cancel/hold/discontinue tails), `routes/authorizations.py:61-63` (birth) and `:184-185` (approval sets `units_remaining`); confirmed `select_authorization` (`calculations.py:414-449`) is called only from `routes/appointments.py:86` and performs no writes. (c) Adjustment: narrowed the invariant to *scheduling* refusals and to the *unit* ledger only (dropped a broader "every ledger" phrasing) so the assistance/enrollment paths and the cascade release paths remain undescribed rather than mis-described.
3. **§3.7 chair-calendar edit.** (a) Subject: narrative ordering of selector vs chair check as a precedence rule. (b) Enumerated: `routes/appointments.py:82-99` (the ranking block), the `_chair_conflict` half-open/buffer semantics at `:34-48` (`SCHEDULED`/`ADMINISTERED` only — cancelled rows never block), and confirmed no other endpoint consults a chair calendar. (c) Adjustment: kept the original "Only then is the chair's calendar consulted" opening verbatim and added the precedence clause after it, so the paragraph's remaining buffer/boundary/cancelled-appointment sentences are untouched.

**No edit made for the `test_helpers/fixtures.py` item** — the `open_planned_episode` positional/`**overrides` `TypeError` is a pure test-artifact bug with no PRD implication, so no PRD text was manufactured for it. Likewise no edit for the deleted-test/laxened-assertion categories, since Step 7 deleted no tests and changed no `test_suite/` assertions.

Orchestrator verification: `wc -l` gives 479 for both files; `diff` shows exactly 6 changed lines (3 revised lines, `<`/`>` pairs); `cmp` confirms the files DIFFER (so the copy-only failure mode did not occur); tail still ends on the complete §5 error table, not truncated.

## Step 9: Complete PRD — 2026-09-06T04:02:58.108721495Z

Step 9 was run as FOUR sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2-4 edited in place and never re-copied). Partitioning was by implementation module so no two passes owned the same PRD prose; a fourth reconciliation pass closed the cross-pass contradictions the partition-bounded passes could only report.

**Source vs output:** `PRD_FINALIZED.md` 479 lines / 106,213 chars -> `PRD_COMPLETED.md` 480 lines / 126,147 chars (**+1 line, +19,934 chars**). 54 diff hunks, 109 changed lines. NOT byte-identical to its source. Tail still ends with the complete §5 error table (`| \`ERR_QUALITY_PERIOD_NO_VISITS\` | 422 |`).

**Total counts across the four passes: 60 edits — 49 ambiguity-pins, 11 mismatch-revisions.**

### Pass 1 — cross-cutting + reference data (app/store/errors/response/auth/validation/constants/serializers, routes/common, routes/reference less the quality report, routes/ops)
13 ambiguity-pins, 0 mismatch-revisions (§5's 46-row catalogue matched `errors.py:7-54` exactly; every §3.1 field range/default matched `routes/reference.py`).
- §2.1 — insert — a whitespace-only auth header is not empty: it passes the presence test, so a whitespace-only `X-User-Role` yields `ERR_FORBIDDEN_ROLE`, not `ERR_UNAUTHENTICATED` — `auth.py:28-34`
- §2.2 — insert — `api_request_id` is `req_` plus exactly twenty `[A-Z0-9]` chars — `response.py:11,14-15`
- §2.2 — insert — `api_request_timestamp` comes from the host's real clock, not the logical clock, and no rule is evaluated against it — `response.py:18-28`
- §2.2 — insert — pre-routing failures answer in the error envelope with `error_id` `ERR_INVALID_REQUEST` under the routing status (404 unknown path, 405 wrong method); trailing slashes insignificant — `app.py:21,30-38`
- §2.3 — insert — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; an empty-string value falls back to the default — `validation.py:209-216`
- §2.3 — insert — `created_at` ties (endemic under a static logical clock) broken by server creation order, making paging stable — `store.py:141-147`
- §2.4 — insert — accepted input instant grammar (T-or-space separator, optional seconds + 1-9 fractional digits, `Z`/numeric offset/no designator, offsets converted to UTC, bare values read as UTC) versus the single normalised 3-digit UTC output form — `store.py:20-24,63-100`
- §2.10 rule 12 — insert — JSON `null` treated as absent; undeclared fields ignored — `validation.py:29-52`
- §2.11 — revise — the clock endpoint requires `current_utc` and returns an object with the single normalised field, not a byte-for-byte echo — `routes/ops.py:16-20`
- §2.11 — insert — the sweep declares no input, its `data` is the three-counter object alone, `episodes_lapsed` counts each episode at most once and skips authorizations whose episode is not `AUTHORIZED` — `routes/ops.py:26,43-47`
- §3.1 — revise — `step_therapy_classes_required` members must be distinct; a repeat is a shape violation — `validation.py:178-193`, `routes/reference.py:152-154`
- §3.1 — insert — `medical_facility_fee_cents` may be zero — `routes/reference.py:148`
- §3.1 — insert — chair PATCH accepts only `status`, `status` is required, and re-asserting the current status still refreshes `updated_at` and increments `version` — `routes/reference.py:197-208`
- §3.1 — insert — duplicate-key collision is exact string equality within the same field/collection (case- and whitespace-sensitive) and runs only after shape validation — `routes/common.py:34-41`

Deliberate non-edits: `elapsed_whole_days/weeks` floor-vs-truncate (unobservable — see pass 4 item 6); intra-payload validation order in `routes/reference.py` (every branch raises the same `ERR_INVALID_REQUEST`).

### Pass 2 — clinical path (routes/visits, screening, episodes, labs; cascades.py; the clinical half of calculations.py and serializers.py)
17 edits: 11 ambiguity-pins, 6 mismatch-revisions. +5,133 chars.
- §3.2 — insert — mismatch — booking's ownership check runs after payload shape but before reference resolution, so a well-shaped payload naming a colleague gets `ERR_NOT_RESOURCE_OWNER` even with an unresolvable `patient_id` — `routes/visits.py:40-57`
- §3.2 — insert — `visit_datetime` unconstrained relative to the logical clock — `routes/visits.py:43`
- §3.2 — insert — mismatch — scoring resolves the visit `id` before the ownership comparison, so a bad path id yields `ERR_VISIT_NOT_FOUND` despite rule 4 sitting above rule 6; ownership precedes body parsing — `routes/visits.py:104-110`
- §3.2 — revise — `activity_score`, `activity_category`, `escalation_recommendation`, `scored_at` all null until scored — `routes/visits.py:80-83`
- §3.2 — revise — missing `physician_global_assessment` under CDAI is `ERR_INVALID_REQUEST`, ahead of the `CHECKED_IN` state check — `routes/visits.py:123-130`
- §3.2 — revise — mismatch — "ignored" `crp_mg_dl`/`esr_mm_hr` under CDAI are still persisted and echoed, not discarded — `routes/visits.py:151-152`
- §3.2 — revise — mismatch — same for `physician_global_assessment` under DAS28_CRP — `routes/visits.py:150`
- §3.2 — revise — patient-projection winner's residual tie broken by later insertion — `calculations.py:128`
- §3.3 — insert — a future-dated `resulted_at` gives a negative elapsed count and reads as current — `calculations.py:143-145`
- §3.3 — insert — the completed-treatment record is not currency-filtered; with several current positives, `POSITIVE_UNTREATED` wins if any one lacks a follower — `calculations.py:153-173`
- §3.3 — revise — `EXPIRED`/`MISSING` count only `TB_IGRA`/`TB_TST`; a lone `TB_LTBI_TREATMENT_COMPLETE` leaves the posture `MISSING` — `calculations.py:152,185-187`
- §3.4 — insert — benefit routing settles before the predecessor check (38 beats 39), both below the stale-version check — `routes/episodes.py:65-81`
- §3.4 — insert — the supersede cascade stops at the episode row: no appointment cancellation, no enrollment termination — `cascades.py:145-164`
- §3.4 — insert — mismatch — `record-training` has no state or site precondition; it overwrites `NOT_REQUIRED` and counts the attempt on any episode in any `therapy_state` — `routes/episodes.py:275-284`
- §3.6 — revise — mismatch — a hold-triggering panel on an `ACTIVE` episode advances the episode's `version` by **two** (filing + `ACTIVE -> HELD`), not one — `routes/labs.py:58,64` + `cascades.py:111`
- §3.6 — insert — future-dated `collected_at` reads `CURRENT` — `calculations.py:277-279`
- §3.9 — insert — mismatch — resumption declares no required field and tolerates an absent/empty/non-object body — `routes/episodes.py:207`
- §3.9 — revise — `SUPERSEDED` is outside the discontinue field's declared member set -> `ERR_INVALID_REQUEST` 422 — `routes/episodes.py:267` + `constants.py:88-94`
- §3.9 — revise — `therapy_exposure_weeks` floored at 0 for an episode stopped before its own `therapy_start_at` — `calculations.py:364`
- §3.9 — insert — discontinuation clears `hold_reason`/`held_at`/`resume_not_before` (leaves `hold_count`) and bumps patient `version` even when the active count didn't move — `cascades.py:132-142`

Verdicts on pass 1's five flagged items: (1) `serializers.py:139-140` `monitoring_status -> "OVERDUE"` on an unresolvable `drug_id` — NO EDIT, genuinely unreachable (`drug_id` validated at episode creation, no endpoint deletes a drug); same for the parallel `cascades.py:104-110` fallback. (2) `SCREEN_RESULTS` four-member set — already pinned. (3) `SUPERSEDED` caller exclusion — pinned, strengthened to an explicit enum restriction. (4) ALT/ANC grade-boundary inclusivity both directions — already pinned with worked boundary examples. (5) `SITE_NEUTRAL_AMBULATORY_MAX_MINUTES = 180` and `MAX_LINE_OF_THERAPY = 6` — already verbatim in §3.4.

### Pass 3 — funding, scheduling, assistance, reporting (routes/authorizations, appointments, assistance; the quality-report endpoint; the funding half of calculations.py and serializers.py)
26 edits: 22 ambiguity-pins, 4 mismatch-revisions. +8,171 chars. Step 8's two §3.7 sentences and the §2.10 clarifications paragraph preserved verbatim.
- §3.5 — insert — authorization intake gated on episode existence + version only; lawful against any `therapy_state` incl. `DISCONTINUED` and any `funding_state` — `routes/authorizations.py:47-51`
- §3.5 — revise — pinned the literal supersede note text — `constants.py:116`, `routes/authorizations.py:84`
- §3.5 — revise — mismatch — `funding_state := PENDING_AUTH` is unconditional from any prior value, and the episode `version` advances even when the value did not change — `routes/authorizations.py:87-88`
- §3.5 — revise — an `X-User-ID` resolving to no clinician row also draws the 403; 403 precedes existence as well as state — `routes/authorizations.py:98-106`
- §3.5 — insert — attest-exception reads no body at all (any body ignored) — `routes/authorizations.py:93-112`
- §3.5 — insert — submit declares no input fields; absent/empty/non-object body tolerated (and "four preconditions" -> "preconditions", five are listed) — `routes/authorizations.py:119`
- §3.5 — insert — the occult-risk gate reads the patient posture alone, indifferent to the drug's `hbv_screen_required` — `routes/authorizations.py:132-134`
- §3.5 — revise — `approved_units` is 0..24; `valid_from`/`valid_through` unconstrained against each other and the clock — `routes/authorizations.py:161-163`
- §3.5 — insert — `approved_units > requested_units` is rule 12 and outranks the `SUBMITTED` state check; `approved_units` 0 is lawful; `decision_reason` recorded on approval too — `routes/authorizations.py:165-172,188`
- §3.5 — revise — denial records `decision_reason` as supplied, null when omitted — `routes/authorizations.py:204`
- §3.5 — revise — mismatch — final denial writes `UNFUNDED` unconditionally and always bumps the episode `version`, incl. when already `UNFUNDED`; non-final denial does not write the episode at all — `routes/authorizations.py:208-212`
- §3.7 — insert — `scheduled_start` unconstrained vs the clock; administration never compares the clock to `scheduled_start` — `routes/appointments.py:57,144-161`
- §3.7 — insert — the episode's `funding_state` is not a scheduling gate (a `LAPSED` episode can still be booked via another approved authorization) — `routes/appointments.py:66-76`
- §3.7 — insert — `dose_count` is a required query param, min 1, no max; absent/empty/unparseable/<=0 -> `ERR_INVALID_REQUEST` 422 — `routes/episodes.py:291`, `validation.py:219-233`
- §3.7 — insert — the estimate is a pure read (no enrollment, no assistance figures, no writes) and the plan's `deductible_remaining_cents` is never drawn down by either operation — `routes/episodes.py:287-294`, `calculations.py:382-409`
- §3.7 — revise — mismatch — the vector is computed over `max(approved_units, dose_sequence)`, not `approved_units` — `routes/appointments.py:117`
- §3.7 — insert — the four administration checks run in the operation's own order, which governs outright: a cancelled appointment on a non-`ACTIVE` episode reports `ERR_APPOINTMENT_STATE_INVALID` — `routes/appointments.py:153-161`
- §3.7 — insert — `reversal_reason` stands after re-administration; a further reversal overwrites it — `routes/appointments.py:163-183,204`
- §3.7 — revise — `THERAPY_HELD` is not in the cancel field's member set -> `ERR_INVALID_REQUEST` 422 — `constants.py:127`, `routes/appointments.py:232`
- §3.8 — insert — enrollment has no episode-state gate; `coverage_start` unconstrained vs the clock; the episode is not written and its `version` does not move — `routes/assistance.py:44,46-47`
- §3.8 — insert — attest tolerates absent/empty/non-object body — `routes/assistance.py:76`
- §3.8 — insert — the sweep moves only enrollments actually in `ACTIVE`; `SUBMITTED`/`EXHAUSTED`/`TERMINATED` passed over, but an `EXHAUSTED -> ACTIVE` return is caught by the next run — `routes/ops.py:49-57`
- §3.8 — insert — renewal's `annual_benefit_cents` must be an integer > 0; body optional/non-object tolerated — `routes/assistance.py:94-95`
- §3.8 — insert — `annual_benefit_cents - benefit_reserved_cents` is not floored: it may go negative and the enrollment still lands `ACTIVE` — `routes/assistance.py:111-113`
- §3.8 — revise — mismatch — `TERMINATED` is reachable from `SUBMITTED` and `EXHAUSTED` too (any non-`TERMINATED` status), and `benefit_used_cents` is left standing — `cascades.py:79-89`
- Quality report — insert — `period_start`/`period_end` are required query params (absent/empty/unparseable -> 422), settled after the patient 404 and before the consent check; an inverted window is accepted and falls to `ERR_QUALITY_PERIOD_NO_VISITS` — `routes/reference.py:223-230`, `validation.py:236-248`

Verdicts on its five flagged items: assistance tiering exclusive bounds — already pinned verbatim; `THERAPY_HELD` caller rejection — pinned; `dose_count` required/min 1/error — pinned; enrollment has no episode-state gate — pinned; attest/reauthorize tolerate an absent body — pinned.

### Pass 4 — RECONCILIATION (7-item docket of cross-pass contradictions)
6 new hunks + 2 amended in place. All docket items closed; every finding re-verified against source rather than taken on the reporting pass's word.

1. **Ownership site count — EDITED.** Grepped every `ERR_NOT_RESOURCE_OWNER` raise: `auth.py:78` (`require_patient_ownership`, called from `routes/reference.py:216` single-patient read and `routes/screening.py:82` screening-record list), `routes/visits.py:48` (booking), `:108` (scoring), `:181` (visit list) — **five** sites, not four. §2.1 line 30 revised ("exactly four places" -> "exactly five places", "all four" -> "all five", booking prepended) and §2.10 rule 4 revised to enumerate booking.
2. **Rule 12 over-broad universal — EDITED.** Classified all 36 `read_body(` sites: `required=True` wherever >=1 required field exists; `required=False` at sweep (`ops.py:26`), submit (`authorizations.py:119`), enrollment attest (`assistance.py:76`), reauthorize (`assistance.py:94`), resume (`episodes.py:207`); four operations never call `read_body` at all — check-in (`visits.py:90`), activate (`episodes.py:154`), attest-exception (`authorizations.py:93`), administer (`appointments.py:144`). The invariant is exact: tolerant <=> no required field. Rule 12 rescoped to "at least one **required** input field" and names all nine tolerant operations. The five §3 carve-outs left in place as more-specific and non-contradictory.
3. **Rules 22/24 inversion — EDITED.** `appointments.py:154-161` confirms appointment status before episode state. `reverse` (:194) and `cancel` (:233) never check episode state, so no inversion is possible there; scheduling checks the episode (:66) before any appointment exists — the carve-out is administration-only. §2.10's "Two clarifications" became "Three", with the Step 8 window-42/chair-45/units-48 clarification preserved verbatim. While verifying, the same carve-out proved owed for two more inversions passes 2/3 had pinned only locally — scoring resolves rule 6 before rule 4 (`visits.py:106-108`), booking settles rule 12 before rule 4 (`visits.py:40-48`) — so the Third clarification covers all three; without them its "and nowhere else" would have been false.
4. **§2.6 DRAFT-expiry number — EDITED.** `authorizations.py:78-85` loops every authorization and expires each still-`DRAFT` one. §2.6 line 116 revised to "every one of that episode's authorizations still sitting in `DRAFT` — not merely the most recent of them"; the §4 endpoint table's `/authorizations` row carried the same singular and was aligned.
5. **§2.7 two-decimal-places — EDITED.** `response.py:31-35` returns `float(obj)` for `Decimal`, so `json.dumps` emits `2.8` for `Decimal("2.80")`. The old sentence read as a formatting rule and would license a string or fixed-width emission; now "JSON numbers rounded half up to two decimal places... a rounding rule and not a formatting rule... 2.80 is emitted as `2.8`". The neighbouring one-decimal percentage sentence was left alone: Python float repr always emits at least one fractional digit, so `Decimal("100.0")` really does reach the wire as `100.0`.
6. **Floor-vs-truncate on negative intervals — NO EDIT NEEDED; pass 1 was right.** All four reachable call sites are unobservable: `calculations.py:145` (`<= 365`), `:277` (`<= monitoring_panel_interval_days`, min 1) and `:109` (`>= 90`) compare against non-negative thresholds where -n and 0 fall on the same side; `:363-364` wraps `elapsed_whole_weeks` in `max(0, ...)`. `therapy_exposure_weeks` is the only elapsed quantity ever serialized. Pass 2's two future-dated pins are correct as written and unaffected.
7. **Cross-pass consistency sweep — one contradiction found and FIXED.** Pass 2's §3.2 CDAI sentence claimed the shape rule is reported "ahead of every other scoring gate", contradicting its own sentence four lines earlier ("the ownership comparison is made before the scoring payload is parsed at all"); `visits.py:106-107` vs `:123` settles it, and §3.2 line 235 now reads "ahead of every other scoring gate bar the two that precede the payload entirely". Also re-verified against source the pins most likely to collide — `cascades.py:79-89`, `:145-164`, `:132-134`, `:142`, `calculations.py:382-409`, `appointments.py:117`, `ops.py:49-57`, `store.py:141-147` + `calculations.py:128`, `app.py:30-38` — all mutually consistent and accurate.

**Remaining contradictions: none known.** The three ladder inversions the implementation actually exhibits (24-before-22 on administration, 6-before-4 on scoring, 12-before-4 on booking) are now stated in §2.10 as well as in their local §3 pins, so §2.10's ladder is no longer false anywhere. One cosmetic non-contradiction deliberately left: §2.1's last line says the credential check runs "before any state precondition on the authorization itself" where §3.5 more fully says "before every existence and state check" — incomplete rather than wrong (`authorizations.py:98-106`).

Orchestrator verification: `wc -l` gives PRD.md 479 / PRD_FINALIZED.md 479 / PRD_COMPLETED.md 480; `cmp` confirms PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md (so the copy-only failure mode did not occur — the scan genuinely ran); `diff | grep -c '^[<>]'` = 109 changed lines; tail still ends on the complete §5 error table. Step 9 edited only PRD prose, so the Step 7 sweep remains valid: all 8 `results.$i.json` still read `passed=197, total=197`. Pipeline complete.

