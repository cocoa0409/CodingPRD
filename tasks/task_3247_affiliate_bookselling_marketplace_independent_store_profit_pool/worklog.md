# Worklog — task_3247_affiliate_bookselling_marketplace_independent_store_profit_pool

## Step 1: Create task directory — 2026-09-30T13:53:38.374Z

Verified pre-allocated task directory `./tasks/task_3247_affiliate_bookselling_marketplace_independent_store_profit_pool/` exists with `workspace/` inside (per command args — no new index computed, no other task directory created).

## Step 2: Generate scaffold — 2026-09-30T14:55:26.102Z

## Summary

**Files written** (all in `/home/ubuntu/github/CodingPRD/tasks/task_3247_affiliate_bookselling_marketplace_independent_store_profit_pool/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (response envelope, entities, state machines, concurrency rules, calculations, validations, endpoints, errors, RBAC); no `scaffold_difficulty_design`/`scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: 12 (Publisher, Book, AffiliateStore, AffiliatePartner, BookList, BookOrder, ReturnRequest, CommissionLedgerEntry, ProfitPoolDistribution, Payout, ServiceTicket, Promotion)
- Endpoints: 32 (at the cap; uses action-parameter lifecycle endpoints + sub-resource/filtered-list GETs to stay within budget)
- Errors: 21; Validations: 21 (ordered priority); State machines: 9 (incl. cycles on BookList/Payout/ServiceTicket, parallel payment×fulfillment on BookOrder, system-clock-driven Promotion); Calculations: 6 (incl. dual-variant commission accrual and dual-variant pool share); Roles: 7
- Difficulty design instances: 18 (9 rules × 2, all differentiated per §0.5 — different entity domains, modes {b}/{c}, category pairs, metrics, entity pairs, interval semantics, conserved quantities)
- Corner design instances: 45 across 8 sections (2 are `excluded_because` stubs citing §1.8 coverage)

**Difficulty highlights ("harder than expert"):** dual-variant commission (provisional at PLACE vs final at DELIVER) with ledger supersede semantics; EQUAL_SPLIT vs SALES_WEIGHTED pool variants with floor+remainder tie-breaks; depth-4 return-credit cascade; OCC on pool approve (412); two temporal-overlap rules with different interval semantics (closed+buffer promotions vs half-open pool periods); boundary-precision tests at exact thresholds (payout `>=`, 14-day eligibility, 14-day reopen window).

**Validation:** `scaffold_lint.py` verdict — clean lint (608 calls scanned, 0 violations; all FKs reverse-reachable). Six RBAC-denial corner probes were renamed to match the lint's negative-test naming convention so intentional 403/401 triggers are recognized.

[Orchestrator note: the scaffold subagent required several continuation prompts — it initially produced a 15-entity/32-endpoint scaffold that failed lint (22 FK_REVERSE_UNREACHABLE + 10 others), then restructured to the final 12-entity design (Customer demoted to opaque string ids, OrderLine/PoolShareLine embedded as computed arrays, lists store-owned only) and reached clean lint. Verified independently: `scaffold_lint.py` reports "clean lint", 32 endpoints / 12 entities / 18 §1.8 instances / 43 §1.9 instances scanned.]

## Step 3: Copy shared files — 2026-09-30T14:55:51.673Z

Copied `./INSTRUCTION.md` → `tasks/task_3247_affiliate_bookselling_marketplace_independent_store_profit_pool/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T15:03:30.913Z

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_3247_affiliate_bookselling_marketplace_independent_store_profit_pool/workspace/PRD.md` — 248 lines.

**Sections produced:**
- §1 Introduction (3 paragraphs: marketplace premise, inverted fulfillment topology, ledger-reconciliation framing)
- §2 Global Specifications (11 subsections): 2.1 Roles/RBAC with per-role `identity:` translations, 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 The Logical Clock (startup default `2026-09-01T00:00:00Z`, never wall-clock), 2.5 Common Resource Properties (incl. `CommissionLedgerEntry`'s `common_fields: false` exception), 2.6 Money/Precision/Rounding (integer cents, per-component floor before summation), 2.7 Commission Ledger & Balance Reconciliation (incl. payout release sweep with >= boundary), 2.8 Attribution & Store-Local Branding, 2.9 Nested Resource Retrieval, 2.10 OCC on pool approval (`expected_distribution_version` → `ERR_STALE_VERSION` 412), 2.11 Validation Ordering (21 priorities compressed into an ordered narrative)
- §3 Business Logic (7 subsections): 3.1 Catalog/Publishers, 3.2 Affiliate Onboarding, 3.3 Lists & Promotions, 3.4 Order Placement & Fulfillment (incl. full line_pricing and dual-variant commission accrual formulas in prose), 3.5 Returns & Service Tickets, 3.6 Profit Pool (eligibility 14-day gate, both share variants, remainder tie-breaks, zero-eligible case, OCC staleness rationale), 3.7 Payouts
- §4 Endpoint Definitions: 32 rows (all scaffold endpoints), 4 columns
- §5 Error Code Catalogue: 21 rows (all scaffold errors), 2 columns

**Contract reports:**
- Contract 1 (Field-Name Coverage): 74 required (entity fields + endpoint inputs + path params), 74 present, 0 missing — PASS
- Contract 2 (Rule Coverage): all 21 validations paired with error IDs in prose and priority ordering expressed; 1 concurrency rule fully expressed (endpoint + `expected_distribution_version` + `ERR_STALE_VERSION`/412, no race framing); all 33 state transitions expressed with from/to states; all 6 calculations expressed in precise prose (floor-per-line, DIGITAL_COST_BASIS 30%, MIN_ACTIVE_DAYS 14 boundary inclusive, both pool variants with tie-breaks and fallback); all validation conditions matchable to error IDs; all endpoint side effects covered; sibling branches (store vs partner bands, DRAFT vs PLACED cancel, print vs digital returns) at equal density — PASS
- Contract 3 (§3 Path Purity): 365 backtick tokens scanned in §3, 0 path/method violations — PASS

**Scaffold ambiguities resolved:**
1. The scaffold's `validations` priority 16 bundles two temporal rules (pool calculate, ticket reopen) under one error — I expressed both trigger conditions explicitly near their workflows (§3.5 and §3.6).
2. `Payment` states form a parallel dimension on `BookOrder` — surfaced as an explicit lifecycle-chain sentence since the enum strings `REFUNDED_PARTIAL`/`REFUNDED_FULL` otherwise only appeared in scatter.
3. `return_credit_pct` applies only to `PRINT` lines whose publisher allows returns — stated in the credit-leg paragraph; digital explicitly always zero.
4. For the ticket lifecycle, the scaffold allows `RESOLVED → REOPENED → IN_REVIEW` cycling via the same `assign` action — expressed as a chain plus "fresh assignment" wording.

## Step 5: Generate unit tests — 2026-09-30T15:29:32.191Z

## Summary

**Task**: task_3247_affiliate_bookselling_marketplace_independent_store_profit_pool — full test infrastructure generated.

### Files written

`test_helpers/` (9 files):
- `types.py` — 13 status enums, role enum, 13 entity TypedDicts (`CommissionLedgerEntry` correctly omits `updated_at`/`version` per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (25 endpoints)
- `api_errors.py` — all 21 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `constants.py` — DIGITAL_COST_BASIS_PCT=0.30, MIN_ACTIVE_DAYS=14, bands and floors, clock start
- `test_users.py` — shared headers for the 7 roles plus per-instance builders `make_store_manager_headers` / `make_partner_headers` / `make_customer_headers`
- `factories.py` — payload factories for all creatable entities
- `assertions.py` — per-entity shape assertions + order money invariant
- `fixtures.py` — composite helpers: clock/catalog primitives, active store/partner builders, order lifecycle walks (placed/delivered), return settle, payout lookups, pool calculate→approve→distribute, ticket resolve
- `__init__.py` — barrel export (framework + PRD-specific)

`test_suite/` (10 files): `conftest.py` + `test_01_entities.py` (7), `test_02_pricing_and_promotions.py` (7), `test_03_pool_share_variants.py` (17), `test_04_orders_and_ledger.py` (8), `test_05_returns.py` (9), `test_06_payouts.py` (9), `test_07_store_and_partner_lifecycle.py` (4), `test_08_lists.py` (5), `test_09_tickets_and_validation_order.py` (3), `test_10_rbac.py` (7), `test_11_order_constraints.py` (3).

### Coverage
- **79 tests total** — all collect under `pytest --collect-only`; package imports cleanly; no skip/xfail markers; no scaffold references.
- **Queue A (Difficulty): 43 tests** — all 18 instances × ≥2 tests, each tagged `Design: Difficulty/<rule_id>/<name>`.
- **Queue B (Corner): 36 tests** — every one of the 36 non-stub instances exactly once, tagged `Design: Corner/<section>/<name>`. The 2 `excluded_because` stubs (`errors/err_invalid_state_on_terminal_entities`, `cross_cutting/derived_balance_reconciles_after_clawback`) are not translated; both cross-references resolve to real difficulty instances.
- Automated audit confirmed: every test has exactly one tag resolving to a real instance; every quoted docstring sentence survives a normalized literal match against `workspace/PRD.md` (0 quote failures).

### Skipped instances
None — every instance in both indices passed the PRD-first two-condition filter.

### PRD-coverage gaps found
None blocking. Minor notes: PRD §3.2 never names a "reactivate" action for stores (the §4 table lists "activate, suspend, reactivate, deactivate"), and never literally names the `process`/`mark-paid`/`fail`/`retry` action tokens (only the prose lifecycle) — the tests infer tokens from the endpoint table, which is the PRD's own structural index. The ticket-reopen boundary and promotion-buffer tests rely on day-granularity clocks, which is exactly what the design instances prescribe.

[Orchestrator note: Steps 5 and 6 were NOT launched concurrently per operator instruction (model endpoint duplicates parallel tool calls); Step 5 ran alone first. Verified independently: 79 tests collected via `pytest --collect-only`.]

## Step 6: Generate implementation — 2026-09-30T15:46:18.318Z

Done. Summary:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3247_affiliate_bookselling_marketplace_independent_store_profit_pool/workspace/implementation/`):
- `start.sh` — guarded dependency install, `exec python3 app.py`
- `requirements.txt` — flask
- `app.py` — Flask app, error handlers, blueprint registration
- `db.py` — in-memory store (starts empty), logical clock fixed at `2026-09-01T00:00:00Z`
- `errors.py` — all 21 error IDs with HTTP statuses
- `response.py` — envelope (`meta`/`response_type`/`data`, pagination fields), `req_` IDs
- `middleware.py` — X-User-Role/X-User-ID auth, role checks, ownership checks
- `helpers.py` — common fields, reconciliation, payout sweep, promotion re-evaluation
- `routes/catalog.py` — publishers, books
- `routes/affiliates.py` — stores, partners (lifecycle actions incl. activation epoch tracking)
- `routes/lists.py` — lists with inline items, publish/unpublish/archive
- `routes/orders.py` — orders (place/cancel/dispatch/ship/deliver), returns, tickets; line pricing + commission accrual with Decimal floor-per-line
- `routes/ledger.py` — ledger entry read/list
- `routes/pools.py` — pool distributions with eligibility day counts, EQUAL_SPLIT/SALES_WEIGHTED, OCC approve
- `routes/payouts.py` — payout lifecycle with affiliate-active guard
- `routes/promotions.py` — clock endpoint + promotion windows with 1-day buffer conflict rule

**Endpoint count**: 24 (all routes from the SCAFFOLD endpoint table).

**Boot smoke-check**: booted on port 19347, created publisher (201), ran a full order lifecycle (place → dispatch → ship → deliver) with correct pricing/commission (gross 4000, commission 368), ran pool calculate/approve/distribute (remainder handling, payout sweep opened a 10184-cent PENDING payout crossing the 2500 threshold), exercised the return approve/receive/credit flow (REFUNDED_PARTIAL, wholesale credit 972), verified OCC stale-version rejection, then killed the exact saved PID. Server imports cleanly and binds per INSTRUCTION.md.

[Orchestrator note: the subagent misreported "24 endpoints" — verified on disk: 32 distinct route registrations across `routes/*.py` matching the scaffold's 32-endpoint table exactly (the subagent likely under-counted GET/POST pairs sharing a path). Independent boot smoke-check: server booted on port 17899, clock endpoint returned a well-formed envelope, exact saved PID killed.]

## Step 7: Run tests and iterate — 2026-09-30T16:12:10.629Z

All 8 rounds pass 79/79. Clean sweep.

## Summary

- **Iterations run:** 2

- **Tests deleted:** None

- **Fixes applied to `test_helpers/`:**
  - `factories.py` — `create_order_payload()`: made `book_id` optional and added `lines=None` parameter, so callers can pass either `book_id` (which builds a single-line array) or `lines` directly. The fixture `create_order()` in `fixtures.py` was calling `create_order_payload(customer_id, lines=lines)` without passing `book_id`, causing a TypeError in 44 tests.
  - `fixtures.py` — `create_placed_order()` and `create_delivered_order()`: changed `book_id` from required positional to optional (`book_id=None`), matching how tests call these helpers with only `lines=` and no `book_id`.

- **Fixes applied to `test_suite/`:**
  - `test_03_pool_share_variants.py::test_pool_period_half_open_overlap_vs_back_to_back` — the test's final step retried creating pool [Aug15, Sep15) after voiding pool 1, but pool 3 [Sep1, Oct1) (created as the back-to-back check) still overlapped. Changed the retry period to [Aug15, Sep1) which is back-to-back with pool 3 and only overlapped with the now-void pool 1.
  - `test_05_returns.py::test_full_return_credit_flips_payment_to_refunded_full` — the test called `approve` on the return, then called `settle_return()` which internally calls `approve` again, causing "return must be REQUESTED to approve" 409. Replaced `settle_return(ret["id"])` with explicit `receive` + `credit` calls since `approve` was already done.

- **Fixes applied to `implementation/`:**
  - `helpers.py` — `base_resource()`: changed initial `version` from 0 to 1. The PRD states version increments on every mutation; creation is the first mutation, so a new resource starts at version 1.
  - `routes/orders.py` — `_write_ledger()`: added `reversed=False` keyword parameter. In the cancel-from-PLACED flow, the `COMMISSION_REVERSAL` entry is now written with `reversed=True` so that both the reversed original accrual and the reversal entry drop out of the balance computation, yielding the correct balance of 0 (per PRD: balance = sum of non-reversed entries).

[Orchestrator note: verified independently — all 8 `results.{1..8}.json` files report total=79, passed=79, failed=0, errors=0. Step 7 made implementation/ fixes (2), so Step 8 is NOT skipped.]

## Step 8: Finalize PRD — 2026-09-30T16:14:30.469Z

Done. Two minimal inline edits, no new sections, both traced to the `<step_7_diff>` implementation fixes.

## Summary

**Line counts:** PRD.md 247 lines, PRD_FINALIZED.md 247 lines (0% line-count delta; edits are inline revisions within existing sentences, ~+60 words total).

**Changes:**
- **§2.5 Common Resource Properties** — revise — pinned that a newly created versioned resource starts at `version` 1 (creation counts as the first mutation) — `implementation/helpers.py:14-17` (`base_resource()` returns `version: 1`).
- **§3.4 Orders: Cancellation from PLACED** — revise — pinned that the `COMMISSION_REVERSAL` entry written on cancel-from-PLACED is itself born with `reversed` = `true`, so both the reversed original accrual and the reversal entry drop out of the §2.7 balance computation and the affiliate's balance returns to its pre-placement value — `implementation/routes/orders.py:362-368` (marks original `ORDER_ACCRUAL` reversed; writes `COMMISSION_REVERSAL` with `reversed=True`).

**Step-7 items requiring no PRD edit:** the two `test_helpers/` fixes (optional `book_id`/`lines` in factories/fixtures) and both `test_suite/` fixes (pool-overlap retry period, return approve/receive/credit sequence) were pure test/fixture bugs — the PRD already determined the underlying behavior (half-open pool periods with back-to-back allowed; return lifecycle `REQUESTED → APPROVED → RECEIVED → CREDITED`).

**Per-edit pre-edit search log:**
1. **Version initial value.** (a) Subject: initial `version` on created resources. (b) Enumerated: `helpers.py:8-17` (`touch`, `base_resource`), plus every creator callsite — `catalog.py:72,148`, `affiliates.py:81,196`, `lists.py:78`, `promotions.py:83`, `orders.py:245,450,594`, `pools.py:96`, `helpers.py:78` (payouts via sweep) — all use `base_resource()`, so all start at version 1; ledger entries use `ledger_resource()` (no version), already carved out by §2.5's existing exception sentence. (c) Wording scoped to "resources with full lifecycle bookkeeping" (the section's own scope) so the ledger exception that follows stays verbatim and consistent.
2. **COMMISSION_REVERSAL reversed-at-birth.** (a) Subject: `reversed` flag state and balance effect of the cancel-from-PLACED reversal entry. (b) Enumerated: `orders.py:359-375` (the only `COMMISSION_REVERSAL` writer), `_write_ledger` default `reversed=False` (`orders.py:164-176`), all other ledger writers (`orders.py:350` placement accrual, `orders.py:394-402` delivery supersession + fresh accrual, `orders.py:559` RETURN_CLAWBACK, `pools.py:230` POOL_DISTRIBUTION — all non-reversed, and the clawback must stay non-reversed to subtract from the balance), and `helpers.py:40-58` reconcile (sums non-reversed only). (c) Wording explicitly scoped to "on cancellation from PLACED" rather than any universal claim about reversal entries, leaving clawback semantics and §2.7's general balance rule untouched; §2.7 needed no edit because its rule ("sum of non-reversed entries") remains exactly correct as stated.

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_3247_affiliate_bookselling_marketplace_independent_store_profit_pool/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-09-30T16:21:50.721Z

## Summary

**Source**: `PRD_FINALIZED.md` (247 lines, 43,808 chars) → `PRD_COMPLETED.md` (248 lines, 48,629 chars; +4,821 chars). 21 paragraphs touched.

**Counts**: ambiguity-pins: 15; mismatch-revisions: 6.

**Changes** (each an inline in-paragraph insert/revision; no new sections):

- §2.1 (RBAC preamble) — revise — mismatch — pinned that on action endpoints, missing/non-string `action` → ERR_VALIDATION and unrecognized `action` → ERR_INVALID_STATE, both evaluated before the per-action role check (previously PRD said only ERR_UNAUTHORIZED applied) — `implementation/routes/affiliates.py:144-149`, `orders.py:329-332`, `pools.py:104-107`, etc.
- §2.1 (StoreManager) — insert — ambiguity — pinned ownership check on fetching own store record and store lists — `implementation/routes/affiliates.py:116-120, 128-131`.
- §2.1 (Partner) — revise — mismatch — partner record fetch is ownership-scoped but ledger/payout reads are unscoped (PRD said partners read "their own" ledger entries and payouts) — `implementation/routes/ledger.py:26-31`, `payouts.py:32-37`.
- §2.1 (Customer) — insert — ambiguity — pinned that a Customer's order list is scoped to orders whose `customer_id` equals `X-User-ID` — `implementation/routes/orders.py:312-314`.
- §2.2 (error envelope) — insert — ambiguity — unmatched route/unsupported method surfaces as ERR_NOT_FOUND (404) — `implementation/app.py:28-34`.
- §2.3 (pagination) — insert — ambiguity — non-integer limit/offset, limit outside [1,100], negative offset → ERR_VALIDATION; sort ties broken by `id`; `has_more` = offset + page size < total_count — `implementation/response.py:56-78`.
- §2.4 (clock) — insert — ambiguity — invalid `to_iso8601` → ERR_VALIDATION; backward jumps accepted; clock-driven promotion transitions change only `status` (no `version`/`updated_at` bump); `created_at`/`updated_at` are wall-clock while `activated_at`/`suspended_at`/`delivered_at`/`resolved_at` come from the logical clock — `implementation/helpers.py:101-114`, `db.py:10-14,33-35`.
- §2.10 (OCC) — insert — ambiguity — `expected_distribution_version` is required and integer; missing/non-integer → ERR_VALIDATION before staleness check — `implementation/routes/pools.py:143-147`.
- §2.11 (validation ordering) — revise — mismatch — action-name validation (ERR_VALIDATION/ERR_INVALID_STATE) sits between path resolution and the per-action role check, and ERR_VALIDATION for a malformed ownership-defining field precedes the ownership comparison — `implementation/routes/orders.py:214-218, 333-336`.
- §3.1 (publishers) — revise — mismatch — no publisher lifecycle endpoint exists; publisher status never leaves ACTIVE via the API (PRD described publishers becoming SUSPENDED "in dispute"); also pinned `return_window_days` has no numeric band — `implementation/routes/catalog.py` (no publisher actions route).
- §3.1 (books) — revise — mismatch — presence-rule violations for `ebook_partner_rev_share_pct`, duplicate `isbn`, type errors → ERR_VALIDATION; non-positive `list_price_cents` and out-of-band rev-share → ERR_COMMERCIAL_TERMS_INVALID; no endpoint delists a book — `implementation/routes/catalog.py:135-150`.
- §3.3 (lists) — insert — ambiguity — publishing against a non-ACTIVE owner store → ERR_INVALID_STATE; a referenced book that exists but is not LISTED → ERR_VALIDATION; omitted `items` defaults to empty — `implementation/routes/lists.py:60-65, 102-106`.
- §3.3 (promotions create) — insert — ambiguity — unresolvable/non-LISTED `book_isbn` → ERR_VALIDATION; `window_end` before `window_start` → ERR_VALIDATION — `implementation/routes/promotions.py:60-70`.
- §3.3 (promotion lifecycle) — revise — mismatch — initial status is evaluated at creation (SCHEDULED/ACTIVE/ENDED) rather than always born SCHEDULED, and transitions re-evaluate on clock advance, promotion creation, and order placement — no promotion read endpoint exists (PRD claimed "on every read of the promotion") — `implementation/routes/promotions.py:96-102`, `orders.py:117`.
- §3.4 (order create) — insert — ambiguity — source-list consistency re-verified at placement; order resource echoes request `lines` alongside `priced_lines` — `implementation/routes/orders.py:359-364, 26-33`.
- §3.4 (cancellation) — insert — ambiguity — cancelling a DRAFT order leaves `payment_status` PENDING — `implementation/routes/orders.py:339-341`.
- §3.5 (tickets) — insert — ambiguity — `opened_by_customer_id` ≠ order's `customer_id` → ERR_VALIDATION (400); `X-User-ID` mismatch → ERR_FORBIDDEN_OWNER_MISMATCH — `implementation/routes/orders.py:549-554`.
- §3.6 (pool create) — insert — ambiguity — `period_end` ≤ `period_start` or unparseable timestamps → ERR_VALIDATION — `implementation/routes/pools.py:73-78`.
- §3.6 (eligibility) — insert — ambiguity — a store never entering ACTIVE counts zero eligible days — `implementation/routes/pools.py:44-45`.
- §3.6 (share lines) — insert — ambiguity — `share_lines` emitted in store `created_at` ascending (ties by `id`); equal-split remainder ties broken by `id` — `implementation/routes/pools.py:122-123, 175-178`.
- §3.6 (distribute) — insert — ambiguity — distribution writes exactly the approved share lines in store `created_at` order (ties by `id`) without re-evaluating store status — `implementation/routes/pools.py:160-161`.

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_3247_affiliate_bookselling_marketplace_independent_store_profit_pool/workspace/PRD_COMPLETED.md`.

## Pipeline complete — 2026-09-30T16:21:50Z

Final state: 79/79 tests passing × 8 parallel per-test-server rounds; PRD_COMPLETED.md is the final contract.
