"""Payload factories — one per write endpoint, client-supplied input fields only."""

from .constants import TEST_DEFAULTS


# --------------------------------------------------------------- franchise spine
def create_franchisee_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Harborlight Fitness LLC",
        "contact_email": "ops@harborlightfit.example",
        "royalty_rate_bps": TEST_DEFAULTS["ROYALTY_RATE_BPS"],
        "national_account_eligible": False,
    }
    payload.update(overrides)
    return payload


def create_territory_payload(franchisee_id: str, **overrides) -> dict:
    payload = {
        "franchisee_id": franchisee_id,
        "center_lat": TEST_DEFAULTS["TERRITORY_LAT"],
        "center_lng": TEST_DEFAULTS["TERRITORY_LNG"],
        "protected_radius_km": TEST_DEFAULTS["TERRITORY_RADIUS_KM"],
        "state_code": "CA",
    }
    payload.update(overrides)
    return payload


def create_club_payload(territory_id: str, **overrides) -> dict:
    payload = {
        "territory_id": territory_id,
        "name": "Harborlight Club",
        "opened_on": TEST_DEFAULTS["MODERN_OPENED_ON"],
        "guest_fee_cents": TEST_DEFAULTS["GUEST_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_relocation_request_payload(club_id: str, **overrides) -> dict:
    payload = {
        "club_id": club_id,
        "requested_lat": 34.04,
        "requested_lng": -118.04,
        "requested_radius_km": TEST_DEFAULTS["TERRITORY_RADIUS_KM"],
        "justification": "Landlord redevelopment forces a move",
    }
    payload.update(overrides)
    return payload


def request_changes_payload(**overrides) -> dict:
    payload = {"reviewer_note": "Confirm the parking ratio at the new site"}
    payload.update(overrides)
    return payload


def relocation_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def withdraw_relocation_payload(**overrides) -> dict:
    payload = {"reason": "Re-siting the proposal"}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------- plans and promos
def create_plan_template_payload(**overrides) -> dict:
    payload = {
        "code": TEST_DEFAULTS["PLAN_CODE"],
        "monthly_dues_cents": TEST_DEFAULTS["MONTHLY_DUES_CENTS"],
        "initiation_fee_cents": TEST_DEFAULTS["INITIATION_FEE_CENTS"],
        "term_months": TEST_DEFAULTS["TERM_MONTHS"],
        "cancellation_notice_days": TEST_DEFAULTS["CANCELLATION_NOTICE_DAYS"],
        "floor_price_cents": TEST_DEFAULTS["FLOOR_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_promotion_payload(franchisee_id: str, plan_template_id: str, **overrides) -> dict:
    payload = {
        "franchisee_id": franchisee_id,
        "plan_template_id": plan_template_id,
        "code": "SUMMER10",
        "discount_pct": 0.10,
        "starts_on": "2026-08-01",
        "ends_on": "2026-08-31",
    }
    payload.update(overrides)
    return payload


def promotion_review_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# -------------------------------------------------------- members and corporates
def create_member_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ivo Marchetti",
        "email": "ivo.marchetti@example.com",
        "home_state_code": "CA",
    }
    payload.update(overrides)
    return payload


def create_corporate_account_payload(**overrides) -> dict:
    payload = {
        "name": "Atlas Logistics National Account",
        "corporate_credit_pct": 0.045,
        "allocation_method": "USAGE_SHARE",
    }
    payload.update(overrides)
    return payload


def fund_corporate_account_payload(amount_cents: int = 100000, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def allocate_corporate_account_payload(**overrides) -> dict:
    payload = {"note": "Monthly subsidy distribution"}
    payload.update(overrides)
    return payload


def recall_allocation_payload(**overrides) -> dict:
    payload = {"reason": "Corporate customer restated its headcount"}
    payload.update(overrides)
    return payload


def suspend_corporate_account_payload(**overrides) -> dict:
    payload = {"reason": "Corporate customer entered administration"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- agreements
def create_agreement_payload(
    member_id: str,
    home_club_id: str,
    plan_template_id: str,
    expected_club_version: int,
    signed_on: str = "2026-08-01",
    **overrides,
) -> dict:
    payload = {
        "member_id": member_id,
        "home_club_id": home_club_id,
        "plan_template_id": plan_template_id,
        "expected_club_version": expected_club_version,
        "signed_on": signed_on,
        "multi_club_access": False,
    }
    payload.update(overrides)
    return payload


def request_cancellation_payload(**overrides) -> dict:
    payload = {"reason": "Member is moving out of state"}
    payload.update(overrides)
    return payload


def place_in_collections_payload(**overrides) -> dict:
    payload = {"agency_reference": "AGENCY-REF-0001"}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------- billing events
def create_billing_event_payload(
    agreement_id: str,
    event_type: str,
    amount_cents: int,
    occurred_on: str,
    **overrides,
) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "event_type": event_type,
        "amount_cents": amount_cents,
        "occurred_on": occurred_on,
    }
    payload.update(overrides)
    return payload


def dues_posted_payload(
    agreement_id: str, amount_cents: int, occurred_on: str, due_on: str, **overrides
) -> dict:
    return create_billing_event_payload(
        agreement_id, "DUES_POSTED", amount_cents, occurred_on, due_on=due_on, **overrides
    )


def payment_received_payload(
    agreement_id: str, amount_cents: int, occurred_on: str, **overrides
) -> dict:
    return create_billing_event_payload(
        agreement_id, "PAYMENT_RECEIVED", amount_cents, occurred_on, **overrides
    )


def payment_failed_payload(agreement_id: str, occurred_on: str, **overrides) -> dict:
    return create_billing_event_payload(
        agreement_id, "PAYMENT_FAILED", 0, occurred_on, **overrides
    )


def write_off_payload(
    agreement_id: str, amount_cents: int, occurred_on: str, **overrides
) -> dict:
    return create_billing_event_payload(
        agreement_id, "WRITE_OFF", amount_cents, occurred_on, **overrides
    )


# ---------------------------------------------------------- transfer requests
def create_transfer_request_payload(
    agreement_id: str,
    from_club_id: str,
    to_club_id: str,
    expected_agreement_version: int,
    **overrides,
) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "from_club_id": from_club_id,
        "to_club_id": to_club_id,
        "expected_agreement_version": expected_agreement_version,
        "reason": "Member relocated across town",
    }
    payload.update(overrides)
    return payload


def transfer_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ------------------------------------------------- guest usage and settlements
def create_guest_usage_event_payload(
    agreement_id: str, host_club_id: str, period_month: str, visit_count: int, **overrides
) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "host_club_id": host_club_id,
        "period_month": period_month,
        "visit_count": visit_count,
    }
    payload.update(overrides)
    return payload


def create_usage_settlement_payload(
    period_month: str, home_club_id: str, host_club_id: str, **overrides
) -> dict:
    payload = {
        "period_month": period_month,
        "home_club_id": home_club_id,
        "host_club_id": host_club_id,
    }
    payload.update(overrides)
    return payload


def reverse_usage_settlement_payload(**overrides) -> dict:
    payload = {"reason": "Host club disputed the visit log"}
    payload.update(overrides)
    return payload


# ---------------------------------------------- royalty reports and inspections
def create_royalty_report_payload(
    franchisee_id: str, period_month: str, reported_member_count: int, **overrides
) -> dict:
    payload = {
        "franchisee_id": franchisee_id,
        "period_month": period_month,
        "reported_member_count": reported_member_count,
    }
    payload.update(overrides)
    return payload


def adjudicate_royalty_report_payload(adjusted_royalty_cents: int, **overrides) -> dict:
    payload = {"adjusted_royalty_cents": adjusted_royalty_cents}
    payload.update(overrides)
    return payload


def create_inspection_payload(club_id: str, inspection_date: str, **overrides) -> dict:
    payload = {"club_id": club_id, "inspection_date": inspection_date}
    payload.update(overrides)
    return payload


def score_inspection_payload(
    equipment_condition_pts: int,
    cleanliness_pts: int,
    safety_pts: int,
    equipment_age_months_max: int,
    **overrides,
) -> dict:
    payload = {
        "equipment_condition_pts": equipment_condition_pts,
        "cleanliness_pts": cleanliness_pts,
        "safety_pts": safety_pts,
        "equipment_age_months_max": equipment_age_months_max,
    }
    payload.update(overrides)
    return payload


def waive_remediation_payload(**overrides) -> dict:
    payload = {"reason": "Replacement cardio floor already on order"}
    payload.update(overrides)
    return payload


def reinstate_franchisee_payload(**overrides) -> dict:
    payload = {"note": "Equipment refresh verified"}
    payload.update(overrides)
    return payload


def set_clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}
