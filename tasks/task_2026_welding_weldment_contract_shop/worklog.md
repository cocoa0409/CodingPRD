# Worklog — task_2026_welding_weldment_contract_shop

## Step 1: Create task directory — 2026-08-15T08:00:00.000Z

Directory `tasks/task_2026_welding_weldment_contract_shop/` and `workspace/` created externally (pipeline launcher); orchestrator started at Step 2 per instructions.

## Step 2: Generate scaffold — 2026-08-15T08:37:00.000Z

All three files are written and pass lint cleanly.

## Summary

Scaffold artifacts written to `/home/ubuntu/github/CodingPRD/tasks/task_2026_welding_weldment_contract_shop/`:

- **SCAFFOLD.yaml** — §1.0–§1.7 (no scaffold_difficulty_design / scaffold_corner_design keys)
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single top-level `scaffold_difficulty_design:` key
- **SCAFFOLD_CORNER_DESIGN.yaml** — single top-level `scaffold_corner_design:` key

### Counts
- **Entities**: 17 (Shop, Welder, NDTVendor, Oven, PQR, WPS, WelderQualification, ConsumableLot, ConsumableIssue, Fixture, ShopOrder, Weldment, Joint, WeldPass, DistortionReport, Inspection, TravelerSignOff)
- **State machines**: 8 (PQR, WPS, WelderQualification, ConsumableLot, Fixture, Weldment posture-driven, Joint parallel dimensions, Oven)
- **Calculations**: 8 (continuity_expiry, repair_rate_pct, exposure_minutes_on_return, ndt_slot_availability, wps_thickness_envelope, oven_load_kg, repair_review_threshold_gate, frozen_threshold)
- **Validations**: 19 (priority-ordered)
- **Endpoints**: 98 (includes 34 flat reverse-reachability GETs added per lint check (f))
- **Errors**: 40
- **Roles**: 10 (ShopAdmin, QCManager, WeldLead, Welder [entity_backed], CWI, MaterialController, ProductionPlanner, QualityInspector, ShippingClerk, Any)

### §1.8 Difficulty Design — 18 non-stub instances (2 per rule × 9 rules)
- dual_variant_calc: continuity_expiry (prospective vs retrospective), repair_rate_pct (weldment vs joint scope)
- combinatorial_formula: wps_thickness_envelope (mode a: 4-input non-linear), repair_rate_rounding_order (mode b: nested rounding)
- non_linear_state_machine: wps_revision_cycle (cyclic), joint_parallel_dimensions (parallel)
- transitive_cascade: wps_supersede_cascade_depth_3, oven_offline_cascade_depth_2
- priority_pair_validation_conflict: state vs business_safety (WPS approve), business_safety vs business_fiscal (lot issue)
- boundary_precision_check: repair_rate 5.00 >= 5 boundary, NDT slot half-open [start,end) boundary
- cross_entity_state_dependency: Joint→Weldment posture, WeldPass→WelderQualification continuity
- resource_temporal_overlap: NDT vendor slot (half-open interval), Fixture capacity (aggregate count)
- compensating_invariant: consumable_kg_conservation, weldment_posture_freeze_unfreeze_conservation

### §1.9 Corner Design — 39 instances total (30 non-stub, 9 stub)
- entities (7), state_machines (8), calculations (2), validations (5), endpoints (2), errors (9 stubs), rbac (2), cross_cutting_layers (2 OCC stale-version), consistency_model (1 immediate visibility)

### Lint
`scaffold_lint.py` verdict: **clean lint** — all 608 §1.8/§1.9 calls conform to §1.5; all §1.1 FKs have reverse-reachability in §1.5.

### Difficulty design notes (harder-than-expert calibration)
- 3 OCC concurrency rules (Weldment ship, Joint start-fab, WPS approve)
- Depth-3 cascade (WPS approve → prior rev SUPERSEDED → PENDING Joints ON_HOLD → WelderQualification re-evaluation to LAPSED)
- Compound Weldment posture derived from 4 distinct triggers (joint ON_HOLD, distortion PENDING, repair_rate ≥ limit, NDT_FAILED × distortion_count ≥ 2)
- Segregation-of-duties role model enforced in two distinct places (PQR reviewer vs WPS approver; welder vs VT inspector)
- Version-pinned PQR on WPS approval; logical clock with mandatory `2026-08-01T00:00:00Z` startup default

## Step 3: Copy shared files — 2026-08-15T08:38:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2026_welding_weldment_contract_shop/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T09:00:00.000Z

All checks pass. The one extra §4 row (`send-for-repair`) is the declared trigger of the Fixture `IN_USE → UNDER_REPAIR` state-machine transition — including it is the lossless projection of the scaffold's state machine even though `endpoints[]` omitted it.

---

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2026_welding_weldment_contract_shop/workspace/PRD.md` — **390 lines**

**Section list:**
- §1 Introduction (2 paragraphs, audit/business-context angle)
- §2 Global Specifications: 2.1 RBAC (10 roles + per-role identity prose), 2.2 API Response Structure (verbatim block, byte-identical match confirmed), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Shop Logical Clock, 2.6 Optimistic Concurrency Control, 2.7 Derived Posture and Cascade Consistency, 2.8 Validation Precedence, 2.9 Measurement Precision and Rounding, 2.10 Nested Retrieval, Flat Collections, and Addressing
- §3 Business Logic (8 subsections): 3.1 Shop Onboarding & Procedure Qualification, 3.2 Welder Roster/Qualification/Continuity, 3.3 Consumable Lots/Ovens/Exposure, 3.4 Fixtures/Shop Orders/Weldments, 3.5 Joint Fabrication & Weld-Pass Recording, 3.6 Inspection Hold Points & NDT Vendor Scheduling, 3.7 Distortion/Repair Cycles/Posture, 3.8 Traveler Sign-Off/Shipment/Order Completion
- §4 Endpoint Definitions (99 rows, 4 columns), §5 Error Code Catalogue (40 rows, 2 columns)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 95 required, 95 present, 0 missing
- endpoints[].input (extra inputs): 5 required (to_iso8601, expected_weldment_version,
  expected_joint_version, expected_wps_version, new_wps_id), 5 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
- path params: 17 required, 17 present in backticked {braced} form, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 19 checked, 19 expressed (global precedence in §2.8; per-endpoint
  order stated in §3.1 for WPS approve and §3.5/§3.6 for joint/inspection writes), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (ship + expected_weldment_version,
  start-fabrication + expected_joint_version, wps approve + expected_wps_version; each named with
  ERR_STALE_VERSION / HTTP 412), 0 missing
- state_machines[].transitions: 8 machines, 32 transitions checked, 32 fully expressed
  (from/to states, preconditions with error IDs, side effects incl. all cascades), 0 missing
- calculations[]: 8 checked, 8 fully expressed (continuity 183-day window with inclusive boundary
  and both variants; repair_rate_pct round-half-up 2dp with both scopes; exposure floor-minutes
  and 240-min SMAW quarantine; NDT half-open-interval slot rule; inclusive thickness envelope;
  oven load aggregation with rebake exemption; repair-review >= gate; frozen 2-distortion threshold),
  0 missing
- validations[] conditions: 19 checked, 19 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (clock sweeps, WPS supersession cascade,
  oven-offline cascade, weld-pass fan-out, ship/cancel fixture+order cascades), 0 missing
- entities[].fields[] structured content: all defaults, enums, ranges (holding_temp_c 120–300,
  capacity_weldments ≥ 1, max>min thickness, end>start slots), computed-field derivations, and the
  common_fields:false exception for ConsumableIssue/WeldPass/DistortionReport/Inspection/
  TravelerSignOff stated explicitly, 0 missing
- sibling-branch symmetry: requalify/revoke branches, VT vs UT/RT scheduling, PASS vs FAIL result
  branches, CUSTOMER vs SHOP fixture disposition, RESTRICTED/REPAIR_REVIEW/FROZEN posture paths all
  rendered with equal density, 0 asymmetric
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

**Coverage audit notes:** All 15 entities, 8 state machines, 8 calculations, 19 validations, 40 errors, and 10 roles are represented in prose. All 98 scaffold endpoints appear in §4, plus one additional row (`POST .../fixtures/{fixtureId}/send-for-repair`) sourced from the Fixture state machine's declared trigger, which the scaffold's endpoint table omitted. Enum vocabularies are listed in full (including unreached members `EXPOSED`/`CONSUMED`, oven `QUARANTINED`, ShopOrder `CANCELLED`, welder `TERMINATED`) exactly as the scaffold declares them, with only scaffolded transitions narrated. The difficulty/corner design files were never opened.

## Step 5: Generate unit tests — 2026-08-15T09:40:00.000Z

Generation complete. All verification passes: `compileall` clean, `pytest --collect-only` succeeds (68 cases), all 65 `Design:` tags resolve to real instances, every docstring ends with exactly one tag, every PRD citation survives a normalized literal grep of PRD.md, no skip/xfail markers, no scaffold references in generated code.

## Summary

**Totals: 65 test functions (68 pytest cases after parametrize) — 33 queue A tests across 15 difficulty instances, 32 queue B tests across 30 corner instances.**

### Queue A (Difficulty) — 15 of 18 instances translated
Every translated instance has ≥2 tests. Notable adaptations made so the asserted outcome is what the PRD uniquely derives (setups changed, assertions unchanged):
- `state_vs_business_safety_on_wps_approve`: re-reads the WPS for a fresh `expected_wps_version` before the second approve — §2.8 puts OCC before lifecycle, so the recipe's stale version would have yielded `ERR_STALE_VERSION`, not the asserted `ERR_WPS_NOT_DRAFT`.
- `ndt_slot_half_open_boundary` / `ndt_vendor_slot_half_open`: bookings spread across separate VT_PASSED joints instead of re-booking one NDT_IN_PROGRESS joint (§3.6 requires `VT_PASSED` to schedule).
- `continuity_expiry_prospective_vs_retrospective`: all clock moves are forward (PRD states no regression rule); the 183-day math was recomputed (2026-01-01 + 183d = 2026-07-03, not the yaml's 07-02 — no assertion depended on it).
- Repair-rate instances: normal passes recorded before repair passes, since the inclusive `>=` gate trips mid-buildup otherwise.
- `weldment_posture_freeze_unfreeze_conservation`: distortion reports dispositioned before the NDT FAIL, so the weldment is literally `OPEN` when freeze criteria recompute (satisfies §3.7's "on an `OPEN` weldment" under the strictest reading).

### Queue A — 3 instances skipped (PRD-first filter)
- `priority_pair_validation_conflict/safety_vs_fiscal_on_consumable_issue` — asserts `ERR_LOT_NOT_USABLE` at issue time, but PRD §3.3 assigns `ERR_LOT_NOT_IN_OVEN` to issuing from a non-IN_OVEN lot (`ERR_LOT_NOT_USABLE` is scoped to weld-pass time); asserted outcome contradicts the PRD.
- `resource_temporal_overlap/fixture_capacity_aggregate_overlap` — PRD defines `capacity_weldments` semantics but never states an enforcement rule or error when exceeded (the instance itself only expects "ERR_INVALID_REQUEST OR a capacity-specific error"); not uniquely derivable.
- `compensating_invariant/consumable_kg_conservation` — PRD self-contradicts on whether a return restores `remaining_kg` (the derived-formula sentence ⇒ 47, the draw-down prose ⇒ 27); the asserted 27 also violates the instance's own stated invariant (50 ≠ 27+3+0).

### Queue B (Corner) — all 30 non-stub instances covered
All 8 `errors`-section stubs correctly not translated (their cross-references were checked; several point at corner rather than difficulty instances — e.g. `error_wps_not_approved` → `joint_start_fab_with_superseded_wps_returns_error` — noted as corner-design pointer bugs, no tests emitted). Two judgment calls: `oven_creation_rejects_invalid_holding_temp` asserts `ERR_INVALID_REQUEST` (the only generic 400 input error the PRD names, §2.8); `weldment_system_fields_server_managed` asserts the PRD-pinned defaults (posture OPEN, zeroed counters, null `signed_off_at_utc`, UUID id) and drops the yaml's `version == 1` since the PRD never pins the initial version value.

### Files
- `test_helpers/` (all under `/home/ubuntu/github/CodingPRD/tasks/task_2026_welding_weldment_contract_shop/`): `__init__.py` (barrel), `types.py` (10 role/status enums, 18 TypedDicts — ledger entities omit `updated_at`/`version`), `api_client.py` (all 65 PRD §4 endpoints incl. flat GETs), `api_errors.py` (40-entry catalog registered via `set_error_http_status_map`), `assertions.py` (per-entity asserts + instant-compare at second granularity + 2dp percent assert), `factories.py`, `constants.py` (183d, 240min, caps, pagination), `test_users.py` (shared constants + `make_*` builders; `make_welder_headers(welder.id)` threaded for all weld-pass calls), `fixtures.py` (~15 creation helpers + `setup_fab_workspace`, `setup_supersession_scenario`, `setup_weldment_at_repair_rate`, `setup_vt_passed_workspace`, `setup_frozen_weldment`, pass-ordering helpers).
- `test_suite/`: `conftest.py` + `test_01_platform_rbac.py` (9), `test_02_pqr_wps_approval.py` (10), `test_03_wps_supersession_cascade.py` (8), `test_04_welder_continuity.py` (6), `test_05_consumables_oven_exposure.py` (8), `test_06_joints_fabrication.py` (6), `test_07_repair_rate_posture.py` (9), `test_08_inspections_ndt.py` (5), `test_09_freeze_ship_closeout.py` (4).

## Step 6: Generate implementation — 2026-08-15T09:40:00.000Z

Implementation complete and verified. Final summary:

## Implementation summary

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_2026_welding_weldment_contract_shop/workspace/implementation/`

**Files (2,815 lines total):**
| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher, guarded `pip install`, `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | `flask>=3.0` |
| `app.py` | 51 | App factory, blueprint registration, envelope error handlers (ApiError/404/405/500) |
| `db.py` | 31 | In-memory dict store, empty at boot (no seeding) |
| `errors.py` | 70 | `ApiError` + all 38 catalog error IDs |
| `response.py` | 50 | Envelope: `meta{api_request_id, api_request_timestamp}`, `response_type`, `data`; list meta adds `limit/offset/total_count/has_more` |
| `middleware.py` | 62 | `X-User-ID`/`X-User-Role` validation, role authorization |
| `helpers.py` | 160 | Datetime/Decimal/pagination/enum helpers |
| `serializers.py` | 276 | 16 entity serializers (versioned vs ledger field sets) |
| `services.py` | 365 | Cascades, posture derivation, continuity sweeps, gates |
| `routes/*.py` | 1,703 | 7 route modules + flat-GET registrar |

**Endpoint coverage: 99/99** (verified programmatically against the PRD §4 table; no extras). Verified by two smoke suites run against live server (all pass): full happy path to SHIPPED, OCC 412s, segregation 403s, PQR/WPS gates, continuity lapse/requalify/revoke, oven/lot/issue/return/exposure/quarantine/rebake, offline cascade, slot conflicts (half-open), too-early results, repair cycles → hard-cap cancel, REPAIR_REVIEW/RESTRICTED/FROZEN postures, supersession cascade + rebind, traveler step-role gates, cancel/SCRAP cascades, pagination + envelope shape, reboot-clean empty store via `bash start.sh`.

**Ambiguities resolved (PRD silent or self-contradictory):**
1. **Clock endpoint targets no shop in path** — body accepts optional `shop_id`; without it, sets *all* shops' clocks and returns the targeted shop / the only shop / the first-created shop.
2. **CUSTOMER-fixture ship disposition** — no "release-to-customer record" endpoint exists in the API surface, so `owner_party == CUSTOMER` always fails ship with `ERR_FIXTURE_NOT_DISPOSITIONED`; SHOP fixtures require `AVAILABLE`/`IN_USE`.
3. **`remaining_kg` on return** — per the entity's computed formula (`received − passes − open issues`), a return credits `issued_kg` back; a VOID (oven-offline cascade) does not (material lost).
4. **Issue-to-zero** — per the PRD issue narrative the lot becomes `ISSUED` unconditionally; `EXHAUSTED` is applied when weld-pass consumption drives `remaining_kg <= 0` and on return-with-nothing-left.
5. **Repair-cycle semantics** — `repair_cycle_count` increments on NDT FAIL (state machine); `> 2` cancels the joint (fabrication); `declare-repair` rejected with `ERR_REPAIR_CYCLE_LIMIT` only when count already `> 2` (i.e., post-cancel), keeping both scaffold rules live.
6. **Frozen gate source state** — FROZEN and REPAIR_REVIEW derive only from `OPEN` (per the calculation formulas), never from RESTRICTED.
7. **Weld-pass joint-state gate** — PRD §3.5 specifies exactly three gates (continuity, lot usability, posture OPEN), so no fabrication-status gate is enforced on pass recording.
8. **In-flight inspection "void"** — implemented as deletion ("discarded", and the Inspection entity has no status field), which also releases vendor slots.
9. **Repair weld-out final state** — `inspection_status` ends at `READY_FOR_VT` (passing through `REPAIR_WELDED_OUT` per the state-machine side effect) with `fabrication_status = WELDED_OUT`; repair-pass gate uses `welded_at_utc >= last NDT_FAILED` (inclusive, second-granularity clock).
10. **Missing-body-FK references** (e.g., `lot_id` on issue, `wps_id` on joint) resolve to `ERR_NOT_FOUND` 404; a missing PQR at WPS-approve time surfaces `ERR_PQR_NOT_APPROVED` 422.
11. **Welder identity on pass recording** — payload `welder_id` must equal `X-User-ID` (PRD §2.1 identity rule), else `ERR_INSUFFICIENT_PERMISSIONS` 403.
12. **Uniqueness fields** (`stencil`, `pqr_number`, `po_number`, `weldment_serial`) are not enforced — the error catalog defines no uniqueness violation for them (only `ERR_WPS_REVISION_CONFLICT` at WPS-approve time, which is enforced).
13. **Version starts at 1**; exactly one version bump per mutated entity per request (cascades bump each affected entity once); weldment version additionally bumps on any recorded inspection result or distortion disposition (PRD §2.6 OCC narrative).

## Step 7: Run tests and iterate — 2026-08-15T09:45:00.000Z

All 8 rounds passed cleanly. Here is the summary:

---

**Summary**

- **Iterations run:** 1 (single 8-round parallel sweep, all clean on first pass)
- **Tests deleted:** None
- **Fixes applied to `test_helpers/`:** None
- **Fixes applied to `test_suite/`:** None
- **Fixes applied to `implementation/`:** None

All 68 tests passed in all 8 parallel rounds. No flakiness, no failures, no diagnostic work needed. The implementation and test suite are stable and consistent.

## Step 8: Finalize PRD — 2026-08-15T09:45:00.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — `PRD.md` already determined every behavior the implementation exhibits. No `PRD_FINALIZED.md` produced; Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-08-15T09:58:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_2026_welding_weldment_contract_shop/workspace/PRD_COMPLETED.md` produced — 29 paragraphs changed, all in-place edits (no new sections, line count unchanged).

**Source vs completed:** `PRD.md` 390 lines / 61,353 chars → `PRD_COMPLETED.md` 390 lines / 69,072 chars (delta +7,719 chars).

**Counts:** 24 ambiguity-pins, 5 mismatch-revisions.

Changes (each `{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`):

- §2.4 — insert — ambiguity — `version` starts at 1; one bump per mutated entity per request; weldment version also bumps on any recorded inspection result and on any distortion disposition — services.py:31-39, quality.py:104-105,152-153
- §2.5 — revise — ambiguity — clock endpoint takes no shop in path; optional body `shop_id` (unresolvable → 404); without it sets all shops and returns first-created; 404 when no shops; sweep re-derives only OPEN/RESTRICTED — routes/shops.py:28-55
- §2.8 — insert — ambiguity — body-referenced FKs resolve to `ERR_NOT_FOUND` 404 (except PQR at WPS-approve); undefined method on a valid path → `ERR_NOT_FOUND` 404 — joints.py:43-46, production.py:170, app.py:38-39
- §3.1 — revise — ambiguity — `pqr_number` uniqueness not server-enforced — docs.py:39-52 (no check)
- §3.1 — revise — ambiguity — missing/non-APPROVED PQR at WPS-approve surfaces `ERR_PQR_NOT_APPROVED` 422, not 404 — docs.py:169-172
- §3.1 — insert — ambiguity — PQR reject of non-DRAFT → same `ERR_PQR_NOT_DRAFT` — docs.py:92-93
- §3.1 — insert — ambiguity — WPS reject of non-DRAFT → same `ERR_WPS_NOT_DRAFT` — docs.py:216-217
- §3.2 — revise — ambiguity — `stencil` uniqueness not server-enforced; `SUSPENDED` only system-derived, `TERMINATED` never system-assigned — shops.py:105-113, services.py:125-137
- §3.2 — revise — ambiguity — qualification creation: body FKs → 404; process mismatch vs WPS → `ERR_INVALID_REQUEST`; WPS need not be APPROVED at creation — quals.py:28-33
- §3.2 — insert — ambiguity — revoke from other than QUALIFIED/LAPSED → generic `ERR_INVALID_STATE` — quals.py:100-101
- §3.3 — insert — mismatch — issue draws lot to `ISSUED` unconditionally even at zero; `EXHAUSTED` only via pass consumption or return-to-zero (PRD previously claimed issue-to-zero → EXHAUSTED) — materials.py:192-193, joints.py:258-260, materials.py:244-247
- §3.3 — revise — ambiguity — return credits `issued_kg` back to `remaining_kg`; return of non-OPEN issue → `ERR_INVALID_STATE`; VOID issues never credited — materials.py:231-241, services.py:330-331
- §3.3 — revise — ambiguity — rebake checks the lot's own oven ONLINE → `ERR_OVEN_NOT_ONLINE` — materials.py:161-163
- §3.3 — revise — mismatch — take-offline requires ONLINE, bring-online requires OFFLINE, else `ERR_INVALID_STATE`; EXHAUSTED triggers restated to match impl (drop "drawn down by an issue") — materials.py:67-70,80-83
- §3.4 — insert — ambiguity — `capacity_weldments` recorded but not enforced — production.py (no check anywhere)
- §3.4 — revise — ambiguity — `po_number` and `weldment_serial` uniqueness not server-enforced; weldment creation has no fixture-status or order-status gate — production.py:122-138, 163-189
- §3.4 — revise — ambiguity — fixture reserve/release/send-for-repair state violations → generic `ERR_INVALID_STATE` — production.py:71-72,83-91,102-110
- §3.5 — revise — ambiguity — joint creation: body `wps_id` → 404, need not be APPROVED; no weldment-posture gate — joints.py:43-46
- §3.5 — insert — ambiguity — payload `welder_id` must equal `X-User-ID` else `ERR_INSUFFICIENT_PERMISSIONS` 403; body FKs → 404; no fabrication-status gate on pass recording — joints.py:217-222
- §3.5 — revise — ambiguity — start-fabrication fixture gate violation → generic `ERR_INVALID_STATE` — joints.py:113-114
- §3.5 — revise — mismatch — repair weld-out: repair-pass gate inclusive (`welded_at_utc` at-or-after last NDT_FAILED qualifies); `REPAIR_WELDED_OUT` is transient, persisted state is `WELDED_OUT`/`READY_FOR_VT`; inspection status only advances from NOT_READY/REPAIR_REQUIRED — joints.py:131-153
- §3.6 — revise — ambiguity — VT booking without inline result has no joint-state gate; VT result (inline or deferred) requires READY_FOR_VT; VT FAIL records result but drives no joint transition, no cycle increment, no freeze evaluation — quality.py:184-191, 142-148
- §3.6 — revise — ambiguity — record-result lifecycle: UT/RT require NDT_IN_PROGRESS, VT requires READY_FOR_VT; elapsed-slot check applies to all methods incl. VT; inline UT/RT results allowed with same check; every recorded result bumps weldment version; UT/RT PASS with methods outstanding stays NDT_IN_PROGRESS; cancel-by-cap keeps inspection_status NDT_FAILED — quality.py:127-153, 208-210, 265-284, services.py:351-365
- §3.7 — revise — ambiguity — distortion report: `joint_id` resolved within the weldment (cross-weldment → 404); no joint-state or posture gate — quality.py:48-51
- §3.7 — revise — ambiguity — freeze void = outright deletion of unresulted inspection rows (later reads → 404); unfreeze gate = no joint still NDT_FAILED; violations → `ERR_INVALID_STATE`; cap-cancelled joint blocks unfreeze forever — services.py:194-203, production.py:294-299
- §3.7 — revise — ambiguity — clear-repair-review violations → `ERR_INVALID_STATE` — production.py:278-281
- §3.7 — revise — mismatch — declare-repair rejected with `ERR_REPAIR_CYCLE_LIMIT` only when count already exceeds 2 (the cap-cancel at third FAIL is what produces that state); non-NDT_FAILED → `ERR_INVALID_STATE` — joints.py:162-166
- §3.8 — revise — ambiguity — sign-off role violations → `ERR_INSUFFICIENT_PERMISSIONS`; no posture gate; FINAL missing prior steps → `ERR_TRAVELER_INCOMPLETE` — quality.py:302-311
- §3.8 — revise — mismatch — CUSTOMER-owned fixture can never ship: no release-to-customer record type exists, so the gate always fails with `ERR_FIXTURE_NOT_DISPOSITIONED`; SHOP requires AVAILABLE/IN_USE — production.py:242-248
- §3.8 — revise — ambiguity — cancel requires OPEN posture (else `ERR_INVALID_STATE`); cancels every joint not already CANCELLED including WELDED_OUT; in-flight inspections deleted — production.py:262-263, services.py:270-280

All 13 generation-time resolutions were verified against the implementation and are pinned (resolution 4 turned out to be a genuine PRD mismatch — PRD said issue-to-zero → EXHAUSTED, impl keeps ISSUED; revised). No changes were made to the endpoint table or error catalogue, as impl matched both.
