## Step 1: Create task directory — 2026-09-06T02:57:54.875137548Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2991_academic_integrity_case_adjudication and its workspace/ subdirectory (pre-assigned path; no index allocation performed).

## Step 2: Generate scaffold — 2026-09-06T05:03:21.942863988Z

All three scaffold artifacts are complete, parse cleanly, and pass the scaffold lint.

**Task dir**: `/home/ubuntu/github/CodingPRD/tasks/task_2991_academic_integrity_case_adjudication/`

**SCAFFOLD.yaml (3677 lines)** — §1.0–§1.7, neither forbidden key present. 15 entities (Department, FacultyMember, Student, CourseOffering, IntegrityReport, EvidenceItem, Case, Notification, AdvisorEngagement, CaseMeeting, HearingRoom, HearingSession, PanelVote, Sanction, Appeal), 74 endpoints, 72 errors, 61 ordered validations, 10 calculations, 8 state-machine blocks (Case has 3 parallel dimensions), 2 OCC rules, 6 roles (segregation_of_duties), 3 invariants, 3 designed priority conflicts. Profile: `compliance_audit` / `multi_party_negotiation`, layers `cascading_side_effects, dual_variant_calculation, derived_field_reconciliation, optimistic_concurrency`, flat topology, immediate consistency.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (2725 lines)** — 20 instances across all 9 rules (>=2 each): dual_variant_calc 2 (formal/informal ladder bands; submitted/adjudicated reporting basis), combinatorial_formula 3 (7-step evidence chain; grade-component rounding; escalation read from provisional), non_linear_state_machine 3 (parallel case dimensions; return-for-info cycle; remand loop hitting the round limit), transitive_cascade 2 (5-hop impose reaching a sibling case; 4-hop overturn unwind), priority_pair_validation_conflict 2 (13 over 38; 32 over 44), boundary_precision_check 2 (45.00 vs 44.99 similarity band; strict inequalities at the peer/training thresholds), cross_entity_state_dependency 2 (reporter training on submit; pending advisor blocks convene), resource_temporal_overlap 2 (half-open instructor calendar vs closed buffered rooms + daily cap), compensating_invariant 2 (room-minutes ledger; points/open-case counters).

**SCAFFOLD_CORNER_DESIGN.yaml (4934 lines)** — 66 instances (38 full recipes + 28 `excluded_because` stubs) over 9 sections: entities 11, state_machines 17, calculations 12, validations 13, endpoints 5, errors 2, rbac 1, cross_cutting_complexity_layers 4, consistency_model 1. Foot of file carries a generated error-catalog coverage map: all 72 error ids are asserted by at least one §1.8/§1.9 instance.

**Verification**: `scaffold_lint.py` → `VERDICT: clean lint` (74 endpoints, 15 entities, 20 §1.8 + 38 §1.9 instances, 1422 calls scanned); all 86 instance names unique across both design files; every stub's `difficulty_instance` resolves; no stub carries a `test_recipe`; only the two intentionally invalid sha256 negatives deviate from `^[0-9a-f]{64}$`.

**Fixes made to SCAFFOLD.yaml this session**: validation priority 11 now covers `POST /integrity/cases/legacy-import` (the endpoint declared `ERR_REPORT_STATE_INVALID` with no rule behind it) and pins that legacy import requires a DRAFT report. Nothing outside the three output files was touched.

**Orchestrator note**: the scaffold generator copied the difficulty directive line "Generate task harder than expert level!" into SCAFFOLD.yaml's `scenario:` block. The orchestrator stripped that single line immediately after Step 2 (verified by grep across the task dir) so it cannot reach PRD.md via the doc generator. YAML re-verified as parseable after the edit.

## Step 3: Copy shared files — 2026-09-06T05:03:21.957289930Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T05:23:49.223008034Z

PRD complete and verified.

**File:** `workspace/PRD.md` — **569 lines**, ends at a clean boundary (final row of the §5 error table).

**Sections:** §1 Introduction; §2.1 RBAC · 2.2 Response Structure (verbatim) · 2.3 Pagination · 2.4 Logical Clock · 2.5 Common Resource Properties · 2.6 Sub-Resource Path Resolution · 2.7 Numeric Precision · 2.8 Optimistic Concurrency · 2.9 Validation Precedence · 2.10 Two Case Dimensions · 2.11 Conserved Quantities · 2.12 Sanction Ladder; §3.1–3.10 (departments/faculty, students/gradebook, intake/evidence/triage, case opening + dual severity algorithms, notice/advisors/meetings, informal pathway, hearings, sanctions, appeals, notation/expungement); §4 Endpoint Definitions; §5 Error Code Catalogue.

**Coverage:** 74 endpoints (4-column table, 0 malformed rows) · 72 errors (2-column table, all unique) · 61 validation priorities · 10 calculations · 15 entities / 143 fields · 8 state machines / 62 transitions / 44 states · 2 OCC rules · 3 invariants · 6 roles.

Field coverage check: entities[].fields 143/143 present; endpoints[].request_body 81/81; query_params folded into input. PASS
Rule coverage check: 61/61 validation priorities in prose; 2/2 OCC rejections; 62/62 transitions; 10/10 calculations; 61/61 error_id-matchable conditions; 37/37 side_effects; 4/4 structured field contents; 2/2 sibling-branch symmetry groups equal density. PASS
Path purity check (§3 only): 1223 backtick tokens scanned, 0 paths, 0 bare methods, 0 method+path tokens. PASS

Two fixes applied during verification: the `.../adjourn` shorthand in the §2.9 rank-17 entry was expanded to full paths, and four recurring-decimal ellipses were reworded to "recurring" so no placeholder-looking text remains (grep for TODO/TBD/"..."/"as above" is clean).

**Orchestrator verification (truncation guard):** independently re-counted the PRD tail — 72 `ERR_*` catalogue rows (matches scaffold's 72 errors), 74 endpoint table rows (matches scaffold's 74), last line is a well-formed table row of §5, and the heading list ends at `## 5. Error Code Catalogue`. Not truncated; no regeneration needed. Leak grep for "harder than expert"/"scaffold"/"test_recipe" over PRD.md: clean.

## Step 6: Generate implementation — 2026-09-06T06:23:53.864744163Z

Implementation complete.

**Modules** (`workspace/implementation/`, 4271 lines total): app.py 80, db.py 101, errors.py 95, util.py 106, response.py 122, middleware.py 100, shapes.py 221, calc.py 811, cascades.py 134, routes_admin.py 320, routes_reports.py 245, routes_cases.py 540, routes_advisors.py 221, routes_hearings.py 349, routes_sanctions.py 422, serializers.py 286, lookup.py 107, start.sh 10, requirements.txt 1.

**Coverage.** All 74 PRD endpoints are routed — a programmatic diff of the Flask url_map against the PRD §4 table reports zero missing and zero extra (74 = 74). All 72 error ids are catalogued in `errors.py`; the 61-rank precedence order, the 8 state machines, both OCC endpoints, the RBAC model and the 3 derived-on-read ledgers are implemented. State is in-memory only, nothing is seeded, and `start.sh` binds `0.0.0.0`, reads `$PORT` (default 10000) and runs in the foreground.

**Verification.** Two cold-boot smoke runs touched 103 distinct endpoint/method pairs with zero 5xx: full formal lifecycle (report -> evidence -> triage -> case -> severity -> notice -> room/session -> votes -> decide -> sanction -> impose -> notation post -> complete), informal lifecycle (INFORMAL pathway -> meeting -> informal-resolution -> ACCEPT -> impose -> complete), dismissal, adjourn, cancel, legacy-import, expungement request+grant, and all four appeal outcomes (upheld restores `pre_appeal_adjudication_status`; reduction vacates rank 6 and creates a rank-4 `APPEAL_REDUCTION` replacement in IMPOSED with the notation standing; remand -> FORMAL_REFERRED/UNDETERMINED; overturn -> CLOSED/EXPUNGED/`overturned: true`). Stale `expected_case_version` returns 412 `ERR_STALE_CASE_VERSION`; missing headers return 401. Smoke servers were killed by captured PID/port only, and `.scratch/step6` was removed (siblings `step4`/`step5` untouched).

**Ambiguities resolved this session** (earlier ones unchanged)
- `POST /integrity/sanctions/{id}/complete`: rank 13 outranks rank 19, so a pending appeal (SUBMITTED/UNDER_REVIEW) yields `ERR_CASE_STATE_INVALID` before the IMPOSED check.
- `POST /integrity/sanctions/{id}/impose`: case state (rank 13, DECIDED+RESPONSIBLE or INFORMAL_ACCEPTED) is checked before sanction state (rank 19), and rank 34 component-scores before rank 44 effective-before-decision.
- Appeal screening: rank 13 case state before rank 20 appeal state; appeal deciding: rank 15 pathway (remand only) before rank 20.
- The appeal-reduction replacement sanction keeps the entity defaults for the three grade figures (0.00) and a null `grade_component_code` — PRD §3.9 enumerates only origin/replaces/rank/kind/status for that row.
- PRD §2.7 requires exactly two decimals, but `json.dumps` renders `Decimal("60.00")` as `60.0`; the response encoder now emits Decimals as nonce-tagged tokens that are unquoted into bare JSON numbers, so bodies carry `60.00`, `0.50`, `100.00`.
- Unrouted paths/methods return the standard error envelope with `ERR_INVALID_REQUEST` at 404/405 (PRD declares no generic route error).

## Step 5: Generate unit tests — 2026-09-06T06:33:39.763663073Z

Step 5 complete. Both output dirs are at the task root, all eight fan-out agents finished, and every file's size has stabilised.

**`test_helpers/` — 9 files, 3856 lines** (Stage 1)
`__init__.py` 59 · `api_client.py` 541 · `api_errors.py` 176 · `assertions.py` 524 · `constants.py` 186 · `factories.py` 591 · `fixtures.py` 1123 · `test_users.py` 120 · `types.py` 536

**`test_suite/` — 9 files, 9416 lines** (Stage 2)
`conftest.py` 47 · `test_01_corner_entities.py` 1404 · `test_02_corner_state_machines.py` 867 · `test_03_corner_calculations_and_endpoints.py` 1251 · `test_04_corner_validations.py` 1451 · `test_05_corner_errors_rbac_consistency.py` 1101 · `test_06_difficulty_variants_formulas_state.py` 1058 · `test_07_difficulty_cascades_priority_boundary.py` 1169 · `test_08_difficulty_cross_entity_temporal_invariant.py` 1068

**Tests: 190 functions / 214 collected items** (`pytest --collect-only` clean, `py_compile` clean).

**Queue A (Difficulty): 20/20 instances translated, 40 tests** — every instance got exactly 2, meeting the >=2 quota across all 9 rules.
**Queue B (Corner): 38/38 non-stub instances translated, 150 tests** — entities 39, state_machines 15, calculations 5, validations 47, endpoints 9, errors 15, rbac 14, cross_cutting 3, consistency 3. All 28 `excluded_because:` stubs emitted nothing.

**SKIPPED instances: none.** One sub-claim was skipped on PRD-first grounds (no weakening, no xfail): the `both_occ_rules_...` claim that replaying a used `expected_case_version` on `POST /cases/{id}/informal-resolution` yields 412 — §2.9 rank 23 runs after every state check, so the PRD uniquely derives `ERR_CASE_STATE_INVALID` there. Two further sub-claims were dropped for C2 failure (severity-read `version` stability, which §2.5 + §4 leave undetermined; and a filter-`404` on an unknown `student_id` query param, which the PRD never states).

**Audit results:** every docstring carries exactly one `Design:` line, it is the last docstring line, and all 190 tags resolve verbatim to a real non-stub instance in the correct rule/section. No duplicate test names, no double `["data"]` unwraps, no whitespace-as-blank auth headers, no reference to `workspace/implementation/` or any sibling task. `.scratch/step4` was left intact; only `.scratch/step5` was removed.

**Three fixture defects the subagents surfaced, which I verified against the PRD and fixed centrally in `test_helpers/`:**
1. `factories.student_payload` sent `class_year: 2027`; PRD §3.2 requires "a `class_year` from 1 to 8" -> now `3`. This would have failed **every** `create_student`, cascading a setup-error wipeout across the whole suite in Step 7 iteration 1.
2. `factories.unique_course_offering_payload` minted `CRS-0001`; §3.2 requires 2–6 uppercase letters + hyphen + **three** digits -> added `unique_course_code()` yielding `CRS-001`.
3. `fixtures.create_faculty` asserted exactly `201` on the training-completion POST; TrainingCompletion is not a declared entity and §4's 201/200 rules both plausibly apply, so the setup helper no longer pins a status the PRD doesn't derive.

Four agents independently reported (1) and three reported (2) before I patched them, so the fixes are corroborated rather than speculative; the last agent to run confirmed both literals as PRD-conformant post-fix.

**Orchestrator note on step ordering:** Steps 5 and 6 were launched back-to-back rather than in a single message, so Step 6 lost strict physical isolation from `test_suite/`. Mitigation: Step 6's prompt carried an explicit test-blindness prohibition, and it started before any `test_suite/*.py` existed (test_suite/ was empty until 05:53, by which time Step 6 had already written its core modules). Step 6 reported no reference to the test directories.

## Step 7: Run tests and iterate — 2026-09-06T07:05:09.771987675Z

All 8 rounds green. Final summary:

## Step 7 Summary — task_2991_academic_integrity_case_adjudication

**Iterations run:** 2 sweeps (iteration 1 diagnostic, iteration 2 verification).

**Final sweep (results.1.json .. results.8.json, left in `workspace/implementation/`):**
```
round 1: 214/214   round 5: 214/214
round 2: 214/214   round 6: 214/214
round 3: 214/214   round 7: 214/214
round 4: 214/214   round 8: 214/214
```
Iteration 1 was 197/214 in **all 8 rounds** — 17 fully deterministic failures, zero load-induced flakiness.

**Tests deleted:** none. No test was PRD-silent or non-derivable end-to-end; every failure resolved to a test-artifact or test-vs-PRD-consistency defect.

**Fixes to `test_suite/` (file, test, why):**
- `test_04_corner_validations.py` — `_session_payload` helper (feeds 9 tests: lapsed chair, reporter-on-panel, too-few panelists, duplicated panelist, chair-among-panelists, start-after-end, <15 min, >4 h, non-whole-minute): merged `**overrides` into a keyword dict before calling `factories.hearing_session_payload`, so an override of `chair_id`/`panelist_ids`/`start_at`/`end_at` replaces the default instead of raising `TypeError: got multiple values for argument`. Pure test-artifact bug, no HTTP request behind it.
- `test_04_corner_validations.py::test_screening_an_appeal_twice_is_refused` — first screening changed from `ACCEPT_FOR_REVIEW` to `DENY_NO_GROUNDS`, which PRD §3.9 says "leaves the case's `adjudication_status` untouched". The old setup left the case in `APPEAL_UNDER_REVIEW`, which trips rank 13 (`ERR_CASE_STATE_INVALID`) — and §2.9 puts rank 13 ahead of rank 20 — so the test was demanding an error the ladder forbids. The denial keeps the case in `SANCTION_IMPOSED`, isolating the rank-20 `ERR_APPEAL_STATE_INVALID` gate under test.
- `test_06_difficulty_variants_formulas_state.py::test_returned_report_cannot_be_resubmitted_without_fresh_evidence` — clock advanced to 2026-08-03 before the `RETURN_FOR_INFO` triage. Previously the evidence and `returned_at` shared the T0 instant, and PRD §2.4 makes every window "inclusive at both ends unless ... strictly", so the pre-existing item legitimately counted as "added since `returned_at`". Now the stale item sits strictly before the return.
- `test_06...::test_remand_unwinds_the_decision_and_reopens_the_hearing_loop` — two fixes: (a) `pre_appeal_adjudication_status` was read off the **Appeal** row (`KeyError`); PRD §3.9 puts it on the **Case**; (b) the `kind=REHEARING_NOTICE` filter was passed to the case sub-resource listing, which PRD §4 describes only as a "listing of a case's notices" — the `kind` filter is declared on the global `GET /integrity/notifications`. Switched to the global list.
- `test_02_corner_state_machines.py::test_notation_walks_pending_posting_to_expunged_through_one_denial` — asserted `transcript_notation == "POSTED"` after an expungement denial. PRD §3.2 derives it strictly as "`POSTED` when any of the student's cases has `notation_status` `POSTED`, otherwise `EXPUNGED` ... otherwise `NONE`"; the only case has left `POSTED` for `EXPUNGEMENT_REQUESTED`/`EXPUNGEMENT_DENIED`, so `NONE` is uniquely determined. Rewritten to capture the value before the decision and assert §3.10's actual claim — that the denial leaves it *unchanged* — plus the §3.2-derived `NONE`.
- `test_08_difficulty_cross_entity_temporal_invariant.py::test_a_fresh_training_completion_reopens_the_submit_the_lapse_had_closed` — dropped the hard `201` on `POST .../training-completions`. A TrainingCompletion is not one of the resource types PRD §2.6 enumerates, so §4's "new distinct resource in a collection -> 201" and "derived-field recomputation -> 200" both plausibly apply; switched to `get_success_data` (any 2xx), matching the deliberate choice already made in `fixtures.create_faculty`.
- `test_08...::test_a_replayed_completion_reports_the_case_state_error_and_releases_nothing_twice` -> renamed `...reports_a_state_error...`; error id relaxed to `validate_error_is_one_of([ERR_CASE_STATE_INVALID, ERR_SANCTION_STATE_INVALID])` plus an explicit 409 check. PRD §3.8 names exactly two gates for `complete` — "any other status is `ERR_SANCTION_STATE_INVALID`" and "No appeal ... `SUBMITTED` or `UNDER_REVIEW`, otherwise `ERR_CASE_STATE_INVALID`" — so reading rank 13 as *only* that appeal condition (rank 19 wins) and reading the terminal `CLOSED` case as inadmissible (rank 13 wins) are both faithful. The design claim under test — the untouched store, counters and ledger — is fully preserved.

**Fixes to `test_helpers/`:**
- `api_client.py` — added `_allow_whitespace_only_headers` and an `ApiClient._request` override that suspends `requests.models.check_header_validity` for header values that are entirely whitespace. `requests` refuses client-side to serialise a value with leading whitespace, so the two PRD §2.1 probes for an `X-User-Role`/`X-User-ID` "consisting only of spaces" (`test_whitespace_only_role_header_is_unauthenticated`, `test_entity_backed_role_with_whitespace_user_id_is_unauthenticated`) could never leave the test process. Validation is never bypassed for values containing CR/LF and is always restored.
- `fixtures.py` — `schedule_hearing` now merges `**overrides` into a keyword dict before calling `hearing_session_payload`, closing the same latent positional/keyword collision.

**Fixes to `implementation/`:** **none.** No implementation defect was found; all 17 failures traced to test artifacts or test assertions that a faithful PRD-only implementer could not be required to satisfy. No endpoint, field, side effect or seeded data was added; storage remains in-memory only.

**Housekeeping:** `.scratch/step7/` removed (sibling `.scratch/step4/` untouched); no stray servers; `worklog.md`, `PRD.md`, `INSTRUCTION.md`, `sweep.sh` and `SCAFFOLD*.yaml` were never written.

**Orchestrator verification:** independently read all 8 `results.$i.json` files after the sentinel appeared — every round reports `passed: 214, total: 214`, confirming the subagent's claim rather than taking it on trust. Iteration-1 results were also independently confirmed at 197/214 in all 8 rounds before diagnosis began.

**Step 8 decision:** the skip condition requires all four counters at zero. Step 7 made 0 deletions and 0 `implementation/` fixes but 7 `test_suite/` fixes and 2 `test_helpers/` fixes, so Step 8 runs. Several of those fixes are genuine PRD-silence signals worth pinning (the `complete` gate precedence between rank 13 and rank 19, the training-completion success status, the §3.2 notation derivation after an expungement denial, and the `kind` filter's scope), which is exactly what Step 8 exists to close.

## Step 8: Finalize PRD — 2026-09-06T07:15:57.497093486Z

Step 8 complete.

**Line counts:** PRD.md 569 -> PRD_FINALIZED.md 571 (+2 lines, +0.35%). Nothing removed; 6 lines revised in place, 1 paragraph (2 lines incl. blank) inserted. Tail byte-identical to PRD.md (ends at the §5 error-catalogue table). `diff` shows exactly 7 hunks, all intended.

**Changes**
- §2.2 Error envelope — insert — unrouted path -> `ERR_INVALID_REQUEST` at 404, unaccepted method -> `ERR_INVALID_REQUEST` at 405, overriding §5's 400 for that id — `implementation/app.py:46-64`
- §3.1 Faculty training — revise — `POST .../training-completions` answers `200 OK` with the recomputed `FacultyMember` as `data`, an explicit exception to §4's 201 rule; completion rows have no read of their own — `implementation/routes_admin.py:205-220`
- §3.3 Report resubmission — revise — freshness boundary is inclusive (`created_at >= returned_at`); null `returned_at` imposes no requirement — `implementation/routes_reports.py:147-149`
- §3.5 Official notices — revise — `case_id`/`kind`/`acknowledged` belong to the global listing only; the per-case listing ignores those params rather than rejecting them — `implementation/routes_cases.py:493-500` vs `503-518`
- §3.8 Imposition cascade — revise — both rank-13 case conditions (`adjudication_status`, formal-route `RESPONSIBLE`) precede the rank-19 sanction-status check, which is `PROPOSED` on `DECIDED` / `ACCEPTED` on `INFORMAL_ACCEPTED`; also notes the component-scores guard (rank 34) is evaluated before the `effective_from` guard (rank 44) despite prose order — `implementation/routes_sanctions.py:148-177`
- §3.8 Completion — revise — the open-appeal test is the whole rank-13 case condition and precedes the rank-19 `IMPOSED` test; `adjudication_status` is not a guard, so a replayed completion reports `ERR_SANCTION_STATE_INVALID` — `implementation/routes_sanctions.py:180-201`
- §3.9 Reducing the sanction — revise — replacement row copies `effective_from`, carries null `grade_component_code` even at grade-penalty ranks 2/3, three grade figures at 0.00 (no §3.8 grade arithmetic), null `completed_at`/`vacated_reason`, `imposed_at` = clock only when created `IMPOSED` — `implementation/routes_sanctions.py:363-390`

**Pre-edit NO-NEW-MISMATCH log**
1. §2.2 — (a) generic transport errors; (b) `app.py:42-69` all four `HTTPException` branches (404/405/400+415/other), every `fail()` callsite's use of `ERR_INVALID_REQUEST` at 400, §5 mapping line; (c) dropped a draft "the only place" universal because the `else` branch can echo other HTTP codes — wrote "stand in place of" instead.
2. §3.1 — (a) create-response status codes; (b) grepped every `created(`/`ok(` return across `routes_admin.py`, `routes_reports.py`, `routes_cases.py`, `routes_advisors.py`, `routes_hearings.py`, `routes_sanctions.py`; confirmed `record_training` is the sole POST-create returning 200; grepped `training-completions` for a GET (none); (c) framed as a scoped exception so the other 201 creates stay governed by §4.
3. §3.3 — (a) evidence freshness; (b) all four `returned_at` sites in `routes_reports.py` (init, submit filter, triage write) plus `evidence_complete` in `calc.py`; (c) added the null-`returned_at` clause to mirror the impl's `or` guard exactly.
4. §3.5 — (a) filter handling on a sub-resource listing; (b) `list_case_notices`, `list_notices`, `lookup.py:81-93 filter_rows` (unknown params ignored generally), `list_case_appeals`, `query_enum` (which *does* reject bad declared enums like `basis`/`pathway_basis`); (c) scoped the sentence to the notices sub-resource and said "has no effect" rather than any global claim about query params; noted pagination still applies.
5. §3.8 impose — (a) case-vs-sanction state precedence; (b) `impose_sanction`, `propose_sanction` (rank 13 on `DECIDED` only), `complete_sanction`, `screen_appeal`, `decide_appeal`, §2.9 ranks 13/19/34/44; (c) attributed ordering to §2.9 rather than restating a local rule, so parallel endpoints stay consistent.
6. §3.8 complete — (a) guards on completion; (b) `complete_sanction:180-201`, `calc.appeals_of_case`, `calc.expungement_eligible_at`, `cascades.recompute_department_of_case`; (c) said `adjudication_status` "is not itself a guard" instead of "the case is untouched" — completion does write `CLOSED`.
7. §3.9 reduce — (a) replacement-row field defaults; (b) the single `APPEAL_REDUCTION` creation site, `new_row` in `db.py`, `cascades.write_grade_figures` + `impose_cascade`, `calc.LADDER_KIND` (ranks 2/3 are grade-penalty), `calc.governing_sanction`; (c) scoped the arithmetic claim to the reduction itself so a later imposition of a `PROPOSED` replacement may still fill the figures.

Scratch: `.scratch/step8` removed; sibling `.scratch/step4` untouched. No other file modified.

**Orchestrator verification:** `cmp` confirms PRD_FINALIZED.md is not byte-identical to PRD.md, the diff is 7 hunks / 13 changed lines, and the tail still ends on a well-formed §5 table row.

## Step 9: Complete PRD — 2026-09-06T08:36:58.119094597Z

Step 9 was run as **four sequential passes over one shared PRD_COMPLETED.md**, partitioned by implementation module, with a fourth reconciliation pass. Rationale: a single-agent full-codebase scan of a 4271-line implementation against a 571-line PRD reliably runs out of working context and returns a PRD byte-identical to its input; module-partitioned passes each keep only their own slice in context. Pass 1 alone performed the `cp` from PRD_FINALIZED.md; passes 2–4 were explicitly forbidden to copy, and each verified that the earlier passes' hunks survived. Pass 4 exists because partitioned passes report cross-boundary contradictions rather than fixing them.

Partition: pass 1 = app/db/errors/util/response/middleware/shapes/lookup/serializers/routes_admin/routes_reports · pass 2 = routes_cases/routes_advisors/routes_hearings · pass 3 = routes_sanctions/calc/cascades · pass 4 = reconciliation + seam sweep.

**Totals: PRD_FINALIZED.md 571 lines -> PRD_COMPLETED.md 575 lines (+4 lines, 122,290 -> ~134k chars), 73 edits across the four passes, 60 diff hunks. Headings still 30 (no new sections), §5 error table still 72 rows, §4 endpoint table still 74 rows, file still ends on a well-formed §5 table row.**

### PASS 1 — infrastructure + department/faculty/student/report intake (20 changes: 15 ambiguity-pins, 5 mismatch-revisions)
- §2.1 — revise — ambiguity — "read-only" pinned to HTTP GET, so the POST clock endpoint still requires `X-User-ID` — middleware.py:60-66
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + 20 uppercase alnum; `api_request_timestamp` is the logical clock — response.py:40,46
- §2.2 — insert — ambiguity — pagination meta keys absent from non-list 2xx and from error bodies — response.py:60-66
- §2.2 — insert — ambiguity — non-JSON/non-object body -> ERR_INVALID_REQUEST 400; empty body = `{}`; the 7 bodyless writes ignore any body; parsing happens after auth — shapes.py:54-67, app.py:56
- §2.3 — insert — ambiguity — present-but-empty `limit`/`offset` rejected; offset past end yields an empty page with `has_more` false — response.py:98-122,73-86
- §2.3 — insert — ambiguity+mismatch — `created_at` ties broken by insertion order; filters are exact string equality; out-of-set filter values match nothing rather than 400; unknown query params ignored; only `basis`/`as_of`/`pathway_basis` reject; `acknowledged` accepts true/false/1/0 — db.py:90-96, lookup.py:81-107
- §2.4 — revise — **mismatch** — `monitoring_flag` and `reporting_rate_per_1k_submitted` are persisted, not re-derived on read; only `training_completion_pct` and `open_case_count` are live — serializers.py:36-39, calc.py:287-301
- §2.4 — insert — ambiguity — inbound instant grammar (space separator, 1-9 fractional digits, offset or bare = UTC); output always 3 digits + `Z` — util.py:37-78
- §2.4 — insert — ambiguity — clock endpoint returns 200 with `current_utc` only; unknown fields rejected — routes_admin.py:79-84
- §2.6 — insert — **mismatch** — sub-resource reads resolve the parent before the entire query string; only `training-completions` resolves the path id before the body; every other bodied write does shape first — routes_admin.py:208, routes_cases.py:426,452,473
- §2.6 — insert — ambiguity — all id-valued list filters 404 on unknown ids (enumerated); runs after rank 7; non-id filters never validated — lookup.py:81-93
- §2.7 — insert — ambiguity — two-decimal values render with both digits (`60.00`), counts bare, nullable decimals as `null` — response.py:20-29,54-57
- §2.9 r4 — insert — ambiguity — ownership skipped when the row is absent, so 404 answers instead of 403 — routes_reports.py:127-130
- §2.9 r5 — insert — ambiguity — optional `null` == omitted (feeds rank 6); no type coercion; unknown-before-missing is unobservable — shapes.py:189-199
- §3.1 — revise — **mismatch** — "recompute a department" rewrites exactly two persisted values; version advances only on real change; `training_status` filter uses the live status — cascades.py:132-134
- §3.1 — insert — ambiguity — faculty `full_name` 1-120; email rule and its rank-5 position; uniqueness exact and faculty-scoped — routes_admin.py:32-36,66-68
- §3.1 — insert — ambiguity — `module_code` free-form; `completed_at` after clock -> ERR_INVALID_REQUEST; member version advances on every accepted completion — routes_admin.py:205-218
- §3.1 — revise — **mismatch** — metrics read persists only rate+flag; version only on change; peer median computed after the persist; flag always keyed on the persisted SUBMITTED rate — routes_admin.py:126-162
- §3.2 — insert — ambiguity — student `full_name` 1-120, email rule student-scoped, `program_code` unpatterned — routes_admin.py:43-48
- §3.3 — insert — ambiguity+mismatch — `incident_at` future check precedes FK resolution; `reporter_id` ignored whatever its type; `earned_points` upper bound checked last yet answers ERR_INVALID_REQUEST — routes_reports.py:64-78
- §3.3 — insert — ambiguity — `similarity_pct` always present on evidence reads, `null` for non-similarity kinds; `triage_note` required on all three decisions with no length rule — serializers.py:118-127, routes_reports.py:35-38

### PASS 2 — case lifecycle, notices/advisors/meetings, hearings (25 changes: 16 ambiguity-pins, 9 mismatch-revisions)
- §2.9 r34 — revise — mismatch — `ERR_COMPONENT_SCORES_INCOMPLETE` endpoint list gained `POST /integrity/cases` — routes_cases.py:120
- §2.9 r26 — revise — mismatch — vote conflict covers reporter *and* offering instructor, not reporter only — routes_hearings.py:305
- §3.4 — revise — mismatch — `case_number` comes from a store-wide counter in creation order, not "`created_at` ascending"; legacy imports consume numbers; clock rewinds don't renumber — db.py `next_case_number`, routes_cases.py:98
- §3.4 — insert — ambiguity — legacy `decided_at`/`completed_at` rules are rank-5 shape checks evaluated before `report_id` resolves — routes_cases.py:142
- §3.4 — insert — ambiguity — a legacy import runs no assessment (all severity fields keep creation defaults) and its companion sanction's `origin`/`effective_from`/null and 0.00 defaults; response carries the case — routes_cases.py:152
- §3.4 — insert — ambiguity — INFORMAL-basis assessment response: uncapped `tier_rank`, band 1..capped rank, `required_panel_size` 3, `attorney_advisor_permitted` false, prior-history counters still visible — routes_cases.py:245
- §3.4 — insert — mismatch — the severity read persists recomputed fields but advances neither `updated_at` nor `version`, explicitly excepting §2.5 — routes_cases.py:241
- §3.4 — insert — ambiguity — `dismiss_reason` is 1..500 chars — routes_cases.py:36
- §3.5 — revise — mismatch — non-`ALLEGATION_NOTICE` `kind` is rank-5 `ERR_INVALID_REQUEST`; `MEETING_NOTICE`/`SANCTION_NOTICE` are raised by nothing at all — routes_cases.py:59, grep of `create_notice`
- §3.5 — insert — ambiguity — advisor requests have no case-state guard (any status, incl. CLOSED/DISMISSED) — routes_advisors.py:61
- §3.5 — insert — ambiguity — `decision_reason` is 1..500 and is discarded on `APPROVE` — routes_advisors.py:30,125
- §3.5 — insert — ambiguity — `DENY` leaves `reconfirmation_required` as it stands — routes_advisors.py:128
- §3.5 — insert — ambiguity — meeting booking has no ownership guard; stored `instructor_id` comes from the case's report — routes_advisors.py:139,152
- §3.5 — insert — ambiguity — both outcome restrictions report `ERR_NOT_RESOURCE_OWNER` (incl. office on HELD/NO_SHOW and reporter on CANCELLED), and are peeked before shape validation — routes_advisors.py:196
- §3.6 — insert — ambiguity — informal proposal's null `imposed_at`/`completed_at`/`vacated_reason`, 0.00 grade figures, null `replaces_sanction_id` when nothing superseded — routes_cases.py:348, cascades.py:54
- §3.6 — revise — mismatch — decline re-runs the whole assessment: adds `prior_upheld_count_at_assessment` and the two informal fields — routes_cases.py:397, calc.py:580
- §3.7 — revise — mismatch — a bad `adjudication_status` on scheduling is `ERR_CASE_STATE_INVALID`, not `ERR_CASE_PATHWAY_NOT_SET` — routes_hearings.py:100
- §3.7 — insert — ambiguity — `effective_vote_count` is derived per read, climbing as votes are cast — serializers.py `session_json`, calc.py:610
- §3.7 — insert — ambiguity — `cancel_reason` is 1..500 and is stored but never exposed on a session read — routes_hearings.py:36, serializers.py
- §3.7 — insert — ambiguity — convene checks the response window before the pending-advisor check — routes_hearings.py:197
- §3.7 — revise — mismatch — vote conflict includes the offering instructor and precedes the panel-membership test — routes_hearings.py:305
- §3.7 — revise — mismatch — deciding re-runs the full formal assessment (8 persisted fields), not three fields — routes_hearings.py:259, calc.py:580
- §3.7 — revise — mismatch — deciding recomputes the department per §3.1 (SUBMITTED rate + `monitoring_flag`), never "on the adjudicated basis" — cascades.py:124, calc.py:287
- §3.7 — insert — ambiguity — `adjourn_reason` is 1..500 chars — routes_hearings.py:38
- §3.10 — insert — ambiguity — `request_statement` 1..4000; `decision_reason` 1..500 and discarded on `GRANT` — routes_cases.py:50,459

Pass 2 deliberately left unpinned: the pre-rejection `expungement_eligible_at` rewrite (unobservable; pinning would contradict §2.9's byte-identical-on-rejection promise), `notation_request_statement` being nulled on success, and the stray rank-5/6 mention of `POST /integrity/panel-votes` — all three handed to pass 4.

### PASS 3 — sanctions, calculations, cascades (16 changes: 13 ambiguity-pins, 3 mismatch-revisions)
- §2.9 (r5/6) — revise — mismatch — dropped `POST /integrity/sanctions` from the rank-6 list, added `POST /integrity/appeals/{id}/screen`, added "and forbidden otherwise"; a sanction proposal's conditional `grade_component_code` is the rank-33 rule, so it never answers `ERR_INVALID_REQUEST` — routes_sanctions.py:79-90, 276-277, 322-327
- §2.12 — revise — mismatch — rank 4 `TRANSCRIPT_NOTATION_ONLY` is reachable by four routes (office band one rank above the recommendation, panel floor, appeal reduction, legacy import), not two — calc.py office_band + routes_sanctions.py:95-101
- §3.5 — insert — ambiguity — every side-effect notice takes the endpoint default: `response_window_days` 7 and a deadline exactly 7 days after its own `sent_at` — cascades.py:16-31
- §3.8 propose — insert — ambiguity — `effective_from` arbitrarily far in the future is accepted; `ladder_rank` 1..8 is a rank-5 shape bound so 0 or 9 answers `ERR_INVALID_REQUEST` — routes_sanctions.py:30, 91-93
- §3.8 hop one — insert — ambiguity — non-grade kinds leave all three grade percentages at 0.00; a `GRADE_PENALTY_ASSIGNMENT` with a null `grade_component_code` zeroes nothing, so adjusted equals baseline and delta is 0.00 — cascades.py:66-74, routes_sanctions.py:373
- §3.8 hop four — insert — ambiguity — the informal pair is rewritten too, and every sibling is written unconditionally: `updated_at`/`version` advance even when all eight recomputed values are identical — cascades.py:86-87
- §3.8 completion — insert — ambiguity — the department is also recomputed in the §3.1 sense, its `updated_at`/`version` advancing only when one of the two persisted metrics changes — routes_sanctions.py:200, cascades.py:124-129
- §3.9 filing — insert — ambiguity — the case row is not written by a filing, so `adjudication_status`, `updated_at` and `version` all stay put — routes_sanctions.py:228-240
- §3.9 screening — revise — ambiguity — `decision_reason` is 1..500 chars; one sent alongside an acceptance is accepted and then discarded — routes_sanctions.py:43, 291-296
- §3.9 denial — revise — ambiguity — a denial leaves the case row untouched altogether, not merely its `adjudication_status` — routes_sanctions.py:302
- §3.9 deciding — revise — ambiguity — `decision_reason` is 1..500 chars and is recorded whichever outcome is chosen — routes_sanctions.py:48, 352
- §3.9 reduction — revise — mismatch — strictly-below-governing rule, the same `ERR_REDUCED_RANK_INVALID` for a case with no governing sanction at all, and 1..8 as a rank-5 shape bound — routes_sanctions.py:49, 343-347
- §3.9 remand — revise — ambiguity — named the eight fields the re-run assessment rewrites, including the informal pair — routes_sanctions.py:398, calc.py `ASSESSMENT_PERSISTED_FIELDS`
- §3.9 remand — insert — ambiguity — of the two notices, `REHEARING_NOTICE` is created first and `APPEAL_OUTCOME_NOTICE` second — routes_sanctions.py:401, 421
- §3.9 overturn hop three — insert — ambiguity — department recomputed in the §3.1 sense exactly as on a completion — routes_sanctions.py:417
- §3.9 overturn hop four — insert — ambiguity — informal pair, unconditional sibling writes, and no `SANCTION_RECOMPUTE_NOTICE`, so the only notification an overturn creates is the `APPEAL_OUTCOME_NOTICE` — routes_sanctions.py:419, cascades.py:98

### PASS 4 — reconciliation + seam sweep (12 changes)
Work-list disposition:
1. **edited** — §3.4 now enumerates the case object's exact 27 non-system keys "and nothing else", and states the notified instant and the expungement denial reason are audit-only and unpublished; matching revisions at §3.5 and §3.10. `serializers.py:130-160` omits all three and nothing in the impl ever reads them back.
2. **edited** — §3.10: the expungement `request_statement` is validated then **discarded**, not retained (`routes_cases.py:444` assigns `None`; the key is never read). Two requests differing only in the statement give byte-identical case objects.
3. **no edit** — pass 2's reasoning verified: at `routes_cases.py:439-440` the recomputed value always equals the stored one (kept fresh by post_notation:415 and complete_sanction:196-197 whenever the notation is `POSTED`; the governing sanction cannot change afterwards because completion sets `CLOSED` and appeals cannot be filed from `CLOSED`), and `touch()` is not reached. Pinning it would falsely contradict §2.9.
4. **edited** — §2.9 rank 6's endpoint list is now exactly the five endpoints that raise `ERR_INVALID_REQUEST` conditionally (routes_reports.py:201/204, routes_sanctions.py:277, routes_sanctions.py:323/326, routes_advisors.py:120, routes_cases.py:454); `POST /integrity/sanctions` and `POST /integrity/panel-votes` removed, `adjourn_reason` re-classified as an ordinary rank-5 required 1–500-char string (routes_hearings.py:38).
5. **edited** — the rank-5/6 mention of `POST /integrity/panel-votes` was wrong, not merely stray: `severity_recommendation` is pinned to ranks 36/37 (routes_hearings.py:311-317), which never answer `ERR_INVALID_REQUEST`.
6. **edited** — §2.10 now describes the one backward move in the notation dimension: hop two sets `notation_status` to `PENDING_POSTING` regardless of the prior value (cascades.py:112-113), reachable via post -> remand -> re-hear -> re-impose. §3.8 hop two got a matching clause.
7. **no edit** — the three notification statements are mutually consistent and match `cascades.py`: `create_notice` has exactly 7 call sites, imposition raises only `SANCTION_RECOMPUTE_NOTICE` on siblings (cascades.py:99), `SANCTION_NOTICE`/`MEETING_NOTICE` are raised by nothing, and §3.9's overturn paragraph correctly notes `notify=False` (routes_sanctions.py:419).
8. `strict_slashes` — **pinned** in §2.2 (app.py:31 overrides Flask's default, so a fresh implementer would plausibly 404 or redirect). Duplicate-detection case sensitivity — no edit, §3.2 already says "judged by exact string equality" and every other unique key is uppercase-pattern-constrained. `module_code` empty string — no edit, §3.1 already says it carries no length or pattern rule.
9. **no edit** — both spot-checks confirm unreachability. `decided_at` is non-null in every state reaching routes_sanctions.py:91 and :173. `supersede_proposed` can never see two `PROPOSED` rows: every proposal supersedes its predecessors, and the appeal-reduction `PROPOSED` branch (routes_sanctions.py:375) is itself unreachable because `was_imposed` is False only for a `COMPLETED` governing sanction, which implies a `CLOSED` and unappealable case.

Seam-sweep findings:
- §2.9 ranks 40/41 — revise — internal contradiction — swapped the two bullets so the interval check (`ERR_MEETING_WINDOW_INVALID`) outranks the calendar conflict, matching §3.5's own "the window check outranks the conflict check" and the code — routes_advisors.py:154-159 (session ordering 39 < 40 still holds, routes_hearings.py:122-127)
- §3.7 Recording votes — insert — ambiguity — a vote read publishes exactly 5 fields beside `id`/`created_at`, with `severity_recommendation` always a key and explicitly null on the forbidding verdicts — serializers.py:241-249
- §3.7 Adjourning — insert — ambiguity — `adjourn_reason` *is* published on a session read, in deliberate contrast to the unpublished `cancel_reason` — serializers.py:233 vs routes_hearings.py:279
- §2.2 — insert — ambiguity — trailing slashes are not significant on any method — app.py:31
- Full serializer-vs-writer sweep across all 15 entities found no further promised-but-omitted or omitted-but-promised field. Every `calc.py` helper reached from `routes_cases.py`/`routes_hearings.py` (`interval_problem` 15–240, `room_buffer_conflict` closed vs half-open, `required_panel_size`, `quorum_required`, `panel_tally` lower-middle median, `governing_sanction` tie-break, `expungement_eligible_at`, `speaking_rights`, `ASSESSMENT_PERSISTED_FIELDS`) matches the PRD's formula prose, not just the caller's summary. Merged multi-pass paragraphs (§2.9 ranks 5/6, §3.5 notices, §3.10 deciding) re-read end to end and are coherent.

**Earlier-pass text overridden by pass 4:** only the flat "`EXPUNGED` is terminal" in §2.10 and §3.10 (original PRD_FINALIZED wording; §3.10's line also carried a pass-2 clause, which was preserved). It is not enforced — `cascades.py:112-113` overwrites any prior value and the reduce-then-remand-then-re-impose path reaches it. Both are now qualified as terminal for the registrar-and-student route only.

**Pass 4's judgement:** PRD_COMPLETED.md is free of silence or mismatch on every behavior reachable from the implementation. One knowingly-left gap, recorded rather than pinned: inbound instants with 7–9 fractional digits are truncated to microseconds before comparison (`util.py` `_DT_RE`/`fmt_dt`), unobservable through the 3-fractional-digit output and only distinguishable by a sub-microsecond boundary comparison.

### Orchestrator verification of Step 9
- PRD_COMPLETED.md is **not** byte-identical to PRD_FINALIZED.md (`cmp` differs; 60 hunks / 128 changed lines) — the failure mode where the scan silently never ran is ruled out.
- Structure intact: 575 lines, 30 headings (no new sections), 72 `ERR_` rows in §5, 74 rows in the §4 endpoint table, file ends on a well-formed §5 table row.
- `find -newer results.1.json` over implementation/, test_suite/ and test_helpers/ returns nothing: Steps 8 and 9 touched only the PRD documents, so the green 8-round sweep remains valid for the shipped implementation. Re-read all 8 results files at the end of the pipeline: 214/214 each.
- `.scratch/` removed in full and the `SWEEP_DONE` sentinel cleaned up; `worklog.md` exists only at the task root (no stray copies under workspace/).

---

**Note on entry order:** worklog.md is append-only, so entries appear in completion order, not step order. Step 6 (implementation) is recorded before Step 5 (unit tests) because the two ran concurrently and Step 6 finished first. No entry was ever overwritten or reordered.

**Pipeline outcome:** complete through Step 9. Final artifacts — SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files, 3856 lines), test_suite/ (9 files, 9416 lines, 214 collected tests), workspace/PRD.md (569 lines), workspace/PRD_FINALIZED.md (571), workspace/PRD_COMPLETED.md (575), workspace/implementation/ (17 modules + start.sh, 4271 lines, all 74 endpoints), and the final passing sweep's results.1-8.json at 214/214 each.
