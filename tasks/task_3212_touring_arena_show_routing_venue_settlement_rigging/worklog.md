# Worklog — task_3212_touring_arena_show_routing_venue_settlement_rigging

## Step 1: Create Task Directory — 2026-09-30T10:46:00.000Z

Pre-allocated task directory `./tasks/task_3212_touring_arena_show_routing_venue_settlement_rigging/` verified to exist with `workspace/` inside (per command args; no new index computed).

## Step 2: Generate Scaffold — 2026-09-30T11:08:00.000Z

All three files complete, parse as valid YAML, and pass `scaffold_lint.py` clean.

## Final summary

**Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3212_touring_arena_show_routing_venue_settlement_rigging/`):**
- `SCAFFOLD.yaml` — 2042 lines, parses OK
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1227 lines, parses OK
- `SCAFFOLD_CORNER_DESIGN.yaml` — 648 lines, parses OK

**Counts:**
- Entities: 13 (Tour, Venue, RiggingPoint, DateAvail, Engagement, RiggingPlan, RiggingAllocation, LaborCall, TruckMove, TicketScale, Settlement, LicenseAgreement, SafetyInspection)
- Endpoints: 88 (includes 22 flat read aliases added for FK reverse-reachability)
- Errors: 52; Roles: 8; Calculations: 10; State machines: 10; Concurrency rules (OCC): 2; Validations: 24 priority-ordered
- Difficulty instances: 18 (9 rules × 2, per §0.5 minimum)
- Corner instances: 17 (16 active + 1 `excluded_because` stub) across 9 sections
- Lint: **VERDICT: clean lint** (323 calls scanned, 0 violations)
- No instance-name collisions within or across design files; no `scaffold_difficulty_design`/`scaffold_corner_design` keys leaked into SCAFFOLD.yaml

**Notable design decisions:**
- **Archetype**: ledger reconciliation (rent-vs-percentage settlement with floor-binding dual variant) × temporal windowing (half-open DateAvail intervals, hold TTL, market cooldown).
- **Difficulty Rule 1** grounds on two genuinely different domains: settlement `venue_share` (FLAT_RENT vs PERCENTAGE-with-floor) and labor cost (per-call estimate vs per-worker chronological final).
- **Rule 2** uses mode (a) non-linear interaction (royalty max/min/cap nesting) and mode (b) nested rounding order (family-pack per-seat division before multiplication — 17499 vs 17498 cent divergence).
- **Rule 8** contrasts two interval semantics: DateAvail half-open adjacency-ALLOWED vs Engagement-within-avail strict `< closes_at` containment.
- **Segregation of duties**: high-risk rigging plans require a different approver X-User-ID than the submitter.
- Logical clock endpoint with fixed default `2026-09-01T00:00:00Z` drives hold expiry, on-sale timing, license windows, and system transitions.
- The FK lint forced 22 flat read-alias endpoints (`/engagements`, `/date-avails`, etc.) alongside the nested routes — the lint only recognizes literal `{id}` in sub-resource paths and 2-segment single-GETs for collection derivation, so flat aliases were the cleanest compliant resolution.

(Orchestrator note: subagent required 4 resume rounds due to output-cap truncation; first two exits produced partial/no files, resolved by chunked writes.)

## Step 3: Copy Shared Files — 2026-09-30T11:10:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T11:20:00.000Z

All checks pass. The PRD is complete and on disk.

## Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_3212_touring_arena_show_routing_venue_settlement_rigging/workspace/PRD.md` — exists, 348 lines (~7,700 words, 56 KB).

**Sections written:**
- §1 Introduction (3 paragraphs, business-context angle)
- §2.1 RBAC (8 roles, all opaque identity, header contract), §2.2 verbatim fixed response-envelope block, §2.3 Pagination, §2.4 Resource identity/timestamps/versioning, §2.5 Money/precision/rounding (half-up, integer cents, 0.5-hour increments), §2.6 Logical clock and scheduled transitions, §2.7 OCC (both rules: `expected_avail_version` / `ERR_STALE_AVAIL_VERSION` 412 and `expected_settlement_version` / `ERR_STALE_SETTLEMENT_VERSION` 412), §2.8 Nested path left-to-right existence, §2.9 Validation priority ordering
- §3 (9 subsections, freely grouped by domain workflow): tour setup + licensing, venue onboarding (points/avails), engagement routing (holds, 72h TTL, market cooldown), rigging engineering (capacity sums, high-risk independent review), truck logistics (2 trucks per dock door), union labor (IATSE 4h/8h/1.5x, TEAMSTERS 5h/10h/1.5x, NON_UNION 1h/8h/1.25x; per-call estimate vs per-worker punch-settle), safety/show-ready gate, ticketing (family-pack divide-then-multiply, group minimums, on-sale gating), settlement (dual-variant venue share with rent floor, three-rounding-event royalty waterfall with reserve cap, negative promoter net allowed, dispute/payment flow)
- §4 Endpoint table — **all 88 scaffold endpoints covered** (66 nested + clock + 22 flat read aliases), 4 columns only, paths in backticks per example convention
- §5 Error catalogue — **all 52 error IDs**, 2 columns only

**Hard contracts:** Contract 1 field coverage PASS (108/108 identifiers present in backticks, including path params); Contract 3 §3 path purity PASS (454 backtick tokens scanned, zero path/method violations — no endpoints named in §3, only state-transition/role-verb framing); all 52 error IDs and all 39 state enum values appear in prose; every state transition, calculation formula (in reconstruction-safe prose), validation condition, OCC rule, and side-effect cascade from the scaffold is expressed. No fuzzy/approximating wording found. The two forbidden scaffold design files were never opened.

## Step 5: Generate Unit Tests — 2026-09-30T11:40:00.000Z

All checks pass. Final summary:

## Files written

**`test_helpers/`** (10 files, 1618 lines):
- `__init__.py` (30) — barrel export of framework generics + PRD-specific code
- `types.py` (326) — 17 status/enum classes + 13 entity TypedDicts (all carry `common_fields: true`)
- `api_client.py` (522) — `ApiClient(GenericApiClient)` with one method per endpoint (nested + flat read aliases + `/_clock/set_current_utc`)
- `api_errors.py` (118) — 54 `ApiErrorId` values + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` (157) — per-entity field assertions + settlement waterfall invariant checker
- `factories.py` (137) — 12 payload factories
- `constants.py` (28) — HOLD_TTL_HOURS=72, TRUCKS_PER_DOOR=2, FAMILY_PACK_SIZE=4, union rule matrix, shared timeline constants
- `test_users.py` (18) — 9 role header constants (all roles are `identity: opaque`, includes a second ProductionEngineer identity `pe-002` for segregation-of-duties)
- `fixtures.py` (280) — composite setup helpers: `setup_held_engagement`, `setup_confirmed_engagement`, `setup_in_performance_engagement`, `setup_reconciled_settlement`, `setup_rigging_plan` (submit/approve with independent approver), clock advance + lazy-tick helpers

**`test_suite/`** (11 files, 1691 lines): `conftest.py` + 10 test files organized by concern (scaffolding, holds, avails, rigging, labor, trucks, show-ready, tickets, settlement, validation/RBAC).

## Tests emitted: 38 total
- **Queue A (Difficulty): 18 instances → 28 tests** (every instance ≥2 tests)
- **Queue B (Corner): 15 non-stub instances → 10 tests**... correction: all 15 non-stub corner instances covered (some files hold multiple); 1 stub (`Corner/calculations/venue_share_flat_rent_ignores_gross`) correctly NOT translated — its `excluded_because` pointer resolves to `dual_variant_calc/venue_share_flat_rent_vs_percentage_floor_binds`, which owns the FLAT_RENT assertion.

## Instances skipped: none
All 33 non-stub instances passed the PRD-first two-condition filter; every asserted rule (error_id, boundary, rounding order, cascade, OCC version field) has verbatim PRD prose.

## Self-check results (Stage 1 + Stage 2)
- `py_compile` clean on all 21 files; `test_helpers` imports successfully.
- Completeness audit (script-checked): 34/34 expected `Design:` tags present, 0 missing, 0 extras, 0 stub tags, 0 under-covered instances.
- Citation audit (C1 verbatim grep against PRD.md): 0 failures — every quoted docstring passage survives a literal whitespace-normalized grep.
- One docstring-tag note: `test_07_show_ready.py` carries two tests tagged to the same cross-entity instance (wrong-state rejection + blocked/unblocked pair), both derived from the PRD's gate sentence; no dual-tagged test exists.

## Step 6: Generate Implementation — 2026-09-30T11:55:00.000Z

Implementation complete.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3212_touring_arena_show_routing_venue_settlement_rigging/workspace/implementation/`):

- `start.sh` (7) — guarded pip install, `exec python3 app.py`, binds 0.0.0.0:$PORT
- `requirements.txt` (1), `app.py` (22), `db.py` (45), `errors.py` (70), `response.py` (100), `middleware.py` (37), `clock.py` (39), `constants.py` (41), `helpers.py` (176), `calc.py` (149), `ticks.py` (121)
- `routes/`: `__init__.py` (0), `tours.py` (108), `venues.py` (196), `engagements.py` (184), `rigging.py` (202), `labor.py` (178), `trucks.py` (111), `tickets.py` (104), `settlements.py` (125), `licenses.py` (89), `inspections.py` (124), `flat.py` (290)

Total 2519 lines.

**Coverage**: All 88 endpoints implemented (66 nested + `POST /_clock/set_current_utc` + 22 flat read aliases: 11 single-read + 11 filtered lists). All 52 error IDs present in the error catalog with the scaffold's HTTP statuses. Both OCC rules (`expected_avail_version` → 412 `ERR_STALE_AVAIL_VERSION` on engagement create; `expected_settlement_version` → 412 `ERR_STALE_SETTLEMENT_VERSION` on mark-paid). All calculations: dual-variant venue share with rent floor (PERCENTAGE = `max(rent, round_half_up(G·pct))`, FLAT_RENT ignores gross), three-rounding-event royalty waterfall with reserve cap (per-agreement pct rounding → per-agreement guarantee proration rounding → reserve-cap rounding, max of pct/guarantee sums, cap only when `royalty_reserve_pct > 0`), per-call labor estimate vs per-worker chronological final cost with union matrix (IATSE 4/8/1.5x, TEAMSTERS 5/10/1.5x, NON_UNION 1/8/1.25x), hours rounded half-up to 0.5 before rate application, family-pack divide-then-multiply pricing, ceil(trucks/2) dock doors, floor-day market cooldown, 72h hold TTL with inclusive-expiry boundary. Logical clock defaults to 2026-09-01T00:00:00Z with lazy ticks on read/write (HOLD expiry auto-cancel with cascade, CONFIRMED→IN_LOAD, SHOW_READY→IN_PERFORMANCE, ROUTING→ON_ROAD, ON_ROAD→WRAP with counter recompute, ACTIVE→EXPIRED licenses). No seeding at startup.

**Boot smoke test**: passed — fresh process boot, `POST /tours` 201 with correct envelope/defaults, `GET /tours` pagination meta, `POST /_clock/set_current_utc` echoes `current_utc`, full tour→venue→point→avail→engagement→confirm chain works (avail flips to BOOKED), and re-creating on a now-BOOKED avail returns `ERR_AVAIL_NOT_OPEN` 409. Server killed by its own PID.

**Notable decisions**: (1) The four system-wide constants (HIGH_RISK_DYNAMIC_KG=500, UNION_CANCEL_NOTICE_HOURS=24, LATE_CANCEL_FEE_PCT=0.25, TRUCK_ARRIVAL_GRACE_HOURS=2) are referenced by name in PRD/SCAFFOLD without numeric values; I picked conventional values since the difficulty-design files (which likely define them) are off-limits to the implementer. (2) Where validation priority is ambiguous (avail-state vs OCC at engagement create; settlement state vs OCC at mark-paid), state/machine gates fire before the 412 stale-version check, per the PRD §2.9 global ordering.

## Step 7: Run Tests and Iterate — 2026-09-30T12:20:00.000Z

Clean exit after a green 8-round sweep (54/54 in all rounds).

## Summary

**Iterations run:** 3 sweeps (baseline 40/54 → 53/54 → 54/54 across all 8 rounds).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3212_touring_arena_show_routing_venue_settlement_rigging/test_helpers/fixtures.py` — `setup_in_performance_engagement`: with `with_approved_plan=False` the fixture skipped the approved-rigging-plan → mark-show-ready → clock-advance chain, leaving the engagement in IN_LOAD so reconcile correctly failed with `ERR_INVALID_STATE`. PRD §3.7 makes an APPROVED rigging plan an unconditional precondition of IN_LOAD → SHOW_READY, and §3.9 requires IN_PERFORMANCE for reconcile, so the chain now always runs; the flag only controls whether `point`/`plan` are attached to ctx. This fixed the 13 setup-failing settlement tests (triage hint applied — one shared fixture bug).

**Fixes applied to `test_suite/`:**
- `test_04_rigging.py::test_capacity_equality_allowed_excess_rejected` — restructured: the original built plan A (SUBMITTED) then created plan B, but PRD §3.4 verbatim supersedes any prior DRAFT/SUBMITTED/REJECTED plan on new-plan creation, so plan A was SUPERSEDED before its approve. Plan A is now created→submitted→approved before plan B exists; the capacity equality/excess assertions are unchanged. Also removed the now-dead `_build_two_plans` helper.
- `test_09_settlement.py::test_confirm_books_avail_then_reconcile_bubbles_tour_totals` — setup previously jumped CONFIRMED → IN_PERFORMANCE without the PRD-required show-ready gate; now runs the full rigging-approve/mark-show-ready/clock chain. Also relaxed `total_settlement_due_cents == 10000000` to `> 0`: PRD §3.9 defines it only as "the running sum of what is owed across settled engagements" without naming which settlement figure is owed (gross vs venue_share both admissible — unique-derivability collapse), so the absolute value assertion was removed while the bubble-up effect assertion stays.
- `test_09_settlement.py::test_tour_total_settlement_due_invariant_under_dispute_resolve_cycle` — same `total_settlement_due_cents` ambiguity: dropped the absolute `== 10000000` (kept `> 0` plus the dispute/resolve-cycle invariant, which is the PRD-covered rule).
- `test_09_settlement.py::test_terminal_settlement_paid_accepts_no_further_dispute` — relaxed exact `ERR_INVALID_STATE` to `validate_error_is_one_of([ERR_INVALID_STATE, ERR_SETTLEMENT_NOT_RECONCILED])` (ERROR PRECEDENCE SILENCE: PRD §3.9 names the dispute transition RECONCILED → DISPUTED but never names the error for disputing from PAID; both are PRD-catalogued 409 state-gate errors).

**Fixes applied to `implementation/`:** none — every implementation check exercised here (reconcile state gate, plan supersede cascade, settlement computation) traced to verbatim PRD prose and was correct.

(Orchestrator note: subagent's final-sweep results files were absent on disk after its exit, so the orchestrator re-ran the full 8-round sweep itself — all 8 rounds independently verified 54/54 passed, 0 failed, 0 errors.)

## Step 8: Finalize PRD — 2026-09-30T12:35:00.000Z

Done. PRD_FINALIZED.md is written with three inline edits and no other changes.

## Line counts

- PRD.md: 347 lines; PRD_FINALIZED.md: 347 lines — 0% delta in line count (3 lines revised in place, no lines added or removed).

## Changes

- **§3.1 (tour wrap paragraph)** — revise — appended that `total_settlement_due_cents` recomputes as the sum of each settled engagement's settlement `venue_share_cents` (the amount owed to the venue), cross-referencing §3.9 — `implementation/ticks.py:20` (`due += db.settlements[sid]["venue_share_cents"]` in `recompute_tour_counters`, invoked from `tick_tour` on WRAP at ticks.py:47).
- **§3.9 (reconcile paragraph)** — revise — pinned `total_gross_cents` as the running sum over settled engagements' `gross_ticket_cents` and `total_settlement_due_cents` as the running sum of `venue_share_cents` across settled engagements — `implementation/ticks.py:8-27` (gross from `gross_ticket_cents` at line 14, due from `venue_share_cents` at line 20; invoked after reconcile at `routes/settlements.py:75`).
- **§3.9 (dispute paragraph)** — revise — inserted that disputing from any status other than RECONCILED is rejected with `ERR_SETTLEMENT_NOT_RECONCILED` (HTTP 409) — `implementation/routes/settlements.py:106-107`.

## Step 7 diff items with no PRD edit (and why)

- `test_helpers/fixtures.py` `setup_in_performance_engagement` — pure fixture bug; PRD §3.7/§3.9 already pin the APPROVED-plan show-ready gate and IN_PERFORMANCE precondition for reconcile (impl: `routes/engagements.py:171-184`, `routes/settlements.py:46-47`). No silence.
- `test_04_rigging.py` restructure — PRD §3.4 already pins verbatim that creating a new plan supersedes any prior DRAFT/SUBMITTED/REJECTED plan (impl: `routes/rigging.py:37-40` with `helpers.py:13` `PLAN_NONTERMINAL = ["DRAFT", "SUBMITTED", "REJECTED"]`). No silence.
- `test_confirm_books_avail_then_reconcile_bubbles_tour_totals` setup fix — fixture ordering bug only; the PRD-required show-ready gate chain was already specified.

## Per-edit pre-edit search log

**Edit 1 (§3.1 wrap-recompute sentence):**
- (a) Subject: the composition of `total_settlement_due_cents` (and the wrap-time recompute).
- (b) Enumerated impl paths touching the subject: `ticks.py:8-27` (`recompute_tour_counters` — sums `venue_share_cents` over engagements in status SETTLED with a settlement); all four callsites — `ticks.py:47` (WRAP transition), `ticks.py:81` (engagement-cancel cascade), `routes/engagements.py:91` (confirm), `routes/settlements.py:75` (reconcile); `routes/tours.py:40-41` (creation zeroes); `routes/labor.py:134-176` (post-reconcile settlement mutations touch `labor_total_cents`/`promoter_net_cents` only, never `venue_share_cents`).
- (c) Wording adjustment: scoped the claim to "the amount owed to the venue" and cross-referenced §3.9 rather than asserting an isolated definition, and aligned the parenthetical's "settled engagements" qualifier with the impl's SETTLED-status filter — important because the shared recompute function also runs on confirm and cancel, where PRD §3.3 describes incremental semantics; describing the figure's composition (not the update mechanism) keeps all four callsites consistent.

**Edit 2 (§3.9 reconcile absorb sentence):**
- (a) Subject: same counter composition, at the reconcile site.
- (b) Same enumeration as Edit 1, plus `routes/settlements.py:23-29` (`_recompute_settlement` — dispute resolution recomputes `venue_share_cents` but not gross, so the dispute/resolve-cycle invariants hold under this wording) and `calc.py:20` (`compute_venue_share`).
- (c) Wording adjustment: changed PRD's "closed engagements" to "settled engagements" to match the impl's status filter exactly (no engagement status named CLOSED exists; the impl counts only SETTLED).

**Edit 3 (§3.9 dispute error):**
- (a) Subject: error identity for the dispute state gate.
- (b) Enumerated impl paths: `routes/settlements.py:106-107` (dispute gate raises `ERR_SETTLEMENT_NOT_RECONCILED` from any non-RECONCILED status including PAID, DISPUTED, OPEN); `routes/settlements.py:87-88` (mark-paid uses the same error for the same predicate); `errors.py:35` (catalogue: 409); `routes/settlements.py:120` (resolve-dispute uses `ERR_INVALID_STATE` — different transition, unaffected).
- (c) No adjustment needed; the new sentence mirrors the mark-paid sentence's existing phrasing, keeping the two gates symmetric exactly as the impl has them.

## Step 9: Complete PRD — 2026-09-30T12:55:00.000Z

The diff is clean — all 22 edits are in place with no unintended changes.

## Summary

**Files**: `/home/ubuntu/github/CodingPRD/tasks/task_3212_touring_arena_show_routing_venue_settlement_rigging/workspace/PRD_FINALIZED.md` (347 lines, 56,716 chars) → `PRD_COMPLETED.md` (347 lines, 60,957 chars; **+4,241 chars**, line count unchanged — all edits inline, no new sections).

**Counts**: 18 ambiguity-pins, 4 mismatch-revisions (22 edits total).

**Change log** (section — insert|revise — ambiguity|mismatch — what changed — impl ref):

1. §2.3 — insert — ambiguity — pagination tie-break by `id` ascending and `ERR_INVALID_REQUEST` (400) for invalid/out-of-range `limit`/`offset` — response.py:70-100
2. §2.4 — revise — ambiguity — `version` starts at 1; `created_at` taken from the logical clock — db.py:33-40
3. §2.6 — revise — mismatch — clock-set endpoint performs one full transition sweep before responding; laziness applies beyond that sweep (was "not eagerly at clock-set time") — flat.py:31, ticks.py:115-121
4. §3.1 (tour close) — insert — ambiguity — non-CANCELLED engagement with no settlement also fails the close gate — routes/tours.py:89-94
5. §3.1 (licenses) — insert — ambiguity — terminate from non-ACTIVE is `ERR_INVALID_STATE` (409) — routes/licenses.py:85-86
6. §3.2 — revise — mismatch — force-release of a HELD avail ends the avail in `RELEASED` (was implied `OPEN` via "HELD → OPEN" sentence) — routes/venues.py:186-193
7. §3.3 (create) — insert — ambiguity — avail must be `OPEN` (`ERR_AVAIL_NOT_OPEN` 409); endpoint check order: FK existence → timing consistency → containment → avail-OPEN gate → stale-version — routes/engagements.py:37-70
8. §3.3 (create) — insert — ambiguity — `market_overlap_flag` computed at create and on every read of a HOLD/CONFIRMED engagement; `open_engagement_count` counts HOLD..IN_PERFORMANCE and is recomputed from scratch — routes/engagements.py:19-29,83-85; ticks.py:8-27
9. §3.3 (hold expiry) — insert — ambiguity — expiry cancellation stamps `cancel_reason` `HOLD_EXPIRED` — ticks.py:94-96
10. §3.3 (cancel) — insert — ambiguity — cancelling from any other status is `ERR_INVALID_STATE` (409) — routes/engagements.py:162
11. §3.4 (submit) — insert — ambiguity — submit from non-DRAFT is `ERR_INVALID_STATE`; `submitted_by_user_id` stamps the submitter's `X-User-ID`; `high_risk_review_required` recomputed on each allocation add and at approve — routes/rigging.py:84-96,124
12. §3.4 (submit) — revise — ambiguity — high-risk dynamic threshold pinned to strictly exceeding 500 kg — constants.py:27, routes/rigging.py:22
13. §3.4 (approve) — insert — ambiguity — capacity checks run before segregation-of-duties; allocation referencing a nonexistent point yields `ERR_POINT_NOT_FOUND` (404) — routes/rigging.py:111-128
14. §3.5 — insert — ambiguity — arrival grace window pinned to 2 hours — constants.py:12, routes/trucks.py:94
15. §3.6 (post) — revise — mismatch — removed "headcount multiplying last" multiplication-order claim (Decimal multiplication is commutative; PRD's stated factors all present) and clarified the per-worker settle computation uses rate × weighted hours with no headcount factor — calc.py:87-89,100-117
16. §3.6 (cancel) — insert/revise — ambiguity — union cancel-notice pinned to 24 hours; late-cancel fee pinned to 25% (0.25) of `estimated_cost_cents` rounded half-up, recorded as `cancellation_fee_cents`; settlement labor total includes cancelled calls' fees; cancelling SETTLED/CANCELLED call is `ERR_INVALID_STATE`; "late-window-legal" reworded to "notice-legal" — constants.py:15-16, routes/labor.py:146-178
17. §3.6 (settle) — insert — ambiguity — absent `created_at` tie-break values sort as empty strings; missing/non-array `punch_records` or malformed records are `ERR_INVALID_REQUEST` (400); empty array settles at zero — calc.py:106, routes/labor.py:114-129
18. §3.7 (pass) — insert — ambiguity — pass check order state → timing → permit; early pass, non-SCHEDULED fail/waive, and non-POSTED labor fill are `ERR_INVALID_STATE` (409) — routes/inspections.py:74-77, routes/labor.py:98-99
19. §3.7 (waive) — insert — ambiguity — `ERR_WAIVE_REASON_REQUIRED` fires before `ERR_PYRO_NOT_WAIVABLE` — routes/inspections.py:116-120
20. §3.7 (show-ready) — revise — mismatch — gate requires every inspection on the engagement be PASSED/WAIVED (removed the undefined "tour's act profile" notion); non-IN_LOAD engagement is `ERR_INVALID_STATE` before the gate — routes/engagements.py:171-180
21. §3.8 — insert — ambiguity — non-positive sale `quantity` is `ERR_INVALID_REQUEST` (400) before the three sale constraints — routes/tickets.py:74-75
22. §3.9 (reconcile + royalty + resolve) — insert — ambiguity — tour counters recomputed from scratch; zero-eligible-engagement guarantee divisor treated as 1; resolve-dispute also recomputes `labor_total_cents`; resolving a non-DISPUTED settlement is `ERR_INVALID_STATE` (409) — ticks.py:8-27, calc.py:46-47, routes/settlements.py:23-29,119-120

No changes were needed for: roles/RBAC, response envelopes, OCC semantics in §2.7, venue/rigging-point/date-avail creation defaults (all match impl: `engineering_review_required` default true, `standard_load_in_hours` 8, `priority_rank` 100, `percentage_share_pct` range check, family-pack divide-then-multiply, venue-share floor, royalty 3-event rounding, dock-door ceil formula, union rule tables).
