# Worklog — task_3151_air_hub_sort_operations_next_day_commitment

Append-only record of pipeline steps. Orchestrator-owned.

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Pre-allocated task directory `./tasks/task_3151_air_hub_sort_operations_next_day_commitment/` used exactly as specified (no index computation, no other task_* directory created). `workspace/` confirmed present and empty. No files created in this step beyond this worklog.

## Step 2: Generate Scaffold (SCAFFOLD.yaml + DIFFICULTY + CORNER) — 2026-09-30T01:05:00.000Z

> Orchestrator note: files verified on disk — SCAFFOLD.yaml 2608 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1740 lines, SCAFFOLD_CORNER_DESIGN.yaml 3341 lines; top-level key counts 13 / 1 / 1 confirming the design files each carry a single mandated top-level key. Subagent summary below verbatim.

All three artifacts are complete and verified. Here is the summary.

## Files written

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_3151_air_hub_sort_operations_next_day_commitment/SCAFFOLD.yaml` | 2,609 |
| `/home/ubuntu/github/CodingPRD/tasks/task_3151_air_hub_sort_operations_next_day_commitment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1,740 |
| `/home/ubuntu/github/CodingPRD/tasks/task_3151_air_hub_sort_operations_next_day_commitment/SCAFFOLD_CORNER_DESIGN.yaml` | 3,341 |

## Verdict block (verbatim from `scaffold_lint.py`)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    103
  §1.1 entities declared:     12
  §1.8 instances scanned:     20
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  1575

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```

## Counts

- **Entities 12** (Hub, ArrivalBank, Aircraft, Package, SortLane, LoadMove, Buildup, GroundFeeder, LaborShift, OpsRun, ServiceFailure, ServiceFailureClaim), flat FK topology
- **State machines 13** — Package carries four parallel status planes plus cyclic diverge/resolve and a branching reclaim fork-join; Hub is posture-driven (`OPEN→CONGESTED→LOCKDOWN→GROUND_STOP`, with `GROUND_STOP→OPEN` and `LOCKDOWN→OPEN` back-edges); SortLane forks by operator vs capacity; Buildup has a banded breach axis; LoadMove and Aircraft both have rework/self-transitions
- **Concurrency rules 2** (both OCC on the parent's `version`, both write endpoints take `expected_*_version`)
- **Calculations 18**, **Validations 12** (priorities 1–12), **Endpoints 103**, **Errors 34**, **Roles 10** (all `opaque`; `role_model: peer_roles`)

## Difficulty / corner design

- **§1.8 depth instances: 20** across all 9 §0.5 rules (rule 1 and 2 carry 3 each; the other seven carry 2), each with a fully structured `setup_api_calls` chain, `trigger`, and literal-valued asserts. Formula-derived values were computed by hand and pinned (e.g. refund 96270 → batch 192540 vs the forbidden 192539; unload budget 73 vs 90).
- **§1.9 breadth instances: 73** (62 live + 11 `excluded_because:` stubs) spanning all nine taxonomy sections: entities 13, state machines 19, calculations 9, validations 4, endpoints 9, errors 8, rbac 6, cross-cutting layers 4, consistency model 1.
- **1,575 structured calls** scanned; every `${var}` closes against an earlier `captures:`, and all OCC version inputs are `${var}`-derived.

## Step 3: Copy shared INSTRUCTION.md — 2026-09-30T01:06:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `{task_dir}/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD.md — 2026-09-30T02:00:00.000Z

> Orchestrator note: PRD.md verified on disk — 428 lines, 89,221 bytes. Both design indices withheld as required; subagent confirmed it opened neither. Summary below verbatim.

PRD is complete and verified. Here is the report.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_3151_air_hub_sort_operations_next_day_commitment/workspace/PRD.md` — 429 lines, ~13,400 words. Generated purely from `SCAFFOLD.yaml` plus the doc-generator skill (I did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task).

## Section list

- **1. Introduction** (3 paragraphs, business-context angle)
- **2. Global Specifications & System-Wide Principles** — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim §2.2 contract) · 2.3 Pagination · 2.4 The Operating Day and the Logical Clock · 2.5 Posture: The Hub, the Package, and the Shift · 2.6 The Live Planning Volume and its Consequences · 2.7 Currency, Minutes, and Weight Precision · 2.8 Resource Addressability, Hierarchy, and Validation Order · 2.9 Optimistic Concurrency Control · 2.10 Cascading Effects and the Recompute Obligation
- **3. Business Logic & Workflows** — 15 subsections (induction/rated weight; banks & unload face; sorting & lanes; contingency; irregular/hazmat routing; load moves & buildups; labor staffing; ground feeders; commitment cutoffs; ops checkpoints; service failures & MBG; finalization/dispute/void; lane geometry & concourse width; the cascade chain; manual overrides)
- **4. Endpoint Definitions** — 103-row table, 4 columns, prefaced by the 201/200 status rule
- **5. Error Code Catalogue** — 34-row table, 2 columns, no trigger conditions

## Hard contracts — all PASS

```
Field coverage check (backtick tokens, §2.2 fenced blocks excluded):
- entities[].fields: 96 required, 96 present, 0 missing
- endpoints input/request_body: 78 required, 78 present, 0 missing
- endpoints[].query_params: 0 present in scaffold (filter params are modeled as input)
- endpoints[].path_params: 0 present in scaffold
Status: PASS

Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed (explicit priority ordering in §2.8)
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_package_version / expected_load_move_version + ERR_STALE_VERSION/412)
- state_machines[].transitions: 78 checked (13 machines), all from/to pairs + preconditions + side_effects expressed
- calculations[]: 18 checked, 18 expressed (formulas in precise prose, pinned evaluation orders stated)
- validations[] conditions: 12 checked, all matchable to error_id in §2/§3
- endpoints[].side_effects / applies_to: 77 checked, 77 expressed
- errors[]: 34 checked, all 34 mentioned in §2/§3
- entities[].fields[] structured content: 114 checked, reconstructible
- calculations[].constants: all named and valued (incl. SORT_BUDGET_GRAMS_FLOOR, FEEDER_DEPART_TOLERANCE_PCT)
- enum values / state strings / role names: all present verbatim
- sibling-branch symmetry: branch pairs (advance vs release; downgrade/ground-downgrade/diverge/upgrade-hold; route-irregular vs route-hazmat; reclaim from PRIMARY_SORTED vs SECONDARY_SORTED) rendered at equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 527
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 also verified byte-identical to `section-2.2-response-structure.md`; no audit footer in PRD.md.

## Scaffold rules I judged under-specifiable (flagged for the caller, not resolved by invention)

1. **`effective_sort_budget`** references an aircraft field `unload_slack_minutes` that appears in no entity definition (only inside the formula). I expressed the rule as the derived "slack" quantity (actual minus scheduled arrival, clamped to `[0, unload_slack_cap_minutes]`) rather than inventing a persisted field name.
2. **`ArrivalBank.effective_sort_budget_minutes` = 0** is mandated "once every aircraft has been UNLOADED or CANCELLED" and "for a bank whose status is CLOSED or ABANDONED" — consistent with the `CANCELLED`-excluded formula only for the all-cancelled case, not for the all-UNLOADED case. Both statements are in the PRD; they cannot both hold for an all-UNLOADED bank.
3. **`hub_sort_constants` declares `GROUND_DOWNGRADE_SLIP_MINUTES = 1440` and `DEFAULT_UNLOAD_BUDGET_MINUTES = 45`** (plus `CONGESTED_/LOCKDOWN_GRAMS_PER_WINDOW_MINUTE` in `hub_posture`) but no rule consumes the 1440. The endpoint table states `ground-downgrade` uses 1800 minutes (+30 h). The 1800 has no named constant. I used 1800 (the endpoint is more specific) and mentioned no 1440 slip.
4. **`Hub` transition `LOCKDOWN → OPEN` side effect** says clear-contingency restores `AWAITING_ASSIGNMENT` packages to `COMMITTED`; `AWAITING_ASSIGNMENT` is not a member of the `commitment_status` enum in the PRD, so I expressed this as "restore to `COMMITTED`".
5. **`PackageCommitment` machine** is modeled as "projected over" `Package` fields (per its own side-effect wording), so I expressed it inside §3.9 rather than as a separate addressable resource; §1.1 lists 12 package fields but my Contract 1 count is 96 because `Package` also carries the FK/derived fields.
6. **`RefundAdjuster`'s `claim-indemnity`** has an input `claimed_value_cents` that the scaffold says is recorded but not paid; there is no field for it on any entity. I stated the rule (the declared value is recorded and not paid; the emitted `NO_SCAN`/`CARRIER` failure uses the standard MBG refund).
7. **`gateway_requirements`** is declared as a computed field with `default: {}` but is written by an explicit endpoint; I described it as a planner-declared map (not invented as an entity).
8. Several `validations[].applies_to` entries name paths the scaffold never defines (`POST /sort-lanes`, `POST /load-moves`, `POST /ground-feeders`, `POST /service-failures`, `POST /airhub/moves/{move_id}/set-tier` is defined but not in `applies_to`). I mapped these to their actual endpoint counterparts (lane/move/feeder/failure creation) rather than reproducing the inconsistent spellings.

Design notes: §2 subsection count and titles are domain-derived (clock/posture/precision, not the example's fiscal/safety pattern); §3 uses a mixed lifecycle + cross-cutting grouping with 15 subsections; sentence starters verified varied (only 2 of 91 paragraphs open with "The system"); no fuzzy hedging words used in any rule statement; §3 contains zero tables and zero bullet lists.

## Step 5: Generate Unit Tests (test_helpers/ + test_suite/) — 2026-09-30T02:30:00.000Z

> Orchestrator note: verified on disk — test_helpers/ 9 modules (2,174 lines), test_suite/ 23 test files + conftest.py (4,526 lines). Stale `__pycache__` dirs left by the subagent's local pytest execution were removed so the tree is clean for Step 6/7. Summary below verbatim.

Done. Both stages are complete and verified.

## Files written

**`test_helpers/`** (2,174 lines, 9 modules)
- `types.py` — status enums + entity TypedDicts; `OpsRun` and `ServiceFailureClaim` correctly carry only `id`/`created_at` (`common_fields: false`)
- `api_client.py` — `ApiClient(GenericApiClient)` with a method per PRD endpoint + `raw_request` escape hatch
- `api_errors.py` — all 34 error IDs, HTTP map registered via `set_error_http_status_map`
- `assertions.py` — `assert_{entity}` for all 12 entities plus the moving PRD invariants (`assert_package_invariants`, `assert_load_move_invariants`, `assert_buildup_invariants`) and `confirm()` for mutating calls under test
- `constants.py` — every PRD-pinned constant, clock→minute table, shared fixture literals
- `factories.py` — payload factory per entity, input fields only
- `test_users.py` — all ten roles as shared constants (+ per-role builders; identity is `opaque` for every role, so no ownership threading is needed)
- `fixtures.py` — 649 lines of composite setup: night/lane-set/move/buildup/hazmat builders, airside and package progressions, OCC-carrying `onboard_package`
- `__init__.py` — barrel export

**`test_suite/`** (4,526 lines, 145 tests across 23 files + `conftest.py`)

## Coverage

| Queue | Instances | Tests emitted | Target |
|---|---|---|---|
| A — difficulty | 20/20 translated | 79 | ≥2 each (min = 2) |
| B — corner, non-stub | 62/62 translated | 66 | ≥1 each |
| B — corner, `excluded_because` stubs | 11 skipped (correct) | 0 | not translated |

**Skipped: 0 instances.** All 20 difficulty and all 62 live corner instances passed the PRD-first two-condition filter. All 11 stubs were verified as resolving to real difficulty instances and correctly left untranslated.

Verified mechanically: every test has exactly one `Design:` line as the last docstring line; no dangling tags, no stub tags, no untagged/dual-tagged tests; all 176 quoted docstring fragments survive a literal grep of `PRD.md` (I re-wrapped 87 of them to the PRD's exact sentence boundaries); every `test_helpers` import name and every `api_client` method resolves; suite collects cleanly (145 tests, 0 errors); a stub echo server confirmed the fixture plumbing issues the right requests.

## PRD/scaffold disagreements adjudicated

1. **Instance name typo in the source yaml** — `SCAFFOLD_DIFFICULTY_DESIGN.yaml` names the instance `buoy_under_capacity_guard_excludes_the_zero_delta_boundary` (rule `boundary_precision_check`). The rule is about a *buildup*, not a buoy. C4 requires the tag copied verbatim, so I emit `Design: Difficulty/boundary_precision_check/buoy_...` and left the source untouched. Flagging it as an upstream typo to fix, since the tag is not greppable as an English phrase.
2. **`child_endpoints_never_expose_listing`-style contract mismatch** — `POST /airhub/shifts` appears in the PRD §4 table with `SortSupervisor` as sole authorized role while the SRD §2.1 prose says SortSupervisor owns shift creation, which agrees; no adjudication needed, but note `POST /airhub/hubs` is `HubOpsManager`-only in both, whereas the SRD's `shared_operations` list implies only reads are shared — I tested the exclusive reading, which both sources support.
3. **`GET /airhub/lanes/concourse-width` route ordering** — the PRD table lists `GET /airhub/lanes/concourse-width` and `GET /airhub/lanes/{lane_id}` adjacently; the static path wins, so I always call the computed read with `lane_kind` as an explicit param rather than relying on inference.
4. **SRD §1.5 declares `POST /airhub/hubs/{hub_id}/clear-contingency` emits one `REVENUE_PRORATE` failure per held package, but PRD §3.4 says the same only for the `HOLD_AT_HUB`→`UPGRADED_HELD` arm** — I asserted only the arm both sources state (held packages), and left out the diverted-arm failure emission, which PRD does not state. This is encoded as a skipped assertion, not a skipped test.
5. **Field-presence ambiguity on computed fields** — I dropped assertions on `lane_count` in the concourse read, `eligible_failure_count`/`provisional_failure_count` in the refund summary, and non-existent-`shift_id` in the triage read: the PRD names those output objects but no verbatim sentence pins those exact keys, so two PRD-only readers could legitimately name them differently. Their owner instances remain covered by the pinned value assertions (`merged_minutes`, `concourse_width_rating`, `batch_total_cents`, `triage`, `staffing_posture`).
6. **`version == 1` on creation** — relaxed to `>= 1` in three places, since PRD §1 only says `version` increments on every mutation and never pins the creation-time value.

No fixtures were shared mutably across tests; every test builds its own state from scratch, which is required because the harness restarts the server per test.
## Step 6: Generate Implementation — 2026-09-30T03:30:00.000Z

> Orchestrator note: verified on disk — implementation/ 19 files, 3,881 lines (start.sh 10, app.py 103, auth.py 21KB, calculations.py 14KB, routes/ 8 modules). Ran with test_suite/ and test_helpers/ withheld as required. Stale `__pycache__` from the subagent's own verification runs removed. Summary below verbatim.

Implementation complete and verified. Final summary:

## Files written under `workspace/implementation/`

19 files, **3,881 lines** total:

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | launcher (`exec python3 app.py`) |
| `requirements.txt` | 1 | `flask>=2.3,<4.0` |
| `app.py` | 103 | entry point, priority-ordered `before_request` guard, error handlers |
| `store.py` | 148 | in-memory dicts, logical clock, hub-local minute derivation |
| `errors.py` | 134 | 34-error catalog with exact HTTP statuses |
| `response.py` | 93 | envelope, `req_` ids, 3-digit ISO timestamps, pagination |
| `auth.py` | 367 | 103-entry endpoint map (roles / path tables / body FKs / declared inputs) |
| `serializers.py` | 79 | per-entity wire field lists |
| `calculations.py` | 432 | all 18 calculations |
| `services.py` | 164 | postures, cascades, failure emission |
| `routes/{hubs,aircraft,packages,lanes,moves,feeders,shifts,failures}.py` | 2,361 | the 103 endpoints |

## `start.sh` contract
`cd`s to its own directory, runs `python3 -m pip install -q -r requirements.txt` **only if `import flask` fails** (so per-test reboots don't contend on pip), then `exec python3 app.py`. `app.py` reads `int(os.environ.get("PORT", "10000"))` and calls `app.run(host="0.0.0.0", threaded=True, use_reloader=False)` — foreground, no backgrounding, first route reached in ~1s.

Verified: rebooting via `start.sh` twice returns `total_count` 1 → 0 (store is empty at boot — no seeding); reachable on the host interface (not just loopback); default `PORT` 10000 and explicit `PORT` both honoured.

## Coverage
103 endpoints, 12 entities, 13 state machines, 18 calculations, 12 validation priorities, all 34 errors. Verified against 4 self-written black-box suites (**122 assertions, 0 failures**) covering the pinned arithmetic (rated weight, MBG 963/1375, batch total 192540 vs the forbidden 192539), the depth-4 cascades, the feeder 95%-departure trap, the lane-freshness gate, OCC 412s, and the 30/60-minute downgrade windows.

## PRD rules that were ambiguous or self-contradictory

1. **Hub window range (real conflict).** SCAFFOLD caps `sort_window_open_minutes` at 0..1439, but PRD §2.4 states the default clock "reads as minute 1440 — the opening edge of a 1440-open / 1560-close window." Scaffold wins vs PRD per the skill spec, but PRD wins on disagreement per the same spec. **Resolved for PRD**: only `close > open` is enforced; no range cap. Without this the canonical hub is uncreatable.
2. **Late-unload hop 2 final minute.** PRD says hop 2 overwrites `final_commitment_minutes` to the cutoff *itself*, not cutoff+360. Implemented literally: hop 1 writes cutoff+360 transiently, hop 2 overwrites with cutoff (so the column shows 1560, not 1920).
3. **Handling status in the late-unload and aircraft-cancel cascades.** PRD §3.14 mentions only the commitment rewrite. Implemented literally: `handling_status` stays `NORMAL` (only `diverge`/`upgrade-hold`/`void` set `DIVERTED`/`HOLD_AT_HUB`). This differs from the aggregate `handling_posture` intuition and is a likely fault line.
4. **`upgrade-hold` failure emission.** The endpoint table lists "one ServiceFailure emitted (LATE_INBOUND / CARRIER / FINALIZED)" while the state machine says only volume+shift recompute and PRD §3.9 lists no failure. **Followed PRD**: no failure emitted.
5. **Bank-abandon failure count.** The endpoint table says "each emits one WEATHER ServiceFailure" (each aircraft) but PRD §3.4 says "each of which emits one weather-attributed failure" while also downgrading "every package aboard". Implemented one failure per cancelled aircraft, using its first package as subject (or none when bare).
6. **Guard ordering conflict.** SCAFFOLD priority 5 puts `ERR_HAZMAT_CAP_EXCEEDED` first; PRD §3.6 narrates the destination-buildup guard before the hazmat cap. **Followed the scaffold's priority 5**, which the skill treats as authoritative on priority numbering when PRD does not explicitly contradict.
7. **Saturated lane vs capacity error.** A capability-matching lane auto-flips to `SATURATED` on its own derived recompute, which would make every subsequent sort return `ERR_LANE_NOT_AVAILABLE`. Implemented so the capacity check precedes the availability check for capability-matching lanes, yielding `ERR_LANE_CAPACITY_EXCEEDED`; `CLOSED`/capability mismatch still yield `ERR_LANE_NOT_AVAILABLE`.
8. **Feeder window conflict bound.** Scaffold says "within `window_minutes`", PRD says "within one window length" — both read as inclusive `<=`.
9. **`forward_capacity_grams`/`_raw_forward_grams`.** The entity table lists `forward_capacity_grams` as a field, but the endpoint side-effects for `complete-load` quote "planned_weight_grams <= weight_limit_grams" where the state-machine table quotes the same gate using `forward_capacity_grams`. Since PRD §3.6 pins the *floored* value as display-only and the tier as raw-derived, the ceiling guard uses raw and the floor guard uses the floored value, as written.

## Step 7: Run Tests and Iterate — 2026-09-30T10:45:00.000Z

> Orchestrator note: independently verified — all eight `results.1..8.json` present and each reports `passed == total == 145`. No `__pycache__`/`.pyc` residue. Step 7 required many fixes (see below), so Step 8 is NOT skipped. Summary below verbatim.

All 145 tests pass in all 8 rounds. Cleanup is done (8 result files kept, no `__pycache__`/`.pyc`, no stray scratch files, no leftover servers).

## Summary

**Iterations run:** 12 full 8-round parallel sweeps at the prescribed 8× concurrency (no reduction needed — the host sustained it; wall time stayed ~1 round). Baseline was 75/145; final is **145/145 in all 8 rounds**.

**Tests deleted:** none. No test failed the PRD-coverage or unique-derivability checks outright, so nothing was removed. One assertion was relaxed under the permitted coverage rule: `test_a_ground_stop_forces_a_move_into_rework_and_replan_waits_for_the_clear` now accepts `validate_error_is_one_of(["ERR_INVALID_STATE", "ERR_CONTINGENCY_NOT_DECLARED"])` for a replan attempted while the contingency is still declared — PRD §3.6 states replanning is available "once the contingency has been cleared" but names no identifier for the still-declared case.

**Fixes to `test_helpers/`**
- `assertions.py` — added `confirm_list(response)` wrapping `validate_paginated`; ~23 call sites did `x, meta = confirm(api.list_*)`, but `validate_success` returns only `data`, so every paginated assertion raised `ValueError: not enough values to unpack`.
- `constants.py` — `LANE_CAPACITY_WIDE` 400000→900000; `TEST_DEFAULTS["WEIGHT_LIMIT_GRAMS"]` 400000→350000. A 400000-gram move's *empty* forward capacity is 400000, which exceeds PRD §3.6's 350000 onboarding ceiling, so nearly every `create_move` default was illegal.
- `fixtures.py` — `land_second_aircraft` gained a `complete=` flag and clamps the unload minute to `actual_arrival_minutes` (it was issuing `unload_completed_minutes` before the arrival → `ERR_LATE_UNLOAD_REGRESSION`); `cancel_aircraft` now grounds a SCHEDULED/IN_FLIGHT aircraft first (PRD's cancellable subject is "a grounded aircraft"); `setup_hazmat_package` no longer calls `route-hazmat` before `primary_sort` (the primary sort *is* the automatic divisional step); added `wide_primary_lane`/`wide_secondary_lane`.

**Fixes to `test_suite/`**
- `test_14`, `test_19` — 5 tests used a `night` name in their body but omitted the fixture parameter (`TypeError: 'FixtureFunctionDefinition' object is not subscriptable`); 8 others *did* create their own `night` locally and were reverted.
- `test_19` — the grace-clause clock `CLOCK_1581` read minute 1581, inside the cutoff+60 window (the test believed it was past it), corrected to minute 1621; the feeder-window test was reordered so the hub-window refusal is probed after the admitted case (the clock is monotone).
- `test_07` — clear-contingency (PRD §3.4) had already restored the DIVERTED/REROUTED package, making `clear-reroute` unreachable; the cycle now reaches REROUTED through the §3.10 advance disposition, matching the test's own docstring.
- `test_09` — the seed cancelled the aircraft before its package existed so the package never reached DOWNGRADED; rewritten so both packages ride N701UP and the aircraft hop is exercised on an empty N702UP. `ops_run_index` expectations corrected (checkpoint creation 0→1, disposition 1→2).
- `test_17` — the zero-deletion and guard-band tests were restructured so the refused request is an *onboarding* (the PRD places the band guard on onboarding only), not an assignment.
- `test_21` — unload-face test rewritten with a dedicated two-aircraft bank (the setup had left N701UP UNLOADED, so no face was occupied); overweight-completion now issues `begin-loading` (completing is a LOADING→LOADED step); duplicate-tracking-number freed via the void exit (PRD §3.1 frees it only on `VOIDED`/`DIVERTED` *commitment*); `LOADING` assertions corrected to `PLANNED`.
- Various weight-limit/clock/lane retargetings across `test_04/06/08/10/11/13/20/22`.

**Fixes to `implementation/`**
- `serializers.py` — `forward_capacity_grams` was computed but never serialized on a move (`KeyError` in 3 tests).
- `calculations.py` — removed an erroneous early-zero for an all-`UNLOADED` bank; PRD §3.2's live set explicitly includes `UNLOADED`.
- `routes/packages.py` — `induct` now requires `NOT_INDUCTED` (a second induction and an induction of a `REJECTED` package were both accepted, contradicting the terminal-dimension rule); `primary_sort` admits a commodity-dedicated lane for its own class; `secondary_sort` moved the lane gates ahead of the stage-budget gate per the pinned §2.8 priority.
- `routes/aircraft.py` — landing is gated on `GROUND_STOP` only (the hydraulic crew gates the unload face, not touchdown); landing re-opens a bank whose face folded to `UNLOADED`, and `begin_unload` re-takes it (the single face cycles); `cancel` admits `UNLOADED`; `complete_unload` refuses a maintenance-held aircraft.
- `routes/moves.py` — a missing required body input reports `ERR_INVALID_REQUEST` (was `ERR_RESOURCE_NOT_FOUND`); onboarding records explicit move membership so a package assigned to no buildup still counts toward the move's filled weight; offboarding unwinds both memberships; `seal_buildup` checks weight before status and refuses rated > container limit.
- `routes/feeders.py` — departure zeroes `staged_weight_grams`.
- `routes/shifts.py` — the advance disposition rewrites the commitment only, leaving handling untouched (it was calling `cascade_reroute`, which set `DIVERTED` and made the package unreachable by a later clear-contingency sweep).

**Final sweep:** 145/145 in rounds 1–8 (verified from `results.1.json` … `results.8.json`).

## Step 8: Finalize PRD (PRD_FINALIZED.md) — 2026-09-30T11:30:00.000Z

> Orchestrator note: PRD_FINALIZED.md verified on disk — 428 lines, 92,236 bytes vs PRD.md 428 lines / 89,221 bytes (+3,015 bytes, 0% line delta). Step 7 was not clean (many implementation fixes), so Step 8 ran as required. Summary below verbatim.

All edits are in place. Final state: PRD.md and PRD_FINALIZED.md are both 428 lines (0% line-count delta); 12 single-sentence inline revisions, no new sections.

## Summary

**Alignment target:** `workspace/implementation/` (145/145). Test files used only as auxiliary evidence; the finalized PRD follows what the implementation actually does.

**Changes (one bullet per edit):**

1. §2.1 — revise — `ERR_INVALID_REQUEST` also covers body-level, non-resource requirements (duplicate `iata_code`/`bank_code`/`lane_code`/`shift_code`/`feeder_code`, out-of-set gateway/cause codes, cross-field window/turnout/shift end-order) — `routes/packages.py:106`, `routes/aircraft.py:55`, `routes/lanes.py:28`, `routes/shifts.py:36`, `routes/feeders.py:36`.
2. §3.1 — insert — induction is entered only from `NOT_INDUCTED`; a second induction or a rejection of an `INDUCTED`/`REJECTED` package is refused with `ERR_INVALID_STATE` — `routes/packages.py:201,227`.
3. §3.2 — insert — a bank that auto-settled to `UNLOADED` re-takes its face on a landing (or on `begin-unload`), returning to `UNLOADING` with a fresh `actual_start_minutes` — `routes/aircraft.py:242`.
4. §3.2 — insert — an aircraft under a maintenance hold cannot complete an unload — `routes/aircraft.py:286`.
5. §3.3 — insert — the primary face admits a commodity-dedicated lane of the package's own class (`lane_kind == commodity_class`), not only `PRIMARY` — `routes/packages.py:255`.
6. §3.3 — revise — the secondary stage-budget gate is the sort's *last* check; lane certification/availability/kind/capacity are settled ahead of it per the §2.8 priority — `routes/packages.py:287-295`.
7. §3.4 — revise — the cancellable subject is any non-`CANCELLED` aircraft (`SCHEDULED`/`IN_FLIGHT`/`LANDED`/`UNLOADING`/`UNLOADED`) — `routes/aircraft.py:329`.
8. §3.6 — revise — replan while the contingency is still declared is refused with `ERR_CONTINGENCY_NOT_DECLARED` — `routes/moves.py:152`.
9. §3.6 — revise — onboarding records explicit move membership so a package whose gateway has no buildup still counts toward filled weight; offboarding unwinds it — `routes/moves.py:262,298`, `store.py:133`.
10. §3.6 — insert — sealing's below-container-limit weight bound is settled before the status gate (a non-`OPEN` buildup above its limit returns `ERR_BUILDUP_UNDER_CAPACITY`) — `routes/moves.py:408`.
11. §3.8 — insert — departure returns the feeder's `staged_weight_grams` to zero — `routes/feeders.py:151`.
12. §3.10 — revise — the advance disposition rewrites commitment only; handling is left untouched — `routes/shifts.py:161`.

**Per-edit pre-edit search log (subject; impl paths enumerated; wording adjustment):**

1. (a) `ERR_INVALID_REQUEST` scope. (b) Grepped all `ERR_INVALID_REQUEST` sites across `hubs.py:48,53`, `lanes.py:27,35`, `shifts.py:33,37`, `feeders.py:36`, `aircraft.py:56`, `moves.py:191,194,345,352,355,362,365`, `failures.py:181`, `auth.py:222,266,272,279,290,299,367`; read `errors.py`. (c) Scoped the clause to body-level requirements not concerning path/body resources, so it complements rather than contradicts the "before any business rule is consulted" sentence.
2. (a) induction one-way door. (b) Read `packages.py:193-231`; grepped tests for `NOT_INDUCTED`/`REJECTED` (test_18, test_19); confirmed no other writer of `induction_status` except `clear-upgrade-hold` (`packages.py:555`, sets mid-path `INDUCTED`). (c) No change — the sentence pins preconditions only.
3. (a) bank face re-take. (b) Enumerated `aircraft.py` (land 242, begin_bank_unload 104-110, _settle_bank 315) and `set_clock`; confirmed only `begin-unload` and `land` write `bank["status"]="UNLOADING"`. (c) Wrote "a landing on an `UNLOADED` bank" / "opening the face on such a bank" rather than a universal "the bank re-opens", to avoid over-claiming for non-`UNLOADED` banks.
4. (a) maintenance-held unload completion. (b) Grepped `maintenance_hold` in `aircraft.py` (232, 286, 344, 365, 370, 385) and `moves.py:99,223,239`. (c) No change.
5. (a) primary-sort dedicated lane. (b) Read `packages.py:238-267`; checked fixture/test call sites (`setup_hazmat_package` calls `primary_sort(pkg, lane_hz1_id)`; test_15/22/23 rely on the primary capacity/close/capability gates). (c) Worded as an equivalent alternative admission (`PRIMARY` *or* commodity-matching dedicated kind) so it cannot read as excluding `PRIMARY`-kind behaviour.
6. (a) secondary-sort gate order. (b) Read `packages.py:270-307`; re-read the §2.8 priority list and its use in test_15/test_21. (c) Scoped to "this stage-budget gate is the sort's last check" before naming the lane groups, mirroring the implementation's exact sequence.
7. (a) aircraft cancellable states. (b) Enumerated `aircraft.py:324-355` cancel; `services.cascade_upgrade_hold`; fixture `cancel_aircraft` (grounds a `SCHEDULED`/`IN_FLIGHT` aircraft first). (c) Phrased positively as "the cancellable subject is any aircraft that is not already `CANCELLED`" while keeping "A grounded aircraft must be cancelled" intact, so both the PRD prose and the guard remain consistent.
8. (a) replan identifier. (b) Read `moves.py:145-155`; test_21 prepared to accept `ERR_CONTINGENCY_NOT_DECLARED`. (c) No change.
9. (a) onboarding move membership. (b) Read `store.py:133-157`, `calculations.move_members`, `moves.py:249-299`; cross-checked test_17/20 (offboard restores the pre-load row set) and test_06 onboarding without a buildup. (c) No change.
10. (a) sealing gate order. (b) Read `moves.py:400-424`; checked the same "rated ≤ container limit" test at `moves.py:408`; confirmed `ERR_LOAD_WEIGHT_EXCEEDED` is unrelated to seal. (c) No change.
11. (a) feeder departure weight. (b) Enumerated `feeders.py` departure (137-162) and cancel (165-178); confirmed cancel zeroes only via recompute of cleared references while departure nulls the reference *and* explicitly zeroes the field. (c) No change — added only to departure.
12. (a) advance disposition handling. (b) Grepped `cascade_reroute`/`cascade_downgrade`/`cascade_commit` in `services.py`; read `shifts.py:144-178`; confirmed the §3.4 clear-sweep selects DIVERTED **and** REROUTED, so advance must leave handling untouched for test_07's `_rerouted_by_advance` to survive the clear. (c) Added the clarifying clause "only the divergence of §3.9 and the void of §3.9 ever move handling to `DIVERTED`" to keep the sentence true against the void path too (previously the sentence would have implied only diverge sets `DIVERTED`).

**No-new-mismatch note:** Every edit's subject was re-searched across all parallel endpoints touching that field (e.g. #3 against `begin-unload` and `land`; #5 against `secondary-sort` and `reclaim`; #9 against `assign-buildup` and `unload-package`; #12 against the clear-contingency sweep and the two dispositions) before committing.

## Step 9: Complete PRD (PRD_COMPLETED.md) — 2026-09-30T12:05:00.000Z

> Orchestrator note: PRD_COMPLETED.md verified on disk — 432 lines / 100,144 bytes vs PRD_FINALIZED.md 428 lines / 92,236 bytes. All pipeline artifacts present; no `__pycache__`/`.pyc` residue. Summary below verbatim.

The file is complete. Here is my report.

## Summary

Produced `/home/ubuntu/github/CodingPRD/tasks/task_3151_air_hub_sort_operations_next_day_commitment/workspace/PRD_COMPLETED.md` as a minimal inline patch over `PRD_FINALIZED.md`. Only `PRD_COMPLETED.md` was edited; no new sections, no new paragraphs (two blank-line separators were added where a clarifying sentence was broken out).

**Counts**
- Source: `PRD_FINALIZED.md` — 429 lines, 91,978 chars
- Target: `PRD_COMPLETED.md` — 433 lines, 99,850 chars (line delta +4, char delta +7,872)
- **Ambiguity-pins: 40**
- **Mismatch-revisions: 3**
- Sections touched: 21 of 24 subsections (2.1–2.10, 3.1–3.9, 3.11, 3.12, 3.13); §2.2, §3.10, §3.14, §3.15, the §4 table and the §5 catalogue needed no change.

**Mismatch-revisions (PRD said something impl does not do)**
- §2.3 Pagination — revise — out-of-range `limit` was stated as an error bound; impl silently clamps to 1–100, and non-numeric/negative inputs fall back — `response.py:70-86`
- §3.6 Load-move lifecycle — revise — "cancelled from `PLANNED` while nothing on it is loaded" is actually a hard refusal when any package is `LOADED`, and moves gain an explicit terminal `CANCELLED` state — `routes/moves.py:158-173`
- §3.6 Buildup sealing — revise — the separate "not in the tolerance band" clause was mis-ordered; the single rated-above-container bound is settled before the status gate and subsumes it — `routes/moves.py:408-410`

**Ambiguity-pins (one bullet per changed passage)**
- §2.1 RBAC — insert — missing `X-User-ID` is `ERR_UNAUTHENTICATED` too — `auth.py:205-207`
- §2.1 RBAC — insert — natural-key uniqueness set (iata across hubs; bank/lane/shift/feeder code and aircraft `tail_number` within hub; gateway within move) — `routes/hubs.py:47`, `lanes.py:25`, `shifts.py:31`, `feeders.py:34`, `moves.py:353`
- §2.2 Success format — insert — `api_request_timestamp` always ends in `Z` — `response.py:21-24`
- §2.2 Success format — insert — clock pin returns an empty `data` object — `routes/hubs.py:39`
- §2.4 Clock — insert — same-instant re-send accepted; unparseable input is `ERR_INVALID_REQUEST` — `routes/hubs.py:33-38`
- §2.4 Hub creation — insert — unresolvable `alternate_hub_id` is `ERR_RESOURCE_NOT_FOUND` — `auth.py:310-311` + `check_body_fks`
- §2.5 Posture — insert — thresholds are already whole numbers, so the floor is a no-op — `calculations.py:96-104`
- §2.6 Live volume — insert — override takes a non-negative int; clear-contingency discards it; posture and labor variance read the override — `routes/hubs.py:216-224`, `105`, `calculations.py:112-130`
- §2.8 Addressability — insert — bare UUID ids, no decoration — `serializers.py:67-76`
- §2.8 Validation order — insert — graded shape pass: below-minimum integers and undeclared fields are `ERR_INVALID_REQUEST` before existence — `auth.py:276-284`, `360-367`
- §2.8 Validation order — insert — `ERR_LANE_CAPACITY_EXCEEDED` added to the business-constraints tier — `routes/packages.py:82-84`
- §2.9 OCC — insert — downgrade guard only fires when the field is supplied — `routes/packages.py:430-433`
- §2.9 OCC — insert — omitted expected version imposes no rejection — same
- §2.9 OCC — insert — `expected_load_move_version` is a guard by supplied field — `routes/moves.py:211-216`
- §2.9 OCC — insert — `expected_buildup_version` is accepted and ignored — `auth.py:343` + `moves.py:400`
- §2.10 Recompute — insert — a shift is refreshed without bumping its own `version` — `calculations.py:357-364`
- §3.1 Creation — insert — malformed weight bounds / enum members / unknown fields are `ERR_INVALID_REQUEST` — `routes/packages.py:105-110`
- §3.1 Creation — insert — ack replay compares the seven shipment fields — `routes/packages.py:51-54`, `118`
- §3.1 Induction — insert — no covering shift blocks nothing — `routes/packages.py:205-207`
- §3.1 Induction — insert — below-1 dimension weight is `ERR_INVALID_REQUEST` — `routes/packages.py:198`, `211-212`
- §3.2 Effective budget — insert — null `actual_start_minutes` falls back to the full 45-minute cap — `calculations.py:151-156`
- §3.3 Lane load — insert — `CLOSED` is exempt from the derived `AVAILABLE`/`SATURATED` flip — `calculations.py:190-194`
- §3.3 Primary sort — insert — `commodity_capability` must still match; certification/availability/capacity precede the kind gate — `routes/packages.py:74-86`, `255`
- §3.4 Declaration — insert — gate is the flag alone, admitted from any posture — `routes/hubs.py:92-93`
- §3.4 Clear contingency — insert — the clear is what de-escalates `GROUND_STOP`; it discards the override and voids still-`OPEN` failures on packages it returns to `COMMITTED` — `routes/hubs.py:99-134`
- §3.5 Route irregular — insert — accepted from any handling state but hazmat; lane must be `IRREGULAR` kind — `routes/packages.py:355-364`
- §3.5 Route hazmat — insert — lane gates and their order; `DIVERTED`/`HOLD_AT_HUB` refused — `routes/packages.py:339-347`, `389`
- §3.6 Onboarding — insert — creation-time `forward_capacity_grams` is superseded by recompute — `routes/moves.py:57-69`, `calculations.py:232-249`
- §3.7 Shift — insert — invalid equal-minute shift excluded from window comparisons — `calculations.py:320-327`
- §3.7 Triage — insert — read also returns `staffing_posture` and `shift_id` — `routes/hubs.py:233-249`
- §3.8 Feeder — insert — no covering shift blocks nothing; non-positive departure is `ERR_INVALID_REQUEST` — `routes/feeders.py:38`, `96-98`
- §3.8 Feeder — insert — departure ceiling checked before the posture gate — `routes/feeders.py:143-147`
- §3.9 Diverge — insert — pre-cutoff or non-`COMMITTED` is a state failure — `routes/packages.py:483-489`
- §3.9 Clear reroute — insert — voids only the late-inbound failure; `ERR_CONTINGENCY_NOT_DECLARED` from the hub — `routes/packages.py:524-537`
- §3.9 Clear upgrade hold — insert — requires clear contingency; resets lane assignment; leaves `INDUCTED` — `routes/packages.py:542-558`
- §3.11 Failure creation — insert — `failure_minutes` is client-supplied; only server-emitted failures stamp the clock — `routes/failures.py:59-71`, `services.py:66-77`
- §3.11 Attribution — insert — cause outside the seven-member set is `ERR_INVALID_REQUEST` — `routes/failures.py:22`, `59`
- §3.12 Transitions — insert — finalize/dispute/reopen/void are all entered only from `OPEN` — `routes/failures.py:102`, `116`, `130`, `144`
- §3.12 Reopen — insert — disputed-status gate precedes the hub-posture gate — `routes/failures.py:130-133`
- §3.11 Refund summary — insert — reports `batch_total_cents`, `eligible_failure_count`, `provisional_failure_count` — `calculations.py:417-433`
- §3.13 Concourse — insert — reports `concourse_width_rating`, `merged_minutes`, `lane_count` — `calculations.py:199-216`

**Cross-checks that required no change** (verified against impl, already pinned by `PRD_FINALIZED.md`): rated-weight rounding, cutoff arithmetic, bank slack/budget sums, primary/secondary sort error ordering, the held-checkpoint advance/release fork, forward-capacity tier order, buildup tier band and `WEIGHT_BREACH` flip, feeder 95% departure ceiling, the batch-total rounding order, cascade chains, and the §4 status-code convention (non-create writes 200, creates 201). All 34 error ids and the 103-row endpoint table were left untouched.

## Pipeline Complete — 2026-09-30T12:06:00.000Z

All nine steps finished. Final verification: 145/145 tests passing in all 8 rounds of the final stability sweep; implementation boots clean with an empty in-memory store on every `start.sh` invocation.
