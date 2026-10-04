# Worklog — task_3446_multi_brand_portfolio_rationalization_assortment_reduction

## Step 1: Create task directory — 2026-10-02T04:32:00.000Z

Task directory pre-allocated by caller at ./tasks/task_3446_multi_brand_portfolio_rationalization_assortment_reduction with workspace/ inside (verified present and empty). No new index computed; no other task_* directory created.

## Step 2: Generate scaffold — 2026-10-02T05:35:00.000Z

All checks pass. The scaffold generation is complete.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3446_multi_brand_portfolio_rationalization_assortment_reduction/`):
- `SCAFFOLD.yaml` — 1119 lines (§1.0–§1.7 + invariants; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 529 lines (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1104 lines (single key `scaffold_corner_design`)

**Domain design** (Newell-style portfolio rationalization, `api_prefix: /portfolio`):
- **12 entities**: Brand, Item, Plant, Retailer, RationalizationCase, Divestiture, TransitionServiceAgreement, ProductTransfer, QualificationRun (common_fields: false, immutable), CombinedNegotiation, CapitalCycle, InnovationProject — flat topology, FK-joined
- **10 state machines**: branching+revert on Item (LISTED↔CUT_PROPOSED→SELL_THROUGH→DISCONTINUED), self-loop cyclic ProductTransfer (FAIL resets consecutive-pass counter; 2 consecutive PASSes auto-execute), 5-state RationalizationCase with VOIDED cascade terminal, 4-stage Divestiture, 3-state TSA, diamond CombinedNegotiation (incl. TTL auto-EXPIRED), plus Plant/CapitalCycle/InnovationProject
- **10 calculations**, all constants pinned as literals (composite cut-score with 4 clamped sub-scores and ≥65 threshold; TSA early-termination penalty with pinned ceil→multiply→round order; STANDARD/SALVAGE obsolescence and STANDARD/CORE_BRAND priority dual variants; integer cross-multiplication 110% capacity gate; 250bp reject-rate gate; 90-day sell-through window; 30-day negotiation TTL; skip-and-continue capital waterfall)
- **23 ordered validations**, **40 endpoints** (at the cap; 39 prefixed + unprefixed `POST /_clock/set_current_utc` with fixed default 2026-09-01T00:00:00Z), **32 errors**, **6 roles** (3 entity-backed: BrandManager→Brand, PlantDirector→Plant, RetailerBuyer→Retailer; segregation-of-duties on propose/decide and plan/certify), **1 OCC rule** (sell-down on Item.version), **2 named invariants**

**§1.8**: 18 instances (2 per rule × 9 rules), all numeric asserts pre-computed in Python (composite 72.04/CUT, penalty 90008 vs forbidden-order 90009, 250bp and 110.00% boundaries, waterfall 900M/100M conservation, unit balance 400+600=1000).
**§1.9**: 67 instances — 62 active (entities 7, state_machines 11, calculations 5, validations 19, endpoints 5, errors 3, rbac 8, complexity_layers 3, consistency_model 1) + 5 `excluded_because` stubs.

**Self-checks**: (a) all three parse; (b) all 23 CONST symbols have literal definitions; (c) all states used in transitions exist in entity enums; (d) all referenced error_ids are catalogued and every catalogued error is referenced; (e) endpoint count 40 ≤ 40. Additionally: `scaffold_lint.py` verdict — **clean lint** (430 calls scanned, 0 violations, all FKs reverse-reachable); placeholder closure, grounds resolvability, stub references, and 85-instance name uniqueness all verified programmatically; forbidden concurrency vocabulary absent.

Two authoring hazards were caught and fixed en route: YAML flow-syntax breaks (unquoted `field?` optional markers and bracketed `errors[...]` grounds) and two validation-deadlock traps (open-case/open-divestiture uniqueness shadowed by earlier state guards — restructured so both errors are reachable: DISCONTINUED/EXITED → state error, CUT_PROPOSED/SELL_THROUGH/open-divestiture → ALREADY_OPEN).

Orchestrator verification (independent): all three YAMLs parse; api_prefix=/portfolio; 12 in-domain entities; 40 endpoints; 32 errors; 6 in-domain roles; no foreign-domain tokens found.

## Step 3: Copy shared files — 2026-10-02T05:36:30.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T05:45:00.000Z

The PRD is complete and all hard contracts pass. Final report:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3446_multi_brand_portfolio_rationalization_assortment_reduction/workspace/PRD.md` — 297 lines, written in 11 sequential quoted-heredoc append chunks (each ≤60 lines), then two targeted patches.

**Section list:** §1 Introduction (3 paragraphs); §2 Global Specifications with 9 subsections (2.1 RBAC + role-identity prose, 2.2 Response Structure — byte-identical to the canonical block, verified programmatically, 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Resource Properties, 2.6 Precision/Rounding/Integer Arithmetic, 2.7 OCC, 2.8 Validation Precedence, 2.9 Uniqueness & Open-Work Singletons); §3 Business Logic with 7 subsections (foundation entities, rationalization case pipeline, sell-down, footprint consolidation, divestiture/TSA, combined negotiations, capital waterfall); §4 Endpoint table (4 columns, 40 endpoints); §5 Error catalogue (2 columns, 32 errors). No audit footer; file ends at §5.

**Coverage counts:** 12/12 entities, 10/10 state machines (all transitions, guards, and side effects, including the 3-hop TSA cascade and both VOIDED branches), 10/10 calculations with literal constants and rounding/order rules, 23/23 validations in stated priority order (with the priority-7-vs-11 DISCONTINUED/open-case disambiguation called out), 40/40 endpoints, 32/32 errors, 6/6 roles with identity semantics, all ~23 pinned constants verbatim as full sentences (65 cut threshold, 250bp integer gate with exact-boundary-passes, 110% capacity gate with 110.00-allowed/110.01-rejected, 90-day sell-through with inclusive boundary, 30-day negotiation TTL with strictly-later expiry, TSA penalty ceil-months→multiply→round-product order with the forbidden 90,008-vs-90,009 counterexample, SALVAGE 20% recovery, 0.30/0.25/0.20/0.25 weights, 0.5+0.005 damping, 0.60/0.40 capital weights, +10 core bonus post-rounding capped at 100, 2..5 brand_terms, all four worked fixtures).

**Self-check results:**
- (a) Scaffold-parsed diff: 83/83 entity fields, 46/46 request-body ids, 20/20 query params, 1/1 path params, all states/enums/errors/roles/paths present verbatim — 0 missing. (`ProductTransfer`, `CombinedNegotiation`, `CapitalCycle`, `InnovationProject`, `transfer_id`, `cycle_status`, and plain-literal constant forms were caught missing in pass 1 and patched in pass 2.)
- (b) Every transition's preconditions and side effects narrated, including version increments per hop and `decider_user_id` := `system` on cascade-voided cases.
- (c) Every formula stated with evaluation order, clamps, zero-divisor branches, and rounding discipline; per-item-then-sum rounding and integer-cross-multiplication gates explicitly distinguished.
- (d) Response envelope emitted verbatim (byte-identity check: True); pagination defaults/min/max and `created_at`-ascending sort stated.
- Contract 3 (§3 path purity): 472 backtick tokens scanned in §3, 0 violations.
- Clock endpoint: stated as unprefixed `POST /_clock/set_current_utc` with fixed default 2026-09-01T00:00:00Z, in both §1 and §2.4.

Orchestrator verification (independent): all 32 error ids, 40 endpoint paths, 6 role names, 12 entity names, and key constant tokens (_clock path, 2026-09-01T00:00:00Z, 250, 110.00, 90,008, 0.30, SALVAGE) appear verbatim in PRD.md — 0 missing.

## Step 5a: Generate test helpers (Stage 1 of Step 5, split for size) — 2026-10-02T06:02:00.000Z

Stage 1 is complete and verified. All nine helper files are written, import-clean, AST-parseable, and cross-checked against PRD.md.

**Files written (all under test_helpers/):** `__init__.py` 155 lines (barrel export); `types.py` 292 (16 enums + 14 TypedDicts; QualificationRun correctly omits updated_at/version — common_fields false); `api_client.py` 201 (ApiClient with exactly 40 typed methods, 23 POST + 17 GET, + api_client singleton); `api_errors.py` 89 (32 ids + status map); `assertions.py` 283 (validate_created/validate_ok status-explicit, 12 per-entity assertions, 2 invariant checkers); `factories.py` 223 (18 payload factories; salvageable omitted by default to exercise PRD server-side default-false; auto-unique names/SKUs/period codes); `constants.py` 142 (PRD-verbatim only, no dead scaffold variants); `test_users.py` 103 (role header matrix + per-instance entity-backed builders + negative-auth shapes); `fixtures.py` 489 (5 tiers of composite fixtures).

**Constant table frozen (grep-verified against PRD.md):** CLOCK_START_ISO 2026-09-01T00:00:00Z; DEFAULT_APPROVAL_DEADLINE_ISO 2026-11-30T00:00:00Z; PAGINATION 10/1/100/0; VOLUME_REF_UNITS 50000, MARGIN_REF_PCT 0.35, SHELF_SHARE_REF_PCT 0.20, BACKLASH_REV_REF_CENTS 10000000000, PL_DAMPING_BASE 0.5, PL_DAMPING_SLOPE 0.005, W 0.30/0.25/0.20/0.25, CUT_RECOMMEND_THRESHOLD 65, SELL_THROUGH_DAYS 90, DAYS_PER_PENALTY_MONTH 30, EARLY_TERM_PENALTY_RATE 0.25, SALVAGE_RECOVERY_PCT 0.20, REVENUE_REF_CENTS_YEAR3 2000000000, W_STRATEGIC_FIT 0.60, W_REVENUE 0.40, CORE_PRIORITY_BONUS 10, TRANSFER_MAX_UTILIZATION_PCT 110, QUAL_MAX_REJECT_RATE_BP 250, QUAL_REQUIRED_CONSECUTIVE_PASSES 2, NEGOTIATION_TTL_DAYS 30. WORKED pins: 80.00/57.14/90.00/63.00→72.04 CUT; obsolescence 50000 vs 40000; TSA penalty 90008 (vs forbidden 90009); priority 68.00 vs 78.00.

**User/role matrix:** PortfolioManager ×5 distinct ids (SoD propose/decide expressible), SupplyChainPlanner scp-1, FinanceController fc-1; entity-backed builders make_brand_manager_headers(brand_id), make_plant_director_headers(plant_id) (threads target_plant_id into run certification), make_retailer_buyer_headers(retailer_id); negative-auth headers_without_role()/headers_without_user_id().

**Verification:** import graph clean (9/9, importlib resolves module vs singleton both directions); AST 9/9; endpoint coverage 40/40 with matching verbs; clock path unprefixed POST /_clock/set_current_utc; 32/32 error ids match SCAFFOLD §1.6 and PRD §5 with identical statuses; all date literals ≥ clock start; compute_sell_through_deadline reproduces both design-index deadlines; offline smoke (SoD distinctness, identity threading, salvageable omission, append-only QualificationRun, unit-balance and capital-conservation invariants) passes.

**PRD-vs-scaffold discrepancies:** none requiring resolution. Cosmetic note: SCAFFOLD §1.4 priority-14 lists two error conditions (ERR_BRAND_CORE, ERR_CLOSE_DATE_OUTSIDE_TSA) under a single error_id field; PRD §5 carries both with 422 and the helper catalog registers both.

Orchestrator verification (independent): 9 files present; `import test_helpers` + submodule imports all succeed; ApiClient exposes 44 public methods (40 typed endpoints + framework helpers). Helpers FROZEN for Stage 2.

## Step 5b: Generate test suite (Stage 2 of Step 5) — 2026-10-02T06:45:00.000Z

Stage 2 is complete. Final summary:

**Deliverables:** `test_suite/` — 23 files, 3082 lines, 98 tests. The frozen `test_helpers/` layer was not modified.

| File | Lines | Tests |
|---|---|---|
| conftest.py | 50 | — (api + 7 role-header fixtures) |
| test_01_difficulty_dual_variant.py | 170 | 4 |
| test_02_difficulty_combinatorial.py | 154 | 4 |
| test_03_difficulty_nonlinear_state.py | 163 | 4 |
| test_04_difficulty_cascades.py | 199 | 4 |
| test_05_difficulty_priority_pairs.py | 127 | 4 |
| test_06_difficulty_boundaries.py | ~129 | 4 |
| test_07_difficulty_cross_entity.py | 109 | 4 |
| test_08_difficulty_temporal_overlap.py | 147 | 4 |
| test_09_difficulty_invariants.py | 177 | 4 |
| test_10_corner_entities.py | 182 | 7 |
| test_11_corner_state_machines.py | 192 | 7 |
| test_12_corner_state_machines_lifecycle.py | 106 | 4 |
| test_13_corner_calculations.py | 169 | 5 |
| test_14_corner_validations_authz.py | 89 | 4 |
| test_15_corner_validations_uniqueness.py | 134 | 5 |
| test_16_corner_validations_composition.py | 122 | 5 |
| test_17_corner_validations_bounds_timing.py | 130 | 5 |
| test_18_corner_endpoints.py | 142 | 5 |
| test_19_corner_errors.py | 54 | 3 |
| test_20_corner_rbac.py | ~177 | 8 |
| test_21_corner_complexity.py | 130 | 3 |
| test_22_corner_consistency.py | 42 | 1 |

**Tag audit (real AST parse):** Emitted 98 = 36 difficulty (18 instances × exactly 2) + 62 corner (62 × 1). All 9 difficulty rules at 4 tests each. Per corner section: entities 7, state_machines 11, calculations 5, validations 19, endpoints 5, errors 3, rbac 8, complexity_layers 3, consistency_model 1 — matches index exactly. Tags pointing to non-existent instances: 0. Duplicate corner tags: 0. Instances with no test: 0. No skip/xfail markers. 5 excluded_because stubs correctly got NO test; all 5 stub→difficulty cross-references resolve. Verbatim-citation sweep: all 98 docstrings contain a ≥8-word substring surviving literal grep of PRD.md. pytest --collect-only: 98 collected, 0 errors.

**Skipped instances:** None. All 80 active instances passed the PRD-first two-condition filter.

**Notable adjudications:** system-stamped datetimes PRD §2.5 does not pin to three fractional digits (sell_through_deadline, expires_at, closure_date) asserted by parsed-instant comparison, not exact string; created_at uses exact 2026-09-01T00:00:00.000Z string because §2.5 pins its format. TSA-penalty second test uses distinct reachable data point (terminate 2027-08-13 → 19 days → 1 month → 30,002.5 → 30,003 half-up) instead of bare != 90009. Respond-priority second test exercises ACCEPTED terminal state (symmetric to recipe's REJECTED). All clock moves ascend within each test, reachable from clock start via unprefixed POST /_clock/set_current_utc.

Orchestrator verification (independent): AST-walked all 22 test files — 98 Design tags, 80 unique; diffed against parsed indices (80 active instance tags): emitted-not-in-index NONE, index-without-test NONE. pytest --collect-only: 98 collected in 0.24s, 0 errors.

## Step 6: Generate implementation — 2026-10-02T07:12:00.000Z

Done. The implementation is complete, smoke-tested, and cleanly shut down. Final report:

**What was built:** Python + Flask implementation in `workspace/implementation/`, all 40 endpoints (39 under `/portfolio` + the unprefixed clock), in-memory dict storage created empty at boot, no seeding.

**File list (lines):** `start.sh` (19 — guarded dep install, `exec python3 app.py`, PORT env default 10000 per INSTRUCTION.md, binds 0.0.0.0, foreground); `requirements.txt` (1 — flask>=3.0,<4.0); `app.py` (81 — blueprint registration, unprefixed POST /_clock/set_current_utc, error handlers); `clock.py` (36 — fixed default 2026-09-01T00:00:00Z, never wall-clock, 3-fractional-digit ISO serializer); `storage.py` (38); `errors.py` (53 — full 32-entry catalog); `rbac.py` (66 — six roles, steps 1-3, global request lock); `envelope.py` (92 — meta/response_type/data, pagination); `validation.py` (117 — step-4 body validators, ISO8601); `calculations.py` (231 — all pinned literals: composite 50000/0.35/0.20/10^10/0.5+0.005/0.30-0.25-0.20-0.25/65 with sub-scores rounded before composite; TSA penalty ceil→multiply→round 30-day months 0.25; obsolescence STANDARD/SALVAGE 0.20; priority STANDARD/CORE_BRAND 2×10^9 ref 0.60/0.40 +10 cap 100; plant load per-item half-up then sum; integer gates 250bp/110%; waterfall priority DESC, created_at ASC, never id); `serializers.py` (211); routes: `routes_foundation.py` (155), `routes_items.py` (126 incl. OCC sell-down), `routes_cases.py` (146), `routes_divestitures.py` (179), `routes_tsas.py` (77, 3-hop cascade), `routes_transfers.py` (157, runs + auto-execute), `routes_negotiations.py` (162), `routes_capital.py` (135).

**Boot log evidence:** `portfolio-rationalization api booting on 0.0.0.0:53777 logical_clock=2026-09-01T00:00:00.000Z`. Fresh boot `GET /portfolio/brands` → empty list envelope with total_count 0.

**Smoke-test evidence (two rounds, all passed):** (a) unprefixed clock set → 200 with current_utc echo; (b) Brand/Plant/Retailer creates → 201 each; (c) full rationalization chain with PRD worked example → scores 80.00/57.14/90.00/63.00, composite 72.04, CUT → APPROVE by second PM → EXECUTING, item SELL_THROUGH deadline 2026-11-30T00:00:00.000Z (+90d) → finalize at exact deadline (inclusive) → EXECUTED, item DISCONTINUED, obsolescence 170000 STANDARD, plant load recomputed 0; (d) catalog errors verified: ERR_MISSING_ROLE 401, ERR_SELF_DECISION 403, ERR_SELL_THROUGH_OPEN 409, ERR_SAME_PLANT 422, ERR_OWNERSHIP_MISMATCH 403, ERR_INVALID_STATE 409, ERR_STALE_VERSION 412. Round 2: 250bp boundary PASS (200/5), FAIL reset, auto-EXECUTE at 2 consecutive passes with plant rewrite; TSA penalty worked example → 90008 cents exactly; divestiture to SEPARATED/EXITED; negotiation +30d TTL, wrong-buyer 403, ACCEPT; waterfall funds core 78.00 over standard 68.00, allocated 60000/remaining 40000, skip-and-continue DEFERRED. Servers killed by exact PID only.

**Interpretations chosen (PRD-under-determined points):**
1. All server-stamped timestamps read the logical clock (created_at, updated_at, api_request_timestamp) — expires_at = created_at + 30d forces created_at onto the logical clock; extended uniformly.
2. All datetimes serialize with 3 fractional digits + Z.
3. Clock may be set to any instant (no monotonicity rule in PRD).
4. Naive ISO datetimes assumed UTC rather than rejected.
5. Inverted negotiation window → ERR_INVALID_REQUEST per PRD §3.6 prose, overriding scaffold validation 17 (ERR_NEGOTIATION_WINDOW_OVERLAP); inverted cycle window → ERR_CYCLE_WINDOW_OVERLAP.
6. Invalid limit/offset → ERR_INVALID_REQUEST; unknown list-filter values yield empty lists; unknown query params ignored.
7. created_at ties break by insertion sequence, never id — list sorting and waterfall tie-break.
8. Extra/unknown body fields ignored everywhere, including version sent to non-OCC endpoints.
9. Empty strings accepted for name/sku_code/period_code; X-User-ID rejected only when absent or literally empty.
10. Scalar uniqueness is global across all records of a type regardless of lifecycle state.
11. Plant load and cycle remaining_cents computed on read (never stored).
12. TSA cascade ordering: items discontinued in creation order, then open cases VOIDED with decider_user_id="system"; TSA version bumps once.
13. Case-create step-7 guard rejects only DISCONTINUED; CUT_PROPOSED/SELL_THROUGH fall through to step-11 ERR_CASE_ALREADY_OPEN per PRD §2.8 callout.
14. REJECT branch of decide does not re-check item state.
15. Respond on expired negotiation mutates to EXPIRED and bumps version before returning 409.
16. PORT default 10000 (INSTRUCTION.md contract).

Orchestrator verification (independent boot on dynamic port 41505): unprefixed POST /_clock/set_current_utc → 200 with correct envelope; GET /portfolio/brands → 200 empty array envelope with meta{limit 10, offset 0, total_count 0, has_more false}; killed by exact saved PID.

## Step 7: Test-fix iteration loop — 2026-10-02T07:35:00.000Z

All 8 rounds pass 98/98. Results files remain in `workspace/implementation/` as evidence.

- **Iterations run:** 2 (baseline sweep: 94/98 in all 8 rounds, same 4 deterministic failures; post-fix sweep: 98/98 × 8 rounds, clean).
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none — the role-header builders and fixtures were already PRD-faithful (`fixtures.py`'s `create_project` already defaults to PortfolioManager).
- **Fixes applied to `test_suite/` (test bug, STEP 2 — request identity violated PRD role mapping):**
  - `test_suite/test_01_difficulty_dual_variant.py` — `TestInnovationPriorityDualVariant`: both tests (`test_priority_score_standard_variant_plain_blend`, `test_priority_score_core_brand_variant_adds_bonus`) created innovation projects with `fc_headers` (FinanceController). Switched to `pm_headers` (PortfolioManager). The assertions themselves (68.00 STANDARD / 78.00 CORE_BRAND) trace verbatim to PRD §3.7's worked example.
  - `test_suite/test_09_difficulty_invariants.py` — `TestCapitalConservationAcrossWaterfall._setup_cycle_with_three_projects`: the three `create_innovation_project` calls used `FC`. Added `PM = TEST_USERS["portfolio_manager_headers"]` and switched creation to PM; kept FC for `run_capital_cycle_selection` (PRD-correct) and GETs (all-role).
- **Fixes applied to `implementation/`:** none — the implementation's 403 `ERR_FORBIDDEN_ROLE` for FinanceController on `POST /portfolio/innovation-projects` was PRD-correct. PRD §2.1 states verbatim: "Item creation and innovation-project creation are shared between `PortfolioManager` and `BrandManager`" and the endpoint table lists "PortfolioManager, BrandManager" for that route; FinanceController "exclusively controls capital cycles, runs selection, and terminates transition service agreements." The tests' fixtures contradicted the PRD, so the tests were fixed, not the implementation.

Final state: 8/8 rounds clean at 98/98 under per-test-server isolation; all 8 `results.{1..8}.json` files left in `workspace/implementation/`.

Orchestrator verification (independent): (1) all 8 results files present, each passed=98 total=98 failed=0; (2) PRD.md line 21 contains the verbatim role sentence the fix direction hinged on — the FC→PM repairs are faithful to PRD, implementation's 403 is PRD-correct; (3) no implementation/*.py file is newer than results.1.json — no post-sweep impl writes; (4) spot-checked shipped test files — test_01 uses pm_headers at lines 117/133/139/159/162, test_09 line 26 adds PM constant and lines 114–126 pass PM to create_innovation_project. Claims match source.

## Step 8: Finalize PRD — SKIPPED — 2026-10-02T07:36:00.000Z

Skip decision (orchestrator): Step 7 had **0 `implementation/` fixes, 0 deletions, 0 `test_helpers/` fixes** — the only changes were 4 `test_suite/` header repairs where the tests contradicted an already-verbatim PRD §2.1 role sentence. Per the pipeline overview ("skipped if Step 7 had 0 implementation/ fixes") and Step 8's own HARD SCOPE (every PRD edit must trace to a fix revealing PRD-silence or PRD-mismatch *with implementation/*), there is no qualifying edit site: the PRD was already correct and the implementation already matched it. Running Step 8 here would ship a byte-identical PRD_FINALIZED.md (known fixture-only-diff pattern). Step 9 still runs unconditionally and performs the full PRD-vs-implementation scan, which subsumes any residual.

## Step 9: PRD completeness scan — 2026-10-02T07:55:00.000Z

The diff confirms exactly the 7 intended edit sites and nothing else. Final report:

**Files:** `PRD.md` (297 lines, 52,562 chars) → `PRD_COMPLETED.md` (299 lines, 54,240 chars). Delta: +2 lines, +1,678 chars. All edits inline; no new sections.

**Counts:** 7 ambiguity-pins, 1 mismatch-revision.

### Changes

- §2.2 — insert — ambiguity — pinned fallback failures that never reach a route: unmatched path → ERR_NOT_FOUND 404, unsupported method → ERR_INVALID_REQUEST 400, internal failure → ERR_INVALID_REQUEST with HTTP 500, all in the standard envelope — implementation/app.py:59-74
- §2.3 — insert — ambiguity — malformed pagination params (non-base-10 integer, limit outside 1..100, negative offset) rejected with ERR_INVALID_REQUEST 400 — implementation/envelope.py:51-77
- §2.3 — insert — ambiguity — list ordering tie-break (same logical created_at keeps relative creation order, never id) and total_count/has_more semantics (total_count = all filter-matching records; has_more iff offset + page size < total) — implementation/envelope.py:78-92
- §2.5 — insert — ambiguity — datetime request fields accept ISO 8601 with trailing Z or numeric offset; offsetless values read as UTC — implementation/validation.py:85-101
- §2.5 — insert — ambiguity — list filter values are exact-match; a non-matching filter yields an empty page with 200, not an error — e.g. implementation/routes_items.py:80-83 (same pattern in all 10 list handlers)
- §3.4 — insert — ambiguity — every accepted qualification run (PASS or FAIL) increments the transfer's version by exactly 1 (status transition / counter update / updated_at refresh); the auto-executing 2nd PASS adds no second transfer increment and increments the item once — implementation/routes_transfers.py:133-144
- §3.7 — insert — ambiguity — waterfall ranking sub-tie-break: projects tied on both priority_score and created_at keep relative creation order, still never id — implementation/calculations.py:195
- §4 — revise — mismatch — the "record an event → 200" clause would have made run-recording a 200; impl creates an immutable QualificationRun and returns 201, so the sentence now classifies run-recording as a create (201) — implementation/routes_transfers.py:145

### Coverage proof (modules walked)

app.py (1 endpoint + 3 error handlers; blueprints under /portfolio); clock.py (startup default 2026-09-01T00:00:00Z, set/now/iso); envelope.py (envelope, request-id, pagination validation, sort); errors.py (all 32 IDs and HTTP statuses checked against §5 — exact match); rbac.py (6 roles, precedence steps 1–3); validation.py (8 body/field validators incl. bool rejection of ints); storage.py (12 entity stores, insertion sequence, UUID minting); calculations.py (13 calculation units: 4 case sub-scores + composite + recommendation, quarterly commitment, plant load, capacity gate, qualification gate, TSA penalty ceil→multiply→round, obsolescence STANDARD/SALVAGE, discontinue, priority STANDARD/CORE_BRAND, negotiation totals, waterfall — all 20 pinned constants verified against PRD literals; all 4 PRD worked examples reproduce impl arithmetic exactly: 72.04/CUT, 90,008 penalty, 68.00/78.00 priority, 40,000 salvage); serializers.py (12 serializers; run_out correctly omits updated_at/version; plant load and cycle remaining_cents computed on read); routes_foundation.py (7 endpoints: 3 creates with uniqueness guards, 2 lists, announce/complete closure with state + emptiness guards); routes_items.py (4 endpoints: item create 5-check guard chain in §2.8 order, list 3 filters, get, OCC sell-down bounds at step 21, stale-version last); routes_cases.py (5 endpoints: propose score-at-creation + item→CUT_PROPOSED, decide both branches with self-decision after state guards, finalize inclusive deadline); routes_divestitures.py (6 endpoints: propose/sign/close/separate with side-effect version bumps; brand UNDER_REVIEW→DIVESTING→DIVESTED→EXITED; TSA created DRAFT at signing); routes_tsas.py (3 endpoints: terminate with penalty + 3-hop cascade — items discontinued, open cases VOIDED decider system, plants recompute on read); routes_transfers.py (5 endpoints: create guard battery §2.8 order steps 8→11→12→20, 110% integer capacity gate, run recording with auto-execute at 2 consecutive passes); routes_negotiations.py (4 endpoints: composition 2–5/distinct/ACTIVE, closed-interval overlap, 30-day TTL inclusive boundary + auto-EXPIRED-on-late-respond); routes_capital.py (5 endpoints: half-open cycle windows adjacency allowed, one-shot selection, size cap, priority at creation). Endpoint inventory: 40 routes, matching §4 row-for-row (including absence of single-brand/plant/retailer GETs).

### Impl-side defects found (named, NOT papered over)

1. **`sell_through_deadline` is never reset to null.** PRD §3.2 states the field "is null at all other times in an item's life", but finalization (routes_cases.py:142-146 → calculations.py:154-163 discontinue_item) and the TSA cascade (routes_tsas.py:63-64) leave the stamped deadline in place on DISCONTINUED items. Tests only assert null pre-approval (test_10_corner_entities.py:141), so the deviation is unasserted. The PRD sentence was left unchanged — this is an impl-side gap, not a PRD error.
2. **Minor catalog tension:** the 500 fallback emits error_id ERR_INVALID_REQUEST with HTTP 500, outside the §5 mapping (ERR_INVALID_REQUEST → 400); the 405 handler similarly returns 400 rather than 405 (app.py:65-74). Unreachable in the graded regime; pinned as-is in the new §2.2 sentence and flagged.

## Step 9-follow-up: Fix sell_through_deadline-null defect + re-sweep — 2026-10-02T08:05:00.000Z

Fix complete and fully verified. Final report:

**Step 1 — grep classification of every sell_through_deadline read/assertion.** test_suite/ 4 sites: test_10_corner_entities.py:141 asserts null on LISTED item (PRD-consistent); test_13_corner_calculations.py:88 asserts deadline == decide+90d during SELL_THROUGH; test_03_difficulty_nonlinear_state.py:91 asserts CLOCK_START+90d during SELL_THROUGH; test_11_corner_state_machines.py:156 docstring quote only. test_helpers/ 6 sites: assertions.py:98 state-agnostic nullable-timestamp check; fixtures.py:69-70 pure date-math helper; fixtures.py:161-163 docstring; fixtures.py:185 clock-set before finalize (no field assertion on the DISCONTINUED item); constants.py:44 comment; types.py:118,144 comment + Optional[str]. No test asserts non-null deadline outside SELL_THROUGH → no test-side conflict.

**Step 2 — diff applied.** One file: workspace/implementation/calculations.py discontinue_item — added `item["sell_through_deadline"] = None` at line 164 immediately after the status flip, plus one docstring line. Site-B note: both discontinuation paths (routes_cases.py:145 finalize, routes_tsas.py:64 TSA cascade hop 1) call this shared discontinue_item; routes_tsas.py contains no inline item mutation. Verified by grep these are the only two DISCONTINUED-write paths. No other behavior changed; PRD.md, PRD_COMPLETED.md, test_suite/, test_helpers/ untouched.

**Step 3 — sweep results:** rounds 1–8 all 98/98, 0 failed / 0 errors / 0 skipped in every round.

**Step 4 — results files:** all 8 results.{1..8}.json confirmed on disk.

Orchestrator verification (independent): calculations.py:164 contains the fix; results.1.json mtime 07:55 is newer than calculations.py mtime 07:52 (sweep ran after the fix); parsed all 8 results files — each passed=98 total=98 failed=0.

## Pipeline complete — 2026-10-02T08:06:00.000Z

Final state: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml (12 entities, 10 state machines, 10 calculations, 23 validations, 40 endpoints, 32 errors, 6 roles; 18 §1.8 instances, 67 §1.9 instances); PRD.md 297 lines; test_helpers/ 9 files frozen; test_suite/ 23 files / 98 tests (80 unique Design tags, 0 gaps, 0 dangling); implementation/ Python+Flask, in-memory, 40 endpoints incl. unprefixed clock; PRD_COMPLETED.md 299 lines (+7 ambiguity pins, +1 mismatch revision over PRD.md); Step 8 skipped (0 implementation fixes in Step 7); final evidence 8 × results.{1..8}.json all 98/98 under per-test-server isolation.
