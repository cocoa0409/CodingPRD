# Worklog — task_3445_single_brand_line_extension_distributor_coverage_management

## Step 1: Create Task Directory — 2026-10-02T04:28:00.000Z

Pre-allocated task directory verified at `tasks/task_3445_single_brand_line_extension_distributor_coverage_management/` with `workspace/` inside. No new index computed (per orchestration args).

## Step 2: Generate Scaffold — 2026-10-02T05:45:00.000Z

All three artifacts are generated, parse cleanly, and pass every check. Summary:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_3445_single_brand_line_extension_distributor_coverage_management/SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3445_single_brand_line_extension_distributor_coverage_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3445_single_brand_line_extension_distributor_coverage_management/SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

## Counts

| Element | Count |
|---|---|
| Entities | 15 |
| State machines | 14 (cyclic: ProductLine review loop, Distributor suspend/reinstate, MarketRegistration reject/revise + renewal, Promotion LIVE↔SUSPENDED) |
| Calculations | 12 |
| Validation rows (priority-ordered) | 13 |
| Endpoints | 82 |
| Error codes | 62 |
| Roles | 11 (DistributorContact is `entity_backed:Distributor`; rest opaque) |
| OCC concurrency rules | 2 (assignment create on Distributor.version, price-list create on PackFormat.version) |
| §1.8 instances | **19 total, 19 non-stub** (9 rules × 2, plus a 3rd combinatorial instance covering mode (c)) |
| §1.9 instances | **89 total, 79 non-stub** (10 `excluded_because` stubs citing §1.8 instances) |

## Lint verdict (verbatim from `scaffold_lint.py`)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(1605 calls scanned, 0 violations.)

## Difficulty design highlights (per the "harder than expert" directive)

- **Posture-driven gating**: `Brand.protection_posture` (counterfeit severity + for-cause breach revocations) gates launches, registration submits, exclusive coverage activation, and promo depth caps (25.00/15.00/5.00%).
- **Depth-3 cascade**: for-cause grant revoke → manufacturer SUSPENDED → sibling grants REVOKED for cause → formulation regresses COMPARTMENTALIZED→SEALED. Depth-2: sell-through report → SANCTION tier → distributor + assignments suspended.
- **Two interval regimes**: coverage exclusivity uses closed intervals (touching conflicts); price lists use half-open windows with clip/supersede resolution.
- **Dual-variant calcs on different domains**: attainment ACTUAL vs PROJECTED (distributor), provisional vs actual promo funding (promotion finance); combinatorial modes (a) tiered rebate with nested min, (b) pinned unit-first rounding (5088 ≠ 5090), (c) evaluation-order-pinned dilution novelty baseline (750 vs 550 for identical specs).
- **Segregation of duties by user id**: promotion approver ≠ creator; for-cause revoker ≠ grantor.
- Logical clock with pinned startup default `2026-09-01T00:00:00Z`, monotonic, drives all sweep transitions.

## Notes for downstream steps

- Endpoint count (82) deliberately exceeds the Expert band per the difficulty directive. Per known pipeline behavior, the Step-6 implementation-generation prompt will need pre-constraining (per-domain modules, one file per message, no-truncation, self-smoke-test).
- Every numeric assert in both design files was pre-computed from the pinned formulas (e.g., attainment 6667 = round_half_up(10000·200/300); rebate estimate 4865 = round_half_up(300·499·325/10000); renewal boundary 2026-10-03T00:00:00Z = expiry 2027-01-01 minus exactly 90 days).

Orchestrator verification: all three files exist and parse as YAML (top-level keys confirmed: SCAFFOLD.yaml has scenario/domain_name/api_prefix/entities/...; design files have their single top keys). Domain markers match the scenario — domain_name `brand-line-coverage`, api_prefix `/brand-ops`, entities include Brand, ProductLine, Formulation, ContractManufacturer, ConfidentialityGrant, Distributor, Market, MarketRegistration, CoverageAssignment, PackFormat, ChannelPriceList, Promotion, CounterfeitCase, UseCaseSubmission, SellThroughReport.

## Step 3: Copy Shared Files — 2026-10-02T05:46:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T05:58:00.000Z

All contracts PASS. The PRD is complete and shipped at `/home/ubuntu/github/CodingPRD/tasks/task_3445_single_brand_line_extension_distributor_coverage_management/workspace/PRD.md` (409 lines). Neither forbidden design index was opened, and no sibling task directory was touched.

## PRD section list

- **§1. Introduction** — 2 paragraphs, brand-equity vs. brand-protection framing
- **§2. Global Specifications** — 2.1 RBAC (11 roles with per-role identity translations; `DistributorContact` entity-backed, others opaque), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending), 2.4 Logical Clock & Time Sweep (startup default `2026-09-01T00:00:00Z`, strictly-advancing `to_iso8601` → `current_utc`, `ERR_CLOCK_REGRESSION`, all six sweep transition families + posture recompute; clock noted as mounted outside `/brand-ops`), 2.5 Common Resource Properties (UUID/`created_at`/`updated_at`/`version`; `SellThroughReport` carries only `id`+`created_at`), 2.6 Validation Order (all 13 priority rows as an ordered first-failure-wins list with every mapped error id), 2.7 OCC (both rules: `expected_distributor_version`, `expected_pack_format_version`, `ERR_STALE_VERSION` 412), 2.8 Precision & Rounding (integer bps, round-half-up, floors, second precision, no approximation), 2.9 Window Semantics (closed date intervals vs half-open datetime windows, 90-day inclusive renewal boundary), 2.10 Nested Path Resolution (left-to-right `ERR_NOT_FOUND`)
- **§3. Business Logic** — 3.1 Brand stewardship/lockdown/posture thresholds, 3.2 Product-line review loop + dilution cost + fiscal gates, 3.3 Formulations/manufacturers/grants + compartmentalization + 3-link for-cause cascade, 3.4 Markets/registrations + renewal windows, 3.5 Distributors/coverage cells (exclusivity, capacity 3, supersede, OCC), 3.6 Sell-through + ACTUAL/PROJECTED attainment + rebate preview, 3.7 Pack formats + price lists (supersede/clip, effective-price resolution), 3.8 Promotions (depth caps 25.00/15.00/5.00, MAP floor, frequency-before-gap, provisional vs actual funding, pinned case-price rounding with the 5088-not-5090 example, redemption budget), 3.9 Counterfeit enforcement + use-case moderation + genericization risk/gate
- **§4. Endpoint Definitions** — 82 rows, 4 columns
- **§5. Error Code Catalogue** — 62 rows, 2 columns; file ends here, no audit footer

## Coverage self-audit (scaffold → PRD)

- **Entities (15)**: every field of all 15 entities in §3 narrative — §3.1 Brand, §3.2 ProductLine, §3.3 Formulation/ContractManufacturer/ConfidentialityGrant, §3.4 Market/MarketRegistration, §3.5 Distributor/CoverageAssignment, §3.6 SellThroughReport, §3.7 PackFormat/ChannelPriceList, §3.8 Promotion, §3.9 CounterfeitCase/UseCaseSubmission. Contract 1: **114/114 identifiers present** (86 entity fields + endpoint inputs/outputs/path params + pagination), 0 missing.
- **State machines (14)**: all 70 transitions expressed with from/to states co-located in §3 prose; preconditions paired with exact error ids; side effects (cascades, recomputes, field stamps) stated.
- **Calculations (12)**: all expressed as precise prose — posture thresholds (2 breaches / severity 5 / sum 10 / ELEVATED 1 / sum 6 / 180-day window), genericization (100/50 bps, cap 10000, gate 500), dilution cost (400 + 150/extra channel + 200 novelty, cap 1000, pinned baseline), equity consumption (floor-half refund, 7000 floor, gate order), attainment (3-month window, floor-per-assignment quota, both variants, tier thresholds 12000/10000/9000), rebate (300/200/100/0 + 25 MASS bonus, cap 350), promo funding (PROVISIONAL smallest-pack tie-break; ACTUAL at redemption), case price (round once at unit level), compartmentalization (union × 2 ≤ component count; disclosed-pair count), renewal window (90 days inclusive), frequency gate (fewer than 2 peers within ±90 days, then 14-day gap), price resolution (greatest `effective_from`, earliest `created_at` tie-break).
- **Validations (13 rows)**: all in §2.6 in priority order with "first failure wins" semantics and every listed error id.
- **Endpoints (82)**: all paths verified present in §4 with method, description, and authorized roles; side effects narrated in §3; `/_clock/set_current_utc` correctly unprefixed.
- **Error codes (62)**: 62/62 in §5 table; 62/62 also mentioned in §2/§3 prose with trigger conditions.
- **Contract 3 (§3 path purity)**: 753 backticked tokens scanned, 0 path/method violations.

Orchestrator spot-check: 409 lines confirmed; §4 table has 82 endpoint rows (84 pipe-lines incl. header/separator); `/_clock/set_current_utc` explicitly stated as mounted outside `/brand-ops` in both §2.4 and the §4 preamble; clock default `2026-09-01T00:00:00Z` present in §2.4.

## Step 5a: Generate Test Helpers (Stage 1 of 2) — 2026-10-02T06:15:00.000Z

Step 5 split into 5a (helpers, frozen) then 5b (tests) per known output-cap failure mode (~98 non-stub design instances + 82-endpoint helper surface).

Stage 1 is complete. All shared test infrastructure is generated, compiles, and collects clean.

## Files written

| File | Lines | Contents |
|---|---|---|
| `test_helpers/__init__.py` | 28 | Barrel export (framework generics + all PRD-specific modules) |
| `test_helpers/types.py` | 425 | 24 enums + 15 entity TypedDicts |
| `test_helpers/api_client.py` | 472 | `ApiClient(GenericApiClient)` with 82 endpoint methods + `api_client` singleton |
| `test_helpers/api_errors.py` | 150 | `ApiErrorId` (62 errors) + `HTTP_STATUS_CODES` (62 mappings) + framework registration |
| `test_helpers/assertions.py` | 331 | 15 entity assertions + 4 computed-read assertions + 2 invariant checkers |
| `test_helpers/factories.py` | 193 | 15 payload factories |
| `test_helpers/constants.py` | 132 | ~50 PRD-pinned constants |
| `test_helpers/test_users.py` | 85 | `TEST_USERS` (11 roles) + 11 `make_*_headers` builders |
| `test_helpers/fixtures.py` | 454 | 43 fixture helpers across all 5 tiers |
| `test_suite/conftest.py` | 71 | `api` session fixture + 11 role-header fixtures |

## Public API surface (function names)

- **types.py**: enums `UserRole, Channel, BrandStatus, LockdownReason, ProtectionPosture, ProductLineStatus, FormulationStatus, VocClass, ManufacturerStatus, ManufacturerCapability, GrantStatus, GrantReason, DistributorStatus, QuotaComplianceTier, MarketStatus, VocRegime, RegistrationStatus, AssignmentStatus, DeliverySystem, PackFormatStatus, PriceListStatus, PromotionStatus, CounterfeitCaseStatus, UseCaseStatus, BrandReviewDecision, UseCaseReviewDecision`; TypedDicts for all 15 entities (SellThroughReport correctly omits `updated_at`/`version`).
- **api_client.py**: `set_clock` (unprefixed `/_clock/set_current_utc`) plus one method per §1.5 endpoint (82 total: create_brand … list_sell_through_reports).
- **assertions.py**: `assert_brand, assert_product_line, assert_formulation, assert_contract_manufacturer, assert_confidentiality_grant, assert_distributor, assert_market, assert_market_registration, assert_coverage_assignment, assert_pack_format, assert_channel_price_list, assert_promotion, assert_counterfeit_case, assert_use_case_submission, assert_sell_through_report` (asserts absence of `version`/`updated_at`), `assert_rebate_preview, assert_effective_price, assert_redemption, assert_clock_response, assert_brand_invariants, assert_distributor_invariants`.
- **factories.py**: `create_brand_payload, create_product_line_payload, create_formulation_payload, create_contract_manufacturer_payload, create_confidentiality_grant_payload, create_distributor_payload, create_market_payload, create_market_registration_payload, create_coverage_assignment_payload (OCC kwarg), create_pack_format_payload, create_price_list_payload (OCC kwarg), create_promotion_payload, create_counterfeit_case_payload, create_use_case_payload, create_sell_through_report_payload` — required fields defaulted, optional fields omitted unless overridden.
- **constants.py**: clock default `2026-09-01T00:00:00Z`, `CLOCK_PATH="/_clock/set_current_utc"`, posture thresholds (10/6/5/180d/2), genericization (100/50/10000/500), dilution (400+150+200 cap 1000), identity floor 7000, budget default 10000, attainment (3-month window, tiers 12000/10000/9000, quota divisor 4), rebate (300/200/100/0, +25 MASS, cap 350), renewal 90 days, promo caps 25.00/15.00/5.00 (max 90.00), frequency 2 peers/90 days, gap 14 days, cell capacity 3, max suspensions 3, components 3..12, scope fraction 1/2, severity 1..5, pagination 10/100, canonical window literals.
- **test_users.py**: `TEST_USERS` with 11 keys (`platform_admin_headers` … `consumer_headers`; canonical ids tso-1/pa-1/mm-1/ca-1 matching the design recipes) + `make_<role>_headers(user_id)` for all 11 roles; `make_distributor_contact_headers` documented as mandatory for ownership-gated calls.
- **fixtures.py**: Tier 1 atomic creators (incl. `advance_clock`, OCC auto-fetch `propose_coverage_assignment`/`create_price_list_record`, identity-threaded `file_sell_through_report`, `create_use_case_record`); Tier 2/3 composites (`setup_brand_with_market`, `setup_line_with_sealed_formulation`, `setup_compartmentalized_line`, `setup_pilot_line`, `setup_launched_line`, `setup_active_coverage`, `setup_submitted_promotion`, `setup_approved_promotion`, `setup_live_promotion`, `setup_active_registration`); Tier 4 (`file_reports`, `setup_distributor_with_attainment`, `setup_brand_with_open_cases`, `setup_brand_at_posture`, `create_flagged_use_cases`); Tier 5 (`setup_discontinued_line`, `setup_terminated_distributor`).

## Verification

- `python3 -m py_compile` + `ast.parse` passed for all 10 files.
- `pytest test_suite --collect-only -q` → `no tests collected in 0.18s` — zero tests, zero collection errors.
- Package import smoke test: 62/62 error IDs registered with the framework, 82 client endpoint methods (86 incl. 4 inherited convenience methods), 11 TEST_USERS keys, full fixture graph imports cleanly.

Key correctness points honored: clock helper hits the unprefixed `/_clock/set_current_utc`; everything else is under `/brand-ops`; GET endpoints with inputs (`rebate-preview`, `effective-price`) pass them as query params; OCC fields (`expected_distributor_version`, `expected_pack_format_version`) are first-class payload members with auto-fetch fixture variants; DistributorContact identity threading uses `make_distributor_contact_headers(distributor["id"])` inside the report fixture; no test files are imported by conftest; helpers never import from `test_suite`.

Orchestrator verification: all 10 files exist on disk with the reported sizes; `pytest --collect-only` reruns clean ("no tests collected"); `constants.py` spot-check confirms `CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"`, `CLOCK_PATH = "/_clock/set_current_utc"`, `TIER_GOLD_BPS = 12000`.

## Step 5b: Generate Test Suite (Stage 2 of 2) — 2026-10-02T06:55:00.000Z

All checks pass. Final summary:

## Stage 2 complete — 96 tests generated and verified

**Files written** (all under `test_suite/`):

| File | Tests | Contents |
|---|---|---|
| test_01_brands.py | 6 | brand create defaults/envelope, required field, computed-field ignore, lockdown/lift gates, posture-gated submit & exclusive activation |
| test_02_product_lines.py | 7 | review revision loop, core/line-code uniqueness, DISCONTINUED lockdown, third-reject auto-discontinue, core immutability, write-read consistency, list filters |
| test_03_equity_dilution.py | 5 | equity budget gate, identity floor gate, dilution base/cap edges, half-cost discontinue refund, novelty-baseline evaluation order (750 vs 550) |
| test_04_formulations_grants.py | 9 | formulation roundtrip, sealed/subset/reference gates, compartment cap at exactly half, safety>temporal priority, disclosed-count conservation, expiry sweep regression, ERR_GRANT_EXPIRED |
| test_05_manufacturers_breach.py | 3 | depth-3 for-cause revoke cascade, 90-day requalify block, grantor/revoker segregation |
| test_06_markets_registrations.py | 9 | country-code uniqueness, market-open gate, VOC regime, formulation-line mismatch, one-live-registration, reject/revise loop, renewal window boundary (exactly 90 days), expired renew, strictly-later expiry |
| test_07_packs_price_lists.py | 10 | initial status stamping, effective-price boundary + 404, MAP floor, enter-production gates, launch gate, retire gate, line-stage gates, half-open clip/supersede, price-list OCC |
| test_08_distributors.py | 6 | pagination, 404, entity-backed read, suspend/reinstate cycle, third-strike termination, APPLICANT proposal gate |
| test_09_coverage_assignments.py | 8 | registration-gated activation, closed-interval touch conflict, sweep auto-close, inverted windows, cell capacity 3/4, market close unblock, supersede, distributor OCC |
| test_10_attainment_rebate.py | 10 | ACTUAL-vs-PROJECTED divergence (4000 vs 9000), SANCTION cascade, rebate tier+bonus+cap (325 bps / 4865¢), report immutability, window exclusion, net-units floor, null-tier preview, duplicate report, ownership, period completion |
| test_11_promotion_lifecycle.py | 6 | state>fiscal priority, sweep LIVE→ENDED, suspended sweep survival + window-closed resume, funding-headroom conservation, segregation of duties, RBAC |
| test_12_promotion_gates.py | 8 | per-unit rounding (5088 not 5090), 25.00/25.01 cap boundary, provisional-vs-actual divergence (75 vs 90), MAP floor, 14-day gap, 90-day frequency, budget exact/over, pack-line mismatch |
| test_13_brand_defense_use_cases.py | 5 | genericization 500 bps gate, posture NORMAL/ELEVATED bands, submitter mismatch, launched-line gate, reject/retract paths |
| test_14_platform_validation.py | 4 | missing auth headers, role 403, existence-before-state 404, clock regression |

**Verification:**
- `pytest test_suite --collect-only -q`: **96 tests collected, 0 errors**
- AST audit (real parse, both yamls): expected 98 non-stub instances (19 Difficulty + 79 Corner; 10 corner `excluded_because:` stubs correctly untranslated); **emitted 96, missing 2 (== declared skips), extra 0, partition exact**
- Citation sweep: **182/182 PRD quotes survive literal grep** of PRD.md
- No skip/xfail markers; no scaffold references in test code; `test_helpers/` and `conftest.py` untouched (mtimes predate this stage)

**Skip list (2 instances, gaps stay gaps):**
1. `Corner/entities/formulation_component_count_limits` — PRD self-contradiction: §2.6 rule 4 assigns 400 `ERR_INVALID_REQUEST` to `component_codes` outside 1..12, while §3.3 assigns 422 `ERR_COMPONENT_LIMIT_EXCEEDED` to an oversized list; the 13-component outcome is not uniquely derivable.
2. `Corner/validations/channel_membership_trio` — the instance asserts an intra-priority-12 evaluation order (served → allowed → scope) that PRD §2.6/§3.5 never names; two of its three proposals trip multiple channel errors at once, so the asserted error_id is not uniquely derivable.

**Adjudication notes (PRD-first weakening inside otherwise-emitted instances):** absolute `version == 1` assertions were replaced by PRD-derivable relative increments ("increments by exactly one", §2.5/§2.7) since the PRD never pins the initial version value; the `updated_at` strictly-later assertion in `mutation_visible_in_same_response` was dropped (unobservable under a fixed logical clock); timestamp equality asserts use date-prefix matching (PRD pins instants, not string formats); pagination order asserts are tie-safe (set membership + non-decreasing `created_at`).

Orchestrator re-audit (independent AST walk, section/rule-id paths from the yamls' own `section`/`rule_id` keys): expected 98, emitted 96, EXTRA 0, MISSING exactly the 2 declared skips — subagent report confirmed. PRD contradiction for skip #1 confirmed by orchestrator grep: PRD.md line 121 (§2.6 priority 4: `component_codes` 1..12 → ERR_INVALID_REQUEST 400) vs line 179 (§3.3: oversized list → ERR_COMPONENT_LIMIT_EXCEEDED 422). Doc-generator feedback: a 13-component `component_codes` array is double-mapped; §2.6 rule 4 should scope the range check to exclude the array-size domain limit that priority 12 owns.

## Step 6: Generate Implementation — 2026-10-02T07:35:00.000Z

Done. The implementation is complete, compiles, and passed both smoke chains on fresh boots. Summary follows.

## Deliverable

`workspace/implementation/`

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 10 | Guarded pip install, `exec python3 app.py`, `$PORT`/`0.0.0.0`, foreground |
| `requirements.txt` | 1 | flask>=3.0,<4.0 |
| `app.py` | 73 | App factory, `POST /_clock/set_current_utc` (outside prefix), envelope error handlers (404/405 → `ERR_NOT_FOUND` envelope) |
| `core.py` | 329 | In-memory store (empty at boot, clock default `2026-09-01T00:00:00Z`), ApiError + all 62 PRD error IDs with HTTP statuses, envelope (`meta.api_request_id`/`api_request_timestamp` 3-fraction-digit, `response_type`, `data`), datetime/date/month parse+format, second-precision compare, Decimal half-up rounding, `stamp_new`/`touch` |
| `validate.py` | 212 | 11 roles, header auth (`X-User-ID`/`X-User-Role`), field validators, pagination (`limit` 1–100 default 10, `offset` default 0) |
| `derived.py` | 311 | Posture (2-breach/severity-5/sum≥10 → CRITICAL, LIVE-promo cascade), dilution (400+150/channel+200 novelty, cap 1000; freeze at PILOT; floor(half) refund), genericization (100/50, cap 10000, gate 500), disclosed_component_count, coverage re-eval, attainment ACTUAL/PROJECTED + tier + SANCTION strike cascade, rebate (300/200/100/0 +25 MASS, cap 350), price resolution |
| `sweep.py` | 87 | Registrations (RENEWAL_DUE at expires−90d inclusive, EXPIRED), grants (EXPIRED + coverage regress), price lists (SCHEDULED→EFFECTIVE→EXPIRED), promotions (LIVE/ENDED, never SUSPENDED), coverage CLOSED, posture recompute |
| `routes_brands.py` | 267 | Brands + lockdown/lift + product lines + brand-review/launch/discontinue |
| `routes_secret.py` | 341 | Formulations, manufacturers, grants incl. for-cause cascade |
| `routes_markets.py` | 276 | Markets + registrations (submit/approve/reject/revise/renew/revoke) |
| `routes_distribution.py` | 486 | Distributors, coverage assignments (OCC, supersede, cell capacity 3, closed-interval exclusivity), sell-through reports, rebate preview |
| `routes_pricing.py` | 250 | Packs, price lists (OCC, supersede/clip, half-open windows), effective-price |
| `routes_promo.py` | 263 | Promotions (SoD, depth caps 25/15/5, MAP floor, frequency ±90d <2, gap ≥14d, provisional funding), redemptions (round-once-at-unit: 499@15%×12 → 5088) |
| `routes_defense.py` | 219 | Counterfeit cases, use-case moderation |

**Endpoints: 83 routes = all 82 PRD §4 contract rows + `GET /brand-ops/brands`** (§3.1 prose says "brands may be listed" though the table omits it; extra route is harmless). Verified by programmatic diff of route decorators against the PRD table: zero missing.

**Isolation honored**: I read only `INSTRUCTION.md`, `SCAFFOLD.yaml`, `PRD.md` — never the design or test files. No test suite run.

**Smoke tests passed** (own server, dynamic ports, exact-PID kills only):
- Chain 1: brand → line → formulation seal → 2-manufacturer grant/activate → `COMPARTMENTALIZED` flip; scope cap `ERR_COMPARTMENT_SCOPE_EXCEEDED`; OCC bump + stale → `ERR_STALE_VERSION`; launch; coverage activate; report → attainment 5000/15000 bps, tier SANCTION → auto-suspend (count 1); rebate 25 bps/187 cents; promo approve → LIVE with provisional 75; SoD 403; redemption unit 75 / case **5088** (PRD's conformance example); sev-5 case → CRITICAL → promo SUSPENDED; genericization 50; `ERR_NOT_RESOURCE_OWNER`, `ERR_PERIOD_NOT_COMPLETED` verified.
- Chain 2 (sweep): promo APPROVED→LIVE→ENDED at date boundaries; grant EXPIRED at `expires_on`; assignment CLOSED; price list EXPIRED at `effective_to` while touching successor went SCHEDULED→EFFECTIVE; registration RENEWAL_DUE at exactly expires−90d (inclusive), renew→ACTIVE, `ERR_RENEWAL_WINDOW_NOT_OPEN` from ACTIVE, `ERR_REGISTRATION_EXPIRED` from EXPIRED; clock regression → 400; clock 404s under `/brand-ops`.

## Interpretation decisions (for Step 8)

1. **§2.6 category order beats §3 endpoint prose on conflict** (prompt pins §2.6 as "the" order). Applied at: grant action → scope cap (9) before `ERR_GRANT_EXPIRED` (10), contradicting §3.3's "re-verifies expiry then enforces compartmentalization"; coverage activate/resume → lockdown/posture (9) before window (10) before line/registration (11); promo resume → `ERR_PROMO_WINDOW_CLOSED` at category 8 before posture/lockdown (9), contradicting §3.8's listed order.
2. **Resume skips the line-LAUNCHED and exclusive-brand gates** (scaffold resume preconditions + §3.5's enumeration omit them).
3. **component_codes**: empty array or non-string items → `ERR_INVALID_REQUEST` (400); >12 entries → `ERR_COMPONENT_LIMIT_EXCEEDED` (422) per §3.3.
4. **Posture cascade** fires whenever a recompute yields CRITICAL (not only on transition edge) — keeps "no LIVE promotion while CRITICAL" invariant.
5. **Datetimes canonicalized** to `...Ttt:tt:tt.tttZ` on output regardless of input formatting; input datetimes must carry `Z`/offset; all comparisons at second precision.
6. **`version` starts at 1** (PRD names no initial value); recomputes that change nothing do not bump.
7. **Null tier → rebate_bps 0 with no MASS bonus** ("a null tier earns 0" read as the final rate).
8. **`ERR_REGISTRATION_EXISTS` blocking set includes REJECTED** (terminal = EXPIRED/REVOKED), but **market close is not blocked by REJECTED** (its set is DRAFT/SUBMITTED/ACTIVE/RENEWAL_DUE) — the spec genuinely uses two different sets.
9. **Promo "window covers starts_on"** evaluated at `starts_onT00:00:00Z` under half-open semantics.
10. **Redemption `units` ≥ 1**; zero rejected as `ERR_INVALID_REQUEST`.
11. **Registration reject `reason` required but not stored** (no such entity field; undeclared fields are never stored); **renew keeps original `submitted_at`/`approved_at`**.
12. **`api_request_timestamp` uses the logical clock**, never wall time (§2.4 "must not fall back to the host clock under any circumstance").
13. **OCC fields required** on the two guarded creates (missing → 400, mismatch → 412).
14. **For-cause revoke of a REQUESTED grant counts as a breach** in posture math (formula has no status qualifier; §3.3 mandates a posture recompute on that path).
15. **Sell-through**: bad/mismatched `coverage_assignment_id` → `ERR_INVALID_REFERENCE` (422, cat 5) fires before the ownership check (403, cat 6).
16. **Sponsoring-officer exclusion** from for-cause revocation is realized via RBAC (only ComplianceAuditor calls revoke); no separate error for auditor==sponsoring_officer_id exists in the catalog — only `ERR_AUDITOR_CONFLICT` vs `granted_by_user_id` is enforced.

Orchestrator verification: all 14 impl files exist on disk. PRD.md line 157 confirmed verbatim: "brands may be listed and individual brands retrieved" — the 83rd route traces to PRD prose; §4 table omission is doc-generator feedback (list-brands row missing from the endpoint table).

## Step 7: Test-Fix Iteration Loop — 2026-10-02T07:52:00.000Z

Summary:

- **Iterations run**: 2 (initial sweep → 1 fix → verification sweep).
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**:
  - `test_suite/test_09_coverage_assignments.py::test_cell_capacity_third_assignment_ok_fourth_fails` — the test proposed 4 assignments on the same cell up front, then tried to activate the first 3. PRD §3.5 (line 209) states verbatim: "Creation has one more side effect: any `PROPOSED` proposals already sitting on the same cell are moved to `SUPERSEDED`", so proposals 1-3 were SUPERSEDED before activation and the implementation correctly returned `ERR_INVALID_STATE_TRANSITION` ("Assignment is not PROPOSED"). The setup violated a PRD rule the implementation enforces faithfully (the sibling supersede test passes). Fixed by interleaving propose→activate via the existing `fx.create_active_assignment` helper for the first 3 assignments, then proposing a 4th and asserting its activation is refused with `ERR_CELL_CAPACITY_EXCEEDED` (PRD §3.5 line 211 verbatim: "a third coexists, a fourth is refused") and that it stays `PROPOSED`. All original assertions preserved; no weakening.
- **Fixes applied to `implementation/`**: none — the implementation was correct.
- **Final sweep evidence** (all 8 `results.${i}.json` retained on disk in `workspace/implementation/`):
  - round 1: 96/96, round 2: 96/96, round 3: 96/96, round 4: 96/96, round 5: 96/96, round 6: 96/96, round 7: 96/96, round 8: 96/96 — 0 failures, 0 errors in every round.

Orchestrator verification: all 8 `results.*.json` files exist on disk, each parsing to passed=96, failed=0, total=96, errors=0. Newest source file across implementation/ + test_suite/ + test_helpers/ (test_09_coverage_assignments.py, Step 7's fix) is OLDER than results.1.json — the final 8-round sweep post-dates every edit, so the evidence covers the shipped tree. Note for Step 8: the single Step 7 fix is test-side only (a fixture-shape bug against a PRD-verbatim rule); sibling unasserted paths around the supersede side effect (e.g., version/timestamp stamping on superseded proposals) plus the 16 Step 6 interpretation decisions were never failure-signaled and fall to Step 9's full scan.

## Step 8: Finalize PRD — 2026-10-02T07:58:00.000Z

Done. `workspace/PRD_FINALIZED.md` is written and verified byte-identical to `PRD.md` (`diff -q` and `cmp` both pass).

## Summary

**Line counts / %-delta:** PRD.md 409 lines, PRD_FINALIZED.md 409 lines — **byte-identical** (zero-edit outcome).

**Why zero edits — one bullet per diff item:**

- `test_suite/test_09_coverage_assignments.py::test_cell_capacity_third_assignment_ok_fourth_fails` (test_suite setup fix; no implementation/ or test_helpers/ changes) — no patch needed. Both behaviors the test tripped on are PRD-verbatim rules the implementation enforces faithfully:
  1. The create-side supersede side effect is stated at **PRD §3.5 line 209**: *"Creation has one more side effect: any `PROPOSED` proposals already sitting on the same cell are moved to `SUPERSEDED`, and the new assignment's `supersedes_assignment_id` points at the superseded proposal with the greatest `created_at` — or stays null when nothing was superseded."* The impl matches exactly (`implementation/routes_distribution.py` ~lines 313-325: collects same-cell PROPOSED proposals on the `(market_id, channel, product_line_id)` triple the PRD itself defines, sorts by `created_at`, sets all to SUPERSEDED, points `supersedes_assignment_id` at the latest). Under this rule, the original test's 4 up-front proposals left only the 4th PROPOSED — the setup was PRD-impossible.
  2. The activation refusal the buggy test hit is also PRD-determined: §3.5 line 211 pins activation's source state (*"Activation moves a `PROPOSED` assignment to `ACTIVE`"*) and global invariant §2 line 125 assigns `ERR_INVALID_STATE_TRANSITION` (409) to any transition the state machine does not admit — exactly what the impl returns at `routes_distribution.py:369`.
  3. The capacity behavior the fixed test asserts is PRD-verbatim at **§3.5 line 211**: *"the cell must currently hold fewer than 3 assignments in `ACTIVE` or `SUSPENDED` — a third coexists, a fourth is refused with `ERR_CELL_CAPACITY_EXCEEDED` (HTTP 409)"* — matched by `_cell_active_count` (`routes_distribution.py:79-91`, counts only ACTIVE/SUSPENDED on the cell) and the gate at lines 132-133. Step 7's final sweep (8/8 rounds, 96/96) confirms the interleaved propose→activate fixture is the PRD-legal path.

**Per-edit pre-edit search log:** no edits were committed, so no (a)/(b)/(c) entries apply. The mandatory verification reads behind the no-op decision: PRD lines 125, 209, 211, 213, 357, 384; impl `routes_distribution.py` (create side effect, `activate_assignment`, `_activation_gates`, `_cell_active_count`, resume/withdraw state gates); the fixed test at `test_suite/test_09_coverage_assignments.py:121-147` plus its sibling `test_new_proposal_supersedes_proposed_assignment_on_same_cell` (line 169), which independently asserts the line-209 rule. Since no wording changed, no new-mismatch exposure exists.

Orchestrator verification: `diff -q PRD.md PRD_FINALIZED.md` confirms byte-identical (409/409 lines). The zero-edit outcome was pre-authorized in the prompt (fixture-only Step 7 diff) and the subagent's no-op reasoning cites verbatim PRD lines that do cover the tripped rule.

## Step 9: Complete PRD — 2026-10-02T08:20:00.000Z

All edits verified — the file is structurally intact (balanced fences, complete error catalogue, 410 lines). The work is done. Final report:

---

## PRD_COMPLETED.md produced

**Source vs output:** `workspace/PRD_FINALIZED.md` 409 lines / 72,001 bytes → `workspace/PRD_COMPLETED.md` 410 lines / 75,358 bytes (+1 line — one added §4 table row — +3,357 bytes, 29 edit sites). Not byte-identical.

**Counts:** 17 ambiguity-pins, 8 mismatch-revisions (some spanning 2–3 paragraphs for consistency).

### Changes (section — insert|revise — kind — what — impl evidence)

- §2.2 — insert — ambiguity — `api_request_timestamp` is taken from the logical clock, never host clock — `core.py:127-131` (`_meta_base` uses `fmt_dt(now())`)
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` 400; `created_at` ties break toward earliest-created — `validate.py:184-206`, `core.py:328-329`
- §2.5 — revise — ambiguity — `version` starts at 1; a recompute/sweep that changes nothing does not bump `version`/`updated_at` — `core.py:313`, `derived.py:70-72,122-125,142-144,157-159,266-267`
- §2.6 rule 4 — revise — mismatch — `component_codes` removed from the 400 shape list except as "non-empty array of non-empty strings"; the 12-entry ceiling explicitly belongs to category 12 (`ERR_COMPONENT_LIMIT_EXCEEDED`) — `validate.py:115-121`, `routes_secret.py:66-67`
- §2.6 rule 5 — insert — ambiguity — added `home_market_id` and `manufacturer_id` to the body-reference existence list — `routes_distribution.py:148-149`, `routes_secret.py:179-184`
- §2.7 — revise — ambiguity — missing/malformed `expected_*_version` → 400 `ERR_INVALID_REQUEST`; only well-formed-but-stale → 412 — `routes_distribution.py:275,284-285`, `routes_pricing.py:154-157`
- §2.8 — revise — mismatch — percentages have *at most* two decimal places (was "exactly two"); added: all emitted datetimes canonicalized to ISO 8601 UTC with exactly three fractional digits — `validate.py:153-166`, `core.py:183-187,271-279`
- §3.1 — revise — ambiguity — lockdown admitted only from `OPERATING`, lift only from `PROTECTIVE_LOCKDOWN` (else `ERR_INVALID_STATE_TRANSITION`) — `routes_brands.py:91-92,105-106`
- §3.1 — revise — mismatch — posture cascade flips `LIVE` promos on *any* recompute yielding `CRITICAL`, even when posture was already `CRITICAL` — `derived.py:68-75`
- §3.3 — revise — ambiguity — `component_codes`: empty/non-string entries → 400; >12 entries → 422 — `routes_secret.py:59,66-67`
- §3.3 — revise — mismatch — **grant action order**: compartmentalization scope cap fires *before* the expiry re-verification (PRD said the reverse) — `routes_secret.py:239-253`
- §3.3 — revise — mismatch — `sponsoring_officer_id` is informational only; no exclusion of the sponsoring officer from for-cause revocations — **FLAGGED below** — `routes_secret.py:129,294`
- §3.4 — revise — ambiguity — reject `reason` is mandatory but validated-only, never stored; renew leaves `submitted_at`/`approved_at` untouched — `routes_markets.py:215`, `routes_markets.py:250-254`
- §3.5 — insert — ambiguity — supersede pointer: greatest `created_at`, ties broken toward most recently created — `routes_distribution.py:314-325`
- §3.5 — revise — mismatch — activation gate order aligned to §2.6 categories: distributor → [exclusive: lockdown, posture] → window → exclusivity → line-`LAUNCHED` → registration → capacity — `routes_distribution.py:95-133`
- §3.5 — revise — ambiguity — resume re-applies only distributor/window/exclusivity/registration/capacity; line-`LAUNCHED` and exclusive-brand gates are *not* re-applied — `routes_distribution.py:400-403` (`check_line_launch=False`)
- §3.5/§3.6 — revise — mismatch — SANCTION auto-suspension fires whenever a recompute *yields* `SANCTION` while `APPROVED`, whether or not the tier changed — `derived.py:268-269`
- §3.6 — insert — ambiguity — sell-through `coverage_assignment_id` reference failure (422) fires before the ownership check (403) — `routes_distribution.py:437-443`
- §3.6 — insert — ambiguity — rebate preview takes a required, non-negative-integer `reference_unit_price_cents` *query parameter* — `routes_distribution.py:239-247`
- §3.6 — revise — ambiguity — null tier earns rebate_bps 0 with *no* MASS bonus; bonus applies only to non-null tiers — `derived.py:276-282`
- §3.7 — insert — ambiguity — effective-price `channel` (required) and `at` (optional) are query parameters; missing/invalid channel → 400 — `routes_pricing.py:232-239`
- §3.8 — revise — mismatch — `discount_pct` "at most two decimal places" — `validate.py:162-163`
- §3.8 — revise — ambiguity — "covers `starts_on`" pinned to half-open containment of the `starts_on`T00:00:00Z instant (price support + provisional funding); reference list = governing list under §3.7 resolution — `routes_promo.py:34-35,148-155,180-186`
- §3.8 — revise — mismatch — promo resume guard order: `ERR_PROMO_WINDOW_CLOSED` → `ERR_POSTURE_CRITICAL` → `ERR_BRAND_IN_LOCKDOWN`; resume lands in `LIVE` — `routes_promo.py:209-218`
- §3.8 — insert — ambiguity — redemption `units` must be an integer ≥ 1 (else 400) — `routes_promo.py:230`
- §3.8/§3.9 — revise — mismatch — cascade wording aligned to "whenever a recomputation yields CRITICAL" (was "the moment it becomes/became") — `derived.py:73-75`
- §4 — insert — ambiguity — added `GET /brand-ops/brands` (List brands) table row; impl exposes it and §3.1 prose already allowed it — `routes_brands.py:71-75`

### Candidate impl gaps (PRD rule omitted by impl)

1. **§3.3 sponsoring-officer exclusion.** PRD_FINALIZED stated: *"The onboarding officer's `X-User-ID` is recorded as `sponsoring_officer_id`; that officer is thereafter excluded from performing for-cause revocations of this manufacturer's grants."* The rule is implementable and self-consistent (it parallels the `granted_by_user_id` segregation check), but **no code enforces it**: `routes_secret.py:294` checks only `user_id == g["granted_by_user_id"]` → `ERR_AUDITOR_CONFLICT`, and `sponsoring_officer_id` is written (`routes_secret.py:129`) but never read by any gate. PRD_COMPLETED.md revises the sentence to "informational only … gates no later operation" to match impl. Orchestrator should adjudicate: either restore the rule in impl (compare caller against `sponsoring_officer_id` on for-cause revokes, presumably also `ERR_AUDITOR_CONFLICT`) or accept the PRD revision.

### Verdicts on the 16 known interpretation sites

1. Category-order conflicts — **pinned-by-this-edit** (§3.3 grant: scope-cap before expiry; §3.5 activate/resume: §2.6 category order; §3.8 promo resume: window-closed → posture → lockdown)
2. Resume gate subset (no line-`LAUNCHED`, no exclusive-brand gates) — **pinned-by-this-edit** (PRD's five-item list was near-pinning but conflicted on exclusivity-vs-registration order; now explicit)
3. `component_codes` empty/non-string → 400, >12 → 422, §2.6-vs-§3.3 double-map — **pinned-by-this-edit** (both passages revised)
4. Posture cascade on any recompute yielding CRITICAL — **pinned-by-this-edit** (§3.1, §3.8, §3.9)
5. Datetime canonicalization + second-precision comparison — **pinned-by-this-edit** (§2.8; second precision was already pinned)
6. `version` starts at 1; no-op recomputes don't bump — **pinned-by-this-edit** (§2.5)
7. Null tier → rebate_bps 0, no MASS bonus — **pinned-by-this-edit** (§3.6)
8. `ERR_REGISTRATION_EXISTS` blocking set includes REJECTED; market-close set excludes it — **already-pinned** ("non-terminal" + "EXPIRED and REVOKED are terminal"; close set explicit; impl `routes_markets.py:25,78-83` conforms)
9. "Covers `starts_on`" at `starts_on`T00:00:00Z half-open — **pinned-by-this-edit** (§3.8)
10. Redemption units ≥ 1 — **pinned-by-this-edit** (§3.8)
11. Reject `reason` required-not-stored; renew keeps `submitted_at`/`approved_at` — **pinned-by-this-edit** (§3.4)
12. `api_request_timestamp` uses the logical clock — **pinned-by-this-edit** (§2.2)
13. OCC field missing → 400, mismatch → 412 — **pinned-by-this-edit** (§2.7, both creates)
14. For-cause revoke of a REQUESTED grant counts as a breach — **already-pinned** (§3.1 breach definition has no pre-revocation status filter; §3.3 confirms a posture recompute follows; impl `routes_secret.py:299-301` + `derived.py:49-52` conform)
15. Sell-through `ERR_INVALID_REFERENCE` (422) before ownership (403) — **pinned-by-this-edit** (was derivable from §2.6 rule 5<6; made explicit in §3.6)
16. For-cause revoke SoD only vs `granted_by_user_id` — **pinned-by-this-edit and flagged-as-gap** (the `sponsoring_officer_id` exclusion was an omitted PRD rule; see gap section)

---

Orchestrator adjudication of the flagged gap (sponsoring-officer exclusion) — **revision ACCEPTED, no impl change**. Ground truth from SCAFFOLD.yaml (orchestrator-only read): the field description (line 97) does assert the exclusion, but ALL THREE revoke transition preconditions (lines 415/424/435) name only `granted_by_user_id` → `ERR_AUDITOR_CONFLICT`, the segregation-of-duties validation row (line 1187) enumerates only "for-cause revoker vs grantor", and the 62-code error catalog contains no error for a sponsoring-officer violation. The scaffold is self-contradictory between a descriptive field note and its normative behavioral sections; the normative sections shadow the note (the exoneration class for exactly this case). Enforcing the exclusion would require inventing an error mapping neither scaffold nor PRD names — violating unique derivability in the opposite direction — and would add a gate no test asserts, invalidating the green sweep for zero measured behavior. The PRD_COMPLETED.md wording ("informational only … judged solely against `granted_by_user_id`") is the coherent resolution. Feedback for scaffold-generator: don't assert exclusion semantics in a field description without a matching transition precondition + error mapping.

Orchestrator verification: PRD_COMPLETED.md exists at 410 lines, differs from PRD_FINALIZED.md (not a silent no-op), §4 gained the `GET /brand-ops/brands` row (line 261), the §3.3 sponsoring-officer revision reads cleanly (line 183), and the file still ends with the complete error catalogue.

## Pipeline Complete — 2026-10-02T08:25:00.000Z

Final output-contract verification: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml + worklog.md present; test_helpers/ 9 files; test_suite/ 14 test files = 96 tests collected clean; workspace/ INSTRUCTION.md + PRD.md + PRD_FINALIZED.md (byte-identical to PRD.md) + PRD_COMPLETED.md (410 lines); implementation/ start.sh + requirements.txt + 12 source modules + results.1..8.json (each 96/96/0/0). `find -name "*.py" -newer results.1.json` → 0 files: the final 8-round sweep post-dates every source edit, evidence valid. Final state: **96/96 tests passing across all 8 parallel rounds; pipeline done in 2 Step-7 iterations with 1 test-side fix and 0 implementation fixes.**
