# Worklog — task_3432_laboratory_consumable_supply_instrument_service_contracts

## Step 1: Create Task Directory — 2026-10-02T01:21:00.000Z

Task directory pre-allocated by the caller at `tasks/task_3432_laboratory_consumable_supply_instrument_service_contracts/` with `workspace/` inside; verified existence, created nothing new.

## Step 2: Generate Scaffold — 2026-10-02T02:16:00.000Z

All three artifacts are complete and the official lint is clean. Final summary:

## Task complete — task_3432_laboratory_consumable_supply_instrument_service_contracts

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3432_laboratory_consumable_supply_instrument_service_contracts/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 plus concurrency_rules; contains neither design key
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Counts:**
- Entities: 10 | State machines: 8 | Calculations: 9 | **Endpoints: 39** (≤40 cap met) | Validation priority rows: 8 | Errors: 30 | Roles: 6 | OCC concurrency rules: 2
- §1.8: 18 instances (9 rules × 2, all non-stub) | §1.9: 47 instances (40 non-stub, 7 `excluded_because` stubs)
- `scaffold_lint.py` verdict: **clean lint** (412 calls checked, all FKs reverse-reachable). No sibling task directory was read at any point.

**Domain consolidation:** the 10 scenario sub-domains were merged into one model — a single order pipeline with item-class branching (STANDARD/COLD_CHAIN/HAZARDOUS/CONTROLLED), one service-request entity spanning break/fix, PM, app-support and method-dev, and one surge/waterfall allocation mechanism.

**Key design decisions (interpretation choices):**
1. **Logical clock** pinned at default `2026-09-01T00:00:00Z`, advanced only by `POST /lab/_clock/set_current_utc`; it drives the delivery sweep and the *derived* EA/contract statuses (EXPIRING/RENEWAL_DUE/EXPIRED are computed-at-read and never bump `version` — this keeps the two OCC renew races deterministic).
2. **Difficulty from rule depth, not surface:** depth-3 cascade (contract cancel → $24,000 termination fee → credit HOLD → DRAFT orders auto-cancelled); skip-not-block priority waterfall (scores 150/60/10, qty-5 order skipped, qty-1 allocated); per-line-then-sum rounding trap (218 vs 219); flat-band vs blended-marginal pricing trap (9000 vs 9333); pull-through dual variant (140000 vs 170000); PM quota boundary (4th free, 5th bills 37000); strictly-greater credit boundary (2,000,000 stays GOOD).
3. **Selector determinism without ids:** engineer rank = open_ticket_count ASC → created_at ASC → name ASC; loaner = created_at ASC → serial_number ASC; waterfall final tie-break = account name ASC. Two corner fixtures step the clock 1s between engineer creates so the created_at tie-break is genuinely exercised (caught during my replay pass).
4. **Validation priority order** pinned: auth → authz/ownership → existence → state → OCC(412) → business_safety → business_constraint → business_fiscal; the two priority-conflict instances exercise state-vs-safety and safety-vs-fiscal pairs.
5. All worked-example literals were executed in Python before being written into `assert:` lines (billing split 10000+127000=137000, fee 800000×6×0.5=2400000, tier boundaries inclusive at the lower floor, etc.).

Orchestrator verification: all three YAML files parse with yaml.safe_load; SCAFFOLD.yaml keys = [scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors]; endpoint count = 39; api_prefix = /lab; 288 lab/instrument/reagent domain mentions (correct domain, not foreign); design keys absent from SCAFFOLD.yaml.

## Step 3: Copy Shared Files — 2026-10-02T02:17:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T02:24:00.000Z

PRD generation complete. `workspace/PRD.md` — 301 lines, ends at §5 with no audit footer.

## Section list

- §1 Introduction (2 paragraphs: business context; the three design themes — cent-exact money/credit, explicit scarcity adjudication, logical clock)
- §2.1 Roles (`PlatformAdmin`, `AccountManager`, `LabProcurement` entity-backed to `Account`, `ServiceDispatcher`, `FieldEngineer` entity-backed to `Engineer`, `SupplyOps`; identity prose per role; `ERR_UNAUTHENTICATED`/`ERR_FORBIDDEN`)
- §2.2 API Response Structure — emitted **verbatim** from `section-2.2-response-structure.md` (including `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }`)
- §2.3 Pagination (`limit` default 10 / min 1 / max 100, `offset` default 0, `created_at` ascending, `meta` fields; all 13 list-filter query params named in backticks)
- §2.4 Logical clock (startup default exactly `2026-09-01T00:00:00Z`, never wall-clock, advanced only via the clock capability with `to_iso8601` → `current_utc`; clock-set is the sole delivery-sweep trigger; derived statuses never bump `version`/`updated_at`)
- §2.5 Common resource properties (`id` UUID no prefix, `created_at`, `updated_at`, `version` +1 per mutation incl. system-driven transitions; derived-read exemption)
- §2.6 Integer cents, whole-number percentages, round-half-up at named steps
- §2.7 OCC: only the two renewals; `expected_agreement_version` / `expected_contract_version` non-optional; mismatch → `ERR_STALE_VERSION` 412; omission → `ERR_INVALID_REQUEST`; no other endpoint takes a version field
- §2.8 Credit: `outstanding_balance_cents` starts at 0; three posting events (ship invoice, resolve invoice, termination fee); `HOLD` iff balance **strictly greater than 2000000** cents, exactly-2000000 stays `GOOD`; `GOOD`→`HOLD` cancels every `DRAFT` order with per-order `version` increments
- §2.9 Validation priority ordering, all 8 priority tiers in order with the two concrete disambiguations (state guard beats stale-version on renewals; license gate beats credit gate on submit)
- §3.1–3.8: accounts → enterprise agreements → instruments/pull-through → service contracts → field service (create/dispatch/loaner/resolve billing) → catalog & order pipeline → surge waterfall → delivery sweep
- §4: 39-row endpoint table (4 columns), matching the 39 scaffold endpoints
- §5: 30-row error catalogue (2 columns)

## Constants carried over (spot-check confirmed by grep)

All scaffold numeric literals verified present with identical values: 2026-09-01T00:00:00Z; pagination 10/1/100/0; tier floors 10000000/50000000/200000000 with inclusive-lower-edge (exactly-50000000-is-GOLD stated); discounts 0/5/10/15; windows 365 days / 60 days / 30 days / 12-month renewals; response hours 72/48/24/8 plus 72-hour no-contract default; PM visits 1/2/4/12; parts coverage 0/50/90/100 with labor 100%; monthly values 50000/120000/300000/800000; termination rate 0.5 with the worked 2027-03-01→2027-09-01 = 6 months → 2400000 example; credit line 2000000 strictly-greater; labor 18500/hour; trip charge 45000; SLA credit 10 percent round-half-up; handling fees 0/4500/7500/9500; transit days 3/1/5/4; priority weights 100/50/10; tier multipliers 2.0/1.5/1.2/1.0; engineer capacity 4/day; the pinned worked examples (60000000→9000 not 9333; two 115-cent lines → 218 not 219). Tie-break chains stated in full: dispatch (`open_ticket_count` ASC → `created_at` ASC → `name` ASC), loaner (`created_at` ASC → `serial_number` ASC), waterfall (score DESC → `submitted_at` ASC → `total_quantity` ASC → account `name` ASC).

## Contract reports

- **Contract 1 (field-name coverage):** 80 required identifiers — 80 present as exact backticked tokens, 0 missing. **PASS**
- **Contract 2 (rule coverage):** all 8 validation priorities expressed with explicit ordering prose; both OCC rules with endpoint + field + `ERR_STALE_VERSION`/412; all state transitions with from/to, preconditions paired to error ids, and side effects on both branches; all 9 calculations in reconstructible prose; all `applies_to` scopes and sibling-branch density symmetric. **PASS**
- **Contract 3 (§3 path purity):** 557 backticked tokens in §3, 0 path tokens, 0 bare-method tokens, 0 method+path tokens. **PASS**

## Scaffold shorthand expanded into prose

- `end_date += 12 months`, `renewal_count += 1`, `reserved_quantity += quantity` etc. → natural-language increment/decrement sentences throughout.
- Half-open windows and the PM gap rendered as inclusive/exclusive boundary prose.
- The early-termination "full calendar month" definition and the delivery-sweep comparison written as boundary-exact sentences.
- `band_rate_flat` vs `blended_marginal_rate` and `per_line_then_sum` vs `sum_then_round` variants rendered as pinned-reading vs explicitly-wrong-reading prose with the scaffold's own worked numbers.
- The depth-3 credit cascade written as a three-link narrative in both §2.8 and §3.4.
- One judgment call: contract creation on a non-`INSTALLED` instrument is mapped to `ERR_INVALID_STATE` (the scaffold names the requirement but no error id; this matches the sibling service-request-create guard).

Orchestrator verification: PRD.md exists at 301 lines; constant spot-check greps pass.

## Step 5a: Generate Test Helpers — 2026-10-02T02:42:00.000Z

All checks pass. Stage 1 is complete.

## Summary

**Files written** in `test_helpers/` (2079 lines total):

| File | Lines | Contents |
|---|---|---|
| `__init__.py` | 42 | Barrel export: framework generics + all PRD-specific modules |
| `types.py` | 337 | 18 enums + 11 TypedDicts; all 10 entities carry `id`/`created_at`/`updated_at`/`version` |
| `constants.py` | 94 | All PRD literals: tier floors, discount map, handling fees, transit days, priority weights, tier multipliers, response hours, PM quotas, parts coverage, monthly values, ETF rate 0.5, credit limit 2000000, capacity 4, PM gap 30d, renewal windows 60/30d, 365d trailing, clock start 2026-09-01T00:00:00Z, `round_half_up` helper |
| `api_errors.py` | 93 | `ApiErrorId` enum (30 ids) + `HTTP_STATUS_CODES` map |
| `api_client.py` | 285 | `ApiClient(GenericApiClient)` with one method per endpoint (33 total incl. `set_clock`), instant normalizers, singleton |
| `test_users.py` | 118 | `TEST_USERS` dict, opaque constants for 4 operator roles, entity-backed header builders for LabProcurement/FieldEngineer, malformed-auth sets |
| `factories.py` | 184 | Payload builders per entity with counter-stamped sku/serial uniqueness |
| `assertions.py` | 312 | `assert_{entity}` per entity + entitlement table check, `assert_stock_invariant`, `assert_order_pricing_invariant`, `assert_billing_split_invariant`, `assert_pull_through_projection` |
| `fixtures.py` | 614 | Composite builders |

**Constant-grep confirmation**: every literal in constants.py greps verbatim in `workspace/PRD.md`.

**Verification**: AST parse OK (9 files); real import check OK (`import test_helpers` + 50 named imports, 43 public ApiClient methods); pyflakes clean apart from expected re-export warnings; zero "scaffold" references in comments.

**Key fixture entry points for Stage 2**: create_account/suspend_account/close_account; create_catalog_item; create_engineer/ensure_engineer/create_engineers_staggered (created_at tie-break control); create_instrument/create_installed_instrument; create_service_contract/setup_instrument_with_contract; create_enterprise_agreement/renew/terminate; create_order/submit_order/create_allocated_order/create_shipped_order/create_delivered_order; deliver_order (clock-derived); seed_delivered_spend/setup_account_with_trailing_spend/setup_account_with_agreement/ship_order_total/push_account_to_credit_hold; create_service_request/dispatch_request/resolve_request and composites; create_pm_request/resolve_pm_visit/setup_pm_quota_scenario; setup_loaner_scenario/reserve_loaner; create_surge_event/resolve_surge_event/create_backordered_order; set_clock/plus_seconds/plus_days/plus_months.

**Drift flag for Stage 2** (PRD-first adjudication needed): the difficulty-design instances assume tier floors at 50000/200000 cents (SILVER/GOLD) — PRD §3.2 pins 10000000/50000000/200000000, and constants.py carries the PRD values. Consequence: seeding SILVER+ trailing spend (>= 10000000) requires shipping invoices above the 2000000 credit line, which flips `credit_status` to HOLD and blocks subsequent submits — tier reads via GET remain reachable, but priced-proof submits at SILVER+ tiers are not. All spend fixtures are parameterized by amount so Stage 2 can re-derive with PRD values or skip per the two-reader rule.

## Step 5b: Generate Test Suite — 2026-10-02T02:53:00.000Z

Stage 2 complete. All mandatory verification steps pass.

## Summary

**Generated** `test_suite/` — `conftest.py` + 11 test files, **74 tests** (test_helpers/ untouched):

| File | Tests | Contents |
|---|---|---|
| test_01_accounts.py | 7 | defaults, 404, bad enum, CLOSED terminal, credit boundary, trailing-spend, read consistency |
| test_02_enterprise_agreements.py | 7 | tier band-flat (A×2), tier boundary (A×2), window overlap/adjacency (A×2), EA renew cycle |
| test_03_instruments.py | 8 | rental commitment, install gate (A×2), dual status dimensions (A×2), decommission block, pull-through (A×2) |
| test_04_service_contracts.py | 7 | renewal cycle (A×2), renew-too-early, OCC stale renew, one-live-contract, cancel cascade (A×2) |
| test_05_service_requests.py | 12 | PM contract gate, PM gap (A×2), PM quota (A×2), billing split (A×2), dispatch tie-break/capacity/no-eligible, resolve ownership, dispatch RBAC |
| test_06_loaners.py | 5 | eligibility gate (A×2), empty pool, serial tie-break, auto-return |
| test_07_orders.py | 8 | ship/cancel guards, line validation ×3, transit sweep, stock conservation (A×2) |
| test_08_order_gates_pricing.py | 8 | licensed CONTROLLED, fee precedence, cold-chain fee, credit-hold 402, gate priorities (A×4) |
| test_09_catalog.py | 2 | duplicate sku, pagination envelope |
| test_10_surges.py | 6 | one-active-per-group, double resolve, frozen scores + waterfall (A×2), promote+reserve (A×2) |
| test_11_rbac_and_not_found.py | 4 | missing auth 401, two role-exclusivity 403s, per-resource 404 map |

**Tag audit (AST-walked):** Queue A: 17/18 instances emitted, all with ≥2 tests; 0 extra, 0 malformed/dual tags. Queue B: 40/40 non-stub instances emitted; 0 stub leakage; all 7 excluded-stub cross-references resolve to real queue-A instances.

**Skipped instance (1):** `Difficulty/combinatorial_formula/order_line_rounding_per_line_then_sum` — under PRD §3.2 floors, any discounted tier (SILVER ≥ 10,000,000) requires delivered spend above the 2,000,000-cent credit line, so the account stands on HOLD and the submit probe that distinguishes 218 (round-per-line) from 219 (sum-then-round) cannot be submitted; at BASE (0%) both rounding orders agree. No observable distinction is uniquely derivable.

**Drift-flag adjudications (recipes re-derived with PRD values 10000000/50000000/200000000):**
- `order_discount_flat_band_vs_blended_marginal` → GET-based tier assertions (50,000,000 → GOLD/10; PRD's own 60,000,000 example → GOLD/10); the submit-based pricing probe is unreachable through the credit gate (recorded gap, noted in file comment).
- `ea_tier_boundary_inclusive_floor` → GET-based: 50,000,000 → GOLD/10 vs 49,999,999 → SILVER/5.
- `surge_score_weight_times_tier_gate` / `surge_resolve_promotes_and_reserves` → re-derived with no-agreement accounts (BASE ×1.0): scores 100/50/10; waterfall skip-not-block and reservation assertions preserved verbatim. Tier multipliers ≠ 1.0 unreachable (same credit-gate reason) — recorded gap.

**Verification:** `pytest --collect-only -q` → **74 collected, 0 errors**. Zero skip/xfail markers. Every docstring carries a verbatim-grep-clean PRD citation plus exactly one resolving `Design:` tag.

## Step 6: Generate Implementation — 2026-10-02T03:12:00.000Z

Implementation complete. All verification passed.

## Summary

**File list** (all under `workspace/implementation/`):

| File | Lines |
|---|---|
| `start.sh` (executable, guarded pip install, `exec python3 app.py`) | 13 |
| `requirements.txt` (flask>=3.0,<4) | 1 |
| `app.py` — entry point, blueprint registration, error handlers | 67 |
| `db.py` — in-memory store, logical clock (starts 2026-09-01T00:00:00Z) | 40 |
| `util.py` — ISO8601 parse/format (3 fractional digits), round-half-up, add_months, remaining_full_months | 76 |
| `errors.py` — ApiError | 9 |
| `response.py` — envelope (meta/response_type/data), pagination | 69 |
| `middleware.py` — X-User-ID/X-User-Role auth, entity-backed role resolution | 56 |
| `domain.py` — all constants, derived-at-read calculators, credit cascade, serializers | 404 |
| `routes/accounts.py` — create/get/patch + pull-through-projection | 166 |
| `routes/agreements.py` — create/get/list/renew/terminate | 153 |
| `routes/instruments.py` — create/get/list/install/decommission | 176 |
| `routes/contracts.py` — create/get/list/renew/cancel + termination fee | 172 |
| `routes/engineers.py` | 54 |
| `routes/service_requests.py` — create/get/list/dispatch/resolve/loaner | 331 |
| `routes/loaners.py` | 55 |
| `routes/catalog.py` | 88 |
| `routes/orders.py` — create/get/list/submit/ship/cancel | 238 |
| `routes/surges.py` — create/resolve + allocation waterfall | 109 |
| `routes/clock.py` — set clock + delivery sweep | 37 |

**Endpoint count: 39/39** (verified by introspecting the Flask url_map).

**Verification results:**
- `python3 -m compileall` — OK; real `import app` — OK.
- Smoke test 1 (port 35241): 39/39 pass — account/catalog/order create→submit(ALLOCATED, pricing 2×115=230)→ship, clock set + delivery sweep to DELIVERED, engineer/instrument/install/request/dispatch/resolve (deadline +72h, no-contract billing 83000 = 37000 labor + 1000 parts + 45000 trip), balance 83230, trailing spend 230, 401/403/404 envelopes, pagination meta. Killed exactly PID 3989789.
- Smoke test 2 (port 40319): 63/63 real pass — agreement overlap/adjacency, EXPIRING derivation + OCC 412 + renew 200 (+12mo), GOLD contract entitlements, PM within-quota, loaner reserve→RESERVED→resolve→AVAILABLE, CRITICAL break-fix DOWN→UP, surge→BACKORDERED (score 100.0)→waterfall→ALLOCATED, credit-hold cascade, license-beats-credit 422, pull-through projection. Killed PID 4013338.
- Smoke test 3 (port 37697): 25/25 pass — real PM-gap 422 at 19d, allowed at exactly 30d, contract renew 422/400/412/200 chain, decommission-blocked 409, no-eligible-engineer 422 on install, non-INSTALLED request 409, commitment/duplicate-sku validations. Killed PID 4014651.
- `bash start.sh` evaluator contract: booted on dynamic port 53455, 200 response; one shell-operator slip orphaned child python (pid 4015027) — verified it answered 200, then killed exactly that PID; no leftover servers.

**Interpretations chosen** (candidate over-guard audit list):
1. Initial `version` = 1 at creation.
2. Same-status PATCH (e.g. ACTIVE→ACTIVE) → ERR_INVALID_STATE; CLOSED + any status field → 409 even before enum validation.
3. PM gap check is symmetric (`abs(diff) < 30 days` violates; exactly 30 days allowed).
4. Cross-resource version bumps only where §3 explicitly says so per §2.5's qualifier: loaner units, cascade-cancelled DRAFT orders, waterfall-promoted orders, swept orders, and host entities bump; catalog-item stock mutations, account balance/credit_status postings, and contract `used_pm_visits` do NOT.
5. Engineer daily capacity counts tickets currently DISPATCHED dispatched on the current UTC calendar day; if not all eligible engineers are at capacity, top-ranked engineer picked literally even if individually at 4 today.
6. Loaner reserve on a non-OPEN/DISPATCHED request → ERR_INVALID_STATE (409) rather than ERR_LOANER_NOT_ELIGIBLE; type/severity/contract gate → 422. Re-reservation over existing `loaner_unit_id` allowed.
7. List endpoints silently scoped to caller's own account for LabProcurement; single-resource reads of foreign resources → 403. Ownership-after-404 for load-required checks; direct id-vs-id 403 before 404.
8. `labor_cents` rounded half-up to integer cents before billing split.
9. Renewal endpoints: state guard (422) → missing/non-integer expected version (400) → mismatch (412).
10. Pagination clamping: out-of-range limit/offset clamp to [1,100]/[0,∞); non-integer → 400.
11. Meta `api_request_timestamp` uses the logical clock, 3 fractional digits.
12. Termination fee uses date-granularity comparisons on both sides; verified against PRD example (6 months → 2400000 PLATINUM).
13. `hours_on_site` required numeric ≥ 0, `parts_cost_cents` integer ≥ 0 at resolve.
14. `allocation_score` stored as Decimal, serialized as JSON float.
15. `stock_on_hand` ≥ 0 at catalog create; `monthly_baseline_consumable_cents` has no sign constraint.

## Step 7: Run Tests and Iterate — 2026-10-02T04:22:00.000Z

All 8 rounds pass 74/74 and the required results artifacts are preserved. Exiting with the summary.

---

**Summary**

- **Iterations run:** 2 (baseline sweep: 69/74 with the same 5 failures in all 8 rounds, fully deterministic; post-fix sweep: 74/74 in all 8 rounds).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none — the existing `same_instant`/`canonical_instant` utilities and the `ensure_engineer` fixture were already correct; the bugs were at the call sites.

- **Fixes applied to `test_suite/`:**
  - `test_suite/test_02_enterprise_agreements.py` (`test_ea_expiring_renew_cycle_succeeds`): the assertion `renewed["end_date"] == plus_months(end_date, 12)` pinned a fractional-digit-free serialization the PRD never states. PRD §3.2 covers only the 12-month instant extension; §2.6 admits any ISO 8601 UTC rendering and §2.5 blesses three-fractional-digit form, so exact-string equality fails unique derivability (STEP 1b/1c). Kept the covered claim at full strength by comparing instants via `same_instant`, matching the suite's own convention in test_03/test_07.
  - `test_suite/test_04_service_contracts.py` (`test_contract_renew_closes_cycle_and_extends_term`, `test_contract_renew_before_window_rejected`, `test_contract_renew_stale_version_rejected`): same serialization-pin defect on three `end_date` assertions; switched all three to `same_instant` and added the import.
  - `test_suite/test_06_loaners.py` (`test_loaner_auto_returns_on_resolve`): setup failed with HTTP 422 `ERR_NO_ELIGIBLE_ENGINEER`. The loaner scene builder creates no engineers, but the test's dispatch step hits PRD §3.5's verbatim rule "An empty eligible set fails the dispatch with `ERR_NO_ELIGIBLE_ENGINEER`" — the implementation was PRD-correct, the test choreography incomplete. Added `ensure_engineer(scene["account"], ["BREAK_FIX"])` before dispatch, matching the pattern used by `create_and_dispatch_request` and `setup_pm_quota_scenario`.

- **Fixes applied to `implementation/`:** none — the implementation was PRD-faithful on every failure (canonical three-fractional-digit instant serialization per §2.5 house style; `ERR_NO_ELIGIBLE_ENGINEER` on an empty eligible set per §3.5). No implementation check was weakened or removed, and no capability was added.

- **Artifacts:** `results.1.json` … `results.8.json` (all passing, 74/74) remain in `workspace/implementation/` per the output contract.

Orchestrator verification: all 8 results.*.json confirmed passed=74/total=74/errors=0 on disk; no implementation/*.py newer than results.1.json (no post-sweep impl edits); spot-checked same_instant present in test_02 (2 uses) and test_04 (4 uses), ensure_engineer call at test_06_loaners.py:116; zero skip/xfail markers in test_suite/.

## Step 8: Finalize PRD — 2026-10-02T04:31:00.000Z

The patch is complete and minimal. Final verification confirms exactly one line revised.

## Summary

**Line counts / diff:** `PRD.md` 301 lines, `PRD_FINALIZED.md` 301 lines (0% count delta). `diff` shows exactly one line changed (line 101, §2.6) — a revise-in-place, no lines added or removed.

**Changes (one edit):**
- **§2.6 — revise —** Split the closing sentence and inserted a global timestamp-rendering pin: every timestamp the API returns is rendered with exactly three fractional digits and a `Z` suffix (e.g. `2026-09-01T00:00:00.000Z`), finer input precision truncated not rounded, and non-conforming ISO 8601 input normalized on output — `implementation/util.py:25-30` (`fmt_dt`), with all output paths verified below.

**Per-item disposition of `<step_7_diff>`:**
- **Item 1 (EA renew `end_date` string-pin):** PRD silence. Impl path: `routes/agreements.py:130` (`add_months(end_date, 12)`) → `domain.py:248` (`agreement_json`) → `fmt_dt` → always `.000Z` form. Covered by the §2.6 edit.
- **Item 2 (contract renew `end_date` string-pins ×3):** Same root cause. Impl path: `routes/contracts.py:141` → `domain.py:291` (`contract_json`) → `fmt_dt`. Covered by the same single edit.
- **Item 3 (loaner test missing engineer):** Pure test-choreography defect — PRD §3.5 already pins "An empty eligible set fails the dispatch with `ERR_NO_ELIGIBLE_ENGINEER`" and the impl enforces it. No PRD edit.

**Pre-edit search log (for the single edit):**
- (a) **Subject:** rendering format of every timestamp the API returns.
- (b) **Impl paths enumerated and read/grepped:** `util.py:7-30` (`parse_dt`/`fmt_dt` — sole serializer, millisecond truncation via `microsecond // 1000`); `response.py:11-32` (`api_request_timestamp` via `fmt_dt` in both envelopes); `domain.py:236-402` (all ten entity serializers — every datetime field goes through `fmt_dt`); `routes/clock.py:37` (`current_utc` echo via `fmt_dt`); `routes/agreements.py:26-27,56-57,130` and `routes/contracts.py:45-46,64-65,141` (client dates parsed, stored, re-serialized normalized — never echoed verbatim). The only two `.isoformat()` callsites (`domain.py:169`, `routes/service_requests.py:206`) are internal date-only strings for the per-day dispatch-capacity counter; `service_request_json` never exposes `dispatched_day`.
- (c) **Wording adjustment:** non-exhaustive example phrasing under the universal claim — verified true for all enumerated paths — and preserved the original day-granularity-duration clause verbatim. Included the truncation clause because `fmt_dt` truncates rather than rounds.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly line 101 revised; 0 implementation/*.py files and 0 test files newer than results.1.json (Step 8 left impl/tests untouched; sweep still valid).

## Step 9: Complete PRD — 2026-10-02T04:55:00.000Z

The diff is exactly the 24 intended hunks and the prose reads cleanly. Task complete.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 301 lines / 53736 chars → `PRD_COMPLETED.md` 303 lines / 58314 chars (+4578 chars, 24 diff hunks; `diff -q`: files differ).

**Counts:** 23 ambiguity-pins, 3 mismatch-revisions, 0 MISSING-IN-IMPL.

**Changes (one bullet each):**
- §2.1 — insert — ambiguity — LabProcurement list endpoints scope (filter to `account_id == X-User-ID`) rather than reject; catalog list is unscoped — routes/agreements.py:86-87, orders.py:102-103, catalog.py:73-74
- §2.2 — revise — ambiguity — `api_request_timestamp` is stamped from the logical clock, not wall-clock — response.py:11-15
- §2.2 — insert — ambiguity — undefined paths yield `ERR_NOT_FOUND` (404) and wrong methods `ERR_METHOD_NOT_ALLOWED` (405), outside the §5 catalogue — app.py:49-56
- §2.3 — revise — ambiguity — `limit` clamps into [1,100], negative `offset` reads as 0, non-integer values yield `ERR_INVALID_REQUEST`; `created_at` ties break by creation order — response.py:39-69, domain.py:196-198
- §2.4 — revise — ambiguity — clock target accepts any parsable instant, including one earlier than current time (no monotonicity check) — routes/clock.py:20-26
- §2.5 — revise — ambiguity — `version` starts at 1 at creation with `created_at` == `updated_at` — routes/accounts.py:55-58 and all other create handlers
- §2.5 — insert — ambiguity — four version-exempt writes: account charge-posting/`credit_status` (domain.py:202-220), contract `used_pm_visits` increment (routes/service_requests.py:250), catalog-item `reserved_quantity`/`stock_on_hand` adjustments (routes/orders.py:182,207-208,234; surges.py:106), and the request's `loaner_unit_id` write (service_requests.py:327)
- §2.6 — revise — mismatch — the rounding enumeration omitted the resolution labor charge, which impl rounds half-up; added to the list — service_requests.py:240
- §2.6 — revise — ambiguity — offset-less ISO 8601 input instants are read as UTC — util.py:20-21
- §2.7 — insert — ambiguity — renewal check order pinned: state guard (422) → expected-version presence/integer shape (400) → version equality (412) — agreements.py:108-127, contracts.py:119-138
- §2.9 item 2 — insert — ambiguity — ownership rules needing the loaded resource run after the existence check (404 before 403); direct id comparisons apply before load — agreements.py:74-78 vs accounts.py:70-71, orders.py:27-31
- §2.9 item 3 — revise — mismatch — dropped the clause attributing body `account_id`/`instrument_id` resolution failures to `ERR_CATALOG_ITEM_NOT_FOUND`; impl yields the by-resource error (`ERR_ACCOUNT_NOT_FOUND`/`ERR_INSTRUMENT_NOT_FOUND`) — agreements.py:25, instruments.py:27, contracts.py:33, orders.py:31, service_requests.py:40
- §3.1 — insert — ambiguity — the four account transitions are the complete set (same-status PATCH → `ERR_INVALID_STATE`); `CLOSED` blocks only status changes, not profile edits; supplying a recognized field is a mutation even when the value is unchanged; a no-field patch changes nothing — accounts.py:87-134, domain.py:70-75
- §3.2 — insert — ambiguity — renewal adds 12 calendar months with day-of-month clamping (Feb 29 → Feb 28) — util.py:38-44, agreements.py:130
- §3.3 — insert — ambiguity — omitted commitment reads as 0, so CAPITAL may omit the field — instruments.py:40,52-57
- §3.4 — insert — ambiguity — termination-fee month count is taken on calendar dates; time-of-day plays no part — util.py:47-68, contracts.py:165
- §3.4 — insert — ambiguity — contract renewal uses the same clamped month addition as §3.2 — contracts.py:141
- §3.4 — insert — ambiguity — `used_pm_visits` increment is a counter write only; no contract `version`/`updated_at` change — service_requests.py:250
- §3.5 — revise — mismatch — PM 30-day gap is symmetric (`abs(Δ) < 30d` rejected in either direction; exactly 30 days permitted) — service_requests.py:84
- §3.5 — insert — ambiguity — daily capacity counts only requests still `DISPATCHED` dispatched on the current UTC calendar day of the logical clock — domain.py:166-176, service_requests.py:189-196
- §3.5 — insert — ambiguity — loaner reservation on a request in any state other than OPEN/DISPATCHED yields `ERR_INVALID_STATE` — service_requests.py:295-299
- §3.5 — insert — ambiguity — the reservation's `loaner_unit_id` write bumps neither the request's `version` nor `updated_at` — service_requests.py:326-330
- §3.5 — revise — ambiguity — resolve-time validation: `hours_on_site` required, non-negative, may be fractional; `parts_cost_cents` optional non-negative integer default 0; violations → `ERR_INVALID_REQUEST` — service_requests.py:225-236
- §3.5 — revise — ambiguity — labor charge is 18500 × `hours_on_site` rounded half-up to the nearest cent — service_requests.py:240
- §3.6 — insert — ambiguity — `stock_on_hand` must be a non-negative integer; missing/non-integer/negative → `ERR_INVALID_REQUEST` — catalog.py:43-47
- §3.6 — revise — ambiguity — DRAFT order's pricing figures and `total_quantity` read 0, `submitted_at`/`shipped_at`/`delivered_at` null until the pipeline fills them — orders.py:62-81
- §3.7 — revise — ambiguity — `allocation_score` is returned as a JSON number while waterfall comparison uses the exact decimal — domain.py:383, surges.py:91-98

**MISSING-IN-IMPL:** none. Every PRD requirement traced to implementation behavior, including all 36 endpoint role lists, the credit-hold cascade firing only on the GOOD→HOLD flip, the waterfall's stock-only satisfiability test, `delivered_at = shipped_at + transit`, and the strict `> 2000000` credit boundary.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md differs from PRD_FINALIZED.md (303 vs 301 lines); 0 implementation/*.py files and 0 test files newer than results.1.json (Step 9 left impl/tests untouched; the 74/74 × 8-round sweep remains valid).
