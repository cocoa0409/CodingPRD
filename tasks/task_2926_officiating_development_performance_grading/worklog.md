## Step 1: Create task directory — 2026-09-05T17:35:16.463165575Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2926_officiating_development_performance_grading and its workspace/ subdirectory. Index 2926 pre-assigned by the invoking pipeline (no auto-allocation scan performed, per orchestration instructions — 32 concurrent pipelines on this host).


## Step 2: Generate scaffold — 2026-09-05T18:58:42.555Z

All three scaffold artifacts are complete and the linter is clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2926_officiating_development_performance_grading/`)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2914 | 142,896 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1769 | 97,904 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3228 | 182,374 |

All three `yaml.safe_load` cleanly. `SCAFFOLD.yaml` top-level keys are exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — it contains **neither** `scaffold_difficulty_design` **nor** `scaffold_corner_design`. Each design file has its single required top-level key. Pre-existing `worklog.md` (4 lines) and `workspace/` were never touched.

**SCAFFOLD.yaml counts**: 14 entities, 10 state machines, 2 concurrency rules, 17 calculations, 28 validation rules, 57 endpoints, 45 error codes, 8 roles. Profile: `api_prefix "/"`, flat topology, parallel state-machine shape, `segregation_of_duties` role model, `immediate` consistency, complexity layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`.

**Design indices**: difficulty = 9 rule_ids / 23 instances (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 3). Corner = 9 sections / 72 instances (entities 10, state_machines 15, calculations 10, validations 16, endpoints 4, errors 3, rbac 6, cross_cutting_layers 7, consistency_model 1), of which 59 carry a full `test_recipe` and 13 are `excluded_because` stubs; every cited `difficulty_instance` resolves, and instance names are unique across the union of both files.

**Lint verdict (verbatim)**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2926_officiating_development_performance_grading/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2926_officiating_development_performance_grading/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2926_officiating_development_performance_grading/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     14
  §1.8 instances scanned:     23
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  1302

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Final fix this round: the first lint pass flagged two unresolvable captures in the difficulty file's `crew_counters_restored_after_confirm_then_withdraw` instance — it read `open_assignment_count` off `GET /games/{id}`, but that field is declared on `Official`, not `Game`. Re-sourced both the baseline and the post-withdrawal reads to `GET /officials/{id}` (adding a companion read for the untouched referee so the assert proves only the withdrawn official's counter moved) and corrected the prose and asserts to match.

**Orchestrator note (post-subagent):** the difficulty directive line "Generate task harder than expert level!" had leaked into SCAFFOLD.yaml's `scenario:` block (known generator failure mode — it would reach PRD.md via the doc generator). Stripped that one line from the scenario key; re-validated `yaml.safe_load` OK and confirmed 0 remaining matches. The two design indices did not contain the line.

## Step 3: Copy shared files — 2026-09-05T18:58:42.588Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-05T19:12:19.851Z

The PRD is complete and fully verified.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2926_officiating_development_performance_grading/workspace/PRD.md` — **483 lines / 92,896 characters**

Built incrementally per the operational constraints: 1 `Write` (24,945 chars) followed by 7 quoted-heredoc `cat >>` appends (each under 16k), then three surgical `Edit` calls for precision. The file was never overwritten after the initial `Write`. Scratch work lived in `/tmp/task_2926_doc/`. Nothing outside `workspace/PRD.md` was touched — no `worklog.md`, no `SCAFFOLD*.yaml`. Neither withheld design index was opened, and no sibling task directory was read.

## Section list

§1 Introduction · §2 Global Specifications (2.1 Departmental Roles and Caller Identity, 2.2 API Response Structure, 2.3 Pagination and List Ordering, 2.4 The Logical Clock, 2.5 The Season Program as the Departmental Write Gate, 2.6 Common Resource Properties, 2.7 Numeric Precision and Rounding, 2.8 Optimistic Concurrency Control on Parent Versions, 2.9 Rejection Precedence, 2.10 Derived Fields, Cascades and Version Discipline, 2.11 Identifier Resolution and Sub-Resource Paths) · §3 Business Logic & Workflows (3.1 Configuring a Season and the Governing Thresholds, 3.2 Recruiting Officials, Clinics and Preseason Clearance, 3.3 The Advancement Pipeline and the Committee Return Loop, 3.4 Scheduling Games and Building Crews, 3.5 Game Day: Kickoff, the Replay Center, and the End of Play, 3.6 Grading Plays and the Season Accuracy Record, 3.7 Appeals: Filing, Adjudication, and the Accuracy-Recovery Cascade, 3.8 Discipline, Suspension Cascades and Remediation, 3.9 Closing Out: Finalization, Public Accountability and Retention) · §4 Endpoint Definitions · §5 Error Code Catalogue

11 §2 subsections and 9 §3 subsections, all with domain-derived titles.

## Tail completeness

Confirmed a real section boundary. The last line is a complete `§5` table row — `| ERR_GAMES_IN_PROGRESS | 409 Conflict |` — not mid-sentence, mid-table, or mid-list. No audit footer or contract report leaked into the document.

## Hard Contract reports

```
Contract 1 — Field-Name Coverage
- entities[].fields:            97 required,  97 present, 0 missing
- endpoints[].request_body:     62 required,  62 present, 0 missing
- endpoints[].query_params:     30 required,  30 present, 0 missing
Status: PASS
```

```
Contract 2 — Rule Coverage
- state machines:        10 machines, all transitions in prose, 0 missing
- calculations:          17 required, 17 present, 0 missing
- validations:           28 required, 28 present, 0 missing (explicit priority order in §2.9)
- concurrency_rules:      2 required,  2 present, 0 missing (endpoint + occ_field + error_id + 412 each)
- error_ids:             45 declared, 45 present, 0 missing
- roles:                  8 declared,  8 present, 0 missing
- enum / state values:   all present, 0 missing
Status: PASS
```

```
Contract 3 — §3 Path Purity
- backtick tokens scanned in §3:   925
- tokens starting with `/`:           0
- bare HTTP-method tokens:            0
- method+path combined tokens:        0
Status: PASS
```

## Other guards

§2.2 diffs **byte-identical** against `section-2.2-response-structure.md`. §4 table is uniformly 4 columns with 57 endpoint rows; §5 table is 2 columns with 45 rows. No fuzzy words and no operator syntax anywhere — all comparisons and accumulations are stated in prose.

One detail worth flagging for the implementer's benefit: §2.10 spells out the four derived counters explicitly (`confirmed_crew_count`, `open_assignment_count`, `active_review_count`, `eligible_official_count`), and §3.9 states the `retention_score` penalty-band reading in non-circular form, calling out the wrong circular reading (raw 81.50 → band 5.00 → 76.50 `DEVELOP`, not 72.50 `RELEASE`) since that is the easiest place to silently diverge.

**Orchestrator verification (anti-truncation guard):** independently confirmed 483 lines / 92,896 chars; `grep '^#'` shows all planned sections present through §5; tail is a complete markdown table row. Cross-checked against SCAFFOLD.yaml programmatically: all 57 endpoint paths and all 45 error ids appear verbatim in PRD.md (0 missing each). No difficulty-directive leak in PRD.md (0 matches for "harder than expert"). PRD accepted without regeneration.

## Step 6: Generate implementation — 2026-09-05T19:42:29.626Z

Implementation complete, smoke-tested end to end, all servers I started killed by their own PID only.

## Files written (`workspace/implementation/`, 3117 lines total)

| file | lines | role |
|---|---|---|
`app.py` | 60 | `create_app()`, 11 blueprints, `strict_slashes=False`, envelope handlers for `ApiError` / `HTTPException` / bare `Exception`, `app.run(host=0.0.0.0, port=$PORT, threaded=True, debug=False, use_reloader=False)`
`db.py` | 120 | in-memory `Store` (14 dicts + logical clock + insertion seq), `CLOCK_START=2026-08-01T00:00:00.000Z`, `iso()` 3-digit ms, `base_row/touch/order_rows/serialize`
`errors.py` | 127 | `ApiError` + all 45 error-ID constants + status map
`response.py` | 69 | `meta` with `req_…` id and clock timestamp, object/list/empty/error envelopes, `has_more`
`middleware.py` | 71 | 8 roles, `@endpoint(roles)` doing 401-then-403
`validation.py` | 268 | `q2()` ROUND_HALF_UP, typed field readers, score/team-code/instant/enum/int parsers, strict `limit`/`offset`
`services/calc.py` | 242 | every pure number: error points, accuracy index, crew contribution/strength, evaluation composite, availability, retention bands, window-overlap predicates
`services/derive.py` | 426 | 404 lookups, program-OPEN gate, crew posture, PROVISIONAL/FINAL and PROJECTED/REALIZED recomputes, clearance/deficiency, discipline blocking set, eligibility re-derivation, `void_assignments` cascade
`routes/*.py` | 1726 | clock 22, season_programs 138, officials 183, applications 234, games 178, assignments 207, play_grades 110, appeals 217, replay 162, pool_reports 99, discipline 176
`start.sh` (7, +x), `requirements.txt` (1) | | `exec python3 app.py`, foreground, installs flask only if missing

## Endpoint parity
`app.url_map` enumerates exactly **57** non-static method/rule pairs = PRD §4's 57 rows. (`/season-records` lives in `routes/officials.py`, hence 11 blueprints for 57 endpoints.)

## Structure
- **Precedence** is encoded as call order inside each handler, matching PRD §2.9's 28 steps: decorator (401/403) → `v.*` shape readers (400) → `derive.get_*` in path-then-body declared order (404) → ownership/segregation (403) → `require_program_open` (409) → entity state (409) → `expected_*_version` (412) → business rules.
- **Calculations** are isolated in `services/calc.py` as pure `Decimal` functions, never floats: round-then-sum for error points, double rounding for crew strength (per-contribution then index over `crew_size_required`), composite rounded before averaging, retention penalty band selected from the *pre-penalty* raw composite and clamped at 0.00.
- **State machines** are explicit legal-from tuples at each transition; PlayGrade's two dimensions (`grade_status`, `appeal_state`) are independent with the single cross-guard on finalize/publish. Cascades (mark-played, finalize, suspension/escalation/lock-postseason voids) iterate `created_at` ASC and bump `updated_at`+`version` once per touched row.
- **Storage** is dicts keyed by UUID, empty on every boot, zero seeding.

## Smoke test
Two scripts under `/tmp/task_2926_impl/`, run against `bash start.sh` on random high ports (last clean run: **27855**, PID 754329, killed by that PID; earlier runs 31111, 23921, 20279, 28835 — never a pattern kill; 0 tracebacks in any server log).
- `smoke.py` — **81 assertions, 0 failures**: envelope/auth/pagination, program lifecycle, officials + training clearance, crew proposal with OCC 412, half-open window conflict *and* exact-adjacency acceptance, projected 6.24 → staffed 8.64 crew strength, kickoff/LOCKED, replay capacity at a touching window + decision at exactly 120 s, mark-played, error points 2.63 / 1.20, PROVISIONAL 47.40, appeal ownership + segregation + OVERTURNED recovery to 100.00, finalize → REALIZED, pool report publish, suspension cascade with void, lock-postseason (referee 85.00 DEVELOP retained, umpire 54.18 RELEASE released), post-lock `ERR_SEASON_NOT_OPEN`.
- `smoke2.py` — **60 assertions, 0 failures**: the advancement path (screen → 3 evaluations 71.50/78.10/90.00 → average 74.80 refused, 79.87 accepted → return-for-tape loop → APPROVED raising tier), assignment withdraw + re-propose, appeal withdraw with credit refund, finalize with a pending appeal leaving the grade at POSTED, remediation cycle loop to the 409 cap and CLEARED restoring ACTIVE.
- Re-running `smoke.py` on a store that already held `smoke2`'s data produced only the expected extra rows in `GET /officials`, confirming per-program isolation; every boot started from an empty store (a duplicate `season_year` would otherwise have 400'd).

## Ambiguities and the interpretation chosen
1. **Duplicate `season_year` / duplicate `station_code`** — no dedicated code exists, so `ERR_INVALID_REQUEST` (400).
2. **`score` on training records** — required for `PHYSICAL_TEST`/`RULES_EXAM`, rejected for `RULES_CLINIC` (clinics "carry none").
3. **No ownership check on `POST /advancement-applications`** — §2.9 step 5 names only the two appeal endpoints, so an Official may file for another `official_id`.
4. **Accuracy-recovery cascade** fires only on appeal outcome `OVERTURNED`, not on `MODIFIED`.
5. **Discipline open** applies its official-status transition only from the declared from-states and raises nothing otherwise (e.g. suspending an already-SUSPENDED official still supersedes, voids and bumps).
6. **`confirmed_crew_count` after mark-played** — recomputed from §2.10's invariant (all assignments become COMPLETED, so it reads 0) even though §3.5's side-effect list omits it.
7. **Version discipline** — one bump per row per request; the void cascade bumps each affected game once; named recomputes bump unconditionally, while an eligibility-only refresh bumps the season record only when the derived flag actually moves.
8. **Training-record filing** bumps the official only when `status` or `preseason_cleared` changes.
9. **lock-postseason RELEASE voids** apply no game-status filter beyond PROPOSED/CONFIRMED and do not re-derive `postseason_eligible` afterwards.
10. **Field evaluations** enforce no application state gate (no error is declared for one).
11. **Unknown body fields ignored**; enum/boolean query filters are lenient (no match rather than 400) while `limit`/`offset` are strict.
12. **The MODIFIED "must differ" 400** sits after existence and before segregation of duties.
13. **CLEARED / ESCALATED** re-derive `postseason_eligible` even when the official's status does not move.
14. **`GET /season-records/{id}`** has no dedicated 404 code, so it returns `ERR_OFFICIAL_NOT_FOUND`.
15. **Unmatched path/method** returns the standard envelope with `ERR_INVALID_REQUEST` at the original HTTP status (404/405).

## Step 5: Generate unit tests — 2026-09-05T20:31:31.568Z

(Appended after the Step 6 entry because Steps 5 and 6 ran concurrently and Step 6 returned first; worklog is append-only so chronological-by-completion ordering is preserved.)

Stage 1 and Stage 2 are complete for task 2926. Nothing was written into `workspace/`; `worklog.md`, `PRD.md`, `INSTRUCTION.md` and the three `SCAFFOLD*.yaml` files are untouched.

## Output location (verified)

Both directories sit at the task root `/home/ubuntu/github/CodingPRD/tasks/task_2926_officiating_development_performance_grading/`. `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`, `run_sweep.sh`, `sweep.sh` — no `test_helpers/` or `test_suite/` anywhere beneath it. All `__pycache__` from `py_compile` was removed.

## test_helpers/ (9 files, 2 992 lines)

`__init__.py` 29 · `api_client.py` 318 (57 methods) · `api_errors.py` 144 · `assertions.py` 569 · `constants.py` 189 · `factories.py` 316 · `fixtures.py` 874 · `test_users.py` 110 · `types.py` 443

## test_suite/ (conftest 78 lines + 18 test files, 6 693 lines, 165 tests)

Queue A — `test_01`–`test_09`, 57 tests (208/240/202/208/268/274/214/259/286 lines).
Queue B — `test_10` 531/15, `test_11` 701/20, `test_12` 578/13, `test_13` 1113/24, `test_14` 365/8, `test_15` 285/7, `test_16` 477/11, `test_17` 374/8, `test_18` 110/2 — 108 tests.

## Coverage audit (scripted, `/tmp/task_2926_tests/audit.py`)

- **165 tests, 165 `Design:` tags, zero tests with more or fewer than one tag.** Zero tags pointing at a stub or at a non-existent instance name.
- **Queue A (§1.8): 23/23 non-stub instances translated across 9 rule_ids. 0 skips.**
- **Queue B (§1.9): 59/59 non-stub instances translated** — entities 10/10, state_machines 12/12, calculations 6/6, validations 13/13, endpoints 4/4, errors 3/3, rbac 6/6, cross_cutting_layers 4/4, consistency_model 1/1.
- The 13 `excluded_because:` stubs were correctly left untranslated (3 state_machines, 4 calculations, 3 validations, 3 cross_cutting_layers).
- No instance was dropped on the PRD-first filter; every non-stub instance had verbatim, uniquely-deriving PRD text. Two *sub-assertions* inside otherwise-emitted instances were omitted as non-PRD-derivable: the clock setter's "response carries no entity payload", and "no nested route such as `/games/{id}/crew-assignments` exists". A third (`training_deficiency_count is 0`) was omitted because that quantity is not an exposed field.

## Verification

Every file compiles (`py_compile` over all 27 files, plus a final `pyflakes` pass showing no undefined names — only benign unused re-exports in `test_helpers/__init__.py`). No test suite was run and no server was started; no `pkill`. Scratch lived in `/tmp/task_2926_tests/`. Zero occurrences of "scaffold" in any generated prose.

Fixture-fidelity rules held throughout: decimals as JSON numbers, full three-digit ISO instants compared via `assert_instant_equals`, `validate_success`/`get_success_data`/`validate_paginated` used without double-unwrapping, blank-header cases via `headers_with_empty_user_id` (empty string, not whitespace), boolean query filters sent as the string `"true"` because `GenericApiClient` passes them to `requests` params, and all enum/threshold symbols defined once in `constants.py`. One constant was added this session (`INSTANT_MIDSEASON_CLOCK_SET`) plus three read helpers earlier (`read_review`, `read_pool_report`, `read_program`).

## Step 7: Run tests and iterate — 2026-09-05T20:52:50.228Z

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2 (one diagnostic sweep, one verification sweep).

**Tests deleted:** none. Every failing test cited a verbatim PRD rule and asserted it faithfully; all four failures were a single fixture-shape bug in the request payload, caught at STEP 2.

**Fixes applied to `test_helpers/`:** none — the bad literals lived inline in the test functions, not in the factories.

**Fixes applied to `test_suite/`** (the request-payload layer, per STEP 2c):
- `test_suite/test_02_combinatorial_formulas.py` — the `retention_scenario` fixture scheduled its spare game with `away_team_code="KC"`, a two-letter code. PRD §3.4 requires "a `home_team_code` and an `away_team_code` — each exactly three uppercase letters", so the PRD-faithful implementation correctly returned `ERR_INVALID_REQUEST`. Changed to `"KAN"`. This one fixture bug errored 3 tests on setup.
- `test_suite/test_08_temporal_resource_overlap.py` — `test_a_window_opening_exactly_on_the_previous_close_is_accepted` scheduled its adjacent game with `home_team_code="KC"` / `venue_market_code="KC"`, same two-letter violation. Changed both to `"KAN"`.

**Fixes applied to `implementation/`:** none. No implementation defect was found; the rejection the tests hit was a PRD-required shape check that must stay.

**Key finding:** all four failures were deterministic across all 8 rounds and shared one setup error naming `away_team_code` / `home_team_code` length — the classic "common upstream fixture bug masquerading as many independent defects" shape. Diagnosis was confirmed out-of-band by booting a probe server on port 39271 and replaying the `retention_scenario` chain with a three-letter code, which produced exactly the asserted values (`accuracy_index` 95.00, `availability_component` 50.00, `retention_score` 76.50, `retention_recommendation` `DEVELOP`) before the verification sweep was launched. The probe server was killed by its own pid.

**Final sweep evidence** (all rounds, 307s each):

| round | passed / total |
| --- | --- |
| results.1.json | 165 / 165 |
| results.2.json | 165 / 165 |
| results.3.json | 165 / 165 |
| results.4.json | 165 / 165 |
| results.5.json | 165 / 165 |
| results.6.json | 165 / 165 |
| results.7.json | 165 / 165 |
| results.8.json | 165 / 165 |

`failed=0 errors=0 skipped=0` in every round. `worklog.md` was not touched, and no scaffold file was read — scratch work stayed in `/tmp/task_2926_step7/`.

**Orchestrator verification:** independently parsed all 8 `results.*.json` — every one reads passed=165 total=165 failed=0 errors=0 skipped=0, all written within 1 second of each other at 20:43:4x (real concurrent sweep, not a stale artifact). Grepped all 8 `round.$i.log` for `Terminated`: none, so the sweep was not reaped. Test count is still 165, matching Step 5's output — confirming zero deletions.

**Step 8 gating decision:** Step 7 made 0 `implementation/` fixes and 0 deletions, but it did make 2 `test_suite/` fixes, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is NOT met. Step 8 will run. Both fixes were pure payload-shape bugs against a PRD rule quoted verbatim in the diff, so Step 8 is expected to find little or nothing to pin — a byte-identical PRD_FINALIZED.md would be a legitimate outcome here.

## Step 8: Finalize PRD — 2026-09-05T21:00:43.763Z

`workspace/PRD_FINALIZED.md` is written and is **byte-identical to PRD.md** (md5 `4dc9d7e7e6dfead2495971b6671c3f4d`, 483 lines each, 0.00% delta). Zero edits were warranted.

## Line counts
- PRD.md: 483 lines
- PRD_FINALIZED.md: 483 lines
- Delta: 0 lines, 0.00%

## Changes
None. Both `<step_7_diff>` items were test-side payload literals violating a shape rule PRD already states verbatim; neither reveals PRD silence or PRD/impl mismatch.

## Per-item analysis (with mandatory pre-edit search, performed even though no edit followed)

**Item 1 — `test_suite/test_02_combinatorial_formulas.py`, `retention_scenario` fixture used `away_team_code="KC"`**
- (a) Subject: the shape constraint on game team/market codes and the error class for violating it.
- (b) Impl paths enumerated and read: `implementation/routes/games.py:26-32` (`req_team_code` on `home_team_code`, `away_team_code`, `venue_market_code`, then the differ check → `ERR_INVALID_REQUEST`); `implementation/validation.py:151-164` (`req_team_code`/`opt_team_code` = `_check_str(min 3, max 3)` + `^[A-Z]{3}$` → `ERR_INVALID_REQUEST`); grepped every `team_code`/`market_code` callsite repo-wide — the only other shape-validating sites are `routes/officials.py:48` (`home_market_code`, required) and `:50` (`affiliated_team_code`, optional, default `None`); the remaining hits (`routes/assignments.py:18-90`, `routes/games.py:174`, `routes/officials.py:86`) are read-only comparisons/filters that never re-validate shape.
- Verdict: PRD §3.4 line 243 already says "a `home_team_code` and an `away_team_code` — each exactly three uppercase letters, and the two must differ" and "a `venue_market_code` of exactly three uppercase letters"; PRD §3.2 line 209 covers `home_market_code` and nullable `affiliated_team_code` identically; PRD §2.9 step 3 puts body well-formedness (`ERR_INVALID_REQUEST` 400) above identifier resolution, which matches the impl's validate-then-lookup order in `games.py`. Uniquely determined — no edit.
- (c) Wording adjustment: none (no edit committed).

**Item 2 — `test_suite/test_08_temporal_resource_overlap.py`, `test_a_window_opening_exactly_on_the_previous_close_is_accepted` used `home_team_code="KC"` / `venue_market_code="KC"`**
- (a) Subject: same three-uppercase-letter code shape, on the same `POST /games` path.
- (b) Impl paths enumerated: identical set to Item 1 (same `req_team_code` helper, same single scheduling callsite); additionally confirmed the test's actual asserted behavior — half-open occupancy adjacency — is stated verbatim in PRD §3.4 line 249 ("Exact adjacency does not conflict … while a second game whose window opens even one minute before that instant is rejected with `ERR_OFFICIAL_WINDOW_CONFLICT`"), so nothing about the assertion target is PRD-silent either.
- (c) Wording adjustment: none (no edit committed).

## Corroborating checks
- Step 7 applied **zero** `implementation/` fixes, zero deletions, and zero `test_helpers/` fixes, so there is no impl-side behavioral choice introduced by Step 7 to pin.
- The values the Step 7 probe confirmed (`accuracy_index` 95.00, `availability_component` 50.00, `retention_score` 76.50, `DEVELOP`) are the literal worked example already in PRD §3.9 line 369, including the pre-penalty band selection of 5.00 — already pinned.
- The current test files now read `KAN`/`NYJ`/`DAL`/`PHI` throughout, consistent with the described fixes.
- Per HARD SCOPE I did not scan for unrelated ambiguities; that is Step 9's work.

**Orchestrator note:** a byte-identical PRD_FINALIZED.md is the legitimate outcome for Step 8 when Step 7 made no implementation fixes — verified md5 equality myself. This does NOT license an identical Step 9 output; Step 9's full impl scan must produce a real diff, and will be run as sequential module-partitioned passes over one shared PRD_COMPLETED.md.

## Step 9: Complete PRD — 2026-09-05T21:24:57.657Z

Run as **three sequential module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 owned the `cp`; passes 2 and 3 were explicitly forbidden from re-copying it). Partition by implementation module so no two passes contend for the same prose:
- pass 1 — app.py, db.py, errors.py, middleware.py, response.py, validation.py, routes/clock.py, routes/season_programs.py, routes/officials.py
- pass 2 — routes/applications.py, routes/games.py, routes/assignments.py, services/calc.py
- pass 3 — routes/play_grades.py, routes/appeals.py, routes/replay.py, routes/pool_reports.py, routes/discipline.py, services/derive.py

Cumulative result: **483 lines, 92,896 → 105,445 chars (+12,549), 47 edits (40 ambiguity-pins, 7 mismatch-revisions)**, all in-paragraph; no new sections, no renumbering, no table-structure changes.

### Pass 1 (infrastructure + cross-cutting + first route group) — 19 ambiguity-pins, 2 mismatch-revisions, +5,578 chars

- §2.1 — revise — ambiguity — "absent or empty" narrowed to the empty string; a whitespace-only header passes authentication and is carried through unchanged — `middleware.py:50`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly twenty uppercase-alphanumeric characters — `response.py:15`
- §2.2 — revise — ambiguity — `api_request_timestamp` reads the logical clock, not wall clock — `response.py:21`
- §2.3 — insert — ambiguity — empty-string `limit`/`offset` take defaults; a non-integer value is `ERR_INVALID_REQUEST` — `validation.py:229-244`
- §2.3 — insert — ambiguity — `created_at` ties break by write order everywhere the doc says `created_at` ascending — `db.py:101`
- §2.4 — insert — ambiguity — clock endpoint returns `200 OK` with `data` = a single `current_utc` echo, not a resource — `routes/clock.py:22`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are stamped from the logical clock — `db.py:77`
- §2.4 — insert — ambiguity — serialization truncates sub-millisecond precision; parsing accepts `Z`/`z`, a numeric UTC offset (normalized), a naive value, and a date with no time component — `db.py:69`, `validation.py:179-188`
- §2.5 — revise — **mismatch** — "Four operations are deliberately outside this gate" → "Five" — `routes/*.py`
- §2.7 — insert — ambiguity — a decimal input may be a JSON number *or* a numeric string; >2 decimal places is quantized round-half-up rather than refused — `validation.py:135-148`
- §2.7 — insert — ambiguity — integer inputs must be genuine JSON integers; a boolean or fractional number is `ERR_INVALID_REQUEST` — `validation.py:108`
- §2.9 step 3 — insert — ambiguity — explicit JSON `null` counts as absent; no body / invalid JSON reads as `{}`; non-object JSON body is `ERR_INVALID_REQUEST`; non-blank text stored untrimmed, bounds measured untrimmed — `validation.py:37-46,68-73`
- §2.11 — insert — ambiguity — filters match exactly; an unrecognized/out-of-enum string filter selects no rows, an empty one is absent, an unparseable boolean filter is ignored — `validation.py:248-264`, `routes/officials.py:89`
- §3.1 — insert — ambiguity — duplicate `season_year` is `ERR_INVALID_REQUEST` (400) — `routes/season_programs.py:31`
- §3.1 — insert — ambiguity — `reviewable_categories` stored in supplied order with duplicates collapsed to first occurrence — `validation.py:206-212`
- §3.2 — insert — ambiguity — a `RULES_CLINIC` filing carrying a score is `ERR_INVALID_REQUEST`; a training record stores/returns both `score` (null for clinic) and `passed` — `routes/officials.py:103-106,121-128`
- §3.2 — insert — ambiguity — a training filing that moves neither `status` nor `preseason_cleared` does not mutate the official; the season record's `postseason_eligible` bumps only on an actual flag change — `routes/officials.py:139-142`, `services/derive.py:371`
- §3.2 — revise — **mismatch** — training deficiency count is not stored or returned anywhere and is not refreshed on filing; evaluated only when a retention score is computed — `routes/season_programs.py:115`
- §3.6 — insert — ambiguity — an unresolvable season-record id reports `ERR_OFFICIAL_NOT_FOUND` (404) — `services/derive.py:127`
- §3.9 — insert — ambiguity — the lock mutates each season record exactly once regardless of how many of the four steps move fields; a `RELEASE` void sweep is not restricted to `SCHEDULED`/`IN_PROGRESS` games; step four does not re-derive `postseason_eligible` — `routes/season_programs.py:112-126`
- §4 preamble — insert — ambiguity/mismatch — clock set returns 200; paths match with or without a trailing slash; unknown path/undeclared method returns the standard envelope with `ERR_INVALID_REQUEST` at 404/405 — `app.py:24,35-44`

### Pass 2 (advancement, scheduling, crew assignment, calc layer) — 10 ambiguity-pins, 2 mismatch-revisions, +3,648 chars

- §2.7 — insert — ambiguity — whole-second interval arithmetic drops the fractional remainder (120.9 s → 120) — `services/calc.py:240-242`
- §3.3 (create) — insert — ambiguity — `official_id` is read from the body and never compared to `X-User-ID`; an official may carry more than one application; `screened_at` null at creation — `routes/applications.py:29-53`
- §3.3 (field evaluations) — revise — **mismatch** — no application-state precondition beyond the `OPEN` gate; a report may be filed against any status including `APPROVED`/`DENIED` — `routes/applications.py:95-123`
- §3.3 (return-for-tape) — insert — ambiguity — `note` is ≥1 non-blank character with no declared upper bound — `routes/applications.py:171-172`
- §3.3 (decide) — insert — ambiguity — optional `note` under the same bounds; an omitted note leaves any previous `decision_note` intact — `routes/applications.py:200,210-211`
- §3.3 (list) — insert — ambiguity — the nested evaluation-report listing takes `limit`/`offset` only, no filters — `routes/applications.py:126-133`
- §3.4 (schedule) — insert — ambiguity — home/away distinctness runs at §2.9 step 3, ahead of resolving `season_program_id`; `kickoff_utc` is never compared to the clock — `routes/games.py:26-35`
- §3.4 (propose) — insert — ambiguity — the `OPEN` gate applies to the game's program; the official need not be registered under that program — `routes/assignments.py:45-49`
- §3.4 (confirm/withdraw) — insert — ambiguity — the assignment's own state is tested before the game's, so a doubly-invalid request reports `ERR_ASSIGNMENT_STATE_INVALID` — `routes/assignments.py:142-147,173-178`
- §3.4 (crew strength) — insert — ambiguity — `seasons_experience`/`tier` are read live at recompute time, so an approved advancement does not itself refresh any stored index — `services/derive.py:202-206`, `services/calc.py:98-105`
- §3.4 (PROJECTED variant) — revise — **mismatch** — names the actual recomputers (propose/confirm/withdraw/kickoff) and pins that voiding a merely `PROPOSED` assignment neither recomputes the index nor bumps the game's `version` — `services/derive.py:398-426`
- §3.4 (withdraw) — insert — ambiguity — `reason` is validated non-blank but never stored or returned — `routes/assignments.py:167`
- §3.5 (mark-played) — insert — ambiguity — `confirmed_crew_count` falls to 0; a still-`PROPOSED` assignment is untouched and never completed; `crew_strength_index`/`_variant` are not recomputed here — `routes/games.py:101-106`
- §3.9 (finalize) — revise — ambiguity — the recompute set is every distinct `official_id` named by any grade on the game whatever its `grade_status`, in the `created_at` order of the grades that first named them, each record mutated exactly once — `routes/games.py:141-158`

### Pass 3 (grading, appeals, replay, pool reports, discipline, derive layer) — 11 ambiguity-pins, 3 mismatch-revisions, +3,323 chars

- §2.9 step 3 — insert — mismatch — only the *presence* test of `MODIFIED`/`revised_grade_code` runs pre-lookup; the differs-from-stored comparison waits for the appeal to resolve, so a bad `appeal_id` still yields `ERR_APPEAL_NOT_FOUND` — `routes/appeals.py:112-120`
- §3.5 — insert — ambiguity — duplicate `station_code` rejected with `ERR_INVALID_REQUEST` — `routes/replay.py:31-34`
- §3.5 — insert — ambiguity — opening a review requires the game `IN_PROGRESS`, else `ERR_GAME_STATE_INVALID`, outranking category/offline/capacity — `routes/replay.py:66-68`
- §3.6 — insert — ambiguity — the `FINAL`-variant overturn exclusion scans every appeal ever filed against the grade (reachable via withdraw-then-refile) — `services/derive.py:301-324`
- §3.7 — insert — ambiguity — a filed appeal is written with null `decided_by_user_id`, `decision_note`, `revised_grade_code` — `routes/appeals.py:66-75`
- §3.7 — insert — ambiguity — the provisional recompute is itself a mutation, so `version` advances even on `UPHELD` — `routes/appeals.py:154`, `services/derive.py:358-359`
- §3.7 — insert — ambiguity — cascade hop five refreshes `postseason_eligible` with no second `version` bump; one decision moves the record's `version` by exactly 1 — `routes/appeals.py:171`, `services/derive.py:363-373`
- §3.8 — revise — mismatch — impl never refuses a `SUSPENSION` on official status: it moves only `ACTIVE`/`PROBATION`, leaves `SUSPENDED`/`CANDIDATE`/`RELEASED` alone, and runs the void cascade anyway — `routes/discipline.py:71-74`
- §3.8 — insert — ambiguity — the official's `version` bumps exactly once per open however many voids occur; the eligibility re-derive mutates the record only on an actual flag change — `routes/discipline.py:83-84`, `services/derive.py:363-373`
- §3.8 — insert — ambiguity — a resolve omitting `note` preserves an earlier `resolution_note` — `routes/discipline.py:136-137`
- §3.8 — revise — mismatch — impl re-derives eligibility on *every* `CLEARED` and leaves the official's row untouched when restoration doesn't land — `routes/discipline.py:140-148`
- §3.8 — insert — ambiguity — `ESCALATED` also re-derives `postseason_eligible`; record mutated only when the value moves; official bumps once — `routes/discipline.py:149-157`
- §3.9 — insert — ambiguity — the cited `play_grade_id` must resolve but need not belong to the named game and may be in any `grade_status` at drafting — `routes/pool_reports.py:29-38`
- §3.9 — insert — ambiguity — a supersede target already `SUPERSEDED` is a silent no-op and publication still succeeds — `routes/pool_reports.py:75-79`

### Confirmed-no-change verdicts (pass 3, on observations escalated by earlier passes)

- `derive.py:292-294` first-season-record-only — unobservable: registration opens exactly one record per official and nothing else writes `db.season_records`.
- `calc.py:242` truncation toward zero — already governed by pass 2's §2.7 sentence, including the negative-interval case; a local duplicate would add nothing.
- `derive.py:420` `max(0, n-1)` on `open_assignment_count` (and `replay.py:141` on `active_review_count`) — every decrement path fires exactly once per row leaving the counted set, so the clamp cannot bind.
- §3.9's "`supersedes_id` naming the drafting report itself is rejected" is vacuous prose (no update endpoint, no id at create time) with no client-observable behavior; left alone rather than spend an edit on unfalsifiable text.

### Closing integrity check (pass 3, re-verified independently by the orchestrator)

Tail ends at the last §5 row `| ERR_GAMES_IN_PROGRESS | 409 Conflict |` (real section boundary) · §4 = 57 endpoint rows · §5 = 45 error rows · 28 headers intact and in order · `cmp` confirms PRD_COMPLETED.md is **not** byte-identical to PRD_FINALIZED.md (+12,549 chars) · pass 1 and pass 2 edits spot-checked and surviving in the final file · zero occurrences of "scaffold" or the difficulty directive.

## Pipeline complete

All nine steps done. Final deliverables in place: SCAFFOLD.yaml + two design indices, workspace/PRD.md, workspace/PRD_FINALIZED.md (byte-identical to PRD.md — Step 7 made no implementation fixes), workspace/PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (conftest + 18 files, 165 tests, zero deletions), workspace/implementation/ (57 endpoints), and results.1..8.json all reading 165/165.
