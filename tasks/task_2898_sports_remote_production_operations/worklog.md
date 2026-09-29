# Worklog — task_2898_sports_remote_production_operations

## Step 1: Create task directory — 2026-09-05T13:14:45.291Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2898_sports_remote_production_operations and its workspace/ subdirectory. Index 2898 pre-assigned by the orchestrating command; no index allocation scan performed.

## Step 2: Generate Scaffold — 2026-09-05T14:37:12.356Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and lint-clean.

**Lint verdict (verbatim, first and only run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     13
  §1.8 instances scanned:     24
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  763

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all under the task dir)
- `SCAFFOLD.yaml` — 2726 lines / 141 KB, 13 top-level keys, contains neither design key
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2030 lines / 133 KB, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3628 lines / 231 KB, single key `scaffold_corner_design`
- `workspace/` (empty) and `worklog.md` untouched; `git status` shows only the untracked task dir.

**SCAFFOLD.yaml (§1.0–§1.7)** — api_prefix `/broadcast-ops`; 13 entities, 52 endpoints, 9 state machines (ShowExecution carries two parallel dimensions), 11 calculations (3 with dual variants), 50 validations in one pinned priority ladder, 50 error ids, 5 roles, 3 OCC `concurrency_rules`, complexity layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers`, topology `flat`, shape `cyclic`, consistency `immediate`, logical clock default `2026-08-01T00:00:00Z`.

**§1.8 rule ids / instances (24 total):** dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 4, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 2.

**§1.9 sections / instances (79 total, all 9 sections present):** entities 11, state_machines 15, calculations 10, validations 21, endpoints 5, errors 3, rbac 6, cross_cutting_complexity_layers 7, consistency_model 1. Of these, 55 carry full `test_recipe`s and 24 are `excluded_because` stubs citing a §1.8 instance by name (every citation resolves; no name collides across the two design files).

**Design adjudications**
- Cost control: 24 corner claims already asserted verbatim by a §1.8 instance were written as `excluded_because` stubs instead of duplicating 20-call chains (feed-suspension cascade, crew-call/booking compensation, parallel air-vs-signal dimensions, guarded show creation, prep-vs-feed dependency, priority ordering, turnaround boundary, both readiness variants, crew-call OCC).
- Terminal-state lockdown was split: the cheap VenueSurvey `SUPERSEDED` / CrewCall `DECLINED` pair covers non-Production terminals, `ShowExecution.OFF_AIR` rides on the `rate_threshold_triggers` instance, and `Production.SETTLED` rides on the rbac settle instance (re-wrap -> `ERR_PRODUCTION_STATE_INVALID`).
- Error triggerability is closed for all 50 ids: the eight remaining 404s go through one unknown-UUID sweep, and the four 401/403 ids (`ERR_UNAUTHENTICATED`, `ERR_UNAUTHORIZED`, `ERR_NOT_CALL_OWNER`, `ERR_SEGREGATION_OF_DUTIES`) through the rbac section, which also exercises both segregation-of-duties pairs (review-vs-submit, settle-vs-wrap).
- Three long chains were reused verbatim from one canonical fixture (REHEARSED -> PRE_SHOW, -> ON_AIR, -> WRAPPED) so the pinned literals (settlement 208000 / variance 0, air_minutes_total 120 and 180, engine hours 485+15=500, signal loss 2.03+8.10=10.13) stay consistent across instances.
- Every OCC-guarded write in a recipe is preceded by a fresh `GET /broadcast-ops/productions/{id}` version read, since `recompute_production_stage` bumps the version on side-effect mutations.

**Orchestrator post-step action:** the scaffold generator copied the difficulty directive line "Generate task harder than expert level!" into SCAFFOLD.yaml's `scenario:` block. The orchestrator stripped that single line from SCAFFOLD.yaml so it cannot reach PRD.md via the doc generator. Verified with `grep -rn "harder than expert"` -> no hits anywhere in the task dir. All three YAMLs re-verified as parseable after the edit.

## Step 3: Copy Shared Files — 2026-09-05T14:37:12.378Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to $task_dir/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T14:52:15.189Z

Subagent summary (verbatim):

PRD generation complete.

**File:** `workspace/PRD.md`
**Line count:** 502
**Exact final section heading:** `## 5. Error Code Catalogue` (line 447); the file ends on the final table row `| ERR_LABOR_BUDGET_EXCEEDED | 422 |` — not mid-sentence, mid-table or mid-list.

**Section outline as actually written**
```
# Sports Remote Production Operations API — Product Requirements Document   1
## 1. Introduction                                                          3
## 2. Global Specifications & System-Wide Principles                       11
### 2.1. Operator Identity and Role-Based Access Control                   13
### 2.2. API Response Structure                                            31   (verbatim)
### 2.3. Pagination and List Ordering                                      80
### 2.4. Resource Identity, Timestamps and the Logical Clock               86
### 2.5. Optimistic Concurrency on the Production Record                   94
### 2.6. Nested Paths and Left-to-Right Resolution                        102
### 2.7. Validation Precedence: Exactly One Error Per Request              108
### 2.8. Precision: Cents, Minutes, Hours and Decibels                    167
### 2.9. Readiness Recomputation and the Consistency Cascade              173
### 2.10. Conserved Ledgers                                              186
## 3. Business Logic & Workflows                                          194
### 3.1. Opening a Remote and Its Tier-Derived Requirements               196
### 3.2. The Venue Survey Loop and the Camera Plot                        208
### 3.3. The Fleet: Truck Registration, Rating and Travel Logistics       224
### 3.4. Transmission: Path Registry, Window Geometry and Proving Tests   238
### 3.5. Show Systems: Data Feeds, Preparation and Rights Compliance      258
### 3.6. Crew: Hiring, Union Rules and the Labor Ledger                   270
### 3.7. Rehearsal, Camera Blocking and Certified Readiness               304
### 3.8. Air, Contingency and Signal Failover                             328
### 3.9. Wrap, Settlement and the Return Leg                              358
## 4. Endpoint Definitions                                                388   (52 rows)
## 5. Error Code Catalogue                                                447   (50 rows)
```

**Hard Contract reports**

1. Field-Name Coverage — **PASS**. `entities[].fields`: 110 required / 110 present / 0 missing. `endpoints[].request_body`: 71 / 71 / 0 missing. `endpoints[].query_params`: 14 / 14 / 0 missing. (Mechanically checked with `/tmp/task_2898_prd/c1.py` against backtick tokens in the PRD.)
2. Rule Coverage — **PASS**. `validations[]` 50/50 priorities rendered as the §2.7 ladder; `concurrency_rules[]` 3/3 (write endpoint set, `expected_production_version`, `ERR_STALE_PRODUCTION_VERSION`, 412 all named); `state_machines[].transitions` 51/51 across 9 machines; `calculations[]` 11/11 with pinned rounding order and all constants embedded; validation conditions 50/50 matchable to their `error_id`; `endpoints[].side_effects`/`applies_to` 52/52; `entities[].fields[]` structured content 110/110; sibling-branch symmetry 11 groups / 0 asymmetric.
3. §3 Path Purity — **PASS**. 840 backtick tokens in §3 (288 unique) scanned: 0 slash-leading tokens, 0 bare HTTP methods, 0 method+path pairs.

**Additional coverage confirmation:** 13/13 entities, 52/52 endpoints (verified by set-diffing method+path pairs against the scaffold — no missing, no extras), all 50 error IDs, all 5 role names (`producer`, `engineer_in_charge`, `transmission_coordinator`, `crew_scheduler`, `compliance_officer` as named in the scaffold), all state-machine state values, and all enum-typed field values appear verbatim in backticks. §2.2 verified byte-identical to `section-2.2-response-structure.md` via `diff`.

**Two scaffold inconsistencies resolved during writing** (worth flagging to later steps): (a) inline comments cite priorities 25/24/27 for the signal-loss-budget, curfew and labor-budget rules while the actual `validations[]` entries number them 41/45/50 — I treated the `validations[]` list as authoritative; (b) priority 19 (`{PROVISIONED, REHEARSED}` stage admission) combined with priority 39 (`production.status == REHEARSED` for an `ON_AIR` target) would make `IN_EXTENDED_PLAY -> ON_AIR` unreachable, so §3.8 states explicitly that the resume from `IN_EXTENDED_PLAY` is guarded only by the show's air dimension and re-evaluates neither production stage, certified readiness, nor curfew.

**Orchestrator truncation check (per the known doc-generator failure mode):** verified independently — 502 lines / 94892 bytes; `tail -25` shows the file ending on the complete final row of the §5 error table (`ERR_LABOR_BUDGET_EXCEEDED | 422`), all 50 error ids present, every section from the outline above present in `grep "^#"`. Not truncated. No difficulty-directive leak (`grep "harder than expert"` -> no hits).

## Step 6: Generate Implementation — 2026-09-05T15:22:00.000Z

(Steps 5 and 6 were launched concurrently per the skill's isolation requirement. Step 6 returned first, so it is logged first; Step 5's entry follows below.)

Orchestrator note on this worklog: an earlier attempt to stamp this entry's timestamp used the one-liner `open(p,"w").write(open(p).read().replace(...))`, which truncates the file before reading it and zeroed worklog.md. The orchestrator rebuilt Steps 1-4 verbatim from its own context using heredoc appends only, and no longer performs any in-place Python rewrite of worklog.md. Step 1-4 content above is the original text; only the sub-second digits of the Step 1 timestamp were normalised (13:14:45.291215889Z -> 13:14:45.291Z).

Subagent summary (verbatim):

The implementation is complete, compiled, and smoke-verified end to end.

## Files created (all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `core.py` | 388 | logical clock (starts exactly `2026-08-01T00:00:00Z`), ids, `Decimal`/ROUND_HALF_UP money + 2dp helpers, truncating `whole_minutes`, `ApiError`, response envelope (`meta`/`response_type`/`data`), `require_roles` (401 then 403), pagination (`limit` 1-100 default 10, `offset`, `total_count`, `has_more`), `Payload` schema validator |
| `store.py` | 167 | 13 in-memory dicts + `new_row`/`touch`/`set_fields`/`ordered`/`fetch` and the 11 typed `find_*` 404 helpers |
| `domain.py` | 734 | all constants, 13 serializers, 11 calculations, conserved aggregates, cascades, `recompute_production_stage` |
| `routes_registry.py` | 237 | trucks x5, transmission-paths x2, crew-members x2, data-feeds x3, `_clock/set_current_utc` |
| `routes_production.py` | 459 | productions x6 (incl. OCC truck-assignment, wrap, settle) + venue-survey loop x7 |
| `routes_transport.py` | 243 | path-bookings x6 (geometry, proving tests, release) |
| `routes_crew.py` | 226 | crew-calls x6 (union rules, provisional reserve, settled release) |
| `routes_systems.py` | 242 | system-preps x4 + rehearsals x4 |
| `routes_show.py` | 270 | show-executions x4 + incident log x2 |
| `app.py` | 64 | blueprint registration, `ApiError`/`HTTPException`/500 handlers, `0.0.0.0:$PORT` |
| `start.sh` | 9 | guarded `import flask` check + `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=3.0` |

**Endpoints: 52 implemented vs 52 in the scaffold** — verified programmatically against `SCAFFOLD.yaml`'s method/path pairs: `missing: []`, `extra: []`.

## Structure
- **State machines** are enforced inline at each handler's ladder position, not in a table: 8 machines including ShowExecution's two independent dimensions (`air_status` x `signal_status`). The shared system-driven derivation lives in `domain.recompute_production_stage` (steps 1-6 exactly as specified, with the closed-status early return), and it is invoked by every gating write. Cascades (`abort_scheduled_rehearsals`, `set_readiness_hold`) are single functions reused by every trigger.
- **Calculations** all live in `domain.py` with the pinned rounding orders honoured: per-band cents rounded then summed (straight/OT x1.5/DT x2.0), per-position dB at 2dp then summed then re-rounded, meal units `ceil((worked-360)/30)` capped at 4 with the TIER_1 x1.5 multiplier, bracketed overrun rate keyed on the labor subtotal (never the settlement total), truck accrual `8 + 4 + ceil(air/60)`.
- **Validation precedence** follows the 50-rung ladder literally, including the deliberate inversions: segregation (16) before state (19/21); rung 19 admits both PROVISIONED and REHEARSED for going on air so a demoted production lands on rung 39; truck gates ordered power(42) -> tier(43) -> channel(44) -> travel(46); labor budget last of all. `POST /productions` window relations are schema (400), while `ERR_INVALID_TIME_WINDOW` is 422.
- **Version/OCC**: `expected_production_version` on the 3 write endpoints; a row's `version` advances by exactly 1 per request even when the derivation touches it again (request-scoped dedupe on `flask.g`).

## Smoke evidence (server on self-chosen ports 41677/41678, killed by exact PID; no pattern kills)
Three scripted runs under `/tmp/task_2898_impl/`, **0 failures** across ~150 assertions:
- Full pipeline: truck -> production -> survey (2 positions, loss 2.70, headroom 340) -> submit -> review -> booking -> schedule-test -> PASS -> feed/prep VALIDATED -> truck-assignment -> 2 accepted calls (`provisional_total_cents` 104000 each, 4 meal units) -> rehearsal COMPLETED -> **certified readiness exactly 100.00** -> ON_AIR -> EXTENDED_PLAY incident -> IN_EXTENDED_PLAY -> OFF_AIR (`air_minutes_total` 270) -> wrap (truck IN_TRANSIT, engine hours 17) -> settle (`overrun_fee_cents` 36000, `settlement_total_cents` 244000, variance 0) -> arrive -> AVAILABLE.
- Corner paths: PATH_LOSS promoting a CONFIRMED BACKUP (`ON_BACKUP`, still on air, primary `FAILED_OVER`, path bandwidth returned) then a second loss exhausting redundancy (`LOST` + forced OFF_AIR); 20-minute technical-downtime threshold forcing OFF_AIR while the production stays ON_AIR; feed suspension cascade (prep->PENDING, production->SURVEYED, rehearsal->ABORTED, `readiness_hold` true); satellite guard-band clash vs. exact-10-minute gap accepted; fiber capacity at 101 rejected / exactly 100 accepted / abutting window accepted; survey supersede dropping SURVEYED->PLANNED; turnaround at 599 rejected and exactly 600 accepted; latency-410ms FAILED branch at HTTP 200; contract expiry equality rejected.
- Error envelope confirmed for 400/401/403/404 (unknown route -> `ERR_NOT_FOUND`)/409/412/422.

**Storage**: purely module-level Python dicts, **zero seeded data** — after a restart every collection reported `total_count: 0` (productions, trucks, path-bookings, crew-calls, system-preps). No SQLite, no file/JSON dump, no `/tmp` cache. Boot is a bare Flask import and responds to the first request within a fraction of a second, suitable for `--isolation per-test-server`. Nothing outside `workspace/implementation/` was created or modified, and the test directories were never read or listed.

## Step 5: Generate Unit Tests — 2026-09-05T15:53:00.000Z

(Launched concurrently with Step 6; returned second. Logged after the Step 6 entry above for that reason — worklog is append-only.)

Subagent summary (verbatim):

Stage 1 and Stage 2 are complete and verified.

## Output

**`test_helpers/` (9 files, 2,478 lines) — at the TASK ROOT**
`__init__.py` (barrel: framework generics + all local exports), `constants.py` (PRD literals: 1.35 dB/100 ft, 10.13 dB budget, 600/720 crew bands, 360-min meal window, 3500 c units, 600-min turnaround, 40/25/20/15 readiness weights, 20-min downtime threshold, canonical TIER_3 event, unknown-UUID pool), `types.py` (27 enums + 13 TypedDicts; only `CameraPosition` and `Incident` omit `updated_at`/`version`), `api_errors.py` (50-member `ApiErrorId` + status map registered at import; `ERR_INVALID_REQUEST` -> 400 per PRD §5), `api_client.py` (52 endpoint methods under `/broadcast-ops` + `canonical_instant`/`instants_equal`), `test_users.py` (5 roles, two distinct PM/TD identities, `make_crew_member_headers`, empty-string header builders, undeclared role), `factories.py` (22 payload factories), `assertions.py` (identity/versioned/append-only, pagination, 13 entity shape checks, conserved labor + path ledgers, readiness), `fixtures.py` (read/version helpers, tier-1/2 creators, full-lifecycle chains `setup_surveyed_/provisioned_/rehearsed_production`, `setup_show_pre_show/on_air`, `setup_wrapped_/settled_production`, plus threshold builders for test-attempt limit, survey revision, feed consumer ceiling).

**`test_suite/` (conftest.py + 13 test files, 5,953 lines) — at the TASK ROOT**
**134 test functions**, all 134 collected by pytest with no import errors.
01 production/fleet 19 · 02 survey/camera plot 19 · 03 signal loss & power 8 · 04 truck assignment 10 · 05 paths & bookings 13 · 06 feeds & preps 10 · 07 crew calls & labor 14 · 08 turnaround 5 · 09 rehearsal & readiness 8 · 10 show & incidents 7 · 11 cascades & holds 4 · 12 wrap & settlement 5 · 13 access control & precedence 12.

## Queue coverage

- **Queue A (difficulty, §1.8): 24 non-stub instances — 24 translated, 0 skipped.** Every one carries >=2 tests (verified programmatically).
- **Queue B (corner, §1.9): 55 non-stub instances — 55 translated, 0 skipped.** The 24 `excluded_because` stubs were deliberately not translated (their cross-references to difficulty instances were checked and all resolve).
- **No instance-level skips.** Sub-assertions dropped under the PRD-first filter (instance coverage retained): whitespace-only header case (`requests` raises `InvalidHeader` client-side, unsendable); `settled_total_cents` / `meal_penalty_units` values before a call reaches `RELEASED` (PRD states no pre-release value); `test_attempt_count` immediately after schedule-test (PRD increments only on a filed result); the "client smuggles computed camera-position fields" body (PRD does not uniquely derive ignore-vs-refuse); the claim that per-band rounding order is observable for crew cost (integer rates make the straight/overtime bands whole cents); `readiness_score_preflight == 100.00` after a call cancellation (PRD derives 92.50) and re-arming an OFF_AIR show (rung 19 vs 27 ambiguous).

## PRD-first adjudications applied throughout

`ERR_INVALID_REQUEST` = HTTP 400 (yaml said 422 in several places); malformed clock instant -> `ERR_INVALID_TIME_WINDOW` 422; a successful clock set asserts HTTP 200 only (empty `data` object per §2.2); a reversed proving window -> `ERR_INVALID_TIME_WINDOW`, not `ERR_TEST_WINDOW_INVALID`; the yaml's non-existent `venue_roof_type: FIXED` replaced with declared enum values.

## Verification performed

- `python3 -m py_compile` passes on all 9 helper and all 14 suite files; `pytest --collect-only` -> **134 tests collected in 0.43s**, zero errors (no server started, suite never run).
- Design-tag cross-check against both yamls: every test has exactly one `Design:` line, it is the last docstring line, every tag resolves to a real `rule_id`/`section` + instance `name`, none points at a stub, **79/79 non-stub instances covered**, no difficulty instance under 2 tests.
- Citation check: **320 `PRD:` quotations, all verbatim substrings of `workspace/PRD.md`**, none containing an ellipsis.
- Static call check: every helper function and `ApiClient` method invoked from the suite exists and binds cleanly to its signature (0 problems) — catches arity/kwarg bugs before Step 7.
- Grep sweeps clean: no `skip`/`skipif`/`xfail`, no "scaffold" mention, no `sys.path` hacks, no `workspace` imports, no `["data"]` double-unwrap, no string-typed money, no date-only literals where instants are required, no space-only header values.
- **Both directories are at the task root** (`ls -la` shows `test_helpers/` and `test_suite/` alongside `SCAFFOLD*.yaml`, `worklog.md`, `workspace/`); `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation` — no stray `test_helpers/` or `test_suite/` inside it. `workspace/implementation/` was never read, listed, or written; no server was started; no broad `pkill`; `worklog.md` untouched; `__pycache__` artifacts removed.

Note for the orchestrator: Stage 2 was fanned out across five subagents (2-3 files each) working from a shared written brief; I verified every file myself with the checks above rather than trusting their reports.

## Step 7: Run Tests and Iterate — 2026-09-05T16:05:00.000Z

Subagent summary (verbatim):

All 8 rounds clean. Final state verified.

## Summary

**Iterations run:** 2

**Final sweep evidence (iteration 2, 8 parallel rounds):**

| Round | Passed/Total |
|---|---|
| 1 | 134/134 |
| 2 | 134/134 |
| 3 | 134/134 |
| 4 | 134/134 |
| 5 | 134/134 |
| 6 | 134/134 |
| 7 | 134/134 |
| 8 | 134/134 |

failed=0, errors=0, skipped=0 in every round.

**Tests deleted:** none. No test failed STEP 1a (PRD coverage) or STEP 1b (unique derivability).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** one line.
- `test_suite/test_09_rehearsal_and_readiness.py`, helper `_setup_divergent_evidence` (feeding `test_preflight_reads_100_while_certified_reads_47_50_on_the_same_row`): the helper captured the crew-call row returned by `offer_call` (status `OFFERED`), then invoked `accept_call` while **discarding** its return value, so the dict's `accepted_call` entry was a stale pre-acceptance snapshot. Changed `accept_call(api, accepted["id"], member_one["id"])` to `accepted = accept_call(...)`.

**Fixes applied to `implementation/`:** none. No implementation defect was found.

**Diagnosis detail on the single failure.** Iteration 1 was 133/134 in all 8 rounds with the identical failure `AssertionError: Expected crew-call status ACCEPTED, got OFFERED`. Triage:
- STEP 1a — PRD verbatim-covers the scenario in §3.7: *"for a production with an approved survey, one `RESERVED` primary booking, one `PENDING` preparation, and one `OFFERED` plus one `ACCEPTED` call against a `required_crew_positions` of 2, the preflight projection reads 100.00 while the certified figure reads 47.50."* STEP 1b — uniquely derivable; the sentence names both figures and both call statuses explicitly.
- STEP 2 — the failure was on the *setup*, not the rule: the two readiness assertions (`preflight=100.00`, `certified=47.50`), the stage assertion (`SURVEYED`) and the loss-budget assertion (5.41 dB) all passed on the line before, proving the implementation had genuinely moved the call to `ACCEPTED` and scored it as such. Only the test's own stale local variable disagreed. The implementation's `POST /crew-calls/{id}/respond` correctly returns the updated row (`routes_crew.py` returns `domain.crew_call_json(call)` after `set_fields(call, status="ACCEPTED")`), which is why the parallel helper `create_accepted_call` in `test_helpers/fixtures.py` — which does keep the returned row — works throughout the rest of the suite.

**Load-induced failures:** none observed. There were zero connection/timeout failures in either sweep; the iteration-1 failure was deterministic (identical message in all 8 rounds) and was a real test bug.

**Adjudication hypotheses from the brief:** all three flagged PRD-vs-scaffold items (`ERR_INVALID_REQUEST` as HTTP 400; malformed clock instant as `ERR_INVALID_TIME_WINDOW` 422; reversed proving window as `ERR_INVALID_TIME_WINDOW` rather than `ERR_TEST_WINDOW_INVALID`) plus both implementation-side notes (schema-level 400 on `POST /productions` window relations; rung 19 admitting both `PROVISIONED` and `REHEARSED`) produced no test disagreements — the suite and implementation already agreed with PRD prose on each, so no action was required.

**Orchestrator independent verification of the sweep artifacts:** all 8 `workspace/implementation/results.$i.json` files exist (each ~40.7 KB, all stamped 16:00) and were parsed directly by the orchestrator — every round reports `total 134 / passed 134 / failed 0 / errors 0 / skipped 0`. `workspace/SWEEP_DONE` reads `2026-09-05T16:00:39Z`. The Step 7 subagent did not touch worklog.md, as instructed.

**Step 8 decision:** NOT skipped. The skip condition requires zero deletions AND zero `test_suite/` fixes AND zero `test_helpers/` fixes AND zero `implementation/` fixes; Step 7 made one `test_suite/` fix, so Step 8 runs. Note for the reader: that fix was a stale-local-variable bug in a test setup helper, not evidence of PRD silence, so a byte-identical PRD_FINALIZED.md would be a legitimate Step 8 outcome here.

## Step 8: Finalize PRD — 2026-09-05T16:08:00.000Z

Subagent summary (verbatim):

## Result: PRD_FINALIZED.md is byte-identical to PRD.md — and that is the correct output

- `PRD.md`: 502 lines. `PRD_FINALIZED.md`: 502 lines. Delta: **0 lines, 0.00%**. `md5sum` matches on both (`d9693f92...`), `diff` is empty.
- **Changes: none.** No PRD edit was warranted.

### Why no edit

The `<step_7_diff>` contains exactly one fix, and it is a pure test-fixture bug with zero PRD implications:

- `test_suite/test_09_rehearsal_and_readiness.py`, helper `_setup_divergent_evidence` line 84: `accept_call(...)` was called for its side effect only, so `context["accepted_call"]` held the pre-acceptance `OFFERED` snapshot. Changed to `accepted = accept_call(...)`.

Everything the failure touched is already uniquely pinned in `PRD.md`:

- §2.2 line 55 — "operations that create or modify a resource will return the created or updated resource object in the data field" — determines that `POST /crew-calls/{id}/respond` returns the post-transition row. The impl at `implementation/routes_crew.py:165` (`return respond_object(domain.crew_call_json(call))` after `set_fields(call, status="ACCEPTED"...)`) matches verbatim.
- §3.6 line 298 — "An acceptance moves the call `OFFERED -> ACCEPTED`" — matches `routes_crew.py:161`.
- §3.7 line 326 — verbatim names the exact scenario and both figures (preflight 100.00 / certified 47.50). Nothing ambiguous to pin.

No implementation fix, no test deletion, no `test_helpers/` change, and no assertion weakening occurred, so under the HARD SCOPE rule there is no PRD-silence or PRD-mismatch site to patch. The five adjudication hypotheses the diff lists as producing no test disagreements are likewise already explicit in `PRD.md` (line 82/453 for `ERR_INVALID_REQUEST` = 400; line 92/488 for malformed clock instant = `ERR_INVALID_TIME_WINDOW` 422; line 252 for a reversed proving window = `ERR_INVALID_TIME_WINDOW` while only an escaping window is `ERR_TEST_WINDOW_INVALID`; line 198 for the schema-level window relations on `POST /productions`; line 306 for rung 19 admitting both `PROVISIONED` and `REHEARSED`) — and none of them produced a fix, so they are out of scope for an edit regardless.

### Per-edit pre-edit search log

Zero edits were committed, so there is no per-edit log. For completeness, the one candidate edit I considered and rejected:

- **(a) Subject considered:** the response body of `POST /broadcast-ops/crew-calls/{id}/respond` (does the PRD pin that it returns the updated row with `status: ACCEPTED`?).
- **(b) Impl paths enumerated and read:** `routes_crew.py` `respond_crew_call` (lines 145-165), plus every parallel crew-call mutator to check for a consistent return convention — `create_crew_call` (`respond_object(..., 201)` at line 120), `read_crew_call` (126), `list_crew_calls` (129-142), `release_crew_call` (168-209, returns updated row at 208), `cancel_crew_call` (211+). Also read `PRD.md` §2.2 envelope rules (lines 35-84) and §3.6 (lines 296-302), and cross-checked the test side at `test_helpers/fixtures.py:347` (`accept_call`) and `:367` (`create_accepted_call`).
- **(c) Wording adjustment:** none needed — §2.2 line 55's existing general clause already covers every enumerated mutator uniformly. Adding a respond-specific sentence would have been redundant at best, and at worst would have implied the other mutators are exceptions to line 55 — a brand-new mismatch Step 9 would have to undo. Left verbatim.

**Orchestrator note:** an identical PRD_FINALIZED.md is a legitimate Step 8 outcome — Step 7 applied zero implementation fixes, so there was no divergence site to patch. Verified independently: both files are 502 lines and `md5sum` agrees. This is expressly NOT acceptable for Step 9, which must run a full independent PRD-vs-implementation scan and is expected to produce a non-identical PRD_COMPLETED.md.

## Step 9: Complete PRD — 2026-09-05T16:35:00.000Z

Orchestrator note on method: Step 9 was run as THREE sequential subagent passes over one shared `workspace/PRD_COMPLETED.md`, partitioned by implementation module so that no pass had to hold the whole 11-module implementation plus the 505-line PRD in context at once. Pass 1 owned the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden from copying (a second `cp` would erase the prior pass's edits). Each pass was told to anchor edits on text rather than line numbers, and not to revert an earlier pass's work but to report disagreement instead. Slices:
  - Pass 1 — app.py, start.sh, core.py, store.py, domain.py (cross-cutting: envelope, error handlers, RBAC order, pagination, ordering, id/timestamp/version conventions, logical clock, precision, payload validator, serializers, calculations, cascades, recompute_production_stage)
  - Pass 2 — routes_registry.py, routes_production.py
  - Pass 3 — routes_transport.py, routes_crew.py, routes_systems.py, routes_show.py

### Pass 1 summary (verbatim)

Pass 1 complete.

## Verification
- `PRD_COMPLETED.md` exists; the `cp` from `PRD_FINALIZED.md` was performed by me (Step 0, this pass only).
- Source `PRD_FINALIZED.md`: 502 lines / 94,892 chars. `PRD_COMPLETED.md`: 503 lines / 104,213 chars. Char delta **+9,321**; line delta **+1** (one new bullet inside the existing §2.2 error-format bullet list; no new sections, no new headings).
- `md5sum PRD.md` = `md5sum PRD_FINALIZED.md` = `d9693f9268ffc1022fc4449e82793936` — both untouched and still byte-identical to each other.
- 8 diff hunks; only `PRD_COMPLETED.md` modified. No scratch files left in the task dir.

## Counts
- Ambiguity-pins: **14**
- Mismatch-revisions: **2** (§2.2 error-envelope status range; §3.3 `engine_hours_since_service` type)

## Changes
- §2.2 (`api_request_id` bullet) — insert — ambiguity — pins `req_` + exactly 20 chars from `A-Z0-9`, minted per response — `core.py:150,155`
- §2.2 (`api_request_timestamp` bullet) — insert — ambiguity — pins that this one timestamp reads the host **wall clock**, not the logical clock, so it won't match a same-request `created_at` — `core.py:156`
- §2.2 (error format lead-in) — revise — mismatch — "4xx status codes" -> "4xx and 5xx alike" (the 500 handler uses the same envelope) — `app.py:52-54`
- §2.2 (new bullet) — insert — ambiguity — pins transport-layer error ids/statuses: `ERR_NOT_FOUND`/404, `ERR_METHOD_NOT_ALLOWED`/405, `ERR_INVALID_REQUEST`/400 & 415, `ERR_HTTP_<status>`, `ERR_INTERNAL`/500 quoting the fault; plus that routing failures precede the 401/403 rungs — `app.py:37-54`
- §2.3 P1 — insert — ambiguity — pins non-integer `limit`/`offset` -> 400 (empty, `abc`, `1.5`, `+5`), whitespace trimmed, leading zeros OK, `limit` validated before `offset`, over-range offset -> empty page, enum filters -> 400 vs id filters matched literally -> empty page (never 404) — `core.py:229-263`
- §2.3 P2 — insert — ambiguity — pins ordering as a monotonic **creation sequence** (never `id`), which also governs clock-rewound creations and every "in `created_at` ascending order" summation — `store.py:98-100`, `store.py:46`
- §2.4 P1 — insert — ambiguity — `id` is a lowercase hyphenated v4 UUID; `created_at` is stamped from the logical clock — `core.py:63-64`, `store.py:46`
- §2.4 P2 — insert — ambiguity — **request-scoped `version`**: multiple mutations of one row in one request advance it by exactly 1; a no-op write bumps neither `version` nor `updated_at`; `updated_at` == `created_at` on creation — `store.py:65-95`
- §2.4 P3 — insert — ambiguity — clock set replaces the value outright and may wind backwards; omitted/`null`/non-string `to_iso8601` -> 400 while a malformed string -> 422; `created_at`/`updated_at` read the clock; all state in memory, empty at boot, clock reset per restart — `core.py:20,54`, `core.py:366-375`, `store.py:1-37`
- §2.7 rung 3 — insert — ambiguity — pins the payload validator: absent/unparseable body == `{}`; non-object JSON body -> 400; JSON `null` counts as absent (incl. for "forbidden" fields); blank/whitespace strings rejected except `notes`/`outcome_notes`/`note`; integers reject bools and floats incl. `5.0`; enum arrays reject non-array/empty/bad element but accept duplicates in order; instants accept `Z`/offset, naive == UTC, date-only == midnight UTC; unknown fields ignored — `core.py:289-388`
- §2.8 P2 — insert — ambiguity — 2-dp quantities serialize as bare JSON **numbers** (3.00->`3.0`, 47.50->`47.5`, 100->`100.0`), money/counts as integers, and truck engine-hour fields as int-when-integral — `core.py:128-129`, `domain.py:119-127`
- §2.9 lead-in + step 1 — insert — ambiguity — only rows whose values actually change are versioned; `required_crew_positions`/`required_validated_preps` re-asserted in step 1 — `domain.py:638-654`, `store.py:86-95`
- §2.9 step 6 — insert — mismatch-adjacent ambiguity — the closed-status guard runs **after step 1, before step 2** and abandons the rest: no provisioning test, no rehearsal abort, no `readiness_hold` for ON_AIR/WRAPPED/SETTLED — `domain.py:657-662`
- §3.3 (truck registration) — revise — mismatch — `engine_hours_since_service` is accepted as an integer *or* a fractional number (§2.7 rung 3 implies integer; impl uses the `number` validator) — `core.py:329-337`, `domain.py:139,141`
- §3.8 P1 — insert — ambiguity — pins which show record is "the" one when a production holds several: earliest `OFF_AIR`, else earliest with non-null `on_air_at_utc`, else earliest of all; none => zero air/overrun minutes — `domain.py:535-546`, `domain.py:729-734`
- §4 preamble — insert — ambiguity — trailing slash accepted as equivalent — `app.py:23`

## Slice confirmation
Every edit above is justified by behavior implemented in `app.py`, `start.sh`, `core.py`, `store.py` or `domain.py`. I read the six route modules only to confirm call sites of my helpers (`query_enum`/`query_string` filter names, `body.number` for engine hours, `body.string(allow_blank=True)` fields, `raw_instant` for the clock, `production_show` consumers) — no route-only behavior was patched. I did not read `SCAFFOLD*.yaml` or `worklog.md`, started no servers, ran no tests, and ran no `pkill`.

Note for passes 2/3: §2.2's bullet list gained one line, so all line numbers after ~line 78 in `PRD_COMPLETED.md` are shifted; anchor edits on text, not line numbers.

### Pass 2 summary (verbatim)

Pass 2 complete.

## Metrics

- **PRD_COMPLETED.md**: 503 lines before -> **503 lines after** (every edit was in-paragraph; no new paragraphs or sections)
- **Chars**: 104,213 -> **108,596** (**+4,383**)
- **11 edits**: 5 mismatch-revisions, 6 ambiguity-pins

## Changes

- **§3.1** — revise — mismatch — `SURVEYED -> PLANNED` was attributed to the §2.9 derivation, which has no such step; re-attributed to the survey-superseding operation — `routes_production.py:317-318`
- **§3.2** — insert — ambiguity — new survey's initial field values pinned: `submitted_by_user_id`/`reviewed_by_user_id` null, four plot aggregates at 0, `power_headroom_amps` at the production's full `venue_power_capacity_amps` — `routes_production.py:300-306`
- **§3.2** — revise — mismatch — supersede cascade is actually **three-way** by stage; PRD described only the `SURVEYED` branch and credited it to the derivation. Pinned: handler applies it directly; `PROVISIONED` (conditions holding) keeps its stage with *no* abort and *no* `readiness_hold`; `REHEARSED` falls to `PROVISIONED` via step 4 with a hold but *without* aborting rehearsals — `routes_production.py:311-321`
- **§3.2** — insert — ambiguity — camera-position add, survey submit and survey review consult **no** production-stage gate; only opening a survey does — `routes_production.py:342-357, 395-402, 431-448`
- **§3.2** — insert — ambiguity — review's `notes` is validated then discarded; the survey record has no notes field — `routes_production.py:436`
- **§3.2** — revise — mismatch — `PLANNED -> SURVEYED` is applied by the review itself and only when the production stands *exactly* at `PLANNED`; the derivation has no such step — `routes_production.py:451-456`
- **§3.3** — insert — ambiguity — `truck_code` uniqueness compared exactly, never case-folded or trimmed — `routes_registry.py:42-44`
- **§3.3** — revise — mismatch/ambiguity — truck-assignment's `version` bump is **unconditional** (`store.touch`, the only such call in the codebase), making it the sole exception to §2.4's no-op rule; and the superseded truck is driven to `AVAILABLE` from whatever status it stood in, not only from `ASSIGNED` — `routes_production.py:168, 184`
- **§3.5** — insert — ambiguity — `contract_expiry_utc` accepted even when already at/before the clock; registration never compares it to the clock — `routes_registry.py:183`
- **§2.4** — insert — ambiguity — clock endpoint answers 200 with `response_type` `object` and empty `data`; the reading is not echoed — `routes_registry.py:237`
- **§3.9** — insert — ambiguity — wrap sweeps `ACCEPTED` calls only; an `OFFERED` call is untouched and keeps carrying its provisional reserve in `labor_committed_cents` while being excluded from the settlement subtotal — `routes_production.py:202-204`
- **§3.9** — insert — ambiguity — settlement recomputes §2.9 step-1 scalars *after* the transport release, so both readiness figures shed the 25-point transmission component; the stage ladder is not re-entered — `routes_production.py:268`

## Confirmations

- **No `cp` run.** Edited the existing file in place with 11 targeted `Edit` calls.
- **Pass 1 survives** — spot-checked both requested anchors: §2.2 `ERR_METHOD_NOT_ALLOWED` transport-layer bullet (present) and §2.4 "scoped to the **request**" prose (present); also verified `ERR_HTTP_<status>`. No Pass 1 text was reverted or re-litigated.
- **`md5sum` of both PRD.md and PRD_FINALIZED.md still `d9693f9268ffc1022fc4449e82793936`.** No file other than PRD_COMPLETED.md was modified.
- **Stayed within slice** — every edit is justified by `routes_registry.py` or `routes_production.py`. I read `core.py`/`store.py`/`domain.py` for helper semantics only. Pass 3's four files untouched.

## Notes for the orchestrator

Two items worth flagging, neither of which I changed:

1. **No Pass 1 edit appeared wrong.** The one point of *tension* I resolved rather than reverted: Pass 1's §2.4 no-op rule ("a write that leaves every field at the value it already held is not a mutation") is contradicted by `routes_production.py:168`'s unconditional `store.touch`. I left §2.4 alone and pinned the exception locally in §3.3, since that is the only unconditional `touch` in the whole implementation (verified by grep).
2. **Deliberately skipped, as non-observable:** within-rung-3 field ordering (all variants share `ERR_INVALID_REQUEST`, so message-only differences); the §3.9 prose listing stage-then-SoD for settle while §2.7's ladder pins SoD at rung 16 ahead of stage at 19 (ladder already authoritative, same for survey review); and a fresh survey rendering `total_signal_loss_db` as JSON `0` rather than `0.0` (§2.8 is Pass 1's slice and JSON parsers equate them).

### Pass 3 summary (verbatim)

Pass 3 complete.

## PRD_COMPLETED.md size

| | lines | chars |
|---|---|---|
| before my pass | 503 | 108,596 |
| after my pass | 505 | 115,132 |

17 edits: **12 ambiguity-pins, 5 mismatch-revisions**. Only one new paragraph (§3.6); everything else is an in-paragraph insert or revision. No new sections.

## Changes

- **§2.7 rung 3** — insert — mismatch — the seven body conventions (incl. "a non-object body is `ERR_INVALID_REQUEST`") are scoped to operations that name at least one body field; the bodyless ones read no body and accept anything. `routes_transport.py:229`, `routes_crew.py:215`, `routes_systems.py:96`
- **§3.4** — revise — mismatch — PRIMARY supersession releases **every other** active-status `PRIMARY` of the production in created order (not "that earlier booking"), skips ones already `RELEASED`/`FAILED_OVER`, runs after the new row exists, and therefore lets the new satellite window clash with the outgoing primary. `routes_transport.py:106-115`
- **§3.4** — insert — ambiguity — schedule-test / test-result / release never consult the production's stage; `test_attempt_count` is not reset by a re-schedule. `routes_transport.py:148,190,228`
- **§3.4** — insert — ambiguity — test-result `notes` is type-checked then discarded (booking has no notes field). `routes_transport.py:193`
- **§3.5** — insert — ambiguity — opening a prep runs step 1 of §2.9 **only** (`recompute_production_scalars`), so `readiness_score_preflight` rises on a `PENDING` prep and the stage ladder is not entered. `routes_systems.py:67`
- **§3.5** — insert — ambiguity — validate-feed does not consult the production's stage. `routes_systems.py:93-117`
- **§3.7 readiness list** — revise — mismatch — added "the opening of a system preparation" to the list of gating changes that recompute readiness. `routes_systems.py:67`
- **§3.6** — insert — ambiguity — the `offer_rate_cents` employment-type rule fires at rung 3 (ahead of an unknown `production_id`) but is **skipped** when the member does not exist, so that case reports `ERR_CREW_MEMBER_NOT_FOUND`. `routes_crew.py:41-48`
- **§3.6** — insert — ambiguity — a `CrewMember` may read/list *every* call; the §2.1 ownership comparison applies to respond alone. `routes_crew.py:124,130`
- **§3.6** — insert (new short paragraph) — ambiguity — respond/release/cancel ignore the production's stage, so a call can be answered/released/cancelled on an `ON_AIR`/`WRAPPED`/`SETTLED` production, moving the labor ledger and readiness while the stage stands still. `routes_crew.py:147,170,214`
- **§3.7** — revise — ambiguity + mismatch — signoffs are strict booleans; a `COMPLETED` outcome with **no `APPROVED` survey** is `ERR_REHEARSAL_SIGNOFF_INCOMPLETE`; and the ordering is pinned as hold-cleared -> derivation -> promotion (PRD previously read "the derivation is run first"). `routes_systems.py:192-241`
- **§3.8** — insert — ambiguity — `target_air_status: PRE_SHOW` passes schema but is always `ERR_SHOW_STATE_INVALID`. `routes_show.py:123-124`
- **§3.8** — insert — ambiguity — going off air is guarded by the air dimension alone (no stage, readiness or curfew re-check). `routes_show.py:120-122`
- **§3.8** — insert — mismatch — the 20-minute downtime trigger fires **before** path-loss failover, so one `PATH_LOSS` crossing the threshold ends `OFF_AIR` *and* `ON_BACKUP`; PRD had said "the show stays on air". `routes_show.py:212-219`
- **§3.8** — revise — ambiguity — failover target picked deterministically: earliest `CONFIRMED` `PRIMARY`, else earliest `PROMOTED` of any role, else none. `routes_show.py:229-239`
- **§3.8** — revise — ambiguity — the promoted standby is the earliest-created `CONFIRMED` `BACKUP`. `routes_show.py:245-248`
- **§3.8** — revise — ambiguity — the `LOST` branch runs even with no bookings at all, and does not re-stamp `off_air_at_utc` when already `OFF_AIR`. `routes_show.py:256-259`

## End-of-step verification

- Final: **505 lines / 115,132 chars**.
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` -> **163 lines** (non-empty; the scan ran).
- `md5sum` of both `PRD.md` and `PRD_FINALIZED.md` = `d9693f9268ffc1022fc4449e82793936` — unchanged. (Both live in `workspace/`, not the task root.)
- Prior-pass edits survive: §2.2 `ERR_METHOD_NOT_ALLOWED` transport-layer bullet OK, §2.4 "`version` is scoped to the **request**" OK, §3.3 "That version increment is **unconditional**" OK.
- No `cp` was run. Only `workspace/PRD_COMPLETED.md` was edited, via 17 targeted `Edit` calls. I stayed inside my slice: every edit is justified by `routes_transport.py`, `routes_crew.py`, `routes_systems.py` or `routes_show.py` (I read `core.py`/`store.py`/`domain.py`/`routes_production.py` only to resolve helpers such as `check_occ`, `require_open_production`, `recompute_production_scalars`, `set_readiness_hold` and `prior_call_for_member`).

## Notes for the orchestrator

- I did not revert anything from Passes 1-2 and found nothing in them I believe is wrong.
- One item straddles passes: the bodyless-endpoint carve-out I added to §2.7 also covers survey submit, feed suspend, wrap and settle (Pass 2's files). I verified all seven bodyless handlers skip `Payload()`, so the statement is accurate system-wide; I phrased it as a scope caveat on Pass 1's "Seven conventions" sentence rather than an eighth convention, so that count stays correct.
- `implementation/` still holds the eight `results.*.json` sweep artifacts from Step 7 (~40 KB each); harmless, but they sit inside the impl directory if you want them cleaned before packaging.

### Step 9 aggregate + orchestrator verification

- Total across the three passes: **44 edits — 32 ambiguity-pins, 12 mismatch-revisions.**
- `workspace/PRD_COMPLETED.md`: 505 lines / 115,132 chars, versus 502 / 94,892 for PRD.md (+3 lines, +20,240 chars, +21.3%). `diff PRD_FINALIZED.md PRD_COMPLETED.md` is 163 lines — NOT byte-identical, so the scan demonstrably ran (an identical file would have meant it did not).
- Independently re-verified by the orchestrator: `md5sum` of PRD.md and PRD_FINALIZED.md both still `d9693f9268ffc1022fc4449e82793936`; PRD_COMPLETED.md is `fd19562e6cb751cd074e36739c125ff5`. Heading count is 33 in both PRD.md and PRD_COMPLETED.md, confirming no pass added a section. PRD_COMPLETED.md ends on the complete final row of the §5 error table — not truncated.
- All 8 `workspace/implementation/results.$i.json` from the Step 7 final sweep are intact and still report 134/134; the suite is still 134 test functions. Steps 8 and 9 wrote only `workspace/PRD_FINALIZED.md` and `workspace/PRD_COMPLETED.md` and changed no code or test file, so no confirmation sweep was re-run — the green sweep artifacts remain valid for the current tree.
- The `results.*.json` files are retained deliberately: the skill's Output section lists them as an expected artifact of the final passing sweep.
- No difficulty-directive leak anywhere in the task tree. (`grep -rn "harder than expert"` matches only this worklog's own two audit notes about having stripped the line from SCAFFOLD.yaml.)

## Pipeline complete — 2026-09-05T16:40:00.000Z

Steps 1 through 9 all finished. Final artifact set: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files) + test_suite/ (conftest + 13 files, 134 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, sweep.sh, sweep.log, SWEEP_DONE, implementation/}, and worklog.md.
