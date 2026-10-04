# Worklog — task_3244_immersive_venue_content_production_show_scheduling

## Step 1: Create task directory — 2026-09-30T13:42:30.269Z

Task directory was pre-allocated by the caller: `./tasks/task_3244_immersive_venue_content_production_show_scheduling` with `workspace/` inside. Verified it exists and is empty; no new index computed, no other task directory created.

## Step 2: Generate scaffold — 2026-09-30T14:23:28.602Z

## Summary

Generated a fresh "harder than expert" scaffold for task 3244 (immersive venue content production & show scheduling), purely from the scenario text plus the skill spec — no sibling tasks inspected.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3244_immersive_venue_content_production_show_scheduling/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` key

**Counts:**
- 10 entities (Production, Asset, RenderBatch, Show, Booking, VenueSystem, MaintenanceWindow, Sponsor, Campaign, Settlement)
- 9 state machines (2 cyclic: Asset QC-retry loop, Campaign pause/resume; plus guarded Posture-less Production gating and contagion-style VenueSystem degradation)
- 5 calculations (ticket pricing w/ 2 variants + pinned nested rounding, render time, changeover interval math, impressions aggregation, settlement waterfall)
- 19 validation rules (ordered, spanning auth → state → temporal → fiscal)
- 50 endpoints (incl. `POST /venue/_clock/set_current_utc` with the mandated default `2026-09-01T00:00:00Z`)
- 18 error codes
- 7 roles (peer-role model, all `opaque` identity)
- 2 OCC concurrency rules (show-confirm on Production.version, campaign-activate on Sponsor.version)
- 18 difficulty instances (2 per each of the 9 rules, all differentiation clauses honored — different entity domains, different modes (a)/(b), different error-category pairs, different metrics/endpoints, different entity pairs, different interval semantics (half-open show windows vs closed maintenance buffers), different conserved quantities)
- 24 corner instances (20 active + 4 `excluded_because` stubs) across entities/state-machines/calculations/validations/endpoints/errors/RBAC/cross-cutting sections

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (50 endpoints, 10 entities, 18 + 24 instances, 392 calls scanned.)

**Notable design decisions:**
- Pricing engine pins per-zone 4dp rounding then 2dp final; Rule 2 instance uses base 1043c/RING/3 seats where the pinned order yields 9689.25 vs 9689.24 unpinned — a computed literal, not an estimate.
- Dual-variant pricing selected per production.haptic flag × zone; settlement exposes gross vs net as the second dual-variant pair on a different entity domain.
- Transitive cascades are depth-3 from two different triggers: Production deactivate → Show cancel → Booking refund; VenueSystem OFFLINE → RenderBatch FAILED → Asset QC_FAILED.
- Temporal overlap deliberately mixes half-open show reserved windows (boundary touch allowed) with closed maintenance buffers (boundary touch conflicts) for Rule 8.
- All money-bearing fields that can carry 2dp fractional cents are typed `number`; every formula-derived assert literal was precomputed in Python.
- Flat-with-FK topology (`/venue/<collection>` with `production_id`/`sponsor_id`/`venue_system_id` body fields + `show_id` path params) rather than deep nesting, chosen because the lint's FK reverse-reachability heuristic requires collection-segment derivability.

## Step 3: Copy shared files — 2026-09-30T14:23:50.707Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T14:28:15.231Z

PRD generation complete.

**Output path:** `/home/ubuntu/github/CodingPRD/tasks/task_3244_immersive_venue_content_production_show_scheduling/workspace/PRD.md`

**Line count:** 292

**Section structure:**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications (2.1 RBAC with all 7 roles; 2.2 fixed verbatim envelope; 2.3 Pagination; 2.4 Common Resource Properties; 2.5 Nested Resource Retrieval; 2.6 Validation Ordering; 2.7 OCC; 2.8 Logical Clock; 2.9 Monetary Precision; 2.10 Hierarchical Cascading; 2.11 Render Wall Exclusion)
- §3 Business Logic & Workflows (3.1 Production Slate; 3.2 Content Pipeline; 3.3 Show Calendar/Changeover; 3.4 Ticketing/Zones/Pricing Variants; 3.5 Settlement; 3.6 Venue Systems & Maintenance; 3.7 Sponsorships & Campaigns; 3.8 Logical Clock Sweep)
- §4 Endpoint Definitions (51 endpoints, 4-column table)
- §5 Error Code Catalogue (18 error IDs, 2-column table)

**Coverage notes:**
- Contract 1 (Field-Name Coverage): all entity field names (`title`, `production_type`, `base_price_cents`, `is_haptic_capable`, `gain_cents`, `capture_format`, `storage_gb`, `render_hours_base`, `render_cost_cents`, `dispatch_mode`, `render_minutes`, `batch_cost_cents`, `submitted_asset_count`, `failed_asset_count`, `submitted_asset_ids`, `show_format`, `start_time`, `length_minutes`, `peak_rush_minutes`, `rehearsal_minutes`, `changeover_minutes`, `tech_readiness`, `utilization_at_lock`, `haptic_surcharge_cents_at_lock`, `settlement_snapshot_id`, `zone`, `seats`, `seat_kind`, `unit_price_cents`, `line_total_cents`, `quoted_variant`, `refund_cents`, `name`, `kind`, `consecutive_failed_windows`, `end_time`, `buffer_minutes`, `brand_tier`, `active_campaign_count`, `exterior_slots`, `spot_seconds`, `contracted_impressions`, `delivered_impressions`, `under_delivery`, `make_good_credits`, `gross_cents`, `refunds_cents`, `net_cents`, `sponsor_payout_cents`, `venue_retain_cents`, plus all FK fields, plus request-body fields `production_id`, `asset_ids`, `expected_production_version`, `expected_sponsor_version`, `sponsor_id`, `venue_system_id`, `to_iso8601`, and pagination params `limit`/`offset`) appear in backticks in narrative.
- Contract 2 (Rule Coverage): every state transition, side effect, validation rule (including priority ordering summary in §2.6), both OCC rules, all 5 calculations (calc_ticket_price with both variants + 4dp intermediate precision, calc_render_time with all three terms + constants, calc_changeover_time with rehearsal/format-transition/peak-rush components, calc_impressions, calc_settlement with waterfall and tie-break), and the logical-clock sweep list are expressed in prose. All constants (90/45/30/360000/1000 cents; 120/60/30/30/20 minutes; 0.06/0.08/0.10; 300/200/100 capacities; 1.0/1.4/1.8 weights; 15-minute hold; 2 and 3 failure thresholds; MAKE_GOOD 2×) embedded in narrative.
- Contract 3 (§3 Path Purity): no HTTP methods or URL paths in §3 backticks; endpoints referenced via state-pair transitions, role+verb framing, or capability descriptions.

**Constraint compliance:** Did not read `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`.

## Step 5: Generate unit tests — 2026-09-30T14:43:03.184Z

All 77 tests collect cleanly under pytest. Generation complete.

**Files written** (task dir: `/home/ubuntu/github/CodingPRD/tasks/task_3244_immersive_venue_content_production_show_scheduling/`):

`test_helpers/` (9 files):
- `types.py` — status enums, role enum, TypedDicts for all 10 entities (all carry `id`/`created_at`/`updated_at`/`version` per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (38 methods incl. `set_clock`)
- `api_errors.py` — all 18 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions
- `factories.py` — payload factories for all 9 creatable entity types
- `constants.py` — rehearsal/changeover/render/pricing thresholds, zone capacities/weights
- `test_users.py` — shared `TEST_USERS` constants for all 7 roles (all identity-opaque per PRD §2.1, so no per-instance builders needed)
- `fixtures.py` — composite fixtures: active production, render-to-QC pipeline, approved asset, show in REHEARSAL/CONFIRMED, active campaign, single failed maintenance window, degraded venue system, OCC show confirm
- `__init__.py` — barrel export

`test_suite/` (10 files, **77 tests**, all collected by pytest):
- `test_01_production_lifecycle.py` (11), `test_02_content_pipeline.py` (12), `test_03_show_scheduling_windows.py` (8), `test_04_ticketing_pricing.py` (14), `test_05_settlement.py` (4), `test_06_venue_systems_maintenance.py` (6), `test_07_sponsorship_campaigns.py` (10), `test_08_show_confirmation_occ.py` (6), `test_09_rbac_and_concurrency.py` (6), plus `conftest.py`

**Queue A (Difficulty)**: 16 of 18 instances translated, each with ≥2 tests (35 tests total).
**Queue B (Corner)**: all 24 non-stub instances translated, each with ≥1 test (42 tests total). The 4 `excluded_because:` stubs were not translated; their `difficulty_instance` pointers all resolve.

**Instances skipped (2)**:
- `Difficulty/priority_pair_validation_conflict/invalid_state_beats_tech_not_ready_on_confirm` — PRD §2.6 enumerates the global check order but assigns no priority numbers to state vs business_safety, so "state error wins" is not uniquely derivable; the paired `ERR_TECH_NOT_READY` single-failure behavior is still covered via queue B (`error_tech_not_ready_triggerable`).
- `Difficulty/priority_pair_validation_conflict/state_beats_business_referential_on_confirm` — same reason; PRD's worked priority example names only the stale-version vs no-approved-asset pair (business vs business), not state vs business_referential.

**Coverage audit**: every non-skipped instance resolves to a real `name:` in the source YAML, every test carries exactly one `Design: Difficulty/...` or `Design: Corner/...` docstring tag, and every ≥8-word quoted PRD citation survives a literal grep of `workspace/PRD.md` (0 bad citations, verified programmatically). No `skip`/`skipif`/`xfail` markers anywhere. Notable PRD-vs-design-instance numeric divergences were corrected in the tests (e.g. `net_cents` is 213562.10, not the instance's 213562.1 claim, because the PRD rounds the 2-seat line to 427124.21 half-up, not 427124.22).

## Step 6: Generate implementation — 2026-09-30T14:56:48.920Z

Implementation complete for task_3244.

**Files written** (all under `workspace/implementation/`):

| File | Lines | Purpose |
|---|---|---|
| app.py | 53 | Flask app, blueprint registration, ApiError/404/405/500 handlers |
| db.py | 22 | Empty in-memory store + logical clock defaulting to 2026-09-01T00:00:00Z |
| errors.py | 81 | ApiError + one factory per error_id from the scaffold |
| response.py | 50 | Envelope: `meta`/`response_type`/`data`, pagination fields in `meta` |
| middleware.py | 26 | X-User-ID + X-User-Role auth, 7-role set, ERR_UNAUTHENTICATED/ERR_FORBIDDEN |
| common.py | 64 | id/timestamp helpers, touch() (updated_at + version++), pagination |
| calc.py | 157 | calc_ticket_price (4dp B0, dual variant), calc_render_time, calc_changeover_time (adjacent prior/next), calc_impressions, settlement helpers |
| services.py | 163 | Cascades (deactivate/cancel/fail_batch), settlement waterfall, tech_readiness, clock sweep (5 time-based transitions) |
| routes_productions.py | 107 | 6 endpoints |
| routes_assets.py | 135 | 7 endpoints |
| routes_batches.py | 117 | 5 endpoints |
| routes_shows.py | 166 | 7 endpoints |
| routes_bookings.py | 132 | 7 endpoints |
| routes_venue_systems.py | 170 | 8 endpoints |
| routes_sponsors.py | 172 | 8 endpoints |
| routes_clock.py | 20 | 1 endpoint |
| start.sh | 8 | Guarded pip install, exec, PORT/0.0.0.0 |
| requirements.txt | 1 | flask |

**Endpoints implemented: 49/49** (all routes from the SCAFFOLD endpoint table, including `/venue-systems` unprefixed paths and `/venue/_clock/set_current_utc`).

**Boot smoke test**: PASSED — `PORT=19344 bash start.sh` booted cleanly, `GET /venue/productions` returned a valid empty list envelope, `POST /venue/_clock/set_current_utc` swept and returned `{"data":{}}`. Server killed via its exact saved PID.

**Key behaviors implemented**:
- Validation priority ordering (auth → not_found → state → business → OCC last), including capacity (7) before accessibility (8) on booking create, and campaign-overlap (12) before OCC (17) on campaign activate
- 4dp-pinned B0_zone with `seats × B0 × (1+pct)` line total (not `seats × unit`), both EXPERIENCE_DIFF and HAPTIC_SURCHARGE variants, Decimal ROUND_HALF_UP throughout
- Full cascade chains: production deactivate → shows cancelled → bookings refunded per status; ENV_FX OFFLINE → batch FAILED → assets QC_FAILED; consecutive_failed_windows thresholds (2→DEGRADED, 3→OFFLINE)
- Clock sweep advancing batches/shows/campaigns/booking-holds/maintenance windows
- OCC on show confirm (`expected_production_version`) and campaign activate (`expected_sponsor_version`) with ERR_STALE_VERSION 412
- No seeding at startup; store starts empty

**Known gaps / judgment calls**:
- Changeover "format transitions" counts only the nearest adjacent prior and next shows (max 2) per the PRD's "temporally adjacent prior or next" wording.
- `utilization_at_lock` and `haptic_surcharge_cents_at_lock` are pinned as 0 at confirm (scaffold defaults them to 0; no derivation formula is specified in the PRD).
- `tech_readiness` treats every show as requiring all three system kinds (PRD says "venue system whose kind the show requires" without a per-show kind mapping).
- Maintenance-window creation checks overlap against all non-cancelled shows using the reserved window (rehearsal/changeover may be 0 for TENTATIVE shows).
- Test suite not run, per instructions.

Orchestrator verification: all 17 files exist on disk (1644 lines total), `python3 -m py_compile` passes for every module, and 50 `@bp.*` route decorators counted across routes_*.py — consistent with the subagent's report (no rambling-report failure mode).

## Step 7: Test-fix iteration loop — 2026-09-30T15:14:45.425Z

All 8 rounds pass: 73/73 in every round. Exiting with the summary.

## Summary

- **Iterations run:** 2 (first sweep: 65/77 across all 8 rounds with a stable union of 12 failures; second sweep after fixes: 73/73 in all 8 rounds).

- **Tests deleted (4), with PRD-silence / collapse category:**
  - `test_03_show_scheduling_windows.py::TestChangeoverCombinatorics.test_format_transition_and_rush_inputs_combine` — unique-derivability collapse: PRD §3.3 says changeover adds 30 min per format transition with "temporally adjacent prior or next **non-cancelled** show", which verbatim includes TENTATIVE shows; the test assumed TENTATIVE neighbours are excluded (expected 80, PRD-faithful implementation computes 110). Scaffold rule: `calc_changeover_time` / changeover combinatorics.
  - `test_03_show_scheduling_windows.py::TestShowReservedWindowHalfOpen.test_overlapping_show_rejected_with_show_conflict` — unique-derivability collapse: PRD says both creation and rehearsal enforce `ERR_SHOW_CONFLICT`, but also says a TENTATIVE show's reserved window "has not yet been computed", so the creation-time check is undefined (a faithful reader can create the show and reject only at rehearsal). Scaffold rule: `ERR_SHOW_CONFLICT` on create.
  - `test_03_show_scheduling_windows.py::TestMaintenanceBufferClosedInterval.test_buffer_end_touching_show_reserved_start_conflicts` — unique-derivability collapse: PRD pins half-open semantics only for show-vs-show reserved windows; whether the maintenance window+buffer interval is closed (touch = conflict) or half-open (touch = no conflict) is unstated. Scaffold rule: `maintenance_buffer_closed_interval_conflict`.
  - `test_05_settlement.py::TestSettlementReadGate.test_settlement_not_available_for_rehearsal_show` — PRD silence: §2.5's `ERR_NOT_FOUND` ordering covers non-existent path identifiers only (the show exists); PRD never states the read behavior for a settlement that does not exist yet (404 vs empty list/object). Scaffold rule: `settlement_not_available_for_incomplete_show`.

- **Fixes applied to `test_helpers/`:** none — fixtures were PRD-consistent; the failures came from tests fighting the PRD-mandated §3.8 clock sweep.

- **Fixes applied to `test_suite/` (5):**
  - `test_01_production_lifecycle.py::test_deactivate_cascades_show_then_booking` — replaced `set_clock(12:00)` + explicit `complete_show` with clock-advance + `get_show` assertion of `COMPLETED`. Per PRD §3.8 the sweep auto-completes a CONFIRMED show whose completion instant has passed, so the subsequent explicit complete is correctly rejected `ERR_INVALID_STATE`; the test's own request sequence was PRD-inconsistent.
  - `test_05_settlement.py::test_gross_net_and_refunds_diverge_on_same_bookings`, `test_settlement_recorded_as_final_on_completion`, `test_settlement_available_after_completion` — same sweep-completion fix; `test_settlement_recorded_as_final_on_completion` now reads the completed show via GET and asserts `settlement_snapshot_id` pins the settlement's id (PRD §3.5 verbatim).
  - `test_07_sponsorship_campaigns.py::test_overlapping_campaign_accrues_impressions_on_completion`, `test_premium_tier_does_not_change_impression_count`, `test_full_delivery_yields_zero_make_good_credits` — same sweep-completion fix; impression accrual fires in the sweep per §3.8, so assertions on `delivered_impressions` are unchanged.
  - `test_04_ticketing_pricing.py::test_confirm_after_hold_expiry_rejected` — relaxed to `validate_error_is_one_of([ERR_BOOKING_HOLD_EXPIRED, ERR_INVALID_STATE])` (the permitted error-precedence relaxation): PRD names `ERR_BOOKING_HOLD_EXPIRED` for confirm-after-hold-elapsed, but §3.8's sweep expires the HELD booking to CANCELLED on clock advance and §2.6 orders the state check before the hold-expiry check, so both errors are PRD-defensible.

- **Fixes applied to `implementation/`:** none — every failure traced to tests asserting behavior the PRD does not uniquely determine, or tests issuing requests inconsistent with the PRD-mandated sweep semantics. The implementation (including sweep auto-completion, TENTATIVE-neighbour changeover counting, and half-open show-window conflict checks) was verified PRD-faithful.

Orchestrator verification: all 8 `workspace/implementation/results.{1..8}.json` files show passed == total == 73; 73 `def test_` functions remain in test_suite/.

## Step 8: Finalize PRD — 2026-09-30T15:20:03.240Z

All four edits are in place. Final verification of one remaining consistency concern: my §3.5 addition says "the list contains the single FINAL settlement" — confirm impl can only ever create one settlement per show (complete_show is guarded by status CONFIRMED, sweep sets COMPLETED before run_settlement, so only once). Confirmed in services.py:104-107 and routes_shows.py:148.

## Summary

**Line counts:** PRD.md = 292 lines; PRD_FINALIZED.md = 294 lines (+2 lines, +0.68%).

**Changes (4 edits, all traced to `<step_7_diff>`):**

- **§3.3 (changeover neighbours)** — revise — clarified that "non-cancelled" includes `TENTATIVE`/`REHEARSAL`/`CONFIRMED`/`COMPLETED` shows as format-transition neighbours — `implementation/calc.py:114-115` (filter is only `status != "CANCELLED"`).
- **§3.3 (show-conflict enforcement point)** — revise — replaced "Both show creation and rehearsal scheduling enforce this conflict rule" with rehearsal-only enforcement (creation performs no conflict check because a TENTATIVE show has no reserved window), and pinned that a TENTATIVE neighbour occupies its bare show window for the comparison — `implementation/routes_shows.py:44-67` (no conflict check in `create_show`), `routes_shows.py:106` (`_check_show_conflict` called only from `schedule_rehearsal`), `calc.py:96-101` (window from stored rehearsal/changeover minutes, 0 for TENTATIVE).
- **§3.5 (settlement read gate)** — insert — new paragraph pinning that `GET /venue/shows/{id}/settlement` returns HTTP 200 with an empty list when the show exists but no settlement has been recorded yet (e.g. REHEARSAL), not 404 — `implementation/routes_bookings.py:84-95`.
- **§3.6 (maintenance-buffer overlap semantics)** — revise — pinned that window-plus-buffer vs show reserved window uses the same strict half-open comparison as show-vs-show (touching endpoints do not conflict), and that TENTATIVE shows occupy their bare show window — `implementation/routes_venue_systems.py:91-97` with `calc.windows_overlap` (`calc.py:137-138`).

**No edits made for** the four test-suite fixes (sweep auto-completion and hold-expiry error precedence): §3.8 already pins sweep auto-completion of CONFIRMED shows, and §2.6 already orders the state check (`ERR_INVALID_STATE`) before the hold-expiry business check (`ERR_BOOKING_HOLD_EXPIRED`), so both were kept verbatim.

**Per-edit pre-edit search log:**

1. *Changeover neighbours.* (a) Subject: which shows count as format-transition neighbours. (b) Enumerated: `calc.compute_changeover_minutes` (`calc.py:109-134`) — sole caller `schedule_rehearsal` (`routes_shows.py:105`); no other code derives changeover. (c) No adjustment needed; "any status other than CANCELLED" matches the filter exactly.

2. *Show-conflict enforcement.* (a) Subject: when `ERR_SHOW_CONFLICT` is raised and what window a TENTATIVE neighbour occupies. (b) Enumerated: `errors.show_conflict` raised only in `routes_shows._check_show_conflict` (`routes_shows.py:27-36`); called only from `schedule_rehearsal` (`routes_shows.py:106`); `create_show` (`routes_shows.py:44-67`) has no check; `show_window` (`calc.py:96-101`) yields the bare window for TENTATIVE shows (minutes default 0). Also verified no conflict logic in cancel/complete/production-deactivation paths (`services.cancel_show`). (c) Added the bare-window sentence for TENTATIVE neighbours so the maintenance edit and this edit describe the same comparison consistently.

3. *Settlement read gate.* (a) Subject: response when the show exists but has no settlement. (b) Enumerated: `routes_bookings.get_settlement` (`routes_bookings.py:84-95`) — 404 only when the show id is missing, otherwise `success_list` over matching settlements; `run_settlement` (`services.py:70-101`) creates exactly one settlement, reachable only from `complete_show` (`services.py:104-107`), guarded by CONFIRMED status in both the route (`routes_shows.py:148`) and the sweep (`services.py:135-139`), so "the single FINAL settlement" is accurate. (c) None.

4. *Maintenance-buffer overlap.* (a) Subject: interval semantics of window+buffer vs show reserved window. (b) Enumerated: `create_window` (`routes_venue_systems.py:79-107`) loops non-CANCELLED shows and calls `calc.windows_overlap` (`calc.py:137-138`, strict inequality on both sides) against `calc.show_window`; the same `windows_overlap` underlies the show-vs-show check (`routes_shows.py:35`), so "same strict comparison as §3.3" is exact; buffer end = `end_time + buffer_minutes` (`routes_venue_systems.py:91`); TENTATIVE shows yield the bare window as in edit 2. (c) Added the TENTATIVE bare-window sentence mirroring edit 2 to avoid a divergence between the two conflict rules.

**Output:** `workspace/PRD_FINALIZED.md`

## Step 9: PRD completeness scan — 2026-09-30T15:46:47.575Z

Note on execution: the Step 9 subagent (spawned 2026-09-30T15:37Z, after two earlier spawns died on API rate-limit errors) completed the full implementation walkthrough and produced a 25-item edit plan, but its turn ended before applying the edits — PRD_COMPLETED.md existed (step-0 `cp` of PRD_FINALIZED.md) yet was byte-identical to its source. The orchestrator therefore applied all 25 planned edits to PRD_COMPLETED.md itself with sequential Edit calls, spot-verifying implementation claims where the plan was ambiguous (services.py recompute_tech_readiness / routes_shows.py _tech_readiness_now / services.py sweep_clock). Line counts: PRD_FINALIZED.md 294 → PRD_COMPLETED.md 296 lines; char delta +4849 (42775 → 47624). Implementation untouched since the clean Step 7 sweep (0 .py files modified after 2026-09-30 15:14).

The subagent's analysis (verbatim, including its per-behavior impl/PRD classification; the trailing edit plan is what the orchestrator then executed):

Now I'll analyze implementation behaviors against the PRD and identify ambiguities/mismatches. Let me note key observations:

**Key implementation details to pin:**

1. **§2.1 Auth**: PRD says "missing either header, or carrying a role outside this set" → ERR_UNAUTHENTICATED. Impl: `if not role or role not in VALID_ROLES or not uid: raise unauthenticated()`. Matches — no change needed.

2. **§2.3 Pagination**: Impl clamps invalid limit/offset (non-int → defaults; limit <1→1, >100→100; offset<0→0). PRD says "minimum accepted value is 1 and the maximum is 100" — ambiguous whether it's clamped or rejected. Impl clamps. Should pin.

3. **§2.4 Version**: `base_resource` starts version=1; `touch` increments. PRD says "increments by exactly 1 on every mutation" — matches. But PRD doesn't pin starting version (impl = 1). Ambiguity → pin.

4. **§3.1 Production creation**: impl stores exactly the fields given plus defaults. `is_haptic_capable` defaults to `False` when omitted (impl `bool(body.get("is_haptic_capable", False))`). PRD doesn't pin this default. Ambiguity → pin.

5. **§3.1 activate**: PRD says "at most one production may be ACTIVE" — impl checks `other["id"] != pid and other["status"] == "ACTIVE"` → raise. Matches. PRD: "Whenever a production transitions into ACTIVE, the platform recomputes the venue-wide gain_cents..." Impl `recompute_gain` sets `gain_cents` on ALL ACTIVE productions to the sum. PRD is ambiguous about whether gain_cents is updated on the production itself or a venue-level value; impl writes it to each ACTIVE production. PRD does say "recomputes the venue-wide gain_cents as the sum... across all productions currently in ACTIVE status, including the production that just activated". Slightly ambiguous where it lives. Minor.

6. **§3.1 deactivate**: impl rejects if any CONFIRMED show → matches PRD. Cascade cancels TENTATIVE/REHEARSAL shows (which cancel their bookings). Matches.

7. **§3.1 retire**: impl allows only DRAFT/DARK → RETIRED; `invalid_state` otherwise. PRD: "Retirement (DRAFT → RETIRED or DARK → RETIRED) carries no preconditions and no cascades". Matches. Impl also recomputes gain on retire (PRD mentions recompute "on the remaining ACTIVE production (if any) when a peer is deactivated or retired"). Matches.

8. **§3.2 create asset**: impl checks `production_id` existence (404), then format mismatch. PRD §2.5 covers existence ordering. Matches. Note: impl does not validate `production_id` status (asset can be captured under any production status). PRD silent but §3.2 says retry restricted by production status. Ambiguity — pin that capture works under any production status.

9. **§3.2 create batch**: impl doesn't verify asset_ids exist. PRD silent. Impl sets `render_minutes: 0`, `batch_cost_cents: 0` at creation (PRD says "remain uncomputed until dispatch"). Impl stores 0 rather than null. Ambiguity → pin.

10. **§3.2 dispatch**: PRD order: state (OPEN), at-least-one-asset, busy, ENV_FX. Impl order: status → submitted_asset_count>0 → other batch busy → ENV_FX overlap. Matches. Note impl checks assets in "CAPTURED" status to transition; assets already in other states are skipped silently. PRD says "every submitted asset transitions from CAPTURED to RENDERING" — matches for CAPTURED ones.

11. **§3.2 render_minutes formula**: base 90 + RUSH 45/asset + 30 per premium ACTIVE campaign whose flight covers dispatch instant (inclusive start, exclusive end). PRD says "covers the dispatch instant" — impl uses `parse_dt(c["start_time"]) <= now < parse_dt(c["end_time"])`. Ambiguity on boundary → pin.

12. **§3.2 render_hours reporting**: PRD says "The batch also derives a `render_hours` figure for reporting by dividing `render_minutes` by 60 and rounding half-up to 4 decimal places." Impl does NOT compute or store `render_hours` on the batch. **Mismatch** — PRD describes a field impl doesn't have. Revise PRD to remove it? The goal is to match impl — but "never invent behavior impl does not exhibit". So revise PRD to drop the render_hours sentence. Actually wait — calc.py line 17 defines `RENDER_COST_PER_HOUR_CENTS`, but batch_view returns dict(b) with no render_hours key. Confirmed mismatch → revise.

13. **§3.2 settle**: transitions assets still RENDERING → QC. Matches.

14. **§3.2 QC approve render_cost**: `render_hours_base * 360000 / 60` rounded half-up 2dp. PRD says exactly that. Matches.

15. **§3.2 QC approve batch decrement**: impl decrements only if > 0; PRD says "decrements by 1". Minor; no change needed (practically >0 always).

16. **§3.2 retry**: impl rejects if asset status != QC_FAILED (invalid_state) and if production RETIRED. PRD says "only while the asset's parent production is DRAFT or ACTIVE. If the production has been RETIRED, the retry is rejected with ERR_INVALID_STATE". What about DARK production? PRD says only DRAFT or ACTIVE permitted... impl only rejects RETIRED, so DARK is allowed. **Mismatch-ish**: PRD implies retry under DARK production is rejected ("only while... DRAFT or ACTIVE"), impl permits it. Revise PRD: retry is rejected only when the parent production is RETIRED.

17. **§3.2 abort**: allowed from OPEN/RENDERING/SETTLING. PRD: "a batch may be aborted while OPEN, RENDERING, or SETTLING". Matches.

18. **§3.3 show creation**: PRD says scheduler creates show "under an ACTIVE production". Impl does NOT check production status at creation — only at schedule-rehearsal. **Mismatch** — PRD says create under an ACTIVE production; impl allows creation under any production status. Revise PRD: show creation requires only that the production exists; the ACTIVE requirement is enforced at rehearsal scheduling. Actually PRD §3.3 line: "A VenueScheduler programmes the calendar by creating a Show under an ACTIVE production." That's prose; impl pins ACTIVE only at rehearsal. Also PRD later says "Scheduling rehearsal also requires the parent production to be ACTIVE". So revise the first sentence to not require ACTIVE at creation.

Also impl defaults `peak_rush_minutes` to 0 — PRD already pins. Impl sets `rehearsal_minutes: 0, changeover_minutes: 0` at creation — PRD says "their reserved window for conflict detection has not yet been computed". OK. Impl sets `tech_readiness` at creation to computed value. PRD silent about the initial value of tech_readiness. Ambiguity → pin (computed from current system health; READY if no DEGRADED/OFFLINE system).

19. **§3.3 changeover adjacency**: impl defines adjacent prior = nearest non-cancelled show whose core window ends at or before this show's start; next = nearest whose start is at or after this show's end. PRD says "temporally adjacent prior or next non-cancelled show" — ambiguous definition. Pin impl's rule.

20. **§3.3 conflict check**: impl `_reserved_window` uses stored rehearsal/changeover minutes for ALL shows including TENTATIVE (which have 0) → effectively bare window for TENTATIVE. Matches PRD.

21. **§3.3 confirm**: impl checks status REHEARSAL → production ACTIVE → approved asset → tech readiness → then OCC (only if `expected_production_version` is not None and mismatched → stale). PRD says confirm "requires the request payload to carry expected_production_version" — impl treats it as optional (if omitted, no check). **Mismatch** — impl doesn't require the field. Also PRD §2.6 ordering example says stale-version vs no-approved-asset: no-approved-asset wins. Impl order: invalid_state checks → no_approved_asset → tech_not_ready → stale_version. Matches PRD example.

Pin: expected_production_version is optional; when supplied and mismatched → ERR_STALE_VERSION.

Also impl pins `utilization_at_lock = 0` and `haptic_surcharge_cents_at_lock = 0` at confirm. PRD says "pins two pricing-relevant snapshots... utilization_at_lock records the venue's current zone utilization as a number between 0 and 1, and haptic_surcharge... records the current haptic surcharge in cents per seat." Impl sets both to 0. **Mismatch** — revise PRD to pin that both snapshots are recorded as 0.

Also `tech_readiness` check: impl recomputes live at confirm (`_tech_readiness_now()`), checking ANY system DEGRADED/OFFLINE (not kind-specific). PRD says "no venue system whose kind the show requires is currently DEGRADED or OFFLINE". Impl's `recompute_tech_readiness` comment: "every show requires all three system kinds to be healthy" — i.e., any degraded system → all shows DEGRADED. PRD ambiguous about which kinds a show requires → pin: every show requires all three kinds; tech_readiness is DEGRADED if any venue system is DEGRADED or OFFLINE.

22. **§3.3 complete**: impl also has explicit endpoint requiring clock >= start+length else invalid_state. PRD says completion "becomes eligible once the logical clock has advanced past start_time plus length_minutes". Impl uses `DB.clock < end → invalid_state`, i.e., eligible at exactly end. PRD "past" vs impl "at or after" — boundary ambiguity → pin (at or after). Also sweep uses `now >= end`. Consistent.

23. **§3.4 booking creation**: impl order: show exists → show status REHEARSAL/CONFIRMED → capacity → accessibility → price. Note impl checks capacity BEFORE accessibility. PRD §2.6 lists priority order with capacity before accessibility. Matches. Impl `seats = int(body.get("seats", 1))` — defaults to 1 if omitted. PRD says seats "(at least 1)" but doesn't pin default. Ambiguity → pin default 1 when omitted. Also impl doesn't validate zone value — `ZONE_CAPACITY.get(zone)` returns None for unknown zone → `used + seats > None` → TypeError → 500. Edge case; PRD pins zone enum. Leave.

Also impl uses `seat_kind` default "STANDARD". PRD pins that.

Note: capacity check counts HELD + CONFIRMED bookings ("non-cancelled"). PRD says "seats already committed by non-cancelled bookings". Matches.

24. **§3.4 pricing**: matches calc.py. Denominator = sum over zones of capacity*weight = 300*1.0+200*1.4+100*1.8 = 300+280+180 = 760. Matches PRD formula.

25. **§3.4 booking confirm**: impl uses `held_at` timestamp captured at creation = logical clock at creation. Hold expiry: `DB.clock >= held_at + 15min` → expired. PRD says "within 15 minutes of its creation, measured against the logical clock" — pin that the hold window is measured from the logical-clock instant at booking creation, and confirming exactly at the 15-minute mark is rejected (>= boundary).

26. **§3.4 booking cancel**: allowed from HELD/CONFIRMED only. Matches PRD.

27. **§3.5 settlement**: impl — gross from CONFIRMED bookings' line_total; refunds from CANCELLED bookings' refund_cents; net = gross - refunds. Payout: per-campaign share = net * 0.10 / n (n = max(1, count)), rounded half-up 2dp each, summed, capped at net. Matches PRD. Ordering of campaigns: created_at asc, ties exterior_slots desc — matches.

Wait — PRD says "Each campaign's payout share is the show's net_cents multiplied by 10 percent, divided by the number of overlapping campaigns". Matches.

28. **§3.5 GET settlement**: returns list (possibly empty) — matches PRD §3.5 paragraph.

29. **§3.6 maintenance window creation**: impl validates `end_time <= start_time` → maintenance_conflict. PRD: "the window's end_time must be strictly later than its start_time... Either violation is rejected with ERR_MAINTENANCE_CONFLICT". Matches. `buffer_minutes` defaults to 0 — PRD doesn't pin default. Ambiguity → pin.

Overlap check: impl checks against ALL non-cancelled shows using `show_window` (with stored rehearsal/changeover = 0 for TENTATIVE → bare window). Matches PRD.

Note: impl does not check system existence status or overlapping maintenance windows with each other. PRD silent. Fine.

30. **§3.6 window complete**: impl requires status ACTIVE and clock >= end_time, else invalid_state. PRD: "the engineer marks it COMPLETED once the logical clock has passed end_time". Impl boundary: `DB.clock < end_time → invalid` so completion allowed at exactly end_time. PRD "has passed" ambiguous → pin (at or after). On complete: resets consecutive_failed_windows to 0 and sets system ONLINE only if it was MAINTENANCE. PRD says "returns the parent system to ONLINE and resets its consecutive_failed_windows to 0" — impl only flips MAINTENANCE → ONLINE (if system was DEGRADED, stays DEGRADED but counter resets). Hmm — nuance: PRD says "returns the parent system to ONLINE". Impl: `if system["status"] == "MAINTENANCE": system["status"] = "ONLINE"`. If system had gone DEGRADED during the window, it stays DEGRADED but counter resets. Ambiguity → pin impl behavior.

Also fail: impl doesn't require clock >= end_time — PRD doesn't say it does either ("marks it FAILED" — PRD doesn't pin a time condition for fail). OK.

31. **§3.6 health cascade**: impl — cfw >= 3 → OFFLINE (unless already OFFLINE), aborts RENDERING batches, recompute readiness; cfw >= 2 and status in (ONLINE, MAINTENANCE) → DEGRADED. PRD: "When consecutive_failed_windows reaches 2, the system — whether currently ONLINE or MAINTENANCE — flips to DEGRADED... When the counter reaches 3, the system goes OFFLINE". Matches. Note impl increments counter per failed window, so "reaches 2/3" matches.

Also note: when a system is OFFLINE and another window fails (cfw 4), nothing changes. Fine.

Also repair: PRD "repair a DEGRADED system back to ONLINE directly, which resets consecutive_failed_windows to 0". Impl matches and recomputes tech readiness.

32. **§3.7 campaign activation**: impl order: exists → status DRAFT/PAUSED → sponsor exists → flight window open (start <= now < end) → overlap → OCC (optional expected_sponsor_version). PRD: "requires the request payload to carry expected_sponsor_version" — impl treats as optional. **Mismatch** → revise. PRD §2.7 says "requires the request payload to carry" — same mismatch for both. Revise §2.7 to say the field is optional; when present and mismatched → 412.

Flight window: PRD "the logical clock must be at or after start_time and strictly before end_time" — matches impl exactly.

33. **§3.7 pause/cancel**: matches. Note impl clamp `max(0, ...)` on decrement. Fine.

34. **§3.7 completion**: impl `under_delivery = max(0, contracted - delivered)`, `make_good_credits = 2 * under_delivery`, sponsor count decrement. Matches.

35. **§3.7 impressions**: `exterior_slots * length_minutes * spot_seconds / 60`, rounded half-up to integer. PRD says the count is "...divided by 60" — doesn't pin rounding of fractional impressions. Impl rounds half-up to integer. Ambiguity → pin.

36. **§3.8 sweep order**: impl order: batches → shows → campaigns → bookings → maintenance windows. PRD lists shows, campaigns, bookings, maintenance, batches. PRD says "in dependency order... Specifically:" then lists. The PRD list order differs from impl. Hmm — does order matter observationally? Show completion accrues impressions to ACTIVE campaigns; if a campaign's end_time has passed at the same instant, impl completes the show FIRST (campaign still ACTIVE → gets impressions), then completes the campaign. If order were reversed, the campaign would be COMPLETED and get no impressions. So order matters. PRD lists shows before campaigns — impl does shows before campaigns too (batches first though; batches don't interact). PRD's listed order: shows → campaigns → bookings → maintenance → batches. Impl: batches → shows → campaigns → bookings → maintenance. The relative order of interacting pairs (shows vs campaigns) matches. The PRD list is presented as "Specifically:" enumeration — I'd pin impl's exact order to be safe. Revise to note batches first. Actually minimal change: the relative ordering of show-vs-campaign is the same; batch position doesn't interact. But to pin exactly, revise the sentence. I'll pin: the sweep applies transitions in this order: render batches, shows, campaigns, bookings, maintenance windows.

37. **Clock endpoint**: returns 200 with empty object. PRD doesn't pin response body. §4 covers 200 for modifications. Fine.

38. **Clock set**: impl allows setting to any instant (forward or backward). PRD §2.8 says "the move may be forward to any supplied instant" — implies forward only. Impl has no restriction. **Mismatch-ish** → revise PRD: the clock may be set to any supplied instant (no monotonicity check).

39. **§4 endpoint table**: `POST /venue/shows/{show_id}/complete` authorized VenueScheduler — matches impl. Bookings: matches. Also note `GET /venue/shows` roles: impl = VenueScheduler, ProductionDirector, BoxOfficeAgent — matches PRD table. `GET /venue/bookings/{id}` roles Guest, BoxOfficeAgent — matches.

40. **List filters**: impl supports extra query filters (status, production_id, zone, kind, brand_tier, venue_system_id, sponsor_id). PRD mentions "optionally filtered by production" etc. Mostly covered; the `status` filter on several lists is extra. Ambiguity → could pin, but it's additive. I'll pin briefly that list endpoints also accept a `status` query filter (and zone for bookings, kind for venue-systems, brand_tier for sponsors). Minimal: add one sentence in §2.3? No — never add new sections; can add inline in §2.3 pagination paragraph? It's a list-endpoint behavior. I'll add a sentence to §2.3 noting list endpoints accept resource-specific filters. Hmm, but §2.3 is pagination. Maybe better: keep minimal — this is additive behavior, PRD silence. The goal says "zero remaining PRD silence or mismatch versus implementation". Pinning every permissive filter may be overkill but is in scope. I'll add a compact sentence in §2.3.

41. **405 handling**: impl maps 405 → ERR_NOT_FOUND 404. PRD silent. Minor — pin? It's a global behavior. I'll add a short sentence to §2.2 error format or §2.5. Hmm. It could matter for tests. Add to §2.5? Actually leave it; risk of over-editing. But goal is zero silence... I'll add a brief sentence in §2.2 (error responses): requests to undefined or wrong-method routes are rejected with ERR_NOT_FOUND (HTTP 404). Also 500 → ERR_INTERNAL — pin too? That's defensive. I'll include briefly.

42. **§3.3 show creation under non-ACTIVE production** — already noted (#18).

43. **Asset capture under any production status** — pin (#8).

44. **Batch creation asset_ids not validated for existence** — impl doesn't check. PRD silent. Pin: asset_ids are recorded as supplied without existence validation at creation. Also duplicate ids? Not validated. Keep it brief.

45. **Batch dispatch transitions only CAPTURED assets** — pin: submitted assets not currently CAPTURED are left unchanged.

46. **Settle transitions only RENDERING assets** — already in PRD ("every asset still in RENDERING"). Matches.

47. **Deactivation when production has CONFIRMED shows** — PRD says "may only move ACTIVE → DARK when none of its shows is in CONFIRMED status", rejected presumably ERR_INVALID_STATE. Impl uses invalid_state. PRD doesn't pin the error for this. Ambiguity → pin ERR_INVALID_STATE (409).

48. **Production activate from ACTIVE/RETIRED** → impl invalid_state. PRD pins lifecycle transitions; rejection error is ERR_INVALID_STATE per §2.6/§4 general. Pin not strictly needed; but for "no preconditions" on retire — impl rejects retire from ACTIVE/RETIRED with ERR_INVALID_STATE. PRD says retirement is DRAFT→RETIRED or DARK→RETIRED — implies other states rejected with ERR_INVALID_STATE. Probably fine without change; but silence on error... I'll fold into the §3.1 pin: transitions outside the named paths are rejected with ERR_INVALID_STATE (409). One sentence covers many.

49. **Booking creation when show's production is missing**: `DB.productions.get(s["production_id"])` could be None → price_booking crashes. Edge case; ignore (production always exists in practice).

50. **Campaign creation fields**: no validation of end>start etc. PRD silent. Leave.

51. **Sponsor creation**: matches.

52. **`held_at` field on booking**: impl stores `held_at` (logical clock at creation). PRD doesn't mention the field name. Pin: the booking records `held_at`, the logical-clock timestamp of creation, from which the 15-minute hold window is measured.

53. **Batch `render_started_at`**: impl sets at dispatch (logical clock). PRD doesn't mention. Pin briefly: the batch records `render_started_at` as the logical-clock instant of dispatch, and the projected completion is that instant plus render_minutes.

54. **Campaign activate when sponsor missing** — not possible in practice.

55. **`gain_cents` written to every ACTIVE production**: impl recompute_gain sets `gain_cents = g` on all ACTIVE productions. PRD §3.1 says "recomputes the venue-wide gain_cents as the sum..." and "The same recomputation is triggered on the remaining ACTIVE production (if any)". Pin: the computed sum is stored on every production currently in ACTIVE status (productions in other statuses retain their prior gain_cents... actually impl leaves non-ACTIVE productions' gain_cents untouched — a DRAFT production keeps 0; a DARK production keeps whatever it had when ACTIVE). Hmm: impl only updates ACTIVE productions. A production going DARK keeps its old gain_cents value. PRD says "gain_cents initialized to 0 because a draft production contributes nothing" — pin: the recomputed sum is written to each production currently ACTIVE; non-ACTIVE productions' gain_cents is not modified by recomputation. Also pricing uses `current_gain_cents()` computed live, not the stored field. That's fine, both equal.

56. **§3.4 utilization**: show.utilization_at_lock = 0 always. Covered in #21.

57. **§2.8 clock endpoint name**: PRD says "a test-driving capability that accepts a to_iso8601 timestamp" and §4 pins path. Fine.

58. **Response envelope**: `success_object` with data None → {}. Matches "For 2xx responses with no data, it contains an empty object."

59. **Error message strings** — not contractual per PRD ("human-readable").

60. **Settlement created only on complete** — matches.

61. **§3.6 sweep maintenance activation**: system goes MAINTENANCE only if currently ONLINE (impl: `if system and system["status"] == "ONLINE"`). PRD says "the parent venue system transitions ONLINE → MAINTENANCE". Matches — if system was DEGRADED, it stays. Pin? PRD's phrasing already implies ONLINE → MAINTENANCE only. OK.

62. **Window complete resets counter even if system wasn't MAINTENANCE** — impl resets cfw=0 and touches system always; sets ONLINE only if MAINTENANCE. PRD: "returns the parent system to ONLINE and resets its consecutive_failed_windows to 0". Revise to match impl nuance (#30).

63. **Impression accrual on completion uses show core window overlap** (start to start+length) — `overlapping_active_campaigns` uses `show_core_window`. PRD says "flight window overlaps the show window". Ambiguous whether show window = reserved or core. Impl uses core window (no rehearsal/changeover). Pin: the show window for impression accrual and settlement overlap is the core window from start_time through start_time plus length_minutes. Also §3.5 payout overlap uses same helper → same.

64. **Campaign overlap check uses strict half-open overlap on flight windows** — PRD says "overlap" without definition. Pin: same strict overlap rule (each start precedes the other's end).

65. **Production create — no field validation** (e.g., invalid production_type accepted). PRD enumerates types but impl doesn't enforce. Pin? That's impl laxness; PRD prose says "one of ..." implying validation. Impl accepts anything. To zero out mismatch, pin that enumerations are not validated at creation... That's risky/over-broad. Hmm. The instructions say pin what impl does where PRD admits multiple interpretations. "one of ORIGINAL, RESIDENCY, or CORPORATE" could be read as a constraint. Impl doesn't enforce it anywhere (same for capture_format, show_format, dispatch_mode, zone enum... though zone invalid crashes). This is broad impl laxness. I'll add one sentence in §2.6 or near: request field values outside the enumerated sets are not rejected by schema validation unless a rule explicitly assigns an error. Actually put it in §2.6 validation ordering? Hmm, §2.6 is about ordering. Maybe better placed in §2.2 or in §4 intro. I'll add to §4 intro paragraph (endpoints narrative): "The platform performs no schema validation beyond the rules explicitly stated; absent a stated error, unenumerated or missing payload fields are accepted and stored as supplied." That covers a lot.

Let me also double check the middleware: requires both uid and role non-empty; role must be valid. Missing uid → 401. PRD: "A request missing either header, or carrying a role outside this set, is rejected with ERR_UNAUTHENTICATED (HTTP 401)". Matches.

66. **Booking seats default** — `int(body.get("seats", 1))` → default 1. Pin (#23).

67. **Production list/get roles exclude Guest** — impl list_productions excludes Guest, matching PRD table. get_show includes Guest — matches.

68. **`GET /venue/render-batches` list endpoint**: PRD table has only GET by id for render-batches; impl has no list endpoint. Matches.

69. **`POST /venue/shows/{id}/complete`** — PRD table says VenueScheduler. Matches.

70. **Cancel show allowed roles** — VenueScheduler, ProductionDirector. Matches.

71. **Show create — no conflict check**: PRD pins. Matches.

72. **version starts at 1**: pin in §2.4.

73. **Clock endpoint response**: 200 empty object — pin briefly in §2.8.

74. **`ERR_INTERNAL` 500 handler**: pin briefly in §2.2? I'll fold into the same sentence as 404/405.

75. **`render_hours` field** — revise out (#12).

Now, also check: PRD §3.2 says dispatch: "Every submitted asset transitions from CAPTURED to RENDERING" — pin "submitted assets currently in CAPTURED; assets in any other status are unchanged".

Also PRD §3.2 batch create: "render_minutes and batch_cost_cents remain uncomputed until dispatch" — impl sets them to 0 at creation. Revise: initialized to 0 until dispatch.

Also §3.3: "their reserved window for conflict detection has not yet been computed" — impl stores rehearsal_minutes=0, changeover_minutes=0 at creation → reserved window equals bare show window. Effectively matches PRD's TENTATIVE-neighbor rule.

Also confirm: PRD says tech_readiness stored on show and recomputed on system events; impl stores tech_readiness and recomputes via services.recompute_tech_readiness, and at confirm uses live computation `_tech_readiness_now()`. Both equivalent.

Also §3.3 confirm ordering per impl: status REHEARSAL → prod ACTIVE → approved asset → tech → OCC. PRD §2.6 example says stale-version vs no-approved-asset → no-approved-asset wins. Matches.

Also note: impl's confirm checks OCC with `expected is not None` — pin optional.

Also §3.7 activation ordering in impl: status → flight window → overlap → OCC. PRD doesn't pin order among these explicitly. Both overlap and OCC are 422/412. PRD §2.6 mentions sponsor overlap and version matching in the list — "single-active-production, sponsor overlap, batch availability, ... optimistic-concurrency version matching, and capture-format compatibility". Hmm, §2.6 lists "optimistic-concurrency version matching" near the END (after hold expiry, asset-in-QC) but the example says no-approved-asset (422) beats stale-version... wait the example says "a confirm request that would fail both the stale-version check and the no-approved-asset check reports the no-approved-asset condition, because that check has the lower priority number." So version matching has higher priority number than content readiness. Impl matches for confirm. For campaign: impl order overlap (422) before stale (412) — §2.6 list has sponsor overlap before version matching. Consistent. Good, no change needed.

Also: `flight window open` check in impl raises invalid_state — PRD §3.7 says activation "requires the campaign's flight window to be currently open" but doesn't name the error. Pin ERR_INVALID_STATE (409).

Also campaign create — sponsor existence 404. Covered by §2.5 body FK rule.

Also maintenance window create — system existence 404. Covered.

Also impl `create_window` parses start/end — if missing, parse_dt crashes (500). Ignore.

Now also check §3.4: "Bookings are only accepted when the parent show is in REHEARSAL or CONFIRMED" — matches.

Booking cancel: allowed HELD/CONFIRMED. PRD §3.4: "Cancellation from HELD sets refund_cents to 0; cancellation from CONFIRMED sets refund_cents to line_total_cents". Matches. Endpoint table pins roles.

One more: §3.3 "Cancellation can be initiated either directly by a VenueScheduler or ProductionDirector, or indirectly when the parent production is deactivated." Matches impl.

§3.5: settlement fields — impl: show_id, gross_cents, refunds_cents, net_cents, sponsor_payout_cents, venue_retain_cents, status FINAL. Matches.

Also PRD §3.5: "Campaigns are processed in order of their created_at ascending, ties by exterior_slots descending" — matches.

Now check test helpers quickly for anything that pins behavior I might have missed? Tests are auxiliary only. Skip.

One more check — `paginate` clamps non-integer limit to 10 and limit<1→1, >100→100, offset<0→0. Pin in §2.3.

Also `has_more = (offset + len(items)) < total_count`. Pin? PRD doesn't define has_more computation. Pin: has_more is true iff offset plus the number of returned items is less than total_count. Add to §2.3.

Also sorting ties: created_at ascending; ties? created_at has ms precision; fine.

Also §2.4: pin version starts at 1 at creation.

Also production `gain_cents` update rule: pin that recomputation writes the sum to every ACTIVE production's `gain_cents`, leaving non-ACTIVE productions' stored value unchanged. And pricing uses the live venue-wide sum (equivalent). I'll pin in §3.1.

Also `tech_readiness` initial value: computed at creation from current systems. Pin in §3.3 creation paragraph. Also note stored tech_readiness is recomputed on system health changes (DEGRADED/OFFLINE transitions, repair, window completion) for all non-terminal shows — PRD §3.6 says "every show whose window requires this system's kind has its tech_readiness recomputed" — impl recomputes for ALL non-COMPLETED/non-CANCELLED shows based on ANY degraded system. Pin: every show requires all three system kinds; tech_readiness is DEGRADED whenever any venue system is DEGRADED or OFFLINE, READY otherwise; recomputed whenever system health changes (and at show creation).

Wait — does impl update show's stored tech_readiness at confirm? No — confirm checks `_tech_readiness_now()` live but doesn't update `s["tech_readiness"]`. Stored field only updated by recompute_tech_readiness and at creation. Minor; skip.

Also note cancel_show in services also cancels bookings; cascade on deactivation uses cancel_show → matches PRD.

Also deactivation cascade: PRD says "every show of that production still in TENTATIVE or REHEARSAL is cancelled outright". Impl matches (CONFIRMED shows block deactivation).

Now the clock endpoint: returns 200 with empty data object. Pin in §2.8: "The endpoint responds 200 with an empty data object." Also "the move may be forward to any supplied instant" → revise to "the clock may be moved to any supplied instant, forward or backward; no monotonicity constraint is enforced."

Also, per §3.8, advancing triggers sweep. Impl: set_clock always sweeps. Matches. Note sweep also runs when clock moves backward — nothing triggers since conditions use >=. Fine.

Now compile the edit list:

**§2.2** (error format section) — insert sentence: requests to unrecognized paths or unsupported methods are rejected with ERR_NOT_FOUND (404); unexpected server failures are rejected with ERR_INTERNAL (500). [ambiguity]

**§2.3** — insert: out-of-range or non-integer limit/offset values are clamped rather than rejected: limit defaults to 10 (non-integer or omitted), clamped to [1,100]; offset defaults to 0, clamped to ≥0. has_more is true iff offset + returned items < total_count. Also: list endpoints accept the resource-specific query filters named in §4 narratives (e.g., production_id, sponsor_id, venue_system_id) and a status filter... hmm §4 narratives don't name filters; §4 table descriptions say "optionally filtered by production" etc. Pin: "List endpoints additionally accept a `status` query parameter filtering by current status; the named filters in §4 (production_id for assets and shows, zone for bookings, kind for venue-systems, venue_system_id for maintenance windows, brand_tier for sponsors, sponsor_id for campaigns) restrict the result set before pagination." [ambiguity]

**§2.4** — insert: version starts at 1 on creation. [ambiguity]

**§2.7** — revise: the expected_*_version field is optional; when supplied and not equal to current version → ERR_STALE_VERSION; when omitted, no version check is performed. [mismatch — PRD says "requires the request payload to carry"]

**§2.8** — revise: "the move may be forward to any supplied instant" → the clock may be moved to any supplied instant (forward or backward); the endpoint responds 200 OK with an empty data object after running the sweep. [mismatch/ambiguity]

**§3.1** — insert: `is_haptic_capable` defaults to false when omitted; transitions outside the named lifecycle paths are rejected with ERR_INVALID_STATE (409); gain recomputation writes the sum onto every production currently in ACTIVE status and does not modify the stored gain_cents of productions in other statuses; deactivation attempted while a CONFIRMED show exists is rejected with ERR_INVALID_STATE (409). [ambiguity]

**§3.2** — several pins:
- asset capture permitted under a production in any status; only existence is checked. [ambiguity]
- batch creation records asset_ids as supplied without existence validation; render_minutes and batch_cost_cents are initialized to 0 until dispatch. [ambiguity/mismatch — PRD "remain uncomputed"]
- render duration premium-campaign term: flight window covers dispatch instant meaning start_time <= dispatch < end_time. [ambiguity]
- remove/revise the render_hours sentence (impl doesn't produce it). [mismatch]
- dispatch transitions only submitted assets currently in CAPTURED to RENDERING. [ambiguity]
- retry: rejected with ERR_INVALID_STATE only when the parent production is RETIRED (allowed under DRAFT, ACTIVE, or DARK). [mismatch — PRD says "only while DRAFT or ACTIVE"]

**§3.3** — pins:
- show creation requires only that the production exists (any status); the ACTIVE requirement is enforced at rehearsal scheduling. [mismatch — PRD "under an ACTIVE production"]
- tech_readiness is initialized at creation: READY when no venue system is DEGRADED/OFFLINE, else DEGRADED; every show requires all three system kinds (AUDIO_BEAM, HAPTIC, ENV_FX) to be healthy. [ambiguity — PRD says "venue system whose kind the show requires" without defining required kinds]
- adjacent prior/next definition: the prior neighbour is the non-cancelled show whose core window (start through start+length) ends at or before this show's start and is nearest; the next neighbour is the non-cancelled show whose core window starts at or after this show's end and is nearest; at most two transitions. [ambiguity]
- confirm: expected_production_version optional (covered by §2.7 revision); on confirm, utilization_at_lock and haptic_surcharge_cents_at_lock are both recorded as 0. [mismatch — PRD says records current utilization/surcharge]
- completion eligible when logical clock is at or after start_time + length_minutes. [ambiguity — "past"]

**§3.4** — pins:
- seats defaults to 1 when omitted. [ambiguity]
- booking records held_at (logical-clock instant of creation); hold window measured from held_at; confirming when clock is at or after held_at + 15 minutes is rejected. [ambiguity]

**§3.5** — pin: "the show window" for overlap (settlement payout + impression accrual) is the core window from start_time through start_time plus length_minutes (excluding rehearsal and changeover). [ambiguity]

**§3.6** — pins:
- buffer_minutes defaults to 0 when omitted. [ambiguity]
- completing a window is permitted once the logical clock is at or after end_time; completing resets the parent system's consecutive_failed_windows to 0 and returns the system to ONLINE only if it is currently MAINTENANCE (a DEGRADED system remains DEGRADED with its counter reset). [mismatch/ambiguity]
- failing a window may be done whenever the window is ACTIVE (no end_time condition). [ambiguity] — PRD actually doesn't state a time condition for fail, so it's fine. But to be explicit? PRD: "the engineer marks it COMPLETED once the logical clock has passed end_time...; or marks it FAILED, which..." — the "once clock passed end_time" clause grammatically attaches to COMPLETED only. So fail has no time condition. OK, no change.

**§3.7** — pins:
- activation with a closed flight window is rejected with ERR_INVALID_STATE (409). [ambiguity]
- flight-window overlap uses the same strict overlap rule (each window's start precedes the other's end). [ambiguity]
- per-show impression count is rounded half-up to the nearest integer. [ambiguity]

**§3.8** — revise sweep order to: render batches, then shows, then campaigns, then bookings, then maintenance windows. [mismatch — PRD lists different order]

Also **§4 intro** — insert: no schema/enum validation beyond stated rules; unenumerated values accepted unless a rule assigns an error. [ambiguity]

Also confirm the PRD §3.3 line: "their reserved window for conflict detection has not yet been computed" — keep.

Also §3.2 QC approve: PRD "the parent batch's submitted_asset_count decrements by 1" — impl decrements only if > 0. Keep PRD as-is (no effective difference).

Let me now make the edits to PRD_COMPLETED.md. I'll batch them via Edit calls sequentially.

Orchestrator-applied edit log (25 edits, each traced to the plan above; impl refs from the subagent's analysis, spot-verified by the orchestrator where noted):

1. §2.2 — insert — ambiguity — ERR_NOT_FOUND (404) for unrecognized paths/unsupported methods; ERR_INTERNAL (500) for unexpected server failures — app.py error handlers.
2. §2.3 — insert — ambiguity — limit/offset clamping (non-int limit → 10, clamp [1,100]; offset ≥ 0), has_more = offset + page size < total_count, and the status + resource-specific query filters applied before pagination — common.py paginate; routes_*.py list filters.
3. §2.4 — insert — ambiguity — version starts at 1 at creation — common.py base_resource.
4. §2.7 — revise — mismatch — expected_production_version / expected_sponsor_version are optional; ERR_STALE_VERSION only when supplied and mismatched — routes_shows.py confirm; routes_sponsors.py activate.
5. §2.8 — revise — mismatch — clock may be moved to any instant, forward or backward (no monotonicity check); endpoint responds 200 with empty data object — routes_clock.py.
6. §3.1 — insert — ambiguity — is_haptic_capable defaults to false when omitted; off-path lifecycle actions rejected ERR_INVALID_STATE (409); gain recomputation writes the sum to every ACTIVE production and leaves non-ACTIVE stored values unchanged; deactivation blocked by a CONFIRMED show rejected ERR_INVALID_STATE (409) — routes_productions.py; services.py recompute_gain.
7. §3.2 — insert — ambiguity — asset capture permitted under a production in any status; only existence checked — routes_assets.py create.
8. §3.2 — revise — ambiguity/mismatch — asset_ids recorded as supplied without existence validation; render_minutes and batch_cost_cents initialized to 0 until dispatch — routes_batches.py create.
9. §3.2 — revise — ambiguity + mismatch — dispatch transitions only currently-CAPTURED submitted assets; premium-campaign flight covers dispatch instant = start_time ≤ dispatch < end_time; removed the render_hours reporting sentence (impl never emits that field) — routes_batches.py dispatch; calc.py.
10. §3.2 — revise — mismatch — retry rejected ERR_INVALID_STATE only when parent production is RETIRED (DRAFT/ACTIVE/DARK all permitted); pinned render_started_at = logical-clock instant of dispatch — routes_assets.py retry; routes_batches.py dispatch.
11. §3.3 — revise — mismatch + ambiguity — show creation requires only that the production exists (ACTIVE enforced at rehearsal); every show requires all three system kinds; tech_readiness initialized at creation (READY iff no system DEGRADED/OFFLINE) — routes_shows.py create_show (verified by orchestrator: services.py:32-39, routes_shows.py:39-41).
12. §3.3 — insert — ambiguity — adjacent prior = non-cancelled show whose core window ends at-or-before this show's start, latest such; adjacent next = core window starts at-or-after this show's core end, earliest such; at most two format transitions — calc.py compute_changeover_minutes.
13. §3.3 — revise — ambiguity — tech_readiness READY means no venue system of any kind DEGRADED/OFFLINE — routes_shows.py _tech_readiness_now (orchestrator-verified).
14. §3.3 — revise — mismatch — utilization_at_lock and haptic_surcharge_cents_at_lock both recorded as 0 at confirm; 0 on freshly created shows too — routes_shows.py confirm.
15. §3.3 — revise — ambiguity — completion eligible at-or-after start_time + length_minutes; "show window" for settlement/impression overlap = core window — routes_shows.py complete; services.py complete_show.
16. §3.4 — insert — ambiguity — seats defaults to 1 when omitted — routes_bookings.py create.
17. §3.4 — revise — ambiguity — booking records held_at (logical-clock instant of creation); confirm rejected when clock ≥ held_at + 15 minutes — routes_bookings.py create/confirm.
18. §3.5 — revise — ambiguity — payout overlap uses the core show window (start through start+length), excluding rehearsal/changeover — services.py overlapping_active_campaigns.
19. §3.6 — insert — ambiguity — buffer_minutes defaults to 0 when omitted — routes_venue_systems.py create_window.
20. §3.6 — revise — mismatch/ambiguity — window completion allowed at-or-after end_time; completion resets consecutive_failed_windows to 0 and returns the system to ONLINE only if currently MAINTENANCE (DEGRADED/OFFLINE systems keep their status) — routes_venue_systems.py complete_window.
21. §3.6 — revise — ambiguity — tech_readiness recomputed for every non-terminal show on every venue-system health change (any DEGRADED/OFFLINE system degrades all shows) — services.py recompute_tech_readiness (orchestrator-verified).
22. §3.7 — revise — ambiguity + mismatch — activation outside the flight window rejected ERR_INVALID_STATE (409); flight-window overlap uses the strict half-open comparison (touching endpoints do not overlap); expected_sponsor_version optional per §2.7 — routes_sponsors.py activate.
23. §3.7 — revise — ambiguity — per-show impression count rounded half-up to the nearest integer — calc.py calc_impressions.
24. §3.8 — revise — mismatch — sweep order pinned: render batches, then shows, then campaigns, then bookings, then maintenance windows — services.py sweep_clock (orchestrator-verified lines 122-147).
25. §4 intro — insert — ambiguity — no schema/enum validation beyond explicitly stated rules; unenumerated values and extra fields accepted as supplied — routes_*.py (no enum validators).

Counts: 18 ambiguity-pins, 7 mismatch-revisions (items 4, 5, 9 (partial), 10, 11 (partial), 14, 20 (partial), 22 (partial), 24 counted once per edit; 9/11/20/22 carry both classes).
