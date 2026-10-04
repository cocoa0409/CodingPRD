# Worklog — task_3499_circulating_numismatic_coin_production_subscription_sales

## Step 1: Create Task Directory — 2026-10-02T19:00:00.000Z

Task directory was pre-allocated by the caller: `tasks/task_3499_circulating_numismatic_coin_production_subscription_sales/` with `workspace/` inside. Verified it exists; no new index computed, no other task_* directory created.

Scenario: Circulating and Numismatic Coin Production & Subscription Sales (United States Mint) — production planning vs Federal Reserve orders, blank supply, metal procurement + seigniorage, commemorative programs with surcharge beneficiaries, mintage/household limits with allocation + queue management, subscription programs, bullion program with authorized purchasers, QC / error coin destruction, release calendar + sell-out management.

Difficulty instruction: "Generate task much harder than expert level!" (applies to prd-bench-scaffold-generator only).

## Step 2: Generate Scaffold — 2026-10-02T20:40:00.000Z

All checks pass. Scaffold generation complete for task_3499.

**Files written** (all under the task directory):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**(a) Section counts**
- Entities: 14 (Denomination, FederalReserveOrder, MetalProcurementLot, ProductionRun, CommemorativeProgram, NumismaticProduct, Collector, NumismaticOrder, Subscription, SubscriptionInvoice, BullionIssue, AuthorizedPurchaser, BullionAllocation, ErrorCoinCase)
- State machines: 12 (incl. run rework cycle, program design-revision self-loop, subscription dunning cycle, AP suspend↔reinstate cycle, order payment×allocation independent dimensions, SOLD_OUT↔ON_SALE flip-flop)
- Calculations: 14 (seigniorage budgeted/realized, dual-variant metal exposure, blank conservation, household threshold, queue allocation, head-of-line waitlist promotion, per-unit-rounding subscription billing, pinned-order program net proceeds, surcharge min-cap, tier+bracket bullion pricing, 30-day error-rate gate, press-window half-open overlap, 24h release gap)
- Validations: 32 ordered rows (auth → role → ownership → existence → state/OCC → referential → safety/segregation → temporal → constraint → fiscal)
- Endpoints: 48
- Errors: 46 (all referenced; http codes 400/401/403/404/409/412/422)
- Roles: 12 (2 entity-backed: Collector, BullionDealer; segregation-of-duties model)
- Concurrency rules: 2 OCC (allocation offer on BullionIssue.version, billing cycle on Subscription.version), both 412/ERR_STALE_VERSION

**(b) Design indices**
- Difficulty: **25 instances** (rules 1–9: 2/3/3/2/3/3/3/3/3 — exceeds the ≥18 floor; all formula-derived asserts pre-computed as literals, e.g. budgeted 1900000 vs realized 1789000 seigniorage, MTM 2000000 vs budget-variance 3000000 exposure, 8996×2+495=18487 invoice, T2/50oz → 13312500 bullion price)
- Corner: **91 instances** (83 active + 8 `excluded_because` stubs, all stubs resolve to named §1.8 instances); instance names unique across the union

**(c) YAML parse confirmation**: all three files parse with `yaml.safe_load`; `scaffold_lint.py` verdict: **clean lint** — 696 calls scanned, zero violations, all FKs reverse-reachable. One indentation hazard did occur mid-build (unquoted `errors[ERR_X]` entries inside flow-style `grounds:` lists) and was fixed by quoting, verified by re-parse.

**(d) api_prefix / clock**: `api_prefix: /mint`; logical clock endpoint is unprefixed `POST /_clock/set_current_utc` with mandatory boot default `2026-09-01T00:00:00Z`; all fixture dates ≥ that default. Spot prices ride the same endpoint as an optional `spot_prices` map (absent at boot → ERR_SPOT_PRICE_MISSING).

**(e) Ambiguity decisions baked in**:
1. Time-based transitions (program window open/close, product release, allocation expiry) fire only on clock-set sweeps; recipes use two-step clock advances where program/product ordering could matter.
2. Order allocation is atomic whole-order (no partial fills); over-mintage orders waitlist instead of erroring; waitlist promotion is strict head-of-line blocking ordered by `created_at` (never `id`).
3. Production run inherits denomination from its Fed order; order-state is gated at run *start*, not run create — enabling the (state p5) vs (fiscal p10) priority test.
4. Subscription discount rounds per-unit before multiplication; program admin fee is 5% of (gross − direct), evaluation order pinned.
5. Segregation of duties enforced by user-id comparison: disburser ≠ program creator, settler ≠ offerer, two destruction certifiers distinct and ≠ reporter (reporter role itself is also role-gated off destroy).
6. Denominations referenced by `code` string rather than FK id; blank stock observable via the seigniorage report (blank-delivered/on-hand/reserved/produced/scrapped conservation row).
7. INSPECTION is a transient state resolved within the inspect call; SOLD_OUT products still accept orders straight to WAITLISTED.
8. Endpoint count 48 exceeds the Expert guideline band deliberately (user asked for max difficulty) but stays within the range of the shipped examples (48–64) and the impl-gen skill's per-resource-group modularization; difficulty is carried by density (14 calcs, 32 validations, 46 errors, 12 roles) rather than CRUD volume.

**Orchestrator verification (independent re-measurement)**: all three files parse with yaml.safe_load; SCAFFOLD.yaml has api_prefix `/mint` and the 14 entity names listed above (no foreign-domain contamination). Difficulty index re-counted from YAML: 25 active / 0 stub across 9 rules (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 3). Corner index re-counted: 83 active / 8 stub across 8 sections (entities 9, state_machines 35 active/2 stub, calculations 9 active/3 stub, validations 13, endpoints 4 active/1 stub, rbac 9, cross_cutting_layers 3 active/2 stub, consistency_model 1). **Grand total active test instances: 108** — Step 5 will be split into 5a (helpers) + 5b fanout.

## Step 3: Copy Shared Files — 2026-10-02T20:41:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T20:55:00.000Z

PRD generation complete. All checks pass.

**Output:** `workspace/PRD.md` — 323 lines total.

### (a) Section list with line counts
- Title + §1 Introduction: lines 1–8 (8)
- §2 Global Specifications: lines 9–128 — §2.1 RBAC (11–20), §2.2 API Response Structure, emitted verbatim (21–69), §2.3 Pagination (70–73), §2.4 Logical Clock & Spot Prices (74–79), §2.5 Identity/Timestamps/Versioning (80–87), §2.6 OCC (88–95), §2.7 Validation Order & Error Precedence (96–112), §2.8 Monetary Precision & Rounding (113–116), §2.9 Seigniorage/Reconciliation/Reports (117–124), §2.10 Segregation of Duties (125–128)
- §3 Business Logic: lines 129–216 — §3.1 Denominations & Fed Order Intake (131–140), §3.2 Metal Procurement & Vault Receipt (141–148), §3.3 Striking Operations (149–158), §3.4 Error-Coin Quarantine & Destruction (159–164), §3.5 Commemorative Programs (165–176), §3.6 Catalog/Release Calendar/Order Flow (177–192), §3.7 Subscriptions & Dunning (193–202), §3.8 Bullion Program (203–216)
- §4 Endpoint Definitions: lines 217–271 (48-row table, 4 columns)
- §5 Error Code Catalogue: lines 272–323 (46-row table, 2 columns)

### (b) Total: 323 lines.

### (c) Known-ambiguity / adjudication sites (feed Step 8 prompt)
1. **NumismaticProduct `terminal_states` lists `SOLD_OUT` yet declares `SOLD_OUT → ON_SALE`** — resolved as cyclic: SOLD_OUT is reversible, WITHDRAWN is the sole terminal state (consistent with `state_machine_shape: cyclic`). Same pattern for **BullionIssue** (`SOLD_OUT → ACTIVE`); the issue has no absorbing state.
2. **Fed-order cancel endpoint description says "releases their reserved blanks"** while the state-machine note says no blank release occurs — resolved to the note: PLANNED/REWORK runs hold zero `reserved_blanks` (reservation exists only at start), so the release is vacuous. PRD states no blanks return on cancel.
3. **Validation row `error_id: ERR_UNIQUENESS_DOMAIN`** is not in the error catalog; its own description maps to `ERR_DENOMINATION_EXISTS`/`ERR_PRODUCT_CODE_EXISTS`/`ERR_EMAIL_EXISTS`. PRD names only the three catalog ids.
4. **Rung-5 state gate vs rung-6 body-reference existence** (product-orderable check precedes `ERR_UNKNOWN_PRODUCT` numerically) — PRD states the ladder as declared and adds that body references resolve at rung six with state gates evaluating against the resolved resource.
5. **No explicit issue-ACTIVE gate on allocation creation** — resolved via `ERR_POOL_INSUFFICIENT`: a SOLD_OUT issue's `remaining_pool_units` is zero, so any offer fails the pool check.
6. **Second invoice failure while DUNNING** has no declared DUNNING→DUNNING transition — PRD states the first failure flips ACTIVE→DUNNING, subsequent failures leave it DUNNING, and the third failure writes the invoice off and moves the subscription to CANCELLED_NONPAYMENT.
7. **Subscription cancel from a terminal state** has no dedicated error — generic `ERR_INVALID_STATE_TRANSITION` fallback applies (stated).
8. **Spot price required at lot creation even for hedged lots** (validation applies unconditionally because `order_spot_cents_per_tonne` is recorded at creation) — stated explicitly.
9. **`planned_end` not after `planned_start`** maps to `ERR_PRESS_WINDOW_OVERLAP` (409) per the priority-8 row, not `ERR_INVALID_REQUEST`; the analogous sales-window rule has no dedicated row and maps to `ERR_INVALID_REQUEST` (400).
10. **Allocation confirm's "clock < `offer_expires_at`"** is subsumed by the eager expiry sweep (a lapsed offer is already EXPIRED → `ERR_ALLOCATION_NOT_CONFIRMABLE`); PRD states both.
11. **Anonymous is a declared role value** — callers still send both headers; rung-1 header presence applies even to collector registration.
12. **`realized_unit_blank_cost` divisor** (sum of `blanks_produced` over DELIVERED lots) is positive in every reachable fulfillment (production requires delivered blanks); PRD states the input set without inventing a zero-division rule.
13. **Timestamp two-family rendering** stated contractually in §2.5: `created_at`/`updated_at`/`api_request_timestamp` always render with exactly three fractional digits; domain datetimes (`planned_start`, `planned_end`, `release_datetime`, `sales_window_start`/`sales_window_end`, `offer_expires_at`, `current_utc`) render as the logical clock reads / as supplied; date fields (`due_date`, `planned_delivery_date`, `next_billing_date`) render as ISO dates.
14. **Clock endpoint placement** stated explicitly: `POST /_clock/set_current_utc` sits outside the `/mint` prefix, boot default 2026-09-01T00:00:00Z with no spot prices, `spot_prices` replaces only keys present, and clock-set sweeps exactly four transition families (program open, program close, product release, offer expiry).

### (d) Error-id coverage
Grep check over all 46 catalog ids against PRD prose: **ALL 46 ERROR IDS PRESENT** (each appears at least once outside the §5 table, in §2.7/§3 narrative).

### (e) Completeness
Tail check confirms the file ends inside §5 Error Code Catalogue with the final row `ERR_PAYMENT_AMOUNT_MISMATCH | 422`. Contract 1 (field-name coverage): all ~115 entity fields + endpoint input/query/path identifiers verified present in backticks — PASS. Contract 3 (§3 path purity): zero backticked tokens in §3 start with `/` or are bare HTTP methods — PASS. Contract 2 verified by construction during drafting: all 12 state machines' transitions/guards/side effects, all 14 calculations with literal constants (50 t/day vault cap, 0.02/30-day quality gate, 24-hour family gap, 10% subscriber discount with pinned per-unit rounding, 495/895/0 shipping tiers at 3/10/11 units, 5% admin fee, 300/450/625 tier bps, 200/100/0 bracket bps at 100/500 oz), all 32 validation rows with error ids, both OCC rules, and the full priority ladder are expressed in prose.

**Orchestrator verification**: PRD.md is 323 lines, ends with `ERR_PAYMENT_AMOUNT_MISMATCH | 422`, contains 91 `ERR_` mentions, 2 `set_current_utc` mentions. Step-4 ambiguity list preserved above for the Step 7/Step 8 prompts.

## Step 5a: Generate Test Helpers (Stage 1, frozen) — 2026-10-02T21:05:00.000Z

All verification passed. Final summary:

## (a) Files written (10 files, 2280 lines)

| File | Lines |
|---|---|
| `test_helpers/types.py` | 385 |
| `test_helpers/constants.py` | 89 |
| `test_helpers/api_errors.py` | 119 |
| `test_helpers/api_client.py` | 230 |
| `test_helpers/test_users.py` | 84 |
| `test_helpers/factories.py` | 266 |
| `test_helpers/assertions.py` | 434 |
| `test_helpers/fixtures.py` | 530 |
| `test_helpers/__init__.py` | 33 |
| `test_suite/conftest.py` | 110 |

No `test_*.py` files created (verified: 0). No "scaffold" mentions in any generated file (grep-verified).

## (b) FROZEN helper API surface (Stage 2 must not modify these files)

**api_client.py** — `ApiClient(GenericApiClient)` + `api_client` singleton. `_request` override routes `/_*` paths to the bare host, all else under `/mint` (probe-verified: `/_clock/set_current_utc` unprefixed, `/mint/denominations`, `/mint/reports/seigniorage`, `/mint/products` prefixed). 45 methods, one per endpoint: `set_clock(payload, headers)`, `create_denomination`, `create_fed_order`, `get_fed_order`, `cancel_fed_order`, `create_metal_lot`, `get_metal_lot`, `receive_metal_lot`, `create_production_run`, `list_production_runs(headers, params=None)`, `get_production_run`, `start_production_run`, `inspect_production_run(id, payload, headers)`, `cancel_production_run`, `create_program`, `get_program`, `decide_design(id, payload, headers)`, `disburse_surcharges`, `create_product`, `list_products(params)`, `get_product`, `withdraw_product`, `create_collector`, `create_order`, `list_orders(params)`, `get_order`, `pay_order(id, payload, headers)`, `cancel_order`, `create_subscription`, `list_subscriptions(params)`, `get_subscription`, `cancel_subscription`, `run_billing_cycle(id, payload, headers)` (201 — creates invoice), `list_subscription_invoices(id, params)`, `pay_invoice(id, payload, headers)`, `create_bullion_issue`, `get_bullion_issue`, `create_authorized_purchaser`, `set_authorized_purchaser_status(id, payload, headers)`, `create_allocation(issue_id, payload, headers)`, `list_allocations(params)`, `get_allocation`, `confirm_allocation(id, headers)`, `settle_allocation(id, headers)`, `create_error_coin_case`, `list_error_coin_cases(run_id, params)`, `destroy_error_coin_case(id, payload, headers)`, `get_report(report_type, headers, params=None)`.

**api_errors.py** — `ApiErrorId` (46 members, all PRD §5 ids), `HTTP_STATUS_CODES`, auto-registered via `set_error_http_status_map` at import.

**assertions.py** — `validate_created(response)` (mandatory 201 wrapper; convention documented in module docstring), timestamp families `assert_system_timestamp` (exactly 3 fractional digits) / `assert_domain_timestamp` (as-supplied, no ms normalization) / `assert_iso_date`; 14 `assert_<entity>(data)`; `assert_order_derived_status`, `assert_report_envelope`, `assert_blank_conservation`; PRD-pinned calculators (Decimal-exact): `round_half_up_int`, `round_half_up_2dp`, `budgeted_unit_seigniorage_cents`, `realized_unit_blank_cost_cents(lots)`, `realized_seigniorage_cents`, `subscriber_unit_net_cents`, `shipping_cents_for_units`, `subscription_invoice_amount_cents`, `program_net_proceeds_cents`, `surcharge_disbursement_cents`, `bullion_bracket_bps`, `bullion_premium_bps`, `bullion_total_price_cents`.

**factories.py** — 14 `create_*_payload(**overrides)` + action payloads (`clock_payload`, `decide_design_payload`, `inspect_payload`, `order_payment_payload`, `billing_cycle_payload`, `invoice_payment_payload`, `set_status_payload`, `destroy_payload`). Conventions: None-drops-key for optional fields; `_uniq` counter keeps default codes/emails/families collision-free.

**constants.py** — 38 constants (see (d)).

**test_users.py** — `TEST_USERS` (18 header entries), named user-id constants (`pm-1/pm-9/fin-1/fin-9/qi-1/qi-9/dc-1..dc-4`, all distinct — segregation-safe), `make_collector_headers(id)`, `make_bullion_dealer_headers(id)`, `make_headers(user_id, role)`.

**fixtures.py** — `set_clock(client, to_iso8601, spot_prices=None)` (required signature), `add_months`; circulating chain: `create_denomination`, `create_fed_order`, `create_metal_lot`, `receive_metal_lot`, `setup_denomination_with_delivered_lot`, `setup_circulating_base`, `create_run`, `start_run`, `inspect_run`, `create_started_run`, `create_completed_run`, `setup_quarantined_case`, `destroy_case`; catalog: `create_product`, `setup_on_sale_product`, `create_collector(s)`, `place_order`, `pay_order`, `place_and_pay_order`; subscriptions: `setup_subscription`, `run_billing_cycle` (returns fresh version), `setup_billed_subscription`, `pay_invoice`, `setup_dunning_subscription`, `setup_written_off_subscription`; programs: `create_program`, `approve_program`, `setup_approved_program`, `setup_on_sale_program`, `setup_sales_closed_program`, `setup_program_with_paid_sales`, `disburse_surcharges`; bullion: `create_authorized_purchaser`, `set_ap_status`, `setup_bullion_issue`, `create_allocation_offer` (surfaces fresh issue version), `confirm_allocation`, `settle_allocation`, `setup_confirmed_allocation`, `setup_settled_allocation`; plus header aliases ADMIN/LIAISON/PROCUREMENT/PLANNER/INSPECTOR/MANAGER/DIRECTOR/FINANCE/ANONYMOUS.

**conftest.py** — session `api` fixture + 18 role-header fixtures.

## (c) Verification results

```
PY_COMPILE: ALL 10 FILES OK
python3 -m pytest test_suite --collect-only -q → "no tests collected in 0.20s", EXIT=5
```
Exit 5 is pytest's documented "no tests collected" code — 0 items, zero import errors, as required. Runtime probes also passed: path routing, singleton binding, all 13 design-index pre-computed literals reproduced exactly by the calculators (18487/27483/36879, 13312500/128750000/25987500/26000000, 760000, 350000/300000, 19.0/5.11/1789000.0), error-map registration (46 entries), SoD id distinctness, timestamp-family accept/reject.

## (d) PRD grep evidence for constants

All 26 checks hit verbatim in PRD.md (0 failures): boot clock `2026-09-01T00:00:00Z` ×1, `/mint` prefix, `/_clock/set_current_utc` ×2 (incl. "intentionally mounted outside the `/mint` prefix"), pagination "defaults to 10" / "minimum of 1 and a maximum of 100", "ten-percent subscriber discount", shipping "495 cents…at most 3 units" / "895 cents…4 to 10 units" / "11 units or more", admin fee "five percent", tier bps "300…T1, 450…T2, 625…T3", brackets "200…under 100 troy ounces" / "100…from 100 up to but not including 500" / "zero at 500…or more", "divided by ten thousand", vault "must not exceed 50 tonnes", error rate "at least 0.02" over "30 days before the current logical-clock instant", "at least 24 hours apart", billing "already at 3 attempts", "one month"/"three months" advances.

## (e) PRD gaps and notes for Stage 2

1. **No read endpoint for Denominations or Collectors** (create-only), and no list endpoints for lots/programs/bullion-issues — blank stock is observable only via `GET /mint/reports/seigniorage` (`blanks_on_hand_pieces`). Do not invent GETs.
2. **`INSPECTION` is never persisted** — post-inspect reads show COMPLETED or REWORK only (`assert_production_run` encodes this).
3. **`planned_delivery_date` is metadata only** — drives no transition.
4. **Clock-set to the same instant is legal** (no regression) and still applies spot updates + sweeps — the `clock_regression_rejected` recipe depends on this.
5. **Scaffold/PRD divergence**: the scaffold's fed-order-cancel row says "releases their reserved blanks", but PRD §3.1 explicitly says runs in PLANNED/REWORK hold no reservations and no pieces return to stock — PRD wins; helpers assume nothing.
6. **Billing-cycle returns 201** (it creates the invoice) — the one non-obvious 201 among action endpoints; `validate_created` covers it.
7. **Inspect-PASS `good_pieces` out of range is plain `ERR_INVALID_REQUEST` (400)**, not a domain state error.
8. **Every set_clock sweeps all four transition families** — fixtures keep release datetimes in the past only where ON_SALE is intended; tests moving the clock across `2026-10-01T14:00:00Z` will flip default `create_product` products (release default) to ON_SALE.
9. **Waitlist tie-break** is `created_at` ASC then "server receipt order" — fixtures create orders sequentially so receipt order is deterministic.
10. **Shared `collector_headers`/`bullion_dealer_headers` carry non-entity fallback ids** — usable only for 400/403/404 checks; any ownership-gated call must use the per-instance builders (canonical-bug guard from the spec is encoded in fixture identity threading).

**Orchestrator verification (independent)**: all 10 files present; `pytest --collect-only` exits clean with 0 items; `importlib.import_module('test_helpers.api_client')` yields the module with `ApiClient`, while `from test_helpers import api_client` yields the `ApiClient` *instance* (package-level shadowing — Step 7 prompt must warn about this); zero "scaffold" mentions in helpers; api_client.py defines 49 functions.

## Step 5b-1: Difficulty-Queue Tests — 2026-10-02T21:25:00.000Z

Audit is fully clean. All work is complete — here is the exit summary.

**(a) Tests emitted per rule (25 total, 0 skips):**

| File | Tests |
|---|---|
| test_difficulty_dual_variant_calc.py | 2 |
| test_difficulty_combinatorial_formula.py | 3 |
| test_difficulty_non_linear_state_machine.py | 3 |
| test_difficulty_transitive_cascade.py | 2 |
| test_difficulty_priority_pair_validation_conflict.py | 3 |
| test_difficulty_boundary_precision_check.py | 3 |
| test_difficulty_cross_entity_state_dependency.py | 3 |
| test_difficulty_resource_temporal_overlap.py | 3 |
| test_difficulty_compensating_invariant.py | 3 |

**(b) Skipped instances: none.** All 25 instances passed the PRD-first two-condition filter. Notably, the three `priority_pair_validation_conflict` instances survived the filter despite the `validation-priority` silence pattern, because PRD §2.7 is *not* silent: it states the fixed ladder ("the earliest rung that fails produces the response, and later rungs are never consulted") and pins each asserted error to its rung (rung 5 `ERR_RUN_NOT_STARTABLE`, rung 6 `ERR_UNKNOWN_PROGRAM`/`ERR_AP_NOT_APPROVED`, rung 8 `ERR_RELEASE_GAP_VIOLATION`, rung 10 `ERR_BLANKS_INSUFFICIENT`/`ERR_POOL_INSUFFICIENT`), making the winner uniquely derivable.

**(c) `pytest --collect-only -q`: 25 tests collected, zero import errors.**

**(d) AST tag audit output:**
- Per-file counts: 3/3/3/3/2/3/3/3/2 = **TOTAL TAGS: 25**
- DUPLICATES: none
- UNRESOLVED (not in difficulty yaml): none — every tag resolves to a real `name:` in SCAFFOLD_DIFFICULTY_DESIGN.yaml
- INDEX INSTANCES WITH NO TEST: none (index holds 25 active instances; the YAML header comment "22 instances" is stale — orchestrator's count of 25 is what the YAML actually contains)
- Every docstring ends with its `Design: Difficulty/<rule_id>/<instance>` tag (terminal-tag check passed)
- **C1 verbatim-quote check: 0 failures** — every quoted PRD sentence in every docstring survives whitespace-normalized literal match against PRD.md

**(e) Helper-API friction (report only, no helper changes made):**
- None blocking. Everything needed existed: `setup_circulating_base` matched the canonical QUARTER/10t-hedged-lot recipe exactly; `create_allocation_offer` threads the OCC issue version automatically; `add_months` covers the `next_billing_date` expectation; calculators (`realized_unit_blank_cost_cents`, `realized_seigniorage_cents`, `subscription_invoice_amount_cents`, `program_net_proceeds_cents`, `bullion_total_price_cents`) reproduced every design literal (cross-checked: 19.0/1900000.0/5.11/1789000.0/18487/760000/13312500/128750000).
- Minor note: `test_difficulty_cross_entity_state_dependency.py` has two separate `from test_helpers.factories import ...` lines (cosmetic only; collection is clean).

**Process notes:** no server started, no live tests run (collection-only as instructed), no processes killed, `test_helpers/` and `conftest.py` untouched. Clock discipline: every `set_clock` sequence is monotonic from the 2026-09-01T00:00:00Z boot default, with spot prices passed in the same payload as the clock set, and the two-step sweep used where recipes straddle release/window instants.

## Step 5b-2: Corner entities + state_machines Tests — 2026-10-02T21:40:00.000Z

Done. Exit summary:

## (a) Tests emitted per file — 44 total, 0 skips
| File | Tests | Queue section |
|---|---|---|
| `test_suite/test_corner_entities.py` | 9 | entities (all) |
| `test_corner_sm_circulating.py` | 7 | SM: fed order ×3, production run ×3, metal lot ×1 |
| `test_corner_sm_program_product.py` | 8 | SM: commemorative program ×4 (incl. DESIGN_REVIEW self-loop, window sweeps, both disbursement gates), product orderability ×2, withdraw gate + cascade ×2 |
| `test_corner_sm_order_subscription.py` | 9 | SM: order double-pay/double-cancel, subscription enrollment gates ×2, cancel-from-DUNNING, billing gates ×2, invoice attempt-boundary write-off + post-PAID lockdown |
| `test_corner_sm_bullion_errorcoin.py` | 11 | SM: AP suspend↔reinstate + TERMINATED lockdown, allocation expiry field/sweep/confirm/settle/ownership ×4, error-coin create bound + destruction SoD ×2 + success + double-destroy |

## (b) Skipped instances — none
All 44 active instances passed the PRD-first two-condition filter; every asserted rule has a verbatim rule-bearing PRD sentence that uniquely determines the outcome. The 2 `excluded_because` stubs (`order_waitlisted_payment_rejected` → `order_payment_and_allocation_dimensions_evolve_independently`; `product_sold_out_flip_at_exact_mintage` → `order_cancel_releases_units_and_promotes_waitlist`) were NOT translated; both difficulty-instance pointers resolve at SCAFFOLD_DIFFICULTY_DESIGN.yaml lines 317 and 494.

## (c) Collection
`python3 -m pytest test_suite --collect-only -q` → **69 tests collected** (25 existing difficulty + 44 emitted), zero import errors.

## (d) AST tag audit output
```
per-file test/tag counts:
  test_corner_entities.py: 9
  test_corner_sm_circulating.py: 7
  test_corner_sm_program_product.py: 8
  test_corner_sm_order_subscription.py: 9
  test_corner_sm_bullion_errorcoin.py: 11
total tags: 44 | expected: 44
duplicates: none
unresolved to active instance: none
tags pointing at stubs: none
active instances with NO tag: none
problems: none
```
Additionally, the C1 verbatim pass: every `PRD §x.y: "..."` docstring citation (whitespace-normalized) greps literally in PRD.md — 0 misses. Every docstring's last line is its single `Design: Corner/<section>/<name>` tag.

## (e) Helper-API friction (report only, nothing modified)
- No read endpoint exists for `Denomination` or `AuthorizedPurchaser`; post-state assertions there rely on the create/action response bodies (sufficient for all queued instances — the recipes were written accordingly).
- `test_helpers/fixtures.py` has no bare `get_program`; tests call `api.get_program(...)` + `validate_success` directly (same pattern fixtures use internally).
- `run_billing_cycle`/`pay_invoice` fixtures use lenient `get_success_data`, so expected-error triggers correctly go through the raw client (`api.run_billing_cycle`, `api.pay_invoice`) + `validate_error` — worked without friction.
- `create_collector_payload(email=None)` cleanly drops the key for the required-field test, as documented.
- `make_headers` + `test_helpers.test_users.PROGRAM_MANAGER_USER_ID` cover the cross-role same-id SoD case; the stable-ID constants are not re-exported by `test_helpers/__init__.py`, so they were imported from the submodule per the import-discipline rule.

## Step 5b-3: Corner calculations + validations Tests — 2026-10-02T21:55:00.000Z

Done. Both files are written, collection passes, and the tag audit is clean.

**(a) Tests emitted per file** — 21 total (22 queue instances − 1 documented skip):
- `test_suite/test_corner_calculations.py` — 9 tests (all 9 active `calculations` instances)
- `test_suite/test_corner_validations.py` — 12 tests (12 of 13 active `validations` instances)
- The 3 `excluded_because` stubs in `calculations` (`program_net_proceeds_admin_fee_constant`, `metal_exposure_hedged_lot_excluded`, `household_limit_aggregates_across_collectors`) were left untranslated, per contract.

**(b) Skipped instance + PRD-silence pattern**:
- `validations/run_create_unknown_fed_order_not_found` — scaffold asserts a body `fed_order_id` that resolves to nothing → 404 `ERR_NOT_FOUND`. The PRD scopes `ERR_NOT_FOUND` strictly to URL-path ids (§2.7 rung 4: "every id in the URL path resolves to an existing resource... (`ERR_NOT_FOUND`, 404)"), and the rung-6 referential list never names `fed_order_id`. Worse, the only rule-bearing PRD sentence for this chain — §3.3 "a run whose order's denomination cannot be resolved is rejected with `ERR_UNKNOWN_DENOMINATION` (422)" — points at the *other* outcome. Two PRD-only readers diverge (404 `ERR_NOT_FOUND` vs 422 `ERR_UNKNOWN_DENOMINATION`); fails unique derivability. Silence pattern: **referential-integrity error-id for a body FK not PRD-pinned** (scaffold-only error binding).

**(c) `pytest --collect-only -q`**: **90 tests collected, 0 errors** = 69 existing + 21 new. No live server was started.

**(d) AST tag audit** (over only my two files): 21 `Design:` tags found; every tag resolves to an active instance in `calculations`/`validations`; no duplicates; no stub tagged; the only active instance without a test is the documented skip. `AUDIT PASS`.

**(e) Helper-API friction** (report only, nothing modified under `test_helpers/`):
- None blocking. Notes: `setup_quarantined_case(api)` defaults (200/10000/9800) matched the error-rate recipes exactly; `create_allocation_offer`'s `offerer_headers` param cleanly expressed the pm-9 SoD setup; `GenericApiClient._request` maps `headers=None` to `{}`, which made the 401 no-headers test expressible as `api.list_products(headers=None)`; `NON_EXISTENT_UUID` equals the recipe's all-zeros UUID verbatim.
- Minor: `setup_subscription` builds product+collector+subscription per call, so the two-subscription shipping-tier recipe was realized as two independent subscription products — semantically identical for the per-cycle amount assertion (tier depends only on `units_per_cycle` and `price_cents`).

## Step 5b-4: Corner endpoints + rbac + cross_cutting + consistency Tests — 2026-10-02T22:05:00.000Z

All verification gates pass. Exit summary:

**(a) Tests emitted per file (17 total, 0 skips):**
- `test_suite/test_corner_endpoints.py` — 4 tests: `response_envelope_success_shape`, `response_envelope_error_shape`, `list_pagination_envelope_and_offset`, `orders_list_filter_by_product`
- `test_suite/test_corner_rbac.py` — 9 tests: `collector_cannot_create_products`, `quality_inspector_cannot_certify_destruction`, `program_manager_cannot_disburse_surcharges`, `fedliaison_cannot_start_production_run`, `collector_cannot_run_billing_cycle`, `bullion_dealer_cannot_create_allocation_offer`, `collector_reading_others_order_forbidden`, `collector_listing_with_foreign_collector_filter_forbidden`, `allocation_confirm_while_ap_suspended_rejected`
- `test_suite/test_corner_cross_cutting.py` — 3 tests: `occ_allocation_offer_stale_version_rejected`, `occ_billing_cycle_stale_version_rejected`, `product_release_auto_opens_at_release_datetime`
- `test_suite/test_corner_consistency.py` — 1 test: `immediate_read_after_write_consistency`

**(b) Skipped instances:** none. All 17 active instances passed the PRD-first two-condition filter — every asserted rule (error_id + HTTP status, envelope shape, pagination semantics, OCC behavior, role/ownership gates, sweep inclusivity, read-after-write visibility) is stated as a verbatim PRD sentence that uniquely determines the outcome. The 3 `excluded_because:` stubs (`report_seigniorage_computed_read`, `cascading_side_effects_layer`, `dual_variant_calculation_layer`) were not translated, per contract. Two judgment calls worth noting: `occ_billing_cycle_stale_version_rejected` asserts `ERR_STALE_VERSION` over a simultaneously-true `ERR_BILLING_NOT_DUE`, which is derivable only because PRD §2.7 explicitly pins the ladder order (rung 5 OCC before rung 8 temporal) — covered, not a `validation-priority` skip. For `immediate_read_after_write_consistency`, the instance's "updated_at is refreshed" was translated as version advancing by exactly 1 plus the immediate GET echoing the pay response's `updated_at` — asserting a *later* timestamp is not uniquely derivable under a logical-clock implementation (same instant renders equal), so no inequality was asserted.

**(c) `pytest --collect-only -q`:** **107 tests collected, 0 import errors** (90 existing + 17 new).

**(d) AST tag audit output:**
```
Active instance counts (orchestrator claims 4/9/3/1): {'endpoints': 4, 'rbac': 9, 'cross_cutting_layers': 3, 'consistency_model': 1}
Stub counts (claims 1/0/2/0): {'endpoints': 1, 'rbac': 0, 'cross_cutting_layers': 2, 'consistency_model': 0}
test_suite/test_corner_endpoints.py: 4 tests
test_suite/test_corner_rbac.py: 9 tests
test_suite/test_corner_cross_cutting.py: 3 tests
test_suite/test_corner_consistency.py: 1 tests
Total tags: 17
Unresolved tags: none
Tags pointing at stubs: none
Duplicate tags: none
Active instances missing a test: none
Tags outside my four sections: none
AUDIT: PASS
```
A separate C1 sweep confirmed all 47 quoted docstring spans grep verbatim in PRD.md (whitespace-normalized), and no skip/skipif/xfail markers exist in any of the four files.

**(e) Helper-API friction (report only):** minor — `validate_success`/`validate_created` return only `data`, so envelope-level assertions (`meta.api_request_id` prefix, `response_type`, error-`meta` key set) require a raw `resp.json()` read alongside the validators; no helper changes were made (frozen). Everything else — `set_clock` with spot prices, `setup_quarantined_case`, `setup_billed_subscription` (returns the post-cycle version-2 subscription, so the stale version is `subscription["version"] - 1`), `create_allocation_offer` returning `(allocation, refreshed_issue)` — mapped cleanly onto the recipes. No servers started, no frozen files touched.

**Orchestrator full-suite AST audit (independent, all 14 test files)**: 107 tests, 107 tags, no duplicates, no unresolved tags, no tags pointing at stubs; every active difficulty instance has a test; the single corner instance without a test is the documented skip `validations/run_create_unknown_fed_order_not_found`. **Step 5 complete: 107 tests = 108 active instances − 1 PRD-silence skip.**

## Step 6: Generate Implementation — 2026-10-02T23:15:00.000Z

All checks pass and the smoke server is torn down cleanly. Here is the final report.

## (a) Files written — `workspace/implementation/` (all ≤600 lines)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 9 | Guarded install (no-op when Flask present) + `exec python3 app.py` |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 60 | Bootstrap, blueprint registration, envelope-ized 404/405/500 handlers |
| `errors.py` | 9 | `ApiError(error_id, http_status, message)` |
| `store.py` | 154 | In-memory dicts, logical clock (boot `2026-09-01T00:00:00Z`, no spots), dashed UUIDs, the two timestamp rendering families, month arithmetic |
| `helpers.py` | 233 | Envelope, 12-role auth, limit/offset pagination [1,100]/default 10, shape validators |
| `serialize.py` | 258 | Per-entity serializers + live computed fields (program financials, allocated/remaining units, derived order status) |
| `routes_clock.py` | 112 | Unprefixed `POST /_clock/set_current_utc`, spot-price key-merge, the four sweep families |
| `routes_denominations.py` | 153 | Denominations + Fed orders + FULFILLED/SHORTFALL auto-transitions + realized seigniorage |
| `routes_lots.py` | 113 | Lots + receive with 50t/day vault cap |
| `routes_runs.py` | 222 | Runs: press-window half-open overlap, start (quality gate → blanks), inspect, cancel |
| `routes_errorcoins.py` | 86 | Cases + two-person destruction |
| `routes_programs.py` | 111 | Programs + decide-design self-loop + disbursement |
| `routes_products.py` | 146 | Products: 24h family gap, mintage ceiling, withdraw cascade |
| `routes_orders.py` | 219 | Collector registration, orders, household limit, waterfall, head-of-line waitlist promotion |
| `routes_subscriptions.py` | 231 | Enrollment, OCC billing cycle, invoice dunning ladder |
| `routes_bullion.py` | 269 | Issues, APs, allocations (OCC offer, tiered-premium confirm, SoD settle) |
| `routes_reports.py` | 92 | seigniorage + metal-exposure (both variants) |

## (b) Endpoints: **48 total** — 47 under `/mint` + the unprefixed `POST /_clock/set_current_utc`. Matches the scaffold table exactly (no GET list endpoints were invented for denominations/orders/lots/programs/collectors/issues/APs, which the table omits).

## (c) `python3 -m py_compile` — all .py files pass. One real bug was caught by the smoke test (`try_datetime` not imported in `routes_products.py`) and fixed.

## (d) Smoke test (server booted via `bash start.sh` on dynamic port 59555, `$PORT` honored, `0.0.0.0`, foreground): clock+spot set → denomination → fed order (snapshot 20000) → lot → receive (realized 4,000,000; stock 500,000) → run → start (reserved 1,000) → collector → product → clock re-set releases product → order ALLOCATED → pay COMPLETED → both reports 200. Also verified: invoice math (1999×0.9→1799/unit ×2 + 495 = **4093**), OCC 412, BILLING_NOT_DUE 422, dunning ACTIVE↔DUNNING and NOT_PAYABLE; FULFILLED with realized = 500×15.25 = **7625** and SHORTFALL_RECORDED at 950/1000; quality-gate breach at 50/1000; same-sweep program-open+product-release; waitlist promotion on cancel; ownership 403s; household limit equality-then-fail; offer expiry restores pool (ACTIVE 40) and confirm-after-expiry 422; premium pricing 50×2.0oz×3000×1.0725 = **321,750**; SOLD_OUT flip after confirm; disbursement min(10000, 1500) = 1500 with SoD 422. Server PID 3109242 killed by exact PID; port verified free; pid file removed.

## (e) INTERPRETATIONS CHOSEN (numbered; PRD-admits-two-readings sites)

1. **System timestamps read the logical clock** (never wall-clock), rendered with exactly 3 fractional digits; domain datetimes render verbatim as supplied (raw strings kept); computed `offer_expires_at` renders in the clock's own precision.
2. **Naive ISO datetimes are treated as UTC**, not rejected.
3. **Body-FK misses with no dedicated catalog error** (`fed_order_id`, `production_run_id`) → **404 ERR_NOT_FOUND**; unknown `report_type` → 404; unknown report `variant` → 400.
4. **Clock set to an equal instant is allowed** (only "earlier" regresses); sweeps re-run idempotently; unknown `spot_prices` keys accepted (integer values enforced), absent keys untouched.
5. **Sweep order**: program-open → product-release → program-close → offer-expiry; a clock jump past both window bounds moves a program APPROVED_FOR_SALE→ON_SALE→SALES_CLOSED in one sweep (version +2), releasing its due products in the same sweep (PRD §3.5).
6. **Product release happens only at clock-set sweeps** — a product created with `release_datetime` already in the past stays SCHEDULED until the next clock set (trigger is "evaluated on POST /_clock/set_current_utc").
7. **No order gate on program status** — products of a SALES_CLOSED program remain orderable while ON_SALE/SOLD_OUT (the gate names only product state).
8. **Run creation is not gated on order state** (only run *start* is); SUBMITTED→SCHEDULED fires only when the order is SUBMITTED at run creation.
9. **PASS-after-REWORK accumulates scrap** (`scrapped += reserved − good`, not overwrite) so the §2.9 blank-stock invariant holds; "pieces already scrapped stay scrapped" supported this over the scaffold's literal "becomes".
10. **Quality gate**: window `[now−30d, now]` inclusive on `case.created_at` and an internal last-inspection instant (set on PASS and FAIL); exact rational compare `50·error_pieces >= struck`, only when struck > 0.
11. **OCC fields**: present-and-mismatched (incl. non-int) → 412 at rung 5; absent → 400 at rung 9. Billing-cycle order: ACTIVE(422) → OCC(412) → BILLING_NOT_DUE(422) → shape(400). Allocation-offer order: 404 → OCC(412) → AP_NOT_APPROVED(422) → shape/quantity(400) → POOL_INSUFFICIENT(422); no issue-state gate (SOLD_OUT fails via pool==0 as PRD states).
12. **ERR_QUANTITY_INVALID (400)** for ≤0 on: quantity_ordered_pieces (PRD §3.1 pins it even though the scaffold's applies_to omits fed-orders — PRD wins), quantity_tonnes, planned_quantity, order quantity, units_per_cycle, quantity_units, and error_pieces' lower bound (upper bound is ERR_ERRORCOIN_QUANTITY_EXCEEDS).
13. **ERR_INVALID_REQUEST (400)** for the other numeric bounds (face_value_cents<1; program max_mintage/surcharge/cap/costs; product price/mintage/household ≤0; issue weight/pool/window ≤0), because the scaffold's QUANTITY_INVALID applies_to omits those endpoints.
14. **Malformed program sales window → 400 ERR_INVALID_REQUEST** (PRD-pinned); malformed press window (end ≤ start) → 409 ERR_PRESS_WINDOW_OVERLAP (PRD §3.3-pinned), evaluated at rung 8 when both datetimes parse.
15. **decide-design**: state gate before `decision` validation (non-DESIGN_REVIEW → 422 fallback; bad decision in DESIGN_REVIEW → 400). **AP set-status**: any (from,to) pair outside the declared set → 422 ERR_INVALID_STATE_TRANSITION, including unknown to_status values and same-state requests; missing to_status → 400.
16. **Collector list endpoints are implicitly scoped to the caller's own records** (PRD §2.1 "read only own"), and a `collector_id` filter naming another id → 403. BullionDealer reads are not ownership-scoped (only confirm is).
17. **Unregistered Collector may place orders/subscriptions** — no catalog error exists for an unknown collector; household aggregation then sees an empty household. Payload `collector_id` is rejected as undeclared (server sets it from X-User-ID).
18. **Household limit counts every non-CANCELLED order** (WAITLISTED included, allocation_status != RELEASED) across the household; equality allowed.
19. **Undeclared/read-only body fields → 400 on every endpoint**, evaluated at rung 9 (after state/SoD on action endpoints). `good_pieces` on outcome=FAIL is accepted and ignored.
20. **Invoice attempts** increment before outcome handling; the 3rd recorded FAILED attempt writes off + CANCELS_NONPAYMENT; SUCCEEDED from FAILED at attempts<3 is allowed and lifts DUNNING→ACTIVE; invoice version bumps per attempt.
21. **`disbursed_cents` initializes to 0** (absent from §2.5's nullable list); `description`/optional fields serialize as null when omitted; explicit JSON null on optional fields treated as omitted.
22. **Run serialization includes inherited `denomination_code`** (the run list filters on it).
23. **Seigniorage report**: one row per denomination (sorted by code); `fiscal_year` narrows the budgeted/realized order sums while blank figures stay denomination-wide; `denomination_code` narrows rows. **Metal-exposure**: rows only for commodities with exposed (unhedged, ORDERED/DELIVERED) lots, sorted; negative exposures allowed.
24. **Pagination**: non-integer or negative `offset` → 400 (PRD pins only limit bounds); `has_more = offset + returned < total_count`; unknown filter values yield empty pages rather than 400.
25. **Program mintage ceiling counts all products of the program including WITHDRAWN** (no status carve-out, unlike the release-gap rule which excludes WITHDRAWN explicitly); equality allowed.
26. **Issue flips**: ACTIVE→SOLD_OUT re-checked after offer/confirm/settle (requires pool==0 AND zero OFFERED); SOLD_OUT→ACTIVE only via the expiry sweep, one version bump per expired allocation.
27. **No guards added beyond the PRD**: no blank release on cancel-from-PLANNED/REWORK, no billing-cycle product-state check, no spot-price deletion, no extra state gates on creation endpoints.

`start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, stays foreground via `exec`, and the pip install is guarded so per-test reboots are no-ops. Boot state is empty (clock default only); no seed data anywhere.

**Orchestrator verification (independent)**: 17 .py files + start.sh + requirements.txt present, all compile; `store.py:85` returns `str(uuid.uuid4())` (dashed, with an explicit never-`.hex` comment); start.sh is guarded + foreground `exec`; no seed/fixture code in any .py; 2468 total lines.

## Step 7: Test-Fix Iteration Loop — 2026-10-02T23:45:00.000Z

Clean sweep: all 8 rounds pass 107/107. The `results.*.json` files remain in `workspace/implementation/` per the output contract.

**Iterations run:** 2 (initial sweep: 104/107 in all 8 rounds, same 3 failures; post-fix sweep: 107/107 × 8 rounds, zero flakes).

**Tests deleted:** none.

**Fixes applied to test_suite/:**
- `test_suite/test_corner_calculations.py` — `test_error_rate_exactly_two_percent_breaches`, `test_error_rate_just_below_threshold_passes`, `test_error_rate_rolling_window_excludes_old_cases`: the setup completed run1 as the order's only run with fulfilled (9800) < ordered (50000), which per PRD §3.1 auto-transitions the order to terminal `SHORTFALL_RECORDED`; PRD §3.3 then requires any further run start to fail with `ERR_RUN_NOT_STARTABLE`, making the quality-gate assertion unreachable under a PRD-faithful impl. Replaced `setup_quarantined_case` with a new local helper `_setup_case_with_pending_run` that schedules run2 *before* run1's inspection resolves (order stays `FULFILLING` since not all linked runs are terminal), with run2's press window moved to 13:00–15:00 so it can't overlap run1's 08:00–12:00 window while run1 is non-terminal. Also used `validate_created` (201) for the error-case create instead of `validate_success` (200).

**Fixes applied to test_helpers/:** none — the shared `setup_quarantined_case` fixture is used by other passing tests whose assertions don't require a subsequent run start, so it was left untouched.

**Fixes applied to implementation/:** none — the implementation's behavior (state gate `ERR_RUN_NOT_STARTABLE` before the quality gate; `SHORTFALL_RECORDED` on all-runs-terminal shortfall) was verified verbatim against PRD §3.1 and §3.3 and is correct.

**Orchestrator verification (independent)**: all 8 `results.{i}.json` files present, each `passed: 107, total: 107, failed: 0`; implementation .py mtimes unchanged since Step 6 (newest 23:14, the smoke-test fix); the claimed `_setup_case_with_pending_run` helper exists in test_corner_calculations.py:51 with 3 call sites (229, 251, 275). Step 7 had 0 implementation/ fixes and 0 test_helpers/ fixes; the 3 test_suite/ fixes are pure fixture-ordering bugs (the asserted quality-gate path was unreachable under the PRD's own terminal-state rule).

## Step 8: Finalize PRD — 2026-10-02T23:55:00.000Z

Step 8 complete. Zero-edit outcome — PRD_FINALIZED.md is byte-identical to PRD.md.

**Line counts / %-delta:** PRD.md 323 lines, PRD_FINALIZED.md 323 lines — 0% delta (zero edits).

**Per-item investigation** (all three items are in `test_suite/test_corner_calculations.py` and share the same two PRD behaviors plus one endpoint-semantics behavior):

- **§3.1 (order auto-transition) — no-edit** — PRD already pins SHORTFALL_RECORDED on all-runs-terminal shortfall, so the original fixture (run1 the order's only run, fulfilled 9800 < ordered 50000) was PRD-illegal, not the impl. Evidence: PRD line 137 "If instead every linked run of a `SCHEDULED` or `FULFILLING` order has reached a terminal state — `COMPLETED` or `CANCELLED`, with at least one linked run existing — and the fulfilled count still falls short of the ordered quantity, the order auto-transitions to `SHORTFALL_RECORDED`, again incrementing `version`" (plus §3.3 lines 155 and 157, and line 139 "`FULFILLED`, `SHORTFALL_RECORDED`, and `CANCELLED` are the order's terminal states"). Impl: `routes_denominations.py:35-48` (`advance_order_after_run_change`: guards on SCHEDULED/FULFILLING, fulfilled≥ordered → FULFILLED with realized seigniorage, else all-runs-terminal → SHORTFALL_RECORDED with `store.bump`), invoked from `routes_runs.py:198` (inspect PASS) and `routes_runs.py:221` (run cancel).
- **§3.3 (run-start state gate) — no-edit** — PRD already pins ERR_RUN_NOT_STARTABLE when the parent order is not SCHEDULED/FULFILLING, and §2.7's ladder (rung 5 state < rung 7 quality < rung 10 blanks) pins the gate ordering the tests rely on. Evidence: PRD line 153 "The linked order must be in `SCHEDULED` or `FULFILLING`; starting a run that is not in `PLANNED` or `REWORK`, or whose order sits in any other state, is rejected with `ERR_RUN_NOT_STARTABLE` (422)"; §2.7 line 98 "the earliest rung that fails produces the response, and later rungs are never consulted". Impl: `routes_runs.py:148-151` (state gate) precedes `:154` (quality gate) precedes `:158` (blanks gate) — exact ladder order.
- **§4 (201 on error-case creation) — no-edit** — PRD already pins 201 for error-coin-case creation, so the fix's switch to `validate_created` matches impl and PRD alike. Evidence: PRD line 219 "Resource-creating operations — … and error-coin cases — respond 201 on success and return the created resource". Impl: `routes_errorcoins.py:42` `return envelope(serialize.error_case(case), status=201)`; sweep of all 14 create endpoints (`grep status=201`) shows uniform 201, consistent with the §4 sentence.

**Per-decision pre-edit search log:**
1. Subject: order auto-transition on run terminality. Paths enumerated/read: `routes_denominations.py` (full), `routes_runs.py` (full), `store.py` (full); greps `SHORTFALL_RECORDED|advance_order_after_run_change` and `FULFILLED` across `implementation/` — every run→terminal path (inspect PASS, run cancel) calls the helper; the fed-order cancel cascade needs none (order itself goes CANCELLED per §3.1). Wording adjustment: none — PRD text already exact.
2. Subject: run-start gate. Paths: `routes_runs.py:142-169` (only start endpoint), `errors.py`/catalog cross-check via grep `ERR_RUN_NOT_STARTABLE` (single raise site). Wording adjustment: none.
3. Subject: create-response statuses. Paths: `grep -rn "status=201"` over all `routes_*.py` (14/14 creates) plus `test_helpers/assertions.py:75` (`validate_created` = 201) and `api_client.py:212` as auxiliary test-side evidence. Wording adjustment: none.

**`diff -q` result:** `PRD.md PRD_FINALIZED.md` — no output, files are byte-identical (confirmed "BYTE-IDENTICAL").

Output file: `workspace/PRD_FINALIZED.md`

**Orchestrator verification (independent)**: `diff -q PRD.md PRD_FINALIZED.md` confirms byte-identical (both 323 lines). Zero-edit outcome consistent with the fixture-only Step 7 diff.

## Step 9: PRD Completeness Scan — 2026-10-03T00:25:00.000Z

All 16 edits landed exactly where intended — pure in-place line revisions, no structural change. Here is the final report.

**File:** `workspace/PRD_COMPLETED.md`
**Source vs. output:** PRD_FINALIZED.md 323 lines / 58,434 chars → PRD_COMPLETED.md 323 lines / 62,615 chars (**+4,181 chars, 16 in-place paragraph edits, no lines added or removed**).

**Counts:** 15 ambiguity-pin edits + 1 mismatch-revision edit (the §3.3 inspection edit also carries one ambiguity pin) = **16 ambiguity-pins, 1 mismatch-revision, 2 impl-bugs-reported**.

### Changes (one bullet per edit)

- §2.3 — insert — ambiguity — pins non-integer `limit`/`offset` and negative `offset` → 400, `has_more` = offset + returned < total_count, `created_at` ties break by server receipt order, unknown filter values yield empty pages — implementation/helpers.py:83-110, store.py:140-142
- §2.4 — insert — ambiguity — unknown `spot_prices` keys accepted and stored; equal-instant clock set allowed, sweeps idempotent — routes_clock.py:84, 92-101
- §2.5 — insert — ambiguity — computed `offer_expires_at` renders in the clock's current fractional precision; naive ISO datetimes read as UTC — store.py:27-29, 108-120, routes_bullion.py:178
- §2.6 — insert — ambiguity — state precondition before OCC within rung 5; non-integer/mismatched expected version → 412, omitted field → 400 at rung 9 — routes_subscriptions.py:133-149, routes_bullion.py:140-157
- §2.7 rung 4 — insert — ambiguity — unknown `report_type` → 404; unresolvable body `fed_order_id`/`production_run_id` → 404 (not a rung-6 error) — routes_reports.py:19-20, routes_runs.py:29-32+54-55, routes_errorcoins.py:17-25
- §2.7 rung 9 — insert — ambiguity — `ERR_QUANTITY_INVALID` scoped to the seven named quantity fields; all other numeric bounds (face_value, program/product/issue bounds) → `ERR_INVALID_REQUEST`; explicit JSON null treated as omitted — helpers.py:139-141, routes_programs.py:24-35, routes_products.py:59-67, routes_bullion.py:52-59
- §2.9 — insert — ambiguity — report response shape `{report_type, rows}`, no pagination, seigniorage rows sorted by code with `fiscal_year` narrowing sums only, exposure rows sorted by commodity, non-integer `fiscal_year` → 400, unknown `variant` → 400 — routes_reports.py:25-26, 29-92
- §3.3 — insert — ambiguity — run creation not gated on order state (only start is); inherited `denomination_code` carried on the run's serialized form — routes_runs.py:84-87, serialize.py:81-95
- §3.3 — insert — ambiguity — quality-gate window inclusive; a run counts via its *most recent* inspection in-window, contributing current produced+scrapped totals — routes_runs.py:120-139, 182
- §3.3 — **revise — mismatch** — PASS now reads "scrapped_pieces **grows by** the reserved count minus the good pieces" (was "becomes"); justification: the literal "becomes" contradicts §2.9's blank-stock invariant and the FAIL paragraph's own "grows by" for PASS-after-REWORK, so the invariant-consistent reading impl adopted is pinned — routes_runs.py:191. Same edit pins (ambiguity): `good_pieces` with `outcome=FAIL` accepted and ignored — routes_runs.py:179, 199-205
- §3.5 — insert — ambiguity — one clock set runs open-then-close sweeps in a single pass: APPROVED_FOR_SALE→ON_SALE→SALES_CLOSED in one call (version +2), product releases evaluated mid-sweep against ON_SALE — routes_clock.py:18-46
- §3.5 — insert — ambiguity — `disbursed_cents` initializes to 0 at creation — routes_programs.py:55
- §3.6 — revise — ambiguity — program mintage ceiling sums over all products, WITHDRAWN included — routes_products.py:76-78
- §3.6 — insert — ambiguity — payload `collector_id` rejected as undeclared; unregistered Collector may order, with no household limit applied; orderability gates on product state alone (SALES_CLOSED program does not block) — routes_orders.py:88, 101-107, 84-86
- §3.7 — insert — ambiguity — enrollment: payload `collector_id` rejected; unregistered Collector may enroll — routes_subscriptions.py:36, 58
- §3.7 — insert — ambiguity — monthly/quarterly `next_billing_date` advance clamps the day to the target month's length — store.py:145-154, routes_subscriptions.py:171

### IMPL BUGS reported (PRD left unchanged at these sites)

- **8 action endpoints** — §2.7: "the earliest rung that fails produces the response, and later rungs are never consulted" — shape/undeclared-field checks (rung 9) run *before* earlier-rung gates, so a double-fault request returns 400 instead of the earlier rung's error: `POST /mint/production-runs/{id}/start` (routes_runs.py:146 before state gate :148), `POST /mint/production-runs/{id}/cancel` (routes_runs.py:213 before :214), `POST /mint/orders/{id}/cancel` (routes_orders.py:204 before :205), `POST /mint/subscriptions/{id}/cancel` (routes_subscriptions.py:118 before :119), `POST /mint/products/{id}/withdraw` (routes_products.py:128 before :131), `POST /mint/authorized-purchasers/{id}/set-status` (routes_bullion.py:117-120 before :123), `POST /mint/allocations/{id}/confirm` (routes_bullion.py:229 before rung-6 AP/spot :231-239), `POST /mint/allocations/{id}/settle` (routes_bullion.py:260 before rung-7 SoD :261). Expected e.g.: start on a COMPLETED run with an undeclared body field → 422 ERR_RUN_NOT_STARTABLE; actual: 400 ERR_INVALID_REQUEST.
- **2 action endpoints** — §2.7 rung 9: "rejection of undeclared or read-only fields (`ERR_INVALID_REQUEST`, 400)" — `POST /mint/federal-reserve-orders/{id}/cancel` (routes_denominations.py:137-153) and `POST /mint/commemorative-programs/{id}/disburse-surcharges` (routes_programs.py:96-111) never call `no_undeclared`, so a body carrying undeclared fields succeeds with 200; every other no-body action endpoint enforces the check via `no_undeclared(body(), set())`. Expected: 400; actual: 200.

### Watch-list checklist

1. Prose-only uniqueness rules — **clean**: the only uniqueness claims (denomination `code`, `product_code`, collector `email`) all have catalog error_ids and live store-scans (routes_denominations.py:67, routes_products.py:70, routes_orders.py:26); AP `name` carries no uniqueness claim in PRD.
2. Nullable-field crash paths — **clean**: all four null-until-event fields are read only where set or serialized as null; the realized-seigniorage division is unreachable with zero delivered blanks (FULFILLED ⇒ started run ⇒ stock ⇒ DELIVERED lot with positive blanks). No live-smoke required.
3. "Recording" vs "carry" — **clean**: `order_spot_cents_per_tonne`, `reported_by_user_id`, `offered_by_user_id`, `created_by_user_id`, `disbursed_cents`, `destroyed_by_user_ids` all persist and serialize.
4. Dead checks — **clean on error_ids**: all 43 §5 catalog ids have live raise sites on their PRD-assigned endpoints; but see impl bug #2 (rung-9 check absent on two endpoints).
5. Body-FK error binding — **pinned**: 404 ERR_NOT_FOUND for body `fed_order_id`/`production_run_id` and unknown `report_type` (§2.7 rung 4), 400 for unknown `variant` (§2.9).

All 27 documented interpretation pins were checked: 12 needed new prose (items 1,2,3,4,5,7,8,10,11,13,17,19,21,22,23,24,25 map into the edits above; item 9 is the mismatch-revision); the rest (6,12,14,15,16,18,20,26,27) are already uniquely implied by existing PRD text and required no change — items 15 and 19 partially map to the two impl bugs instead.

**Orchestrator adjudication + verification (independent)**: PRD_COMPLETED.md confirmed 323 lines, +4158 chars over PRD_FINALIZED.md. The mismatch-revision (§3.3 "grows by" vs "becomes") is EXONERATED: PRD self-contradiction (the literal "becomes" contradicts §2.9's blank-stock conservation invariant), so pinning the invariant-consistent reading is correct. Both IMPL BUGS spot-checked against source and CONFIRMED: (bug 1) `routes_runs.py:146` runs `no_undeclared(body(), set())` before the state gate at :148-151, and `routes_bullion.py:229` runs it between the state gate and the rung-6 AP/spot checks — both violate the PRD §2.7 earliest-rung-wins ladder; (bug 2) `cancel_fed_order` (routes_denominations.py:137-153) and `disburse_surcharges` (routes_programs.py:96-111) contain no `no_undeclared` call at all. Both are genuine impl violations of verbatim PRD sentences → Step 9b: targeted impl fix + full re-sweep; PRD_COMPLETED.md untouched (impl moves toward PRD).

## Step 9b: Impl Fix + Re-sweep — 2026-10-03T00:45:00.000Z

All work is complete. Final report:

**(a) Per-file edit list (all under `workspace/implementation/`)**

Bug 1 — `no_undeclared` moved to the rung-9 position (after all rung-5/6/7/8 gates, before rung-10/mutation):
1. `routes_runs.py` `start_run` — removed from old line 146 (before state gate); inserted at new line 157, after the `_quality_gate` (rung-7) block, immediately before the `ERR_BLANKS_INSUFFICIENT` (rung-10) check.
2. `routes_runs.py` `cancel_run` — old :213 → new :217, after the `ERR_RUN_NOT_CANCELLABLE` state gate, before `run["status"] = "CANCELLED"`.
3. `routes_orders.py` `cancel_order` — old :204 → new :206, after the `ERR_ORDER_NOT_CANCELLABLE` gate, before the RELEASED mutation.
4. `routes_subscriptions.py` `cancel_subscription` — old :118 → new :121, after the `ERR_INVALID_STATE_TRANSITION` gate, before the CANCELLED mutation.
5. `routes_products.py` `withdraw_product` — old :128 → new :133, after the `ERR_PRODUCT_NOT_WITHDRAWABLE` gate, before the order cascade.
6. `routes_bullion.py` `set_ap_status` — old :117 → new :125, after the `AP_TRANSITIONS` state gate, before `ap["status"] = to_status` (the `to_status` missing-field 400 check left in place, per minimal-edit rule).
7. `routes_bullion.py` `confirm_allocation` — old :229 → new :240, after the rung-6 AP-APPROVED and spot-price checks, before the premium/price computation.
8. `routes_bullion.py` `settle_allocation` — old :260 → new :264, after the rung-7 `ERR_SEGREGATION_OF_DUTIES` check, before the SETTLED mutation.

Bug 2 — `no_undeclared(body(), set())` added (was entirely absent):
9. `routes_denominations.py` `cancel_fed_order` — added at :144, after the `ERR_FEDORDER_NOT_CANCELLABLE` gate, before the run-cancellation cascade.
10. `routes_programs.py` `disburse_surcharges` — added at :107, after the `ERR_SEGREGATION_OF_DUTIES` check, before `serialize.program_financials(p)`.

Neighboring endpoints (`pay_order`, `billing_cycle`, `decide_design`, `offer_allocation`, `receive_lot`, creates) verified already correct and untouched. No PRD/test_suite/test_helpers files modified.

**(b) py_compile** on all 6 touched files: PY_COMPILE_OK.

**(c) Smoke transcript (dynamic port 41877, exact-PID kill, port verified free after)**
- A1 cancel SUBMITTED fed order + undeclared field → 400 ERR_INVALID_REQUEST (bug-2 single-fault)
- A2 same order, clean body → 200 (order now CANCELLED)
- A3 cancel CANCELLED order + undeclared field → 422 ERR_FEDORDER_NOT_CANCELLABLE (rung 5 beats rung 9)
- B run driven start→inspect PASS→COMPLETED, then start + undeclared field → 422 ERR_RUN_NOT_STARTABLE (pre-fix: 400)
- C confirm with SUSPENDED AP + undeclared field → 422 ERR_AP_NOT_APPROVED (rung 6 beats rung 9)
- C2 settle by the offering manager + undeclared field → 422 ERR_SEGREGATION_OF_DUTIES (rung 7 beats rung 9)
All 6 expectations OK.

**(d) 8-round stability sweep (per-test-server isolation, 120s/30s timeouts): rounds 1–8 each 107 passed / 0 failed / 107 total.** All 8 `results.*.json` files retained in `workspace/implementation/` (fresh mtimes 2026-10-03 00:30).

**(e) Anomalies:** none. No test asserted the old buggy order; no flakes observed across 856 total test executions.

**Orchestrator final verification (independent)**: all 8 `results.{i}.json` parsed — each `passed: 107, total: 107, failed: 0`; PRD_COMPLETED.md mtime 00:12 (untouched by Step 9b, per the fix-and-resweep contract); `start_run` ordering spot-checked at routes_runs.py:144-160 (state gate → quality rung 7 → `no_undeclared` rung 9 → blanks rung 10). Task tree complete per the output contract: SCAFFOLD.yaml + both design indices, worklog.md, test_helpers/ (10 files), test_suite/ (15 test files + conftest, 107 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md (byte-identical to PRD.md), PRD_COMPLETED.md, implementation/ (17 .py + start.sh + requirements.txt + results.1-8.json)}.

**PIPELINE COMPLETE — final state: 107/107 tests passing across 8 consecutive per-test-server isolation rounds (856 executions, zero flakes); 1 documented PRD-silence test skip (run_create_unknown_fed_order_not_found); 0 test deletions; 3 test-suite fixture fixes; 0 test_helpers changes; 2 implementation defects found at Step 9 and fixed at Step 9b (validation-ladder ordering on 8 endpoints + missing undeclared-field check on 2 endpoints); PRD_COMPLETED.md = PRD.md + 16 ambiguity pins + 1 adjudicated mismatch revision (+4,158 chars).**
