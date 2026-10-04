"""Corner tests: cross-cutting layers (OCC on exercise, end-to-end cascade)
and immediate consistency."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_agency,
    create_and_assign_slot,
    create_bus_configuration_payload,
    create_component,
    create_draft_contract,
    create_engineered_bus,
    create_frozen_configuration,
    get_success_data,
    setup_active_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

PO = TEST_USERS["procurement_officer_headers"]
CE = TEST_USERS["config_engineer_headers"]
PP = TEST_USERS["production_planner_headers"]


def test_sibling_exercise_invalidates_stale_version(api):
    """PRD section 2.7: "If the contract's current `version` does not match
    the supplied value — because an intervening award, activation, sibling
    option exercise, or sibling freeze advanced it — the write is rejected
    with `ERR_STALE_VERSION` (HTTP 412). Both of these writes, when they
    succeed, themselves increment the parent contract's `version` by one, as
    do the award and activation transitions."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_option_exercise
    """
    setup = setup_active_contract(
        contract_overrides={
            "base_quantity": 2,
            "option_years": 2,
            "option_specs": [
                {"quantity": 4, "propulsion_type": "DIESEL"},
                {"quantity": 10, "propulsion_type": "DIESEL"},
            ],
        }
    )
    resp = api.list_contract_option_orders(setup["contract"]["id"], PO)
    options, _meta = validate_paginated(resp)
    opt1, opt2 = options[0], options[1]
    contract = get_success_data(
        api.get_contract(setup["contract"]["id"], PO),
    )
    stale_version = contract["version"]

    resp = api.exercise_option_order(
        opt1["id"], {"expected_contract_version": stale_version}, PO
    )
    exercised = validate_success(resp)
    assert exercised["status"] == "EXERCISED"

    resp = api.exercise_option_order(
        opt2["id"], {"expected_contract_version": stale_version}, PO
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_end_to_end_verify_cascade_unblocks_production(api):
    """PRD section 3.5: "On assignment the slot moves `OPEN` → `ASSIGNED` and
    records the `bus_unit_id`; if the bus's parts kit has already reached
    `COMPLETE`, the slot's `kit_status` flips to `KITTED` at assign time
    rather than waiting for a later event."
    PRD section 3.5: "A successful start fires three cascades at once: the bus
    moves `ENGINEERED` → `IN_PRODUCTION`, the linked parts kit moves
    `COMPLETE` → `CONSUMED`, and for every component in the kit, the parts
    stock row keyed by the contract's agency and that component — if such a
    row exists — has its `quantity` decremented by one."

    Design: Corner/cross_cutting_layers/cascade_end_to_end_doc_to_bus_state
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    # The kit's only component was verified during the pre-award audit, so the
    # kit created at engineer time is already COMPLETE.
    bus = create_engineered_bus(
        setup["contract"]["id"], setup["configuration"]["id"]
    )
    resp = api.list_bus_parts_kits(bus["id"], PP)
    kits, _meta = validate_paginated(resp)
    assert kits[0]["status"] == "COMPLETE"

    slot = create_and_assign_slot(bus["id"], line_id="LINE_B")
    assert slot["kit_status"] == "KITTED", (
        "kit already COMPLETE at assign time flips kit_status to KITTED; got "
        f"{slot['kit_status']}"
    )

    resp = api.start_production(slot["id"], PP)
    validate_success(resp)
    bus = get_success_data(api.get_bus_unit(bus["id"], PP))
    assert bus["status"] == "IN_PRODUCTION"
    resp = api.list_bus_parts_kits(bus["id"], PP)
    kits, _meta = validate_paginated(resp)
    assert kits[0]["status"] == "CONSUMED"


def test_award_response_and_read_back_are_consistent(api):
    """PRD section 3.2: "On award the contract moves `DRAFT` → `AWARDED`, the
    system stamps `awarded_at` with the current logical time, the contract's
    `version` increments by one, and — crucially — the system creates one
    `OptionOrder` for each entry of `option_specs`: the entry at position zero
    becomes an option order with `option_year` 1, the next `option_year` 2,
    and so on, each created in `AVAILABLE` status with its `quantity` and
    `propulsion_type` copied from the spec and its `exercise_deadline`
    computed as `awarded_at` plus the option year number multiplied by 365
    days."
    PRD section 2.4: "Every persisted resource carries an `id` that is a
    server-minted UUID with no type prefix, a `created_at` timestamp, an
    `updated_at` timestamp, and an integer `version` that increments by one on
    every mutation of the resource."

    Design: Corner/consistency_model/mutation_visible_immediately_in_same_response
    """
    agency = create_agency()
    contract = create_draft_contract(agency["id"], base_quantity=1)
    component = create_component()
    create_frozen_configuration(
        contract["id"], [component["id"]], contract["version"]
    )
    # The successful freeze incremented the contract version (PRD section
    # 2.7), so re-read the pre-award version instead of trusting the stale
    # creation response.
    pre_award_version = get_success_data(
        api.get_contract(contract["id"], PO)
    )["version"]

    resp = api.award_contract(contract["id"], PO)
    awarded = validate_success(resp)
    assert awarded["status"] == "AWARDED"
    assert awarded["version"] == pre_award_version + 1, (
        "award increments the contract version by one"
    )

    resp = api.get_contract(contract["id"], PO)
    reread = validate_success(resp)
    assert reread["status"] == "AWARDED"
    assert reread["version"] == awarded["version"], (
        "no drift between the write response and the immediate read: "
        f"{reread['version']} vs {awarded['version']}"
    )
