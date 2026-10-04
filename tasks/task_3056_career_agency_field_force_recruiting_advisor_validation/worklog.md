# Worklog: task_3056_career_agency_field_force_recruiting_advisor_validation

Scenario: Career Agency Field Force Recruiting & Advisor Validation (Northwestern Mutual) — campus and career-changer recruiting pipelines with selection assessments, financial representative contracts with training allowances and validation production requirements, managing director and district office overrides on team production, joint work and split-case credit allocation between representatives, product licensing and appointment sequencing across insurance and securities registrations, persistency measurement affecting compensation and renewal commissions, chargeback of advanced commissions on lapsed policies, advisor termination with orphan policyholder reassignment

## Step 1: Create task directory — 2026-09-30T00:00:00.000Z

Task directory pre-allocated by caller; verified `./tasks/task_3056_career_agency_field_force_recruiting_advisor_validation/workspace/` exists and is empty. No new task_* directory created (index computation skipped per caller instruction). `./INSTRUCTION.md` present at project root.

## Step 2: Generate scaffold — 2026-09-30T00:05:00.000Z

Done. All three artifacts are generated, self-consistent, and lint-clean.

## Files (absolute paths)

- `/home/ubuntu/github/CodingPRD/tasks/task_3056_career_agency_field_force_recruiting_advisor_validation/SCAFFOLD.yaml` — 2,404 lines (§1.0–§1.7; no `scaffold_difficulty_design`/`scaffold_corner_design` key)
- `/home/ubuntu/github/CodingPRD/tasks/task_3056_career_agency_field_force_recruiting_advisor_validation/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1,544 lines (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_3056_career_agency_field_force_recruiting_advisor_validation/SCAFFOLD_CORNER_DESIGN.yaml` — 1,870 lines (single top-level key `scaffold_corner_design`)

No sibling `task_*` directory was read, listed, or grepped; nothing was written into `workspace/`.

## §1.1–§1.7 counts

| Table | Count |
|---|---|
| Entities (§1.1) | 14 |
| State machines (§1.2) | 11 (76 transitions) |
| Concurrency rules (§1.2.1) | 3 (all OCC, all `expected_*_version` + parent-version bump verified) |
| Calculations (§1.3) | 8 |
| Validations (§1.4) | 10 (ordered priorities 1–10) |
| Endpoints (§1.5) | 96 |
| Errors (§1.6) | 50 |
| Roles (§1.7) | 7 (5 `entity_backed:Advisor`, 2 `opaque`) |

## Difficulty target: pushed past expert

- **Profile**: `graph` topology × `posture_driven` state shape × `hierarchical_override` roles × 4 complexity layers (OCC, cascading side effects, dual-variant calc, rate/threshold triggers).
- **State machines** are cyclic (candidate `OFFER_DECLINED→REENGAGED` loop, `VOIDED→OPEN` joint cases, `DISPUTED→PROVISIONAL` persistency, `EXTENDED→OPEN` windows), parallel (four independent dimensions on one Advisor row), self-referential (`sponsoring_advisor_id`, `prior_candidate_id`, `prerequisite_registration_id` DAG), and branching (assessment fork: SUPERSEDE vs INVALIDATE with distinct side effects).
- **Cascades reach depth 5** (ValidationPeriod → EmploymentContract → Advisor posture → sponsor override → DistrictOffice aggregate), all hop-caused.
- Two dual-variant calcs on **different entity domains** (assessment weight tables vs. employment-contract allowance draw); two combinatorial calcs in **different modes** (nested rounding order vs. tier-selection chain); two validations in **different categories** (auth vs. existence; business_safety vs. business_fiscal); two overlap rules in **different interval semantics** (half-open licences allow boundary touch, closed windows/registrations reject it).

## §1.8 / §1.9 instance counts

- **§1.8**: 9 `rule_id` blocks × 2 instances = **18 instances**; every rule at its §0.5 minimum, every `${var}` bound by an earlier `captures:`, every numeric assert executed as Python against the declared formula (e.g. `8.29`/`7.69` divergence, `8.88` vs `8.87` rounding order, `204000`/`122400`/`81600` split conservation, `6120`/`4080`/`10200` override chain, `153000` chargeback proration).
- **§1.9**: 9 sections, **34 instances** (33 with structured `setup_api_calls`/`trigger`; 1 `excluded_because` stub pointing at the §1.8 instance `contract_validation_cascade_of_depth_four`). Two-way §1.5 audit added `GET /agency/securities-registrations/{id}/dependents` plus FK reverse-reachability GETs.

## Verification

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5
and all §1.1 FKs have reverse-reachability in §1.5.
```

662 calls scanned across §1.8+§1.9; independently re-verified: 0 unbound placeholders, 0 dangling `grounds:`, unique instance names across both design files, no §1.2.1-forbidden vocabulary in any of the three files.

One caveat worth flagging for the downstream generators: the scaffold pins several deliberately interlocking semantics (round-then-sum assessment scoring, descendant-eligibility-by-contract-status for overrides, half-open vs closed interval boundaries, the `licensing_locked` suppression flag) — these are stated explicitly in §1.3 and §1.2 so the PRD/tests/implementation inherit the same reading rather than inventing a rival one.

## Step 3: Copy shared files — 2026-09-30T00:07:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3056_career_agency_field_force_recruiting_advisor_validation/workspace/INSTRUCTION.md` (1424 bytes, identical).

## Step 4: Generate PRD — 2026-09-30T00:16:00.000Z

The PRD is complete and all three hard contracts verified mechanically. Here is my closing report.

## Output

- **Path**: `/home/ubuntu/github/CodingPRD/tasks/task_3056_career_agency_field_force_recruiting_advisor_validation/workspace/PRD.md`
- **Length**: 449 lines, ~1,282 backticked tokens (397 unique), §4 table with 96 endpoint rows, §5 table with 50 error rows. No placeholder markers remain.

## Section headings produced

**§1** Introduction
**§2** Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim contract, byte-identical to `section-2.2-response-structure.md`); 2.3 Pagination; 2.4 Field Hierarchy, Sponsoring Chains, and Pipeline Lineage; 2.5 Common Resource Properties; 2.6 Optimistic Concurrency Control on Parent-Anchored Writes; 2.7 Money, Rounding, and the Credit Ledger Invariants; 2.8 Interval and Window Conventions; 2.9 Derived Postures and the Parallel Licensing Dimensions; 2.10 Validation Evaluation Order and Error Precedence; 2.11 District Office Structure and Override Parameters
**§3** Business Logic & Workflows — 3.1 Recruiting a Campus or Career-Changer Candidate; 3.2 The Assessment Fork: Scoring, Superseding, Invalidating, and Re-engaging; 3.3 Contracting an Accepted Candidate and the Training Allowance Ledger; 3.4 Validation Windows, Production Attainment, and the Contract Lifecycle; 3.5 Insurance Licensing, Securities Registration, and Appointment Sequencing; 3.6 Writing Business: Commission Allocation, Overrides, and Chargebacks; 3.7 Persistency Measurement and Renewal Income; 3.8 Termination and Orphan Policy Reassignment
**§4** Endpoint Definitions; **§5** Error Code Catalogue

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 104 required, 104 present, 0 missing
- endpoints[].request_body: 70 required, 70 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
- endpoints[].path_params: 0 required, 0 present, 0 missing
- state enumeration values: 46 required, 46 present, 0 missing
- enum-type field values: 92 required, 92 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 10 checked, 10 expressed in prose (explicit ordering statement in §2.10), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 named), 0 missing
- state_machines[].transitions: 60 checked, 60 fully expressed (from/to named, preconditions paired with error_ids, side_effects stated), 0 missing
- calculations[]: 8 checked, 8 fully expressed with pinned evaluation order, constants, and precision, 0 missing
- validations[] conditions: 10 checked, 10 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 96 / 10 checked, all expressed, 0 missing
- entities[].fields[] structured content: 104 checked, 104 reconstructible from prose, 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 894
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Cross-entity cascades — how they were handled

Rather than compressing cascade depth into single clauses, I rendered each cascade as an explicitly numbered depth chain with every branch stated. Cascade #1 (contracting) names all four consequences plus the explicit negative — no `ProductLicense`/`SecuritiesRegistration`/`CarrierAppointment` rows are created, all three dimensions begin at `NONE`. Cascade #3 (joint-case submission) is rendered to depth three: credit re-split → both advisors' team production → sponsoring advisors' override income → district-office override cap. Termination is rendered as a complete enumerated set of nine side effects, with each sub-cascade's guard (e.g. only `ISSUED`/`ACTIVE` policies orphan; only `ACCRUED`/`RENEWAL` credits voided). The lapse cascade carries the depth-two override reassessment, and the reinstate compensator states its asymmetry plainly (assessed resets but `recovered_cents` is unchanged, leaving the advisor in credit by the recovered amount). Both the happy and failure branches of the orphan selector are rendered with equal density — empty pool gives `REJECTED`/`NO_ELIGIBLE_ADVISOR` and the policy stays `orphaned`, never silently no-ops. Where the scaffold had compressed siblings (`ACTIVE→SURRENDERED` vs `LAPSED→SURRENDERED`, and the four termination-source transitions), I expanded each branch separately and stated whether it writes a further assessment.

## Error precedence — how it was handled

§2.10 states the single evaluation order explicitly: auth → existence (path left-to-right, then body in declared input order) → state (`ERR_INVALID_STATE`, `ERR_ALREADY_TERMINAL`) → structural payload → compliance → posture/interval → fiscal → uniqueness → temporal. I stated the two consequences concretely (a doubly-blocked request reports the licence error, not the posture error; a licence failure pre-empts the chargeback-balance block). The OCC race semantics are stated as a separate paragraph that explicitly pre-empts the state path: a stale `expected_candidate_version`/`expected_contract_version`/`expected_policy_version` yields `ERR_STALE_VERSION` at 412 even when the parent's state would independently have satisfied preconditions, and the endpoint that does not pin a version accepts no version field at all.

## Step 5: Generate unit tests — 2026-09-30T00:41:00.000Z

Done. Full report below.

## Files created

**`test_helpers/`**

| File | Lines |
|---|---|
| `types.py` | 484 |
| `api_client.py` | 357 |
| `api_errors.py` | 130 |
| `assertions.py` | 338 |
| `constants.py` | 95 |
| `factories.py` | 153 |
| `test_users.py` | 59 |
| `fixtures.py` | 606 |
| `__init__.py` | 26 |

**`test_suite/`**

| File | Lines |
|---|---|
| `conftest.py` | 48 |
| `test_01_assessment_scoring.py` | 167 |
| `test_02_training_allowance.py` | 153 |
| `test_03_recruiting_pipeline.py` | 125 |
| `test_04_licensing_sequencing.py` | 383 |
| `test_05_cascades_and_ledgers.py` | 319 |
| `test_06_persistency.py` | 104 |
| `test_07_boundaries_and_terminals.py` | 237 |
| `test_08_invariants.py` | 222 |
| `test_09_permissions_and_violations.py` | 331 |
| `test_10_precedence_and_reads.py` | 182 |
| `test_11_candidate_and_case_states.py` | 168 |

Nothing was written under `workspace/`.

## Totals
- **77 test functions** — all collected cleanly (`pytest --collect-only`: 77 collected, 0 errors).
- **77 docstring tags**, every one pointing at a real instance from the source yaml; 0 bad tags, 0 untagged, 0 dual-tagged, 0 `skip`/`skipif`/`xfail`.
- **Every one of the 77 PRD citations is verbatim** — a sliding ≥8-word window of each quoted span survives a literal `grep` of `PRD.md` (0 failures). No generated file mentions "scaffold"/table references.
- Live execution could not be exercised: `task_3056` has no `workspace/implementation/`, so tests fail only at the first HTTP call (connection refused). Collection, imports, and name resolution were all verified.

## Queue A — `SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8
**18 of 18 instances emitted, each with ≥2 tagged tests.** None skipped.

- `dual_variant_calc`: `selection_assessment_v1_vs_v2_weight_tables` (3 tests), `training_allowance_flat_vs_production_draw` (3)
- `combinatorial_formula`: `assessment_intermediate_rounding_order_pinned` (3), `persistency_tier_selection_chain_with_renewal_base` (2)
- `non_linear_state_machine`: `recruiting_pipeline_cycle_and_reengagement` (5), `licensing_parallel_dimensions_and_registration_dag` (5)
- `transitive_cascade`: `contract_validation_cascade_of_depth_four` (3), `policy_lapse_cascade_to_chargeback_ledger` (3)
- `boundary_precision_check`: `duplicated_live_credit_boolean_boundary_at_validation` (3), `empty_orphan_candidate_pool_returns_422` (2)
- `cross_entity_state_dependency`: `securities_activation_gated_by_prerequisite_registration` (3), `policy_activation_gated_by_advisor_licensing_dimensions` (2)
- `resource_temporal_overlap`: `product_licence_half_open_interval_no_overlap_at_boundary` (4), `securities_registration_closed_interval_overlap_at_boundary` (4)
- `compensating_invariant`: `reinstatement_preserves_only_unrecovered_chargeback_balance` (3), `joint_case_void_restores_the_primary_credit_exactly` (4)
- `priority_pair_validation_conflict`: `missing_header_beats_unknown_resource_on_scoring` (2), `licence_compliance_beats_chargeback_fiscal_on_policy_write` (2) — both survivors of the filter below

## Queue B — `SCAFFOLD_CORNER_DESIGN.yaml` §1.9
**25 of 33 non-stub instances emitted** (one test each). The 1 `excluded_because:` stub (`cross_cutting_complexity_layers/cascading_side_effects_and_dual_variant_coverage_are_claimed_by_difficulty_design`, pointing at `contract_validation_cascade_of_depth_four`) was verified to resolve and was correctly **not** translated.

Emitted: `assessed_surrender_assesses_the_full_gross_commission`, `persistency_tier_boundaries_at_95_and_90`, `training_allowance_draw_pauses_once_the_product_requirement_is_met`, `override_income_is_min_capped_by_the_office_cap`, `override_income_fully_recomputes_on_termination_of_a_downline`, `chargeback_balance_above_threshold_blocks_new_policy_activation`, `second_overlapping_validation_window_is_rejected`, `licence_compliance_error_precedence_on_appointment_approval`, `policies_can_be_filtered_to_the_orphaned_set`, `district_office_close_is_refused_while_live_advisors_remain`, `training_allowance_draw_beyond_the_total_is_rejected`, `duplicate_policy_number_is_rejected_as_a_natural_key_conflict`, `recruiting_officer_cannot_create_a_district_office`, `financial_rep_cannot_terminate_an_advisor_or_pay_a_credit`, `only_the_lead_advisor_may_submit_their_own_joint_case`, `stale_expected_candidate_version_blocks_contract_creation`, `derived_posture_fields_are_reconciled_on_read_after_a_cascade`, `joint_case_split_credit_is_visible_in_the_submit_response_state`, plus `candidate_reject_from_offer_extended_is_allowed_and_invalidates_assessment`, `terminal_candidate_admits_no_further_stage_change_except_reengagement`, `campus_candidate_cannot_be_screened_without_campus_name`, `advance_to_interview_blocked_by_a_failing_latest_assessment`, `assessment_scoring_requires_all_four_competency_keys`, `joint_work_case_submit_and_reopen_cycle`, `validation_period_extension_loop_is_capped`.

**8 skipped** — all under `section: entities`, each failing the PRD-first two-condition filter:

| Instance | Skip reason |
|---|---|
| `district_office_create_returns_every_declared_field` | Asserts `override_rate_pct == 0.05` / `override_cap_cents == 300000` server defaults. PRD only calls these client-optional ("defaulting to 0.05"); an implementation may echo `null` while applying the rate internally. Not uniquely derivable. |
| `district_office_get_round_trips_the_stored_configuration` | Same default-derivability problem (`override_paid_cents == 0` is separately derivable, but the instance's core claim is the stored-configuration round-trip including defaults). |
| `advisors_list_paginates_with_total_count_and_has_more` | Requires the query parameters `district_office_id`, `rank`, `limit`, `offset` on a list endpoint. PRD §4 states "Request bodies, response bodies, query parameters, and side effects are deliberately omitted here"; the only list semantics PRD pins are the four `meta` pagination fields. The exact row counts are not derivable. |
| `policy_get_with_an_unknown_id_returns_policy_not_found` | PRD never states an entity-specific `ERR_POLICY_NOT_FOUND` for a **GET by id**; §2.4 scopes its not-found list to path-validation "whenever a request path contains more than one resource identifier". An implementation could faithfully return a generic not-found here. |
| `employment_contract_create_missing_validation_requirement_returns_invalid_request` | Asserts the *specific* error id `ERR_INVALID_REQUEST` for a single omitted field. PRD §2.10 says a missing required body field "is reported as `ERR_INVALID_REQUEST` where the enum or field is simply malformed" — the hedged clause leaves the id open. |
| `advisor_status_and_posture_are_computed_at_creation_and_input_ignored` | PRD never states that a client-supplied `contract_status`/`validation_posture`/`version` is ignored; the read-only nature of the advisor list isn't enough to pin the *create-ignores-input* outcome. |
| `advisor_create_with_an_out_of_enum_rank_returns_invalid_request` | Same hedged `ERR_INVALID_REQUEST` derivability problem as the omitted-field instance. |
| `advisor_sponsoring_chain_is_self_referential_and_cycle_rejected` | **PRD-silent on the asserted half.** PRD states the cycle *refusal* (`ERR_SPONSORING_CYCLE_DETECTED`) but never states that a downline read returns *direct* reports only; the instance's distinguishing claim (the REP absent from the MD's downline) has no PRD coverage. |

## PRD-silent / not-uniquely-derivable instances (summary)
- **PRD-silent:** the downline "direct sponsorship only" behaviour (blocks one corner).
- **Not-uniquely-derivable:** server-side default field values; list-endpoint query-parameter filtering and its exact row counts; the concrete id behind the hedged `ERR_INVALID_REQUEST`; entity-specific not-found on single-identifier paths; create-time input-ignoring for computed fields.
- Two difficulty instances are emitted but with one deliberately dropped assertion each, for the same reason (the yaml's own trailing asserts are not derivable and were not translated): `training_allowance_flat_vs_production_draw`'s claim that `recruiter_override_cents` "is NOT posted as a CommissionCredit row" (absences are never pinned by PRD), and `licensing_parallel_dimensions_and_registration_dag`'s dependents-read exact-row-count (list filtering omitted from PRD).

## Step 6: Generate implementation — 2026-09-30T04:18:00.000Z

The implementation is complete. Here is my summary.

## Deliverables

All files under `/home/ubuntu/github/CodingPRD/tasks/task_3056_career_agency_field_force_recruiting_advisor_validation/workspace/implementation/`:

| File | Lines | | File | Lines |
|---|---|---|---|---|
| `app.py` | 58 | | `services/derived.py` | 232 |
| `db.py` | 111 | | `services/licensing.py` | 354 |
| `errors.py` | 131 | | `services/policies.py` | 372 |
| `middleware.py` | 168 | | `services/contracts.py` | 339 |
| `response.py` | 49 | | `services/jointwork.py` | 207 |
| `routes/*.py` (7 files + `_shared`) | 985 | | `services/recruiting.py` | 153 |
| `services/calc.py` | 222 | | `services/persistency.py` | 174 |
| `services/assessment.py` | 82 | | `services/serialize.py` | 155 |
| `services/advisors.py` | 193 | | `services/orphans.py` | 98 |
| | | | **total Python** | **4,283** |

Plus `start.sh` (9 lines, `exec`s the server, guards `pip install`) and `requirements.txt`.

## Endpoints
- **96 endpoints registered / 96 routes** — matches the scaffold §1.5 table exactly (verified by enumerating `url_map`).
- Storage is pure in-memory dicts; no seeding anywhere. Verified that `start.sh` re-invocation drops a created office (1 → 0) and the clock resets to `2026-09-01T00:00:00.000Z`.

## OCC
`expected_candidate_version` / `expected_contract_version` / `expected_policy_version` are checked **at the top of the service**, immediately after body-FK existence resolution and *before* the state path (`services/contracts.py`, `services/jointwork.py`). A mismatch raises `ERR_STALE_VERSION` (412) unconditionally, so a stale pin wins over an independent state failure — the §2.10 pre-emption. Confirmed: a stale pin on a `NOT_CONTRACTED` advisor still returns 412, not a state error.

## Error precedence (§2.10)
Encoded as an explicit order in each service body rather than by decorator stack: auth context → RBAC → path-existence left-to-right → body-FK existence in declared input order → state → structural payload (`ERR_INVALID_REQUEST`, and the specific `ERR_ASSESSMENT_INCOMPLETE_SCORES` / `ERR_SPLIT_PCT_INVALID` / `ERR_SELF_JOINT_CASE`) → business rules in the fixed sub-order **compliance → posture/interval → fiscal → natural-key → temporal**. This required moving all `required(...)` field checks out of the routes into the services (routes now only pass the body through), otherwise a missing field would 400 before a nonexistent parent 404. Two precedence cases the tests probe were fixed specifically: `/policies/{id}/activate` now checks the licensing gate before the chargeback-balance block, and `/orphan-policy-assignments/{id}/assign` reports `ERR_NO_ELIGIBLE_ADVISOR` (422) while still leaving the assignment `REJECTED`/`NO_ELIGIBLE_ADVISOR` and the policy orphaned.

## Cascades
- **Termination**: one pass over contracts/windows/licences/registrations/appointments/policies (orphan-assignment creation)/joint cases/renewal credits, then a full `cascade_rollups()` (team production → overrides → office ledger) plus chargeback-balance recomputation.
- **Overrides** are always **fully recomputed**, never incremented, in the pinned 4-step order (own posture gate → descendant `contract_status == VALIDATED` filter → per-credit rank accrual round-then-sum → single sum-then-cap last).
- **Joint submit/void** re-runs the waterfall; void restores the PRIMARY row to `credit_pct 1.00` and zeroes the SPLIT rows.
- **Lapse/surrender** assess every PAID/ACCRUED credit, then recompute balances for the credit's advisor *and its ancestors*.

## Verification
`prd-bench-local-run --isolation per-test-server`: **72/77 pass, 0 errors**. Of the 5 failures, **4 are defects in the generated test suite**, not the implementation:
- `test_chargeback_balance_above_the_block_refuses_new_policy_activation` and `test_closing_an_office_with_live_advisors_is_refused` → `NameError` (missing `fetch_policy` / `setup_contracted_rep` imports in those test modules; both names exist in `test_helpers/fixtures.py` and are imported by other files).
- `test_a_rejected_candidate_may_also_be_re_engaged` → asserts against an id never returned by any request in the test (verified by tracing every body and response id; the same helper pattern passes in sibling test files).
- `test_securities_activation_also_drives_the_prerequisite_dag_case_for_series_sixty_five` → asserts `insurance_license_status == "PENDING"` after a licence was activated; PRD §3.5 says activation "sets the advisor's `insurance_license_status` to `ACTIVE`". The implementation follows the PRD.

The fifth, `test_rounding_case_outcome_is_pass_and_locked_table_is_v1`, asserts 8.87 for competencies (9,9,8,9) under V1. The PRD's own text (line 170) states verbatim that the pinned order yields **8.88** while "adding first and rounding afterwards is a different, incorrect reading that shifts results by a cent". I implemented the pinned reading; all three of the scaffold's worked examples reproduce exactly (8.29/8.88/7.69).

## Ambiguities found in the PRD
1. **Assessment selection order** (§3.1): "latest by `scored_date` descending". Because `scored_date` is set to the logical clock, which is frozen between `/_clock` calls, several assessments normally share a timestamp. I implemented "latest" as the most recently *created* assessment, with `created_at` ascending as the declared tie-break — the reading that makes the declared tie-break meaningful.
2. **`Quantity shortfall`**: `PersistencyRecord.renewal_base_cents` is summed over the advisor's policies "ACTIVE at the instant of `measurement_end` within the CLOSED window". The PRD gives no issue-date/lapse-date predicate, so I sum over currently-ACTIVE policies whose issue falls inside the window; the evident test case has a single ACTIVE policy, so this is untested.
3. **Window vs. createdAt consistency**: `ValidationPeriod` bounds and credit `created_at` are both real timestamps supplied by tests, but the clock is frozen at the default when validation windows are opened — attainment therefore depends on tests setting the clock consistently with their window bounds, which the PRD does not call out.
4. **`ERR_NO_ELIGIBLE_ADVISOR`**: §3.8 describes the empty-pool outcome as both a success-shaped `REJECTED` record and "the same `ERR_NO_ELIGIBLE_ADVISOR` condition the error catalogue carries, reported at the unprocessable-entity status". I persist the `REJECTED` record and then raise the 422 error.

## Step 7: Run tests and iterate — 2026-09-30T05:00:00.000Z

All fixes verified. The task is complete with a clean 8-round sweep.

## Summary

**Iterations run:** 2 (baseline sweep + one fix sweep).

**Baseline (verified myself, STEP 0):** 72/77 in all 8 rounds — the 5 failures were fully deterministic, identical across every round (no flakiness).

**Tests deleted:** none. Every failure traced to PRD-covered, uniquely-derivable rules; three were test-artifact bugs and two were test-module import bugs.

**Fixes applied to `test_helpers/`:**
- `assertions.py` — `assert_scored_against_weight_table` used Python's built-in `round()` (float half-to-even), which read the §3.2 pinned example (competencies 9, 9, 8, 9 under V1) as 8.87. PRD line 170 states verbatim the pinned order yields **8.88** (avg 8.750 → weighted component 6.125 → **6.13** half-up). Replaced with explicit Decimal `ROUND_HALF_UP` helpers. This was the sole cause of the `test_rounding_case_outcome_...` failure — the *implementation* was already correct at 8.88; the test's expected-value computation was the bug. Also updated the module import line.

**Fixes applied to `test_suite/`:**
- `test_05_cascades_and_ledgers.py` — added missing `fetch_policy` import (NameError in `test_chargeback_balance_above_the_block_refuses_new_policy_activation`).
- `test_09_permissions_and_violations.py` — added missing `setup_contracted_rep` import (NameError in `test_closing_an_office_with_live_advisors_is_refused`).
- `test_03_recruiting_pipeline.py` — `test_a_rejected_candidate_may_also_be_re_engaged` reassigned the *candidate* variable to the return of `schedule_assessment`, which returns the created **SelectionAssessment**, so the subsequent `reject_candidate` addressed an assessment id and got 404 `ERR_CANDIDATE_NOT_FOUND`. Kept the candidate reference and discarded the assessment (matches how every other helper in the suite treats that endpoint).
- `test_04_licensing_sequencing.py` — `test_securities_activation_also_drives_the_prerequisite_dag_case_for_series_sixty_five` asserted `insurance_license_status == "PENDING"` ("the licence dimension is untouched by the registration ladder") but created its licence with `new_license()`'s default `activate=True`, making it ACTIVE. Changed to `activate=False` so the fixture honours the PRD precondition (§3.5: licence created PENDING; the four dimensions evolve independently) the assertion tests.

**Fixes applied to `implementation/`:** none — the implementation was correct on all five; each failure was a test-artifact defect.

**Final sweep result:** 77/77 in each of the 8 rounds (0 failed, 0 errors, 0 skipped). The 8 `results.{1..8}.json` files remain in the implementation directory.

**PRD ambiguity worth feeding Step 8:** the §2.7 "rounded half up" convention is stated verbally, but the presence of a Python-`round()`-style expected value in the generated helper shows implementers/tests need the half-up rule restated at every formula that produces a rounded quantity; §3.2's single pinned example (8.88 vs 8.87) is the only place the unrounded-intermediate of 6.125 is disambiguated, and it is load-bearing for a whole class of computations.

## Step 8: Finalize PRD — 2026-09-30T05:15:00.000Z

Both edits are in place and verified (449 lines each, 0% delta). Here is the report.

## Summary

`PRD_FINALIZED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_3056_career_agency_field_force_recruiting_advisor_validation/workspace/PRD_FINALIZED.md`.

- **PRD.md:** 449 lines → **PRD_FINALIZED.md:** 449 lines (**0% line delta**; 2 lines changed).

### Changes (one bullet per edit)

- **§2.7 (Money, Rounding, and the Credit Ledger Invariants) — revise** — the global rounding sentence now says the half-up rule applies to *"a monetary amount, a percentage, or a score"* (previously only "a monetary amount") and adds that it is applied *"to the exact decimal value of the computation and never to a binary floating-point approximation of it, and a value that falls exactly halfway between two representable results is rounded up rather than to the nearest even digit."* — impl `workspace/implementation/services/calc.py:71-78` (`round_2`/`round_cents` both `quantize(..., rounding=ROUND_HALF_UP)`), surfaced at `services/assessment.py:75` (`f2` → `weighted_score`) and `services/persistency.py:125` (`persistency_pct`).
- **§3.3 (Contracting an Accepted Candidate and the Training Allowance Ledger) — revise** — the requirement threshold wording was *"multiplied by 0.35, rounded half up to two decimal places"*; changed to *"rounded half up to the nearest whole cent"*, matching the implementation's integer-cents conversion. — impl `workspace/implementation/services/calc.py:157-158` (`product_requirement_cents` → `round_cents`), sole caller `services/contracts.py:119`.

### Per-edit pre-edit search log

**Edit 1 (§2.7 global rounding convention).** (a) *Subject:* the half-up rounding mode itself — the disambiguation between a decimal half-up rule and a float half-to-even rule, and which quantity classes it governs. (b) *Impl paths enumerated:* grepped every `Decimal|quantize|round|ROUND` across `implementation/` — all rounding funnels through exactly two primitives, `calc.round_2` (2-dp, half-up) and `calc.round_cents` (whole-cent, half-up), both `ROUND_HALF_UP`, never Python `round()`. Read every callsite: `services/calc.py` (lines 95-97 assessment, 111 case gross, 118 split lead, 142/144/146 chargeback bands, 158 threshold, 169 production draw, 173 recruiter override, 182 persistency pct, 196 renewal, 222 override accrual), `services/assessment.py:75`, `services/persistency.py:120-128`, `services/derived.py:185,194`, `services/policies.py`, `services/contracts.py:119,146`. Confirmed the only rounded quantity classes are money (`round_cents`) and percentage/score (`round_2`) — nothing else is rounded. (c) *Wording adjustment:* I deliberately used *"a monetary amount, a percentage, or a score"* (not "every computation") so the sentence covers every rounded quantity class without excluding any and without asserting a rounding step the impl never performs; "per term", "at the exact point named in the rule", and the untouched Third/evaluation-order sentence preserve all existing pinned orders (split remainder, round-then-sum, sum-then-cap).

**Edit 2 (§3.3 requirement threshold).** (a) *Subject:* the rounding unit of the training-allowance requirement threshold. (b) *Impl paths enumerated:* grepped `validation_requirement_cents` — three uses in `calc.py` (lines 158 threshold, 169 production draw, 173 recruiter override) plus `serialize.py:58` and `contracts.py:69,86`; read all of them. The two sibling uses (lines 169, 173) are already correctly worded "nearest cent" in §3.3 and are untouched; `product_requirement_cents` (line 158) has the single caller `contracts.py:119` inside `draw_allowance`, and no other path computes the threshold. Also read `services/licensing.py`, `services/recruiting.py`, `services/jointwork.py`, `services/orphans.py`, `services/advisors.py` to confirm no unrelated path reuses this quantity. (c) *Wording adjustment:* none needed — *"to the nearest whole cent"* is consistent with `round_cents`, with the §2.7 Second convention's "every integer-cents conversion", and with the sibling §3.3 formulas; the pinned 105000 example still holds (300000 × 0.35 = 105000 exactly).

### Items deliberately not edited

The four remaining `<step_7_diff>` items are pure test-artifact defects with no PRD silence to patch: two missing test imports (`fetch_policy` in `test_05`, `setup_contracted_rep` in `test_09`), the `schedule_assessment` return-value reassignment in `test_03`, and the `new_license(activate=False)` fixture correction in `test_04`. The last one is PRD-*determined* (§3.5 already pins that a licence is created `PENDING` and the four dimensions evolve independently), so the fixture was the bug and no PRD edit was manufactured. No `implementation/` fix existed in Step 7, so no PRD/impl mismatch beyond the two rounding-items was available to patch.

## Step 9: Complete PRD — 2026-09-30T05:30:00.000Z

All 24 edits are present and verified. The file remains a strict inline superset of PRD_FINALIZED.md (same 449-line block structure, no lines added or removed).

## Summary

**Source vs output:** `PRD_FINALIZED.md` (449 lines, 98,510 chars) → `PRD_COMPLETED.md` (449 lines, 102,824 chars), char-delta **+4,314**. No sections, paragraphs, or lines were added or removed — 24 unique-string replacements landed across 11 in-place hunks.

**Counts:** 24 alignment changes — **17 ambiguity-pins**, **7 mismatch-revisions**.

One bullet per change:

- **§2.8 completed-month count** — insert — ambiguity — count clamped to ≥0 when lapse precedes issue — `services/calc.py:126-134`
- **§3.1 advance-to-interview selection** — revise — mismatch — "latest by scored_date desc" → "single most recently *created* SCORED assessment, ties by `id` asc"; added `ERR_ASSESSMENT_NOT_PASSED` when no SCORED assessment exists — `services/assessment.py:26-42`, `services/recruiting.py:81-84`
- **§3.2 terminal candidate** — insert — ambiguity — only `reject` yields `ERR_ALREADY_TERMINAL`; all other transitions from terminal yield `ERR_INVALID_STATE` — `services/recruiting.py:40-43,119-125`
- **§3.3 advisor email** — insert — ambiguity — duplicate email → `ERR_DUPLICATE_NATURAL_KEY` — `services/advisors.py:39-44`
- **§3.3 recruiter_override_cents** — insert — ambiguity — computed and stored on the contract row but never serialized and creates no credit — `services/contracts.py:146`, `services/calc.py:172-173`
- **§3.3 TRAINING_ALLOWANCE credit row** — insert — ambiguity — no policy: `policy_id` null, `case_gross_commission_cents` 0, outside §2.7 invariant — `services/contracts.py:130-145`
- **§3.4 period_number** — insert — ambiguity — stored exactly as supplied, no consecutiveness/uniqueness/start-at-one validation — `services/contracts.py:208-214`
- **§3.4 extend validation window** — revise — mismatch — extendable from `OPEN` **or** `EXTENDED`; a window already at/above its requirement is refused with `ERR_INVALID_STATE` — `services/contracts.py:318-331`
- **§3.5 registration own expiry** — insert — ambiguity — prereq-null activation past own expiry → `ERR_REGISTRATION_NOT_ACTIVE` — `services/licensing.py:230-233`
- **§3.5 registration re-activation** — insert — ambiguity — activating an already-`ACTIVE` registration is an idempotent success, not a refusal — `services/licensing.py:219-221`
- **§3.5 rejected appointment** — insert — ambiguity — `REJECTED` admits no further transition (`ERR_INVALID_STATE`) — `services/licensing.py:299-303,348-353`
- **§3.6 override rate** — insert — mismatch — only the rank rate (0.03/0.02) accrues; office `override_rate_pct` never scales override, only `override_cap_cents` caps — `services/derived.py:178-190`, `services/calc.py:210-223`
- **§3.6 chargeback fiscal block** — revise — mismatch — block fires at policy *activation* (and joint-case submit), not at policy write — `services/policies.py:215-217`, `services/jointwork.py:129-133`
- **§3.6 override chargeback cascade** — revise — mismatch — no `OVERRIDE_DO`/`OVERRIDE_MD` credit rows are ever created; only `override_income_cents` is recomputed (codebase-wide absence)
- **§3.6 lapse chargeback_reason** — insert — ambiguity — late-band lapse also records `LAPSE_WITHIN_12MO`; `REPLACEMENT`/`TERMINATION` are never written — `services/policies.py:268`
- **§3.6 assessed credit scope** — insert — ambiguity — only `ACCRUED`/`PAID` credits with positive gross are assessed; zero-rounding leaves status untouched — `services/policies.py:236-242`
- **§3.6 recovery amount** — insert — ambiguity — non-positive amounts also refused with `ERR_RECOVERY_EXCEEDS_ASSESSED` — `services/policies.py:364-366`
- **§3.6 void from OPEN** — insert — ambiguity — non-lead/`ManagingDirector` void from `OPEN` → `ERR_INVALID_STATE`, not the scope error — `services/jointwork.py:166-168`
- **§3.6 submit balance block scope** — insert — ambiguity — evaluated against policy `writing_advisor_id` and both lead and support balances — `services/jointwork.py:129-133`
- **§3.7 renewal base** — revise — mismatch — base is all the advisor's `ACTIVE` policies at finalization; window bounds do not narrow the set — `services/persistency.py:88-99`
- **§3.7 RENEWAL credit row** — insert — ambiguity — no policy: `policy_id` null, `case_gross_commission_cents` 0 — `services/persistency.py:136-151`
- **§3.8 terminated production** — insert — ambiguity — terminated advisor dropped from ancestor rollups by status; its credits are not voided — `services/derived.py:133-155,163-175`
- **§3.8 orphan assign states** — insert — ambiguity — `ASSIGNED` → `ERR_ALREADY_TERMINAL`; `REJECTED` → `ERR_INVALID_STATE` (must reopen) — `services/orphans.py:50-55`
- **§4 status codes** — insert — mismatch — `POST …/schedule-assessment` returns `200 OK` (authored as a parent transition), unlike other child-creating 201s — `routes/candidates.py:88-97`

Key structural finding: the implementation is a faithful realisation of the PRD's arithmetic and state machines — all 8 test rounds pass 77/77. The two largest divergences an implementer could plausibly get wrong from prose alone are (a) the §3.6 chargeback fiscal block firing at activation rather than at policy write, and (b) the complete absence of materialised `OVERRIDE_DO`/`OVERRIDE_MD` credit rows, both of which the original PRD described as real behaviours.

## Pipeline close-out — 2026-09-30T05:31:00.000Z

Final independent orchestrator-side verification round (`prd-bench-local-run --isolation per-test-server`, single round, after Steps 8/9 which touched only markdown): **77/77 passed, 0 failed, 0 errors, 0 skipped** in 139.0s. Steps 8 and 9 edited only `PRD_FINALIZED.md`/`PRD_COMPLETED.md`, so the Step 7 green state is preserved unchanged.

Pipeline complete. Final artifacts:
- `SCAFFOLD.yaml` (2404 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1544), `SCAFFOLD_CORNER_DESIGN.yaml` (1870)
- `test_helpers/` (9 files), `test_suite/` (11 test modules + conftest, 77 tests)
- `workspace/INSTRUCTION.md`, `workspace/PRD.md` (449), `workspace/PRD_FINALIZED.md` (449), `workspace/PRD_COMPLETED.md` (449)
- `workspace/implementation/` (4,283 Python lines, 96 endpoints, in-memory only) + `start.sh` + `results.{1..8}.json`