# Worklog — task_2802_water_heater_manufacturing

## Step 1: Create task directory — 2026-09-04T23:45:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2802_water_heater_manufacturing` and `.../workspace`. Index 2802 was pre-assigned by the invoker; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-05T01:28:00.000Z

Scaffold generation for task 2802 is complete and lint-clean.

Output files (`tasks/task_2802_water_heater_manufacturing/`)

| file | bytes | lines |
|---|---|---|
| `SCAFFOLD.yaml` | 168,059 | 3,432 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 143,063 | 2,423 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 476,615 | 8,218 |

Each design file has exactly one top-level key (`scaffold_difficulty_design` / `scaffold_corner_design`); `SCAFFOLD.yaml` contains neither. No sibling task was read, and the difficulty directive line appears nowhere in any file (verified by string scan).

SCAFFOLD.yaml (§1.0–§1.7): 14 entities (Supplier, ComponentLot, ProductModel, RatingCertification, EfficiencyTest, TestCell, Furnace, GlassLiningBatch, TankLot, LiningInspection, HeaterUnit, WarrantyClaim, RecallCampaign, RecallNotice) · 11 state machines · 2 concurrency rules · 17 calculations · 41 ordered validations · **85 endpoints** · 67 errors · 8 roles. Profile: `graph` topology, `cyclic` state machines, `immediate` consistency, layers `optimistic_concurrency` + `cascading_side_effects` + `dual_variant_calculation` + `derived_field_reconciliation`.

§1.8 rules (9 rules / 19 instances)
- `dual_variant_calc` 2 — `tank_failure_rate_cohort_naive_vs_exposure_weighted`, `recall_completion_notice_based_vs_population_based`
- `combinatorial_formula` 3 — `uef_effective_minimum_multistage_tier_derate_credit`, `certified_uef_round_per_test_then_mean`, `recall_remedy_admin_fee_tier_pinned_from_provisional`
- `non_linear_state_machine` 2 — `tank_lot_reline_cycle_returns_to_lined`, `product_model_parallel_dimensions_independent`
- `transitive_cascade` 2 — `supplier_disqualification_three_hop_to_model_restriction`, `lining_fail_quarantine_cascades_sibling_lots`
- `priority_pair_validation_conflict` 2 — `unit_state_beats_model_not_certified_on_label`, `sod_inspector_beats_sample_size_on_inspection`
- `boundary_precision_check` 2 — `holiday_density_exactly_at_max_passes`, `uef_margin_exactly_zero_passes`
- `cross_entity_state_dependency` 2 — `component_lot_release_requires_supplier_qualified`, `unit_label_requires_model_certified_and_released`
- `resource_temporal_overlap` 2 — `furnace_window_exclusive_half_open_adjacency_allowed`, `test_cell_parallel_slots_plus_cooldown_buffer`
- `compensating_invariant` 2 — `rework_reversal_restores_tank_count_ledger`, `payment_reversal_restores_warranty_reserve_ledger`

§1.9 sections (9 sections / 85 instances, of which 25 are `excluded_because` stubs): entities 11 · state_machines 14 · calculations 17 · validations 18 · endpoints 7 · errors 3 · rbac 5 · cross_cutting_complexity_layers 8 · consistency_model 2. Every stub cites a §1.8 instance that exists by name (verified). All 67 catalog error ids are asserted by at least one instance across the two design files.

Scaffold repairs the §1.9 audit forced (unreachable preconditions fixed, never weakened)
- Added `ERR_INVALID_MODEL_STATE` (409) plus its priority-8 family membership — ProductModel had no invalid-state error, so "release an already RELEASED model" / "lift a restriction on a non-RESTRICTED model" were inexpressible.
- Broke a mutual deadlock between `POST /mfg/component-lots/{id}/unblock` (needed a qualified supplier) and `requalify` (needed `blocked_lot_count == 0`): the containment gate moved from requalify onto the following `qualify`, and unblock now accepts a PENDING supplier. This made the unblock success path reachable at all.
- Added `GET /mfg/lining-inspections/{id}`, the only route that can trigger `ERR_LINING_INSPECTION_NOT_FOUND`.
- Extended priority 11 to cover `POST /mfg/heater-units/{id}/release-hold`, which had a component-lot precondition with no declared error.
- Fixed a contradiction in the disassemble endpoint's side effects: it claimed a CONSUMED lot "returns to RELEASED" while `terminal_states` and the HeaterUnit transition both say a CONSUMED lot is never resurrected. Endpoint text now matches the state machine.
- Two `input:` declarations corrected to optional (`certificate_of_conformance?` — the field has `default: false`; `production_period?` on the warranty-analysis computed read — a query param whose mandatory-in-practice status is now stated in the description and enforced via `ERR_INVALID_REQUEST`).

Lint

```
Coverage
  §1.5 endpoints declared:    85
  §1.1 entities declared:     14
  §1.8 instances scanned:     19
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  2148

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy shared files — 2026-09-05T01:29:00.000Z

Copied `INSTRUCTION.md` (1424 bytes) to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T01:52:00.000Z

PRD.md is complete and verified.

Output: `workspace/PRD.md` — **530 lines / 116,663 bytes**, ends with a trailing newline on the final row of the §5 error table (a real section boundary, no audit footer). Orchestrator independently re-verified the tail: last line is `| \`ERR_BLOCKED_LOTS_REMAIN\` | 409 |`, a complete table row — not truncated. No leak of the difficulty directive or the word SCAFFOLD into PRD.md.

Section list
- `# Water Heater Manufacturing API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` (11 subsections): 2.1 User and Role-Based Access Control · 2.2 API Response Structure · 2.3 Pagination · 2.4 Common Resource Properties and the Immutable Inspection Record · 2.5 The Logical Plant Clock · 2.6 Precision and Rounding Discipline · 2.7 Version Pinning on Shared Parents · 2.8 Request Admission Order · 2.9 Transitive Containment and Cascade Discipline · 2.10 Segregation of Duties · 2.11 Conserved Ledgers and Compensating Actions
- `## 3. Business Logic & Workflows` (9 subsections): 3.1 Supplier Qualification and Incoming Component Control · 3.2 The Catalogue: Models, Private-Label Variants and Two Independent Postures · 3.3 Glass-Lining Furnaces and Firing Windows · 3.4 Tank Fabrication, Lining Verification and Lot Release · 3.5 The Efficiency Test Programme · 3.6 Rating Certification, Publication and Revocation · 3.7 Unit Staging, Assembly, Serialisation and Shipment · 3.8 Warranty Adjudication, the Reserve Ledger and Field Failure Analysis · 3.9 Recall Campaigns and Serial-Based Remedy Tracking
- `## 4. Endpoint Definitions` (4-column table, 85 rows)
- `## 5. Error Code Catalogue` (2-column table, 67 rows)

Coverage verification (all machine-checked against SCAFFOLD.yaml)
- **Contract 1 — field names: PASS.** 137 unique required identifiers; 0 missing. 475 backticked tokens outside code fences.
- **Contract 2 — rules: PASS.** 67/67 error IDs in §1–§3 prose *and* §5 table; 53/53 state names; 8/8 roles; all enum values; 85/85 endpoint rows verbatim in §4; 47 explicit `X → Y` arrows with 0 non-existent pairs; remaining 29 transitions are cascade/system hops described in prose. All 17 calculations, both OCC rules, the 41-item admission ladder and all 4 conserved-ledger invariants rendered.
- **Contract 3 — §3 path purity: PASS.** 0 violations across §3 (lines 194–365).
- §2.2 byte-identical against `section-2.2-response-structure.md`. Style scans clean.

Defects the doc generator caught and fixed during its own verification
1. WarrantyClaim initial state `REPORTED` → `OPEN` (6 places).
2. Invented fields `part_cost_cents` / `labor_cost_cents` / `freight_cost_cents` described as stored — reworded to unpersisted intermediates; only `approved_payout_cents` and `coverage_pct` are stored.
3. Wrong ledger field `warranty_reserve_paid_cents` → `warranty_paid_cents` (3 places).
4. Invented `announced_at` / `closed_at` on RecallCampaign removed; replaced with the four real derived fields.
5. Wrong role on all 13 recall endpoints: `ComplianceEngineer` → `WarrantyAnalyst` (8 replacements in §3.9 + 2 computed reads).
6. Two consistency repairs: §2.1 no longer claims `GET /mfg/_clock` is auth-exempt; §3.2 cross-reference retargeted from §3.7 to §3.6.

Confirmed: neither design yaml nor any sibling task was read.

## Step 6: Generate Implementation — 2026-09-05T02:29:00.000Z

ORCHESTRATOR NOTE: this subagent died mid-run at ~02:12 with an infrastructure API error ("The system encountered an unexpected error during processing"), having written 57/85 endpoints and no `app.py`. Rather than respawn a fresh generator (which would diverge stylistically from the 57 finished routes), the orchestrator diffed `routes/` against the PRD §4 endpoint table, computed the exact 28-endpoint remainder plus the missing `app.py`, and resumed the SAME agent via SendMessage with that to-do list. The agent finished from its retained context. Subagent's own summary follows verbatim.

The implementation is complete.

## Modules written (22 files, 3,845 lines)

| File | Lines | Role |
|---|---|---|
| `app.py` | 100 | Flask factory, 9 blueprints at `/mfg`, ApiError + 400/404/405/HTTPException/500 handlers, `PORT`/0.0.0.0 entrypoint |
| `db.py` | 135 | In-memory `Store` (14 dicts), logical clock defaulted to `2026-08-01T00:00:00Z`, ts format/parse, `make_row`/`touch`/`ordered` |
| `errors.py` | 93 | All 68 error IDs → HTTP status, `ApiError` |
| `response.py` | 98 | Envelope (`meta`/`response_type`/`data`), `req_`+20 char id, offset pagination (10/1/100) |
| `middleware.py` | 60 | `@endpoint([roles])` — 401 → 403 gate, 8 roles |
| `validation.py` | 144 | Ladder position 4 helpers (string/enum/integer/number/boolean/timestamp/forbid, query params) |
| `serializers.py` | 374 | 14 entity projections incl. all computed reads; `LiningInspection` emits no `updated_at`/`version` |
| `services/calc.py` | 331 | Every pinned calculation with `Decimal`/`ROUND_HALF_UP` |
| `services/core.py` | 216 | `resolve`/`rows`/`require_unique`, `hold_unit`, `restrict_model_if_released`, the 3 cascades, `recall_population` |
| `routes/clock.py` | 25 | 2 endpoints |
| `routes/suppliers.py` | 311 | 13 |
| `routes/assets.py` | 165 | 9 |
| `routes/models.py` | 265 | 9 |
| `routes/tanklots.py` | 402 | 15 |
| `routes/tests.py` | 347 | 11 |
| `routes/units.py` | 297 | 8 |
| `routes/warranty.py` | 170 | 7 |
| `routes/recalls.py` | 301 | 13 |
| `start.sh` (exec bit set), `requirements.txt`, 2 `__init__.py` | 11 | launcher reads `$PORT`, binds 0.0.0.0, `exec`s in foreground, pip install only when flask is missing |

## Endpoint coverage: 85/85

Verified programmatically — extracted the 85 `| METHOD | path |` rows from PRD §4 and diffed them against `app.url_map` with `<param>` normalised to `{id}`: **MISSING: [] / EXTRA: [] / MATCHED: 85/85**.

## Smoke test: pass

Started on `PORT=18802`, then a second boot via `./start.sh` on `PORT=18803`. Two scripted runs (~120 requests) covering the full chain plus all three cascades; zero unexpected status codes. Spot-checked figures all match the PRD's own worked examples:

- Payout at 0.50 coverage = **28676** (20750 + 6263 + 1663 — both half-up boundaries observable)
- `GAS_VALVE_KIT` per-unit remedy = **20700** (band chosen once from the 18000 provisional subtotal, not re-banded)
- Serial `EL50-202608-00001`; holiday density exactly `0.5` → PASS; achieved R `18.0` from 45 mm; hardness 7.0 → `MODERATE`/1.00; 73 months frozen; exposure-weighted rate 13698.6 vs naive 1000000.0
- Lining-failure cascade: batch → `QUARANTINED`/`REPEAT_LINING_FAILURE` at `rejected_lot_count` 2, sibling lot swept to `LINING_REJECTED` with `cascade_rejected: true`, `last_scrap_quantity: null`, quantities untouched; both reversal refusals returned 409; the inspected lot's version advanced exactly once per filing
- Supplier disqualification: lot `BLOCKED` → unit `HELD`/`COMPONENT_LOT_BLOCKED`/`held_from_status: ASSEMBLED` → model `RESTRICTED`; recovery path requalify → unblock → release-hold → lift-restriction all succeeded, and the piece ledger returned to 9/0/9 after disassembly
- Envelope, 401/403/404/405, malformed-JSON 400, and pagination meta all correct; a fresh boot reports `total_count: 0` and the default clock

Both servers were stopped by exact PID (`ss -ltnp` used to find the real python PID, since `$!` was the bash wrapper); ports confirmed released, no broad `pkill` used. `__pycache__` and temp scripts removed. Storage is in-memory only, with no seeding and no disk I/O.

One decision worth flagging: PRD §2.1 ("no unauthenticated endpoints… including the logical-clock read") conflicts with §2.8 item 1 ("every endpoint except the logical-clock read"); I implemented 401 on all 85 endpoints including `GET /mfg/_clock`. Also, `ERR_DUPLICATE_CAMPAIGN_CODE` appears only in §3.9 prose and is absent from both §5 and the scaffold, so recall-campaign code collisions report `ERR_DUPLICATE_CODE` (409) per §2.8 item 23.

## Step 5: Generate Unit Tests — 2026-09-05T04:04:00.000Z

All 17 test files are complete. `test_17_cross_cutting_consistency.py` closed the last two queue B sections.

## Files written

**`test_helpers/`** (9 files, 2,452 lines): `__init__.py` 153, `api_client.py` 511, `api_errors.py` 180, `assertions.py` 176, `constants.py` 193, `factories.py` 332, `fixtures.py` 484, `test_users.py` 118, `types.py` 305.

**`test_suite/`** (conftest + 17 files, 9,370 lines):

| file | tests | file | tests |
|---|---|---|---|
| test_01_variant_divergence | 8 | test_10_entity_shapes | 22 |
| test_02_composite_formulas | 8 | test_11_state_transitions | 18 |
| test_03_state_machine_cycles | 8 | test_12_calculations | 17 |
| test_04_transitive_cascades | 9 | test_13_validation_ladder | 20 |
| test_05_validation_priority | 6 | test_14_validation_guards | 23 |
| test_06_boundary_precision | 7 | test_15_endpoint_behaviours | 29 |
| test_07_cross_entity_state | 6 | test_16_errors_and_roles | 30 |
| test_08_resource_windows | 10 | test_17_cross_cutting_consistency | 29 |
| test_09_compensating_ledgers | 10 | **TOTAL** | **260** |

## Design-index coverage

Machine-verified against both YAMLs: **79 distinct `Design:` tags over 260 tests; every tag resolves to an existing non-stub instance; no unknown tags, no stub-tagged tests, no dual tags, exactly one `Design:` line last in every docstring.**

- **Queue A (§1.8 difficulty): 19/19 non-stub instances translated, 0 skipped** (72 tests, files 01–09). The index declares no stubs.
- **Queue B (§1.9 corner): 60/60 non-stub instances translated, 0 skipped** (188 tests, files 10–17). The 25 `excluded_because` stubs were correctly left untranslated — each is subsumed by a named §1.8 instance.

New in this file: `cross_cutting_complexity_layers` (4/4 non-stub: both OCC version pins, the supplier version ledger, the `held_unit_count` reconciliation) and `consistency_model` (1/1 non-stub: derived fields visible in the writing response).

## Verification run

- Audit over all 17 files: `TOTAL 260 PROBLEMS 0` — every `PRD: "..."` quote is a whitespace-normalized substring of `workspace/PRD.md`, no "scaffold" string anywhere, one trailing `Design:` line per test.
- Per-file AST hygiene: `UNUSED: []` / `MISSING: []` (removed a stray `component_lot_payload` import).
- All 17 modules import cleanly against `test_helpers`.
- No `test_helpers/` or `test_suite/` anywhere under `workspace/`; `worklog.md` untouched; no server started.

## Design/PRD conflicts resolved in favour of the PRD (7)

1. `Corner/entities/component_lot_certificate_of_conformance_defaults_false` asserted `ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED`; PRD line 212 attaches `ERR_INVALID_COMPONENT_LOT_STATE`.
2. `Corner/entities/heater_unit_reverse_lookup_by_each_foreign_key` asserted consumed 1 / remaining 49; PRD line 302 says a staged unit has not drawn its pieces (asserted 0 / 50).
3. `Corner/calculations/supplier_score_below_conditional_floor_...` asserted error-*message* content the envelope does not derive; replaced with an observable corrective-action clamp (100/0/10 CAPAs → 75.00 CONDITIONAL).
4. `Corner/validations/missing_headers_beat_forbidden_role_...` asserted the clock read works with no headers; PRD line 15 closes it — that assertion dropped.
5. `Corner/validations/recall_scope_range_and_budget_guards_rejected` asserted `affected_unit_count == 0` on a DRAFT campaign that PRD line 344 says is *unset*; asserted `status == "DRAFT"` and both serial-range fields null instead.
6. `Corner/cross_cutting.../version_increments_on_every_write_and_never_on_a_read` asserted `qualification_score == 91.40` for 94 audit / 1200 ppm / 0 CAPA; the PRD weights give 0.40×94 + 0.35×76 + 0.25×100 = **89.20** (91.40 is the 96/1000/0 figure). Asserted 89.20.
7. Minor: the design's `rejected_lot_count` on `Supplier` is not a PRD-declared field, so only `blocked_lot_count` is asserted.

## Two judgement calls worth a second opinion

- `Corner/validations/private_label_base_and_release_rules_rejected` wants 400 `ERR_INVALID_REQUEST` for a private-label variant missing `brand_label` and for a non-private model supplying one. PRD line 222 enumerates exactly four violations mapping to 422 `ERR_PRIVATE_LABEL_BASE_INVALID`, none about `brand_label`, while validation rung 4 covers "required inputs present" — translated as 400 on that reading rather than skipped.
- `held_unit_count_reconciles_across_hold_release_and_scrap` has the second hold release succeed while the supplier is only `PENDING`. Rung 11 lists "unit hold release" under the supplier-qualified gate, but §3.7 line 318's `ASSEMBLED` branch literally requires only that every referenced lot be back in `RELEASED`. Followed §3.7 (which matches the design).

## Step 7: Run Tests and Iterate — 2026-09-05T05:52:00.000Z

ORCHESTRATOR VERIFICATION: the orchestrator independently read all 8 `workspace/implementation/results.$i.json` files after the agent exited — every round reports `281 / 281`. The baseline sweep was also independently observed at `271 / 281` in all 8 rounds (identical failure count each round, i.e. deterministic, no reaping and no load-induced flakiness). Subagent's own summary follows verbatim.

All 8 parallel rounds are green: **281 passed / 281 total, 0 failed, 0 errors** in every round.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (iteration 1 = baseline diagnosis: 271/281 in all 8 rounds, identical failure set every round, so zero flakiness and no sweep reaping; iteration 2 = post-fix: 281/281 in all 8 rounds).

**Tests deleted:** none. All 10 failures traced to test-side bugs against PRD sentences that do cover and uniquely determine the behaviour, so no PRD-silence deletion was warranted.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `make_supply_base`, the valve-supplier `qualify_supplier` call: `open_capa_count` 1 → 0. The fixture's own docstring promises "Two qualified suppliers", but PRD §2.2's formula uniquely yields `0.40·92 + 0.35·70 + 0.25·87.5 = 83.175 → 83.18` = CONDITIONAL; with 0 open CAPAs it is 86.30 = QUALIFIED, which is what the fixture and its consumer both intend. (Fixed `test_04::test_02`.)
- `test_helpers/factories.py` — `safety_valve_supplier_payload` docstring no longer claims a QUALIFIED band; registration data is never scored, so the claim was unverifiable and misleading.

**Fixes applied to `test_suite/`:**
- `test_11_state_transitions.py` (6 call sites) and `test_14_validation_guards.py` (1 call site) — headers/payload argument order. `api_client` declares reason-bearing optional-payload endpoints as `(id, headers, payload=None)`; these sites passed `reason_payload(...)` positionally into the `headers` slot, so the reason dict was sent as HTTP headers and the real headers as the JSON body — every request arrived with no `X-User-ID`/`X-User-Role` and got `ERR_UNAUTHENTICATED`/401. Affected: `scrap_tank_lot` ×2, `withdraw_model` ×2, `requalify_supplier` ×3, `reject_component_lot` ×1, `cancel_campaign` ×1. `test_17` and `test_15` already used the correct order, confirming the convention. Assertions untouched. (Fixed 6 failures.)
- `test_11_state_transitions.py::TestDeclaredInitialStates::test_02` — `assert stored_campaign["affected_unit_count"] == 0` → `is None`. The test's own quoted PRD §3.9 sentence lists `affected_unit_count` among the fields that are "all unset" on a DRAFT campaign, and lists only `notice_count`, `remedied_count` and the two percentages as "at their empty-campaign values of zero". The assertion contradicted the sentence it cited; the implementation was right.
- `test_16_errors_and_roles.py::_two_open_certifications_one_submitted` — reordered so the SUBMITTED certificate is opened first and the DRAFT second. PRD §3.6: "any certification of the same model still sitting at `DRAFT` or at `REJECTED` moves to the terminal `SUPERSEDED`". The old order created the draft first, so opening the second certificate legitimately superseded it and the fixture could never produce the live DRAFT its docstring described. Docstring corrected to match. Verified tests 22, 23 and 25 (the other three consumers) still pass.

**Fixes applied to `implementation/`:** none. No implementation defect was found; all 10 failures were test-side. `calc.py`, `serializers.py`, `core.py` and `db.py` were audited against PRD §2.x/§3.x formulas, ladders and cascades and matched. Storage remains in-memory dicts with no seeding.

**Notes for the record:** two internal PRD inconsistencies were observed but did not affect any test, so nothing was changed for them — §3.9 names `ERR_DUPLICATE_CAMPAIGN_CODE` while the §5 catalogue and §2.8 item 23 name `ERR_DUPLICATE_CODE`; and §3.1 hop 2 sets `label_status` INVALID for LABELED units on supplier disqualification while §3.7 says "Only a de-certification sets `label_status` to INVALID".

## Step 8: Finalize PRD — 2026-09-05T05:57:00.000Z

Step 8 was NOT skipped: Step 7 applied 2 `test_helpers/` fixes and 3 `test_suite/` fixes (0 implementation fixes, 0 deletions), so the skip condition (zero changes of any kind) did not hold. Because Step 7 made no implementation fixes, a near-identical PRD_FINALIZED.md was the expected legitimate outcome; the subagent was told so explicitly and instructed not to manufacture edits. It made 2 edits, both from the "Notes for the record" PRD self-inconsistencies. Subagent summary follows verbatim.

Done. Both edits applied; PRD_FINALIZED.md differs from PRD.md on exactly 2 lines.

## Line counts
- `PRD.md`: 530 lines
- `PRD_FINALIZED.md`: 530 lines
- **%-delta: 0.00% in line count; 2 of 530 lines revised (0.38% of lines touched)**

## Changes

- **§3.7 (holds paragraph, line 316) — revise** — `Only a de-certification sets label_status to INVALID.` → `A supplier disqualification and a de-certification each additionally set label_status to INVALID on a unit that was LABELED; a recall-scope hold is the one cause that leaves label_status exactly as it found it.` — `implementation/services/core.py:73-74` (`hold_unit`, `invalidate_label` branch), callers at `core.py:116` (supplier disqualification, `True`), `core.py:147` (revocation, `True`), `routes/recalls.py:149` (recall announce, `False`).
- **§3.9 (campaign creation, line 344) — revise** — `ERR_DUPLICATE_CAMPAIGN_CODE` → `ERR_DUPLICATE_CODE`, with a parenthetical tying it to §2.8 position 23 and the §5 catalogue — `implementation/routes/recalls.py:42` → `implementation/services/core.py:58-60`.

## Per-edit pre-edit search log

**Edit 1 — subject: which events set `label_status` to `INVALID`, and which do not.**
(b) Paths enumerated: `grep -rn "label_status"` over all of `implementation/` returned exactly five mutation/read sites — `routes/units.py:95` (stage → `NONE`), `:201` (label → `APPLIED`), `:214` (ship precondition requires `APPLIED`), `:249` (release-hold-to-`LABELED` precondition requires `APPLIED`), and `services/core.py:74` (the only assignment of `INVALID`). Read `services/core.py` in full to enumerate every `hold_unit` caller: `cascade_supplier_disqualification` (`invalidate_label=True`), `cascade_certification_revocation` (`invalidate_label=True`), and `routes/recalls.py:149` in the announcement fan-out (`invalidate_label=False`). Also read `routes/units.py` in full to confirm `disassemble_unit` and `release_hold` never write `label_status`, so `INVALID` is never cleared. Cross-checked against PRD §3.1 hop 2 and §3.6 hop 2, both of which already assert the `INVALID` write and are therefore left verbatim; §3.9 makes no such claim and is likewise left verbatim.
(c) Wording adjustment: I first drafted a longer sentence that also asserted "Nothing anywhere in the service ever moves `label_status` back out of `INVALID`." I verified that claim holds (no impl path returns an `INVALID` unit to `ASSEMBLED`, the only state from which `label` can re-stamp `APPLIED`), but cut it anyway — it is a universal claim wider than the Step 7 item warrants, and the guidance prefers under-determined wording. I also dropped the `§3.1 hop 2 / §3.6 hop 2` cross-reference as noise. Final wording is scoped to the three hold causes only, and to `LABELED`-prior units only, which is exactly the `prior == "LABELED" and invalidate_label` guard.

**Edit 2 — subject: the error identifier for a colliding `campaign_code`.**
(b) Paths enumerated: `grep -rn "DUPLICATE"` over `implementation/` — the only identifier that exists is `ERR_DUPLICATE_CODE` (registered at `errors.py:43`, 409); `ERR_DUPLICATE_CAMPAIGN_CODE` is absent from `errors.py`, so an impl following §3.9 literally could not even map it to a status. `grep -rn "require_unique"` enumerated all seven callsites — `routes/assets.py:33` (furnace_code), `:67` (batch_code), `:144` (cell_code), `routes/suppliers.py:194` (part_number, supplier-scoped), `routes/models.py:84` (model_code), `routes/tanklots.py:49` (lot_code), `routes/recalls.py:42` (campaign_code) — all funnel into the single `services/core.py:49` helper that raises `ERR_DUPLICATE_CODE` unconditionally. Confirmed `ERR_DUPLICATE_CAMPAIGN_CODE` appears nowhere in `test_suite/` or `test_helpers/` either. Also confirmed `require_unique` at `recalls.py:42` runs *after* `resolve("model", …)` at `:41`, consistent with the existing ladder text (position 5 before position 23), so no ordering claim needed touching.
(c) Wording adjustment: none to the substance; I added the clause "the same code-uniqueness identifier that §2.8 position 23 and the §5 catalogue name" so the sentence reads as reconciling the three sites rather than silently contradicting the reader's memory of §3.9.

## Items that correctly produced no edit
- `fixtures.py` `open_capa_count` 1 → 0: pure fixture arithmetic bug. `services/calc.py:55-73` matches §3.1's formula, the 0-floors, the weights, the round-half-up-to-2 and the rounded-score band selection exactly.
- `factories.py` docstring: registration data is never scored in `routes/suppliers.py`; no behavioral claim.
- `test_11`/`test_14` headers/payload positional-argument bugs (9 call sites): a `test_helpers/api_client.py` calling-convention error, invisible to the PRD.
- `test_11::TestDeclaredInitialStates::test_02` `affected_unit_count`: `routes/recalls.py:52` sets it `None` at creation, which is what §3.9's "all unset" (explicitly contrasted with "at their empty-campaign values of zero" for the other four) already uniquely determines.
- `test_16` fixture certificate-ordering reorder: §3.6's supersession sentence already determines the behaviour `routes/` implements.

## Step 9: Complete PRD — 2026-09-05T06:34:00.000Z

ORCHESTRATOR NOTE ON METHOD: Step 9 was run as THREE SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`, not as a single subagent. A single agent cannot hold 85 endpoints + 17 calculations + a 41-rung ladder against a 117KB PRD in one context, and the known failure mode is a "scan" that returns a byte-identical file. Pass 1 did the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden to run any `cp` (a copy would have destroyed the prior passes' edits). Partition: pass 1 = app/db/errors/response/middleware/validation + routes/clock, suppliers, assets; pass 2 = routes/models, tests, tanklots + serializers; pass 3 = routes/units, warranty, recalls + services/calc, core.

ORCHESTRATOR VERIFICATION: `PRD_COMPLETED.md` is 531 lines / 133,992 chars vs PRD_FINALIZED.md's 530 / 116,902 — NOT byte-identical (55 lines changed, +17,090 chars), so the scan demonstrably ran. Tail ends on a complete §5 table row (`| ERR_BLOCKED_LOTS_REMAIN | 409 |`), not mid-sentence. Both tables survived all three passes intact: 67 error rows and 85 endpoint rows still present. The Step 7 sweep artifacts are still on disk and still green: all 8 `results.$i.json` report 281/281.

TOTALS ACROSS THE THREE PASSES: 71 edits — 60 ambiguity-pins, 11 mismatch-revisions.

### Pass 1 (infra + clock/suppliers/assets) — 29 edits: 6 mismatch-revisions, 23 ambiguity-pins
PRD_FINALIZED 530 lines / 116,902 chars → PRD_COMPLETED 531 / 123,132 (+6,230). Agent booted the impl on a private port (8791) and probed with curl to confirm every pin empirically, then freed the port.

Mismatch-revisions
- §2.8 pos 1 — revise — "on every endpoint except the logical-clock read" → auth applies to *every* endpoint including the clock read (contradicted §2.1 and impl) — middleware.py:34-39 + routes/clock.py:23
- §2.8 pos 28 — revise — score floor "on supplier scoring and supplier requalification" → scoring only — routes/suppliers.py:162-176
- §3.1 — revise — "the same score-floor rule is declared on the requalification action as well as on scoring" removed; requalify takes only `reason_code` and computes no score — routes/suppliers.py:167
- §3.1 — revise — supplier disqualification "Four hops then fire" → "Three hops" (PRD itself only enumerated 3) — services/core.py:88-124
- §4 table — revise — `/disqualify` row "four-hop containment cascade" → "three-hop" — services/core.py:88
- §2.2 — revise — error envelope "(4xx status codes)" → "(4xx and 5xx)"; impl uses it for 500 too — app.py:83-90

Ambiguity-pins
- §2.2 — insert — unmatched route → `ERR_NOT_FOUND` 404, undeclared method → `ERR_METHOD_NOT_ALLOWED` 405, fault → `ERR_INTERNAL` 500, none in §5's catalogue; trailing slash accepted — app.py:45-62,83-90,35
- §2.2 — insert — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — response.py:21
- §2.2 — insert — `api_request_timestamp` is read from the logical clock, not wall clock — response.py:27
- §2.3 — insert — non-integer `limit`/`offset` → 400; omitted or empty → default — response.py:62-83
- §2.3 — insert — equal `created_at` ties broken by creation sequence (clock is frozen, so effective order is creation order) — db.py:133-135
- §2.3 — insert — `offset` past `total_count` → empty page, `has_more` false; unmatched filter → empty page not 404; undeclared query param ignored — response.py:93-98
- §2.3 — insert — multiple filters AND together; bad enum filter → 400, empty enum filter → absent — validation.py:127-137
- §2.8 pos 4 — insert — the big position-4 convention block: JSON `null` ≡ omitted; absent/empty body ≡ `{}`; non-object or unparsable body → 400; undeclared fields ignored; bool never a number/integer; integer rejects `900.0`; no string trimming; timestamp grammar (real calendar instant, `T…Z`, 1-9 fractional digits, offsets rejected, sub-ms truncated to 3 digits on output) — validation.py:17-124 + db.py:16-18,59-72
- §2.5 — insert — clock-set answers with an empty `data` object; the clock may be set backwards or to its current value — routes/clock.py:13-19
- §2.5 — insert — the store holds no rows at boot; nothing is seeded — db.py:26-43
- §2.1 — insert — whitespace-only header counts as empty; role names matched exactly/case-sensitively, so a misspelling is 401 not 403 — middleware.py:36-39
- §2.1 — insert — `SupplierRep` component-lot list: omitted `supplier_id` is forced to `X-User-ID`, a differing one is `ERR_SUPPLIER_SCOPE_VIOLATION`, checked after query validation — routes/suppliers.py:228-235
- §3.1 — insert — `audit_score` may be fractional; `defect_ppm`/`open_capa_count` are non-negative integers with no upper bound — routes/suppliers.py:56-58
- §3.1 — insert — the no-self-transition refusal runs *after* the position-28 score floor (a `QUALIFIED` supplier re-scored below 70.00 reports `ERR_SUPPLIER_SCORE_BELOW_FLOOR`), while the `DISQUALIFIED` refusal is the position-8 check — routes/suppliers.py:115-126
- §3.1 — insert — an accepted scoring call overwrites the stored `audit_score`, `defect_ppm`, `open_capa_count` — routes/suppliers.py:133-135
- §3.1 — insert — hop 3 bumps `version` on a visited model even when it did not move; hop 2 sees only lots blocked by hop 1 of the same request — services/core.py:105-124
- §3.1 — insert — `part_number` uniqueness is per supplier and spans every lot state (rejected/consumed lots still hold theirs) — routes/suppliers.py:194-199
- §3.1 — insert — the CoC test precedes both supplier checks on release — routes/suppliers.py:253-263
- §3.1 — insert — unblocking increments only the lot's `version`, leaving the supplier unstamped — routes/suppliers.py:293-311
- §3.1 — insert — rejecting a merely `QUARANTINED` lot bumps only the lot's `version` — routes/suppliers.py:281-289
- §3.3 — insert — `max_firing_temp_c` is a whole-degree integer — routes/assets.py:32
- §3.3 — insert — `firing_temp_c` is a whole-degree integer with no schema-level upper bound — routes/assets.py:62
- §3.5 — insert — `parallel_slots` and `cooldown_hours` are integers — routes/assets.py:142-143

Zero-edit module: `errors.py` only — all 67 `ERROR_STATUS` entries diffed programmatically against the §5 table; every id and status matches exactly, no id present on one side only. The other eight assigned modules were walked endpoint-by-endpoint. Role lists for all 24 endpoints in the partition checked line-by-line against §4 and §2.1 and match.

### Pass 2 (models/tests/tanklots/serializers) — 23 edits: 3 mismatch-revisions, 20 ambiguity-pins
No `cp` run; edited in place with 23 Edit calls. 531 lines / 123,132 chars → 531 / 129,838. All in-paragraph; no new lines, no new sections.

- §2.4 — insert — ambiguity — every declared field is always present on a response, unset/cleared fields as explicit JSON `null`, never omitted — serializers.py:26
- §2.8 pos. 4 — revise — mismatch — the "field whose presence is an error" example was `base_model_id` on a non-private-label model, which is actually a position-16 `ERR_PRIVATE_LABEL_BASE_INVALID`; replaced with the real position-4 cases (`brand_label`, `holiday_count`, `adhesion_class`) and stated the `base_model_id` exception explicitly — routes/models.py:59-81, routes/tanklots.py:279-291
- §3.2 — insert — ambiguity — the two `brand_label` shape rules are schema-level `ERR_INVALID_REQUEST`, not `ERR_PRIVATE_LABEL_BASE_INVALID`, and precede base resolution — routes/models.py:56-64
- §3.2 — insert — ambiguity — withdrawal's `reason_code` is required non-empty and discarded (no model reason field) — routes/models.py:173
- §3.2 — insert — ambiguity — suspension's `reason_code` likewise required and not persisted — routes/models.py:197
- §3.2 — insert — ambiguity — accrued/paid start at 0; `warranty_reserve_balance_cents` is not stored but derived per read as accrued − paid — serializers.py:224-228, routes/models.py:102
- §3.4 — revise — ambiguity — `WITHDRAWN` is the *only* release posture blocking weld; `DRAFT`/`RESTRICTED` weld normally — routes/tanklots.py:107
- §3.4 — insert — ambiguity — `holidays_per_tank` renders as a plain JSON number, so exactly 0.5000 comes back as `0.5` — serializers.py:12-15, services/calc.py:33
- §3.4 — insert — ambiguity — the three `scrap_quantity` rules run *after* body resolution, version pin, state, SoD and sample adequacy; a sample-short failing filing reports `ERR_SAMPLE_SIZE_INSUFFICIENT` — routes/tanklots.py:295,320-335
- §3.4 — insert — ambiguity — `sample_size` has no schema upper bound, so it may exceed `planned_quantity` — routes/tanklots.py:274
- §3.4 — insert — ambiguity — reline authorisation tests the rework ceiling before the wip test, and never consults `cascade_rejected` — routes/tanklots.py:141-146
- §3.4 — insert — ambiguity — scrapping leaves `last_scrap_quantity` as-is; reversal/scrap `reason_code` validated then discarded — routes/tanklots.py:158,189,192-194
- §3.4 — insert — ambiguity — `foam_density_kg_m3` and `foam_thickness_mm` carry no declared ranges; the 40 mm floor is the only bound — routes/tanklots.py:204-205
- §3.5 — insert — ambiguity — body FKs resolve `product_model_id` before `test_cell_id` — routes/tests.py:48-49
- §3.5 — revise — mismatch — "non-terminal … must stay within `parallel_slots`" → overlapping tests still `SCHEDULED` must be **strictly less than** `parallel_slots` — routes/tests.py:52-59
- §3.5 — insert — ambiguity — cooldown reference is the latest same-cell/same-model window ending at or before `window_start`, counted regardless of `status`; a gap exactly equal to `cooldown_hours` passes — routes/tests.py:62-73
- §3.5 — insert — ambiguity — `measured_value` is unbounded, so a zero/negative reading is admitted and simply fails the margin test — routes/tests.py:128
- §3.6 — revise — ambiguity — `effective_date` is non-optional; the supplied instant is validated then discarded — routes/tests.py:269,281
- §3.6 — insert — ambiguity — approving against an already-`DECERTIFIED` model publishes nothing and does not bump the model's `version`, though the certificate still becomes `APPROVED` and supersedes prior approvals — routes/tests.py:297-303
- §3.6 — revise — mismatch — rejection returns only an `UNCERTIFIED` model to `TEST_PENDING`; `TEST_PENDING`/`CERTIFIED`/`SUSPENDED`/`DECERTIFIED` are untouched. Also pinned that `uef_test_count` and `submitted_by_user_id` survive rejection — routes/tests.py:321-329
- §3.6 — insert — ambiguity — a `REVOKED` certificate retains its own certified values and `label_serial_prefix`; revocation carries no SoD check — routes/tests.py:333-347
- §3.8 — insert — ambiguity — empty-string `production_period` counts as omitted; no `YYYY-MM` format check; an unmatched period yields an all-zero report — routes/models.py:210-215
- §3.8 — insert — ambiguity — `EXPOSURE_WEIGHTED` divides by the *rounded* two-decimal `weighted_exposure_unit_months` — routes/models.py:242-245

Zero-edit modules: none. serializers.py's remaining 11 projections matched PRD prose field-for-field, including the inspection record's absent `updated_at`/`version`. Verified as already uniquely pinned: model creation defaults and dual state dimensions, withdrawal fan-out ordering, lift-restriction gating, the UEF five-step floor and flat rating floors, the round-then-mean certification order, cert supersession sets, the four-hop revocation cascade's single model `version` bump, the four-hop lining-failure cascade, lot release ledger settlement, and every list filter set.

### Pass 3 (units/warranty/recalls/calc/core) — 19 edits: 2 mismatch-revisions, 17 ambiguity-pins
No `cp` run; 20 Edit calls (19 distinct changes; one was a wording refinement of another). 531 lines / 129,838 chars → 531 / 133,992 (+4,154). No new sections, no new paragraphs.

- §2.6 Precision — revise — mismatch — "truncated toward zero (floored)" was wrong for months in service: impl floors toward negative infinity, so a clock moved back before `shipped_at` yields a *negative* month count rather than 0 — services/calc.py:210-215
- §2.6 Precision — insert — ambiguity — every decimal-scaled field is rendered as a plain JSON number, so declared trailing zeros are lost (`85.00`→`85.0`, `coverage_pct` `1.00`→`1.0`, `hardness_factor` `0.80`→`0.8`, `80.00`→`80.0`) — services/calc.py:33-39
- §3.2 Catalogue (`RESTRICTED`) — revise — mismatch — "never entered by a client request … only ever the third hop of a cascade" was untrue: the restriction rule runs at exactly four sites (cascade-1 hop 3, cascade-2 hop 3, recall announcement, disassembly of a `HELD` unit), and hold release stamps the model without applying it — services/core.py:78-80, routes/units.py:295, routes/recalls.py:153
- §3.7 Staging — insert — ambiguity — body FKs resolve `tank_lot_id` → `safety_valve_lot_id` → `gas_control_lot_id`, so several missing rows report `ERR_TANK_LOT_NOT_FOUND` — routes/units.py:56-60
- §3.7 Staging — revise — ambiguity — the capacity count is the lot's `unit_count` (excludes `SCRAPPED`), so a disassembly frees a slot — routes/units.py:78-84
- §3.7 Shipment — insert — ambiguity — `install_water_hardness_gpg` carries **no** declared range (unlike a claim's 0.0–60.0), so negative/extreme readings are admitted and band as `SOFT`/`VERY_HARD` — routes/units.py:211
- §3.7 Release-hold — insert — ambiguity — only lot `status` is re-read; supplier standing and `qualified_until` are never re-examined, so `ERR_QUALIFICATION_EXPIRED` cannot arise here — routes/units.py:254-265
- §3.7 Disassembly — revise — ambiguity — the held-unit recomputation applies the restriction rule (a still-`RELEASED` model with another held unit moves to `RESTRICTED`), and `held_from_status`/`label_status` are left as the hold set them — routes/units.py:288-296
- §3.8 Reversal — insert — ambiguity — `coverage_pct`/`approved_payout_cents` survive a payment reversal — routes/warranty.py:163-166
- §3.8 Claim states — revise — ambiguity — denying a claim that is not `OPEN` also reports `ERR_INVALID_CLAIM_STATE` — routes/warranty.py:118
- §3.9 Campaign creation — revise — ambiguity — `campaign_code` is non-empty and at most 20 characters (length was unstated) — routes/recalls.py:36
- §3.9 Scoping — insert — ambiguity — `ERR_RECALL_SCOPE_EMPTY` leaves the campaign untouched: ranges back to null, `version` unmoved — routes/recalls.py:102-105
- §3.9 Announcement — insert — ambiguity — the fan-out population is re-resolved live from the stored serial range, not replayed from the scoping snapshot, so `affected_unit_count` may not equal the units visited — routes/recalls.py:130
- §3.9 Announcement — revise — ambiguity — only units moved to `HELD` get a `version` bump; a `SHIPPED` unit receiving a notice is not mutated — routes/recalls.py:133-149
- §3.9 Notice lifecycle — insert — ambiguity — the campaign-liveness check precedes the notice's own state, so a terminal notice under a closed campaign reports `ERR_INVALID_CAMPAIGN_STATE` — routes/recalls.py:222-227
- §3.9 Notify — insert — ambiguity — notify is the one notice action that leaves the campaign row alone (no `version` bump) — routes/recalls.py:259-262
- §3.9 Remedy — revise — ambiguity — every accepted remedy bumps the campaign's `version`, not only the first one that moves it to `IN_REMEDY` — routes/recalls.py:279-281
- §3.9 Mark-unreachable — insert — ambiguity — the campaign's `version` increments alongside the notice's — routes/recalls.py:300
- §3.9 Completion read — insert — ambiguity — a never-scoped campaign reports `affected_unit_count` as null with the population-based pct at 0.00 — routes/recalls.py:201-213
- §3.9 Closure — insert — ambiguity — the held-unit gate re-resolves the population live at closing time — routes/recalls.py:171-173

Zero-edit modules: none of the five was fully silent. services/core.py produced only the §3.2 reconciliation — `resolve`/`rows`/`require_unique`, `hold_unit`, all three cascades (supplier disqualification hops 1–3, certification revocation hops 1–4, lining-failure hops 2–4) and `recall_population` were walked, and §3.1/§3.6/§3.4/§3.9 already pinned each uniquely (including the exactly-once model `version` bump in the revocation cascade and the cascade-termination rule). Likewise most of calc.py (supplier score/band, sample size, holiday density, R-value, UEF five-step floor, certified `mean_of_rounded`, hardness bands, coverage tiers, three-line payout, remedy banding, `failure_rate_ppm`, `completion_pct`) was already exact.

Closing consistency check (pass 3): passed. The new §2.6 rendering note agrees with §3.4's `holidays_per_tank` note; "floored toward negative infinity" agrees with §3.7's "truncated downward"; the `unit_count` pin agrees with §3.4's definition; the release-hold pin agrees with §2.8 positions 11/27 (hold release absent from 27); the disassembly restriction pin is reconciled with §3.2 line 229 rather than contradicting it; no other passage bounds `install_water_hardness_gpg` to 0–60; the three campaign-`version` statements (notify/remedy/unreachable) are mutually consistent; and §3.7's "recall announcement holds from `LABELED`" is not contradicted by §3.9's "`ASSEMBLED` or `LABELED`" because an `ASSEMBLED` unit can never hold a serial number and so never enters the population.

## PIPELINE COMPLETE — 2026-09-05T06:35:00.000Z

All 9 steps done. Final state: 85/85 endpoints, 260 test functions (281 collected including parametrisation), 281/281 passing in all 8 rounds of the final stability sweep, `workspace/PRD_COMPLETED.md` written.
