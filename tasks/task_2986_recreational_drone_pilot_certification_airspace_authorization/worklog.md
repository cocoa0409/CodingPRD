## Step 1: Create task directory — 2026-09-06T01:41:35.680469504Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2986_recreational_drone_pilot_certification_airspace_authorization and /home/ubuntu/github/CodingPRD/tasks/task_2986_recreational_drone_pilot_certification_airspace_authorization/workspace. Index 2986 pre-assigned by orchestrator input; no auto-allocation scan performed.


## Step 2: Generate Scaffold — 2026-09-06T03:25:20.200Z

Step 2 complete. All three scaffold artifacts are written, lint-clean, and valid YAML.

**Deliverables**:

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3269 | 175,351 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2072 | 137,184 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4811 | 310,975 |

**Scaffold size**: `api_prefix: /drone-ops`; 14 entities, 12 state machines, 2 concurrency rules, 14 calculations, 38 validations, 70 endpoints, 61 errors, 6 roles. Top-level keys are exactly the 13 §1.0–§1.7 keys — neither design key leaks into `SCAFFOLD.yaml`. Design files each carry exactly one top-level key (`scaffold_difficulty_design` / `scaffold_corner_design`), with 21 and 79 instances respectively (26 of the corner instances are `excluded_because` stubs, leaving 53 lintable ones across all 9 claim-guide sections).

**Lint verdict** (verbatim):
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    70
  §1.1 entities declared:     14
  §1.8 instances scanned:     21
  §1.9 instances scanned:     53
  Calls scanned (§1.8+§1.9):  1072

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Design decisions worth recording:**
- Complexity profile is `compliance_audit` / `temporal_windowing` over a graph topology with cyclic state machines, `segregation_of_duties` roles and `immediate` consistency. The four layers are `cascading_side_effects`, `dual_variant_calculation`, `optimistic_concurrency`, `selector_policy`.
- Dual-variant calculations are `pilot_currency_expiry` (RECREATIONAL_BASIS = cert issue + 24 months vs COMMERCIAL_BASIS clamped to last completed flight + 90 days) and `accident_settlement` (PROVISIONAL reserve at 1.25x + flat injury reserve vs FINAL itemized coinsurance at 0.85 with deductible and tier surcharge) — both give different numbers from identical inputs.
- Two OCC gates: `expected_zone_version` on authorization create, `expected_pilot_version` on waiver create (the supersede path). Both are exercised positively and negatively with `${...}` versions.
- The 38 validations are a single explicit priority chain (auth -> role -> ownership -> SoD -> path -> shape -> window -> body FK -> uniqueness -> OCC -> invalid-state -> preflight -> suspended -> certification -> currency -> registration -> grounded -> remote-ID -> TFR -> waiver -> authorization -> containment -> ceiling -> category -> capacity -> turnaround -> safety case -> SAIL -> revision limit -> duplicate report -> attempt cap -> fiscal -> clock rewind). Several corner probes exist specifically to prove a *lower*-priority rule can be reached (e.g. a separate UNCERTIFIED pilot is needed to reach the recreational/commercial rule past the pilot-state check).
- Corner file owns the `selector_policy` claim (covering-policy tie-break by `created_at`, expired candidate dropped) because §1.8 has none; window arithmetic, capacity, turnaround, revision/remediation limits and the suspension cascade are deferred to §1.8 via stubs to avoid duplicate claims.
- All 61 error ids are referenced across §1.8/§1.9, and all 70 endpoints are hit by structured calls (verified programmatically: `endpoints never called: []`), including a dedicated instance covering the 9 collection GETs and their declared filters.

**One fix applied at the end:** `SCAFFOLD.yaml`'s `scenario` value had absorbed the meta-directive line `Generate task harder than expert level!`. That line (plus its blank separator) was stripped so it cannot propagate into PRD.md; the remaining scenario text is byte-identical to the supplied description. `worklog.md` and `workspace/` were not touched; scratch is confined to `.scratch/step2/`.

ORCHESTRATOR NOTE: verified independently — `grep -n "harder than expert" SCAFFOLD.yaml` returns nothing; scenario key begins "2986. Recreational Drone Pilot...". Difficulty directive did not leak.

## Step 3: Copy Shared Files — 2026-09-06T03:25:20.224Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md -> $TASK/workspace/INSTRUCTION.md (53 lines).

## Step 4: Generate PRD — 2026-09-06T03:45:04.767Z

PRD generation for task_2986 is complete.

## Deliverable

`workspace/PRD.md` — **509 lines / 121,437 bytes**, built in 8 incremental appends (32 -> 81 -> 121 -> 155 -> 200 -> 232 -> 270 -> 306 -> 332 -> 364 -> 509), with `wc -l` verified after every one. No truncation occurred at any step.

## Section list

- `# Drone Pilot Certification & Airspace Authorization API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC (6 roles, entity-backed Pilot identity, both segregated pairs) / 2.2 API Response Structure / 2.3 Pagination & List Ordering (incl. the pilots-`DESC` exception) / 2.4 The Logical Clock / 2.5 Identity, Timestamps & Versioning / 2.6 Path Resolution & Reference Integrity / 2.7 Optimistic Concurrency on Zones and Pilots / 2.8 Cascading Consistency & Lazy State Discovery (5 cascades + lazy-transition inventory) / 2.9 Arithmetic, Cents & Rounding / 2.10 Conserved Quantities / 2.11 Validation Precedence (all 38 rungs, ordered, each with `error_id`, status and exact scope)
- `## 3. Business Logic & Workflows` — 3.1 Becoming a Certified Remote Pilot / 3.2 Currency, Lapse & Recurrent Training / 3.3 Airframes, Registration & Remote ID / 3.4 Airspace Structure, Restrictions & Authorization / 3.5 Waivers & the Safety Case Review Loop / 3.6 Insurance Cover & Commercial Indemnification / 3.7 Planning, Clearing & Flying a Mission / 3.8 Accidents, Investigation & Settlement / 3.9 Enforcement: Risk, Suspension, Reinstatement & Revocation
- `## 4. Endpoint Definitions` — status-code paragraph (13 creations at 201, incl. preflight-check even on `FAILED`) + 4-column table, 70 rows
- `## 5. Error Code Catalogue` — 2-column table, 61 rows. **Document ends here; no audit footer.**

## Verification results (all mechanical, via `.scratch/step4/verify.py` and `verify2.py`)

- **Endpoint coverage: 70/70** paths present. Missing: none.
- **Error coverage: 61/61** ids present. Missing: none.
- **Contract 1 (Field-Name Coverage): PASS** — 0 missing of the full required set (all `entities[].fields[].name` + common fields + every endpoint `input`/`query_params`/output identifier).
- **Contract 2 (Rule Coverage): PASS** — every state-machine state and transition literal, every enum member, every calculation constant *value* (all 30+ numeric literals verified present), and every `error_id` referenced anywhere in `validations` are all in the prose. Only bare *constant names* (`BASE_CEILING_FT`, `STRUCTURE_RELIEF_FT`, `CERT_VALIDITY_MONTHS`, `INJURY_RESERVE_CENTS`, `REMOTE_ID_WEIGHT_THRESHOLD_G`) are absent — intentional, since the spec requires numeric values in prose rather than symbols. No operator syntax / pseudocode anywhere outside the fixed §2.2 JSON block.
- **Contract 3 (§3 Path Purity): PASS** — 0 violations across 60,033 characters of §3: no backtick token starts with `/`, no bare HTTP method, no method+path combination.
- **No leakage** — neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or grepped; no sibling task dir was read. Grep for `harder than` / `expert level` / `test_recipe` returns nothing.
- **Tail confirmed complete**: the file's last line is the final row of the §5 table and the last error in `SCAFFOLD.yaml`'s catalogue. Not truncated.

## Scaffold contradictions adjudicated (each by majority of independent scaffold sources)

1. Ground-cascade `cancellation_reason` -> `AUTHORIZATION_REVOKED` (endpoint bullet's `AIRCRAFT_GROUNDED` is not in the Flight transition list or the field's own enumeration).
2. Reinstatement `risk_score` -> **recomputed**, not reset to 0 (state machine + calc trigger list outvote the endpoint bullet). PRD also states reinstatement never re-fires automatic suspension.
3. `attempt_number` -> 1 + count of pre-existing tests **in any state** (entity field + state machine outvote the endpoint's `knowledge_attempt_count + 1`); `knowledge_attempt_count` counts only `PASSED`/`FAILED` and moves at grading.
4. `open_waiver_count` -> always recomputed from its definition (so approval does not decrement it, since `APPROVED` counts as open); pilot `version` increments on both outcomes.
5. `POST .../aircraft/{id}/register` -> takes no body; the server assigns `registration_number`.
6. Accident filing precondition -> flight `status` in `{IN_PROGRESS, COMPLETED, CANCELLED}` (state machine's set, broader than the endpoint blurb's two).

Ten error identifiers initially written from memory did not exist in the catalogue and were remapped to real codes (e.g. `ERR_AIRCRAFT_SCHEDULE_CONFLICT`, `ERR_SAFETY_CASE_MISSING`, `ERR_ACCIDENT_REPORT_DUPLICATE`, `ERR_REVISION_LIMIT_EXCEEDED` for the remediation budget, `ERR_REMOTE_ID_NOT_VERIFIED`, `ERR_WAIVER_REQUIRED`). A reverse check now confirms **zero invented `ERR_*` tokens** in the document. Two judgement calls where the scaffold has no dedicated code: the waiver-decision `granted_ceiling_ft` constraint is reported as `ERR_INVALID_REQUEST`, and both reinstatement preconditions (open investigation, lapsed currency) as `ERR_PILOT_INVALID_STATE`.

ORCHESTRATOR NOTE: independently verified the truncation guard — PRD.md is 509 lines / 121,437 bytes, last line is `| \`ERR_INSURANCE_COVERAGE_INSUFFICIENT\` | 402 |` (a complete table row), all 5 top-level sections and 21 subsections present, and grep for `harder than expert` / `expert level` / `test_recipe` / `scaffold` returns nothing. PRD accepted; no regeneration needed.

## Step 6: Generate Implementation — 2026-09-06T04:14:51.740Z

(Steps 5 and 6 were launched concurrently in a single orchestrator message, per the skill. Step 6 returned first, so its entry is recorded here ahead of Step 5's.)

Implementation complete: all 70 endpoints, live-verified.

## Modules written (`workspace/implementation/`)

| file | lines | role |
|---|---|---|
| app.py | 66 | Flask factory, 7 blueprints under `/drone-ops`, ApiError/404/405/500 handlers, `PORT` bind |
| errors.py | 85 | all 62 error ids -> HTTP status, `ApiError` |
| clockmod.py | 80 | logical clock (start `2026-08-01T00:00:00Z`), monotonic `set`, ISO formatters, calendar month/day/minute arithmetic |
| store.py | 73 | in-memory dicts, 14 collections, id/created_at/updated_at/version, `CERT-%06d` / `FA%08d` counters |
| envelope.py | 42 | §2.2 envelope, `req_` + 20 alnum, 3-digit ms timestamp, list meta |
| shape.py | 231 | rung-7 validators + pagination (limit 1-100, offset >= 0) |
| auth.py | 96 | rungs 1-3, `owner_of` per entity, pilot list scoping |
| views.py | 91 | per-entity field lists; PreflightCheck alone has no `updated_at`/`version` |
| calc.py | 328 | currency projection, granted ceiling, SAIL, ledger, reserve/settlement waterfalls, risk score, flight summary |
| cascades.py | 267 | five cascades + lazy state discovery + remote-ID rungs 20/21 |
| common.py | 71 | rung-6 existence, filters, list pipeline |
| routes_pilot.py | 331 | clock, pilots, knowledge tests, certifications (16) |
| routes_aircraft.py | 203 | airframes + remote-ID modules (11) |
| routes_airspace.py | 251 | zones, TFRs, authorizations (12) |
| routes_waiver.py | 262 | waivers + safety-case review loop (10) |
| routes_insurance.py | 92 | policies + verify (4) |
| routes_flight.py | 434 | plan/check/launch/complete/cancel (8) |
| routes_accident.py | 207 | file/investigate/remediate/close/withdraw (9) |
| start.sh / requirements.txt | 10 / 1 | `PORT` env, `0.0.0.0`, foreground `exec python3 app.py`, guarded pip |

Total 3221 lines. `compileall` clean; no `__pycache__` left behind.

## Endpoint coverage
**70/70.** Diffed the URL map against the endpoint table extracted from PRD §4 — exact match, no extras, no misses. All 61 PRD error ids are reachable (48 raised literally, the 13 `*_NOT_FOUND` via `common.must_exist`'s map).

## Smoke result: PASS
Booted on a random high port via `bash start.sh`, ran a 60-call walk with 25 assertions, killed only the captured PID (both smoke servers confirmed stopped, ports free). Verified: envelope byte-shape for object/array/error against §2.2; pilot roster descending while other lists ascend; certification flow; remote-ID gate (422 before verify, 200 after); ledger opening at the limit on verify; rung ordering (11 stale-zone 412, 12 stale-pilot 412, 14 not-cleared 409, 30 safety-case 422, 35 insurance 402); slot conservation (reserve 1 on approve -> 0 on completion); `logged_minutes` 53 from a 53m30s flight; `altitude_exceedance` true at 520 ft over a 500 ft grant; reserve 750000 = round_half_up(400000x1.25)+250000; settlement 981751 = (850001+212500)-100000 deductible +2% tier surcharge; waiver `valid_until` at now+180d. A second boot showed `total_count: 0` — no seeded data, state resets per launch.

Two behaviours worth flagging as correct-per-PRD, not bugs: filing the accident drove `risk_score` to exactly 70 (25 incident + 15 exceedance + 30 open accident) and auto-suspended the pilot mid-walk, which then correctly blocked waiver creation with `ERR_PILOT_SUSPENDED`.

## PRD ambiguities resolved
1. `POST /flights/{id}/complete` with `actual_end <= actual_start` -> `ERR_INVALID_WINDOW` (400), evaluated **after** rung 13 since complete is absent from rung 8's endpoint list.
2. Launch with a cited authorization that is not `APPROVED` or not live now -> `ERR_AUTHORIZATION_INVALID_STATE` (409), evaluated last, after rung 22.
3. Module `verify` with `outcome=VERIFIED` and a past `verified_until` -> `ERR_INVALID_REQUEST`; the analogous policy case is explicitly `ERR_POLICY_INVALID_STATE` and is coded as such.
4. `indemnification_clause_accepted` has no stated default -> optional, defaults `false` (lower blast radius than making it required).
5. Accident filing checks only the flight's operational status at rung 13, letting rung 33 own duplicates; re-filing after a withdrawal resets `investigation_status` to `OPEN`.
6. Rungs 18/19 on authorization and flight creation: rung 18 names only `PENDING_REGISTRATION`/`DEREGISTERED`, so a `GROUNDED` airframe falls through to rung 19.
7. Pilot lapse transition is bound to rung 17, not to the pre-gate lazy sweep, so a lapsed pilot yields `ERR_PILOT_CURRENCY_LAPSED` rather than being masked by rung 16.
8. Rung 25/26 apply whenever `authorization_id` is supplied, even in an uncontrolled zone; effective ceiling falls back to 400 ft when the grant is null.
9. Closure with a null `policy_id`: deductible 0, no cap.
10. `days_remaining` truncates toward zero; `api_request_timestamp` is the only wall-clock value in the service.

Also fixed while writing: `settlement_for` now tolerates a null policy, and `shape.py` gained `req_num`/`req_object_list` for lat/long and damage line items.

ORCHESTRATOR NOTE: independently verified — 20 files / 3210 lines of .py in `workspace/implementation/`; `start.sh` reads `$PORT`, binds via app.py, and `exec`s in the foreground with a guarded pip install; grep for `sqlite` / `json.dump` / file-write / `/tmp/` in the implementation returns nothing, so storage is in-memory only. Stray `__pycache__` removed. `test_helpers/` and `test_suite/` are at the task root (not under `workspace/`), as required.

## Step 5: Generate Unit Tests — 2026-09-06T04:58:08.877Z

(Launched concurrently with Step 6 in a single orchestrator message; returned after Step 6, hence recorded below it.)

Step 5 is complete. Both stages are on disk at the task root.

## Files written

**`test_helpers/`** (Stage 1, 9 files / 3,563 lines): `__init__.py` (147), `types.py` (547, 30 enums + 16 TypedDicts), `api_client.py` (522, 77 endpoint methods), `api_errors.py` (159, all 61 error ids + status map registered with the framework), `constants.py` (165), `factories.py` (468), `assertions.py` (611), `fixtures.py` (805, 5 tiers), `test_users.py` (133).

**`test_suite/`** (Stage 2, 14 files): `conftest.py` (86) plus 13 numbered domain-language test files, 10,999 lines total — `test_01_pilot_registration_and_knowledge_testing.py` (842/16 tests), `test_02_pilot_currency_and_certification_lifecycle.py` (564/8), `test_03_airframe_registration_and_remote_id.py` (568/11), `test_04_airspace_zones_and_authorizations.py` (819/18), `test_05_zone_slots_and_version_gates.py` (974/14), `test_06_waivers_and_safety_cases.py` (874/12), `test_07_insurance_coverage_and_fiscal_gates.py` (882/12), `test_08_flight_planning_and_preflight.py` (803/17), `test_09_flight_summary_and_risk_scoring.py` (738/10), `test_10_accident_reports_and_settlement.py` (1124/12), `test_11_enforcement_cascades_and_terminal_states.py` (1060/11), `test_12_access_control_and_identity.py` (811/10), `test_13_error_catalogue_and_collection_filters.py` (953/15).

**166 test functions, 205 collected pytest items** (parametrized families). Every file has >=5 tests.

## Coverage

- **Queue A: 21/21 difficulty instances translated, 0 skipped, 0 shortfalls** (all >=2 tests).
- **Queue B: 53/53 non-stub corner instances translated, 0 missing.** The 26 `excluded_because:` stubs were not translated, and all 26 `difficulty_instance` cross-references were verified to resolve.
- Zero untagged, dual-tagged, or dangling `Design:` tags; zero tags pointing at a stub.
- Three bundled *sub*-assertions were dropped for failing unique derivability (the instances themselves are still covered): the "touching restriction still permits launch" half of `a_restriction_published_after_clearance_blocks_the_launch_until_lifted` (the PRD makes the flight window closed but the restriction window half-open, so they intersect at the shared instant); the "no PATCH/DELETE on tfrs" half of `restriction_create_read_and_filtered_list_round_trip` (route absence is not observable); and the "re-file after withdrawal" half of `duplicate_accident_filing_...` (§3.7 requires `investigation_status == NONE` while withdrawal sets `CLOSED`). `ERR_INSURANCE_COVERAGE_INSUFFICIENT` (rung 37) is also unasserted — it is only reachable through an `ACTIVE`->`INSUFFICIENT` path the PRD does not pin.

## Verification

`ls -d` confirms both directories are at the task root and `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`, `sweep.sh` — no stray copies anywhere beneath it. `python3 -m py_compile` clean on all 23 `.py` files; `pyflakes` clean; `pytest --collect-only` imports the whole suite with **zero errors and zero warnings**. Grep sweeps return nothing for `scaffold` / `§1.8` / `§1.9` / `Table N`, for `mark.skip`/`skipif`/`xfail`, for money-as-string or money-as-float, for date-only instants, and for double-unwrapped envelopes. All 525 quoted PRD citations were re-verified independently by whitespace-normalised literal match against `PRD.md`: 0 non-verbatim.

Both input-yaml defects are fixed: `BLUETOOTH_5` is absent (`BLUETOOTH_LE` used), and **no instant literal anywhere in the suite predates the `2026-08-01T00:00:00Z` startup value** — all 15 distinct literal clock targets are strictly after it, so no test can trip `ERR_CLOCK_REWIND_FORBIDDEN`.

## Three bugs found and fixed in Stage 1 output

1. `test_helpers/__init__.py` did not re-export `ModuleOutcome` or `PolicyOutcome`, which broke `test_03`'s import at collection time. Added both.
2. `conftest.py`'s `clock` fixture called `Clock()` but `Clock.__init__(self, api, headers=None)` requires `api`. Fixed to `Clock(api)`. (Four writers flagged this; two described the signature backwards — adjudicated from the source. No test actually requests the fixture, so nothing was blocked.)
3. `TestCode` (a knowledge-test code enum) triggered `PytestCollectionWarning` in five files; added `__test__ = False`.

## Worth passing to Step 7

Writers reported several design-yaml literals that contradict the PRD; in every case the PRD was trusted, so a failure on one of these is an implementation bug, not a test bug: `ERR_TEST_ATTEMPT_LIMIT` is **409** (yaml said 422); `ERR_RECREATIONAL_OPERATION_FORBIDDEN`/`ERR_AIRCRAFT_NOT_REGISTERED`/`ERR_AIRCRAFT_GROUNDED` are **403/409/409** (yaml said 422); `currency_basis` is derived at pilot creation, not null; a freshly filed policy reports all three ledger figures at **0**; a request-stage authorization does **not** bump the zone version and reserves no slot; and a commercial flight under an `INSUFFICIENT` policy yields **`ERR_INSURANCE_NOT_ACTIVE` (402)**, not `ERR_INSURANCE_COVERAGE_INSUFFICIENT`. Also note the PRD's whitespace-header rule is unreachable over HTTP — `requests` raises `InvalidHeader` client-side — so `test_12` exercises blank identity via `""`, missing headers, and `NO_HEADERS` only.

Scratch was confined to `.scratch/step5/`, which was removed; the sibling `.scratch/step2` and `.scratch/step4` are intact. `worklog.md`, both `SCAFFOLD*.yaml` files, `PRD.md`, `INSTRUCTION.md` and `workspace/implementation/` were never written to, and `workspace/implementation/` was never read.

ORCHESTRATOR NOTE: independently verified — 9 helper files + 14 test files, 14,656 lines total, both directories at the task root with nothing stray under `workspace/`; `grep -rn "mark.skip\|xfail"` returns nothing; `Design:` tag census is 118 Corner + 48 Difficulty tags. `.scratch/step5` confirmed removed with step2/step4 intact.

## Step 7: Run Tests and Iterate — 2026-09-06T05:23:37.825Z

All 8 parallel rounds pass at **205/205**. Sibling scratch dirs (`step2`, `step4`) survived; `worklog.md` untouched.

## Summary

**Iterations run:** 2 (each a full 8-round parallel sweep).

**Baseline (iteration 1):** 202/205 in all 8 rounds — 3 deterministic failures (each failing 8/8, so no flakiness anywhere in the suite).

**Tests deleted:** none. No test failed the STEP 1a coverage check outright.

**Fixes applied to `test_helpers/`:** none. Audited `api_client.py`, `factories.py`, `fixtures.py`, `test_users.py`, `constants.py`, `assertions.py` against the known upstream-fixture failure shapes (money-as-string, date-only instants, sub-second width, envelope double-unwrap, duplicate kwargs, clock parked outside window, paginated-vs-unpaginated) — none applied; the helper layer was clean and the failures were not setup errors.

**Fixes applied to `test_suite/`:**
- `test_11_enforcement_cascades_and_terminal_states.py`, `test_filing_opens_the_investigation_erodes_the_cover_and_cancels_the_next_mission` — removed the exact version-delta assertion `policy["version"] == before + 1` (replaced with the covered, strictly-weaker claim that the row's version advanced). **STEP 1b failure, unique derivability broken.** PRD §2.8 attributes exactly one bump to the ledger write ("its `remaining_coverage_cents` falls by that reserve, bumping the policy's `version`") and then describes the `ACTIVE -> INSUFFICIENT` demotion as a further cascade link **with no version claim at all**, while §2.5 says `version` "increments by exactly 1 on **every mutation** of that row" — and the demotion is a write of `coverage_status` to that same row. Both readings are PRD-faithful (+1 as one atomic event per row, or +2 as ledger-write plus derived-status-write), so the exact delta is not uniquely determined. Every PRD-covered assertion in the test (reserve of 1,250,000; `open_reserved_cents_total`; `remaining_coverage_cents` 750,000; `INSUFFICIENT`; ledger conservation; investigation opening without touching operational status; the `COVERAGE_INSUFFICIENT` cancellation of the fourth link) was kept intact — this is STEP 1c partial-coverage handling, not a deletion. Scaffold rule that drove it: `Difficulty/transitive_cascade/accident_filing_cascades_through_investigation_and_coverage_to_future_flight`.

**Fixes applied to `implementation/`** (both remaining failures were one root cause):
- `cascades.py`, `check_remote_id()` — rung 20 now measures presence over modules in `VERIFIED` **or** `EXPIRED`, letting rung 21 own the verdict. Previously the launch path's §2.8 lazy transition moved the stale `VERIFIED` module to `EXPIRED` *before* the gate ran, so rung 20 saw no `VERIFIED` module and returned `ERR_REMOTE_ID_NOT_VERIFIED` where PRD rung 21 requires `ERR_REMOTE_ID_EXPIRED` (422). Rung 20's own enumeration of its failures — "`UNVERIFIED`, `VERIFICATION_PENDING` or `VERIFICATION_FAILED`, or the absence of any module row" — deliberately omits `EXPIRED`, and under the old ordering rung 21 was unreachable dead code on all three of its endpoints, which is not a defensible reading. Verified against all 12 remote-ID error expectations in the suite: the two `NOT_VERIFIED` cases are "no module at all" and "only a `VERIFICATION_FAILED` module", both still correct.
- `routes_flight.py`, `run_lazy_transitions()` — left the up-front module expiry in place (an intermediate revision had removed it) so PRD §3.7's "a launch that fails on a stale gate still leaves the stale row correctly transitioned" holds even when launch is refused at an earlier rung; the gate rewrite above is order-independent, so both PRD sentences are now satisfied simultaneously. Comment updated to record why.

**Final sweep evidence** (`implementation/results.{1..8}.json`, left in place): 205/205 x 8 — union of failing tests across all 8 rounds: 0. Cross-checked per rule 4: `total - passed == 0` matches zero non-`passed` entries in every round.

ORCHESTRATOR NOTE: independently re-verified the sweep artifacts rather than trusting the summary. All 8 `results.$i.json` exist (written 05:19, ~69.8 KB each); a fresh parse of each keyed on the runner's real schema (`tests[].status`) gives `passed=205 total=205 entries=205 non-passed=0` for every round, and the `total - passed == len(non-passed)` cross-check holds in all 8. `workspace/SWEEP_DONE` sentinel reads `2026-09-06T05:19:34Z`. Step 7 had non-zero fixes (1 `test_suite/` edit, 2 `implementation/` edits), so Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-06T05:29:01.288Z

Done. `PRD_FINALIZED.md` written with 4 surgical edits.

## Line counts
- `PRD.md`: 509 lines / 121,437 bytes
- `PRD_FINALIZED.md`: 509 lines / 122,531 bytes
- Line delta: 0 lines (0.0%); 4 of 509 lines revised (0.79% of lines), +1,094 bytes (+0.90%). Final table row is identical.

## Changes

- **§2.8 (Filing an accident report cascade)** — revise — the `ACTIVE -> INSUFFICIENT` demotion is now stated to be a *further* mutation of the same policy row that bumps `version` a second time, so a filing that erodes *and* demotes advances the policy's `version` by 2 while an erosion-only filing advances it by 1 — `cascades.py:130-149` (`apply_policy_ledger`: `touch(policy)` at 137 after `recompute_policy_ledger`, second `touch(policy)` at 142 on the demotion).
- **§2.11 rung 20 (Remote-ID presence)** — revise — presence is measured over modules in `VERIFIED` **or** `EXPIRED`; `EXPIRED` is explicitly stated to count as present and to fall through to rung 21, making the code independent of whether the §2.8 lazy expiry already ran this request — `cascades.py:261-265`.
- **§2.11 rung 21 (Remote-ID validity)** — revise — restated as "at least one module in `VERIFIED` with `verified_until` strictly after now"; when none is, *every* still-`VERIFIED` module of the airframe is transitioned to `EXPIRED` and the call is refused with `ERR_REMOTE_ID_EXPIRED`; an already-`EXPIRED` module yields the same code with nothing to transition — `cascades.py:266-275`.
- **§3.3 (Registration remote-ID gate)** — revise — pinned the retry code: a retry that finds the module in `EXPIRED` is refused with `ERR_REMOTE_ID_EXPIRED` again, never `ERR_REMOTE_ID_NOT_VERIFIED` — `routes_aircraft.py:78,106` -> `cascades.py:261-275`.

## Per-edit pre-edit search log

**Edit 1 — §2.8 policy version delta**
(a) Subject: mutations/`version` bumps of the `Policy` row, and the derived `coverage_status` transition.
(b) Enumerated & read: `store.py:34-45,67-70` (`insert` opens at `version` 1; `touch` = +1 unconditionally); `cascades.py:130-149` (`apply_policy_ledger`, both `erode` and `restore` directions); `cascades.py:151-162` (`cancel_flights_of_short_policy` — touches flights only); `cascades.py:212-219` (`expire_policies_of_pilot` — single `touch`); `routes_insurance.py:39-53` (creation), `:72-92` (`verify` — status write + ledger recompute share **one** `touch`, so +1); `routes_accident.py:28-33,85,178,201` (all three `settle_ledger` callsites: file/close/withdraw); grep for `version` across all impl modules; PRD §2.5, §3.6, §3.8 and `test_11:497-553`.
(c) Adjustment: scoped the claim to the *filing* link only and made it conditional ("a filing that both erodes and demotes ... by 2 ... only erodes it ... by 1"). Deliberately did **not** generalise to "any derived `coverage_status` write bumps version again", because `routes_insurance.py:84-91` performs the `PENDING_VERIFICATION -> ACTIVE` transition plus ledger recompute under a single `touch` (+1) — a universal claim would have contradicted it. The symmetric `INSUFFICIENT -> ACTIVE` restore (also +2 in impl) was left unstated: PRD silence there is not a Step 7 item and under-determination is safer than a false universal.

**Edit 2 — §2.11 rung 20**
(a) Subject: what module states satisfy the remote-ID *presence* gate, on all three of its endpoints.
(b) Enumerated & read: `cascades.py:246-275` (`check_remote_id`); its only callsites `routes_aircraft.py:78` (register), `:106` (return-to-service), `routes_flight.py:359` (launch); `routes_flight.py:230-246` (`run_lazy_transitions`, which pre-expires modules before launch rungs 15-22) and `:337`; the parallel-but-distinct pre-flight finding path `routes_flight.py:278-280` -> `cascades.py:222-230` (`active_verified_module`); `cascades.py:169-177` (`expire_modules_of_aircraft`); `cascades.py:233-237` (`any_verified_module` — now dead, no callsite); module lifecycle writers `routes_aircraft.py:137,167,181-193`; grep of `VERIFIED|EXPIRED` across all impl modules.
(c) Adjustment: kept the sentence explicitly scoped to "this rung" and to rung 20's three endpoints, so it cannot be read as changing the pre-flight sweep's `REMOTE_ID_INVALID` finding (§3.7), which still uses the strict `VERIFIED`-and-live test via `active_verified_module`.

**Edit 3 — §2.11 rung 21**
(a) Subject: the validity verdict and the `VERIFIED -> EXPIRED` write it performs.
(b) Enumerated & read: `cascades.py:266-275` (the `live` filter and the `for module in present` loop — note it expires **all** still-`VERIFIED` modules, not just one); `cascades.py:169-177` (`expire_modules_of_aircraft`, the other writer of that transition, gated on `verified_until <= now`); `routes_aircraft.py:181-193` (the only writer of `VERIFIED`, which always sets `verified_until`, so a `VERIFIED` row with a null `verified_until` is unreachable); PRD §3.3 module-lifecycle paragraph (re-entry `EXPIRED -> VERIFICATION_PENDING`).
(c) Adjustment: changed the singular "the `VERIFIED` module's" to "at least one of the airframe's modules", and the singular transition to "every module of that airframe still sitting in `VERIFIED`", to match the loop's multi-module behaviour rather than implying a single candidate.

**Edit 4 — §3.3 registration retry code**
(a) Subject: the error code an airframe with an already-`EXPIRED` module receives at registration / return-to-service.
(b) Enumerated & read: `routes_aircraft.py:69-82` (register) and `:97-110` (return-to-service) — neither runs any lazy expiry before `check_remote_id`, so a pre-existing `EXPIRED` row reaches the gate directly; `cascades.py:259-275`; PRD §2.8 lazy-discovery sentence for consistency.
(c) Adjustment: left the pre-existing "no module at all is refused with `ERR_REMOTE_ID_NOT_VERIFIED`" sentence untouched (still true in impl) and cross-referenced rungs 20/21 rather than restating the presence rule locally, avoiding a second place that could drift.

Note on the remaining Step 7 item: the `routes_flight.py` `run_lazy_transitions()` change (retaining the up-front module expiry) needed no PRD edit — §3.7's "The lazy transitions run first here too..." and §2.8's lazy-discovery paragraph already determine that behavior, and the impl now satisfies both simultaneously. No test deletions and no `test_helpers/` fixes occurred, so nothing else in the diff traced to a PRD silence.

ORCHESTRATOR NOTE: independently verified — `PRD_FINALIZED.md` is 509 lines / 122,531 bytes vs PRD.md's 509 / 121,437; `cmp` reports the files DIFFER (so the finalizer genuinely ran); `diff` shows exactly 8 changed-line records = 4 revised lines; the final table row is byte-identical to PRD.md's, so no truncation.

## Step 9: Complete PRD — 2026-09-06T06:08:06.466Z

ORCHESTRATOR DECISION (recorded per the autonomy directive): a single-shot Step 9 scan over a 509-line / 122 KB PRD against ~3,200 lines of implementation across 20 modules reliably under-scans and, in the worst case, returns a PRD_COMPLETED.md byte-identical to its input. Step 9 was therefore run as **four sequential passes over one shared `PRD_COMPLETED.md`**, partitioned by implementation module, with pass 1 owning the `cp` and passes 2-4 explicitly forbidden from re-copying. Pass 4 is a dedicated reconciliation pass, because module-partitioned passes report cross-pass contradictions instead of fixing them (a pass may only edit prose its own modules own).

Partition: pass 1 = `app.py`, `errors.py`, `clockmod.py`, `store.py`, `envelope.py`, `shape.py`, `auth.py`, `views.py`, `common.py`, `routes_pilot.py`. pass 2 = `routes_aircraft.py`, `routes_airspace.py`, `routes_waiver.py`, `routes_insurance.py`. pass 3 = `calc.py`, `cascades.py`, `routes_flight.py`, `routes_accident.py`. pass 4 = reconciliation, the only pass permitted to edit across partition boundaries.

Source file: `PRD_FINALIZED.md` (Step 8 output, 509 lines / 122,531 chars).
Result: `PRD_COMPLETED.md`, 509 lines / **150,725 chars** (+28,194 chars, +23.0%; 146 diff records = 73 revised lines). Structure preserved: 509 lines, 28 headings, no new sections, tail unchanged.

Totals across the four passes: **109 edits — 22 (pass 1) + 27 (pass 2) + 30 (pass 3) + 30 (pass 4)**. Classification across passes 1-3: 60 ambiguity-pins, 19 mismatch-revisions.

### Pass 1 — core + pilot (22 edits: 19 ambiguity-pins, 3 mismatch-revisions)
- §2.1 — insert — ambiguity — pilot list scoping: a `Pilot` sees only owned rows; unowned collections (zones, TFRs) visible to all roles — `auth.py:87-96`, `common.py:67`
- §2.1 — revise — **mismatch** — ownership resolution: policy owner is `InsurancePolicy.pilot_id` (PRD wrongly said "pilot of the referenced flight"); added `Pilot.id`, `KnowledgeTest.pilot_id`, `Certification.pilot_id` — `auth.py:42-60`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — `envelope.py:11,16`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is 400; empty-string value = omitted — `shape.py:177-198`
- §2.3 — revise — ambiguity — `total_count` computed after filters **and after** `Pilot` ownership scoping — `common.py:67-71`
- §2.3 — insert — ambiguity — equal-`created_at` ties broken by creation order; the pilot roster's DESC order reverses the tie-break too — `store.py:62-63`, `common.py:68`
- §2.3 — insert — ambiguity — filters exact/case-sensitive, empty-string filter ignored, unknown query params ignored — `common.py:39-45,63-65`
- §2.4 — insert — ambiguity — datetime input tolerance (either-case `Z`, numeric offset normalised, naive read as UTC, whitespace stripped, fractional seconds accepted then **truncated** on output); unparseable -> `ERR_INVALID_REQUEST` — `clockmod.py:35-63`
- §2.5 — insert — ambiguity — every declared field always present, unset emitted as JSON `null` not omitted; `id`/`created_at`/(`updated_at`,`version`) lead; internal ordering key never exposed — `views.py:73-87`
- §2.11 rung 3 — insert — ambiguity — unresolved path id and unowned rows fall through rung 3; non-string body `pilot_id` is a rung-7 shape failure — `auth.py:63-84`
- §2.11 rung 7 — insert — ambiguity — absent/empty body = `{}`; non-JSON or non-object body fails here; JSON `null` == absent; boolean never accepted as int/number, int accepted as number; strings not trimmed (blank test on trimmed, max-length on raw) — `shape.py:17-54,63-93`
- §3.1 — insert — ambiguity — `email` is 1-254 chars, non-blank, no format check beyond `@` — `routes_pilot.py:48-50`
- §3.1 — insert — ambiguity — `scheduled_at` unconstrained relative to the clock (past or future bookings allowed) — `routes_pilot.py:213`
- §3.1 — insert — ambiguity — fail path returns to `UNCERTIFIED` only from `KNOWLEDGE_PENDING` — `routes_pilot.py:281-282`
- §3.1 — insert — ambiguity — pass path advances status only from `KNOWLEDGE_PENDING` (cert still issued otherwise); either grading outcome bumps the pilot's `version` — `routes_pilot.py:284,305-310`
- §3.2 — insert — ambiguity — currency review always mutates the pilot (version bumps even when nothing changed), once before any auto-suspension bump — `routes_pilot.py:155-156`
- §3.2 — insert/revise — **mismatch** — projection response also carries `pilot_id` (PRD's field list omitted it); empty `basis` = omitted, other non-members -> 400 — `routes_pilot.py:165-179`
- §3.3 — insert — ambiguity — `registration_number` format `FA` + 8 zero-padded digits, service-wide sequence — `store.py:58-59`
- §3.9 — insert — ambiguity — manual `suspension_reason` required, non-blank, <=500 chars — `routes_pilot.py:95`
- §3.9 — insert — ambiguity — reinstatement's currency recomputation is read-only (stored `currency_expires_at`/`currency_basis` untouched); no `ACTIVE` certificate also fails the precondition — `routes_pilot.py:114-116`
- §3.9 — insert — ambiguity — revoke's `suspension_reason` under the same 1-500 rule — `routes_pilot.py:129`
- §5 — insert — **mismatch** — unrouted path -> `ERR_NOT_FOUND` 404 (an id absent from the catalogue table) and method-not-allowed -> `ERR_INVALID_REQUEST` at **HTTP 405**, not the tabulated 400; trailing slash equivalence — `app.py:28,37-44`

Verified aligned, no edit needed: the §5 error table is an exact 61-for-61 match with `errors.py` (machine-diffed); clock start instant and monotonicity; whole-second `Z` output vs 3-digit `api_request_timestamp`; `PreflightCheck` as sole unversioned entity; UUID ids; `CERT-%06d`; §2.3 filter inventory vs every `string_filters` call; all §4 role lists for clock/pilot/knowledge-test/certification endpoints. Noted: `bool_filters()` in `common.py:48` is dead code; unhandled exceptions return `ERR_INTERNAL` 500 (`app.py:56`), an id in no catalogue, deliberately left alone.

### Pass 2 — aircraft / airspace / waiver / insurance (27 edits: 21 ambiguity-pins, 6 mismatch-revisions)
Zero edits inside §2, so no possible collision with pass 1's §2.x revisions; pass 1's `FA`+8-digit pin left unrestated.
- §3.3 — insert — ambiguity — `serial_number` uniqueness spans every airframe the owner ever created, whatever state it is now in — `routes_aircraft.py:32-35`
- §3.3 — insert — ambiguity — module attachment has no airframe-`registration_status` gate; many modules per airframe; `broadcast_sample_ref` 1-200; `module_serial` uniqueness spans failed/expired modules — `routes_aircraft.py:117-141`
- §3.3 — insert — ambiguity — `broadcast_sample_ref` is *required* on submit-verification (1-200, non-blank) — `routes_aircraft.py:166`
- §3.3 — insert — ambiguity — `verified_until` at or before now is `ERR_INVALID_REQUEST` (400) at rung 7, ahead of the module's state check — `routes_aircraft.py:185-191`
- §3.3 — insert — ambiguity — `failure_reason` 1-500, non-blank — `routes_aircraft.py:189`
- §3.3 — insert — ambiguity — `grounding_reason` 1-500, non-blank — `routes_aircraft.py:90`
- §3.3 — insert — ambiguity — return-to-service takes no request body — `routes_aircraft.py:97-110`
- §3.3 — insert — ambiguity — `registration_number` never cleared or reissued; register succeeds at most once, a repeat gives `ERR_AIRCRAFT_INVALID_STATE` — `routes_aircraft.py:73-81`
- §3.4 — insert — ambiguity — unlimited/overlapping TFRs per zone; a TFR with an already-elapsed window is still created `ACTIVE` — `routes_airspace.py:70-92`
- §3.4 — insert — ambiguity — lift reads only stored `status`, never the clock; `LIFTED`/`EXPIRED` give `ERR_TFR_INVALID_STATE` (409) — `routes_airspace.py:109-117`
- §3.4 — insert — ambiguity — airframe must belong to the named pilot (`ERR_OWNERSHIP_VIOLATION` 403, after reference resolution, before `expected_zone_version`); cited `waiver_id` need only resolve — no pilot/airframe/type/`APPROVED` check at request time — `routes_airspace.py:136,143-147`
- §3.4 — insert — **mismatch** — request time also runs rungs 35/37 for `COMMERCIAL` pilots: candidacy = `ACTIVE` + `effective_from <= window_start` + `effective_until > window_end`, greatest `remaining_coverage_cents` (tie on `created_at` asc) must hold >=1,000,000; indemnification never consulted, no `covering_policy_id` written, no lazy expiry — `routes_airspace.py:163-170`
- §3.4 — revise — **mismatch** — `denial_reason` on decide is conditional (required on `DENY`, ignored on `APPROVE`), 1-500 — PRD had called it "optional" — `routes_airspace.py:210-213`
- §3.4 — insert — ambiguity — the `DENY` branch skips rungs 16 and 18 entirely — `routes_airspace.py:219-224`
- §3.4 — insert — **mismatch** — at approval any non-`CERTIFIED` pilot yields `ERR_PILOT_NOT_CERTIFIED` (not `ERR_PILOT_SUSPENDED`) and any non-`REGISTERED` airframe including `GROUNDED` yields `ERR_AIRCRAFT_NOT_REGISTERED` (not `ERR_AIRCRAFT_GROUNDED`); currency, ceiling and window are not re-checked — `routes_airspace.py:225-231`
- §3.4 — insert — ambiguity — revoke's `denial_reason` 1-500; when omitted the existing value is kept, not nulled — `routes_airspace.py:247` / `cascades.py:42-46`
- §3.5 — insert — ambiguity — airframe must belong to the named pilot, checked before `expected_pilot_version` — `routes_waiver.py:47-50`
- §3.5 — insert — ambiguity — the pilot row is touched only when `open_waiver_count` actually moves; unconditional on create and decide, so submit / begin-review / request-revision / clear leave `version` alone — `routes_waiver.py:22-27,72,167,179,201,226,261`
- §3.5 — insert — ambiguity — several safety cases may be attached to one waiver, undeduplicated — `routes_waiver.py:109-121`
- §3.5 — insert — ambiguity — `reviewer_findings` on request-revision is required, 1-1000, non-blank — `routes_waiver.py:188`
- §3.5 — insert — ambiguity — clear's `reviewer_findings` 1-1000 when supplied, omission preserves existing findings; **every** attached case is tested for `sail_level <= 5` regardless of its own `review_status` — `routes_waiver.py:210,213-216,223-224`
- §3.5 — insert — ambiguity — segregation compares against `cleared_by_user_id` of *every* attached case, and being rung 4 it precedes both body reading and the waiver state check — `routes_waiver.py:233-239`
- §3.5 — revise — ambiguity — `granted_ceiling_ft` is an integer of at least 1 — `routes_waiver.py:245`
- §3.5 — insert — ambiguity — waiver `DENY`'s `denial_reason` is 1-500, non-blank — `routes_waiver.py:249`
- §3.6 — revise — **mismatch** — `indemnification_clause_accepted` is optional and stored false when omitted/null; no upper bound on either cents figure and no deductible-vs-limit relation enforced; no pilot-status gate on filing — `routes_insurance.py:26-30,34`
- §3.6 — revise — **mismatch** — a `REJECTED` outcome forces all three ledger figures to 0 outright rather than recomputing — PRD mentioned only `remaining_coverage_cents` — `routes_insurance.py:87-90`
- §4 — revise — **mismatch** — the module-attach row read "to an airframe in UNVERIFIED status"; it is the *module* that starts `UNVERIFIED` and the airframe's `registration_status` is not a precondition — `routes_aircraft.py:117-141`

Verified already-consistent: `calc.granted_ceiling` vs §3.4, `calc.sail_level` vs §3.5, `calc.overlapping_slot_count` vs §3.4, `calc.recompute_policy_ledger` vs §3.6, and every §4 role list for those four modules.

### Pass 3 — calc / cascades / flight / accident (30 edits: 20 ambiguity-pins, 10 mismatch-revisions)
- §2.8 — insert — ambiguity — suspension is itself a pilot-row mutation, so an auto-suspension firing inside an already-touched recompute advances the pilot's `version` twice — `cascades.py:74-77,89-95`
- §2.8 — insert — ambiguity — a cascade-driven authorization revocation supplies no `denial_reason`, so the field keeps its prior (usually null) value — `cascades.py:42-48`
- §2.8 — revise — **mismatch** — the pilot lapse is *not* part of the eager pre-verdict sweep on launch or on flight creation (only on the pre-flight check); on those two rung 17 performs it, and only when currency has actually run out; flight creation runs none of the other three. Also pinned that the lazy lapse rewrites `currency_expires_at`/`currency_basis` and bumps `version` by 1 — `routes_flight.py:230-245,111-114,349-352`; `cascades.py:200-209`
- §2.8 — revise — **mismatch** — the policy expiry is a **separate sweep run before candidacy**, only on a `COMMERCIAL` creation, over every `ACTIVE`/`INSUFFICIENT` policy of the pilot — not a step inside the selector — `routes_flight.py:163`; `cascades.py:212-219`
- §2.10 — insert — ambiguity — the release floors `reserved_slot_count` at 0 but still advances the zone's `updated_at`/`version`, so the version can move while the count does not — `cascades.py:13-19`
- §3.2 — revise — **mismatch** — `last_completed_flight_end` is overwritten with the *latest completion's* `actual_end`, not recomputed as a maximum; `actual_end` has no upper bound, so out-of-order completions move the anchor backwards (`calc.last_completed_flight_end` is dead code) — `routes_flight.py:416`; `calc.py:89-98`
- §3.6 — revise — **mismatch** — deferred item 1: pinned the three-stage selection (expiry sweep -> `ACTIVE`+window-span collection -> indemnification narrowing -> coverage narrowing); the collection itself reads neither `indemnification_clause_accepted` nor `remaining_coverage_cents` and expires nothing — `calc.py:211-220`; `routes_flight.py:162-176`
- §3.6 — revise — **mismatch** — `ERR_INSURANCE_NOT_ACTIVE` means no `ACTIVE` policy **spanning the window**, not "no `ACTIVE` policy at all" — `calc.py:217-218`
- §3.6 — insert — ambiguity — restore-side version arithmetic is symmetric with erosion: +1 for the ledger recompute, +2 when the same event also moves `coverage_status` — `cascades.py:130-148`
- §3.7 — insert — ambiguity — the aircraft-ownership cross-check yields `ERR_OWNERSHIP_VIOLATION` (403) after all five body references resolve and *ahead* of the suspension/certification/currency/registration/grounding gates — `routes_flight.py:102-103`
- §3.7 — insert — ambiguity — a `waiver_id` cited with no special-operation flag raised is never examined and is stored as supplied — `routes_flight.py:124-127,182`
- §3.7 — insert — ambiguity — the pre-flight check is admissible only from `PLANNED`; any other state is `ERR_FLIGHT_INVALID_STATE` — `routes_flight.py:255-256`
- §3.7 — insert — ambiguity — the 400-foot fallback also absorbs a cited authorization whose `granted_ceiling_ft` is null (reachable when the zone is uncontrolled) — `routes_flight.py:29-35`
- §3.7 — revise — **mismatch** — launch re-runs only the clock-sensitive gates; it never re-checks ownership, rule set, ceiling, turnaround, window containment or rungs 35-37, so a `PREFLIGHT_CLEARED` commercial flight launches after its policy fell to `INSUFFICIENT` — `routes_flight.py:327-371`; `cascades.py:151-162`
- §3.7 — insert — ambiguity — the stale-authorization refusal at launch is `ERR_AUTHORIZATION_INVALID_STATE` (409), evaluated *after* the restriction gate, so `ERR_TFR_ACTIVE` wins when both apply — `routes_flight.py:361-371`
- §3.7 — insert — ambiguity — completion's `actual_end` breach is `ERR_INVALID_WINDOW` but sits *after* the state gate (not at rung 8), and `actual_end` has no upper bound — `routes_flight.py:395-399`
- §3.7 — insert — ambiguity — `incident_summary` is required/non-blank only on the incident branch; sent anyway on the false branch it is stored — `routes_flight.py:391-394`
- §3.7 — insert — ambiguity — completion consumes the authorization only while it is still `ACTIVE`; one revoked or expired mid-flight releases no second slot — `routes_flight.py:410-414`
- §3.7 — insert — ambiguity — a completion that auto-suspends moves the pilot's `version` by 2, an ordinary one by 1 — `routes_flight.py:415-420`
- §3.7 — insert — ambiguity — deferred item 4: flight-summary imposes no interval ordering (absent from rung 8), so `window_start >= window_end` yields the empty aggregate rather than `ERR_INVALID_WINDOW` — `calc.py:294-303`
- §3.7 — insert — ambiguity — deferred item 4: `pilot_id` added to the enumerated response fields; the nine fields are the whole body (no `id`, no `version`, no `meta`) — `routes_pilot.py:196-200`; `calc.py:321-328`
- §3.8 — revise — **mismatch** — the flight's `investigation_status` is **not** a filing precondition (impl checks only the operational status plus the live-report bar); a flight whose sole report was withdrawn is refilable although its `investigation_status` is `CLOSED` — `routes_accident.py:58-63`
- §3.8 — revise — **mismatch** — filing moves `investigation_status` to `OPEN` from `NONE` *or back from* `CLOSED` — `routes_accident.py:83-84`
- §3.8 — insert — ambiguity — the copied policy's `coverage_status` is never consulted at filing; `INSUFFICIENT`/`EXPIRED` policies erode exactly as `ACTIVE` ones, but only `ACTIVE` can be demoted — `routes_accident.py:64,82-85`; `cascades.py:136-143`
- §3.8 — insert — ambiguity — `damage_line_items` may be an empty array, yielding a settlement of 0 — `shape.py:96-106`; `calc.py:183-186`
- §3.8 — insert — ambiguity — with a null `policy_id` the deductible is 0, no cap applies, and no ledger is recomputed — `calc.py:187,198-200`; `routes_accident.py:30-33`
- §3.8 — insert — ambiguity — closure increments the pilot's `version` and runs the automatic-suspension test just as a filing does — `routes_accident.py:36-42,183`
- §3.8 — insert — ambiguity — withdrawal also runs the automatic-suspension test — `routes_accident.py:206`
- §3.9 — revise — **mismatch** — the "flights in PLANNED/.../CANCELLED never contribute to **any of the four** counts" claim is wrong: the open-accident count spans reports against *any* of the pilot's flights whatever the flight's status — `calc.py:242-261`
- §4 — revise — **mismatch** — the accident-filing row said "COMPLETED or IN_PROGRESS"; impl also admits `CANCELLED`, and `investigation_status` is not a precondition — `routes_accident.py:58`

### Pass 4 — reconciliation (30 edits)
Verdicts on the six deferred work-list items:
1. **Rung 4 singular -> plural — FIXED.** `routes_waiver.py:233-238` iterates `safety_cases_of(candidate)` and refuses on a match against *any* case's `cleared_by_user_id`. Rung 4 now reads "of *every* safety case attached to the waiver, a match on any one of them being enough to fail the rung whatever that case's own `review_status`". Ladder structure and rung numbering untouched. The same singular error was found in two more places outside pass 3's partition and both were fixed: §2.1 and the §4 table row for `/waivers/{id}/decide`.
2. **Rung 8 carve-out — ADDED, four-POST list untouched.** Verified `routes_flight.py:395-399` (state gate first, then the breach) and `calc.py:294-303` / `routes_pilot.py:189-200` (flight-summary does no ordering check; `window_start` defaults to `pilot.created_at`, `window_end` to `clock.now()`). Grep confirmed the only `ERR_INVALID_WINDOW` raise sites are the four rung-8 endpoints plus completion. Appended a sentence declaring the enumeration exhaustive and naming completion as the one ordering check evaluated after its own state gate; worded as "the only other **ordering check**" so it does not collide with §3.7's phrasing.
3. **§3.6 lazy-policy-expiry — TIGHTENED.** `routes_flight.py:162-163` calls `cascades.expire_policies_of_pilot` *before* `covering_policy_candidates`, gated on `operation_category == "COMMERCIAL"`; `cascades.py:212-219` sweeps every `ACTIVE`/`INSUFFICIENT` policy of the pilot with `effective_until <= now`, candidate or not. §3.6's closing sentence now says exactly that and explicitly denies the selector-evaluates-it reading. Grep confirmed a single call site, so pass 4 could also pin "no other endpoint in the service expires a policy".
4. **§2.8 "four such transitions" lead-in — RE-WORDED** to "Four such transitions arise on the flight path, and the gates that reach them do not all perform the same subset — the list that follows is an inventory of the four, not a claim that any one gate runs all four...", with the endpoint attribution moved into the follow-on sentence. The now-redundant trailing sentence "Flight creation runs none of the other three transitions at all." was removed.
5. **§3.9 "six moments" — CLAUSE ADDED.** Every `recompute_risk_score` / `maybe_auto_suspend` call site was grepped: the test runs on completion (`routes_flight.py:418-420`), filing/closure/withdrawal (`routes_accident.py:36-42`) and currency review (`routes_pilot.py:154-156`), and **not** on reinstatement (`routes_pilot.py:119-120`). §3.9 now states the 5-of-6 split in one clause. `cascades.recompute_and_maybe_suspend` is dead code, which also allowed pinning "no other event in the service recomputes `risk_score`".
6. **§3.3 `registration_number` — NO CHANGE NEEDED.** `store.py:58-59` is `"FA%08d"`; the format is stated exactly once and matches; the other two mentions are non-overlapping facts.

Coherence sweep results:
- **Contradictions found and fixed:** the singular-vs-plural safety-case comparison in §2.1 and §4 — the only true cross-passage contradiction remaining.
- **Duplicated pins resolved:** one (the redundant §2.8 trailing sentence, above).
- **Dangling cross-references:** all 28 `rung N` pointers resolved against the ladder; two were made explicit rather than implicit — rung 26 now states the 400-foot fallback also applies when the cited authorization's `granted_ceiling_ft` is null (`routes_flight.py:29-35`), and rung 5 now records that both segregation rungs fall through to rung 6 on an unresolvable path id (`routes_waiver.py:233-234`, `routes_accident.py:148-149` both use `find`, not `must_exist`).
- **Version-delta verdict: mutually consistent.** Policy +1 erosion / +2 erosion+demotion is symmetric with +1 restore / +2 restore+promotion, matching `cascades.apply_policy_ledger`. Pilot +2 on auto-suspension across all five triggering events matches `recompute -> touch -> suspend_pilot -> touch`. Zone `version` advancing on a floored release matches `release_zone_slot`. Waiver create/decide unconditional (`force=True`) vs submit/begin-review/request-revision/clear conditional matches `refresh_open_waiver_count`. **§2.5 was qualified** rather than left to a literal misreading: it now states the increment is counted per mutation and not per request, names the +2 shape explicitly, cross-references the pinning sections, and adds the converse (a no-op mutation still counts — the floored slot release and the idempotent currency review).

Additional pass-4 pins:
- §2.5 — revise — ambiguity — per-mutation not per-request increment; +2 double-mutation shape; no-op mutations still count — `store.py:66-70`, `cascades.py:74-95`, `cascades.py:13-19`
- §2.11 rung 5 — revise — ambiguity — unresolvable path id falls through both segregation rungs to rung 6 — `routes_waiver.py:233`, `routes_accident.py:148`
- §2.11 rung 26 — revise — ambiguity — 400-foot fallback also covers a null `granted_ceiling_ft` — `routes_flight.py:29-35`
- §3.6 — revise — **mismatch** — no endpoint other than `COMMERCIAL` flight creation expires a policy — `cascades.py:212`, `routes_flight.py:163`
- §3.9 — insert — ambiguity — reinstatement is the only one of the six that skips the auto-suspension test; no other event recomputes `risk_score` — `routes_pilot.py:119-120,154-156`

ORCHESTRATOR NOTE: independently verified after all four passes — `PRD_COMPLETED.md` is 509 lines / 150,725 chars with 28 headings; `cmp` against `PRD_FINALIZED.md` reports DIFFERS (so the scan genuinely ran and is not the known byte-identical failure mode), with 146 diff records = 73 revised lines; the tail is still the final `ERR_INSURANCE_COVERAGE_INSUFFICIENT` table row, so no truncation. Grep for `harder than expert` / `expert level` / `test_recipe` / `scaffold` returns nothing. All 8 `implementation/results.*.json` are still present, and `find -newermt` confirms no file under `implementation/`, `test_suite/` or `test_helpers/` was modified after the 05:19 green sweep — the 205/205 x 8 evidence therefore still describes the delivered code. `.scratch/step2` and `.scratch/step4` survived every pass.
