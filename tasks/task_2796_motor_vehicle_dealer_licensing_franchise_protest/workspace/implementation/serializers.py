"""Entity representations. Field lists follow SCAFFOLD entities / PRD section 3."""

import db
from calc import as_number


def _common(record):
    return {
        "id": record["id"],
        "created_at": db.iso_instant(record["created_at"]),
        "updated_at": db.iso_instant(record["updated_at"]),
        "version": record["version"],
    }


def _log_common(record):
    """MarketStudy and EvidenceSubmission expose only id and created_at (PRD 2.4)."""
    return {"id": record["id"], "created_at": db.iso_instant(record["created_at"])}


def manufacturer(record):
    body = _common(record)
    body.update({
        "legal_name": record["legal_name"],
        "line_make": record["line_make"],
        "home_office_state": record["home_office_state"],
        "posted_warranty_labor_rate_cents": record["posted_warranty_labor_rate_cents"],
        "state_registration_status": record["state_registration_status"],
        "open_dispute_count": record["open_dispute_count"],
        "active_filing_count": record["active_filing_count"],
    })
    return body


def hearing_room(record):
    body = _common(record)
    body.update({
        "room_code": record["room_code"],
        "seating_capacity": record["seating_capacity"],
        "max_hearings_per_day": record["max_hearings_per_day"],
        "buffer_minutes": record["buffer_minutes"],
        "booked_hearing_count": record["booked_hearing_count"],
    })
    return body


def dealer(record):
    body = _common(record)
    body.update({
        "legal_name": record["legal_name"],
        "dealer_type": record["dealer_type"],
        "county_tier": record["county_tier"],
        "line_make": record["line_make"],
        "site_x_km": as_number(record["site_x_km"]),
        "site_y_km": as_number(record["site_y_km"]),
        "license_status": record["license_status"],
        "franchise_status": record["franchise_status"],
        "suspension_reason": record["suspension_reason"],
        "license_effective_on": db.iso_date(record["license_effective_on"]),
        "license_expires_on": db.iso_date(record["license_expires_on"]),
        "disciplinary_points": record["disciplinary_points"],
        "restitution_outstanding_cents": record["restitution_outstanding_cents"],
        "licensed_salesperson_count": record["licensed_salesperson_count"],
        "approved_warranty_labor_rate_cents": record["approved_warranty_labor_rate_cents"],
    })
    return body


def license_application(record):
    body = _common(record)
    body.update({
        "dealer_id": record["dealer_id"],
        "application_type": record["application_type"],
        "status": record["status"],
        "facility_sqft": record["facility_sqft"],
        "display_spaces": record["display_spaces"],
        "service_bays": record["service_bays"],
        "bond_amount_cents": record["bond_amount_cents"],
        "insurance_liability_cents": record["insurance_liability_cents"],
        "zoning_certificate_status": record["zoning_certificate_status"],
        "line_make_count": record["line_make_count"],
        "requested_term_start_on": db.iso_date(record["requested_term_start_on"]),
        "relocation_site_x_km": as_number(record["relocation_site_x_km"]),
        "relocation_site_y_km": as_number(record["relocation_site_y_km"]),
        "new_owner_name": record["new_owner_name"],
        "deficiency_codes": list(record["deficiency_codes"]),
        "deficiency_count": record["deficiency_count"],
        "fee_quoted_cents": record["fee_quoted_cents"],
        "fee_total_cents": record["fee_total_cents"],
        "fee_delta_cents": record["fee_delta_cents"],
        "resubmission_count": record["resubmission_count"],
        "submitted_at": db.iso_instant(record["submitted_at"]),
        "decided_at": db.iso_instant(record["decided_at"]),
        "decision_outcome": record["decision_outcome"],
        "denial_reason_code": record["denial_reason_code"],
        "deficiency_note": record["deficiency_note"],
    })
    return body


def salesperson(record):
    body = _common(record)
    body.update({
        "sponsoring_dealer_id": record["sponsoring_dealer_id"],
        "full_name": record["full_name"],
        "disclosed_prior_discipline": record["disclosed_prior_discipline"],
        "license_status": record["license_status"],
        "discipline_status": record["discipline_status"],
        "disciplinary_points": record["disciplinary_points"],
        "waiver_granted": record["waiver_granted"],
        "license_effective_on": db.iso_date(record["license_effective_on"]),
        "license_expires_on": db.iso_date(record["license_expires_on"]),
        "renewal_count": record["renewal_count"],
        "denial_reason_code": record["denial_reason_code"],
    })
    return body


def franchise_filing(record):
    body = _common(record)
    body.update({
        "manufacturer_id": record["manufacturer_id"],
        "affected_dealer_id": record["affected_dealer_id"],
        "filing_type": record["filing_type"],
        "line_make": record["line_make"],
        "status": record["status"],
        "proposed_effective_on": db.iso_date(record["proposed_effective_on"]),
        "site_x_km": as_number(record["site_x_km"]),
        "site_y_km": as_number(record["site_y_km"]),
        "termination_cause_code": record["termination_cause_code"],
        "notice_served_on": db.iso_date(record["notice_served_on"]),
        "notice_days_provided": record["notice_days_provided"],
        "protest_window_ends_on": db.iso_date(record["protest_window_ends_on"]),
        "amendment_count": record["amendment_count"],
        "active_protest_count": record["active_protest_count"],
    })
    return body


def protest(record):
    body = _common(record)
    body.update({
        "franchise_filing_id": record["franchise_filing_id"],
        "protestant_dealer_id": record["protestant_dealer_id"],
        "hearing_room_id": record["hearing_room_id"],
        "status": record["status"],
        "grounds_code": record["grounds_code"],
        "filed_on": db.iso_date(record["filed_on"]),
        "distance_to_site_km": as_number(record["distance_to_site_km"]),
        "hearing_start_at": db.iso_instant(record["hearing_start_at"]),
        "hearing_end_at": db.iso_instant(record["hearing_end_at"]),
        "hearing_session_count": record["hearing_session_count"],
        "evidence_deadline_at": db.iso_instant(record["evidence_deadline_at"]),
        "accepted_evidence_pages": record["accepted_evidence_pages"],
        "late_evidence_count": record["late_evidence_count"],
        "good_cause_score": as_number(record["good_cause_score"]),
        "good_cause_threshold": as_number(record["good_cause_threshold"]),
        "decided_on": db.iso_date(record["decided_on"]),
        "findings_note": record["findings_note"],
        "assessment_total_cents": record["assessment_total_cents"],
        "protestant_share_cents": record["protestant_share_cents"],
        "manufacturer_share_cents": record["manufacturer_share_cents"],
        "appeal_filed_on": db.iso_date(record["appeal_filed_on"]),
        "appellant_party": record["appellant_party"],
        "court_docket_number": record["court_docket_number"],
    })
    return body


def market_study(record):
    body = _log_common(record)
    shares = record["comparable_market_shares_pct"]
    body.update({
        "protest_id": record["protest_id"],
        "submitted_by_party": record["submitted_by_party"],
        "basis": record["basis"],
        "total_market_registrations": record["total_market_registrations"],
        "line_make_registrations": record["line_make_registrations"],
        "statewide_line_make_share_pct": as_number(record["statewide_line_make_share_pct"]),
        "comparable_market_shares_pct": (
            None if shares is None else [as_number(share) for share in shares]
        ),
        "permanency_investment_cents": record["permanency_investment_cents"],
        "consumer_access_drive_minutes": record["consumer_access_drive_minutes"],
        "market_growth_pct": as_number(record["market_growth_pct"]),
        "actual_penetration_pct": as_number(record["actual_penetration_pct"]),
        "expected_penetration_pct": as_number(record["expected_penetration_pct"]),
        "shortfall_pts": as_number(record["shortfall_pts"]),
        "is_probative": record["is_probative"],
    })
    return body


def evidence_submission(record):
    body = _log_common(record)
    body.update({
        "protest_id": record["protest_id"],
        "submitting_party": record["submitting_party"],
        "exhibit_label": record["exhibit_label"],
        "page_count": record["page_count"],
        "leave_granted": record["leave_granted"],
        "received_at": db.iso_instant(record["received_at"]),
        "acceptance_status": record["acceptance_status"],
        "is_late": record["is_late"],
    })
    return body


def _repair_order_line(line):
    """Labor hours are the one quantity carried to one decimal place (PRD 2.6)."""
    return {
        "labor_charge_cents": line["labor_charge_cents"],
        "labor_hours": as_number(line["labor_hours"]),
        "repair_type": line["repair_type"],
    }


def warranty_rate_dispute(record):
    body = _common(record)
    body.update({
        "dealer_id": record["dealer_id"],
        "manufacturer_id": record["manufacturer_id"],
        "status": record["status"],
        "repair_order_lines": [_repair_order_line(line) for line in record["repair_order_lines"]],
        "filed_on": db.iso_date(record["filed_on"]),
        "qualifying_line_count": record["qualifying_line_count"],
        "declared_rate_cents": record["declared_rate_cents"],
        "counter_rate_cents": record["counter_rate_cents"],
        "manufacturer_response_type": record["manufacturer_response_type"],
        "excluded_line_indexes": list(record["excluded_line_indexes"]),
        "spread_pct": as_number(record["spread_pct"]),
        "approved_rate_cents": record["approved_rate_cents"],
        "effective_on": db.iso_date(record["effective_on"]),
        "decided_on": db.iso_date(record["decided_on"]),
        "denial_reason_code": record["denial_reason_code"],
    })
    return body


def consumer_complaint(record):
    body = _common(record)
    body.update({
        "dealer_id": record["dealer_id"],
        "salesperson_id": record["salesperson_id"],
        "complainant_name": record["complainant_name"],
        "allegation_code": record["allegation_code"],
        "alleged_loss_cents": record["alleged_loss_cents"],
        "status": record["status"],
        "investigator_user_id": record["investigator_user_id"],
        "findings_code": record["findings_code"],
        "substantiated": record["substantiated"],
        "sanction_type": record["sanction_type"],
        "points_assessed": record["points_assessed"],
        "civil_penalty_cents": record["civil_penalty_cents"],
        "restitution_ordered_cents": record["restitution_ordered_cents"],
        "restitution_paid_cents": record["restitution_paid_cents"],
        "restitution_due_on": db.iso_date(record["restitution_due_on"]),
        "resolved_at": db.iso_instant(record["resolved_at"]),
    })
    return body
