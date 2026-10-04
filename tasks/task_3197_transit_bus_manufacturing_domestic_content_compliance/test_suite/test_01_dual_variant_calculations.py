"""Depth tests: dual-variant calculations (domestic content, ZEV ratios)."""
from test_helpers import (
    TEST_USERS,
    assert_compliance_certificate,
    award_contract,
    build_bus_to_accepted,
    complete_pre_award_audit,
    create_agency,
    create_bus_configuration_payload,
    create_bus_unit_payload,
    create_certificate_payload,
    create_component,
    create_draft_contract,
    create_frozen_configuration,
    get_success_data,
    setup_active_contract,
    setup_active_contract_with_config,
    validate_success,
)

PO = TEST_USERS["procurement_officer_headers"]
CE = TEST_USERS["config_engineer_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PP = TEST_USERS["production_planner_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _setup_bus_with_kit(api, component_specs, contract_overrides=None,
                        propulsion_type="DIESEL", configuration_overrides=None):
    """ACTIVE contract whose FROZEN configuration carries the given component
    specs, plus one ENGINEERED bus (kit carries the components).

    The configuration is frozen before the contract is activated (PRD section
    3.3 allows submit-review only while the contract is DRAFT or AWARDED).

    Returns (setup, bus, configuration).
    """
    contract_overrides = contract_overrides or {}
    configuration_overrides = configuration_overrides or {}
    components = [create_component(**spec) for spec in component_specs]
    setup = setup_active_contract_with_config(
        contract_overrides=contract_overrides,
        config_components=components,
        propulsion_type=propulsion_type,
        **configuration_overrides,
    )
    cfg = setup["configuration"]
    bus = get_success_data(
        api.create_bus_unit(
            create_bus_unit_payload(setup["contract"]["id"], cfg["id"]), PP
        ),
    )
    bus = get_success_data(api.engineer_bus(bus["id"], CE))
    return setup, bus, cfg


def test_domestic_content_cost_based_variant_percentage(api):
    """PRD section 3.6: "Under `COST_BASED`, the percentage is one hundred
    times the summed `unit_cost_cents` of domestic components divided by the
    summed `unit_cost_cents` of all components on the kit, so an inexpensive
    domestic fastener contributes very little."
    PRD section 2.8: "Percentages that are not money — `domestic_content_pct`,
    `completeness_pct`, and kit completeness — are rounded half-up to one
    decimal place."

    Design: Difficulty/dual_variant_calc/domestic_content_cost_vs_count_variants
    """
    _setup, bus, _cfg = _setup_bus_with_kit(
        api,
        [
            dict(name="Axle", category="AXLE", unit_cost_cents=100000,
                 is_domestic=True),
            dict(name="Motor", category="PROPULSION", unit_cost_cents=200000,
                 is_domestic=False),
            dict(name="Body Panel", category="BODY", unit_cost_cents=300000,
                 is_domestic=True),
            dict(name="Farebox", category="FARE", unit_cost_cents=150000,
                 is_domestic=False),
        ],
        contract_overrides={"base_quantity": 2},
    )

    resp = api.issue_certificate(
        bus["id"], create_certificate_payload(variant="COST_BASED"), CO
    )
    cert = validate_success(resp, expected_status=201)
    assert_compliance_certificate(cert)
    assert cert["domestic_content_pct"] == 53.3, (
        f"COST_BASED pct must be 100*(100000+300000)/750000 = 53.3, "
        f"got {cert['domestic_content_pct']}"
    )


def test_domestic_content_component_count_variant_percentage(api):
    """PRD section 3.6: "Under `COMPONENT_COUNT`, the percentage is one hundred
    times the count of domestic components divided by the total component
    count, weighting every part equally regardless of price; the same
    component set therefore yields a different percentage under the two
    variants whenever unit costs are unequal."

    Design: Difficulty/dual_variant_calc/domestic_content_cost_vs_count_variants
    """
    _setup, bus, _cfg = _setup_bus_with_kit(
        api,
        [
            dict(name="Axle", category="AXLE", unit_cost_cents=100000,
                 is_domestic=True),
            dict(name="Motor", category="PROPULSION", unit_cost_cents=200000,
                 is_domestic=False),
            dict(name="Body Panel", category="BODY", unit_cost_cents=300000,
                 is_domestic=True),
            dict(name="Farebox", category="FARE", unit_cost_cents=150000,
                 is_domestic=False),
        ],
        contract_overrides={"base_quantity": 2},
    )

    resp = api.issue_certificate(
        bus["id"], create_certificate_payload(variant="COMPONENT_COUNT"), CO
    )
    cert = validate_success(resp, expected_status=201)
    assert cert["domestic_content_pct"] == 50.0, (
        f"COMPONENT_COUNT pct must be 100*2/4 = 50.0, "
        f"got {cert['domestic_content_pct']}"
    )
    assert cert["domestic_content_pct"] != 53.3, (
        "the two variants must diverge whenever unit costs are unequal"
    )


def test_zev_ratio_realized_variant_counts_accepted_only(api):
    """PRD section 3.1: "The realized ratio, `zev_ratio`, counts only buses
    the agency has accepted: it is the number of the agency's `ACCEPTED` buses
    whose configuration propulsion is `BEV` or `FCEV`, divided by the total
    number of the agency's `ACCEPTED` buses, and it is 0 when the agency has
    accepted no buses."

    Design: Difficulty/dual_variant_calc/zev_ratio_realized_vs_projected_variants
    """
    agency = create_agency()
    contract = create_draft_contract(
        agency["id"],
        base_quantity=2,
        option_years=1,
        option_specs=[{"quantity": 3, "propulsion_type": "BEV"}],
    )
    component = create_component(name="Engine", category="PROPULSION")
    # Both propulsion variants are frozen before award/activation: PRD
    # section 3.3 allows submit-review only while the contract is DRAFT or
    # AWARDED, and PRD section 3.2 requires a FROZEN configuration whose
    # propulsion_type matches an option order at exercise time.
    bev_cfg = create_frozen_configuration(
        contract["id"], [component["id"]], contract["version"],
        propulsion_type="BEV", seating_layout={"rows": 10},
    )
    dsl_cfg = create_frozen_configuration(
        contract["id"], [component["id"]], contract["version"] + 1,
        propulsion_type="DIESEL", seating_layout={"rows": 12},
    )
    award_contract(contract["id"])
    complete_pre_award_audit(contract["id"], [component["id"]])
    get_success_data(api.activate_contract(contract["id"], PO))

    # Starting production requires the logical clock to be at or after the
    # slot's start_ts (PRD section 3.5); the clock boots at 2026-09-01, so
    # advance it before driving the buses through production.
    get_success_data(
        api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, ADMIN)
    )
    bus_bev = build_bus_to_accepted(
        {"contract": contract, "configuration": bev_cfg},
        slot_overrides={"line_id": "LINE_A",
                        "start_ts": "2026-09-01T00:00:00Z",
                        "end_ts": "2026-09-05T00:00:00Z"},
    )
    # The second bus's slot starts later; advance the logical clock to its
    # start_ts so production may begin (PRD section 3.5).
    get_success_data(
        api.set_clock({"to_iso8601": "2026-09-05T00:00:00Z"}, ADMIN)
    )
    bus_dsl = build_bus_to_accepted(
        {"contract": contract, "configuration": dsl_cfg},
        slot_overrides={"line_id": "LINE_A",
                        "start_ts": "2026-09-05T00:00:00Z",
                        "end_ts": "2026-09-09T00:00:00Z"},
    )
    assert bus_bev["status"] == "ACCEPTED"
    assert bus_dsl["status"] == "ACCEPTED"

    # Exercise the BEV option (quantity 3) to build the projected pipeline.
    from test_helpers import validate_paginated
    resp = api.list_contract_option_orders(contract["id"], PO)
    options, _meta = validate_paginated(resp)
    option = options[0]
    contract = get_success_data(api.get_contract(contract["id"], PO))
    get_success_data(
        api.exercise_option_order(
            option["id"],
            {"expected_contract_version": contract["version"]},
            PO,
        ),
    )

    agency = get_success_data(api.get_agency(agency["id"], ADMIN))
    assert agency["zev_ratio"] == 0.5, (
        f"realized zev_ratio must count ACCEPTED buses only: 1 BEV of 2 "
        f"ACCEPTED = 0.5000, got {agency['zev_ratio']}"
    )


def test_zev_ratio_projected_variant_counts_exercised_pipeline(api):
    """PRD section 3.1: "The forward-looking `projected_zev_ratio` adds the
    exercised-but-undelivered option pipeline to both sides: the numerator
    adds the summed `quantity` of every `EXERCISED` option order across the
    agency's contracts whose `propulsion_type` is `BEV` or `FCEV`, and the
    denominator adds the summed `quantity` of every `EXERCISED` option order
    regardless of propulsion."
    PRD section 3.1: "The realized ratio ignores the pipeline entirely, so the
    same agency at the same instant shows two different numbers whenever an
    option has been exercised but its buses are not yet accepted."

    Design: Difficulty/dual_variant_calc/zev_ratio_realized_vs_projected_variants
    """
    from test_helpers import validate_paginated

    agency = create_agency()
    contract = create_draft_contract(
        agency["id"],
        base_quantity=2,
        option_years=1,
        option_specs=[{"quantity": 3, "propulsion_type": "BEV"}],
    )
    component = create_component(name="Engine", category="PROPULSION")
    # Both propulsion variants are frozen before award/activation: PRD
    # section 3.3 allows submit-review only while the contract is DRAFT or
    # AWARDED, and PRD section 3.2 requires a FROZEN configuration whose
    # propulsion_type matches an option order at exercise time.
    bev_cfg = create_frozen_configuration(
        contract["id"], [component["id"]], contract["version"],
        propulsion_type="BEV", seating_layout={"rows": 10},
    )
    dsl_cfg = create_frozen_configuration(
        contract["id"], [component["id"]], contract["version"] + 1,
        propulsion_type="DIESEL", seating_layout={"rows": 12},
    )
    award_contract(contract["id"])
    complete_pre_award_audit(contract["id"], [component["id"]])
    get_success_data(api.activate_contract(contract["id"], PO))

    # Starting production requires the logical clock to be at or after the
    # slot's start_ts (PRD section 3.5); the clock boots at 2026-09-01, so
    # advance it before driving the buses through production.
    get_success_data(
        api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, ADMIN)
    )
    bus_bev = build_bus_to_accepted(
        {"contract": contract, "configuration": bev_cfg},
        slot_overrides={"line_id": "LINE_A",
                        "start_ts": "2026-09-01T00:00:00Z",
                        "end_ts": "2026-09-05T00:00:00Z"},
    )
    # The second bus's slot starts later; advance the logical clock to its
    # start_ts so production may begin (PRD section 3.5).
    get_success_data(
        api.set_clock({"to_iso8601": "2026-09-05T00:00:00Z"}, ADMIN)
    )
    bus_dsl = build_bus_to_accepted(
        {"contract": contract, "configuration": dsl_cfg},
        slot_overrides={"line_id": "LINE_A",
                        "start_ts": "2026-09-05T00:00:00Z",
                        "end_ts": "2026-09-09T00:00:00Z"},
    )
    assert bus_bev["status"] == "ACCEPTED"
    assert bus_dsl["status"] == "ACCEPTED"

    resp = api.list_contract_option_orders(contract["id"], PO)
    options, _meta = validate_paginated(resp)
    option = options[0]
    contract = get_success_data(api.get_contract(contract["id"], PO))
    get_success_data(
        api.exercise_option_order(
            option["id"],
            {"expected_contract_version": contract["version"]},
            PO,
        ),
    )

    agency = get_success_data(api.get_agency(agency["id"], ADMIN))
    assert agency["projected_zev_ratio"] == 0.8, (
        f"projected zev_ratio must fold the EXERCISED BEV pipeline into both "
        f"sides: (1 + 3) / (2 + 3) = 0.8000, got {agency['projected_zev_ratio']}"
    )
    assert agency["zev_ratio"] != agency["projected_zev_ratio"], (
        "realized ignores the pipeline while projected counts it; the two "
        "variants must diverge while the pipeline is non-empty"
    )
