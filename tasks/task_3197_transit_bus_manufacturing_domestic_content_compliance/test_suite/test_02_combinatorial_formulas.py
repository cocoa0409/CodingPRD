"""Depth tests: combinatorial formulas (option escalation, domestic content
rounding order)."""
from test_helpers import (
    TEST_USERS,
    build_bus_to_built,
    create_bus_configuration_payload,
    create_bus_unit_payload,
    create_certificate_payload,
    create_component,
    get_success_data,
    setup_active_contract,
    validate_paginated,
    validate_success,
)

PO = TEST_USERS["procurement_officer_headers"]
CE = TEST_USERS["config_engineer_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PP = TEST_USERS["production_planner_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _exercise_option(api, contract_id, option_index=0):
    """Fetch the contract's options, re-read the contract version, and
    exercise the option at `option_index`. Returns the exercised OptionOrder."""
    resp = api.list_contract_option_orders(contract_id, PO)
    options, _meta = validate_paginated(resp)
    option = options[option_index]
    contract = get_success_data(api.get_contract(contract_id, PO))
    resp = api.exercise_option_order(
        option["id"],
        {"expected_contract_version": contract["version"]},
        PO,
    )
    return validate_success(resp)


def test_option_escalation_pinned_evaluation_order_year2_tier2pct(api):
    """PRD section 3.2: "The exercise price is computed by the option
    escalation calculation, whose evaluation order is pinned: escalate first,
    apply the volume tier second, round once at the end."
    PRD section 3.2: "The annual escalation factor is 1.031 when the index is
    `PPI_1413` and 1.024 when the index is `CPI_U`, so the same option year
    and quantity yield different unit prices under the two indices."
    PRD section 3.2: "A flat volume discount is then selected from the
    exercised `quantity`: no discount when the quantity is fewer than 5 buses,
    a 2 percent discount when the quantity is at least 5 but fewer than 20,
    and a 5 percent discount when the quantity is 20 or more."

    Design: Difficulty/combinatorial_formula/option_escalation_multi_input_tier_formula
    """
    setup = setup_active_contract(
        contract_overrides={
            "base_quantity": 2,
            "base_unit_price_cents": 50_000_000,
            "escalation_index": "PPI_1413",
            "option_years": 2,
            "option_specs": [
                {"quantity": 4, "propulsion_type": "DIESEL"},
                {"quantity": 10, "propulsion_type": "DIESEL"},
            ],
        }
    )
    option = _exercise_option(api, setup["contract"]["id"], option_index=1)
    assert option["status"] == "EXERCISED"
    # escalate: 50000000 * 1.031**2 = 50000000 * 1.062961 = 53148050
    # tier: quantity 10 -> 2% discount -> 53148050 * 0.98 = 52085089
    assert option["exercised_unit_price_cents"] == 52085089, (
        "escalate-first-then-tier with a single final round_half_up must "
        f"yield 52085089, got {option['exercised_unit_price_cents']}"
    )


def test_option_escalation_index_variant_cpi_u_differs(api):
    """PRD section 3.2: "The annual escalation factor is 1.031 when the index
    is `PPI_1413` and 1.024 when the index is `CPI_U`, so the same option year
    and quantity yield different unit prices under the two indices."

    Design: Difficulty/combinatorial_formula/option_escalation_multi_input_tier_formula
    """
    setup = setup_active_contract(
        contract_overrides={
            "base_quantity": 2,
            "base_unit_price_cents": 50_000_000,
            "escalation_index": "CPI_U",
            "option_years": 2,
            "option_specs": [
                {"quantity": 4, "propulsion_type": "DIESEL"},
                {"quantity": 10, "propulsion_type": "DIESEL"},
            ],
        }
    )
    option = _exercise_option(api, setup["contract"]["id"], option_index=1)
    assert option["status"] == "EXERCISED"
    # escalate: 50000000 * 1.024**2 = 50000000 * 1.048576 = 52428800
    # tier: quantity 10 -> 2% -> 52428800 * 0.98 = 51380224
    assert option["exercised_unit_price_cents"] == 51380224, (
        "CPI_U variant of the same formula must yield 51380224, got "
        f"{option['exercised_unit_price_cents']}"
    )


def test_domestic_content_below_rounding_boundary_stays_below(api):
    """PRD section 2.8: "Rounding is always a single terminal operation within
    each calculation; intermediate values are never pre-rounded."
    PRD section 3.6: "for a federally funded agency the certificate must
    additionally show a `domestic_content_pct` of at least its
    `threshold_pct`, with a shortfall rejected as
    `ERR_DOMESTIC_CONTENT_BELOW_THRESHOLD`."

    Design: Difficulty/combinatorial_formula/domestic_content_boundary_rounding_order
    """
    # Just under the rounding boundary: domestic 6994 / total 10000 = 69.94,
    # which rounds to 69.9, below the 70 default threshold. The configuration
    # carrying these components is frozen *before* activation, because
    # submit-review is allowed only while the contract is DRAFT or AWARDED
    # (PRD section 3.3).
    domestic = create_component(name="Fasteners", category="BODY",
                                unit_cost_cents=6994, is_domestic=True)
    foreign = create_component(name="Engine", category="PROPULSION",
                               unit_cost_cents=3006, is_domestic=False)
    from test_helpers import setup_active_contract_with_config
    setup = setup_active_contract_with_config(
        contract_overrides={"base_quantity": 1},
        config_components=[domestic, foreign],
    )
    cfg = setup["configuration"]
    bus = get_success_data(
        api.create_bus_unit(
            create_bus_unit_payload(setup["contract"]["id"], cfg["id"]), PP
        ),
    )
    bus = get_success_data(api.engineer_bus(bus["id"], CE))
    from test_helpers import (
        ApiErrorId,
        create_and_assign_slot,
        validate_error,
    )
    # Both components were verified by the pre-award audit, so the kit
    # completed at engineering time.
    slot = create_and_assign_slot(
        bus["id"], line_id="LINE_B",
        start_ts="2026-09-01T00:00:00Z", end_ts="2026-09-03T00:00:00Z",
    )
    get_success_data(api.start_production(slot["id"], PP))
    get_success_data(api.complete_production(slot["id"], PP))

    resp = api.issue_certificate(
        bus["id"], create_certificate_payload(variant="COST_BASED"), CO
    )
    cert = validate_success(resp, expected_status=201)
    assert cert["domestic_content_pct"] == 69.9, (
        "69.94 rounds half-up once to 69.9, got "
        f"{cert['domestic_content_pct']}"
    )
    # 69.9 < 70: the plant-inspection gate must reject the shortfall.
    resp = api.submit_plant_inspection(bus["id"], PP)
    validate_error(resp, ApiErrorId.ERR_DOMESTIC_CONTENT_BELOW_THRESHOLD)
