# Worklog — task_3370_veteran_volunteer_disaster_response_deployment_incident_typing

## Step 1: Create task directory — 2026-10-01T09:32:00.000Z

Task directory pre-allocated by command args: `./tasks/task_3370_veteran_volunteer_disaster_response_deployment_incident_typing/` with `workspace/` inside. Verified existence; no new index computed, no other task_* directory created. Difficulty instruction: "Generate task much harder than expert level!" (passed to prd-bench-scaffold-generator only).

## Step 2 (attempt 1): Generate scaffold — INTERRUPTED 2026-10-01T10:08:00.000Z

Host session ended mid-flight. Left a partial `SCAFFOLD.yaml` (1292 lines, ended with `# === CONTINUE: endpoints_2 ===` marker; missing errors/roles sections; both design files absent). Verified truncation via YAML parse + tail inspection at 2026-10-01T10:12:47Z. Partial file deleted at 2026-10-01T10:13:14.642Z; Step 2 redone from scratch below.

## Step 2 (attempt 2): Generate scaffold — 2026-10-01T11:43:46.350Z

Subagent report (verbatim):

All checks pass. The lint verdict block, verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Summary of what was generated** (harder-than-expert design: maximal rule/state/calculation density within the 40-endpoint cap, no endpoint sprawl):

Files:
- `/home/ubuntu/github/CodingPRD/tasks/task_3370_veteran_volunteer_disaster_response_deployment_incident_typing/SCAFFOLD.yaml` — 1405 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_3370_veteran_volunteer_disaster_response_deployment_incident_typing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1536 lines, single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_3370_veteran_volunteer_disaster_response_deployment_incident_typing/SCAFFOLD_CORNER_DESIGN.yaml` — 1514 lines, single key `scaffold_corner_design`

SCAFFOLD.yaml contents (§1.0–§1.7, no design keys inside):
- 12 entities (Volunteer, Certification, Incident, Operation, Deployment, FobSite, DutyShift, WorkOrder, PartnerAgency, TrainingCourse, TrainingEnrollment, WellnessCheck)
- 40 endpoints (at cap), including `POST /vdr/_clock/set_current_utc` (default 2026-09-01T00:00:00Z) and `POST /vdr/_ops/run` (six ordered sweeps)
- 11 state-machine entries over 9 entities — cyclic machines (Certification VERIFIED→EXPIRED→VERIFIED, WorkOrder block loop, Volunteer suspend/reinstate) plus parallel dimensions (Operation status × aar_status, Deployment status × duty_status)
- 7 calculations covering all three combinatorial modes (priority-score nested caps = mode a, per-night-then-sum lodging rounding pinned = mode b, stipend travel-tier evaluation order = mode c) and two dual-variant domains (Deployment stipend provisional/final; Volunteer readiness operational/wellness-adjusted)
- 22 ordered validations, 34 error codes, 8 roles (segregation-of-duties: OperationsLead submits AAR, IncidentCommander adopts; SafetyOfficer alone verifies credentials), 2 OCC concurrency rules (operation retype, work-order triage)
- Two transitive cascades: incident stand-down (depth 3: Incident→Operation→Deployment→FobSite/WellnessCheck) and cert revocation (depth 2: Certification→Deployment SAFETY_HOLD→WorkOrder BLOCKED)

Design indices:
- §1.8: 18 instances (9 rules × 2, every differentiation clause honored — different entity domains, error-category pairs, metrics, interval semantics, conserved quantities), all formula asserts precomputed to literals (e.g. stipend 41000 vs 34500, readiness 65 vs 45, priority 100/60/40, lodging 3963 vs forbidden 3964)
- §1.9: 31 active instances + 2 `excluded_because` stubs across all nine claim-extraction-guide sections

Verification performed: all three files parse via `yaml.safe_load`; SCAFFOLD top-level keys complete; scaffold_lint.py clean across 635 scanned calls; 51 instance names unique across both design files; zero unbound `${var}` placeholders; zero forbidden concurrency-vocabulary or continuation markers; every named constant carries a concrete value; all fixture dates sit at/after the pinned clock default.

result: task_3370 scaffold complete — SCAFFOLD.yaml + DIFFICULTY_DESIGN (18 instances) + CORNER_DESIGN (31 active + 2 stubs), 40 endpoints/12 entities/34 errors, lint-clean.

Orchestrator verification (independent): all three files on disk (1405/1536/1514 lines), all parse via yaml.safe_load, SCAFFOLD.yaml top-level keys = [scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles], 40 endpoints / 12 entities / 34 errors confirmed, no continuation markers (grep exit 1), 2 excluded_because stubs confirmed in corner design.

## Step 3: Copy shared files — 2026-10-01T11:44:45.858Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T12:03:06.535Z

Subagent report (verbatim):

All checks pass and the file ends cleanly. Here is the summary.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_3370_veteran_volunteer_disaster_response_deployment_incident_typing/workspace/PRD.md` — 309 lines, generated solely from `SCAFFOLD.yaml` (the two forbidden design-index files were never opened).

## Section list

- **§1 Introduction** (2 paragraphs: coordination discipline; safety-is-credentialed + people-are-finite principles; `/vdr` mount)
- **§2 Global Specifications** — 2.1 RBAC (8 roles, exact spellings, per-role `identity` translations incl. `entity_backed` semantics for `PartnerLiaison`/`Volunteer`); 2.2 API Response Structure (verbatim block, confirmed byte-identical); 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending); 2.4 Logical clock (startup default `2026-09-01T00:00:00Z`, no wall-clock fallback) + six-sweep ops run in pinned order with all seven report counters; 2.5 Common resource properties + null-until-lifecycle-field convention + zero-initialized counters; 2.6 Left-to-right nested resolution with all 12 per-entity 404 ids + full 7-tier validation priority ordering; 2.7 OCC (both guarded writes, `expected_operation_version` / `expected_work_order_version`, `ERR_STALE_VERSION` 412, no race framing); 2.8 Integer-cents precision + per-night round-half-up pinning; 2.9 Dual-variant readiness doctrine (base 10 + weights 30/25/25/20; penalty 2/hr floored at 0) + fatigue doctrine; 2.10 Pinned hazard→capability map + `capability_gap` semantics
- **§3 Business Logic** (8 subsections, zero HTTP paths/methods in backticks): 3.1 roster/vetting/credentialing incl. full revocation cascade; 3.2 incident report→assess→type; 3.3 operation lifecycle, muster gates, OCC retype; 3.4 deployment journey with all accept gates in priority order, stipend recipe (pinned 5-step order, both variants), lodging ledger rounding order; 3.5 duty shifts (half-open overlap, 12h cap, 40h fatigue cap, chronological accrual + 24h reset); 3.6 work orders (intake roles, OCC triage, full priority formula 60/50/35/30/20 + 40 bonus + 5/day capped 20, cap 100, P1≥80/P2≥50, schedule gates in priority order); 3.7 training pipeline (capacity 50, waitlist positions, 730-day cert grants, drop compensation); 3.8 wind-down (AAR segregation of duties, demobilize/complete gates, incident stand-down 3-hop cascade, wellness resolution)
- **§4 Endpoint Definitions** — 4-column table, all 40 endpoints
- **§5 Error Code Catalogue** — 2-column table, all 34 errors

## Coverage spot-check results

- **Contract 1 (Field-Name Coverage): PASS** — 73/73 required identifiers (entity fields + request bodies + query/path params) present in backticks, 0 missing (two stragglers, `course_id` and `incident_id`, were found and repaired into §3.3/§3.6/§3.7 narrative).
- **Contract 2 (Rule Coverage): PASS** — all 22 validations expressed with priority ordering (global tiers in §2.6, per-endpoint evaluation orders for offer/accept/shift-create/work-order-schedule in §3); both OCC rules fully specified; all 11 state machines with every transition's guards and side effects; all 7 calculations with constants embedded and evaluation order pinned (incl. stipend tier-keying circularity resolution and lodging per-night rounding); all cross-entity cascades (revocation, stand-down, demobe, ops-run) enumerated hop by hop.
- **Contract 3 (§3 Path Purity): PASS** — 529 backticked tokens scanned in §3, 0 path/method violations.
- **Structural:** 40/40 endpoint paths in §4; 34/34 error ids in §5, all 34 also mentioned in §2/§3 prose; 47/47 state values present; 70/70 enum values present; §2.2 verbatim block byte-identical; no pseudocode operators leaked into prose; no continuation markers; file ends at the final §5 table row.

result: PRD.md generated at /home/ubuntu/github/CodingPRD/tasks/task_3370_veteran_volunteer_disaster_response_deployment_incident_typing/workspace/PRD.md (309 lines) — all three hard contracts PASS, full coverage of 12 entities, 40 endpoints, 34 errors, 11 state machines, 7 calculations, 22 validations, 8 roles.

Orchestrator verification (independent): PRD.md on disk at 308 lines (wc; subagent's 309 counts trailing newline), ends cleanly at final §5 table row (ERR_DUPLICATE_ENROLLMENT), 0/40 endpoint paths missing, 0/34 error ids missing, 0 CONTINUE/TODO markers.

## Step 5: Generate unit tests — 2026-10-01T12:53:57.944Z

Launched ALONE (sequential mode per endpoint constraint — no concurrent Step 6). Subagent report (verbatim):

result: task_3370 test infrastructure generated — 69 tests (36 queue-A, 33 queue-B), 0 collect errors, all design tags and PRD citations verified

**File inventory** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3370_veteran_volunteer_disaster_response_deployment_incident_typing/`):

- `test_helpers/` — `__init__.py` (108), `types.py` (338), `api_client.py` (139, 36 endpoint methods covering all 40 endpoint rows), `api_errors.py` (85, all 34 error IDs registered), `assertions.py` (174), `factories.py` (132), `constants.py` (90), `test_users.py` (35, 8 roles + entity-backed builders for Volunteer/PartnerLiaison), `fixtures.py` (526, 5 tiers: state progression, hierarchy, lifecycle, fatigue/threshold targeting, cascade-ready composites)
- `test_suite/` — `conftest.py` (54) + 9 test files: test_01_volunteer_readiness (267 lines/13 tests), test_02_incident_and_operation (257/8), test_03_deployment_callup (226/8), test_04_stipend_lodging_fob (193/8), test_05_duty_shift_fatigue (240/7), test_06_work_orders (276/10), test_07_cascades (139/4), test_08_training (133/6), test_09_security (105/4)

**Coverage:** Queue A — all 18 difficulty instances, exactly 2 tests each (36). Queue B — all 31 non-stub corner instances (33 tests; both OCC instances get a success + rejection pair). The 2 `excluded_because` stubs were not translated; both difficulty-instance pointers resolve.

**Skipped instances:** none — every instance passed the PRD-first two-condition filter.

**Literal adjudications (pitfalls #1/#4):**
1. Corner `operation_initial_state_is_draft` asserted `capability_gap == {HEAVY_EQUIPMENT: 1}`; PRD §3.3 pins "an empty `capability_gap` until volunteers are rostered" — asserted `{}`.
2. Difficulty `incident_stand_down_three_hop_cascade` recipe was unreachable as written (MEDICAL-only volunteer accepting against `required_capabilities=[CHAINSAW]` violates the §3.4 accept gate); corrected caps to `[CHAINSAW, MEDICAL]`, preserving every asserted literal (stipend 41000, lodging 3963, NO_SHOW, FATIGUE_THRESHOLD).
3. `deployment_window_rest_buffer_gap`: "window ending" ambiguous between `planned_end` and `demobed_at`; fixture demobes exactly at `planned_end` so both readings coincide and the 23h-reject/24h-admit boundary is unambiguous.
4. `waitlist_promotion_follows_created_at_order`: staggered the logical clock 1s between enrollments so `created_at` ASC is determinate (same-instant creation would tie).
5. `aar_segregation_submit_cannot_adopt`: demobed the ON_SITE deployment before the early COMPLETE attempt so `ERR_AAR_NOT_ADOPTED` is the unique failing gate.
6. OCC tests assert `version == captured + 1` (PRD pins "increments by 1") instead of the index's absolute literal; serializer-format-sensitive timestamp asserts use parsed-datetime comparison.

**Sanity checks:** `pytest --collect-only` → 69 collected, 0 import errors; design-tag audit → every test exactly one resolving tag; 108 citation spans (>=8 words) all verbatim in PRD.md; every POST-create assertion passes 201 explicitly; fixtures use lenient `get_success_data` and thread entity-backed identity via `make_volunteer_headers`/`make_partner_liaison_headers`. No test server was started (no implementation exists yet).

Orchestrator verification (independent): all 9 test_helpers modules + conftest.py + 9 test files on disk; `pytest --collect-only -q test_suite/` → **69 tests collected in 0.20s, 0 errors**; `grep 'def test_'` total = 69; design tags present on all files (spot-audited counts match 2-per-difficulty-instance pattern).

## Step 6: Generate implementation — 2026-10-01T13:27:30.877Z

Launched ALONE after Step 5 completed (sequential mode per endpoint constraint). Subagent report (verbatim):

The implementation is complete and verified. Here is the summary.

## File inventory (all under `/home/ubuntu/github/CodingPRD/tasks/task_3370_veteran_volunteer_disaster_response_deployment_incident_typing/workspace/implementation/`)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded `pip install`; `exec python3 app.py` on `$PORT` (default 10000), bound to 0.0.0.0 |
| `requirements.txt` | 2 | flask==3.0.3, werkzeug==3.0.3 |
| `app.py` | 45 | Flask factory, 12 blueprint registrations, envelope-wrapped error handlers |
| `constants.py` | 87 | Every pinned constant: readiness weights 30/25/25/20 + base 10, stipend 6500/200000/15000/45000, hazard bases 60/50/35/30/20 + 40 bonus + 5/day cap 20 cap 100, 7% lodging surcharge, 48h/24h/24h/730d/40h/12h/30h/10d thresholds, default clock 2026-09-01T00:00:00Z |
| `db.py` | 60 | In-memory dicts for the 12 entities, logical clock, mint/touch (version starts 1, bumps per mutation) |
| `timeutil.py` | 50 | ISO8601 parse/format (3 fractional digits, Z) |
| `errors.py` | 48 | ApiError + all 34 catalog IDs with exact HTTP statuses |
| `envelope.py` | 71 | PRD §2.2 envelope verbatim; limit/offset/total_count/has_more (default 10, min 1, max 100, offset 0) |
| `validation.py` | 155 | Priority-1 schema checks: required fields, types, enums, unknown-field rejection, end>start ordering |
| `auth.py` | 26 | X-User-ID / X-User-Role extraction (401), role membership (403) |
| `domain.py` | 76 | Readiness dual-variant recompute, rostered_count/capability_gap (rostered = ACCEPTED+ON_SITE), ownership helpers |
| `calculations.py` | 74 | Stipend 5-step order, per-night round-half-up lodging (Decimal), priority score with floor(days)×5 cap 20, ceil shift hours |
| `cascades.py` | 126 | Demobe bundle (bunk release, lodging finalize, final stipend, shift cancel, wellness screen), cert-revocation 2-hop cascade, incident stand-down 3-hop cascade |
| `opsrun.py` | 158 | Six sweeps in pinned order with all seven counters |
| `routes/` (13 files) | 1303 | volunteers, certifications, incidents, operations (+retype), deployments (+wellness list), fobs, shifts, workorders (+triage), partners, training, wellness, admin |

## Verification results
- **Compile:** `python3 -m py_compile` on every .py — all pass.
- **Import:** `import app` — clean, 12 blueprints.
- **Boot smoke test:** `PORT=28594 bash start.sh` (fresh process) → `GET /vdr/operations` as SystemAdmin returned **HTTP 200** with the exact envelope (`meta.api_request_id/api_request_timestamp/limit/offset/total_count/has_more`, `response_type: "array"`); missing headers → **401 ERR_UNAUTHENTICATED**; clock set → 200; ops run → 200 with all seven counters. Server killed by exact PID only.
- **Lifecycle smoke (fresh boot):** register → VETTED → cert verify → DEPLOYABLE (readiness 40 = 10+30) → incident REPORTED→ASSESSED→TYPED → operation DRAFT→OPEN → offer → volunteer accept (provisional stipend 47,500 = 5×6500+15000) → check-in (rostered_count 1, gap {}) → work-order intake → triage (score 90 = 50+40, tier P1) → stale re-triage → **412 ERR_STALE_VERSION** → demobe (final stipend 8,000 = 1 day, duty_status RESTING). All asserted values match the pinned constants.
- **Endpoints:** 40 route handlers registered — matches the endpoint table exactly.
- **Isolation rule honored:** I read only INSTRUCTION.md, SCAFFOLD.yaml, and PRD.md; never opened SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_suite/, or test_helpers/; never ran pytest. No seeding at startup — the store boots empty. Process safety: no pkill/pgrep; only PIDs I launched were killed.

result: Task 3370 implementation complete — 27-file Flask app in workspace/implementation/ implementing all 40 endpoints, 34 error codes, 11 state machines, 7 pinned calculations, both OCC writes, logical clock, and six-sweep ops run; compiles, imports, boots fresh per start.sh, and passes a full lifecycle smoke test.

Orchestrator verification (independent): 14 top-level files + 13 route files on disk; `py_compile` on all .py → OK; own boot smoke on port 29753: no-headers → 401 ERR_UNAUTHENTICATED with clock-stamped envelope; SystemAdmin GET /vdr/operations → 200 with full pagination envelope (limit 10, offset 0, total_count 0, has_more false); server killed by exact PID.

## Step 7: Test-fix iteration loop — 2026-10-01T13:37:29.804Z

Subagent report (verbatim):

Clean sweep: all 8 rounds report 69/69 passed, 0 failed, and the log contains zero FAIL lines. I verified each `results.{1..8}.json` individually (all present, all `passed == total`), and the files remain in `workspace/implementation/` per the output contract.

result: task_3370 sweep clean — 69/69 passing in all 8 parallel rounds after one test-side header fix.

Summary:
- Iterations run: 2 (iteration 1: 68/69 in all 8 rounds, same single deterministic failure; iteration 2: 69/69 in all 8 rounds).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `test_suite/`: `test_07_cascades.py::test_cert_revocation_opens_gap_and_blocks_field_work` — the test read the work order via `api.get_work_order(..., safety_officer_headers)`, but PRD endpoint table (line 254) permits GET `/vdr/work-orders/{id}` only to SystemAdmin, IncidentCommander, OperationsLead, IntakeCoordinator, PartnerLiaison — SafetyOfficer is not on the list, so the PRD-faithful implementation correctly returned 403 `ERR_UNAUTHORIZED`. STEP 1 passed (the asserted rule — work order moved to `BLOCKED` with `blocked_reason=CAPABILITY_LOST` — is verbatim in PRD §3.1); STEP 2 found the request identity violated the PRD role mapping. Fix: added `get_work_order` to the `test_helpers` import and replaced the direct SafetyOfficer call with the existing helper (which reads as IntakeCoordinator, a PRD-permitted role). The assertions themselves are unchanged.
- Fixes applied to `implementation/`: none — the implementation's 403 was correct PRD behavior.

Files touched: `/home/ubuntu/github/CodingPRD/tasks/task_3370_veteran_volunteer_disaster_response_deployment_incident_typing/test_suite/test_07_cascades.py` (import list + 2-line call-site change). Results evidence at `/home/ubuntu/github/CodingPRD/tasks/task_3370_veteran_volunteer_disaster_response_deployment_incident_typing/workspace/implementation/results.{1..8}.json`.

Orchestrator verification (independent): all 8 `results.{1..8}.json` present, every round `passed: 69, total: 69, failed: 0`; claimed fix confirmed in test_07_cascades.py (import at line 11, helper call at line 137); 0 implementation .py files newer than results.1.json (no post-sweep impl edits).

<step_7_diff>
- Tests deleted: none.
- test_suite/ fixes: `test_07_cascades.py::test_cert_revocation_opens_gap_and_blocks_field_work` — request identity violated PRD role mapping (SafetyOfficer lacks GET /vdr/work-orders/{id} permission per PRD endpoint table line 254); replaced direct SafetyOfficer call with `get_work_order` helper (reads as IntakeCoordinator, a PRD-permitted role). Assertions unchanged. Pure test-side bug; implementation's 403 was correct PRD behavior.
- test_helpers/ fixes: none.
- implementation/ fixes: none.
</step_7_diff>

## Step 8: Finalize PRD — 2026-10-01T13:40:33.289Z

NOT skipped (Step 7 had 1 test_suite fix → strict skip condition unmet). Subagent report (verbatim):

Verification complete. The workspace has no test_suite/ or test_helpers/ directories materialized (only INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, implementation/), but the step_7_diff narrative is authoritative for the test-side change, and my required verification — PRD endpoint table vs implementation role set — is fully done.

**Verification performed (zero-edit outcome):**
- PRD.md line 254 (§4 endpoint table): `GET /vdr/work-orders/{id}` roles = `SystemAdmin, IncidentCommander, OperationsLead, IntakeCoordinator, PartnerLiaison` — SafetyOfficer is not listed.
- Implementation `workspace/implementation/routes/workorders.py:17-18`: `WO_READ_ROLES = ("SystemAdmin", "IncidentCommander", "OperationsLead", "IntakeCoordinator", "PartnerLiaison")` — identical set and order; the GET-by-id handler at workorders.py:41-47 enforces it via `auth.require_roles(*WO_READ_ROLES)`, so SafetyOfficer correctly receives 403.
- The step_7_diff item is a pure test-side identity bug (test called the route as SafetyOfficer, which the PRD's endpoint table already excludes; the fix switched to an IntakeCoordinator helper). PRD already pins the behavior; no PRD silence, no impl mismatch.

**Summary:**
- PRD.md: 308 lines; PRD_FINALIZED.md: 308 lines; delta 0.0% (`diff -q` reports identical).
- Changes: **zero edits.** The single step_7_diff item is a test_suite fix where the implementation was already PRD-correct, and inspection confirmed PRD.md line 254 already uniquely pins the role set for GET /vdr/work-orders/{id} to match the implementation exactly.
- Per-edit pre-edit search log: not applicable — no edits were committed. The mandatory verification for the zero-edit path was performed: PRD §4 line 254 role list vs `WO_READ_ROLES` at implementation/routes/workorders.py:17-18 and its enforcement at workorders.py:43 — exact match.

Deliverable: `workspace/PRD_FINALIZED.md` (byte-identical copy of PRD.md).

Orchestrator verification (independent): `diff -q PRD.md PRD_FINALIZED.md` → identical; PRD line 254 role list confirmed verbatim; `WO_READ_ROLES` confirmed at workorders.py:17 with enforcement at :32 and :43. Zero-edit outcome is genuine (subagent alive through report; verification reproducible).

## Step 9: Complete PRD — 2026-10-01T14:21:28.185Z

Subagent report (verbatim):

Verification complete: PRD_COMPLETED.md exists (310 lines vs 308), the diff shows exactly 32 hunks — all intended, no collateral changes — and I re-read every edited sentence in context during the full-document pass; the callsite greps confirm which helpers are live.

## Summary

**Source vs output**: `PRD_FINALIZED.md` 308 lines / 56,932 chars → `PRD_COMPLETED.md` 310 lines / 62,963 chars (**+2 lines, +6,031 chars**, 32 diff hunks, all reviewed).

**Counts**: 44 ambiguity-pins (inserts), 4 mismatch-revisions.

### Ambiguity-pins (insert)
- §2.1 — insert — unknown `X-User-Role` value counts as malformed → 401 — auth.py:17-18
- §2.2 — insert — unmatched route → `ERR_VALIDATION` 404, unsupported method → `ERR_VALIDATION` 405 — app.py:25-31
- §2.3 — insert — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION` 400 — envelope.py:41-63
- §2.3 — insert — filter query-param names (`volunteer_id`, `incident_id`, `operation_id`, `deployment_id`, `fob_site_id`, `course_id`, `source_partner_id`, `status`, `priority_tier`), literal matching, unknown value → empty page — routes/*.py list handlers
- §2.4 — insert — all server timestamps (envelope, `created_at`/`updated_at`, lifecycle stamps) read the logical clock — envelope.py:15, db.py:39-41
- §2.4 — insert — clock-set accepts any instant, even earlier than current — admin.py:17-23
- §2.4 — insert — ops-run request carries no body fields — admin.py:28-29
- §2.4 — insert — `start_date` reads as midnight UTC for the no-show deadline — opsrun.py:78
- §2.5 — insert — `version` starts at 1 on creation — db.py:42
- §2.5 — insert — null-until list gains `stipend_provisional_cents` (before acceptance) and `aar_submitted_by_role` — deployments.py:77, incidents.py:127
- §2.6 item 1 — insert — transition-conditional fields (severity/households, incident_type, expires_at, operation_id, blocked_reason, resolved_notes) validate after state legality as `ERR_VALIDATION`; endpoint-valid but transition-irrelevant fields are validated-then-ignored — incidents.py:67-76, certifications.py:98-99, workorders.py:91-92,106-108, wellness.py:28-29
- §2.6 item 3 — insert — entity-backed ownership compares against the resolved record (404 first on reads, deployment-answer, enrollment-drop); volunteer-record PATCH compares before resolution — volunteers.py:50-54/68-70, deployments.py:115-123, training.py:129-133
- §2.6 item 6 — insert — unsettable target statuses (e.g. `EXPIRED` deployment, `INTAKE` work order, `ENROLLED` enrollment) → `ERR_INVALID_STATE` 409 before record resolution — deployments.py:111-112, workorders.py:79-80, training.py:127-128
- §2.7 — insert — triage stays INTAKE-only; a fresh second attempt draws `ERR_INVALID_STATE` 409 — workorders.py:61-62
- §3.1 — insert — skills list may be empty at registration — volunteers.py:25
- §3.1 — insert — duplicate email → `ERR_VALIDATION` 400 — volunteers.py:29-31
- §3.1 — insert — availability window end earlier than start is a schema violation — validation.py:152-153
- §3.1 — insert — vetting an incomplete record → `ERR_VALIDATION` 400 — volunteers.py:91-92
- §3.1 — insert — VETTED→DEPLOYABLE without a VERIFIED cert → `ERR_INVALID_STATE` 409 — volunteers.py:96-97
- §3.1 — insert — reinstatement evaluates the wellness condition first; either failure → `ERR_OPEN_WELLNESS_CHECKS` 409 — volunteers.py:104-110
- §3.1 — insert — INACTIVE gate violation → `ERR_INVALID_STATE` 409 — volunteers.py:118-119
- §3.1 — insert — Volunteer sending `readiness_status` / SafetyOfficer sending `availability_windows` → 403; PATCH with neither field → 400 — volunteers.py:65-77
- §3.1 — insert — verify refusal → `ERR_CERT_NOT_VERIFIED` 422, strictly-past boundary (equal still verifies) — certifications.py:86-89
- §3.1 — insert — renewal: missing `expires_at` → 400, not-strictly-later → 422 — certifications.py:98-102
- §3.1 — insert — no `issued_at`/`expires_at` ordering enforced at recording — certifications.py:23-25
- §3.3 — insert — `required_capabilities` deduplicated server-side — incidents.py:116, operations.py:163
- §3.3 — insert — DRAFT→OPEN under non-TYPED incident → `ERR_INCIDENT_NOT_TYPED` 409 — operations.py:77-81
- §3.3 — insert — muster roster-mismatch → `ERR_INVALID_STATE` 409, checked before the gap — operations.py:84-90
- §3.3 — insert — MUSTERED→ACTIVE with no ON_SITE → `ERR_INVALID_STATE` 409 — operations.py:93-97
- §3.4 — insert — FOB establishment payload/bounds (name, `bunks_total` ≥ 1, `nightly_rate_cents` ≥ 0), permitted under any operation status; no operation-state gate on check-in — fobs.py:16-34, deployments.py:136-137
- §3.4 — insert — rest-buffer window end is `demobed_at` when stamped, else `planned_end` — deployments.py:175
- §3.4 — insert — clear-hold shortfall → `ERR_CERT_NOT_VERIFIED` 422 — deployments.py:218-221
- §3.4 — insert — demobe gate violation → `ERR_INVALID_STATE` 409 — deployments.py:232-234
- §3.4 — insert — wellness screen: at most one check per demobilization, `FATIGUE_THRESHOLD` precedence, stay measured in the stipend's rounded-up days — cascades.py:43-56
- §3.5 — insert — overlong (>12h) shift is a schema violation — shifts.py:31-32
- §3.5 — insert — non-ON_SITE target → `ERR_INVALID_STATE` 409; cross-operation `deployment_id` → `ERR_VALIDATION` 400; no operation-state gate — shifts.py:40-43
- §3.6 — insert — intake outside ASSESSED/TYPED/STANDING_DOWN → `ERR_INVALID_STATE` 409 — incidents.py:153-154
- §3.6 — insert — IntakeCoordinator may quote any existing agency id; only the liaison is bound to their own (or 403 for other/none) — incidents.py:145-152
- §3.6 — insert — scheduling is IntakeCoordinator-only; OperationsLead → 403 — workorders.py:88-90
- §3.6 — insert — start under non-ACTIVE operation → `ERR_INVALID_STATE` 409 — workorders.py:100-103
- §3.6 — insert — unblocking open to both IntakeCoordinator and OperationsLead — workorders.py:20-27
- §3.7 — insert — outcome marking before course start → `ERR_INVALID_STATE` 409 — training.py:140-141
- §3.8 — insert — AAR submit under other operation status → `ERR_INVALID_STATE` 409; operation PATCH combination rules (status XOR aar_status; notes only with SUBMITTED) → `ERR_VALIDATION` 400 — operations.py:52-59,127-129
- §3.8 — insert — completion with remaining ON_SITE/SAFETY_HOLD → `ERR_INVALID_STATE` 409, review check fires first — operations.py:108-115
- §3.8 — insert — incident closure with non-terminal operations → `ERR_INVALID_STATE` 409 — incidents.py:84-89

### Mismatch-revisions (revise)
- §2.4 — revise — mismatch — sweep 2 downgrades every DEPLOYABLE volunteer holding zero VERIFIED certs, however caused (not only those sweep 1 stripped) — opsrun.py:56-61
- §2.9 + §3.1 — revise — mismatch — rejection joins the recompute trigger list; "no further ceremony" replaced (owner scores recomputed, volunteer record touched) — certifications.py:116-119
- §3.3 — revise — mismatch — counter recompute enumerated (acceptance, check-in, hold-clearing, demobilization, retype, no-show sweep, revocation cascade); expiry transitions (offer expiry, cancellation, stand-down expiry) do not recompute, replacing the overclaim "every deployment status change" — cascades.py:93-100,115-122, opsrun.py:64-70, deployments.py
- §3.7 — revise — mismatch — unresolvable instructor reference → `ERR_VOLUNTEER_NOT_FOUND` 404 (per §2.6 existence), not 422; 422 only for an existing non-certified volunteer — training.py:35-40

### Dead-code findings
Callsite method: enumerated every `def` in domain.py, calculations.py, cascades.py, opsrun.py, errors.py, validation.py and grepped non-definition references package-wide; confirmed each live helper sits under a route registered in app.py:17-19.

- **No PRD-required check is defined-but-uncalled.** Three benign items only:
  - `errors.fob_site_not_found` (errors.py:42) — 0 callsites, but unreachable *by construction*: no endpoint accepts a fob-site identifier in path or body (`fob_site_id` is set internally at check-in and exposed only as a list filter), so no request shape exists where the check belongs. Not an implementation bug.
  - `validation.req_bool` (validation.py:74) — 0 callsites; every boolean input is optional-with-default via `opt_bool`. Unused generic helper, not a PRD-required check.
  - `operations.py:135-136` — the same-role AAR segregation comparison is unreachable in isolation (submit is role-gated to OperationsLead at :63-64, adopt to IncidentCommander at :65-66), but the PRD-required outcome — an OperationsLead attempting adoption → `ERR_UNAUTHORIZED` 403 — is enforced one frame earlier at the endpoint role gate with the pinned error id. Redundant defense, correct behavior.

result: PRD_COMPLETED.md written at workspace/PRD_COMPLETED.md — 48 pinned changes (44 ambiguity inserts, 4 mismatch revisions) aligning the PRD to implementation/, 32 diff hunks verified, no PRD-required dead checks found.

Orchestrator verification (independent): PRD_COMPLETED.md 310 lines vs PRD_FINALIZED.md 308; diff shows 64 changed lines (32 hunks) — real edits, not a silent no-op; 0 implementation .py files newer than the Step 7 sweep results (Steps 8/9 did not touch implementation/ — sweep remains valid, no re-run needed); all 8 results.{i}.json intact and still 69/69.

## PIPELINE COMPLETE — 2026-10-01T14:21:28.185Z

All 9 steps done. Final state: SCAFFOLD.yaml + both design indices, PRD.md → PRD_FINALIZED.md (zero-edit) → PRD_COMPLETED.md (48 pins), 69 tests (36 queue-A + 33 queue-B), 27-file Flask implementation, 8-round stability sweep all-green (69/69 × 8), results.{1..8}.json preserved.
