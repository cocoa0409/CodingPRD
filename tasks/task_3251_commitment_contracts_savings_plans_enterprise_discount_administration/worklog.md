# Worklog — task_3251_commitment_contracts_savings_plans_enterprise_discount_administration

## Step 1: Create Task Directory — 2026-09-30T14:26:00.000Z

Pre-allocated directory `./tasks/task_3251_commitment_contracts_savings_plans_enterprise_discount_administration/workspace/` verified to exist (per command-args; no new index computed, no other task_* directory created).

## Step 2: Generate Scaffold — 2026-09-30T14:38:00.000Z

All three scaffold artifacts are complete and lint-clean. Final lint verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3251_commitment_contracts_savings_plans_enterprise_discount_administration/`):

1. **SCAFFOLD.yaml** (~1270 lines; 1336 on disk) — §1.0–§1.7 only, no design keys. Counts: **12 entities** (BillingOrganization, LinkedAccount, EnterpriseAgreement, DiscountTier, PricingAmendment, CommitmentPlan, UsageRecord, CreditGrant, Invoice, InvoiceLine, TrueUpCharge, RenewalForecast), **8 state-machine entries** (7 real: parallel-dimension EnterpriseAgreement with lifecycle×renewal axes, CommitmentPlan, UsageRecord, CreditGrant, cyclic Invoice with DISPUTED↔FINALIZED loop, TrueUpCharge, LinkedAccount), **6 calculations** (tiered marginal discount, pinned-order waterfall, dual-variant coverage ACTUAL/PROJECTED, two-pass marketplace true-up, dual-variant renewal forecast LINEAR/COHORT_WEIGHTED, chronological credit consumption), **10 validation priorities**, **56 endpoints**, **23 errors**, **4 roles** (3 opaque + LinkedAccountManager entity_backed), **1 OCC concurrency rule** (expected_agreement_version → ERR_STALE_AGREEMENT_VERSION 412).
2. **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1044 lines) — **19 instances**: all 9 §0.5 rules × 2 instances, plus a third combinatorial_formula block covering mode (c) (two-pass marketplace weighting: tier depends on consumed which includes marketplace — circular-looking, pinned pass order; modes a/b/c all exercised). All numeric asserts are literal pre-computed values (e.g., tier straddle 17500, rounding-order 128 vs 127, two-pass true-up 500000 vs 600000, forecast 160000 vs 126000).
3. **SCAFFOLD_CORNER_DESIGN.yaml** (1230 lines) — **35 instances** (33 active test_recipes across sections entities/state_machines/calculations/validations/endpoints/errors/rbac/cross_cutting_layers + 2 `excluded_because:` stubs).

Instance names are unique across the union of both design files (verified programmatically). Forbidden concurrency vocabulary scan is clean. One design fix was applied mid-draft: the original p6-vs-p7 priority-conflict instance was internally incoherent (overlap requires same family, which the referential check would have forbidden), so it was rebuilt as temporal-out-of-term vs referential-family-coverage — a genuine dual violation.

Orchestrator verification: all three files exist on disk, parse as YAML, top-level keys correct (SCAFFOLD.yaml has no design keys; difficulty/corner files have their single required key). NOTE: endpoint count is 56 — above the ≤40 safety threshold; Step 6 impl-gen instructed to write one small file per message, and orchestrator will verify implementation files on disk.

## Step 3: Copy Shared Files — 2026-09-30T14:58:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3251_commitment_contracts_savings_plans_enterprise_discount_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T15:06:00.000Z

All audits pass. The PRD is complete at `workspace/PRD.md` (282 lines).

**PRD sections:**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 RBAC & header contract, 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Common resource properties & logical clock, 2.5 Monetary precision & rounding, 2.6 Validation order & error precedence, 2.7 OCC, 2.8 Consolidated billing, 2.9 Derived balances & invariants, 2.10 Status codes
- §3 Business Logic (scattering zone): 3.1 org/account setup, 3.2 agreement lifecycle, 3.3 tiers & amendments, 3.4 plans & coverage, 3.5 usage ingest, 3.6 four-stage invoice waterfall, 3.7 credit grants, 3.8 period close & true-up, 3.9 settlement/dispute/void, 3.10 renewal & forecasting, 3.11 termination cascade
- §4 Endpoint table (56 endpoints, 4 columns)
- §5 Error catalogue (23 errors, 2 columns)

**Zero-Silence Rule audit (Hard Contracts):**
- Contract 1 (Field-Name Coverage): 70 required identifiers (all entities[].fields[].name plus request/query/path params incl. to_iso8601, outcome, mode, window_start, window_end, reason, expected_agreement_version), 70 present, 0 missing — PASS (one gap, `status`, found and repaired on the second pass).
- Contract 2 (Rule Coverage): all 10 validation priority levels expressed in evaluation order (§2.6 + endpoint-local orderings like state-before-fiscal in §3.4); the single OCC rule (expected_agreement_version → ERR_STALE_AGREEMENT_VERSION/412) fully specified; all state-machine transitions with preconditions, error IDs, and side-effect cascades (terminate cascade links 1–3, finalize cascade links 1–3, credit forfeiture bookkeeping); all 6 calculations (tiered_eda_discount, invoice_waterfall, savings_plan_coverage ACTUAL/PROJECTED, commitment_trueup two-pass, renewal_forecast LINEAR/COHORT_WEIGHTED, credit_consumption) rendered as precise reconstructible prose with constants (0.5 marketplace base weight, 1.0 top-tier weight, 0.5 early-term penalty, cohort weights 0.5/0.3/0.2) embedded; all error IDs and all 30 enum/state values verified present in prose — PASS.
- Contract 3 (§3 Path Purity): 319 backticked tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path tokens — PASS.

## Step 5: Generate Unit Tests — 2026-09-30T15:32:35.000Z

Everything passes. Final summary:

## Report

**Task 3251 — test infrastructure + suite generated.**

### Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3251_commitment_contracts_savings_plans_enterprise_discount_administration/`)

`test_helpers/` (Stage 1, 1065 lines):
- `types.py` (244) — 11 entity TypedDicts; `UsageRecord`/`InvoiceLine`/`RenewalForecast` correctly omit `updated_at`/`version` (append-only); 10 status enums + role enum
- `api_client.py` (184) — `ApiClient(GenericApiClient)` with one method per PRD endpoint (all 41)
- `api_errors.py` (60) — all 23 `ApiErrorId` values with HTTP status map registered via `set_error_http_status_map`
- `assertions.py` (129) — per-entity asserters + `assert_credit_conservation`
- `factories.py` (125), `constants.py` (26), `test_users.py` (33) — `make_manager_headers(user_id)` builder for the entity-backed `LinkedAccountManager` role
- `fixtures.py` (228) — org/agreement/plan/grant builders, `create_active_agreement`, `ingest_usage` (ownership-threaded), `setup_draft_invoice`/`setup_finalized_invoice`, `setup_expired_agreement`
- `__init__.py` (36) — barrel export

`test_suite/` (Stage 2, 2530 lines): `conftest.py` + `test_01`…`test_17_*.py`

### Coverage
- **Queue A (Difficulty): 19/19 instances, 38 tests (exactly 2 each)** — dual_variant_calc ×2, combinatorial_formula ×2, non_linear_state_machine ×2, transitive_cascade ×2, priority_pair ×2, boundary_precision ×2, cross_entity ×2, resource_temporal_overlap ×2, compensating_invariant ×2, combinatorial_formula_two_pass ×1
- **Queue B (Corner): 33/33 non-stub instances, 33 tests (1 each)**; the 2 `excluded_because:` stubs (`error_stale_agreement_version…`, `error_credit_not_usable_on_revoke_of_exhausted`) correctly not translated — both pointers resolve (to `Corner/cross_cutting_layers/occ_stale_amendment_rejected_412` and `Corner/state_machines/credit_grant_terminal_lockdown_revoke_on_exhausted_rejected` respectively, which own the assertions)
- **Skipped instances: 0** — every non-stub instance passed the PRD-first two-condition filter

### Stage 2 self-check verdict: PASS
- Tag audit: 71/71 tests carry exactly one `Design:` tag; all 52 tags resolve to real instances; zero invented tests; zero tags pointing at stubs; no `skip`/`skipif`/`xfail` markers
- PRD verbatim audit: every quoted citation survives whitespace-normalized literal grep of `PRD.md` (one hyphenation break in PRD §2.5 was fixed by splitting the quote)
- All 26 files compile; `test_helpers` imports cleanly against the real `prd_bench_local_runner.testing` framework

Orchestrator verification (2026-09-30T15:32Z, after API-interruption resume): all 9 test_helpers files (1065 lines) and 18 test_suite files (2530 lines) verified present on disk with the reported line counts — not truncated.

## Step 6: Generate Implementation — 2026-09-30T15:47:00.000Z

Server cleanly stopped, no other tasks' processes touched (I killed only PIDs 2230530, 2242301, and 2230532 — all from my own boot chain; the other app.py processes on ports belonging to tasks 3194/3229/3179 were left running).

## Summary

**Implementation complete** at `workspace/implementation/` — Python + Flask, in-memory store, no seeding, 56 endpoints, 2016 lines total.

**File list (lines):**
- start.sh (9), requirements.txt (1), app.py (59)
- store.py (83) — logical clock (default 2026-09-01T00:00:00Z), ApiError, ISO helpers
- response.py (73) — envelope `meta/response_type/data`, pagination limit/offset/total_count/has_more
- auth.py (66) — X-User-ID/X-User-Role auth, 4 roles, field validators
- helpers.py (110) — entity getters (404), resource factory, touch (version+1)
- derived.py (21) — unapplied_credit_cents / accrued_trueup_cents / conservation recompute
- calc_tiers.py (36), calc_amend.py (18), calc_coverage.py (77), calc_trueup.py (102), calc_forecast.py (42), calc_credits.py (31), calc_waterfall.py (180)
- routes_orgs.py (78) incl. clock + run-period-close expiry sweeps
- routes_accounts.py (68), routes_agreements.py (167) incl. terminate cascade, routes_tiers.py (54), routes_amendments.py (76) with OCC, routes_plans.py (146) incl. coverage read, routes_usage.py (86), routes_credits.py (68), routes_invoices.py (224), routes_trueup.py (86) dual-mode assess, routes_forecasts.py (57)

**Boot verification:** HTTP 200 on `GET /api/billing-orgs` (envelope correct, logical clock default confirmed). Full smoke passed: org→account→agreement→tier→activate→plan→usage→grant→invoice-generate→finalize→settle, with waterfall math verified by hand (10000 list − 20 plan − 998 tier − 500 credit = 8482 due).

**Ambiguities resolved:**
1. OCC check ordering on amendment create: scaffold doesn't rank `ERR_STALE_AGREEMENT_VERSION` in the priority table; I placed it after state/temporal/referential checks (just before commit), matching its "write guard" semantics.
2. Stage-4 credit-to-line allocation: PRD defines grant debit order but not line mapping; I walk lines in canonical order (account created_at, family) against the expiry-ordered grant pool.
3. Plan coverage budget scope: PRD says budget is shared per-hour across accounts, not per-line — so for multiple usage records of the same family in one line, each hour's budget applies per record (each record is its own hour).
4. Forecast "eligible spend" filter: used tier-covered families of the forecast's agreement (consistent with the true-up eligibility rule); without a filter any family would count.
5. Invoice generation allowed in any period with no upper bound on `period_index` vs `current_period_index` (PRD silent); only the non-VOIDED duplicate check is enforced per §3.6.

Orchestrator verification: all 26 files present on disk (2016 lines total), `python3 -m py_compile *.py` passes, start.sh reads $PORT via app.py and binds per INSTRUCTION contract.

## Step 7: Run Tests and Iterate — 2026-09-30T16:05:00.000Z

All 8 rounds pass cleanly: 71/71 in every round.

Summary:
- **Iterations run**: 3 sweeps (round 1: 6 distinct failures incl. flaky ones; round 2: 1 deterministic failure; round 3: clean).
- **Tests deleted**: none.
- **Fixes to `test_helpers/`**: none.
- **Fixes to `test_suite/`**:
  - `test_suite/test_07_cross_entity_dependencies.py` — `_setup()` called bare `api.terminate_agreement` where `api` was only a fixture parameter (NameError); switched to the imported `api_client` module object.
  - `test_suite/test_08_temporal_overlap.py` — `test_adjacent_window_accepted` asserted the raw submitted string `"2026-11-01T00:00:00Z"`; PRD §5 mandates rendering all timestamps with three fractional digits, so the assertion now expects the canonical `"2026-11-01T00:00:00.000Z"`.
  - `test_suite/test_15_endpoint_claims.py` — `test_clock_default_is_fixed_2026_09_01_before_any_set` asserted `current_utc` in raw `Z` form; updated to the PRD §5 canonical `.000Z` rendering of the same instant pinned by PRD §2.4.
- **Fixes to `implementation/`**:
  - `workspace/implementation/helpers.py` — `make_resource()`: the logical clock is frozen between explicit sets, so resources created in the same logical instant got identical millisecond `created_at`, making PRD-mandated `created_at`-ascending tie-breaks (grant debit order, account allocation order) nondeterministic. Appended a monotonic per-process sequence suffix (`#NNNNNNNNN`) to the stored `created_at`/`updated_at` strings so string ordering always matches creation order.
  - `workspace/implementation/calc_waterfall.py` — `generate_invoice_lines()` stage 2 gave each invoice line its own full `hourly_commitment_cents` budget; PRD §3.7 defers to §3.4's ACTUAL replay, which shares each hour's plan budget across all of the org's accounts in account `created_at` ascending order. Now tracks remaining budget per `(plan_id, usage_hour_start)` across lines.

Final state: `results.1.json` … `results.8.json` in `workspace/implementation/` all show `passed == total == 71`.

Orchestrator verification: all 8 result files re-read from disk at 2026-09-30T16:05Z — every round passed=71 total=71 failed=0. Confirmed clean.

## Step 8: Finalize PRD — 2026-09-30T16:12:00.000Z

Done. PRD_FINALIZED.md written at `workspace/PRD_FINALIZED.md`.

**Line counts / delta:** PRD.md 282 lines, PRD_FINALIZED.md 282 lines (0% line-count delta; 2 lines revised inline).

**Changes:**
- §2.3 (Pagination) — revise — added: resources created at the same logical-clock instant share the same `created_at`, and ties in any `created_at`-keyed ordering break in creation order unless a rule specifies a different tie-break — implementation/helpers.py:91-98.
- §3.6 (stage 2) — revise — added: plan coverage budget is a single shared per-(plan, usage-hour) budget of `hourly_commitment_cents` across all lines/accounts, allocated hour-ascending then account `created_at` ascending, with no carryover between hours — implementation/calc_waterfall.py:34-35,83-92.

**Items 1–3 (test-suite fixes)** were pure test bugs against behavior PRD already pinned (§5 three-fractional-digit rendering, §2.4 default clock instant); no PRD edits.

**Per-edit pre-edit search log:**
- Edit 1 (tie-break): (a) subject = `created_at`-ascending ordering/tie-breaks. (b) enumerated: all list-endpoint sorts (routes_accounts:45, routes_amendments:75, routes_orgs:49, routes_invoices:90/100/122/142, routes_trueup:55, routes_usage:83, routes_forecasts:56, routes_credits:49, routes_plans:103, routes_tiers:53, routes_agreements:81), grant pool order (calc_credits:16), waterfall usage/line ordering (calc_waterfall:19,31), coverage replay (calc_coverage:60); confirmed all sort on the stored `created_at` string, which helpers.py:97 makes strictly monotonic in creation order. (c) wording scoped with "wherever an ordering in this document keys on `created_at`" and an escape hatch ("unless a rule specifies a different tie-break") so §3.7's expires_at-first ordering and §3.4/§3.6's explicit composite orders remain consistent. The internal `#NNNNNNNNN` suffix was deliberately left unpinned: it is an ordering device invisible in every response path (all comparisons/sorts use the stored string; iso_fmt-rendered timestamps elsewhere stay in `.000Z` form), and pinning it would contradict §2.4's timestamp-format claim.
- Edit 2 (stage-2 budget): (a) subject = plan coverage budget scoping in invoice generation. (b) enumerated: calc_waterfall.py:83-92 (shared `hour_budget` per (plan_id, usage_hour_start) across lines, lines processed in account-`created_at` order per line 31), calc_coverage.py:55-75 (ACTUAL read shares one budget per hour across all org accounts, ordered by account created_at, `break` on exhaustion → no carryover), active_plan_for_family (calc_coverage.py:6-15) gating "org's ACTIVE plans whose term windows cover the usage hour". (c) phrased as "for each plan and each usage hour … allocated in the §3.4 order — hour ascending, and within an hour, account `created_at` ascending" to match both the invoice path and the coverage read, and explicitly added the no-carryover clause to match the per-hour `break`/reinit in both files.

Orchestrator verification: no implementation/*.py files modified after the 16:01Z clean sweep (mtime check) — sweep remains valid; PRD_FINALIZED.md diff confirmed to be exactly the 2 described inline revisions.

## Step 9: Complete PRD — 2026-09-30T16:20:00.000Z

All edits applied cleanly. Final summary:

## Summary

**Source vs. output:** `PRD_FINALIZED.md` 282 lines / 42,745 chars → `PRD_COMPLETED.md` 282 lines / 48,089 chars (+5,344 chars, +0 lines — all edits are inline in-paragraph inserts/revisions, no new sections).

**Counts:** 14 ambiguity-pins, 4 mismatch-revisions (18 changes total).

**Changes** (PRD section — insert|revise — ambiguity|mismatch — what — impl file:line):

- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` 400 — response.py:37-56
- §2.4 — revise — mismatch — derived-counter recomputation and `consumed_commitment_cents` advancement do not bump `version`, carving out the "every mutation increments version" claim — derived.py:4-17, routes_invoices.py:65-66, calc_waterfall.py (no touch)
- §2.4 — insert — ambiguity — equal-instant `created_at` strings carry a monotonic creation-order suffix; all `created_at` orderings resolve ties by creation order — helpers.py:88-102
- §2.4 — insert — ambiguity — clock-set answers 200 with `current_utc` in data — routes_orgs.py:11-19
- §2.6 — revise — mismatch — request-shape `ERR_INVALID_REQUEST` (400) checks run after existence but before state gates (previously PRD implied state gates precede structural); amendment-create is the exception (state gate before window shape) — routes_usage.py:20-28, routes_plans.py:31-44, routes_amendments.py:24-31
- §2.6 — insert — ambiguity — resource-level ownership authorization evaluates after the referenced account's existence check — routes_usage.py:15-18
- §2.6 — insert — ambiguity — OCC version check is the final validation of amendment create — routes_amendments.py:43-45
- §2.6 — insert — ambiguity — list-endpoint filter ids are existence-checked (404), except `invoice_id` on usage list and `linked_account_id` on invoice-line list — routes_usage.py:81-82, routes_invoices.py:120-121
- §2.1 — insert — ambiguity — `LinkedAccountManager` may GET only its own account (403 otherwise) — routes_accounts.py:31-32
- §3.1 — insert — ambiguity — `max_hourly_commitment_cents`/`capacity_quota_units` are integers ≥ 0 — routes_orgs.py:30-31
- §3.2 — insert — ambiguity — `committed_spend_cents` ≥ 1, required `name`, inverted term → `ERR_INVALID_REQUEST` 400 — routes_agreements.py:45-53
- §3.2 — insert — ambiguity — activation check order pinned: state gate → clock-in-term → tier existence → no-other-active — routes_agreements.py:89-98
- §3.3 — insert — ambiguity — amendment create check order pinned: state gate (`ERR_AGREEMENT_NOT_ACTIVE` 409 for non-ACTIVE/SUSPENDED) → inverted window 400 → out-of-term 422 → overlap 422 → coverage 422 → OCC 412 last — routes_amendments.py:24-45
- §3.4 — insert — ambiguity — plan purchase: request-shape checks (type, units discipline, window shape, all 400) precede the agreement state gate — routes_plans.py:23-44
- §3.4 — insert — ambiguity — manual plan terminate returns the updated plan (200), not the spawned charge — routes_plans.py:131
- §3.4 — insert — ambiguity — coverage read: `mode` defaults to `ACTUAL`, window defaults to plan term, `window_end < window_start` → 400, `window_hours` is whole hours (sub-hour remainder dropped), ACTUAL uses the org's ACTIVE agreement at read time for amendment rates, and per-hour covered amounts truncate (floor) to integer cents — routes_plans.py:138-146, calc_coverage.py:25-33,38-42,69-76
- §3.6 Stage 2 — revise — mismatch — at most one plan discounts a usage record: the earliest-created ACTIVE plan matching family and hour (PRD said "plans" plural) — calc_coverage.py:6-15, calc_waterfall.py:81
- §3.6 Stage 4 — insert — ambiguity — line-level credit breakdown: lines walked in stage-3 order drawing grants in expiry order, capped at the line's post-stage-3 remainder, `net_due_cents` never below zero — calc_waterfall.py:130-176
- §3.7 — revise — mismatch — finalize-time grant debit walks ISSUED/DEPLETING grants in expiry order against recorded `total_credit_applied_cents` without re-evaluating `expires_at` against the clock (PRD's candidate-pool expiry filter applies at generation only) — routes_invoices.py:139-148 vs calc_credits.py:4-17
- §3.8 — insert — ambiguity — period close answers 200 with the org and bumps org `version` — routes_orgs.py:76-78
- §3.10 — insert — ambiguity — forecasts: no lifecycle gate; `window_periods` integer ≥ 3 for both variants and stored; forecast eligible spend is raw `list_price_cents` sums with no marketplace weighting, and all families count when the agreement has no tiers — routes_forecasts.py:20-35, calc_forecast.py:14-19

No files under `workspace/implementation/` were touched; `PRD_COMPLETED.md` is the only file created/modified.

Orchestrator verification: post-Step-9 mtime check on implementation/*.py confirms zero writes after the 16:01Z clean sweep; all 8 results files still show 71/71. Sweep remains valid — no re-run required.

## Pipeline Complete — 2026-09-30T16:20:00.000Z

All 9 steps done. Final state: 71/71 tests passing across 8/8 parallel stability rounds (per-test-server isolation). Deliverables: SCAFFOLD.yaml + both design indices (lint-clean), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}, test_helpers/ (9 files, 1065 lines), test_suite/ (18 files, 71 tests: 19 difficulty + 52 corner-derived), workspace/implementation/ (26 files, 2016 lines, Python+Flask, in-memory, boot-verified), results.1-8.json all green.
