# Worklog — task_2803_venue_event_day_staffing_guest_services

## Step 1: Create task directory — 2026-09-04T23:48:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2803_venue_event_day_staffing_guest_services` and its `workspace/` subdirectory. Index 2803 was pre-assigned by the invocation; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-05T01:56:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and pass the lint cleanly.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2803_venue_event_day_staffing_guest_services/`

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3224 | 160289 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2341 | 164216 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5906 | 380284 |

`worklog.md` and `workspace/` survived untouched; nothing was written outside the task directory, and no sibling task was read.

## SCAFFOLD.yaml (§1.0–§1.7)
`difficulty_level: expert_plus`, `api_prefix: "/"`, complexity profile = primary `quota_allocation` / secondary `compliance_audit`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, topology `flat`, machine shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`.

- **13 entities**, **66 endpoints**, 10 state machines, 13 calculations, 24 validations, **43 errors**, 4 roles (+4 conditional role rules), 1 concurrency rule (`plan-activate-stale-event`).
- Verified it contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.

## SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 9 rules / 25 instances
`dual_variant_calc` 3, `combinatorial_formula` 3, `non_linear_state_machine` 3, `transitive_cascade` 3, `priority_pair_validation_conflict` 3, `boundary_precision_check` 3, `cross_entity_state_dependency` 3, `resource_temporal_overlap` 2, `compensating_invariant` 2.

## SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 9 sections / 102 instances (75 full recipes + 27 `excluded_because` stubs)
`entities` 13 (12+1), `state_machines` 18 (12+6), `calculations` 18 (11+7), `validations` 18 (12+6), `endpoints` 9 (9+0), `errors` 8 (5+3), `rbac` 7 (7+0), `cross_cutting_complexity_layers` 9 (5+4), `consistency_model` 2 (2+0).

All 27 stub `difficulty_instance` references resolve to real §1.8 instances, no stub carries a `test_recipe`, all 102 names are unique across the two design files, and every full recipe has setup / setup_api_calls / trigger / assert (the sole `setup_api_calls: []` is intentional — the clock-default instance requires a server on which nothing has been called).

## Lint verdict
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2803_venue_event_day_staffing_guest_services/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2803_venue_event_day_staffing_guest_services/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2803_venue_event_day_staffing_guest_services/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    66
  §1.1 entities declared:     13
  §1.8 instances scanned:     25
  §1.9 instances scanned:     75
  Calls scanned (§1.8+§1.9):  1326

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Fixes applied in the last pass (18 lint violations → 0): list-endpoint pagination captures moved from `$.data.total_count` / `$.data.has_more` to `$.meta.*` (the envelope puts `data` = the array itself), `$.data.items[0].x` rewritten to `$.data[0].x`, `sla_deadline_at` → the declared `GuestIssue.sla_deadline`, and the non-existent `StaffingPlan.tier_surcharge_bp` replaced by the declared `accessibility_surcharge_cents` with asserts restated in cents (`25200` = 350 bp of the 720000 base) rather than basis points.

Orchestrator verification: all three files present; `workspace/` and `worklog.md` intact; grepped SCAFFOLD.yaml for the difficulty directive line ("harder than expert") — no leak into the scenario key or anywhere else, so no stripping was needed.

## Step 3: Copy shared files — 2026-09-05T01:57:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T02:16:00.000Z

Subagent summary (verbatim):

PRD generation for task 2803 is complete.

**Output:** `workspace/PRD.md` — **462 lines / 98,273 bytes**. Written incrementally (1 `Write` + 8 heredoc appends), each append verified with `wc -l` and `tail`.

**Section list (all present, verified by heading scan):**
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Operator Identity and RBAC · 2.2 API Response Structure (verbatim contract block) · 2.3 Pagination and List Ordering · 2.4 The Logical Event Clock · 2.5 Common Resource Properties and Mutation Semantics · 2.6 Money, Headcount and Rounding Discipline · 2.7 Optimistic Concurrency on the Event Record · 2.8 Nested and Referential Resolution Order · 2.9 Validation Precedence · 2.10 Cascade Discipline Across the Staffing Hierarchy · 2.11 Guest-Recovery Ledger Integrity
- `## 3. Business Logic & Workflows` — 3.1 Forecasting an Event and Opening a Staffing Plan · 3.2 Position Families, Shift Blocks and Plan Costing · 3.3 Activation, Supersession and the Event-Day Lifecycle · 3.4 The Part-Time Workforce · 3.5 Shift Bidding and Award Adjudication · 3.6 Event-Day Attendance, No-Shows and the Backfill Pool · 3.7 Guest Issue Intake, Response Deadlines and Escalation · 3.8 Issue Resolution, Refund Authority and the Recovery Ledger · 3.9 Accessibility Service Pools and Guest Bookings · 3.10 Closing the Books: Payout Runs, Guest Sentiment and Model Refinement
- `## 4. Endpoint Definitions` — 4-column table, **66 rows** (matches the scaffold's 66 endpoints exactly)
- `## 5. Error Code Catalogue` — 2-column table, **43 rows**

**Tail confirmation:** the file ends on the last error row (`| ERR_INVALID_TIME_WINDOW | 422 |`) at a real section boundary, with no audit footer and nothing mid-sentence.

**Hard Contract verification**

- **Contract 1 — Field-Name Coverage: PASS.** Two mechanical passes. Pass 1 extracted all 137 `- name:` identifiers plus every `input`/query/path identifier and diffed them against the PRD's backticked inline-code spans: the only 13 absences are the scaffold's 13 *calculation names*, which are internal calc IDs, not entity fields or request identifiers. Pass 2 swept every snake_case token in the whole `calculations:` block; residuals were only intermediate locals, which the skill's no-pseudocode rule requires be expressed as prose. All 124 real field/param identifiers appear verbatim in backticks.
- **Contract 2 — Rule Coverage: PASS.** §2.9 states the ladder as an explicit numbered 1–24 list matching the scaffold's `priority:` order item-for-item, including the two ordering traps (reopen window above ceiling; uniqueness above rest buffer). §2.7 frames the OCC guard purely as a stale-version check. All 43 scaffold error IDs appear in the prose (not merely in the §5 table), and §5 statuses match the scaffold's `http:` values with zero mismatches/omissions. Every uppercase enum/state value appears backticked; numeric constants individually confirmed (tier floors 12000/25000/40000 and multipliers 1.00/1.10/1.25/1.45, surcharge floors 60/150/300 and 350/600/900 bp, reliability 25/8/3 with floor 65 over a 3-event window, 5-minute grace, 30-minute rest buffer, 480-minute/1.5x overtime, caps 5000/50000/2500, uplifts 5000/2500 bp, SLA 5/15/45/120, 1440-minute window, promoter floor 4, 8000 bp / 1.10 / 0.95 / 4.5). No fuzzy words, no symbolic operators.
- **Contract 3 — §3 Path Purity: PASS.** Scan of all 176 lines of §3: zero backticked path/method tokens and zero bare path-like strings outside backticks. §2 and §4 name paths, as permitted.

**Two judgment calls preserved from the earlier passes** (worth flagging to the implementation step): the scaffold mentions a `decided_at` field in ShiftBid's award side effects that does not exist in the entity definition, so it is deliberately omitted; and `rank_score` is documented as a snapshot of the member's `reliability_score` at award-run time (2 of 3 scaffold sources), not as a rank position.

Only `workspace/PRD.md` was written. `worklog.md` was not touched, and neither design yaml was ever opened.

Orchestrator verification (truncation guard): `wc -l` = 462; heading scan shows all five top-level sections plus 11 §2 and 10 §3 subsections; `tail` ends cleanly on the final error-catalogue table row `| ERR_INVALID_TIME_WINDOW | 422 |`. Not truncated — no regeneration needed. Grep for scaffold/difficulty-directive leakage into PRD.md returned 0 hits.

## Step 6: Generate implementation — 2026-09-05T03:05:00.000Z

(Steps 5 and 6 were launched concurrently; Step 6 returned first, so its entry is recorded first. Step 5's entry follows below.)

Subagent summary (verbatim):

Implementation complete. All files live only in `workspace/implementation/`; no test/helper directories, difficulty/corner design files or sibling tasks were read.

## Modules (4,347 lines total)

| file | lines | contents |
|---|---|---|
| `core.py` | 508 | in-memory `DB` (13 dicts), logical clock (default `2026-08-01T00:00:00Z`), envelope/`meta` builders, `req_`/`api_request_id`, ISO-8601 with exactly 3 fractional digits, entity-specific 404 table, `ApiError` factories, auth ladder rungs 1–2, rung-3 validators, offset pagination, `new_record`/`update`/`touch` version discipline |
| `calc.py` | 245 | all 13 calculations + every pinned constant (Decimal, ROUND_HALF_UP/CEILING/FLOOR, 480-minute pay split, gratuity remainder in ranking order, refund caps, SLA table, peak occupancy, fill-rate/recommended ratio) |
| `serialize.py` | 284 | one serializer per entity in scaffold field order, derived `cert_status`, `sla_breached`, `SatisfactionResponse` without `version` |
| `services.py` | 803 | reachability helpers, slot sizing/re-derivation, six-step plan costing, cascades (supersede/void/close/event-cancel/member-removal), eligibility + rest buffer, assignment creation, reliability + auto-probation + ELEVATOR_OPERATION cascade, backfill candidate ranking, accessibility peak capacity, satisfaction summary, recommendation, gratuity + payroll |
| `routes_events.py` | 394 | clock, events CRUD + lifecycle, payout-run, satisfaction summary/responses, recommendation |
| `routes_staffing.py` | 507 | position types, staffing plans + OCC activation, position slots, batch bid award |
| `routes_workforce.py` | 270 | staff members + standing changes, certifications + revoke |
| `routes_work.py` | 471 | shift bids, assignments, attendance (4 actions), backfill requests |
| `routes_guest.py` | 492 | guest issues, assign/escalate/resolve/reopen/close, two-step refund ladder with SoD |
| `routes_access.py` | 288 | accessibility pools (incl. shrink-below-peak refusal) and bookings with the six declared transitions |
| `app.py` | 69 | blueprint registration, `ApiError`/404/405/JSON-parse/500 handlers in envelope form, `0.0.0.0:$PORT` (fallback 10000) |
| `start.sh` | 15 | foreground `exec python3 app.py`, reads `$PORT`, guarded flask install, `PYTHONDONTWRITEBYTECODE` |

## Endpoint coverage
66 routes registered — a programmatic diff of the registered `(method, path)` set against the SCAFFOLD endpoint list is an exact match: **0 missing, 0 extra**.

## Smoke test (own server, `PORT=18803`, stopped by its own pid; no broad pkill)
Two clean-boot runs across a fresh process each time (storage confirmed empty on restart):
- Clock set, event created (`FORECAST`, v1, ledger `500000/0/500000`), position type, plan (`basis 12000`, `TIER_2`, `revision 1`), slot (`ratio 33`, `shift_minutes 360`, `slot_labor_cost 396000`).
- Activation: stale `expected_event_version` → 412 `ERR_STALE_EVENT_VERSION`; correct version → `ACTIVE` with `396000/0/396000`.
- Credential rung 4 → 422 `ERR_INVALID_TIME_WINDOW`; valid cert reads `VALID`.
- Bid → manual award → assignment `SCHEDULED/PENDING/BID_AWARD`, slot `1/PARTIALLY_FILLED`; CHECK_IN then CHECK_OUT → `worked 3480`, `base_pay 182600`.
- Guest issue: `sla_minutes 15` with stamped deadline; assign; refund-request; self-decision → 403 `ERR_SEGREGATION_OF_DUTIES`; director APPROVE on a `SEAT_RELOCATION` HIGH issue → `PARTIALLY_APPROVED 2500` (hard 2500 ceiling after the uplift) and the event ledger re-derived to `2500/497500`; resolve with a staffed zone → 200.
- Accessibility: pool of 2 units, booking of 2 confirmed → `peak_committed_units 2`; overlapping 1-unit confirm → 409 `ERR_ACCESSIBILITY_CAPACITY_EXCEEDED`; shrink to 1 → 409 same code; IN_SERVICE → COMPLETED releases units, repeat COMPLETED → 409 `ERR_ACCESS_REQUEST_STATE_INVALID`, and the previously refused booking then confirms.
- Second run: capacity-full direct assignment → 409 `ERR_SLOT_CAPACITY_FULL`; NO_SHOW → `NO_SHOW/VOIDED`, reliability 100→75, strike 1, backfill request opened automatically, auto-fill picked the expected candidate (slot back to `FILLED`), re-run → 409 `ERR_BACKFILL_NOT_OPEN`.
- Close → payroll phase pays the assignment (`PAID`); recommendation returns per-position `fill_rate_bp`/`direction`/`recommended_ratio_per_1000`; satisfaction summary returns averages, `promoter_share_bp` and zone breakdown.
- Envelope/error spot checks: unknown id → entity-specific 404, bad role → 401, missing body fields → 422, `limit=0` → 422; list `meta` carries `api_request_id`, `limit`, `offset`, `total_count`, `has_more` with `response_type: array`.

## Step 5: Generate unit tests — 2026-09-05T04:22:00.000Z

Subagent summary (verbatim):

Generation is complete. Both stages are finished and every live design-index instance is translated.

## Files written (all under the task dir)

**Stage 1 — `test_helpers/` (2140 lines, 9 modules)**
`__init__.py` 109 · `api_client.py` 314 · `api_errors.py` 104 · `assertions.py` 288 · `constants.py` 137 · `factories.py` 425 · `fixtures.py` 501 · `test_users.py` 67 · `types.py` 195

**Stage 2 — `test_suite/` (conftest 8 lines + 21 test modules, 142 tests)**
`test_01` 391/6 · `test_02` 366/6 · `test_03` 377/8 · `test_04` 522/9 · `test_05` 184/3 · `test_06` 333/5 · `test_07` 340/6 · `test_08` 194/3 · `test_09` 238/6 · `test_10` 245/6 · `test_11` 302/6 · `test_12` 169/3 (queue A, 67 tests) · `test_13_corner_entities` 636/12 · `test_14_corner_state_machines` 670/12 · `test_15_corner_calculations` 881/11 · `test_16_corner_validations` 895/12 · `test_17_corner_endpoints` 869/9 · `test_18_corner_errors` 536/5 · `test_19_corner_rbac` 671/7 · `test_20_corner_cross_cutting` 509/5 · `test_21_corner_consistency` 251/2 (queue B, 75 tests)

## Coverage

- **Queue A (difficulty):** 25 instances, 25 live, **25/25 translated**, every rule_id carrying >=2 tests (67 total).
- **Queue B (corner):** 102 instances, 75 live / 27 `excluded_because:` stubs. **75/75 live translated, 0 stubs translated.**
- 100 distinct `Design:` tags, exactly one tag per test, **no dangling tags**, no dual tags. No instance was weakened, skipped, or placeheld.

## Verification passes

- `python3 -m py_compile` over all 31 modules: clean.
- Import/symbol/client-method audit: no unused imports, no missing helper symbols, no unknown `client.*` methods.
- Citation check across all 21 test files: `problems: 0` (every docstring quote is a verbatim >=8-word PRD substring; exactly one `Design:` line each).
- `test_helpers/` and `test_suite/` are siblings of `workspace/`; `workspace/` still contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`. No SCAFFOLD file, `PRD.md`, or `worklog.md` was touched.

## Two recipe defects corrected against the PRD

- `cross_cutting_complexity_layers/probation_threshold_holds_at_exactly_sixty_five` asserts `rel_below == 53`; the PRD 223 formula over that window (two no-shows + one late completion) gives **45**, and the sibling recipe states 45 for the identical window. The test asserts 45.
- Carried from the previous sections: the three `rbac` recipe defects (event opens `FORECAST` not `PLANNED`; an empty `GRATUITY_ALLOCATION` run is refused with `ERR_PAYOUT_PHASE_INVALID` rather than returning 200; `understaffed_slot_count` is 0, since PRD 339 counts only `UNDERSTAFFED_ESCALATED` blocks).

Orchestrator verification: `test_helpers/` and `test_suite/` are siblings of `workspace/` (no strays inside `workspace/`); collected test-function count = 142, matching the subagent's report.

## Step 7: Run tests and iterate — 2026-09-05T05:09:00.000Z

Subagent summary (verbatim):

Clean 8-round sweep achieved: **142/142 passing in all 8 rounds, zero flakiness**.

## Summary

**Iterations run:** 3 (each a full 8-round parallel `setsid` sweep).

| Iteration | Result |
|---|---|
| 1 | 84/142 in all 8 rounds (58 failures, fully deterministic) |
| 2 | 139/142 in all 8 rounds (3 failures, fully deterministic) |
| 3 | **142/142 in all 8 rounds** |

No flakiness was ever observed — the union and intersection of failing tests were identical in every iteration, so every failure was a real artifact defect rather than load-induced noise.

**Tests deleted:** none. All 142 tests traced to verbatim PRD prose.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — the four canonical position-family builders (`usher_payload`, `ticket_taker_payload`, `elevator_operator_payload`, `guest_services_rep_payload`) passed `code`/`display_name`/`base_hourly_rate_cents`/`attendance_ratio_per_1000`/`min_headcount` as explicit keywords *and* splatted `**overrides` into the same call, so any test overriding one of those five fields raised `TypeError: got multiple values for keyword argument`. Extracted a `_family_payload()` merge helper that applies overrides onto the defaults dict before the call. This single upstream bug was responsible for **57 of the 58** iteration-1 failures.
- `test_helpers/assertions.py` — `err()` returned `body.get("error", body)`, i.e. the entire envelope, because no `error` key exists in the standard error format. Per PRD §2.2 the `error_id` and its human-readable `message` both live inside `data`, so it now returns `body.get("data", body)`.

**Fixes applied to `test_suite/`:**
- `test_02_reliability_and_probation.py::test_a_second_no_show_voids_the_row_opens_a_backfill_and_moves_both_scores` — asserted `reason="NO_SHOW"` on the backfill request. PRD §3.6 enumerates the backfill-request fields exhaustively (`position_slot_id`, `triggering_assignment_id`, `attempt_count`, `selected_staff_member_id`, `filled_assignment_id`, `cancel_reason`, `status`) and names no `reason` field, so this was **PRD-silent on a response attribute**. Applied the STEP 1c partial-coverage split: dropped the uncovered `reason` assertion, kept `status`/`position_slot_id`/`attempt_count` and added the verbatim-covered `triggering_assignment_id` check. No implementation field was invented to satisfy it.
- `test_18_corner_errors.py` and `test_20_corner_cross_cutting.py` — two call sites indexed `err(...)["data"]["error_id"]`, assuming `err()` handed back the whole envelope. Corrected to `["error_id"]` to match the fixed helper. Both assertions are unchanged in strength (still exact `error_id` equality, still 12 distinct not-found ids / still `ERR_STALE_EVENT_VERSION`).

**Fixes applied to `implementation/`:** none. Every failure in this task was a test-artifact defect; the PRD-faithful implementation needed no change, and no PRD-required check was weakened or removed to accommodate a fixture.

One latent (dormant) helper bug noticed but deliberately left alone: `assertions.expected_surcharge_bp()` uses strict `>` against the surcharge head thresholds where PRD §3.2 says "300 heads or more" / "at least 150" / "at least 60" (i.e. `>=`), so it would misreport at exactly 60/150/300 heads. It is referenced by no test in `test_suite/`, so it affects nothing; left untouched rather than make an unexercised change.

Orchestrator verification: the subagent exited leaving NO `results.*.json` and no `sweep.log` behind (a known failure mode where the claimed clean sweep cannot be audited), so the orchestrator re-ran the full 8-round `setsid` sweep itself. First attempt was misconfigured by the orchestrator (`--start-command "bash start.sh"` without the `cd`, so every round died with `bash: start.sh: No such file or directory`); relaunched with the full `cd .../implementation && bash start.sh`. Independent result: **142/142 passed, 0 failed, in every one of the 8 rounds**, artifacts persisted at `workspace/implementation/results.{1..8}.json`.

Note for Step 8: Step 7 reported **0 implementation/ fixes**, so per the skill's skip condition Step 8 would normally be skipped only when deletions AND test_suite AND test_helpers AND implementation fixes are all zero. Here there were 2 `test_helpers/` fixes and 3 `test_suite/` fixes (one of them a PRD-silence partial-coverage split), i.e. non-zero iterations beyond the baseline, so Step 8 runs.

## Step 8: Finalize PRD — 2026-09-05T05:17:00.000Z

Subagent summary (verbatim):

`workspace/PRD_FINALIZED.md` is written: 462 lines, byte-for-byte identical to `PRD.md` except one in-place sentence insertion in §3.6. It ends at the real section boundary (last row of the §5 error catalogue, `ERR_INVALID_TIME_WINDOW | 422`).

## Line counts
- `PRD.md`: 462 lines
- `PRD_FINALIZED.md`: 462 lines
- delta: 0 lines (+0.0%); the single edit extends line 269 in place.

## Changes
- §3.6 (backfill request creation) — **revise** — after "...in status `OPEN`." added: the seven named fields plus the §2.5 common properties are the whole of the record; it carries no field naming the cause of the shortfall beyond `triggering_assignment_id`, and `cancel_reason` is written only by the abandonment path — `implementation/services.py:745-759` (creation) and `implementation/serialize.py:175-186` (projection).

## Per-edit pre-edit search log
**Edit 1 — §3.6 backfill-request field set** (traces to the `test_02_reliability_and_probation.py` fix, which dropped an assertion on a nonexistent `reason` attribute)
- (a) Subject: the complete set of persisted/serialized attributes on a backfill request, and which of them record a "reason".
- (b) Impl paths enumerated (grepped `backfill` across all of `implementation/`, excluding `in_backfill_pool`, then read each hit): `services.py:745` `open_backfill_request` (sole creator — exactly 7 fields); `serialize.py:175` `backfill_request_json` (sole projection — same 7 keys + `_common` at `serialize.py:22`: `id`, `created_at`, `updated_at`, `version`); `routes_work.py:341-354` no-show cascade (creation callsite); `routes_work.py:363-371` release compensation (writes only `status`, `selected_staff_member_id`, `filled_assignment_id`); `routes_work.py:411-456` auto-fill (writes `attempt_count`, `status`, `selected_staff_member_id`, `filled_assignment_id`); `routes_work.py:459-471` cancel (sole writer of `cancel_reason`); `routes_work.py:379-408` read/list; `core.py:30,122` table + 404 mapping. No path anywhere writes or exposes a `reason` field.
- (c) Wording adjustment: an initial draft said the record carries "no separate reason field", which would have falsely excluded `cancel_reason` (written by `routes_work.py:470`). Re-scoped to "no field naming *the cause of the shortfall* beyond `triggering_assignment_id`" and added the explicit carve-out that `cancel_reason` is written by the abandonment path, and included "together with the common resource properties of §2.5" so the claim does not exclude `id`/`created_at`/`updated_at`/`version`.

## Step 7 items deliberately NOT patched (with verification)
- `test_helpers/factories.py` `_family_payload()` merge helper — a Python duplicate-keyword bug in fixtures; no impl behavior involved, and the ~57 unblocked tests then passed against an unmodified `implementation/`, so no PRD silence or mismatch is implied.
- `test_helpers/assertions.py` `err()` returning `data` instead of a nonexistent `error` key, and the two corrected call sites in `test_18`/`test_20` — PRD §2.2 already fixes the error envelope verbatim, and `core.py:268-272` (`respond_error`) emits exactly `{"meta": ..., "response_type": "error", "data": {"error_id", "message"}}`. Prose kept verbatim.
- Latent `assertions.expected_surcharge_bp()` strict-`>` bug — verified the *implementation* is on the PRD's side: `calc.py:97-104` uses `>=` against `calc.py:17-19` floors 300/150/60 with 900/600/350 bp, matching §3.2's "300 heads or more / at least 150 / at least 60" exactly. The defect is confined to the unused test helper, so no PRD change.
- Step 7 applied no fixes to `implementation/`, which is consistent with a near-verbatim finalized PRD.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (269), byte count 98273 -> 98538 (+265 B), tail ends on the final error-catalogue row. Step 8 was NOT skipped because Step 7 had non-zero artifact fixes (2 in `test_helpers/`, 3 in `test_suite/`).

## Step 9: Complete PRD — 2026-09-05T05:55:00.000Z

Run as three sequential passes partitioned by implementation module, so that no single subagent had to hold all 4,346 lines of `implementation/` in context. All three passes edited the same `workspace/PRD_COMPLETED.md`; pass 1 performed the `cp` from `PRD_FINALIZED.md`, passes 2 and 3 were explicitly forbidden from re-copying it, and each pass was told which modules the earlier passes had already covered so it would neither re-pin nor contradict them.

### Pass 1 — global layer (`app.py`, `core.py`, `calc.py`, `serialize.py`) — subagent summary (verbatim)

Pass 1 complete. `PRD_COMPLETED.md` created from `PRD_FINALIZED.md` and patched.

Counts: source `PRD_FINALIZED.md` 462 lines / 98,538 chars; output `PRD_COMPLETED.md` 467 lines / 103,473 chars (+4,935 chars, +5 lines). `diff` touches 27 lines (16 added/replacement lines across 12 hunks). Not byte-identical. File still ends at the real §5 boundary. 11 ambiguity-pins, 1 mismatch-revision.

Changes:
- §2.1 — insert — ambiguity — `X-User-ID` inspected only on mutating requests (a read carrying only `X-User-Role` is accepted); whitespace-only counts as empty — core.py:284-297.
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`-`Z`/`0`-`9` — core.py:233-237.
- §2.2 — revise — ambiguity — pagination `meta` keys appear on windowed list reads only; batch bid adjudication and payout run answer `response_type` `array` with a 2-key `meta` — core.py:505-508, routes_staffing.py:507, routes_events.py:324.
- §2.2 — insert — ambiguity — surface-level refusals reuse the envelope: unknown path → 404 `ERR_NOT_FOUND`, wrong method → 405 `ERR_VALIDATION_FAILED`, server fault → 500 `ERR_INTERNAL` (all outside the §5 catalogue); trailing slashes accepted — app.py:35-59, app.py:23.
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` → 422; empty-string query param means omitted; enum filters validated → 422; boolean filters accept `true|1|false|0` case-insensitively; over-run `offset` yields empty data with `has_more` false — core.py:447-492, core.py:255-265.
- §2.5 — insert — ambiguity — one rendering shape for every instant including date-named fields (`event_date`, `seniority_date`, `issued_on`, `expires_on`); offsets normalized, naive read as UTC, sub-ms truncated; unparseable → 422 — core.py:147-174, serialize.py:33,106,133.
- §2.5 — insert — ambiguity — "absent" fields are present as JSON `null`, not omitted — serialize.py (all projections).
- §2.5 — revise — MISMATCH — a re-derivation that reproduces the stored value moves neither `updated_at` nor `version`; several recomputed fields in one request still move `version` by 1; a client revision always moves it by 1 even when nothing changed — core.py:203-217, services.py:153-177, routes_staffing.py:165-166, routes_events.py:210.
- §2.5 — revise — ambiguity — satisfaction responses omit `updated_at`/`version` outright rather than rendering `null` — serialize.py:257-267.
- §2.6 — revise — ambiguity — ratios/multipliers rendered as JSON numbers, never strings — serialize.py:13-18,55.
- §2.6 — revise — ambiguity — identical-`created_at` ties break by write order — core.py:220-222, core.py:192.
- §2.9 rung 3 — insert — ambiguity — absent/unreadable body = empty object; non-object JSON body → 422; booleans rejected where numbers required; undeclared body fields ignored; explicit `null` on an optional field → 422 unless the field's rule clears on `null` — core.py:304-310,313-320,403-440.
- §3.2 — revise — ambiguity — `required_certifications` must be an array of the four codes; duplicates collapse, first appearance fixes order — core.py:368-377.
- §3.10 — revise — ambiguity — `planned_headcount` of 0 yields `fill_rate_bp` 0 rather than failing — calc.py:232-239.

Every calc constant and rounding mode was checked against §3.1/§3.2/§3.4/§3.6/§3.8/§3.9/§3.10 and matched except the zero-denominator case; every serializer field set matched existing prose.

### Pass 2 — services + staffing/workforce (`services.py`, `routes_staffing.py`, `routes_workforce.py`) — subagent summary (verbatim)

Pass 2 complete. Lines 467 → 467; `wc -c` 103,473 → 107,588. 15 distinct lines changed (16 targeted Edit calls); all edits in-paragraph, no new sections, no paths/HTTP methods introduced into §3, file still ends at the final `ERR_INVALID_TIME_WINDOW | 422` row. Pass 1's inserted wording untouched. Counts: 15 ambiguity-pins, 2 mismatch-revisions.

- §2.10 — insert — ambiguity — a `CLOSED` block is permanently outside the fill derivation: `filled_headcount` keeps being recomputed (a `COMPLETED` row still counts) but `status` never re-derives — services.py:157-159, 292
- §3.1 — insert — ambiguity — opening a plan is not gated on the event's status at all — routes_staffing.py:180-210
- §3.2 — revise — MISMATCH — "identified by its `code`" implied uniqueness; impl enforces none, so a duplicate code is accepted and `created_at` breaks the code ordering — routes_staffing.py:92-105, 125
- §3.2 — insert — ambiguity — `required_headcount_override` sent as `null` on creation reads as absent — routes_staffing.py:282-286, 306-308
- §3.2 — revise — ambiguity — on a revision `null` clears the override; a lone bound is ordered against the stored other bound after the block resolves; the plan's state is tested before the block's own `CLOSED` state — routes_staffing.py:282-286, 375-392
- §3.4 — insert — ambiguity — the eight declared standing moves enumerated; the only undeclared pair `SUSPENDED → PROBATION` is refused `ERR_STAFF_MEMBER_NOT_ACTIVE` — routes_workforce.py:54-63, 165-169
- §3.4 — revise — MISMATCH — `in_backfill_pool` goes false on every target but `ACTIVE`, `PROBATION` included — routes_workforce.py:181-185
- §3.4 — insert — ambiguity — worker list filters `status`, `employment_type`, `in_backfill_pool` — routes_workforce.py:110-121
- §3.4 — insert — ambiguity — a hand-recorded demotion to `PROBATION` runs no cascade, not even the elevator cancellation — routes_workforce.py:187
- §3.4 — revise — ambiguity — the failed `PROBATION → ACTIVE` reinstatement error is `ERR_STAFF_MEMBER_NOT_ACTIVE` — routes_workforce.py:170-179
- §3.4 — insert — ambiguity — revoke's `reason` is mandatory but stored nowhere, and revocation has no state guard — routes_workforce.py:261-270
- §3.5 — insert — ambiguity — an assignment is born with `check_in_at`/`checked_out_at` absent, `late_check_in` false and the four money/minute columns at 0 — services.py:397-417
- §3.5 — insert — ambiguity — the batch sweep's own gates: block not `CLOSED` (`ERR_SLOT_STATE_INVALID`) then plan `ACTIVE` (`ERR_PLAN_STATE_INVALID`), event status never consulted — routes_staffing.py:444-455
- §3.5 — insert — ambiguity — a batch award from `SUBMITTED` records `decision_reason` `MANUAL_AWARD` — routes_staffing.py:490-492
- §3.5 — revise — ambiguity — the three decline reasons are the sweep's whole vocabulary, so a same-block duplicate declines as `REST_CONFLICT` and capacity never declines; the answer lists ranked bids first in ranking order, then declined bids by `created_at` ascending — routes_staffing.py:466, 503-507
- §3.10 — insert — ambiguity — payroll passes over `PENDING` rows as it does `VOIDED`, and answers in the gratuity ranking order — services.py:681-691
- §3.10 — insert — ambiguity — a `zone_code` narrowing scopes `response_count`/`average_score`/`promoter_share_bp`/`zone_breakdown` but not the two issue counters — services.py:526-557
- §3.10 — insert — ambiguity — each recommendation group carries `position_type_id` and the family's `code` — services.py:610-624

Two dead helpers found and deliberately not documented: `services.recompute_reliability`/`auto_probation` (superseded by `settle_reliability`+`elevator_cascade`) and `rederive_slot_status` (no callers).

### Pass 3 — remaining routes (`routes_events.py`, `routes_work.py`, `routes_guest.py`, `routes_access.py`) — subagent summary (verbatim)

Pass 3 of 3 complete. 34 targeted Edit calls; no other file touched. Lines 467 → 467; `wc -c` 107,588 → 114,068. 31 lines changed; every change an in-paragraph insert or revision, no new sections, no new §5 rows. Integrity confirmed: ends at `| ERR_INVALID_TIME_WINDOW | 422 |`, all 29 headings §1–§5 intact, §4 still 66 endpoint rows and §5 still 43 error rows, no prose line cut mid-sentence. The pre-pass baseline was reconstructed by reverse-applying the 34 edits and matched 467 lines / 107,588 bytes byte-for-byte, so passes 1 and 2 were left fully intact. §3 remains free of URL paths and HTTP method names. Every newly named error_id already existed in §5; the only prose ids absent from §5 are `ERR_NOT_FOUND` and `ERR_INTERNAL`, both from pass 1's §2.2 sentence that explicitly declares them out of catalogue scope.

Counts: 27 ambiguity-pins, 7 mismatch-revisions.

- §2.4 — insert — ambiguity — `current_utc` required; response `data` carries exactly one field — routes_events.py:51
- §2.9 — insert — ambiguity — every declared string, required or optional, refused when empty/whitespace-only — core.py:327
- §3.1 — insert — ambiguity — `historical_actual_attendance` nullable: absent on filing, clears on revision — routes_events.py:64
- §3.1 — insert — ambiguity — both door bounds judged before the event lookup; a single bound tested against the stored other bound after resolution — routes_events.py:161
- §3.1 — insert — ambiguity — HISTORICAL_ACTUAL plan keeps its stored basis when the event carries no historical figure — routes_events.py:196
- §3.1 — revise — MISMATCH — revision re-derives both ledger totals with no version bump of its own, event version +1 exactly once; lowering the budget below approved is accepted and remaining goes negative — routes_events.py:209
- §3.3 — insert — ambiguity — `target_status` validated against all five statuses; `reason` nullable, otherwise non-empty, recorded nowhere — routes_events.py:228
- §3.3 — insert — ambiguity — the exactly-one-ACTIVE-plan failure is `ERR_PLAN_STATE_INVALID` — routes_events.py:250
- §3.5 — insert — ambiguity — bid filing takes only the event gate and the duplicate test — routes_work.py:110
- §3.5 — insert — ambiguity — manual award: slot then plan state after bid state; event status not consulted — routes_work.py:166
- §3.6 — insert — ambiguity — StaffMember NO_SHOW/RELEASE refusal decided from `action` before the assignment resolves; the three SCHEDULED-only movements refuse a CHECKED_IN row — routes_work.py:276
- §3.6 — insert — ambiguity — check-in block gate is `ERR_SLOT_STATE_INVALID`, event gate judged first — routes_work.py:304
- §3.6 — insert — ambiguity — check-out gated on neither event nor block — routes_work.py:289
- §3.6 — insert — ambiguity — no-show does not consult the block's status — routes_work.py:304
- §3.6 — insert — ambiguity — release block gate is `ERR_SLOT_STATE_INVALID` — routes_work.py:309
- §3.6 — insert — ambiguity — auto-fill ignores remaining capacity, so a block can exceed `required_headcount` — routes_work.py:439
- §3.6 — insert — ambiguity — UNFILLABLE escalation only from OPEN/PARTIALLY_FILLED; abandoning a non-OPEN request is `ERR_BACKFILL_NOT_OPEN` — routes_work.py:441
- §3.7 — insert — ambiguity — `severity` always required; `seat_reference` nullable; intake takes no event gate — routes_guest.py:126
- §3.7 — insert — ambiguity — escalation child inherits the parent's `reported_by_user_id`, opens with no responder and refund state NONE — routes_guest.py:252
- §3.8 — insert — ambiguity — missing `relocation_zone_code` is `ERR_VALIDATION_FAILED` before the issue resolves — routes_guest.py:296
- §3.8 — insert — ambiguity — a zone supplied with any other resolution is discarded — routes_guest.py:337
- §3.8 — insert — ambiguity — reopen keeps `assigned_staff_member_id` — routes_guest.py:361
- §3.8 — revise — MISMATCH — the ask is non-negative, drives PENDING from any prior refund state without clearing `refund_approved_cents`, admitted from every status but CLOSED — routes_guest.py:391
- §3.8 — revise — MISMATCH — supervisor-capped approval enters AWAITING_AUTHORIZATION from whatever status was held — routes_guest.py:488
- §3.8 — revise — MISMATCH — director path re-derives the ledger by §2.11's full rescan rather than by a delta — routes_guest.py:491
- §3.8 — revise — MISMATCH — denial has no refund sub-state guard and re-derives the ledger, releasing money when it overrides a live authorization — routes_guest.py:434
- §3.9 — insert — ambiguity — pool staging takes no event gate; a revision re-derives `peak_committed_units` from live bookings and judges the refusal against it — routes_access.py:140
- §3.9 — insert — ambiguity — booking filing takes no pool/event gate and judges no capacity — routes_access.py:158
- §3.9 — insert — ambiguity — `REQUESTED` is not an admissible target, and a DENIED target without `denial_reason` is a schema refusal, both before the booking resolves — routes_access.py:225
- §3.9 — insert — ambiguity — the COMPLETED move takes no event or pool gate — routes_access.py:277
- §3.10 — revise — MISMATCH — PAYROLL also requires a CLOSED event; the gate precedes both phases' preconditions and yields `ERR_PAYOUT_PHASE_INVALID` — routes_events.py:302
- §3.10 — insert — ambiguity — the satisfaction summary takes no event-status gate — routes_events.py:331
- §3.10 — insert — ambiguity — response `comment` nullable; filing takes no event-status gate — routes_events.py:370
- §4 — revise — MISMATCH — lifecycle row no longer advertises `PLANNED` as a target — routes_events.py:235

All 11 implementation modules are now covered across the three passes: pass 1 `app.py`/`core.py`/`calc.py`/`serialize.py`, pass 2 `services.py`/`routes_staffing.py`/`routes_workforce.py`, pass 3 `routes_events.py`/`routes_work.py`/`routes_guest.py`/`routes_access.py`.

### Orchestrator verification of Step 9

- `PRD.md` 462 lines / 98,273 B → `PRD_FINALIZED.md` 462 lines / 98,538 B → `PRD_COMPLETED.md` 467 lines / 114,068 B. `PRD_COMPLETED.md` is emphatically NOT byte-identical to its source (+15,530 B, 109 changed lines vs `PRD_FINALIZED.md`), so the scan demonstrably ran.
- Structural integrity re-checked independently: 27 markdown headings, §4 holds exactly 66 endpoint rows, §5 holds exactly 43 error rows, the file ends on `| ERR_INVALID_TIME_WINDOW | 422 |` with a trailing newline — no truncation.
- Totals across the three passes: 53 ambiguity-pins and 10 mismatch-revisions.

## Pipeline complete — 2026-09-05T05:56:00.000Z

Final state: 142/142 tests passing in all 8 rounds of an orchestrator-run `setsid` stability sweep (`workspace/implementation/results.{1..8}.json`), zero tests deleted, zero implementation fixes, and `workspace/PRD_COMPLETED.md` written.
