## Step 1: Create task directory — 2026-09-04T17:29:00.000Z

Created `tasks/task_2762_police_professional_standards_early_intervention/` and its `workspace/` subdirectory. Index 2762 was pre-assigned by the orchestrating prompt; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-04T19:48:00.000Z

All three scaffold artifacts are complete and the lint is clean.

## Output files (all `yaml.safe_load` clean)
`/home/ubuntu/github/CodingPRD/tasks/task_2762_police_professional_standards_early_intervention/`
- `SCAFFOLD.yaml` — **3578 lines** (§1.0–§1.7 only; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — **3299 lines** (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — **4763 lines** (single key `scaffold_corner_design`)

## SCAFFOLD.yaml content
15 entities (Unit, Officer, HearingRoom, Complaint, Allegation, Investigation, InterviewSession, Discipline, Appeal, Reinstatement, OfficerActivityEvent, EarlyInterventionAlert, InterventionPlan, MonitoringCheckIn, CredibilityDisclosure), 61 endpoints (32 POST / 29 GET), 12 state machines, 14 calculations, 75 validations across a 13-priority masking ladder, 74 error codes, 8 roles, 2 OCC concurrency rules. Profile: `compliance_audit` / `event_sourcing`, graph topology, cyclic machines, `role_model: segregation_of_duties`, layers `rate_threshold_triggers, cascading_side_effects, dual_variant_calculation, optimistic_concurrency`, `consistency_model: immediate`. The "Generate task harder than expert level!" directive was deliberately excluded from `scenario:` so it cannot leak into PRD.md.

## Difficulty queue (§1.8) — 9 rules / 25 instances
`dual_variant_calc` (2), `combinatorial_formula` (3), `non_linear_state_machine` (3), `transitive_cascade` (3), `priority_pair_validation_conflict` (3), `boundary_precision_check` (4), `cross_entity_state_dependency` (3), `resource_temporal_overlap` (2), `compensating_invariant` (2).

## Corner queue (§1.9) — all 9 guide sections, 74 instances (51 with full test recipes, 23 `excluded_because` stubs)
entities 12/0 · state_machines 9/7 · calculations 5/9 · validations 6/3 · endpoints 5/1 · errors 7/0 · rbac 3/1 · cross_cutting_layers 3/2 · consistency_model 1/0 (real/stub).

## Audits
- `scaffold_lint.py`: **`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`** (1298 calls scanned)
- All **74** error ids are triggered somewhere in §1.8 ∪ §1.9 (0 missing); every instance name is unique across both design files; every `excluded_because.difficulty_instance` citation resolves to a real §1.8 instance name; all claim types are guide-sanctioned; no forbidden concurrency vocabulary remains.

## Scaffold defects found and fixed while writing §1.9 (9 clarifying edits total)
Notable this session: `Allegation.support_pct` was cited by §1.8 but never declared as a field (added, `source: computed`); `severity_code` was declared required on `POST /officers/{id}/activity-events` while the entity field declares `default: NA`, contradicting the Defaults claim (made optional); earlier fixes made `ERR_SUSTAINED_NOT_WITHDRAWABLE` reachable via a new Complaint `ADJUDICATION -> WITHDRAWN` transition plus an Investigation `PENDING_REVIEW -> VOIDED` cascade, and extended p8 `ERR_OFFICER_SEPARATED` to `POST /officers/{id}/employment-status` so the SEPARATED terminal lockdown is testable.

**Orchestrator verification:** all three files present; `grep "harder than expert"` over the three YAMLs returns nothing, so the difficulty directive did not leak via the scaffold. `workspace/` and `worklog.md` survived the subagent.

## Step 3: Copy shared files — 2026-09-04T19:48:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2762_police_professional_standards_early_intervention/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T20:07:00.000Z

PRD.md is complete at **576 lines**, ending at a real section boundary (the last row of the §5 table).

Output: `/home/ubuntu/github/CodingPRD/tasks/task_2762_police_professional_standards_early_intervention/workspace/PRD.md`

**Sections written, in order**
- `# Police Professional Standards API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Actors, Identity and RBAC / 2.2 API Response Structure (verbatim block) / 2.3 Pagination and List Ordering / 2.4 Record Identity, Timestamps and the Logical Clock / 2.5 Precision, Rounding and Day Arithmetic / 2.6 Version Pinning on Supersession Writes / 2.7 Nested Paths and the Order in Which Rejections Are Decided / 2.8 Cascade Integrity and Ledger Conservation / 2.9 Controlled Vocabularies
- `## 3. Business Logic & Workflows` — 3.1 Standing Reference Data and the Officer Record / 3.2 Complaint Intake: Classification, Priority and Routing / 3.3 Screening, Reclassification and Withdrawal / 3.4 The Investigation: Opening, Assignment and the Statutory Clock / 3.5 Interview Procedure and Officer Rights / 3.6 Findings and Adjudication under the Preponderance Standard / 3.7 Discipline, Appeal and Reinstatement / 3.8 The Early Intervention System / 3.9 Records Retention, Disclosure and Public Reporting
- `## 4. Endpoint Definitions` — 1 status-code preamble + 4-column table (Method, Path, Description, Authorized Role(s)), 61 rows
- `## 5. Error Code Catalogue` — 2-column table (Error ID, HTTP Status Code), 74 rows

**Coverage against the scaffold**
- Entities: 16/16, all 156 declared field names present in backticks.
- Endpoints: 61/61 in the §4 table, column count verified at exactly 4, roles copied per endpoint.
- State machines: 10 entities, 62/62 transitions expressed (arrow-pair form where possible, verbal form for the system cascades), including the cyclic `PLAN_REQUIRED -> PLAN_ACTIVE -> ESCALATED -> PLAN_REQUIRED` revolution and the `CLASSIFIED -> CLASSIFIED` reclassification self-loop.
- Calculations: 14/14, each with its constants, step order, boundary orientation and rounding site in prose (dual-variant matrix and dual-variant EIS score both given as two named variants with their divergence explained).
- Validations: all 74 error IDs also appear in the §2/§3 prose at their governing rule, with the 13-tier priority ladder and all three priority pairs in §2.7; both OCC rules in §2.6.
- Roles: 8/8, with the three entity-backed ownership comparisons spelled out.

**Hard Contract reports**
- **Contract 1 (Field-Name Coverage): PASS** — two independent passes. 203 identifiers checked (156 entity fields + endpoint `input`/output keys + both `occ_field`s + report group keys); 0 missing. Pass 1 found one gap (`plan_id`), which was patched into §3.8; pass 2 clean.
- **Contract 2 (Rule Coverage): PASS** — 62/62 transitions, 14/14 calculations with constants, 74/74 error conditions, all `applies_to` scopes carried in §2.7's endpoint-scoped ladder, all endpoint `side_effects` narrated (including the six sweep counters and five sweep effects, and the five SUSTAINED cascade links). Sibling-branch symmetry given explicit equal treatment for the five commander-driven dispositions and the three appeal outcomes. Only the five percentage constants (`0.05`, `0.10`, `0.20`, `0.25`, `0.30`) are absent as literals — deliberately rendered as "five percent per annum", "10/20/25/30 percent" per the no-operator-syntax rule.
- **Contract 3 (§3 Path Purity): PASS** — 0 backticked tokens inside §3 start with `/`, are a bare HTTP method, or combine method and path; every §3 reference is by role, state pair or action phrase.

Also verified: no pseudocode, operator syntax, `round_half_up`/`min`/`max` call forms, fuzzy words, or audit/contract footer anywhere in the file. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or grepped, and no sibling task directory was read.

**Orchestrator truncation check:** `wc -l` = 576; `tail` shows the file ending on `| ERR_SALARY_UNKNOWN | 422 |`, the 74th of 74 error rows — a completed table, not a mid-sentence cut. Section headings present in order (1..5). `grep "harder than\|expert level"` over PRD.md returns nothing, so the difficulty directive did not reach the PRD. No regeneration needed.

## Step 6: Generate implementation — 2026-09-04T20:47:00.000Z

The implementation is complete.

## Files written

`workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `app.py` | 72 | Flask factory, blueprint registration, `ApiError`/`HTTPException`/catch-all handlers, `app.run(host="0.0.0.0", port=$PORT)` |
| `core.py` | 570 | 75-entry error->HTTP map, `ApiError`, Decimal/ROUND_HALF_UP helpers, ISO-8601 formatter (3 fractional digits + `Z`), `Store` (15 in-memory dicts + logical clock + sequences), `new_row`/`touch`/`dump`, response envelope, header auth/RBAC decorator, schema + query validators, offset pagination |
| `calc.py` | 683 | Every constant and calculation |
| `svc.py` | 277 | Entity lookups, collection accessors, cascades (`recompute_officer_eis`, `create_alert`, `void_investigation`, `refresh_investigation_window`, ...), custom serializers |
| `routes/reference.py` | 296 | Units, hearing rooms, officers, employment status, activity events, EIS profile, logical clock |
| `routes/complaints.py` | 433 | Intake, allegations, classify/reclassify, withdraw, purge |
| `routes/investigations.py` | 309 | Open, assign, toll, findings, close |
| `routes/sessions.py` | 228 | Schedule, hold, postpone |
| `routes/discipline.py` | 447 | Disposition cascade, impose, appeals, reinstatement back pay |
| `routes/eis.py` | 397 | Sweep, alerts, intervention plans, monitoring check-ins |
| `routes/records.py` | 183 | Credibility disclosures, public outcome report |
| `start.sh` | 10 | `$PORT`, 0.0.0.0, `exec python3 app.py` in the foreground, executable, lazy pip install |
| `requirements.txt` | 1 | `Flask>=2.0.0` |

## Endpoints: 61 / 61

Enumerated from `app.url_map` — the count matches the PRD exactly, path for path.

## Coverage

State machines: Complaint (SCREENING/CLASSIFIED -> UNDER_INVESTIGATION -> ADJUDICATION -> CLOSED, plus REJECTED_INTAKE / WITHDRAWN / PURGED), Investigation (UNASSIGNED <-> ASSIGNED -> IN_PROGRESS <-> TOLLED -> PENDING_REVIEW -> CLOSED, VOIDED), Allegation dispositions incl. system-written WITHDRAWN and OVERTURNED_ON_APPEAL, InterviewSession, Discipline (PROPOSED -> IMPOSED -> APPEALED -> UPHELD/MODIFIED/OVERTURNED), Appeal, Reinstatement, Alert (OPEN -> PLAN_REQUIRED -> PLAN_ACTIVE -> ESCALATED -> PLAN_REQUIRED revolution, DISMISSED/CLOSED_SUCCESS), Plan, CheckIn, CredibilityDisclosure, Officer employment status.

Calculations: classification/routing/priority, intake reference codes, statutory windows with tolling, 8-condition investigator eligibility + deterministic selector, notice hours, the deliberate interval asymmetry (officer rest buffer = closed-interval +/-60 min buffered pair test; room capacity = half-open aggregate count), preponderance, the dual-variant discipline matrix (PRESUMPTIVE vs FINAL priors), back pay with interest, the dual-variant EIS score (ROLLING_12M vs PEER_RELATIVE) with decay and banding, check-in cadence, compliance score, retention by governing disposition, and the suppressed sustain-rate report.

## Smoke test

Booted on ports 21473-21475 and 21499 (each killed by captured PID only; all ports confirmed free, no broad kill ever issued). A full end-to-end path passed with zero server tracebacks: unit -> officers -> hearing room -> complaint (`CLASS_I`, priority 1, `CMP-000001`) -> allegation -> investigation (180 statutory days, cert 3) -> assignment (plus a `412 ERR_STALE_INVESTIGATION_VERSION` on a bad pin) -> session (notice_hours 216.0, 90 min) -> hold -> findings (support_pct 70.0, preponderance met) -> SUSTAINED disposition (presumptive 15 days) -> impose -> appeal filed/heard/MODIFIED -> reinstatement finalized (gross 35096, net 34096, total 34096) -> both EIS profile variants -> sweep -> investigation close -> outcome report (DG_B suppressed with nulls, trailing `SUPPRESSED` group disclosed). RBAC 403, 404, and the `limit>100` 400 all returned the correct envelope. Fresh boot via `start.sh` confirmed empty storage and clock at `2026-08-01T00:00:00.000Z`.

One real bug found and fixed while smoke-testing: `respond_object`/`respond_list` were passing raw data straight to `jsonify`, so `Decimal`s in hand-built response dicts (notably `sustain_rate_pct`) serialized as JSON **strings**. Both now run `jsonable()`, and the report verifies as `float 100.0`. All `.py` files compile clean; `__pycache__` removed.

**Orchestrator note:** Steps 5 and 6 were launched back-to-back as background agents. At the moment the impl agent started, neither `test_helpers/` nor `test_suite/` existed on disk (verified at 20:13 — still absent), and the impl prompt carried an explicit hard ban on reading either directory, so the isolation contract held.

## Step 5: Generate unit tests — 2026-09-04T22:22:00.000Z

All 76 design instances are now translated; the suite is complete and verified.

## Output layout (both at the task root, nothing under `workspace/`)

**`test_helpers/` (Stage 1, 2,872 lines):** `__init__.py` 91, `api_client.py` 338, `api_errors.py` 193, `assertions.py` 322, `constants.py` 152, `factories.py` 507, `fixtures.py` 821, `test_users.py` 96, `types.py` 352.

**`test_suite/` (7,290 lines, 101 test functions):** `conftest.py` 24; difficulty — `discipline_and_back_pay` 471/8, `eis_scoring` 329/8, `investigation_lifecycle` 402/8, `scheduling_overlaps` 443/6, `boundaries` 320/6, `validation_precedence` 358/6, `intervention_cycle` 227/4, `cascades` 258/4; corner — `entities` 622/12, `state_machines` 636/9, `errors` 1089/7, `validations` 407/6, `calculations` 378/5, `endpoints` 524/5, `cross_cutting` 421/4, `rbac` 381/3.

## Coverage

- **Queue A (difficulty):** 25/25 instances (D1-D25, no stubs) -> **50 tests**, every instance carrying >=2.
- **Queue B (corner):** **51/51 non-stub instances -> 51 tests** (one each). The 23 `excluded_because:` stubs (C16, C23-C28, C34-C42, C49-C51, C57, C68, C72, C73) were correctly not translated.
- **Skipped instances: none.** Every non-stub instance passed the PRD-first two-condition filter.

## Verification

- `python3 -m py_compile` clean over all 9 helper and 17 suite files; `pyflakes` clean (I also removed three pre-existing unused imports in `test_difficulty_eis_scoring.py`, `test_difficulty_investigation_lifecycle.py` and `test_difficulty_validation_precedence.py`).
- Tag/citation audit: `checked 300 missing 0 badtags 0 distinct 76 tests 101; untranslated OK instances: 0` — i.e. all 300 `PRD:` lines are literal substrings of `workspace/PRD.md`, all 101 `Design:` tags resolve to real non-stub instances, exactly one `Design:` line per test (101 lines / 101 tests), and all 76 instances are covered.
- No occurrences of "scaffold" anywhere in either directory; `__pycache__` removed; `find workspace -name test_helpers -o -name test_suite` returns nothing.

## Deviations forced by design/PRD conflicts (all resolved toward the PRD)

- **Illegal `interventions` vocabulary** in C63/C67/C70 (`PEER_MENTORING`, `USE_OF_FORCE_REFRESHER`) replaced with declared values (`RETRAINING`, `COUNSELING`, `PEER_REVIEW`).
- **C67 status code:** design asserts `ERR_PENDING_CHECKINS` at 422; the PRD's tier-10 list and error table say **409** — asserted 409.
- **C62/C64 appeal `outcome`:** design says null on a HEARD appeal; PRD says it is created `PENDING` — asserted `"PENDING"`.
- **C71 `evaluated_officer_count`** left unasserted (the standard seed has 4 officers vs the design's 3); all alert/profile figures asserted exactly (50.00 -> PLAN_REQUIRED, 67.50 with `FORCE_COUNT`, 0.00/NONE after the window moves).

**Orchestrator verification:** `test_helpers/` and `test_suite/` both sit at the task root; `find workspace -name test_helpers -o -name test_suite` is empty (no stray dirs to relocate). `grep -c 'def test_'` across `test_suite/*.py` totals 101, matching the reported count.

## Step 7: Run tests and iterate — 2026-09-04T23:33:00.000Z

## Summary

**Iterations run: 2.** Iteration 1: 91/101 in all 8 rounds (10 deterministic failures, zero flakiness). Iteration 2 after fixes: **101/101 in all 8 rounds.**

### Final per-round results (`results.$i.json`)

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 101/101 | 101/101 | 101/101 | 101/101 | 101/101 | 101/101 | 101/101 | 101/101 |

### Tests deleted
**None.** Every failing test traced to a verbatim, uniquely-derivable PRD rule; all 10 were artifact bugs (test-side mis-translations or one implementation over-enforcement), not PRD-silence cases.

### Fixes applied to `test_helpers/`
- **`factories.py`** — added `_role_payload()` merge helper and rewrote `commander_payload` / `investigator_payload` / `supervisor_payload` to merge defaults with overrides. They previously passed hardcoded kwargs *and* `**overrides` into `officer_payload`, so any caller varying one field raised `TypeError: got multiple values for keyword argument`.
- **`factories.py`** — replaced the `x or [default]` idiom in the three complaint payload builders and `intervention_plan_payload`. An empty list is falsy, so a test deliberately sending `reported_allegation_types=[]` silently got `["DISCOURTESY"]` instead, and the intended `ERR_INVALID_REQUEST` probe succeeded.
- **`fixtures.py`** — `file_supervisor_complaint` / `file_public_complaint` / `file_anonymous_complaint` now `pop` `subject_unit_id` (and `reporting_supervisor_officer_id`) from overrides instead of colliding with the positional argument.

### Fixes applied to `test_suite/` (assertions corrected toward PRD, none weakened)
- **`test_corner_endpoints.py`** — `test_reference_data_round_trips...` asserted `version == 1` on `Unit`/`HearingRoom`. PRD §2.4 states verbatim that for these both `updated_at` and `version` are "absent from the resource entirely"; now asserts absence.
- **`test_corner_state_machines.py`** — `test_opening_an_investigation...` expected `ERR_INVESTIGATION_ALREADY_EXISTS` on a re-open. The first open drove the complaint to `UNDER_INVESTIGATION`, so the tier-8 complaint-state check pre-empts the tier-10 rule; PRD: "the first violated rule determines the response". Now expects `ERR_COMPLAINT_STATE_INVALID`.
- **`test_corner_validations.py`** — asserted `compliance_score is None` mid-plan. PRD: completing a check-in means "The plan's `compliance_score` is recomputed" -> 100x1/2 = 50.00. Now asserts 50.00.
- **`test_corner_cross_cutting.py`** and **`test_corner_rbac.py`** — both ignored PRD §3.2's mandated cascade ("attaching an allegation ... appends a `system_generated` activity event of type `COMPLAINT_INTAKE` ... with `occurred_at` equal to the owning complaint's `received_at`"). Corrected the event counts (0->1, 1->2) and the downstream EIS figures: weighted total 4.0->5.0, `eis_score`/`composite_score` 10.00->12.50, `event_count` 1->2. Verified by hand against PRD's formula (intake base 1 x 1.0 severity x 1.0 decay + sustained base 4 = 5.0; x PATROL 1.0 x scale 2.5 + 0 bonus = 12.50, band `NONE`).

### Fixes applied to `implementation/`
- **`routes/investigations.py`**, findings submission — dropped the `maximum=100` cap on `evidence_weight_for` / `evidence_weight_against`. PRD §2.7 tier 4 enumerates the declared numeric ranges exhaustively and does not list the evidence weights, and PRD §3.6's own worked example uses weights of **5001 and 5000** to demonstrate that preponderance is decided on the rounded `support_pct`. The cap made that PRD-specified scenario unreachable.

**Note on the one PRD tension worked around rather than "fixed":** §3.2 calls the intake cascade event `system_generated`, while §3.8 says `system_generated` is "true only for the `COMPLAINT_SUSTAINED` events". The implementation sets it `True` per §3.2. The cross-cutting test deliberately does not assert `system_generated` on the `COMPLAINT_INTAKE` row, to keep the suite off that ambiguity; neither side was touched.

`worklog.md` was not read or modified by the subagent.

**Orchestrator verification:** I independently read all 8 `workspace/implementation/results.*.json` files after the final sweep — every one reports `passed = 101`, `total = 101`. Because Step 7 applied 1 implementation fix, Step 8's skip condition does not hold and Step 8 will run.

## Step 8: Finalize PRD — 2026-09-04T23:45:00.000Z

PRD_FINALIZED.md is written. Five inline edits, all traced to `<step_7_diff>` items.

**Size:** PRD.md 576 lines / 127,626 bytes -> PRD_FINALIZED.md 576 lines / 128,553 bytes (line count delta 0%; byte delta +0.73%). All edits are inline inside existing paragraphs; no sections added.

**Changes**
- §2.7 tier 4 (declared numeric ranges) — insert — added `evidence_weight_for` / `evidence_weight_against` "each at least 0 with no upper bound" to the tier-4 range enumeration, which previously omitted them entirely — `implementation/routes/investigations.py:235-240`.
- §3.6 (findings entry fields) — revise — replaced "on a scale from 0.00 to 100.00" / "on the same scale" with a non-negative, no-upper-bound rule (nominal 0.00-100.00, larger magnitudes accepted, negative refused as a tier-4 schema failure) — `implementation/routes/investigations.py:235-240`, `implementation/core.py:455-466`.
- §3.8 (activity events) — revise — `system_generated` is now "false for events recorded through this endpoint and true for the events the system appends of its own accord — both the `COMPLAINT_INTAKE` event of the allegation-attachment cascade in Section 3.2 and the `COMPLAINT_SUSTAINED` event of the sustained-disposition cascade", resolving the §3.2/§3.8 contradiction in favour of the implementation — `implementation/routes/complaints.py:208-215`, `implementation/routes/discipline.py:115-122`, `implementation/routes/reference.py:249-255`.
- §3.8 (plan creation) — insert — plan is created with `compliance_score` null, not 0.00, and stays null until the first completed check-in — `implementation/routes/eis.py:210`.
- §3.8 (completing a check-in) — revise — `compliance_score` is recomputed in the same request (1 of 2 on-time reads 50.00 mid-plan, not null), and sweeping a check-in to `MISSED` does not itself rewrite it — `implementation/routes/eis.py:334-338`, `implementation/calc.py:644-651`.

**Per-edit pre-edit search log**
1. §2.7 tier 4 — (a) subject: tier-4 numeric range validation of the two evidence weights. (b) enumerated: `investigations.py` findings handler (only validation site; `f_num(minimum=0)`, no `maximum`), `core.f_num` (type/min/max semantics; bools and non-numerics rejected as type failures), ordering of the body parse vs. the tier-6 `ERR_NOT_ASSIGNED_INVESTIGATOR` check (parse first, so tier-4 placement is right), grep of `evidence_weight` across all impl files (`complaints.py:195-196` init, `discipline.py:73` UNFOUNDED test) — no other range enforcement exists. (c) adjustment: wrote "with no upper bound" explicitly rather than a bare "at least 0", so the entry cannot be read as re-implying the old 100 cap.
2. §3.6 weights — (a) subject: accepted domain and stored form of `evidence_weight_for`/`_against`. (b) enumerated: `investigations.py:235-267` (validation + write + `calc.preponderance`), `calc.preponderance` (no clamping; `support_pct` naturally <= 100), `core.jsonable` (Decimal -> float, so no quantisation is observable), `complaints.py:195-196` (initial 0), `discipline.py:73` (`!= 0` for UNFOUNDED), §3.6's own 5001/5000 worked example, §4 endpoint table (states no ranges). (c) two adjustments: dropped a first draft sentence claiming weights "are not quantised on storage" (unobservable in JSON — would have been an invented, untestable claim), and changed "only a negative weight is refused" to "while a negative weight is refused" so the sentence does not imply non-numeric types are accepted.
3. §3.8 `system_generated` — (a) subject: the `system_generated` flag on every `OfficerActivityEvent`. (b) enumerated: all three creation paths via `grep append_activity_event|OfficerActivityEvent` — `reference.py:249` (client endpoint, `False`), `complaints.py:208` (intake cascade, `True`), `discipline.py:115` (sustained cascade, `True`) — plus `svc.append_activity_event` default (`False`); no other writer, and events are immutable. (c) adjustment: phrased the false case as "events recorded through this endpoint" rather than "supervisor-recorded", since the endpoint is also open to `SystemAdmin`; enumerated both cascades explicitly instead of a bare "system cascades" so the claim stays exactly as wide as the impl.
4. §3.8 plan creation — (a) subject: initial value of `InterventionPlan.compliance_score`. (b) enumerated: all four `compliance_score` sites — `eis.py:210` (create, `None`), `eis.py:334` (check-in complete), `eis.py:359-364` (close), `calc.compliance_score` (floors at 0, so a written score is never null); confirmed activation and the sweep never write it, and that close is reachable only from `ACTIVE`. (c) none needed; kept the claim scoped to creation.
5. §3.8 check-in completion — (a) subject: when `compliance_score` becomes/changes visible. (b) enumerated: `eis.py:315-340` (completion path, recompute inside the same request), `eis.py:343-375` (close recompute), the sweep's `PENDING -> MISSED` branch (verified it does **not** touch `compliance_score`), `calc.compliance_score` (100 x on-time / required - 15 x concerns, floored, 2 dp). (c) adjustment: added the explicit "sweeping to `MISSED` does not itself rewrite `compliance_score`" clause instead of a general "recomputed whenever the counters change", which would have been a false universal against the sweep path.

Items in the diff deliberately **not** patched: the three `test_helpers` fixture bugs (pure fixture defects — `TypeError` on kwargs, falsy-empty-list defaults, positional collisions), the `Unit`/`HearingRoom` version/`updated_at` absence (§2.4 verbatim already), and the re-open tier-8-before-tier-10 ordering (§2.7 tier ladder + §3.4 already determine `ERR_COMPLAINT_STATE_INVALID`), plus the corrected cascade event counts and EIS figures (fully derivable from §3.2 and §3.8's scoring table).

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` yields 20 lines — exactly the 5 changed lines and their context markers, so the file is a genuine minimal patch and not a byte-identical copy. Both files are 576 lines; PRD_FINALIZED.md still ends on the 74th error row, so nothing was truncated.

**Step 9 plan (orchestrator decision):** a single subagent cannot hold a 576-line PRD plus ~3,400 lines of implementation and still scan exhaustively, so Step 9 is run as three sequential passes partitioned by implementation module over one shared PRD_COMPLETED.md. Pass 1 performs the `cp` from PRD_FINALIZED.md and covers the cross-cutting modules (`app.py`, `core.py`, `calc.py`, `svc.py`); passes 2 and 3 must NOT re-copy, and each edits the file the previous pass left. Pass 2 covers `routes/reference.py`, `routes/complaints.py`, `routes/investigations.py`; pass 3 covers `routes/sessions.py`, `routes/discipline.py`, `routes/eis.py`, `routes/records.py`.

## Step 9: Complete PRD — 2026-09-04T23:52:00.000Z

Run as three sequential passes over one shared `workspace/PRD_COMPLETED.md`, partitioned by implementation module (rationale recorded at the end of the Step 8 entry). Totals: **66 edits — 52 ambiguity-pins, 14 mismatch-revisions.** PRD_FINALIZED.md 128,553 chars -> PRD_COMPLETED.md 144,999 chars (**+16,446**, +12.8%); 576 lines throughout, all growth in-paragraph, no new sections.

### Pass 1 — `app.py`, `core.py`, `calc.py`, `svc.py` (16 edits: 14 ambiguity, 2 mismatch)

Performed the `cp` from PRD_FINALIZED.md. 128,553 -> 132,799 chars (+4,246).

- §2.1 Actors/RBAC — insert — ambiguity — a header holding only whitespace counts as empty for `ERR_UNAUTHENTICATED` — `core.py:364`
- §2.2 Success envelope — insert — ambiguity — `api_request_id` is `req_` + 16 chars from lowercase letters and digits — `core.py:308-314`
- §2.2 Success envelope — insert — ambiguity — `api_request_timestamp` is read from real server time, not the logical clock — `core.py:315`
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` and out-of-domain filter values are `ERR_INVALID_REQUEST`; empty-string query param = omitted; booleans accept `true/false/1/0` any case; undefined query params ignored — `core.py:496-538`
- §2.3 List ordering — insert — ambiguity — `created_at` ties broken by write order — `core.py:277`
- §2.4 Timestamps — insert — ambiguity — every timestamp field renders as exactly `YYYY-MM-DDTHH:MM:SS.mmmZ` in UTC, including the date-named fields (`hire_date`, `effective_date`, `suspension_end_date`, `end_date`) which are full instants — `core.py:169-175`
- §2.4 Timestamps — insert — ambiguity — accepted input form: optional seconds/fraction, `Z` or offset normalised to UTC, bare calendar date rejected — `core.py:178-207`, `core.py:469-476`
- §2.5 Scores — insert — ambiguity — decimals render as bare JSON numbers, never strings, without trailing zeros; supplied decimals stored at given precision unless a formula names a rounding step — `core.py:284-293`, `core.py:455-466`
- §2.5 Money — insert — ambiguity — a fractional money value is a tier-4 schema failure, not something rounded — `core.py:440-452`
- §2.7 tier 4 — revise — ambiguity — absent/empty body = empty JSON object; non-object body rejected; JSON `null` counts as absent; undeclared fields ignored; string fields must hold non-whitespace — `core.py:387-419`
- §2.8 Cascades — insert — ambiguity — a recompute counts as a mutation even when the value is unchanged — `svc.py:149-165`
- §2.8 `open_case_load` — insert — ambiguity — the decrement is floored at 0 — `svc.py:218`
- §3.8 Activity events — **revise — mismatch** — `base_weight` is the event-type base weight **multiplied by the severity multiplier** (PRD said base weight alone) — `svc.py:178-180`
- §3.8 Peer-relative — **revise — mismatch** — the empty-pool/zero-mean fallback also reports `peer_mean` 0 and keeps the rolling band — `calc.py:606-617`
- §3.8 Profile read — insert — ambiguity — `weighted_total`/`peer_mean` reported rounded to 2 dp while unrounded values feed the score; `ROLLING_12M` reports `peer_pool_size` 0 and `peer_mean` 0 — `svc.py:264-277`
- §3.8 Alerts — insert — ambiguity — `run_sequence` is null on alerts no sweep has touched — `svc.py:187-203`
- §4 preamble — insert — ambiguity — off-catalogue pre-endpoint failures: `ERR_NOT_FOUND` 404 unmatched path, `ERR_METHOD_NOT_ALLOWED` 405 wrong method; trailing slash accepted — `app.py:39-55`

Verified-already-pinned: the error-code->HTTP map matches §5 exactly (74/74 ids, zero status mismatches, checked programmatically), and every `calc.py` formula and constant already matched the PRD — severity band, priority, screening gate, routing, `CMP-%06d`, statutory days/certification, `due_at`, the 8 eligibility conditions and 4 sort keys, closed-interval 60-minute officer buffer vs half-open room count, preponderance (strict > 50.00 on rounded `support_pct`), the 7-step matrix incl. class-A floor then 180 cap, per-period back pay + 5%/365 interest (worked example reproduces 840,002 / 715,002 / 7,150 / 722,152), the half-open 365-day EIS window with 180/181-day decay, indicator thresholds, x2.5 scale + 10/indicator clamped 0-100, peer scale 40, bands 30/50/75, check-in interval, compliance score, retention tables, and `sustain_rate` at 1 dp.

### Pass 2 — `routes/reference.py`, `routes/complaints.py`, `routes/investigations.py` (19 edits: 12 ambiguity, 7 mismatch)

No `cp`; 19 targeted Edits. 132,799 -> 136,462 chars (+3,663). Pass-1 insertions spot-checked present.

- §3.1 Standing reference data — revise — mismatch — `command_code` is no longer claimed unique across units (no such error in the catalogue) — `reference.py:38-59`
- §3.1 Employment dimension — revise — mismatch — the write polices only the *current* status, so a direct administrative `SUSPENDED` and a write repeating the stored value are both accepted; any accepted write targeting `ACTIVE` clears `suspension_end_date` — `reference.py:215-229`
- §3.2 Intake fields — revise — mismatch — `alleged_injury` is optional and defaults to false — `complaints.py:45`
- §3.2 Conditional intake fields — revise — mismatch — an empty/whitespace `complainant_name`/`complainant_contact` is a tier-4 `ERR_INVALID_REQUEST`, not `ERR_COMPLAINANT_IDENTITY_REQUIRED` — `complaints.py:50-51,82-87`
- §3.2 Conditional intake fields — insert — ambiguity — `reporting_supervisor_officer_id` resolved before `subject_unit_id`, so both-unresolvable reports `ERR_OFFICER_NOT_FOUND` — `complaints.py:71-74`
- §3.2 Allegation initial values — insert — ambiguity — `preponderance_met` starts false — `complaints.py:199`
- §3.2 Allegation cascade — insert — ambiguity — the `COMPLAINT_INTAKE` event carries `severity_code` `NA` and `source_reference` = the complaint `id`; the cascade never raises an alert — `complaints.py:208-216`
- §3.3 Classification — insert — ambiguity — `ERR_NO_INTAKE_UNIT` applies on the rejection path too — `complaints.py:271-272`
- §3.3 Screening accept — insert — ambiguity — routing uses the freshly re-evaluated screening gate before `screening_required` is cleared; `reclassification_count` untouched — `complaints.py:287-302`
- §3.3 Reclassification guard — insert — ambiguity — an accept from `CLASSIFIED`/`UNDER_INVESTIGATION` with no `classification_override` also yields `ERR_MAX_RECLASSIFICATIONS_REACHED` — `complaints.py:307-312`
- §3.3 Reclassification cascade — insert — ambiguity — a `CLOSED`/`VOIDED` investigation is left untouched — `complaints.py:321`
- §3.3 Withdrawal guards — revise — mismatch — the tier-6 credential is decided *before* the tier-8 status test; `intake_reference_code` is a required body field on every withdrawal — `complaints.py:346-354`
- §3.3 Withdrawal cascade — insert — ambiguity — an already `CLOSED`/`VOIDED` investigation is left alone — `complaints.py:375-379`
- §3.3 Withdrawal from ADJUDICATION — revise — mismatch — session cancellation runs on this path too — `complaints.py:379` + `svc.py:223-234`
- §3.4 Nominated investigator — revise — mismatch — re-nominating the current assignee is `ERR_INVESTIGATOR_CONFLICT`; caseload decided ahead of the certification bar — `investigations.py:144-150`
- §3.4 Tolling — revise — mismatch — no assigned-investigator ownership check; any `Investigator` may toll — `investigations.py:165-171`
- §3.6 Findings array — insert — ambiguity — absent / non-array / empty-array / non-object-member `allegation_findings` is `ERR_INVALID_REQUEST`, not `ERR_FINDINGS_INCOMPLETE` — `investigations.py:220-228`
- §3.8 Activity events — insert — ambiguity — `occurred_at` ties broken by `created_at` then write order; `source_reference` null when omitted — `reference.py:245,271`
- §3.9 Purge retention guard — insert — ambiguity — a missing `retention_until` also yields `ERR_RETENTION_NOT_EXPIRED` — `complaints.py:418-420`

### Pass 3 — `routes/sessions.py`, `routes/discipline.py`, `routes/eis.py`, `routes/records.py` (31 edits: 26 ambiguity, 5 mismatch)

No `cp`; 44 tool uses, targeted Edits only. 136,462 -> 144,999 chars (+8,537). Prior passes' distinctive phrases each grep to exactly 1 occurrence.

- §2.4 — revise — mismatch — bare `YYYY-MM-DD` remains a schema failure everywhere except the outcome report's two period bounds — `records.py:29,86-87`
- §2.7 tier 5 — insert — ambiguity — the sweep's optional `officer_id` added to the tier-5 officer-resolution list — `eis.py:38-40`
- §3.5 — revise — mismatch — interview subject need only resolve to an existing officer (no allegation-subject test); officer resolved before room — `sessions.py:56-57`
- §3.5 — insert — ambiguity — interviewability decided before the SEPARATED test — `sessions.py:62-65`
- §3.5 — insert — ambiguity — tier-11 order is window coherence -> officer rest buffer -> room count — `sessions.py:71-77`
- §3.5 — insert — ambiguity — scheduling touches the investigation only on `ASSIGNED -> IN_PROGRESS` — `sessions.py:96-98`
- §3.5 — revise — mismatch — hold preconditions reordered (SEPARATED ahead of notice); notice recomputed not rewritten; tested representation status is supplied-else-stored and is written back; investigation touched on every hold — `sessions.py:148-173`
- §3.5 — revise — mismatch — postponement carries no ownership check; `postpone_reason` required but never persisted; room resolved on the omitted path too — `sessions.py:182-195`
- §3.5 — insert — ambiguity — the postponed session is excluded from both of its own overlap calculations — `sessions.py:206-212`
- §3.5 — insert — ambiguity — postponement writes `hearing_room_id` and `status` back to `SCHEDULED`, nothing else — `sessions.py:219-227`
- §3.6 — insert — ambiguity — `rationale` validated but not persisted; `aggravator_count`/`mitigator_count` default 0 — `discipline.py:52-58`
- §3.6 — revise — mismatch — the disposition responds with the allegation at HTTP 200, never the created Discipline and never 201 — `discipline.py:88,140`
- §3.6 — insert — ambiguity — payload counts stored on the Discipline; event carries `severity_code` `NA` and `source_reference` = allegation id; the cascade alert is created regardless of an already-open alert with `run_sequence` null; disclosure `retention_until` = created_at + 2555d — `discipline.py:94-139`
- §3.7 — insert — ambiguity — omitted impose counts fall back to the stored proposal values and are written back; `effective_date` untested; not-sustained allegation -> `ERR_DISCIPLINE_STATE_INVALID`; other complaint statuses -> `ERR_COMPLAINT_STATE_INVALID` — `discipline.py:177-211`
- §3.7 — insert — ambiguity — the appeal is created with `modified_days`, `heard_at`, `decided_at`, `hearing_notes` all null — `discipline.py:255-259`
- §3.7 — insert — ambiguity — hear writes `hearing_notes` only when supplied; decide does not test the discipline's status, writes `modified_days` on the MODIFIED branch alone, and returns the appeal at 200 — `discipline.py:297-349`
- §3.7 — insert — ambiguity — a null `final_days` counts as 0 for the MODIFIED bound; the MODIFIED branch leaves `employment_status`/`suspension_end_date` untouched — `discipline.py:338-365`
- §3.8 — insert — ambiguity — targeted rescore ignores employment status; the run returns the six-counter object at 200; `evaluated_officer_count` is 1 on the targeted path; `run_sequence` is a monotonic server counter from 1 that only accepted runs consume — `eis.py:40-115`
- §3.8 — insert — ambiguity — sweep order and unconditional score/band write; open-alert selection; the refresh writes `NONE` verbatim and always counts as a mutation; `score_variant` always `ROLLING_12M`; only `OPEN -> PLAN_REQUIRED` counts as promoted; the time-driven check-in/disclosure sweeps are department-wide on both paths — `eis.py:63-104`
- §3.8 — insert — ambiguity — an alert's `plan_count` only rises; `dismissal_reason` null until dismissal; `PLAN_ESCALATION` never appears on a stored alert — `eis.py:159-160,214,388-392`
- §3.8 — insert — ambiguity — the dismissal decrement of `open_alert_count` is floored at 0 — `eis.py:164`
- §3.8 — insert — ambiguity — `interventions` is a non-empty array stored verbatim including repeats; `supervisor_officer_id` need only exist — `eis.py:186-203`
- §3.8 — insert — ambiguity — `activation_note`/`closing_note` validated but persisted nowhere; the successful-close decrement is floored at 0; escalation raises the band leaving `eis_score` unchanged; a completed check-in stores `notes` only when supplied — `eis.py:253,326-327,348,384,395`
- §3.9 — insert — ambiguity — `requesting_party` required but not persisted — `records.py:68`
- §3.9 — insert — ambiguity — both report bounds are required and a bare `YYYY-MM-DD` reads as midnight UTC — `records.py:82-91`
- §3.9 — revise — mismatch — the population is `CLOSED`, `WITHDRAWN` or `PURGED` with non-null `closed_at` in an inclusive window; `REJECTED_INTAKE` excluded; a null demographic code groups as `UNKNOWN` — `records.py:125-142`
- §3.9 — insert — ambiguity — the trailing `SUPPRESSED` group carries `suppressed` false with its own rate and is emitted only when something was suppressed; top-level `breakdown` echoes `ALL` when omitted — `records.py:156-174`

Pass 3 flagged one fact now stated in two voices: §4's blanket "creates -> 201" rule contradicts the disposition endpoint (creates a Discipline, returns 200 + allegation) and the decide endpoint (creates a Reinstatement, returns 200 + appeal). Because the §4 preamble was pass 1's territory, pass 3 pinned both exceptions locally in §3.6/§3.7 rather than reaching across the partition. **Orchestrator adjudication:** left as pass 3 wrote it. The local carve-outs are unambiguous and correct against the implementation, so a fresh implementer reading §3.6/§3.7 lands on 200 for both endpoints; editing §4's preamble as well would add a second statement of the same fact without changing any derivable behavior, and the whole-file scan is finished, so it is not worth reopening a pass to restate it.

### Orchestrator verification of the finished artifact

- `PRD_COMPLETED.md` exists at `workspace/PRD_COMPLETED.md`, 576 lines / 144,999 chars. `cmp` against PRD_FINALIZED.md confirms it is **not** byte-identical (the failure mode where the scan silently never ran); `diff` reports **59 changed lines**, i.e. roughly one in ten lines of the document was revised.
- Structure intact: 5 `##` sections in order, and §5 still carries all **74** error rows, ending on `| ERR_SALARY_UNKNOWN | 422 |` — a real section boundary, no truncation from any of the three passes.
- `implementation/` was not modified by Steps 8 or 9 — the newest source mtime is `routes/investigations.py` at 22:35, which is Step 7's last fix and predates Step 8's 22:59 start. The final 8-round sweep therefore still stands: I re-read all eight `results.$i.json` files and every round reports **101 / 101**.
- Housekeeping: exactly one `worklog.md` in the tree (the stray copy created by a cwd drift during Step 8 was appended into this file and deleted, preserving append-only order); no `test_helpers`/`test_suite` directories anywhere under `workspace/`.

**Pipeline complete.**
