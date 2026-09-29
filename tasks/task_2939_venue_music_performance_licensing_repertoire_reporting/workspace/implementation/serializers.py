"""Row -> JSON projections.

Field names come straight from the entity definitions.  Money is emitted as
JSON integers (PRD 2.6), instants as ISO 8601 UTC with exactly three fractional
digits (PRD 2.5), and the three two-decimal figures are held internally in
integer hundredths and divided by 100 on the way out.
"""

import db
from core import (
    FULL_COVERAGE_THRESHOLD_BP,
    iso,
    pct_from_h,
)


def _triplet(row, out):
    out["id"] = row["id"]
    out["created_at"] = iso(row["created_at"])
    out["updated_at"] = iso(row["updated_at"])
    out["version"] = row["version"]
    return out


def society_json(row):
    out = {
        "society_code": row["society_code"],
        "display_name": row["display_name"],
        "repertoire_share_bp": row["repertoire_share_bp"],
        "rate_court_supervised": row["rate_court_supervised"],
        "licensed_venue_count": licensed_venue_count(row["id"]),
    }
    return _triplet(row, out)


def licensed_venue_count(society_id):
    """PRD 2.10: distinct venues holding at least one ACTIVE licence here."""
    venue_ids = set()
    for lic in db.ordered("licenses"):
        if lic["society_id"] == society_id and lic["coverage_status"] == "ACTIVE":
            venue_ids.add(lic["venue_id"])
    return len(venue_ids)


def pinned_license_count(schedule_id):
    """PRD 3.2: licences whose rate_schedule_id equals this schedule's id."""
    total = 0
    for lic in db.ordered("licenses"):
        if lic["rate_schedule_id"] == schedule_id:
            total += 1
    return total


def schedule_json(row):
    out = {
        "society_id": row["society_id"],
        "venue_category": row["venue_category"],
        "schedule_version": row["schedule_version"],
        "effective_from": iso(row["effective_from"]),
        "rate_court_order_ref": row["rate_court_order_ref"],
        "adjustment_bp": row["adjustment_bp"],
        "min_annual_fee_cents": row["min_annual_fee_cents"],
        "max_annual_fee_cents": row["max_annual_fee_cents"],
        "status": row["status"],
        "pinned_license_count": pinned_license_count(row["id"]),
    }
    return _triplet(row, out)


def posture_for(covered_share_bp):
    if covered_share_bp >= FULL_COVERAGE_THRESHOLD_BP:
        return "FULLY_COVERED"
    if covered_share_bp >= 1:
        return "PARTIALLY_COVERED"
    return "UNCOVERED"


def venue_json(row):
    out = {
        "legal_name": row["legal_name"],
        "venue_category": row["venue_category"],
        "seating_capacity": row["seating_capacity"],
        "standing_capacity": row["standing_capacity"],
        "occupancy_limit": row["occupancy_limit"],
        "music_use_profile": row["music_use_profile"],
        "weekly_live_performance_nights": row["weekly_live_performance_nights"],
        "annual_cover_revenue_cents": row["annual_cover_revenue_cents"],
        "gross_square_feet": row["gross_square_feet"],
        "speaker_count": row["speaker_count"],
        "max_speakers_per_room": row["max_speakers_per_room"],
        "has_cover_charge": row["has_cover_charge"],
        "retransmission_only": row["retransmission_only"],
        "uses_licensed_bgm_service": row["uses_licensed_bgm_service"],
        "bgm_service_provider": row["bgm_service_provider"],
        "bgm_exemption_status": row["bgm_exemption_status"],
        "bgm_exemption_reason": row["bgm_exemption_reason"],
        "status": row["status"],
        "covered_share_bp": row["covered_share_bp"],
        "coverage_posture": row["coverage_posture"],
        "gap_risk_score": pct_from_h(row["gap_risk_score_h"]),
        "audit_hold": row["audit_hold"],
        "lifetime_assessed_cents": row["lifetime_assessed_cents"],
        "outstanding_balance_cents": row["outstanding_balance_cents"],
        "settled_amount_cents": row["settled_amount_cents"],
        "voided_amount_cents": row["voided_amount_cents"],
    }
    return _triplet(row, out)


def application_json(row):
    out = {
        "venue_id": row["venue_id"],
        "society_id": row["society_id"],
        "requested_license_type": row["requested_license_type"],
        "assigned_license_type": row["assigned_license_type"],
        "declared_seating": row["declared_seating"],
        "declared_standing": row["declared_standing"],
        "declared_cover_revenue_cents": row["declared_cover_revenue_cents"],
        "declared_live_nights": row["declared_live_nights"],
        "declared_music_use_profile": row["declared_music_use_profile"],
        "requested_term_start": iso(row["requested_term_start"]),
        "provisional_annual_fee_cents": row["provisional_annual_fee_cents"],
        "status": row["status"],
        "revision_round": row["revision_round"],
        "return_reason": row["return_reason"],
        "decline_reason": row["decline_reason"],
    }
    return _triplet(row, out)


def license_json(row):
    out = {
        "venue_id": row["venue_id"],
        "society_id": row["society_id"],
        "application_id": row["application_id"],
        "rate_schedule_id": row["rate_schedule_id"],
        "renewal_of_license_id": row["renewal_of_license_id"],
        "pinned_schedule_version": row["pinned_schedule_version"],
        "license_type": row["license_type"],
        "term_start": iso(row["term_start"]),
        "term_end": iso(row["term_end"]),
        "provisional_annual_fee_cents": row["provisional_annual_fee_cents"],
        "annual_fee_cents": row["annual_fee_cents"],
        "verified_fee_delta_cents": row["verified_fee_delta_cents"],
        "coverage_status": row["coverage_status"],
        "billing_status": row["billing_status"],
        "suspension_reason": row["suspension_reason"],
        "reporting_required": row["reporting_required"],
        "accepted_report_count": row["accepted_report_count"],
        "renewal_issued_at": iso(row["renewal_issued_at"]),
    }
    return _triplet(row, out)


def window_json(row):
    out = {
        "license_id": row["license_id"],
        "window_kind": row["window_kind"],
        "window_start": iso(row["window_start"]),
        "window_end": iso(row["window_end"]),
        "covered_day_count": row["covered_day_count"],
        "rider_fee_cents": row["rider_fee_cents"],
        "status": row["status"],
    }
    return _triplet(row, out)


def work_json(row):
    return {
        "id": row["id"],
        "society_id": row["society_id"],
        "title": row["title"],
        "writer_name": row["writer_name"],
        "iswc": row["iswc"],
        "created_at": iso(row["created_at"]),
    }


def report_json(row):
    out = {
        "license_id": row["license_id"],
        "period_start": iso(row["period_start"]),
        "period_end": iso(row["period_end"]),
        "status": row["status"],
        "reported_entry_count": row["reported_entry_count"],
        "matched_entry_count": row["matched_entry_count"],
        "uncovered_entry_count": row["uncovered_entry_count"],
        "unmatched_share_pct": pct_from_h(row["unmatched_share_pct_h"]),
        "uncovered_share_pct": pct_from_h(row["uncovered_share_pct_h"]),
        "gap_exposure_cents": row["gap_exposure_cents"],
        "rejection_reason": row["rejection_reason"],
        "review_round": row["review_round"],
    }
    return _triplet(row, out)


def entry_json(row):
    return {
        "id": row["id"],
        "performance_report_id": row["performance_report_id"],
        "work_title": row["work_title"],
        "writer_name": row["writer_name"],
        "society_affiliation": row["society_affiliation"],
        "performance_datetime": iso(row["performance_datetime"]),
        "use_type": row["use_type"],
        "duration_seconds": row["duration_seconds"],
        "is_matched": row["is_matched"],
        "matched_work_id": row["matched_work_id"],
        "is_covered": row["is_covered"],
        "created_at": iso(row["created_at"]),
    }


def case_json(row):
    out = {
        "venue_id": row["venue_id"],
        "audit_trigger": row["audit_trigger"],
        "lookback_start": iso(row["lookback_start"]),
        "lookback_end": iso(row["lookback_end"]),
        "society_ids": list(row["society_ids"]),
        "status": row["status"],
        "unlicensed_month_count": row["unlicensed_month_count"],
        "back_license_exposure_cents": row["back_license_exposure_cents"],
        "penalty_cents": row["penalty_cents"],
        "pre_credit_total_cents": row["pre_credit_total_cents"],
        "goodwill_credit_cents": row["goodwill_credit_cents"],
        "settlement_total_cents": row["settlement_total_cents"],
        "settlement_floor_cents": row["settlement_floor_cents"],
        "offered_amount_cents": row["offered_amount_cents"],
        "payment_plan_months": row["payment_plan_months"],
        "dispute_round": row["dispute_round"],
        "findings_issued_by_user_id": row["findings_issued_by_user_id"],
        "settlement_proposed_by_user_id": row["settlement_proposed_by_user_id"],
        "settled_by_user_id": row["settled_by_user_id"],
        "closed_reason": row["closed_reason"],
    }
    return _triplet(row, out)


def assessment_json(row):
    out = {
        "venue_id": row["venue_id"],
        "license_id": row["license_id"],
        "audit_case_id": row["audit_case_id"],
        "assessment_kind": row["assessment_kind"],
        "amount_cents": row["amount_cents"],
        "paid_amount_cents": row["paid_amount_cents"],
        "due_date": iso(row["due_date"]),
        "status": row["status"],
    }
    return _triplet(row, out)
