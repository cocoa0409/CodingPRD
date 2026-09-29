# Worklog — task_2883_police_recruit_academy_field_training

## Step 1: Create task directory — 2026-09-05T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2883_police_recruit_academy_field_training` and `.../workspace` (pre-assigned index 2883; no index scan performed, per orchestrator instruction — other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-05T00:00:00.000Z

All three artifacts are complete and lint-clean.

**Final lint (verbatim):**
```
Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     12
  §1.8 instances scanned:     21
  §1.9 instances scanned:     70
  Calls scanned (§1.8+§1.9):  2042

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all parse under `yaml.safe_load`, all non-empty):
- `SCAFFOLD.yaml` — 3036 lines / 172 KB
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 3478 lines / 213 KB (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 8558 lines / 508 KB (single key `scaffold_corner_design`)

SCAFFOLD.yaml top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key leaks into it.

**§1.0–§1.7 counts:** 12 entities, 57 endpoints, 54 error codes, 38 validation rules (priority-ordered ladder 1→82), 8 roles, 12 state machines (4 of them parallel dimensions on Recruit), 8 calculations, 2 OCC rules. Profile: `api_prefix ""`, flat topology, cyclic state machines, immediate consistency, `segregation_of_duties` role model, complexity layers `[cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency, version_pinning_on_approval]`.

**§1.8 — 9 rules / 21 instances:** dual_variant_calc (2), combinatorial_formula (2), non_linear_state_machine (2), transitive_cascade (2), priority_pair_validation_conflict (3), boundary_precision_check (3), cross_entity_state_dependency (2), resource_temporal_overlap (3), compensating_invariant (2).

**§1.9 — all 9 guide sections, 70 instances (47 with full `test_recipe`, 23 `excluded_because` stubs), every claim_type row of the closed taxonomy covered:** entities 17/0, state_machines 15/5, calculations 7/4, validations 16/6, endpoints 6/0, errors 1/4, rbac 6/0, cross_cutting_complexity_layers 1/4, consistency_model 1/0.

**Verified invariants:** no instance-name collision across §1.8 ∪ §1.9; every stub cites a real `rule_id / instance_name` from the difficulty file and carries no `test_recipe`; all 54 declared error ids appear in at least one `assert` (the §1.9 `errors` instance closes the last gap, `ERR_STALE_LESSON_PLAN_VERSION`, by firing one code per HTTP family — 400/401/403/404/409/412/422 — from one fixture).

**Design adjudications made while auditing §1.5 for §1.9:**
- Tightened four endpoint descriptions so corner behaviour is pinned rather than inferred: `certify-graduates` (skip-reason order, HOURS_SHORTFALL reachability, FORMING/GRADUATED cohort → 409 so a second run is not a zero-count success), `certification-progress` (report shape, per-topic/exam ordering, `eligible_for_certification` always on ATTENDED basis), `rotations/{id}/complete` (legal from REMEDIAL, does not clear EXTENSION_REQUIRED), `lesson-plans/{id}/request-revision` (illegal from APPROVED).
- Clarified `ERR_DUPLICATE_SCREENING_TYPE` so retests re-enter the same row (no second row of a type is ever legitimate, even post-terminal).
- `version_pinning_on_approval` has no row in the guide's complexity table; mapped it to `derived_field_reconciliation` and stubbed it against the §1.8 pin instance, which already walks pin → stale-status → stale-number → control session.
- `ERR_SAME_ACTOR_ADJUDICATION` is asserted for real in `rbac` (both priority-56 branches: lesson-plan approver vs author, and adjudicator vs findings recorder) rather than stubbed in `errors`.
- House style enforced: list filters as `payload:` keys with bare paths in `call:`, never query strings.

**Orchestrator note (post-step action taken):** the scaffold generator flagged that `SCAFFOLD.yaml`'s `scenario:` key still opened with the difficulty directive line `Generate task harder than expert level!` (required verbatim as its input). The orchestrator stripped that line (and the blank line following it) from `SCAFFOLD.yaml` immediately after Step 2, and verified via `grep -rn "harder than expert" .` that the phrase now appears nowhere in the task directory, and that `SCAFFOLD.yaml` still parses under `yaml.safe_load` with an unchanged top-level key set. This prevents the directive from reaching PRD.md via the doc generator.

## Step 3: Copy shared files — 2026-09-05T00:00:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T00:00:00.000Z

PRD complete and verified.

## Output
`workspace/PRD.md` — **524 lines, ~15,100 words, 112.8 KB**, built by 8 chunked `cat >>` appends (no giant Write). File ends at the last row of the §5 error table, at a real section boundary.

## Sections written
- `# Police Recruit Academy & Field Training API — Product Requirements Document`
- **§1 Introduction** (litigation/legal burden, pipeline scope, segregation of duties + arithmetic determinism, flat top-level path topology)
- **§2 Global Specifications** — 2.1 RBAC (8 roles, opaque vs `entity_backed` identity, subject-scoped screening authority, the 4 ownership-armed operations); 2.2 API Response Structure (byte-identical canonical paste); 2.3 Pagination + every list filter; 2.4 Common record properties & the `TrainingRecordEntry` exception; 2.5 Logical clock + instant/date field inventory + expiry sweep; 2.6 Arithmetic precision (2 dp vs 4 dp, CEIL/FLOOR, per-row vs once-at-end rounding); 2.7 the 38-rung validation ladder with priorities, error ids, statuses and scopes; 2.8 both OCC rules; 2.9 cascade discipline + 3 conserved quantities; 2.10 the 12 not-found resolutions; 2.11 closed vs half-open intervals + room-turnaround rule
- **§3 Business Logic** — 3.1 standard & cohort; 3.2 intake, screening pipeline, `physical_fitness_composite`; 3.3 instructor certification, lesson-plan approval, cascade C; 3.4 sessions/attendance/hours ledger (`session_scheduled_hours`, `topic_hours_ledger`, `certified_hours_variant`, `absence_hours_accrual`, delivery + void-delivery, progress report); 3.5 examinations, remediation budget, cascade A; 3.6 rotations + DORs, both competency variants, cascade B, abort compensation; 3.7 stage advancement, `probation_schedule` forward pass, probation decisions, dismissal, certify-graduates; 3.8 immutable record + `attrition_and_pipeline_forecast`
- **§4** 57-row endpoint table (4 columns), generated programmatically from the scaffold
- **§5** 54-row error table (2 columns)

## Coverage (machine-verified)
- **57/57 endpoint paths** present in the document; **54/54 error ids** present in §5 **and** every one also referenced in §1–§3 prose
- **38/38 validations** (37 distinct error ids) enumerated as ordered rungs in §2.7
- **12/12 state machines**: every `initial_state`, `from` and `to` value across all 12 machines appears in §1–§3
- **8/8 calculations** documented with pinned evaluation order, constants and worked numbers
- **12/12 entities**; 2/2 OCC rules; 3/3 named cascades; 3/3 conserved quantities

## Hard Contract results
- **Contract 1 (identifier coverage) — PASS.** All 112 `entities[].fields[].name`, all 77 distinct `input` identifiers, all 12 path params, and all response-shape keys from every inline `output` object appear verbatim in backticks (0 misses).
- **Contract 2 (rule coverage) — PASS.** Every validation priority/error/scope, both OCC rules, all cascade chains with per-level ordering, all `applies_to` scopes, field-level structured content (`topic_requirements`, `dimension_ratings`, `raw_metrics`, both hour maps, `exam_status`, `skipped`, `stages`, `per_stage_expected`), and sibling-branch symmetry (both `FAILED_FINAL` origins, both abort origins, both `GRADUATED` origins, all dismiss/withdraw stage variants) documented.
- **Contract 3 (§3 path purity) — PASS.** 0 backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path. Paths appear only in §2 (`applies_to` precision) and §4.

Also scrubbed: no scaffold-internal leakage anywhere (`section 1.x`, `calculations.*`, `test_recipe`, `input_set`, `applies_to`, "FK reverse-reachability", or difficulty-directive text — all zero hits). Neither withheld design index was opened; no sibling task directory was read. Scratch confined to `/tmp/task_2883_prd/`.

## Zero-Silence adjudications
1. **`delivered_at` is absent from `CourseSession.fields`** but written by the deliver side-effect and cleared by void-delivery. Documented as a system-managed second-precision instant on `CourseSession` (null at creation, stamped at close-out, cleared to null on void) and added to the §2.5 instant-field list.
2. **`ERR_SESSION_NOT_DELIVERABLE` vs the transition table.** The catalogue condition implies close-out is legal from `SCHEDULED` **or** `UNDER_MIN_ENROLLMENT`; the transition table declares only `SCHEDULED → DELIVERED`. Adopted the catalogue reading (both statuses deliverable, plus the `ends_at ≤ clock` gate), because a session below its enrolment floor would otherwise never be able to credit hours actually earned.
3. **`request-revision` on an `APPROVED` plan.** The endpoint declares both a "when coming from APPROVED" side effect and that this case is `ERR_INVALID_STATE`; the machine declares only `SUBMITTED → REVISION_REQUESTED`. Ruled request-revision legal from `SUBMITTED` only; the session-cancellation behaviour is documented under cascade C, plus a derivable note that sessions pinned to a sent-back plan keep `SCHEDULED` but cannot be closed out.
4. **`ERR_INSTRUCTOR_CERT_EXPIRED` boundary.** Catalogue says "at or before the clock at the moment of the session's scheduled start"; validation 51 says `certification_expires_at` must be "strictly after the current logical clock". Used validation 51's wording as authoritative.
5. **`ERR_FITNESS_STANDARD_NOT_MET` scope.** Validation 55 scopes it to adjudicate-CLEAR; the catalogue also covers advancing past `SCREENING` and the per-event `fitness_event_floor_points`. Stated rung 55 authoritatively, then documented the broader catalogue readings as additional arming points.
6. **`ERR_PRIOR_ROTATION_MISMATCH` breadth.** The catalogue is richer than validation 72; documented all four faults (different recruit, `phase_number` not exactly one less, predecessor `status` not `COMPLETED`, null link while `phase_number > 1`).
7. **Probation `PASS` with a null `probation_milestone_score`.** The transition requires it non-null but no specific error covers that; `ERR_MILESTONE_NOT_REACHED` is date-only per its catalogue condition. Routed the null-score case to `ERR_INVALID_STATE` under that error's "trigger not declared and no more specific state error applies" clause, keeping `ERR_MILESTONE_NOT_REACHED` for the date gate alone.
8. **`attempt_number` derivation mentions "non-VOIDED examinations"** though `Examination.status` has no `VOIDED` value. Documented as one plus the count of the recruit's existing examination rows carrying the same `topic_code`.
9. **Grade-outcome boundary phrasing.** The endpoint uses `attempt_number <= max_remediation_attempts` / `>` while the machine uses `< 1 + max_remediation_attempts` / `>=`. These are identical over integers; documented with the machine's `1 + max_remediation_attempts` framing and a concrete attempt-count example.

**Orchestrator truncation check (per operating note):** verified independently — `PRD.md` is 524 lines / 113312 bytes, `tail` ends on the final `| \`ERR_MILESTONE_NOT_REACHED\` | 409 |` table row (a real section boundary, not mid-sentence); all 54 scaffold error ids and all 57 scaffold endpoint paths are present; §5 has exactly 54 `ERR_` rows and §4 has exactly 57 endpoint rows. No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T00:00:00.000Z

## Done — implementation complete and smoke-verified

**Location:** `workspace/implementation/`

### Files written (`wc -l`, 4086 lines total)

| File | Lines |
|---|---|
| `start.sh` (chmod +x, reads `$PORT`, binds 0.0.0.0, foreground `exec`) | 9 |
| `requirements.txt` | 1 |
| `app.py` (blueprint wiring, `json.sort_keys=False`, error handlers, request lock) | 78 |
| `core.py` (54 error ids + statuses, instant/date codecs, `Store` of 12 empty dicts, envelopes, auth rungs 1–4, pagination rung 22) | 393 |
| `validate.py` (rung 20/21 shape helpers, `dimension_ratings`, fitness `raw_metrics`, query parsers) | 377 |
| `calc.py` (exact `Fraction` half-up rounding, hour ledgers both bases, competency variants, fitness composite, clearance/probation derivation, attrition + forecast) | 623 |
| `serial.py` (13 serialisers; entries carry only `id`/`created_at`) | 259 |
| `ops.py` (training-record appends, enrolment re-derivation, cascades A/B/C, delivery + void) | 326 |
| `routes/common.py` | 89 |
| `routes/standards.py` / `classes.py` / `recruits.py` / `screenings.py` | 75 / 170 / 361 / 182 |
| `routes/instructors.py` / `plans.py` / `sessions.py` / `exams.py` / `rotations.py` / `records.py` | 107 / 149 / 286 / 185 / 340 / 76 |
| `routes/__init__.py` | 0 |

**Endpoints: exactly 57** (`grep -c '@bp\.(get|post)'` across route modules = 57). Storage is plain in-memory dicts; a fresh boot returns `total_count: 0` on all twelve list endpoints (verified on a clean process). No seeding, no disk persistence, `__pycache__` removed.

### Verification
Four smoke suites (~140 assertions) against `PORT=39883`/`39177`, each PID captured and killed individually — no broad pkill. All passed, covering: auth/role/ownership rungs, typed 404s and 404-before-400, duplicate identifiers, screening pipeline with SoD + fitness composite (80 at reference metrics), stage hops, session scheduling incl. the 15-minute cross-room turnaround conflict, attendance consistency, delivery/hours ledger and its conserved void reversal (cohort back to `0.00`, `HOURS_REVERSAL` of `-4.00`), cascade A (`FAILED_FINAL` → `DISMISSAL_PENDING` → provisional voids → `UNDER_MIN_ENROLLMENT`), cascade B (score 2.00 → `REMEDIAL` → `EXTENSION_REQUIRED` → 60-day extension → `2026-10-14`) and its exact abort compensation (back to 5.00/0 days/`2026-08-15`), cascade C (plan → session → attendance → cohort `AT_RISK` → rotation abort → load 0), clock monotonicity + expiry sweep, OCC 412s on both parents, probation schedule forward pass, bulk certification with terminal second run, attrition/forecast, pagination.

### PRD ambiguities resolved (reading chosen)
1. **Attendance duplicate** applies whatever the `ledger_status` (rung 66 literal) over the scaffold's "non-voided".
2. **`ERR_INSTRUCTOR_CERT_EXPIRED`** judged against the *current clock*, not the session's `starts_at`. Note the ladder makes it reachable only when `certification_expires_at` equals the clock exactly (the sweep expires *strictly* earlier rows, and rung 50 catches an `EXPIRED` instructor first) — verified as the live path.
3. **Examination `attempt_number`** = 1 + count of the recruit's existing rows on that topic (all rows, no status filter).
4. **`request-revision`** legal from `SUBMITTED` only, so the scaffold's "cancel sessions when coming from APPROVED" side effect is unreachable and omitted.
5. **Rotation overlap / rotating-trainer sets** = non-`ABORTED` = `{PLANNED, ACTIVE, REMEDIAL, COMPLETED}`; FTO load ceiling counts only `{PLANNED, ACTIVE, REMEDIAL}`.
6. **Instructor schedule-conflict live set** = `{SCHEDULED, UNDER_MIN_ENROLLMENT, DELIVERED}`.
7. **Probation `SEPARATE`** also aborts the recruit's open rotations (§3.7).
8. **`POST /_clock/set_current_utc` denies `Recruit`** — §4's 7-role table over §2.5's "any of the eight roles".
9. **Waive role-narrowing not implemented separately** (subject scope subsumes it; implementing it would make rung 54's PHYSICAL_FITNESS-waive clause unreachable). The `RETEST`-only-`TrainingCoordinator` narrowing *is* implemented as `ERR_ROLE_NOT_PERMITTED`.
10. **Screening state errors:** findings from `FINDINGS_RECORDED` and adjudicate from `ORDERED`/`RETEST_REQUIRED` → `ERR_INVALID_STATE`; the three terminal statuses → `ERR_SCREENING_ALREADY_ADJUDICATED`.
11. **Preconditions with no declared error → `ERR_INVALID_STATE` (409):** `ACADEMY→FIELD_TRAINING` academy gate, `FIELD_TRAINING→PROBATION` rotation gates, cohort not `FORMING/IN_SESSION/AT_RISK`, activate-time trainee-stage and sibling-active checks, complete-time `dor_count`/`end_date` gates, retest on a non-fitness screening.
12. **Duplicate non-`ABORTED` `phase_number`** → `ERR_INVALID_STATE`, checked *last* so declared errors (overlap, trainer, prior, load) win.
13. **Instructor `certify`**: legal from `UNCERTIFIED`/`EXPIRED` only; `certification_expires_at` at or before the clock → `ERR_INSTRUCTOR_CERT_EXPIRED`.
14. **`counted_absence_hours`** = the session's `scheduled_hours` for `ABSENT_UNEXCUSED` rows only, else `0.00`.
15. **`POST /lesson-plans` by an `AcademyInstructor`** must name itself, enforced as `ERR_NOT_RESOURCE_OWNER` after FK resolution.
16. **No `PROBATION_DECISION` entry** for cascade B or the abort compensation, and none for reaching academy `COMPLETE` (PRD silent; scaffold said otherwise).
17. **Ladder beats prose on ordering:** rung 62 (schedule conflict) before rung 70 (topic in standard) at session create; rungs 50/51 before 52 at deliver; rung 61 (DOR window) before rung 64 (author) — the last one is confirmed live behaviour.
18. **FTO certification gate applied at rotation *create* too** (§3.6 states it explicitly even though rung 57's "applies to" lists only `activate`).

## Step 5: Generate unit tests — 2026-09-05T00:00:00.000Z

Suite complete and verified. Final state:

## Files written (all at the task root, nothing under `workspace/`)

`test_helpers/` (9 files, 2,482 lines)
| file | lines |
|---|---|
| `__init__.py` | 16 |
| `types.py` | 400 |
| `api_errors.py` | 214 |
| `constants.py` | 280 |
| `test_users.py` | 154 |
| `api_client.py` | 293 |
| `assertions.py` | 220 |
| `factories.py` | 329 |
| `fixtures.py` | 576 |

`test_suite/` (conftest + 11 modules, 6,172 lines)
| file | lines | tests |
|---|---|---|
| `conftest.py` | 32 | – |
| `test_01_hour_bases_competency_and_fitness_scoring.py` | 425 | 12 |
| `test_02_screening_and_rotation_state_loops.py` | 449 | 12 |
| `test_03_cascades_and_compensations.py` | 504 | 12 |
| `test_04_rejection_precedence_and_boundaries.py` | 462 | 12 |
| `test_05_scheduling_overlap_and_capacity.py` | 268 | 6 |
| `test_06_entity_shapes_and_listings.py` | 663 | 17 |
| `test_07_state_machine_transitions.py` | 735 | 15 |
| `test_08_derived_calculations_and_reports.py` | 391 | 7 |
| `test_09_validation_rules_and_precedence.py` | 794 | 16 |
| `test_10_endpoint_behaviours.py` | 639 | 8 |
| `test_11_access_control_and_consistency.py` | 810 | 9 |

## Coverage

- **Total: 126 tests**, all collected cleanly (`pytest --collect-only` → 126 in 0.56s), every file `ast.parse`-clean and `pyflakes`-clean (the only pyflakes output left is `conftest.py`'s deliberate fixture re-export block, already marked `# noqa: F401`).
- **Queue A (§1.8 difficulty): 21/21 instances translated**, 54 tests, minimum 2 tests per instance, every `rule_id/name` pair verified against the yaml.
- **Queue B (§1.9 corner): 70/70 non-stub instances translated**, 72 tests (two `endpoints` instances got 2 tests each). The 23 `excluded_because:` stubs were not translated, as specified.
- **0 instances skipped** — every non-stub instance passed the PRD-first two-condition filter.
- Every test docstring carries exactly one `Design:` line as its last line; all 126 tags were machine-verified to name an existing instance and the correct section/rule. No test mentions the scaffold.

## Key findings (recipe defects corrected PRD-first, no PRD narrowing)

1. `rbac/exclusive_operations` asserts a new instructor's `certification_status == 'NOT_CERTIFIED'`; PRD §3.3 says `UNCERTIFIED` — asserted the PRD literal.
2. `cross_cutting/optimistic_concurrency` files its first revision from `SUBMITTED`, which PRD §3.3 makes illegal; restructured through `request-revision` so all its claims (v1→v6, two 412s from tokens retired by unguarded writes, `approved_revision_number` 3) survive.
3. `consistency_model/immediate` asserts `ERR_ATTENDANCE_ALREADY_RECORDED` on a *post-delivery* duplicate, where rungs 40/42 also answer 409; the error id is asserted on the pre-delivery duplicate (uniquely derived) and only the 409 family plus invariants post-delivery. Its progress-report field names (`credited_hours_total`) were replaced with the PRD's (`total_hours`).
4. `rbac/shared_operations` includes an FTO among identical readers, but §2.1 scopes FTO ownership through a rotation and the scenario has none; the FTO is excluded with an in-test comment, five other roles compared byte-identically.
5. `rbac/peer_roles_entity_backed` references a `${rec_id}` its own setup never creates; the test builds the trainee through the declared endpoints.

Every test builds all its own state through the API (safe under `--isolation per-test-server`); no server was started and `workspace/implementation/` was never read, written, or listed.

**Orchestrator note:** Steps 5 and 6 were launched back-to-back as background agents within seconds of each other, so the implementation generator ran to completion without `test_suite/` being readable in any meaningful form at its start; it also reported never reading, writing or listing the test directories. Verified after both exited that `test_helpers/` and `test_suite/` sit at the task root (not under `workspace/`), and that no stray copies exist under `workspace/`.

## Step 7: Run tests and iterate — 2026-09-05T00:00:00.000Z

Drove to a fully clean 8-round sweep on `task_2883_police_recruit_academy_field_training`.

## Iterations run
**2.** Iteration 1 baseline was 124/126 in all 8 rounds with the *same 2 failures deterministically in every round* (no flakiness, no load artifacts — sweeps completed in ~4 min, host was not contended). Iteration 2 was clean.

## Tests deleted
**None.** Both failures survived STEP 1a (PRD verbatim-covers) and STEP 1b (unique derivability), and both resolved at STEP 2 as test-side mis-translations of the PRD sentence the test itself quotes.

## Fixes applied to `test_helpers/`
**None.** The helper layer (`api_client.py` envelope contract, `factories.py` payload shapes/JSON numbers, `test_users.py` role-header builders, `assertions.py` instant canonicalisation) audited clean — no money-as-string, date-vs-instant, whitespace-header, or double-unwrap bugs.

## Fixes applied to `test_suite/`
1. `test_suite/test_08_derived_calculations_and_reports.py` — `test_each_session_interval_is_rounded_to_hours_on_its_own`: the assertion `contact_hours == 2.00` was hardcoded against a value the shared fixture never produces (`fixtures.SESSION_HOURS = 4.0` is `create_approved_lesson_plan`'s default, and `_patrol_curriculum` does not override it). Changed to `4.00`, which preserves the test's stated intent verbatim — PRD §3.4 lists only `scheduled_hours`, `topic_code` and `pinned_lesson_plan_revision` as derived at session creation, so the plan's authored `contact_hours` (4.00) must differ from all three block intervals (0.83 / 1.33 / 0.50). Implementation was correct.

2. `test_suite/test_10_endpoint_behaviours.py` — `test_sending_a_plan_back_is_legal_only_from_submitted`: two assertions expected `approved_revision_number == 1` to survive a `request-revision`, directly contradicting the PRD sentence the test's own docstring quotes from (§3.3): *"The director may instead send a plan back, supplying `reviewer_notes`, which moves it `SUBMITTED` → `REVISION_REQUESTED`, stores those notes, clears `approved_revision_number`, `approved_at` and `approved_by_user_id` to null, and increments `version`."* Changed both to `is None`, and strengthened the first to also assert `approved_at is None` / `approved_by_user_id is None` (the other two fields the same sentence clears) — a strictly more PRD-faithful assertion. The neighbouring checks that *do* hold were left intact: the revision-from-`APPROVED` case still asserts `approved_revision_number == 1` (§3.3 "left unchanged"), the session's `pinned_lesson_plan_revision == 1` still survives, and `version == 4` confirms the two rejected calls bumped nothing.

## Fixes applied to `implementation/`
**None.** No implementation defect was found. All 18 `.py` files under `workspace/implementation/` retain their pre-existing mtimes (14:02–14:21) — the implementation was not touched, and storage remains in-memory only.

## Final sweep evidence
`sweep.done` = `all 8 rounds exited at 2026-09-05T15:41:04+00:00`

| results file | passed/total | failed | errors | skipped |
|---|---|---|---|---|
| results.1.json | 126/126 | 0 | 0 | 0 |
| results.2.json | 126/126 | 0 | 0 | 0 |
| results.3.json | 126/126 | 0 | 0 | 0 |
| results.4.json | 126/126 | 0 | 0 | 0 |
| results.5.json | 126/126 | 0 | 0 | 0 |
| results.6.json | 126/126 | 0 | 0 | 0 |
| results.7.json | 126/126 | 0 | 0 | 0 |
| results.8.json | 126/126 | 0 | 0 | 0 |

Union of non-passing tests across all 8 rounds: **empty.**

Housekeeping: `worklog.md` untouched (mtime still 15:28 — the orchestrator owns it); no `test_suite/` or `test_helpers/` strays under `workspace/`; scratch dir `/tmp/task_2883_step7/` removed.

**Orchestrator independent verification (per operating note — a Step 7 agent has previously claimed a clean sweep with no artifacts on disk):** re-read all eight `workspace/implementation/results.$i.json` directly. Every one reports `passed=126, failed=0, errors=0, skipped=0, total=126`, all with mtime 15:41:04 matching `sweep.done`. `grep -c '^def test_'` across `test_suite/` still totals 126, confirming the zero-deletion claim. `ls -la implementation/*.py` shows mtimes of 14:02–14:09, all predating the Step 7 agent's spawn, confirming the implementation was genuinely untouched. Sweep ran via the orchestrator-provided `workspace/sweep.sh` → `setsid nohup workspace/sweep_body.sh`, so no reaping was possible; per-round logs are in `workspace/sweep.round{1..8}.log`.

**Step 8 skip-condition adjudication:** the skill skips Step 8 only when Step 7 made 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 applied 2 `test_suite/` fixes, so the skip condition is NOT met and Step 8 runs. Noting in advance that both fixes were pure test mis-translations against PRD prose that already pinned the behaviour (a hardcoded fixture value the fixture never produces; assertions contradicting the very §3.3 sentence the test quotes), and the implementation needed no change — so a byte-identical or near-identical `PRD_FINALIZED.md` is a legitimate outcome here, and Step 8 must not invent edits to look productive. Step 9's full scan remains the substantive completeness pass.

## Step 8: Finalize PRD — 2026-09-05T00:00:00.000Z

**Conclusion: no PRD edit is warranted.** `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`.

## Line counts
- `PRD.md`: 524 lines / `PRD_FINALIZED.md`: 524 lines — **0.00% delta** (identical md5 `352fe149bdd2f419208552d46c02f93f`).

## Changes
None. Both `<step_7_diff>` items were test-side mis-translations of PRD sentences that already uniquely determine the implementation's behavior.

## Per-item analysis (why each yielded no edit)

**Item 1 — `test_08 … test_each_session_interval_is_rounded_to_hours_on_its_own` (`contact_hours 2.00 → 4.00`)**
- (a) Subject: the lesson plan's authored `contact_hours`, and the set of values derived at session creation.
- (b) Impl paths enumerated: `grep -rn contact_hours` across all 18 `.py` files returns exactly 5 writes/reads — `routes/plans.py:29,42` (create, caller-supplied), `routes/plans.py:87,99` (revision, wholesale replace), `serial.py:136` (echo). Nothing in `routes/sessions.py`, `calc.py`, or `ops.py` ever writes or reads a plan's `contact_hours`. Session creation (`routes/sessions.py:132-134`) derives only `scheduled_hours` (`calc.session_scheduled_hours`, `calc.py:152-154`: `round_half_up(Fraction(seconds,3600), 2)`), `topic_code`, and `pinned_lesson_plan_revision`. `calc.py:315` (`_class_delivered_topic_hours`, feeding both `class_unmet_topic_hours` and `class_projected_topic_hours`) sums per-session `scheduled_hours`, never `contact_hours`.
- PRD §3.3 ¶ at line 267 already pins `contact_hours` as caller-authored; line 273 pins revision as its only mutation; §3.4 line 283 already enumerates exactly the three derived-at-creation values and the half-up-to-2dp rounding of `scheduled_hours`. The failure was purely that the test hardcoded `2.00` while `fixtures.SESSION_HOURS = 4.0` (fixtures.py:42, used as `create_approved_lesson_plan`'s `contact_hours` default at fixtures.py:139-141). Pure fixture-value bug; PRD is neither silent nor mismatched.
- (c) No wording adjustment — no edit made.

**Item 2 — `test_10 … test_sending_a_plan_back_is_legal_only_from_submitted` (`approved_revision_number == 1` → `is None`)**
- (a) Subject: which fields `request-revision` clears, versus the parallel paths that also leave `APPROVED`.
- (b) Impl paths enumerated: `grep -rn "approved_revision_number\|approved_at\|approved_by_user_id"` — `routes/plans.py:45-47` (create: all null), `:125-127` (approve: set from `revision_number`/clock/actor), `:145-147` (**request-revision: all three set to `None`**), `revise_plan` (`:97-101`) deliberately touches none of them, `ops.py:210` (cascade C level 2 sets only `approved_revision_number = None`, leaving `approved_at`/`approved_by_user_id` intact), `serial.py:139-141` (echo), `routes/sessions.py:64,134` (pin capture and delivery-time pin match).
- PRD §3.3 line 271 already states verbatim that request-revision "clears `approved_revision_number`, `approved_at` and `approved_by_user_id` to null" — exactly matching `routes/plans.py:145-147`. Critically, that clause is already scoped to the request-revision route only, so it does not misdescribe `ops.py:210` (cascade C, correctly described by line 260 as nulling only `approved_revision_number`) nor `revise_plan` (correctly described by line 275 as leaving all three unchanged). The three parallel paths are already distinctly and correctly pinned.
- (c) No wording adjustment — no edit made. Any edit here would have risked collapsing the three distinct clearing behaviors into one false universal claim.

No implementation defects existed (Step 7 changed zero impl files), and no test was deleted, so there is no PRD-silence or PRD-mismatch signal anywhere in the diff to patch. Per the task's own guidance, the subagent did not manufacture edits.

**Orchestrator note:** a byte-identical `PRD_FINALIZED.md` is the correct Step 8 outcome when Step 7 applied zero `implementation/` fixes and zero deletions (per the standing operating note, only Step 9 must never be byte-identical). Step 9 is therefore the substantive completeness pass here, and to avoid the known Step 9 failure mode (a single agent silently not scanning and emitting an identical file) it will be run as sequential passes partitioned by implementation module over one shared `PRD_COMPLETED.md` — pass 1 performs the `cp`, later passes must not.

## Step 9: Complete PRD — 2026-09-05T00:00:00.000Z

**Orchestrator design decision:** run as **four sequential passes partitioned by implementation module** over one shared `PRD_COMPLETED.md`, rather than a single agent. Rationale: `PRD_FINALIZED.md` came out byte-identical to `PRD.md` (Step 7 fixed no implementation code), so Step 9 was the only substantive alignment pass in this pipeline, and the known failure mode is a single agent emitting a byte-identical `PRD_COMPLETED.md` because it never really scanned 4,086 lines of implementation. Pass 1 performed the `cp`; passes 2–4 were each explicitly told the file already existed with prior edits and must NOT re-copy it. Each pass was also required to hand its deliberately-deferred findings forward, and the final pass was given the accumulated cross-pass leftovers to adjudicate so nothing fell through the cracks. Partition: pass 1 = `app.py`/`core.py`/`validate.py`/`serial.py`/`routes/common.py`; pass 2 = `calc.py`/`ops.py`; pass 3 = `routes/standards.py`/`classes.py`/`recruits.py`/`screenings.py`; pass 4 = `routes/instructors.py`/`plans.py`/`sessions.py`/`exams.py`/`rotations.py`/`records.py`.

### Pass 1 — cross-cutting infrastructure (app/core/validate/serial/routes.common)

`cp` performed. `PRD_FINALIZED.md` 524 lines / 113,312 bytes (untouched) → `PRD_COMPLETED.md` 526 lines / 120,528 chars, **char delta +7,177**. **Ambiguity-pins: 21 · Mismatch-revisions: 2.**

- §2.1 auth headers — insert — ambiguity — whitespace-only header counts as empty; both values trimmed before use (incl. ownership compare); role matched exactly/case-sensitively — `core.py:334-347`
- §2.2 `api_request_id` — insert — ambiguity — `req_` + exactly 20 mixed-case ASCII letters/digits — `core.py:287-291`
- §2.2 `api_request_timestamp` — insert — ambiguity — read from the logical clock, not wall time, so it repeats across requests — `core.py:290`
- §2.2 pagination-meta bullet — insert — ambiguity — the four keys appear on list responses only; `has_more` = `offset + len(data) < total_count` — `core.py:294-306`
- §2.2 (new bullet) — insert — ambiguity — envelope and `meta` keys emitted in declaration order, never alphabetised — `app.py:24`, `core.py:295`
- §2.2 error `message` — insert — ambiguity — wording is not contractual; only `error_id` + status are — `core.py:88-90`
- §2.2 (new bullet) — insert — ambiguity — off-surface failures: unrouted path → `ERR_INVALID_REQUEST` 404, bad method → 405, unclassified → 400; trailing slash tolerated — `app.py:61-68`, `app.py:23`
- §2.3 pagination parsing — insert — ambiguity — empty value is a rejection not an omission; signed digits only, whitespace trimmed, `10.0` rejected; `limit` before `offset`; ignored on single-resource endpoints — `core.py:364-388`
- §2.3 ordering / `total_count` — insert — ambiguity — `created_at` ties broken by insertion sequence; `total_count` is post-filter/pre-page; `offset` past end = empty page, not an error — `core.py:276-277,391-393`
- §2.3 filters — insert — ambiguity — empty filter = absent (except `state_code`, matched literally); invalid enum → `ERR_INVALID_REQUEST` at rung 20, *before* rung 22; boolean filters accept `true/false/1/0` any case; id/code filters never resolved — `validate.py:334-352`, `routes/standards.py:70`
- §2.4 `id` / `created_at` — insert — ambiguity — 36-char lowercase-hex 8-4-4-4-12; stamped from the logical clock — `core.py:241-257`
- §2.4 `version` / `updated_at` — insert — ambiguity — new row is version 1 with `updated_at == created_at`; **increment once per row per request**, not per touch; `created_at`/`updated_at`/`version` emitted last — `core.py:260-273`, `serial.py:6-11`
- §2.5 clock response — insert — ambiguity — `current_utc` echoed at second precision — `routes/records.py:76`
- §2.5 instant/date codecs — **revise — mismatch** — `findings_recorded_at` removed from the second-precision list and pinned as an RFC 1123 date-time (`Sat, 01 Aug 2026 00:00:00 GMT`), because it is emitted as a raw `datetime` through Flask's JSON provider; plus inbound tolerance (1–9 fractional digits, `Z` or `±HH:MM`, **truncated** to seconds; naive/date-only rejected) and strict `YYYY-MM-DD` with real-calendar-day check — `serial.py:102` (+`routes/screenings.py:81`), `core.py:101-145`
- §2.6 2-dp list — revise — ambiguity — added `required_hours` and `remediation_hours`, both carried at 2 dp — `validate.py:249`, `routes/exams.py:159,178`
- §2.6 numeric emission — insert — ambiguity — equality is numeric not textual (`3.50` may render `3.5`); inbound must be a JSON number, and an over-precise value is rejected at rung 20, never rounded — `core.py:178-184`, `validate.py:48-53,121-141`
- §2.7 rung 12 — insert — ambiguity — body FK resolution attempted only for a present non-empty string; absent/null/empty/other-typed falls through to rung 20 — `routes/common.py:46-54`
- §2.7 rung 20 — **revise — mismatch** — dropped "exactly the five declared keys" (extras are ignored, not refused) and pinned four conventions: explicit `null` == absent, undeclared fields ignored, missing/empty body read as `{}`, non-object JSON body is itself the failure; strict bool-vs-number typing — `validate.py:16-46,268-280`
- §3.2 screening initial state — insert — ambiguity — `raw_metrics`, `composite_score`, `waiver_justification`, both actor ids and `findings_recorded_at` all null; `disqualifier_codes` empty array — `serial.py:89-105`, `routes/recruits.py:333-346`
- §3.2 `raw_metrics` / `disqualifier_codes` — insert — ambiguity — per-event bounds (`push_ups`/`sit_ups` ≥ 0, run > 0, jump ≥ 0 at ≤2 dp), must be an object, **extra keys retained verbatim and echoed back**; codes 1–24 chars — `validate.py:228-317`, `serial.py:108-111`
- §3.3 `authorized_topic_codes` — insert — ambiguity — each an uppercase code of 1–24 characters — `validate.py:228-235`
- §3.3 `revision_notes` — insert — ambiguity — required by shape but not retained on the plan or in any representation — `serial.py:130-145`, `routes/plans.py:88`
- §3.6 `dimension_ratings` — insert — ambiguity — extra keys ignored; stored object carries exactly the five in declared order — `validate.py:259-280`, `serial.py:232`

Cross-check: every one of the 116 serialiser keys is named somewhere in the PRD, and all 54 `error_id` → HTTP status pairs in `core.py:15-77` match §5 exactly — no patch needed there.

Deferred forward: the §2.5 seven-vs-eight clock-roles mismatch (`routes/records.py`), all `calc.py` readings, report shapes/query parsing at route call sites, per-field requiredness at route call sites, per-endpoint RBAC/transitions, cascade sequencing and training-record literals (`ops.py`).

### Pass 2 — arithmetic and cascades (calc.py / ops.py)

Did **NOT** re-copy the file; all changes were in-place `Edit`s and pass 1's 23 changes remain intact. 526 lines unchanged; **120,528 → 124,724 chars (+4,196)**. **11 ambiguity-pins · 3 mismatch-revisions.**

- §3.3 cascade C level 3 — revise — **mismatch** — PRD selected sessions "referencing one of [the revoked author's plans]"; impl selects by the session's own `instructor_id` of record, whatever plan/author, in ascending `created_at`; added the corollary that another instructor's session against a revoked author's plan stays `SCHEDULED` — `ops.py:216-222`
- §3.7 probation-schedule triggers — revise — **mismatch** — PRD claimed re-derivation on "every `probation_status` transition and every rotation transition into `COMPLETED`, `REMEDIAL` or `ABORTED`"; replaced with the exact five call sites, plus the negatives (`REMEDIAL`→`ACTIVE` flip, non-restoring abort, separation via dismissal) and the `probation_start`-null no-op — `ops.py:160,186-188`, `calc.py:488-490`
- §3.8 training-record `actor_role` — revise — **mismatch** — PRD said cascade-generated entries carry `system`; impl carries the acting request's role/user everywhere (incl. `HOURS_CREDIT`), with `system` only on the auto `APPLICANT`→`SCREENING` entry — `ops.py:24-25,35-38,268`
- §3.4 delivery consequences — insert — ambiguity — `HOURS_CREDIT` entries also carry `subject_entity` `CourseSession`, the session id and `detail` `hours credited from delivered session`, appended in the rows' ascending `created_at` order — `ops.py:257,268-277`
- §3.4 delivery consequences — insert — ambiguity — post-delivery standing re-evaluation: absence ceiling first (only from `IN_PROGRESS`/`REMEDIATION`, short-circuiting), else `IN_PROGRESS`→`COMPLETE`; `REMEDIATION` never completes on a delivery — `ops.py:94-106,284-285`
- §3.4 crediting hours — insert — ambiguity — row-level `counted_absence_hours` = session's whole `scheduled_hours` for `ABSENT_UNEXCUSED`, `0.00` otherwise — `calc.py:167-170`, `ops.py:262`
- §3.4 crediting hours — insert — ambiguity — `per_topic_credited_hours` key set: one entry per `topic_requirements` entry in declared order, `0.00` when no qualifying row — `calc.py:186-201`
- §3.4 void-delivery — insert — ambiguity — `HOURS_REVERSAL` entries carry `subject_entity`/`subject_entity_id`/`detail` `hours reversed by voided delivery`, in ascending row order — `ops.py:308-317`
- §3.4 void-delivery — insert — ambiguity — `COMPLETE`→`IN_PROGRESS` is the only `academy_status` move; `DISMISSAL_PENDING` is not walked back — `ops.py:109-112`
- §3.4 progress report `exam_status` — revise — ambiguity — value is the **most recently created** exam row's status for the topic, and every exam verdict reads it that way — `calc.py:247-248`
- §3.3 cascade C level 2 — insert — ambiguity — `approved_at` and `approved_by_user_id` are left as they stand (unlike request-revision, which clears all three) — `ops.py:209-212`
- §3.3 cascade C rotations — insert — ambiguity — cascade-C aborts also void the rotation's non-voided reports — `ops.py:135-138,243`
- §3.6 abort — insert — ambiguity — the officer's row is touched only on an abort from `ACTIVE`/`REMEDIAL`, never from `PLANNED` — `ops.py:131,139-141`
- §3.8 survival — insert — ambiguity — each factor uses the already-rounded 4-dp stage rate; the running product is exact/unrounded until the final rounding — `calc.py:565-574`
- §3.8 attrition report — insert — ambiguity — `rolling_mean_scores` is keyed in the covered rotations' ascending `created_at` order — `calc.py:576-583`
- §3.8 forecast — insert — ambiguity — when `required_applicants` is null, every `per_stage_expected` value is null — `calc.py:602-604`

Deferred forward: training-record entry literals for `DOR_FILED`/`EXAM_RESULT`/`STAGE_ENTRY`/`ADVERSE_EXIT`/`PROBATION_DECISION`/`SCREENING_ADJUDICATION`/`CERTIFICATION_ISSUED`; `void_reason`/`abort_reason` literals on non-delivery paths; `target_sworn_officers`/`basis` query parsing and report role tuples; grading/remediation machine, rung-42/81 gates, activation/completion preconditions.

Pass-2 note on a pass-1 sentence (not undone): §2.4's "increment is once per row per request" is correct for `touch`, but §2.9's blanket "every row a cascade touches has its own `version` incremented" is slightly over-broad given `abort_rotation` skips the instructor row when the rotation was `PLANNED`; the exception was pinned locally in §3.6 instead of editing §2.9.

### Pass 3 — standard / cohort / recruit / screening routes

Did **not** `cp` or overwrite; every change an in-place targeted `Edit`. Before 526 lines / 124,724 chars → after **526 lines / 133,010 chars (+8,286)**; 27 headings unchanged, so no new sections and no new paragraphs. **18 ambiguity-pins · 7 mismatch-revisions (25 edits).**

- §2.1 (ownership gate) — insert — ambiguity — rung 4 on the two recruit reads compares the *unresolved* path id, so a `Recruit` naming a nonexistent recruit gets `ERR_NOT_RESOURCE_OWNER`, not the 404 — `routes/recruits.py:52-55,99,292`
- §2.1 (subject-scoped screening authority) — revise — mismatch — subject scope is **not** at rung 3; it is decided after rung 10 and before rung 20 — `routes/screenings.py:28-32,64-65,106-107`
- §2.1 (same sentence) — revise — mismatch — deleted the claim that only a `BackgroundInvestigator`/`MedicalExaminer` "may adjudicate a waiver"; there is no role gate on `WAIVE`, and the retest role narrowing is decided *after* body shape — `routes/screenings.py:113-114,127-131`
- §2.7 rung 3 — revise — mismatch — removed "including the subject-scoped screening authority"; points at the later decision points instead — `routes/screenings.py:65,107`
- §2.3 (filters) — revise — mismatch — `certification_standard_id` on cohorts joins `state_code` as a filter matched literally when supplied empty (raw `request.args.get`, not `query_str`) — `routes/classes.py:63`
- §3.2 (intake) — insert — ambiguity — a new recruit carries `probation_base_days` 365 and `probation_extension_days` 0 from intake, other probation fields null — `routes/recruits.py:85-90`
- §3.2 (first screening) — insert — ambiguity — auto `STAGE_ENTRY` literals: `subject_entity` `ScreeningRecord` naming the *screening* row, `detail`, `actor_user_id` `system` — `routes/recruits.py:352-359`
- §3.2 (findings) — insert — ambiguity — `raw_metrics` and `disqualifier_codes` both required; findings from `FINDINGS_RECORDED` → `ERR_INVALID_STATE`; the recruit row is not touched — `routes/screenings.py:67-74,99`
- §3.2 (adjudication legality) — insert — ambiguity — from `ORDERED`/`RETEST_REQUIRED` the answer is `ERR_INVALID_STATE`, not the already-adjudicated 409 — `routes/screenings.py:116-119`
- §3.2 (clear bullet) — insert — ambiguity — `SCREENING_ADJUDICATION` entry literals (`subject_entity` `ScreeningRecord`, screening `id`, `detail` `screening adjudicated <DECISION>`) — `routes/screenings.py:173-180`
- §3.2 (waive bullet) — revise — mismatch — "open only to a BI or ME" replaced by the actual mechanism; plus `waiver_justification` is optional/≤2000 chars, whitespace-only counts as missing, fitness refusal precedes the missing-justification refusal, and no disqualifier codes are required — `routes/screenings.py:111,127-131`
- §3.2 (retest bullet) — insert — ambiguity — `ERR_ROLE_NOT_PERMITTED` after body shape; wrong type / null-or-passing composite → `ERR_INVALID_STATE`, both decided *after* rungs 54/55/56; `adjudicated_by_user_id` and the recruit's `version` still move — `routes/screenings.py:113-114,146-154,171`
- §3.4 (certification-progress) — insert — ambiguity — `basis` empty ⇒ `ATTENDED`, any other value ⇒ `ERR_INVALID_REQUEST`, case-sensitive — `routes/recruits.py:294`
- §3.7 (advance one hop) — insert — ambiguity — `to_stage` must be one of the eight stages (else rung 20 400); only a well-formed non-successor reaches `ERR_STAGE_TRANSITION_NOT_ALLOWED` — `routes/recruits.py:150,160-162`
- §3.7 (`SCREENING`→`ACADEMY`) — revise — mismatch — cohort posture is tested **first** (rung 40, `ERR_INVALID_STATE`) *before* clearance; and the `DISQUALIFIED` diagnosis order is pinned (any record's non-empty `disqualifier_codes` whatever its status → fitness composite → fallback `ERR_CLEARANCE_INCOMPLETE`) — `routes/recruits.py:129-142,164-175`
- §3.7 (stage entry) — insert — ambiguity — `STAGE_ENTRY` `subject_entity` `Recruit` / `detail` literals — `routes/recruits.py:193-200`
- §3.7 (probation hop data) — insert — ambiguity — `probation_start` required, `probation_base_days` optional integer ≥ 0, both read at rung 20 ahead of rung 39 and the successor test — `routes/recruits.py:151-155`
- §3.7 (probation decisions) — insert — ambiguity — `justification` 1–2000 chars, retained nowhere — `routes/recruits.py:247`
- §3.7 (`PASS`) — revise — mismatch — the null-milestone-score `ERR_INVALID_STATE` is tested **before** the milestone-date `ERR_MILESTONE_NOT_REACHED` (PRD had them the other way round) — `routes/recruits.py:257-261`
- §3.7 (`SEPARATE`) — insert — ambiguity — `abort_reason` literal `probation separation`, reports voided — `routes/recruits.py:274`
- §3.7 (decision entry) — insert — ambiguity — `PROBATION_DECISION`/`ADVERSE_EXIT` `subject_entity` `Recruit` and `detail` `probation decision <DECISION>` — `routes/recruits.py:278-285`
- §3.7 (dismissal) — insert — ambiguity — `justification` 1–2000 chars — `routes/recruits.py:210`
- §3.7 (dismissal legality) — insert — ambiguity — an exit from `APPLICANT` answers `ERR_INVALID_STATE` 409 — `routes/recruits.py:214-215`
- §3.7 (exit cascades) — insert — ambiguity — `void_reason`/`abort_reason` both the literal `recruit exited pipeline`; `CREDITED` rows survive; the `PROBATION` branch runs only the rotation aborts, never the attendance void — `routes/recruits.py:221-228`
- §3.7 (exit entry) — insert — ambiguity — `ADVERSE_EXIT` `subject_entity` `Recruit` / `detail` `pipeline exit recorded with reason <CODE>` — `routes/recruits.py:230-237`
- §3.7 (certify graduates) — insert — ambiguity — `CERTIFICATION_ISSUED` literals, `hours_delta` `0.00`, actor is the director not `system` — `routes/classes.py:110-117`
- §3.7 (skipped/certified ordering) — insert — ambiguity — `certified_recruit_ids` shares the `skipped` array's ascending `created_at` order (single walk) — `routes/classes.py:103-118`
- §3.7 (zero-certified run) — insert — ambiguity — only `status` is unchanged; the cohort row is touched on **every** run, so `updated_at`/`version` advance even at `certified_count` 0 — `routes/classes.py:120-122`
- §3.8 (pipeline forecast) — insert — ambiguity — `target_sworn_officers` is a required integer ≥ 0, trimmed, `25.0` rejected, decided after the path 404 — `routes/classes.py:162`

No change needed: `standards.py` was already fully pinned (all three role tuples, every field bound, the literal empty-`state_code` filter); `classes.py`'s cohort create/read/list and `attrition-analysis` response shape and role tuple likewise matched, as did every §4 role tuple across all four files.

Deferred forward to pass 4: `abort_rotation`'s `void_reports`/instructor-touch semantics and `restore_probation_after_abort`; rotation status transitions; `exam_status` tie-breaking and `remediation_attempts_used`; attendance `void_reason` literals on delivery/cancel paths; training-record read/list endpoints and `stage_code`/`kind` filter enums. Also flagged the rung-55 `fitness_event_floor_points` sentence for adjudication.

### Pass 4 — remaining routes (instructors/plans/sessions/exams/rotations/records) + cross-pass leftovers

Did **NOT** `cp` or overwrite; all 27 changes were targeted in-place `Edit`s. `PRD.md` and `PRD_FINALIZED.md` never opened for write; `worklog.md` never touched; no forbidden SCAFFOLD file or sibling task dir read; no server started. Before 526 lines / 133,010 chars → after **526 lines / 139,960 chars (+6,950, 0 lines)**. Cumulative across four passes: **95 changes**. **18 ambiguity-pins · 9 mismatch-revisions.**

- §2.5 — revise — mismatch — "any of the eight roles" → the seven roles §4 lists, `Recruit` excluded, refused `ERR_ROLE_NOT_PERMITTED` at rung 3 — `routes/records.py:24-26`
- §2.7 rung 55 — revise — mismatch — sub-floor fitness event raises no error of its own; reaches the identifier only via the 59 cap failing the pass-score comparison — `calc.py:453-455`
- §2.7 rung 57 — revise — mismatch — applies-list extended to include `POST /field-training-rotations` (credential tested at planning *and* activation) — `routes/rotations.py:85,189`
- §2.7 rung 60 — revise — mismatch — "any other live rotation" → any non-aborted sibling, `COMPLETED` included; `ABORTED` never counts — `routes/rotations.py:88-93`
- §2.7 rung 62 — insert — ambiguity — "live" pinned to `SCHEDULED`/`UNDER_MIN_ENROLLMENT`/`DELIVERED`; `CANCELLED`/`VOIDED` neither overlap nor impose turnaround — `routes/sessions.py:74`
- §2.7 rung 12 — insert — ambiguity — body-FK resolution order for both multi-FK creates — `routes/sessions.py:102-104`, `routes/rotations.py:64-66`
- §2.7 rung 20 — insert — ambiguity — the six free-text fields bounded 1–2000 chars — `instructors.py:100`, `plans.py:88,137`, `sessions.py:279`, `rotations.py:210,240`
- §2.1 — insert — mismatch — only two of the `Recruit` narrowings are enforced; cross-recruit reads of exams/rotations/reports are answered, not refused — `exams.py:73`, `rotations.py:152,319`
- §2.1 — insert — ambiguity — the other two ownership gates compare *after* path resolution; plus the fifth, later-decided comparison on `POST /lesson-plans` — `plans.py:83-84,33-35`, `rotations.py:256-257`
- §3.3 — insert — ambiguity — certify's `ERR_INSTRUCTOR_CERT_EXPIRED` decided after the status test — `instructors.py:80-85`
- §3.3 — revise — ambiguity — cascade C level 3 `void_reason` literal `session cancelled` + hour resets — `ops.py:226-228`
- §3.3 — insert — ambiguity — create-plan ownership → `ERR_NOT_RESOURCE_OWNER` after rungs 12/20; `TrainingCoordinator` exempt — `plans.py:33-35`
- §3.4 — revise — mismatch — "five things" → "six", and rung 62 before rung 70 — `sessions.py:120-121`
- §3.4 — insert — mismatch — session creation re-derives the cohort projection in both directions (`IN_SESSION` → `AT_RISK` too) — `sessions.py:140`, `ops.py:84-87`
- §3.4 — insert — mismatch — close-out's three later gates run 50 → 51 → 52, not in the narrated order — `sessions.py:264-268`
- §3.4 — insert — ambiguity — attendance route tests no session status at all — `sessions.py:189-208`
- §3.4 — insert — ambiguity — absence-accrual void uses the literal `academy dismissal pending` — `ops.py:103`
- §3.4 — insert — ambiguity — voided attendance rows carry the supplied reason as their own `void_reason` — `ops.py:303`
- §3.4 — insert — ambiguity — `exam_status` tie-break on equal `created_at` is insertion order — `calc.py:242-248`
- §3.5 — insert — ambiguity — `EXAM_RESULT` entry's `subject_entity`/`subject_entity_id`/`detail` literals, appended before cascade A — `exams.py:128-136`
- §3.5 — revise — ambiguity — cascade A level 3 `void_reason` literal + hour resets — `ops.py:171`
- §3.5 — insert — ambiguity — `remediation_hours` required, ≥ 0, 2dp, no upper bound — `exams.py:159`
- §3.6 — insert — ambiguity — `prior_rotation_id` alongside `phase_number` 1 is always `ERR_PRIOR_ROTATION_MISMATCH` — `rotations.py:111-116`
- §3.6 — insert — ambiguity — phase-uniqueness answers `ERR_INVALID_STATE` and is decided **last**, after rung 80 — `rotations.py:128-131`
- §3.6 — insert — ambiguity — activation: only the credential has its own id; stage/sibling/status all `ERR_INVALID_STATE`, status first, `ERR_ROTATION_NOT_ACTIVE` never — `rotations.py:184-197`
- §3.6 — revise — ambiguity — `DOR_FILED` entry's full literal set, appended before cascade B — `rotations.py:303-310`
- §3.6 — revise — mismatch — `dor_count` tested first; wrong status answers `ERR_ROTATION_NOT_ACTIVE` ahead of both — `rotations.py:212-219`
- §3.6 — insert — ambiguity — abort from `COMPLETED`/`ABORTED` is `ERR_INVALID_STATE`; probation restoration armed on this endpoint alone — `rotations.py:242-249`, `ops.py:145-160`

**Rung-55 verdict: genuine mismatch, fixed.** `fitness_event_floor_points` is consumed at exactly one place in the whole implementation, `calc.fitness_composite` (`calc.py:453-455`), where a smallest event below the floor merely `return min(raw_total, 59)` — no `fail()`. Both raisers of `ERR_FITNESS_STANDARD_NOT_MET` (`screenings.py:138` on a `CLEAR` adjudication, `recruits.py:141` on advance-stage) compare the composite against `fitness_pass_score` and nothing else. Elsewhere the key is only echoed (`serial.py:35`) or set (`standards.py:38`). The rung-55 sentence now says the sub-floor case raises no error of its own and reaches the identifier only indirectly through the capped composite failing the pass-score comparison.

**Pass-4 residual notes (not silently rewritten):**
- §3.5 still says grading "re-derives the recruit's `remediation_attempts_used`". That is vacuous — only `assign-remediation` moves `attempt_number` — but the recruit's `version` genuinely does advance on grading (`exams.py:137`), so the sentence is harmless rather than wrong.
- §3.1's list of `IN_SESSION` → `AT_RISK` triggers omits session creation; §3.1 was another pass's authority, so the behaviour was pinned at §3.4 instead.
- No §4 table edits were needed: every `require_roles` tuple in the six modules matches its §4 row exactly (verified endpoint by endpoint), and `grep -c` over `routes/` confirms 57 endpoints, matching §4's stated count.
- §2.3 already pins the `kind`/`stage_code` entry filters and their rung-20 enum rejection, so `records.py`'s list route needed no change.
- No remaining PRD silence or mismatch found against `instructors.py`, `plans.py`, `sessions.py`, `exams.py`, `rotations.py` or `records.py`.

### Step 9 totals and orchestrator verification

Source (`PRD_FINALIZED.md`) 524 lines / 113,312 chars → `PRD_COMPLETED.md` **526 lines / 139,960 chars**, char-delta **+26,648 (+23.5%)**. Aggregate **95 changes: 68 ambiguity-pins, 21 mismatch-revisions** (per-pass: 21/2, 11/3, 18/7, 18/9). Verified independently by the orchestrator: `md5sum` differs from both `PRD.md` and `PRD_FINALIZED.md` (`415c03630bc11a3d0eebe5a815403d4a` vs `352fe149bdd2f419208552d46c02f93f`), so the byte-identical Step 9 failure mode did not occur; `diff` reports 140 changed lines; heading count is still 27, confirming no new sections were added; the file still ends on the final `| \`ERR_MILESTONE_NOT_REACHED\` | 409 |` row of the §5 table (no truncation). `find` confirms no `.py` file under `implementation/`, `test_suite/` or `test_helpers/` was modified after the green sweep at 15:41, so the 8/8-round × 126/126 result recorded in Step 7 still describes the artifacts as they now stand.

Pipeline complete.
