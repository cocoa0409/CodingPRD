# Worklog — task_3414_fast_follow_product_development_value_price_point

Scenario: Fast-Follow Product Development & Value Price Point Sourcing (e.l.f. Beauty)

## Step 1: Create task directory — 2026-10-01T20:49:00.000Z

Task directory pre-allocated by the caller: `tasks/task_3414_fast_follow_product_development_value_price_point/` with `workspace/` inside. Verified it exists; no new index computed, no other task_* directory created.

## Step 2: Scaffold generation — 2026-10-01T20:55:00.000Z

Scaffold generation complete and verified.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3414_fast_follow_product_development_value_price_point/SCAFFOLD.yaml` (1750 lines; §1.0–§1.7, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3414_fast_follow_product_development_value_price_point/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1416 lines; single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3414_fast_follow_product_development_value_price_point/SCAFFOLD_CORNER_DESIGN.yaml` (2880 lines; single top key `scaffold_corner_design`)

## Counts

- **Entities: 12** — TrendSignal, Concept, Product (self-referential successor link + parallel packaging dimension), ContractManufacturer, FormulaProject, CostQuote, ComplianceDossier (4 parallel compliance dimensions), RetailPartner, LineReview, PlanogramSlot, LaunchPlan (parallel sampling dimension + append-only distributions), DiscontinuationReview
- **Endpoints: 47** (flat topology, incl. `POST /_clock/set_current_utc` with the mandatory 2026-09-01T00:00:00Z default)
- **State machines: 12** — cyclic reformulation loops (Product, FormulaProject), parallel dimensions (ComplianceDossier ×4, LaunchPlan sampling), branching with compensation (CostQuote, LineReview, PlanogramSlot), approval-chain with segregation of duties (DiscontinuationReview)
- **Calculations: 11** — incl. dual-variant landed cost (provisional vs settled) and launch quantity (demand vs risk-adjusted), pinned nested-rounding order, single-pass circular-dependency clamp, tiered fixed-price-point cost targets, decay-tiered markdown exposure, chronological CM capacity, eviction waterfall
- **Errors: 44** | Validations: 30 | Roles: 8 (7 opaque + `ManufacturerRep` entity-backed) | OCC concurrency rules: 2
- **§1.8 difficulty instances: 20** — all nine §0.5 rules at ≥2 each (3 each for boundary_precision_check and cross_entity_state_dependency)
- **§1.9 corner entries: 64** (56 active instances + 8 `excluded_because` stubs) across all nine taxonomy sections

## Difficulty profile ("much harder than expert")

Density-driven per §0.4: depth-3 discontinuation cascade and depth-2 cert-denial cascade with distinct triggers; two temporal-overlap geometries (half-open review windows vs closed+14-day-buffer shelf occupancy); two compensating invariants (launch-inventory units, shelf facing budget); validation priority conflicts on state-vs-safety and referential-vs-fiscal; boundary checks at ==target (260/261 cents), ==capacity (6/7 facings), ==threshold (70.0 score), ==cap (80/81 samples), ==4-week markdown tier; OCC on Product and LineReview versions; entity-backed ownership and field-level role splitting.

## Verification

- `scaffold_lint.py`: **VERDICT: clean lint** — 1634 calls across §1.8/§1.9 all conform to §1.5; all FKs reverse-reachable (pasted verdict block above).
- Every formula-derived assert literal was recomputed by executing the formulas in Python (234/233/247/261/260 landed costs, 819/237 clamp, 94800 exposure, 70.0/69.7/58.0 scores, 84/168/260/360/440 tier targets — all match).
- Self-audit: all 44 errors covered by at least one test, all endpoint roles in RBAC, 84 instance names unique across both design files, all `grounds:` resolve, no forbidden concurrency vocabulary. One design bug caught and fixed pre-lint: `CANCELLED` was unreachable for DECIDED line reviews, which would have shipped the release-committed-slots cascade as dead code.

## Step 3: Copy shared files — 2026-10-01T22:15:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3414_fast_follow_product_development_value_price_point/workspace/INSTRUCTION.md`. Verified all three scaffold artifacts exist (SCAFFOLD.yaml 99999 bytes, SCAFFOLD_DIFFICULTY_DESIGN.yaml 70704 bytes, SCAFFOLD_CORNER_DESIGN.yaml 134741 bytes).

## Step 4: PRD generation — 2026-10-01T22:30:00.000Z

That occurrence is the idiom "built around" in the introduction, not a fuzzy quantity hedge — acceptable. All checks pass. Final report:

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_3414_fast_follow_product_development_value_price_point/workspace/PRD.md` — 299 lines.

**Section structure:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (headers, 8 roles, identity semantics, field-level role splits), 2.2 API Response Structure (verified byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 The Logical Clock (fixed start `2026-09-01T00:00:00Z`, lazy EXPIRED/LAPSED), 2.5 Common Resource Properties, 2.6 Money/Precision/Rounding, 2.7 OCC, 2.8 Validation Order and Error Precedence (all 30 priority levels in explicit order), 2.9 Finite Pools, 2.10 Lifecycles and Parallel Dimensions
- §3 Business Logic: 3.1 Trend Discovery, 3.2 Concepts/Price Points, 3.3 Products/Tooling/Reformulation, 3.4 Manufacturers/Formula Projects, 3.5 Cost Quotes/Landed Cost, 3.6 Compliance Dossier, 3.7 Retail/Line Reviews/Planogram, 3.8 Launch Planning/Sampling/Reconciliation, 3.9 Discontinuation
- §4 Endpoint Definitions (4-column table), §5 Error Code Catalogue (2-column table)

**Coverage confirmation (all verified mechanically against SCAFFOLD.yaml):**
- **Entities:** all 12 covered in prose with every field named in backticks (contract check: 0 missing of ~110 required identifiers including endpoint-only inputs like `variant`, `dimension`, `outcome`, `blocked_items`, `notes`, `event_type`, `units`, `channel`, `actual_qty`, `actual_freight_total_cents`, `current_utc`, `expected_product_version`, `expected_line_review_version`).
- **State machines:** all 12 (including the separately-declared LaunchPlanSampling parallel dimension); all 59 state tokens present (one gap found by audit — `SETTLED` — was fixed by adding the `ACCEPTED → SETTLED` pair to §3.5).
- **Calculations:** all 9 expressed as precise prose (momentum score with caps/weights/threshold 70.0 and 1-decimal half-up; price-point cost tiers with worked values 84/168/260/360/440; landed cost both variants with pinned round-per-component order and duty-from-rounded-freight; launch quantity single-pass clamp with MOQ evaluation order; markdown risk 5%/week capped 40%; markdown exposure tiers 4/8/12 weeks; shelf reconciliation with footprint invariant; capacity eviction committed_at DESC tie created_at DESC; CM quarterly capacity accepted_at ASC tie created_at ASC; packaging lead 5/14 weeks; sampling burn 10% cap with COMMIT/DISTRIBUTE/RELEASE semantics and conservation invariant).
- **Validations:** all 30 priorities expressed with explicit ordering and paired error IDs (§2.8 plus workflow-local trigger prose).
- **Errors:** all 44 IDs present (44/44), correct HTTP statuses in §5.
- **Endpoints:** all 47 rows in §4 table, exact method+path match with scaffold, no extras.
- **Roles:** all 8 with exact spelling and identity translations (7 opaque, ManufacturerRep entity-backed by ContractManufacturer).
- **Concurrency rules:** both OCC rules fully expressed (endpoint, `expected_*_version` field, `ERR_STALE_VERSION`/412).
- **§3 path purity:** 546 backtick tokens scanned, 0 paths, 0 bare methods, 0 method+path combos.
- No gaps to name.

## Step 5a: Test helpers generation (Stage 1 of 2) — 2026-10-01T22:55:00.000Z

Stage 1 is complete and verified. Summary:

## Files written — `/home/ubuntu/github/CodingPRD/tasks/task_3414_fast_follow_product_development_value_price_point/test_helpers/`

| File | Contents |
|---|---|
| `types.py` | 12 entity TypedDicts (all `common_fields: true` → id/created_at/updated_at/version), 20 status/dimension enums with PRD-exact string values, `REVIEW_OUTCOMES` per-dimension outcome sets |
| `api_errors.py` | `ApiErrorId` enum (44 errors) + `HTTP_STATUS_CODES` with plain-string keys, registered via `set_error_http_status_map()` at import |
| `constants.py` | Domain thresholds + canonical clock waypoints (see below) |
| `api_client.py` | `ApiClient(GenericApiClient)` with **47 endpoint methods** — one per scaffold endpoint, including `set_clock`; `headers` optional everywhere so 401 tests just omit it; module singleton `api_client` |
| `test_users.py` | `TEST_USERS` (8 role headers) + per-role `make_*_headers` builders; ManufacturerRep builder takes the `ContractManufacturer.id` (entity-backed) |
| `factories.py` | 15 payload factories, input fields only; `None` values are **omitted** from payloads (optional-field semantics; lets tests strip `tooling_fee_cents`/`sample_budget_cents`); unknown override keys pass through (system-field-injection tests); unique name/SKU counter |
| `assertions.py` | 12 `assert_<entity>()` shape checks + 4 invariant checkers (`assert_launch_inventory_conserved`, `assert_footprint_conservation`, `assert_dossier_compliance_verdict`, `assert_sample_cap_respected`) |
| `fixtures.py` | 12 read-throughs (admin headers), ~30 granular step helpers, 14 composite `setup_*` fixtures returning ctx dicts (see below) |
| `__init__.py` | Barrel: framework generics + all PRD-specific modules |

Nothing written to `test_suite/`. No server was started; no module-level mutable state beyond a documented uniqueness counter (safe under per-test-server isolation).

## Public API surface for Stage 2

**Client:** `api_client.<verb>_<resource>(...)` — e.g. `create_trend_signal(payload, headers=None)`, `patch_cost_quote(quote_id, payload, headers)`, `submit_dossier_review(dossier_id, payload, headers)`, `create_sample_distribution(plan_id, payload, headers)`, `set_clock(current_utc, headers)`. Lists take `params=`.

**Granular fixtures:** `set_clock(now=LOGICAL_CLOCK_START)`, `read_{concept,product,manufacturer,formula_project,cost_quote,dossier,partner,line_review,planogram_slot,launch_plan,discontinuation_review}`; `create_trend`/`transition_trend`/`create_selected_trend`; `create_concept`/`transition_concept`/`create_selected_concept`; `create_manufacturer`/`transition_manufacturer`/`set_manufacturer_capacity`; `create_product`/`transition_product`/`set_packaging_ready`; `create_formula_project`/`submit_formula_sample(fp_id, cm_id)`/`approve_formula`/`reject_formula_sample`/`abandon_formula`/`create_approved_formula`; `create_quote(product_id, cm_id, expected_product_version=None(fresh-read), **ov)`/`evaluate_quote`/`accept_quote`/`create_accepted_quote`/`reject_quote`/`withdraw_quote(q_id, cm_id)`/`settle_quote(q_id, actual_qty, actual_freight_total_cents)`; `open_dossier`/`submit_dossier_review`/`certify_dossier`/`make_dossier_compliant`; `create_partner`/`update_partner_capacities`; `create_line_review`/`open_line_review(now=window_start+1d)`/`advance_line_review_to_reviewing`/`advance_line_review_to_decided`; `create_slot(review_id, product_id, expected_line_review_version=None(fresh-read), **ov)`/`commit_slot`/`withdraw_slot`; `create_launch_plan`/`lock_plan(variant="DEMAND")`/`approve_plan`/`execute_plan(now=occupancy_start)`/`set_sampling_status`/`set_sample_budget`/`record_sample_event`; `propose_discontinuation(proposer_user_id="pm-nadia")`/`approve_discontinuation(approver_user_id="rp-owen")`/`reject_discontinuation`.

**Composites (ctx dicts keyed `trend, concept, manufacturer, product, formula_project, quote, dossier, partner, line_review, slot, plan`):** `setup_product_with_approved_formula` → `setup_sourcing_product` → `setup_accepted_quote_product` → `setup_compliance_gate_product` → `setup_compliant_gate_product` → `setup_launch_ready_product` → `setup_open_review_with_slot` → {`setup_draft_plan` (plan created inside window at 2026-10-02, risk 0.20), `setup_decided_review_with_slot`} → `setup_committed_slot_scenario` → `setup_locked_plan(variant)` → `setup_approved_plan` → `setup_executed_plan` (product LAUNCHED at 2026-11-01, slot ACTIVE) → `setup_executed_plan_with_sampling`. Each accepts `*_overrides` dicts per entity it creates.

## Constants (all diffed against PRD prose)

`LOGICAL_CLOCK_START=2026-09-01T00:00:00Z`; momentum: `VELOCITY_CAP_PER_DAY=5000`, `GROWTH_CAP=2.0`, `W_VELOCITY=0.5`, `W_GROWTH=0.3`, `W_SIGNAL=0.2`, `TREND_SELECT_THRESHOLD=70.0`; pricing: `PRICE_POINTS=(300,600,1000,1500,2000)`, `TARGET_UNIT_COST_BY_PRICE_POINT={300:84, 600:168, 1000:260, 1500:360, 2000:440}`; packaging: `TOOLING_NEW_WEEKS=14`, `TOOLING_REUSE_WEEKS=5`; formula: `COMPRESSED_FORMULA_WEEKS=6`, `MAX_FORMULA_ROUNDS=3`; cert: `CERT_VALIDITY_DAYS=365`; launch qty: `FACINGS_WEEKLY_SELLTROUGH=12`, `LAUNCH_WEEKS=8`, `TREND_DECAY_PCT_PER_WEEK=0.05`, `MARKDOWN_RISK_CAP=0.40`; markdown tiers: `4/8/12` weeks at depths `0.00/0.30/0.50/0.70`; `RESET_GAP_DAYS=14`; `SAMPLE_CAP_PCT=0.10`; pagination `10/1/100/0`. Clock waypoints: `CLOCK_INSIDE_WINDOW=2026-10-02`, `CLOCK_AFTER_WINDOW=2026-10-16`, `CLOCK_AT_REVIEW_DATE=2026-10-21`, `CLOCK_OCCUPANCY_START=2026-11-01`, `CERT_EXPIRY_FROM_START=2027-09-01`, `CLOCK_PAST_CERT_EXPIRY=2027-09-02`, `CLOCK_MARKDOWN_WEEK4=2026-11-29` (exactly 28 days post-launch), `CLOCK_MARKDOWN_WEEK9=2027-01-05` (65 days → 9 weeks) — all verified reachable by monotonic advancement from the 2026-09-01 start, and date arithmetic machine-checked.

## Verification

- `python -m py_compile` on all 9 files: OK.
- Real import of the package: OK — 44 errors registered with the framework map, exactly 47 client endpoint methods, ~100-name public surface present.
- AST dangling-import audit: every `from .X import name` across helper modules resolves to a top-level definition; all star-import targets define `__all__`.
- Behavior smoke: None-drop/override passthrough/unique names in factories, entity-backed vs opaque headers (incl. SoD cross-role `make_retail_planner_headers("pm-nadia")`), and all fixture date math (window+1d, review+1d, cert+365d, markdown week boundaries) verified numerically.

One correction made mid-build: the PRD has **no** `GET /trend-signals/{id}` endpoint (list only), so `read_trend` was removed rather than shipped as a call to a nonexistent route — the corner 404 sweep deliberately covers only the 10+1 single-GET resources, and the client matches that exactly.

## Step 5b: Test suite generation (Stage 2 of 2) — 2026-10-01T23:30:00.000Z

All checks pass. The suite is complete and verified.

## Stage 2 complete — task_3414 test_suite generated

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3414_fast_follow_product_development_value_price_point/test_suite/`):

| File | Tests | Covers |
|---|---|---|
| `conftest.py` | — | `api` fixture + 8 role-header fixtures |
| `test_01_landed_cost_variants.py` | 4 | Difficulty: landed provisional/settled divergence, nested rounding order |
| `test_02_launch_quantity_variants.py` | 4 | Difficulty: demand/risk variants, single-pass budget clamp |
| `test_03_reformulation_and_dossier_cycles.py` | 4 | Difficulty: reformulation loop, dossier parallel dimensions |
| `test_04_cascades.py` | 4 | Difficulty: discontinuation depth-3, cert-denial depth-2 |
| `test_05_validation_priority_pairs.py` | 4 | Difficulty: state>compliance, referential>fiscal orderings |
| `test_06_boundary_precision.py` | 6 | Difficulty: landed-cost ±1 cent, facings at capacity, score 70.0/69.7 |
| `test_07_cross_entity_gates.py` | 6 | Difficulty: quote-accept/product, slot-commit/review, lapsed-cert/plan |
| `test_08_temporal_overlap.py` | 4 | Difficulty: half-open windows, 14-day occupancy buffer |
| `test_09_compensating_invariants.py` | 4 | Difficulty: sampling conservation, facings evict/recommit cycle |
| `test_10_corner_entities_create.py` | 6 | Corner/entities (creation half) |
| `test_11_corner_entities_read.py` | 6 fns / 15 items | Corner/entities (reads; unknown-id sweep parametrized ×10) |
| `test_12_corner_state_machines.py` | 9 | Corner/state_machines |
| `test_13_corner_calculations.py` | 5 fns / 9 items | Corner/calculations (price tiers parametrized ×5) |
| `test_14_corner_validations_auth_state.py` | 8 | Corner/validations (auth, existence, OCC, SoD, ownership, MOQ) |
| `test_15_corner_validations_business.py` | 9 | Corner/validations (business rules) |
| `test_16_corner_endpoints.py` | 8 | Corner/endpoints |
| `test_17_corner_rbac.py` | 3 | Corner/rbac |
| `test_18_corner_cross_cutting.py` | 2 | Corner/cross_cutting + consistency_model |

**Coverage (AST-walked both indices and diffed against emitted tags):**
- Queue A (Difficulty): **20/20 instances, each with exactly 2 tests** (40 tests)
- Queue B (Corner): **56/56 active instances covered** (69 collected items via 2 parametrized families); **8 `excluded_because` stubs emitted no test**, and all 8 stub→difficulty cross-references resolve to real §1.8 instances
- **Skipped instances: none** — every non-stub instance passed the PRD-first two-condition filter

**Adjudication notes:**
- The two priority-pair instances (state-beats-compliance, referential-beats-fiscal) were emitted because PRD §2.8 states the fixed evaluation order verbatim ("Seventh… Eighth…", referential group before "Fiscal rules follow"), satisfying unique derivability — no validation-priority silence-pattern skip. Each pair is tested as the ordered conflict plus the lower-priority error in isolation as the instance's second test.
- `trend.created_at` is asserted equal to the logical clock (Corner B1); this is uniquely derivable because §3.8's `markdown_risk_pct` formula reads the parent trend's `created_at`.

**Helper gaps (worked around, helpers untouched):** no `reconcile_plan` granular helper exists — reconciliation is driven via `api.patch_launch_plan(..., {"status": "RECONCILED"})` directly (2 uses). Trend re-reads go through `list_trend_signals` with a status filter since the PRD defines no `GET /trend-signals/{id}` endpoint (Stage 1 documented this).

**Verification results:**
1. AST tag audit: every test function's docstring ends with exactly one `Design:` tag resolving to a real instance; zero untagged/dual-tagged/stub-tagged tests
2. Strict verbatim pass: every ≥8-word quoted fragment in every docstring literal-greps in `PRD.md` (two trailing-punctuation mismatches found and fixed during the sweep)
3. `python -m pytest --collect-only` (PYTHONPATH=task dir): **109 tests collected, 0 errors**
4. No "scaffold" references anywhere in generated code; no server started

## Step 6: Implementation generation — 2026-10-02T00:10:00.000Z

All verification steps complete. Final report:

## Summary

**Implementation complete** at `/home/ubuntu/github/CodingPRD/tasks/task_3414_fast_follow_product_development_value_price_point/workspace/implementation/` — Python + Flask, in-memory dict storage only, zero startup seeding, boots empty on every `start.sh` invocation. Isolation rule honored: only INSTRUCTION.md, SCAFFOLD.yaml, PRD.md were read (no design/test files, no test suite runs).

### Files written (28 files, 3,298 lines)

| File | Lines | Role |
|---|---|---|
| start.sh | 10 | guarded pip install, `exec python3 app.py` |
| requirements.txt | 1 | flask>=2.2,<4 |
| app.py | 66 | factory, envelope error handlers (ApiError/404/405/500), /health + /, main |
| core/constants.py | 96 | every named constant, defined once (thresholds, tiers, caps, roles, headers) |
| core/errors.py | 87 | ApiError + 44-entry error catalog (+3 framework fallbacks) |
| core/clock.py | 67 | logical clock (default 2026-09-01T00:00:00Z), ISO parse/format (millis, Z) |
| core/store.py | 59 | dict-per-entity store, new_record (UUID, created_at, version=1), touch (version+1) |
| core/envelope.py | 64 | success/error envelope, generic serializer (datetime/Decimal aware, strips `_`-fields) |
| core/auth.py | 40 | X-User-ID/X-User-Role auth (p1), role/ownership gates (p2) |
| core/validate.py | 151 | shape validation helpers (p3) |
| core/pagination.py | 58 | limit/offset parse, filter + created_at-asc sort + slice + meta |
| services/calc.py | 288 | all 9 calculations (Decimal, per-component round-half-up, ceil amortization) |
| services/cascade.py | 248 | reformulation/kill/cert-denial/lapse/discontinuation cascades, lazy expiry, atomic eviction |
| routes/ (13 modules) | ~2,000 | clock, trends, concepts, products, manufacturers, formulas, quotes, compliance, partners, line_reviews, slots, launch_plans, discontinuation |

All 47 endpoints implemented. `python -m py_compile` passes on all files; AST import-graph audit clean (27 modules, no dangling imports).

### Self-smoke-test results (server self-booted via `bash start.sh` on a dynamic port, PID saved and killed exactly)

Two passes, ~85 assertions, all green:
- **Pass 1 (main chain)**: 401 without headers; clock set (PlatformAdmin-only); trend create→evaluate (momentum 96.0)→select; concept select (target 260 for $10 price point); product create; OCC 412 on stale `expected_product_version`; landed-cost math (freight 50 + duty 25 + tooling 1 = 276 → ERR_COST_TARGET_EXCEEDED vs 260; second quote 231 accepted, pins formula_version, supersedes sibling); packaging gate 409 before compliance gate 422 (priority order); full dossier → compliant → LAUNCH_READY; window/clock gates on line review; slot propose/commit with facing reconciliation; plan create (capacity 384, variants, risk 0.10 after 2 weeks); lock 384 @ 231; mixed field-groups → 403; approve; ERR_LAUNCH_WINDOW_NOT_OPEN; execute fan-out (product LAUNCHED, slot ACTIVE, concept COMMERCIALIZED); sampling COMMIT/DISTRIBUTE/RELEASE with cap+budget overdraws; segregation-of-duties 403; discontinuation cascade (product DISCONTINUED, slot VACATED, facings freed, plan RECONCILED with markdown 364 @ 0% depth); settle-after-discontinuation 409; pagination envelope.
- **Pass 2 (edges)**: tooling reuse at same clock instant (5 weeks); lazy cert LAPSED + reversion cascade (product→FORMULATION, quote→INVALIDATED, formula reopened round 2); window overlap rejected / adjacency allowed; occupancy 9-day gap rejected / exactly-14-day allowed; capacity eviction (4→2 facings evicts newest commit, slot RELEASED); quote lazy EXPIRED on read; fresh reboot = empty store; entity 404 shape; undeclared GET /trend-signals/{id} → 405 (matches endpoint table).

**start.sh confirmed**: honors exported `$PORT`, binds `0.0.0.0` (verified via `ss`), runs foreground via `exec` (the start.sh PID becomes `python3 app.py`; SIGTERM to that PID shuts it down), no stray listeners after kill. Dependency install is guarded by an `import flask` check so per-test reboots skip pip.

### Interpretations chosen where the PRD left behavior open (candidate over-guards, honestly listed)

1. **Concept create same-step precedence**: category mismatch → ERR_INVALID_REQUEST is checked *before* trend-not-SELECTED ("reports ERR_INVALID_REQUEST instead" read as precedence).
2. **Tooling reuse "strictly earlier created_at"**: implemented as (created_at, insertion-seq) — two products at the same logical instant still detect reuse; otherwise the common case (clock unmoved between creates) would never reuse.
3. **Occupancy 14-day buffer**: PRD says "strictly more than fourteen days" then "exactly fourteen days is allowed" — implemented gap ≥ 14 days allowed (explicit allowance wins).
4. **PATCH /products with both `packaging_status` and `status`**: packaging applied first, so PACK_READY+LAUNCH_READY can succeed in one call.
5. **Quote-acceptance gate order**: validations priority order (product/formula → expiry → CM → MOQ → capacity → cost-target), *not* the scaffold state-machine's listing order (cost-target third). PRD §2.8 is pinned as fixed.
6. **Quote lazy expiry on PATCH**: non-ACCEPTED targets on a pending-but-expired quote persist EXPIRED then fail 409 from the terminal state; ACCEPTED from UNDER_EVALUATION surfaces ERR_QUOTE_EXPIRED at its priority-16 step.
7. **Plan approval check order**: compliance gate (p8) before slot-committed (p13), per §2.8's fixed order over the scaffold's narrative order.
8. **Quantity lock**: single-pass algorithm followed literally (clamp → ERR_BUDGET_EXCEEDED; final MOQ check → ERR_BELOW_MOQ), not naive priority ordering (p25 < p28); q0=0 → ERR_BELOW_MOQ without dividing by zero.
9. **Multiple ACCEPTED quotes / APPROVED formulas**: lock uses the most recently accepted quote; acceptance pins max formula_version (spec assumes one of each).
10. **Sample-distribution gates** (partly unnamed in spec): events require plan ∈ {QUANTITY_LOCKED, APPROVED, EXECUTED} and sampling ≠ CLOSED (ERR_INVALID_STATE); DISTRIBUTE requires ACTIVE; DISTRIBUTE/RELEASE over `samples_committed` → ERR_SAMPLE_OVERDRAW (family error); `units` integer ≥ 1.
11. **Empty PATCH** (no recognized writable fields) → 200 no-op, no version bump.
12. **Pagination** limit/offset non-integer or outside 1–100 → ERR_INVALID_REQUEST (400), not clamped.
13. **Trend conditional-required fields**: supplying the *other* source's field → 400 per PRD §3.1, overriding the scaffold's "ignored otherwise".
14. **Capacity PATCH**: map replaced wholesale; a category absent from the new map is treated as capacity 0 (eviction applies).
15. **Plan revert to DRAFT** also clears `locked_variant` (spec names qty/landed only; DRAFT's default is null).
16. **Discontinuation cascade** reconciles *all* EXECUTED plans of the product (spec says singular).
17. **Clock set** accepts any instant; no monotonicity gate ("advances" not enforced).
18. **EXECUTED fan-out** applies product/concept/slot transitions conditionally (defensive against cert-lapse interleaving; unreachable on PRD-legal paths).
19. **Field range constraints** (scaffold `constraints:` column: ≥0, 0..1, ≥1, shipment_weight ≥ unit_weight) enforced as ERR_INVALID_REQUEST at shape priority.
20. `api_request_timestamp` is wall-clock; all resource timestamps are logical-clock. Framework-only error ids (ERR_NOT_FOUND/ERR_METHOD_NOT_ALLOWED/ERR_INTERNAL) exist solely for unmatched routes/methods/500s — never emitted by declared endpoints.

## Step 7: Test-fix iteration loop — 2026-10-02T00:45:00.000Z

Clean 8-round sweep achieved. Final summary:

## Summary

**Iterations run:** 2 (sweep 1: 8 deterministic failures, identical across all 8 rounds; sweep 2: fully clean).

**Root cause (single, shared by all 8 failures):** timestamp string-format drift. The implementation rendered every datetime as ISO 8601 with three fractional digits (`...T00:00:00.000Z`); the failing tests asserted the no-fraction form (`...T00:00:00Z`). Adjudication against PRD verbatim split the fields into two classes:

- **Stamped / computed / input datetimes** (`selected_at`, `evaluated_at`, `accepted_at`, `committed_at`, `cert_expires_at`): PRD §2.4 pins the logical clock's reading to exactly `2026-09-01T00:00:00Z` (no fractional digits) and §2.5 defines stamps as logical-clock instants — so the no-fraction form is the PRD-faithful rendering. The tests were faithful; the **implementation** drifted.
- **`created_at`/`updated_at`**: PRD §2.5 verbatim requires "ISO 8601 UTC with three fractional digits" — the implementation was correct; the one test asserting the no-fraction form contradicted the very PRD sentence its own docstring quotes.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3414_fast_follow_product_development_value_price_point/test_suite/test_10_corner_entities_create.py` — `test_trend_create_ignores_client_supplied_system_fields`: `created_at` expectation corrected to `"2026-09-01T00:00:00.000Z"` per PRD §2.5 (STEP 2 — assertion mis-translated the PRD rule it cited).

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3414_fast_follow_product_development_value_price_point/workspace/implementation/core/clock.py` — added `fmt_instant()` rendering logical-clock instants at seconds precision exactly as §2.4's clock reads.
- `/home/ubuntu/github/CodingPRD/tasks/task_3414_fast_follow_product_development_value_price_point/workspace/implementation/core/envelope.py` — `pub()` now renders `created_at`/`updated_at` with three fractional digits (PRD §2.5) and every other datetime via `fmt_instant()` (PRD §2.4/§2.5 stamped-instant rule).
- `/home/ubuntu/github/CodingPRD/tasks/task_3414_fast_follow_product_development_value_price_point/workspace/implementation/routes/clock_routes.py` — clock-set endpoint returns the clock's new reading via `fmt_instant()` (PRD §2.4 "reads exactly `2026-09-01T00:00:00Z`").

**Sweep confirmation:** `results.1.json` … `results.8.json` from the final clean sweep are all present in the implementation directory; every round shows **passed == total == 109, failed == 0**. The results files remain in place per the output contract.

## Step 8: PRD finalization — 2026-10-02T00:55:00.000Z

The diff is exactly the two intended sentence-level revisions; nothing else changed. Task complete.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3414_fast_follow_product_development_value_price_point/workspace/PRD_FINALIZED.md` (copy of PRD.md + 2 inline revisions). Nothing under `implementation/`, `test_suite/`, or `test_helpers/` was created, modified, or deleted — read/grep/diff only.

**Line counts:** PRD.md 298 lines / 55,462 bytes → PRD_FINALIZED.md 298 lines / 56,059 bytes. 0% line delta; +1.08% character delta.

### Changes
- **§2.4 — revise** — pinned the clock-set capability's returned reading to the seconds-precision `2026-09-01T00:00:00Z` form (no fractional digits) — `implementation/routes/clock_routes.py:23`, `implementation/core/clock.py:66-80`
- **§2.5 — revise** — pinned rendering of every resource datetime field besides `created_at`/`updated_at` (stamped instants, computed deadlines, client-supplied echoed instants) to seconds precision with no fractional digits, exemplar `2026-09-01T00:00:00Z` — `implementation/core/envelope.py:50-68` (`pub()` key-split), `implementation/core/clock.py:66-80`

### Step 7 items requiring no PRD edit
- `test_10_corner_entities_create.py` `created_at` correction to `"2026-09-01T00:00:00.000Z"` — pure fixture bug; PRD §2.5 verbatim already pins `created_at`/`updated_at` to three fractional digits and the implementation already matched. Kept verbatim.
- `envelope.py` ms-rendering of `created_at`/`updated_at` — already PRD-§2.5-verbatim. Test deletions: none. `test_helpers/` fixes: none.

### Per-edit pre-edit search log
**Edit 1 (§2.4 clock-set response):** (a) subject — rendering format of the clock-set endpoint's returned reading. (b) enumerated — `routes/clock_routes.py:23` (confirmed sole site returning a clock reading via greps for `current_utc`, `clock.now()`, `fmt_instant` across routes/core/services); `core/clock.py:66-80` (`fmt_instant`, `timespec="seconds"`). (c) adjustment — scoped the clause to the returned reading's *form*, reusing §2.4's own `2026-09-01T00:00:00Z` exemplar; no widening needed (single call site).

**Edit 2 (§2.5 non-created_at/updated_at datetime rendering):** (a) subject — serialization format of resource datetime fields other than `created_at`/`updated_at`. (b) enumerated — `core/envelope.py:50-68` `pub()` (universal serializer; `created_at`/`updated_at`→`fmt`/ms, all else→`fmt_instant`/seconds); wrappers `_pub_plan` (`launch_plans.py:29-40`), `_pub_dossier` (`compliance.py:28-36`), `_pub_partner` (`partners.py:19-29`) all delegate to `pub()` adding only non-datetime fields; `core/pagination.py:45-58` lists serialize through the same per-route `pub`-based serializers; field writers/echoes: `concepts.py:109` `selected_at`, `trends.py:109` `evaluated_at`, `formulas.py:51,57,113` `due_at`/`submitted_at`, `quotes.py:58,194` `valid_until`/`accepted_at`, `compliance.py:60`+`cascade.py:100` `cert_expires_at`, `slots.py:53-54,109-112,176` occupancy bounds/`committed_at`, `line_reviews.py:37-39,64-66` window bounds/`review_date`, `launch_plans.py:200` `launched_at`, `store.py:42-59` `created_at`/`updated_at`; excluded non-resource outputs — `meta.api_request_timestamp` (`envelope.py:20-24`, wall clock, ms; pinned separately by §2.2 verbatim) and clock-set response (Edit 1). (c) adjustment — rejected a stamped-fields-only clause because `pub()` renders computed (`due_at`, `cert_expires_at`) and client-supplied echoed instants (`valid_until`, window bounds, `review_date`, occupancy bounds) at seconds precision too; a narrow clause would leave those unpinned and invite a fresh milliseconds mismatch. Widened to "every other datetime field a resource carries besides `created_at` and `updated_at`", using the clock's reading as *form* exemplar (not value source) so client-supplied instants are not mis-described; wording scoped to resource fields so §2.2's `api_request_timestamp` rule is untouched.

## Step 9: PRD completeness scan — 2026-10-02T01:30:00.000Z

Done. The completed PRD is written and verified. Final summary:

## Output verification
- **Source**: `/home/ubuntu/github/CodingPRD/tasks/task_3414_fast_follow_product_development_value_price_point/workspace/PRD_FINALIZED.md` (298 lines, 56,059 chars) → **PRD_COMPLETED.md** (301 lines, 59,014 chars; +3 lines, +2,955 chars). `diff -q` confirms the files differ in exactly 20 changed regions (19 in-paragraph edits + 1 three-row table append). No file under `implementation/`, `test_suite/`, or `test_helpers/` was created or modified — the 8 `results.*.json` sweep artifacts are untouched.

## Counts
- **Ambiguity-pins: 20** (all edits are pins of the impl-adopted reading; one is a `revise` of soft conditional prose, the rest `insert`s).
- **Mismatch-revisions: 0** — every genuine contradiction found was classified as a suspected impl bug and left out of the PRD.

## Changes (one per bullet)
- §2.3 — insert — ambiguity — invalid `limit`/`offset` → `ERR_INVALID_REQUEST`; `created_at` ties break by creation sequence; filters are exact-match; undeclared query params ignored — `core/pagination.py:20-58`
- §2.4 — insert — ambiguity — clock-set applies the supplied instant as given, no monotonicity check — `routes/clock_routes.py:16-23`
- §2.5 — revise+insert — ambiguity — `version` starts at 1; undeclared body fields (incl. client-supplied `id`/`created_at`/`version`) ignored — `core/store.py:42-53`
- §3.1 — insert — ambiguity — `mention_velocity_7d` non-negative integer, `engagement_growth_pct` non-negative — `routes/trends.py:35-36`
- §3.3 — revise — ambiguity — `PACK_READY` may be set in the same update as the status change (packaging applied first) — `routes/products.py:129-138`
- §3.4 — insert — ambiguity — `capacity_slots_per_quarter` is zero-or-more — `routes/manufacturers.py:39-41`
- §3.5 — insert — ambiguity — `duty_rate` ∈ [0,1], `initial_order_qty` ≥ 1, monetary fields non-negative, weights positive — `routes/quotes.py:45-57`
- §3.5 — insert — ambiguity — with several APPROVED projects, `pinned_formula_version` takes the highest `formula_version` — `routes/quotes.py:192`
- §3.5 — insert — ambiguity — non-acceptance transition on an expired pending quote lazily moves it to `EXPIRED` then fails with `ERR_INVALID_STATE` (only acceptance reports `ERR_QUOTE_EXPIRED`) — `routes/quotes.py:236-245`
- §3.6 — revise — ambiguity — ingredient `BLOCKED`→`CLEARED` re-review is a plain dimension transition, not conditioned on an intervening reformulation — `routes/compliance.py:107`
- §3.7 — insert — ambiguity — category absent from a revised capacity map treated as capacity zero; eviction tie-break adds creation order, newest first — `services/cascade.py:162-204`
- §3.7 — revise — ambiguity — slot release also clears the plan's `locked_variant` — `services/cascade.py:120-132`
- §3.8 — insert — ambiguity — plan creation fields are non-negative integers — `routes/launch_plans.py:64-67`
- §3.8 — insert — ambiguity — with several ACCEPTED quotes, the lock reads the most recently accepted (`accepted_at`, then creation order) — `routes/launch_plans.py:43-54`
- §3.8 — insert — ambiguity — `retail_units_available` null before lock; `markdown_exposure_cents` null until reconciliation — `routes/launch_plans.py:29-40`
- §3.8 — insert — ambiguity — sampling events accepted only in QUANTITY_LOCKED/APPROVED/EXECUTED; event POST returns 201 with the updated plan — `routes/launch_plans.py:312-322,368`
- §3.8 — revise — ambiguity — COMMIT exceeding `retail_units_available` → `ERR_SAMPLE_OVERDRAW` — `routes/launch_plans.py:334-344`
- §3.8 — revise+insert — ambiguity — RELEASE over-commit → `ERR_SAMPLE_OVERDRAW`; only DISTRIBUTE is gated on `ACTIVE` — `routes/launch_plans.py:317-326,360-366`
- §3.9 — insert — ambiguity — approval when the product is no longer LAUNCHED still marks the review APPROVED, no cascade — `routes/discontinuation.py:120-125`
- §4 — insert — ambiguity — no-op lifecycle PATCH returns 200 unchanged; `GET /health` and `GET /` are bare-status probes; undeclared routes → `ERR_NOT_FOUND`, wrong method → `ERR_METHOD_NOT_ALLOWED`, unexpected → `ERR_INTERNAL` — `app.py:26-53`
- §5 — insert — ambiguity — three framework-level rows appended to the error catalogue with a fallback lead-in — `core/errors.py:66-69`

## Suspected implementation bugs (PRD unchanged)
1. **Tooling-reuse same-instant tie-break** — PRD §3.3: reuse is true exactly when another product has the same `tooling_code`, *"a strictly earlier `created_at`"*, and non-KILLED status. `services/calc.py:148-161` compares `(created_at, _seq)` tuples, so a product created at the *same* logical-clock instant but earlier insertion order counts as reuse — contradicting "strictly earlier `created_at`" whenever two products share a `created_at` (common under a logical clock).
2. **Validation-order deviations vs §2.8** (role auth priority 2 and shape priority 3 precede path resolution priority 4): `routes/formulas.py:98-107` resolves the path id (404) *before* the field-level role split and before enum validation (a ManufacturerRep attempting a non-submission target on a nonexistent project gets 404, not `ERR_FORBIDDEN_ROLE`); `routes/quotes.py:219-227` and `routes/launch_plans.py:253-265` validate the status enum after path resolution (bogus status on a nonexistent id → 404, not `ERR_INVALID_REQUEST`). All other PATCH endpoints do these in the PRD order, so the impl is also internally inconsistent.
3. **Partial mutation without version increment on failed combined PATCHes** — PRD §2.5: `version` *"increments by one on every mutation of that resource"*. `routes/products.py:129-138` applies the packaging transition before the status gates; if a status gate then raises (e.g. `ERR_COMPLIANCE_GATE_FAILED`), `packaging_status` stays mutated with no version bump and an error response. Same pattern at `routes/launch_plans.py:292-296` (`sample_budget_cents` applied before a possibly-failing sampling transition).

## Dead-contract-surface findings
None among PRD-declared behavior — every PRD-stated check, cascade, gate, and filter is live and reachable in impl (all 35 declared endpoints exist; the endpoint surface matches exactly). One non-contract dead helper: `services/calc.py:287-288` (`def now()`) is defined but never called.

## Post-Step-9: Orchestrator remediation of Step 9's suspected impl bugs + evidence regeneration — 2026-10-02T01:20:00.000Z

Orchestrator-verified Step 9's artifact claims first: `diff -q` confirms PRD_COMPLETED.md ≠ PRD_FINALIZED.md (298→301 lines); all 8 results files present and green (109/109); newest impl/test source mtime (00:29) predated the Step 7 sweep results (00:33); dead-helper claim spot-verified (`def now()` at calc.py:287 has no callers — left in place as harmless non-contract dead code).

Then remediated the 3 suspected implementation bugs (each contradicts PRD verbatim; the reference implementation must match PRD_COMPLETED.md it ships with):

1. **Tooling-reuse tie-break** — `services/calc.py` `detect_tooling_reuse`: dropped the `(created_at, _seq)` tuple comparison; reuse now requires strictly earlier `created_at` per PRD §3.3 verbatim. Signature lost the `seq` param; single caller `routes/products.py:60` updated. Test-exposure check before the fix: the only reuse test (`test_13_corner_calculations.py::test_packaging_lead_weeks_tooling_reuse_detection`) advances the clock a full day between the two product creates, so the strict comparison satisfies it; the product factory defaults `tooling_code` to None (omitted), so no other fixture can collide.
2. **Validation-order deviations vs PRD §2.8** (role p2 / shape p3 precede path resolution p4):
   - `routes/formulas.py::patch_formula_project` — role-class check (non-submission target → SourcingLead) now runs on the raw value before path resolution; `req_enum` hoisted above the 404; the ManufacturerRep ownership check (needs the record) stays immediately after resolution.
   - `routes/quotes.py::patch_cost_quote` — `req_enum` and the SETTLED conditionally-required ints (`actual_qty`, `actual_freight_total_cents`) hoisted above the 404.
   - `routes/launch_plans.py::patch_launch_plan` — pm-group enum validation (`status`, `variant`), the conditionally-required `variant`-on-lock check, and ml-group shapes (`sample_budget_cents`, `sampling_status`) hoisted above the 404.
3. **Partial mutation without version bump on failed combined PATCHes**:
   - `routes/products.py::patch_product` — restructured to validate-then-apply: both dimensions validated against the current record (`new_pack`/`new_status` locals, gates raise before any write), then applied together; LAUNCH_READY gate checks the effective post-call `new_pack`, preserving the PRD_COMPLETED §3.3-pinned combined PACK_READY+LAUNCH_READY call.
   - `routes/launch_plans.py::patch_launch_plan` ml branch — the sampling transition (which may raise) now runs before the `sample_budget_cents` write.

No PRD_COMPLETED.md edits needed: the document already stated the correct rules — the impl now matches it. No test_suite/test_helpers edits.

**Evidence regeneration (orchestrator-run, per post-sweep-write invalidation rule):** `python -m py_compile` + AST parse on all 5 touched files: OK. Full 8-round parallel sweep (`prd-bench-local-run --isolation per-test-server`, fresh `results.${i}.json`): **all 8 rounds passed == total == 109, failed == 0** (round wall time ~190s). The results.{1..8}.json in `workspace/implementation/` are from this post-fix sweep and are the final evidence artifacts.
