"""Entity serializers: explicit field picks (internal underscore-prefixed keys
are never serialized). Shares serialize as JSON numbers via float(); Decimal
values used here are always pre-rounded to <= 4 decimal places, so the float
round-trips exactly through shortest-repr JSON encoding.
"""
from calculations import total_programmed_federal_cents
from db import STORE


def _common(r):
    return {
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_funding_program(r):
    return {
        "id": r["id"],
        "code": r["code"],
        "name": r["name"],
        "eligible_activity_codes": r["eligible_activity_codes"],
        "base_federal_share_pct": float(r["_base_share_dec"]),
        **_common(r),
    }


def serialize_apportionment(r):
    return {
        "id": r["id"],
        "funding_program_id": r["funding_program_id"],
        "state_code": r["state_code"],
        "federal_fiscal_year": r["federal_fiscal_year"],
        "apportioned_cents": r["apportioned_cents"],
        "obligated_cents": r["obligated_cents"],
        "available_cents": r["available_cents"],
        **_common(r),
    }


def serialize_stip(r):
    return {
        "id": r["id"],
        "state_code": r["state_code"],
        "state_federal_land_pct": r["state_federal_land_pct"],
        "start_federal_fiscal_year": r["start_federal_fiscal_year"],
        "end_federal_fiscal_year": r["end_federal_fiscal_year"],
        "description": r["description"],
        "status": r["status"],
        "comment_period_opened_at": r["comment_period_opened_at"],
        "amendment_count": r["amendment_count"],
        "total_programmed_federal_cents": total_programmed_federal_cents(
            r["id"], STORE["projects"].values()
        ),
        **_common(r),
    }


def serialize_comment(r):
    # PublicComment is the common_fields exception: only id and created_at.
    return {
        "id": r["id"],
        "stip_id": r["stip_id"],
        "author_name": r["author_name"],
        "comment_text": r["comment_text"],
        "created_at": r["created_at"],
    }


def serialize_project(r):
    determined = r["_determined_share_dec"]
    return {
        "id": r["id"],
        "stip_id": r["stip_id"],
        "funding_program_id": r["funding_program_id"],
        "route_name": r["route_name"],
        "description": r["description"],
        "activity_code": r["activity_code"],
        "is_interstate_system": r["is_interstate_system"],
        "dbe_goal_pct": r["dbe_goal_pct"],
        "total_estimated_cost_cents": r["total_estimated_cost_cents"],
        "provisional_federal_share_pct": float(r["_provisional_share_dec"]),
        "provisional_federal_estimate_cents": r["provisional_federal_estimate_cents"],
        "determined_federal_share_pct": (
            float(determined) if determined is not None else None
        ),
        "status": r["status"],
        "advertised_on_date": r["advertised_on_date"],
        "awarded_bid_id": r["awarded_bid_id"],
        **_common(r),
    }


def serialize_clearance(r):
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "kind": r["kind"],
        "nepa_class": r["nepa_class"],
        "status": r["status"],
        "row_cert_level": r["row_cert_level"],
        "decided_by_user_id": r["decided_by_user_id"],
        **_common(r),
    }


def serialize_authorization(r):
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "agreement_number": r["agreement_number"],
        "initial_obligated_cents": r["initial_obligated_cents"],
        "apportionment_id": r["apportionment_id"],
        "federal_share_pct": float(r["_share_dec"]),
        "obligated_cents": r["obligated_cents"],
        "reimbursed_cents": r["reimbursed_cents"],
        "repaid_cents": r["repaid_cents"],
        "cumulative_change_order_federal_cents": r[
            "cumulative_change_order_federal_cents"
        ],
        "status": r["status"],
        "closed_at": r["closed_at"],
        **_common(r),
    }


def serialize_bid(r):
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "contractor_name": r["contractor_name"],
        "bid_amount_cents": r["bid_amount_cents"],
        "is_responsive": r["is_responsive"],
        "submission_seq": r["submission_seq"],
        "status": r["status"],
        **_common(r),
    }


def serialize_voucher(r):
    return {
        "id": r["id"],
        "authorization_id": r["authorization_id"],
        "period_start_date": r["period_start_date"],
        "period_end_date": r["period_end_date"],
        "line_items": r["line_items"],
        "documentation_complete": r["documentation_complete"],
        "is_final": r["is_final"],
        "status": r["status"],
        "claimed_amount_cents": r["claimed_amount_cents"],
        "eligible_amount_cents": r["eligible_amount_cents"],
        "federal_reimbursable_cents": r["federal_reimbursable_cents"],
        "ineligible_line_indexes": r["ineligible_line_indexes"],
        "submitted_by_user_id": r["submitted_by_user_id"],
        "decided_by_user_id": r["decided_by_user_id"],
        "resubmission_count": r["resubmission_count"],
        **_common(r),
    }


def serialize_change_order(r):
    return {
        "id": r["id"],
        "authorization_id": r["authorization_id"],
        "description": r["description"],
        "delta_cost_cents": r["delta_cost_cents"],
        "requested_by_user_id": r["requested_by_user_id"],
        "state_concurred_by_user_id": r["state_concurred_by_user_id"],
        "federal_participation_cents": r["federal_participation_cents"],
        "status": r["status"],
        **_common(r),
    }


def serialize_audit(r):
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "auditor_user_id": r["auditor_user_id"],
        "status": r["status"],
        "findings_text": r["findings_text"],
        "ineligible_amount_cents": r["ineligible_amount_cents"],
        "findings_issued_at": r["findings_issued_at"],
        "final_eligible_federal_share_cents": r["final_eligible_federal_share_cents"],
        "repayment_due_cents": r["repayment_due_cents"],
        "repaid_cents": r["repaid_cents"],
        "closed_at": r["closed_at"],
        **_common(r),
    }
