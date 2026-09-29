# Worklog — task_2977_state_fish_hatchery_stocking_program

## Step 1: Create task directory — 2026-09-06T00:36:30.788Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2977_state_fish_hatchery_stocking_program` and `.../workspace` (pre-assigned path from the orchestrator invocation; no index auto-allocation performed, per instruction — 32 concurrent pipelines run on this host).

## Step 2: Generate Scaffold — 2026-09-06T02:11:10.455362071Z

All three scaffold artifacts are complete and the lint is clean on the first pass.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2977_state_fish_hatchery_stocking_program/`)

| File | Lines | Top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | **2482** | §1.0–§1.7 section keys only — contains **neither** `scaffold_difficulty_design` **nor** `scaffold_corner_design` (verified programmatically) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | **2310** | single key `scaffold_difficulty_design` — 9 rule blocks / 29 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | **3742** | single key `scaffold_corner_design` — 9 sections / 112 instances (81 with full `test_recipe`, 31 `excluded_because:` stubs citing §1.8 names) |

Corner-design section breakdown: entities 15, state_machines 15, calculations 14, validations 11, endpoints 8, errors 29, rbac 11, cross_cutting_complexity_layers 8, consistency_model 1. All 46 catalogued `error_id`s are triggerable (real instance or stub citing a §1.8 instance that asserts it). Instance names are unique **across both** design files (112 + 29, zero overlap), and every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2977_state_fish_hatchery_stocking_program/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2977_state_fish_hatchery_stocking_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2977_state_fish_hatchery_stocking_program/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    47
  §1.1 entities declared:     11
  §1.8 instances scanned:     29
  §1.9 instances scanned:     81
  Calls scanned (§1.8+§1.9):  1577

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Notes for the caller

- **Meta-directive excluded from `scenario:`** — the line "Generate task harder than expert level!" was deliberately left out of `SCAFFOLD.yaml`'s `scenario:` value (known leak vector into PRD.md); the domain paragraph itself ("2977. State Fish Hatchery & Stocking Program … stocking request intake from regional biologists and the public.") is verbatim.
- **One SCAFFOLD.yaml self-consistency fix earlier in the run:** `ERR_PATHOGEN_NOT_TREATABLE` was unreachable because `own-state-legal` (priority 8) would return `ERR_INVALID_STATE` for `record-treatment` from `FAILED_REPORTABLE`. Fixed with reciprocal `note:` carve-outs on `own-state-legal` and `pathogen-treatable` rather than by reordering priorities; corner instance `treating_a_reportable_finding_reports_pathogen_not_treatable` now asserts that carve-out and that it is narrow (SAMPLED still yields `ERR_INVALID_STATE`).
- **Anchor scheme:** the corner file re-declares its own base chain with `c_<step>` anchors (the §1.8 file uses `k_<step>`) because YAML aliases are file-scoped. Every asserted literal was computed against the scaffold's own formulas (e.g. biomass 175.93 from 20000 × 3.99 g, density 0.0880, FCR 0.583, cost 45000 + ceil(240.00 × 150) = 81000, acclimation ceil(7.5) × 6 = 48, priority scores 97.50 / 80.00 / 77.50, `plan_fill_pct` 120.00, budget-exceeded 45033 > 40000).
- **Constraints honoured:** no sibling task directory was read, listed, globbed or grepped at any point; scratch was confined to `.scratch/step2/` (`calc.py`, `verify2.py` only) and nothing outside it was deleted; every YAML was built by one `Write` plus incremental `cat >>` heredocs with a `yaml.safe_load` parse check after each chunk.

**Orchestrator verification:** confirmed all three files present with the stated line counts; `grep -i "expert level"` over SCAFFOLD.yaml returns nothing, so the difficulty directive did not leak.

## Step 3: Copy shared files — 2026-09-06T02:11:10.467709196Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-06T02:28:31.262777447Z

PRD complete and verified.

**Deliverable:** `workspace/PRD.md`

**Final line count: 435 lines.** Last section heading: `## 5. Error Code Catalogue` — the file ends at a real section boundary (the final table row `| \`ERR_BUDGET_EXCEEDED\` | 422 |`), no truncated sentence, no missing trailing section.

Built incrementally: 1 `Write` + 17 heredoc `cat >>` appends, `wc -l` after each. No giant single Write, so no 64k-cap truncation.

**Structure shipped**
- §1 Introduction
- §2 Global Specifications, 11 subsections: 2.1 RBAC (5 roles), 2.2 API Response Structure (verbatim), 2.3 Pagination/Ordering/Filtering, 2.4 Logical Clock, 2.5 Station Ledgers as Conserved Quantities, 2.6 Operating Posture, 2.7 Common Record Properties, 2.8 Optimistic Concurrency, 2.9 Numeric Precision, 2.10 The Order of Refusal (15-level ladder), 2.11 Resolving Identifiers
- §3 Business Logic, 9 subsections (station/effluent, brood + spawning window, egg take, rearing/feedings/stage gates, fish health, demand intake + priority score, allocation plans + run, the stocking trip, marking + contribution)
- §4 Endpoint Definitions — 4-column table, all 47 endpoints
- §5 Error Code Catalogue — 2-column table, all 46 error IDs

**Three Hard Contracts — all PASS**

*Contract 1: Field-Name Coverage — PASS (2 independent passes).* Pass 1 diffed the PRD's backticked tokens against the 154-name union in `.scratch/step4/required_entity_fields.txt` + `required_endpoint_inputs.txt`: 0 missing. Pass 2 recomputed the requirement set from scratch directly out of `SCAFFOLD.yaml` (all `entities[].fields[].name` plus every `input`/`request_body`/`query_params`/`path_params` identifier, 151 candidates) rather than trusting the scratch files: 0 missing.

*Contract 2: Rule Coverage — PASS.* All 46 error IDs appear in the §1–§3 prose, not only in the §5 table. All 3 `concurrency_rules` are documented with write endpoint, OCC token, error ID, 412 status, ladder position and the `version += 1` success effect (`expected_lot_version` on trip scheduling; `expected_plan_version` on both plan-run and attach-to-plan). All 3 `validation_conflict_pairs` are written out explicitly in §2.10 as worked orderings (state beats safety, temporal beats capacity, safety beats fiscal), plus the level-10 internal order on load and the single `ERR_PATHOGEN_NOT_TREATABLE` carve-out. Every state-machine transition literal across all 9 machines is present in backticks, including both RearingLot dimensions (stage `EGG`/`FRY`/`FINGERLING`/`YEARLING`/`RELEASED`/`TERMINATED` and health `UNSCREENED`/`UNDER_INSPECTION`/`CERTIFIED`/`RESTRICTED`/`QUARANTINED`, with the `CERTIFIED → UNSCREENED` certificate-lapse edge). All 14 `calculations` are rendered as prose with their rounding modes and boundary behaviour; both dual-variant calculations (`allocation_grant` modes; `contribution_index_cohort` / `contribution_index_harvest` computed side by side with no selector) and the selector policy's tie-break chain are stated.

*Contract 3: §3 Path Purity — PASS.* Scanned all 272 distinct backticked tokens between `## 3.` and `## 4.` (lines 182–330): zero start with `/`, zero are a bare HTTP method, zero combine method+path, zero contain a stray path separator. §3 refers to operations only by state-transition framing, role + action verb, or capability description.

Also verified §2.2 is byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md`.

**Constraints honoured:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced. No difficulty language anywhere in the PRD. Scratch confined to `.scratch/step4/`.

Two judgement calls worth flagging for the next step: (1) the scaffold's `loaded_at` is declared `source: input` and is listed as a load-endpoint input, yet the StockingEvent state machine also says `loaded_at = current_utc` — I documented it as the caller-supplied value, matching the field declaration and endpoint side effects; (2) attach-to-plan's precondition says the plan must be `DRAFT` while the plan machine has an `ALLOCATED → DRAFT` edge fired by that same endpoint — §3.7 resolves this by allowing `DRAFT` or `ALLOCATED` and refusing only `CLOSED` with `ERR_INVALID_STATE`.

**Orchestrator verification (truncation guard):** independently ran `wc -l` (435) and `tail -14`; PRD.md ends on the last row of the §5 error table, a real section boundary — not truncated. `grep -i "expert\|scaffold"` returns nothing, so no difficulty directive and no scaffold reference leaked into the PRD.

## Step 6: Generate Implementation — 2026-09-06T02:59:12.712779137Z

The implementation is complete and verified.

## Deliverables

`workspace/implementation/` — 19 Python modules + `requirements.txt` + executable `start.sh`, 3117 lines total, all `py_compile` clean:

| lines | file |
|---|---|
| 17 | `serialize.py` |
| 17 | `start.sh` (executable) |
| 41 | `auth.py` |
| 70 | `errors.py` |
| 71 | `routes_transport.py` |
| 85 | `app.py` |
| 93 | `routes_water.py` |
| 102 | `constants.py` |
| 104 | `envelope.py` |
| 139 | `routes_lot.py` |
| 142 | `routes_hatchery.py` |
| 185 | `routes_plan.py` |
| 185 | `routes_request.py` |
| 185 | `validators.py` |
| 194 | `store.py` |
| 205 | `routes_health.py` |
| 245 | `calc.py` |
| 284 | `routes_brood.py` |
| 346 | `derive.py` |
| 406 | `routes_event.py` |
| 1 | `requirements.txt` |

## Fresh-boot smoke check

`start.sh` booted from a clean process on a random high port. `GET /waters` returned the exact PRD envelope:

```json
{"meta": {"api_request_id": "req_0Y6DN7KGBTY5JD5YLCWD", "api_request_timestamp": "2026-09-06T02:58:14.798Z", "limit": 10, "offset": 0, "total_count": 0, "has_more": false}, "response_type": "array", "data": []}
```

`/waters`, `/rearing-lots`, `/stocking-events`, `/allocation-plans` all returned `total_count: 0` on a fresh boot, confirming **zero seeded data**. A blank `X-User-ID` gave 401 `ERR_UNAUTHENTICATED`. `GET /hatcheries` returned 405 `ERR_METHOD_NOT_ALLOWED`, which is correct — the PRD declares only `POST /hatcheries`, `GET /hatcheries/{id}` and `GET /hatcheries/{id}/effluent-readings`, no station collection listing.

The 55-step end-to-end walk (`.scratch/step6/smoke.py`) reports **SMOKE OK, 0 failures**. It exercises station -> water -> brood stock -> spawning window -> spawn event -> egg take -> feeding -> stage advances -> inspection -> certification -> request -> plan -> attach -> run -> transport unit -> trip -> load -> release -> recoveries -> effluent exceedances -> freeze cascade, plus 401/403/404/400/412/422 refusals. Every hand-checkable figure matched the PRD worked examples: `cumulative_survival 0.684`, `required_eggs 21930`, `projected_release_count 41040`, `fcr 0.558/0.463`, `growth 0.49`, `biomass 551.16`, `priority_score 97.5`, allocation 625 granted from a 1000 pool with unmet 15, `planned_load_lbs 6.89` -> cost 46034, `oxygen 0.103`, `max_fish_allowed 54431`, `tempering_minutes_required 48`, `released_count 600`, water 600/0/30.0/1400, plan auto-`CLOSED`, unit back to `AVAILABLE` with a null `current_event_id`, budget 0/46034/99953966, `effective_marked 380`, cohort 0.15, harvest 0.38.

The freeze cascade runs: one exceedance -> `RESTRICTED` (count 1), second -> `FROZEN` (count 2), and the brood stock correctly cascades to `SUSPENDED`.

The two earlier smoke failures were bugs in the smoke script, not the implementation — two effluent `sampled_at` literals sat a day ahead of the logical clock, and the server rightly answered 400 `ERR_INVALID_REQUEST` "sampled_at must not be after the logical clock."

## Constraint compliance

- Storage is in-memory only. An audit for `sqlite`, `open(`, `json.dump(`, `pickle`, `shelve`, `/tmp`, `test_suite`, `test_helpers` across all modules returned **no matches** — nothing touches disk and no test directory was ever read.
- No entity data is seeded, preloaded or hardcoded at startup.
- `start.sh` reads `$PORT`, binds `0.0.0.0`, runs `exec python3 app.py` in the foreground; every re-invocation is a fresh empty world.
- Both smoke servers were killed by the exact PID resolved from `ss -ltnp` on its own random high port (575403 on 21985, 620616 on 31059), both confirmed "port free". No broad `pkill` was used at any point.
- Scratch confined to `.scratch/step6/`; sibling `step2`, `step4`, `step5` directories are intact. `__pycache__` was removed so the implementation dir ships only source.

One note for the caller: the background Step 5 unit-test agent was still running when this finished, so the suite has not been run against this implementation yet.

## Step 5: Generate Unit Tests — 2026-09-06T04:12:40.281594933Z

All 13 test files are complete and verified. `test_13_refusal_order_and_concurrency.py` was the last deliverable.

## What was written this session

`test_suite/test_13_refusal_order_and_concurrency.py` — 684 lines, **11 tests**, covering the four `Corner/cross_cutting_complexity_layers` OCC instances and the three remaining `Difficulty/priority_pair_validation_conflict` instances:

- **Stale lot revision** (2 tests): a feeding between the read and the schedule -> 412 `ERR_STALE_LOT_VERSION`, with `reserved_count` 0 and `budget_committed_cents` 0; the identical body quoting the fresh revision then returns 201 and reserves 2400 ("refused, not lost").
- **Stale plan revision on the run** (1) — plan stays `DRAFT`, `run_count` 0, `version` 2, request `QUEUED` with `allocated_count` 0.
- **Stale plan revision on a second attach** (1) — second request stays `SUBMITTED` with a null `allocation_plan_id`, plan version unmoved by the attempt, and the same attach succeeds after a re-read.
- **Lot revision moves on every write** (1) — 1 at the take, 2 after a feeding, 3 after the stage advance, unchanged by a GET.
- **Own state beats quarantine safety** (2) — an `OPERATOR_ABORT`ed trip whose lot a later `POSITIVE_REPORTABLE`/VHSV finding quarantined answers 409 `ERR_INVALID_STATE`, never 422; `abort_reason` stays `OPERATOR_ABORT` (not the cascade's `LOT_QUARANTINED`), loading fields null, truck free.
- **Transport overlap beats the capacity ceiling** (2) — a 2500-fish 18.0 C load overlapping the released 08:00-14:00 trip on TRK-01 answers 409 `ERR_TRANSPORT_UNIT_UNAVAILABLE`; the identical warm load on an uncommitted TRK-02 answers 422 `ERR_TRANSPORT_CAPACITY_EXCEEDED`, making the ordering falsifiable.
- **Quarantine safety beats the fiscal ceiling** (2) — a 45033-cent trip against a 40000-cent appropriation on a quarantined lot answers 422 `ERR_LOT_QUARANTINED`, never `ERR_BUDGET_EXCEEDED`; no event exists for the request, lot 20000 on hand / 0 reserved, budget committed 0, request still `ALLOCATED` 1000.

Two design sub-assertions were deliberately not emitted, for the reasons used consistently across the suite: `oxygen_flow_lpm == null` on a `SCHEDULED` trip (PRD 3.8 states scheduling computes it), and the design's "returns 201" for load/release (PRD line 334 gives 201 to creates only).

## Final verification (whole suite)

- `python3 -m py_compile` on all 9 helper + 14 suite files: OK. `python3 -m pyflakes` across all: **rc=0**.
- **179 PRD quotations, 0 not found verbatim** (`check_quotes.py`), and `check_sections.py` confirms **0 section-label mismatches** in all 13 files — every `PRD n.n:` label matches the heading the quoted sentence actually lives under.
- `check_tags.py`: **140 tests, 110 distinct design instances, 0 problems** — exactly one `Design:` line per test, always the last docstring line, no unknown instances. A set diff against `.scratch/step5/queues.txt` shows **live 110 / used 110, nothing missing and nothing extra** (29 queue A + 81 queue B).
- `check_symbols.py`: 13 files, 0 bad symbols. `check_api.py`: 47 client methods, 0 unknown `api.*` calls. `check_fx_api.py`: 0 unknown calls in `fixtures.py`.
- Path rule confirmed: `test_helpers/` and `test_suite/` exist at the task root; `workspace/test_helpers` and `workspace/test_suite` do **not** exist. `__pycache__` from py_compile removed.

## File inventory

`test_helpers/`: `__init__.py` 133, `api_client.py` 292, `api_errors.py` 129, `assertions.py` 255, `constants.py` 238, `factories.py` 381, `fixtures.py` 822, `test_users.py` 101, `types.py` 220.

`test_suite/`: `conftest.py` 23, `test_01_station_and_discharge.py` 438 (10 tests), `test_02_brood_groups_and_spawning.py` 308 (8), `test_03_egg_takes_and_projection.py` 535 (12), `test_04_rearing_and_feed_conversion.py` 481 (11), `test_05_fish_health.py` 593 (12), `test_06_waters_and_demand.py` 457 (11), `test_07_allocation.py` 506 (12), `test_08_trips_scheduling_and_load.py` 976 (22), `test_09_release_and_abort.py` 505 (10), `test_10_truck_calendar_and_oxygen.py` 348 (6), `test_11_marking_and_recoveries.py` 150 (3), `test_12_access_control.py` 465 (12), `test_13_refusal_order_and_concurrency.py` 684 (11). **9040 lines total, 140 tests.**

Scratch checkers left in place for Step 7's use at `.scratch/step5/{check_quotes,check_sections,check_symbols,check_api,check_fx_api,check_tags,show}.py` plus `queues.txt`. No server was started, no pytest or `prd-bench-local-run` was invoked, and nothing under `workspace/implementation/` was read or written.

**Orchestrator verification:** `test_helpers/` and `test_suite/` confirmed present at the task root; no `workspace/test_helpers` or `workspace/test_suite` stray directories exist.

**Note:** Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator ran while `test_suite/` did not yet exist — physical isolation held.

## Step 7: Run Tests and Iterate — 2026-09-06T04:29:41.664384932Z

**Step 7 complete — all 8 rounds green in the same sweep.**

## Iterations
2 (iteration 1: diagnose 9 deterministic failures; iteration 2: verify after one fix batch).

Iteration 1 sweep: all 8 rounds `total=140 passed=131`, 9 non-passed entries, cross-check 140-131=9 OK. Every one of the 9 failed in all 8 rounds — fully deterministic, no flakiness, no timeouts, no `ServerStartError`.

## Tests deleted
None. One assertion removed under STEP 1c partial-coverage split (below).

## Fixes to `test_helpers/`
None. No fixture, factory, or role-header defect was found; `test_users.py` already uses `""` for the blank-ID case and every version-quoting fixture re-reads its parent immediately before the write.

## Fixes to `test_suite/`
1. **`test_01_station_and_discharge.py::test_immediate_consistency_shows_the_recomputed_station_in_the_same_call`**, **`test_03_egg_takes_and_projection.py::test_planning_a_take_on_a_restricted_station_is_refused`**, and **`test_04_rearing_and_feed_conversion.py`** tests `test_lot_biomass_and_fcr_round_half_up_to_the_declared_places`, `test_fcr_biological_and_economic_diverge_on_the_same_lot`, `test_a_feeding_landing_exactly_on_the_density_cap_is_accepted`, `test_a_feeding_lands_on_the_growth_dimension_while_health_is_under_inspection` — six `validate_success(api.record_feeding(...), 201)` call sites changed to `200` (plus test_01's docstring reworded off "A feeding's own 201"). *Why:* PRD §4's status rule is "Endpoints that create a new resource answer HTTP 201 on success; every other successful operation ... answers HTTP 200", and no `Feeding` resource exists in the PRD — it has no `id`, no read endpoint, no §2.3 list filter, no field list, and §2.7 names the discharge sample as the *only* record exception. The response body is the rearing lot itself (`version: 2`, its own `created_at`) and all six tests assert only on lot fields, so the feeding endpoint is a modify -> 200. Changing the implementation to 201 was explicitly rejected as contradicting a verbatim PRD sentence.
2. **`test_06_waters_and_demand.py::test_habitat_suitability_score_above_one_hundred_is_rejected`** — its local `trappers_lake(**overrides)` helper passed explicit keywords *and* `**overrides` to `f.water_payload`, so `trappers_lake(angler_demand_index=-1)` raised `TypeError: got multiple values for keyword argument`. Rewritten to merge defaults and overrides into one dict so overrides win. Pure test-artifact bug — the request never reached the server; intended semantics (101->400, -1->400, 100->201) preserved unchanged.
3. **`test_11_marking_and_recoveries.py::test_recoveries_against_a_trip_that_never_shipped_are_refused`** — STEP 1c split: removed only `assert_is_none(event["recovered_count"], "recovered_count")`. *Why:* `recovered_count` appears in PRD §3.9 solely as an input to `POST /stocking-events/{id}/recoveries` and as a term in the two index formulas, and §4's GET row lists only "its load plan, capacity ceiling, acclimation requirement, release outcome and contribution indices" — PRD is silent on its pre-recovery default (DEFAULT-VALUE SILENCE). The test's covered assertions were all kept: `validate_error(..., ERR_INVALID_STATE, 409)`, the status re-read staying `SCHEDULED`, and both `contribution_index_*` nulls, which *are* verbatim covered by "Both remain null on a trip until a recovery with a `recovered_count` strictly greater than zero has been reported."

## Fixes to `implementation/`
1. **`workspace/implementation/routes_event.py::create_stocking_event`** — `"effective_marked_count": None` -> `calc.effective_marked_count(mark_type, marked_count)`. *Why:* PRD §3.9 states "A trip declares its marking programme when it is scheduled, through the `mark_type` and `marked_count` fields" and "The system therefore derives the trip's `effective_marked_count` by discounting the declared `marked_count` by a method-specific tag-loss rate". Both inputs exist at scheduling, and the null-until-recovery sentence is scoped by "Both" to the two contribution indices only. Previously the field was computed solely in `record_event_recoveries`, so a scheduled CWT trip read back `None` instead of 2280 (2400 x 0.95). No new field, endpoint, or side effect was introduced — `calc.effective_marked_count` already existed and is unchanged.

## Final counts
Iteration-2 sweep (single sweep, 8 concurrent rounds): **rounds 1-8 all `total=140 passed=140`, zero non-passed entries, union of failing tests = 0, `ALL GREEN`.** Confirmed from the eight per-round `results.$i.json` files individually, with the `total - passed` cross-check satisfied in every round. No SCAFFOLD file was read; `worklog.md` untouched; scratch confined to `.scratch/step7/` (`summarize.py`, `detail.py`).

**Orchestrator verification:** independently parsed all eight `workspace/implementation/results.[1-8].json`. Each reports `total 140 / passed 140` with zero entries whose `status` key is not `passed`, and `total - passed == len(non-passed)` holds in every round. The clean sweep is real, not a subagent claim. Step 8 will run (1 implementation fix, so the skip condition does not apply).

## Step 8: Finalize PRD — 2026-09-06T04:33:45.884158909Z

Done. PRD_FINALIZED.md is a 3-line patch of PRD.md.

## Line counts
- `PRD.md`: 435 lines / 106,535 bytes
- `PRD_FINALIZED.md`: 435 lines / 107,318 bytes
- Line delta: 0 (+0.00%); byte delta: +783 (+0.73%). Three lines revised, no insertions/deletions of lines, no truncation.

## Changes
- **§3.4 (Rearing: Feedings...)** — insert — appended to the feeding-inputs paragraph that a feeding is not a resource (no `id`, no read endpoint, no list filter), so recording one is a modification of the rearing lot answering **HTTP 200 with the updated lot in `data`, not 201** — `implementation/routes_lot.py:112-113`.
- **§3.9 (Marking Programmes)** — revise — `effective_marked_count` is derived **when the trip is scheduled**; a scheduled trip reads it back immediately rather than only after a recovery, and an unmarked (`NONE`) trip reads 0 — `implementation/routes_event.py:115`, `implementation/calc.py:217-221`.
- **§3.9 (Marking Programmes)** — revise — "Both remain null" -> "Both **indices** remain null" (scoping the null-until-recovery rule to the two contribution indices), plus a clause pinning that the trip's own `recovered_count` **opens at 0 at scheduling** and is replaced by the reported figure — `implementation/routes_event.py:111`, `:399`.

No PRD edit for Step 7's `test_06` fixture bug (pure test-artifact `TypeError`; PRD §3.6 already pins 0-100 inclusive and impl matches) or for the `test_users.py`/factory areas (no defects found there).

## Per-edit pre-edit search log

**Edit 1 — feeding response status/body**
- (a) Subject: HTTP status code and response body of `POST /rearing-lots/{id}/feedings`, and by extension the global 201-vs-200 rule in §4.
- (b) Enumerated/read: `envelope.py:22-36` (`ok`=200, `created`=201, list=200); grepped every `@bp.post` / `return created(` / `return ok(` across all nine `routes_*.py`. Result: 201 is used **only** by the ten collection-level creates (`/hatcheries`, `/effluent-readings`, `/waters`, `/brood-stocks`, `/spawn-events`, `/health-inspections`, `/stocking-requests`, `/allocation-plans`, `/transport-units`, `/stocking-events`); every sub-resource action returns 200 — including `feedings`, `advance-stage`, `record-take`, `cancel`, `open-spawning-window`, `record-result`, `record-treatment`, `certify`, `withdraw`, `attach-to-plan`, `run`, `load`, `release`, `abort`, `recoveries`, `_clock/set_current_utc`. Also read `routes_lot.py:55-113` (body is `dump(lot)`) and `serialize.py` (no `id` for any feeding; no feedings collection in `store.py:COLLECTIONS`).
- (c) Adjustment: scoped the sentence strictly to feedings and justified it by the absence of a Feeding resource, rather than rewriting §4's general 201 rule — a general rewrite would have had to speak for the other fifteen 200-returning actions and for `/effluent-readings` and `/stocking-events`, which do return 201. §4's existing "Unless a section above says otherwise" makes the §3.4 sentence authoritative without touching §4. Did not mention `recoveries` (also a 200 sub-collection POST) since it is outside the diff; the narrow wording contradicts nothing there.

**Edit 2 — `effective_marked_count` derivation timing**
- (a) Subject: when and from what `effective_marked_count` is populated on a stocking event.
- (b) Enumerated/read: `routes_event.py:52-59` (`mark_type` default `NONE`, `marked_count` default 0, `marked_count` must be 0 when `NONE`), `:115` (computed at create), `:395`/`:401` (recomputed identically inside `record_event_recoveries` from the same two stored fields), `calc.py:217-221` (`TAG_LOSS.get` -> 0 when `mark_type` not in the table), `constants.py:98-102` (`TAG_LOSS` has only `AD_CLIP`/`CWT`/`PIT`). Grepped `mark_type|marked_count` across the whole implementation: no other writer — `load`, `release`, `abort` and the quarantine cascade never touch them, so the value is stable from scheduling onward.
- (c) Adjustment: wrote "derives ... when the trip is scheduled" rather than "only at scheduling / and never again", because `record_event_recoveries` re-derives the same figure (identical inputs, identical value); the chosen wording is true of both paths. Added the `NONE` -> 0 clause because `TAG_LOSS` has no `NONE` entry and the impl returns 0 there, so a fresh implementer must not choose null.

**Edit 3 — "Both indices" scoping + `recovered_count` pre-recovery default**
- (a) Subject: which stocking-event fields are null before a recovery, specifically the initial value of `recovered_count`.
- (b) Enumerated/read: `routes_event.py:88-120` (full `base_record` field initialisation — `recovered_count: 0`, while `creel_sample_fraction`, `released_count`, `max_fish_allowed`, `tempering_minutes_required`, `contribution_index_*` are `None` and `transport_mortality_count` is 0), `:399` (recovery assigns the supplied value), `calc.py:224-234` (`contribution_indices` returns `None, None` while `recovered_count <= 0`), `routes_event.py:293-301` and `:346-350` (release and abort never touch `recovered_count`), `serialize.py:16-17` (no field is dropped from the payload). Grepped `recovered_count` implementation-wide: only those sites.
- (c) Adjustment: wrote "is replaced by the figure a recovery report supplies" instead of "accumulates" or "is added to", matching the impl's plain assignment, while stopping short of an explicit claim about repeated recovery reports (PRD is silent there and that silence is outside the diff). Restricted the sentence to `recovered_count` and did not enumerate the other scheduling-time nulls/zeros, which are outside the Step 7 item.

**Orchestrator verification:** `wc -l -c` confirms 435 lines in both files with +783 bytes; `diff | grep -c '^[<>]'` reports 6 changed lines (3 revised pairs), so the patch is genuinely minimal. `PRD_FINALIZED.md` ends on the last row of the §5 error table — not truncated.

## Step 9: Complete PRD — 2026-09-06T05:21:51.933663892Z

**Orchestrator decision (recorded per the autonomy directive):** Step 9 was run as **five sequential passes over one shared `PRD_COMPLETED.md`**, partitioned by implementation module, rather than as a single monolithic scan. A single-agent scan of a 435-line PRD against a 3117-line, 19-module implementation reliably under-covers (and in past runs produced a byte-identical output, i.e. a silent no-op). Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2-5 edited in place and were explicitly forbidden to re-copy. Pass 5 was a reconciliation-only pass, because partitioned passes report cross-pass contradictions instead of resolving them. Partitions: (1) app/envelope/errors/auth/serialize/store/constants/validators; (2) routes_hatchery/water/brood/lot; (3) routes_health/request/plan/transport; (4) routes_event/calc/derive; (5) reconciliation.

**Aggregate result: `PRD_FINALIZED.md` 435 lines / 107,318 chars -> `PRD_COMPLETED.md` 436 lines / 136,624 chars. Char-delta +29,306 (+27.3%); +1 line (one added §2.2 list bullet). 73 edits total: 16 + 15 + 20 + 22 scanning edits plus pass 5's reconciliation patches. No new sections (28 headings, unchanged), §4 still 47 endpoint rows, §5 still 46 error rows matching `errors.py` byte-for-byte.**

---

### Pass 1 of 5 — cross-cutting layers (app, envelope, errors, auth, serialize, store, constants, validators)

- `cp PRD_FINALIZED.md PRD_COMPLETED.md` done as the first action; result **not** byte-identical (16 diff hunks, 35 changed lines).
- 435 lines / 107,318 chars -> 436 lines / 114,718 chars (+7,400 chars, +1 line from one added list bullet). `tail -3` confirms the file still ends at `| \`ERR_BUDGET_EXCEEDED\` | 422 |`. Heading count (28) and table-row count (97) unchanged.
- §5 error catalogue cross-checked row-by-row against `errors.py:ERROR_STATUS`: all ids and statuses match exactly, in the same order. No change needed there.
- **Ambiguity pins: 14. Mismatch revisions: 2.**

Changes:
- §2.1 — insert — ambiguity — absent/blank/unknown `X-User-Role` yields `ERR_FORBIDDEN_ROLE` (not 401); both headers compared byte-for-byte with no trim/case-fold, the sole whitespace tolerance being the blank test on `X-User-ID` — auth.py:12-23
- §2.1 — revise — ambiguity — the "scope only on a found record" rule extended to station-bearing **body** identifiers, which are resolved before the scope comparison they feed — routes_hatchery.py:114-115, routes_brood.py:33-34, auth.py:27
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly 20 chars from `A-Z0-9` — store.py:72-77
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the **wall** clock, not the logical clock, and is unrelated to `created_at` — envelope.py:18, store.py:115
- §2.2 — insert — ambiguity — new bullet pinning the three uncatalogued failures: `ERR_NOT_FOUND`/404 unrouted path, `ERR_METHOD_NOT_ALLOWED`/405, `ERR_INTERNAL`/500, all in the standard error envelope; trailing slash tolerated — app.py:37-75, app.py:48
- §2.2 — revise — ambiguity — `message` wording is non-contractual; only `error_id` + status are — errors.py:65-66
- §2.3 — revise — ambiguity — `offset` has no upper bound (past-end offset returns an empty page with true `total_count`); "wrong type" pinned to an optionally signed digit run, so `10.5`, words and empty values are 400 while omission takes the default — envelope.py:48-72
- §2.3 — insert — ambiguity — `total_count`/`has_more` computed post-filter, `has_more` iff `offset + len(returned) < total_count`; `created_at` ties (routine, since the clock is stationary) broken by creation order — envelope.py:30-36, store.py:193-194
- §2.3 — revise — ambiguity — the "newest sample first" departure ordered by **descending `sampled_at`** with reverse-creation tiebreak, not by `created_at` — routes_hatchery.py:106
- §2.3 — revise — **mismatch** — "an unrecognised value for any of them is `ERR_INVALID_REQUEST`" was false for identifier filters and `county`: those are open text matched exactly and just select nothing; only closed-vocabulary filters 400; `fiscal_year` must be an integer; filters ANDed; undeclared query params ignored — envelope.py:75-98, routes_water.py:67-69, routes_plan.py:69-71
- §2.4 — revise — ambiguity — output is always 3 fractional digits + `Z`, but input accepts `Z`/`z`, numeric offsets converted to UTC, zone-less values read as UTC, any fractional width with sub-ms **truncated** not rounded, and date-only values as midnight UTC — store.py:83-112
- §2.7 — revise — ambiguity — `created_at`/`updated_at` are stamped from the **logical clock**, so co-clock records share an instant and a backwards clock can invert creation order — store.py:148, store.py:156-165
- §2.7 — revise — ambiguity — `updated_at` is identical to `created_at` at creation — store.py:163
- §2.7 — insert — ambiguity — exactly one version bump per record per request even when a cascade reaches it twice (dirty-set settled once); serialisation includes every field, emits unknown values as JSON `null` rather than omitting, and never exposes internal bookkeeping keys — store.py:127-153, serialize.py:16-17
- §2.9 — insert — ambiguity — numeric fields are JSON numbers never strings, and a decimal-place count fixes the value not a text width (`0.9000` serialises as `0.9`, zero as `0.0`) — serialize.py:6-13
- §2.10 level 6 — insert — ambiguity — strict typing (no bool-as-number, no float-for-integer even when integral, no numeric strings, exact enum spellings), explicit `null` == absent (default applies for optional, "required" failure for required), required strings non-blank after trimming but stored as sent, absent/unparseable body reads as `{}`, non-object body is 400 — validators.py:24-41, 73-96, 144-159
- §2.11 — insert — ambiguity — an absent/`null`/non-string/blank body identifier is a shape failure (`ERR_INVALID_REQUEST`) reported at its own position in the left-to-right order, before any later identifier is resolved; worked both ways with the schedule-trip example — validators.py:44-70, routes_event.py:40-42
- §4 preamble — insert — ambiguity — only the ten collection-level POSTs answer 201; every sub-resource POST (feeding, recovery) answers 200 with the updated parent — envelope.py:26-27 vs routes_event.py:406, routes_lot.py:113
- §4 clock row — revise — **mismatch** — the row claimed the clock "must not move backwards", contradicting §2.4 and the implementation, which assigns unconditionally; also pinned that it answers 200 with `data` carrying only `current_utc` — routes_hatchery.py:22-32

Left for later passes: all of `calc.py`/`derive.py` (per-figure rounding scales, posture recomputation, ledger identities, priority score, load plan, acclimation, survival, contribution formulas — only verified `calc.q*`/`round_int` use ROUND_HALF_UP/FLOOR/CEILING, matching §2.9's general statement); per-route validation literals such as `station_code` `^[A-Z0-9]{4}$` (routes_hatchery.py:42) and the absence of minima on `annual_water_right_af`/`rearing_capacity_lbs`/`oxygen_supply_lpm`/`tss_permit_limit_mg_l`/`annual_budget_cents`; clock-cascade ordering; all §3.x workflow rules; ladder levels 8-15; the `record-treatment` carve-out; §4 per-endpoint role columns. Note: no list endpoint applies station scoping (only `GET /hatcheries/{id}` and the discharge list do), which §2.1 already states correctly.

---

### Pass 2 of 5 — routes_hatchery / routes_water / routes_brood / routes_lot

- 436 lines / 114,718 chars -> 436 lines / 120,430 chars. Verification: 436 lines, ends at `| \`ERR_BUDGET_EXCEEDED\` | 422 |`, all 47 §4 rows and 46 §5 error rows intact, pass 1's edits all still present.
- **14 ambiguity-pins, 1 mismatch-revision.**

Changes:
- §2.1 — revise — **mismatch** — "Scope applies to every `HatcheryManager` write, and additionally to **two reads**" was factually wrong: eight single-record reads are station-scoped (station, brood group, egg take, rearing lot, allocation plan, transport unit, stocking trip) while a health inspection is the one station-bearing read that is *not*, and no collection list except the discharge list is scoped. Replaced with the verified enumeration — routes_brood.py:71,181, routes_lot.py:26 (mine); cross-checked routes_plan.py:62, routes_transport.py:51, routes_event.py:138, routes_health.py:72
- §3.1 — insert — ambiguity — `station_code` is exactly four chars from `A-Z0-9`; uniqueness evaluated only after full shape validation, so duplicate-plus-malformed-number reports `ERR_INVALID_REQUEST`; `annual_water_right_af`, `rearing_capacity_lbs`, `oxygen_supply_lpm`, `tss_permit_limit_mg_l`, `annual_budget_cents` carry **no** minimum or maximum (zero and negatives accepted), with only `annual_budget_cents` an integer — routes_hatchery.py:42-54
- §3.1 — insert — ambiguity — posture is seeded literally `OPEN`, not derived, so a station registered with `annual_water_right_af` <= 0 opens `OPEN` despite already satisfying the freeze condition — routes_hatchery.py:73
- §3.1 — insert — ambiguity — the three discharge measurements have no upper bound; only `flow_af` is rounded (4 dp) while `tss_mg_l`/`total_phosphorus_mg_l` echo exactly as supplied — routes_hatchery.py:118-133
- §3.1 — insert — ambiguity — logging a sample is never gated on the water right; `water_available_af` may go negative and `ERR_WATER_RIGHT_EXCEEDED` is not a possible answer — routes_hatchery.py:137-141
- §3.6 — insert — ambiguity — `habitat_suitability_score`, `angler_demand_index`, `plan_target_count` are integer fields, so `55.0` fails like `55.5` — routes_water.py:29-34
- §3.6 — insert — ambiguity — closing a water takes no request body and ignores anything sent — routes_water.py:83-88
- §3.2 — insert — ambiguity — an equal-ended window is also refused; `egg_take_target` alone carries no minimum (a <= 0 target closes the group on its first take); the window is never compared with the clock at registration — routes_brood.py:43-44, routes_brood.py:235
- §3.2 — insert — ambiguity — the window test precedes the posture test, so a `READY` group outside its window at a `FROZEN` station answers `ERR_SPAWN_WINDOW_CLOSED`; operation takes no body — routes_brood.py:100-110
- §3.2 — revise — ambiguity — only the single brood read is scoped; the list returns every station's groups — routes_brood.py:75-77
- §3.3 — insert — ambiguity — `target_release_count` carries no minimum; `planned_take_date` is never compared with the clock or the spawning window — routes_brood.py:128-130
- §3.3 — insert — ambiguity — cancel takes no body; the single take read is scoped through its brood group, the list is not — routes_brood.py:176-198, routes_brood.py:268-276
- §3.4 — insert — ambiguity — `feed_lbs`/`avg_weight_g_after` >= 0 and `mortality_count` an integer >= 0 with no upper bound, so `mortality_count` is **not** capped at `count_on_hand` (drives it negative, which then never satisfies the exactly-zero termination test); `fed_at` not clock-checked; a `RELEASED`/`TERMINATED` lot may not be fed (`ERR_INVALID_STATE`), tested before the density cap — routes_lot.py:62-68, derive.py:305
- §3.4 — revise — ambiguity — `to_stage` is an enum over all six stage names: an unrecognised spelling is `ERR_INVALID_REQUEST`, a recognised non-adjacent target (incl. `RELEASED`/`TERMINATED`) is `ERR_INVALID_STATE` — routes_lot.py:123-128
- §3.4 — insert — ambiguity — the single lot read is scoped, the list is not — routes_lot.py:22-30

Flagged: pass 2's §2.1 edit falls inside pass 1's partition — pass 1 edited that paragraph and left the "two reads" claim standing; it was a hard mismatch affecting three of pass 2's endpoints, so it was corrected rather than left. Deferred to later passes: §3.8 line 321's two live defects (`stocking_plan_count` does not exist — impl uses `plan_target_count`, derive.py:129-132; and a release returns a `RESTRICTED` station to "`NORMAL`", not a posture value — impl yields `OPEN`, calc.py:72); `calc.density_index` returning 0.0000 when `rearing_capacity_lbs` <= 0 (calc.py:59-63); `calc.growth_rate_g_per_day` truncating a negative day span toward zero (calc.py:91).

---

### Pass 3 of 5 — routes_health / routes_request / routes_plan / routes_transport

- 436 lines / 120,096 chars -> 436 lines / 125,833 chars. Intact at 436 lines, still ending at `| \`ERR_BUDGET_EXCEEDED\` | 422 |`, passes 1-2 edits verified present (§2.3 and §3.4 both still differ from PRD_FINALIZED.md), all 20 own edits verified by marker grep.
- **6 mismatch-revisions, 14 ambiguity-pins.**

Mismatch-revisions:
- §3.5 — revise — mismatch — "`treatment_code` must be one of the recognised therapeutant codes" was false; impl accepts any non-blank string (`v.req_str`, no vocabulary). Same edit pins that `treatment_completed_at` is not clock-compared — routes_health.py:153-155
- §3.7 — revise — mismatch — `created_at` was called the "final tie-break"; the run's sort key ends in the service's creation sequence — routes_plan.py:85-90
- §3.7 — revise — mismatch — the cycle guard was scoped to "a request this plan allocated"; impl blocks on any event ever created against any request *currently attached*, at any event status (aborted/released included) — routes_request.py:109-116,166
- §4 `/health-inspections/{id}/certify` — revise — mismatch — row claimed certify requires "any withdrawal window has elapsed"; certify never re-tests it, so a backwards clock move lets a `PASSED` inspection certify with `withdrawal_clears_at` ahead of the clock — routes_health.py:178-205
- §4 `/stocking-requests/{id}/withdraw` — revise — mismatch — row claimed withdrawal surrenders "any grant it holds", but only `SUBMITTED`/`QUEUED`/`DEFERRED` (grant-free) requests may withdraw — routes_request.py:97-98
- §4 `/stocking-requests/{id}/attach-to-plan` — revise — mismatch — row said "a submitted request"; `DEFERRED` also attaches — routes_request.py:157-159

Ambiguity-pins:
- §3.5 — insert — creation field set: `escalated_from_retests` opens `false` (not null), plus the seven explicitly-null treatment/certificate fields — routes_health.py:47-58
- §3.5 — insert — `pathogen_code` optional on every result, free-form, stored even beside `NEGATIVE`, and **retained** when omitted; only `SAMPLED`/`RETEST_DUE` admit a result; state test precedes quarantine — routes_health.py:103,105-110,120-121
- §3.5 — insert — a `NEGATIVE` result does not touch the lot: `health_status` stays `UNDER_INSPECTION` or `RESTRICTED` and the lot's `version` does not advance — routes_health.py:125-126
- §3.5 — insert — recording a treatment writes only the inspection; lot stays `RESTRICTED` un-bumped; `result`/`pathogen_code` survive into `RETEST_DUE` — routes_health.py:165-174
- §3.5 — insert — the withdrawal gate is specific to the `NEGATIVE` retest branch (positives record normally mid-window) and a clock exactly at `withdrawal_clears_at` counts as cleared — routes_health.py:112-116
- §3.5 — insert — certify takes no body, any non-`PASSED` status is `ERR_INVALID_STATE`, a `RESTRICTED` lot certifies, and segregation-of-duties is evaluated last — routes_health.py:178-190
- §3.5 — insert — an escalated inspection reads `retest_count` two, not three — routes_health.py:128-131,171
- §3.6 — insert — a `CLOSED` water is not a gate at intake; `justification` need only be non-blank — routes_request.py:27,32
- §3.6 — insert — an unknown request id answers `ERR_REQUEST_NOT_FOUND` before the ownership test, for withdraw and attach alike — routes_request.py:94-95,146-147
- §3.6 — insert — reading a request is not ownership-scoped; a `PublicRequester` may read any requester's request — routes_request.py:60-63
- §3.7 — insert — `fiscal_year` is a required integer with no range (zero/negative accepted) — routes_plan.py:30
- §3.7 — insert — attach returns the updated **request**, and the plan's `version` bumps exactly once however much of it the attach rewrites — routes_request.py:174-185
- §3.7 — insert — reset-to-`DRAFT` also clears `allocated_at` and `deferral_reason`; `DENIED` requests are not requeued — routes_request.py:119-140
- §3.8 — insert — `unit_code` is not unique, and `certification_expires_at` is not clock-checked at registration, so an already-elapsed unit opens `AVAILABLE` — routes_transport.py:26,30,41

Flagged for reconciliation: pass 1's §2.1 "scope evaluated only on a found record" is written for `HatcheryManager` station scope only, while pass 3's §3.6 insert extends the same principle to request ownership — reconciliation may prefer hoisting it. Deferred to pass 4: the load gate at routes_event.py:206 tests only `unit["status"] == "OUT_OF_SERVICE"` and never re-reads `certification_expires_at`; `derive.recompute_water` recomputes `allocated_count_ytd` by full rescan whereas §3.6/§3.7 describe incremental add/subtract; `derive.quarantine_lot`, `derive.apply_clock`'s sweeps, `derive.close_plan_if_complete`. Verified `calc.priority_score` matches §3.6's four-step formula exactly (including clamp-then-quantize order).

---

### Pass 4 of 5 — routes_event / calc / derive

- 436 lines / 126,215 chars -> 436 lines / 134,217 chars. Intact (436 lines, ends at `| \`ERR_BUDGET_EXCEEDED\` | 422 |`); passes 1-3's edits in §2.1, §2.3, §3.4 and §3.5 all spot-check present. All 22 edits in-paragraph.
- **3 mismatch-revisions, 19 ambiguity-pins.**

Changes:
- §3.8 — revise — mismatch — `plan_shortfall_count`/`plan_fill_pct` recomputed against `plan_target_count`, not the nonexistent `stocking_plan_count` — derive.py:129-132
- §3.8 — revise — mismatch — a release returns a `RESTRICTED` station to `OPEN`, not to the non-value `NORMAL` — calc.py:72
- §3.8 — revise — mismatch — `OUT_OF_SERVICE` is terminal but **not** a booking gate: scheduling never inspects the truck's `status`, so the refusal only arrives at load — routes_event.py:36-121 (no status read) vs routes_event.py:206
- §3.8 — revise — ambiguity — the unit gate reads the stored `status` alone and never re-derives certification from the clock (covers the `IN_USE`-through-expiry path); an `ABORTED` trip blocks no calendar slot; an `IN_USE` unit is still loadable for a non-intersecting trip and its `current_event_id` is overwritten — routes_event.py:206-218
- §3.8 — revise — ambiguity — release returns the truck only while the unit still records *this* trip as `current_event_id` — routes_event.py:321-325
- §3.8 — insert — ambiguity — release leaves `cumulative_mortality_biomass_lbs` untouched (only a feeding adds mortality pounds), so transport losses do not move either FCR — routes_event.py:308-311
- §3.8 — insert — ambiguity — release input bounds: `tempering_minutes`/`transport_mortality_count` whole >= 0 with no cap (mortality > `fish_count` drives `released_count` negative), `site_water_temp_c` unbounded, `arrived_at` compared with neither clock nor `loaded_at` — routes_event.py:263-267,299
- §3.8 — insert — ambiguity — load input bounds: `load_water_temp_c` unbounded, `measured_load_lbs` >= 0 and stays null when omitted and is never compared with the load plan, `loaded_at` compared with neither clock nor scheduled interval — routes_event.py:193-195
- §3.8 — insert — ambiguity — "latest inspection" for the withdrawal gate = the latest one that actually *carries* a `withdrawal_clears_at`, by `updated_at` then creation order — derive.py:73-79
- §3.8 — insert — ambiguity — the per-fish pound figure is carried at full division precision, not the 2-decimal pound scale — calc.py:174-175,200
- §3.8 — insert — ambiguity — `avg_weight_g` <= 0 yields no load plan: `ERR_TRANSPORT_CAPACITY_EXCEEDED` whatever the count, `max_fish_allowed` stays null — calc.py:201-202, routes_event.py:233
- §3.8 — insert — ambiguity — all three body ids resolve before the station-scope test, so an out-of-scope `lot_id` + unknown `transport_unit_id` yields `ERR_TRANSPORT_UNIT_NOT_FOUND` — routes_event.py:41-44
- §3.8 — insert — ambiguity — the truck is not scoped: its `hatchery_id` is never compared with the lot's station, and the oxygen aggregate is measured against the lot's station — routes_event.py:41-44,223
- §3.8 — insert — ambiguity — `transport_mortality_count` and `recovered_count` open at 0; every other outcome field opens null (enumerated) — routes_event.py:100-119
- §3.8 — revise — ambiguity — abort ignores anything sent as a body — routes_event.py:336 (never calls `v.body()`)
- §3.8 — revise — ambiguity — abort also clears the request's `allocated_at` to null — routes_event.py:360
- §3.5 — insert — ambiguity — the quarantine cascade *keeps* the request's `allocated_at`, unlike an operator abort — derive.py:261-266
- §3.5 — revise — ambiguity — the cascade returns a truck only where it still records the aborted trip — derive.py:255-259
- §3.9 — insert — ambiguity — each index is null when its *own* denominator is not strictly positive (`effective_marked_count` 0 -> cohort null; `released_count` <= 0 -> harvest null); repeat reports replace outright, and a later `recovered_count` of 0 returns both to null — calc.py:224-234, routes_event.py:399-403
- §2.5 — insert — ambiguity — `rearing_capacity_lbs` <= 0 gives `density_index` 0.0000 flat, so such a station never restricts on density nor trips the feed cap — calc.py:59-63
- §2.6 — insert — ambiguity — the freeze cascade does not re-evaluate the posture that fired it: the returned acre-feet are credited but the station stays `FROZEN` on that write — derive.py:194-199
- §3.4 — insert — ambiguity — the whole-day span is signed and truncated toward zero, so a backwards `fed_at` yields a negative divisor (and a sub-day backwards span yields null) — calc.py:89-95

Disposition of the 7 items deferred to pass 4: (1) both §3.8 defects **FIXED** (`stocking_plan_count` -> `plan_target_count`; `NORMAL` -> `OPEN`). (2) `density_index` with non-positive capacity **FIXED** in §2.5; reachable because §3.1 already pins that a zero/negative `rearing_capacity_lbs` is accepted. (3) Negative growth-rate span **FIXED** in §3.4. (4) Load gate reads `status` only — **FIXED** in §3.8, including the reachability path. (5) `recompute_water` full rescan — **NO CHANGE NEEDED**: pass 2 already rewrote §3.6's closing sentence as full-rescan definitions, exactly matching derive.py:117-132. (6) `priority_score` and rounding modes — **CONFIRMED**, no change: matches §3.6 step for step including flat terms after the multiplier and clamp-then-quantize; every `q`/`q2`/`q3`/`q4`/`round_int` is ROUND_HALF_UP, `floor_int`/`ceil_int` are ROUND_FLOOR/ROUND_CEILING, every §2.9 scale matches its call site. (7) `quarantine_lot` — **2 edits**; `apply_clock` sweeps — no change needed (§2.4/§3.5 already pin strict `>` for certificate lapse and `>=` with `AVAILABLE`-only for unit expiry); `close_plan_if_complete`'s non-empty precondition — **LEFT deliberately**, its only call site provably never passes an empty attached set, so documenting it would pin dead code.

---

### Pass 5 of 5 — RECONCILIATION

**1a — §3.8 transport-unit paragraph, unconditional release/abort return. FIXED IN DOCUMENT.** All three hand-back sites guard identically on `unit["current_event_id"] == event["id"]` — routes_event.py:321-325 (release), routes_event.py:369-373 (abort), derive.py:255-259 (quarantine cascade). Pass 3's general sentence was the wrong one. Softened line 301 to "finishing the trip the unit still records there — by releasing it or by aborting it — returns the unit to `AVAILABLE`...", plus one sentence naming `current_event_id` as the whole of the coupling and stating that release, operator abort and the §3.5 quarantine cascade all hand back only the truck that still records the finishing trip. The three later narrowing clauses (lines 259, 321, 323) are now restatements of one rule rather than three exceptions. Also aligned the abort clause (line 323), which alone used the divergent phrasing "when the unit was `IN_USE` for this trip", and extended it to cover the reassigned-truck case it had omitted.

**1b — "such a unit can no longer be booked". ADJUDICATED FINE as pass 4 left it.** `create_stocking_event` (routes_event.py:36-121) resolves the three body ids, scopes on the lot, and never reads `unit["status"]`; the only status refusal is routes_event.py:206 at load. No surviving sentence in §3.8 claims scheduling gates on unit status. The neighbouring claim that `OUT_OF_SERVICE` "is terminal" also checks out: derive.py:342-346 only ever sweeps `AVAILABLE` units, and nothing moves a unit out of `OUT_OF_SERVICE`.

**1c — §2.1 ownership/scope wording. FIXED IN DOCUMENT; §3.6 restatement kept local.** Pass 2's enumeration verified from source rather than on trust: the scoped single-record reads are routes_hatchery.py:88, routes_brood.py:71 and :181, routes_lot.py:26, routes_plan.py:62, routes_transport.py:51, routes_event.py:138 — seven, exactly the seven the document names — plus the one scoped list at routes_hatchery.py:98. `routes_health.py` contains no `scope_hatchery` at all, so `GET /health-inspections/{id}` is correctly the single unscoped station-bearing read. "Scope applies to every `HatcheryManager` write" is also true: every route whose `authorize` includes `HATCHERY_MANAGER` calls `scope_hatchery`. Enumeration left as pass 2 wrote it. Instead: §2.10 level 3 now carries the general found-first rule (level 4 runs ahead of it for URL-addressed records; level 5 for body-identifier-borne scope), and §3.6's sentence was reworded to "As the found-first rule of sections 2.1 and 2.10 has it..." and kept local, since it carries attach-and-withdraw specificity that does not belong in §2.10.

Unflagged incoherence found and fixed:
1. §2.1's "never a 404, and never a request-shape complaint" vs §3.8's trip-creation insert. Pass 1 wrote the absolute; pass 3 then documented (correctly, per routes_event.py:41-44) that an out-of-scope `lot_id` plus an unknown `transport_unit_id` yields `ERR_TRANSPORT_UNIT_NOT_FOUND`. Fixed at §2.1: the claim now scopes to "a 404 about that record or a shape complaint about the identifier that named it", followed by the multi-identifier qualification and a pointer to §3.8.
2. §2.10's clean level-5-above-level-6 split vs §2.11's body-identifier insert. `v.req_id` shape-checks each identifier immediately before its own `get_or_404`, so a malformed identifier beats a later identifier's 404 while an earlier 404 still beats a later shape failure. Added that interleaving to level 5, plus the verified fact that all remaining scalar fields are shape-validated only after every body FK resolves (checked in `create_stocking_event`, `create_stocking_request`, `create_effluent_reading`, `create_brood_stock`, `create_spawn_event`, `create_transport_unit`, `create_allocation_plan`, `create_health_inspection`, `attach_request_to_plan`).
3. §4 abort row vs newly-narrowed §3.8 prose: "returning ... the grant and the truck" now reads "and whichever truck was still holding the trip".

Checked and adjudicated fine (no edit): the `recovered_count`/`transport_mortality_count` open-at-0 rule is double-pinned in §3.8 and §3.9 but the two statements agree, and §3.8's null-field enumeration correctly excludes the two computed fields `effective_marked_count` and `oxygen_flow_lpm`; §2.9's trailing-zero rule matches serialize.py's Decimal -> float; §2.3's discharge ordering matches routes_hatchery.py:106; §3.7's production-guard placement matches routes_request.py:157-171 exactly; §4's certify row matches routes_health.py:178-190; §4's clock row matches routes_hatchery.py:32; the §4 preamble's "ten collection-level POSTs answer 201" matches exactly ten `return created` call sites; §3.9's index-nullity rules match `calc.contribution_indices`.

Integrity checklist: **436 lines**, unchanged by this pass (all edits in-paragraph); the 435->436 delta versus PRD_FINALIZED.md is still the single added §2.2 bullet. Final line still `| \`ERR_BUDGET_EXCEEDED\` | 422 |`. §4: **47 endpoint rows**. §5: **46 error rows**, diffed byte-for-byte against the 46 entries of errors.py's status map — ERRORS_MATCH. No new sections: `grep '^#'` identical between PRD_FINALIZED.md and PRD_COMPLETED.md (28 headings). No broken tables: every §4 row has a uniform 5 pipes, every §5 row a uniform 3. Token sweep re-run post-edit: 305 distinct backticked tokens, 4 unmatched — `AllocationPlan`, `RearingLot` (prose entity names), `POST`, `false` (JSON literal), all benign.

Final: **PRD_COMPLETED.md 436 lines, 136,624 chars** vs PRD_FINALIZED.md 107,318 chars. Total char-delta **+29,306** across all five passes (+2,407 from pass 5).

---

**Orchestrator verification of Step 9:** `workspace/PRD_COMPLETED.md` exists at 436 lines / 136,624 chars and is confirmed **not** byte-identical to `PRD_FINALIZED.md` (`cmp -s` differs), so the scan genuinely ran. The file ends on the last row of the §5 error table — not truncated. `find workspace/implementation -name '*.py' -newer results.1.json` returns nothing, so no pass touched the implementation and the 8/8 green sweep recorded in Step 7 still describes the shipped code exactly.

## Pipeline complete — 2026-09-06T05:36:00.000Z

All nine steps finished. Deliverables: SCAFFOLD.yaml (2482 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (2310), SCAFFOLD_CORNER_DESIGN.yaml (3742), workspace/PRD.md (435), workspace/PRD_FINALIZED.md (435), workspace/PRD_COMPLETED.md (436), test_helpers/ (9 files, 2571 lines), test_suite/ (14 files, 6469 lines, 140 tests), workspace/implementation/ (19 modules + start.sh, 3117 lines), and results.1-8.json all recording 140/140.
