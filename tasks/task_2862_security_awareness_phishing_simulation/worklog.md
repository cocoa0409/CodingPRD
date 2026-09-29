# Worklog — task_2862_security_awareness_phishing_simulation

## Step 1: Create task directory — 2026-09-05T08:06:01.298Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2862_security_awareness_phishing_simulation` and `.../workspace` (pre-assigned path; no index allocation performed).

## Step 2: Generate scaffold — 2026-09-05T09:25:30.000Z

All three scaffold artifacts for task 2862 are complete and lint-clean.

Lint verdict (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2862_security_awareness_phishing_simulation/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2862_security_awareness_phishing_simulation/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2862_security_awareness_phishing_simulation/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     77
  Calls scanned (§1.8+§1.9):  950

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2862_security_awareness_phishing_simulation/`):
- `SCAFFOLD.yaml` — 2816 lines / 143 KB, 13 top-level keys, neither `scaffold_difficulty_design` nor `scaffold_corner_design`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 845 lines / 88 KB, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 2341 lines / 224 KB, single key `scaffold_corner_design`

SCAFFOLD.yaml contents: 12 entities, 9 state machines + 1 (Employee parallel axes), 3 concurrency rules (`assignment-create-stale-employee`, `access-consequence-create-stale-employee`, `campaign-schedule-stale-campaign`), 13 calculations, 30 validation rules (priority 1–30), 55 endpoints, 46 errors, 6 roles (ProgramAdmin, CampaignAuthor, CampaignApprover, Manager, Learner, SecurityAnalyst) under `role_model: segregation_of_duties`. Complexity profile: `expert_plus`, layers `[rate_threshold_triggers, cascading_side_effects, dual_variant_calculation, optimistic_concurrency]`, flat topology, cyclic state machines, immediate consistency.

§1.8 — 9 rules / 19 instances: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

§1.9 — 9 sections / 97 instances (77 full recipes + 20 `excluded_because` stubs, every stub citing an existing §1.8 instance by name): entities 13, state_machines 16, calculations 13, validations 17, endpoints 11, errors 9, rbac 8, cross-cutting complexity layers 8, consistency model 2.

Notable fixes made along the way (all in SCAFFOLD.yaml, so the design stays self-consistent): scoped the priority-11 delivery-state check so `ERR_CREDENTIAL_WITHOUT_CLICK` is reachable; rewrote `ERR_REPORT_PERIOD_INVALID`'s condition to remove the priority-3 overlap; added a `CurriculumAssignment ASSIGNED -> ASSIGNED` extension self-loop so pre-deadline grants are legal; and stripped the leaked "Generate task harder than expert level!" directive line from the `scenario` block (it now begins "2862. Security Awareness & Phishing Simulation…"). All 46 catalog errors are covered by at least one triggering instance. No sibling task directories were read at any point.

Orchestrator verification: all three files present (2816 / 845 / 2341 lines); `grep` for "harder than expert" / "expert level" across all three returns nothing — difficulty directive did not leak.

## Step 3: Copy shared files — 2026-09-05T09:28:59.965Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T09:44:00.000Z

PRD generated at `workspace/PRD.md` — **467 lines**.

Section list (25 headings): 1. Introduction; 2. Global Specifications & System-Wide Principles; 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim); 2.3 Pagination; 2.4 Resource Identity, Timestamps and Versioning; 2.5 The Logical Clock; 2.6 Numeric Precision and Rounding; 2.7 Optimistic Concurrency on Reservation-Bearing Writes; 2.8 Path Resolution and the Order of Validation; 2.9 Conserved Ledgers and Compensating Actions; 2.10 Realism Boundaries and Communication Policy; 3. Business Logic & Workflows; 3.1 The Employee Registry and Three Independent State Axes; 3.2 Curriculum Modules and the Creation of Assignments; 3.3 The Learner's Path Through an Assignment; 3.4 Compliance Sweeps: Reminder Cadence, Overdue Marking and the Four-Hop Escalation Chain; 3.5 Manager Response, Deadline Relief and Voiding; 3.6 The Access-Consequence Severity Ladder; 3.7 Pretext Templates and Campaign Governance; 3.8 Reserving and Delivering a Simulation Cohort; 3.9 Interaction Capture, Outcome Classification and the Campaign Scorecard; 3.10 Repeat Clickers, Targeted Coaching and Risk Measurement; 4. Endpoint Definitions (55 rows, 4 columns); 5. Error Code Catalogue (46 rows, 2 columns).

Coverage: 12 entities · 121 entity fields · 55 endpoints · 75 request-body/query identifiers · 23 composite output keys · 30 validations · 13 calculations · 3 OCC rules · 57 state transitions · 46 errors · 6 roles.

Hard Contract reports (verbatim):

```
Field coverage check:
- entities[].fields: 121 required, 121 present, 0 missing
- endpoints[].request_body/input: 75 required, 75 present, 0 missing
- endpoints[].query_params: included in the 75 above, 0 missing
- endpoints composite output keys: 23 required, 23 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 30 checked, 30 expressed in prose (1-12 as an explicit numbered order in 2.8; 13-30 named in ascending evaluation order), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named in 2.7), 0 missing
- state_machines[].transitions: 57 checked, 57 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing
- validations[] conditions: 30 checked, 30 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 55 endpoints checked, all expressed, 0 missing
- entities[].fields[] structured content: 121 checked, 121 reconstructible from prose, 0 missing
- sibling-branch symmetry: 5 groups checked, 0 asymmetric
Status: PASS
```
```
Path purity check (Section 3 only):
- backtick tokens scanned: 1143
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- pipe-table lines in Section 3: 0
Status: PASS
```

Additional verification: §2.2 lines 29–76 `diff`-clean against `section-2.2-response-structure.md` (byte-identical); zero fuzzy quantifiers and zero pseudocode operators remain (one gloss, "roughly six months", was removed from §3.10 so only the exact 180-day window stands); §4 and §5 tables have exactly 4 and 2 columns.

File-completeness confirmation: PRD.md ends at line 467 with the final row of the §5 Error Code Catalogue table (`ERR_COMMUNICATION_POLICY_NOT_ACKNOWLEDGED` | 422) — a complete section boundary, not mid-sentence, with no audit footer and no contract-report block written into the document.

Constraints honoured: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or grepped; no sibling task directory was read; the file was built with one `Write` plus seven heredoc appends (156 -> 192 -> 227 -> 257 -> 301 -> 327 -> 353 -> 467 lines) to avoid the output cap; no `pkill` was run.

Orchestrator verification (anti-truncation guard): `tail -12 PRD.md` confirms the file terminates on the last error-catalogue table row, a real section boundary. `grep` for "harder than expert" / "expert level" / "SCAFFOLD" / "test_recipe" in PRD.md returns nothing — no difficulty-directive and no scaffold leakage. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T10:50:00.000Z

Test-suite generation for task 2862 is complete.

Files written (all at the task root, nothing under `workspace/`)

`test_helpers/` — 2082 lines: `__init__.py` 45, `api_client.py` 245, `api_errors.py` 112, `assertions.py` 342, `constants.py` 312, `factories.py` 242, `fixtures.py` 449, `test_users.py` 96, `types.py` 239.

`test_suite/` — 6129 lines, 115 tests: `conftest.py` 52 (—); `test_01_difficulty_dual_variant_and_formula.py` 518 / 10; `test_02_difficulty_state_machine_and_cascade.py` 394 / 8; `test_03_difficulty_priority_and_boundary.py` 384 / 8; `test_04_difficulty_cross_entity_overlap_invariant.py` 587 / 12; `test_05_corner_entities.py` 510 / 13; `test_06_corner_state_machines.py` 531 / 10; `test_07_corner_calculations.py` 517 / 9; `test_08_corner_validations.py` 731 / 14; `test_09_corner_endpoints.py` 554 / 9; `test_10_corner_errors.py` 453 / 9; `test_11_corner_rbac.py` 537 / 8; `test_12_corner_complexity_layers.py` 361 / 5.

Design-index coverage
- §1.8 depth index (queue A): 19 instances, 0 stubs — all 19 translated, every one with >=2 tests (38 difficulty tests total).
- §1.9 breadth index (queue B): 97 instances, 20 of them `excluded_because:` stubs -> 77 non-stub — all 77 translated, every one with >=1 test (77 corner tests). Per section: entities 13, state_machines 10, calculations 9, validations 14, endpoints 9, errors 9, rbac 8, `cross-cutting complexity layers` 4, `consistency model` 1.
- Skipped: only the 20 stub instances, which the spec forbids translating (each carries an `excluded_because.difficulty_instance` pointing at the §1.8 instance that already asserts the claim). No instance was skipped for failing the PRD two-condition filter.

Audit results (machine-verified this session)
- Design tags: clean. Exactly one `Design:` line per test, always the last docstring line; all 115 tags resolve to a real instance name; zero stub instances tagged; zero unresolved or dual tags. Section strings with spaces (`cross-cutting complexity layers`, `consistency model`) reproduced verbatim.
- PRD citations: clean. All 145 quoted sentences were whitespace-normalised and grep-matched against `workspace/PRD.md`, and each cited §x.y was checked against that heading's actual line range. Three defects were found and fixed: a §3.6 quote in test_01 that had been truncated with an invented period (extended to the real sentence end), a §3.7 attribution in test_11 for text that lives at PRD line 23 (§2.1), and a paraphrased sweep-response sentence in test_12 (replaced with the verbatim PRD line 209).
- Static checks: clean. `pyflakes` reports nothing across `test_suite/` and `test_helpers/`. All 13 suite modules `ast.parse` successfully.
- Design-vs-PRD conflicts were resolved in favour of the PRD throughout (e.g. `PASSWORD_EXPIRY` -> `IT_PASSWORD_RESET`, `QUIET_HOURS` -> `ANNOUNCEMENT_MORATORIUM`, `CREDENTIAL_PHISHING` -> `CREDENTIAL_PHISH`, `LEGAL` -> `EXECUTIVE`; corrected `next_reminder_due_at`, post-sweep assignment state, and `rejection_reason` expectations).
- No smoke server was started, so no process was killed; `worklog.md` was not touched; no `test_helpers/`/`test_suite/` directory exists anywhere under `workspace/`.

Orchestrator verification: `find workspace -type d -name "test_*"` returns nothing — both test directories are correctly at the task root.

## Step 6: Generate implementation — 2026-09-05T10:19:00.000Z

Implementation complete. All 55 endpoints are live and three smoke passes ran green against a fresh boot.

Files written — `workspace/implementation/`: `store.py` 144 (in-memory `Store` (12 dicts), logical clock `DEFAULT_CLOCK = 2026-08-01T00:00:00Z`, ISO parse/`fmt` (3 fractional digits), `add_days`/`floor_days`/`floor_minutes`, `round_half_up`/`rate`, `new_row`/`touch`/`ordered`); `errors.py` 62 (all 46 catalogue ids -> HTTP status, `ApiError`, `fail()`); `envelope.py` 49; `guards.py` 247 (auth headers, role gate, body + query well-formedness validators, pagination); `calc.py` 411 (enumerations + every pure calculation); `derive.py` 253 (per-entity serializers; all derived fields computed at read time); `cascades.py` 272 (severity ladder, notice/consequence exits, assignment supersession, intervention opening, delivery release, compliance sweep); `lookups.py` 54 (family-specific 404 resolution); `routes_employees.py` 195 (9 endpoints); `routes_training.py` 313 (17); `routes_campaigns.py` 477 (15); `routes_simulations.py` 235 (8); `routes_reports.py` 266 (7); `app.py` 61 (blueprints + envelope error handlers, `0.0.0.0:$PORT`); `start.sh` 9 (`export PORT="${PORT:-10000}"`, foreground `exec python3 app.py`; `chmod +x` applied); `requirements.txt` 1 (`Flask==3.0.3`).

Endpoint coverage: 55/55. The implemented `method + path` set was diffed against the PRD §4 table (55 rows) — byte-identical after path-parameter normalisation.

What is implemented
- State machines: TrainingModule (3), CurriculumAssignment (7 states incl. supersession/void/extension reset), EscalationNotice, AccessConsequence (with same-type supersession), PhishingTemplate, PhishingCampaign (8 states, `SCHEDULED->SCHEDULED` reschedule self-loop), SimulationDelivery (7 states incl. the `REPORTED->CLICKED` dominance and `CLICKED->CLICKED` report self-loop), RepeatClickerIntervention (5 states, child assignment bubbling `COACHING_ASSIGNED->COACHING_COMPLETED`).
- Calculations: tenure band, due windows (HIGH -> `max(3, base//2)`), reminder cadence, escalation ladder 1/7/14, cohort resolution, per-employee difficulty escalation (greater-of -> cap 3 -> new-hire cap 2), scorecard rates (`resilience_ratio` over `max(1, clicked_n)`), department + tenure-band segments, repeat-clicker tier with 180-day window and decay, clean streak, both risk-score variants (weights 18/10/8 vs 6/5/2, x(1+0.1*tier), round-then-clamp), monthly effectiveness buckets with CONCURRENT/LAGGED pairing and Pearson correlation.
- Validation order: the 30 pinned priorities, including OCC 412s, three ownership 403s, SoD, harmful-theme screen ahead of everything referential, the credential capture-before-click ordering, event ordering, the four schedule gates in order, and the two extension budget/window clauses.
- Conserved ledgers: `reserved_simulation_slots` and `active_suspension_count` are derived from live rows, so reschedule/cancel/launch/offboard all balance by construction.
- No seeded data: every dict starts empty; the only persistence is process memory.

Smoke boot: booted via `PORT=18627 ./start.sh` four times (fresh process each time) and ran three scripted passes from `/tmp/task_2862_impl/` covering ~180 assertions: full campaign lifecycle, blackout/quiet-period/schedule-in-past refusals, reschedule and cancel ledger balance, launch, all four event types plus their refusals, scorecard and segments, close with rate freezing, sweep escalation cascade (both with a manager and the fragile null-`manager_id` case where hops 2-4 correctly produce nothing while `escalation_level` still reaches 3), coaching/extension/retake, consequence ladder and lifts, offboarding, retirement, effectiveness report and the >24-month refusal.

Four assertions "failed" and all four were the subagent's own test arithmetic, verified by hand against the PRD: two risk scores (8.8 is right — the 6-point report credit and 5-point new-hire relief had been forgotten), one `days_overdue` (31, not 46), and one notice count (notices *are* created when the manager row is merely offboarded — only a null `manager_id` suppresses hop 2). No implementation defects found.

Killed only its own PIDs (1349577, 1355936, 1359463, 1367342), one at a time by pid; the 33 other `python3 app.py` processes on this host were left untouched and port 18627 is free. Scratch files live only in `/tmp/task_2862_impl/`; `worklog.md` was not touched and the test directories were never read.

One judgement call flagged by the subagent: `api_request_timestamp` is stamped from the logical clock (not wall time), which the PRD leaves ambiguous but which keeps every timestamp in a response internally consistent. Orchestrator adjudication: accepted — this is an internal-consistency choice, and Step 9's full scan will pin it in PRD_COMPLETED.md if it remains PRD-silent.

Orchestrator note: Steps 5 and 6 were launched back-to-back as background agents so they ran concurrently; the impl generator was additionally given an explicit hard prohibition on reading `test_helpers/` and `test_suite/`, and it confirms it never read them.

## Step 7: Run tests and iterate — 2026-09-05T11:07:00.000Z

Done — clean 8-round sweep achieved.

**Iterations run:** 2

**Union of failures found (iteration 1):** exactly one, deterministic in all 8 rounds — `test_a_legitimate_learner_still_cannot_drive_someone_elses_assignment` (`test_11_corner_rbac.py`) with `KeyError: 'started_at'`. Every other one of the 115 tests passed in all 8 rounds of both sweeps, so there was no flakiness signal to chase.

**Tests deleted:** none deleted outright. One assertion removed under STEP 1c partial-coverage handling:
- `test_suite/test_11_corner_rbac.py:116` — `assert_instant_equals(started["started_at"], CLOCK_EPOCH, "started_at")`. **Category: PRD silence (computed/response-field silence).** `started_at` appears nowhere in PRD.md; worse, §3.3 affirmatively closes the question — *"Each of the three starts bumps the assignment's `version` by one and changes nothing else."* A PRD-faithful implementer must therefore **not** persist or serialize a `started_at`, so the assertion was unfairly demanding a field the PRD forbids. The rest of the test is fully PRD-covered (the two `ERR_NOT_ASSIGNMENT_OWNER` refusals per §2.1, the unchanged `ASSIGNED`/`attempt_count=0` state, the `ASSIGNED -> IN_PROGRESS` transition, and the `ERR_ROLE_NOT_PERMITTED` refusal of `ProgramAdmin` per the §4 authorized-role list) and was kept intact. The now-unused `CLOCK_EPOCH` import was dropped alongside it; `pyflakes` over `test_suite/` and `test_helpers/` is clean.

**Fixes applied to `test_helpers/`:** none. None of the known high-frequency fixture bug classes (money-as-string, date-only-vs-instant, `validate_success` double-unwrap, sub-second timestamp width) were present — `api_client.py` had no timestamp canonicalisation problem because `assertions.parse_instant` already compares moments rather than spellings.

**Fixes applied to `implementation/`:** none. No implementation defect was reachable: the single failure was a test asserting a field the PRD explicitly rules out, so adding `started_at` to the serializer would have violated the cardinal rule against introducing response fields that do not trace to a verbatim PRD sentence.

**Final sweep evidence** (iteration 2, all 8 parallel rounds ran to completion, `SWEEP_DONE` present):

| round | passed/total |
| --- | --- |
| results.1.json | 115 / 115 |
| results.2.json | 115 / 115 |
| results.3.json | 115 / 115 |
| results.4.json | 115 / 115 |
| results.5.json | 115 / 115 |
| results.6.json | 115 / 115 |
| results.7.json | 115 / 115 |
| results.8.json | 115 / 115 |

0 failed, 0 errors, 0 skipped in every round. `worklog.md` was not touched (mtime unchanged at 10:53), no stray `test_*` directories exist under `workspace/`, and scratch stayed in `/tmp/task_2862_step7/`. No servers were started or killed by the subagent outside the runner's own per-test lifecycle.

Orchestrator verification (independent, not taken on trust): all 8 `results.$i.json` exist (each ~34 KB, mtime 11:06); parsed each with `python3 -c json.load` — every round reports `passed=115 total=115 failed=0 errors=0 skipped=0`; `grep -c SWEEP_DONE workspace/sweep.log` = 1; `worklog.md` mtime confirmed unchanged at 10:53 (subagent did not write its own step heading). Step 8 skip condition NOT met (1 `test_suite/` fix), so Step 8 will run.

## Step 8: Finalize PRD — 2026-09-05T11:10:00.000Z

`workspace/PRD_FINALIZED.md` is written and is **byte-identical** to `PRD.md` (md5 `d9c3583f75118b2e9b71d31ffa08ac93`). This is the legitimate outcome here: the single Step 7 item was a pure test bug with no PRD silence and no PRD/impl mismatch behind it.

Line counts: `PRD.md` 467 lines; `PRD_FINALIZED.md` 467 lines; delta 0 lines, 0.00%.

Changes: none. Zero inserts, zero revisions.

Candidate-edit analysis log (the one Step 7 item)

**(a) Subject identified.** Whether an assignment `start` persists/serializes a `started_at` instant — the removed assertion `assert_instant_equals(started["started_at"], CLOCK_EPOCH, "started_at")` at `test_suite/test_11_corner_rbac.py:116`, which failed with `KeyError: 'started_at'` in all 8 rounds.

**(b) Impl paths enumerated (read/grepped).**
- `grep -rn "started_at" implementation/ --include=*.py` -> zero hits anywhere in the 3,039-line implementation. No store field, no serializer key, no calc input.
- `routes_training.py:162-175` — the `start` handler: owner check, `state in ("ASSIGNED","OVERDUE","ESCALATED")`, employment-liveness check, module-still-`PUBLISHED` check, then exactly `asg["state"] = "IN_PROGRESS"; touch(asg)` and return. `touch()` is the version+`updated_at` bump of §2.4 — nothing else is written, matching §3.3's "Each of the three starts bumps the assignment's `version` by one and changes nothing else."
- `derive.py:59-82` — `assignment_json`, the single serializer used by every assignment-returning route (create, read, list, start, submit, retake, extension, void, sweep). Its 19 keys plus the `_common` block are all traceable to §3.2/§3.3/§2.4 prose; there is no `started_at` key on any path.
- Parallel learner actions `submit_assignment` and `retake` (`routes_training.py:178-215`) — same story: they mutate only `attempt_count`, `last_score_pct`, `state` and the version/timestamp pair, so no sibling endpoint exposes a start timestamp either.
- Cross-check on the test side: `test_helpers/types.py:75` declares an `Optional[str] started_at` on the assignment TypedDict, but no fixture or helper ever populates or reads it — confirming the field was invented by the test generator, not by the implementation.

**(c) Wording adjustment made.** None — no edit was committed. PRD.md already uniquely determines this behavior in the direction the implementation takes it: §3.3 affirmatively closes the question ("changes nothing else"), and §3.2's enumeration of a new assignment's initial fields (`attempt_count`, `last_score_pct`, `completed_at`, `reminders_sent`, `last_reminder_at`, `escalation_level`, `days_overdue`, `next_reminder_due_at`) contains no start timestamp. A fresh implementer reading PRD_FINALIZED.md alone would therefore correctly omit `started_at` and reproduce `implementation/`. Adding any sentence about `started_at` would either restate existing prose or introduce a field the implementation does not exhibit — a brand-new mismatch for Step 9 to undo.

No other Step 7 item exists to trace (no tests deleted outright, no `test_helpers/` fixes, no `implementation/` fixes), so the HARD SCOPE admits no further edits.

Orchestrator adjudication: a byte-identical PRD_FINALIZED.md is a legitimate Step 8 outcome (verified by md5 — both files `d9c3583f75118b2e9b71d31ffa08ac93`). Step 9, by contrast, performs a full PRD-vs-implementation scan and must NOT be identical; it will be run as three sequential module-partitioned passes over one shared PRD_COMPLETED.md.

## Step 9: Complete PRD — 2026-09-05T11:45:00.000Z

Run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` (pass 1 performs the `cp`; passes 2 and 3 edit in place and were explicitly forbidden from copying). Total: **51 edits — 44 ambiguity-pins, 7 mismatch-revisions.**

### Pass 1 — `app.py`, `envelope.py`, `errors.py`, `guards.py`, `lookups.py`, `store.py`, `routes_employees.py`, `routes_training.py`

`cp` performed. `PRD_FINALIZED.md` 467 lines / 101,238 chars -> `PRD_COMPLETED.md` 469 lines / 107,899 chars (+2 lines, +6,661 chars). 17 ambiguity-pins, 1 mismatch-revision (18 diff hunks).

- §2.1 — insert — ambiguity — whitespace-only headers count as empty; both header values are trimmed before role matching and before any ownership comparison — `guards.py:26-35`
- §2.1 — insert — ambiguity — ownership checks are confined to the named mutating actions; read/list endpoints apply role authorization only (a Manager/Learner may read any employee, assignment or notice, and lists impose no implicit owner filter) — `routes_employees.py:53-56`, `routes_training.py:119-120,271-272,277-296`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — `envelope.py:9-16`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time, at envelope-build time (so the clock-set response already reports the new instant; identical across responses without an intervening move); errors stamp it identically — `envelope.py:12-17,39-44`, `store.py:47-48`
- §2.2 — insert — ambiguity — pagination `meta` fields are absent from single-object and error envelopes — `envelope.py:20-36`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` text is `ERR_INVALID_REQUEST`; `offset` past `total_count` is legal, empty page, `has_more` false — `guards.py:188-207`, `envelope.py:34,47-49`
- §2.3 — insert — ambiguity — default ordering ties (identical `created_at` under a frozen clock) break by ascending creation order — `store.py:142-144`
- §2.3 — insert (new paragraph) — ambiguity — filters are optional and ANDed, unknown query params ignored, closed-vocabulary filters validated (400), identifier filters matched-not-resolved (empty page, not 404) — `guards.py:210-235`, `routes_employees.py:63-67,161-164`, `routes_training.py:127-131,279-282`
- §2.4 — insert — ambiguity — every emitted instant uses `YYYY-MM-DDTHH:MM:SS.mmmZ`; scalar "empty/unset" fields are JSON `null` (arrays are `[]`) — `store.py:81-86`, `derive.py:6-11`
- §2.5 — insert — ambiguity — in-memory only, empty registry every boot, nothing seeded/persisted — `app.py:1-5`, `store.py:19-37`
- §2.5 — insert — ambiguity — accepted client instant grammar: date + seconds + mandatory `Z`/numeric offset, optional 1-9 fractional digits, normalised to UTC; bare dates rejected; `YYYY-MM-DD` is the only date form — `store.py:13-16,52-78`, `guards.py:133-148`
- §2.8 — insert — ambiguity — unmatched path -> `ERR_RESOURCE_NOT_FOUND` (404); unsupported method -> `ERR_INVALID_REQUEST` on HTTP 405; trailing slash tolerated — `app.py:22,34-40`
- §2.8 step 3 — insert — ambiguity — JSON booleans rejected where integers expected; unnamed body keys ignored; absent body read as `{}`; unparseable or non-object body -> 400 — `guards.py:46-54,96-99`
- §2.8 step 6 — insert — ambiguity — email uniqueness also ignores surrounding whitespace and the address is stored verbatim; module `code` uniqueness is an exact string comparison (case-sensitive) — `routes_employees.py:31-34`, `routes_training.py:32-34`
- §3.1 — insert — ambiguity — `manager_id` need only exist (no role/employment check); future `hire_date` accepted; `email` gets no format validation beyond non-emptiness — `routes_employees.py:21-29`
- §3.1 — insert — ambiguity — offboarding bumps each rewritten child row's own `version` (assignment, notice, consequence, delivery) — `routes_employees.py:104-126`, `cascades.py:16-37`
- §3.2 — insert — ambiguity — `passing_score_pct` bounded 0-100; `reminder_offsets_days` accepts any integer array incl. negatives/repeats, empty array means no reminder ever due; every assignment create bumps `Employee.version` once whether or not it superseded — `routes_training.py:26-28,113`, `guards.py:175-184`, `calc.py:117-124`
- §3.3 — **revise — mismatch** — the `employment_status = ACTIVE` requirement on start is not limited to the `ASSIGNED` source; all three source states are checked, after state legality and before the module-published check — `routes_training.py:167-172`
- §3.6 — insert — ambiguity — the `lift_reason_code`/`reason_code`/`void_reason_code` vocabulary is descriptive, not enforced: client-supplied codes need only be non-empty and are stored verbatim — `routes_employees.py:134,185-191`, `routes_training.py:250`

### Pass 2 — `routes_campaigns.py`, `routes_simulations.py`, `cascades.py`

No `cp` run; edited in place, 20 patches, all of pass 1's 18 edits intact. 469 -> 471 lines; 107,899 -> 115,565 chars (+7,666). 15 ambiguity-pins, 5 mismatch-revisions.

- §2.7 — revise — mismatch — scoped the `expected_employee_version` requirement to `POST /awareness/curriculum-assignments`, since the coaching-created assignment carries none — `routes_simulations.py:207`
- §3.2 Supersession — revise — mismatch — superseded assignment's `ACTIVE` consequences exit with `lift_reason_code` `SUPERSEDED_BY_NEW_ASSIGNMENT`, not `ASSIGNMENT_VOIDED` — `cascades.py:118`
- §3.4 intro — insert — ambiguity — pinned all six sweep report fields: `assignments_scanned` counts every assignment row including terminal ones and offboarded employees' rows, `reminders_sent_count`/`overdue_count` count acted-on assignments, `escalations_created_count` counts notices created (0 when no `manager_id`), `consequences_applied_count` counts consequence rows — `cascades.py:196-205, 219, 229, 256, 265`
- §3.4 intro — insert — ambiguity — the report object alone is the response body, hence HTTP 200 — `cascades.py:272`, `routes_training.py:265`
- §3.4 Step A — insert — ambiguity — a reminder bumps only the assignment's `version`, never the employee's — `cascades.py:216-219`
- §3.4 Hop 3 — insert — ambiguity — consequence `reason_code` is `ESCALATION_LEVEL_2` / `ESCALATION_LEVEL_3` — `cascades.py:260`
- §3.4 hop-2 fragility para — revise — ambiguity — Step C bumps assignment and employee by exactly one regardless of rung count; an assignment already at its target rung is untouched — `cascades.py:237, 268-269`
- §3.6 lift-code map — revise — mismatch — four compensated exits, adding `SUPERSEDED_BY_NEW_ASSIGNMENT` — `cascades.py:118`
- §3.7 template block — insert — ambiguity — `blocked_reason` mandatory, non-whitespace, stored verbatim — `routes_campaigns.py:65`
- §3.7 Rejection — insert — ambiguity — `rejection_reason` mandatory non-whitespace, validated before campaign resolution — `routes_campaigns.py:192-194`
- §3.8 cohort split — insert — ambiguity — an excluded-at-birth delivery carries the same `queued_at`, tiers and frozen band, and bumps no `Employee.version` — `routes_campaigns.py:291-311`
- §3.8 reservation — revise — ambiguity — "each reserved employee" rather than "each targeted employee" — `routes_campaigns.py:309-311`
- §3.8 Rescheduling — insert — ambiguity — superseded rows are kept as excluded history; a retained member is version-bumped twice (release + re-reservation) — `routes_campaigns.py:289`, `cascades.py:179-191`
- §3.8 Cancelling — insert — ambiguity — `target_count` is retained while `evaluable_count` falls to 0 — `routes_campaigns.py:404`
- §3.9 event record — revise — ambiguity — `superseding_effect` literal format `FROM->TO` with no spaces; the exact four transition strings — `routes_simulations.py:55, 73, 80`
- §3.9 append guards — insert — ambiguity — delivery-interactability is checked before campaign state, and `OPEN` leaves the delivery row wholly untouched (no version bump) — `routes_simulations.py:92-97, 116`
- §3.9 (new para) — insert — ambiguity — duplicate `CLICK`/`REPORT` are logged but wholly inert, with the one exception that a `REPORT` on a `CLICKED` delivery always bumps its version — `routes_simulations.py:56-63, 66-69`
- §3.9 Closing — revise — mismatch — the employee `version` bump is once per cohort member (not per `NO_INTERACTION` transition), a `REPORTED` delivery's own version is not bumped, and an all-excluded employee is not bumped — `routes_campaigns.py:367-390`
- §3.9 Segments — insert — ambiguity — `segment_by` vocabulary and trim/upper-case matching, both-axis default with department segments first, group discovery over all deliveries in `created_at` order (excluded included) with first-seen ordering, and the full segment row shape — `routes_campaigns.py:410-477`
- §3.9 Closing — insert — ambiguity — whitespace-only `debrief_note` counts as empty; a non-string is `ERR_INVALID_REQUEST` before the state check; an accepted note is stored untrimmed — `routes_campaigns.py:356-364`
- §3.10 Assigning coaching — insert — mismatch — the coaching create takes no version field and applies neither role-eligibility nor employment-liveness (offboarding does not close interventions), but does run the full supersession cascade — `routes_simulations.py:196-211`, `cascades.py:107-118`
- §3.10 Completing and closing — insert — ambiguity — `resolution_code` mandatory non-whitespace, stored verbatim — `routes_simulations.py:219`

### Pass 3 — `calc.py`, `derive.py`, `routes_reports.py`

No `cp` run; edited in place, 16 patches. 471 lines / 115,565 chars -> 471 lines / 121,708 chars (all in-paragraph; no new lines, no new sections). 12 ambiguity-pins, 4 mismatch-revisions. Tail check: document still ends at `| ERR_COMMUNICATION_POLICY_NOT_ACKNOWLEDGED | 422 |`, the last row of the §5 error-code table — no truncation.

- §3.10 repeat-clicker tier — revise — **mismatch** — "reduced by one" replaced with the accumulated, permanent decay count subtracted from the banded figure then floored at 0; two decays subtract 2 forever, nothing restores them; worked examples added — `calc.py:233`, `routes_simulations.py:231`
- §3.10 Completing and closing — revise — **mismatch** — the close adds one unit to a permanent decay count rather than decrementing the tier once; a second qualifying close subtracts a second unit for good — `routes_simulations.py:229-232`
- §3.10 The clean streak — revise — **mismatch** — `REPORTED` counts only once its campaign is `CLOSED`; `QUEUED` rows (no `delivered_at`) are outside the walk; a still-`DELIVERED` row neither counts nor breaks the run; ties broken by creation order; the click reset is positional, not unconditional — `calc.py:236-253`
- §3.9 Classifying one delivery — revise — **mismatch** — classification reads only the delivery's own `state` and three stored instants; the false claim that "the events are considered in ascending `occurred_at` order" removed — `calc.py:307-320`
- §3.8 cohort resolution — revise — **mismatch** — the frozen `tenure_band` is retained internally for §3.9 segmentation and is not a delivery response field (it had been listed as one) — `routes_campaigns.py:306`, `derive.py:172-190`
- §3.1 Tenure band — insert — ambiguity — the day count goes negative for a future `hire_date`, so such an employee is `NEW_HIRE` — `calc.py:88-97`
- §3.4 Step C — insert — ambiguity — the same floored expression is what `days_overdue` reports on every read, unconditioned on state, so a `COMPLETED`/`VOIDED` row past its deadline still reports a positive count — `calc.py:127-129`, `derive.py:78`
- §3.8 delivery read/list — insert — ambiguity — the full delivery key set plus exactly three derived fields, all recomputed for every delivery including `EXCLUDED` rows (whose `quiet_period_until` falls 5 days after the campaign's `scheduled_send_at`) — `derive.py:172-190`, `calc.py:329-342`
- §3.7 campaign creation — insert — ambiguity — a `DRAFT` campaign carries `target_count`/`evaluable_count` at 0 and all four scorecard figures `null` — `derive.py:162-167`, `routes_campaigns.py:111-116`
- §3.10 Real incidents — insert — ambiguity — `summary` must be non-blank; `root_cause_employee_id` need only resolve (no `employment_status`/`role_code` check) — `routes_reports.py:29-33`
- §3.10 Real incidents (filters) — insert — ambiguity — `occurred_from`/`occurred_to` are both inclusive bounds — `routes_reports.py:73-76`
- §2.10 communication windows — insert — ambiguity — `reason` must be non-blank; created by `ProgramAdmin`, immutable, listable on `window_type` + `scope_department`; overlaps allowed; only `SIMULATION_BLACKOUT` is consulted by any gate — `routes_reports.py:83-123`, `routes_campaigns.py:230`
- §3.10 Program effectiveness (inputs) — insert — ambiguity — inputs accepted from query string or JSON body, query wins on conflict; the 24-month cap counts month buckets, a 25th refuses — `routes_reports.py:148-156, 205-210`
- §3.10 bucketing — insert — ambiguity — buckets snap to whole calendar months (first bucket may open before `period_start`, last may extend past `period_end`), are measured unclipped, and each serializes `month`/`bucket_start`/`bucket_end`/`report_rate`/`incident_count` — `routes_reports.py:138-145, 203-222`
- §3.10 response summary — insert — ambiguity — `mean_report_rate` and `total_incidents` span every bucket, not the surviving pairs (so `LAGGED`'s dropped bucket still contributes); both null-cases pinned — `routes_reports.py:251-265`
- §2.5 the logical clock — insert — ambiguity — the clock endpoint returns exactly `current_utc` and `previous_utc`, equal when the clock is set to where it stands — `routes_reports.py:127-134`

Pass 3 confirms every deferred item was handled. Enum vocabularies, the due-window/reminder-cadence/escalation-ladder/cohort-resolution/difficulty-escalation/scorecard-rate/`resilience_ratio` formulas, `time_to_report_minutes`, `current_tier`, frozen-vs-live campaign rates, and the CONCURRENT/LAGGED pairing plus Pearson rules were each verified line-by-line against the code and found already uniquely pinned (the §3.10 worked example — 11.00 provisional vs 0.00 settled — was re-derived and reproduces exactly), so they needed no edit. The `_tier_decay_total` mismatch pass 2 handed pass 3 is confirmed at `calc.py:233` and fixed in both places §3.10 describes it.

### Orchestrator verification

- `wc -l -c`: PRD.md 467 / 101,238 · PRD_FINALIZED.md 467 / 101,238 · **PRD_COMPLETED.md 471 / 121,708** (+20,470 chars over the source).
- `md5sum`: PRD.md and PRD_FINALIZED.md both `d9c3583f75118b2e9b71d31ffa08ac93`; PRD_COMPLETED.md `37243f47e86829ad56fe06df5f3e82ed` — **not identical**, so the scan demonstrably ran.
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` = 102 changed lines.
- `tail -4 PRD_COMPLETED.md` ends on the final §5 error-catalogue row — intact, no truncation.
- `grep` for "harder than expert" / "expert level" across PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md: no matches — the difficulty directive never leaked into any PRD.
- Exactly one `worklog.md` in the task tree (no cwd-drift strays under `workspace/`); no stray `test_*` directories under `workspace/`.
- Steps 9's passes touched no implementation or test file, so the Step 7 evidence stands: all 8 sweep rounds 115/115.

## Pipeline complete — 2026-09-05T11:47:00.000Z

All nine steps finished. `workspace/PRD_COMPLETED.md` written.
