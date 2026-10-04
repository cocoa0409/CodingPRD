# Worklog — task_3483_seized_asset_custody_valuation_disposition

## Step 1: Create Task Directory — 2026-10-02T14:17:00.000Z

Task directory pre-allocated by the caller: `./tasks/task_3483_seized_asset_custody_valuation_disposition/` with `workspace/` inside. Verified it exists and is empty; no index computed, no other directory created.

## Step 2: Generate Scaffold — 2026-10-02T15:23:00.000Z

All three artifacts are complete, parse cleanly, and pass the linter. Final report:

## Scaffold generated: task_3483_seized_asset_custody_valuation_disposition

**Design** (compliance/audit primary, ledger-reconciliation secondary; flat topology; segregation-of-duties role model; parallel state dimensions):

- **9 entities** — SeizureCase, Asset (dual independent state dimensions: `custody_state` × `legal_state`), CustodyTransfer, Valuation, ExpenseEntry (append-only ledger, reversal-by-compensating-entry), InterlocutorySaleRequest, ThirdPartyInterest (liens + innocent-owner claims, cyclic appeal loop capped at 1), SaleEvent, Distribution.
- **39 endpoints** (deliberately kept under the >40 impl-gen danger line; clock lives unprefixed at `POST /_clock/set_current_utc` with the mandated `2026-09-01T00:00:00Z` startup default).
- **25 errors, 10 ordered validation tiers, 9 roles, 7 calculations, 2 OCC concurrency rules** (valuation-create and ISR-create, both on `Asset.version`).

**Difficulty drivers** (all nine §0.5 rules × 2 instances = 18): dual-variant retention estimate (provisional-vs-final on Asset) vs gross/net sharing-pool basis (Case); combinatorial formulas in modes (a) tiered-forward-looking interlocutory eligibility and (b) INCOME_APPROACH per-year-round-then-sum (9900 vs 9901 pinned divergence); transitive cascades depth-3 (ISR approval → legal/custody flip → scheduled transfers cancelled → accrual-sweep exclusion, proven by two clocked `run-holding-review` calls) and depth-2 (innocent-owner grant → RETURN_PENDING → auction cancelled); priority conflicts (state-beats-fiscal on ISR, constraint-beats-temporal on sale slots); inclusive boundaries (ratio exactly at 0.30; bid == reserve sells) with all formula literals pre-computed in Python; contiguous-chain custody windows vs half-open auction slots; compensating invariants on holding-cost accumulator and case proceeds pool.

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(39 endpoints, 9 entities, 18 §1.8 instances, 39 active §1.9 instances + 5 excluded stubs, 498 calls scanned.)

**Additional audits run:** zero forbidden concurrency vocabulary; zero unbound `${var}` placeholders; all grounds resolve; all 25 errors referenced by §1.2/§1.4/§1.5 and named in at least one test instance; instance names unique across both design files; enum values all have producers.

**Mid-course correction worth noting:** I initially drafted an `ERR_GRANTED_CLAIM_OUTSTANDING` retain-gate, then realized the innocent-owner grant cascade (which fires on every non-terminal legal state) made the check unreachable — dead code a green sweep would never catch. Removed the error and reshaped the rule: GRANT cascades only from `{SEIZED, VALUATION_PENDING, VALUED, DISPOSITION_REVIEW, SALE_AUTHORIZED}`, filings against RETAINED assets are admitted, and a corner instance (`claim_grant_on_retained_asset_does_not_cascade`) pins the conditional-cascade behavior. Also widened asset intake to allow FORFEITED cases (substitute-asset seizures) after spotting that most settle-flow recipes forfeit before creating the asset.

Files: `/home/ubuntu/github/CodingPRD/tasks/task_3483_seized_asset_custody_valuation_disposition/SCAFFOLD.yaml` (1030 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1242), `SCAFFOLD_CORNER_DESIGN.yaml` (1821).

Orchestrator verification: all three files exist, parse as YAML; SCAFFOLD.yaml has no `scaffold_difficulty_design`/`scaffold_corner_design` keys; design files have the single correct top-level key each; api_prefix `/custody`; 9 scenario entities (SeizureCase, Asset, CustodyTransfer, Valuation, ExpenseEntry, InterlocutorySaleRequest, ThirdPartyInterest, SaleEvent, Distribution); 39 endpoints.

## Step 3: Copy Shared Files — 2026-10-02T15:24:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_3483_seized_asset_custody_valuation_disposition/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-10-02T15:47:00.000Z

Done. The PRD is written to `/home/ubuntu/github/CodingPRD/tasks/task_3483_seized_asset_custody_valuation_disposition/workspace/PRD.md` — 291 lines, generated incrementally in 11 chunks from `SCAFFOLD.yaml` only (the two design-index files were never opened).

**Section list:**
- §1 Introduction (2 paragraphs + API mount note)
- §2 Global Specifications: 2.1 RBAC (9 roles, opaque identity per role, audit-field recording), 2.2 Response Structure (byte-verbatim match confirmed), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 The Logical Clock (startup default `2026-09-01T00:00:00Z`, `to_iso8601`), 2.5 Common Resource Properties, 2.6 Monetary Precision and Rounding (integer cents, round-half-up via the +5,000/÷10,000 formulation in prose), 2.7 OCC, 2.8 Dual-Track Asset State Model, 2.9 Cascading Consistency and the Append-Only Ledger, 2.10 Validation Pipeline and Ordering (all 10 tiers, first-failure-wins, SoD-after-state illustration, tier-9 floor-before-ratio internal order), 2.11 Resource Discovery and Nested Validation
- §3 Business Logic: 3.1 case/forfeiture track (dismiss 2-link cascade, `RETAINED` carve-out), 3.2 intake/custody transfers (window contiguity, kind→state mapping ×4), 3.3 valuation & retention (method-specific inputs, per-year-then-sum income rounding pinned with the 9,900-vs-9,901 divergence, both retention variants, floor-then-ratio gates), 3.4 holding costs & ISR (append-only ledger, idempotent monthly sweep, 30% inclusive ratio, 3-link approval cascade), 3.5 liens/innocent owners/appeal loop, 3.6 auctions/settlement/waterfall (tiered marginal fee, gross vs net basis), 3.7 equitable sharing (approve/rescind compensating pair, re-check at approval), 3.8 returns & depreciation disputes
- §4 Endpoint Definitions (39 rows, 4 columns)
- §5 Error Code Catalogue (25 rows, 2 columns)

**Contract 1 (Field-Name Coverage): PASS**
- entities[].fields: 76 required, 76 present, 0 missing
- endpoints[].request_body: 44 required, 44 present, 0 missing
- endpoints[].query_params: 2 required, 2 present, 0 missing
- path params: 1 required (`id`), 1 present
- Two gaps found on the first pass (`status`, `ACCEPTED`) were repaired and the diff re-run to empty.

**Contract 2 (Rule Coverage): PASS**
- validations[] with priority: 10 checked, 10 expressed in §2.10's ordered pipeline (incl. floor-before-ratio intra-tier order and the SoD-fires-after-state ordering example), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (`expected_asset_version` on valuation submission and ISR filing, mismatch → `ERR_STALE_VERSION` HTTP 412, rationale per rule), 0 missing
- state_machines[].transitions: 43 checked, 43 fully expressed (all cascade links enumerated; every state token of the 43-state vocabulary appears backticked), 0 missing
- calculations[]: 7 checked, 7 fully expressed as precise prose (no operator syntax; reconstruction-safe), 0 missing
- validations[] conditions: 25 errors checked, 25 matchable to `error_id` in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (incl. ISR-creation asset version bump, sweep response fields `assets_reviewed`/`accruals_posted`, `posted_by_user_id` "system", denied-lien position release, `RETAINED`-filing carve-out), 0 missing
- entities[].fields[] structured content: defaults/initials/required-vs-null rules all reconstructible (verified via 30 targeted anchors, all OK), 0 missing
- sibling-branch symmetry: custody mappings ×4, TPI outcomes ×3, close/rescind branches ×2, retention variants ×2, sharing bases ×2 — equal density, 0 asymmetric

**Contract 3 (§3 Path Purity): PASS**
- backtick tokens scanned: 559; tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path combined tokens: 0

§2.2 matches the canonical block byte-for-byte (verified by substring equality against `section-2.2-response-structure.md`).

Orchestrator verification: PRD.md exists (290 lines), opens with the seized-asset/USMS scenario prose, 57 `ERR_` token mentions present.

## Step 5a: Generate Test Helpers (Stage 1 of split Step 5) — 2026-10-02T16:08:00.000Z

Stage 1 is complete and frozen. All 10 files parse, compile, and import cleanly; the package's public surface is verified.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_3483_seized_asset_custody_valuation_disposition/`)

| File | Lines | Exports |
|---|---|---|
| `test_helpers/types.py` | 381 | 23 enums (`UserRole`, `CaseStatus`, `AssetType`, `ConditionGrade`, `CustodyState`, `LegalState`, `RetentionDecision`, `LocationKind`, `TransferStatus`, `ValuationMethod`, `ValuationStatus`, `EntryKind`, `ExpenseType`, `ExpenseSource`, `IsrStatus`, `InterestKind`, `InterestStatus`, `SaleMethod`, `SaleStatus`, `DistributionKind`, `UsageRestriction`, `DistributionStatus`, `ForfeitureType`) + 9 entity TypedDicts (`SeizureCase` … `Distribution`), all carrying `id/created_at/updated_at/version` per PRD §2.5 |
| `test_helpers/api_errors.py` | 80 | `ApiErrorId` (25 errors), `HTTP_STATUS_CODES`; registers the map with the framework at import time |
| `test_helpers/constants.py` | 250 | `CLOCK_EPOCH="2026-09-01T00:00:00Z"`, `CAPITALIZATION_BPS`, `CONDITION_FACTOR_BPS`, `PROVISIONAL_PROJECTION_MONTHS`, `RETENTION_VALUE_FLOOR_CENTS`, `MONTHLY_CARRYING_COST_CENTS`, `ISR_PROJECTION_MONTHS`, `INTERLOCUTORY_RATIO_THRESHOLD_PCT`, `TIER1/2_*`, `TIER3_BPS`, `APPEAL_LIMIT`, `EQUITABLE_SHARE_MIN_CENTS`, `GRADE_RANK`, `DEPRECIATION_*`, `DISPUTE_WINDOW_DAYS`, `TEST_DEFAULTS` + calc helpers `rhu`, `condition_adjusted_value`, `income_capitalized_value`, `auction_fee`, `projected_burden`, `is_interlocutory_eligible`, `provisional_net_retention_value`, `final_net_retention_value`, `full_months_held`, `expected_depreciation` |
| `test_helpers/api_client.py` | 273 | `ApiClient(GenericApiClient)` with 39 endpoint methods; `create_api_client(base_url=None)` factory — **no module-level singleton** (see below). `set_clock()` posts `{"to_iso8601": ...}` to `/_clock/set_current_utc` **without** the `/custody` prefix; all 38 business methods are `/custody/...`-prefixed |
| `test_helpers/assertions.py` | 296 | `validate_created` (explicit 201), `validate_action` (explicit 200), `assert_common_fields`, 9 `assert_<entity>()` checkers, `assert_case_pool_invariants` (available == net − paid; gross == net + liens + cost-reimb), `assert_holding_cost_non_negative` |
| `test_helpers/factories.py` | 204 | `unique_case_number`, `unique_petitioner_ref`, `create_{case,asset,custody_transfer,valuation,expense_entry,isr,lien,innocent_owner,sale_event,distribution}_payload` — valuation factory is method-conditional (INCOME_APPROACH shape vs raw+grade shape), TPI split into lien vs innocent-owner (nulls carried explicitly) |
| `test_helpers/test_users.py` | 148 | 12 user-id constants (`CASE_AGENT_USER_ID` … `SYSTEM_OPERATOR_USER_ID`, incl. `SECOND_*` for both SoD pairs), `TEST_USERS` (12 header dicts), 9 `make_<role>_headers()` builders; `make_claimant_headers(petitioner_ref)` is the identity-pinned path for file/appeal |
| `test_helpers/fixtures.py` | 682 | 47 composite helpers: clock (`set_clock`), reads (`get_asset/get_case/fresh_asset_version`), case lifecycle (`create_case_in_state`), valuation pipeline (`submit_valuation` with OCC auto-reread, `accept/reject_valuation`, `create_valued_asset`), ledger (`post_expense`, `post_accumulated_cost`), transfers (`next_contiguous_window`, `schedule_transfer`, `move_asset`, `move_asset_to_storage`), disposition (`decide_retention`, `authorize_sale`, `create_sell_authorized_asset`), TPI (`file_lien`, `verify_lien`, `file_innocent_owner_claim`, `adjudicate_interest`, `appeal_interest`), ISR (`create_isr`, `adjudicate_isr`, `create_isr_eligible_asset`), sales (`schedule_sale_event`, `close_sale_event`, `settle_sale_event`, `create_settled_sale` with costs/liens params), distributions (`create/approve/rescind_distribution` with SoD-distinct defaults), return track (`create_return_pending_asset`, `hand_over_to_claimant`, `create_returned_asset`, `create_disputed_asset`), `run_holding_review` |
| `test_helpers/__init__.py` | 56 | Barrel: framework generics + all of the above |
| `test_suite/conftest.py` | 74 | Session `api` fixture (returns `create_api_client()`) + 12 role-header fixtures |

## Key decisions and verification results

- **Clock unprefixed**: `set_clock` hits `/_clock/set_current_utc` with field `to_iso8601` (matches SCAFFOLD line 950, PRD §2.4, and every design recipe); all business methods carry `/custody`.
- **Clock reachability**: every default timestamp (`seized_on`, windows, slots) is ≥ 2026-09-01T00:00:00Z; factories are safe against a fresh boot.
- **Constants**: all 32 literal greps against PRD.md prose pass; no scaffold-only or losing-value constants. Helper math smoke-tested: income-approach `[10001,10001,10001] → 9900` (pinned per-year rounding), fee `2,000,000 → 170,000`, burden boundary `75,000 vs 74,999` on a 500,000 VEHICLE, depreciation `315,000` for the GOOD→POOR/3-month design case.
- **Import safety (hard requirement #6)**: verified `import test_helpers.api_client as ac` binds the **module** (the singleton-shadowing trap was reproduced with the skill's template shape and then eliminated by switching to the `create_api_client()` factory; `fixtures.py` holds a module-local `_api`). Stage 2 must import `create_api_client`/`ApiClient` or use the `api` pytest fixture — there is intentionally no `test_helpers.api_client` instance export.
- **Identity model**: all roles opaque per PRD §2.1; petitioner-pinned Claimant calls thread through `make_claimant_headers(ref)`; both SoD pairs have second identities (`co-lane`, `fa-lenovo`).
- No test files written; helpers are frozen for Stage 2.

Orchestrator verification: all 10 files present; `python3 -m py_compile` passes on all; `api_client.py` posts to `/_clock/set_current_utc` without prefix. Measured design queues from YAML myself: queue A = 18 active difficulty instances (0 stubs); queue B = 39 active corner instances + 5 `excluded_because` stubs (NOT to be translated). Total expected tests: 57.

## Step 5b: Generate Test Suite (Stage 2 of split Step 5) — 2026-10-02T16:58:00.000Z

STAGE 2 complete. All audits pass.

**Output:** 10 test files in `/home/ubuntu/github/CodingPRD/tasks/task_3483_seized_asset_custody_valuation_disposition/test_suite/`, exactly **57 test functions** (18 difficulty + 39 corner), matching the orchestrator-measured queue sizes. **Zero skips** — every active instance passed the PRD-first two-condition filter (all asserted rules have verbatim PRD coverage and unique derivability). The 5 `excluded_because` stubs (`income_approach_rounding_order`, `provisional_variant_prefers_submitted`, `cascade_side_effects_layer`, `dual_variant_calculation_layer`, `rate_threshold_layer`) were not translated; all their difficulty-instance cross-references resolve.

**Per-file test counts:**
- `test_01_case_and_asset_intake.py` — 7 (creation defaults, round-trips, pagination, computed-field init, system fields, expense default, read-after-write)
- `test_02_intake_error_probes.py` — 8 (404s, missing/invalid fields, 401 bogus role, 403 role gate, p2/p3-before-p4 ordering, duplicate case number)
- `test_03_valuations_and_retention.py` — 6 (accept side effects, double adjudication, RETAINED lockdown, floor/ratio gates, provisional-vs-final dual variant, INCOME_APPROACH rounding order)
- `test_04_custody_and_returns.py` — 5 (parallel state dimensions, window contiguity, physical-handover guard + depreciation 315000, expired dispute window, depreciation cap-then-resolve)
- `test_05_interlocutory_sales.py` — 6 (tier-divergent eligibility, inclusive 30% boundary, VALUED gate, state-beats-fiscal priority, 3-link approval cascade, ISR SoD)
- `test_06_third_party_interests.py` — 6 (appeal cycle + ERR_APPEAL_EXHAUSTED, innocent-owner grant cascade, no-cascade on RETAINED, outcome/kind mismatch both directions, priority conflict frees after deny, appeal identity pinning)
- `test_07_sale_events_and_settlement.py` — 9 (bid==reserve boundary, half-open slot overlap, slot-constraint-beats-temporal, reserve/active-sale rejections, tiered fee 440000, waterfall priority + partial lien, gross-vs-net pool basis, dismiss cascade, dismiss-FORFEITED 409)
- `test_08_distributions.py` — 4 (ERR_CASE_NOT_FORFEITED, 9999/90001/90000 pool boundary, distribution SoD, approve/rescind pool conservation)
- `test_09_expense_ledger_and_holding_review.py` — 3 (COST/REVERSAL conservation at 80000, ERR_NEGATIVE_HOLDING_COST floor, idempotent filtered accrual sweep)
- `test_10_occ_and_versioning.py` — 3 (valuation OCC 412, ISR OCC 412, version 1→4 mutation counter)

**Hard-requirement compliance:** one file per message; all imports from `test_helpers` (frozen helpers untouched); `api` fixture for raw/negative calls, fixture helpers for happy paths; clock only via `set_clock` (all datetimes ≥ 2026-09-01T00:00:00Z, forward-only); `validate_created` (201) for creates, `validate_action`/200 for actions, `validate_error` with the registered status map; OCC flows use `fresh_asset_version` / explicit expected versions; `validate_paginated` for list endpoints.

**Audits run (subagent):**
- AST tag audit: 57 functions, each with exactly one `Design:` tag; 0 missing instances, 0 unknown tags, 0 stubs emitted, 0 dual/untagged tests.
- PRD verbatim sweep: 129 citation fragments extracted from docstrings, all grep clean against `workspace/PRD.md` (5 initial misses were dropped `**bold**` markers on §2.10 tier names; fixed in place).

**Final collect-only line (verbatim):** `57 tests collected in 0.25s`

Orchestrator re-verification (independent AST parse): 57 test functions, 0 untagged/dual-tagged; 57 valid active design tags (18 Difficulty + 39 Corner); 0 emitted tags outside design; 0 design instances missing tests; 5 corner `excluded_because` stubs correctly untranslated. `pytest --collect-only` → `57 tests collected`.

## Step 6: Generate Implementation — 2026-10-02T17:44:00.000Z

The implementation is complete and verified. Here is the final summary.

## Files written (22 files, all in `/home/ubuntu/github/CodingPRD/tasks/task_3483_seized_asset_custody_valuation_disposition/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| start.sh | 10 | Foreground launcher: guarded `pip install`, `exec python3 app.py`, `$PORT` (default 10000 per INSTRUCTION.md), binds 0.0.0.0 |
| requirements.txt | 1 | flask>=3.0 |
| app.py | 73 | Flask app factory, blueprint registration, envelope-wrapped error handlers (ApiError, 404, 405, 500) |
| constants.py | 147 | Every PRD-pinned constant, defined exactly once (CAPITALIZATION_BPS=3300, CONDITION_FACTOR_BPS, MONTHLY_CARRYING_COST_CENTS, PROVISIONAL_PROJECTION_MONTHS=6, ISR_PROJECTION_MONTHS=3, INTERLOCUTORY_RATIO_THRESHOLD_PCT=30, RETENTION_VALUE_FLOOR_CENTS=500000, TIER1/2/3 fee caps+bps, DEPRECIATION_*=800/50/6000, DISPUTE_WINDOW_DAYS=30, APPEAL_LIMIT=1, EQUITABLE_SHARE_MIN_CENTS=10000, all enum domains, roles) |
| errors.py | 75 | ApiError + all 25 catalog error IDs with fixed HTTP statuses |
| clock.py | 31 | Logical clock, default exactly 2026-09-01T00:00:00Z, never wall-clock fallback |
| store.py | 88 | In-memory dicts (9 collections), common-field stamping, version/touch, pool rederivation; no seeding |
| util.py | 171 | ISO-8601 parse/format (3 fractional digits), RHU floor formula, tier-3 field validators, pagination (limit 1–100 default 10, offset ≥ 0) |
| response.py | 49 | Verbatim envelope: `meta`/`response_type`/`data`, error shape, list pagination meta |
| middleware.py | 40 | Tier-1 auth (X-User-ID/X-User-Role), tier-2 role gates, business-role helper |
| calc.py | 155 | condition-adjusted valuation (per-year INCOME rounding), dual retention variants, integer eligibility ratio, tiered marginal auction fee, depreciation with whole-months rule |
| serialize.py | 173 | One serializer per entity; retention variants derived at read time |
| routes_cases.py | 163 | case CRUD, file-forfeiture/forfeit/dismiss with 2-link dismiss cascade |
| routes_assets.py | 262 | intake, read, decide-retention (floor-before-ratio), authorize-sale, initiate/complete-return, dispute/resolve |
| routes_transfers.py | 119 | scheduling with contiguous-window chaining, completion custody mapping |
| routes_valuations.py | 152 | OCC-guarded submission (SEIZED→VALUATION_PENDING), adjudication incl. DISPOSITION_REVIEW revert |
| routes_expenses.py | 93 | append-only ledger, STORAGE_ACCRUAL reserved, non-negative accumulator guard |
| routes_isr.py | 122 | OCC + ratio gate + snapshots, SoD adjudication, 3-link approval cascade |
| routes_interests.py | 212 | kind/field consistency, petitioner identity, priority-position uniqueness, outcome-kind compatibility, appeal loop, grant cascade |
| routes_sales.py | 225 | slot guards, close (NO_SALE keeps asset listable), settle: fee schedule + lien-first waterfall + case pool accumulators |
| routes_distributions.py | 139 | equitable-share create/approve/rescind with SoD and pool-conserving compensation |
| routes_ops.py | 75 | `/custody/run-holding-review` sweep (idempotent per asset per calendar month) + unprefixed `POST /_clock/set_current_utc` |

Total: 2,575 lines. Dependency graph: `constants`/`errors` are leaves; `util`→errors; `clock`→constants; `store`→util; `response`→util; `middleware`→errors+constants; `calc`→constants+util; `serialize`→calc+store; `routes_*`→(store, serialize, middleware, util, response, errors, calc/clock, constants); `app`→all routes modules. No cycles.

## Verification results

- **Route inventory**: exactly **38 business endpoints under `/custody`** + **1 unprefixed clock endpoint** at app root (verified via `url_map`).
- **Constant audit (AST)**: every UPPER_CASE name used is defined exactly once; 52 constants + 25 error IDs import cleanly. No undefined-constant risk.
- **Compile**: all 20 modules byte-compile.
- **Boot 1 smoke** (dynamic port 54741): 68 checks, all PASS — verbatim tail `SMOKE OK (boot 1)`. Covered: envelope/meta shape, 401/403/404/409/412/422 paths, valuation math (RHU(1000001×7500)=750001; INCOME [10001,10001,10001]→9900 per-year-rounded), OCC, window chaining, holding-review idempotency per month, retention floor-then-ratio ordering, full waterfall (bid 200000 → fee 20000 → liens 3000+2000 → cost reimb 80000 → net basis 95000), distribution SoD/approve/rescind pool conservation.
- **Boot 2 fresh-boot smoke** (ports 39679, then fresh 35135): 43 checks, all PASS — verbatim tail `SMOKE OK (boot 2)`. Covered: fresh store after reboot (boot-1 case → 404), RETAIN success, grant-on-RETAINED without cascade, ratio-blocked RETAIN (422), ISR snapshots + SoD + approval cascade cancelling SCHEDULED transfers, slot adjacency vs conflict, NO_SALE re-list, dismiss cascades (assets→RETURN_PENDING, open sales→CANCELLED, blocked when SOLD), depreciation (EXCELLENT→POOR + 3 months → 255000; day-boundary months → 10000), dispute window expiry, pagination meta.
- **Double-boot**: server killed by exact PID and relaunched twice; both reboots clean with empty state. Only PIDs I started were killed (2370348, 2370351, 2372908, 2373433); all smoke servers are now down and ports free.

## Key interpretation decisions (traced to PRD/scaffold)
- `created_at`/`updated_at`/`api_request_timestamp` use wall-clock UTC (scaffold guarantees created_at tie-breaks impossible, which a frozen logical clock would violate); logical clock drives only the pinned time-relative rules.
- Tier-ordered validation per PRD §2.10: e.g. active-sale (8) → reserve (9) → slot-in-past (10); retention floor before ratio; OCC before state gates.
- Second and later valuation submissions do not bump asset version (scaffold attaches the bump only to the SEIZED→VALUATION_PENDING transition); ISR creation does bump it.
- Waterfall-created distributions are born PAID with `created/approved_by_user_id = "system"`; rescinding a PAID system-kind distribution voids it without touching `equitable_shares_paid_cents` (which never counted it).

**Isolation rule honored**: I read only `INSTRUCTION.md`, `SCAFFOLD.yaml`, `PRD.md`, and the skill file. `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, and `test_helpers/` were never opened, and the test suite was never run.

Orchestrator verification: 20 .py modules + start.sh + requirements.txt present; all compile; start.sh is a foreground launcher with guarded pip install.

## Step 7: Run Tests and Iterate — 2026-10-02T18:05:00.000Z

Clean 8-round sweep achieved. All artifacts in place.

**Iterations run:** 3 sweeps (17 deterministic failures → 2 → 0). Final state: **57/57 passing in all 8 parallel rounds**, identical result every round (no flakiness observed at any step).

**Tests deleted:** none. Every failing assertion traced to verbatim PRD prose with unique derivability; all fixes went to the implementation or to test-side literals.

**Fixes applied to `test_helpers/`:**
- `constants.py` — added `CLOCK_EPOCH_SYSTEM_STAMP = "2026-09-01T00:00:00.000Z"` (the §2.4 startup clock instant rendered in the three-fractional-digit format §2.5 pins on `created_at`/`updated_at`), exported via `__all__`.

**Fixes applied to `test_suite/`:**
- `test_01_case_and_asset_intake.py` — `test_case_create_returns_declared_fields_and_zeroed_pool` and `test_asset_system_fields_server_stamped`: the `created_at`/`updated_at` expected literal changed from `"2026-09-01T00:00:00Z"` to `CLOCK_EPOCH_SYSTEM_STAMP` (".000Z"). The tests' *rule* (system stamps read the logical clock, §2.4 "Time inside this API is defined by a server-side logical clock, never by wall-clock time") was correct and stays an exact-equality assertion; only the literal contradicted §2.5's "three fractional digits" pin. Docstrings now cite both §2.4 and §2.5. No assertion was weakened or removed.

**Fixes applied to `implementation/` (all in `workspace/implementation/`):**
- `store.py` `new_entity` — `uuid.uuid4().hex` → `str(uuid.uuid4())`: PRD §2.5 "a server-minted UUID with no type prefix" denotes the canonical hyphenated string form (the form the shared framework's `is_valid_uuid` and `NON_EXISTENT_UUID` use). This one-line fix unblocked 13 tests.
- `util.py` — added `fmt_dt_echo()`: serializes domain datetimes with the zero fractional part elided, so client-supplied timestamps (`seized_on`, windows, slots) round-trip exactly and clock-stamped fields echo the clock's reading (§2.4 states the default as the zero-fraction string "2026-09-01T00:00:00Z", and the §2.5 three-fractional-digit clause is explicitly scoped to `created_at`/`updated_at`/`api_request_timestamp` only).
- `serialize.py` — `forfeited_at`, `seized_on`, `appraised_at`, `returned_at`, `window_start/end`, `incurred_on`, `slot_start/end` now serialize via `fmt_dt_echo`; `created_at`/`updated_at` keep the pinned 3-digit `fmt_dt`.
- `store.py` `new_entity`/`touch` — `created_at`/`updated_at` now stamp from the logical clock (`clock.now()`) instead of wall clock, per §2.4's absolute sentence; all ordering sites (`_latest` valuation pick, pagination, lien waterfall, sweep scan) already tie-break on the monotonic `_seq`, so frozen-clock ties resolve deterministically in insertion order.

**Evidence:** `results.1.json` … `results.8.json` (each 57/57) left in place in `workspace/implementation/` as required output artifacts.

Orchestrator verification: all 8 `results.*.json` files present, each `total: 57, passed: 57, failed: 0`.

## Step 8: Finalize PRD — 2026-10-02T18:20:00.000Z

PRD_FINALIZED.md is written. Final verification confirms exactly five edits, nothing else.

**Line counts / delta:** PRD.md 290 lines → PRD_FINALIZED.md 292 lines (+2 lines, +0.69%). 4 lines revised, 2 lines added (Edit C paragraph).

**Changes (one bullet each):**
- §2.5 — revise — `id` bullet now pins "canonical hyphenated string form (five hex-digit groups of 8-4-4-4-12)" for the server-minted UUID — `implementation/store.py:42` (`str(uuid.uuid4())`, the Step 7 fix from `.hex`)
- §2.5 — revise — `created_at`/`updated_at` bullets now state they are stamped "from the logical clock of §2.4", with the pre-advance created_at literal `2026-09-01T00:00:00.000Z` spelled out — `implementation/store.py:40` and `store.py:55` (`clock.now()` in `new_entity`/`touch`)
- §2.5 — insert — new closing paragraph: the nine domain timestamps (`seized_on`, `forfeited_at`, `appraised_at`, `returned_at`, `window_start`/`window_end`, `slot_start`/`slot_end`, `incurred_on`) echo the exact supplied/stamped instant, fractional second rendered to three digits when nonzero and omitted when zero; the three-fractional-digit pin is scoped to `created_at`, `updated_at`, `api_request_timestamp` only — `implementation/util.py:34-52` (`fmt_dt_echo`) and `implementation/serialize.py:25,47,51,58,73,74,103,148,149`
- §2.3 — revise — list ordering gains a tiebreak clause: `created_at` ties (routine under an unmoved logical clock) order by creation sequence, earliest first — `implementation/util.py:190` (`sort_and_page` on `(created_at, _seq)`)
- §3.3 — revise — the "latest accepted valuation" definition replaces the now-false "which cannot tie because the server stamps it" with ties "possible whenever the logical clock has not advanced between two submissions, broken toward the valuation created later" — `implementation/calc.py:43-47` (`_latest` via `max` on `(created_at, _seq)`)

**Step 7 diff items requiring no edit:** the `test_helpers/constants.py` `CLOCK_EPOCH_SYSTEM_STAMP` addition and the two test-literal fixes were pure test-side literal bugs — the `.000Z` startup `created_at` was already determined by composing §2.4 + §2.5 (Edit B now makes that composition explicit, which is the impl-fix half of that item). The wall-clock→logical-clock move was an impl fix toward PRD §2.4's absolute sentence, pinned in place by Edit B.

**Considered and rejected edits:** §3.6's lien-waterfall "ties broken by `created_at`" left verbatim — the extra `_seq` tiebreak in `routes_sales.py:158` is unreachable because §3.5's position-conflict rule makes `priority_position` unique among VERIFIED liens. The sweep scan order (`routes_ops.py:29`) is unobservable (response carries only counts). `api_request_id` format untouched (§2.2 pins only the `req_` prefix; no Step 7 item).

**Pre-edit search logs:**
- **Edit A** — (a) subject: resource `id` minting format. (b) enumerated: grep `uuid` across `implementation/` → only `store.py:42` (sole minting site for all nine collections via `new_entity`) and `response.py:18` (`api_request_id`, a distinct identifier governed by §2.2's "starts with `req_`" prose, not a UUID); path/body id lookups are format-agnostic dict hits → 404 on any miss. (c) scoped wording to the §2.5 resource-`id` bullet so `api_request_id` stays described by §2.2.
- **Edit B** — (a) subject: which clock stamps `created_at`/`updated_at`. (b) enumerated: `store.py:40` and `store.py:55` are the only two write sites (grep `created_at|updated_at|clock.now|wall_now`); `serialize.py:12-13` formats via 3-digit `fmt_dt` (unchanged); `response.py:19` `api_request_timestamp` uses the *wall* clock; domain stamps (`routes_cases.py:123`, `routes_valuations.py:134`, `routes_assets.py:201`, `routes_expenses.py:50`, `routes_ops.py:52`) already read `clock.now()` and §3 already pins them to "the logical clock time". (c) named the two fields explicitly and cited §2.4 — deliberately avoided any blanket "all server timestamps use the logical clock" claim, which would falsify the wall-clock `api_request_timestamp`.
- **Edit C** — (a) subject: serialization format of non-system datetime fields. (b) enumerated: grep `fmt_dt_echo` → exactly nine callsites (listed above), matching the field list in the edit one-for-one; grep `req_dt|opt_dt` → client-supplied datetime inputs are `seized_on`, `window_start`, `window_end`, `slot_start`, `slot_end`, `incurred_on`, plus `to_iso8601` (clock endpoint returns `{}` — never echoed, correctly absent from the list); `fmt_dt_echo`'s two branches (microsecond==0 → omit; else `microsecond//1000` → 3 digits) match the wording. (c) enumerated exact fields instead of a blanket "domain timestamps" phrase; added the closing scoping sentence for the 3-digit pin; tied the zero-fraction rendering to §2.4's existing literal; left sub-millisecond truncation unpinned (under-determined on purpose).
- **Edit D** — (a) subject: list ordering under `created_at` ties. (b) enumerated: grep `sort_and_page` → all 8 list endpoints route through `util.py:189-192`, the single sort site `(created_at, _seq)` ascending; the sweep scan and lien waterfall sort internally but are not list-endpoint responses. (c) phrased as "creation sequence, earliest-created first", scoped to list endpoints only.
- **Edit E** — (a) subject: "latest valuation" under frozen-clock ties. (b) enumerated: `calc.py:43-47` `_latest` = `max` on `(created_at, _seq)` → tie goes to the later-created valuation; consumed by `calc.py:63` (final variant) and `calc.py:72` (provisional variant), so revising the single definitional sentence covers both; no other code ranks valuations. (c) replaced the false "cannot tie" clause with tie-possibility plus direction (toward later-created), keeping it attached to the same sentence so the provisional variant's un-redefined use of "latest" inherits it.

File: `workspace/PRD_FINALIZED.md`

Orchestrator verification: `diff` confirms exactly the 5 described edits (290 → 292 lines); newest implementation source mtime (store.py 18:06:16) is OLDER than oldest results file (18:09:29) — the clean 8-round sweep postdates all impl edits, no re-sweep needed.

## Step 9: Complete PRD — 2026-10-02T18:37:00.000Z

The task is complete. PRD_COMPLETED.md is written and verified.

**Source vs output**: `PRD_FINALIZED.md` 292 lines / 56,848 chars → `PRD_COMPLETED.md` 292 lines / 60,733 chars (char-delta +3,885, 15 in-paragraph edits, no new sections).

**Counts**: 14 ambiguity-pins, 1 mismatch-revision.

**Changes** (one bullet each; impl refs under `workspace/implementation/`):

- §2.2 — insert — ambiguity — envelope `api_request_timestamp` is stamped from the server's wall clock, not the logical clock — response.py:16-23, util.py:13-21
- §2.3 — insert — ambiguity — malformed/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; path-id existence resolves before pagination parsing on nested lists — util.py:166-185
- §2.4 — insert — ambiguity — clock endpoint accepts any instant, no monotonicity constraint — routes_ops.py:66-75
- §2.5 — insert — ambiguity — offset-less client timestamps interpreted as UTC — util.py:55-73
- §2.7 — insert — ambiguity — OCC is exact version equality; any mismatch → `ERR_STALE_VERSION` — routes_valuations.py:75-79, routes_isr.py:34-38
- §2.10 tier 3 — insert — ambiguity — null-means-absent convention; unused body fields ignored; missing/unparseable body treated as `{}`, non-object body rejected; non-negative pins for `raw_value_cents`/`reserve_price_cents`/`winning_bid_cents`/depreciation inputs; positive lien `amount_cents`/`priority_position`; non-empty `case_number` — util.py:87-161, routes_cases.py:38
- §3.2 — insert — ambiguity — `seized_on` recorded as supplied, never validated against the clock — routes_assets.py:53
- §3.2 — revise — ambiguity — window-chain exemption applies whenever the asset has no non-`CANCELLED` transfer (not just literally-first) — routes_transfers.py:56-70
- §3.3 — revise — ambiguity — provisional retention base falls back to the latest `REJECTED` valuation when no `SUBMITTED`/`ACCEPTED` exists — calc.py:72
- §3.4 — insert — ambiguity — ISR approval landing after the asset left `VALUED`/`DISPOSITION_REVIEW` still marks the request `APPROVED` but fires no cascade — routes_isr.py:99-112
- §3.6 — revise — **mismatch** — sale-event guard order realigned to §2.10 tiers (the old §3.6 list put tier-10 `ERR_SLOT_IN_PAST` before tier-9 `ERR_RESERVE_ABOVE_VALUE` before the tier-8 pair, contradicting §2.10's "earliest tier wins"; impl and live smoke confirm state → `ERR_SALE_ALREADY_ACTIVE` → `ERR_AUCTION_SLOT_CONFLICT` → `ERR_RESERVE_ABOVE_VALUE` → `ERR_SLOT_IN_PAST`) — routes_sales.py:39-81
- §3.6 — insert — ambiguity — zero-amount waterfall buckets create no distribution; a zero-paid verified lien stays `VERIFIED` with null `satisfied_amount_cents`; lien double-ties break by creation sequence — routes_sales.py:150-198
- §3.7 — insert — ambiguity — rescind credit-back applies only to `EQUITABLE_SHARE`; voiding a system-created `LIEN_PAYMENT`/`COST_REIMBURSEMENT` touches no case accumulator and leaves the lien `SATISFIED` (the blanket reading would break §3.7's own pool-conservation claim) — routes_distributions.py:126-138
- §3.8 — revise — ambiguity — `return_condition_grade` is supplied-and-consumed by the depreciation computation, not persisted (the persisted handover record is `current_condition_grade` via the transfer's arrival inspection) — routes_assets.py:184-208
- §4 — insert — ambiguity — unknown paths → 404 `ERR_NOT_FOUND`; unsupported method on a defined path → HTTP 405 with an `ERR_NOT_FOUND` body — app.py:48-60

**IMPL BUG list**: empty. Borderline call disclosed: §2.4's blanket "never by wall-clock time" vs the wall-clock envelope timestamp was judged ambiguity (not a violation) because §2.4's own next sentence scopes the clock to enumerated time-relative *rules* and §2.5 explicitly pins entity timestamps to the logical clock — the pin carves out transport metadata only.

**Dead-code / dead-path audit**:
1. **Catalogue → raise sites**: all 25 PRD §5 error_ids have raise sites (5 raised via `errors.*` helpers — call sites grep-confirmed in routes_valuations/routes_isr/routes_assets/routes_distributions/routes_interests).
2. **Raise → catalogue**: one uncatalogued id, `ERR_INTERNAL` (app.py:64), the 500 catch-all; no business path reaches it (all smokes returned 2xx/4xx). The 405 handler emits catalogued `ERR_NOT_FOUND` at uncatalogued status 405 — now documented by the §4 pin.
3. **Gates invoked on live paths**: three defined-but-unreachable guards, all benign: the dismissal "no `SOLD` asset" check (routes_cases.py:141) is shadowed because `SOLD` requires a `FORFEITED` case, which fails the earlier from-state check — PRD §3.1 pins this check, so it stays; the `appraised is None` guards in calc.py:102 and routes_assets.py:115 are unreachable because `VALUED`/`DISPOSITION_REVIEW` imply an accepted valuation. Every other gate was confirmed firing, incl. each §3.6 sale guard individually via live smoke.
4. **Nullable-field reads**: all guarded (reserve check, depreciation, resolve-dispute limit) or set-before-state (returned_at, gross_proceeds). Live-smoked on a dynamic port: future-`seized_on` → negative computed depreciation `-20000` with 200 (this is exactly what the PRD's own months formula yields; no floor pinned or applied), unappraised return → computed 0, resolve 1 → `ERR_DEPRECIATION_EXCEEDS_VALUE`, resolve 0 → `RESOLVED`; zero-paid lien → stays `VERIFIED`, no zero distributions; ISR approve after `RETAIN` → `APPROVED`, asset untouched. No 500s anywhere.
5. **Recording-vs-carry**: every "records X as `<field>`" clause persists (condition_on_arrival, computed/dispute/final depreciation, all §2.1 audit ids, ISR snapshots, satisfied_amount_cents, winning_bid_cents); the single carry-classified clause ("recording the `return_condition_grade`") is pinned per item 14.

Auxiliary cross-reference: `test_helpers/constants.py` matches impl constants (3300 bps, fee tiers, 800/50/6000 depreciation, carrying rates); sweep artifacts `results.1-8.json` all 57/57 green.

**Orchestrator adjudication of the single mismatch-revision (§3.6 guard order):** EXONERATED. The revision resolved a PRD-internal self-contradiction — §3.6's local guard list contradicted §2.10's globally-pinned ordered validation pipeline ("earliest tier wins") — in favor of the global section, which is what the implementation, the passing test suite, and Contract-2-verified §2.10 prose all agree on. This matches the known adjudication category "scaffold/PRD self-contradiction" rather than lost scaffold intent.

**Orchestrator verification:** PRD_COMPLETED.md exists (292 lines, +3,857 chars by my own measurement vs PRD_FINALIZED.md; diff = 15 in-place line revisions, no whole-line inserts/deletes — matches "15 in-paragraph edits, no new sections"); PRD_FINALIZED.md untouched by Step 9 (mtime 18:17 = Step 8 write); all implementation sources OLDER than the oldest results.*.json (sweep still valid — Step 9 made zero impl edits); 8 results files intact (57/57 each); test_helpers/ and test_suite/ intact.

## Pipeline Complete — 2026-10-02T18:40:00.000Z

All 9 steps done. Final state: 57/57 tests passing in 8/8 parallel stability rounds under per-test-server isolation; PRD_COMPLETED.md is the final contract (PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, minimal diffs at each stage).
