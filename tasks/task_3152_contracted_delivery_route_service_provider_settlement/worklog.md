## Step 1: Create Task Directory — 2026-09-30T05:08:41.397241554Z

Task directory `tasks/task_3152_contracted_delivery_route_service_provider_settlement/` was pre-allocated by the caller (index 3152, label `contracted_delivery_route_service_provider_settlement`) with an empty `workspace/` inside. No new index computed and no other `task_*` directory created, per the invocation instruction. Verified: directory exists, `workspace/` present and empty.

## Step 2: Generate Scaffold — 2026-09-30T05:49:23.134495791Z

All three artifacts are complete and the lint verifier reports `VERDICT: clean lint`. Final state:

## Deliverables

- `SCAFFOLD.yaml` — §1.0–§1.7
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Counts

| Metric | Count |
|---|---|
| Entities | **15** |
| State machines | **7** (39 transitions) |
| Calculation rules | **9** |
| Validation rules | **29** |
| API endpoints | **105** |
| Error codes | **29** |
| RBAC roles | **6** |
| Concurrency rules (§1.2.1) | **3** |
| §1.8 difficulty instances | **18** (9 rules × 2) |
| §1.9 corner instances | **36** (32 active + 4 `excluded_because` stubs) |

## Design summary

Scenario kept verbatim. Profile: **Ledger reconciliation** primary, **Multi-party negotiation** secondary; layers = optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers.

Role model is **delegated_authority**: `ServiceProvider` is `entity_backed:ServiceProvider` (owns its titles, files its own disputes, subject to ownership checks), the other five are `opaque`.

Difficulty-rule grounding (both instances of each rule sit on different entity domains / error pairs / metrics, per §0.5):
- **dual_variant_calc** — settlement exoneration (provisional 5400 vs reconciled 3400 on identical accrual window) and provider composite weight-shift (95.00 vs 88.00)
- **combinatorial_formula** — mode (a)+(b) tier cliff (cliff rate on all stops; 22000 → 25025) and mode (c) pinned evaluation order
- **non_linear_state_machine** — `RouteAssignment` re-enterable `ACTIVE↔PENDING_TRANSFER` cycle plus length-1 self-loop; `ServiceProvider` `APPROVED↔UNDER_REVIEW` cycle plus guard-driven self-loop
- **transitive_cascade** — depth-3 provider→assignment→area chain and depth-2 agreement→assignment chain, hops spelled out as `HOP 1/2/3`
- **priority_pair_validation_conflict** — existence-vs-referential and state-vs-safety
- **boundary_precision_check** — stop tier/capacity numbers and empty-collection denominators
- **cross_entity_state_dependency** — `(RouteAssignment, Agreement)` and `(RouteAssignment, ServiceProvider)`
- **resource_temporal_overlap** — half-open abutment permitted on area occupancy vs inclusive 1-minute guard buffer on driver duty
- **compensating_invariant** — cents conservation on chargeback offset and zero-assessment count invariant

The logical clock defaults to `2026-09-01T00:00:00Z` (documented on the clock endpoint, no wall-clock fallback). All 29 error codes are either validation-driven or grounded by a corner instance; all 201 `grounds:` references resolve; placeholder closure is complete across all 716 design-file calls; no `id` participates in any ordering or tie-break.

## Notes / caveats

- Two mechanical hiccups during authoring left transient states that I repaired (a validation-row renumbering pass that briefly duplicated a priority, and a section-consolidation pass that dropped the `scaffold_corner_design:` key line). Both are fixed and verified — every check above re-ran clean afterward.
- A few corner asserts deliberately reference a *contrasting* reading (e.g. "at exactly N the same call succeeds") that is established by setup state rather than by a second executed call; these are phrased as boundary comparisons, not as second invocations. If the downstream unit-test-generator wants them as two literal invocations, the §1.5 surface already supports it without changes.
- I did not build `workspace/PRD.md`, tests, or an implementation — the task scoped only the three scaffold artifacts.

## Step 3: Copy Shared Files — 2026-09-30T05:49:26.860010996Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes) via bash, no subagent.

## Step 4: Generate PRD — 2026-09-30T05:59:12.519763365Z

PRD generated and audited. Report follows.

## Deliverable

`workspace/PRD.md`

- **462 lines**, ~13,690 words
- **32 headings total**: 1 title, 5 H2 (Introduction, Global Specifications, Business Logic, Endpoint Definitions, Error Code Catalogue), 24 H3 (12 in §2, 12 in §3), 2 H4 (the fixed §2.2 sub-blocks)
- **§4 table**: 105 endpoint rows (matches scaffold endpoint count exactly), 4 columns (Method, Path, Description, Authorized Role(s))
- **§5 table**: 29 error rows (matches scaffold error count exactly), 2 columns (Error ID, HTTP Status Code)

## Section structure (domain-derived, not templated)

§2 subsections: 2.1 RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 The Ledger Principle and Conserved Money · 2.5 Route Titles, Service Areas and Occupancy Intervals · 2.6 Fleet, Roster and Coverage Compliance · 2.7 Asset Tiers, Guard Buffers and Surge Windows · 2.8 Common Resource Properties · 2.9 Nested Resource Retrieval and Validation Order · 2.10 Precision, Rounding and Monetary Representation · 2.11 Optimistic Concurrency Control · 2.12 The Logical Clock.

§3 subsections: 3.1 Provider registration/fleet-roster · 3.2 Territories/asset eligibility/insurance · 3.3 Agreement negotiation & renewal cycle · 3.4 Acquiring & activating a route title · 3.5 Selling a route + outstanding-balance gate · 3.6 Peak-season surge · 3.7 Week opening, accrual, gross settlement · 3.8 Deductions, segment cap, multiplier · 3.9 Performance measurement & renewal · 3.10 Charge-backs and recovery · 3.11 Disputes and payout release · 3.12 Operational support/cross-references.

## Deliberately scattered or withheld from prose

- **Path/method information withheld from §3 entirely**: all 105 URL paths and every HTTP method live only in §4. §3 refers to endpoints solely via state-transition framing (`DRAFT → ACTIVE`, `FILED → APPROVED → SETTLED`), role+gerund ("approval by an `AccountManager`"), or capability description ("a `PlatformAdmin`-only test-driving capability advances the logical clock"). Verified mechanically: 703 backticked tokens in §3, zero starting with `/`, zero bare methods, zero method+path.
- **Trigger conditions withheld from §5**: the error table carries only ID + status; every trigger is stated next to the rule it guards in §2/§3.
- **Request/response bodies and side effects withheld from §4**: omitted from the table by design so the reader must reconstruct payloads and effects from §3 narrative.
- **Scattered across subsection boundaries** (by design): the OCC rules (three guarded writes split across 2.11, 3.4, 3.5); the deduction-cap waterfall and its `deduction_order`/`allow_over_cap` switches (3.8, with the post happens in 3.7); the multiplier's exempt-symbol branch and momentum floor (3.7/3.8); the chargeback escalation test split across approval-time and reconcile-time readings (3.10); the two renewal-reading variants (3.9); cascades attached to their trigger rather than listed centrally (3.1, 3.3, 3.5, 3.6, 3.9, 3.11).
- **Constants embedded in business context**: tier increment expressed as "3 cents"/"6 cents" with the 1000/2500/4000 stop bounds, the 50000-cent cap as "50000 cents", the brand/pct thresholds as decimals, rather than dumped as a constants table.
- **Weight constants (`PERF_WEIGHT` 0.5, `SAFETY_WEIGHT` 0.3, `CX_WEIGHT` 0.2, `SERVICE_WEIGHT` 0.5)**: stated as prose weights ("five tenths", "three tenths", "two tenths") under all three weight regimes, not as named symbols. This is the one intentional non-naming: the scaffold's own `# §1.3.1` pinning instruction directs that weight constants be pinned as prose weights across regimes, not recited as identifier lists.

## Coverage audit (all PASS)

- **Contract 1 field-name coverage** — entity fields 82/82 present, body/input ids 70/70, path params 1/1, 0 missing. Enum values 62/62 present.
- **Contract 2 rule coverage** — all 29 error IDs named in §2/§3 (the ten not-yet-cited 404/409 codes were added as an explicit left-to-right resolution mapping in §2.9, plus a terminal-state list); 39/39 state transitions present as from→to pairs; 9/9 calculations expressed (named where the scaffold's own prose path names them, otherwise fully described); all 9 OCC-bearing calculation variants and all 12 role/identity translations present; all 14 state-machine sibling groups and 9 calculation variant groups rendered with equal density.
- **Contract 3 §3 path purity** — scanned 703 backticked tokens in §3: 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos.
- **§2.2** is byte-identical to `section-2.2-response-structure.md` (verified by diff; backticks include `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }`; no synthesized entity payload).
- No fuzzy/approximating words; no pseudocode operators; no trailing whitespace; no scaffold/skill metadata leaked into prose.

## Rules the PRD could not state verbatim

None were dropped, but two naming caveats worth flagging for the test generator:

1. **Calculation algorithm names** are not all recited as identifiers. `owned_vehicle_count_reconciliation`, `owned_driver_count_reconciliation`, `gross_settlement_calculation`, `chargeback_net_recovery`, `deduction_segment_cap` and `provider_renewal_recommendation` are named verbatim (because the scaffold's own §1.1/§1.2 side-effect prose names them); `provider_composite_score`, `settlement_performance_multiplier` and `driver_qualification_compliance` are described fully in prose but the identifiers themselves do not appear. A test keyed on those three identifier strings would not find them; a test keyed on their behavior will.
2. **`SettlementDeduction.performance_factor_eligible`'s `false` buckets, the `FUEL` pre-multiplier timing, and the `CHARGEBACK` post-multiplier treatment are stated in prose but must be read across §3.7 and §3.8 together** — by design for the scattering requirement, but the implementer will need both subsections.

Also worth noting: the `§1.2.1` concurrency rules reference `expected_service_area_version` for the transfer-approval endpoint, and the request-body mapping in the scaffold's own read-endpoint metadata is present, but the create-assignment and create-period OCC fields are stated in §2.11 and §3.4/3.7 rather than duplicated at each endpoint row in §4 (which carries no request bodies by contract).

## Step 5: Generate Unit Tests — 2026-09-30T06:24:56.853861828Z

Generation complete. Summary below.

## Deliverables

**7 test files, 83 tests** in `test_suite/`, plus 9 modules in `test_helpers/`. No test is untagged, dual-tagged, or points at a nonexistent instance; the four `excluded_because:` stubs are correctly left untranslated. All 133 embedded PRD citations pass a literal grep of `PRD.md`; no `skip`/`skipif`/`xfail` appears anywhere.

Per-file counts: `test_01_combinatorial_formula` 10, `test_02_state_machine_cycles` 16, `test_03_compensating_invariant` 7, `test_04_dual_variant_reconciliation` 4, `test_10_provider_lifecycle` 10, `test_11_calculations_and_errors` 22, `test_12_rbac_and_cross_cutting` 14.

## `test_helpers/` structure

`types.py` (entity TypedDicts + status enums, with `common_fields: false` entities — StopObservation/SettlementDeduction/Dispute — omitting `updated_at`/`version`), `api_client.py` (117 endpoint methods against `/route-settlement`, `_request`-based), `api_errors.py` (29 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity + append-only + domain invariants), `factories.py` (one payload factory per entity, input fields only), `constants.py` (all named PRD thresholds), `test_users.py` (six roles; `make_service_provider_headers()` per-instance builder for the entity-backed role), `fixtures.py` (composite tiers + a `run_scenario` record-driven executor that replays a design-index `test_recipe` with `${var}` interpolation and `$.a.b` captures), `__init__.py` (barrel export). Verified importable and `pytest --collect-only` clean.

## Queue A (difficulty) — 18 instances, all covered at ≥2 tests

Translated: `tiered_stop_rate_cliff_boundary`, `late_accrual_recut_evaluation_order`, `nonexistent_area_precedes_occupied_area`, `terminal_agreement_precedes_branding_gate`, `stop_tier_and_capacity_boundaries`, `route_title_transfer_negotiation_cycle`, `provider_compliance_posture_review_cycle`, `suspension_three_hop_area_release_chain`, `insurance_expiry_two_hop_release_chain`, `assignment_activation_requires_active_agreement`, `transfer_approval_requires_approved_acquirer`, `area_occupancy_abutting_titles`, `driver_duty_guard_buffer`, `claim_rejection_leaves_assessment_zero`, `empty_roster_and_branding_denominator_boundaries`, and both `dual_variant_calc` instances. `release_chargeback_offset_conservation` is covered via PRD §2.4's own conservation identities (the index's own literal "offset 85000" is not printed in the PRD; equality/conservation statements are).

## Instances skipped — PRD-first filter reasons

- **`dual_variant_calc/settlement_exoneration_late_accrual_divergence`** — skipped (translated to different assertions). Its `grounds` cite `validations[priority=21]` asserting a reconcile-time insurance re-evaluation, but PRD §3.8's reconcile prose names only the tiered re-run, re-cap and late-accrual re-bucket — no insurance re-read. The 5400→3400 / 2000-cent figure additionally depends on the composite weight selector at `UNDER_REVIEW` (§3.9 lists the safety-emphasized weights as an *alternative* reading, so the exact 1.10 multiplier is not uniquely derivable). Generated two PRD-grounded tests (provisional write on close; reconcile replaces net) tagged to the instance.
- **`dual_variant_calc/provider_composite_weight_shift_divergence`** — partial skip. The ≥2 tests assert the PRD-unique band outcomes (<50.00 → UNDER_REVIEW; <65.00 → SUSPENDED); the specific literals 95.00 / 88.00 / 7.00-point spread are not derivable because which weight set applies is not uniquely fixed by §3.9 prose.
- **`combinatorial_formula/tiered_stop_rate_cliff_boundary`** (assert line 4) — the "separate week… capped_deduction_cents of exactly 50000" sub-scenario omitted; `DEDUCTION_CAP_EXCEEDED`'s enumeration is stated only in PRD §5, and §3.8 describes the over-cap bypass without naming the residue flag a caller sets. `deductions_above_cap_require_over_cap_flag` is likewise present only as a queue-B tag, not a filterable A instance.
- **`transitive_cascade/insurance_expiry_two_hop_release_chain`** — hop-2 partial. The trigger is not fully derivable: §3.3 gives expiring an agreement an explicit `now >= renewal_due_at` gate, while §2.9 forbids expiry against a terminal resource and §3.3 limits termination to `RE_NEGOTIATION`. The renegotiate/sign-refused-with-`ERR_INSURANCE_INSUFFICIENT` path (which the PRD does uniquely determine) is asserted instead.
- **`combinatorial_formula/late_accrual_recut_evaluation_order`** — exact net 33600 and the `ACCESSORIAL_FIRST` switch not asserted; both depend on the RE_NEGOTIATION/peak-week reversal rule and on `deduction_order` naming, which the PRD does not commit at the precision the recipe needs. Degenerate-expiry, late-accrual and ambiguous cases were left as gaps rather than weakened.

## Queue B (corner) — 32 non-stub instances, 31 covered at ≥1 test

One skip: **`entities/provider_creation_missing_tax_id_returns_invalid_request`** — no verbatim PRD sentence states that omitting a field yields `ERR_INVALID_REQUEST` (the only such rule, §3.3 agreement submission, is about floors, not missing fields; §2.9's "missing-or-invalid-request" clause is scoped to dangling foreign keys). `composite_score_rounding_precision` was retagged to `Corner/calculations/…` (it is a queue-B instance) and also carries complete PRD coverage.

Note: tests run against `PRD.md` prose only — no implementation was read or generated, and no sibling `task_*` directory was accessed.

## Step 6: Generate Implementation — 2026-09-30T06:56:40.765402135Z

The implementation is complete and verified.

## Summary

Built a complete Python + Flask implementation at `workspace/implementation/`.

### Files and line counts

| File | Lines | Role |
|---|---|---|
| `start.sh` | 11 | executable launcher |
| `requirements.txt` | 1 | `Flask>=2.0` |
| `app.py` | 52 | entry point, error handlers, blueprint registration |
| `db.py` | 132 | in-memory store, logical clock, ISO-8601 helpers |
| `errors.py` | 102 | all 30 error ids + HTTP statuses |
| `response.py` | 107 | envelope + pagination helpers |
| `middleware.py` | 213 | auth gates, role decorator, field validators |
| `calculations.py` | 583 | the nine §1.3 calculations |
| `services.py` | 730 | state machines, cascades, business gates |
| `routes.py` | 1516 | all 105 endpoints |
| **total** | **3447** | |

### Endpoint count
**105 method+path operations** across 90 distinct paths — an exact set-equality match against `SCAFFOLD.yaml §1.5` after normalizing `{id}` to the Flask converter form. 79 are GET, 26 POST; no duplicates.

### start.sh (PORT / 0.0.0.0 / foreground)
`start.sh` cds to its own directory, guards the dependency install behind `if ! python3 -c "import flask"` (so the per-test-server reboots don't re-run pip concurrently), then `exec python3 app.py` — `exec` replaces the shell so signals propagate and the script never exits while the server runs. `app.py` reads `int(os.environ.get("PORT", "10000"))` and calls `app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)`. Verified: 8 concurrent boots from `start.sh` all became HTTP-ready (8/8) with no pip contention.

### Verification performed
Wrote two black-box suites (61 assertion groups) driven through fresh `start.sh` boots on isolated ports, exercising auth gates, OCC, all state machines, cascades, both waterfall orders, both multiplier variants, recovery escalation, budget limits, pagination, and 404 ordering. Both pass. Storage is in-memory only: `app.py`/`db.py` contain no seeding, no `seed_*()`, and no module-level `db.*` writes.

### PRD rules that were ambiguous or under-determined

1. **`adjustment_provisional_variant` vs. the reconcile balance precondition.** The close-accrual variant is described as using the "performance-adjusted deduction bundle", yet reconcile is refused unless `base_gross - net == Σ non-CHARGEBACK deductions`. Resolving the metrics-driven multiplier at close makes that identity unsatisfiable. I resolved it by resolving the multiplier **only at reconcile**, leaving the close to use the field's declared default (1.00). Consequence: the §3.7 sentence "a week exempted from the multiplier returns a higher net at close" is not observable at close time in this reading; the exemption takes effect at reconcile.

2. **"Two deduction segments" vs. four deduction types.** PRD §3.7 says "the pre-multiplier bundle is MAINTENANCE plus the ACCESSORIAL deduction segment", but §3.8 and priority 26 speak of "summed non-CHARGEBACK segments" exceeding the cap, which would also include FUEL. I followed §3.7 (FUEL is post-multiplier and uncapped) and applied the cap gate to MAINTENANCE+ACCESSORIAL only, keeping priority 26's "two deduction calls drive the cap" literally true.

3. **`allow_over_cap` semantics.** Whether it merely bypasses the reject gate or also disables the waterfall fill is not stated. I made it bypass only the gate, so the waterfall still fills to 50000 — otherwise the MAINTENANCE-first / maintenance-deferred variants could never be observed on any period, since any over-cap week would be refused without the flag.

4. **`allow_over_cap` default and `deduction_order` trigger.** Both default to false/absent; I inferred `deduction_order` accepts `"forward"`/`"reversed"` (unspecified vocabulary) and otherwise auto-selects reversed when the governing agreement is `RE_NEGOTIATION` or the week is a peak week, per the `maintenance_deferred` variant.

5. **Reference period for the primary version.** I used PRD §2's startup terminal `2026-09-01T00:00:00Z` for `created_at`, the optimistic-concurrency comparison, the accrual window, `renewal_due_at` and `expires_at`.

6. **`provider_type := SUCCESSOR` on transfer approval** appears only in the SCAFFOLD endpoint table, not in PRD prose. Implemented, since PRD is silent rather than contradictory.

7. **Insurance gate with no `AUTO_LIABILITY` row.** PRD §3.1's wording is a universal ("every AUTO_LIABILITY policy ... is VERIFIED"), which a provider with no policy satisfies vacuously; the SCAFFOLD error condition instead implies a coverage floor. I followed the PRD (vacuous pass), noting the alternative reading would fail such providers.

## Step 7: Run Tests and Iterate — 2026-09-30T07:59:55.216301352Z

All 8 rounds clean (83/83 each). Final verification confirms the contract holds.

## Summary

**Iterations run:** 7 fix-and-verify single rounds → final **8-round parallel stability sweep: 8/8 rounds × 83/83 passed, zero failures in the union.**

**Tests deleted: 0.** No test was removed. Every failure was either a `test_helpers` fixture bug, a test artifact that contradicted a verbatim PRD sentence, or an implementation gap against a verbatim PRD rule.

### `test_helpers/` fixes
- `fixtures.py::run_call_chain` — **path `${var}` never interpolated** (only payloads were). Record-driven recipes sent the literal string `${pol_a_id}` as a path id, so `POST /insurance-policies/${pol_a_id}/verify` hit `ERR_INVALID_REQUEST`. Single highest-impact bug; fixed the whole record-driven class.
- `fixtures.py::setup_provider_compliance` — added `approve=True` kwarg so a test can drive the approval transition itself and observe the role gate.
- `fixtures.py::setup_two_approved_providers_after_transfer` (new) — reaches `PENDING_TRANSFER` via the real `POST /route-assignments/{id}/request-transfer` endpoint. The old fixture handed tests a title with no recorded occupancy/cancel-applicability, so the "abutting is permitted / overlap is refused" pair had no live start instant and false-passed/false-failed.

### `test_suite/` fixes (test-side, PRD-faithfulness)
- 5 module-level helpers called the `api` pytest fixture out of scope (`NameError`): `_expiring_policy_provider`, `_empty_roster_provider`, `_reconciled_week_with_two_claims`, `_accrual_closed_week_with_capped_segments`, `_fleet_with_two_owned_and_one_temporary` — switched to the module-level `api_client`.
- Temporary-asset fixtures (`test_03`, `test_12`) omitted the covering `ACTIVE` `PeakSeasonDeclaration` that PRD §2.7/§3.6 requires, so the setup itself was refused.
- `test_insurance_floor_above_coverage_blocks_title_acquisition` — its precondition (an `ACTIVE` agreement whose floor exceeds the provider's coverage) is one PRD §3.3 forbids ever existing, since signature gates on the same floor; replaced with the other half of the same §3.4 sentence (coverage lapsed past `expires_at`).
- `test_vehicle_registration_rejects_a_dangling_area_reference` — asserted `ERR_INVALID_REQUEST`; PRD §2.9's identifier-to-error mapping pins `ERR_SERVICE_AREA_NOT_FOUND`.
- `test_dispute_filed_one_day_inside_the_window_is_accepted` — used the boundary instant itself (2026-12-13 = `week_start_at`+7+90), which PRD §3.11 refuses "at or after"; moved to 2026-12-12.
- `test_terminated_governing_agreement_beats_branding_gate` — asserted `ERR_INVALID_STATE`; the cascade terminates the title, and PRD §2.9 states the already-terminal check precedes the legality check. Renamed/reasserted `ERR_ALREADY_TERMINAL`.
- `test_third_counter_offer_on_one_dispute_is_refused` — a dropped `validate_error()` call.
- `test_expired_insurance_blocks_renewal_signature_at_the_insufficient_gate` — renegotiation from `ACTIVE` is legal only inside the 30-day window; the fixture clock (2026-10-02) was well outside it. Certificate re-dated short and the clock moved to the renewal boundary; added the §3.3 renegotiate→resubmit→sign chain.
- `test_stale_area_version_refuses_transfer_approval` / `test_fresh_area_version_after_mutation_is_accepted` — the fixtures could not reach the gate under test (stale path short-circuited at 412 before the state check; fresh path hit `ERR_TEMPORAL_OVERLAP` first). Now mutate the area directly and assert only the OCC outcome.

### `implementation/` fixes
- `routes.py` — the three nested list endpoints (`stop-observations`, `deductions`, `disputes`) omitted `limit/offset/total_count/has_more`; PRD §2.3 states every list endpoint carries them.
- `routes.py::compose_metric` — the safety cascade writes `safety_index` onto the provider but never bumped its `version`; PRD §2.8 makes any modification a version increment.
- `services.py` — dispute counter allowed only one offer (`> 1`) where PRD §3.11 permits two, and the re-file back-edge was budget-gated where PRD gives it no budget precondition; agreement round budget now counts the renegotiate action and the resubmission against the shared three-round allowance.
- `services.py::assignment_approve_transfer` — double `touch` on the transferring title and an extra one on the area; PRD §3.5 pins one title bump and two area bumps.
- `services.py::occupancy_interval` — a recorded end preceding the effective date (zero-length span) was still treated as live to infinity, making every later candidate on the area an unconditional `ERR_TEMPORAL_OVERLAP`.
- `calculations.py` — `segment_order` rejected the PRD §3.8-named maintenance-first order; the cap waterfall skipped filling when `allow_over_cap` was set, leaving `capped_deduction_cents` at the raw 60000 rather than the 50000 cap of §3.7; `capped_deduction_cents` was reported pre-multiplier.

No skips/xfails; no persistence (in-memory dicts only, verified); endpoint count unchanged at 105/105; no seeding.

**One ambiguity worth flagging to the generator:** PRD §3.8 defines the deduction-cap waterfall (which segment absorbs the cap) but never states what `allow_over_cap` does to that waterfall. Two PRD-faithful readings exist — bypass the cap entirely (segments stand as posted, 60000) or waive only the refusal while the cap still fills (50000). The `deductions_above_cap_require_over_cap_flag` corner instance asserts the second and I implemented it, but PRD says only "the cap is bypassed."

## Step 8: Finalize PRD — 2026-09-30T09:21:20.825835014Z

All edits are applied, implementation files remain untouched (mtimes unchanged), and PRD_FINALIZED.md is exactly 462 lines — a 0% line-count delta from PRD.md (8 lines modified in place, no lines added or removed).

## PRD.md vs PRD_FINALIZED.md
- PRD.md: 462 lines. PRD_FINALIZED.md: 462 lines. **0.0% delta** (8 lines revised in place).

## Changes (one bullet per edit)

- **§2.5 Route Titles / Occupancy** — insert — a title whose recorded `occupancy_ends_at` precedes its own `effective_date` leaves no span and contributes no interval to the overlap test — `implementation/services.py:137-141` (`occupancy_interval`)
- **§3.3 Agreement renewal cycle** — revise — the second `ERR_NEGOTIATION_ROUND_LIMIT` budget is a *shared 6-unit negotiation allowance* consumed by ACTIVE renegotiation and by DRAFT/`RE_NEGOTIATION` submission; signature resets it to zero; renegotiation from `PENDING_REVIEW` tests but does not consume it — `implementation/services.py:49,452-453,468,481,488`
- **§3.5 Selling a Route** — revise — on transfer approval the area's `version` and the transferring title's `version` **each advance once** (the successor's creation no longer bumps the area a second time) — `implementation/services.py:374-377`
- **§3.7 Settlement week summary** — insert — `capped_deduction_cents` is the pre-multiplier bundle *after* the multiplier is applied and rounded once; `uncapped_deduction_cents` is never scaled — `implementation/calculations.py:279,297`
- **§3.8 Deduction cap** — revise — `allow_over_cap` waives only the `ERR_DEDUCTION_CAP_EXCEEDED` refusal; the capped segments are still filled through the waterfall to 50000 — `implementation/services.py:630,636`; `implementation/calculations.py:323-374`
- **§3.8 Deduction order** — insert — `deduction_order` accepts `MAINTENANCE_FIRST`/`forward` and `ACCESSORIAL_FIRST`/`reversed`; any other value → `ERR_INVALID_REQUEST` 400; omitted falls back to the agreement/peak-week default — `implementation/calculations.py:313-315`; `implementation/routes.py:1047-1049`
- **§3.9 Composition / safety cascade** — revise — `version`/`updated_at` are bumped on every composition path *except* the plain APPROVED→UNDER_REVIEW demotion, which flips status in place without bumping — `implementation/routes.py:1146-1157`
- **§3.11 Dispute cycle** — revise — the re-file back-edge (`COUNTERED`→`EVIDENCE_SUBMITTED`) carries no precondition beyond state; it neither tests nor consumes the counter budget, so the counter is the sole consumer — `implementation/services.py:750-754`

## Per-edit pre-edit search log (a/b/c)

1. **§2.5 occupancy** — (a) occupancy interval derivation. (b) `occupancy_interval` 127-141, `require_no_overlap` 144-161, callers `create_route_assignment` routes.py:342 & `assignment_activate` services.py:301; writers of `occupancy_ends_at_dt` at provider_suspend:271, assignment_terminate:325, approve_transfer:371, agreement_expire:512. (c) none — single consumer.
2. **§3.3 budget** — (a) renegotiation round budget. (b) `RENEGOTIATION_ROUND_BUDGET` 49, `require_round_budget` 487-489, `agreement_submit` 440-456, `agreement_renegotiate` 473-484, `agreement_sign` reset 468; route readers `submit/renegotiate/negotiation-rounds`; empirically confirmed DRAFT-submit and ACTIVE-renegotiate each +1, 6th refused, sign resets. (c) softened from "three renegotiation rounds" to a shared six-unit allowance naming each consuming action so neither increment site is excluded.
3. **§3.5 version** — (a) version increments during transfer approval. (b) `assignment_approve_transfer` 359-401; instrumented touch-log = `{RouteAssignment:1, ServiceArea:1, ServiceProvider:1}`; black-box deltas area +1/title +1; all other area-mutation paths bump once. (c) reworded to "each advance by one" and dropped the false second-area-bump clause.
4. **§3.7 summary** — (a) summary's `capped_deduction_cents`. (b) `summary_breakdown` 285-300, `compute_gross_settlement` 253-282, `deduction_bundles` 239-250, route 1019-1028; tests pin the post-multiplier reading (test_11:157,501). (c) framed against both bundle members to match the shared `gross_fee`/`post` semantics.
5. **§3.8 allow_over_cap** — (a) `allow_over_cap` effect. (b) `period_reconcile` gate 630 + call 636, `apply_deduction_segment_cap` 323-374 (ignores flag, always fills), `deduction_bundles`, route 1040-1051. (c) replaced "cap is bypassed" with "refusal is waived; waterfall still caps" — matches every path.
6. **§3.8 deduction_order** — (a) accepted `deduction_order` values. (b) route 1047-1049, `period_reconcile` 613-616, `segment_order` 307-320; empirically `BOGUS`→400, `ACCESSORIAL_FIRST`→accepted. (c) named tokens plus explicit fallback so the default branch is not excluded.
7. **§3.9 compose** — (a) provider `version`/`updated_at` on composition. (b) `compose_metric` 1135-1158, `provider_suspend` 263-285; touch-log = `{PerformanceMetric:1}` only for APPROVED&<50; probed APPROVED/UNDER_REVIEW/SUSPENDED and no-demotion branches. (c) replaced "in every demotion the provider advances its version" with a universal claim plus the single documented exception.
8. **§3.11 dispute re-file** — (a) re-file budget. (b) `dispute_resubmit` 750-754 (no budget/increment), `dispute_counter` 733-747, routes 1244-1271. (c) reworded from "gated by the same round budget" to "no precondition; sole consumer is the counter".

## Items in `<step_7_diff>` deliberately NOT edited
- `routes.py` nested-list pagination (the three list endpoints now carry `limit/offset/total_count/has_more`): PRD §2.3 already states every list endpoint carries them — impl now matches, no silence/mismatch to pin.
- `test_helpers/*` and `test_suite/*` fixes (path interpolation, out-of-scope fixture, temporary-asset declaration, dispute-window boundary, dangling-area error id, already-terminal cascade, dropped `validate_error`, stale/fresh area version): these are test-side bugs/PRD-faithful reassertions, not PRD silence or PRD-mismatch, so no PRD edit traces to them.
- One residual undocumented behavior was observed but left unedited because it is consistent with existing PRD text and was not a Step 7 fix: `routes.py:593` `/agreements/{id}/negotiation-rounds` raises `AttributeError` on `svc.RENEGOTIATION_ROUND_LIMIT` (constant is named `RENEGOTIATION_ROUND_BUDGET`) — a latent endpoint bug, not a behavioral choice PRD leaves open.

Key finding worth flagging: three genuine **PRD-vs-impl divergences** (not merely silences) were corrected to match implementation — §3.5 transfer-approval area double-bump, §3.8 over-cap bypass, and §3.9 "every demotion bumps version" — plus the §3.11 re-file budget precondition.

## Step 8b: Orchestrator-side latent bug fix — 2026-09-30T09:21:32.368446275Z

Step 8's subagent flagged a latent defect it deliberately did not patch (out of Step 8's scope): `workspace/implementation/routes.py:593` referenced `svc.RENEGOTIATION_ROUND_LIMIT`, but `services.py:49` defines the constant as `RENEGOTIATION_ROUND_BUDGET`. The orchestrator reproduced it against a live server booted on an isolated port:

- Repro: POST /route-settlement/service-providers (201) -> POST /route-settlement/service-areas (201) -> POST /route-settlement/agreements (201) -> GET /route-settlement/agreements/{id}/negotiation-rounds
- Observed: HTTP 400 `ERR_INVALID_REQUEST` ("the request could not be processed"), server stderr `AttributeError: module 'services' has no attribute 'RENEGOTIATION_ROUND_LIMIT'. Did you mean: 'ERR_NEGOTIATION_ROUND_LIMIT'?`
- PRD_FINALIZED.md line 189 states verbatim: "The negotiation rounds consumed are exposed by a computed read that reports the agreement's `agreement_id`, its `rounds_used`, its `rounds_remaining` and its `renewal_due_at`" — and §4 line 360 declares the GET endpoint. The unfixed route could never return the PRD-required `rounds_remaining`.

Fix: `routes.py:593` — `svc.RENEGOTIATION_ROUND_LIMIT` -> `svc.RENEGOTIATION_ROUND_BUDGET` (one token; no behavior added beyond the PRD-declared field).

Post-fix verification on a fresh boot: GET returns HTTP 200 with `{"agreement_id": ..., "renewal_date_at": null, "rounds_remaining": 6, "rounds_used": 0}`, and zero tracebacks in server stderr. `rounds_remaining: 6` is consistent with the §3.3 shared 6-unit allowance priced in PRD_FINALIZED.md.

The Step 7 test suite never exercised this route, which is why the 83/83 sweep did not catch it. The full 8-round stability sweep was re-run after the fix: **8/8 rounds x 83/83 passed, zero failures** — no regression.

## Step 9: Complete PRD — 2026-09-30T10:07:18.920720537Z

Done. All 22 pins are applied to `PRD_COMPLETED.md` only.

## Result

**File:** `workspace/PRD_COMPLETED.md`
- Source `PRD_FINALIZED.md`: 462 lines / 99,204 chars → `PRD_COMPLETED.md`: 462 lines / 103,169 chars (**+3,965 chars**, char-delta +4.0%)
- 21 lines changed (21 removed / 21 replaced), each an **in-paragraph insert or revision**. No new sections, no new paragraphs.

**Counts:** 8 ambiguity-pins, 15 mismatch-revisions (22 pinned sites across the 21 lines; E11 below carries one of each). Re-verified Step 8's 8 sites without reopening them; §3.3's shared-6-unit allowance prose is consistent with `RENEGOTIATION_ROUND_BUDGET` / `rounds_remaining = 6 - rounds_used`.

### Ambiguity-pins (PRD silent)
- §2.6 — insert — ambiguity — an auto-liability invariant over an empty policy set passes vacuously — `services.py:67-78`
- §2.3 — insert — ambiguity — rows sharing an identical `created_at` fall back to `id` ascending as the final tie-break — `middleware.py:188`
- §2.11 — insert — ambiguity — names the three fields exactly (`expected_service_area_version` ×2, `expected_provider_version` ×1); omitted/non-int value rejected as stale — `routes.py:86-98,336,425,887`
- §3.2 — insert — ambiguity — duty-shift read returns an object `{driver_id, shifts[]}` sorted by `starts_at`, not a paginated array — `routes.py:803-810`
- §3.7 — insert — ambiguity — summary read recomputes base gross/net and therefore advances the week's `version`/`updated_at` — `routes.py:1019-1028`
- §3.7 — insert — ambiguity — close-accrual does not resolve the multiplier; it scales by the stored `performance_multiplier` (still 1.00), tier table applied only at reconcile — `calculations.py:253-269`
- §3.11 — insert — ambiguity — `expires_at` is recorded only; not enforced on evidence/counter/escalate, does not force closure — `routes.py:1244-1283`
- §2.5 — insert — ambiguity — re-archiving an `ARCHIVED` area → `ERR_ALREADY_TERMINAL` — `routes.py:247`

### Mismatch-revisions (PRD described a different behavior)
- §3.7 — revise — mismatch — "index selected by date and read into the week" replaced: the week records the **request-supplied** `fuel_rate_cents_per_mile`; `FuelIndexRate` rows are never consulted — `routes.py:883,895` (no `FuelIndexRate` read anywhere)
- §3.8 — revise — mismatch — cap gate tests only eligible `MAINTENANCE`+`ACCESSORIAL`; `FUEL` (and ineligible rows) excluded, so large FUEL never refused — `services.py:628-631`
- §3.8 — revise — mismatch — balance identity pinned to `base_gross − net == Σ(FUEL+MAINTENANCE+ACCESSORIAL)` after a refresh with the stored multiplier — `services.py:622-626`
- §3.10 — revise — mismatch — approval posts deduction, recomputes **branding only**; "pre-charge-back service area score" removed (no such derivation) — `services.py:696-711`
- §3.10 — revise — mismatch — rejection "restores the pre-charge-back service area score" replaced with: posts no deduction, leaves outstanding/branding untouched — `services.py:723-726`
- §3.4 — revise — mismatch — signature "strict variant" counts failures only on `qualification_status`/`CLASS_C`, **not** on `SUSPENDED`/`TERMINATED` status (unlike the reaffirm derivation) — `services.py:428-433` vs `calculations.py:511-521`
- §3.4 — revise — mismatch — reaffirm also blocks a qualified `CLASS_C` driver — `services.py:428-433`
- §3.5 — revise — mismatch ×2 — non-`APPROVED` acquirer → `ERR_INVALID_STATE` (409) at request and at approval — `services.py:345,363`
- §3.4 — revise — mismatch — suspended-provider activation refusal → `ERR_INVALID_STATE` (409) — `services.py:303`
- §3.4 — revise — mismatch — terminate while area has a `DISPUTED` week → `ERR_INVALID_STATE` (409) — `services.py:322`
- §2.5 — revise — mismatch — new assignment to `ARCHIVED` area → `ERR_INVALID_STATE` (409) — `routes.py:338-339`
- §3.3 — revise — mismatch — amend outside window → `ERR_NEGOTIATION_ROUND_LIMIT`; expire before due → `ERR_INVALID_STATE` — `services.py:494,504`
- §3.10 — revise — mismatch — claim-approval gates (week status, EQUIPMENT vehicle mismatched/absent, missing `recorded_at`) all → `ERR_INVALID_STATE` (409) — `services.py:684,688,693`
- §3.12 — revise — mismatch — "these reads are read-only" scoped to the reverse lookups it enumerates (the §3.7 summary computed read is the exception) — `routes.py:1027`

### Verified as already consistent (no change)
Transfer approval does not re-evaluate the overlap gate (`services.assignment_approve_transfer` only calls `require_area_free`), matching §3.5's omission; `renewal_due_at`/`expires_at`/close-gate/accrual-window reference-period clauses; `deduction_order` vocabulary + default trigger; transfer-approval `SUCCESSOR` + widened branding denominator; posting a `CHARGEBACK` deduction shapes.

