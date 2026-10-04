# Worklog — task_3346_municipal_water_utility_operations_maintenance_contract_delivery

Append-only per-step record. Orchestrator-written; subagent summaries are pasted verbatim.

## Step 1: Create task directory — 2026-10-01T04:12:00.000Z

Task directory `./tasks/task_3346_municipal_water_utility_operations_maintenance_contract_delivery/` was pre-allocated by the caller and already contained `workspace/`. Verified on disk; no new index computed and no other `task_*` directory created.

## Step 2: Generate scaffold — 2026-10-01T04:45:00.000Z

Attempt 1 (agentId a6a2cfeed9d81f06e) stalled after reading the skill and wrote ZERO files — hand-back was truncated mid-sentence ("I'll start by reading the skill specification."). Verified on disk: no `SCAFFOLD*.yaml` anywhere under the task directory or repo. Re-spawned with an explicit early-write + chunked-write (`# __CONTINUE__` sentinel) prompt.

Attempt 2 (agentId a569d2c26891e1306) summary, verbatim:

> All three artifacts are written, parse cleanly, and the linter verdict is clean.
>
> **Files**
> - `/home/ubuntu/github/CodingPRD/tasks/task_3346_municipal_water_utility_operations_maintenance_contract_delivery/SCAFFOLD.yaml`
> - `/home/ubuntu/github/CodingPRD/tasks/task_3346_municipal_water_utility_operations_maintenance_contract_delivery/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
> - `/home/ubuntu/github/CodingPRD/tasks/task_3346_municipal_water_utility_operations_maintenance_contract_delivery/SCAFFOLD_CORNER_DESIGN.yaml`
>
> **Top-level keys**
> - SCAFFOLD.yaml: `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no `scaffold_difficulty_design` / `scaffold_corner_design`)
> - SCAFFOLD_DIFFICULTY_DESIGN.yaml: `scaffold_difficulty_design`
> - SCAFFOLD_CORNER_DESIGN.yaml: `scaffold_corner_design`
>
> **Counts**
> - Entities 15; state machines 14; states 108; transitions 127
> - Calculations 11 (10 with dual variants); validations 66 (ordered by priority, 1–66); endpoints 140 (101 POST, 39 GET); error codes 68; roles 4 (`PlatformAdmin` opaque, `MunicipalityAdmin` entity_backed:Municipality, `OperatorAdmin` entity_backed:Contract, `Employee` entity_backed:Employee); concurrency rules 2 (both OCC on `Contract.version`)
> - §1.8: 9 rules × 2 instances = 18 non-stub instances
> - §1.9: 9 sections, 31 instances (25 with full `test_recipe`, 6 `excluded_because:` stubs, all citing existing §1.8 instance names); 522 structured setup/trigger calls scanned
>
> **Lint verdict (verbatim)**
> ```
> VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
> ```
>
> **Notes worth flagging**
> - Depth pushes beyond the Expert band on the caller's instruction: every one of the 14 entities except the root has 5–10 states, the Contract/Asset/Permit/WorkOrder/PMSchedule/EmergencyEvent/RenewalProposal/TransitionObligation machines all carry genuine cycles or fork-join branches, and the endpoint surface (140) is roughly 4× the §0.4 Expert ceiling — the skill treats those ceilings as guidelines, but downstream generators may need the wider surface handled with the usual output-cap care.
> - Three pins exist purely to make the transitive cascades testable through the API: `POST /_clock/set_current_utc` (default clock `2026-09-01T00:00:00Z`, stated in the endpoint description), `POST /water-om/pm-schedules/{id}/evaluate`, and `POST /water-om/transition-obligations/{id}/evaluate`. All three are declared as first-class endpoints in §1.5 with roles and side effects.
> - Formula-derived assertions were computed by executing the formulas, not estimated: penalty uplift (15% of 6×breach_penalty), per-component rounding divergence (627531 vs 627530), settlement composition (13479452 − 125000 − 900000 = 12454452), benchmark index (3985.0560 cents/MG), staffing floor, and PM compliance — all appear as literals in the assert lists.

Orchestrator disk verification (independent of the hand-back):
- All three files exist: SCAFFOLD.yaml 280,703 B; SCAFFOLD_DIFFICULTY_DESIGN.yaml 87,368 B; SCAFFOLD_CORNER_DESIGN.yaml 101,096 B.
- All three parse via `yaml.safe_load`; top-level keys match the hand-back exactly.
- Zero `# __CONTINUE__` sentinels remain in any file.
- Independently recounted: endpoints 140, entities 15, validations 66, errors 68, roles 4, calculations 11, state_machines 14 — matches.

**RISK FLAG carried into Steps 4–6:** 140 endpoints is ~3.5× the >40 threshold at which Step 6 (impl-gen) is known to return a rambling report instead of writing files. Steps 4, 5, 6, 7 below are therefore run with mandatory chunked-write discipline (one file per message, sentinel-appended chunks) and mandatory orchestrator disk verification of every hand-back claim.

## Step 3: Copy shared files — 2026-10-01T04:46:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3346_municipal_water_utility_operations_maintenance_contract_delivery/workspace/INSTRUCTION.md` (1424 B). Verified present on disk.

## Step 4: Generate PRD — 2026-10-01T04:58:00.000Z

Attempt 1 and attempt 2 both died instantly with `model_not_found` HTTP 404 (`model sent to the API: deepseek-v4p1-flash-wave`) — a transient/infra failure of the default subagent model, not a prompt problem. Verified nothing was written. Attempt 3 pinned `model: opus` and succeeded.

Attempt 3 (agentId a8225abc0181e2692) summary, verbatim:

> PRD generated and verified.
>
> ## Output
>
> `/home/ubuntu/github/CodingPRD/tasks/task_3346_municipal_water_utility_operations_maintenance_contract_delivery/workspace/PRD.md` — 544 lines, 113,667 bytes, zero `<!-- __CONTINUE__ -->` sentinels remaining.
>
> ## Section list
>
> - §1 Introduction (3 paragraphs, angle chosen from attribution/organizational context)
> - §2 Global Specifications — 2.1 RBAC, 2.2 API Response Structure (verbatim), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning, 2.5 Logical Clock & Temporal Evaluation, 2.6 Nested Resource Addressing & Referential Integrity, 2.7 Money/Rounding/Precision, 2.8 Optimistic Concurrency Control, 2.9 Segregation of Duties, 2.10 Validation Ordering & Failure Precedence
> - §3 Business Logic — 3.1 Awarding & Mobilizing, 3.2 Asset Condition Baseline, 3.3 Staffing Commitments & Employee Transition, 3.4 Operating Period: Measurement/Breach/Penalty Allocation, 3.5 Regulatory Permits & NOVs, 3.6 Preventive Maintenance & Work Orders, 3.7 Emergency Response & Notification, 3.8 Benchmark Comparison & Renewal, 3.9 Transition Back & Final Settlement, 3.10 Aggregate Integrity Rules
> - §4 Endpoint Definitions (4-column table, 140 rows)
> - §5 Error Code Catalogue (2-column table, 68 rows)
>
> No audit footer; PRD ends at §5.
>
> ## Verification results
>
> - **Endpoint coverage: 140 of 140 endpoint entries covered** (125 unique paths, all present in §4; all 140 method+path pairs represented — the scaffold has 140 entries over 125 unique paths because `POST .../reviews` and `POST .../renewals` appear twice with different role sets and descriptions, both preserved).
> - **Entity fields: 99/99** present in backticks; **endpoint inputs: 92/92** present; query params (`limit`/`offset`/filters) and path params covered.
> - **States: 0 missing** across all 14 state machines (initial, terminal, and every transition `from`/`to`). **Enum values: 131/131.**
> - **Errors: 0 of 68 absent from §2/§3**; Erratum — all 66 validation `error_id`s reachable in §2/§3.
> - **OCC**: both `concurrency_rules` expressed with `write_endpoint` + `expected_contract_version` + `ERR_STALE_VERSION`/412.
> - **Calculation constants**: all numeric values stated — the two cost thresholds as `2,500,000 cents` and `5,000,000 cents`, the withholding cap as `4,000,000 cents`, plus MGD-per-capita 0.00011, rates 8450/1.0875, tier offsets 120000/185000/250000, uplift 0.15 with 0.40 cap, grace 7 days, withholding escalation at 30 days.
> - **§2.2 byte-for-byte** match against `section-2.2-response-structure.md`: PASS.
>
> ## Hard Contracts
>
> ```
> Field coverage check:
> - entities[].fields: 99 required, 99 present, 0 missing
> - endpoints[].request_body/input: 92 required, 92 present, 0 missing
> - endpoints[].path_params (id/eid/cid/sid): 4 present, 0 missing
> - endpoints[].query_params: 15 present, 0 missing
> Status: PASS
> ```
>
> ```
> Rule coverage check:
> - validations[] with priority: 66 checked, 66 expressed in prose, 0 missing
> - concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_contract_version + error_id all named), 0 missing
> - state_machines[].transitions: 137 checked, 137 fully expressed, 0 missing
> - calculations[]: 11 checked, 11 fully expressed, 0 missing
> - validations[] conditions: 66 checked, 66 matchable to error_id in prose, 0 missing
> - endpoints[].side_effects / applies_to: 140 checked, 140 expressed, 0 missing
> - entities[].fields[] structured content: 99 checked, 99 reconstructible from prose, 0 missing
> - sibling-branch symmetry: 12 groups checked (emergency escalate from CONTAINED vs RESTORED, termination from OPERATING vs UNDER_REVIEW, hand-back from RENEWAL_PENDING vs UNDER_REVIEW, accept from SUBMITTED vs COUNTERED, work-order complete from IN_PROGRESS/PAUSED/RETURNED vs verify-return, etc.), 12 with equal prose density, 0 asymmetric
> Status: PASS
> ```
>
> ```
> Path purity check (§3 only):
> - backtick tokens scanned: 1074
> - tokens starting with "/": 0
> - bare HTTP-method tokens: 0
> - method+path combined tokens: 0
> Status: PASS
> ```
>
> Note on a check-instrumentation caveat: naive backtick tokenization is corrupted by the triple-backtick JSON code fences in the verbatim §2.2 block; the final counts above strip fenced regions first. Both forbidden files and all sibling task directories were left unread.

Orchestrator disk verification (independent of the hand-back):
- `workspace/PRD.md` exists; `wc -l -c` = **543 lines / 113,667 bytes** (hand-back said 544 lines — off-by-one on its own count, immaterial; byte count matches exactly).
- Zero `<!-- __CONTINUE__ -->` sentinels remain.
- Independently re-derived endpoint coverage with python3/yaml: scaffold has **140 endpoint entries over 125 unique paths**; **0 paths missing** from PRD.md. Hand-back's 140/140 and 125-unique claims confirmed.

Isolation compliance: the two design-index files were not read; PRD generated from SCAFFOLD.yaml only.
## Step 5 (partial): Unit test generation — interrupted — 2026-10-01T07:16:00.000Z

Step 5 was launched four times; every attempt was killed by the infrastructure outage (`model_not_found`, HTTP 404 on `deepseek-v4p1-flash-wave`) — the same outage that stopped the whole pipeline. Attempts 1–2 died before writing anything; attempt 3 wrote the complete `test_helpers/` layer and then died; attempt 4 died while reading the helpers.

**Orchestrator disk verification of what survived (NOT a subagent claim):**
- `test_helpers/` is COMPLETE and self-consistent: `__init__.py` (27 L), `types.py` (306 L), `api_client.py` (441 L), `api_errors.py` (148 L), `assertions.py` (208 L), `factories.py` (179 L), `constants.py` (114 L), `test_users.py` (47 L), `fixtures.py` (533 L) — 9/9 files, ~2003 lines.
- All 9 files `py_compile` clean; ZERO `# __CONTINUE__` sentinels remain (no truncated chunks).
- Content spot-checks passed: `ApiClient` subclasses the harness `GenericApiClient` (so `$PORT` resolution comes from the runner, not a hardcoded port — grep for a hardcoded port/localhost returned nothing); `test_users.py` implements the PRD's entity_backed ownership model with per-call `make_*_headers(user_id)` builders and explicitly warns that the shared `TEST_USERS` constants are fallbacks for non-ownership-gated calls only; `fixtures.py` constructs ALL state through declared API endpoints (municipality → contract → standards → assets → baseline → permits → staffing → employees → transfer) and drives the logical clock via `set_clock`/`api_client.set_current_utc` rather than wall-clock now.
- `test_suite/` does NOT exist — it was never started. Step 5 is therefore PARTIAL, not complete.

Decision: keep the verified `test_helpers/` (re-verified against source per the "a lost subagent report is not a lost artifact" rule) and generate only the missing `test_suite/`.

## Step 5 (completion): Unit test generation — 2026-10-01T07:47:00.000Z

Re-spawned after the outage cleared (agentId a9257b557993f8e1e, no model override). It audited the surviving `test_helpers/`, left it unmodified, and generated the missing `test_suite/`. Summary, verbatim:

> All checks pass. Here is the final report.
>
> ## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_3346_municipal_water_utility_operations_maintenance_contract_delivery/`)
>
> | File | Lines |
> |---|---|
> | `test_suite/conftest.py` | 65 |
> | `test_suite/test_difficulty_calculations.py` | 257 |
> | `test_suite/test_difficulty_state_machine.py` | 191 |
> | `test_suite/test_difficulty_cascade.py` | 318 |
> | `test_suite/test_difficulty_validation.py` | 356 |
> | `test_suite/test_corner_entities.py` | 114 |
> | `test_suite/test_corner_state_machines.py` | 201 |
> | `test_suite/test_corner_calculations.py` | 175 |
> | `test_suite/test_corner_validations.py` | 148 |
> | `test_suite/test_corner_endpoints.py` | 120 |
> | `test_suite/test_corner_errors_rbac.py` | 186 |
> | `test_suite/test_corner_cross_cutting.py` | 309 |
> | **Total** | **2440** |
>
> `test_helpers/` was not modified. Every test builds state through the shipped helpers (`setup_operating_contract`, `setup_under_review_contract`, `setup_operating_contract_with_permit`, `register_*`/`award_contract`/`create_standard`/…), drives the logical clock via `set_clock`, and binds `X-User-ID` to real entity ids (`make_*_headers(<id>)`); no port is hardcoded.
>
> ## Tests emitted
> - Queue A (Difficulty): **18 tests**, covering **16 distinct instances** (3 of them on the penalty-allocation instance — its PRD worked illustration and the cap boundary).
> - Queue B (Corner): **30 tests**, covering **30 distinct instances** (the 5 `excluded_because` stubs were not translated).
> - Total 48 tests, 48 `Design:` tags, all single-tagged.
>
> ## Skipped instances (3)
> 1. `Difficulty/non_linear_state_machine/renewal_negotiation_cycle_across_counter_rounds` — PRD §3.8 gates submission on `benchmark_ratio ≤ 1.25` with ratio base = municipality `benchmark_index_baseline` × `staffing_floor_fte` × 12; for the asserted 41,000,000-cent fee the base is ≈30,127 (floor 0.63) or 0 (index 0.0 while the contract is not in a live status), so the submission the counter-cycle depends on is unreachable. PRD also pins the counter's next-round number as "the contract's `renewal_round` plus one" (=1), contradicting the instance's literal `2`.
> 2. `Difficulty/compensating_invariant/pm_completion_clears_overdue_without_losing_history` — the OVERDUE regeneration requires the linked preventive work order to be `CLOSED`, but PRD never states that auto-created work order's `estimated_cost_cents`; a zero estimate classifies as `PENDING_CLASSIFICATION`, which PRD forbids closing (`ERR_EXPENSE_CLASS_UNRESOLVED`), so the asserted post-regeneration state is unreachable. The index's `compliance_rate_pct == 50.0` / `next_due_at == 2026-11-12` also do not follow from the stated compliance and regeneration arithmetic.
> 3. `Corner/consistency_model/affected_asset_condition_band_reconciles_after_verification` — PRD §3.2 names the five condition bands but never states their numeric boundaries, so "54.0 reads back as `FAIR`" is not uniquely derivable (same reason the `condition_band == 'CRITICAL'` literal in the verification-cascade instance was dropped while its cascade assertions were kept).
>
> ## PRD-vs-index corrections applied (index literal contradicted PRD; test follows PRD)
> - Expense-class branch selection: index said the 100%-elapsed asset → `OPERATING`; PRD's pinned order yields `CAPITAL_LIFE_EVENT` (2011+15 ≤ 2026) and `CAPITAL_THRESHOLD` for the 66.7%-elapsed asset.
> - PM-miss cascade: the index timeline produces only 2 misses; clock extended one more window to reach exactly 3, and the "exactly one work order row" literal ignores the preventive order created at `DUE`.
> - `contract_version_increments_…`: index's literal `3` ignores the version bump from standard activation; asserted one increment per state-writing call instead.
> - Both stale-version instances: index setups were unreachable (review `CLOSE` from `OPERATING`; hand-back from `RENEWED`); realized with a PRD-legal intervening bump (penalty allocation / entering renewal).
> - `work_order_schedule_from_closed_state_is_rejected`: PRD names both `ERR_ALREADY_TERMINAL` and `ERR_CLOSED_WORK_ORDER_IMMUTABLE` → `validate_error_is_one_of`, with terminal-state and closure-cost assertions kept.
> - Both not-found instances: index bound `X-User-ID` to a non-existent contract, which PRD §2.1 rejects as `ERR_ACTOR_NOT_FOUND` first; actor now bound to a real contract.
> - Vesting instance: index hire date is 3652 days (=10.01 y under PRD's /365 rule); used a hire date exactly 3650 days before contract start so `10.00 / ENHANCED / 2500000` is derivable.
> - Dropped non-derivable literals: settlement proration (PRD never defines "operating days" — composition identity asserted instead), benchmark "live contract count" (field unnamed), review-cascade penalty total `== 0`, termination-cascade commitment `SHORTFALL`, and the "client-supplied expense_class is ignored" half (PRD is silent on unknown payload fields).
>
> ## Verification (raw results)
> - (a) 48 `Design:` tags, **0 unresolvable**; 0 tags pointing at `excluded_because` stubs; 0 untagged test functions; 0 functions with more than one tag. Additionally, all **78** PRD citation quotes were checked as literal substrings of `workspace/PRD.md` — 0 misses.
> - (b) Queue A: 18 tests / 16 distinct instances (18 expected ceiling); Queue B: 30 tests / 30 distinct instances (31 non-stub). Uncovered: the two queue-A instances and the one queue-B instance listed above.
> - (c) `# __CONTINUE__` sentinels remaining: **NONE**.
> - (d) `py_compile`: **12 of 12 files OK**; all 11 test modules import cleanly; `pytest test_suite --collect-only -q` → **48 tests collected, 0 errors**.

Orchestrator disk verification (independent of the hand-back):
- 12 files / **2440 lines total** — matches the hand-back table exactly, file by file.
- Zero `# __CONTINUE__` sentinels; all 12 files `py_compile` clean.
- Independently re-derived tag validity with python3/yaml: **48 tags, 0 unresolvable, 0 pointing at stubs**. Distinct instances covered **46 of 49** — consistent with the 3 declared skips. One instance (`Difficulty/dual_variant_calc/penalty_share_forward_looking_vs_chronological_recidivist`) carries 3 tests, which the hand-back disclosed; the contract requires one instance per test, not one test per instance, so this is extra coverage rather than a tagging violation.
- `pytest test_suite --collect-only -q` → **48 tests collected in 0.18s, 0 errors**.

Design-index-only contract honored: every test traces to exactly one §1.8/§1.9 instance; no SCAFFOLD-derived baseline/smoke/RBAC/listing/pagination tests were invented. 3 instances skipped on the PRD-first two-condition filter rather than weakened.

## Step 6: Generate implementation — 2026-10-01T08:30:00.000Z

Single subagent (agentId a244f988412af4b7b), launched alone per the sequential-Steps-5/6 instruction, with the ISOLATION RULE enforced (no read of the two design indices, `test_suite/`, or `test_helpers/`; no test-suite execution) and chunked-write discipline mandated up front because this scaffold is ~3.5x the endpoint count that has historically made impl-gen return a report instead of files. Summary, verbatim:

> Implementation complete and verified on disk.
>
> ## Deliverable — `workspace/implementation/` (16 files, 4494 lines)
>
> | File | Lines | Role |
> |---|---|---|
> | `start.sh` | 11 | guarded dep install, `exec python3 app.py`, foreground, `$PORT` |
> | `requirements.txt` | 1 | `Flask>=2.2` |
> | `core.py` | 636 | app object, in-memory store, logical clock, envelope, error catalogue, auth/RBAC, pagination, route decorator |
> | `calc.py` | 395 | the 11 calculation rules |
> | `services.py` | 424 | shared cascades (staffing floor, breach penalty, PM evaluation, obligations, allocations) |
> | `routes_contracts.py` | 422 | municipalities, contracts, reviews, renewals, hand-back, settlement |
> | `routes_standards.py` | 345 | standards + measurements |
> | `routes_staffing.py` | 382 | staffing commitments + employee transition |
> | `routes_assets.py` | 341 | assets + condition assessments |
> | `routes_pm.py` | 214 | preventive maintenance schedules |
> | `routes_workorders.py` | 307 | work orders |
> | `routes_permits.py` | 389 | permits + penalty allocations |
> | `routes_emergency.py` | 246 | emergency events |
> | `routes_renewal.py` | 347 | renewal proposals + transition obligations |
> | `routes_misc.py` | 9 | logical clock |
> | `app.py` | 25 | assembly + `0.0.0.0:$PORT` foreground server |
>
> ## Verification (raw results)
> - **(a)** `ls -la` above; no `__pycache__`, no data files, nothing persisted.
> - **(b)** `bash -n start.sh` → `bash -n OK`.
> - **(c)** Boot 1 on `PORT=8137` → `401` with the exact PRD error envelope `{"meta":{"api_request_id","api_request_timestamp"},"response_type":"error","data":{"error_id","message"}}`; killed exactly the recorded PID; port released. Boot 2 on `PORT=8138` (fresh process, different port) → same envelope, `/_clock/set_current_utc` → `{"current_utc":"2026-09-01T00:00:00.000Z"}` (default clock, empty store). Ports released.
> - **(d)** **140 registered endpoint entries / 125 unique paths** — exact match with SCAFFOLD.yaml.
> - **(e)** zero `# __CONTINUE__` sentinels.
> - Functional sweeps (7 scripts, ~120 calls, 0 tracebacks) exercised: award→mobilize→baseline→freeze→commence, staffing floor 2.50, vesting GRANDFATHERED/0, work-order cost `631703` (matches the scaffold's worked example exactly), PM DUE→WO→regenerate (compliance 100.0), review open/close + `ERR_STALE_VERSION`, renewal negotiate/counter/accept, hand-back→obligations→settlement→`TRANSITIONED`, permits/allocations (`720000/1080000/720000` first-allocation comparator), emergency dispatch/contain/restore/notify/escalate/investigate/close, and the guard catalogue (`ERR_DUPLICATE_*`, `ERR_MEASUREMENT_PERIOD_OVERLAP`, `ERR_THRESHOLD_DIRECTION_INVALID`, `ERR_PM_WINDOW_TOO_FAR`, `ERR_CAPITAL_THRESHOLD_NOT_MET`, `ERR_OPEN_WORK_ORDER_BLOCKS`, `ERR_CLOSED_WORK_ORDER_IMMUTABLE`, `ERR_BASELINE_FROZEN`, `ERR_CRITICAL_OBLIGATION_NOT_WAIVABLE`, `ERR_NOTIFICATION_WINDOW_CLOSED`, `ERR_CONTAINMENT_WINDOW_EXCEEDED`, `ERR_OBLIGATION_DUE_BEFORE_HANDOFF`).
> - One real bug found and fixed during smoke testing: `Contract` had no `total_operator_penalty_cents` field although §3.4/§2.8 require it; added at award and to the version-tracking field set.
>
> ## PRD rules I could not implement exactly (named-but-unvalued constants / self-contradictions)
> 1. **`ERR_REPORTING_FREQUENCY_VIOLATION`** — "the permit's reporting frequency" is never valued and `Permit` has no such field. Implemented as a 30-day minimum monitoring interval.
> 2. **Critical containment window** — no value anywhere; implemented as the event's `notify_deadline_at`.
> 3. **Condition band cut points** — bands are named but never valued; implemented at 80/60/40/20, compared at 1 dp.
> 4. **"review tolerance"** — no value; implemented as the contract's `annual_fee_cents` (the same ceiling used by `ERR_PENALTY_CAP_EXCEEDED`).
> 5. **Operator share when a standard moves to `BREACHED`** — "the operator share computed by the penalty allocation formula" but no allocation exists then; implemented with the standard's `breach_penalty_cents` as the total.
> 6. **`ERR_CRITICAL_ACKNOWLEDGEMENT_MISSING`** — requires two operator acknowledgements but declares no ack endpoint/field; implemented by counting the operator's recorded actions (dispatch/contain/restore/notify), so a `CONTAINED` event always clears it.
> 7. **Penalty-allocation illustration is internally inconsistent** — 720,000 + 270,000 is stated to equal 1,620,000. I implemented the stated formula (990,000 for those inputs). Flagging because both PRD and scaffold repeat 1,620,000.
> 8. **`expected_contract_version`** — §2.8 says renewal acceptance takes no version field, §3.8 says it does; implemented as validated-when-present on acceptance, optional on reviews/hand-back (no error id exists for a missing one).
> 9. **Notification boundary** — validation 39 says "strictly before the deadline" while §3.7's worked illustration requires filing *at* the deadline to be accepted-and-late; implemented the illustration.
> 10. **Wrong from-state on entities with no dedicated invalid-state error** (standard, measurement, assessment, permit, employee, proposal, obligation) — the catalogue has no such id; used `ERR_ALREADY_TERMINAL` (409).
> 11. **PM schedule created after commence stays `DRAFT`** — literal reading (DRAFT→ACTIVE is only the commence cascade); a schedule created post-commence never goes live.
> 12. **Generated hand-back obligations** — `due_at` = hand-back start + 30 days, `is_critical` false, `penalty_per_day_cents` 0 (none stated; non-critical keeps `complete-hand-back` reachable).
> 13. **Auto-created work orders** — flagging cascade estimates 2,500,000 cents (so scheduling reclassifies it `CAPITAL_LIFE_EVENT`), PM-DUE cascade 250,000 cents (`OPERATING`); a 0 estimate would classify `PENDING_CLASSIFICATION` and permanently block closure.
> 14. **`ERR_INVALID_PAGINATION`** (400) plus `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` for unmatched routes — the PRD mandates a client error for out-of-range `limit` but declares no id.
> 15. **60 % capital-service test** — measured from Jan 1 of `install_year` (no in-service timestamp exists).
> 16. **Escalation-created allocation** — `total_penalty_cents` 0, `violation_code` = event type (no amount stated).
> 17. **`await-parts`** requires `actual_cost_cents > 0`, which is only ever set at completion, so the transition is effectively unreachable; implemented literally.
> 18. **Ownership-gate error** — §2.1 mandates FK-vs-`X-User-ID` ownership checks but names no error; used `ERR_CROSS_TENANT_DENIED` (403), and existence (404) is evaluated before ownership so random-id probes still return the per-entity not-found error.

Orchestrator disk verification (independent of the hand-back):
- 16 files present, **4494 lines total** — matches the hand-back table file by file (app.py 881 B, calc.py 14432 B, core.py 24122 B, routes_*.py, services.py, start.sh 444 B, requirements.txt 11 B).
- Zero `# __CONTINUE__` sentinels anywhere under `implementation/`.
- **Route surface is an EXACT match**: after normalizing Flask `<param>` to scaffold `{param}` (name-preserving), the diff is `MISSING: 0`, `EXTRA: 0` — 140 registered method+path entries / 125 unique paths against 140 scaffold entries / 125 unique paths.
- **Independent boot smoke test (orchestrator-run, not subagent-reported):** `PORT=8192 bash start.sh` served the PRD envelope; `POST /water-om/_clock/set_current_utc` with `{"to_iso8601":"2026-10-01T00:00:00Z"}` → `{"current_utc":"2026-10-01T00:00:00.000Z"}`. A SECOND independent process on `PORT=8193` booted to the default clock `2026-09-01T00:00:00.000Z` (proving fresh-boot state wipe) and correctly rejected `{}` with `ERR_INVALID_DATE_WINDOW`/"Missing required field 'to_iso8601'".
- `start.sh` reads `$PORT`, binds `0.0.0.0`, `exec`s in the foreground; dependency install is guarded so the per-test reboot does not re-run pip.
- No data files, no `__pycache__`, no on-disk state under `implementation/`.
- Orchestrator mis-step worth recording: an initial route diff used a normalizer that collapsed multi-param paths (`<eid>`→`{id}`), and an initial clock curl omitted the `/water-om` prefix the `endpoint` decorator applies — both produced transient false alarms that were resolved by re-checking against source. **No implementation defect existed**; the route surface and clock are correct.

**UPSTREAM DEFECT FLAGGED FOR THE DOC-GENERATOR (carried into Steps 7–9):** hand-back item 7 — PRD §3.4's penalty-allocation worked illustration states 720,000 + 270,000 = 1,620,000, which is arithmetically wrong (the stated formula yields 990,000). Both PRD.md and SCAFFOLD.yaml repeat the bad total. The implementation follows the formula. Tests that assert the illustrative total rather than the formula will fail; per the PRD-first contract they must be reconciled against the formula, and the PRD text should be corrected in Step 8/9.

## Step 7: Run tests and iterate — 2026-10-01T08:52:00.000Z

Single long-lived fix subagent (agentId ab512b2ba4bf9c6df) owning the whole run-diagnose-fix-rerun loop, per the skill's one-long-lived-subagent rule. Summary, verbatim:

> All 8 rounds of the final sweep are clean. Here is the summary.
>
> ## Result: 47/47 tests pass in all 8 parallel rounds (0 failures, 0 errors)
>
> Iterations run: **4** (sweeps: 25 failures → 3 → 1 → 0).
>
> ### Tests deleted (1)
>
> - **`test_corner_calculations.py::test_settlement_composes_proration_withholding_and_non_void_penalties`** — COMPUTED-FIELD SILENCE. PRD §3.9 states the settlement arithmetic as prose only ("the prorated fee", "the withholding total", "the penalty total", "the net payable") and never backticks any of the four response field names — while every other computed field in the PRD is backticked (`filled_fte`, `outstanding_days`, `operator_share_cents`, …). The test asserted the **scaffold formula's** exact keys (`withholding_total`, `penalty_total`), mixed with `_cents`-suffixed siblings the scaffold also spells that way. A PRD-only implementer naming them `withholding_total_cents`/`penalty_total_cents` — matching the API's pervasive `_cents` convention — is equally faithful and fails the test; the shipped implementation did exactly that. Drives a **doc-generator Zero-Silence Rule** note: the `contract_settlement_net` calculation's four output names never reached PRD prose as tokens.
>
> ### Fixes to `test_helpers/`
>
> - **`fixtures.py` → `setup_operating_contract()`** — reordered the contract lifecycle to **mobilize → freeze-baseline → fill roster → commence**. PRD §3.1 makes `baseline_frozen == false` a *mobilization* precondition and §3.3 makes the frozen baseline a *transfer* precondition; the old freeze-then-mobilize order violated the PRD, so every fixture-built contract died with `409 ERR_CONTRACT_INVALID_STATE` (24 of the 25 initial failures). Same function: the roster now fills to `max(filled_fte, staffing_floor_fte)` with ≤1.0 FTE per employee (PRD §3.3 caps `transfer_offer_fte` at 1.0), so commence's `filled_fte >= staffing_floor_fte` precondition holds for multi-standard contracts.
>
> ### Fixes to `test_suite/`
>
> - **`test_corner_state_machines.py`**, **`test_difficulty_cascade.py`** (`_operating_contract`), **`test_difficulty_validation.py`** (`_operating_contract`) — same freeze/mobilize swap at the three inline sites.
> - **`test_difficulty_cascade.py::test_transfer_of_an_accepted_employee_is_blocked_until_the_baseline_is_frozen`** — relaxed the exact error id to `validate_error_is_one_of([ERR_CONTRACT_INVALID_STATE, ERR_ASSET_BASELINE_UNRESOLVED])`. PRD §3.3 requires the freeze but names no error, and the path names an *employee already in its correct from-state*, so §3.10's invalid-state mapping does not pin one. State-unchanged assertion kept.
> - **`test_corner_cross_cutting.py::test_hand_back_with_a_pre_renewal_version_…`** — removed a double `validate_success()` wrapper around `enter_renewal_negotiation()`, which already validates and returns the data dict.
> - **`test_corner_calculations.py::test_settlement_composes_…`** — deleted (above); now-unused imports pruned.
>
> ### Fixes to `implementation/`
>
> - **`routes_staffing.py` → `transfer_employee()`** — the `baseline_frozen` and clock guards raised `ERR_ALREADY_TERMINAL`, which §3.10 defines as terminal-state-only; the employee is in `ACCEPTED`. Now `ERR_CONTRACT_INVALID_STATE`.
> - **`services.py` → `evaluate_schedule()`** — the overdue test was gated on `status == "DUE"`, so once a schedule reached `OVERDUE` it never re-fired: `missed_occurrence_count` stuck at 1 and `next_due_at` never advanced again, making the PRD's "exactly 3 → `REPLACEMENT_FLAGGED`" rule unreachable. Now applies to `DUE` **and** `OVERDUE`, re-stamping `status_changed_at` only on an actual transition.
>
> ### Notes
>
> - The known upstream PRD §3.4 defect (720,000 + 270,000 stated as 1,620,000) affects no test — nothing in `test_suite/` or `test_helpers/` asserts the erroneous illustration.
> - Sweep evidence is intact: 8 × `results.{1..8}.json` in `workspace/implementation/`, all written after the last source edit (newest source mtime 08:47:28; sweep ran 08:47:41–08:49:07), so no post-sweep write invalidates the clean run. No on-disk state exists under `implementation/` beyond the required results files.

Orchestrator disk verification (independent of the hand-back):
- **All 8 `results.{1..8}.json` present and green**: each round independently parsed → `passed=47, total=47, failed=0`. Eight files, 15.3 KB each, all stamped 08:49:07.
- **Sweep not invalidated by later writes**: newest *source* mtime across `implementation/`, `test_suite/`, `test_helpers/` (excluding `__pycache__`) is **08:47:28** (`test_suite/test_corner_calculations.py`); the sweep ran at **08:49:07**. No source write postdates the clean sweep. (Compared source-file mtimes, not directory mtimes, per the `__pycache__` false-positive rule.)
- **Test count**: `pytest --collect-only -q` → **47 collected**, consistent with 48 generated minus the 1 deletion.
- **Deletion independently re-verified against source** (not accepted on the hand-back's word): `grep -c` for backticked `` `withholding_total` ``, `` `penalty_total` ``, `` `prorated_fee_cents` ``, `` `net_payable_cents` `` in `workspace/PRD.md` → **0 matches**. PRD line 307 renders the settlement arithmetic purely as prose ("The prorated fee is … The withholding total is … The net payable is …") with no field-name tokens. A PRD-only implementer is therefore free to name the serialized keys `*_cents`, so the test's exact-key assertion was not uniquely derivable — COMPUTED-FIELD SILENCE confirmed, deletion stands.
- **Fixture fix independently plausible from source**: the freeze/mobilize ordering is a PRD precondition chain (§3.1 mobilization requires an unfrozen baseline; §3.3 transfer requires the frozen baseline), and a single upstream fixture defect explaining 24 of 25 initial failures matches the documented triage hint (≥5 failures sharing one setup error ⇒ suspect `test_helpers/` first).

Step 8 is REQUIRED (not skipped): Step 7 ran 4 iterations with 1 deletion, 3 `test_suite/` fixes, 1 `test_helpers/` fix, and 2 `implementation/` fixes — far from the "0 iterations / 0 fixes" skip condition.

## Step 8: Finalize PRD — 2026-10-01T09:00:00.000Z

Ran (Step 8 is required here — Step 7 ran 4 iterations with 1 deletion / 3 `test_suite/` fixes / 1 `test_helpers/` fix / 2 `implementation/` fixes, far from the skip condition). Subagent (agentId a2122b4b98a165a63), with the Step 7 entry inlined verbatim as `<step_7_diff>`. Summary, verbatim:

> All edits are complete and verified. Final report:
>
> ## Deliverable
>
> `/home/ubuntu/github/CodingPRD/tasks/task_3346_municipal_water_utility_operations_maintenance_contract_delivery/workspace/PRD_FINALIZED.md` — 543 lines / 114,763 bytes vs. `PRD.md` 543 lines / 113,667 bytes: **0.00% line delta** (byte delta +0.96%). 5 lines replaced, 0 inserted/deleted sections.
>
> ## Changes (one bullet per change)
>
> - **§3.3 Staffing Commitments and the Employee Transition — revise** — added "an attempt that fails either precondition is rejected with `ERR_CONTRACT_INVALID_STATE` (HTTP 409)" to the transfer sentence (previously silent on the error, and §3.10's terminal-state rule does not cover it since the employee is in its correct from-state). — `implementation/routes_staffing.py:304-307`.
> - **§3.6 Preventive Maintenance — revise** — pinned that the overdue test is keyed to the current `next_due_at`, applies on every evaluation while the schedule is `DUE`/`OVERDUE` (including the evaluation that just moved it `ACTIVE`→`DUE`), so repeated misses increment `missed_occurrence_count` past 1; `status_changed_at` is stamped only on actual entry into `OVERDUE`. Previously the sentence read as a one-shot transition, which made the "exactly 3 → `REPLACEMENT_FLAGGED`" rule unreachable. — `implementation/services.py:237-267`.
> - **§3.9 Final Settlement — revise** — the settlement paragraph now names the returned fields: `prorated_fee_cents`, `withholding_total_cents`, `penalty_total_cents`, `net_payable_cents`, plus `contract_id` and `operating_days` (defined as whole 24-hour periods elapsed after `contract_start_date`, 0 before it). Previously only prose names, no backticks. — `implementation/calc.py:357-374`; consumed at `implementation/routes_contracts.py:349-351` and `:405-410`.
> - **§3.4 Penalty Allocation illustration — revise** — corrected the illustrative operator share for 1,800,000 cents at 0.40 with one breached standard from 1,620,000 to 990,000 (720,000 + 270,000), matching the PRD's own formula and the impl. — `implementation/calc.py:133-138`.
> - **§3.4 Comparator paragraph — revise** — same corrected figure restated: forward-looking basis yields 990,000 (not 1,620,000) with one breached standard. — `implementation/calc.py:133-138`, `:156-165`.
>
> **Deliberately not edited** (Step 7 items that are pure fixture/test bugs the PRD already determines): the freeze→mobilize ordering swap in `test_helpers/fixtures.py` and three inline test sites (§3.1 makes `baseline_frozen == false` a mobilization precondition; §3.3 makes the frozen baseline a transfer precondition); the roster fill to `max(filled_fte, staffing_floor_fte)` (§3.3 caps `transfer_offer_fte` at 1.0; §3.1 commence requires filled ≥ floor); the removed double `validate_success()` wrapper (test-only bug).
>
> ## Per-edit pre-edit search log
>
> 1. **§3.9 settlement fields** — (a) Subject: the settlement object's returned field names and its `operating_days` figure. (b) Enumerated/read: `calc.py:345-374` (sole producer); `routes_contracts.py:342-369` (complete_hand_back consumes `net_payable_cents` for `ERR_NEGATIVE_SETTLEMENT`); `routes_contracts.py:405-410` (GET settlement returns the object); grep `settlement|prorated|net_payable|operating_days` (only those hits) and `annual_fee_cents|365` (other 365 uses — `routes_renewal.py:185` term extension, `calc.py:176` benchmark gallons, `calc.py:297` years of service — are unrelated). (c) Wording adjustment: named all six returned keys rather than only the four the deleted test touched, since `calc.settlement` also returns `contract_id`/`operating_days` and the object shape would otherwise stay under-determined; the `operating_days` definition is scoped to the settlement arithmetic (its only callsite).
> 2. **§3.3 transfer error** — (a) Subject: error raised when the transfer is blocked by an unfrozen baseline or by the clock preceding `contract_start_date`. (b) Enumerated: `routes_staffing.py:295-319` (only path that sets `TRANSFERRED`; both guards raise `ERR_CONTRACT_INVALID_STATE`); grep `baseline_frozen` across all files — the other seven guards raise different errors (`routes_contracts.py:152/181/299/324`, `routes_permits.py:115`, `routes_assets.py:153/273/297`); grep `TRANSFERRED` — no cascade enters that state. (c) Wording adjustment: scoped the sentence to "an attempt" on the transfer route rather than stating a general rule about unfrozen baselines, because sibling routes raise `ERR_ASSET_BASELINE_UNRESOLVED` / `ERR_ALREADY_TERMINAL` / `ERR_ASSET_INVALID_STATE` for their own frozen-baseline guards.
> 3. **§3.6 overdue re-fire** — (a) Subject: the rule driving a schedule into `OVERDUE` and counting missed occurrences. (b) Enumerated/read: `services.py:237-273` (sole implementation, only increment site); `routes_pm.py:207-214` (only caller — the evaluate endpoint, which rejects `SUSPENDED`/`COMPLETED`/`RETIRED`); `routes_pm.py:112-141` (regenerate), `:160-174` (reactivate), `:177-204` (close-out/retire); `routes_contracts.py:200-206` (commence fan-out); `routes_assets.py:190-215` (complete-replacement advances `next_due_at`); `calc.py:229-247` (compliance rate); grep `evaluate_schedule|next_due_at|OVERDUE|missed_occurrence_count`. (c) Wording adjustment: bounded the sentence to "every evaluation of a schedule that is `DUE` or `OVERDUE`" and "keyed to the current `next_due_at`" so it does not describe regenerate/reactivate/complete-replacement (which move the schedule out of, or re-stamp, `next_due_at` without counting misses) as counting occurrences; the "stamping `status_changed_at` when it actually enters that state" clause matches the impl's conditional re-stamp, leaving repeated `OVERDUE` evaluations unstamped. A second pass removed "re-applied on each later evaluation", which could have implied a prior evaluation is required for the single-call `ACTIVE`→`DUE`→`OVERDUE` path.
> 4. **§3.4 illustration (forward-looking)** — (a) Subject: worked illustration of the forward-looking allocation. (b) Enumerated/read: `calc.py:130-138` (`penalty_shares`), `calc.py:156-165` (`state_baseline_share`), `services.py:35-40`, `services.py:355-363`, `routes_permits.py:283-290`, `:334-339`; verified 1,800,000 × 0.40 = 720,000, uplift 1,800,000 × 0.15 = 270,000, cap 1,800,000 not binding → 990,000. (c) Wording adjustment: none — only the numeric total changed; formula prose already matches the impl.
> 5. **§3.4 comparator paragraph** — (a) Subject: the restated forward-looking figure inside the comparator illustration. (b) Same enumeration as edit 4 (comparator path `calc.py:156-165` re-read to confirm the 720,000 comparator figure is unaffected). (c) Wording adjustment: none — only 1,620,000 → 990,000.

Orchestrator disk verification (independent of the hand-back):
- `PRD_FINALIZED.md` exists at 543 lines / 114,763 bytes vs `PRD.md` 543 lines / 113,667 bytes — matches the hand-back exactly.
- **Not a silent no-op**: `diff -q PRD.md PRD_FINALIZED.md` reports the files differ (the cp-then-edit failure mode leaves a byte-identical file, not a truncated one — explicitly checked).
- The arithmetic correction landed: `1,620,000` → **0 occurrences** in PRD_FINALIZED.md (still 2 in PRD.md); `990,000` → **2 occurrences**.
- The settlement field names landed: `prorated_fee_cents`, `withholding_total_cents`, `penalty_total_cents`, `net_payable_cents`, `operating_days` each present exactly once.
- **No post-sweep implementation writes**: `find implementation -name "*.py" -newermt "2026-10-01 08:49:07"` (excluding `__pycache__`) → **0 files**. Step 8 edited only PRD_FINALIZED.md, so the Step 7 clean sweep remains valid.

## Step 9: Complete PRD — 2026-10-01T09:26:00.000Z

Always-run step (no skip condition). Subagent (agentId af4ab9067c50b8925) started from `PRD_FINALIZED.md` and ran a full PRD-vs-`implementation/` scan. Summary, verbatim:

> Done. `/home/ubuntu/github/CodingPRD/tasks/task_3346_municipal_water_utility_operations_maintenance_contract_delivery/workspace/PRD_COMPLETED.md` is written.
>
> ## Sizes
> - `PRD_FINALIZED.md`: 543 lines / 114,763 chars → `PRD_COMPLETED.md`: 549 lines / 127,647 chars (**+6 lines, +12,884 chars**)
> - 71 inline edits: **25 mismatch-revisions, 46 ambiguity-pins**. No new sections; all edits are in-paragraph inserts/revisions. Route table still 140 rows; §5 now 72 rows.
>
> ## Mismatch revisions (PRD described a different behavior)
> - §2.8 — revise — `expected_contract_version` is not "non-optional"; optional + validated-when-present on all three routes that read it — `routes_contracts.py:18-27`, `routes_renewal.py:29-37`
> - §2.8 — revise — "accepting a renewal proposal ... do not take a version input" contradicted §3.8; now names *submitting* a proposal instead — `routes_renewal.py:176`
> - §2.8 — revise — opening line "Two write operations ... both require the client to declare" → three routes, declared version validated when supplied
> - §2.9 — revise — record-level segregation expanded with the two extra same-actor denials (measurement waive after dispute, obligation waive after dispute) — `routes_standards.py:335`, `routes_renewal.py:334`
> - §2.10 — revise — ownership gate runs *after* existence (404 precedes 403), not before — `core.py:592-611`
> - §3.1 — revise — commence fan-out also moves `BASELINE_DISPUTED` assets to `IN_SERVICE` and marks the accepted assessment `baseline_binding` — `routes_contracts.py:195-200`
> - §3.1 — revise — activation's two preconditions can never fail because the definition route already enforces weight/threshold/penalty — `routes_standards.py:86-95`
> - §3.2 — revise — assessments are created directly in `SUBMITTED` (no `DRAFTED`, no submit route) — `routes_assets.py:126-134`
> - §3.2 — revise — dispute is allowed from `REVISED` as well as `SUBMITTED` — `routes_assets.py:269`
> - §3.2 — revise — the `BASELINE_DISPUTED`→`IN_SERVICE` accept move is gated on `is_baseline` — `routes_assets.py:325-329`
> - §3.4 — revise — adjustment accepts `CONTESTED` *or* `ADJUSTED` (PRD self-contradiction) — `routes_permits.py:332-333`
> - §3.4 — revise — allocation `contract_id` comes from the route's permit, not the payload — `routes_permits.py:277-286`
> - §3.4 — revise — measurement waiver needs *any* permit under the contract in `NOTICE_OF_VIOLATION`, not "the owning permit" — `routes_standards.py:340`
> - §3.4 — revise — comparator tie-break was "the `asset_tag` of the violation's asset", which an allocation does not reference; now creation sequence — `calc.py:148-153`
> - §3.4 — revise — review request's `review_outcome` is accepted but never read or stored — `routes_contracts.py:232-249`
> - §3.5 — revise — permit `permit_number` uniqueness is **not** enforced — `routes_permits.py:56-82`
> - §3.5 — revise — suspending a filed renewal changes nothing else (no measurement becomes waivable) — `routes_permits.py:220-223`
> - §3.5 — revise — suspending an `ACTIVE` permit suspends only `ACTIVE` schedules on `TREATMENT_UNIT` assets — `routes_permits.py:213-219`
> - §3.6 — revise — clock-driven states are produced by the evaluation capabilities (no background timer), not "driven by the logical clock rather than by explicit calls" — `routes_pm.py:207-214`, `routes_renewal.py:340-347`
> - §3.8 — revise — `RENEWED` is a resting state; there is no automatic `RENEWED`→`OPERATING`, no `RETIRED`→`DRAFT`, no floor recompute (grep of `RENEWED` found no such transition anywhere in `implementation/`)
> - §3.8 — revise — proposals are created directly in `SUBMITTED`; `DRAFTED` is never produced — `routes_renewal.py:83-90`
> - §3.8 — revise — acceptance: municipally-submitted `SUBMITTED`/`UNDER_REVIEW` proposals may be accepted by either role, and the `COUNTERED` path also requires the contract to be `RENEWAL_PENDING` (PRD said "requires only") — `routes_renewal.py:158-175`
> - §3.9 — revise — begin-hand-back accepts `expected_contract_version` optionally — `routes_contracts.py:328`
> - §3.9 — revise — satisfying from `PENDING`/`IN_PROGRESS` is open to either role, not the operator alone — `routes_renewal.py:287-288`
> - §5 — revise — catalogue claimed "every error identifier"; added `ERR_INVALID_PAGINATION`/`ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` — `core.py:431,621,626,636`
>
> ## Ambiguity pins (PRD silent; impl now pinned)
> §2.1 ownership-gate error `ERR_CROSS_TENANT_DENIED` + role scope — `core.py:576-589` · §2.3 `ERR_INVALID_PAGINATION` and negative-offset rule — `core.py:423-435` · §2.5 clock response `current_utc` — `routes_misc.py:5-9` · §2.8 tracked fields += `baseline_asset_count`, `contract_end_date` — `core.py:322-341` · §2.10 self-service check placement, catch-all `ERR_INVALID_DATE_WINDOW` for unnamed payload failures, accepted instant formats — `core.py:239-244,402-409` · §3.1 `award_date` defaults to start; `benchmark_index_baseline` seeds the *municipality* — `routes_contracts.py:90,114-115`; mobilize/commence error ids — `routes_contracts.py:150-157,187-193` · §3.2 band cut points 80/60/40/20 at 1 dp, score clamped 0–100 and stored at 4 dp — `calc.py:10-31`, `services.py:151-158`; `JOINT` = operator branch, municipality-without-operator-baseline stays `REGISTERED` — `routes_assets.py:136-142`; dispute `dispute_basis` + asset from-state set — `routes_assets.py:266-282`; clear-flag → `IN_SERVICE`, complete-replacement → `REPLACED` — `routes_assets.py:174,192` · §3.3 duplicate `role_code` error id — `routes_staffing.py:83-85`; separation measures *filled* FTE vs suspension measures *committed* FTE — `routes_staffing.py:33-59`; separation demotes only from `BINDING` — `services.py:107-116`; induction reinstate check is contract-wide — `routes_staffing.py:344-349` · §3.4 fixed 30-day reporting frequency (not read from any permit) — `routes_standards.py:16,226-228`; "latest measurement" = greatest `period_end` — `services.py:73-78`; breach share total = the standard's `breach_penalty_cents`, count taken after entering `BREACHED` — `services.py:35-40,62-64`; review tolerance = `annual_fee_cents`, auto-measurement shape — `routes_contracts.py:266,271-285`; allocation create/adjust/void maintain the municipality's penalty total, floored at zero, plus settle error ids — `routes_permits.py:31-38,380-387`; threshold-0 breach score guard — `calc.py:70-73` · §3.5 notice-of-violation requires permit `ACTIVE` and picks the first qualifying allocation — `routes_permits.py:145-158`; file-renewal guard is `now >= expiration-180` with no upper bound — `routes_permits.py:184` · §3.6 flagging work order estimate 2,500,000, PM-DUE work order 250,000 — `services.py:169,219`; 30-day horizon formula and occupation windows — `routes_pm.py:19-48,85-91`; post-commence schedules stay `DRAFT` — `services.py:237-250`; regenerate anchors on current `next_due_at` + re-checks overlap; DUE branch needs the regeneration itself inside the window; suspend `reason` optional — `routes_pm.py:122-140,147`; one missed occurrence per call, asset flagged only from `IN_SERVICE` — `services.py:254-267`; `documentation_complete` needs all three closure inputs — `routes_workorders.py:218-225`; 60% capital test anchored at Jan 1 of `install_year` — `routes_workorders.py:159-164`; await-parts is unreachable — `routes_workorders.py:204-205` · §3.7 critical containment window = the event's `notify_deadline_at`, inclusive — `routes_emergency.py:109-112`; filing at the deadline accepted-and-late, only strictly-after rejected — `routes_emergency.py:157-159`; applicable response-time standard = lowest ACTIVE threshold — `calc.py:380-389`; late-notification permit = first ACTIVE — `routes_emergency.py:166-169`; acknowledgements = distinct operator actions, internal — `services.py:386-397`; escalation allocation shape (0 totals, `violation_code` = event type, no ACTIVE permit → none created but version still bumps) and close error id — `routes_emergency.py:211-224,244`; re-staffing marker is internal — `routes_emergency.py:188` · §3.8 zero-population cost guard — `calc.py:174-179`; renewal entry error ids — `routes_contracts.py:297-307`; `submitted_by` not cross-checked against the acting role, zero ratio base → 0.0 — `routes_renewal.py:70-79`; benchmark read response field names — `routes_contracts.py:119-131` · §3.9 generated obligations (due = start+30d, non-critical, penalty 0) — `routes_contracts.py:329-338`; direct-obligation `is_critical` default and check scope — `routes_renewal.py:246-252`; complete-hand-back checks the negative settlement first — `routes_contracts.py:349-357`; `termination_reason` optional — `routes_contracts.py:377` · §3.10 entities with no dedicated invalid-state error use `ERR_ALREADY_TERMINAL` — `routes_standards.py:123` etc.
>
> ## Dead-code check
> I grepped callsites for **every** top-level `def` across `implementation/*.py` (core, calc, services, all route modules). Route handlers and `@app.errorhandler` functions are reachable via decorators. Genuinely defined-but-never-called:
>
> - `implementation/services.py:131` `guard_emergency_staffing_floor` — dead copy. The PRD-required §3.3 check **is** reachable via `routes_staffing.py:33` `_floor_guard_commitments` (suspend) and `routes_staffing.py:47` `_floor_guard_filled` (separate). Note the dead copy raises at `committed <= floor` while the live guards raise at `< floor`; the PRD now describes the live boundary.
> - `implementation/services.py:408` `lapse_open_proposals` — dead copy; the §3.8 auto-lapse is implemented inline at `routes_renewal.py:178-180`.
> - `implementation/services.py:209` `live_schedule_statuses`, `:417` `contract_or_404`, `:421` `municipality_of`, `implementation/calc.py:392` `contract_of`, `implementation/core.py:251` `dt_of` — dead utilities with no PRD rule attached.
>
> **No PRD-required check ships as dead code**, so no PRD sentence needs a warning to a fresh implementer on that account.
>
> Two adjacent findings worth recording (checks that are wired but unsatisfiable — I did not "fix" the implementation, and only pinned the one that would otherwise mislead):
> - `ERR_OVERFLOW_CONTAINMENT_REQUIRED` (`routes_emergency.py:132`) and `ERR_CONTAMINATION_CONTAINMENT_REQUIRED` (`routes_emergency.py:151`) can never fire: restore/notify are only reachable from `CONTAINED`, which always sets `_contained_at`. The PRD's §3.7 sentences describe them accurately, so a fresh implementer would reproduce the same unreachable wiring — no misleading, left as prose.
> - `await-parts` (`routes_workorders.py:204-205`) is likewise unreachable; since the PRD states it as the precondition of a normal transition, I pinned the unreachability inline in §3.6.

Orchestrator disk verification (independent of the hand-back):
- `PRD_COMPLETED.md` exists at **549 lines / 127,647 bytes** vs `PRD_FINALIZED.md` **543 lines / 114,763 bytes** — matches the hand-back exactly (+6 lines, +12,884 chars).
- **Not a silent no-op**: `diff -q PRD_FINALIZED.md PRD_COMPLETED.md` reports the files differ.
- **No post-sweep implementation writes**: `find implementation -name "*.py" -newermt "2026-10-01 08:49:07"` (excluding `__pycache__`) → **0 files**. Steps 8 and 9 edited PRD documents only, so the Step 7 clean sweep remains valid.
- All 8 `results.{1..8}.json` still present at that point (the results-deletion failure mode did not occur here).

## Final acceptance sweep (orchestrator-run) — 2026-10-01T09:26:00.000Z

Per the "re-run the sweep yourself" rule, the orchestrator — not a subagent — executed the final 8-round parallel sweep against the frozen artifacts, after `rm -f results.*.json` so the evidence is provably this run's:

```bash
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run --start-command "cd .../workspace/implementation && bash start.sh" \
    --test-dir .../test_suite --isolation per-test-server --timeout 120 --test-timeout 30 \
    --results-file .../workspace/implementation/results.${i}.json &
done
wait
```

Result: **8/8 rounds `passed=47 total=47 failed=0` — ALL CLEAN, 0 rounds with failures.** The clean sweep is reproducible by the orchestrator independently of the Step 7 subagent.

## Final state verification — 2026-10-01T09:27:00.000Z

Pipeline complete. Deliverable structure matches the skill's output contract exactly:

```
tasks/task_3346_municipal_water_utility_operations_maintenance_contract_delivery/
├── SCAFFOLD.yaml                          280,703 B
├── SCAFFOLD_DIFFICULTY_DESIGN.yaml         87,368 B   (18 non-stub instances)
├── SCAFFOLD_CORNER_DESIGN.yaml            101,096 B   (31 non-stub + 5 stubs)
├── worklog.md
├── test_helpers/                          9 files, ~2,003 lines
├── test_suite/                           12 files, 2,440 lines, 47 tests
└── workspace/
    ├── INSTRUCTION.md                       1,424 B
    ├── PRD.md                             113,667 B / 543 lines
    ├── PRD_FINALIZED.md                   114,763 B / 543 lines  (Step 8)
    ├── PRD_COMPLETED.md                   127,647 B / 549 lines  (Step 9)
    └── implementation/                    16 files, 4,494 lines + results.{1..8}.json
```

Final checks (all orchestrator-run, all green):
- **Source frozen since the acceptance sweep**: newest source mtime across `implementation/`, `test_suite/`, `test_helpers/` is **08:47:28**; the acceptance sweep's results are stamped **09:24**. Zero source files newer than the sweep. The only post-sweep filesystem action was deleting the stray `implementation/__pycache__` that the orchestrator's own route-import created — bytecode cache, not source; a fresh boot was re-verified afterwards and still serves the PRD envelope.
- **8/8 rounds `passed=47 total=47 failed=0`**, re-checked programmatically after all cleanup.
- **140/140 endpoints registered**, matching SCAFFOLD.yaml exactly on method+path after parameter-name-preserving normalization.
- **In-memory storage only** — no SQLite, no JSON dump, no `/tmp` cache; a second process boots to the default logical clock `2026-09-01T00:00:00Z` with empty state.
- **No seeded entity data** at startup.

Known residual issues carried in the record (none block the benchmark):
1. **Doc-generator Zero-Silence Rule violation** (from Step 7): PRD §3.9's settlement arithmetic named its four output fields only in prose, never as backticked tokens, so the exact serialized key names were not uniquely derivable. One test was deleted on COMPUTED-FIELD SILENCE; Step 8 pinned the names in `PRD_FINALIZED.md`.
2. **PRD internal arithmetic error** (found at Step 6, corrected at Step 8): §3.4's penalty-allocation illustration asserted 720,000 + 270,000 = 1,620,000; the PRD's own formula yields 990,000. Both PRD.md and SCAFFOLD.yaml repeat the bad total. The implementation follows the formula; `PRD_FINALIZED.md`/`PRD_COMPLETED.md` carry the corrected figure. No test asserted the erroneous value.
3. **Index-vs-PRD drift** (from Step 5): three design-index instances were skipped rather than weakened because their literals contradicted the PRD (an unreachable renewal counter-cycle, an unreachable PM-overdue regeneration, and condition-band boundaries the PRD never values). Several further index literals were corrected to follow the PRD. These are unit-test-generator feedback items, consistent with the known pattern that a design index can silently contradict PRD+SCAFFOLD.
4. **Wired-but-unreachable guards** (from Step 9's dead-code sweep): `ERR_OVERFLOW_CONTAINMENT_REQUIRED`, `ERR_CONTAMINATION_CONTAINMENT_REQUIRED`, and the `await-parts` transition cannot fire given the reachable state graph. No PRD-required check ships as dead code; the PRD describes these accurately, so a fresh implementer reproduces the same wiring.
5. **Named-but-unvalued PRD constants** (18 flagged by the Step 6 implementer) — all pinned inline in `PRD_COMPLETED.md` so PRD and implementation now agree. The most consequential: condition-band cut points (80/60/40/20), the 30-day permit reporting frequency, the critical containment window, the review tolerance, the ownership-gate error id (`ERR_CROSS_TENANT_DENIED`), and the auto-created work-order cost estimates (2,500,000 / 250,000 cents).
