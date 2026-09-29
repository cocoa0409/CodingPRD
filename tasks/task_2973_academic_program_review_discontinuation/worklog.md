# Worklog — task_2973_academic_program_review_discontinuation

## Step 1: Create task directory — 2026-09-05T23:53:09.945Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2973_academic_program_review_discontinuation/` and its `workspace/` subdirectory. Index 2973 was pre-assigned by the invoking pipeline (no scan of ./tasks/, no auto-allocation) because up to 32 pipelines run concurrently on this host. Also created `.scratch/` for per-step scratch subdirs.

## Step 2: Generate scaffold — 2026-09-06T01:55:00.000Z

All three scaffold artifacts for `task_2973_academic_program_review_discontinuation` are complete and lint-clean.

## Files (absolute paths, real line counts)

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | **3292** | 174456 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | **1927** | 133519 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | **6109** | 401168 |

`SCAFFOLD.yaml` top-level keys are exactly `[scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles]` — no `scaffold_difficulty_design` / `scaffold_corner_design` keys. The two design files each carry exactly one top-level key. `worklog.md` and `workspace/` were never touched; `.scratch/step2` (mine) was removed and the `.scratch` parent left in place. No other task directory was created, and no sibling task was read.

## Domain model

13 entities: `AcademicProgram` (root; dual-axis lifecycle + catalog, 15 computed fields), `ViabilityMetricSnapshot`, `ReviewCycle`, `SelfStudy`, `ExternalReviewer`, `ReviewerVisit`, `ReviewerReport`, `DecisionRecord`, `AgencyNotification`, `TeachOutPlan`, `CourseGuarantee`, `DisplacedStudent`, `FacultyAppointment`.

12 state machines, `state_machine_shape: parallel` — the program runs a lifecycle axis (`ACTIVE -> UNDER_REVIEW -> IMPROVEMENT_MONITORED | CONSOLIDATION_PENDING | TEACH_OUT_PENDING -> TEACH_OUT_ACTIVE -> DISCONTINUED | CONSOLIDATED`) alongside an independent catalog axis (`LISTED -> MARKETING_SUPPRESSED -> ADMISSIONS_CLOSED -> CATALOG_WITHDRAWN`, with a reverse edge and `catalog_status_pre_decision` so a rescission restores the prior value). `ReviewCycle` has 10 states with a bounded addendum loop (`addendum_round` 0..2) and a `VISIT_SCHEDULED` self-loop for multi-reviewer teams; `SelfStudy` has a revision loop bounded at two returns; `TeachOutPlan` is `DRAFT -> SUBMITTED -> APPROVED -> IN_EFFECT -> COMPLETED | SUPERSEDED`; `FacultyAppointment` has 6 states including a reversible `REASSIGNMENT_PROPOSED` edge.

44 endpoints, 65 error ids, 46 ordered validations, 6 roles (`ReviewCoordinator`, `Provost`, `ProgramChair`, `ExternalReviewer`, `Registrar`, `HRPartner`; `role_model: segregation_of_duties`), 6 calculations, 2 OCC rules, `difficulty_level: expert_plus`.

## §1.8 depth probe — 9 rule_ids x 2 instances = 18

`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

## §1.9 breadth probe — 83 entries = 72 active + 11 `excluded_because` stubs

entities 12 · state_machines 14 (12+2) · calculations 11 (7+4) · validations 18 (16+2) · endpoints 7 · errors 6 · rbac 6 · cross_cutting_complexity_layers 7 (4+3) · consistency_model 2. Every stub cites a real `<rule_id> / <instance_name>` pair in the difficulty design (verified programmatically, 0 bad refs) and carries no `test_recipe`.

## Verification beyond the lint

- **Endpoint coverage: 0 of 44 endpoints untouched** by §1.8+§1.9 (this closed three read channels — `GET /provost/reviewer-visits`, `GET /provost/reviewer-visits/{id}`, `GET /provost/academic-programs/{id}/review-cycles` — via a new `computed_read` endpoints instance asserting the derived `span_start_date`/`span_end_date` calendar-day cut and AND-composed filters).
- **Error coverage: 0 untriggered of 65**, and 0 error ids referenced that aren't declared. This caught two invented ids in the new work: `ERR_DUPLICATE_TERM_INDEX` (real name `ERR_DUPLICATE_TERM_SNAPSHOT`) and `ERR_DUPLICATE_FACULTY_NUMBER`, which does not exist — `faculty_number` has no uniqueness constraint, so that call would have returned 201; it was replaced with an `fte: 1.50` -> `ERR_VALIDATION` 422 refusal.
- No difficulty-directive text and none of the forbidden concurrency vocabulary appears in any of the three files; all instance names unique; every active instance has `distinguishing_aspect` + a `setup`/`trigger`/`assert` recipe.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    44
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     72
  Calls scanned (§1.8+§1.9):  1437

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Orchestrator verification: `grep -rn "harder than expert"` over the task dir returns nothing — the difficulty directive did not leak into any scaffold value. Line counts confirmed independently: 3292 / 1927 / 6109.

## Step 3: Copy shared files — 2026-09-06T02:04:58.246Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` (1424 bytes) to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-06T02:22:34.371Z

PRD complete.

**Output:** `workspace/PRD.md` — **530 lines, 108,805 bytes**

**Section structure**
- `# Academic Program Review & Discontinuation API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections: 2.1 Actors, Authentication Headers and Identity · 2.2 API Response Structure (verbatim block) · 2.3 Pagination · 2.4 Record Identity, Versioning and Audit Stamps · 2.5 The Logical Clock and Statutory Interval Arithmetic · 2.6 Two Independent Axes on Every Program · 2.7 Derived Figures, Rounding Discipline and Recomputation Points · 2.8 Optimistic Concurrency on the Program and the Cycle · 2.9 Path Resolution and the Terminal-Program Bar · 2.10 The Order of Refusals · 2.11 Two Conserved Quantities
- `## 3. Business Logic & Workflows` — 11 subsections (3.1 program registration & viability evidence -> 3.11 faculty appointments, staffing waterfall & separation)
- `## 4. Endpoint Definitions` — 4-column table
- `## 5. Error Code Catalogue` — 2-column table

**Coverage documented (all machine-verified against SCAFFOLD.yaml)**
- **44 / 44 endpoints** — method+path set is an exact match, zero missing, zero extra; **all 44 role lists match the scaffold exactly**; the 13 scaffold-`code`-201 endpoints are exactly the resource-creation POSTs, consistent with the stated 201/200 rule
- **65 / 65 error ids** — exact set match, and **all 65 HTTP statuses match** the scaffold's `http` field
- **46 / 46 validations** — rendered as an explicit numbered 1–46 waterfall in §2.10; every error id (including the 5 multi-id steps, 33 ids in total across priorities 7, 8, 10, 12, 18) and every `http_status` verified present on its own numbered step, plus each `applies_to` scope
- **12 / 12 state machines, 76 unique transitions (79 declared edges)** — every `from`/`to` pair verified documented; all state values present
- **6 / 6 calculations** with full formulas and every constant value
- **6 / 6 roles**, **13 / 13 entities**, **2 / 2 OCC rules**

**Hard Contracts**
- **Contract 1 (Field-Name Coverage): PASS** — 158 required names (147 entity fields + 11 endpoint-only identifiers); 0 missing after repair. Two FK names (`visit_id`, `teach_out_plan_id`) were absent on the first pass and were given a natural home: a new §2.9 paragraph on path-derived parent-key stamping.
- **Contract 2 (Rule Coverage): PASS** — all 8 categories walked mechanically. Three real gaps found and fixed: (a) §2.10 steps 7 and 8 delegated their 404 vocabulary to §2.9 instead of naming the 15 ids inline — now inlined; (b) the `PROPOSED -> RATIFIED` edge was only implicit in §3.6 — now explicit; (c) **the closed `action` enum vocabulary was never given as literals** — the PRD described transitions only by verb, so an implementer would have invented wire tokens. Added a §2.1 paragraph enumerating all accepted `action` values for all seven action-bearing endpoints (`SUBMIT`/`RETURN`/`ACCEPT`/`APPROVE`/`ACTIVATE`/`RATIFY`/`EFFECTUATE`/`RESCIND`/`EVALUATE_IMPROVEMENT`/`SEND`/`ACKNOWLEDGE`/`RETAIN`/`PROPOSE_REASSIGNMENT`/`WITHDRAW_REASSIGNMENT`/`CONFIRM_REASSIGNMENT`/`ISSUE_NOTICE`/`SEPARATE`/`COMMIT`/`RELEASE`/`SUBSTITUTE`/`WAIVE`/`COMPLETE`/`WITHDRAW`) plus the verb->token mapping and the out-of-set -> `ERR_VALIDATION` 422 rule.
- **Contract 3 (§3 Path Purity): PASS** — 887 backticked tokens in §3; zero start with `/`, zero are bare HTTP methods, zero are method+path; zero occurrences of `/provost` in §3 even unbackticked.

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md`; zero occurrences of any difficulty directive or fuzzy quantifier ("approximately", "roughly", "conservatively"); file ends at a complete section with a complete final table row.

**Constraints honoured:** written as 1 `Write` + 5 `cat >>` heredocs plus 5 targeted `Edit` repairs (no single large write); the two withheld design YAMLs were never opened, grepped, or referenced; `worklog.md`, `SCAFFOLD*.yaml`, `workspace/INSTRUCTION.md` untouched; only `.scratch/step4/` was removed, the `.scratch` parent remains.

**Verbatim last 3 lines:**
```
| `ERR_TENURE_OBLIGATION_ACTIVE` | 409 |
| `ERR_NOTICE_PERIOD_NOT_ELAPSED` | 409 |
| `ERR_REASSIGNMENT_TARGET_INVALID` | 422 |
```

**One scaffold inconsistency worth flagging to the test author:** `DecisionRecord.notification_count`'s entity description says "in any status", while §1.3 `agency_notice_deadline` says non-`VOIDED` only. I documented the §1.3 reading (non-`VOIDED`), since the calculation block is the arithmetic authority and it is the only reading under which rescinding a decision returns `compliance_posture` to `NOT_APPLICABLE`.

Orchestrator truncation check (the known doc-generator failure mode): `tail -25` ends on a complete error-catalogue table row `| \`ERR_REASSIGNMENT_TARGET_INVALID\` | 422 |`, not mid-sentence. Independently counted 65 `ERR_` catalogue rows and 44 endpoint-table rows in §4 — matches the scaffold's declared totals, so no trailing section was dropped. Section headings present: §1 (L3), §2 (L11), §3 (L211), §4 (L409), §5 (L460). No regeneration needed. No difficulty-directive leak.

## Step 5: Generate unit tests — 2026-09-06T03:12:01.000Z

Step 5 complete. Test suite generated for `task_2973_academic_program_review_discontinuation`.

## Files written (all at the TASK ROOT, verified — nothing under `workspace/`)

`test_helpers/` — 3048 lines
`__init__.py` 20, `api_client.py` 459, `api_errors.py` 183, `assertions.py` 474, `constants.py` 182, `factories.py` 532, `fixtures.py` 621, `test_users.py` 127, `types.py` 450

`test_suite/` — 8876 lines
`conftest.py` 54; queue A: `test_01_dual_variant_calc.py` 184, `test_02_combinatorial_formula.py` 234, `test_03_non_linear_state_machine.py` 261, `test_04_transitive_cascade.py` 305, `test_05_priority_pair_validation_conflict.py` 242, `test_06_boundary_precision_check.py` 227, `test_07_cross_entity_state_dependency.py` 254, `test_08_resource_temporal_overlap.py` 265, `test_09_compensating_invariant.py` 344; queue B: `test_10_corner_entities.py` 788, `test_11_corner_state_machines.py` 895, `test_12_corner_calculations.py` 534, `test_13_corner_validations.py` 1122, `test_14_corner_endpoints.py` 833, `test_15_corner_errors.py` 839, `test_16_corner_rbac.py` 652, `test_17_corner_cross_cutting.py` 568, `test_18_corner_consistency.py` 275

## Tests emitted: 90

- **Queue A (§1.8 difficulty): 18 tests** — all 18 active instances across 9 rule_ids, 2 tests per rule_id, zero stubs.
- **Queue B (§1.9 corner): 72 tests** — all 72 active instances across the 9 corner sections. The 11 instances carrying `excluded_because` produced no tests and are referenced by no tag.

## Skipped instances: none

Every active instance in both indices passed the PRD-first two-condition filter and was translated. No placeholders, no `skip`/`xfail`, no weakened assertions. Coverage audit prints `uncovered active difficulty: []` and `uncovered active corner: []`.

## Verification

- `ast.parse` — **OK for 28 files** (all 19 test_suite + all 9 test_helpers).
- Static reference resolver over all 18 test files — **ALL REFERENCES RESOLVE**: every `test_helpers` attribute, every `GenericApiClient` method, every `ERR_*` constant, and every call arity/keyword binds against its definition.
- Design-tag audit — **TAG AUDIT CLEAN**: 90 test functions, each with exactly one well-formed `Design:` line as the final docstring line; zero untagged, zero dual-tagged, zero duplicate tags, zero tags pointing at stubs or non-existent instances.
- `.scratch/step5` removed; `.scratch/step6` (Step 6's dir) left intact. Nothing under `workspace/implementation/` was read, listed, or written, and no server was started.

## Notes worth carrying into Step 7

- The two-sided seat ledger and the FTE waterfall are asserted by conservation identity (`assert_seat_conservation`, `assert_fte_partition`) at every observation point, so a Step 7 failure in those helpers means the aggregate is internally inconsistent, not that a single field is off.
- Several queue-A tests issue a **byte-identical request twice** across a state change (test_06 decision proposal, test_07 plan ACTIVATE, test_09 seat commit). If both halves fail identically the fault is in the shared setup path, not in the boundary being probed.
- `test_06`'s boundary constants were hand-derived from PRD §3.2 rather than taken from the yaml: 3 flat snapshots give composite exactly 40.00 (IMPROVEMENT_ELIGIBLE); the 4th snapshot gives rolling 50042 / latest 50126 / composite 39.99 (NONVIABLE). These match `constants.py`.

Orchestrator verification: `test_helpers/` and `test_suite/` are at the task root; `workspace/test_helpers` and `workspace/test_suite` do not exist (the known misplacement failure mode did not occur). Independently counted 90 `def test_` and 90 `Design:` tag lines — one tag per test.

## Step 6: Generate implementation — 2026-09-06T03:15:00.000Z

Verification and clean-up are done. Final state of the deliverable:

## Files written (all under `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `derive.py` | 498 | all 6 calculations, rounding helpers, seat ledger primitives |
| `r_programs.py` | 386 | programs, snapshots, catalog axis, cycles, appointments create, plan create |
| `r_decisions.py` | 331 | ratify / effectuate / rescind / evaluate + agency notifications |
| `serial.py` | 313 | 14 entity serializers |
| `r_reviewers.py` | 278 | reviewers, visits, reports, addendum re-file |
| `r_plans.py` | 251 | teach-out plans, guarantees, seat allocations |
| `r_cycles.py` | 248 | cycle read, self-study create, program response, decision proposal |
| `valid.py` | 197 | body-schema layer (check 9) |
| `guards.py` | 188 | roles, per-(endpoint,action) RBAC, ownership, terminal bar, resolvers |
| `r_students.py` | 142 | displaced students, advising, progress |
| `store.py` | 142 | in-memory dicts, logical clock, instant/interval arithmetic |
| `errors.py` | 107 | 65 error ids -> HTTP status |
| `r_faculty.py` | 107 | appointment machine, reduction sequence, notice, separation |
| `r_selfstudy.py` | 101 | self-study patch + SUBMIT/RETURN/ACCEPT |
| `envelope.py` | 85 | response envelope, request id, pagination |
| `app.py` | 83 | Flask app, Decimal/datetime JSON provider, error handlers, `PORT` entry |
| `cascade.py` | 65 | multi-hop cascades and auto-minted notices |
| `filters.py` | 48 | list filter helpers |
| `r_misc.py` | 39 | `POST /_clock/set_current_utc`, `POST /provost/compliance-sweeps` |
| `start.sh` | 7 | launcher |
| `requirements.txt` | 1 | `Flask==3.0.3` |

Total 3617 lines, 19 `.py` files. Flat module layout, no package, no persistence of any kind (process dicts only).

## PRD section -> module

- §2.1–2.3 headers/roles/action vocabularies -> `guards.py`; §2.2/2.3 envelope+pagination -> `envelope.py`
- §2.4 stamps and version bumps -> `store.touch`; §2.8 OCC -> `r_programs.create_plan` (`expected_program_version`) and `r_cycles.propose_decision` (`expected_cycle_version`)
- §2.5 logical clock and 24h-multiple intervals -> `store.py` + `r_misc.py`
- §2.6 two program axes -> `r_programs.CATALOG_EDGES` (cross-axis guards) + `serial.program`
- §2.7 rounding discipline and recomputation points -> `derive.py` (compute-on-read, so nothing can go stale)
- §2.9 best-effort resolution + terminal bar -> `guards.program_of_*`, `Ctx.not_terminal`
- §2.10 checks 1–3 -> `guards.begin`; 4–6 -> `Ctx.chair_owner/reviewer_owner/segregation`; 7 -> `Ctx.require`; 8 body FKs and 9 schema -> per handler + `valid.py`; 10 -> OCC; 11 -> terminal bar; 12–46 -> the owning route module in numbered order
- §2.11 seat conservation -> `derive.holdings` ledger keyed `(guarantee_id, student_id)`
- §3.1–3.2 -> `r_programs.py`; §3.3 -> `r_programs.create_cycle` + `r_selfstudy.py`; §3.4 -> `r_reviewers.py`; §3.5 -> `r_reviewers.file_report` + `r_cycles.program_response`; §3.6 -> `r_cycles.propose_decision` + `r_decisions._ratify`; §3.7 -> `r_decisions.py` + `cascade.mint_auto_notifications` + `r_misc` sweep; §3.8 -> `r_decisions._effectuate/_rescind/_evaluate_improvement`; §3.9 -> `r_plans.py`; §3.10 -> `r_students.py`; §3.11 -> `r_faculty.py` + `derive.waterfall`
- §4 all 44 endpoint rows implemented — 44 route decorators (26 POST, 17 GET, 1 PATCH), no extras; §5 -> `errors.py`

## Verification

- `ast.parse` on every file: `AST OK for 19 files`.
- `len(errors.ERROR_STATUS) == 65`, statuses drawn only from `{401,403,404,409,412,422}`.
- `start.sh` execs in place — proven: `PORT=18975 bash start.sh &` recorded pid 785946, `ss -ltnp` showed `python3 pid=785946` bound to `0.0.0.0:18975`, and killing that one pid freed the port. So the harness's per-test kill/relaunch cycle cannot leak a listener.
- Fresh process starts empty with the clock at its mandatory default:
  `GET /provost/academic-programs` -> `{"meta":{...,"api_request_timestamp":"2026-08-01T00:00:00.000Z","total_count":0,"has_more":false},"response_type":"array","data":[]}`
  `POST /provost/academic-programs {"code":"BOOT-BA",...}` -> `201 CREATED`, `data` with `lifecycle_state:"ACTIVE"`, `catalog_status:"LISTED"`, `viability_band:"INSUFFICIENT_DATA"`, `composite_score:null`, all staffing figures 0.0, `version:1`
  `POST /provost/academic-programs` as `Registrar` -> `403` `ERR_ROLE_NOT_PERMITTED`

## Behaviour confirmed end-to-end (four smoke scripts on port 18973)

Discontinuation arc: cost pair 100000/133333/226667 -> composite 12.03 / NONVIABLE / rolling 139130 / cap 14400000; 4-hop ratification (`TEACH_OUT_PENDING` + `MARKETING_SUPPRESSED` + `catalog_status_pre_decision:"LISTED"` + two AUTO_MINTED notices at exactly +30d/+45d from `ratified_at`); sweep boundary strict (0 marked at `due_at`, 1 marked one second later); 3-hop completion cascade to `DISCONTINUED`/`CATALOG_WITHDRAWN` with retained appointments returned to `ASSIGNED`.

Consolidation arc: `ERR_RECEIVING_PROGRAM_REQUIRED` -> `ERR_OUTCOME_NOT_SUPPORTED_BY_VIABILITY` -> `ERR_RECEIVING_PROGRAM_INELIGIBLE` (self as receiver) in the declared order; rescission unwound every hop (program back to `UNDER_REVIEW` with `catalog_status` restored verbatim and `catalog_status_pre_decision` nulled, notices `VOIDED` so `notification_count` 2->0 and posture back to `NOT_APPLICABLE`, cycle `DECIDED -> RESPONSE_SUBMITTED` with `decided_at` cleared); replacement decision effectuated to `CONSOLIDATED`/`ADMISSIONS_CLOSED`.

Improvement arc: `IMPROVEMENT_MONITORED` with the catalog axis untouched, `EVALUATE_IMPROVEMENT` refused before effectuation, then `UNMET` reopening the cycle with `discontinuation_override:true`.

Gates individually exercised: checks 22 and 23 now both proven distinct — same reviewer 24h buffer -> `ERR_REVIEWER_WINDOW_CONFLICT`, two *different* reviewers on one calendar day against `host_capacity_per_day:1` -> `ERR_PROGRAM_HOST_CAPACITY_EXCEEDED`; checks 34/35 in the declared precedence (`ERR_COURSE_GUARANTEE_SHORTFALL` first, then `ERR_AT_RISK_STUDENTS_PRESENT`); `ERR_STALE_PROGRAM_VERSION`/`ERR_STALE_CYCLE_VERSION`; `ERR_SEGREGATION_OF_DUTIES`; `ERR_TENURE_OBLIGATION_ACTIVE` outranking `ERR_NOTICE_PERIOD_NOT_ELAPSED`; `ERR_REDUCTION_SEQUENCE_VIOLATION` and `ERR_TENURE_NOTICE_TOO_SHORT`; `ERR_VISIT_NOT_SCHEDULED`, `ERR_REPORT_ALREADY_FILED`, `ERR_NOT_ASSIGNED_REVIEWER`, `ERR_NOT_PROGRAM_OWNER`, `ERR_PROGRAM_ALREADY_TERMINAL`; the seat ledger (`ERR_SEAT_CAPACITY_EXCEEDED`, `ERR_SEAT_NOT_COMMITTED`, `ERR_GUARANTEE_HAS_COMMITMENTS`, `ERR_GUARANTEE_STATE_INVALID`) with substitution leaving `seats_guaranteed`/`seats_committed` untouched while a waive drops the row from `guaranteed_seat_total`; `retained_teach_out_fte` correctly clamped to `faculty_fte_baseline`; notice pay verified against hand arithmetic at three tenure tiers (986301, 82192, 4438356); waterfall stopping on the severance cap leaves `reduction_sequence_position` null.

Three `{"state":null}` outputs from the first smoke run were confirmed to be legitimate refusals (`ERR_PLAN_STATE_INVALID` / `ERR_DECISION_STATE_INVALID` / `ERR_PROGRAM_ALREADY_TERMINAL`) caused by my script's own sequencing, not crashes. No traceback or `ERR_INTERNAL` occurred at any point.

Clean-up: smoke server killed by exact pid 523421 (no `pkill` used), ports 18973/18974/18975 confirmed free, `__pycache__` removed, `.scratch/step6` removed and the shared `.scratch` parent left in place. `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened; `worklog.md`, `SCAFFOLD.yaml`, `PRD.md` and `INSTRUCTION.md` were never touched.

Orchestrator note: Steps 5 and 6 were launched concurrently in a single message, so the implementation generator started before `test_suite/` existed on disk — physical isolation from the tests, in addition to its instruction not to read them.

## Step 7: Run tests and iterate — 2026-09-06T03:33:42.000Z

Clean sweep achieved. All 90 tests pass in all 8 rounds.

## Summary

**Iterations run:** 2 (sweep 1 -> diagnose/fix -> sweep 2 clean).

**Tests deleted:** none. The single failing test was PRD-covered and uniquely derivable, so STEP 1 kept it and the bug resolved at STEP 2 (test artifact), never reaching STEP 3.

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_client.py` — added the `allow_blank_header_values()` context manager, which suspends `requests.utils._validate_header_part` for the duration of a block and always restores it. Needed because `requests` refuses a whitespace-only header value *client-side* (its validator admits only `""` or a value beginning with a non-whitespace character), so the probe raised `InvalidHeader` and never put a byte on the wire — leaving the PRD clause unexercised.
- `test_helpers/test_users.py` — docstrings on `make_headers_with_whitespace_user_id` / `make_headers_with_whitespace_role` now state that they must be sent inside that context manager, removing the footgun.

**Fixes applied to `test_suite/`:**
- `test_suite/test_16_corner_rbac.py`, `test_blank_and_unknown_identity_headers_are_rejected_before_anything_else` — the two whitespace-only probes now issue their request inside `allow_blank_header_values()`, then assert as before.

**Fixes applied to `implementation/`:** none — the implementation was already correct.

**Key finding.** The lone failure was a test-transport bug, not a defect. `guards.py:117` already implements the §2.1 rule correctly (`role_hdr.strip() == "" or user_hdr.strip() == ""`). Confirmed with a raw socket that the server, handed a genuinely unstripped `X-User-ID: "   "` on the wire, answers `401 ERR_MISSING_AUTH_HEADER` — exactly what §2.1 mandates ("contains only whitespace ... treated exactly as an absent one"). The assertion was therefore never weakened: rather than collapsing the whitespace probe into the already-covered empty-string case (which would have silently dropped coverage of a distinct PRD clause), the client-side obstruction was removed so the server adjudicates header validity, which is where the contract places that decision.

One note on method, since it affected triage: the first spot-check of `test_16` showed an unrelated `ERR_DUPLICATE_PROGRAM_CODE` failure. That was an artifact of a single shared probe server accumulating state — the sweep uses `--isolation per-test-server`, giving each test a fresh empty store. Not a defect, and it does not appear under the real runner.

**Final sweep evidence** (from `results.$i.json`, key `status`; nonpass count cross-checked equal to `total - passed` in every round, union of failures across all 8 rounds empty):

| Round | Passed/Total |
|---|---|
| 1 | 90/90 |
| 2 | 90/90 |
| 3 | 90/90 |
| 4 | 90/90 |
| 5 | 90/90 |
| 6 | 90/90 |
| 7 | 90/90 |
| 8 | 90/90 |

`worklog.md` untouched, probe server killed by exact PID, scratch log removed, no changes outside `test_suite/` and `test_helpers/`.

Orchestrator verification: independently parsed all 8 `results.$i.json` — every round reads `90 / 90`. The sweep ran via the pre-written `workspace/sweep.sh` under `setsid nohup` with the `SWEEP_DONE` sentinel, so neither the reaping failure mode nor the early-return-relaunch failure mode applied. Step 8 is NOT skipped: Step 7 applied 2 `test_helpers/` fixes and 1 `test_suite/` fix, so the skip condition (zero fixes of every kind) is not met — though with 0 implementation fixes, a byte-identical `PRD_FINALIZED.md` would be a legitimate Step 8 outcome.

## Step 8: Finalize PRD — 2026-09-06T03:41:38.000Z

No edits were warranted. `PRD_FINALIZED.md` is byte-identical to `PRD.md` — which, per the brief, is the correct output here.

## Line counts

| File | Lines | Bytes | MD5 |
|---|---|---|---|
| `PRD.md` | 530 | 108805 | `7a943055722deb824adc13e13620d736` |
| `PRD_FINALIZED.md` | 530 | 108805 | `7a943055722deb824adc13e13620d736` |

**%-delta: 0.00%** (0 lines changed, 0 inserted, 0 deleted).

## Per-item analysis of `<step_7_diff>`

All four diff items reduce to a single subject — the §2.1 whitespace-only auth-header rule — and none of them reveals PRD-silence or PRD/impl mismatch.

- **`test_helpers/api_client.py` — `allow_blank_header_values()` added.** Pure client-side transport fix. `requests.utils._validate_header_part` rejects a whitespace-only header value before it reaches the socket, so the probe never exercised the server. Suspending a *client library's* validator says nothing about the server contract; there is no server behavior here to pin.
- **`test_helpers/test_users.py` — docstrings only.** No behavioral content whatsoever.
- **`test_suite/test_16_corner_rbac.py` — probes wrapped in the context manager.** The assertions were unchanged (`ERR_MISSING_AUTH_HEADER`, 401). Step 7 explicitly did *not* weaken them — it removed the client-side obstruction so the server could adjudicate. So this is not evidence of PRD ambiguity.
- **`implementation/` — zero fixes; zero test deletions.** Nothing to align to.

Critically, the behavior at the Step 7 site is **already uniquely determined by PRD.md**, verbatim in two places, so rule 2 ("where PRD already determines behavior, keep prose verbatim") applies:

- **§2.1, line 15**: "If either header is absent, an empty string, or contains only whitespace, the request is refused with `ERR_MISSING_AUTH_HEADER` (HTTP 401); a whitespace-only value is treated exactly as an absent one."
- **§2.10, line 156** (check 1): "Both `X-User-Role` and `X-User-ID` are present and non-blank on every request — otherwise `ERR_MISSING_AUTH_HEADER` (401)", ranked above check 2 (`ERR_INVALID_ROLE`, line 157).

`implementation/guards.py:115-118` implements precisely that, in precisely that order — `None` check, then `.strip() == ""` (which subsumes both the empty-string and whitespace-only cases), then role-membership. Adding prose would have been redundant at best and a narrowing risk at worst.

## Pre-edit search log

No edits were committed, but the mandatory enumeration was run for the one candidate subject before concluding:

**(a) Subject identified:** auth-header presence/blankness validation and its rank in the §2.10 refusal waterfall.

**(b) Impl paths enumerated:**
- `grep -rn "X-User\|headers"` across all of `implementation/` -> only **two** header-reading callsites exist in the entire codebase: `guards.py:113` (`X-User-Role`) and `guards.py:114` (`X-User-ID`), both inside `begin()`. No route module reads headers directly, so there is no off-Step-7 path with divergent blankness semantics.
- `guards.py:111-130` (`begin()`) read in full — confirmed ordering: absent -> blank -> unknown role -> endpoint role list -> per-action owner.
- `errors.py:82-83` — canonical messages, consistent with the 401 pair.
- Verified `begin()` is the universal gate by counting callsites per module: `r_programs.py` (11), `r_reviewers.py` (7), `r_plans.py` (6), `r_decisions.py` (6), `r_cycles.py` (5), `r_students.py` (4), `r_selfstudy.py` (2), `r_misc.py` (2), `r_faculty.py` (1). No module bypasses it.
- `r_misc.py:13-19` — confirmed the clock endpoint `POST /_clock/set_current_utc` also gates through `begin((CHAIR, REVIEWER, COORD, PROVOST, REGISTRAR, HR))`, matching §2.1's explicit "including the test-driving clock endpoint". This was the path most likely to be a silent exception; it is not one.

**(c) Wording adjustment:** none — no sentence was changed, because every enumerated path is already correctly described by the existing §2.1 and §2.10 prose.

No `.scratch/step8/` was created. `PRD.md`, `implementation/`, `test_suite/`, `test_helpers/`, `INSTRUCTION.md`, `worklog.md` and `SCAFFOLD*.yaml` were left untouched; `worklog.md` and the scaffolds were never read.

Orchestrator note: a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 result precisely because Step 7 made 0 implementation fixes and 0 deletions — there was no impl behavior for the PRD to have mis-described. Step 9, by contrast, must NOT come back identical: it runs a full impl scan and is the step that closes silences the test suite never probed. Step 9 will therefore be run as sequential module-partitioned passes over one shared `PRD_COMPLETED.md`, followed by a narrow reconciliation pass.

## Step 9: Complete PRD — 2026-09-06T04:25:01.817Z

Step 9 was run as FOUR SEQUENTIAL passes over one shared `workspace/PRD_COMPLETED.md`: three partitioned by implementation module (pass 1 does the `cp`, passes 2–4 must not), then a narrow reconciliation pass to close the cross-pass escalations. Rationale: a single agent cannot hold 3617 lines of implementation plus a 530-line PRD and still scan exhaustively, and unpartitioned re-runs produce a byte-identical file. Totals: **12 + 29 + 28 + 5 = 74 edits**, `PRD_FINALIZED.md` 530 lines / 108,805 bytes -> `PRD_COMPLETED.md` **532 lines / 130,692 bytes** (+21,887 chars, +2 lines). MD5 `e674196de168e2b5119f5e21d2657513` vs source `7a943055722deb824adc13e13620d736` — NOT identical, so the scan genuinely ran.

### PASS 1 — app.py, envelope.py, store.py, guards.py, errors.py, valid.py, filters.py, serial.py, r_misc.py

`cp` performed as the first action: `PRD_FINALIZED.md` -> `PRD_COMPLETED.md`, at 530 lines / 108805 bytes. Source 530 lines / 108805 bytes -> after edits 530 lines / 114156 bytes; char-delta +5317. Counts: ambiguity-pins **12**, mismatch-revisions **0**. The two catalogues checkable mechanically were already exact: all 65 `error_id`->HTTP status pairs in §5 match `errors.py` one-for-one, and all 134 payload keys emitted by `serial.py` already appear in the PRD.

- §2.1 — insert — ambiguity — header values used untrimmed: role matched exactly (whitespace-padded valid name => `ERR_INVALID_ROLE`), `X-User-ID` compared verbatim — `guards.py:113-120`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A–Z/0–9 — `envelope.py:11-15`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the logical clock, not wall clock — `envelope.py:19`, `store.py:55-56`
- §2.2 — insert — ambiguity — every declared field always present, empty => JSON `null`, never omitted; only `updated_at`/`version` on the two append-only types are absent — `serial.py:12-17`
- §2.3 — insert — ambiguity — `limit`/`offset` parsed as trimmed text with optional `+`/`-`; empty or non-digit (`5.0`) => non-integer failure; `limit` examined before `offset`; no upper bound on `offset`; `offset >= total_count` => empty `data`, `has_more` false — `envelope.py:58-78`
- §2.3 — insert — ambiguity — `created_at` ties break by insertion sequence, same tiebreak settles equal `cycle_year` / equal `reduction_sequence_position`; `id` is never an ordering key — `store.py:132-133`, `r_programs.py:237-238,299-302`
- §2.3 — insert — ambiguity — string filters exact and case-sensitive; non-integer `term_index`/`cycle_year` and non-boolean `at_risk` (accepted `true/false/1/0`, case-insensitive, trimmed) yield an empty array, never an error — `filters.py:17-48`
- §2.5 — insert — ambiguity — accepted ISO-8601 grammar (optional seconds, `.`/`,` fraction up to 9 digits, `T`/space separator, `Z` or `±HH:MM` converted to UTC, no designator read as UTC) and render rule: microsecond precision stored, exactly 3 fractional digits rendered with finer digits truncated — `store.py:19-22,63-102`, `r_misc.py:16-19`
- §2.7 — insert — ambiguity — cents/counts as JSON integers, two-decimal figures as JSON numbers (not strings) with no trailing zero preserved (`47.5`, `1.0`) — `derive.py:47-51`, `app.py:32-38`
- §2.10 check 4 — insert — ambiguity — checks 4/5/6 are skipped when the named row does not resolve, so check 7's 404 wins even for a chair/reviewer/self-ratifying provost — `guards.py:73-96`, `r_decisions.py:60-62`
- §2.10 check 9 — insert — ambiguity — full body contract: required `application/json` object on every POST/PATCH except the compliance sweep and visit-completion; undeclared keys ignored; JSON `null` == absent; numbers never as strings; integer fields reject booleans and `3.0`; boolean fields reject `0`/`1`; `fte`/`improvement_target_score` reject >2 decimals; uppercase-constrained strings/code arrays must already equal their uppercasing; code arrays keep order and duplicates — `valid.py:19-197`, `guards.py:99-102`
- §3.7 — insert — ambiguity — `marked_overdue_notification_ids` in ascending insertion order; those three keys are the whole `data`; no request body — `r_misc.py:22-39`
- §4 — insert — ambiguity — unmatched path and unaccepted method both answer `ERR_VALIDATION` 422 (not 404); 404 reserved for unresolvable identifiers — `app.py:53-61` (verified live)

Escalated to pass 4: `app.py:63-73` emits `ERR_INTERNAL` at HTTP 500, absent from the §5 catalogue whose intro claims universality; and Flask `strict_slashes` behavior on trailing-slash paths.

### PASS 2 — derive.py, r_programs.py, r_cycles.py, r_selfstudy.py, r_reviewers.py

No `cp` was run. Entry 530 lines / 114,156 bytes (pass 1's 12 inserts verified present); exit 530 lines / 119,715 bytes; **+5,559 chars**. All 12 pass-1 markers re-verified present afterwards; heading count unchanged at 30. Counts: **22 ambiguity-pins, 7 mismatch-revisions (29 edits)**.

- §2.6 — insert — ambiguity — `suppression_note` 1–2,000 chars, validated but persisted nowhere and echoed on no payload — `r_programs.py:120`
- §2.6 — revise — mismatch — `ADMISSIONS_CLOSED -> CATALOG_WITHDRAWN` unreachable by the registrar (check 11 outranks the edge check => `ERR_PROGRAM_ALREADY_TERMINAL`); fires only as the plan-completion cascade — `r_programs.py:122-126`, `cascade.py:36-40`
- §3.2 — insert — ambiguity — enrollment factor when oldest window observation enrolled 0: 100 if newest > 0 else 50 — `derive.py:237-241`
- §3.2 — insert — ambiguity — completion factor when window headcount sum is 0: 0 if completions sum is 0 else 100 — `derive.py:245-250`
- §3.2 — insert — ambiguity — efficiency factor is 0 when rolling cost is null, 100 when exactly 0 cents — `derive.py:256-262`
- §3.3 — insert — ambiguity — `ACTIVE`/`IMPROVEMENT_MONITORED` are the only source states the cycle-open edge moves; other non-terminal states keep `lifecycle_state` and still bump program `version` — `r_programs.py:224-226`
- §3.3 — insert — ambiguity — self-study creation ungated on cycle state, omitted `section_codes` = `[]`, parent cycle `version` untouched — `r_cycles.py:53-73`
- §3.3 — insert — ambiguity — `attestation_note` 1–2,000 chars; all three PATCH keys optional; a no-op edit still succeeds and bumps `version` — `r_selfstudy.py:24-43`
- §3.3 — revise — ambiguity — SUBMIT's `attestation_note` optional; omitted preserves the earlier value — `r_selfstudy.py:76-77`
- §3.3 — revise — ambiguity — RETURN's `revision_notes` optional, writes null when omitted, clearing the prior round's note — `r_selfstudy.py:89`
- §3.3 — insert — ambiguity — ACCEPT->cycle cascade fires only from `SELF_STUDY_OPEN` — `r_selfstudy.py:98-100`
- §3.4 — revise — ambiguity — `conflict_program_codes` must already be uppercase, but program-code charset is not enforced — `r_reviewers.py:34-35`
- §3.4 — insert — ambiguity — body FKs resolve `cycle_id` before `reviewer_id`; both unresolvable => `ERR_CYCLE_NOT_FOUND` — `r_reviewers.py:113-122`
- §3.4 — insert — ambiguity — visit list has no path parent and no ownership narrowing; a chair sees every program's visits — `r_reviewers.py:169-176`
- §3.5 — insert — ambiguity — first report's cycle cascade fires only from `VISIT_COMPLETED` — `r_reviewers.py:254-259`
- §3.5 — insert — ambiguity — addendum self-loop still increments `ReviewerVisit.version` — `r_reviewers.py:261`
- §3.5 — revise — **mismatch** — disputed-code subset is over the union of every report on every visit of the cycle, not the newest report; empty/omitted array on `DISPUTE` is `ERR_VALIDATION` at the body-schema step, above the cycle-state check — `r_cycles.py:105-122`
- §3.5 — insert — ambiguity — `response_submitted_at` not cleared when an addendum closes a round — `r_reviewers.py:262-266`
- §3.6 — revise — **mismatch** — "branch discipline is symmetric and strict" -> strict on two of the three fields — `r_cycles.py:164-178`
- §3.6 — revise — **mismatch** — the two improvement fields on a non-improvement outcome are `ERR_VALIDATION`; `improvement_milestones` is ignored (not refused) and always stored as `[]` — `r_cycles.py:164-178`
- §3.6 — insert — ambiguity — the `INSUFFICIENT_DATA` refusal is absolute and precedes `discontinuation_override` — `r_cycles.py:196-200`
- §3.7 — revise — **mismatch** — `compliance_posture` pools notifications across every decision record on the cycle, whatever state those decisions are in — `derive.py:488-498`
- §3.9 — revise — ambiguity — a `decision_id` on the wrong program, or with a non-wind-down outcome, is `ERR_VALIDATION` at the body-schema step, not a 404 or state error — `r_programs.py:335-340`
- §3.9 — insert — ambiguity — a plan whose decision is neither `RATIFIED` nor `EFFECTUATED` is refused `ERR_DECISION_STATE_INVALID`, ranked below stale-token/terminal and above the horizon check — `r_programs.py:350-356`
- §3.10 — insert — ambiguity — a student withdrawn straight from `PENDING` reports `CONSERVATIVE_ADVISED_LOAD` with load falling back to `max_credits_per_term` — `derive.py:404-408`
- §3.11 — insert — ambiguity — duplicate `faculty_number` within the program is `ERR_VALIDATION`, evaluated ahead of the terminal-program bar — `r_programs.py:261-263`
- §3.11 — revise — ambiguity — step-4 pool order gets a final insertion-sequence tiebreak after `created_at` — `derive.py:340-344`
- §2.10 check 26 — revise — **mismatch** — unknown-finding-code check applies to the `DISPUTE` branch only; `CONCUR`/`PARTIAL_CONCUR` store codes unchecked — `r_cycles.py:113-122`
- §3.11 — revise — **mismatch** — `fte` is "carried to no more than two decimals" (was "exactly two"), so `0.5` is accepted — `valid.py:137-139`

Hand-off verdicts: (1) step-4 residual tie **edited**, worded to match pass 1's §2.3 sentence; (2) `faculty_number` uniqueness **edited** — §3.11 stated the uniqueness but named no error, now pinned to `ERR_VALIDATION` at check 9 ahead of check 11; (3) `forbid_present` **edited**, and additionally corrected the PRD's claim that all three branch fields are strictly disciplined; (4) `seats_available` on a `WAIVED`/`SUBSTITUTED` guarantee — **no edit warranted**: §3.9 already pins the formula unconditionally, impl matches literally, and the discrepancy is non-observable (waiving requires `seats_committed == 0`, `COMMIT` is refused on a `WAIVED` guarantee, `SUBSTITUTED` leaves the ledger untouched).

No contradiction with any pass-1 insert. Flagged for pass 4: check-26 was changed by pass 2 not pass 1; and the 404-before-typing behavior on body FKs supplied with the wrong JSON type, judged already implied by §2.10's 8-before-9 ranking.

### PASS 3 — r_decisions.py, cascade.py, r_plans.py, r_students.py, r_faculty.py

No re-copy: no `cp`, no `Write`, no whole-file rewrite; 22 `Edit` calls. Entry 530 lines / 119,715 bytes with all pass 1+2 edits present; exit 530 lines / 127,334 bytes; **+7,619 bytes, +0 lines**. Counts: **20 ambiguity-pins, 8 mismatch-revisions (28 changes)**.

- §2.6 — revise — mismatch — `catalog_status_pre_decision` copied on the wind-down hop unconditionally, even when the catalog axis does not move; a rescission whose pre-decision slot is null leaves `catalog_status` untouched — `r_decisions.py:110-112,201-203`
- §2.10 check 8 — revise — mismatch — applies-list extended to the seat-allocation endpoint's `displaced_student_id`, reporting `ERR_STUDENT_NOT_FOUND` at this rank — `r_plans.py:177-183`
- §2.10 check 12 — revise — mismatch — carve-out scoped to the progress endpoint only; advising reports `ERR_STUDENT_STATE_INVALID` from `PLAN_SIGNED` as well — `r_students.py:89-90,121-122`
- §3.6 — revise — ambiguity — `ratification_note` optional, 1–2,000 chars, stored null when omitted — `r_decisions.py:69`
- §3.6 hop 2 — insert — ambiguity — the four lifecycle edges fire only from `UNDER_REVIEW`; otherwise the lifecycle axis is untouched while remaining hops proceed and `version` still advances — `r_decisions.py:106-113`
- §3.6 hop 3 — revise — ambiguity — the pre-decision copy records whatever the axis holds; the axis moves only from `LISTED` — `r_decisions.py:110-112`
- §3.6 hop 4 — revise — ambiguity — posture recomputes to `NOTICES_PENDING`, from `NOT_APPLICABLE` ordinarily but from `NOTICES_CLEARED` when an earlier decision on the cycle left acknowledged notices in the pool — `cascade.py:44-58`, `derive.py:488-498`
- §3.6 — revise — ambiguity — `CONTINUE`/`IMPROVEMENT_PLAN` leave posture exactly where it stood rather than necessarily at `NOT_APPLICABLE` — `derive.py:488-498`
- §3.6 — insert — ambiguity — decision-record list has no path parent and no chair narrowing; the single-record read is narrowed — `r_decisions.py:32-41,44-50`
- §3.7 — revise — ambiguity — `transmitted_reference` is 1–200 characters — `r_decisions.py:313`
- §3.7 — revise — mismatch — rescission voids only `PENDING`/`SENT`/`OVERDUE`; `ACKNOWLEDGED` notices survive, so posture can remain `NOTICES_CLEARED` — `r_decisions.py:194-197`
- §3.8 — revise — mismatch — the four effectuation gates reordered so the receiving-program gate ranks first, matching §2.10's 29 < 31 < 32 < 33 — `r_decisions.py:126-149`
- §3.8 — insert — ambiguity — effectuation lifecycle/catalog edges guarded on source state; every other branch effect fires regardless; `CONTINUE`/`IMPROVEMENT_PLAN` leave `AcademicProgram.version` untouched — `r_decisions.py:162-172`
- §3.8 — revise — ambiguity — `rescission_reason` optional, 1–2,000 chars — `r_decisions.py:71`
- §3.8 — revise — mismatch — rescission writes `lifecycle_state` to `UNDER_REVIEW` unconditionally, including from the `ACTIVE` a ratified `CONTINUE` produced; only the catalog restore is guarded — `r_decisions.py:199-204`
- §3.9 — insert — ambiguity — teach-out-plan list has no path parent and no chair narrowing — `r_plans.py:23-30`
- §3.9 — revise — ambiguity — `SUBMIT` tests plan state before decision state; `revision_notes` optional 1–2,000 and a null overwrites an earlier round's value — `r_plans.py:64-68,57`
- §3.9 — revise — ambiguity — `course_code` length-checked only (no case/charset rule), `seats_guaranteed` unbounded above, duplicate guarantees on one plan permitted and counted separately — `r_plans.py:130-132`
- §3.9 — insert — ambiguity — `displaced_student_id` resolved whenever present, before the action is read and before the terminal bar; all four actions answer 200 with the guarantee payload and bump only `CourseGuarantee.version` — `r_plans.py:177-183,220/235/242/250`
- §3.9 — revise — ambiguity — `SUBSTITUTE`: code 3–16 chars; substitute equal to `course_code` is `ERR_VALIDATION` ranked ahead of both the terminal bar and the status check; justification required 1–2,000 — `r_plans.py:195-198`
- §3.9 — revise — mismatch — `waived_reason_code` optional, 1–40 chars, null when omitted — `r_plans.py:200`
- §3.9 — revise — ambiguity — `displaced_student_id` 1–200 chars with no cross-plan enrolment check; `seat_count` at least 1 — `r_plans.py:179-193`
- §3.10 — revise — ambiguity — `student_number` collision is `ERR_VALIDATION` ranked ahead of the terminal bar; `credits_remaining` >= 0 unbounded above, 0 accepted yielding 0 terms, null projected completion, `at_risk` false, 0 seats — `r_students.py:31-36`, `derive.py:410-418`
- §3.10 — revise — mismatch — advising refused from `PLAN_SIGNED` with `ERR_STUDENT_STATE_INVALID`; student state tested before plan state — `r_students.py:89-94`
- §3.10 — revise — ambiguity — `completion_term_index` optional >= 1, null when omitted; plan state tested before advising status on `COMPLETE`; `withdrawal_reason_code` optional 1–40; `WITHDRAW` imposes no plan-state condition — `r_students.py:114-135`
- §3.10 — insert — ambiguity — hop 1 not firing leaves the plan's `version` unmoved; hop 2's two legs each guarded on their source value; hop 3 fires only when hop 2's lifecycle leg fired — `cascade.py:24-41`
- §3.11 — revise — ambiguity — `reassigned_to_department_code` 2–12 chars, compared verbatim against the receiving program's code — `r_faculty.py:38,81`
- §3.11 — revise — ambiguity — `notice_days` required integer >= 0, unbounded above — `r_faculty.py:40`

Hand-off verdicts: (1) `student_number` **confirmed and pinned** — same shape as `faculty_number`, `ERR_VALIDATION` before `not_terminal`; (2) `credits_remaining` 0 **confirmed reachable and pinned**; (3) no-chair-narrowing **confirmed for both lists and pinned** in §3.6/§3.9 (neither `list_decisions` nor `list_plans` calls `ctx.chair_owner`); (4) §3.10's three-hop prose **reconciled** — the rescission `lifecycle_state = "UNDER_REVIEW"` is unconditional and only the catalog restore is guarded, while `maybe_complete_plan`'s hop-2/hop-3 guards are real and reachable (a second cycle can be opened on a program still in `TEACH_OUT_ACTIVE`). Verification of pass 2's cross-partition claims: §3.7 pooling **ACCURATE** (`derive.py:488-498` iterates `decisions_of(cycle["id"])` regardless of decision state — this forced pass 3 to correct two of its own posture sentences that had asserted `NOT_APPLICABLE` unconditionally); §2.6 unreachable catalog edge **ACCURATE** (`r_programs.py:122` `not_terminal` precedes `:124-126` `catalog_edge_allowed`).

Escalated to pass 4: the seat-allocation endpoint performs no cross-plan check, so a `COMMIT` naming a student enrolled on a different plan is accepted and credited to both sides — possibly making §2.11's per-plan conservation invariant a false universal (§2.11 is pass 1's territory).

### PASS 4 — reconciliation

No `cp`. Entry 530 lines / 127,963 bytes; exit **532 lines / 130,692 bytes**; **+2,729 chars, +2 lines. 5 edits.** No prior pass's edit was reverted.

- **Item A — `ERR_INTERNAL` — RESOLVED by qualifying the §5 intro (option i).** `app.py:63-73` shows it is emitted only by the blanket `@app.errorhandler(Exception)` after the `isinstance(err, ApiError)` re-dispatch at `app.py:65-66` — only on an unexpected fault, never on a specified refusal path, and it is absent from `errors.py`'s `ERROR_STATUS`. The §5 intro (line 462) no longer universalises and names `ERR_INTERNAL`/HTTP 500 in prose. **No row added** — the table still has exactly 65 `ERR_` rows.
- **Item B — §2.11 seat conservation WAS a false universal, now qualified.** Settled by `derive.py:148-162` (`guarantee_committed` sums `db.holdings` over all students; `student_committed` sums over all guarantees on all plans), `r_plans.py:177-183` (check 8 resolves `displaced_student_id` against the global `db.students` with no plan-membership test) and `serial.py:255`/`serial.py:275`. A cross-plan `COMMIT` moves supply on one plan and demand on another, breaking per-plan equality on **both**. The invariant's opening is now qualified ("on any teach-out plan whose seats have only ever been committed to students enrolled on that same plan"), cross-referencing pass 3's §3.9 sentence; also pinned that `derive.release_all_holdings` (`r_students.py:137`) releases holdings plan-agnostically.
- **Item C — 404-before-typing on body FKs — ONE CLAUSE ADDED** (mild disagreement with pass 2). Confirmed at `r_programs.py:320-326`, `r_cycles.py:147-153`, `r_reviewers.py:110-122`, `r_plans.py:177-183`: all four use `db.X.get(supplied) if isinstance(supplied, str) else None`, so a non-string FK is unresolvable and 404s before `require_object_body()`/`valid.*` run. 8-before-9 points at this, but "resolves to an existing row" can equally be read as presupposing a well-typed value, making check 9's 422 the answer — a 404-vs-422 fork a test will hit. One clause added to check 8, grounded in §2.4 (all minted ids are strings).
- **Item D — Trailing slash — PINNED, because pass 1's premise was factually wrong.** Pass 1 recorded a 308 redirect; empirically it is not. No registered rule ends in a slash, so Werkzeug `strict_slashes` 404s (it redirects only in the opposite direction) and `app.py:53-56` converts that into an enveloped `ERR_VALIDATION` -> HTTP **422** (`errors.py:24`). Measured live on port 8791: `POST /provost/academic-programs/` -> 422 `ERR_VALIDATION` "No such route."; `GET /provost/nonexistent` -> same; `DELETE /provost/academic-programs` -> 422 "Method not allowed for this route." (`app.py:58-61`); all three identical **with no auth headers at all**, so route matching precedes check 1. Enveloped, deterministic, product-observable, and mentioned nowhere in the document — pinned as one paragraph in §2.9.
- **Item E — cross-pass consistency audit: NO contradictions found.** Every named overlap region was read and checked against the implementation, and all held: §2.3 vs §3.11 step 4 are different orders serving different purposes, both exact (`r_programs.py:296-303` vs `derive.py:340-344`); §2.10 check 9 decimals vs §3.11 `fte` consistent with `r_programs.py:258-259` (`places=2`, `low_exclusive=True`); check 26 DISPUTE-only confirmed at `r_cycles.py:113-122`, with check 18's `ERR_ADDENDUM_LIMIT_REACHED` genuinely ranking ahead; checks 8 & 12 confirmed at `r_students.py:119-121` (terminal-only carve-out) with the `ERR_ADVISING_REQUIRED` fall-through at `:128` and plan-state-before-advising at `:126-129`; §3.7 pooling confirmed at `derive.py:488-498` with passes 2 and 3 agreeing; §2.6's two `catalog_status_pre_decision` sentences confirmed at `r_programs.py:113-130` and `r_decisions.py:108-113,198-202`, and check 11 preceding check 13 (`r_programs.py:122` before `:124`) is what makes the "unreachable by the registrar" claim true. The only tension pass 4 created was between its new §2.9 paragraph and check 1's "on every request", closed with a one-sentence precedence note in §2.10's intro (edit 5).
- **Item F — structural integrity: intact.** 532 lines / 130,692 bytes. Headings present and in order: §1; §2 with 2.1–2.11 (2.2 keeps its two `####` sub-headings); §3 with 3.1–3.11; §4; §5 — no section added or removed. §4 method rows **44** (unchanged); §5 `ERR_` rows **65** (unchanged). Artifact scan (double spaces, `..`, `,,`, `;;`, orphaned em-dashes, stray markers) flagged only the legitimate indentation inside §2.2's JSON code fence. Verbatim last 2 lines: `` | `ERR_NOTICE_PERIOD_NOT_ELAPSED` | 409 | `` / `` | `ERR_REASSIGNMENT_TARGET_INVALID` | 422 | `` — a complete final table row, file ends cleanly.

### Orchestrator closing verification

- `PRD_COMPLETED.md` **532 lines / 130,692 bytes**, MD5 `e674196de168e2b5119f5e21d2657513`; source `PRD_FINALIZED.md` 530 / 108,805, MD5 `7a943055722deb824adc13e13620d736` — **not identical**, so the completeness scan genuinely ran (the known Step 9 no-op failure mode did not occur). 65 `ERR_` rows confirmed independently.
- `workspace/implementation/` last modified 02:50:35, well before the 03:23:07 clean 8-round sweep, and untouched by Steps 8 and 9 — the passing sweep evidence still describes the shipped code. All 8 `results.$i.json` present at 90/90.
- No stray `workspace/test_helpers` or `workspace/test_suite`. One leftover probe server (PID 908431, cwd = this task's `implementation/`) survived a pass-1 kill of its parent shell; the orchestrator killed that exact PID and verified it dead. The 72 other `app.py` processes on the host belong to concurrent pipelines and were deliberately left alone — no broad pkill was ever issued.
- `.scratch/` parent intact and empty; every pass removed only its own subdir.

Pipeline complete through Step 9.
