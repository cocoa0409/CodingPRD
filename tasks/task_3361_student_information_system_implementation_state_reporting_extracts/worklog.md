# Worklog — task_3361_student_information_system_implementation_state_reporting_extracts

## Step 1: Create Task Directory — 2026-10-01T08:53:31.579Z

Task directory pre-allocated by the command invocation; verified `./tasks/task_3361_student_information_system_implementation_state_reporting_extracts/workspace/` exists. No new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-01T09:47:00.000Z

All checks pass. The scaffold generation is complete with a clean lint verdict.

## Summary

Generated the scaffold for **task_3361_student_information_system_implementation_state_reporting_extracts** (Student Information System Implementation & State Reporting Extracts / PowerSchool-style), per the "much harder than expert" difficulty directive, purely from the scenario + skill spec (no sibling tasks consulted).

**Output files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3361_student_information_system_implementation_state_reporting_extracts/`):
- `SCAFFOLD.yaml` — 1566 lines (§1.0–§1.7 + 2 concurrency rules; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 943 lines (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1134 lines (single key `scaffold_corner_design`)

**Inventory:** 13 entities, 12 state machines (Enrollment carries parallel lifecycle × absence_posture dimensions; ReportingExtract and IntegrationFeed are cyclic; rollover execute/compensate forms a saga-like pair), 10 calculations, 9 validation priority bands, 65 endpoints, 65 error codes, 5 roles (4 opaque peer roles + `PortalUser` entity-backed by PortalAccount with ownership scoping). 2 OCC concurrency rules (extract-create on SchoolYear.version, rollover-create on District.version).

**§1.8:** 19 instances — every rule ≥2, `combinatorial_formula` has 3 covering modes (a) three-input min-cap FTE, (b) round-per-record-then-sum extract totals (888 vs 889 millis divergence), (c) pinned-order truancy exit inference. All assert literals were pre-computed in Python (e.g., fte 0.556/0.844/0.313 round-half-up edge, membership 304/212/100/80/33, escalation at exactly 48h).

**§1.9:** 41 instances (37 active + 4 `excluded_because` stubs tied to named §1.8 instances), spanning all nine claim-extraction-guide sections including OCC stale-version 412s, soft-delete archival filtering, terminal lockdowns, and RBAC ownership/denial.

**Design highlights for difficulty:** half-open year adjacency vs buffered section-time overlap (opposite interval semantics), depth-3 rollover→enrollment→student→portal cascade vs depth-2 discipline→absence→posture cascade, roster-seat and active-enrollment-count compensating invariants, state-vs-temporal and referential-vs-temporal validation priority conflicts, and a fixed logical clock (default 2026-09-01T00:00:00Z) gating half-open submission windows.

**Verification:** `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (585 calls scanned; one FK_REVERSE_UNREACHABLE for Course was fixed by adding `GET /sis/courses/{id}`). Additional self-audits: zero unbound `${var}` placeholders, 60 unique instance names across both files, no forbidden race vocabulary, response envelope verbatim, all enum values reachable, all error codes referenced.

**One risk to flag downstream:** 65 endpoints exceeds the ~40-endpoint threshold at which Step 6 (impl-gen) has previously returned rambling reports — this was a deliberate trade-off for the harder-than-expert directive; Step 6 output should be verified on disk rather than trusted.

Orchestrator verification: all three files exist on disk with claimed line counts (1566/943/1134); top-level keys `scaffold_difficulty_design:` / `scaffold_corner_design:` confirmed; SCAFFOLD.yaml contains neither design key; 65 endpoint methods counted.

## Step 3: Copy Shared Files — 2026-10-01T09:48:04.451192407Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T10:13:30.771483067Z

Subagent was interrupted mid-flight by host session end; its report was lost. Per interrupted-pipeline protocol, the artifact was verified on disk instead of re-running:
- workspace/PRD.md exists: 397 lines, 55,036 bytes, ends with newline + complete table row (not truncated).
- All 5 sections present: Introduction / Global Specifications / Business Logic & Workflows / Endpoint Definitions / Error Code Catalogue.
- Error codes: 68 unique in PRD vs 68 unique in scaffold (only diff is scaffold-spec placeholder ERR_XXX) — full coverage.
- Endpoint table §4: exactly 65 endpoint rows, matching the 65 endpoints in SCAFFOLD.yaml.
- Key literals present: logical clock 2026-09-01T00:00:00Z, round-half-up (4 mentions), 48-hour escalation window.
Artifact adopted as complete; Step 4 not re-run.

## Step 5: Generate Unit Tests — 2026-10-01T10:46:00.000Z

All checks pass. The suite is complete.

## Summary

**Task:** task_3361_student_information_system_implementation_state_reporting_extracts — full test generation from the two design indices against PRD.md.

### Files created

`test_helpers/` (Stage 1):
- `types.py` (332) — 19 status/role enums, 13 entity TypedDicts; `AttendanceEvent` correctly omits `updated_at`/`version` (PRD §2.5 immutable-ledger rule)
- `api_client.py` (237) — `ApiClient(GenericApiClient)` with one method per endpoint (52 methods, all §4 routes incl. `/_clock/set_current_utc`)
- `api_errors.py` (149) — full 60-entry `ApiErrorId` catalog + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` (132) — per-entity structure assertions
- `factories.py` (173) — payload factories; standard TX spec factory carries the U/E/H/P attendance map, FIGHT/TARDY discipline map, and EL(1.2)/HDK(0.5)/GT(1.25) program map (unifies the difficulty and corner anchor variants)
- `constants.py` (34) — thresholds (AT_RISK 0.05, chronic 0.10, FTE cap 1.0, severity cap 100, escalation 48h, 10-min section buffer) + standard dates
- `test_users.py` (20) — four opaque-role shared headers + `make_portal_user_headers(user_id)` for the entity-backed PortalUser role
- `fixtures.py` (269) — composite builders: `setup_base` (live district + published spec + open year), `setup_closed_year_with_enrollment`, `setup_rollover_pair`, threshold/withdraw/streak helpers
- `__init__.py` (115) — barrel export

`test_suite/` (Stage 2): `conftest.py` (35) + 12 numbered test files (2,149 lines total).

### Coverage
- **Queue A (Difficulty):** 19/19 instances, 2 tests each = **38 tests**
- **Queue B (Corner):** 37/37 non-stub instances, 1 test each = **37 tests**
- **Total: 75 tests.** `python -m pytest --collect-only` collects 75 with zero import errors.
- The 4 `excluded_because:` stubs were not translated; all four `difficulty_instance` cross-references resolve.
- Tag audit: no orphan, dual, or missing `Design:` tags; every tag is the docstring's final line.
- Citation audit: 116 quoted PRD sentences, all verified verbatim against PRD.md (whitespace-normalized).

### Skipped instances
None — every non-stub instance in both queues passed the PRD-first two-condition filter.

### Clock check (per task guidance)
All design worked-example literals are reachable under the PRD clock default 2026-09-01T00:00:00Z. I re-derived every number from PRD + SCAFFOLD rather than trusting the YAML: membership 304/212/100/80/45/33/227 days, FTE 0.556/0.844/0.313/1.000, extract totals 888 and 1556 millis, escalation 336h→STANDARD and exactly-48h→URGENT — all check out; no stale literals. Truancy inference tests rely on a qualifying streak, so the clock fallback path is never exercised ambiguously. Windowed tests move the clock explicitly (2027-07-01, 2027-07-13, 2027-08-01).

### Design-index issues found and resolved
1. **`version == 1` literal not uniquely derivable** — PRD §2.5 defines `version` as incrementing per mutation but never pins the initial value. In `district_create_returns_defaults_and_common_fields` I assert presence/type of `version` (PRD-covered) instead of the literal 1, and relaxed `_assert_common_fields` to type-only. All OCC flows capture versions dynamically, so nothing else is affected.
2. **Anchor spec divergence between the two indices** — difficulty's `c_sp1` has EL/HDK only; corner's `k_sp1` adds GT 1.25. Resolved by one shared factory containing all three codes; no test's asserted outcome changes.
3. **`submitted_at` string format unpinned** — PRD pins the value to "the current logical clock" but not its rendering; the revision-cycle test compares parsed instants, not raw strings.

Orchestrator verification: test_helpers/ has all 9 files (1461 lines); test_suite/ has conftest + 12 test files (2314 lines); 75 `Design:` tags counted; `pytest --collect-only` independently re-run by orchestrator → 75 tests collected, 0 errors.

## Step 6: Generate Implementation — 2026-10-01T11:12:00.000Z

Done. The implementation is complete, compiles cleanly, and boots verified from a fresh process.

## Files created (all under workspace/implementation/)

| File | Lines |
|---|---|
| start.sh | 10 |
| requirements.txt | 1 |
| app.py | 60 |
| db.py | 66 |
| dates.py | 35 |
| errors.py | 9 |
| response.py | 78 |
| validators.py | 105 |
| middleware.py | 27 |
| services/__init__.py | 0 |
| services/calc.py | 183 |
| services/serializers.py | 179 |
| routes/__init__.py | 0 |
| routes/clock.py | 20 |
| routes/districts.py | 79 |
| routes/school_years.py | 125 |
| routes/specs.py | 114 |
| routes/students.py | 78 |
| routes/courses.py | 68 |
| routes/sections.py | 257 |
| routes/enrollments.py | 229 |
| routes/incidents.py | 145 |
| routes/extracts.py | 202 |
| routes/portal.py | 124 |
| routes/feeds.py | 90 |
| routes/rollover.py | 253 |

Total 2,537 lines across 26 files. Pure in-memory dicts; zero startup seeding; `start.sh` guards the pip install behind `python3 -c "import flask"` and `exec`s `app.py` on `0.0.0.0:$PORT`.

## Endpoint count
65 route handlers implemented — matching PRD §4 / the SCAFFOLD endpoint table exactly: 64 under `/sis` plus `POST /_clock/set_current_utc`. Note: the task brief said "65 + the clock endpoint" (66), but the authoritative endpoint table defines 65 rows *including* the clock; I implemented all 65.

## Boot verification (two fresh-process runs, each killed by exact saved PID)
- Boot in <1s; no-auth request → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT` in the exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type: "error"`, `data.error_id`/`message`).
- District create 201 (version 1, `IMPLEMENTATION`), list envelope with `limit/offset/total_count/has_more` in meta, Registrar-role write → 403 `ERR_FORBIDDEN`, clock echo `{"current_utc": "2026-10-15T12:00:00Z"}`.
- Full chain: district→activate→spec→publish→year→open→student→enrollment→attendance. Verified membership_days=304 for [2026-08-01, 2027-06-01) half-open, FTE cap at 1.0 with weight 1.2, program-code mapping through the PUBLISHED spec, absence recompute (rate 1/304 → CLEAR), and student PRE_REGISTERED→ENROLLED cascade. `py_compile` passed on all 24 Python modules (Flask 3.1.3 present).

## PRD ambiguities resolved (Step 8/9 should review these)
1. **Withdraw fold vs. double count**: PRD folds the closing segment into `prior_segment_days` at withdraw *and* recomputes `membership_days = prior + current segment`. Taken literally with unchanged `entry_date`, that double-counts. I keep `entry_date` unchanged, fold at withdraw, and treat the closed segment's current contribution as 0 (internal `segment_closed` flag). Observables: after withdraw `prior_segment_days` includes the closed segment and `membership_days` is correct; after reenter `entry_date = reentry_date`, `prior_segment_days` retained.
2. **Extract create on a non-CLOSED year**: no dedicated error ID exists; I used `ERR_SOURCE_YEAR_NOT_CLOSED` (409), the only catalog entry whose condition names `CLOSED_FOR_REPORTING`.
3. **assign-teacher on LOCKED/CANCELLED section**: no error specified; I used `ERR_SECTION_NOT_ROSTERABLE` (409) — same DRAFT-or-COMMITTED predicate as roster mutations.
4. **Discipline `incident_date` outside the school-year window**: no dedicated error; used `ERR_INVALID_DATE_RANGE` (422).
5. **Rollover create with source == target**: used `ERR_INVALID_REQUEST` (400), checked at stage 2.
6. **Truancy inference with no PUBLISHED spec**: the streak tunable falls back to the documented default 10 (no `ERR_SPEC_NOT_PUBLISHED`, since no raw-code mapping is involved); likewise posture recompute falls back to the 0.10 default chronic threshold.
7. **Pagination bounds**: `limit`/`offset` non-integer, `limit` outside [1,100], or negative `offset` → `ERR_INVALID_REQUEST` (400) rather than clamping (stage-2 "numeric ranges sane").
8. **Cross-district roster-add**: rejected with `ERR_DISTRICT_MISMATCH` (422) — §2.8's mismatch list doesn't name roster explicitly but describes the general stitching rule.
9. **Timestamp serialization**: `created_at`/`updated_at`/`api_request_timestamp` use wall clock with exactly 3 fractional digits; entity date fields and logical-clock stamps (`submitted_at`, `last_synced_at`, clock echo) serialize ISO-8601 UTC with `Z`, omitting the fractional part for whole seconds so echoes match client input.
10. **OCC placement**: `expected_school_year_version` / `expected_district_version` are required (missing → `ERR_INVALID_REQUEST`); the 412 check runs after existence/state/referential checks, immediately before side effects. New resources are created at `version: 1`.
11. **Validation pipeline**: stages 2 (body shape) → 3 (role) → 4 (path existence), except the nested attendance-event routes where PRD §2.8 explicitly says a nonexistent enrollment surfaces `ERR_ENROLLMENT_NOT_FOUND` "before the body is ever examined" — there path existence precedes body-shape validation (role check still precedes both).

Orchestrator verification: all 26 files on disk, 2537 total lines, `py_compile` clean on every module, 65 route decorators counted, start.sh reads $PORT/binds 0.0.0.0/foreground via exec app.py. Independent boot smoke test on port 19731 (killed by exact PID): validation error envelope correct (ERR_INVALID_REQUEST with meta fields), list envelope correct (limit/offset/total_count/has_more).

## Step 7: Run Tests and Iterate — 2026-10-01T11:35:00.000Z

All 8 rounds pass 75/75. The sweep is clean and the `results.${i}.json` artifacts remain in place.

## Summary

**Iterations run:** 2 (initial sweep: 2 deterministic failures across all 8 rounds; one fix round; final sweep: 8/8 rounds at 75/75).

**Root cause:** Both failures — `test_spec_publish_auto_retires_prior_published_spec` and `test_registrar_cannot_publish_spec_returns_forbidden` (test_02_collection_specs.py) — failed with 404 `ERR_NOT_FOUND` when observing spec state after the publish action. The tests called `api.get_collection_spec(id)` → `GET /sis/collection-specs/{id}`, an endpoint that **PRD §4 does not define** (PRD defines only create/list/publish/retire for specs, lines 273-276). The implementation correctly omitted the route, so Flask returned a generic 404.

**Diagnostic protocol outcome:**
- STEP 1a/1b passed for both tests: the asserted rules are verbatim in PRD — §3.2 (line 162) "Publication is exclusive: at most one spec per `state_code` may be `PUBLISHED` at a time, so publishing a spec automatically retires any other `PUBLISHED` spec for the same state..." and §2.1 (lines 17/19) role-disjointness + `ERR_FORBIDDEN`. Assertions unchanged.
- STEP 2 found the test bug: the observation request used a non-PRD endpoint. Fixed the test artifact to observe through the PRD-defined list endpoint — never weakened an assertion, never touched the PRD-required publish cascade or role gate.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_client.py` — removed `get_collection_spec()`; it called an endpoint PRD §4 does not define (the client docstring promises one method per PRD endpoint).
- `test_helpers/fixtures.py` — added `get_spec(spec_id)`: reads spec state via the PRD-defined `GET /sis/collection-specs` list endpoint (limit=100) and selects by id.
- `test_helpers/__init__.py` — exported `get_spec`.

**Fixes applied to `test_suite/`:**
- `test_suite/test_02_collection_specs.py` — two call sites (post-publish RETIRED check at line ~53, post-forbidden-publish DRAFT check at line ~80) switched from `api.get_collection_spec(...)` to `get_spec(...)`.

**Fixes applied to `implementation/`:** none — the implementation faithfully matched PRD §4's endpoint table; no implementation change was warranted.

Orchestrator verification: all 8 results.${i}.json files present, each passed=75/75 failed=0; `get_collection_spec` has 0 remaining occurrences; `get_spec` defined at fixtures.py:71; SCAFFOLD.yaml likewise defines no GET /sis/collection-specs/{id} (publish/retire only), so PRD matches scaffold and the fix direction was correct. Newest impl source mtime (app.py) predates oldest results file — no post-sweep impl writes.

Note for Step 8: all Step 7 fixes were test-side (pure fixture/client bug — tests invented a non-PRD endpoint). Zero implementation fixes, zero deletions.

## Step 8: Finalize PRD — 2026-10-01T11:42:00.000Z

Task complete. PRD_FINALIZED.md is a zero-edit faithful copy of PRD.md, confirmed byte-identical.

## Summary

**Line counts:** PRD.md = 397 lines, PRD_FINALIZED.md = 397 lines, %-delta = 0.0% (zero edits, `diff -q` byte-identical).

**Changes:** none.

**Zero-edit justification (explicitly, per orchestrator note):**

The single Step 7 diff item — two tests in `test_02_collection_specs.py` failing 404 from `GET /sis/collection-specs/{id}` — was a pure test bug, fixed entirely test-side (`get_spec()` helper reads via the PRD-defined list endpoint). Both adjudication checks come back clean:

- **(a) No PRD prose outside §4 implies a spec get-by-id read model.** Grepped all spec mentions in PRD.md plus `retrieve|fetch|get one|by id` language: §3.2 (line 160-162) covers only create/publish/retire semantics; §2.8's `ERR_SPEC_NOT_FOUND` (line 124) is a path-validation rule satisfied by the two path-parameterized transitions (`/publish`, `/retire`); §3.7 references `collection_spec_id` only as a request-body FK (stage-6 `ERR_REFERENCED_ENTITY_NOT_FOUND`). No retrieve/fetch narrative exists anywhere.
- **(b) PRD nowhere promises single-resource GET for collection-specs.** §4 lines 273-276 define exactly POST create, GET list, POST publish, POST retire — conspicuously omitting the "Get one X" row that 11 other resources have. Observing spec state via `GET /sis/collection-specs?limit=100` (the Step 7 fix in test_helpers/fixtures.py:71-79) is fully PRD-supported by §4 line 274 and §2.3's pagination rules (limit max 100).

**Implementation verification at the diff site:** implementation/routes/specs.py registers exactly 4 routes (lines 25, 65, 81, 104) matching §4 1:1; publish (DRAFT gate, maps-non-empty gate, same-state auto-retire cascade, version bump) and retire (PUBLISHED gate) match §3.2 line 162 verbatim; the list endpoint's `state_code`/`status` filters and `created_at` ascending sort match §2.3. No PRD/impl divergence exists at or around the Step 7 site.

**Per-edit pre-edit search log:** no edits were committed, so no per-edit logs apply. The searches above (full-PRD spec grep, retrieve/fetch grep, impl route grep, full read of `specs.py`, test-helper call-site grep) constitute the investigation underlying the zero-edit verdict. Implementation untouched; nothing under `implementation/`, `test_suite/`, or `test_helpers/` was modified.

Orchestrator verification: PRD_FINALIZED.md exists (397 lines), `diff -q` confirms byte-identical to PRD.md; newest impl source (app.py) still predates oldest results file — sweep evidence remains valid.

## Step 9: Complete PRD — 2026-10-01T12:20:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written (400 lines / 60,256 chars vs source `PRD_FINALIZED.md` 397 lines / 55,036 chars; char delta +5,220). Implementation, tests, and helpers were not touched.

## Counts
- Ambiguity-pins: 23
- Mismatch-revisions: 3

## Changes (one per bullet)

- §2.3 — insert — ambiguity — pinned pagination bounds: non-integer/`limit`∉[1,100]/`offset`<0 → `ERR_INVALID_REQUEST` 400, never clamped; sort ties broken by creation order — implementation/response.py:58-74
- §2.3 — revise — **mismatch** — filter sentence pointed at a nonexistent per-endpoint enumeration in §4; revised to exact-match equality filters, unrecognized query params ignored, and pinned `total_count`/`has_more` semantics — implementation/response.py:34-43
- §2.4 — insert — ambiguity — clock may be set to an earlier or later instant (no monotonicity) — implementation/routes/clock.py:19, db.py:40-41
- §2.5 — insert — ambiguity — new resources start at `version` 1; date-typed fields echo as Z-suffixed ISO 8601 at supplied precision (date-only → `T00:00:00Z`), logical-clock stamps same; only `created_at`/`updated_at`/`api_request_timestamp` are wall-clock with 3 fractional digits — implementation/db.py:48-59, dates.py:27-30
- §2.6 — insert — ambiguity — computed numerics (`fte_adm`, `fte_count_date`, `absence_rate`, `absence_weight_sum`) serialize as plain JSON numbers — implementation/services/serializers.py:91-94
- §2.7 — insert — ambiguity — non-object JSON body → 400; absent body treated as `{}`; unrecognized body fields ignored — implementation/validators.py:8-14
- §2.9 — insert — ambiguity — OCC version check runs after all existence/state/referential checks, immediately before side effects — implementation/routes/extracts.py:58-60, routes/rollover.py:54-56
- §2.8 — insert — ambiguity — `ERR_DISTRICT_MISMATCH` coverage extended to cross-district roster-adds (section's year vs enrollment's year) — implementation/routes/sections.py:206-211
- §3.2 — insert — ambiguity — `auto_withdraw_streak` must be >0 and `min_membership_days` ≥0 (else `ERR_INVALID_REQUEST`); `chronic_absence_threshold` unvalidated — implementation/routes/specs.py:39-44
- §3.3 — revise — ambiguity — assign-teacher from LOCKED/CANCELLED → `ERR_SECTION_NOT_ROSTERABLE`; `teacher_ref` key required (null unassigns, missing key → `ERR_INVALID_REQUEST`) — implementation/routes/sections.py:175-186
- §3.3 — revise — ambiguity — roster-add check order (section state → enrollment exists 422 → district match 422 → ACTIVE → duplicate → capacity); roster-drop requires rosterable section + existing enrollment — implementation/routes/sections.py:192-257
- §3.4 — revise — ambiguity — enrollment-create gates now include year-existence (`ERR_REFERENCED_ENTITY_NOT_FOUND`) first; creation never gates on student `status` — implementation/routes/enrollments.py:37-40
- §3.4 — insert — ambiguity — program-code mapping resolves before the duplicate-enrollment check — implementation/routes/enrollments.py:60-75
- §3.4 — revise — **mismatch** — "first ACTIVE enrollment moves PRE_REGISTERED→ENROLLED" replaced: creation moves `PRE_REGISTERED` **or `INACTIVE`** → `ENROLLED`, other statuses unchanged — implementation/routes/enrollments.py:79-81
- §3.4 — insert — ambiguity — withdraw-fold: once folded, the closed segment contributes **zero** to the current-segment term (`membership_days` == `prior_segment_days`) until re-entry — implementation/services/calc.py:61-67, routes/enrollments.py:130-136
- §3.4 — revise — ambiguity — explicit `null` `exit_date` treated as omitted (inference runs); `entry_date` left unchanged on withdraw — implementation/routes/enrollments.py:116,165
- §3.5 — insert — ambiguity — attendance-event list: remaining ties after `created_at` broken by posting order — implementation/routes/enrollments.py:225-226
- §3.5 — revise — ambiguity — general recompute excludes events with `attendance_date` ≥ set `exit_date`; OSS `action_days` counted regardless of exit — implementation/services/calc.py:72-81
- §3.5 — insert — ambiguity — no-PUBLISHED-spec fallbacks: chronic threshold 0.10, streak 10 — implementation/services/calc.py:17-19,91-92,147
- §3.6 — revise — ambiguity — incident: both refs must exist (422), student must share the year's district (`ERR_DISTRICT_MISMATCH`), no student–enrollment correspondence enforced, `incident_date` outside year window → `ERR_INVALID_DATE_RANGE` — implementation/routes/incidents.py:45-59
- §3.7 — revise — ambiguity — extract-create: both identifiers must exist (422); non-`CLOSED_FOR_REPORTING` year → `ERR_SOURCE_YEAR_NOT_CLOSED` — implementation/routes/extracts.py:39-56
- §3.8 — insert — ambiguity — unlimited portal accounts per student; update-access bumps `version` even when no field changes — implementation/routes/portal.py:41-46,119-123
- §3.9 — revise — ambiguity — rollover source==target → `ERR_INVALID_REQUEST`; all three ids must exist / belong to district; run counters start at zero — implementation/routes/rollover.py:33-52,65-66
- §3.9 — revise — ambiguity — promoted enrollment carries no `program_code` (`state_program_code` null, `program_weight` 1.0) — implementation/routes/rollover.py:161-164, services/calc.py:110-136
- §3.9 — revise — **mismatch** — conservation invariant: revoked portal accounts restore to `ACTIVE` unconditionally (an `INVITED` account is NOT restored to `INVITED`); invariant text now carves this out — implementation/routes/rollover.py:231-235
- §5 — insert — ambiguity — documented framework-level `ERR_NOT_FOUND` (404/405) and `ERR_INTERNAL` (500) outside the catalogue — implementation/app.py:41-51

## Dead-code findings (mandatory)

1. **PRD-required check shipping as dead code** — `implementation/routes/sections.py:146-148`: the commit-time "roster must already fit within `capacity`" check (`roster_count > capacity` → `ERR_CAPACITY_EXCEEDED`) is **unreachable**. Roster-adds reject at `roster_count >= capacity` (line 221), so `roster_count ≤ capacity` invariantly holds and the commit guard can never fire. PRD §3.3 lists it as a commit gate; reported rather than excused.
2. `implementation/routes/extracts.py:173` — `spec is None` sub-branch of the submit window check is unreachable (specs are never deleted; an extract's `collection_spec_id` always resolves).
3. `implementation/routes/extracts.py:137` — `min_days = ... if spec else 10` fallback in validate is unreachable for the same reason.
4. `implementation/routes/rollover.py:210` — `r.get("_undo") or {}` fallback unreachable: compensate requires `COMMITTED`, and execute always populates `_undo` first.
5. **PRD-catalogue error codes never raiseable: none.** All 64 catalogue codes appear in raised-code greps. The implementation additionally emits `ERR_NOT_FOUND` (404/405) and `ERR_INTERNAL` (500) from framework handlers — previously undocumented, now covered by the §5 insert.
6. No helper in validators.py, middleware.py, response.py, or services/calc.py is defined-but-never-called (callsites grep-verified for all 24 functions).

Note: the `DEFAULT_CHRONIC_THRESHOLD` / `DEFAULT_AUTO_WITHDRAW_STREAK` fallbacks in calc.py looked like dead code but are genuinely reachable (enrollment recompute / truancy inference when the district's state has no PUBLISHED spec, e.g. an enrollment created without `program_code`) — they are pinned in the §3.5 insert, not reported as dead.

Orchestrator verification and adjudication:
- PRD_COMPLETED.md exists (400 lines) and DIFFERS from PRD_FINALIZED.md (`diff -q`) — not a silent no-op.
- Implementation untouched since the clean sweep (newest source app.py predates oldest results file); all 8 results.${i}.json present.
- Dead-code finding #1 adjudicated: capacity is set only at section create (sections.py:36, `capacity > 0` required); there is no capacity-mutation path anywhere in the API, and roster-add rejects at `roster_count >= capacity` (sections.py:221). The state `roster_count > capacity` is therefore unreachable through the API, so the commit-time gate (sections.py:146-148) can never fire in ANY PRD-faithful implementation — a fresh PRD_COMPLETED reader would write the same dead guard. Observable behavior is identical with or without it: benign defense-in-depth, no behavioral divergence, no action taken (removing it would invalidate the sweep for zero behavioral gain). Findings #2–4 are internal defensive fallbacks, not PRD-required behavior.
