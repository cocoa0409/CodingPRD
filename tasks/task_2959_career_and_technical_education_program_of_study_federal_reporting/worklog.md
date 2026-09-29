# Worklog — task_2959_career_and_technical_education_program_of_study_federal_reporting

## Step 1: Create task directory — 2026-09-05T22:09:33.122Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2959_career_and_technical_education_program_of_study_federal_reporting` and its `workspace/` subdirectory. Index 2959 was pre-assigned by the invoking pipeline (no auto-allocation scan performed, per instructions, because up to 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-05T23:50:41.382030569Z

Step 2 scaffold generation for task_2959 is complete.

## Files written (all in `tasks/task_2959_career_and_technical_education_program_of_study_federal_reporting/`)

| File | Lines | Top-level keys |
|---|---|---|
| `SCAFFOLD.yaml` | 2818 | `scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles` — no `scaffold_difficulty_design` / `scaffold_corner_design` key |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 3440 | single key `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6487 | single key `scaffold_corner_design` |

## Scaffold contents (§1.0–§1.7)
`domain_name: cte-program-of-study-federal-reporting`, `api_prefix: /cte`. 13 entities · 7 state machines (cyclic, incl. a 4-round negotiation loop and a 3-round plan revision loop) · 2 concurrency rules (OCC on `ProgramOfStudy.version` and `GrantAward.version`) · 6 calculations · 39 ordered validations · 61 endpoints (28 GET, 32 writes, 1 clock) · 65 errors · 5 roles (`CteDirector`, `StateComplianceReviewer`, `GrantFiscalOfficer`, `CommitteeChair` (entity-backed on `CommitteeMember`), `SchoolRegistrar`). Profile: `compliance_audit` / `multi_party_negotiation`, layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`; topology flat, role model segregation_of_duties, consistency immediate; clock pinned to `2026-08-01T00:00:00Z`.

## §1.8 — 24 instances, all nine difficulty rules >=2
dual_variant_calc 2 · combinatorial_formula 2 · non_linear_state_machine 2 · transitive_cascade 3 · priority_pair_validation_conflict 3 · boundary_precision_check 4 · cross_entity_state_dependency 4 · resource_temporal_overlap 2 · compensating_invariant 2.

## §1.9 — 71 instances across all nine taxonomy sections
entities 13 · state_machines 15 · calculations 12 · validations 11 · endpoints 6 · errors 6 · rbac 3 · cross_cutting_complexity_layers 4 · consistency_model 1. Of these, 50 carry full `test_recipe`s and 21 are `excluded_because` stubs pointing at the §1.8 instance that already covers the corner (every stub reference resolves to a real §1.8 instance name).

## Lint
```
Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     13
  §1.8 instances scanned:     24
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  1589

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Two lint rounds were needed: 14 rule-(d) violations from pagination captures written as `$.data.total_count` / `$.data.has_more` on array endpoints (rewritten to `$.meta.*`), and one rule-(e) violation where a negative test hardcoded `expected_grant_award_version: "1"` (a real GrantAward is now created in that instance's setup and its version captured).

## Coverage audit
- **Errors: 65/65** are explicitly asserted as `error_id == …` somewhere in §1.8/§1.9.
- **Endpoints: 61/61** are actually issued as a call (the last 8 collection reads were covered by adding the §1.9 `endpoints` instance `collection_reads_expose_every_declared_filter_and_paginate`, which probes each declared query filter twice — once selecting a known subset, once required to select nothing).
- Structural check: every §1.8 and non-stub §1.9 instance has `grounds`, `distinguishing_aspect` and a complete `test_recipe` (`setup`, `setup_api_calls`, `trigger`, `assert`); no duplicate instance names in either file.

## Scaffold defects found and fixed during generation (§1.2/§1.4/§1.5 reshaped, not weakened)
- `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` was untriggerable — priority 9's state map shadowed every path. Priority 9 now explicitly declines to map `ARBITRATED` for `negotiation-offers` / `accept-level` and delegates them to priority 30.
- Arbitration payout contradicted itself between §1.2 and §1.5 (midpoint vs `baseline_pct`); §1.5 now matches §1.2.
- `ImprovementPlan` return preconditions read the pre-increment counter, contradicting the §1.8 assert; rewritten as `revision_round + 1 < / == MAX_PLAN_REVISION_ROUNDS` with the missing `revision_round += 1` side effect added.
- `MAX_NEGOTIATION_ROUNDS`, `MAX_PLAN_REVISION_ROUNDS` and `MIN_PLAN_MILESTONES` were referenced but undeclared; added to `calculations.performance_indicator_actual.constants`.

The difficulty directive line was stripped: `scenario` begins `2959. Career and Technical Education …` and the string "harder than expert" appears nowhere in `SCAFFOLD.yaml`. `worklog.md` and `workspace/` were not touched, and `.scratch/step2/` (my scratch subdir only) has been removed.

**Orchestrator verification:** all three files parse as YAML; leak-grep for "harder than expert"/"expert level" across SCAFFOLD*.yaml returned nothing.

## Step 3: Copy shared files — 2026-09-05T23:50:41.397417084Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T00:07:22.306748578Z

Step 4 complete. `workspace/PRD.md` is written and verified.

## Deliverable
- **Line count: 500** (`wc -l`), built via 10 chunked appends to dodge the 64k single-write cap.
- No other files created or modified. `.scratch/step4/` was used for verification scripts and removed (the `.scratch` parent was left intact). `worklog.md`, `SCAFFOLD*.yaml`, `test_helpers/`, `test_suite/`, `implementation/` untouched. Neither forbidden design file (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) nor any sibling task dir was opened.

## Section list
`# CTE Program Of Study & Federal Reporting API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Operators, Roles and Access Control · 2.2 API Response Structure (verbatim block, incl. `#### Standard Success Response Format` / `#### Standard Error Response Format`) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Versioning and Audit Timestamps · 2.5 The Logical Clock and Federal Date Arithmetic · 2.6 Path Resolution and Referential Existence · 2.7 The Validation Precedence Ladder · 2.8 State Axes and Transition Admissibility · 2.9 Optimistic Concurrency on Parent Records · 2.10 Segregation of Duties under Federal Grant Controls · 2.11 Cents, Credit Hours, Rates and Rounding Discipline · 2.12 Dual-Variant Computation and Lazy Re-evaluation · 2.13 Cascade Chains and Ledger Reconstruction
- `## 3. Business Logic & Workflows` — 3.1 Authoring a Program of Study and Building the Course Sequence · 3.2 The Comprehensive Local Needs Assessment Cycle · 3.3 Advisory Committee Membership, Meetings and Documented Minutes · 3.4 Sequence Approval: Submission, Findings and State Approval · 3.5 Instructor Certification Pathways · 3.6 Students, Credit Postings, Credential Attainment and Concentrator Classification · 3.7 Federal Grant Awards, Allowable-Use Certification and the Obligation Ledger · 3.8 Performance Indicators: Negotiation, Year Close and the Sanction Cascade · 3.9 Improvement Plans and Lifting the Sanction
- `## 4. Endpoint Definitions` (61 rows + header, exactly 4 columns)
- `## 5. Error Code Catalogue` (65 rows + header, exactly 2 columns)

## Hard Contract results

**Contract 1 — Field-Name Coverage: PASS**
```
entities[].fields:            129 required, 129 present, 0 missing
endpoint input/query fields:   92 required,  92 present, 0 missing
errors:                        65 required,  65 present, 0 missing
roles:                          5 required,   5 present, 0 missing
states:                        36 required,  36 present, 0 missing
enum values (scaffold-wide):   95 required,  95 present, 0 missing
```

**Contract 2 — Rule Coverage: PASS**
```
validations (priority-ordered):   39 / 39   all in the §2.7 ladder, each with its error id
concurrency_rules (OCC):           2 / 2    §2.9, both with field, error id, HTTP 412
state_machines:              7 machines, 48 / 48 transitions documented in §3
calculations:                      6 / 6    full prose formulas, constants, both variants of each dual calc
endpoint side_effects:            61 / 61   endpoints have their effects narrated in §3
entity defaults/initial values:  documented (incl. CredentialAttainment's no-version exception)
sibling-branch symmetry:  REQUESTED→{CERTIFIED,DISALLOWED}; CERTIFIED→{OBLIGATED,VOIDED};
                          SUBMITTED→{RETURNED,REJECTED_FINAL}; NEGOTIATING→{NEGOTIATING,ARBITRATED};
                          {AGREED,ARBITRATED,NOT_MET,MONITORING}→{MET,NOT_MET,NOT_SCORED};
                          PROVISIONAL→{ELIGIBLE,PROVISIONAL,LAPSED} — all branches given equal density
```

**Contract 3 — §3 Path Purity: PASS**
```
§3 backticked tokens scanned: 927
containing "/": 0    bare HTTP methods: 0    method+path pairs: 0    raw "/cte" occurrences: 0
```
Also swept the whole document for `harder than expert`, `difficult`, `approximately`, `roughly`, `conservatively`, `more or less`, `in the neighborhood`, `etc.` — zero hits. No difficulty-tuning language anywhere.

## Coverage notes
13 entities, 61 endpoints, 65 errors, 39 priority-ordered validations, 5 roles, 7 state machines / 48 transitions, 6 calculations, 2 concurrency rules. Both dual-variant calculations (`PROVISIONAL_LOCAL`/`FEDERAL_CERTIFIED` alignment index; `PRELIMINARY_UNADJUSTED`/`FINAL_SMALL_COHORT_ADJUSTED` performance actual) are documented with worked divergences, as are the pinned per-line rounding order, the three indirect-cost tiers keyed on `direct_obligated_cents`, both 4-link cascade chains (sanction and un-sanction), the two lazy clock-driven re-evaluations, and the three segregation-of-duties points. Three scaffold ambiguities were resolved by majority-of-sources and stated unambiguously in prose: CLNA re-open to `DATA_COLLECTION` is admitted from both `CERTIFIED` and `EXPIRED`; the unmapped `held_at >= scheduled_for` precondition maps to `ERR_INVALID_REQUEST` at priority 3; a `CteDirector` opening the negotiation from `PROPOSED` gets `ERR_INVALID_INDICATOR_STATE` at priority 9.

## No-truncation proof
- Final heading: `## 5. Error Code Catalogue`
- Final line, verbatim: `` | `ERR_CHAIR_ALREADY_SEATED` | 409 | ``

`tail -40` shows 40 complete, well-formed 2-column table rows ending on the last error of the 409 block — a clean section boundary, no mid-sentence cut.

**Orchestrator verification:** independently re-checked — `wc -l` = 500; `grep "^## "` shows all five sections at lines 3/11/202/360/430; `tail -15` shows complete pipe-table rows ending at `| ERR_CHAIR_ALREADY_SEATED | 409 |`, a real section boundary, so the known doc-generator truncation failure did NOT occur; leak-grep for the difficulty directive returned nothing.

## Step 6: Generate implementation — 2026-09-06T00:33:00.000Z

(Recorded before Step 5 because the two ran concurrently and Step 6 returned first; Step 5's entry follows.)

Implementation complete and verified.

## Files written — `workspace/implementation/`

| file | lines | role |
|---|---|---|
`start.sh` | 8 | reads `$PORT`, guarded `pip install`, `exec python3 app.py` (foreground) |
`requirements.txt` | 1 | `Flask==3.0.3` |
`app.py` | 69 | blueprint registration, `strict_slashes=False`, `ApiError`/404/405/HTTP/500 handlers, `app.run(host="0.0.0.0", port=$PORT or 10000)` |
`store.py` | 257 | constants, all 20 enum tuples, in-memory `DB.reset()`, logical clock (epoch `2026-08-01T00:00:00Z`), `Decimal`/ROUND_HALF_UP helpers, id/seq/stamp/touch |
`errors.py` | 85 | all 66 error IDs -> HTTP status + default message |
`envelope.py` | 42 | `meta.api_request_id` (`req_` + 20 alnum), 3-frac-digit `Z` timestamp, `object`/`array`/`error` bodies, pagination meta |
`shape.py` | 258 | priority-3 shape layer (`ERR_INVALID_REQUEST`) + query-string/pagination validation |
`auth.py` | 95 | 401 then 403 ladder, 4 opaque identities + entity-backed `CommitteeChair` binding, derived member status |
`calc.py` | 323 | alignment index (2 variants), credit subtotals, concentrator classification, indicator aggregates, quorum arithmetic, 6-step grant ledger rebuild |
`serialize.py` | 263 | 14 entity serializers with derive-on-read fields |
`services.py` | 232 | lazy CLNA/educator transitions, evidence lookups, both 4-link cascade chains, asset-overlap check |
`resolve.py` | 83 | per-entity path resolution -> the 12 `*_NOT_FOUND` codes, left-to-right |
`routes_programs.py` | 385 | 9 GET + 6 write |
`routes_courses.py` | 208 | 3 GET + 3 write |
`routes_students.py` | 181 | 3 GET + 4 write |
`routes_committees.py` | 270 | 5 GET + 4 write |
`routes_grants.py` | 286 | 4 GET + 5 write |
`routes_indicators.py` | 189 | 1 GET + 4 write |
`routes_plans.py` | 150 | 2 GET + 4 write |
`routes_educators.py` | 88 | 1 GET + 2 write + `POST /_clock/set_current_utc` |

3473 lines total; every file `py_compile`s clean.

## Endpoints: 61/61

I diffed the live Flask url_map against the 61 paths declared in `SCAFFOLD.yaml` §1.5 — exact 1:1 match (28 GET + 33 POST/PATCH + the clock endpoint counted in the 33). Nothing omitted; no extra routes (Flask's `/static` route is disabled via `static_folder=None`).

## Domain coverage

- **9 state machines**: ProgramOfStudy `approval_status` and `clna_phase` (independent axes, successor map incl. `CERTIFIED|EXPIRED -> DATA_COLLECTION`), SequenceCourse, CommitteeMeeting minutes (incl. `FINALIZED -> AMENDED`), AdvisoryCommittee (`FORMING -> ACTIVE` on quorum+employer+chair), Expenditure (incl. `REQUESTED<->BLOCKED`), PerformanceIndicator (10 states incl. the `ARBITRATED` carve-out that falls through to `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`), ImprovementPlan, Educator (incl. lazy `-> LAPSED`).
- **Dual-variant calculations**: alignment index `PROVISIONAL_LOCAL` (submit) vs `FEDERAL_CERTIFIED` (state-approve, floor 0.7500 inclusive), single round to 4dp after the clamp with no intermediate rounding; performance actual `PRELIMINARY_UNADJUSTED` (recomputed on every read) vs `FINAL_SMALL_COHORT_ADJUSTED` (only variant that persists `actual_pct`/drives transitions).
- **Grant ledger** rebuilt from scratch in the six pinned steps on every certify/void/obligate; per-line round-half-up of federal share; 3-tier indirect rate; 5% admin cap.
- **Both 4-link cascades**: miss counter -> `IMPROVEMENT_REQUIRED` -> program `SUSPENDED` + `PERF_SUSPENSION` -> `REQUESTED -> BLOCKED`; and the mirror on plan acceptance -> `MONITORING` (miss count 0) -> `SUSPENDED -> CHANGES_REQUESTED` + `PERF_IMPROVEMENT_ACCEPTED` -> `BLOCKED -> REQUESTED`.
- **Validation ladder** (PRD §2.7) implemented in priority order per handler: auth (1-2) -> shape (3) -> path existence left-to-right (4) -> body FK (5) -> OCC (6-7, the two required `expected_*_version` fields -> `ERR_STALE_*_VERSION` 412) -> state (9) -> SoD -> the business checks 10-39. First failure wins.
- Half-open committee terms vs closed grant/asset intervals with the 14-day mobilisation buffer; employer parity (`2xemployers >= eligible`, inclusive); quorum failure ordering headcount -> employer -> vote arithmetic.

## Smoke-test evidence (live server, `bash start.sh`, `PORT=33408`, killed by captured PID)

Envelope matches §2.2 exactly, e.g.
`{"meta":{"api_request_id":"req_UUDBBHB40RROQXOB0JUA","api_request_timestamp":"2026-09-06T00:32:17.209Z"},"response_type":"object","data":{...}}`
and array responses add `limit/offset/total_count/has_more` inside `meta`.

Status-code slice, all as expected: clock set `200 {}` · create program `201` · course create `201` (subtotals 5.0/4.0 recomputed, program version bumped) · enroll `201` · credit posting `200` returning the Student with `concentrator_status: CONCENTRATOR` · list `200` with `total_count:1, has_more:false` · unknown id `404 ERR_PROGRAM_NOT_FOUND` · no headers `401 ERR_UNAUTHENTICATED` · registrar creating a program `403 ERR_UNAUTHORIZED` · bad `cip_code` `400 ERR_INVALID_REQUEST` · negative balance `422 ERR_CREDIT_BALANCE_NEGATIVE` · stale `expected_program_of_study_version` `412 ERR_STALE_PROGRAM_VERSION` ("at version 4, not 1") · `state-approve` on DRAFT `409 ERR_INVALID_APPROVAL_TRANSITION` · grant award `201` with derived ledger (`indirect_rate 0.0812`, `admin_cap_cents 500000`) · educator assign `201` PROVISIONAL -> verify 2100/2500 hours `200` ELIGIBLE.

I also ran a full in-process end-to-end path (charter -> 3 seated members -> 2 quorate CLNA meetings -> 4 CLNA phases -> submit -> endorsement -> state approve -> award/expenditure/certify/obligate -> indicator negotiation -> two misses -> sanction cascade -> plan draft/submit/return/resubmit/accept -> reverse cascade): **0 failures**, with `alignment_index 1.0 FEDERAL_CERTIFIED`, ledger `510000` approved / `41412` indirect / `551412` obligated / `9448588` remaining (arithmetic verified by hand), indicator `actual_pct 33.33` -> `NOT_MET` x2 -> `IMPROVEMENT_REQUIRED`, program `SUSPENDED` then `CHANGES_REQUESTED` with `["PERF_SUSPENSION","PERF_IMPROVEMENT_ACCEPTED"]`.

Two consecutive fresh `start.sh` boots each reported `total_count 0` before any write — no seeding, no persistence, state fully wiped per launch (safe for `--isolation per-test-server`). Killed only my own captured PIDs; no broad pkill. `.scratch/step6` removed (parent and siblings untouched); no files written outside `workspace/implementation/`, and I did not read `test_helpers/`, `test_suite/`, or either withheld design index.

## Step 5: Generate unit tests — 2026-09-06T01:15:58.149372753Z

Stage 2 is complete. Both deliverables sit at the task root and the whole suite collects cleanly.

## Files written

`test_suite/` — 20 files, 11,554 lines:

| file | lines | tests |
|---|---|---|
| conftest.py | 71 | — |
| test_01_dual_variant_calculations.py | 359 | 8 |
| test_02_rounding_and_rollup_formulas.py | 308 | 8 |
| test_03_non_linear_lifecycle_cycles.py | 386 | 14 |
| test_04_temporal_overlap_windows.py | 342 | 8 |
| test_05_transitive_cascades.py | 614 | 20 |
| test_06_compensating_invariants.py | 605 | 17 |
| test_07_validation_priority_conflicts.py | 357 | 9 |
| test_08_boundary_precision.py | 593 | 12 |
| test_09_cross_entity_state_dependencies.py | 723 | 14 |
| test_10_entity_field_sets_and_defaults.py | 681 | 22 |
| test_11_entity_reads_and_foreign_keys.py | 605 | 22 |
| test_12_lifecycle_initial_states.py | 385 | 11 |
| test_13_lifecycle_transition_guards.py | 590 | 11 |
| test_14_calculation_tables_and_tiers.py | 808 | 29 |
| test_15_derived_field_consistency.py | 179 | 7 |
| test_16_validation_rules_and_scopes.py | 1013 | 34 |
| test_17_rbac_and_optimistic_concurrency.py | 842 | 34 |
| test_18_endpoint_behaviour_and_filters.py | 1063 | 41 |
| test_19_error_reachability.py | 1030 | 44 |

Stage 1 `test_helpers/` (9 files, 2,983 lines) is unchanged from the earlier session.

**365 tests**, `pytest --collect-only` -> 365 collected, `grep -c "Design: "` -> 365. All modules `py_compile` clean.

## Design-index coverage

- **Queue A (§1.8 difficulty): 24 / 24 instances translated, 0 skipped.** Every instance is at or above the >=2-test quota (range 3-10).
- **Queue B (§1.9 corner): 50 / 50 non-stub instances translated, 0 skipped.** Every instance >=1 test (range 1-12). The 21 `[STUB]` instances were correctly ignored.
- Zero tag problems: exactly one `Design:` line per test, every tag resolves to a real non-stub instance in the source yaml, no dual-tagged or untagged tests.

## No instance was skipped, but seven sub-assertions were dropped under the C2 filter

1. `counts_toward_indicator` for a `NATIONAL` credential — the corner digest expects `false`; PRD §3.1 says `true`. **PRD asserted.** The digest is wrong here.
2. `federal_reporting_eligible` after plan acceptance — digest expects `true`; PRD §3.9 says it "stays false". **PRD asserted.**
3. `/dependents` — digest expects a transitive closure; PRD §4 derives only direct dependents. **PRD asserted (direct children).**
4. `pos_id` on `GET /cte/sequence-courses/{id}` — the PRD never declares a parent-pointer field on `SequenceCourse`, so that one field assertion is absent.
5. `consecutive_miss_count` after `REJECTED_FINAL` — the PRD specifies the counter only on the acceptance branch; value not derivable, omitted.
6. `active_member_count` after seating an already-lapsed term — §3.3 vs §2.12 leave the stored status ambiguous; omitted.
7. Ill-typed `expected_*_version` probe — PRD derives an outcome only for *omitting* the field; both omission probes are present instead.

Digest cluster literals outside the PRD's five-member enum (`STEM`, `MANUFACTURING`, `ARCHITECTURE`, `ARTS_AV`, `TRANSPORTATION`, ...) were replaced with legal members throughout.

## Verification passes

- **PRD-citation pass:** an AST extractor pulled all 679 quoted spans >=25 chars out of test docstrings and confirmed each is a verbatim (whitespace-normalised) substring of `workspace/PRD.md`. 17 initially failed — 8 elided with `...` and 9 with a fabricated trailing period — and all 17 were repaired in place by splitting into separate verbatim spans or trimming the invented punctuation. Final result: 0 mismatches.
- **Scaffold-citation pass:** `grep -niE "scaffold|§1\.[0-9]|GROUNDS|DISTINGUISHING|difficulty_instance|validations\[|state_machines\.|calculations\.|entities\.[A-Z]|test_recipe|excluded_because"` over `test_suite/*.py` -> **0 hits**.
- **Fixture-correctness guards:** no money-as-string literals; no date-only literals in `scheduled_for`/`held_at`/`submitted_at`/`accepted_at`/`to_iso8601`; no `["data"]` indexing anywhere in `test_suite/` (zero occurrences, so no double-unwrap); no whitespace-only header values; 289 `validate_unpaginated` / 64 `validate_paginated` / 143 `validate_error` / 2 `get_success_data`.
- **Symbol resolution:** every `k.*`, `f.*`, `errors.*`, `users.*`, `build.*`, `api.*` reference in all 19 modules was checked against the live helper modules — 0 missing attributes.

## Output location confirmed

`test_helpers/` and `test_suite/` are both directly under the task root. `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` and `sweep.sh` — no test directories leaked there. `worklog.md`, `PRD.md`, `SCAFFOLD*.yaml` and `workspace/implementation/` were never written. `.scratch/step5` (mine only) was removed; `__pycache__` byproducts cleaned.

One note for Step 7: deviations 1-3 above are places where an implementation generated from the design indices rather than the PRD will fail a test. The tests are right; the implementation should follow the PRD.

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single message, so the implementation generator could not read `test_suite/` (the directory did not exist when it started). Output-location check re-verified by the orchestrator: `test_helpers/` and `test_suite/` are at the task root; `workspace/` holds only INSTRUCTION.md, PRD.md, implementation/, sweep.sh.

## Step 7: Run tests and iterate — 2026-09-06T01:45:15.983849315Z

Loop closed with a clean 8-round sweep.

## Summary

**Iterations run:** 2 (sweep -> 1 fix -> sweep).

**Tests deleted:** none. No test failed the STEP 1 coverage or unique-derivability checks.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `test_04_temporal_overlap_windows.py`, `TestCommitteeSeatTermOccupancy::test_back_to_back_seating_rebuilds_the_committee_member_counts` — corrected `employer_member_count` expectation from `3` to `4`. The assertion miscounted the fixture's own roster.

**Fixes applied to `implementation/`:** none. The implementation was already PRD-faithful on the one failing rule.

### Diagnosis detail

The single failure was deterministic in all 8 rounds of iteration 1 (`assert 4 == 3`), so no flakiness or load-induced noise was in play — every round was 364/365 with the same test.

The scenario builds a committee via `build.seat_roster` with the default roster (`EMP-1` Rosa/EMPLOYER/chair, `EMP-2` Ken/EMPLOYER, `PSE-1` Iris/POSTSECONDARY), then seats an `EMP-3` incumbent (Hana, EMPLOYER, term `2026-01-01`->`2027-01-01`) and a back-to-back `EMP-3` successor (Leo, EMPLOYER, term `2027-01-01`->`2027-12-31`). At the default logical clock of `2026-08-01T00:00:00Z` no member has reached its `term_end_on`, so all five are `ACTIVE` — which the test's own passing `active_member_count == 5` assertion confirms. Four of those five carry `sector` `EMPLOYER`.

PRD §3.3 states: "`employer_member_count` becomes the number of those whose `sector` is also `EMPLOYER`", where "those" are the committee's `ACTIVE` members. `calc.committee_counts` implements exactly that — it filters on `member_status(member) != "ACTIVE"` and then counts `sector == "EMPLOYER"` — so returning `4` is correct. The test's `3` was a plain arithmetic slip that forgot the successor is itself an employer, so this resolved at STEP 2 (assertion mis-translates the PRD rule over the fixture's roster) rather than STEP 3. I confirmed the implementation before editing rather than after, so no PRD-required check was weakened.

Worth noting the sibling test `test_a_successor_starting_on_the_incumbent_end_date_is_seated` already asserts the successor is `ACTIVE` on seating and passed in every round, which independently corroborates the count of 4 — the two tests would have contradicted each other had `3` been right.

### Final sweep evidence

| Round | Passed / Total |
| --- | --- |
| 1 | 365 / 365 |
| 2 | 365 / 365 |
| 3 | 365 / 365 |
| 4 | 365 / 365 |
| 5 | 365 / 365 |
| 6 | 365 / 365 |
| 7 | 365 / 365 |
| 8 | 365 / 365 |

Union of failing tests across all 8 rounds: 0. Zero failures, zero errors.

I left `worklog.md` untouched (unmodified since 01:15, before I started) and removed only my own `.scratch/step7` subdirectory.

**Orchestrator verification (independent of the subagent's report):** all eight `workspace/implementation/results.$i.json` files exist (~131 KB each, all written 01:42) and were re-parsed by the orchestrator — every round reports `passed=365 total=365 failed=0`. The `workspace/SWEEP_DONE` sentinel is present and reads `2026-09-06T01:42:01.416Z / SWEEP COMPLETE`, confirming the sweep ran to `wait` completion under `setsid` rather than being reaped. The sweep was driven by the pre-written `workspace/sweep.sh` (script file, not an inline one-liner) to avoid the known `--start-command` quoting bug and the relaunch-on-early-return trap.

**Step 8 disposition:** the skip condition (0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes) is NOT met — there was 1 `test_suite/` fix across 2 iterations — so Step 8 will run. Note in advance that the single Step 7 item was a test-side arithmetic slip with 0 implementation fixes, so a byte-identical `PRD_FINALIZED.md` would be a legitimate outcome for Step 8 (unlike Step 9, which must not be identical).

## Step 8: Finalize PRD — 2026-09-06T01:47:02.492585303Z

## Result: PRD_FINALIZED.md is byte-identical to PRD.md — and that is the correct outcome

- `PRD.md`: 500 lines, 98,594 bytes. `PRD_FINALIZED.md`: 500 lines, 98,594 bytes. Delta: **0 lines, 0.0%** (md5 `d1c1be2301830867d07e978220852122` for both).
- Changes: **none.** No PRD section required an insert or revise.

### Analysis of the single `<step_7_diff>` item

Item: `test_suite/test_04_temporal_overlap_windows.py::TestCommitteeSeatTermOccupancy::test_back_to_back_seating_rebuilds_the_committee_member_counts` — expectation corrected from `employer_member_count == 3` to `== 4`. No impl fix, no test deletion, no helper fix.

Subject of the item: derivation of `employer_member_count` (and its two siblings `active_member_count` / `chair_member_id`) from a committee's members, plus the clock-derived `CommitteeMember.status` that gates it.

Enumerated impl paths for that subject (all read/grepped, not just the Step 7 site):
- `implementation/calc.py:198-212` — `committee_counts()`: skips members of other committees, skips any member whose `member_status(...) != "ACTIVE"`, then increments `active`, increments `employers` when `sector == "EMPLOYER"`, and takes the first `is_chair` member as `chair_id`.
- `implementation/calc.py:216-221` — `refresh_committee()` writing the three fields.
- `implementation/services.py:188-190` — the seating-path refresh, same triple.
- `implementation/serialize.py:105,113-115` — committee serialization recomputing the same triple at read time (this is the path the failing assertion actually observed).
- `implementation/routes_committees.py:104-105` — charter-time literals `0`/`0`.
- `implementation/auth.py:55-62` — `member_status()`: `EXPIRED` once `clock_date() >= term_end_on`, else `ACTIVE`; plus its other consumers at `auth.py:72,89`, `routes_committees.py:42,131,147`, `serialize.py:130`, confirming one single status definition everywhere.

Comparison with PRD prose (§3.3, PRD.md:244 and PRD.md:242): the PRD already says `active_member_count` is the count of members whose `status` is `ACTIVE`, `employer_member_count` is "the number of **those** whose `sector` is also `EMPLOYER`", and that `status` "begins as `ACTIVE` and becomes `EXPIRED` once the logical clock's date reaches `term_end_on`". Line-for-line that is what `committee_counts` + `member_status` do. In the fixture scenario all five members are pre-`term_end_on` at the default clock `2026-08-01T00:00:00Z` (independently corroborated by the same test's passing `active_member_count == 5`), and four carry `sector` `EMPLOYER`, so `4` is the unique value the PRD determines. The old `3` was a plain arithmetic slip that forgot the back-to-back successor is itself an employer.

Conclusion: the item reveals **no PRD silence and no PRD/impl mismatch** — it is a pure test-fixture arithmetic bug already resolved test-side. Per the method's rule, no edit was made rather than manufacturing one. Since there are zero edits, the per-edit pre-edit search log above is recorded once for the single item that was evaluated and rejected as out-of-scope-for-editing.

Note deliberately left alone (Step 9's job, not mine): the PRD frames the derived counts as rebuilt "each successful seating," while `serialize.py:105` recomputes them live on every committee read. The Step 7 scenario cannot distinguish the two (values coincide at seating and read time), so widening that sentence here would exceed the hard scope.

**Orchestrator verification:** `md5sum` confirms `PRD.md` and `PRD_FINALIZED.md` are byte-identical (both `d1c1be2301830867d07e978220852122`, 500 lines each). This is a legitimate Step 8 outcome, because Step 7 applied 0 `implementation/` fixes and 0 deletions — its one item was a test-side arithmetic slip. Step 9, by contrast, performs a full PRD-vs-implementation scan and must NOT come out identical; the orchestrator will verify that explicitly.

**Step 9 execution plan (decided by the orchestrator, recorded here per the autonomy directive):** Step 9 will be run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`, followed by a fourth narrow reconciliation pass. Rationale: a single agent scanning all 18 implementation modules (3,473 lines) against a 500-line PRD reliably exhausts its output budget and returns an unedited copy. Only pass 1 performs the `cp` from `PRD_FINALIZED.md`; passes 2-4 must edit the existing file in place. Partition:
- Pass 1 — cross-cutting/global modules: `app.py`, `store.py`, `errors.py`, `envelope.py`, `shape.py`, `auth.py`, `resolve.py` (mostly PRD §2).
- Pass 2 — derivation core + program/course routes: `calc.py`, `serialize.py`, `services.py`, `routes_programs.py`, `routes_courses.py`.
- Pass 3 — remaining route modules: `routes_students.py`, `routes_committees.py`, `routes_grants.py`, `routes_indicators.py`, `routes_plans.py`, `routes_educators.py`.
- Pass 4 — reconciliation: resolve contradictions introduced across passes, confirm no truncation, confirm the file is not byte-identical to its source.

## Step 9: Complete PRD — 2026-09-06T02:25:51.247264950Z

Run as four sequential passes over one shared `PRD_COMPLETED.md`: three module-partitioned scan passes plus a reconciliation pass. **49 scan edits + 9 reconciliation edits = 58 total.** Source `PRD_FINALIZED.md` 500 lines / 98,594 chars -> `PRD_COMPLETED.md` 504 lines / 121,689 chars (**+4 lines, +23,095 chars**). Only pass 1 performed the `cp`; passes 2-4 edited in place, and each verified its predecessor's md5 before its first edit.

### Pass 1 — cross-cutting modules (`app.py`, `store.py`, `errors.py`, `envelope.py`, `shape.py`, `auth.py`, `resolve.py`)
12 edits: 11 ambiguity-pins, 1 mismatch-revision. Result after pass: 502 lines, md5 `bf9a5084…`.
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + exactly 20 chars from `A`-`Z`/`0`-`9`, 24 total, minted per request — store.py:144-146.
- §2.2 — insert — ambiguity — `api_request_timestamp` = exactly 3 fractional digits + `Z`, read from the **real wall clock**, not the §2.5 logical clock — envelope.py:8, store.py:183-197.
- §2.2 — insert — ambiguity — pagination `meta` keys absent from single-resource responses; lists always `response_type` `"array"` with a possibly-empty, never-null `data` array — envelope.py:11-27.
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` -> `ERR_INVALID_REQUEST`; undeclared query params ignored; offset >= `total_count` legal; all 15 list endpoints paginated — shape.py:214-234, envelope.py:39-42.
- §2.3 — insert — ambiguity — ordering realised against the server's monotonic creation sequence, not the ms-resolved rendered timestamp; same sequence is the tie-break for equal `fiscal_year`/`scheduled_for`/`position` — store.py:133/246.
- §2.4 — insert — ambiguity — `id` = random v4 UUID, canonical lowercase hyphenated, 36 chars, uniform across entities — store.py:140-141.
- §2.4 — insert — ambiguity — `created_at`/`updated_at` from the real wall clock; `updated_at` equals `created_at` at creation — store.py:243-256.
- §2.5 — insert — ambiguity — epoch renders `2026-08-01T00:00:00.000Z`; clock-set takes a **required** `to_iso8601`, performs no lazy re-evaluation, answers 200 with empty `data`, and may move backwards or to its current value — store.py:61, routes_educators.py:82-89.
- §2.5 — insert — ambiguity — dates accepted only as exact 10-char `YYYY-MM-DD` (`2026-8-1` rejected); instants parsed leniently (any/no fractional width, `Z`/offset/no zone -> UTC, no time part -> midnight UTC), normalised and re-rendered at 3 digits so read-back may differ textually — store.py:150-189, shape.py:145-166.
- §2.1 — insert — ambiguity — 401 precedes body parsing and path lookup on every endpoint; whitespace-only header counts as empty; both header values trimmed; role match case-sensitive so `ctedirector` is 401, not 403 — auth.py:13-25.
- §2.7 item 3 — insert — ambiguity — the whole priority-3 layer reports the single id `ERR_INVALID_REQUEST` (only `message` differs), plus six conventions: absent/empty body == `{}` while non-object/unparseable JSON fails here; explicit `null` == omitted; undeclared body fields ignored; strings rejected when non-string/empty/off-pattern; enums case-sensitive; numeric strings and booleans never accepted for numbers, integral floats like `3.0` accepted for integers; booleans strictly `true`/`false` — shape.py:14-136.
- §2.11 — insert — ambiguity — a scale is a rounding rule, not a rendering rule: plain JSON numbers so trailing zeros are lost (`0.8500`->`0.85`), cents always integers, finer-than-scale client input rounded half-up **at ingest** — store.py:217-239, shape.py:108-121.
- §5 intro — **revise** — **mismatch** — PRD claimed every failure carries a catalogued identifier, but impl emits three uncatalogued transport-level ones: unmatched path -> 404 `ERR_NOT_FOUND`, method not offered -> 405 `ERR_INVALID_REQUEST` (the one place that id is not 400), unhandled fault -> 500 `ERR_INTERNAL`, all raised before authentication; plus trailing-slash insignificance — app.py:25,38-58.

Verified clean, no edit needed: §5 error->HTTP table matches `errors.HTTP_BY_ERROR` exactly (65 ids, zero differences); §2.6 not-found codes match `resolve._TABLES`; §2.4's `CredentialAttainment`-has-no-`version` carve-out matches the single `with_version=False` call site; §2.1's `CommitteeChair` entity binding matches `auth.require_chair_binding`.

### Pass 2 — derivation core + program/course routes (`calc.py`, `serialize.py`, `services.py`, `routes_programs.py`, `routes_courses.py`)
13 edits: 9 ambiguity-pins, 4 mismatch-revisions, all in-paragraph (line count still 502). Result: md5 `0a7d4e41…`.
- §2.12 — revise — mismatch — exact scope of the lazy CLNA refresh: every write whose path addresses the program, plus a sequence-course revision and expenditure certification; child writes elsewhere and the program *collection* read do not refresh, so a lapsed program still lists/filters as `CERTIFIED` — services.py:11, routes_programs.py:42-51,58,226,248,306,347,364, routes_courses.py:99,157,192.
- §2.13 — insert — ambiguity — enumerated which derived fields are derive-on-read (a read can differ from the last write with no `version` move) versus genuinely stored — serialize.py:34,54,68,105,130,159,209,242.
- §3.1 — insert — ambiguity — a PATCH supplying none of the three fields is an accepted no-op that still bumps `version` — routes_programs.py:218-237.
- §3.1 — revise — mismatch — course revision: prerequisite rules re-evaluated for the revised course only (dependents not re-validated); explicit `null` on `prerequisite_course_id` *clears* it (the one field where null != omitted); the `articulated_credit_hours`/`credit_hours` bound uses the effective stored pair; `depth_from_root` derived on read so dependents' `version`/`updated_at` never move; the rebuild uses the variant already in `alignment_index_variant` and never changes it, leaving `alignment_index` null while that field is null; course writes are not gated on `approval_status`, so a write against a `STATE_APPROVED` program rebuilds under `FEDERAL_CERTIFIED` and may push the stored index below the floor — calc.py:26-38,94-103, routes_courses.py:126-180.
- §3.2 — insert — ambiguity — `evidence_url` is filed against the program but never surfaces in any representation — routes_programs.py:281, serialize.py:15-38.
- §3.3 — insert — ambiguity — "the program's `ACTIVE` committee" = newest committee whose own `status` is `ACTIVE`; while the newest is `FORMING` the program has none and every evidence rule fails — services.py:49-55.
- §3.3 — insert — ambiguity — `CommitteeMember.status` is clock-derived on every read, never stored: no `version`/`updated_at` on expiry, and a backwards clock returns it to `ACTIVE` — serialize.py:130 via auth.py:55.
- §3.3 — revise — mismatch — **pass 1's flagged item**: the three derived counts are recomputed on every committee read, so a lapsing term lowers them (and can null `chair_member_id`) with no `version` increment; two `ACTIVE` chairs (reachable via a backwards clock) resolve to the earlier-seated; the `FORMING -> ACTIVE` flip is one-directional and only evaluated at seating — serialize.py:105, calc.py:198-213, services.py:187-197.
- §3.3 — insert — ambiguity — `attendee_member_ids` is not de-duplicated; a repeat is counted once per occurrence and stored as sent — calc.py:230.
- §3.4 — insert — ambiguity — `finding_codes` must be present but may be an empty array (which empties `open_finding_codes`); elements are free-form strings — routes_programs.py:344.
- §3.7 — revise — mismatch — award `status` is derived per read and only the upper edge closes it: before `obligation_window_start` it still reads `OPEN` while requests are refused `ERR_GRANT_WINDOW_CLOSED` — serialize.py:156-161 vs services.py:201-205.
- §3.7 — insert — ambiguity — the 365-day capital-review lookback is measured in whole elapsed days (365 days + hours still qualifies; 366 does not), and a future `held_at` qualifies — services.py:109.
- §3.9 — insert — ambiguity — the terminal return branch never writes the program's `approval_status`: `PERF_SANCTION` is appended and the program's `version` bumped whatever the status, including when link 3 never suspended it; `consecutive_miss_count` untouched — services.py:176-183.

### Pass 3 — remaining route modules (`routes_students.py`, `routes_committees.py`, `routes_grants.py`, `routes_indicators.py`, `routes_plans.py`, `routes_educators.py`)
24 edits: 13 ambiguity-pins, 11 mismatch-revisions, all in-paragraph (line count still 502). Result: md5 `d127961d…`.
- §3.6 — revise — mismatch — enrolment writes/versions no indicator (`denominator_count` is read-derived) and does not bump the program's version on its own account — routes_students.py:63-93.
- §3.6 — insert — ambiguity — a credit posting has no addressable representation; the call answers **200 with the updated `Student`**, not 201 with a posting, and bumps the student's version — routes_students.py:96-126.
- §3.6 — revise — mismatch — an exit is re-admissible (overwrites both fields), returns 200 with the `Student`, writes nothing onto any indicator — routes_students.py:129-141.
- §3.6 — revise — mismatch — `exam_score` is **optional** at priority 3; only the second integrity rule demands it — routes_students.py:152.
- §3.6 — insert — ambiguity — the attainment representation always carries the `exam_score` key, `null` when unsupplied; filing answers **201** with the attainment — serialize.py:97, routes_students.py:181.
- §3.6 — revise — mismatch — filing rewrites the student's three stored derived fields **without** bumping the student's `version`/`updated_at`; credential and indicator counts need no write — routes_students.py:180.
- §3.6 — revise — mismatch — a posting versions the student alone; no indicator record is written or versioned — routes_students.py:124-125.
- §3.3 — insert — ambiguity — the §2.12 CLNA refresh runs *before* the OCC comparison, so a lapse on this very call yields `ERR_STALE_PROGRAM_VERSION`; each dissolved predecessor (incl. a `FORMING` one) gets its own version bump — routes_committees.py:89-97.
- §3.3 — insert — ambiguity — seating is admitted whatever the committee's `status` (incl. `DISSOLVED`) and leaves the program's version untouched — routes_committees.py:113-163.
- §3.3 — revise — mismatch — a scheduled meeting also starts with `eligible_attendee_count` and `employer_attendee_count` at 0; scheduling is admitted whatever the committee's status — routes_committees.py:175-192.
- §3.3 — insert — ambiguity — all minutes inputs but `amendment_reason` required, empty attendee array legal; the `held_at`-vs-`scheduled_for` shape check runs after path resolution but *before* the chair binding — routes_committees.py:200-212.
- §3.3 — insert — ambiguity — a successfully filed minutes always stores `quorum_met` true; false only ever appears on a `SCHEDULED` meeting — routes_committees.py:233-244.
- §3.3 — revise — mismatch — an amendment also overwrites `held_at` and recomputes both attendance counts — routes_committees.py:248-259.
- §3.7 — insert — ambiguity — an expenditure request runs no CLNA refresh and does not bump the charged program's version (`pos_id` is a body FK) — routes_grants.py:127-164.
- §3.7 — insert — ambiguity — `DISALLOW` without `finding_code` is a priority-3 `ERR_INVALID_REQUEST`; a `CERTIFY` may carry one and it is recorded — routes_grants.py:175-176,242-243.
- §3.7 — revise — mismatch — certification writes `approved_cents` only; `federal_share_pct` was stamped at request time and is never restated — routes_grants.py:151,226-239.
- §3.8 — insert — ambiguity — opening an indicator is gated on nothing but the program's existence and does not bump its version on its own account — routes_indicators.py:41-77.
- §3.8 — insert — ambiguity — every accepted offer bumps the indicator's `version`; `rationale` is validated but not persisted — routes_indicators.py:87,119.
- §3.8 — insert — ambiguity — acceptance bumps the version; `acceptance_note` validated, not persisted — routes_indicators.py:127,147.
- §3.8 — insert — ambiguity — a non-advancing `closed_on` is refused at priority 9 with `ERR_INVALID_INDICATOR_STATE`, not as a shape failure — routes_indicators.py:163-169.
- §3.9 — revise — mismatch — milestone element shape: JSON object, non-empty `label`, `YYYY-MM-DD` `due_on`, extra keys dropped, unordered/non-unique allowed, empty array legal at draft — shape.py:193-210.
- §3.9 — insert — ambiguity — submission imposes no condition on the parent indicator's status; `submission_note` not persisted — routes_plans.py:92-102.
- §3.9 — revise — mismatch — the terminal rejection reaches beyond the plan **only while the parent indicator is still `IMPROVEMENT_REQUIRED`**; otherwise it is confined to the plan — routes_plans.py:124-127.
- §3.9 — revise — mismatch — acceptance checks the plan's own state (`ERR_INVALID_PLAN_STATE`) *before* the indicator's — routes_plans.py:137-145.
- §3.5 — revise — mismatch/ambiguity — `full_name` 1-200 chars, `claimed_industry_hours` an integer, and assignment does not evaluate the lapse (a past `credential_expires_on` is stored `PROVISIONAL`) — routes_educators.py:34-48.
- §3.5 — revise — ambiguity — `verified_hours` is an integer and `verification_source` is 1-400 chars — routes_educators.py:58-59.
- §3.5 — insert — ambiguity — further tranches are admitted from `ELIGIBLE`, accumulate against the same ceiling and leave the status at `ELIGIBLE` — routes_educators.py:75-77.

Pass 3 also confirmed pass 1's §2.6 `attendee_member_ids` exemption sentence is correct as written: `calc.eligible_attendance` (calc.py:224-243) silently drops an id that does not resolve, one belonging to another committee, and one whose half-open term does not cover `held_at`'s date — nothing raises.

### Pass 4 — reconciliation (9 edits)
Closed the seven cross-pass items passes 1-3 reported but declined to fix, plus three further contradictions found by re-reading all 49 edited regions.
1. **§2.7 vs §3.1 null handling** — resolved. §2.7's "explicit `null` == omitted" convention now carries the narrow exception for `prerequisite_course_id`, whose `null` *detaches* the prerequisite. Independently verified that routes_courses.py:140 is the only `"…" in data` membership test in the implementation, so the "only such field" claim holds.
2. **§2.12 vs §3.7 refresh scope** — resolved. §2.12's "every create that hangs a child off the program" did admit the expenditure case; narrowed to "every create whose own path addresses the program", enumerating the six real `services.refresh_clna` create call sites, and the negative sentence now names the expenditure request explicitly.
3. **§2.7's priority-3 enumeration** — resolved. Added the three missing cross-field checks (`employer_seat_min` <= `quorum_min_members`, `held_at` >= `scheduled_for`, `finding_code` with `DISALLOW`), stated that the seven cross-field checks are exhaustive while the single-field bounds are illustrative, and noted the `held_at` check is the one priority-3 check that runs after path resolution. `employer_seat_min` <= `quorum_min_members` was already pinned in §3.3, so no §3.3 edit was needed.
4. **List-filter existence** — resolved with one edit in §2.6 (not duplicated in §2.3): `student_id`/`credential_id`/`performance_indicator_id`/`funding_expenditure_id` are matched literally and never resolved, so a non-existent id yields 200 with an empty array and `total_count` 0.
5. **String-length asymmetry** — resolved in §2.7: where no maximum is stated (a committee member's `full_name`, an expenditure's `description`) none is enforced and the one-character minimum is the only bound. Deliberately illustrative — ~20 uncapped call sites exist.
6. **`credit_delta` of exactly 0** — resolved in §3.6: no bound on either side, so a zero delta is legal, is stored as a posting, still increments the student's `version` and still re-runs the classification ladder.
7. **Two mutations in one request** — resolved in §2.4: a version can move twice in one request (confirmed in `create_course`, `create_credential`, `revise_course`, `amend_program`, and a re-opening `clna_advance`).

Additional contradictions found and fixed in the item-8 sweep:
- **§2.4 vs §3.6** — §2.4's "increments by exactly 1 on every mutation" flatly contradicted pass 3's pin that attainment filing rewrites the student's classification fields *without* touching `version`/`updated_at`. Exemption folded into the §2.4 edit; verified at routes_students.py:180.
- **§2.11 vs §2.7** — pass 1's §2.11 ingest-rounding sentence applied to cents fields too, contradicting its own §2.7 clause that `3.5` is rejected where an integer is required. Narrowed §2.11 to the six client-supplied two-decimal fields (verified as the complete `places=2` set) with an explicit cents carve-out.
- **§2.3 sort-override miscount** — "Three endpoints override that default" was immediately followed by a fourth override; corrected to "Four", verified against the four sort sites.

Non-issue reported, not edited: §2.12's *pre-existing* (unedited) claim that the lazy refreshes run "before any other validation" is loose — shape validation and path resolution actually precede `refresh_clna` — but it contradicts none of the 58 edits and sits outside the edited regions.

### Verification (subagent, then re-verified independently by the orchestrator)
- `PRD_COMPLETED.md`: 504 lines, 121,689 chars, md5 `2cd7239f1daa600255e3eb0c5733c9fe`.
- **NOT byte-identical to `PRD_FINALIZED.md`** (`2cd7239f…` vs `d1c1be23…`) — the scan demonstrably ran.
- No truncation: the file still ends at a real section boundary, on the §5 error table's last row `| ERR_CHAIR_ALREADY_SEATED | 409 |`.
- Structure preserved: `diff` of every heading line against `PRD_FINALIZED.md` is **identical** (30 headings, no sections added or renamed); §4 endpoint table still 61 data rows; §5 error table still 65 data rows. The +4 lines are new in-section paragraphs only.
- One edit from each pass spot-checked present after pass 4.
- `PRD.md` and `PRD_FINALIZED.md` both still md5 `d1c1be23…` — neither was modified.
- Orchestrator re-checks: leak-grep for the difficulty directive across all three PRD files returns nothing; `find` confirms **no file under `implementation/`, `test_suite/`, or `test_helpers/` was modified after the green sweep's `SWEEP_DONE`**, so the 8x365/365 result still describes the shipped artifacts.

## Pipeline complete
All nine steps finished. Final deliverables: `SCAFFOLD.yaml` + both design indices, 365 tests in `test_suite/` with `test_helpers/`, a 3,473-line Flask implementation passing 8/8 rounds at 365/365 under `--isolation per-test-server`, and `PRD.md` -> `PRD_FINALIZED.md` -> `PRD_COMPLETED.md`.
