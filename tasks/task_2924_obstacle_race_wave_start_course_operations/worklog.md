# Worklog — task_2924_obstacle_race_wave_start_course_operations

## Step 1: Create task directory — 2026-09-05T17:14:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2924_obstacle_race_wave_start_course_operations` and its `workspace/` subdirectory. Index 2924 was pre-assigned by the invocation; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T19:10:00.000Z

All three scaffold artifacts for task 2924 are complete and lint-clean.

## Files

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 1759 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1872 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4338 |

All three tails end at real structural boundaries (last `roles:` bullet, last `assert:` bullet, last `assert:` bullet respectively).

## SCAFFOLD.yaml (§1.0–§1.7)
12 entities / 54 endpoints / 33 validations / 63 errors / 7 roles / 11 calculations / 11 state machines / 2 concurrency rules. Top-level keys only — verified it contains **no** `scaffold_difficulty_design` or `scaffold_corner_design` key. Profile: Expert, `temporal_windowing` primary, layers `[dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency]`, graph topology, parallel state machines, `segregation_of_duties`, `immediate` consistency.

## SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)
9 rule groups (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`) × 2 instances = **18 instances**.

## SCAFFOLD_CORNER_DESIGN.yaml (§1.9)
All 9 guide sections present; **97 instances** = 59 full `test_recipe`s + 38 `excluded_because` stubs:

| section | total | recipes | excluded |
|---|---|---|---|
| entities | 12 | 12 | 0 |
| state_machines | 22 | 13 | 9 |
| calculations | 17 | 8 | 9 |
| validations | 15 | 9 | 6 |
| endpoints | 9 | 4 | 5 |
| errors | 12 | 7 | 5 |
| rbac | 3 | 3 | 0 |
| Cross-Cutting Complexity Layers | 6 | 2 | 4 |
| Consistency Model | 1 | 1 | 0 |

All 38 stub citations resolve to real §1.8 instance names (17 distinct; only `one_marshal_cannot_hold_overlapping_shifts_on_two_courses_until_the_first_is_vacated` is never cited). No name collisions between §1.8 and §1.9. Both §1.2.1 concurrency rules get real OCC instances under Cross-Cutting (`a_stale_entry_version_is_refused_before_the_state_check`, `a_stale_venue_version_is_refused_on_bond_settlement`), each proving stale-token 412, fresh-token success, and non-replayability of an accepted token.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2924_obstacle_race_wave_start_course_operations/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2924_obstacle_race_wave_start_course_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2924_obstacle_race_wave_start_course_operations/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  1137

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Other checks
- The `Generate task harder than expert level!` directive line was **stripped** from `scenario:` — it begins at "2924. Obstacle Race Wave Start & Course Operations (obstacle course race producer): ...". `grep -i "harder than expert"` returns nothing in any of the three files.
- Forbidden concurrency vocabulary ("simultaneously", "at the same time", "concurrently submitted", "in parallel", "first-writer-wins", "race winner/loser") appears nowhere.
- 46 distinct permit numbers (P-2924-01…12 in §1.8, C-2924-01 and C-2924-20…52 in §1.9) with zero duplicates, so the global `permit_number` uniqueness rule can't misfire across recipes.
- No sibling task directory was read, listed, or grepped at any point; scratch files stayed under `/tmp/task_2924_scaffold/`.

Orchestrator verification: all three files present (121943 / 308787 / 136126 bytes), no `harder than expert` / `expert level` string anywhere in the three YAMLs, no forbidden design keys in SCAFFOLD.yaml.

## Step 3: Copy shared files — 2026-09-05T19:11:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T19:26:00.000Z

PRD generated and all three hard contracts pass.

**Output:** `workspace/PRD.md`
**Line count:** 433 lines (96,612 bytes). Built with 8 chunked `cat >>` appends plus 2 targeted repair edits — no single giant Write.
**Tail check:** file's last line is `| \`ERR_WAVE_ROSTER_EMPTY\` | 409 |`, the final row of the §5 Error Code Catalogue table. Final heading is `## 5. Error Code Catalogue`. Real section boundary, no truncation, no audit footer.

### Section outline
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 Operator Identity and RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Common Resource Properties and Versioning · 2.5 The Logical Race Clock · 2.6 Request Evaluation Order · 2.7 Segregation of Duties · 2.8 Superseding Writes and Expected-Version Guards · 2.9 Rates, Roundings and the Conserved Bond Ledger · 2.10 Parcel Posture and the Freeze Cascade
- §3 Business Logic (9 subsections, lifecycle-chronological) — 3.1 Parcel + land-use application loop · 3.2 Course layout, bypass lanes, design gate · 3.3 Marshaling, medical coverage, staffing cascade · 3.4 Divisions and wave grid · 3.5 Enrolment, waivers, bag check · 3.6 Start line (two orthogonal dimensions) · 3.7 Attempt cards and provisional reading · 3.8 Protests, adjudication, official reading · 3.9 Festival area, restoration, bond settlement
- §4 Endpoint Definitions (54 rows, 4 columns)
- §5 Error Code Catalogue (63 rows, 2 columns)

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 111 required, 111 present, 0 missing
- endpoints[].request_body: 70 required, 70 present, 0 missing
- endpoints[].query_params: 23 required, 23 present, 0 missing
- concurrency_rules[].occ_field: 2 required, 2 present, 0 missing
- errors[].id: 63 required, 63 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 33 checked, 33 expressed in prose (§2.6 gives the full 33-rung ladder with applies_to scopes named per rung), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_entry_version / expected_venue_version + ERR_STALE_ENTRY_VERSION / ERR_STALE_VENUE_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 41 checked, 41 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed (incl. both dual variants of entry_elapsed_time and restoration_bond_release), 0 missing
- validations[] conditions: 33 checked, 33 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 30 endpoints with side_effects checked, 30 expressed, 0 missing
- entities[].fields[] structured content: 127 field entries checked, 127 reconstructible from prose (defaults, initial values, enum sets, and the common_fields:false exclusion for Division and ObstacleAttempt all stated), 0 missing
- sibling-branch symmetry: 8 groups checked (3 adjudication rulings; 4 inspection transitions; 2 waiver branches; 2 hold directions; design vs. effective clearance rate; 2 bond-release variants; provisional vs. official reading; 3 course→SUSPENDED links), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 930
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- literal "/ocr" occurrences anywhere in §3 (incl. outside backticks): 0
Status: PASS
```

### Coverage notes vs. the scaffold
- §2.2 verified byte-identical against `section-2.2-response-structure.md` (`req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `"data": { }` all unmodified).
- All 37 distinct state values and all 76 enum member strings appear verbatim in backticks; scans for fuzzy words (*approximately/roughly/conservatively/~*) and for operator syntax inside backticks (`==`, `>=`, `+=`, …) both return zero hits.
- Constants embedded in narrative rather than tabulated: 250 participants per medic, 2 water-safety per water obstacle, 45-minute holdback, 15-minute wave grid, 6-minute corral window, 15-minute travel buffer, 0.50 bypass-relief factor, 8.00/min relief cap, 0.60 partial-staffing factor, 3 obstacles / 0.50 progression / 2-point regression gates, 2 protest rounds, 25,000 cents per late day.
- **One scaffold ambiguity resolved explicitly:** the `RestorationTask` inspect transitions carry precondition `venue.site_posture != CLOSED_OUT`, while the `ERR_VENUE_FROZEN` catalogue entry lists "inspection operation … `FROZEN` or `CLOSED_OUT`". I followed the error catalogue (inspection requires `OPEN`) since it is the more explicit statement and is a superset that still satisfies the transition precondition; §2.10 and §3.9 state this consistently. Flagging in case Step 7 sees a divergence here.
- Confirmed: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. Scratch files were confined to `/tmp/task_2924_prd/`.

Orchestrator verification: 433 lines / 96612 bytes; heading scan shows §1–§5 all present; tail is the final `ERR_WAVE_ROSTER_EMPTY` catalogue row — a real section boundary, not mid-sentence. No regeneration needed.

## Step 6: Generate implementation — 2026-09-05T20:06:00.000Z

(Note: Steps 5 and 6 were launched concurrently; Step 6 returned first, so it is recorded first. The Step 5 entry follows.)

## Delivered

Complete Flask implementation at `workspace/implementation/` — 3,196 lines across 22 files, all `py_compile`-clean, no `__pycache__`/data files left behind.

| file | lines | | file | lines |
|---|---|---|---|---|
| `app.py` | 92 | | `routes/venues.py` | 60 |
| `start.sh` | 10 | | `routes/permits.py` | 137 |
| `requirements.txt` | 1 | | `routes/courses.py` | 139 |
| `errors.py` | 104 | | `routes/obstacles.py` | 116 |
| `db.py` | 200 | | `routes/divisions.py` | 58 |
| `response.py` | 64 | | `routes/waves.py` | 391 |
| `auth.py` | 62 | | `routes/participants.py` | 87 |
| `validation.py` | 335 | | `routes/entries.py` | 309 |
| `services/calc.py` | 365 | | `routes/staff.py` | 137 |
| `services/results.py` | 72 | | `routes/restoration.py` | 223 |
| `services/bond.py` | 81 | | `routes/common.py` | 64 |
| `services/cascade.py` | 89 | | | |

**Endpoints: 54 of 54 declared**, enumerated straight off `app.url_map` (venues 3, permits 5, courses 5, obstacles 4, divisions 3, waves 9, participants 4, entries 9, staff 4, restoration 6, clock 1; the clock endpoint lives in `routes/restoration.py`). Plus one undeclared `GET /ocr/_health` used only by the smoke harness.

## Structure

- **Ladder (PRD §2.6, normative over §3 prose).** Each handler executes rungs in numeric order with an inline rung comment: role (`auth.require`) → path (`validation.path_*`) → body schema (`field_*`) → body FKs (`fk_*`) → ownership → SoD → OCC → entity state → cross-entity → capacity. Two documented tie-breaks: un-hold checks `ERR_COURSE_STATE_INVALID` (9) before `ERR_COURSE_UNSAFE` (12); check-in checks entry/roster/wave state (9) before `ERR_PARTICIPANT_NOT_CLEARED` (14). Within rung 9 entity state precedes `ERR_VENUE_FROZEN` everywhere except task inspection, where frozen wins.
- **Errors.** `errors.py` maps all **63** catalogue ids; a programmatic diff against the PRD §5 table shows zero missing and zero status mismatches (only extra `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED` fallbacks).
- **State machines.** Parallel dimensions kept orthogonal: wave `release_status` vs `roster_status`, entry `progress_status` vs cyclic `result_status` (PROVISIONAL<->UNDER_PROTEST bounded by `protest_rounds < 2`), task VERIFIED<->REMEDIATION_REQUIRED, permit SUBMITTED<->REVISION_REQUESTED.
- **Cascades** (`services/cascade.py`, all in-transaction): four-link freeze (permit DENIED/EXPIRED -> venue FROZEN -> courses SUSPENDED+FROZEN -> waves HELD `VENUE_FROZEN`) with the FestivalService OPEN->CLOSED fan-out and no reduction of `disturbed_area_sqm`; four-link staffing vacate (marshal count -> staffing_state -> readiness -> SCHEDULED waves within the 45-min holdback HELD `COURSE_RESTRICTED`); wave-close bubble-up PUBLISHED->COMPLETED.
- **Calculations** (`services/calc.py`, `results.py`, `bond.py`): rates/progression 2dp `ROUND_HALF_UP` via `Decimal`, pph floors, money whole cents half-up, elapsed times exact whole seconds. Corral rate clamps both clearance rates; staffing factor (1.00/0.60/0.00) multiplies before relief.
- **OCC**: `expected_entry_version` -> `ERR_STALE_ENTRY_VERSION` (412) at rung 8 of adjudication; `expected_venue_version` -> `ERR_STALE_VENUE_VERSION` (412) at rung 8 of bond settlement, which uses `db.forced_mutation` so a repeated settlement still bumps `version`. Everything else uses `db.mutation` (bump only on real change). Logical clock only, never wall clock.

## Smoke check (port 21501, killed by verified PID)

Full happy path plus ~35 negative cases all behaved: permit revision loop -> approve (`revision_rounds` 1), SoD 403 when one `X-User-ID` submits and decides, validate/publish, register -> check-in -> lock -> release -> start (gun stamped, roster SEALED, `chip_start_utc` = gun+offset) -> attempt (penalty 30, staffing snapshot MARSHALED) -> finish (`provisional_elapsed_seconds` 630) -> protest -> stale adjudication 412 -> `UPHELD_ADJUSTED` (voided id, official 600) -> close -> entry OFFICIAL -> course COMPLETED. Bond ledger: shares 6,000,000/4,000,000 of a 10,000,000 bond over 300/200 sqm of 500 disturbed, clawback reversing to 0, FINAL with 3 late days -> released 9,925,000 / forfeited 75,000 / held 0 / `CLOSED_OUT`, then `ERR_BOND_ALREADY_SETTLED`. Clock expiry produced `expired_permit_ids` and the full freeze chain (venue FROZEN, course SUSPENDED+FROZEN, wave HELD `VENUE_FROZEN`); vacate produced the holdback split (near wave HELD `COURSE_RESTRICTED`, far wave untouched). Envelope, pagination meta, and 401/403/404/405/409/412/422 shapes all correct. No 500s in the server log.

Two host notes: port 21473 (my first pick) was already serving **another pipeline's** app, so I bind-tested a range and used 21501. Launching as `cd dir && bash start.sh &` captures the *subshell* pid, not the server's — that orphaned one process which I located via `ss -ltnp` + `/proc/<pid>/cwd` verification and killed by exact pid; no broad `pkill` was ever used. All scratch files are under `/tmp/task_2924_impl/`.

## Step 5: Generate unit tests — 2026-09-05T20:16:00.000Z

Stage 1 + Stage 2 are complete and verified for task 2924.

## Output locations (both directly under the TASK ROOT; no stray copies under `workspace/`)

**test_helpers/ — 2126 lines**
| file | lines |
|---|---|
| `__init__.py` | 10 |
| `api_client.py` | 325 |
| `api_errors.py` | 177 |
| `assertions.py` | 249 |
| `constants.py` | 283 |
| `factories.py` | 306 |
| `fixtures.py` | 462 |
| `test_users.py` | 117 |
| `types.py` | 197 |

**test_suite/ — 10097 lines, 178 tests**
| file | lines | tests |
|---|---|---|
| `conftest.py` | 16 | — |
| `test_01_dual_variant_readings.py` | 495 | 6 |
| `test_02_combinatorial_formulas.py` | 559 | 6 |
| `test_03_non_linear_state_machines.py` | 548 | 7 |
| `test_04_transitive_cascades.py` | 497 | 6 |
| `test_05_validation_priority_pairs.py` | 429 | 6 |
| `test_06_boundary_precision.py` | 484 | 6 |
| `test_07_cross_entity_state_dependency.py` | 401 | 6 |
| `test_08_resource_temporal_overlap.py` | 497 | 6 |
| `test_09_compensating_invariants.py` | 512 | 7 |
| `test_10_corner_entities.py` | 1052 | 26 |
| `test_11_corner_rbac.py` | 682 | 5 |
| `test_12_corner_state_machines.py` | 1181 | 37 |
| `test_13_corner_calculations.py` | 591 | 12 |
| `test_14_corner_validations.py` | 682 | 11 |
| `test_15_corner_endpoints.py` | 346 | 7 |
| `test_16_corner_errors.py` | 725 | 19 |
| `test_17_corner_cross_cutting.py` | 400 | 5 |

## Coverage

- **Queue A (depth index): 18/18 instances, 56 tests** — every instance has >=3 tests.
- **Queue B (breadth index): 59/59 live instances, 122 tests** — every live instance has >=1 test. The 38 `excluded_because:` stubs (state_machines 9, calculations 9, validations 6, endpoints 5, errors 5, Cross-Cutting 4) were deliberately not translated; zero tags point at a stub.
- `pytest --collect-only`: **178 collected, 0 import errors** — exactly matching the 178 `Design:` tags, so no test is untagged.

## Verification run

- Tag audit (`/tmp/task_2924_tests/verify_tags.py`) exits 0: every test carries exactly one `Design:` line, every tag resolves to a real live instance, no dual tags, no stub tags, no queue-A instance under 2 tests, no live queue-B instance with zero tests, and test-def count == tag count in all 17 files.
- Each of the 7 partition agents independently scripted a citation audit: all 178 leading citations are byte-verbatim substrings of `workspace/PRD.md`, non-abbreviated, prose (no endpoint-table rows or headings).
- `python3 -m py_compile` clean across all 26 files; `pyflakes` clean per agent.
- `test_helpers/` was **not** modified by any Stage 2 agent (all helper mtimes <= 19:41, earliest test file 19:50). Extra composition lives in private `_helper()` functions inside each agent's own test file.
- Grep checks: no `skip`/`xfail` anywhere, no whitespace-only header values, no money-as-string, no envelope double-unwrap.
- `__pycache__` removed; `git status` shows only the two new untracked directories.

## Skips (no whole instance was skipped; 9 sub-assertions dropped under the PRD-first filter)

*PRD-silent (condition 1 fails):*
1. `Corner/entities/computed_course_fields_ignore_client_supplied_values` — the "client-supplied computed values are ignored" half; §2.4 covers only a client-supplied `id`.
2. `Corner/entities/division_and_attempt_are_immutable_rows_without_version_or_update_endpoint` — the "no PATCH/PUT/DELETE route" half; only groundable in the §4 table, which citation rule C2 forbids.
3. `Corner/entities/self_referential_bypass_lane_resolves_and_is_excluded_from_primary_aggregates` — the claim that a lane's relief folds into its primary's clearance rate; §3.2 states the fold but gives no formula.
4. `Corner/endpoints/body_references_must_belong_to_the_path_courses_own_station_set` — the staff-assignment arm (shift naming a sibling course's `obstacle_id`); nothing requires the reference to resolve *on the addressed course*.
5. `Corner/Consistency Model/every_cascade_effect_is_visible_on_the_first_read_after_the_write` — the `vacated_at_utc` assertion; that field appears 0 times in the PRD.

*Not uniquely derivable (condition 2 fails):*
6. `Corner/validations/...` MEDIC shift echoing `obstacle_id: null` — PRD says the field is *omitted*, so null-vs-absent is open.
7. `Corner/validations/team_code_is_mandatory_for_team_heats_and_forbidden_elsewhere` — non-team entry echoing `team_code: null`; absent from §3.5's default list.
8. `Corner/errors/every_path_id_route_returns_its_own_not_found_code` — the `GET /ocr/divisions/{unknown}` probe; §2.6 rung 3 omits `ERR_DIVISION_NOT_FOUND`. The other 9 routes are asserted.
9. `Corner/state_machines/every_new_row_lands_in_its_declared_initial_state` — the RestorationTask row was left out rather than encode the yaml's invalid `RESEEDING` literal (see defects).

## Input defects found (PRD treated as authoritative in every case)

- **`SCAFFOLD_CORNER_DESIGN.yaml` / `SCAFFOLD_DIFFICULTY_DESIGN.yaml` use undeclared task types** `RESEEDING`, `REGRADING`, `DEBRIS_REMOVAL`; PRD §3.9 declares `RESEED`/`DECOMPACT`/`SILT_REMOVAL`/`DEBRIS_SWEEP`.
- **Corner recipes send inspection `outcome: "PASS"`**; the PRD enum is `VERIFIED`/`REMEDIATION_REQUIRED`.
- **Corner stale-venue-version recipe (~line 4229) asserts `bond_released_cents: 0` after two passing inspections**, contradicting §3.9's immediate per-task ledger sync *and its own next line*; the PRD-derived ledger was asserted instead.
- **PRD gaps worth flagging to the implementation side:** `ERR_DIVISION_NOT_FOUND` is missing from the §2.6 rung-3 enumeration although `GET /ocr/divisions/{id}` exists; the §3.2 bypass-relief fold has no formula; permit-decision HTTP status is only derivable from the §5 preamble (200, not 201).
- Test-authoring trap: the `factories` default `valid_until_utc` of `2026-09-15` must be overridden for any world that advances the clock to the late-closeout instants, or the §2.10 freeze cascade fires mid-setup.

Orchestrator verification: `python3 -m compileall` clean on both directories; 178 `def test_` across 17 files; `workspace/` contains only INSTRUCTION.md, PRD.md, implementation/, sweep.sh — no stray test dirs.

## Step 7: Run tests and iterate — 2026-09-05T20:57:00.000Z

All 8 rounds are green. Done.

## Summary

**Iterations run:** 2 sweeps (baseline + confirmation). The baseline came in at 177/178 in all 8 rounds with a single deterministic failure — no load artifacts, no flakiness, no connection/timeout noise.

**Tests deleted:** none. All 178 tests remain (`grep -c "^def test_"` across `test_suite/` still totals 178).

**Fixes applied to `test_suite/`:** one, in `test_suite/test_14_corner_validations.py`, test `test_the_permit_gate_runs_before_the_design_gates_on_validate`. Applied the STEP 1c partial-coverage split: kept both covered ladder-ordering assertions (`ERR_PERMIT_NOT_APPROVED` at rung 23 before `ERR_COURSE_TOO_SHORT` at rung 25, which is the test's stated purpose) and the post-approval `readiness_posture == RESTRICTED` assertion; replaced only the non-derivable `readiness_posture == FROZEN` assertion that followed the *refused* validate with an assertion that the refusal left the course `DRAFT`.

The failure was `AssertionError: readiness_posture: expected FROZEN, got RESTRICTED`. Diagnosis (BRANCH-ASYMMETRIC SIDE EFFECT under STEP 1b): PRD §3.3 enumerates the recompute triggers exhaustively — "recomputed whenever a permit is approved, denied or expired, whenever a course is validated or published, whenever a shift is confirmed or vacated, and whenever a heat is scheduled" — and §3.2 renders only validation's happy path as recomputing the posture, compressing the `ERR_PERMIT_NOT_APPROVED` refusal to a clause with no side effects. A rejected validate fires no declared trigger, so the course still carries the posture §3.2 explicitly mints it with: "A new course reads `status` of `DRAFT` and `readiness_posture` of `RESTRICTED`". The implementation was faithful and was left alone.

Corroborating evidence that the implementation's model is the PRD-faithful one: `test_an_unpermitted_venue_skips_the_quiet_window_entirely` (same file, line 242) asserts `FROZEN` on an identically unpermitted parcel and **passes** — because it schedules a heat first, which *is* a declared trigger. The two assertions are only mutually consistent under the stored-and-recomputed-at-declared-triggers reading, which is what the implementation does.

**Fixes applied to `test_helpers/`:** none. The helpers were clean — money as integer cents, full ISO-8601 instants, a `canonical_instant` normaliser already guarding sub-second-precision comparisons, empty-string (not whitespace) blank auth headers, and single-unwrap `get_success_data`. None of the known upstream-fixture failure shapes were present.

**Fixes applied to `implementation/`:** none. No implementation defect was found; storage remains in-memory only with no seeding or persistence (verified by grep for sqlite/file-writes/`/tmp`).

**Final sweep evidence** — read straight from `results.1..8.json` in `workspace/implementation/`:

| round | passed/total | failed | errors |
|---|---|---|---|
| 1 | 178/178 | 0 | 0 |
| 2 | 178/178 | 0 | 0 |
| 3 | 178/178 | 0 | 0 |
| 4 | 178/178 | 0 | 0 |
| 5 | 178/178 | 0 | 0 |
| 6 | 178/178 | 0 | 0 |
| 7 | 178/178 | 0 | 0 |
| 8 | 178/178 | 0 | 0 |

Each round ran ~320s. `worklog.md` was not touched (mtime still 20:23, predating my first sweep). My throwaway probe server on port 22410 was killed by exact PID; scratch files stayed under `/tmp/task_2924_step7/`.

Orchestrator verification: independently parsed all 8 `results.$i.json` — every round reports 178/178, failed=0, errors=0. `test_suite/` still holds 178 `def test_`. Step 8 is NOT skipped: the skip condition requires zero fixes in all four categories, and Step 7 made one `test_suite/` fix that flagged a genuine PRD silence (the `readiness_posture` recompute-trigger set on a refused validate).

## Step 8: Finalize PRD — 2026-09-05T20:49:00.000Z

Done. One edit, in §3.3.

## Line counts
- `PRD.md`: 433 lines / 13,771 words
- `PRD_FINALIZED.md`: 433 lines / 13,990 words
- Delta: 0 lines (+0.0%); +219 words (+1.6%) — a single paragraph (line 212) modified, `git diff` reports 1 insertion / 1 deletion.

## Change
- **§3.3 (`readiness_posture` paragraph, line 212)** — *insert* — after the existing (verbatim, untouched) trigger list, pinned that `readiness_posture` is a **stored** field, not derived at read time; that the trigger list is **exhaustive** and each trigger writes only when its operation succeeds; that a refused request (explicitly: a validation turned away at the §2.6 permit rung) leaves the stored posture as it stood, i.e. a never-triggered course still reads the `RESTRICTED` it was created with; that non-trigger operations leave it stale even when they move its inputs (station placement, heat close, `FINAL` bond settlement); that a permit denial/expiry leaves **every** course on the parcel at `FROZEN`, including already-`SUSPENDED`/`COMPLETED` ones; and that the rung-12 gates read the stored value. — `implementation/services/calc.py:265-283`, `implementation/routes/courses.py:36,120`, `implementation/services/cascade.py:15-49`, `implementation/routes/waves.py:84,142,194,226`

## Pre-edit search log (the one edit)
**(a) Subject:** where and when `readiness_posture` is written, and which value (stored vs freshly computed) is read by the operations gated on it.

**(b) Impl paths enumerated** (grep for `readiness_posture|apply_readiness|readiness_for|freeze_venue|staffing_*_cascade|recompute_venue_courses_readiness`, then read each):
- Writes: `routes/courses.py:36` (create -> literal `RESTRICTED`), `courses.py:120` (validate, after all gates), `courses.py:138` (publish, after all gates); `routes/permits.py:133` (APPROVED -> `cascade.recompute_venue_courses_readiness`), `:135` (DENIED -> `cascade.freeze_venue`); `routes/restoration.py:219` (clock advance -> permit `EXPIRED` -> `freeze_venue`); `routes/staff.py:78` (shift confirm), `:135` (vacate); `routes/waves.py:84` (heat scheduled). `services/cascade.py:29` forces `FROZEN` for `DRAFT/VALIDATED/PUBLISHED`, and the `else` branch at `:37` recomputes on `SUSPENDED/COMPLETED` courses too (both land on `FROZEN` because the parcel is non-`OPEN`) — this is what drove the "reaches every course on the parcel" clause.
- Reads: `waves.py:142` (un-hold), `:194` (release), `:226` (start) all read the **stored** field; `cascade.py:65` reads it immediately after writing it; `courses.py:133` (publish gate) is the lone site using freshly-computed `calc.readiness_for` — I verified this is unobservable (publish runs `require_venue_open` first, and the only other `FROZEN` cause, no single `APPROVED` permit while the parcel is `OPEN`, is unreachable for a `VALIDATED` course), so I deliberately scoped the "reads that stored value" claim to the three rung-12 operations §2.6 line 109 already enumerates rather than to every readiness check.
- Non-writers confirmed by reading: `routes/obstacles.py:16-81` (recomputes design fields/bottleneck/disturbed area only), `cascade.close_bubble_up` via `waves.py:303` (recomputes `scheduled_capacity_total`, can flip `PUBLISHED -> COMPLETED`, never readiness), `restoration.py:158-196` (`FINAL` settlement sets `site_posture = CLOSED_OUT` without refreshing any course posture), festival-service/entry/attempt/protest paths.
- `db.py:136-141`: `mutation()` bumps `version` only on actual change, so no-op recomputes are invisible — no version wording was needed.

**(c) Wording adjustments made for consistency:** (1) dropped a broader draft claim that "a request refused at any rung of §2.6 writes nothing at all" (unverifiable as a universal across all endpoints) down to a readiness-only claim, which every write site supports since the posture is always written after the last gate; (2) scoped the stored-value-read claim to the rung-12 trio instead of "every readiness check", to avoid mis-describing `courses.py:133`'s fresh evaluation; (3) added the permit-denial/expiry clause covering `SUSPENDED`/`COMPLETED` courses so the new "the list is complete" claim does not under-describe `cascade.py:37`; (4) named station placement, heat close and `FINAL` settlement as explicit non-triggers, since each moves a genuine readiness input (`staffing_state`, `scheduled_capacity_total`, `site_posture`) and a fresh implementer would otherwise plausibly recompute there.

No implementation or test files were touched; `worklog.md` and `SCAFFOLD*.yaml` were not read or modified.

Orchestrator verification: `PRD_FINALIZED.md` exists, 433 lines, 97865 bytes vs PRD.md's 96612, and `cmp` confirms the two differ — the edit landed.

## Step 9: Complete PRD — 2026-09-05T21:32:00.000Z

Run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 owned the `cp`; passes 2 and 3 were explicitly forbidden from copying). A single pass over 22 impl modules reliably under-scans, and a byte-identical PRD_COMPLETED.md would mean the scan never ran. Total: **54 edits** (45 ambiguity-pins, 9 mismatch-revisions), 433 lines / 97,865 -> 114,013 bytes (+16.5%).

### Pass 1 — global machinery + parcel/permit/course/obstacle/division
Files: app.py, response.py, auth.py, errors.py, db.py, validation.py, routes/{common,venues,permits,courses,obstacles,divisions}.py, services/cascade.py. 22 changes (18 ambiguity-pins, 4 mismatch-revisions), all single-line `NcN` hunks so line numbering stayed stable for later passes. §2.2 envelope byte-identical.
- §2.1 L15 — insert — header values are trimmed, so a whitespace-only header counts as empty -> `ERR_UNAUTHENTICATED` — auth.py:43-48
- §2.3 L74 — insert — non-integer `limit`/`offset` is 422; empty-string value falls back to the default — validation.py:225-237
- §2.3 L76 — revise — mismatch — the two attempt listings order by `recorded_at` (then `created_at`, then insertion), not `created_at`; insertion-order tie-break pinned for all other listings — obstacles.py:115, db.py:164
- §2.3 L78 — insert — a list filter naming an unresolvable id is never a 404, it matches no rows (`total_count` 0) — obstacles.py:86-92, waves.py:92-96, entries.py:22-26, staff.py:88-92
- §2.4 L82 — insert — accepted input instant forms (`Z`, `+00:00`, other offsets converted, naive read as UTC, any fractional width) and truncation, not rounding, to three digits on render — validation.py:193-205, db.py:73-86
- §2.4 L84 — insert — a recomputation leaving every stored value identical is not a mutation: `version`/`updated_at` stand still — db.py:135-141
- §2.5 L90 — insert — the world boots empty, nothing is seeded, nothing survives a restart, clock returns to epoch — app.py:33, db.py:43-47
- §2.6 rung 12 L109 — revise — mismatch — course publication is also guarded by `ERR_COURSE_UNSAFE`, under the weaker "not `FROZEN`" test, after its state and posture rungs — courses.py:130-134
- §2.8 L142 — revise — a version field sent to a non-versioned endpoint (like any unrecognised body field) is ignored, not rejected — validation.py:70-82
- §2.9 L150 — insert — numerics are JSON numbers, never quoted strings; `3.0` is refused where an integer is declared — validation.py:119-147
- §2.10 L160 — revise — mismatch — "every row touched" -> only rows the chain actually modifies bump `version`; a link finding its target already in the imposed state writes nothing — cascade.py:15-43 with db.py:135-141
- §3.1 L168 — insert — `water_access`, `land_use_zone`, `protected_acreage_sqm` are descriptive only; no gate reads them — venues.py:19-21
- §3.1 L172 — insert — `max_disturbed_area_sqm` is an integer; equal quiet hours describe an *empty* window; drafting an application is not gated on `site_posture` — permits.py:18-55, calc.py:355-361
- §3.1 L174 — insert — permit state is examined before parcel posture, so `ERR_PERMIT_STATE_INVALID` wins over `ERR_VENUE_FROZEN` — permits.py:82-84
- §3.1 L176 — insert — `""` is a valid `decision_note`; omitted/null preserves the existing note — permits.py:99,122-123
- §3.2 L182 — revise — `total_distance_m` is an integer — courses.py:21
- §3.2 L184 — insert — `station_index` uniqueness spans bypass lanes too, and `ERR_OBSTACLE_SET_FROZEN` precedes `ERR_VENUE_FROZEN` — obstacles.py:37-48
- §3.2 L186 — insert — `paired_obstacle_id` is only checked for resolving on the same course, so pairing to another bypass lane is accepted — validation.py:323-328
- §3.2 L198 — revise — mismatch — publication tests the posture as *recomputed*, not the stored value — courses.py:133
- §3.4 L218 — insert — `division_type`/`bypass_policy`/`scoring_mode` are never cross-validated; downstream rules read each field directly — divisions.py:19-21
- §4 preamble L306 — insert — unauthenticated `GET /ocr/_health` returns a bare `{"status","current_utc"}` object outside the §2.2 envelope — app.py:80-82
- §5 preamble L367 — insert — `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405) for unroutable requests, decided before authentication, plus `ERR_INTERNAL` (500) as a last resort — app.py:53-78

Pass 1 borderline trail: permit decisions are not posture-gated (`decide_permit` never calls `require_venue_open`); publish's fresh-vs-stored readiness is practically unobservable but was pinned anyway; `permit_number` has no max length and was left silent rather than inventing a bound; Flask's 400 handler (`ERR_INVALID_REQUEST` at HTTP 400) is unreachable because `validation.body()` raises its own 422; non-JSON `Content-Type` with a valid body yields 422 as a Flask artefact, left unpinned.

### Pass 2 — wave grid / start line / enrolment / entries / attempts / protests / staffing / calculations
Files: routes/{waves,participants,entries,staff}.py, services/{calc,results}.py. 20 changes across 17 lines (18 ambiguity-pins, 2 mismatch-revisions). 104,412 -> 110,212 bytes.
- §3.3 — insert — a rostered shift's `obstacle_id` must resolve *on the addressed course* (404 otherwise) and that rung outranks the missing-station complaint; an explicit `null` counts as omitting it for a MEDIC/SWEEP shift — staff.py:126,131,134
- §3.3 — insert — `certification_level` is recorded but never checked against `staff_role`; rostering is not gated on parcel posture or course status — staff.py:105-167
- §3.3 — revise — mismatch — PRD claimed shift instants "are compared at second resolution"; impl compares at full supplied precision (§2.4 truncation is render-only) — calc.py:340-352, validation.py:257-269
- §3.3 — insert — confirming a shift recomputes `bottleneck_capacity_pph`/`readiness_posture` but never holds a heat (no holdback counterpart) — cascade.py:314-318
- §3.4 — revise — mismatch — pass 1's "only the team roster minimum consults `division_type`" was too narrow; §3.5's `team_code` shape rule + `team_size_max` cap also read it (the only two reads) — waves.py:235,332
- §3.4 — insert — heat scheduling never consults the course's own `status` (DRAFT/VALIDATED/PUBLISHED/COMPLETED all schedulable) — waves.py:15-86
- §3.4 — insert — quiet window with equal start/end hour is *empty*, not a full day — calc.py:355-361
- §3.5 — insert — `email` gets no format validation, only uniqueness — participants.py:20
- §3.5 — insert — `signature_name` validated but never persisted; `medical_flags` is free-form (not an enum) and omitting it stores an empty array — participants.py:69-86
- §3.5 — revise — re-signing a resolved waiver names its error id: `ERR_ENTRY_STATE_INVALID` (409), previously unnamed anywhere — participants.py:77-78
- §3.5 — insert — registration reads only `waiver_signed`, never `clearance_status` (a `MEDICALLY_HELD` human registers, is stopped at check-in); not gated on parcel posture or course status — waves.py:326-327
- §3.5 — insert — `bag_tag_code` is stored as supplied and not unique across entries — entries.py:64,83
- §3.5 — insert — reassignment re-applies *only* roster capacity: bib uniqueness, age, and `team_size_max` go unchecked in the target; a self-move is accepted subject to the capacity test and advances no `version` — entries.py:89-127
- §3.6 — insert — `hold` `reason` omitted leaves `hold_reason` null; empty string accepted — waves.py:122,132
- §3.6 — insert — a `DNS` entry keeps `chip_start_utc` null — waves.py:270-273
- §3.6 — insert — the close moves a non-finisher to DNF *unconditionally*, overwriting `DISQUALIFIED -> NOT_CLASSIFIED` (§3.8 calls DISQUALIFIED terminal) while leaving `dq_reason` standing — waves.py:292-296
- §3.6 — insert — the official reading is computed only for the PROVISIONAL->OFFICIAL promotions; DNF entries and finished-DISQUALIFIED entries keep `official_penalty_seconds` 0 / `official_elapsed_seconds` null — waves.py:292-300
- §3.6 — insert — *every* close recomputes the course's `scheduled_capacity_total` and bumps the course `version`, not only the completing one — cascade.py:340-351
- §3.7 — insert — an attempt's `obstacle_id` must resolve on the entry's heat's course, 404 at rung 5 — entries.py:243
- §3.8 — insert — `voided_attempt_ids` appends without de-duplication (re-protesting the same attempt records the id twice); a `DISQUALIFIED` ruling alone computes no official reading — entries.py:214-228

### Pass 3 — restoration / inspections / festival services / bond ledger / closeout / clock advance
Files: routes/restoration.py, services/bond.py, closeout-facing parts of services/cascade.py. 12 changes (9 ambiguity-pins, 3 mismatch-revisions). 110,212 -> 114,013 bytes.
- §2.5 — revise — mismatch — the clock-advance response was described as "not an envelope-wrapped entity"; impl uses the standard §2.2 envelope with `response_type: "object"` and the `{current_utc, expired_permit_ids}` object inside `data` — restoration.py:221, response.py:27
- §2.5 — insert — the clock may be set backwards; no monotonicity rule, no error — restoration.py:206
- §2.5 — insert — `expired_permit_ids` is ordered by permit creation order, and a second permit expiring on the same parcel in one movement re-runs a cascade that writes nothing — restoration.py:209,216-219
- §2.8 — insert — `expected_venue_version` has no schema bounds, so 0/negative clears rung 4 and is reported as `ERR_STALE_VENUE_VERSION`, not `ERR_INVALID_REQUEST` — restoration.py:167
- §3.9 — insert — installing a festival service increments the parcel's `version`/`updated_at` (footprint >= 1 makes the disturbed-area recompute always a real change) — restoration.py:45-46
- §3.9 — insert — opening a remediation task is **not** posture-gated; `FROZEN`/`CLOSED_OUT` parcels accept it — restoration.py:64-93
- §3.9 — insert — `findings_note`: empty string overwrites; omitted/null leaves the stored note untouched — restoration.py:128,138-139
- §3.9 — insert — posture gate is checked before the no-op-outcome gate, so a no-op inspection on a frozen parcel reports `ERR_VENUE_FROZEN` — restoration.py:131-133
- §3.9 — insert — a zero share (parcel with `restoration_bond_cents` of 0) writes no money and leaves the parcel's `version`/`updated_at` untouched while the task's still advances — restoration.py:151-154
- §3.9 — insert — every inspection transition answers with the `RestorationTask`, not the parcel — restoration.py:156
- §3.9 — revise — mismatch — `PROGRESSIVE` was said to leave `site_posture` "OPEN"; impl never touches it, so a `FROZEN` parcel stays `FROZEN`. Also pinned: settlement's only posture check is the `CLOSED_OUT` refusal, both kinds answer with the `Venue`, and the `version` bump is **unconditional** — the single documented exception to §2.4's idempotent-recompute rule (`db.forced_mutation` is used here and nowhere else) — restoration.py:159-197, bond.py:54-58, db.py:145
- §3.9 — revise — mismatch — `FINAL` was said to advance `site_posture` "from `OPEN`"; impl writes `CLOSED_OUT` from whatever it read, `FROZEN` included — restoration.py:195
- §3.9 — insert — remainder target tie-break gains a third key (equal area + equal `created_at` -> earliest insertion), that task's `version` increments, and the adjusted figure is not clamped so it may go negative under a large late penalty — bond.py:71-77

Pass 3 verified-as-already-pinned: `RESEED`/`DECOMPACT`/`SILT_REMOVAL`/`DEBRIS_SWEEP` and `VERIFIED`/`REMEDIATION_REQUIRED` match validation.py:57,59 and are each stated uniquely — the Step 5 generator's flag about the design YAMLs' undeclared literals is confirmed as a scaffold-only defect, not a PRD one. Also confirmed correct: the area-budget sum spans tasks of every status; per-task `round_half_up` vs once-rounded gross; the `min(25000*days, gross)` clamp with `ceil(seconds/3600/24)`; the conservation invariant; role lists on all seven restoration endpoints match §4 exactly; and Step 8's pin that `FINAL` settlement is not a readiness trigger (confirmed — `settle_bond` makes no cascade call).

### Structural integrity (pass 3 + orchestrator, independently)
433 lines; ends at the final §5 row `| ERR_WAVE_ROSTER_EMPTY | 409 |`; §2.2 success-envelope block intact; §4 = 54 rows, §5 = 63 rows (121 pipe rows total across both); 27 headings; `cmp` vs `PRD_FINALIZED.md` = DIFFERENT, so the scan demonstrably ran.

### Orchestrator final verification
- PRD chain: PRD.md 96,612 B -> PRD_FINALIZED.md 97,865 B -> PRD_COMPLETED.md 114,013 B, all 433 lines.
- `find` over `workspace/implementation`, `test_suite`, `test_helpers` for any `.py` newer than `results.1.json` returns nothing — no code was modified after the green sweep, so the 8x 178/178 evidence still stands for the delivered artifacts.

## Pipeline complete — 2026-09-05T21:33:00.000Z
All nine steps done. Final state: 178 tests, 8/8 sweep rounds at 178/178, `workspace/PRD_COMPLETED.md` written.
