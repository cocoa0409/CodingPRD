# Worklog — task_2789_demand_planning_sales_and_operations_planning

## Step 1: Create task directory — 2026-09-04T21:33:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2789_demand_planning_sales_and_operations_planning` and its `workspace/` subdirectory. Path was pre-assigned by the caller (index fixed by scenario number 2789); no index auto-allocation performed.

## Step 2: Generate scaffold — 2026-09-04T23:17:00.000Z

Scaffold generation for task 2789 is complete and lints clean.

**Output files** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2789_demand_planning_sales_and_operations_planning/`):

| file | lines | top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | 2406 | §1.0–§1.7 only (no difficulty/corner keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1646 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5271 | `scaffold_corner_design` |

**Lint verdict** (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` — 47 endpoints declared, 12 entities, 18 §1.8 instances, 82 §1.9 instances, 1026 calls scanned.

**SCAFFOLD.yaml contents**: domain `demand-planning-sop`, prefix `/sop`, difficulty `expert`. 12 entities, 7 state machines (PlanningCycle, DemandForecast, ConsensusAdjustment, SupplyPlan, Allocation, Scenario, Item lifecycle, Promotion), 12 calculations, 17 validation-priority rungs (10→170), 47 endpoints, 52 errors, 6 roles (SopAdmin, DemandPlanner, DemandReviewLead, SupplyPlanner, ExecutiveSponsor, CustomerRep — the last entity-backed on Customer), 2 concurrency rules. Complexity profile: `workflow_orchestration` primary / `quota_allocation` secondary, layers `[dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers]`, cyclic state machine, `segregation_of_duties`, `immediate` consistency.

**§1.8 difficulty design**: 9 rule ids × 2 instances = 18 — `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

**§1.9 corner design**: all nine claim-extraction sections present — entities 12, state_machines 14, calculations 15 (+2 `excluded_because` stubs), validations 19, endpoints 5, errors 4 (+2 stubs), rbac 8, cross_cutting_complexity_layers 3 (+2 stubs), consistency_model 2 → **82 active instances + 6 excluded stubs**. Every stub's cited difficulty instance was verified to exist by name and none carries a `test_recipe`.

Notes worth carrying forward: the constraint that no sibling task was consulted was honoured throughout; all asserted money/unit literals are pre-computed with ROUND_HALF_UP; and the lint rejects `$.data.total_count` captures on list endpoints, so list-cardinality assertions are stated in prose instead of captured variables.

**Orchestrator verification**: all three YAML files parse; tails end at real structural boundaries; `workspace/` survived Step 2; `grep "harder than expert"` over all three yamls returns nothing and `SCAFFOLD.yaml:scenario` contains only the verbatim scenario text — no difficulty-directive leak to strip.

## Step 3: Copy shared files — 2026-09-04T23:18:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T23:34:00.000Z

PRD generation for task 2789 is complete and verified.

## Deliverable

`workspace/PRD.md` — **502 lines**, written in 7 chunks (1 `Write` + 6 `cat >> … <<'MDEOF'` heredoc appends) per the anti-truncation protocol. `tail` confirms the file ends on the final `§5` error-table row (`| ERR_UNCLOSED_GAP | 422 Unprocessable Entity |`), a real section boundary. No audit footer, no contract-report block inside the PRD.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task directory was read.

## Section list (27 headings, grepped back out of the file)

1 Title; 3 §1 Introduction; 11 §2 Global Specifications; 15 §2.1 RBAC; 34 §2.2 API Response Structure; 36 Success format; 61 Error format; 85 §2.3 Pagination; 93 §2.4 Resource Identity / Immutable Accuracy Ledger; 110 §2.5 Logical Clock & Calendar; 122 §2.6 Numeric Precision & Rounding; 135 §2.7 Optimistic Concurrency on Parent Version; 145 §2.8 Cycle Posture, Phase Gating, Frozen Cycle; 153 §2.9 Rejection Precedence; 179 §2.10 Cascades, Version Bumps, Conserved Quantities; 189 §3 Business Logic; 193 §3.1 Master Data; 207 §3.2 Publishing Capacity; 215 §3.3 Opening a Cycle / Statistical Baseline; 241 §3.4 Promotions & Consensus Adjustment Loop; 275 §3.5 Closing Demand Review / Constraining Supply; 300 §3.6 Rationing Scarce Supply; 324 §3.7 Scenario Planning, Gap Closure, Executive Review; 354 §3.8 Item Lifecycle, Runout, Discontinuation Cascade; 372 §3.9 Forecast Accuracy, Bias Detection, Planner Accountability; 393 §4 Endpoint Definitions (47 endpoints); 447 §5 Error Code Catalogue (52 codes).

§2.2 is the byte-verbatim fixed block from `section-2.2-response-structure.md`. The §3 skeleton is domain-derived (S&OP process timeline), not a copy of the example PRD's skeleton.

## Hard Contract reports

Field coverage: entities[].fields 109/109; write bodies 61/61; GET query params 23/23; path_params 12/12 (6 standalone backticked, 6 only inside §4 path strings per §3 path purity). Status PASS.

Rule coverage: 52/52 error ids in prose (not merely §5 table); 31/31 states; all 37 transitions with guard/actor/side-effects/version bump; 6/6 roles; 12 calc_* + 2 conservation invariants with pinned step order; all 17 validation priority levels (10–170) rendered as §2.9's ordered ladder; both OCC guards (ERR_STALE_FORECAST_VERSION 412, ERR_STALE_CYCLE_VERSION 412); endpoint side_effects/applies_to 0 missing; entity field structured content 0 missing; 5/5 named-constant literal values in prose (z-tiers 2.33/1.96/1.65/1.28/0.84, trade tiers 10.00/20.00/35.00, 25/30/12/2/3, 0.75, 25,000, 5,000,000, 1,000,000, 8.0/6.0/4.0, 5.00, 100.00, 0.00); sibling-branch symmetry 7 forks equal density, 0 asymmetric. Status PASS.

Path purity (§3 only): 921 backtick tokens (263 unique), 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens, 0 occurrences of "/sop". Status PASS.

## Scaffold coverage notes

- **AccuracyRecord** is the one entity with `common_fields: false` — §2.4 states it carries only `id` and `created_at`, has no `updated_at` and no `version`, and is never a target of OCC.
- **Asymmetries called out deliberately**: abutting promotion windows are legal but abutting capacity blocks are not; `lifecycle_state` defaults to `MATURE` on item create even though the entity-level default is `PRELAUNCH`; `SELECTED → SUPERSEDED` removes the scenario's money from the cycle while `SELECTED → EXECUTED` retains it; `PRELAUNCH → RAMP` touches nothing while `PRELAUNCH → CANCELLED_NPI` runs three sweeps; the runout cascade runs three hops in one request; `ERR_UNAUTHORIZED_PHASE_ACTOR` (priority 60) wins over `ERR_CYCLE_PHASE_CLOSED` (priority 110).
- **Rounding discipline** is per-calculation, not global: single-rounding-at-the-end for the baseline, separate lift and cannibalisation roundings, ceil-then-add for the reorder point, six-decimal-then-floor for hours conversion, round-per-line-then-sum for the consensus roll-up, MAPE round-then-average vs WMAPE aggregate-then-round.
- **Rationing** is a two-pass waterfall with largest-remainder distribution and the full tie-break chain (fractional part DESC, then `priority_rank` ASC, then `created_at` ASC), with the explicit statement that `id` is never a tie-break.
- **Gap closure** pins all seven steps in order and pins the trade tier to `pre_trade_closure_cents` only.
- No pseudocode, no operator syntax, no fuzzy language. `NATL-A` and `FAM-SNACK` treated as illustrative labels, not enum members.

**Orchestrator verification**: PRD.md = 502 lines; §1–§5 all present; §5 contains exactly 52 error rows and the file ends on a complete table row (real section boundary) — not truncated. `grep -i "harder than expert|scaffold|test_recipe"` over PRD.md returns nothing.

## Step 6: Generate implementation — 2026-09-05T00:03:00.000Z

The implementation is complete, compiles, boots, and answers requests.

## Modules written (all under `workspace/implementation/`, 3001 lines total)

**Foundation:** `start.sh` (guarded pip install + `exec python3 app.py`), `requirements.txt` (Flask 3.0.3), `app.py` (blueprint registration, `ApiError`/400/404/405/catch-all handlers, `0.0.0.0:$PORT`, no seeding), `util.py` (logical clock pinned at `2026-08-01T00:00:00Z`, ISO-8601 3-digit formatter, Decimal rounding helpers, month/date calendar helpers), `store.py` (12 in-memory dicts, `_seq` tie-breaker, `public()` strips internal `_`-keys), `errors.py` (52-entry error→HTTP catalogue), `envelope.py` (`meta`/`response_type`/`data`, list pagination meta), `validators.py` (ladder step 3), `auth.py` (steps 10/20/60/70/80/100/110), `calcs.py` (all 11 calculations), `cascades.py` (version-bump cascades + both conservation invariants).

**Routes (47 endpoints, exactly matching the PRD §4 table):** `master.py` (11), `capacity.py` (3), `promotions.py` (4), `cycles.py` (5), `forecasts.py` (4), `adjustments.py` (5), `supply.py` (6, incl. allocations), `scenarios.py` (5), `accuracy.py` (3), `clock.py` (1).

## Notable design decisions

- **PHASE_ACTOR vs PHASE_CLOSED** resolved role-ownership-wise (not "has moved past"): if the acting role owns the required phase → `ERR_CYCLE_PHASE_CLOSED` (409), else `ERR_UNAUTHORIZED_PHASE_ACTOR` (403). Owners: DEMAND_REVIEW {SopAdmin, DemandPlanner, DemandReviewLead}, SUPPLY_REVIEW {SopAdmin, SupplyPlanner}, SCENARIO_REVIEW {SupplyPlanner}, EXECUTIVE_REVIEW {ExecutiveSponsor}, PUBLISHED {} — this is the only reading that satisfies §3.6 ("any other phase" → PHASE_CLOSED), §3.7 select, and §3.7 evaluate ("or as PHASE_CLOSED when the actor is the role that owns the phase") simultaneously.
- **Forecast transitions** carry a cycle-phase precondition only on `BASELINE → UNDER_CONSENSUS` (PRD §3.3 + scaffold preconditions); the two lock edges and the rework edge do not. This keeps the "manual unlock stales the item's plans" rule reachable during SUPPLY_REVIEW. The frozen barrier still covers all four.
- **Gate order** per op: phase_actor(60) → SoD(80) → OCC(90) → frozen(100) → phase_closed(110) → legality(120) → referential(130) → calendar(140) → uniqueness(150) → safety limits(160) → financial guardrails(170).
- **Version-bump discipline:** one bump per cycle transition; one on supply-plan create; one per affected cycle when plans go STALE (deduped); one on scenario select (covers the supersede recompute); none on scenario evaluate; none at cycle create. Adjustment create bumps the forecast line exactly once even when it supersedes an earlier proposal (`void_adjustment(..., recompute_line=False)` then a single rollup+touch).
- **Rounding fidelity:** `Decimal` throughout with round-once-where-specified — separate roundings for promotion lift and cannibalisation terms, per-line-then-sum roll-up, ceiling-first cycle-stock term in the reorder point, 6-dp rounding before flooring in hours→units, MAPE as round-then-average (per-record `ape_pct` kept as an internal `_ape_dec` Decimal, stripped from responses) vs WMAPE/bias as aggregate-then-round.
- Reopen reverts CONSENSUS_LOCKED lines to UNDER_CONSENSUS but does **not** un-commit adjustments (only the manual forecast edge does), per each passage's literal text.
- `AccuracyRecord` created via `new_row(with_common=False)` so it carries only `id` + `created_at`.
- Two fidelity fixes made this session: `mape_pct` was leaking a `Decimal` into JSON (now `float`), and `void_adjustment` gained `bump_line` so supersession doesn't double-bump the line.

## Verification performed
`python3 -m py_compile` clean on all 20 `.py` files; `url_map` dump confirms all 47 routes; two end-to-end smoke runs (~55 assertions) covering the full cycle lifecycle through publication, all three adjustment types with review/revision/resubmit, the rationing waterfall (conservation identity checked: 1420+500+495 == 2415), scenario evaluate/select with OCC 412, the three-hop runout cascade, capacity changeover + monthly-hour rejections, CustomerRep scoping, pagination bounds, and the clock capability — all passed, with the arithmetic hand-verified (baselines 1320/1000, safety stock 457/182, reorder 757/582, promotion delta 200-75=125, APE 18.33 -> grade B / OVER_FORECAST). Smoke server was killed by its specific PIDs (881478, 881480) and port 35995 confirmed free; `__pycache__` and temp scripts removed. No files were read or written under `test_helpers/` or `test_suite/`, and no sibling task directory was touched.

## Step 5: Generate unit tests — 2026-09-05T00:52:00.000Z

Generation is complete. Everything is at the task root (`test_helpers/`, `test_suite/`), nothing was written into `workspace/`.

**Files written (test_helpers/ — 9 modules, 2,291 lines)**
`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

**Files written (test_suite/ — conftest + 16 test modules, 6,214 lines)**
Queue A (36 tests, >=2 per difficulty instance): `test_depth_calculation_variants.py` 8, `test_depth_state_machine_loops.py` 4, `test_depth_cascades_and_invariants.py` 8, `test_depth_precedence_and_eligibility.py` 8, `test_depth_boundaries_and_windows.py` 8.
Queue B (82 tests, 1 per non-stub corner instance): `test_corner_entities.py` 12, `test_corner_state_machines.py` 14, `test_corner_calculation_demand_and_supply.py` 8, `test_corner_calculation_money_and_accuracy.py` 7, `test_corner_validation_uniqueness_and_horizon.py` 5, `test_corner_validation_eligibility_and_limits.py` 7, `test_corner_validation_precedence.py` 7, `test_corner_endpoints.py` 5, `test_corner_errors.py` 4, `test_corner_rbac.py` 8, `test_corner_concurrency_and_consistency.py` 5.

**Totals** — 118 tests: queue A 36, queue B 82. All 18 difficulty instances have >=2 tests; all 82 non-stub corner instances have >=1 test; zero uncovered non-stub instances.

**Verification** — every `Design:` tag resolves to a real instance in the source yamls (0 bad tags, 0 dual tags, 0 untagged tests, no stub instance tagged); every docstring carries exactly one PRD quote that grep-matches `workspace/PRD.md` verbatim after whitespace normalisation (16/16 files report `BAD: 0`); no quote is reused across files; all 25 `.py` files `py_compile` clean; no unused imports; `__pycache__` removed.

**Instances skipped (6, all pre-marked stubs carrying `excluded_because:` deferrals to a named §1.8 difficulty instance — no placeholders emitted)**
- `calculations/allocation_fill_rate_pct_rounds_half_up_to_two_decimals`
- `calculations/scenario_trade_spend_rounds_half_up_at_the_tier_boundary`
- `errors/err_ration_target_invalid_on_a_non_planned_plan`
- `errors/err_family_monthly_hours_exceeded_on_the_second_block`
- `cross_cutting_complexity_layers/item_runout_cascade_reaches_promotions_adjustments_and_consensus`
- `cross_cutting_complexity_layers/reopen_cascade_voids_allocations_and_supersedes_the_selected_scenario`

**Two design-index defects resolved in the PRD's favour** (recorded here because they change asserted outcomes): the `rbac` and `consistency_model` recipes assert an `ENDORSE` review returns status `COMMITTED`, but PRD §3.4 says `ENDORSE` moves `PROPOSED → ENDORSED` — the tests assert `ENDORSED`; and the `rbac` capacity-block recipe calls 2026-10-01..2026-10-31 buffer-legal against a 2026-09-01..2026-09-30 block, which violates the §3.2 two-day changeover gap — the test uses 2026-10-05..2026-10-20 so its `!= ERR_CAPACITY_BLOCK_OVERLAP` assertion is meaningful. Earlier in the run, three corner recipes' 422 statuses for `ERR_DUPLICATE_FORECAST` / `ERR_SUPPLY_PLAN_EXISTS` / `ERR_DUPLICATE_ACCURACY_RECORD` were corrected to the PRD §5 value of 409, and a recipe `channel: "MASS"` was replaced with the declared `GROCERY`.

One pre-existing citation defect was also fixed: `test_depth_state_machine_loops.py` had truncated a PRD sentence with an added full stop, breaking the verbatim match; it now quotes the full clause.

## Step 7: Run tests and iterate — 2026-09-05T01:31:00.000Z

Clean 8-round sweep achieved: **117/117 passing in all 8 parallel rounds**, zero failures, zero errors, no flakiness.

## Iterations run
3 (sweep 1: 107/118 → sweep 2: 116/117 → sweep 3: 117/117 across all 8 rounds). Every failure was deterministic across all 8 rounds in every iteration — no load-induced or timing flakiness appeared.

## Tests deleted (1)
- `test_supply_plan_create_rejects_a_cycle_with_one_unlocked_line` (`test_depth_precedence_and_eligibility.py`) — **unreachable-precondition**. It targeted the "even one line still in `BASELINE` or `UNDER_CONSENSUS`" branch of `ERR_FORECAST_NOT_LOCKED`, but that state cannot exist in a PRD-faithful implementation: §3.5's `DEMAND_REVIEW → SUPPLY_REVIEW` advance sweeps "every forecast line still in BASELINE or UNDER_CONSENSUS ... to CONSENSUS_LOCKED", and §2.8 bars forecast transitions once the cycle leaves `DEMAND_REVIEW`. No setup repair preserves the test's identity. The sibling reachable branch ("no line exists at all") remains covered by the passing `test_an_item_with_no_forecast_line_at_all_cannot_be_planned`. Scaffold rule: `Difficulty/cross_entity_state_dependency/supply_plan_create_requires_all_forecasts_consensus_locked`.

## Assertion removed (partial-coverage split, STEP 1c)
- `test_a_rejected_adjustment_cannot_be_reviewed_or_resubmitted_again` — dropped only `rejected["review_note"] == "no evidence"`. **Branch-asymmetric side effect**: §3.4 renders `review_note` storage solely on the `REQUEST_REVISION` branch ("REQUEST_REVISION ... stores the supplied review_note"); the `REJECT` branch is silent, so omitting the write is PRD-faithful. All covered assertions (terminality, `reviewed_by_user_id`, roll-up untouched, both follow-up 409s) were kept.

## Fixes applied to `test_suite/`
- `test_corner_entities.py` / `test_corner_errors.py` (4 assertions) — read `response_type` from the top level instead of from inside `meta`. §2.2 makes `response_type` a sibling of `meta`/`data` and states "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`", so the old reads raised `KeyError`.
- `test_depth_cascades_and_invariants.py::test_policy_reset_stales_the_plan_voids_its_allocations_and_zeroes_the_plan_value` — the loop asserted all 5 allocation rows go `VOIDED`, contradicting §3.6's "Rows already in `WITHHELD_CREDIT_HOLD` are left as they are." Now asserts the credit-hold row keeps its status while the four `ALLOCATED` rows void with `fill_rate_pct` 0.00 / `allocation_pass` `NONE`, plus the §2.10 conservation identity — a strictly stronger, faithful check.
- `test_depth_precedence_and_eligibility.py::test_rejected_supply_plan_create_writes_nothing` — retargeted its setup (`_partially_locked_cycle` → `_unsettled_demand_side_cycle`) onto the reachable empty-line-set branch of the same PRD sentence, keeping all write-nothing assertions and adding the missing explicit `ERR_FORECAST_NOT_LOCKED` check.
- `test_depth_precedence_and_eligibility.py::test_phase_actor_outranks_the_fiscal_guardrail_on_the_same_request` — asserted the line stayed `BASELINE` at its original version after the cycle advance, ignoring §3.5's sweep. Now captures the post-sweep state (asserting `CONSENSUS_LOCKED` / `consensus_units == 333`) and verifies the *refused* create moved nothing further, which is what the test actually exists to prove.

## Fixes applied to `implementation/`
- `auth.py::check_phase_actor` — removed an inverted role-ownership guard that suppressed `ERR_UNAUTHORIZED_PHASE_ACTOR` whenever the acting role owned the target phase, letting the request fall through to `ERR_CYCLE_FROZEN` (step 10), `ERR_CYCLE_PHASE_CLOSED` (step 11) or `ERR_STALE_FORECAST_VERSION` (step 9). Per §2.8 the check covers exactly nine operations and fires on *any* cycle-status mismatch regardless of role; the role-ownership condition belongs to `ERR_CYCLE_PHASE_CLOSED` alone, and §2.9's ladder plus "it wins wherever both could apply" makes phase-actor authoritative. This single fix resolved three independent precedence failures. Call sites were already correct — forecast create/transitions rightly bypass the actor check, so `ERR_CYCLE_PHASE_CLOSED` stays reachable for exactly the two writes the actor check omits.

No implementation check required by the PRD was weakened, no assertion was downgraded to an HTTP-status check, and no skip/xfail was introduced.

**Orchestrator verification**: independently re-read all 8 `results.$i.json` (mtime 2026-09-05 01:22) — every round reports `passed=117 total=117 failed=0 errors=0`; `grep -c "^def test_" test_suite/*.py` totals 117, matching. Step 7 did not touch worklog.md. Step 8 will run (Step 7 made 1 implementation fix, so the skip condition does not apply).

## Step 8: Finalize PRD — 2026-09-05T01:40:00.000Z

Done. `PRD_FINALIZED.md` written.

## Line counts
- `PRD.md` — 502 lines; `PRD_FINALIZED.md` — 504 lines (+2, **+0.40%**). Six hunks, five of them single-line in-place revisions.

## Changes
- **§2.8** — revise — pinned the phase-actor / phase-closed boundary: for the nine phase-actor operations *any* cycle-status mismatch is `ERR_UNAUTHORIZED_PHASE_ACTOR` regardless of the acting role, and `ERR_CYCLE_PHASE_CLOSED` is scoped to the two writes the actor check omits (forecast-line create, `BASELINE → UNDER_CONSENSUS` transition), so the nine can never observably return phase-closed — `implementation/auth.py:86-105`, `auth.py:113-132`, `implementation/routes/forecasts.py:56-57,112-113`
- **§3.4 (Review)** — revise — cycle-not-in-`DEMAND_REVIEW` on an adjustment review is `ERR_UNAUTHORIZED_PHASE_ACTOR`, not `ERR_CYCLE_PHASE_CLOSED` — `implementation/routes/adjustments.py:144`
- **§3.4 (Review branches)** — insert — one sentence: `REQUEST_REVISION` is the only branch that writes `review_note`; `ENDORSE`/`REJECT` leave it as found (always null) — `implementation/routes/adjustments.py:155-162`
- **§3.6 (Rationing)** — revise — rationing outside `SUPPLY_REVIEW` is `ERR_UNAUTHORIZED_PHASE_ACTOR` — `implementation/routes/supply.py:77` → `auth.py:126`
- **§3.7 (Evaluation)** — revise — dropped the "or `ERR_CYCLE_PHASE_CLOSED` when the actor owns the phase" alternative; always phase-actor — `implementation/routes/scenarios.py:87` → `auth.py:126`
- **§3.7 (Selection)** — revise — cycle not in `EXECUTIVE_REVIEW` on select is `ERR_UNAUTHORIZED_PHASE_ACTOR` — `implementation/routes/scenarios.py:117`

## Per-edit pre-edit search log

**Edit A (§2.8)** — (a) Subject: which cycle-status mismatch yields `ERR_UNAUTHORIZED_PHASE_ACTOR` vs `ERR_CYCLE_PHASE_CLOSED`, at every gated write. (b) Grepped `phase_gate|check_phase_actor|check_phase_closed|check_frozen|PHASE_OWNERS` across all of `implementation/`; read `auth.py` in full plus every callsite: `adjustments.py:68/74/75, 144/147/148, 186/191/193`; `supply.py:39, 77`; `scenarios.py:55, 87, 117/124/125`; `accuracy.py:39` (`frozen=False`); `forecasts.py:56-57, 109-113`. Confirmed `check_phase_closed` is dominated by an identical-status `check_phase_actor` at every one of the nine operations, so its only reachable sites are the two forecast writes; also confirmed `PHASE_OWNERS` is now unreferenced dead data, and that for forecast create/transition the authorised roles (`SopAdmin`, `DemandPlanner`, `DemandReviewLead`) all own `DEMAND_REVIEW`, so the PRD's role-ownership clause is vacuously satisfied rather than violated. (c) Adjustments made: kept the role-ownership clause alive as a satisfied observation ("whose owning roles are the only ones authorised for them anyway") instead of deleting it, since impl's `check_phase_closed` genuinely ignores role and deleting the clause would have been a false universal; and scoped phase-closed to the *`BASELINE → UNDER_CONSENSUS`* transition only rather than "forecast-line transitions" generally, because `forecasts.py:112` gates only that edge — the lock edges and the `CONSENSUS_LOCKED → UNDER_CONSENSUS` rework edge are admitted in any non-frozen cycle status, consistent with §3.3's "carries no precondition of its own". Also phrased the closing claim as "can never observably return", not "does not implement", to stay true to code that still calls the check.

**Edit B (§3.4 review)** — (a) Subject: the error for an adjustment review against a cycle outside `DEMAND_REVIEW`. (b) Read `adjustments.py:131-169` (review) and the two sibling writes `create_adjustment:64-75` and `resubmit_adjustment:185-193`, plus `auth.py:86-105`. All three call `check_phase_actor(cycle, "DEMAND_REVIEW")` first; the §3.4 prose for create/resubmit names no error, so only the review sentence needed changing. (c) None; added the "under the phase-actor check of §2.8" pointer so the sentence does not restate the ladder position locally and cannot conflict with §2.9.

**Edit C (§3.4 review branches)** — (a) Subject: every write to `review_note` and `reviewed_by_user_id`. (b) Grepped both fields across all of `implementation/`: only three write sites — `adjustments.py:110` (create → null), `:162` (`REQUEST_REVISION` only), `:219-220` (resubmit → both null). No cascade in `cascades.py` touches either field; `void_adjustment` leaves them alone. Verified `review_adjustment` requires status `PROPOSED` (`:150`), so at every `ENDORSE`/`REJECT` the field is necessarily already null. (c) Wrote it as "leave the field exactly as they found it" *and then* stated the observable consequence (reads back null) with its reason, rather than asserting a bare "is set to null" — the latter would have mis-described the code path, which performs no write at all, and would have been a false universal if any future row could reach review with a non-null note.

**Edit D (§3.6 rationing)** — (a) Subject: the error for rationing a plan while the cycle is outside `SUPPLY_REVIEW`. (b) Read `supply.py:70-100` (`phase_gate(cycle, "SUPPLY_REVIEW")` at `:77`) and its sibling `create_supply_plan:39`, plus `auth.py:122-132` to confirm `phase_gate` runs `check_phase_actor` before `check_frozen`/`check_phase_closed`. Confirmed §3.5's supply-plan-create prose names no phase error, so only the ration sentence needed changing. (c) None.

**Edit E (§3.7 evaluation)** — (a) Subject: the error for evaluating a scenario outside `SCENARIO_REVIEW`. (b) Read `scenarios.py:80-104` (`phase_gate` at `:87`) and its sibling `create_scenario:55`, plus `auth.py:122-132`. Both go through `phase_gate` with `phase_actor=True`, so `SupplyPlanner` (the `SCENARIO_REVIEW` owner in the now-dead `PHASE_OWNERS`) gets the same phase-actor rejection as anyone else. (c) Replaced the disjunction with "whatever the acting role" rather than simply deleting the second alternative, to positively close the role carve-out that the original wording invited — the exact misreading the removed `auth.py` guard implemented.

**Edit F (§3.7 selection)** — (a) Subject: the error for selecting a scenario outside `EXECUTIVE_REVIEW`. (b) Read `scenarios.py:107-148`, confirming the ordering `check_phase_actor:117` → `check_sod:118` → OCC `:120` → `check_frozen:124` → `check_phase_closed:125` (unreachable), and cross-checked against §2.9 steps 6/8/9/10/11. (c) None; left the rest of the sentence's narrative ordering untouched since §2.9 governs precedence and the impl ordering already matches it.

Two Step 7 items needed **no** PRD change: the `response_type`-inside-`meta` fixture bug (§2.2 already makes `response_type` a sibling of `meta`) and the credit-hold allocation row surviving a policy reset (§3.6's "Rows already in `WITHHELD_CREDIT_HOLD` are left as they are" plus `allocation_pass` → `NONE` already match the shared `cascades.py::void_plan_allocations` used by all four staleness paths, reopen included). The deleted test and the two retargeted precedence tests are likewise covered by existing §3.5 prose.

**Orchestrator verification**: `PRD_FINALIZED.md` = 504 lines vs 502; `diff` shows 12 changed lines total (a genuinely minimal patch, not identical); all 5 top-level sections and all 52 §5 error rows still present; file ends on a complete table row.

## Step 9: Complete PRD — 2026-09-05T02:12:00.000Z

Run as **three sequential passes partitioned by implementation module**, all editing one shared `workspace/PRD_COMPLETED.md`. Pass 1 performed the single `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place with the Edit tool only. Total: **51 changes (41 ambiguity-pins, 10 mismatch-revisions)**; 504 → 505 lines, 103,265 → 112,869 chars (+9,604); `diff PRD_FINALIZED.md PRD_COMPLETED.md` = 178 lines / 44 hunks (not byte-identical, so the scan demonstrably landed).

### Pass 1 — app.py, util.py, store.py, envelope.py, errors.py, validators.py, auth.py, routes/{master,capacity,promotions,clock}.py

`cp` performed from **PRD_FINALIZED.md** (it existed). 505 lines / 108,370 chars after the pass. ambiguity-pins **16**, mismatch-revisions **4**.

- §2.1 — revise — mismatch — `X-User-ID` is never compared against a family's `accountable_planner_user_id`; that field is only stored, copied onto accuracy records and used as a list filter, so it is not an authorisation test — `auth.py:44-72`, `routes/master.py:52,85-89`
- §2.1 — insert — ambiguity — whitespace-only header values are treated as empty, and role names are matched case-sensitively — `auth.py:47-52`
- §2.2 — insert — ambiguity — unrouted paths answer `ERR_NOT_FOUND`/404 and wrong methods `ERR_METHOD_NOT_ALLOWED`/405 in the same error envelope; trailing slashes are tolerated — `app.py:24,42-51`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` text is `ERR_INVALID_REQUEST` — `validators.py:172-185`
- §2.3 — insert — ambiguity — `created_at` ties (pervasive, since the clock is frozen) break by server creation sequence, never by `id` — `store.py:41-43`
- §2.3 — insert — ambiguity — filters are optional (except the CustomerRep `customer_id`), combine conjunctively, enum filters validate to 400, identifier filters match literally and never 404, undeclared query params ignored — `validators.py:189-223`, `routes/master.py:85-91`
- §2.5 — insert — ambiguity — `to_iso8601` accepts `Z`, an explicit offset or no zone at all; the echoed `current_utc` is the normalised 3-digit UTC rendering and the sole `data` field; missing/unparseable → `ERR_INVALID_REQUEST` — `util.py:48-57`, `routes/clock.py:15-23`
- §2.5 — insert — ambiguity — month part must be `01`–`12` — `util.py:11`
- §2.5 — insert — ambiguity — date strings must name a real calendar day — `util.py:115-122`
- §2.9 step 3 — insert — ambiguity — explicit `null` == omitted; integer fields reject fractional/string/boolean values while number fields accept int or decimal; absent/empty body reads as `{}`; non-object JSON is 400 — `validators.py:12-34,25-26`
- §2.9 conditional fields — revise — mismatch — `runout_end_month` must be "absent **or null**" for non-RUNOUT targets (was "absent") — `validators.py:151-154`
- §3.1 — insert — ambiguity — a family's `name` is required but may be the empty string — `routes/master.py:51`
- §3.1 — insert — ambiguity — any of the six lifecycle values may seed an item on create with no reachability rule; `runout_end_month`/`successor_item_id` cannot be seeded — `routes/master.py:113-137`
- §3.1 — insert — ambiguity — inventory-policy reset requires all three inputs and is admitted whatever the item's lifecycle state — `routes/master.py:170-184`
- §3.1 — insert — ambiguity — a customer's `name` follows the same required-but-possibly-empty rule — `routes/master.py:267`
- §3.4 — insert — ambiguity — promotion create resolves `item_id` before `customer_id`; drafting/approving consult no cycle, so no `status`/`posture` gating — `routes/promotions.py:35-36,21-82`
- §3.8 — insert — ambiguity — `successor_item_id` is consulted only by `MATURE → RUNOUT`; elsewhere it must still resolve (before transition legality) and is then ignored, not stored — `routes/master.py:198-215`
- §3.8 — insert — ambiguity — the `CANCELLED_NPI` adjustment sweep also zeroes `applied_delta_units` and re-runs the line's roll-up — `routes/master.py:227-231`, `cascades.py:76-86`
- §3.8 hop three — revise — mismatch — only `UNDER_CONSENSUS`/`CONSENSUS_LOCKED` lines past `runout_end_month` truncate; `BASELINE` (and already-truncated) lines are untouched, unlike the `CANCELLED_NPI` sweep — `routes/master.py:250-254`
- §4 clock row — revise — mismatch — the role column said `SopAdmin` while the endpoint is served with any or no headers per its §2.1/§2.5 exemption — `routes/clock.py:15`, `auth.py:75-80`

Pass 1 left unpatched, with reasons: no §5 rows added for `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED` (catalogue must stay at 52 rows; both pinned in §2.2 prose instead); `auth.PHASE_OWNERS` (dead code, never referenced); `auth.open_endpoint` (defined but never applied — the clock route simply carries no gate, already pinned); untrimmed string storage and exact/case-sensitive code uniqueness (too fine-grained for prose); JSON spelling of numeric defaults `npi_ramp_pct` → `100` and `demand_cv` → `0.3` (numerically identical to the PRD's "100"/"0.30"); relative order of two step-3 shape failures in one body (both surface as `ERR_INVALID_REQUEST`, indistinguishable); `cancel_promotion_runout` skipping its adjustment hop for a DRAFT promotion (unobservable — a DRAFT promotion can never be cited by an adjustment); §3.7 publication-role and §3.9 roll-up prose (subjects owned by passes 2/3).

### Pass 2 — routes/{cycles,forecasts,adjustments}.py, calcs.py

505 lines; 108,022 → 110,690 chars. All edits in-paragraph; line numbering unchanged. ambiguity-pins **15**, mismatch-revisions **4**.

- §2.6 (unit integers) — revise — mismatch — "Only `signed_error_units` may be negative" was false; `baseline_units`, `consensus_units` and `applied_delta_units` are never clamped (negative `delta_units`, cannibalisation > lift, or a steep negative trend all carry through) — `calcs.py:84,91-99`
- §3.3 (forecast create) — insert — ambiguity — body FKs resolved `cycle_id` → `item_id` → `customer_id`, first unknown wins — `routes/forecasts.py:50-52`
- §3.3 (forecast list) — insert — ambiguity — the `month` filter is itself format-validated, a malformed one is `ERR_INVALID_REQUEST` rather than an empty page — `routes/forecasts.py:167`, `validators.py:198`
- §3.3 (rework edge) — revise — mismatch — "every non-`STALE` supply plan" → only plans in `PLANNED` or `RATIONED`, in any cycle; a `COMMITTED` plan is left alone — `routes/forecasts.py:146` → `cascades.py:49-54`
- §3.4 (adjustment create) — insert — ambiguity — body FKs resolved `demand_forecast_id` first, `promotion_id` second — `routes/adjustments.py:57-62`
- §3.4 (proposal creation) — insert — ambiguity — the target line's `status` is no precondition; a `CONSENSUS_LOCKED` or `RUNOUT_TRUNCATED` line accepts a proposal — `routes/adjustments.py:64-96`
- §3.4 (roll-up) — insert — ambiguity — the `RUNOUT_TRUNCATED` override suppresses units only; `endorsed_adjustment_count` still counts contributing rows — `calcs.py:115-118`
- §3.4 (review) — insert — ambiguity — `review_note`, when present, must be a string but may be empty — `routes/adjustments.py:136`
- §3.4 (`REJECT`) — insert — ambiguity — the forecast line is not written, so its `version` does not move — `routes/adjustments.py:165`
- §3.4 (`REQUEST_REVISION`) — insert — ambiguity — same: line `version` stands still — `routes/adjustments.py:165`
- §3.4 (resubmit) — insert — ambiguity — omitted/null `delta_units` keeps the value already carried — `routes/adjustments.py:205-206`
- §3.4 (resubmit) — insert — ambiguity — the `PROMOTION` recompute reads the cited promotion's current percentages with no re-test of its status — `routes/adjustments.py:208-212`
- §3.4 (supersession) — insert — ambiguity — the void shares the creation's single line `version` bump (+1 total, not +2) — `routes/adjustments.py:119,125-126`
- §3.7 (publication) — revise — mismatch — "reserved to the `ExecutiveSponsor`" → driven by `ExecutiveSponsor` **or** `SopAdmin` — `routes/cycles.py:79`
- §3.7 (reopening) — revise — mismatch — `SopAdmin` may also reopen; `reopen_reason` must be non-empty and is validated only, never persisted — `routes/cycles.py:79,83-86`
- §3.7 (reopen cascade) — insert — ambiguity — unlike §3.3's rework edge, the reopen sweep leaves adjustments alone: `COMMITTED` stays `COMMITTED` and keeps contributing — `routes/cycles.py:147-150`
- §3.9 (empty record set) — insert — ambiguity — the two supporting unit totals are `0`, not null — `calcs.py:409-411`
- §3.9 (worst offender) — insert — ambiguity — zero-actual items are ordered among themselves by the same earliest-record tie-break — `calcs.py:466-472`
- §3.9 (accuracy summary) — insert — ambiguity — `family_id` is matched literally, never resolved as an FK; an unknown family empties the scope instead of 404 — `routes/cycles.py:189-195`

Pass 2 left unpatched, with reasons: §2.8's "ten operations" frozen list (eight of the ten are phase-actor-gated first and `FROZEN` only arises at `status == PUBLISHED`, so `ERR_CYCLE_FROZEN` is observable only on forecast create and forecast transitions — the gate lives in pass 1's `auth.py` and §2.8 already carries the analogous unreachability note for `ERR_CYCLE_PHASE_CLOSED`); negative `requested_units` in the rationing waterfall (a negative consensus sum leaves a candidate in none of the four branches and raises `KeyError` → HTTP 500 at `calcs.py:268` — a latent crash, not specifiable behavior, so the §2.6 wording stays silent on whether aggregated request figures can go negative); `calc_constrained_supply`, `calc_rationing_waterfall`, `calc_scenario_gap_closure`, `calc_inventory_policy`, `calc_statistical_baseline`, MAPE/WMAPE/bias/grade (verified line by line against §3.1, §3.3, §3.5–§3.9 — formulas, step order, tie-breaks, clamping, rounding sites, tier boundaries, the six-decimal hours conversion — all already pinned uniquely); per-record `version` bumps in the `DEMAND_REVIEW → SUPPLY_REVIEW` sweep (already covered generically by §2.10).

### Pass 3 — routes/{supply,scenarios,accuracy}.py, cascades.py

505 lines; 111,065 → 112,869 chars. ambiguity-pins **10**, mismatch-revisions **2**.

- §3.1 (inventory-policy reset) — revise — mismatch — PRD said "every supply plan of that item which is not already `STALE`" is invalidated; impl stales only `PLANNED`/`RATIONED` and leaves `COMMITTED` alone — `cascades.py:49-52`
- §3.8 (item lifecycle) — revise — mismatch — same "not already `STALE`" claim corrected to `PLANNED`/`RATIONED`, plus the owning cycle's `version` bump — `cascades.py:49-59`
- §3.5 (supply-plan create) — insert — ambiguity — body identifiers resolve `cycle_id` then `item_id` (unknown-both ⇒ `ERR_CYCLE_NOT_FOUND`) — `routes/supply.py:36-37`
- §3.5 (supply-plan create) — insert — ambiguity — the cycle's `version` increments by 1 when the create recomputes its money and posture — `routes/supply.py:66` → `cascades.py:11-16`
- §3.6 (ration) — insert — ambiguity — the response body is the updated supply plan, not the allocation rows — `routes/supply.py:100`
- §3.6 (ration) — insert — ambiguity — allocation rows are created in ascending customer `created_at`/creation-sequence order (not waterfall-pass order), which fixes the allocation list ordering — `routes/supply.py:84-95` + `calcs.py:208-209,266-269`
- §3.7 (scenario create) — insert — ambiguity — `cycle_id` resolves before `target_item_id` — `routes/scenarios.py:51-53`
- §3.7 (scenario evaluate) — insert — ambiguity — the plan-existence test runs last, so a non-`DRAFT` scenario reports `ERR_SCENARIO_NOT_EVALUATABLE` even when its target plan is also gone — `routes/scenarios.py:89-98`
- §3.7 (`SELECTED → SUPERSEDED`) — insert — ambiguity — a superseded scenario retains `selected_by_user_id` as well as its `net_gap_closure_cents` — `routes/scenarios.py:144-145`
- §3.9 (accuracy create) — insert — ambiguity — the three body identifiers resolve `cycle_id`, `item_id`, `customer_id` in that order — `routes/accuracy.py:32-34`
- §3.9 (accuracy create) — insert — ambiguity — the `ERR_MONTH_OUTSIDE_HORIZON` test examines only that triple's `CONSENSUS_LOCKED` forecast lines, against the inclusive horizon bounds — `routes/accuracy.py:43-51`
- §3.9 (family roll-up) — insert — ambiguity — exactly one family is rolled forward and its own `updated_at`/`version` move — `cascades.py:108-120`

Pass 3 left unpatched, with reasons: `cascades.cancel_promotion_runout`'s `was_approved` guard (unobservable — adjustment create requires an `APPROVED` promotion and promotions never return to `DRAFT`, so a `DRAFT` promotion swept by hop one can have no citing adjustments); `ration`/`evaluate` `store.cycles.get(...) is not None` guards (cycles are never deleted, so the None branch is unreachable); `_ape_dec` on accuracy records (internal underscore key stripped by `public()`, not observable); envelope/pagination/enum-filter validation behaviour in pass 3's route files (already pinned by §2.2/§2.3/§2.9 and pass 3's files add nothing beyond them).

### Orchestrator verification and closing notes

- `PRD_COMPLETED.md` = 505 lines / 112,869 chars; all 5 top-level `## ` sections present (lines 3, 11, 190, 396, 450); §5 still exactly 52 `ERR_` rows; file ends on the complete `ERR_UNCLOSED_GAP` table row; `diff PRD_FINALIZED.md PRD_COMPLETED.md` = 178 lines / 44 hunks — **not** byte-identical, so the scan demonstrably ran.
- `find workspace/implementation test_suite test_helpers -newermt "2026-09-05 01:25"` returns nothing but the `results.*.json` artifacts: **neither Step 8 nor Step 9 touched code or tests**, so the Step 7 verdict of 117/117 across all 8 parallel rounds still holds for the artifacts on disk and no re-sweep was required.
- **Judgement call recorded (autonomy):** pass 2 surfaced a latent `KeyError` → HTTP 500 at `calcs.py:268` when an aggregated `requested_units` figure is negative. I deliberately did NOT patch the implementation. Rationale: (a) the PRD is silent on negative aggregated requests, so any behavior there is PRD-consistent and Step 9's mandate is documentation-only; (b) the path is unreachable from every test in the suite; (c) changing implementation after the verified green sweep would invalidate the 117/117 evidence without a re-run, and adding a new guard would be an implementation behavior with no verbatim PRD sentence behind it — forbidden by the pipeline's cardinal rules. It is logged here so a future pass can decide with full information.

Pipeline complete: `workspace/PRD_COMPLETED.md` written.
