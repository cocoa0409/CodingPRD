"""Entity -> JSON projection.

Decimal fields are rendered with a fixed number of decimals so that, for
example, an adjustment of 0.125 never appears as 0.12500000000000003.
"""

from constants import QC_DEFECT_HOLD_NOTE
from numeric import dump_decimal

TWO = 2
THREE = 3
FOUR = 4


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def broker(row):
    payload = _common(row)
    payload.update({
        "legal_name": row["legal_name"],
        "nmls_id": row["nmls_id"],
        "home_state": row["home_state"],
        "status": row["status"],
        "financial_strength_score": dump_decimal(row["financial_strength_score"], TWO),
        "tier": row["tier"],
        "licensed_states": list(row["licensed_states"]),
        "approved_product_codes": list(row["approved_product_codes"]),
        "volume_expectation_cents": row["volume_expectation_cents"],
        "rolling_funded_volume_cents": row["rolling_funded_volume_cents"],
        "rolling_quality_score": dump_decimal(row["rolling_quality_score"], TWO),
        "open_defect_tier": row["open_defect_tier"],
        "exclusivity_status": row["exclusivity_status"],
        "active_loan_count": row["active_loan_count"],
        "total_active_compensation_commitment_cents": row["total_active_compensation_commitment_cents"],
        "suspended_reason": row["suspended_reason"],
    })
    return payload


def license(row):
    payload = _common(row)
    payload.update({
        "broker_id": row["broker_id"],
        "state_code": row["state_code"],
        "license_number": row["license_number"],
        "license_type": row["license_type"],
        "expires_on": row["expires_on"],
        "status": row["status"],
        "revoked_at": row["revoked_at"],
    })
    return payload


def financial_review(row):
    payload = _common(row)
    payload.update({
        "broker_id": row["broker_id"],
        "net_worth_cents": row["net_worth_cents"],
        "liquidity_cents": row["liquidity_cents"],
        "total_liabilities_cents": row["total_liabilities_cents"],
        "years_in_business": row["years_in_business"],
        "prior_year_funded_volume_cents": row["prior_year_funded_volume_cents"],
        "audit_attested": row["audit_attested"],
        "computed_financial_strength_score": dump_decimal(row["computed_financial_strength_score"], TWO),
        "attainment_band": row["attainment_band"],
        "status": row["status"],
        "is_current": row["is_current"],
    })
    return payload


def product_eligibility(row):
    payload = _common(row)
    payload.update({
        "broker_id": row["broker_id"],
        "product_code": row["product_code"],
        "max_ltv": dump_decimal(row["max_ltv"], FOUR),
        "min_fico": row["min_fico"],
        "max_loan_amount_cents": row["max_loan_amount_cents"],
        "status": row["status"],
        "approved_at": row["approved_at"],
    })
    return payload


def exclusivity_policy(row):
    payload = _common(row)
    payload.update({
        "broker_id": row["broker_id"],
        "competitor_identifier": row["competitor_identifier"],
        "competitor_name": row["competitor_name"],
        "effective_from": row["effective_from"],
        "effective_to": row["effective_to"],
        "status": row["status"],
        "breach_count": row["breach_count"],
        "restriction_scope": row["restriction_scope"],
    })
    return payload


def rate_sheet(row):
    payload = _common(row)
    payload.update({
        "broker_id": row["broker_id"],
        "product_code": row["product_code"],
        "base_rate_pct": dump_decimal(row["base_rate_pct"], THREE),
        "status": row["status"],
        "superseded_by_sheet_id": row["superseded_by_sheet_id"],
        "published_at": row["published_at"],
        "publish_sequence": row["publish_sequence"],
        "adjustment_table": [
            {
                "dim": entry["dim"],
                "bucket": entry["bucket"],
                "adjust_pct": dump_decimal(entry["adjust_pct"], THREE),
            }
            for entry in row["adjustment_table"]
        ],
    })
    return payload


def pricing_quote(row):
    """Immutable snapshot: id + created_at only, no version, no updated_at."""
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "rate_sheet_id": row["rate_sheet_id"],
        "broker_id": row["broker_id"],
        "product_code": row["product_code"],
        "representative_fico": row["representative_fico"],
        "ltv_ratio": dump_decimal(row["ltv_ratio"], FOUR),
        "occupancy_type": row["occupancy_type"],
        "loan_amount_cents": row["loan_amount_cents"],
        "lock_period_days": row["lock_period_days"],
        "loan_purpose": row["loan_purpose"],
        "overall_adjustment_pct": dump_decimal(row["overall_adjustment_pct"], THREE),
        "lock_adjustment_pct": dump_decimal(row["lock_adjustment_pct"], THREE),
        "note_rate_pct": dump_decimal(row["note_rate_pct"], THREE),
        "price_points": dump_decimal(row["price_points"], THREE),
        "adjustment_trace": [
            {
                "dim": entry["dim"],
                "bucket": entry["bucket"],
                "adjust_pct": dump_decimal(entry["adjust_pct"], THREE),
            }
            for entry in row["adjustment_trace"]
        ],
        "is_repriced": row.get("is_repriced", False),
    }


def loan_submission(row):
    payload = _common(row)
    payload.update({
        "broker_id": row["broker_id"],
        "pricing_quote_id": row["pricing_quote_id"],
        "comp_plan_id": row["comp_plan_id"],
        "borrower_name": row["borrower_name"],
        "property_state": row["property_state"],
        "loan_amount_cents": row["loan_amount_cents"],
        "lock_expires_at": row["lock_expires_at"],
        "competitor_channel_identifier": row["competitor_channel_identifier"],
        "compensation_election": row["compensation_election"],
        "lender_paid_comp_cents": row["lender_paid_comp_cents"],
        "borrower_paid_comp_cents": row["borrower_paid_comp_cents"],
        "rate_impact_pct": dump_decimal(row["rate_impact_pct"], THREE),
        "final_note_rate_pct": dump_decimal(row["final_note_rate_pct"], THREE),
        "defect_remediation_open": row["defect_remediation_open"],
        "underwriting_due_at": row["underwriting_due_at"],
        "closing_due_at": row["closing_due_at"],
        "repurchase_exposure_cents": row["repurchase_exposure_cents"],
        "status": row["status"],
        "closing_path": row["closing_path"],
        "submitted_at": row["submitted_at"],
        "cleared_at": row["cleared_at"],
        "suspended_reason": row.get("suspended_reason"),
    })
    return payload


def compensation_plan(row):
    payload = _common(row)
    payload.update({
        "broker_id": row["broker_id"],
        "plan_code": row["plan_code"],
        "default_election": row["default_election"],
        "lender_paid_amount_cents": row["lender_paid_amount_cents"],
        "borrower_paid_amount_cents": row["borrower_paid_amount_cents"],
        "is_active": row["is_active"],
    })
    return payload


def underwriting_decision(row):
    payload = _common(row)
    payload.update({
        "loan_submission_id": row["loan_submission_id"],
        "broker_id": row["broker_id"],
        "underwriter_id": row["underwriter_id"],
        "decision_type": row["decision_type"],
        "conditions": list(row["conditions"]),
        "decision_notes": row["decision_notes"] or QC_DEFECT_HOLD_NOTE,
        "decided_at": row["decided_at"],
        "is_final": row["is_final"],
    })
    return payload


def turn_time_escalation(row):
    payload = _common(row)
    payload.update({
        "loan_submission_id": row["loan_submission_id"],
        "broker_id": row["broker_id"],
        "stage": row["stage"],
        "opened_at": row["opened_at"],
        "target_due_at": row["target_due_at"],
        "resolved_at": row["resolved_at"],
        "resolution_note": row["resolution_note"],
        "status": row["status"],
    })
    return payload


def quality_control_review(row):
    payload = _common(row)
    payload.update({
        "loan_submission_id": row["loan_submission_id"],
        "broker_id": row["broker_id"],
        "reviewer_id": row["reviewer_id"],
        "defect_type": row["defect_type"],
        "severity": row["severity"],
        "weighted_defect_points": dump_decimal(row["weighted_defect_points"], TWO),
        "outcome": row["outcome"],
        "remediation_status": row["remediation_status"],
        "repurchase_required": row["repurchase_required"],
        "repurchase_due_at": row["repurchase_due_at"],
        "reviewed_at": row["reviewed_at"],
    })
    return payload