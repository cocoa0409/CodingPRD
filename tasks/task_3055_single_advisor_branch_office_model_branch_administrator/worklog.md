# Worklog — task_3055_single_advisor_branch_office_model_branch_administrator

## Step 1: Create Task Directory — 2026-09-29T18:24:00.000Z

Task directory `./tasks/task_3055_single_advisor_branch_office_model_branch_administrator/workspace/` was pre-allocated by the invoking command; verified it exists with `workspace/` inside. No new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-29T18:52:26.720Z

Clean lint, verbatim verdict:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_3055_single_advisor_branch_office_model_branch_administrator/SCAFFOLD.yaml
  Difficulty design:  tasks/task_3055_single_advisor_branch_office_model_branch_administrator/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_3055_single_advisor_branch_office_model_branch_administrator/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    73
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     37
  Calls scanned (§1.8+§1.9):  585

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3055_single_advisor_branch_office_model_branch_administrator/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_3055_single_advisor_branch_office_model_branch_administrator/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_3055_single_advisor_branch_office_model_branch_administrator/SCAFFOLD_CORNER_DESIGN.yaml`

**Surface counts:** 14 entities, 73 endpoints, 24 error codes, 6 calculation rules, 8 state machines, 2 OCC concurrency rules, 4 RBAC roles. Above-Expert band per the caller's difficulty instruction, with difficulty concentrated in coupled mechanics rather than volume.

**Difficulty design:** 18 active instances (exactly 2 per each of the 9 rules). Highlights: dual-variant calcs on two different domains (P&L profit share provisional/final vs goodwill valuation internal/open-market); combinatorial modes (a) tiered nested min/max and (b) per-record rounding order; cyclic state machines on GoodwillTransfer (negotiation alternation) and TrainingProgram (remediation loop); cascades of depth 3 (charge→totals→net→share) and 2 (terminate→branch/territory/solicitations); priority pairs state-vs-safety and safety-vs-referential; half-open vs closed interval overlap semantics; two compensating invariants (period fiscal totals, escrow balance).

**Corner design:** 37 active instances + 4 `excluded_because` stubs, across sections entities(6), state_machines(8), calculations(3), validations(7), endpoints(3), errors(3), rbac(4), cross_cutting_layers(2), consistency_model(1).

**Design adjudications made:**
1. **Fixed arithmetic literals** computed by executing the formulas in Python (share(1,160,000)=473,600; share(1,150,000)=469,000; share(1,000,010)=400,005; valuation 1,800,000 vs 2,640,000; per-record rounding 51+51=102 vs sum-then-round 101).
2. **Priority-conflict instance 1 reframed** from state-vs-fiscal to state-vs-business_safety (counter-offer on a DECLINED transfer by the last offerer) — the original pairing could not produce an honest dual-failure given the validation table's `applies_to` scopes.
3. **Enum-closure fixes**: added `retire` transitions/endpoints for Territory and ProductShelfEntry, and `place-on-leave`/`return-from-leave`/`release` for the BOA, so every declared enum value has a producer.
4. **FK reverse-reachability**: added `GET /advisors/{id}/{goodwill-transfers,solicitation-requests,production-records}`, `GET /branches/{id}/charges`, and filter params on `GET /advisors`.
5. **Auto-period hazard**: branch `open` auto-creates an OPEN period, which would block branch `close` in two corner instances — chains were amended to fetch the auto period via list capture and close+finalize it (at clock 2026-10-02, deliberately before the 30-day goodwill expiry at 2026-10-05).
6. **Revenue attribution fix**: the immediate-consistency corner instance originally posted revenue for an unassigned advisor; it now fully enrolls/validates/assigns the advisor so period revenue resolves.
7. All 585 calls across both design files pass the linter's endpoint/role/payload/capture/OCC checks with zero unbound placeholders and unique instance names.

## Step 3: Copy Shared Files — 2026-09-29T18:52:42.632Z

Copied `./INSTRUCTION.md` to `./tasks/task_3055_single_advisor_branch_office_model_branch_administrator/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-29T18:59:09.195431068Z

Done. The two difficulty-design files were never opened.

## Summary

**PRD path:** `/home/ubuntu/github/CodingPRD/tasks/task_3055_single_advisor_branch_office_model_branch_administrator/workspace/PRD.md` — 286 lines.

**Section list:**
- §1. Introduction (3 paragraphs: business model, lifecycle scope, ledger-semantics framing)
- §2. Global Specifications — 2.1 RBAC (with per-role identity prose), 2.2 Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Common Resource Properties & OCC, 2.5 Nested Retrieval & Validation Order, 2.6 Monetary Precision & Rounding Orders, 2.7 Logical Clock, 2.8 Branch P&L Integrity (waterfall + deficit carryforward), 2.9 Staffing Invariants
- §3. Business Logic — 3.1 Training/Validation pipeline, 3.2 Territories & Door-Knocking, 3.3 Branch Siting/Leasing/Staffing/Opening, 3.4 Production Posting, 3.5 Period Close/Reopen/Finalize, 3.6 Profit Share & Service Tier, 3.7 Retirement & Goodwill Negotiation, 3.8 Product Shelf & Solicitation Approval
- §4. Endpoint Definitions (72 endpoints, 4-column table)
- §5. Error Code Catalogue (24 errors, 2-column table)

**Zero-Silence Rule audit (all three hard contracts PASS):**

- **Contract 1 — Field coverage:** 68 required identifiers (entity fields + endpoint inputs + path params), 68 present in backticks, 0 missing. Mechanical check via YAML parse vs backtick extraction. Three stragglers (`training_program_id`, `period_id`, `administrator_id`) were found and repaired in a second pass.
- **Contract 2 — Rule coverage:** all 10 state machines' transitions expressed with from/to states, preconditions paired to error IDs, and side effects stated (including the termination cascade's auto-cancel of OFFERED/NEGOTIATING transfers with escrow refund, and the asymmetric `ERR_TRANSFER_ACTIVE` scope between rescind-retirement and branch close). All 6 calculations fully translated to prose with pinned rounding/evaluation orders (per-record half-up then sum for milestones; per-tier half-up before summing for profit share; floor division and inclusive TIER_2 boundary at score 900; trailing-12-complete-months valuation window with 0.75/1.10 multiples; waterfall charge order DEFICIT_CARRYOVER → LEASE_RENT → BOA_PAYROLL → EQUIPMENT). Both OCC rules expressed with endpoint, `expected_<parent>_version` field, and `ERR_STALE_VERSION`/412. All 24 validations traceable to their error IDs in prose, including the capacity-before-window check order on contact logging and the segregation-of-duties-first ordering on solicitation approval. All 24 error IDs, all ~40 state values (backtick-verified), and all 4 role names present.
- **Contract 3 — §3 path purity:** 358 backticked tokens scanned inside §3, 0 violations (no paths, no bare HTTP methods, no method+path tokens).

Notable boundary semantics pinned in prose: half-open territory assignment intervals with adjacency allowed vs. closed lease intervals with adjacency conflicting; inclusive milestone goal boundary; inclusive 30-day expiry boundary (`clock >= created_at + 30 days`); provisional-vs-final profit-share variants; clock default `2026-09-01T00:00:00Z`.

## Step 5: Generate Unit Tests — 2026-09-29T19:21:53.839542109Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (9 files): `types.py` (status enums + TypedDicts, with lean `id`/`created_at`-only shapes for DoorKnockContact / MilestoneEvaluation / ProductShelfEntry per the PRD), `api_client.py` (one method per PRD endpoint, subclassing `GenericApiClient`), `api_errors.py` (all 24 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (per-instance `make_advisor_headers` / `make_branch_administrator_headers` builders for the two entity-backed roles), `fixtures.py` (composite setups: `create_validated_advisor` driving the full CANDIDATE→VALIDATED pipeline, `create_open_branch` / `setup_open_branch_with_period` reaching FULLY_STAFFED OPEN, `setup_retiring_advisor_with_transfer` with clock-setting before transfer creation, `setup_practicing_advisor_with_solicitation`), `__init__.py` barrel.

**`test_suite/`**: `conftest.py` + 18 test files, **73 tests total**.

## Coverage

- **Queue A (difficulty)**: 36 tests — all 9 non-stub §1.8 instances with exactly 2 tests each.
- **Queue B (corner)**: 37 tests — all 22 non-stub §1.9 instances with ≥1 test each (the two larger corner instances got two tests).
- **4 `excluded_because:` stubs** not translated; all their `difficulty_instance` cross-references verified to resolve.

## Per-instance audit

All 55 non-stub instances (9 queue A + 22 queue B, where queue A requires ≥2 and queue B ≥1) emitted; **none skipped** — every instance passed the PRD-first two-condition filter. Notable design decisions:

- `profit_share_provisional_vs_final_on_charge_correction`: the reopen/repost/re-close sequence keeps the first close's 473600 snapshot observable while the finalize yields 469000 — both variants PRD-covered.
- `safety_vs_referential_on_solicitation_approval`: the design's own assert text says the Advisor-role approval returns `ERR_UNAUTHORIZED` (role gate precedes safety/referential), so no segregation-of-duties assertion was emitted (the PRD doesn't uniquely pin the role-vs-safety ordering).
- `goodwill_complete_gated_by_advisor_statuses`: tests translated faithfully to the PRD gate (rescind-to-PRACTICING blocks complete with `ERR_INVALID_STATE`; VALIDATED-successor path verifies the full succession cascade including `predecessor_advisor_id`).
- `error_transfer_active_blocks_close`: used the retiring-advisor/SUCCESSION_PENDING route (suspend from OPEN after finalize) rather than termination, since termination would release the advisor and auto-cancel the transfer.

## Stage 2 self-check results (all green)

- Every test has exactly one `Design:` tag, last docstring line, resolving to a real instance; no untagged/dual-tagged/dangling tags.
- Every docstring contains a ≥8-word span that literally greps in `PRD.md`.
- No `pytest.mark.skip`/`skipif`/`xfail`; no "scaffold" or §1.x references in generated code; everything compiles; `test_helpers` imports cleanly.

One caveat for the downstream implementation pass: the PRD does not explicitly state whether creating a second GoodwillTransfer on a branch while one is OFFERED is permitted — one test (`test_internal_valuation_rounds_half_up`) guards that optional second-create behind a status check so it asserts only when the create succeeds.

**Orchestrator audit note:** subagent's "22 corner instances / 9 difficulty instances" phrasing was imprecise; independent grep+YAML audit confirms 18 difficulty instances (all covered, 2 tags each) and 37 active corner instances (all covered, 1 tag each), 4 excluded stubs correctly untranslated, 73 tests total = 36 queue A + 37 queue B.

## Step 6: Generate Implementation — 2026-09-29T19:48:22.173076993Z

Done. Summary below.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_3055_single_advisor_branch_office_model_branch_administrator/workspace/implementation/`:

- `start.sh` — launcher; guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py` (foreground, `$PORT` default 10000, `0.0.0.0`).
- `requirements.txt` — `flask>=3.0`.
- `app.py` — app factory, blueprint registration, error handlers (ApiError → envelope; 404/405 → `ERR_NOT_FOUND`).
- `db.py` — in-memory dict stores (all empty at boot), logical `clock` defaulting to `2026-09-01T00:00:00Z`, UUID + request-id generators, ISO-8601-with-millis formatter.
- `errors.py` — `ApiError` + full error catalog (id → HTTP status) verbatim from scaffold §1.6.
- `response.py` — success/error envelopes per §2.2 (`meta.api_request_id`, `meta.api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` for lists).
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, role whitelist (`HomeOfficeAdmin`, `Advisor`, `BranchAdministrator`, `CompliancePrincipal`), 401/403 enforcement.
- `helpers.py` — body validation, datetime parsing, `round_half_up_cents` (Decimal/ROUND_HALF_UP), pagination (limit default 10, min 1, max 100, offset 0; sorts by `created_at` asc), plus domain helpers: `recompute_staffing`, `recompute_tier`, `profit_share` (per-tier round-then-sum), `recompute_period`, `recompute_advisor_cumulative`, `release_territory`.
- `routes/advisors.py` — register/list/get; enroll-training (CANDIDATE→TRAINEE + TrainingProgram ACTIVE); assign-branch (VALIDATED→PRACTICING, territory takeover, staffing update); declare/rescind retirement (ownership check, `ERR_TRANSFER_ACTIVE` on ACCEPTED/COMPLETED); terminate cascade (branch SUSPENDED, territory released, SUBMITTED solicitations WITHDRAWN, OFFERED/NEGOTIATING transfers auto-CANCELLED).
- `routes/territories.py` — create/list/get; assign with half-open overlap check (adjacency allowed); retire (OPEN only); contacts with capacity-then-window ordering, per-territory address uniqueness, `include_archived`.
- `routes/branches.py` — propose/list/get; OCC-guarded PATCH (`expected_branch_version`, input-shape before stale-version check, tier recompute); approve-site (closed-interval lease overlap at same site, creates SIGNED lease); open (FULLY_STAFFED gate, auto-creates current-month OPEN period); suspend/reinstate/close (cascade: BOA RELEASED, lease TERMINATED, territory released); scoped list endpoints; assign-administrator (single-ACTIVE invariant).
- `routes/administrators.py` — hire/list/get, place-on-leave, return-from-leave, release (each recomputes branch staffing).
- `routes/training.py` — list/get/evaluations, submit-milestone (Advisor, own program, ACTIVE/REMEDIATION), evaluate (closed window [start_date, window_end], per-record-rounded sum, inclusive PASS boundary, `force_outcome` with `ERR_GOAL_NOT_MET`, second-FAIL → program FAILED + advisor TERMINATED).
- `routes/production.py` — post (per-record `round_half_up(gross × payout_rate)`), reverse, list; both recompute advisor cumulative.
- `routes/financials.py` — period create (half-open non-overlap), charge post (rejected on FINALIZED), charge reverse (bumps period version), close (clock ≥ period_end gate, provisional snapshot, deficit_carryforward), reopen (latest-only), finalize (final share, DEFICIT_CARRYOVER charge onto next OPEN period, tier recompute).
- `routes/goodwill.py` — create (trailing-12-complete-months revenue, 0.75/1.10 multiples), OCC-guarded counter-offer with strict alternation, accept (escrow ≥ round_half_up(10% of offer)), decline (escrow refunded), complete (four-record cascade), cancel; `expire_transfers()` sweep.
- `routes/compliance.py` — product shelf propose/approve/retire (unique code among APPROVED), solicitation submit/approve/deny/withdraw (segregation-of-duties check before cross-entity gates, `decided_by_role` recorded).
- `routes/clock.py` — `POST /branch-office/_clock/set_current_utc`, sets logical clock and expires offers past created_at + 30 days (inclusive boundary).

## Boot smoke test

Started via `bash start.sh` on self-allocated free port 32839 (PID 4106208), exercised: unauthenticated 401, advisor create 201 + `ERR_DUPLICATE`, envelope + pagination shape, territory/branch/approve-site (v1→v2), enroll-training, production post with per-record rounding (100001 × 0.5 → 50001), milestone submit/evaluate (FAIL → REMEDIATION), OCC `ERR_STALE_VERSION` 412 on stale PATCH and stale counter-offer, tier recompute (hh=50 → score 500 → TIER_2), branch open (FULLY_STAFFED, auto-created first period), charge posting aggregates, retirement declaration, goodwill valuation (trailing 1000 × 0.75 = 750), negotiation round/alternation (`ERR_NEGOTIATION_TURN`), clock set with expiry sweep. All responses matched the scaffold envelope and error catalog. Then killed exactly PID 4106208, verified a second fresh boot (PID 4139941) starts with `total_count: 0` and serves 401 correctly, and killed that PID too. No other processes touched.


## Step 7: Test Iterate + Fix — 2026-09-30 (diagnostic loop)

8-round parallel sweeps via `prd-bench-local-run --isolation per-test-server`, iterating until all 8 rounds passed 73/73.

**Round A (collection):** 4 files failed to import `setup_open_branch` — the fixture is named `create_open_branch`. Renamed the import symbol in `test_suite/test_05_validation_priority_pairs.py`, `test_11_state_machine_rules.py`, `test_12_calculation_details.py`, `test_17_occ_transfer_and_tier_trigger.py` (same signature/return; test_12's import was unused).

**Round B (13 failures, deterministic across all 8 rounds):**
- 12 failures shared one fixture bug: `setup_open_branch_with_period` in `test_helpers/fixtures.py` created an explicit `[2026-09-01, 2026-10-01)` period, which collides with the first OPEN period that branch-open auto-creates for the current calendar month (PRD §3.3: open "as a side effect, creates the branch's first `OPEN` financial period covering the current calendar month"; §3.5: periods "must never overlap"; clock defaults to 2026-09-01). The PRD-faithful implementation correctly rejected the overlapping creation. Fixture now fetches the auto-created September period via `list_branch_financial_periods` (timestamps normalized against the server's `.000Z` format) and only creates a new period for genuinely non-overlapping windows. Same root cause fixed inline in `test_11_state_machine_rules.py::test_finalize_creates_deficit_carryover_charge` (p1 now fetched, p2 October created) and `test_17_occ_transfer_and_tier_trigger.py::test_tier_threshold_trigger_on_finalize`. Also fixed a latent 4-tuple unpack of the 5-tuple fixture in `test_04_cascades.py::test_advisor_termination_keeps_administrator_employed`.
- 1 failure (`test_decline_out_of_turn_rejected_and_escrow_untouched`) was an implementation bug: `implementation/routes/goodwill.py` treated the initial OFFERED offer as made by no one (`_last_offer_by: None`), so the retiring advisor could decline their own offer. PRD §3.7: "Acceptance and decline likewise belong to the party who did not make the most recent offer — accepting one's own offer or declining it out of turn is also `ERR_NEGOTIATION_TURN`." Fix: creation records the retiring advisor as the most recent offerer; the turn check now applies uniformly to counter-offer (the `status == "NEGOTIATING"` exemption was removed). All other negotiation tests (successor accept/decline/counter from OFFERED) remain valid under this reading.

**Round C (1 failure):** `test_provisional_snapshot_unchanged_by_post_close_corrections` — `reverse_charge` in `implementation/routes/financials.py` recomputed period aggregates while the period was CLOSED, overwriting the provisional snapshot taken at close. PRD §3.5 says close "recomputes all four aggregates as a provisional snapshot" and §3.6 says "The provisional variant applies while the period is `OPEN` or `CLOSED` and snapshots the charges currently posted; the final variant applies at finalization and includes late re-posted corrections" — the post-close correction must leave the recorded provisional share untouched and surface only at finalize. Fix: aggregate recompute on reversal only while the period is OPEN; the version bump (PRD: "Reversing a charge also increments the parent period's `version`") still applies for OPEN and CLOSED periods.

**Final sweep:** all 8 rounds, 73/73 passed, 0 failed, 0 errors.

**Deletions:** none — every failing test traced to a verbatim PRD rule; all fixes made the test artifacts more PRD-faithful or corrected genuine implementation bugs.
## Step 7: Run Tests and Iterate — 2026-09-29T20:07:55.640749694Z

## Summary

**Iterations run:** 4 sweeps (1 collection-only + 3 full 8-round parallel sweeps). Final sweep: all 8 rounds passed 73/73, 0 failed, 0 errors.

**Tests deleted:** none — every failing test traced to a verbatim PRD rule; no PRD-silence or unique-derivability violations found.

**Fixes applied to `test_helpers/`:**
- `fixtures.py::setup_open_branch_with_period` — the fixture created an explicit `[2026-09-01, 2026-10-01)` period that collided with the first OPEN period auto-created by branch open (PRD §3.3 side effect + §3.5 non-overlap, clock default 2026-09-01). Now fetches the auto-created period via `list_branch_financial_periods` (with `_norm_instant` to match the server's `.000Z` timestamp format) and only creates a new period for genuinely non-overlapping windows. This one fixture bug was masquerading as 12 independent "implementation" failures.

**Fixes applied to `test_suite/`:**
- `test_05`, `test_11`, `test_12`, `test_17` — import of nonexistent `setup_open_branch` renamed to the actual fixture `create_open_branch` (identical signature/return).
- `test_04_cascades.py::test_advisor_termination_keeps_administrator_employed` — fixed 4-tuple unpack of the 5-tuple fixture (latent bug, would have failed next).
- `test_11::test_finalize_creates_deficit_carryover_charge` and `test_17::test_tier_threshold_trigger_on_finalize` — replaced duplicate-September `create_period` calls (same auto-period collision) with a fetch of the auto-created period.

**Fixes applied to `implementation/`:**
- `routes/goodwill.py` — negotiation-turn bug: a fresh OFFERED transfer recorded `_last_offer_by: None`, letting the retiring advisor decline their own opening offer. PRD §3.7 ("Acceptance and decline likewise belong to the party who did not make the most recent offer…") pins the initial offer as the retiring advisor's. Creation now records the retiring advisor as the most recent offerer, and the turn check applies uniformly to counter-offer (removed the `status == "NEGOTIATING"` exemption).
- `routes/financials.py::reverse_charge` — recomputed period aggregates while the period was CLOSED, overwriting the provisional snapshot that PRD §3.5/§3.6 freeze at close ("the final variant applies at finalization and includes late re-posted corrections" — the correction must surface only at finalize). Aggregate recompute on reversal now happens only while OPEN; the PRD-required parent-period version bump still applies for OPEN and CLOSED.

## Step 8: Finalize PRD — 2026-09-29T20:12:09.336722221Z

The diff is clean and minimal — 3 sentences touched across 2 PRD sections, same line count (286 lines, 0% delta).

## Summary

**Line counts:** PRD.md = 286 lines, PRD_FINALIZED.md = 286 lines (0% delta; edits are in-place sentence revisions within existing paragraphs, no new sections).

**Changes (one bullet each):**

- §3.5 — revise — split "Every charge post or reversal recomputes the period's aggregates while the period is `OPEN` or `CLOSED`" into: posting recomputes while `OPEN` or `CLOSED`, but reversal recomputes only while `OPEN` (the close-time provisional snapshot stays frozen through a post-close reversal; corrections surface via the final variant at finalization); also scoped the parent-period version bump on reversal to `OPEN` or `CLOSED` periods — `implementation/routes/financials.py:120-129` (`reverse_charge`).
- §3.7 — revise — creation sentence now pins that the initial offer is treated as made by the retiring advisor for turn-alternation, so the first negotiation act (counter-offer, acceptance, or decline) must come from the successor — `implementation/routes/goodwill.py:79` (`_last_offer_by: retiring["id"]`).
- §3.7 — revise — replaced "Within an ongoing negotiation the same party may not speak twice in a row" with wording stating the turn check applies uniformly in both `OFFERED` and `NEGOTIATING` status, counting the initial offer as the retiring advisor's — `implementation/routes/goodwill.py:118-121,132,159,177` (`_check_turn` called by counter-offer, accept, decline with no status exemption).

**Per-edit pre-edit search log:**

1. **§3.5 reversal/recompute edit.**
   - (a) Subject: period aggregate recompute and parent-period version bump on charge reversal.
   - (b) Paths enumerated: `grep -rn "recompute_period\|reverse"` across `implementation/` — `routes/financials.py:94` (`post_charge` recomputes for any non-FINALIZED period; FINALIZED rejected at line 83), `routes/financials.py:110-130` (`reverse_charge`: recompute only if OPEN; `touch(period)` only if OPEN or CLOSED; FINALIZED-period charge reversal allowed with no period effects), `routes/financials.py:143,180,201` (close/finalize/carryover recompute — unaffected), `routes/production.py:47-59` (production reversal never touches period aggregates), `helpers.py:211-219` (`recompute_period`), and a grep over `routes/advisors.py, branches.py, administrators.py, compliance.py, training.py, territories.py, clock.py` confirming no other charge-reversal or charge-mutation side effects.
   - (c) Wording adjustment: kept "posting recomputes while OPEN or CLOSED" (matches `post_charge`), narrowed reversal recompute to OPEN-only, scoped the version-bump sentence with "while the period is `OPEN` or `CLOSED`" so the FINALIZED-period charge-reversal path (allowed by impl, no bump) is not mis-described; deliberately left FINALIZED-period charge reversibility itself unpinned (Step 7 never exercised it; under-determined is safer).

2. **§3.7 initial-offer attribution edit (creation sentence).**
   - (a) Subject: who counts as maker of the initial offer for turn alternation.
   - (b) Paths enumerated: `grep -rn "_last_offer_by\|NEGOTIATION_TURN\|_check_turn"` — confined to `routes/goodwill.py`: line 79 (creation sets `_last_offer_by = retiring["id"]`), lines 118-121 (`_check_turn`), line 132 (counter-offer), line 146 (counter-offer updates `_last_offer_by` to actor), lines 159 and 177 (accept/decline). No other route reads or writes negotiation-turn state. Cross-checked `test_suite/test_15_auth_and_negotiation_errors.py:35` (successor makes the first counter-offer on a fresh OFFERED transfer — consistent).
   - (c) Wording adjustment: phrased as "treated as made by the retiring advisor for turn-alternation purposes" and "the first negotiation act (counter-offer, acceptance, or decline) must come from the successor" — covers all three endpoints without inventing any stored-field contract.

3. **§3.7 turn-check scope edit ("ongoing negotiation" sentence).**
   - (a) Subject: statuses in which the alternation check applies.
   - (b) Paths enumerated: same grep as edit 2 — `_check_turn` is invoked in counter-offer, accept, and decline with no `status == "NEGOTIATING"` gate; each endpoint first requires status in `{OFFERED, NEGOTIATING}` (lines 130-131, 157-158, 175-176), so the check fires in both statuses. Verified the neighboring sentences ("Acceptance and decline likewise belong to the party who did not make the most recent offer") remain consistent with retiring-advisor-attributed initial offer — no further change needed there.
   - (c) Wording adjustment: dropped the "Within an ongoing negotiation" qualifier (which could be misread as NEGOTIATING-only) and added "the turn check applies in both `OFFERED` and `NEGOTIATING` status, counting the initial offer as the retiring advisor's", matching the impl exactly.

All other Step 7 items were pure test/fixture bugs (fixture name imports, tuple unpack, duplicate-period fixture creation, timestamp normalization in test helpers) with no PRD-relevant behavior, so no PRD edits were made for them.

## Step 9: Complete PRD — 2026-09-29T20:28:44.534419365Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_3055_single_advisor_branch_office_model_branch_administrator/workspace/PRD_COMPLETED.md`.

**Counts**
- Source: `PRD_FINALIZED.md` — 286 lines, 48,234 chars. `PRD_COMPLETED.md` — 288 lines, 54,183 chars. Char delta: **+5,949**.
- Ambiguity-pins: **24**; mismatch-revisions: **0** (implementation was already closely aligned; every change pins impl behavior where PRD prose admitted multiple readings).

**Changes (one bullet per edit)**

- §2.3 — insert — ambiguity — pin unknown-path/wrong-method rejection as `ERR_NOT_FOUND` (404) and list tiebreak sort by `id` — `implementation/app.py:39-45`, `implementation/helpers.py:123`.
- §2.4 — insert — ambiguity — every mutation (including cascade side effects) increments `version` by 1 and refreshes `updated_at` — `implementation/helpers.py:95-98`.
- §2.4 — insert — ambiguity — `expected_branch_version` is mandatory on branch PATCH (missing or non-integer → `ERR_INVALID_REQUEST`, 400), and attribute input-shape validation runs before the version check — `implementation/routes/branches.py:87-100`.
- §2.7 — insert — ambiguity — clock may be set backward; all server timestamps read the logical clock; every clock-set sweeps expirations; clock endpoint returns an empty data object — `implementation/routes/clock.py:20-23`, `implementation/db.py:27-28`.
- §2.8 — insert — ambiguity — the carried-forward `DEFICIT_CARRYOVER` lands on the open period with the earliest `period_start` — `implementation/routes/financials.py:187-191`.
- §2.9 — insert — ambiguity — `staffing_status` is recomputed from current advisor/administrator presence on every staffing-relevant event — `implementation/helpers.py:143-154`.
- §3.1 — insert — ambiguity — advisor email uniqueness compared as exact strings; `hire_date` is an ISO 8601 datetime — `implementation/routes/advisors.py:28-31`.
- §3.1 — insert — ambiguity — non-terminal training program statuses are `ACTIVE`/`MILESTONE_PENDING`/`REMEDIATION`; enrollment returns the created `TrainingProgram` (201) — `implementation/routes/training.py`/`implementation/routes/advisors.py:120-132`.
- §3.1 — insert — ambiguity — `force_outcome` validated as `PASS`/`FAIL` (else `ERR_INVALID_REQUEST`); forced `FAIL` always accepted; evaluate returns the created `MilestoneEvaluation` (201) — `implementation/routes/training.py:70-89,117`.
- §3.2 — insert — ambiguity — explicit assign is defined from `OPEN` or `ASSIGNED` (`RETIRED` → `ERR_INVALID_STATE`) and replaces the current assignment; explicit `assignment_end` must be strictly after start; open-ended-interval overlap rule pinned — `implementation/routes/territories.py:76-97`.
- §3.2 — insert — ambiguity — a territory with no current assignment rejects all contacts with `ERR_CONTACT_OUTSIDE_WINDOW`; no assigned-advisor ownership check on contact logging — `implementation/routes/territories.py:133-139`.
- §3.3 — insert — ambiguity — branch creation computes `tier_score`/`service_tier` immediately (starts 0 / `TIER_1`) — `implementation/routes/branches.py:48`.
- §3.3 — insert — ambiguity — `monthly_rent_cents` must be a positive integer; lease-overlap compares exact `site_address` strings of *other* branches; approve-site returns the branch — `implementation/routes/branches.py:115-117,132-155`.
- §3.3 — insert — ambiguity — assign-branch: territory `ASSIGNED` to another advisor → `ERR_TERRITORY_OVERLAP`, `RETIRED` → `ERR_INVALID_STATE`; assignment clears `assignment_end`; response is the advisor — `implementation/routes/advisors.py:154-171`.
- §3.3 — insert — ambiguity — assign-administrator has no branch operating-state precondition; response is the administrator — `implementation/routes/branches.py:303-321`.
- §3.3 — insert — ambiguity — the first period on open covers the logical clock's current calendar month (half-open, first instant to first instant), aggregates zeroed; close may release a practicing/retiring advisor's assignment and always releases the administrator — `implementation/routes/branches.py:20-27,169-182,228-243`.
- §3.4 — insert — ambiguity — only `POSTED` records can be reversed; `hire_date` boundary in cumulative sum is inclusive; posting requires no particular advisor status — `implementation/routes/production.py:52-53`, `implementation/helpers.py:222-234`.
- §3.5 — insert — ambiguity — period creation allows adjacency, requires `period_end` strictly after start, requires no branch state — `implementation/routes/financials.py:44-46`.
- §3.5 — insert — ambiguity — posted charge's `branch_id` must own the period in the path (else `ERR_NOT_FOUND`) — `implementation/routes/financials.py:77-78`.
- §3.5 — insert — ambiguity — charge reversal touches the charge, requires `POSTED` status, and on a `FINALIZED` period leaves aggregates untouched — `implementation/routes/financials.py:115-129`.
- §3.5 — insert — ambiguity — "latest period" for reopen is max by (`period_start`, then `period_end`); reopen keeps the close-snapshot aggregates until next recompute — `implementation/routes/financials.py:159-169`.
- §3.5 — insert — ambiguity — finalization with non-negative net does not touch `deficit_carryforward_cents` (close value retained); carryover target's aggregates recomputed immediately — `implementation/routes/financials.py:184-202`.
- §3.6 — insert — ambiguity — tier AUM floor-division truncates toward zero; tier also recomputed at branch creation — `implementation/helpers.py:159`, `implementation/routes/branches.py:48`.
- §3.7 — insert — ambiguity — transfer creation performs no preconditions on branch state or party statuses (existence only); gates apply at completion — `implementation/routes/goodwill.py:50-66`.
- §3.7 — insert — ambiguity — negotiation endpoints reject non-party advisors with `ERR_UNAUTHORIZED`; `expected_transfer_version` mandatory on every counter-offer — `implementation/routes/goodwill.py:113-115,134`.
- §3.7 — insert — ambiguity — completion moves a `VALIDATED` successor to `PRACTICING` and performs no territory reassignment (territory keeps its current assignment) — `implementation/routes/goodwill.py:203-207`.
- §3.8 — insert — ambiguity — `ERR_DUPLICATE` on product code fires both at entry proposal and at approve — `implementation/routes/compliance.py:37-38,69-70`.
- §3.8 — insert — ambiguity — solicitation submission rejects a session whose `X-User-ID` ≠ body `advisor_id` with `ERR_UNAUTHORIZED`; advisor status/branch not checked at submission — `implementation/routes/compliance.py:93-94`.
- §3.8 — insert — ambiguity — SoD check = principal's `X-User-ID` equals requester's advisor id; `PLAIN` products have no SoD restriction; `decided_by_role` records the role string — `implementation/routes/compliance.py:137-151`.

No edits touched the endpoint table (§4) or error catalogue (§5) — both already matched the implementation exactly (all 49 routes, same roles, same filters; error IDs and HTTP statuses identical to `errors.py`).
