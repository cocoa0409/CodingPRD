# Worklog — task_3065_core_banking_platform_conversion_community_institution

## Step 1: Create Task Directory — 2026-09-29T19:20:03.000Z

Pre-allocated task directory verified: `./tasks/task_3065_core_banking_platform_conversion_community_institution/` with `workspace/` inside (per command args, no new index computed). Project-root `INSTRUCTION.md` present.

## Step 2: Generate Scaffold — 2026-09-29T20:30:00.000Z

All three scaffold artifacts are generated and lint-clean at `/home/ubuntu/github/CodingPRD/tasks/task_3065_core_banking_platform_conversion_community_institution/`.

## Files written

- **SCAFFOLD.yaml** — §1.0–§1.7 (no `scaffold_difficulty_design` / `scaffold_corner_design` keys). Scenario verbatim.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single top-level `scaffold_difficulty_design:` key.
- **SCAFFOLD_CORNER_DESIGN.yaml** — single top-level `scaffold_corner_design:` key.

## Design summary ("much harder than expert level")

- **Archetype**: compliance/audit + ledger reconciliation; layers: optimistic concurrency, cascading side effects, dual-variant calculation, ops-run checkpoint. Segregation-of-duties role model; flat entity topology (URLs are top-level collections under `/api/v1`, scoped by explicit `project_id`/`plan_id`/`session_id` request fields — this shape was required for the lint's FK reverse-reachability heuristic).
- **Counts**: 14 entities, 12 state machines (including cyclic Defect and AncillarySystem machines and the phase-gated ConversionProject pipeline), 7 calculations (incl. pinned daily-rounding-then-multiply accrual with ACT_365/ACT_360/THIRTY_360 day counts, waterfall service-credit with monthly cap, capped age-weight triage priority), 17 validation rows, 91 endpoints (incl. `POST /api/v1/_clock/set_current_utc` with fixed default 2026-09-01T00:00:00Z), 17 error codes, 7 roles, 2 OCC concurrency rules on ConversionProject.version.

## Difficulty design (§1.8): 18 instances, 2 per rule

Dual-variant accrual (mock 8220 vs cutover 15618) and comm wave-vs-backoff scheduling; combinatorial formulas in modes (a) triage scoring and (b) nested rounding order; cyclic machines on Defect and AncillarySystem; cascades depth-3 (product deactivate → account EXCEPTION → GL recompute) and depth-2 (defect reopen → claim DISPUTED); priority conflicts state-vs-phase-gate and temporal-vs-referential; boundaries on fee-waiver equality and session capacity; cross-entity dependencies CustomerComm→Account.frozen_flag and Enrollment→TrainingSession; temporal overlap with half-open branch-room semantics vs cross-project freeze-channel point-in-window-plus-grace; compensating invariants on GL expected sums and claim amounts.

## Corner design (§1.9): 45 active instances + 1 `excluded_because:` stub

Across sections entities (8), state_machines (7 incl. stub), calculations (5), validations (6), endpoints (4), errors (6), rbac (3), cross_cutting_layers (4), consistency_model (1). All formula-derived asserts were pre-computed by executing the formulas as code (e.g. 822 × 19 = 15618; THIRTY_360 32 days → 192000; breaches [6,26] → capped 200000).

## Validation checks run

1. `scaffold_lint.py` — final verdict: **clean lint** (91 endpoints, 14 entities, 18 + 45 instances, 922 calls scanned, 0 violations).
2. Custom audits beyond the linter: placeholder closure (0 unbound `${var}` in both design files), role↔endpoint authorization match, grounds resolvability against §1.1–§1.7, instance-name uniqueness (64 unique), and a call-by-call state-machine replay of every setup/trigger chain (the only 7 "violations" are intentional negative triggers whose asserts expect the rejection).

One design note: to satisfy the lint's FK reverse-reachability heuristic I flattened the URL topology and added six reverse-lookup sub-resource GETs (`/product-types/{ptid}/accounts`, `/gl-accounts/{gid}/accounts`, `/staff/{id}/enrollments`, `/accounts/{aid}/customer-comms`, `/ancillary-systems/{sid}/defects`, `/tasks/{tid}/dependents`); Enrollment/CutoverTask ownership fields are named `parent_session_id`/`parent_plan_id` since the parent is already in the request payload.

## Step 3: Copy Shared Files — 2026-09-29T20:31:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3065_core_banking_platform_conversion_community_institution/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-29T20:37:00.000Z

All mechanical checks pass. Final summary:

**PRD generated:** `/home/ubuntu/github/CodingPRD/tasks/task_3065_core_banking_platform_conversion_community_institution/workspace/PRD.md` — 324 lines.

**Sections covered:**
- §1 Introduction (3 paragraphs: business context, role split, three dominant design properties)
- §2 Global Specifications (2.1 RBAC with `X-User-ID`/`X-User-Role`, all 7 roles, segregation-of-duties pairs; 2.2 response envelope emitted verbatim from the canonical source file; 2.3 pagination with limit default 10 / min 1 / max 100 / offset 0 and `created_at` ascending sort; 2.4 logical clock pinned at `2026-09-01T00:00:00Z`; 2.5 common resource properties with the lighter id+created_at-only treatment for Enrollment/CutoverPlan/CutoverTask; 2.6 integer-cents precision and round-half-up daily interest; 2.7 OCC on `expected_project_version`; 2.8 full validation priority ordering; 2.9 cross-project freeze channel; 2.10 file freeze)
- §3 Business Logic in 12 subsections (program setup/phases, product design, account staging/mapping/GL, accrual + fee math in prose including the THIRTY_360 day-count formula, mock runs and balancing with the PASSED-run CLEARED→MAPPED recertification cascade, cutover planning + freeze channel, cutover weekend execution with 30-minute grace, ancillary reintegration, training/enrollment with auto-complete cascade, comm waves with 3-day window and resend backoff, defect triage with priority scoring bands, service credit waterfall with 4 covered hours / 25,000 cents-per-hour / 200,000-cent monthly cap)
- §4 Endpoint table (4 columns, all 62 endpoints) and §5 Error catalogue (2 columns, all 17 error ids)

**Self-checks run (all PASS):**
- Contract 1 Field-Name Coverage: all entity field names + endpoint input/query/path params verified present in backticks (0 missing after fixing 4 initial gaps: `status`, `claim_status`, `parent_session_id`, `parent_plan_id`)
- Contract 2 Rule Coverage: walked state machines (all transitions, preconditions, side effects incl. defect-resolve ancillary knock-back, defect-reopen claim-dispute cascade, rollback cascade, go-live comm flush exemption), all 7 calculations in precise prose (reconstruction-safe, no pseudocode, no fuzzy words), all validation rules paired with their `error_id` and priority ordering stated in §2.8, both OCC rules named with endpoint + field + `ERR_STALE_VERSION`/412, segregation-of-duties pairs stated
- Contract 3 §3 Path Purity: 521 backticked tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos
- All 17 error ids and all 7 role names appear in the PRD; no fuzzy/approximating wording detected

The two forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-09-29T21:09:00.000Z

All done. Summary:

## test_helpers/ (8 files, Stage 1)
- `types.py` — status enums for all 13 entities, role enum, TypedDicts (common-field branching honored: Enrollment/CutoverPlan/CutoverTask carry only id + created_at).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (all under `/api/v1`), `Connection: close` header to survive per-test server restarts.
- `api_errors.py` — `ApiErrorId` enum + HTTP status map (all 17 errors from §5), registered via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` checkers (GL asserts variance == converted − expected).
- `factories.py`, `constants.py` (divisors, 4h covered / 25000¢/h / 200000¢ cap, triage weights/bands, send-window days, 30-min grace, default clock), `test_users.py` (7 opaque roles + per-instance builders + `NO_AUTH_HEADERS`).
- `fixtures.py` — tiered composites: mapped-account, MOCK_CONVERSION, passed-run, cutover-planned / plan-scheduled / plan-GO / completed-task, full LIVE happy path, post-live defect and OPEN-claim scaffolding (SEV1 opened 09-21, resolved 09-24 → breach 48h, credit 200000).
- `__init__.py` barrel re-exporting framework + PRD-specific names.

## test_suite/ (10 files + conftest, 81 tests)
- test_01 projects/catalog/RBAC (13), test_02 accounts/mapping/OCC/freeze (9), test_03 accrual/fees/GL (10), test_04 mock runs/phase gates (7), test_05 cutover/go-live (8), test_06 training/enrollment (11), test_07 comms (3), test_08 defects/triage (10), test_09 service credits (7), test_10 cascades (3).

## Coverage & audit
- Queue A (difficulty): 18/18 instances translated, each with ≥2 tests.
- Queue B (corner): 45/45 non-stub instances translated (≥1 test each); the single `excluded_because` stub (`defect_reopen_cascade_on_claim`) left untranslated — its cross-reference resolves to Difficulty/transitive_cascade/defect_reopen_cascades_service_credit_dispute, which is covered by 2 tests.
- AST audit: every test has exactly one `Design:` tag; all 81 tags resolve to real instances; no duplicate per-test tagging; PRD quotation spot-check passed (only two benign multiline-quote scanner artifacts, both verified present verbatim in PRD.md).
- `pytest --collect-only` collects all 81 tests cleanly; no "scaffold" references remain in generated code.

## Skips (PRD-silence driven)
- Difficulty `priority_pair_validation_conflict/invalid_state_wins_over_phase_gate_on_finalize`, variant 2 ("finalize a RUNNING run while project is CONFIGURATION"): not emittable — mock-run creation is itself phase-gated, and PRD gives no unique derived error for that setup. The instance is covered by the state-over-phase-gate test (PRD §2.8 explicitly orders ERR_INVALID_STATE before ERR_PHASE_GATE).
- Corner `nested_resource_under_wrong_parent_returns_not_found`: the recipe's cross-project probe is not reachable through flat paths; translated to ERR_NOT_FOUND on a non-existent account id (PRD §2.8/§5 covered).
- One test (`test_account_mutation_rejected_with_frozen_after_cutover_planned`) uses an `ERR_FROZEN in (…)` assertion tightened to strict `ERR_FROZEN` on flag-exception, per PRD §2.10/§2.8's explicit freeze-before-frozen-ordering sentence.

## Step 6: Generate Implementation — 2026-09-29T21:26:00.000Z

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3065_core_banking_platform_conversion_community_institution/workspace/implementation/`):
- `start.sh` — foreground launcher; guarded dep install (`if ! python3 -c "import flask"`), `exec python3 app.py`
- `requirements.txt` — `flask>=3.0`
- `app.py` — single-module Flask app (~1100 lines) implementing all 59 endpoints

**Boot smoke-check result**: started via `PORT=18711 bash start.sh`, PID saved to a file. Verified:
- Unauthenticated `GET /api/v1/conversions` → 401 `ERR_UNAUTHENTICATED`
- Authenticated list → envelope with `meta.api_request_id`/`api_request_timestamp`/`limit`/`offset`/`total_count`/`has_more`, `response_type: "array"`
- Full happy path: project create → advance (CONFIGURATION) → product activate → account stage → map with OCC `expected_project_version=2` → advance (MOCK_CONVERSION) → mock run start+finalize → `PASSED`, `balanced=1`, `converted_total=100256`; accrual arithmetic checked exactly (`daily=8`, 32 days 2026-08-01→2026-09-01 ACT_365, `accrued=256`, `conversion_balance=100256`).
- Killed exactly the PID started (confirmed stopped).

**Design decisions**:
- **Module layout**: single `app.py` rather than routes/services split — the spec is wide (13 entities) but shallow per-endpoint; one module keeps cross-entity cascades (GL recompute, go-live, rollback, defect/ancillary knock-backs, comm flush, session auto-complete) explicit and local. Response envelope/errors/auth helpers at the top; entity sections follow.
- **State-machine engine**: hand-coded per-endpoint transition guards (state check → phase gate → freeze → side effects) rather than a generic transition table. The PRD's cascades (e.g. PASSED run flips CLEARED→MAPPED + GL recompute; defect resolve knocks linked ancillary system back; defect reopen disputes OPEN claims; rollback blocks accounts and resets baseline) don't fit a table cleanly and read more faithfully as direct code. Validation priority ordering (auth → RBAC → existence → body → OCC → state → window → reference → invariant → duplicate → eligibility → phase gate → frozen → overlap → run-in-progress → freeze channel → SoD) is encoded as statement order inside each handler.
- **Clock handling**: module-level `_CLOCK` dict holding a single `datetime`, defaulting to exactly `2026-09-01T00:00:00Z`, advanced only by `POST /api/v1/_clock/set_current_utc`. All window checks, accrual day counts, SLA deadlines, comm send windows, task grace windows use it; no wall-clock fallback. Resource `created_at`/`updated_at` derive from the logical clock; envelope `api_request_timestamp` uses real wall time (per PRD §2.2 example).
- **Storage**: plain dicts in a `DB` module-level map keyed by id, empty at boot. No seeding anywhere. Entities with `common_fields: true` get `id`/`created_at`/`updated_at`/`version` (version starts at 1, `touch()` bumps version + refreshes updated_at); enrollments and cutover plans/tasks are "light" (`id`/`created_at` only). Internal datetime objects are kept in underscore-prefixed fields (e.g. `_ws`, `_sla_deadline`) alongside the ISO strings so comparisons stay exact.
- **Precision**: accrual daily interest via `Decimal(principal) * Decimal(str(rate)) / divisor`, `ROUND_HALF_UP` to whole cents before multiplying by day count; THIRTY_360 uses the 30/360 day formula; all money stays integer cents. Service-credit breach hours use `math.ceil(seconds/3600)`, cap 200000 cents, 4 covered hours, 25000 cents/hour.
- **OCC**: only `accounts/{id}/map` and `customer-comms/{id}/schedule` require `expected_project_version` (412 `ERR_STALE_VERSION` on mismatch); both bump project version on success.
- **Freeze channel**: `freeze_channel_busy()` scans all other projects' non-ROLLED_BACK plans' tasks for `[window_start, window_end + 30min]` containing `file_freeze_start`, enforced at both plan-cutover and plan-schedule.
- **Subagent note (left as-is)**: flag-exception on a CLOSED project returns ERR_PHASE_GATE (account MAPPED→EXCEPTION allowed; project phase gate fails), since PRD §2.10's CLOSED→ERR_INVALID_STATE example mentions only `map`; deemed the reasonable PRD-consistent pick.

## Step 7: Run Tests and Iterate — 2026-09-29T21:47:00.000Z

All 8 rounds pass 80/80. Final sweep is clean.

Summary:

- **Iterations run**: 3 sweeps (each 8 parallel rounds, per-test-server isolation).
  - Round 1: 72/81 across all 8 rounds — 9 deterministic failures.
  - Round 2: 79/80 — only `test_gl_variance_visible_immediately_after_mapping` remained.
  - Round 3: 80/80 × 8 rounds, zero failures.

- **Tests deleted** (1):
  - `test_project_create_ignores_client_supplied_system_fields` (test_01_projects_catalog_rbac.py) — scaffold rule `Corner/entities/system_fields_extra_field_input_ignored` directly contradicts PRD §2.8's verbatim "no unknown fields (`ERR_INVALID_REQUEST`)" in the body well-formedness check; a PRD-faithful implementation must reject, not ignore, client-supplied `id`/`version`.

- **Test fixes** (test_suite/):
  - `test_07_customer_comms.py::test_wave_schedule_then_backoff_on_resend` — timestamp literals updated to `...T00:00:00.000Z`; PRD §2.5 mandates ISO 8601 UTC with three fractional digits for system timestamps, and the test's own verbatim PRD quote never specified a zero-fraction rendering.
  - `test_08_defects_triage.py::test_reject_fix_retains_priority_and_reopen_reresolve` — same timestamp-format fix for `sla_deadline` and `resolved_at`.
  - `test_08_defects_triage.py::test_failed_integration_retest_cycle` — `api.verify_ancillary_system(...)` → `api.verify_integration(...)` (the ApiClient method name used everywhere else; AttributeError in test code).
  - `test_04_mock_runs_phase_gates.py::test_zero_balanced_fails_then_passed_with_exceptions` — setup violated PRD §3.1's MOCK_CONVERSION phase gate (needs an ACTIVE product and a MAPPED account). Now stages and maps a gate account `b0` before advancing, flags it into EXCEPTION so run 1 still sees zero balanced accounts (FAILED), then clears it so run 2 is PASSED_WITH_EXCEPTIONS with `balanced_account_count == 2`.
  - `test_03_accrual_fees_gl.py::test_mock_finalize_then_cutover_recompute_at_cutoff_date` and `::test_same_account_yields_different_accrual_per_variant` — expected cutoff accrued interest corrected from 15618 (19 days, "clock minus one") to 16440 (20 days) and conversion balance to 10016440; PRD §3.7 verbatim: "`cutoff_business_date` [is set] to the current clock date" and "computation date set to `cutoff_business_date`", with §3.4's inclusive day count.
  - `test_01_projects_catalog_rbac.py::test_gl_variance_visible_immediately_after_mapping` — relaxed the un-derivable constant `variance == -424242` (PRD never states a staged account's `conversion_balance_cents`) to the PRD-verbatim relation `variance == converted − expected` with `expected == 424242` pinned.

- **test_helpers/ fixes**: none needed (the `verify_ancillary_system` name collision was in the test file, not the fixture; the fixture helper is untouched).

- **Implementation fixes** (workspace/implementation/app.py, 1 change, net):
  - `rollback_plan` — added `recompute_all_gls(p["id"])` after the account-blocking cascade so the GL's continuously-exposed totals (PRD §3.3: "continuously exposes") reflect BLOCKED accounts dropping out of the input set immediately after rollback. (A map-time accrual was briefly added in iteration 2, then reverted: PRD does not mandate accrual at mapping, and the correct resolution was fixing the over-pinned test assertion instead.)

## Step 8: Finalize PRD — 2026-09-29T21:54:00.000Z

Done. `PRD_FINALIZED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_3065_core_banking_platform_conversion_community_institution/workspace/PRD_FINALIZED.md`.

## Line counts

- `PRD.md`: 324 lines; `PRD_FINALIZED.md`: 324 lines (0.0% delta — three in-place sentence insertions, no sections added).

## Changes (3 edits)

- **§2.5** — insert — appended a sentence pinning that every server-stamped datetime (`created_at`, `updated_at`, `opened_at`, `sla_deadline`, `resolved_at`, `started_at`, `finished_at`, `send_after`, `send_before`, `scheduled_send_date`, plan/task window fields, clock `current_utc`) renders with exactly three fractional digits and trailing `Z` even when zero — `implementation/app.py:288-289` (`iso_ms` = `isoformat(timespec="milliseconds")`).
- **§3.3** — insert — appended a sentence to the staging paragraph pinning a freshly `STAGED` account's initial computed fields: `conversion_balance_cents == opening_principal_cents`, `cutoff_accrued_interest_cents`/`daily_interest_cents`/`monthly_fee_assessed_cents` all 0, holding until finalize/go-live recomputes them — `implementation/app.py:1115-1118`.
- **§3.6** — revise — added a rollback cascade clause: after accounts become `BLOCKED`, every project GL's three totals are recomputed so blocked accounts drop out immediately — `implementation/app.py:2765` (`recompute_all_gls(p["id"])` in `rollback_plan`).

## Step 7 items judged not to need PRD edits

- Deleted test (`system_fields_extra_field_input_ignored`): PRD §2.8 already verbatim requires rejecting unknown fields with `ERR_INVALID_REQUEST`; impl's `validate_body` (app.py:220-222) matches. Kept verbatim.
- `verify_ancillary_system` → `verify_integration`: pure test-side AttributeError (test_helpers method name), no PRD surface.
- Mock-run phase-gate fixture fix and accrual cutoff 15618→16440: fixture bugs; PRD §3.1 gate and §3.7 "computation date set to `cutoff_business_date`" + §3.4 inclusive day count already determine the corrected behavior (impl: app.py:704-714, 393-404).

## Pre-edit search log (NO-NEW-MISMATCH)

**Edit 1 (§2.5 timestamp rendering).** (a) Subject: rendering format of server-emitted timestamps. (b) Enumerated paths: `iso_ms` (app.py:288-289) and all callers — `new_common`/`new_light`/`touch` (292-310), clock endpoint `set_clock` (462-468), plan fields (653-655), task windows (2651-2652), sessions (1625-1626), comms (1963-1965, 2076), defects `opened_at`/`sla_deadline`/`resolved_at` (2156-2157, 2250), mock run `started_at`/`finished_at` (1295, 1372); confirmed all route through `iso_ms(...Z)` with `timespec="milliseconds"`, so ".000Z" is emitted for whole-second values everywhere. (c) Wording adjustment: scoped the claim to "every server-stamped datetime the API emits" with an explicit field list, and did not claim anything about echoing client-supplied `current_utc` verbatim (impl normalizes it — also consistent with the sentence, which covers the emitted rendering).

**Edit 2 (§3.3 staged-account initial balances).** (a) Subject: initial values of account computed fields at staging. (b) Enumerated paths: account creation defaults (app.py:1115-1118); `recompute_gl` (357-367, reads `conversion_balance_cents` of GL-assigned accounts — STAGED accounts have null `gl_account_id` so never enter a GL sum until mapped, at which point conversion_balance still equals principal); `finalize` `converted_total_cents` sum over all accounts (1363) — PRD §3.5 already says unmapped accounts "contribute their converted balance"; `apply_monthly_fee` fallback `(a.get("conversion_balance_cents") or 0)` (428) — fee runs only on MAPPED/EXCEPTION/CLEARED where the field is set, so the new sentence doesn't misdescribe it. (c) Wording adjustment: phrased as "until a mock-run finalization or the go-live cascade recomputes them" rather than claiming recompute at mapping (impl does not recompute at map), and avoided asserting that placeholder values persist through mapping (they coincide with principal anyway, but the PRD stays silent on that to avoid a false universal).

**Edit 3 (§3.6 rollback GL recompute).** (a) Subject: rollback cascade effects on GL totals. (b) Enumerated paths: `rollback_plan` (app.py:2751-2774) — blocks MAPPED/CLEARED/EXCEPTION accounts then calls `recompute_all_gls` (2765); `recompute_gl` (357-367) and `GL_STATUSES` (354) confirm BLOCKED drops out of expected/converted sums; the plan frozen at rollback keeps `frozen_flag` true per the same paragraph; parallel GL-recompute sites (map 1190, flag 1213, clear 1234, finalize 1357/1389, go-live 719) are unaffected by the rollback-scoped clause. (c) Wording adjustment: kept the clause strictly scoped to rollback ("every GL of the project then has its three totals recomputed") without asserting anything about other cascades; verified §2.10's freeze sentence "blocks the previously mapped inventory" remains compatible (blocking precedes the recompute, consistent with the inserted ordering "then").

## Step 9: Complete PRD — 2026-09-29T22:12:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_3065_core_banking_platform_conversion_community_institution/workspace/PRD_COMPLETED.md` produced from `PRD_FINALIZED.md`.

**Source vs output**: PRD_FINALIZED.md 324 lines / 53,210 chars → PRD_COMPLETED.md 345 lines / 64,090 chars (Δ +21 lines, +10,880 chars).

**Counts**: 24 ambiguity-pins, 5 mismatch-revisions.

**Changes** (insert = ambiguity pin, revise = mismatch fix):

- §2.1 — insert — ambiguity — unknown route / wrong method surfaces `ERR_NOT_FOUND` (404) — app.py:139-156
- §2.2 — insert — ambiguity — `api_request_id` format is `req_` + 20 lowercase hex chars — app.py:109
- §2.2 — insert — ambiguity — `api_request_timestamp` rendered with trailing `Z` — app.py:103-104
- §2.3 — revise — mismatch — out-of-range `limit`/`offset` are clamped (limit→[1,100], offset→0), only non-integer values are `ERR_INVALID_REQUEST` — app.py:327-339
- §2.3 — insert — ambiguity — `has_more` = (offset + returned count) < total_count; task list endpoints sort by `sequence` ascending (exception to `created_at` rule) — app.py:124, 2679-2683, 2700-2704
- §2.5 — insert — ambiguity — `id` is 32-char lowercase hex, no dashes — app.py:295
- §2.5 — revise — mismatch — `version` starts at 1 at creation — app.py:298
- §2.8 — insert — ambiguity — body-scoped nonexistent ids → `ERR_NOT_FOUND` (404), wrong-relationship → `ERR_INVALID_REFERENCE`; map's stale-version check precedes body GL existence — app.py:2140, 2382-2384, 1811-1812, 2609, 986, 1081, 1167-1172
- §2.10 — insert — ambiguity — rollback does not clear `frozen_flag` on blocked accounts — app.py:2761-2764
- §2.9/§3.6 — insert — ambiguity — one `ERR_FREEZE_CHANNEL_BUSY` regardless of overlap count; span membership is inclusive of both endpoints — app.py:439-454
- §3.1 — insert — ambiguity — past-date `cutover_scheduled_date` at creation → `ERR_INVALID_REQUEST` (400); advance from any other status → `ERR_INVALID_STATE` — app.py:517-521, 585
- §3.2 — insert — ambiguity — accrual legality enforced at creation as well as activation — app.py:829-831
- §3.3 — insert — ambiguity — staging rejects duplicate `legacy_account_number` with `ERR_DUPLICATE`; product cross-project/kind mismatch at staging → `ERR_INVALID_REFERENCE`; product need not be `ACTIVE` at staging — app.py:1089-1100
- §3.3 — insert — ambiguity — `new_account_number` format `NEW-` + 10-digit zero-padded sequential counter — app.py:1108
- §3.3 — insert — ambiguity — deactivation cascade does not touch `STAGED` accounts — app.py:915-919
- §3.3 — insert — ambiguity — mapping leaves accrual/fee figures untouched until recompute — app.py:1187-1191
- §3.3 — insert — ambiguity — new GL starts with all three totals at zero — app.py:996-998
- §3.3 — insert — ambiguity — flag-exception also recomputes owning GL; deactivation cascade does not recompute GLs, go-live cascade does — app.py:1212-1213, 915-919, 719
- §3.4 — insert — ambiguity — THIRTY_360 formula applied literally even when the count exceeds the calendar span — app.py:395-402
- §3.5 — insert — ambiguity — new run's initial field values (`duration_seconds`/`outcome` null, counts zero, `is_cutover_baseline` false) — app.py:1289-1304
- §3.6 — revise — mismatch — one-plan-at-a-time, not one-plan-ever: rollback frees the planning slot; rolled-back plan retained; list-plans description updated in §4 — app.py:590-672 (no plan-exists check in plan_cutover)
- §3.6 — insert — ambiguity — sequence rule pinned (unique, ≤ existing count + 1) → `ERR_INVARIANT_VIOLATION`; task start time not exposed on task record; empty plan at schedule → `ERR_PHASE_GATE`; FAILED task blocks GO with `ERR_PHASE_GATE`; rollback preserves `FAILED` tasks — app.py:2630-2634, 2561-2574, 2714-2715, 2742-2746, 2758-2760
- §3.7 — revise — mismatch — task start/complete/fail restricted exclusively to the task's `owner_role` (others → `ERR_FORBIDDEN`); start requires plan `GO` (`ERR_PHASE_GATE`); incomplete predecessor → `ERR_INVALID_STATE` — app.py:2777-2802
- §3.7 — insert — ambiguity — completion allowed at any clock ≤ window_end + 30 min (no lower bound); `duration_minutes` floored whole minutes — app.py:2815-2818
- §3.7 — insert — ambiguity — go-live does not refresh `monthly_fee_assessed_cents` — app.py:708-719
- §3.9 — revise — mismatch — auto-complete fires only on mark-attended (not no-show/cancel); certification granted at session completion in both paths — app.py:1869-1874 vs 1878-1903
- §3.9 — insert — ambiguity — enrollment has no same-project/branch constraint; `parallel_ops_certified` starts false; capacity counts RESERVED enrollments; duplicate rule allows re-enrollment after CANCELLED; marking on non-IN_PROGRESS session → `ERR_INVALID_STATE`; count recompute definitions — app.py:1804-1838, 1662-1674, 1766
- §3.10 — insert — ambiguity — comm creation checks account existence only (no status/project check) — app.py:1946-1947
- §3.10 — insert — ambiguity — scheduling account-status failure → `ERR_INVALID_STATE` — app.py:2013-2018
- §3.10 — insert — ambiguity — resend goes straight to `SENT` with backed-off schedule, no window check — app.py:2065-2079
- §3.11 — insert — ambiguity — `credit_eligible` true only when `resolved_at` strictly after `sla_deadline` — app.py:2251
- §3.11 — insert — ambiguity — defect close blocked by OPEN claim → `ERR_INVALID_STATE` — app.py:2304-2313
- §3.12 — insert — ambiguity — empty `defect_ids` → `ERR_INVALID_REQUEST`; defects need not belong to claim's project; `approved_by` starts null; approve/pay/reopen/reject re-check failures → `ERR_CREDIT_INELIGIBLE`; reject of a fully-eligible OPEN claim → `ERR_CREDIT_INELIGIBLE`; `dispute_note`/`approved_by` persist through reopen — app.py:2375-2376, 2502-2536
- §4 — insert — ambiguity — per-endpoint list-filter catalog (status/project_id/state/etc. per resource) — app.py list handlers
- §4 — insert — ambiguity — per-endpoint validation-order notes for 14 endpoints where multiple rejections could apply — app.py various
- §5 — insert — ambiguity — unexpected failures surface as `ERR_INTERNAL` (HTTP 500) — app.py:159-166
