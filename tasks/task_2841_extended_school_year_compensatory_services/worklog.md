## Step 1: Create task directory — 2026-09-05T05:00:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2841_extended_school_year_compensatory_services and its workspace/ subdirectory. Index 2841 was pre-assigned by the orchestrating command; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-05T06:24:00.000Z

Scaffold generation for task 2841 is complete. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_2841_extended_school_year_compensatory_services/`.

**Lint verdict (verbatim, final run):**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2841_extended_school_year_compensatory_services/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2841_extended_school_year_compensatory_services/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2841_extended_school_year_compensatory_services/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    47
  §1.1 entities declared:     12
  §1.8 instances scanned:     21
  §1.9 instances scanned:     44
  Calls scanned (§1.8+§1.9):  815

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Worklog summary**

- `SCAFFOLD.yaml` (2679 lines, §1.0–§1.7): 12 entities, 11 state machines / 44 transitions, 9 calculations, 36 validation rules (priority-ordered), 3 priority_conflict_pairs, 2 concurrency rules (`assignment-create-stale-commitment`, `makeup-create-stale-award`), 47 endpoints, 47 error codes, 6 roles, 17 FKs. Profile: Ledger reconciliation × Multi-party negotiation; layers `dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers`; `entity_topology: flat`, `state_machine_shape: cyclic`, `role_model: segregation_of_duties`, `consistency_model: immediate`. Contains neither design key.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2414 lines): single key `scaffold_difficulty_design`, all 9 §0.5 rules, 21 instances (>=2 per rule), every instance with structured `setup_api_calls` and pre-computed literal asserts.
- `SCAFFOLD_CORNER_DESIGN.yaml` (2854 lines): single key `scaffold_corner_design`, all nine guide sections, 77 instances = 44 full `test_recipe`s + 33 `excluded_because` stubs. Per section: entities 10, state_machines 12, calculations 9, validations 5, endpoints 3, errors 27, rbac 5, cross_cutting_layers 5, consistency_model 1.

**Coverage audit**

- Error catalogue: all 47 codes are triggered by at least one real (non-stub) recipe across §1.8+§1.9 — verified programmatically. Batched instances cover the ten path-`{id}` 404s and the body-FK-only `ERR_RUN_NOT_FOUND` (no run has a GET-by-id path). The 13 codes owned by §1.8 (state, fiscal, credential/role, window/overbooking, stay-put, temporal-overlap, indirect-overage) are cited as stubs, not duplicated.
- Names: 0 duplicates within §1.9 and 0 collisions with the 21 §1.8 names; every `excluded_because.difficulty_instance` resolves to an existing §1.8 instance name; no stub carries a `test_recipe`, no real instance lacks one.
- Cross-cutting: both `concurrency_rules` have OCC 412 recipes (stale + re-read + success), and each declared complexity layer plus the `immediate` consistency model has an instance or stub.

**Fixes applied during generation**

1. Six sub-resource GETs were renamed to the spec's canonical `{id}` parent parameter (`/esy/students/{id}/eligibility-determinations`, `.../due-process-records`, `/esy/programs/{id}/fund-allocations`, `.../transportation-runs`, `/esy/providers/{id}/provider-assignments`, `/esy/service-commitments/{id}/provider-assignments`) — this was the sole cause of 6 `FK_REVERSE_UNREACHABLE` violations; references in §1.3/§1.7 prose were updated to match.
2. Self-consistency: stay-put record types unified to `{COMPLAINT, DUE_PROCESS_HEARING}` across three descriptions; `transport_run_occupancy` seat filter fixed to `status IN {PLANNED, ASSIGNED, ACTIVE, SUSPENDED}`.
3. Stripped the `Generate task harder than expert level!` directive line from `scenario:` so it cannot leak into PRD.md (known hazard); the domain sentence is otherwise verbatim.
4. `.scratch/` removed; no stray files left in the task dir (only the three artifacts plus the pre-existing `worklog.md` and `workspace/`).

**Orchestrator verification:** all three files present (2679 / 2414 / 2854 lines); `grep -rn "harder than expert"` over the task dir returns nothing — difficulty directive did not leak.

## Step 3: Copy shared files — 2026-09-05T06:25:00.000Z

Copied ./INSTRUCTION.md to tasks/task_2841_extended_school_year_compensatory_services/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T06:37:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2841_extended_school_year_compensatory_services/workspace/PRD.md`.

**Final stats:** 491 lines; ends at a real section boundary — last line is the final §5 error table row `| `ERR_SUPPLANT_RESTRICTION` | 422 |`. No audit footer written into PRD.md. Scratch dir removed. The two design-index files were never opened.

**Section list**
- §1 Introduction (3 paragraphs — pain point -> ledger framing -> three shaping constraints)
- §2 (11 subsections): 2.1 Acting Users and RBAC · 2.2 API Response Structure (verbatim, byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination and List Ordering · 2.4 Resource Identity, Timestamps, and the Version Counter · 2.5 The Logical Clock · 2.6 Path Resolution for Nested Reads · 2.7 Rejection Precedence · 2.8 Stale-Version Protection · 2.9 Money in Cents and the Fund Charge Waterfall · 2.10 Minute Arithmetic and Rounding Discipline · 2.11 Ledger Recomputation and Cascade Discipline
- §3 (9 subsections): 3.1 Student Records and the Running Minute Ledger · 3.2 ESY Eligibility: Regression, Recoupment, Parent Agreement · 3.3 The Shortened Summer Calendar and Its Transportation Routes · 3.4 Service Commitments and the Pinned Minute Plan · 3.5 Provider Roster, Budget Codes, and Staffing Assignments · 3.6 Running the Session: Service Logs, Day Cancellations, Voids · 3.7 Compensatory Award Calculation and the Negotiation Cycle · 3.8 Makeup Delivery, Forfeiture, and the Delivery Dimension · 3.9 Due Process, Stay-Put Protection, and the Documentation Packet
- §4 Endpoint Definitions (47 rows, 4 columns) · §5 Error Code Catalogue (47 rows, 2 columns)

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 116 required, 116 present, 0 missing
- endpoints[].request_body: 86 required, 86 present, 0 missing
- endpoints[].query_params: 14 required, 14 present, 0 missing
- endpoints[].path_params: 12 required, 12 present, 0 missing
- skill_probes sub-fields + common fields (id/created_at/updated_at/version): 9 required, 9 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 36 checked, 36 expressed in prose (§2.7 numbered normative order, each with its applies_to scope enumerated), 0 missing
- priority_conflict_pairs: 3 checked, 3 expressed (state-beats-fiscal, safety-beats-referential, temporal-beats-fiscal), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_commitment_version / expected_award_version + ERR_STALE_*_VERSION + HTTP 412), 0 missing
- state_machines[].transitions: 44 checked across 11 machines/dimensions, 44 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed in prose (per-week-then-sum rounding, 1-dp regression comparisons, ceil projection, 15-minute unit rounding, 5-step waterfall with no re-selection), 0 missing
- validations[] conditions: 36 checked, 36 matchable to error_id, 0 missing
- endpoints[].side_effects / applies_to: 47 endpoints checked, all side effects expressed, 0 missing
- entities[].fields[] structured content: 116 checked, all defaults/enums/ranges/provenance reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked (determination parent-response AGREE/OBJECT/WITHDRAW; award parent-response AGREE/DISPUTE/DECLINE with the 2-round threshold fork; MakeupSession SCHEDULED->{DELIVERED,NO_SHOW_PARENT,CANCELLED_DISTRICT}; program CLOSED from OPEN vs from PLANNING; PROBE_BASED vs TEAM_JUDGMENT; MINUTE_FOR_MINUTE vs QUALITATIVE_BENEFIT), 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 976
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Coverage notes worth flagging to the pipeline**
- All 47 error IDs, all 6 role names, all 60 state values and every enum value appear verbatim in backticks. `WITHDRAWN` initially existed only inside a state-pair token; a standalone determination-status enumeration was added to §3.2 to fix it.
- Scaffold internal inconsistency: `covered_total_minutes` is defined two ways (entity field description uses ISO weeks in `[effective_from, effective_to]` containing an instructional date; `fund_charge_waterfall` step 1 uses `program.instructional_week_count`). The PRD states the entity-field form as normative in §3.5 and has §2.9 defer to it, so a PRD-only reader gets one reading.
- Zero fuzzy/approximating words (the 3 regex hits were all "turnaround"). No pseudocode operators anywhere; all thresholds are spelled in words with inclusivity preserved (`PROBE_BASED` inclusive vs `TEAM_JUDGMENT` strict).
- §2.7 is the deliberate home for `validations[].applies_to` breadth, which keeps §3 free of a concentrated rejection block while still uniquely determining every scope.

**Orchestrator verification:** `tail -25` confirms PRD.md terminates on a complete final error-table row (real section boundary, not mid-sentence) — no silent truncation. `grep` for the difficulty directive / SCAFFOLD / test_recipe over PRD.md returns nothing.

## Step 6: Generate implementation — 2026-09-05T07:11:00.000Z

Implementation complete.

## Files (all under `workspace/implementation/`, 2970 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | guarded `pip install` + `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `app.py` | 76 | blueprint registration, `ApiError`/404/405/400/500 envelope handlers, threaded `app.run` |
| `errors.py` | 109 | all 47 `error_id` -> HTTP status pairs from PRD §5 |
| `store.py` | 98 | in-memory dicts, logical clock pinned at `2026-08-01T00:00:00Z`, `new_record`/`touch`/`creation_order` |
| `envelope.py` | 91 | success/error envelopes, `req_` + 20 alnum request ids, limit/offset pagination |
| `auth.py` | 69 | 6 roles, `endpoint()` decorator (checks 1-2 + global lock), guardian/provider scope guards |
| `validate.py` | 143 | shape validators (check 7) |
| `calcs.py` | 322 | rounding, program calendar, regression/recoupment, minute plan, award minutes, proposal band, 5-step fund waterfall |
| `ledgers.py` | 187 | full-recomputation ledgers, lazy lapse, forfeiture, seat/encumbrance reversal |
| `resolve.py` | 56 | path/body FK resolution -> the 12 not-found codes |
| `serialize.py` | 46 | public projection + the 19-key due-process packet |
| `routes/` (13 modules) | 1762 | clock 50, students 88, determinations 184, programs 224, providers 69, fund_allocations 72, transportation 74, commitments 155, assignments 163, service_logs 135, awards 209, makeup 268, due_process 71 |

**47 endpoints** — exactly matching the PRD §4 table (19 reads, 27 writes, 1 clock).

## Notable design decisions
- **Precedence**: PRD §2.7's 36-step order is implemented literally and uniformly; shape (7) precedes state (9) everywhere, `ERR_NO_COMPENSABLE_MINUTES` (25) masks `ERR_DUPLICATE_AWARD` (30), credential (12) precedes provider-active (13), state (9) precedes stay-put (11) precedes segregation (15) precedes band (26).
- **Booking a session against a LAPSED award** returns `ERR_INVALID_STATE` (per check 9 and §3.8's booking paragraph), not `ERR_MAKEUP_OUTSIDE_WINDOW`; the two agree in practice since a lapse also closes negotiation.
- **Version accounting**: each ledger recompute folds with the state advance it causes into one bump. A fulfilling delivery = award +2 (recompute/advance, then `AGREED->CLOSED`) and student +2; a reopening void = award +2 (recompute/`FULFILLED->IN_PROGRESS`, then `CLOSED->AGREED`) and student +1; `NO_SHOW_PARENT` bumps the student only when forfeiture fires; `CANCELLED_DISTRICT` bumps no student.
- **Lazy lapse** is applied only on requests whose path or body names the award (per §2.5), i.e. not on `/makeup-sessions/{id}/log-outcome` and not on list reads.
- `log-outcome` gates per-outcome role: `VOIDED` is ComplianceOfficer-only, the other three are RelatedServiceProvider-only (`ERR_ROLE_NOT_PERMITTED`), with check 4 provider-ownership run before path resolution.
- `Decimal` + ROUND_HALF_UP throughout; money is integer cents; instants carry exactly 3 fractional digits; storage is process memory with zero seeding.

## Smoke test
Two scripted end-to-end passes on `PORT=18841` (server killed by port afterwards; port confirmed free). **Pass 1: 0 failures** across 40 calls — determination -> finalize -> program -> allocation -> provider -> run -> commitment -> assignment -> logs -> day cancellation -> award -> propose/dispute/re-propose/agree -> stale-version 412 -> booking -> overbook 422 -> stay-put block 409 -> delivered -> void -> packet -> clock-driven lapse -> pagination/auth/404 negatives. **Pass 2: 1 "failure" that was a defect in my own test** (a role-mismatch probe used a weekday outside the program calendar, so `ERR_INVALID_REQUEST` correctly masked check 14); the other 45 calls passed, covering supersession, `CANCELLED_DISTRICT` deadline +30d, double no-show forfeiture, MEDIATION escalation, arbitration, service-log void, allocation freeze/close, and program-close cascade. Verified arithmetic by hand: local indirect 14.5% (600x100 -> 68700), federal 8% (360x120 -> 46656), `QUALITATIVE_BENEFIT` 260x1.25 -> 330 at the 15-minute unit, and exact `available_cents` restoration on both reversals. Full byte-compile of the tree passes.

## Step 5: Generate unit tests — 2026-09-05T07:47:00.000Z

Step 5 is complete. Both stages landed at the task root, and the coverage/citation audit is clean.

## Files

`/home/ubuntu/github/CodingPRD/tasks/task_2841_extended_school_year_compensatory_services/test_helpers/` (9 files, 2,586 lines)
- `__init__.py` 50, `types.py` 383, `constants.py` 136, `api_errors.py` 116, `test_users.py` 80, `api_client.py` 400, `factories.py` 345, `assertions.py` 496, `fixtures.py` 480

`/home/ubuntu/github/CodingPRD/tasks/task_2841_extended_school_year_compensatory_services/test_suite/` (9 files, 5,269 lines)
- `conftest.py` 48
- `test_01_eligibility_determination.py` 473 (11 tests)
- `test_02_platform_conventions.py` 803 (17)
- `test_03_program_calendar_and_transportation.py` 535 (10)
- `test_04_service_commitments_and_minute_plan.py` 364 (7)
- `test_05_staffing_assignments_and_funds.py` 1013 (15)
- `test_06_service_logs_and_award_calculation.py` 643 (10)
- `test_07_makeup_delivery_and_award_dimensions.py` 902 (12)
- `test_08_due_process_governance_and_fiscal_limits.py` 488 (6)

Nothing was written under `workspace/`.

## Coverage

- 88 test functions, all tagged with exactly one trailing `Design:` line; `pytest --collect-only` collects 101 cases (13 extra from parametrized tests in files 01-03).
- Difficulty (queue A): 21/21 instances, every one with >=2 tests.
- Corner (queue B): 44/44 non-stub instances covered >=1 (the other 33 of 77 carry `excluded_because:` and were not translated).
- Citation audit (`.scratch_tests/check_citations.py`): "all citations verbatim, all tags resolve" — every double-quoted span in every docstring is a literal PRD substring, no untagged/dual-tagged tests, no dangling tags.
- `pyflakes` clean on `test_suite/`.

## PRD-first filter: design assertions overridden or dropped

No instance was skipped outright, but these design-supplied values contradicted the PRD and the PRD-derived value was asserted instead:

- HTTP statuses: the design asserts 409 for `ERR_PROVIDER_CREDENTIAL_EXPIRED`, `ERR_PROVIDER_ROLE_MISMATCH`, `ERR_MAKEUP_OUTSIDE_WINDOW` and `ERR_OVERBOOKED_MAKEUP_MINUTES`; PRD §5's table says 422 for all four.
- `makeup_outside_delivery_window_beats_overbooked_minutes` asserts `remaining_owed_minutes == 0` after booking 85 minutes; PRD §3.8 defines remaining as agreed less delivered less forfeited, so scheduling cannot move it — asserted 85 (this matches the sibling instance `makeup_booking_requires_agreed_award`, which says the same thing).
- `due_process_packet_computed_read_aggregates_the_documentation_fields` asserts `excluded_log_count == 0` for the canonical three-log set; PRD §3.7 counts the `MISSED_PARENT` log as excluded — asserted 1.
- `provider_weekly_slots_use_half_open_intervals_and_date_intersection` asserts `covered_total_minutes == 1374` for an assignment effective 2027-06-14..2027-06-30; the PRD multiplies weekly minutes by distinct ISO weeks in the range (3) — asserted 687 / 103050 / 8244 / 111294.
- `owed_minutes_conservation_survives_a_voided_delivery` asserts the voided session's own `minutes_delivered == 0`, `charge_cents == 0`, `charged_fund_source == null`; the PRD only specifies the reversal of the award/student/allocation ledgers, so those three sub-assertions were dropped (instance still covered).
- `resolved_at` equality was asserted as a prefix match on the clock date-time rather than byte equality, to stay independent of sub-second ISO width.

**Orchestrator verification:** `test_helpers/` and `test_suite/` are at the task root; `find workspace -type d -name "test_*"` returns nothing (no stray copies under workspace/). 7755 total lines across both dirs.

## Step 7: Run tests and iterate — 2026-09-05T07:57:00.000Z

Clean on the first sweep. Verified artifacts on disk:

```
results.1.json .. results.8.json  (all 8 present, each 101 passed / 101 total, 0 failed, 0 errors, 0 skipped)
```

Each round carried full per-test detail (101 entries, all `passed`), and the rounds genuinely ran concurrently (~179s wall each, launched together under `setsid nohup`), so this is not an early-exit or an empty-collection artifact.

## Summary

**Iterations run:** 1 (one 8-round parallel sweep, all rounds green).

**Tests deleted:** none. No test failed in any of the 8 rounds, so no test entered the diagnostic protocol and no PRD-silence / unique-derivability deletion was warranted.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:** none required.

## What I verified while the sweep ran

Since there were no failures to diagnose, I spent the sweep window auditing the artifact for the classic failure shapes so a green sweep isn't a false green:

- **Canonical calendar/plan constants are arithmetically correct.** I independently recomputed the canonical program (2027-06-14 -> 2027-07-23, MON-THU, blackouts 2027-06-30 and 2027-07-05) and confirmed `instructional_days_count == 22`, `instructional_week_count == 6`, per-week prorated minutes `[250, 250, 188, 188, 250, 250]` -> `planned_total_minutes == 1376`, `weekly_minutes_committed == 229`, `daily_minutes == 57`, and heaviest weekly daily load 62.67 < the 90 cap. These match `test_helpers/constants.py` exactly, so the widely-shared fixture chain is not silently mis-pinned.
- **No money-as-string or date-only-vs-instant fixture bugs.** `test_helpers/factories.py` sends all cents as Python ints and all clock values as full ISO-8601 instants (`CLOCK_PRE_SESSION = "2027-06-01T00:00:00Z"`), with dates only where the PRD declares `YYYY-MM-DD`.
- **No `validate_success` double-unwrap.** `test_helpers/fixtures.py` uses the runner's `get_success_data` uniformly and unwraps `data` exactly once.
- **Timestamp width is PRD-exact.** `implementation/store.py:iso_instant` renders exactly three fractional digits, so the ISO sub-second-width class of phantom failures cannot fire.
- **Storage is in-memory only and unseeded.** `implementation/store.py` holds plain dicts keyed by id with `reset()` clearing them; no SQLite, no disk dump, no startup seeding.
- **`start.sh` is contention-safe** — it pip-installs only when Flask is missing, which matters because it is re-invoked before each of the 101 per-test server boots x 8 concurrent rounds.

I did not touch `worklog.md`.

**Orchestrator re-verification (independent of the subagent's claim):** `ls` shows 8 results files all written 07:51; parsing each with json.load reports `passed=101, failed=0, errors=0, skipped=0, total=101` for every round 1-8. The clean sweep is real.

## Step 8: Finalize PRD — SKIPPED — 2026-09-05T07:58:00.000Z

Skip condition met per the skill: Step 7 exited on its first 8-round sweep with 0 iterations beyond baseline, 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. With no Step 7 diff there is no site of demonstrated PRD-silence or PRD/impl mismatch for Step 8 to patch, and its `<step_7_diff>` hand-off would be empty. `PRD_FINALIZED.md` is therefore deliberately not produced, and Step 9 will start from `PRD.md`. (A byte-identical PRD_FINALIZED.md is a legitimate outcome of a zero-fix Step 7, but the skill directs an outright skip in this case, so no file is written.)

## Step 9: Complete PRD — 2026-09-05T08:20:00.000Z

Run as **three sequential module-partitioned passes over one shared `PRD_COMPLETED.md`** (pass 1 performed the `cp` bootstrap from `PRD.md`, since Step 8 was skipped and no `PRD_FINALIZED.md` exists; passes 2 and 3 were explicitly forbidden from copying and edited in place with the Edit tool only). Partition by implementation module so no two passes contend for the same PRD prose:

- **Pass 1** — app.py, errors.py, store.py, envelope.py, auth.py, validate.py, resolve.py, serialize.py, routes/clock.py, students.py, determinations.py
- **Pass 2** — calcs.py, ledgers.py, routes/programs.py, transportation.py, commitments.py, providers.py, fund_allocations.py
- **Pass 3** — routes/assignments.py, service_logs.py, awards.py, makeup.py, due_process.py

### Pass 1 (platform core) — 14 edits: 12 ambiguity-pins, 2 mismatch-revisions
- §2.1 — insert — ambiguity — a header holding only whitespace counts as empty for `ERR_UNAUTHENTICATED` — auth.py:38
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9`; `api_request_timestamp` reads the logical clock, not wall time — envelope.py:19,26
- §2.3 — insert — ambiguity — pagination values must be canonical decimal (empty, leading `+`, leading zeros, non-digits rejected; whitespace trimmed) — envelope.py:63-83
- §2.3 — insert — ambiguity — creation order is the stable tie-break on equal `created_at` and settles residual ties in the four deviating orders — store.py:92-94
- §2.5 — insert — ambiguity — accepted `current_utc` grammar (optional seconds, 1-9 fractional digits, `T` or space, optional `Z`/`+-HH:MM` normalized to UTC, bare value read as UTC), unparseable/non-string -> `ERR_INVALID_REQUEST`, backwards moves allowed, 200 with empty `data` — routes/clock.py:14-50
- §2.6 — insert — ambiguity — a body identifier present but non-string is a shape violation, not a dangling reference — resolve.py:45-56
- §2.7 check 3 — revise — **mismatch** — flat "3 before 5" holds only for the two student-scoped paths; the four record-scoped guardian operations resolve before ownership, so a bad id yields 404 — auth.py:60-69
- §2.7 check 7 — insert — ambiguity — absent/empty body = empty JSON object; non-object body and unparseable JSON both -> `ERR_INVALID_REQUEST` 422 — validate.py:22-28, app.py:55-59
- §5 intro — insert — **mismatch** — impl also emits `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500), and tolerates trailing slashes — app.py:36,45-66
- §3.1 — insert — ambiguity — duplicate `student_number` -> `ERR_INVALID_REQUEST` 422, tested after all other field shape checks — routes/students.py:38-39
- §3.2 — insert — ambiguity — fixed pre-analysis shape of a DRAFT determination (three counters + `objection_round_count` = 0, `SUFFICIENT`, `PENDING_DATA`, three nulls) — routes/determinations.py:88-103
- §3.2 — insert — ambiguity — mastery percentages may be fractional, day/trial counts must be integers; probes normalized to exactly five properties, extras discarded — routes/determinations.py:25-71
- §3.2 — insert — ambiguity — a supplied replacement array is what the two-probe precondition measures, shape-checked before the `DRAFT` guard, stored only after both guards pass — routes/determinations.py:120-133
- §3.2 — revise — ambiguity — `parent_comment` written unconditionally, storing null when omitted and erasing an earlier round's comment — routes/determinations.py:150,155

### Pass 2 (calc / calendar / fiscal core) — 16 edits: 12 ambiguity-pins, 4 mismatch-revisions
- §2.9 step two — revise — mismatch — `ERR_FUND_FROZEN` also covers a program with **no** allocations at all — calcs.py:293-296
- §2.9 step two — insert — ambiguity — creation order settles a `created_at` tie between allocations of the same `fund_source` — calcs.py:284-285
- §2.10 — revise — mismatch — "Three places deviate" -> four; the heaviest-week daily-load quotient is compared unrounded — calcs.py:202-205
- §2.11 — insert — ambiguity — the award ledger pass also rebuilds `parent_no_show_count` — ledgers.py:65-66
- §3.3 — revise — ambiguity — program read also returns the `cancelled_dates` array — programs.py:79 / serialize.py:5
- §3.3 — insert — ambiguity — `target_status` enum over all four names; `PLANNING` target, same-status target and close-from-`STAFFING_LOCKED` all -> `ERR_INVALID_STATE` — programs.py:144-170
- §3.3 — insert — mismatch — close-from-`OPEN`: a run shared by several departing commitments is recomputed once (one `version` bump), and no student ledger/`version` moves — programs.py:117-136
- §3.3 — insert — ambiguity — close-from-`PLANNING`: already-`TERMINATED` commitments re-touched; assignments stay `ACTIVE` with encumbrances intact; no seat or student recompute — programs.py:162-165
- §3.3 — insert — ambiguity — a run aimed at a `CLOSED` program -> `ERR_INVALID_STATE` — transportation.py:32-33
- §3.3 — insert — mismatch — the seat check recounts seat-holding commitments live rather than reading stored `seats_committed` — commitments.py:53-57
- §3.4 — insert — ambiguity — body ids resolved `student_id` -> `program_id` -> `transportation_run_id` — commitments.py:31-33
- §3.4 step four — insert — ambiguity — the per-week daily-load quotient keeps its exact fraction; a load exactly on the cap passes — calcs.py:202-206
- §3.4 — insert — ambiguity — commitment `target_status`: enum first, `PLANNED`/`COMPLETED` -> `ERR_INVALID_STATE`, `ComplianceOfficer` requesting `ACTIVE` -> `ERR_ROLE_NOT_PERMITTED` ahead of state guards — commitments.py:112-153
- §3.4 termination — insert — ambiguity — touched allocation and provider each bump `version`; student ledger recomputed with `version` +1 — commitments.py:141-151, ledgers.py:158-179
- §3.5 — insert — ambiguity — provider PATCH reads only the three fields, null = omitted, an empty update still returns 200 and bumps `version` — providers.py:42-52
- §3.5 — insert — ambiguity — allocation PATCH takes a required `status` field; bad value -> `ERR_INVALID_REQUEST`, same-state target -> `ERR_INVALID_STATE` — fund_allocations.py:55-68
- §3.6 day cancellation — insert — ambiguity — `cancellation_reason` is required and constrained to the six miss reason codes — programs.py:182

### Pass 3 (assignments / logs / awards / makeup / due process) — 24 edits: 20 ambiguity-pins, 4 mismatch-revisions
- §2.7 check 4 — insert — ambiguity — provider-ownership check skipped when the id resolves to nothing (not-found wins); the covering assignment may be in any status — routes/makeup.py:150, routes/service_logs.py:33
- §3.5 — insert — ambiguity — assignment body-id order `provider_id` -> `commitment_id`; weekday-membership and session-window tests are check-7 `ERR_INVALID_REQUEST`, ahead of state and version — routes/assignments.py:35,54,58
- §3.5 — revise — mismatch — **every** other `ACTIVE` assignment on the commitment supersedes (not one incumbent), in creation order — routes/assignments.py:135
- §3.5 — revise — mismatch — commitment `version` increments on every release, not only when the `ASSIGNED -> PLANNED` revert fires — routes/assignments.py:162
- §3.6 — insert — ambiguity — service-log body-id order; no commitment- or program-status gate on a manual log — routes/service_logs.py:42
- §3.6 — insert — ambiguity — `PARTIAL` carries no minute constraint of its own — routes/service_logs.py:55
- §3.6 — revise — mismatch — `generated_by` is derived from the acting role, never a client input; `void_reason` starts null — routes/service_logs.py:84
- §3.7 — insert — ambiguity — award body-id order; duplicate scan reads stored `negotiation_status` with no lapse evaluation; fixed post-creation shape — routes/awards.py:38,50,56
- §3.7 — insert — ambiguity — `severity_factor` echoed as a JSON number `1.0`/`1.25`/`1.5` — routes/awards.py:72
- §3.7 — insert — ambiguity — a rejected proposal does not persist the recomputed figures; no 30-minute floor re-check on propose — routes/awards.py:117
- §3.7 — insert — ambiguity — `AGREE` also sets `remaining_owed_minutes`; `delivery_status` stays `NOT_STARTED` — routes/awards.py:149
- §3.7 — insert — ambiguity — neither `DISPUTE` nor `DECLINE` recomputes the student ledger — routes/awards.py:155
- §3.7 — revise — mismatch — arbitration precondition order is stay-put -> segregation -> band; band reads stored `computed_minutes`; sets `remaining_owed_minutes`; deadline is a fresh 180 days — routes/awards.py:180
- §3.8 — insert — ambiguity — makeup body-id order; no collision test on the half-open session interval; booked-session initial shape — routes/makeup.py:42,90
- §3.8 — insert — ambiguity — every later booking also increments the award's `version` — routes/makeup.py:110
- §3.8 — insert — ambiguity — per-outcome role split answers `ERR_ROLE_NOT_PERMITTED`, decided after the enum check and before the state guard; omitted `outcome_note` is not cleared — routes/makeup.py:161
- §3.8 — insert — ambiguity — delivered-branch version arithmetic: award +2 / student +2 when fulfilling, +1 / +1 otherwise — routes/makeup.py:205
- §3.8 — insert — ambiguity — forfeiture repeats on every no-show past the threshold; student ledger recomputed only when a forfeiture fired — routes/makeup.py:221
- §3.8 — insert — ambiguity — the 30-day extension counts from the stored deadline (null stays null); no student recompute — routes/makeup.py:237
- §3.8 — insert — ambiguity — a voided session retains its own minutes/charge/coding; award +1, or +2 when the reopen fires — routes/makeup.py:253
- §3.8 — insert — ambiguity — exactly which operations evaluate the lazy lapse (booking, outcome logging and the award list do not); a lapse on a GET moves award +2 / student +1; `ERR_MAKEUP_OUTSIDE_WINDOW` vs `ERR_INVALID_STATE` split; a void on a `LAPSED` award reopens nothing — routes/makeup.py:59, ledgers.py:95
- §3.9 — insert — ambiguity — record creation leaves `resolution_note`/`resolved_at` null; filing bumps the student regardless of type — routes/due_process.py:31
- §3.9 — insert — ambiguity — the close `status` enum spans only `RESOLVED`/`DISMISSED`, so `OPEN` answers `ERR_INVALID_REQUEST`; an omitted `resolution_note` is not cleared — routes/due_process.py:54
- §3.9 — insert — ambiguity — a dismissal leaves `resolved_at` null; both branches bump the student even for `MEDIATION_AGREEMENT`; the packet is exactly nineteen fields with no `id`/`created_at`/`updated_at`/`version` and evaluates the lapse — routes/due_process.py:63, serialize.py:24

### Whole-scan totals
- `PRD.md` 491 lines / 104,644 chars -> `PRD_COMPLETED.md` 493 lines / 121,886 chars (**+2 lines, +17,242 chars**).
- **54 edits total: 44 ambiguity-pins, 10 mismatch-revisions.** All in-paragraph inserts/revisions; no new sections added.
- No PRD change was needed for the §4 endpoint rows or §5 status codes — every route's method, path, role set and error status already matched the implementation.

**Orchestrator verification:** `diff PRD.md PRD_COMPLETED.md` reports 108 changed lines (NOT byte-identical, so the scan genuinely landed — the classic Step 9 no-op failure mode is ruled out); the file ends on the complete final §5 row `| ERR_SUPPLANT_RESTRICTION | 422 |`; distinctive pass-1 and pass-2 marker phrases are both still present after pass 3, confirming no pass clobbered an earlier one; no difficulty-directive or SCAFFOLD leakage. All scratch dirs removed; the only `worklog.md` in the tree is the canonical one at the task root (no cwd-drift strays under workspace/).

## Pipeline complete — 2026-09-05T08:22:00.000Z

Final state: SCAFFOLD.yaml + both design indices at task root; `test_helpers/` (9 files) and `test_suite/` (9 files, 88 test functions / 101 collected cases) at task root; `workspace/` holds INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, `implementation/` (2970 lines, 47 endpoints) and the 8 passing `results.{1..8}.json` sweep artifacts. `PRD_FINALIZED.md` is absent by design (Step 8 skipped on a zero-fix Step 7).

