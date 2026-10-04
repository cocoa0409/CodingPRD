# Worklog — task_3107_destination_medicine_referral_intake_multi_specialty_visit

## Step 1: Create Task Directory — 2026-09-29T23:26:00.000Z

Task directory was pre-allocated per command args: `./tasks/task_3107_destination_medicine_referral_intake_multi_specialty_visit/` with `workspace/` inside. Verified existence; no new index computed and no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-29T23:58:00.000Z

All three files are complete and pass `scaffold_lint.py` with a clean verdict.

Generated scaffold for `task_3107_destination_medicine_referral_intake_multi_specialty_visit` (Destination Medicine Referral Intake & Multi-Specialty Visit Bundling), at the deepest difficulty the skill supports — Expert band structure with all nine Difficulty Rules instantiated at maximum differentiation.

**Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3107_destination_medicine_referral_intake_multi_specialty_visit/`):**

- `SCAFFOLD.yaml` — §1.0–§1.7 plus concurrency rules
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` (§1.9)

**Counts:**
- Entities: 14 (SpecialtyService, Referral, Patient, MedicalRecord, VisitCase, CaseReview, EstimateLetter, FinancialClearance, Itinerary, AppointmentSlot, Visit, LogisticsArrangement, Communication, BillingTransaction)
- State machines: 8 (Referral, MedicalRecord, VisitCase, FinancialClearance, AppointmentSlot, Visit, Itinerary, LogisticsArrangement) — including a true cycle (clearance CLEARED→PENDING reopen), a fork-join (Itinerary DRAFT→CONFIRMED→LOCKED vs CANCELLED), compound/bubble-up (clearance→case, case→referral closure), and a system-driven SUM-threshold auto-withdrawal
- Calculations: 6 — dual-variant itinerary estimate (per-visit-round vs sum-then-round, pinned order), tiered deposit with >= boundaries, capacity threshold, half-open interval overlap, fatigue accumulator with circular-dependency evaluation order, 5-day itinerary window compression
- Validations: 21, ordered priority 1–21 across auth/existence/state/safety/referential/temporal/constraint/fiscal categories
- Endpoints: 59 (incl. `/_clock/set_current_utc` with the mandatory 2026-09-01T00:00:00Z default)
- Errors: 31, all referenced by at least one validation or transition
- Roles: 5 (PlatformAdmin, IntakeCoordinator, CaseReviewer, FinancialCounselor, LogisticsCoordinator), segregation-of-duties model (reviewer ≠ assigned coordinator; financial ops exclusive to FinancialCounselor)
- OCC concurrency rule: `slot-hold-stale-case` (412 ERR_STALE_VERSION on `POST /visit-cases/{id}/slot-holds` via `expected_case_version`)
- Difficulty instances: 18 (exactly 2 per rule × 9 rules), each with distinguishing aspects naming the §0.5-required differentiation (different entity domains, modes (a)/(b)/(c), error-category pairs, interval semantics, conserved quantities)
- Corner instances: 44 total (41 active with test recipes + 3 `excluded_because:` stubs), spanning entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting_layers / consistency_model sections

**Verified:** `scaffold_lint.py` clean (784 §1.8/§1.9 calls validated against §1.5: endpoint existence, role permission, payload shape, capture resolution, OCC placeholder discipline, and FK reverse-reachability); all numeric asserts pre-computed as literals (e.g., provisional 285015 vs final 285014; deposit tiers 60000/90000/180000; international 4-visit 144000 vs 143999); no forbidden concurrency vocabulary; instance names unique across both design files; file split honored (no design keys inside SCAFFOLD.yaml).

## Step 3: Copy Shared Files — 2026-09-30T00:00:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3107_destination_medicine_referral_intake_multi_specialty_visit/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T00:05:00.000Z

(Note: first subagent invocation exited prematurely after field inventory; resumed via SendMessage and it completed.)

PRD generation complete. The file exists at `/home/ubuntu/github/CodingPRD/tasks/task_3107_destination_medicine_referral_intake_multi_specialty_visit/workspace/PRD.md` — 288 lines, 6677 words. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened at any point.

## Document structure

- **§1 Introduction** — 3 paragraphs (business context, system scope, architectural stance: segregation of duties, tiered deposits, dual-variant estimates, OCC, logical clock).
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC (all 5 roles, `identity: opaque` prose per role, both auth error IDs), 2.2 response envelope (verbatim fixed block from `section-2.2-response-structure.md`), 2.3 pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields), 2.4 logical clock (initial `2026-09-01T00:00:00Z`, `current_utc`, no retroactive transitions, governs `received_at`/`sent_at`/`reviewed_on_date`), 2.5 common resource properties (UUID `id`, ISO-8601 3-fractional-digit timestamps, `version` semantics incl. cascade bumps), 2.6 monetary precision (integer cents, round half-up, rounding-order distinction teaser), 2.7 OCC (`expected_case_version` on slot-hold, `ERR_STALE_VERSION` 412, no other endpoint takes a version field), 2.8 validation ordering (full priority sequence 1–21 in prose), 2.9 nested retrieval (left-to-right 404), 2.10 hierarchical consistency (bidirectional cascades).
- **§3 Business Logic** — 8 subsections organized by lifecycle timeline: 3.1 services/slots/capacity, 3.2 referral intake & records, 3.3 case review + segregation of duties + fatigue accumulator (+2 verify, −3 remote-consult floor 0, ≥10 auto-withdraw, ≤3 distinct review days guard), 3.4 slot holds & visit booking (OCC, overlap, capacity boundary, imaging flag), 3.5 estimates/deposits/estimate letters (dual-variant rounding order, 0/5/10% tiers at bundled counts ≤2/=3/≥4, 1.20 international multiplier, deposit tiers 500000→30%, 100000→20%, else 10% with inclusive boundaries, 150000-cent base seed, supersede + staleness via `itinerary_revision_at_issue` vs current `revision`), 3.6 financial clearance (threshold equality-clears, waiver domestic-only, reopen limits incl. `holds_released` asymmetry, 14-day forfeit deadline with depth-3 cascade, settlement ≥3 completed + amount overwrite + compensating invariant), 3.7 withdrawal/confirmation/travel authorization/visit completion (5-day window boundary, sequencing guard with `created_at` tiebreak, `ERR_VISIT_NOT_DUE`, auto-completion rule), 3.8 logistics/communications/referral closure (interpreter gating, `continuity_plan` owner/`follow_up_weeks` 1–52, dual-communication closure requirement).
- **§4 Endpoint table** — 59 rows matching all 59 scaffold endpoints, 4 columns (Method, Path, Description, Authorized Roles), 201-vs-200 status rule paragraph above.
- **§5 Error catalogue** — all 31 error IDs with HTTP statuses, 2 columns, no trigger conditions.

## Hard contract reports

Field coverage check: entities[].fields + endpoints[].input 67/67; query_params 16/16; nested sub-keys 8/8; errors 31/31; roles 5/5; state values 32/32; enum values 56/56 — PASS.

Rule coverage check: validations priority ordering in §2.8 plus per-rule error pairings in §3; concurrency rule slot-hold-stale-case in §2.7/§3.4; all 8 state machines' transitions with preconditions + side effects; all 6 calculations as precise prose; all 21 validations matched to error_ids; side_effects/applies_to expressed; sibling-branch symmetry rendered at equal density — PASS.

Path purity check (§3 only): 419 backtick tokens scanned; 0 path/method tokens — PASS.

One tooling note: an early verification pass produced false "missing" reports because the naive backtick regex mis-paired across the §2.2 fenced code blocks. The final checker masks fenced blocks before extracting tokens; the PRD text itself was correct, and only one real gap existed (`CLOSED` not backticked in two state-pair arrows), which was fixed.

## Step 5: Generate Unit Tests — 2026-09-30T00:40:00.000Z

Generation complete. All 79 tests collect cleanly, every docstring carries a verbatim-grep-verified PRD citation plus exactly one Design tag, and no skip/xfail markers exist anywhere.

**Output locations**
- `test_helpers/` — 9 files: `__init__.py` (barrel export), `types.py` (15 entity TypedDicts, all `common_fields: true`), `api_client.py` (43 endpoint methods + `Connection: close` keep-alive hardening), `api_errors.py` (31 error IDs + HTTP map registered with the framework), `assertions.py`, `factories.py`, `constants.py` (deposit tiers, fatigue thresholds, canonical operator IDs), `test_users.py` (all roles opaque per PRD §2.1 — shared constants canonical), `fixtures.py` (composite setup tiers: `setup_referral_in_review`, `setup_approved_case`, `setup_cleared_case`, `setup_case_with_holds`, `setup_scheduled_case`, `setup_ready_to_travel_case`, `setup_fatigue_case`).
- `test_suite/` — `conftest.py` + 7 test files, 79 tests total.

**Coverage audit (automated)**
- Queue A (Difficulty): all 18 instances covered with ≥2 tests each (36 tests).
- Queue B (Corner): all 40 non-stub instances covered with ≥1 test (43 tests). The 3 `excluded_because:` stubs (`error_slot_not_open`, `error_capacity_exhausted`, `error_stale_estimate_letter`) were not translated; their cross-referenced difficulty instances all resolve.
- Every PRD citation block (83 blocks) passes a literal whitespace-normalized grep against `workspace/PRD.md`; every docstring ends with exactly one `Design:` tag resolving to a real instance.

**Instances skipped: none.** One deviation from the literal recipe: `Difficulty/priority_pair_validation_conflict/state_precondition_beats_business_fiscal_on_slot_confirm` test 1 also asserts the slot remains `OPEN` (a PRD-derivable side condition); the second tagged test for that instance exercises the isolated fiscal error (`ERR_FINANCIAL_CLEARANCE_REQUIRED`, 402) on a genuinely HELD slot with a reopened PENDING clearance.

**Notes on asserted constants** (all PRD-derivable from §3.5 formulas): 285015/285014 provisional-vs-final rounding split, 60000 approval deposit (2×150000 → 20% tier), 57003 letter deposit (round_half_up(285014×0.20)), 144000/143999 international 4-visit totals, 20000 deposit at the 100000 tier boundary, fatigue auto-withdrawal at exactly 10 with score 8 staying INTAKE.

## Step 6: Generate Implementation — 2026-09-30T01:00:00.000Z

All 59 routes (52 unique paths + 7 distinct-method registrations counted per entry in the ROUTES table — matching the full PRD §4 endpoint table, including both nested and top-level routes). Done.

**Files written** (all under `workspace/implementation/`):
- `start.sh` — executable, `exec`s the server in foreground, binds `0.0.0.0:$PORT` (default 10000), guards `pip install` behind an `import flask` check
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry, envelope (`meta`/`response_type`/`data`), error handler (`error_id`/`message`), header auth + RBAC wrapper
- `db.py` — in-memory stores (14 entity tables, all empty at boot) + logical clock initialized to `2026-09-01T00:00:00Z`
- `helpers.py` — envelope/pagination/IDs/Decimal rounding/validators, `ApiError`
- `services.py` — estimate engine, tiered deposit, fatigue accumulator, release/decline cascades, completion + referral-closure re-evaluation, capacity/overlap/sequencing
- `routes.py` — all 59 route registrations

**Endpoints**: all from PRD §4 implemented (clock, specialty services, slots, referrals, patients, medical records + verify/reject/submit-review, visit cases, reviews, withdraw, authorize-travel, financial clearance + waive/reopen/forfeit, estimate letters, billing transactions (per-case + global), itinerary + confirm/lock, slot holds, visits + complete/no-show/cancel, logistics + confirm/cancel, communications), each with the exact role set from the RBAC matrix.

**State machines implemented**: Referral (SUBMITTED→RECORDS_PENDING→IN_REVIEW→REVIEWED→CLOSED with DECLINED branch), MedicalRecord (RECEIVED→VERIFIED/REJECTED), VisitCase (9-state pipeline incl. INTAKE/AWAITING_FINANCIAL/FINANCIAL_CLEARED/SCHEDULING/SCHEDULED/READY_TO_TRAVEL/COMPLETED/WITHDRAWN/DECLINED, manual + fatigue auto-withdrawal), FinancialClearance (PENDING↔CLEARED, FORFEITED/SETTLED/WAIVED terminal), AppointmentSlot (OPEN→HELD→CONFIRMED, RELEASED/CANCELLED terminal), Visit (PENDING→CONFIRMED→COMPLETED/NO_SHOW/CANCELLED), Itinerary (DRAFT→CONFIRMED→LOCKED, CANCELLED), LogisticsArrangement (REQUESTED→BOOKED/CANCELLED).

**Calculations implemented**: dual-variant itinerary totals (provisional rounds per-visit then sums; final sums then rounds once, with 0%/5%/10% bundling tiers and 1.20 international multiplier, Decimal + ROUND_HALF_UP), tiered deposit (10%/20%/30% at 100000/500000 floors, inclusive boundaries, care-team-size × 150000 approval seed with international multiplier), aggregate per-date capacity pool (strict `<` at hold time), half-open interval overlap (adjacency legal), fatigue accumulator (+2 per verify, −3 per REMOTE_CONSULT completion, floor 0, auto-withdraw at `>= 10`), 5-distinct-date itinerary window compression, 14-day forfeit deadline, OCC via `expected_case_version` (412).

**Validation ordering**: auth headers → role → path existence (left-to-right) → body shape → state → OCC → segregation-of-duties → business rules, per PRD §2.8; all 31 error IDs from §5 mapped to their exact HTTP statuses (including 402 for `ERR_FINANCIAL_CLEARANCE_REQUIRED` and 412 for `ERR_STALE_VERSION`).

**Fresh-boot smoke test**: confirmed — server booted from a clean process on three separate invocations (ports 18731/18733/18734/18735), each killed by its own saved PID. ~60 assertions passed across referral intake, review SoD, approval fan-out, deposit clearing (equality boundary), OCC 412, slot confirm/release/cancel semantics, estimate-letter supersede/staleness, settlement minimum-visit gate, international waiver prohibition, interpreter rules, fatigue auto-withdrawal at exactly 10, withdraw/decline cascades, no-show timing, sequencing guard, referral closure via both communications, pagination bounds, and envelope shape. No seeding anywhere — the store starts empty on every boot.

## Step 7: Run Tests and Iterate — 2026-09-30T01:30:00.000Z

All 8 rounds pass, 79/79 each. Clean sweep.

- **Iterations run**: 2 fix iterations (3 sweeps total; final sweep clean: 8/8 rounds, 79/79 tests each).

- **Tests deleted**: none. (Two assertions were *split out* of existing tests per STEP 1c — see below — no whole test was removed.)

- **Fixes applied to `test_helpers/`**:
  - `test_helpers/fixtures.py` — `register_and_verify_record` returned the stale register response (status `RECEIVED`); now returns the verify response (status `VERIFIED`), matching PRD §3.2's "A successful verification moves the record to `VERIFIED`".

- **Fixes applied to `test_suite/`**:
  - `test_04_clearance_lifecycle.py::test_forfeit_reopen_blocked_after_holds_released` — called `validate_error(resp)` with no expected id (TypeError); switched to the framework's `validate_error_is_one_of([ERR_CLEARANCE_HOLD_RELEASED, ERR_INVALID_STATE])`, which is exactly what the test already intended and PRD §3.6 permits.
  - `test_04_clearance_lifecycle.py::test_refund_restores_clearance_balance` and `::test_refund_voids_only_source_deposit` — removed the `clearance["status"] == "PENDING"` assertion after refund. PRD §3.6 defines refund effects as only "the referenced source DEPOSIT transaction is voided … and the refunded amount is subtracted from deposit_paid_cents", and describes exactly "one reversible edge back from CLEARED to PENDING" (the reopen action). A refund-driven CLEARED→PENDING revert is not uniquely derivable (unique-derivability collapse: branch-asymmetric side effect / single reversible edge). Covered assertions (deposit_paid_cents subtraction, source txn VOID) were kept.
  - `test_06_travel_fatigue_closure.py` — three fatigue tests had broken increment arithmetic (fixture's `verify_first=1` verify lands before the case exists and counts 0 per PRD §3.3, so `records[1:4]` = 3 verifies = 6 points, not 8). Fixed: threshold tests now use `num_records=6` with 5 post-case verifies (8 → INTAKE, then 10 → WITHDRAWN), and `test_nine_points_does_not_withdraw` verifies `records[1:5]` for a true 8-points-below-threshold check.
  - `test_03_estimates_and_deposits.py::_four_international_hold_setup` and `test_06_travel_fatigue_closure.py::_international_scheduled_case` — `deposit_cents=180000` underpaid the PRD-derived international 4-team requirement (4×150000=600000 ×1.20 = 720000 → 30% tier = 216000); updated to 216000 once the clearance correctly required the seeded deposit.

- **Fixes applied to `implementation/`** (all in `workspace/implementation/routes.py`):
  - `set_current_utc` — now echoes the submitted `current_utc` verbatim instead of a normalized `.000Z` rendering (PRD §2.4: "replies with the accepted `current_utc`").
  - `create_slot` — creation-time overlap check now covers existing `OPEN` slots as well as `HELD`/`CONFIRMED` (PRD §3.1: "creation overlapping an existing slot is rejected with `ERR_SLOT_OVERLAP`", no status qualification; terminal RELEASED/CANCELLED slots still excluded so forfeiture genuinely frees intervals).
  - `cancel_visit` / `release_slot` — removed the `itinerary["status"] == "DRAFT"` gate on the revision bump + totals recompute (PRD §3.4 states the bump unconditionally; the gate was silently keeping issued estimate letters fresh after confirmed-visit cancellations).
  - Approval fan-out in `create_case_review` — `FinancialClearance` is now born with `required_deposit_cents` = the case's seeded tiered deposit instead of 0 (PRD §3.6: clearance is "born PENDING … otherwise it waits for money"; the only nonzero figure PRD names at approval is the seeded tier deposit — the 0 default had made every threshold check vacuous).

- **Key findings**: The original failures were deterministic (identical 11 failures across all 8 rounds), not flaky. Root causes split roughly evenly between implementation deviations from PRD prose (clock echo, unconditional revision bumps, overlap scope, clearance seed) and test-artifact bugs (stale fixture return, arithmetic miscount in fatigue tests, undersized international deposit in fixtures, and two non-PRD-derivable refund status assertions corrected via partial-coverage split).

## Step 8: Finalize PRD — 2026-09-30T01:40:00.000Z

**File produced**: `/home/ubuntu/github/CodingPRD/tasks/task_3107_destination_medicine_referral_intake_multi_specialty_visit/workspace/PRD_FINALIZED.md`

**Line counts**: PRD.md 288 lines, PRD_FINALIZED.md 288 lines (0.0% delta — all changes are inline revisions within existing sentences; 6 lines modified, no lines added or removed).

### Changes (one bullet per edit)

- §2.4 — revise — clock-set capability now specified to reply with the accepted `current_utc` "echoed verbatim, exactly as submitted (no re-formatting or normalization)" — `implementation/routes.py:47` (`set_current_utc` returns `body["current_utc"]` raw).
- §3.1 — revise — slot-creation overlap check pinned to existing slots in non-terminal status (`OPEN`/`HELD`/`CONFIRMED`); terminal `RELEASED`/`CANCELLED` slots explicitly do not block creation — `implementation/routes.py:140-147` (`create_slot`).
- §3.3 — revise — approval fan-out now states the `FinancialClearance` is born with `required_deposit_cents` initialized to the seeded tiered deposit — `implementation/routes.py:534-544` (`create_case_review`).
- §3.4 — revise (two clauses, one sentence pair) — slot-release and visit-cancellation itinerary `revision` bump + totals recompute pinned as unconditional, "regardless of the itinerary's current status" — `implementation/routes.py:210-217` (`release_slot`), `implementation/routes.py:1115-1121` (`cancel_visit`).
- §3.6 — revise — clearance birth sentence now pins `required_deposit_cents` = the case's seeded tiered deposit (the approval-computed `deposit_amount_cents`), with estimate-letter issuance overwriting it — `implementation/routes.py:539`, `implementation/routes.py:725-734`.
- §3.6 — revise — `REFUND` effects pinned as exhaustive: voids source deposit and subtracts from `deposit_paid_cents` only; never changes clearance `status` and does not re-run the threshold check — `implementation/routes.py:818-839`.

### Step-7 items with no PRD edit (with reason)

- `test_helpers/fixtures.py` stale register/verify response — pure fixture bug; PRD §3.2 already pinned `VERIFIED`.
- `test_04` `validate_error` TypeError fix and refund-status assertion removals — test-artifact fixes; refund behavior pinned by the §3.6 refund edit above.
- `test_06` fatigue arithmetic fixes (`num_records=6`, `records[1:5]`) — test miscount; PRD §3.3 already pins +2/verify on existing non-terminal cases and the inclusive ≥10 threshold.
- International deposit fixture 180000→216000 — fixture underpayment; PRD §3.5 already pins 4×150000×1.20→30% tier.

### Per-edit pre-edit search log

1. **Clock echo (§2.4)** — (a) subject: clock-set response body. (b) enumerated: `routes.py:40-47` (only endpoint returning `current_utc`); `helpers.py:115-129` (`parse_iso8601_utc` normalizes only the internally stored clock); `db.py:11-15`; grep `current_utc|set_clock|get_clock` across all impl files — no other path reads/returns the submitted string. (c) none.
2. **Creation overlap scope (§3.1)** — (a) subject: creation-time overlap check. (b) enumerated: `routes.py:140-147` (creation, statuses `OPEN/HELD/CONFIRMED`); `routes.py:943-955` (hold-time overlap, `HELD/CONFIRMED` only — separate rule already pinned in §3.4, untouched); `services.py:268-278` (`slots_overlap`, `used_capacity`); all `held_by_case_id` sites (release/forfeit/withdraw cascades set slots terminal, consistent with "frees its interval"). (c) scoped wording to creation only ("creation overlapping...") so the hold-time rule in §3.4 is not re-defined.
3. **Unconditional revision bump (§3.4)** — (a) subject: itinerary revision bump on release/cancel. (b) enumerated: `routes.py:210-217` (release, no status gate), `routes.py:1115-1121` (cancel, no status gate), `routes.py:686-689` (forfeit bumps only if DRAFT — governed by its own §3.6 sentence, untouched), `routes.py:528` (birth at revision 1), `routes.py:989-990` (hold recomputes totals but does NOT bump revision — §3.4 already says only totals recompute on hold; my wording does not claim otherwise), `services.py:80-86` (`letter_view` staleness from revision). (c) wording scoped to "release ... and visit-level cancellation" with "regardless of the itinerary's current status", avoiding any universal claim about all revision mutations.
4. **Clearance birth `required_deposit_cents` (§3.3 + §3.6)** — (a) subject: clearance creation and the `required_deposit_cents` field lifecycle. (b) enumerated all `required_deposit_cents|deposit_paid_cents|deposit_amount_cents` sites: `routes.py:524` (seed compute), `routes.py:539` (birth), `routes.py:729/733` (issuance overwrite on PENDING and CLEARED), `services.py:257-263` (threshold compare), `routes.py:813/837` (deposit/refund arithmetic). (c) §3.6 wording includes "whose issuance overwrites the seeded initial value" to stay consistent with the estimate-letter overwrite paths, including the CLEARED-status overwrite branch.
5. **Refund effects exhaustive (§3.6)** — (a) subject: REFUND transaction effects. (b) enumerated: `routes.py:818-839` (sole REFUND branch: voids earliest POSTED deposit, subtracts amount, `touch` only — no status change, no `maybe_clear_on_deposit` call); `services.py:247-263` (clearing paths only invoked from deposit posting and letter issuance); reopen endpoint `routes.py:642-657` is the only CLEARED→PENDING edge. (c) added "does not re-run the clearance threshold check" to cover the absence of `maybe_clear_on_deposit` in the refund branch, and cross-referenced reopen as the sole reversible edge, consistent with the lifecycle sentence in the same section.

## Step 9: Complete PRD — 2026-09-30T01:55:00.000Z

All edits applied. Source: PRD_FINALIZED.md → PRD_COMPLETED.md at `workspace/PRD_COMPLETED.md`.

**Counts**
- Lines: 288 → 288 (in-paragraph edits only; no new sections)
- Chars: 50460 → 52365 (+1905)
- Ambiguity-pins: 12; mismatch-revisions: 3

**Changes** (`{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl}`)
- §2.1 — insert — ambiguity — unrecognized `X-User-Role` value rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400), not 403 — `implementation/app.py:74-76`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — `implementation/helpers.py:159-179`
- §3.1 — insert — ambiguity — duplicate service `code` and window field violations are `ERR_INVALID_REQUEST` — `implementation/routes.py:81-83,63-74`
- §3.2 — insert — ambiguity — all referral payload violations (incl. MN-resident rejection) are `ERR_INVALID_REQUEST` — `implementation/routes.py:230-254`
- §3.2 — insert — ambiguity — referral accepts new records in exactly `SUBMITTED` or `RECORDS_PENDING` — `implementation/routes.py:321-322,332-334`
- §3.2 — revise — mismatch — removed "(the self-transition is recorded for audit)"; rejection does not touch the referral — `implementation/routes.py:370-379`
- §3.3 — revise — mismatch — review guard 1 accepts cases in `INTAKE`, `AWAITING_FINANCIAL`, `FINANCIAL_CLEARED`, or `SCHEDULING`, not only `INTAKE`; fatigue guard counts distinct dates per case (not per reviewer) — `implementation/routes.py:31,484,496-503`
- §3.3 — insert — ambiguity — approval creates no itinerary for `SECOND_OPINION`/`REMOTE_CONSULT` cases — `implementation/routes.py:525-533`
- §3.4 — insert — ambiguity — slot hold also rejected with `ERR_INVALID_STATE` from `SCHEDULED`/later states and when the itinerary is missing or not `DRAFT` — `implementation/routes.py:919-925`
- §3.4 — insert — ambiguity — release's revision bump + totals recompute apply even when no pending visit existed to cancel — `implementation/routes.py:210-217`
- §3.5 — insert — ambiguity — approval seed estimate applies the 1.20 international multiplier on top of care-team-size × 150000 for international patients — `implementation/services.py:127-134`
- §3.5 — insert — ambiguity — estimate-letter issuance requires an itinerary (`ERR_INVALID_STATE` otherwise), recomputes totals at issuance, and updates `required_deposit_cents` for `PENDING` or `CLEARED` clearances with threshold re-evaluation on `PENDING` — `implementation/routes.py:700-735`
- §3.6 — insert — ambiguity — `DEPOSIT` requires clearance `PENDING`; `REFUND` requires at least one `POSTED` deposit, targets the oldest, and records `refunded_txn_id` — `implementation/routes.py:801-839`
- §3.6 — revise — ambiguity — zero-required clearance clears when the zero requirement is evaluated (creation or later issuance), not only "immediately upon creation" — `implementation/routes.py:728-731`, `implementation/services.py:257-263`
- §3.6 — insert — ambiguity — with no `HELD` slot there is no deadline anchor, so forfeiture can never pass the breach check — `implementation/services.py:289-296`
- §3.7 — revise — mismatch — removed the system auto-no-show on clock advance; no-show is explicit coordinator action only — `implementation/routes.py:1088-1101` (no clock hook exists anywhere)
- §3.8 — revise — mismatch — communications are always accepted when well-formed; `ERR_RESULTS_NOT_TRANSMITTED`/`ERR_CONTINUITY_PLAN_MISSING` are closure-obligation identifiers, not send-time errors — `implementation/routes.py:1212-1240`, `implementation/services.py:229-242`

Deliberately left unchanged (PRD already pins uniquely): envelope shape, pagination meta, clock echo semantics, capacity-pool strict-below rule, half-open overlap/adjacency, estimate dual-variant rounding, deposit tiers, hold precondition battery (incl. redundant window check), itinerary confirm/lock guards, sequencing tie-break by `created_at`, interpreter arrangement rules, withdraw/forfeit cascades, and the endpoint/role table (matches `ROUTES` exactly).
