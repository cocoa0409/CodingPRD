# Worklog — task_3397_reemployment_rights_case_handling_employer_outreach

## Step 1: Create Task Directory — 2026-10-01T16:24:00.000Z

Pre-allocated task directory `./tasks/task_3397_reemployment_rights_case_handling_employer_outreach/` verified to exist with empty `workspace/` inside. No new index computed; no other task directory created.

## Step 2: Generate Scaffold — 2026-10-01T17:40:00.000Z

All checks green. The pre-existing `worklog.md` and `workspace/` in the task dir belong to the orchestrator — untouched. No sibling task was read at any point.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3397_reemployment_rights_case_handling_employer_outreach/`):
- `SCAFFOLD.yaml` (77 KB) — §1.0–§1.7 only; no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (77 KB) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (105 KB) — single top-level key `scaffold_corner_design`

**Counts**: 14 entities · 40 endpoints (exactly at the safe ceiling — memory: >40 breaks impl-gen) · 32 error codes · 12 calculations · 7 state machines · 6 roles · 19 difficulty instances (every rule ≥2; `combinatorial_formula` carries 3, one per mode) · 49 active corner instances + 9 `excluded_because` stubs.

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
802 test-recipe calls scanned; my own static checker additionally confirmed placeholder closure, grounds resolvability, cross-file name uniqueness, and stub targets; every pinned literal (1825-day cap, 30/31-day band flip, 24-month health cap, 1.98-vs-1.97 pension rounding, 35→BRONZE→40 award score, all deadline dates) was recomputed in Python — one hand-derived date (1000-day period end) was caught and fixed to 2022-09-27.

**Notable design decisions**:
- **Archetypes**: compliance/audit + multi-party negotiation; flat topology, cyclic state machines, segregation-of-duties role model (proctor may not certify; referral creator may not submit) — all PRIORITIZE-flagged dimensions.
- **Difficulty density over volume**: dual-variant pairs on different domains (STRICT/LENIENT excuse-notice eligibility vs per-period/aggregate pension rounding); circular-looking award score pinned to base-tier-then-bonus evaluation order; depth-3 decertify cascade (ombudsman → cases → rounds → system AUDIT notes) vs depth-2 referral-submit cascade; two OCC rules on `ReemploymentCase.version` (assign + analysis supersede).
- **Boundary rigor**: 1825-vs-1826 service cap, caseload exactly-4, inclusive deadline/window edges (response 14d, referral 30d, reopen 60d), half-open service-period adjacency vs closed-interval venue booking with 60-minute teardown buffer.
- **Clock discipline**: `POST /reemployment/_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z default; all expiry transitions (certification, statement lapse, round expiry) are lazy strictly-greater comparisons, so boundary-equal instants stay active.
- **FK coverage**: every `FK ->` field has a sub-resource or filtered-list GET; audit-only actor ids (referral creator, award nominator, note author) are deliberately non-FK strings, documented as such.

Orchestrator verification: all three files exist, parse as YAML, correct top-level keys, 329 on-domain hits (reemployment|ombudsman|employer), api_prefix `/reemployment`.

## Step 3: Copy Shared Files — 2026-10-01T17:42:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T18:03:00.000Z

All contracts pass. The PRD is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3397_reemployment_rights_case_handling_employer_outreach/workspace/PRD.md` — 283 lines.

**Sections:**
- §1. Introduction (2 paragraphs, ESGR informal-mediation framing)
- §2. Global Specifications — 2.1 Roles/RBAC, 2.2 API Response Structure (byte-identical to the canonical fixed block, verified by diff), 2.3 Pagination, 2.4 Program Clock/Statutory Windows/Lazy Expiry, 2.5 Common Resource Properties & Audit Records, 2.6 OCC on Case-Bound Writes, 2.7 Validation Order & Error Precedence, 2.8 Ownership/Neutrality/Segregation of Duties, 2.9 Precision & the 30.44-Day Month, 2.10 Nested Resource Retrieval
- §3. Business Logic — 3.1 Intake, 3.2 Service Record, 3.3 Assignment & Neutrality Screen, 3.4 Mediation Rounds & Documentation Standard, 3.5 Statutory Eligibility Analysis, 3.6 Benefits & Pension, 3.7 Escalation/Referral/Withdrawal/Reopening, 3.8 Volunteer Lifecycle, 3.9 Recognition/Outreach/Trend Reporting
- §4. Endpoint Definitions — 40 rows, 4 columns (Method, Path, Description, Authorized Roles); exact match to scaffold
- §5. Error Code Catalogue — 32 rows, 2 columns; exact match to scaffold

**Zero-Silence verification (mechanical + manual walk):**
- **Contract 1 (fields):** 93/93 entity fields, 55/55 endpoint input identifiers (incl. `to_iso8601`, `to_status`, `reason`, `expected_case_version`, `period_start`/`period_end`), 4/4 common fields present in backticks — PASS. (First verifier run false-positived 87 missing because triple-backtick JSON fences corrupted token pairing; stripping fenced blocks confirmed full coverage.)
- **Contract 2 (rules):** all 10 validation priorities rendered as an explicit ordered cascade in §2.7 with endpoint-level sub-orderings (segregation-before-requirements; assign's gate→version→neutrality→caseload); both OCC rules named with write operation + `expected_case_version` + `ERR_STALE_CASE_VERSION`/412 in stale-read framing; all 40+ state transitions with preconditions/side effects; all 12 calculations with constants (24h notice, 1,825-day cap, 30/180 bands, 1/14/90 deadlines, 30.44 days/month, 24-month caps, caseload 4, 14/30/60-day windows, 20h/8h certification hours, exam 80, award 10/15/10 points, 60/40/20 gates, 30/15/5 bonuses, 1/3/5 vet gates, 60-minute venue buffer) and worked examples (pension 1.98 vs 1.97; award base-35-stays-BRONZE); every cross-entity cascade (resolution, referral, withdrawal per state, decertify 3-link) rendered. PASS.
- **Contract 3 (§3 path purity):** 459 backticked tokens scanned, 0 paths, 0 bare HTTP methods — PASS.
- Auxiliary sweeps: 32/32 error IDs in §2/§3 prose, 104/104 enum values, 36/36 state names, 6/6 roles with per-role `identity:` translations in §2.1.

The withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened. No servers were started or killed.

## Step 5a: Generate Test Helpers (frozen layer) — 2026-10-01T18:22:00.000Z

Step 5a is complete. The FROZEN test-helper layer is generated, audited, and consistent with the PRD.

## Files written

| File | Lines | Contents |
|---|---|---|
| `test_helpers/constants.py` | 131 | Every PRD literal: clock default `2026-09-01T00:00:00Z`, 1825-day cap, 24h notice, 30/180 bands, 1/14/90 deadlines, 30.44 days/month, 24-month caps (health, certification, statement), caseload 4, 14/30/60-day windows, 20h cert + 8h recert, exam pass 80, award points 10/15/10, gates 20/40/60, bonuses 5/15/30, vet gates 1/3/5, 60-min venue buffer, pagination 10/1/100/0 |
| `test_helpers/types.py` | 437 | 25 enums + 16 TypedDicts; the five append-only audit records (ServicePeriod, CaseNote, EligibilityAnalysis, BenefitAssessment, TrainingRecord) correctly omit `updated_at`/`version` |
| `test_helpers/api_errors.py` | 106 | All 32 PRD error IDs with HTTP statuses, registered via `set_error_http_status_map` (incl. 412 OCC, 403 segregation-of-duties, 422 temporal/constraint tiers) |
| `test_helpers/api_client.py` | 200 | One method per PRD endpoint (39) under the `/reemployment` prefix, plus `canonical_instant` for 3-fractional-digit timestamp comparison |
| `test_helpers/test_users.py` | 127 | Six roles; entity-backed builders `make_service_member_headers` / `make_employer_headers` / `make_ombudsman_headers`; opaque coordinators `pc-coordinator`/`pc-admin` (proctor) / `pc-lead` (certifier) so segregation-of-duties is expressible; `ANONYMOUS_HEADERS` with no `X-User-ID`; malformed-header helpers |
| `test_helpers/factories.py` | 351 | 23 payload builders, PRD-exact field names; optional fields omitted from the body when `None` so server defaults are exercised |
| `test_helpers/assertions.py` | 318 | Per-entity shape assertions (append-only asserts absence of `version`/`updated_at`), instant/2dp comparators, analysis band↔deadline↔escalator consistency, award score invariants |
| `test_helpers/fixtures.py` | 545 | 5 tiers: clock/single-entity creates; certification chain (proctor `pc-admin`, certifier `pc-lead`, 8+8+6h core template with passing scores) and triage→assign OCC chain; lifecycle shortcuts (`resolve_case_informally` with documentation-standard notes, `escalate_case`, `setup_escalated_case_with_referral`, statements, awards, analyses); accumulation (`fill_caseload`, `setup_employer_with_resolved_cases`); `setup_basic_world` |
| `test_helpers/__init__.py` | 192 | Barrel export: framework generics + full PRD-specific surface |
| `test_suite/conftest.py` | 103 | `api` fixture (env-injected base URL), per-role header fixtures, entity-backed builder fixtures, `world` fixture |

Key wiring decisions: identity threading is enforced throughout (fixtures that create an entity then act as it always call `make_*_headers(entity["id"])`); OCC fixtures return the case body post-mutation so `version` is live for `expected_case_version`; the certification fixture's proctor/certifier split matches the design anchors (`pc-admin` proctors, `pc-lead` certifies).

## Audit results

- **Compile**: all 10 files pass `python3 -m py_compile`.
- **Import graph**: `PYTHONPATH=$PWD python3 -c "import test_helpers.fixtures"` (and every other module + the barrel) imports cleanly; 45-name barrel surface spot-check passed; error map has all 32 entries with correct statuses.
- **pytest --collect-only test_suite/**: 0 items collected, no conftest import errors (expected pre-Step-5b).
- **Constants diff vs PRD**: all 25 numeric literals traced to verbatim PRD prose — PASS (the two checker artifacts, `825` and `0`, are the comma-split of "1,825" in a docstring and pagination's `DEFAULT_OFFSET = 0`, both PRD-backed).
- **Scaffold leakage**: zero references to scaffold/§1.x/Table N in generated code.

Orchestrator spot-check: files present, `import test_helpers.fixtures` OK, pytest collect-only clean (0 items).

## Step 5b: Generate Test Suite — 2026-10-01T18:51:00.000Z

All checks pass. Step 5b is complete. Summary:

## Files written (12 files, 2,632 lines, 88 tests)

All under `/home/ubuntu/github/CodingPRD/tasks/task_3397_reemployment_rights_case_handling_employer_outreach/test_suite/`:

| File | Lines | Tests |
|---|---|---|
| test_01_registration_and_entities.py | 146 | 5 |
| test_02_case_intake_and_listing.py | 224 | 9 |
| test_03_eligibility_analysis.py | 381 | 10 |
| test_04_benefit_assessments.py | 187 | 6 |
| test_05_assignment_and_caseload.py | 284 | 11 |
| test_06_mediation_rounds.py | 271 | 10 |
| test_07_case_lifecycle.py | 168 | 6 |
| test_08_ombudsman_lifecycle.py | 187 | 6 |
| test_09_referrals.py | 204 | 7 |
| test_10_recognition_and_statements.py | 180 | 6 |
| test_11_overlap_and_events.py | 194 | 5 |
| test_12_reports_and_access.py | 206 | 6 |

## AST tag audit (real `ast` parse, trailing-docstring-line rule enforced)

- **Queue A (Difficulty): 19/19 instances emitted, 38 tests (exactly 2 each), 0 skipped.**
- **Queue B (Corner): 49/49 active instances emitted, 50 tests** (`disputed_period_selector_prefers_latest_completed` got 2: selector behavior + `ERR_NO_COMPLETED_SERVICE_PERIOD` abort), **0 skipped**. All 9 `excluded_because` stubs left untranslated; every stub's `difficulty_instance` cross-reference resolves to a real queue-A instance.
- Zero untagged, zero dual-tagged, zero dangling tags. **AUDIT: PASS.**
- **Citation sweep:** every double-quoted span in all 88 docstrings verified verbatim against `PRD.md` (whitespace-normalized literal match) — 0 failures.
- **`pytest --collect-only test_suite/`** (with `PYTHONPATH=.` for test_helpers): **88 tests collected, no errors.**

## Two design literals re-derived against PRD (per the PRD-wins rule)

1. **`service_cap_1825_exactly_eligible`** (test_03): the design's `notice_given_at: 2024-12-01` falls ~11 months *after* the disputed period's 2023-01-01 start, which fails STRICT notice and contradicts the design's own asserted `overall_eligible == true`. Re-derived to `2022-12-01T00:00:00Z` (31 days before start, satisfies the 24-hour floor); all asserted outcome literals (1825/1826 days, deadline dates, eligibility booleans) kept as designed.
2. **`venue_booking_closed_interval_with_buffer`** (test_11): the design pins *acceptance* at exactly `end + 60min`, but PRD states each event occupies a **closed** interval including the 60-minute buffer and "two events that merely touch count as overlapping" — at exactly 13:00 the probe touches the prior event's closed buffered interval `[10:00, 13:00]`, so PRD does not uniquely derive acceptance there. The acceptance probe was moved to `13:00:01` (unambiguous under both readings); the inside-buffer rejection (12:30), per-venue scoping, and cancelled-exclusion assertions are unchanged.

Frozen files untouched: nothing under `test_helpers/` or `test_suite/conftest.py` was modified.

Orchestrator spot-check: `pytest --collect-only` independently re-run — 88 tests collected, no errors.

## Step 6: Generate Implementation — 2026-10-01T19:31:00.000Z

Implementation complete and verified. Summary:

## Files written (in `workspace/implementation/`, 2384 lines of Python + launcher)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 10 | Foreground launcher, `exec python3 app.py`, guarded pip install (`import flask` check), `$PORT`/default 10000, `0.0.0.0` |
| `requirements.txt` | 1 | `flask>=3.0,<4.0` |
| `store.py` | 40 | In-memory dicts for all 14 entities + logical clock (default `2026-09-01T00:00:00Z`); empty on boot, no seeding |
| `util.py` | 116 | Envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), ISO-8601 3-fractional-digit formatting/parsing, day-normalization, `add_months`, `limit`/`offset` pagination (default 10, 1..100, `total_count`/`has_more`) |
| `errors.py` | 9 | `ApiError(error_id, status, message)` |
| `auth.py` | 51 | `X-User-Role`/`X-User-ID` validation (401 `ERR_UNAUTHENTICATED`; Anonymous needs no ID), endpoint role lists (403 `ERR_UNAUTHORIZED_ROLE`), ownership helper |
| `helpers.py` | 615 | All enums/constants (notice 24h, cap 1825, caseload 4, cert 20h/recert 8h, 14/30/60-day windows, 30.44 days/month, tier gates 20/40/60, bonuses 5/15/30, vet gates 1/3/5), shape validators, per-family 404 getters, lazy expiry (ombudsman/statement/round, strictly-greater), derived counters, documentation predicate, `completed_periods` selector, all 14 serializers |
| `routes_clock.py` | 18 | `POST /reemployment/_clock/set_current_utc` |
| `routes_parties.py` | 135 | members/employers/ombudsmen create+read, affiliated-ombudsmen, member/employer service-period lists |
| `routes_ombudsmen.py` | 180 | ombudsman lifecycle (certify/leave/recertify/decertify + 3-step decertify cascade), training records |
| `routes_service_periods.py` | 59 | create with half-open overlap check (adjacency allowed, ongoing = infinity) |
| `routes_cases.py` | 265 | case file/read/list (6 filters), assign with OCC+neutrality+caseload in PRD priority order, full state machine (12 transition rules) |
| `routes_analysis.py` | 183 | eligibility analysis (disputed-period selection, STRICT/LENIENT notice, cap, bands, escalator, OCC) + benefit assessments (per-period vs aggregate rounding via `Decimal` ROUND_HALF_UP) |
| `routes_rounds.py` | 150 | round open (one-open rule), respond (deadline lazy-expiry → 422, documentation gate on ACCEPT), case rounds list |
| `routes_notes.py` | 49 | case notes (AUDIT rejected on input), notes list |
| `routes_referrals.py` | 218 | referral draft, lifecycle (30-day first-submission window, resubmission without window, REFERRED cascade mooting rounds + AUDIT notes) |
| `routes_recognition.py` | 218 | statements (sign/renew/revoke, lazy lapse), awards (nomination qualification, pinned vetting score: base → tier_qualified from base alone → bonus → final) |
| `routes_events.py` | 163 | outreach events (closed-interval venue overlap + 60-min buffer, CANCELLED excluded), sector-trends report (half-open window, repeat employers, earliest-created tie-break) |
| `app.py` | 76 | blueprint registration, per-request lock, `ApiError`/404/405/Exception envelope handlers |

## Compile + import audit
- `python3 -m py_compile` on all 17 `.py` files: **COMPILE_OK**
- `python3 -c "import app"`: **IMPORT_OK**, 41 URL rules registered (40 endpoints + Flask static)

## Smoke test (dynamic ports, own PIDs only, both killed after)
- Boot 1 (port 56263): **75/75 checks OK** — member/employer/ombudsman create (201), self-read (200), bad-enum (400 `ERR_INVALID_REQUEST`), missing ID (401), training + segregation-of-duties 403 then certify by another coordinator (200, `expires_on` = +24 months), period overlap 422 / adjacency allowed, case INTAKE→TRIAGE→assign (stale version → 412 `ERR_STALE_CASE_VERSION`, fresh → v3), round open (deadline = created+14d, case → AWAITING_RESPONSE), DECLINE → IN_MEDIATION, escalate → referral draft → submit → case REFERRED → agency ACK, analysis (disputed period = latest end_date, SHORT band, STRICT notice fail, cumulative 110), benefit math (health 3.61, pension official 3.62 vs alternate 3.61 — rounding-order divergence confirmed), documentation gate 409 then ACCEPT → RESOLVED_INFORMAL with derived employer counters, statement pledge/sign, award nominate→vet (base 25 → BRONZE, bonus 5, final 30)→confer → `recognition_tier` BRONZE, venue double-booking 422, clock set → lazy cert EXPIRED + statement LAPSED, sector-trends (total 2, resolved 1, tie-break top_issue_type).
- Boot 2 (fresh): empty store (404 `ERR_MEMBER_NOT_FOUND`), auth enforced, `created_at` = default clock `2026-09-01T00:00:00.000Z` — clean per-test reboot confirmed.

## Ambiguities resolved (interpretations chosen)
1. **`created_at` = logical clock, not wall clock** — required so `response_deadline = created_at + 14d` and the sector-trend `created_at` window are test-drivable; `meta.api_request_timestamp` also uses the logical clock for determinism.
2. **`closed_at` set on RESOLVED_INFORMAL** — PRD §3.4 explicitly states it, overriding the entity-table description naming only the CLOSED_* states.
3. **`version`/`updated_at` bump on every mutation including lazy-expiry flips and cascade side effects** — literal reading of PRD §2.5 ("increments by exactly 1 on every mutation"); OCC only guards assign/analysis, so clients must re-read after clock-driven flips.
4. **Case sub-resource reads (rounds, analyses, benefit-assessments, referrals) require the ombudsman to be the assigned one** — PRD says "all four case parties"; case-notes GET is left open to any ombudsman per §3.4's "readable by ombudsmen and coordinators" (no party qualifier).
5. **`employer.recognition_tier` computed from `tier_qualified`** (the vetted tier), not the nominated `tier` — tier_qualified is the award's actual earned tier and is never recomputed from score_final.
6. **Assign check order within priority 6**: case-state (`ERR_INVALID_STATE`) before ombudsman-certified (`ERR_OMBUDSMAN_NOT_CERTIFIED`).
7. **`counter_text` required when `response == COUNTER`** ("a counter carries the party's counter_text"); ignored for ACCEPT/DECLINE.
8. **Recertification window interpreted inclusively**: `completed_on` within `[clock − 24 months, clock]`.
9. **Pagination bounds enforced with 400** on non-integer or out-of-range `limit`/`offset` rather than silent clamping; invalid `status`/`issue_type`/`sector` filter values also 400.
10. **State-endpoint targets with no transition via that endpoint** (e.g. `to_status: RESOLVED_INFORMAL` on `/cases/{id}/state`) → 409 `ERR_INVALID_STATE`; transition-level actor mismatches → 403 `ERR_UNAUTHORIZED_ROLE` per the priority-2 rule.
11. **No round mooting on ESCALATION_PENDING → CLOSED_WITHDRAWN** — the scaffold/PRD side-effect list for that edge names only DRAFT-referral withdrawal; round mooting is tied to AWAITING_RESPONSE withdrawal/closure and referral submission only.

Orchestrator spot-check: `import app` independently re-run — IMPORT_OK, 41 URL rules.

## Step 7: Test Iteration (8-round stability sweep) — 2026-10-01T20:12:00.000Z

Two iterations run. Final sweep: 87/87 passed in all 8 parallel rounds (results.1.json .. results.8.json retained in workspace/implementation/).

**Iteration 1 sweep**: 85/88 in all 8 rounds; 3 deterministic failures (identical across rounds, no flakiness):
- `test_venue_buffer_scoped_per_venue_and_excludes_cancelled` — setup HTTP 500.
- `test_event_conclude_before_ends_at_returns_invalid_state` — setup HTTP 500.
- `test_round_create_while_one_proposed_returns_round_already_open` — expected ERR_ROUND_ALREADY_OPEN, got ERR_INVALID_STATE.

**Fixes applied**:
1. `workspace/implementation/routes_events.py` — added `touch` to the helpers import. `event_state()` called `touch(e)` without importing it (NameError -> ERR_INTERNAL 500 on every event state transition). Both test_11 failures shared this root cause; pyflakes sweep over the whole package confirmed it was the only undefined-name bug.
2. `test_suite/test_06_mediation_rounds.py` — DELETED `test_round_create_while_one_proposed_returns_round_already_open` (STEP 1b, error-precedence collapse with the A-reading impossible). PRD §3.4 names ERR_ROUND_ALREADY_OPEN for "opening a second while a PROPOSED round exists", but a PROPOSED round exists iff the case is AWAITING_RESPONSE (round creation moves it there atomically), and the round-open transition exists only from ASSIGNED or IN_MEDIATION (PRD §3.4 + case state machine). PRD §2.7 ranks state gates (priority 6, ERR_INVALID_STATE) ahead of the one-open-round business rule (priority 10) and states "the earliest category determines the response", so ERR_INVALID_STATE is the uniquely derived outcome for every input this scenario can construct; the scaffold corner instance (Corner/state_machines/round_create_while_one_proposed_returns_round_already_open) ignored the status coupling. The implementation's check order was PRD-correct and was kept; the ERR_ROUND_ALREADY_OPEN branch remains as defense-in-depth after the state gate.

**Iteration 2 sweep**: 87/87 x 8 rounds — clean, exit criteria met.

**Subagent exit summary (verbatim):**

Clean 8-round sweep achieved: **87/87 passed in every round**. Exit criteria met; `results.1.json` … `results.8.json` remain in `workspace/implementation/` as evidence.

**Iterations run:** 2 (first sweep 85/88 × 8 rounds, three deterministic failures; second sweep 87/87 × 8 rounds, all clean — no flakiness observed in either sweep).

**Tests deleted (1):**
- `test_06_mediation_rounds.py::test_round_create_while_one_proposed_returns_round_already_open` — STEP 1b error-precedence collapse with the A-reading impossible. The test asserted `ERR_ROUND_ALREADY_OPEN` per PRD §3.4's one-open-round sentence, but a `PROPOSED` round exists iff the case is `AWAITING_RESPONSE` (round creation moves it there atomically), and PRD §3.4 permits round-opening only from `ASSIGNED`/`IN_MEDIATION`. PRD §2.7 ranks state gates (priority 6, `ERR_INVALID_STATE`) ahead of the one-open-round business constraint (priority 10) and states "the earliest category determines the response," so `ERR_INVALID_STATE` is the uniquely derived outcome for every input this scenario can construct. Scaffold driver: `Corner/state_machines/round_create_while_one_proposed_returns_round_already_open`, which ignored the status coupling. The implementation's check order was already PRD-correct and was kept (the `ERR_ROUND_ALREADY_OPEN` branch remains as unreachable-by-design defense after the state gate).

**Fixes to `test_helpers/`:** none.

**Fixes to `test_suite/`:** the one deletion above in `/home/ubuntu/github/CodingPRD/tasks/task_3397_reemployment_rights_case_handling_employer_outreach/test_suite/test_06_mediation_rounds.py`.

**Fixes to `implementation/` (1):**
- `/home/ubuntu/github/CodingPRD/tasks/task_3397_reemployment_rights_case_handling_employer_outreach/workspace/implementation/routes_events.py` — added `touch` to the `helpers` import. `event_state()` called `touch(e)` without importing it, so every event state transition (`OPEN`, `CONCLUDED`, `CANCELLED`) raised `NameError` → HTTP 500. This single bug was the shared root cause of both test_11 failures (`test_venue_buffer_scoped_per_venue_and_excludes_cancelled`, `test_event_conclude_before_ends_at_returns_invalid_state`). A pyflakes sweep over the whole package confirmed it was the only undefined-name defect (one benign unused import in `helpers.py` remains).

Orchestrator verification: all 8 results files independently re-read — 87/87, failed: 0 in every round; deletion confirmed (test_06 now has 9 test functions, no `round_already_open` test); `touch` import confirmed present in routes_events.py.

## Step 8: Finalize PRD — 2026-10-01T20:41:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_3397_reemployment_rights_case_handling_employer_outreach/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts / %-delta:** PRD.md 283 lines, PRD_FINALIZED.md 283 lines — 0% line delta (single inline sentence insertion within an existing paragraph; +466 chars on line 139).

**Changes (1 edit total):**
- §3.4 (Mediation Rounds and the Documentation Standard) — insert — added a precedence-clarifying sentence after the one-open-round rule: "Per the precedence order of §2.7, the case state gate is evaluated before this one-open-round rule, so an attempt to open a round on a case whose status is not `ASSIGNED` or `IN_MEDIATION` — including a case already `AWAITING_RESPONSE` on a live proposal — is rejected with `ERR_INVALID_STATE`, and the `ERR_ROUND_ALREADY_OPEN` check is reached only when the case state itself permits opening a round." — `implementation/routes_rounds.py:31-42` (expiry application → state gate at lines 32-36 → already-open check at lines 37-42).

**Step 7 items with no PRD edit:**
- `routes_events.py` `touch` import fix — pure implementation defect (missing import → NameError → HTTP 500 on event transitions). PRD §3.9 already fully specifies the event lifecycle; nothing was silent or mismatched. Confirmed the fix is in place (`routes_events.py:10` imports `touch`, used at line 95) and moved on.

**Per-edit pre-edit search log:**

*Edit 1 (§3.4 precedence sentence):*
- (a) Subject: validation ordering on `POST /reemployment/mediation-rounds` — case state gate (`ERR_INVALID_STATE`) vs. the one-open-round business rule (`ERR_ROUND_ALREADY_OPEN`).
- (b) Impl paths enumerated: `routes_rounds.py:21-57` `create_round` (the only raise site of `ERR_ROUND_ALREADY_OPEN`, confirmed by grep across the package — no parallel endpoint raises it); `helpers.py:282-295` `apply_round_expiry`/`apply_case_round_expiry` (lazy expiry runs at `create_round` line 31, before the state gate, and only moves the case when it is `AWAITING_RESPONSE`); `routes_cases.py:191-265` `case_state` (escalation `AWAITING_RESPONSE → ESCALATION_PENDING` at lines 233-244 leaves the PROPOSED round outstanding, so a live proposal can coexist with `ESCALATION_PENDING`; withdrawal/close from `AWAITING_RESPONSE` moot proposals); grep of `apply_case_round_expiry` callsites (`routes_cases.py:142,197`, `routes_analysis.py:39`, `routes_rounds.py:31,146`) confirmed no path can produce `ASSIGNED`/`IN_MEDIATION` + live `PROPOSED` round, so the impl's `ERR_ROUND_ALREADY_OPEN` branch is unreachable-by-design defense, exactly as the Step 7 note describes.
- (c) Wording adjustment made: my first draft asserted the universal invariant "a PROPOSED round exists only while its case is AWAITING_RESPONSE" — enumeration showed that is false (escalation with a proposal outstanding leaves the case `ESCALATION_PENDING` with the round still `PROPOSED`). I widened the wording to key on the case status check ("whose status is not `ASSIGNED` or `IN_MEDIATION` — including a case already `AWAITING_RESPONSE` on a live proposal") and to state only that the `ERR_ROUND_ALREADY_OPEN` check "is reached only when the case state itself permits opening a round," which is consistent with every enumerated path without asserting any reachability invariant.

Orchestrator verification: `diff -q` confirms PRD_FINALIZED.md differs from PRD.md (real one-sentence insertion at line 139, not a no-op copy); implementation/ mtimes all precede the results files — sweep evidence still valid, no post-Step-7 impl writes.

## Step 9: Complete PRD — 2026-10-01T21:12:00.000Z

PRD_COMPLETED.md is complete. Final verification confirms the file is coherent and all edits landed.

## Summary

**Source vs output**: `workspace/PRD_FINALIZED.md` (283 lines / 51,196 chars) → `workspace/PRD_COMPLETED.md` (285 lines / 56,696 chars); delta +2 lines, +5,500 chars, 46 diff lines. Implementation untouched (read-only); no servers run.

**Counts**: 24 ambiguity-pins, 4 mismatch-revisions (28 changes total).

**Changes** (section — insert|revise — ambiguity|mismatch — what — impl ref):

- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, never wall-clock — util.py:70
- §2.2 — insert — ambiguity — unmatched path → `ERR_NOT_FOUND` (404); unsupported method → `ERR_INVALID_REQUEST` (405) — app.py:55-62
- §2.3 — revise — ambiguity — non-integer/out-of-range `limit`/`offset` → 400; `created_at` ties break by creation sequence; `has_more` ⇔ `offset`+`limit` < `total_count` — util.py:90-116
- §2.4 — revise — mismatch — clock "advances" → "sets"; any parseable instant accepted, backward moves allowed — routes_clock.py:16-17
- §2.4 — insert — ambiguity — month arithmetic clamps day-of-month to target month's length — util.py:58-64
- §2.4 — insert — ambiguity — lazy-expiry flips re-stamp `updated_at` and increment `version` — helpers.py:268-289
- §2.5 — revise — ambiguity — `created_at`/`updated_at` are logical-clock stamps — routes_cases.py:61,69
- §2.7 — revise — mismatch — transition-level actor rules decoupled from tier 2; each endpoint's definition fixes where they fire — routes_cases.py:200-221 et al.
- §2.7 — insert — ambiguity — undeclared payload fields are ignored, not rejected — helpers.py:84-88
- §3.1 — insert — ambiguity — `resolved_case_count` = cases in `RESOLVED_INFORMAL`; `open_case_count` = six open statuses (REFERRED no longer open) — helpers.py:319-330
- §3.1 — insert — ambiguity — identifier filters match on equality (never 404); enum filters (`status`/`issue_type`/`sector`) 400 on unknown values — routes_cases.py:100-128
- §3.2 — revise — ambiguity — `start_date`/`end_date` day-normalized; `notice_given_at` keeps time-of-day — routes_service_periods.py:23-26
- §3.3 — revise — mismatch — assign check sub-order: case-state gate (`ERR_INVALID_STATE` unless TRIAGE/ASSIGNED) precedes ombudsman-certified gate — routes_cases.py:145-154
- §3.4 — revise — ambiguity — `counter_text` required (400 if absent/empty) only for `COUNTER`; stored only for `COUNTER` — routes_rounds.py:65-70,125
- §3.4 — insert — ambiguity — respond check order (load → addressed-party actor rule → ownership → deadline → open-state); case status never consulted, case-side effects fire regardless; deadline-flip case fallback only from AWAITING_RESPONSE — routes_rounds.py:71-136
- §3.4 — revise — ambiguity — notes readable by any ombudsman (assigned or not); system audit notes carry `author_role` `SYSTEM`/`author_id` `system`; rounds listed in `round_number` order — routes_notes.py:42-49, helpers.py:256-257, routes_rounds.py:148
- §3.7 — insert — ambiguity — case-state endpoint order: load → fixed target actor rule (ESCALATION_PENDING/CLOSED_UNRESOLVED→Ombudsman, CLOSED_WITHDRAWN→ServiceMember) → ownership → no-(from,to)-transition → `ERR_INVALID_STATE` regardless of role → transition actor set → `ERR_UNAUTHORIZED_ROLE` — routes_cases.py:196-221
- §3.7 — revise — ambiguity — ESCALATION_PENDING→CLOSED_WITHDRAWN withdraws DRAFT referrals but does not moot rounds; a still-out proposal stays PROPOSED — routes_cases.py:245-257
- §3.7 — revise — ambiguity — `info_request_note` optional (null when omitted); resubmission does not re-stamp `submitted_at`; referral state endpoint loads referral+case before the per-target actor rule; referrals readable by the four case parties — routes_referrals.py:52,75,91-99,153-162
- §3.8 — revise — mismatch — ON_LEAVE volunteer past expiry is not flipped to EXPIRED (lazy flip applies only to CERTIFIED); return rejected with `ERR_INVALID_STATE`; recertification unreachable from ON_LEAVE — helpers.py:268-272, routes_ombudsmen.py:101-108
- §3.8 — revise — ambiguity — recertification window inclusive at both ends (exactly 24 months prior counts; future-dated records do not) — routes_ombudsmen.py:47-50
- §3.8 — revise — ambiguity — training `hours` any number (no range constraint); an ombudsman lists only their own training records — routes_ombudsmen.py:153,175-176
- §3.9 — revise — ambiguity — `recognition_tier` recomputed as highest `tier_qualified` (not nominated `tier`) among CONFERRED awards — helpers.py:333-340
- §3.9 — insert — ambiguity — award scoring fields null until vetting — routes_recognition.py:130-131
- §3.9 — revise — ambiguity — `term_months` any integer, no range validation — routes_recognition.py:29
- §3.9 — insert — ambiguity — statement `REVOKED` actor rule fires before the statement is loaded — routes_recognition.py:52-56
- §3.9 — insert — ambiguity — sector-trend parameter validation (missing/unknown sector, unparseable or non-increasing period) → 400 — routes_events.py:103-123
- §5 — insert — ambiguity — added `ERR_NOT_FOUND` (404) catalogue row — app.py:55-57

**Notable verified-already-pinned items from the brief's checklist** (no change needed): logical-clock semantics of deadlines, assign OCC/caseload order after the state gates, notes any-ombudsman scoping (sharpened anyway), inclusive reopen/referral windows, and the documentation-completeness predicate all matched PRD text verbatim.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (real edits, not a no-op copy); no `*.py` under implementation/ is newer than `results.1.json` — Step 8/9 left the implementation untouched, so the clean 87/87 × 8-round sweep remains valid; all 8 `results.{1..8}.json` files present.

## Pipeline Complete — 2026-10-01T21:13:00.000Z

All 9 steps done. Final state: 87 tests (88 generated, 1 deleted in Step 7 on PRD unique-derivability grounds), all passing in 8/8 parallel per-test-server rounds; PRD_COMPLETED.md is the final aligned contract.
