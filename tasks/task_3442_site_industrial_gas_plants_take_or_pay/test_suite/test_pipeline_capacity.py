"""Pipeline networks and firm capacity: exact-fit admission, the
create/release conservation invariant, release state rules, the PRIMARY
connection activation gate, and purpose/mode matching."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_network_capacity_invariant,
    create_active_contract,
    create_connection,
    create_connection_payload,
    create_draft_contract,
    create_network,
    release_connection,
    set_logical_clock,
    setup_standard_onsite_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

METCO_CUSTOMER = {"name": "MetCo", "segment": "METALS", "credit_standing": "PRIME"}
METCO_EVALUATION = {
    "site_label": "MILL-9", "demand_avg_nm3h": 2000, "demand_peak_nm3h": 2600,
    "required_purity_percent": 99.9, "required_product": "N2",
    "pipeline_available": True,
}
METCO_CONTRACT = {
    "min_monthly_volume_nm3": 800000, "unit_price_cents_per_nm3": 10,
    "monthly_facility_fee_cents": 200000, "facility_fee_escalation_pct_annual": 0.02,
    "base_power_index": 0.08, "power_kwh_per_nm3": 0.30,
}


def test_pipeline_aggregate_capacity_exact_fit(api):
    """PRD section 3.4: "Admission is a capacity check: the requested flow must
    fit within the network's currently available capacity, where an exact fit —
    reservations totaling precisely the nameplate — is allowed, while a single
    Nm3/h over is rejected with `ERR_PIPELINE_CAPACITY_EXCEEDED`."
    PRD section 3.4: "A connection is born with `status` `ACTIVE` and
    immediately adds its flow to the network's reserved total."

    Design: Difficulty/resource_temporal_overlap/pipeline_aggregate_capacity_exact_fit
    """
    set_logical_clock()
    network = create_network()
    metco = create_active_contract(
        customer_overrides=METCO_CUSTOMER,
        evaluation_overrides=METCO_EVALUATION,
        contract_overrides=METCO_CONTRACT,
        network=network,
        primary_reserved_flow_nm3h=6000,
    )
    fab = create_draft_contract(
        {"name": "Fabrikam Chips", "segment": "ELECTRONICS", "credit_standing": "PRIME"}
    )

    exact_fit = api_client.create_connection(
        create_connection_payload(network["id"], fab["contract"]["id"],
                                  reserved_flow_nm3h=4000, purpose="BACKUP"),
        TEST_USERS["pipeline_dispatcher_headers"],
    )
    validate_success(exact_fit, 201)
    after_fit = validate_success(api_client.get_network(
        network["id"], TEST_USERS["pipeline_dispatcher_headers"]
    ))
    assert after_fit["reserved_capacity_nm3h"] == 10000, (
        f"6000 + 4000 must reserve the full nameplate, got {after_fit['reserved_capacity_nm3h']}"
    )
    assert after_fit["available_capacity_nm3h"] == 0
    assert_network_capacity_invariant(after_fit)

    one_over = api_client.create_connection(
        create_connection_payload(network["id"], fab["contract"]["id"],
                                  reserved_flow_nm3h=1, purpose="BACKUP"),
        TEST_USERS["pipeline_dispatcher_headers"],
    )
    validate_error(one_over, ApiErrorId.ERR_PIPELINE_CAPACITY_EXCEEDED)
    assert metco["connection"]["purpose"] == "PRIMARY"


def test_pipeline_capacity_conservation(api):
    """PRD section 3.4: "The aggregation invariant is maintained continuously:
    `reserved_capacity_nm3h` is the sum of `reserved_flow_nm3h` over the
    network's `ACTIVE` connections, `available_capacity_nm3h` is the nameplate
    minus the reserved total, and the two always sum back to the nameplate."
    PRD section 3.4: "Releasing a connection — by a `PipelineDispatcher`, or
    through the contract-termination cascade — is legal only from `ACTIVE`, any
    other state drawing `ERR_INVALID_STATE_TRANSITION`, and moves it to
    `RELEASED`, subtracting its flow from the reservation as a compensating
    action that restores availability."

    Design: Difficulty/compensating_invariant/pipeline_capacity_conservation
    """
    set_logical_clock()
    network = create_network()
    metco = create_active_contract(
        customer_overrides=METCO_CUSTOMER,
        evaluation_overrides=METCO_EVALUATION,
        contract_overrides=METCO_CONTRACT,
        network=network,
        primary_reserved_flow_nm3h=6000,
    )
    fab = create_draft_contract(
        {"name": "Fabrikam Chips", "segment": "ELECTRONICS", "credit_standing": "PRIME"}
    )
    backup = create_connection(network["id"], fab["contract"]["id"],
                               reserved_flow_nm3h=4000, purpose="BACKUP")

    released = release_connection(metco["connection"]["id"])
    assert released["status"] == "RELEASED", (
        f"the compensating release must land in RELEASED, got {released['status']}"
    )
    after = validate_success(api_client.get_network(
        network["id"], TEST_USERS["pipeline_dispatcher_headers"]
    ))
    assert after["reserved_capacity_nm3h"] == 4000
    assert after["available_capacity_nm3h"] == 6000
    assert_network_capacity_invariant(after)
    backup_after = validate_success(api_client.get_connection(
        backup["id"], TEST_USERS["pipeline_dispatcher_headers"]
    ))
    assert backup_after["status"] == "ACTIVE"


def test_connection_release_twice_returns_invalid_state(api):
    """PRD section 3.4: "Releasing a connection — by a `PipelineDispatcher`, or
    through the contract-termination cascade — is legal only from `ACTIVE`, any
    other state drawing `ERR_INVALID_STATE_TRANSITION`, and moves it to
    `RELEASED`, subtracting its flow from the reservation as a compensating
    action that restores availability."

    Design: Corner/state_machines/connection_release_twice_returns_invalid_state
    """
    bundle = setup_standard_onsite_scenario(with_plant=False)
    network = create_network()
    connection = create_connection(network["id"], bundle["contract"]["id"],
                                   reserved_flow_nm3h=4000, purpose="BACKUP")
    release_connection(connection["id"])
    response = api_client.release_connection(
        connection["id"], TEST_USERS["pipeline_dispatcher_headers"]
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    network_after = validate_success(api_client.get_network(
        network["id"], TEST_USERS["pipeline_dispatcher_headers"]
    ))
    assert network_after["reserved_capacity_nm3h"] == 0, (
        "a rejected second release must not double-refund capacity"
    )
    assert_network_capacity_invariant(network_after)


def test_pipeline_activation_requires_primary_connection(api):
    """PRD section 3.2: "A `PIPELINE`-mode contract must already hold an
    `ACTIVE` pipeline connection with purpose `PRIMARY`
    (`ERR_PIPELINE_CONNECTION_REQUIRED`)."
    PRD section 3.4: "The referenced contract must be in `DRAFT` or `ACTIVE`,
    and the reserved flow must be at least 1 Nm3/h — a non-positive flow is
    rejected with `ERR_VALIDATION`."

    Design: Corner/validations/pipeline_activation_requires_primary_connection
    """
    set_logical_clock()
    network = create_network()
    bundle = create_draft_contract(METCO_CUSTOMER, METCO_EVALUATION, METCO_CONTRACT)
    contract = bundle["contract"]
    response = api_client.activate_contract(
        contract["id"], TEST_USERS["supply_planner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_PIPELINE_CONNECTION_REQUIRED)

    create_connection(network["id"], contract["id"],
                      reserved_flow_nm3h=6000, purpose="PRIMARY")
    activated = validate_success(api_client.activate_contract(
        contract["id"], TEST_USERS["supply_planner_headers"]
    ))
    assert activated["status"] == "ACTIVE"


def test_connection_purpose_mode_mismatch(api):
    """PRD section 3.4: "Purpose and contract mode must agree: `PRIMARY` serves
    a contract whose mode is `PIPELINE`, while `BACKUP` serves an
    `ONSITE_PLANT` contract; either mismatch is rejected with
    `ERR_MODE_MISMATCH`."

    Design: Corner/validations/connection_purpose_mode_mismatch
    """
    set_logical_clock()
    network = create_network()
    bundle = create_draft_contract(
        {"name": "Fabrikam Chips", "segment": "ELECTRONICS", "credit_standing": "PRIME"}
    )
    response = api_client.create_connection(
        create_connection_payload(network["id"], bundle["contract"]["id"],
                                  reserved_flow_nm3h=1000, purpose="PRIMARY"),
        TEST_USERS["pipeline_dispatcher_headers"],
    )
    validate_error(response, ApiErrorId.ERR_MODE_MISMATCH)
    connections, meta = validate_paginated(api_client.list_connections(
        TEST_USERS["pipeline_dispatcher_headers"],
        params={"network_id": network["id"]},
    ))
    assert connections == [] and meta["total_count"] == 0
