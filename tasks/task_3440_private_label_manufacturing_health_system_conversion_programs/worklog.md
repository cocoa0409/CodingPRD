# Worklog — task_3440_private_label_manufacturing_health_system_conversion_programs

## Step 1: Create Task Directory — 2026-10-02T03:28:00.000Z

Task directory pre-allocated by caller: `./tasks/task_3440_private_label_manufacturing_health_system_conversion_programs/` with `workspace/` inside. Verified existence; no new index computed, no other task_* directory created.

## Step 2: Generate Scaffold — 2026-10-02T04:26:00.000Z

Scaffold generation complete and lint-clean. Report:

**Output files** (all parse as valid YAML; `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`):
- `/home/ubuntu/github/CodingPRD/tasks/task_3440_private_label_manufacturing_health_system_conversion_programs/SCAFFOLD.yaml` — 1221 lines (§1.0–§1.7 + 2 OCC concurrency rules)
- `/home/ubuntu/github/CodingPRD/tasks/task_3440_private_label_manufacturing_health_system_conversion_programs/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 965 lines (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3440_private_label_manufacturing_health_system_conversion_programs/SCAFFOLD_CORNER_DESIGN.yaml` — 2223 lines (single key `scaffold_corner_design`)

**Counts**
- Entities: 11 — Product, ManufacturingLot, SterilizationBatch, Facility, ConversionProgram, TrayTemplate, PrimeVendorAgreement, DistributionOrder, RebateClaim, SupplyDisruption, InventoryProgram
- Endpoints: 39 (within the ≤40 hard cap; density over volume)
- State machines: 9 (cyclic: Product registration resubmit, ConversionProgram redesign loop, TrayTemplate change-management cycle, RebateClaim dispute cycle, PVA auto breach/recovery)
- Calculations: 5; Validations: 36 (priority-ordered); Errors: 43 (all referenced); Roles: 8 (segregation_of_duties model; FacilitySupplyDirector is `entity_backed:Facility`)
- §1.8 difficulty instances: 18 (9 rules × 2, each with distinguishing aspect per §0.5)
- §1.9 corner instances: 71 active + 13 `excluded_because` stubs = 84 entries across all 9 guide sections

**Difficulty design highlights** (all formula-derived asserts pre-computed via Python execution of §1.3 formulas): dual-variant fill rate (93.33 provisional vs 100.00 final) and rebate accrual (36000 vs 42000); combinatorial rebate tier+bonus+multiplier (21000) vs pinned per-line case-ceiling order pricing (9560 vs forbidden 8060); depth-3 cascades (receive→rolling recompute→SUSPENDED→inventory-program mute; substitution APPROVE→coverage→RESOLVED→auto-reject pending requests); priority conflicts state-vs-fiscal and safety-vs-referential; fill-rate equality-is-compliant boundary (95.00 vs 94.92) and reorder-point inclusive/zero boundary; cross-entity gates (ConversionProgram→PVA, Lot→SterilizationBatch); half-open chamber windows vs closed rebate periods; stock-conservation and scarcity-partition invariants.

**Verification**: `scaffold_lint.py` verdict block — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (486 calls scanned, 0 violations). Additional checks passed: 102 unique instance names across both design files, all grounds refs (calculations/state-machine transitions/endpoints/roles/errors/validation priorities) resolve, all stub citations exist, no forbidden concurrency vocabulary, YAML re-parsed after every incremental append (two flow-sequence bracket issues found and fixed during writing).

One design note: RECEIVED accepts open (uncancelled) shortfall lines with the shortfall counted against the final fill rate — deliberately pinned so the final variant isn't vacuously 100% (an all-resolved-lines gate would have made `final == 100` always, killing the dual-variant rule).

Orchestrator spot-check after hand-back: all three files exist with reported line counts (1221/965/2223), all parse as YAML with expected top-level keys, 210 domain-marker hits (steriliz/conversion/tray/rebate/prime-vendor/disruption) confirm on-domain content, and SCAFFOLD.yaml contains no design-index keys.

## Step 3: Copy Shared Files — 2026-10-02T04:27:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-10-02T04:47:00.000Z

All verification passes. The PRD is complete and shipped.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_3440_private_label_manufacturing_health_system_conversion_programs/workspace/PRD.md` — 328 lines, written incrementally in 16 chunks (Write + quoted-heredoc appends, avoiding the unquoted-heredoc backtick-execution trap), then repaired and verified.

**Section list**:
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications, 10 subsections: 2.1 RBAC (all 8 roles with identity prose — `FacilitySupplyDirector` entity-backed to `Facility`, 7 opaque roles), 2.2 API Response Structure (diffed **byte-identical** against `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 The Logical Clock (`2026-09-01T00:00:00Z` initial, `to_iso8601`/`current_utc`, no wall-clock fallback), 2.5 Common Resource Properties, 2.6 Validation Priority Ordering (10-band cascade with worked first-failure examples), 2.7 OCC (both rules), 2.8 Precision/Rounding, 2.9 Nested Resource Retrieval, 2.10 Automatic Transitions & Cascades
- §3 Business Logic, 9 subsections: catalog/registration, lots/sterilization/QA disposition, facilities/conversion programs, tray change management, agreements/order placement, fulfillment/breach–recovery cycle, GPO rebates, disruptions/allocations/substitutions, inventory programs/replenishment
- §4 Endpoint table — **39 rows**, 4 columns
- §5 Error catalogue — **43 rows**, 2 columns; file ends with the complete `ERR_PAR_LEVEL_VIOLATION` row (no truncation)

**Error IDs**: 43/43 present both in §2/§3 prose (with trigger conditions adjacent to their workflows) and in the §5 table.

**Numeric literals carried over**: all scaffold constants verified present — rebate tiers 100000/500000/1000000/2000000 cents with rates 0.01/0.02/0.03/0.04, floor 0.005, bonus threshold 0.30 and rate 0.005, multipliers 1.0/0.5, pinned double-rounding order; 90-day rolling window; 100.00 empty-denominator convention; per-line ceiling rule; array bounds 1..20/1..30/1..50/1..50; deliveries 1..7; committed rate 0..100 at 2 decimals; pagination 10/1/100/0; `AUTO_RESOLVED`; all HTTP statuses.

**Hard contracts**: Contract 1 PASS (116/116 required field/input/query tokens backticked — 3 initial misses `event`/`disposition`/`result` repaired via targeted edits); Contract 2 PASS (priority orderings, both OCC rules with exact `ERR_STALE_VERSION`/412 framing, all 9 state machines' transitions with preconditions/side effects, all 5 calculations with precise reconstructible prose, sibling-branch symmetry, cascade version arithmetic including the disruption single-increment exception); Contract 3 PASS (671 §3 backtick tokens, zero path/method violations — the clock endpoint path lives only in §2.4 and §4).

Orchestrator spot-check after hand-back: PRD.md is 328 lines, tail shows the complete §5 error table ending at `ERR_PAR_LEVEL_VIOLATION` (no truncation), all 43 scaffold error_ids appear in the PRD (only scaffold placeholder `ERR_XXX` absent, as expected).

## Step 5: Generate Unit Tests — 2026-10-02T05:19:00.000Z

Generation complete and fully verified. Final report:

**Task 3440** (private label medsupply): full test infrastructure generated under `/home/ubuntu/github/CodingPRD/tasks/task_3440_private_label_manufacturing_health_system_conversion_programs/`.

### File inventory (4,838 lines total)
- `test_helpers/` (1,725 lines): `types.py` 386, `fixtures.py` 469, `api_client.py` 182 (all 39 PRD endpoints; clock endpoint correctly unprefixed at `/_clock/set_current_utc`), `assertions.py` 186, `__init__.py` 153, `factories.py` 147, `api_errors.py` 100 (43/43 error IDs with HTTP map registered), `test_users.py` 60 (shared constants + per-user builders for all 8 roles, entity-backed `make_facility_director_headers(facility.id)`), `constants.py` 42.
- `test_suite/` (3,113 lines): `conftest.py` + 10 domain test files (`test_01_catalog_registration` … `test_10_inventory_programs`), each with ≥5 tests.

### Coverage accounting
- **Queue A (difficulty): 18/18 instances emitted, exactly 2 tests each** (36 tests) — split along each recipe's natural assert boundaries (e.g. provisional-after-SHIPPED vs final-after-RECEIVED; gate-fires vs losing-gate-not-reported).
- **Queue B (corner): 71/71 active instances emitted** (1 test each). 13 `excluded_because` stubs not translated; all 13 cross-references verified to resolve to real difficulty instances.
- **Skipped: 0.** Every active instance passed the PRD-first two-condition filter — the PRD carries verbatim prose for every asserted rule, including all priority orderings (§2.6), both OCC rules (§2.7), all cascades (§3.6/§3.8), and every calculation constant.

### Verification results
- **AST tag audit (real `ast` parse)**: 89 unique `Design:` tags = exactly the 18 difficulty + 71 corner instance sets; 107 tagged test functions; 0 untagged, 0 dual-tagged, 0 tags pointing to non-existent instances; 0 difficulty instances with <2 tests.
- **Citation sweep**: all 107 docstrings' quoted spans (both ≥8-word and short fragments, whitespace-normalized) are verbatim-present in PRD.md. Found and fixed 5 ellipsis-truncated quotes (C3 violations) during the sweep.
- **Constants diff**: all 19 constants in `constants.py` match PRD+scaffold literals (only "mismatch" was `90` vs PRD's prose "ninety-day" — value correct). No dead constants.
- **py_compile**: all 20 files OK. **`pytest --collect-only`: 107 tests collected, 0 errors** — no dangling imports.

### Recipe/PRD adjudication notes
- No fixture-date corrections needed: all recipe dates are reachable from the 2026-09-01T00:00:00Z clock start; the single clock-advance test uses `POST /_clock/set_current_utc` (2026-12-06) per PRD §2.4.
- `claim_create_computes_provisional_only`: PRD never says verbatim that `final_amount_cents` is null at creation (unlike orders, where §3.5 says it). Asserted via `.get("final_amount_cents") is None` so both faithful serializations (field omitted / explicit null) pass; the 2500-provisional and ACCRUED assertions are fully pinned.
- `sterility_result_recording_twice_rejected`: the PRD declares no batch-read endpoint, so the second-write-did-not-land assertion is made through the readable lot proxy (status stays AWAITING_QA, sterility stays PASSED — a landed FAILED would have quarantined it).
- Dropped the unused third lot (L3) from the chamber-adjacency recipe; no assertion touches it.
- All creates assert 201 explicitly (`validate_success(resp, 201)`); no skip/xfail anywhere; all boundary literals copied verbatim from the design YAML (93.33/100.00, 36000/42000/21000, 9560, 89.47/93.10, 95.00/94.92, 45→0 mute, partition 40/25/35, AUTO_RESOLVED).

Orchestrator spot-check after hand-back: test_suite/ has conftest.py + 10 domain files; 89 unique `Design:` tags confirmed via grep; clock endpoint is `/_clock/set_current_utc` (unprefixed) in test_helpers/api_client.py matching PRD §2.4/§4; independent `pytest --collect-only` collects 107 tests with 0 errors.

## Step 6: Generate Implementation — 2026-10-02T05:36:00.000Z

All verification passes. The implementation is complete and the smoke server is stopped (only PIDs I started were killed).

**File inventory** (all under `workspace/implementation/`):

| File | Lines | Purpose |
|---|---|---|
| start.sh | 10 | Executable; guarded `pip install` (no-op when flask present); `exec python3 app.py`, `$PORT`/0.0.0.0/foreground |
| requirements.txt | 1 | flask>=2.2 |
| app.py | 58 | Flask entry, blueprint registration, ApiError/404/405/500 envelope handlers |
| db.py | 47 | In-memory dict stores (empty at boot, no seeding), logical clock defaulting to `2026-09-01T00:00:00Z` |
| errors.py | 67 | ApiError + all 43 PRD §5 error-id constants with catalog statuses |
| helpers.py | 190 | Envelope (`meta`/`response_type`/`data`, list pagination fields), auth (X-User-ID/X-User-Role), typed field validators |
| services.py | 247 | 5 calculations (order fill-rate provisional/final, 90-day rolling rate, rebate tiers with pinned double-rounding, per-line case-ceiling price, reorder suggestion), lazy EXPIRED, breach/recovery + inventory-mute cascades |
| routes_clock.py | 20 | `POST /_clock/set_current_utc` — unprefixed |
| routes_facilities.py | 29 | facility create |
| routes_products.py | 83 | product create + registration lifecycle (incl. REJECTED→SUBMITTED resubmission) |
| routes_lots.py | 130 | lot create/list/get + QA disposition with ordered guards (state → registration → sterility → SoD) |
| routes_sterilization.py | 105 | batch create (existence → window → dup code → lot composition → half-open chamber overlap) + result recording with FAILED quarantine cascade |
| routes_conversion.py | 174 | programs, line-item evaluations with PENDING→IN_REVIEW bubble-up, gated review APPROVE/REDESIGN |
| routes_trays.py | 176 | tray CRUD + OCC-guarded propose-change + SoD approval with post-increment `approved_version` pinning |
| routes_agreements.py | 99 | agreement create (exclusivity after lazy expiry), list/get with lazy EXPIRED, orders sub-resource |
| routes_orders.py | 158 | order placement (full 10-band cascade) + SHIPPED/RECEIVED fulfillment with fill rates and receipt cascade |
| routes_rebates.py | 130 | claim accrual (closed-interval overlap) + SUBMIT/SETTLE_PAID/SETTLE_DISPUTED/RESUBMIT lifecycle |
| routes_disruptions.py | 238 | disruption declare, OCC-guarded allocations, role-and-action-locked substitution REQUEST/DECIDE, auto MITIGATING/RESOLVED with AUTO_RESOLVED cascade |
| routes_inventory.py | 124 | inventory programs + signed stock events with recompute |

**Route count**: 39 total (38 under `/supply` + 1 clock) — matches PRD exactly, no deviations. Clock-route grep: exactly one registration, `@bp.post('/_clock/set_current_utc')`, unprefixed.

**py_compile**: all 17 .py files pass.

**Smoke tests** (self-run, two scripts, 104 checks, 0 failures): one create flow per domain — product→registration→lot→sterilization batch→QA release; facility→conversion program→evaluation bubble-up→gated APPROVE; tray create→propose (412 stale)→approve (403 self-approval); agreement→order→partial/full ship→receive with `spent_cents`/`rolling_fill_rate_pct` accrual; rebate claim with tier-boundary math (1,000,000¢ → 0.03 tier → 30,000 provisional / 35,000 validated); disruption→allocation (412 stale OCC)→substitution REQUEST/DECIDE→auto-RESOLVED; inventory program with reorder math + stock events. Error paths verified by exact error_id: band-9 `ERR_PRODUCT_NOT_ORDERABLE` beats band-10 `ERR_COMMITMENT_EXCEEDED`; missing headers and undeclared role both → 401 `ERR_UNAUTHENTICATED`; breach cascade suspends agreement and mutes inventory programs; lazy EXPIRED on read after clock advance.

**Adjudications made from PRD text**: logical-clock-vs-`end_date` comparisons are date-based (end_date inclusive); `shipped_qty` in fulfillment payloads is a per-event delta (cumulative semantics per §3.6); OCC evaluated after existence/ownership/state, before component business rules; existence enforced for all scaffold-FK body ids but not for embedded allocation/substitution `facility_id` (deliberately absent from the §2.9 list); read-time reorder recomputation does not bump `version` (only stock events and cascades do).

Orchestrator spot-check after hand-back: all 19 files present (17 .py + start.sh + requirements.txt), `py_compile` passes on all .py files, clock route confirmed unprefixed at `routes_clock.py:13`, no stray app.py server processes left running.

## Step 7: Test-Fix Iteration Loop — 2026-10-02T06:04:00.000Z

Clean 8-round sweep achieved: 107/107 passing in every round, with all 8 `results.*.json` files preserved in `workspace/implementation/`.

## Summary

- **Iterations run**: 2 (baseline: 9 identical failures × 8 rounds; post-fix: 0 failures × 8 rounds)
- **Tests deleted**: none — every failure traced to either a test/fixture mis-expression of a PRD-covered rule or one implementation crash

**Fixes applied to `test_helpers/`**:
- `test_helpers/fixtures.py` — `suspend_agreement_via_breach`: changed the breach order to ship 170-of-200 with `backorder_cancelled: False` (open shortfall, final = 170/200 = 85.00). The old fixture used `backorder_cancelled: True`, which per PRD §3.6 ("a line's cancelled units are its ordered quantity minus its shipped quantity") removes all 30 unshipped units from the denominator, yielding final = 170/170 = 100.00 and never breaching. The design YAML's 89.47 literal was arithmetically unreachable under the PRD formula (single cancelled line always finals at 100.00). This one fixture bug was the upstream cause of 6 of the 9 failures.
- `test_helpers/assertions.py` — `find_substitution_request` gained an optional `status` filter: the disruption's request list can hold a REJECTED request and a PENDING one for the same facility, and the unfiltered first-match lookup returned the REJECTED one as the DECIDE target.

**Fixes applied to `test_suite/`** (assertions/setups re-aligned to the PRD-derived numbers):
- `test_04_conversion_programs.py` — `test_conversion_approve_blocked_by_suspended_agreement`: expected final rate 89.47 → 85.00.
- `test_06_agreements_and_order_placement.py` — `test_order_create_on_suspended_blocked_but_receive_allowed`: breach shipment now cancel=False; expected rolling rate 91.67 → 88.00 (220/250).
- `test_07_fulfillment_fill_rates.py` — `test_receive_breach_suspends_agreement` (final 89.47 → 85.00, rolling 93.10 → 90.00 = 270/300) and `test_breach_mutes_inventory_program` (cancel=True → False).
- `test_09_supply_disruptions.py` — `test_partition_invariant_through_resolve`: DECIDE target now looked up with `status="PENDING"`.

**Fixes applied to `implementation/`**:
- `workspace/implementation/routes_sterilization.py` — added the missing `ERR_STERILIZATION_IN_PAST` import; the priority-7 past-window guard referenced the constant without importing it, so it raised NameError → 500 ERR_INTERNAL instead of the PRD-required 422 whenever a past window was submitted (a called-but-never-imported check).

**Note for doc/unit-test generators**: the difficulty instances `receive_breach_cascades_suspend_and_mutes_programs`, `conversion_approve_requires_active_agreement`, and the corner instance `order_create_on_suspended_blocked_but_receive_allowed` all encode the same impossible arithmetic ("x200, ship 170 with cancel → final 89.47"); the scaffold's own `order_fill_rate` formula makes a cancelled single-line order final at 100.00. The PRD-consistent breach vehicle is an open (uncancelled) shortfall received from PARTIALLY_SHIPPED.

Orchestrator verification after hand-back: all 8 `results.*.json` present and each reports 107/107 passed, 0 failed; no implementation or test .py file is newer than the sweep output (no post-sweep edits; sweep is current).

## Step 8: Finalize PRD — 2026-10-02T06:12:00.000Z

## Result: ZERO-EDIT OUTCOME — PRD_FINALIZED.md is byte-identical to PRD.md

**Line counts**: PRD.md = 328 lines, PRD_FINALIZED.md = 328 lines, 0% delta. Verified with `diff -q` → BYTE-IDENTICAL.

### Adjudication of every `<step_7_diff>` item

**1. `test_helpers/fixtures.py` — `suspend_agreement_via_breach` (backorder_cancelled True→False; 89.47→85.00)**
Traced to PRD §3.6 (line 200): final rate = shipped / (ordered − cancelled), "where a line's cancelled units are its ordered quantity minus its shipped quantity" — i.e., cancellation only removes units when `backorder_cancelled` is true; and line 202: "units neither shipped nor backorder-cancelled stay in the final rate's denominator." Impl matches verbatim at `implementation/services.py:92-115` (`_line_cancelled_units`, `final_fill`, zero-denominator → 100.00). Both 170/170 = 100.00 (old fixture) and 170/200 = 85.00 (new fixture) are uniquely determined by the PRD; 89.47 was unreachable under the pinned formula. Pure fixture bug → **no edit**.

**2. `test_helpers/assertions.py` — `find_substitution_request` status filter**
The impl behavior the filter serves — a REJECTED request does not block a later REQUEST for the same facility — is pinned by PRD §3.8 (line 222): "One pending request per facility per disruption is the limit: a second `PENDING` request ... is rejected with `ERR_DUPLICATE_SUBSTITUTION`." Impl enforces exactly that at `routes_disruptions.py:172-176` (duplicate check matches only `status == 'PENDING'`). Pure test-helper lookup fix → **no edit**.

**3. `test_04` / `test_06` / `test_07` numeric re-alignments (85.00 = 170/200; 88.00 = 220/250; 90.00 = 270/300)**
All three are direct arithmetic consequences of the PRD-pinned formulas: final rate (line 200/202) and the unit-weighted rolling aggregate (line 204: "total shipped units ... divided by total still-wanted units (ordered minus cancelled)", RECEIVED-only, trailing-90-day window). Impl `services.py:118-143` (`rolling_fill`) and the breach/recovery cycle at `services.py:146-174` implement exactly this. Test-side corrections only → **no edit**.

**4. `test_09` — DECIDE target looked up with `status="PENDING"`**
Same subject as item 2; PRD-pinned → **no edit**.

**5. `implementation/routes_sterilization.py` — missing `ERR_STERILIZATION_IN_PAST` import**
An impl crash bug (NameError → 500) fixed *toward* the already-unambiguous PRD: §3.2 (line 164) pins the guard ("`scheduled_start` must be at or after the current logical clock and `scheduled_end` must be strictly after `scheduled_start`; violations are rejected with `ERR_STERILIZATION_IN_PAST` (HTTP 422)"), §2.6 band 7 pins its priority, §5 pins the code/status. Verified the fixed impl (`routes_sterilization.py:8-11, 33-36`) now matches the PRD wording exactly, including boundary semantics (start == clock accepted, end == start rejected) → **no edit**.

### Pre-edit search log
No edits were committed, so no (a)/(b)/(c) entries are owed. The evidence reads above (PRD lines 200-206, 222, 164; `services.py` fill-rate block; `routes_disruptions.py` duplicate-substitution guard; `routes_sterilization.py` temporal guard; the four touched test files) constitute the trace from each diff item to the PRD sentence that already determines the behavior.

**Conclusion**: every Step 7 change was either a test/fixture mis-expression of a rule the PRD already pins uniquely, or an impl crash fix that brought the code toward an unambiguous PRD. A fresh implementer reading PRD.md alone already has every behavior pinned; PRD_FINALIZED.md is therefore a byte-identical copy.

Orchestrator verification after hand-back: `diff -q workspace/PRD.md workspace/PRD_FINALIZED.md` confirms BYTE-IDENTICAL (328 lines each).

## Step 9: Complete PRD — 2026-10-02T06:30:00.000Z

All edits verified. The file is complete and consistent. Final report:

**Produced** `workspace/PRD_COMPLETED.md` (copied from PRD_FINALIZED.md — confirmed byte-identical to PRD.md — then edited in place).

**Size**: PRD_FINALIZED.md 328 lines / 62,766 chars → PRD_COMPLETED.md 328 lines / 66,237 chars (char-delta **+3,471**; 18 paragraphs touched, no sections added or removed).

**Counts**: 18 ambiguity-pins, 1 mismatch-revision (19 edits total; one paragraph received two edits).

### Changes (one bullet each)

- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped to the nearest bound and non-integer values fall back to defaults, not rejected — implementation/helpers.py:51-60
- §2.3 — insert — ambiguity — list filter params match by exact equality; an unmatched/unknown filter value yields an empty page, not an error — implementation/routes_lots.py:70-79 (same pattern in all list endpoints)
- §2.6 band 3 — revise — ambiguity — existence parenthetical extended to point at §2.9's full body-identifier list — implementation/routes_trays.py:74, routes_agreements.py:34, routes_rebates.py:34, routes_inventory.py:39, routes_disruptions.py:55
- §2.6 band 4 — revise — ambiguity — facility-ownership check applies only where §3 names it (tray create/propose, order placement, substitution REQUEST); all reads skip it — implementation/routes_trays.py:78,135; routes_orders.py:44; routes_disruptions.py:165
- §2.6 band 8 — revise — ambiguity — "duplicate array members" scoped to the arrays with a dedicated rule (lines/components/positions/pending-substitution); `target_categories`, `line_items`, `lot_ids`, `shipped_lines` accept repeats — implementation/routes_orders.py:60-65, routes_trays.py:49-55, routes_inventory.py:50-55, routes_disruptions.py:172-176
- §2.6 final para — revise — ambiguity — ERR_INVALID_REQUEST blanket extended to scalar/array bound violations with no dedicated error (lot `quantity` 0, agreement `end_date` ≤ `start_date`, `committed_fill_rate_pct` >2dp/out of 0–100, etc.); pinned to run after auth + endpoint-level role check, before band 3 — implementation/helpers.py:111-190, routes_agreements.py:24-32
- §2.7 — insert — ambiguity — OCC compares for exact equality and is evaluated after existence/ownership/state, before the payload's business rules — implementation/routes_trays.py:140-143, routes_disruptions.py:117-123
- §2.9 — revise — ambiguity — full enforced body-identifier list (creation `facility_id`s, conversion incumbent/replacement ids, lot/disruption `product_id`, `proposed_product_id`); explicit exemption: allocation and substitution-request `facility_id` are not existence-checked — implementation/routes_disruptions.py:106,157 (no check) vs 161 (proposed product checked)
- §3.2 — revise — **mismatch** — sterilization check order pinned as impl does it: lot existence → temporal window → `batch_code` uniqueness → composition (state/sterile/already-batched) → chamber overlap; also pins `lot_ids` non-empty. Original prose ("Temporal rules run first … composition rules follow: every lot must exist") ordered existence after temporal — implementation/routes_sterilization.py:26-61
- §3.3 — revise — ambiguity — review-gate agreement check compares `end_date` against the logical-clock *date* — implementation/routes_conversion.py:164-167, services.py:56-58
- §3.3 — insert — ambiguity — omitted `notes` on a (re-)evaluation leaves previously stored `evaluation_notes` unchanged — implementation/routes_conversion.py:132-133
- §3.4 — revise — ambiguity — tray component rules evaluated in pinned order: sterile-assembly → duplicate → orderable (prose previously listed duplicate first; consistent with §2.6 bands 6<8<9) — implementation/routes_trays.py:42-60
- §3.6 — revise — ambiguity — `shipped_lines` is non-empty; each entry's `shipped_qty` is a per-event delta added to the cumulative quantity (omitted = 0); `backorder_cancelled` replaces the flag when present, leaves it unchanged when omitted — implementation/routes_orders.py:109-119,135-139
- §3.6 — insert — ambiguity — lazy EXPIRED comparison is date-based with `end_date` inclusive (agreement live through its end_date; expires only when the clock's calendar date is strictly after) — implementation/services.py:52-61
- §3.8 — insert — ambiguity — allocation record's `created_at` is a wall-clock server timestamp, not a logical-clock reading — implementation/routes_disruptions.py:128
- §3.8 — revise — ambiguity — substitution REQUEST `covered_quantity` pinned greater than 0 — implementation/routes_disruptions.py:159
- §3.8 — revise — ambiguity — decision against a non-`PENDING` request pinned to ERR_INVALID_STATE (409) — implementation/routes_disruptions.py:218-220
- §3.8 — revise — ambiguity — REJECT also stamps `decided_by`; stores supplied `rationale` (null when omitted) — implementation/routes_disruptions.py:232-235
- §3.9 — insert — ambiguity — read-time reorder recomputation (single read and list read) refreshes only the computed outputs; it does not bump the program's `version` or `updated_at` — implementation/routes_inventory.py:77-91, services.py:245-247

All five known Step 6 adjudications are now covered by PRD prose: date-based `end_date` comparison (§3.6 + §3.3 edits), per-event-delta `shipped_qty` (§3.6 edit), OCC ordering (§2.7 edit), existence enforcement incl. the allocation/substitution `facility_id` exemption (§2.9 + §2.6 band 3 edits), and read-time recompute not bumping `version` (§3.9 edit).

### IMPL BUG (not patched into the PRD)

- **implementation/routes_orders.py:130-139** — duplicate `product_id` entries within a single SHIPPED event each validate against the *pre-event* cumulative `shipped_qty`, so their sum can exceed `ordered_qty` without error (e.g. `ordered_qty` 10 with two entries of 7 → both pass `0+7 ≤ 10`, then both apply → cumulative 14). This violates the unambiguous PRD rule, quoted verbatim from §3.6: "the cumulative `shipped_qty` on a line across all events may never exceed that line's `ordered_qty` (otherwise `ERR_OVER_SHIPMENT`, HTTP 422)". The fix is to accumulate within the event during validation (or reject duplicate entries per event — note the completed PRD now blesses repeated `shipped_lines` members as legal input, so accumulation is the consistent fix). The implementation should be fixed and the sweep re-run; the PRD was intentionally left stating the rule impl violates.

No other genuine impl violations of unambiguous PRD rules were found; all eight sweep result files show 107/107 passing.

Orchestrator verification after hand-back: PRD_COMPLETED.md exists (328 lines, +3,449 chars vs PRD_FINALIZED.md — matches report modulo measurement method), `ERR_OVER_SHIPMENT` rule intact (2 mentions). Orchestrator adjudication of the single §3.2 mismatch-revision: it re-pins check *ordering* to match impl (existence before temporal), consistent with §2.6's band cascade (existence band 3 < temporal band 7) — the revision brings §3.2 into line with the PRD's own global priority section rather than stripping scaffold intent. Accepted. The reported impl bug is genuine and must be fixed + re-swept (see Step 9b below).

## Step 9b: Post-Step-9 impl fix + re-sweep — 2026-10-02T06:45:00.000Z

Step 9 surfaced one genuine impl bug (orchestrator-fixed, not delegated — small targeted change):

- `workspace/implementation/routes_orders.py` (fulfillment_event, priority-8.92 guard) — duplicate `product_id` entries within a single SHIPPED event each validated against the *pre-event* cumulative `shipped_qty`, so their sum could exceed `ordered_qty` without raising `ERR_OVER_SHIPMENT` (violating PRD §3.6: "the cumulative `shipped_qty` on a line across all events may never exceed that line's `ordered_qty`"). Fix: accumulate a running within-event total per product_id and validate each entry against stored cumulative + running total. Preserves error_id, priority position, and first-failure-wins semantics; consistent with PRD_COMPLETED §2.6 band 8 blessing repeated `shipped_lines` members as legal input.

Re-ran the full 8-round parallel stability sweep after the fix (`prd-bench-local-run --isolation per-test-server`, results.1..8.json regenerated): **all 8 rounds 107/107 passed, 0 failed**. Currency check: no .py file in implementation/, test_suite/, or test_helpers/ is newer than the sweep output — the final sweep reflects the shipped code.
