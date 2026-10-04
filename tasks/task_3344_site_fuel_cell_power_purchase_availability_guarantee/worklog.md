# Worklog — task_3344_site_fuel_cell_power_purchase_availability_guarantee

## Step 1: Create task directory — 2026-09-30T22:04:00.000Z

Task directory `tasks/task_3344_site_fuel_cell_power_purchase_availability_guarantee/` was pre-allocated by the pipeline invocation and already contains `workspace/`. No index computation performed; no other `task_*` directory created.

## Step 2: (attempt 1, interrupted) Generate scaffold — 2026-09-30T22:05:00.000Z

Subagent launched but the host killed all background processes under memory pressure before the subagent returned; no output files were written. Task directory was inspected on 2026-10-01T04:07Z and contained only `worklog.md` + empty `workspace/`. Step 2 restarted from scratch.
## Step 2: Generate scaffold — 2026-10-01T04:45:00.000Z

All three artifacts are written and the scaffold passes the skill's linter cleanly. Final state:

### Files written
- `SCAFFOLD.yaml` (175 KB — §1.0–§1.7; no difficulty/corner keys inside)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (84 KB — single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (164 KB — single top-level key `scaffold_corner_design`)

Nothing else in the task directory was touched (a pre-existing `worklog.md` and `workspace/` were already there). No sibling task directory was read, listed, or globbed.

### Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    64
  §1.1 entities declared:     9
  §1.8 instances scanned:     22
  §1.9 instances scanned:     48
  Calls scanned (§1.8+§1.9):  525

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### Counts
| Element | Count |
|---|---|
| Entities / fields | 9 / 172 |
| State machines / transitions | 8 / 50 |
| Calculations / variants | 25 / 50 |
| Validations | 39 (priorities 1–28, no duplicate priority) |
| Endpoints | 64 |
| Errors | 37 (every one referenced by a validation, transition side effect, or concurrency rule) |
| Roles | 7 (1 `entity_backed:Customer`, 6 `opaque`) |
| Concurrency rules | 3 (all OCC on a parent `version`, all with `expected_*_version` required input + version bump) |
| §1.8 difficulty instances | 22 across all nine rules (rule minimums 2,2,2,2,2,3,4,3,2) |
| §1.9 corner instances | 48 (47 with recipes + 1 `excluded_because:` stub) |

### Design
**Archetype** Ledger reconciliation × Temporal windowing; layers: cascading side effects, optimistic concurrency, derived-field reconciliation, scheduled/deferred actions, multi-tenancy isolation. Topology hybrid, state shape parallel, role model segregation of duties, consistency saga.

**Difficulty design (≥2 per rule, differentiation clauses honored):** dual-variant on ServicePlan lifecycle vs fuel custody (R1); mode-(a) nested-min reserve floor and mode-(b) per-line-then-sum proration (R2); Ppa exit→cure cycle and ServicePlan parallel cyclic dimensions (R3); depth-4 site-freeze → Ppa → ServicePlan → replacement-stage and depth-3 delivery-confirm → site fuel basis (R4); `state` vs `business_constraint` and `business_safety` vs `business_temporal` conflicts (R5); three boundary instances — 0–1 paired-field set, exact confirm instant, zero cap pool (R6); four cross-entity pairs (Site→Ppa freeze, Ppa→Customer renew, Site→Ppa transfer, Ppa→Allowance issuance) (R7); closed-interval holder vs half-open settlement adjacency vs per-resource aggregate scope (R8); therm-conservation and signed-accrual conservation (R9).

**Corner design sections:** entities (10), state_machines (9), calculations (6), validations (5), endpoints (3), errors (3 + 1 stub), rbac (4), cross_cutting_layers (5), consistency_model (2).

**Hard-difficulty machinery applied:** two depth-5/depth-4 conditional cascades; five calculation modes (nested min/max, pinned rounding order, pinned circular evaluation order, tiered remedy branches, double waterfall/countdown overflow); 28 validation priorities with dual-failure precedence tests; three true OCC races reduced to sequential stale-version checks; saga compensation pinned (settle reconciles accruals → reverse reopens them).

**Consistency notes:** forbidden concurrency vocabulary absent; identical-ID bug class avoided (child entities carry optional filtered-list discriminators, so no same-method+same-path GET differs only by output type); all reverse-reachability GETs present; every formula-derived assert is a pre-computed literal (e.g. `net_charge_cents == 9051567.57`, `439868.90`, `4665600.00`, `363708.50` vs `363708.49`, `8946567.57`).

### Orchestrator verification (independent of subagent report)
Ran `yaml.safe_load` on all three files: all parse, top-level keys correct (`scenario, domain_name, api_prefix, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, response_envelope, endpoints, errors` for SCAFFOLD.yaml; single-key `scaffold_difficulty_design` / `scaffold_corner_design` for the two design indices). Verified counts independently: 64 endpoints / 9 entities / 37 errors, all 64 endpoint method+path pairs unique. Tail bytes of each file show well-formed YAML closures (no truncation).

## Step 3: Copy shared INSTRUCTION.md — 2026-10-01T04:45:05.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `tasks/task_3344_site_fuel_cell_power_purchase_availability_guarantee/workspace/INSTRUCTION.md` (1424 bytes). Build contract: produce `./implementation/start.sh`; server listens on `$PORT` (default 10000), binds `0.0.0.0`, stays in the foreground; evaluator runs `bash start.sh` from `./implementation/`.

## Step 4: Generate PRD — 2026-10-01T04:57:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — 1,627 lines, ~128 KB.

**Section coverage (all of §1.0–§1.7 expressed in prose):**
- §1 Introduction — 3 paragraphs (site-evaluation pain points, resource-pool framing, auditability constraint)
- §2 — 10 domain-derived subsections: 2.1 Request Identity and Segregation of Duties (all 7 roles, `entity_backed:Customer` vs 6 `opaque`, both auth error IDs); 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md` — verified by diff); 2.3 Pagination (defaults 10 / min 1 / max 100 / offset 0, `created_at` ascending, meta fields); 2.4 Resource Identity, Common Properties and Collection Filters (id/created_at/updated_at/version, `PpaTransition`'s `common_fields: false` absence of updated_at+version, all 64 endpoints' filter params, left-to-right nested resolution with all four not-found IDs, global validation priority order 1→29+); 2.5 Site Posture and the Suspension Cascade; 2.6 Fuel Pool, Delivery Windows and Sourcing Configuration; 2.7 Optimistic Concurrency (all 3 rules with `expected_site_version` / `expected_ppa_version` → `ERR_STALE_VERSION` 412); 2.8 Money, Precision and Escalation; 2.9 Reserves, Stop-Loss and the Credit Exposure Cap; 2.10 The Logical Clock and Deferred Actions
- §3 — 9 subsections grouped by lifecycle stage / business-process timeline (siting & evaluation → PPA drafting/activation/adjustment → fuel supply, custody, allocation, accruals → settlement-line lifecycle, reversal, true-up, rollover, rebate → escalated rates, pool waterfalls, remedy tiers → allowances → service plans & module replacement → exit/cure/termination/renewal/transfer → portfolio aggregates & token ledger). No tables, no field lists, no declared foreign keys.
- §4 — 64-row table, 4 columns (Method, Path, Description, Authorized Role(s)); status-code rule stated above it
- §5 — 39-row table, 2 columns (37 error IDs + header/separator); no trigger conditions

**Hard contract reports**

```
Field coverage check:
- entities[].fields: 153 required, 153 present, 0 missing
- endpoints[].request_body/input: 81 required, 81 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS
```
(Verified mechanically twice, per the skill's two-pass rule; the first pass found `industry_code`, `net_charge_allocated_cents`, `trigger_code` missing and all three were repaired in their natural narrative homes. All 102 enum-type field values and all 50 state-machine state strings also verified present.)

```
Rule coverage check:
- validations[] with priority: 39 checked, 39 expressed with relative ordering in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named; no overlap-in-time framing used), 0 missing
- state_machines[].transitions: 50 checked, 50 fully expressed (state pair + preconditions with error IDs + side effects + trigger/actor), 0 missing
- calculations[]: 25 checked, 25 expressed in precise prose, 0 missing
- validations[] conditions: 39 checked, all matchable to their error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 64 checked, expressed (validations' applies_to sets enumerated; cascades stated hop-by-hop including the depth-5 activation chain and the confirmation chain), 0 missing
- entities[].fields[] structured content: 106 defaulted fields checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (draft vs locked pool basis; monthly vs hourly proration; ALLOCATION_ORDER vs UNIT_INDEX; AVOIDED_COST vs CAPACITY allowance; as-built vs transferred; deemed vs actual; measured vs no-meter extension; per-line vs batch true-up; itemised vs aggregated commit), 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 344
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Items the generator could not express as unambiguous prose** (all are defects carried faithfully rather than invented):
1. `calculations[10] commitment_allocation_rights` — "Self-sourcing customer must not appear…" is absent, and it references `party_effective_flag`, `allocation.party_effective_flag`, `allocated_kwh`, `term_months` and `normalized()` which are not declared entity fields; the prose states the weighted score (0.5 / 0.3 / 0.2, ×100, 2dp) and the caps `SCOPE_RATIO_CEILING`, `ALLOCATION_CEILING_PCT`, `FALLBACK_BINDING_PCT` verbatim, but the clause cannot be uniquely reconstructed.
2. `calculations[19] availability_savings_two_offtakers` — the branch compares against `RATE_CAP_REFERENCE_CENTS` (300000) while the else-branch also divides by 300000 and multiplies by `BASE_SAVINGS_REFERENCE_CENTS` (2), and `BASE_SAVINGS_REFERENCE_CENTS: 2` overlaps with the default rate difference 2.2; both branches stated exactly as written, but the threshold is semantically unreachable.
3. `calculations[2] net_charge_cents = pool_after_loss − output_shortfall − capacity_shortfall` collides with `calculations[3]`'s four-pool sum for the same field name; both are stated.
4. Design-index files were not opened, grepped, or referenced; no sibling task directory was read, listed, or globbed.

### Orchestrator verification (independent of subagent report)
`wc -l -c workspace/PRD.md` → 1627 lines / 128749 bytes. `grep -n '^#\{1,3\} '` confirms the full section skeleton is present (1, 2.1–2.10, 3.1–3.9, 4, 5) and the file tail is the complete §5 error-code table closing on `ERR_STALE_VERSION | 412 Precondition Failed` — no truncation. Both `INSTRUCTION.md` and `PRD.md` present in `workspace/`.

## Step 5: Generate unit tests — 2026-10-01T05:38:00.000Z (IN PROGRESS)

Test generation proved unstable on this host: the first subagent was killed by the host's memory-pressure process sweep at 05:16 mid-file, and two subsequent attempts died on a transient endpoint error (`model_not_found` for `deepseek-v4p1-flash-wave`). Work is therefore being completed incrementally, with orchestrator verification between every attempt.

### Verified state at 05:38Z
Files on disk and independently checked with `ast.parse` + AST docstring walk:

| File | Tests | Design tags | Parse |
|---|---|---|---|
| test_helpers/{__init__,types,api_client,api_errors,assertions,constants,factories,test_users,fixtures}.py | — | — | all OK |
| test_suite/conftest.py | 0 | 0 | OK |
| test_suite/test_01_settlement_pool_basis.py | 5 | 5 | OK |
| test_suite/test_02_fuel_pricing_basis.py | 4 | 4 | OK |
| test_suite/test_03_contract_state_cycles.py | 4 | 4 | OK |
| test_suite/test_04_freeze_cascade.py | 5 | 5 | OK |
| test_suite/test_05_validation_ordering.py | 6 | 6 | OK |
| test_suite/test_06_boundary_precision.py | 6 | 6 | OK |
| test_suite/test_07_cross_entity_gates.py | 9 | 9 | OK |
| test_suite/test_08_window_semantics.py | 6 | 6 | OK |
| test_suite/test_09_allocatable_pool_and_ledger.py | 5 | 5 | OK |
| test_suite/test_10_capacity_reserve_floor.py | 2 | 2 | OK |
| test_suite/test_20_entity_contracts.py | 10 | 10 | OK |
| test_suite/test_21_state_machine_contracts.py | 17 | 17 | OK |
| test_suite/test_22_calculation_contracts.py | 9 | 9 | OK |

88 test functions total; **0 tagging issues** (every test carries exactly one `Design:` line; no untagged and no dual-tagged tests).

Coverage measured mechanically against the two design indices:
- **Queue A (§1.8 difficulty): 22/22 instances tagged, 0 missing, 0 extra tags.** Complete.
- **Queue B (§1.9 corner): 23/48 real instances tagged, 25 missing.** Remaining sections: validations (5), cross_cutting_layers (6), rbac (4), errors (3), endpoints (3), calculations (2), consistency_model (2).

Note: 33 instances are currently covered by more than one test function (88 tests over 45 distinct instances). This is over-generation, not the spec's "dual-tagged test" failure mode (each individual test still carries exactly one tag). Logged for the Step 7 reviewer; not blocking.

## Step 5: Generate unit tests — 2026-10-01T09:05:00.000Z (COMPLETE)

Generation spanned four attempts (host memory-pressure kill at 05:16; two transient `model_not_found` endpoint failures; final successful run on the replacement endpoint). Steps 5 and 6 were run sequentially rather than concurrently because this endpoint duplicates parallel tool calls — isolation of the Step 6 implementer from `test_suite/` is therefore enforced by an explicit read ban in the Step 6 prompt rather than by non-existence of the directory.

### Final verified state (orchestrator-checked with `ast.parse` + AST docstring walk, independent of subagent reports)

**test_helpers/** (9 files, unchanged since first attempt): `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `test_users.py`, `fixtures.py`

**test_suite/** (16 test files + conftest.py):

| File | Tests |
|---|---|
| test_01_settlement_pool_basis.py | 5 |
| test_02_fuel_pricing_basis.py | 4 |
| test_03_contract_state_cycles.py | 4 |
| test_04_freeze_cascade.py | 5 |
| test_05_validation_ordering.py | 6 |
| test_06_boundary_precision.py | 6 |
| test_07_cross_entity_gates.py | 9 |
| test_08_window_semantics.py | 6 |
| test_09_allocatable_pool_and_ledger.py | 5 |
| test_10_capacity_reserve_floor.py | 2 |
| test_20_entity_contracts.py | 10 |
| test_21_state_machine_contracts.py | 17 |
| test_22_calculation_contracts.py | 9 |
| test_23_validation_contracts.py | 5 |
| test_24_cross_cutting_layers.py | 6 |
| test_25_rbac_contracts.py | 3 |
| test_26_error_surface_contracts.py | 3 |
| test_27_endpoint_contracts.py | 3 |
| test_28_calculation_and_consistency.py | 3 |

**111 test functions, 68 distinct tagged instances. 0 syntax errors, 0 untagged tests, 0 dual-tagged tests, 0 tags pointing at non-existent instances.**

### Coverage against the two design indices
- **Queue A (§1.8 difficulty): 22/22 instances tagged, 0 missing.**
- **Queue B (§1.9 corner): 46/48 real instances tagged, 2 missing.** The 49th `errors` entry is an `excluded_because:` stub and correctly not translated.

### Skipped instances (2) — both failed the PRD-first unique-derivability condition
1. `Corner/rbac/customer_can_read_its_own_contract_but_not_another_customers` — **condition (b)**. PRD §2.1 says a Customer "may read only those contracts whose offtaker is the acting customer" but names no error for the violation; SCAFFOLD conditions `ERR_UNAUTHORIZED` on "the acting role is not listed in the endpoint's roles", and the Customer role *is* admitted on `GET /power/ppas/{id}`. A PRD-only implementer can legitimately answer 404 `ERR_PPA_NOT_FOUND` (don't leak existence) instead of 403.
2. `Corner/calculations/unreversed_charge_recomputes_a_sibling_charge_downward` — **condition (b)**. The recipe's own setup (one line) contradicts its aspect ("one of three period lines"); it asserts `allocation_discount_pct`, which is not a declared SettlementLine field; and the literals 9051567.57 / 8946567.57 cannot be re-derived from §3.4's stated discount rule ("stored base allocation × non-reversed/total, capped at 0.35").

### PRD-vs-scaffold disagreements surfaced during generation (recipes adjusted, assertions kept PRD-faithful)
- `reconcile_cadence_slots == 0` (many_open_accruals recipe) contradicts §3.9's formula (contracts in PPA_ACTIVE/SUSPENDED − open accruals = 1 − 2 = **−1**). Assertion dropped.
- **Rollover count**: PRD names no response field for "the count it advanced" and SCAFFOLD's `OpsRunResult` is undefined → count assertion dropped; state-change assertions kept. PRD's `period_anchor_iso8601` is not a declared SettlementLine field, so the clock is advanced past the whole period to make the row eligible under either reading.
- **`MAX_ACTIVE_DEMANDS_PER_SITE` and `ACCRUAL_RECONCILE_SLA_DAYS` have no value in PRD or SCAFFOLD.** The demand-limit test walks the site up to the ceiling rather than hard-coding 5; the reconcile test advances the clock a full year before reconciling.
- **`fixed_consideration_cents == 0`** (site_evaluation recipe) depends on an unstated in-service-date cutoff for a site that *does* hold a contract → dropped; the 10800 / 47500 standby and exit figures kept.
- **Credit-ceiling setup**: the recipe's 60,000,000-cent accrual does not put `net_charge − output_guarantee_credit` above the 50,000,000 ceiling under the PRD's *second* (waterfall) `net_charge` definition (that reading lands at ~46.5M). Raised to 300,000,000 so the breach holds under both readings.
- **`site_registration_advances_draw_posture_without_an_ops_run`**: the recipe's setup leaves the site already `RESOURCE_DRAWING` from activation, making the transition unobservable. Used a contract-free site so the `RESOURCE_AVAILABLE → RESOURCE_DRAWING` edge is actually exercised.
- **`canceled_hold_returns_its_window_for_reuse`**: flagged as the weakest PRD derivation in the suite — the PRD overlap rule ("A delivery or resource hold occupies the closed interval … two such windows at the same site may never overlap") carries no terminal-state carve-out, while SCAFFOLD's validation says "every other **open hold window**". PRD-only basis is the cancellation-as-restoration framing in §2.6/§3.3. **Carried into Step 7 as a known deletion candidate.**
- **`revenue_variance_uses_the_forward_looking_index_basis`**: the instance name does not match its own recipe (which concerns the draft-vs-frozen pool basis); the recipe's rule (§3.5 "Which accruals a line sees depends on where the line sits") was implemented — verbatim PRD.

### Over-generation note
33 instances are currently covered by more than one test function (111 tests over 68 distinct instances). This is NOT the spec's "dual-tagged test" failure mode — each individual test carries exactly one tag — but it means several instances are asserted twice, sometimes with different fixture setups. Logged for the Step 7 reviewer; not blocking.

## Step 6: Generate implementation — 2026-10-01T09:24:00.000Z

Implementation complete and verified.

### Files written (`workspace/implementation/`, ~4,150 lines)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | guarded `pip install` (no-op once Flask imports) + `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 73 | Flask app, blueprint registration, envelope error handlers, clock tick |
| `middleware.py` | 88 | auth/role gate, `meta`/`response_type`/`data` envelope, internal-key stripper |
| `fields.py` | 90 | body extraction with deferred field-level errors |
| `errors.py` | 115 | 37 error ids + HTTP statuses from the catalog |
| `constants.py` | 276 | pinned constants, state vocabularies, 64-entry endpoint→roles map |
| `store.py` | 233 | in-memory collections, logical clock, pagination, insertion ordering |
| `calc.py` | 363 | money/rate rounding, escalation, reserves, site/customer/PPA recompute |
| `settle_calc.py` | 416 | line assembly, pools, remedies, allowances, valuation, portfolio readings |
| `transitions.py` | 433 | 8 state machines, cascades, deferred actions |
| `routes_sites.py` / `_customers.py` / `_ppas.py` / `_service.py` / `_deliveries.py` / `_settlement.py` / `_ops.py` | 205/156/306/208/401/651/120 | the 64 endpoints |

### Self-verification reported by the generator
- All 16 modules `ast.parse` clean; pyflakes shows only unused locals.
- Booted with `PORT=10128 bash start.sh` → `/health` 200, `GET /power/sites` 200, zero tracebacks.
- Two self-written suites (~110 calls) covering the full lifecycle (site→customer→PPA→activate→delivery→confirm→line→validate/approve/settle/reverse→allowance apply→reconcile→freeze/unfreeze→exit/cure/terminate/renew→transfer→batch ops) plus 40 error/boundary paths: **0 failures, 0 tracebacks**.
- Restart check: a site created before a kill is gone after re-launch; clock resets to `2026-09-01T00:00:00.000Z`.
- Route audit: 64/64 declared endpoints implemented, 64/64 have an auth role entry, no extras. No persistence, no seeding.

### PRD/SCAFFOLD ambiguities resolved by the generator
- **Unpinned constants** (named in PRD/SCAFFOLD, never valued): `INITIAL_FUEL_INVENTORY_THERMS=1e6`, `KW_PER_SQM=10`, `MIN_RESUME_DRAW_THERMS=1000`, `MAX_ACTIVE_DEMANDS_PER_SITE=5`, `MAINTENANCE_GAP_DAYS=7`, `MODULE_DISPATCH_HOLD_DAYS=7`, `MODULE_REPLACEMENT_REVERT_HOURS=24`, `SETTLEMENT_REVERSAL_WINDOW_DAYS=15`, `ACCRUAL_RECONCILE_SLA_DAYS=1`, `TRANSFER_TOKEN_GRANT=1`, `DAILY_KW_CHARGE_CENTS_PER_KW=1`, `CANDIDATE_PPA_DISTANCE_KM=0`. All documented in `constants.py`. **Note: `MAX_ACTIVE_DEMANDS_PER_SITE=5` and `ACCRUAL_RECONCILE_SLA_DAYS=1` were independently flagged by Step 5 as unpinned; Step 5's tests were written to walk up to the ceiling / advance the clock rather than hard-code these, so no collision.**
- **`purchase_price_cents_per_kwh`** (no value anywhere): read as `effective_tariff / term_years`, so `fixed_purchase_cents` is one month of energy at the contracted annual output. The literal "purchase price = tariff" reading makes `fixed_purchase` ~100× the energy leg and trips `ERR_BUMPER_EXCEEDED` on the first ordinary settle.
- **`net_charge_cents` has two conflicting formulas** (`forward_looking_net_charge_basis` four-pool sum vs `recurring_base_charge_pools` waterfall). Took the four-pool sum — its components are all declared `SettlementLine` fields; the waterfall's intermediates are not.
- **`capacity_guarantee_reserve_cents`**: entity description (shortfall × penalty) vs stop-loss calc (pre − credits). Took pre − credits per PRD §2.9.
- **`current_avoided_fuel_cost_cents_per_therm`**: took PRD §3.1's `min(rate, gas×1.25)` ceiling over the scaffold's plain "most recent confirmed rate".
- **Delivery pricing basis**: scheduled/in-transit price the index leg off the site's current gas index, confirmed/settled read their own frozen index — so the same delivery prices differently before and after confirm (PRD §3.3).
- **True-up**: strict pre-write snapshot (`reversed_count > open_count`, not counting the reversal in flight), per PRD §3.4.
- **Renewal** requires `active_ppa_count >= 1`, so renewing a terminated contract needs another live contract for that customer (PRD §3.8).
- **Exit-fee/standby capacity** sums `contracted_kw` over *all* the site's contracts (terminated ones leave equipment behind).
- **Deferred exit-termination** is armed but left to the explicit `POST /terminate` (auto-firing would pre-empt the endpoint's own precondition); the module-replacement revert and maintenance-window open/close do fire on the clock tick.
- **Ordering ties** break on an insertion counter (`_seq`, stripped from responses), never on `id`, because the frozen logical clock makes `created_at` ties the norm.
- Uncatalogued preconditions mapped to the nearest catalogued error (e.g. exit with fuel in motion → `ERR_INVALID_STATE` 409; empty cap-side pool at validate → `ERR_NO_ELIGIBLE_ACCRUAL` 422).

### Orchestrator verification (independent of subagent report)
- 16 Python files present; `ast.parse` over all → **0 syntax errors**.
- Persistence/seeding scan (`sqlite|pickle|json.dump|/tmp/|open(...,'w')|.write(`) → **no hits**; storage is in-memory only, no startup seeding.
- Independent boot: `PORT=10241 timeout 60 bash start.sh` → `/health` returned **200**; `GET /power/sites` without role headers returned **401 `ERR_UNAUTHENTICATED`** with the documented envelope (`meta.api_request_id`, `api_request_timestamp`, `response_type`, `data`), confirming both the boot contract and the auth gate. Logical clock reads `2026-09-01T00:00:00.000Z`.
- `start.sh` matches the INSTRUCTION.md contract: reads `$PORT`, `exec`s the server in the foreground, and guards the `pip install` so per-test-server reboots don't contend with concurrent sweep rounds.
- Killed only the PID I started (port 10241); no broad kill patterns used.

## Step 7: Run tests and iterate — 2026-10-01T09:57:00.000Z

All 8 rounds of the final sweep are clean (109/109 in every round), and no source file was written after the sweep started.

### Summary

**Iterations run:** 2 eight-round parallel sweeps. Sweep 1: 51/111 with 60 tests failing in all 8 rounds (deterministic). Sweep 2 (after fixes): **109/109 in all 8 rounds**, zero flakiness.

**Tests deleted (2):**
1. `test_suite/test_06_boundary_precision.py::test_confirmation_exactly_at_the_gate_instant_is_still_too_early` — STEP 1b unique-derivability. PRD §2.6 says a delivery "may not be confirmed before its `confirm_after_iso8601` instant **has passed**" (strict), but §3.2 calls it "the instant **before which** the load may not be receipted" and §3.3 says a coordinator "may receipt an in-transit load **only once** the logical clock **has reached**" it (both non-strict). At exactly the gate instant the readings diverge, so a PRD-faithful reader may legitimately admit the confirm. Scaffold rule that drove it: `boundary_precision_check/confirm_at_exact_window_open_returns_confirm_too_early`.
2. `test_suite/test_07_cross_entity_gates.py::test_transferring_a_contract_on_a_suspended_site_is_refused` — STEP 1a PRD silence. PRD names only two transfer refusals (credit tier, `transfer_stage == TRANSFER_BLOCKED`); nothing in §2.5's freeze cascade or §3.8 ever sets `TRANSFER_BLOCKED` on a freeze, and no sentence gates a transfer on site posture. Scaffold rule: `cross_entity_state_dependency/transfer_rejected_on_a_suspended_site`.

**`test_helpers/` fixes:**
- `factories.py::create_settlement_line_payload` — default period 2026-03-01→2026-04-01 → **2026-03-11→2026-04-11** (source deadline → 2026-03-25). The composite fixtures activate the contract at the logical clock instant (2026-03-10), so the old default violated PRD §3.4 ("`period_start` must not fall before the contract's `state_entered_at`"). Root cause of the 27-test `ERR_SETTLEMENT_PERIOD_BEFORE_ACTIVATION` cluster.
- `fixtures.py::setup_terminated_ppa` — gives the offtaker a second live contract at its own facility; PRD §3.8 admits a renewal offer only to a customer whose `active_ppa_count` is ≥ 1, so terminating the only contract made the offer illegal (3 tests).

**`test_suite/` fixes (all making tests more PRD-faithful):** periods moved after activation in test_01/05/08/22/24/26/27; test_02's scheduled-blend expectation corrected to PRD §3.3's "site's current `gas_commodity_rate_cents_per_therm` as its index leg"; test_05 refused-hold tests call the raw client instead of the raising fixture; plan creation asserted `201` (test_05/08) per PRD §4; unpinned `initial_fuel_inventory_therms` literals (100000/70000/60000/75000) replaced with the observed opening inventory in test_06/08/20/21/23/24/26; test_20 uses a role PRD §4 admits on `GET /power/customers/{id}/ppas`; test_21 gained the missing `create_site`/`issue_allowance` imports (7 `NameError`s) and drives approve/reverse as `SettlementApprover`; test_09 asserts a true-up is not a cap-side accrual type (PRD §3.5); test_10/22/28 create the settlement line the allowance cap is read against (PRD §3.6); test_22 asserts the §3.5 relation (0.60 × `capacity_guarantee_reserve_cents`) instead of a literal built from a conflicting definition; test_06 no longer asserts an error id for the empty-pool validate gate (PRD names none); test_21 no longer asserts a draft contract's `exit_fee_cents` default (PRD silent); test_01's maintenance-window test rebuilt on the derivable path (plan created while the contract is a draft, then activated) and its input tuned (accrual 100020) so the per-part and once-rounded sums actually differ.

**`implementation/` fixes (3, each traceable to verbatim PRD):**
- `transitions.py::cure` — `exit_fee_cents = 0` now lands **after** `calc.recompute_ppa()`, which was overwriting the reset (§3.8 "its `exit_fee_cents` is reset to zero").
- `transitions.py::activate` — every `SERVICE_PLAN_DRAFT` plan of the contract now rides the DRAFT→SERVICE_ACTIVE edge, not just the one the cascade creates (§3.7 "A plan moves from `SERVICE_PLAN_DRAFT` to `SERVICE_ACTIVE` when its contract enters `PPA_ACTIVE` in the same transaction").
- `transitions.py::process_deferred` (window entry) — recomputes the parent contract's derived fields and touches it (§3.7 "it recomputes the parent contract's `effective_tariff_cents_per_kwh` and `availability_penalty_cents_per_kwh`"; §2.4 "a recomputation of a derived field ... advances `version`").

No implementation check, endpoint, field or side effect was added beyond these; no persistence or seeding was introduced.

**Note for future runs:** `test_27::test_a_resource_created_before_any_clock_call_carries_the_startup_instant` and `test_23::test_a_create_carrying_no_identity_is_refused_before_the_authorization_check` fail only when the suite is run against one long-lived server (they depend on fresh-boot clock state / an empty collection). Both pass under the mandated `--isolation per-test-server`; ignore them in ad-hoc single-server runs.

### Orchestrator verification (independent of subagent report)
- **Sweep evidence present and clean:** all 8 `workspace/implementation/results.{1..8}.json` exist; each parses to `passed=109 total=109`.
- **No post-sweep writes:** the newest source mtime across `implementation/`, `test_suite/`, `test_helpers/` is 09:49:26 (`test_01`), strictly older than `results.1.json` at 09:53:05. `find … -newer results.1.json` returns empty. The sweep is therefore valid evidence for the current source tree.
- **Deleted tests confirmed gone:** `def test_confirmation_exactly_at_the_gate_instant_is_still_too_early` and `def test_transferring_a_contract_on_a_suspended_site_is_refused` are both absent. The two Design tags still appear in the same files, but on *sibling* tests — the over-generation noted in Step 5 means those instances had duplicate coverage, and only the offending duplicate was removed. Test count 111 → **109**, matching the sweep total.
- **Implementation fixes confirmed in source:** `transitions.py:266-270` calls `calc.recompute_ppa(ppa)` before assigning `ppa["exit_fee_cents"] = 0`; `transitions.py:119-126` walks sibling plans with `lifecycle_state == "SERVICE_PLAN_DRAFT"` onto `SERVICE_ACTIVE`; `transitions.py:437-442` calls `calc.recompute_ppa(ppa)` on the deferred window-entry path with the §3.7/§2.4 citations in comments.
- **`test_helpers` fixes confirmed in source:** `factories.py:159-169` carries the §3.4 citation with `period_start` `2026-03-11` and `customer_source_deadline_iso8601` `2026-03-25`; `fixtures.py:397-407` builds the documented "second, untouched live contract at its own facility" via `create_ppa(other_site["id"], ctx["customer_id"])`.

## Step 8: Finalize PRD — 2026-10-01T10:16:00.000Z

**Note on this entry.** The Step 8 subagent was killed when the launching session ended, so its summary report was never recorded. Per the "a lost subagent report ≠ a lost artifact" rule, the step was NOT blindly re-run: `workspace/PRD_FINALIZED.md` was inspected on disk, confirmed complete and non-trivial, and its edits were then verified against `implementation/` by the orchestrator. Findings below are orchestrator-verified, not subagent-reported.

### Artifact state
- `PRD.md` 1627 lines / 128,749 chars → `PRD_FINALIZED.md` **1645 lines / 130,515 chars** (+18 lines, +1,766 chars, ~1.4% delta). A minimal patch, as required.
- `diff -q` confirms the two files **differ** — this is not the silent-`cp`-only no-op failure mode.
- Section skeleton identical: both files have **25** `^#{1,3} ` headers, and `diff` of the header lists is empty → **no new sections were introduced**.
- File tail is the complete §5 error catalogue closing on `ERR_STALE_VERSION | 412 Precondition Failed` — **not truncated**.
- Patch size: 37 lines removed, 55 added.

### Orchestrator verification of the edits against `implementation/`

| PRD_FINALIZED claim | Implementation evidence | Verdict |
|---|---|---|
| Ties in `created_at` are ordered "by the order in which they were created, and never by their identifier" | `store.py:202` — `sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))`; `_seq` assigned at `store.py:109`. No sort anywhere keys on `id`. | ✓ |
| `MIN_RESUME_DRAW_THERMS` "which is 1,000 therms" | `constants.py:25` `MIN_RESUME_DRAW_THERMS = 1000.0` | ✓ |
| `MAX_ACTIVE_DEMANDS_PER_SITE` "which is 5" | `constants.py:26` `MAX_ACTIVE_DEMANDS_PER_SITE = 5` | ✓ |
| `MODULE_REPLACEMENT_REVERT_HOURS` "which is 24 hours" | `constants.py:31` `= 24` | ✓ |
| `MODULE_DISPATCH_HOLD_DAYS` "which is 7 days" | `constants.py:30` `= 7` | ✓ |
| Confirmation "at exactly that instant is admitted, and only an earlier one is refused" | `routes_deliveries.py:234` refuses on `store.clock() < parse_dt(confirm_after)`; at the exact instant the comparison is false, so the confirm is admitted. This is precisely the divergence that caused Step 7 to delete `test_confirmation_exactly_at_the_gate_instant_is_still_too_early`. | ✓ |
| Exit cure deadline "is not self-executing: no termination fires when it passes" | `transitions.py` `process_deferred` contains no `PPA_TERMINATED` write and no `PPA_EXIT_PENDING` auto-transition — its only contract-side action is `calc.recompute_ppa(ppa)` on window entry. Termination is reachable only via the explicit endpoint (`transitions.py:281-292`). | ✓ |
| (Step 7 fix) `cure()` recomputes before zeroing the exit fee | `transitions.py` `cure()` — `calc.recompute_ppa(ppa)` at body line 19, `ppa["exit_fee_cents"] = 0` at body line 23. | ✓ |
| Other unpinned constants (`INITIAL_FUEL_INVENTORY_THERMS`, `SETTLEMENT_REVERSAL_WINDOW_DAYS`, `ACCRUAL_RECONCILE_SLA_DAYS`) | `constants.py:23` `= 1000000.0`; `:34` `= 15`; `:35` `= 1` | ✓ |

No edit was found that mis-describes a code path outside its own subject; the patch pins values and semantics that the implementation genuinely exhibits.

## Step 9: Complete PRD — full PRD-vs-implementation scan — 2026-10-01T10:40:00.000Z

### Output
`workspace/PRD_COMPLETED.md` — source `workspace/PRD_FINALIZED.md`: 1,645 lines / 130,515 chars → `PRD_COMPLETED.md`: 1,801 lines / 143,963 chars (**+156 lines, +13,448 chars, +10.3%**), 49 diff hunks, **no new sections** (heading sets byte-identical), both tables (64 endpoint rows, 37 error rows) structurally unchanged.

Counts: **37 ambiguity-pins**, **30 mismatch-revisions** (some entries combine a revision with an inserted pin).

### Changes (PRD section — insert/revise — ambiguity|mismatch — what changed — impl ref)
- §2.2 — insert — ambiguity — internal `_`-prefixed keys never rendered in a response — middleware.py:30-36
- §2.3 — revise — ambiguity — negative `offset` served as 0; non-numeric limit/offset falls back to the default — store.py:216-225
- §2.4 — revise — ambiguity — site-first delivery listing also filters `selected_ppa_id`; contract-/customer-first listings take no filter — routes_deliveries.py:188-198,392-401
- §2.4 — insert — ambiguity — body-named `site_id`/`customer_id` resolve with ERR_SITE_NOT_FOUND/ERR_CUSTOMER_NOT_FOUND; body identifiers are read before resolution so 400 beats 404 — routes_ppas.py:58-62; routes_settlement.py:409-424
- §2.5 — insert — ambiguity — both freeze gates are ERR_INVALID_STATE 409 before `reason` is read — routes_sites.py:148-154
- §2.5 — insert — ambiguity — unfreeze's maintenance-window and RENEWAL_DECLINED gates are ERR_INVALID_STATE 409 — transitions.py:183-190
- §2.5 — revise — mismatch — no exit-fee acknowledgement exists; unfreeze restores RESOURCE_CLOSED unconditionally — transitions.py:215-216
- §2.6 — revise — ambiguity — settled deliveries count as confirmed; capped at gas×1.25, 4dp; "most recent" tie-break — calc.py:277-284
- §2.9 — revise — ambiguity — credits = CAPACITY_ALLOWANCE applied-as-time + every TRUEUP_ACCRUAL amount; avoided-cost allowances never draw — calc.py:163-174
- §2.9 — revise — mismatch — apply tests the projected figure (CAPACITY_ALLOWANCE only); settle tests the already-recorded figure — routes_settlement.py:585-591 vs 278-280
- §2.9 — revise — ambiguity — ceiling on apply tested against nominal `amount_cents` — routes_settlement.py:592-594
- §2.9 — insert — ambiguity — trigger code `EXPOSURE_HOLD_ARMED`; customer must be CUSTOMER_ACTIVE (409) — transitions.py:343-357
- §2.9 — insert — ambiguity — trigger code `EXPOSURE_HOLD_RELEASED`, plans restored, three 409 gates — transitions.py:372-395
- §2.10 — insert — ambiguity — deferred sweep runs before every request and right after the clock is set — app.py:37-41; routes_ops.py:116
- §2.10 — revise — mismatch — `monitoring_degraded_at` is never written, so the dispatch hold is computed but never armed — routes_service.py:59-66,128
- §3.1 — revise — mismatch — no in-service date or fixed-consideration cutoff; status always `IN_SERVICE` — routes_sites.py:124-125,137
- §3.1 — revise/insert — ambiguity — rate read from the site's earliest-created contract (0 if none); response echoes `site_id`/`site_version` — routes_sites.py:126-140
- §3.1 — insert — ambiguity — `committed_feedstock_therms`/`clearance_zone_used` carried to 4dp — calc.py:291-293
- §3.2 — revise — mismatch — `expected_net_low/high_cents` live on the settlement line, with formulas — settle_calc.py:140-141
- §3.2 — revise — mismatch — the draft-vs-live index leg is not implemented (dead `site_index_leg`); every contract prices on the site's declared gas index — calc.py:73-79; settle_calc.py:94
- §3.2 — insert — ambiguity — clearance re-test at activation; fixed gate evaluation order — routes_ppas.py:182-189
- §3.2 — insert — ambiguity — hand-created draft plans ride the activation edge — transitions.py:123-127
- §3.2 — revise — mismatch — adjust-contract netting (earliest applied line vs portfolio remainder), `commitment_swap_netting_cents`, no state gate, stored-efficiency test — routes_ppas.py:253-306
- §3.3 — revise — ambiguity — `sourcing_mode` optional; neither rule applies when unset — routes_deliveries.py:126,112-118
- §3.3 — revise — mismatch — actual gauntlet order (window pair → ceiling → draw → attesting → overlap → version → field defects → sourcing last) — routes_deliveries.py:138-154
- §3.3 — revise — mismatch — release names an explicit `delivery_id`; no implicit most-recent-hold selection; 404/409; returns the site — routes_deliveries.py:369-389
- §3.3 — revise — mismatch — "only these four edges" dropped; hold requires SITE_ACTIVE (409); cancel/release/terminate also restore the state — routes_deliveries.py:325-326,310-311,385-386; transitions.py:299-301
- §3.3 — insert — ambiguity — closed transit-cancellation gate is ERR_INVALID_STATE 409 — routes_deliveries.py:300-304
- §3.3 — insert — ambiguity — confirmation accruals' amounts, source line, anchor — routes_deliveries.py:261-286
- §3.3 — revise — mismatch — candidates ranked only at scheduling/hold; no-active-contract fallback; tie-break; allocated formulas; 4dp — routes_deliveries.py:42-77
- §3.3 — revise — ambiguity — a named `accrual_id` is reconciled directly; the three refusal codes — routes_settlement.py:477-494
- §3.3 — revise — mismatch — `lifetime_settle_reconcile_count` is derived from ACCRUAL_RECONCILED rows, not incremented — calc.py:302-304
- §3.4 — insert — ambiguity — `customer_source_deadline_iso8601` recorded but never read — routes_settlement.py:123,155
- §3.4 — insert — ambiguity — period checks precede the version comparison, which precedes remaining field defects — routes_settlement.py:127-146
- §3.4 — revise — mismatch — allocation limit is ordinal > consumed (PRD's "not strictly less than" would refuse every first line); no-allowance refusal 409; pool freeze — routes_settlement.py:247-264
- §3.4 — revise/insert — ambiguity — `applied_at`; only a CAPACITY_ALLOWANCE is consumed; the settled delivery — routes_settlement.py:285-313
- §3.4 — insert — ambiguity — reversal window reads `applied_at`; non-applied line is 409 — routes_settlement.py:331-337
- §3.4 — revise — mismatch — earned-token advance is max(1, the period's reversed count incl. this line) — routes_settlement.py:368-371
- §3.4 — revise — mismatch — one open true-up per contract, overwritten in place; reconciliations write none — routes_settlement.py:373-394,477-506
- §3.4 — revise — mismatch — rollover anchors on `period_end`, per-site pool, no post-pass, no fallback, `settled_cents`/`applied_at` — routes_ops.py:48-102
- §3.4 — revise — mismatch — term-end rebate is not computed; only `REBATE_CENTS`=0 in the buyer cost — calc.py:184 (dead); settle_calc.py:289
- §3.5 — insert — ambiguity — expected charge uses each line's own escalated rate — settle_calc.py:158-160
- §3.5 — revise — mismatch — HIGH_LOAD_TIER_1/2_MULTIPLE reached by no operation — constants.py:78-79 (dead)
- §3.5 — revise — mismatch — no forecast/unit counter-pool pair; what is actually published — settle_calc.py:213 (dead)
- §3.5 — revise — mismatch — waterfall intermediates not materialized; `net_charge_cents` does not depend on `allocation_basis` — settle_calc.py:104-136
- §3.6 — insert — ambiguity — open-accrual gate precedes the version comparison — routes_settlement.py:519-524
- §3.6 — revise — mismatch — apply branch keyed on the contract as a whole, plus the unbalanced/already-applied refusals — routes_settlement.py:573-609
- §3.6 — insert — ambiguity — target line is the contract's most recently created line — routes_settlement.py:576-577
- §3.6 — revise — mismatch — both allowance kinds compute days identically; divergence is only the hold counter and the reserve — settle_calc.py:223-245
- §3.7 — revise — ambiguity — gap test covers every non-archived window-declaring plan; start<end and boundary-pair rules; no contract-state gate — routes_service.py:40-56,97-120
- §3.7 — insert — ambiguity — the ERR_INVALID_STATE 409 refusals (stage/contract/plan/hold) — routes_service.py:171-181,196-202
- §3.7 — revise — mismatch — degraded instant never written, so `dispatch_hold` is never armed — routes_service.py:59-66,128
- §3.8 — insert — ambiguity — exit 409 refusals, `exit_deadline_iso8601`, exit-window collision test — routes_ppas.py:199-224; transitions.py:238-241
- §3.8 — revise — mismatch — extension machinery not implemented; cure's 409/409 gates — transitions.py:248-257; settle_calc.py:400 (dead)
- §3.8 — insert — ambiguity — termination before the deadline / not pending are 409 — transitions.py:277-286
- §3.8 — revise — ambiguity — offer reopens RENEWAL_DECLINED, three 409 gates, accept/decline is a CustomerService act — routes_customers.py:115-148; constants.py:222-223
- §3.8 — revise — ambiguity — renewal's 409/409 refusals and the archived plan's restoration — transitions.py:310-332
- §3.8 — revise — mismatch — `transfer_basis` optional and sets the resulting basis; unknown customer 404; `transfer_valuation` payload — routes_sites.py:167-205
- §3.8 — insert — mismatch — nothing sets `originating_ppa_id`, so the transferred-from listing is always empty — routes_ppas.py:160-167
- §3.8 — insert — ambiguity — `annual_customer_cost_cents` = annual kWh × effective tariff — calc.py:207-208
- §3.8 — insert — ambiguity — outage threshold governs the reported line items only, not the two costs — settle_calc.py:281-289
- §3.8 — revise — mismatch — valuation takes one shape not two; flag provenance corrected; field names listed — settle_calc.py:249-310
- §3.9 — revise — mismatch — billed energy over all applied lines; split between the earliest-created commitment and the rest; tie-break; commitments read at execution — settle_calc.py:372-397; routes_ops.py:85-89
- §3.9 — revise — mismatch — home-availability measure is not surfaced; its constants unreached — settle_calc.py:314 (dead)
- §3.9 — revise — mismatch — no third counter-pool aggregate is exposed — settle_calc.py:213 (dead)
- §3.9 — revise — mismatch — no net token figure or floor is stored or exposed — calc.py:342-347; constants.py:43 (dead)
- §5 — insert — ambiguity — three framework-level refusals whose status is not the catalogue's (404 unrouted, 405 method, 500 unexpected) — app.py:53-69

### The four mandated trap checks
1. **Dead code that PRD requires — FOUND, and it was the largest class.** Five helpers defined and never called: `calc.site_index_leg` (calc.py:73), `calc.contract_days_used` (calc.py:184), `settle_calc.forecast_band` (settle_calc.py:213), `settle_calc.home_availability_measure` (settle_calc.py:314), `settle_calc.extension_days` (settle_calc.py:400); plus `routes_settlement.write_trueup` (:75), a dead duplicate whose logic is inlined in `reverse_line`. Dead constants behind PRD claims: `HIGH_LOAD_TIER_1/2_MULTIPLE`, `AVAILABILITY_FALLBACK_PCT`, `SPECIAL_AGE_FALLBACK_PCT`, `TOKEN_FLOOR`, `FORECAST_WINDOW_DAYS`, `EXTENSION_DAYS_MAX`. Separately, `monitoring_degraded_at` is never written by any route, so `dispatch_hold` can never be true and both dispatch-hold refusals are unreachable. Each affected PRD claim was revised to say what the code actually does.
2. **Route-path normalization — CLEAN, no false alarms.** 64 endpoints in PRD §4 vs 64 Flask routes; after `<param>` → `{id}` normalization the sets are identical, and all 64 authorized-role lists match exactly. Blueprints are registered without a `url_prefix` (paths carry `/power` literally), so there was no decorator prefix to normalize.
3. **Assignment/ownership gate — N/A by design.** This task has no `ERR_NOT_ASSIGNED`-style gate; the only ownership rule is role-shaped (a `Customer` may read only its own contracts: middleware.py:85-88 plus the inline check at routes_ppas.py:155-156), which PRD §2.1 already describes correctly. No blanket rule was written.
4. **Create → 201 — CONFIRMED.** Exactly the 9 creating POSTs return 201 (sites, customers, ppas, service-plans, fuel-deliveries, resource-holds, settlement-lines, ppa-accruals, allowances); all 27 other operations return 200. PRD §4's convention statement matches; no other passage contradicts it.

Auxiliary cross-checks: the §5 error catalogue matches `errors.py` exactly (37 ids, identical statuses, every id raised somewhere, none raised that is uncatalogued); **no `implementation/` file was modified.**

### Orchestrator verification
- `diff -q PRD_FINALIZED.md PRD_COMPLETED.md` → **differs** (not the silent `cp`-only no-op failure mode).
- 1,801 lines / 143,963 chars; heading sets identical to PRD_FINALIZED.md → no new sections; file tail is the complete §5 table → not truncated.

## Final confirmation sweep (orchestrator-run) — 2026-10-01T10:42:00.000Z

Steps 8 and 9 rewrote only `workspace/*.md` files. Verified by mtime that **no file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` was written after the 09:53 sweep** (`find … -newer results.1.json` → empty), so the Step 7 evidence was already valid for the shipped tree. As additional insurance after this task's two session kills and four dead subagents, the orchestrator then **re-ran the full 8-round sweep itself** against the final tree:

```
results.1.json  passed=109 total=109  CLEAN
results.2.json  passed=109 total=109  CLEAN
results.3.json  passed=109 total=109  CLEAN
results.4.json  passed=109 total=109  CLEAN
results.5.json  passed=109 total=109  CLEAN
results.6.json  passed=109 total=109  CLEAN
results.7.json  passed=109 total=109  CLEAN
results.8.json  passed=109 total=109  CLEAN
```

**ALL 8 ROUNDS CLEAN** — 109/109 on the final source tree, confirmed by the orchestrator rather than reported by a subagent.
