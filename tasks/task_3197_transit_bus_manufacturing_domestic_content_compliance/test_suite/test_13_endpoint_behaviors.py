"""Corner tests: endpoint behavior claims (kitted gate, assign gate,
certificate supersede)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_and_assign_slot,
    create_bus_configuration_payload,
    create_bus_unit_payload,
    create_certificate_payload,
    create_component,
    create_engineered_bus,
    create_production_slot_payload,
    get_success_data,
    setup_active_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

PO = TEST_USERS["procurement_officer_headers"]
CE = TEST_USERS["config_engineer_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PP = TEST_USERS["production_planner_headers"]


def test_start_production_requires_kitted_slot(api):
    """PRD section 3.5: "Attempting to start production on a slot whose kit
    has not completed is rejected with `ERR_KIT_INCOMPLETE`; the related
    `ERR_PRODUCTION_NOT_KITTED` covers the same not-kitted condition surfaced
    when the linked kit has not reached `COMPLETE`."

    Design: Corner/endpoints/start_production_requires_kitted_slot
    """
    # The two-component configuration is frozen before activation (PRD section
    # 3.3 allows submit-review only while the contract is DRAFT or AWARDED);
    # the extra AXLE component is not PROPULSION, so the pre-award audit still
    # completes while it stays undocumented.
    first = create_component(name="Engine", category="PROPULSION")
    extra = create_component(name="Axle", category="AXLE",
                             unit_cost_cents=300000, is_domestic=True)
    from test_helpers import (
        setup_active_contract_with_config,
        submit_and_verify_component,
    )
    submit_and_verify_component(first["id"])
    setup = setup_active_contract_with_config(
        contract_overrides={"base_quantity": 1},
        config_components=[first, extra],
        verify_components=False,
    )
    cfg = setup["configuration"]
    bus = create_engineered_bus(setup["contract"]["id"], cfg["id"])
    slot = create_and_assign_slot(bus["id"], line_id="LINE_B")
    assert slot["kit_status"] == "NOT_KITTED"

    resp = api.start_production(slot["id"], PP)
    validate_error(resp, ApiErrorId.ERR_KIT_INCOMPLETE)
    slot = get_success_data(api.get_production_slot(slot["id"], PP))
    assert slot["status"] == "ASSIGNED"


def test_assign_rejects_non_engineered_bus(api):
    """PRD section 3.5: "Assigning a bus to a slot requires the bus to be in
    `ENGINEERED` status and the interval to be conflict-free on the line."
    PRD section 2.5: "Fourth, state-machine legality: whether the target
    resource's current state permits the requested transition, failing as
    `ERR_INVALID_STATE`."

    Design: Corner/endpoints/assign_rejects_non_engineered_bus
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    resp = api.create_bus_unit(
        create_bus_unit_payload(
            setup["contract"]["id"], setup["configuration"]["id"]
        ),
        PP,
    )
    bus = get_success_data(resp)
    assert bus["status"] == "ORDERED"
    resp = api.create_production_slot(create_production_slot_payload(), PP)
    slot = get_success_data(resp)

    resp = api.assign_slot(slot["id"], {"bus_unit_id": bus["id"]}, PP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    slot = get_success_data(api.get_production_slot(slot["id"], PP))
    assert slot["status"] == "OPEN"


def test_second_certificate_supersedes_first(api):
    """PRD section 3.6: "At most one certificate per bus may be `ISSUED` at
    any time: issuing a new certificate for a bus that already has an `ISSUED`
    one moves the prior certificate to `SUPERSEDED`, and a duplicate-live-certificate
    situation is rejected with `ERR_DUPLICATE`."

    Design: Corner/endpoints/certificate_supersede_keeps_single_issued
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    bus = create_engineered_bus(
        setup["contract"]["id"], setup["configuration"]["id"]
    )
    resp = api.issue_certificate(
        bus["id"], create_certificate_payload(variant="COST_BASED"), CO
    )
    cert1 = validate_success(resp, expected_status=201)
    assert cert1["status"] == "ISSUED"

    resp = api.issue_certificate(
        bus["id"], create_certificate_payload(variant="COMPONENT_COUNT"), CO
    )
    cert2 = validate_success(resp, expected_status=201)
    assert cert2["status"] == "ISSUED"

    resp = api.list_bus_certificates(bus["id"], CO)
    certs, _meta = validate_paginated(resp)
    by_id = {c["id"]: c for c in certs}
    assert by_id[cert1["id"]]["status"] == "SUPERSEDED", (
        "the prior ISSUED certificate must move to SUPERSEDED, got "
        f"{by_id[cert1['id']]['status']}"
    )
    assert by_id[cert2["id"]]["status"] == "ISSUED"
    issued = [c for c in certs if c["status"] == "ISSUED"]
    assert len(issued) == 1, "at most one ISSUED certificate per bus"
