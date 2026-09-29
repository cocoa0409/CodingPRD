# Worklog — task_2954_automated_grocery_fulfillment_center_operations

## Step 1: Create task directory — 2026-09-05T21:29:04.482Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2954_automated_grocery_fulfillment_center_operations/` and its `workspace/` subdirectory. Index 2954 was pre-assigned by the invoking pipeline (no auto-allocation scan performed, per instructions, because up to 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-05T23:32:42.897Z

All three scaffold artifacts are complete and lint-clean.

Lint verdict (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2954_automated_grocery_fulfillment_center_operations/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2954_automated_grocery_fulfillment_center_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2954_automated_grocery_fulfillment_center_operations/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     104
  Calls scanned (§1.8+§1.9):  1445

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Deliverables in `/home/ubuntu/github/CodingPRD/tasks/task_2954_automated_grocery_fulfillment_center_operations/`:

| file | lines | top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 3116 | scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, global_constants, calculations, validations, endpoints, errors, roles (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1916 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 7701 | `scaffold_corner_design` only |

Domain model: 15 flat peer entities (DeliveryRoute, DockBay, GridZone, MaintenanceWindow, PickStation, InventorySku, DeliverySlot, CustomerAccount, CustomerOrder, OrderLine, SlotBooking, DeliveryWave, Tote, PickTask, SubstitutionProposal), 10 cyclic state machines, 2 OCC concurrency rules, 13 calculations (2 dual-variant: catchweight line price, zone inventory accuracy), 33 priority-ordered validations, 65 endpoints, 53 error codes, 5 roles under `segregation_of_duties` (FulfillmentAdmin, WavePlanner, PickOperator, GridEngineer, Customer). Complexity layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy; consistency_model `immediate`.

Counts: §1.8 = 9 difficulty rules × 2 instances = 18. §1.9 = 120 instances across all nine guide sections (entities 51, state_machines 32, calculations 14, validations 9, endpoints 4, errors 1, rbac 3, complexity_layers 5, consistency_model 1), of which 104 are full test recipes and 16 are `excluded_because` stubs citing real `<rule_id> / <instance_name>` pairs in the difficulty file (verified programmatically; stubs carry no `test_recipe`).

Coverage-audit notes: all 53 error codes are triggered somewhere across the two design files (verified by census — zero untriggered); the auth ladder (401/401/403/403/403) and segregation of duties are discharged in the rbac section, ERR_STALE_VERSION in complexity_layers (one instance per §1.2.1 rule, each keeping `${...}` in the version field), and ERR_MAINTENANCE_WINDOW_OVERLAP / ERR_DOCK_BAY_CAPACITY_EXCEEDED / ERR_NO_TOTES_TO_CONSOLIDATE are §1.8-owned. Rows the scaffold makes non-applicable are documented in the corner file's header (Immutability — every entity has `common_fields: true`; hierarchical/graph/hybrid topology; Bubble-up; the nine undeclared complexity layers; the non-`immediate` consistency rows). `selector_policy` has no row in the guide's layer table, so it is emitted under its own declared layer name with a filter-before-rank + symmetric-price-tie instance. Instance names are unique across both design files; `.scratch/step2` removed.

**Orchestrator note (post-step fix):** the scaffold generator copied the difficulty directive line "Generate task harder than expert level!" verbatim into `SCAFFOLD.yaml`'s `scenario:` key. Since Step 4's doc generator reads `SCAFFOLD.yaml`, that line would have leaked into PRD.md. The orchestrator deleted the line (and its trailing blank line) from the `scenario:` block before Step 3; grep for "harder than expert"/"expert level" across all three scaffold files now returns nothing, and `SCAFFOLD.yaml` still parses with exactly the §1.0–§1.7 top-level keys and neither design key.

## Step 3: Copy shared files — 2026-09-05T23:33:04.257Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T23:51:22.338Z

All 15 entities are covered (either by the exact scaffold name or by its natural-language form, which is what the skill's §3 narrative style calls for). The PRD is complete and verified.

## Deliverable

`workspace/PRD.md` — **528 lines**, built with 1 `Write` + 12 heredoc appends, each verified with `wc -l` + `tail`. Ends cleanly at the last row of the §5 table; no audit footer, no contract reports written into the file. Scratch dir `.scratch/step4` was removed; the parent `.scratch` was left intact.

## Section list

1. Introduction
2. Global Specifications & System-Wide Principles — 2.1 RBAC · 2.2 API Response Structure (verbatim block) · 2.3 Pagination · 2.4 Common Resource Properties, Timestamps and Version Counters · 2.5 The Logical Clock · 2.6 Money, Weight and Rounding Discipline · 2.7 Stale-Version Guards on Basket and Line Writes · 2.8 Validation Precedence · 2.9 Conserved Quantities (slot capacity + SKU unit ledgers) · 2.10 Cold-Chain Segregation · 2.11 Wave Posture · 2.12 Independent Status Dimensions and Segregation of Duties (12 subsections)
3. Business Logic & Workflows — 3.1 The Standing Plant · 3.2 Baskets, Line Pricing and the Charge Waterfall · 3.3 Delivery Slots · 3.4 Wave Formation, Order Slotting and Dock Scheduling · 3.5 Robotic Grid Retrieval · 3.6 Shortages, Substitution Rounds and Customer Approval · 3.7 Consolidation, Loading Sequence, Transport Cost and Dispatch · 3.8 Grid Maintenance Windows and Inventory-Accuracy Audits · 3.9 Cancellation, Compensating Actions and the Waitlist Cascade (9 subsections)
4. Endpoint Definitions — 4-column table, 65 rows
5. Error Code Catalogue — 2-column table, 53 rows

## Coverage counts

Endpoints 65/65 · Entities 15/15 · State machines 10/10 (59/59 transitions) · Calculations 13/13 · Validations 33/33 (priority-numbered 1–33 in §2.8, including both deliberate collisions) · Errors 53/53 · Roles 5/5 · Concurrency rules 2/2 · Global constants all present.

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 100 required, 100 present, 0 missing
- endpoints[].request_body: 56 required, 56 present, 0 missing
- endpoints[].query_params: 23 required, 23 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 33 checked, 33 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_order_version / expected_order_line_version + ERR_STALE_VERSION 412 all named), 0 missing
- state_machines[].transitions: 59 checked, 59 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing
- validations[] conditions: 33 checked, 33 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 65 checked, 65 expressed, 0 missing
- entities[].fields[] structured content: 100 checked, 100 reconstructible from prose, 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 946
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Verbatim last 5 lines:

```
| `ERR_PROPOSAL_ALREADY_OPEN` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_WITHHELD_UNITS_EXCEEDED` | 422 |
| `ERR_SLOT_UNITS_EXCEED_CAPACITY` | 422 |
| `ERR_MINIMUM_ORDER_NOT_MET` | 422 |
```

Notes worth passing on: neither withheld design file was opened, and no sibling task directory was read. §2.2 was verified byte-identical to `section-2.2-response-structure.md`. One scaffold inconsistency surfaced — the order-cancel endpoint lists only `Customer` in `roles`, while the `CANCELLED` transitions also name `FulfillmentAdmin` as a permitted actor; §3.9 records the ownership rule for `Customer` and notes the administrator exemption, and the §4 row keeps the scaffold's role list.

**Orchestrator verification (truncation guard):** `wc -l` = 528; `tail -12` ends at the final `| ERR_MINIMUM_ORDER_NOT_MET | 422 |` table row, i.e. a real section boundary, not mid-sentence. Grep for "harder than expert", "expert level", "scaffold" and "test_recipe" over PRD.md returns zero hits, so the Step 2 difficulty directive did not reach the PRD. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-06T00:36:00.000Z

Step 5 complete. Everything is on disk at the task root and verified.

## Deliverables

**`test_helpers/`** (2,425 lines total)
`__init__.py` 21 · `api_client.py` 279 · `api_errors.py` 142 · `assertions.py` 516 · `constants.py` 86 · `factories.py` 276 · `fixtures.py` 655 · `test_users.py` 88 · `types.py` 362

**`test_suite/`** (11,079 lines, 173 tests)
`conftest.py` 57 · `test_01_plant_topology_and_catalogue.py` 1552/36 · `test_02_bookings_waves_and_reference_integrity.py` 696/13 · `test_03_slot_booking_lifecycle.py` 811/10 · `test_04_picking_floor_lifecycle.py` 523/9 · `test_05_grid_holds_and_substitution_rounds.py` 751/16 · `test_06_derived_figures_and_orderings.py` 1038/8 · `test_07_validation_precedence.py` 989/13 · `test_08_endpoint_surface_and_access_control.py` 939/9 · `test_09_optimistic_guards_and_immediate_consistency.py` 661/8 · `test_10_pricing_and_scoring_variants.py` 729/12 · `test_11_cycles_cascades_and_guard_precedence.py` 1265/20 · `test_12_boundaries_dependencies_and_conservation.py` 1068/19

## Coverage

- **173 tests. Queue A (Difficulty) 51, Queue B (Corner) 122.**
- Every test carries exactly one `Design:` line as the last docstring line. An AST audit against both indices found **zero** tag problems: no untagged, dual-tagged, dangling or stub-naming tests.
- All **18** difficulty instances have ≥2 tests each. **102 of 104** non-stub corner instances have ≥1 test. All **16** `excluded_because:` corner stubs skipped silently.
- No design instance was invented from `SCAFFOLD.yaml`: test count equals tag count equals instances covered plus the multi-test instances.

## Instances skipped by the PRD-first filter (2 — gaps left as gaps)

1. `Corner/entities/create_inventory_sku_zone_temperature_zone_mismatch_rejected` — the PRD states the rule ("a SKU cannot be registered into a zone of a different class") but assigns it no error id, and gate 14 scopes `ERR_TEMPERATURE_ZONE_MISMATCH` exclusively to `POST /pick-tasks/{taskId}/assign-tote`.
2. `Corner/entities/create_delivery_wave_second_wave_on_same_slot_rejected` — §3.4 states "at most one wave may ever exist for a given `delivery_slot_id`" verbatim but names no code. **I removed this test myself** after the writer had asserted `ERR_INVALID_REQUEST`: §2.8 gate 8's enumeration is closed and purely syntactic, and only `route_code` gets an explicit duplicate→`ERR_INVALID_REQUEST` mapping, so 422 vs 409 is not uniquely derivable. Removing it keeps the filter consistent with skip 1.

## Notable PRD-over-YAML adjudications (the PRD won in each case)

- `last_count_variance_units` is counted minus system, so a shrink is **negative** (three files had followed the YAML's positive literal).
- Order slotting advances `SLOTTED → WAVED`, not `SLOTTED` (test_04).
- A short line's `final_line_price_cents` stays **null** (test_11).
- The loading-sequence call advances totes `CONSOLIDATED → LOADED` (test_06).
- A **waitlisted** booking still runs the charge waterfall, so the order's fee/total are non-null (test_06) — the one place the suite could diverge from an implementation that read §3.2 literally.
- `actual_weight_grams` on a non-catchweight line and any unknown body field are refused with `ERR_INVALID_REQUEST` per gate 8, not silently ignored (test_07, test_01).
- Several writers rescaled slot capacities so utilisation stays inside one surge tier, because the PRD does not fix whether `surge_multiplier_at_booking` snapshots before or after the booking's own ledger effect — the derived cents are then unambiguous.

## Verification

- `python3 -m py_compile test_helpers/*.py test_suite/*.py` → **COMPILE_OK**.
- `pyflakes` over both directories → clean (no unused imports, no undefined names).
- `pytest --collect-only` → **173 tests collected**, no collection or import errors; no duplicate test function names in any file.
- Path check: both `test_helpers/` and `test_suite/` exist at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation`, `sweep.sh` — no strays. `__pycache__` removed.
- Nothing under `workspace/implementation/` was read or written, no sibling task dir was touched, `worklog.md` is untouched, and only `.scratch/step5` was deleted (`.scratch/step6` intact).

## Step 6: Generate implementation — 2026-09-06T00:41:00.000Z

Cleanup done and all verification passes. Final report:

## Deliverable
`workspace/implementation/`

| module | lines | role |
|---|---|---|
| `app.py` | 57 | `create_app()`, 5 blueprints, 3 error handlers, `PORT`/`0.0.0.0` entrypoint |
| `db.py` | 252 | constants, in-memory `Store` (15 dict tables), logical clock, instant parse/format, decimal helpers, snapshot-diff version bookkeeping |
| `errors.py` | 69 | all 53 error ids → HTTP status, `ApiError` |
| `response.py` | 133 | envelope/`meta` builder, error body, pagination + filtered listings |
| `middleware.py` | 83 | `endpoint(roles, mutating)` decorator = gates 1–4 under a global `RLock`, then reconcile + version finalize |
| `validation.py` | 223 | body reader, field descriptors, unknown-field rejection, declared-order shape checks, uniqueness, FK resolution |
| `routes/plant.py` | 327 | clock, routes, dock bays, grid zones + audits, pick stations, SKUs, maintenance windows |
| `routes/slots.py` | 264 | slots, withhold/release capacity, accounts, slot bookings + confirm |
| `routes/orders.py` | 160 | orders, lines, cancel, order-line reads, accept-shortage |
| `routes/waves.py` | 618 | waves (slot-orders, assign-dock, start-picking, consolidate, loading-sequence, dispatch), totes, pick tasks |
| `routes/subs.py` | 222 | substitution proposals: create/propose/approve/decline/expire |
| `services/derive.py` | 206 | relationship helpers, both conserved ledgers, all derived counters, `reconcile()` |
| `services/money.py` | 172 | provisional/final line pricing, deviation ratio, 4-step waterfall, authorize/capture, surge, transport cost |
| `services/selectors.py` | 224 | retrieval sequence, station selector, substitute selector, waitlist promotion, bump, stop order, load sequence, audit application |
| `services/cascade.py` | 114 | short-pick 4-hop cascade, auto-proposal creation, order cancellation cascade |

3124 lines total (plus two empty `__init__.py`), `Flask>=3.0.0` in `requirements.txt`, and `start.sh` (executable, foreground `exec python3 app.py`, reads `$PORT` default 10000, binds `0.0.0.0`, guarded pip install so per-test reboots don't contend).

## Coverage
- **Endpoints: 65/65.** A script diff of the PRD §4 table against the `@bp.route` rules reports `missing: []`, `extra: []` (26 GET + 39 POST, matching the PRD's own 26/39 split).
- **Validations:** one priority-ordered gate. Gates 1–4 (auth, role, JSON, content) live in the `endpoint()` decorator; gate 5 (path ids, left to right) in `must_get`; gates 6–33 are inlined per handler in numbered order with the gate number in a comment. Where a numbered gate and §3 prose disagree, the numbered gate wins, except where an endpoint's prose is more specific (see below).
- **State machines:** status strings on the entity dicts with the transition precondition checked at the gate-11 slot, including the parallel `fulfillment_status` × `billing_status` dimensions on CustomerOrder and the three cyclic machines (tote OPEN↔SEALED, line PENDING→SHORT→PENDING, zone OPERATIONAL↔MAINTENANCE/AUDIT_HOLD).
- **Calculations:** all in `services/money.py` + `derive.py` using `Decimal` with `ROUND_HALF_UP` and `Fraction` for exact ratio comparisons — never float, never banker's rounding. Both conserved ledgers are recomputed from scratch inside the mutating request and re-checked by `derive.reconcile()` at the end of every mutating request.
- Storage is in-memory dicts only: no seeding, no file/SQLite/JSON persistence (the only `json` call in the tree is `json.dumps` for the response body). Boots empty every launch.

## Smoke tests
Three end-to-end passes, each on a freshly launched server on port 41954, all **FAILURES: 0**:
1. Happy path: plant setup, catchweight SKU, booking waterfall (subtotal 3800 / fee 500 / total 4300), confirm+authorize, wave, dock, picking, cold-chain rejection, tolerance boundary (1100 g accepted, 1101 g rejected), catchweight final price 2200, short-pick cascade, auto-proposal → approve (total 4620, ADJUSTED → CAPTURED), consolidate, load sequence (transport 1500 = 120 c/km × 12.50 km), segregation-of-duties 403, dispatch, audit (0.9375 → AUDIT_HOLD), maintenance overlap 409 + activate/complete, waitlist/withhold/bump/release, cancellation.
2. Gate ordering and negatives: 30+ specific error ids asserted (route mismatch beats minimum basket, window-closed beats minimum basket, FK-not-found beats a malformed body, duplicate booking, stale version 412, substitute-not-comparable, supersede target, proposal already open, proposal expired/not-expired, line-not-short, station zone/capacity, tote-not-assigned, wave frozen, wave-has-no-orders), plus waitlist non-promotion when free capacity is still short and PREMIER's 5% below-threshold discount (1920 → 96 → 1824).
3. Posture and capacity: consolidation permitted under RESTRICTED but loading refused with `ERR_ORDER_DISPATCH_BLOCKED`, dock concurrency (touching intervals accepted, 1-minute overlap refused, capacity-2 bay accepted), maintenance buffer boundaries (exactly +15 min accepted, 14:59 refused, COMPLETED windows ignored), activate-too-early, AUDIT_HOLD zone refusing maintenance, station IDLE/ACTIVE cycle across seal/unseal, task cancel restoring `allocated_units` 3→0, pagination meta.

All 15 `.py` files pass `python3 -m py_compile` (`COMPILE_OK`). The port-41954 server was killed by its specific PID, the port is confirmed free, `__pycache__` and `.scratch/step6` were removed (parent `.scratch` preserved), and `worklog.md`, `test_helpers/` and `test_suite/` were never read or written.

## PRD ambiguities and chosen interpretations
1. **Waterfall step 2 vs waitlisting** — §3.2 says the fee needs a HELD/CONFIRMED booking; §3.3 says a WAITLISTED booking still counts for step 2. Followed §3.3 (more specific): the totals become non-null on the waitlist branch.
2. **Numbered gate vs prose order** — the numbered gate of §2.8 wins by default: start-picking 11→12→13→26→27→31, slot-bookings 10→18→24→30→32→33, assign-tote 11→14→30, loading-sequence 11→12→26→29, dispatch 11→12→17→29, approve 11→13→25→27→31.
3. **Two documented exceptions** where an endpoint's own prose is strictly more specific: `start-retrieval` keeps prose order (task QUEUED → `ERR_TOTE_NOT_ASSIGNED` → zone OPERATIONAL → wave PICKING) because gate 30's applies-to list omits it; and tote `seal` checks "every bound task terminal" (`ERR_INVALID_STATE`) before `ERR_WAVE_FROZEN`, per §3.5's ordering, while `consolidate` checks frozen before task terminality, per §3.6's ordering.
4. **`POST /delivery-waves` body constraints** (slot route ≠ wave route, duplicate `delivery_slot_id`, `cutoff_at` not before `window_start`, duplicate `wave_code`) have no dedicated code → `ERR_INVALID_REQUEST` 422.
5. **Audit payload naming a SKU in another zone** → `ERR_SKU_NOT_FOUND` (all payload ids pre-resolved before any write, so a partial audit is impossible).
6. **`units` on withhold/release** validated as ≥ 0 with no upper bound, so oversized values surface as `ERR_WITHHELD_UNITS_EXCEEDED` rather than a shape error.
7. **Surge recomputation** also runs on wave creation, justified by §3.5's "the route's active-wave count has just changed" rationale.
8. **Substitution-created task** gets `sequence_index = 1 + max(existing index in the wave)`.
9. **Short pick** writes both `picked_units` and `picked_weight_grams` on the line; approval resets only `picked_units`, exactly as §3.6 words it.
10. **Unknown query parameters** on list endpoints are ignored (the PRD specifies codes only for `limit`/`offset`); an unrecognised *value* for a declared filter returns an empty page, not 422.
11. **`created_at`/`updated_at`** come from host wall clock (3 fractional digits) while the logical clock drives every temporal rule; a hidden `_seq` is the final list tiebreak so `id` is never a sort key.
12. **Version bumps**: explicit at every PRD-enumerated site, otherwise exactly one snapshot-diff bump per mutated entity per request; rejected requests bump nothing (`abort_request` in all three error handlers).

## Step 7: Run tests and iterate — 2026-09-06T01:00:00.000Z

All 173 tests pass in all 8 rounds. Details below.

## Iterations run
2 (one diagnostic sweep, one verification sweep).

## Iteration 1 findings — 7 deterministic failures (same 7 in all 8 rounds), three root causes

**Tests deleted:** none. Every failing test cited a verbatim PRD sentence and survived both the coverage and unique-derivability checks.

**Fixes applied to `test_helpers/`:** none. The helpers were audited (api_client canonicalisation, factories money-as-numbers/full-instant literals, test_users genuinely-empty header strings, assertions single-unwrap) and were clean; the bugs were at call sites, not in shared fixtures.

**Fixes applied to `test_suite/`:**

- `test_suite/test_06_derived_figures_and_orderings.py` — `test_retrieval_order_puts_frozen_first_then_the_lower_zone_then_the_lower_sku` and `test_van_is_loaded_last_stop_first_with_the_freezer_tote_ahead_of_ambient`: both registered `FRZ-1` into a `FROZEN` grid zone while leaving the factory's default `temperature_zone` of `AMBIENT` in the body. PRD §3.1 requires the SKU's class to equal its zone's class, so the PRD-faithful implementation correctly answered `ERR_INVALID_REQUEST` during setup. Added `temperature_zone=TemperatureZone.FROZEN.value` to both SKU registrations rather than relaxing the impl's check.
- `test_suite/test_11_cycles_cascades_and_guard_precedence.py` — the four `test_binding_a_*_task_to_a_*_tote_*` tests built a basket worth 250 cents (default SKU price 250 × qty 1) and then booked a slot, tripping the PRD §2.8 gate 33 minimum of 1,000 cents in setup. Raised each to the convention the rest of the file already uses (`unit_price_cents=700, physical_units=100` plus `ordered_qty=2, units=1` → 1,400 cents). The min-basket check in the implementation was left untouched.

**Fixes applied to `implementation/`:**

- `workspace/implementation/routes/waves.py`, `create_wave` — removed a `money.recompute_surge_for_route(...)` call that re-priced every slot on the route when a wave was merely opened. PRD §3.3 enumerates the surge recompute triggers exhaustively ("when the slot is created, when a booking is created, when a booking is confirmed, when capacity is released, when capacity is withheld, when an order is cancelled, and when the logical clock is moved") and wave *creation* is absent; only wave *status* changes re-price the route, via the explicit recomputes at start-picking (§3.5) and dispatch (§3.7). The stray trigger baked the 0.15 congestion premium into the stored multiplier early, so `surge_multiplier_at_booking` came back 1.35 instead of 1.20. The two PRD-mandated route-wide recomputes at start-picking and dispatch were left in place. I cross-checked every other surge assertion in the suite (test_01/02/03/06/07/09/10/12) — none of them has a wave in scope at the point it reads a slot's multiplier, so nothing else depended on the extra trigger.

## Final per-round numbers (iteration 2)

| Round | Passed / Total |
| --- | --- |
| 1 | 173 / 173 |
| 2 | 173 / 173 |
| 3 | 173 / 173 |
| 4 | 173 / 173 |
| 5 | 173 / 173 |
| 6 | 173 / 173 |
| 7 | 173 / 173 |
| 8 | 173 / 173 |

Zero failures, zero errors, zero skips in every round. No flakiness appeared across the 8 concurrent rounds. `$TASK/.scratch/step7` removed; `worklog.md` untouched.

**Orchestrator verification (sweep-artifact guard):** the orchestrator independently read all eight `workspace/implementation/results.$i.json` off disk before this summary arrived and confirmed `passed=173, total=173, failed=0, errors=0` in every round (the preceding baseline sweep had shown an identical 166/173 in all 8 rounds — deterministic, no load-induced flakiness). Step 7 applied 1 `implementation/` fix, so the Step 8 skip condition does NOT apply and Step 8 will run.

## Step 8: Finalize PRD — 2026-09-06T01:07:00.000Z

Done. `PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 528 lines / 120,199 bytes
- `PRD_FINALIZED.md`: 528 lines / 121,133 bytes
- **0.00% line delta** (4 lines revised in place, none added or removed); +0.78% byte delta.

## Changes (one bullet each)

- **§3.3 (surge pricing preamble)** — revise — replaced the open-ended "recomputed whenever anything that feeds it moves" enumeration with a closed trigger list, scoped per-slot vs. per-route vs. service-wide, and added an explicit exclusion that opening a wave, slotting an order, assigning a dock, consolidating and sequencing a load never re-price a slot; states that a wave's congestion contribution enters the stored figures at start-picking and leaves at dispatch — `routes/waves.py:66-72` (the removed trigger), `routes/slots.py:55,86,105,211,258`, `services/cascade.py:113`, `routes/plant.py:33`, `routes/waves.py:247,357`.
- **§3.5 (start-picking outcome)** — revise — rationale clause "because the route's active-wave count has just changed" → "because the wave's `status` has just changed"; behavior claim unchanged — `routes/waves.py:247`.
- **§3.7 (dispatch)** — revise — same rationale softening ("Because the wave's `status` has changed") — `routes/waves.py:357`.
- **§3.1 (catalogue / SKU registration)** — insert — pinned the error identifier for a SKU whose `temperature_zone` differs from its grid zone's as `ERR_INVALID_REQUEST`, explicitly not one of §2.10's three cold-chain codes — `routes/plant.py:205-206` via `validation.py:12-13`.

## Per-edit pre-edit search log

**Edit 1 — §3.3 trigger list**
- (a) Subject: the complete set of events that rewrite a slot's `surge_multiplier`, and the scope (one slot / one route / all slots) of each.
- (b) Enumerated: `grep -rn surge` over all of `implementation/`. Every writer of `slot["surge_multiplier"]` is `money.recompute_surge` (`services/money.py:111-144`) plus the initial `SURGE_FLOOR` seed at `routes/slots.py:52` which is immediately recomputed at `:55`. All nine call sites read in full: `routes/slots.py:55` (create), `:86` (release-capacity, after promotion), `:105` (withhold-capacity, after bumping), `:211` (booking create — both HELD and WAITLISTED branches, unconditional), `:258` (confirm); `services/cascade.py:106-113` (order cancellation, over `touched_slots` only); `routes/plant.py:33` (`recompute_surge_all` on clock set); `routes/waves.py:247` (`recompute_surge_for_route` at start-picking) and `:357` (at dispatch). Read all of `routes/waves.py` to confirm the *absent* sites: `create_wave`, `slot_orders`, `assign_dock`, `consolidate`, `loading_sequence`, tote open/seal/unseal, `assign_tote`, `start_retrieval`, `complete_task`, `cancel_task` — none recompute. Also confirmed `routes/subs.py` and `services/selectors.py` (audit, promotion, bumping) contain no recompute of their own.
- (c) Two adjustments made for consistency: (i) "when an order is cancelled" narrowed to "when an order cancellation releases one of that slot's own bookings — a booking in `HELD`, `CONFIRMED` or `WAITLISTED`", because `cascade.py` recomputes only the slots of released bookings, not every slot; (ii) the clock trigger explicitly scoped "across every slot in the service" (matching `recompute_surge_all`) and the two wave triggers scoped "every slot of one route" (matching `recompute_surge_for_route`), so the closed list can't be read as per-slot everywhere. Noted that impl recomputes at `consolidate`-time nowhere even though congestion drops there — the exclusion sentence names consolidation explicitly rather than claiming inputs are always live.

**Edit 2 & 3 — §3.5 / §3.7 rationale**
- (a) Subject: the stated reason for the route-wide recompute at start-picking and at dispatch.
- (b) Enumerated: `routes/waves.py:226-248` (start_picking: `FORMING → PICKING`, so the `FORMING or PICKING` congestion count is unchanged) and `:348-357` (dispatch: the wave left the count at consolidation, so it is unchanged here too); `services/money.py:132-136` (the congestion population) and `:147-150`. Both recomputes are unconditional at the end of a successful transition.
- (c) Replaced the factually false "the route's active-wave count has just changed" with the neutral, true "the wave's `status` has just changed" in both places; the behavioral sentence (which slots, when) was left verbatim so no path is re-described.

**Edit 4 — §3.1 SKU/zone class mismatch code**
- (a) Subject: which error identifier a SKU registration returns when its `temperature_zone` differs from its grid zone's, and whether that check can be pre-empted.
- (b) Enumerated: `routes/plant.py:180-206` in full — `v.fk` on `grid_zone_id` (→ `ERR_ZONE_NOT_FOUND`, 404) runs first, then shape validation, then the catchweight conditional pair (`v.bad`), then `ensure_unique` on `sku_code` (`validation.py:207-210` → `bad`), then the class-equality check at `:205` (`v.bad`); `validation.py:12-13` confirms `bad` → `ERR_INVALID_REQUEST` (422). Also grepped every `temperature_zone` comparison and every use of the three cold-chain codes to confirm `ERR_TEMPERATURE_ZONE_MISMATCH` occurs only at `routes/waves.py:518` (assign-tote), `ERR_STATION_ZONE_UNSUPPORTED` only at `:380` (tote open), `ERR_SUBSTITUTE_NOT_COMPARABLE` only at `routes/subs.py:53-56`.
- (c) Kept "which must exist and" ahead of the new clause so the 404-before-422 ordering is preserved, and phrased the exclusion as "not with any of the three cold-chain segregation codes of §2.10" — §2.10 already frames those three as the rules derived *from* the declarations, so the registration rule stays outside them and no other endpoint's code is redefined.

The other two Step 7 items yielded no edits: the `FRZ-1`/`AMBIENT` registration and the 250-cent basket were both call-site fixture bugs against behavior PRD already pins verbatim (§3.1/§2.10 class equality; §2.8 gate 33 and §3.3 minimum basket). The only substantive adjudication was the surge-recompute trigger set.

**Orchestrator verification:** `PRD_FINALIZED.md` is 121,133 bytes vs `PRD.md` 120,199 — not byte-identical, so the pass genuinely ran. Step 9 will start from `PRD_FINALIZED.md` and will be split into three sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (a single agent asked to scan all 3,124 impl lines against the 528-line PRD reliably degrades into a byte-identical no-op copy).

## Step 9: Complete PRD — 2026-09-06T01:40:00.000Z

Step 9 was run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`. Rationale (orchestrator decision, made autonomously): a single subagent asked to scan all 3,124 implementation lines against a 528-line PRD in one context reliably degrades into a byte-identical no-op copy, so the implementation was partitioned by module. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying and edited the file in place. Each pass was told what its predecessors had settled, and each handed forward the behaviors whose true source lay in a later pass's modules.

### Pass 1 — infra + plant (`app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `validation.py`, `routes/plant.py`)

`cp PRD_FINALIZED.md → PRD_COMPLETED.md` performed (this pass only). 528 lines / 121,133 bytes → 540 lines / 134,277 bytes. All 9 `###` section headers, both markdown tables (65 endpoint rows, 53 error rows) verified intact.

Counts: **14 ambiguity-pins, 0 mismatch-revisions** (nothing in these modules contradicted the PRD; `errors.py`'s 53 id→status pairs match §5 exactly, in the same order — verified programmatically).

- **§2.1** — insert — ambiguity — headers compared verbatim (no trim/case-fold); whitespace-only header = absent → `ERR_UNAUTHENTICATED`, padded role name → `ERR_UNKNOWN_ROLE` — `middleware.py:33-53`
- **§2.2 success** — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A–Z0-9`, freshly minted per response; `api_request_timestamp` reads host wall clock, not the logical clock — `db.py:160-162`, `response.py:38-42`
- **§2.2 success** — insert — ambiguity — every non-list response uses `response_type` `"object"`; undetermined fields present as JSON-`null`; internal bookkeeping never exposed — `response.py:53-67`, `db.py:222-235`
- **§2.2 success** — insert — ambiguity — the four pagination `meta` fields appear on list responses *and only there* — `response.py:54-61`
- **§2.2 error** — insert — ambiguity — unrouted path / unsupported method → `ERR_INVALID_REQUEST` with the routing status (404/405); trailing slash tolerated; unanticipated failure → `ERR_INVALID_REQUEST` 422; no rejected request mutates state — `app.py:21,34-47`, `db.py:245-252`
- **§2.3** — insert — ambiguity — "integer" = optionally signed digit run (`+25` accepted), whitespace stripped, empty/decimal/non-digit rejected; offset past `total_count` legal → empty array; params ignored on single reads — `response.py:82-105`
- **§2.3** — insert — ambiguity — `created_at` ties broken by server creation sequence; `has_more` = `offset + len(page) < total_count`; filters exact, case-sensitive, conjunctive, never an error even for a non-existent id; unknown query params ignored; null field never matches — `db.py:152-157`, `response.py:108-133`
- **§2.4** — insert — ambiguity — `created_at`/`updated_at` read host wall clock, explicitly *not* the logical clock — `db.py:78-79,141-149`
- **§2.4** — insert — ambiguity — version discipline: +1 per request not per field; a resource created in a request stays at `version` 1; derived-field recomputation counts as a mutation and bumps the carrier's own version (slot ledger/surge, station count/status, wave posture/counters, SKU ledger, zone scores/status, order flags, tote counts); rejected requests bump nothing; a no-op recompute bumps nothing — `db.py:176-216`, `middleware.py:60-65`
- **§2.5** — insert — ambiguity — `current_utc` is the body's only field; clock may wind backwards; not a persisted resource; 200 / `"object"` / `data` = `{ "current_utc": … }`; the move also reconciles all derived aggregates — `routes/plant.py:27-34`, `services/money.py:153-155`
- **§2.6** — insert — ambiguity — every decimal field is a bare JSON *number* in and out; a whole number is acceptable where a decimal is expected; trailing zeros not observable (`0.9800` renders `0.98`) — `db.py:229-230`, `validation.py:104-123`
- **§2.8 gate 6** — insert — ambiguity — gate 6 inspects only present non-empty-string FKs; absent/null/blank/wrong-type falls through to gate 8 as `ERR_INVALID_REQUEST` — `validation.py:213-223`
- **§2.8 gate 8** — insert — ambiguity — six sub-bullets: body must be a JSON object; absent/whitespace body = `{}` so action endpoints accept an empty body and reject any field; `Content-Type` never examined; explicit `null` treated as absent; strings never trimmed, whitespace-only is blank; strict types, no coercion, non-finite rejected; instant grammar (optional fractional part of any width, `Z`/`z`/`+00:00`/`+0000`, non-zero offset and naive timestamps rejected, always rendered with 3 digits); all uniqueness violations are `ERR_INVALID_REQUEST` 422, exact/case-sensitive, after type checks and after gate 6 — `validation.py:16-26,90-101,148-152,187-210`, `db.py:41-75`
- **§2.10** — insert — ambiguity — `temperature_zone_capability` rejects empty/duplicate/non-class/non-array, and is stored and returned in the client's supplied order (never re-sorted into the cold-chain ranking) — `validation.py:155-165`
- **§3.1** — insert — ambiguity — the service boots with zero data; every family arrives only via §4 endpoints; fresh lists return empty `data` and `total_count` 0 — `app.py:1-6`, `db.py:113-119`
- **§3.8 windows** — insert — ambiguity — `window_end <= window_start` is `ERR_INVALID_REQUEST` (422) and outranks the overlap check; the three fields are the whole body; a window may be scheduled entirely in the past or future — `routes/plant.py:253-259`
- **§3.8 audit** — insert — ambiguity — `counts` is the only field; entries carry exactly `sku_id`/`counted_units` with `counted_units` in 0…1,000,000; an **empty** array is legal and still re-scores and advances `last_audited_at`; unknown `sku_id` caught *before* shape validation, wrong-zone `sku_id` *after*, both `ERR_SKU_NOT_FOUND` 404 — `routes/plant.py:126-142`, `validation.py:166-183`
- **§3.8 audit** — insert — ambiguity — entries applied strictly in array order, one fully before the next, giving duplicate `sku_id` a defined outcome (second entry's system figure = first's counted figure; last entry wins `physical_units`) — `services/selectors.py:190-198`
- **§3.8 audit** — revise — ambiguity — empty scored population additionally leaves the zone's `status` untouched (can neither impose nor lift a hold) but still advances `last_audited_at` — `services/selectors.py:204,224`

### Pass 2 — slots / orders / subs (`routes/slots.py`, `routes/orders.py`, `routes/subs.py`)

No `cp` run; 15 targeted `Edit` calls. 540 lines / 134,277 bytes → 540 lines / 137,322 bytes (+3,045; never approached 121,133).

Counts: **10 ambiguity-pins, 4 mismatch-revisions.**

- **§3.1 (shopper account)** — revise — ambiguity — `email` bounds 3…320 characters, containing `@` anywhere is the only structural requirement, out-of-bounds → `ERR_INVALID_REQUEST` — `validation.py:133-137` via `routes/slots.py:118` *(pass 1 hand-off)*
- **§3.2 (basket open)** — revise — mismatch — `stop_distance_km` is "at most two decimal places" (`5`, `5.1` accepted, stored `5.00`/`5.10`; a third place is `ERR_INVALID_REQUEST`) — `routes/orders.py:27`, `validation.py:113-116` *(pass 1 hand-off)*
- **§3.2 (basket open)** — insert — ambiguity — `stop_distance_km` is the body's only accepted field, so a supplied `customer_id` is rejected as an unknown field rather than ignored — `routes/orders.py:26-28`
- **§3.3 (slot creation)** — insert — ambiguity — `window_end` at or before `window_start` is a shape violation → `ERR_INVALID_REQUEST` (422) — `routes/slots.py:39-40`
- **§3.3 (slot creation)** — insert — ambiguity — `withheld_units > total_capacity_units` at creation is also `ERR_INVALID_REQUEST`, never `ERR_WITHHELD_UNITS_EXCEEDED`; both cross-field comparisons run after all field-level checks, window first — `routes/slots.py:41-42`
- **§3.3 (release capacity)** — insert — ambiguity — `units` is a required integer ≥ 0 with no upper bound of its own (negative → `ERR_INVALID_REQUEST`, oversized → `ERR_WITHHELD_UNITS_EXCEEDED`); `units: 0` is a legal no-op that still runs the promotion selector and can promote a waitlisted booking — `routes/slots.py:76-87`
- **§3.3 (withhold capacity)** — insert — ambiguity — same `units` bounds and the `0` no-op that still runs the bump sequence — `routes/slots.py:94-106`
- **§2.8 gate 33** — revise — mismatch — the minimum-basket gate applies to `POST /slot-bookings/{bookingId}/confirm` as well as `POST /slot-bookings` (§3.3 already said so; the gate's "Applies to" line did not) — `routes/slots.py:251-254`
- **§3.6 (offer substitute)** — insert — ambiguity — a line not in `substitution_resolution` `PENDING` is `ERR_INVALID_STATE` (409) at gate 11, never `ERR_LINE_NOT_SHORT` — `routes/subs.py:46-49`
- **§3.6 (propose)** — revise — ambiguity — both the proposal's `DRAFT` status and the line's `PENDING` resolution are gate-11 `ERR_INVALID_STATE` checks, proposal status first — `routes/subs.py:107-112`
- **§3.6 (approve)** — insert — ambiguity — the wave-`PICKING` requirement is a gate-11 `ERR_INVALID_STATE` evaluated right after the proposal's `PROPOSED` check, so it outranks the zone/expiry/station/inventory checks, and a wave-less order fails it too — `routes/subs.py:136-138`
- **§3.6 (approve)** — insert — ambiguity — the line's `picked_weight_grams` is deliberately not reset (only `picked_units` is) — `routes/subs.py:163`
- **§3.6 (approve)** — insert — ambiguity — the substitute's new pick task carries null `tote_id`, `picked_units` and `actual_weight_grams` — `routes/subs.py:171-177`
- **§3.9 (cancellation)** — revise — mismatch — removed the dead "an administrator acting on a shopper's behalf is exempt from ownership" clause; the endpoint is `Customer`-only, so any other role gets `ERR_FORBIDDEN_ROLE` — `routes/orders.py:100-103`, `middleware.py:80-83`

### Pass 3 — waves + services (`routes/waves.py`, `services/derive.py`, `services/money.py`, `services/selectors.py`, `services/cascade.py`)

No `cp`, no `Write`, no rewrite — all in-paragraph revisions/inserts via targeted `Edit`. 540 lines / 137,322 bytes → 540 lines / 144,391 bytes (+7,069; line count unchanged because every change was in-paragraph).

Counts: **11 ambiguity-pins, 7 mismatch-revisions.**

- **§2.4** — insert — ambiguity — an exact `created_at` tie in any §3 ordering is resolved *at that same key position* by creation order (earlier first), before any lower-priority key; `id` never compared — `db.py:152` as consumed by `services/selectors.py:20,66,94,112,160,180`
- **§3.2 step 2** — revise — mismatch — the waterfall locates the order's **live** booking (`HELD`, `CONFIRMED` **or `WAITLISTED`**), HELD/CONFIRMED outranking WAITLISTED, earliest-created among equals — `services/money.py:57`, `services/derive.py:98-105`
- **§3.3 surge lead premium** — insert — ambiguity — "rounds down" is a floor, so a `window_start` at/before now yields ≤0 hours and earns the full 0.20 — `services/money.py:123-127`
- **§3.3 promotion selector** — revise — ambiguity — created-order settles the first-come key, so `units`/`quoted_fee_cents` sit strictly beneath it — `services/selectors.py:104-113`
- **§3.3 bump selector** — revise — mismatch ×2 — candidate set is `CONFIRMED` bookings whose order is in `DRAFT` or `SLOTTED` **only**; the loop stops when the eligible set runs dry, so the withholding succeeds with `available_units` still **negative** — `services/selectors.py:124-149`, cross-checked against `routes/slots.py:101-106`
- **§3.4 wave creation** — insert — ambiguity — the three cross-field conditions (slot serves route, one wave per slot, cutoff before `window_start`) are all `ERR_INVALID_REQUEST` 422, evaluated after field checks and after `wave_code` uniqueness, in that order — `routes/waves.py:42-49`
- **§3.4 wave counters** — revise — mismatch — `van_capacity_totes` is never enforced; no endpoint tests `tote_count` against it and no error code exists — `routes/waves.py:391-401` (grep: `van_capacity_totes` appears only in `routes/plant.py:47,55`)
- **§3.4 order slotting** — insert — ambiguity — the response payload is the **wave**, and `ERR_WAVE_SLOT_MISMATCH` is reported ahead of `ERR_ROUTE_MISMATCH` when both fail — `routes/waves.py:107-129`
- **§3.5 start-picking** — insert — ambiguity — the three feasibility checks are listed by subject, not precedence; §2.8 positions 13 < 26 < 27 < 31 decide — `routes/waves.py:197-224`
- **§3.5 station selector** — revise — mismatch — assigning a task does not move `current_tote_count`, so the pool/ranking are identical for every task in one start-picking request and all same-class tasks land on the *same* station — `services/selectors.py:49-67`, `routes/waves.py:227-241`
- **§3.5 opening a tote** — insert — ambiguity — the wave's `status` is never examined; only posture and station capacity gate it — `routes/waves.py:366-390`
- **§3.5 assign-tote** — revise — mismatch — the `QUEUED` self-loop does **not** permit re-binding; a task already carrying a `tote_id` is refused — `routes/waves.py:524-525`
- **§3.6 hop one** — insert — ambiguity — the short line records `picked_units`/`picked_weight_grams` from the task, and the SKU debited is the one actually retrieved (the substitute on a substitute pick) — `services/cascade.py:38-45`
- **§3.6 hop two** — revise — ambiguity — auto-proposal `round_no` is 1 only for a first round, otherwise highest+1 — `services/cascade.py:13-19`
- **§3.6 approval** — revise — mismatch — the new task's `sequence_index` is one greater than the highest among *all* the wave's existing tasks (1 if none), extending the retrieval order — `services/selectors.py:37-43`
- **§3.7 stop order** — insert — ambiguity — the stop ordering is per-request only; nothing is persisted, the stored outputs are `load_sequence` and `transport_cost_cents` — `services/selectors.py:155-161`, `routes/waves.py:310-312`
- **§3.8 hold gate** — insert — ambiguity — the status write ignores the zone's current status, so auditing a `MAINTENANCE` zone moves it to `AUDIT_HOLD`/`OPERATIONAL` even with an `ACTIVE` window — `services/selectors.py:220-223`
- **§3.9 hop 2** — revise — mismatch — the multiplier is not written in hop 2; ledger → promotion → one surge recompute from the **final** ledger — `services/cascade.py:107-113`
- **§3.9 hop 3** — insert + revise — ambiguity ×2 — promotion runs only on slots that released a `HELD`/`CONFIRMED` booking (waitlist-only slots get ledger+surge but no promotion); plus the created-order tie-break — `services/cascade.py:86-110`, `services/selectors.py:112`
- **§3.9 reversal** — insert — ambiguity — the cancelled order's `merchandise_subtotal_cents` falls to 0 and its other three money figures revert to null, without an `ADJUSTED` transition — `services/cascade.py:101`, `services/money.py:44-98`

All five of pass 2's hand-offs were resolved in pass 3 (live-booking set; bump candidate statuses; the bump loop's negative-`available_units` overclaim; the creation-order tie-break, pinned globally in §2.4 and locally in both promotion write-ups; and the substitute task's `sequence_index`).

Pass 3 recorded one incidental observation it deliberately did not act on because it is not PRD-fixable: at `routes/waves.py:566-581`, a catchweight *substitute* task completing on a line whose original SKU was not catchweight would evaluate `line["nominal_weight_grams"] * line["ordered_qty"]` against a null snapshot, and `services/selectors.py:73-96` does not filter substitute candidates on `is_catchweight`, so the path is reachable in principle. It left the PRD's existing tolerance wording unchanged rather than document a crash. No test exercises this path.

### Step 9 totals and orchestrator verification

**35 ambiguity-pins + 11 mismatch-revisions = 46 changes** across the three passes. `PRD.md` 528 lines / 120,199 bytes → `PRD_FINALIZED.md` 528 / 121,133 → `PRD_COMPLETED.md` 540 lines / 144,391 bytes (+20.1% bytes over `PRD.md`).

Orchestrator's independent checks on the final file: `PRD_COMPLETED.md` is byte-different from BOTH `PRD_FINALIZED.md` and `PRD.md` (so no pass degenerated into a no-op copy, and no later pass clobbered an earlier one); the §4 endpoint table still has exactly **65** data rows and the §5 error table exactly **53**; 29 markdown headings intact; the file ends at a real section boundary (`| ERR_MINIMUM_ORDER_NOT_MET | 422 |`), not mid-sentence; grep for the Step 2 difficulty directive returns 0 hits. `find` over `test_suite/`, `test_helpers/` and `implementation/` shows no `.py` file modified after the final Step 7 sweep completed at 00:58, so the verified 8×173/173 result still describes the code on disk — Step 9 changed documentation only.

## Pipeline complete — 2026-09-06T01:42:00.000Z

All nine steps finished. Final deliverables present: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 files), `test_suite/` (13 test files + conftest, 173 tests), and `workspace/` with `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `implementation/` (15 modules + `start.sh` + `requirements.txt`) and `results.{1..8}.json` all at 173/173.
