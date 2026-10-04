# Worklog — task_3040_storm_ready_limited_menu_activation_continuous_operations

## Step 1: Create Task Directory — 2026-09-29T15:54:54.904Z

Pre-allocated task directory `./tasks/task_3040_storm_ready_limited_menu_activation_continuous_operations/` confirmed to exist with `workspace/` inside. No new index computed; no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-29T16:43:17.458Z

Generated a fresh expert-level scaffold for **task_3040_storm_ready_limited_menu_activation_continuous_operations** at `/home/ubuntu/github/CodingPRD/tasks/task_3040_storm_ready_limited_menu_activation_continuous_operations/`, without reading any sibling task:

**Design shape**
- Archetype: posture-driven gating + compliance/audit; hybrid topology (StormEvent→Unit tree with flat cross-cutting crews/assets/lodging/relief); parallel state-machine shape; hierarchical-override role model (5 opaque operational roles + segregation-of-duties on checklist review).
- 14 entities, 73 endpoints (incl. `/ops/_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z default), 30 error codes, 12-priority validation stack, 2 OCC concurrency rules (storm actions, menu deactivate).
- All endpoints live under a single `api_prefix: /ops` so every FK has a reverse-reachability GET (lint check f).

**Difficulty mechanics (§1.8, 18 instances, all 9 rules × 2, all differentiated per §0.5)**
- Dual-variant relief reimbursement: conservative (capped at pledge, 4630) vs actual (overage paid, 5556) on ReliefPledge; tier-priority menu derivation vs independent cash-only axis on Unit.
- Combinatorial: tiered bonus + tax-inclusive floor extraction (mode a, 3704 at the exact 3000-cent tier boundary); cold-hold deadline pinned evaluation order (mode c, fails at 14:00:01, passes at exactly 14:00:00).
- Cyclic StormEvent WATCH↔WARNING with warning_count; parallel 4-axis resource state on Unit.
- Transitive cascades from two distinct triggers (checklist approve → menu FULL → close gate; condition report → tier recompute → activation auto-END).
- Priority conflicts on different error-category pairs (business_fiscal vs OCC/state; business_referential vs business_temporal).
- Boundary precision on assigned_from (`>=`, via start) and hours_since_shift_change (`>= 12`, via start/complete stamping).
- Temporal overlap with two interval semantics: half-open instants for crew assignments vs calendar-date sets for lodging nights.
- Compensating invariants: lodging fund money conservation and asset fleet cardinality across return→redeploy.

**§1.9 corner design**: 49 instances across all nine guide sections (entities/state machines/calculations/validations/endpoints/errors/RBAC/cross-cutting/consistency), including 11 `excluded_because:` stubs that resolve to real §1.8 instance names.

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (73 endpoints, 554 calls scanned, 0 violations). All formula-derived asserts were computed by executing the formulas in Python. A programmatic audit confirmed: no design keys inside SCAFFOLD.yaml, 30/30 error codes used, 79 unique instance names across both design files, no forbidden concurrency vocabulary.

## Step 3: Copy Shared Files — 2026-09-29T16:43:30.553Z

Copied `./INSTRUCTION.md` → `tasks/task_3040_storm_ready_limited_menu_activation_continuous_operations/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-29T16:47:53.696Z

Generated `/home/ubuntu/github/CodingPRD/tasks/task_3040_storm_ready_limited_menu_activation_continuous_operations/workspace/PRD.md` from `SCAFFOLD.yaml` per the `prd-bench-doc-generator` skill. The difficulty/corner design files were not read.

Structure: §1 Introduction (3 paragraphs, domain-driven), §2 with 9 subsections (roles/identity prose for all 5 opaque roles, verbatim §2.2 block, pagination, common properties incl. `ChecklistItem`/`CashDrop` without `updated_at`/`version`, OCC, always-open shift-clock, logical clock, nested retrieval + full 12-priority validation order, integer-cents precision), §3 with 8 subsections (storm lifecycle, condition reports/menu-tier derivation, menu activation, assets/allocations, reopening checklist + cold-hold gate order, cash-only ops, crew/lodging, relief pledges/reporting cadence), §4 four-column endpoint table (73 endpoints), §5 two-column error catalogue (30 errors).

Hard contract results:
- **Contract 1 (Field-Name Coverage): PASS** — entities[].fields: 73 required, 73 present; endpoint inputs (incl. `to_iso8601`, `expected_storm_event_version`, `expected_unit_version`, `lodging_fund_top_up_cents`, query params, clock/report output fields `current_utc`, `generated_at`, `units_reported`, `pledges_finalized`, `per_unit`): all present; 0 missing.
- **Contract 2 (Rule Coverage): PASS** — validation priority order 1–12 expressed as a numbered list in §2.8 plus per-workflow in §3 (checklist submit gates in pinned order in §3.5); both OCC rules named with field, error, and 412 status; all state-machine transitions (StormEvent 8, Unit/Resource cascades, CrewMember 4, CrewAssignment 3, Asset 5, AssetAllocation 4, LodgingBooking 1, MenuActivation 2, ChecklistRun 4, ReliefPledge 2) with preconditions, error IDs, and side effects; all 9 calculations in precise prose (menu-tier derivation with power dominance and payment exclusion, pinned 4-step cold-hold deadline with `reported_at`-max/`created_at` tie-break and strictly-greater comparison, lodging night enumeration, both relief reimbursement variants with all constants 250/3000/8000/0/1000/2500/100/800 and floor tax-inclusive extraction, run-report sweep ordering, 12-hour inclusive shift boundary, 48-hour inclusive pre-position window, half-open assignment overlap with terminal-storm exclusion, calendar-date lodging overlap); endpoint side effects and applies_to scopes covered; sibling branches (deescalate dual-source, activate dual-source, cancel dual-source, retire dual-source, approve/reject symmetric) rendered with equal density.
- **Contract 3 (§3 Path Purity): PASS** — 332 backtick tokens scanned in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combinations (verified programmatically).

Other checklist items confirmed: §2.2 matches the verbatim source file byte-for-byte (placeholder `req_RANDOMALPHANUM123456`, timestamp, `"data": { }` unchanged); limit default 10/min 1/max 100, offset default 0, `created_at`-ascending sort with the `reported_at`-ascending exception for condition reports stated; all 30 `ERR_*` IDs appear in prose and the §5 table.

## Step 5: Generate Unit Tests — 2026-09-29T17:30:00.000Z

Orchestrator note: two Step 5 subagents were accidentally launched concurrently (the intended Step 6 impl-gen call was a duplicate of the Step 5 prompt). Both wrote to test_helpers/ and test_suite/; the second agent fully rewrote both directories (8 files in test_helpers, conftest + 8 files, 87 tests in test_suite) and its write completed last. Post-hoc verification by the orchestrator confirmed the on-disk state is coherent: all 87 tests collect cleanly via `pytest --collect-only`, and docstring tag audit shows exactly 18 unique `Design: Difficulty/...` tags and 49 unique `Design: Corner/...` tags (all 18 §1.8 instances and all non-stub §1.9 instances referenced). The surviving state corresponds to the second agent's summary, recorded below.

## Generated output

**`test_helpers/`** (8 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_3040_storm_ready_limited_menu_activation_continuous_operations/test_helpers/`):
- `types.py` — 14 status enums + role enum + 15 entity TypedDicts; `ChecklistItem` and `CashDrop` carry only `id`/`created_at` (common_fields: false honored)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~50 methods, `/ops` prefix)
- `api_errors.py` — all 30 error IDs with PRD §5 HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions + confirmed-pledge invariant checker
- `factories.py` — input-field-only payload factories
- `constants.py` — cold-hold 4h, shift 12h, preposition 48h, relief rate/tier/bonus/penalty/tax constants
- `test_users.py` — 5 opaque role headers (all roles are `opaque`, so shared constants are canonical)
- `fixtures.py` — composite setups: `setup_storm_with_unit`, storm lifecycle walks (`activate/escalate/deescalate_storm`), `setup_submittable_checklist`/`setup_submitted_checklist` (outage → all-clear → five PASS items inside the cold-hold window), `setup_crew_assignment`, `setup_lodging_scenario`, `setup_asset_scenario`, `setup_relief_scenario`

**`test_suite/`** — `conftest.py` + 8 test files, **87 tests**, all collecting cleanly.

## Coverage audit (automated)
- All 12 §1.8 difficulty instances have ≥2 tests each (36 tests tagged `Design: Difficulty/...`)
- All 37 non-stub §1.9 corner instances have ≥1 test (51 tests tagged `Design: Corner/...`)
- All 12 `excluded_because:` stubs correctly have no test
- No orphan/dual/untagged tests; every docstring's last line is exactly one `Design:` tag; no skip/xfail markers; every quoted PRD sentence verified verbatim against `workspace/PRD.md` (0 misses)

## Key PRD-first adjudication calls
- **Corrected one index pre-computation**: corner instance `relief_pledge_get_returns_computed_fields_after_confirm` (10 pledged / 8 served) asserts `reimbursement_cents == 2130` by capping eligible meals at `meal_count`, but the PRD pins eligible = `served_count − overage` = 8 → gross 2000 → tax floor(1800·800/10800)=133 → **1667**. The test asserts 1667 (PRD wins over the YAML literal; the 4630 dual-variant instance is unaffected since served ≥ pledged there).
- **Kept priority-pair tests**: PRD §2.8 numbers all 12 validation layers with "an earlier failure masks every later one", which uniquely derives both pair orderings (fiscal-before-OCC for close; idleness-before-window for allocations).
- **Unit lazy-read of `hours_since_shift_change`** with a null stamp: PRD §2.6 defines the count as hours from `last_shift_change_at` and §3.8 says a null stamp leaves the sweep count unchanged — both readers converge on measuring from unit creation, so the asserted value (6h at 14:30) is uniquely derivable.
- Removed a stale duplicate test file found in the target directory (`test_01_storm_declaration_and_defaults.py`) that predated/conflicted with this generation.

## Step 6: Generate Implementation — 2026-09-29T17:53:50.269Z

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_3040_storm_ready_limited_menu_activation_continuous_operations/workspace/implementation/`:
- **`start.sh`** — guarded `pip install` (no-op once Flask is present, so per-test-server reboots stay fast), then `exec python3 app.py` in the foreground.
- **`requirements.txt`** — `flask>=3.0`.
- **`app.py`** (~2,200 lines) — single-file Flask app, in-memory store, no startup seeding. Listens on `PORT` (default 10000), binds `0.0.0.0`.

## Contract coverage

- **Envelope**: `meta{api_request_id, api_request_timestamp}`, `response_type` object/array/error, `data`; pagination fields `limit/offset/total_count/has_more` in `meta` (default 10, min 1, max 100, offset 0); error body `{error_id, message}`.
- **Auth/RBAC**: `X-User-ID` + `X-User-Role` headers, five roles, 401/403 per the endpoint table; validation priority order (auth → forbidden → existence → body-shape 422 → state 409 → food-safety gates → referential → temporal → posture → SoD 403 → fiscal → OCC 412 last).
- **Logical clock**: defaults to exactly `2026-09-01T00:00:00Z`, never wall-clock; admin-only `POST /ops/_clock/set_current_utc`; all stamped timestamps from the logical clock with 3-fractional-digit ISO 8601.
- **All 50+ endpoints** from the PRD table, including reverse-reachability reads and the flat checklist aliases.
- **State machines**: cyclic WATCH↔WARNING storm with `warning_count`; StormEvent close/de-escalate gates (ERR_UNITS_NOT_RESTORED / ERR_OPEN_CHECKLISTS / ERR_UNITS_STABILIZING); resource axes → menu-tier derivation (power dominates; payment excluded); condition-report cascades ending divergent activations and setting `cash_only_flag`; MenuActivation supersede/END; cyclic allocation RETURNED→DEPLOYED; checklist rework loop; segregation of duties.
- **Calculations**: lodging nights (check_in date through check_out−1 day; PRD's Sep10→Sep12 = 2 nights example verified), calendar-date overlap coarser than instant-level (the PRD's Sep-12 touch example verified), half-open assignment overlap with terminal-storm exclusion, conservative vs actual relief reimbursement with tier bonus and tax-inclusive floor extraction (hand-checked: 1667 / 2315 / 4167 / 11575 cent cases), 4h cold-hold with strictly-greater deadline comparison, 48h inclusive pre-position window, 12h rolling shift-change clock with lazy + sweep refresh.
- **OCC**: `expected_storm_event_version` / `expected_unit_version` required (422 if absent) and checked last (412 on mismatch).
- **Ordering under a frozen clock**: a global monotonic insertion sequence backs every `created_at ASC` / tie-break ordering so collections stay deterministic when many creates share one logical timestamp.

## Verification

Two smoke suites (~110 assertions) covering auth, OCC, storm lifecycle, cascades, checklist gates, lodging math, reimbursement math (both variants), run-report, pagination, and error IDs all pass against a fresh boot; `bash start.sh` was exercised directly on a custom port and responds immediately. No files under `test_helpers/` or `test_suite/` were read.

## Step 7: Run Tests and Iterate — 2026-09-29T18:18:26.364Z

All 8 rounds pass: 86/86 across the board.

## Summary

**Iterations run:** 3 sweeps (round 1: 67/87 with 20 deterministic failures; round 2: 82/86 after the auth-signature fix; round 3: 86/86 clean across all 8 parallel rounds).

**Tests deleted (1):**
- `test_unit_get_refreshes_shift_clock_from_logical_time` (TestShiftClockLazyRead, test_01) — unique-derivability collapse. The test asserted that a unit never stamped by any crew event lazily reports `hours_since_shift_change = 6` (anchored to creation). PRD §2.6 defines the count only as "the whole-hour count from that timestamp [`last_shift_change_at`] to the logical clock's present" with no creation-time anchor, and §3.8 affirmatively states "a null stamp leaves the count unchanged" for the reporting sweep. Two faithful PRD-only readers diverge (leave 0 vs. recompute from creation). Scaffold rule that drove generation: `Corner/entities/unit_get_refreshes_shift_clock_from_logical_time` claiming "hours elapsed since unit creation" — a scaffold-only rule absent from PRD prose.

**Fixes applied to `test_helpers/`:**
- `api_client.py` — 15 bodyless-POST client methods (`create_checklist`, `submit_checklist`, `approve_checklist`, `reject_checklist`, `rework_checklist`, `cancel_relief_pledge`, `start_assignment`, `complete_assignment`, `cancel_assignment`, `retire_asset`, `dispatch_allocation`, `return_allocation`, `cancel_allocation`, `cancel_lodging_booking`, `run_report`) had signature `(…, headers, payload=None)` while `fixtures.py` called them payload-first (`(unit_id, None, UM)`), so the headers dict landed in `payload` and requests went out with no auth headers → the 15-test `ERR_UNAUTHENTICATED` cluster. Converted all to the payload-first convention used by every other method.

**Fixes applied to `test_suite/` (test bugs, STEP 2):**
- All headers-first call sites of the above methods in test_04/05/06/07/08 updated to payload-first (`api.submit_checklist(uid, run_id, None, headers)` etc.).
- `test_lodging_cost_counts_calendar_dates_not_midnights` — asserted 3 nights for check-out exactly at midnight Sep 12; PRD's example semantics (billing spans check-in date through the day before check-out date) gives 2 nights / 18000. Corrected to the PRD-derivable outcome.
- `test_lodging_calendar_date_overlap_vs_instant_adjacency` — asserted A [Sep10 14:00, Sep11 00:30) bills 2 nights / 18000; PRD example forces 1 billed night / 9000 (the overlap gate remains touched-date based, per "coarse calendar-date intersection … merely touch the same date do conflict", so the OVERLAP assertion and its point are preserved). Fund expectation updated 982000 → 991000.
- `test_lodging_fund_conserved_across_two_bookings_and_one_cancel` — setup booking B2 [Sep11 14:00, …] touched Sep 11, which B1's stay also touches, so the PRD-required overlap gate correctly rejected the fixture's own second booking. Moved B2 to Sep 12–13 (disjoint date sets); fund-conservation assertions unchanged.
- `test_lodging_fund_exact_balance_boundary` — second booking on Sep 12–13 shared Sep 12 with B1's touched dates, so the (priority-first) overlap gate masked the fund gate the test exists to exercise. Moved the second booking to Sep 13–14 so the request passes overlap and deterministically reaches `ERR_LODGING_FUND_EXCEEDED`.

**Fixes applied to `implementation/`:** none — every failure traced to the test layer (auth-signature mismatch in helpers, four PRD-inconsistent lodging setups/assertions, one underdetermined shift-clock test). The implementation's split lodging semantics (hotel-night billing per the PRD example; touched-date overlap per the "coarse calendar-date intersection" sentence) proved PRD-faithful.

## Step 8: Finalize PRD — 2026-09-29T18:25:00.000Z

Done. PRD_FINALIZED.md written at `/home/ubuntu/github/CodingPRD/tasks/task_3040_storm_ready_limited_menu_activation_continuous_operations/workspace/PRD_FINALIZED.md`.

## Line counts and delta

- PRD.md: 330 lines; PRD_FINALIZED.md: 330 lines (0% line-count delta; two paragraphs revised in place, no sections added or removed).

## Changes (one bullet each)

- **§2.6 (shift-change clock)** — revise — added an explicit null-stamp rule: "Until the first stamp, `last_shift_change_at` is null and `hours_since_shift_change` reads zero; nothing anchors the count to the unit's creation, and neither a unit read nor the reporting-cadence sweep of §3.8 recomputes it for a null stamp"; also scoped the lazy-refresh sentence to stamped units ("(for units already stamped)") — `implementation/app.py:384-391` (`refresh_shift_clock` early-returns on null stamp), `app.py:931-932` (unit created with null stamp and count 0), `app.py:969` (GET unit), `app.py:2223` (run-report sweep). This pins the exact underdetermination that caused the Step 7 test deletion (`test_unit_get_refreshes_shift_clock_from_logical_time`) — the impl leaves a never-stamped unit at 0 rather than recomputing from creation.
- **§3.7 (lodging)** — revise — split the single "night set" notion into two: billed nights are "each calendar date (UTC) from check-in's date through the day before check-out's date" (hotel-night billing), while the overlap gate uses a distinct, coarser "touched-date set" = every UTC date intersected by the half-open stay — `implementation/app.py:626-639` (`booking_nights`, used for cost at `app.py:2017`) vs `app.py:642-654` (`booking_touched_dates`, used for the overlap gate at `app.py:2008-2016`). This pins the divergence Step 7 exposed (check-out exactly at midnight bills one fewer night than dates touched; instant-adjacent stays sharing a date still conflict).

## Items in the Step 7 diff that produced NO PRD edit

- The 15 `api_client.py` signature fixes and the test-suite call-site fixes: pure test-harness bugs (headers-vs-payload argument order), no behavioral content.
- `test_lodging_fund_conserved...` and `test_lodging_fund_exact_balance_boundary` fixture moves: the fixtures violated the already-specified overlap gate; PRD wording was already correct (gate priority overlap-before-fund is pinned by §2.8 item 8 vs item 11 and §3.7 "in priority order").

## Per-edit pre-edit search log

**Edit 1 (§2.6 null-stamp rule).**
- (a) Subject: behavior of `hours_since_shift_change` / `last_shift_change_at` when a unit has never been stamped.
- (b) Paths enumerated (via `grep -n "hours_since_shift_change\|last_shift_change_at"`): `app.py:384-391` (`refresh_shift_clock` — returns False on null stamp, used by both GET-unit `app.py:969` and run-report `app.py:2223`); `app.py:670-684` (`maybe_stamp_shift_change` — null stamp stamps unconditionally at assignment start `app.py:1755` and complete `app.py:1769`); `app.py:931-932` (unit creation initializes null/0); `app.py:403-404` and `app.py:2231` (view emission, pure reads). Read each region.
- (c) Adjustment: initial draft said only "reads zero"; widened to state explicitly that no reader or sweep recomputes from creation, since both `refresh_shift_clock` call sites (GET unit and §3.8 sweep) share the same null-stamp early-return — wording must cover both paths, not just the GET path the deleted test exercised.

**Edit 2 (§2.6 lazy-refresh scoping).**
- (a) Subject: which units the GET-unit lazy refresh and reporting-cadence refresh apply to.
- (b) Paths enumerated: same set as Edit 1 — `refresh_shift_clock` (app.py:384) is the single shared implementation for `app.py:969` (GET /ops/units/{id}) and `app.py:2223` (POST /ops/run-report); `maybe_stamp_shift_change` (app.py:670) is the only null-stamp writer, called from assignment start/complete only.
- (c) Adjustment: inserted "(for units already stamped)" rather than rewriting the sentence, to avoid narrowing the §3.8 sweep description (which correctly skips null-stamped units per its own "a null stamp leaves the count unchanged" clause).

**Edit 3 (§3.7 lodging nights vs touched dates).**
- (a) Subject: lodging night-count definition for cost vs the date set used for the overlap gate.
- (b) Paths enumerated (via grep for `nights|calendar|date`): `app.py:626-639` `booking_nights` (dates from check-in date through (check-out − 1 day) date — used only for `cost_cents` at `app.py:2017`); `app.py:642-654` `booking_touched_dates` (dates from check-in date through (check-out − 1µs) date — used only for the overlap gate at `app.py:2008-2016`); `app.py:2065-2074` `cancel_booking` (refunds stored `cost_cents`, never recomputes nights); `app.py:916/933/980/2018/2036` (fund seed/top-up/debit paths — no night computation). `parse_date`/`service_date` hits are relief-pledge territory, unrelated.
- (c) Adjustment: originally considered revising the existing "night" definition only; that would have broken the overlap gate (instant-adjacent stays sharing a date must conflict, which fails under a check-out-minus-one-day set — e.g. [Sep10 14:00, Sep11 00:30) would touch only Sep 10). Final wording introduces two named sets — "billed nights" for cost and the coarser "touched-date set" for overlap — preserving both the PRD's existing example (Sep 10–12 = two nights, still true under hotel-night billing) and the impl's touched-date overlap behavior; the cancel path needed no wording change since it refunds the stored cost verbatim.

## Step 9: Complete PRD — 2026-09-29T18:35:00.000Z

PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_3040_storm_ready_limited_menu_activation_continuous_operations/workspace/PRD_COMPLETED.md`.

## Summary

**Source:** PRD_FINALIZED.md (330 lines) → PRD_COMPLETED.md (332 lines), char delta **+5,211**. No sections added or removed; all changes are inline.

**Counts:** 22 ambiguity-pins, 4 mismatch-revisions (26 total edits).

### Changes

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned as wall-clock (not logical clock) — app.py:237-240
- §2.2 — revise — ambiguity — error envelope now covers 4xx and 5xx — app.py:729-733
- §2.2 — insert — ambiguity — unknown routes/methods → ERR_NOT_FOUND 404; internal failure → ERR_INTERNAL 500 — app.py:719-733
- §2.3 — insert — ambiguity — non-integer/out-of-range limit/offset → ERR_VALIDATION — app.py:332-350
- §2.3 — insert — ambiguity — filter values must be in the declared enum (is_jump_team as string "true"/"false"), else ERR_VALIDATION — app.py:781-782, 1602-1607
- §2.3 — insert — ambiguity — created_at ties broken by monotonic insertion sequence — app.py:203-215
- §2.3 — insert — ambiguity — reverse-reachability lists and checklist-item lists return the full set in one page (limit = count, offset 0, has_more false), no limit/offset accepted — app.py:2084-2094, 1226-1231, 2196-2205
- §2.4 — insert — ambiguity — created_at/updated_at stamped from the logical clock; version starts at 1 — app.py:207-214, 218-221
- §2.5 — insert — ambiguity — missing/null/non-integer expected-version field is ERR_VALIDATION; only a well-formed mismatch is ERR_STALE_VERSION (both paths) — app.py:812-818, 1108-1114
- §2.6 — insert — ambiguity — under-12h arrival/departure refreshes stored hours_since_shift_change without touch or version bump — app.py:678-684
- §2.7 — revise — ambiguity — clock endpoint "set" (not "advance"): no monotonicity; tz-less ISO inputs interpreted as UTC — app.py:123-126, 148-150
- §2.8 — insert — ambiguity — body-shape step 4 pinned: booleans rejected as integers, lower bounds only, strictly ordered ranges — app.py:310-316, 1658-1659, 2006-2007
- §3.1 — insert — ambiguity — storm activation does not cascade to units (no tier derivation from storm status) — app.py:859-866
- §3.1 — insert — mismatch — `unit_code` uniqueness is declarative, not enforced (impl performs no duplicate check) — app.py:910-937
- §3.1 — insert — ambiguity — seeded lodging_fund_cents must be ≥ 0 — app.py:916
- §3.1 — insert — ambiguity — lodging_fund_top_up_cents is required, integer, no lower bound (negative subtracts) — app.py:979
- §3.2 — insert — ambiguity — cash_only_flag written from the reported payment axis alone (stored flag never read) — app.py:1018
- §3.2 — insert — ambiguity — an all-clear report restores FULL by itself, without checklist approval — app.py:588-594, 1019-1020
- §3.2 — insert — ambiguity — axis values validated before any cascade; a malformed report ends nothing — app.py:996-999, 1021-1025
- §3.3 — insert — ambiguity — deactivation with no ACTIVE activation → ERR_INVALID_STATE before OCC; success response (200) carries the unit object — app.py:1104-1106, 1119
- §3.4 — insert — ambiguity — retirement from ALLOCATED → ERR_INVALID_STATE; RETIRED is permanently out of the allocation pool — app.py:1841-1846
- §3.4 — insert — ambiguity — re-dispatch of a RETURNED allocation re-checks nothing (window, storm status, kind match exempt) — app.py:1926-1941
- §3.5 — insert — ambiguity — note accepted/stored on PASS; re-recorded key keeps same id and re-stamps created_at; item lists returned in fixed canonical key order — app.py:1195-1216, 1225
- §3.5 — revise — mismatch — cold-hold comparison is at full timestamp precision, not "whole-hour precision" — app.py:1270-1271
- §3.5 — insert — mismatch — rework retains items and submitted_at/submitted_by_user_id until individually replaced/overwritten at resubmission — app.py:1325-1334, 1277-1279
- §3.7 — insert — ambiguity — home_unit_id may be any unit under any storm status; crew/assignment creation gates only existence — app.py:1582
- §3.7 — insert — ambiguity — assignment creation checks no storm status/posture/certification/window-start; ASSIGNED members may take further non-overlapping assignments — app.py:1640-1693
- §3.7 — revise — mismatch — start-precondition evaluation order pinned to impl: storm → jump-team → window → tier (was storm → tier → jump-team → window) — app.py:1729-1752
- §3.7 — insert — ambiguity — no member-status cascade on start (member already ASSIGNED) — app.py:1753-1755
- §3.7 — insert — ambiguity — lodging booking validates assignment/unit by existence only: any assignment status, paying unit need not match the assignment's unit — app.py:1998-1999
- §3.8 — insert — ambiguity — relief-org PATCH to its current status is a successful no-op write (updated_at/version still advance) — app.py:1422-1431
- §3.8 — insert — ambiguity — pledge creation leaves served_count/shortfall_meals/overage_meals/shortfall_penalty_cents/reimbursement_cents null until confirmation — app.py:1464-1468
- §3.8 — insert — ambiguity — run-report per_unit array ordered by storm creation order, then unit creation order — app.py:2219-2233
- §5 — insert — ambiguity — ERR_INTERNAL (500) added to the error catalogue — app.py:729-733

## Post-Step-9 Verification Sweep — 2026-09-29T18:50:00.000Z

Orchestrator-run supplementary 8-round parallel sweep after Step 9 completed (Step 9 edited PRD docs only — implementation and test suite untouched). All 8 rounds: **86/86 passed, 0 failed, 0 errors**. Final `results.1.json`–`results.8.json` retained in `workspace/implementation/`. Task pipeline complete.
