# Worklog — task_2134_hospital_nutrition_room_service

## Step 1: Create task directory — 2026-08-22T10:30:33.163Z

Created `tasks/task_2134_hospital_nutrition_room_service/` and `tasks/task_2134_hospital_nutrition_room_service/workspace/`.

## Step 3: Copy shared files — 2026-08-22T10:31:10.000Z

Copied `INSTRUCTION.md` -> `tasks/task_2134_hospital_nutrition_room_service/workspace/INSTRUCTION.md` (run early; independent of Step 2).

## Step 2: Generate scaffold — 2026-08-22T11:27:00.000Z

All three scaffold artifacts are generated and lint-clean.

**Files written to `/home/ubuntu/github/CodingPRD/tasks/task_2134_hospital_nutrition_room_service/`**
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts**
| Item | Count |
|---|---|
| Entities | 12 |
| State machines | 9 tables over 8 entities (MealOrder carries two parallel dimensions) |
| Concurrency rules (OCC) | 2 |
| Calculations | 10 |
| Validations | 41 (single global priority ladder) |
| Endpoints | 65 |
| Errors | 51 |
| Roles | 5 (all `opaque`) |
| §1.8 difficulty instances | 20 across all 9 rule_ids (2–3 each) |
| §1.9 corner instances | 75 across all 9 sections — 60 executable + 15 `excluded_because` stubs |

**Difficulty calibration (beyond-Expert)**
- Archetype `compliance_audit` + `temporal_windowing`; topology `graph` (self-referential DietOrder supersede chain, cross-aggregate refs); shape `parallel`; role model `segregation_of_duties`.
- Rule 1: dual-variant on two different domains — `malnutrition_risk_score` (SCREENING 71.00/HIGH vs COMPREHENSIVE 52.50/MODERATE on identical inputs) and `production_forecast_trays` (ROLLING_AVERAGE 20 vs CENSUS_BASED 3 on the same ward/date).
- Rule 2: all three modes present — (a) 5-input `effective_diet_envelope` with a non-monotonic NPO_CLEAR_LIQUIDS branch that pins liquid *down* to THIN; (b) per-line-then-sum rounding (741 vs the rejected 740); (c) circular-looking `meal_period_cost_rollup` with tier keyed on the step-1 subtotal (2039 vs the rejected 1947).
- Rule 3: cyclic DietOrder revision loop (bounded by MAX_REVISION_ROUNDS 3) + parallel `fulfillment_status × qa_status` on MealOrder.
- Rule 4: 5-level cascade from ProcedureHold activation (NPO → MISSED trays → slot/cents release + rollup → missed-meal counters + auto URGENT consult → ward census) and a 4-level cascade from DietOrder cosign (activate → supersede → re-pin/revert trays → slot release + rollup).
- Rule 5: `business_safety` vs `business_fiscal` (allergen beats tray capacity) and `state` vs `business_temporal` (period CLOSED beats cutoff passed).
- Rule 6: hot probe `>= 60.0` (59.9 fails / 60.0 passes) and zero-cardinality `lines: []`, on different endpoints.
- Rule 7: three distinct entity pairs — MealOrder<->DietOrder, SupplementOrder<->NutritionConsult, MealOrder<->ProcedureHold.
- Rule 8: buffered **half-open** ProcedureHold intervals on Patient (touching allowed) vs unbuffered **closed** MealPeriod windows on Ward (touching rejected).
- Rule 9: slot-count conservation (`committed_tray_count`, validate/cancel) vs monetary-ledger conservation (`Patient.daily_supplement_cost_cents`, activate/cancel, 780 -> 260).

**Verification performed**
- `scaffold_lint.py` verdict (pasted verbatim):
```
Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     12
  §1.8 instances scanned:     20
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  791

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
- Every formula-derived assertion literal was computed with Python `Decimal`/ROUND_HALF_UP (741, 1340, 1728/311/2039, 146, 211, 216/39/255, 281, 367, 708, 71.00, 52.50, 46.00, 70.00, 4.33, -66.67, scores 65/75/85/90/100).
- Custom checks passed: zero duplicate instance names across both design files, zero unresolved `grounds`, zero unbound `${var}` in payloads/paths/asserts, every `excluded_because.difficulty_instance` resolves to a real §1.8 name, no forbidden concurrency vocabulary, and neither design key appears in `SCAFFOLD.yaml`.
- No sibling task directory was read at any point; the scaffold derives only from the scenario text and the skill spec.

One deliberate call-out: a logical-clock endpoint `POST /_clock/set_current_utc` is declared with the mandated startup default `2026-08-01T00:00:00Z`, and all fixture dates sit on 2026-08-02 so every cutoff/window/SLA assertion is run-time independent.

## Step 4: Generate PRD — 2026-08-22T11:40:00.000Z

PRD generated at `workspace/PRD.md` — **457 lines**, ending at §5 with no audit footer. The two design-index files were never opened.

**Structure:** §1 Introduction (3 paragraphs) · §2 with 10 subsections (RBAC, verbatim response envelope, pagination, identity/audit/logical clock, the 41-step validation ladder, OCC, cascades and ledger symmetry, nested addressing, precision, segregation of duties) · §3 with 9 domain-derived subsections (wards/patients, rule catalogue and menu, diet-order lifecycle, effective envelope, meal periods and cost rollup, tray placement/substitution/validation, tray line and QA, procedure holds and missed-meal escalation, consults/supplements/satisfaction) · §4 4-column endpoint table · §5 2-column error table.

**Coverage confirmation** (all verified mechanically against SCAFFOLD.yaml):

```
Field coverage check:
- entities[].fields: 144 required, 144 present, 0 missing
- endpoints[].request_body: 78 required, 78 present, 0 missing
- endpoints[].query_params: 25 required, 25 present, 0 missing
- endpoints[].path_params: 2 required (id, line_id), 2 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 41 checked, 41 expressed in prose (§2.5 ladder is explicitly ordered; each condition restated beside the workflow it guards), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_diet_order_version / expected_consult_version + ERR_STALE_DIET_ORDER_VERSION / ERR_STALE_CONSULT_VERSION + HTTP 412 all named), 0 missing
- state_machines[].transitions: 9 machines / 38 transitions checked, 38 fully expressed with from/to, preconditions and every side-effect level, 0 missing
- calculations[]: 10 checked, 10 fully expressed in prose with all constants embedded in business context (waste factor 1.08, texture surcharges, tier boundaries 2000/6000 cents, overhead 18/15/12%, discount 0/2/4.5%, 1150 cents per tray, 0.92 / 0.85, history depth 3, 60.0/4.0 Celsius, penalties 25/10/15/20, weights, tiers 30/60, threshold 2, SLA 4h/24h, 3 revision rounds, 15.0 g clear-liquid cap), pinned evaluation orders stated, 0 missing
- validations[] conditions: 41 checked, 41 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 65 endpoints checked, all applies_to scopes enumerated in full, 0 missing
- entities[].fields[] structured content: 144 checked, defaults / initial values / null semantics / enum members reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups checked (submit fork, cancel-from-4-states, MISSED-from-4-states, accuracy retry cycle, temperature retry cycle, consult cancel from 3 states, supplement cancel PENDING vs ACTIVE), 7 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 905
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All 5 roles named with exact spelling and their `identity: opaque` translated into §2.1 prose; all 51 error IDs appear in §2/§3 narrative as well as the §5 table; §2.2 matches the canonical block byte-for-byte; §4 has 65 rows, §5 has 51 rows.

Orchestrator verification: `grep` confirms §4 (67 table lines incl. header/sep) and §5 (53 table lines incl. header/sep) both present and terminal — no doc-generator truncation.

## Step 6: Generate implementation — 2026-08-22T12:05:00.000Z

The implementation is complete and verified.

**Location:** `workspace/implementation/`

**Module layout** (20 files, no single oversized write; all built from INSTRUCTION.md + SCAFFOLD.yaml + PRD.md only — test_helpers/, test_suite/ and the two design YAMLs were never opened):

| File | Role |
|---|---|
| `start.sh` | Guarded dep install (`if ! python3 -c "import flask"`), `exec python3 app.py` |
| `requirements.txt` | `Flask>=2.2` |
| `app.py` | Blueprint registration (14 blueprints), ApiError/HTTPException handlers, `0.0.0.0:$PORT` |
| `errors.py` | All 51 catalogue error ids -> HTTP statuses (+2 fallbacks for unrouted paths) |
| `store.py` | In-memory dicts (12 collections), logical UTC clock (epoch `2026-08-01T00:00:00Z`), id/timestamp/version helpers, per-type not-found resolvers |
| `api.py` | `meta`/`response_type`/`data` envelope, `error_id`/`message`, `limit`/`offset`/`total_count`/`has_more`, `X-User-ID`/`X-User-Role` auth + RBAC decorator, body/query validators |
| `calcs.py` | All 10 calculations with pinned evaluation orders, `Decimal` + `ROUND_HALF_UP` everywhere |
| `domain.py` | Envelope resolution, tray recomputation, period ledger, missed-meal escalation, activation/supersede cascade |
| `serialize.py` | Per-entity representations (surveys carry `id`+`created_at` only) |
| `routes/` (12 files) | clock, wards, patients, catalog (rules+menu), diet_orders, meal_periods, meal_orders, tray_line, lines, holds, consults (+supplements), surveys |

**Endpoints: 65 registered** — exactly matching the scaffold's declared count (verified by enumerating `url_map`).

**Verification:** three HTTP smoke suites (~145 assertions) all pass with 0 failures against a live server, covering: the 41-step validation ladder ordering (role outranks existence; allergen -> texture -> liquid -> tag -> discontinued), envelope layering + both NPO overrides, per-line cost rounding then summing, the six-step period rollup across all three tier boundaries, ledger symmetry (validate -> cancel returns the period to exact pre-reservation values), the supersede cascade with re-pinning onto the post-bump version, procedure-hold voiding + auto `SYSTEM`/`URGENT` consult escalation at 2 missed meals, period-close and discharge cascades, both forecast variants incl. the empty-history fallback and null zero-denominator variance, both risk-score variants, SoD on all three pairings, OCC on both creation endpoints, the full 12-entry not-found catalogue, and pagination bounds.

**Startup:** `bash start.sh` boots from a fresh process, binds `0.0.0.0:$PORT` (default 10000) in the foreground via `exec`, responds in ~1s, and the store is confirmed empty on every boot — nothing is seeded, preloaded, or persisted to disk.

## Step 5: Generate unit tests — 2026-08-22T12:20:00.000Z

Test infrastructure and suite are complete and verified.

## Files written

**`test_helpers/`** (2,150 lines, 9 files)
- `types.py` — 20 status enums + 12 entity TypedDicts. `SatisfactionSurvey` correctly carries only `id`/`created_at` (no `updated_at`, no `version`) per PRD §2.4.
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per PRD endpoint (65 endpoints + the logical clock).
- `api_errors.py` — all 51 `ApiErrorId` members + status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions, `assert_period_cost_rollup`, `assert_risk_tier_matches_score`, and `assert_instant_equals` (parses instants rather than string-matching, so timestamp formatting is not over-constrained).
- `factories.py` — payload factories plus a reusable menu/diet-rule catalogue (`SOU-BRO`, `SID-RIC`, `SUP-ORS`, `DES-PUD`, `ENT-CHK`, `SID-PNB`; `REGULAR_STD`, `RENAL_2G_NA`, `CARB_MOD`).
- `constants.py`, `test_users.py` (opaque per-identifier builders for the segregation-of-duties tests), `fixtures.py` (5 tiers, incl. `setup_tray_scenario` / `setup_validated_tray` / `setup_plated_tray` / `setup_temp_passed_tray` / `setup_delivered_tray` / `setup_assessed_consult` / `setup_signed_consult`), `__init__.py` barrel.

**`test_suite/`** (4,202 lines) — `conftest.py` + 10 domain-named modules, `test_01_…` through `test_10_…`.

## Counts

- **100 tests**, all collected cleanly by pytest.
- **Queue A (difficulty): 20/20 instances translated**, 2 tests each = 40 tests.
- **Queue B (corner): 60/60 non-stub instances translated**, 1 test each = 60 tests.
- **0 instances skipped.** Every instance passed the PRD-first two-condition filter — this PRD verbatim-covers every rule the indices assert.
- The 15 `excluded_because:` corner stubs were **not** translated; all 15 `difficulty_instance` cross-references were verified to resolve to real names in the difficulty index.

## Verification performed

- **Citation audit (scripted):** every docstring quote of >=20 chars survives a whitespace-normalised literal match against `workspace/PRD.md` — 0 non-verbatim quotes, 0 tests without a quote.
- **Design-tag audit (scripted):** exactly one `Design:` line per test, always the final docstring line, every tag resolving to a real instance — 0 untagged, 0 dual-tagged, 0 orphan tags, 0 stub translations.
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no "scaffold"/table references leaked into generated code.
- `python -m compileall` clean; AST undefined-name sweep clean (two hits were `AnnAssign` false positives).

## Assertions deliberately relaxed under the two-reader rule

Three index assertions were dropped rather than weakened elsewhere, all for unique-derivability:

1. `MealOrder.effective_texture_level == PUREED` **at creation time** (`tray_cost_rounds_per_line_before_summing`) — the PRD pins that field's refresh only at validate and re-pin, so a faithful reader could leave it unset at creation while still costing correctly. The distinguishing assertion (741 vs. the rejected 740) is kept.
2. Literal timestamp strings such as `"2026-08-02T09:00:00.000Z"` — asserted as *instants* via `assert_instant_equals`; the PRD pins three-fractional-digit formatting for `created_at`/`updated_at` only, not for `effective_from` / `released_at` / `delivered_at`.
3. `pinned_diet_order_version == <literal captured at cosign>` in the supersede cascade — asserted instead as equality to the successor's live `version`, since the PRD does not pin whether the re-pin writes the value before or after the cascade's final version bump (equality to the live version is the only reading under which the re-pinned tray can revalidate at all).

## Step 7: Run tests and iterate — 2026-08-22T12:40:00.000Z

All 8 parallel rounds now pass 100/100.

## Summary

**Iterations run:** 2 (each an 8-round parallel stability sweep, 100 tests × per-test server restart).

**Iteration 1 result:** 95/100 in all 8 rounds — 5 deterministic failures (identical in every round, no flakiness observed).

**Root cause (single upstream bug, 4 of the 5 failures):** PRD §3.6 states that placing a tray "increments the pinned diet order's `linked_meal_order_count` by 1 and therefore that diet order's `version` by 1", while validation requires "the tray's `pinned_diet_order_version` must still equal that diet order's current `version`, else `ERR_DIET_ORDER_SUPERSEDED`". Together these mean two trays pinned to the same diet order can only both validate if each is validated *before* the next is placed. Four test setups placed both trays first and then validated, so the first tray was correctly rejected with `ERR_DIET_ORDER_SUPERSEDED`. This was a test-setup bug (STEP 2: setup state does not satisfy a PRD precondition), not an implementation bug — the implementation check is PRD-required and was left untouched.

**Tests deleted:** none. No test failed the STEP 1a coverage check or the STEP 1b unique-derivability check outright.

**Assertion removed (STEP 1c partial coverage):**
- `test_suite/test_10_concurrency_and_reconciliation.py` — `test_every_accepted_tray_advances_the_linked_count_and_the_version`: dropped `assert second_tray["pinned_diet_order_version"] == version_after_first_tray`. **Pattern: computed-field silence / ordering silence.** PRD says only that `pinned_diet_order_version` is "stamped with the diet order's `version` at the instant of pinning" and never states whether that instant precedes or follows the creation's own linked-count version bump; both readings are PRD-faithful, so the concrete integer is not uniquely derivable. (Scaffold rule that drove it: `Corner/cross_cutting_layers/diet_order_version_and_linked_count_advance_on_every_accepted_tray`, whose index asserts the pre-bump value.) The test's other four assertions — `linked_meal_order_count == 2`, `version == v+1` on both placements, and `total_count == 2` — are verbatim-covered and were kept.

**Fixes applied to `test_suite/` (setup ordering, all three make the setup *more* faithful to PRD §3.6):**
- `test_06_tray_line_qa_and_delivery.py` — `test_delivery_before_the_window_is_early_and_at_window_end_is_late`: validate the lunch tray before placing the dinner tray.
- `test_07_procedure_holds_and_missed_meals.py` — `_two_validated_trays_under_a_covering_hold()` (shared by `test_activation_voids_every_covered_tray_and_moves_patient_counters` and `test_voided_trays_release_their_ledgers_and_raise_one_urgent_consult`): same interleaving.
- `test_08_consults_supplements_and_surveys.py` — `_two_delivered_trays_for_one_patient()` (used by `test_patient_average_rounds_half_up_over_already_rounded_composites`): same interleaving, plating/QA/delivery left unchanged.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:** none. No implementation defect was found; no PRD-required check was removed or weakened, and no endpoint, field, or side effect was added.

Orchestrator verification: all 8 `results.{1..8}.json` re-read independently — each reports `passed == total == 100`.

## Step 8: Finalize PRD — 2026-08-22T12:47:00.000Z

`PRD_FINALIZED.md` is written. One edit total.

**Line counts:** PRD.md 457 lines -> PRD_FINALIZED.md 457 lines (0.0% line delta; one sentence extended in place on §3.6, line 263).

**Changes:**
- §3.6 (tray placement, "An accepted tray is stored with…") — revise — pinned the stamping instant of `pinned_diet_order_version`: it is now stated to fall *after* the creation's own `linked_meal_order_count`/`version` bump, so an accepted tray pins the post-increment `version` — `implementation/routes/meal_orders.py:126-128` (`diet_order["linked_meal_order_count"] += 1; store.touch(diet_order); order["pinned_diet_order_version"] = diet_order["version"]`, which overwrites the provisional pre-bump value set at `routes/meal_orders.py:81`).

**Pre-edit search log (edit 1):**
- (a) Subject: what integer `pinned_diet_order_version` holds, and every place that field or `linked_meal_order_count` is written or compared.
- (b) Paths enumerated (grep for `pinned_diet_order_version|linked_meal_order_count`, `store.meal_orders[`, `store.touch(diet_order|new_order|predecessor)` across `implementation/`, then read):
  - `routes/meal_orders.py:37-129` — the only meal-order creation path (single `store.meal_orders[...] = order` site); the pin is set twice, the second write is unconditional and post-bump.
  - `routes/meal_orders.py:173` — validation's `pinned_diet_order_version != diet_order["version"] -> ERR_DIET_ORDER_SUPERSEDED`; consistent with post-bump pinning (last-placed tray passes, earlier ones need re-validation before the next placement).
  - `domain.py:230-243` `run_activation_cascade` — the *other* writer of `pinned_diet_order_version` (re-pin onto `new_order["version"]` after that order's own bump) and notably does **not** touch `linked_meal_order_count`; PRD §3.4 (line 208) already covers this path. Wording is explicitly scoped to "the creation's own bump", so the cascade re-pin is not described or constrained by it.
  - `routes/diet_orders.py:79` — `linked_meal_order_count: 0` at draft; `store.store.touch` sites at `diet_orders.py:33/131/135/158/191` (cosign, revision, discontinue) bump `version` without touching the count — unaffected by the new clause, which speaks only about the placement bump.
  - `store.py:102-117` (`stamp_new`, `touch`) — confirms `touch` bumps `version` by exactly 1 and is the sole bump mechanism.
  - `serialize.py:113,171` — both fields are echoed verbatim, no derivation at serialization time.
- (c) Wording adjustment: scoped the clause to "the creation's own `linked_meal_order_count` bump" and to "an accepted tray" rather than making a universal claim about the field, so the activation-cascade re-pin (`domain.py:238`) and the non-placement version bumps in `routes/diet_orders.py` remain correctly described by the existing §3.4/§2.6 prose.

**Items requiring no PRD edit:** the three `test_suite/` setup-ordering fixes (`test_06`, `test_07`, `test_08`) were fixture bugs against an already-PRD-determined precondition, and no `implementation/` or `test_helpers/` fixes or test deletions were reported — so nothing else in `<step_7_diff>` traced to PRD silence or mismatch.

## Step 9: Complete PRD — 2026-08-22T12:56:00.000Z

Patch complete and verified.

## Result

`workspace/PRD_COMPLETED.md` written from `PRD_FINALIZED.md` with 26 in-paragraph edits. No sections added, no paragraphs added, no table rows changed.

**Integrity check:** §1–§5 all present; §4 endpoint table = **65 rows**; §5 error table = **51 rows**.

**Size:** 457 lines -> 457 lines (identical); 93,569 -> 98,029 chars (**+4,460**).

**Counts:** 23 ambiguity-pins, 3 mismatch-revisions.

### Changes

- §2.1 — insert — ambiguity — an empty (not merely absent) `X-User-ID`/`X-User-Role` also yields `ERR_UNAUTHENTICATED` — `api.py:85`
- §2.3 — insert — ambiguity — rows sharing a `created_at` (common under the frozen logical clock) tie-break on server insertion order — `store.py:273-275`
- §3.1 — revise — **mismatch** — `temperature_probe_required` gates nothing; the TEMP_PASSED delivery precondition applies to every tray on every ward. `delivery_lead_minutes` likewise descriptive only — `routes/tray_line.py:125` (flag unreferenced anywhere)
- §3.1 — insert — ambiguity — ward PATCH: requesting the status already held is `ERR_INVALID_STATE`; no other field revisable; a no-field PATCH still bumps `version`; wards filter by `status` — `routes/wards.py:73-96`
- §3.1 — insert — ambiguity — patient PATCH accepted whatever the admission status; bumps `version` even when it names no field — `routes/patients.py:173-189`
- §3.2 — insert — ambiguity — diet-rule PATCH: no-op status is `ERR_INVALID_STATE`; ceilings/floors not revisable; rules filter by `status` — `routes/catalog.py:61-86`
- §3.2 — insert — ambiguity — menu-item PATCH: only `status` and `unit_cost_cents` revisable; no-op status is `ERR_INVALID_STATE`; items filter by `status`, `texture_level`, `service_temp_class` — `routes/catalog.py:133-164`
- §3.3 — insert — ambiguity — a DRAFT order's five scalar `effective_*` fields read null and `forbidden_tag_codes_effective` reads `[]` until first submission — `routes/diet_orders.py:74-78`
- §3.3 — revise — **mismatch** — resubmission from `REVISION_REQUESTED` never takes the auto-activate fork; it always lands in `PENDING_COSIGN` (the §4 table row implied otherwise) — `routes/diet_orders.py:127-131`
- §3.3 — insert — ambiguity — `revision_note` is required, not optional — `routes/diet_orders.py:146`
- §3.3 — insert — ambiguity — supersede cascade level two also refreshes each re-pinned tray's `effective_texture_level`/`effective_liquid_level`, leaving totals and costs untouched — `domain.py:241-242`
- §3.4 — insert — ambiguity — an `ACTIVE` order recomputes all six envelope fields live on every read; any other status reports the frozen snapshot — `domain.py:36-54`
- §3.5 — insert — ambiguity — window-overlap compares every period on the ward whatever its `status`, `CLOSED` included — `routes/meal_periods.py:45-51`
- §3.5 — insert — ambiguity — meal periods filter by `ward_id`, `period_code`, `service_date`, `status` — `routes/meal_periods.py:80-90`
- §3.5 — insert — ambiguity — period close bumps the patient's `version` once per missed tray, not once per close — `domain.py:176-177`
- §3.6 — insert — ambiguity — a fresh tray copies `effective_texture_level`/`effective_liquid_level` from the pinned order's envelope at creation (this is what the creation-time surcharge keys on) — `routes/meal_orders.py:76,86-87`
- §3.6 — insert — ambiguity — a cost pass at creation or validation writes `line_cost_cents` in place without bumping the line's `version`/`updated_at` — `domain.py:73-77`
- §3.6 — insert — ambiguity — substitution is gated by the safety battery alone (any tray fulfillment state, any patient/period/diet-order status); omitted `substitution_reason` writes null; response body is the line, not the tray — `routes/lines.py:184-232`
- §3.6 — revise — ambiguity — substitution texture/thickness floors read the tray's own stored `effective_*`, while the tag test reads the pinned order's live `forbidden_tag_codes_effective` — `routes/lines.py:207-219`
- §3.6 — insert — ambiguity — the five safety checks are applied check-major: each runs across every line before the next begins, so a higher check on any line outranks a lower check on another — `routes/meal_orders.py:183-210`
- §3.7 — insert — ambiguity — all three start-production failures (not `VALIDATED`, period not `IN_SERVICE`, revalidation pending) report `ERR_INVALID_STATE` in that order — `routes/tray_line.py:20-28`
- §3.7 — insert — ambiguity — `observed_line_count` is a mandatory integer >= 0; `defect_codes` defaults to empty — `routes/tray_line.py:50-51`
- §3.7 — revise — **mismatch** — probe readings are stored rounded half up to 1 dp (not required at 1 dp on input), stored even for a probe the tray does not require, and compared as supplied — `routes/tray_line.py:100-105`
- §3.8 — insert — ambiguity — a second concurrently `ACTIVE` hold reports `ERR_INVALID_STATE` — `routes/holds.py:100-104`
- §3.9 — insert — ambiguity — `recommended_supplement_item_id`, when supplied, must resolve (`ERR_MENU_ITEM_NOT_FOUND`) but need not be `ACTIVE` — `routes/consults.py:88-91`
- §5 — insert — ambiguity — two non-catalogue identifiers: `ERR_NOT_FOUND` (404) for unrouted paths, `ERR_METHOD_NOT_ALLOWED` (405) for a routed path with an unaccepted method — `errors.py:56-57`, `app.py:124-133`

### Verified as already uniquely pinned (no change)
Envelope five-step resolution and NPO override; tray cost line-then-sum order; six-step period rollup and tier banding; both forecast variants and the empty-history fallback; variance null-on-zero-denominator; risk scoring and both weight sets; satisfaction composite and the round-then-average order; every ladder position exercised by the routes (creation ordering, validation ordering, hold booking, supplement activation); half-open vs closed interval readings; ledger symmetry on cancel/miss/supersede; survey immutability; and the filter sets for patients, diet orders, meal orders, lines, holds, consults, supplement orders and surveys.
