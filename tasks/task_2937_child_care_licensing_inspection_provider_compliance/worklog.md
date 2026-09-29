# Worklog — task_2937_child_care_licensing_inspection_provider_compliance

## Step 1: Create task directory — 2026-09-05T18:49:22.186562535Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2937_child_care_licensing_inspection_provider_compliance and its workspace/ subdirectory. Index 2937 was pre-assigned by the orchestrating invocation; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-05T21:04:46.569250102Z

Scaffold generation for task 2937 is complete and lint-clean.

**Verdict block (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2937_child_care_licensing_inspection_provider_compliance/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2937_child_care_licensing_inspection_provider_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2937_child_care_licensing_inspection_provider_compliance/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    80
  §1.1 entities declared:     14
  §1.8 instances scanned:     27
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  1124

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Deliverables** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2937_child_care_licensing_inspection_provider_compliance/`)
- `SCAFFOLD.yaml` — 4677 lines. `domain_name: child-care-licensing-compliance`, `api_prefix: /licensing`. 14 entities (23 FKs), 11 state machines, 15 calculations, 59 validations, 68 error codes, 80 endpoints, 8 roles, 2 `concurrency_rules`, 3 segregation-of-duties rules. Complexity profile: topology `flat`, shape `cyclic`, role_model `segregation_of_duties`, consistency `immediate`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`. Contains neither design key.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2992 lines, single key `scaffold_difficulty_design`: 9 rule blocks / 27 instances — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 4, cross_entity_state_dependency 4, resource_temporal_overlap 4, compensating_invariant 2.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3667 lines, single key `scaffold_corner_design`: all nine guide sections, 76 instances (59 real + 17 stubs that cite a §1.8 instance via `excluded_because`): entities 12, state_machines 15 (4 stubs), calculations 11 (6 stubs), validations 9 (4 stubs), endpoints 5, errors 14, rbac 4, cross_cutting_complexity_layers 5 (3 stubs), consistency_model 1.

**Key design facts**
- Error coverage is closed: all 68 declared codes are triggered somewhere. The 14 `errors` instances plus the `rbac` and OCC instances cover the 16 codes no other section reached (auth trio, both stale-version codes, five `ERR_INVALID_*_STATE` codes, `ERR_UNRESOLVED_CRITICAL_VIOLATION`, `ERR_P1_CANNOT_BE_SCREENED_OUT`, `ERR_APPEAL_DEADLINE_PASSED`, `ERR_REPEAT_REFERENCE_INVALID`, `ERR_DUPLICATE_CHECK_TYPE`, `ERR_ACTIVE_ENFORCEMENT_BLOCKS_AMENDMENT`, `ERR_COMPLAINT_INSPECTION_REQUIRED`).
- Both `concurrency_rules` entries got their own real OCC instance; the CAP one exploits the fact that creating a plan itself bumps `Inspection.version`, so the second plan's pre-plan version is genuinely stale.
- Two lint fixes were needed at the end: list-endpoint captures (`GET /licensing/providers`, `GET /licensing/public-report-postings`) can't address `$.data.total_count` because the output is an array — moved to `$.data[0].id` plus prose assertions.
- `worklog.md` untouched; `.scratch/step2/` removed, parent `.scratch/` left in place.

**Orchestrator post-step action:** the scaffold generator copied the difficulty directive line ("Generate task harder than expert level!") verbatim into SCAFFOLD.yaml's `scenario:` key. Per the known leak hazard, the orchestrator stripped that single line from SCAFFOLD.yaml so it cannot reach PRD.md via Step 4. Re-verified: `grep -rn "harder than expert"` over the task dir returns nothing, and all three YAMLs still parse under yaml.safe_load.

## Step 3: Copy shared files — 2026-09-05T21:04:46.582772183Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T21:26:53.101852442Z

Step 4 complete.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2937_child_care_licensing_inspection_provider_compliance/workspace/PRD.md` — **519 lines / 122,840 bytes**. Ends cleanly at the final `ERR_ROSTER_CAPACITY_MISMATCH` row of the §5 table; no audit footer, no mid-sentence truncation. `worklog.md` untouched; `.scratch/step4/` removed, parent `.scratch/` preserved.

## Section list (in order)

- `# Child Care Licensing Compliance API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles`
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure *(verbatim from `section-2.2-response-structure.md`)*
  - 2.3 Pagination
  - 2.4 The Logical Licensing Clock
  - 2.5 Record Identity, Revision Counters and Optimistic Concurrency
  - 2.6 Scoring Precision and Rounding Discipline
  - 2.7 The Order in Which a Request Is Refused
  - 2.8 Segregation of Duties Across the Casework Chain
  - 2.9 Conserved Quantities: Points and Capacity Slots
  - 2.10 Cascades and Cross-Entity Consistency
  - 2.11 Path Resolution and Not-Found Semantics
- `## 3. Business Logic & Workflows` (9 subsections)
  - 3.1 The Regulatory Catalog and the Field Workforce
  - 3.2 Assembling a Provider Application: The Dossier, Its Rooms and Its People
  - 3.3 Clearance: Registry Checks, Disqualification Cascades and Waivers
  - 3.4 The Inspection Visit — Scheduling Through Finalization
  - 3.5 Citations, Point Assessment and the Two Compliance Scores
  - 3.6 Remediation: Corrective Action Plans and Violation Disposition
  - 3.7 Complaint Casework and Serious-Incident Reporting
  - 3.8 Licensure Decisions, the Enforcement Ladder and Appeals
  - 3.9 Amendments to the Licence Record and the Public Inspection Register
- `## 4. API Endpoints`
- `## 5. Error Code Catalogue`

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** 188 identifiers derived independently from the scaffold (all `entities[].fields[].name`, every endpoint `input` entry with `?` stripped, all 14 path params, plus `id`/`created_at`/`updated_at`/`version`); **0 missing** — every one appears verbatim in backticks. (Verification must strip ```json fences first; §2.2's code blocks contribute an odd number of backtick runs and desynchronise a naive pair regex, producing a false 182-missing result.)

**Contract 2 — Rule Coverage: PASS.** All 8 `roles[].name` present; all 3 segregation-of-duties rules, both OCC rules (`expected_provider_version`→`ERR_STALE_PROVIDER_VERSION`, `expected_inspection_version`→`ERR_STALE_INSPECTION_VERSION`, both 412, with the ChecklistItem no-`updated_at`/no-`version` exception), the 4-link transitive cascades, both dual-variant calculations, and all `applies_to` scopes narrated. All 68 `errors[].id` are mentioned in §2 or §3, not just the §5 table — four (`ERR_INVALID_ENFORCEMENT_STATE`, `ERR_INVALID_AMENDMENT_STATE`, `ERR_INVALID_INCIDENT_STATE`, `ERR_INVALID_POSTING_STATE`) initially appeared only in the table and were repaired with explicit origin-state paragraphs. §3 contains no pseudocode: 0 occurrences of `==`, `!=`, `&&`, `||`, `->`, `>=`, `<=`, ` AND `, ` OR `, `IF `, `FOR EACH`, and no fuzzy words ("approximately"/"roughly"/"conservatively"). 131 enum/state tokens checked, 0 real misses.

**Contract 3 — §3 Path Purity: PASS.** 384 distinct backtick tokens in §3; **0** start with `/`, none is a bare HTTP method, none is a method+path combination. The only slash token anywhere in §1–§2 is the `/licensing` prefix.

## Coverage counts

- **Endpoints: 80/80.** Every `endpoints[].path` appears in the PRD; §4 table has exactly 80 data rows and exactly 4 columns (Method, Path, Description, Authorized Role(s)). Method mix 49 POST / 30 GET / 1 PATCH.
- **Errors: 68/68.** Every `errors[].id` present; §5 table has exactly 68 data rows and exactly 2 columns (Error ID, HTTP Status Code). Statuses read from the scaffold's `http` key (not `http_status`).
- Heading hygiene: 0 spacing defects (fixed one missing blank line before the §3 heading).

## Scaffold self-contradictions resolved (implementer-visible choices)

`correction_due_date` follows §1.3 exclusively (no halving/1-day forcing); capacity amendment types are `CAPACITY_INCREASE`/`CAPACITY_DECREASE` with `requires_inspection` true only for `SITE_MOVE`, `AGE_GROUP_ADD` and positive-delta capacity changes; no invented `Provider.director_staff_member_id` field; `current_ladder_step` stated as the derived maximum plus each explicit override; `effective_capacity_delta` computed and stored at creation; promote-to-full baseline is `provisional_started_at` (noted equal to `licensed_at`); roster `supervision_compliant` reconciles the empty-room exemption with the four lead tests; provider point counters defined over `FINALIZED`-inspection violations only, with finalization noted as the moment points land.

**Orchestrator verification (truncation guard):** independently re-checked PRD.md against SCAFFOLD.yaml — all 80 declared endpoint paths and all 68 declared error ids are present; §4 table has 81 pipe rows (80 data + header) and §5 has 69 (68 + header); the file ends on a complete final table row, not mid-sentence. No regeneration needed. Leak scan for "harder than expert", "SCAFFOLD", "scaffold_difficulty", "scaffold_corner", "test_recipe" over PRD.md returns nothing.

## Step 6: Generate implementation — 2026-09-05T22:16:48.489813235Z

(Recorded ahead of the Step 5 entry: Steps 5 and 6 ran concurrently and Step 6 returned first. Its summary is pasted here verbatim on completion so nothing is lost; the Step 5 entry follows below.)

Step 6 complete. The implementation is in `/home/ubuntu/github/CodingPRD/tasks/task_2937_child_care_licensing_inspection_provider_compliance/workspace/implementation/`.

## Layout (`ls -la`)

```
implementation/
  app.py  auth.py  calc.py  clock.py  constants.py  derive.py  envelope.py
  errors.py  helpers.py  serialize.py  store.py  validate.py
  requirements.txt          (Flask==3.0.3)
  start.sh                  (-rwxrwxr-x, executable)
  routes/
    __init__.py  config.py  providers.py  staff.py  rosters.py  inspections.py
    violations.py  complaints.py  reports.py  caps.py  enforcement.py
    amendments.py  postings.py
```

## Module line counts (4,837 lines total, 25 modules)

| module | lines | | module | lines |
|---|---|---|---|---|
| derive.py | 438 | | routes/enforcement.py | 274 |
| serialize.py | 376 | | routes/amendments.py | 255 |
| routes/inspections.py | 336 | | routes/caps.py | 241 |
| routes/providers.py | 334 | | routes/staff.py | 235 |
| constants.py | 247 | | routes/reports.py | 211 |
| routes/complaints.py | 274 | | routes/rosters.py | 203 |
| calc.py | 175 | | routes/postings.py | 166 |
| validate.py | 161 | | routes/violations.py | 162 |
| routes/config.py | 159 | | clock.py | 123 |
| store.py | 92 | | errors.py | 90 |
| app.py | 86 | | envelope.py | 79 |
| auth.py | 67 | | helpers.py | 53 |

All 25 modules pass `python3 -m py_compile`.

## Endpoint coverage

Programmatic diff of `app.url_map` against `SCAFFOLD.yaml`'s `endpoints` list (path params normalised):

```
declared: 80   routed: 80
MISSING (declared but not routed): none
EXTRA   (routed but not declared): none
```

Nothing is unimplemented, and no endpoint exists that the contract does not declare. 12 blueprints cover all 14 entities, 11 state machines, 15 calculations, 59 validations and 68 error codes.

## start.sh contract

`start.sh` cds to its own directory, does a guarded `pip install` (skipped entirely when Flask already imports), then `exec python3 app.py` — foreground, no `&`, no nohup. `app.py` binds `host="0.0.0.0", port=int(os.environ.get("PORT", "10000"))`, `use_reloader=False`, `threaded=True`. Measured cold boot-to-first-200 on a fresh process: **0.61 s**, which is safe for `--isolation per-test-server` relaunching before every test.

## Smoke test

End-to-end script on a random high port (`PORT=$((20000 + RANDOM % 20000))`, killed by captured PID only — no `pkill` was ever used), ~45 calls, all matching expected status: clock set → provider create → checklist items → inspector → director + cleared checks → roster → submit-application → clear-checks → schedule/start/cite/submit/finalize → compliance-score → risk-assessment → CAP submit/review/complete → disposition → licence ISSUE → complaint intake/screen → posting create/post → late incident report → enforcement propose/issue/effectuate/appeal/appeal-decision → amendment create/decide → report review/close, plus negative cases. Final line: `SMOKE OK`, `smoke exit=0`.

Representative observed values: `assessed_points=4` for a MODERATE PRESCHOOL citation; `final=96.0 prelim=96.0 raw=4.0`; after verified correction `display_score=98.4 banner=NONE`; `license_number=LIC-07-0001 licensed_capacity=20`; complaint `priority=P1 due=2026-09-01T10:05:00.000Z`; late report `timeliness=LATE_REPORT late_violation=True`, cascade leaving `open=15 critical_open=1`; enforcement `basis=15 fine=37500 step=1`. CAP-reviewer segregation returned 403 for the conflicted supervisor and 200 for a clean one. Negative cases returned 401/401/404/400/422/400/422/405 as expected.

## No-seed / no-persistence verification

On a fresh boot, all 14 collection GETs return `response_type=array, total_count=0, limit=10, offset=0, has_more=false` with a valid `req_…` id and the default logical clock `2026-08-01T00:00:00.000Z`. No SQLite file, JSON dump, or `/tmp` cache is created — storage is 14 in-memory dicts in `store.py`.

Three notable contract readings worth flagging to Step 7, since near-certain tests hinge on them: CAP `complete` checks CAP state before covered-violation state, `effectuate` checks enforcement state before licence compatibility, and `DIRECTOR_CHANGE` approval mutates no staff record (no PRD field exists for a designated director, so minimal-surface applies). Cleanup done: `.scratch/step6` removed, siblings `step5`/`step7` untouched; nothing written outside `workspace/implementation/`.

## Step 5: Generate unit tests — 2026-09-05T23:24:41.799206598Z

(Ran concurrently with Step 6; recorded after it because the test generator returned second.)

Step 5 is complete. The test suite is finished at the task root: `/home/ubuntu/github/CodingPRD/tasks/task_2937_child_care_licensing_inspection_provider_compliance/{test_helpers,test_suite}/`. Nothing landed under `workspace/`, `worklog.md` was never touched, and `workspace/implementation/` was never read.

## Deliverables

**`test_helpers/`** (9 files, 2 494 lines): `__init__.py` 108, `api_client.py` 568, `api_errors.py` 185, `assertions.py` 385, `constants.py` 182, `factories.py` 411, `fixtures.py` 715, `test_users.py` 124, `types.py` 416.

**`test_suite/`** (conftest 68 lines + 18 test files, 9 258 lines, **157 tests**):

| file | lines | tests | source |
|---|---|---|---|
| test_01 … test_10 | 706/464/559/254/608/509/794/952/626/540 | 11/6/9/4/11/9/13/15/13/8 = **99** | queue A (§1.8) |
| test_11 entities | 744 | 12 | queue B |
| test_12 state_machines | 691 | 11 | queue B |
| test_13 calculations | 374 | 5 | queue B |
| test_14 validations | 248 | 4 | queue B |
| test_15 endpoints | 377 | 5 | queue B |
| test_16 errors | 1 048 | 14 | queue B |
| test_17 rbac | 462 | 4 | queue B |
| test_18 cross_cutting + consistency_model | 352 | 3 (2 + 1) | queue B |

## Coverage and verification (scripted, `.scratch/step5/t2937_check_tags.py`, `t2937_check_quotes2.py`)

- **Queue A: 27/27** difficulty instances → 99 tests. **Queue B: 58/59** non-stub corner instances → 58 tests (exactly one test per corner instance).
- 157 tests / 157 `Design:` tags, 1:1 per file; no unknown tags, no tags pointing at STUB instances, no duplicate Corner tags (Difficulty tags repeat legitimately — several tests per instance).
- All 157 embedded PRD quotations verified verbatim (whitespace-normalised, exactly one PRD match per fragment). This pass caught and fixed one reordered quote in test_11 §3.2.
- Every file `py_compile`s; `pyflakes` is clean across `test_suite/` (I removed 9 unused `import pytest` lines and one unused `assert_instant` import found in the sweep). No `skip`/`xfail` anywhere.

## Skipped instance (1)

- `Corner/validations/val_aggregate_validation_roster_sizes_exceed_requested_capacity_rejected` — the design asserts a refusal when roster sizes exceed requested capacity, but PRD §3.2 sums `approved_group_size`, which is pinned at 0 until the licence issues, so a compliant implementation returns 201. The PRD uniquely derives the *opposite* of the asserted outcome, so the instance was dropped rather than weakened.

## Design deviations worth knowing for Steps 6–9

- **Points land at finalization (PRD §3.5 line 218).** Several designs assert open points from citations on an `IN_PROGRESS` visit. Those setups were carried to `FINALIZED` first (test_16, test_17 shared-ops) or assert 0/0/0 where the design said 15.
- **Six corner recipes schedule at the exact clock instant** (`ERR_SCHEDULE_IN_PAST` per §3.4). Those tests keep the clock earlier and schedule into the future.
- **Fine arithmetic corrections:** PROBATION@30bp = 130625 (design said 125000); SUSPENSION@45bp = 274312.
- **Promotion gate ordering (§2.7):** the design's setup would report `ERR_INVALID_LICENSE_STATE`, so a passing ANNUAL was added to make `ERR_UNRESOLVED_CRITICAL_VIOLATION` the genuine answer.
- Other minor restructures: waiver payload carries `waiver_rationale` (shape before state); ownership test PATCHes `staff_assigned_count` instead of `enrolled_count`; CAPACITY_DECREASE filed while on PROBATION plus an added SITE_MOVE; the rbac shared-ops provider is created by the AgencyAdmin (PRD §4 lists it) while `fx.create_provider` elsewhere correctly sends no `X-User-ID`.

**Orchestrator verification:** `ls -d workspace/test_helpers workspace/test_suite` prints nothing (no stray copies under workspace/); `python3 -m compileall` clean over both directories; independent count confirms 157 test functions and 157 `Design:` tags (99 Difficulty + 58 Corner); `grep` for `pytest.mark.skip`/`xfail` across both directories returns nothing.

## Step 7: Run tests and iterate — 2026-09-05T23:55:44.337229534Z

Clean sweep achieved. All 8 parallel rounds: **157/157**.

## Summary

**Iterations run:** 3 (each a full 8-round parallel sweep).

**Round-by-round, final sweep:** rounds 1–8 all `157 passed / 157 total`, 0 failed, 0 errors, 0 skipped (~298 s per round).

**Tests deleted:** none. Every failure traced to a test artifact that mis-expressed a rule the PRD does state verbatim, so all six were fixed rather than dropped.

**Fixes applied to `test_helpers/`:** none — no shared fixture bug was involved.

**Fixes applied to `implementation/`:** none. No failure survived STEP 1/STEP 2; the implementation was PRD-faithful on all six.

**Fixes applied to `test_suite/`** (all absolute paths under `/home/ubuntu/github/CodingPRD/tasks/task_2937_child_care_licensing_inspection_provider_compliance/test_suite/`):

1. `test_08_cross_entity_state_dependency.py`, local helper `_half_cleared_provider_in_pending_review` — the setup created a `requested_capacity=20` provider with **no age-group roster**, so `submit_application` was correctly refused `ERR_CAPACITY_SLOT_IMBALANCE` and the two tests in `TestInspectionFinalizeRequiresProviderClearance` died in setup. Added a PRESCHOOL roster with `requested_group_size=20`, per PRD §3.2 ("the provider must have at least one age-group roster… the sum of the `requested_group_size` values… must equal the provider's `requested_capacity` exactly").

2. `test_13_calculation_recipes.py`, `test_attaching_and_then_clearing_one_assistant_flips_the_flag_twice` — asserted a cleared ASSISTANT is `supervision_eligible is False`, which directly contradicts PRD §3.2 ("A person is `supervision_eligible` exactly when their `clearance_status` is `CLEARED` and their `member_type` is `DIRECTOR`, `LEAD_TEACHER` or `ASSISTANT`"). Flipped to `is True`.

3. `test_15_endpoint_surfaces.py`, `test_going_on_leave_blocks_new_scheduling_and_nothing_else` — compared the post-leave inspector `version` against a baseline captured at registration, two operations earlier. Scheduling a visit legitimately advances the inspector row (`scheduled_visit_count` is a row field; PRD §2.10 bumps `version` on any cascaded field change), so the baseline is not PRD-derivable. Now re-reads the inspector immediately before the leave change, which is the exact expression of "Every leave-status change increments the inspector's `version`."

4. `test_15_endpoint_surfaces.py`, `test_promotion_waits_for_the_six_months_and_the_passing_annual_visit` — two problems. (a) Expected `provisional_started_at == 2026-08-05T09:00:00Z` (the visit instant) where PRD §3.8 stamps it "with the current instant" of the ISSUE decision, which the licensing walk takes at the unmoved clock; corrected to `DEFAULT_LOGICAL_CLOCK`. (b) The premature-promotion attempt violated **two** preconditions at once (period not elapsed *and* no finalized ANNUAL visit), and PRD does not uniquely order them — §3.8's prose lists the period first while §2.7's generic order puts state checks before temporal rules, so `ERR_INVALID_LICENSE_STATE` is an equally faithful answer. Rather than relax the error assertion, the setup now finalizes the passing ANNUAL visit first (inside the provisional period) so the period rule is the sole violation, and the success case now promotes at exactly `provisional_started_at + 6 months`, which also exercises the inclusive lower edge the docstring quotes.

5. `test_17_role_matrix.py`, `test_seven_cross_role_attempts_are_all_unauthorized` — two problems. (a) Compared the provider `version` against a baseline captured before `attach_staff`, which PRD §3.2 says "increments the provider's `version`"; now reads the baseline after the dossier is assembled. (b) Asserted `after_check["result"] is None`, but `result` is only an *input* to the record-result action and PRD §3.3 never names it as a stored/response attribute of a BackgroundCheck (computed-field silence); swapped for `decided_at is None`, which PRD §3.3 does declare null at creation and stamped on a recorded result — same intent, verbatim coverage.

**Notable non-findings:** no flakiness at all (the failure set was byte-identical across all 8 rounds in every iteration), no load-induced timeouts, and no `test_helpers/` defect — unusual for this benchmark, and worth noting that `api_client.py`'s instant canonicalisation and money/type handling were already correct.

**Orchestrator verification:** independently re-read all 8 `workspace/implementation/results.$i.json` (all mtimes 23:45, sizes ~54.8 KB, per-round duration ~282 s): every round reports `passed=157, failed=0, total=157, errors=0, skipped=0`. Test-function count is still 157, confirming the reported zero deletions. `grep` for `mark.skip`/`xfail` across `test_suite/` and `test_helpers/` returns nothing. `grep` for `sqlite3` / file-write / `json.dump` across all implementation modules returns nothing, confirming in-memory-only storage.

**Step 8 gating decision:** NOT skipped. The skip condition requires zero deletions AND zero `test_suite/` fixes AND zero `test_helpers/` fixes AND zero `implementation/` fixes. Deletions, `test_helpers/` and `implementation/` fixes were all zero, but there were six `test_suite/` fixes, at least two of which (item 4b's promotion-precondition ordering and item 5b's `result` computed-field silence) are genuine PRD under-determination rather than pure fixture slips. Step 8 therefore runs, with this entry handed over verbatim as `<step_7_diff>`.

## Step 8: Finalize PRD — 2026-09-06T00:05:03.157688985Z

PRD_FINALIZED.md is written. Sibling scratch dirs (`.scratch/step5`, `.scratch/step7`) untouched.

**Line counts:** PRD.md 519 → PRD_FINALIZED.md 519 (0.0% line delta; 3 lines revised in place, +404 bytes / +0.33%). Tail verified: still ends with the complete §5 table whose last row is `ERR_ROSTER_CAPACITY_MISMATCH`.

**Changes (3):**
- §3.8 (Promotion to full licensure) — revise — the five precondition clauses are reordered to the order the implementation actually evaluates them (PROVISIONAL state → passing in-period `FINALIZED` `ANNUAL` inspection → `critical_open_count` → 6-month period → `open_violation_points`) and declared normatively ordered; PRD prose previously listed the temporal period second, so a request violating both the period and the annual-inspection rule was not uniquely determined — `implementation/routes/providers.py:237-276`.
- §3.4 (Scheduling a visit) — insert — spells out that the `scheduled_visit_count` bump is a change to the inspector row and therefore advances the inspector's `version` in the same request — `implementation/routes/inspections.py:147` → `implementation/derive.py:218-228`.
- §3.3 (Recording a registry result) — insert — states that `result` is an input only, never stored on the check and never present in the check's representation (the outcome lives in `status`) — `implementation/serialize.py:118-136`, `implementation/routes/staff.py:141-185`.

**Per-edit pre-edit search log:**

1. §3.8 promotion ordering. (a) Subject: promote-to-full precondition evaluation order and `provisional_started_at` semantics. (b) Enumerated/read: `routes/providers.py` `promote_to_full` (only writer of the transition), `license_decision` ISSUE branch (the sole stamper of `provisional_started_at`, `routes/providers.py:208-212`), `restore_full` (the parallel `license_status` mover, to be sure I did not describe its looser point test), grep for `provisional_started_at` / `PROVISIONAL_PERIOD_MONTHS` / `"PROVISIONAL"` across `routes/`, `derive.py`, `calc.py`, `constants.py` (only hits: providers.py + `constants.py:207`), and PRD §2.7's generic ladder to confirm the new order (state → safety → temporal → fiscal) does not contradict it. (c) Adjustment: phrased the order claim as "the first one listed here" rather than re-stating §2.7's category names, so it neither restates nor narrows §2.7; every clause's own wording is left verbatim, only their sequence changed.

2. §3.4 inspector `version` on scheduling. (a) Subject: mutations of the `Inspector` row's `scheduled_visit_count`/`version`. (b) Enumerated/read: `routes/inspections.py` schedule (`derive.recompute_inspector_visit_count` at :147), `derive.recompute_inspector_visit_count` (`derive.py:218-228` — touches the inspector **only when the recomputed count differs**), `derive.void_inspection` (`derive.py:284-295`, the recompute-after-void path), `routes/config.py:152-159` leave-status (always touches), and grep for `scheduled_visit_count`/`touch(inspector` across `routes/`, `derive.py`, `store.py`. (c) Adjustment: confined the sentence to the scheduling path (where the count always changes by +1) and did not add any version claim to §3.4's void sentence or §3.1's count definition, because a no-op recompute leaves the inspector's `version` alone — a universal "recomputing the count bumps the version" would have been a new mismatch.

3. §3.3 `result` not stored. (a) Subject: the `BackgroundCheck` field set / representation and the `result` input. (b) Enumerated/read: `serialize.py:118-136` (`CHECK_FIELDS`, no `result`), `routes/staff.py:101-114` (creation record keys), `routes/staff.py:141-185` (record-result: `result` only branches, never assigned to the record), `routes/staff.py:188-234` (waiver and waiver-decision, which also move only `status`/timestamps), plus a repo-wide grep for `"result"`/`'result'` (remaining hits are the corrective-action-plan `result` input in `routes/caps.py`, which likewise is not persisted under that name). (c) Adjustment: scoped the sentence explicitly to the check (`a field of the check`, `the check's representation`) instead of a general "inputs are never stored" claim, so the CAP `result` input and other action inputs are untouched by the wording.

**Items deliberately not patched** (PRD already determines the behavior verbatim, so they were pure test-artifact bugs): item 1 (roster sum must equal `requested_capacity`, §3.2), item 2 (`supervision_eligible` for a cleared `ASSISTANT`, §3.2), item 4a (`provisional_started_at` stamped with the ISSUE decision's current instant, §3.8), item 5a (`attach_staff` increments the provider's `version`, §3.2).

**Orchestrator verification:** PRD_FINALIZED.md is 519 lines / 123,244 bytes vs PRD.md's 519 / 122,840 (+404 bytes). A line-level diff confirms exactly three lines differ (166, 182, 297) — consistent with the three reported in-paragraph revisions and with "no new sections". The file still carries 28 headings and all 68 `ERR_` table rows, and ends on the complete `ERR_ROSTER_CAPACITY_MISMATCH` row, so it is not truncated.

## Step 9: Complete PRD — 2026-09-06T00:41:03.723794692Z

**Orchestrator decision (recorded per the autonomy directive):** a single subagent scanning 4,837 lines of implementation across 25 modules reliably under-covers, and the known failure mode is a PRD_COMPLETED.md that comes back byte-identical to its source because the scan never really ran. Step 9 was therefore executed as **three sequential module-partitioned passes over one shared PRD_COMPLETED.md**. Pass 1 owned the initial `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden from re-copying (a second `cp` would have destroyed the previous pass's edits). Partition: pass 1 = cross-cutting layer (app/envelope/auth/errors/clock/store/helpers/constants/serialize) + config/providers/staff/rosters → §2.1–§2.11, §3.1–§3.3, provider-side §3.8; pass 2 = inspections/violations/caps + calc.py/derive.py → §3.4–§3.6; pass 3 = complaints/reports/enforcement/amendments/postings + validate.py → §3.7, enforcement/appeal §3.8, §3.9, and a closing cross-pass consistency check.

**Net result: PRD_FINALIZED.md 519 lines / 123,244 bytes → PRD_COMPLETED.md 521 lines / 148,818 bytes (+25,574 chars, +2 lines). 69 edits total: 51 ambiguity-pins, 18 mismatch-revisions.**

### Pass 1 — cross-cutting + application/clearance domain (21 edits: 18 ambiguity-pins, 3 mismatch-revisions)

Initial copy performed (verified byte-identical at that moment via md5sum). 519 → 521 lines / 132,060 bytes (+8,816 chars, +2 lines, from one added paragraph in §2.11).

- §2.1 — insert — ambiguity — a whitespace-only `X-User-ID` is `ERR_UNAUTHENTICATED`, not just an absent/empty one — auth.py:19
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 uppercase-alphanumeric characters — envelope.py:20
- §2.3 — insert — ambiguity — `limit`/`offset` must be bare integer literals; out-of-range limit, negative offset or a non-integer is `ERR_INVALID_REQUEST` 400; list ordering ties on equal `created_at` broken by creation sequence — envelope.py:53-75, store.py:50
- §2.3 — insert — ambiguity — enum-valued query params (incl. `variant`) outside their set are `ERR_INVALID_ENUM_VALUE` 422; string filters match literally so `""` matches nothing; undeclared query params are ignored — validate.py:147-161
- §2.4 — insert — ambiguity — clock endpoint answers `{current_utc}` in the 3-digit form; instant inputs are ISO-parsed and normalised to UTC (offset accepted, no-zone read as UTC, sub-ms retained internally but rendered to ms, unparseable → `ERR_INVALID_REQUEST`); month arithmetic preserves day/time and clamps to month end — clock.py:18-41, 57-70, 109-114
- §2.5 — insert — ambiguity — every service-stamped instant uses the same 3-fractional-digit UTC rendering, so all are string-comparable — clock.py:57
- §2.6 — insert — ambiguity — 2-decimal scores travel as JSON numbers, not strings (`0.0` is a legal rendering of `0.00`) — serialize.py:8-11
- §2.7 — revise — ambiguity — request shape is three stages: unknown-key scan before required/type; enum stage across the whole body before any other constraint; explicit `null` == omission (cannot clear a stored value); no-input endpoints accept absent/empty/`{}` and treat any key as unknown; non-object body is `ERR_INVALID_REQUEST` — validate.py:50-118
- §2.9 — revise — mismatch — the three point balances are defined only over `FINALIZED` inspections, so a citation on an `IN_PROGRESS`/`PENDING_REVIEW` visit moves none of them (§2.9 previously implied citing itself moves the balances) — derive.py:131-133
- §2.11 — insert — ambiguity — unrouted path → `ERR_INVALID_REQUEST` 404, unsupported method → `ERR_INVALID_REQUEST` 405, trailing slash not significant — app.py:45, 53-62
- §5 — revise — mismatch — the "always with the HTTP status listed here" claim now excepts those two route-level refusals — app.py:53-62
- §3.1 — revise — ambiguity — every leave-status call bumps the inspector's `version`, including one restating the current status — config.py:157-158
- §3.2 — insert — ambiguity — `requested_capacity` below 1 is `ERR_INVALID_REQUEST`, above the ceiling is `ERR_CAPACITY_CEILING_EXCEEDED` — providers.py:35, 46
- §3.2 — revise — ambiguity — `date_of_birth` carries no range test (future dates accepted); `qualified_age_groups` is required but may be `[]` — staff.py:32-33
- §3.2 — insert — ambiguity — fixed order of the room tests: lead eligibility, ratio, group size, (creation only) age-band uniqueness, provider capacity last — rosters.py:69-88, 150-166
- §3.2 — insert — ambiguity — roster PATCH: omitted fields keep values, `null` cannot detach a lead, lead test applies only to a lead the request names — rosters.py:144-155
- §3.2 — insert — ambiguity — verify-ratio tests ratio→group-size→supervision in that order, and applies the named-lead test first whenever a lead is present even at zero enrolment — rosters.py:182-200
- §3.2 — insert — ambiguity — submission preconditions run in the listed order with the roster-to-capacity agreement last, after the ceiling test — providers.py:125-151
- §3.3 — insert — ambiguity — recording either registry result always bumps the provider's `updated_at`/`version`; the two waiver paths touch the provider only when the flip changes something — staff.py:184, 208, 234; derive.py:344-345
- §3.3 — insert — ambiguity — cascade link four also recomputes the provider's point counters, complaint counters, `risk_score` and `risk_tier`; and a granted waiver leaves the check's `disqualifying_offense_tier` in place — derive.py:342, staff.py:224-229
- §3.8 (provider-side) — revise ×4 — `decision_reason` stored only on DENY and discarded on ISSUE (providers.py:229); issuance re-derives all three flags plus `required_staff_count` per room and bumps each room's `version` (providers.py:213-216); **mismatch** — restore-full evaluates `critical_open_count` *before* `open_violation_points`, opposite to the PRD's listed order (providers.py:295-304); risk-assessment response shape pinned to the 7-field computed object with live-recomputed counters and nothing persisted (providers.py:320-333)

Pass 1 deliberately left unpinned: the `Exception`→500 fallback in app.py:69-71 (unreachable through documented behavior; documenting it would invite implementations to swallow real defects); §4's dangling "§1.3" cross-references (a documentation artifact, not an impl ambiguity); roster-creation's provider-capacity check being effectively a no-op (already entailed by the existing `approved_group_size` wording).

### Pass 2 — inspection / citation / remediation domain (22 edits: 15 ambiguity-pins, 7 mismatch-revisions)

Did NOT re-copy the file; pass 1's edits confirmed intact (§2.11 unrouted-path/405 paragraph present). 521 lines / 132,060 chars → 521 lines / 139,968 chars (+7,908).

- §3.4 — insert — ambiguity — full observable refusal order of a schedule request (windows → past-start → certification → ACTIVE → daily ceiling → complaint-reference rules last) — routes/inspections.py:69-122
- §3.4 — insert — ambiguity — `age_groups_observed` is tested against the inspector's certification only, never against `target_age_groups` — routes/inspections.py:219
- §3.4 — insert — ambiguity — finalization also refreshes the two 24-month complaint counters — routes/inspections.py:294
- §3.4 — revise — mismatch — "Both the inspection's and the provider's `version` advance" was exhaustive and wrong: the assigned inspector's row advances too (count drops leaving `PENDING_REVIEW`), and the provider is touched unconditionally — routes/inspections.py:302-304
- §3.4 — revise — mismatch — voiding leaves the provider row **untouched** (counters read only `FINALIZED`, so `recompute_provider_tracked` never bumps), and does not refresh the inspection's `violation_count`, `cap_required` or either stored score — routes/inspections.py:317-318, derive.py:284-295,431-438
- §3.4 — revise — mismatch — "Reads are open to every role" was false: intake specialist and background-check unit are excluded, the scoring read is admin/supervisor/inspector only, and no read applies an ownership filter — routes/inspections.py:20-27,151-178,324
- §3.5 — revise — mismatch — `infant_exposure`'s second disjunct cannot fire for an inspector's own citation (`age_groups_observed` is null throughout `IN_PROGRESS`); it bites only on cascade-written citations — derive.py:248-251, routes/inspections.py:244,263
- §3.5 — insert — ambiguity — the checklist item's `age_groups_applicable` is **not** enforced against `primary_age_group` — routes/violations.py:50-58
- §3.5 — insert — ambiguity — `severity_override` is echoed verbatim and null when absent; `severity` always carries the effective value — routes/violations.py:83
- §3.5 — insert — ambiguity — the repeat parent may sit on the same visit or any earlier visit of the provider, in any status — routes/violations.py:60-72
- §3.5 — revise — mismatch — `preliminary_compliance_score` is rewritten by every citation while the visit is open, then frozen at finalization — routes/violations.py:87
- §3.5 — insert — ambiguity — citing touches the provider row without moving any counter; plus the violation list/read filter set and role set — routes/violations.py:19-26,90-115
- §3.5 — insert — ambiguity — the scoring read's computed object (`variant`, `compliance_score`, `raw_deduction`, `violation_count`), its availability in any status, and that the FINAL `violation_count` counts vacated rows — routes/inspections.py:322-336, calc.py:44-63
- §3.6 — revise — mismatch — `correction_due_date` is a full three-fractional-digit UTC instant counted from the citation's own `created_at`, not a calendar date — derive.py:276-278
- §3.6 — insert — ambiguity — `vacated_reason` is 1–500 chars, its conditional requirement fires before the citation lookup, and it is discarded on the other two branches — routes/violations.py:131-138,148-152
- §3.6 — insert — ambiguity — disposition performs no ownership comparison, and the supervisor-only test precedes the origin-state test — routes/violations.py:127,140-146
- §3.6 — insert — ambiguity — every disposition advances both the inspection's and the provider's `version`, on every branch — routes/violations.py:157-161
- §3.6 — insert — ambiguity — `expected_inspection_version` is retained/echoed and never refreshed; `proposed_completion_date` is compared with nothing — routes/caps.py:91,101
- §3.6 — revise — mismatch — approval stamps `correction_due_date` on any moved citation, bumps the inspection only if something moved (in practice nothing does), and a rejection also stores the note — routes/caps.py:155-173
- §3.6 — insert — ambiguity — resubmission checks the window **before** the cycle allowance, touches neither inspection nor provider, and preserves `reviewed_at` / `reviewed_by_user_id` / `review_note` — routes/caps.py:184-201
- §3.6 — insert — ambiguity — either CAP result recomputes `violation_count` and the provider's whole counter set and bumps both versions; plan reads apply no ownership filter — routes/caps.py:19,108-129,236-240
- §4 — revise — ambiguity — `GET /licensing/violations` also filters by `status` and `severity` — routes/violations.py:99-114

Pass 2 deliberately left unpinned: per-endpoint refusal orders already determined generically by pass 1's §2.7 (re-stating them would duplicate); the §3.5 risk-assessment computed read (verified correct, and providers.py is pass 1's slice); `derive.auto_propose_enforcement`, `calc.fine_amount_cents`, `calc.display_score`, `calc.complaint_priority` and the cascade citation writers in complaints.py/reports.py (pass 3's subjects, relied on only as evidence); the void scope of the three system-initiated voids (already pinned in §3.3 link four, §3.8 denial sweep and revocation sweep); `calc.latest_finalized`'s tie-break and `derive.inspector_finalized_recently` (consumed only by pass-1/pass-3 endpoints).

### Pass 3 — complaint / incident / enforcement / amendment / posting domain (26 edits: 18 ambiguity-pins, 8 mismatch-revisions)

Did NOT re-copy the file; 26 in-place edits only. Passes 1 and 2 confirmed intact by marker greps (pass 1's §2.11 unrouted-path/405 paragraph, pass 1's §2.7 segregation-ordering sentence, pass 2's §3.6 `correction_due_date`-as-instant sentence — all return 1). 521 lines / 139,968 chars → 521 lines / 148,818 chars (+8,850). Structure unchanged: 28 headings, 68 `ERR_` rows, 152 total table rows, ASCII-clean.

- §3.7 — revise — mismatch — assignment applies the 12-month inspector-lookback segregation check *before* both the `SCREENED_IN` and inspector-`ACTIVE` state tests, matching §2.7's segregation-before-state ordering — routes/complaints.py:175-182
- §3.7 — insert — ambiguity — `AGENCY_INCIDENT` is a reserved channel: an intake submission naming it is `ERR_INVALID_ENUM_VALUE`, tested after body validation and before the anonymity rule and before the provider is resolved — routes/complaints.py:88-98
- §3.7 — insert — ambiguity — anonymous intake refusal is evaluated before provider existence, so an anonymous complaint against an unknown provider reports the anonymity error — routes/complaints.py:94-98
- §3.7 — insert — ambiguity — priority matrix pinned as category×severity with probation escalation applied after the base lookup, one rung only, never past P1 — routes/complaints.py + calc.py
- §3.7 — insert — ambiguity — `response_due_at` from screening instant + priority window; `determination_due_at` from DETERMINATION_DAYS P1=30/P2=45/P3=60 — routes/complaints.py:120-135
- §3.7 — revise — mismatch — a *non*-substantiated determination still recomputes and version-bumps the provider (previously implied only substantiation touched it) — routes/complaints.py:238-241
- §3.7 — insert — ambiguity — full four-link substantiation cascade ordering pinned: citation → provider counters + inspection score → auto-proposed enforcement only when points ≥ 30 and `current_ladder_step` < 2 — routes/complaints.py:200-241
- §3.7 — insert — ambiguity — substantiation with no FINALIZED inspection to hang the citation on completes with no citation and no cascade rather than refusing — routes/complaints.py:205-215
- §3.7 — insert — ambiguity — closure requires `DETERMINED`; `SCREENED_OUT` is terminal and not closable — routes/complaints.py
- §3.7 — insert — ambiguity — incident window table pinned per type and the deadline computed from `occurred_at`, not from receipt — routes/reports.py:53
- §3.7 — insert — ambiguity — `occurred_at` in the future is `ERR_INCIDENT_OCCURRED_IN_FUTURE`, checked before timeliness is computed — routes/reports.py:48-52
- §3.7 — insert — ambiguity — LATE_REPORT cascade is conditional on a latest FINALIZED inspection existing; RE-601 is resolved (404 `ERR_CHECKLIST_ITEM_NOT_FOUND` if absent) *before* the report row is created, so a missing catalog item aborts the whole filing — routes/reports.py:66-72, 90
- §3.7 — insert — ambiguity — the auto-cited late-report violation is CRITICAL with `severity_override` also CRITICAL, `CORRECTION_PENDING`, auto-generated, with a due date; `late_report_violation_created` true only when the violation was actually written — routes/reports.py:92-104
- §3.7 — insert — ambiguity — review dispositions: MONITOR forbidden for FATALITY/MISSING_CHILD; a non-MONITOR disposition generates a `P1`/`SCREENED_IN` `AGENCY_INCIDENT` complaint whose `screened_at` stays **null**, category ABUSE for FATALITY/SERIOUS_INJURY/MISSING_CHILD else RECORDS — routes/reports.py:167-183
- §3.7 — insert — ambiguity — close refuses while the generated complaint is neither `CLOSED` nor `SCREENED_OUT`, and that test precedes the report's own state test — routes/reports.py:193-205
- §3.8 — revise — mismatch — posting refresh is **unconditional on every effectuation** (warnings included), not revocation-only; `PENDING_REDACTION` and `WITHDRAWN` postings are skipped; `decide_appeal` never refreshes postings — routes/enforcement.py:200, 30-40
- §3.8 — insert — ambiguity — proposal consults only `open_violation_points`: no `license_status` gate and no uniqueness constraint, so multiple `PROPOSED` actions may coexist; `ERR_NO_ENFORCEMENT_BASIS` before `ERR_LADDER_STEP_SKIP`; a lower rung than recommended is allowed — routes/enforcement.py:59-71
- §3.8 — insert — ambiguity — `EFFECTUATION_LICENSE_STATES` table pinned per action type — routes/enforcement.py:22-27
- §3.8 — insert — ambiguity — ladder step uses `max()` for warning/probation/suspension but revocation hard-sets 4; suspension/revocation capacity-slot bookkeeping pinned — routes/enforcement.py:163-183
- §3.8 — insert — ambiguity — appeal requires `EFFECTIVE` and is owner-scoped; deadline is strict (`>` the deadline fails); VACATED restoration targets pinned per action type (SUSPENSION/REVOCATION → PROBATION/step 2, PROBATION → FULL/step 1, WARNING → step 0 with `license_status` untouched) — routes/enforcement.py:214-270
- §3.9 — revise — mismatch — attach-inspection order corrected to FINALIZED → amendment state → `inspection_type` → provider match (the referential-agreement mismatch answers **last**, not second) — routes/amendments.py:142-157
- §3.9 — revise — mismatch — approval guards ordered critical-open → active enforcement → capacity ceiling, and stated as observable — routes/amendments.py:184-205
- §3.9 — revise — mismatch — a DIRECTOR_CHANGE approval writes **nothing** to the provider (no director field on `Provider`); only the amendment's status/`decided_at`/`version` plus the provider's `version` bump are visible — routes/amendments.py:216-236
- §3.9 — insert — ambiguity — `requires_inspection` derived from delta sign (SITE_MOVE/AGE_GROUP_ADD always; capacity only when delta > 0); same-type supersession of open amendments; `expected_provider_version` OCC checked after ownership — routes/amendments.py:59-82
- §3.9 — insert — ambiguity — AGE_GROUP_ADD does not move `licensed_capacity` and is not ceiling-tested, so approved group sizes can exceed `licensed_capacity` (verified `ERR_ROSTER_CAPACITY_MISMATCH` is raised only in rosters.py) — routes/amendments.py:216-236
- §3.9 — revise — mismatch — publish order pinned as inspection FINALIZED → posting `PENDING_REDACTION` → open investigation → `redaction_complete`; the one-posting-per-inspection slot is never released even by withdrawal; a `WITHDRAWN` posting keeps its last `enforcement_banner` and `correction_count` while `display_score` goes null — routes/postings.py:40-46, 96-107, 161-164
- §4 — revise — mismatch — five endpoint rows' filter lists corrected/completed for complaints, reports, actions, amendments and postings to match the actual `validate.query_*` calls — routes/*.py list handlers

**Closing cross-pass consistency check — passed, with three genuine contradictions found and fixed minimally, all resolved in favour of §2.7 plus the implementation:**
1. §3.7 asserted state-before-segregation on investigator assignment while pass 1's §2.7 asserts segregation-before-every-state-precondition; impl agrees with §2.7. Fixed in §3.7.
2. §3.9's attach-inspection narrative claimed the provider-mismatch test ran second, contradicting §2.7's referential-agreement-last rule; impl agrees with §2.7. Fixed in §3.9.
3. §3.9's approval-guard prose listed the ceiling check before the active-enforcement check, contradicting its own §2.7-derived claim that safety precedes fiscal; impl order is critical → enforcement → ceiling. Fixed in §3.9.
No other cross-pass conflict: no version-bump, refusal-order, rounding or clock statement added by pass 1 or pass 2 is contradicted by anything in §3.7–§3.9 or §4/§5.

Pass 3 deliberately left unpinned: `validate.py` internals (fully pinned by pass 1 in §2.7/§2.3); intra-stage field iteration order inside `validate.body` (not externally observable — both orders surface the same `ERR_INVALID_REQUEST`); the `suspended_capacity < 0` guard at enforcement.py:198 (unreachable on that path; the reachable sibling at :252 is pinned); the 24-month complaint-counter window (already pinned by pass 2 in §3.5); `revision_note` overwrite-on-revise (already implied by existing §3.9 prose).

### Orchestrator verification of Step 9

- PRD_COMPLETED.md is 521 lines / 148,818 bytes and is **not** byte-identical to PRD_FINALIZED.md (146 differing lines by diff) — the known "the scan never ran" failure mode is excluded.
- All 80 declared endpoint paths and all 68 declared error ids from SCAFFOLD.yaml are still present; the §5 table still has 68 `ERR_` rows; the file ends on the complete `ERR_ROSTER_CAPACITY_MISMATCH` row, so no pass truncated it.
- No new sections were added (heading count unchanged); only two lines were added in total, both from pass 1's single §2.11 paragraph.
- `find` over `test_suite/`, `test_helpers/` and `workspace/implementation/` shows **no** `.py` file modified after the clean sweep at 23:45, so the verified 8×157/157 result still describes the shipped implementation and test suite. Steps 8 and 9 touched only PRD derivatives, as required.
