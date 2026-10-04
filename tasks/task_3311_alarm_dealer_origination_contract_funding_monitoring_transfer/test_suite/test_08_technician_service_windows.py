"""The technician's half-open service window rule for scheduled visits."""
import pytest

from test_helpers import (
    api_client,
    set_logical_clock,
    setup_package_with_contract,
    submit_and_approve_package,
    fund_package,
    declare_package_contract,
    provision_monitoring_account,
    register_customer,
    create_dealer_payload,
    setup_scheduled_visit,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
)

_CHANNEL = TEST_USERS["channel_manager_headers"]
_ANALYST = TEST_USERS["funding_analyst_headers"]
_SERVICE = TEST_USERS["service_coordinator_headers"]

_TECH = "TECH-X"
_SLOT_DAY = "2026-09-10"


def _two_active_contracts():
    """Two funded ACTIVE contracts: A with one child, B with one child.

    Returns (contract_a, contract_b).
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    dealer = validate_success(api_client.create_dealer(
        create_dealer_payload(dealer_code="D13", holdback_rate=0.10,
                              quality_tier="TIER_1"), _CHANNEL), 201)
    package = validate_success(api_client.create_package(
        {"package_reference": "PKG-P13", "dealer_id": dealer["id"]}, _ANALYST), 201)
    declared = []
    for label in ("A", "B"):
        customer = register_customer(
            full_name=f"Zeke Overlap {label}",
            email=f"zeke.overlap.{label.lower()}@example.com")
        child = declare_package_contract(
            package["id"], customer["id"], equipment_config_code="PREMIUM",
            credit_score=700, contract_term_months=60, monthly_monitoring_cents=4999,
            installation_scheduled_at="2026-09-02T00:00:00Z",
            installation_engineer_id=f"ENG-{label}",
            premises_address_line=f"16{0 if label == 'A' else 1} Palm St")
        provision_monitoring_account(child["id"])
        declared.append(child)

    package = submit_and_approve_package(dealer, package["id"])
    fund_package(package["id"])
    rows = [get_success_data(api_client.get_contract(c["id"], _ANALYST))
            for c in declared]
    return rows[0], rows[1]


def _first_slot_and_candidate(candidate_start_iso, candidate_minutes=60):
    """Schedule a 120-minute visit at midnight on TECH-X, then request a candidate.

    Returns (first_visit, candidate_visit).
    """
    contract_a, contract_b = _two_active_contracts()
    first = setup_scheduled_visit(
        contract_a["id"], scheduled_at=f"{_SLOT_DAY}T00:00:00Z", work_type="REPAIR",
        technician_id=_TECH, duration_minutes=120, allowed_duration_minutes=120)
    assert first["visit_status"] == "SCHEDULED"

    candidate = setup_scheduled_visit(
        contract_b["id"], scheduled_at=candidate_start_iso, work_type="REPAIR",
        technician_id=_TECH, duration_minutes=candidate_minutes,
        allowed_duration_minutes=candidate_minutes, schedule=False)
    return first, candidate


# ─── Difficulty: resource_temporal_overlap / technician_half_open_service_window_collision ───

def test_visit_starting_inside_another_slot_is_rejected_as_overlap(api):
    """PRD §3.8: "Scheduling moves it to `SCHEDULED` — the value its `visit_status` field then holds — and is permitted only when the technician's service windows hold for the requested instant under the half-open overlap rule — a collision with another non-cancelled slot of the same technician is refused with `ERR_SERVICE_WINDOW_OVERLAP`."
    PRD §3.8: "The technician's window is the half-open interval the visit occupies, and the requested slot length is what determines its extent"

    Design: Difficulty/resource_temporal_overlap/technician_half_open_service_window_collision
    """
    first, candidate = _first_slot_and_candidate(f"{_SLOT_DAY}T01:00:00Z")

    res = api_client.schedule_service_visit(
        candidate["id"], {"scheduled_at": f"{_SLOT_DAY}T01:00:00Z"}, _SERVICE)
    # [01:00, 02:00) meets [00:00, 02:00): true interior overlap.
    validate_error(res, ApiErrorId.ERR_SERVICE_WINDOW_OVERLAP, expected_status=422)


def test_visit_starting_exactly_when_another_ends_is_scheduled(api):
    """PRD §3.8: "The technician's window is the half-open interval the visit occupies, and the requested slot length is what determines its extent"

    Design: Difficulty/resource_temporal_overlap/technician_half_open_service_window_collision
    """
    first, candidate = _first_slot_and_candidate(f"{_SLOT_DAY}T02:00:00Z")

    res = api_client.schedule_service_visit(
        candidate["id"], {"scheduled_at": f"{_SLOT_DAY}T02:00:00Z"}, _SERVICE)
    # [02:00, 03:00) only abuts [00:00, 02:00): adjacency is allowed.
    scheduled = validate_success(res, 200)
    assert scheduled["visit_status"] == "SCHEDULED"