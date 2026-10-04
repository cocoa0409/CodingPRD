# Worklog — task_3211_theatrical_house_booking_weekly_grosses_royalty_pool

## Step 1: Create Task Directory — 2026-09-30T10:43:00.000Z

Task directory `./tasks/task_3211_theatrical_house_booking_weekly_grosses_royalty_pool/` was pre-allocated (per command args); verified it exists with `workspace/` inside. No new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-30T10:59:00.000Z

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3211_theatrical_house_booking_weekly_grosses_royalty_pool/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3211_theatrical_house_booking_weekly_grosses_royalty_pool/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_3211_theatrical_house_booking_weekly_grosses_royalty_pool/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

## Counts

- **Entities (§1.1): 13** — ProductionCompany, Theatre, Production, Booking, LicenseAgreement, RoyaltyParticipant, DiscountCode, TicketOrder, WeeklyGrossReport, Settlement, StopNotice, CapitalProject, CrewAssignment
- **State machines (§1.2): 7** — Booking (9-state with cyclic withdraw/supersede paths and system auto-transitions), LicenseAgreement (supersede cycle), WeeklyGrossReport (DRAFT→SUBMITTED→REJECTED→DRAFT revision cycle), Settlement, StopNotice, CapitalProject, TicketOrder; plus 2 OCC concurrency rules on Booking.version
- **Endpoints (§1.5): 55** (including `POST /_clock/set_current_utc` with the fixed 2026-09-01T00:00:00Z startup default)
- **Errors (§1.6): 16**
- **Difficulty instances (§1.8): 18** — 2 per each of the 9 Difficulty Rules, with differentiation honored (e.g., dual-variant on report gross vs order gross; combinatorial modes (a) nested-max settlement split vs (b) pinned per-order rounding; cascades from eviction (depth 3) vs capital-project completion (depth 2); boundary precision on gross-vs-floor vs 8-ticket group-sale; overlap semantics half-open booking windows vs closed capital-project contact; invariants on weekly gross vs non-terminal license count)
- **Corner instances (§1.9): 25** across sections entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting_layers / consistency_model

Maximum-difficulty levers applied: segregation-of-duties role model (CompanyRep submits, HouseManager verifies), temporal windowing with two distinct interval semantics, dual-variant provisional/final gross with refund-driven divergence, OCC create-with-supersede on licenses, eviction cascade of depth 3 into DRAFT report recompute, and landmark-theatre maintenance-hold interlock.

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (557 calls scanned, 0 violations).

## Step 3: Copy Shared Files — 2026-09-30T11:00:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3211_theatrical_house_booking_weekly_grosses_royalty_pool/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T11:05:00.000Z

**Summary**

- **Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3211_theatrical_house_booking_weekly_grosses_royalty_pool/workspace/PRD.md` — 295 lines, 27 headings (5 top-level sections: Introduction, Global Specifications with 10 subsections, Business Logic with 10 subsections, Endpoint Definitions, Error Code Catalogue).
- **Did not read** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`, per the hard constraint.

**Coverage assessment against the scaffold:**

- **Entities (13/13)**: ProductionCompany, Theatre, Production, Booking, LicenseAgreement, RoyaltyParticipant, DiscountCode, TicketOrder, WeeklyGrossReport, Settlement, StopNotice, CapitalProject, CrewAssignment — all fields covered. Contract 1 field-name check: 58 required backticked names (entity fields + endpoint inputs + query params + common fields), 58 present, 0 missing.
- **State machines (7/7)**: Booking (REQUESTED→APPROVED/DECLINED/WITHDRAWN/ACTIVE/CLOSED/EVICTED/MAINTENANCE_HOLD/DONE with all cascade depths), LicenseAgreement (DRAFT/SIGNED/SUPERSEDED/VOIDED), WeeklyGrossReport (DRAFT/SUBMITTED/VERIFIED/REJECTED cycle), Settlement, StopNotice, CapitalProject (including CANCELLED), TicketOrder — all states, preconditions, and side effects expressed in prose.
- **Calculations (5/5)**: per-order gross with pinned round-half-up-per-order rule; weekly gross sum with provisional/final variants; union crew minimums (4/8/14) and 120000-cent weekly rate; settlement waterfall with pinned 6-step order, 30% theatre share, 65% pool share, and pool remainder allocation by points DESC / created_at ASC; stop-clause counter with strict `<` accrual and inclusive `>=` eviction.
- **Validations (8/8 priorities)**: expressed as an explicit priority-ordered validation cascade in §2.5 plus endpoint-specific error pairings in §3.
- **Endpoints (55/55)**: all in the §4 table with method, path, description, roles; OCC rules for license create/sign (`expected_booking_version`, `ERR_STALE_VERSION`/412) specified in §2.8 and §3.3.
- **Errors (17/17)**: all in §5 table; trigger conditions scattered through §2/§3 prose.
- **Roles (3/3)**: HouseManager, CompanyRep (entity-backed by ProductionCompany), BoxOfficeAgent (opaque) — identity semantics spelled out in §2.1.
- **Contract 3 (§3 path purity)**: 0 violations — no HTTP methods or URL paths in §3 backticks; endpoints referenced via state-pair and role+verb framing.
- **§2.2** emitted verbatim from the fixed response-structure block; logical clock default (2026-09-01T00:00:00Z, never wall-clock) covered in §2.9.

## Step 5: Generate Unit Tests — 2026-09-30T11:21:00.000Z

## Files written

**test_helpers/ (9 files):** `__init__.py` (barrel export), `types.py` (14 entity TypedDicts + 8 status/role enums), `api_client.py` (ApiClient subclassing GenericApiClient, ~45 endpoint methods incl. `/_clock/set_current_utc`), `api_errors.py` (17 error IDs + HTTP map, registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions + settlement invariants), `factories.py` (13 payload factories), `constants.py` (union minimums 4/8/14, crew rate 120000, 0.30/0.65 waterfall pcts, standard week calendar), `test_users.py` (shared opaque-role headers + mandatory `make_company_rep_headers(company_id)` builder for the entity_backed CompanyRep), `fixtures.py` (composite helpers: `setup_approved_booking`, `setup_active_booking`, `create_and_sign_license`, `verified_report_for_week1`, participant builders — all threading `X-User-ID = ProductionCompany.id`).

**test_suite/ (12 files):** `conftest.py` + 11 test files, 61 tests collected cleanly.

## Queue coverage

- **Queue A (Difficulty):** 17 of 18 instances covered with ≥2 tests each (36 tests).
- **Queue B (Corner):** all 25 non-stub instances covered with ≥1 test each (25 tests).

## Skipped instances (1)

- `Difficulty/resource_temporal_overlap/capital_project_window_closed_contact_conflict` — the instance triggers the conflict on capital-project *create*, but the PRD states the booking-vs-capital-window conflict rule only for booking request/approval (§3.2: "must not overlap ... any `SCHEDULED` capital-project window touching the performance run" is phrased as a check on the requested occupancy window; §2.10 additionally declares capital windows themselves half-open, undercutting the closed-contact semantics). No verbatim PRD sentence uniquely derives rejection of a capital-project creation — gap left as a gap.

## Adjudications applied

- `Corner/state_machines/withdraw_cascades_void_license_and_discharge_notice`: recipe's setup requires withdrawing an ACTIVE booking, which PRD forbids (withdraw is REQUESTED/APPROVED-only). Translated the reachable core — APPROVED booking + SIGNED license → withdraw → WITHDRAWN + VOIDED; the stop-notice depth-2 leg is unreachable and dropped.
- `Corner/calculations/royalty_pool_remainder_allocation_order`: per-participant payout assertion dropped (no PRD endpoint exposes payouts); settlement-level amounts (theatre_share 450000, profit 90000, pool 58500) asserted instead.

## Coverage checks

- Docstring-tag audit: every one of the 61 test functions carries exactly one `Design: Difficulty/...` or `Design: Corner/...` line; all tags resolve to real instances; the only uncovered instance is the intentional skip above.
- PRD-citation verbatim pass: 51/51 distinctive ≥8-word citation probes survive a literal whitespace-normalized match against `workspace/PRD.md`.
- `pytest --collect-only` succeeds: 61 tests, no import errors.

## Step 6: Generate Implementation — 2026-09-30T11:48:00.000Z

## Files written (all in `tasks/task_3211_theatrical_house_booking_weekly_grosses_royalty_pool/workspace/implementation/`)

- `start.sh` — foreground launcher, guarded `pip install` (no-op once Flask is importable), `exec python3 app.py`, reads `PORT` (default 10000), binds 0.0.0.0
- `requirements.txt` — flask
- `app.py` — Flask app, ApiError/404/405/generic handlers, `POST /_clock/set_current_utc`, blueprint registration
- `db.py` — in-memory store, logical clock starting at exactly 2026-09-01T00:00:00Z
- `errors.py` — all 17 scaffold error IDs with their HTTP statuses
- `response.py` — envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`; pagination fields `limit/offset/total_count/has_more`), pagination defaults (10 / min 1 / max 100), created_at-sorted lists, ISO8601 UTC 3-fractional-digit timestamps, UUIDs
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, three roles, CompanyRep ownership via ProductionCompany id
- `services.py` — calculations (per-order gross round-half-up via Decimal, weekly gross sum half-open week, crew cost with union minimums 4/8/14 @120000¢, settlement waterfall with 30% theatre share and 65% pool, floor-based pool payout remainder ranked points-DESC/created_at-ASC), cascades (competitor decline, license void/supersede, refund recompute, stop-clause counter incl. new-notice increment, eviction with future-dated refund), clock-driven transitions (APPROVED→ACTIVE with crew gate, CLOSED/EVICTED→MAINTENANCE_HOLD/DONE, project completion releasing held bookings)
- `routes_core.py`, `routes_bookings.py`, `routes_licenses.py`, `routes_royalty.py`, `routes_orders.py`, `routes_reports.py`, `routes_settlements.py`, `routes_crew_capital.py`

## Endpoint count

57 endpoints (all 57 from the PRD §4 table), plus the Flask `/static` default route — 45 registered URL rules total.

## Smoke boot

Succeeded. `bash start.sh` on port 18765 booted in <2s; manually exercised: company/theatre/production creation, size-class mismatch (422), RBAC 403, booking approve with OCC version increments, license create with `ERR_STALE_VERSION` and default rent from theatre, sign (SIGNED), union-min-crew 422, clock-driven activation, order sale with per-order rounding (150000¢ for 10×10000×1.5), group-sale mismatch, report create/submit/reject/revise/verify cycle, duplicate-week 409, stop-clause counter accrual and discharge, settlement waterfall (crew 1920000 / share max(rent, 30% gross) / profit / pool), second-settlement `ERR_ALREADY_TERMINAL`, fiscal-guard 422, eviction cascade (notice EXECUTED, future orders refunded), landmark MAINTENANCE_HOLD → project complete → DONE, and `ERR_CAPITAL_PROJECT_IN_USE`. Killed exactly the PID started. Fresh boot starts with an empty store and clock 2026-09-01T00:00:00Z.

## Step 7: Run Tests and Iterate — 2026-09-30T12:03:00.000Z

All 8 rounds pass 61/61. Done.

## Summary

- **Iterations run:** 2 (first sweep: 56/61 with 5 deterministic failures in all 8 rounds; second sweep after fixes: 8/8 rounds at 61/61).
- **Tests deleted:** none — every failing rule was verbatim-covered by PRD; all fixes were test-side faithfulness corrections.
- **Fixes to `test_helpers/`:** none needed (factories and role headers were already PRD-consistent).
- **Fixes to `test_suite/`** (file: `/home/ubuntu/github/CodingPRD/tasks/task_3211_theatrical_house_booking_weekly_grosses_royalty_pool/test_suite/`):
  - `test_03_calculations.py` `test_discount_stacking_per_order_rounding` — drifted arithmetic constant: pinned whole-order formula `round_half_up(7×999×1.5×0.89) = round_half_up(9335.655) = 9336`, but the test asserted 9331 (a per-ticket-intermediate artifact). Corrected to 9336; the per-ticket reading 9338 remains the forbidden contrast.
  - `test_03_calculations.py` `test_discount_stacking_divergence_is_exactly_seven_cents` — same drifted constant (asserted 9331); corrected to 9336 and renamed to `test_discount_stacking_diverges_from_per_ticket_reading` since the divergence is 2 cents, not 7. The PRD-verbatim rule ("apply both factors to the raw whole-order value first, then round once; never round per ticket and multiply") is still asserted exactly.
  - `test_03_calculations.py` `_setup_medium_split_scenario` (setup for `test_settlement_split_max_rent_vs_pct_theatre_share` and `test_settlement_split_negative_profit_gates_pool`) — fixture requested 60+40+1=101 royalty points, violating PRD's verbatim "inclusive range from 1 to 100" total-points cap (§2.11/§3.7), so the implementation correctly rejected setup with `ERR_ROYALTY_POINTS_OUT_OF_BOUNDS`. Rebalanced to 40+35+25=100; all asserted waterfall values (theatre_share 600000, crew 1200000, profit −150000, pool 0) are unchanged.
  - `test_07_validations.py` `test_challenger_inside_incumbent_buffer_rejected` — two issues: (1) the challenger window `run_end=2026-11-01` with default 24h loadout overlapped the incumbent's 48h buffer, so creation itself was rejected (setup error before the assertion); (2) the PRD pins the same overlap check at creation (§2.4: "Two business checks guard creation... `ERR_BOOKING_WINDOW_CONFLICT`"), so the faithful check point is the create call. Rewrote the test to assert `ERR_BOOKING_WINDOW_CONFLICT` on `POST /theatres/bookings` directly (same error_id, no downgrade), with a non-self-overlapping challenger window (run_end 10-26, 1h buffers). `_setup_incumbent` gives the challenger 1h loadin/loadout so the boundary-touching sibling test isolates exactly the incumbent's 48h buffer semantics.
- **Fixes to `implementation/`:** none — the implementation was correct on every failure (gross formula, points cap, creation-time and approve-time overlap checks all behave per PRD verbatim).

Final state: 8/8 parallel rounds, 61/61 tests passing each round.

## Step 8: Finalize PRD — 2026-09-30T12:11:00.000Z

**Zero edits made.** `workspace/PRD_FINALIZED.md` is an exact byte-identical copy of `PRD.md` (295 lines each, 0% delta, `diff` confirms identical).

### Why each step_7_diff item required no PRD change

All four items were test-side faithfulness corrections against rules the PRD already pins verbatim, and the implementation matches the PRD at every site:

- **Discount stacking rounding constant (9331→9336)** — Pure test-constant drift. PRD §2.7 and §3.5 already pin the exact rule verbatim: "apply both factors to the raw whole-order value first, then round once; never round per ticket and multiply." Implementation `implementation/services.py:178-181` (`compute_order_gross`: `Decimal(ticket_count) * Decimal(face_value_cents) * dec(factor) * (1 - dec(percent_off)/100)` then `rhu_cents` once) matches exactly. No PRD silence.

- **Same constant, renamed test** — Same verdict; renaming the test and correcting 9331→9336 changed nothing about the spec surface.

- **`_setup_medium_split_scenario` rebalanced 101→100 royalty points** — Fixture bug. PRD §3.4 and §3.9 pin "the per-production total of `royalty_points` ... must lie within the inclusive range from 1 to 100" with `ERR_ROYALTY_POINTS_OUT_OF_BOUNDS`; §3.8 pins the same gate at settlement finalization. Implementation enforces it at participant creation (`implementation/routes_royalty.py:36-37`) and finalize (`implementation/routes_settlements.py:85-86`). PRD already determines the behavior.

- **`test_challenger_inside_incumbent_buffer_rejected` rewritten to assert at create** — PRD §3.2 explicitly pins the overlap check at creation ("Two business checks guard creation... `ERR_BOOKING_WINDOW_CONFLICT`"), §2.5 ranks it fifth in the fixed validation order, and §2.10 defines the buffer-inclusive half-open occupancy window. Implementation checks at create (`implementation/routes_bookings.py:55-56` via `services.py:71-72, 86-97`) and re-checks at approve (`routes_bookings.py:91`), exactly per PRD. The rewritten test asserts the PRD-verbatim check point.

Additionally spot-checked off-site paths per the no-new-mismatch perspective: settlement waterfall constants (`services.py:11-12, 378-380`: 30% vs max rent, 65% pool on positive profit, floor-then-remainder pool payout) all match PRD §3.8 verbatim. The only impl detail not uniquely pinned by PRD found anywhere was the third tie-break key `p["id"]` after `created_at` in `pool_payouts` (`services.py:403`) — but no step_7_diff item traces to it, so per HARD SCOPE no edit was made.

**Per-edit pre-edit search log:** empty — no edits were committed, so no (a)/(b)/(c) entries exist.

## Step 9: Complete PRD — 2026-09-30T12:18:00.000Z

Done. `PRD_COMPLETED.md` written at `workspace/PRD_COMPLETED.md` (295 lines, same as source; 43,005 chars vs 38,069 in `PRD_FINALIZED.md`, +4,936 chars). All changes are inline inserts/revisions within existing paragraphs; no sections were added or removed.

**Counts: 14 ambiguity-pins, 5 mismatch-revisions (19 changed paragraphs total; some paragraphs contain both kinds).**

Change log:

- §2.2 — revise — mismatch — removed "For 2xx responses with no data, `data` contains an empty object" and pinned the clock endpoint's actual return (`{"current_utc": ...}`) — implementation/app.py:47
- §2.3 — revise — mismatch — out-of-range `limit`/`offset` are clamped (1/100/0), not rejected; only non-integer values yield `ERR_INVALID_REQUEST`; added `id`-ascending tie-break on `created_at` sorting — implementation/response.py:89-122
- §2.4 — insert — ambiguity — `version` pinned to start at 1 — implementation/response.py:131-133
- §2.5 — insert — ambiguity — noted that `ERR_BUSINESS_CONSTRAINT_VIOLATION` never appears literally (only its specific variants); `ERR_INVALID_REQUEST` also covers wrong-JSON-type fields; earliest-field ordering for structural checks; body-referenced missing resources (`company_id`, `production_id`, `theatre_id`) yield `ERR_NOT_FOUND` — implementation/response.py:152-161, routes_bookings.py:40-46, routes_core.py:111
- §2.6 — insert — ambiguity — crew-assignment tie-break extended with `id` ascending — implementation/services.py:164
- §2.9 — insert — ambiguity — logical clock governs only business-time comparisons; `created_at`/`updated_at`/`engaged_at`/`api_request_timestamp` are wall-clock UTC — implementation/response.py:17-20, routes_crew_capital.py:28
- §2.10 — revise — mismatch — run-vs-capital-project conflict is a closed-interval test (`window_start <= run_end AND loadin_start <= window_end`); touching the run boundary already conflicts — implementation/services.py:76-82
- §3.2 (create) — insert — ambiguity — cross-referenced the closed-interval touching rule — implementation/services.py:76-82
- §3.2 (approve) — revise+insert — mismatch — landmark precondition pinned to the project's `window_start` (inclusive at `loadin_start`−365d, `run_end`, `run_end`+365d; strictly before `loadin_start`); failure rejected as `ERR_BOOKING_WINDOW_CONFLICT`; notification pinned to `decline_notice_sent` flag (false at creation) — implementation/services.py:114-132, routes_bookings.py:92-93, services.py:233, routes_bookings.py:57
- §3.2 (decline) — revise — mismatch — decline also runs the agreement-voiding cascade — implementation/routes_bookings.py:108
- §3.2 (terminal states) — insert — ambiguity — clarified `EVICTED`/`MAINTENANCE_HOLD` are source states for clock/completion transitions — implementation/services.py:356-366
- §3.3 — insert+revise — mismatch — threshold < 1 is `ERR_INVALID_REQUEST` (not fiscal guard); pinned "the license agreement" = latest live (`DRAFT`/`SIGNED`) by `created_at`/`id`; only finalization requires `SIGNED` — implementation/routes_licenses.py:50-51, services.py:135-149
- §3.4 — revise — mismatch — activation without qualifying crew is a silent gate (booking stays `APPROVED`), not an error; crew gate uses the latest assignment; multi-booking activation has no starvation — implementation/services.py:343-355, routes_crew_capital.py:25-26
- §3.4 (points) — insert — ambiguity — "when it matters" pinned to exactly participant registration and settlement finalization — implementation/routes_royalty.py:34-37, routes_settlements.py:84-86
- §3.5 — insert — ambiguity — duplicate `code` on a production → `ERR_INVALID_REQUEST`; deactivation is idempotent — implementation/routes_royalty.py:69-71, 95-97
- §3.5 (refund cascade) — insert — ambiguity — a new sale also recomputes covering `DRAFT`/`SUBMITTED` reports — implementation/routes_orders.py:66-68
- §3.6 — insert — ambiguity — non-Monday-00:00:00 `week_start` → `ERR_INVALID_REQUEST` — implementation/routes_reports.py:40-42
- §3.7 — insert+revise — ambiguity — stop clause applies only with a live agreement; the week creating a notice counts (counter starts at 1 on a fresh notice); execute requires `ACTIVE` booking (`ERR_INVALID_STATE`) plus notice+agreement+threshold (`ERR_STOP_CLAUSE_NOT_MET`) — implementation/services.py:272-296, routes_bookings.py:145-151
- §3.8 — insert — ambiguity — settlement creation requires a live agreement (`ERR_INVALID_STATE` otherwise); "total pool points" = sum over pool-eligible participants only; finalization precondition failures pinned (`ERR_INVALID_STATE` for report/agreement, `ERR_ROYALTY_POINTS_OUT_OF_BOUNDS` for points) and re-finalize → `ERR_ALREADY_TERMINAL` — implementation/routes_settlements.py:38-40, services.py:389-393, routes_settlements.py:73-86
- §3.9 — revise — mismatch — replaced "While the booking is `ACTIVE`" invariant with the pinned enforcement points of §3.4 — implementation/routes_royalty.py:34-37
- §3.10 — insert — ambiguity — acting on any non-`SCHEDULED` project (complete or cancel) → `ERR_ALREADY_TERMINAL` — implementation/routes_crew_capital.py:86-87, 98-99
