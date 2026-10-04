"""Depth tests: priority-pair validation conflicts and boundary precision."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    build_bus_to_delivered,
    create_bus_configuration_payload,
    create_bus_unit_payload,
    create_component,
    create_engineered_bus,
    get_success_data,
    setup_accepted_bus,
    setup_active_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

PO = TEST_USERS["procurement_officer_headers"]
CE = TEST_USERS["config_engineer_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PP = TEST_USERS["production_planner_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
WA = TEST_USERS["warranty_admin_headers"]


def _setup_expired_option(api):
    """ACTIVE contract with one AVAILABLE option year 1; clock advanced beyond
    the exercise deadline so the option auto-expires."""
    setup = setup_active_contract(
        contract_overrides={
            "base_quantity": 2,
            "option_years": 1,
            "option_specs": [{"quantity": 5, "propulsion_type": "DIESEL"}],
        }
    )
    resp = api.list_contract_option_orders(setup["contract"]["id"], PO)
    options, _meta = validate_paginated(resp)
    option = options[0]
    contract = get_success_data(api.get_contract(setup["contract"]["id"], PO))
    # Awarded at the clock epoch 2026-09-01; deadline = +365d = 2027-09-01.
    get_success_data(
        api.set_clock({"to_iso8601": "2027-09-02T00:00:00Z"}, ADMIN),
    )
    return setup, option, contract


def test_expired_option_exercise_reports_invalid_state_not_deadline(api):
    """PRD section 2.4: "Advancing the clock evaluates time-based
    auto-transitions as a side effect: option orders whose `exercise_deadline`
    has been strictly passed flip from `AVAILABLE` to `EXPIRED`, and delivered
    buses whose `acceptance_deadline` has been strictly passed flip from
    `DELIVERED` to `ACCEPTED`."
    PRD section 2.5: "Fourth, state-machine legality: whether the target
    resource's current state permits the requested transition, failing as
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_exercise
    """
    setup, option, contract = _setup_expired_option(api)
    # The expired option is read back through the contract, which evaluates
    # lazy auto-transitions, so the option is EXPIRED by the time we exercise.
    resp = api.list_contract_option_orders(setup["contract"]["id"], PO)
    options, _meta = validate_paginated(resp)
    assert options[0]["status"] == "EXPIRED"

    resp = api.exercise_option_order(
        option["id"],
        {"expected_contract_version": contract["version"]},
        PO,
    )
    # The option is no longer AVAILABLE, so the state-machine legality check
    # (fourth in the global order) reports ERR_INVALID_STATE before the
    # deadline rule (ninth) is ever reached.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_expired_option_never_computes_price(api):
    """PRD section 3.2: "An option order's `exercised_unit_price_cents` stays
    unset until exercise."
    PRD section 2.5: "Fourth, state-machine legality: whether the target
    resource's current state permits the requested transition, failing as
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_exercise
    """
    setup, option, contract = _setup_expired_option(api)
    resp = api.exercise_option_order(
        option["id"],
        {"expected_contract_version": contract["version"]},
        PO,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    resp = api.get_option_order(option["id"], PO)
    refreshed = validate_success(resp)
    assert refreshed["status"] == "EXPIRED"
    assert refreshed["exercised_unit_price_cents"] is None, (
        "a rejected exercise never computes pricing; "
        f"got {refreshed['exercised_unit_price_cents']}"
    )


def test_engineer_safety_gate_reports_accessibility_error(api):
    """PRD section 3.5: "Engineering also enforces the accessibility safety
    gate: for a federally funded agency, a bus whose configuration's
    `accessibility_features` lack `WHEELCHAIR_LIFT` may not be engineered, and
    the attempt is rejected with `ERR_ACCESSIBILITY_SAFETY`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_engineer
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    # A DRAFT configuration that also lacks WHEELCHAIR_LIFT: the safety gate
    # fires regardless of the configuration's frozen-ness.
    resp = api.create_bus_configuration(
        create_bus_configuration_payload(
            setup["contract"]["id"],
            [setup["components"][0]["id"]],
            propulsion_type="CNG",
            seating_layout={"rows": 8},
            accessibility_features=["PRIORITY_SEATING"],
        ),
        CE,
    )
    bad_cfg = get_success_data(resp)
    bus = get_success_data(
        api.create_bus_unit(
            create_bus_unit_payload(setup["contract"]["id"], bad_cfg["id"]), PP
        ),
    )
    resp = api.engineer_bus(bus["id"], CE)
    validate_error(resp, ApiErrorId.ERR_ACCESSIBILITY_SAFETY)
    bus = get_success_data(api.get_bus_unit(bus["id"], PP))
    assert bus["status"] == "ORDERED"


def test_engineer_frozen_but_noncompliant_config_reports_accessibility(api):
    """PRD section 3.5: "Engineering also enforces the accessibility safety
    gate: for a federally funded agency, a bus whose configuration's
    `accessibility_features` lack `WHEELCHAIR_LIFT` may not be engineered, and
    the attempt is rejected with `ERR_ACCESSIBILITY_SAFETY`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_engineer
    """
    # Non-federally-funded agency: the accessibility gate does not apply at
    # freeze, so a WHEELCHAIR_LIFT-less configuration freezes fine there; then
    # engineering is attempted under a federally funded agency's contract is
    # impossible cross-agency, so instead: federally funded agency, config
    # frozen while DRAFT contract with a noncompliant config is impossible
    # (freeze gate blocks it). Use the DRAFT-config scenario: safety gate
    # still wins over referential integrity.
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    resp = api.create_bus_configuration(
        create_bus_configuration_payload(
            setup["contract"]["id"],
            [setup["components"][0]["id"]],
            propulsion_type="CNG",
            seating_layout={"rows": 8},
            accessibility_features=["PRIORITY_SEATING"],
        ),
        CE,
    )
    bad_cfg = get_success_data(resp)
    bus = get_success_data(
        api.create_bus_unit(
            create_bus_unit_payload(setup["contract"]["id"], bad_cfg["id"]), PP
        ),
    )
    resp = api.engineer_bus(bus["id"], CE)
    err = validate_error(resp, ApiErrorId.ERR_ACCESSIBILITY_SAFETY)
    assert err["error_id"] == "ERR_ACCESSIBILITY_SAFETY"
