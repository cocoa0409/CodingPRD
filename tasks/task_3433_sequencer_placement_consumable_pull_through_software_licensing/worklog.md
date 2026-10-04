# Worklog — task_3433_sequencer_placement_consumable_pull_through_software_licensing

## Step 1: Create task directory — 2026-10-02T02:10:00.000Z

Verified pre-allocated task directory `./tasks/task_3433_sequencer_placement_consumable_pull_through_software_licensing/` with `workspace/` inside exists (as instructed by the invocation; no new index computed, no other task_* directory created).

## Step 2: Generate scaffold — 2026-10-02T03:16:00.000Z

All checks pass. The scaffold is complete and verified.

## Final lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_3433_sequencer_placement_consumable_pull_through_software_licensing/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_3433_sequencer_placement_consumable_pull_through_software_licensing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_3433_sequencer_placement_consumable_pull_through_software_licensing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     13
  §1.8 instances scanned:     22
  §1.9 instances scanned:     58
  Calls scanned (§1.8+§1.9):  714

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

All three artifacts in `/home/ubuntu/github/CodingPRD/tasks/task_3433_sequencer_placement_consumable_pull_through_software_licensing/`, built purely from the scenario + skill spec (no sibling tasks read):

**SCAFFOLD.yaml** — beyond-Expert density: 13 entities (Account, InstrumentModel, ReagentKit, SoftwareUpdate, Instrument, PlacementProgram, ReagentLot, ReagentOrder, ServiceContract, SoftwareLicense, RunRecord, TransitionProgram, SupplyForecast), 9 state machines + 2 OCC concurrency rules (amendment create, forecast freeze), 10 calculations, 39 priority-ordered validations, 49 endpoints, 37 error codes, 6 roles (5 opaque + LabOperator entity-backed by Account). Logical clock endpoint with the mandated `2026-09-01T00:00:00Z` startup default drives expiry sweeps (lots/contracts/transition programs).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 22 instances across all 9 rules, every assert pre-computed as a literal: dual-variant calcs on 3 domains (trade-in 1,400,000→924,000c provisional/final; commitment accrual-vs-final with 1,200,000c penalty; forecast coverage optimistic 70 vs conservative 30); combinatorial modes (a) uptime tier+min/max cap clamp (50,000 then 70,000c), (b) pinned per-line-then-sum rounding (48c not 47c), (c) billing evaluation order samples→tier→gross→expiry→offset→net (net 193,000c); 3 cyclic machines on different entities; depth-3 and depth-4 cascades; state-vs-fiscal and safety-vs-constraint priority pairs; exact-boundary checks (uptime 99.90 → 0 credit; 1000 samples → T2); 3 cross-entity state gates; half-open-adjacency vs aggregate-weekly-capacity overlap semantics; deliver/return and reserve/cancel compensating invariants.

**SCAFFOLD_CORNER_DESIGN.yaml** — 58 active instances across all 9 taxonomy sections plus 22 `excluded_because` stubs that reference §1.8 instances (all verified resolvable).

## Key design decisions worth knowing downstream

- **Endpoint consolidation** kept the surface at 49 despite 13 entities: multi-action endpoints (`events`, `advance`, `review`, `amendments`, `status`) with per-action role gates declared in validation priority 3.
- **Version pinning**: placement programs snapshot kit prices at approval; licenses snapshot sample rates at activation — both probed by tests.
- **Segregation of duties**: program approve, amendment approve, and transition appraise all reject when the approver's X-User-ID equals the recorded creator's.
- Two YAML traps were caught and fixed mid-generation: trailing-`?` optionals in flow-style `input:` lists (PyYAML rejects; quoted) and bracketed grounds refs (`errors[ERR_X]`) inside flow sequences (converted to quoted block style). Every appended chunk was re-parsed immediately.
- Final audit confirmed: all grounds refs resolve, all 102 instance names unique across both files, all 37 errors have at least one triggering recipe, all enum values have a producing transition, no forbidden concurrency vocabulary, and every state in every machine is reachable from empty-DB via §1.5 endpoints alone.

## Step 3: Copy shared files — 2026-10-02T03:20:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-10-02T03:30:00.000Z

All verification passes are clean. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_3433_sequencer_placement_consumable_pull_through_software_licensing/workspace/PRD.md` (321 lines).

## What was generated

A prose PRD for the **sequencer-placement** domain (`/genomics` prefix), structured as:

- **§1 Introduction** — 2 paragraphs from the placement/pull-through/licensing business angle (avoids the "This document outlines…" anti-pattern).
- **§2 Global Specifications** — 10 subsections: RBAC with per-role `identity:` translations (five opaque vendor roles; `LabOperator` entity-backed by Account with ownership/auto-scoping rules), the §2.2 envelope block **emitted byte-verbatim** (verified programmatically), pagination (limit 10/1/100, offset 0, `created_at` ascending), the logical clock (startup default 2026-09-01T00:00:00Z, monotonic, four expiry sweeps), common resource properties (with the RunRecord `common_fields: false` exception — only `id` + `created_at`), RUO/CLINICAL regulatory duality, precision/rounding, OCC for exactly the two scaffold-nominated endpoints, the 8-tier validation ordering, and cascade/mutation semantics.
- **§3 Business Logic** — 9 subsections organized by business process (catalog → installed base → placement programs → lots/QC → orders/FEFO → service contracts → licensing/run records → trade-ins → forecasts). All 10 calculations are rendered as precise prose with constants embedded (capacity bases 50/120/300 × 1.0/1.5/2.2; per-line-then-sum subsidy rounding with the 40% cap; FEFO with `expiry_date`/`created_at` tie-break "never by identifier"; uptime tiers with the exact-threshold-pays-nothing and deficit-1.0-takes-10% rules; pinned six-step billing order with expiry-before-offset; trade-in provisional/final with floor clamp; accrual vs final reconciliation; optimistic vs conservative coverage; 500/1000 weekly cold-chain buckets with equality allowed). All state machines, cascades (decommission, QC-failure, expiry sweep, freeze-supersede, auto-complete), segregation-of-duties sites, and both OCC rules are expressed.
- **§4 Endpoint table** — all 49 endpoints, 4 columns only.
- **§5 Error catalogue** — all 37 errors, 2 columns only; document ends there (no audit footer).

The two forbidden design index files were never opened.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoints input/query/path params: 162 required, 162 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] priority: global 8-tier ladder in §2.9 plus explicit per-endpoint orderings for order-SUBMIT (§3.5) and run-record gates (§3.7)
- concurrency_rules[] OCC: 2 checked, 2 expressed (write op + expected_*_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all expressed incl. self-transitions and system cascades, 0 missing
- calculations[]: 10 checked, 10 expressed with constants, 0 missing
- validations[] conditions: all 39 priorities matchable to error_ids in §2/§3 (all 37 error IDs verified present programmatically)
- endpoints[].side_effects / applies_to: expressed; multi-endpoint scopes (ERR_LICENSE_NOT_ACTIVE ×3, ERR_LOT_EXPIRED ×2, ERR_COLD_CHAIN_BREACHED ×2, horizon check ×2, SoD ×3) enumerated
- entities[].fields[] structured content (defaults/initials/computed): reconstructible from prose
- sibling-branch symmetry: QC outcomes, cancel states, coverage variants, reconciliation variants, trade-in variants all at equal density
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 605
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional mechanical checks: no fuzzy/approximating words, no pseudocode operator leaks (`==`, `>=`, `+=`, etc.), §4 rows match scaffold paths exactly (40 unique paths / 49 endpoints), §5 rows match the error catalog exactly, all enum/state values present as exact UPPERCASE strings.

One caveat to flag honestly: the scaffold's error catalog describes `ERR_INSTRUMENT_NOT_OPERATIONAL` and `ERR_COLD_CHAIN_BREACHED` as applying to software-update application and run-record creation respectively, but the `validations[].applies_to` rows only bind the former to run-records and the latter to order-SHIP. I rendered both per the catalog's broader wording (noting the expectation for software updates in §3.2 and the cold-chain gate for run records in §3.7) so the PRD covers both readings — test generation should be aware the scaffold is mildly ambiguous here.

## Step 5a: Generate test_helpers/ (stage 1 of 2) — 2026-10-02T03:50:00.000Z

Stage 5a is complete. All verification passed.

## Files written (under `/home/ubuntu/github/CodingPRD/tasks/task_3433_sequencer_placement_consumable_pull_through_software_licensing/test_helpers/`)

| File | Lines | Content |
|---|---|---|
| `constants.py` | 113 | All PRD-pinned calculation constants (capacity tables, subsidy cap 0.40, uptime tiers 1.0/3.0 at 5/10/25%, sample tiers 1000/5000 at 250/200/150c, credit value 100/expiry 365d, cloud costs 0/10/25, trade-in 20/35/50% + deductions + floor, penalty 10%, cold-chain capacity 500/1000, horizon 26wk, default clock 2026-09-01T00:00:00Z) + `TEST_DEFAULTS` |
| `types.py` | 571 | 28 enums (all state machines, actions, field enums, `UserRole`) + 13 entity TypedDicts (RunRecord correctly omits `updated_at`/`version` per PRD §2.5) + 3 result-payload TypedDicts |
| `api_errors.py` | 90 | `ApiErrorId` (37 IDs) + `HTTP_STATUS_CODES` + framework `set_error_http_status_map` registration at import |
| `test_users.py` | 68 | `TEST_USERS` (6 shared headers), `NO_AUTH_HEADERS`, and `make_*_headers(user_id)` builders for all 6 roles (mandatory `make_lab_operator_headers(account_id)` for the entity-backed role; distinct ids for SoD flows) |
| `factories.py` | 312 | 14 entity payload factories (counter-unique codes/serials/lot numbers/update versions) + 3 line builders + 10 action-payload builders (review, amendment w/ OCC field, order advance, QC, license status, transition advance, forecast advance, reconciliation, clock) |
| `api_client.py` | 239 | `ApiClient(GenericApiClient)` with one method per endpoint — verified all 49 PRD endpoints present + `api_client` singleton |
| `assertions.py` | 423 | 13 `assert_<entity>()` + 3 result assertions + 4 invariant checkers (`assert_kit_capacity` Decimal-based half-up check, `assert_lot_invariants`, `assert_license_invariants` ledger-sum, `assert_program_invariants` with divisibility guard) |
| `fixtures.py` | 813 | 49 composite setup helpers (see below) |
| `__init__.py` | 47 | Barrel: framework generics + all PRD-specific modules |

## Verification results
- `python3 -m py_compile` on all 9 files: **OK**
- `import test_helpers`: **OK** — 215 exported names, zero missing from `fixtures.__all__`, zero missing endpoint methods.

## Public inventory Stage 2 can rely on

**Client**: `api_client.<method>` for all 49 endpoints (e.g. `create_account`, `post_instrument_event`, `review_placement_program`, `post_placement_amendment`, `close_placement_period`, `post_lot_qc`, `advance_reagent_order`, `activate_service_contract`, `post_uptime_reconciliation`, `set_license_status`, `post_credit_grant`, `close_billing_period`, `create_run_record`, `advance_transition_program`, `advance_supply_forecast`, `set_clock`, plus all GET/list with `params=`).

**Fixtures (49)**: `advance_clock`; creators (`create_account/model/kit/software_update/instrument/lot/lots/program/contract/license/forecast/order`); state walkers (`drive_instrument_to`, `commission_instrument`, `create_operational_instrument`, `create_decommissioned_instrument`, `pass_lot_qc`, `create_passed_lot`, `submit_program`, `approve_program`, `create_submitted_program`, `create_active_program`, `close_program_periods`, `activate_contract`, `create_active_contract`, `record_service_window`, `activate_license`, `create_active_license`, `grant_credits`, `submit_forecast`, `create_submitted_forecast`, `freeze_forecast`, `create_frozen_forecast`, `submit_order`, `ship_order`, `deliver_order`, `create_allocated_order`, `create_shipped_order`, `create_delivered_order`, `record_run`, `create_enrolled_transition` (returns `{account, old_model, new_model, old_instrument, transition}`, supports `commission=True`/`old_installed_at`), `appraise_transition`); composite scenarios: `setup_run_ready` (returns `{account, model, kit, instrument, lot, license}`; supports `regulatory_class`, `model_overrides`/`kit_overrides`/`lot_overrides`/`instrument_overrides`, `pass_qc=False`, `grant_credits_amount`/`granted_on`, `activate=False`), `setup_active_contract_scenario`, `setup_update_gate_scenario`, `setup_breached_account` (12 closes → BREACHED + `credit_hold` asserted), `setup_program_order_pipeline` (`advance_to=ALLOCATED|SHIPPED|DELIVERED`), `setup_backordered_order` (QC_FAILED cascade → BACKORDERED asserted).

**Coverage of all 80 non-stub instances**: every `setup_api_calls` chain in both design indices decomposes into the above (breach-driven credit-hold, amendment cycles, uptime tier/cap, FEFO/tie-break/all-or-nothing, pinned pricing, billing order/tier/provisional divergence, cascades, sweeps, OCC 412s, RBAC/SoD, regulatory gates, capacity boundary) — no instance needs setup beyond these helpers plus direct `api_client` calls for negative-path triggers.

## Step 5b: Generate test_suite/ (stage 2 of 2) — 2026-10-02T04:40:00.000Z

Stage 5b complete. The test suite for task_3433 is fully generated under `/home/ubuntu/github/CodingPRD/tasks/task_3433_sequencer_placement_consumable_pull_through_software_licensing/test_suite/`, with test_helpers/ untouched (frozen).

## Files written (13 files, 3,232 lines)

| File | Lines | Contents |
|---|---|---|
| `conftest.py` | 47 | Session-scoped `api` fixture + one header fixture per role |
| `test_01_platform_envelope_rbac.py` | 256 | envelopes, pagination, version/updated_at, read-after-write, 404, clock monotonicity, RBAC tiers (11 tests) |
| `test_02_catalog_and_registration.py` | 202 | account defaults, required fields, kit capacity, serial uniqueness, initial state, obsolete/regulatory gates, run-record immutability (8) |
| `test_03_instrument_lifecycle.py` | 160 | invalid INSTALL, DECOMMISSIONED lockdown, service-cycle ×2 (4) |
| `test_04_software_update_gates.py` | 253 | contract gate ×2, safety-beats-constraint ×2, withdrawn, model-incompatible, run-mode unlock (7) |
| `test_05_placement_program_terms.py` | 359 | subsidy rounding ×2, amendment cycle ×2, accrual/final reconciliation ×2, cap, auto-complete, SoD ×2, OCC amendment (11) |
| `test_06_order_allocation_fulfillment.py` | 295 | FEFO, created_at tie-break, all-or-nothing, double-submit, cold-chain ship gate, expiry sweep, re-allocation sweep, reserve/cancel ×2 (9) |
| `test_07_program_spend_attribution.py` | 325 | lot-QC cascade ×2, deliver/return ×2, program-state gate ×2, state-beats-fiscal ×2, pinned prices, credit hold (10) |
| `test_08_service_contract_uptime.py` | 306 | tier/cap ×2, exact-threshold ×2, half-open adjacency ×2, window-invalid, reconciliation overlap, contract expiry sweep (9) |
| `test_09_license_billing_credits.py` | 239 | billing order ×2, tier boundary ×2, suspend/resume ×2, provisional divergence, credit flat costs (8) |
| `test_10_run_record_gates.py` | 295 | license gate ×2, FAILED-run asymmetry, and all 9 single-gate rejections (12) |
| `test_11_transition_tradein.py` | 247 | provisional-vs-final ×2, completion cascade ×2, enrollment window, enrollment expiry sweep (6) |
| `test_12_supply_forecasts.py` | 248 | coverage variants ×2, capacity aggregate ×2, horizon, OCC freeze, freeze supersede (7) |

## AST tag audit (real `ast.walk` over every test function)

- 102 test functions, 169 PRD citation lines — every quoted sentence verified as a whitespace-collapsed verbatim substring of `workspace/PRD.md`.
- Queue A (Difficulty): 22/22 instances emitted, each with exactly 2 tests (44 tests). 0 skipped.
- Queue B (Corner): 58/58 non-stub instances emitted, each with ≥1 test (58 tests). 0 skipped. All 22 `excluded_because` stubs left untranslated; every stub's `difficulty_instance` cross-reference resolves.
- Every test has exactly one `Design:` tag as the last docstring line; every tag resolves to its yaml instance. One tag initially mis-sectioned (`kit_min_generation_rejected` is under corner section `errors`, not `validations`) — caught by the audit and fixed.
- No `skip`/`xfail` anywhere; no instances dropped by the PRD-first filter (every instance's asserted rule is verbatim-covered by PRD prose — the citation audit proves it).

## Notable derivability decisions

- `allocation_tie_break_created_at`: the recipe's two lots share the default clock, which would tie `created_at` under a logical-clock reading; I advance the clock one minute between lot registrations so the earlier-created-wins claim is deterministic under both clock readings (noted in the docstring).
- Timestamp assertions (service windows, patch `updated_at`, lot `expiry_date`) compare parsed instants, not exact strings — PRD pins the instant, not the fractional-digit formatting.
- `test_08` opens the first service window at the default clock instant without a clock advance (an advance to `00:00` would itself be `ERR_CLOCK_REGRESSION`).
- `state_beats_fiscal` second test references the BREACHED program itself (not just PENDING_APPROVAL program B) — a second arrangement of the same priority pair.

## Verification results

- `python3 -m py_compile` on all 13 files: OK.
- AST unused-import scan: clean.
- `PYTHONPATH=<task_root> python3 -m pytest --collect-only -q test_suite`: **102 tests collected in 0.27s**, no errors.

Orchestrator re-verification: `python3 -m py_compile test_suite/*.py` OK; `pytest --collect-only` collected 102 tests.

## Step 6: Generate implementation — 2026-10-02T05:15:00.000Z

Implementation complete. Report follows.

## What was built

A complete Python + Flask implementation of the Sequencer Placement / Consumable Pull-Through / Software Licensing API in `/home/ubuntu/github/CodingPRD/tasks/task_3433_sequencer_placement_consumable_pull_through_software_licensing/workspace/implementation/`, structured as per-domain route modules over a shared store/validation/calculation layer.

## File inventory (23 files, 3,242 lines)

- Launcher/deps: `start.sh` (10, guarded `pip install` + `exec python3 app.py`, `$PORT`/0.0.0.0), `requirements.txt` (1)
- Foundation: `store.py` (66, empty-boot store + logical clock defaulting to 2026-09-01T00:00:00Z), `timeutil.py` (56), `errors.py` (29), `envelope.py` (93, exact `meta`/`response_type`/`data` envelope + `limit`/`offset`/`total_count`/`has_more` pagination), `auth.py` (51, X-User-ID/X-User-Role + 6 roles + per-action gates + LabOperator entity-backed ownership), `validate.py` (163)
- Calculations: `calc.py` (336 — all 10 calc rules with Decimal/ROUND_HALF_UP: kit capacity, subsidy pool per-line-round-then-sum, FEFO allocation, uptime credits with 0.05/0.10/0.25 deficit tiers, sample tiers, credit ledger, trade-in provisional/final with floor clamp, commitment reconciliation, forecast variance, cold-chain capacity)
- Cascades: `cascades.py` (161 — lot QC-fail/expiry release-and-backorder, re-allocation sweep in created_at ASC, decommission cascade with final uptime credits, clock sweeps)
- Serializers: `serializers.py` (271 — computed fields derived at read: `credit_hold`, `committed_total_cents`, `available_units`, `credits_balance`; RunRecord ships without `updated_at`/`version` per PRD 2.5)
- Routes: `routes_accounts.py` (45), `routes_catalog.py` (135), `routes_instruments.py` (205), `routes_programs.py` (253), `routes_lots.py` (100), `routes_orders.py` (258), `routes_contracts.py` (164), `routes_licenses.py` (260), `routes_runs.py` (180), `routes_transitions.py` (157), `routes_forecasts.py` (142), `routes_clock.py` (37)
- `app.py` (69 — blueprint registration, ApiError/HTTPException/catch-all handlers all answering in the error envelope)

## Verification

- **py_compile**: all 21 .py files compile — no truncation.
- **Endpoint count**: 49/49 PRD §4 endpoints registered (verified by grepping route decorators against the PRD table).
- **Smoke test** (dynamic port 53205, server killed afterward by exact PIDs — port confirmed released): 28/28 checks passed, covering 401/403 auth layers, account create + LabOperator ownership, catalog create with `capacity_gb` 264.0 (FC_MID × V3), instrument lifecycle SHIP→INSTALL→COMMISSION with `installed_at` stamped from the logical clock, state-gate 409 and per-action-role 403, lot QC + FEFO order SUBMIT (total 10000, reservations written, `reserved_units` 2 / `available_units` 3), clock regression 422 + advance 200 with sweep counts, subsidy cap 422, per-line-rounded pool 30000, segregation-of-duties 409, approval price-pinning `{"K1": 5000}`, and list pagination meta.

## Key interpretation decisions (PRD wins on conflict)

- **RunRecord gate order** follows PRD §3.7's explicit enumeration (cold-chain and expiry *before* clinical clearance), overriding the scaffold's priority numbers 18<19<20.
- **Withdrawn software updates keep their unlocked run modes** (PRD §3.1 "no retroactive lock" over the entity field's RELEASED-only union): `unlocked_run_modes` is persisted and recomputed over all applied updates.
- **OCC fields** (`expected_program_version`, `expected_forecast_version`) are checked only when provided, per the endpoint table's `?` markers and the skill's OCC rule.
- **Uniqueness without a catalog error** (model_code, kit_code, update_version) returns 409 with `ERR_INVALID_REQUEST`; only `serial_number` has its own catalog'd error.
- **Blanket version bump**: every mutation (user or cascade) increments `version` and refreshes `updated_at` per PRD §2.5, including system-driven changes to lots, programs, contracts, and accounts.

Orchestrator re-verification: `python3 -m py_compile *.py` OK for all impl files; 49 route decorators counted.

## Step 7: Test-fix iteration loop — 2026-10-02T05:30:00.000Z

Clean 8-round sweep achieved: 102/102 passed in every round. Exiting with the required summary.

## Summary

- **Iterations run**: 2 sweeps (16 total rounds). First sweep: 94/102 in all 8 rounds (stable, non-flaky failure set of 8 unique tests). Second sweep after one fix: 102/102 in all 8 rounds.

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `implementation/`**: one fix.
  - `/home/ubuntu/github/CodingPRD/tasks/task_3433_sequencer_placement_consumable_pull_through_software_licensing/workspace/implementation/routes_forecasts.py` — added the missing `from auth import require_roles` import. The module called `require_roles(...)` in all 5 forecast route handlers but never imported it, so every forecast endpoint raised `NameError` → HTTP 500 `ERR_INTERNAL`. This single defect explained the entire failure union: all 7 test_12_supply_forecasts failures (setup or direct calls hit forecast endpoints) plus test_09's `test_provisional_and_final_disagree_on_same_period` (its setup calls `create_submitted_forecast`).

- **Diagnostic path**: STEP 0 showed all failures were `ERR_INTERNAL` 500s from forecast endpoints — a crash signature, not a rule dispute. STEP 1/2 were moot (tests are PRD-faithful; forecast endpoints are PRD §3.9). STEP 3: implementation bug, fixed at the source. pyflakes confirmed no other undefined names anywhere in the implementation (only two harmless unused imports), so no sibling files had the same defect class.

- **Deliverables**: `results.1.json` … `results.8.json` from the final clean sweep remain on disk in `workspace/implementation/`.

Orchestrator re-verification: all 8 `results.{i}.json` show 102/102 passed, 0 failed; `from auth import require_roles` present at `routes_forecasts.py:6`.

## Step 8: Finalize PRD — 2026-10-02T05:22:00.000Z

Evidence gathering is complete. The workspace contains no `test_suite/`/`test_helpers/` directories (only INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, implementation/), so test-side reads were not possible — the step_7_diff diagnostic plus the implementation and PRD reads are the evidence base, which is sufficient here since the fix is implementation-only.

## Summary

**Outcome: ZERO EDITS — PRD_FINALIZED.md is a byte-identical copy of PRD.md** (verified with `diff -q`: BYTE-IDENTICAL).

**Line counts:** PRD.md 321 lines, PRD_FINALIZED.md 321 lines, 0% delta.

### Step 7 diff item analysis

The single Step 7 item was an `implementation/` fix: `workspace/implementation/routes_forecasts.py` gained the missing `from auth import require_roles` import (now at line 6). The module calls `require_roles(...)` in all 5 forecast route handlers (lines 62, 81, 91, 106), so every forecast endpoint raised `NameError` → HTTP 500 `ERR_INTERNAL` before the fix. This explained all 8 unique failing tests (7 in test_12_supply_forecasts, plus test_09's `test_provisional_and_final_disagree_on_same_period`, whose period-close flow creates/submits forecasts as setup).

**Why no PRD edit is warranted — evidence:**

1. **Pure crash fix, no behavioral choice made.** Adding an import changed no logic. The behavior the fix enabled was already written in the code and is fully pinned by the PRD:
   - Roles per endpoint — PRD endpoint table (lines 273–276) pins exactly the role sets the impl enforces: create/list/advance → `SupplyPlanner`; read → `SupplyPlanner, AccountManager`. Verified line-by-line against impl lines 62, 81, 91, 106.
   - Forecast workflow — PRD §3.9 (lines 215–221) pins DRAFT/SUBMITTED/FROZEN/SUPERSEDED transitions, the Monday/26-week horizon rule enforced at creation and again at submission, the 500/1,000-unit weekly cold-chain capacity buckets, FREEZE supersession of the account's prior FROZEN forecast, and the `include_variance` variance view — all matching the impl.
   - Optimistic concurrency — PRD §2.8 (line 107) pins `expected_forecast_version` on freeze with `ERR_STALE_VERSION` (412), matching impl lines 124–132.
2. **`require_roles` is defined** at `implementation/auth.py:22`; pyflakes on the fixed file is clean (no other undefined names), corroborating the step_7_diff claim.
3. **No PRD silence revealed.** There is no underspecified choice the implementer had to invent — the crash masked already-PRD-conformant code.

### Per-edit pre-edit search log

No edits were committed, so the no-new-mismatch enumeration was vacuous; for the one candidate subject (forecast endpoint role gating), the enumerated impl paths were routes_forecasts.py lines 60–143 (all 5 handlers) cross-checked against PRD lines 273–276 and §3.9 — all consistent, and since the crash fix introduced no behavior, no wording change was needed anywhere.

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_3433_sequencer_placement_consumable_pull_through_software_licensing/workspace/PRD_FINALIZED.md` (byte-identical copy of PRD.md). Nothing under `implementation/`, `test_suite/`, or `test_helpers/` was touched; no tests were run and no servers were started.

Orchestrator re-verification: `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` → BYTE-IDENTICAL; 0 implementation .py files newer than PRD_FINALIZED.md.

## Step 9: Complete PRD scan — 2026-10-02T05:33:00.000Z

The diff is exactly the intended patch set — nothing else moved. Task complete.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (321 lines, 57,083 chars) → `PRD_COMPLETED.md` (324 lines, 59,982 chars; +2,899 chars, 24 logical changes). Only `PRD_COMPLETED.md` was created/edited; implementation, tests, and helpers untouched. Sweep evidence: `implementation/results.8.json` shows 102/102 passing.

**Counts:** 23 ambiguity-pins, 1 mismatch-revision.

**Changes (section — insert/revise — class — what — impl evidence):**
- §2.2 — revise — ambiguity — `api_request_id` pinned as `req_` + 20 random alphanumerics — envelope.py:21-22
- §2.2 — revise — ambiguity — `api_request_timestamp` pinned as server UTC wall clock, not the logical clock — envelope.py:28
- §2.2 — insert — ambiguity — unmapped routes → `ERR_NOT_FOUND` (404), wrong method → `ERR_INVALID_REQUEST` at 405, unexpected failure → `ERR_INTERNAL` (500) — app.py:48-65
- §2.3 — revise — ambiguity — `limit`/`offset` out-of-range values clamp (1..100 / ≥0); non-integer → `ERR_INVALID_REQUEST` — envelope.py:41-59
- §2.9 — insert — ambiguity — run-record ownership resolves `instrument_id` as part of the check, so an unresolvable id gives 404 despite tier-4-before-6 ordering — routes_runs.py:24-30
- §3.1 — insert ×3 — ambiguity — duplicate `model_code`/`kit_code`/`update_version` → `ERR_INVALID_REQUEST` at **HTTP 409** (id reused at non-400 status) — routes_catalog.py:20-21, 36-37, 66-67, 110-111
- §3.2 — revise — ambiguity — update-application gates evaluate in pinned order: contract ACTIVE → instrument OPERATIONAL → update RELEASED → clinical validation → model generation — routes_instruments.py:163-192
- §3.2 — revise — **mismatch** — `unlocked_run_modes` recompute unions `unlocks_run_modes` of every applied update **regardless of later withdrawal**; dropped the "still in `RELEASED` state" phrase, which contradicted §3.1's "no retroactive lock" — routes_instruments.py:195-203 (no `release_state` filter in the recompute loop)
- §3.3 — insert — ambiguity — amendment CREATE requires at least one of the two `new_*` fields, else 400 — routes_programs.py:180-185
- §3.3 — insert — ambiguity — the 40% subsidy cap is not re-evaluated at amendment approval — routes_programs.py:218-220
- §3.3 — insert — ambiguity — a return after auto-completion does not re-open a `COMPLETED` program — routes_orders.py:220-233
- §3.5 — revise — ambiguity — FEFO tie-break chain: `expiry_date`, then `created_at`, then lot registration order — calc.py:102
- §3.5 — revise — ambiguity — line whose `kit_code` is absent from `pinned_kit_prices` prices at current catalog price; DRAFT orders carry `total_cents`/`attributed_total_cents` as null — routes_orders.py:142-146, 77-78
- §3.5 — insert — ambiguity — cancelling a `BACKORDERED` order releases nothing and adjusts no pipeline — routes_orders.py:203-217
- §3.6 — revise — ambiguity — `downtime_minutes` is summed downtime rounded half up to whole minutes — calc.py:171
- §3.7 — revise — ambiguity — grant `credits` must be a positive integer ≥1; a datetime `granted_on` is truncated to its date — routes_licenses.py:140-149
- §3.7 — revise — ambiguity — grant-consumption attribution for expiry is FIFO by ledger order; `EXPIRY` carries the grant's unconsumed remainder — routes_licenses.py:34-58, 189-211
- §3.8 — revise — ambiguity — years-in-service counts whole 365-day blocks (floor of elapsed seconds / 31,536,000); null `installed_at` = zero years — calc.py:207-210
- §3.9 — revise — ambiguity — horizon boundary inclusive: `week_start` exactly 26 weeks out is still valid — calc.py:256
- §3.9 — revise — ambiguity — `include_variance` truthy values: `true`/`1`/`yes` case-insensitive — envelope.py:84-88, routes_forecasts.py:85
- §5 — revise — ambiguity — catalogue notes the `ERR_INVALID_REQUEST`-at-409 exception for §3.1 uniqueness; added `ERR_INTERNAL | 500` row — routes_catalog.py:21, app.py:64

**Impl-omitted PRD claims (NOT revised):**
1. §2.8/§3.3 — *"Creating an amendment against a placement program requires the request to carry `expected_program_version`"* — impl treats the token as optional: `f_int(body, "expected_program_version", required=False)` and the stale check fires only `if expected_version is not None` (routes_programs.py:179, 188-193). A token-less amendment CREATE succeeds against an ACTIVE program. PRD prose kept as-is.
2. §2.8/§3.9 — *"Freezing a supply forecast likewise requires `expected_forecast_version`"* — same pattern: `f_int(body, "expected_forecast_version", required=False)` with the check guarded by `if expected_version is not None` (routes_forecasts.py:124, 127-132). A token-less FREEZE succeeds from SUBMITTED. PRD prose kept as-is.

Both omissions are consistent with the memory note that a green sweep proves tests match code, not PRD vs code — the tests always send the OCC token, so the missing required-field checks are unasserted paths flagged here for a later step rather than papered over in the contract.

## Post-Step-9: OCC required-field fix + re-sweep (orchestrator) — 2026-10-02T05:40:00.000Z

Step 9's two flagged impl omissions were adjudicated as **impl bugs, not PRD overclaims**: the PRD states "requires" in three places (§2.8, §3.3, §3.9), the PRD §4 endpoint table carries no optional marker, and the scaffold endpoint descriptions themselves say "OCC expected_program_version required" / "OCC expected_forecast_version required" (only the scaffold §1.5 `input:` flow-lists carried a stray `?`). Fixing the impl preserves contract intent rather than stripping it.

- Fixes (orchestrator-applied, 1 line each):
  - `workspace/implementation/routes_programs.py` — `f_int(body, "expected_program_version", required=True)` on amendment CREATE (missing token → `ERR_INVALID_REQUEST` 400 in the shape phase, before the ACTIVE state gate).
  - `workspace/implementation/routes_forecasts.py` — `f_int(body, "expected_forecast_version", required=True)` on forecast FREEZE (same 400-before-409 ordering).
- Pre-fix test-safety audit: all 6 amendment-CREATE call sites and all FREEZE call sites in test_suite/test_helpers pass the token; APPROVE/REJECT/SUBMIT paths (correctly token-less) are untouched.
- PRD_COMPLETED.md needed no further edit — its prose already states the required-token rule the impl now honors.
- **Re-sweep (post-fix, orchestrator-run)**: full 8-round parallel `prd-bench-local-run --isolation per-test-server` sweep re-executed; all 8 rounds 102/102 passed, 0 failed. Fresh `results.1.json` … `results.8.json` written to `workspace/implementation/` against the fixed code.
