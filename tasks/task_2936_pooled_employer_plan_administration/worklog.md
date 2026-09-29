## Step 1: Create task directory — 2026-09-05T18:45:14.216640700Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2936_pooled_employer_plan_administration and its workspace/ subdirectory (pre-assigned index 2936; no auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-05T20:59:14.873037557Z

All three scaffold artifacts are complete and lint-clean.

## Files
- `SCAFFOLD.yaml` — 3510 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 3541 lines (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5328 lines (single top-level key `scaffold_corner_design`)

All three parse with `yaml.safe_load`. `SCAFFOLD.yaml` contains neither design key, its `scenario` begins with "Pooled Employer Plan Administration (pooled employer plan provider): …", and no difficulty-directive text leaked into it.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  §1.5 endpoints declared:    60
  §1.1 entities declared:     12
  §1.8 instances scanned:     24
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  1634

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## SCAFFOLD.yaml shape
`api_prefix: /pep`; 12 entities, 11 state machines, 13 calculations, 71 validations, 60 endpoints, 80 errors (80 unique ids), 2 concurrency rules, 5 roles. Profile: compliance_audit / ledger_reconciliation, `entity_topology: flat`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`.

## §1.8 rule ids (24 instances)
dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 3, compensating_invariant 2.

## §1.9 sections (75 items = 55 real + 20 `excluded_because` stubs)
entities 12, state_machines 13, calculations 12, validations 12, endpoints 5, errors 9, rbac 4, cross_cutting_complexity_layers 6, consistency_model 2.

## Verification beyond lint
- Every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name (0 dangling), no stub carries a `test_recipe`, and all instance names are unique across the union of both design files.
- All 80 declared error ids are exercised by at least one §1.8/§1.9 instance (0 uncovered) — the last gaps closed were the 401/403 quartet (rbac), both 412 stale-version errors (layers), and `ERR_FILING_ALREADY_SUBMITTED` via a year-keyed exit-reversal lock.
- Two SCAFFOLD.yaml reachability defects found earlier were fixed in place: priority 39 rewritten to `ERR_NO_BILLABLE_SERVICE_PROVIDER` (an ACTIVE plan always has engaged providers, so the old `ERR_NO_SERVICE_PROVIDERS` was unreachable) and priority 64 extended to `POST /pep/compliance-tests` scope EMPLOYER_LEVEL (no ACTIVE→APPLIED edge made the batch-only rule unreachable).
- `worklog.md` and `workspace/` were left untouched; scratch stayed in `.scratch/step2/`.

## Step 3: Copy shared files — 2026-09-05T20:59:14.887595567Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-05T21:14:22.829171736Z

`workspace/PRD.md` — **456 lines, 110,892 bytes**. Written incrementally (one `Write` for the title/§1, then ~14 `cat >>` heredoc appends); no truncation. Ends cleanly at the final row of the §5 table (`ERR_FILING_ALREADY_SUBMITTED | 409`), a real section boundary. Orchestrator independently verified the tail and confirmed no difficulty-directive or SCAFFOLD reference leaked into PRD.md.

## Section list
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC · 2.2 API Response Structure · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Version Semantics · 2.5 The Logical Clock, Calendar Dates and the Business-Day Calendar · 2.6 Cents, Percentages and Rounding Discipline · 2.7 Stale-Version Protection on Superseding Writes · 2.8 Reverse Navigation and Left-to-Right Resolution of Path Identifiers · 2.9 Plan Control Totals, Derived Gates and Compensating Reversals · 2.10 Segregation of Duties Across the Provider Layer · 2.11 Rejection Precedence
- `## 3. Business Logic & Workflows` — 3.1 Provider Registration, Plan Document and Provider Layer · 3.2 Admitting Employers and Census Data · 3.3 Plan Design Elections · 3.4 Payroll Delivery, Match Reconciliation and the Deposit Deadline · 3.5 Remittance Settlement, Timeliness and Late-Deposit Correction · 3.6 Coverage and Nondiscrimination Testing · 3.7 The Plan-Level Annual Return · 3.8 Employer Exit, Spin-off and Asset Transfer · 3.9 Fee Disclosure and Revenue Sharing Allocation
- `## 4. Endpoint Definitions` — 4-column table, 60 rows
- `## 5. Error Code Catalogue` — 2-column table, 80 rows

## Coverage audit (scripted against SCAFFOLD.yaml, zero gaps)
- **Endpoints: 60/60** — every path string present, including `/_clock/set_current_utc`.
- **Errors: 80/80** — present in prose and in the §5 table.
- **Validations: 71/71** — all 71 distinct `error_id`s present; priority-1→71 ladder expressed as ordered error-id bands in §2.11, each rule's condition stated in §3 next to its workflow.
- **Calculations: 13/13** — `business_days_elapsed`, `deposit_due_date`, `employer_match_amount`, `lost_earnings`, `excise_tax_5330`, `coverage_ratio_percentage`, `adp_acp_limit`, `revenue_sharing_allocation`, `net_plan_expense`, `exit_settlement_waterfall`, `fidelity_bond_minimum`, `filing_deadline_date`, `plan_control_totals` — each with constants inlined, pinned evaluation order and worked examples.
- **State machines: 11/11** — 52 transitions; includes the `PlanFiling` fork-join with conditional single-branch join, both parallel `RemittanceDeposit` machines (`deposit_status`, `timeliness_status`), and the `EXITED → SPINOFF_IN_PROGRESS` reversal escape.
- **Role model: 5/5** roles with identity translations (`RegulatorOps`, `IndependentAuditor` opaque; `PooledPlanProvider`, `AdoptingEmployer`, `ServiceProvider` entity-backed) plus the §2.10 segregation-of-duties matrix.

## Hard Contracts
- **Contract 1 — Field-Name Coverage: PASS.** All 168 entity field names; all 82 endpoint input tokens (incl. `current_utc`, `limit`, `offset`, `expected_adopting_employer_version`, `expected_plan_document_version`); all 82 enum literals; the 5 `allocation_lines` sub-keys.
- **Contract 2 — Rule Coverage: PASS.** 71/71 validations, 13/13 calculations, 11/11 state machines, 2/2 concurrency rules, 5/5 roles.
- **Contract 3 — §3 Path Purity: PASS.** 1,085 backticked tokens in §3 scanned: zero paths, zero bare HTTP methods, zero method+path combos; no raw `/pep/` anywhere in §3.

## Judgement calls
- Two scaffold preconditions carried no `error_id`; mapped explicitly: `registration_effective_date` earlier than the logical-clock date → `ERR_VALIDATION` (422); compliance-test run against an empty population → `ERR_TEST_INVALID_STATE` (409).
- `ERR_PROVIDER_NOT_REGISTERED` documented as an **activation-only** gate (matching validations priority 25's `applies_to`), not a creation gate — gating creation would make the activation precondition unreachable since registration is terminal.
- `expense_rebate_pct` has conflicting precision hints (field 2dp, calculation 1dp); documented via its three literal values `5.0` / `2.0` / `0.0`, satisfying both.
- Constraints honoured: neither design YAML was opened, grepped or referenced. Scratch confined to `.scratch/step4/`.

## Step 6: Generate implementation — 2026-09-05T21:55:14.929421114Z

Step 6 complete. The implementation is finished, self-verified, and every smoke server has been shut down by exact PID.

## Modules (all in `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `app.py` | 90 | `create_app()`, blueprint registration, envelope error handlers, `PORT` bind |
| `authz.py` | 128 | 5-role RBAC, `X-User-ID`/`X-User-Role` identity, ownership, version-bump tracker |
| `calc.py` | 444 | all 13 calculations (Decimal/ROUND_HALF_UP, `Fraction` largest-remainder) |
| `clockcal.py` | 209 | logical clock (`2026-08-01T00:00:00Z`), business-day calendar, 2025–27 holidays |
| `envelope.py` | 371 | `meta`/`response_type`/`data` envelope, per-entity views, pagination, Decimal raw-JSON |
| `errors.py` | 224 | 80-id catalogue + HTTP statuses, 71-rung `LADDER`, `PRIORITY` |
| `recompute.py` | 155 | plan control totals, derived gates, employer-derived fields |
| `routes_setup.py` | 488 | PRD 3.1 provider/plan/service-provider/fiduciary-allocation |
| `routes_employer.py` | 414 | PRD 3.2/3.3 adopting employer + design election |
| `routes_payroll.py` | 489 | PRD 3.4/3.5 payroll batch, remittance, timeliness, correction |
| `routes_compliance.py` | 456 | PRD 3.6/3.7 coverage/ADP/ACP + fork-join annual return |
| `routes_exit.py` | 351 | PRD 3.8/3.9 exit waterfall, fee disclosure, `_clock/set_current_utc` |
| `start.sh` | 10 | reads `$PORT`, binds `0.0.0.0`, `exec python3 app.py` in foreground |
| `requirements.txt` | 1 | `flask>=2.0` |

4321 lines total. `grep` for `TODO`/`FIXME`/`NotImplemented`/bare `pass`: none.

## Completeness (verified programmatically, not by eye)
- **Endpoints: 60/60** — enumerated from `app.url_map`; `TOTAL 60`.
- **Errors: 80/80** — `errors.CATALOGUE_SIZE == 80`; regex sweep shows zero unreferenced catalogue ids. The only non-catalogue id in source is `ERR_INTERNAL` (500 safety net in `app.py`); `errors.py` also adds `ERR_FEE_DISCLOSURE_NOT_FOUND`, `ERR_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED` after `CATALOGUE_SIZE` is recorded, because the PRD declares no not-found error for FeeDisclosure and no transport fallbacks.
- **Ladder: 71/71** — `len(errors.LADDER) == 71`.
- **Calculations: 13** — deposit due date, business-days-elapsed/late-by, expected match (4 formula codes incl. tiered), IRS 6621 lost earnings, VFCP lost earnings, restoration, excise tax, coverage ratio, weighted-average ADP/ACP + limit, net plan expense, revenue-sharing allocation, exit waterfall, fidelity-bond minimum, filing-deadline roll-forward.
- **State machines: 11** — provider registration, plan document, fiduciary allocation, design election, adopting employer (cyclic), payroll batch, remittance deposit (parallel `deposit_status` × `timeliness_status`), compliance test, plan filing (fork-join), exit transfer, plan compliance posture.
- **No seeded data** — fresh boot on port 52777 returned `ERR_*_NOT_FOUND` for provider, plan and employer probes; boot is instant with no pip install (`start.sh` installs only if `import flask` fails).

## Smoke results
Three end-to-end passes (ports 48177, 59141, 52777), ~200 calls, 0 unexplained mismatches.

PRD worked examples reproduced exactly:
- exit waterfall: `8500000`/13 participants → admin 16250, flat 250000, transfer 8233750, unrecovered 0; `100000`/4 → admin 5000, only 95000 of the flat fee applied, unrecovered 155000, transfer 0
- `filing_deadline_date` 2027-08-02 (Sat 2027-07-31 rolls forward); `fidelity_bond_minimum_cents` 825000 on 8250000 assets
- net plan expense: gross 1020000 + pool 1000000 → rebate tier 2.0, offset 999600, net 0 (order-sensitive, as the PRD demands)
- `expected_match_cents` 3750000 (SAFE_HARBOR_BASIC) and 3375000 (DISCRETIONARY_TIERED); `deposit_due_date` 2026-07-29 under the 7-business-day safe harbour

Cascades and forks verified live: full late-deposit cascade (LATE → SUSPENDED + `contribution_hold` → plan `RESTRICTED` → Schedule-H bump), correction compute → fund → SUSPENDED→ACTIVE unwind, deposit reversal unwinding batch to `VALIDATED` and balance to 0, audit-required fork-join `PREPARED → PARTIALLY_CLEARED → READY_TO_FILE → FILED` with `ACK-000077`, and the exit waterfall closing `EMPLOYER_LEVEL` tests with `EMPLOYER_EXITED`. `contribution_control_delta_cents == 0` and `headcount_control_delta == 0` after every money/headcount transition.

Ladder precedence confirmed observationally, including the three attestation independence rules in order (`ERR_NOT_AN_AUDITOR_FIRM` → `ERR_AUDITOR_NOT_INDEPENDENT` → `ERR_FIDELITY_BOND_INSUFFICIENT`), `ERR_AUDIT_NOT_REQUIRED` (22) pre-empting all of them, `ERR_EMPLOYER_INVALID_STATE` (15) pre-empting `ERR_INVALID_BLACKOUT_WINDOW` (47), plus 401/403/404/412/422 paths and cross-tenant `ERR_NOT_RESOURCE_OWNER` on three entity types.

## Two PRD judgement calls worth flagging to Step 7
1. **`fund-correction`** uses a single compound `if` raising `ERR_CORRECTION_INVALID_STATE` for both "not POSTED" and "not CORRECTION_COMPUTED", per the explicit PRD sentence, even though the bare ladder would put `ERR_DEPOSIT_INVALID_STATE` (17) first. `compute-correction` keeps the split (17 then 19).
2. **Deposit reversal leaves `late_deposit_schedule_h_line_cents` untouched** — the PRD enumerates reversal's effects exhaustively and omits any filing change; `prepare` recomputes the line from scratch anyway.

Never read `test_helpers/` or `test_suite/`, never touched `worklog.md`, wrote no test artifacts, used no broad `pkill`. Scratch confined to `.scratch/step6/`.

## Step 5: Generate unit tests — 2026-09-05T23:15:17.674749533Z

Step 5 is complete. Everything lives at the task root; `workspace/implementation/` was never read or touched, and `worklog.md` was not modified.

Orchestrator note: this step's subagent was killed mid-run by an infrastructure API error after writing only 3 of the 9 `test_helpers/` files and zero test files. Per prior pipeline experience, it was RESUMED via SendMessage with a computed to-do list (the 6 missing helpers, then conftest.py, then all test_*.py) rather than respawned fresh — a fresh agent would have re-derived the design indices and produced a suite inconsistent with the already-written api_errors.py / constants.py / test_users.py. The resumed agent kept its context and scratch indices and completed normally.

## Files written

`test_helpers/` (2,948 lines): `__init__.py` 16, `api_client.py` 525, `api_errors.py` 208, `assertions.py` 275, `constants.py` 317, `factories.py` 519, `fixtures.py` 721, `test_users.py` 104, `types.py` 263.

`test_suite/` (8,298 lines): `conftest.py` 55, `test_01_provider_register_and_plan_document.py` 451 (10 tests), `test_02_service_providers_and_fiduciary_allocations.py` 747 (11), `test_03_employer_adoption_and_design_elections.py` 807 (10), `test_04_payroll_delivery_and_match_reconciliation.py` 827 (8), `test_05_remittance_settlement_and_timeliness.py` 804 (7), `test_06_late_deposit_corrections.py` 402 (4), `test_07_compliance_testing.py` 680 (6), `test_08_annual_return.py` 977 (8), `test_09_exit_transfers.py` 919 (7), `test_10_fee_disclosure_and_plan_expense.py` 628 (5), `test_11_access_control.py` 530 (5), `test_12_envelope_and_consistency.py` 471 (4).

## Tests emitted

**85 tests**, each carrying exactly one `Design:` line (85 tests / 85 tags, verified by grep). `pytest --collect-only` collects all 85 with no import errors; `pyflakes` is clean over `test_suite/` and `test_helpers/`; the word "scaffold" appears nowhere.

## Per-queue instance coverage

- **Queue A (§1.8): 24 of 24 instances translated.**
- **Queue B (§1.9): 55 of 55 real instances translated** (the file holds 58 `- name:` entries; three are `excluded_because:` cross-references, not test recipes).
- Coverage audit: 79 canonical instances, 79 distinct tags emitted, 0 uncovered, 0 tags outside the index. Six large instances are split across two tests each (each test still tagged once): the three `resource_temporal_overlap` instances, `election_submitted_returned_resubmitted_then_replaced_cycle`, `plan_activation_gated_by_provider_registration_and_two_acknowledged_roles`, and `corner_layer_occ_stale_plan_version_rejected_before_window_checks`.

## Instances skipped / narrowed, with reasons

1. `corner_priority_ordering_between_validation_pairs`, `corner_temporal_validation_windows`, `corner_cascading_validation_chain` — not testable instances: each carries only an `excluded_because:` block pointing at the §1.8 instance that already pins the claim. No test emitted, by construction.
2. `corner_layer_occ_stale_employer_version_rejected_and_token_lifetime` — translated only in its PRD-derivable core (stale-version rejection + version advance). The design's "token lifetime" claim has no PRD counterpart; dropped rather than weakened.
3. `corner_net_plan_expense_zero_rebate_below_first_tier_floor` — tier-floor and auditor-fee-in-the-input-set claims asserted as designed, but the design's expectation of one `allocation_lines` row at `credit_cents` 0 contradicts PRD §3.9 ("If the total basis across the population is zero … `allocation_lines` is the empty array …"). The test follows the PRD and asserts the empty array.
4. Three design literals naming undeclared symbols were replaced with the PRD's spelling rather than tested as written: `audit_opinion: "UNQUALIFIED"` → `UNMODIFIED`; `ERR_PLAN_INVALID_STATE` (nonexistent — the test asserts only the 403 it can derive); the design's second sponsor "Calderwood" is the factories' Westvale.

One incidental fix: `test_11` initially asserted the payroll batch's state as `batch_status`, which does not exist in the PRD — corrected to `status` (the PRD's `PayrollBatch` field name) before the final audits.

## Step 7: Run tests and iterate — 2026-09-05T23:36:47.164269282Z

worklog.md, PRD.md and sweep.sh are untouched (mtimes predate my work). Fully green.

**Iterations run:** 3 (each a full 8-round `sweep.sh` sweep). Started at 70/85, then 84/85, then 85/85.

**Tests deleted:** none. Every failure traced to a test-artifact defect or a precedence mis-translation, not to PRD silence.

**Fixes applied to `test_helpers/`**
- `test_helpers/factories.py` — added a `_defaults(defaults, overrides)` merge helper and rewrote eight derived factories (`second_plan_document_payload`, `recordkeeper_payload`, `trustee_payload`, `tpa_payload`, `auditor_firm_payload`, `investment_manager_payload`, `second_adopting_employer_payload`, `tiered_design_election_payload`, `employer_level_test_payload`) to merge their narrowed defaults with the caller's `**overrides` before splatting once. Previously each passed its defaults as explicit keywords *alongside* `**overrides`, so any caller overriding one of those same fields hit `TypeError: got multiple values for keyword argument`. This single bug accounted for **11 of the 15** initial failures (spread across `legal_name`, `provider_type`, `participant_count`, `direct_fee_cents_per_participant`).

**Fixes applied to `test_suite/`**
- `test_01_provider_register_and_plan_document.py` / `test_unresolvable_body_foreign_keys_name_the_collection_they_point_at` — STEP 1c partial-coverage split: removed the stanza asserting `ERR_PLAN_PROVIDER_NOT_FOUND` for an unresolvable body `pooled_plan_provider_id`. PRD §2.8 enumerates exactly four body-FK not-found errors and `PooledPlanProvider` is not among them; §2.11 puts `ERR_NOT_RESOURCE_OWNER` at priority 4 versus body-FK existence at priority 6, so an unresolvable sponsor id can never reach the not-found stage. Kept the covered `ERR_PLAN_DOCUMENT_NOT_FOUND` assertion; `ERR_PLAN_PROVIDER_NOT_FOUND` remains covered as a *path* identifier in `test_11_access_control.py`. Dropped the two now-unused imports.
- `test_03_employer_adoption_and_design_elections.py` / `test_generosity_floors_and_the_window_gate_are_separate_refusals` — removed a stray `ERR_EMPLOYER_INVALID_STATE,` positional argument left in two `validate_error(...)` calls (an editing artifact producing `TypeError: validate_error() got multiple values for argument 'expected_status'`).
- `test_03_.../test_actions_aimed_at_the_wrong_state_are_refused_and_change_nothing` — dropped `"exited_at"` from the `assert_null_fields` on the **ExitTransfer** payload. PRD §5 puts `exited_at` on `AdoptingEmployer` (and `test_helpers/types.py` agrees); asserting it on the transfer row was a resource mix-up.
- `test_04_payroll_delivery_and_match_reconciliation.py` / `test_withholding_and_recovery_windows_are_pinned_at_both_ends` — replaced the `_delivery(...)` call for the early-withholding case with an explicit `payroll_batch_payload`. `_delivery` sets `pay_date = withholding_date`, so the "withholding before period start" case also violated PRD's `pay_date >= pay_period_start` rule, and the implementation correctly reported the higher-priority `ERR_INVALID_PAY_PERIOD` (priority 40) instead of `ERR_WITHHOLDING_DATE_OUT_OF_PERIOD` (priority 42). Now only the intended defect is present.
- `test_08_annual_return.py` / `test_independence_is_judged_before_the_bond_on_a_doubly_defective_attestation` — moved the `fidelity_bond_amount_cents` assertion off the PlanDocument payload onto a `get_plan_provider` read. PRD §5 declares that field on `PooledPlanProvider` and never says the plan document echoes it; PRD §7's bond rule reads "the sponsoring provider's `fidelity_bond_amount_cents`", so the provider row is the faithful target.

**Fixes applied to `implementation/`:** none. No failure survived STEP 1 + STEP 2 — every one was a test-artifact defect, and in the two precedence cases (`ERR_NOT_RESOURCE_OWNER` before body-FK existence, `ERR_INVALID_PAY_PERIOD` before `ERR_WITHHOLDING_DATE_OUT_OF_PERIOD`) the implementation was already the PRD-faithful reading of the §2.11 ladder.

**Final sweep evidence** (`workspace/implementation/results.1..8.json`, left in place):

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 85/85 | 85/85 | 85/85 | 85/85 | 85/85 | 85/85 | 85/85 | 85/85 |

Zero failures, zero errors, union of failing tests across all 8 rounds is empty — no flakiness.

**Orchestrator verification (independent of the subagent's claim):** all 8 `results.$i.json` re-parsed directly — each reports `{'passed': 85, 'failed': 0, 'total': 85, 'errors': 0}`; `grep -c '^def test_'` over `test_suite/` confirms 85 tests actually on disk; `worklog.md` and `PRD.md` mtimes confirm neither was written by Step 7.

## Step 8: Finalize PRD — 2026-09-05T23:45:56.288659691Z

Done. One edit made.

**Line counts:** PRD.md 456 lines → PRD_FINALIZED.md 456 lines (0.0% line delta; one paragraph of §2.8 rewritten, +~90 words / +0.7% by character count). No other byte differs.

## Change
- **§2.8 (Reverse Navigation and Left-to-Right Resolution of Path Identifiers)** — *revise* — Added `ERR_PLAN_PROVIDER_NOT_FOUND` / `pooled_plan_provider_id` to the enumeration of body-foreign-key not-found errors, and pinned that on plan-document creation the sponsor FK is compared to `X-User-ID` before it is resolved, so a value naming anyone else is `ERR_NOT_RESOURCE_OWNER` at priority 4 regardless of existence, while `ERR_PLAN_PROVIDER_NOT_FOUND` is reachable only for a value equal to the caller's own identifier — `implementation/routes_setup.py:130-137` (with `implementation/validate.py:195-226`).

### Pre-edit search log
- **(a) Subject:** which body foreign keys participate in the priority-6 existence stage, which not-found error each raises, and how the priority-4 ownership check orders against them.
- **(b) Impl paths enumerated:** `grep -n "resolve_fk|fk_candidate|require_fk_shape"` over all of `implementation/`; every body-FK site read: `routes_setup.py:130` (`pooled_plan_provider_id` → `providers`, `ERR_PLAN_PROVIDER_NOT_FOUND`, preceded by the raw `!= g.user_id` comparison), `routes_setup.py:289/292`, `routes_setup.py:393/396`, `routes_employer.py:60`, `routes_employer.py:228`, `routes_payroll.py:70`, `routes_payroll.py:266`, `routes_compliance.py:50/53`, `routes_compliance.py:272`, `routes_compliance.py:356`, `routes_exit.py:54`, `routes_exit.py:261`. Also read `validate.py:195-226` (`fk_candidate`/`resolve_fk`/`require_fk_shape`), `authz.py` (`own`, `own_if`, `own_provider`), and `grep -n "g.user_id"` to confirm `routes_setup.py:131` is the only site comparing a body FK to the header before resolution. Confirmed no other body FK points at `PooledPlanProvider`, and every other parent FK is resolved first (`resolve_fk` → 404) then handed to `own_if`, so ownership does not precede existence for them.
- **(c) Wording adjustment:** scoped the ownership-before-resolution clause explicitly to "the `pooled_plan_provider_id` of a new plan document" rather than a general statement about body FKs, because every other create resolves the FK first; a general claim would have contradicted eleven other callsites. Avoided naming a role in the clause (the endpoint is `PooledPlanProvider`-only per §4) and kept the existing "absent or not a string ⇒ `ERR_VALIDATION`" sentence verbatim, matching `routes_setup.py:137` calling `require_fk_shape` after the unresolved-`None` fall-through in `validate.resolve_fk`.

## Items from the Step 7 diff that earned NO edit, with justification
1. **`factories.py` duplicate-kwarg `TypeError` (11 of 15 initial failures)** — pure test-artifact bug: `**overrides` splatted alongside explicit keywords. No `implementation/` behavior implicated; nothing in PRD silent or wrong.
2. **`test_03` stray `ERR_EMPLOYER_INVALID_STATE` positional argument** — pure editing artifact. No PRD implication.
3. **`ERR_INVALID_PAY_PERIOD` before `ERR_WITHHOLDING_DATE_OUT_OF_PERIOD`** — already uniquely determined: §2.11 assigns priority 40 vs 42, and `routes_payroll.py:92-106` checks in exactly that order (`pay_date < period_start` → 40, overlap → 41, withholding range → 42), matching §3.4 ¶2's prose order. Kept verbatim.
4. **Which resource carries `exited_at`** — already determined. `grep -n exited_at implementation/*.py` returns only `routes_employer.py:108` (init null), `routes_exit.py:183` (stamp at settlement), `routes_exit.py:234` (clear at reversal), `envelope.py:209` (in the employers field list); the `exits` field list (`envelope.py:312-331`) has no `exited_at`. PRD §3.8 already says the employer has `exited_at` stamped and cleared on reversal. Test was a resource mix-up, not PRD silence.
5. **Which resource echoes `fidelity_bond_amount_cents`** — already determined. The field appears only on `providers` (`routes_setup.py:52/63/87`, `envelope.py:134`); the `plans` field list has no such key, and the attest gate at `routes_compliance.py:384-385` reads it off the resolved sponsoring provider, exactly as PRD §3.7 words it. The filing carries only the derived `fidelity_bond_minimum_cents`. No edit.

## Step 9: Complete PRD — pass 1 of 3 (cross-cutting foundations) — 2026-09-06T00:21:42.681022772Z

Orchestrator note on method: Step 9 was run as THREE SEQUENTIAL module-partitioned passes over one shared `PRD_COMPLETED.md`, rather than a single agent scanning all 4321 lines of `implementation/`. A single-agent scan of an implementation this large reliably degenerates into a `cp` with no real scan. Pass 1 owned the cp; passes 2 and 3 were explicitly forbidden from copying, and each reported the file's size before/after to prove prior edits survived. Slices: pass 1 = app/authz/errors/envelope/clockcal/validate; pass 2 = calc/recompute/routes_setup/routes_employer; pass 3 = routes_payroll/routes_compliance/routes_exit.

Pass 1 complete. Server probe on port 43936 booted and killed cleanly (PID 3237275).

## Step 0
`cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` confirmed.
- PRD_FINALIZED.md: 456 lines / 111,454 chars
- PRD_COMPLETED.md: 457 lines / 117,415 chars (+5,938 chars, +1 line)

## Counts
- ambiguity-pins: **14**
- mismatch-revisions: **1** (§5 preamble's "Every error identifier the API can return" was false — three ids exist outside the table plus `ERR_INTERNAL`)

## Changes
- §2.1 (RBAC/ownership) — insert — ambiguity — a non-resolving entity-backed `X-User-ID` fails ownership with `ERR_NOT_RESOURCE_OWNER`, never a not-found; `AdoptingEmployer`/`ServiceProvider` reaching an employer-less resource are narrowed to their own `plan_document_id` — authz.py:62-90
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — envelope.py:14,31
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from real wall-clock time, NOT the logical clock, so it is unrelated to `created_at`/event instants (verified live: meta showed 2026-09-05 while `created_at` was 2026-08-01T00:00:00.000Z) — envelope.py:34-39
- §2.2 (error format) — insert — ambiguity — transport fallbacks in the same envelope: unrouted path→`ERR_NOT_FOUND` 404, wrong method→`ERR_METHOD_NOT_ALLOWED` 405, unparseable body→`ERR_VALIDATION` 422, trailing slash is the same path, escaped defect→`ERR_INTERNAL` 500 — app.py:25,38-79
- §2.3 — insert — ambiguity — non-integer-literal `limit`/`offset` is `ERR_VALIDATION`; whitespace and leading `+`/`-` tolerated; params read only by collection endpoints — envelope.py:93-114
- §2.3 — insert — ambiguity — `created_at` ties broken by creation sequence (the stationary clock makes ties the norm), never by `id` — store.py:79
- §2.3 — insert — ambiguity — `has_more` formula (`offset` + rows returned < `total_count`) and offset-past-end returns 200 with an empty array — envelope.py:66,120
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are stamped from the logical clock, so pre-move rows read `2026-08-01T00:00:00.000Z` — store.py:58-60,112
- §2.4 — insert — ambiguity — version/updated_at bump is idempotent within one request even across several side effects — authz.py:125-128, store.py:101-114
- §2.5 — insert — ambiguity — clock endpoint: `current_utc` required, may move backwards, answers 200 with `data.current_utc` echo — routes_exit.py:344-351
- §2.5 — insert — ambiguity — rendered instants always 3 digits + `Z`; accepted instants admit 0–9 fractional digits and `±HH:MM` offsets, normalised to UTC — clockcal.py:52-105
- §2.5 — insert — ambiguity — a fourth business-day primitive, "roll forward to a business day" (a business day stays put) — clockcal.py:200-205
- §2.6 — insert — ambiguity — percentages serialise as JSON numbers at fixed scale with trailing zeros (`5.00`, `7.0`) and inbound percentages are quantised half-up first — envelope.py:19-27, validate.py:123-147
- §2.8 — insert — ambiguity — `ERR_FEE_DISCLOSURE_NOT_FOUND` (404) for the fee-disclosure path id; path existence is settled before ownership can be judged — errors.py:111, routes_exit.py:334
- §2.8 — insert — ambiguity — a body that is not a JSON object at all is `ERR_VALIDATION`, not an ownership/not-found failure; an absent body reads as `{}` — validate.py:19-28, authz.py:93-100
- §2.11 (priority 7) — insert — ambiguity — explicit `null` == absent; booleans rejected as numbers; a decimal-pointed number rejected where an integer is required; numbers-as-strings rejected — validate.py:35-137
- §5 preamble — revise — mismatch — table is the *business* catalogue; names the four out-of-table ids and their statuses — errors.py:105-113, app.py:69-79

## Verified already-pinned (no change), incl. borderline calls
- Error catalogue: all 80 PRD rows match `HTTP_STATUS` id-for-id and status-for-status; PRD table order == `LADDER[:4]` + the 11 not-founds + `LADDER[6:]`. Exact.
- Ladder prose §2.11: the 69 named ids in paragraph order are byte-identical to `LADDER` minus the two placeholders. Exact.
- Per-entity field lists: every one of the ~180 names in `envelope.FIELDS` appears in PRD prose, and every backticked snake_case token in the PRD is either a response field, a known input, an envelope key, or an `allocation_lines` sub-field. No orphan either way. Did NOT pin JSON key *order* — impl is deterministic but the PRD never promises order and it is not observable through a JSON parser.
- `FeeDisclosure` unversioned (`id` + `created_at` only) — §2.4 already exact vs `envelope.UNVERSIONED`.
- Holiday table: all 33 dates match `FEDERAL_HOLIDAYS` exactly, all three years.
- Borderline, left alone: `own_provider` falls through to `ERR_NOT_RESOURCE_OWNER` for roles other than RegulatorOps/IndependentAuditor/the provider itself, but §4's role column makes that branch unreachable — pinning it would add dead prose.

## Notes handed to passes 2/3
- The §2.4 once-per-request bump and the §2.3 created_at tie-break are cross-cutting (`store.py`, owned by no pass); later passes reference them rather than restating.
- "Roll forward to a business day" was added as a §2.5 primitive with deliberately no statement of *where* it is used (`calc.py:442`, the filing deadline) — that use is pass 2's.

## Step 9: Complete PRD — pass 2 of 3 (calculations, derived state, setup + employer routes) — 2026-09-06T00:21:42.694208963Z

Pass 1's edits are intact. Pass 2 complete.

| | before | after |
|---|---|---|
| lines | 457 | **457** |
| chars | 117,415 | **120,675** |

Line count unchanged (every edit is an in-paragraph insert/revision) and all six pass-1 marker strings still present — patched in place with `Edit` only, never re-copied.

## Counts
- ambiguity-pins: **10**
- mismatch-revisions: **5**

## Changes
- §2.6 — revise — ambiguity — added the four election tier percentages (`match_tier_1_pct`, `match_tier_1_limit_pct`, `match_tier_2_pct`, `match_tier_2_limit_pct`) to the fields governed by the two-decimal half-up scale — routes_employer.py:241-244
- §2.8 — insert — mismatch — pinned that *every* body FK of a create resolves (in declaration order) **before** the ownership comparison, so an unresolvable secondary FK beats `ERR_NOT_RESOURCE_OWNER`; §2.11 read literally puts priority 4 first — routes_setup.py:289-299,393-399, consistent with routes_compliance.py:50-60
- §3.1 — insert — ambiguity — the `PPP-NNNN` approval ordinal advances only on a successful grant; a rejected attempt consumes no number — routes_setup.py:90-92
- §3.1 — revise — ambiguity — a fresh plan document also opens with `audit_required` false — recompute.py:27-45
- §3.1 — revise — mismatch — deleted the "must not be the new row's own identifier" affiliate condition; impl mints the id after validation and has no such check — routes_setup.py:311-312
- §3.1 — insert — ambiguity — neither engaging a service provider nor allocating a fiduciary function requires the plan to be `ACTIVE` — routes_setup.py:283-326,387-458
- §3.1 — revise — mismatch — the window-overlap test runs against *every* `ALLOCATED` allocation for the same plan+role (not "the incumbent"), a `REVOKED` window is reusable, and the test is symmetric in time — routes_setup.py:414-424
- §3.1 — revise — mismatch — supersession revokes *every* `ALLOCATED` allocation with a strictly earlier `effective_from`; an accepted strictly-earlier window displaces nothing, so two `ALLOCATED` allocations of one role can coexist; and `holds_fiduciary_role` recomputation mutates a firm only when the flag actually changes (no version/updated_at bump otherwise) — routes_setup.py:375-384,443-455
- §3.1 — insert — ambiguity — `acknowledgment_statement` is required, ≥1 character, no maximum — routes_setup.py:471
- §3.2 — revise — mismatch — `nhce_count`'s "(at least one)" was readable as a shape range; pinned it as ≥0 at shape level with the at-least-one rule reported as `ERR_CENSUS_INCONSISTENT`, and gave the two benefiting counts their ≥0 range — routes_employer.py:69-73,36-46
- §3.3 — revise — ambiguity — `signatory_name`: absent/null/whitespace-only → `ERR_SIGNATORY_REQUIRED`, present-but-not-a-string → `ERR_VALIDATION`, accepted value stored untrimmed — routes_employer.py:316-333
- §3.5 — insert — ambiguity — IRS 6621 rates outside 2025–2027 hold the nearest published rate (7.0 before, 9.0 after) rather than extrapolating — calc.py:171-178
- §3.6 — insert — ambiguity — coverage ratio when the divisor `hce_benefiting_pct` is 0.00: `ratio_pct` is 100.00 if `nhce_benefiting_pct` > 0 else 0.00, and an empty HCE population gives 0.00 not null — calc.py:253-272
- §3.6 — insert — ambiguity — a headcount-weighted average with zero total weight is 0.00, so a population with no HCEs reports `hce_avg_deferral_pct` 0.00 — calc.py:280-286
- §4 (endpoint table) — revise — ambiguity — the service provider's allocations listing returns `ALLOCATED` and `REVOKED` rows alike — routes_setup.py:356

## Borderline, judged already-pinned (no edit)
- **Pass-1 handoff item**: the `roll_forward_to_business_day` use at `calc.py:442` is already uniquely pinned by §3.7's `filing_deadline_date` prose ("roll *forward* one day at a time… never backward", with the 2027-08-02 worked example). Month arithmetic (`add_months(+7)`, day-of-month ignored) also already matches. No edit needed.
- Election approval and census restatement run the *full* `recompute_plan` and bump the plan's `version`; §3.3/§3.2 mention only the specific derived fields, but §2.4's pass-1 sentence covers it and no other total changes observably.
- §2.9's "monotone" description of `cumulative_enrolled_participant_count` is loose, but its operative clause ("moves by the signed delta") matches routes_employer.py:113,164.
- `_acknowledged_role` ignores the allocation's effective window at activation; §3.1's gate is stated affirmatively with no window condition, so it is already determinate.

## Left to pass 3
- All §3.4–§3.9 state transitions, side effects, route-level gate ordering and cascades in routes_payroll.py, routes_compliance.py, routes_exit.py — the late-deposit cascade, deposit reversal, fork-join filing branches, exit approval/settlement/reversal, fee-disclosure workflow.
- `_sync_suspension` / `recompute_employer_corrections` call-site wording in §3.5; the `certified_employer_count` / `late_deposit_schedule_h_line_cents` snapshots in §3.7.
- The invoking workflows for `exit_waterfall`, `net_plan_expense`, `revenue_sharing_allocation`, `fidelity_bond_minimum`, `filing_deadline_date` (pass 2 pinned only formula/rounding/order semantics).

## Step 9: Complete PRD — pass 3 of 3 (workflow routes) — 2026-09-06T00:41:28.412343154Z

Pass 3 complete. All edits applied in place with the Edit tool; no file was re-copied or rewritten.

## File size before / after
- Before (as handed to pass 3): **457 lines / 120,675 chars**
- After: **457 lines / 127,451 chars** (+6,776 chars, all in-paragraph)
- Prior passes' 30 edits survive: a `cut -c1-60` diff against `PRD_FINALIZED.md` still shows exactly the pass-1/pass-2 structural changes (the extra §2.2 transport bullet at line 73, the "Four business-day primitives" revision in §2.5, the §5 "business error identifier" revision), and no line was added or removed by pass 3.

## Counts
- **Ambiguity pins: 16**
- **Mismatch revisions: 2**

## Changes
- §3.4 Reconciliation — insert — ambiguity — `reconciliation_note` is required, ≥1 char, no maximum length — routes_payroll.py:163
- §3.4 Reconciliation — insert — ambiguity — the employer's `version` advances unconditionally (even when a zero `batch_total_cents` leaves the receivable unchanged) and the plan document's `version` advances with its recomputation — routes_payroll.py:177-179
- §3.5 Posting — insert — ambiguity — `posting_reference` is a required string of 1–64 characters — routes_payroll.py:327
- §3.5 cascade level 2 — insert — ambiguity — the `ACTIVE→SUSPENDED` move is conditional on the employer being `ACTIVE` at that instant (an `EXIT_REQUESTED`/`SPINOFF_IN_PROGRESS`/already-`SUSPENDED` employer keeps its status while hold and count still move), and the return path only fires from `SUSPENDED` — routes_payroll.py:240-257
- §3.5 cascade level 2 — insert — ambiguity — `contribution_hold` is never a precondition anywhere; a suspended employer may still record, post, compute and fund a remittance on a batch already `VALIDATED` — routes_payroll.py:260-479
- §3.5 cascade level 4 — **revise** — **mismatch** — only a not-`FILED` filing that has already snapshotted the Schedule H line takes the delinquent `amount_cents`; a `DRAFT` filing keeps a null line, gets no value and no `version` bump — routes_payroll.py:231-237
- §3.5 Reversal — insert — ambiguity — `reversal_reason` required, ≥1 char, no maximum — routes_payroll.py:379
- §3.5 Reversal — insert — ambiguity — reversal touches no filing at all: an already-added Schedule H amount stays, a revoked employer-data branch stays revoked, and only a still-`DRAFT` filing reflects the reversal when prepared — routes_payroll.py:387-402
- §3.5 Computing the correction — insert — ambiguity — the non-`POSTED` case is reported as `ERR_DEPOSIT_INVALID_STATE` (the split the ladder implies), and `actual_investment_return_cents` must be ≥ 0 — routes_payroll.py:418-423
- §3.5 Computing the correction — insert — ambiguity — `correction_method`/`recovery_date`/`actual_investment_return_cents` are stored as given, only the deposit's `version` bumps, and nothing outside the deposit moves — routes_payroll.py:436-444
- §3.5 Funding the correction — insert — ambiguity — both halves of the state condition report `ERR_CORRECTION_INVALID_STATE`, never `ERR_DEPOSIT_INVALID_STATE`; `form_5330_reference` is 1–64 chars — routes_payroll.py:458-464
- §3.6 population — **revise** — **mismatch** — the population is `ACTIVE`/`SUSPENDED` only, so `EXIT_REQUESTED` and `SPINOFF_IN_PROGRESS` are excluded too, which empties an `EMPLOYER_LEVEL` population (→ `ERR_TEST_INVALID_STATE`) once the named employer has requested its exit — routes_compliance.py:21,27-36
- §3.6 coverage — insert — ambiguity — a coverage test never consults the exemption, so `exemption_applied` stays false and the three ADP fields stay null — routes_compliance.py:151-165
- §3.7 opening the return — insert — ambiguity — year uniqueness is judged against every filing whatever its status, and no plan-status gate applies at creation (a return may be opened on a `DRAFT` plan) — routes_compliance.py:266-283
- §3.7 Filing — insert — ambiguity — `acknowledgment_reference` is `ACK-` plus a six-digit zero-padded decimal drawn from a server-wide row sequence, so the digits are not derivable and no rule may depend on them — routes_compliance.py:445
- §3.8 exit request — insert — ambiguity — a `successor_plan_name` supplied on a `PLAN_TERMINATION_DISTRIBUTION` is stored; the plan's totals are recomputed and its `version` bumps even though no total changes value — routes_exit.py:69,107-109
- §3.8 approval — insert — ambiguity — the plan's totals are recomputed and its `version` bumps here too, again with no total changing value — routes_exit.py:147
- §3.8 reversal — insert — ambiguity — the FILED-filing check compares `plan_year` to the bare UTC calendar year of `settled_at`; `reversal_reason` shape; the waterfall figures are kept (they merely stop counting), the election stays `SUPERSEDED`, closed employer-level tests stay `CLOSED`, and `REVERSED` is terminal so the employer never returns to `ACTIVE` — routes_exit.py:216-237
- §3.9 allocation — insert — ambiguity — only employers with a credit > 0 are mutated (`version`/`updated_at` bump); zero-credit and non-eligible employers are untouched, and the plan document is never mutated by a disclosure — routes_exit.py:320-327

## The two Step 6 judgement calls — verdicts
1. **`fund-correction`'s compound `ERR_CORRECTION_INVALID_STATE`** — the PRD already said "failing which the request is rejected with `ERR_CORRECTION_INVALID_STATE`", which technically covers both halves, but §2.11 declares the ladder global and observable, so a reader could still infer priority 17 for a `PENDING` deposit. **Pinned explicitly** in §3.5 (funding) that both halves report `ERR_CORRECTION_INVALID_STATE` and never `ERR_DEPOSIT_INVALID_STATE`, and **pinned the counterpart split** in §3.5 (computing) where `ERR_DEPOSIT_INVALID_STATE` genuinely is reported. The asymmetry is now stated on both sides. Was under-determined, now unique; no impl change implied.
2. **Deposit reversal leaves `late_deposit_schedule_h_line_cents` untouched** — impl is right and the PRD's enumeration was suggestive but not explicit ("every plan control total is recomputed" does not reach filings). **Pinned** in §3.5 (reversal) that no filing is touched, the line keeps the delinquent amount, a revoked employer-data branch stays revoked, and the reversal only reaches the return through a filing still in `DRAFT` at its next preparation.

## Borderline items judged already pinned
- `_employer_balance` (routes_payroll.py:39-51) is a from-first-principles derivation while the PRD describes the balance incrementally. Every reachable path was enumerated (a `CORRECTED` deposit can never be reversed; a settled exit subtracts exactly the gross; a reversed exit rewrites the balance explicitly) and the two readings coincide in every reachable state, so the incremental prose was left alone.
- Cascaded `version`/`updated_at` bumps on the employer and plan for posting/reversal/funding are covered by §2.4's "including cascaded ones" plus §2.9's trigger list; prose was added only where impl bumps something §2.9's list does not cover (exit request, exit approval) or where the bump can happen with no value change (batch validation).
- Per-endpoint role lists in §4 and the ownership behaviour of `authz.own` for plan-level reads matched all nine routes' `authorize(...)` calls exactly.

## Closing statement
No behavior in routes_payroll.py, routes_compliance.py or routes_exit.py remains unpinned: every endpoint's gate sequence was walked against the 71-rung ladder (all nine transition endpoints raise in strictly ascending priority order, so the section prose and §2.11 agree), plus every state transition and cascade, every field written at create/transition time, every default, and every response shape. The only deviations from the bare ladder are the two compound/split correction-state checks, both now explicit in the prose.

## Step 9: Complete PRD — orchestrator verification and pipeline close — 2026-09-06T00:41:28.423927151Z

Step 9 aggregate across the three sequential passes: **40 ambiguity-pins + 8 mismatch-revisions = 48 changes.**

Orchestrator verification, independent of the subagents' claims:
- `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` — 77 changed lines, 111,454 → 127,451 chars (+14.4%). The scan genuinely ran; this was not a `cp`.
- Line counts: PRD.md 456 → PRD_FINALIZED.md 456 → PRD_COMPLETED.md 457. Every Step 9 edit is an in-paragraph insert/revision; no new sections, matching the skill's minimal-patch requirement.
- `PRD_COMPLETED.md` ends at the final row of the §5 error table — a real section boundary, not a truncation.
- `implementation/` mtimes all read 09-05 21:23–21:44, i.e. every source file predates the 23:32 green sweep. Neither Step 8 nor any Step 9 pass modified the implementation, so the 8×85/85 sweep result remains valid for the code as shipped.
- Exactly one `worklog.md` exists in the task tree (no stray copies from cwd drift).

Pipeline complete. Final state: 12 scaffold/design + doc artifacts, 85 tests passing in all 8 rounds, a 4321-line Python+Flask implementation with 60 endpoints, and PRD_COMPLETED.md as the ambiguity-free contract.
