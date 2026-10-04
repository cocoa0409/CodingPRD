"""Take-or-pay contract lifecycle: creation defaults, pagination, the renewal
cycle, expiry, the termination cascade, and OCC on amendments."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    agree_turnaround,
    api_client,
    assert_contract,
    create_accepted_evaluation,
    create_amendment_payload,
    create_connection,
    create_contract,
    create_contract_payload,
    create_network,
    create_tank_with_telemetry_delivery,
    create_turnaround,
    list_tank_deliveries,
    set_logical_clock,
    setup_standard_onsite_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_contract_computed_end_date_and_defaults(api):
    """PRD section 3.2: "The server copies `mode`, `product`, and `site_label`
    from the evaluation, computes `end_date` as `start_date` plus `term_months`
    calendar months, initializes `makeup_credit_balance_cents` to 0 and
    `failover_active` to false, and parks the contract in `DRAFT`."
    PRD section 3.2: "and optionally `makeup_credit_cap_pct`, which defaults to
    0.10 — ten percent."

    Design: Corner/entities/contract_computed_end_date_and_defaults
    """
    set_logical_clock()
    customer, evaluation = create_accepted_evaluation(
        {"name": "Fabrikam Chips", "segment": "ELECTRONICS", "credit_standing": "PRIME"}
    )
    response = api_client.create_contract(
        create_contract_payload(customer["id"], evaluation["id"]),
        TEST_USERS["supply_planner_headers"],
    )
    data = validate_success(response, 201)
    assert_contract(data)
    assert data["end_date"] == "2036-10-01", (
        f"start 2026-10-01 + 120 months must be 2036-10-01, got {data['end_date']}"
    )
    assert data["mode"] == "ONSITE_PLANT"
    assert data["product"] == "N2"
    assert data["site_label"] == "FAB-1"
    assert data["makeup_credit_cap_pct"] == 0.10
    assert data["makeup_credit_balance_cents"] == 0
    assert data["failover_active"] is False
    assert data["status"] == "DRAFT"


def test_contracts_list_paginates_with_total_count_and_has_more(api):
    """PRD section 2.3: "`limit` sets the maximum number of items returned;
    when omitted it defaults to 10, and it may not be less than 1 or greater
    than 100. `offset` sets how many items are skipped and defaults to 0.
    Unless stated otherwise, every list endpoint returns resources sorted by
    `created_at` in ascending order, and the `meta` object of a list response
    carries `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/contracts_list_paginates_with_total_count_and_has_more
    """
    set_logical_clock()
    customer, evaluation = create_accepted_evaluation(
        {"name": "Fabrikam Chips", "segment": "ELECTRONICS", "credit_standing": "PRIME"}
    )
    create_contract(customer["id"], evaluation["id"])
    create_contract(customer["id"], evaluation["id"], term_months=60,
                    start_date="2027-01-01", min_monthly_volume_nm3=2100000,
                    unit_price_cents_per_nm3=13, monthly_facility_fee_cents=510000)
    create_contract(customer["id"], evaluation["id"], term_months=180,
                    start_date="2027-06-01", min_monthly_volume_nm3=2200000,
                    unit_price_cents_per_nm3=14, monthly_facility_fee_cents=520000)
    page1, meta1 = validate_paginated(api_client.list_contracts(
        TEST_USERS["supply_planner_headers"],
        params={"customer_id": customer["id"], "limit": 2, "offset": 0},
    ))
    assert len(page1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True
    page2, meta2 = validate_paginated(api_client.list_contracts(
        TEST_USERS["supply_planner_headers"],
        params={"customer_id": customer["id"], "limit": 2, "offset": 2},
    ))
    assert len(page2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False


def test_contract_renewal_cycle(api):
    """PRD section 2.4: "Any contract in `ACTIVE` whose `end_date` is at most
    ninety days away — the current time is at or after `end_date` minus ninety
    days — moves to `RENEWAL_OPEN`."
    PRD section 3.2: "A renewal is an amendment call with `kind` set to
    `RENEWAL`: it carries the same `expected_contract_version` guard, requires
    `new_end_date` to be present and strictly later than the current `end_date`
    (otherwise `ERR_VALIDATION`), moves the contract back to `ACTIVE` with the
    new `end_date` and any new fee, minimum, or price terms applied, and
    increments `version`."

    Design: Difficulty/non_linear_state_machine/contract_renewal_cycle
    """
    bundle = setup_standard_onsite_scenario(with_plant=False)
    contract = bundle["contract"]
    set_logical_clock("2036-07-03T00:00:00Z")
    opened = validate_success(api_client.get_contract(
        contract["id"], TEST_USERS["supply_planner_headers"]
    ))
    assert opened["status"] == "RENEWAL_OPEN", (
        f"sweep at exactly end_date - 90d (2036-07-03) must open renewal, got {opened['status']}"
    )
    renewed = validate_success(api_client.create_contract_amendment(
        contract["id"],
        create_amendment_payload(
            kind="RENEWAL", expected_contract_version=opened["version"],
            new_end_date="2041-10-01", new_monthly_facility_fee_cents=550000,
        ),
        TEST_USERS["supply_planner_headers"],
    ))
    assert_contract(renewed)
    assert renewed["status"] == "ACTIVE", (
        f"renewal must close the cycle back to ACTIVE, got {renewed['status']}"
    )
    assert renewed["end_date"] == "2041-10-01"
    assert renewed["monthly_facility_fee_cents"] == 550000
    assert renewed["version"] == opened["version"] + 1


def test_contract_expires_after_unrenewed_window(api):
    """PRD section 2.4: "Any contract whose `end_date` has passed — the current
    time is strictly after `end_date` — moves from `RENEWAL_OPEN` to
    `EXPIRED`."
    PRD section 3.2: "Termination is available from `DRAFT`, `ACTIVE`, or
    `RENEWAL_OPEN` and lands the contract in `TERMINATED`."

    Design: Corner/state_machines/contract_expires_after_unrenewed_window
    """
    bundle = setup_standard_onsite_scenario(with_plant=False)
    contract = bundle["contract"]
    set_logical_clock("2036-07-03T00:00:00Z")
    set_logical_clock("2036-10-02T00:00:00Z")
    expired = validate_success(api_client.get_contract(
        contract["id"], TEST_USERS["supply_planner_headers"]
    ))
    assert expired["status"] == "EXPIRED", (
        f"clock past end_date with no renewal must expire the contract, got {expired['status']}"
    )
    response = api_client.terminate_contract(
        contract["id"], TEST_USERS["supply_planner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_contract_terminate_full_cascade(api):
    """PRD section 3.2: "Terminating from `ACTIVE` or `RENEWAL_OPEN` fires the
    full cascade in a single action: any non-`DECOMMISSIONED` plant of the
    contract is decommissioned and its `effective_capacity_nm3h` zeroed; every
    turnaround of that plant in `PROPOSED`, `AGREED`, or `SCHEDULED` moves to
    `CANCELLED` — one already `IN_PROGRESS` is deliberately not cancelled and
    runs to completion; every `ACTIVE` pipeline connection of the contract
    moves to `RELEASED`, which re-aggregates the network's reserved and
    available capacity per §3.4; every delivery still `SCHEDULED` for a tank of
    this customer whose product matches the contract's `product` moves to
    `CANCELLED`; and the contract's `version` increments."

    Design: Corner/state_machines/contract_terminate_full_cascade
    """
    bundle = setup_standard_onsite_scenario()
    customer, contract, plant = bundle["customer"], bundle["contract"], bundle["plant"]
    network = create_network()
    connection = create_connection(network["id"], contract["id"],
                                   reserved_flow_nm3h=4000, purpose="BACKUP")
    _, delivery = create_tank_with_telemetry_delivery(customer["id"])
    turnaround = create_turnaround(plant["id"])
    turnaround = agree_turnaround(turnaround["id"], turnaround["version"], customer["id"])

    terminated = validate_success(api_client.terminate_contract(
        contract["id"], TEST_USERS["supply_planner_headers"]
    ))
    assert terminated["status"] == "TERMINATED"

    plant_after = validate_success(api_client.get_plant(
        plant["id"], TEST_USERS["plant_operator_headers"]
    ))
    assert plant_after["status"] == "DECOMMISSIONED"
    assert plant_after["effective_capacity_nm3h"] == 0

    turnarounds = validate_success(api_client.list_plant_turnarounds(
        plant["id"], TEST_USERS["plant_operator_headers"]
    ))
    ta_after = [t for t in turnarounds if t["id"] == turnaround["id"]][0]
    assert ta_after["status"] == "CANCELLED"

    connection_after = validate_success(api_client.get_connection(
        connection["id"], TEST_USERS["pipeline_dispatcher_headers"]
    ))
    assert connection_after["status"] == "RELEASED"
    network_after = validate_success(api_client.get_network(
        network["id"], TEST_USERS["pipeline_dispatcher_headers"]
    ))
    assert network_after["reserved_capacity_nm3h"] == 0
    assert network_after["available_capacity_nm3h"] == 10000

    delivery_after = validate_success(api_client.get_delivery(
        delivery["id"], TEST_USERS["pipeline_dispatcher_headers"]
    ))
    assert delivery_after["transport_status"] == "CANCELLED"


def test_occ_contract_amendment_stale_version(api):
    """PRD section 2.7: "Amending or renewing a supply contract requires the
    request to include `expected_contract_version`, holding the contract
    `version` the client last observed."
    PRD section 2.7: "In both cases, if the resource's version has advanced
    past the client's observed value since the client last read it, the write
    is rejected with `ERR_STALE_VERSION` (HTTP 412): the client's picture of
    the commercial terms — or of the turnaround window on the table — is stale
    and must be re-read before writing."

    Design: Corner/complexity_layers/occ_contract_amendment_stale_version
    """
    bundle = setup_standard_onsite_scenario(with_plant=False)
    contract = bundle["contract"]
    observed_version = contract["version"]
    amended = validate_success(api_client.create_contract_amendment(
        contract["id"],
        create_amendment_payload(
            kind="AMENDMENT", expected_contract_version=observed_version,
            new_monthly_facility_fee_cents=510000,
        ),
        TEST_USERS["supply_planner_headers"],
    ))
    assert amended["version"] == observed_version + 1
    assert amended["monthly_facility_fee_cents"] == 510000

    replay = api_client.create_contract_amendment(
        contract["id"],
        create_amendment_payload(
            kind="AMENDMENT", expected_contract_version=observed_version,
            new_monthly_facility_fee_cents=520000,
        ),
        TEST_USERS["supply_planner_headers"],
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
    current = validate_success(api_client.get_contract(
        contract["id"], TEST_USERS["supply_planner_headers"]
    ))
    assert current["monthly_facility_fee_cents"] == 510000, (
        "the stale write must change nothing"
    )
