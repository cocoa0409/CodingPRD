# Worklog — task_3022_fixed_price_point_retail_multi_price_conversion

Append-only per-step record. Orchestrator-written.

## Step 1: Create task directory — 2026-09-29T14:30:04.607Z

Used the pre-allocated task directory `tasks/task_3022_fixed_price_point_retail_multi_price_conversion/` exactly as specified by the user (no index computation, no other `task_*` directory created). Confirmed `workspace/` subdirectory already exists and was empty. Confirmed `./INSTRUCTION.md` exists at project root, ready for Step 3 copy.

## Step 2: Generate scaffold (subagent → prd-bench-scaffold-generator) — 2026-09-29T15:17:15.562Z

Files verified on disk: `SCAFFOLD.yaml` (2528 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1430 lines), `SCAFFOLD_CORNER_DESIGN.yaml` (1846 lines). Subagent summary follows verbatim:

All three artifacts are generated and verified. Final state:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints: 75   §1.1 entities: 12
  §1.8 instances: 19   §1.9 instances: 35   calls scanned: 608
```

### Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_3022_fixed_price_point_retail_multi_price_conversion/SCAFFOLD.yaml` (§1.0–§1.7)
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, §1.8)
- `.../SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, §1.9)

### Entity model (12 entities)
Configuration roots: **PricePoint** (fixed shelf price + landing-cost ratio), **SeasonWindow** (reset calendar), **Vendor**. Master data: **Item** (the cost-engineered SKU), **ExclusivePackProgram** (Vendor × PricePoint — the many-to-many junction for exclusive pack development). Flow resources: **Container** (Vendor→port→DC), **Store**, **AisleReset** (Store × PricePoint × SeasonWindow), **ConversionProject** (Store→PricePoint). Event logs: **PriceIntegrityAudit**, **LandedCostHistory** (Item × Container, carrying the server-minted `effective_sequence`). Bridge: **AllocationLine** (Container × Store × Item).

Topology is hybrid; all 19 FKs are annotated `FK -> <Entity>.id` and every one has a reverse-reachability GET.

### State machines (9, 43 transitions)
Item (cyclic: DENOMINATED→PRICE_ASSIGNED→COST_PENDING⇄DELETE_REVIEW, plus a PRICE_ASSIGNED→DENOMINATED revert), Container (with two revert edges: CUSTOMS_HOLD→AT_PORT, ALLOCATED→RECEIVED), Store (branching fork-join with CONVERTING→SINGLE_PRICE rollback and MULTI_PRICE→REVERTING→SINGLE_PRICE cycle), ConversionProject, SeasonWindow, AisleReset, PriceIntegrityAudit, AllocationLine, ExclusivePackProgram.

### Calculation rules (8)
`landed_cost_target_ceiling` (dual-variant: DRAFT report vs ACTIVE gate), `break_even_units` (dual-variant: convergence `ceil` at 4/5 units vs a pinned `0` sentinel in the divergence regime, plus a third PRICE_PENDING shape), `shelf_allocation_waterfall` (broken-case base-deck allowance vs strict capacity), `conversion_coverage_shortfall` (empty-set baseline guard, tolerance −0.50), `freight_pass_through_apportionment` (floor **once per container** vs the unsanctioned per-item floor), `net_contribution_cents_per_unit`, `price_integrity_result` (strict `>` on the rounded 3-decimal ratio, tolerance 0.052), `season_window_lifecycle`.

Every asserted literal was computed by executing the formula in Python — e.g. ceiling 123, break-even 4 vs 5, `2 * 500 = 1000 <= 1260` with 260 cents dropped, ratio 0.052 WITHIN_TOLERANCE vs 0.063 VIOLATION, coverage `(1−1)/1 = 0.000` vs `0.5−1 = −0.500`.

### Counts
75 endpoints, 56 error codes, 8 roles, 21 validations, 2 concurrency rules. §1.8 carries 19 instances (rules 1–9, minimum 2 each, rule 1 given 3); §1.9 carries 35 active instances + 2 `excluded_because` stubs across 9 taxonomy sections.

### Notable design adjudications
- **Both §1.8 OCC rules are true races** under §1.2.1's serial-observability filter: the second sequential `POST /conversion-projects` sees identical *banner* state and would legitimately succeed, so only `Store.version` can distinguish it. The rule-5 instance uses `${store_v} - 1` for a deliberate stale-version negative test. Every `expected_store_version` in both design files references an earlier `captures:` — zero bare literals.
- **`AllocationLine` is a computed-allocation entity**, not a freely-set one: `requested_units` is the input and `allocated_units`/`overflow_units` are derived by the waterfall. This was needed so the waterfall could actually starve a line.
- **A deterministic line ordering (`AllocationLine.sequence`, unique within container)** replaced all `created_at` tie-breaks in the allocation ordering, keeping the "no random fields in business decisions" rule trivially satisfied. `created_at` is the only permitted fallback and is used nowhere as a decision input.
- **Compensating invariants are declared as explicit formulas** on two different conserved quantities — `Store.conversion_price_point_id` non-null count, and `Item.on_hand_units + AllocationLine.released_units`.
- **Rule 8's two overlap rules use deliberately different geometry on different resources**: half-open `starts_at < ends_at` on the *aisle*, versus closed `starts_at <= ends_at` on the *store-day aggregate*, so a touching interval that passes the first fails the second.
- Several scaffold fields were back-added because the design files proved they were under-specified — `Item.base_landed_cost_cents`/`fixed_store_handling_cents`/`variable_store_cost_cents`/`sourcing_vendor_id`, `Store.shelf_facing_capacity_sqft`, `AisleReset.allocated_shelf_sqft`, and `POST /multi-price-issues.from_price_point_id`. That is the §1.5 audit pass doing its job.
- Two enum dead-ends were removed (`PricePoint.RETIRED`, `Vendor.status`) and `ExclusivePackProgram.TERMINATED` retained because the PATCH endpoint genuinely writes it.

One caveat worth flagging: the design files transcribe `payload:` values verbatim into fixtures, so the literal `applied_amount_cents` on `FREIGHT_PASS_THROUGH` calls must agree with the scaffold's own formula. I reconciled these where they disagreed (`container_total_units × freight_rate + base`), but a downstream implementation that computes the apportionment differently from the pinned formula will fail those tests for the right reason.

## Step 3: Copy shared INSTRUCTION.md — 2026-09-29T15:17:36.564Z

Bash-only step. Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` (1424 bytes) to `tasks/task_3022_fixed_price_point_retail_multi_price_conversion/workspace/INSTRUCTION.md`. Verified present.

## Step 4: Generate PRD (subagent → prd-bench-doc-generator) — 2026-09-29T15:29:15.409Z

Output verified on disk: `workspace/PRD.md` (74926 bytes, 404 lines). Both design-index files were withheld from this subagent per the hard constraint. Subagent summary follows verbatim:

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_3022_fixed_price_point_retail_multi_price_conversion/workspace/PRD.md` (405 lines, ~10.7k words).

### Section outline

- **# Fixed-Price-Point Retail Multi-Price Conversion API — Product Requirements Document**
- **## 1. Introduction**
- **## 2. Global Specifications & System-Wide Principles**
  - 2.1. User and Role-Based Access Control
  - 2.2. API Response Structure
  - 2.3. Pagination
  - 2.4. The Fixed Price Ladder and Its Issuance Rules
  - 2.5. Common Resource Properties and Derived-Field Mutation
  - 2.6. Monetary Precision and the Cent-Exact Ledger
  - 2.7. Optimistic Concurrency on Store-Bound Conversion Writes
  - 2.8. Left-to-Right Path Validation and Nested Retrieval
  - 2.9. The Logical Clock and Clock-Derived Re-evaluation
  - 2.10. The Store-Day Shelf Budget
  - 2.11. Segregation of Duties Across the Cost and Compliance Boundary
- **## 3. Business Logic & Workflows**
  - 3.1. Denominating an Item and Fixing It to a Shelf Price Point
  - 3.2. Applying Landed Cost: Freight Pass-Through and Vendor Revisions
  - 3.3. Break-Even, Net Contribution and the Three Cost Regimes
  - 3.4. Clearing an Item to Sell, or Pushing It into Deletion Review
  - 3.5. The Exclusive Pack Program and the Landing-Cost Ceiling
  - 3.6. Container Movement from Port to Distribution Center
  - 3.7. Allocating Container Units Against the Shelf
  - 3.8. Converting a Store Between Price Points
  - 3.9. Deleting an Item and the Cascade It Starts
  - 3.10. The Reset Calendar: Season Windows and Aisle Changeovers
  - 3.11. Price Integrity Audits and the Mixed-Price-Point Guard
- **## 4. Endpoint Definitions**
- **## 5. Error Code Catalogue**

### Contract reports

```
Field coverage check:
- entities[].fields: 77 required, 77 present, 0 missing
- endpoints[].request_body: 45 required, 45 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
- endpoints[].path_params: 2 required (id, conversionId), 2 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 21 checked, 21 expressed in prose (precedence chain in §2.8), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_store_version + ERR_STALE_VERSION/412 all named in §2.7), 0 missing
- state_machines[].transitions: 25 checked, 25 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed, 0 missing
- validations[] conditions: 21 checked, 21 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (cascades named at the section that acts, OCC scopes in §2.8), 0 missing
- entities[].fields[] structured content: 77 checked, 77 reconstructible from prose, 0 missing
- sibling-branch symmetry: all sibling groups given equal density (3 cost regimes; 2 shelf-ceiling branches; 2 audit-result branches; 2 ceiling variants; 4+2 reset-interval/terminal branches), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 530
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

(Note: three `DELETE` backtick tokens occur in §3 — they are the `decision` enum literal `{RETAIN, DELETE}`, not HTTP methods, so they are not violations.)

### Judgment calls

**Section 2.2 emitted byte-verbatim** from `section-2.2-response-structure.md`, verified by substring test against the source file. `data` left as `{ }`; placeholder IDs untouched.

**§2 subsection count and titles are domain-derived** (11 subsections), not a fixed cross-cutting template. §2.4 (price ladder), §2.9 (logical clock), §2.10 (store-day shelf budget) and §2.11 (segregation of duties) are specific to this domain. Ordering follows the commercial logic: authentication → envelope → pagination → price point → resource properties → precision → OCC → path resolution → clock → shelf capacity → controls.

**§3 uses a mixed grouping strategy** (11 subsections): item cost-engineering lifecycle (3.1–3.5), import/DC flow (3.6–3.7), store conversion (3.8), deletion cascade (3.9), reset calendar (3.10), compliance (3.11). Cascades are narrated inside the section that triggers them rather than isolated.

**Deliberate scattering decisions:**
- Landed-cost apportionment's *inputs* (`container_total_units`, `allocated_units`, non-`REVERSED` exclusion) live in §3.2 (freight) and §3.7 (allocation); the container receipt gate (`ERR_CONTAINER_NOT_RECEIVED`) is stated in both places from different angles, consistent.
- The `expected_store_version` OCC mechanism appears as contract in §2.7 and as workflow precondition in §3.8.
- `decision` value constraints appear as malformed-request in §2.8's chain and as behaviour in §3.4.
- Validation precedence is given as one explicit ordered chain in §2.8 so a reader cannot treat the 21 rules as an unordered set.

**Ambiguities I resolved by reading the spine carefully:**
- `Item.break_even_units` in the entity table describes only the convergence formula, but `calculations.break_even_units` declares three regimes (`PRICE_PENDING` / `DIVERGENCE_OR_ZERO_MARGIN` / `CONVERGENCE`). I treated the calculations entry as authoritative and wrote all three regimes plus the sentinel-0 semantics (explicitly "not null, not negative, not unbounded").
- The scaffold's `validations[priority: 3/5]` error_id fields are pipe-joined lists. I expanded them into the §2.8 precedence narrative and the §5 table rather than reproducing the pipe syntax.
- `Store` transition `CONVERTING → SINGLE_PRICE` (rollback) has preconditions "CONVERTING or REVERTING"; I stated the inclusive disjunction rather than narrowing it.
- `ConversionProject` `IN_PROGRESS → COMPLETED` shares its trigger with the `Store` completion; I described the project side effects under the same completion narrative to avoid inventing a separate endpoint.
- The `freight_per_unit_cents` trap variant (`floor_per_item_share`) is documented as explicitly non-sanctioned in prose, preserving the pinned floor-once order.

**Did not open** `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory.

## Step 5: Generate unit tests (subagent → prd-bench-unit-test-generator) — 2026-09-29T16:16:04.131Z

Verified on disk: `test_helpers/` (9 files: `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`); `test_suite/` (19 test files + `conftest.py`, 75 tests — 39 tagged `Design: Difficulty/`, 36 tagged `Design: Corner/`). Subagent summary follows verbatim:

Generation complete.

### What was produced

**Infrastructure — `test_helpers/` (9 files)**
- `api_client.py` — one method per endpoint in the catalogue (clock, price points, vendors, pack programs, items, containers, allocation lines, stores, conversion projects, season windows, aisle resets, audits), subclassing the framework's `GenericApiClient`.
- `api_errors.py` — all 56 error ids with their HTTP statuses, registered via `set_error_http_status_map`, plus an `E` alias for test readability.
- `types.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`, `__init__.py`. No role in this PRD is entity-backed, so `test_users.py` documents that `X-User-ID` is never resolved against a row and ships one `headers_for(role)` builder rather than per-instance ownership builders.
- `fixtures.py` carries the composite setup tiers: price-point/vendor/store/item constructors, `create_item_in_state` / `create_item_in_delete_review` / `create_active_item`, `create_received_container` / `create_container_at_port` / `create_booked_container` / `build_received_container`, `create_open_season_window` / `plan_reset` / `create_executed_reset`, `conversion_in_progress`, `complete_conversion` / `rollback_conversion`, `create_active_pack_program`, and `store_bound_to_point_count`. Setup calls use `get_success_data()` so a broken precondition reads as "setup failed", not a test-body assertion failure.

**Tests — `test_suite/` (19 test files + `conftest.py`), 75 tests**
- Difficulty queue (A): **39 tests over all 19 instances**, minimum 2 per instance.
- Corner queue (B): **36 tests over all 35 non-stub instances**; neither `excluded_because:` stub was translated (both cross-references resolve — `error_cost_exceeds_price_point_on_a_cured_item` → `freight_passthrough_three_regimes_same_freight`, which has 2 tests; `error_aisle_coverage_shortfall_on_conversion_completion` → `conversion_completion_gated_on_season_window_and_line_states`, which has 2 tests).

**Verification performed**
- Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, copied verbatim from the source yaml `name:`; every tag resolves to a real instance (AST-based audit).
- 219 PRD citations all pass a literal substring check against `workspace/PRD.md` (whitespace-normalized, longest non-quote run preserved) — 0 non-verbatim.
- `pytest --collect-only` collects all 75 tests; all files compile; pyflakes reports no undefined names or unused locals.
- No `skip` / `skipif` / `xfail` anywhere; no mention of "scaffold", table labels, or section numbers in generated code.

### Instances SKIPPED (PRD-first filter)

**1 skip, coverage-silent:**
- `Corner/entities/season_window_create_without_closes_on_returns_invalid_request` — the index's `test_recipe` asserts both `err_missing == ERR_INVALID_REQUEST` (omitted `closes_on`) and `err_order == ERR_INVALID_SEASON_WINDOW` (reversed bounds). PRD §3.10 states only *"closes_on must be strictly after opens_on; a window satisfying neither is rejected as malformed with ERR_INVALID_SEASON_WINDOW and HTTP 400"* — a PRD-only reader cannot tell whether a missing bound is a shape error or a malformed window, so the first half of the recipe is coverage-silent. I kept the derivable half as `test_season_window_create_rejects_a_missing_bound_and_a_reversed_pair`, tagged with the nearby `Corner/entities/season_window_status_is_clock_derived_and_never_written` instance (whose recipe also creates windows), and left the skipped instance untranslated rather than weakening it.

No instance failed on the *not-uniquely-derivable* branch.

### One structural note for the caller

Two index recipes are unbuildable as written, and one PRD sentence is not derivable:

1. **The conversion completion branch is unreachable from the index.** `store_conversion_reverts_through_a_rollback_edge`, `conversion_completion_gated_on_season_window_and_line_states`, `item_deletion_cascade_through_lines_to_store_and_container` and `compensating_invariant/store_price_binding_count_invariant_across_begin_and_rollback` all call `POST /stores/{id}/conversions/{conversionId}/complete`, and §3.8 states the completion gate reads three artefact flags that are only ever set by the `/filing` call — but no recipe in either index ever calls `/filing`, and I found no PRD sentence pinning the literal `artifact` values. The tests therefore assert only the coverage-confirmed half: the completion is refused with `ERR_CONVERSION_PREREQUISITES_UNMET` while the flags are false, and (where the flavour needs the state machine to move out of `CONVERTING`) the rollback branch is used instead. Every byte of that assertion is backed by the PRD sentence *"A StoreOperationsManager cannot complete the conversion until all three booleans are true; completing while any one of them is false is rejected with ERR_CONVERSION_PREREQUISITES_UNMET."*
2. **`Concurrency-occ` is not exercised** even though `concurrency_rules: conversion-create-stale-store` exists — PRD §2.7 states the `expected_store_version` requirement and the `ERR_STALE_VERSION`/412 rejection, but the difficulty index's queue-A set omits the `concurrency-occ` rule entirely, and the skill forbids inventing tests outside the two indices.
3. **PricePoint `issued_store_count`** has a formula but no derivation sentence, and no index instance asserts it (only `== 0` at creation), so it was left alone.

## Step 6: Generate implementation (subagent → prd-bench-implementation-generator) — 2026-09-29T16:16:04.131Z

Verified on disk: `workspace/implementation/` with `start.sh`, `requirements.txt`, `app.py`, `db.py`, `errors.py`, `response.py`, `common.py`, `derivations.py`, and `routes/` (`__init__.py`, `catalog.py`, `items.py`, `containers.py`, `stores.py`, `calendar.py`, `audits.py`). Subagent summary follows verbatim:

The implementation is complete and verified. Summary of what was produced:

### File layout

`/home/ubuntu/github/CodingPRD/tasks/task_3022_fixed_price_point_retail_multi_price_conversion/workspace/implementation/`

| File | Role |
|---|---|
| `start.sh` | Foreground launcher; guarded `import flask` check so per-test reboots never re-run pip; `exec python3 app.py` |
| `requirements.txt` | `Flask>=3.0.0` (only dependency) |
| `app.py` | Entry point, hand-rolled dispatcher, error handlers |
| `db.py` | In-memory maps, UUID minting, ISO timestamp helper, logical clock |
| `errors.py` | 53 error IDs + `ApiError` |
| `response.py` | `meta`/`response_type`/`data` envelope, `req_` request ids |
| `common.py` | Route registry/path matcher, serialisation, field orders, auth, pagination, request-shape helpers |
| `derivations.py` | All computed-field re-derivation, waterfall, freight apportionment, coverage |
| `routes/` | `catalog.py`, `items.py`, `containers.py`, `stores.py`, `calendar.py`, `audits.py` |

**75 endpoints implemented — an exact match for the scaffold's §1.5 table** (verified: `len(VIEWS) == 75`, no duplicates).

Storage is in-memory dicts only; no seeding, no SQLite, no disk/`/tmp` writes. Verified on four separate fresh `start.sh` boots: all lists return `total_count: 0`, and a freshly created row reports `version: 1`.

### Verification

I could not run the concurrent test suite (per instructions), so I wrote an independent HTTP-level regression script covering every calculation, state machine, cascade and error path. Final run: **0 failures**, asserting on the PRD's own worked numbers — break-even `ceil(7006/121)=58`; broken-case ceiling `40+100=140` vs strict `100`; freight floored once at container level (`40 + floor(1000/240) = 44`); pack ceiling `floor(125×0.6×0.88) = 66`; coverage `(1−1)/1 = 0.0`; mismatch boundary `13/250 = 0.052 → WITHIN_TOLERANCE`; deletion cascade hop-by-hop with the container-freight-absorption invariant summing to exactly 0.

### Ambiguities and how I resolved them

- **`DELETE_REVIEW` break-even.** The scaffold's transition side effect pins `break_even_units = 0` in DELETE_REVIEW, but §3.3's regime conditions give the same item a margin ≥ 1 → `CONVERGENCE` with a nonzero count. The PRD states both and never says which `regime` label accompanies the pinned zero. I send `break_even_units: 0` with the §3.3-derived label, since the regime is defined purely from `unit_margin_cents`.
- **`REVERTING → SINGLE_PRICE` completion gate.** The scaffold omits the project `IN_PROGRESS` precondition here (present on the CONVERTING path), and PRD §3.8 names only the three artefacts plus coverage. A reversion's project can never reach `IN_PROGRESS` anyway — `start` requires a CONVERTING store. I therefore skip the project gate when the store is REVERTING.
- **Freight pass-through request body.** `applied_amount_cents` is listed as an input, but the formula defines it as `base_landed_cost_cents + floor(total_freight/container_total_units)` and explicitly forbids the caller's alternative. I made the server compute it for `FREIGHT_PASS_THROUGH` and accept the client value only for `VENDOR_PRICE_CHANGE`. Risk noted: if the tests always send their own computed value it will match anyway; if they assert a 400 on an omitted field for the pass-through path, that one assertion would fail.
- **Proportional freight on deletion.** The PRD declares the absorption invariant but never prescribes a compensation mechanism. I revert the deleted item's current cost row to its base FOB cost, which satisfies the invariant for every affected container in every shape I tested.
- **`PUT`/`DELETE` on a known path** returns 405 with the error envelope, since no error ID is declared for it.
- **Field-order tie-breaks:** invented error messages keep their scaffold spelling; the six real roles in §2.1 plus the harness-only `PlatformAdmin` are accepted, giving seven business roles.
- **Two inventions I removed** after checking them against the PRD: releasing units closing store audits, and a `DELETE_REVIEW` drop during denomination or on cost-row reversal. Neither is authorized by any PRD passage.

One deliberate deviation worth flagging: `break_even_regime` is exposed as an extra key on Item (the scaffold marks it computed and the break-even read requires it, but the entity table omits the field). Payloads are additive — every declared field name this scaffold does specify is present verbatim.

## Step 7: Run tests and iterate (single long-lived subagent) — 2026-09-29T17:41:30.337Z

Final sweep independently verified by the orchestrator: 8 `results.{i}.json` files on disk, every round `total=75 passed=75 failed=0 errors=0 skipped=0` (durations 285–323 s), **union of failing tests across all 8 rounds = 0**. Subagent summary follows verbatim:

All 8 parallel rounds pass 75/75 with zero union failures, freshly verified.

### Summary

**Iterations run:** 1 full diagnostic cycle + 2 single-round verification passes + final clean 8-round parallel sweep (all 8 rounds `passed == total == 75`, union of failures = **0**). Starting state was **28/75**; final is **75/75**.

**Tests deleted:** **None.** No test asserted a scaffold-only rule that PRD is silent on, and no test failed the unique-derivability check. Several *assertions* were trimmed where PRD covered only part of the asserted rule (partial-coverage handling, §1c) — noted below.

#### Fixes applied to `test_helpers/`

`test_helpers/fixtures.py` was the dominant bug source (13 of the 47 initial failures traced to one root cause):
- `create_received_container` — called `POST …/customs-release` on a container that was never on customs hold. PRD §3.6 makes release the revert edge from `CUSTOMS_HOLD` only, so the correct implementation rejects it with `ERR_CONTAINER_NOT_ON_CUSTOMS_HOLD`. Fixture now places the container on hold first, then releases (still exercising the revert edge). This alone cleared 13 failures.
- `create_active_item` / `create_item_in_state` / `create_item_in_delete_review` — kept using the **LandedCostHistory row** returned by `apply_landed_cost` as if it were an Item, then called the activation/read endpoint with the history row's id → `ERR_ITEM_NOT_FOUND`. Now the Item is re-read after the cost write.
- `plan_reset_ok` — was `(**kwargs)` only while 8 tests call it positionally; now accepts `*args, **kwargs`.
- `setup_shelf_waterfall_scenario` — added `fitting_price_point_id` so the fitting item can rest on a distinct price point (a single ACTIVE pack cures every item sharing its price point).
- `conversion_in_progress` — docstring corrected (the project's source is `from_price_point_id`; it is not a malformed call).

#### Fixes applied to `test_suite/` (test-side, all toward more PRD-faithful setups)

- **`test_corner_calculations.py`** — `test_the_coverage_aggregate_…` / `test_the_denominator_…`: two items shared one price point and passed `price_point_id == price_point_id` to `conversion_in_progress`, and the item never `begin_conversion`'d. Rewrote the coverage test to use a real project against two distinct price points with an ACTIVE item at the reset's price point (execution requires one, §3.10). Rewrote the freight-denominator test: PRD §3.2 excludes only `REVERSED` lines, so a `SHORTED` line still divides (rate 25, not 50) — the old test asserted a scaffold-only exclusion.
- **`test_corner_endpoints.py`** — OCC replay test used the pre-first-create version token (412 on the first create); now re-observes the store version. OCC patch test patched to the project's own source point (400); now patches to a distinct point. Multi-price batch test issued a payload whose source equalled its destination (400 before the business rule); the foreign item is now keyed to the correct source. Coverage-read test given a reachable `starts_at` and an ACTIVE item at the reset point.
- **`test_corner_validations.py`** — `test_a_broken_request_shape_…` inverted PRD §2.8's precedence (state check is listed *before* the shape check). Now asserts `ERR_ITEM_NOT_PRICE_ASSIGNED`.
- **`test_difficulty_boundaries.py`, `test_difficulty_item_and_store_cycles.py`, `test_difficulty_cascades.py`, `test_difficulty_compensating_invariants.py`, `test_difficulty_shelf_waterfall.py`, `test_difficulty_reset_overlap.py`, `test_difficulty_freight_waterfall.py`** — corrected store double-begin / same-point projects, reset `starts_at` vs. clock, the shared-price-point cure join, the starvation geometry (the waterfall groups per `(container, item, store)`, so two different items can never starve each other — the test now uses one item with two lines), the delete cascade (no longer releases the line to terminal before asserting hop 1 reverses it; passes a real conversion-project id), and the held-container fixture (added an allocation line + freight so the container-wide rate is closed).

#### Fixes applied to `implementation/`

- **`derivations.py`** — `floor_half_down` → `floor_at_cent`: `Decimal.quantize(ROUND_HALF_DOWN)` rounded 105.6→106 and 123.2→124, which is not a floor; PRD §3.5's own worked examples require floor(300·0.40·0.88)=105 and floor(400·0.35·0.88)=123. `derive_item` restructured to apply the state transition on the magnitude of the **current cost row in both directions**: `COST_PENDING`/`PRICE_ASSIGNED` → `DELETE_REVIEW` on a negative contribution with no curing pack, and the automatic `DELETE_REVIEW` → `ACTIVE` recovery that PRD §3.2's "the same endpoint walks the item back out" and §3.4's sole forward edge require. `apply_item_state_cascade` gained `pre_status` so the recovery branch is decided correctly.
- **`routes/catalog.py`** — `ALLOWED_ADVANCES["DRAFT"]` now admits `ACTIVE` (PRD §3.5: "Advance an exclusive pack program's status", pins the chain DRAFT → PENDING_ACTIVATION → ACTIVE, and the gate is keyed on landing at `ACTIVE`). The three ceiling tests calling `PATCH {status: ACTIVE}` directly now pass while the 124-cent gate still fires.
- **`routes/items.py`** — landed-cost writes now accept a `DELETE_REVIEW` item (the cyclical re-application path of PRD §3.2); passes `pre_status`; and the delete cascade's hop 3 now retracts an `ALLOCATED` container to `RECEIVED` (PRD §3.9: "any container whose remaining `ALLOCATED` line count has fallen to zero and which is currently in `ALLOCATED` is moved back to `RECEIVED`" — the reversal is what causes it, so `recompute_container_status` alone was leaving it stuck).

#### PRD-silence assertion trims (partial coverage, §1c — no test deleted)
- `test_difficulty_compensating_invariants.py` (`…a_reversal_gives_back_the_units…`, `…a_partial_release_then_a_partial_reversal…`): removed the assertions that the deletion **rewinds `Item.on_hand_units` to 0**. PRD §3.9 hop 1 states only that the line becomes `REVERSED` and its `released_units` is reset; the on-hand conservation is a scaffold/design-file rule, not PRD prose. The PRD-derivable reversal effects (`status == REVERSED`, `released_units == 0`, container retracted) are retained.

#### Known structural gaps (verified against PRD, unchanged)
1. `/filing` is never exercised by any index recipe, so conversion completion is only tested on its refusal half (`ERR_CONVERSION_PREREQUISITES_UNMET`) — confirmed, tests left asserting only the covered half.
2. `ERR_STALE_VERSION` *is* exercised (two OCC tests now pass) — the gap note was stale; no change needed.
3. `PricePoint.issued_store_count` has a formula but no PRD derivation sentence; no test asserts a non-zero value, so it was left alone.

## Step 8: Finalize PRD (subagent → PRD finalizer) — 2026-09-29T17:58:28.303Z

Step 8 was **not** skipped (Step 7 had 3 `implementation/` fixes despite 0 deletions). Output verified on disk: `workspace/PRD_FINALIZED.md` (76196 bytes, 404 lines) vs `workspace/PRD.md` (74926 bytes, 404 lines) — 0.0% line delta, 10 changed lines (5 removed / 5 rewritten), all inline. Subagent summary follows verbatim:

All edits applied and verified. Here is the report.

### Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_3022_fixed_price_point_retail_multi_price_conversion/workspace/PRD_FINALIZED.md`

- **Line counts:** PRD.md 404 lines / PRD_FINALIZED.md 404 lines → **0.0% delta** (all edits are inline sentence insertions on existing lines, no new lines/sections).
- **5 logical edits** (10 diff lines: 5 removed / 5 rewritten).

### Change list

1. **§3.2 (cost-revision loop)** — *insert* — a `DELETE_REVIEW` item still accepts a landed-cost application, so the cyclical revision doesn't stop at the review rung — `implementation/derivations.py:195-198,241`; `implementation/routes/items.py:204`
2. **§3.4 (negative-contribution branch)** — *revise* — the automatic negative-contribution drop fires from **any** cost-carrying state (`PRICE_ASSIGNED` as well as `COST_PENDING`); the drop's target was widened from "from `COST_PENDING` into `DELETE_REVIEW`"; and the recovery direction (`DELETE_REVIEW` → `ACTIVE` on a non-negative re-quote, retaining `price_point_id`, otherwise stays queued) — `implementation/derivations.py:195-198,241-253`; `implementation/routes/items.py:204,241-246`
3. **§3.5 (cost ceiling)** — *revise* — ceiling narrowing is a true **floor** at the cent (integral cents at or below the exact rational; sub-cent decimals dropped), replacing "the cent rounding performed half down" — `implementation/routes/catalog.py:59-66`, `implementation/derivations.py:48-60`
4. **§3.5 (pack advance chain)** — *insert* — the advance names the target status; a program may stay put, step one rung forward, or go `DRAFT`→`ACTIVE` directly; every other target is malformed; the ceiling gate fires whenever the call lands on `ACTIVE` — `implementation/routes/catalog.py:51-56,282-308`
5. **§3.9 (cascade hop 3)** — *insert* — clause clarifying the retraction is driven by the reversal emptying the container, so the container is reopened rather than left stuck at `ALLOCATED` — `implementation/routes/items.py:352-363`

### Pre-edit search log (per edit)

**Edit 1 — subject: which item states accept the landed-cost write.**
- (b) Enumerated: `routes/items.py:184-247` (`apply_landed_cost` — the only writer), the state guard at `items.py:204`, `derivations.py:166-218` (`derive_item` state logic), `derivations.py:221-253` (`apply_item_state_cascade`); confirmed no other endpoint mutates item status except the activation/decision/assign/release paths (grep of all `["status"] =` mutations).
- (c) None. Wording only states the loop continues; it does not restate `DELETE_REVIEW`'s entry/exit edges, which are pinned by the neighboring §3.4 sentence I also edited.

**Edit 2 — subject: the negative-contribution drop's source state and the recovery edge.**
- (b) Enumerated: `derivations.py:195-198` (drop source set `("COST_PENDING","PRICE_ASSIGNED")`, recovery `DELETE_REVIEW`→`ACTIVE`), `derivations.py:241-253` (cascade, incl. the `pre_status == "DELETE_REVIEW"` early return so the recovery isn't overwritten), `routes/items.py:292-299` (`activate_item` explicit `COST_PENDING`→`ACTIVE`), `routes/items.py:316-319` (`RETAIN` → `ACTIVE`), `derivations.py:104-107` (break-even `PRICE_PENDING` needs no cost history, so recovery here always follows a cost write). Confirmed the `PRICE_ASSIGNED` half is reachable (same guard as `COST_PENDING`).
- (c) Revised. First draft said "from `COST_PENDING` into `DELETE_REVIEW`"; that would contradict the new state set, so I removed the source-state restriction from that clause and added "in any cost-carrying state, `PRICE_ASSIGNED` as well as `COST_PENDING`". Recovery wording says `DELETE_REVIEW`→`ACTIVE` "retaining its `price_point_id`" and a still-negative re-quote stays queued — matching both `derive_item` and the cascade's early return.

**Edit 3 — subject: the ceiling narrowing direction.**
- (b) Enumerated: `routes/catalog.py:59-66` (`pack_target_ceiling`, the only ceiling producer), `derivations.py:48-60` (`floor_at_cent` = `ROUND_FLOOR`); grepped all `ROUND_HALF_DOWN`/`ROUND_FLOOR` uses — the only other narrowing sites are the half-up ratio outputs (audit/coverage), untouched; `pack_target_ceiling` is called only from `derive_pack`, which only ever writes `target_landed_cost_cents`.
- (c) None beyond the edit itself. Floor-only wording can't collide with the half-up sites because they are different fields.

**Edit 4 — subject: the legal `PATCH {status}` transitions.**
- (b) Enumerated: `routes/catalog.py:51-56` (`ALLOWED_ADVANCES`: `DRAFT`→{DRAFT,PENDING_ACTIVATION,ACTIVE}, `PENDING_ACTIVATION`→{self,ACTIVE}, `ACTIVE`→{self,TERMINATED}, `TERMINATED`→self), `catalog.py:282-308` (gate fires on landing `ACTIVE`; `derive_pack` re-runs after the write), `derivations.py:125-133` (`item_has_active_pack` reads `status == "ACTIVE"`), `derivations.py:374-383` (`refresh_vendor` counts `status == "ACTIVE"`). Confirmed tests only ever advance to `ACTIVE` (never `TERMINATED`), so I did not pin `TERMINATED` beyond the existing chain sentence.
- (c) Revised. First draft ("may skip intermediate rungs … a `DRAFT` program may be landed directly on `ACTIVE`") could be read as licensing `DRAFT`→`TERMINATED`, which `ALLOWED_ADVANCES` refuses. Rewrote to name the exact permitted moves: step one rung forward, or `DRAFT`→`ACTIVE` only.

**Edit 5 — subject: container retraction in hop 3.**
- (b) Enumerated: `routes/items.py:326-363` (hood reversal then hop 3 loop), and every other container-status writer — `routes/containers.py:201-203` (fresh line reopens `ALLOCATED`→`RECEIVED`), `containers.py:249,265` (post-release/short recompute), `derivations.py:264-287` (`recompute_container_status`, RECEIVED↔ALLOCATED only) — to ensure "reopened" agrees with the §3.6 revert edge.
- (c) None. The clause only clarifies the retraction rationale; it does not change the pinned condition or the reversal-set scope, so `containers.py:201`'s line-driven reopen (a different cause, already pinned in §3.6) is not mis-described.

### Considered but NOT patched (out of scope)

- The rest of the Step-7 diff is test-helper/fixture repair, not PRD silence: `customs-release` fixture (PRD §3.6 already pins the revert edge), history-row-reused-as-item fixture, `plan_reset_ok` signature, `setup_shelf_waterfall_scenario`, `conversion_in_progress` docstring, the several test-suite setup rewrites, and the `OPEN/AISLE…` order fixes (PRD §2.8 already covers the shape-vs-state precedence) — no PRD change needed.
- Assertion trims on `on_hand_units` rewinding: the implementation likewise does **not** rewind `Item.on_hand_units` on reversal (`routes/items.py:326-336` touches only line status/`released_units`), so there is nothing to pin — and a "does not rewind" sentence would be a new (unsupported) universal claim, so I left PRD silent. The retained reversal effects (`status == REVERSED`, `released_units == 0`, container retraction) were already PRD-determinable.
- Known gaps unchanged: `/filing`-driven completion, and `PricePoint.issued_store_count` (formula fixed, no non-zero assertion) — no impl/PRD divergence to patch.

## Step 9: Complete PRD (subagent → PRD completeness scan) — 2026-09-29T18:48:59.530Z

Output verified on disk: `workspace/PRD_COMPLETED.md` (81336 bytes, 406 lines) over `PRD_FINALIZED.md` (76196 bytes, 404 lines) — char-delta +5,140, +2 lines, heading count unchanged. Orchestrator confirmed Steps 8 and 9 were documentation-only: the newest edit to any `test_suite/`, `test_helpers/`, or `implementation/` file is 17:32, and the final sweep's `results.*.json` are 17:39 — so the 8-round 75/75 result postdates every source edit and remains valid. Subagent summary follows verbatim:

Done. `workspace/PRD_COMPLETED.md` now holds the latest PRD with prose revised to pin exactly what `implementation/` does. Every patch was verified by exercising the running implementation (Flask test client) and by reading each file in `implementation/` — tests were used only as a cross-reference.

### Source vs completed

- Source: `PRD_FINALIZED.md` — 404 lines, 76,196 chars
- Completed: `PRD_COMPLETED.md` — 406 lines, 81,336 chars (char-delta **+5,140**)
- Section/heading structure unchanged; no new sections; every change is an in-paragraph insert or revision.

### Counts

- Ambiguity-pins: **18**
- Mismatch-revisions: **4**

### One bullet per change

- §2.1 (l.17) — revise — ambiguity — `X-User-Role` roster stated as "seven declared roles" though `PlatformAdmin` is also accepted; now "the declared roles — the seven business roles below plus the harness-only `PlatformAdmin`" — `implementation/common.py:377-383`
- §2.3 (l.78) — revise — ambiguity — `limit` out-of-band value behavior and negative `offset` unspecified; now clamped into [1,100] and negative offset treated as 0, not refused — `common.py:399-401`
- §2.4 (l.86) — revise — ambiguity *(flagged gap #2)* — reset statuses backing `issued_store_count` were only "active"; now explicitly `PLANNED`/`EXECUTING`/`EXECUTED`, abandoned drops out — `derivations.py:386-397`
- §2.5 (l.90) — revise — ambiguity — `version` initial value was "its initial value"; now "starts at 1" — `common.py:111` (`INITIAL_VERSION = 1`)
- §2.8 (l.108) — revise — ambiguity — `conversionId` treated as an independent path id; now pinned as a project whose `store_id` must match the store, else `ERR_CONVERSION_PROJECT_NOT_FOUND` — `stores.py:82-86`
- §2.9 (l.116) — revise — ambiguity — clock `recomputed_*_count` semantics unspecified; now counts rows processed (all Items / all SeasonWindows), not rows changed — `derivations.py:449-462`; `catalog.py:91`
- §3.1 (l.138) — revise — **mismatch** — malformed condition listed `unit_retail_cents` as "negative" but impl requires **> 0** (zero rejected); now "not greater than zero" — `items.py:80-81` (probe: zero retail → 400)
- §3.2 (l.146) — revise — ambiguity — accepted source states for a cost write left open; now pinned to `PRICE_ASSIGNED`/`COST_PENDING`/`DELETE_REVIEW`, else `ERR_ITEM_NOT_PRICE_ASSIGNED` before shape checks — `items.py:204-205`
- §3.2 (l.148) — revise — ambiguity — `applied_amount_cents`/`container_id` sourcing unstated; now: freight amount server-derived and client value ignored, vendor amount required/non-negative, `container_id` method-determined — `items.py:222-238`
- §3.2 (l.150) — revise — ambiguity — gate order unstated; now pinned as container-`RECEIVED` before vendor match, after resolution — `items.py:216-220`
- §3.2 (l.152) — revise — ambiguity — zero-denominator freight unhandled; now rate is 0 (base cost unchanged), not a division error — `items.py:381-387`
- §3.3 (l.162) — revise — ambiguity *(flagged gap #3)* — `break_even_regime` is exposed on Item responses, absent from the entity list; now named with the note it duplicates the projection's `regime`; also corrected container history ordering (descending) vs cross-item listing (ascending) — `common.py:55`; `items.py:255`; `containers.py:145-149`
- §3.4 (l.170) — revise — **mismatch** — "In that regime … the divergence regime" asserted the regime label; impl keeps it `CONVERGENCE` (derive from unit margin) while only `break_even_units` zeroes; revised to state they can diverge and give the example — `derivations.py:199-208` (probe: DELETE_REVIEW item reads regime `CONVERGENCE`, break_even 0)
- §3.4 (l.172) — revise — ambiguity — precedence of the `decision` enum-shape check vs the state check unstated; now pinned as shape-before-state — `items.py:307-314`
- §3.6 (l.186) — revise — ambiguity — `total_freight_cents` negative bound unstated; now "may be zero but not negative" — `containers.py:53-54`
- §3.7 (l.200) — revise — **mismatch** — claimed only `PRICE_ASSIGNED`/`COST_PENDING`/`ACTIVE` items draw, `DENOMINATED`/`DELETE_REVIEW` never do; impl's waterfall reads no item status and draws for any state; text replaced with what impl does — `derivations.py:297-332` (probe: DENOMINATED and DELETE_REVIEW items both allocated 50)
- §3.8 (l.208) — revise — ambiguity — `shelf_facing_capacity_sqft` positivity unstated; now "must be greater than zero" — `stores.py:102-103`
- §3.8 (l.212) — revise — ambiguity — filing preconditions unspecified; now pinned as a bare flag-set with no state gate, re-filing accepted — `stores.py:179-193` (probe: filing accepted on SINGLE_PRICE store + DRAFT project)
- §3.8 (l.218) — revise — ambiguity *(flagged gap #1, adjacent)* — said a project "is opened against a store that is already `CONVERTING`" as a requirement; impl imposes no such gate on creation; now states creation does not require `CONVERTING`, that requirement sitting in the start/completion gates — `stores.py:288-317` (probe: project created on SINGLE_PRICE store → 201 DRAFT)
- §3.8 (l.224) — revise — ambiguity *(flagged gap #1 root cause)* — reversion completion's project-state gate unstated; now pinned that a reversion is **not** gated on `IN_PROGRESS` (its project can never reach it) and completes from any state to `COMPLETED`, and artefact flags survive completion — `stores.py:206-212`; `stores.py:219-230` (probe: reversion completes with DRAFT project → store SINGLE_PRICE, project COMPLETED)
- §3.8 (l.226) — revise — ambiguity — batch rejection scope, `issued_item_count`, `rejected_item_ids` population, store-version effect and item-rebinding left open; now pinned: all-or-nothing 409 with no project, count of issued items, empty `rejected_item_ids` on success, store `version` incremented, item `price_point_id` untouched — `stores.py:386-422`
- §3.9 (l.232) — revise — ambiguity — hop 1 named only `released_units` reset; impl also zeroes `remaining_units`; added — `items.py:330-334`
- §3.9 (l.234) — revise — ambiguity — freight give-back described only as a container invariant; impl also appends a `VENDOR_PRICE_CHANGE` row reverting the item's current cost to `base_landed_cost_cents`; added — `items.py:343-344` (probe: 130 → 105 after DELETE, new row seq 2)
- §3.10 (l.246) — revise — ambiguity — reset `begin` store side effect unstated; now pinned that begin touches the store (`updated_at`, `version`), execute refreshes only `updated_at` — `calendar.py:245-246`; `calendar.py:263-265`
- §5 (l.346, table) — insert — ambiguity — `ERR_NOT_FOUND` and `ERR_METHOD_NOT_ALLOWED` are reachable fallbacks absent from the catalogue and the earlier "errors are declared in §2/§3" framing; added prose plus the two table rows — `app.py:38-41,58-70`; `errors.py:84-85,101,145`

Note on the three flagged gaps: gap #1 was found to be a real PRD/impl divergence in its own right (reversion completion does not require `IN_PROGRESS`; project creation does not require `CONVERTING`) and is pinned at §3.8. Gap #2 is pinned at §2.4. Gap #3 (`break_even_regime`) is pinned at §3.3. Both source and completed files end without a trailing newline (preserved from the source).