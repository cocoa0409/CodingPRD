# Worklog — task_2125_custom_crush_winery

## Step 1: Create task directory — 2026-08-21T14:10:40.934876414Z

Created `tasks/task_2125_custom_crush_winery/` and `tasks/task_2125_custom_crush_winery/workspace/`. Index 2125 = highest existing (2124) + 1.

## Step 3: Copy shared files — 2026-08-21T14:10:40.934876414Z

Copied `./INSTRUCTION.md` → `tasks/task_2125_custom_crush_winery/workspace/INSTRUCTION.md` (done early; no dependency on Step 2).

## Step 2: Generate scaffold — 2026-08-21T15:23:30.782031156Z

All three scaffold artifacts are generated, lint-clean, and self-audited.

## Generated files

- `/home/ubuntu/github/CodingPRD/tasks/task_2125_custom_crush_winery/SCAFFOLD.yaml` (§1.0–§1.7, 153 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_2125_custom_crush_winery/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 117 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_2125_custom_crush_winery/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 287 KB)

## Complexity profile
`quota_allocation` primary × `compliance_audit` secondary; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation; topology `graph` (self-referential blend lineage via `Lot.parent_lot_id`); shape `parallel`; role model `segregation_of_duties`; consistency `immediate`. `api_prefix: "/"` (flat peer collections at root — required for lint check (f) segment derivation).

## Contents
- **13 entities**: Client, Contract, Vessel, VesselAllocation, HarvestIntake, Lot, BlendTrial, WorkOrder, BottlingLine, BottlingRun, DryGoodsItem, TTBReport, ReleaseOrder (16 FKs, all reverse-reachable).
- **12 state machines / 74 transitions**: Lot carries two independent axes (`production_status` × `bond_status`); cycles on Contract (DRAFT↔PENDING_SIGNATURE, ACTIVE↔SUSPENDED), Vessel (CLEAN↔DIRTY), BlendTrial (SUBMITTED↔REVISION_REQUESTED), WorkOrder (BILLED→DISPUTED→COMPLETED→BILLED), TTBReport (FILED→AMENDED→PREPARED→FILED), BottlingLine (AVAILABLE↔MAINTENANCE); branching with divergent side-effect sets on VesselAllocation (CANCEL vs RELEASE) and ReleaseOrder (TAXPAID_REMOVAL vs TRANSFER_IN_BOND).
- **4 concurrency rules**, all OCC-on-parent-`version` (Vessel ×1, Contract ×3), each with a required `expected_*_version` input and a matching version bump.
- **10 calculations**: intake_yield, crush_fee, lot_composition, blend_projection, work_order_billing, storage_accrual (2 variants), bottling_schedule, dry_goods_allocation, ttb_reconciliation (2 variants), excise_tax.
- **22 validation rules** (priorities 1–90), **60 endpoints** (incl. `POST /_clock/set_current_utc` with a fixed `2026-08-01T00:00:00Z` default that also stamps `created_at`/`updated_at`), **51 error codes**, **4 roles** (FacilityAdmin/CellarSupervisor/ComplianceOfficer opaque, ClientRep `entity_backed:Client`).

## Difficulty design (§1.8) — 18 instances, 9 rules × 2
Rule 1 storage_accrual (money, 237738 vs 303333 cents) / ttb_reconciliation (gallons, produced 2431.25 vs 3411.25). Rule 2 mode (b) crush-fee round-per-tier-then-sum (224157 vs 224156) / mode (c) work-order discount tier from the undiscounted basis (49400 vs 52000). Rule 3 Lot parallel axes / BlendTrial revision cycle to round 3. Rule 4 depth-4 blend-execute cascade / depth-3 client-suspend cascade. Rule 5 state-vs-fiscal / SoD-vs-temporal (disjoint category pairs). Rule 6 brix step at exactly 25.00 / empty `intake_ids`. Rule 7 WorkOrder→Contract / ReleaseOrder→TTBReport. Rule 8 Vessel half-open + 48 h trailing buffer / BottlingLine closed interval where endpoints touching collide. Rule 9 gallons invariant (2431.25 across execute+unwind) / dry-goods unit invariant (11500 across reserve+cancel).

## Corner design (§1.9) — 76 instances (73 with recipes, 3 `excluded_because` stubs)
entities 10, state_machines 11, calculations 11, validations 11, endpoints 5, errors 17, rbac 5, cross_cutting_layers 5, consistency_model 1.

## Verification
`scaffold_lint.py` verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     73
  Calls scanned (§1.8+§1.9):  1155

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Additional self-audit (custom script, 0 problems): placeholder closure over all 1155 calls plus assert lines; global name uniqueness; every `grounds[]` ref resolves into §1.1–§1.7; no forbidden concurrency vocabulary; every one of the 51 error codes exercised by at least one instance and referenced by §1.2/§1.4; every stub's `difficulty_instance` exists; all entity fields typed/sourced/described; all transitions carry preconditions and side effects; all endpoint roles in the RBAC matrix; all OCC endpoints take a required `expected_*_version` and bump the parent version. Every formula-derived assert literal was computed in Python against the pinned constants (e.g. 237738/303333, 224157, 49400, 1583.92, 13624, 1188.77, 3186000).

Scenario text is stored verbatim, typo included.

## Step 4: Generate PRD — 2026-08-21T15:38:35.587090302Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2125_custom_crush_winery/workspace/PRD.md` — 438 lines, ~14,100 words, 111 KB, written incrementally in eight appends (header/§1 → §2.1 → §2.2 verbatim → §2.3–2.5 → §2.6–2.10 → §3.1–3.2 → §3.3–3.4 → §3.5 → §3.6 → §3.7 → §3.8–3.9 → §4/§5 generated from the YAML), each verified after landing.

**Section structure**
- §1 Introduction (3 paragraphs: bonded-premise framing, scope of the harvest arc, the two design pressures — segregation of duties and stale-read protection)
- §2 Global Specifications — 10 domain-derived subsections: 2.1 Access Control and Acting Identity · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination (+ per-collection list filters) · 2.4 Resource Identity, Versioning and the Facility Clock · 2.5 The Request Evaluation Ladder (all 22 priorities as ordered rungs) · 2.6 Stale-Parent Rejection on Shared Ledgers (4 OCC rules) · 2.7 Gallons, Cents and Rounding Discipline · 2.8 Cascade Reconciliation Across the Bonded Estate · 2.9 Segregation of Duties and the Bonded-Book Freeze · 2.10 Resolving Path Identifiers
- §3 Business Logic — 9 subsections along the harvest timeline: onboarding/contracts · cooperage · crush pad · lot creation & production axis · blend trials · contract ledger (work orders + storage accruals) · bottling · removal from bond · TTB reporting
- §4 Endpoint table (4 columns, 60 rows) · §5 Error table (2 columns, 51 rows). Document ends at §5 — no audit footer.

**Coverage audit (scripted against SCAFFOLD.yaml, nothing missing)**
- 13 entities: all named; 137 entity field names present in backticks
- 12 state machines: every state string present (Client 3, Contract 5, Vessel 3, VesselAllocation 4, HarvestIntake 5, Lot 10 across both axes, BlendTrial 7, WorkOrder 7, BottlingRun 4, BottlingLine 2, TTBReport 4, ReleaseOrder 5); all 67 transitions have both endpoints named in prose with their preconditions/error ids and side effects
- 10 calculations: all formulas rendered as prose with every constant embedded (2000 lb/ton, 165.0 base yield, 25.00/5.0/2.5/22.00/3.0 brix steps, 25/75-ton crush bands at full/nine-tenths/eight-tenths, 75.00 and 85.00 label thresholds, 0.55 brix factor, 5 % max blend loss, 25 % rush, 1,000,000/3,000,000-cent discount tiers at 5 %/10 %, 30-day month, 3785.411784 mL/gal, 24/12/6 bottles per case, 2 labels per bottle, 30,000/130,000-gallon excise bands at 7/17/107 cents)
- 22 validation rules: all present as rungs 1,2,3,5,10,15,20,30,35,40,50,55,60,62,65,70,72,75,78,80,85,90, each with its error id(s) and full `applies_to` endpoint enumeration
- 60 endpoints: all in the §4 table; 51 error codes: all in §5 **and** all 51 additionally mentioned in §2/§3 narrative; 4 roles with exact spelling and `identity:` semantics translated (3 opaque, `ClientRep` entity-backed with all seven ownership resolution paths)

**Hard Contracts**
```
Field coverage check:
- entities[].fields: 137 required, 137 present, 0 missing
- endpoints[].request_body: 75 required, 75 present, 0 missing
- endpoints[].query_params: 23 required, 23 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 22 checked, 22 expressed in prose (ordered ladder), 0 missing
- concurrency_rules[] OCC rejections: 4 checked, 4 expressed (write_endpoint + expected_<parent>_version + error_id + 412), 0 missing
- state_machines[].transitions: 67 checked, 67 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 22 checked, 22 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 60 checked, 60 expressed, 0 missing
- entities[].fields[] structured content: 137 checked, 137 reconstructible from prose, 0 missing
- sibling-branch symmetry: 4 groups checked (allocation CANCEL vs RELEASE, release TAXPAID_REMOVAL vs TRANSFER_IN_BOND, storage OCCUPANCY vs VESSEL_FOOTPRINT, TTB BONDED vs GROSS), 4 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1005
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two places where the scaffold left a shape undefined and the PRD had to fix a single reading so the implementer is not guessing: the traceability read's `ancestor_lot_ids` / `total_source_gallons` (defined as transitive manifest ancestry, and intake `estimated_gallons` total for `INTAKE` lots vs component-volume total for `BLEND` lots), and `component_manifest`'s `pct_of_blend` (component volume ÷ `total_component_gallons` × 100, half-up to 2 dp). Neither design file was opened, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-08-21T16:11:35.805452275Z

Test generation complete and audited.

## Summary

**Test files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2125_custom_crush_winery/`)

`test_helpers/` — `__init__.py`, `types.py`, `api_client.py` (60 endpoint methods), `api_errors.py` (51 error ids + status map, registered with the framework), `assertions.py` (13 entity assertions + conservation/reconciliation invariants + `round_half_up`), `factories.py`, `constants.py`, `test_users.py` (opaque-role constants + `make_client_rep_headers` for the `entity_backed:Client` role), `fixtures.py` (685 lines, 5 tiers of composite setup).

`test_suite/` — `conftest.py` plus:

| file | tests |
|---|---|
| test_01_clients_and_contracts.py | 13 |
| test_02_cooperage_and_allocations.py | 16 |
| test_03_crush_pad.py | 12 |
| test_04_lots_and_labels.py | 9 |
| test_05_blend_trials.py | 10 |
| test_06_contract_ledger.py | 10 |
| test_07_storage_fees.py | 5 |
| test_08_bottling.py | 13 |
| test_09_bond_and_reporting.py | 15 |
| test_10_platform_rules.py | 9 |

**Total: 112 tests**, all collected by pytest.

**Coverage**
- Queue A (difficulty): **18/18 instances covered, 39 tests**, minimum 2 tests per instance.
- Queue B (corner): **73/73 non-stub instances covered, 73 tests**, 1 test each.
- The 3 `excluded_because:` stubs were **not** translated; all three `difficulty_instance` cross-references resolve (`corner_storage_accrual_read_is_side_effect_free` → `storage_accrual_occupancy_versus_vessel_footprint`; `corner_dual_variant_reading_default_is_occupancy` → same; `corner_derived_bond_gallons_after_partial_taxpaid_removal` → `lot_bond_axis_cycles_while_production_axis_holds_at_aging`).

**Instances SKIPPED: none.** Every non-stub instance passed the PRD-first two-condition filter.

**One assertion relaxed** (test still emitted, instance still covered): in `Corner/rbac/corner_client_rep_cannot_read_another_clients_contract` I dropped the yaml's second assertion that `GET /contracts?client_id={other}` as a foreign `ClientRep` returns `ERR_CLIENT_SCOPE_VIOLATION`. PRD §2.1 says "List reads performed by a `ClientRep` are always narrowed to that caller's own client", which a faithful PRD-only reader could implement as a 200 with an empty page rather than a 403 — not uniquely derivable. The single-resource `GET /contracts/{id}` 403 (PRD §2.5 rung 20) is asserted instead, plus a FacilityAdmin control read and an owning-ClientRep read.

**Audits run and passing**
- Every test docstring ends with exactly one `Design:` line; every tag resolves to a real instance; no stub is translated; no dual-tagged or untagged test.
- All 196 quoted PRD citations survive a normalized-whitespace literal match against `PRD.md`; every test carries at least one verbatim citation of ≥8 words.
- All 51 asserted `error_id`s are named in PRD prose (§2/§3), not only in the §5 table.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no "scaffold"/§1.x references leaked into generated code.
- Every literal expected value in the suite (yields 800.00/825.00/840.00/1565.00/866.25/3135.00/12540.00, crush fees 950000/1009688/224157/3186000, storage 237738/303333, billing 50000/52000/49400/185250/46313/273563/27000, blend 1583.92/32.33/980.00/14.19, gallons 1188.77/594.39/451.73/237.75, excise 700/3500/13624, TTB 2431.25/3411.25/20.00/1000.00/2311.25) was recomputed independently with `ROUND_HALF_UP` decimal arithmetic and matched.

Worked purely from the four input files plus the skill spec; no sibling task and no `workspace/implementation/` was read.

## Step 6: Generate implementation — 2026-08-21T16:12:25.402753170Z

Implementation complete and verified.

## Files (`workspace/implementation/`, 3889 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 9 | Guarded `pip install` + `exec python3 app.py`, `$PORT` (default 10000), `0.0.0.0`, foreground |
| `requirements.txt` | 1 | Flask>=3.0 |
| `app.py` | 47 | App factory, blueprint registration, `ApiError`/HTTP/unhandled error handlers |
| `store.py` | 134 | In-memory `Database` (13 dicts + loss-event book), logical clock, ISO helpers, `rhu` round-half-up, `touch` |
| `errors.py` | 155 | All 51 error IDs + HTTP status map + `ApiError` |
| `envelope.py` | 83 | `meta`/`response_type`/`data` envelope, `req_` ids, Decimal-preserving body parse |
| `validation.py` | 239 | Rung-5 field validators (types, enums, ranges, decimal places, components, pagination) |
| `auth.py` | 94 | Rungs 1–3 (`X-User-ID`/`X-User-Role`, endpoint roles, per-action actors), rung 20 scoping |
| `calc.py` | 306 | All 10 calculations + pinned constants |
| `domain.py` | 462 | Lookups, ownership resolution, reconciled projections, release cascade, traceability, storage projection, dual-variant TTB reconciliation |
| `helpers.py` | 67 | Listing/filtering/pagination, rung-30 helper |
| `routes/` (13 modules) | 2292 | One module per resource group |

## Coverage audit

- **Endpoints: 60/60.** Programmatic diff of `app.url_map` against the PRD §4 table — zero missing, zero extra. A single live run (`smoke5`) exercised **all 60 with a 2xx**.
- **Error codes: 51/51** reachable — each is raised from concrete code paths (audited by name across all modules; none appears only in `errors.py`). Live-verified in the smoke suites: all 4 OCC/stale-parent and SoD rejections, both duplicate/uniqueness families, vessel 48h-buffer overlap, closed-interval line conflict, daily capacity, dry-goods shortage, appellation ineligibility, destination-permit pairing, reporting-period freeze, bonded-inventory and allocations-outstanding gates.
- **State machines:** all 12 (74 transitions) including Lot's two independent axes, the four cyclic machines (contract, blend revision rounds, work-order billing cycle, TTB amendment cycle) and both branching machines with divergent side effects.
- Calculations spot-checked against hand-computed PRD values: marginal crush across the 25-ton boundary with per-tier rounding (364178¢), the discontinuous Brix step at exactly 25.00 (4800 gal), five-step work-order billing, blend projections + `pct_of_blend`, ceil-to-quarter `run_hours`, dry-goods waterfall ranking, marginal excise, and both storage variants (`VESSEL_FOOTPRINT` strictly larger). **Both TTB variants reconcile to `variance_gallons == 0.00` on the same data**, and the two §2.8 conservation invariants hold across blend execute→unwind and reserve→cancel.

## Constraint compliance

Storage is in-memory dicts only — grep confirms no file I/O, sqlite, pickle or `/tmp` anywhere; the only `json.dumps` builds the HTTP response. No seeding: the store is empty at import and the clock reads exactly `2026-08-01T00:00:00Z` on every boot. No sibling task or design-index file was read.

## Boot check

`PORT=43583 bash start.sh` (backgrounded): **HTTP ready in ~0.5s**. `POST /clients` → 201 with the full envelope; `GET /clients/{id}` → 200 identical; `POST /contracts` → 201; `GET /contracts?limit=1` → 200 with `limit/offset/total_count/has_more` in `meta`; unauthenticated `GET /clients` → 401 `ERR_UNAUTHENTICATED`. Fresh boot showed the clock at `2026-08-01T00:00:00.000Z` and an empty store. Server killed; port released cleanly, no stray processes left.

## Ambiguities resolved (worth knowing if tests disagree)

1. **Ladder vs. §3 prose on double faults** — §2.5's explicit rung order governs the named rung errors (so OCC 412 → cross-entity 409 → SoD 403 on `/work-orders/{id}/bill`, and client-ACTIVE before volume on release approve). Workflow-specific checks with no rung (e.g. commit's cross-contract → already-housed → capacity) follow §3 prose verbatim.
2. **Version bumps on recomputation** — per §2.4/§2.8 every recompute is a full mutation. Client suspend cascade bumps a contract twice (status + one recompute, only when allocations were actually cancelled); blend-execute hop 4 recomputes once *per contract* (deduped), per PRD §3.5 wording.
3. **System-triggered release** clears the consumed/bottled lot's `current_vessel_id` inside the same mutation as the CONSUMED/BOTTLED transition — consistent building, no extra version bump either way.
4. **Client derived figures** (`bond_gallons_in_bond`, `taxpaid_gallons_ytd`, `last_filed_period_end`) are computed at read time so they never drift; the client's `version` advances only where a recompute is explicitly declared.
5. **Datetimes**: client-supplied instants are echoed verbatim; server-stamped/derived instants (`created_at`, `scheduled_end`, `current_utc`, …) are normalized to 3 fractional digits.
6. **TTB loss line**: press losses and declared blend losses are booked as timestamped events (an unwind books the compensating negative), which is what makes both variants balance to zero across execute *and* unwind.


## Step 7: Run tests and iterate — 2026-08-21T16:19:53.279250384Z

Clean exit — all 8 parallel rounds passed 112/112.

## Summary

**Iterations run:** 2 (each a full 8-round parallel `per-test-server` sweep, 112 tests per round).

- Iteration 1: 106/112 in all 8 rounds, 6 failing tests, identical in every round (no flakiness).
- Iteration 2 (after fix): **112/112 in all 8 rounds**, 0 failed / 0 errors / 0 skipped. Union of failures across rounds: none.

**Tests deleted:** none. All 6 failures passed STEP 1a (PRD verbatim-covers) and STEP 1b (uniquely derivable), and STEP 2 found the tests faithful — so this was a genuine STEP 3 implementation bug.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_2125_custom_crush_winery/workspace/implementation/validation.py` — `v_datetime()` now returns `iso(parsed)` instead of the raw client string (and imports `iso` from `store`). It previously documented "inputs are echoed back verbatim", which violated PRD §2.7: *"Timestamps returned by the API are ISO 8601 UTC with three fractional-second digits, including derived instants such as a bottling run's `scheduled_end`."* This is the single upstream cause of all 6 failures — every client-supplied instant (`start_at`, `end_at`, `scheduled_at`, `scheduled_start`, `effective_from`, `effective_to`, `period_start`, `period_end`, `through_at`) was stored and re-served as `2026-11-01T00:00:00Z` rather than `2026-11-01T00:00:00.000Z`, and it propagated into derived fields too (a vessel's `last_released_at`, stamped from the allocation's `end_at`, and a contract's `storage_billed_through`).

2. `/home/ubuntu/github/CodingPRD/tasks/task_2125_custom_crush_winery/workspace/implementation/routes/contracts.py` — `storage_accrual_projection()` now echoes `"through_at": iso(through_dt)` instead of the raw query-string value (the projection reads `through_at` from the query string, so it never passed through `v_datetime`); added `iso` to the `store` import.

**Notes on correctness of the fix rather than a workaround:** all downstream comparisons in the implementation use the parsed `_dt` internals (`_ps_dt`, `_pe_dt`, `_billed_through_dt`, etc.), never the stored strings, so normalizing the stored strings changed only the serialized representation. No implementation check was removed or weakened, no endpoint/field/side-effect was added, storage remains in-memory dicts only (grep confirms no file I/O, sqlite, pickle, or `/tmp` anywhere), and nothing is seeded at startup.

**Orchestrator verification:** independently re-read all 8 `results.{1..8}.json` — every round reports `passed=112 / total=112 / failed=0`.

## Step 8: Finalize PRD — 2026-08-21T16:24:38.942754354Z

`workspace/PRD_FINALIZED.md` is written: two sentence-level edits, both tracing to the two Step 7 implementation fixes.

**Size:** PRD.md 437 lines / 111,101 chars → PRD_FINALIZED.md 437 lines / 111,599 chars. Line delta 0 (0.00%); character delta +494 (+0.445%). Only two lines differ (141, 261).

**Changes**

- §2.7 (Gallons, Cents and Rounding Discipline), line 141 — revise — extended the existing "Timestamps returned by the API are ISO 8601 UTC with three fractional-second digits" sentence to state that client-supplied instants are also covered: a supplied instant is parsed, carried to UTC and re-rendered in that shape (finer-than-millisecond precision dropped, not rounded) before being stored on a resource or echoed back, so a client string in another shape does not come back as written; plus a clause that server-side comparisons use the full-precision instant, not its rendering — `implementation/validation.py:142-166` (`v_datetime` returning `iso(parsed)`), `implementation/store.py:52-61` (`iso`), `implementation/store.py:63-76` (`parse_iso`).
- §4.9-equivalent storage-projection prose, line 261 — revise — "the `through_at` echoed back" → "the `through_at` echoed back in that same rendered shape" — `implementation/routes/contracts.py:179`.

**Pre-edit search log**

Edit 1
- (a) Subject: the serialized representation of every instant the API returns or stores, specifically client-supplied ones now normalized by `v_datetime`.
- (b) Paths enumerated (grepped `v_datetime|parse_iso|iso\(` across all of `implementation/`, then read each site): `store.py:52` `iso` (sole formatter, truncates `microsecond // 1000`), `store.py:63` `parse_iso` (accepts `Z`, offsets, naive→UTC), `validation.py:142` `v_datetime`; every `v_datetime` caller — `routes/allocations.py:45-46,101,108` (`start_at`/`end_at` stored rendered, `_start_dt`/`_end_dt` used for overlap and contract-window tests), `routes/contracts.py:49-50` (`effective_from`/`effective_to`, `_eff_from_dt`/`_eff_to_dt`), `routes/contracts.py:189-199` (`through_at` → `storage_billed_through`, `_billed_through_dt`), `routes/ttb.py:42-43` (`period_start`/`period_end`, `_ps_dt`/`_pe_dt` overlap + period-closed), `routes/work_orders.py:50` (`scheduled_at`), `routes/bottling.py:110,156,165` (`scheduled_start` stored rendered, `scheduled_end` = `iso(end_dt)`, `_start_dt.date()` daily-capacity test), `routes/clock.py:16-18` (`db.clock` holds the full-precision parsed instant; `current_utc` is its rendering); server-stamped/derived sites `envelope.py:33`, `store.py:106,122`, `routes/intakes.py:70`, `routes/lots.py:168`, `routes/blends.py:314`, `routes/release_orders.py:170`, `routes/ttb.py:147`, `domain.py:241,255` (`last_released_at` = allocation's already-rendered `end_at`). Also checked `helpers.py:44-56` and `request.args` usage to confirm no list filter or error message echoes a raw instant.
- (c) Adjustment: added the trailing clause "Comparisons the server makes against a supplied instant are made against the instant itself at full precision, not against its rendering," because every interval/window/daily-capacity check reads the parsed `_dt` internals, not the truncated string — without it, "re-rendered … before it is stored" could be read as truncating the value used for comparison. Also scoped the truncation claim to the rendering rather than to the stored instant, and said "carried to UTC" rather than requiring a `Z`-form input, since `parse_iso` accepts offsets and naive strings.

Edit 2
- (a) Subject: the `through_at` value echoed by `GET /contracts/{id}/storage-accrual` (a query-string instant that never passes through `v_datetime`).
- (b) Paths enumerated: `routes/contracts.py:154-181` (the projection: `parse_iso(raw_through)`, echoes `iso(through_dt)`, echoes the resolved `variant` including the `OCCUPANCY` default), `routes/contracts.py:184-207` (the POST accrual, which stores the `v_datetime`-rendered `through_raw` into `storage_billed_through`), `domain.storage_projection` callers for both, and PRD lines 84 / 265 / 328-329 which also mention `through_at`.
- (c) Adjustment: used "in that same rendered shape" pointing back at §2.7 rather than restating the format, so the sentence stays true of both the query-string projection path and the body-supplied posting path, and does not claim anything about the `variant` echo (which returns the resolved value, matching the existing "the `variant` used" wording).

No other PRD prose conflicts: grepped `PRD_FINALIZED.md` for "verbatim", "as supplied", "exactly as" — line 97 (clock repositioning) and line 265 (`storage_billed_through` advance) both remain consistent with the new §2.7 wording.

**Orchestrator note:** an earlier append landed in `workspace/implementation/worklog.md` because a prior `cd` persisted across bash calls; the Step 7 entry was merged back into this file and the stray removed. All later appends use absolute paths.

## Step 9: Complete PRD — 2026-08-21T16:38:27.401918245Z

`PRD_COMPLETED.md` is written. Full walk of all 3,889 implementation lines (10 core modules + 13 route modules, 60 endpoints, 51 error codes, 12 state machines, 10 calculations, 22 validation rungs) completed; endpoint set, role lists, and error-code/status table were also verified programmatically as exact matches (60/60 endpoints, 60/60 role lists, 51/51 error codes) and required no change.

**Summary**

- Source file: `workspace/PRD_FINALIZED.md` — 437 lines / 111,415 chars → `workspace/PRD_COMPLETED.md` — 437 lines / 116,915 chars (**+5,500 chars**, no new lines, no new sections).
- Counts: **31 ambiguity-pins**, **9 mismatch-revisions** (40 changes total).

- §2.1 — revise — mismatch — resolution-path list omitted `Client` (self), `HarvestIntake` and `BottlingRun`, which impl does scope; added that `Vessel`/`BottlingLine` resolve to no client and are never scoped — routes/clients.py:61, routes/intakes.py:83, routes/bottling.py:176, routes/vessels.py:52
- §2.1 — insert — ambiguity — ClientRep list narrowing excludes vessels and bottling lines — helpers.py:46, routes/vessels.py:59
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is also `ERR_INVALID_REQUEST` — validation.py:224
- §2.3 — insert — ambiguity — default sort ties on equal `created_at` broken by storage sequence — store.py:127
- §2.5 rung 15 — revise — mismatch — guard list missing `POST /contracts/{id}/transitions` (SUBMIT raises `ERR_INVALID_INTERVAL`) — routes/contracts.py:107
- §2.5 rung 40 — revise — mismatch — guard list missing `/blend-trials/{id}/revise`, `/ttb-reports/{id}/transitions`, `/release-orders/{id}/transitions` — routes/blends.py:151, routes/ttb.py:116, routes/release_orders.py:118
- §2.8 — revise — mismatch — `occupied_days` is stored (0 until release, written once at release), not clock-derived; only `aging_days` is read-time — domain.py:243, routes/allocations.py:106
- §2.8 — insert — ambiguity — client's three derived figures are read-time projections; pinned the exact event set that advances the client's `version` (and that bond-status-only moves do not) — domain.py:284, routes/lots.py:94, routes/release_orders.py:127
- §3.1 — insert — ambiguity — contract SUSPEND increments `version` a second time only when an allocation was actually cancelled — routes/contracts.py:132
- §3.2 — insert — ambiguity — decommissioning a vessel with a live allocation is `ERR_INVALID_STATE` — routes/vessels.py:79
- §3.2 — insert — ambiguity — window containment endpoints: `start_at ≥ effective_from`, `end_at ≤ effective_to` — routes/allocations.py:67
- §3.2 — insert — ambiguity — cancelling a RESERVED allocation recomputes contract counters and bumps contract `version` — routes/allocations.py:196
- §3.2 — insert — ambiguity — commit answers with the allocation, not the housed lot — routes/allocations.py:180
- §3.3 — insert — ambiguity — `rejection_reason` optional, stored null when omitted — routes/intakes.py:108
- §3.4 — insert — ambiguity — `vintage_year` is a whole number — routes/lots.py:38
- §3.5 — insert — ambiguity — component-array shape violations (<2 entries, repeated id, non-positive volume) are `ERR_INVALID_REQUEST` — validation.py:192
- §3.5 — insert — ambiguity — `total_component_gallons` rounded half up to 2 dp — calc.py:195
- §3.5 — insert — ambiguity — component `PRESSED`/`AGING` gate is `ERR_INVALID_STATE`, and ownership → status → volume order applies at creation, submission and revision — routes/blends.py:55
- §3.5 — insert — ambiguity — zero `projected_blend_gallons` on APPROVE is `ERR_INVALID_STATE`, tested before the label check — routes/blends.py:198
- §3.5 — insert — ambiguity — `revision_note` optional, stored null when omitted — routes/blends.py:175
- §3.5 — insert — ambiguity — blend lot minted with null `vintage_year`/`current_vessel_id`/`parent_lot_id` and `cases_bottled` 0 — routes/blends.py:297
- §3.5 — insert — ambiguity — hop 1 clears the consumed source lot's `current_vessel_id` in the same mutation, so its `version` advances exactly once — routes/blends.py:341
- §3.5 — insert — ambiguity — execute answers with the trial, not the new lot — routes/blends.py:364
- §3.5 — insert — ambiguity — unwind does not compensate the housing side (allocation stays RELEASED, vessel stays DIRTY, `current_vessel_id` stays null) — routes/blends.py:228
- §3.6 — insert — ambiguity — `material_cost_cents` is a whole number of cents ≥ 0 — routes/work_orders.py:53
- §3.6 — revise — mismatch — SCHEDULE tests the lot's finished state before contract-ACTIVE (PRD listed the reverse) — routes/work_orders.py:118
- §3.6 — insert — ambiguity — state-dependent completing actor is checked after the declared-transition test, still `ERR_FORBIDDEN_ROLE` — routes/work_orders.py:131, auth.py:89
- §3.6 — insert — ambiguity — `dispute_reason` optional, stored null when omitted — routes/work_orders.py:110
- §3.6 — insert — ambiguity — storage projection rejects missing/unparseable `through_at` and unrecognised `variant` with `ERR_INVALID_REQUEST` before resolving the contract id — routes/contracts.py:156
- §3.7 — insert — ambiguity — `cases_per_hour` and `changeover_minutes` are whole numbers — routes/bottling.py:50
- §3.7 — insert — ambiguity — `initial_units` is a whole number ≥ 0 — routes/dry_goods.py:25
- §3.7 — insert — ambiguity — receipt `units` is a whole number > 0 — routes/dry_goods.py:61
- §3.7 — revise — mismatch — foreign-client dry goods are simply ineligible, so the caller sees `ERR_DRY_GOODS_SHORTAGE`; `ERR_CROSS_CONTRACT_REFERENCE` is reserved for a lot resolving to no client — routes/bottling.py:217
- §3.7 — insert — mismatch — `cases_actual` bounds are `ERR_INVALID_REQUEST`, and the `cases_planned` ceiling is tested after the declared-transition test (not at rung 5) — routes/bottling.py:207
- §3.7 — insert — ambiguity — completion hop 2 also clears `current_vessel_id` and is a second lot mutation (`version` +2 overall) — routes/bottling.py:291
- §3.8 — insert — ambiguity — `cases` is a whole number ≥ 0 — routes/release_orders.py:43
- §3.8 — insert — ambiguity — `rejection_reason` optional, stored null when omitted — routes/release_orders.py:100
- §3.9 — revise — mismatch — a PREPARE that omits `variant` leaves the stored variant untouched (not reset to `BONDED`), so a re-prepare after amendment keeps `GROSS` — routes/ttb.py:107
- §3.9 — insert — ambiguity — AMEND leaves `filed_by_user_id` and `filed_at` standing — routes/ttb.py:153
- §4 — revise — mismatch — `POST /ttb-reports` row claimed creation pins the variant; creation always opens at `BONDED` and preparation selects the reading — routes/ttb.py:64
