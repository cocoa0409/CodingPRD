# Worklog — task_3415_domestic_shoe_manufacturing_content_claim_substantiation

## Step 1: Create Task Directory — 2026-10-01T21:22:00.000Z

Task directory pre-allocated per command args: `./tasks/task_3415_domestic_shoe_manufacturing_content_claim_substantiation/` with `workspace/` inside. Verified existence; did not compute a new index. Difficulty directive: "Generate task much harder than expert level!" (passed to scaffold generator only).

## Step 2: Generate Scaffold — 2026-10-01T21:45:00.000Z

Scaffold generation complete. All three artifacts are written and pass every audit, including a clean `scaffold_lint.py` run.

### Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_3415_domestic_shoe_manufacturing_content_claim_substantiation/SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_3415_domestic_shoe_manufacturing_content_claim_substantiation/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3415_domestic_shoe_manufacturing_content_claim_substantiation/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

### Counts
- **SCAFFOLD**: 13 entities, 11 state machines, 8 calculations, 12 ordered validation priority rows, 66 endpoints (incl. `POST /_clock/set_current_utc`, default clock pinned at `2026-09-01T00:00:00Z`), 64 error codes, 7 roles, 2 OCC concurrency rules. api_prefix `/footwear`.
- **§1.8 difficulty design**: 18 instances — all 9 rules × 2, each with a falsifiable `distinguishing_aspect` and a fully structured `setup_api_calls` chain (YAML anchors reused across instances; every `${var}` placeholder closure-verified, every formula-derived assert pre-computed in Python: 83.33 vs 84.00 content divergence, 75.0 vs 81.5 skill-coverage divergence, 5980/5750/4600 surcharge tiers, 19575 vs 20663 evaluation-order discriminator, 95.00/94.99/70.00 threshold fixtures, exact-fit capacity boundary).
- **§1.9 corner design**: 98 instances (81 with full recipes, 17 `excluded_because:` stubs pointing at §1.8). All 64 error codes are exercised by at least one instance; all enum values are used; instance names unique (115 across both files).

### Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Notable design decisions
- **Archetype**: compliance/audit (FTC "Made in USA" thresholds 95/70/20 + Berry 100.00) with quota/allocation secondary (weekly domestic/import capacity pools); flat FK topology; segregation-of-duties role model (evidence uploader can't verify/reject own document; FactoryManager is `entity_backed:Factory`).
- **Hardness via coupling, per the harder-than-expert directive**: depth-3 cascade (lot-cert rejection → certified-report supersede at 100.00→0.00 → claim CHALLENGED → contract COMPLIANCE_AUDIT), depth-2 factory-suspension cascade with lot re-credit and order unschedule, dual-variant calculations on two different entity domains, combinatorial formulas in modes (a) and (c) with a pinned rounding-order (b) corner, half-open line windows vs closed contract windows, two OCC rules, two compensating invariants (pool-sum and lot-quantity conservation).
- **Endpoint count is 66** — deliberately above the expert band (the scenario's eight mandated elements plus FK reverse-reachability and lint rules require them); difficulty is carried by density rather than CRUD volume (every endpoint is load-bearing for a state machine, cascade, or reverse-lookup).
- One caution to flag: SCAFFOLD.yaml was re-serialized once via `yaml.safe_dump` during a surgical fix, so its comments are stripped (content and structure verified intact afterward — scenario text verbatim, envelope fixed block exact, all machines/endpoints/roles confirmed by audit).

Orchestrator verification: all three files parse as YAML; SCAFFOLD.yaml top keys = scenario/domain_name/api_prefix/complexity_profile/response_envelope/entities/state_machines/concurrency_rules/calculations/validations/endpoints/errors/roles; design keys absent from SCAFFOLD.yaml; `/footwear` × 119; entities on-scenario (Factory, ShoeModel, Component, MaterialLot, ProductionRun, DomesticContentReport, CustomOrder, LabelClaim, EvidenceDocument, Worker, TrainingEnrollment, CapacityAllocation, GovContract); 66 endpoints confirmed.

## Step 3: Copy Shared Files — 2026-10-01T23:22:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_3415_domestic_shoe_manufacturing_content_claim_substantiation/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-01T23:40:00.000Z

The "about" is non-numeric prose ("a decision about where it may be made") — not an approximation. All audits pass. The PRD is complete.

### Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3415_domestic_shoe_manufacturing_content_claim_substantiation/workspace/PRD.md` — 403 lines, written incrementally in 14 chunks (title/§1/§2.1, then quoted-heredoc appends with tail verification after each).

**Section list:**
- §1 Introduction (2 paragraphs: regulatory/business context + system scope, `/footwear` mount, logical clock)
- §2 Global Specifications: 2.1 RBAC (7 roles, identity prose per role), 2.2 API Response Structure (**byte-identical verbatim block**, verified programmatically), 2.3 Pagination, 2.4 Logical Clock & Document Freshness, 2.5 Common Resource Properties, 2.6 Money/Units/Rounding Discipline, 2.7 OCC, 2.8 Validation Priority Order (all 12), 2.9 Nested Retrieval & Referential Integrity, 2.10 Cascading State Propagation
- §3 Business Logic (9 subsections: factories, workforce/training, models+BOM+lots, capacity waterfall, production runs, content reports+pricing, custom orders, claims+evidence, government contracts)
- §4 Endpoint Definitions (4-column table, 66 rows) · §5 Error Catalogue (2-column table, 64 rows)

**Hard-contract audit results:**
- **Contract 1 (field-name coverage):** 103 required identifiers (entity fields + endpoint input/query/path params + nested BOM/consumed_lots/certification member names), 103 present in backticks, 0 missing — PASS. (An initial false-negative run was caused by my audit script mis-pairing backticks around §2.2's JSON fences, not by the document; stripping fences fixed the checker.)
- **Contract 2 (rule coverage):** all 12 validation priorities expressed with explicit evaluation order (incl. priority-7's internal order and masking examples); both OCC rules with write capability, `expected_run_version`/`expected_run_version` fields, exact error IDs and 412; all 11 state machines' transitions with preconditions + error IDs + side effects (34 distinct state values all present); all 8 calculations as reconstructible prose (FIFO order/tiebreaks, pinned rounding orders, tier constants 10/25/50→25/15/8%+5%, markup 1.15, fees 500/250, discount tiers 20000/12000, thresholds 95.00/70.00/20.00, Berry 100.00, coverage weights 0.5/0.3/0.2 and 0.5 pipeline credit); all cascade hops (factory suspend, evidence-reject hops 1–3, worker/cert suspend) and all 64 error IDs bound to trigger conditions in §2/§3 — PASS.
- **Contract 3 (§3 path purity):** 774 backticked tokens scanned, 0 path/method violations — PASS.

**Judgment calls (flagged, not silent):** (1) Three errors whose validation-family status differs from the error catalog (`ERR_EVIDENCE_STALE`, `ERR_WORKFORCE_SHORTFALL` cataloged 422 under a 409 family; `ERR_WEEK_RUNS_OPEN` cataloged 409 under a 422 family) — I rendered the per-error catalog statuses as authoritative. (2) Custom-order creation on a `DISCONTINUED` model: the endpoint demands an `ACTIVE` model but the catalog's `ERR_MODEL_NOT_ACTIVE` condition doesn't enumerate order-create; I projected that error onto the case as the least-inventive reading. No scaffold rule was omitted; nothing unrenderable.

Orchestrator verification: PRD.md = 403 lines, starts `# Domestic Footwear Content Claims API — Product Requirements Document`, ends at error catalogue with ERR_STALE_ALLOCATION_VERSION 412; 64 unique `ERR_*` tokens (matches scaffold's 64); 66 `/footwear` refs.

## Step 5: Generate Unit Tests — 2026-10-02T00:15:00.000Z

Generation complete and fully audited. Summary:

### Files written (29)

**test_helpers/** (Stage 1, frozen after write): `types.py` (13 entity TypedDicts + 17 enums), `api_client.py` (52 endpoint methods; clock at `/footwear/_clock/set_current_utc` per task pin), `api_errors.py` (64-error catalog + `set_error_http_status_map` registration), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (7 roles; `make_factory_manager_headers` for the entity-backed FactoryManager), `fixtures.py` (primitives + composites: `standard_kit`, `completed_run_kit`, `m95_completed_run` (95.00), `m70_completed_run` (70.00), `berry_completed_run` (100.00), `claim_with_verified_docs`, `substantiated_claim_95`/`published_claim_95`, `accepted_order`, `certify_pair`), `__init__.py` barrel.

**test_suite/** (Stage 2): `conftest.py` + 19 test files, 117 tests, all ≤15 tests/file. `pytest --collect-only` passes with zero errors.

### AST tag audit (real `ast.walk`, not grep)

- **Queue A (Difficulty): 18/18 instances covered, each with exactly 2 tests (36 tests).**
- **Queue B (Corner): 81/81 non-stub instances covered, 1 test each (81 tests).**
- **Skipped: none** — every live instance passed the PRD-first two-condition filter. The 17 `excluded_because:` stubs were not translated; all their `difficulty_instance` cross-references resolve.
- 0 untagged, 0 multi-tagged, 0 unresolvable tags; 0 `skip`/`skipif`/`xfail`; all 176 multi-word docstring citation spans grep verbatim in `workspace/PRD.md`.

### Internally inconsistent recipes (re-derived, named explicitly)

1. **`Difficulty/compensating_invariant/capacity_shift_conserves_total_reserved_units`** — recipe asserts post-`TO_DOMESTIC 20` pools as `domestic 50 / import 30`, which sums to 80 and contradicts the recipe's own `sum == total_reserved_units (100)` invariant; correct values are `50 / 50` (30+20, 70−20). Test emits the corrected literals; the compensating return to `30 / 70` is unchanged.
2. **`Corner/entities/factory_create_applies_defaults_and_default_logical_clock`** — the recipe's `created_at == '2026-09-01T00:00:00Z'` exact literal conflicts with PRD §2.5 ("three fractional digits") and §2.4 names only `received_at`/`substantiated_at`/`published_at` as logical-clock-stamped. The test asserts the uniquely-derivable outcomes (status ACTIVE, version 1, `government_cleared` default false, both skill-coverage fields 100.0, UUID id, ISO-8601 timestamps) and omits the exact-timestamp equality.
3. **`Corner/errors/err_material_shortage_vs_domestic_shortage`** — setup prose references "two STOCK runs of 10 (separate models)" but defines only one model and the trigger uses one run; emitted with the single reachable run.

Also note: the OCC report-create test (`occ_report_create_with_stale_run_version_returns_412`) asserts run `version` increments on report creation — uniquely forced by PRD §2.7's stated guard rationale (a stale writer would otherwise supersede a report it never saw). Clock-derived timestamp assertions use prefix matching (`startswith("2026-09-01T00:00:00")`) to tolerate the PRD's fractional-digit format latitude while still pinning the logical clock value.

Orchestrator verification: 9 helper files + conftest.py + 19 test files present; independent `pytest --collect-only -q` run collected **117 tests** with 0 errors.

## Step 6: Generate Implementation — 2026-10-02T01:30:00.000Z

Implementation complete and verified. Summary below.

### File tree (line counts) — `workspace/implementation/`

| file | lines | role |
|---|---|---|
| start.sh | 10 | guarded-install foreground launcher (`exec python3 app.py`, `0.0.0.0:$PORT` default 10000) |
| requirements.txt | 1 | flask>=2.2,<4 |
| app.py | 76 | thin factory: registers 13 blueprints, envelope error handlers (ApiError/404/405/500 with traceback logging) |
| constants.py | 98 | every PRD/scaffold-named constant (roles, enums, tiers, fees, weights, thresholds, clock default) |
| errors.py | 98 | full 64-id error catalog + 3 framework fallbacks, `ApiError` |
| state.py | 84 | in-memory stores (empty at boot, no seeding), logical clock, `base_fields`/`touch`, stable sort |
| response.py | 70 | envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`), pagination meta, error body |
| middleware.py | 42 | `X-User-ID`/`X-User-Role` extraction (ERR_MISSING_USER_CONTEXT) + per-endpoint role guard (ERR_FORBIDDEN_ROLE) |
| validation.py | 119 | family-5 schema helpers (typed fields, enums, dates, ISO weeks) |
| calcs.py | 338 | all 8 calculations, Decimal ROUND_HALF_UP with pinned rounding orders |
| cascade.py | 169 | report creation+supersession, factory-suspend cascade, workforce re-check, claim challenge (+hop 3), evidence-reject recompute, lazy expiry |
| serializers.py | 18 | internal-key stripping + computed factory coverage |
| routes_clock.py / routes_factories.py / routes_models.py / routes_lots.py / routes_runs.py / routes_runs_lifecycle.py / routes_reports.py / routes_orders.py / routes_claims.py / routes_evidence.py / routes_workforce.py / routes_capacity.py / routes_gov.py | 48–220 each | 66 endpoints total |

**Endpoint count from Flask url_map: 66** (method+path pairs), matching the scaffold table exactly.

### Smoke-test results (fresh process per boot, dynamic ports, killed only my own PIDs)

- `GET /footwear/factories` no headers → **400** `ERR_MISSING_USER_CONTEXT`
- `POST /footwear/factories` → **201** (coverage fields `100.0/100.0` present); SourcingManager caller → **403** `ERR_FORBIDDEN_ROLE`; unknown id → **404** `ERR_FACTORY_NOT_FOUND`
- Full run lifecycle: create → **201**; lock waterfall → **200** domestic=10/import=190; reserve → **200** consumed 20 units, re-reserve → **409** `ERR_INVALID_STATE`; release re-credits lot (1000, version 3); start without workers → **422** `ERR_WORKFORCE_SHORTFALL`; with 2/1/1 certified → **200**; complete → **200** `certified_unit_cost_cents=6141` (hand-verified: base 5340 × 1.15 tier); CERTIFIED report → **201** pct 100.0; stale `expected_run_version` → **412** `ERR_STALE_RUN_VERSION`; model pricing refreshed (`domestic_price_cents=10977` = round(18500×5340/9000))
- GOVERNMENT run completion → surcharge-exempt cost 5180 (hand-verified)
- Claims/evidence: premature substantiate → **422** `ERR_REQUIRED_EVIDENCE_MISSING`; self-verify → **403** `ERR_SELF_ATTESTATION_FORBIDDEN`; substantiate/publish → **200**; revoke PUBLISHED → **409**; reject VERIFIED claim doc → claim CHALLENGED, `published_at` cleared
- Reject VERIFIED lot origin cert → hop-1 recompute (old report SUPERSEDED, new pct 47.57 = 2540/5340, hand-verified), claim re-pointed and CHALLENGED; hop 3 pushed IN_FULFILLMENT contract → COMPLIANCE_AUDIT
- Gov: closed-window touch → **409** `ERR_GOV_CONTRACT_WINDOW_CONFLICT`; Berry gate passed with 100.00% report
- Shift: stale+over-source → **422** `ERR_SHIFT_EXCEEDS_SOURCE` (correct family ordering: fiscal before OCC); TO_DOMESTIC 5 → **200** pools 5/45 sum preserved; shift on OPEN → **409** `ERR_ALLOCATION_NOT_LOCKED`
- Clock: set → **200** echoes `current_utc`; sweep expired exactly the 3 VERIFIED lapsed docs; REJECTED doc untouched

### Interpretations chosen (ambiguities resolved)

1. **Shift on non-LOCKED allocation** — scaffold precondition said `ERR_INVALID_STATE`, PRD §3.4/§2.8 family 6 say `ERR_ALLOCATION_NOT_LOCKED`; PRD wins → **ERR_ALLOCATION_NOT_LOCKED (409)**.
2. **Start-fulfillment check order** — PRD §3.9 narrative (policy → cleared → Berry) contradicts PRD §2.8 + scaffold family-7 order (Berry → policy → cleared); §2.8 explicitly declares itself the fixed order → **Berry first**, with family-6 states (contract AWARDED, model ACTIVE, factory ACTIVE) before all regulatory checks.
3. **Reserve order** — allocation-existence 404 is family 4, so it precedes the run-state 409 (PRD §3.5 confirms "existence first… then state").
4. **Publish freshness** — "every document counted at substantiation" implemented literally: claim snapshots the qualifying doc ids at substantiate; publish re-checks each snapshot id still VERIFIED unexpired (not a fresh ≥1-of-each-type count).
5. **Re-point without challenge** — a claim whose threshold still passes after a recompute re-point gets `report_id` updated and version +1 (mutation per PRD §2.5); failure folds re-point + challenge into one +1 per the state machine.
6. **quantity_remaining** — stored and mutated (decrement on reserve, re-credit on release / MATERIAL_RESERVED-cancel / suspend reversion) rather than derived, because a QUALITY_HOLD→CANCELLED run retains consumption in a CANCELLED state the derived formula wouldn't count; observable behavior matches the spec.
7. **Timestamps** — `created_at`/`updated_at`/`api_request_timestamp` use wall-clock UTC with 3 fractional digits; `received_at`/`substantiated_at`/`published_at` use the logical clock's raw string (default exactly `2026-09-01T00:00:00Z`); `current_utc` echoes the accepted `to_iso8601` verbatim.
8. **Pagination out-of-range** — limit/offset clamp to [1..100]/[0..] (PRD says "bounded"); non-integer → `ERR_INVALID_REQUEST`.
9. **Invalid `operation` path param on certification endpoints** → `ERR_INVALID_REQUEST` (400, schema family); valid op with no cert entry → `ERR_CERTIFICATION_NOT_FOUND` (404).
10. **PROVISIONAL report on CANCELLED run** → `ERR_INVALID_STATE` (PRD: allowed in any state *other than* CANCELLED); CERTIFIED on non-COMPLETED (incl. CANCELLED) → `ERR_RUN_NOT_COMPLETED`.
11. **Manual SCHEDULED-order cancel** keeps `production_run_id` (scaffold cancel side effects list only version+1; slot accounting is derived from status, so the slot is freed regardless).

Orchestrator verification: all 23 .py files `py_compile` clean; normalized route diff vs scaffold = **0 missing / 0 extra** (only Flask built-in `/static/<filename>` extra; earlier 67-count and `<x>`/`<fid>` diffs were my normalization artifacts — Flask `<param>` vs scaffold `{param}`). Clock path check: scaffold line 1382 + PRD §4 line 267 both pin `/_clock/set_current_utc` UNPREFIXED and impl matches; **test_helpers/api_client.py had wrongly prefixed it `/footwear/_clock/...` — orchestrator fixed to `/_clock/set_current_utc` (test-side bug, found pre-Step-7); collection still 117 tests.**

## Step 7: Run Tests and Iterate — 2026-10-02T01:50:00.000Z

All 8 rounds pass: 117/117, 0 failed, 0 errors, 0 skipped. The sweep evidence files (`results.1.json` … `results.8.json`) are preserved in `workspace/implementation/` as required.

### Summary

**Iterations run:** 2 (sweep 1 identified 4 stable failures; sweep 2 after fixes is clean across all 8 rounds).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none — constants audit against PRD came back clean (thresholds 95/70/20/100, markup 1.15, fees 500/250, discount tiers 20000/12000, weights 0.5/0.3/0.2, surcharge tiers 10/25/50→25/15/8%+5%, pass score 80, clock default all match PRD verbatim).

**Fixes applied to `test_suite/`:**

1. `test_suite/test_04_difficulty_cascades.py` — added `bom_line` to the `test_helpers` import. The helper was exported but never imported, so `test_factory_suspension_holds_and_reverts_runs` and `test_factory_suspension_unschedules_only_reverted_run_orders` died with `NameError`. Pure test-side bug; a suite-wide AST undefined-name scan confirmed this was the only missing import.

2. `test_suite/test_12_corner_state_machines_b.py` — `test_contract_start_with_dual_source_model_returns_policy_error`: added a Berry-qualifying setup (domestic lot + allocation + STOCK run driven to COMPLETED + CERTIFIED 100.00 report on the contract's exact `(model_id, factory_id)` pair), plus `certify_pair`/`start_run`/`complete_run` imports. PRD §2.8 family 7 orders `ERR_BERRY_CONTENT_NOT_PROVEN` *before* `ERR_POLICY_NOT_DOMESTIC_ONLY` while §3.9's gauntlet orders them oppositely — a genuine PRD self-contradiction. With Berry satisfied, the asserted policy error is the unique outcome under both readings, making the test order-independent without weakening the exact `error_id` assertion.

3. `test_suite/test_19_corner_consistency.py` — `test_contract_start_on_uncleared_factory_returns_factory_not_cleared`: same treatment (STOCK run, since GOVERNMENT run creation itself requires a cleared factory), plus `certify_pair`/`complete_run`/`make_allocation`/`start_run` imports. `ERR_FACTORY_NOT_CLEARED` now fires identically under both PRD orderings.

**Fixes applied to `implementation/`:** none — the implementation was already fully PRD-faithful; all four failures were test-side (one missing import, two order-sensitive fixtures). The impl's Berry-first choice (worklog interpretation #2, following §2.8's self-declared fixed order) was left intact.

**Key findings:** the only real ambiguity surfaced is the §2.8-vs-§3.9 precedence contradiction for contract-start checks; both fixtures now isolate their target rule so either faithful implementation reading passes.

Orchestrator verification: all 8 `results.*.json` present and each reports passed=117 failed=0 total=117 errors=0 skipped=0; claimed fixes confirmed in test_04 (bom_line import, line 6) and test_12 (certify_pair import + call); 0 implementation/*.py and 0 test files newer than results.1.json (no post-sweep writes); `pytest --collect-only` still collects 117.

## Step 8: Finalize PRD — 2026-10-02T02:05:00.000Z

The edit is complete and verified. Final verification against the implementation's exact check sequence (routes_gov.py:104–137) confirms a one-to-one match: AWARDED → model ACTIVE → factory ACTIVE → Berry → DOMESTIC_ONLY policy → factory cleared.

### Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3415_domestic_shoe_manufacturing_content_claim_substantiation/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 403 lines, PRD_FINALIZED.md 403 lines — 0.0% delta (one line revised in place, no insertions or deletions).

#### Changes (1 edit)

- **§3.9 (Government Procurement, start-fulfillment paragraph, line 255) — revise** — Reordered the Berry-gate gauntlet to match §2.8 family 6→7 and the implementation: state checks first (`ERR_INVALID_STATE`, `ERR_MODEL_NOT_ACTIVE`, `ERR_FACTORY_NOT_ACTIVE`), then family 7 with Berry first (`ERR_BERRY_CONTENT_NOT_PROVEN` → `ERR_POLICY_NOT_DOMESTIC_ONLY` → `ERR_FACTORY_NOT_CLEARED`); added an explicit "priority order of §2.8" pointer; split factory-ACTIVE into its own clause (impl checks it in family 6, before Berry); updated closing count "all five hold" → "all six hold" to match the six clauses. The original §3.9 narrative ordered Berry *last*, contradicting §2.8 family 7's fixed Berry-first order — this was the one genuine PRD self-contradiction surfaced by Step 7 — `implementation/routes_gov.py:104-137`

#### Per-item disposition of the Step 7 diff

- **Item 1 (test_04 missing `bom_line` import):** pure test-side bug — helper existed in test_helpers but was never imported; reveals no PRD silence or impl behavior. No edit.
- **Items 2+3 (order-sensitive contract-start fixtures):** jointly name the single genuine PRD defect — §2.8 family 7 orders `ERR_BERRY_CONTENT_NOT_PROVEN` before `ERR_POLICY_NOT_DOMESTIC_ONLY`/`ERR_FACTORY_NOT_CLEARED`, while §3.9's narrative ordered them oppositely. The implementation follows §2.8 (Berry first). Resolved by the one §3.9 edit above; §2.8 itself already matched the impl and was left verbatim.
- **Zero implementation fixes / zero deletions:** nothing else to pin.

#### Pre-edit search log (for the single edit)

- **(a) Subject:** check ordering of the contract start-fulfillment gauntlet (position of Berry relative to the policy and factory-clearance rules, and of the factory-ACTIVE check).
- **(b) Impl paths enumerated and read:** `implementation/routes_gov.py` read in full — `start_fulfillment` (lines 99–140) is the sole gauntlet site with order INVALID_STATE → MODEL_NOT_ACTIVE → FACTORY_NOT_ACTIVE → BERRY → POLICY_NOT_DOMESTIC_ONLY → FACTORY_NOT_CLEARED; `create_contract`, `initiate_audit`, `complete_audit` run none of these checks. `implementation/routes_runs.py:40-84` — run creation's own family-7 checks (GOV_RUN before POLICY_FORBIDS), a different endpoint already consistent with untouched §2.8. `implementation/cascade.py:110-119` — challenge cascade only reads `IN_FULFILLMENT` status, never runs the gauntlet. `implementation/constants.py:92` — `BERRY_REQUIRED_PCT = Decimal("100.00")`, matching the verbatim "100.00" in the sentence. Greps for `BERRY`, `POLICY_NOT_DOMESTIC_ONLY`, `FACTORY_NOT_CLEARED`, and `IN_FULFILLMENT` across `implementation/` confirmed no other code path performs or is described by these checks.
- **(c) Wording adjustment:** factory-ACTIVE split into its own clause placed before Berry (impl evaluates it in family 6, ahead of all family-7 checks — keeping it grouped with the cleared check after Berry would have mis-described the suspended-factory-plus-unproven-Berry case); Berry moved ahead of the policy/clearance clauses per §2.8; explicit §2.8 cross-reference added; count updated five→six. Every enumerated path is exactly described by the revised sentence.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one line revised (§3.9 line 255 — Berry moved ahead of policy/clearance, §2.8 pointer added, five→six); 403→403 lines; 0 files under implementation/, test_suite/, test_helpers/ newer than results.1.json (Step 8 was read-only on those trees as instructed).

## Step 9: Complete PRD — 2026-10-02T02:30:00.000Z

All edits are in place and verified by the diff. Here is the final summary.

### Result

**Files:** `PRD_FINALIZED.md` (source, untouched) 403 lines / 80,128 chars → `PRD_COMPLETED.md` 403 lines / 82,127 chars (char-delta +1,999; all edits in-paragraph, no new sections, line count unchanged).

**Counts:** 8 ambiguity-pins, 4 mismatch-revisions (12 changes total, at 11 diff hunks).

#### Changes

- **§2.3** — revise — ambiguity — Out-of-range `limit`/`offset` are clamped to the nearest bound (not rejected); non-integer values are `ERR_INVALID_REQUEST`; `meta` echoes the effective clamped values — `implementation/response.py:33-47`
- **§2.4** — revise — ambiguity — The supplied `to_iso8601` string is retained verbatim: echoed as `current_utc` and re-used as the logical-clock stamp for `received_at`/`substantiated_at`/`published_at`; re-setting the held instant is permitted (only strictly-earlier is a regression) — `implementation/routes_clock.py:38-48`, `implementation/state.py:33-36`, `implementation/routes_lots.py:43`
- **§2.5** — revise — ambiguity — `created_at`/`updated_at` are stamped from wall-clock UTC, not the logical clock — `implementation/state.py:48-64` (`now_iso_ms`)
- **§2.7 (report bullet)** — revise — mismatch — OCC trigger is exact-mismatch ("does not equal the run's current `version`"), not strictly "advanced past" — `implementation/routes_reports.py:32-36`
- **§2.7 (shift bullet)** — revise — mismatch — Same exact-mismatch semantics for `expected_allocation_version` — `implementation/routes_capacity.py:132-136`
- **§3.2** — revise — ambiguity — An `operation` path segment outside `STITCHING|LASTING|ASSEMBLY` is `ERR_INVALID_REQUEST` (400); `ERR_CERTIFICATION_NOT_FOUND` (404) is reserved for a declared operation the worker holds no entry for — `implementation/routes_workforce.py:96-108`
- **§3.3** — revise — mismatch — `quantity_remaining` is server-maintained bookkeeping (init = `quantity_received`, decremented at reservation, re-credited only on release / cancel-from-`MATERIAL_RESERVED` / suspension-reversion), replacing the derived-formula sentence, which under a literal reading would re-credit lots on a `QUALITY_HOLD` cancel — contradicting §3.5's "not re-credited" rule that impl follows — `implementation/routes_lots.py:41`, `implementation/calcs.py:93-107`, `implementation/routes_runs_lifecycle.py:194-203`
- **§3.5** — revise — ambiguity — The three `actual_*_minutes` fields must each be an integer ≥ 0, otherwise `ERR_INVALID_REQUEST` — `implementation/routes_runs_lifecycle.py:161-164`
- **§3.6 (creation)** — revise — ambiguity — Creating a `PROVISIONAL` report against a `CANCELLED` run is rejected with `ERR_INVALID_STATE` (HTTP 409); error code was previously unnamed — `implementation/routes_reports.py:29-30`
- **§3.6 (one-live rule)** — insert — ambiguity — Every successful report creation (direct or cascade-driven) increments the run's `version` by 1 and refreshes `updated_at` — `implementation/cascade.py:58` (`touch(run)` in `create_report_record`)
- **§3.7** — revise — ambiguity — A manual cancel of a `SCHEDULED` order retains its `production_run_id` (unlike the system-driven fallback, which clears it) — `implementation/routes_orders.py:164-173`
- **§5** — revise — mismatch — Catalogue scoped to declared endpoints; framework fallbacks `ERR_NOT_FOUND` (404) / `ERR_METHOD_NOT_ALLOWED` (405) / `ERR_INTERNAL` (500) named for unmatched routes/methods/crashes — `implementation/app.py:56-67`, `implementation/errors.py:82-87`

#### Known-candidate verdicts

(a) publish evidence re-check: PRD already pins the substantiation-time snapshot ("counted at substantiation") — impl `routes_claims.py:146-152` iterates `_evidence_ids`; no change. (b)–(g): all confirmed against impl and edited as above.

#### Impl areas scanned with no change needed

Full walk of all 13 blueprints plus core modules: factory create/suspend/reactivate + 2-hop cascade (`cascade_factory_suspend`), workforce hire/suspend/reinstate/cert-flip/enroll/record-assessment incl. upsert and pass-mark 80, skill-coverage dual-variant computation (100-when-idle, 0.5 pipeline credit, 0.5/0.3/0.2 blend), model/component creation + discontinue guards, BOM existence-before-schema ordering, FIFO allocation (BOM order, DOMESTIC_PREFERRED grouping, `received_at`+cost tie-break, atomic abort), reserve guard order (allocation-exists → state → line window → FIFO → pool, equality allowed), release/start/hold/resume ownership + re-qualification, completion cost tiers (25/15/8/0%, CUSTOM_BATCH +5%, GOVERNMENT exempt, single post-surcharge rounding), report calculation (per-line rounding, recompute overrides, zero-total → 0.00, `final_assembly_domestic`), event-driven model pricing refresh, custom-order pricing (fallback 15% markup, fees, pre-discount tier keying, per-pair rounding before quantity), schedule guard order per §2.8 families, claim lifecycle (substantiate check order, threshold table, re-substantiation clearing `published_at`, revoke state set, no PUBLISHED→REVOKED path), evidence upload/verify/reject incl. segregation guard before state check and lazy expiry, rejection cascade hops 1–3 (model-scoped claim re-point, threshold re-check, IN_FULFILLMENT-only audit push), capacity waterfall (GOVERNMENT→CUSTOM_BATCH→STOCK), shift source/floor checks, reconcile, contract closed-interval overlap, Berry 100.00 equality gate with pinned family-7 order, outcome-computing audit. `implementation/`, `test_suite/`, `test_helpers/` were not modified.

Orchestrator verification: `diff -q` confirms PRD_COMPLETED.md genuinely differs (not a silent no-op); 26 diff body lines at 11 hunks, 403→403 lines (in-paragraph edits as claimed); 0 post-sweep writes under implementation//test_suite//test_helpers/; all 8 `results.*.json` intact; spot-checked `results.3.json` — 117 genuine per-test entries (name/file/status/duration), outcome histogram {passed: 117}.
