"""Corner tests: state machine claims (award gate, terminal lockdown, expired
option exercise, warranty review loop, rework loop, bus initial state)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    build_bus_to_delivered,
    build_bus_to_plant_inspection,
    create_agency,
    create_bus_configuration_payload,
    create_bus_unit_payload,
    create_component,
    create_draft_contract,
    create_engineered_bus,
    create_frozen_configuration,
    create_parts_stock_payload,
    create_warranty_claim_payload,
    get_success_data,
    make_warranty_admin_headers,
    setup_accepted_bus,
    setup_active_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

PO = TEST_USERS["procurement_officer_headers"]
CE = TEST_USERS["config_engineer_headers"]
PP = TEST_USERS["production_planner_headers"]
INSP = TEST_USERS["agency_inspector_headers"]
WA = TEST_USERS["warranty_admin_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_award_rejected_without_frozen_configuration(api):
    """PRD section 3.2: "The `ProcurementOfficer` may award only while the
    agency is `ACTIVE`, the `base_quantity` is at least 1, and at least one
    bus configuration engineered under the contract has reached `FROZEN`
    status."

    Design: Corner/state_machines/contract_award_requires_frozen_config
    """
    agency = create_agency()
    contract = create_draft_contract(agency["id"], base_quantity=2)
    component = create_component()
    resp = api.create_bus_configuration(
        create_bus_configuration_payload(contract["id"], [component["id"]]), CE
    )
    cfg = get_success_data(resp)

    resp = api.award_contract(contract["id"], PO)
    assert resp.status_code in (400, 409, 422), (
        "award without a FROZEN configuration must be rejected, got "
        f"{resp.status_code}"
    )

    # After freezing, the award succeeds.
    get_success_data(api.submit_review_configuration(cfg["id"], CE))
    get_success_data(
        api.freeze_configuration(
            cfg["id"], {"expected_contract_version": contract["version"]}, CE
        ),
    )
    resp = api.award_contract(contract["id"], PO)
    awarded = validate_success(resp)
    assert awarded["status"] == "AWARDED"
    assert awarded["awarded_at"] == "2026-09-01T00:00:00Z", (
        "award stamps awarded_at with the current logical time (the epoch "
        f"before any clock call); got {awarded['awarded_at']}"
    )


def test_completed_contract_rejects_further_transitions(api):
    """PRD section 3.2: "Both `COMPLETED` and `TERMINATED` are terminal."
    PRD section 2.5: "Fourth, state-machine legality: whether the target
    resource's current state permits the requested transition, failing as
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/contract_terminal_completed_lockdown
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    bus = build_bus_to_delivered(setup)
    # Delivery FAIL with defects -> bus REJECTED, making the contract
    # completable (every bus terminal, no options).
    resp = api.create_inspection_record(
        {"bus_unit_id": bus["id"], "inspection_type": "DELIVERY",
         "inspector_id": "insp-1", "result": "FAIL",
         "defects": ["DOOR_MISALIGN"]},
        INSP,
    )
    validate_success(resp, expected_status=201)

    resp = api.complete_contract(setup["contract"]["id"], PO)
    completed = validate_success(resp)
    assert completed["status"] == "COMPLETED"

    resp = api.terminate_contract(setup["contract"]["id"], PO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def _setup_active_contract_with_option(api, quantity=5):
    setup = setup_active_contract(
        contract_overrides={
            "base_quantity": 2,
            "option_years": 1,
            "option_specs": [{"quantity": quantity, "propulsion_type": "DIESEL"}],
        }
    )
    resp = api.list_contract_option_orders(setup["contract"]["id"], PO)
    options, _meta = validate_paginated(resp)
    return setup, options[0]


def test_exercising_expired_option_rejected_and_price_unset(api):
    """PRD section 3.2: "An option order's `exercised_unit_price_cents` stays
    unset until exercise."
    PRD section 2.4: "Advancing the clock evaluates time-based
    auto-transitions as a side effect: option orders whose `exercise_deadline`
    has been strictly passed flip from `AVAILABLE` to `EXPIRED`, and
    delivered buses whose `acceptance_deadline` has been strictly passed flip
    from `DELIVERED` to `ACCEPTED`."
    PRD section 2.5: "Fourth, state-machine legality: whether the target
    resource's current state permits the requested transition, failing as
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/option_exercise_from_expired_invalid
    """
    setup, option = _setup_active_contract_with_option(api)
    contract = get_success_data(
        api.get_contract(setup["contract"]["id"], PO)
    )
    get_success_data(
        api.set_clock({"to_iso8601": "2027-09-02T00:00:00Z"}, ADMIN),
    )
    resp = api.exercise_option_order(
        option["id"], {"expected_contract_version": contract["version"]}, PO
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    option = get_success_data(api.get_option_order(option["id"], PO))
    assert option["status"] == "EXPIRED"
    assert option["exercised_unit_price_cents"] is None


def test_second_review_loop_rejected(api):
    """PRD section 3.9: "A claim in `APPROVED` may be moved back to
    `UNDER_REVIEW` exactly one time, releasing the prior stock reservation by
    decrementing `reserved_quantity`; a claim that has already made this loop
    and attempts it a second time is rejected with
    `ERR_REVIEW_LOOP_EXHAUSTED`."

    Design: Corner/state_machines/warranty_second_review_loop_rejected
    """
    setup = setup_accepted_bus(
        component_overrides={"name": "Alternator", "category": "ELECTRICAL",
                             "unit_cost_cents": 75000},
    )
    component = setup["components"][0]
    get_success_data(
        api.create_parts_stock(
            create_parts_stock_payload(
                setup["agency"]["id"], component["id"], quantity=10
            ),
            WA,
        ),
    )
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(setup["bus"]["id"], component["id"],
                                      defect_code="ALT_FAIL"),
        WA,
    )
    claim = get_success_data(resp)
    wa1 = make_warranty_admin_headers("wa-1")
    get_success_data(api.start_review_claim(claim["id"], wa1))
    get_success_data(api.approve_claim(claim["id"], wa1))
    # First loop back: allowed.
    get_success_data(api.start_review_claim(claim["id"], wa1))
    resp = api.approve_claim(claim["id"], wa1)
    claim = validate_success(resp)
    assert claim["status"] == "APPROVED"
    # Second loop attempt: rejected.
    resp = api.start_review_claim(claim["id"], wa1)
    validate_error(resp, ApiErrorId.ERR_REVIEW_LOOP_EXHAUSTED)


def test_failed_plant_inspection_loops_back_to_built(api):
    """PRD section 3.8: "A failing `PLANT` inspection sends the bus back
    `PLANT_INSPECTION` → `BUILT` for rework, and the bus may be submitted for
    plant inspection again once its issues are resolved."
    PRD section 3.8: "A passing `PLANT` inspection moves the bus
    `PLANT_INSPECTION` → `IN_TRANSIT`."

    Design: Corner/state_machines/bus_unit_plant_fail_rework_loop
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    bus = build_bus_to_plant_inspection(setup)

    resp = api.create_inspection_record(
        {"bus_unit_id": bus["id"], "inspection_type": "PLANT",
         "inspector_id": "insp-1", "result": "FAIL", "defects": ["BRAKE_LINE"]},
        INSP,
    )
    validate_success(resp, expected_status=201)
    bus = get_success_data(api.get_bus_unit(bus["id"], PP))
    assert bus["status"] == "BUILT", (
        f"failed plant inspection loops the bus back to BUILT; got {bus['status']}"
    )

    get_success_data(api.submit_plant_inspection(bus["id"], PP))
    resp = api.create_inspection_record(
        {"bus_unit_id": bus["id"], "inspection_type": "PLANT",
         "inspector_id": "insp-1", "result": "PASS"},
        INSP,
    )
    validate_success(resp, expected_status=201)
    bus = get_success_data(api.get_bus_unit(bus["id"], PP))
    assert bus["status"] == "IN_TRANSIT"


def test_new_bus_starts_ordered_unpaid_with_serial(api):
    """PRD section 3.5: "The server mints a unique `serial_number`,
    initializes `payment_status` to `UNPAID`, and the bus is born in
    `ORDERED`."

    Design: Corner/state_machines/bus_initial_state_and_serial_minted
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    resp = api.create_bus_unit(
        create_bus_unit_payload(
            setup["contract"]["id"], setup["configuration"]["id"]
        ),
        PP,
    )
    bus = validate_success(resp, expected_status=201)
    assert bus["status"] == "ORDERED"
    assert bus["payment_status"] == "UNPAID"
    assert isinstance(bus["serial_number"], str) and bus["serial_number"], (
        "the server must mint a non-empty serial_number"
    )
