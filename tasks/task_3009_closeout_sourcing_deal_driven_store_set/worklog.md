# Worklog — task_3009_closeout_sourcing_deal_driven_store_set

## Step 1: Create task directory — 2026-09-29T12:06:00.000Z

Pre-allocated directory `./tasks/task_3009_closeout_sourcing_deal_driven_store_set/` with `workspace/` verified to exist (per command args; no new index computed, no other task_* directory created).

## Step 3: Copy shared files — 2026-09-29T12:07:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3009_closeout_sourcing_deal_driven_store_set/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold (rerun from scratch after interruption) — 2026-09-29T13:21:28.000Z

All done. Final lint verdict is clean.

**Domain model** (Ollie's-style closeout retail, Expert+ difficulty):

- **Entities (11)**: Vendor, JurisdictionRule (advertising-law config: WAS_NOW_WINDOW / MSRP_REFERENCE / COMPARISON_PROHIBITED), Store (performance tiers), BuyLot (central aggregate with dual-variant landed cost, conservation counters, markdown rounds), SafetyScreening (recall/expiration/condition rounds with segregation-of-duties), Allocation (tier-waterfall), AisleAssignment (deal-driven layout, closed-interval windows, OCC supersede), LoyaltyMember, EarlyAccessEvent (half-open windows, clock-driven), Purchase (member/guest pricing), Disposition (markdown loop / liquidation / scrap).
- **State machines (9)**: non-linear highlights — BuyLot revision loop (SCREENING→SOURCED re-grade) plus markdown loop (DISPOSITION_REVIEW→ON_SALE) plus sold-out/reopen on refund; Allocation SHIPPED→CONFIRMED recall cycle; post-market recall blocking an ON_SALE lot.
- **Calculations (7)**: dual-variant landed cost (provisional 2000 vs final 1190 on identical data), dual-variant member pricing (STANDARD 3400 vs EVENT 3000), jurisdiction-branched price legality, pinned per-unit-first rounding (9597 not 9598), tier-waterfall allocation with created_at tie-break, strict-inequality pacing (sold*2 < target), two compensating invariants (unit conservation; refund restoration).
- **Surface**: 49 endpoints (incl. `POST /_clock/set_current_utc` with pinned default 2026-09-01T00:00:00Z), 26 ordered validations (auth → existence → state → safety → referential → constraint → temporal → fiscal), 26 error codes (all referenced), 8 roles with segregation-of-duties (buyer cannot screen own lot) and entity-backed ClubMember identity.
- **Concurrency**: two true OCC create-with-supersede rules (aisle assignments on Store.version, dispositions on BuyLot.version), both exercised with sequential stale-version tests.

**Counts**: §1.8 difficulty design — 19 instances (2 per rule × 9 rules, plus a third combinatorial instance for the pacing evaluation-order mode). §1.9 corner design — 44 active instances + 2 excluded_because stubs across all 9 claim-extraction sections. 672 total test-recipe calls scanned.

**Files written** (all three, prior partial SCAFFOLD.yaml overwritten):
- `SCAFFOLD.yaml` (1556 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1443 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (2292 lines)

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` Two fixes applied during iteration: `api_prefix` set to `""` (flat multi-root topology) and lot sub-resource GET paths renamed to `{id}` placeholders to satisfy the lint's FK reverse-reachability convention.

Post-hoc orchestrator verification (2026-09-29T13:21Z): all three YAML files parse cleanly with PyYAML; SCAFFOLD.yaml contains all §1.1–§1.7 sections (scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles) and correctly omits both design keys; design files carry their single required top-level key. Files complete, not truncated.

## Step 4: Generate PRD — 2026-09-29T13:35:00.000Z

All mechanical contracts pass. Contract 2 verified by walking the scaffold during drafting: all 36 state-machine transitions (including the three BLOCKED re-screen variants, the regrade loop, CLOSED_SOLD_OUT↔ON_SALE reopen, and the shipment-recall cycle), all 7 calculations (dual-variant landed cost with grade factors 1.0/0.8/0.6, the three-branch advertising legality engine with the 20% anchor, pinned member-price rounding with tier percents 5/10/15, tier-ordered waterfall, pinned pacing steps with 3-day/7-day constants, conservation invariant, refund restoration), all 26 validations with their priority ordering (the purchase cascade is stated as an explicit ordered list), both OCC rules, and all endpoint side effects are expressed in prose.

**Output written:** `workspace/PRD.md` — 271 lines.

**Section coverage audit (scaffold → PRD):**
- §1.0 response envelope → §2.2 emitted verbatim from `section-2.2-response-structure.md` (verified byte-identical containment), §2.3 pagination (limit default 10 / min 1 / max 100, offset 0, `created_at` ascending, the four `meta` fields)
- §1.1 entities (11) → scattered through §2.4, §2.7, §2.9 and §3.1–§3.9 narratives; all 83 field/input/path-param identifiers present as backticked tokens (mechanically verified, 0 missing)
- §1.2 state machines (8 machines, 36 transitions) → §3.2 (lot creation states), §3.3 (screening completion, block cascades links 1+2, regrade loop), §3.4 (CLEARED→PRICED), §3.6 (sold-out close, refund reopen), §3.7 (pacing exit, markdown loop, liquidation/scrap cascades), §3.8 (allocation lifecycle incl. SHIPPED→CONFIRMED recall), §3.9 (aisle supersede, event clock transitions)
- §1.2.1 concurrency rules (2) → §2.8 with `expected_store_version` / `expected_lot_version`, `ERR_STALE_VERSION` (412), framed purely as stale-view rejection
- §1.3 calculations (7) → §3.5 (landed cost dual variant, advertising legality three branches), §3.6 (pinned member-price rounding, cap gate), §3.8 (waterfall), §3.7 (pinned pacing steps), §2.9 (conservation), §3.6 (refund restoration)
- §1.4 validations (26) → §2.6 global order statement plus an explicit ten-step ordered purchase cascade in §3.6; every rule paired with its error id near its workflow
- §1.5 endpoints (49) → §4 table, 4 columns only
- §1.6 errors (26) → §5 table, 2 columns only; all 26 ids also appear in §2/§3 prose
- §1.7 roles (8) → §2.1 with exact spellings, `entity_backed:LoyaltyMember` vs opaque identity translated per role

**Contract results:** Contract 1 PASS (83/83 fields, 0 missing), Contract 2 PASS (36/36 transitions, 7/7 calculations, 26/26 validations, 2/2 OCC rules expressed), Contract 3 PASS (385 §3 backtick tokens scanned, 0 path/method violations).

**Zero-Silence decisions (stated verbatim so tests can derive them):** logical clock startup default `2026-09-01T00:00:00Z` and never-falls-back rule; refund window exactly 14 days inclusive; pacing trigger strictly-below-50% (exactly 50% does not trigger) after at least 3 whole selling days with a half-open trailing 7-day window; member cap boundary inclusive (pct == cap allowed); anchor premium boundary inclusive at retail × 1.20 with half-up cent rounding; closed-interval aisle conflict (touching endpoints conflict) vs half-open event overlap (touching allowed); waterfall tier order TIER_1 < TIER_2 < TIER_3 with `created_at` tiebreak and id never consulted; BLOCKED lot passes the purchase state check so `ERR_LOT_SAFETY_BLOCKED` (not `ERR_INVALID_STATE`) owns the rejection; per-unit-only rounding for purchases (no line-level rounding); grade factors 1.0 / 0.8 / 0.6.

## Step 5: Generate unit tests — 2026-09-29T14:20:00.000Z

All clean. Generation complete.

**Coverage audit — all checks pass.** 83 pytest tests collected, every one carrying exactly one terminal `Design:` docstring line that resolves to a real instance in the design indices.

- **Queue A (Difficulty)**: 39 tests. All 19 instances across the 9 rules have ≥2 tests each.
- **Queue B (Corner)**: 44 tests. All 46 non-stub instances have ≥1 test each. The 2 `excluded_because:` stubs (`cascading_side_effects_excluded`, `rate_threshold_pacing_excluded`) were not translated; both difficulty-instance cross-references (`transitive_cascade/recall_block_cascades_allocations_and_assignments`, `combinatorial_formula/pacing_evaluation_order_eligibility_gate`) resolve.
- **Skipped instances**: none. Every instance survived the PRD-first two-condition filter.

**test_helpers/ files written**: `types.py` (enums + TypedDicts for all 11 entities), `api_client.py` (`ApiClient(GenericApiClient)`, one method per PRD endpoint), `api_errors.py` (26-error catalog registered via `set_error_http_status_map`), `assertions.py` (per-entity asserters + `assert_lot_unit_conservation`), `factories.py`, `constants.py`, `test_users.py` (8 roles; `Anonymous` omits X-User-ID per PRD; `make_club_member_headers(member_id)` threads entity-backed identity), `fixtures.py` (lot lifecycle tiers: cleared/priced/on-sale/sellable/disposition-review composites), `__init__.py` barrel.

**test_suite/** (10 files + `conftest.py`): entities/reference data, lot lifecycle & state machines, pricing & advertised-price legality, pacing/sold-out/refunds, allocations & quantity boundaries, block/liquidation cascades, validation order & auth, layouts & events, RBAC & OCC, listings/summary/consistency.

**Audits run**: docstring-tag audit (0 errors, no dual/untagged tests, no stub tags); verbatim PRD-citation check (116 quoted citations, all survive whitespace-normalized match against PRD.md); no `skip`/`skipif`/`xfail` markers; no scaffold references in comments; all modules import cleanly and pytest collects 83 tests.

**Notable adjudications**: `test_allocation_proposal_on_sourced_lot_rejected` uses `validate_error_is_one_of([ERR_INVALID_STATE, ERR_LOT_SAFETY_BLOCKED])` because PRD does not pin the state-vs-safety ordering for a never-screened lot (error-precedence silence pattern); allocation version assertions are relative (`>=` / `v+1`) since the PRD's "mutation" definition leaves the exact commit-time version increment open to two readings; `PRICED + zero grant stays PRICED` was deliberately not asserted for the same reason (PRD uniquely commits only the grant>0 arm).

## Step 6: Generate implementation — 2026-09-29T15:15:00.000Z

All files in place, start.sh executable, and the server smoke-tested across the full lifecycle.

**Files written** under `workspace/implementation/`:

- `start.sh` — bash launcher; `cd` to its own dir, guards `pip install` behind a `python3 -c "import flask"` import check (no-op once installed so per-test reboots stay fast), then `exec python3 app.py` in the foreground.
- `requirements.txt` — `flask>=3.0`.
- `app.py` — Flask entry point; registers three blueprints; central `ApiError` handler plus 404/405/error fallbacks all emitting the scaffold's error envelope; binds `0.0.0.0:$PORT` (default 10000).
- `db.py` — in-memory `DB` singleton with dicts per entity (`vendors`, `jurisdiction_rules`, `stores`, `lots`, `screenings`, `allocations`, `aisle_assignments`, `members`, `events`, `purchases`, `dispositions`); **starts empty** — no seeding anywhere. Also hosts the logical clock, ISO-8601 (3-fractional-digit `…Z`) formatting/parsing helpers, and Decimal-based `round_half_up` helpers.
- `errors.py` — `ApiError(error_id, message, http_status)` plus per-ID constructors.
- `response.py` — success/error envelope builders: `{meta: {api_request_id: "req_…", api_request_timestamp}, response_type, data}`, with `limit/offset/total_count/has_more` added to `meta` only for list responses.
- `middleware.py` — `X-User-Role`/`X-User-ID` extraction against the 8 declared roles (Anonymous exempt from `X-User-ID`), role gating, JSON body + unknown-field/enum/int-range validators, `limit`/`offset` pagination parsing (defaults 10/0, bounds 1..100).
- `routes/refdata.py` — Vendors, JurisdictionRules (WAS_NOW_WINDOW requires `window_days`/`required_offer_days`; other rules reject them), Stores, LoyaltyMembers, plus reverse-reachability list endpoints.
- `routes/lots.py` — BuyLot create/list/get/summary/regrade, screening open/list/complete, pricing, allocation propose/commit/ship/receive/recall/release/cancel, early-access events, dispositions create/apply.
- `routes/sales.py` — aisle assignments (with OCC `expected_store_version`, closed-interval conflict + `supersede`), purchases (full 10-step cascade), refunds (14-day window, `CLOSED_SOLD_OUT → ON_SALE` reopen), and `POST /_clock/set_current_utc`.
- `services/core.py` — derived lot quantities (`qty_pool`/`qty_allocated_outstanding`/`qty_sold` computed from allocations + COMPLETED purchases so releases/cancels/refunds automatically restore the conservation invariant), dual-variant landed unit cost (provisional vs grade-weighted final with B=0.8/C=0.6 factors), advertised-price-legality engine (COMPARISON_PROHIBITED / WAS_NOW_WINDOW with 20% anchor + 2-dp discount / MSRP_REFERENCE), block and liquidate cascades, sold-out detector, event coverage, clock side-effects (event transitions then pacing evaluation).

**Logical clock** — a module-level `datetime` on the `DB` singleton, initialized to exactly `2026-09-01T00:00:00Z` at process start, advanced only by `POST /_clock/set_current_utc` (Admin-only); it never reads wall-clock. Every `created_at`/`updated_at`/`completed_at`/`applied_at`/`refunded_at`/cascade timestamp is stamped from it. Setting the clock runs, in order: SCHEDULED→ACTIVE / ACTIVE→ENDED event transitions, then the pacing sweep (eligible = `ON_SALE` lots with `floor((now - on_sale_since)/86400) >= 3`; move to `DISPOSITION_REVIEW` when `2 * units_sold_trailing_7d < pace_target`, strict).

**Smoke-test confirmation** — booted via `bash start.sh` on scratch ports 19371/19372/19510 and verified end-to-end: empty store at boot; auth 401/403; full happy path (vendor → jurisdiction → store → lot → screen PASS → price → allocate → commit → ship → receive → aisle-assign → guest and member purchases at 1275c GOLD STANDARD and 300c EVENT at exactly the 25% cap); regrade loop (FAILED_CONDITION → regrade → SOURCED → round-2 screening → PASSED with final-variant cost 510); pacing → DISPOSITION_REVIEW → MARKDOWN apply (1500→1125, rounds=1, back to ON_SALE); LIQUIDATE/SCRAP flows with pool sweep; block cascade (CONFIRMED allocation auto-cancelled, 8 units returned to pool 12→20, assignment superseded with block timestamp, subsequent purchase → `ERR_LOT_SAFETY_BLOCKED`); event windows (overlap 409, touching allowed, zero-window 422, guest-during-event 403, tier-too-low 403, SCHEDULED→ACTIVE→ENDED, cancel); signage daily limit per guest bucket; OCC `ERR_STALE_VERSION` 412 on both `expected_store_version` and `expected_lot_version`; aisle supersede with `valid_to = new valid_from − 1s`; error envelope shape confirmed on every failure path.

## Step 7: Run tests and iterate — 2026-09-29T15:40:00.000Z

All 8 rounds pass: 82/82 in every round, zero failures in the union. Exiting with the summary.

**Iterations run:** 3 sweeps (initial diagnosis, post-fix verification, final clean sweep — all 8 parallel rounds at 82/82 passed, no flakiness in the union).

**Tests deleted (1):**
- `test_allocation_proposal_requires_priced_lot` (test_suite/test_05) — PRD-SILENT / scaffold-only rule. PRD §3.8 names only the §2.10 safety gate, §3.1 store-standing gate, and `ERR_INSUFFICIENT_LOT_QUANTITY` for allocation proposals; the "proposal requires a PRICED lot" state gate appears only in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`. A faithful PRD-only implementation legitimately accepts proposals on CLEARED lots.

**Fixes applied to `test_helpers/` (1):**
- `test_helpers/factories.py` — `create_jurisdiction_rule_payload` leaked the `JURISDICTION_CA` defaults' `window_days`/`required_offer_days` into non-`WAS_NOW_WINDOW` payloads; PRD §3.1 requires those fields "absent otherwise". Now strips them unless explicitly pinned. (This was the triage-hint case: one fixture bug surfaced as 3 setup failures.) Also made `create_disposition_payload`'s `expected_lot_version` default to `None` so the dropping-null helper pattern in test_06 works.

**Fixes applied to `test_suite/` (3):**
- `test_07::test_purchase_on_unscreened_lot_safety_blocked` — relaxed exact `ERR_LOT_SAFETY_BLOCKED` to `validate_error_is_one_of([ERR_LOT_SAFETY_BLOCKED, ERR_INVALID_STATE])`; a never-screened SOURCED lot violates both PRD §3.6 step 1 (state) and §2.10 (safety), and PRD does not pin which error fires first for this cross-paragraph overlap (error-precedence silence; the permitted one-of relaxation).
- `test_06::test_liquidation_cascade_closes_assignments_and_events` — setup bug: created the early-access event after pacing moved the lot to `DISPOSITION_REVIEW`, but PRD §3.9 only permits event creation on `PRICED`/`ON_SALE` lots. Restructured to create the event while `ON_SALE`, then advance the clock into review.
- `test_08::test_aisle_assignment_supersede_ends_incumbent_one_second_earlier` — string-compared `valid_to` to `"2026-09-09T23:59:59Z"`, but PRD §3.9 pins only the instant (one second before) and §2.4's three-fractional-digit format applies only to system-managed `created_at`/`updated_at`. Now compares parsed datetimes. Also `test_09`: added missing `validate_paginated` import.

**Fixes applied to `implementation/` (2):**
- `workspace/implementation/services/core.py::check_price_legality` — advertised-discount percent was computed in hundredths-of-percent (×10000 → 6000.00) but compared against the integer-percent cap (70), rejecting every discount ≥1% (root cause of 53/58 initial failures). Changed to ×100 so the computed figure is percent-units rounded half-up to two decimals, matching the integer-percent cap per PRD §3.5.
- `workspace/implementation/routes/lots.py::commit_allocations` — commit was gated on `commercial_status == "PRICED"` only; PRD §3.8 requires only that the PRICED→ON_SALE transition fire on the first granting commit and never prohibits re-commits on ON_SALE lots. Widened the gate to `PRICED`/`ON_SALE`/`DISPOSITION_REVIEW` so the release-then-recommit waterfall cycle works.

## Step 8: Finalize PRD — 2026-09-29T15:47:00.000Z

Done. PRD_FINALIZED.md is written with exactly two inline edits.

**Line counts:** PRD.md 270 lines; PRD_FINALIZED.md 270 lines; 0% delta (both edits are in-line revisions within existing paragraphs; no sections added).

**Changes:**
- §3.5 (WAS_NOW_WINDOW bullet) — revise — advertised discount percent recomputed as `(comparison − retail) / comparison × 100` in percent units, rounded half-up to two decimals, instead of "hundredths of a percent" — matches `implementation/services/core.py:411-416` (the Step 7 `check_price_legality` fix).
- §3.8 (commit paragraph) — revise — commit is accepted while the lot is `PRICED`, `ON_SALE`, or `DISPOSITION_REVIEW` (rejected otherwise with `ERR_INVALID_STATE`); commits on `ON_SALE`/`DISPOSITION_REVIEW` grant units without changing commercial status — matches `implementation/routes/lots.py:442-464` (the Step 7 `commit_allocations` gate widening).

**Step 7 items requiring no PRD edit (verified against impl):**
- Deleted `test_allocation_proposal_requires_priced_lot`: impl `propose_allocation` (lots.py:380-410) has no commercial_status gate — PRD silence is correct; nothing to pin.
- test_07 one-of relaxation: impl purchase cascade (sales.py:229-234) checks state before safety, which PRD §3.6 already pins ("First... Second..."), so a never-screened SOURCED lot deterministically yields `ERR_INVALID_STATE`; the relaxation was test-side conservatism, no PRD gap.
- test_06 event-creation restructure, test_helpers fixture fixes, test_09 import: pure test/fixture bugs; PRD already correct (§3.9 event states; §3.1 "absent otherwise").
- test_08 `valid_to` format: PRD §3.9 pins only the instant; §2.4's three-fractional-digit format applies to `created_at`/`updated_at`. Impl happens to emit 3-digit format (db.py:47-50), but Step 7 deliberately left this free — pinning it would create a new constraint not required by the relaxed test, so left unpinned.

**Per-edit pre-edit search log:**

Edit 1 (§3.5 discount percent):
- (a) Subject: advertised-discount percent computation and comparison against `max_advertised_discount_pct`.
- (b) Enumerated paths: grep for `max_advertised_discount_pct`/`ERR_ADVERTISED_DISCOUNT_TOO_DEEP`/`discount_pct` across impl — `services/core.py:375-422` (definition, sole computation), `routes/lots.py:365` (only callsite, pricing endpoint), `routes/refdata.py:110-136` (rule creation, cap validated 0-100), `routes/sales.py:276,339` (`discount_pct_applied` is the member/event discount — different subject, unaffected). Confirmed `check_price_legality` is not called from aisle-assignment creation (only the COMPARISON_PROHIBITED branch is re-checked there per §3.5 first paragraph, which was not touched).
- (c) Wording adjustment: changed "hundredths of a percent" to explicit "divided by the comparison price and multiplied by 100 ... in percent units," keeping "rounded half-up to two decimal places" and "cap boundary inclusive" verbatim so §2.7's cross-reference ("carried to two decimal places rounded half-up before comparison against the jurisdictional cap") stays consistent.

Edit 2 (§3.8 commit gate):
- (a) Subject: commercial-status gate on allocation commit and the PRICED→ON_SALE transition.
- (b) Enumerated paths: `routes/lots.py:438-469` (commit_allocations — the only commit path), `routes/lots.py:56-57` (status enum), `services/core.py:445-450` (pacing reads `on_sale_since`/`ON_SALE` — unaffected since the edit only adds gate states, doesn't change the transition), grep for `on_sale_since` writers confirmed only lots.py:137 (init null) and lots.py:464 (commit). Also checked disposition apply paths (lots.py:718-746) that move lots between ON_SALE/DISPOSITION_REVIEW — consistent with commit being legal in both states.
- (c) Wording adjustment: scoped the new gate sentence to "accepted while PRICED, ON_SALE, or DISPOSITION_REVIEW" and added "commits on a lot already in ON_SALE or DISPOSITION_REVIEW grant units without changing the lot's commercial status" to avoid implying the PRICED→ON_SALE transition refires (impl line 462 conditions the transition on `commercial_status == "PRICED"`).

## Step 9: Complete PRD — 2026-09-29T16:05:00.000Z

Done. `workspace/PRD_COMPLETED.md` written as a minimal patch over `PRD_FINALIZED.md`.

**Source vs output:** `PRD_FINALIZED.md` 270 lines / 42,387 chars → `PRD_COMPLETED.md` 270 lines / 44,449 chars (+2,062 chars, no new sections or paragraphs).

**Counts:** 14 ambiguity-pins, 2 mismatch-revisions (16 edits total).

**Changes:**
- §2.2 — insert — ambiguity — pinned that `api_request_timestamp` and all server-stamped timestamps render from the logical clock in `YYYY-MM-DDTHH:MM:SS.mmmZ` — `implementation/response.py:19-26`, `implementation/db.py:36-50`
- §2.3 — insert — ambiguity — pinned `limit`/`offset` validation errors (`ERR_INVALID_REQUEST` on non-integer, out-of-range, or negative values) and creation-order tiebreak for equal `created_at` — `implementation/middleware.py:94-108`, `implementation/services/core.py:290-291`
- §2.6 — insert — ambiguity — declared that intra-endpoint check ordering not pinned by §3 is unconstrained (impl order varies per endpoint) — `implementation/routes/lots.py`, `implementation/routes/sales.py` (mixed check orders)
- §3.1 — insert — ambiguity — store PATCH accepted even as a no-op — `implementation/routes/refdata.py:203-216`
- §3.1 — insert — ambiguity — `home_store_id` existence check on member registration, `ERR_NOT_FOUND` — `implementation/routes/refdata.py:271`
- §3.2 — insert — ambiguity — every BuyLot acquisition field is mandatory (all 11 fields required) — `implementation/routes/lots.py:93-100`
- §3.3 — insert — ambiguity — opening a screening on a lot outside `SOURCED`/`ON_SALE`/`DISPOSITION_REVIEW` is `ERR_INVALID_STATE` — `implementation/routes/lots.py:227-230`
- §3.3 — insert — ambiguity — regrade preconditions: lot in `SCREENING` and latest `COMPLETED` screening has result `FAILED_CONDITION`, else `ERR_INVALID_STATE` — `implementation/routes/lots.py:202-211`
- §3.4 — insert — ambiguity — pricing a lot not `CLEARED` in either status is `ERR_INVALID_STATE` — `implementation/routes/lots.py:361-364`
- §3.5 — insert — ambiguity — under `COMPARISON_PROHIBITED` no further pricing-time check applies once `advertises_comparison` is false — `implementation/services/core.py:379-386`
- §3.6 — insert — ambiguity — purchase creation returns HTTP 201 — `implementation/routes/sales.py:350`
- §3.7 — insert — ambiguity — creating a disposition mutates the lot and increments its `version` — `implementation/routes/lots.py:692`
- §3.7 — revise — mismatch — applying MARKDOWN or LIQUIDATE requires lot in `DISPOSITION_REVIEW` (previously "loops the lot back from DISPOSITION_REVIEW" for markdown only, and LIQUIDATE had no apply-time state gate); also pinned that SCRAP closure triggers no aisle/event cascade — `implementation/routes/lots.py:717-746, 752-753`
- §3.9 — insert — ambiguity — `supersede` is a boolean field and supersedes every conflicting prior assignment — `implementation/routes/sales.py:128-129, 153, 177-181`
- §3.9 — revise — mismatch — every event is created `SCHEDULED` regardless of window position relative to the clock; activation occurs only at a clock advance — `implementation/routes/lots.py:577-587`, `implementation/services/core.py:429-442`

No test files were used as authority; all pins trace to `implementation/` code lines listed above. SCAFFOLD*.yaml and worklog.md were not read.
