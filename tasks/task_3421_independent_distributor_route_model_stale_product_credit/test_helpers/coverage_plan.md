# Coverage Plan — task_3421 Independent Distributor Route Model & Stale Product Credit

Stage 2 reads this plan to create `test_suite/` test files. Every non-stub
instance from §1.8 (queue A, Difficulty) and §1.9 (queue B, Corner) is mapped
to exactly one target test file below. Queue A instances get **≥2 tests each**;
queue B instances get **≥1 test each**. All docstrings carry the mandatory
PRD citation plus the `Design: Difficulty/<rule_id>/<name>` or
`Design: Corner/<section>/<name>` tag copied verbatim from the source YAML.

## Census

| Queue | Instances | Planned | Excluded stubs | SKIP |
|---|---|---|---|---|
| A — Difficulty (§1.8) | 18 | 18 | — | 0 |
| B — Corner (§1.9) | 41 | 36 | 5 | 0 |
| **Total** | **59** | **54** | **5** | **0** |

PRD-first two-condition filter was applied to every instance: all 54 non-stub
instances have verbatim PRD coverage (rule-bearing sentences located in §2.1,
§2.3, §2.5–§2.10, §3.1–§3.8, §4) and a uniquely-derivable outcome. No instance
required SKIP.

Conventions relied on (both derivable from PRD alone, stated here so Stage 2
does not re-litigate them):
- `version` starts at 1 on creation and increments by one on every mutation
  (PRD §2.5; creation is the first mutation). OCC flows always re-read the
  parent version from responses instead of assuming absolute values where the
  instance recipe does so; literal version assertions only appear where the
  instance itself pins them (e.g. agreement version 6 after six mutations).
- Paginated `total_count` counts the filtered result set (PRD §2.3 meta fields
  describe the list response actually returned; the filtered reading is the
  only one coherent with `has_more`).
- Every test starts on an empty database with the logical clock at
  2026-09-01T00:00:00Z (PRD §2.4); fixtures re-pin the clock explicitly.

## Target test files (11 files, reading order simple → complex)

### test_01_structure_and_defaults.py — creation shape, defaults, 404 (6)
| Instance | Queue tag |
|---|---|
| entities / bakery_create_returns_every_declared_field | Corner |
| entities / distributor_create_applies_system_defaults | Corner |
| entities / production_day_capacity_defaults_and_override | Corner |
| entities / order_create_units_total_input_ignored | Corner |
| state_machines / new_order_starts_draft_with_null_computed_fields | Corner |
| entities / agreement_get_unknown_id_returns_not_found | Corner |

### test_02_auth_and_rbac.py — headers, roles, ownership scope (5)
| Instance | Queue tag |
|---|---|
| validations / missing_auth_header_returns_400 | Corner |
| rbac / distributor_cannot_decide_claim_returns_forbidden | Corner |
| rbac / route_ops_cannot_issue_credit_returns_forbidden | Corner |
| rbac / distributor_b_cannot_read_distributor_a_orders | Corner |
| rbac / route_ops_cannot_reinstate_classification_suspension | Corner |

### test_03_agreement_formation.py — FK order, overlap, point-date, activation gate (4)
| Instance | Queue tag |
|---|---|
| validations / agreement_body_fk_checked_in_declared_input_order | Corner |
| resource_temporal_overlap / production_day_point_date_uniqueness | Difficulty |
| resource_temporal_overlap / distributor_agreement_half_open_interval_overlap | Difficulty |
| cross_entity_state_dependency / activate_blocked_until_financing_disbursed | Difficulty |

### test_04_suspension_and_reinstatement.py — suspend/reinstate loop, cross-entity gates (4)
| Instance | Queue tag |
|---|---|
| non_linear_state_machine / agreement_suspend_reinstate_cycle_with_classification | Difficulty |
| cross_entity_state_dependency / order_submit_blocked_when_agreement_suspended | Difficulty |
| priority_pair_validation_conflict / order_submit_state_gate_beats_lead_time | Difficulty |
| validations / claim_blocked_only_for_classification_suspension | Corner |

### test_05_financing.py — plans, disburse, payments, OCC, delinquency (5)
| Instance | Queue tag |
|---|---|
| non_linear_state_machine / financing_delinquency_cure_cycle_via_close | Difficulty |
| transitive_cascade / production_close_delinquency_standing_cascade | Difficulty |
| calculations / weekly_payment_annuity_constant_pinned | Corner |
| errors / second_plan_with_live_plan_rejected | Corner |
| cross_cutting_complexity_layers / occ_plan_create_stale_then_fresh_supersedes | Corner |

### test_06_orders_and_capacity.py — confirm/cancel capacity, OCC, close gate, pagination (6)
| Instance | Queue tag |
|---|---|
| boundary_precision_check / confirm_capacity_exact_fit_allowed_one_over_rejected | Difficulty |
| compensating_invariant / confirm_cancel_capacity_conservation | Difficulty |
| cross_cutting_complexity_layers / occ_confirm_stale_version_412 | Corner |
| state_machines / cancel_submitted_order_releases_nothing | Corner |
| endpoints / close_future_production_day_rejected | Corner |
| cross_cutting_complexity_layers / orders_list_pagination_filter_interaction | Corner |

### test_07_delivery_and_settlement.py — charges, shortages, credit limit, settlement (6)
| Instance | Queue tag |
|---|---|
| combinatorial_formula / delivery_charge_per_line_then_sum_rounding_order | Difficulty |
| calculations / shortage_credit_prorated_per_line | Corner |
| state_machines / record_delivery_before_day_close_rejected | Corner |
| validations / record_delivery_over_credit_limit_returns_fiscal_error | Corner |
| consistency_model / delivery_charge_visible_immediately_in_same_sequence | Corner |
| calculations / settlement_week_fields_and_reconciliation | Corner |

### test_08_retail_audits.py — audit scores, strikes, auto-suspend cascade (4)
| Instance | Queue tag |
|---|---|
| transitive_cascade / audit_strike_auto_suspend_cascade_releases_capacity | Difficulty |
| boundary_precision_check / audit_score_70_passes_69_violates_component_level | Difficulty |
| entities / audit_score_out_of_range_returns_400 | Corner |
| endpoints / audit_post_returns_account_with_appended_log | Corner |

### test_09_stale_claims.py — provisional vs capped credit, resubmit, weekly cap (4)
| Instance | Queue tag |
|---|---|
| dual_variant_calc / stale_credit_provisional_uncapped_vs_final_capped | Difficulty |
| state_machines / claim_needs_info_resubmit_recomputes_provisional | Corner |
| calculations / stale_cap_full_partial_then_exhausted | Corner |
| state_machines / decide_on_needs_info_claim_not_reviewable | Corner |

### test_10_order_and_claim_input_validation.py — 400/422 input rules (5)
| Instance | Queue tag |
|---|---|
| priority_pair_validation_conflict / claim_submit_sku_referential_beats_window_temporal | Difficulty |
| entities / order_create_unknown_sku_returns_sku_unknown | Corner |
| entities / claim_create_missing_items_returns_invalid_request | Corner |
| validations / claim_qty_over_delivered_returns_qty_exceeded | Corner |
| validations / claim_pulled_before_shelf_end_returns_not_stale_yet | Corner |

### test_11_exit_and_transfer.py — valuation variants, payoff, settle, resale loop (5)
| Instance | Queue tag |
|---|---|
| dual_variant_calc / transfer_valuation_voluntary_vs_for_cause_variants | Difficulty |
| combinatorial_formula / transfer_settle_pinned_evaluation_order | Difficulty |
| compensating_invariant / transfer_settle_valuation_equals_payoff_plus_payout | Difficulty |
| state_machines / settled_transfer_rejects_second_settle | Corner |
| state_machines / territory_relisted_after_settle_sells_to_new_distributor | Corner |

## Excluded stubs (queue B `excluded_because:` — NOT translated; owner resolves)

| Stub instance | Owning difficulty instance | Status |
|---|---|---|
| state_machines / claim_auto_expiry_at_close_covered | production_close_delinquency_standing_cascade | cross-reference resolves |
| state_machines / third_strike_auto_suspension_covered | audit_strike_auto_suspend_cascade_releases_capacity | cross-reference resolves |
| state_machines / valuation_variant_divergence_covered | transfer_valuation_voluntary_vs_for_cause_variants | cross-reference resolves |
| state_machines / capacity_exact_boundary_covered | confirm_capacity_exact_fit_allowed_one_over_rejected | cross-reference resolves |
| state_machines / state_vs_temporal_priority_covered | order_submit_state_gate_beats_lead_time | cross-reference resolves |

All five `difficulty_instance` pointers resolve to real `name:` entries in
SCAFFOLD_DIFFICULTY_DESIGN.yaml; the owning instances are planned above.

## Fixture reuse map (Stage 2 must import, not re-invent)

| Recipe chain prefix | Fixture in test_helpers/fixtures.py |
|---|---|
| clock + bakery + territory(LISTED) + distributor + cash agreement + activate | `setup_active_cash_agreement()` |
| same but financed (plan created, disbursed, then activate) | `setup_active_financed_agreement()` |
| production day + order + submit + confirm | `setup_confirmed_order(ctx, delivery_date, lines)` |
| ... + close day + record-delivery | `setup_delivered_order(ctx, delivery_date, lines, ...)` |
| ... + file claim at a chosen clock | `setup_submitted_claim(ctx, ..., file_clock)` |
| ... + decide APPROVE | `setup_approved_claim(ctx, ..., file_clock)` |
| agreement exit (VOLUNTARY/FOR_CAUSE) + PENDING transfer | `setup_exiting_agreement(financed=..., mode=..., exit_clock=...)` |
| ... + settle (agreement EXITED, territory AVAILABLE) | `setup_settled_transfer(...)` |
| retail account create / audit post | `create_retail_account`, `post_audit`, `post_violation_audit`, `post_passing_audit` |
| single transitions | `suspend_agreement`, `reinstate_agreement`, `exit_agreement`, `submit_order`, `confirm_order`, `cancel_order`, `record_delivery`, `reconcile_order`, `decide_claim`, `resubmit_claim`, `issue_credit`, `settle_transfer`, `close_production_day`, `set_clock` |

Identity threading: every Distributor-role call inside fixtures uses
`make_distributor_headers(distributor["id"])` (PRD §2.1 entity-backed
identity); Stage 2 tests must do the same for ownership-gated calls and must
never use the shared `TEST_USERS["distributor_headers"]` fallback for them.
