# Worklog — task_2782_data_broker_registration_deletion_request_handling

## Step 1: Create task directory — 2026-09-04T20:36:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2782_data_broker_registration_deletion_request_handling` and its `workspace/` subdirectory. Index 2782 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-04T22:09:00.000Z

Scaffold generation for task 2782 is complete. All three files are written, parse as valid YAML, and pass the linter clean.

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3095 | 164589 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2028 | 134022 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3066 | 199667 |

**§1.0–§1.7 counts** (`SCAFFOLD.yaml`, top-level keys `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither design key present):
- entities **12** (DataBroker, Registration, DisclosureItem, Consumer, DeletionRequest, VerificationAttempt, DownstreamRecipient, PropagationTask, SuppressionEntry, OptOutSignal, RegulatorInquiry, AuditEvent)
- endpoints **52**, state_machines **9**, concurrency_rules **3**, calculations **9**, validations **45**, errors **45**, roles **7**

**§1.8 rule ids (18 instances, 2 each):** `dual_variant_calc` 2, `combinatorial_formula` 2, `non_linear_state_machine` 2, `transitive_cascade` 2, `priority_pair_validation_conflict` 2, `boundary_precision_check` 2, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 2.

**§1.9 sections (70 instances total = 55 full recipes + 15 `excluded_because` stubs):** entities 11, state_machines 12, calculations 8, validations 16, endpoints 3, errors 7, rbac 6, cross_cutting_complexity_layers 6, consistency_model 1.

**Lint verdict block, verbatim:**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2782_data_broker_registration_deletion_request_handling/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2782_data_broker_registration_deletion_request_handling/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2782_data_broker_registration_deletion_request_handling/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  709

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Additional self-checks run beyond the linter:** all 88 instance names unique across the union of both design files; all 15 stubs carry no `test_recipe` and every cited `difficulty_instance` resolves by name in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`; all 45 §1.6 error codes are exercised somewhere across §1.8+§1.9; zero unbound `${var}` placeholders in either design file; none of the forbidden concurrency vocabulary ("simultaneously", "concurrently", "in parallel", "first-writer-wins", "race winner/loser") appears anywhere. The hard constraint held — no sibling task directory was listed, read, or grepped.

**Two things for the caller to action:**
1. **Difficulty-directive leak (known issue):** the scenario's first line, "Generate task harder than expert level!", was included verbatim per instruction and therefore sits inside `SCAFFOLD.yaml`'s `scenario:` key, from which it will reach `PRD.md`. Strip that single line after Step 2.
2. Three inconsistencies inside `SCAFFOLD.yaml` were found and fixed during this pass: `honor_deadline_at` in `POST /opt-out-signals` said 15 days against `SIGNAL_HONOR_DEADLINE_DAYS = 45`; sweep step 5 claimed a phantom 30-day escalation grace and an `open_breach_count` bump absent from §1.2; and the `PropagationTask` DISPATCHED→ABANDONED precondition used `due_at < clock` instead of the `abandon_at = due_at + 30d` horizon that §1.5 and `TASK_ABANDON_GRACE_DAYS` imply.

**Orchestrator post-step action (item 1 above):** stripped the line `Generate task harder than expert level!` and its trailing blank line from `SCAFFOLD.yaml`'s `scenario:` block scalar. Verified `grep -rn "harder than expert"` now returns 0 hits across the task directory, and all three YAML files still parse via `yaml.safe_load`. The difficulty directive therefore cannot reach PRD.md via the scaffold.

## Step 3: Copy shared files — 2026-09-04T22:09:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T22:28:00.000Z

PRD generation is complete and verified.

## Output
`workspace/PRD.md` — **483 lines**, built incrementally (1 Write + 8 `cat >>` heredoc appends + 3 targeted in-place patches). Ends at a real section boundary: the completed 45-row §5 error table, no audit footer, no truncation, no heredoc marker leaks.

## Section outline
- `# Data Broker Compliance Office API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Authentication, Roles, and Resource Ownership / 2.2 API Response Structure (verified byte-identical to `section-2.2-response-structure.md`) / 2.3 Pagination and List Ordering / 2.4 Resource Identity, Versioning, and the Logical Clock / 2.5 Stale-View Protection on Broker and Consumer Writes / 2.6 The Order in Which a Request Is Rejected / 2.7 Money, Counters, Scores, and Rounding Discipline / 2.8 Cascade Discipline / 2.9 Left-to-Right Path Resolution and Single-Broker Integrity / 2.10 The Append-Only Audit Trail and Retention
- `## 3. Business Logic & Workflows` — 3.1 Broker onboarding, fee funding, registry standing / 3.2 Registry filings: drafts, disclosures, submission, examination / 3.3 Consumer records, collection events, consent dimension / 3.4 Deletion request intake and identity verification / 3.5 Execution and the propagation fork / 3.6 Propagation follow-through, recipient reliability, completion join / 3.7 Suppression and recognised opt-out signals / 3.8 Regulator inquiries and the evidence trail / 3.9 The deferred-action compliance sweep
- `## 4. Endpoint Definitions` (4-column table)
- `## 5. Error Code Catalogue` (2-column table)

## Coverage counts
| Category | Scaffold | Documented |
|---|---|---|
| Entities | 12 | 12 (all 132 field names) |
| Endpoints | 52 | 52 — method/path/role sets diffed programmatically against SCAFFOLD, zero mismatches, order preserved |
| State machines | 9 (50 transitions) | 9, all transitions incl. self-loops, retry/revision/escalation cycles, and both join branches |
| Calculations | 9 | 9, every constant and pinned step (incl. dual-variant assurance, tier-keyed adequacy, provisional-vs-final fee proration) |
| Validations | 45 | 45, as a priority-ordered numbered list in §2.6 with error id, status, and full `applies_to` scope |
| Error codes | 45 | 45 in §5, and all 45 also appear in prose |
| Roles | 7 | 7, with entity-backed vs opaque identity semantics |
| OCC rules | 3 | 3 (`expected_broker_version`, `expected_consumer_version` x2) |

## Hard Contracts
- **Contract 1 (Field-Name Coverage): PASS.** 149 required identifiers (132 entity fields + endpoint request/query/path identifiers + sweep response fields + common fields) checked against backticked tokens in PRD.md; 0 missing. One gap found and fixed mid-check (`registration_id` on DisclosureItem, now documented in §3.2).
- **Contract 2 (Rule Coverage): PASS.** All transitions, calculations, validations, endpoint side effects, `applies_to` scopes, concurrency rules, cross-entity cascades, and sibling-branch symmetry (COMPLETED vs PARTIALLY_COMPLETED, FRAUD_WEIGHTED vs PLATFORM_ASSERTED, ALL_SOURCES vs SINGLE_SOURCE) are stated in prose. Added the waive-side segregation-of-duties rule to §3.6 during verification.
- **Contract 3 (§3 Path Purity): PASS.** Programmatic scan of §3 found 0 backticked tokens starting with `/`, 0 bare HTTP methods, 0 method+path combinations, and 0 raw unbackticked path strings; §3 uses state-transition, role+verb, and capability framing throughout. All explicit paths live in §2.6, §4, and §5 only.

## Scaffold conflicts resolved by judgement (worth a reviewer's eye)
1. **Registration `SUBMITTED -> REJECTED` fee handling** — state machine cascade link 1 plus the `charged_fee_cents` field description say the provisional fee is refunded to `fee_credit_cents`; the endpoint blurb says it "stays consumed". Documented the **refund** (2 witnesses vs 1).
2. **`lift_justification` length** — field constraint says 10..400, but validation priority 53, the transition precondition, and the error condition all say >=20. Documented **20..400** for lift; `waiver_justification` remains 10..400.
3. **Manual suppression-entry creation and sibling supersession** — the DeletionRequest `-> SUPERSEDED` trigger mentions "SuppressionEntry activation", but the create endpoint enumerates side effects without any supersession or counter movement. Documented that direct creation supersedes nothing and that the cascade belongs to the join-created entry, with that stated explicitly in §3.7.
4. **Task dispatch source states** — endpoint blurb says `PENDING|DEFERRED`, state machine says `PENDING`/`FAILED` with `DEFERRED -> PENDING` as the only exit from deferral. Documented the state machine's version, with the reactivation path spelled out.
5. **Recipient list ordering** — endpoint blurb says "reliability rank order"; documented `reliability_score` desc / `created_at` asc as the *planner's* ranking key and left list ordering on the global §2.3 rule.

Per the constraint, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced, and no sibling task directory was read.

**Verbatim last 5 lines:**
```
| `ERR_SUPPRESSION_WINDOW_CONFLICT` | 409 |
| `ERR_COVERAGE_PERIOD_INVALID` | 422 |
| `ERR_RESPONSE_WINDOW_CLOSED` | 409 |
| `ERR_FILING_FEE_UNPAID` | 402 |
| `ERR_FEE_DEPOSIT_INVALID` | 422 |
```

**Orchestrator truncation check (per the known doc-generator failure mode):** independently ran `wc -l` (483), `tail -15`, and `grep -n "^#\+ "` on PRD.md. The file ends on a complete error-table row, not mid-sentence; all five top-level sections plus the ten §2 and nine §3 subsections are present in order. No regeneration was needed. Also confirmed `grep -in "harder than expert|expert level|scaffold"` returns zero hits in PRD.md, so the Step 2 difficulty directive did not reach the PRD.

## Step 5: Generate unit tests — 2026-09-04T23:07:00.000Z

Test generation is complete and audited.

## Files written (task root — nothing under `workspace/`)

**`test_helpers/`** (Stage 1, 2,382 lines): `__init__.py` 43, `api_client.py` 257 (52 endpoint methods), `api_errors.py` 114 (45 error ids + HTTP status map registered), `assertions.py` 405, `constants.py` 118, `factories.py` 259, `fixtures.py` 605 (composite setups through `setup_completed_deletion_request` / `setup_inquiry_over_completed_request`), `test_users.py` 78, `types.py` 503.

**`test_suite/`** (Stage 2, 5,926 lines): `conftest.py` 57, `test_01_records_and_intake_basics.py` 537, `test_02_lifecycle_transitions.py` 511, `test_03_score_calculations.py` 444, `test_04_intake_and_disclosure_rules.py` 394, `test_05_signal_and_window_rules.py` 357, `test_06_ledger_audit_trail_and_sweep.py` 425, `test_07_authorization_and_segregation.py` 410, `test_08_optimistic_concurrency_and_deferrals.py` 327, `test_20_filing_fee_assessment.py` 342, `test_21_registration_filing_lifecycle.py` 516, `test_22_identity_verification_and_execution.py` 368, `test_23_propagation_and_completion.py` 324, `test_24_completion_cascades_and_suppression.py` 479, `test_25_regulator_inquiry_adequacy.py` 435.

## Tests emitted

**109 test functions / 120 collected cases** (11 parametrized expansions). 43 tests translate queue A, 66 translate queue B.

Queue A (§1.8) — all 18 instances covered, every one with >=2 tests: `dual_variant_calc` 6, `transitive_cascade` 6, `combinatorial_formula` 5, `non_linear_state_machine` 5, `cross_entity_state_dependency` 5, `boundary_precision_check` 4, `priority_pair_validation_conflict` 4, `resource_temporal_overlap` 4, `compensating_invariant` 4.

Queue B (§1.9) — all 55 non-stub instances covered: `entities` 11, `state_machines` 9, `calculations` 5, `validations` 17, `endpoints` 7, `rbac` 9, `cross_cutting_complexity_layers` 5, `consistency_model` 3. The 15 `excluded_because:` stubs (7 `errors`, 3 `state_machines`, 3 `calculations`, 2 `cross_cutting`) were not translated; **all 15 `difficulty_instance` cross-references resolve** against `SCAFFOLD_DIFFICULTY_DESIGN.yaml`.

## Instances SKIPPED: none

Every one of the 73 non-stub instances passed the PRD-first filter and was translated. What the filter did remove is **individual sub-assertions** the PRD does not uniquely derive (instance kept, assertion dropped) — 13 in total:
- `audit_sequence_high_water == 0` on broker create (0 vs 1 not determined); `Consumer.created_at` pinned to the clock; `retention_expires_at` literal (asserted relatively as `created_at + 2555d` instead); "no broker row created" (no broker-list endpoint, unobservable).
- `provisional_filing_fee_cents == 60500` after a *refused* submit (PRD says the field is only set on success, so it must still be 0).
- `CONSUMER_COLLECTION_RECORDED` count on a blocked recollection (PRD appends `RECOLLECTION_BLOCKED` there); one `DataBroker.version == 2` on the suppression-side inverted-window test.
- HTTP-200 pin on fee deposit and `response_type == "success"` (PRD pins `response_type` to `object`/`array`).
- `total_deletion_weight == 60` (field absent from the PRD, grep 0); three OCC version literals (`broker.version == 2`, `consumer.version == 2`, `consumer.version == 3`) that contradict or are not fixed by the PRD's "every mutation increments version" prose.

Two design setups were rebuilt to route through an ACCEPTED filing, because as written they would have died on `ERR_NO_ACCEPTED_REGISTRATION` before reaching the asserted rule; all their assertions were preserved.

## Verification

`python3 -m py_compile` passes on all 24 generated files; `pytest --collect-only` collects 120 tests with no import or collection errors. Central audit: every test docstring carries **exactly one** `Design:` line as its last line (0 untagged, 0 dual-tagged, 0 dangling — all 109 tags resolve to a real `name:` in the source yaml, and all 73 instances are hit). **452 docstring PRD quotations** were re-checked against `workspace/PRD.md` by whitespace-normalized literal containment — 0 missing. No `skip`/`skipif`/`xfail`/TODO/placeholder anywhere, no raw ISO-string timestamp comparisons (all via `assert_instant_equals`), no mention of "scaffold" or design-index section numbers in emitted code, no duplicate test-function names. `worklog.md` untouched; `workspace/` contains no test directories or stray files.

## Step 6: Generate implementation — 2026-09-04T23:02:00.000Z

Implementation complete and smoke-verified.

## Files written (`workspace/implementation/`, 3429 lines total)

| file | lines | role |
|---|---|---|
| `core.py` | 395 | logical clock (fixed `2026-08-01T00:00:00Z` boot default), in-memory `Store` of plain dicts, `Decimal`/ROUND_HALF_UP helpers, `ApiError` + the 45-code `ERROR_STATUS` map, deferred `touch`/`flush` version bump, §2.2 envelope, `ENTITY_FIELDS` for all 12 entities |
| `guards.py` | 330 | 7 roles, headers, every closed vocabulary (39 event types, 11 subject kinds), rules 1-4, typed payload getters, pagination/filters |
| `scoring.py` | 225 | the 9 calculations' formulas and constants |
| `standing.py` | 110 | 4-clause standing derivation, fee refund/settlement, the 4-link delinquency cascade |
| `propagation.py` | 209 | fork (4 targets, weights 40/20/20/20), ratio, reliability re-score + auto-suspend, abandon, the completion join |
| `lookups.py` | 170 | 10 existence resolvers, coverage/overlap predicates, buffered + blocking suppression, durable-state-on-4xx block recorder |
| `audit.py` | 49 | append-only trail, monotonic `sequence_no`, 2555-day retention |
| `routes_registry.py` | 431 | brokers, fee deposits, audit-event list, registrations, disclosures, submit/accept/reject/withdraw |
| `routes_requests.py` | 325 | intake, verification attempts, decide, execute, deny, withdraw |
| `routes_propagation.py` | 296 | recipients + status transitions, tasks, dispatch/ack/fail/waive |
| `routes_suppression.py` | 292 | suppression entries + lift, opt-out signals (+ shared `honor_signal`) |
| `routes_inquiries.py` | 207 | open/respond/escalate/close with the 3 pinned adequacy steps |
| `routes_consumers.py` | 184 | consumers, consent dimension, collection events |
| `routes_ops.py` | 120 | `/_clock/set_current_utc` and the 6-step sweep |
| `app.py` | 75 | blueprint registration, ApiError/404/405 handlers, `0.0.0.0:$PORT` |
| `start.sh` | 10 | reads `$PORT`, binds 0.0.0.0, `exec`s in foreground; pip install guarded by an import probe so per-test reboots don't re-run it |
| `requirements.txt` | 1 | `flask>=2.0` |

Storage is in-memory dicts only; nothing is seeded, no file/db/cache is written (verified: only `.py`/`.txt`/`start.sh` remain in the dir).

## Coverage (machine-verified, not eyeballed)
- **Endpoints: 52/52.** Normalised method+path sets from the PRD table and from Flask's `url_map` diff **IDENTICAL**.
- **Entities: 12/12.** Every field declared in `SCAFFOLD.yaml` is present in `ENTITY_FIELDS`; the only additions are the standard `id`/`created_at`/`updated_at`/`version`.
- **Error codes: 45/45**, each with the exact HTTP status from §5 (0 mismatches), and each raised at least once in code (0 unraised).
- **Event types: 39/39** appended somewhere; 11 subject kinds; **7 roles**.
- **State machines: 9/9** (Registration, DeletionRequest, Consumer x2 parallel dimensions, PropagationTask, DownstreamRecipient, SuppressionEntry, OptOutSignal, RegulatorInquiry).
- **Calculations: 9/9**, constants cross-checked against the scaffold (e.g. `temporal_default_derivation`: 730/30/2555/45/30 all match).
- **Validations: 45**, implemented in the §2.6 priority order (including the two inversions the PRD calls out: overlap-before-period-invalid, and suppression-before-registration).

## Smoke test (`PORT=18782`, log `/tmp/impl_2782_smoke.log`)
Two passes: a full happy path (broker -> deposit -> registration -> 4 disclosures -> submit -> accept -> consumer -> deletion request -> GOVT_ID attempt 95.50/PASS -> decide VERIFIED -> execute -> 4 forked tasks -> dispatch/ack x4 -> join `COMPLETED` ratio 1.0 -> consumer `PURGED` -> ALL_SOURCES suppression minted -> opt-out honored in-request -> inquiry respond/close -> clock jump -> sweep), plus a second pass that exercised **every remaining handler**: reject->re-disclose->resubmit->accept, consent, collections, deny, withdraw, list+get on all collections, recipient SUSPEND/RESTORE/TERMINATE, task fail->waive, suppression conflict/short-justification/lift/create, deferred WRITTEN_REQUEST signal honored by sweep step 4, escalate, close.

Result: **57x200, 18x201, and only the intended 4xx** (409 ERR_RECIPIENT_INVALID_STATE, 409 ERR_SUPPRESSION_WINDOW_CONFLICT, 412 ERR_STALE_CONSUMER_VERSION, 422 ERR_LIFT_JUSTIFICATION_REQUIRED). **0 tracebacks, 0 5xx.** Invariants held at the end of both passes: `fee_deposited = fee_paid + fee_credit` OK and `request_intake_total = open + completed + terminated` OK. Adequacy arithmetic matched the PRD's own worked examples (3 cites + bonus -> 60.00/8.00/52.00 DEFICIENT; 5 cites + bonus -> 90.00/0.00/90.00 ADEQUATE). Server killed by PID resolved from port 18782 only — no broad `pkill`.

Exact success envelope (`POST /deletion-requests`, 201):
```json
{"meta":{"api_request_id":"req_BPLAJTW96KRYYHL0PXDK","api_request_timestamp":"2026-08-01T00:00:00.000Z"},
 "response_type":"object",
 "data":{"id":"93d720fb-...","broker_id":"be5ef37b-...","consumer_id":"21099869-...","intake_channel":"DIRECT_PORTAL","requested_scope":"DELETE_ALL","status":"RECEIVED","identity_assurance_score":0.0,"verification_attempt_count":0,"failed_attempt_count":0,"agent_loa_reference":null,"intake_user_id":"intake-1","verification_decided_by_user_id":null,"executed_by_user_id":null,"propagation_required_count":0,"downstream_task_count":0,"acked_task_count":0,"waived_task_count":0,"abandoned_task_count":0,"outstanding_task_count":0,"completion_ratio":0.0,"compliance_breach":false,"executed_at":null,"denial_reason_code":null,"created_at":"2026-08-01T00:00:00.000Z","updated_at":"2026-08-01T00:00:00.000Z","version":1}}
```
Exact error envelope (`POST /consumers/{id}/collections` against a suppressed consumer, 409):
```json
{"meta":{"api_request_id":"req_S4UBOVHGIVG21IQZNQ2W","api_request_timestamp":"2026-08-01T00:00:00.000Z"},
 "response_type":"error",
 "data":{"error_id":"ERR_SUPPRESSION_ACTIVE","message":"an active suppression entry blocks this collection"}}
```

## Bug found and fixed during the smoke run
`ok()` serialised the record **before** the deferred `version`/`updated_at` flush, so a mutating response returned the pre-bump version (deposit answered `version: 1` while the stored broker was already at 2). `flush()` now runs at the top of `ok`/`ok_record`/`ok_list`, before any `view()`. This would have broken essentially every "increments the version by one" assertion.

## PRD ambiguities resolved by judgement
1. **Deferred once-per-record version bump.** `touch()` marks a record dirty and `flush()` bumps `version`/`updated_at` exactly once per record per request, so the PRD's many "increments the parent's version by one" statements hold even when a cascade writes several fields of the same record.
2. **Audit appends do not bump the broker version.** `audit_sequence_high_water` moves without `touch(broker)`; otherwise every audit event would silently invalidate those "+1" guarantees.
3. **List endpoints are not auto-scoped to the caller.** §2.6 rule 4 is about endpoints resolving to a single owned resource, and the endpoint table declares no ownership for lists, so lists return the whole estate filtered only by query parameters.
4. **Ownership vs. existence ordering.** Where the addressed id is directly comparable (`/brokers/{id}`, `/consumers/{id}` for a Consumer, payload FKs) rule 4 runs before the 404; where ownership requires loading the record (e.g. `/regulator-inquiries/{id}/respond`), existence necessarily comes first, per §2.9 left-to-right resolution.
5. **Registration rejection refunds the fee.** The scaffold's reject `side_effects` said the provisional fee "stays consumed"; PRD §3.2 line 242 and the scaffold's own state machine both say link one refunds it. PRD wins -> refund.
6. **Dispatch accepts `PENDING|FAILED`, not `PENDING|DEFERRED`.** The scaffold's dispatch note said `DEFERRED`; §2.6 rule 22 and §3.6 explicitly say a DEFERRED task is *not* dispatchable. PRD wins.
7. **Sweep step 1 refunds.** Step 1 in §3.9 only says `charged_fee_cents` "is zeroed", but §3.2 line 244 and the §2.7 conservation law (which names an "expiry refund") require the money to move back to credit and the withdrawal cascade links 3-4 to run. Implemented as a refund + `derive_standing(cascade=True)`.
8. **`ERR_LIFT_JUSTIFICATION_REQUIRED` swallows the missing/ill-typed case** rather than deferring to rule 15's `ERR_INVALID_REQUEST`, on the strength of the code's own name and §3.7's wording — so the state check (rule 23) still wins over it.
9. **Opt-out signal 404** reuses `ERR_SUPPRESSION_ENTRY_NOT_FOUND`: the 45-code catalogue contains no opt-out-signal-not-found code, and signals live in the same §3.7 workflow.
10. **A single inquiry's breach contributions are tracked out-of-band** (`Store.inquiry_contrib`) so that closing releases exactly "one for each escalation it recorded and one for each DEFICIENT verdict it produced" without adding an undeclared entity field.
11. **`api_request_timestamp` uses the logical clock**, not wall time, so responses stay deterministic.
12. **`ordered()` sorts by `(created_at, _seq)`** because the logical clock repeats within a test and `created_at` alone is not a total order.
13. **Scores serialise as JSON numbers** (`Decimal` -> number), rounded half-up to the declared 2 or 4 places; JSON cannot carry trailing zeros, so `95.50` appears as `95.5`.

**Orchestrator layout check:** verified `test_helpers/` (9 .py) and `test_suite/` (15 .py) are at the task root and that `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, and `implementation/` — no stray test directories or conftest under workspace/ (the known Step 5 misplacement did not occur).

## Step 7: Run tests and iterate — 2026-09-04T23:14:00.000Z

Green on the first iteration — no fixes were required.

## Summary

**Iterations run:** 1

**Sweep result:** all 8 concurrent rounds `120/120 passed`, `failed=0`, `errors=0`, `skipped=0`. Each round genuinely executed (215.1-215.3 s pytest duration, 8 distinct `results.$i.json` written at 23:14, all with per-test `status: "passed"`). No flakiness signal: the union of failing tests across the 8 rounds is empty.

**Tests deleted:** none. No test failed in any round, so STEP 1 (PRD coverage / unique-derivability) was never triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Verification checks performed beyond the sweep**
- Collection count reconciles: 109 `def test_` functions + 4 `@pytest.mark.parametrize` expansions = 120 collected, matching `total` in every round. No tests were silently deselected.
- `grep` for `pytest.mark.skip` / `xfail` / `pytest.skip` across `test_suite/` and `test_helpers/` -> none, and `skipped: 0` in all 8 rounds, so nothing is passing by suppression.
- `grep` for `sqlite` / `open(` / `json.dump` / `/tmp` / `pickle` / `shelve` across `workspace/implementation/*.py` -> none. Storage is in-memory dicts in `Store` (`workspace/implementation/core.py`), constructed empty with no seeding at import time.
- No stray `test_helpers/` or `test_suite/` copies under `workspace/`.
- `worklog.md` untouched, per the orchestrator constraint.

**Artifacts left in place**
- `workspace/implementation/results.1.json` ... `results.8.json` — the 8-round evidence.
- `workspace/sweep.log` (140 K) — 8 interleaved writers, deliberately not used for diagnosis.

**One note for the orchestrator, not a defect acted on.** Two spots read as PRD-underdetermined and currently happen to go unexercised by the suite, so they are latent rather than failing:
- `adequacy()` in `workspace/implementation/scoring.py` computes `coverage_bonus_applied` over only the first five credited citations, whereas PRD §3.8 says the bonus is true when the three mandatory types appear "among the cited events' `event_type` values" — arguably the whole array. This only diverges when a response cites >5 events with a mandatory type appearing solely past position 5.
- `derive_standing()` in `workspace/implementation/standing.py` is called without `delinquency_cascade=True` from the breach path in `evaluate_join()` (`propagation.py`), so a join-driven breach does not park recipient work. PRD §3.6 names the standing re-derivation there but does not extend the recipient-suspension cascade to it, so the current behaviour is a defensible reading.

**Orchestrator independent verification (per the known "subagent claims a clean sweep with no artifacts" failure mode):** re-listed and re-parsed all 8 `results.$i.json` myself. All 8 files exist (each ~38.8 KB, mtime 23:14) and each reports `passed=120, total=120, failed=0, errors=0, skipped=0`. The clean sweep is confirmed from the artifacts, not merely from the subagent's claim.

## Step 8: Finalize PRD — SKIPPED — 2026-09-04T23:20:00.000Z

Skipped per the skill's explicit skip condition. Step 7 exited on its **first** 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. With an empty `<step_7_diff>` there is no Step-7-derived site of PRD silence or PRD/impl mismatch for Step 8 to patch, and the skill hard-scopes every Step 8 edit to a `<step_7_diff>` item. Spawning the subagent could therefore only produce out-of-scope edits, so no subagent was spawned and no `PRD_FINALIZED.md` was written.

Consequence for Step 9: its input is `workspace/PRD.md` (not `PRD_FINALIZED.md`, which does not exist), and Step 9 still runs in full — the full PRD-vs-implementation scan is the only way to close the residual silences that never produced a test-failure signal, including the two latent underdetermined spots Step 7 flagged in `scoring.py` and `standing.py`.

## Step 9: Complete PRD — 2026-09-04T23:46:00.000Z

**Orchestrator execution decision.** Step 9 was deliberately run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md`, rather than as a single subagent. Rationale: the implementation is 3,429 lines across 15 modules and the PRD is 483 dense lines (112 KB) — a single subagent cannot hold both sides of an exhaustive behavior-by-behavior scan, and the known failure mode is that it silently produces a byte-identical copy (i.e. the scan never actually ran). Pass 1 performed the `cp` and owned the foundation modules; passes 2 and 3 were explicitly forbidden from re-copying and edited in place with surgical `Edit` calls only (never `Write`, to avoid the 64k output cap destroying the file). Each pass was handed the list of rules its predecessors had already pinned so it could neither re-pin nor contradict them, and each was handed its predecessors' open questions as explicit adjudication items. Input was `PRD.md` (Step 8 was skipped, so `PRD_FINALIZED.md` does not exist).

Partition:
- **Pass 1** — `core.py`, `guards.py`, `app.py`, `audit.py`, `scoring.py`, `standing.py` (envelope, clock, versioning, rounding, roles/vocabularies, validation rules 1-4, all 9 calculations, standing derivation + delinquency cascade).
- **Pass 2** — `routes_registry.py`, `routes_consumers.py`, `routes_requests.py`, `lookups.py` (brokers/fees/registrations/disclosures, consumers/consent/collections, intake/verification/execute/deny, resolvers + suppression predicates).
- **Pass 3** — `propagation.py`, `routes_propagation.py`, `routes_suppression.py`, `routes_inquiries.py`, `routes_ops.py`, `start.sh` (fork/ratio/reliability/abandon/join, recipients + tasks, suppression + opt-out signals, inquiries + adequacy, clock + the 6-step sweep).

**Aggregate result: 61 changes — 45 ambiguity-pins, 16 mismatch-revisions.** `PRD.md` 483 lines / 111,741 chars -> `PRD_COMPLETED.md` 483 lines / 134,756 chars (**+23,015 chars, +20.6%**), with **zero net line insertions or deletions** — every change was an in-paragraph insert or revision, no new sections, exactly as the minimal-patch contract requires.

### Pass 1 — 14 ambiguity-pins, 7 mismatch-revisions (+8,090 chars)
- §2.1 — insert — ambiguity — whitespace-only auth header counts as empty; `X-User-Role` matched exactly, no trim/case-fold — `guards.py:109-116`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `core.py:243-247`
- §2.2 — insert — ambiguity — pagination `meta` keys absent from every non-list response — `core.py:250-251,290-301`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` -> `ERR_INVALID_REQUEST`; no `offset` cap; out-of-vocabulary filter value -> 400 (not empty result); boolean filters accept only `true/false/1/0`, case-insensitive, trimmed — `guards.py:289-330`
- §2.3 — insert — ambiguity — `created_at` ties broken by server mint order, never by `id`; ordering is a total order — `core.py:191-237`
- §2.4 — revise — **mismatch** — version bump is once per record **per request**, not per field write; a record created in the call stays at `version` 1 even if later steps rewrite it; `updated_at == created_at` at creation; bump lands before serialization; bump also applies on 4xx paths — `core.py:198-232,277-301`, `app.py:32-37`
- §2.4 — insert — ambiguity — input timestamps accept `Z`, explicit offset (converted to UTC), or no zone (read as UTC); sub-millisecond digits truncated to three on output — `core.py:24-44`
- §2.6 rule 15 — insert — ambiguity — absent/unparseable body == `{}`; non-object body always refused; explicit `null` == omitted key; integer fields must be JSON integers; decimal fields accept a number or decimal string, never a boolean or non-finite — `guards.py:137-228`
- §2.7 — insert — ambiguity — exact decimal arithmetic, never binary float; decimal-place counts fix the *value*, not printed width (80.00 serializes as `80.0`, 1.0000 as `1.0`) — `core.py:60-74,254-263`
- §2.7 — insert — ambiguity — whole-day span = elapsed/24h truncated downward; sub-day interval spans 0 days — `core.py:52-54`
- §2.8 — revise — **mismatch** — a cascade bumps a record exactly once in total however many links reach it — `core.py:211-232`
- §2.8 — revise — **mismatch** — recipient-suspension cascade requires the changed standing to be non-`COMPLIANT` — `standing.py:55-57`
- §2.10 — insert — **mismatch** — appending an audit event raises `audit_sequence_high_water` **without** moving the broker's `version`/`updated_at`; it is the one stored-field write that is not a mutation — `audit.py:25-26`
- §3.1 — insert — ambiguity — `audit_sequence_high_water` initialises at 0 but already reads 1 in the enrolment response, while `version` reads 1 — `audit.py:25`, `core.py:198`
- §3.2 — insert — ambiguity — proration ratio floored at 0; sub-day coverage -> `coverage_days` 0 -> 0-cent final fee — `scoring.py:66-76`
- §3.2 — insert — ambiguity — a zero settlement delta moves no money and leaves broker `version`/`updated_at` untouched — `standing.py:99-101`
- §3.2 — revise — **mismatch** — links 3/4 gated on non-`COMPLIANT`, both iterate `created_at` ascending, and run as two complete passes so all `RECIPIENT_STATUS_CHANGED` events precede all `PROPAGATION_DEFERRED` events — `standing.py:60-85`
- §3.2 — insert — ambiguity — refunding an already-zero `charged_fee_cents` (any `DRAFT`) moves no money and does not advance the broker — `standing.py:88-96`
- §3.4 — insert — ambiguity — stored `raw_score` is rounded to 2 dp while the variant arithmetic subtracts the penalty from the **unrounded** raw and rounds once at the end — `scoring.py:99-117`
- §3.8 — revise — **mismatch** (Step 7 flagged item) — `coverage_bonus_applied` is evaluated over **only the first five credited citations**, so a sixth-position `DELETION_EXECUTED` earns no bonus — `scoring.py:201-203`
- §5 — insert — **mismatch** — `ERR_INVALID_REQUEST` also appears at HTTP 404 (unrouted path) and 405 (method not allowed), both in the standard envelope; trailing slashes tolerated — `app.py:24,39-49`

### Pass 2 — 14 ambiguity-pins, 6 mismatch-revisions (+6,235 chars)
- §2.5 — insert — ambiguity — the three version tokens are themselves required non-negative JSON integers; absent/non-integer/negative answers `ERR_INVALID_REQUEST` (400), not a stale-version rejection — `routes_registry.py:149`, `routes_requests.py:62`
- §2.6 rule 4 — insert — ambiguity — client-supplied owning ids (payload `broker_id`/`consumer_id`, and `/consumers/{id}` itself) are compared before resolution so a foreign non-existent id answers 403; an owning id readable only off the record defers to that family's 404; and rule 4 never reaches a `GET` list, so no list is implicitly scoped to the caller — `routes_registry.py:32,228`, `routes_consumers.py:104`, `routes_registry.py:206`
- §2.6 rule 11 — insert — ambiguity — a missing opt-out signal reuses `ERR_SUPPRESSION_ENTRY_NOT_FOUND` — `lookups.py:64`
- §2.6 rule 14 — revise — **mismatch** — dropped `POST /consumers/{id}/collections` from the cross-broker rule; that endpoint names no broker — `routes_consumers.py:149`
- §2.6 rule 27 — revise — **mismatch** — `SINGLE_SOURCE` matches the consumer record's *current* `source_label`, not one stored on the originating request — `lookups.py:140`
- §2.6 rule 43 — revise — **mismatch** — `ERR_FILING_FEE_UNPAID` also guards `/accept`, over the positive part of final minus provisional — `routes_registry.py:370`
- §3.1 — insert — ambiguity — fee-deposit negative-vs-zero split: negative -> rule 15 / 400, zero or over-cap -> rule 44 / 422 — `routes_registry.py:100`
- §3.1 — revise — **mismatch** — standing re-derivation trigger list corrected: accept/reject/withdraw/sweep-expiry, breach flip, inquiry escalate-deficient-close, sweep step 6; draft-open, submit and rejected-reopen never re-derive (even when the 90-day clause would now match) — `routes_registry.py:381,405,426` and absence at `:344`
- §3.2 — insert — ambiguity — `state_code` outside `operating_state_codes` is rule-15 `ERR_INVALID_REQUEST` — `routes_registry.py:143`
- §3.2 — insert — ambiguity — payload `superseded_registration_id` is never read or validated; the field is server-written only — `routes_registry.py:179,196`
- §3.2 — insert — ambiguity — all matching drafts withdrawn in `created_at` order, `superseded_registration_id` retains the last, withdrawal events carry `actor_role` `system` and follow `REGISTRATION_CREATED` — `routes_registry.py:189`
- §3.2 — insert — ambiguity — the mandatory-`SENSITIVE_CATEGORIES` trigger scans consumers whatever their `collection_status`, including `PURGED` — `routes_registry.py:291`
- §3.2 — insert — ambiguity — **acceptance re-derives standing without the delinquency cascade**: no recipient suspension, no task deferral, even on a non-`COMPLIANT` landing; `STANDING_CHANGED` precedes `REGISTRATION_ACCEPTED` — `routes_registry.py:381`
- §3.3 — insert — ambiguity — purged-hash re-use runs the §3.7 suppression test against each `PURGED` namesake in `created_at` order; first blocker refuses with `ERR_SUPPRESSION_ACTIVE`, `RECOLLECTION_BLOCKED` names the pre-existing consumer, and rule 18 outranks it — `routes_consumers.py:41`
- §3.3 — insert — ambiguity — a collection recorded while `PURGE_PENDING` is not refused and leaves the dimension there — `routes_consumers.py:178`
- §3.3 — insert — ambiguity — both authorized roles may send all three consent actions; the role-to-action narrative is descriptive — `routes_consumers.py:112`
- §3.4 — insert — ambiguity — `agent_loa_reference` on a non-`AUTHORIZED_AGENT` channel is stored, not refused — `routes_requests.py:58`
- §3.4 — revise — ambiguity — `DELETION_REQUEST_RECEIVED` lands last, after every supersession event — `routes_requests.py:99`
- §3.4 — revise — **mismatch** — `document_quality_score` is rounded half up to 2 dp as it is read and stored/echoed in that form, so stored `raw_score` less `fraud_penalty_applied` is always exactly the pre-floor/cap figure the `assurance_score` rounds from (the PRD's claimed "hundredth away" divergence cannot occur) — `routes_requests.py:155`
- §3.5 — insert — ambiguity — the consumer moves to `PURGE_PENDING` only out of `ACTIVE`/`REACQUIRED`; an already-`PURGE_PENDING`/`PURGED` consumer is untouched with no version movement, and `DELETION_EXECUTED` is the only event execution+fork produce — `routes_requests.py:276`, `propagation.py:62`
- §3.7 — revise — **mismatch** — `SINGLE_SOURCE` label source corrected as above, plus the blocked-attempt side effects pinned: entry `version`/`updated_at` advance and `RECOLLECTION_BLOCKED` carries `subject_kind` `CONSUMER` with the consumer's `id` — `lookups.py:140,162`

### Pass 3 — 17 ambiguity-pins, 3 mismatch-revisions (+8,690 chars)
- §2.6 rule 13 — insert — ambiguity — `cited_audit_event_ids` array shape (present, JSON array, all entries non-empty strings) is settled under rule 15 *before* rule 13 resolves entries; empty array is well-formed — `routes_inquiries.py:103-109`
- §2.6 rule 22 — insert — ambiguity — dispatch's owning-request-`EXECUTING` check sits between rule 22 and rule 37, and applies only to dispatch — `routes_propagation.py:182-192`
- §2.6 rule 26 — insert — ambiguity — a `status` equal to the recipient's current value is refused, not a no-op — `routes_propagation.py:96,103,122`
- §2.6 rule 38 — revise — **mismatch** — an absent/`null`/non-string `lift_justification` answers `ERR_LIFT_JUSTIFICATION_REQUIRED` (422), not rule 15's 400 — `routes_suppression.py:142-148`
- §2.10 — revise — **mismatch** — `actor_user_id` is *never* null; sweep- and cascade-driven events carry the triggering principal's `X-User-ID` alongside `actor_role` `system` — `routes_ops.py:29` + `audit.py:15`
- §3.6 dispatch — insert — ambiguity — the three preconditions' evaluation order; `due_at` never recomputed on re-dispatch; dispatch moves no request field — `routes_propagation.py:182-198`
- §3.6 reliability — insert — ambiguity — auto-suspension runs the full manual-suspension cascade (`RECIPIENT_STATUS_CHANGED` + `PROPAGATION_DEFERRED`/`RECIPIENT_SUSPENDED`), all at `actor_role` `system`, and lands *before* the task's own ACKED/FAILED/WAIVED event — `propagation.py:100-121`, `routes_propagation.py:226-235`
- §3.6 posture — insert — ambiguity — `RECIPIENT_STATUS_CHANGED` precedes the per-task chain; suspension deferrals carry the caller's role while termination abandonments carry `system`; restoration appends no per-task event and un-defers every reason including `BROKER_DELINQUENT` — `routes_propagation.py:99-136`
- §3.6 join — insert — ambiguity — **the breach re-derivation runs without the delinquency cascade** (incl. when it lands on `SUSPENDED`), and its `STANDING_CHANGED` lands between `DELETION_COMPLETED` and `SUPPRESSION_CREATED` — `propagation.py:167-170`
- §3.6 join cascade — insert — ambiguity — consumer purge fires only out of `PURGE_PENDING`, else a no-version-move no-op — `propagation.py:173-176`
- §3.6 join cascade — insert — ambiguity — **the minted entry bypasses the buffered-conflict and start<end tests**, so the join can create what `POST /suppression-entries` would refuse and leave overlapping `ACTIVE` entries — `propagation.py:178-190`
- §3.6 join cascade — insert — ambiguity — all three join events carry `actor_role` `system` whichever route reached the join — `routes_propagation.py:236,295`
- §3.7 blocking — insert — ambiguity — **only the earliest-created matching `ACTIVE` entry takes the `blocked_recollection_count` increment**; the later overlapping one stays at zero — `lookups.py:146-159`
- §3.7 honoring — insert — ambiguity — honoring always bumps the consumer's `version`/`updated_at` even when no flag value changes; in-request `OPT_OUT_HONORED` carries the caller's role — `routes_suppression.py:174,257`
- §3.8 opening — insert — ambiguity — a `response_due_at` at or before the clock answers `ERR_INVALID_REQUEST` (400) — `routes_inquiries.py:42-43`
- §3.8 respond — insert — ambiguity — array shape before resolution (mirrors rule 13) — `routes_inquiries.py:103-109`
- §3.8 respond — insert — ambiguity — retention comparison is strict; an event cited exactly at `retention_expires_at` is admissible — `routes_inquiries.py:121`
- §3.8 respond — insert — ambiguity — **the `DEFICIENT`/escalate/close derivations all run without the delinquency cascade** — `routes_inquiries.py:152,174,202`
- §3.8 close — insert — ambiguity — the tally is zeroed after release (never released twice); a zero-contribution close moves no broker field but still re-derives — `routes_inquiries.py:195-202`
- §3.9 steps 5 & 6 — insert/revise — ambiguity — step 5's derivation has no cascade, and a broker already `SUSPENDED` by step 5 gives step 6 nothing to change so its work is never parked; step 6 parks only on a genuine change *to* `SUSPENDED` — `routes_ops.py:106,113-116`

### Both Step-7-flagged latent items were closed
The two PRD-underdetermined spots Step 7 reported but did not act on are now pinned: the `scoring.py` five-credited-citation `coverage_bonus_applied` window (pass 1, §3.8) and the join-driven breach re-derivation running without the delinquency cascade (pass 3, §3.6). Pass 3 additionally traced the same missing-cascade pattern through the inquiry paths (`DEFICIENT`/escalate/close) and sweep step 5, and pinned each.

### Orchestrator independent integrity verification
Re-ran every check myself rather than trusting the passes' self-reports:
- `wc -l -c`: PRD.md 483 / 111,741; PRD_COMPLETED.md 483 / 134,756.
- `cmp -s PRD.md PRD_COMPLETED.md` -> **differs** (the Step 9 scan genuinely ran; the known byte-identical failure mode did not occur).
- All five top-level sections present at lines 3, 11, 206, 374, 433.
- `tail -3` ends on the complete row `| ERR_FEE_DEPOSIT_INVALID | 422 |` — a real section boundary, not mid-sentence. No truncation.
- §4 endpoint table: 54 table lines = 52 endpoint rows + header + separator. §5: **45** `ERR_` rows. Both tables intact after 61 edits.
- `grep -ic "harder than expert"` -> **0**. The Step 2 difficulty directive never reached the final PRD.

### Residual notes for a reviewer (from pass 3, not acted on)
1. `start.sh` implies no PRD-visible behavior (conditional `pip install` + `exec python3 app.py`); no edit made.
2. Pass 3 made one deliberate out-of-scope revision at §2.10 (`actor_user_id` "(null for sweep-driven events)"), a genuine mismatch: `audit.actor_system` is never called with `None` anywhere, so no event carries a null `actor_user_id`. Flagged because passes 1-2 nominally owned §2.10.
3. Deliberately **not** pinned: the `open_breach_count` floor-at-zero clamp at `routes_inquiries.py:198` appears unreachable (contributions are per-inquiry and zeroed on release; nothing else decrements), so pinning it would describe behavior the implementation cannot exhibit.
4. `ERR_REQUEST_INVALID_STATE` on dispatch has no numbered entry of its own in §2.6; pass 3 pinned its priority position inside rule 22's text rather than renumbering the list, since renumbering would ripple through cross-references added by passes 1-2.

**PIPELINE COMPLETE.** `workspace/PRD_COMPLETED.md` written; all 9 steps finished (Step 8 legitimately skipped per its documented skip condition).
