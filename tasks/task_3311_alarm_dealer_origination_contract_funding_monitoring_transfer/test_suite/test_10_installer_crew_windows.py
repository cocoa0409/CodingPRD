"""The installer-crew overlap rule for scheduled installations."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    set_logical_clock,
    register_customer,
    originate_direct_contract,
    find_monitoring_account,
    provision_monitoring_account,
    create_installation_payload,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)

_SERVICE = TEST_USERS["service_coordinator_headers"]

_ENG = "ENG-Z"
_OTHER_ENG = "ENG-Y"
_SLOT_DAY = "2026-09-12"


def _contract_with_crew_slot():
    """Contract A holding a 180-minute installation on ENG-Z at midnight, plus a
    second contract B with no installation yet on either crew."""
    set_logical_clock("2026-09-01T00:00:00Z")
    customer_a = register_customer(full_name="Ada First",
                                   email="ada.first@example.com")
    customer_b = register_customer(full_name="Ben Second",
                                   email="ben.second@example.com")
    contract_a = originate_direct_contract(
        customer_a["id"], equipment_config_code="PREMIUM", credit_score=700,
        contract_term_months=60, monthly_monitoring_cents=4999,
        installation_scheduled_at=f"{_SLOT_DAY}T00:00:00Z",
        installation_duration_minutes=180, installation_engineer_id=_ENG,
        premises_address_line="170 Quince St")
    contract_b = originate_direct_contract(
        customer_b["id"], equipment_config_code="PREMIUM", credit_score=700,
        contract_term_months=60, monthly_monitoring_cents=4999,
        premises_address_line="180 Quince St")
    return contract_a, contract_b


# ─── Difficulty: resource_temporal_overlap / installer_crew_buffer_window_collision ───

def test_crew_slot_inside_an_existing_installation_window_is_rejected(api):
    """PRD §3.5: "The crew is a resource whose windows may not collide: a newly scheduled installation must not overlap another non-cancelled slot of the same engineer, and the collision is reported with `ERR_SERVICE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/installer_crew_buffer_window_collision
    """
    contract_a, contract_b = _contract_with_crew_slot()

    res = api_client.create_installation(
        create_installation_payload(
            contract_b["id"], scheduled_at=f"{_SLOT_DAY}T00:20:00Z",
            installation_engineer_id=_ENG, duration_minutes=180),
        _SERVICE,
    )
    validate_error(res, ApiErrorId.ERR_SERVICE_WINDOW_OVERLAP, expected_status=422)


def test_crew_slot_clear_of_the_existing_window_is_accepted(api):
    """PRD §3.5: "The crew is a resource whose windows may not collide: a newly scheduled installation must not overlap another non-cancelled slot of the same engineer, and the collision is reported with `ERR_SERVICE_WINDOW_OVERLAP`."
    PRD §3.5: "An installation begins `SCHEDULED` and carries its `equipment_config_code`, copied from the contract when it completes."

    Design: Difficulty/resource_temporal_overlap/installer_crew_buffer_window_collision
    """
    contract_a, contract_b = _contract_with_crew_slot()

    created = validate_success(api_client.create_installation(
        create_installation_payload(
            contract_b["id"], scheduled_at=f"{_SLOT_DAY}T04:30:00Z",
            installation_engineer_id=_ENG, duration_minutes=180),
        _SERVICE,
    ), 201)
    assert created["install_status"] == "SCHEDULED"

    # The accepted slot is a real, usable crew booking: it carries the contract's
    # equipment configuration once completed.
    provision_monitoring_account(contract_b["id"])
    completed = validate_success(
        api_client.complete_installation(created["id"], _SERVICE), 200)
    assert completed["equipment_config_code"] == "PREMIUM"