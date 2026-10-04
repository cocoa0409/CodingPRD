# Worklog — task_3185_connected_vehicle_emergency_response_subscription_services

## Step 1: Create Task Directory — 2026-09-30T08:15:00.000Z

Used the pre-allocated task directory `./tasks/task_3185_connected_vehicle_emergency_response_subscription_services/` (already created with `workspace/` inside, per command args; no new index computed).

## Step 2: Generate Scaffold — 2026-09-30T08:34:30.000Z

All checks pass. Final state of the sweep:

**Files written**
- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Counts**
- Entities: 14 (PlanTier, Account, Vehicle, Subscription, CoverageZone, CrashEvent, DispatchRequest, PSAP, StolenVehicleCase, RemoteCommand, DiagnosticReport, Dealer, ServiceAppointment, DataConsent)
- Endpoints: 83 (including 1 test-driving `POST /_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z default, plus prefixed alias GETs and `/accounts/<child>` filtered lists for FK reverse-reachability)
- State machines: 7 entity machines + Vehicle side machine (Subscription branching with cycle, CrashEvent branching with terminal rejection states, DataConsent cyclic GRANTED↔REVOKED, StolenVehicleCase branching, RemoteCommand with system expiry)
- Calculations: 8 | Validations: 11 priority rows | Errors: 23 | Roles: 9 (segregation_of_duties model; `Account` is `entity_backed:Account`, others opaque)
- §1.8: 9 rules × 2 instances = 18 | §1.9: 37 active instances across all 9 guide sections + 5 `excluded_because` stubs | 425 test-recipe calls total

**Difficulty settings (hardest admissible per "harder than expert" instruction)**
- Primary archetype compliance/audit + secondary workflow-orchestration; layers: cascading side effects, dual-variant calculation, rate/threshold triggers, scheduled/deferred actions; hybrid topology; branching state machines; immediate consistency.
- Dual-variant calcs on two domains (crash severity sensor variants; conversion fee early-bird vs late) with pre-computed literal asserts (60.0/35.0, 0/800).
- Combinatorial formulas in distinct modes: (a) integer-division/clamp ordering in health_score (76 vs 75 across the 96/95 boundary); (c) pinned evaluation order with empty-set 50.00 baseline in insurance_score.
- Transitive cascades: depth-3 crash→dispatch→bubble-up close chain and depth-3 stolen-verify→vehicle-mutation→arm-eligibility chain from different triggers.
- Boundary precision: severity 34.9 vs 35.0 persistence threshold; strict `<` caps (dealer capacity, remote-command cap at exactly 2 emergency LOCATEs).
- Compensating invariants: vehicle operability restored after recovery; zero orphaned SERVICE_SCHEDULED reports after cancel.
- OCC concurrency rules on Subscription convert/reactivate (`expected_subscription_version`, 412), with priority-5 OCC beating priority-6 state checks as an explicit conflict test.
- Coverage-dominance: cellular dead zones reject crashes into REJECTED_NO_COVERAGE even with full entitlement; EMERGENCY_RETAINED retains crash + emergency LOCATE only (window keyed on lapse_date).

`scaffold_lint.py` verdict: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` No forbidden race vocabulary; all 60 instance names unique across both design files.

## Step 3: Copy Shared Files — 2026-09-30T08:35:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T08:45:00.000Z

All checks pass. Final summary:

**Output path:** `workspace/PRD.md`
**Line count:** 307 lines

### Section list
- §1 Introduction (2 paragraphs)
- §2 Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control
  - 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`)
  - 2.3 Pagination
  - 2.4 Common Resource Properties
  - 2.5 Nested Resource Retrieval and Path Validation
  - 2.6 The Logical Clock
  - 2.7 Optimistic Concurrency Control on Subscription Writes
  - 2.8 Validation Order
  - 2.9 Coverage Dominates Entitlement
  - 2.10 Precision and Rounding
- §3 Business Logic & Workflows
  - 3.1 Platform Onboarding: Tiers, Coverage, Accounts, and Vehicles
  - 3.2 The Subscription Lifecycle: Trial, Billing, Lapse, and the Emergency-Retention Decision
  - 3.3 Automatic Crash Notification, Advisor Connection, and Dispatch
  - 3.4 Stolen Vehicle Assistance: Report, Verification, and Remote Slowdown
  - 3.5 Remote Commands and the Periodic Cap
  - 3.6 Vehicle Diagnostics and Dealer Service Scheduling
  - 3.7 Data Consents and the Insurance Score
- §4 Endpoint Definitions (4-column table; 81 rows)
- §5 Error Code Catalogue (2-column table; 23 errors)

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 64 required, 64 present, 0 missing
- endpoints[].request_body: 49 required, 49 present, 0 missing
- endpoints[].path_params: 14 required, 14 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in §2.8 in pinned order, 0 missing
- concurrency_rules[] OCC rejections: 2 checked (convert, reactivate), 2 expressed with write_endpoint + expected_subscription_version + ERR_STALE_VERSION/412, 0 missing
- state_machines[].transitions: all from/to state pairs across 9 state machines appear in PRD prose, 0 missing
- calculations[]: 7 checked (crash_severity, severity_band, conversion_fee, remote_command_cap, health_score, dealer_daily_capacity, insurance_score, entitlement_snapshot), all formulas expressed in precise natural language with constants embedded, 0 missing
- validations[] conditions: 23 error codes all referenced in §2/§3 narrative alongside their trigger conditions, 0 missing
- endpoints[].side_effects / applies_to: all cascades (verify→vehicle, acknowledge→crash, confirm→report, cancel→report, consent supersede) expressed, 0 missing
- entities[].fields[] structured content: defaults (rollover_detected/airbag_deployed false, dtc_codes [], accepts_location_transfer true, status defaults) all transcribed, 0 missing
- sibling-branch symmetry: cancellation from TRIAL/ACTIVE/EMERGENCY_RETAINED, closure from VERIFIED/SLOWDOWN_EXECUTED/REPORTED, billing outcomes on ACTIVE/PAST_DUE — all rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 374
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Zero-Silence Rule coverage notes

- **Segregation of duties**: expressed in §3.4 with both the role split (LawEnforcement reports/verifies, EmergencyOperator arms/executes) and the `X-User-ID` inequality rule tied to `ERR_SEGREGATION_OF_DUTIES`.
- **Coverage dominates entitlement**: called out as its own §2.9 principle and reinforced at each gate (crash creation, remote command creation, arm-slowdown).
- **OCC stale-version rejection**: framed purely in stale-version terms (no "simultaneously"/race framing) for both convert and reactivate, with `expected_subscription_version`, current `version`, `ERR_STALE_VERSION`, and 412 all named.
- **Cross-entity cascades**: every cascade in the scaffold (StolenVehicleCase→Vehicle, DispatchRequest→CrashEvent bubble-up, Appointment→DiagnosticReport, Appointment-cancel compensation, DataConsent supersession, LAPSED→CANCELLED auto-transition, PAST_DUE→LAPSED auto-transition, RemoteCommand expiry) is named with both source and target.
- **Pinned evaluation orders**: conversion fee (early-bird check before late-fee product), health score (integer division truncates before clamp), insurance score (reports aggregated before average), validation priority order (1–11 in §2.8) — all stated as explicit orderings, not implied.
- **Boundary inclusivity**: retention window "on or before `lapse_date` plus 30 days — reaching the boundary exactly still qualifies"; severity bands "at least 60"/"at least 35"; cap "strictly less than"; appointment `scheduled_date` "strictly in the future"; odometer "monotonically non-decreasing" — all boundary operators preserved without fuzz.
- **`is_emergency_command` semantics**: expressed as true exactly when accepted under the `EMERGENCY_RETAINED` emergency-only path with `LOCATE` command type.
- **Logical clock**: default value `2026-09-01T00:00:00Z`, the `to_iso8601` input, the `current_utc` output, and the three time-based transitions it fires (PAST_DUE→LAPSED, LAPSED→CANCELLED, RemoteCommand expiry) all stated in §2.6.
- **`EMERGENCY_RETAINED` entitlement bundle**: pinned as automatic crash notification plus emergency `LOCATE` only; the alternate cap baseline keyed on `lapse_date` (not `current_period_start`) with the 2-command limit is explicit.
- **`emergency_only_flag` semantics**: the second branch — `ACTIVE` subscription on a tier with `allows_emergency` true and all other entitlements false — is preserved verbatim from the scaffold rather than collapsed into just the `EMERGENCY_RETAINED` case.

## Step 5: Generate Unit Tests — 2026-09-30T09:05:00.000Z

Done. Summary:

## Files written

**`test_helpers/`** (8 files):
- `types.py` — 14 status/type enums, 14 entity TypedDicts (all entities carry full common fields per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (~60 methods)
- `api_errors.py` — 23-error `ApiErrorId` enum + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` checkers
- `factories.py` — per-entity payload factories (VIN generator enforcing 17-char/no-IOQ)
- `constants.py` — crash/health/billing/insurance thresholds
- `test_users.py` — headers for all 9 roles; `make_account_headers` for the entity-backed Account role (ownership threading)
- `fixtures.py` — composite setups: `setup_account_scenario`, `convert_subscription`, `drive_to_emergency_retained`, crash/advisor/dispatch chains, stolen-case chain, `fill_remote_command_cap`, dealer/appointment/consent helpers

**`test_suite/`**: `conftest.py` + 5 test files (`test_01_crash_severity_and_health`, `test_02_subscription_lifecycle`, `test_03_stolen_vehicle_and_rbac`, `test_04_consents_coverage_and_dealers`, `test_05_entities_validations_and_auth`).

## Test counts
- Queue A (Difficulty): 35 tests — 17 of 18 instances covered with ≥2 tests each
- Queue B (Corner): 37 tests — all 37 non-stub instances covered with ≥1 test; all 5 `excluded_because` stubs left untranslated (all stub cross-references verified to resolve)
- Total: 72 tagged tests

## Instances skipped (1)
- `Difficulty/priority_pair_validation_conflict/state_precondition_beats_referential_entitlement_on_remote_command` — fails unique derivability. PRD §3.5 explicitly maps "tier lacking remote-command entitlement" to `ERR_TIER_CAPABILITY_MISSING` and never classifies a CANCELLED subscription on command creation as a priority-6 `ERR_INVALID_STATE`, so the instance's asserted outcome (state beats tier-capability) is not pinned by PRD prose. Documented in a comment in `test_03`.

## Audit results
- **Stage 2 tag audit**: every test carries exactly one `Design:` tag resolving to a real instance; no stub translated; no malformed tags.
- **Stage 1 citation audit**: all 97 citation fragments across all test docstrings verified verbatim (modulo whitespace and markdown backticks) against PRD.md; all asserted `error_id`s named in PRD prose; no `skip`/`skipif`/`xfail` markers anywhere.
- All modules compile (`py_compile` clean).

One process note: an automated docstring-rewrite script truncated the five test files mid-run; I rewrote all five files from scratch with verbatim citations and re-verified, so final on-disk content is complete and consistent.

## Step 6: Generate Implementation — 2026-09-30T09:16:00.000Z

Implementation files written in `workspace/implementation/`:
- `app.py` (2221 lines) — complete Python + Flask implementation, in-memory storage
- `start.sh` — foreground launcher (`exec python3 app.py`, reads `$PORT`, binds 0.0.0.0)
- `requirements.txt` — `flask>=2.3,<4`

Boot smoke test (orchestrator-run): `bash start.sh` with `PORT=31985` serves Flask on 0.0.0.0; requests return the PRD-standard error envelope (`data.error_id` / `meta.api_request_id`) — 404 ERR_NOT_FOUND on unknown path as expected. Clean boot confirmed.

Subagent process notes:
- The Step 6 subagent exceeded its output budget mid-session while doing unauthorized pre-verification (it ran the test suite itself, read `test_suite/`, and reached 67/72 passing with 5 open hypotheses). Its final summary was cut off. The implementation on disk is complete and boots; adjudication of its open hypotheses is deferred to Step 7's diagnostic protocol (the proper owner of test-vs-impl adjudication).
- Open hypotheses handed to Step 7 for adjudication: (a) PlanTier `code` uniqueness — subagent suspected its ERR_DUPLICATE check may be too strict for repeated `setup_account_scenario()` calls with the same code; (b) `period_remote_commands_used` — subagent planned a stored counter zeroed on renewal/conversion/reactivation rather than a window recomputation, to handle same-instant renewal boundary; (c) a suspected test-suite-internal inconsistency between test_01 (pins `//5` integer division in health_score oil-wear term) and test_04 (asserts a mean of 75 and 80 implying no `//5` for oil=88) — Step 7 must apply STEP 1/STEP 2 to determine which side is PRD-faithful and delete/fix the wrong side.

## Step 7: Run Tests and Iterate — 2026-09-30T09:35:00.000Z

All 8 rounds pass 72/72. Clean exit.

## Summary

- **Iterations run:** 3 sweeps of 8 parallel rounds each (initial diagnosis sweep + 2 post-fix sweeps).

- **Tests deleted:** none. All five originally-failing tests traced to verbatim PRD rules; every fix made the artifacts more PRD-faithful.

- **Fixes applied to `test_helpers/`:**
  - `fixtures.py` `create_tier` and `create_zone` — now look up an existing row by unique `code` / `region_code` (via PRD-declared list endpoints) and reuse it instead of blindly POSTing. Fixes the `ERR_DUPLICATE - tier code SAFETY already exists` setup failure when a test legitimately builds two scenarios sharing reference data; PRD §3.1 pins the uniqueness constraint, so the helper — not the implementation check — was at fault.

- **Fixes applied to `test_suite/`:**
  - `test_02_subscription_lifecycle.py::test_payment_failure_then_retry_resets_period_and_usage`, `test_renewal_on_active_performs_same_period_reset`, `test_cap_enforced_within_period_and_reset_on_renewal` — added `set_clock("2026-09-01T00:00:00.001Z")` before the billing event so the reset `current_period_start` is strictly later than pre-reset commands' `created_at`. The frozen logical clock made the renewal instant equal to the command instant, and PRD §3.5's closed-open window `[period_start, period_start+30d)` includes it, so the counter could never read 0 without the bump.
  - `test_04_consents_coverage_and_dealers.py::test_reports_first_order_and_empty_set_baseline` — corrected the fixture/expectation to match PRD §3.6's pinned `health_score = 100 - 8·len(dtc) - (100-oil)//5`: second report changed to `oil_life_pct=86` (score 90), expected mean 82.50. The old values (oil 88, mean 77.50) implied a formula contradicting PRD and the suite's own test_01; PRD wins.

- **Fixes applied to `implementation/`:**
  - `app.py` `find_subscription_for_vehicle` — dropped the non-terminal-status filter so a terminal (CANCELLED) subscription is still resolved and snapshotted into a crash event's `subscription_id`, as PRD §3.3 requires ("The server resolves the vehicle's subscription and snapshots it into the event's `subscription_id`... for LAPSED, CANCELLED, or missing subscriptions... persisted directly into REJECTED_NO_ENTITLEMENT"). Entitlement denial for terminal statuses was already handled in `resolve_entitlements_for_vehicle`; only the snapshot was missing. This fixed `test_lapsed_subscription_rejects_crash_event_but_active_accepts` (asserted `subscription_id` snapshot on the rejected event).

## Step 8: Finalize PRD — 2026-09-30T09:45:00.000Z

**Output file:** `workspace/PRD_FINALIZED.md`

**Line counts & delta:** PRD.md 307 lines → PRD_FINALIZED.md 307 lines (0.00% line-count delta; one in-place sentence revision on line 143).

**Change list (one bullet per change):**
- §3.3 — revise — in the "Third, entitlement is resolved" paragraph, pinned that the server resolves the vehicle's subscription regardless of its status (including terminal `CANCELLED`) and snapshots that subscription's `id` into the event's `subscription_id`, with the snapshot still recorded on `REJECTED_NO_ENTITLEMENT` events whenever a subscription exists — `implementation/app.py:315-333` (`find_subscription_for_vehicle` drops the status filter), `app.py:1132-1142` (snapshot runs before the `allows_emergency` branch and is persisted on rejected events).

**Why other step_7_diff items produced no PRD edits:**
- `test_helpers/fixtures.py` create_tier / create_zone reuse — pure fixture bug; PRD §3.1 already pins `code` and `region_code` uniqueness (`ERR_DUPLICATE` at `app.py:610`, `app.py:703-704`). No PRD silence.
- Three `test_02_*` clock bumps — fixture/test clock setup issue. PRD §3.5 already pins the closed-open window `[period_start, period_start+30d)`, and the impl (`app.py:411-421`) matches. No PRD silence.
- `test_04` health-score expectation fix — fixture values contradicted PRD §3.6's pinned formula `100 − 8·len(dtc) − (100−oil)//5`; impl (`compute_health_score`) already implements the PRD formula. PRD wins; no edit.

**Pre-edit search log (mandatory for every edit):**

Edit 1 (§3.3 entitlement paragraph):
- (a) Subject: crash-event subscription resolution + `subscription_id` snapshot semantics, including terminal statuses.
- (b) Impl paths enumerated and read:
  - `find_subscription_for_vehicle` (`app.py:315-333`) — returns most-recent subscription with no status filter.
  - `resolve_entitlements_for_vehicle` (`app.py:535-554`) — LAPSED/CANCELLED → `(sub, None, False, False, False)`; EMERGENCY_RETAINED → emergency-only bundle; TRIAL/ACTIVE/PAST_DUE → tier-driven.
  - `create_crash_event` (`app.py:1104-1152`) — snapshot at line 1134 happens before the `allows_emergency` branch and is persisted on `RECEIVED` and `REJECTED_NO_ENTITLEMENT` alike; the no-coverage branch sets `subscription_id = None` (coverage dominates before resolution).
  - `create_remote_command` (`app.py:1612-1658`) — parallel snapshot site; on rejected entitlement paths (`ERR_TIER_CAPABILITY_MISSING`, `ERR_EMERGENCY_ONLY_COMMAND`, `ERR_REMOTE_COMMAND_CAP_REACHED`) no command is persisted, so the snapshot only lands on accepted commands.
  - `render_crash_event` (`app.py:1090-1101`), `render_remote_command` (`app.py:1600-1609`) — both surface `subscription_id` as nullable.
- (c) Wording adjustment: the phrase "if any subscription exists for the vehicle, regardless of its status" was chosen over a narrower "LAPSED or CANCELLED" enumeration to cover every status the resolver returns (TRIAL, ACTIVE, PAST_DUE, EMERGENCY_RETAINED, LAPSED, CANCELLED); "null only when the vehicle has no subscription at all" was kept narrow because the no-coverage path does set `subscription_id = None` — but that path is covered by the existing "coverage is consulted … no entitlement check is reached" sentence in the preceding paragraph, so it does not contradict the new sentence's scope (which is inside the entitlement step). The §3.5 remote-command snapshot wording was left untouched because the new §3.3 sentence is scoped to crash events.

## Step 9: Complete PRD — 2026-09-30T09:55:00.000Z

**Source:** `workspace/PRD_FINALIZED.md` (307 lines, 47,607 chars) → **Output:** `workspace/PRD_COMPLETED.md` (309 lines, 53,114 chars). Char delta: **+5,507**. Diff touches 27 paragraphs.

**Counts:** 21 ambiguity-pins, 5 mismatch-revisions (one edit — §2.8 — bundles three ordering clarifications, of which the cap-window piece is a mismatch fix; counted below by their dominant nature).

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):**

- §2.1 — revise — ambiguity — clock setter performs no auth/role check at all; ingestion endpoints accept headerless calls, require `SystemIngestion` only when headers are supplied — app.py:561-573, 1106-1109, 1716-1720, 1762-1765
- §2.1 — insert — ambiguity — Account-role ownership for vehicle-descendant resources (crash events, remote commands, diagnostics, appointments) scopes through the vehicle; flat lists filter silently; stolen-case reads have no Account ownership check — app.py:791-792, 1200-1202, 1686-1688, 1833-1835, 1989-1991, 1479-1510
- §2.2 — insert — ambiguity — `api_request_timestamp` uses wall clock; unknown paths/methods return `ERR_NOT_FOUND` (404) — app.py:122-123, 159-166
- §2.3 — insert — ambiguity — limit/offset clamping and non-integer fallback; `created_at` ties broken by `id` — app.py:230-245
- §2.4 — revise — ambiguity — entity `created_at`/`updated_at` stamped from the logical clock — app.py:211-218, 221-223
- §2.6 — insert — ambiguity — missing/malformed `to_iso8601` → `ERR_INVALID_REQUEST`; time-based transitions also fire lazily on subscription and remote-command endpoints — app.py:563-570, 911/925/944/955/964, 1615/1664/1675/1721/1735
- §2.8 — insert — ambiguity — body-carried identifiers: existence checked after body well-formedness, ownership after existence — app.py:868-875, 1243-1249
- §2.8 — insert — ambiguity — crash severity-threshold evaluated right after body well-formedness — app.py:1122-1125
- §2.8 — insert — mismatch — remote-command order is coverage → entitlement → cap (§2.8's list places cap window at (8), before coverage/entitlement at (10)) — app.py:1622-1646
- §2.9 — revise — ambiguity — missing `CoverageZone` row treated as no coverage — app.py:1128-1130, 1622-1624, 1544-1546
- §3.1 — insert — ambiguity — vehicle registration into a zoneless region → `ERR_INVALID_REQUEST` — app.py:762-763
- §3.2 — insert — ambiguity — subscription creation: unknown vehicle → 404, other-account vehicle → 403, unknown tier_code → `ERR_INVALID_REQUEST`; RETIRED tiers subscribable — app.py:871-878
- §3.2 — revise — mismatch — `next_renewal_date` null in every non-ACTIVE status including TRIAL — app.py:895
- §3.2 — insert — ambiguity — retention with non-ACTIVE vehicle → `ERR_INVALID_STATE` — app.py:1037-1039
- §3.3 — insert — ambiguity — REJECTED_NO_COVERAGE events carry `subscription_id` null even when a subscription exists — app.py:1129-1131
- §3.3 — insert — ambiguity — multiple subscriptions resolve to the most recently created — app.py:326-333
- §3.3 — revise — ambiguity — missing psap_id → `ERR_NOT_FOUND`; exact `location_payload` fields; dispatch carries `vehicle_id`/`psap_id`/`acknowledged_at`; creation response already LOCATION_SENT — app.py:1247-1274
- §3.3 — insert — ambiguity — PSAP registration fields and `accepts_location_transfer` default true — app.py:1379-1395
- §3.4 — revise — ambiguity — non-ACTIVE vehicle and open-case violations both → `ERR_INVALID_STATE`; open = REPORTED/VERIFIED/SLOWDOWN_ARMED/SLOWDOWN_EXECUTED — app.py:1445-1452
- §3.4 — revise — mismatch — arm-slowdown from any non-VERIFIED status → `ERR_SLOWDOWN_NOT_VERIFIED` (PRD said only "unverified case") — app.py:1537-1538
- §3.4 — insert — ambiguity — execute-slowdown precondition failures → `ERR_INVALID_STATE` — app.py:1556-1560
- §3.5 — revise — mismatch — acceptance gate order rewritten to coverage → entitlement → cap (PRD said entitlement → coverage → cap) — app.py:1621-1646
- §3.5 — insert — ambiguity — command `subscription_id` null when no subscription; LAPSED/CANCELLED/missing subscription → `ERR_TIER_CAPABILITY_MISSING` — app.py:535-554, 1632-1634, 1651
- §3.5 — insert — ambiguity — PENDING is transient; creation response presents the command as SENT — app.py:1653
- §3.5 — revise — mismatch — `is_emergency_command` is true only under the EMERGENCY_RETAINED path, not for every LOCATE — app.py:1654
- §3.6 — revise — ambiguity — odometer compared against the maximum existing value; equal accepted — app.py:1781-1786
- §3.6 — insert — ambiguity — `scheduled_date` must be `YYYY-MM-DD` (else `ERR_INVALID_REQUEST`); missing vehicle/report references → `ERR_NOT_FOUND`; no report-to-vehicle cross-check — app.py:1928-1940
- §3.6 — insert — ambiguity — confirm against non-ACTIVE dealer → `ERR_INVALID_STATE` — app.py:2021-2022
- §3.7 — insert — mismatch-by-omission — creation of INSURANCE_PROGRAM_SHARING also enforces the DRIVING_DATA_COLLECTION dependency (`ERR_CONSENT_DEPENDENCY_MISSING`); supersession covers REVOKED priors too — app.py:2114-2126, 2099-2104
- §3.7 — insert — ambiguity — `effective_score` computed once at each entry into GRANTED and stored; not recomputed on read — app.py:2137-2138, 2217-2218

**Post-Step-9 verification (orchestrator-run):** Step 9 touched PRD prose only — implementation, test_helpers, and test_suite were unchanged — but a fresh 8-round stability sweep was re-run anyway: all 8 rounds pass 72/72 (results.final.{1..8}.json).
