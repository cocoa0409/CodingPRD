# Worklog — task_3232_licensed_merchandise_hot_market_production_event_fulfillment

## Step 1: Create task directory — 2026-09-30T12:29:00.000Z

Used the pre-allocated task directory `./tasks/task_3232_licensed_merchandise_hot_market_production_event_fulfillment` (index 3232, label `licensed_merchandise_hot_market_production_event_fulfillment`); did NOT compute a new index. Verified it exists and contains an empty `workspace/` subdirectory. No files created in this step.

## Step 2: Generate scaffold — 2026-09-30T13:16:00.000Z

Subagent returned verbatim:

All three files are written, parse cleanly, and pass `scaffold_lint.py`. Note on scope: I did not read any sibling `task_*` directory — only the skill's own files (`SKILL.md`, `scaffold_lint.py`, `references/claim-extraction-guide.md`, `examples/seed-tables-template.yaml`, `examples/example-maquee-ticketing-v1.yaml`) and the existing `worklog.md` in this new task dir.

## Output files

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_3232_licensed_merchandise_hot_market_production_event_fulfillment/SCAFFOLD.yaml` | 2249 |
| `/home/ubuntu/github/CodingPRD/tasks/task_3232_licensed_merchandise_hot_market_production_event_fulfillment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 976 |
| `/home/ubuntu/github/CodingPRD/tasks/task_3232_licensed_merchandise_hot_market_production_event_fulfillment/SCAFFOLD_CORNER_DESIGN.yaml` | 2054 |

## Entities (11) — `flat` topology, primary archetype `workflow_orchestration` + `temporal_windowing`

Licensor, Design, ProductionOrder, PrintLayer, PrintCapacity, PrintReservation, FulfillmentOrder, Shipment, RoyaltyAccrual, MinimumGuaranteeSettlement, CounterfeitReport. Complexity layers: cascading_side_effects, dual_variant_calculation, optimistic_concurrency, rate_threshold_triggers. Role model: segregation_of_duties. Consistency: immediate.

## State machines (7)

Design (cycle: pending→rejected→pending→approved) · ProductionOrder (fork/join parallel-hold pair, plus a PRINTING→COMMITTED reopen cycle) · PrintLayer (branching × self-loops) · FulfillmentOrder (PLANNED forks to PICKED/DISTRESSED/RETURNED, rejoin on full ship) · PrintReservation (accumulator with reclaim rail) · MinimumGuaranteeSettlement (linear + compensating reversal) · CounterfeitReport (branching confirm/clear + self-loop).

## Endpoint count: 39 (cap ≤40 respected)

38 business endpoints + 1 test-driving (`POST /_clock/set_current_utc`, startup default `2026-09-01T00:00:00Z`). 7 calculations, all carrying 2 variants; 32 validations (priority-ordered); 30 error codes (all referenced); 2 OCC concurrency rules on `ProductionOrder.version` and `Licensor.version`.

## Design-file instance counts

- §1.8: **18 instances** = 9 rules × 2 (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).
- §1.9: **56 instances across 12 sections** — 45 active corners + 11 `excluded_because:` stubs citing §1.8 instance names.

## What I did beyond drafting

Beyond structure, I replayed every design-file chain against §1.2/§1.4/§1.5/§1.6 and fixed the defects that came out of it, then executed every formula in Python to pin literal expected values (e.g. hot-market provisional 375 vs superseding 275; per-row royalty 168.76 vs sum-first 168.75; rush points 95; counterfeit exposure 13920/34800/48720; settlement triple 843.75/0/843.75 with shortfall 1256.25). Also fixed: an endpoint-count banner that disagreed with the table, a `PrintReservation.RELEASED` state no endpoint could reach, an unrelated-domain calculation body that had leaked into §1.3, missing declared output fields the design files captured (`layer_ids`, `capacity_commitment_units`, `rush_delivery_points`, `write_down_inventory_cents`, `destroyed_units`, `licensor_version`), a settlement whose reserve path was unsatisfiable as written, several OCC chains that reused a stale version variable or reused one version across two mutations, and list captures written as `$.data.total_count` against `[]`-returning endpoints.

Final lint: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (483 calls scanned, 0 violations).

**Orchestrator verification.** Note: the subagent's first attempt stalled before writing any file (returned mid-turn with an empty task dir); it was resumed and completed on the second pass. Verified on disk: all three YAML files exist and `yaml.safe_load` succeeds on each. Top-level keys of SCAFFOLD.yaml are `scenario, domain_name, api_prefix, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, response_envelope, endpoints, errors, roles`; the two design files carry exactly their single mandated top-level key. Counts confirmed: 11 entities, 39 endpoints, 32 validations, 30 errors. Removed one cosmetic duplicate `validations:` key (adjacent lines 1358/1359); duplicate YAML mapping keys are last-wins, so the parsed content was already correct and this edit changed no semantics — re-parsed cleanly afterward.

## Step 3: Copy shared files — 2026-09-30T13:17:00.000Z

Copied `./INSTRUCTION.md` (1424 bytes) to `./tasks/task_3232_licensed_merchandise_hot_market_production_event_fulfillment/workspace/INSTRUCTION.md`. Verified present on disk.

## Step 4: Generate PRD — 2026-09-30T13:26:00.000Z

Subagent returned verbatim:

PRD.md is complete and passes all three hard contracts mechanically.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3232_licensed_merchandise_hot_market_production_event_fulfillment/workspace/PRD.md` — 412 lines, ~95 KB, ends at §5 with no audit footer.

**Section list**

- §1 Introduction (3 paragraphs; opening angle is the hot-market time pressure, not "This document outlines")
- §2 Global Specifications: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Rights-Holder Ledgers and the Guarantee Recovery Rail · 2.5 Common Resource Properties and Mutation Semantics · 2.6 The Logical Clock, Event Windows and Terminal Lockdown · 2.7 Monetary Precision and Rounding Discipline · 2.8 Optimistic Concurrency Control · 2.9 Capacity Windows and the Reservation Ordering Rule · 2.10 Validation Precedence · 2.11 Nested Resource Retrieval
- §3 Business Logic: 3.1 Licence Clearance: Authoring, Rejection, Resubmission and Revocation · 3.2 The Parallel-Hold Pair and Hot-Market Capacity Commitment · 3.3 Authoring Layers and Committing the Winning Outcome · 3.4 Press Operations, Print Failures and the Reopen Rail · 3.5 The Shared Inventory Pool: Placing Demand and Picking It · 3.6 Shipping, Delivery and the Rush Commitment · 3.7 Returns, Distress and Retiring the Losing Side · 3.8 Royalty Accruals · 3.9 Minimum-Guarantee Settlement and Its Compensating Reversal · 3.10 Counterfeit Enforcement and Exposure Valuation · 3.11 Advancing the Logical Clock
- §4 Endpoint Definitions (39-row table, 4 columns) · §5 Error Code Catalogue (30-row table, 2 columns)

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 107 required, 107 present, 0 missing
- endpoints[].request_body / input: 56 required, 56 present, 0 missing
- endpoints[].query_params: 20 required (limit, offset, + 18 filters), 20 present, 0 missing
- endpoints[].path_params: all present, 0 missing
- combined deduplicated set: 111 required, 111 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 32 checked, 32 expressed in prose (the full precedence ladder in §2.10, plus the per-workflow ground of refusal), 0 missing
- concurrency_rules[] OCC rejections: 2 checked (`expected_production_order_version` on pick, `expected_licensor_version` on minimum-guarantee apply; both named with `ERR_STALE_VERSION` / HTTP 412, framed purely as stale-version rejection with no race/simultaneity wording), 0 missing
- state_machines[].transitions: 25 checked, 25 fully expressed (every from/to pair, precondition + error_id, and side-effect set; all self-loops and the PRINTING→COMMITTED reopen, APPROVAL_REJECTED→PENDING resubmission, and PRINTED→PRINT_FAILED retirement cascade included), 0 missing
- calculations[]: 7 checked (hot_market_capacity_commitment, licensor_royalty_accrual, rush_delivery_commitment, licensor_royalty_settlement, counterfeit_exposure, wholesale_fulfillment_total, demand_collapse_write_down), 7 fully expressed with all constants, pinned evaluation/rounding order, variants and worked divergences, 0 missing
- validations[] conditions: 32 checked, 32 matchable to their error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 39 endpoints' side-effect lists and all `applies_to` scopes expressed (notably segregation-of-duties on 3 endpoints, `ERR_LICENSOR_MISMATCH` on 2, `ERR_PRINT_TYPECAST_MISMATCH` on layers+print, `ERR_CAPACITY_EXCEEDED` on pick/return/distress/retire/reserve), 0 missing
- entities[].fields[] structured content: 107 checked (types, defaults, initial values, computed-source semantics, response-exposure), 107 reconstructible from prose, 0 missing
- sibling-branch symmetry: 14 groups checked (DESTROY vs DONATE at run retire, order distress and layer failure; provisional vs committed-final; PLANNED→RETURNED vs SHIPPED→RETURNED; confirmed vs unconfirmed enforcement), 14 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 618
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notable precision points written in to avoid silence-driven test failures**

- §2.6 states the server startup clock default is exactly `2026-09-01T00:00:00Z` and that it never falls back to wall-clock time; §3.11 states the clock may move backward as well as forward.
- §3.9 states explicitly that applying an early settlement takes it from `PENDING` to `APPROVED` — the scaffold's state machine omits that self-transition from its own transition list, so leaving it out would have made the settlement's terminal-vs-initial state contradictory.
- §3.2 names the tier enumeration values `MAJOR_MARKET`, `REGIONAL`, `LOCAL` explicitly (they appeared only inside the formula's TIER_RESIDUAL map).
- All server-side defaults are stated: `currency=USD`, `player_code=null`, `approved_version=null`, `rejection_reason=null`, `event_outcome=NO_OUTCOME`, `win_probability_pct=0.5`, `outcome_at=null`, `pennants_included=true`, `layer_ids=[]`, all `_qty`/`_cents` counters at 0, `suspect_quantity=0`, `infringement_confirmed=null`, `rush_flag=false`, `donation_recipient_code=null`, `pick_remark=null`, `distress_reason=null`, `retire_reason=null`.
- Both rounding-order traps are given with their divergent worked values (royalty per-row-first 168.76 vs sum-first 168.75; wholesale per-term vs single-round) so an implementer cannot guess the wrong sequence.
- The `test_recipe`/difficulty-design and corner-design indices were never opened, and no sibling task directory was listed, globbed or read.

**Orchestrator verification.** Verified on disk: `workspace/PRD.md` exists, 411 lines / 95587 bytes, headings run §1 Introduction → §2.1–2.11 → §3.1–3.11 → §4 Endpoint Definitions → §5 Error Code Catalogue. (The subagent reported 412 lines; `wc -l` reports 411 — trailing-newline counting, immaterial.)

## Step 5: Generate unit tests — 2026-09-30T14:08:00.000Z

Subagent returned verbatim:

Test infrastructure and suite are complete and verified on disk.

## Files written

**`test_helpers/`** (Stage 1 — 9 files, 1318 lines)
| File | Lines |
|---|---|
| `__init__.py` | 32 |
| `types.py` | 337 |
| `api_client.py` | 199 |
| `api_errors.py` | 72 |
| `assertions.py` | 172 |
| `constants.py` | 85 |
| `factories.py` | 114 |
| `fixtures.py` | 266 |
| `test_users.py` | 41 |

**`test_suite/`** (Stage 2 — 17 files, 3799 lines)
| File | Lines | Tests |
|---|---|---|
| `conftest.py` | 49 | — |
| `test_01_licensor_ledger_basics.py` | 93 | 3 |
| `test_02_design_lifecycle.py` | 142 | 5 |
| `test_03_hot_market_commitment.py` | 254 | 7 |
| `test_04_production_order_creation.py` | 202 | 6 |
| `test_05_design_clearance_cycle.py` | 155 | 5 |
| `test_06_layer_authoring.py` | 216 | 8 |
| `test_07_press_operations.py` | 232 | 9 |
| `test_08_cascades.py` | 193 | 3 |
| `test_09_capacity_windows.py` | 247 | 9 |
| `test_10_demand_and_quote.py` | 158 | 7 |
| `test_11_picking.py` | 237 | 7 |
| `test_12_shipping_and_delivery.py` | 305 | 10 |
| `test_13_returns_distress_retire.py` | 335 | 11 |
| `test_14_royalty_accrual.py` | 202 | 7 |
| `test_15_minimum_guarantee_settlement.py` | 374 | 9 |
| `test_16_counterfeit_enforcement.py` | 405 | 15 |

Total 121 tests / 121 tags / 5117 lines.

## Coverage

- **Queue A (Difficulty): 41 tests; all 18 instances covered, every one by ≥2 tests.** No under-covered instance remains.
- **Queue B (Corner): 80 tests; all 45 non-stub instances covered by ≥1 test.**

## Skips: none

Every instance in both indices passed the PRD-first two-condition filter — each was translated. The 11 `excluded_because:` stubs (4 under `calculations`, 4 under `state_machines`, 3 under `validations`) were **not** translated, per §2.1; their cited difficulty instances resolve to real `name:` entries and own the assertions.

## Verification performed

- Machine-checked every tag against the two YAMLs: **0 invalid tags, 0 untagged tests, 0 instances in a third namespace**; all 121 tags resolve to real non-stub instances.
- Every docstring's final non-empty line matches `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` (0 malformed).
- Every test carries a ≥10-word PRD citation that survives a literal substring match against `workspace/PRD.md`; 16 paraphrased em-dash spans were repaired back to the PRD's `—` character.
- `pyflakes` clean on all 26 modules; `compileall` clean.
- **No `pytest.mark.skip` / `skipif` / `xfail` anywhere.**
- No files created or modified under `workspace/`; no test run performed.

## Notes for the caller

- `fixtures.py` threads the entity-backed role correctly: `make_licensing_ops_headers(licensor["id"])` is used on every ownership-gated call, with the shared `TEST_USERS` constant reserved for non-ownership cases.
- `test_15`'s `_licensor_with_accrual` helper builds the PRD's 843.75-cent reference ledger from ten delivered ECOM orders of 250 units (each contributing 84.375 = 75 + 9.375), which is the only way to reach that figure with whole-unit orders.
- Two design instances (`Hot_market_commitment_first_run_vs_later_run`, `royalty_accrual_per_row_then_sum`) assert the raw float literals verbatim from the recipe (`168.76`). The assertions pass as written in Python; `pytest.approx` would be the safer form if the framework's JSON decoding ever quantizes these, but I kept the recipes' literal values since they are the load-bearing distinction.

**Orchestrator verification.** Verified on disk: `test_helpers/` holds 9 files, `test_suite/` holds 17 files; combined 5117 lines, matching the subagent's figure. No `workspace/implementation/` directory was created at this step (confirmed — `workspace/` contains only `INSTRUCTION.md` and `PRD.md`).

## Step 6: Generate implementation — 2026-09-30T14:13:00.000Z

Subagent returned verbatim:

The implementation is complete and verified. Here is my summary.

## What was built

A complete Python + Flask implementation at
`/home/ubuntu/github/CodingPRD/tasks/task_3232_licensed_merchandise_hot_market_production_event_fulfillment/workspace/implementation/`

**Files written (line counts):**

| File | Lines |
|---|---|
| `start.sh` | 9 (executable, reads `$PORT` default 10000, binds `0.0.0.0`, `exec`s the server in the foreground, guarded `import flask` so per-test reboots skip `pip install`) |
| `requirements.txt` | 1 (`Flask>=3.0,<4.0`) |
| `app.py` | 48 (envelope-preserving error handlers, blueprint registration, `0.0.0.0:$PORT`) |
| `db.py` | 141 (in-memory entity maps, logical clock, timestamps, creation ordering) |
| `errors.py` | 99 (30 error IDs + declared HTTP statuses, `ApiError`) |
| `response.py` | 131 (envelope `meta`/`response_type`/`data`, pagination, auth) |
| `routing.py` | 238 (blueprint + shared request-shape/existence/authorization helpers) |
| `routes/__init__.py` | 6 |
| `routes/licensing.py` | 278 |
| `routes/production.py` | 390 |
| `routes/capacity.py` | 162 |
| `routes/fulfillment.py` | 243 |
| `routes/enforcement.py` | 142 |
| `services/ledger.py` | 255 |
| `services/pricing.py` | 237 |
| `services/production.py` | 296 |
| `services/fulfillment.py` | 277 |

**Endpoints: 39 registered (38 business + 1 test-driving `POST /_clock/set_current_utc`)** — audited directly from `app.url_map`, not from source.

**Storage: in-memory only.** All state lives in Python dicts on a single `Store` instance; there is no SQLite, no file write, no `/tmp` cache, no `json.dump`, and no external persistence. **No entity is seeded** — every store starts empty and repeated fresh `start.sh` boots return `{"data": []}`. The only pre-populated value is the logical clock's documented startup default `2026-09-01T00:00:00Z`.

## Verification performed (sanity only; the pytest suite was never read or run)

I booted the server on my own explicit ports, drove ~120 HTTP calls across five scenario scripts, and killed only PIDs I started. Confirmed against the spec's own reference values:

- Royalty accrual rounding: two delivered 1250-cent CAP orders → `168.76` (per-row first, not `168.75`)
- Settlement: A=843.75, guarantee 2000, R=100, breach accepted → shortfall `1256.25`, A 743.75 / B 1256.25 / U 0, and apply→reverse restores 843.75/0/843.75 with zero drift
- Hot-market variants: first run 375 vs later run 275 on identical inputs; counterfeit leakage/penalty 13920/34800 on 200 units at rate 0.08
- Write-downs: 100 units × 900 cents → 36000 (STANDARD) vs 90000 (hot market)
- Full precedence ladder, terminal lockdown, the reopen rail (PRINTING→COMMITTED with re-stamped window and re-layering), the PRINTING-retire skip-if-lesser write-down, the reclaim rail for closed capacity windows, SoD, `ERR_LICENSOR_MISMATCH`, both OCC writes of record, `ERR_EVENT_WINDOW_CLOSED`, pagination band, and 404/403/412/409/422/400 statuses

## Judgement calls worth flagging

- **Fractional ledger values.** §2.7 calls `_cents` fields integers, but the PRD's own normative examples yield `168.76` and `843.75`. I followed the worked examples and carry ledger quantities at 2dp (HALF_UP) rather than truncating; a truncating reading would contradict the spec's stated divergence example.
- **Run-creation rights project.** `POST /production-orders` must reject a licensor holding no rights project covering the trigger type (`ERR_LICENSOR_PROJECT_NOT_FOUND`), but no endpoint declares projects. I followed the PRD ("a licensor holds a recorded rights project" is a *limitation* on runs) and treat a registered licensor as holding coverage for all trigger types and garment SKUs — the rejection branch is implemented, and the practical path tests use returns 201. I also added that coverage check to `POST /designs` (implied, though not explicitly triggered in the PRD).
- **`committed_inventory_cents` / `hold_allocation_cents` / the pick "reference pool"** are all under-specified and get no literal formula or constants. I implemented them so the stated integer bounds hold (the pool derives from `committed_inventory_cents ÷ unit_cost_cents`, and the pick's two pools return distinct, deterministically ordered errors as §3.5 describes). These are the thinnest points in the spec.
- **Interpretation of SoD.** The design's licensor decision records only the decisioning operator's identity; creating a run doesn't itself record a creator, so the rule fires on layers-commit and settlement, as §2.1's explanatory sentence describes.

**Orchestrator verification.** Verified on disk: `workspace/implementation/` contains 17 files (`start.sh` present and mode 0755 executable, `requirements.txt`, 15 Python modules across `routes/` and `services/`). No `results.*.json` and no test artifacts present, so the isolation rule held. `start.sh` is executable, which the harness requires.

## Step 7: Run tests and iterate — 2026-09-30T16:21:00.000Z

Subagent returned verbatim:

All 8 rounds pass cleanly. Here is the summary.

## Summary — task_3232_licensed_merchandise_hot_market_production_event_fulfillment

**Final state: 141/141 tests passing in all 8 concurrent rounds, 0 failed, 0 skipped, 0 errors.**

**Iterations run:** 6 sweeps (each 8 parallel rounds). Failure union went 88 → 40 → 17 → 10 → 2 → 0. Every failing test failed in all 8 rounds at each stage (deterministic, no flakiness); the only within-sweep variance seen was one round-4-only setup 404 that did not recur and did not affect the union.

**Tests deleted: NONE.** No test asserted a scaffold-only rule or a rule whose outcome two faithful PRD readers could diverge on. Where a rule was genuinely under-specified or a test's own docstring conflicted with its body, the fix was to make the test *more* PRD-faithful (never weakened, never skipped/xfailed), or to fix the implementation.

### Fixes applied to `test_helpers/`
- `fixtures.py` / `author_layers()` — each layer entry now carries `design_id` from its run. The PRD names the layer's artwork through the run; the fixture issued payloads with no `design_id` at all, which the PRD-faithful implementation correctly refused. This one fixture bug drove **75 of the 88** original failures.

### Fixes applied to `implementation/`
- `routes/production.py` — `_validate_layer_payload` no longer demands a layer-body `design_id` (fields named only for the `PrintLayer` entity are not required request-body inputs; a layer without one inherits its run's artwork). Reverted the state-before-concurrency ordering so the stale-version guard (rung 6) is reported ahead of commit sequencing (rung 9); print-failure on a printed layer is gated by the event window before any write; removed the unreachable duplicate reopen-window check.
- `routes/enforcement.py` — counterfeit integrity restored to the §2.10 enumeration order (overcount constraint before the listing referential); this reconciled a direct contradiction between two tests generated from mutually contradictory design recipes.
- `routes/licensing.py` — `GET /designs/{id}` returns `ERR_NOT_FOUND` for a bare path identifier (§2.11), not the reference-specific code; licensor decisions now flip by state (rejection is the §3.1 revocation rail acting on approved artwork) rather than the contradictory literal reading, which is the only self-consistent reading of §3.1's terminal-state claim plus its normative revocation cascade.
- `routes/capacity.py` — the client-supplied `needed_by` instant is echoed byte-identically instead of being reformatted.
- `routes/fulfillment.py` — pick now checks terminal lockdown (rung 5) before optimistic concurrency (rung 6).
- `services/production.py` — `refresh_printed_totals` credits a still-`PENDING_PRINT` committed layer at its authorised quantity (the "committed layer set"); new `credited_units` gives the pick's reference pool the sellable units of the run's paid-for layers; `fail_printed_layers(force_printed=True)` makes retirement take the whole layer set to `PRINT_FAILED`; Target A write-down recomputed (replaces) from the run's destroyed/donated ledgers rather than accumulating printed units; added `close_order_at_event_window` for Target B; retirement's `DESTROY` branch marks non-terminal orders `DISTRESSED`; `_lot_exhausted` counts only shipped/distressed orders as having left the pool.
- `services/fulfillment.py` — reference pool measured off the order's own requested quantity; `_reference_pool` narrowed to the PRD's "earliest shipment ordered by `committed_at`" (no invented quantisation).
- `services/ledger.py` — `recompute_licensor_accrued` now recomputes `accrued_unsettled_cents` from the invariant, which fixed royalty never appearing in the unsettled figure on delivery.

### Fixes applied to `test_suite/`
- `test_15` — `_licensor_with_accrual` rebuilt to reach the PRD's 843.75-cent ledger at true two-decimal per-row accrual (one 2500-unit CAP order), replacing a fixture that assumed the scaffold's third-decimal arithmetic; the no-op settle test now sets the CAP SKU its own citation names.
- `test_03`, `test_04`, `test_06`, `test_11`, `test_16` — boundary/version/role assertions corrected to express the cited §3.2 sentence verbatim (e.g. the 12550 regional figure is derivable only via the committed-final tier residual, so the suite opens earlier runs of the same team/trigger; licensor and design reads switched to roles §2.3 actually grants; the two §3.1/§3.3 uncleared-artwork cases now assert the run-creation gate the PRD actually states).

**Orchestrator verification.** Verified independently: all 8 `results.{1..8}.json` exist and each reports `passed=141 total=141 failed=0 skipped=0 errors=0`. Counted test functions directly: 121 `def test_` across 16 suite files, with 9 files using `@pytest.mark.parametrize` — which accounts for the gap between Step 5's 121 tagged instances and the 141 collected items (parametrized counterpart variants share their parent's tag; tag census is 41 `Design: Difficulty/` + 80 `Design: Corner/` = 121). No `results.*.json` cleanup is needed for the next step; the sweep files are the required final-state evidence.

Step 8 is NOT skipped: although Step 7 deleted 0 tests, it applied 3 `test_helpers/` + 12 `implementation/` + 6 `test_suite/` fixes, so PRD silences and PRD/impl mismatches were found.

## Step 8: Finalize PRD — 2026-09-30T16:40:00.000Z

Subagent returned verbatim:

Done. `PRD_FINALIZED.md` written — 411 lines vs PRD's 411 (0% line delta; all 15 changes are single-line in-place replacements).

## Changes

- §2.7 (line 115) — revise — ledger triple (`accrued_royalty_cents`, `guarantee_recovery_block_cents`, `accrued_unsettled_cents`) carries two decimal places, so the spec's own 168.76 / 843.75 figures are reachable — `services/ledger.py:51,63-68` (`q2`)
- §2.11 (line 167) — revise — missing-resource code is `ERR_NOT_FOUND` for design-by-path, layer, capacity, report, accrual; `ERR_PRODUCTION_ORDER_NOT_FOUND`/`ERR_FULFILLMENT_ORDER_NOT_FOUND` even by path; `ERR_DESIGN_NOT_FOUND` only for body refs — `routes/licensing.py:212`, `routing.py:124-180`
- §3.1 (line 177) — revise — REJECT accepted from `PENDING_LICENSOR_APPROVAL` **or** `APPROVED`, refused only once already rejected; approval is the one-way edge, so `APPROVED` is not "terminal" — `routes/licensing.py:260-265`
- §3.1 (line 179) — insert — rejection cascade also recomputes the retired run's `write_down_inventory_cents` from its `destroyed_units` — `services/production.py:226-228`
- §3.3 (line 203) — insert — a layer's `design_id` may be omitted (inherits the run's pinned artwork); only a non-string is a shape failure — `routes/production.py:140-158,221`
- §3.3 (line 209) — revise — totals are recomputed from the run's layer set; each layer contributes capped `committed_qty`, except a `PENDING_PRINT` layer is credited at its authorised quantity — `services/production.py:11-33`
- §3.4 (line 221) — insert — a first print may land on a `PENDING_PRINT` layer and carries it straight to `PRINTED` — `routes/production.py:342-346`
- §3.4 (line 223) — insert — a failure on an already-printed layer is window-gated; one on a `PENDING_PRINT` layer is not — `routes/production.py:374-379`
- §3.4 (line 229) — revise — retirement fails the whole layer set (printed or not); `design_version_checked` takes `retired_design_version` only on a destroyed-from-`PRINTING` retirement; write-down is recomputed, order-level charge skip-if-lesser — `services/production.py:177-206,312,324-328`
- §3.4 (line 231) — insert — `needed_by` is echoed byte-identically — `routes/capacity.py:142`
- §3.7 (line 279) — insert — every retire branch moves the run's entire layer set to `PRINT_FAILED` — `services/production.py:312,325-328`
- §3.7 (line 281) — revise — both disposal branches act on still-open orders only and move them to `DISTRESSED`/`DEMAND_COLLAPSE` — `services/production.py:272-295`
- §3.7 (line 283) — revise — `PARALLEL_HOLD` retirement scales open orders to zero and distresses every still-open one — `services/production.py:203-206,312-313`
- §3.7 (line 285) — insert — destroyed-from-`PRINTING` failures record `retired_design_version`; donated ones record the observed current version — `services/production.py:324-328`
- §3.7 (line 287) — insert — the run-level Target A figure is recomputed (replaces), not accumulated from printed units — `services/production.py:341-345`

## Per-edit pre-edit search log

1. **Ledger 2dp** — (a) decimal places of ledger quantities. (b) `ledger.q2` callers (`recompute_unsettled`, `apply_cap`, `accrue`, `recompute_licensor_accrued`, `apply_settlement`, `reverse_settlement`) vs `to_cents`/`int` for all other `_cents` fields; §3.9 examples 843.75/1256.25. (c) Scoped the exception to the three ledger quantities; did not touch the "rounded half up … never later" rule.
2. **Missing-resource codes** — (a) which error id a missing reference yields. (b) `routing.get_*` factories and every `error_id=` override + every `get_run`/`get_design` call in `routes/*.py`; test_02 and test_16. (c) Corrected the false universal that a bare path id always yields `ERR_NOT_FOUND`.
3. **Decision states** — (a) licensor-decision preconditions, `APPROVED` gravity. (b) `licensor_decision`, `submit_design`, `cascade_design_rejection`, `check_segregation`; test_05, test_08. (c) Dropped "terminal state for the channel"; kept APPROVE from PENDING, widened REJECT to PENDING or APPROVED.
4. **Rejection-cascade write-down** — (a) cascade's write-down booking. (b) `cascade_design_rejection`, `run_write_down`, §3.7 retirement recompute. (c) None — stated only the destroyed-units recompute.
5. **Layer `design_id` optional** — (a) requiredness of the layer body's artwork field. (b) `_validate_layer_payload`, layer creation, the conditional `get_design`, `refresh_printed_totals`, `credited_units`, royalty path (reads run's design). (c) None — explicitly allowed omission while preserving the mistyped-field failure.
6. **Printed totals** — (a) how the two totals are computed. (b) `refresh_printed_totals` and all 9 callsites, `sellable_units`, `credited_units`, `capitalized_inventory`; test_06/07/08. (c) Replaced "committed layer set … summing `committed_qty`" with the PENDING-credits-authorised rule that holds at every callsite.
7. **Print on PENDING layer** — (a) printing an unprinted layer. (b) `routes/production.py:print_layer` state assignment + `refresh_printed_totals`. (c) None — no path requires prior authoring.
8. **Print-failure window** — (a) whether the event window gates print-failure. (b) `routes/production.py:print_failure` (`was_printed` gate). (c) Scoped the gate to the already-printed case only.
9. **Third way into PRINT_FAILED** — (a) retire-path layer failure. (b) `fail_printed_layers(force_printed=True)`, `run_write_down`, `order_write_down`; test_13, test_08. (c) Removed the false claim that `design_version_checked` is always `retired_design_version`, and the false "write-down recorded at the layer's planned quantity".
10. **needed_by echo** — (a) stored/returned `needed_by`. (b) `reserve_capacity`, `list_reservations`, `rush_delivery_points` (`hours_between`), test_09 byte-identity. (c) None.
11. **All layers failed on retire** — (a) which layers a retirement fails. (b) every `retire_run` branch + `cascade_design_rejection`; test_13. (c) Added a branch-independent "entire layer set" sentence rather than narrowing per branch.
12. **Disposal branches** — (a) order disposal at retirement. (b) `_settle_orders_for_disposal`, `destroy_weighted_total`/`donate_weighted_total`; test_13, test_08. (c) Added the open-only scope and the `DISTRESSED`/`DEMAND_COLLAPSE` transition the original omitted.
13. **PARALLEL_HOLD retire** — (a) that branch's demand effect. (b) `fail_printed_layers(scale_demand=True)` → `scale_open_orders(0,1)` → `_distress_by_cascade`. (c) Changed "below zero" to "to zero / still open" to match the implementation.
14. **PRINTING retire design_version_checked** — (a) audit version on retire-failed layers. (b) `below` flag / `forced_version` logic; §3.4 rule. (c) Added the destroy-vs-donate distinction the original flattened.
15. **Target A replacement** — (a) how the run-level write-down is produced. (b) `retire_run` (assign not accumulate), `run_write_down`, `mark_committed`/`reopen_run` seeds; test_13. (c) None.

**Orchestrator verification.** Verified on disk: `PRD_FINALIZED.md` exists, 411 lines / 99195 bytes vs `PRD.md` 411 lines / 95587 bytes — 0% line delta, +3.8% byte delta, matching "15 single-line in-place replacements". `diff PRD.md PRD_FINALIZED.md` yields exactly 30 changed lines (15 removed + 15 added), consistent with the reported 15 edits.

## Step 9: Complete PRD — 2026-09-30T17:20:00.000Z

Subagent returned verbatim:

All edits are applied and verified. Final report:

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_3232_licensed_merchandise_hot_market_production_event_fulfillment/workspace/PRD_COMPLETED.md`

- Source: `PRD_FINALIZED.md` existed and was copied first.
- Lines: 411 → 411 (unchanged). Chars: 98,961 → 101,583 (delta +2,622). Line counts stay identical because every change was an inline insert/revision inside an existing paragraph; no sections, paragraphs or headings were added.

## Counts
- Ambiguity-pins (PRD silent → pinned to impl): 10
- Mismatch-revisions (PRD said something else → corrected): 6
- Total: 16 changes

## Changes
- §2.4 Rights-Holder Ledgers — insert — ambiguity — a registered licensor is recorded as holding a project covering every trigger type and garment SKU, so `ERR_LICENSOR_PROJECT_NOT_FOUND` never fires against it — `implementation/routing.py:200-217`, `:207`
- §3.2 Parallel-Hold Pair — insert — ambiguity — a run created with no `outcome_at` is capitalised at a fixed 24-hour horizon — `implementation/routing.py:43`, `implementation/routes/production.py:67-68`
- §3.2 Parallel-Hold Pair — insert — ambiguity — allocation floor defined as ceil(demand·p/2); the "alignment" is the tier residual (LOCAL 25, REGIONAL 50, MAJOR_MARKET 0) — `implementation/services/pricing.py:97-103`
- §3.2 Parallel-Hold Pair — insert — ambiguity — `hold_allocation_cents` = unit cost × capacity_commitment_units (hot-market) or × expected_demand_qty (STANDARD) — `implementation/services/production.py:103-109`
- §3.3 Layer Authoring — insert — ambiguity — committed `committed_inventory_cents` formula, including layer credit (min(quantity, committed_qty), PENDING_PRINT at full quantity, all-failed at 0) — `implementation/services/production.py:68-100`
- §3.4 Press Operations — revise — mismatch — press-failure demand scaling denominator corrected from the run's `quantity` to the layer's authorised `quantity` — `implementation/services/production.py:170-171`
- §3.4 Reopen Rail — insert — ambiguity — reopen scaling projects the layer's realised units forward so a zeroed reducer scales open demand to zero — `implementation/services/production.py:157-158`, `:204-205`
- §3.4 Rush Commitment — insert — ambiguity — reservation walk matches windows against the run's authored layer capabilities, with PENNANT riding BASE — `implementation/services/pricing.py:108-126`
- §3.4 Rush Commitment — insert — ambiguity — committing does not rewrite `rush_delivery_points` from the fast rail; the points its reservations earn stand — `implementation/services/production.py:241` (recomputes honestly via `pricing.refresh_rush_delivery_points`)
- §3.5 Shared Inventory Pool — insert — ambiguity — reference pool is the order's own requested `quantity`; earliest-shipment key resolves to the same figure — `implementation/services/fulfillment.py:100-111`
- §3.6 Shipping — revise — mismatch — removed the "each shipment recomputes requested_wholesale_cents at city/face rate" claim; shipments do not reprice — `implementation/services/fulfillment.py:138-172`
- §3.7 Returns — revise — mismatch — return permitted from PLANNED regardless of pick history/run state; ledger line keyed on entry path (SHIPPED → `units_damaged_destroyed`) — `implementation/services/fulfillment.py:201-232`
- §3.7 Disposal — insert — ambiguity — an omitted `destroy_mode` on the committed branches takes the destruction path — `implementation/services/production.py:316-318`
- §3.7 Write-Down — revise — mismatch — the discharged-wholesale clamp does not reduce the run target; run write-down is recomputed from lost units alone — `implementation/services/production.py:341-345`, `implementation/services/pricing.py:211-220`
- §3.8 Royalty Accruals — revise — mismatch — rows carry `RUSH_or_STANDARD` basis, never go `SETTLED`, `settled_cents` stays 0; supersession is across the licensor, not a "licensor-and-version pair" — `implementation/services/ledger.py:100-127`
- §3.9 Settlement Reversal — revise — mismatch — reversal does not recompute counterfeit exposure on affected reports — `implementation/routes/enforcement.py:129-136` (exposure only written on confirm)

## Key findings
Every change is an inline edit inside existing prose; the endpoint table, error catalogue and section structure are untouched. The largest cluster of silent behaviours was the run's computed money fields (`hold_allocation_cents`, `committed_inventory_cents`, `rush_delivery_points`) — all write-visible on `POST /production-orders` but asserted by no test — plus three rails where PRD didn't pin the arithmetic (press-failure scaling, accrual-row bookkeeping, shipped-return ledger lines).

**Orchestrator verification.** Verified on disk: `PRD_COMPLETED.md` exists, 411 lines / 101835 bytes, over `PRD_FINALIZED.md`'s 411 lines / 99195 bytes — 0% line delta, +2.7% byte delta. `diff PRD_FINALIZED.md PRD_COMPLETED.md` yields 32 changed lines (16 removed + 16 added), consistent with the reported 16 edits. Endpoint table and error catalogue sections unchanged in structure.

## Step 10: Pipeline close — 2026-09-30T17:21:00.000Z

Final-state verification (orchestrator, direct on disk):

- All 8 sweep rounds report `passed=141 total=141 failed=0 skipped=0 errors=0` (`workspace/implementation/results.{1..8}.json`).
- `find` confirms no file under `workspace/implementation/`, `test_suite/` or `test_helpers/` was modified after the final sweep at 16:21 — Steps 8 and 9 were documentation-only, so the passing sweep remains valid evidence for the shipped artifacts.
- Task directory contains: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 files), `test_suite/` (17 files), `workspace/` (`INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `implementation/` with 17 files incl. executable `start.sh`).

Process-safety note: no broad kill pattern (`pkill -f`, `killall`, `pgrep | xargs kill`) was used at any point in this pipeline; no PIDs were killed by the orchestrator at all — all server lifecycle was owned by `prd-bench-local-run` and by subagents killing only PIDs they had started.