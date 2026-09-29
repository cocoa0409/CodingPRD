# Worklog: task_2988_shellfish_aquaculture_harvest_area_classification

## Step 1: Create task directory — 2026-09-06T02:07:18.93821949Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2988_shellfish_aquaculture_harvest_area_classification and its workspace/ subdirectory. Index 2988 was pre-assigned by the invoker; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-06T03:41:40.139Z

Done. All three scaffold artifacts are in place and verified.

**Files written (only additions; `worklog.md` and `workspace/` untouched, `.scratch/step2` removed)**

`/home/ubuntu/github/CodingPRD/tasks/task_2988_shellfish_aquaculture_harvest_area_classification/`

| file | lines | contents |
|---|---|---|
| `SCAFFOLD.yaml` | 3083 | `scenario`, `domain_name: shellfish-harvest-classification`, `api_prefix: /shellfish`, `complexity_profile`, `response_envelope`, **15 entities**, **10 state machines**, **2 concurrency rules**, **14 calculations**, **79 validations**, **64 endpoints**, **79 errors**, **5 roles**. No `scaffold_*_design` keys; the difficulty directive string appears nowhere in it. |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2585 | single key `scaffold_difficulty_design`; **9 rule_ids, 22 instances** (>=2 each) |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6489 | single key `scaffold_corner_design`; **9 sections, 90 instances** = 75 full `test_recipe`s + 15 `excluded_because` stubs |

**§1.8 rule ids** (in file order): `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

**§1.9 sections** (instances / of which stubs): `entities` 12/0, `state_machines` 13/4, `calculations` 13/4, `validations` 29/2, `endpoints` 4/1, `errors` 4/0, `rbac` 7/0, `cross_cutting_complexity_layers` 7/4, `consistency_model` 1/0.

**Verification**
- All three files `yaml.safe_load` cleanly and end on real structural boundaries.
- Zero duplicate instance names across the union of both design files (22 + 90); every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name, and every stub carries exactly `{difficulty_instance, rationale}` with no `test_recipe`.
- Zero unbound `${var}` in any `call`/`payload`/`as_user_id` **or** `assert` line (one real defect found and fixed: `shipment_ship_blocked_by_unlisted_dealer` in §1.8 was missing `captures: { auth: $.data.id }` on its `POST /shellfish/harvest-authorizations` call).
- One bad ground fixed: `calculations.time_to_temperature_minutes` -> `calculations.harvest_lot_time_to_temperature`. All machine-checkable grounds now resolve into §1.1–§1.7.
- All 79 error codes are now referenced by at least one design instance.

**Linter verdict**: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5. (64 endpoints, 15 entities, 22 §1.8 instances, 75 §1.9 instances, 1656 calls scanned.)

## Step 3: Copy shared files — 2026-09-06T03:41:40.162Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-06T04:01:30.966Z

PRD generation complete.

**Output:** `workspace/PRD.md` — **556 lines**, 122,784 bytes, built incrementally (1 `Write` + 5 heredoc appends + 3 small targeted `Edit`s), never a single giant write.

**Headings (complete list):** `# Shellfish Harvest Classification API — PRD`; `## 1. Introduction`; `## 2. Global Specifications & System-Wide Principles` (2.1 Actors/Identity/RBAC, 2.2 API Response Structure, 2.3 Pagination and List Ordering, 2.4 Resource Identity/Timestamps/Record Versions, 2.5 The Logical Clock and Temporal Admissibility, 2.6 Path Resolution and Referential Existence, 2.7 Validation Precedence, 2.8 Optimistic Concurrency on Classification and Certification Records, 2.9 Measurement Precision/Rounding/Money, 2.10 Cascade Discipline and Compensating Reversals); `## 3. Business Logic & Workflows` (3.1 Growing Area registration + sanitary classification, 3.2 Water-quality monitoring/statistics window/automatic downgrade sweep, 3.3 Rainfall closures and the road back to OPEN, 3.4 Lease acquisition: two clearance legs/revision cycles/decision, 3.5 Seed: hatchery certificates/screening/nursery grow-out, 3.6 Grow-out gear/plot occupancy/husbandry currency, 3.7 Vessels/harvest authorizations/harvest cycle, 3.8 Landing a lot: time-to-temperature/vibrio allowance/lease settlement, 3.9 Tagging/dealer certification/shipping/recall chain); `## 4. API Endpoints`; `## 5. Error Codes`.

**Tail confirmed to end at a real section boundary** (orchestrator independently verified): last line is the final complete row of the §5 error table (`| ERR_LEASE_RENT_DELINQUENT | 402 |`). No truncation.

**Hard Contract reports:**
- **Contract 1 — Field-Name Coverage: PASS.** 174 required identifiers machine-diffed against backticked tokens in PRD.md. First pass surfaced one genuine gap (`harvest_authorization_id`), added in §3.8; re-run shows zero misses.
- **Contract 2 — Rule Coverage: PASS.** All 79 catalogue error ids appear in §1–§3 prose (set-compared both directions: no scaffold id unmentioned, no invented id). All 72 validation rows rendered as a 14-rung precedence ladder in §2.7 and restated in situ per workflow. All 6 state machines and every declared transition covered, including the sibling-branch asymmetry of the two lease objections, the cyclic `DEPLOYED`<->`HARVESTING` oscillation, the compound `READY_FOR_PLANTING`<->`PLANTED` bubble-up, the `CLOSED_RAINFALL`->`CLOSED_RAINFALL` closure restart and its two non-transition edge cases, and the `PROHIBITED` coupling. All 13 calculations given step-ordered prose with rounding points; 29 of 31 scaffold constants already named, and the two stated only by value (`DEFAULT_RAINFALL_CLOSURE_HOURS`, `DEFAULT_REOPEN_SAMPLE_COUNT`) are now named in §3.1. Both concurrency rules (`expected_area_version`, `expected_dealer_version`) in §2.8, with a statement that no other endpoint takes a version field. Field-level defaults, computed-field visibility, list ordering (including the five journal overrides) and pagination shape all explicit.
- **Contract 3 — §3 Path Purity: PASS.** Mechanical scan of §3: zero backticked `/`-tokens, zero bare HTTP method words, zero method+path pairs. Paths appear only in §1/§2 and the §4 table.

§4 carries all 64 endpoints in scaffold order with status-code rules in prose and no bodies. §5 carries all 79 error ids with HTTP statuses.

**Constraints honoured:** neither design YAML was opened/grepped/referenced; no sibling task touched; `worklog.md`, `SCAFFOLD*.yaml`, `workspace/INSTRUCTION.md` unmodified.

**Scaffold inconsistencies flagged by the doc generator (adjudications, PRD side chosen):**
1. Lease-creation `side_effects` say the two clearance fields start at `NOT_STARTED`, but the field enum is `PENDING | CLEARED | OBJECTION` with `default: PENDING`. PRD uses `PENDING` throughout.
2. Scaffold auth validation names the header `X-Role` while the skill mandates `X-User-Role`. PRD uses `X-User-Role`.
3. `IllnessInvestigation.traced_lot_ids` field description says "ordered by `created_at` ASC" while the owning calculation says `(tag_harvest_date ASC, created_at ASC)`. PRD uses the calculation's ordering.

## Step 6: Generate implementation — 2026-09-06T04:42:16.550Z

Implementation complete and smoke-verified.

**File inventory (`workspace/implementation/`, 4,499 lines total)**

| File | Lines | Role |
|---|---|---|
| `core.py` | 755 | constants, logical clock, in-memory `Store`, envelope, shape validators, pagination, RBAC, entity lookups |
| `calc.py` | 546 | all 13 calculations (statistics window, geo-mean/p90, allowance derivation, TTT bases, royalty tiers, settlement, traceback set) |
| `routes_area.py` | 423 | 10 growing-area endpoints (registration, classification ladder, reopen, samples, rainfall, summary) |
| `serializers.py` | 320 | per-entity field lists; append-only trio omits `updated_at`/`version` |
| `routes_growout.py` | 304 | deployment gauntlet, husbandry journal, retrieve, void |
| `routes_seed.py` | 284 | hatcheries, seed shipments, screening, nursery |
| `routes_harvest.py` | 283 | vessels, authorization issue/activate/close |
| `routes_lot.py` | 268 | landing, settlement, tagging, void |
| `routes_shipment.py` | 244 | assembly, shipping, investigations-by-shipment |
| `routes_lease.py` | 245 | draft, submit, two review legs, decision |
| `cascades.py` | 197 | 4 cascades (area closure, seed rejection, dealer-suspension hold, 4-hop recall) |
| `errors.py` | 175 | 79 error codes + statuses + default messages |
| `routes_dealer.py` | 139 | certification, renewal (OCC), suspend, reinstate |
| `routes_misc.py` | 103 | vibrio plans, logical clock |
| `app.py` | 101 | app factory, blueprint mounting under `/shellfish`, error handlers |
| `routes_investigation.py` | 97 | traceback, confirm, close |
| `start.sh` / `requirements.txt` | 14 / 1 | launcher, `flask` |

`python3 -m compileall -q .` -> clean.

**Verifications**
- **Endpoints: 64/64.** Programmatic diff of Flask's `url_map` against every `method`+`path` in `SCAFFOLD.yaml`: `MISSING: []`, `EXTRA: []`.
- **Error codes: 79/79** referenced outside `errors.py` (programmatic scan of all modules against `ERROR_STATUS` keys).
- **Storage:** in-memory only. `Store.reset()` assigns 15 empty dicts; grep for `sqlite|open(|json.dump|pickle|shelve|/tmp` returns nothing. Fresh boot answered `total_count=0` on all eight list endpoints — no seeding.
- **start.sh:** `set -euo pipefail`, `cd "$(dirname "$0")"`, guarded install, `export PORT="${PORT:-10000}"`, `exec python3 app.py`; Flask binds `0.0.0.0` with `debug=False, use_reloader=False`, foreground.

**Smoke test** (random port 40639, killed by PID; a first attempt on 41337 hit a sibling pipeline's server, so the port is now probed for availability first): 70 requests, all matching expected status, all inline assertions passing (`SMOKE PASSED`). Covered: envelope shape (`meta.api_request_id` = `req_` + 20 chars, `response_type`, `data`), error body (`{error_id, message}` only), 401/403/404/400-pagination, area registration + duplicate code 409, OCC 412 on both area and dealer, 5-sample statistics + `eligible_classification=APPROVED`, rainfall closure -> `CLOSED_RAINFALL` -> `ERR_REOPEN_TOO_EARLY` -> clean-sample reopen, full lease chain incl. `ERR_SEGREGATION_OF_DUTIES`, hatchery ownership 403, seed screening/nursery (incl. `ERR_NURSERY_PERIOD_TOO_SHORT`), deployment (`ERR_PLOT_NOT_IN_LEASE`, then the `PLANTED` bubble-up), husbandry currency, authorization refusal while closed then issue/activate/double-activate 409, `ERR_NO_VIBRIO_PLAN_FOR_SEASON` then landing with `allowed_ttt_minutes=210` (240-60-30+60) and settlement (`royalty 1150`, `fee 2500`, `surcharge 110`, `total 3760`), tag-date mismatch then tag, interstate shipment, cold-chain 409 then ship, and the confirm cascade (lot->`RECALLED`, shipment->`RECALLED`/`ILLNESS_TRACEBACK`, dealer strike 1, still `LISTED`).

**Two judgement calls flagged to Step 7**
1. **Ship-endpoint rung 13 order** is `CERTIFICATION_EXPIRED -> SUSPENDED -> NOT_LISTED -> NOT_LISTED_FOR_INTERSTATE -> LOT_NOT_TAGGED`: §2.7 puts the interstate check before those two listing checks, but PRD 3.9 explicitly states a `NOT_LISTED` dealer must be refused with `ERR_DEALER_NOT_LISTED` (and an expired cert forces a stale ICSSL window, which would otherwise mask `ERR_DEALER_CERTIFICATION_EXPIRED`).
2. **Cross-field `ERR_INVALID_REQUEST` checks sit at rung 5**, so `nursery_started_on < shipped_on` precedes the seed-lot state gate, and the dealer-renewal date checks precede the OCC check.

Also added `MIN_PLAN_BASELINE_MINUTES = 60` to `core.py` and made the vibrio temperature trigger compare at one decimal place (`q(water_temp_c,1) >= q(high_water_temp_c,1)`) per PRD §3.8, while storing the submitted temperatures verbatim for echo. Scratch dir `.scratch/step6` removed; siblings `step4`, `step5`, `step7` untouched.

## Step 5: Generate unit tests — 2026-09-06T05:02:32.381Z

(Recorded after Step 6 because Steps 5 and 6 ran concurrently in a single message; Step 5's subagent exited later. Both were launched together to give the implementation generator physical isolation from `test_suite/`.)

Step 5 is complete.

**File inventory** — `test_helpers/` 2,022 lines: `__init__.py` 43, `api_client.py` 321, `api_errors.py` 176, `assertions.py` 464, `constants.py` 95, `factories.py` 409, `fixtures.py` 982, `test_users.py` 88, `types.py` 557.

`test_suite/` — 6,003 lines (lines / tests / file):
54 / – / `conftest.py`; 278 / 5 / `test_01_water_quality_statistics_variants.py`; 271 / 7 / `test_02_growing_area_closure_and_reopen_boundaries.py`; 208 / 5 / `test_03_lease_and_dealer_lifecycle_cycles.py`; 333 / 8 / `test_04_authorization_gates_and_boundaries.py`; 237 / 6 / `test_05_deployment_plot_and_seed_dependencies.py`; 197 / 6 / `test_06_landing_settlement_arithmetic.py`; 292 / 7 / `test_07_time_to_temperature_compliance.py`; 355 / 8 / `test_08_cascades_and_dealer_recall.py`; 530 / 12 / `test_09_entity_contracts_and_read_backs.py`; 527 / 9 / `test_10_state_machine_transitions.py`; 444 / 7 / `test_11_derived_calculations.py`; 579 / 14 / `test_12_validation_ladder_part_one.py`; 661 / 13 / `test_13_validation_ladder_part_two.py`; 606 / 11 / `test_14_endpoint_error_and_concurrency_contracts.py`; 431 / 7 / `test_15_role_based_access_control.py`.

**Counts.** **125 test functions**, all collected by pytest (`125 tests collected`), `compileall` clean.
- **Queue A (Difficulty): 50 tests / 22 of 22 instances**, every instance with >=2 tests.
- **Queue B (Corner): 75 tests / 75 of 75 non-stub instances**, every instance with >=1 test.
- Every file has >=5 tests.

**Instances SKIPPED: none.** Every non-stub instance in both design indices passed the PRD-first two-condition filter — a verbatim PRD sentence names each rule and uniquely derives each asserted outcome. No `skip`, `skipif`, `xfail` or placeholder tests anywhere. All 15 `excluded_because:` stubs in the corner index were checked programmatically: every `difficulty_instance` cross-reference resolves to a real §1.8 instance name, and no test carries a tag pointing at a stub.

**Documented deviations (never weakenings; each stated in the owning test's docstring)**
- **Unestablished list filters.** Design assertions written as `GET ...?lease_id=` / `?vessel_id=` / `?sample_status=` / `?season_month=` / `?hatchery_id=` / `?dealer_id=` are asserted against the *unfiltered* list endpoint, because the PRD text does not establish those query-parameter names, and each test starts against an empty database, making the unfiltered form equally exact.
- **Unreachable-as-written recipes** implemented in their reachable form, always keeping the rule under test: the fallow-buffer boundary success (an earlier temporal ladder rung would answer `ERR_FUTURE_DATED_EVENT` first, so the clock is advanced); absolute `version` literals replaced by relative increments where sample ingests bump the version; recipe HTTP 201s corrected to the PRD's declared 200 for classification decisions.
- **Symbol corrections against the PRD:** `ERR_VESSEL_CAPACITY_EXCEEDED` -> `ERR_VESSEL_CAPACITY_CONFLICT`; boolean `navigation_cleared`/`environmental_cleared` -> the `navigation_clearance`/`environmental_clearance` enums; a lease-review recipe's `UNDER_REVIEW` -> the uniquely derived `PENDING_DECISION`.
- All settlement, statistics, survival-rate and time-to-temperature figures were reproduced independently with `Decimal`/`ROUND_HALF_UP` before being asserted.

**Confirmations**
1. Both directories are at the task root and **absent from `workspace/`** (orchestrator independently verified: `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`). `workspace/implementation/` was never read, listed or grepped; nothing in `workspace/` was created, modified or deleted; `worklog.md` and the three `SCAFFOLD*.yaml` files were not touched. `test_helpers/` source mtimes all predate the queue-B workers, confirming no worker edited shared fixtures.
2. **Every one of the 125 tests carries exactly one `Design:` tag** as the final line of its docstring (orchestrator independently verified: 50 Difficulty + 75 Corner = 125). Programmatic validation against both YAML indices reports no unknown tags, no dual tags, no tags on excluded stubs, no uncovered instances in either queue.

## Step 7: Run tests and iterate — 2026-09-06T05:25:20.407Z

All 8 rounds clean at 125/125. Done.

**Iterations run:** 2 (iteration 1: 115-116/125 across the 8 rounds; iteration 2: 125/125 in all 8 rounds).

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule and survived the unique-derivability check; all 10 failures were test-artifact bugs.

**Fixes applied to `test_helpers/`:** none — the shared helpers were correct; the bugs were at the call sites.

**Fixes applied to `test_suite/`:**
- `test_suite/test_06_landing_settlement_arithmetic.py` — `_two_identical_ten_bushel_lots` and `_five_hundred_bushels_then_one_more`: added `set_clock(DW_HARVEST_CLOCK)` after `design_world(stage="active")`. `design_world` only applies `harvest_clock` at stage `landed` or beyond, so at stage `active` the logical clock sat at the activation instant `2026-08-10T06:00:00Z` while the reference landing instants run to 10:30 — the PRD-faithful implementation correctly refused with `ERR_FUTURE_DATED_EVENT` (§2.5). Fixed 6 tests.
- `test_suite/test_07_time_to_temperature_compliance.py` — same clock-parking bug in `_conditionally_approved_world_with_one_lot` (lot placed in temperature control at 10:40) and in `test_one_minute_past_the_allowance_lands_but_cannot_be_tagged` (10:31); added `set_clock(iso(2026, 8, 10, 11))` before each landing. Fixed 3 tests.
- `test_suite/test_11_derived_calculations.py` — `_investigation_over_one_shipped_lot_with_a_tagged_sibling`: added `LOT_B_LANDED_CLOCK = iso(2026, 8, 10, 12)` and a `set_clock` before landing LOT-B. This was the one genuinely flaky test (failed in rounds 2, 4, 6, 7). Both lots share `tag_harvest_date` `2026-08-10`, and because both were landed at the same frozen logical clock they also shared `created_at` to the millisecond. PRD §3.9 orders `traced_lot_ids` by `tag_harvest_date` then `created_at` and declares no third tie-break, so with both keys tied the order was under-determined; the implementation falls back to `id` ascending, which is random UUID order, hence the ~50% failure rate. Giving LOT-B a strictly later `created_at` makes the PRD sentence uniquely determine the order rather than weakening the assertion or forcing an undeclared tie-break onto the implementation.

**Fixes applied to `implementation/`:** none. No implementation defect was found. In particular, the two judgement calls the implementation generator flagged (ship-endpoint rung-13 ordering and the rung-5 placement of cross-field `ERR_INVALID_REQUEST` checks) were never contradicted by any test, so no adjudication was needed.

**Final per-round results:** rounds 1-8 all `passed=125 total=125`. Results left at `workspace/implementation/results.{1..8}.json`.

**Orchestrator independent verification:** re-ran `.scratch/step7/summarize.py` (keyed on the runner's real `tests[].status` / `error_message` schema) against the eight on-disk results files. Per-round output: all eight `passed=125 total=125`; union of failing tests across all rounds = 0. All eight files share mtime `2026-09-06T05:17:38Z`, i.e. they are the final sweep, not stale iteration-1 artifacts.

**Step 8 decision:** Step 8 is NOT skipped — Step 7 ran 2 iterations with 3 `test_suite/` fixes, so the skip condition (zero iterations beyond baseline) does not hold. However there were 0 deletions and 0 `implementation/` fixes, so a byte-identical `PRD_FINALIZED.md` would be a legitimate outcome here; the one substantive PRD-silence candidate in the diff is the `traced_lot_ids` third-level tie-break.

## Step 8: Finalize PRD — 2026-09-06T05:34:41.839Z

`PRD_FINALIZED.md` is written.

**Line counts:** `PRD.md` 556 lines / 122,784 bytes; `PRD_FINALIZED.md` 556 lines / 123,750 bytes. Line-count delta 0% (3 lines revised in place; +966 bytes, +0.79% by size). **Not identical.** (Orchestrator independently verified with `cmp`: differs; 6 diff lines = 3 revised lines; all 27 headings intact; tail still ends on the final §5 error-table row.)

**Changes (3)**
- **§3.9, "The traceback"** — *revise* — added `id` ascending as the declared final tie-break for `traced_lot_ids` (PRD previously stopped at `tag_harvest_date` then `created_at`, leaving the order under-determined; exactly the silence Step 7's flaky `test_11` exposed) — `implementation/calc.py:539-545`.
- **§2.7 rung 13** — *revise* — appended a sentence stating that the shipment-release endpoint is the one endpoint whose internal order within rung 13 differs, giving that order explicitly (`ERR_DEALER_CERTIFICATION_EXPIRED`, `ERR_DEALER_SUSPENDED`, `ERR_DEALER_NOT_LISTED`, `ERR_DEALER_NOT_LISTED_FOR_INTERSTATE`, `ERR_LOT_NOT_TAGGED`), plus an explicit "every other endpoint follows the order listed above" — `implementation/routes_shipment.py:166-183`.
- **§3.9, "Shipping"** — *revise* — pinned the same order in the narrative restatement and noted that per §2.7 the two `shipped_at` conditions (cold-chain ordering at the state rung, future-dating at the temporal rung) are judged before all five — `implementation/routes_shipment.py:145-183`.

**Per-edit pre-edit search log**

*Edit 1 — `traced_lot_ids` ordering.* (a) Subject: the comparator used for `traced_lot_ids` and any list/derived ordering sharing that pattern. (b) Enumerated & read: `calc.py:539-545` (three keys: `tag_harvest_date`, `created_at`, `id`); `core.py:619-628` (`sort_default` = `created_at, id`; `sort_journal` = stable two-pass yielding key -> `created_at` -> `id`); `calc.py:150-152` `_sample_order_key` = `collected_at, created_at, id` (used at `calc.py:162`, `calc.py:240`); `calc.py:426` `(created_at, id)`; `cascades.py:27` `(created_at, id)`; `routes_lot.py:194` `(created_at, id)`; all `sort_default`/`sort_journal` call sites in `routes_area.py:149/347/418`, `routes_growout.py:163/240`, `routes_harvest.py:208`, `routes_lease.py:114`, `routes_lot.py:151`, `routes_misc.py:88`, `routes_seed.py:171`, `routes_shipment.py:129/239`. (c) Adjustment: every enumerated site already terminates in `id` ascending and §2.3 already declares that rule for list endpoints, so the addition was phrased as "the same three-key discipline §2.3 applies to list responses" rather than a traceback-only special rule. Deliberately did **not** touch the analogous silent third key at PRD line 238 (clean-sample run, `_sample_order_key`), since no Step 7 item traces there — left for Step 9.

*Edit 2 — §2.7 rung 13 internal order.* (a) Subject: evaluation order of every rung-13 error code at every endpoint that raises one. (b) Enumerated & read (grepped all 10 rung-13 codes across `*.py`, then read each site): `routes_harvest.py:138-144` authorization issue -> CATEGORY(1), CERT_EXPIRED(3), UNIT_LEASE_MISMATCH(8), SUSPENDED(9) = **matches** §2.7; `routes_shipment.py:71-81` shipment assembly -> CERT_EXPIRED(3), LOT_NOT_TAGGED(4), LOT_DEALER_MISMATCH(5), SUSPENDED(9) = **matches**; `routes_lot.py:220-229` tagging -> TAG_HARVEST_DATE(6), TAG_DEALER_CERT(7), SUSPENDED(9) = **matches**; `routes_dealer.py:132` reinstatement -> CERT_EXPIRED alone = **matches**; `routes_shipment.py:166-183` ship = **the only divergence**. (c) Adjustment: because four of five sites do follow the declared order, the exception was scoped narrowly to the shipment-release endpoint with an explicit closing clause "Every other endpoint follows the order listed above", instead of loosening the rung's order globally (which would have mis-described the four conforming sites).

*Edit 3 — §3.9 "Shipping" restatement.* (a) Subject: the full check sequence of the ship endpoint, including the two `shipped_at` conditions. (b) Enumerated & read: `routes_shipment.py:135-188` — role/auth, `get_shipment`, ownership before `json_body()`, `status != CREATED` -> `ERR_INVALID_SHIPMENT_STATE`, cold-chain compare at second resolution (`shipped_at.replace(microsecond=0) < coldest.replace(microsecond=0)`) -> `ERR_INVALID_SHIPMENT_STATE`, `check_not_future_instant`, then the four dealer grounds, then the lot roster. Cross-checked `core.py` helpers `at_or_after_today`, `check_not_future_instant`, and §2.5's "instants compared at second resolution". (c) Adjustment: first draft said the five checks "run in this order" without qualifying where the `shipped_at` conditions sit; since the impl evaluates both *before* all five (rungs 7 and 10), the sentence was widened to state that explicitly and point at §2.7, so the paragraph's trailing `shipped_at` sentence is no longer readable as "checked last".

**Not edited (checked, no PRD/impl divergence found):** the rung-5 placement of the cross-field `ERR_INVALID_REQUEST` checks. `routes_dealer.py:77-86` (renewal: `certified_through` strictly future, `icssl_listed_through` <= `certified_through`) runs before the rung-6 `ERR_STALE_DEALER_VERSION` check; `routes_seed.py:226` (`nursery_started_on` >= `shipped_on`) runs before the rung-7 state check and the rung-10 future check; `routes_growout.py:194-201` (conditionally required `predator_species`/`control_method`) likewise. §2.7 already places rung 5 above rungs 6, 7 and 10, and §3.5/§3.6/§3.9 already name these as `ERR_INVALID_REQUEST`, so PRD already uniquely determines the impl's behaviour. The Step 7 logical-clock-parking fixes in `test_06`, `test_07` and `test_11` were pure fixture bugs against verbatim §2.5 and needed no PRD change.

## Step 9: Complete PRD — 2026-09-06T06:26:02.362Z

`workspace/PRD_COMPLETED.md` written. Per the known failure mode where a single-agent Step 9 produces a byte-identical file (i.e. never actually scans), the orchestrator ran Step 9 as **five sequential passes over one shared PRD_COMPLETED.md, partitioned by implementation module**, with the fifth pass dedicated to reconciliation. Pass 1 did the `cp`; passes 2-5 were forbidden from copying. Each pass could READ any module for context but could only EDIT prose whose subject its own modules own, reporting anything else as `CROSS-PASS OBSERVATIONS` for the reconciliation pass.

**Source vs output:** `PRD_FINALIZED.md` 556 lines / 123,750 bytes -> `PRD_COMPLETED.md` 558 lines / 146,169 bytes (+22,419 bytes, +18.1%; +2 lines, since nearly every edit was in-paragraph). 126 changed diff lines. **Total 77 edits across the five passes.**

Orchestrator-independent verification: `cmp` confirms PRD_COMPLETED.md differs from BOTH PRD.md and PRD_FINALIZED.md (the identical-file failure mode did not occur); 27 `^#` headings intact; tail still ends on the final §5 error-table row (`| ERR_LEASE_RENT_DELINQUENT | 402 |`); no stray test_suite/test_helpers under workspace/; the eight final sweep results still read 125/125 with a zero-length failure union.

### Pass 1 — core.py, serializers.py, errors.py, app.py, routes_misc.py (13 edits: 13 ambiguity-pins, 0 mismatches)

Three whole-table cross-checks came back clean, which is why pass 1 found no mismatches: `errors.py:ERROR_STATUS` matches §5 row-for-row and in the same order (79/79, no status divergence); the 64 `(method, path)` pairs in §4 match the registered routes exactly; every §4 Authorized-Roles cell matches the `authenticate(...)` role list.

- §2.1 — insert — ambiguity — whitespace-only identity header counts as empty (`ERR_UNAUTHENTICATED`); role match exact/case-sensitive; header values never trimmed — `core.py:638-649`
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + exactly 20 chars from `A-Z0-9`, total length 24, minted per response, never persisted — `core.py:213-217`
- §2.2 — insert — ambiguity — single-object `meta` carries exactly `api_request_id` + `api_request_timestamp` — `core.py:318-335`
- §2.3 — insert — ambiguity — `limit`/`offset` parsed as whole decimals tolerating whitespace and a leading sign; `2.5`/empty/non-numeric -> 400; `offset` past `total_count` yields empty `data` with true `total_count` and `has_more` false — `core.py:544-566,615-616`
- §2.3 — insert — ambiguity — integer filters must be whole and in range; boolean filters accept only `true/True/TRUE/false/False/FALSE`; identifier filters must be non-empty; unknown-but-valid id filter is an empty page, not 404 — `core.py:569-612`
- §2.4 — insert — ambiguity — **one** `version` advance per row per request, not one per touch; `updated_at` stamped at the first change — `core.py:270-301`
- §2.4 — insert — ambiguity — `husbandry_current`, `is_adverse_condition`, `counted_clean` are derived at serialisation time; all other derived fields are stored; the seven `*_note` inputs are validated then discarded (only the husbandry log's `notes` is materialised) — `serializers.py:125,156,157` + 7 route sites
- §2.5 — insert — ambiguity — clock-set `to_iso8601` required, may precede or follow the current reading, exempt from future-dating; response is that one field only — `routes_misc.py:96-103`
- §2.5 — insert — ambiguity — accepted instant syntax (`T`/`t`, 1-9 fractional digits, `Z`/`z` or `±hh:mm`/`±hhmm` normalised to UTC, **no designator = UTC**); rendered back at 3 digits by truncation — `core.py:451-496,168-183`
- §2.6 — insert — ambiguity — a body FK that is absent/`null`/non-string/blank is 400, not the entity's 404 (resolves the rung-3-vs-rung-5 tension) — `core.py:726-733`
- §2.7 rung 5 — insert — ambiguity — absent/empty body = `{}`; non-object or invalid JSON -> 400; explicit `null` == absent (optional fields take their default); blank/whitespace strings rejected unless blank is allowed; integer fields reject booleans and `3.0` — `core.py:353-418`
- §3.8 — insert — ambiguity — all four vibrio-plan publication inputs required; `high_water_temp_c` carries no range constraint — `routes_misc.py:39-46`
- §5 preamble — insert — ambiguity — unrouted path -> `ERR_INVALID_REQUEST` at **404**; wrong method -> `ERR_INVALID_REQUEST` at **405**; trailing slash equivalent; no 5xx ever (unhandled failure -> `ERR_INVALID_REQUEST` 400) — `app.py:43,56-91`

### Pass 2 — calc.py, cascades.py, routes_area.py (19 edits: 16 ambiguity-pins, 3 mismatch-revisions)

- §3.2 — revise — **mismatch** — struck "ties by `created_at` ascending **and by nothing else**"; pinned the real three-key order `collected_at`, `created_at`, `id` — `calc.py:150-152`
- §3.3 — revise — ambiguity — clean-sample run: added `id` as third ordering key; run is 0 when `last_closure_started_at` is null — `calc.py:227-248`
- §3.2 — revise — **mismatch** — supersession said "any **earlier** sample"; impl demotes any previously ingested accepted row for the same station/day whether its `collected_at` precedes or follows — `routes_area.py:298-305`
- §3.1 — revise — **mismatch** — "a request naming the classification the area already holds is likewise `ERR_CLASSIFICATION_STEP_SKIPPED`" is false for `APPROVED`/`CONDITIONALLY_APPROVED`: restating is not a strict downgrade, so the data-support rung (judged first) yields `ERR_CLASSIFICATION_NOT_SUPPORTED_BY_DATA` — `routes_area.py:160-203`
- §4 water-samples row — insert — ambiguity — declared the implemented `sample_status` filter — `routes_area.py:341-345`
- §4 rainfall-events row — insert — ambiguity — declared the implemented boolean `triggered_closure` filter — `routes_area.py:412-416`
- §3.2 — insert — ambiguity — adverse window closed at **both** ends; samples strictly before the event excluded; one qualifying event suffices; non-triggering events ignored — `calc.py:116-126`
- §3.2 — insert — ambiguity — the `ADVERSE_CONDITION` filter is applied **before** the 15-row cap, and eligibility reads the smaller window's own count (<5 => `INSUFFICIENT_DATA`) — `calc.py:154-165`
- §3.1 — insert — ambiguity — within each cascade hop rows are visited `created_at` ASC, ties `id` ASC — `cascades.py:26-27`
- §3.1 — revise — ambiguity — `rainfall_closure_threshold_in` finer precision rounded half-up to 2dp on store, not refused — `routes_area.py:107`
- §3.1 — revise — ambiguity — `clean_sample_mpn_limit` carries no range constraint, stored at the precision supplied — `routes_area.py:88-93,110`
- §3.3 — revise — ambiguity — `inches_24h` rounded half-up to 2dp on store — `routes_area.py:370`
- §3.3 — insert — ambiguity — **the rounding precedes the threshold comparison**: 0.995 vs a 1.00 threshold triggers — `routes_area.py:370-371`
- §3.3 — insert — ambiguity — reopen's `consecutive_clean_samples = 0` is repopulated by the next accepted-sample ingest, because `last_closure_started_at` is retained and the run recomputed from it — `routes_area.py:254-261` + `calc.py:227-248`
- §3.5 — insert — ambiguity — seed-rejection hop 2's returned seed lifts `unallocated_seed_count` above 0 but the lot stays `REJECTED` (no `READY_FOR_PLANTING` bubble-up) — `cascades.py:115-116`, `calc.py:362-366`
- §3.9 — insert — ambiguity — `BROAD` expansion is a **single, non-transitive** hop out of the seed set; a candidate matching several seeds enters once — `calc.py:519-537`
- §3.8 — revise — ambiguity — `royalty_accrued_cents` sums `lot_settlement_cents` over all lease lots whose status is not `VOIDED` (embargoed/recalled still contribute) — `calc.py:339-344`
- §3.6 — insert — ambiguity — `deployed_gear_units` sums `DEPLOYED`+`HARVESTING` units, so the oscillation never moves it — `calc.py:331-336`
- §3.8 — revise — ambiguity — `ttt_basis_variant` is `LAST_HARVEST_BASIS` for *every* classification other than `APPROVED`, not just the two enumerated — `calc.py:451-454`

### Pass 3 — routes_lease.py, routes_seed.py, routes_growout.py (19 items across 15 edits: 13 ambiguity-pins, 6 mismatch-revisions)

- §3.4 Drafting — revise — **mismatch** — `lease_code` was declared "unique across all leases"; impl enforces no uniqueness and no duplicate-lease-code error exists — `routes_lease.py:54`
- §3.4 Drafting — insert — ambiguity — drafting is not gated on area classification; a `PROHIBITED` area still accepts a draft (only submit/decision guard it) — `routes_lease.py:48-85`
- §3.4 Submission — revise — ambiguity — added the missing state precondition (only `DRAFT`/`REVISION_REQUESTED`; else `ERR_INVALID_LEASE_STATE`) and pinned the ownership->state->prohibited order — `routes_lease.py:124-138`
- §3.4 Review legs — insert — ambiguity — the lease's own `status` must read `UNDER_REVIEW` as well as the leg reading `PENDING`; after an objection the sibling leg is refused `ERR_INVALID_LEASE_STATE` despite still being `PENDING` — `routes_lease.py:172-173`
- §3.4 Decision — insert — ambiguity — a `rent_paid_through_date` supplied on `DENY` is shape-checked then discarded — `routes_lease.py:212-244`
- §3.5 Hatcheries — revise — **mismatch** — `ncsp_certificate_no` "unique across hatcheries" is not enforced — `routes_seed.py:67`
- §3.5 Sanitary gates — insert — ambiguity — certificate-age arithmetic is signed/one-sided (issued after shipment passes); `disease_cert_issued_on` is not a future-dating field; only `shipped_on` is, checked after all three gates — `routes_seed.py:119-122`
- §3.5 Screening — revise — **mismatch** — PRD listed `ERR_SCREENING_DATE_INVALID` before the future-dating check; impl checks future first (matches rung 10) — `routes_seed.py:192-194`
- §3.5 Nursery start — insert — ambiguity — the `nursery_started_on < shipped_on` 400 is a rung-5 failure reported *before* the `SCREENED` state check — `routes_seed.py:225-230`
- §3.5 Nursery complete — revise — **mismatch** + ambiguity — PRD ordered future-dating before the 21-day period check; impl (and rung 10) do period first. Also pinned `surviving_seed_count` >= 0 — `routes_seed.py:257-265,254`
- §3.5 Compound bubble-up — revise — **mismatch** + ambiguity — the move is conditioned on the status the lot already holds (other statuses get counters rewritten but keep status -> the `REJECTED` exception); the recompute is full, not incremental; the trigger is "whichever request moved the gear: deployment, void, or the seed-rejection cascade" (PRD had said "inside the deployment request") — `calc.py:347-367`, `routes_growout.py:133/303`, `cascades.py:115-116`
- §3.6 Deployment guards — revise — **mismatch** — PRD listed `ERR_INVALID_DEPLOYMENT_WINDOW` before `ERR_FUTURE_DATED_EVENT`; impl checks future-dating first — `routes_growout.py:88-90`
- §3.6 Gear capacity — insert — ambiguity — the `DEPLOYED`<->`HARVESTING` oscillation moves neither seed counter nor lot status, because `allocated_seed_count` counts `DEPLOYED`/`HARVESTING`/`RETRIEVED` alike — `calc.py:351`, `routes_harvest.py:251/272`
- §3.6 Husbandry logs — revise — ambiguity — `predator_species` reported first when both absent; the requirement is a rung-5 400 reported before unit state; fields stored null for other log types yet still enum-checked when present; `notes` may be blank and is stored verbatim — `routes_growout.py:184-205,193`
- §3.6 Retrieval — insert — ambiguity — `retrieved_on` is otherwise unconstrained (may precede `deployed_on`) and becomes the unit's effective end — `routes_growout.py:259-270`
- §4 husbandry-logs row — revise — ambiguity — declared the implemented `log_type` filter — `routes_growout.py:234-237`

### Pass 4 — routes_harvest.py, routes_lot.py, routes_shipment.py, routes_dealer.py, routes_investigation.py (18 edits: 13 ambiguity-pins, 5 mismatch-revisions)

- §4 lots-under-authorization row — insert — ambiguity — declared the undeclared `status` filter — `routes_lot.py:145-149`
- §4 investigations-by-shipment row — insert — ambiguity — declared the undeclared `status` filter — `routes_shipment.py:231-237`
- §3.7 Vessel — revise — **mismatch** — dropped "`registration_no` (unique across vessels)"; stored as supplied, no uniqueness ground exists — `routes_harvest.py:61`
- §3.7 Vessel — insert — ambiguity — `active_authorization_count` is raw arithmetic, never recomputed and never clamped, yet cannot go below 0 (each authorization increments once at issue, decrements once via close **or** void, never both) — `routes_harvest.py:167-170,274-279`, `cascades.py:30-37`
- §3.7 window — insert — ambiguity — window coherence and both window-containment tests compare at **full supplied precision**, not §2.5's second resolution — `routes_harvest.py:121-124,243-246`
- §3.7 Closing — revise — **mismatch** — deleted the false "`harvest_end_at` must be strictly after `harvest_start_at`"; it equals `harvest_start_at` when the clock has not advanced — `routes_harvest.py:268-270`
- §3.7 Closing — insert — ambiguity — closing is gated on neither area-open nor the clock still inside the window, and moves no gear/seed counter — `routes_harvest.py:265-283`
- §3.8 request — insert — ambiguity — `water_temp_c` carries no range constraint — `routes_lot.py:56`, `core.py:412`
- §3.8 gates — insert — ambiguity — containment and instant-ordering tests use full supplied precision — `routes_lot.py:73-78`
- §3.8 bases — insert — ambiguity — neither basis can be negative; the ordering gate precedes the measurement — `routes_lot.py:77-78,92-95`, `core.py:220-225`
- §3.8 Voiding — revise — **mismatch** — void re-derives both aggregates rather than subtracting incrementally (arithmetically identical) — `routes_lot.py:263-267`, `calc.py:339-344,370-375`
- §3.9 Certifying — revise + insert — **mismatch** + ambiguity — dropped "`certification_no` (unique across dealers)"; `certified_through` unconstrained at certification (a past date is accepted) — `routes_dealer.py:41-42`
- §3.9 Renewals — revise + insert — **mismatch** + ambiguity — both semantic checks are rung-5 shape failures judged **ahead** of the rung-6 version comparison; `version` advances only when a field actually moves — `routes_dealer.py:76-95`, `core.py:270-301`
- §3.9 Reinstatement — insert — ambiguity — a reinstatement's `icssl_listed_through` is unconstrained (not required <= `certified_through`, may be past) — `routes_dealer.py:123-137`
- §3.9 Assembly — insert — ambiguity — `lot_ids` shape-checked at rung 3 (ahead of ownership) while `destination_state`/`carrier` sit at rung 5; the roster is stored verbatim and never de-duplicated, so a lot named twice is double-counted by `lot_count` and `total_bushels` — `routes_shipment.py:52-69,83-92`
- §3.9 Assembly — insert — ambiguity — the four grounds run in rung 13's declared order, each applied across the whole roster in `lot_ids` order; assembly is not gated on `LISTED` — `routes_shipment.py:71-81`
- §3.9 Confirming — insert — ambiguity — `confirmed_at` is exempt from the future-dating rule — `routes_investigation.py:65,74`
- §3.9 Hop 2 — insert — ambiguity — a recalled lot on no shipment drags nothing and adds nothing to `recalled_shipment_count` — `cascades.py:159-175`

Pass 4 also re-verified that Step 8's §2.7 rung-13 shipment-release exception and §3.9 shipping paragraph still match `routes_shipment.py:135-188` exactly (state -> cold-chain -> future-dating -> CERT_EXPIRED -> SUSPENDED -> NOT_LISTED -> NOT_LISTED_FOR_INTERSTATE -> LOT_NOT_TAGGED); passes 2 and 3 disturbed nothing. It adjudicated the vibrio multi-`ACTIVE`-plan question from source and made no edit: `routes_misc.py:57-63` supersedes every `ACTIVE` plan for the month, so §3.8's uniqueness sentence is accurate and `calc.py:418-427`'s tolerance is unreachable.

### Pass 5 — RECONCILIATION (8 edits: 2 ambiguity-pins, 2 mismatch-revisions, 4 contradiction-fixes)

All six deferred cross-pass items were adjudicated from source, not from the pass reports.

- **A1 CONFIRMED, fixed.** §2.5's blanket "instants are compared at second resolution throughout" was globally false and contradicted the §3.7/§3.8 local pins passes 3-4 had added. Replaced with an enumeration: second resolution at `core.py:742` (future-dating), `calc.py:119-124` (adverse window), `calc.py:140-141,233-238` (post-closure clean test), `calc.py:310,320` (inspection & predator ages), `calc.py:388-389` (vessel overlap), `routes_area.py:246-248` (reopen eligibility), `routes_area.py:389` (closure restart), `routes_shipment.py:158-160` (cold chain); full precision at `routes_harvest.py:121,123` (window coherence), `routes_harvest.py:243-246` (activation containment), `routes_lot.py:73-76` (landing containment), `routes_lot.py:77-78` (three-instant ordering), plus sort keys.
- **A2 CONFIRMED, fixed narrowly.** `routes_shipment.py:55` shape-checks `lot_ids` before the ownership compare at `:63`; every other endpoint puts ownership first (verified across all `routes_*.py`). §2.7 rung 5 now carries the scoped exception plus "every other endpoint judges ownership before shape".
- **A3 CONFIRMED, fixed.** §2.10 now mirrors §3.8's recompute wording and additionally names the authorization's harvested volume, which §2.10 had omitted — `routes_lot.py:263-267`, `calc.py:339-344,370-375`.
- **A4 CONFIRMED, fixed.** All 30 filter application sites use `!=` exact equality. §2.3 now pins exact-equality matching with no trim/case-fold/prefix/substring.
- **A5 CONFIRMED dead, no edit.** `core.bump()` and `core.second_resolution()` have zero call sites; no pass pinned a forced second version advance.
- **A6 CONFIRMED unreachable, no edit** (deliberately not documenting unreachable paths): `routes_misc.py:57-63` supersedes every ACTIVE plan so `calc.py:418-427`'s tolerance is dead, and there is no area-delete capability so `routes_harvest.py`'s `if area is not None` guards never fall through.

Four further contradictions found and resolved beyond A1-A4:
- §2.9 — revise — **mismatch** — claimed elapsed minutes are "truncated toward zero from second-resolution instants"; `core.truncated_minutes` truncates the *full-precision* delta to whole seconds and then to minutes, so 00:00:00.900 -> 00:01:00.100 is 0 minutes, not 1 — `core.py:220-226`, `calc.py:446-447`
- §3.3 — revise — **mismatch** — `closure_reopen_eligible_at` was called "derived as `last_closure_started_at` plus `rainfall_closure_hours`", contradicting the next paragraph; it is a stored field written only at closure and nulled at reopen — `routes_area.py:219,259,397`, `cascades.py:89`
- §3.6 — revise — **contradiction** — "the one string field in this document that may be supplied blank" collided with the new §2.3 filter clause; narrowed to "the one **request-body** string field" (only `allow_blank=True` site) — `routes_growout.py:193`
- §3.7 — insert — ambiguity — vessel-capacity overlap comparison pinned at second resolution, explicitly contrasted with the full-precision window-coherence test two paragraphs above — `calc.py:388-389`

**Whole-document invariants re-verified programmatically by pass 5:** (1) §5's 79 rows match `errors.ERROR_STATUS` — 79 codes, zero one-sided, zero status mismatches, zero duplicate rows; (2) §4's 64 `(method, path)` rows match the 64 registered non-static routes exactly in both directions after path-parameter normalisation; (3) all 64 §4 Authorized-Roles cells match the resolved `authenticate(...)` argument, including the two review endpoints that delegate to `routes_lease._record_review` (`SitingReviewer` only). Additionally every named numeric constant in the PRD matches `core.py`'s value, and every member of all 28 enum tuples in `core.py` appears in the PRD.

**Over-eager-pinning audit (pass 5):** spot-verified the highest-risk pins against source — the vessel counter's non-negativity, allowance bases never negative, roster never de-duplicated, `BROAD` expansion single-hop, `confirmed_at`'s future-date exemption, the exactly-three serialise-time derived fields, the eight-field summary object, and the 404/405/trailing-slash/no-5xx paragraph. All accurate; nothing removed.

**Residual:** pass 5 reports no known residual PRD silence or PRD/impl mismatch. The only implementation behaviour left undocumented is the two genuinely unreachable A6 paths, deliberately so.

---

## Pipeline complete — 2026-09-06T06:26:02.362Z

All nine steps finished. Final deliverables in place:
- `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`
- `test_helpers/` (9 modules, 2,022 lines) and `test_suite/` (conftest + 15 test files, 6,003 lines, 125 tests)
- `workspace/INSTRUCTION.md`, `workspace/PRD.md` (556 lines), `workspace/PRD_FINALIZED.md` (556 lines), `workspace/PRD_COMPLETED.md` (558 lines)
- `workspace/implementation/` (16 modules + start.sh + requirements.txt, 4,499 lines) with `results.{1..8}.json` from the final clean sweep, all eight rounds 125/125.
