"""Depth tests: transitive cascades (supplier-doc -> kit -> slot; contract
termination fan-out)."""
from test_helpers import (
    TEST_USERS,
    create_and_assign_slot,
    create_engineered_bus,
    get_success_data,
    make_compliance_officer_headers,
    make_supplier_rep_headers,
    setup_active_contract,
    validate_paginated,
    validate_success,
)

PO = TEST_USERS["procurement_officer_headers"]
CE = TEST_USERS["config_engineer_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PP = TEST_USERS["production_planner_headers"]


def test_final_verify_cascades_component_to_kit_to_slot(api):
    """PRD section 3.4: "When a kit in `STAGING` reaches a completeness of
    100.0 — meaning every required component is verified — the system
    auto-transitions the kit from `STAGING` to `COMPLETE`, and if the kit's
    bus is already assigned to a production slot, that slot's `kit_status`
    flips from `NOT_KITTED` to `KITTED` at the same moment."

    Design: Difficulty/transitive_cascade/supplier_doc_verify_kit_slot_production_cascade
    """
    # The two-component configuration is frozen before activation (PRD section
    # 3.3 allows submit-review only while the contract is DRAFT or AWARDED);
    # the extra AXLE component is not PROPULSION, so the pre-award audit still
    # completes while it stays undocumented.
    first = get_success_data(
        api.create_component(
            {"name": "Engine", "category": "PROPULSION",
             "unit_cost_cents": 800000, "is_domestic": True},
            CO,
        ),
    )
    extra = get_success_data(
        api.create_component(
            {"name": "Axle", "category": "AXLE", "unit_cost_cents": 300000,
             "is_domestic": True},
            CO,
        ),
    )
    # The pre-award audit needs the configuration's PROPULSION components
    # VERIFIED; the AXLE component must stay undocumented so the kit stays
    # incomplete.
    from test_helpers import setup_active_contract_with_config, submit_and_verify_component
    submit_and_verify_component(first["id"])
    setup = setup_active_contract_with_config(
        contract_overrides={"base_quantity": 1},
        config_components=[first, extra],
        verify_components=False,
    )
    bus = create_engineered_bus(
        setup["contract"]["id"], setup["configuration"]["id"]
    )
    slot = create_and_assign_slot(bus["id"])
    assert slot["kit_status"] == "NOT_KITTED", (
        "kit is incomplete while the second component is undocumented; slot "
        f"must be NOT_KITTED, got {slot['kit_status']}"
    )

    # The final verification triggers the whole cascade.
    get_success_data(
        api.submit_supplier_docs(extra["id"], make_supplier_rep_headers("sup-1")),
    )
    resp = api.verify_docs(extra["id"], make_compliance_officer_headers("co-1"))
    validate_success(resp)

    resp = api.list_bus_parts_kits(bus["id"], PP)
    kits, _meta = validate_paginated(resp)
    assert len(kits) == 1
    assert kits[0]["completeness_pct"] == 100.0
    assert kits[0]["status"] == "COMPLETE", (
        f"kit must auto-complete at 100.0 completeness, got {kits[0]['status']}"
    )
    slot = get_success_data(api.get_production_slot(slot["id"], PP))
    assert slot["kit_status"] == "KITTED", (
        "the ASSIGNED slot's kit_status must flip NOT_KITTED -> KITTED at the "
        f"same moment the kit completes, got {slot['kit_status']}"
    )


def test_completed_kit_unblocks_production_start(api):
    """PRD section 3.5: "A successful start fires three cascades at once: the
    bus moves `ENGINEERED` → `IN_PRODUCTION`, the linked parts kit moves
    `COMPLETE` → `CONSUMED`, and for every component in the kit, the parts
    stock row keyed by the contract's agency and that component — if such a
    row exists — has its `quantity` decremented by one."

    Design: Difficulty/transitive_cascade/supplier_doc_verify_kit_slot_production_cascade
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    bus = create_engineered_bus(
        setup["contract"]["id"], setup["configuration"]["id"]
    )
    slot = create_and_assign_slot(bus["id"])
    # The kit's single component was verified during the pre-award audit, so
    # the kit auto-completed at engineer time and the slot was KITTED on assign.
    assert slot["kit_status"] == "KITTED"

    resp = api.start_production(slot["id"], PP)
    slot = validate_success(resp)
    assert slot["status"] == "IN_PRODUCTION"

    bus = get_success_data(api.get_bus_unit(bus["id"], PP))
    assert bus["status"] == "IN_PRODUCTION", (
        f"start cascades bus ENGINEERED -> IN_PRODUCTION, got {bus['status']}"
    )
    resp = api.list_bus_parts_kits(bus["id"], PP)
    kits, _meta = validate_paginated(resp)
    assert kits[0]["status"] == "CONSUMED", (
        f"start cascades kit COMPLETE -> CONSUMED, got {kits[0]['status']}"
    )


def test_terminate_cascades_to_options_buses_slots_and_kits(api):
    """PRD section 3.2: "Terminating an active contract cascades: every option
    order still `AVAILABLE` moves to `EXPIRED`, every bus unit in `ORDERED` or
    `ENGINEERED` moves to `REJECTED`, every production slot referencing those
    buses moves to `CANCELLED` with its `kit_status` reset to `NOT_KITTED`,
    and every linked parts kit in `STAGING` or `COMPLETE` moves to
    `CONSUMED` — releasing no stock, since consumption through termination
    does not decrement parts inventory."

    Design: Difficulty/transitive_cascade/contract_terminate_option_bus_slot_cascade
    """
    setup = setup_active_contract(
        contract_overrides={
            "base_quantity": 2,
            "option_years": 1,
            "option_specs": [{"quantity": 5, "propulsion_type": "DIESEL"}],
        }
    )
    bus = create_engineered_bus(
        setup["contract"]["id"], setup["configuration"]["id"]
    )
    slot = create_and_assign_slot(
        bus["id"], line_id="LINE_B",
        start_ts="2026-09-02T00:00:00Z", end_ts="2026-09-06T00:00:00Z",
    )

    resp = api.terminate_contract(setup["contract"]["id"], PO)
    terminated = validate_success(resp)
    assert terminated["status"] == "TERMINATED"

    resp = api.list_contract_option_orders(setup["contract"]["id"], PO)
    options, _meta = validate_paginated(resp)
    assert options[0]["status"] == "EXPIRED", (
        f"AVAILABLE option must cascade to EXPIRED, got {options[0]['status']}"
    )
    bus = get_success_data(api.get_bus_unit(bus["id"], PP))
    assert bus["status"] == "REJECTED", (
        f"ENGINEERED bus must cascade to REJECTED, got {bus['status']}"
    )
    slot = get_success_data(api.get_production_slot(slot["id"], PP))
    assert slot["status"] == "CANCELLED", (
        f"ASSIGNED slot must cascade to CANCELLED, got {slot['status']}"
    )
    resp = api.list_bus_parts_kits(bus["id"], PP)
    kits, _meta = validate_paginated(resp)
    assert kits[0]["status"] == "CONSUMED", (
        f"STAGING kit must cascade to CONSUMED, got {kits[0]['status']}"
    )


def test_terminate_from_draft_is_unconditional(api):
    """PRD section 3.2: "Alternatively, a `ProcurementOfficer` may terminate a
    contract: from `DRAFT` termination is unconditional, but from `ACTIVE` it
    is permitted only when no bus unit of the contract is in `IN_PRODUCTION`,
    `PLANT_INSPECTION`, or `IN_TRANSIT`."

    Design: Difficulty/transitive_cascade/contract_terminate_option_bus_slot_cascade
    """
    agency = get_success_data(
        api.create_agency(
            {"name": "Draft Term Transit", "agency_code": "DTT9",
             "transition_target_year": 2035},
            TEST_USERS["platform_admin_headers"],
        ),
    )
    from test_helpers import create_draft_contract
    contract = create_draft_contract(agency["id"])
    assert contract["status"] == "DRAFT"

    resp = api.terminate_contract(contract["id"], PO)
    terminated = validate_success(resp)
    assert terminated["status"] == "TERMINATED"
