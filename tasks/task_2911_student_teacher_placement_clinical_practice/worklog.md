# Worklog — task_2911_student_teacher_placement_clinical_practice

## Step 1: Create task directory — 2026-09-05T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2911_student_teacher_placement_clinical_practice` and its `workspace/` subdirectory. Index 2911 was pre-assigned by the orchestrating caller (no scan of ./tasks/ performed, per instruction — concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-05T16:49:02.000Z

The scaffold is complete. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_2911_student_teacher_placement_clinical_practice/`.

**`SCAFFOLD.yaml`** (3000 lines) — `api_prefix: /epp`, domain "Student Teacher Placement & Clinical Practice", profile `expert_plus` / `quota_allocation` + `compliance_audit`, layers `selector_policy`, `cascading_side_effects`, `dual_variant_calculation`, `optimistic_concurrency`; flat topology, cyclic+parallel state machines, `segregation_of_duties` role model, immediate consistency.
- **10 entities**: District, Candidate, ReadinessItem, PartnershipAgreement, CooperatingTeacher, UniversitySupervisor, PlacementRequest, Placement, ObservationCycle, PerformanceAssessment.
- **8 state machines** (Candidate carries readiness x licensure x report dimensions; Placement carries clinical x stipend dimensions), **10 calculations** (readiness score with STRICT/ROLLING variants, commute/match ranking, supervisor caseload points, stipend settlement with PROVISIONAL/FINAL variants, tier-pinned travel reimbursement, agreement ledger, observation compliance ratio, teacher turnaround window, assessment total score, state-report timeliness), **48 validations** (priority ladder 1-48), **52 endpoints**, **55 error codes**, **7 roles**, **1 concurrency rule** (`reroute-supersede-stale-request`, `expected_request_version` -> `ERR_STALE_REQUEST_VERSION`).
- Two corrections made during design: `ERR_AGREEMENT_NOT_ACTIVE` (p15) was provably unreachable at confirm (the suspend/terminate cascade voids PROPOSED placements first), so it was re-scoped to also cover new ObservationCycle / PerformanceAssessment scheduling under a non-ACTIVE agreement; and `response_envelope.pagination_fields` was fixed from limit/offset to page/page_size to match every list endpoint's declared input.

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (2174 lines) — single key `scaffold_difficulty_design`: **9 difficulty rules x 2 differentiated instances = 18**, every literal (readiness 90/85/50, weekly 12962 -> 181468/103696/93234, travel 137886/78792/68943/53546/434763, assessment 100/71/70/69, dates 2026-12-07/2026-10-26/2027-01-21, caseload 2/3/4) executed and cross-checked against the scaffold's own formulas.

**`SCAFFOLD_CORNER_DESIGN.yaml`** (5400 lines) — single key `scaffold_corner_design`: all **9 guide sections** walked, **95 instances (68 with full test_recipe + 27 `excluded_because:` stubs)** — entities 11, state_machines 16, calculations 12, validations 12, endpoints 5, errors 26, rbac 6, cross-cutting layers 5, consistency model 2. Every stub cites a real §1.8 instance name; names are unique across both design files; **all 55 error codes have at least one asserting instance**.

Lint verdict (`scaffold_lint.py`, first run, no iterations needed):

```
Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     68
  Calls scanned (§1.8+§1.9):  1546

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

All three files `yaml.safe_load` cleanly; `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`. No sibling task directory was read at any point; scratch work stayed in `/tmp/task_2911_scaffold/`.

Orchestrator note: grepped the task dir for the phrase "harder than expert" — no leak into SCAFFOLD.yaml or elsewhere. Only `difficulty_level: expert_plus` metadata is present (scaffold-internal, not PRD-bound).

## Step 3: Copy shared files — 2026-09-05T16:49:22.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T17:10:10.000Z

PRD complete and verified.

**Deliverable:** `workspace/PRD.md` — **473 lines**, 113 KB.

**Section list**
- `# Student Teacher Placement & Clinical Practice API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Acting Principals and RBAC; 2.2 API Response Structure (byte-verbatim, incl. its two `####` sub-headings); 2.3 Pagination; 2.4 Resource Identity, Audit Fields and Immediate Consistency; 2.5 The Logical Clock; 2.6 Order of Validation (48 numbered rungs); 2.7 Numeric Precision and Rounding Discipline; 2.8 Deadline-Driven Lazy Transitions; 2.9 Conserved Quantities; 2.10 Optimistic Concurrency on Request Supersession; 2.11 Segregation of Duties; 2.12 Geometry, Intervals and Enumerations; 2.13 Parallel State Dimensions
- `## 3. Business Logic & Workflows` — 3.1 Admitting Candidates and Building the Readiness File; 3.2 Scoring the Readiness Gate: Two Variants; 3.3 District Partnerships: Seats, Money and the Subject Envelope; 3.4 The Clinical Bench; 3.5 Opening, Routing and Rerouting a Placement Request; 3.6 Confirming a Placement and Accruing the Provisional Stipend; 3.7 The Observation Calendar and the Compliance Ratio; 3.8 The Performance Assessment: Windows, Attempts and Scoring; 3.9 Removal, Settlement, Completion, Licensure and State Reporting
- `## 4. Endpoint Definitions` — intro paragraph on the 201-create / 200-everything-else rule (names all eleven 201 endpoints, including route/reroute) + **52 data rows**, exactly 4 columns
- `## 5. Error Code Catalogue` — **55 data rows**, exactly 2 columns

**Tail is a clean section boundary:** the file ends with the last row of the §5 table, no truncation mid-sentence. Last 5 lines verbatim:
```
| `ERR_SUPERVISOR_CASELOAD_EXCEEDED` | 409 |
| `ERR_PLACEMENT_CAP_EXCEEDED` | 409 |
| `ERR_PROVISIONAL_STIPEND_NOT_PAYABLE` | 422 |
| `ERR_NO_COMPLETER_RECORD` | 422 |
| `ERR_LICENSURE_NOT_RECOMMENDED` | 422 |
```

**Hard Contract 1 — Field-Name Coverage: PASS.** Two independent passes (139-identifier list, then a freshly recomputed 135-identifier set from entity fields + endpoint inputs + query filters): 0 missing. All 55 error identifiers, all 7 role names, all enum member strings, all 52 paths, and every calculation/validation constant *value* also present. No scaffold constant NAME leaked (`COMPLETION_PREMIUM_CENTS`, `TRAINING_VALID_DAYS`, `MAX_RESCHEDULES_PER_CYCLE` etc. all rendered as literal values in prose).

**Hard Contract 2 — Rule Coverage: PASS.** 48/48 validations as ordered rungs; the single concurrency rule in §2.10; 46/46 state-machine transitions across all 8 machines textually present (6 verified by hand where the prose omits the arrow glyph — one, `REMOVAL_PENDING -> REMOVED`, was given an explicit arrow during verification); 10/10 calculations with formulas, pinned rounding order and worked literals; all cascades stated hop-by-hop (the depth-4 upheld-removal and assessment-failure cascades); list filters now stated for all 10 list endpoints (placement filters were added during verification). Zero pseudocode operators, zero fuzzy words (`should`, `etc.`, `TBD`, `appropriate` — the one `should` found was rewritten to a determinate statement).

**Hard Contract 3 — §3 Path Purity: PASS.** 0 backticked spans in §3 containing `/` or beginning with an HTTP method; 0 bare `GET/POST/PATCH/PUT/DELETE` tokens anywhere in §3; 0 tables, 0 code fences and 0 bullet lists in §3 (the three per-item-type field bullets were folded into prose).

Scaffold inconsistencies resolved during authoring (baked in consistently): `preferred_district_id` treated as a hard eligibility filter per the ranking formula; `max_caseload_points` = min(employment-type figure, override); `accepting_new_placements` forced false by caseload re-derivation and never restored automatically; `observation_compliance_ratio` at 4 decimals half-up; §2.3 declares `page`/`page_size` while §2.2 stays verbatim; `MAX_ROUTING_ROUNDS` -> `ERR_REQUEST_STATE_INVALID`; expired-window activate/reactivate -> `ERR_AGREEMENT_STATE_INVALID`; duplicate `sequence_no` -> `ERR_INVALID_REQUEST`; clawback-without-disqualification and repeat licensure decision mapped to `ERR_STIPEND_STATE_INVALID` and `ERR_NO_COMPLETER_RECORD` respectively (both rungs edited so §2.6 and §3.9 agree). `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced; no sibling task directory was read; scratch stayed under `/tmp/task_2911_prd/`.

Orchestrator truncation check: independently confirmed `wc -l` = 473, tail ends on the final §5 table row (`ERR_LICENSURE_NOT_RECOMMENDED | 422`), §4 holds ~52 rows and §5 ~55 rows, and the heading list runs 1 -> 5 with no missing trailing section. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-05T17:50:02.000Z

Implementation complete. The 12 smoke3 failures were a bug in my own test script, not the implementation: the matcher had legitimately paired that placement with the older ADJUNCT supervisor (supervisor eligibility in §3.5 has no district clause, and the tie-break falls through to `created_at` asc), so the script's hardcoded supervisor id failed the rung-4 ownership check on `POST /epp/observation-cycles/{id}/complete` and all three completions were silently rejected. Reading `supervisor_id` off the confirm response fixed it; all three suites now pass on fresh boots.

## Modules (`workspace/implementation/`, 3653 lines total, all `py_compile` clean)

| module | lines | role |
| --- | --- | --- |
| `app.py` | 73 | `create_app()`, 10 blueprints, error handlers (`ApiError`, 404 -> `ERR_NOT_FOUND`, 405 -> `ERR_INVALID_REQUEST`, 500 -> `ERR_INTERNAL`), `PORT`/0.0.0.0 foreground run |
| `errors.py` | 76 | 55 error codes with pinned statuses |
| `clock.py` | 91 | logical clock (default `2026-08-01T00:00:00Z`), ISO-8601 parse/format at exactly 3 fractional digits |
| `envelope.py` | 58 | meta/`response_type`/data envelope, `req_` + 20 uppercase alnum ids |
| `store.py` | 162 | in-memory dicts, `_seq` stable ordering, per-request reset hook |
| `shapes.py` | 269 | body/type/enum/number/instant coercion, polymorphic readiness-item field sets, §2.3 page/page_size |
| `auth.py` | 68 | rungs 1-3 role gates, rung 4 `require_owner` |
| `calc.py` | 179 | 10 calculations (Decimal + ROUND_HALF_UP, Manhattan distance, mileage tiers, weeks credited, rubric) |
| `derive.py` | 261 | derived/parallel state: readiness, compliance ratio, caseload points, lazy sweeps |
| `views.py` | 208 | response serializers per resource |
| `matcher.py` | 180 | §3.5 eligibility filter + §3.6 ranking, `routing_envelope_check` (rungs 29/30) |
| `flows.py` | 136 | shared cascades: accrual, settlement, ledger/caseload/teacher refresh, removal-pending, uphold-removal |
| `routes/*` | 1888 | districts 74, candidates 188, items 139, agreements 187, bench 224, requests 268, placements 343, cycles 203, assessments 247, admin 19 |

Storage is in-memory dicts only; nothing is seeded, preloaded or hardcoded at startup; no file, SQLite or `/tmp` persistence anywhere. `start.sh` reads `$PORT`, binds 0.0.0.0, runs `exec python3 app.py` in the foreground, and was booted cold 5 separate times during smoke testing.

## Endpoints
52 declared, 52 implemented, verified programmatically against the PRD endpoint table (missing `[]`, extra `[]`), including `POST /_clock/set_current_utc` and all 11 create-201 operations.

## Notable interpretation decisions
1. **Ladder beats prose.** Where §2.6's numbered ladder and §3's narrative disagree on order, the numeric ladder wins. Concrete cases: routing evaluates rung 14 (lazy agreement expiry) before rung 25 (STRICT readiness) though the prose reverses them; assessment submit evaluates rung 17 (placement ACTIVE) before rung 21; reschedule evaluates rung 33 (bounds/overlap) before rung 37 (reschedule limit).
2. **`seats_committed` vs `seats_reserved` for cap eligibility.** §3.5's filter requires an agreement whose `seats_committed` is *strictly below* `placement_cap`, so proposals may over-subscribe `seats_reserved` while confirmation is what raises `ERR_PLACEMENT_CAP_EXCEEDED`. §3.6's "over-subscription" language refers to reservations only.
3. **`current_placement_id`** is the newest non-voided placement of the request; an outright void (suspension, rerouted-away) clears it to null rather than falling back to an older placement.
4. **Reroute is a hypothetical.** The current placement is voided and the exclusion appended *before* selection, then both are rolled back if no pair qualifies, so a failed reroute is fully atomic (`ERR_NO_ELIGIBLE_PLACEMENT`, placement back to PROPOSED, exclusion list unchanged).
5. **Shared RETURN terms** are applied identically for an explicit `RETURN` decision and for a sub-cut `SCORE` that is not the final attempt: no dimensions recorded, `total_score` left 0, `submitted_at` cleared, `window_closes_at` pushed +7 days, `attempt_no` untouched.
6. **Interval conventions kept deliberately distinct** as the PRD specifies: agreement/term/turnaround closed-closed with +/-14d padding, cycle window half-open, assessment window closed-closed.
7. **Rung 44 uses a projected caseload** (`caseload_points - supervisor_points + stage_points("ACTIVE", travel)`) so confirmation replaces rather than double-counts the proposal's points.
8. **DISMISSED removal retains audit fields** (`removal_reason`, `removal_requested_by_*`) while restoring ACTIVE and re-scoring points down; only the stage changes.

## Smoke-test result
118 assertions across three scripted passes (`/tmp/task_2911_impl/smoke{,2,3}.py`), each against a cold-booted server, all green:
- **smoke.py — 63 checks, 0 failures.** Envelope/meta shape, 3-digit timestamps, `response_type`, error meta carrying only two keys, 401/403/404/400 shapes, pagination meta and the `page_size=101` rejection, polymorphic item validation, readiness scoring to 100/READY, routing -> confirm -> accrual (`12962` / `181468` / travel `137886` / supervisor_points 2), ledger commitment, cycles with owner 403, ratio 1.0, assessment pass at 71, completion/final settlement (`183968`, weeks 14), `state_report_deadline` 2027-01-21, stipend chain with an out-of-order PAID rejection, licensure, SoD 403 and on-time report.
- **smoke2.py — 24 checks, 0 failures.** Reroute OCC 412, successful reroute with exclusion, failed-reroute rollback, misconduct removal cascade (teacher DISQUALIFIED, stipend VOIDED to 0, travel `56280`, 4-week floor, seats/caseload/committed-stipend released, request requeued with both exclusions), lazy MISSED, past-window `ERR_CYCLE_WINDOW_CONFLICT`, reschedule, and lazy training/agreement/readiness expiry (score 65 / LAPSED).
- **smoke3.py — 31 checks, 0 failures.** Adjunct ceiling 10, nearest-teacher routing, fingerprint gate 422 then confirm arithmetic with travel disabled (`13580` / `190120` / `0`), `ERR_PLACEMENT_CAP_EXCEEDED`, routing refused on a non-SUBMITTED request, back-to-back term routing then `ERR_TEACHER_TURNAROUND_CONFLICT`, suspension cascade (AGREEMENT_SUSPENDED void, requeue with exclusion, `seats_reserved` 0), no-eligible while suspended, routing after reactivation, `ERR_ASSESSMENT_ALREADY_EXISTS`, `ERR_OBSERVATION_COMPLIANCE_LOW`, RETURN-with-scores and off-step 422s, sub-cut RETURN with the 7-day grace, attempt 2, `ERR_ASSESSMENT_ATTEMPTS_EXHAUSTED`, FAILED at 60 with the system-filed removal cascade, DISMISSED restoring ACTIVE, `ERR_TERM_NOT_ENDED` and `ERR_ASSESSMENT_NOT_PASSED`.

Every server I started was killed by its captured PID with `ss -ltnp` confirming `PORT_FREE` and `PROCESS_GONE`; no broad `pkill` was ever issued. Scratch files stayed under `/tmp/task_2911_impl/`. `worklog.md`, `test_suite/`, `test_helpers/` and the two design YAMLs were never read or touched. `__pycache__` was cleaned, so the delivered directory contains only source plus `requirements.txt` and `start.sh`.

## Step 5: Generate Unit Tests — 2026-09-05T18:18:58.000Z

Suite complete. Everything lives at the task root (`/home/ubuntu/github/CodingPRD/tasks/task_2911_student_teacher_placement_clinical_practice/`); nothing under `workspace/`, `worklog.md` untouched, `workspace/implementation/` never read.

**test_helpers/** (9 files, 2342 lines): `__init__.py` 206, `api_client.py` 300, `api_errors.py` 145, `assertions.py` 370, `constants.py` 146, `factories.py` 411, `fixtures.py` 456, `test_users.py` 114, `types.py` 394.

**test_suite/** (conftest 15 lines + 18 test modules, 4181 lines): test_01 143, test_02 107, test_03 175, test_04 182, test_05 179, test_06 156, test_07 175, test_08 192, test_09 203, test_10_entities 371, test_11_state_machines 305, test_12_calculations 240, test_13_validations 300, test_14_endpoints 139, test_15_errors 660, test_16_rbac 222, test_17_cross_cutting 157, test_18_consistency 75.

**Tests: 104**, all importable under `PYTHONPATH=<task root>`, all files `py_compile` clean, zero unused `test_helpers` imports (one stray `PLACEMENT_COORDINATOR` import in test_12 removed at the end).

**Coverage (machine-verified against both yaml indices by walking every `name:` and diffing against the `Design:` tags):**
- Queue A (§1.8 difficulty): 18 non-stub instances, 0 stubs — 36 tests, exactly 2 per instance. No missing, no dangling.
- Queue B (§1.9 corner): 68 non-stub instances (95 total, 27 `excluded_because:` stubs) — 68 tests, exactly 1 per instance. No missing, no dangling, and no tag points at a stub. Section split: entities 11, state_machines 9, calculations 6, validations 8, endpoints 4, errors 20, rbac 6, `cross-cutting complexity layers` 3, `consistency model` 1.
- **Instances skipped: none.** Every non-stub instance passed the PRD-first filter.

**PRD-first corrections applied where the design index conflicted with the contract** (design followed only where the PRD confirms it): reroute answers 201 not 200 (§3.5); the eight semantic gates `ERR_FINGERPRINT_CLEARANCE_REQUIRED`, `ERR_CANDIDATE_NOT_READY`, `ERR_COMMUTE_LIMIT_EXCEEDED`, `ERR_SUBJECT_BAND_NOT_ALLOWED`, `ERR_TERM_OUTSIDE_AGREEMENT_WINDOW`, `ERR_PROVISIONAL_STIPEND_NOT_PAYABLE`, `ERR_OBSERVATION_OUTSIDE_WINDOW`, `ERR_OBSERVATION_COMPLIANCE_LOW` are 422 not 409; a 14-week term from 2026-12-01 ends 2027-03-08; the multi-reroute recipes pass `exclude_current_teacher=False` on intermediate hops because §3.5 makes the exclusion permanent (the design's default would starve the matcher into `ERR_NO_ELIGIBLE_PLACEMENT`); factories omit the PRD-forbidden `expires_on` on exam/coursework items.

Money and timestamp hygiene: all cents/quantities sent as JSON numbers; instants compared through `assert_instant_equals`, which canonicalises the three-fractional-digit shape rather than asserting raw width.

## Step 7: Run Tests and Iterate — 2026-09-05T18:40:26.000Z

All 8 rounds of a single sweep pass at **104/104**. Loop closed.

## Summary

**Iterations run:** 2 (iteration 1 = baseline sweep, 97/104 x 8 rounds with 7 deterministic failures; iteration 2 = clean).

Failures were 100% deterministic (identical 7-test failure set in all 8 rounds), so no load-induced flakiness was in play.

**Tests deleted:** none.

**Assertions removed (STEP 1c partial-coverage handling):** 1
- `test_suite/test_10_entities.py` — `test_get_candidate_returns_the_stored_row_with_initial_derived_fields` asserted `readiness_variant_used is None` on the **read** response. PRD §3.1 verbatim covers the null only for a *newly admitted* candidate; §3.2 says a single-candidate read "re-derives `readiness_score` and `readiness_status` under `STRICT`" (naming only those two fields) while also saying "Each evaluation also records `readiness_variant_used`". Both readings are articulable — a PRD-faithful implementer may either record `STRICT` on the read or leave the field null — so the post-read claim fails unique derivability. The PRD-covered part was preserved by moving the assertion onto the 201 admission response, where §3.1 pins it unambiguously.

**Fixes applied to `test_suite/`:** 3 (all test-artifact bugs, STEP 2)
- `test_15_errors.py` (2 call sites, in `test_the_third_reroute_of_one_request_is_rejected` and `test_confirming_a_placement_whose_teacher_was_disqualified_is_rejected`) and `test_17_cross_cutting.py` (2 call sites, in `test_a_reroute_echoing_the_current_version_supersedes_again` and `test_a_stale_expected_request_version_on_reroute_changes_nothing`) — all four omitted the required `stipend_committed_cents` argument to `assert_agreement_ledger`, producing a `TypeError` before any assertion ran. Added `stipend_committed_cents=0` (correct: every one of these scenarios stops at `PROPOSED`, so nothing was ever accrued).
- `test_16_rbac.py` — module constant `SITE_WITHDRAWAL` spelled `removal_reason` as `"SITE_WITHDRAWAL"`, which is not a declared enum member. PRD §2.12 fixes `removal_reason` to `CANDIDATE_PERFORMANCE`, `ASSESSMENT_FAILURE`, `COOPERATING_TEACHER_MISCONDUCT`, `DISTRICT_REQUEST`, so the PRD-faithful implementation correctly rejected the fixture's request with `ERR_INVALID_REQUEST`. Changed to `DISTRICT_REQUEST`, matching the constant's own narrative ("The campus withdrew the offer").

**Fixes applied to `test_helpers/`:** none — the helper signatures were correct; the bug was in the call sites.

**Fixes applied to `implementation/`:** 1 (STEP 3)
- `workspace/implementation/flows.py`, `uphold_removal()` — wrote the literal `"COOPERATING_TEACHER_MISCONDUCT"` into the teacher's `disqualification_reason`. PRD §3.4 states verbatim that on an upheld misconduct removal the teacher is disqualified "with `disqualification_reason` **taken from the removal narrative**". Now assigns `placement["removal_narrative"]`.

**Final per-round results (single sweep, `SWEEP_COMPLETE 2026-09-05T18:33:43Z`):**

| Round | Passed/Total | Failed | Errors |
|---|---|---|---|
| 1 | 104/104 | 0 | 0 |
| 2 | 104/104 | 0 | 0 |
| 3 | 104/104 | 0 | 0 |
| 4 | 104/104 | 0 | 0 |
| 5 | 104/104 | 0 | 0 |
| 6 | 104/104 | 0 | 0 |
| 7 | 104/104 | 0 | 0 |
| 8 | 104/104 | 0 | 0 |

`worklog.md` was not touched (mtime still 18:18, predating this session). No scratch or stray files left behind.

Orchestrator verification: independently parsed all 8 `results.$i.json` — every round reports 104/104. Step 8 is NOT skipped (Step 7 applied 1 `implementation/` fix plus 3 `test_suite/` fixes and 1 assertion removal).

## Step 9: Complete PRD — 2026-09-05T19:22:14.000Z

Orchestrator note on method: per the known failure mode where a single Step 9 subagent silently no-ops (leaving PRD_COMPLETED.md byte-identical to its source), Step 9 was run as **three sequential passes partitioned by implementation module** over one shared `PRD_COMPLETED.md`. Pass 1 owned the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying. Each pass received the prior pass's hand-off notes.

- Pass 1 partition: `app.py`, `errors.py`, `clock.py`, `envelope.py`, `store.py`, `shapes.py`, `auth.py`, `views.py` (envelope, error/status table, logical clock + ISO-8601 rendering, storage/ordering/versioning, body coercion + pagination, role/ownership gates, serializers).
- Pass 2 partition: `calc.py`, `derive.py`, `matcher.py`, `flows.py` (10 calculations and rounding order, derived/parallel state, lazy sweeps, matching eligibility + ranking/tie-breaks, shared cascades).
- Pass 3 partition: all 11 `routes/*.py` (per-endpoint field sets, actual validation firing order, state gates and error codes, status codes, side effects, list filters).

### Pass 1 — infrastructure layer

Setup: `cp PRD_FINALIZED.md PRD_COMPLETED.md` confirmed; both 473 lines / 113,663 bytes before edits. Result: 473 lines / 119,683 bytes (+6,020 chars, 0 line delta — the PRD is one long line per paragraph so all edits are in-paragraph). Counts: **3 mismatch-revisions, 10 ambiguity-pins**.

- §2.2 success envelope — revise — mismatch — meta example's `"limit": 10 / "offset": 0` replaced with `"page": 1 / "page_size": 10` — `envelope.py:42-49`
- §2.2 bullet list — revise — mismatch — pagination-slot bullet renamed to `page`/`page_size`, plus "no `limit` or `offset` slots anywhere" — `envelope.py:44-47`
- §2.2 error-format lead-in — revise — mismatch — "(4xx status codes)" widened to include the 5xx fallback — `app.py:58-63`
- §2.2 `api_request_id` bullet — insert — ambiguity — pinned `req_` + exactly 20 chars from `A`-`Z`/`0`-`9`, regenerated per response including errors — `envelope.py:18-19`
- §2.1 headers — insert — ambiguity — only the literal empty string counts as absent (values not trimmed, whitespace-only passes); role names matched exactly/case-sensitively — `auth.py:23-32`
- §2.3 pagination — insert — ambiguity — non-integer `page`/`page_size` -> 400; empty string = omitted; page past the end -> 200 with empty array, true `total_count`, `has_more` false — `shapes.py:224-241`, `shapes.py:266-269`
- §2.3 ordering/filters — insert — ambiguity — `created_at` tie broken by creation order; empty-string filter = absent; non-member enum filter -> 400; boolean filter accepts only `true|false|1|0` case-insensitively — `store.py:61-63`, `shapes.py:244-263`
- §2.4 audit fields — insert — ambiguity — `version` bumps at most once per HTTP request per row (multi-effect calls still yield +1); serialization shape: `id` first, own fields, then `created_at`/`updated_at`/`version`, keys never alphabetized, every declared field always present as `null` when unset — `store.py:49-58`, `views.py:182-204`, `app.py:31`
- §2.5 instants — insert — ambiguity — every rendered instant carries exactly 3 fractional digits + literal `Z`, sub-millisecond truncated not rounded; input grammar pinned (`T`/`t`, mandatory seconds, optional 1-9 fractional digits, mandatory `Z`/`z` or `±HH:MM` offset normalized to UTC) — `clock.py:11-14`, `clock.py:45-80`
- §2.6 rung 6 — insert — ambiguity — five coercion rules: Content-Type ignored / absent or blank body = `{}` / non-object or invalid JSON -> 400; JSON `null` counts as absent for required-and-default checks (with the §3.1 key-presence exception called out, verified against `routes/items.py:40`); integer fields reject booleans and `12.0`, boolean fields reject `0`/`1`/strings; string lengths untrimmed; enum lists must be arrays of distinct declared members in supplied order — `shapes.py:51-64,67-68,90-125,200-221`
- §2.7 numeric precision — insert — ambiguity — the half-step/ratio fields (`observation_compliance_ratio`, 5 rubric inputs, `credits`) render decimally even on whole values (`12.0`, `4.0`, `1.0`); every other numeric field is a bare integer — `views.py:182-194`, `calc.py:162-165`
- §4 preamble — insert — ambiguity — trailing slash insignificant on every path — `app.py:29`
- §5 preamble — insert — ambiguity — three transport-level fallbacks outside the catalogue: unknown path -> 404 `ERR_NOT_FOUND`, wrong method -> 405 `ERR_INVALID_REQUEST`, server fault -> 500 `ERR_INTERNAL`, all in the standard error envelope — `app.py:49-63`

Pass 1 also confirmed §2.6 rung 4's "exactly two endpoints" claim is accurate (`routes/cycles.py:120`, `routes/assessments.py:116` are the only `require_owner` call sites) — no edit needed.

### Pass 2 — computation and state-derivation layer

Confirmed no re-copy (zero `cp` calls; all changes surgical Edits; pass 1's 13 changed lines verified still present). 473 lines / 119,683 bytes -> 473 lines / 124,389 bytes. Counts: **3 mismatch-revisions, 14 ambiguity-pins**.

- §3.4 — revise — mismatch — `consecutive_terms_hosted` no longer claimed to "feed the ranking"; it drives only the longevity bonus — `matcher.py:173-179`, `calc.py:119-125`
- §3.2 — insert — mismatch — transition set gains `LAPSED -> NOT_READY` (a second consecutive failing evaluation) — `calc.py:85-90`
- §3.6 — revise — mismatch — turnaround blocks are built from every placement other than the one being confirmed (PRD as written self-conflicted every confirmation) — `matcher.py:90-101`, `routes/placements.py:142-144`
- §2.9 — insert — ambiguity — a re-derivation that finds every total already correct writes nothing and leaves `updated_at`/`version` alone — `derive.py:15-19,107-126,142-150,173-190`
- §3.2 — insert — ambiguity — ROLLING's reference is the latest `start_date` (not newest-created), and with no qualifying placement no `EXPIRED` item counts — `derive.py:44-53,56-76`
- §3.2 — insert — ambiguity — a repeat read that finds readiness fields already correct bumps nothing, unlike the explicit evaluate call — `derive.py:79-92` vs `routes/candidates.py:69/108`
- §3.4 — insert — ambiguity — `supervisor_points` is re-derived, not frozen: rewritten to 0 once a placement is REMOVED/VOIDED/COMPLETED — `derive.py:164-190`
- §3.5 — insert — ambiguity — the envelope/window checks run over a scope (preferred district's agreements, else all), expire + re-derive each, are existential over its ACTIVE members, and are skipped entirely when none is ACTIVE — `matcher.py:17-53`
- §3.5 — insert — ambiguity — the lazy training-expiry check hits every teacher on file as the pool is scanned — `matcher.py:109-111`
- §3.5 — insert — ambiguity — the teacher's district backing agreement is the earliest-created qualifying one -> placement's `agreement_id` — `matcher.py:56-75`
- §3.5 — insert — ambiguity — every supervisor's caseload/ceiling/flag is re-derived during the supervisor scan — `matcher.py:141-144`
- §3.5 — insert — ambiguity — `created_at` tie-breaks fall back to creation order (the common case under the logical clock) — `matcher.py:173-179`
- §3.5 — insert — ambiguity — `current_placement_id` derivation: newest-created placement, null when that one is VOIDED (a suspension-voided proposal nulls it; a REMOVED one keeps it) — `derive.py:246-257`
- §3.7 — revise — ambiguity — cancellation note is the literal `CANCELLED_BY_REMOVAL` — `derive.py:234-241`, `flows.py:8`
- §3.7 — insert — ambiguity — an overdue SCHEDULED cycle is claimed by the removal cascade (CANCELLED_HOLD, dropped from the counted set), not by the MISSED sweep — `flows.py:94-95/110-111`, `derive.py:213-215`
- §3.8 — revise — ambiguity — the system-filed removal leaves `removal_narrative` null too — `routes/assessments.py:245`, `flows.py:85-93`
- §3.9 — insert — ambiguity — misconduct disqualification applies whatever the prior status was, overwriting an existing `disqualification_reason` — `flows.py:114-125`

### Pass 3 — endpoint layer (final pass)

Confirmed no re-copy (22 surgical Edits, no `cp`; passes 1 and 2 signature phrases re-grepped and verified intact). 473 lines / 124,389 bytes -> **473 lines / 137,310 bytes** (md5 `e58ed8ab861eafa04b45d5abced3a12c`). Counts: **9 mismatch-revisions, 13 ambiguity-pins**.

Mismatch revisions:
- §3.5 — revise — mismatch — `ERR_AGREEMENT_EXPIRED` pinned to its actual existential condition (scope holds no `ACTIVE` agreement and >=1 `EXPIRED`); a scope with an `ACTIVE` agreement beside lapsed ones never raises it, and an all-`DRAFT`/`SUSPENDED`/`TERMINATED` scope falls through to the matcher — `routes/requests.py:160-165`
- §3.5 — revise — mismatch — routing's real gate order pinned (rung 14 -> 16 -> 25), so an unready request backed only by lapsed agreements answers `ERR_AGREEMENT_EXPIRED`, not `ERR_CANDIDATE_NOT_READY` — `routes/requests.py:160-179`
- §3.5 — revise — mismatch — pass-2's trailing "falls through to `ERR_NO_ELIGIBLE_PLACEMENT`" clause qualified so it no longer contradicts the narrower expiry condition — `routes/requests.py:161`
- §3.5 — revise — mismatch — failed reroute is a value-level rollback, not a version-level one; the matcher ran with the proposal momentarily `VOIDED`, so agreement/teacher/supervisor and the surviving proposal itself can read back with `version` one higher — `routes/requests.py:248-258`
- §3.7 — revise — mismatch — observation at/after `window_end`: the lazy `MISSED` transition runs before the state gate, so once the clock passes `window_end` the answer is `ERR_CYCLE_STATE_INVALID`, not `ERR_OBSERVATION_OUTSIDE_WINDOW` — `routes/cycles.py:127-141`
- §3.7 — revise — mismatch — "the requirement that the placement be `ACTIVE` is enforced in practice" was false for a placement that was never `ACTIVE`; there is no placement-stage gate at all — `routes/cycles.py:110-141`
- §3.7 — revise — mismatch — reschedule refusal order pinned as rung 8 -> 20 -> 33 -> 37 (window conflict before the two-attempt ceiling) — `routes/cycles.py:159-194`
- §3.7 — revise — mismatch — "re-derives the compliance ratio upward again" corrected: `MISSED -> SCHEDULED` leaves the ratio untouched, since both sit in the denominator and neither in the numerator — `derive.py` COUNTED_CYCLE via `routes/cycles.py:200`
- §4 (row for `POST /epp/observation-cycles`) — revise — mismatch — "on an active placement" was wrong; any clinical stage is accepted, only the agreement must be `ACTIVE` — `routes/cycles.py:110-124`

Ambiguity pins:
- §3.1 — insert — ambiguity — a `VERIFIED` decision on a lapsed `BACKGROUND_CLEARANCE` is `ERR_INVALID_WINDOW`, checked after the `PENDING_VERIFICATION` gate; a `REJECTED` decision on a lapsed clearance is accepted — `routes/items.py:120-136`
- §3.4 — insert — ambiguity — future `training_completed_on` -> `ERR_INVALID_REQUEST`; `DISQUALIFIED` teacher -> `ERR_TEACHER_DISQUALIFIED` (after the date check); re-recording from `QUALIFIED` allowed; a back-dated completion >730 days old lands `QUALIFIED` then immediately `TRAINING_EXPIRED` in the same 200 response — `routes/bench.py:80-100`
- §3.4 — insert — ambiguity — second disqualification of an already-`DISQUALIFIED` teacher -> `ERR_TEACHER_DISQUALIFIED`; reachable from every other status — `routes/bench.py:103-118`
- §3.4 — insert — ambiguity — supervisor PATCH: absent key = untouched, unconditional `version` bump (empty body -> 200), and the three fields' differing `null` semantics (`max_caseload_points_override` sent as `null` is how the override is cleared) — `routes/bench.py:205-224`
- §3.5 — insert — ambiguity — the two body FKs resolve candidate-before-district, so both missing -> `ERR_CANDIDATE_NOT_FOUND` — `routes/requests.py:90-92`
- §3.7 — insert — ambiguity — cycle scheduling gates on the agreement only, never on `placement_status` — `routes/cycles.py:110-124`
- §3.7 — insert — ambiguity — the sweep set pinned: placement read, assessment submit and placement complete sweep all cycles; cycle scheduling, single-cycle read/reschedule and all removal cascades recompute without sweeping; no other endpoint recomputes the ratio — `routes/placements.py:51,276`, `routes/assessments.py:138`, `routes/cycles.py:84,200`, `flows.py:95,111`
- §3.8 — insert — ambiguity — the own-assessment segregation check sits after the `SUBMITTED` gate and ahead of both payload rungs — `routes/assessments.py:177-185`
- §3.8 — insert — ambiguity — a sub-cut `SCORE` return needs no feedback (`returned_feedback` becomes whatever was sent, else null), discards the validated rubric values, and no return records `scored_by_user_id`/`scored_at` — `routes/assessments.py:229-233,152-159`
- §3.8 — insert — ambiguity — the failure cascade's levels 2-4 are conditional on the placement still being `ACTIVE` at scoring time — `routes/assessments.py:244-246`
- §3.9 — insert — ambiguity — removal `decision_note` is validated then persisted nowhere — `routes/placements.py:196`
- §3.9 — insert — ambiguity — stipend `note` validated then discarded; `target_status` accepts all six states in shape; neither void nor clawback disturbs `stipend_weekly_cents`, `travel_reimbursement_cents` or `stipend_variant` — `routes/placements.py:296-343`
- §3.9 — insert — ambiguity — `denial_reason` is optional on a denial and ignored on a recommendation; the `ROLLING` re-evaluation runs on both branches but only after the terminality and completer-record checks, so a refused call leaves readiness and `version` untouched — `routes/candidates.py:121-152`
- §3.9 — insert — ambiguity — state report: segregation (rung 23) fires ahead of the reportable-state check (rung 48), and is skipped only while `recommended_by_user_id` is null, so a `DENIED` candidate's decider is refused for segregation — `routes/candidates.py:166-175`
- §4 preamble — insert — ambiguity — no list read performs any derivation: all 10 collection endpoints verified derivation-free by AST scan, so filters select on stale values and an individual read straight afterwards can differ — all `routes/*.py` `list_*`
- §4 preamble — insert — ambiguity — five endpoints declare no request body (agreement activate/reactivate, request route, placement confirm, placement complete) and ignore any body entirely — AST-verified — `routes/placements.py:143`, `routes/agreements.py:122,153`, `routes/requests.py:154`

Disposition of pass 2's five hand-off notes: (1) `ERR_AGREEMENT_EXPIRED` resolved; (2) observation at `window_end` resolved as clock-dependent; (3) reschedule order resolved as 8 -> 20 -> 33 -> 37; (4) failed-reroute "untouched" resolved via the value-vs-version distinction; (5) both dependent claims verified byte-intact (`routes/requests.py:125`, `routes/agreements.py:35`, and the three `force_touch` sites). Pass 1's two claims also verified present and untouched.

### Orchestrator verification of Step 9

- `cmp` confirms `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` — the scan really ran (473 lines / 137,310 bytes vs 473 / 113,663; +23,647 chars, +20.8%).
- Cumulative totals across the three passes: **15 mismatch-revisions, 37 ambiguity-pins** (52 edits).
- Structure intact: §4 holds exactly 52 endpoint rows (54 table lines incl. the 2 header rows), §5 exactly 55 error rows, and the file ends at a real section boundary — the final §5 row `| ERR_LICENSURE_NOT_RECOMMENDED | 422 |`. No new sections were added; line count is unchanged at 473 because every edit is in-paragraph.
- Step 9 touched only `PRD_COMPLETED.md`; `implementation/`, `test_suite/` and `test_helpers/` are byte-unchanged since the clean sweep, so the 8-round 104/104 result from Step 7 still holds and the `results.{1..8}.json` files in `workspace/implementation/` remain the final passing evidence.

Pipeline complete.

### Housekeeping — 2026-09-05T19:22:37.000Z

A stray `workspace/worklog.md` (4,396 bytes) was left by the Step 8 subagent despite the do-not-touch instruction. Its sole content was a duplicate of the Step 8 summary already recorded verbatim above, so it was removed after verification; no information was lost. The canonical append-only worklog is the task-root `worklog.md`.
