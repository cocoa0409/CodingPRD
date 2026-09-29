# Worklog — task_2995_reentry_employment_services

## Step 1: Create task directory — 2026-09-06T03:49:10.407Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2995_reentry_employment_services/` and `.../workspace/` (pre-assigned path; no index allocation performed).

## Step 2: Generate scaffold — 2026-09-06T05:21:30.000Z

All three scaffold artifacts are complete and the lint is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2995_reentry_employment_services/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2995_reentry_employment_services/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2995_reentry_employment_services/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     10
  §1.8 instances scanned:     24
  §1.9 instances scanned:     74
  Calls scanned (§1.8+§1.9):  1589

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**SCAFFOLD.yaml (§1.0–§1.7)** — 10 entities, 61 endpoints, 59 error codes, 55 validation rules, 12 calculations, 14 state machines / 69 transitions, 6 roles, 3 concurrency rules. Profile: `graph` topology, `parallel` state-machine shape, `segregation_of_duties` role model, `immediate` consistency, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation]`, `difficulty_level: expert_plus`. Top-level keys contain neither `scaffold_difficulty_design` nor `scaffold_corner_design`; `scenario` holds the supplied text verbatim starting at "Reentry Employment Services …" and the difficulty directive appears nowhere in the task dir (`grep "harder than expert"` → none).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — single top-level key; 9 of 9 §0.5 difficulty rules, 24 instances (2–3 each): dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 2.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — single top-level key; 9 sections, 96 instances (74 full recipes + 22 `excluded_because` stubs):
entities 11/0, state_machines 12/3, calculations 9/5, validations 13/3, endpoints 5/0, errors 10/9, rbac 8/0, cross_cutting_complexity_layers 5/2, consistency_model 1/0.
All 59 error codes are covered (each either asserted by a §1.9 instance or delegated to a named §1.8 instance); every stub's `difficulty_instance` was programmatically checked to exist in §1.8, and instance names are unique across the union of both design files.

File sizes: SCAFFOLD.yaml 2828 lines / 163164 B; SCAFFOLD_DIFFICULTY_DESIGN.yaml 4576 lines / 170196 B; SCAFFOLD_CORNER_DESIGN.yaml 11172 lines / 402570 B.

Orchestrator verification: `grep -rn "harder than expert"` over the whole task dir returned no matches — the difficulty directive did not leak.

## Step 3: Copy shared files — 2026-09-06T05:22:00.303Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 B). Removed the now-empty `.scratch/` parent left by Step 2.

## Step 4: Generate PRD — 2026-09-06T05:40:00.000Z

Step 4 complete. `workspace/PRD.md` is finished.

**Final file stats:** `464` lines, `117535` bytes (`wc -l` / `wc -c`).

**Last 5 lines verbatim:**
```
| `ERR_PARTICIPANT_HAS_ACTIVE_PLACEMENT` | 409 |
| `ERR_CATEGORY_NOT_FUNDABLE` | 409 |
| `ERR_PARTICIPANT_CAP_EXCEEDED` | 409 |
| `ERR_SUBSIDY_CAP_EXCEEDED` | 409 |
| `ERR_GRANT_FUNDS_INSUFFICIENT` | 409 |
```
The file ends at a real boundary — the last row of the completed §5 error table, no audit footer.

**Structure:** §1 Introduction; §2 Global Specifications with 2.1 RBAC → 2.10 Path Addressing; §3 Business Logic in nine subsections (3.1 intake/assessment/documents, 3.2 release planning, 3.3 supervision + work window, 3.4 partnerships/openings/bonding, 3.5 readiness sessions/seats, 3.6 matching + eligibility ladder, 3.7 shifts/subsidy ladder/separation, 3.8 grants/supportive services/deferral waterfall, 3.9 suspension/licence relief/retention/exit/funder reporting); §4 endpoint table; §5 error table.

**Self-checks (all machine-verified against SCAFFOLD.yaml, never against the two withheld design files — neither was opened, grepped, or referenced):**
- **Endpoints: 61 / 61.** §4 table has exactly 61 data rows, 4 columns; all 61 scaffold paths appear verbatim in backticks; roles copied straight from `endpoints[].roles` and cross-checked against the `roles:` RBAC block.
- **Error codes: 59 / 59.** §5 table has exactly 59 data rows; all 59 identifiers also appear inside the §1–§3 prose, not merely in the table.
- **Contract 1 (Field-Name Coverage): PASS.** Two independent passes (131-name pre-extracted list; 135 names re-derived fresh from YAML) both report 0 missing. 0 missing across the 33 computed-read output field names and 0 missing across 104 enum values (the three initially-uncovered `bonding_status` values `REQUESTED`/`CLAIMED`/`EXPIRED` were repaired by naming the dimension's value set explicitly in §3.6).
- **Contract 2 (Rule Coverage): PASS.** All 69 transitions across the 14 state machines covered; all 55 validation rules' error IDs appear in the body; all 12 calculations written out with formulas, constants, boundaries and worked figures; the 3 OCC rules are in §2.6; the 13-band precedence ladder is in §2.5; both segregation-of-duties checks, both ownership rules, and every cascade family documented.
- **Contract 3 (§3 Path Purity): PASS.** §3 has an even backtick count (2686) and 0 violations.
- §2.2 is byte-identical to the doc-generator skill's `section-2.2-response-structure.md` (diff-verified).
- 0 hits for any of: difficulty, expert, scaffold, complexity, archetype, §1.x, internal scaffold references, machine-generation hints.

**Housekeeping:** built with 1 `Write` + 10 heredoc appends (never a single giant write), verified after each. Nothing outside `workspace/PRD.md` modified.

Orchestrator verification (truncation guard): `tail -20` shows the file ending on a complete final error-table row; top-level headings are §1 … §5 with §5 present and populated; `grep -in "harder than expert|expert_plus|difficulty"` over PRD.md returned no matches. PRD accepted — no regeneration needed.

## Step 6: Generate implementation — 2026-09-06T06:15:00.000Z

Implementation complete and verified. No servers left running; no stray files.

## Deliverables — `workspace/implementation/`

| file | lines | role |
|---|---|---|
| `app.py` | 102 | Flask entry point, global request lock, band-1 auth, error handlers, `POST /_clock/set_current_utc`, 6 blueprints |
| `store.py` | 121 | in-memory `db` (10 dicts), logical clock, ISO-8601 formatter, `new_row`/`touch`/`public` |
| `errors.py` | 88 | all 59 error ids → HTTP status, `ApiError`, `fail()` |
| `envelope.py` | 54 | §2.2 envelope, `ok`/`created`/`listing`/`error_response` |
| `validation.py` | 297 | header/role gates, typed field parsers, pagination, query helpers |
| `domain.py` | 420 | vocabularies, Decimal helpers, derived-field recomputation, three-tier subsidy engine |
| `ledger.py` | 212 | grant ledger by aggregation, posture bands, per-line pricing, deferral waterfall |
| `counters.py` | 122 | opening/partnership/session counters, stage advance/revert, reconcile chains |
| `matching.py` | 104 | six match components + creation-ladder `blocking_error` |
| `cascades.py` | 226 | work-window fit, shift conflict/restore, separation, termination, suspension + exit cascades |
| `common.py` | 61 | read roles, 404 mapping, pagination, filter matching |
| `routes_participants.py` (401), `routes_supervision.py` (158), `routes_partnerships.py` (225), `routes_sessions.py` (220), `routes_grants.py` (329), `routes_placements.py` (441) | | the 61 endpoints |
| `start.sh` | 6 | `PORT` from env (fallback 10000), binds `0.0.0.0`, foreground `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=3.0` |

Total 3588 lines. Nothing else in the directory (`__pycache__` removed); `.scratch/step6` deleted, `.scratch` parent and its `step5` sibling untouched.

## Self-check
- **Endpoints: 61/61.** Enumerated from `app.url_map` and matched path-for-path against the PRD §4 table.
- **Error codes: 59/59.** Every id in the PRD §5 table is present in `ERROR_STATUS`, every HTTP status matches the table exactly, there are no extra ids, and every one of the 59 is actually reachable from a route or helper (no dead entries).
- **No seeded data:** fresh boot on a clean tree returns `total_count: 0` for all ten collections; unauthenticated request → 401.
- **No TODOs, no 501s.**

## Verification performed
Three live smoke runs (ports 51995/51996, each killed by a port-scoped PID lookup — no `pkill` used) exercised ~120 flows. Everything matched the PRD, including all of its pinned figures: per-line support pricing 3868/4718/3188/2185 → 13959 (+419 admin = 14378), admin-fee bands (5000→0, 5001→150, 57143→2857 capped at 60000), subsidy tiers (3×40h@1850 → 92500; 1×90h → 78625; 4×50h@1900 → 114000; 6.25h@1855 → 5797; 10×40h@2000 → capped 120000), barrier 66.3/HIGH, doc completeness 80.0/100.0, match score 75 with exact component breakdown, and the 15% restricted-floor posture bands.

Behavioural checks that passed: the full 13-band refusal ladder order, all three OCC guards (412 with parent-specific codes), both `ERR_SEGREGATION_OF_DUTIES` paths, the deferral waterfall (deny→defer→promote-one-head with `deferred_at`/`promoted_at`), the ledger identity `authorized = available + committed + disbursed` after every write, info-round and petition-round exhaustion at exactly 2, the licence-relief cycle including the PRD's explicit illegal moves (`RELIEF_GRANTED` from `INFO_REQUESTED` → `ERR_PARTICIPANT_INVALID_STATE`), the supervision-revocation cascade (compliance flip → `RESTRICTED` posture → `CONFLICTED`/`SUPERVISION_REVOKED` shifts → restore on re-approval), the closed 45-minute commute buffer (PRD's own 09:00/09:45 adjacency example collides; 09:46 is accepted), session hold/cancel sweeps with the seat-conservation identity, the bonding ladder `NONE→REQUESTED→BONDED→CLAIMED`, retention milestones, the suspension and exit cascades, and both outcome-report variants.

One note for the record: `created_at`/`updated_at` come from the wall clock while every temporal rule and stamp the PRD §2.4 list names (`deferred_at`, `promoted_at`, `last_retention_check_at`, window/past/session/milestone checks) comes from the logical clock — §2.4 enumerates its scope and does not include the audit columns.

Orchestrator verification: `POST /_clock/set_current_utc` is not an unauthorised addition — it is declared verbatim in PRD §4 (line 338) and its semantics are stated in PRD §2.4 (line 94). `start.sh` reads `$PORT`, execs in the foreground. Directory contains only implementation files.

## Step 5: Generate unit tests — 2026-09-06T07:14:00.000Z

NOTE (orchestrator): the Step 5 subagent was killed mid-run by a transient infra/API error after writing 5 of 9 `test_helpers/` files (api_client, api_errors, constants, types, test_users — 1347 lines) and no `test_suite/` at all. Rather than respawning a fresh generator — which would have made the suite diverge from the half already on disk — the same agent was resumed via SendMessage with a computed to-do list (missing `__init__.py`, `assertions.py` incl. both `validate_paginated` and `validate_unpaginated`, `factories.py`, `fixtures.py`, then `conftest.py` and all test files) and its own `.scratch/step5/` compact design indices still intact. It resumed with full context and completed the job. Its final report follows verbatim.

Step 5 is complete. All 98 candidate design instances are translated, zero skips.

## Deliverables

`test_helpers/` (2,636 lines)
```
 81  __init__.py      359  api_client.py    154  api_errors.py
261  assertions.py    376  constants.py     457  factories.py
490  fixtures.py       97  test_users.py    361  types.py
```

`test_suite/` (6,991 lines, 122 test functions)
```
 24  conftest.py                        496  test_10_entities.py
254  test_01_dual_variant_calculations  739  test_11_state_machines.py
265  test_02_combinatorial_formulas     578  test_12_calculations.py
290  test_03_parallel_state_dimensions  545  test_13_validations.py
316  test_04_transitive_cascades        262  test_14_endpoints.py
332  test_05_refusal_precedence_pairs   759  test_15_errors.py
251  test_06_boundary_precision         480  test_16_rbac.py
373  test_07_cross_entity_state_gates   395  test_17_cross_cutting.py
318  test_08_resource_temporal_overlap   96  test_18_consistency_model.py
218  test_09_compensating_invariants
```

## Coverage (machine-verified against both yaml indices)

- Queue A (§1.8, difficulty): **24 / 24** non-stub instances, each rendered as 2 test functions (48 tests) in `test_01`–`test_09`. No instance missing, no tag pointing at a non-existent instance, rule_id matches for all.
- Queue B (§1.9, corner): **74 / 74** non-stub instances, 1:1 with 74 tests in `test_10`–`test_18`. Section names match for all. 22 stub (`excluded_because`) instances correctly ignored.
- **Skips: none.** Every non-stub instance passed the PRD-first two-condition filter.

## Deviations to record

- `Corner/errors/a_live_placement_blocks_termination_exit_and_a_second_bond_agreement` (test_15): the design put the participant in `PLACED` when probing exit, but PRD §3.9 makes exit illegal from `PLACED`, so band 8 (`ERR_PARTICIPANT_INVALID_STATE`) would legitimately outrank the instance's band-12 `ERR_PARTICIPANT_HAS_ACTIVE_PLACEMENT`. The test moves the participant to `RETENTION` — where exit is explicitly legal and the live placement is the only bar — and asserts `stage == RETENTION`. The asserted error id is unchanged.
- `Corner/rbac/a_supervision_officer_cannot_act_on_another_officers_case` and `Corner/consistency_model/derived_money_...`: the design wrote `work_authorization` and `info_request_count`; the tests use the PRD's real field names `work_authorization_status` and `info_rounds_used`.

## Verification run

- `pytest test_suite --collect-only` → **122 tests collected**, no import or collection errors.
- `pyflakes` on both directories → clean apart from 4 intentional re-export warnings in `test_helpers/__init__.py` and `assertions.py`.
- Citation audit: `tests=122 tagged=122 problems=0` (every docstring has ≥1 verbatim PRD quote and exactly one `Design:` line); section-number audit `mismatches=0`; no test mentions the word "scaffold"; no `skip`/`xfail`/placeholder anywhere.
- Fixture audit (12 items) re-run: no money/int field sent as a JSON string; no date-only where an instant is declared and no instant where a date is declared; `api_client` normalises fractional-second width to three digits; blank-header builder uses `""`; no duplicate enum definitions in `constants.py`; every derived builder exposes its explicit values as named parameters so `**overrides` cannot collide; `validate_paginated` (runner) and local `validate_unpaginated` both available; no envelope double-unwrap; all six role identities distinct.

Bugs fixed this session in previously written files: three envelope assertions read `meta["response_type"]` instead of the top-level key (`test_13_validations.py`, two sites in `test_10_entities.py`); one `test_17` request used the factory's default `TOOLS` coverage rate (0.85) where the design needed `TRANSIT_PASS` at 1.00, which would have made the ledger assertion 3400 vs 4000; one `test_17` citation was labelled §3.6 for a §3.7 sentence.

`test_helpers/` and `test_suite/` are at the task root; neither exists under `workspace/`. `worklog.md`, `SCAFFOLD*.yaml`, and `workspace/` are untouched. `.scratch/step5` removed; the `.scratch` parent left in place.

Orchestrator verification: `test_helpers/` and `test_suite/` confirmed at the task root and absent from `workspace/`; 122 `def test_` functions and 122 `Design:` tags counted independently; stray `__pycache__` and the now-empty `.scratch/` parent removed.

## Step 7: Run tests and iterate — 2026-09-06T07:38:00.000Z

Two full 8-round sweeps came back green with zero changes required.

## Summary

**Iterations run:** 1 diagnostic iteration + 1 independent confirmation sweep (16 rounds total, all green).

**Per-round results (from `workspace/implementation/results.$i.json`):**

| Round | Iteration 1 | Confirmation sweep |
|---|---|---|
| 1 | 122 / 122 | 122 / 122 |
| 2 | 122 / 122 | 122 / 122 |
| 3 | 122 / 122 | 122 / 122 |
| 4 | 122 / 122 | 122 / 122 |
| 5 | 122 / 122 | 122 / 122 |
| 6 | 122 / 122 | 122 / 122 |
| 7 | 122 / 122 | 122 / 122 |
| 8 | 122 / 122 | 122 / 122 |

`total - passed == 0` for every round, cross-checked against `Counter(t['status'] for t in d['tests']) == {'passed': 122}` (so the parser is not silently missing failures keyed differently), and against each round log's `Results: 122/122 passed, 0 failed, 0 errors, 0 skipped`. Iteration 1 ran ~215.9 s/round; the confirmation sweep ~224.3 s/round, confirming they are two distinct runs (fresh `SWEEP_DONE` + `results.*.json` timestamps, since `sweep.sh` unlinks both at start).

**Tests deleted:** none. No test failed in any round, so no PRD-silence or non-unique-derivability collapse was ever triggered.

**Fixes to `test_suite/`:** none.
**Fixes to `test_helpers/`:** none.
**Fixes to `implementation/`:** none.
**Failures concluded load-induced:** none — there were no failures at all. No round showed `Terminated` in its server log, no round died at a shared instant, no ServerStartError, no lsof timeout.

**Verification work done anyway** (to be able to adjudicate a failure had one appeared): read `workspace/PRD.md` in full (464 lines), all 20 implementation files, and all 9 `test_helpers/` modules. The known false-alarm traps are already pre-averted by the helpers: `api_client.canonical_instant()` normalises sub-second width; `assertions.validate_unpaginated()` exists alongside `validate_paginated`; `factories._merged()` applies overrides onto the built dict (no duplicate-kwarg `TypeError`) and carries money as integer-cent JSON numbers; `test_users.headers_with_empty_user_id` uses `""` not `" "`; the `clock` fixture parks the logical clock at `2026-08-01T08:00:00.000Z`, inside the 08:00–17:00 window `build.case_authorized` approves; and `fixtures.Builder` phases are non-self-invalidating (e.g. `partnership_active` records bonding *before* walking the status ladder, and the OCC builders re-read `version` immediately before each guarded write).

**Hard constraints honoured:** storage is in-memory only — `store.py` `Store.reset()` builds 10 empty dicts, nothing is seeded/preloaded/hardcoded, and there is no SQLite file, JSON dump, or `/tmp` cache, so `start.sh` re-invocation wipes all state. Never ran `pkill`/`killall` or any pattern/unscoped PID kill, never started a manual probe server, left nothing running, did not touch `worklog.md`, did not read the SCAFFOLD files or any sibling `task_*/`, and removed only `.scratch/step7` (which turned out to be unused).

**Latent PRD/impl divergences noted but deliberately NOT changed** (no failing, faithful, PRD-covered test exercises them; the cardinal rules forbid touching the implementation without one). Flagged for the orchestrator's awareness only:
- `routes_participants.py` — `exit_participant` checks `ERR_PARTICIPANT_HAS_ACTIVE_PLACEMENT` (band 12) before stage legality `ERR_PARTICIPANT_INVALID_STATE` (band 8); for a `PLACED` participant both hold and band 8 should win.
- `routes_partnerships.py` — `list_partnership_openings` resolves the path (band 4) before validating pagination (band 3), so a bad `limit` on a nonexistent partnership yields 404 rather than 422.
- `record_release` / `separate` evaluate state gates before the date-vs-clock `ERR_VALIDATION`; the PRD's band-3-vs-band-8 ordering is ambiguous there.
- No user registry exists (seeding is forbidden), so the PRD's "non-empty but unregistered user → `ERR_UNAUTHENTICATED`" rule is not uniquely implementable; `app.py` accepts any non-empty id and also treats whitespace-only `X-User-ID` as empty.
- The `SUPERSEDED` value of `release_plan_status` is never written; the PRD mentions it only as "reserved for exactly that displaced-plan condition".

Orchestrator verification (independent of the subagent's claim, per the known "clean sweep with no artifacts" failure mode): all 8 `results.$i.json` exist on disk and were parsed directly — each reports `passed=122 total=122`, each carries exactly 122 entries in `tests[]`, and `Counter(status)` is `{'passed': 122}` for all 8. Top-level keys are `duration_seconds, errors, failed, passed, skipped, tests, total`; per-test keys are `name, file, status, duration_seconds, error_message`. The sweep artifacts are real.

## Step 8: Finalize PRD — SKIPPED — 2026-09-06T07:39:00.000Z

Skip condition met exactly as the skill defines it: Step 7 exited on its first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — zero iterations beyond the baseline. There is therefore no `<step_7_diff>` to hand off and no Step-7-identified PRD silence to patch, so `PRD_FINALIZED.md` is not produced and Step 9 will start from `PRD.md`. (Per the skill, a byte-identical finalized PRD would be legitimate here; producing none at all is the documented behaviour for a zero-fix Step 7.)

The five latent divergences Step 7 flagged are NOT lost — they are exactly the class of residual silence/mismatch Step 9's full PRD-vs-implementation scan exists to close, and they have been handed to Step 9 as explicit (non-exhaustive) starting hints on top of its own exhaustive walk.

## Step 9: Complete PRD — 2026-09-06T09:05:00.000Z

Step 9 was deliberately run as FOUR sequential passes over one shared `workspace/PRD_COMPLETED.md`, partitioned by implementation module, rather than as a single subagent. Rationale (written into the log as the skill requires for judgement calls made without a user to consult): the implementation is 3581 lines across 20 modules and the PRD is 464 very long lines / 117 KB. A single agent asked to walk all of it exhaustively cannot hold both, and the documented failure mode is that it emits a `PRD_COMPLETED.md` byte-identical to its input — i.e. the scan silently never ran. Partitioning by module bounds each pass's reading load; pass 1 owns the `cp` and no later pass re-copies; a final reconciliation pass exists because partitioned passes reliably produce cross-pass contradictions and locally-true-but-globally-false universal claims that none of them can see on its own.

Partition:
- Pass 1 — `app.py`, `store.py`, `errors.py`, `envelope.py`, `validation.py`, `common.py`, `routes_participants.py`, `routes_supervision.py`. Owned the `cp` (verified `PRD_FINALIZED.md` absent, so copied `PRD.md`). **40 edits: 30 ambiguity-pins, 10 mismatch-revisions.** 464/117,535 → 466/129,490.
- Pass 2 — `domain.py`, `ledger.py`, `counters.py`, `matching.py`, `cascades.py` (the calculation/derivation/cascade engine). **12 edits: 5 ambiguity-pins, 7 mismatch-revisions.** → 466/134,479.
- Pass 3 — `routes_partnerships.py`, `routes_sessions.py`, `routes_grants.py`, `routes_placements.py`. **19 edits: 13 ambiguity-pins, 6 mismatch-revisions.** → 466/140,242.
- Pass 4 — reconciliation. Audited all 33 diff hunks / 71 committed loci against implementation source; re-derived 63 as correct with no change; **corrected 8 loci and closed 1 adjacent silence (9 edits).** → 466/141,868.

Totals: **80 edits, 48 ambiguity-pins + 23 mismatch-revisions + 9 reconciliation corrections.** `PRD.md` 464 lines / 117,535 chars → `PRD_COMPLETED.md` 466 lines / 141,868 chars (+2 lines, +24,333 chars, +20.7%). Nearly every edit was in-paragraph, which is why the line count barely moved; only one new paragraph was added (a §2.5 index of the endpoints that locally override the refusal ladder).

Highest-value mismatch revisions across the four passes:
- §2.1 / §2.5 band 1 — the PRD's "non-empty but unregistered user → `ERR_UNAUTHENTICATED`" rule is not implementable, because seeding entity data (including a user registry) is forbidden by the benchmark. Revised to what `app.py` does: authentication is a non-emptiness test only, whitespace-only counts as empty, and an unrecognised identifier is not by itself a refusal.
- §3.9 — exit order is already-`EXITED` → active-placement → stage legality, so the active-placement bar pre-empts the stage-legality bar (inverting the PRD's stated band order). §2.5's list of local ladder departures was raised to five, and pass 4 verified the count "five" by scripted enumeration rather than accepting it.
- §3.2 — `release_plan_status` value `SUPERSEDED` is never written; `record_release`'s future-date `ERR_VALIDATION` is evaluated after both state gates.
- §2.8 — a suspension does NOT void open funding requests; only an exit does.
- §3.8 — an `APPROVED` decision lands in `DEFERRED` whenever `available_cents < total_charge_cents` whatever the posture reads, not only when `RESTRICTED`; and at most one deferred request is promoted per *ledger recomputation*, not per triggering write (pass 4 then fixed §3.3, which still said "per write", and re-verified both of the PRD's worked 80,000/5,000 queue examples still read correctly).
- §3.7 — the `ERR_SUBSIDY_CAP_EXCEEDED` gate compares the uncapped raw sum, not the already-capped stored value (which could never exceed its own cap); the money columns are frozen on `SEPARATED`/`DECLINED` while `schedule_compliance` still recomputes; there is NO participant-suspension gate on shift creation.
- §2.4 — pass 1's claim that the logical-clock reader enumeration is "exhaustive" was itself false; pass 4 replaced it with a non-closing list naming the further readers, keeping the wall-clock audit columns as the stated exception.
- §2.5 band 10 — `ERR_BONDING_CLAIM_NOT_ELIGIBLE`, which pass 3 left unbanded on the theory that no co-occurrence is reachable, was pinned to band 10 after pass 4 disproved that reasoning from source.
- §2.5 — a structural departure no per-endpoint claim had captured: the three nested list paths resolve the parent before reading pagination, so a bad `limit`/`offset` under a missing parent reports band-4 not-found rather than band-3 validation.

Pass 4's cross-pass adjudication produced no unresolved contradictions: passes 2 and 3 each reported "CONTRADICTIONS FOR PASS 4: none", and the two conflicts pass 4 did find were introduced by pass 1 (the §2.4 exhaustiveness claim, the §2.5 band-1 self-contradiction) and by pass 3 (an over-reaching closing universal), all three settled against implementation source rather than by splitting the difference.

Residual items consciously left, with justification: the exact `match_breakdown` sub-object key set, and `_seq`-based tie-breaking described functionally as "insertion order" rather than named. Every claim the four passes inserted is derivable from `implementation/`, and no two sections contradict each other on refusal precedence, promotion counts, clock readers, or target-set narrowing.

Orchestrator verification (independent of every subagent's claim): `PRD_COMPLETED.md` is 466 lines / 141,868 chars and is NOT byte-identical to `PRD.md` (`cmp` differs; 112 changed lines in `diff`) — so the scan demonstrably ran. §4 still has exactly 61 endpoint rows, §5 exactly 59 error rows, and the document contains exactly 59 distinct `ERR_*` identifiers. Top-level headings remain §1–§5 (5 headings, no new sections). The file still ends on the final `| ERR_GRANT_FUNDS_INSUFFICIENT | 409 |` row — not truncated. `grep -ic "scaffold|harder than expert|expert_plus"` → 0, so no generator-side or difficulty-directive leakage. Step 9 touched no test or implementation file, so Step 7's green 8-round sweep artifacts remain valid; `results.1.json`–`results.8.json` are retained in `workspace/implementation/`. Stray `SWEEP_DONE` sentinel, `__pycache__` directories and the empty `.scratch/` parent removed.

## Pipeline complete — 2026-09-06T09:05:00.000Z

All nine steps done. Step 8 legitimately skipped (zero-fix Step 7). Final deliverables: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 modules, 2636 lines), `test_suite/` (18 files + conftest, 6991 lines, 122 tests), `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (20 files, 3581 lines, 61 endpoints, 59 error codes) and `workspace/implementation/results.{1..8}.json` all at 122/122.
