# Worklog — task_2981_building_trades_hiring_hall_dispatch

## Step 1: Create task directory — 2026-09-06T01:11:55.539Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2981_building_trades_hiring_hall_dispatch` and `.../workspace`. Index 2981 was pre-assigned by the orchestrating caller (no auto-allocation scan performed, to avoid collisions with the up-to-32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-06T03:15:00.000Z

Scenario 2981 scaffold complete, lint clean.

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_2981_building_trades_hiring_hall_dispatch/`)

**`SCAFFOLD.yaml`** — 2310 lines, §1.0–§1.7 only (contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`):
- 12 entities (Local, Member, SkillEndorsement, OutOfWorkList, Registration, Contractor, JobRequest, Referral, Dispatch, RatioPolicy, Grievance, DispatchLedgerEntry), topology `graph`
- 5 state machines / 31 transitions (Registration, JobRequest, Referral, Dispatch, Grievance), shape `cyclic`
- 1 §1.2.1 concurrency rule (`referral-issue-stale-job-request`, `expected_job_request_version` → 412)
- 7 calculations (dispatch_order_ranking, named_call_and_skill_allowance, traveler_credited_seniority_hours, apprentice_ratio_cap, effective_refusal_strikes, back_pay_make_whole, registration_timing_windows) — two of them dual-variant
- 40 ordered validations, 49 endpoints, 48 errors, 5 roles (`role_model: segregation_of_duties`, consistency `immediate`)

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 1875 lines, single top-level key; 9 rule_ids × 2 = **18 instances**.

**`SCAFFOLD_CORNER_DESIGN.yaml`** — 4487 lines, single top-level key; **79 instances** (59 full test recipes + 20 `excluded_because` stubs citing §1.8 instances), across all nine sections: entities 12, state_machines 15, calculations 9, validations 8, endpoints 6, errors 21, rbac 4, cross_cutting_complexity_layers 3, consistency_model 1.

## Verification
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    49
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  1096
```
One lint iteration was needed: a capture of `$.data.decision` on `GET /grievances/{id}` (Grievance declares `status`/`decided_at`/`decided_by_user_id`, no `decision` field) — replaced with `decided_at` + `decided_by_user_id`. All 48 error codes are triggered somewhere in the §1.8+§1.9 union; instance names are unique across both design files.

## Two disclosures
1. The leading directive line ("Generate task harder than expert level!") was deliberately **omitted** from `scenario:` — it leaks into PRD.md via the scaffold; `difficulty_level: expert` is recorded instead.
2. The Expert band is deliberately overshot (49 endpoints / 48 errors / 40 validations) to carry the extra difficulty.

Scratch was confined to `.scratch/step2/` and has been removed (the empty `.scratch/` parent is left in place); `worklog.md` and `workspace/` were not touched, and nothing outside the task directory was modified. No sibling task directory was read.

---
Orchestrator verification of Step 2: all three YAML files parse cleanly (2310 / 1875 / 4487 lines); `grep -i "harder than expert|expert level"` over SCAFFOLD.yaml returns nothing, so the difficulty directive did not leak into the PRD-visible scaffold; `workspace/` survived the scaffold subagent. Step 2 was spawned twice — the first Agent call died instantly with an unexplained API error before doing any work, so it left no artifacts and the retry ran clean.

## Step 3: Copy shared files — 2026-09-06T03:16:36.337Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-06T03:28:58.248Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2981_building_trades_hiring_hall_dispatch/workspace/PRD.md` — **430 lines / 95,159 bytes**, built incrementally (1 Write + 6 heredoc appends + 1 generated-table append), ends cleanly at the last row of the §5 error table with no audit footer and no mid-sentence truncation.

**Full heading list**

```
# Building Trades Hiring Hall Dispatch API — Product Requirements Document
## 1. Introduction
## 2. Global Specifications & System-Wide Principles
### 2.1. User and Role-Based Access Control
### 2.2. API Response Structure          (+ #### Standard Success / #### Standard Error)
### 2.3. Pagination
### 2.4. Resource Identity, Audit Columns, and the Two Reduced-Shape Records
### 2.5. The Logical Hall Clock, and How Windows Close
### 2.6. Nested Paths and Referential Existence
### 2.7. The Order in Which the Hall Says No
### 2.8. Version Pinning on Referral Issuance
### 2.9. Basis Points, Integer Money, and Pinned Rounding Order
### 2.10. Segregation of Duties and the Five-Year Dispatch Record
## 3. Business Logic & Workflows
### 3.1. The Hall's Books: Locals, Members, and Certifications
### 3.2. List Groups and the Question of Who Is Next
### 3.3. Signing the Book: Registration, Reciprocity, and Preserved Position
### 3.4. Staying on the Book: Re-signing, Removal, and the Housekeeping Sweep
### 3.5. The Contractor Side: Intake, Allowances, and Delinquency
### 3.6. Issuing the Referral: Ratio, Order, and the Dispatcher's Discretion
### 3.7. Twenty-Four Hours to Answer: Acceptance, Refusal, and the Three-Strike Rule
### 3.8. On the Job: Layoff, Recall, and Hours Back to the Book
### 3.9. Grieving the Dispatch: Review, Remedy, and Make-Whole Pay
## 4. Endpoint Definitions
## 5. Error Code Catalogue
```

**Per-scaffold-section coverage (documented / declared)**

| Scaffold section | Declared | Documented |
|---|---|---|
| entities | 12 | 12 (97/97 field names in backticks) |
| state machines | 5 (31 transitions) | 5 / 31 |
| calculations | 7 (2 with variants) | 7 / both variant pairs |
| validations | 40 | 40, priority-ordered in §2.7 |
| endpoints | 49 | 49 rows, 4 columns |
| errors | 48 | 48 rows, 2 columns; all 48 also triggered in narrative |
| roles | 5 | 5, each `identity:` translated |
| concurrency_rules | 1 | 1 |

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 97 required, 97 present, 0 missing
- endpoints[].request_body: 54 required, 54 present, 0 missing
- endpoints[].query_params: 26 required, 26 present, 0 missing
- computed output / nested-object identifiers (sweep counters, dispatch-order
  projection, reciprocity_credits members): 15 required, 15 present, 0 missing
- enum + state enumeration values: 89 required, 89 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 40 checked, 40 expressed in prose (§2.7 states the full
  1→40 precedence with each error_id and its applies_to scope), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed
  (POST /hiring-hall/job-requests/{id}/referrals + expected_job_request_version +
  ERR_STALE_JOB_REQUEST_VERSION + 412 all named, §2.8), 0 missing
- state_machines[].transitions: 31 checked, 31 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed (no operator syntax, no fuzzy words;
  both pinned rounding orders and both dual-variant pairs stated), 0 missing
- validations[] conditions: 40 checked, 40 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 49 checked, 49 expressed, 0 missing
- entities[].fields[] structured content: 97 checked, 97 reconstructible from prose
  (types, ranges, defaults, initial values, null-when clauses), 0 missing
- sibling-branch symmetry: 7 groups checked (refuse good-cause / no-cause / third-strike;
  SUSTAINED vs DENIED; scheduled_hours vs actual_hours; strict_group_order vs
  short_call_interfiled; suspend vs reinstate; LAID_OFF vs FOR_CAUSE vs QUIT;
  OPEN->PARTIALLY_FILLED vs OPEN->FILLED), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 839
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 was appended by `cat` from `section-2.2-response-structure.md`, so it is byte-identical (diff shows only the trailing blank line I added as a section separator); `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING` and `"data": { }` are all intact.

Notes for the caller: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read. Only `workspace/PRD.md` was written; `worklog.md`, `INSTRUCTION.md` and the `SCAFFOLD*.yaml` files are untouched. Scratch was confined to `.scratch/step4/` and removed at the end (the `.scratch` parent itself was left in place). One methodological gotcha worth recording: the first Contract-1 sweep reported 94 false-positive "missing" fields because a naive `` `([^`]+)` `` regex pairs across the triple-backtick fences in §2.2 and flips backtick parity for the rest of the file — the verifier must strip fenced blocks before extracting inline code spans.

---
Orchestrator verification of Step 4 (truncation guard): `wc -l -c` = 430 lines / 95,159 bytes; `tail -c 1200` shows the file ending on the final `| ERR_REMEDY_NOT_APPLICABLE | 409 |` table row — a real section boundary, not a mid-sentence cut. 27 markdown headings present. `grep -i "harder than expert|expert level|scaffold"` over PRD.md returns nothing, confirming the Step 2 difficulty directive never reached the implementer-visible contract. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-06T05:34:00.000Z

Suite is complete and audited.

## Deliverables (both at the task root, `ls`-verified)
- `/home/ubuntu/github/CodingPRD/tasks/task_2981_building_trades_hiring_hall_dispatch/test_helpers/`
- `/home/ubuntu/github/CodingPRD/tasks/task_2981_building_trades_hiring_hall_dispatch/test_suite/`

Nothing was written under `workspace/` (confirmed: `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/`, none of which I read or touched). `.scratch/step5` removed; `.scratch/` parent left in place.

### test_helpers (9 files, 2,299 lines)
`__init__.py` 109, `api_client.py` 327, `api_errors.py` 129, `assertions.py` 302, `constants.py` 245, `factories.py` 429, `fixtures.py` 473, `test_users.py` 127, `types.py` 258.

### test_suite (conftest + 17 test files, 10,081 lines, 231 tests)
| file | lines | tests |
|---|---|---|
| conftest.py | 17 | - |
| test_01_dispatch_order_and_back_pay_variants.py | 445 | 7 |
| test_02_allowance_and_reciprocity_formulas.py | 335 | 8 |
| test_03_registration_and_request_state_cycles.py | 383 | 10 |
| test_04_refusal_and_delinquency_cascades.py | 416 | 12 |
| test_05_validation_precedence_conflicts.py | 347 | 8 |
| test_06_acceptance_and_ratio_boundaries.py | 355 | 10 |
| test_07_signatory_and_standing_dependencies.py | 279 | 8 |
| test_08_employment_and_referral_overlap.py | 382 | 9 |
| test_09_slot_and_ordinal_conservation.py | 349 | 9 |
| test_10_entity_shapes_and_field_derivation.py | 712 | 17 |
| test_11_lifecycle_transitions_and_guards.py | 1251 | 29 |
| test_12_computed_windows_and_ranking_inputs.py | 870 | 17 |
| test_13_eligibility_and_window_validations.py | 767 | 17 |
| test_14_endpoint_surfaces_and_actions.py | 862 | 18 |
| test_15_error_catalogue_triggers.py | 1257 | 32 |
| test_16_role_and_duty_boundaries.py | 577 | 12 |
| test_17_concurrency_and_visibility.py | 377 | 8 |

### Design-index coverage — 100%, zero skips
- **Queue A (§1.8 difficulty): 18/18 instances translated**, every one with >=2 tests (81 tests in `test_01`-`test_09`).
- **Queue B (§1.9 corner): 59/59 non-stub instances translated**, every one with >=1 test (150 tests in `test_10`-`test_17`): entities 12, state_machines 13, calculations 6, validations 6, endpoints 6, errors 10, rbac 4, cross_cutting_complexity_layers 1, consistency_model 1. The 20 `excluded_because` stubs were correctly not translated.
- No instance was skipped for the PRD-first filter, so there are no gap reasons to report.

### Machine-verified audits (whole suite)
- `python3 -m py_compile` on all 26 files: clean.
- `importlib.import_module` on all 17 test modules: clean.
- `pyflakes test_suite/*.py`: rc=0 (fixed a leftover unused local `home` in `test_02`; the only remaining warnings anywhere are the intentional re-export "imported but unused" lines in `test_helpers/__init__.py`).
- **PRD-citation sweep: 261 quotes across 17 files, all whitespace-normalized-verbatim in `workspace/PRD.md`** (0 missing).
- **Scaffold-citation sweep: 0 occurrences of "scaffold"** in any test file, conftest, or helper.
- **Design-tag audit: 231 tests, 231 tags, exactly one per test; 0 dangling tags, 0 tags pointing at excluded stubs**, tag strings byte-compared against the yaml `name:` values.

### Work done this session
1. Closed the three open `test_16` defects: replaced a fabricated §3.7 issuance quote with the verbatim §2.1 sentence "A `Dispatcher` works the out-of-work lists and is the only role permitted to issue a referral.", and dropped the unused `plus_days` / `validate_list` imports.
2. Wrote `test_17_concurrency_and_visibility.py` (377 lines, 8 tests): 3 tests for the OCC instance (version 1 issues and reserves a slot; the replayed version 1 -> 412 `ERR_STALE_JOB_REQUEST_VERSION` with version, open slots and referral count all unchanged; the refreshed version 2 issues to the next-ranked registrant with `total_count == 2`) and 5 for the immediate-consistency instance (accept response already carries the finished `WORKING` dispatch with `start_at == report_at` and the four null fields; referral `ACCEPTED` + registration `DISPATCHED_OUT` on the next reads; group `registered_count` 2 -> 1; request counters/`PARTIALLY_FILLED`/version 3; `REFERRAL_ACCEPTED` ledger row with `recorded_at` at the parked clock).

One PRD note worth flagging to the implementation side: §3.7 narrates a `registered_count` decrement at *both* issuance and acceptance, which read literally would double-decrement. §3.2 settles it authoritatively — "A group's `registered_count` is computed as the number of registrations currently on it whose `status` is `REGISTERED`" — so `test_17` asserts 1 (not 0) after the acceptance and cites that computed definition.

## Step 6: Generate implementation — 2026-09-06T05:34:00.000Z

The implementation is complete, boots cleanly, and covers the whole PRD.

## Files written (`.../task_2981_building_trades_hiring_hall_dispatch/workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | reads `$PORT`, guarded pip install, `exec python3 app.py` in the foreground |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `core.py` | 167 | in-memory `Store` (12 dicts), logical clock (default `2026-08-01T00:00:00Z`), all constants/enums, `iso`/`parse_iso` (3 fractional digits), `round_half_up_div`, `touch` |
| `envelope.py` | 104 | §2.2 envelope, `ApiError`, the 48-code -> HTTP map |
| `guards.py` | 227 | §2.1 auth/RBAC, §2.7 priority-3 shape validators, §2.3 pagination |
| `domain.py` | 321 | candidate pool + both ranking variants, `position_number`, strike arithmetic, allowances, ratio cap |
| `serializers.py` | 219 | 12 views; the two reduced-shape records emit only `id`+`created_at` |
| `services.py` | 179 | ledger append, withdrawal cascade, status re-derivation, three-strike cascade |
| `routes_admin.py` | 325 | clock, locals, list groups, members + standing cascade, endorsements, ratio policies |
| `routes_reg.py` | 309 | registration/reciprocity/preservation, renew, remove, 4-step housekeeping sweep |
| `routes_work.py` | 440 | contractors + delinquency/reinstatement, job-request intake, cancel, dispatch-order, referral issuance |
| `routes_ref.py` | 369 | referral reads, accept/refuse/withdraw, dispatch reads, layoff, recall |
| `routes_griev.py` | 267 | grievance file/review/adjudicate incl. dual back-pay variants, ledger reads |
| `app.py` | 58 | blueprints + `ApiError`/HTTPException handlers, `0.0.0.0:$PORT` |

**2,996 lines total.** Every module passes `python3 -m py_compile`. State is Python dicts only — a grep confirms no `open()`, sqlite, json.dump, pickle or shelve anywhere, and nothing is seeded.

## Coverage
- **Endpoints: 49/49.** Enumerated from `app.url_map` — exact match to the §4 table (paths, methods, and the role lists per row).
- **Error codes: 48/48.** A static audit of every module against `envelope.ERROR_HTTP` shows all 48 catalogue codes are raised somewhere and no non-catalogue code exists.
- Validation precedence 1-40 is implemented in-order per endpoint (e.g. issuance runs SoD-free 4->5->8->9->11->15->17->18->19->23->30->35->36->37->38).

## Smoke-test evidence (`PORT=18981 bash start.sh`, PID captured and killed; no broad pkill)

Envelope/error paths, e.g.
- `curl -X POST .../hiring-hall/locals -H X-User-ID:admin-1 -H X-User-Role:HallAdmin -d '{"local_number":48,...}'` → **201** `{"meta":{"api_request_id":"req_R8I0QDZYNCQ5YQ7Z3BT6","api_request_timestamp":"2026-09-06T03:47:34.790Z"},"response_type":"object","data":{"id":"bce10d95-...","local_number":48,...,"created_at":"2026-08-01T00:00:00.000Z","version":1}}`
- same POST with no headers → **401** `..."response_type":"error","data":{"error_id":"ERR_UNAUTHENTICATED","message":"Both X-User-ID and X-User-Role are required."}`
- `"kind":"NOPE"` → **422** `ERR_INVALID_REQUEST`; `GET /locals/does-not-exist` → **404** `ERR_LOCAL_NOT_FOUND`; Member role → **403** `ERR_ROLE_NOT_PERMITTED`; `?limit=0` → **422**; list → **200** with `meta.limit/offset/total_count/has_more`.

Two scripted end-to-end runs also verified, among others: `STRICT_GROUP_ORDER` vs `SHORT_CALL_INTERFILED` selecting *different* top candidates from identical data; per-entry reciprocity rounding (401 h x 5000 bp → 201); `named_call_allowance` 0 on short calls; `ERR_STALE_JOB_REQUEST_VERSION` (412); the ratio-cap asymmetry (apprentice refused at cap 0 pre-acceptance, allowed at cap 1 after); out-of-order override flag; short-call refusal charging a demotion but no strike; three long-call refusals → `REMOVED`/`THREE_REFUSALS` + 30-day cooling off + `dispatch_eligible:false`; `ERR_HOURS_EXCEED_ELAPSED` (40 h against 2 elapsed days); layoff → `LAID_OFF` + 7-day recall window + hours back to `local_hours_in_trade`; `FILLED`->`CLOSED` bubble-up; recall 201 inside and `ERR_RECALL_WINDOW_CLOSED` outside; position preservation inheriting `registered_at`; SoD 403; both back-pay variants (`SCHEDULED_HOURS` 2 weekdays → 16 h / 88000¢; `ACTUAL_HOURS` path exercised); delinquency suspension with `suspended_from_status` and asymmetric reinstatement; sweep report counts; and ledger purge flipping `purge_state:PURGED` with `snapshot_json:null`.

Scratch was confined to `.scratch/step6/` and removed at the end (sibling `.scratch/step5/` untouched); no server left running.

---
Orchestrator verification of Steps 5+6: both Agent calls were issued in a single assistant message, so the implementation generator was physically unable to read `test_suite/` (the directory did not exist at its spawn time). `test_helpers/` (9 files) and `test_suite/` (18 files) landed at the TASK ROOT, not under `workspace/` — `ls workspace/test_helpers workspace/test_suite` returns "No such file or directory" for both, so no move was needed. `workspace/` contains exactly INSTRUCTION.md, PRD.md, implementation/. Port 18981 is clear, so the Step 6 smoke server was not left running.

## Step 7: Run tests and iterate — 2026-09-06T05:58:13.776Z

## Step 7 complete — 8/8 rounds green

**Iterations run:** 2 (iteration 1 = baseline sweep + diagnosis; iteration 2 = verification sweep after one batch of three fixes)

### Final sweep evidence
`.../workspace/implementation/results.1.json` .. `results.8.json` (left in place as deliverables):

| round | passed / total | failed | errors | skipped |
|---|---|---|---|---|
| 1 | 233 / 233 | 0 | 0 | 0 |
| 2 | 233 / 233 | 0 | 0 | 0 |
| 3 | 233 / 233 | 0 | 0 | 0 |
| 4 | 233 / 233 | 0 | 0 | 0 |
| 5 | 233 / 233 | 0 | 0 | 0 |
| 6 | 233 / 233 | 0 | 0 | 0 |
| 7 | 233 / 233 | 0 | 0 | 0 |
| 8 | 233 / 233 | 0 | 0 | 0 |

Iteration 1 was 230/233 in **all 8 rounds** with an identical 3-test failure union — fully deterministic, no load-induced flakiness, so all three were real artifact defects.

### Tests deleted
None. All three failures survived STEP 1a/1b (each rule is verbatim in PRD.md and uniquely determined), so all three resolved at STEP 2 as test-artifact bugs.

### Fixes applied to `test_suite/`
- `test_suite/test_06_acceptance_and_ratio_boundaries.py` — `TestAcceptanceDeadlineBoundary::test_the_sweep_one_millisecond_late_expires_and_demotes`: the call site read `fx.accept_referral(scene["referral_a"]["id"], scene["zoe"]["id"])` while `fixtures.accept_referral(api, referral_id, member_id)` takes `api` first, so the test died with `TypeError: accept_referral() missing 1 required positional argument: 'member_id'` before issuing any HTTP request (known signature #8, symbol/arity drift — every other call site in the suite passes `api`); added the missing `api` so the minority call site matches the majority.
- `test_suite/test_12_computed_windows_and_ranking_inputs.py` — `TestCandidateSetFiltering::test_a_removed_registration_and_the_wrong_classification_are_never_candidates`: the test asserted `list_position_at_issue == 1` (`assert 2 == 1`), conflating the *candidate-pool rank* with the *list ordinal*. PRD §3.3 line 213 states `position_number` "is the one-based rank of the registration within its own list among the rows whose `status` is `REGISTERED`", and PRD §3.6 line 269 defines `list_position_at_issue` as "a snapshot of the selected registration's `position_number` at that moment" — the delinquent registrant (9,500 h) is dropped from the *pool* but keeps their `REGISTERED` row, so the sole surviving candidate (9,000 h) legitimately holds ordinal 2. Corrected the expectation to 2, pinned it to a new `RANKED_LIST_POSITION` constant, added a pre-issuance `fx.read_registration` cross-check so the assertion now ties the snapshot to the live `position_number` (strictly more faithful to PRD, not less), and added the two governing PRD quotes to the docstring.
- `test_suite/test_15_error_catalogue_triggers.py` — `TestOnlyOneLiveRegistrationAcrossEveryList::test_signing_the_same_list_twice_is_refused`: `KeyError: 're_registration_eligible_at'` came from indexing that field on a **Registration** payload. PRD §3.1 line 179 and §4 line 336 place `re_registration_eligible_at` on the **Member** ("`re_registration_eligible_at` is null for a member in ordinary standing"); no PRD sentence puts it on a registration. Redirected the assertion through `fx.read_member(...)` — the check is preserved and now reads the field on the entity PRD actually assigns it to.

### Fixes applied to `test_helpers/`
None needed. All three defects were localized to individual `test_suite/` call sites/assertions; no shared fixture, factory, header builder or assertion helper was implicated (no >=5-test shared-setup cluster appeared).

### Fixes applied to `implementation/`
None. The implementation was already faithful on all three points — in particular `domain.position_number` correctly ranks only `REGISTERED` rows under `intra_list_key`, and `serializers.member_view` correctly owns `re_registration_eligible_at`. Nothing in `workspace/implementation/` was modified in either iteration.

### Notes
- `workspace/sweep.sh` had no bugs and was not edited; the sanctioned `setsid nohup bash .../sweep.sh` launch was used verbatim both times, joined by polling `workspace/SWEEP_DONE` (fired ~7.5 min in) and only then reading the 8 per-round result files. Diagnosis used only `results.$i.json`; `sweep.log` was not used as evidence.
- `worklog.md`, `workspace/PRD.md`, `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not touched. `.scratch/step7` was removed; its parent left intact. No broad `pkill` was ever issued.
- One unconfirmed observation worth recording for later steps (no test failed on it, so I left it alone): `fixtures.laid_off_dispatch` defaults (`report_at` 2026-09-25T07:00, `layoff_clock` 2026-09-27T07:00, `hours_worked=40`) imply 2 elapsed calendar days against §3.8's 12-hours-per-elapsed-day cap of 24. No current test exercises that combination in a way that trips `ERR_HOURS_EXCEED_ELAPSED`, but a future test that does would need the fixture's clock widened rather than the cap relaxed.

---
Orchestrator verification of Step 7: re-read all 8 `results.$i.json` independently (keyed on `"status"`, not `"outcome"`). Every round reports `passed=233 total=233` with a status histogram of exactly `{'passed': 233}` — no failed/error/skipped entries anywhere, and `passed == total` in all 8. All 8 files are present and same-mtime (05:57), so this is one coherent sweep rather than stale artifacts. Green claim accepted.

Step 8 skip-condition evaluation: NOT skipped. Step 7 ran 2 iterations and applied 3 `test_suite/` fixes, so the zero-iteration skip condition does not hold. Note for Step 8's expected output: all 3 fixes were test-artifact bugs with 0 `implementation/` fixes and 0 deletions, so a byte-identical `PRD_FINALIZED.md` is a legitimate outcome here (per the skill, only Step 9 must never be identical).

## Step 8: Finalize PRD — 2026-09-06T06:02:00.000Z

## Result

`workspace/PRD_FINALIZED.md` created as a byte-identical copy of `PRD.md`. **Zero edits** — all three Step 7 items are localized test-artifact bugs, and PRD.md already uniquely determines the implementation's behavior at each site.

- PRD.md: 430 lines / 95,159 bytes. PRD_FINALIZED.md: 430 lines / 95,159 bytes. Delta: **0 lines, 0.00%** (md5 `6c1aeba14c059df6f11146de32d8b7b0` on both).
- Changes: none.

## Per-item verification (the mandatory pre-edit search, run for each candidate edit; all three concluded "no edit")

**Item 1 — `test_06` `fx.accept_referral` arity slip**
- (a) Subject: the acceptance-window boundary + sweep-consequence behavior the test exercises once it can issue a request at all.
- (b) Enumerated/read: `implementation/routes_reg.py:253-305` (sweep counters `expired_referral_count`, `demoted_registration_count`, `removed_registration_count`, `run_at`), the acceptance path in `routes_ref.py`, `test_suite/test_06_acceptance_and_ratio_boundaries.py:131-250`. PRD line 225 pins strict-past expiry ("A referral sitting exactly at its deadline is untouched"), line 229 names every sweep response counter the test reads, line 213 pins the post-demotion `position_number`.
- (c) No wording adjustment: the defect was a Python signature error (`accept_referral(api, referral_id, member_id)` called without `api`) that aborted before any HTTP request. No PRD sentence is implicated. **No edit.**

**Item 2 — `list_position_at_issue` = 2, not 1 (candidate-pool rank vs list ordinal)**
- (a) Subject: what `position_number` ranks over, and what `list_position_at_issue` snapshots.
- (b) Enumerated/read: `domain.position_number` (domain.py:102-111) -> `registered_registrations` (domain.py:54-56, filters **only** `list_id` + `status == REGISTERED`, no eligibility filter) -> `intra_list_key`/`strict_group_order_key` (domain.py:73-89); the separate, eligibility-filtering `domain.candidate_pool` (domain.py:165-196); `domain.candidate_snapshot` (domain.py:199-215, which emits *both* a pool `rank` and the row's own `position_number` — direct impl evidence the two are distinct); `domain.registered_count` (domain.py:59-60); `serializers.registration_view:80` and `referral_view:144`. Cross-checked every logically related PRD path, not just the Step 7 site: line 191 (pool filter, listed separately from any ordinal), line 187 (`registered_count` "computed as the number of registrations currently on it whose `status` is `REGISTERED`"), line 213 (`position_number` over "rows whose `status` is `REGISTERED`" — a status predicate, not an eligibility one), line 269 (issuance renumbers "every remaining `REGISTERED` registration ... from 1 through the group's `registered_count`"), line 311 (`NEXT_AVAILABLE_PRIORITY` renumbering to ordinal 1 — impl achieves this live via `priority_flag` leading `intra_list_key`), and line 179's "invisible to every ranked candidate **set**", whose defined referent is §3.2's ranked candidate *pool*, not a list ordinal.
- (c) No wording adjustment needed. The three PRD sentences (187, 213, 269) mutually reinforce that list numbering spans all `REGISTERED` rows regardless of `dispatch_eligible`, while 191 confines the eligibility filter to the pool. A fresh reader lands on 2. The old `assert 2 == 1` was the test conflating the two. **No edit.** (Note: any wording that had tried to "clarify" 213 toward eligibility-filtered numbering would have contradicted 187, 269 and 311 simultaneously — this is exactly the false-universal trap the no-new-mismatch rule guards.)

**Item 3 — `KeyError: 're_registration_eligible_at'` on a Registration payload**
- (a) Subject: which entity owns `re_registration_eligible_at`.
- (b) Enumerated/read: `serializers.member_view:31` (owns it) vs `serializers.registration_view:66-86` (does **not** carry it); every impl reader of the field — `domain.member_dispatch_eligible` (domain.py:20-24) and `domain.candidate_pool` (domain.py:181-182), both of which read it off `db.members`, never off a registration; every writer, via grep for the three-refusals cooling-off cascade. Exhaustive grep of PRD for the identifier returns exactly two hits: line 179 (assigns it to the Member, "null for a member in ordinary standing") and line 336 (the member GET row). No PRD sentence places it on a registration; §3.3's registration prose and line 346's registration GET row enumerate `position_number`, `credited_seniority_hours`, `demotion_count`, `priority_flag` and omit it.
- (c) No wording adjustment. Ownership is stated once, unambiguously, and never contradicted. **No edit.**

## Additional check (informational, no edit)

Step 7's unconfirmed `laid_off_dispatch`/`ERR_HOURS_EXCEED_ELAPSED` observation is not a PRD gap: PRD line 295 already gives the closed-form rule (`hours_worked` <= 12 x ceil((now - `start_at`)/24h)) and even states the exact 40-vs-24 worked example the fixture defaults would hit. It is an unexercised fixture combination, not an ambiguity, and it produced no fix — so out of the hard scope regardless.

---
Orchestrator verification of Step 8: `md5sum` confirms PRD.md and PRD_FINALIZED.md are byte-identical (both `6c1aeba14c059df6f11146de32d8b7b0`, 430 lines each). This is the legitimate outcome for this task — Step 7 applied 0 `implementation/` fixes and made 0 deletions, so there were no PRD-silence or PRD-mismatch sites for Step 8 to patch. Step 9, by contrast, must not come out identical: it runs the full PRD-vs-implementation scan and will be executed as sequential module-partitioned passes over one shared PRD_COMPLETED.md (pass 1 performs the cp; later passes must not), followed by a narrow reconciliation pass to close any cross-pass contradictions.

## Step 9: Complete PRD — 2026-09-06T06:51:32.693Z

Orchestrator decision, recorded here because there is no user to consult: Step 9 was run as **four sequential passes over one shared `PRD_COMPLETED.md`**, partitioned by implementation module, rather than as a single subagent. A single agent cannot hold 2,996 lines of implementation plus a 95 KB PRD and still do an exhaustive behavior-by-behavior scan; a monolithic Step 9 characteristically returns a PRD byte-identical to its source, which for Step 9 means the scan never really ran. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2-4 inherited the file and were explicitly forbidden from repeating it. Pass 4 is a narrow reconciliation pass, added because partitioned passes report cross-pass contradictions instead of fixing them.

Partition: pass 1 = core.py, envelope.py, guards.py, serializers.py, app.py. Pass 2 = domain.py, services.py, routes_admin.py, routes_reg.py. Pass 3 = routes_work.py, routes_ref.py, routes_griev.py. Pass 4 = reconciliation only.

### Growth across the four passes

| stage | lines | chars | delta |
|---|---|---|---|
| source (`PRD_FINALIZED.md`) | 430 | 95,159 | — |
| after pass 1 | 431 | 101,123 | +5,964 |
| after pass 2 | 431 | 114,736 | +13,613 |
| after pass 3 | 435 | 131,096 | +16,360 |
| after pass 4 (final) | 435 | 133,181 | +2,085 |
| **total** | **+5 lines** | **+38,022 chars (+40.0%)** | |

Final `PRD_COMPLETED.md` md5 `98b3dd8ebcb55645798c792745c22d38`.

### Counts

- Pass 1: 13 ambiguity-pins, 2 mismatch-revisions (15 edits).
- Pass 2: 30 ambiguity-pins, 7 mismatch-revisions (37 edits).
- Pass 3: 27 ambiguity-pins, 7 mismatch-revisions (34 edits).
- Pass 4: 8 reconciliation edits.
- **Total: 70 ambiguity-pins, 16 mismatch-revisions, 8 reconciliations = 94 edits.**

### Pass 1 (core/envelope/guards/serializers/app) — 15 edits

- §2.2 — revise — ambiguity — `api_request_id` pinned as `req_` + exactly 20 chars from `A-Z0-9` (24 total) — core.py:113-115
- §2.2 — revise — ambiguity — `api_request_timestamp` pinned as real wall-clock, explicitly not the logical hall clock, so it never matches `created_at`/`updated_at` — envelope.py:70-79
- §2.2 — revise — mismatch — "(4xx status codes)" -> "4xx and 5xx alike", since the catch-all handler emits the same envelope at 500 — app.py:44-47
- §2.2 — insert — ambiguity — `message` wording non-contractual; unroutable path -> 404, disallowed method -> 405, both `ERR_INVALID_REQUEST`, both decided by routing *before* the §2.1 header check, both keeping 404/405 rather than §5's 422; trailing-slash paths route to the documented path; unexpected fault -> 500 same envelope — app.py:22,38-47
- §2.3 — revise — ambiguity — empty-string `limit`/`offset` treated as absent; non-digit forms incl. `5.0` and leading `+` are 422; whitespace trimmed; `offset` >= row count is legal (200, empty `data`, true `total_count`, `has_more` false) — guards.py:189-210
- §2.3 — revise — mismatch — offset's "no upper bound beyond the size of the collection" -> "no upper bound of any kind" — guards.py:209
- §2.4 — revise — ambiguity — `id` pinned as canonical lowercase 36-char hyphenated random UUID — core.py:109-110
- §2.4 — revise — ambiguity — at creation `updated_at` equals `created_at` (not null); every refresh reads the logical clock, so a mutation under a stationary clock bumps `version` without changing `updated_at` — core.py:164-167
- §2.4 — revise — ambiguity — representations are fixed-shape: every §3-named field always present, valueless fields emitted as `null` not omitted, nothing beyond §3-named fields ever emitted — serializers.py:8-219
- §2.5 — revise — ambiguity — instant parsing pinned: must be a JSON string; accepts `Z`, a numeric offset (normalized to UTC), no designator (read as UTC), or date-only (midnight UTC); sub-millisecond precision truncated toward zero (`.6789Z` -> `.678Z`); unparseable -> `ERR_INVALID_REQUEST` — core.py:129-146
- §2.7 item 3 — revise — ambiguity — absent/blank body read as `{}`; unparseable JSON, non-object JSON and a body without a JSON content type each `ERR_INVALID_REQUEST`; explicit `null` == absent; undeclared fields ignored; booleans never accepted as integers; min-length-1 strings reject `""`; identifier arrays must be arrays of non-empty strings; unrecognized enum *filter* value is 422 rather than an empty result; boolean filters accept only `true/false/1/0` case-insensitively — guards.py:38-186
- §2.8 — revise — ambiguity — `expected_job_request_version` is a precondition only; not stored on the referral and not echoed — serializers.py:130-150
- §3.3 — revise — ambiguity — each reciprocity credit entry must be an object with non-empty string `sister_local_id` and integer `raw_hours` >= 0, else `ERR_INVALID_REQUEST` — guards.py:136-155
- §3.3 — revise — ambiguity — Registration echoes `claim_position_preservation` as supplied and `reciprocity_credits` in supplied order normalized to only the two keys (extra keys discarded); empty array not null — serializers.py:72-73
- §3.9 — revise — ambiguity — `note` capped at 2,000 chars, written into the `GRIEVANCE_DECIDED` `snapshot_json`, never a field of the `Grievance` resource — serializers.py:172-190, routes_griev.py:143,228

Pass 1 verified-no-change: all 48 `error_id` -> HTTP status pairs in §5 match `envelope.py` exactly (same set, same values, same order); all 30+ enum tuples in `core.py` match their §2/§3 prose lists; every day/hour/basis-point constant matches; `round_half_up_div` matches §2.9's "away from zero"; the two reduced-shape records in §2.4 match `endorsement_view`/`ledger_view` field-for-field; all 12 serializer field lists were already fully named in §3.

### Pass 2 (domain/services/routes_admin/routes_reg) — 37 edits

- §2.3 — insert — ambiguity — list-group tie-break named (`created_at` ASC) plus the global rule that all ties resolve finally by recording sequence, never by `id`; `created_at` ties are ordinary because it reads the logical clock — services.py:174 / routes_admin.py:133
- §2.5 — insert — ambiguity — clock setter answers 200 with a `data` object of exactly one key `current_utc`, creates nothing, accepts backwards moves — routes_admin.py:32-39
- §2.10 — revise — mismatch — `hours_delta` is non-zero on a layoff as well as on a make-whole credit — services.py:14-32
- §2.10 — revise+insert — mismatch+ambiguity — exact set of events with null `referral_id` (five kinds), plus the full per-event `snapshot_json` key sets for pass 2's events — services.py:14-32,94-98,135-152; routes_reg.py:154-163,218,237,291
- §2.10 — revise — mismatch — `retention_until` exception: `REGISTRATION_CREATED` measures its horizon from `registered_at`, not `recorded_at` — services.py:24 + routes_reg.py:159
- §3.1 — insert — ambiguity — no uniqueness on `local_number` or `kind`; a single HOME local is convention, not an invariant — routes_admin.py:45-62
- §3.1 — insert — ambiguity — member-delinquency cascade: `acceptance_deadline` ASC, REFERRAL_WITHDRAWN(`MEMBER_DELINQUENT`)+POSITION_RESTORED per referral, job-request version +1 each, fires on the value written not on a change, GOOD_STANDING reissues nothing, member version +1 — routes_admin.py:203-223
- §3.1 — insert — ambiguity — a missing endorsement id answers `ERR_MEMBER_NOT_FOUND`; a past `certified_until` is accepted at creation — routes_admin.py:229-249,267-275
- §3.2 — insert — ambiguity — `requires_local_hours`/`accepts_travelers` required, hours >= 0 with no upper bound; `group_code`/`priority_rank` not unique — routes_admin.py:90-108
- §3.2 — insert — ambiguity — `registered_count` and `position_number` are derived at read time, never stored, so all "increment/decrement/renumber" prose describes consequences, not writes — domain.py:59,102-111
- §3.2 — insert — ambiguity — cross-policy ordering axis: SENIORITY yields negated hours, FIRST_REGISTERED yields epoch seconds, so SENIORITY candidates precede FIRST_REGISTERED at equal rank/flag/demotion — domain.py:63-70
- §3.2 — insert — ambiguity — the pool filter reads nothing else: ignores `renewal_due_at` (lapsed rows still dispatchable), does not re-check group eligibility, and a SPECIAL_SKILL referral against a null `required_skill_code` admits nobody — domain.py:152-196
- §3.2 — revise — mismatch — "five components" corrected to "six components" for strict group order — domain.py:73-84
- §3.2 — insert — ambiguity — candidates tied on all six are ordered by recording sequence (identity still never a tie-break) — domain.py:83
- §3.2 — insert — ambiguity — the interfiled variant's four-component tie resolves by recording sequence; the variant reaches neither `priority_rank` nor `ordering_policy` — domain.py:92-99
- §3.2 — insert — ambiguity — dispatch-order payload is exactly seven keys, `variant` is never NOT_APPLICABLE there, `top_position_number` is the own-list ordinal (often not 1 under interfiling), and the 10-key candidate-row shape is retained in the REFERRAL_ISSUED snapshot — services.py:160-171, domain.py:199-215
- §3.3 — insert — ambiguity — reciprocity entries are not deduplicated — routes_reg.py:23-31
- §3.3 — insert — ambiguity — cooling-off is the only member-record bar on signing: a DELINQUENT member may sign, and a DISPATCHED_OUT holder may re-sign while still working — routes_reg.py:105-128
- §3.3 — insert — ambiguity — the most-recently-created LAID_OFF dispatch governs the window (including a recall, which inherits `referral_id`); claim=true with no predecessor gives ERR_REREGISTRATION_WINDOW_EXPIRED; claim=false is never evaluated — routes_reg.py:34-42,111-122
- §3.3 — insert — ambiguity — nothing beyond `registered_at`/`demotion_count` is inherited: `priority_flag` starts false, `credited_seniority_hours` is always recomputed — routes_reg.py:131-145
- §3.3 — revise — mismatch — `position_number` is a computed rank, not "`registered_count` plus one — the tail of the queue"; tail only holds under FIRST_REGISTERED, SENIORITY can land at 1, and preservation reproduces standing rather than a remembered ordinal — domain.py:102-111 vs routes_reg.py:131-132
- §3.3 — insert — ambiguity — REGISTRATION_CREATED's `recorded_at` is the clock while its retention horizon is `registered_at`+1825d; both signing entries carry null `referral_id` — routes_reg.py:154-163
- §3.4 — insert — ambiguity — no deadline on re-signing: permitted any time while REGISTERED, even past `renewal_due_at` — routes_reg.py:199-220
- §3.4 — insert — ambiguity — REGISTRATION_RENEWED's snapshot is `registration_id` alone — routes_reg.py:218-219
- §3.4 — insert — ambiguity — REGISTRATION_REMOVED snapshot keys; THREE_REFUSALS/RENEWAL_LAPSED supplied as a manual reason is ERR_INVALID_REQUEST — routes_reg.py:228,237-239
- §3.4 — insert — ambiguity — step one visits in `acceptance_deadline` ASC and writes every terminal status before step two charges, so each strike count includes every expiry of the same run — routes_reg.py:259-266
- §3.4 — insert — ambiguity — step three appends REGISTRATION_EXPIRED with null `referral_id` and `{registration_id, removal_reason}`; step four considers only RETAINED rows, purges once, and adds no `updated_at`/`version` — routes_reg.py:291-300
- §3.4 — revise — mismatch — the sweep re-derives only OPEN/PARTIALLY_FILLED requests (never FILLED/SUSPENDED/CLOSED/CANCELLED) and bumps the request's version once per expired referral — services.py:47-59, routes_reg.py:277-280
- §3.4 — insert — ambiguity — the six sweep keys are the whole payload at 200, five zeroes on an idle run; demoted+removed always sums to `expired_referral_count` — routes_reg.py:302-309
- §3.6 — revise+insert — ambiguity — supersession only for a strictly-earlier `effective_from` (equal or later stay ACTIVE, so several ACTIVE policies coexist), each superseded policy's version +1, a new policy never supersedes itself, missing policy id gives ERR_MEMBER_NOT_FOUND — routes_admin.py:297-303,306-313
- §3.6 — insert — ambiguity — the `max_apprentices_allowed` read never errors; it is 0 both with no accepted JW and with no governing policy — domain.py:295-309
- §3.7 — revise — mismatch — the removal threshold is "3 or more" strikes, not equality with 3 — services.py:140
- §3.7 — insert — ambiguity — the member's own version +1 in hop three — services.py:148
- §3.7 — insert — ambiguity — the no-cause REFERRAL_REFUSED snapshot is `good_cause` false plus the post-answer `strike_count` — services.py:135-137
- §3.7 — insert — ambiguity — REFERRAL_EXPIRED carries the same two snapshot keys — services.py:134-137
- §3.7 — insert — ambiguity — REFERRAL_WITHDRAWN `{reason, referral_kind}` / POSITION_RESTORED `{registration_id}`, both carrying the referral id — services.py:94-98
- §4 — revise — mismatch — the renew row's "within the resign interval" replaced with "accepted at any time while the registration is REGISTERED, even after `renewal_due_at` has passed" — routes_reg.py:199-220

Pass 2 confirmed it did not re-run the `cp` and verified three pass-1 edits still present by grep (§2.4 fixed-shape rule, §2.5 sub-millisecond truncation, §2.7 item 3's `apprentice_period` clause), with 27 headings and 101 table rows intact and zero stale duplicates of the phrases it replaced.

### Pass 3 (routes_work/routes_ref/routes_griev) — 34 edits

Mismatches:
- §3.6 ¶268 — revise — mismatch — deleted the false precondition "The member must have no dispatch whose `status` is `WORKING`"; impl has no such check and no error code for it, the condition being reachable only through the §3.2 candidate filter — routes_work.py:327-366
- §3.6 ¶268 — insert — mismatch — pinned precedences 11/17/18/19/30 as evaluated only when the dispatcher names a `member_id`; the selected-candidate path skips all five — routes_work.py:328,338,362
- §3.7 ¶290 — revise — mismatch — withdrawal does not release a named-call or special-skill allowance, because neither allowance is charged at issuance (both are validated once at intake) — services.py:81-98 vs routes_work.py:160-166
- §3.5 ¶248/¶252 — revise — mismatch — the contractor-delinquency and cancellation cascades bump each affected job request's `version` by exactly 1 in total, not once per withdrawn referral — routes_work.py:102-104,242-244; services.py:92-93
- §3.8 ¶298 — revise — mismatch — the elapsed-day divisor is `ceil` of elapsed seconds / 86400 (0 when elapsed <= 0), so hours cap at `12 x elapsed_days` and any positive report against a zero cap is `ERR_HOURS_EXCEED_ELAPSED` — routes_ref.py:277-284
- §3.9 ¶316 — revise — mismatch — the SCHEDULED_HOURS formula rounds per day and then multiplies by weekday count, rather than rounding once on the total — routes_griev.py:204-208
- §3.9 ¶312 — revise — mismatch — softened the absolute "renumbered so that registration holds `position_number` 1"; impl only sets `priority_flag = True` on the first `REGISTERED` registration in default order, so a peer already carrying the flag outranks it — routes_griev.py:185-191

Ambiguity-pins:
- §2.8 — insert — `ERR_INVALID_REQUEST` covers the missing-`slot_kind` query parameter and the "at least one worker" intake rule — routes_work.py:137-139,252-253
- §2.10 ¶166 — insert — completed the `snapshot_json` key-set catalogue for `REFERRAL_ISSUED`, good-cause `REFERRAL_REFUSED`, `REFERRAL_ACCEPTED`, `DISPATCH_LAID_OFF`, `DISPATCH_RECALLED`, `GRIEVANCE_DECIDED`, `MAKE_WHOLE_CREDITED` and the remedy-side `POSITION_RESTORED` — routes_work.py:405-411; routes_ref.py:159-161,195-197,301-305,365-368; routes_griev.py:192-228
- §2.10 ¶166 — insert — `hours_delta` is `hours_worked` on `DISPATCH_LAID_OFF`, `back_pay_hours` on `MAKE_WHOLE_CREDITED`, 0 everywhere else — routes_ref.py:305; routes_griev.py:221; services.py:15
- §2.10 — insert — ledger listing is ordered `recorded_at`, then `created_at`, then recording sequence, filterable by `member_id`/`referral_id`/`event_code`/`purge_state`; reads are HallAdmin/BusinessManager only — routes_griev.py:249-265
- §3.2 ¶198 — insert — the dispatch-order payload's exact seven keys and the `ERR_NO_ELIGIBLE_REGISTRANT` on an empty pool, which precedes nothing else because the request lookup comes first and no status gate exists — routes_work.py:248-264; services.py:160-171
- §3.5 ¶234 — insert — `signatory_status` defaults to `SIGNATORY` when omitted at contractor creation — routes_work.py:35-36
- §3.5 ¶236 — insert — the intake validation order: shape, >=1-worker rule, contractor existence, named-member FKs, ownership, signatory standing, then the two allowances — routes_work.py:126-166
- §3.5 ¶242 — insert — contractor list filters on `signatory_status` only; job-request list on `contractor_id`, `status`, `duration_type` — routes_work.py:66,209-219
- §3.5 ¶248 — insert — the delinquency branch fires on the written value being `DELINQUENT_TRUST_FUNDS` or `TERMINATED` regardless of the prior value, suspends only OPEN/PARTIALLY_FILLED, and records the pre-suspension status in `suspended_from_status` — routes_work.py:91-99
- §3.5 ¶250 — insert — reinstatement fires only on a transition into `SIGNATORY` from something else, restores `suspended_from_status` (falling back to OPEN when null), clears the memo, reissues nothing — routes_work.py:105-111
- §3.5 ¶252 — insert — cancellation accepts OPEN, PARTIALLY_FILLED and SUSPENDED, requires a 1-500-char `reason` carried verbatim into each withdrawal snapshot, and clears `suspended_from_status` — routes_work.py:229-244
- §3.6 ¶258 — insert — `override_reason` is optional, max 500 chars, may be the empty string at parse time, but a blank or whitespace-only value does not satisfy the out-of-order override — routes_work.py:294-295,393
- §3.6 ¶260 — insert — the apprentice consumption count is deliberately asymmetric: ISSUED+ACCEPTED at issuance, ACCEPTED-only at acceptance (the referral being answered is still ISSUED and would otherwise be charged twice) — routes_work.py:375-376 vs routes_ref.py:124
- §3.6 ¶262 — insert — a `NAMED_CALL` without `member_id` is `ERR_INVALID_REQUEST`, raised immediately after the request lookup and before the member FK — routes_work.py:302-304
- §3.6 ¶264 — insert — `ERR_JOB_REQUEST_SUSPENDED` precedes the openness test, and the open-slot shortfall reuses `ERR_JOB_REQUEST_NOT_OPEN` — routes_work.py:315-325
- §3.6 ¶266 — insert — `ERR_STALE_JOB_REQUEST_VERSION` sits between the outstanding-referral check and the member standing checks, so it is reported after precedence 11 but before 17/18/19 — routes_work.py:333
- §3.6 ¶268 — insert — the target registration is the member's most recently created live (REGISTERED/REFERRED) registration, else the most recently created of any status, so a REFERRED one yields `ERR_REGISTRATION_NOT_ACTIVE` rather than a 404 — routes_work.py:270-282
- §3.6 ¶270 — insert — `list_position_at_issue` is null for a named call and otherwise the position computed before the registration flips to REFERRED; issuance touches the registration and the request (+1 each) and appends one REFERRAL_ISSUED with `hours_delta` 0 — routes_work.py:425-439
- §3.7 ¶274 — insert — the acceptance ladder in order: 404, ownership (members only), job-request openness, ISSUED, deadline, overlap, then the apprentice ratio — routes_ref.py:101-129
- §3.7 ¶276 — insert — the acceptance deadline is exclusive-of-equality (`now() > acceptance_deadline` fails), so acceptance exactly at the deadline instant succeeds — routes_ref.py:112
- §3.7 ¶278 — insert — acceptance clears the registration's `priority_flag` as it moves to DISPATCHED_OUT — routes_ref.py:136-138
- §3.7 ¶278 — insert — the acceptance response payload is the new `Dispatch` at 201, not the answered `Referral`; the request's `version` moves exactly 1 — routes_ref.py:157-162
- §3.7 ¶280 — insert — refusal never consults job-request status, so a referral on a SUSPENDED, CANCELLED or FILLED request may still be refused; the parent request is touched either way — routes_ref.py:179-202
- §3.7 ¶290 — insert — withdrawal requires a 1-500-char `reason`, only an ISSUED referral qualifies, and it appends both REFERRAL_WITHDRAWN and POSITION_RESTORED while leaving `registered_at`, `credited_seniority_hours`, `demotion_count` and `priority_flag` untouched — routes_ref.py:214-219; services.py:81-98
- §3.8 ¶296 — insert — employment intervals are half-open `[start_at, ended_at)` with a WORKING dispatch open-ended, so adjacency is permitted; the overlap probe tests only the reporting instant — routes_ref.py:40-56
- §3.8 ¶300 — insert — layoff credits `hours_worked` to the member's `local_hours_in_trade` and touches the member; the FILLED -> CLOSED bubble-up is evaluated only here — routes_ref.py:297-307
- §3.8 ¶302 — insert — the recall window is closed at both ends (`ended_at <= clock <= recall_window_ends_at`); the new dispatch inherits the original's `referral_id` and `job_request_id`, consumes the first REGISTERED registration in default order, and neither the parent request nor the laid-off row is modified — routes_ref.py:329-368
- §3.9 ¶306 — insert — the filing window is `issued_at + 10 days` inclusive, and only the referral's existence is checked — not the grievant's connection to it — routes_griev.py:57-64
- §3.9 ¶308 — insert — `note` is optional, may be empty, max 2000 chars, stored on the GRIEVANCE_DECIDED snapshot as `null` when absent — routes_griev.py:143,228
- §3.9 ¶310 — insert — the adjudication ladder: 404, segregation of duties (7), state (14), purge guard (24, only for a sustained OUT_OF_ORDER_DISPATCH), then remedy applicability (40) — so a self-issued referral yields `ERR_SEGREGATION_OF_DUTIES` even on a FILED grievance — routes_griev.py:145-177
- §3.9 ¶310 — insert — the challenged dispatch is the earliest non-recall dispatch of the referral, falling back to the earliest of any — routes_griev.py:25-31
- §3.9 ¶314 — insert — the variant turns on the dispatch's current status: WORKING -> SCHEDULED_HOURS, anything else -> ACTUAL_HOURS on `hours_worked` (0 if null) — routes_griev.py:202-214
- §3.9 ¶316 — insert — the weekday count spans the half-open date interval `[date(start_at), date(decided_at))`, Mon-Fri — routes_griev.py:34-45
- §3.9 ¶316 — insert — ACTUAL_HOURS rounds exactly once on `hours x rate x factor_bp / 10000`; `back_pay_hours` is `weekdays x 8` or `hours_worked` respectively — routes_griev.py:207-214
- §3.9 ¶320 — insert — MAKE_WHOLE_CREDITED is appended before GRIEVANCE_DECIDED, and the remedy-side POSITION_RESTORED is written once whether or not a registration was found — routes_griev.py:192-228
- §4 (4 rows) — insert — filter key sets for the referrals, dispatches, grievances and ledger-entries collections — routes_ref.py:72-88,236-252; routes_griev.py:102-115,250-253

Pass 3 confirmed no `cp` and verified two pass-1 and two pass-2 edits still present by grep.

### Pass 4 (reconciliation) — 8 edits

1. **§2.7 items 11/17/18/19 vs §3.6 — real contradiction, fixed.** `routes_work.py`: check 11 is `if member is not None and domain.member_has_outstanding_referral(...)` (line 328); 17/18/19 sit inside `if member is not None:` (338-352); 30 inside `if member is not None:` (362). All five are named-member-only, so §3.6 was right and §2.7 was wrong. Items 11/17/18/19 now state the named-only restriction; item 30 already did. Also tightened §3.6 ¶264's SPECIAL_SKILL sentence, since on the unnamed path a missing endorsement yields `ERR_NO_ELIGIBLE_REGISTRANT`, not `ERR_SKILL_ENDORSEMENT_MISSING`.
2. **Apprentice-count asymmetry — confirmed, both call sites now self-labelling.** §3.6 step three reads "at issuance ... `ISSUED` or `ACCEPTED` — at acceptance that same count reaches only the `ACCEPTED` ones"; §3.7 ¶280 states the accepted-only count and why.
3. **Version-bump reconciliation — confirmed with an important refinement.** The §3.1 member-delinquency cascade is *not* an exception: `routes_admin.py:222` calls `withdraw_referral` with the default `True`, so it bumps per referral, exactly as §3.1 already claimed. ¶294 now names only §3.5's two cascades as exceptions and explicitly groups §3.1 with the per-withdrawal rule.
4. **`snapshot_json` catalogue swept — no edit needed.** All 17 `append_ledger` call sites across five modules were enumerated and matched against §2.10 ¶166: all 17 correct, including pass 3's GRIEVANCE_DECIDED fix. The five-kinds-null-`referral_id` claim checks out. No event's key set is stated twice with conflicting content; the eight restatements in §3.3/§3.4/§3.6/§3.7 all either defer to §2.10 or repeat it exactly.
5. **§3.9 priority-flag claim — overstated, softened.** `priority_flag` is component 2 of `strict_group_order_key`, after `priority_rank`. The sentence now reads "ahead of every unflagged registration it is compared against", noting the remedy is a promotion within the ordering, not a guarantee of rank one — a same-list flagged peer is still separated by `demotion_count`, and on a long call `priority_rank` is compared first.

Additional contradiction the general sweep found and closed: **§3.5 ¶248 vs §3.1 ¶182 described the same cascade's withdrawal ordering differently and one was wrong.** `routes_admin.py:218-220` sorts the member's outstanding referrals globally by `acceptance_deadline` (§3.1 right), but `routes_work.py:101-104` loops suspended requests and calls `withdraw_issued_referrals_of_job_request` per request, so the sort is within each request and the global order is request-by-request in `created_at` order — observable through ledger `_seq` when one contractor has two suspended requests with interleaved deadlines. §3.5 ¶248 was corrected and explicitly contrasted with §3.1. §3.5 ¶252 (cancellation) needed nothing, being a single request.

Pass 4 verified-clean, no edit: every boundary convention across §2.5/§3.3/§3.4/§3.7/§3.8/§3.9 checked against its comparison operator (acceptance `now() > deadline`; registration occupation `deadline >= clock`; recall closed both ends; employment half-open; grievance filing `clock > issued_at + 10d`; strike window closed left edge; sweep steps one/three/four strict `<`; endorsement `certified_until > clock`; position preservation `now() > horizon` with no lower bound; cooling-off `now() < eligible_at`; ratio policy `effective_from <= clock`; weekday count half-open; layoff elapsed-days `ceil` with zero-or-less -> 0). Tie-break rules agree everywhere, `_seq` being the final component of every sort key. A programmatic check over 591 sentences >= 70 chars found zero repeats and no orphaned fragments.

Pass 4 resolved conservatively (flagged, not edited): §3.6 ¶272's "a LIST_ORDER or SPECIAL_SKILL referral to [a working named member] is refused as `ERR_OUT_OF_ORDER_DISPATCH` ... and with one, it is issued". Impl evaluates precedence 37 before 38, so if the working member were the only candidate the override would carry it past 37 and then hit `ERR_NO_ELIGIBLE_REGISTRANT` at 38. The sentence is true whenever any other candidate exists, and §2.7 item 38 plus ¶264 both state the empty-pool test.

### Structural verification (pass 4, re-confirmed by the orchestrator)

27 headings, byte-identical to `PRD_FINALIZED.md`'s heading set. §4 endpoint table 49 data rows; §5 error table 48 data rows. File ends at the final error-table row `| ERR_REMEDY_NOT_APPLICABLE | 409 |` — a real section boundary, no truncation.

---
Orchestrator final verification of the whole pipeline:
- `workspace/PRD_COMPLETED.md` exists at 435 lines / 133,181 chars, md5 `98b3dd8ebcb55645798c792745c22d38`, and `cmp` confirms it is NOT identical to `PRD_FINALIZED.md` — the Step 9 scan genuinely ran (a byte-identical Step 9 output would have meant it did not).
- The PRD chain is coherent: PRD.md == PRD_FINALIZED.md (both md5 `6c1aeba1...`, legitimately unchanged because Step 7 made 0 implementation fixes), and PRD_COMPLETED.md is +38,022 chars over both.
- All 8 `results.$i.json` re-read a second time after Step 9: still `233/233` each. Step 9 touched no implementation or test file, so the green sweep remains the valid evidence for the shipped implementation.
- Exactly one `worklog.md` exists in the task tree (no cwd-drift strays under `workspace/`).
- Cleanup: transient `workspace/SWEEP_DONE` and the spliced `workspace/sweep.log` removed; `.scratch/` and all `__pycache__/` directories removed. `workspace/sweep.sh` is deliberately retained as the reproducible sweep harness.
- No task directory other than task_2981 was created at any point, and the pre-assigned index was used verbatim throughout.

Pipeline complete: Steps 1-9 all finished, Step 9 has written workspace/PRD_COMPLETED.md.
