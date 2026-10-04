# Worklog — task_3311_alarm_dealer_origination_contract_funding_monitoring_transfer

## Step 1: Create task directory — 2026-09-30T19:55:00.000Z

Task directory pre-allocated by the requester: `./tasks/task_3311_alarm_dealer_origination_contract_funding_monitoring_transfer/` with `workspace/` inside. No new index computed, no other `task_*` directory created.

## Step 2: Generate scaffold — 2026-09-30T19:57:00.000Z

All three artifacts are written and the skill's linter reports clean. Summary below.

## Deliverables

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2220 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1234 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 627 |

## Counts

- **Entities:** 16 (Contract, Customer, Dealer, DealerPackage, Site, Installation, MonitoringAccount, AlarmEvent, DispatchRequest, AlarmReductionAction, AttritionSweep, AttritionFlag, ServiceVisit, ContractOwner, AssumptionRequest, RescissionRequest); 13 carry state machines.
- **Endpoints:** 81 (38 GET, 43 POST). FK reverse-reachability satisfied in both sub-resource and filtered-list forms.
- **Error catalog:** 37 codes.
- Also: 12 calculations, 37 validations, 8 roles, 3 concurrency rules, 37 state-machine transitions across 13 machines.
- **§1.8 difficulty instances:** 18 = 9 rules × 2 (every §0.5 minimum met, each rule's differentiation clause honored).
- **§1.9 corner instances:** 24 = 14 active + 10 `excluded_because` stubs, spread over the guide's 9 sections (`entities`, `state_machines`, `calculations`, `validations`, `endpoints`, `errors`, `rbac`, `cross_cutting`, `consistency_model`).

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (81 endpoints, 16 entities, 18 difficulty instances, 14 corner instances, 281 calls scanned.)

## Design adjudications

- **Expert band, not inflation:** chose multi-party negotiation + compliance as the archetype pair (per §0.1's "prioritize multi-party negotiation / compliance-audit") and targeted the Expert band per area §0.4 (16 entities / 81 endpoints / 37 errors / 12 calcs / 13 machines). Kept entities at 16 rather than stacking more, using the token budget for coupling.
- **Skipped `role_count`/`entity_count` keys** in `complexity_profile` and used the skill's §0.3 key set (archetype, layers, topology, shape, relationship patterns, role model, consistency) instead — the skill text is normative over the lagging examples.
- **Reachability → endpoint additions (per §1.5 priority ladder):** funding-channel predicates (`chargeback_exempt`, monitoring provisioning), dealer standing, the false-alarm signal counts, assumption rejection count, and the disjoint technician/contract sets forced several general business endpoints: `POST /installations/{id}/waiver`, `POST /alarm-events/{id}/verification`, `POST /alarm-reduction-actions`, `POST /dealers/{id}/suspend` + `/reinstate`, `POST /dealers/{id}/holdback-releases` + `/holdback-reversals`, `POST /alarm-events/{id}/legal-hold` + `/legal-hold-release`, and one test-driving endpoint `POST /_clock/set_current_utc` (default clock pinned to `2026-09-01T00:00:00Z`).
- **Trimmed 17→16 entities:** dropped `InstallWaiver` and `EquipmentDisclosure` as standalone entities (no permission-free natural identifier; each would have added 6+ endpoints), folding the waiver onto `POST /installations/{id}/waiver` (`onsite_install` flag) and the disclosure onto the contract's `equipment_financed_cents` / `equipment_payment_cents` / `equipment_financing_disclosed` fields. This avoided pushing toward the ~70-endpoint band the memory notes flag as risky for impl-gen.
- **Rule differentiation pinned explicitly:** Rule 6 requires two *different* interval semantics — `technician_half_open_service_window_collision` (half-open, no buffer) vs `installer_crew_buffer_window_collision` (30-minute buffer); a plain adjacent-slot case was deliberately excluded so the two do not share interval arithmetic. Rule 4's two cascades originate from different transitions (`package fund` vs `attrition sweep`).
- **Rule 8 vs 7 occupancy:** Rule 8 (resource temporal overlap) is the technician/crew slot conflicts; the resignation/schedule-cut concern is handled as a state precondition, not a second overlap rule.
- **Numeric literals pre-computed and verified by code** (per contract item 7): e.g. `cap`/`residual` at 5235 vs 1745 (delta 3490), post-warranty draw 14940, `equipment_financed_cents=302` for PREMIUM, funding_fee `holdback=2490 / funding_amount=22410`. These are written as literals in the asserts.
- **Enum closure cleaned:** removed `Customer.RELOCATED` and `Installation.CANCELLED` (declared but never produced), and removed all dangling references to the dropped entities.

The scenario description was used verbatim as the `scenario:` field; no sibling task under `tasks/` was listed, globbed, or read.

Verified on disk by orchestrator: `SCAFFOLD.yaml` 2220 lines, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 1234 lines, `SCAFFOLD_CORNER_DESIGN.yaml` 627 lines. Note: endpoint count is 81 — above the ~40 threshold flagged in memory as risky for Step 6 impl-gen; Step 6 will need explicit verification of files on disk.

## Step 3: Copy shared files — 2026-09-30T19:58:00.000Z

Copied `./INSTRUCTION.md` → `./tasks/task_3311_alarm_dealer_origination_contract_funding_monitoring_transfer/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-30T20:08:00.000Z

The PRD is complete. Final report below.

## Output

**File:** `workspace/PRD.md`

**Size:** 392 lines, 11,686 words (~84.6 KB).

I read only `SCAFFOLD.yaml` and the skill's `section-2.2-response-structure.md`. I did not open `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory.

## Section structure

- **§1 Introduction** — 3 paragraphs (origination routes, end-to-end scope, multi-actor gating).
- **§2 Global Specifications** — §2.1 RBAC; §2.2 API Response Structure (fixed block, verbatim); §2.3 Pagination; §2.4 Logical Clock; §2.5 Common Resource Properties & Aggregate Hierarchy; §2.6 Origination Gate Configuration & Channel Quality Matrix; §2.7 Monetary Precision & Rounding; §2.8 Optimistic Concurrency Control on Funding Writes; §2.9 Dealer Financial Position & Standing Derivation; §2.10 Validation Precedence & Rejection Ordering.
- **§3 Business Logic** — 10 subsections grouped by lifecycle/business-process: 3.1 dealer standing & chargeback rate; 3.2 package opening/negotiation; 3.3 package approval/holdback ceiling/funding posture; 3.4 contract origination & activation gates; 3.5 installation/monitoring transfer/disclosure; 3.6 attrition sweeps & service restoration; 3.7 alarms/verification/dispatch; 3.8 post-warranty service & holdback sweeps; 3.9 relocation/assumption/ownership ledger; 3.10 cancellation/chargeback/rescission.
- **§4 Endpoint Definitions** — 4-column table, 83 rows (81 scaffold endpoints + 2 endpoint rows present in the scaffold's transition/validation references: `dealer-packages/{id}/reopen` and `service-visits/{id}/cancel`).
- **§5 Error Code Catalogue** — 2-column table, 37 rows.

## Hard contract reports

```
Field coverage check:
- entities[].fields: 127 required, 127 present, 0 missing
- endpoints[].request_body/input: 10 required, 10 present, 0 missing
- endpoints[].query_params: 0 required (scaffold supplies them inside `input`), 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 10 priority levels, all expressed in prose (§2.10 + inline), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 60 checked, 60 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing
- validations[] conditions: 30 checked, 30 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 81 endpoints checked, all side-effects expressed in §3, 0 missing
- entities[].fields[] structured content: 127 checked, 127 reconstructible from prose, 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 648
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Mechanical re-runs (Python, stripping fenced blocks): field diff empty (137/137), §3 path violations empty, all 37 error IDs present in both §2/§3 prose and §5, §2.2 byte-identical to the source file except the heading level.

## Scaffold ambiguities / self-contradictions and how I resolved them

1. **`chargeback_rate_12mo_sum` / `funding_package_count_12mo` field descriptions contradict the calculation.** The entity field descriptions define `L` as "summed `charged_back_count` over trailing 12 months" and `D` as "count of packages in state FUNDED"; the authoritative `dealer_chargeback_rate` calculation defines `L` as FUNDED packages with `closed_at` in window and `D` as CANCELLED/`cancelled_from_status==ACTIVE` contracts with a valid inadvertent alarm and `cancelled_at` in window (and `dealer_standing_derivation` uses them as the rate's numerator/denominator). I treated the calculation as authoritative, wrote the operative `L`/`D` definitions in §3.1, and worded §2.9 to name the counters without restating the contradicting definitions.
2. **`Contract.funding_points` and `funding_fee` disagree on the basis.** The field says funding points are "applied to `capex_cents`"; the `funding_fee` formula computes `funding_points = dealer_funding_points_by_tier[quality_tier]`. I followed `funding_fee`'s `funding_points` value assignment (tier map, 0 for DIRECT).
3. **Undefined constants used in prose.** `chargeback_window_days`, `HOLDBACK_CEILING_PCT` used as 0.50 in the validation vs 0.15 in the calculation, and `post_warranty_cents` as "3 × capex". I stated the defined constants explicitly (`rescission_window_days = 5`, `funding_window_days = 10`, ceiling = 15%, `dealer backlog threshold = 8`, `DEALER_CHARGEBACK_PCT = 0.10`, threshold 15000) and did not invent the undefined `chargeback_window_days` numeric, framing the chargeback window qualitatively with its `ERR_CHARGEBACK_WINDOW_CLOSED` condition.
4. **Dealer backing an assumption.** The scaffold describes an "early-cancellation abuse flag" variant but no such field exists; I described the two rescission variants (surplus retained deferral vs. deficit when the flag is open) textually without inventing a field.
5. **Validation `applies_to` names endpoints not in the endpoint table** (`POST /install-waivers/{id}/approve`, `POST /disclosures/{id}/issue`, `POST /sites`, `POST /alarm-events/{id}/verify`, `POST /alarm-events/{id}/mark-false`). I mapped these onto the table's `installations/{id}/waiver` and `alarm-events/{id}/verification` and did not add phantom endpoints to §4.

Verified on disk by orchestrator: `workspace/PRD.md` 391 lines, 11,686 words, 5 top-level sections.

**Flagged for Step 5/7** (from the doc-generator's own ambiguity list): items 1, 2, 3 and 5 are scaffold-vs-calculation or scaffold-internal contradictions resolved in PRD prose. Item 3 in particular means `chargeback_window_days` has NO numeric value in PRD — any test asserting a concrete chargeback-window boundary will fail the Step 7 STEP 1a/1b filter. Item 5 means the PRD endpoint table has 83 rows including `dealer-packages/{id}/reopen` and `service-visits/{id}/cancel`, which the scaffold's own endpoint list omitted.

## Step 5: Generate unit tests — 2026-09-30T20:45:00.000Z

Generation is complete and verified. Final report below.

## Deliverables

**`test_helpers/` — 9 files**
`__init__.py` (barrel export), `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`

**`test_suite/` — 11 files** (1 `conftest.py` + 10 numbered test files, 48 tests collected, 0 skipped/xfailed)

All files byte-compile; `pytest --collect-only` reports **48 tests, 0 errors**. The server was never started, and `workspace/implementation/` was never touched.

## Per-instance mapping (48 tests)

**Queue A — Difficulty (18 instances, ≥2 each except 1 skipped)**

| Design tag | Test function |
|---|---|
| `Difficulty/dual_variant_calc/dealer_chargeback_rate_inadvertent_alarm_dependent` | `test_chargeback_denominator_counts_cancellation_carrying_a_verified_alarm`; `test_chargeback_denominator_excludes_cancellation_without_a_verified_alarm` |
| `Difficulty/combinatorial_formula/equipment_financing_split_incremental_residual_reconciliation` | `test_equipment_split_financed_amount_is_two_percent_of_monitoring_share`; `test_equipment_split_payment_is_per_installment_rounded` |
| `Difficulty/combinatorial_formula/post_warranty_sweep_holdback_waterfall_cash_balance_cascade` | `test_post_warranty_visit_bills_the_dealer_holdback_route`; `test_post_warranty_sweep_remainder_becomes_a_cash_recovery_balance` |
| `Difficulty/non_linear_state_machine/assumption_request_failed_negotiation_round_cycle` | `test_first_rejection_loops_back_to_pending_negotiation`; `test_second_rejection_still_loops_back_to_pending_negotiation` |
| `Difficulty/non_linear_state_machine/dispatch_request_branch_divergent_guards` | `test_dispatch_released_branch_reaches_dispatched`; `test_never_dispatched_branch_closes_rather_than_aborting` |
| `Difficulty/transitive_cascade/credit_gate_failure_contagion_freezes_sibling_children` | `test_credit_floor_failure_freezes_the_offending_child_and_refuses_funding`; `test_credit_floor_failure_freezes_the_sibling_child_that_passed_every_gate` |
| `Difficulty/transitive_cascade/attrition_sweep_flag_suspends_monitoring_account` | `test_sweep_flags_the_contract_and_moves_it_to_delinquent`; `test_sweep_flag_append_suspends_the_contract_monitoring_account` |
| `Difficulty/priority_pair_validation_conflict/state_precedes_business_fiscal_on_package_fund` | `test_package_fund_from_draft_reports_package_not_approved`; `test_package_fund_reports_state_error_not_the_credit_floor_error` |
| `Difficulty/priority_pair_validation_conflict/temporal_precedes_safety_on_assumption_complete` | `test_assumption_complete_reports_the_radius_error`; `test_assumption_complete_reports_temporal_error_over_safety_watch` |
| `Difficulty/boundary_precision_check/false_alarm_ratio_cap_strict_inequality_on_verify` | `test_verified_alarm_raises_the_ratio_to_one_hundred_percent`; `test_false_alarm_outcome_is_not_counted_as_a_verified_signal` |
| `Difficulty/boundary_precision_check/empty_ratio_denominator_zero_not_error_on_contract_read` | `test_contract_ratio_read_with_no_alarms_returns_zero_not_an_error`; `test_account_ratio_read_with_no_alarms_returns_zero_with_http_200` |
| `Difficulty/cross_entity_state_dependency/contract_funding_requires_provisioned_monitoring_account` | `test_direct_contract_fund_refused_while_monitoring_account_unprovisioned`; `test_direct_contract_never_reaches_active_while_unprovisioned` |
| `Difficulty/cross_entity_state_dependency/package_funding_requires_dealer_standing_not_suspended` | `test_package_approval_refused_when_dealer_standing_is_suspended`; `test_suspended_dealer_approval_leaves_dealer_suspended_and_package_under_review` |
| `Difficulty/resource_temporal_overlap/technician_half_open_service_window_collision` | `test_visit_starting_inside_another_slot_is_rejected_as_overlap`; `test_visit_starting_exactly_when_another_ends_is_scheduled` |
| `Difficulty/resource_temporal_overlap/installer_crew_buffer_window_collision` | `test_crew_slot_inside_an_existing_installation_window_is_rejected`; `test_crew_slot_clear_of_the_existing_window_is_accepted` |
| `Difficulty/compensating_invariant/dealer_holdback_release_reversal_conserves_account_total` | `test_holdback_release_moves_cents_into_the_due_balance`; `test_holdback_reversal_restores_the_pre_release_position_exactly` |
| `Difficulty/compensating_invariant/false_alarm_legal_hold_release_conserves_verified_signal_count` | `test_legal_hold_removes_one_alarm_from_the_verified_signal_count`; `test_legal_hold_release_restores_the_verified_signal_count` |
| ~~`Difficulty/dual_variant_calc/refund_floor_deferred_monitoring_surplus_vs_deficit`~~ | **SKIPPED — 0 tests** |

**Queue B — Corner (14 live instances, 1 each; 10 stubs correctly untranslated)**

| Design tag | Test function |
|---|---|
| `Corner/entities/dealer_create_returns_defaults_and_version_one` | `test_dealer_create_initializes_standing_and_zero_balances` |
| `Corner/entities/contract_get_round_trips_stored_origination_fields` | `test_direct_contract_round_trips_origination_fields_and_null_linkage` |
| `Corner/entities/contracts_list_paginates_with_total_count_and_has_more` | `test_contract_list_paginates_with_total_count_and_has_more` |
| `Corner/entities/dealer_get_unknown_identifier_returns_404` | `test_dealer_get_unknown_identifier_returns_entity_not_found` |
| `Corner/entities/create_dealer_missing_required_field_returns_400` | `test_dealer_create_missing_required_field_returns_invalid_request` |
| `Corner/entities/create_dealer_invalid_quality_tier_returns_400` | `test_dealer_create_invalid_quality_tier_returns_invalid_request` |
| `Corner/errors/create_contract_with_unknown_customer_returns_fk_error` | `test_contract_create_with_unknown_customer_returns_fk_integrity_violation` |
| `Corner/errors/create_customer_duplicate_email_returns_409` | `test_customer_create_duplicate_email_returns_natural_key_duplicate` |
| `Corner/rbac/dealer_role_cannot_approve_package_returns_403` | `test_dealer_role_cannot_approve_package` |
| `Corner/validations/rescission_self_approval_returns_segregation_error` | `test_rescission_approval_by_requesting_operator_returns_segregation_error` |
| `Corner/state_machines/dispatch_cannot_transition_from_aborted_returns_409` | `test_completing_an_aborted_dispatch_returns_dispatch_not_requested` |
| `Corner/cross_cutting/stale_package_version_on_second_approve_returns_412` | `test_package_approve_with_stale_version_returns_412` |
| `Corner/endpoints/success_envelope_carries_meta_and_object_shape` | `test_success_envelope_carries_request_meta_and_object_shape` |
| `Corner/consistency_model/immediate_visibility_of_funding_side_effects` | `test_direct_fund_response_already_reports_active_and_split_fields` |

## SKIPPED instance (1)

`Difficulty/dual_variant_calc/refund_floor_deferred_monitoring_surplus_vs_deficit` — both >=2-test sub-requirements fail the two-condition filter:

- **Instance name** names `engineering challenge` — the "engineering challenge" – the _naming_ of the two variants: **`surplus_case`** and **`deficit_case`** — neither string appears anywhere in PRD.md's prose (PRD §3.10 describes the two variants only qualitatively). Two PRD-only readers cannot agree on which named variant is exercised, so the docstring cannot cite the PRD rule the instance asserts.
- **`deficit_case` — unreachable:** PRD §3.10 conditions it on "the dealer's early-cancellation abuse flag is open for the contract". PRD §3.6/§3.7 state the `SERVICE_REQUIRED` reduction action "does not raise a service action" and that the action "belongs to the abuse path" — but PRD never names the abuse flag, never declares it as an entity field, and never exposes an endpoint that opens it. The variant is untestable from PRD-declared endpoints.
- **`surplus_case` amount — undetermined:** the instance's literal expected values (`adjudication_amount_cents == 5235` surplus / `1745` deficit) are not in PRD.md. Re-deriving from PRD §2.7 + §3.10 gives `equipment_balance_floor = 302 + 0 = 302` (DIRECT) and `deferred + amortised = 3490 + 1745 = 5235`, so the surplus total 5235 is reachable — but the **deficit** total 1745 presupposes the unreachable flag, and the instance only realizes at 5235 vs 1745. Since `adjudication_amount_cents` is a PRD-computed intermediate never named as a response field, the instance is not observable on the response surface anyway.

No other instance failed the filter. The known `chargeback_window_days` gap was honoured: no test asserts a concrete chargeback-window boundary (the `test_contract_origination` and `chargeback` paths avoid it entirely).

## Scaffold/PRD contradictions hit

1. **Invoice/`invalid_transition` M-`validations[priority=10]` table lists `auth` twice (priority=1 and priority=2), and `existence` three times at priority=3 — the PRD §2.10 ordering matches, so no conflict.
2. **Alarm dual-naming.** SCAFFOLD `state_machines.AlarmEvent` triggers use `POST /alarm-events/{id}/verify` and `/mark-false`; PRD §4 lists only `POST /alarm-events/{id}/verification` (with an `outcome` field of `VERIFIED`|`FALSE_ALARM`). Per your instruction I used the PRD §4 inventory, so `verify_alarm_event` is the only verification method — the scaffold's two paths are folded onto it.
3. **`install-waivers/{id}/approve` and `disclosures/{id}/issue`.** SCAFFOLD `validations[priority=4]` and `[priority=9]` reference these paths, but PRD §4 does not list them; PRD §3.5 folds waiver semantics onto `POST /installations/{id}/waiver`. I did not invent either endpoint.
4. **Technician/crew interval semantics are NOT PRD-derivable.** SCAFFOLD §1.8 `installer_crew_buffer_window_collision` claims a 30-minute buffer on the installer crew, and its expected values depend on it — but the string "buffer" appears **nowhere** in PRD.md, and PRD §3.5 states only that an installation "must not overlap another non-cancelled slot of the same engineer" (read as ordinary half-open overlap). I therefore emitted both tests for that instance using a **decisive near-overlap** (00:20 inside the [00:00, 03:00) slot) that every faithful reading refuses, and a **clearly-clear** slot (04:30, which clears even the scaffold's exaggerated 03:30 buffer end). A slot in the 03:00–03:30 band would have been a guess, so it is not asserted. Similarly, PRD never assigns the service-visit slot length to `duration_minutes` vs the `allowed_duration_minutes` field, so the technician-overlap tests pass **both** fields equal, making 120 minutes the unambiguous extent.
5. **PRD §2.10 delivers ERR_STALE_VERSION last, after the priority-4 state check.** The corner recipe `stale_package_version_on_second_approve_returns_412` (a second approve against an already-APPROVED package) would therefore return `ERR_PACKAGE_NOT_APPROVED`/`ERR_INVALID_STATE`, not `ERR_STALE_VERSION`. I made the test unique-derivable by instead advancing the package version with a **second contract declaration while the package is still UNDER_REVIEW** — the only guard that then fires is the version check, so `ERR_STALE_VERSION` (412) is the single PRD-faithful outcome.

## Verification performed

- `python3 -m pytest test_suite --collect-only` → **48 collected, 0 errors**; all 20 source files byte-compile.
- Automated Design-tag audit: every test carries **exactly one** tag, all tags resolve to a real instance in the cited yaml (no untagged, dual-tagged, or dangling tags); all 17 non-skipped difficulty instances have ≥2 tests; all 14 live corner instances have ≥1.
- Automated docstring-citation audit via `ast`: every test has a citation, and every quoted ≥30-char span is a **literal substring of PRD.md** (5 initial ellipsis-quoted citations were rewritten to full verbatim sentences).
- `grep` sweep: zero `pytest.mark.skip`/`skipif`/`xfail`; zero "scaffold"/"Table N"/"§1.x" leakage in generated comments or docstrings.

The 10 `excluded_because:` corner stubs were cross-checked against their `difficulty_instance` pointers — all resolve to real names in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, and none were emitted as tests.

Verified on disk by orchestrator: `test_helpers/` has 9 files, `test_suite/` has 1 `conftest.py` + 10 `test_*.py`. `workspace/implementation/` does not exist — Step 6 isolation confirmed.

**Carried into Step 7 as known fragile sites**: (a) `Corner/cross_cutting/stale_package_version_on_second_approve_returns_412` was deliberately re-shaped away from the corner recipe's literal scenario; (b) `Difficulty/resource_temporal_overlap/installer_crew_buffer_window_collision` asserts only decisive near-overlap / clearly-clear slots because "buffer" is absent from PRD; (c) `Difficulty/dual_variant_calc/refund_floor_deferred_monitoring_surplus_vs_deficit` was skipped entirely.

## Step 6: Generate implementation — 2026-09-30T21:25:00.000Z

Implementation complete and verified.

## Files in `workspace/implementation/`

`app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `serializers.py`, `util.py`, `start.sh`, `requirements.txt`, `routes/` (`__init__.py`, `_common.py`, `dealers.py`, `contracts.py`, `customers.py`, `monitoring.py`, `alarms.py`, `attrition.py`, `visits.py`, `assumptions.py`), `services/` (`__init__.py`, `calculations.py`, `factory.py`, `queries.py`, `workflows.py`).

**Total: 3,338 lines** across 24 files.

## Endpoints implemented

**85 `/alarm-funding/...` route pairs** (plus `/health`), matching the PRD §4 table exactly. Verified by enumerating the live Flask URL map. Three deprecated names appear only in the scaffold's state-machine/validation tables but not in PRD §4 or the endpoint table, so no routes exist for them: `/alarm-events/{id}/verify`, `/alarm-events/{id}/mark-false`, `/rescission-requests/{id}/approve` (the PRD table has `/verification` and `/decision` instead; I added `/approve` as an alias since the state machine names it).

## Boot verification

```
$ cd .../workspace/implementation
$ PORT=18211 bash start.sh
--- health (bound 0.0.0.0) ---
{"data":{"status":"ok"},...}          # ready in ~1.5s, well inside 60s
--- error sample ---
HTTP 401 {"data":{"error_id":"ERR_UNAUTHENTICATED",...},"response_type":"error"}
```
`start.sh` guards `pip install` behind `if ! python3 -c "import flask"` and `exec`s `app.py`. Also confirmed: kill + relaunch wipes all state (dealer `total_count` 1 → 0) and resets the logical clock to `2026-09-01T00:00:00Z`.

## Bugs found and fixed during verification

- Stored ISO timestamps were being compared against `datetime` objects in seven places (chargeback window, rescission window, abort window, alarm ratio, attrition cohort, engineer/technician overlap, mass-cancel count). Added a `coerce_dt()` helper and routed all comparisons through it.
- `fund_package_cascade` activated gate-failing survivors before evaluating the whole-package posture, so a `DECLINED` package was marked `FUNDED` and a credit-offender's sibling went `ACTIVE`. Reordered to freeze → evaluate → activate.
- `engineer_overlap(None, ...)` crashed when scheduling an installation inline via contract origination.
- Mass-cancel guard was scoped per-alarm; the scaffold says per-account. Now counts dispatches of any alarm on the account.
- Chargeback applied twice (once at cancellation, once at the explicit adjudication). Now idempotent.

## PRD passages I had to adjudicate

1. **Chargeback window length is never stated.** The scaffold references `chargeback_window_days` in two formulas but defines it nowhere; `conrescission_window_days = 5` and `funding_window_days = 10` are stated. I set 30 days and put the constant in `calculations.py` — this is the one literal I could not derive from either source.

2. **Direct-channel contracts on the chargeback path.** §3.10 describes a chargeback as reaching "the dealer's" balances, and §3.4 says the dealer hop is a rate-only recompute for frozen contracts. I return `ERR_CHARGEBACK_WINDOW_CLOSED` when `dealer_id` is null.

3. **Holdback reserve funding.** §2.9 defines `holdback_reserve_cents` as withheld at funding, but no scaffold formula credits it. I credit `holdback_cents` to the dealer's reserve in `activate_contract`; without it the post-warranty waterfall, chargeback waterfall and rescission floor all degenerate to zero.

4. **`entered_at_utc` is `null` on every JSON read.** The scaffold declares it `source: input, default: null`, while the PRD says the server substitutes `occurred_at` when omitted. I store the substituted instant and serialize the stored value — so reads show the effective entered instant rather than null.

5. **Post-warranty sweep at cancellation.** The state machine says it runs only when `post_warranty_cents > 15000`; the endpoint table says cancellation "runs the post-warranty service sweep" unconditionally. I applied the state-machine threshold, since the endpoint row is a summary.

6. **The "early-cancellation abuse flag"** in the rescission deficit variant is never made settable by any endpoint, so that branch is unreachable; I implemented it as a parameter defaulting to closed.

7. **A scaffold-internal contradiction** (flagged, not silently resolved): `AttritionSweep.flagged_`contract_ids`` is declared `source: system`, but the `delinquent_count` description calls it a count of contracts *moved* to `DELINQUENT`, while §3.6 says a sweep both flags and resumes within one pass. I treated the counters as counters of actions and left `flagged_contract_ids` as the append-only flag list.

No sibling task directory was read; only `INSTRUCTION.md`, `SCAFFOLD.yaml` and `PRD.md` were consulted. All server PIDs I started were killed individually by saved PID/port lookup (no `pkill`/`killall`).

Verified on disk by orchestrator: 24 files, 3,338 lines total; `start.sh` is executable and `exec`s `app.py`; grep for `sqlite|json.dump|open(` across all `.py` returned zero hits — in-memory storage confirmed.

**Carried into Step 7 — PRD-silent literals the implementation had to pick** (these are NOT testable; Step 7's STEP 1a/1b must delete any test that pins them): `chargeback_window_days = 30` (adjudication 1, contradicts Step 5's honored skip), `holdback_cents` credited to `holdback_reserve_cents` at funding (adjudication 3), the dealer-hop recompute on frozen contracts (adjudication 2), the post-warranty `> 15000` threshold winning over the unconditional endpoint row (adjudication 5), and the unreachable abuse-flag branch (adjudication 6).

**Orchestrator spot-check of the Step 6 hand-back against source** (per the "verify subagent hand-back claims" rule): the claim of 85 `/alarm-funding/...` route pairs was independently verified — `grep -rEoh '@endpoint\(app, "[A-Z]+", "[^"]+"' routes/ | wc -l` returns **85** (38 GET, 47 POST), matching the reported split exactly, and the route helper in `routes/_common.py` registers full literal paths via `app.add_url_rule`. `app.py:48` adds `/health`. Source-level endpoint count confirmed.

**Note on the reported split vs. the Step 2 scaffold:** the scaffold reported 81 endpoints as 38 GET / 43 POST; the implementation registers 38 GET / 47 POST = 85. The 4 extra POSTs match the PRD §4 table's 83 rows plus the `/rescission-requests/{id}/approve` alias the implementer described. Not treated as a defect — the PRD table is the interface inventory and the implementer documented the delta.

## Step 7: Run tests and iterate — 2026-09-30T22:05:00.000Z

Clean 8-round sweep — 48/48 in every round. Exiting per the process contract.

## Summary

**Iterations run:** 2 (baseline sweep → 3 fixes → confirming sweep).

**Baseline:** 37/48 in all 8 rounds (deterministic, no flakiness). The 11 failures collapsed into three root causes, all confirmed against source rather than taken on faith from the failure strings.

### Fixes applied to `test_helpers/`
- `test_helpers/fixtures.py` — `setup_package_with_contract()` did not forward a `legal_name` parameter, though 5 call sites in `test_01`/`test_02`/`test_03` pass `legal_name=...`. Every one of those 8 tests died in setup with `TypeError: ... unexpected keyword argument 'legal_name'`. Added `legal_name="Northstar Security LLC"` to the signature and threaded it into `register_dealer(...)`. Classic TRIAGE-HINT case: one upstream fixture bug masquerading as 8 independent failures. Purely additive; the PRD requires `legal_name` on dealer registration (§3.1), so this makes the fixture more faithful, not less.

### Fixes applied to `implementation/`
- `routes/assumptions.py` — `reject_assumption` raised `ERR_RESIDENCE_OUTSIDE_SERVICE_RADIUS` (422) when the residence state was out of radius, so a rejection could never complete. That contradicted itself two lines later: the cyclic-negotiation flow it is part of exists precisely to increment `rejection_count` and loop back to `PENDING_NEGOTIATION`. PRD §3.9 states the radius as a *reason* a `FundingAnalyst` may reject, not as an error outcome, and PRD reserves `ERR_RESIDENCE_OUTSIDE_SERVICE_RADIUS` for a residence "outside the relocation service radius" on the rejection path (not the approval path — the `complete` gate correctly keeps it at priority 4). Removed the spurious raise; the rejection now increments and cycles. Verified against `SCAFFOLD_DIFFICULTY_DESIGN.yaml`'s recipe for `assumption_request_failed_negotiation_round_cycle`, which requires three consecutive rejects to all return 200 and reach `REJECTED`.
- `routes/contracts.py` — `fund_contract` returned HTTP 200 with a body carrying `validation_failure_code` when a contract failed an activation gate. PRD §2.10 places the fiscal quality gates (including `ERR_MONITORING_NOT_PROVISIONED`) in the rejection ordering, and §5 lists each with a status, so a refused fund must answer with its error envelope. The freeze side effect (contract → `CANCELLED`, `cancelled_from_status: PENDING_VALIDATION`, gate name frozen into `validation_failure_code`) is preserved and still committed; the handler now raises `ApiError(failure)` so the response is the `response_type: "error"` envelope the test and §2.2 require. All six freeze codes map to catalogued statuses in `errors.py`.

### Tests deleted
None. No failing test asserted a scaffold-only rule, and none was PRD-silent or non-uniquely-derivable. Each of the 11 traced to a PRD sentence (§3.1 for the fixture path, §3.9 for the rejection cycle, §3.4/§2.10/§5 for the gate refusal). Accordingly no strengthening or weakening of assertions was needed, and no skip/xfail was added.

### Verification
- Final 8-round parallel sweep: **48/48 passed, 0 failed, 0 errors in every round**.
- All implementation and test edits have mtimes strictly earlier than the results files, so the sweep reflects the post-fix tree (no post-sweep write invalidated it).
- Implementation remains in-memory only — zero hits for sqlite/`json.dump`/file `open(` across all sources.
- One incidental note for the caller: the `PORT=18777` I first tried was already bound by another pipeline's server on this shared host, which silently served a different API. I re-ran on a verified-free port. Any external spot-checks should likewise confirm the port is free rather than trusting a fixed one.

### Orchestrator review of the Step 7 hand-back (and the re-opened iteration)

Per the "verify subagent hand-back claims against source" rule, I audited all three fixes rather than accepting the summary.

**Rejected as reported — the `routes/assumptions.py` fix.** The first summary claimed the reject-path radius error was PRD-silent and cited the difficulty recipe as authority for deleting it. Both grounds were wrong. PRD.md line 238 is *in the reject paragraph* and reads verbatim: "A `FundingAnalyst` rejects a request when the incoming `incoming_credit_score` is strictly below the credit floor of 620, or when the `residence_state_code` is outside the relocation service radius; a residence outside the radius is refused with `ERR_RESIDENCE_OUTSIDE_SERVICE_RADIUS`." So the reject-path radius error is PRD VERBATIM-COVERED by STEP 1a. Citing `SCAFFOLD_DIFFICULTY_DESIGN.yaml` as authority also violated the isolation contract (implementers read PRD.md only), and the recipe in fact asserts only that the count advances and the state cycles — it says nothing about a no-fault reject's response. I sent the loop owner a re-open message (STEP 2, not STEP 3 — the FIXTURE was the bug). Outcome: `routes/assumptions.py` now restores the reject-path radius raise; `test_suite/test_07_assumption_and_relocation.py`'s fixture changed from `_open_out_of_radius_assumption()` (AZ, 700 — which PRD *requires* the reject to refuse) to `_open_rejectable_assumption()` (TX, `incoming_credit_score=580`), taking PRD §3.9's *other* declared reject reason. No assertion weakened; both tests keep their `Difficulty/non_linear_state_machine/assumption_request_failed_negotiation_round_cycle` tag and their `rejection_count` 1→2 / `PENDING_NEGOTIATION` asserts. The loop owner also flagged a factual error in *my* review: the code had deleted the radius raise, not the healthy-request refusal, so my instruction as literally written would have been a no-op. It implemented the intended end state — removed the uncited `ERR_INVALID_STATE` refusal of a healthy reject **and** restored the radius raise. I verified both in source.

**Accepted — the `fund_contract` gate-refusal envelope.** Traced to PRD §2.10's rejection ordering plus the §5 status rows, with the `CANCELLED` / `cancelled_from_status: PENDING_VALIDATION` / `validation_failure_code` freeze side effect preserved. PRD-supported.

**Accepted — the `legal_name` fixture forwarding.** Purely additive; PRD §3.1 requires `legal_name` on dealer registration.

**Orchestrator re-run of the sweep.** The loop owner removed `results.*.json` when it re-verified manually, leaving no durable sweep artifact. I re-ran the full 8-round parallel sweep myself and independently confirmed **48/48 passed, 0 failed in all 8 rounds**. The `results.{1..8}.json` files now on disk are my run's.

**Step 7 diff carried into Step 8** (this is the Step 8 focus list — 0 deletions, 1 `test_suite/` fix, 1 `test_helpers/` fix, 2 `implementation/` fixes):
- DELETIONS: none.
- `test_helpers/fixtures.py` — `setup_package_with_contract()` gained a forwarded `legal_name` parameter (was causing 8 setup TypeErrors). Pure fixture bug; no PRD silence.
- `test_suite/test_07_assumption_and_relocation.py` — `_open_out_of_radius_assumption()` → `_open_rejectable_assumption()`, taking the below-floor reject reason instead of the out-of-radius one. Fixture corrected to satisfy the PRD-required reject-path radius guard; no assertion changed.
- `implementation/routes/assumptions.py` — `reject_assumption`: restored the PRD §3.9 reject-path `ERR_RESIDENCE_OUTSIDE_SERVICE_RADIUS` raise; removed an uncited `ERR_INVALID_STATE` refusal of healthy rejects. The `ACCEPTED → PENDING_NEGOTIATION` withdrawal branch and the 3rd-reject → `REJECTED` terminal branch are unchanged.
- `implementation/routes/contracts.py` — `fund_contract`: a gate failure now raises `ApiError(failure)` (error envelope) instead of returning HTTP 200 with a `validation_failure_code` body; the freeze side effect is unchanged and still committed.
- PRD-silence sites this diff exposes (for Step 8, and distinct from the Step 6 adjudication list): (i) PRD §3.9's reject paragraph names the radius refusal but the PRD never states what a *healthy* reject does — the implementation now lets it succeed, which Step 8 must pin; (ii) PRD §3.4/§2.10 name the gate errors but the PRD's §3.4 text describes the freeze side effect for a failed gate while leaving the *response shape* of a refused fund to §2.10/§5 — the implementation returns the error envelope, which Step 8 should make explicit.

## Step 8: Finalize PRD — 2026-09-30T22:15:00.000Z

Both edits are in place and verified. Final report (as corrected after orchestrator review — see below):

## Result

`PRD_FINALIZED.md` created at `workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md 391 → PRD_FINALIZED.md 391 (0.0% line delta); 11,686 → 11,757 words (+71, +0.61%). No new sections; prose kept verbatim except the two edited passages.

**Changes (2 edits; 5 diff items reduced to 2 PRD-silence/mismatch sites):**

- **§3.9** — *revise* — Reject paragraph rewritten. Final corrected text: "The reject act's only request-side refusal is an out-of-radius residence, refused with `ERR_RESIDENCE_OUTSIDE_SERVICE_RADIUS`; it consults no `incoming_credit_score` at all. A request in `PENDING_NEGOTIATION` whose residence lies inside the radius records a rejection regardless of its incoming credit score." *(Corrects PRD.md, which wrongly said the reject fires on score<620 and never pinned the healthy case; matches `implementation/routes/assumptions.py:76-104` — radius raise at :92-93, count/loop/terminal at :94-104, ACCEPTED→PENDING_NEGOTIATION at :82-87.)*
- **§3.4** — *insert* — Appended one sentence to the "fails a gate" paragraph of §3.4: on the single-contract fund route the freeze is committed first, then the request is answered with the §2.2 error envelope (`response_type: "error"`, `data.error_id` = the failing gate so it agrees with the frozen `validation_failure_code`, HTTP status per §5). *(Pins the response shape PRD.md left under-determined; matches `implementation/routes/contracts.py:103-106` + `implementation/errors.py:9-47` + `implementation/app.py:26-28`.)*

No PRD change was made for the two `test_helpers/` items — they are pure fixture bugs: the `legal_name` parameter (PRD §3.1 already requires it) and the `_open_rejectable_assumption` re-parameterisation (lets the §3.9 score reason reach the reject). No tests were deleted.

**Per-edit pre-edit search log:**

- **Edit 1** — (a) subject: assumption-request reject behavior. (b) Enumerated/read: `routes/assumptions.py:64-123` (`accept_assumption` score≥620; `reject_assumption` status guard, ACCEPTED-withdrawal, radius-only check, count/loop/terminal; `complete_assumption` score+radius+surviving+watch); `services/calculations.py:39` (`RELOCATION_RADIUS`); `services/factory.py:252-253`; `test_suite/test_07` (score 580, state TX → expects count 1→2 / PENDING_NEGOTIATION); confirmed no `incoming_credit_score` reference exists in `reject_assumption`. (c) Wording adjustment (final round): scoped the record clause to a request **in `PENDING_NEGOTIATION`** rather than "any in-radius request", because the `ACCEPTED` in-radius branch (:82-87) withdraws without recording a rejection — the broader phrasing would have mis-described that success path. Added no recording clause to the refusal, and removed the below-floor baseline so the paragraph no longer references a reject class it does not define. The accept-path floor sentence elsewhere in §3.9 was left verbatim and remains consistent with `accept_assumption:69-70`.
- **Edit 2** — (a) subject: response shape of a refused single-contract fund (`POST /contracts/{id}/fund`). (b) Enumerated/read: `routes/contracts.py:94-108` (`fund_contract`: stale → `ERR_CONTRACT_NOT_PENDING` → `first_failing_gate` → `freeze_contract` → `raise ApiError(failure)`); `services/workflows.py:21-41` (`first_failing_gate` order), `:79-90` (`freeze_contract` side effects); `app.py:26-45` (error handlers); `errors.py:9-47` (gate→status); and the package analogues `routes/dealers.py:243-280` / `services/workflows.py:93-150` (read only to confirm no contradiction). (c) Adjustment: scoped the sentence to "the single-contract fund route" rather than a universal claim over all freezes, because the package-fund route returns `ERR_NO_FUNDABLE_CONTRACT`/`ERR_FUNDING_WINDOW_EXPIRED` envelopes distinct from the individual gate frozen into a child's `validation_failure_code` — the looser scoping leaves both paths correctly described.

No new mismatch introduced: verified no other passage contradicts the revised reject semantics or the newly-pinned error-envelope wording (checked all `validation_failure_code` and fund-endpoint mentions).

### Orchestrator review of the Step 8 hand-back

Per the "verify subagent hand-back claims against source" rule I audited both edits against `PRD.md`, `PRD_FINALIZED.md` and the implementation.

**§3.4 insert — accepted.** Cleanly scoped to the single-contract fund route, does not over-claim across the package-fund analogue, and matches `fund_contract`'s commit-then-raise ordering.

**§3.9 rewrite — sent back once for a self-contradiction.** The first version read: "A `FundingAnalyst` rejects a request in `PENDING_NEGOTIATION` whose `residence_state_code` is outside the relocation service radius; such a request is refused with `ERR_RESIDENCE_OUTSIDE_SERVICE_RADIUS` and no rejection is recorded. A request whose residence lies inside the radius is rejected exactly as a below-floor one is, regardless of its `incoming_credit_score`, because the reject act itself does not re-test the credit floor…". Three defects: (1) sentence 1 said a `FundingAnalyst` *rejects* an out-of-radius request and then that the same request is *refused* — mutually exclusive outcomes (a rejection is a 200 recording a counter-offer; a refusal is a 422 recording nothing), which is exactly the ambiguity Step 8 exists to remove; (2) "and no rejection is recorded" was a phantom clause inherited from my diff note where it described the implementation's *comment*, not its behavior — vacuous in a refusal path and implying a refusal could otherwise leave a rejection behind; (3) sentence 2 was built on a reason that no longer exists — "rejected exactly as a below-floor one is … does not re-test the credit floor" presupposes some other actor tests the floor on reject, but nothing does, so the paragraph referenced a reject class it never defines. I sent the re-open with the corrected semantics (the reject act consults no `incoming_credit_score` at all; sole request-side refusal is the radius; any in-radius `PENDING_NEGOTIATION` request records a rejection regardless of score) and asked for the pre-edit search to re-confirm the `accept_assumption` floor gate at :64-75 still holds so the new wording could not be read as skipping it. The corrected text is verified in place at `PRD_FINALIZED.md:238`; the `accept_assumption` floor is untouched in §3.9 and the implementation still enforces it.

**Scope check:** no `test_suite/`, `test_helpers/` or `implementation/` writes post-date the Step 7 sweep — only `PRD_FINALIZED.md`, `PRD.md` and `INSTRUCTION.md` exist in `workspace/` alongside `implementation/`. Step 7's 48/48 result remains valid.

## Interruption notice — 2026-10-01T04:06:00.000Z

The host killed all background processes under memory pressure mid-pipeline. On restart I audited the task directory: Steps 1–8 are complete and their artifacts intact (`SCAFFOLD*.yaml`, `test_helpers/` 9 files, `test_suite/` 11 files, `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/implementation/` 24 files), and the Step 7 sweep's `results.{1..8}.json` still showed 48/48. Step 9 was the only incomplete step: `workspace/PRD_COMPLETED.md` existed but was a byte-identical copy of `PRD_FINALIZED.md` (same md5 `cdd5bfae1fcafccf825d2235a0d4c944`), i.e. the `cp` had run and the edits had not. Step 9 was therefore redone from scratch.

## Step 9: Complete PRD — 2026-10-01T04:30:00.000Z

The work is complete. All edits are confined to `workspace/PRD_COMPLETED.md` (only that file was written; implementation/, test_suite/, test_helpers/ are untouched, verified by mtime).

## Report

**Source vs output**
- `workspace/PRD_FINALIZED.md`: 391 lines / 86,183 chars
- `workspace/PRD_COMPLETED.md`: 393 lines / 97,538 chars
- Char delta: **+11,355** (line delta +2: two added §4 table rows)

**Counts**: **31 ambiguity-pins**, **9 mismatch-revisions** (40 edits total)

**Changes (PRD section — insert/revise — class — what changed — impl anchor)**
- §2.6 — revise — mismatch — `holdback_rate` outside [0.0,0.5] returns `ERR_INVALID_REQUEST` via the declared-range check; `ERR_HOLDBACK_RATE_EXCEEDS_CEILING` is catalogue-only — `routes/dealers.py:32,37`
- §2.8 — insert — ambiguity — version guard optional (omitted ⇒ no staleness refusal) and compared before the state guard — `routes/dealers.py:64-66,203-205,249-253`
- §2.9 — revise — mismatch — `L` = FUNDED packages with `closed_at` in window (not `charged_back_count`); `D` = contracts CANCELLED-from-ACTIVE with valid inadvertent alarm — `services/calculations.py:129-159`
- §2.9 — revise — ambiguity — standing gate ordering (SUSPENDED → rate cap → reference duplicate) — `routes/dealers.py:138-143`
- §2.10 — revise — mismatch — removed the phantom "or whose children carry no monitoring account" clause; empty package ⇒ `ERR_MONITORING_ACCOUNT_NOT_FOUND` — `routes/dealers.py:207-208,256-258`
- §2.10 — insert — ambiguity — empty-package rule consults package status first — `routes/dealers.py:205-208`
- §2.10 — insert — ambiguity — stale observation compared before state guard — `routes/dealers.py:203-205`
- §3.1 — insert — ambiguity — reinstatement on non-zero balance or non-SUSPENDED ⇒ `ERR_INVALID_STATE` — `routes/dealers.py:84-88`
- §3.2 — insert — ambiguity — package-creation ownership (`ERR_INVALID_REQUEST`/`ERR_ENTITY_NOT_FOUND`) and gate ordering — `routes/dealers.py:127-143`
- §3.2 — insert — ambiguity — declaration validates field shape first (incl. 2-char `state_code`) and raises `ERR_SERVICE_WINDOW_OVERLAP` for inline crews — `routes/contracts.py:22-63`
- §3.3 — insert — ambiguity — approval runs the funding fee on zero-capex children; records `allowed_holdback_rate_ceiling_cents` + `approved_holdback_cents` — `routes/dealers.py:218-222`
- §3.3 — insert — ambiguity — empty-composition refused with `ERR_MONITORING_ACCOUNT_NOT_FOUND` — `routes/dealers.py:207-208,256-258`
- §3.4 — insert — ambiguity — funding credits the dealer's `holdback_reserve_cents` with `holdback_cents` — `services/workflows.py:51`
- §3.4 — revise — mismatch — freezing runs **no** dealer rate recompute and leaves the dealer row untouched — `services/workflows.py:79-90`
- §3.4 — insert — ambiguity — `contract_number` minting; package fund refreshes `funded_package_count` — `services/workflows.py:58-60,71-75`
- §3.5 — insert — ambiguity — installation `duration_minutes` default 180; engineer required with schedule — `routes/contracts.py:45-50`, `routes/monitoring.py:30`
- §3.5 — insert — ambiguity — overlap half-open; non-`FAILED` slots occupy the engineer — `services/workflows.py:456-471`
- §3.5 — revise — mismatch — transfer guard is a current `OCCUPIED` site (not `account.site_id`), from `UNPROVISIONED` only, and it marks `activation_committed` — `routes/monitoring.py:152-172`
- §3.5 — insert — ambiguity — completion gate (`activation_committed`/`activation_gate_met`) and `equipment_config_code` stamp — `routes/monitoring.py:62-70`
- §3.5 — insert — ambiguity — failure only from `SCHEDULED`; `reason` recorded — `routes/monitoring.py:85-88`
- §3.5 — insert — ambiguity — waiver state guard and boolean shape check — `routes/monitoring.py:104-111`
- §3.6 — insert — ambiguity — sweep visits only `ACTIVE` contracts — `services/workflows.py:218-220`
- §3.6 — insert — ambiguity — `SUSPEND` cascade only from `PROVISIONED` — `services/workflows.py:239`
- §3.6 — insert — ambiguity — restore guards `ERR_INVALID_STATE`; delinquency object fields — `routes/contracts.py:144-152,203-212`
- §3.7 — insert — ambiguity — omitted `entered_at_utc` stored as substituted `occurred_at`; outside-window flag false — `routes/alarms.py:33-40`
- §3.7 — insert — ambiguity — legal-hold guards; dispatch-on-verified; release requires `PROVISIONED`; `abort_reason` default "" — `routes/alarms.py:78-95,107-108,137-139`
- §3.7 — insert — ambiguity — auto-raise dedups open `SERVICE_REQUIRED` — `services/workflows.py:340-342`
- §3.8 — revise — mismatch — occupied slot uses `allowed_duration_minutes` (default 60), not `duration_minutes`; cancel-after-instant ⇒ `ERR_INVALID_STATE` — `routes/visits.py:61,99-103`
- §3.8 — insert — ambiguity — `billed_cents` recorded on both routes; no sweep inside warranty — `routes/visits.py:80-89`
- §3.8 — insert — ambiguity — 15000 gate admits every funded contract (base = 3×capex) — `services/calculations.py:27`, `services/workflows.py:195`
- §3.9 — revise — mismatch — sites are minted only at origination; assumption completion vacates and creates **no** replacement site — `services/factory.py:110`, `services/workflows.py:381-384`
- §3.10 — insert — ambiguity — cancel/backlog refusals are `ERR_INVALID_STATE` — `routes/contracts.py:113-119`
- §3.10 — insert — ambiguity — site vacate, chargeback-at-cancel, `updated_at`, terminal definition — `services/workflows.py:173-206`
- §3.10 — revise — mismatch — chargeback window = **30 days**; `dealer_id` null ⇒ `ERR_CHARGEBACK_WINDOW_CLOSED` — `services/calculations.py:267`, `routes/contracts.py:127-128`
- §3.10 — insert — ambiguity — chargeback fires once per contract; preview read-only with same decision codes — `services/calculations.py:256-262,270-287`
- §3.10 — revise — mismatch — rescission cancels via the ordinary path (no sweep/chargeback); `decided_at`; guard ordering — `services/workflows.py:396-425`
- §3.10 — insert — ambiguity — abuse flag is a parameter, unreachable via the API — `services/calculations.py:331,340-341`
- §4 — insert — ambiguity — `GET /health` liveness read — `app.py:48-50`
- §4 — insert — ambiguity — added `/contracts/{id}/delinquency` row — `routes/contracts.py:203`
- §4 — insert — ambiguity — added `/rescission-requests/{id}/approve` row — `routes/assumptions.py:180`

**Key corrections worth flagging**: the nine mismatch-revisions are the load-bearing ones — an implementer reading only the old PRD would have gotten the chargeback window undefined, the DEALER `L`/`D` counters wrong, the holdback-rate error code wrong, the freeze-cascade side effect wrong, the monitoring-transfer guard wrong, the visit-slot duration wrong, the relocation site minting wrong, the rescission cancellation pathway wrong, and the package empty-composition rule wrong. Note that §3.10's rescission sentence ("cancels the contract with `cancelled_from_status` of `ACTIVE`") was left as-is because it is self-consistent for the in-window contracts the approval path admits; I only added that the cancellation runs through the ordinary path with the status actually held.

### Orchestrator review of the Step 9 hand-back

Step 9 stayed in scope — the only file written was `PRD_COMPLETED.md`; no `implementation/`, `test_suite/` or `test_helpers/` mtime post-dates the sweep. `PRD_COMPLETED.md` is complete (5 top-level sections, 80 changed lines vs `PRD_FINALIZED.md`, ends mid-table on the §5 error catalogue's last row — i.e. the file is whole, not truncated).

Per the "verify subagent hand-back claims against source" rule I spot-checked five of the load-bearing anchors directly:
1. **`CHARGEBACK_WINDOW_DAYS = 30`** — confirmed at `services/calculations.py:267`, used at :253 and :280. Reconciles the Step 5 skip (which correctly refused to assert an unvalued constant) with the Step 6 adjudication.
2. **`holdback_rate` range check shadows the ceiling error** — confirmed: `routes/dealers.py:32` calls `as_number(..., 0.0, 0.5)` whose `maximum` violates at `middleware.py:151-153` with `ERR_INVALID_REQUEST` *before* the `> 0.5` branch at :36-37 can fire. `ERR_HOLDBACK_RATE_EXCEEDS_CEILING` is genuinely catalogue-only (declared at `errors.py:42`, raised nowhere reachable). Step 9's "mismatch" classification is right, and no test asserts that error as a live outcome — only the §2.10 bullet-list citation in `test_03`'s docstring. Not a defect for this pipeline (it matches the implementation), but it IS a residual unreachable-code smell in `implementation/` and a candidate for a future hardening pass.
3. **Visit slot uses `allowed_duration_minutes`** — confirmed at `routes/visits.py:61` (`visit.get("allowed_duration_minutes", 60) or 60`), passed into `technician_overlap` at :62. Note this is the *service-visit* path at its own default of 60; the installation path's 180 default is a separate field, as Step 9 documents separately.
4. **`L`/`D` counter selection** — confirmed at `services/calculations.py:129-159`: `L` counts FUNDED packages with `closed_at` in the trailing window, `D` counts contracts CANCELLED-from-`ACTIVE` carrying a valid inadvertent alarm with `cancelled_at` in window. The PRD's §2.9 field descriptions had these inverted relative to the calculation; Step 9 pinned the calculation's semantics, which is what ships.
5. **Monitoring-transfer guard and freeze cascade** — confirmed: `routes/monitoring.py:152-172` requires a current `OCCUPIED` site and `UNPROVISIONED` state, then sets `activation_committed` on the contract's `SCHEDULED` installations; `services/workflows.py:79-90` freezes the gate into the row and refreshes only the parent package — no dealer recompute, matching Step 9's mismatch-revision.

### Final certification

After the interruption I re-ran the full 8-round parallel stability sweep against the frozen end state: **48/48 passed, 0 failed, 0 errors in every round**. The `results.{1..8}.json` now on disk are that final run's. The pipeline is complete: `SCAFFOLD.yaml` + `SCAFFOLD_DIFFICULTY_DESIGN.yaml` + `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 files) + `test_suite/` (11 files, 48 tests), and `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}` (24 files, 3,338 lines, in-memory storage, `start.sh` boots fresh on every invocation).