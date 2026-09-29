"""Entity to JSON projections.

Resources carrying the common fields expose id, created_at, updated_at and
version. Eligibility footprint rows and stackability edges are append-only
configuration and carry only id and created_at (PRD 2.4).
"""

_COMMON = ("id", "created_at", "updated_at", "version")


def _base(entity, versioned=True):
    out = {"id": entity["id"], "created_at": entity["created_at"]}
    if versioned:
        out["updated_at"] = entity["updated_at"]
        out["version"] = entity["version"]
    return out


def _copy(entity, fields, versioned=True):
    out = _base(entity, versioned)
    for field in fields:
        out[field] = entity.get(field)
    return out


PROGRAM_FIELDS = (
    "program_code",
    "name",
    "incentive_type",
    "status",
    "effective_from",
    "effective_to",
    "per_unit_amount_cents",
    "apr_buydown_bps",
    "residual_support_bps",
    "stack_group",
    "priority_rank",
    "stack_cap_cents",
    "budget_cents",
    "tier_schedule",
    "tier_bonus_mode",
    "accrual_method",
    "projected_take_rate_bps",
    "committed_cents",
    "paid_cents",
    "accrued_budget_cents",
    "claimed_units",
    "per_unit_spend_cents",
    "residual_impact_bps",
    "submitted_by_user_id",
    "approved_by_user_id",
    "supersedes_program_id",
)

ELIGIBILITY_RULE_FIELDS = (
    "program_id",
    "model_code",
    "trim_code",
    "region_code",
    "build_date_from",
    "build_date_to",
    "min_msrp_cents",
    "max_msrp_cents",
    "allowed_deal_types",
)

STACK_EDGE_FIELDS = ("program_a_id", "program_b_id", "mode", "cap_amount_cents")

DEALER_FIELDS = (
    "dealer_code",
    "name",
    "region_code",
    "status",
    "historical_volume_units",
    "market_opportunity_bps",
    "paid_cents",
    "open_chargeback_cents",
)

OBJECTIVE_FIELDS = (
    "program_id",
    "dealer_id",
    "stretch_bps",
    "basis_units",
    "objective_units",
    "status",
    "protest_round",
    "achieved_units",
    "attainment_bps",
    "tier_attained",
    "payout_cents",
    "paid_payout_cents",
)

PROTEST_FIELDS = (
    "objective_id",
    "round_index",
    "claimed_basis_units",
    "reason",
    "status",
    "resolved_units",
    "resolved_by_user_id",
)

DELIVERY_FIELDS = (
    "dealer_id",
    "vin",
    "model_code",
    "trim_code",
    "build_date",
    "msrp_cents",
    "sale_date",
    "reported_at",
    "customer_region_code",
    "deal_type",
    "term_months",
    "contract_apr_bps",
    "base_residual_bps",
    "status",
    "reporting_lag_days",
    "back_dated_flag",
    "validated_by_user_id",
    "unwound_at",
)

CLAIM_FIELDS = (
    "delivery_id",
    "dealer_id",
    "program_id",
    "payment_batch_id",
    "claim_type",
    "claimed_amount_cents",
    "approved_amount_cents",
    "rate_basis",
    "snapshot_per_unit_cents",
    "validation_status",
    "payment_status",
    "rejection_error_id",
    "adjudicated_by_user_id",
    "paid_at",
)

BATCH_FIELDS = (
    "batch_code",
    "region_code",
    "period_start",
    "period_end",
    "scheduled_pay_date",
    "status",
    "claim_count",
    "total_cents",
    "held_claim_count",
    "disbursed_at",
)

CHARGEBACK_FIELDS = (
    "claim_id",
    "reason",
    "amount_cents",
    "status",
    "created_by_user_id",
    "recovered_at",
)

ACCRUAL_FIELDS = (
    "program_id",
    "period_month",
    "accrual_method",
    "entry_type",
    "unit_basis",
    "accrued_cents",
    "reversal_cents",
    "source_reference",
)

REPRICING_FIELDS = (
    "program_id",
    "mode",
    "new_per_unit_amount_cents",
    "effective_at",
    "previous_per_unit_amount_cents",
    "month_start",
    "affected_claim_count",
    "net_adjustment_cents",
)


def program(entity):
    return _copy(entity, PROGRAM_FIELDS)


def eligibility_rule(entity):
    return _copy(entity, ELIGIBILITY_RULE_FIELDS, versioned=False)


def stack_edge(entity):
    return _copy(entity, STACK_EDGE_FIELDS, versioned=False)


def dealer(entity):
    return _copy(entity, DEALER_FIELDS)


def objective(entity):
    return _copy(entity, OBJECTIVE_FIELDS)


def protest(entity):
    return _copy(entity, PROTEST_FIELDS)


def delivery(entity):
    return _copy(entity, DELIVERY_FIELDS)


def claim(entity):
    return _copy(entity, CLAIM_FIELDS)


def payment_batch(entity):
    return _copy(entity, BATCH_FIELDS)


def chargeback(entity):
    return _copy(entity, CHARGEBACK_FIELDS)


def budget_accrual(entity):
    return _copy(entity, ACCRUAL_FIELDS)


def repricing_event(entity):
    return _copy(entity, REPRICING_FIELDS)
