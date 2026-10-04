# Worklog — task_3411_proprietary_variety_licensing_independent_growers_quality_grading

## Step 1: Create Task Directory — 2026-10-01T19:50:00.000Z

Task directory was pre-allocated by the caller at `./tasks/task_3411_proprietary_variety_licensing_independent_growers_quality_grading` with `workspace/` inside; verified it exists and is empty. No new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-01T21:10:00.000Z

All three artifacts are complete, lint-clean, and cross-verified. Summary:

**Files written** (all parse as YAML; lint verdict clean):
- `/home/ubuntu/github/CodingPRD/tasks/task_3411_proprietary_variety_licensing_independent_growers_quality_grading/SCAFFOLD.yaml` — 1282 lines (§1.0–§1.7 only; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3411_proprietary_variety_licensing_independent_growers_quality_grading/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1467 lines (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3411_proprietary_variety_licensing_independent_growers_quality_grading/SCAFFOLD_CORNER_DESIGN.yaml` — 2154 lines (single key `scaffold_corner_design`)

**Scaffold surface**: 10 entities, 41 endpoints, 9 state machines (incl. cyclic grade-regrade loop, cyclic statement dispute-resolve loop, parallel lot_status × grade_status dimensions on HarvestLot, compound PoolPeriod SETTLED→PAID), 7 calculations, 12 ordered validation priorities, 37 error codes, 8 roles (segregation-of-duties model: certifier must differ from both grade submitter and receiving operator), 2 OCC concurrency rules. Archetype: ledger reconciliation (provisional-vs-final pool settlement) + compliance/audit secondary; flat topology; all constants pinned as literals.

**Difficulty design (§1.8)**: 19 instances, 9/9 rules with ≥2 each — dual variants in two domains (pool rate 450.3335 vs 468.3469 on identical lots; royalty 225000 vs 190000 across the 100000-plant tier boundary), combinatorial modes a+b+c separately instanced (shoulder multiplier 413.6000 vs 376.0000; marketing-fee-before-rate evaluation order with 118500-not-111390 / 450.3335-not-479.0782 contrasts; per-lot-round-then-sum with the −1 remainder absorbed by H3), depth-4 recall-enforce and depth-3 grower-exit cascades, {state vs temporal} and {state vs constraint} priority pairs, 11.0-brix and 8h00m boundaries, Grower→Agreement and HarvestLot→PoolPeriod cross-entity gates, half-open (windows) vs closed (agreements) overlap semantics, and plant-inventory + pool-zero-sum conservation invariants. All money literals precomputed by code.

**Corner design (§1.9)**: 68 instances — 53 active + 15 `excluded_because` stubs — across all 9 taxonomy sections. Every error code is exercised, every endpoint is called at least once, instance names are unique across the union (87 names), all `excluded_because` refs resolve to real §1.8 instances, and all `grounds:` refs resolve into §1.1–§1.6.

**Lint verdict (verbatim)**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (41 endpoints, 10 entities, 19 §1.8 + 53 §1.9 instances, 1191 calls scanned.)

One notable endpoint-budget tradeoff: CoolingFacility and Region are scalar fields rather than entities to keep the surface at 41 endpoints (Step-6-safe per past overshoot failures) while preserving the cold-chain and regional-scheduling logic as computations/validations on HarvestLot and HarvestWindow.

Orchestrator verification: all three files exist and parse as YAML with correct top-level keys.

## Step 3: Copy Shared Files — 2026-10-01T21:12:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3411_proprietary_variety_licensing_independent_growers_quality_grading/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T21:40:00.000Z

All checks pass. The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3411_proprietary_variety_licensing_independent_growers_quality_grading/workspace/PRD.md` — 330 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 RBAC (8 roles, per-role identity prose incl. entity-backed `GrowerPrincipal`), 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, verified by string equality), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 The Logical Clock (startup default 2026-09-01T00:00:00Z, `current_utc`), 2.5 Common Resource Properties, 2.6 Money/Rates/Rounding (integer cents, half-up, 4dp rates, 2dp precool, per-lot-then-sum), 2.7 OCC (both rules), 2.8 Validation Order (all 12 priority tiers, first-failure-wins, state-before-deadline ordering note), 2.9 Referential Integrity & Cascading Consistency
- §3 Business Logic (9 subsections): varieties/recall issuance/enforcement; grower onboarding/suspension/exit; agreements; plant lots & tiered royalty; plantings & window booking; harvest delivery & cold chain; grading & four-eyes certification; pool close/settle pipelines; statement dispute/resolve/pay
- §4 Endpoint Definitions — 41 rows (4 columns only), matching all 41 scaffold endpoints
- §5 Error Code Catalogue — 37 rows (2 columns only), matching all 37 scaffold errors

**Coverage attestation (mechanical, via Python diff of SCAFFOLD.yaml vs PRD backticked tokens, with fenced code blocks stripped):**
- Contract 1 (field names): 104/104 entity fields, 41/41 request-body identifiers, 18/18 query params, 11/11 path params present — 0 missing in every set
- Contract 3 (§3 path purity): 559 backticked tokens scanned in §3; 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos
- All 37 error IDs appear in §2/§3 prose (not just §5); all 8 role names, all 31 state names, all 42 enum values present verbatim
- All 40 state-machine transitions have both from/to states expressed; all 40 scaffold transitions covered
- Contract 2 rules verified per category: 12-tier validation priority stated as ordered narrative; both OCC rules express write operation + `expected_agreement_version`/`expected_planting_version` + `ERR_STALE_VERSION`/412 in stale-read framing (no simultaneity language); all cascades expressed (recall enforce's pinned plantings→lots→windows order, grower exit's 3 links, suspend's 1 link, confirm's lot/agreement/window effects, settle's lot+statement effects, pay→pool derivation); all 6 calculations rendered as precise prose with every constant (45/38/30 cents, 100,000/500,000 tiers, 1.15/1.00/0.55/0.25 weights, 6% fee, 1.10 shoulder multiplier, 8% breach deduction, 8.0h/4.0°C/10.0°C cold-chain bounds, 60/75/90/120 days, 2.5/1.8/2.0/3.0 kg yields, 120% window cap, 22-cent default compensation, fourteen-day dispute window, remainder allocation with received_at/created_at tie-breaks); sibling branches given equal density (UPHOLD vs ADJUST, `SHIPPED → DEPLETED` direct vs via `PLANTED`, PLANNED vs PLANTED/HARVESTING recall arms, `ISSUED → PAID` vs `FINAL → PAID`)
- Constants spot-check list: 0 missing; PRD ends at §5 with no audit footer

One process note: my first verification script reported false mass-missing results because the naive backtick-token regex misaligned on §2.2's ` ```json ` fences; after stripping fenced blocks before extraction (the correct procedure), every contract reports PASS.

Orchestrator verification: PRD.md exists (330 lines), starts with the expected title.

## Step 5a: Generate test_helpers/ (Stage 1) — 2026-10-01T22:05:00.000Z

Stage 1 is complete. Summary:

**Files generated** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3411_proprietary_variety_licensing_independent_growers_quality_grading/test_helpers/`):

| File | Lines | Contents |
|---|---|---|
| `__init__.py` | 28 | Barrel export: framework generics + all PRD-specific modules |
| `types.py` | 312 | 10 entity TypedDicts (all `common_fields: true`, so all carry `id`/`created_at`/`updated_at`/`version`), 12 status enums, 13 domain enums (BerryType, CulturalPractice, Decision, Resolution, …), `UserRole` with all 8 roles |
| `api_client.py` | 172 | `ApiClient(GenericApiClient)` + module-level `api_client` |
| `api_errors.py` | 87 | `ApiErrorId` enum + `HTTP_STATUS_CODES` map, registered via `set_error_http_status_map()` at import |
| `assertions.py` | 218 | `assert_*()` per entity (all 10) using framework UUID/ISO-8601 validators, plus `assert_plant_lot_conservation` (reserved+planted+destroyed+available == quantity) and `assert_pool_zero_sum` invariants |
| `factories.py` | 173 | 20 payload factories, input fields only, PRD-canonical defaults |
| `constants.py` | 80 | All pinned constants: royalty tiers 45/38/30c at 100,000/500,000, cold-chain 8.0h/4.0°C/10.0°C/8%, grade band bounds, yields (2.5/1.8/2.0/3.0), maturation days (60/75/90/120), 1.20 oversubscribe, grade weights 1.15/1.00/0.55/0.25, 6% fee, 1.10 shoulder multiplier, 14-day dispute window, 22c default recall compensation, canonical clock/window/pool dates |
| `test_users.py` | 73 | 8 roles |
| `fixtures.py` | 403 | Composite setup helpers (see tiers below) |

**Endpoint methods in `api_client.py`: 41** (1 clock + 5 variety + 3 grower + 4 agreement + 3 plant-lot + 5 planting + 3 harvest-window + 7 harvest-lot + 4 pool-period + 5 settlement-statement + 1 recall-order).

**Error codes in `api_errors.py`: 37**, each mapped to its PRD §5 HTTP status.

**Roles in `test_users.py`: all 8** — PlatformAdmin, BreedingManager, ComplianceOfficer, NurseryManager, GrowerPrincipal, CoolingOperator, QualityGrader, SettlementOfficer. `make_grower_principal_headers(user_id)` is the mandatory per-instance builder for the entity-backed role; segregation of duties is supported via distinct canonical ids (`COOLING_OP_1="co-1"`, `GRADER_SUBMITTER="qg-1"`, `GRADER_CERTIFIER="qg-2"`, `GRADER_THIRD="qg-3"`) plus `make_quality_grader_headers` / `make_cooling_operator_headers` builders.

**Fixture tiers provided:**
- **Tier 0 primitives**: `set_clock`, create/release/recall variety, create/suspend/exit grower, apply/decide agreement, plant-lot, harvest-window, `plan_planting`/`create_lot_in_transit` (both re-read the parent's current version to satisfy OCC), confirm/complete planting, receive/submit/certify/dispute grade, pool create/close/settle, `find_statement`, dispute/resolve/pay statement, `enforce_recall`.
- **Tier 1–2**: `setup_active_agreement`, `setup_planting_planned`, `setup_planting_confirmed` (creates covering window, advances clock to confirm day).
- **Tier 3 full-lifecycle**: `setup_lot_in_transit` / `setup_lot_received` / `setup_lot_submitted` / `setup_lot_certified` (delivery→grading→certification with SoD-distinct actors); `setup_pool_closed` / `setup_pool_settled` / `setup_statement_disputed` (pool close→settle→statement chain).
- **Tier 5 terminal/cascade**: `setup_recalled_variety_order`, `setup_exit_ready_grower`, `setup_exited_grower_with_cancelled_planting` (grower-exit cascade through CANCELLED planting and released lot reservation).

All fixtures thread `make_grower_principal_headers(grower["id"])` on ownership-gated calls, use `get_success_data`, and encode the canonical design timeline (clock pin 2026-06-01, planted 2026-08-01, strawberry first harvest 2026-09-30 inside window [09-28, 10-05), pool week [10-05, 10-12)).

**Verification**: all 9 files pass `ast.parse`; `python3 -c "import test_helpers"` succeeds (framework is pip-installed, no sys.path hack needed); endpoint/error/role counts and the fixture surface were asserted programmatically; no `test_suite/` directory was created — Stage 2 is left for the follow-up subagent.

Orchestrator verification: `wc -l test_helpers/*.py` = 1546 total lines; `python3 -c "import test_helpers"` succeeds from the task dir.

## Step 5b: Generate test_suite/ (Stage 2) — 2026-10-01T23:00:00.000Z

Step 5b is complete. Summary:

## Test files (all under `/home/ubuntu/github/CodingPRD/tasks/task_3411_proprietary_variety_licensing_independent_growers_quality_grading/test_suite/`)

| File | Lines | Content |
|---|---|---|
| `conftest.py` | 49 | §2.0 fixture bridge (`api` session fixture + 8 role-header fixtures) |
| `test_01_varieties.py` | 118 | variety create/release/recall, recall-order listing |
| `test_02_growers.py` | 145 | exit lockdown, suspend cascade selectivity, live-plantings exit gate, exit depth cascade ×2 |
| `test_03_agreements.py` | 234 | enum/exclusive-marketing 400s+409, decide branches, pagination, closed-window overlap ×2, active-grower decide gate ×2 |
| `test_04_plant_lots_royalty.py` | 168 | lot creation accounting, variety mismatch, availability gate, tiered royalty difficulty ×2 |
| `test_05_plantings_confirm.py` | 216 | confirm computed fields, quota/capacity/window/temporal gates, state-beats-quota ×2, ownership |
| `test_06_harvest_windows.py` | 83 | half-open overlap difficulty ×2, listing filters |
| `test_07_harvest_lots.py` | 228 | tare default, harvest-before-planting, 10.0 °C hard-reject, precool 8h boundary ×2, receive immediacy, list filters, auto-HARVESTING + complete gate |
| `test_08_grading.py` | 211 | brix 11.0 boundary ×2, STANDARD/PROCESS defect boundary, JUICE/REJECT, receive gate, double-certify, segregation ×2, regrade cycle ×2 |
| `test_09_pool_pipeline.py` | 227 | canonical 3-lot pool: provisional-vs-final ×2, evaluation order ×2, per-lot rounding/remainder ×2, zero-sum ×2 |
| `test_10_pool_close_membership.py` | 240 | close gate ×2, half-open membership, provisional statements, pool overlap, shoulder mode ×2 |
| `test_11_statement_cycle.py` | 109 | dispute/resolve cycle ×2, state-beats-deadline ×2 (reuses `_canonical_pool` from test_09) |
| `test_12_statement_payment.py` | 127 | expired dispute window, negative settlement, pay gating, pool-paid derivation, grower-pay RBAC, unsettled-statements exit (reuses `_corner_pool` from test_10) |
| `test_13_recall_enforce.py` | 107 | recall-enforce depth-4 cascade ×2 |
| `test_14_conservation.py` | 62 | plant-lot conservation invariant ×2 |
| `test_15_auth_rbac_notfound.py` | 151 | 401, role-beats-existence, 3 RBAC denials, 9-endpoint 404 sweep |
| `test_16_occ.py` | 92 | both OCC guards (agreement/planting stale version) |

## Audit results
- **Collection**: `python3 -m pytest test_suite/ --collect-only -q` from the task dir exits **0** with **91 tests collected**.
- **Tag audit (AST + yaml.safe_load)**: 91 emitted = 19 difficulty × 2 + 53 corner × 1 exactly; untagged/dual-tagged **0**; tags not resolving to a real instance **0**; tags pointing at `excluded_because:` stubs **0**; uncovered active instances **none**.
- **Skipped instances: none.** All 72 non-stub instances passed the PRD-first two-condition filter; all 15 corner stubs cross-resolve to real difficulty instances (verified programmatically — refs carry spaces around `/`, e.g. `"dual_variant_calc / royalty_provisional_vs_tiered_final"`).
- **PRD-citation pass**: strict multi-window verbatim grep of every docstring quote against PRD.md passes with 0 failures (required normalizing `->`→`→`, `--`→`—`, `C`→`°C` and expanding all `...` elisions to full sentences).
- **No `skip`/`skipif`/`xfail`** markers anywhere.

## Notes for downstream steps
- Tests assume per-test server restart; every test rebuilds state via `test_helpers` fixtures. The canonical 3-lot pool (H1/H2/H3, close@500/settle@520) and corner pool (H1 + HY at week_end) are private builders in test_09/test_10, imported by test_11/test_12.
- One PRD observation: growers have no GET endpoint in the §4 table, so `grower_exited_terminal_lockdown` asserts lockdown via the exit response plus both rejected transitions rather than a re-read.
- All create calls use `validate_success(resp, 201)` explicitly; mutations use 200. Monetary/literal assertions copy the design-index precomputed values verbatim (e.g. royalty 190000/-35000, pool rates 450.3335/468.3469, remainder-adjusted H3 936693).

Orchestrator verification: `pytest --collect-only -q` exits 0 with 91 tests; `grep -rhoE "Design: (Difficulty|Corner)/..." | sort -u | wc -l` = 72 (matches 19 difficulty + 53 corner active instances); no skip/xfail markers found.

## Step 6: Generate Implementation — 2026-10-01T23:30:00.000Z

Implementation complete and verified. Summary:

## Files delivered (19 files, 2210 lines) in `workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 9 | Foreground launcher; guarded `pip install` (no-op when flask present); `exec python3 app.py`; `$PORT` (default 10000), binds `0.0.0.0` |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 52 | Flask bootstrap, blueprint registration, ApiError/HTTPException handlers |
| `store.py` | 65 | In-memory dicts (10 entity tables), logical clock (starts exactly `2026-09-01T00:00:00Z`), UUID ids, ISO-8601 3-fractional-digit timestamps, `version` starting at 1 with `touch()` on every mutation including cascades |
| `constants.py` | 76 | Every scaffold constant defined once (grade bands, cold-chain 8.0h/4.0C/10.0C/8%, yields 2.5/1.8/2.0/3.0, maturation 60/75/90/120, oversubscribe 1.20, royalty 45/tiers 100k@45/500k@38/30, weights 1.15/1.00/0.55/0.25, fee 6%, shoulder 1.10, dispute 14d, default comp 22) |
| `errors.py` | 98 | All 37 catalog error ids with exact HTTP statuses |
| `helpers.py` | 228 | Envelope (`meta.api_request_id/api_request_timestamp` + `response_type` + `data`; pagination `limit/offset/total_count/has_more` in meta), auth tiers 1–3, typed body validators, Decimal-safe parsing |
| `calc.py` | 173 | Grade bands (top-down, inclusive), cold chain (2dp round-half-up precool), yield/window selection (half-open coverage), tiered marginal royalty by (variety, season_year) counter ordered (shipped_at, created_at), pinned 8-step pool pipeline |
| 11 route modules | ~1200 | One per domain: clock, varieties, growers, agreements, plant_lots, plantings, harvest_windows, harvest_lots, pools, statements, recall |

## Endpoint count: 41/41 (verified via `url_map` enumeration, including `POST /_clock/set_current_utc`)

Key behaviors implemented per PRD-over-scaffold precedence: validation tiers 1–12 in exact order (ownership before existence; state-gate before deadline on dispute; RECALLED→`ERR_VARIETY_RECALLED` vs DEVELOPMENT→`ERR_VARIETY_NOT_RELEASED` on decide); OCC `expected_agreement_version`/`expected_planting_version`→412; closed-interval agreement overlap (boundary day counts), half-open window/pool overlap (adjacency allowed); two-stage pool pipeline with per-lot round-then-sum and remainder to largest-weighted lot (ties: earliest received_at, created_at); statements PROVISIONAL→ISSUED at settle with royalty offset (depleted_at in window) and recall credit (recalled_at in window); pool SETTLED→PAID derived from last paid statement; recall enforce cascade plantings→lots→windows with compensation 22c default; grower exit 3-link cascade with live-planting/unsettled-statement blockers; four-eyes segregation on certify.

## Smoke test (dynamic port 54327, full happy path, all observed statuses)
Clock set 200 → variety create **201** → release **200** → grower **201** → agreement **201** → decide APPROVE **200** (ACTIVE) → plant-lot **201** → harvest-window **201** → planting **201** → confirm **200** (efh 2026-10-31, yield 1000) → harvest-lot **201** → receive **200** (RECEIVED, precool 4.5h, compliant) → grade **200** (PREMIUM, v1) → certify **200** (CERTIFIED/GRADED) → pool **201** → close **200** (rate 408.6957, gross 59000, fee 3540 — hand-verified) → settle **200** (final rate 490.4348, gross 70800) → statement ISSUED net 66552 → dispute **200** → resolve ADJUST **200** (net 67052) → early pay **409 ERR_STATEMENT_NOT_PAYABLE** → pay **200** (PAID) → pool derived **PAID** → complete **200** (COMPLETED).

Negative spot-checks on second boot all returned exact catalog ids: ERR_UNAUTHENTICATED (missing + bad role), ERR_FORBIDDEN_ROLE (incl. GrowerPrincipal→plant-lot propagation prohibition), ERR_VARIETY_NOT_RELEASED, ERR_NOT_OWN_RESOURCE, ERR_EXCLUSIVE_MARKETING_REQUIRED, ERR_AGREEMENT_WINDOW_OVERLAP (boundary-day case), ERR_STALE_VERSION.

## Statelessness check: PASS
Boot 1 created the full entity chain; killed exact saved PID; boot 2 on a fresh port returned `total_count: 0, data: []` for `/licensing/agreements` and `/licensing/plant-lots`. No seeding anywhere — `store.py` tables start empty and are only mutated via endpoints.

Isolation rule honored: only INSTRUCTION.md, SCAFFOLD.yaml, and PRD.md were read; no test_suite/test_helpers/design files or sibling tasks were inspected.

Orchestrator verification: `python3 -m compileall -q .` passes in workspace/implementation; `url_map` enumeration = 41 routes; 2210 total lines.

## Step 7: Run Tests and Iterate — 2026-10-01T23:50:00.000Z

All 8 rounds clean: 91/91 passed, 0 failed.

## Summary

**Iterations run:** 2 (initial sweep → fix → verification sweep, 8/8 clean rounds each time).

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3411_proprietary_variety_licensing_independent_growers_quality_grading/test_suite/test_07_harvest_lots.py` (`test_harvest_lot_tare_defaults_to_zero_and_net_computed`): changed `del payload["tare_weight_kg"]` to `payload.pop("tare_weight_kg", None)`. The `create_harvest_lot_payload` factory omits `tare_weight_kg` by default (it's an optional PRD field sent only via override), so the `del` raised `KeyError` before any request was issued. The test's intent — field omitted entirely so the server default 0 applies — is preserved. The PRD rule itself (§3.6: tare "defaults to 0", `net_kg = gross_weight_kg − tare_weight_kg`) is verbatim-covered and the assertion was correct.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_3411_proprietary_variety_licensing_independent_growers_quality_grading/workspace/implementation/routes_harvest_lots.py` (`grade_harvest_lot`): reworked the receipt gate from strict `lot_status != "RECEIVED"` to rejecting only lots never received — `IN_TRANSIT`, or `REJECTED` while still `UNGRADED` (hard reject). Root cause of both regrade failures (`test_regrade_cycle_dispute_then_fresh_submission`, `test_regrade_cycle_closes_with_fresh_certification`): certification moves a non-REJECT lot `RECEIVED → GRADED` (PRD §3.7 verbatim) and dispute leaves `lot_status` untouched, so the strict gate made the PRD-mandated cycle "SUBMITTED → CERTIFIED → DISPUTED → SUBMITTED may repeat without limit" unreachable — every regrade died with 409 `ERR_LOT_NOT_RECEIVED`. The PRD-consistent reading of "the same lot_status requirement as any submission" is "the lot must have been received," which the new gate encodes; the two existing `ERR_LOT_NOT_RECEIVED` tests (IN_TRANSIT submission, hard-rejected lot grading) still pass because both states remain rejected.

Orchestrator verification: all 8 `results.{1..8}.json` present, each `passed: 91, total: 91, failed: 0`; no `.py` file in implementation/, test_suite/, or test_helpers/ is newer than the sweep results (no post-sweep writes); spot-checked `grade_harvest_lot` gate matches the reported fix.

## Step 8: Finalize PRD — 2026-10-02T00:05:00.000Z

Done. PRD_FINALIZED.md is written with exactly one targeted revision.

## Summary

**Line counts / delta:** PRD.md 330 lines, PRD_FINALIZED.md 330 lines — 0% line-count delta; exactly 1 line's content revised (~0.3% of lines), rest byte-identical (verified with `diff`).

**Changes (one edit):**
- §3.7 (Quality Grading and Four-Eyes Certification, line 204) — revise — replaced "Submission requires the lot's `lot_status` to be `RECEIVED` — otherwise `ERR_LOT_NOT_RECEIVED`…" with the receipt gate as implemented: rejects exactly a lot still `IN_TRANSIT` or hard-rejected at receipt (`lot_status` `REJECTED` with `grade_status` locked at `UNGRADED`); every other `lot_status` satisfies the requirement, so a certified-then-disputed lot (sitting at `GRADED`, or `REJECTED` via a certified `REJECT` grade) remains regradeable — `implementation/routes_harvest_lots.py:196-199`. This was a genuine PRD-internal contradiction (the strict `RECEIVED` reading made §3.7's own "cycle may repeat without limit" unreachable, since certification always moves `lot_status` off `RECEIVED`), which Step 7 resolved as "the lot must have been received."

**Step-7 diff item needing no edit:**
- `tare_weight_kg` default (test fixture fix `del` → `pop`) — pure fixture bug; PRD §3.6 (line 196) already pins it verbatim: "optionally the packaging `tare_weight_kg` — which defaults to 0, may never be negative, and must always be strictly less than `gross_weight_kg`" and "its `net_kg` is computed as `gross_weight_kg` minus `tare_weight_kg`", matching `routes_harvest_lots.py:75` (`b.get("tare_weight_kg", 0)`) and `:97` (`"net_kg": gross - tare`).

**Pre-edit search log (for the single edit):**
- (a) Subject: the grade-submission receipt gate — which `lot_status`/`grade_status` combinations trigger `ERR_LOT_NOT_RECEIVED`.
- (b) Paths enumerated and read: `routes_harvest_lots.py:196-201` (receipt gate + the separate grade-dimension gate rejecting `grade_status ∉ {UNGRADED, DISPUTED}` with `ERR_INVALID_STATE`), `:145-171` (`receive_harvest_lot`, sole producer of `RECEIVED` and of hard-reject), `:219-235` (`certify_grade`: `RECEIVED → GRADED`/`REJECTED`), `:238-251` (`dispute_grade`: leaves `lot_status` untouched, blocks `SETTLED`), `routes_pools.py:60,195` (close gate reads; settlement moves only CERTIFIED lots `GRADED → SETTLED`), `routes_plantings.py:203` (completion reads resolved statuses), `errors.py:34,76` (409 mapping, matches PRD catalog line 310). Grep confirmed `:199` is the only `ERR_LOT_NOT_RECEIVED` raise site. PRD cross-refs checked: line 123 (tier-7 gate list, generic), line 216 ("same `lot_status` requirement as any submission" — now consistent under the redefined gate, kept verbatim), line 274 (endpoint table).
- (c) Wording adjustment: rejected the false-universal "requires `RECEIVED`" phrasing and rejected enumerating passing states exhaustively (which would misdescribe `SETTLED` — it passes this gate, then fails the dimension gate with `ERR_INVALID_STATE`). Final wording pins exactly the two rejected states, says "every other `lot_status` satisfies this receipt requirement," and scopes regrade reachability with "once its grade is disputed" so the `UNGRADED`/`DISPUTED` dimension gate is not contradicted.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one revised line (line 204, §3.7 receipt gate) — matches the claim.

## Step 9: Complete PRD — 2026-10-02T00:40:00.000Z

Done. The diff is 14 in-place paragraph edits, no new sections, line count unchanged.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3411_proprietary_variety_licensing_independent_growers_quality_grading/workspace/PRD_COMPLETED.md`
**Source vs output:** PRD_FINALIZED.md 330 lines / 55,893 chars → PRD_COMPLETED.md 330 lines / 58,250 chars (Δ +2,357 chars, 14 paragraphs touched, 0 lines added/removed — all inline inserts/revisions).

**Counts:** 10 ambiguity-pins, 3 mismatch-revisions.

**Changes (one per bullet):**
- §2.3 — insert — ambiguity — pins invalid `limit`/`offset` (non-integer, limit outside 1–100, negative offset) → `ERR_INVALID_REQUEST`, and sort tie-break `created_at` then `id` ascending (ties are the norm under the logical clock) — implementation/helpers.py:197-228
- §2.8 tier 3 — revise — mismatch — pins that ownership is evaluated only after the target chain resolves: path identifiers (and the body-carried `agreement_id`/`planting_id` of new plantings/harvest-lots) yield their 404 ahead of `ERR_NOT_OWN_RESOURCE`; agreement application is the exception, checking the claimed `grower_id` before grower existence — implementation/routes_plantings.py:57-62, implementation/routes_harvest_lots.py:62-68, implementation/routes_statements.py:64-65, implementation/routes_agreements.py:52-55
- §2.8 tier 4 — revise — mismatch — scopes tier-4 existence to path identifiers plus the ownership-chain head; all other body-carried identifiers (grower/variety on agreements, agreement/variety on plant lots, variety on harvest windows, plant lot on plantings) resolve only after tier-5 shape checks pass — implementation/routes_agreements.py:55-76, implementation/routes_plant_lots.py:63-73, implementation/routes_harvest_windows.py:43-52, implementation/routes_plantings.py:65-73
- §2.8 tier 5 — insert — ambiguity — required string fields must be non-empty; offset-less ISO 8601 inputs are read as UTC — implementation/helpers.py:124-127, 172-185
- §3.1 — insert — ambiguity — duplicate `variety_code` → `ERR_INVALID_REQUEST` (PRD named no error) — implementation/routes_varieties.py:45-47
- §3.1 — insert — ambiguity — recall response is `201 Created` carrying the created recall order (not the modified variety) — implementation/routes_varieties.py:103
- §3.2 — revise — ambiguity — `region_code` is uppercase by convention only, stored as supplied with no case validation — implementation/routes_growers.py:34
- §3.2 — revise — mismatch — suspend's optional `reason` is accepted but **not persisted** (impl has no grower reason field; deliberate per code comment) — implementation/routes_growers.py:47
- §3.6 — insert — ambiguity — a hard-rejected lot records `cold_chain_compliant` false — implementation/routes_harvest_lots.py:163-166
- §3.7 — insert — ambiguity — scores outside their scales rejected with `ERR_INVALID_REQUEST`, bounds inclusive — implementation/routes_harvest_lots.py:183-190
- §3.7 — insert — ambiguity — `grade_version` starts at 0 on lot creation — implementation/routes_harvest_lots.py:115
- §3.7 — revise — ambiguity — certification sets `lot_status` to `GRADED`/`REJECTED` unconditionally, covering regrade certifications arriving from `GRADED`/`REJECTED`, not only `RECEIVED` — implementation/routes_harvest_lots.py:230-233
- §3.8 — insert — ambiguity — empty inclusion set: all pipeline totals zero, pool rate 0.0000 (division guard), no statements at close, no remainder allocation at settle — implementation/calc.py:152-155, implementation/routes_pools.py:182
- §3.9 — insert — ambiguity — `adjustment_cents` is required on `ADJUST` (absence → `ERR_INVALID_REQUEST`) and ignored on `UPHOLD` — implementation/routes_statements.py:87-93

**Suspected implementation bugs NOT papered over:** none meeting the flag bar (PRD-verbatim + test-exercised). The closest call is the suspend-`reason` persistence: PRD_FINALIZED said "optionally recording a `reason`", the impl accepts-and-discards it, and no test exercises persistence. I revised the PRD to match impl because the PRD never names a grower reason field — unlike `reject_reason`, `grade_dispute_reason`, and `dispute_reason`, which are all named and persisted — so "no persistence" is the PRD-derivable reading; flagged here in case the pipeline wants Step 7 to re-adjudicate.

Everything else in the impl — the full endpoint/role matrix, all 37 error codes and statuses, the tiered royalty math, the 8-step pool pipeline with shoulder multiplier, remainder allocation, the recall 3-link cascade, OCC guards, cold-chain bounds, grade bands, statement dispute/resolve/pay gates, and all version/`updated_at` stamping — was verified to match PRD prose already and required no change.

Orchestrator verification: PRD_COMPLETED.md exists at 330 lines; `diff PRD_FINALIZED.md PRD_COMPLETED.md` = 28 changed lines (14 in-place paragraph edits, matches claim); all 8 `results.{1..8}.json` still present (91/91 each); no `.py` file in implementation/, test_suite/, or test_helpers/ is newer than the sweep results.

Orchestrator adjudication of the flagged suspend-`reason` item: the PRD never names a grower `reason` field (contrast `reject_reason`, `grade_dispute_reason`, `dispute_reason`, which are all named), so persisting it would have added a response-visible field with no PRD trace — pinning "accepted but not persisted" in PRD_COMPLETED.md is the correct resolution, and no Step 7 re-adjudication is warranted. The two §2.8 tier-3/4 mismatch-revisions pin precedence-order details (404 vs ownership, body-id resolution timing) that the green 8-round sweep confirms are test-consistent.
