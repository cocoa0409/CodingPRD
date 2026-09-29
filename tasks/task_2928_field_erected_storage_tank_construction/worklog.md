# Worklog — task_2928_field_erected_storage_tank_construction

## Step 1: Create task directory — 2026-09-05T17:45:09.739913027Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2928_field_erected_storage_tank_construction and its workspace/ subdirectory. Index 2928 was pre-assigned by the orchestrating caller; no index scan performed.

## Step 2: Generate scaffold — 2026-09-05T19:38:32.610522090Z

All three scaffold artifacts are complete and lint-clean.

## Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2928_field_erected_storage_tank_construction/`)

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 3936 | §1.0–§1.7 only (`scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles`, `segregation_of_duties_rules`) — verified free of both design keys |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2358 | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3992 | `scaffold_corner_design` only |

`worklog.md` and `workspace/` untouched; all scratch confined to `.scratch/step2/`. No sibling task directory was read.

## Lint

```
Coverage
  §1.5 endpoints declared:    66
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  1066

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Domain model

- **14 entities**: Tank, FoundationPackage, SettlementSurvey, PlateLot, ShellCourse, Welder, WeldSeam, NdeReport, WaterSource, HydrotestPlan, WaterWithdrawal, CoatingApplication, Appurtenance, CommissioningPackage. Flat topology, one-to-many + self-referential (`WeldSeam.predecessor_seam_id`) + cross-aggregate.
- **66 endpoints** at prefix `/`, **66 errors**, **54-row validation priority ladder** (1 UNAUTHENTICATED → 54 COURSE_THICKNESS_DEFICIENT), **6 peer roles** (ProjectEngineer, CivilContractor, ErectionSuperintendent, Welder, QcInspector, AuthorizedInspector) plus 3 segregation-of-duties rules.
- **14 state machines**, including two parallel dimensions on Tank (`construction_phase` DESIGN_REGISTERED→…→COMMISSIONED and `quality_posture` OPEN/RESTRICTED/FROZEN driven by `open_nonconformance_count`), a compound ShellCourse status derived from its WeldSeam children, and cyclic machines for WeldSeam repair (capped), CoatingApplication rework (uncapped) and CommissioningPackage review.
- **15 calculations**: API 650 one-foot-method shell thickness (three-way MAX of DESIGN / TEST / diameter-tiered minimum nominal, rounded per case before the MAX, corrosion allowance on the DESIGN case only), dual-variant settlement evaluation (cosine best fit vs adjacent pair), coating DFT acceptance (spot-average 80/120 vs individual gauge), holiday-test voltage per mil, welder continuity decay, weld reject-rate escalation of `required_examination_pct`, tiered water/disposal pricing with a subtotal-keyed permit surcharge, plate steel and water volume ledgers, half-open withdrawal rate envelope, buffered closed-interval RT window conflicts, appurtenance clearance envelope, commissioning document completeness, and the in-service inspection schedule (decay function → internal/external intervals and due dates).
- **Key rules**: OCC on two parents (`expected_tank_version` on plan create, `expected_water_source_version` on withdrawal reserve, both 412); FROZEN blocks all production writes but whitelists the nonconformance-closing operations; RESTRICTED blocks only hydrotest approval, fill advance and commissioning submission/review; hydrotest fill must advance monotonically with a matching settlement hold point; commissioning submission requires COATED + complete appurtenance scope + 4 required documents, with the physical gate outranking the paperwork gate.

## "Harder than expert level" targeting

Difficulty is carried by design, not by volume: a 54-deep priority ladder where several pairs are deliberately adjacent so the wrong ordering is observable (seam state outranks welder qualification, withdrawal temporal outranks permit-volume fiscal, host-course referential outranks clearance, appurtenance-scope outranks missing paperwork); rounding order that is load-bearing (per-case 3-dp rounding before the thickness MAX, per-withdrawal 2-dp rounding before the water-cost sum); two independent Tank state dimensions that must move separately; cascades up to five hops deep with reversal paths (NDE void walks the reject rate back down across a tier edge); and two dual-variant calculators whose variants diverge on identical inputs. §1.8 contains 25 instances spread ≥2 per each of the nine §0.5 rules; §1.9 adds 62 executable breadth recipes plus 20 `excluded_because` stubs across all nine claim-guide sections.

**Orchestrator post-step action:** the subagent kept the directive line `Generate task harder than expert level!` as the first line of `SCAFFOLD.yaml`'s `scenario:` value. The orchestrator stripped that line (and its trailing blank) immediately after this step, so the scenario value now begins at `2928. Field-Erected Storage Tank Construction`. Verified by grep: zero occurrences of "harder than expert" anywhere in the task directory. All three YAMLs re-parsed clean after the edit (SCAFFOLD.yaml 3934 lines post-strip).

## Step 3: Copy shared files — 2026-09-05T19:38:32.622603123Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T19:54:27.110680734Z

PRD generation for task 2928 is complete.

**Output:** `workspace/PRD.md` — **461 lines, 114,765 bytes**. Built in 9 incremental heredoc/append passes; verified with `wc -l` after each. Nothing else in the task directory was touched. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

**Heading list (actual `grep -n '^#'`, matches outline exactly):** 27 headings — §1 Introduction; §2 Global Specifications (2.1 Roles/Access Control, 2.2 Response Structure incl. success+error formats, 2.3 Pagination, 2.4 Resource Identity/Revision Stamps/Logical Clock, 2.5 Numeric Precision and Rounding, 2.6 Version Guards on Contested Parents, 2.7 The Two State Dimensions of a Tank, 2.8 Nonconformance Accounting/Posture Gates/Suspension Cascade, 2.9 Segregation of Duties, 2.10 Order of Rejection); §3 Business Logic & Workflows (3.1 Registering a Tank Design → 3.9 Appurtenances/Commissioning/In-Service Schedule); §4 API Endpoint Reference; §5 Error Code Reference. No truncation: file ends on the last row of the §5 error table (`ERR_PLATE_WEIGHT_EXCEEDED | 409`), no stray heredoc markers, no mid-sentence tail.

**Coverage (mechanically verified against SCAFFOLD.yaml):**
- **Entities/fields — Contract 1 PASS.** 220-name inventory diffed against backticked PRD tokens: 0 missing. All 14 entities narrated with constraints, defaults, initial values.
- **Endpoints — PASS.** All 66 scaffold endpoints render in the §4 table (Method / Path / Description / Authorized Role(s)), including `POST /_clock/set_current_utc`; 0 missing.
- **Errors — PASS.** All 66 error IDs in the §5 table with scaffold HTTP statuses, and all 66 independently narrated in §1–§3 prose.
- **State machines — PASS.** All 14 machines; every `initial_state`, `from`/`to` and terminal state verbatim (0 missing states), including the parallel `Tank.construction_phase` / `Tank.quality_posture` pair, suspension/restore pairs, cyclic coating and commissioning loops.
- **Calculations — PASS.** All 15 rendered, both dual-variant pairs named and contrasted (`SPOT_AVERAGE_80_120` vs `INDIVIDUAL_GAUGE_MIN`; `COSINE_BEST_FIT` vs `ADJACENT_PAIR`). All constants in prose, tier maps checked value-by-value (0.188/0.250/0.313/0.375; 500/2000 → 1.00/0.85/0.70; 1000/2000 → 0.00/0.03/0.05; 0.50/0.25 → 100.0/50.0/10.0), plus round-then-sum ordering, half-open vs closed window semantics, inclusive-at-limit boundaries.
- **Validations — Contract 2 PASS.** All 54 priorities ordered as prose bands in §2.10 with `applies_to` scopes, the two OCC guards (412), the five-hop NDE reject cascade, the four-link coating-rework chain, and sibling-branch symmetry (PASS/FAIL, ACCEPT/RETURN, ACCEPT/REJECT).
- **§3 Path Purity — Contract 3 PASS.** 0 backtick tokens starting with `/`, 0 bare HTTP methods, 0 method+path combinations, 0 unbackticked `/path` fragments in §3.

Ambiguities the doc generator resolved by judgment (flagged for Steps 5–7): (1) priority 24 `ERR_TANK_POSTURE_RESTRICTED` scoped to its four `applies_to` operations rather than all erection work, per the check text — this conflicts with a `Tank.quality_posture == OPEN` precondition listed on the ShellCourse `SPECIFIED → FITTED` and Tank `ERECTION_IN_PROGRESS → SHELL_COMPLETE` transitions; (2) plate-lot quarantine reason taken from `quarantine_reason` when supplied, else `remarks`; (3) `welded_at_utc` taken from `completed_at_utc` when supplied, else the logical clock. Also `MAX_REWORK_CYCLES` is referenced in a `CoatingApplication` field description but defined nowhere, and the state machine says `rework_cycle_count` is uncapped — the PRD states it is uncapped.

**Orchestrator verification:** read the tail of PRD.md independently — ends on a complete markdown table row at a real section boundary, 27 headings present, no heredoc sentinel leakage, no occurrence of the difficulty directive or any scaffold design-file reference. Accepted without regeneration.

## Step 6: Generate implementation — 2026-09-05T20:43:31.691184836Z

The implementation is complete, smoke-tested, and the server is shut down with port 39281 free.

## Deliverable

`workspace/implementation/` — Python 3 + Flask + waitress, 3,529 lines across 17 files, in-memory dicts only (no file, DB, or /tmp persistence), zero seeded data.

```
   11 start.sh          exec python3 app.py, foreground, $PORT (default 10000), bind 0.0.0.0,
                        pip install only when flask/waitress are missing
    2 requirements.txt  flask>=2.0, waitress>=2.0
   82 app.py            8 blueprints, ApiError/HTTPException/Exception handlers, waitress serve
   69 auth.py           PRD 2.1 headers + RBAC + global RLock (order-of-rejection steps 1-2)
  114 envelope.py       PRD 2.2 envelope, PRD 2.3 pagination + domain filters
  118 errors.py         all 71 PRD 5 error ids + HTTP status map
  111 util.py           logical clock (default 2026-08-01T00:00:00Z), ISO-8601 3-digit fmt, Decimal ROUND_HALF_UP
   74 store.py          the 14 in-memory tables, new_row/touch/touch_time/serialize
  183 validate.py       shape validation (PRD 2.10 step 6)
  125 common.py         FK resolvers -> the 14 *_NOT_FOUND errors, frozen/restricted guards
  778 derive.py         every calculation + cascade: one-foot method, settlement envelope, steel and
                        water ledgers, hydrotest cost ladder, reject-rate/examination ladder, DFT,
                        posture recount + suspend/restore, in-service schedule, tank summary
  138 routes_tank.py    PRD 2.4 clock, 3.1 tanks, 3.3 phase transitions, tank summary
  189 routes_found.py   PRD 3.2 foundation packages + settlement surveys
  265 routes_plate.py   PRD 3.4 plate lots, allocations, shell courses, fit-up
  267 routes_weld.py    PRD 3.5 welders, weld seams, weld log, repair loop
  205 routes_nde.py     PRD 3.6 examination scheduling, results, voiding
  376 routes_water.py   PRD 3.7 water sources, hydrotest plans, fill/completion, withdrawals
  175 routes_coating.py PRD 3.8 coating: surface prep, DFT, holiday test
  247 routes_final.py   PRD 3.9 appurtenances, commissioning packages, submission/review
```

**Endpoints: 66 registered vs 66 in the PRD §4 table** — programmatic diff of `app.url_map` against the table returns `missing: []`, `extra: []`.

## Smoke evidence

`bash start.sh` with `PORT=39281`, driven by `.scratch/step6/smoke.py` (85 assertions, **0 failures**) end-to-end through every module: envelope/meta shape (`req_`+20 alnum, 24-char 3-digit timestamp), pagination defaults and `limit=0` -> 400, 401 on missing/blank headers, 403 on wrong and bogus roles, clock set, tank create + defaults + duplicate + `joint_efficiency 0.9` -> 400 + 404 mapping, foundation package (`point_spacing_in 471.2389`, `allowable_differential_in 4.712`), baseline survey, acceptance -> `FOUNDATION_ACCEPTED`, plate lot ORDERED->ROLLED->SHIPPED->RECEIVED (MTR gate, `received_weight_lb 20000.0`), shell course one-foot method (`0.524 / 0.430 / DESIGN / ADEQUATE`), allocation, fit-up -> `ERECTION_IN_PROGRESS`, welder create (`continuity_expires_at_utc 2027-02-11`), seam create + duplicate label, `ERR_WELDER_IDENTITY_MISMATCH`, weld log -> course `WELDED`, NDE schedule (+ duplicate-schedule and `ERR_INDICATION_COUNT_INCONSISTENT` paths), ACCEPT -> `RT_ACCEPTED`, phase -> `SHELL_COMPLETE`, water source, `ERR_STALE_TANK_VERSION` (412), plan create + tank version bump, approval, `ERR_STALE_WATER_SOURCE_VERSION` (412), withdrawal cost `1950.00` and full plan ladder (`disposal 765.00`, `subtotal 2715.00`, `pct 0.05`, `surcharge 135.75`, `total 2850.75`), fill advance + non-advancing + hold-point-missing, coating prep/DFT (`SSPC` ranking, dew-point spread, spot aggregates, `PASS`), appurtenance clearance `36.0` + duplicate + install, package singleton/documents/submission gate, `GET /tanks/{id}/summary`, and the logical-clock continuity boundary (inclusive at expiry, `LAPSED` one second later, RENEW preserving `qualification_date_utc`, REVOKE terminal).

Fresh-boot contract re-verified: after killing and relaunching via `start.sh`, all 14 collections report `total_count=0`.

## Findings worth relaying

- One real defect found and fixed during verification: `GET /nde-reports` was missing the PRD §2.3 `nonconformance_open` filter. All 14 filter sets now match the PRD verbatim.
- Two PRD-vs-SCAFFOLD conflicts resolved in the PRD's favour: the hydrotest DRAFT + `SHELL_COMPLETE` gate applies to **both** approval branches, and `ERR_REPAIR_LIMIT_EXCEEDED` is checked first on a `REPLACEMENT_REQUIRED` seam (§3.5 assigns it explicitly; otherwise the error is unreachable).
- Two ordering calls follow §2.10 over section prose: `settlement_survey_count >= 4` (constraint) before `ERR_HOLD_PERIOD_NOT_ELAPSED` (temporal); `ERR_APPURTENANCES_NOT_INSTALLED` (referential) before `ERR_MISSING_COMMISSIONING_DOCUMENTS` (constraint).
- Judgement call the test suite may probe: `created_at`/`updated_at` are stamped from real time, not the logical clock. The PRD assigns the logical clock to expiries, windows, hold periods and the named `*_at_utc` domain stamps (all implemented that way) but never to the audit stamps, and §2.3 guarantees `created_at` ascending equals recording order — which a rewindable clock would break. Pagination sorts by insertion order, so §2.3 holds regardless.

## Step 5: Generate unit tests — 2026-09-05T21:41:26.661744621Z

Step 5 is complete for task 2928. Final state and audits below.

## Output locations (task root, not under `workspace/`)
- `test_helpers/`
- `test_suite/`

`ls -d workspace/test_helpers workspace/test_suite` -> both "No such file or directory", so nothing leaked into `workspace/`. `__pycache__` dirs from the collection check were removed; both dirs contain only `.py` files.

## Line counts
`test_helpers/` (9 files, 2503 lines): `__init__.py` 1, `api_client.py` 446, `api_errors.py` 170, `assertions.py` 220, `constants.py` 306, `factories.py` 473, `fixtures.py` 737, `test_users.py` 116, `types.py` 34.

`test_suite/` (20 files, 6797 lines): `conftest.py` 15, `test_01_dual_variant_divergence.py` 182, `test_02_combinatorial_formulas.py` 216, `test_03_non_linear_state_machines.py` 374, `test_04_transitive_cascades.py` 319, `test_05_rejection_priority_conflicts.py` 267, `test_06_inclusive_boundaries.py` 279, `test_07_cross_entity_state_gates.py` 322, `test_08_temporal_resource_overlap.py` 322, `test_09_compensating_invariants.py` 491, `test_10_entity_shape_and_lifecycle.py` 394, `test_11_state_machine_transitions.py` 434, `test_12_derived_calculations.py` 274, `test_13_input_validation_boundaries.py` 320, `test_14_endpoint_behaviour.py` 340, `test_15_error_catalog.py` 596, `test_16_error_state_and_posture_gates.py` 729, `test_17_role_authorisation_and_duties.py` 426, `test_18_version_guards_and_recalculation.py` 361, `test_19_immediate_consistency_of_one_write.py` 136.

## Test count
**144 tests**, confirmed by `pytest --collect-only -q` -> "144 tests collected in 0.67s" (collection is clean; no import errors).

## Coverage tally
- **Queue A (§1.8 Difficulty): 25 instances, 25 live, 25 translated -> 82 tests.** Zero skipped. Minimum 2 tests per instance (SKILL.md floor met).
- **Queue B (§1.9 Corner): 82 instances, 62 live, 62 translated -> 62 tests.** Minimum 1 test per live instance. All 8 sections complete: entities, state_machines, calculations, validations, endpoints, errors, rbac 4/4, cross_cutting_complexity_layers 3/3, consistency_model 1/1.
- **20 instances skipped, all for the same reason: the corner yaml itself marks them `excluded_because:`** (a stub pointing at a §1.8 difficulty instance that covers the same claim at greater depth), and stubs are not to be translated: `cyclic_shape_loop_and_termination`, `parallel_dimensions_move_independently`, `guarded_transition_cross_entity_precondition`, `cascade_down_parent_change_reaches_children`, `ledger_sync_updates_ancestor_derived_field`, `compensation_reverses_original_side_effects`, `conditional_cascade_fires_only_for_children_in_one_state`, `threshold_boundary_values_for_examination_escalation`, `tiered_pricing_boundaries_and_straddling`, `rounding_order_inside_the_cost_aggregate`, `aggregate_running_total_survives_reversal`, `interval_merge_boundary_semantics`, `constraint_propagation_reaches_a_fixed_point`, `variant_divergence_on_the_same_inputs`, `variant_selection_follows_the_owning_entity_config`, `priority_ordering_between_simultaneously_violated_rules`, `validity_that_depends_on_another_entity_state`, `cascading_side_effects_end_to_end_and_partial`, `dual_variant_calculation_both_variants_and_the_switch_delta`, `rate_threshold_triggers_at_the_boundary_and_on_reset`. No live instance was skipped for the PRD-first filter — every live instance had verbatim PRD coverage that uniquely derives its asserted outcome.
- 87 distinct instances covered; **0 orphan tags** (every tag resolves to a real yaml `name:`).

## Tag and hygiene confirmation
`cite.py` over the whole suite: `tests: 144 instances covered: 87 problems: 0` — every test has **exactly one** `Design:` line, it is the docstring's last line, its instance exists, every `PRD: "..."` quote matches PRD.md verbatim after whitespace normalisation, and no file contains the word "scaffold" or any skip/xfail marker. `check.py`: `checked 19 files; 0 problems` (every helper import, `X.<attr>` and `api.<method>` resolves). `pyflakes` over both directories: exit 0.

`workspace/implementation/` was never read, listed, or grepped; `worklog.md`, `SCAFFOLD*.yaml`, `PRD.md` and `workspace/INSTRUCTION.md` were not touched. All scratch stayed in `.scratch/step5/`; no sibling scratch dir was removed.

**Orchestrator note:** verified independently that `test_helpers/` and `test_suite/` are at the task root and that no copies exist under `workspace/`. Steps 5 and 6 were launched concurrently in a single message, so the implementation generator could not have read `test_suite/` — the directory did not exist when it started.

## Step 7: Run tests and iterate — 2026-09-05T22:02:16.186407701Z

Clean exit: all 8 rounds at 144/144.

## Summary

**Iterations run:** 2

**Note on tooling:** `.scratch/step7/summarize.py` reported `union of failing tests: 0` alongside `passed=139` in iteration 1 — the runner emits per-test outcomes under the key `status`, not `outcome`. I patched the summarizer's key detection (and its nodeid construction) so failures are actually surfaced. Anyone reusing that script elsewhere should carry the same fix.

**Tests deleted:** none. All 5 failures were localised assertion defects inside otherwise well-covered tests, so they were handled as STEP 1c partial-coverage splits or STEP 2 test bugs.

**Fixes applied to `test_suite/`** (no `test_helpers/` or `implementation/` change was needed — the implementation had zero real defects):

1. `test_07_cross_entity_state_gates.py` — `TestAppurtenanceGateReadsHostCourseStatus::test_accepting_the_examination_opens_the_gate_for_the_same_request`: dropped `assert report["decision"] == DECISION_ACCEPT`. **COMPUTED-FIELD SILENCE / partial coverage** — PRD §3.6 names `decision` only as a request input to the result endpoint; the report's persisted, response-visible fields are enumerated as `status`, `nonconformance_open`, `reported_by_user_id`, `reported_at_utc`, `void_reason`. The accept/reject outcome is expressed through `status` (`REPORTED_ACCEPT`). Remaining seam/course/install assertions kept.

2. `test_13_input_validation_boundaries.py` — `TestForeignKeyResolutionOrder::test_an_unresolvable_welder_id_answers_before_any_qualification_check`: `assert welder_after["last_weld_date_utc"] is None` directly contradicted PRD §3.5 — *"On creation the welder's `qualification_status` is `QUALIFIED`, `last_weld_date_utc` is set to `qualification_date_utc`"*. Replaced with an `assert_instant` against the welder's own `qualification_date_utc`, which preserves the test's actual intent (the refused weld log must not move the base date) while being PRD-faithful. Added the `assert_instant` import.

3. `test_15_error_catalog.py` — `TestPlateLotTransitionGuards`: dropped `assert_instant(received["received_at_utc"], ...)`. **PRD SILENT** — `received_at_utc` appears nowhere in PRD.md (nor in the implementation); §3.3's receipt paragraph stamps only `received_weight_lb` and `remaining_weight_lb`. Status/mtr_number/weight/tank-ledger assertions kept.

4. `test_15_error_catalog.py` — `TestFitupFoundationGate`: relaxed the fit-up refusal to `validate_error_is_one_of([ERR_FOUNDATION_NOT_ACCEPTED, ERR_COURSE_STATE_INVALID])`, plus an explicit `status_code == 409`. **ERROR PRECEDENCE SILENCE** — PRD §3.4 gives the fit-up phase requirement (*"It requires the tank's `construction_phase` to be either `FOUNDATION_ACCEPTED` or `ERECTION_IN_PROGRESS`"*) **no error identifier of its own**. Because an unaccepted package always leaves the tank at `DESIGN_REGISTERED`, that unnamed requirement and `ERR_FOUNDATION_NOT_ACCEPTED` are tripped by the same call, and PRD never says which answers. Folding the phase check into the fit-up state gate `ERR_COURSE_STATE_INVALID` (§2.10 priority 13, ahead of the referential checks) is a faithful reading — which is what the implementation does. Both readings are articulable, so the sanctioned relaxation applies rather than a deletion.

5. `test_18_version_guards_and_recalculation.py` — `TestHydrotestPlanTankVersionGuard` (2 lines): the test asserted plan *creation* re-points `tank.active_hydrotest_plan_id`; corrected to `is None`. PRD §3.7 sets that pointer only on approval — *"On `APPROVE` the plan moves `DRAFT → APPROVED` ... and the tank's `active_hydrotest_plan_id` is pointed at the plan"* — while §3.7's create paragraph is silent and §3.1 starts the field null. §2.6's *"re-points the tank's `active_hydrotest_plan_id`"* is rationale for why the version guard exists, not a create-branch side effect; reading it operatively is also incoherent with the REJECT branch, which never clears the pointer. Two sibling tests that already passed (`test_07:287`, `test_09:312`) assert the pointer is null after a create whose approval was refused or rejected, so these two lines were the minority mis-translation.

**Final sweep evidence** (iteration 2, all 8 parallel rounds under per-test-server isolation):

| round | passed / total |
| --- | --- |
| results.1.json | 144 / 144 |
| results.2.json | 144 / 144 |
| results.3.json | 144 / 144 |
| results.4.json | 144 / 144 |
| results.5.json | 144 / 144 |
| results.6.json | 144 / 144 |
| results.7.json | 144 / 144 |
| results.8.json | 144 / 144 |

Union of failing tests: 0. No flakiness — the 5 iteration-1 failures were deterministic across all 8 rounds, and no load-induced timeout or connection failure appeared in either sweep. `workspace/implementation/`, `test_helpers/`, `PRD.md`, `INSTRUCTION.md` and `worklog.md` are all unmodified.

**Orchestrator verification:** re-read all 8 `results.*.json` independently — 8 rounds present, each `passed=144 total=144` with zero non-passing per-test entries. `grep 'def test_'` still counts 144 tests (no silent deletions beyond the reported zero), and no `@pytest.mark.skip`/`xfail` marker exists anywhere in `test_suite/`. Step 8 is NOT skipped: Step 7 made 5 `test_suite/` fixes, four of which mark PRD silences (computed-field silence, an outright missing field, an unnamed-error precedence gap, and a create-branch side-effect ambiguity) that PRD_FINALIZED.md must pin.

## Step 8: Finalize PRD — 2026-09-05T22:13:02.138118703Z

Done. `PRD_FINALIZED.md` is written; 5 lines changed, structure intact.

**Line counts:** PRD.md 461 -> PRD_FINALIZED.md 461 (0.0% delta). Tail still ends at the last row of the §5 error table (`| ERR_PLATE_WEIGHT_EXCEEDED | 409 |`). Changed lines: 105, 203, 231, 233, 251.

**Changes**

- **§3.6 (line 231) — revise** — report creation now also nulls `indication_count`, `film_count`, `defect_type` — `implementation/routes_nde.py:63-65`
- **§3.6 (line 233) — revise** — result stores `indication_count`/`film_count`; `defect_type` stored on reject, left null on accept; `decision` is input-only and never a persisted field, outcome read off `status` — `implementation/routes_nde.py:127-136,149`
- **§3.4 (line 203) — revise** — the fit-up `construction_phase` requirement is folded into the fit-up state gate and carries `ERR_COURSE_STATE_INVALID`, evaluated right after the `SPECIFIED` check and ahead of posture/foundation/thickness; a `DESIGN_REGISTERED` tank therefore reports the state error, not `ERR_FOUNDATION_NOT_ACCEPTED` — `implementation/routes_plate.py:242-257`
- **§2.6 (line 105) — revise** — "re-points the tank's `active_hydrotest_plan_id`" changed to "will re-point ... once it is approved", plus an explicit note that creation never touches the field — `implementation/routes_water.py:106-129` (create) vs `:172` (approve)
- **§3.7 (line 251) — insert** — create/supersede paragraph now says creation leaves `active_hydrotest_plan_id` untouched; only approval points it and only a failed test clears it — `implementation/routes_water.py:172`, `:274`

**No-edit findings (Step 7 items 2 and 3):** both were pure test-artifact bugs, not PRD gaps. §3.5 already states `last_weld_date_utc` is set to `qualification_date_utc` on creation, which is exactly `routes_weld.py:55`. `received_at_utc` exists in neither PRD.md nor the implementation (grep across `implementation/*.py` returns nothing), so there is nothing to pin.

**Per-edit pre-edit search log**

1. *§3.6 line 231 (report initial nulls).* (a) Subject: the persisted field set of an examination report at creation. (b) Enumerated: `routes_nde.py` `schedule_report` (54-69, the only construction site), `report_result` (127-150), `void_report` (183-185), `list_reports` filters (84-85), `derive.reports_of_seam`/`recompute_reject_rate` consumers, and `envelope.object_response` (no projection/whitelist — rows are emitted whole, so the stored key set *is* the response key set). (c) None; the three added names are exactly the keys initialised to `None`.

2. *§3.6 line 233 (decision not persisted).* (a) Subject: whether a `decision` input becomes a stored field, and where the evidence fields land. (b) Enumerated every `decision` callsite in the impl so the claim stayed scoped to NDE reports and did not leak onto siblings that *do* persist decision-adjacent state: `routes_nde.py:100` (NDE result — not stored), `routes_water.py:152` (plan approval — stores `approved_by_user_id`, not `decision`), `routes_water.py:228` (completion — stores `completed_at_utc`), `routes_final.py:219` (commissioning review — stores `reviewed_by_user_id`), `routes_found.py:89-101` (foundation — *does* persist `decision_remarks`). Also re-read the accept branch's `defect_type = None` (136) and the reject branch's `defect_type = defect_type` (149). (c) Wording deliberately says "a field of the report" rather than anything general about `decision` inputs, so the foundation package's `decision_remarks` and the three sibling endpoints are untouched; and `defect_type` is described per-branch rather than "stored", because the accept branch actively nulls it.

3. *§3.4 line 203 (fit-up phase gate).* (a) Subject: the `construction_phase` precondition on fit-up, its error identifier, and its precedence. (b) Enumerated: every `ERR_COURSE_STATE_INVALID` raise in the impl (`grep` -> only `routes_plate.py:243` and `:247`, both inside `fitup_course`); the full gate order in `fitup_course` (242 status -> 245 phase -> 249 `require_not_frozen` -> 251 foundation -> 254 thickness); §2.10's priority list (state gates 9-22 -> posture 23-24 -> referential `ERR_FOUNDATION_NOT_ACCEPTED` -> thickness last), which the impl order already matches once the phase check is a state gate, so §2.10 needed no edit; the parallel phase gates on other families to confirm I was not implying a system-wide pattern — plan approval `routes_water.py:158-166` (`ERR_PLAN_STATE_INVALID`, already stated in PRD) and commissioning submission `routes_final.py` (`ERR_PACKAGE_STATE_INVALID`, already stated); and `routes_weld.py:190-220`, which confirms the **weld log has no phase check at all**. (c) Two adjustments: the sentence is scoped to fit-up only (not "phase gates generally"), because the weld log would otherwise be mis-described; and the `DESIGN_REGISTERED` example is worded as "whose foundation package has necessarily not been accepted" rather than claiming `ERR_FOUNDATION_NOT_ACCEPTED` is dead on fit-up — the PRD keeps that error for fit-up, and I did not want a false universal about its reachability.

4. *§2.6 line 105 (version-guard rationale).* (a) Subject: when `active_hydrotest_plan_id` is written. (b) Enumerated all four sites touching the field: `routes_tank.py:91` (initialised null), `routes_water.py:172` (set on `APPROVE` only), `routes_water.py:274` (cleared on completion `FAIL` only), `derive.py:773` (read-only, tank summary projection). Also checked the create path (`routes_water.py:95-129`) — it only `touch(tank)`es for the version bump — and the supersede loop, which only ever supersedes `DRAFT`/`REJECTED` plans, i.e. never the plan the pointer refers to. (c) Kept the original rationale clause and appended the qualification rather than deleting it, so §2.6 still explains why the guard exists; added "once it is approved" so the sentence cannot be read operatively.

5. *§3.7 line 251 (create leaves the pointer alone).* (a) Subject: same field, at the create/supersede site. (b) Same four sites re-confirmed, plus the `REJECT` branch (`routes_water.py:175-178`) which does **not** clear the pointer, and the suspension/restore cascade in `derive.py` which does not touch it either. (c) Widened "null" to "null on a tank that has never had a plan approved" — an unqualified "stays null" would have been a false universal for a tank whose earlier plan was approved and then superseded by a fresh create, where the pointer legitimately still holds the old plan's id. The "only approval points it and only a failed hydrostatic test clears it" clause was verified exhaustive against the grep above.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` returns a non-empty 20-line hunk set (5 changed lines), so the file is a genuine patch and not a bare copy. Both files are 461 lines and PRD_FINALIZED.md ends on the same complete §5 table row, confirming no truncation.

## Step 9: Complete PRD — 2026-09-05T23:13:21.37065851Z

Run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` (pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were forbidden to re-copy and edited in place). Partition: pass 1 = infrastructure + tank/foundation/plate; pass 2 = welding/NDE + the whole `derive.py` calculation and cascade engine; pass 3 = water/hydrotest, coating, appurtenances/commissioning.

**Totals: 461 lines / 115,955 chars (PRD_FINALIZED.md) -> 464 lines / 132,636 chars (PRD_COMPLETED.md); +3 lines, +16,681 chars, 49 diff hunks, 62 changes (49 ambiguity-pins, 13 mismatch-revisions).**

### PASS 1 — infra + tank/foundation/plate (22 changes: 19 ambiguity-pins, 3 mismatch-revisions; 461 -> 464 lines, +7,964 chars)

Performed the `cp` itself. Changes:
- §2.1 — insert — ambiguity — whitespace-only header values treated as absent; both header values trimmed before use — `auth.py:28-35`
- §2.2 — insert — ambiguity — `api_request_timestamp` is real wall-clock time, unaffected by the logical clock — `envelope.py:16-20`, `util.py:28-30`
- §2.2 — insert — ambiguity — undeclared path/method answered with the error envelope carrying `ERR_INVALID_REQUEST` at the router's status (404/405); trailing slash accepted — `app.py:44,54-58`
- §2.3 — insert — ambiguity — `has_more` formula; non-integer / out-of-range `limit` and negative `offset` -> `ERR_INVALID_REQUEST`; empty string falls back to default; offset past the end yields empty data; `created_at` ties keep insertion order — `envelope.py:39,57-92`
- §2.3 — insert — ambiguity — filter matching: exact case-sensitive string compare, boolean accepts `true/false/1/0` any case, null fields never match, unlisted query params ignored — `envelope.py:95-114`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` stamped from real wall-clock time, not the logical clock — `store.py:42,52,60`, `util.py:28-30`
- §2.4 — revise — **mismatch** — "version increases on every mutation" refined: an idempotent re-derivation moves neither field; four named parent-aggregate refreshes move `updated_at` only (tank count when posture unchanged, tank steel ledger, tank reject-rate pair, water-source volume trio); creation always returns `version` 1 even when computed — `store.py:51-61`, `derive.py:140-149,284,358,380,457`
- §2.4 — insert — ambiguity — a body foreign key that is not a JSON string fails the shape check instead of the not-found mapping — `validate.py:24-38`, `common.py:30-34`
- §2.4 — insert — ambiguity — `to_iso8601` required and parseable; clock response is a non-resource 200 whose `data` holds only `current_utc` — `routes_tank.py:27-32`
- §2.8 — revise — **mismatch** — the "only nonconformance-closing operations remain available on a FROZEN tank" sentence was false; the barred roster is the exhaustive one (now including foundation acceptance on either branch), every other write stays available, and the approval/review gates are scoped to their `APPROVE`/`ACCEPT` branches — `common.py:103-117` plus a complete `require_not_frozen`/`require_posture_open` call-site census across all route modules
- §2.10 — insert — ambiguity — JSON `null` == omitted; absent/unparseable/non-object body treated as `{}`; numeric fields must be JSON numbers (strings and booleans rejected, integers accept whole floats); datetime fields accept `Z`, any offset, no offset (UTC) and date-only — `validate.py:18-131`, `util.py:55-70`, `auth.py:38-42`
- §3.1 — insert — ambiguity — `design_standard` is inert; nothing branches on it — `routes_tank.py:40-41`
- §3.1 — insert — ambiguity — `tank_tag` uniqueness is exact and case-sensitive — `routes_tank.py:66-68`
- §3.1 — insert — ambiguity — `total_hydrotest_cost_usd` sums `total_cost_usd` over every plan of the tank whatever its status, 2 dp — `derive.py:751-753,774`
- §3.1 — insert — ambiguity — phase-transition `remarks` must be a string and are not persisted — `routes_tank.py:124`
- §3.2 — insert — ambiguity — `ringwall_top_elevation_ft` carries no sign restriction — `routes_found.py:32-33`
- §3.2 — revise — **mismatch** — a baseline must be shot at `fill_percent` 0; any other fill level with no baseline yet is `ERR_FOUNDATION_STATE_INVALID`; the baseline row's two differential metrics and `governing_metric_in` are 0.000 with no evaluation run — `routes_found.py:128-132,151-158`
- §3.2 — insert — ambiguity — stored `point_readings` echo submission order (reduced to `point_index`/`elevation_in`); only evaluation reorders — `routes_found.py:150`, `validate.py:157-167`
- §3.3 — insert — ambiguity — a body `mtr_number` on the direct `RECEIVED -> RELEASED` hop is ignored; `quarantine_reason` left null when neither it nor `remarks` is supplied — `routes_plate.py:97-99,110-114`
- §3.3 — insert — ambiguity — `allocated_weight_lb` may be zero and a zero-weight allocation still moves the course to `ALLOCATED`; response is the course, not the lot — `routes_plate.py:126,143-148`
- §3.3 — insert — ambiguity — no check compares a lot's as-rolled `thickness_in` against a course's ordered `plate_thickness_in` — `routes_plate.py:121-148`
- §3.3 — insert — ambiguity — allocation-release `reason` is required and non-empty but persisted nowhere — `routes_plate.py:218`
- §3.4 — insert — ambiguity — `course_bottom_elevation_ft` and `design_liquid_height_ft` are unrounded and the height may be negative — `derive.py:171-174,199-201`

Modules: `app.py`, `auth.py`, `envelope.py`, `util.py`, `store.py`, `validate.py`, `common.py`, `routes_tank.py`, `routes_found.py`, `routes_plate.py` all produced edits; `errors.py` already fully pinned (catalogue and HTTP codes match §5 exactly). Cross-read the pass-2/3 modules only to census `require_not_frozen`/`require_posture_open` and `touch`/`touch_time` sites before the two global rewrites.

### PASS 2 — welding / NDE / derive.py (16 changes: 11 ambiguity-pins, 5 mismatch-revisions; 464 lines held, +4,097 chars)

Did not re-copy; found the file at 464 lines / 123,919 chars and spot-verified pass 1's sentences survive. Changes:
- §2.4 — insert — mismatch — the blanket "every status move advances `version`" claim was false for the lazy welder continuity re-evaluation, which rewrites `qualification_status` with no `version`/`updated_at` move — `derive.py:461-470`, `routes_weld.py:78`
- §2.5 — revise — mismatch — DFT figures said "carried to 1 decimal place"; impl stores 2 dp spot/overall averages and an unrounded lowest gauge reading — `derive.py:572-591`
- §2.8 — insert — ambiguity — `suspension_reason` literals pinned as `TANK_POSTURE_RESTRICTED` / `TANK_POSTURE_FROZEN` — `derive.py:296`
- §2.10 — insert — mismatch — the repair-cycle cap is listed among late constraint checks, but the `REPLACEMENT_REQUIRED` case runs ahead of the weld-log/repair-start state gates and the posture gates — `routes_weld.py:198,255`
- §3.1 — revise — ambiguity — summary tallies count rows whose status is exactly the named value (so `welded_seam_count` excludes `EXAM_SCHEDULED`/`RT_ACCEPTED`); `steel_remaining_lb` = received less allocated — `derive.py:762-772`
- §3.5 — insert — ambiguity — each `qualified_positions` entry must be a non-empty string — `routes_weld.py:31`, `validate.py:147`
- §3.5 — revise — mismatch — `continuity_expires_at_utc` "held to the second" -> base date plus whole 24-hour days, preserving time of day and fractional seconds — `util.py:73`
- §3.5 — insert — ambiguity — continuity is also re-evaluated on a qualification action — `routes_weld.py:89`
- §3.5 — insert — ambiguity — the re-evaluation is a two-way pure function of the clock (a rewind un-lapses a welder); `REVOKED` is never re-evaluated; no `version`/`updated_at` move — `derive.py:463-469`
- §3.5 — insert — ambiguity — `REVOKE` ignores `effective_date_utc` and leaves continuity fields alone — `routes_weld.py:104-106`
- §3.5 — insert — ambiguity — both action branches refresh continuity before the `LAPSED` gate, so a stale-`QUALIFIED` welder may be renewed — `routes_weld.py:89-96`
- §3.5 — insert — ambiguity — declaring a seam re-derives the host course (drops `WELDED`/`RT_ACCEPTED` to `FITTED`, reverting `SHELL_COMPLETE`); a `SPECIFIED` course is never re-derived — `routes_weld.py:162`, `derive.py:220-241`
- §3.6 — revise — mismatch — RT-window instants "compared to the second" -> compared at full supplied precision; buffer is exactly 3,600 s per side — `derive.py:679-692`
- §3.6 — insert — ambiguity — a `UT`/`MT`/`PT`/`VT` acceptance carries the seam to `RT_ACCEPTED` too, though only `RT` enters the reject-rate population — `routes_nde.py:134-146`
- §3.6 — insert — ambiguity — same for a non-RT rejection (opens a nonconformance, leaves the reject rate untouched) — `routes_nde.py:147-156`, `derive.py:437-439`
- §3.6 — insert — ambiguity — a void (and a repair re-weld) never clears or repoints `last_nde_report_id` — `routes_nde.py:183-196`

`derive.py` walked function-by-function (52 functions enumerated, from `by_created` through `tank_summary`, including `compute_course_thickness`, `recompute_posture`/`suspend_live_plans`/`restore_suspended_plans`, `rederive_steel_ledger`, `rederive_water_ledger`, `disposal_multiplier`, `surcharge_pct`, `recompute_plan_costs`, `withdrawal_cost_for`, `recompute_reject_rate`, `refresh_welder`, `settlement_envelope`, `evaluate_survey`, `evaluate_dft`, `coating_rework_cascade`, `required_clearance`, `rt_window_conflict`, `compute_in_service_schedule`). The one-foot method, settlement variants, both ledgers, the cost ladder (disposal tiers, surcharge tiers, round-then-sum order), clearance tiers, in-service schedule and DFT variants were already pinned to constant, tier boundary and rounding order — only DFT storage precision was wrong. Two no-new-mismatch adjustments: the repair-cap note is scoped to weld-log/repair-start only (NDE scheduling reports `ERR_NDE_STATE_INVALID` for the same seam state), and the DFT precision revision was checked against `routes_coating.py`.

### PASS 3 — water / coating / commissioning (24 changes: 19 ambiguity-pins, 5 mismatch-revisions; 464 lines held, +4,620 chars)

Did not re-copy; found the file at 464 lines / 128,016 chars. Changes:
- §3.7 — insert — ambiguity — `source_name` uniqueness is exact, case-sensitive whole-string comparison — `routes_water.py:42`
- §3.7 — insert — ambiguity — registration never compares `permit_expiry_utc` to the clock; a lapsed permit may be registered — `routes_water.py:40`
- §3.7 — insert — ambiguity — `fill_volume_gal` is record-only: never checked against reserved withdrawal volume, no part in cost — `routes_water.py:82,110`
- §3.7 — insert — ambiguity — `hold_hours` is a whole number of hours — `routes_water.py:85`
- §3.7 — insert — ambiguity — plan creation consults no `construction_phase`; `SHELL_COMPLETE` binds approval only — `routes_water.py:78-131`
- §3.7 — revise — **mismatch** — `previous_plan_id` is null whenever the create superseded nothing, including when the tank's earlier plan has moved past `DRAFT`/`REJECTED` (PRD said only "a tank's first plan") — `routes_water.py:96-106`
- §3.7 — insert — ambiguity — the posture gate and permit-currency check bind the `APPROVE` branch alone; state/phase gates bind both — `routes_water.py:163-168`
- §3.7 — insert — ambiguity — withdrawal window bounds are never compared to the logical clock (a wholly past window is reservable) — `routes_water.py:307-313`
- §3.7 — insert — ambiguity — `target_fill_percent` is 0–100 inclusive, outside = `ERR_INVALID_REQUEST` — `routes_water.py:185`
- §3.7 — insert — ambiguity — away from the four hold points a supplied survey need only resolve (no ownership/fill/verdict check) yet still increments the counter — `routes_water.py:201-214`
- §3.7 — revise — **mismatch** — an advance to exactly 100 reaches `FILL_HOLD` from `APPROVED` too, not only from `FILLING` — `routes_water.py:215-219`
- §3.7 — revise — **mismatch** — `settlement_survey_count >= 4` is a tally, not proof the four levels were surveyed; and it is reported ahead of the hold-period breach — `routes_water.py:241-249`
- §2.10 — revise — **mismatch** — the `ERR_PLAN_STATE_INVALID` state-gate roster also covers withdrawal reservation against a plan that accepts no further action — `routes_water.py:300`
- §3.8 — insert — ambiguity — `surface_area_sqft` is record-only; no required spot count derives from it — `routes_coating.py:29,41`
- §3.8 — insert — ambiguity — issuing a specification is gated by neither phase nor posture — `routes_coating.py:23-61`
- §3.8 — insert — ambiguity — `profile_mils` >= 0; `dew_point_spread_f` accepts any finite number (negative included), the 5.0 floor being a 409 safety check — `routes_coating.py:85-102`
- §3.8 — insert — ambiguity — `test_voltage_v` >= 0 and is stored on both holiday-test branches — `routes_coating.py:143,163-164`
- §3.9 — insert — ambiguity — design places no requirement on the host course's status, and no appurtenance operation consults `construction_phase` — `routes_final.py:26-68,86-111`
- §3.9 — insert — ambiguity — a supplied `installed_at_utc` is stored verbatim, never clock-compared — `routes_final.py:108`
- §3.9 — insert — ambiguity — `reference_number` is unconstrained free text; document rows are not resources and the recording call returns the updated package; neither create nor document recording consults the phase — `routes_final.py:161-180`, `store.py` serialize
- §3.9 — revise — **mismatch** — submission gates reordered to actual evaluation order (state/phase -> posture -> appurtenances -> documents), matching §2.10 — `routes_final.py:190-207`
- §3.9 — insert — ambiguity — on `ACCEPT` the posture gate precedes the duties check — `routes_final.py:226-231`
- §3.9 — insert — ambiguity — a remaining life under two years floors the internal interval to 0, a legitimate value — `derive.py:731`
- §3.9 — insert — ambiguity — due-date day-of-month falls back to the month's last day (29 Feb -> 28 Feb) — `util.py:81-90`

Modules: `routes_water.py` 12 edits, `routes_coating.py` 4 edits (DFT variants, prep ranking, rework cascade and `COATED` advance already pinned), `routes_final.py` 8 edits (clearance geometry, document ordering, interval formulas already pinned). Left alone as already pinned: the source-version bump asymmetry between reservation and cancellation, plan version bumps on cost recomputation, created-withdrawal at `version` 1, posture openness of source/plan/withdrawal/spec/design/package writes.

Pass 3's closing sanity check: tail still the last §5 row, 66 error rows, 66 §4 endpoint rows, 464 lines, and a difflib hunk map confirming all 32 pre-existing hunks plus its own 17 (49 total) — no sentence left mid-edit.

**Orchestrator verification:** `diff PRD_FINALIZED.md PRD_COMPLETED.md` reports the files differ with 49 hunks (so Step 9 genuinely ran and is not a byte-identical copy — the known silent-skip failure mode). All three documents have distinct md5sums. PRD_COMPLETED.md is 464 lines / 132,636 chars, retains 27 headings, 66 `ERR_` table rows, and ends on the complete final table row. Pipeline complete.

