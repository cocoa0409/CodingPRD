# Worklog — task_3228_repertoire_registration_blanket_licensing_royalty_distribution

## Step 1: Create Task Directory — 2026-09-30T12:19:00.000Z

Pre-allocated task directory `tasks/task_3228_repertoire_registration_blanket_licensing_royalty_distribution/` with `workspace/` inside verified to exist; no new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-30T13:05:00.000Z

Scaffold generation complete. Lint is clean.

**Summary**

Task: Repertoire Registration, Blanket Licensing & Royalty Distribution (BMI-like PRO) — generated purely from the scenario text and the scaffold-generator skill (no sibling tasks inspected).

**SCAFFOLD.yaml (§1.0–§1.7)**
- Entities: 13 — Affiliate, Work, ShareClaim, Licensee, License, RateDispute, RateCourtCase, PerformanceEvent, DistributionCycle, RoyaltyStatement, RoyaltyAdjustment, AuditRequest, UnclaimedRoyaltyPool
- State machines: 11 — including cyclic RateDispute (OPEN↔NEGOTIATION↔RATE_COURT with dismissal loop), cyclic Work/ShareClaim (REGISTERED↔IN_CONFLICT with revocation cycle), License with expiry sweep, DistributionCycle with ADJUSTED post-state
- Calculations: 9 — tiered category fee engine, sampled-vs-census play projection (dual variant), medium×daypart performance weighting with feature bonus, per-license-truncated prorated royalty pool, waterfall royalty allocation with pinned round-then-residue-reconcile order, payable-only admin fee with zero floor, full-coverage late-claim payout, strictly-greater audit delinquency threshold, escheatment grace sweep
- Endpoints: 75 (incl. `POST /pro/_clock/set_current_utc` with the mandated 2026-09-01T00:00:00Z default)
- Errors: 28
- Roles: 9 with segregation-of-duties (adjustment creator ≠ approver) and entity-backed identities for Publisher/Songwriter/Licensee
- Concurrency: 3 OCC rules (work resolve-conflict, cycle close, license issuance) — all version-placeholder based

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)**
- 19 instances across all 9 rules (combinatorial_formula has 3, covering modes a/b/c); 0 stubs. All numeric asserts pre-computed via Python (e.g., pool 1,006,027,397 for the 90/365 proration; allocation split 335,342,466 / 335,342,465 / 670,684,931 with the −1 cent negative-residue clawback pinned).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)**
- 38 instances, 0 stubs (all carry full test recipes) across entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting_layers / consistency_model.

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` Placeholder-closure and OCC-placeholder audits also pass via a custom check.

**Output files**
- /home/ubuntu/github/CodingPRD/tasks/task_3228_repertoire_registration_blanket_licensing_royalty_distribution/SCAFFOLD.yaml
- /home/ubuntu/github/CodingPRD/tasks/task_3228_repertoire_registration_blanket_licensing_royalty_distribution/SCAFFOLD_DIFFICULTY_DESIGN.yaml
- /home/ubuntu/github/CodingPRD/tasks/task_3228_repertoire_registration_blanket_licensing_royalty_distribution/SCAFFOLD_CORNER_DESIGN.yaml

## Step 3: Copy Shared Files — 2026-09-30T13:06:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3228_repertoire_registration_blanket_licensing_royalty_distribution/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T13:12:00.000Z

All checks pass. A few manual verifications of Contract 2 items I want to double-check — the OCC entries, claim auto-acceptance to ACCEPTED from SUBMITTED, and the work flip back from IN_CONFLICT to REGISTERED when last disputed claim revoked. All present in §3.2 and §3.3. The `Affiliate` `status` enumeration includes `SUSPENDED` and `TERMINATED` — mentioned in §3.1 ("move the `status` through `SUSPENDED` to `TERMINATED`"). `PARTIALLY_ESCHEATED`/`ESCHEATED` mentioned in §3.11. `FINDINGS_FILED`/`CLOSED` in §3.10. All 51 transitions are covered by the narrative arcs (work lifecycle, share claim, license, dispute, court case, performance void/rejected, cycle, statement, adjustment, audit, pool).

Done. Final summary:

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3228_repertoire_registration_blanket_licensing_royalty_distribution/workspace/PRD.md`

**Size:** 307 lines. Section count: 5 top-level (§1 Introduction, §2 Global Specifications with 9 subsections §2.1–§2.9, §3 Business Logic with 11 subsections §3.1–§3.11, §4 Endpoint Definitions, §5 Error Code Catalogue).

**Hard contract results:**
- **Contract 1 (Field-Name Coverage): PASS** — 74 required identifiers (entity fields + endpoint input/query params), 0 missing.
- **Contract 2 (Rule Coverage): PASS** — all 28 error IDs appear in §2/§3 prose with trigger conditions; all state values (including `DECIDED`, `PARTIALLY_ESCHEATED`, `RATE_COURT`, `FINDINGS_FILED`, etc.) present as backticked UPPERCASE tokens; all 9 roles spelled exactly; all fee-engine constants present (tier caps `500,000,000,000` / `2,000,000,000,000` / `100,000,000,000` cents; rates `0.0160`/`0.0140`/`0.0110`/`0.0175`/`0.0150`/`0.0080`; minimums `25,000,000`/`10,000,000`/`5,000,000`; per-stream 20 micro-cents; per-event 15,000 cents; ADMIN 15%, withhold 5%, claims window 90 days, escheat grace 30 days, lookback 1095 days, delinquency threshold 1,000,000 cents; medium factors 1.0/2.5/1.5/0.6/1.2; daypart factors 2.0/1.0/0.7/0.4; feature bonus 1.1; sampling frame 52; days-in-year 365).
- **Contract 3 (§3 Path Purity): PASS** — 412 backticked tokens scanned in §3; zero path tokens, zero bare-method tokens, zero method+path combos.

**Verbatim-level prose coverage ensured for:**
- **All 7 calculation formulas** in precise natural language: `fee_engine` (tiered marginal rates per category, per-stream/per-event adders, max-with-minimum, single round-half-up at end), `performance_weight` (medium × daypart × universe, 1.1× feature bonus when more than two `ACCEPTED` writer claims, 4-dp round-half-up), `sampled_projection` (×52/frame, round-half-up, floored at `play_count`), `royalty_pool` (proration by covered days / 365, per-license integer truncation before summing, 15% admin deduct, single final round), `royalty_allocation` (exact-rational unit value, per-affiliate per-work round-half-up, cent-by-cent residue reconciliation ordered by rounded amount DESC then affiliate `created_at` ASC, unclaimed routing for non-`ACTIVE` affiliates and works with no accepted claim), `admin_fee` (5% of payable, capped at payable, zero floor), `late_claim_payout` (full-coverage rule, on-or-before final day), `audit_assessment` (strictly-greater-than 1,000,000 cents flips to `DELINQUENT`), `escheatment_sweep` (strictly-greater-than claims_open_until + 30 days).
- **All 3 OCC rules** with named `expected_work_version` / `expected_cycle_version` / `expected_licensee_version` fields, each mapped to `ERR_STALE_VERSION` (HTTP 412), framed in stale-version terms only.
- **All 51 state transitions** across 11 state machines (Work, ShareClaim, License, RateDispute, RateCourtCase, PerformanceEvent, DistributionCycle, RoyaltyStatement, RoyaltyAdjustment, AuditRequest, UnclaimedRoyaltyPool), with preconditions paired to their error IDs and side-effects (version bumps, cascade claim revocation on withdraw, pool zero-balance creation on cycle open, license fee_basis pinning, dispute→license blanket_fee writeback, etc.) stated in prose.
- **All 23 validation rules** with priority ordering stated in §2.9 and trigger conditions scattered through §3 adjacent to the workflows they guard.
- **Segregation of duties** on adjustment approve/reject, **audit-lookback** (1095 days), **claims-window** (90 days), **escheat grace** (30 days), **delinquency threshold** (1,000,000 cents, strictly-greater), **bulk-ingest REJECTED-row semantics** with `rejection_error_id`, and the **fixed logical clock** (`2026-09-01T00:00:00Z`, expiry sweep on set).
- §2.2 emitted verbatim from `section-2.2-response-structure.md` (untouched placeholder values, empty `data: { }`).

§4 endpoint table has exactly 4 columns (Method, Path, Description, Authorized Role(s)); §5 error table has exactly 2 columns (Error ID, HTTP Status Code); no conditions or side-effects leaked into either table. No `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` content was read or referenced.

## Step 5: Generate Unit Tests — 2026-09-30T13:32:00.000Z

All done. Final summary:

## Summary

**Task**: task_3228_repertoire_registration_blanket_licensing_royalty_distribution — full test infrastructure generated.

### Coverage
- **Queue A (Difficulty)**: 19/19 instances, each with ≥2 tests → **38 tests, 0 skipped**
- **Queue B (Corner)**: 38/38 non-stub instances, each with ≥1 test → **38 tests, 0 skipped** (no `excluded_because:` stubs existed in this index)
- **Total**: 76 test functions across 5 test files

### Docstring-tag audit (automated)
- Every test has exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, all resolving to real yaml instances — no untagged, dual-tagged, or dangling tags.
- Verbatim-citation sweep: every quoted PRD sentence in every docstring survives a literal (whitespace/backtick-normalized) grep of `workspace/PRD.md` — 76/76 pass.
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold references in generated code.
- `pytest --collect-only` passes (76 collected); `test_helpers` imports cleanly.

### Files created
- `test_helpers/`: `types.py`, `api_client.py` (all 55 endpoints), `api_errors.py` (28 errors registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (per-instance builders for entity-backed roles), `fixtures.py` (state-progression → full-lifecycle tiers, incl. distributed-cycle and suspended-affiliate routing setups), `__init__.py` (barrel; `__all__` added to `fixtures.py` so private-named helpers export through `*`).
- `test_suite/`: `conftest.py`, `test_01_works_and_share_claims.py` (12), `test_02_licensees_disputes_rate_court.py` (15), `test_03_performance_ingestion.py` (13), `test_04_distribution_cycles.py` (13), `test_05_adjustments_audits_escheat_rbac.py` (23).

### Key design decisions
- Numeric literals verified against PRD constants (e.g., pool proration `int(4.8e9×182/365)×0.85 → 2034410958`; allocation residue tie-break by affiliate creation order pinned via fixture ordering).
- One judgment call: `second_dispute_on_same_license_rejected` uses `validate_error_is_one_of([ERR_DISPUTE_ALREADY_OPEN, ERR_INVALID_STATE])` because the corner yaml itself allowed either and the PRD names the license's ACTIVE→DISPUTED state flip plus the duplicate-dispute error without fixing evaluation order between them (error-precedence silence pattern).
- No instances skipped: every non-stub design instance found verbatim PRD coverage with uniquely-derivable outcomes.

## Step 6: Generate Implementation — 2026-09-30T13:46:00.000Z

75 endpoints in the PRD table, 75 implemented. Error catalog: 28 errors in PRD §5 — all 28 are defined in `store.ERR` and raised.

Done. Summary below.

## Summary

**Files created** in `/home/ubuntu/github/CodingPRD/tasks/task_3228_repertoire_registration_blanket_licensing_royalty_distribution/workspace/implementation/`:

- `start.sh` — foreground launcher; guards `pip install` behind `python3 -c "import flask"` (no-op once deps present, critical for per-test-server reboots); `exec python3 app.py`; binds `0.0.0.0`, port from `$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4.0`
- `store.py` — in-memory DB (starts empty, no seeding), logical clock (defaults to exactly `2026-09-01T00:00:00Z`, never wall-clock), response envelope (`meta.api_request_id`/`api_request_timestamp`/`response_type`/`data`, pagination fields `limit`/`offset`/`total_count`/`has_more`), 28-entry error catalog
- `helpers.py` — auth (`X-User-ID` + `X-User-Role` against the 9 declared roles), pagination (default 10, min 1, max 100), enum/date/int validators, ISO 8601 timestamps with 3 fractional digits
- `calcs.py` — all 7 calculation rules with `Decimal` arithmetic: `fee_engine` (marginal tiers, per-stream/per-event charges, single final round-half-up, settled-fee override via `max(engine, settled)` on PATCH), `performance_weight` (medium×daypart factors, ×1.1 feature bonus when >2 ACCEPTED writer claims, 4dp half-up), `sampled_projection` (×52/frame, half-up, floored at play_count), `royalty_pool` (per-license prorate covered_days/365 truncated per license, then ×0.85, round once), `royalty_allocation` (exact-rational unit value, per-affiliate per-work round-half-up, residue reconciled cent-by-cent by (amount DESC, affiliate created_at ASC), non-ACTIVE affiliates and claim-less works routed to the unclaimed pool as gross cents), `admin_fee` (5% of payable only, capped, zero floor)
- `app.py` — all **75 endpoints** from the PRD §4 table; all **28 error IDs** from §5

**Verified by smoke tests** (three scripts, all passing): auth/RBAC (401/403), envelope shape, work registration → share-claim auto-accept/conflict flip → OCC-gated conflict resolution (412 on stale), fee engine numbers for all 3 categories, license issuance with pinned `fee_basis_cents`, dispute lifecycle (open/negotiate/settle/escalate/decide/dismiss/withdraw) including `ERR_DISPUTE_ALREADY_OPEN`, blanket-fee override semantics, performance ingest + SAMPLE projection (3 plays / 4 frame units → 39), bulk ingest with per-row REJECTED persistence and `rejection_error_id`, cycle open/capture/close (pool math verified independently: 6,522,830,599 cents across 4 intersecting licenses), statement finalize/distribute with claims window (period_end + 90d = 2026-09-28), suspended-affiliate unclaimed routing, late-claim approve/apply debiting the pool, `ERR_UNCLAIMED_POOL_INSUFFICIENT` full-coverage rule, segregation of duties (403), audit close gating (`ERR_AUDIT_CLOSE_REQUIRES_ADJUSTMENT`), delinquency flip strictly > 1,000,000, escheatment timing (`ERR_ESCHEAT_NOT_YET_DUE` → PARTIALLY_ESCHEATED → ESCHEATED), license expiry sweep and lazy expiry on read, `ERR_AUDIT_SCOPE_TOO_OLD` (1095 days). Fresh-boot-from-empty verified.

**Deviations / judgment calls** (PRD silent, chose most literal reading):
1. `POST /pro/licenses/{id}/disputes`: when a live dispute exists, the license is necessarily `DISPUTED`, so both `ERR_INVALID_STATE` and `ERR_DISPUTE_ALREADY_OPEN` could fire — I check the live-dispute condition first and return `ERR_DISPUTE_ALREADY_OPEN` (the more specific catalogued error).
2. `RateDispute.negotiation_rounds`: "counter_fee_cents must differ from the last offered fee" requires tracking the last offer — stored as a private `last_offer_cents` field on the dispute (initialized to `disputed_fee_cents`).
3. First negotiate round (`OPEN → NEGOTIATION`) is restricted to `ProLicensingAdmin` per the state machine's actor column; subsequent rounds accept either admin or owning licensee.
4. Bulk ingest returns the array envelope (`response_type: "array"`, all rows including REJECTED ones) with HTTP 200 per the endpoint table.
5. `expected_*_version` OCC fields are optional-when-omitted (skip check) but validated as integers when present, per the skill's OCC guidance.

## Step 7: Run Tests and Iterate — 2026-09-30T14:11:00.000Z

All 8 rounds pass 76/76. Clean sweep.

## Summary

**Iterations run:** 3 (initial sweep 59/76 all rounds; second 73-74/76; final 76/76 × 8 rounds — clean).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `_create_affiliate`: `party_type` is now popped from `**overrides` before being forwarded to `create_affiliate_payload`, and `create_publisher_affiliate` / `create_songwriter_affiliate` use `overrides.setdefault("party_type", ...)` instead of passing it as a duplicate keyword. Six tests crashed with `TypeError: got multiple values for keyword argument 'party_type'` because they legitimately override `party_type="SONGWRITER"` through the publisher-named helper.

**Fixes applied to `test_suite/`:**
- `test_03_performance_ingestion.py` — `test_census_network_tv_prime_credit_units`: expected constant corrected 250.0 → 500.0 (PRD formula 2.5 × 2.0 × 100; test's own comment said so but the constant was miscomputed). `test_feature_bonus_applies_with_three_writer_claims`: 275.0 → 550.0 (2.5 × 2.0 × 1.1 × 100). `test_expiry_date_inclusive_and_one_day_after_rejected` and `test_day_before_effective_date_rejected`: now set the logical clock into the license window before setup — the PRD-pinned boot clock (2026-09-01) is past these windows' `expiry_date`, so PRD's lazy-expiry rule ("a license past its expiry_date reports EXPIRED even without an explicit sweep") correctly produced `ERR_LICENSE_SUSPENDED`. Added `SYSADMIN` header constant.
- `test_04_distribution_cycles.py` — four pool-proration tests (`test_truncate_per_license_before_summing`, `test_per_license_truncation_not_rounding`, `test_license_covering_90_of_365_days_contributes_prorated`, `test_terminated_license_contributes_nothing`): same clock fix (set to 2026-02-01, inside the license window, before any lazy-expiry evaluation). `_build_two_work_scenario` and `_build_conservation_scenario`: advance the clock between affiliate creations so `created_at` tie-breaks in the PRD's residue-reconciliation rule ("rounded amount descending, then affiliate created_at ascending") are deterministic — previously created_at tied at the fixed clock instant and the implementation's residual `affiliate_id` tie-break made the clawback target random per boot (the flaky 503013699 vs 503013698 failures). `_build_two_work_scenario` also changed work X `play_count` 100 → 400 so the scenario actually produces a nonzero residue (with the old numbers the PRD-exact rounded amounts summed exactly to the pool, residue 0); expected constants in `test_residue_reconciles_rounded_sum_to_pool` and `test_unclaimed_portion_carries_no_admin_fee` recomputed per PRD §3.8 (`collection_share_bps/10000` share of work value — the old constants ignored the 5000-bps halving, e.g. asserting 335342466 where PRD yields 167671233).
- `test_02_licensees_disputes_rate_court.py` — `test_open_hearing_then_dismiss_after_hearing_not_declared`: second escalation of a dispute already in `RATE_COURT` now expects `ERR_INVALID_STATE` instead of `ERR_RATE_COURT_CASE_EXISTS`. PRD §2.6 pins a fixed error-priority order in which state-machine permission (`ERR_INVALID_STATE`) is evaluated before business checks, and §3.6 permits escalation only from `OPEN`/`NEGOTIATION` — the live-case scenario is unreachable with the dispute in `RATE_COURT`.
- `test_01_works_and_share_claims.py` — `test_work_list_pagination_envelope`: advances the logical clock between the three work creations so `created_at` values are distinct; PRD pins only "sorted by created_at ascending", which is nondeterministic under tied timestamps.

**Fixes applied to `implementation/`:**
- `app.py` — `revoke_claim`: allow revocation from `DISPUTED` status (previously only `ACCEPTED`/`SUBMITTED`). PRD §3.2 requires the automatic `IN_CONFLICT` → `REGISTERED` reverse transition "when the last DISPUTED claim on a conflicted work is revoked", and §3.3 permits a claim owner to "revoke their own claim outright" with the distribution-lock as the only stated restriction.

## Step 8: Finalize PRD — 2026-09-30T14:17:00.000Z

Wait — for Edit 3, I should double-check the impl's affiliate `id` used in the sort is the affiliate resource `id`, not the statement id. Yes: `calcs.py:222` sorts on `s["affiliate_id"]`, the affiliate's id. Wording "the affiliate's `id` ascending" is accurate.

One more consideration for Edit 3's NO-NEW-MISMATCH check: impl sorts statement specs per-affiliate (aggregated gross across works), so "statements ordered by rounded amount descending" = per-affiliate aggregated rounded gross. The PRD's original sentence already said "statements ordered by rounded amount" — my insertion only adds the final tie-break and doesn't alter that. Consistent.

For Edit 2's check: the `id` tie-break uses the resource's own `id` for every list endpoint (paginate is shared). Accurate.

For Edit 1's check: revocation from `DISPUTED` interacts with §3.2's reverse transition (already described in the following sentence of the same paragraph and in the earlier paragraph at line 110). Also confirm: does the impl reject revoke of a `REVOKED` claim with `ERR_INVALID_STATE`? Yes (app.py:526-527). And SUBMITTED revoke — permitted (line 526 tuple). The new wording "from any non-`REVOKED` status (SUBMITTED, ACCEPTED, or DISPUTED)" matches exactly.

Done. Final report.

## Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_3228_repertoire_registration_blanket_licensing_royalty_distribution/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 307 lines, PRD_FINALIZED.md 307 lines (0% delta — three in-place sentence revisions, no lines added or removed).

**Changes (3 edits, all revisions):**

- **§2.3 Pagination** — revise — appended "with ties broken by `id` in ascending order" to the list-ordering sentence — `implementation/helpers.py:72` (`paginate` sorts by `(created_at, id)`; all 23 list endpoints route through it).
- **§3.2 Work Registration and Share Claims** — revise — claim-revocation sentence now reads "revoke their own claim outright from any non-`REVOKED` status (`SUBMITTED`, `ACCEPTED`, or `DISPUTED`)" — `implementation/app.py:526` (the step_7 impl fix permitting `DISPUTED` revocation; PRD previously left source statuses unpinned while §3.2 elsewhere requires the reverse transition triggered by revoking a `DISPUTED` claim).
- **§3.8 Distribution Cycles** — revise — residue-reconciliation ordering now reads "…then by the affiliate's `created_at` ascending, with remaining ties broken by the affiliate's `id` ascending…" — `implementation/calcs.py:222` (`stmt_specs.sort(key=lambda s: (-s["gross"], s["created_at"], s["affiliate_id"]))`).

**Step_7_diff items not requiring PRD edits:** the `fixtures.py` `party_type` fix (pure test-helper bug); the test_03 credit-unit constants 250→500 / 275→550 (test arithmetic errors — PRD formulas already yield 500/550); all logical-clock test-setup fixes (PRD §2.8 already pins lazy expiry and the 2026-09-01 boot clock); the recomputed §3.8 expected constants (test errors — PRD already pins the `collection_share_bps/10000` share); the escalate-expects-`ERR_INVALID_STATE` change (PRD §2.9 already pins state-check-before-business-check priority and §3.6 pins escalation only from `OPEN`/`NEGOTIATION`; impl `app.py:986-993` matches).

**Per-edit pre-edit search log:**

1. **Edit §2.3 (list ordering tie-break):**
   (a) Subject: default sort order of list endpoints.
   (b) Enumerated: `helpers.py:71-74` (the single `paginate()` sorter, key `(created_at, id)`); grep of all `paginate(` call sites in `app.py` (23 sites, lines 186…1875) — confirmed no endpoint overrides the ordering, so a global wording is safe.
   (c) No adjustment needed; wording is a global clause matching the shared sorter.

2. **Edit §3.2 (revocable claim statuses):**
   (a) Subject: which claim statuses the owner-initiated revoke endpoint accepts.
   (b) Enumerated: `app.py:521-561` (`revoke_claim` — permits `SUBMITTED`/`ACCEPTED`/`DISPUTED`, rejects `REVOKED` with `ERR_INVALID_STATE`, ownership check, distribution-lock check, aggregate recompute and IN_CONFLICT→REGISTERED reversal); `app.py:327-328` (work withdraw revokes every non-`REVOKED` claim — separate path, untouched by the edit); `app.py:382-383` (conflict-resolution revokes listed `DISPUTED` claims — registrar path, untouched); `app.py:433-443` and `573-582` (non-`REVOKED` treated as live for duplicate-check and challenge-eligibility — consistent with the new wording).
   (c) Wording scoped explicitly to "their own claim" owner-initiated revocation so it does not re-describe the withdraw/resolution cascades.

3. **Edit §3.8 (residue reconciliation tie-break):**
   (a) Subject: ordering of statements for cent-by-cent residue award/clawback.
   (b) Enumerated: `calcs.py:213-236` (the only `stmt_specs` sort and the residue loops — final key is affiliate `id`); `app.py:1439-1474` (`distribute_cycle` — iterates statements without order-dependent money effects); statement list endpoints (`app.py:1476-1561`) route through the generic paginator and are unaffected.
   (c) Kept the existing "one cent at a time … in that same order" phrasing unchanged (impl's `i % n` cycling remains compatible and under-determined); only inserted the `affiliate id` tie-break clause so no off-site behavior is narrowed.

## Step 9: Complete PRD — 2026-09-30T14:34:00.000Z

Done. `PRD_COMPLETED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_3228_repertoire_registration_blanket_licensing_royalty_distribution/workspace/PRD_COMPLETED.md`.

**Size**: PRD_FINALIZED.md 307 lines / 51,779 chars → PRD_COMPLETED.md 309 lines / 59,695 chars (+2 lines, +7,916 chars).

**Counts**: 25 ambiguity-pins, 3 mismatch-revisions (28 edits total; the mismatch edits are #3, #7, #8 below).

Changes (PRD section — kind — class — what — impl ref):

- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` and negative/non-integer `offset` rejected with `ERR_VALIDATION` — helpers.py:47-68
- §2.4 — revise — ambiguity — `created_at`/`updated_at` read from the logical clock; `version` starts at 1 — store.py:62-81
- §2.6 — revise — mismatch — expected-version fields are optional when omitted; non-integer expected version → `ERR_VALIDATION` — app.py:347-352, 704-709, 1416-1420
- §2.8 — insert — ambiguity — in-memory store starts empty; clock accepts offset datetimes (naive = UTC), may move backward, returns 200 with empty data object; bad `to_iso8601` → `ERR_VALIDATION` — store.py:41-55, app.py:121-129, helpers.py:87-99
- §3.2 (work registration) — insert — ambiguity — `registered_by_affiliate_id` must exist (`ERR_REFERENCE_NOT_FOUND`) but need not be the caller nor a PUBLISHER; `alternate_titles` must be a list of strings — app.py:233-243
- §3.2 (claim creation) — insert — ambiguity — non-own `affiliate_id` → `ERR_FORBIDDEN`; claims allowed on works in any status — app.py:413-417, 431-432
- §3.2 (challenge) — revise — mismatch — challenge flips work to `IN_CONFLICT` from any status incl. `CONFIRMED`; violations → `ERR_FORBIDDEN`, non-`ACCEPTED` target → `ERR_INVALID_STATE` — app.py:564-591
- §3.2 (revoke) — revise — mismatch — lock = claim's work referenced by an `ACCEPTED`/`VOIDED` event captured into a cycle holding a `FINALIZED`/`PAID`/`ADJUSTED` statement; non-owner revoke → `ERR_FORBIDDEN`, `REVOKED` revoke → `ERR_INVALID_STATE` — app.py:521-548
- §3.3 (withdraw) — insert — ambiguity — withdraw allowed only from `REGISTERED`/`IN_CONFLICT` (else `ERR_INVALID_STATE`); ownership violations → `ERR_FORBIDDEN` — app.py:312-319
- §3.3 (withdraw aggregate) — insert — ambiguity — non-conflict withdrawal recomputes aggregate (zero post-revocation) rather than explicit reset — app.py:330-333
- §3.4 — insert — ambiguity — nullable `settled_fee_cents` field (stamped at settlement/decision, compared only on revenue/usage patch); patch with neither field is a no-op; VENUE usage units charged 15,000 cents each vs DIGITAL_SERVICE micro-charge — app.py:601-611, 674-687, calcs.py:81-84
- §3.5 — insert — ambiguity — issuance bumps the licensee's `version` — app.py:730
- §3.5 (lifecycle) — insert — ambiguity — suspend/reinstate/terminate precondition failures all → `ERR_INVALID_STATE` — app.py:790-794, 806-810, 822-828
- §3.6 (open dispute) — insert — ambiguity — duplicate-live-dispute check precedes license-state check; `opened_by_role` must match caller role (else `ERR_FORBIDDEN`); dispute carries `last_offer_cents` initialized to `disputed_fee_cents` — app.py:851-863, 872
- §3.6 (negotiate) — insert — ambiguity — first round from `OPEN` may carry optional constraint-free `counter_fee_cents`; licensee attempting first round → `ERR_INVALID_STATE`; identical counter → `ERR_VALIDATION`; standing offer tracked — app.py:935-958
- §3.7 (single ingest) — insert — ambiguity — deterministic check order: license status, then window, then work-confirmation; SAMPLE `frame_units_reported` must be integer ≥1 else `ERR_VALIDATION`; census rows store field as given/null — app.py:1116-1117, 1127-1137
- §3.7 (bulk) — insert — ambiguity — bulk returns `200 OK` array envelope with meta limit=row count, offset 0; rejected rows persist echoed fields, `universe_estimated_plays` 0, `credit_units` 0.0 — app.py:1162-1180, 1192-1206
- §3.8 (create/open cycle) — insert — ambiguity — duplicate `label` and reversed period → `ERR_VALIDATION`; cycle born with `claims_open_until` null — app.py:1338-1352
- §3.8 (capture) — insert — ambiguity — capture rules: unknown id → `ERR_REFERENCE_NOT_FOUND`; non-`ACCEPTED` or other-cycle event → `ERR_INVALID_STATE`; date outside cycle period → `ERR_VALIDATION`; cycle `version` bumps when ≥1 event listed — app.py:1286-1303
- §3.8 (residue) — insert — ambiguity — residue reconciliation includes rounded no-claim pool credits and walks the statement ordering cyclically (wraps for |residue| > statement count) — calcs.py:200-236
- §3.8 (routing) — insert — ambiguity — pool credited at calculation time for both routings; claims referencing a deleted affiliate route gross to pool as unclaimed — calcs.py:201-203, 216-217, 263-268
- §3.9 (file adjustment) — insert — ambiguity — `audit_id` rule is field-shape `ERR_VALIDATION` checked before affiliate restrictions; unknown `audit_id` → `ERR_REFERENCE_NOT_FOUND`; affiliate filing violations → `ERR_FORBIDDEN`; `LATE_CLAIM` window checked at filing; adjustment records `created_by_user_id` — app.py:1597-1624
- §3.9 (approve) — insert — ambiguity — claims-window check applies only to `LATE_CLAIM`; other reasons file/approve any time — app.py:1687-1699
- §3.9 (apply) — insert — ambiguity — pool debit requires pool to exist, balance not re-validated; cycle moves to `ADJUSTED` only from `DISTRIBUTED` — app.py:1734-1745
- §3.10 — insert — ambiguity — reversed scope → `ERR_VALIDATION`; lookback horizon inclusive (end exactly 1095 days back accepted); close requires `FINDINGS_FILED` else `ERR_INVALID_STATE` — app.py:1768-1774, 1832-1833
- §3.11 — insert — ambiguity — escheat allowed from `OPEN` or `PARTIALLY_ESCHEATED`; `ESCHEATED` pool → `ERR_INVALID_STATE`; unset claims window → `ERR_ESCHEAT_NOT_YET_DUE`; due-date check precedes amount check — app.py:1892-1905
- §4 table (GET /pro/licensees) — insert — ambiguity — filters `category`, `credit_standing` — app.py:647-653
- §4 table (GET /pro/cycles/{id}/statements) — insert — ambiguity — filters `status`, `epoch`, `affiliate_id` — app.py:1483-1495

Everything else in the PRD (envelope shapes, error catalog and HTTP codes, role tables, fee-engine constants, sampling factor 52, credit-weight factors, 15%/5% admin rates, 365-day proration with per-license truncation, 90-day claims window, 30-day grace, 1,000,000-cent delinquency threshold, lazy license expiry) was verified to match the implementation exactly and was left untouched.
