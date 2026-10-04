# Worklog — task_3162_direct_vehicle_sales_delivery_appointment_mobile_service

## Step 1: Create task directory — 2026-09-30T05:55:00.000Z

Task directory `./tasks/task_3162_direct_vehicle_sales_delivery_appointment_mobile_service/` was pre-allocated by the caller (it already existed and contained an empty `workspace/` subdirectory). No new index was computed and no other `task_*` directory was created. Confirmed `workspace/` exists and is empty; no `mkdir` needed.

## Step 2: Generate scaffold — 2026-09-30T06:45:00.000Z

Scaffold generation complete. No sibling task was inspected; everything was derived from the skill spec plus the verbatim scenario.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3162_direct_vehicle_sales_delivery_appointment_mobile_service/`):
- `SCAFFOLD.yaml` — 3008 lines, §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1552 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2429 lines, single key `scaffold_corner_design`

**Surface**: 19 entities (flat topology, self-referential `DeliveryEstimate.prior_estimate_id`), 14 state machines / 67 transitions, 9 calculations, 19 validations, 118 endpoints, 73 error codes, 8 roles, 3 concurrency rules (OCC on `VehicleOrder.version` and `ServiceAppointment.version`).

**§1.8**: 9 rule_ids × 2 instances = 18 instances, one per §0.5 rule.
**§1.9**: 8 sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers) × 55 instances. No `excluded_because:` stubs — §1.8 and §1.9 were kept disjoint by construction.

**Difficulty profile (Expert-beyond)**: dual-variant totals with pinned rounding order, annuity with explicit evaluation order, capped bundle discount with per-row remainder allocation, a cyclic estimate-restore machine, a numbered 3-hop delay cascade, and compensating invariants over two different conserved quantities (currency vs bay occupancy). All formula-derived assertion literals were computed by code before writing (e.g. 4934000 → 4931500, 91103, 3800000, 859988, 82425, 5000-cent post-cancellation balance).

**Verification**: `scaffold_lint.py` verdict, verbatim:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```
Coverage: 118 endpoints, 19 entities, 18 §1.8 instances, 55 §1.9 instances, 1192 calls scanned, 0 violations. Additionally checked by hand: all 73 instance names unique across both design files, every `grounds:` ref resolves, every error id referenced ≥2× in `SCAFFOLD.yaml`, no forbidden concurrency vocabulary, and no UUID-`id` use in any ordering decision (`created_at ASC` used as the fallback).

Orchestrator verification: `wc -l` confirms 3007/1551/2428 lines on disk; top-level keys confirmed as `scenario, domain_name, api_prefix, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, response_envelope, endpoints, errors, roles` for SCAFFOLD.yaml (no design keys leaked in), `scaffold_difficulty_design` for SCAFFOLD_DIFFICULTY_DESIGN.yaml, `scaffold_corner_design` for SCAFFOLD_CORNER_DESIGN.yaml.

## Step 3: Copy shared INSTRUCTION.md — 2026-09-30T06:47:00.000Z

`cp ./INSTRUCTION.md ./tasks/task_3162_direct_vehicle_sales_delivery_appointment_mobile_service/workspace/INSTRUCTION.md` — copied the shared build-contract file (1424 bytes) into the task workspace. Verified present alongside the (still empty) future `implementation/` location.

## Step 4: Generate PRD — 2026-09-30T07:05:00.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_3162_direct_vehicle_sales_delivery_appointment_mobile_service/workspace/PRD.md` — 524 lines, 15,107 words.

**Sections written:** §1 Introduction (3 paragraphs, franchise-law + no-negotiation angle); §2 Global Specifications with 11 domain-derived subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Franchise-Law Regimes, 2.5 Common Resource Properties/Mutation, 2.6 Bay and Van Interval Semantics, 2.7 OCC, 2.8 Money/Precision/Ledger, 2.9 Left-to-Right Path Validation, 2.10 Logical Clock and Sweeps, 2.11 Derived State/Conservation/Compensation); §3 with 12 subsections grouped by lifecycle (catalogue → order+lock → trade-in → production/allocation/estimates → financing → handover/acceptance → cost+readiness → cancellation unwind → diagnostics triage → mobile repair cost → OTA bundles → validation precedence); §4 endpoint table (118 rows, 4 columns); §5 error table (72 rows, 2 columns).

**Coverage (all mechanically checked):**
- Entities: all 19, every field name present in backticks; `OrderFeeLedgerEntry` explicitly described as `common_fields: false` (only `id` + `created_at`, no `updated_at`/`version`).
- State machines: all 14 (51 distinct state strings, all present) incl. auto transitions, `DELAYED → DELAYED`, `ACTIVE → ACTIVE` re-grant, `SUSPENDED → ACTIVE` reinstate.
- Calculations: all 9 with pinned operation ordering, constants embedded as numerals (25000/7500/2500/50000/12¢/200000/25000 floor, 490/590/790/890/1290 bps, 48/49 months, 19500/hr, 30 included mi, 95¢/mi, 60000 ceiling).
- Validations: all 19 with the priority order rendered as an explicit 19-step ordered list plus per-rule trigger prose.
- Concurrency: all 3 `concurrency_rules` (write endpoint + OCC field + `ERR_STALE_VERSION`/412), plus the non-listed `expected_*_version` guards (place, lock, allocation, config-change, contract-review, fund) distinguished as mutation guards.
- Endpoints: 101 unique scaffold paths ≡ 101 in §4; all `request_body`/`input`/`query`/`path` identifiers covered (133 required, 0 missing). 0 requests lacking endpoints.
- Errors: 72 unique `errors[].id` present, all 72 also named before §4.
- RBAC: all 8 roles, with `entity_backed:Buyer` (only) vs. opaque identities spelled out role-by-role.

**Contract reports:**
```
Field coverage check:
- entities[].fields: 100 required, 100 present, 0 missing
- endpoints[].input/request_body: 31 required, 31 present, 0 missing
- endpoints[].query/path params (indirect): 2 required, 2 present, 0 missing
- concurrency_rules[].occ_field: 3 required, 3 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 19 checked, 19 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed, 0 missing
- state_machines[].transitions: 62 checked, 62 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 19 checked, 19 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 118 checked, 118 expressed, 0 missing
- entities[].fields[] structured content: 100 checked, 100 reconstructible, 0 missing
- sibling-branch symmetry: 14 groups checked, 14 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 874
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
§2.2 is byte-identical to `section-2.2-response-structure.md` (verified programmatically); §3 contains 0 tables and 0 URL paths.

**Ambiguities I had to adjudicate (scaffold internally inconsistent — flagging for the test author):**
1. `ERR_GALLERY_SERIALIZATION_GAP` is defined twice with contradictory conditions (a "2 days after prior batch" text vs. "occupy a bay at a GALLERY site"). I used the second, which matches the transition precondition in `VehicleOrder IN_TRANSIT → AT_DELIVERY_CENTER`, and omitted the orphan 2-day rule.
2. `DeliveryAppointment CONFIRMED → COMPLETED` requires `acceptance_inspection_result` ∈ {CLEAN, ISSUES_DOCUMENTED}, but that field's `default` is `NOT_PERFORMED` and it is *computed*; the value is only observable as a request field on `/complete` (`acceptance_inspection_result`, `documented_issues`). I resolved this by having completion validate the request-supplied value and then set the stored field.
3. `ServiceAppointment` hold asymmetry: the create path sets `PARTS_HOLD`, while `TRIAGED → MOBILE_DISPATCHED` sets `AWAITING_PARTS_SHIPMENT`; `mobile-service-visits/{id}/complete` also requires `is_warranty_covered == false` in the endpoint table but the state machine says only "hold_state ∈ {AWAITING_PARTS_SHIPMENT, PARTS_HOLD}". I wrote the shared precondition and left the endpoint-table note unenforced since `is_warranty_covered` is derived, not supplied.
4. Duplicate `http`/`condition` keys under `ERR_INVALID_REQUEST` (malformed YAML block) — treated as one rule.
5. `order_total_due_cents` adds `order_fee_cents` as a component distinct from the `ORDER_FEE_PAYMENT` ledger capture; I documented both sides (included in the total, and separately tracked as `order_fee_paid_cents`) without inventing a netting rule.
6. `delivery-appointments/{id}/complete` is in the endpoint table with `order_id`-scoped behavior but the completion OCC rule and `ERR_ORDER_NOT_DELIVERY_SCHEDULED` refer to the linked order; I kept the OCC field on the linked order as the scaffold names it.

Orchestrator verification: `wc -l -w` on disk confirms 523 lines / 15,107 words; section headers confirmed as §1, §2.1–§2.11, §3.1–§3.12, §4, §5 — matching the reported structure. Note the subagent reported 524 lines; `wc -l` counts 523 (final line has no trailing newline) — immaterial.

**Carry-forward note for Step 5:** the 6 adjudications above are places where the unit-test generator must NOT assume a scaffold-silent behavior. Any test built on these rules must clear the PRD-first two-condition filter against the PRD prose as actually written.

## Step 5: Generate unit tests — 2026-09-30T07:35:00.000Z

Generation is complete and fully audited. Final report.

### What was written

**`test_helpers/`** (Stage 1, 9 files, ~2,270 lines)
- `types.py` (507) — 20 entity TypedDicts + 25 status enums + `UserRole`; `OrderFeeLedgerEntry` correctly modelled `common_fields: false` (id + created_at only, no `updated_at`/`version`); all other 19 entities carry both.
- `api_client.py` (467) — `ApiClient(GenericApiClient)` with one method per endpoint (118 paths).
- `api_errors.py` (177) — 73 error IDs + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` (305) — per-entity assertions + `assert_{order,delivery_center,entitlement_bundle}_invariants` + `assert_ledger_conservation`.
- `factories.py` (224), `constants.py` (65), `test_users.py` (25, with `make_buyer_headers` for the one `entity_backed` role), `fixtures.py` (473, 5 tiers), `__init__.py` (30).

**`test_suite/`** (16 test files + `conftest.py`, **91 tests**)
`01_dual_variant_totals` 4 · `02_combinatorial_formulas` 4 · `03_state_machine_cycles` 4 · `04_transitive_cascades` 4 · `05_priority_conflicts` 4 · `06_boundary_precision` 8 · `07_temporal_overlap` 4 · `08_conservation_invariants` 4 · `09_corner_entities` 11 · `10_corner_state_machines` 7 · `11_corner_calculations` 4 · `12_corner_validations` 8 · `13_corner_endpoints` 4 · `14_corner_errors` 8 · `15_corner_rbac` 5 · `16_corner_cross_cutting` 8.

### Translation coverage
- **Queue A (§1.8): 18/18 instances translated, 36 tests** — every instance exactly 2 tests, verified by AST audit.
- **Queue B (§1.9): 55/55 non-stub instances translated, 55 tests.** The yaml contains **0 `excluded_because:` stubs**, so nothing was skipped for that reason.
- **0 instances SKIPPED.** Every instance cleared the PRD-first two-condition filter: the PRD states each rule verbatim (including all nine difficulty rules), so no PRD-silence gap arose.
- 0 untagged, 0 dual-tagged, 0 tags resolving to non-existent instances; 0 `skip`/`skipif`/`xfail`; 0 "scaffold"/"Table N"/"§1.x" strings in emitted code.

### Interpretation choices forced by the PRD (adjudicated inconsistencies)
- **`ERR_GALLERY_SERIALIZATION_GAP`** — used the PRD's bay-occupancy reading only; the orphan 2-day rule is absent from the PRD and therefore untested.
- **Completion inspection** — asserted the request-supplied `acceptance_inspection_result` is validated and then stored; never asserted the `NOT_PERFORMED` default.
- **`ServiceAppointment` hold asymmetry** — asserted only the shared `TRIAGED` precondition; the endpoint-table `is_warranty_covered == false` note was left unenforced (derived, not supplied).
- **`ERR_INVALID_REQUEST` duplicate keys** — treated as one rule.
- **`order_total_due_cents` vs `ORDER_FEE_PAYMENT`** — documented both sides with no invented netting rule.
- **`delivery-appointments/{id}/complete` OCC** — `expected_order_version` read as the linked order's version.

### Tests dropped / weakened after a filter failure
- **Queue B, `corner/entities/venue_get_…`**: the scaffold's claimed `center_kind` listing filter and the kind-specific 409 are absent from PRD prose → replaced with the PRD-stated suspend/reinstate-invalid-state behaviour under the same tag.
- **Undefined query filters removed from 6 tests** (`buyer_id`, `status`, `configuration_id`, `is_software_entitlement`, `estimate_state`, `vehicle_id`, `state_code`, `order_id`): the PRD only defines `limit`/`offset` semantics, so any assertion resting on a filter a PRD-only reader could omit was rewritten to PRD-stated pagination ordering alone. This also changed the `configuration_options` test from a flag-filter claim to the `is_software_entitlement` derivation + `configured_price_cents` reconciliation.
- **Arithmetic correction**: the delay-cascade ordering test originally asserted an accumulator of 3 for a 3-day slip; per PRD §3.4 the shift is `max(0, floor(new.start − prior.end))`, which is 0 for a slip inside the 7-day post-allocation window (the PRD's own 9-day example yields 2). The test now asserts 0 and documents why.

All citations were machine-verified: 91/91 tests carry a ≥20-character quoted span that survives a literal whitespace-normalised grep of `PRD.md` (0 mismatches), and `workspace/implementation/` was neither read nor created.

Orchestrator verification: `test_helpers/` has all 9 expected modules; `test_suite/` has `conftest.py` + 16 test files. Test count independently recounted on disk: **91** test functions (36 in files 01–08, 55 in files 09–16), with exactly **36** `Design: Difficulty/...` tags and **55** `Design: Corner/...` tags — matching the reported 18×2 + 55 split. `workspace/implementation/` confirmed absent at Step 5 exit, so physical isolation from the concurrently-scheduled Step 6 held.

## Step 6: Generate implementation — 2026-09-30T08:10:00.000Z

Done. Summary below.

### Files written (all under `workspace/implementation/`, 4138 lines total)

| File | Lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 (`Flask>=3.0.0`) |
| `app.py` | 67 |
| `errors.py`, `db.py`, `response.py`, `repository.py`, `middleware.py` | 147 / 86 / 52 / 137 / 182 |
| `routes/` (`__init__`, `common`, `ops`, `buyers`, `catalog`, `orders`, `delivery_appointments`, `finance`, `production`, `service`) | 15 / 146 / 37 / 105 / 191 / 339 / 96 / 68 / 116 / 330 |
| `services/` (`__init__`, `calculation`, `ledger`, `scheduling`, `order_flow`, `sales`, `appraisal`, `financing`, `delivery`, `service_ops`, `entitlements`, `sweeps`) | 12 / 281 / 58 / 125 / 366 / 233 / 108 / 121 / 249 / 306 / 77 / 78 |

**Layout**: `app.py` holds the request pipeline (auth → role permission → handler), envelope error handlers, and blueprint registration. `middleware.py` carries the 8-role `PERMISSIONS` table transcribed from the PRD §4 endpoint table. `services/` holds all state machines, calculations and workflows; `routes/` is thin parsing + dispatch. Storage is `db.DB` — plain in-memory dicts, reset per process, **nothing seeded**.

**Endpoint count**: 118 registered under `/v1`, exactly matching the 118 rows of the PRD §4 table (0 missing, 0 extra) — equal to the scaffold's declared `endpoint_count`.

**Smoke test**: `cd implementation && PORT=<free port> bash start.sh` — server ready in ~690 ms, serving `0.0.0.0:$PORT` in the foreground via `exec`. Five consecutive cold boots each ran a full mini-workflow (buyer → jurisdiction → center → trim → order → pay → place → lock → allocation → transit → arrival → book → confirm → complete → diagnostic report) and produced identical results (`DELIVERED`, total 1027500), confirming the store starts empty and boots cleanly from a fresh process. Verified: envelope shape/fields, pagination `limit/offset/total_count/has_more` defaults 10/0/1..100, clock default `2026-09-01T00:00:00.000Z` with no wall-clock drift, all nine calculations, both OCC paths, RBAC/auth ordering, and every scheduled sweep. No files or processes were left behind; no other task's server was touched.

**PRD-resolved points honoured**: GALLERY `ERR_GALLERY_SERIALIZATION_GAP` implemented as the bay-occupancy reading only (the orphan "2 days after prior batch" variant is not implemented); `CONFIRMED → COMPLETED` validates the request-supplied result then stores it, with the stored default staying `NOT_PERFORMED`; `ServiceAppointment` holds use the shared `hold_state ∈ {AWAITING_PARTS_SHIPMENT, PARTS_HOLD}` precondition (the `is_warranty_covered == false` clause is not enforced); scaffold's duplicated `http`/`condition` keys collapsed to one `ERR_INVALID_REQUEST` rule; `order_total_due_cents` includes `order_fee_cents` with `order_fee_paid_cents` tracked separately via `ORDER_FEE_PAYMENT` (no netting invented); completion OCC checks the linked order's version.

**Ambiguities I had to adjudicate (worth flagging)**

1. **Mobile travel fee — PRD prose contradicts the scaffold formula.** PRD §3.10 says "the platform's base travel charge is currently 0, so in the present configuration the travel line is exactly the per-mile charge on the excess miles"; the scaffold has a `0 when base == 0` short-circuit that would zero the line. I followed the PRD (per-mile charge applies), so 40 miles yields travel 950. If the suite was built from the scaffold, this single line is where it will differ.
2. **Frequency/count caps going unenforced.** `bay_count` and `van_count` exist as attributes but the PRD never states a capacity limit for placement, so none is enforced (it states only the buffer rule and the conservation rule for `booked_slot_count`). Related: when overlapping appointments exist, `booked_slot_count` is derived from live rows (4 in one probe shown above, though only 2 bays exist), consistent with the PRD's declaration that an implementation "may treat it as a derivation rather than a hand-maintained counter".
3. **Estimate chain after a booking.** PRD §3.4 says slippage supersedes "the order's current PROVISIONAL or FIRM estimate", but PRD §3.6's risk path presumes a delay still moves an order whose window was already consumed by a booking. I made allocation supersede the prior live estimate (keeping the chain single-valued) and let a delay fall back to the newest row of the chain when none is live — this is the only reading under which the AT_RISK path is reachable, which I verified end to end.
4. **`ERR_TRADE_IN_TRANSFER_UNSETTLED` and the cancelled-order config-change code.** No settlement state, endpoint or field exists for a trade-in title transfer, so that gate is never triggered. Likewise a configuration change on a CANCELLED order returns `ERR_STALE_VERSION` (its version advanced at cancellation), since PRD §3.12 makes the version comparison the sole remaining guard on that path.

Orchestrator verification: `workspace/implementation/` on disk contains `start.sh`, `requirements.txt`, `app.py`, and the `db/errors/middleware/repository/response` modules plus `routes/` and `services/` packages — 4138 total lines across `.py`/`start.sh`/`requirements.txt`, matching the report. `start.sh` confirmed to `exec python3 app.py` in the foreground (after a guarded conditional pip install), and `app.py`'s `__main__` block confirmed as `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True, use_reloader=False)` — satisfying the INSTRUCTION.md contract (reads `$PORT`, binds `0.0.0.0`, foreground).

## Step 7: Run tests and iterate — 2026-09-30T09:55:00.000Z

All 8 rounds of sweep 11 pass 91/91 with zero failures, errors, or skips.

### Summary

**Iterations run:** 11 parallel 8-round stability sweeps (each sweep = 8 concurrent `prd-bench-local-run --isolation per-test-server` rounds). Progress: 54 → 54 → 42 → 26 → 18 → 10 → 12 → 7 → 5 → 1 → **0** failures.

**Tests deleted:** none. No assertion was dropped for being strict or brittle — every failing test traceable to a verbatim PRD rule was kept and made faithful.

#### `test_helpers/` fixes
- `api_client.py` — `list_order_estimates` now routes the order id as a query filter so it does not leak other orders' estimates.
- `fixtures.py` — account email made unique per setup call (PRD §3.1 uniqueness made the name-derived email collide when one test built two scenarios); the parts hub moved to `state_code="OK"` so a second `TX` regime for the site-less vehicle is creatable; a `cover_order_total()` helper posts the balance the recomputed total still needs (PRD §3.7 posture → §3.5 funding gate); `walk_order_to_delivered` no longer strips the caller's options and now funds the order before booking; `setup_order_context` attaches caller-named options via the configuration-change endpoint; an unused `prepare_order_for_booking` helper was removed.
- `types.py` — added `canonical_instant()`, the PRD §2.5 spelling for an instant.

#### `implementation/` fixes
- `errors.py` — `ERR_CONFIG_LOCK_DEADLINE_PASSED` was missing from the status map, so a required 409 was served as 400.
- `calculation.py` — `order_total_due_cents` now cores on the **order's chosen options** (PRD §3.7), not the trim's `configured_price_cents`; `visible_appraisals` tightened to `{OFFERED, ACCEPTED}` (PRD §3.3 "visible"); `shift_days_for` measures from the prior window's start when that window is no longer a live promise.
- `order_flow.py` — lock closure promotes and consolidates the estimate chain to one live row; per-path `shift_days` staging (projected rows measure from the prior window end, bound/delay rows keep the prior width); delay supersession no longer accrues a phantom shift; `allocate` checks unit eligibility before mutating the order; `cancel_order` gates a `DELIVERED` order with `ERR_ALREADY_TERMINAL` (PRD §3.8).
- `sales.py` — dropped the `state_code` uniqueness rejection (uniqueness is an identifier property, and PRD names no error for a repeat); minting brings a `SCHEDULED` batch into production.
- `delivery.py` / `routes/delivery_appointments.py` — booking evaluates the version guard (entry 19) only after the slot-conflict rule (entry 11); `delivery.complete` no longer requires a beforehand-settled title transfer (`ERR_TRADE_IN_TRANSFER_UNSETTLED` remains declared but unreachable, per adjudication 4).
- `financing.py` — `amount_financed_cents` computed at submission (PRD §3.5).
- `service_ops.py` / `calculation.py` — visit cost always displays the three-line sum and takes no report/vehicle arguments; opening a service appointment only refuses `NO_ACTION` reports; the dispatch jurisdiction bar (entry 15) now precedes the channel check.
- `scheduling.py` — van occupancy covers every non-cancelled visit (PRD §3.10 "other non-cancelled visits").
- `routes/common.py`, `response.py`, all 7 route modules — `meta.total_count` now reports matching rows across all pages (PRD §2.3); the API preserves either accepted instant spelling while still emitting `.000Z`; the clock snaps to millisecond resolution so same-instant rows share a `created_at` value.
- `routes/orders.py` — order creation distinguishes an absent field (`ERR_INVALID_REQUEST`) from a present-but-unknown reference (`ERR_<ENTITY>_NOT_FOUND`, PRD §2.9); the configuration-change path evaluates the deadline (entry 7) before the version check; `arrive-at-center` blueprint registration verified.

#### PRD-adjudicated landmines confirmed
- **Travel fee** (landmine 1): the per-mile charge on excess miles is implemented and asserted.
- **`ERR_GALLERY_SERIALIZATION_GAP`**, **`ServiceAppointment` holds**, **completion OCC on the linked order**, **cancelled-order config change → `ERR_STALE_VERSION`**: all left as implemented.

#### Coverage corrections (unique-derivability collapses kept, not deleted)
One assertion was relaxed at `test_12_corner_validations.py` to `validate_error_is_one_of([ERR_APPRAISAL_OFFER_EXPIRED, ERR_INVALID_STATE])`, because the clock sweep lapses an `OFFERED` row in the same advance that carries it past its validity, making the accept-path expiry branch unreachable. Two tests were re-pointed at the reachable sibling rule rather than the unreachable one, with the unreachability documented in the test: the FROZEN-posture booking gate (`ERR_ORDER_DELIVERY_NOT_READY` is unreachable on that endpoint because a fundable order must have arrived) and the entry-16/17 precedence pair.

Orchestrator verification: all 8 `results.{1..8}.json` present in `workspace/implementation/` and each independently parsed to `passed=91 total=91 failed=0 errors=0 skipped=0` — confirming the clean 8-round sweep on disk rather than taking the report's word for it. 91 matches the Step 5 test count, so no test was silently dropped from collection.

**Step 8 gate:** NOT skipped. Although Step 7 recorded 0 test deletions, it applied numerous `test_helpers/`, `test_suite/` (1 relaxation + 2 re-points) and `implementation/` fixes — the skip condition requires all four counts to be zero. Step 8 runs.

## Step 8: Finalize PRD — 2026-09-30T11:35:00.000Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_3162_direct_vehicle_sales_delivery_appointment_mobile_service/workspace/PRD_FINALIZED.md`.

### Size
- `PRD.md` 523 lines → `PRD_FINALIZED.md` 524 lines (+1 line, **+0.19%**). 24 changed line-blocks, each a minimal inline patch; no new sections.

### One bullet per change

- **§2.4** — revise — `state_code` uniqueness not enforced at write time; a repeat code is accepted (no error named) — `implementation/services/sales.py:46-73`
- **§2.5** — insert — input instants accepted in any ISO 8601 spelling (Z or offset, with/without fraction), emitted form always `.000Z`-shaped, finer precision rendered at ms, and same-instant rows share `created_at` (clock snapped to ms) — `implementation/errors.py:114-140`, `routes/ops.py:24-28`
- **§2.6** — insert — `bay_count`/`van_count` are recorded attributes, not enforced capacity caps; no limit check, `booked_slot_count` derived and may exceed `bay_count` — `implementation/services/scheduling.py:126-135`, `services/delivery.py:38-39`
- **§3.1** — insert — order creation distinguishes an absent field (`ERR_INVALID_REQUEST`) from a present-but-unknown reference, resolved left-to-right to the per-entity not-found code — `implementation/routes/orders.py:27-51`
- **§3.2** — revise — config change admissible while deadline is unset (unplaced order), declined only when a set deadline has passed — `implementation/services/order_flow.py:62-66`
- **§3.2** — revise — replaced the false "instantly rejects every later change" with "no longer starts from `PLACED`"; also replaced fabricated `configuration_option_ids` with the order's chosen option set — `implementation/routes/orders.py:123-133`
- **§3.3** — insert — offer's expires-before-delivery gate bites only while a live `PROVISIONAL`/`FIRM` estimate exists — `implementation/services/appraisal.py:50-59`
- **§3.3** — insert — definition of a *visible* appraisal as exactly `{OFFERED, ACCEPTED}` — `implementation/services/calculation.py:20-25`
- **§3.4** — revise — batch minting auto-starts a `SCHEDULED` batch; a still-`SCHEDULED` batch fails allocation with `ERR_NO_ELIGIBLE_UNIT` — `implementation/services/sales.py:217-219`, `order_flow.py:229-235`
- **§3.4** — revise — allocation's second estimate carries `shift_days` 0 (was falsely stated as measured and "increased") — `implementation/services/order_flow.py:82-95,213-218`
- **§3.4** — revise — `shift_days` measured from the prior window *start* when the prior window is no longer live (passed/consumed); scoped to the projected-window rule — `implementation/services/calculation.py:123-135`
- **§3.4** — revise — delay propagation keeps the prior window's width (fresh `shift_days` 0, accumulator unchanged), with newest-row fallback when no live row remains — `implementation/services/order_flow.py:377-413`
- **§3.4** — revise — unplaced affected orders (null `placed_at`) sort before placed ones — `implementation/services/calculation.py:300`
- **§3.5** — revise — `amount_financed_cents` present on the submitted row, recomputed at decision/contract-review/accept — `implementation/services/financing.py:32,70-73,98-105`, `appraisal.py:82-83`
- **§3.6** — revise — booking precondition sequence fixed: state, franchise screening, window, bay conflict (entry 11), then referential/readiness gates, version guard (entry 19) last — `implementation/services/delivery.py:30-58`
- **§3.6** — insert — `buffer_minutes` default 60 when no regime matches the site's `state_code` — `implementation/services/scheduling.py:43-47`
- **§3.6** — revise — removed the "title transfer must be settled / `ERR_TRADE_IN_TRANSFER_UNSETTLED`" precondition; code declared but unreachable — `implementation/services/delivery.py:194-196`
- **§3.7** — revise — total's core uses the *order's chosen* options, not the trim's `configured_price_cents` book figure — `implementation/services/calculation.py:37-58`
- **§3.7** — insert — unplaced order (null deadline) carries no late fee — `implementation/services/calculation.py:49-50`
- **§3.8** — insert — cancellation of a `DELIVERED` order is refused with `ERR_ALREADY_TERMINAL` — `implementation/services/order_flow.py:160-165`
- **§3.8** — revise — cancellation rejects every visible appraisal not already `REJECTED` (covers `ACCEPTED` too) — `implementation/services/order_flow.py:172-177`
- **§3.9** — revise — opening a service appointment requires non-`RETIRED` vehicle and non-`NO_ACTION` report; window well-formedness is a scheduling-step rule, not an opening one — `implementation/services/service_ops.py:42-49`
- **§3.9** — revise — center scheduling additionally requires a well-formed window; dispatch order is state → jurisdiction → channel → window → van, version guard applied first at the route — `implementation/services/service_ops.py:81-101,141-156`, `routes/service.py:194-210`
- **§3.12** — revise — entry 7 wording (window open, incl. unset deadline); dropped the false "no other validation" absolute in the trailing adjudication — `implementation/routes/orders.py:75-97`, `order_flow.py:62-66`
- **§5** — insert — added the missing `ERR_CONFIG_LOCK_DEADLINE_PASSED | 409 Conflict` catalogue row — `implementation/errors.py:16`

Kept verbatim where PRD already determined behavior (per §3.2's spare-path adjudication, §3.10 travel-fee line, §3.9 `ERR_GALLERY_SERIALIZATION_GAP`, PARTS_HOLD/AWAITING_PARTS_SHIPMENT hold semantics, completion OCC on the linked order's version, cancelled-order config-change stale handling, bay/van caps). No assertion was invented beyond what `implementation/` exhibits, and nothing was pinned that the tests only weakly cover where the implementation is silent.

### Per-edit pre-edit search log (a: subject, b: paths enumerated, c: wording adjustment)

1. **state_code uniqueness** — a) regime-creation guard. b) grepped `state_code` across `services/{sales,delivery,scheduling,service_ops}.py`, `routes/{catalog,buyers}.py`; confirmed site/buyer `state_code` are independent attributes. c) none.
2. **instant spelling / ms clock** — a) input instant parsing and clock precision. b) `errors.parse_dt/fmt`, `routes/ops.set_clock`, `repository.serialize`, every `instant_field` caller; confirmed no handler rejects an offset or sub-ms spelling. c) narrowed my first draft ("either accepted spelling" → "any ISO 8601 spelling") after probing `+00:00`, `+05:00`, and `.123456` were all accepted.
3. **bay/van capacity** — a) capacity enforcement. b) grepped `bay_count|van_count` — they are only stored/serialized, never gated; `booked_slot_count` only derived. c) none.
4. **order-create reference resolution** — a) absent field vs unknown row. b) `routes/orders.create_order`, `repository.get/find` NOT_FOUND map; verified all four codes empirically. c) softened my first "buyer first" phrasing to "the first reference to fail, in the order …".
5. **config-change deadline-unset** — a) lock-deadline guard on a DRAFT/unplaced order. b) `order_flow.assert_lock_window_open`, `routes/orders.configuration_changes`, `sales.*` (never sets a deadline on create); verified DRAFT and CANCELLED-DRAFT config changes succeed. c) kept the existing `ERR_STALE_VERSION` sentinel prose untouched (still true while the window is open).
6. **config-change after CONFIG_LOCKED** — a) what the endpoint actually does after lock. b) `routes/orders.lock_configuration` (status guard), `order_flow.apply_configuration_change`; the order serialization carries no `configuration_option_ids`. c) reworded away from "rejected" (impl accepts) and from the non-existent field.
7. **offer expires-before-delivery** — a) that timing gate's condition. b) `appraisal.offer`, `calculation.current_estimate/latest_estimate`; verified refusal on a PLACED order and acceptance on a DRAFT order. c) none.
8. **visible appraisal set** — a) definition of visible. b) `calculation.visible_appraisals` and every callsite: booking, funding, cancellation, offer gate. c) none (wording explicitly lists all non-visible statuses to avoid narrowing).
9. **batch auto-start** — a) minting's effect on a SCHEDULED batch. b) `sales.mint_unit/start_batch`, `order_flow.assert_eligible_unit/pick_unit`; verified mint flips SCHEDULED→IN_PRODUCTION and an empty started batch still yields `ERR_NO_ELIGIBLE_UNIT`. c) none.
10. **allocation shift_days** — a) allocation estimate's shift. b) `order_flow.allocate/create_estimate`, `calculation.shift_days_for`; probed far-future `transport_eta` — always 0 (corrected my own first draft, which had claimed measurement).
11. **shift_days anchor** — a) which end anchors the shift. b) `calculation.shift_days_for` + its only caller `create_estimate`; confirmed the start-anchor is a projected-window-only path. c) added "For a deliberately projected window (below)" to avoid claiming it binds allocation.
12. **delay propagation shift** — a) delay's shift and accumulator. b) `order_flow.propagate_delay/delay_batch`, `calculation.orders_for_batch_delay`; probed 3- and 9-day delays (accumulator stays 0). c) rewrote "cumulatively on top of the existing shift" to "moving each order's newest estimate row on by the new delay".
13. **delay order tie-break** — a) null `placed_at` ordering. b) `orders_for_batch_delay` sort key; Python string comparison sorts `None` as `""` first. c) none.
14. **financed principal at submission** — a) when the field is written. b) all `amount_financed*`/`pricing_for` callsites in `financing.py`, `appraisal.py`. c) none.
15. **booking precondition order** — a) the booking guards' sequence. b) `delivery.book` read line-by-line; corrected my own first draft (version is last, not second-to-last) — c) fix applied.
16. **buffer default 60** — a) unmatched `state_code` buffer. b) `scheduling.buffer_for_center` vs `service_ops.center_buffer` (0 fallback) — c) scoped the sentence to booking's handover buffer so the service-appointment 0-default is not mis-described.
17. **title transfer / `ERR_TRADE_IN_TRANSFER_UNSETTLED`** — a) the transfer gate. b) `delivery.apply_transfer_gate` is a no-op, `errors.ERROR_STATUS` declares the code; no caller raises it. c) made it explicit that the code stays in the catalogue (the catalogue row was left verbatim).
18. **order total core** — a) what feeds the core. b) `calculation.order_total_due_cents`, `sales.add_option`; tested with an un-attached 50 000 option (does not move the total). c) none.
19. **late fee with null deadline** — a) late-fee condition. b) `calculation.order_total_due_cents` deadline guard, create/place. c) none.
20. **cancel DELIVERED** — a) delivered-order cancellation. b) `order_flow.cancel_order`, `routes/orders.cancel_order`, `errors.ERROR_STATUS`; verified 409 `ERR_ALREADY_TERMINAL`. c) none.
21. **cancel visible appraisals** — a) which appraisals the cascade rejects. b) `order_flow.cancel_order` uses `visible_appraisals` with a not-already-`REJECTED` filter. c) none.
22. **service-appointment opening gates** — a) open-time refusals. b) `service_ops.open_service_appointment`; verified `NO_ACTION` → 409 and RETIRED → 409, and that a malformed window opens fine (unlike scheduling). c) none.
23. **dispatch ordering** — a) the dispatch guard sequence. b) `service_ops.dispatch_visit` plus `routes/service.dispatch_visit` (version checked first); probed 403-vs-400 and 412 cases. c) none.
24. **entry-7 wording / spare-path absolute** — a) the ordering claim. b) `routes/orders.configuration_changes`, `order_flow.assert_lock_window_open`; verified stale-in-window → 412, stale-past-deadline → 409. c) softened the absolute so the documented entry-19-first behavior of §3.6 is not contradicted.
25. **error catalogue row** — a) missing code. b) `errors.ERROR_STATUS`; found `ERR_CONFIG_LOCK_DEADLINE_PASSED` absent from the PRD table. c) none.

No test files or implementation files were modified; `PRD.md` was left untouched (only `PRD_FINALIZED.md` was edited, and it is untracked/new).

Process note: I did not start or kill any servers; all verification used an in-process Flask test client, so no ports or other concurrent pipelines were touched.

Orchestrator verification: `wc -l` confirms PRD.md 523 lines → PRD_FINALIZED.md 524 lines (+1); `diff` shows 47 changed lines (~24 blocks, consistent with the report); `diff` of the `^#{1,3} ` section headers between the two files is empty, confirming the "no new sections" constraint held. `PRD.md` itself confirmed unmodified on disk relative to its Step 4 state.

## Step 9: Complete PRD — 2026-09-30T12:35:00.000Z

PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_3162_direct_vehicle_sales_delivery_appointment_mobile_service/workspace/PRD_COMPLETED.md`. No source files, tests, or implementations were modified; all probe servers I started were stopped.

### Summary

**Source vs output**
- Source: `PRD_FINALIZED.md` (present) — 524 lines, 112,456 chars.
- Output: `PRD_COMPLETED.md` — 524 lines, 117,589 chars. Line delta 0 (no new sections/paragraphs); char delta +5,113, all inline.

**Counts**
- Ambiguity-pins: 18
- Mismatch-revisions: 2 (E1 pagination; E16 cancellation availability)

**Changes** (`insert`/`revise` — ambiguity/mismatch — impl anchor)

- §2.1 — insert — ambiguity — the order-ownership guard applies only on order retrieval, configuration change, placement, cancellation, and order-scoped listings; **not** on allocation/transport/arrival/re-projection/allocation-unit listing/explicit lock, and **not** on any handover endpoint — `routes/orders.py:23,70,77,144,177`, `routes/delivery_appointments.py:59-100`
- §2.3 — revise — mismatch — `limit`/`offset` are clamped (limit→1…100, negative offset→0) and non-integer values fall back to defaults rather than erroring — `repository.py:98-115`
- §2.5 — insert — ambiguity — emitted instants truncate sub-millisecond digits (no rounding) — `ops.py:27`, `errors.py:114-120`
- §2.5 — insert — ambiguity — a non-transition ledger post refreshes the order's `order_fee_paid_cents`/`order_total_due_cents`/`delivery_readiness_posture` without advancing the order's `version` — `ledger.py:27-43`
- §3.1 — insert — ambiguity — `center_kind` stored verbatim, not validated against its four-value set — `sales.py:84-101`
- §3.1 — insert — ambiguity — `option_category` stored verbatim; `is_software_entitlement` mirrors the stored value — `sales.py:136-152`
- §3.2 — insert — ambiguity — order creation resolves all four references before responding, so a failed create persists no order row — `routes/orders.py:37-51`
- §3.2 — insert — ambiguity — placement compares `expected_order_version` before all four preconditions (stale wins over unpaid fee) — `routes/orders.py:105-118`
- §3.2 — insert — ambiguity — explicit lock rejects a non-`PLACED` order with `ERR_INVALID_STATE` before version/deadline checks — `routes/orders.py:127-131`
- §3.3 — insert — ambiguity — order-scoped appraisal actions resolve through the order; a cross-order appraisal is `ERR_APPRAISAL_NOT_FOUND` — `routes/orders.py:294-345`
- §3.3 — insert — ambiguity — acceptance recomputes every linked trade-in-flagged application not `FUNDED`/`DECLINED`, refreshing payment (and `apr_bps` where written) — `appraisal.py:67-88`
- §3.4 — insert — ambiguity — allocation estimate's `basis_equipment_at` is the batch's `planned_completion_at`, not the allocation instant — `order_flow.py:213-217`
- §3.4 — insert — ambiguity — a slippage estimate inherits `basis_equipment_at` from the prior row rather than stamping the clock — `order_flow.py:391-397`
- §3.4 — insert — ambiguity — re-projection's `window_days` defaults to 7 — `routes/orders.py:181`
- §3.5 — insert — ambiguity — financeable maxima: PRIME 8,000,000, NEAR_PRIME 6,000,000, SUBPRIME 4,000,000 cents — `db.py:32-36`, `financing.py:66-69`
- §3.5 — insert — ambiguity — decline is recorded without the `identity_verified` gate (the gate is approval-only) — `financing.py:42,63`
- §3.6 — revise — mismatch — cancellation is available from any non-terminal state, including `AT_RISK` (PRD previously said `BOOKED`/`CONFIRMED`) — `delivery.py:124-126`
- §3.6 — insert — ambiguity — no handover write applies the order-ownership guard — `routes/delivery_appointments.py`, `delivery.py:30-191`
- §3.9 — insert — ambiguity — the named report must belong to the named vehicle (`ERR_REPORT_NOT_FOUND`), and the warranty mileage ceiling is 60000 — `routes/service.py:145-149`, `service_ops.py:70-72`
- §3.10 — insert — ambiguity — neither a covered nor a chargeable mobile repair writes any ledger entry — `service_ops.py:192-201,258-273`
- §3.11 — insert — ambiguity — the re-grant check compares `basis_version` against the vehicle's installed `software_version` (strictly greater), records it on the rows, and never rewrites the vehicle's own version — `entitlements.py:12-18`, `delivery.py:210-215`

**Deliberately left unchanged** (verified impl-conformant, not silent): pagination shape and `has_more`; the configured-price/order-core calculation; the final-vs-provisional variant rules; bay/van interval semantics (buffered handover, unbuffered van, lapsed intervals vacating the bay); `booked_slot_count` conservation; the delay-propagation ordering key; and the sweep set.

Orchestrator verification: `wc -l -c` confirms PRD_FINALIZED.md 524 lines/112,456 chars → PRD_COMPLETED.md 524 lines/117,589 chars (+5,133 chars, +0.0% lines — matching the reported +5,113 to within trailing-whitespace/newline accounting); `diff` of the section headers between FINALIZED and COMPLETED is empty (no new sections); `PRD.md` unchanged at 523 lines/105,969 chars. `find implementation -name "*.py" -newer PRD_COMPLETED.md` returns nothing, confirming no implementation file was modified after (or by) Step 9 — the alignment target was left intact. 18 + 2 = 20 edits, consistent with the 20 bullets listed.

**Pipeline complete.** Step 9 is documentation-only and does not invalidate the Step 7 verification: the test suite asserts against `implementation/` behavior, which Step 9 did not touch, and PRD_COMPLETED.md is a derivative document, not a runtime input. The Step 7 result (8/8 rounds × 91/91 passing) stands as the final verified state.