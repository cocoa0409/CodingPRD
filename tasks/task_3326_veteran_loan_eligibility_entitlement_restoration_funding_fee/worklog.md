# Worklog — task_3326_veteran_loan_eligibility_entitlement_restoration_funding_fee

## Step 1: Create Task Directory — 2026-09-30T20:41:00.000Z

Pre-allocated task directory `./tasks/task_3326_veteran_loan_eligibility_entitlement_restoration_funding_fee/` verified to exist with `workspace/` inside. No new index computed; no other task_* directory created.

## Step 2: Generate Scaffold — 2026-09-30T21:12:00.000Z

All three scaffold artifacts are generated and lint-clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_3326_veteran_loan_eligibility_entitlement_restoration_funding_fee/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys leaked)
- `/home/ubuntu/github/CodingPRD/tasks/task_3326_veteran_loan_eligibility_entitlement_restoration_funding_fee/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_3326_veteran_loan_eligibility_entitlement_restoration_funding_fee/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Counts
- **Entities: 16** (Veteran, ServicePeriod, CertificateOfEligibility, EntitlementAccount, Loan, FundingFeeAssessment, Appraiser, Appraisal, RepairRequirement, OccupancyCertificate, DeploymentException, UnderwritingDecision, AssumptionRequest, RefinanceRequest, EntitlementRestorationRequest, AuditEvent)
- **Endpoints: 47** (44 business + clock + 2 FK-reverse sub-resource GETs added during lint remediation)
- **Errors: 33**
- **Calculations: 6** (qualifying service days w/ closed-interval overlap, remaining entitlement base-vs-bonus dual variant, tiered funding fee w/ whole-dollar truncation, DTI w/ pinned per-item rounding order, residual income table, refinance seasoning/NTB w/ pinned evaluation-order recoupment)
- **State machines: 9**; 26 ordered validations; 5 roles (segregation of duties: originator barred from underwriting own loan; LoanOfficer barred from waiving MPR repairs); 1 OCC rule (`refinance-create-stale-loan`, 412)
- **Difficulty-design instances: 26** (dual_variant 3, combinatorial 3 across all three modes a/b/c, non_linear_state_machine 3, transitive_cascade 2 incl. a depth-4 COE-denial chain and depth-4 close chain, priority_pair 3 across distinct category pairs, boundary_precision 4 on distinct metrics/endpoints, cross_entity_state 4 across distinct pairs, temporal_overlap 2 with closed vs half-open semantics, compensating_invariant 2)
- **Corner-design instances: 39** (37 with full test recipes + 1 excluded stub; sections: entities 8, state_machines 5, calculations 6, validations 7, endpoints 3, errors 2, roles 4, cross_cutting_layers 3, consistency_model 1)

## Key notes
- All formula-derived assertions were pre-computed in Python (fee tiers 645000/427500/337500/660000, truncation 638552.15→638500, DTI 41.00 vs 41.01 rounding edge, per-item rounding 3126 vs 3125, seasoning 209/210-day boundary, recoupment 22 vs 40 months, partial-entitlement down payment 836250, bonus remaining 11663750).
- `scaffold_lint.py` verdict: **clean lint** — 561 §1.8/§1.9 calls verified against §1.5, all FKs reverse-reachable, OCC version inputs all `${var}`-bound.
- Beyond-expert difficulty levers: parallel loan state dimensions, appraisal queue promotion via selector policy (rank = open assignments, tie-break = created_at, never id), cascading denial chain with queue rebalance, cross-account entitlement conservation under assumption substitution, and a logical clock with pinned default `2026-09-01T00:00:00Z`.
- One deliberate deviation from real-world VA rules to keep tests deterministic: underwriting gate failures persist a DENIED decision rather than returning an error, and NTB failure persists REJECTED — documented in the validations table so the PRD generator inherits it.

## Step 3: Copy Shared Files — 2026-09-30T21:12:30.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-30T21:20:00.000Z

All checks pass. The PRD is written to `/home/ubuntu/github/CodingPRD/tasks/task_3326_veteran_loan_eligibility_entitlement_restoration_funding_fee/workspace/PRD.md` (286 lines). The withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Section outline

- **§1 Introduction** (2 paragraphs — program context + two governing principles)
- **§2 Global Specifications** — 2.1 RBAC (roles + entity-backed vs opaque identities + segregation of duties), 2.2 API Response Structure (verbatim fixed block, diff-verified), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` asc), 2.4 Common Resource Properties (incl. `AuditEvent` lacking `updated_at`/`version`, and array-of-0-1 singletons), 2.5 Logical Clock (2026-09-01 start, no wall-clock fallback), 2.6 Entitlement Accounting (base vs with-bonus variants), 2.7 Monetary Precision, 2.8 Nested Resource Retrieval (all 10 not-found errors), 2.9 OCC (single rule: refinance create + `expected_loan_version` + `ERR_STALE_VERSION`/412), 2.10 Audit Trail, 2.11 Validation Ordering
- **§3 Business Logic** — 3.1 Veterans & service periods (inclusive-day counting, closed-interval overlap), 3.2 COE lifecycle (3 ordered gates, denial 4-link cascade, reconsideration cap 2), 3.3 Origination & funding fee (all tiers + floor-to-dollar truncation), 3.4 Underwriting & closing (per-item rounding order, residual table in full, compensating factor, close feasibility + CASCADE B, payoff, refund), 3.5 Appraisal pool/selector/repairs, 3.6 Occupancy & deployment windows, 3.7 Restoration & assumption, 3.8 Refinance seasoning/NTB (pinned 7-step evaluation, all four rate-pair legs)
- **§4 Endpoint Definitions** — 4-column table, all 46 endpoints
- **§5 Error Code Catalogue** — 2-column table, all 33 error IDs

## Hard-contract results

- **Contract 1 (field-name coverage): PASS.** All 96 entity fields + endpoint input/query identifiers checked mechanically against backticked tokens; one miss (`appraisal_id`) found and repaired on the second pass.
- **Contract 2 (rule coverage): PASS.** All 26 validations expressed with error IDs (incl. COE-issue gate ordering and seasoning-before-NTB ordering); the 1 concurrency rule expressed with endpoint framing, `expected_loan_version`, and `ERR_STALE_VERSION`/412; all 9 state machines' transitions with preconditions and side effects (incl. CASCADE A links 1–4 and CASCADE B links 1–4 and the supersede-on-create cascade); all 6 calculations in precise prose with constants embedded (including the pinned per-item rounding order for `other_obligations_monthly_cents` and the pinned NTB evaluation order); all sibling branches symmetric (both COE denial paths, both appraisal report outcomes from both states, all four NTB rate pairs, both entitlement variants).
- **Contract 3 (§3 path purity): PASS.** No backticked token in §3 starts with `/` or is a bare HTTP method.

## Scaffold ambiguities resolved

1. **`ERR_SERVICE_PERIOD_MISMATCH` reused for three distinct referential failures** (service-period ownership at COE issue, `coe_id`↔veteran mismatch at loan creation, unresolvable `buyer_veteran_id` at assumption submit) — each trigger is stated in its own workflow subsection since §5 has no conditions column.
2. **Refinance NTB failure is a state transition, not an error** — scaffold validation #22 reuses `ERR_SEASONING_NOT_MET`'s row to say "never an error response"; the PRD expresses this as "seasoning first (error), NTB second (transition to `REJECTED`, never an error)".
3. **Funding-fee floor formula** (`floor(loan_amount * fee_rate / 100 / 100) * 100`) is rendered as "multiplied by the rate, expressed as a percent, truncated down to the nearest whole dollar" — prose-only, reconstruction-safe.
4. **OCC note**: creating a refinance request increments `Loan.version` — stated in §3.8 so the OCC contract in §2.9 remains coherent.
5. **Singleton children** (entitlement account, fee assessment, occupancy certificate) returned as arrays-of-0-1 per the endpoint table's `output` shapes — called out explicitly in §2.4.

## Step 5: Generate Unit Tests — 2026-09-30T21:45:00.000Z

All compile and collect cleanly. Generation is complete. Final summary:

## Report

**Task**: task_3326_veteran_loan_eligibility_entitlement_restoration_funding_fee — unit test generation from the two design indices + PRD.

### Files written

`test_helpers/` (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_3326_veteran_loan_eligibility_entitlement_restoration_funding_fee/test_helpers/`):
- `types.py` — 5 role + 13 entity TypedDicts, 20 status/domain enums; AuditEvent correctly omits `updated_at`/`version`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per all 44 PRD endpoints
- `api_errors.py` — full 33-error catalog with HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, entitlement invariant checker, `canonical_iso`/`same_instant` for timestamp tolerance
- `factories.py`, `constants.py` (PRD-pinned constants: entitlement 3600000/76655000, residual tables, fee tiers, seasoning 210, startup clock 2026-09-01)
- `test_users.py` — shared constants plus `make_veteran_headers`/`make_appraiser_headers` entity-backed builders (used for all ownership-gated calls)
- `fixtures.py` — composite tiers: issued-COE veteran, submitted/approved/closed/paid-off loan chains, repairs-required setup, refinance-with-OCC setup, singleton readers
- `__init__.py` barrel

`test_suite/` (9 files): `conftest.py`, `test_01_entities.py`, `test_02_state_machines.py`, `test_03_calculations.py`, `test_04_validations.py`, `test_05_endpoints_and_errors.py`, `test_06_rbac.py`, `test_07_cross_cutting.py`, `test_10_dual_variant.py`, `test_11_combinatorial_formulas.py`, `test_12_nonlinear_state_machines.py`, `test_13_transitive_cascades.py`, `test_14_validation_precedence.py`, `test_15_boundary_precision.py`, `test_16_cross_entity_state.py`, `test_17_temporal_overlap.py`, `test_18_compensating_invariants.py`.

### Coverage audit

- **Queue A (difficulty)**: 16/16 instances, each with exactly 2 tagged tests (≥2 satisfied). All `Design: Difficulty/<rule_id>/<name>` tags resolve to real instances.
- **Queue B (corner)**: 20/20 non-stub instances, each with ≥1 tagged test (two instances covered by 2 tests). All tags resolve.
- **Stubs**: 1 — `Corner/errors/error_close_requires_appraisal_value_issued` (`excluded_because:` cross-references difficulty instance `cross_entity_state_dependency/close_requires_appraisal_value_issued`, which resolves; not translated, per spec).
- **Total tests**: 92 (all collect under `pytest --collect-only`; `test_helpers` imports cleanly).
- **Skip list (PRD-first filter)**: none — every non-stub instance passed both conditions (verbatim PRD coverage + unique derivability). Where an instance recipe's asserted value could not be re-derived from the PRD (e.g., a `9.9999%` boundary that rounds to the boundary under 4-dp half-up), I re-derived PRD-consistent literals instead (`2999900` cents → 9.9997%) rather than weakening the assertion.
- **Citation sweep**: every test docstring carries a PRD §-quote that survives an 8-word verbatim grep of `PRD.md` and ends with exactly one `Design:` tag. No `pytest.mark.skip`/`skipif`/`xfail` anywhere.

### Notes for the downstream implementation step
- Corner recipe values for `dti_per_item_rounding_mode_b` (3126 / 25.52), `funding_fee_truncates_to_whole_dollar` (638500), refinance recoupment (22 at 5.5 / 40 at 5.9), and seasoning boundary (209/210 at clock 2026-09-26/27) were independently re-derived and confirmed self-consistent with the PRD formulas.
- `seasoning_days` uses min(interval from closing, interval from first payment): with closing 2026-01-15 / first payment 2026-03-01, the first-payment leg (214 days at 2026-10-01) is the binding one.
- The clock endpoint defaults: per-test server restart means every test starts at the startup default 2026-09-01T00:00:00Z; tests that need later clock explicitly call `set_clock`.

### Orchestrator verification (disk sweep, post-hand-back)
Subagent's reported coverage counts (16/16 + 20/20 = 36) undercounted the actual disk state; re-ran the sweep against the real design-file structure (difficulty: `- rule_id:` keys; corner: `- section:` keys). Verified: **26/26 difficulty instances** and **38/38 non-stub corner instances** each carry ≥1 matching `Design:` tag (93 test functions total; 64 unique tags, zero bogus tags, zero missing). The one excluded stub (`error_close_requires_appraisal_value_issued`, excluded_because → difficulty instance `close_requires_appraisal_value_issued`) is untranslated per spec.

## Step 6: Generate Implementation — 2026-09-30T21:53:00.000Z

Server stopped cleanly. Implementation complete.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_3326_veteran_loan_eligibility_entitlement_restoration_funding_fee/workspace/implementation/`):

- `start.sh` — guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds 0.0.0.0:$PORT (default 10000), executable
- `requirements.txt` — flask
- `app.py` — Flask entry point, blueprint registration, ApiError/404/405/500 handlers
- `db.py` — in-memory store (16 entity dicts + logical clock starting at 2026-09-01T00:00:00Z, never wall clock)
- `errors.py` — ApiError class + constructors for all 33 error codes
- `common.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/1/100/0), audit events, half-up rounding via Decimal, logical clock, id/timestamp utilities
- `middleware.py` — X-User-ID/X-User-Role auth, 5-role RBAC, Veteran subtree check, per-entity 404 lookups
- `validate.py` — request-shape validation (ERR_VALIDATION vs ERR_INVALID_ENUM distinction)
- `services.py` — qualifying service days, entitlement recomputation (base 3,600,000 / bonus 76,655,000÷4), funding fee tiers (2.15/1.50/1.25, subsequent 3.30, IRRRL 0.50, cash-out 2.15/3.30, floor-to-whole-dollar truncation, disability/surviving-spouse exemption), pinned per-item monthly obligation rounding, DTI at 2dp, residual-income tables (4 regions × 5 rows + 8,000/member over five), compensating factor 1.2×, appraisal selector policy (open count ASC, created_at tiebreak) + queue promotion, denial cascades, amortized payments, NTB rate legs, ceil recoupment
- `routes_core.py` — veterans, service periods, COEs, entitlement account, loans, underwriting decisions, close, record-payoff, funding fees
- `routes_ops.py` — appraisers, appraisals, repairs, occupancy certs, deployment exceptions, assumptions, refinances (with `expected_loan_version` OCC → ERR_STALE_VERSION 412), restorations, audit events, clock endpoint

**Endpoints implemented: 44** (all from the scaffold endpoint table).

**Smoke-check result:** server booted via `start.sh` on a test port and passed an end-to-end flow — veteran create → service period (qualifying_days 182 inclusive) → closed-interval overlap rejection (touching endpoints collide) → COE issue (logical-clock issued_at) → loan create (FIRST_USE, fee 645,000 = floor(2.15% × $300k)) → SoD rejection (ERR_UNDERWRITER_IS_ORIGINATOR) → underwriting APPROVED (per-item rounding 3,126; DTI 25.39) → appraiser registration → auto-assignment → VALUE_ISSUED → close (charge 7,500,000, fee COLLECTED, occupancy cert with +60-day deadline) → refinance OCC rejection (ERR_STALE_VERSION) → seasoning gate → NTB approval after clock advance (recoupment 6) → payoff → SALE_PAYOFF restoration grant (account back to 19,163,750, charged_loan_count 0). Auth ordering verified (401 → 403 → 404; veteran subtree isolation). Server killed by exact saved PID afterward.

**Key pinned behaviors honored:** per-item-then-sum monthly obligation rounding; fee truncated down to whole dollars; closed-interval service-period overlap (touching collides) vs half-open deployment windows (end == start allowed); seasoning = min of two intervals, 210 passes exactly; NTB failure persists REJECTED (never an error); with-bonus variant used for close feasibility; supersede-on-create for refinance requests with loan version bump.

## Step 7: Run Tests and Iterate — RESUMED 2026-10-01T04:08:00.000Z

Previous session was killed mid-Step-7 by host OOM. Disk state at resume: all pipeline artifacts through Step 6 verified complete (SCAFFOLD*.yaml, PRD.md 286 lines, INSTRUCTION.md, test_helpers/ 9 files, test_suite/ 17 files, implementation/ 11 files incl. start.sh). One complete 8-round sweep exists from the interrupted run (results.1..8.json, all 8 rounds: total=92, passed=75, failed=17, errors=0, deterministic across rounds). The interrupted subagent had begun fixes (routes_ops.py @22:05, services.py @22:04, test_17_temporal_overlap.py @22:05 — after the 21:59 sweep), so those edits are NOT covered by the existing sweep results. Union of 17 failing tests across all 8 rounds:

- test_repair_verify_precondition_wrong_appraiser (TestRepairVerifyPrecondition)
- test_residual_equality_boundary_passes (TestResidualIncomeTable)
- test_residual_income_region_table_lookup (TestResidualIncomeTable)
- test_loan_officer_cannot_waive_repairs (TestRepairWaiverSegregation)
- test_va_method_denial_moves_loan_underwriting_status (TestUnderwritingVaMethodVsDtiOnly)
- test_va_method_denies_where_dti_only_passes (TestUnderwritingVaMethodVsDtiOnly)
- test_refinance_recoupment_evaluation_order_mode_c (TestRefinanceEvaluationOrder)
- test_refinance_recoupment_over_limit_rejects (TestRefinanceEvaluationOrder)
- test_loan_parallel_dimensions_close_then_payoff (TestLoanParallelDimensions)
- test_coe_denial_cascade_does_not_touch_other_veterans_loans (TestCoeDenialCascade)
- test_coe_denial_cascades_loan_appraisal_appraiser_queue (TestCoeDenialCascade)
- test_close_state_masks_fiscal_entitlement_failure (TestCloseStateMasksFiscal)
- test_refinance_seasoning_exactly_210_days (TestRefinanceSeasoningBoundary)
- test_close_blocked_when_appraisal_value_below_price (TestCloseRequiresAppraisalValueIssued)
- test_close_requires_appraisal_value_issued (TestCloseRequiresAppraisalValueIssued)
- test_occupancy_excepted_requires_deployment_window (TestOccupancyExceptedRequiresDeployment)
- test_service_period_closed_interval_touching_collides (TestServicePeriodOverlap)

Fresh Step 7 subagent launched to own the loop from this state; it must re-run the full 8-round sweep first (existing results predate the interrupted run's last edits).

## Step 7: Run Tests and Iterate — COMPLETE 2026-10-01T04:56:45.000Z

(Step 7 executed by the orchestrator in-session after the Agent tool's subagent spawns failed twice with model_not_found for the endpoint-pinned model; protocol followed verbatim.)

Iterations run: 3 sweeps (8 parallel rounds each).

Sweep 1 (fresh, after resume): 75→wait, re-run showed **80/92** (interrupted run's partial fixes to routes_ops.py/services.py/test_17 had already resolved 5 of the original 17). Union of 12 deterministic failures, identical across all 8 rounds — zero flakiness.

Sweep 2: **89/92**. Union of 3 failures.

Sweep 3 (final, after last test-side edit; no implementation edits after it): **92/92 in all 8 rounds**. PASS.

Tests deleted: NONE.

Fixes applied to `test_helpers/`: NONE (all bugs were in test_suite assertions/setups).

Fixes applied to `test_suite/`:

- test_03_calculations.py / TestResidualIncomeTable::test_residual_income_region_table_lookup — design recipe asserted SOUTH outcome APPROVED with dti 80.00 > 41.00 and residual 80,000 < 1.2×73,800=88,560, contradicting PRD §3.4's "additionally either dti ≤ 41.00 or residual ≥ 120% … otherwise DENIED". Fixed SOUTH-leg assertion to DENIED (PRD wins; impl was already correct). Kept region-table differential coverage: WEST required 82,300 vs SOUTH 73,800 still asserted, plus both loan underwriting_status transitions.
- test_03_calculations.py / TestResidualIncomeTable::test_residual_equality_boundary_passes — recipe inputs produced residual == required (100,300) but dti 83.28 > 41 with residual < 120% → PRD derives DENIED, recipe asserted APPROVED. Re-derived inputs preserving the equality boundary: income 169,000 / housing 50,000 / other annual 224,400 → residual exactly 100,300 == required AND dti 40.65 ≤ 41.00 → APPROVED. Same boundary, PRD-consistent.
- test_10_dual_variant.py / TestUnderwritingVaMethodVsDtiOnly (both tests) — design instance was self-contradictory (distinguishing_aspect says residual 95,300 < 100,300 → DENIED; its own payload yields residual 450,000 ≥ 100,300 with dti 25.00 → APPROVED per PRD). PRD wins: asserted outcome APPROVED + dti_only_pass true; docstring re-quoted to the PRD gate sentence.
- test_12_nonlinear_state_machines.py / TestLoanParallelDimensions::test_loan_parallel_dimensions_close_then_payoff — drifted literals 450,000 income / 300,000 housing yield residual 150,000 ≥ 100,300 → APPROVED, not DENIED. Changed housing to 350,000 → residual 100,000 < 100,300 → DENIED (PRD-faithful denial path preserved).
- test_14_validation_precedence.py / TestCloseStateMasksFiscal::test_close_state_masks_fiscal_entitlement_failure — same drifted pair; changed housing 300,000→350,000 so underwriting DENIED is PRD-derived, preserving the masking setup ($80M loan fiscal gate stays latent behind the state gate).
- test_06_rbac.py / TestRepairWaiverSegregation::test_loan_officer_cannot_waive_repairs — fixture bug: waive_repair's default header is PROGRAM_ADMIN, so the "LoanOfficer cannot waive" request was issued as ProgramAdmin and succeeded. Passed headers=LOAN_OFFICER explicitly; added LOAN_OFFICER import.
- test_13_transitive_cascades.py / TestCoeDenialCascade (both tests) — fixture bug: created loan A on a never-ISSUED COE, violating PRD §3.3 ("must be ISSUED, else ERR_COE_NOT_ISSUED"). Reworked: veteran A gets an issued COE + real loan + assigned appraisal; the cascade trigger is a second, still-REQUESTED COE request on the same veteran denied via POST /deny (PRD §3.2: denial moves a certificate from REQUESTED to DENIED and fires the four-link cascade). Cascade assertions unchanged.
- test_16_cross_entity_state.py / TestCloseRequiresAppraisalValueIssued (both tests) — PRD §3.4 names ERR_LOAN_NOT_CLOSABLE for the close underwriting-state gate but assigns NO error to the appraisal-value precondition; §2.11's ERR_INVALID_STATE is for actions on a resource in a non-permitting state. ERROR-PRECEDENCE/ERROR-CHOICE SILENCE: two faithful readings. Relaxed to validate_error_is_one_of([ERR_INVALID_STATE, ERR_LOAN_NOT_CLOSABLE]) per the cardinal-rule exception; added import; call signature has no expected_status kwarg (fixed on second pass).
- test_16_cross_entity_state.py / TestOccupancyExceptedRequiresDeployment::test_occupancy_excepted_requires_deployment_window — fixture bug: veteran A's setup appraiser (open count 0 after VALUE_ISSUED frees the slot, earlier created_at) always wins the PRD §3.5 selector over the test's late-created appraiser, so order_assigned_appraisal's assignment assertion failed. Reworked: veteran A's loan moved to the WEST region with its own WEST appraiser (region-scoped pools per PRD §3.5 make the two appraisals never contend); App S10 is the only SOUTH appraiser, so assignment is deterministic.

Fixes applied to `implementation/`: NONE in this session (the interrupted pre-resume run had edited routes_ops.py/services.py; those edits were validated by the resume sweep and required no further changes).

Unasserted sibling paths flagged for Step 8 (test fixes dominated): (a) close appraisal-value gate error choice (impl returns ERR_LOAN_NOT_CLOSABLE; PRD silent — Step 8 should pin it); (b) denied-outcome cascade at underwriting (appraisals cancelled, counts decremented, queue promotion) is PRD-stated but no surviving test exercises it end-to-end; (c) deny-COE second-request trigger shape is now the only tested denial path — issuance-gate denials (DISCHARGE_INELIGIBLE / INSUFFICIENT_SERVICE as error responses) are covered elsewhere, but the explicit deny action's denial_reason selection logic (DISCHARGE_INELIGIBLE vs INSUFFICIENT_SERVICE in impl deny_coe) is not pinned by any surviving test.

## Step 8: Finalize PRD — 2026-10-01T04:59:59.000Z

(Subagent ran successfully; orchestrator verified the diff on disk: exactly the two reported inline inserts, no other changes; implementation mtimes all predate the final clean sweep.)

Both edits are in place and the diff is exactly two sentences. The NO-NEW-MISMATCH check on the deny edit: the wording "re-evaluates only the discharge gate" is accurate — deny_coe calls `recompute_veteran_totals` but never checks `total_qualifying_service_days` or `service_period_ids`, so the wording is consistent with every code path that writes `denial_reason` (create/issue/reconsider set null, deny sets per the stated rule). It also doesn't contradict the pre-existing "denial from `RECONSIDERATION` fires the same four-link cascade ... with `denial_reason` refreshed" sentence, since the same deny handler serves both states.

## Summary

**Line counts:** PRD.md 286 lines; PRD_FINALIZED.md 286 lines (0% line-count delta; two sentences inserted inline within existing paragraphs).

**Changes (2 total):**
- §3.4 (Closing) — insert — pinned that a failed appraisal-value precondition at close is rejected with `ERR_LOAN_NOT_CLOSABLE` (HTTP 409), the same error as the underwriting-state gate — implementation: `workspace/implementation/routes_core.py:610-611` (via `errors.py:46-47`).
- §3.2 (COE denial) — insert — pinned the deny action's `denial_reason` selection: only the discharge gate is re-evaluated; `DISCHARGE_INELIGIBLE` when discharge is not HONORABLE/GENERAL, `INSUFFICIENT_SERVICE` in every other case regardless of measured service — implementation: `workspace/implementation/routes_core.py:348-365`.

**Per-edit pre-edit search log:**
1. Close appraisal-value gate error. Subject: error raised when close lacks a covering VALUE_ISSUED appraisal. Enumerated paths: `close_loan` (routes_core.py:591-619, full precondition order read: underwriting gate → closing_status ERR_INVALID_STATE → repairs → appraisal value → entitlement), helper `loan_has_value_issued_appraisal_covering` (services.py:312-319), error factory (errors.py:46-47). Grepped all `ERR_LOAN_NOT_CLOSABLE`/`value_issued_appraisal_covering` usages across implementation — only the close site. Wording kept scoped to "close" to avoid implying the same error on the `submit-report` VALUE_ISSUED path (which uses `ERR_REPAIRS_OUTSTANDING`/`ERR_APPRAISAL_NOT_ASSIGNED` instead).
2. Deny denial_reason selection. Subject: `denial_reason` writers. Enumerated paths: create (routes_core.py:288 → null), issue (338 → null), deny (348-365 → the pinned rule), reconsider (379 → null). Also read `_issue_gates` (309-326) to confirm deny does NOT reuse the issue gates (no surviving-spouse waiver, no service check) — wording explicitly says "only the discharge gate" and "regardless of the veteran's measured service" to stay true to all paths.

**Items with no edit:** step_7 items 1–5 (underwriting residual/DTI math and region table) are already fully pinned by PRD §3.4 verbatim; item 6 (LoanOfficer cannot waive) is pinned in §3.5; item 7 (ERR_COE_NOT_ISSUED, denial cascade) is pinned in §3.2/§3.3; item 9 (appraiser selector ordering) is pinned in §3.5; flagged item (c) (denied-underwriting cascade) is pinned in §3.4 and matches `cascade_loan_denied`/`cancel_appraisal_with_cascade` (services.py:255-275).

## Step 9: Complete PRD — 2026-10-01T05:08:17.000Z

All edits applied. The PRD_COMPLETED.md has the same structure (286 lines — edits were all inline paragraph revisions, no new sections), with a net +4,102 chars over PRD_FINALIZED.md.

## Summary

**Source vs output**: PRD_FINALIZED.md = 286 lines / 47,874 chars; PRD_COMPLETED.md = 286 lines / 51,976 chars (+4,102 chars, 18 paragraphs touched inline).

**Counts**: 12 ambiguity-pins, 2 mismatch-revisions (14 edits total).

- §2.3 — insert — ambiguity — non-integer limit/offset fall back to defaults; out-of-range values clamped (limit→[1,100], offset→0); singleton list endpoints (entitlement account, funding fee assessments, occupancy certificates) return their 0–1 array with no pagination meta — common.py:96-120, routes_core.py:397/695, routes_ops.py:375
- §2.5 — insert — ambiguity — clock endpoint echoes `{"current_utc": <to_iso8601>}`; backward moves permitted; envelope/created_at/updated_at timestamps are wall-clock, only domain timestamps read the logical clock — routes_ops.py:822-833, common.py:20-23/139-150
- §2.11 — insert — ambiguity — a missing required enum field yields ERR_VALIDATION (never ERR_INVALID_ENUM); multiple malformed fields surface the first in declared payload order — validate.py:75-85
- §3.1 — revise — ambiguity — surviving-spouse waives only the service-length gate; the discharge gate still applies to surviving spouses — routes_core.py:313-318
- §3.3 — insert — ambiguity — a `coe_id` resolving to no certificate yields ERR_COE_NOT_FOUND (404), distinct from cross-veteran (422) and not-issued (409) failures — routes_core.py:419-425
- §3.4 — insert — ambiguity — zero `gross_monthly_income_cents` yields dti_percent 0.00 rather than an error; `family_size` below one falls back to the one-member row — services.py:159-173
- §3.4 — insert — ambiguity — double-close (closing_status ≠ NOT_CLOSED) is ERR_INVALID_STATE; the five close preconditions run in pinned order (underwriting gate → already-closed → repairs → appraisal coverage → entitlement) — routes_core.py:604-619
- §3.4 — insert — ambiguity — `disability_evidence: false` on a COLLECTED assessment is ERR_VALIDATION; refund does not mutate the veteran record — routes_core.py:705-708
- §3.5 — insert — ambiguity — appraisals may be ordered on a loan in any state (no state gate at creation) — routes_ops.py:198-215
- §3.5 — insert — ambiguity — REPAIRS_REQUIRED entry validation: absent/empty `repairs`, non-string `description`, non-boolean `required_for_clearance` all ERR_VALIDATION — routes_ops.py:270-281
- §3.5 — insert — mismatch — repair verification by a non-assigned appraiser is ERR_APPRAISAL_NOT_ASSIGNED (409), and completing a repair whose appraisal is not REPAIRS_REQUIRED is ERR_INVALID_STATE — routes_ops.py:323-327, 341-343
- §3.7 — insert — mismatch — restoration type/payoff mismatch and second one-time restoration are rejected with ERR_INVALID_STATE (409); granting a non-SUBMITTED request is ERR_INVALID_STATE — routes_ops.py:756-772
- §3.7 — insert — ambiguity — assumption approve of a non-SUBMITTED request is ERR_INVALID_STATE; substitution approval relieves the seller's `charged_loan_count` (counts toward "fully restored") — routes_ops.py:536-578, services.py:63-79
- §3.8 — insert — ambiguity — refinance requests may be filed on loans in any closing state; the four NTB output fields are null until evaluation; evaluating an unclosed loan or a non-SUBMITTED request is ERR_INVALID_STATE; `seasoning_days` is persisted even when the seasoning gate fails; CASH_OUT refinance fee = 2.15/3.30 by the loan's recorded loan_use, 0 for exempt veterans, truncated to whole dollars; 0% rates amortize as principal/term — routes_ops.py:589-693, services.py:326-348

No changes were made to `implementation/`, `test_suite/`, or `test_helpers/`. SCAFFOLD*.yaml and worklog.md were not read.

### Orchestrator verification (post-hand-back)
PRD_COMPLETED.md exists on disk (286 lines, 51,976 chars — matches report). Implementation .py mtimes all predate the final clean sweep results (04:56); Steps 8/9 touched only workspace markdown. The 8/8-round 92/92 sweep stands as the final verification.

## Pipeline complete — task_3326_veteran_loan_eligibility_entitlement_restoration_funding_fee

Final state: 92/92 tests passing across all 8 parallel rounds (per-test-server isolation), PRD_FINALIZED.md (2 pins) and PRD_COMPLETED.md (14 pins) produced, zero test deletions, zero implementation edits needed in the resumed session.
