"""Payload factories — one per write operation, input fields only.

Every monetary amount is an integer count of cents and every payload value is
sent with its JSON-native type (never as a string).
"""
from .constants import TEST_DEFAULTS


def manufacturer_payload(**overrides) -> dict:
    """Register a franchisor. `state_registration_status` is optional and
    defaults to REGISTERED on the server, so it is omitted unless overridden."""
    payload = {
        "legal_name": "Aurora Motors NA",
        "line_make": TEST_DEFAULTS["LINE_MAKE"],
        "home_office_state": TEST_DEFAULTS["HOME_OFFICE_STATE"],
        "posted_warranty_labor_rate_cents": TEST_DEFAULTS["POSTED_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def hearing_room_payload(**overrides) -> dict:
    """Create a hearing room. `max_hearings_per_day` and `buffer_minutes` are
    optional; they are only sent when a test overrides them."""
    payload = {
        "room_code": "HR-1",
        "seating_capacity": TEST_DEFAULTS["SEATING_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def dealer_payload(**overrides) -> dict:
    """Open a prospective dealership record."""
    payload = {
        "legal_name": "Lakeside Aurora",
        "dealer_type": "NEW_MOTOR_VEHICLE",
        "county_tier": "TIER_2",
        "site_x_km": 0,
        "site_y_km": 0,
        "line_make": TEST_DEFAULTS["LINE_MAKE"],
    }
    payload.update(overrides)
    return payload


def used_only_dealer_payload(**overrides) -> dict:
    """Open a used-only dealership: no line make is sold new."""
    payload = dealer_payload(
        legal_name="Quarry Used Cars",
        dealer_type="USED_ONLY",
        line_make="",
    )
    payload.update(overrides)
    return payload


def license_application_payload(dealer_id, **overrides) -> dict:
    """Open a licence application in draft. The defaults clear every
    new-motor-vehicle statutory minimum, so the sufficiency scan finds nothing."""
    payload = {
        "dealer_id": dealer_id,
        "application_type": "INITIAL",
        "facility_sqft": TEST_DEFAULTS["FACILITY_SQFT"],
        "display_spaces": TEST_DEFAULTS["DISPLAY_SPACES"],
        "service_bays": TEST_DEFAULTS["SERVICE_BAYS"],
        "bond_amount_cents": TEST_DEFAULTS["BOND_AMOUNT_CENTS"],
        "insurance_liability_cents": TEST_DEFAULTS["INSURANCE_LIABILITY_CENTS"],
        "zoning_certificate_status": "APPROVED",
        "line_make_count": 1,
    }
    payload.update(overrides)
    return payload


def used_only_application_payload(dealer_id, **overrides) -> dict:
    """Open a licence application clearing the used-only minimums."""
    payload = license_application_payload(
        dealer_id,
        facility_sqft=2500,
        display_spaces=4,
        service_bays=0,
        bond_amount_cents=2500000,
        insurance_liability_cents=50000000,
        line_make_count=0,
    )
    payload.update(overrides)
    return payload


def application_decision_payload(outcome="APPROVED", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def deficiency_notice_payload(**overrides) -> dict:
    payload = {"deficiency_note": "Facility and zoning particulars must be corrected."}
    payload.update(overrides)
    return payload


def salesperson_payload(sponsoring_dealer_id, **overrides) -> dict:
    payload = {
        "sponsoring_dealer_id": sponsoring_dealer_id,
        "full_name": "Dana Reyes",
        "disclosed_prior_discipline": False,
    }
    payload.update(overrides)
    return payload


def salesperson_decision_payload(outcome="APPROVED", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def termination_filing_payload(manufacturer_id, affected_dealer_id,
                               proposed_effective_on="2026-12-01", **overrides) -> dict:
    """A TERMINATION names the affected dealership and cites a statutory cause."""
    payload = {
        "manufacturer_id": manufacturer_id,
        "filing_type": "TERMINATION",
        "proposed_effective_on": proposed_effective_on,
        "affected_dealer_id": affected_dealer_id,
        "termination_cause_code": "FAILURE_TO_MEET_SALES_PERFORMANCE",
    }
    payload.update(overrides)
    return payload


def relocation_filing_payload(manufacturer_id, affected_dealer_id,
                             proposed_effective_on="2026-12-01",
                             site_x_km=10, site_y_km=0, **overrides) -> dict:
    """A RELOCATION names the affected dealership and the destination point."""
    payload = {
        "manufacturer_id": manufacturer_id,
        "filing_type": "RELOCATION",
        "proposed_effective_on": proposed_effective_on,
        "affected_dealer_id": affected_dealer_id,
        "site_x_km": site_x_km,
        "site_y_km": site_y_km,
    }
    payload.update(overrides)
    return payload


def additional_point_filing_payload(manufacturer_id,
                                    proposed_effective_on="2026-11-01",
                                    site_x_km=9, site_y_km=12, **overrides) -> dict:
    """An ADDITIONAL_POINT carries the destination and omits any dealership."""
    payload = {
        "manufacturer_id": manufacturer_id,
        "filing_type": "ADDITIONAL_POINT",
        "proposed_effective_on": proposed_effective_on,
        "site_x_km": site_x_km,
        "site_y_km": site_y_km,
    }
    payload.update(overrides)
    return payload


def amendment_payload(proposed_effective_on, **overrides) -> dict:
    payload = {"proposed_effective_on": proposed_effective_on}
    payload.update(overrides)
    return payload


def protest_payload(franchise_filing_id, protestant_dealer_id,
                    expected_franchise_filing_version,
                    grounds_code="NO_GOOD_CAUSE_FOR_TERMINATION", **overrides) -> dict:
    payload = {
        "franchise_filing_id": franchise_filing_id,
        "protestant_dealer_id": protestant_dealer_id,
        "grounds_code": grounds_code,
        "expected_franchise_filing_version": expected_franchise_filing_version,
    }
    payload.update(overrides)
    return payload


def schedule_payload(hearing_room_id, hearing_start_at, hearing_end_at,
                     expected_hearing_room_version, hearing_session_count=1,
                     **overrides) -> dict:
    payload = {
        "hearing_room_id": hearing_room_id,
        "hearing_start_at": hearing_start_at,
        "hearing_end_at": hearing_end_at,
        "hearing_session_count": hearing_session_count,
        "expected_hearing_room_version": expected_hearing_room_version,
    }
    payload.update(overrides)
    return payload


def statewide_study_payload(submitted_by_party="PROTESTANT", **overrides) -> dict:
    """A market study on the statutory STATEWIDE_AVERAGE basis."""
    payload = {
        "submitted_by_party": submitted_by_party,
        "basis": "STATEWIDE_AVERAGE",
        "total_market_registrations": 10000,
        "line_make_registrations": 800,
        "statewide_line_make_share_pct": 12.50,
        "permanency_investment_cents": 600000000,
        "consumer_access_drive_minutes": 30,
        "market_growth_pct": 8.00,
    }
    payload.update(overrides)
    return payload


def comparable_study_payload(submitted_by_party="PROTESTANT", **overrides) -> dict:
    """A market study on the COMPARABLE_MARKET basis."""
    payload = {
        "submitted_by_party": submitted_by_party,
        "basis": "COMPARABLE_MARKET",
        "total_market_registrations": 10000,
        "line_make_registrations": 800,
        "comparable_market_shares_pct": [10.00, 10.00],
        "permanency_investment_cents": 600000000,
        "consumer_access_drive_minutes": 30,
        "market_growth_pct": 8.00,
    }
    payload.update(overrides)
    return payload


def exhibit_payload(submitting_party="PROTESTANT", exhibit_label="EX-A",
                    page_count=10, **overrides) -> dict:
    payload = {
        "submitting_party": submitting_party,
        "exhibit_label": exhibit_label,
        "page_count": page_count,
    }
    payload.update(overrides)
    return payload


def protest_decision_payload(outcome="SUSTAINED", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def appeal_payload(court_docket_number="CV-2026-00812", **overrides) -> dict:
    payload = {"court_docket_number": court_docket_number}
    payload.update(overrides)
    return payload


def repair_order_line(labor_charge_cents, labor_hours, repair_type="CUSTOMER_PAID") -> dict:
    """One repair order line. Labor hours carry at most one decimal place."""
    return {
        "labor_charge_cents": labor_charge_cents,
        "labor_hours": labor_hours,
        "repair_type": repair_type,
    }


def qualifying_lines(count=5, labor_charge_cents=8400, labor_hours=1.0) -> list:
    """A sample of identical qualifying CUSTOMER_PAID lines."""
    return [repair_order_line(labor_charge_cents, labor_hours) for _ in range(count)]


def rate_dispute_payload(dealer_id, manufacturer_id, repair_order_lines=None,
                         **overrides) -> dict:
    payload = {
        "dealer_id": dealer_id,
        "manufacturer_id": manufacturer_id,
        "repair_order_lines": repair_order_lines if repair_order_lines is not None
        else qualifying_lines(),
    }
    payload.update(overrides)
    return payload


def dispute_response_payload(manufacturer_response_type="REBUT", **overrides) -> dict:
    payload = {"manufacturer_response_type": manufacturer_response_type}
    payload.update(overrides)
    return payload


def dispute_decision_payload(outcome="APPROVED", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def complaint_payload(dealer_id, allegation_code="ODOMETER_MISREPRESENTATION",
                      alleged_loss_cents=100000, **overrides) -> dict:
    payload = {
        "dealer_id": dealer_id,
        "complainant_name": "Jamie Consumer",
        "allegation_code": allegation_code,
        "alleged_loss_cents": alleged_loss_cents,
    }
    payload.update(overrides)
    return payload


def investigation_payload(findings_code="MISREPRESENTATION_CONFIRMED", **overrides) -> dict:
    payload = {"findings_code": findings_code}
    payload.update(overrides)
    return payload


def resolution_payload(substantiated=True, sanction_type="CIVIL_PENALTY", **overrides) -> dict:
    """A `sanction_type` is present exactly when the complaint is substantiated."""
    payload = {"substantiated": substantiated}
    if substantiated:
        payload["sanction_type"] = sanction_type
    payload.update(overrides)
    return payload


def restitution_payment_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload
