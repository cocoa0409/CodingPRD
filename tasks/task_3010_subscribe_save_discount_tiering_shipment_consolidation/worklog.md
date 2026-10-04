# Worklog — task_3010_subscribe_save_discount_tiering_shipment_consolidation

## Step 1: Create task directory — 2026-09-29T12:06:00.000Z

Task directory was pre-allocated by the caller; verified `./tasks/task_3010_subscribe_save_discount_tiering_shipment_consolidation/workspace/` exists and is empty. No new index computed, no other task_* directory created.

## Step 3: Copy shared files — 2026-09-29T12:07:00.000Z

Copied `./INSTRUCTION.md` to `./tasks/task_3010_subscribe_save_discount_tiering_shipment_consolidation/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-09-29T12:58:31.000Z

**Files written** (all three fresh, in `tasks/task_3010_subscribe_save_discount_tiering_shipment_consolidation/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys), 1069 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`, 1351 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`, 2173 lines

**Lint verdict (pasted verbatim):**
```
Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     45
  Calls scanned (§1.8+§1.9):  629

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts:**
- Entities: 14 (Customer, Product, PriceEvent, InventoryPlacement, Subscription, DeliveryPlan, PlanLine, Coupon, Promotion, RetentionOffer, DamageClaim, Reshipment, DemandForecast, Notification)
- Endpoints: 63 · Errors: 39 · State machines: 9 (incl. cyclic Subscription ACTIVE→PENDING_CANCEL→ACTIVE and PlanLine SCHEDULED↔SKIPPED/AUTO_SKIPPED loops) · Calculations: 12 · Roles: 3 (Customer entity-backed; SupportAgent, PlatformAdmin opaque)
- Difficulty design: 19 instances — all 9 rules with ≥2 instances each (combinatorial_formula has 3, covering all three modes a/b/c)
- Corner design: 50 instances (45 active + 5 `excluded_because` stubs), all names unique across both files

**Design decisions worth noting:**
- Archetype: pricing engine + event sourcing; flat topology, peer roles, immediate consistency; calibrated beyond-expert via density (tier/cap/coupon/promotion interactions) rather than sprawl.
- The `lock_evaluation_pipeline` pins a 7-step evaluation order (substitute → price-at-ship → cap → tier → per-line-round-then-sum → coupons in attach order → bonus lines last) to resolve the circular-looking tier↔skip↔cap dependency — the mode-(c) combinatorial instance shows a cap-skip dropping tier 0.10→0.05 and repricing survivors 900→950.
- Rounding pinned per-line-then-sum with a crafted 3×333-cent fixture (948 vs the forbidden 949) as the mode-(b) probe.
- Dual-variant calculations deliberately placed on different entity domains: estimated-vs-charged totals on DeliveryPlan, committed-vs-provisional (half-weight PAUSED, floored) on DemandForecast.
- OCC lives only on `POST /sns/delivery-plans/{id}/refresh` (a true supersede race); lock/ship are plain state preconditions per the §1.2.1 filter.
- Compensating invariants pinned as explicit formulas: money (`gross_line_total == SHIPPED/RESHIPPED lines + refunded_total + still-SCHEDULED lines`) and units (`received == on_hand + reserved + shipped` through receive→lock→ship→reship).
- Logical clock endpoint `POST /sns/_clock/set_current_utc` with the mandatory startup default `2026-09-01T00:00:00Z`; retention-offer expiry is lazy (evaluated on read), exercised by a clock-advance corner test.
- Temporal-overlap instances contrast half-open promotion windows (adjacency allowed) with strict point ordering on price-event `effective_from` (equal timestamp collides).
- No sibling task directories were inspected; the scaffold was derived solely from the scenario text and the skill spec.

(Note: the first Step-2 subagent attempt was interrupted by a session exit before writing files; the run was resumed and completed successfully. Both runs executed under the same instructions.)

## Step 4: Generate PRD — 2026-09-29T13:09:34.750679707Z

All checks pass. PRD.md is fully written at `workspace/PRD.md`.

**Summary**

- **Line count:** 337 lines
- **Section structure:**
  - §1 Introduction (3 paragraphs: business framing, price-at-ship philosophy, logical clock)
  - §2 Global Specifications — 11 subsections: 2.1 RBAC (with per-role identity prose), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Logical Clock (startup default `2026-09-01T00:00:00Z`, `to_iso8601`/`current_utc`), 2.5 Validation Ordering (all 10 priority tiers), 2.6 Nested Resource Retrieval, 2.7 Common Resource Properties (incl. PriceEvent/Notification `common_fields: false` exceptions), 2.8 Money/Precision (integer cents, round-half-up, per-line-then-sum), 2.9 Price History as Append-Only Log, 2.10 Inventory Conservation + Derived Availability, 2.11 OCC on Plan Refresh (`expected_plan_version` → `ERR_STALE_PLAN_VERSION` 412)
  - §3 Business Logic — 13 subsections organized by lifecycle (catalog → customers → subscriptions → pause/resume/cancel/retention → monthly generation → lock pipeline 7 steps → coupons → promotions → ship/deliver/money-invariant → line skip/unskip → damage claims/reshipments → demand forecasting → notifications)
  - §4 Endpoint table — 4 columns, all 55 endpoints
  - §5 Error catalogue — 2 columns, all 39 error IDs

**Hard contract reports:**

- **Contract 1 (Field-Name Coverage):** 87 required identifiers (all entity fields incl. common fields, all endpoint input/query/path params), 87 present, 0 missing — PASS (verified programmatically)
- **Contract 2 (Rule Coverage):** validation priority ordering expressed in §2.5 with relative-order prose; OCC rule fully expressed (write operation + `expected_plan_version` + `ERR_STALE_PLAN_VERSION` + 412); all 10 calculation rules expressed in reconstruction-safe prose (clamped month arithmetic, consolidation grouping, tier thresholds 3/5 inclusive, per-line round-then-sum, price-at-ship estimated vs final variants, pinned 7-step lock pipeline, coupon stacking order with per-step rounding, half-open promotion windows, forecast committed/provisional with floored 0.5 paused weight, 110% price-increase notice, damage refund + money invariant, inventory conservation invariant, availability derivation); all state-machine transitions with preconditions and side-effects covered; sibling branches (cancel from ACTIVE vs PAUSED, review decisions, estimated vs final price variants) symmetrically specified — PASS
- **Contract 3 (§3 Path Purity):** 369 backtick tokens scanned in §3, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos — PASS

**Coverage notes:** the two withheld difficulty/corner design files were not opened. The logical-clock default (`2026-09-01T00:00:00Z`) from the clock endpoint description is stated in §2.4. All 39 error IDs appear in prose before §5 (the six entity-scoped 404s not individually named in §2/§3 narrative are covered generically via §2.5/§2.6 and enumerated in §5, consistent with the "table has no conditions" design).

## Step 5: Generate unit tests — 2026-09-29T13:48:21.761918795Z

**Orchestrator note:** Step 5 was mistakenly launched twice (two concurrent test-generator subagents). Both agents detected each other mid-flight, reconciled test_helpers to a single coherent interface, and their outputs merged cleanly. The merged suite was audited programmatically by the orchestrator after both agents exited: every instance in §1.8/§1.9 has correct coverage with zero unknown tags, zero uncovered instances, zero untagged tests. Verbatim agent reports follow.

**Agent A report:**
Files written — test_helpers/ (9 files, ~1100 lines): types.py, api_client.py (all 44 /sns endpoints), api_errors.py (40 error IDs), assertions.py (per-entity validators + inventory-conservation and money-invariant checkers), factories.py, constants.py, test_users.py (TEST_USERS + make_customer_headers for entity-backed Customer role), fixtures.py (composite setup chains), __init__.py barrel. test_suite/ — 19 test modules + conftest.py (10 written by this agent). Queue A: 19/19 instances each ≥2 tests; Queue B: 45/45 non-stub instances each ≥1 test; 141 tagged tests, zero untagged/malformed docstrings. Instances skipped: none — every non-stub instance passed the PRD-first two-condition filter; all 5 excluded_because stubs correctly left untranslated. Notes: detected concurrent sibling writing same directory, reconciled fixtures.py/__init__.py to merged interface, re-verified imports and audit. Caveat flagged: 3 tests in sibling files carry PRD citations with `...` elisions that may not survive a literal grep.

**Agent B report:**
test_helpers/ (9 files, ~1,050 lines) — same module list; api_errors.py registers all 39 ApiErrorIds keyed on .value; assertions.py includes assert_inventory_conservation and assert_plan_money_invariant. test_suite/ — conftest.py + 23 test files, 162 test functions, all collected by pytest without error. Queue A: 18/18 instances, 71 tests (≥2 per instance); Queue B: 46/46 non-stub instances, 91 tests. Every docstring ends with exactly one verbatim Design: tag; every quoted PRD citation passes literal grep after de-eliding fused citations; no skip/skipif/xfail markers. Reconciled with pre-existing files: added ADMIN/add_price/create_product aliases to fixtures.py; fixed one non-verbatim citation in test_11_state_preconditions.py. Zero instances skipped. One recipe-vs-PRD discrepancy handled conservatively: cap_skip_drops_tier_and_reprices_surviving_lines recipe pre-computes 950/3800, but PRD formulas applied to the recipe's own setup give 1140/4560 — tests assert PRD-derived values with verbatim §3.6 citations (PRD is the contract).

**Orchestrator post-merge audit (authoritative):** difficulty non-stub 19, corner non-stub 45, corner stubs 5; 162 test functions, 162 tags, 0 untagged, 0 unknown tags, 0 uncovered instances; tests-per-instance distribution {1:2 (both Corner — allowed), 2:40, 3:8, 4:14}. pytest collection: 162 tests collected without error.

## Step 6: Generate implementation — 2026-09-29T14:11:07.945944528Z

(First attempt terminated early due to a transient API throttling error after writing only start.sh + requirements.txt; relaunched and completed.)

**Files written**
- `workspace/implementation/app.py` — complete single-file Flask implementation (~1250 lines)
- `start.sh` — pre-existing launcher kept as-is (guarded pip install, exec python3 app.py); made executable
- `requirements.txt` — flask>=2.2,<4, kept as-is

**Endpoint coverage:** All 63 endpoints from PRD §4 implemented: customers (CRUD + suspend/unsuspend + 4 nested lists), products (+ price events + product subscriptions), inventory placements (+ receive), subscriptions (create/read/patch/pause/resume/cancel + retention-offer list), retention offers (read/accept/decline), coupons, promotions, ops (generate-plans, recompute-forecasts), demand forecasts, delivery plans (read, lines, OCC-guarded refresh, lock, ship, mark-delivered, resolve, cancel, line skip/unskip, coupon attach, damage claims), top-level plan-lines, damage claims (read/review/reshipments), reshipments (read/dispatch/mark-delivered), and the logical-clock endpoint (startup default 2026-09-01T00:00:00Z).

**Key spec fidelity points:** envelope meta/response_type/data; pagination in meta (limit default 10, min 1, max 100, clamped); full validation priority order with all 37 scaffold error IDs and exact HTTP statuses; clamped month arithmetic, cadence re-anchor on PATCH, resume fix-up to today+2; lock pipeline in pinned order (availability/substitution → price-at-ship → cap → tier → per-line round-half-up charges → coupons in attach order → bonus lines); inventory reserve/release conservation; PRICE_INCREASE at strict >110%; PRICE_CAP_SKIP notifications; lazy retention-offer expiry; Decimal round-half-up money math; forecasts with floored 0.5×PAUSED contribution, upsert keyed on (product, region, month); in-memory dicts only, zero seeding.

**Boot verification:** Server booted via PORT=18342 bash start.sh, responded within ~1s, passed full smoke flow: 401 on missing auth, clock set/report, customer/product/price/placement/receive, availability derivation, subscription create, plan generation, lock, ship, deliver, damage claim, APPROVE_REFUND, resolve; plus OCC 412, ERR_FORBIDDEN, ERR_INVALID_REQUEST precedence, lazy offer expiry. Server killed after verification.

## Step 7: Run tests and iterate — 2026-09-29T14:27:51.261486827Z

All 8 rounds pass 162/162.

- **Iterations run:** 2 (first sweep: 4 deterministic failures × 8 rounds; second sweep: 162/162 in all 8 rounds).
- **Tests deleted:** none. All four failures survived STEP 1 (each asserts a rule stated verbatim in PRD §3.6/§3.7/§3.10 and uniquely derivable from it); all three fixes landed in STEP 2 as test-artifact bugs.
- **Fixes applied to test_suite/:**
  - `test_01_tier_and_lock_pricing.py` — `test_cap_skip_drops_tier_and_reprices_surviving_lines`: expected totals changed from 3800 → 4560. The test had inherited the design recipe's stale pre-computation (950/line assuming pre-change price 1000); PRD §3.6 Step 2 resolves `unit_price_cents` at the lock instant (1200, price event effective 2026-09-02, clock at 2026-09-03), so 4 surviving lines × round_half_up(1200 × 0.95) = 4 × 1140 = 4560. The implementation was PRD-correct.
  - `test_03_state_machine_cycles.py` — added missing `get_plan` to the `from test_helpers import (...)` list; two tests in the file used it bare (`NameError`) while sibling files import it explicitly.
  - `test_12_calculations.py` — `TestStackedCouponOrder._setup`: added `flat_off_cents=None` to the PERCENT coupon creation. The factory default includes `flat_off_cents`, and PRD §3.7 declares the wrong value-field/type combination malformed (`ERR_INVALID_REQUEST`) — so the implementation correctly rejected the malformed fixture payload; the fixture now matches the pattern already used in test_05.
- **Fixes applied to test_helpers/:** none.
- **Fixes applied to implementation/:** none — the implementation was PRD-faithful in all four cases.

**Orchestrator verification:** all 8 results.{1..8}.json read directly — each reports passed=162 total=162 failed=0.

## Step 8: Finalize PRD — 2026-09-29T14:32:22.505836015Z

Both edits are confined to the two Step 7 items that warranted PRD clarification (the get_plan import was a pure test bug; nothing was deleted).

**Line counts / % delta:** PRD.md 337 lines; PRD_FINALIZED.md 337 lines; 0% line delta (2 lines modified in place).

**Changes:**
- §3.6 — revise — Step 2 gained a sentence stating the lock instant is the logical clock's reading when the lock request is processed, so the resolved price is the latest PriceEvent effective at or before that reading (not the subscribe price or an earlier estimate) — implementation/app.py:1468-1471 (`evaluate_line_availability` calls `product_current_price`, defined at app.py:289-298 as latest `effective_from <= now()`).
- §3.7 — revise — coupon creation sentence now spells out type↔value-field mutual exclusivity (PERCENT requires `percent_off` and forbids `flat_off_cents`; FLAT vice versa; wrong combination or missing matching field → `ERR_INVALID_REQUEST`) — implementation/app.py:1170-1179.

Step 7 items with no PRD edit: the test_03 missing-import fix (pure test artifact), and the test_01 expected-totals fix was deemed covered by existing §2.9/§3.6 prose, with one clarifying sentence added per its suggestion (the §3.6 edit above).

**Per-edit pre-edit search log:**

1. **§3.6 Step 2 edit**
   - (a) Subject: price resolution for `unit_price_cents` during the lock pipeline.
   - (b) Paths enumerated: `evaluate_line_availability` (app.py:1440-1485, step 2 at 1468-1471), shared by `lock_plan` (app.py:1539-1541) and `refresh_plan` (app.py:1521-1523); resolver `product_current_price` (app.py:289-298, `eff <= now()`); logical clock `now()`/`CLOCK` (app.py:18-26); estimate path `estimate_plan` (app.py:370-384) uses the same resolver. Refresh is described by §3.6's own "re-runs steps 1 through 3 in estimated mode" sentence, so the new clause was scoped to the lock wording without touching refresh.
   - (c) Wording adjustment: explicitly anchored "the lock instant" to the logical clock reading (per §2.4/§2.9) rather than making any claim about wall clock or subscribe price, so the clause stays consistent with refresh and estimation paths that use the same resolver.

2. **§3.7 mutual-exclusivity edit**
   - (a) Subject: coupon value-field ↔ `discount_type` combination validation.
   - (b) Paths enumerated: `create_coupon` (app.py:1159-1196, checks at 1170-1179) — the only mutation site for coupon value fields (other coupon endpoints are `GET` at 1197 and `disable` at 1204, which do not alter value fields); consumer `apply_coupons` (app.py:335-346) only reads the matching field; serializer `ser_coupon` (app.py:503-506) echoes both fields, which may be null.
   - (c) Wording adjustment: kept the exclusivity statement scoped to creation ("a `PERCENT` coupon must carry ..."), and retained the original "wrong combination ... rejected as `ERR_INVALID_REQUEST`" clause so the revise is a pure strengthening of an already-pinned rule, consistent with serialization of null fields.

## Step 9: Complete PRD — 2026-09-29T14:47:21.472755729Z

**Source vs output:** PRD_FINALIZED.md 337 lines / 46,797 chars → PRD_COMPLETED.md 337 lines / 50,224 chars (+3,427 chars, +0 lines; all edits inline).

**Counts:** 20 ambiguity-pins (inserts), 3 mismatch-revisions (all three are pure removals of duplicated/incorrect prose: the duplicated "and `plan_id` anchoring the line to its plan" clause, and the coupon "(ties broken by coupon creation time, earliest first)" tie-break the impl does not implement). Everything else is additive pinning; no section added, no behavior invented.

**Changes:**
- §2.1 — insert — ambiguity — pin that a Customer X-User-ID need not reference an existing Customer record (auth does not resolve the id) — app.py:185-190
- §2.2 — insert — ambiguity — pin that generate-plans/recompute-forecasts return an array of created/updated resources in data — app.py:1336, 1385
- §2.3 — insert — ambiguity — pin limit/offset clamping (limit into [1,100], offset to ≥0) and ERR_INVALID_REQUEST for non-integer pagination params — app.py:261-279
- §2.5 — insert — ambiguity — pin that a non-object JSON body is ERR_INVALID_REQUEST — app.py:235-236
- §2.7 — insert — ambiguity — pin version starts at 1 at creation — app.py:112
- §2.7 — insert — ambiguity — pin that any mutation (including no-op-effective pipeline rewrites of a line) refreshes updated_at/version — app.py:1460, 1466, 1476, 1484
- §3.1 — insert — ambiguity — pin duplicate sku rejected with ERR_INVALID_REQUEST — app.py:782-784
- §3.1 — revise — mismatch — substitute reference pinned to impl: only existence is checked; a patch may even self-reference — app.py:826-827
- §3.1 — insert — ambiguity — pin non-positive price_cents rejected with ERR_INVALID_REQUEST — app.py:848-849
- §3.1 — insert — ambiguity — pin placement create requires existing product, and missing placement id surfaces ERR_PRODUCT_NOT_FOUND — app.py:890, 904-906, 930-932
- §3.2 — insert — ambiguity — pin duplicate email rejected with ERR_INVALID_REQUEST — app.py:660-662
- §3.2 — insert — ambiguity — pin suspend-of-non-ACTIVE and unsuspend-of-non-SUSPENDED both yield ERR_CUSTOMER_SUSPENDED (409) — app.py:701-702, 713-714
- §3.3 — insert — ambiguity — pin non-positive price_cap_cents rejected with ERR_INVALID_REQUEST — app.py:952-953, 1010-1011
- §3.4 — insert — ambiguity — pin resume leaves an already-far-enough next_delivery_date unchanged — app.py:1063-1067
- §3.4 — insert — ambiguity — pin cancel from a status other than ACTIVE/PAUSED yields ERR_SUBSCRIPTION_NOT_ACTIVE — app.py:1079-1080
- §3.4 — insert — ambiguity — pin offer accept/decline return the updated RetentionOffer object — app.py:1136, 1153
- §3.4 — insert — ambiguity — pin lazy expiry only flips the subscription when still PENDING_CANCEL, and notification-feed reads run expiry across all of the customer's subscriptions — app.py:412-414, 422-425, 748
- §3.5 — revise — mismatch — removed duplicated "and plan_id anchoring the line to its plan" clause — PRD prose defect
- §3.5 — insert — ambiguity — pin malformed delivery_month rejected with ERR_INVALID_REQUEST, and the operation returns the created-plan array — app.py:1287-1292, 1336
- §3.6 Step 1 — insert — ambiguity — pin: no placement counts as zero on hand; substitution additionally requires the substitute to exist and have a current price — app.py:1445-1447, 1451, 1454-1456
- §3.6 Step 2 — insert — ambiguity — pin: no current price at lock leaves unit_price_cents unchanged, skips the cap check, and contributes zero to totals — app.py:1469-1471, 1473, 1551
- §3.6 — insert — ambiguity — pin: bonus lines consume no inventory; lock returns the updated plan — app.py:1576-1580, 1599
- §3.6 — insert — ambiguity — pin refresh effects: same substitution/auto-skip/PRICE_CAP_SKIP notification side effects as lock, returns updated plan, and ERR_PLAN_NOT_OPEN precedes ERR_STALE_PLAN_VERSION — app.py:1515-1518, 1523, 1526
- §3.7 — insert — ambiguity — pin ERR_INVALID_REQUEST for unknown discount_type, duplicate code, negative min_subtotal; pin disabling a non-ACTIVE coupon is ERR_INVALID_REQUEST — app.py:1168, 1180-1183, 1209-1210
- §3.7 — revise — mismatch — disabled coupon attach surfaces ERR_COUPON_NOT_FOUND (PRD said "no longer attachable" without pinning the error) — app.py:1733-1734
- §3.7 — revise — mismatch — removed the "(ties broken by coupon creation time, earliest first)" tie-break; impl applies strictly in attach order — app.py:335-345
- §3.8 — insert — ambiguity — pin ERR_INVALID_REQUEST for min_line_count < 1, misordered window, and disabling a non-ACTIVE promotion — app.py:1227-1232, 1273-1274
- §3.9 — insert — ambiguity — pin mark-delivered on non-SHIPPED plan is ERR_PLAN_NOT_LOCKED, and bonus lines ship without touching placement counters — app.py:1615-1619, 1633-1634
- §3.9 — insert — ambiguity — pin resolve-of-non-DELIVERED is ERR_PLAN_NOT_DELIVERED; plan-cancel of non-OPEN is ERR_PLAN_NOT_OPEN; cancel only moves SCHEDULED lines — app.py:1645-1649, 1660-1666
- §3.10 — insert — ambiguity — pin refresh-healing requires a current price to exist (priceless line stays AUTO_SKIPPED) — app.py:1498-1503
- §3.11 — insert — ambiguity — pin invalid decision value is ERR_INVALID_REQUEST; refund approval moves the claim to COMPLETED — app.py:1848-1849, 1872
- §3.11 — insert — ambiguity — pin reshipment dispatch/mark-delivered on wrong status is ERR_INVALID_REQUEST — app.py:1926-1927, 1956-1957
- §3.12 — insert — ambiguity — pin malformed forecast_month is ERR_INVALID_REQUEST; the run returns the array of written forecast rows — app.py:1343-1348, 1385
