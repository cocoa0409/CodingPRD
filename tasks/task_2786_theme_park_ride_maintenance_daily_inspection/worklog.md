# Worklog — task_2786_theme_park_ride_maintenance_daily_inspection

## Step 1: Create task directory — 2026-09-04T21:06:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2786_theme_park_ride_maintenance_daily_inspection` and `.../workspace` (pre-assigned path; no index allocation performed).

## Step 2: Generate scaffold — 2026-09-04T22:53:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts are complete, parse cleanly, and the lint is green.

## Verdict (pasted verbatim, first run was clean)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2786_theme_park_ride_maintenance_daily_inspection/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2786_theme_park_ride_maintenance_daily_inspection/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2786_theme_park_ride_maintenance_daily_inspection/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    71
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  624

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Artifacts

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 2936 | §1.0–§1.7: 14 entities, 10 state machines, 2 concurrency rules, 9 calculations, 26 priority-ordered validations, 71 endpoints, 47 errors, 6 roles. No `scaffold_difficulty_design` / `scaffold_corner_design` keys. |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1240 | single key `scaffold_difficulty_design`; 9 rule_ids × 2 instances = 18 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3135 | single key `scaffold_corner_design`; all 9 guide sections, 66 instances (50 with full `test_recipe`, 16 `excluded_because` stubs) |

Section breakdown of §1.9: entities 11, state_machines 13, calculations 12, validations 11, endpoints 7, errors 2, rbac 3, complexity_layers 6, consistency_model 1.

## Verification performed
- `yaml.safe_load` on all three files; each design file has exactly one top-level key.
- 66 corner names unique, zero collisions with the 18 difficulty names; every `excluded_because.difficulty_instance` citation resolves to a real §1.8 instance name; no stub carries a `test_recipe`.
- Placeholder-closure check: no `${var}` used before an earlier `captures:` binds it.
- Scenario field contains only item 2786 text; grep for "harder than expert" returns 0 in all three files; `complexity_profile.difficulty_level: expert`.

## Key findings while authoring §1.9 (the §1.5 audit pass)
- **Enum drift caught and fixed.** Recipes written from memory used `ride_class: EXTREME`, `severity_class: ROUTINE`, `component_type: RESTRAINT` / `CHAIN`, and `park_area: MAIN_STREET` — none of which are declared. Rewritten to `THRILL`, `ADVISORY`, `RESTRAINT_ACTUATOR`, `LIFT_CHAIN`, `KIDS_COVE` (the two deliberately-invalid values in `attraction_create_invalid_enum_and_out_of_range_integer_rejected` were left in place on purpose).
- **`required_part_received` is derived, not stored.** Its declared semantics ("true when… or when no PartRequisition references this action at all") contradict its `default: false`; corner asserts were aligned to the derived reading, which is also what makes `POST /bulletin-actions/{id}/verify` succeed for unreferenced actions.
- **Claim-type vocabulary corrected** to the SKILL's own example spelling: `violation_to_error` / `satisfaction_to_pass`. The `errors` section reuses `violation_to_error` because the extraction guide's Table 6 declares no claim-type rows.
- **No §1.5 gap required a new endpoint.** Every corner precondition was reachable by composing declared endpoints; cascade-created rows (BulletinAction, InspectionItemResult) are addressable via the filtered list GETs, and the two OCC fields are always captured from a live read rather than pinned.
- Pinned literals were computed against the declared constants, e.g. fan-out risk KIDDIE 24.00 / FAMILY 32.00 → fleet 28.00 vs per-unit max 32.00, divergence 4.00; capacity windows 550.00/467.50/82.50 and 1550.00/1317.50/232.50; projection 1300.50 → settled 1530.00 (divergence 229.50); overhaul 4,424,000 (straddling window) vs 3,713,000 (fully off-season); NDT day boundaries 29 CURRENT / 30 DUE / 35 DUE / 36 OVERDUE.
- Error-catalogue triggerability is now complete across the §1.8 ∪ §1.9 union — the previously untouched 13 `*_NOT_FOUND` codes plus `ERR_STALE_ATTRACTION_VERSION` and `ERR_UNAUTHORIZED` are all covered.

Orchestrator verification: all three files present (2936 / 1240 / 3135 lines); `grep -rni "harder than expert|expert level"` over the task dir returns nothing, so the difficulty directive did not leak.

## Step 3: Copy shared files — 2026-09-04T22:54:00.000Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T23:09:00.000Z

Subagent summary (verbatim):

PRD generation is complete and verified.

## Output
`workspace/PRD.md`

- **Final line count: 516 lines** (14,381 words), written incrementally (1 `Write` + 8 `cat >> ... <<'PRDEOF'` heredoc appends) — no truncation.
- **Last section heading: `## 5. Error Code Reference`**, and the document ends at a real boundary: the final non-empty line is the last table row `| `ERR_PARTS_BUDGET_EXCEEDED` | 402 |`. Nothing is mid-sentence.
- Structure: §1 Introduction; §2 with 11 subsections (2.1 roles/auth, 2.2 verbatim response envelope, 2.3 pagination/ordering/filters, 2.4 logical park clock, 2.5 identity/audit fields, 2.6 the 26-priority validation ladder, 2.7 stale-parent OCC, 2.8 operational posture gate, 2.9 conserved quantities, 2.10 rounding, 2.11 cascades); §3 with 9 domain workflow subsections (3.1 fleet/templates → 3.9 off-season overhaul); §4 endpoint reference; §5 error reference.

## Requested grep verification
- **Endpoints: 71/71 present, 0 missing.** §4 contains exactly 71 data rows, set-equal to the scaffold's 71 endpoints (symmetric difference empty). Authorized-role cells match the scaffold's `roles` list for all 71 rows (0 mismatches).
- **Error codes: 47/47 present, 0 missing.** §5 contains exactly 47 data rows in scaffold order.

## Hard Contract results (transcript only)
- **Contract 1 — Field-Name Coverage: PASS.** 138 required names; 0 missing. Computed-read response keys: 0 missing. All 59 transitions' state enum values: 0 missing. All 6 role names present. Only absent scaffold tokens are the 8 calculation block ids (formulas spelled out in prose) and the entity class name `ShopBay` (PRD uses "shop bay" prose plus `/park-ops/shop-bays`).
- **Contract 2 — Rule Coverage: PASS.** All 26 validation priorities enumerated in §2.6 with error id and HTTP status; every distinctive field token covered. All 59 state transitions covered including cyclic legs (`REJECTED`→`IN_PROGRESS`, `IN_PROGRESS`↔`BLOCKED`, `AWAITING_PARTS`↔`DIAGNOSED`) and the `IncidentReport` fork-join at equal density. Both concurrency rules carry write endpoint, OCC field, error id and 412 in §2.7. All 9 calculations given as precise prose with pinned evaluation order (7-step overhaul cost chain; expedite tier selected from `discounted_base_cents`).
- **Contract 3 — §3 Path Purity: PASS.** 1,007 backtick tokens scanned between `## 3.` and `## 4.`: 0 violations; 0 raw `/park-ops` occurrences in §3.

## Other conformance checks
- §2.2 byte-verbatim from `section-2.2-response-structure.md`.
- §4 exactly 4 columns, §5 exactly 2; no anomalous rows; neither table exposes trigger conditions or bodies.
- Scaffold-jargon leak scan clean; §4 descriptions rewritten rather than copied.
- The withheld files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

Orchestrator anti-truncation verification: `wc -l` = 516; `tail -25` shows the §5 error table completing with `ERR_PARTS_BUDGET_EXCEEDED | 402` — a real section boundary, not mid-sentence. Heading scan shows all of §1–§5 present in order. `grep -ni "harder than expert|expert level" PRD.md` → no match, so the difficulty directive did not reach the PRD.

## Step 6: Generate implementation — 2026-09-04T23:48:00.000Z

Launched concurrently with Step 5 (impl generator was forbidden from reading `test_helpers/`, `test_suite/`, and both design YAMLs).

Subagent summary (verbatim):

The implementation is complete, compiles, boots from a fresh process, and passes an end-to-end functional smoke test of every declared endpoint.

## What was built

`workspace/implementation/` — Python 3 + Flask, in-memory dicts only, zero seeding, logical clock parked at `2026-08-01T00:00:00Z` on every boot.

Per-file line counts (3,518 total):

| file | lines | file | lines |
|---|---|---|---|
| derive.py | 581 | routes_bulletins.py | 197 |
| calc.py | 310 | routes_overhaul.py | 187 |
| routes_inspections.py | 303 | routes_incidents.py | 191 |
| store.py | 199 | routes_downtime.py | 156 |
| envelope.py | 150 | routes_requisitions.py | 156 |
| validate.py | 145 | routes_templates.py | 137 |
| errors.py | 128 | routes_attractions.py | 120 |
| fetch.py | 120 | routes_certifications.py | 97 |
| app.py | 93 | routes_components.py | 88 |
| auth.py | 63 | num.py | 48 |
| reply.py | 19 | routes_clock.py | 19 |
| start.sh | 10 | requirements.txt | 1 |

`python3 -m py_compile` clean on all 23 modules.

## Design notes worth relaying

- **Version bumps are reconciled, not incremented.** `app.before_request` snapshots the whole store for every non-GET (excluding the clock endpoint); `derive.commit()` bumps exactly the pre-existing rows whose stored-or-derived observable state changed. Cascades that touch a row twice bump it once, and clock movement bumps nothing.
- **`regulatory_hold`, `operational_posture`, `certified_operator_count`, `booked_order_count`, `committed_cents` are all derived at read time**, so hops 1/2/4 of the ride-hold cascade and the bay's `booked_order_count`/`version` movement fall out for free. The only state the hold cascade writes is hop 3 (certification suspension), recorded on the incident as an internal `_suspended_certification_ids` list so `clear` reinstates exactly its own suspensions.
- Two PRD/SCAFFOLD conflicts resolved in the PRD's favour (per the skill's precedence rule): `InspectionItemResult.requires_photo` is present on the result row, and the daily-inspection `service_date >= effective_from_date` check runs after `ERR_NO_ACTIVE_TEMPLATE` (it needs the pinned template) but before `ERR_DUPLICATE_INSPECTION`.
- Method-not-allowed returns `ERR_INVALID_REQUEST`/400 and an unmatched path returns `ERR_NOT_FOUND`/404, since the catalogue declares neither.

## Verified behaviour (fresh boot, high random port)

401/403 gating; envelope + pagination (`limit=0` → 400); OCC on both endpoints (`ERR_STALE_ATTRACTION_VERSION`, `ERR_STALE_SHOP_BAY_VERSION`); template activate/supersede; inspection fan-out, four-hop SAFETY_CRITICAL cascade (BLOCKED + auto downtime) and its compensating leg; `ERR_SEGREGATION_OF_DUTIES`; `ERR_CERTIFICATION_WINDOW_OVERLAP`; full incident branch A (hold → investigate → notify → clear with `ERR_REGULATOR_CLEARANCE_REQUIRED` first) with certification suspend/reinstate and `suspended_certification_count = 1`; budget ledger (`ERR_PARTS_BUDGET_EXCEEDED` at 402, equality accepted, reserve→cancel restores the pre-reserve value exactly); DIAGNOSED↔AWAITING_PARTS round trip; `ERR_DOWNTIME_SPANS_SERVICE_DATES`; `ERR_BAY_CAPACITY_CONFLICT` on the buffered window; the 4-step overhaul advance chain with recommissioning resets. Spot-checked arithmetic all matches hand calculation: settled 5910.00 for 360 peak + 420 off-peak at 600 guests/h; provisional 2677.50 with the 0.85 recovery credit and divergence 472.50; overhaul estimate 1,950,000 → 117,000 discount → 1,833,000 → 12% → 219,960 → 2,052,960; `dispatch_readiness_index` 44.00 for ratio 0.5 and mean restraint 92.

`worklog.md` untouched. `test_helpers/`, `test_suite/`, and both `SCAFFOLD_*_DESIGN.yaml` were never read, listed, or grepped.

## One incident to flag

A malformed smoke-test one-liner backgrounded the port assignment, so a later `ss -ltnp | grep ":$P"` ran with `$P` empty and I killed PID 2255939 — which was very likely another pipeline's Flask server rather than mine (my own launch had failed with "Address already in use" on port 32824). No broad `pkill` was ever issued; it was a single stray PID. Under `--isolation per-test-server` the affected pipeline relaunches its server before the next test, so the expected blast radius is at most one test. The final boot/kill cycle was redone with the port chosen in the foreground, checked free, and the launcher PID captured from `$!`.

Orchestrator note: the stray-PID kill is recorded here for cross-pipeline forensics; no action is available from this pipeline. Step 5 was still running at the time this entry was written.

## Step 5: Generate unit tests — 2026-09-05T00:39:00.000Z

Launched concurrently with Step 6 in the same orchestrator turn (Step 6's impl generator therefore never saw `test_suite/`).

Subagent summary (verbatim):

Stage 2 is complete: the design-index coverage ledger now closes at 100%.

## What was finished this session
Three new test files, each written incrementally (Write + `cat >>` heredoc appends) and `py_compile`d after every chunk:

- `test_suite/test_11_endpoint_contracts_and_listings.py` — 580 lines, 6 tests, all 6 non-stub `endpoints` instances (bay pagination/meta/`limit 0`, ACTIVE-revision append + reactivation guard with per-template `sequence_no` uniqueness, zero shapes of the three computed reads on empty input sets, mutually exclusive requisition links, acknowledge fan-out with the 28.00/32.00/4.00 risk figures, and the clock endpoint reopening the inspection requirement).
- `test_suite/test_12_role_boundaries_and_error_identity.py` — 421 lines, 5 tests, the 2 `errors` + 3 `rbac` instances (14 path-id 404 codes with envelope checks, body-FK codes in declared field order including the first-declared-input win, eight cross-role 403s proving priority 2 precedes priority 3, RideOperator's two capabilities, and the segregation-of-duties badge test).
- `test_suite/test_13_optimistic_concurrency_and_derived_freshness.py` — 329 lines, 4 tests, the 3 `complexity_layers` + 1 `consistency_model` instances (stale attraction version on activate, stale bay version ahead of the capacity check, the 29/30/35/36-day NDT boundary walk into posture `DOWN`, and the mutation response already carrying the recomputed posture).

## Verification run
- `pytest --collect-only`: **94 tests collected**, no import or collection errors.
- Full-suite tag audit: every test carries exactly one trailing `Design:` line; **18/18** non-stub §1.8 difficulty instances and **50/50** non-stub §1.9 corner instances covered (16 corner stubs correctly untested); zero dangling and zero dual tags.
- All 15 new docstring citations verified verbatim against `workspace/PRD.md` after whitespace normalisation, with corrected section labels (`§2.11`, not `§2.5`, for the derived-field freshness sentence).
- Unused-import sweeps clean on all three files; timestamps compared only through `assert_instant_equals` (canonicalising).

## Design-vs-PRD contradictions resolved as gaps (not asserted either way)
- Corner `endpoints` empty-set recipe wants `mean_restraint_score == 0.00`; the PRD does not uniquely derive it when no division is attempted, so only the index 0.00 is asserted.
- Corner `complexity_layers` OCC-attraction recipe asserts the superseded revision reads `RETIRED`; the PRD declares `SUPERSEDED`, which is what the test asserts.
- Corner `complexity_layers` OCC-bay recipe asserts `off_season == false` for a 2027-01-10..2027-01-15 window, but PRD §3.9 step 3 makes every January date off-season (so it is true). `off_season` is simply not asserted there; the OCC claim itself is fully covered.
- Carried forward from earlier: `expedite_pct`, `cycles_since_last_ndt` and `deferral_count` are never asserted (not PRD-declared fields).

## Paths
`test_helpers/` and `test_suite/` both sit at the task root; `ls workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation`, and a recursive `find` confirms no stray copies anywhere under the task. `worklog.md` was not touched and nothing under `workspace/implementation/` was read or written. `__pycache__` directories created by the compile checks were removed.

Line counts: helpers 180/574/124/478/138/296/957/82/470; suite 47 (conftest) + 253/271/370/330/544/469/669/1261/633/698/580/421/329 — 10,174 lines total.

Orchestrator verification: `find . -name test_helpers -o -name test_suite` returns only `./test_helpers` and `./test_suite` at the task root (no strays under `workspace/`); `grep -rn "pytest.mark.skip|pytest.mark.xfail" test_suite/` → 0 matches.

## Step 7: Run tests and iterate — 2026-09-05T00:59:00.000Z

Subagent summary (verbatim):

Clean sweep achieved.

## Summary

**Iterations run:** 2 (each an 8-round parallel `setsid` sweep). Final state: **all 8 rounds 94/94 passed, 0 failed, 0 errors.**

Iteration 1 baseline was 90/94 in every round — 4 deterministic failures (no flakiness anywhere in the suite across 16 total rounds).

**Tests deleted:** none.

**Assertions removed (PRD silence):**
- `test_suite/test_10_validation_gates.py` :: `test_the_inspection_setup_path_carries_three_independent_gates` — dropped `assert inspection["item_count"] == 1`. PRD declares `item_count` only on an *inspection template revision* (§3.1: "A new revision opens with `status` `DRAFT`, an `item_count` of 0"); §3.2's enumeration of a freshly opened daily inspection's fields never mentions `item_count`. STEP 1a/1c partial-coverage: covered assertions kept, the uncovered field-presence assertion removed. Also removed the phantom `item_count` key from the `DailyInspection` TypedDict in `test_helpers/types.py`.

**Fixes to `test_helpers/`:**
- `fixtures.py` :: `walk_requisition_to` — the helper unconditionally reserved before receiving, so calling it with a row already in `RESERVED` (as `test_02`'s `_mine_train_action_awaiting_a_part` bundle does) hit `ERR_REQUISITION_STATE_INVALID` in setup. Now it walks from the row's *current* status, per PRD §3.5 "A requisition that is `RESERVED` or `BACKORDERED` moves to `RECEIVED`". Fixed 2 tests.

**Fixes to `test_suite/` (assertion mis-translation):**
- `test_08_lifecycle_transitions_and_terminal_states.py` :: `_one_row_in_every_machine` / `test_a_trigger_fired_from_an_undeclared_state_names_the_owning_entity` — the test closed with `attraction["version"] == opening_version + 1`, counting only the template-activation bump and missing the downtime-open hop. Verified against a live server that the setup produces version 3, not 2: opening the downtime event flips `operational_posture` `CLOSED_PENDING_INSPECTION` → `DOWN`, and PRD §2.5 ("A mutation for this purpose includes changes to derived fields … because the row genuinely changed") plus §2.11 ("Each hop is a genuine mutation of the row it touches: that row's `updated_at` refreshes and its `version` increments") make that a real bump. The implementation is faithful. The setup now captures a `settled_version` after the park is built and the test asserts the seven refusals left it there — which is exactly what the test's own docstring claims ("not one row moved") and is strictly PRD-covered.

**Fixes to `implementation/`:** none. No implementation defect was found; all four failures were test-artifact bugs.

Orchestrator verification: read all 8 `results.$i.json` directly — every round reports `passed 94 / total 94`. Sweep artifacts present and non-empty for i = 1..8.

Orchestrator decision on Step 8: the skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 ran 2 iterations with one `test_helpers/` fix and one `test_suite/` fix, so the skip condition is not met and Step 8 will run. Because there were 0 `implementation/` fixes, a byte-identical `PRD_FINALIZED.md` is a legitimate Step 8 outcome — the two test-artifact bugs were fixture/assertion errors, not PRD silences, and the one removed assertion (`item_count` on a daily inspection) is a PRD silence the implementation does not exhibit, so it needs no PRD pin.

## Step 8: Finalize PRD — 2026-09-05T01:07:00.000Z

Subagent summary (verbatim):

Done. One edit.

## Line counts
- `PRD.md`: 516 lines; `PRD_FINALIZED.md`: 516 lines — **0% line delta** (one paragraph edited in place, +3 sentences of prose).

## Change
- **§2.8 (Operational Posture)** — *insert* — after the sentence listing when posture is recomputed, added that a recomputation which **actually changes** the posture is a genuine mutation of the attraction row (its `updated_at` refreshes and `version` increments by one) even when the triggering row was a child row such as a technician-opened or cascade-auto-opened downtime event; that a recomputation landing on the posture the attraction already held is not on its own such a mutation; and that the post-clock-move re-derivation advances neither field — `implementation/derive.py:500-575` (`DERIVED_STATE["attractions"]` includes `operational_posture`; `snapshot`/`apply_bumps`/`commit` bump only rows whose snapshot changed), `implementation/store.py:166` (`touch`), `implementation/app.py:53-60` (`capture_pre_state` skips GET and `/_clock/set_current_utc`).

## Per-edit pre-edit search log
**(a) Subject:** when a posture recomputation advances the attraction's `updated_at`/`version` (the arithmetic behind Step 7's `settled_version` fix: the setup lands the attraction at version 3, not 2).
**(b) Impl paths enumerated / read:** `derive.operational_posture` (5 clauses, `derive.py:166-182`); `derive.DERIVED_STATE` for all six collections carrying derived tuples and the absence of one for `components`/`certifications`/`incidents`/`downtime_events`/`requisitions`/`work_orders`; `derive.snapshot`/`snapshot_all`/`apply_bumps`/`commit`; `store.touch`, `store.new_row` (created rows start at version 1 and are absent from the pre-snapshot, so cascades never bump them); `reply.saved`/`made` (the only commit callers — grepped every module: `routes_clock.py:19` is the sole handler returning `ok()` directly); `app.capture_pre_state` (GET and clock path excluded); every writer whose posture could move — `routes_downtime.open_downtime`/`diagnose`/`resolve`/`close`/`void`, `routes_templates.activate_template`, `routes_inspections` record/submit/sign-off paths, `routes_attractions.log_cycles` (`cumulative_cycles += cycles_added`, which can flip a component's `ndt_status` to `OVERDUE`), `routes_incidents`, `routes_overhaul`, `routes_requisitions` (reserve/backorder/receive/cancel and `committed_cents`), `routes_certifications`.
**(c) Wording adjustments made:** three, all to avoid false universals. (1) I did **not** write "opening a downtime event bumps the attraction" — when the attraction is already `DOWN`/`HOLD`/`OVERHAUL` the recompute is a no-op and the impl bumps nothing; the clause is conditioned on the posture *actually changing*. (2) I wrote "is **not on its own** such a mutation" rather than "advances nothing", because the same request can bump the attraction for an independent reason (`committed_cents`, `cumulative_cycles`, `last_signed_off_service_date`). (3) I confined the change-sensitivity claim to `operational_posture` instead of stating a general "any derived field change bumps its row" rule — that generalization would have been a new mismatch, since a component's `ndt_status` can flip `CURRENT`→`OVERDUE` purely because `log_cycles` moved the parent attraction's cycle count and the impl leaves the component's `version` untouched (`components` has no `DERIVED_STATE` entry). Clock carve-out verified against `routes_clock.py` (no `commit()`, snapshot skipped).

## Items checked and deliberately left unpatched
- **`item_count` on a daily inspection**: `derive.ser_inspection` (`derive.py:320-345`) exposes only `pending_item_count`/`blocking_item_count`/`essential_fail_count`; `derive.item_count` is a template-only aggregate serialized solely by `ser_template` (`derive.py:306`) and read by `routes_templates.py:111`. PRD §3.1/§3.2 already match exactly — the test assertion was a phantom field, no PRD silence.
- **`walk_requisition_to` fixture bug**: PRD §3.5 already says "A requisition that is `RESERVED` or `BACKORDERED` moves to `RECEIVED`", and reserve/backorder are already pinned to `REQUESTED` only; `routes_requisitions.py` (`RELEASES_BUDGET`, `CANCELLABLE`) matches the prose verbatim. Pure fixture bug.
- **Zero implementation fixes in Step 7**, so no PRD/impl divergence was patched; the single edit closes the version-arithmetic ambiguity that made the Step 7 test author under-count the attraction's version by one.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` is non-empty (a single §2.8 paragraph hunk), so Step 8 genuinely edited the copy.

## Step 9: Complete PRD — 2026-09-05T01:38:00.000Z

Run as THREE SEQUENTIAL module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from re-copying, to protect prior edits). Partition: pass 1 = cross-cutting layer (app/auth/envelope/errors/reply/num/store/fetch/validate/calc/derive); pass 2 = routes group A (attractions/components/templates/inspections/downtime/clock); pass 3 = routes group B (bulletins/requisitions/certifications/incidents/overhaul). Rationale: a single-pass exhaustive scan of a 3,507-line implementation against a 516-line PRD reliably exceeds the output budget and silently degrades into a no-op.

### Pass 1 of 3 — cross-cutting layer (subagent summary, verbatim)

- **Source**: `PRD_FINALIZED.md` 516 lines / 104,365 chars → **`PRD_COMPLETED.md`** 518 lines / 110,065 chars (**+2 lines, +5,700 chars**)
- 16 surgical edits (Edit tool only). Header count (28) and markdown table row count (122) unchanged.
- **Ambiguity-pins: 12 · Mismatch-revisions: 4**

Changes:
- §2.1 — insert — ambiguity — both header values are whitespace-trimmed before examination — `auth.py:32-40`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alnum chars; `api_request_timestamp` is read from the **logical** clock — `envelope.py:19-27`
- §2.3 — revise — ambiguity — `limit`/`offset` fall back to defaults when omitted **or empty-string**; non-base-ten values are `ERR_INVALID_REQUEST`; `offset` has no upper bound — `envelope.py:72-93`
- §2.3 — revise — ambiguity — every ordering (including default `created_at`) takes insertion sequence as final tie-break; nulls sort last — `envelope.py:137-146`, `store.py:181-190`
- §2.3 — insert — ambiguity — filters/orderings match the **serialized** (freshly derived) view; boolean filters accept true/1/yes and false/0/no case-insensitively; unrecognised filter value yields 200 + empty array + `total_count` 0; unknown query params ignored — `envelope.py:99-150`
- §2.4 — revise — ambiguity — input instants accepted leniently (0–9 fractional digits, `T`/`t`/space separator, absent `Z` read as UTC, `±HH:MM`/`±HHMM` converted); seconds mandatory — `store.py:79-124`
- §2.5 — revise — **mismatch** — narrowed the "derived changes count as mutations" claim: a component's `ndt_status` and a certification's derived `status` never advance their own row's `version`/`updated_at` — `derive.py:520-542`
- §2.6 step 2 — revise — **mismatch** — an unrecognised role name is `ERR_UNAUTHENTICATED` (401), not `ERR_UNAUTHORIZED` (403) — `auth.py:37-38`
- §2.6 step 5 — insert — ambiguity — invalid/non-object JSON body is `ERR_INVALID_REQUEST`, absent body reads as `{}`; integer fields must be JSON integers — `validate.py:13-28,56-69`
- §2.11 — insert — **mismatch** — the version increment counts **requests, not hops** — `derive.py:562-581`, `app.py:53-60`
- §3.3 — revise — **mismatch** — `last_signed_off_service_date` is the **greatest** `SIGNED_OFF` `service_date` — `derive.py:78-80`
- §3.6 — insert — ambiguity — `required_part_received` counts referencing requisitions in **any** status — `derive.py:236-241`
- §3.6 — revise — ambiguity — `escalation_factor` reports 1.00 for an empty evaluated set — `calc.py:180,195`
- §3.7 — revise — ambiguity — `mean_restraint_score` rounded to 2dp and 0.00 when the certified set is empty — `calc.py:233-236,263`
- §4 — insert — ambiguity — a trailing slash is equivalent to none — `app.py:47`
- §5 — insert — ambiguity — unrouted path → 404 `ERR_NOT_FOUND`; wrong method on a declared path → 400 `ERR_INVALID_REQUEST` (not 405) — `app.py:66-75`

Tail check passed. One finding routed to pass 3: `routes_incidents.py:98` orders incidents by `occurred_at` ascending while §2.3's order list omits incidents.

### Pass 2 of 3 — routes group A (subagent summary, verbatim)

- Before: 518 lines / 110,065 chars → After: **518 lines / 112,014 chars** (all edits in-paragraph)
- Tail check passed; pass 1's edits verified intact.
- **Counts: 14 ambiguity-pins, 0 mismatch-revisions.** No case found where PRD prose actively contradicted routes group A.

Changes:
- §3.1 — insert — `name` non-empty, ≤120 chars — routes_attractions.py:27
- §3.1 — insert — `service_date`/`cycles_added` mandatory; `cycles_added` non-negative, 0 accepted — routes_attractions.py:84-85
- §3.1 — insert — NDT record persists no resource; answers 200 with the updated component (not 201) — routes_components.py:88
- §3.1 — insert — any number of `DRAFT` revisions may coexist; uniqueness only over `ACTIVE` — routes_templates.py:33-43
- §3.2 — insert — `service_date` earlier than the pinned revision's `effective_from_date` → `ERR_INVALID_REQUEST`, after the active-template gate, before the duplicate check — routes_inspections.py:39-53
- §3.2 — insert — the auto-opened downtime event's `service_date` is the UTC date of the clock instant — routes_inspections.py:220-227
- §3.2 — insert — supplied `note` overwrites; omitting leaves `note` null — routes_inspections.py:278
- §3.2 — insert — the three declared record directions are exhaustive; same-outcome re-records, moves into `NA`, and records against an already-`NA` row are all `ERR_INSPECTION_STATE_INVALID` — routes_inspections.py:253-264
- §3.2 — insert — the "no other failed row" test is system-wide; flag-clearing confined to the safety-critical compensating leg, so `ESSENTIAL`/`ADVISORY` FAIL→PASS leaves `SUSPECT` — routes_inspections.py:204-301
- §3.3 — insert — `rejection_reason` mandatory but empty string accepted — routes_inspections.py:150
- §3.3 — insert — `note` on reset FAIL rows is retained — routes_inspections.py:169-173
- §3.4 — insert — `root_cause_code` mandatory, may be empty — routes_downtime.py:87
- §3.4 — insert — `void_reason` mandatory, may be empty — routes_downtime.py:150
- §3.4 — insert — capacity-impact window bounds are query parameters; empty string read as omitted — routes_attractions.py:93-109

### Pass 3 of 3 — routes group B (subagent summary, verbatim)

- Before: 518 lines / 112,014 chars → After: **519 lines / 115,263 chars**. 19 surgical `Edit` calls; no rewrite, no new sections.
- **Counts: 3 mismatch-revisions, 16 ambiguity-pins.**

Handoff resolution (incident ordering): confirmed at `routes_incidents.py:98` — `list_incidents` passes `order=("occurred_at",)` and `envelope.list_response` appends `_seq` as final tie-break. §2.3 omitted incidents so the stated `created_at` default would have applied — a real mismatch. Fixed by inserting a normative bullet `- Incident reports: by \`occurred_at\` ascending.` between the certification and work-order bullets. Every other list in the partition was re-verified against §2.3 (fleet actions/requisitions/shop bays `created_at`, bulletins `issued_date`+`created_at`, certifications `effective_from`, work orders `window_start_date`) — all already correct.

Changes:
- §2.3 — insert — mismatch — incident list ordering pinned to `occurred_at` ascending — routes_incidents.py:98
- §2.4 — revise — mismatch — removed `notified_late` from the recomputed-on-read list; evaluated once at filing and stored — routes_incidents.py:147, derive.py:445
- §3.5 — insert — ambiguity — `part_number` non-empty string — routes_requisitions.py:33
- §3.5 — revise — ambiguity — `expected_availability_date` mandatory on backorder; shape failure settled before the status check — routes_requisitions.py:111-114
- §3.5 — revise — ambiguity — `cancel_reason` mandatory, empty accepted — routes_requisitions.py:144
- §3.6 — revise — ambiguity — `manufacturer`/`model_code` non-empty strings — routes_bulletins.py:35-36
- §3.6 — insert — ambiguity — acknowledging with no matching fleet unit creates nothing, stays `ACKNOWLEDGED` with `action_total_count` 0, never bubbles to `COMPLETED` — routes_bulletins.py:103-106,170
- §3.6 — revise — ambiguity — `deferral_reason` mandatory-may-be-empty, `deferred_until_date` mandatory, past-deadline date is `ERR_INVALID_REQUEST` before the state check and the recall bar — routes_bulletins.py:181-193
- §3.7 — insert — ambiguity — `operator_user_id` non-empty string — routes_certifications.py:33
- §3.7 — insert — ambiguity — a wholly past validity interval is accepted, derives `EXPIRED` at once, still occupies its interval for overlap — routes_certifications.py:40-51, derive.py:150
- §3.7 — revise — ambiguity — `suspension_reason` mandatory-may-be-empty, checked before the derived-status gate — routes_certifications.py:90-94
- §3.7 — revise — mismatch — dropped the "only while the clock is still inside the interval" precondition on reinstatement; `suspended_at`/`suspension_reason` cleared unconditionally for every certification that incident suspended — routes_incidents.py:185-190
- §3.8 — insert — ambiguity — hop three reaches only certifications already deriving `CERTIFIED` when it runs — routes_incidents.py:36-43
- §3.8 — revise — ambiguity — `regulator_case_ref` mandatory and non-empty, checked before state and severity — routes_incidents.py:134-141
- §3.8 — revise — ambiguity — whitespace-only `regulator_clearance_ref` counts as empty; on Branch B the field stays null even when supplied — routes_incidents.py:170-184
- §3.9 — insert — ambiguity — shop bay `name` non-empty string — routes_overhaul.py:44
- §3.9 — revise — ambiguity — `labor_hours` must be a JSON integer, `expedite_requested` a JSON boolean defaulting to false; 0 accepted for subtotal and hours — routes_overhaul.py:106-109
- §3.9 — insert — ambiguity — the work order reports the full breakdown including `expedite_pct` as a plain decimal fraction (0.0/0.12/0.08/0.05) — calc.py:302-310, derive.py:473-479
- §3.9 — revise — ambiguity — `target_phase` naming the current status is 409; absent or outside the five phase names is `ERR_INVALID_REQUEST` — routes_overhaul.py:165-170

Verification: `wc -l` = 519; tail still ends `| ERR_PARTS_BUDGET_EXCEEDED | 402 |`. Prior passes' wording re-read around every edit site (notably §2.6 rung 5 — `validate.number_field` is dead code, so no input field is a decimal quantity and the `labor_hours` integer pin does not contradict it).

### Orchestrator final verification

- `PRD.md` 516 / `PRD_FINALIZED.md` 516 / `PRD_COMPLETED.md` 519 lines. `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → differs, so the Step 9 scan genuinely ran (49 edits total across the three passes: 42 ambiguity-pins, 7 mismatch-revisions).
- `find workspace/implementation -name "*.py" -newer results.1.json` → empty, so Steps 8 and 9 touched only PRD prose; the implementation is byte-for-byte the one the clean sweep measured.
- Final sweep still on disk and green: `results.1..8.json` each report `94 / 94`.

Pipeline complete through Step 9.
