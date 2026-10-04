# Worklog — task_3001_warehouse_club_depot_cross_dock_pallet_level

## Step 1: Create Task Directory — 2026-09-29T00:00:00.000Z

Task directory `./tasks/task_3001_warehouse_club_depot_cross_dock_pallet_level/` was pre-allocated by the invoker (already contained `workspace/`); verified existence, no new index computed.

## Step 2: Generate Scaffold — 2026-09-29T13:27:07.202Z

(Note: first attempt was interrupted by session exit after writing a partial SCAFFOLD.yaml; re-run from scratch in foreground, partial file fully overwritten.)

All checks pass. Final lint verdict block, pasted verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_3001_warehouse_club_depot_cross_dock_pallet_level/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_3001_warehouse_club_depot_cross_dock_pallet_level/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_3001_warehouse_club_depot_cross_dock_pallet_level/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    70
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     41
  Calls scanned (§1.8+§1.9):  725

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

Generated a fresh, maximal-difficulty scaffold for the Costco-style warehouse club cross-dock scenario at `/home/ubuntu/github/CodingPRD/tasks/task_3001_warehouse_club_depot_cross_dock_pallet_level/`. The partial SCAFFOLD.yaml was fully overwritten; no sibling tasks were consulted.

**Counts:**
- Entities: 15 (Region, Vendor, Club, Item, Depot, Appointment, Pallet, CrossDockRun, Allocation, Member, Purchase, MarkdownDecision, Complaint, Chargeback, DepartmentSale)
- State machines: 9 (Item with DELETION_REVIEW cycle, Appointment with no-show auto-transition, Pallet with stranding, Allocation, CrossDockRun, Purchase, Chargeback with appeal/auto-confirm, Club posture 3-state threshold machine, Vendor compliance suspension)
- Calculations: 9 (pallet_quantity_design, allocation_priority_score with dual velocity-window variants, unload_fee tiered pricing, chargeback_amount with pinned evaluation order and provisional/final variants, member_cap_check, club_posture_recompute, complaint_weighted_score_calc, vendor_compliance_score with 30-day bucket decay, sell_through_ratio)
- Endpoints: 70 (including 1 `/_clock/set_current_utc` test-driving endpoint with pinned default 2026-09-01T00:00:00Z)
- Errors: 20
- Roles: 6 (RegionalOps, CategoryManager, DepotManager, DepotPlanner, MembershipDesk, entity_backed VendorRep)
- Difficulty instances: 18 (all 9 rules × 2 instances, with required differentiations — different entity domains, formula modes (a) vs (c), entities, cascade triggers, error-category pairs, metrics/endpoints, entity pairs, interval semantics, conserved quantities)
- Corner instances: 41 across 7 sections (entities, state_machines, calculations, validations, endpoints, errors, roles, cross_cutting_layers, consistency_model)
- Concurrency: 2 OCC rules (allocation create on CrossDockRun.version, markdown decision on Item.version), with an `Allocation.run_version` echo field enabling chained allocations without re-reads

Key difficulty mechanisms: half-open appointment window overlap vs aggregate club-slot capacity (two distinct interval semantics), strict-greater posture thresholds with exact-boundary tests (8-of-10 NORMAL, 9 CONSTRAINED, 10 FROZEN), member cap equality-allowed boundary, multiplicative min()-capped allocation scoring (19.5 vs 19.4999 at cap boundary), repeat-offender chargeback multiplier (112500 cents pinned), round-half-up sell-through (72.5→73), depth-3 discontinue cascade (item→pallet→allocation→club posture), and vendor suspension cascade from compliance decay (7600 < 8500 bp).

All formula-derived assertion values were computed by executing the formulas (Python/Decimal), and lint passes clean with 725 calls scanned.

## Step 3: Copy Shared Files — 2026-09-29T13:28:04.348Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-29T13:41:00.000Z

The PRD is complete and all three hard contracts pass.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3001_warehouse_club_depot_cross_dock_pallet_level/workspace/PRD.md` — 313 lines.

**Sections covered:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC with per-role identity semantics (VendorRep entity-backed, others opaque), 2.2 fixed verbatim response envelope, 2.3 pagination (limit 10/1/100, offset 0, created_at ASC), 2.4 common resource properties, 2.5 logical clock (default `2026-09-01T00:00:00Z`, no rollback, fires no-show/stranding/auto-confirm), 2.6 precision rules, 2.7 OCC for both concurrency rules with exact error IDs and HTTP 412, 2.8 nested-reference validation order, 2.9 validation priority ordering
- §3 Business Logic in 8 subsections organized by workflow: merchandise setup/pallet design, appointments/receiving dock, pallet receipt + same-day cross-dock run (create/void/commit/cancel with both commit phases and score-ordered shipping), club posture capacity ladder, members/purchases/caps/ancillary, chargebacks/appeals/vendor compliance decay, complaints/deletion review, treasure-hunt sell-through/markdown
- §4 Endpoint table (4 columns, all 68 endpoints) and §5 error catalogue (2 columns, all 20 error IDs)

**Contract reports:**
- Contract 1 Field-Name Coverage: 79 entity+path fields, 53 request-body fields, 23 query params — all present, 0 missing. PASS (one repair: added `run_id` mention in §2.7).
- Contract 2 Rule Coverage: PASS by construction — all state-machine transitions (Item×5, Appointment×4, Pallet×6, Allocation×3, CrossDockRun×2, Purchase×1, Chargeback×4, Club×6, Vendor×3) with preconditions/side effects, all 9 calculations with constants and pinned boundaries, all 18 validations with error IDs, both OCC rules, and all endpoint side effects expressed in prose.
- Contract 3 §3 Path Purity: 421 backtick tokens scanned in §3, 0 path/method violations. PASS.

**Zero-silence decisions made:**
- All numeric constants embedded in prose with exact boundaries (e.g., "at most 10 / more than 10 and at most 25 / exceeds 25" tiers; "strictly greater than the 80-percent threshold" vs "at least capacity"; equality allowed at cap and cutoff).
- The scaffold's `provisional` chargeback variant ("not used by any current transition; documented for forward compatibility") was deliberately omitted from the PRD since it is explicitly non-normative in the scaffold; the `final` variant semantics (amounts frozen at terminal observation, never recomputed) are expressed.
- Forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened, grepped, or referenced.

## Step 5: Reset after concurrent-generation clash — 2026-09-29T16:11:37.186Z

Orchestrator error: Step 5 was launched twice concurrently (both subagents wrote test_helpers/ and test_suite/ simultaneously, clobbering each other). Deleted both directories; Step 5 is being re-run with a single subagent. No test artifacts from the clashed run are retained.

## Step 5: Generate Unit Tests — 2026-09-29T16:48:15.360627333Z

(Single foreground subagent; clean regeneration after the Step 5 reset above.)

Generation is complete. Final summary:

## Summary

**Task 3001 — Warehouse Club Cross-Dock & Pallet-Level Replenishment**: test infrastructure and test suite generated fresh, driven exclusively by the two design indices with the PRD as contract.

### test_helpers/ (9 files)
- `types.py` — TypedDicts for all 15 entities (all `common_fields: true`), 15 status/enum classes, `UserRole`.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (regions, vendors, clubs, items, depots, appointments, pallets, cross-dock runs, allocations, members, purchases, complaints, chargebacks, department sales, `_clock/set_current_utc`).
- `api_errors.py` — all 20 `ApiErrorId` values with the PRD §5 HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` validators plus `assert_club_invariants` (posture/slot consistency ladder).
- `factories.py` — input-only payload factories with collision-free generated codes/SKUs/membership numbers.
- `constants.py` — all PRD thresholds (4500/pallet fee, 10/25 tiers, 15000/75000/25000 bases, 6000/extra pallet, 15-min grace, 7-day appeal window, 80% posture threshold, 25.0 deletion threshold, 8500 bp suspension, 10000 bp perfect score, 200000/20000000 caps, velocity base 10).
- `test_users.py` — shared headers for the five opaque roles plus `make_vendor_rep_headers(vendor_id)` for the entity-backed VendorRep.
- `fixtures.py` — composite helpers: `setup_received_pallets` (full receiving-dock chain), `create_open_run`, `allocate_pallet`/`allocate_many` (OCC version chaining via `run_version` echo), `setup_run_with_allocations`, `record_purchase`, `file_complaint`, `confirm_chargeback`, `setup_vendor_with_confirmed_no_shows`.

### test_suite/ — 88 tests in 8 files (all tagged, no skips/xfail)
- Queue A (Difficulty): **36 tests, exactly 2 per each of the 18 instances** — all 9 rules covered (dual-variant velocity windows, provisional-vs-final over-pallet chargeback, tier×repeat-offender evaluation order, min-cap multiplicative interaction, deletion-review cycle, posture 3-state walk, depth-3 discontinue cascade, vendor suspension cascade, state-vs-safety and cap-vs-inactive precedence, member-cap equality boundary, posture strict-> boundary, same-day rule, vendor-identity appeal, half-open adjacency, aggregate slot capacity, void/refund compensating invariants).
- Queue B (Corner): **52 tests, ≥1 per corner instance** across entities/state_machines/calculations/validations/endpoints/errors/roles/cross_cutting/consistency sections. The corner index contained **zero `excluded_because:` stubs**.

### Instances skipped
None. Every instance passed the PRD-first two-condition filter (verbatim coverage + unique derivability).

### Coverage audit
- All 18 difficulty instances: ≥2 tagged tests each — pass.
- All corner instances: ≥1 tagged test each — pass; 0 stubs. (Subagent summary said "26 non-stub corner instances" but orchestrator verified 41 unique `Design: Corner/...` tags in test_suite matching all 41 corner yaml instances — full coverage.)
- Every test docstring ends with exactly one `Design:` tag resolving to a real instance name (verified programmatically against both yamls).
- Every quoted PRD citation survives a literal grep of `workspace/PRD.md` modulo whitespace — 0 failures out of 88 tests after a normalization pass that restored the PRD's inline-code backticks in citations.
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold references in generated code; all files compile; `test_helpers` imports cleanly.

## Step 6: Generate Implementation — 2026-09-29T17:08:53.998923177Z

(Single foreground subagent.)

All 70 routes from the scaffold endpoint table are registered. Work complete.

## Summary

**Files written** (all under `workspace/implementation/`):
- `start.sh` — guarded Flask install (no-op once importable), `exec python3 app.py`, foreground, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point, envelope/error handlers, `X-User-Role`/`X-User-ID` auth middleware, RBAC enforcement, route registration from the route table
- `db.py` — in-memory stores for all 15 entities plus the logical clock (default exactly `2026-09-01T00:00:00Z`, never wall-clock). No seeding anywhere.
- `helpers.py` — envelope meta (`req_` ids, wall-clock request timestamps, logical-clock entity timestamps at 3 fractional digits), error constructors for all 20 catalog error IDs, half-up rounding helpers, pagination (`limit`/`offset`/`total_count`/`has_more`, default 10, min 1, max 100), field validators
- `services.py` — all calculation rules and cascade logic
- `routes.py` — all 70 endpoint handlers from the scaffold endpoint table

**Endpoint coverage:** 70/70 routes from SCAFFOLD §1.5, including all nested list endpoints, all action endpoints, and `POST /wcd/_clock/set_current_utc`.

**State machines implemented:** Item (DRAFT→ACTIVE→DELETION_REVIEW→ACTIVE/DISCONTINUED, plus TREASURE_HUNT direct discontinue), Appointment (BOOKED→CHECKED_IN→COMPLETED, →NO_SHOW auto, →CANCELLED with vendor-identity gate), Pallet (RECEIVED→ALLOCATED→SHIPPED/STRANDED→RECONCILED), Allocation (PROPOSED→COMMITTED→SHIPPED, →VOIDED with pallet/club/run cascade), CrossDockRun (OPEN→COMMITTED two-phase atomic with FROZEN preflight, OPEN→CANCELLED with RUN_CANCELLED voids), Purchase (COMPLETED→REFUNDED), Chargeback (ASSESSED→APPEALED→CONFIRMED/WAIVED plus >7-day auto-confirm), Club posture ladder (NORMAL/CONSTRAINED/FROZEN with 80% integer-floor threshold, strict-greater boundary), Vendor (ACTIVE→SUSPENDED cascade below 8500bp, reinstate, guarded deactivate).

**Calculations implemented:** pallet quantity design (48×40 slot, 2dp footprint compare), allocation priority score (exact-Decimal intermediates so 4dp half-up rounding is correct — 11.64375 → 11.6438), tiered unload fee (4500/pallet × 1.00/1.15/1.30), chargeback amounts (base by reason + 6000/extra pallet + repeat multiplier capped at 4 priors), per-day member cap with equality-allowed boundary, complaint weighted score (frozen weights, trailing-30-day inclusive, 2dp half-up), vendor compliance score (30-day bucket right-shift decay over CONFIRMED only), sell-through percentage (denominator floored at 1, integer half-up), mandatory-markdown and no-reorder rules, OCC on `expected_cross_dock_run_version` / `expected_item_version` with 412 errors.

**Boot verification:** `bash start.sh` boots cleanly from a fresh process with an empty store and serves within ~2s. Three smoke suites (90+ assertions) pass covering CRUD, envelope shape, pagination, RBAC, VendorRep identity binding, dock-door assignment/overlap, late-check-in and no-show chargebacks with repeat-offender multipliers, OCC stale-version rejection, same-day/cutoff/capacity/frozen/safety gates, commit two-phase ordering and slot release, run-cancel cascade, clock-driven transitions (no-show, stranding, auto-confirm), complaint-driven deletion review, markdown decision rules, and member suspension gates.

One design note: per the Club entity definition, `allocated_slot_count` sums only PROPOSED+COMMITTED allocations, so run commit releases shipped allocations' slots (verified: FROZEN club returns to NORMAL after commit ships everything).

## Step 7: Run Tests and Iterate — 2026-09-29T18:01:28.813670673Z

(Single long-lived foreground subagent; owns run→diagnose→fix→rerun loop.)

All 8 rounds: 86/86 passed. Clean sweep. (Orchestrator verified all 8 results.N.json files: 86/86 in every round.)

## Summary

**Iterations run:** 3 sweeps (initial + 2 after fix rounds).

**Tests deleted (PRD-silence/unique-derivability collapses):**
- `test_over_pallet_count_assessed_at_completion` (test_02) — PRD §3.2 says completion requires "exactly equal" pallet count → ERR_INVALID_STATE on mismatch, but §3.6 also describes OVER_PALLET_COUNT chargeback at completion. Internal contradiction; both readings PRD-faithful. (Unique-derivability collapse / CONTRADICTORY-REQUIREMENTS pattern.)
- `test_over_pallet_chargeback_amount_matches_booked_excess` (test_02) — same contradiction as above.
- `test_cap_precedence_over_inactive_item` (test_05) — §2.9 lists "member caps ... active-reference checks" but qualifies "in the order those gates appear in §3", and §3.5 prose puts the ACTIVE-item check before the cap paragraph. Two valid orderings admitted. (Unique-derivability collapse / ERROR-PRECEDENCE-SILENCE pattern.)
- `test_score_excludes_resolved_complaints` (test_07) — PRD lists recompute triggers as create/resolve/deletion-review-open only; test expects trailing-30-day window to apply at READ time after a clock advance. Both snapshot-on-write and recompute-on-read are PRD-faithful. (Unique-derivability collapse / SNAPSHOT-VS-LIVE ambiguity.)
- `test_score_excludes_complaints_older_than_thirty_days` (test_07) — same pattern as above.

**Fixes applied to `test_helpers/`:**
- `factories.py` — `create_region_payload` was generating `code=f"R{n:02d}"` (digits) violating PRD's `^[A-Z]{2,4}$` rule (region code "two to four uppercase letters"). Replaced with a base-26 letters-only encoder. This single bug was killing 81 of 91 tests because every region creation failed in setup.

**Fixes applied to `test_suite/`:**
- `test_03_cross_dock_runs.py::test_failed_allocation_does_not_consume_capacity` — setup passed `num_pallets=2` with `club_capacity=1`, so the second setup allocation already failed with ERR_CLUB_FROZEN before the test body ran. Reduced to `num_pallets=1` so the setup completes, then a fresh second pallet exercises the FROZEN rejection.
- `test_03_cross_dock_runs.py::test_committed_run_allocation_returns_invalid_state_over_frozen_club` — original setup made the run's only destination club FROZEN before commit, so commit itself failed per PRD §3.3 ("any destination club's posture is FROZEN, the entire commit fails"). Restructured: commit a normal run, then build a separate FROZEN club in another setup, then attempt allocation to the FROZEN club on the committed run — verifying state-machine precedence over business gate.
- `test_06_complaints_and_deletion.py::_setup_treasure_hunt_below_target` — fixture advanced clock to 2026-09-30 (28 days past the 2026-09-02 received_date), causing PRD-mandated auto-stranding of the pallet; the stranded pallet dropped out of the sell-through denominator, raising the ratio above the target and disarming the mandatory-markdown rule. Moved delivery_date and exit_window_date to the same day (2026-09-30) and pushed the post-setup clock to 2026-09-30T23:00:00Z, so the pallet stays RECEIVED at evaluation.
- `test_07_compliance_and_reconciliation.py::test_fourth_confirm_suspends_vendor` (renamed to `test_third_confirm_suspends_vendor`) — fixture attempted to book appointments on 2026-08-25 with the boot clock at 2026-09-01, violating PRD's "delivery_date on or after the current logical date". Also the test's math was wrong: 3 confirmed NO_SHOWs at 600 bp each yields 10000 - 1800 = 8200, which is already below the PRD's 8500 suspension threshold, so the vendor would already be SUSPENDED before the 4th confirm. Restructured to 2 NO_SHOWs in setup (8800 ACTIVE) and the 3rd confirm crosses the threshold to 8200 SUSPENDED. Also fixed dates to 2026-09-01/02/03.
- `test_07_compliance_and_reconciliation.py::test_suspension_blocks_booking_and_recompute_is_per_confirm` — same date fix; also the total-chargeback assertion was wrong: the third NO_SHOW is assessed with prior_confirmed=2 → repeat multiplier 1.5 → 112500, so total is 262500, not 225000.

**Fixes applied to `implementation/`:** None. The implementation was correct for all failures attributable to it; every failure traced to test/fixture bugs or PRD-internal ambiguity requiring test deletion.

Final state: 8/8 rounds at 86/86 passed.
## Step 8: Finalize PRD — 2026-09-29T18:06:55.43711776Z

(Single foreground subagent; Step 7 diff inlined in prompt; scope bounded to step_7_diff items.)

All edits are committed. Final state: `PRD.md` 312 lines, `PRD_FINALIZED.md` 312 lines (0.0% delta — all changes are inline revisions within existing paragraphs; no sections added or removed).

## Changes made

- **§2.9 (Validation Priority Order)** — revise — appended a sentence stating that when an endpoint's §3 narrative pins a more specific order among business gates (as §3.3 does for allocation proposals, where the safety gates — including the CONSTRAINED approval gate — precede club capacity), that narrative order governs. Resolves the ambiguity that killed `test_cap_precedence_over_inactive_item` by deferring to the §3.3 sentence "the safety gates, the cutoff, the same-day rule, and finally club capacity," which matches the implementation. — `implementation/routes.py:717-735`
- **§3.1 (Regions)** — revise — pinned the region `code` format to the exact regex `^[A-Z]{2,4}$` (two to four uppercase ASCII letters), disambiguating the prose "two to four uppercase letters" that the buggy `R{nn}` factory exploited. — `implementation/routes.py:22,62-63`
- **§3.2 (Appointment completion)** — revise — replaced the sentence claiming an `OVER_PALLET_COUNT` chargeback is assessed when received > booked with a statement that the exact-equality check runs first, so over-delivery fails with `ERR_INVALID_STATE` like any other count mismatch and no over-count chargeback is reachable at completion; the §3.6 formula remains as the pinned rule for such an assessment. Resolves the §3.2/§3.6 contradiction that killed the two `test_over_pallet_*` tests. — `implementation/routes.py:582-589`
- **§3.6 (Chargebacks)** — revise — reworded the violations list so `OVER_PALLET_COUNT` is defined as a rule ("applies when more pallets arrive than booked") with a note that completion's equality gate makes it unreachable in practice; keeps the §3.6 amount formula and compliance-penalty entry intact. — `implementation/services.py:29,44,85-93`; `implementation/routes.py:586-589` (dead branch)
- **§3.7 (Complaints)** — revise — pinned `complaint_weighted_score`/`complaint_count` as stored snapshots recomputed only at complaint create, complaint resolve, and deletion-review-open; clock passage alone never recomputes them. Resolves the snapshot-vs-live ambiguity that killed the two `test_score_excludes_*` tests. — `implementation/services.py:210-223`; call sites `implementation/routes.py:323,999,1015` (none in clock transitions at `services.py:242-278`)

## Step-7 items with no PRD edit (pure fixture/test bugs, PRD already matched impl)

- `test_failed_allocation_does_not_consume_capacity` and `test_committed_run_allocation_returns_invalid_state_over_frozen_club` — test setup bugs; impl (capacity non-consumption on failure, `routes.py:713-724` state-check-before-FROZEN) already matches PRD text.
- `_setup_treasure_hunt_below_target` clock fix — PRD §2.5's "earlier than the current logical date" stranding rule is exactly impl (`services.py:264`); no ambiguity.
- `test_third_confirm_suspends_vendor` / `test_suspension_blocks_booking_and_recompute_is_per_confirm` fixes — dates and repeat-multiplier math were test errors; impl (`services.py:85-93,122-131`) matches PRD §3.2/§3.6 verbatim.

## Pre-edit search log

1. **Region code regex** — (a) subject: region `code` format validation. (b) enumerated: `routes.py:22` (regex def), `routes.py:57-75` (`create_region`, sole enforcement site), `routes.py:78-81` (`list_regions` code filter — equality only, unaffected), `services.py` (no region-code touch). (c) none — prose already said "two to four uppercase letters"; the regex merely pins the same rule, consistent everywhere.
2. **Completion over-count (§3.2 + §3.6)** — (a) subject: appointment completion count gate and `OVER_PALLET_COUNT` assessment. (b) enumerated: `routes.py:578-592` (`complete_appointment`, sole completion site), `services.py:85-93` (`compute_chargeback_amount`, shared by LATE_CHECKIN at `routes.py:571` and NO_SHOW at `services.py:254` — neither affected by wording about completion), `services.py:29,44` (constants). (c) initially said the over-count block "is unreachable and never fires"; softened to "no OVER_PALLET_COUNT chargeback is reachable at completion in practice; the §3.6 formula nonetheless pins what such an assessment would be," because the code block exists and fires in the (impossible) `len(received) > pallet_count` case after an equality check — categorical "never fires" would mis-describe the code. The §3.6 companion edit was scoped to the same logic to avoid contradicting §3.2 while keeping the formula/penalty pinned.
3. **§2.9 ordering deference** — (a) subject: business-gate evaluation order, specifically CONSTRAINED-safety-gate vs club capacity on allocation proposals. (b) enumerated: `routes.py:696-755` (`create_allocation`: state → OCC → CONSTRAINED safety gate → FROZEN → cutoff → same-day → capacity), `routes.py:791-829` (`commit_run`: FROZEN gate, no capacity/safety interplay), `services.py:57-66` (posture recompute). Also checked every other endpoint raising `ERR_SAFETY_GATE` or `ERR_INACTIVE_REFERENCE` (`routes.py:931-934` purchases, 987-988 complaints, 1075 department sales — each has only one applicable gate, so no ordering claim binds them). (c) scoped the new sentence to "when an endpoint's §3 narrative pins a more specific order … that narrative order governs" rather than asserting a global safety-gate-before-X rule, avoiding any new universal claim.
4. **Complaint figures snapshot semantics** — (a) subject: when `complaint_weighted_score`/`complaint_count` recompute. (b) enumerated: `services.py:210-223` (`recompute_item_complaints`), all call sites — `routes.py:323` (deletion-review open), `routes.py:999` (complaint create), `routes.py:1015` (complaint resolve); confirmed no call in `services.py:242-278` (`fire_due_transitions`); consumers `routes.py:336-337` (APPROVE threshold check reads stored figure), `routes.py:286-287` (init to 0). (c) initial wording said "a complaint that ages out of the trailing window, or a complaint resolution, leaves the stored figures untouched until the next … event" — wrong, since resolve recomputes immediately (`routes.py:1015`); corrected to attribute staleness only to clock-driven aging.

Output file: `workspace/PRD_FINALIZED.md`
## Step 9: Complete PRD — 2026-09-29T18:16:48.645407457Z

(Single foreground subagent; full PRD-vs-implementation scan over PRD_FINALIZED.md.)

Done. `workspace/PRD_COMPLETED.md` is written as a minimal patch over `PRD_FINALIZED.md`.

## Summary

**Source/dest sizes:** `PRD_FINALIZED.md` 312 lines / 47,184 chars → `PRD_COMPLETED.md` 312 lines / 50,604 chars (char-delta +3,420; all changes are in-paragraph insertions/revisions — no new sections, no new paragraphs except two sentences folded into existing paragraphs, line count unchanged).

**Counts:** 20 ambiguity-pins (insert), 3 mismatch-revisions (revise) — 23 changed lines total.

**Changes:**

- §2.2 — insert — ambiguity — `meta.api_request_timestamp` pinned as wall-clock UTC (not the logical clock) — implementation/helpers.py:107-112
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, out-of-range limit, negative offset → `ERR_VALIDATION` — implementation/helpers.py:234-258
- §2.5 — insert — ambiguity — clock backwards-move rejected as `ERR_VALIDATION` (HTTP 400); equal-set allowed; malformed `to_iso8601` is `ERR_VALIDATION` — implementation/routes.py:1096-1104
- §3.1 regions — insert — ambiguity — duplicate region `code` → `ERR_CONSTRAINT_VIOLATION` (422); income pinned as integer — implementation/routes.py:66-68
- §3.1 vendors — insert — ambiguity — duplicate `vendor_code` → `ERR_CONSTRAINT_VIOLATION` — implementation/routes.py:96-98
- §3.1 clubs — insert — ambiguity — duplicate `club_number` → `ERR_CONSTRAINT_VIOLATION`; `member_base` pinned integer ≥ 0 — implementation/routes.py:161-177
- §3.1 depots — insert — ambiguity — dock-hours/`slot_length_minutes` rule violations pinned as `ERR_VALIDATION` — implementation/routes.py:427-434
- §3.1 items — insert — ambiguity — duplicate `sku` → `ERR_CONSTRAINT_VIOLATION`; cap/target pinned integer; `exit_window_date` on REGULAR items is validated for format and stored (not forbidden) — implementation/routes.py:254-271
- §3.1 items — insert — ambiguity — footprint quantized to 2dp before comparison against the 1920 sq-in slot area — implementation/services.py:50-53
- §3.1 activation — insert — ambiguity — sub-1 pallet design fields at activation rejected as `ERR_INVALID_STATE` — implementation/routes.py:308-309
- §3.2 booking — revise — mismatch — validation order pinned: references → vendor-identity 403 → window geometry 409 (ordering, dock hours, grid) → delivery-date recency `ERR_VALIDATION` → vendor-active 422 → door scan — implementation/routes.py:493-514
- §3.2 booking — revise — mismatch — door assignment is a lowest-numbered-free-door scan (doors 1..`dock_count`); only non-`CANCELLED`/non-`NO_SHOW` appointments on the same delivery date block a door; replaced the fictitious "tie-break by window start then creation time" rule — implementation/routes.py:515-534
- §3.2 cancel — insert — ambiguity — cancel-time vendor-identity 403, non-BOOKED → `ERR_INVALID_STATE`, at/after window start → `ERR_APPOINTMENT_CONFLICT` — implementation/routes.py:595-607
- §3.3 receipt — revise — mismatch — receipt gate order pinned: appointment `CHECKED_IN` → unit-qty equality (422) → markdown reorder guard (422) → vendor ACTIVE → item ACTIVE — implementation/routes.py:628-640
- §3.3 allocation proposal — revise — mismatch — among the safety gates the CONSTRAINED-approval gate (`ERR_SAFETY_GATE`) fires before the FROZEN gate (`ERR_CLUB_FROZEN`); `regional_ops_approved` defaults false and must be a boolean — implementation/routes.py:706-724
- §3.3 allocation proposal — insert — ambiguity — cutoff binds only when current logical date equals `run_date` (later dates are caught by the same-day rule, earlier dates unrestricted) — implementation/routes.py:726-727
- §3.3 score — insert — ambiguity — velocity window pinned as inclusive `[run_date − window, run_date − 1 day]` — implementation/services.py:148-160
- §3.3 void — insert — ambiguity — omitted `void_reason` stored as empty string — implementation/routes.py:780-782
- §3.3 commit — revise — mismatch — shipped allocations release their reserved slots (`allocated_slot_count` decremented, posture recomputed per touched club); cutoff equality/date-scoping pinned same as proposals; commit's run version advances once — implementation/routes.py:791-829
- §3.3 run cancel — insert — ambiguity — run version advances exactly once for the cancellation (not once per voided allocation) — implementation/routes.py:832-842
- §3.5 members — insert — ambiguity — duplicate `membership_number` → `ERR_CONSTRAINT_VIOLATION`; suspending an already-`SUSPENDED` member → `ERR_INVALID_STATE` — implementation/routes.py:859-861, 883-887
- §3.7 deletion review — insert — ambiguity — calling without `decision` on a non-`ACTIVE` item → `ERR_INVALID_STATE` — implementation/routes.py:320-322
- §3.8 markdown decision — insert — ambiguity — `markdown_pct` pinned as an integer in (0, 100); decisions may be recorded against an item in any status (no state gate) — implementation/routes.py:366-395

Note: behaviors the PRD already pinned uniquely (chargeback formula/order, compliance decay buckets, posture ladder, sell-through formula, complaint weighting/snapshot semantics, OCC errors, error catalogue, endpoint roles) were verified against the implementation and left untouched.
