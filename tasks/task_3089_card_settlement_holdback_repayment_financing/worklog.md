# Worklog — task_3089_card_settlement_holdback_repayment_financing

## Step 1: Create Task Directory — 2026-09-29T21:34:00.000Z

Task directory `./tasks/task_3089_card_settlement_holdback_repayment_financing/` was pre-allocated by the caller (with `workspace/` inside); verified it exists. No new index computed, no other task directory created.

## Step 2: Generate Scaffold — 2026-09-29T22:37:00.000Z

All checks pass. Final state verified: lint clean, all 30 errors covered, 74 unique instance names, no forbidden concurrency vocabulary, `SCAFFOLD.yaml` contains only §1.0–§1.7 keys.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3089_card_settlement_holdback_repayment_financing/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Scale** (calibrated maximal per "harder than expert"):
- Entities: **12** (Merchant, ProcessingDayBatch, LoanOffer, Guarantor, Loan, DisclosureStatement, SettlementSweep, CatchUpPayment, EnforcementAction, FundingPartnerBank, LoanSale, MigrationSignal)
- State machines: **12** — including cyclic LoanOffer (OFFERED→EXPIRED→REUNDERWRITING→OFFERED), cyclic Loan (ACTIVE↔DELINQUENT cure loop), cyclic LoanSale (FAILED→QUOTED requote)
- Endpoints: **65** (incl. `/_clock/set_current_utc` with mandated 2026-09-01T00:00:00Z default)
- Error catalog: **30**
- Calculations: 10 (tiered offer pre-approval with seasonality haircut, pinned evaluation-order fee/minimum, pinned per-day holdback rounding, 60-day minimum threshold with >= boundary, dual-variant migration risk, dual-variant APR-equivalent, sale waterfall, enforcement draw)
- Validations: 11 priority tiers; Concurrency rules: 2 OCC (offer-accept on Merchant.version, sweep-post on Loan.version); Roles: 7 with segregation-of-duties (sale committer ≠ settler)

**Design instances:**
- Difficulty design: **18 instances** (2 per each of the 9 rules, all with differentiated aspects — dual-variant on LoanOffer vs Merchant domains; combinatorial modes (a) and (b); priority pairs state-vs-fiscal and safety-vs-referential; half-open vs closed+buffer interval overlap; repayment-total vs bank-exposure conserved quantities)
- Corner design: **56 instances** (48 active + 8 `excluded_because` stubs citing real §1.8 instances), spanning all nine claim-extraction sections

**Verification:** `scaffold_lint.py` verdict, pasted verbatim:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

All difficulty-instance arithmetic was precomputed as literals (e.g., seasonal offer: standard 1,550,000 vs conservative 1,050,000 at index 1.2; per-day holdback 101×7=707 vs naive weekly 704; period minimum exactly 64,750 with 64,749 as the miss case; sale waterfall 1,118,880 = 55,944 + 1,062,936; APR variants 0.0372 scheduled vs 0.0765 projected). No sibling task directories were inspected.

## Step 3: Copy Shared Files — 2026-09-29T22:38:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3089_card_settlement_holdback_repayment_financing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-29T22:45:00.000Z

PRD generation complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3089_card_settlement_holdback_repayment_financing/workspace/PRD.md` — 306 lines.

**Sections:**
- §1 Introduction (2 paragraphs — business context + compliance machinery angle)
- §2 Global Specifications: 2.1 RBAC (with entity-backed vs opaque identity prose per role), 2.2 Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Common Resource Properties & Logical Clock, 2.5 Money/Precision/Rounding, 2.6 OCC, 2.7 Validation Order, 2.8 Ledger Principles
- §3 Business Logic (8 subsections, organized by business process): merchant onboarding/aggregates, offer underwriting/renewal/acceptance, loan activation with disclosure+guarantee gates, daily holdback sweeps, repayment periods/delinquency/default, guarantee enforcement, migration risk, bank funding/loan sales
- §4 Endpoint table (66 rows, 4 columns), §5 Error catalogue (30 rows, 2 columns)

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 82 entity fields + 27 endpoint inputs + 13 path params = 103 required identifiers, all present in backticks after one repair pass (added path-param names `merchantId`/`batchId`/etc. and `status` filter to §2.3). PASS
- Contract 2 (Rule Coverage): all 11 validation priorities rendered as an ordered narrative in §2.7; both OCC rules expressed with endpoint + `expected_<parent>_version` + `ERR_STALE_VERSION`/412; all 47 state transitions with preconditions and side effects; all 10 calculations in reconstructible prose (tiered fee, per-day-then-accumulate holdback rounding pinned, offer variants with 1.25/0.70/0.75/$500 constants, 60-day period evaluation with inclusive `>=` MET boundary, dual-variant migration verdict, dual APR variants, reserve-first waterfall, capped enforcement draw); all 30 error IDs mentioned in §2/§3; all state/enum values present verbatim. PASS
- Contract 3 (§3 Path Purity): 454 backtick tokens in §3 scanned, zero path/HTTP-method violations (endpoints referenced via state-pair and role+verb framing). PASS

**Translation notes (rules requiring careful prose pinning):**
- `period_minimum_evaluation`: the shortfall-first catch-up application and the "portion exceeding shortfall reduction" crediting rule needed explicit ordering prose in §3.5 to avoid two divergent readings.
- `daily_holdback`: the scaffold's pinned "round per day, then accumulate" (vs weekly-sum-then-round) was called out explicitly since both readings are plausible.
- Offer renewal from `OFFERED` directly (treated as passing through `EXPIRED`) and lazy expiry evaluation were phrased without naming the endpoint.
- The `Loan` initial-state fork at acceptance (`PENDING_DISCLOSURE` vs `PENDING_ACK` by `state_code` in {CA,NY,UT,VA}) and the paired activation gates (`ERR_DISCLOSURE_NOT_ACKNOWLEDGED` vs `ERR_DISCLOSURE_NOT_DELIVERED`) were kept symmetric per the sibling-branch density rule.
- `Merchant`→`SUSPENDED` has two cascade sources (migration confirm; loan delinquency/default) while reinstatement is always explicit — pinned to prevent an implementer auto-reinstating on signal clear.

The `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` files were not opened.

## Step 5: Generate Unit Tests — 2026-09-29T23:10:00.000Z

All generation and verification passes complete. Final state:

**Task**: `task_3089_card_settlement_holdback_repayment_financing` — test infrastructure + suite generated from the two design indices only.

### Coverage (verified by automated audit)

**Queue A (Difficulty, 18 instances): 18/18 translated, each with exactly 2 tests; 0 skipped.**
The two per-instance tests split mechanically verifiable assertions from interpretation-dependent ones (e.g. `offer_expiry_reunderwriting_cycle`: status/window-cycle test + recomputed-amounts test; `enforcement_demand_window_closed_interval`: blocked-at-closed-boundary test + succeeds-one-day-after test; `daily_holdback_per_day_rounding`: accumulated-balance test + per-sweep-field test).

**Queue B (Corner, 56 instances): 48/48 non-stub instances translated (1 test each); 8 `excluded_because:` stubs not translated** — all 8 stub cross-references resolve to real difficulty instances which carry the assertions. 0 instances skipped for PRD-silence: every non-stub instance had verbatim PRD coverage and uniquely-derivable outcomes (the PRD's §2.7 fixed validation order covers the two priority-conflict difficulty instances).

### Files

- `test_helpers/`: `__init__.py`, `types.py` (13 entity TypedDicts, 11 status enums, role enum), `api_client.py` (54 endpoint methods on `GenericApiClient`), `api_errors.py` (30 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity + ledger/exposure invariants), `factories.py`, `constants.py` (fee tiers, period/cooling/window constants, standard history profiles), `test_users.py` (shared constants + per-instance builders for the two entity-backed roles), `fixtures.py` (history builders, eligible-merchant / accepted-loan / active-loan / delinquent / defaulted bundles, OCC-aware sweep posting, catch-up settle, period-evaluation clock schedule, sale helpers)
- `test_suite/`: `conftest.py` + `test_01_offer_underwriting.py`, `test_02_merchants_batches.py`, `test_03_loan_activation_disclosure.py`, `test_04_sweeps_ledger.py`, `test_05_repayment_periods.py`, `test_06_migration_sales_access.py` — **84 tests**

### Verification results
- `compileall` clean; `test_helpers` imports against the real framework; `pytest --collect-only` → 84 tests, 0 errors
- Tag audit: 0 bad/dual/unknown tags; difficulty shortfall none; corner shortfall none; stubs have 0 tests
- Citation audit: all 84 docstrings contain ≥1 PRD quote surviving literal grep of `workspace/PRD.md`; every docstring's last line is the `Design:` tag
- No `skip`/`skipif`/`xfail` markers anywhere

Note: no implementation server was run (out of scope for this stage); tests are ready for `prd-bench-local-run --isolation per-test-server`.

## Step 6: Generate Implementation — 2026-09-29T23:41:00.000Z

Done. Summary:

## Implementation: task_3089_card_settlement_holdback_repayment_financing

**Files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_3089_card_settlement_holdback_repayment_financing/workspace/implementation/`):
- `start.sh` — guarded pip install (skips when flask importable), `exec python3 app.py`, foreground, `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=2.2
- `app.py` (36 lines) — Flask app, blueprint registration, `ApiError`/404/405/generic error handlers
- `core.py` (454 lines) — logical clock (default 2026-09-01T00:00:00Z, set-only), response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, min 1 max 100), auth (X-User-ID/X-User-Role, 7 roles), in-memory `DB` dicts (no seeding), merchant aggregate recompute, offer pre-approval, loan fee, disclosure APR, validation helpers
- `routes.py` (1437 lines) — all route handlers

**Endpoints: 47/47 implemented** (1 clock + 46 lending routes covering merchants, batches, offers, loans, guarantors, disclosures, sweeps, catch-ups, enforcement actions, migration signals, funding banks, loan sales).

**State machines (12):** Merchant (ONBOARDING/ELIGIBLE/SUSPENDED), ProcessingDayBatch (OPEN/FINALIZED/SWEPT), LoanOffer (DRAFT/OFFERED/EXPIRED/REUNDERWRITING/ACCEPTED/WITHDRAWN, lazy expiry), Guarantor (LINKED/ACTIVE/ENFORCED/RELEASED), Loan (PENDING_DISCLOSURE/PENDING_ACK/ACTIVE/DELINQUENT/DEFAULTED/REPAID/CHARGED_OFF), DisclosureStatement (GENERATED/DELIVERED/ACKNOWLEDGED with 24h cooling in mandate states), SettlementSweep, CatchUpPayment, EnforcementAction (DRAFT/DEMANDED/ESCALATED/DRAWN/RELEASED), FundingPartnerBank, LoanSale (QUOTED/COMMITTED/SETTLED/FAILED with SoD), MigrationSignal.

**Calculations (9):** net_settled, merchant aggregates (trailing-12m closed window, monthly seasonality 4dp half-up, half-open 30/60d windows), offer pre-approval (×1.25, 0.70 haircut, $500 floor, 0.75 seasonality threshold, 12-month gate), tiered loan fee (0.11/0.13/0.15, floor(total/18) minimum), per-day holdback rounding with balance clip, period minimum evaluation (inclusive ≥, surplus carry, shortfall accumulation, 2-miss delinquency / 4-miss default cascades), migration risk (drop ≥0.60 volume-only vs. active chargeback >0.03 variant), dual disclosure APR (SCHEDULED 1080d vs. PROJECTED 90d pace), sale waterfall (5% reserve then bank remittance), enforcement draw (min of remaining vs. guarantee cap).

**Key semantics honored:** OCC (`expected_merchant_version` on accept, `expected_loan_version` on sweeps, 412), validation priority order (auth → existence → OCC → state → disclosure gates → SoD/uniqueness → referential → fiscal → temporal → body shape; volume-before-tenure on merchant activate per PRD §2.7 ordering), shortfall-first catch-up application with internal `_shortfall_applied` attribution (stripped from responses), REPAID cascade (clears `active_loan_id`, bumps `loans_repaid_count`, auto-creates DRAFT renewal offer when merchant ELIGIBLE, releases open enforcement actions), sweep/catch-up compensating reversals, entity-backed identity (MerchantOwner = merchant id, GuarantorPrincipal = guarantor id), all money as integer cents via `Decimal` ROUND_HALF_UP.

**Boot verification:** `start.sh` booted cleanly on a free port; two end-to-end smoke suites passed (~75 assertions) covering the full lifecycle — mandate-state (CA) and non-mandate (TX) disclosure paths, cooling window, OCC 412, duplicate-date 409, sweep clip/reverse, 4-period delinquency→default cascade with enforcement demand/window/escalate/draw to REPAID, guarantor release, migration evaluation, and bank sale quote→commit→SoD→settle waterfall with exposure release. Test server was killed by its own saved PID; temp files and `__pycache__` removed.

## Step 7: Test-Fix Iteration Loop — 2026-09-30T00:05:00.000Z

All 8 rounds pass 84/84. Clean sweep.

Summary:
- Iterations run: 2 (first sweep surfaced 6 deterministic failures; fixes applied; second sweep clean, 84/84 across all 8 rounds).
- Tests deleted: none.
- Fixes applied to `test_suite/`:
  - `test_01_offer_underwriting.py::test_flat_history_conservative_variant_floored_to_same_step` — test arithmetic error: base 1,250,000 × 0.70 = 875,000, which is NOT a multiple of the 50,000-cent ($500) step (875,000 = 17.5 × 50,000); PRD-verbatim flooring yields 850,000. Expected value corrected to 850,000.
  - `test_01_offer_underwriting.py` (`test_expired_offer_renews_and_reissues_with_fresh_window`, `test_issue_at_exact_expiry_boundary_succeeds`) and `test_05_repayment_periods.py` (`test_enforcement_demand_blocked_through_closed_window_end`) — exact-string timestamp assertions (`...T00:00:00Z`) collapsed on FORMAT SILENCE: PRD pins the *instant* ("sets `expires_at` to exactly 30 days later"; "`window_end` is set to exactly 30 days after the demand") but never the string rendering for `expires_at`/`window_end` (the "three fractional digits" convention in §2.4 is stated only for `created_at`/`updated_at`/`api_request_timestamp`), so `.000Z` vs `Z` are both PRD-faithful. Assertions relaxed per STEP 1c to compare parsed instants via a local `_iso_instant()` helper; the covered rule (exact 30-day offset) is fully preserved.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`:
  - `workspace/implementation/routes.py::accept_offer` — after the lazy `refresh_offer_expiry` transition, an EXPIRED offer fell through to the generic `ERR_INVALID_STATE_TRANSITION`; PRD §3.2 verbatim ("Acceptance attempted at or after `expires_at` is rejected with `ERR_OFFER_EXPIRED`") and the §2.7 priority order (state checks fourth, fiscal eighth) require `ERR_OFFER_EXPIRED`. Added an explicit `status == "EXPIRED"` → `ERR_OFFER_EXPIRED` branch before the generic state check; other non-OFFERED states still yield `ERR_INVALID_STATE_TRANSITION`.

Files changed:
- /home/ubuntu/github/CodingPRD/tasks/task_3089_card_settlement_holdback_repayment_financing/test_suite/test_01_offer_underwriting.py
- /home/ubuntu/github/CodingPRD/tasks/task_3089_card_settlement_holdback_repayment_financing/test_suite/test_05_repayment_periods.py
- /home/ubuntu/github/CodingPRD/tasks/task_3089_card_settlement_holdback_repayment_financing/workspace/implementation/routes.py

## Step 8: Finalize PRD — 2026-09-30T00:12:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one inline edit.

**Line counts:** PRD.md 306 lines; PRD_FINALIZED.md 306 lines (0% line-count delta; one sentence appended inline to an existing line).

**Changes:**

- **§2.4 — revise — appended a sentence pinning that every server-emitted resource timestamp (`issued_at`, `expires_at`, `activated_at`, `acknowledged_at`, `delivered_at`, `reversed_at`, `demanded_at`, `window_end`, `evaluated_at`) is rendered in ISO 8601 UTC with three fractional digits (e.g. `2026-10-01T00:00:00.000Z`) — `implementation/core.py:33-36` (`ts_now`), `implementation/routes.py:341` (`expires_at`), `implementation/routes.py:1050` (`window_end`). This resolves the PRD silence that forced Step 7 to relax exact-string timestamp assertions in `test_01_offer_underwriting.py` and `test_05_repayment_periods.py`; the pin re-tightens derivability and matches what the implementation renders for every timestamp field.

**Step-7 items requiring no edit:**
- Flat-history conservative-variant test fix — pure test arithmetic bug; PRD §3.2 already pins flooring to the 50,000-cent step (implementation `core.py:329-330` matches).
- `accept_offer` EXPIRED → `ERR_OFFER_EXPIRED` branch — an implementation fix bringing code into compliance with PRD §3.2's existing verbatim sentence ("Acceptance attempted at or after `expires_at` is rejected with `ERR_OFFER_EXPIRED`"). PRD was already correct.

**Pre-edit search log (for the single edit):**
- (a) Subject: string rendering of server-emitted timestamp fields.
- (b) Enumerated paths: `core.py:33-36` `ts_now()` — feeds `created_at`/`updated_at` (via `new_common`/`touch`, core.py:168-175), `issued_at` (routes.py:339), `activated_at` (routes.py:593), guarantor `acknowledged_at` (routes.py:722), disclosure `delivered_at` (routes.py:755) and `acknowledged_at` (routes.py:776), sweep `reversed_at` (routes.py:903), `demanded_at` (routes.py:1048), `evaluated_at` (routes.py:1188); `core.py:39-41` `wall_ts_now()` — `api_request_timestamp` (already pinned in §2.2); `routes.py:341` `expires_at`; `routes.py:1050` `window_end`. Grepped for all `*_at`/`*_end` fields: only `processing_started_at` is additional, and it is stored verbatim from the client request body (routes.py:132-144), so it is client-supplied, not server-emitted.
- (c) Wording adjustment: scoped the sentence to "every other timestamp the server emits on a resource" (rather than "all timestamps") specifically to exclude client-supplied `processing_started_at`, and enumerated the nine server-emitted fields explicitly so no off-site emission path is mis-described.

## Step 9: Complete PRD — 2026-09-30T00:28:00.000Z

Done. PRD_COMPLETED.md written at `/home/ubuntu/github/CodingPRD/tasks/task_3089_card_settlement_holdback_repayment_financing/workspace/PRD_COMPLETED.md` — a minimal inline patch over PRD_FINALIZED.md, aligned to `implementation/core.py` + `routes.py`.

**Size**: PRD_FINALIZED.md 306 lines / 47,409 chars → PRD_COMPLETED.md 306 lines / 53,373 chars (Δ +5,964 chars; all edits are in-paragraph inserts/revisions, no new sections, same 24 headers).

**Counts**: 19 ambiguity-pins (inserts), 4 mismatch-revisions.

**Changes** (`{PRD section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`):

- §2.1 — revise — mismatch — `MerchantOwner` ownership check does NOT apply to offer acceptance (impl compares no owner id at accept); narrowed to disclosures/catch-ups — `routes.py:382-504` (no uid check).
- §2.2 — insert — ambiguity — `api_request_timestamp` is wall-clock, not logical-clock — `core.py:39-41,80,90,105`.
- §2.3 — insert — ambiguity — invalid `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — `core.py:120-135`.
- §2.3 — insert — ambiguity — `has_more = (offset+limit) < total_count`; tie-break by insertion order since `created_at` reads the logical clock — `core.py:95,138-142`, `routes.py` sort sites.
- §2.4 — insert — ambiguity — clock accepts any instant (no monotonicity check); all entity lifecycle timestamps read the logical clock — `core.py:16-26,33-36`.
- §2.6 — insert — ambiguity — on sweep create, the missing/mistyped `expected_loan_version` (`ERR_INVALID_REQUEST`) surfaces only after loan and batch state gates — `routes.py:792-823`.
- §2.7 — insert — ambiguity — undefined routes also yield `ERR_NOT_FOUND` — `app.py:18-25`.
- §2.7 — insert — mismatch — three endpoint-specific exceptions: activation checks volume (8th) before tenure (9th); batch creation checks date-uniqueness before body shape; sale settle checks SoD (6th) before loan/bank state gates — `routes.py:184-192, 219-226, 1358-1364`.
- §2.8 — insert — ambiguity — every mutating operation touches (version+1, updated_at) each entity it mutates, including cascaded side effects and lazy expiry flips — `core.py:168-175`, `routes.py:36-40`.
- §3.1 — insert — ambiguity — `processing_started_at` stored and echoed verbatim — `routes.py:132-138,144`.
- §3.1 — insert — ambiguity — aggregates recomputed only at finalize/activate/offer generate/renew/migration-evaluate; sweep post/reverse do not change them (SWEPT stays included) — `core.py:244-246`, `routes.py:258,297,369,1163`.
- §3.1 — insert — ambiguity — activation from non-ONBOARDING → `ERR_INVALID_STATE_TRANSITION`; volume-before-tenure error surfacing — `routes.py:182-192`.
- §3.1 — insert — ambiguity — reinstate from non-SUSPENDED → `ERR_INVALID_STATE_TRANSITION` — `routes.py:202-203`.
- §3.2 — insert — ambiguity — `trailing_12m_avg_net_cents` snapshot stores the truncated whole-cent value — `core.py:325,337`.
- §3.2 — insert — ambiguity — issue from other statuses → `ERR_INVALID_STATE_TRANSITION`; sibling offers lazily expired before overlap check — `routes.py:327-336`.
- §3.2 — insert — ambiguity — lazy expiry flip also increments `version`/refreshes `updated_at`; expiry refresh happens on the merchant offer listing too — `routes.py:36-46, 526`.
- §3.2 — revise — mismatch — acceptance performed by any `MerchantOwner` role caller, no ownership comparison — `routes.py:384`.
- §3.3 — insert — ambiguity — loan activation: disclosure gate evaluated before guarantee gate; wrong loan status → `ERR_INVALID_STATE_TRANSITION` — `routes.py:577-591`.
- §3.3 — insert — ambiguity — guarantor acknowledge: from non-LINKED → `ERR_INVALID_STATE_TRANSITION`; uid≠guarantor id → `ERR_FORBIDDEN_FOR_ROLE` — `routes.py:716-720`.
- §3.3 — insert — ambiguity — disclosure deliver only from GENERATED / acknowledge only from DELIVERED, wrong state → `ERR_INVALID_STATE_TRANSITION`; ack uid mismatch → `ERR_FORBIDDEN_FOR_ROLE` — `routes.py:752-769`.
- §3.4 — revise — mismatch — "batch already swept by a non-reversed sweep" replaced: impl keys `ERR_BATCH_ALREADY_SWEPT` purely on `SWEPT` status (reversed sweep's batch returns to FINALIZED and can be re-swept, creating an additional sweep record); wrong-merchant batch → `ERR_BATCH_NOT_FINALIZED`; loan gates run before batch gates — `routes.py:798-820, 909-912`.
- §3.5 — insert — ambiguity — evaluate_period status gates: terminal → `ERR_LOAN_ALREADY_TERMINAL`, otherwise non-ACTIVE/DELINQUENT → `ERR_LOAN_NOT_ACTIVE`; loan version increments on every evaluation — `routes.py:621-624, 664`.
- §3.5 — insert — ambiguity — repayment-cascade auto offer: aggregates recomputed first; `issued_at`/`expires_at`/acceptance fields null, `renewal_count` 0, `generated_by` null; charge-off from non-DEFAULTED → `ERR_INVALID_STATE_TRANSITION` — `routes.py:49-79, 603-604`.
- §3.5 — insert — ambiguity — catch-up initiation ungated on loan status (only uid check, 403); settle/fail require `INITIATED`; settle of non-ACTIVE/DELINQUENT/DEFAULTED → `ERR_LOAN_ALREADY_TERMINAL`; reverse checks terminal-loan before payment status — `routes.py:920-1001`.
- §3.6 — insert — ambiguity — release: wrong action status or non-terminal loan → `ERR_INVALID_STATE_TRANSITION`; already-RELEASED guarantor untouched — `routes.py:1099-1105`, `release_enforcement_action` `routes.py:86-99`.
- §3.7 — revise — mismatch — SUSPENDED merchant evaluation yields `ERR_MERCHANT_SUSPENDED` (not `ERR_MERCHANT_NOT_ELIGIBLE`); aggregates recomputed during evaluation — `routes.py:1155-1163`.
- §3.7/§3.8 — insert — ambiguity — signal confirm/dismiss only from DETECTED, clear only from CONFIRMED; bank suspend only from ACTIVE; commit only from QUOTED; quote applies no loan-state gate; fail only from COMMITTED — `routes.py:1198-1225, 1278-1279, 1304-1329, 1336, 1381-1382`.
- §4 — insert — ambiguity — accept (200) and migration evaluate (200, signal or inline verdict) return their primary object despite creating resources — `routes.py:504, 1175-1191`.
