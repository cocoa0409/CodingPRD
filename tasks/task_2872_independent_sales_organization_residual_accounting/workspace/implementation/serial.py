"""Response serializers: exact field sets per entity (PRD 2.4 / scaffold entities)."""
from decimal import Decimal

import calc


def _num(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row, out):
    out["created_at"] = row["created_at"]
    out["updated_at"] = row["updated_at"]
    out["version"] = row["version"]
    return out


def program(row):
    return _common(row, {
        "id": row["id"],
        "name": row["name"],
        "buy_rate_bps": row["buy_rate_bps"],
        "buy_rate_per_item_cents": row["buy_rate_per_item_cents"],
        "assessment_bps": row["assessment_bps"],
        "normalization_mode": row["normalization_mode"],
        "minimum_billing_mode": row["minimum_billing_mode"],
        "status": row["status"],
        "posted_batch_count": calc.posted_batch_count(row["id"]),
    })


def agent(row):
    total, _active, _attrited = calc.portfolio_counts(row["id"])
    bps = calc.portfolio_attrition_bps(row["id"])
    return _common(row, {
        "id": row["id"],
        "name": row["name"],
        "parent_agent_id": row["parent_agent_id"],
        "split_pct": _num(row["split_pct"]),
        "override_pct": _num(row["override_pct"]),
        "vesting_start_date": row["vesting_start_date"],
        "status": row["status"],
        "departure_effective_date": row["departure_effective_date"],
        "hierarchy_depth": row["hierarchy_depth"],
        "vested_pct": calc.vested_pct(row),
        "vested_pct_at_departure": row["vested_pct_at_departure"],
        "residual_hold": bps >= 2500,
        "portfolio_attrition_bps": bps,
        "lifetime_clawback_cents": calc.lifetime_clawback_cents(row["id"]),
        "trailing_residual_cents": calc.trailing_residual_cents(row["id"]),
        "advance_outstanding_cents": calc.advance_outstanding_cents(row["id"]),
        "portfolio_merchant_count": total,
    })


def portfolio_summary(row):
    total, active, attrited = calc.portfolio_counts(row["id"])
    bps = calc.portfolio_attrition_bps(row["id"])
    return {
        "agent_id": row["id"],
        "portfolio_merchant_count": total,
        "active_merchant_count": active,
        "attrited_merchant_count": attrited,
        "portfolio_attrition_bps": bps,
        "residual_hold": bps >= 2500,
        "vested_pct": calc.vested_pct(row),
        "trailing_residual_cents": calc.trailing_residual_cents(row["id"]),
        "advance_outstanding_cents": calc.advance_outstanding_cents(row["id"]),
        "lifetime_clawback_cents": calc.lifetime_clawback_cents(row["id"]),
    }


def merchant(row):
    return _common(row, {
        "id": row["id"],
        "owning_agent_id": row["owning_agent_id"],
        "processor_program_id": row["processor_program_id"],
        "mid": row["mid"],
        "monthly_minimum_cents": row["monthly_minimum_cents"],
        "per_transaction_fee_cents": row["per_transaction_fee_cents"],
        "equipment_lease_monthly_cents": row["equipment_lease_monthly_cents"],
        "upfront_bonus_cents": row["upfront_bonus_cents"],
        "boarded_on": row["boarded_on"],
        "status": row["status"],
        "attrition_date": row["attrition_date"],
        "reactivation_date": row["reactivation_date"],
        "clawed_back_bonus_cents": calc.clawed_back_bonus_cents(row["id"]),
    })


def batch(row):
    return _common(row, {
        "id": row["id"],
        "processor_program_id": row["processor_program_id"],
        "period_month": row["period_month"],
        "coverage_start": row["coverage_start"],
        "coverage_end": row["coverage_end"],
        "file_checksum": row["file_checksum"],
        "state": row["state"],
        "line_count": row["line_count"],
        "gross_volume_cents": row["gross_volume_cents"],
        "total_normalized_net_revenue_cents": row["total_normalized_net_revenue_cents"],
        "iso_retained_cents": row["iso_retained_cents"],
        "posted_at": row["posted_at"],
        "recall_count": row["recall_count"],
    })


def line(row):
    return _common(row, {
        "id": row["id"],
        "residual_batch_id": row["residual_batch_id"],
        "merchant_id": row["merchant_id"],
        "transaction_count": row["transaction_count"],
        "sales_volume_cents": row["sales_volume_cents"],
        "interchange_cents": row["interchange_cents"],
        "assessments_cents": row["assessments_cents"],
        "gross_income_cents": row["gross_income_cents"],
        "processor_cost_cents": row["processor_cost_cents"],
        "normalized_net_revenue_cents": row["normalized_net_revenue_cents"],
        "normalization_mode_applied": row["normalization_mode_applied"],
    })


def chargeback(row):
    """PRD 2.4: a ChargebackEvent carries only id and created_at."""
    return {
        "id": row["id"],
        "merchant_id": row["merchant_id"],
        "amount_cents": row["amount_cents"],
        "occurred_on": row["occurred_on"],
        "period_month": row["period_month"],
        "liability": row["liability"],
        "created_at": row["created_at"],
    }


def profitability(row):
    return _common(row, {
        "id": row["id"],
        "merchant_id": row["merchant_id"],
        "residual_batch_id": row["residual_batch_id"],
        "period_month": row["period_month"],
        "normalized_net_revenue_cents": row["normalized_net_revenue_cents"],
        "chargeback_cost_cents": row["chargeback_cost_cents"],
        "agent_chargeable_chargeback_cents": row["agent_chargeable_chargeback_cents"],
        "equipment_cost_cents": row["equipment_cost_cents"],
        "profit_cents": row["profit_cents"],
        "agent_basis_cents": row["agent_basis_cents"],
        "allocated_total_cents": row["allocated_total_cents"],
        "iso_retained_cents": row["iso_retained_cents"],
    })


def allocation(row):
    return _common(row, {
        "id": row["id"],
        "agent_id": row["agent_id"],
        "merchant_id": row["merchant_id"],
        "statement_id": row["statement_id"],
        "period_month": row["period_month"],
        "allocation_type": row["allocation_type"],
        "tier_level": row["tier_level"],
        "applied_pct": _num(row["applied_pct"]),
        "basis_cents": row["basis_cents"],
        "gross_allocation_cents": row["gross_allocation_cents"],
        "vesting_withheld_cents": row["vesting_withheld_cents"],
    })


def statement(row):
    return _common(row, {
        "id": row["id"],
        "agent_id": row["agent_id"],
        "period_month": row["period_month"],
        "lifecycle_state": row["lifecycle_state"],
        "settlement_state": row["settlement_state"],
        "direct_residual_cents": row["direct_residual_cents"],
        "override_residual_cents": row["override_residual_cents"],
        "minimum_true_up_cents": row["minimum_true_up_cents"],
        "gross_after_trueup_cents": row["gross_after_trueup_cents"],
        "advance_recoupment_cents": row["advance_recoupment_cents"],
        "adjustment_cents": row["adjustment_cents"],
        "opening_deficit_cents": row["opening_deficit_cents"],
        "net_payable_cents": row["net_payable_cents"],
        "carry_forward_deficit_cents": row["carry_forward_deficit_cents"],
        "issued_at": row["issued_at"],
        "paid_on": row["paid_on"],
        "hold_reason": row["hold_reason"],
    })


def adjustment(row):
    return _common(row, {
        "id": row["id"],
        "statement_id": row["statement_id"],
        "source_merchant_id": row["source_merchant_id"],
        "kind": row["kind"],
        "amount_cents": row["amount_cents"],
        "reason": row["reason"],
        "state": row["state"],
        "created_by_user_id": row["created_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "info_request_note": row["info_request_note"],
    })


def advance(row):
    return _common(row, {
        "id": row["id"],
        "agent_id": row["agent_id"],
        "advance_type": row["advance_type"],
        "recoupment_mode": row["recoupment_mode"],
        "principal_cents": row["principal_cents"],
        "recoupment_pct": _num(row["recoupment_pct"]),
        "amortization_months": row["amortization_months"],
        "first_recoupment_month": row["first_recoupment_month"],
        "last_recoupment_month": row["last_recoupment_month"],
        "funded_on": row["funded_on"],
        "outstanding_cents": row["outstanding_cents"],
        "cumulative_recouped_cents": row["cumulative_recouped_cents"],
        "months_recouped": row["months_recouped"],
        "state": row["state"],
    })
