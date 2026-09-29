# Worklog — task_2875_non_qualified_mortgage_alternative_documentation_underwriting

## Step 1: Create task directory — 2026-09-05T10:10:36.229Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2875_non_qualified_mortgage_alternative_documentation_underwriting/` and its `workspace/` subdirectory. Index 2875 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-05T12:24:00.000Z

Subagent summary (verbatim):

Scaffold generation is complete. All three artifacts are written, parse as valid YAML, and the lint is clean.

## Files (absolute paths, byte size / line count)

| File | Bytes | Lines |
|---|---|---|
| SCAFFOLD.yaml | 160,211 | 2,996 |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 119,238 | 1,574 |
| SCAFFOLD_CORNER_DESIGN.yaml | 388,701 | 7,139 |

`ls -la` of the task dir also shows `worklog.md` (439 B, orchestrator-owned — untouched) and `workspace/scratch_step2/` (Decimal literal generators plus the audit script; no strays elsewhere).

## SCAFFOLD.yaml (§1.0–§1.7)
- `api_prefix: "/"`, scenario stored **verbatim** (including the leading "Generate task harder than expert level!" line — the orchestrator strips it downstream).
- `complexity_profile`: archetypes compliance_audit / multi_party_negotiation, `difficulty_level: expert_plus`, layers = dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, version_pinning_on_approval, optimistic_concurrency; topology flat, shape branching, role_model segregation_of_duties, consistency immediate.
- **14 entities**, **9 state machines** (incl. `AppraisalReview` parallel dimensions, `ExceptionRequest` tier-2 fork/join, `PostCloseAudit` compound, `SecuritizationPool` cyclic), **2 §1.2.1 OCC rules**, **14 calculations** (one per algorithm family: waterfall, chronological, tiered_pricing, interval_merge, 2x weighted_scoring, 2x constraint_propagation, 2x threshold, 3x aggregation), **43 ordered validations (1..43, contiguous)**, **54 endpoints**, **55 error codes**, **8 roles**.

## §1.8 — 9 rules x 2 instances = 18
dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.

## §1.9 — 9 sections, 82 instances
entities 13, state_machines 16, calculations 18, validations 9, endpoints 6, errors 9, rbac 3, cross_cutting_complexity_layers 6, consistency_model 2. Sixty-six carry full recipes; 16 are `excluded_because` stubs pointing at a named §1.8 instance.

## Verification
- `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (§1.5 endpoints 54, §1.1 entities 14, §1.8 instances 18, §1.9 instances 66, calls scanned 1,073).
- Independent audit script: 0 unresolved `${placeholders}`, 0 duplicate instance names across both design files, 100 instances total, **all 54 endpoints actually called**, **all 55 error codes triggered** by some instance; the only two "invalid enum" literals left are the deliberate `BANK_STATEMENT_18MO` / `PRIMARY_RESIDENCE` rejection probes.

## Ambiguities found and closed in SCAFFOLD.yaml while writing §1.9
1. Added validations 39/40/41 (`ERR_FICO_BELOW_PROGRAM_MIN`, `ERR_LTV_ABOVE_PROGRAM_MAX`, `ERR_DSCR_BELOW_PROGRAM_MIN`) — the program floors had no enforcing rule; old 39/40 renumbered to 42/43.
2. Deleted the untriggerable `ERR_CREDIT_EVENT_NOT_FOUND` (no endpoint accepts a credit-event id).
3. Fee test now explicitly invalidates `safe_harbor_class`; `removal_reason` enum and "settlement requires an empty pool" made explicit.
4. Validation 15 contradicted the `AuditFinding` machine (adjudicate is legal from ISSUED) — reworded, with `RETURN_FOR_MORE_INFO` requiring REBUTTED.
5. Rebut's "acting user must be the assigned underwriter" precondition conflicted with LoanOfficer holding the shared op — replaced with a role-based precondition.
6. `POST /points-and-fees-items` and `.../void` now declare the ATR invalidation on a result flip, matching the test endpoint.
7. The SECOND_APPRAISAL order transition's single `actor: Underwriter` relaxed to the endpoint's declared role set.

**Orchestrator post-step action**: the line "Generate task harder than expert level!" was present in SCAFFOLD.yaml's `scenario:` block scalar (line 2). Per the difficulty-directive containment rule it was stripped in place so it cannot reach PRD.md via the doc generator, which reads SCAFFOLD.yaml. SCAFFOLD.yaml re-validated as YAML afterwards (13 top-level keys intact); the scenario text itself is otherwise verbatim.

## Step 3: Copy shared files — 2026-09-05T12:25:08.902Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` (1424 B) to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-05T12:44:00.000Z

Subagent summary (verbatim):

PRD generation complete.

**Output**: `workspace/PRD.md` — 443 lines, 105,683 bytes, built with 11 chunked `cat >>` appends plus one `Edit` fix.

**Structure** (verified ends at a real section boundary — the last row of the §5 table, no truncation, no audit footer):
§1 Introduction · §2.1–2.10 Global Specs (RBAC, verbatim response envelope, pagination, identity/versioning, rounding, logical clock, OCC, the 43-item rule-evaluation ladder, cascade chains, read/reverse-reachability) · §3.1–3.9 Business Logic · §4 Endpoint Definitions (54 rows, 4 columns) · §5 Error Code Catalogue (55 rows, 2 columns).

**Hard Contract 1 — Field-Name Coverage: PASS.** 165/165 required identifiers (153 entity field names ∪ 108 endpoint input identifiers, deduped) appear in backticks. One gap was caught and fixed mid-verification: `worksheet_id` was missing and is now stated in §3.4 as the statement month's parent link.

**Hard Contract 2 — Rule Coverage: PASS** (8 lines):
1. Validations: 43/43 priorities enumerated in §2.8 with their exact `applies_to` endpoint scope, then re-stated in the §3 narrative in ladder order.
2. Concurrency: 2/2 OCC rules — `expected_loan_file_version`/`ERR_STALE_LOAN_FILE_VERSION` and `expected_pool_version`/`ERR_STALE_POOL_VERSION` (both pool write endpoints), with the "no other endpoint takes a version field" closure.
3. State transitions: all 9 machines; every `from`/`to` state and all 120 declared enum members are present (`REJECTED` appears inside the `RECEIVED → REJECTED` transition token).
4. Calculations: 14/14 — pitia_monthly, bank_statement_income, asset_depletion_income, profit_and_loss_income, dscr_ratio, points_and_fees_test, credit_event_seasoning, overlay_breach_evaluation, appraisal_reconciliation, ltv_recompute, atr_determination, audit_grade, pool_metrics_recompute, securitization_eligibility — each with constants, rounding site and boundary inclusivity.
5. Validation conditions: every `check` string rendered as prose, including boundary direction (inclusive FICO/reserves/LTV/pool cap, strict variance and points-and-fees FAIL).
6. Endpoint side_effects / applies_to: all 54 endpoints' effects appear in §3 or §4; the `_clock` endpoint's "recomputes nothing" is stated.
7. Entity field structured content: all 14 entities, including CreditEvent's absence of `updated_at`/`version` and every computed default.
8. Sibling-branch symmetry: equal density for INTEREST_ONLY vs FULLY_AMORTIZING, the four income methodologies, tier-1 vs tier-2 exception paths, the two AppraisalReview dimensions, and the business-purpose vs consumer-purpose ATR branches.

**Hard Contract 3 — §3 Path Purity: PASS.** 1,097 backticked tokens in §3, zero starting with `/`, zero bare HTTP methods anywhere in §3 prose, zero method+path pairs. Paths/methods are used only in §2.7/§2.8 (to pin `applies_to` scopes) and §4.

**Other checks**: §2.2 byte-identical to the skill's source file; zero occurrences of difficulty/benchmark/scaffold meta-commentary; the two withheld design YAMLs were never opened; scratch confined to `workspace/scratch_step4/`.

**Ambiguities resolved additively** (worth flagging to the implementer/test author): priority 28's statement-month `applies_to` has no code of its own (stated as never raising); the submit-to-underwriting "at least one ACTIVE fee item" precondition has no dedicated code (mapped to `ERR_LOAN_FILE_STATE_INVALID`); the pool `investor_code` equality rule has no dedicated code (mapped to `ERR_LOAN_NOT_SECURITIZATION_ELIGIBLE`); approve-time `unresolved_overlay_breach_count == 0` and close-time `securitization_eligible == true` are stated as preconditions without inventing codes.

**Orchestrator truncation check** (the known doc-generator failure mode): `tail -12 workspace/PRD.md` ends on `| ERR_POOL_BALANCE_CAP_EXCEEDED | 422 |` — a complete final table row at a real section boundary, not mid-sentence. Section header scan confirms all of §1, §2.1–2.10, §3.1–3.9, §4, §5 present. Independent grep for "harder than expert", "expert level", "scaffold", "benchmark" over PRD.md returned zero hits, so the difficulty directive did not leak. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-05T14:39:00.000Z

Subagent summary (verbatim):

Step 5 is complete. Both output trees sit at the task root, `test_helpers/` and `test_suite/` (verified by `ls -la`); nothing was written under `workspace/` except the task-scoped `workspace/scratch_step5/` (only `check_quotes.py` and two generated name indices). `workspace/implementation/` was never read or touched, `worklog.md` was never touched, and no `pkill` was ever run.

## Files

`test_helpers/` (8534 lines total across both dirs)
- `__init__.py` 97, `api_client.py` 276, `api_errors.py` 181, `assertions.py` 157, `constants.py` 140, `factories.py` 315, `fixtures.py` 340, `test_users.py` 110, `types.py` 28

`test_suite/`
- `conftest.py` 12
- `test_01_dual_variant_income.py` 252 (5 tests), `test_02_points_and_fees_and_rounding_order.py` 208 (4), `test_03_fork_join_and_parallel_dimensions.py` 199 (4), `test_04_transitive_cascades.py` 288 (4), `test_05_priority_pair_conflicts.py` 271 (4), `test_06_boundary_precision.py` 225 (4), `test_07_cross_entity_state_gates.py` 238 (4), `test_08_temporal_overlap.py` 304 (4), `test_09_compensating_invariants.py` 307 (4)
- `test_10_entities.py` 506 (13), `test_11_state_machines.py` 601 (11), `test_12_calculations.py` 845 (13), `test_13_validations.py` 586 (7), `test_14_endpoints.py` 524 (6), `test_15_errors.py` 782 (9), `test_16_rbac.py` 271 (3), `test_17_cross_cutting.py` 225 (2), `test_18_consistency.py` 246 (2)

## Coverage

- **103 tests total.** Queue A (Difficulty): 37 tests covering all 18 non-stub instances across the 9 rule_ids (no stubs exist in that index). Queue B (Corner): 66 tests, exactly one per non-stub instance — entities 13, state_machines 11, calculations 13, validations 7, endpoints 6, errors 9, rbac 3, cross_cutting_complexity_layers 2, consistency_model 2.
- **Skips: zero non-stub instances skipped.** Every non-stub instance in both indices is translated. The 16 `excluded_because:` stubs were deliberately not translated, as required: state_machines (`corner_appraisal_review_parallel_dimensions`, `corner_exception_request_fork_and_join`, `corner_audit_defect_cascade_down_to_pool`, `corner_pool_removal_compensates_every_metric`, `corner_approval_guarded_by_appraisal_review_state`), calculations (`corner_pool_metric_aggregation_after_add_and_reversal`, `corner_points_and_fees_cap_tier_boundary`, `corner_appraisal_variance_tolerance_boundary`, `corner_expense_factor_variant_divergence`, `corner_bank_statement_per_month_rounding_order`), validations (`corner_priority_conflict_state_versus_ceiling`, `corner_cross_entity_validation_appraisal_review_gate`), cross_cutting (`corner_cascading_side_effects_four_level_chain`, `corner_dual_variant_calculation_expense_factor_and_rent`, `corner_rate_threshold_triggers_hpml_and_hoepa_boundaries`, `corner_version_pinning_on_approval_voids_stale_waiver`).

## Verification run at the end

- Design tags: an AST pass over all 18 files confirms **every one of the 103 tests carries exactly one final `Design:` line**, each resolving to a real, non-stub instance name in the source yaml; 0 untagged, 0 dual-tagged, 0 stub-tagged, 0 unknown.
- Citation check: `python3 workspace/scratch_step5/check_quotes.py test_suite/*.py` -> `checked files: 19 missing fragments: 0` (every `"..."` docstring fragment appears verbatim in PRD.md).
- `python3 -m py_compile` clean on all 27 modules (no truncation), and all 18 test modules import cleanly against `test_helpers` and `prd_bench_local_runner.testing`; per-file AST checks report no unused imports, no undefined `ERR_*` names, and no `fx.`/`A.`/`F.`/`api.` attribute that does not exist in the helpers. `__pycache__` dirs removed.

## Deviations worth flagging to Step 7

Three design-asserted values were dropped because the PRD does not uniquely derive them (the tests still distinguish the intended behaviour): the loan-file `approval_note` field (PRD names it only as an approve input), the clock response's `current_utc` echo (PRD declares no clock response body), and `securitization_eligible == true` in test_15's pool-removal case (replaced by `status == "CLOSED"` plus a null `pool_id`). Also note `ERR_FINDING_STATE_INVALID` is HTTP 409 per PRD line 418 even though one design recipe claims 422 — harmless, since `validate_error` reads the registered `ERROR_HTTP_STATUS` map rather than a per-call status.

**Orchestrator verification**: `ls -d test_helpers test_suite` confirms both trees are at the task root, NOT under `workspace/` (a known Step 5 failure mode). `grep -rh "^def test_" test_suite/*.py | wc -l` = 103, matching the reported count.

## Step 6: Generate implementation — 2026-09-05T14:39:00.000Z

Subagent summary (verbatim):

Implementation complete. All files live in `workspace/implementation/`.

## Files (line counts)

| file | lines | contents |
|---|---|---|
| `app.py` | 58 | Flask app factory, 9 blueprints, `strict_slashes=False`, `ApiError`/`HTTPException`/catch-all envelope handlers, `0.0.0.0:$PORT` |
| `core.py` | 410 | error catalogue + HTTP statuses, envelope/meta emission, ISO instants, Decimal helpers (`ROUND_HALF_UP`), auth (8 roles), pagination, body validation |
| `store.py` | 145 | in-memory dict store (no seeding), `Tx` (one version bump per resource per request), FK existence resolution |
| `services.py` | 761 | all 14 calculations, cascade chains, overlay sweep, eligibility conjunction, pool metrics, audit regrade |
| `routes_config.py` | 196 | programs, overlays, `_clock/set_current_utc` |
| `routes_borrower.py` | 106 | borrowers, credit events (+ seasoning recompute cascade) |
| `routes_loanfile.py` | 460 | loan files, reads, all 9 lifecycle actions, approval gate ladder |
| `routes_worksheet.py` | 294 | worksheets, statement months, calculate/accept/exclude |
| `routes_valuation.py` | 184 | orders, receive/decision, appraisal reviews, override-escalation |
| `routes_fees.py` | 96 | points-and-fees items + void |
| `routes_exception.py` | 155 | exception requests, tier-1/tier-2 fork-join decisions |
| `routes_audit.py` | 172 | post-close audits, findings, rebut, adjudicate |
| `routes_pool.py` | 149 | pools, assignment, removal/settlement |
| `start.sh` | 8 | `$PORT`, foreground `exec python3 app.py`, conditional pip install |
| `requirements.txt` | 1 | `flask>=3.0.0` |

Every module passes `python3 -m py_compile` (no truncation); all writes were chunked `cat`/Edit calls.

## Coverage

- **54/54 endpoints** — `url_map` dump matches the 54 method+path pairs in SCAFFOLD.yaml exactly.
- **43/43 validations** in priority order (auth 1-4, existence 5, shape 6, range 7, both OCC rules 8-9, nine state machines 10-16, business 17-43); ladder placements chosen where the PRD leaves the error implicit (e.g. valuation receive/decision loan-file precondition -> `ERR_VALUATION_ORDER_STATE_INVALID`, audit-finding loan-file state -> `ERR_FINDING_STATE_INVALID`, per §5's per-error endpoint lists).
- **14/14 calculations**, **9/9 state machines**, both optimistic-concurrency rules, RBAC for all 8 roles.
- In-memory dicts only, zero seeded data — a fresh boot returns `total_count: 0` for every collection (verified).

## Smoke tests (3 scripted passes, curl-equivalent HTTP, ports 28751/28752, killed by port-specific PID)

Pass 1 (bank-statement happy path): program -> borrower -> loan file (`pitia 352871`, `ltv 80`) -> doc-type -> fee item -> submit -> worksheet -> 12 statement months -> calculate (`PROGRAM_DEFAULT_FACTOR`, income 1,950,000) -> accept (`dti 25.79`, reserves 25.51) -> valuation order/receive/accept -> points-and-fees `PASS` -> ATR `DOCUMENTED` -> approve -> close -> pool assign (`wac 6.875/7.25`, cap check) -> removal -> settlement -> audit + finding + rebut + waive (grade `C_MATERIAL` -> `A_CLEAN`). Error paths confirmed: `ERR_UNKNOWN_ROLE`, `ERR_MISSING_USER_HEADER`, `ERR_LOAN_FILE_NOT_FOUND`, `ERR_UNAUTHORIZED`, `ERR_VALUE_OUT_OF_RANGE`, `ERR_INVALID_REQUEST`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_DUPLICATE_CODE`, `ERR_STALE_LOAN_FILE_VERSION`, `ERR_STALE_POOL_VERSION`, `ERR_LOAN_ALREADY_POOLED`, `ERR_POOL_STATE_INVALID`, `ERR_FINDING_STATE_INVALID`.

Pass 2 (asset depletion + exceptions): overlay `MIN_FICO GTE 780` tier 2 breached at submit -> exception pinned at 700 -> CCO-first refused (`ERR_EXCEPTION_AUTHORITY_INSUFFICIENT`) -> committee fork -> committee second signature refused -> CCO join -> `investor_notification_required` true, unresolved breach 0 -> approve/close -> pool assign -> MATERIAL finding upheld -> audit `MATERIAL_DEFECT` -> repurchase cascade (`AUDIT_DEFECT`, `repurchase_flag`, `pool_id` null) and pool `OPEN -> REBALANCING` with version bump.

Pass 3 (DSCR + appraisal variance + exclusions): `dscr_ratio 1.1072` (`LEASE_IN_PLACE`), second valuation required at LTV 80 > 70, variance 19.05% -> `PRIMARY_ESCALATED`/`SECOND_RECONCILED`, reconciled to the lower value -> LTV 95.24, ATR `EXEMPT`/`EXEMPT_BUSINESS_PURPOSE`, approve blocked by escalation then by LTV, override-escalation clears then rejects a second override; CPA-letter variant, overlap/window/exclusion/insufficient-month errors all correct.

Two spec-fidelity fixes made during the smoke: decimal-scaled (`num`) fields now also accept exact decimal strings (integers stay strict), and the CPA expense-factor domain/program-floor checks (both `ERR_INVALID_REQUEST`, priority 6) now precede the priority-8 concurrency check on `POST /income-worksheets`.

Both smoke servers are shut down (ports 28751/28752 free), `__pycache__` removed, no broad `pkill` used, `worklog.md` and the test directories untouched. Scratch artifacts are under `workspace/scratch_step6/` (`smoke.py`, `smoke2.py`, `smoke3.py`, run logs).

**Orchestrator note**: Steps 5 and 6 were launched concurrently in a single message, so the implementation generator's process began before `test_suite/` existed on disk — physical isolation from the tests, not just an instruction. Orchestrator also pre-wrote `workspace/sweep.sh` (syntax-checked with `bash -n`) so Step 7 launches the 8-round sweep from a script file rather than an inline one-liner whose nested quoting has corrupted `--start-command` in past runs.

## Step 7: Run tests and iterate — 2026-09-05T15:02:00.000Z

Subagent summary (verbatim):

All 8 rounds pass 103/103. Iteration 2 was clean.

**Iterations run:** 2 (iteration 1: 94/103 in all 8 rounds, 9 deterministic failures, no flakiness; iteration 2: 103/103 in all 8 rounds)

**Tests deleted:** none. One assertion was removed under STEP 1c (partial coverage):
- `test_suite/test_15_errors.py::test_each_child_entity_owns_its_own_wrong_state_code` — dropped `included_month_count: 1` on a never-calculated DRAFT worksheet (COMPUTED-FIELD SILENCE: PRD 3.4 writes `included_month_count` only in step one of the bank-statement *calculation*, and states "Attaching a month never recalculates the worksheet", so a PRD-only implementer may legitimately leave it at 0 and a "decrement by one" from 0 is not pinned). The `status: DRAFT` assertion and all four error-code assertions were kept.

**Fixes applied to `test_helpers/`:** none — the whole helper layer was audited against the five known fixture-bug shapes (money-as-string, date-only literals, sub-second precision, envelope double-unwrap, whitespace blank headers) and is clean.

**Fixes applied to `test_suite/`:**
- `test_04_transitive_cascades.py::test_upholding_the_last_open_finding_defects_the_closed_loan_file` — `before` snapshot expected `securitization_eligible: True` while the audit already graded `C_MATERIAL`; PRD 3.9 recomputes eligibility "on every audit grade change" and forbids any audit row grading `C_MATERIAL`, so the correct pre-adjudication value is `False`.
- `test_05_priority_pair_conflicts.py::test_voiding_the_high_cost_charge_lets_the_already_pooled_error_surface` — added the missing ATR re-determination after the void: PRD 3.6 invalidates the determination whenever a fee write flips the verdict, so without it the assignment is refused at priority 19 and `ERR_LOAN_ALREADY_POOLED` (priority 33) is unreachable.
- `test_13_validations.py::test_the_pool_balance_cap_is_an_inclusive_aggregate_ceiling` — the third (exact-cap) assignment of `file_b` ran before the refusal-invariance block, so `assert_is_null(..., "pool_id")` observed the later success; moved the assignment after that block.
- `test_16_rbac.py::test_seven_roles_read_the_same_file_and_the_program_admin_cannot` — expected `dscr_ratio == 1.2367` on a DRAFT file with `doc_type` null; PRD 3.3 says the ratio "stays null on any file whose `doc_type` is not `DSCR`", so this is now `assert_is_null`.

**Fixes applied to `implementation/`:**
- `routes_fees.py`, `create_fee_item` / `void_fee_item` — dropped `tx.watch(loan_file)`; PRD 2.4 names exactly two cross-resource loan-file `version` bumps (worksheet open, worksheet accept), so a fee write recomputes steps 1–3 without moving the file's version.
- `routes_loanfile.py`, `create_loan_file` — `recompute_ltv` -> `compute_ltv_only`; PRD 3.3 opens a file with `second_valuation_required` false and PRD 3.5 re-tests only at submission and on a later `ltv_pct` recomputation.
- `routes_loanfile.py`, `submit_to_underwriting` — the seasoning recompute now runs inside the handler and writes to the file before the priority-20 gate answers (PRD 3.3 lists it as an act of submission; PRD 3.2 defines the computation as storing `governing_credit_event_id`, `seasoning_months_required`, `seasoning_months_elapsed`), so a refused submission leaves the recomputed fields behind. Version/`updated_at` are untouched on the refusal path since the tx never commits.

**Final sweep evidence:** round 1 103/103 · round 2 103/103 · round 3 103/103 · round 4 103/103 · round 5 103/103 · round 6 103/103 · round 7 103/103 · round 8 103/103 (0 failed, 0 errors, 0 skipped in every round).

**Orchestrator verification**: independently re-read all 8 `workspace/implementation/results.$i.json` — 8 files present, each `passed: 103, failed: 0, total: 103, errors: 0, skipped: 0`. The clean sweep is real, not a subagent claim without artifacts. Step 7 applied 3 `implementation/` fixes, so the Step 8 skip condition does not apply and Step 8 runs.

## Step 8: Finalize PRD — 2026-09-05T15:12:00.000Z

Subagent summary (verbatim):

Done. `PRD_FINALIZED.md` written with four minimal edits; file verified intact (443 lines, still ends with the `| ERR_POOL_BALANCE_CAP_EXCEEDED | 422 |` catalogue row).

## Line counts
- `PRD.md`: 443 lines / 105,683 bytes
- `PRD_FINALIZED.md`: 443 lines / 107,317 bytes
- Line delta: 0 (0.0%); byte delta +1,634 (+1.55%) — all four edits are inline inside existing paragraphs, no new sections.

## Changes
- **3.2 (seasoning) — insert** — the submission-time seasoning recompute is stored *before* the priority-20 refusal, so a refused `submit-to-underwriting` leaves the recomputed `governing_credit_event_id` / `seasoning_months_required` / `seasoning_months_elapsed` / `seasoning_satisfied` behind with `status`/`updated_at`/`version` untouched; the approval gate instead evaluates without storing and writes only on success — `routes_loanfile.py:243-246` (submit) and `routes_loanfile.py:64-75, 414` (probe + success-path store).
- **3.4 (statement-month exclusion) — revise** — exclusion writes nothing to the worksheet on a `DRAFT` worksheet (so `included_month_count` / `eligible_deposit_total_cents` stay at 0, no `version` bump); on a `CALCULATED` worksheet the calculation re-runs and rewrites `included_month_count`, `eligible_deposit_total_cents`, `net_deposit_total_cents`, `gross_monthly_income_cents`, `monthly_qualifying_income_cents`, leaving `calculation_count` unchanged — `routes_worksheet.py:233-241` with `services.py:482-555` (`count=False`).
- **3.5 (second-valuation retest) — revise** — the retest fires at submission and when a `reconciled_value_cents` change recomputes `ltv_pct`; file creation computes `ltv_pct` without the retest, so a new file always opens `second_valuation_required` false — `routes_loanfile.py:159-163` (`compute_ltv_only`), `services.py:186-215`, `services.py:591-596`.
- **3.6 (fee writes) — insert** — adding or voiding a charge rewrites the file's fee aggregates (and any ATR/eligibility fields touched) in place without refreshing the loan file's `updated_at` or incrementing its `version` — `routes_fees.py:48-66, 90-99` (no `tx.watch(loan_file)`), `store.py:106-130`.

## Per-edit pre-edit search log
1. **3.2 edit** — (a) subject: where seasoning fields are computed and whether the write persists across a refusal. (b) grepped `compute_seasoning|seasoning_probe|seasoning_satisfied` across `implementation/`; read `routes_loanfile.py` submit (243), `gate_seasoning`/`seasoning_probe` (64-75, dict copy -> no persistence), approve success (414), `clear_conditions` -> `overlay_sweep` -> `compute_seasoning` (`services.py:318`), `routes_borrower.py:87-93` (credit event, watched + committed), `store.py` `Tx.commit` (bump only on real field change). (c) scoped the persistence claim to *submission only* and added the explicit contrasting approval clause, because the approval gate provably does **not** store (probe on a copy) — an unscoped "seasoning refusals persist the recompute" would have mis-described `approve`.
2. **3.4 edit** — (a) subject: every writer of the worksheet's derived aggregates (`included_month_count`, `eligible_deposit_total_cents`, `calculation_count`). (b) read `routes_worksheet.py` `attach_statement_month` (no `Tx`, no worksheet write), `exclude_statement_month` (recalc only when `CALCULATED`, `count=False`), `calculate`, `accept` (`included_month_count` read by the priority-29 gate), `services.calculate_worksheet` (all four method branches, incl. the non-bank-statement zeroing path since `attach` never checks method); grepped `included_month_count`/`calculation_count` in `test_suite/` to confirm no round asserts an exclusion-driven `calculation_count` bump. (c) wrote "the calculation is re-run" rather than "the bank-statement calculation is re-run" (widening, so the method-generic zeroing branch is not mis-described), and dropped the PRD's original "incrementing `calculation_count` by one" which contradicts `count=False`.
3. **3.5 edit** — (a) subject: every write of `ltv_pct` and of `second_valuation_required`. (b) grepped `compute_ltv_only|recompute_ltv|retest_second_valuation|second_valuation_required` — exactly three `ltv_pct` writers (create: no retest; submit: retest immediately after; `accept_valuation` -> `recompute_ltv` only when `reconciled_value_cents` moved) and one `second_valuation_required` writer (`retest_second_valuation`, also flipping the review row `SECOND_NOT_REQUIRED -> SECOND_REQUIRED`); also checked `ensure_review` which *reads* the flag when minting the review row. (c) softened the tail from "until it is submitted for underwriting" to "until one of those two re-tests runs", so the sentence stays true for the reconciliation-driven path as well.
4. **3.6 edit** — (a) subject: which requests move a loan file's `version`/`updated_at` when the request targets another resource. (b) read `store.py` `Tx.watch/bump/commit` (bump requires an explicit watch *and* a real field change), then every cross-resource loan-file mutation: `routes_fees.py` create/void (**not** watched -> never bumps), `routes_worksheet.py` create (`tx.bump`) and accept (`tx.bump`), `routes_borrower.py` credit event (watched), `routes_exception.py` decision (watched), `routes_valuation.py` decision + override-escalation (watched), `routes_pool.py` assign/remove (watched), `routes_audit.py` -> `services.cascade_material_defect`/`cascade_audit_cleared`/`audit_regrade` (watched), plus `routes_loanfile.py`'s own actions incl. `points-and-fees-test` (watched -> does bump). (c) deliberately did **not** write "version moves only on the two worksheet events of §2.4" (false — the file's own lifecycle actions, pool writes, credit events, exception and valuation decisions and audit cascades all bump it); the committed sentence is scoped to the two fee-item endpoints only.

**Orchestrator verification**: `cmp` confirms PRD_FINALIZED.md is NOT byte-identical to PRD.md (443 lines, 107,317 B vs 105,683 B) and still ends on the final error-catalogue row, so the pass genuinely ran and was not truncated.

## Step 9 plan — 2026-09-05T15:13:00.000Z

Step 9 is run as **three sequential, module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` rather than a single subagent. Rationale: the implementation is 15 modules / ~3,200 lines and the PRD is 443 lines / 107 KB; one subagent attempting an exhaustive walk reliably runs out of working context and returns a PRD_COMPLETED.md that is byte-identical to its source, i.e. the scan never actually ran. Partitioning by implementation module keeps each pass's read set small. Pass 1 performs the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 must NOT re-copy (that would discard the previous pass's edits) and instead edit the shared file in place. Orchestrator verifies after each pass that the file grew / changed and still ends at a real section boundary.

## Step 9: Complete PRD — 2026-09-05T15:50:00.000Z

Run as three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`. Pass 1 owned the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 were explicitly forbidden to re-copy and edited in place. Orchestrator verified after each pass that the file had grown, that the previous pass's unique marker strings survived, and that the file still ended on the final error-catalogue row.

Cumulative result: PRD_FINALIZED.md 443 lines / 107,317 B -> PRD_COMPLETED.md **444 lines / 133,898 B** (+1 line, +26,581 B / +24.8%). 69 edits total: 44 ambiguity-pins, 25 mismatch-revisions. No new sections; all changes are inline inserts/revisions plus one added error-catalogue row (`ERR_NOT_FOUND` 404).

### Pass 1 (core.py, store.py, app.py, routes_config.py, routes_borrower.py) — verbatim summary

Setup: `cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` confirmed done. Size: 443 lines / 107,317 chars -> 444 lines / 112,038 chars (+1 line, +4,721 chars). Counts: 13 ambiguity-pins, 2 mismatch-revisions.

- §2.3 Pagination — insert — ambiguity — bad/out-of-bounds `limit`/`offset` report `ERR_INVALID_REQUEST` 400 (not a domain failure), empty-string params take defaults, and same-millisecond `created_at` ties order by insertion sequence — core.py:270-303
- §2.4 ¶1 — insert — ambiguity — new rows have `updated_at == created_at`; `created_at`/`updated_at`/`api_request_timestamp` come from the host wall clock, not the logical clock — store.py:76-85, core.py:89-97
- §2.4 ¶3 — revise — **mismatch** — PRD claimed version increments "each time the resource is mutated"; impl bumps at most once per request, shares one `updated_at` instant across the request, and does not bump at all when no stored value moved unless the bump is declared unconditional (worksheet open/accept, pool membership) — store.py:101-129, routes_worksheet.py:136,287, routes_pool.py:98,141
- §2.5 — insert — ambiguity — decimal fields accept a JSON number *or* a decimal string, finer-scale input is rounded half up to the declared scale rather than refused, and output is a plain JSON number with trailing zeros not preserved (`0.0000` -> `0`) — core.py:332-360, core.py:165-173
- §2.6 — insert — ambiguity — the clock may move backwards, `/_clock/set_current_utc` answers 200 with empty `data`; body instants accept `Z`/numeric offset/bare date (midnight UTC) and are echoed back canonicalised to three fractional digits + `Z` — routes_config.py:191-196, core.py:100-123, core.py:93
- §2.8 ladder item 5 — insert — ambiguity — a body FK present but not a JSON string is a shape error, not a 404 — store.py:132-145
- §2.8 ladder item 6 — insert — ambiguity — JSON `null` counts as absent (required -> missing, optional -> default); an all-optional endpoint accepts no body; any JSON string incl. `""` satisfies a string field; unparseable/non-object body is `ERR_INVALID_REQUEST` — core.py:381-401
- §2.9 ¶1 — revise — **mismatch** — cascade claim "each affected resource has its `version` incremented" narrowed to resources whose stored values actually move, at most once per request — store.py:122-129
- §3.1 ¶2 — insert — ambiguity — a `statement_period_months` value outside the family's allowed 12/24 is `ERR_INVALID_REQUEST`; the expense factors read back as null on `ASSET_DEPLETION`/`DSCR` — routes_config.py:65-81, 133-135
- §3.1 ¶2 — revise — ambiguity — `depletion_horizon_months` / `min_dscr` are *required* for their family — routes_config.py:83-93
- §3.1 ¶4 — insert — ambiguity — domain list extended with `min_fico` 300-850, non-negative `min_reserves_months`/`min_dscr`/seasoning months, strictly-positive `depletion_horizon_months` and `second_valuation_loan_amount_threshold_cents`, non-negative overlay `threshold_value` — routes_config.py:102-124, 164
- §3.1 ¶5 — insert — ambiguity — `required_authority_tier` other than 1 or 2 is `ERR_INVALID_REQUEST` — routes_config.py:162-163
- §3.2 ¶1 — insert — ambiguity — `credit_event_count` counts every event, documented or not — routes_borrower.py:86
- §3.2 ¶2 — insert — ambiguity — future-`completion_date` refusal compares full instants against the clock instant; the cascade covers every loan file whose status is not `DENIED` and also refreshes each file's `securitization_eligible`; an unrecognised `event_type` filter yields an empty page — routes_borrower.py:76, 87-92, 102-104
- §3.2 ¶3 — insert — ambiguity — insertion order settles a seasoning tie surviving deficit / `completion_date` / `created_at` — services.py:238-241

Out-of-scope gaps handed forward: §3.9's eligibility-recompute trigger list under-inclusive; `_closing_date` stripped by `public_view`; `supporting_valuation` heuristic undocumented; `reorder_too_soon` uses `abs()` of the day delta.

### Pass 2 (services.py, routes_loanfile.py, routes_worksheet.py) — verbatim summary

No copy performed; pass 1's 15 edits verified intact. Size: 444 lines / 112,038 B -> 444 lines / 126,172 B. Counts: 14 ambiguity-pins, 17 mismatch-revisions (31 paragraph changes).

- §3.3 — insert — ambiguity — omitted `monthly_hoa_cents` stores 0 and enters PITIA, omitted rents store null — routes_loanfile.py:118-131
- §3.3 — revise — mismatch — payment recomputed at exactly two points (creation, doc-type selection), not "whenever inputs change"; `documented_reserves_months` is 0.00 when PITIA <= 0 — services.py:186-219
- §3.3 — insert — ambiguity — `ltv_pct` null when the basis is not strictly positive — services.py:173-184
- §3.3 — insert — ambiguity — doc-type selection recomputes all three PITIA dependents, no underwriter-binding check — routes_loanfile.py:190-220
- §3.3 — insert — ambiguity — `dscr_ratio` null when PITIA <= 0; the two shape names are not stored; recomputed again on worksheet acceptance — services.py:151-171
- §3.3 — revise — mismatch — submission does five things and does **not** run the points-and-fees test; its sweep carries no suspend cascade — routes_loanfile.py:237-253
- §3.4 — insert — ambiguity — P&L period/program equality checked at calculation, not creation; every worksheet-payload domain violation reports `ERR_INVALID_REQUEST` and sits above the version/state/doc-type/segregation checks — routes_worksheet.py:70-95
- §3.4 — revise — mismatch — month attachment has no underwriter-binding check and no `BANK_STATEMENT` requirement; window compared as calendar dates; null `statement_period_months` means no lookback floor — routes_worksheet.py:162-187, services.py:730-745
- §3.4 — revise — mismatch — `calculate` gates on worksheet status only — routes_worksheet.py:247-260
- §3.4 — revise — mismatch — `exclude` has **no** worksheet-status gate at all, no segregation, no loan-file gate — routes_worksheet.py:216-241
- §3.4 — revise — mismatch — `accept` gates on worksheet status only; month-count test reads stored `included_month_count`; full publish cascade enumerated; its sweep suspends only via a voided exception — routes_worksheet.py:263-294
- §3.5 — insert — ambiguity — re-order buffer picks the latest prior order by creation order, distance is an absolute value between calendar dates, 30 blocks / 31 does not, forward-dated `effective_date` blocks identically — services.py:715-727
- §3.5 — insert — ambiguity — the second-valuation re-test rewrites the flag in both directions but never walks the review dimension backwards — services.py:270-300
- §3.5 — insert — ambiguity — a second appraisal accepted with no primary value is `ERR_VALUATION_ORDER_STATE_INVALID`; `variance_pct` is 0.00 when the low value is 0 — services.py:570-581
- §3.5 — revise — mismatch — suspension on acceptance: non-null -> different-non-null value move suspends outright, first reconciliation only via breach/void, no-op acceptance fires no cascade — services.py:591-598
- §3.6 — insert — ambiguity — voided fee items keep their last `inclusion_in_test` value — services.py:375-395
- §3.6 — insert — ambiguity — the explicit fee test and the ATR determination are accepted from every status except `DENIED` and both require the bound underwriter — routes_loanfile.py:263-287
- §3.6 — insert — ambiguity — a non-exempt `DSCR` file can never reach `DOCUMENTED`; a non-`DSCR` file can reach `EXEMPT` with no worksheet — services.py:416-442
- §3.7 — revise — mismatch — corrected which events re-run the overlay sweep, that every sweep recomputes seasoning first and ends in an eligibility recompute, and that the first tier-2 signature deliberately does not sweep — services.py:313-360, routes_exception.py:141-148
- §3.7 — revise — mismatch — a metric that became null counts as changed; comparison numeric at declared scale; the suspend cascade fires only for the three cascading sweeps — services.py:302-311, 344-360
- §3.8 — insert — ambiguity — **gap #2**: `suspension_reason`, `resolution_note`, `approval_note`, `denial_reason` and the closing instant are internal-only and never emitted, yet still bump `version` — core.py:176-182, routes_loanfile.py:302-312/412/433/466
- §3.8 — revise — mismatch — manual and cascaded suspension are the same operation writing the same four fields (incl. `securitization_eligible` false); three cascade sources enumerated; a rising breach count alone suspends nothing — routes_loanfile.py:304, services.py:335-360
- §3.8 — revise — mismatch — the non-`DSCR` ACCEPTED-worksheet requirement is a separate `ERR_LOAN_FILE_STATE_INVALID` check; `unresolved_overlay_breach_count` occupies a slot below the appraisal gates; the seasoning gate re-evaluates against the clock without storing — routes_loanfile.py:347-365, 64-75
- §3.8 — revise — mismatch — LTV basis corrected to §3.3's basis; null `ltv_pct`/`dscr_ratio` refused under their own codes; approval records the note and re-stores seasoning — routes_loanfile.py:389-398, 411-415
- §3.8 — revise — mismatch — **gap #3**: closing's three gates in order, eligibility last as `ERR_LOAN_FILE_STATE_INVALID`; full `supporting_valuation` selection rule incl. both skip-entirely fallbacks; calendar-date expiry; internal closing instant — routes_loanfile.py:451-468, services.py:692-712
- §3.9 — revise — mismatch — **gap #1**: recompute-trigger set rewritten to the inclusive list (submission, fee test + every fee add/void, ATR, worksheet accept, every accepted valuation, reviewer override, condition clearing, approval, closing, every exception decision incl. first tier-2 signature, every finding write/regrade and its cascades, credit-event recording across the borrower's non-`DENIED` files), plus the two direct writes (suspend, deny) and the pool non-trigger
- §3.9 — revise — mismatch — audit clearance returns the file to `CLOSED` only when no other audit on it grades `C_MATERIAL` — services.py:646-657
- §4 — revise — mismatch — `GET /loan-files` has no investor filter — routes_loanfile.py:178
- §4 — revise — mismatch — submit-to-underwriting no longer claims it runs the points-and-fees test — routes_loanfile.py:237-253
- §4 — insert — ambiguity — `status` filter on `GET /loan-files/{id}/income-worksheets` — routes_worksheet.py:152-154
- §4 — insert — ambiguity — `inclusion_status` filter on `GET /income-worksheets/{id}/statement-months` — routes_worksheet.py:209-211

All three handed-over gaps resolved.

### Pass 3 (routes_valuation.py, routes_fees.py, routes_exception.py, routes_audit.py, routes_pool.py) — verbatim summary

No copy performed; pass 1 + pass 2 edits verified present by spot-checking unique marker strings. Size: 444 lines / 126,172 B -> 444 lines / **133,898 B**. Counts: 17 ambiguity-pins, 6 mismatch-revisions (23 edits).

- §3.5 — revise — mismatch — appraisal review row created by the file's first order of **any** `valuation_type`, not only the first `PRIMARY_APPRAISAL`; birth-state field nulls pinned — routes_valuation.py:64
- §3.5 — insert — ambiguity — receipt's loan-file condition reports `ERR_VALUATION_ORDER_STATE_INVALID`; negative `appraised_value_cents` is `ERR_INVALID_REQUEST` above both state checks, zero accepted — routes_valuation.py:96-103
- §3.5 — insert — ambiguity — missing `rejection_reason` on `REJECTED` is `ERR_INVALID_REQUEST` before the order-state rule; a reason sent with `ACCEPTED` is ignored — routes_valuation.py:129-133
- §3.5 — revise — mismatch — `second_valuation_status` written to `SECOND_RECONCILED` unconditionally on accepting a second appraisal, and an out-of-tolerance variance can escalate an already-`PRIMARY_CLEARED` dimension — services.py:570-589
- §3.5 — insert — ambiguity — **(gap a)** `override_justification` is internal bookkeeping absent from the emitted appraisal-review resource; the override refreshes `securitization_eligible` but runs no LTV recompute/sweep/cascade — routes_valuation.py:167,178,182
- §3.6 — insert — ambiguity — `fee_code` uniqueness ignores `status` so a voided code stays occupied; `amount_cents` is the payload's only numeric-domain condition and the duplicate check is last of the three — routes_fees.py:37-46
- §3.6 — insert — ambiguity — the 201 body already carries the settled `inclusion_in_test`; void has no loan-file-status precondition and a double void is `ERR_INVALID_REQUEST` at 400 — routes_fees.py:57,64,87-88
- §3.7 — revise — mismatch — the tier-2 **first** signature also requires `pinned_metric_value` to equal the live metric — routes_exception.py:110-118
- §3.7 — insert — ambiguity — loan-file-status and live-metric refusals both report `ERR_EXCEPTION_STATE_INVALID` and precede the segregation and authority checks; `decision_reason` written only when supplied — routes_exception.py:111-137
- §3.7 — insert — ambiguity — a denial checks neither the loan file's status nor the pinned metric, yet still runs the sweep + eligibility recompute — routes_exception.py:138-140
- §3.9 — insert — ambiguity — non-positive `target_balance_cents` is `ERR_INVALID_REQUEST`, before the duplicate-code check — routes_pool.py:30-35
- §3.9 — insert — ambiguity — assignment also moves the assigned loan file's `version`/`updated_at` — routes_pool.py:99-100
- §3.9 — insert — ambiguity — **(gaps c+e)** a client-requested removal leaves pool `status` untouched; `OPEN -> REBALANCING` belongs to the material-defect cascade alone; removal bumps the loan file's version; neither attach nor detach recomputes `securitization_eligible` — routes_pool.py:139-149, services.py:617-625
- §3.9 — insert — ambiguity — **(gap d)** audit creation requires the file `CLOSED` or `AUDIT_DEFECT`; `open_finding_count` starts 0; unlimited audits per file — routes_audit.py:35-46
- §3.9 — insert — ambiguity — **(gap d)** finding creation's loan-file condition also reports `ERR_FINDING_STATE_INVALID`; refusal order audit-status -> file-status -> duplicate code; finding born with `rebuttal_round` 0 and both notes null; `OPEN -> FINDINGS_ISSUED` precedes the regrade — routes_audit.py:80-105
- §3.9 — insert — ambiguity — **(gap d)** `rebuttal_round` never resets on a return; returned `rebuttal_text` persists; an omitted `adjudication_note` leaves an earlier note in place — routes_audit.py:136,161-162
- §4 — revise — mismatch — `POST /valuation-orders`: review created on the first order of any type — routes_valuation.py:64
- §4 — revise — mismatch — `POST /post-close-audits`: `CLOSED` or already `AUDIT_DEFECT` — routes_audit.py:35
- §4 — revise — mismatch — `POST /points-and-fees-items/{id}/void`: rebuilds aggregates, re-decides the verdict only once a test has run — routes_fees.py:97
- §4 — insert — ambiguity — `valuation_type`/`status` filters on the file's valuation-order list — routes_valuation.py:83-86
- §4 — insert — ambiguity — `status`/`inclusion_in_test` filters on the file's fee-item list — routes_fees.py:74-77
- §4 — insert — ambiguity — `grade` filter on the file's post-close-audit list — routes_audit.py:61-63
- §4 — insert — ambiguity — `status`/`severity` filters on the audit's finding list — routes_audit.py:115-118

Gap disposition: (a) pinned in §3.5. (b) verified already pinned in §3.7 — no change needed. (c) pass 2's negative assertion cross-checked against `routes_pool.py` and confirmed correct (neither `assign_loan` nor `remove_loan` calls `recompute_eligibility`); balance-cap ordering already matched. (d) both gates and the round counter pinned. (e) resolved — `detach_from_pool` is called only from `cascade_material_defect` with `rebalancing=True`, so a client removal never drives `OPEN -> REBALANCING`; the `rebalancing=False` parameter is dead code. No corrections to earlier passes' wording were required.

Completeness statement: after three passes no *reachable* implementation behavior remains unpinned. Two dead paths named for the record: `services.audit_regrade`'s `MATERIAL_DEFECT -> CLEARED` branch (unreachable because reaching `MATERIAL_DEFECT` requires every finding terminal, and terminal findings admit no further write) and `services.ensure_review`'s `SECOND_REQUIRED` birth branch (unreachable because `second_valuation_required` can only turn true via a re-test that runs after the review row exists).

### Orchestrator final verification — 2026-09-05T15:52:00.000Z

- `workspace/PRD_COMPLETED.md` exists: 444 lines / 133,898 B; `cmp` confirms it is NOT byte-identical to `PRD_FINALIZED.md` (the scan genuinely ran); it ends on `| ERR_POOL_BALANCE_CAP_EXCEEDED | 422 |` and retains all 27 section headers, so no pass truncated it.
- All 8 `workspace/implementation/results.$i.json` present, each `passed: 103, failed: 0, total: 103`. The newest implementation source file is stamped 14:54:05, earlier than the sweep's 14:58:31, so the clean 8-round sweep describes exactly the implementation now on disk — Steps 8 and 9 touched only PRD documents.
- No stray `worklog.md` anywhere under the task tree except the orchestrator-owned one at the task root; `test_helpers/` and `test_suite/` are at the task root, not under `workspace/`.
- Per-step scratch directories (`scratch_step2/4/5/6/8/9`) and all `__pycache__` removed. `workspace/sweep.sh` and `workspace/sweep.log` retained as Step 7 evidence.

Pipeline complete through Step 9.
