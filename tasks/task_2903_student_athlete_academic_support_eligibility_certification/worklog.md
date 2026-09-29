# Worklog — task_2903_student_athlete_academic_support_eligibility_certification

## Step 1: Create task directory — 2026-09-05T13:58:30.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2903_student_athlete_academic_support_eligibility_certification` and its `workspace/` subdirectory. Index 2903 was pre-assigned by the orchestrating prompt; no scan of `tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T15:36:03.000Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and the lint is clean.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2903_student_athlete_academic_support_eligibility_certification/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2903_student_athlete_academic_support_eligibility_certification/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2903_student_athlete_academic_support_eligibility_certification/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     14
  §1.8 instances scanned:     20
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  780

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2903_student_athlete_academic_support_eligibility_certification/`):
- `SCAFFOLD.yaml` — 168 KB, §1.0–§1.7 only (verified: no `scaffold_*_design` key)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 117 KB, single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 200 KB, single top-level key `scaffold_corner_design`

**SCAFFOLD.yaml content:** `api_prefix: /athletics`; archetype compliance_audit / ledger_reconciliation, difficulty expert_plus, topology graph, state shape cyclic, role_model segregation_of_duties, consistency immediate; layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, ops_run_checkpoint. 14 entities, 11 state machines / 71 transitions, 1 concurrency rule (`certification-create-stale-student`, `expected_student_athlete_version`, ERR_STALE_STUDENT_VERSION 412), 9 calculations (2 dual-variant: degree audit CATALOG_AT_ENTRY/CATALOG_AT_CERTIFICATION, risk TERM_SNAPSHOT/CUMULATIVE), 37 ordered validations across 15 priority bands, 54 endpoints, 51 errors, 10 roles (8 opaque + entity_backed Tutor and StudentAthlete).

**§1.8:** 9 rule_ids × ≥2 instances = 20 total — dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 3.

**§1.9:** all 9 guide sections, 85 instances — entities 10, state_machines 14, calculations 12, validations 11, endpoints 5, errors 21, rbac 6, cross-cutting complexity layers 5, consistency model 1. 60 carry full `test_recipe`s; 25 are `excluded_because` stubs, and every cited difficulty instance resolves by name. All 105 instance names are unique across the two design files, and all 51 error codes are triggerable.

**Flag for the orchestrator:** `SCAFFOLD.yaml`'s `scenario:` value still contains the literal line `Generate task harder than expert level!` (it was supplied verbatim). Strip that one line after Step 2 so the difficulty directive never reaches PRD.md.

Orchestrator action taken: stripped the `Generate task harder than expert level!` line from `SCAFFOLD.yaml`'s `scenario:` block. Re-grepped the whole task dir for "harder than expert" — 0 hits. All three YAML files re-verified as parseable.

## Step 3: Copy shared files — 2026-09-05T15:36:10.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T15:52:52.000Z

Subagent summary (verbatim):

PRD generation for task 2903 is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2903_student_athlete_academic_support_eligibility_certification/workspace/PRD.md` — 451 lines, 14,299 words, built via 13 chunked heredoc appends (no truncation).

**Section list**
- `# Athletics Academic Eligibility API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Operators, Roles and Access Control / 2.2 API Response Structure / 2.3 Pagination and List Ordering / 2.4 Common Resource Properties and the Logical Clock / 2.5 Precision and Rounding Discipline / 2.6 Path Resolution and Referential Existence / 2.7 The Validation Ladder / 2.8 Optimistic Concurrency on Certification Creation / 2.9 The Term as Reporting Boundary / 2.10 Conservation Invariants / 2.11 Cascades, Ordering and Version Semantics
- `## 3. Business Logic & Workflows` — 3.1 Building the Academic Catalogue / 3.2 Students, Enrollments and Graded Outcomes / 3.3 The Degree-Applicability Credit Audit / 3.4 Progress Benchmarks and the Certification Lifecycle / 3.5 Appeals, Waivers and Restoration / 3.6 Academic Risk, the Study-Hall Obligation and the Support Dimension / 3.7 Tutors, Assignments and Session Logging / 3.8 Competition Travel and Missed-Class Accounting / 3.9 Impermissible Assistance, Tutor Discipline and the Term Close
- `## 4. Endpoint Definitions` (4-column table, 54 rows)
- `## 5. Error Code Catalogue` (2-column table, 51 rows) — file ends here, no audit footer

**Hard Contract results**
- **Field-Name Coverage check: PASS.** 143 candidate names extracted from scaffold entity fields, endpoint `input` lists (query params and request-body fields, `?` stripped) and `{path_param}` occurrences; 134 appear verbatim inside backticks in PRD.md. The 9 unmatched tokens are exactly the nine `calculations[].name` values (`degree_applicable_credit_audit`, `progress_benchmark_evaluation`, `academic_risk_score`, `support_requirement_hours`, `missed_class_units`, `apr_points_award`, `transfer_credit_acceptance`, `tutor_compliance_penalty`, `academic_standing_rollup`) — internal calculation labels, not fields/params, and deliberately expressed as prose rather than named tokens.
- **Rule Coverage check: PASS.** All 51 `ERR_*` ids appear in the sections 1-3 prose (not only in the section 5 table); all state-machine `states` and all transition `action` names appear; all 91 field-level defaults are stated with their literal values at the point of creation; every calculation constant appears as a literal value (verified 0.10, 1.80, 0.40/0.25/0.20/0.15, 2.30, 1000, 0.5, 10.0, 4.0, 2.0, 60, 40.00/20.00/60.00, cap 6, 2 grace terms, etc.); the single OCC rule (`expected_student_athlete_version` -> `ERR_STALE_STUDENT_VERSION`, 412) is in 2.8; all 15 validation bands with their `applies_to` scopes are in 2.7; cascades and version semantics in 2.11 plus each section 3 workflow.
- **Path Purity check: PASS.** 935 backticked spans in section 3; zero start with `/`, zero are a bare HTTP method, zero combine method+path. The literal string `/athletics` does not occur anywhere in section 3, and no bare GET/POST/PUT/PATCH/DELETE token occurs in section 3 at all.

**Additional fidelity checks**
- 2.2 is byte-identical to `section-2.2-response-structure.md`.
- Section 4 table cross-checked programmatically against the scaffold: 54/54 endpoints (29 GET, 25 POST) present, zero missing, zero extra, and every row's role list matches the scaffold's `roles` array exactly in content and order. Section 4's status-code paragraph (201 create / 200 everything else) matches the scaffold's 14 `code: 201` endpoints.
- Section 5 table cross-checked: 51/51 error ids with zero status-code mismatches, zero missing, zero extra (includes `ERR_RELIEF_EXCEEDS_REQUEST` 422, which has no `validations[]` entry and is carried in 3.5 as the GRANT precondition).
- Neither withheld design file was opened; no sibling task directory was read. Scratch work confined to `/tmp/task_2903_prd/`.

**Exact last 5 lines**
```
| `ERR_APPEAL_ROUNDS_EXHAUSTED` | 409 |
| `ERR_MISSED_CLASS_ALLOWANCE_EXCEEDED` | 422 |
| `ERR_TUTOR_WEEKLY_HOURS_EXCEEDED` | 422 |
| `ERR_TIER_HOURS_CAP_EXCEEDED` | 422 |
| `ERR_RELIEF_EXCEEDS_REQUEST` | 422 |
```

**Scaffold ambiguities resolved (load-bearing for test generation)**
- `cumulative_gpa`: 2 decimal places ROUND_HALF_UP (calculation precision wins over the entity field's "3 decimals"), 0.00 on empty input; inputs are COMPLETED enrollments with `credit_source` of `RESIDENT` and a grade in A-F.
- `is_full_time_countable`: true only on a COMPLETED resident enrollment whose term met `full_time_credit_minimum`.
- `failure_reasons` order: `PROGRESS_BELOW_BENCHMARK` before `GPA_BELOW_MINIMUM`.
- `audit_variant` resolution written as an explicit 4-step precedence ladder (TRANSFER -> forced `CATALOG_AT_CERTIFICATION`; INITIAL -> `CATALOG_AT_ENTRY`; explicit request honoured; else derived from `major_declared_term_index` vs `entry_term_index`).
- Precondition failures lacking a dedicated error id (SUBMIT under `SUPPORT_WITHHELD`; CONTINUING submit past the major-declaration deadline) surface as `ERR_INVALID_STATE_TRANSITION`; a session whose `start_at` falls in no term is `ERR_SESSION_OUTSIDE_TERM`.

Orchestrator verification: `wc -l` = 451; `tail -30` confirms the file ends with a complete final table row (`| ERR_RELIEF_EXCEEDS_REQUEST | 422 |`) inside section 5, i.e. a real section boundary and not a mid-sentence truncation. Grep for "harder than expert" and "SCAFFOLD" in PRD.md: 0 hits. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T16:35:04.000Z

Subagent summary (verbatim):

All test infrastructure and test cases are complete and verified at the task root.

## Files written

`test_helpers/` (2,789 lines): `constants.py` 319, `types.py` 48, `api_errors.py` 136, `test_users.py` 159, `api_client.py` 377, `assertions.py` 308, `factories.py` 439, `fixtures.py` 923, `__init__.py` 80.

`test_suite/` (5,439 lines): `conftest.py` 27, `test_01_registry_and_entities.py` 389, `test_02_validations.py` 527, `test_03_state_machines.py` 406, `test_04_calculations.py` 463, `test_05_endpoint_reads.py` 302, `test_06_error_guards.py` 853, `test_07_access_control.py` 340, `test_08_cross_cutting_layers.py` 314, `test_09_variant_and_formula.py` 397, `test_10_state_and_cascade.py` 428, `test_11_priority_and_boundary.py` 315, `test_12_cross_entity_and_overlap.py` 376, `test_13_conservation.py` 302.

**103 test functions, 112 collected cases** (`pytest --collect-only`: 112 collected, 0 errors — three tests in `test_06` are parametrized).

## Per-queue coverage

- **Queue A (1.8 difficulty): 20/20 instances translated, every one with >=2 tests.** Files 09-13 carry queue A: variant/formula divergence (8), non-linear state machines + transitive cascades (10), priority pairs + boundary precision (8), cross-entity state dependency + resource temporal overlap (8), compensating invariants (6).
- **Queue B (1.9 corner): 59/60 non-stub instances translated, >=1 test each.** The 25 `excluded_because:` stubs were not translated, as required.

## Skipped instances

- `Corner/calculations/transfer_credit_waterfall_fills_core_before_elective` — **non-unique-derivability**. Its trigger is `RECORD_GRADE` on a `TRANSFER` enrollment, but PRD 3.2 creates transfer rows directly in `COMPLETED` and calls `COMPLETED` terminal for all four outcome actions, and the PRD never states `earned_credit_hours` for an ungraded transfer row. No placeholder, no weakened assertion.

No other instance was skipped; no `skip`/`skipif`/`xfail` appears anywhere.

## Individual asserts dropped (instance still translated, `distinguishing_aspect` still asserted)

The recurring one: `risk_score` / `risk_tier` / `required_study_hall_hours` asserts were dropped wherever the student holds **no** `COMPLETED` enrollment, because the `TERM_SNAPSHOT` grade component is defined over "the student's highest-ordinal term that holds at least one `COMPLETED` enrollment" and the PRD gives no empty-set convention for it (affects `safety_beats_referential_on_tutor_assignment_create`, three `errors/*assignment*` instances, `meeting_starting_exactly_at_return_at_not_counted`, `incident_severity_points_applied_without_decay`, and the cancellation-conservation instance). Also dropped: `eligibility_state == NOT_CERTIFIED` after a deny (3.4 declares only `CERTIFIED -> INELIGIBLE`); `degree_applicable_credits == 0.00` as a fresh-record default (unstated); `instructor_user_id == instr_soc_1` on a fresh request (PRD 3.8 says it is null until notification — the yaml assert contradicted the PRD). One recipe/PRD contradiction was repaired rather than dropped: `ptd_progress_exactly_at_benchmark_passes` now certifies against a third term so both completed full-time terms sit strictly below the certification term's ordinal.

## Verification performed

Automated pass over all 13 files: exactly one `Design:` line per test and it is the docstring's last line; every tag's section and instance name exists verbatim in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` (no orphans); every PRD quote confirmed as a whitespace-normalised verbatim substring of `workspace/PRD.md` (one bad band-8 paraphrase in `test_12` was replaced with the verbatim PRD 2.9 sentence); no `skip`/`xfail`; `py_compile` + import check on every module; pyflakes clean in `test_suite/` (`conftest.py`'s `api_errors` import is intentional — it registers the error->HTTP-status map). `test_helpers/` and `test_suite/` exist only at the task root; `workspace/` top level holds only `INSTRUCTION.md`, `PRD.md`, `implementation`, `sweep.sh`. `worklog.md` untouched, `workspace/implementation/` never read, no server started, no `pkill`, scratch confined to `/tmp/task_2903_tests/`, `__pycache__`/`.pyc` cleaned.

Orchestrator verification: `test_helpers/` and `test_suite/` confirmed present at the task root with the 9 + 15 files listed above; `find workspace/ -name test_helpers -o -name test_suite` returned nothing, so no stray copies were written under `workspace/`.

## Step 6: Generate implementation — 2026-09-05T16:36:57.000Z

Subagent summary (verbatim):

The implementation is complete, verified, and the smoke server is shut down (killed by captured PID only; no broad pkill was ever used).

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2903_student_athlete_academic_support_eligibility_certification/workspace/implementation/`

| file | lines |
|---|---|
| `start.sh` | 8 |
| `requirements.txt` | 1 (`flask==3.0.3`) |
| `app.py` | 61 |
| `envelope.py` | 73 |
| `errors.py` | 114 |
| `store.py` | 152 |
| `helpers.py` | 168 |
| `routes_catalog.py` | 247 |
| `validation.py` | 263 |
| `routes_compliance.py` | 268 |
| `derive.py` | 289 |
| `routes_travel.py` | 303 |
| `routes_students.py` | 314 |
| `routes_support.py` | 418 |
| `routes_cert.py` | 424 |
| `calc.py` | 587 |
| **total** | **3690** |

`python3 -m py_compile *.py` clean, `pyflakes` exit 0, `__pycache__` removed. `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, `exec`s in the foreground, skips pip when Flask is already importable (measured cold boot to first 200: under 1 s). State is plain module-level dicts; nothing is seeded, no file/SQLite/JSON persistence.

## Coverage

**54 endpoints — an exact set-equality match with the PRD's endpoint table** (programmatic diff of method+normalised path: `prd only: []`, `impl only: []`), plus no extras beyond the PRD-declared `POST /athletics/_clock/set_current_utc`.

State machines: term APR status; enrollment outcomes (`RECORD_GRADE`/`MARK_INCOMPLETE`/`DROP`/`WITHDRAW` with the `PROPOSED|ACTIVE -> TERMINATED/ENROLLMENT_DROPPED` tutoring cascade); certification (incl. supersession, `DENIED|REVOKED -> RESTORED`); appeal (3-round revision cycle, three terminal states, grant cascade); tutor (training/expiry/suspension/reinstatement/termination); tutor assignment (`ACTIVE <-> SUSPENDED` cycle, both terminal exits, capacity release only from `ACTIVE`); competition event; missed-class request (dispute/re-notify cycle, cancel and event-driven void release); compliance incident; student `eligibility_state` and `support_status` as two independent dimensions.

Calculations: dual-variant credit audit (`CATALOG_AT_ENTRY|CATALOG_AT_CERTIFICATION`) with elective ceilings, per-rule caps and remedial handling; cumulative GPA; completed full-time terms; progress benchmark; dual-variant risk score/tier (`TERM_SNAPSHOT|CUMULATIVE`); the four-step study-hall derivation (gross-based ceiling selection); missed-class units with per-occurrence rounding then summation and the event multiplier; tutor capacity and tier ceilings; session `hours_credited`, overlap and the 20-minute buffer; APR points ledger with `PROJECTED|OBSERVED` retention and `squad_apr`; tutor penalty decay. Conservation invariants (missed-class allowance = charged + remaining, APR possible - earned = forfeited, `assigned_weekly_hours` = sum of ACTIVE hours) hold by recomputation, and the 2.11 recomputation chain order is centralised in `derive.py`.

## Verification

Two probe suites against freshly booted servers on high random ports: `smoke2.py` **44/44 PASS** and `smoke3.py` (deep branch coverage: full cert/appeal path, tutor+assignment lifecycle, event depart/complete/cancel-void, dispute/re-notify exhaustion/cancel release, incident substantiate/unsubstantiate/remediate, all 14 list endpoints, filters, pagination errors, RBAC/ownership 403s, two-term APR close) **ALL CHECKS PASSED**. Spot-checked numeric fidelity from raw JSON: `cumulative_gpa: 0.00`, `progress_pct: 0.0000`, `missed_units: 1.0`, `missed_class_unit_multiplier: 1.0`, `required_study_hall_hours: 8.0`, `squad_apr: 500`, instants as `2026-09-10T12:00:00.000Z`.

The five residual `smoke3` failures reported before this session's fixes were all probe-expectation errors, each confirmed against a PRD sentence and then corrected in the probe (not the server): SoD compares the decider to the cert's `requested_by_user_id` (the creating CertificationOfficer); `GRANT` is legal only from `COMMITTEE_REVIEW`, so a re-submitted appeal needs a second `OPEN_REVIEW`; assignment `ACTIVATE` requires the enrollment to still be `ENROLLED`; and the probe's event window sat behind its own logical clock.

## PRD ambiguities resolved

- **Session logging vs. lapsed training:** 3.7's two verbatim sentences win over band 11's narrower scoping — sessions are refused for `UNTRAINED` (`ERR_TUTOR_NOT_TRAINED`) and for `EXPIRED`/`SUSPENDED`/`TERMINATED` or a term past `training_valid_through_term_index` (`ERR_TUTOR_TRAINING_EXPIRED`). Session logging is *not* one of band 8's six frozen operations, so no term-freeze check fires there.
- **Re-notification bound:** rejected when `dispute_count >= 2` (the PRD's "would carry `dispute_count` past two"); lead time is not re-checked on re-notification, since the PRD lists only two requirements for that edge.
- **Undeclared error codes -> `ERR_INVALID_STATE_TRANSITION` (409):** request `CANCEL` with a parent event outside `{SCHEDULED, TRAVEL_APPROVED}`, event `DEPART`/`COMPLETE` clock preconditions, and assignment `ACTIVATE` with a non-`ENROLLED` enrollment.
- **Uniqueness without a declared code -> `ERR_INVALID_REQUEST` (400)** (band 5): term `code`/`term_index`, program `code`, course `subject_code`+`course_number`. The PRD names dedicated 409s only for enrollment and applicability-rule duplicates.
- **Event roster rule:** any existing request on the event whose enrollment belongs to a different student -> `ERR_ENROLLMENT_NOT_NOTIFIABLE`, across all request statuses ("already on the event's roster").
- **APR close ordering:** `apr_status` is set to `CLOSED` *before* the tutor penalty recomputation, so the just-closed term counts as the newest closed reporting term and the decay actually bites — a deliberate departure from the sentence's literal ordering, chosen as the only effect-bearing reading.
- **Tutor `COMPLETE_TRAINING`** writes ordinals from the supplied `term_id` (PRD) rather than the term containing the clock; validity = ordinal + 2.
- **Tier cap** is enforced on activation and reinstatement as well as creation, per "guard activation and reinstatement equally."
- **Assignment `ACTIVATE` on an already-`ACTIVE` row and every repeat action** report `ERR_INVALID_STATE_TRANSITION`, per band 9's "every repeat of an already-applied action."

## Step 7: Run tests and iterate — 2026-09-05T16:52:47.000Z

Subagent summary (verbatim):

Done — clean 8-round sweep.

## Summary

**Iterations run:** 2 (sweep 1 -> single deterministic failure; sweep 2 -> all green).

**Tests deleted:** none. The suite still holds 112 tests.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2903_student_athlete_academic_support_eligibility_certification/test_suite/test_11_priority_and_boundary.py` — `test_dropped_only_student_is_absent_from_the_apr_cohort`: removed the trailing `assert student["support_status"] == SUPPORT_NORMAL` (and its now-unused `SUPPORT_NORMAL` import) under STEP 1c partial-coverage handling. The three APR-counter assertions, which the cited PRD 3.9 sentence verbatim covers ("excluded from both the numerator and the denominator — not counted as a forfeit, simply absent"), were kept and pass.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Key diagnostic finding.** The lone failure (`SUPPORT_MANDATED` vs `SUPPORT_NORMAL`, deterministic in all 8 rounds) was *not* produced by the APR close at all. I reproduced it against a standalone server: the student is correctly excluded from the cohort (`apr_points_possible/earned/forfeited` all 0, term `squad_apr` null), and `support_status` was already `SUPPORT_MANDATED` **before** the close — it came from the `DROP` outcome cascade. With the only enrollment dropped, no term holds a `COMPLETED` enrollment, so the `TERM_SNAPSHOT` grade component has an empty input set; the implementation applies the PRD's empty-set convention (0.00 GPA) -> grade component 100.00 -> `risk_score` 40.00 -> `TIER_3` -> `SUPPORT_MANDATED`.

PRD is silent on that degenerate branch, and two faithful readings exist: (a) 2.5/3.2's "an empty input set yields 0.00" carries into the risk grade component, giving `TIER_3`/`SUPPORT_MANDATED`; or (b) 3.2's `DROP`/`WITHDRAW` clause names only "the study-hall requirement re-runs and `support_status` is re-derived" — not the risk score — leaving `risk_tier` at `TIER_1`/`SUPPORT_NORMAL`. Since both are articulable from the PRD prose, the assertion failed unique derivability while the counter assertions did not, so only the uncovered assertion was removed. No implementation check was weakened.

**Final sweep (all 8 rounds):** 112/112 passed, 0 failed, 0 errors, 0 skipped in every round. Results left in place at `$T/workspace/implementation/results.{1..8}.json`. `worklog.md` untouched.

Orchestrator verification (independent, not taken on the subagent's word): all 8 `results.$i.json` files exist under `workspace/implementation/`; each parses to `passed=112, failed=0, errors=0, skipped=0, total=112`; `sweep.log` contains exactly 1 `SWEEP_COMPLETE` marker. Step 8 is NOT skipped, because Step 7 applied 1 `test_suite/` fix (a non-zero diff), which marks a PRD site where the document did not uniquely determine the implementation's behavior.

## Step 8: Finalize PRD — 2026-09-05T16:56:12.000Z

Step 8 was NOT skipped: Step 7 applied one `test_suite/` fix, so the diff was non-zero.

Subagent summary (verbatim):

`PRD_FINALIZED.md` is complete (ends at the last row of the section 5 error table, `ERR_RELIEF_EXCEEDS_REQUEST | 422`).

## Line counts
- `PRD.md`: 451 lines; `PRD_FINALIZED.md`: 451 lines — **0.00% delta** (both edits are inline sentence insertions into existing paragraph lines; 2 lines modified).

## Changes
- **3.2 (Students, Enrollments and Graded Outcomes)** — insert — appended to the "Two aggregates are rebuilt ... on every outcome" paragraph: every one of the four outcome actions runs the 2.11 recomputation chain for the student, refreshing `cumulative_gpa`, `completed_full_time_terms`, `transfer_credits_accepted`, `degree_applicable_credits`, `progress_pct`, `risk_score`, `risk_tier`, `required_study_hall_hours` and `support_status`; a `DROP`/`WITHDRAW` may therefore move the risk tier and support dimension with no tutor assignment involved — `implementation/routes_students.py:289` (unconditional `derive.recompute_student`), `implementation/derive.py:69-96` (`persist_picture` field list + trailing `derive_support_status`).
- **3.6 (Academic Risk...)** — insert — appended to the `TERM_SNAPSHOT` sentence: an empty input set (no term holds a `COMPLETED` enrollment, or the selected term contributes no graded row) yields a term-snapshot average of 0.00 rather than null, and the grade component scores from that 0.00 — `implementation/calc.py:404-405` and `implementation/calc.py:417-418`.

## Per-edit pre-edit search log

**Edit 1**
- (a) Subject: what recomputation an enrollment-outcome action triggers, and which student fields it rewrites.
- (b) Enumerated/read: `routes_students.py:238-315` (all four branches of `record_outcome`; `derive.recompute_student` is called unconditionally at :289, the DROP re-zero at :291, `_terminate_assignments_of_enrollment` + `recompute_support_only` only for DROP/WITHDRAW at :293-295); `derive.py:14-66` (`compute_picture` — audit, transfer, benchmark, risk, tier, study-hall), `derive.py:69-96` (`persist_picture` exact written-field list, then `derive_support_status`), `derive.py:99-134` (`recompute_support_only`, `recompute_risk_and_support`); grepped every callsite of the five chain entry points across `routes_*.py` to confirm no outcome path bypasses the chain.
- (c) Adjustment: first draft named "the progress-benchmark evaluation" outputs among the refreshed values. `persist_picture` does **not** store `required_progress_pct`, `benchmark_result` or `failure_reasons` on the student row (they are computed but only frozen onto certifications), so those three names were dropped and only the nine fields the impl actually persists are listed, referring to the benchmark step indirectly via "the recomputation chain of 2.11 ... in the order that section states". The "risk tier may move" clause was scoped as a *may*, not a universal, since it depends on the recomputed inputs. The sentence was deliberately NOT attached to 3.2's DROP/WITHDRAW sentence: doing so would have implied by contrast that `RECORD_GRADE`/`MARK_INCOMPLETE` skip the chain, which the impl contradicts. The existing DROP/WITHDRAW study-hall sentence was left verbatim (it is a true subset — that step does run again after the assignment cascade).

**Edit 2**
- (a) Subject: the grade basis fed to the risk score's first component under `TERM_SNAPSHOT`, in the degenerate case of an empty input set.
- (b) Enumerated/read: `calc.term_snapshot_gpa` (`calc.py:395-419`) — two distinct zero-returns, `best_index is None` (:404) and `denominator <= 0` (:417); `calc.risk_score` (`calc.py:443-481`) confirming a 0.00 basis yields exactly the 100.00 grade component; `calc.resolve_risk_variant` (:347) for when the branch is reachable (explicit or defaulted `TERM_SNAPSHOT` with `completed_full_time_terms < 2`); both callsites (`derive.py:38` in `compute_picture`, `derive.py:126` in `recompute_risk_and_support`) plus the explicit-variant summary path (`routes_students.py:133-143`); grepped the whole impl to confirm no other term-scoped GPA computation exists.
- (c) Adjustment: first draft covered only "no term holds a `COMPLETED` enrollment"; the second zero-return (`denominator <= 0`, reachable when the selected highest-ordinal term's `COMPLETED` rows carry no grade in `A`-`F`, e.g. transfer rows) would then have been mis-described, so the clause was widened to "or the selected term contributes no graded row". Restating the resident/graded filters of the selection itself was avoided — the impl's term selection admits `COMPLETED` rows of any `credit_source` while the average admits only graded rows, which the original PRD sentence leaves loose; narrowing it here would have been a new mismatch off the Step 7 site. Finally the wording says "under the same empty-input convention as 2.5" rather than claiming the term-snapshot average is a stored field (it is only a basis, never persisted).

Orchestrator verification: `cmp` reports PRD.md and PRD_FINALIZED.md DIFFER; `diff` confirms exactly 2 changed lines (199 and 260) matching the two reported inline insertions; both files are 451 lines; PRD_FINALIZED.md ends at the final section 5 table row, so it is not truncated.

## Step 9: Complete PRD — 2026-09-05T17:34:31.000Z

Orchestrator note on method: Step 9 was run as THREE SEQUENTIAL module-partitioned passes over one shared `PRD_COMPLETED.md`, not as a single subagent. A single pass reliably under-scans a 3,690-line implementation, and the known failure mode is a byte-identical PRD_COMPLETED.md. Pass 1 performed the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden from copying and edited the file in place.

Partition:
- Pass 1 — app.py, envelope.py, errors.py, store.py, helpers.py, validation.py, routes_catalog.py, routes_students.py
- Pass 2 — routes_cert.py, routes_support.py
- Pass 3 — routes_travel.py, routes_compliance.py, calc.py, derive.py

### Pass 1 of 3 summary (verbatim)

**cp performed:** yes — `PRD_COMPLETED.md` was created from `PRD_FINALIZED.md` as my first action; `PRD.md` and `PRD_FINALIZED.md` are untouched.

**Sizes:** source 451 lines / 107,991 chars -> output 451 lines / 114,543 chars (+6,552 chars). 23 lines edited, no lines added or removed, file still ends at `| ERR_RELIEF_EXCEEDS_REQUEST | 422 |`.

**Counts:** 17 ambiguity-pins, 5 mismatch-revisions (22 edits).

**Changes**
- 2.1 — revise — mismatch — an `X-User-ID`/`X-User-Role` header of only whitespace is `ERR_UNAUTHENTICATED`, not merely an empty one — validation.py:35
- 2.2 — revise — ambiguity — `api_request_id` is `req_` plus twenty upper-case-alnum characters — envelope.py:17
- 2.2 — revise — mismatch — `api_request_timestamp` is the one instant read from the host's real clock, not the logical clock of 2.4 — envelope.py:36-38
- 2.3 — revise — ambiguity — `limit`/`offset` that are not integers at all are `ERR_INVALID_REQUEST` — validation.py:202-217
- 2.3 — insert — ambiguity — ties on every declared sort key fall back to creation order; string sort keys compare as strings, so course `1000` precedes `190` — store.py:152, helpers.py:113
- 2.3 — insert — ambiguity — filter-value typing (booleans accept `true/false/1/0` any case, numerics compare numerically, empty/`null` matches null fields), an uninterpretable filter yields an empty page rather than an error, undeclared query parameters are ignored — validation.py:221-257
- 2.4 — revise — ambiguity — `created_at` and `updated_at` are written from the logical clock — store.py:79,126,144
- 2.5 — insert — ambiguity — fixed-scale fields render as unquoted JSON numbers with trailing zeros (`12.00`, never `12` or `"12.00"`) — envelope.py:20-33
- 2.5 — revise — ambiguity — 2-decimal storage also covers `credit_hours`, `earned_credit_hours`, `total_required_credits`, `max_elective_credits_countable`, `max_countable_credits`, `min_progress_gpa`, `missed_class_units_allowance` — routes_catalog.py:128-131,181; routes_students.py:66,222
- 2.5 — revise — mismatch — `required_progress_pct` is not a field of the student row — routes_students.py:68-93, derive.py:69-89
- 2.6 — insert — ambiguity — full type ladder: string fields never accept empty/whitespace, booleans must be JSON booleans, integers accept `3.0`, decimals accept numeric strings, booleans never count as numbers, ISO-8601 instant parsing (Z/offset/naive/date-only), empty or non-object payload malformed, `Content-Type` not inspected — validation.py:45-194
- 2.6 — revise — mismatch — companion fields are *rejected* when supplied with another action, not merely "otherwise not required" — validation.py:179-182
- 3.1 — insert — ambiguity — duplicate term `code`/`term_index` is `ERR_INVALID_REQUEST` (400) and is checked before the window-ordering 422 — routes_catalog.py:62-68
- 3.1 — insert — ambiguity — term `start_date`/`end_date` echo back normalised to three-fractional-digit UTC — routes_catalog.py:75
- 3.1 — insert — ambiguity — duplicate program `code` is `ERR_INVALID_REQUEST` — routes_catalog.py:120
- 3.1 — revise — ambiguity — `course_number` is a string (and sorts/filters as one); duplicate `(subject_code, course_number)` is `ERR_INVALID_REQUEST`; `instructor_user_id` is required and non-empty — routes_catalog.py:156,161,170
- 3.1 — revise — mismatch — rule publication also re-runs transfer acceptance and re-derives `support_status`, walks students in `created_at` order, and advances neither their `version` nor `updated_at` — routes_catalog.py:242-246
- 3.2 — insert — ambiguity — full zero-initialisation of a fresh student row, and the row carries no `required_progress_pct`/`benchmark_result`/`failure_reasons` — routes_students.py:68-93
- 3.2 — revise — mismatch — major declaration re-derives `eligibility_state` wholesale from the governing certification, and leaves it alone when no non-superseded certification exists — routes_students.py:121, derive.py:200
- 3.2 — insert — ambiguity — a `TRANSFER` enrollment is born `COMPLETED` with `earned_credit_hours` equal to `credit_hours`; `credit_source=TRANSFER` is not cross-checked against `transfer_status`; the non-terminal set for the duplicate guard is `ENROLLED`/`INCOMPLETE` — routes_students.py:206-232
- 3.2 — insert — mismatch — all four outcome actions stamp `outcome_recorded_at`, not just `RECORD_GRADE` — routes_students.py:286
- 3.6 — revise — ambiguity — summary variant keys are `audit_variant`/`risk_variant`, a bad variant is `ERR_INVALID_REQUEST`, and the default-variant persistence also writes per-enrollment contributions and re-derives `support_status` while advancing neither `version` nor `updated_at` — routes_students.py:133-167
- 5 — insert — ambiguity — `ERR_INVALID_REQUEST` is also served with HTTP 404 (unrouted path), 405 (bad method) and 500 (caught fault), inside the normal error envelope — app.py:40-56

**Left for later passes:** `derive.persist_picture` sibling-enrollment rewrites without version/updated_at advance (pass 3); `_clock/set_current_utc` (pass 3); `weekly_hours` scale and the alias-based `subject_code` tutor filter (pass 2).

### Pass 2 of 3 summary (verbatim)

- I did **not** re-copy the file. `PRD_COMPLETED.md` was opened as it stood and edited in place with 24 targeted `Edit` calls across 21 paragraphs.
- Pass 1's edits are intact: 2.6 still carries the type-ladder prose, 2.5 the decimal-rendering sentence, 2.3 the tiebreak/string-ordering prose. `diff PRD_FINALIZED.md PRD_COMPLETED.md` now shows 43 changed paragraphs = pass 1's 22 + my 21.
- File ends at `| ERR_RELIEF_EXCEEDS_REQUEST | 422 |`; structure intact (451 lines, 20 `###` headings, 23 numbered bold items, 109 table rows).

**Size:** 451 lines / 114,543 chars -> 451 lines / 124,689 chars.

**Counts:** 13 ambiguity-pins, 11 mismatch-revisions (24 edits total).

**Changes**
- 2.3 — insert — ambiguity — the tutors `subject_code` filter is an array-membership test on `subject_codes`, exact/case-sensitive/never numeric, and an empty value matches nothing — validation.py:253-254, routes_support.py:44-45
- 2.5 — insert — ambiguity — `weekly_hours`, `max_weekly_hours`, `assigned_weekly_hours` stored at 2 dp — routes_support.py:62,189, derive.py:250
- 2.7 band 10 — revise — mismatch — `ERR_APPEAL_NOT_ELIGIBLE` guards creation plus `SUBMIT`/`GRANT`/`DENY`/`REQUEST_REVISION` only; `OPEN_REVIEW` and `WITHDRAW` exempt — routes_cert.py:338-340
- 2.7 band 11 — revise — mismatch — the two tutor-training codes also fire on session logging (incl. term-of-record expiry), they precede `ERR_IMPERMISSIBLE_ASSISTANCE_BLOCK`, and the SoD list gains revision-request — routes_support.py:356-369, routes_cert.py:387-388
- 2.8 — insert — ambiguity — `expected_student_athlete_version` is an integer with minimum 0; out-of-range is 400 from the shape band, below the 412 — routes_cert.py:111
- 3.3 — revise — ambiguity — `INITIAL` forces `CATALOG_AT_ENTRY` unconditionally; a supplied `audit_variant` on `INITIAL`/`TRANSFER` is enum-validated then ignored — routes_cert.py:143-150
- 3.4 — revise — mismatch — winning-relief tie-break is *later* `created_at` then later insertion; only `GRANTED` appeals are candidates; certification `degree_applicable_credits_counted` = audit + relief — routes_cert.py:43-54,66-69
- 3.4 — revise — mismatch — deleted the non-existent converse `ERR_TRANSFER_CREDIT_SOURCE_INVALID` rule for `INITIAL`/`CONTINUING`; pinned the same-band order MAJOR_NOT_DECLARED -> TRANSFER_CREDIT_SOURCE_INVALID -> CERTIFICATION_TYPE_TERM_MISMATCH -> TRANSFER_RESIDENCY_NOT_MET — routes_cert.py:120-140
- 3.4 — revise — mismatch — supersession sweeps `DRAFT` rows only; the create also persists the picture onto the student row under the certification's resolved variant, re-derives `support_status`, does not touch `eligibility_state`, and bumps student `version` once — routes_cert.py:172-183
- 3.4 — revise — mismatch — submission is *not* the last snapshot refresh; adds `credit_relief_applied` to the rewritten list; the student row is untouched on submit; the endpoint authorises both roles for all four actions — routes_cert.py:188,217-220
- 3.4 — insert — ambiguity — certifying a `FAIL` reports `ERR_INVALID_STATE_TRANSITION`, ahead of the SoD check — routes_cert.py:225-228
- 3.4 — insert — ambiguity — revoke writes no `decided_*` and is exempt from SoD — routes_cert.py:240-243
- 3.5 — insert — ambiguity/mismatch — the predecessor need not belong to the same certification, and it is resolved *after* the filing's scalar shape checks — routes_cert.py:282-291
- 3.5 — insert — ambiguity — `SUBMIT` from `DRAFT` overwrites a predecessor-derived `round_number` with 1; term-open applies to `OPEN_REVIEW`/`WITHDRAW` too; both roles authorised for all six actions — routes_cert.py:324,334,343-346
- 3.5 — revise — mismatch — `credit_relief_applied` is a selection, not a running total; the whole certification snapshot and its `version` refresh on every grant; `ERR_RELIEF_EXCEEDS_REQUEST` is checked after state legality and SoD — routes_cert.py:397-412,423
- 3.5 — revise — mismatch — restoration runs the *full* chain on the student under default variants with no relief folded in; a non-flipping grant leaves the certification's status alone and touches no student field — routes_cert.py:411-424, derive.py:92-96
- 3.7 — revise — ambiguity — `COMPLETE_TRAINING` accepts only `UNTRAINED`/`EXPIRED`, the named term need not be open, session expiry reports `ERR_TUTOR_TRAINING_EXPIRED`; both endpoint roles cover all four actions — routes_support.py:76,90-97,361-364
- 3.7 — insert — ambiguity — a blocked reinstatement is `ERR_INVALID_STATE_TRANSITION`, and reinstatement takes no `term_id` and leaves both training ordinals untouched — routes_support.py:107-116
- 3.7 — revise — mismatch — `terminated_reason` is required on `TERMINATE`, accepts any of the five reasons and is stored verbatim; an explicit `COMPLETE` takes no reason and leaves it null — routes_support.py:207-212,263-271
- 3.7 — insert — mismatch — all five assignment transitions rewrite tutor capacity and re-derive the student's study-hall/support (never the risk score) and bump assignment, tutor and student `version` even when values are unchanged — routes_support.py:228-278
- 3.7 — insert — ambiguity — a `Tutor`'s `X-User-ID` must equal the `Tutor` row's `id`; the check runs after both FKs resolve (404 beats 403) and never applies to `STUDY_HALL`; logging recomputes nothing else — routes_support.py:320-327,415-418
- 3.7 — revise — mismatch — `end_at` exactly at the term's `end_date` is accepted; a `start_at` in no term gives the same error; overlap spans both session types; the buffer applies across students and to true overlaps; `STUDY_HALL` is never buffer-bound — routes_support.py:374-396
- 3.9 — revise — mismatch — removed the claim that a suspended tutor "completes training again"; reinstatement changes neither `penalty_points` nor the ordinals and `COMPLETE_TRAINING` is illegal from `SUSPENDED` — routes_support.py:90-92,114-116

**Left for pass 3:** `derive.persist_picture` sibling-enrollment rewrites; the penalty-decay window keying off the discovered session's `term_index_of_record`; `_clock`, compliance incidents, the APR close cascade, travel/missed-class, all calc.py formula internals.

### Pass 3 of 3 summary (verbatim)

**Integrity**
- No re-copy: never ran `cp PRD_FINALIZED.md PRD_COMPLETED.md`. Opened the existing file (already carrying passes 1+2) and edited in place with ~26 targeted `Edit` calls. No `Write` call against it; no section added or removed.
- Prior passes intact: pass 1's 2.6 type-ladder prose and pass 2's 3.7 buffer revision both present. Diff against `PRD_FINALIZED.md` shows 65 changed lines, of which 43 are passes 1+2 and 22 are mine.
- Structure: 451 lines before, 451 after. `tail -1` is still the final error-table row.
- Size: 124689 chars -> 135086 chars (+10397).
- Nothing else written. No server booted, no `pkill`, no scratch files. `SCAFFOLD*.yaml` and `worklog.md` never read.

**Counts:** 22 paragraphs touched — **14 ambiguity-pins**, **8 mismatch-revisions**.

**Changes**
- 2.4 — insert — ambiguity — clock capability accepts any instant including one earlier than the present reading, and answers 200 with a `data` object whose single key is `current_utc`, not a stored row — routes_compliance.py:262-268
- 2.7 band 8 — revise — mismatch — "six operations" corrected to **seven**, adding `APPROVE_TRAVEL`; plus the ordering exception (freeze evaluated after the `SCHEDULED` precondition) and the negative universal that no other event action and no request action consults the governing term — routes_travel.py:120-133
- 2.7 band 10 — insert — ambiguity — `ERR_EVENT_NOT_TRAVEL_APPROVED` also answers `NOTIFY_INSTRUCTOR` (first and re-notification), after the request's own status precondition — routes_travel.py:228-262
- 2.11 — insert — ambiguity — partial chain entry pinned: a single-input move enters at the risk-score or study-hall step; the risk-score entry recomputes audit+benchmark internally under default variants but persists only risk/tier/hours/support, leaving the five audit fields untouched — derive.py:206-238
- 3.3 — insert — ambiguity — audit catalog year falls back to `entry_catalog_year` when the student holds no enrollment — calc.py:118-134
- 3.3 — insert — ambiguity — the remedial cap ignores `applicability`, and the elective walk order plus headroom spelled out — calc.py:196-244
- 3.3 — insert — ambiguity — deferred item (a): per-enrollment `degree_applicable_credits_counted`/`is_full_time_countable` rewrites are silent — no `version`, no `updated_at`, "notwithstanding the general cascade rule of 2.11" — derive.py:96-118
- 3.4 — insert — ambiguity — governing-certification tie-break: highest `term_index`, then later `created_at`, then later-inserted — derive.py:135-149
- 3.4 — revise — mismatch — the open-term requirement binds only the operator's own `REVOKE` (checked ahead of the state precondition); the 3.9 substantiation cascade revokes regardless of term status — routes_cert.py:270-309 vs routes_compliance.py:96-102
- 3.6 — insert — ambiguity — travel component when the allowance is 0.00: 100.00 if anything is charged, else 0.00 — calc.py:318-341
- 3.6 — revise — mismatch — none of the four support moves is available while any top-severity incident (including `REMEDIATED`) sits on the record; the only exit is remediation out of `SUPPORT_WITHHELD` — derive.py:151-186
- 3.8 — insert — ambiguity — the travel window is never tested against the term's dates; the multiplier is stored at one decimal place — routes_travel.py:60-95, calc.py:96-104
- 3.8 — revise — mismatch — meeting containment accepts the term's closing instant, and a weekday repeated in `meeting_days` yields one occurrence per date — calc.py:432-470
- 3.8 — insert — ambiguity — DEPART/COMPLETE before the clock reaches the bound give `ERR_INVALID_STATE_TRANSITION`, and DEPART/COMPLETE/CANCEL consult no term — routes_travel.py:120-176
- 3.8 — insert — ambiguity — event `version` advances on each charge and exactly once per cancellation/release even at 0.00 units — routes_travel.py:150-176
- 3.8 — insert — ambiguity — the roster is every request ever filed (`CANCELLED`/`VOIDED` included) and the roster test precedes the notifiability test — routes_travel.py:186-214
- 3.8 — insert — ambiguity — the enrollment's own `term_id` and status are never examined — routes_travel.py:186-214
- 3.8 — revise — mismatch — "only that instructor may respond" localised: the endpoint authorises `AcademicAdvisor` and `Instructor` for all four actions and the ownership check fires only for role `Instructor` on ACK/DISPUTE — routes_travel.py:228-303
- 3.8 — insert — ambiguity — lead time binds only the first notification out of `DRAFT`; `instructor_response_note` is optional on ACK/DISPUTE, written as-is, and malformed with NOTIFY_INSTRUCTOR/CANCEL — routes_travel.py:236-290
- 3.8 — revise — mismatch — re-notification carries no lead-time rule, checks the event first, and is refused when `dispute_count` already stands at 2; request CANCEL requires the event `SCHEDULED`/`TRAVEL_APPROVED` — routes_travel.py:262-303
- 3.9 — insert — ambiguity — incident `tutor_id`/`discovered_session_id` are honoured only as strings; other JSON types are silently ignored and stored null (a narrow, explicitly scoped exception to 2.6) — routes_compliance.py:48-71
- 3.9 — insert — ambiguity — LEVEL_III revocation is not gated on the certification's term; remediation mechanics; UNSUBSTANTIATE writes only the incident; a student both reporting and holding an assignment with the suspended tutor advances `version` twice — routes_compliance.py:74-149
- 3.9 — revise — mismatch — deferred item (c): decay paragraph rewritten — computed and written only at the APR close; the incident's term is the *discovered session's* `term_index_of_record` (no session => never decays); the reduction is a single point however many terms elapsed; `penalty_points` is the undecayed running total between closes; the suspension threshold is read at substantiation off that undecayed figure — calc.py:560-586, routes_compliance.py:252-256
- 3.9 — revise — mismatch — the close's support re-derivation is the pure 3.6 function, so a zero-point student escalates to `SUPPORT_PROBATION` (not `SUPPORT_MANDATED`) and no `required_study_hall_hours` is rewritten — routes_compliance.py:246-248, derive.py:151-186
- 3.9 — revise — mismatch — close finish order: expire lapsed training -> `OPEN -> CLOSED` -> penalty recompute for every tutor, with the closing term already counting as the newest closed reporting term; next term is the lowest `term_index` above, whatever its `is_apr_reporting_term` — routes_compliance.py:162-169, 250-257

**Four deferred items — all handled** (a) sibling-enrollment silent rewrites pinned in 3.3 and carved out of 2.11; (b) `_clock/set_current_utc` pinned in 2.4; (c) penalty-decay window fully rewritten in 3.9; (d) APR close cascade, compliance incidents, travel/missed-class and all calc.py internals covered across 2.7, 2.11, 3.3, 3.4, 3.6, 3.8, 3.9.

**Residual judgement:** partition believed free of PRD silence or mismatch on anything observable through the API. Two deliberately under-determined spots named: the `_clock` capability's role list described as unrestricted-among-authenticated-roles rather than enumerated; and `refresh_missed_class_ledger`/`refresh_tutor_capacity` described through their conservation invariants rather than as literal recompute-from-scratch passes (accurate for every reachable state). Both left loose under the no-new-mismatch rule.

### Orchestrator verification of Step 9

- `PRD_COMPLETED.md` exists, is 451 lines / 135,086 chars, and is NOT byte-identical to `PRD_FINALIZED.md` (the known Step 9 no-op failure mode) — `cmp` reports DIFFERS.
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` shows 65 changed paragraphs, exactly the cumulative 22 (pass 1) + 21 (pass 2) + 22 (pass 3), confirming no pass clobbered an earlier pass's work.
- Both prior-pass canary strings still present after pass 3: the pass-1 type-ladder phrase ("whole-valued number such as") and the pass-2 buffer phrase ("20 minutes of clear time"), 1 occurrence each.
- File ends at the final section 5 error-table row — not truncated. 27 `##`-level headings, no new sections added by any pass.
- Grep for "harder than expert", "SCAFFOLD" and "scaffold_" in PRD_COMPLETED.md: 0 hits, so the difficulty directive and the withheld design indices never leaked into the deliverable.
- Total growth PRD.md (107,162 chars) -> PRD_COMPLETED.md (135,086 chars) = +27,924 chars at constant 451 lines, i.e. all inline paragraph edits with no structural change.

Pipeline complete: Step 9 has written `workspace/PRD_COMPLETED.md`.
