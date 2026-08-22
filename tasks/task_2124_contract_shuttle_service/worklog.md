# Worklog — task_2124_contract_shuttle_service

## Step 1: Create task directory — 2026-08-21T14:10:02.804Z

Created `tasks/task_2124_contract_shuttle_service/` and `tasks/task_2124_contract_shuttle_service/workspace/`. Index 2124 chosen as max existing (2123) + 1.

## Step 3: Copy shared files — 2026-08-21T14:10:02.804Z

Copied `./INSTRUCTION.md` -> `tasks/task_2124_contract_shuttle_service/workspace/INSTRUCTION.md` (performed early alongside Step 1; no dependency on Step 2).

## Step 2: Generate scaffold — 2026-08-21T15:05:00.000Z

All three scaffold artifacts are generated and lint-clean.

### Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_2124_contract_shuttle_service/SCAFFOLD.yaml` (§1.0–§1.7 + §1.2.1)
- `/home/ubuntu/github/CodingPRD/tasks/task_2124_contract_shuttle_service/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2124_contract_shuttle_service/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

Plus a Step-4 entry appended to the existing `worklog.md`. No sibling task directory was read.

### Design summary

Profile: **temporal_windowing × ledger_reconciliation**, `entity_topology: graph`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy]`. Expert band, deliberately over it as requested: 11 entities, 49 endpoints, 12 calculations, 31 ordered validations, 53 errors, 9 state machines, 2 OCC rules, 5 roles.

Core mechanics: `Trip` carries two independent axes (`dispatch_status × settlement_status`); `ServicePeriodReport` and `RenewalOffer` are cyclic; `ServiceContract` is self-referential via `predecessor_contract_id`, minted by the renewal-accept cascade. `api_prefix: ""` (flat paths), which is what makes the lint's FK segment derivation resolve.

### Difficulty coverage (§1.8 — 9 rules, 21 instances, ≥2 each)

- **dual_variant**: report PROVISIONAL vs FINAL settlement (21600/10440 vs 14580/4122 cents) and on-demand PROMISED vs REALIZED wait (9 vs 15 min → 900-cent credit) — different entity domains.
- **combinatorial**: mode (a) fleet requirement `max(ceil, ceil)` + ADA ceiling; mode (b) gross amount pinned to **sum-then-round** (22500 vs the wrong 22410); mode (c) renewal escalation keyed on a frozen APPROVED report (3.5 + 0.0 − 2.0 = 1.5 % → 9135).
- **cascades**: depth-4 `MaintenanceOrder → Vehicle → Trip → OnDemandRequest` (+ Route DEGRADED branch) and depth-3 `Trip MISSED → CreditMemo ISSUED → contract balance`.
- **overlap semantics**: Vehicle = buffered half-open (12-min layover, zero gap rejected) vs Driver = closed adjacency permitted + aggregate daily duty cap (77 rejects 78, 78 accepts).
- **invariants**: cents conserved across issue/void; vehicle block-minutes conserved across assign/unassign.
- Priority pairs are disjoint: `state × business_safety` and `business_referential × business_fiscal`.

### Verification performed

- `scaffold_lint.py` → `VERDICT: clean lint` (640 calls scanned, all six checks).
- Custom checks: zero unbound `${var}` across both design files (including asserts), 78 unique instance names, every `grounds[*]` ref resolves into §1.1–§1.7, both `excluded_because` stubs cite real §1.8 instances, all 53 error codes referenced.
- All money/minute literals in asserts were computed in Python against the declared formulas, not estimated.
- No forbidden concurrency vocabulary; no `id` used in any selector, ranking, or tie-break (`RidershipCount.sequence_no` and `created_at` are the tie-breaks).

Two semantic bugs were caught and fixed during self-audit: a corner instance whose expected `ERR_TRIP_DEPARTURE_TOO_EARLY` would actually have been masked by the higher-priority seats check (retargeted to a trip with free seats), and an on-demand serve whose pickup minute preceded its own trip departure.

_(Orchestrator note: the subagent labeled its own worklog entry "Step 4"; corrected to Step 2 here. The entry above is its returned summary verbatim.)_

## Step 4: Generate PRD — 2026-08-21T15:18:00.000Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2124_contract_shuttle_service/workspace/PRD.md` (449 lines, ~102 KB). The two design indices were not opened, and `worklog.md` was not touched.

### Document skeleton (domain-derived, not copied from the example)

- **§1** — 3-paragraph introduction framing the ops/commercial seam that the API closes.
- **§2** (10 subsections): 2.1 Operating Personas and Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination, Ordering and Collection Filters · 2.4 Resource Identity, Versioning and the Audit Trail · 2.5 The Logical Service Clock · 2.6 The Request Screening Ladder · 2.7 Cascade Discipline and Derived Counters · 2.8 Optimistic Concurrency on Contracts and Routes · 2.9 Minutes, Money and Rounding Discipline · 2.10 Segregation of Duties in Settlement.
- **§3** (9 subsections, lifecycle + cross-cutting mix): Standing Up a Client Site · Route Design, Fleet Sizing and the Daily Cut · The Fleet: Registration, Client Livery and the Shop · Drivers, Blocks and the Dispatch Board · On-Demand Riders · Counting Ridership · Missed Trips, Credit Memos and the Client's Balance · Period Settlement · Renewal Negotiation and Rate Escalation.
- **§4** 4-column endpoint table, **§5** 2-column error table. File ends at §5 — no audit footer.

### Verified completeness counts (re-read from disk after writing)

| Scaffold table | Scaffold count | Covered in PRD |
|---|---|---|
| entities | 11 | 11 (all named in prose; 112/112 field names in backticks) |
| state machines | 9 (47 transitions) | 9 / all 47 from->to pairs, preconditions + side effects |
| calculations | 12 | 12, all constants embedded in business context |
| validations | 31 | 31, enumerated as an explicitly *ordered* ladder in §2.6 |
| endpoints | 49 | 49 rows |
| errors | 53 | 53 rows; all 53 also triggered in §2/§3 narrative |
| roles | 5 | 5, each with its `identity:` translated |
| concurrency rules | 2 | 2, both with endpoint + OCC field + error id + 412 |

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 112 required, 112 present, 0 missing
- endpoints[].request_body: 59 required, 59 present, 0 missing
- endpoints[].query_params: 21 required, 21 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 31 checked, 31 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 47 checked, 47 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 31 checked, 31 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 49 checked, 49 expressed, 0 missing
- entities[].fields[] structured content: 112 checked, 112 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (maintenance close RETURN_TO_SERVICE/RETIRE; mark-missed OPERATOR_FAULT/CLIENT_REQUEST/WEATHER; match selector vs explicit trip_id; respond REOPEN/ACCEPT/DECLINE; PROVISIONAL/FINAL settlement; PROMISED/REALIZED wait), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 956
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 matches the canonical file byte-for-byte; no fuzzy/approximating words anywhere; all 47 state values and every enum member appear as exact backticked strings; §4 has exactly 4 columns and §5 exactly 2.

One judgement call worth flagging: the `Route` state machine names *"ServiceContract terminate **or renewal-accept** cascade"* as the trigger for `PUBLISHED -> RETIRED` and `DEGRADED -> RETIRED`, but the `ServiceContract RENEWAL_PENDING -> RENEWED` transition lists only the three renewal-cascade links and no route retirement. I chose losslessness and expressed both (§3.2: a `PUBLISHED`/`DEGRADED` route retires when its contract is terminated *or* when an accepted renewal closes that contract out), while keeping `DRAFT -> RETIRED` tied to termination only, matching that transition's narrower trigger.

_(Orchestrator independent verification: 449 lines / 102086 bytes; headings run unbroken §1 -> §5 with no truncation; §4 = 51 pipe rows - 2 header = 49 endpoints; §5 = 53 error rows; all 53 scaffold error codes present in PRD (the 54th scaffold token `ERR_XXX` is the response-envelope placeholder at SCAFFOLD.yaml:57, not a real error); 0 occurrences of scaffold/test_recipe/difficulty_design vocabulary in PRD.)_

## Step 6: Generate implementation — 2026-08-21T15:45:00.000Z

The implementation is complete and verified. Here is my summary.

### What was built

A complete Python + Flask API in `/home/ubuntu/github/CodingPRD/tasks/task_2124_contract_shuttle_service/workspace/implementation/` (~2,500 lines, 16 files):

```
start.sh  requirements.txt  app.py  store.py  errors.py  envelope.py  guards.py  calc.py
routes/{contracts,route_design,fleet,trips,ondemand,reports,memos,renewals,clock}.py
```

All **49 endpoints**, **11 entities**, **9 state machines** (including Trip's parallel `dispatch_status` / `settlement_status` axes), **12 calculations**, the **31-rung validation ladder**, **53 errors**, **5 roles**, and both **OCC rules** are implemented.

### Verification

Seven scenario suites (~200 assertions) run green, covering: the auth ladder and envelope shape, fleet-requirement ceilings, trip generation, all six ordered assign checks, maintenance displacement -> route degradation -> republish recovery, missed-trip/wait-SLA credit minting and voiding, provisional-vs-final settlement arithmetic, the submit->dispute->submit->approve loop with segregation of duties, renewal pricing/counter/reopen/accept with successor minting, the terminate cascade, and boundary cases (12-minute layover gap, touching driver endpoints, duty cap equality, 5-minute on-time grace, zero shortfall, ADA share equality, 2-vs-3-minute wait grace, renewal window opening/closing days).

Three consecutive `start.sh` boots each began with an empty store (create -> `total_count == 1` every time), ready in **0.57 s**; the pip install is guarded so per-test reboots are no-ops.

### Judgment calls worth flagging (PRD taken literally over scaffold)

- **Rung 4 before rung 5/7**: driver ownership is checked before body shape and path existence — so a `DriverUser` acting on a trip whose `driver_id` is null or foreign gets `ERR_DRIVER_NOT_ASSIGNED` even when the state is also wrong. Ownership is skipped when the target can't be resolved (nonexistent trip, or a request with null `matched_trip_id`), letting 404 / `ERR_REQUEST_NOT_MATCHED` surface.
- **Republish ordering**: the PRD's "the route's stored `headway_minutes` is *then* replaced" means reverted riders' `promised_wait_minutes` is recomputed against the **old** headway; `promised_headway_minutes` stays frozen at its creation value per the entity contract.
- **`amount_cents < 1`** on a credit memo yields `ERR_MEMO_AMOUNT_EXCEEDS_CAP` (422), not `ERR_INVALID_REQUEST` — §3.7 says so explicitly.
- **Explicit match against a non-`SCHEDULED`/`ASSIGNED` trip** returns `ERR_TRIP_NOT_SCHEDULABLE` (409); §3.5 says every eligibility condition is enforced but names no error for that one.
- **Version bumps**: a targeted derived-counter recompute always bumps the row (per §2.4/§2.7), with one bump per row per request; the clock endpoint's global driver-duty sweep bumps only drivers whose value actually changed.
- **`current_utc`** echoes the caller's `to_iso8601` verbatim; `created_at`/`updated_at` use real wall-clock time (§2.5 keys only two rules to the logical clock).

_(Orchestrator independent verification: `start.sh` reads `$PORT`, binds `0.0.0.0`, foreground `exec python3 app.py`; `store.py` declares all 11 collections as empty dicts with zero seeded entities; grep for `sqlite3` / file-write / `json.dump` / `pickle` / `shelve` / `/tmp/` across all impl `.py` files returns nothing — in-memory only, as required. 2493 Python LOC. Stray `__pycache__` dirs removed.)_

## Step 5: Generate unit tests — 2026-08-21T15:56:00.000Z

Done. Generated complete test infrastructure and a 97-test suite for `task_2124_contract_shuttle_service`.

### What was produced

**`test_helpers/`** (9 files, ~2,050 lines)
- `types.py` — 18 status/role enums plus TypedDicts for all 11 resources. `RidershipCount` correctly carries only `id` + `created_at` (no `updated_at`/`version`), matching PRD §2.4's append-only rule.
- `api_client.py` — one method per PRD §4 endpoint (48 methods, including `/_clock/set_current_utc`).
- `api_errors.py` — all 54 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions plus four domain invariant checkers (`assert_credit_balance_matches_issued_memos`, `assert_committed_block_matches_trips`, `assert_duty_minutes_match_trips`, `assert_settlement_block_zeroed`).
- `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (859 lines: ~35 primitive steps plus 15 composite scenarios pre-built from the design indices' `setup_api_calls` chains), `__init__.py` barrel.
- `DriverUser` is the only `entity_backed` role; `make_driver_headers(driver["id"])` is threaded through every ownership-gated call in fixtures — the shared constant is never used for those.

**`test_suite/`** (conftest + 10 domain-named files, ~3,800 lines, 97 tests)

### Coverage audit (verified by script)
- Queue A: **21/21 difficulty instances x exactly 2 tests each = 42 tests**, no shortfall.
- Queue B: **55/55 non-stub corner instances x >=1 test = 55 tests**, no shortfall.
- The 2 `excluded_because:` stubs were **not** translated; both cross-references (`report_settlement_provisional_versus_final`, `route_fleet_requirement_max_of_headway_and_demand`) resolve to real difficulty instances.
- Every test carries exactly one `Design:` line as the last docstring line, resolving to a real instance. No untagged, dual-tagged, or dangling tags.
- Every quoted PRD citation (>=8 words) survives a whitespace-normalised literal match against `PRD.md` — 0 failures.
- No `pytest.mark.skip/skipif/xfail`; no "scaffold"/table/§1.x references anywhere in emitted code.
- `pyflakes` clean; `pytest --collect-only` collects all 97.

### One adjudication call worth flagging
`Corner/errors/serve_before_match_returns_request_not_matched` uses `validate_error_is_one_of([ERR_REQUEST_NOT_MATCHED, ERR_DRIVER_NOT_ASSIGNED])`. A never-matched request has `matched_trip_id` null, so PRD §2.1's rung-4 ownership check ("the `driver_id` of the trip named by the request's `matched_trip_id`") has no trip to resolve against — two faithful PRD-only readers could land on either error. This is the sanctioned `error-precedence` Silence pattern, documented inline in the test.

No PRD gaps forced an outright skip: every non-stub instance in both indices passed the two-condition filter.

_(Orchestrator independent verification: 5926 test LOC; 97 `def test_` functions; `Design:` tag census = 42 Difficulty + 55 Corner = 97, one per test; zero `pytest.mark.skip`/`xfail` occurrences across both directories. Stray `__pycache__` removed. Note the convergence: this agent's flagged `serve_before_match` adjudication is the same PRD silence the Step 6 implementer independently flagged as its judgment call #1 — the relaxed `validate_error_is_one_of` should accommodate the implementation's chosen branch.)_

## Step 7: Run tests and iterate — 2026-08-21T15:51:00.000Z

Task `task_2124_contract_shuttle_service` is already green and stable. No changes were needed.

### Summary

**Iterations run:** 1 (a single 8-round parallel stability sweep; no fixes required, so no second iteration was needed).

**Sweep result:** all 8 concurrent rounds returned `97/97 passed, 0 failed, 0 errors, 0 skipped`. The union of failing tests across all 8 rounds is empty, so no flakiness surfaced — no timing-sensitive concurrency, fixture-ordering, or port-collision failures appeared in any round. Each round's `results.${i}.json` was freshly written (old ones deleted before launch) and independently confirms `total: 97, passed: 97`.

**Tests deleted:** none. No test failed either sub-check of STEP 1, because no test failed at all.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Integrity checks performed** (to rule out a pass rate inflated by pre-existing hacks rather than by correct behaviour):
- `grep` over `test_suite/` and `test_helpers/` found zero `pytest.mark.skip`, `xfail`, or any `pytest.mark` usage — so nothing is passing by being skipped.
- 97 `def test_` functions exist across the ten `test_suite/` modules, exactly matching the 97 executed tests; no test is being silently uncollected.
- `grep` over `workspace/implementation/` found no `sqlite`, `open(`, `json.dump`, `/tmp`, `pickle`, or `shelve` — storage is in-memory Python dicts only (`store.py`), with no startup seeding, matching the cardinal rule.

**Notable design points confirmed while reading for diagnosis** (relevant if the task is revisited):
- `workspace/implementation/store.py` bumps a row's `version` at most once per request via a per-request `_touched_rows` set, and `register_new()` pre-marks freshly created rows so a same-request cascade recompute cannot push a new row past `version: 1` — this is what makes PRD §2.7's "a cascade mutation increments version exactly as a direct write would" hold without double-counting.
- `app.py` serializes every request behind a global `store.LOCK` acquired in `before_request`, which is why the concurrency/race tests are deterministic across all 8 rounds rather than intermittently landing in an unexpected error branch.

_(Orchestrator independent verification: re-parsed all 8 `results.*.json` directly — each has `total=97 passed=97 failed=0 errors=0 skipped=0`, and the per-test outcome census is `{'passed': 97}` per round with no other status present. Union of test identities across rounds = exactly 97 unique names, so 776 test executions all passed and no round silently collected a smaller set. mtime audit: latest `test_suite/` file 15:47:00, latest `test_helpers/` file 15:30:13, latest `implementation/` file 15:44:34, all strictly earlier than `results.1.json` at 15:51:04 — the sweep ran against the final generated artifacts, and nothing was modified afterward.)_

## Step 8: Finalize PRD — SKIPPED

Skip condition met per the pipeline spec: Step 7 exited on its first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the implementation exhibits at each site the test suite exercised, leaving `<step_7_diff>` empty and Step 8 with nothing to patch. No `PRD_FINALIZED.md` is produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-21T16:02:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written; `PRD.md`, `implementation/`, `test_suite/`, `test_helpers/` are untouched (PRD.md md5 unchanged, no impl/test file modified).

### Counts

| | |
|---|---|
| PRD.md | 449 lines / 102,086 chars |
| PRD_COMPLETED.md | 449 lines / 110,355 chars (**+8,269**) |
| Ambiguity-pins | 29 |
| Mismatch-revisions | 6 |

All 35 changes are in-paragraph inserts/revisions — no new paragraphs, no new sections, line count unchanged.

### Changes

- **§2.1** — insert — ambiguity — a whitespace-only `X-User-ID`/`X-User-Role` counts as empty — `guards.py:38`
- **§2.3** — insert — ambiguity — `created_at` ties (ms precision) break on persistence order everywhere it is a sort/tie-break key — `store.py:115`, `calc.py:264,321,550`
- **§2.3** — insert — ambiguity — `is_ada_accessible` filter accepts `true`/`1`/`false`/`0`; any other spelling matches no row — `guards.py:164`
- **§2.4** — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` come from real wall-clock UTC, not the logical clock — `store.py:62`
- **§2.4** — insert — ambiguity — one `version` bump per row per request (`updated_at` still refreshed each touch); a row the request created stays at `version` 1 — `store.py:90,97`
- **§2.5** — revise — **mismatch** — "The server does not read wall-clock time" -> no *business rule* reads it; the real clock serves only the audit stamps — `store.py:62`
- **§2.5** — revise — **mismatch** — `current_utc` echoes the submitted `to_iso8601` verbatim rather than reporting a normalized instant; bare dates accepted, offsets converted, unparseable -> `ERR_INVALID_REQUEST` — `clock.py:18,46`
- **§2.5** — revise — **mismatch** — the clock sweep bumps a driver's `version`/`updated_at` only when the recomputed duty actually changed (the one exception to §2.4/§2.7) — `calc.py:179`, `clock.py:45`
- **§2.6 rung 4** — insert — ambiguity — ownership is skipped when the trip cannot be resolved (missing path id, missing/non-string/unknown body `trip_id`, request absent or carrying no `matched_trip_id`); a resolved `matched_trip_id` pointing at no trip still fails 403 — `trips.py:36,239`, `ondemand.py:124`
- **§2.6 rung 5** — insert — ambiguity — absent/unparseable/non-object bodies screen as `{}`; unassign/activate/submit/approve declare no body; the four body-vs-body checks sit here while `actual_completion_min` vs `actual_departure_min` is deferred past rung 10 — `guards.py:48,87`, `trips.py:188`
- **§2.6 rung 11** — insert — ambiguity — assign's route-`PUBLISHED`/`DEGRADED` test precedes vehicle availability; offer creation needs `ACTIVE`/`RENEWAL_PENDING`, counter and `ACCEPT`/`DECLINE` need `RENEWAL_PENDING`, `REOPEN` is exempt — `trips.py:91`, `renewals.py:34,97,152`
- **§2.9** — insert — ambiguity — supplied percentages are range-checked then stored/echoed verbatim, never quantised to 2dp — `contracts.py:21`
- **§3.1** — insert — ambiguity — `termination_reason` is a required non-empty string, validated only, never stored or echoed — `contracts.py:97`
- **§3.2** — insert — ambiguity — republish re-quotes reverted riders against the **old** headway (and pre-restore route status), and sets `published_service_date` to the payload date — `route_design.py:128-134`
- **§3.3** — insert — ambiguity — `RETIRE` leaves `committed_block_minutes` and the vehicle's trips alone — `fleet.py:247`
- **§3.4** — insert — ambiguity — assign resolves `vehicle_id` before `driver_id` at rung 8 — `trips.py:85`
- **§3.4** — insert — ambiguity — route test precedes vehicle availability — `trips.py:91`
- **§3.4** — insert — ambiguity — vehicle block scans every trip still naming the bus (`ASSIGNED`/`IN_SERVICE`/`COMPLETED`); both intervals buffered, so symmetric — `trips.py:114`
- **§3.4** — insert — ambiguity — same population rule for the driver block — `trips.py:124`
- **§3.4** — insert — ambiguity — completion's `actual_completion_min` check runs after `ERR_TRIP_NOT_IN_SERVICE`; `ada_boardings <= boarded` applies at rung 5 — `trips.py:184,186,188`
- **§3.5** — insert — ambiguity — explicit match against a non-schedulable trip yields `ERR_TRIP_NOT_SCHEDULABLE` (409) — `ondemand.py:91`
- **§3.5** — revise — **mismatch** — precedence chain extended to route -> dispatch-state -> ADA -> seats -> departure -> contract — `ondemand.py:88-104`
- **§3.5** — insert — ambiguity — recompute rewrites `promised_wait_minutes` only; `promised_headway_minutes` stays frozen; no qualifying route leaves the old value in place — `calc.py:272`
- **§3.7** — revise — **mismatch** — `amount_cents` carries no rung-5 range (was "of at least 1") — `memos.py:17`
- **§3.7** — insert — ambiguity — zero/negative amounts yield `ERR_MEMO_AMOUNT_EXCEEDS_CAP`, never `ERR_INVALID_REQUEST` — `memos.py:36`
- **§3.8** — insert — ambiguity — submit is not contract-gated, takes no body fields, keeps `dispute_reason` — `reports.py:76-90`
- **§3.8** — insert — ambiguity — `dispute_reason` is a required non-empty string — `reports.py:20`
- **§3.8** — insert — **mismatch** — approval bumps the contract only when at least one memo qualifies; otherwise the contract is untouched — `reports.py:112`
- **§3.9** — insert — ambiguity — offer creation requires `ACTIVE`/`RENEWAL_PENDING` (`ERR_CONTRACT_NOT_ACTIVE`), between the version guard and the window test — `renewals.py:34`
- **§3.9** — insert — ambiguity — counter's contract gate is `ERR_CONTRACT_NOT_ACTIVE`, after the offer state check, before the rate bounds — `renewals.py:97`
- **§3.9** — insert — ambiguity — `REOPEN` skips the contract-status test — `renewals.py:145`
- **§3.9** — insert — ambiguity — `DECLINE` gate failure is `ERR_CONTRACT_NOT_ACTIVE` (409) — `renewals.py:152`
- **§3.9** — insert — ambiguity — `ACCEPT` gate failure is `ERR_CONTRACT_NOT_ACTIVE` (409) — `renewals.py:152`
- **§3.9** — insert — ambiguity — month advance clamps to the landing month's last day — `calc.py:69`
- **§3.9** — insert — ambiguity — acceptance retires only `PUBLISHED`/`DEGRADED` routes; on-demand requests, memos and reports are untouched — `renewals.py:167`

### Notes

- All 49 impl endpoints match the §4 catalogue exactly; all 53 error IDs and all 12 tuned constants (12-min layover, 3-min lead, 2-min grace, 150 c/min, 5-min on-time, SLA/volume tiers, 60-day window, 3x memo cap) were already pinned and needed no change.
- Deliberately left unpinned: the off-catalogue fallbacks `ERR_NOT_FOUND` / `ERR_METHOD_NOT_ALLOWED` / `ERR_INTERNAL` in `errors.py:80-82`, since §4 declares its table the complete catalogue and adding rows to §5 would go beyond a minimal patch.

_(Orchestrator independent verification: `PRD.md` mtime 15:17:14 — unchanged since Step 4, so Step 9 wrote only `PRD_COMPLETED.md` as instructed. Both files 449 lines; +8269 chars. `diff` = 27 hunks / 58 changed line-pairs, consistent with 35 in-paragraph edits and zero structural change. Heading list is byte-identical between the two files (no sections added, removed, or renamed); §4 still 51 pipe rows (49 endpoints) and §5 still 53 error rows; all 53 error codes still present; zero scaffold/§1.x vocabulary leaked into the completed PRD.)_

## Pipeline complete — 2026-08-21T16:03:00.000Z

All 9 steps done (Step 8 skipped by its documented skip condition). Final state: 97/97 tests passing across all 8 parallel stability rounds; deliverables `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/PRD.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/`, `test_helpers/`, `test_suite/`.
