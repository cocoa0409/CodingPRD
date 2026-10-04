"""Corner tests: calculation claims (option tier boundary, certificate
threshold default, kit completeness input set, warranty age tier boundary)."""
from test_helpers import (
    TEST_USERS,
    award_contract,
    build_bus_to_accepted,
    complete_pre_award_audit,
    create_agency,
    create_bus_configuration_payload,
    create_bus_unit_payload,
    create_certificate_payload,
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
    submit_and_verify_component,
    validate_paginated,
    validate_success,
)

PO = TEST_USERS["procurement_officer_headers"]
CE = TEST_USERS["config_engineer_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PP = TEST_USERS["production_planner_headers"]
WA = TEST_USERS["warranty_admin_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _active_contract_with_option(api, quantity):
    """ACTIVE contract (PPI_1413, base 50000000) with one option year of the
    given quantity. Returns (setup, option_id)."""
    setup = setup_active_contract(
        contract_overrides={
            "base_quantity": 1,
            "option_years": 1,
            "option_specs": [{"quantity": quantity, "propulsion_type": "DIESEL"}],
        }
    )
    resp = api.list_contract_option_orders(setup["contract"]["id"], PO)
    options, _meta = validate_paginated(resp)
    return setup, options[0]["id"]


def _exercise(api, setup, option_id):
    contract = get_success_data(
        api.get_contract(setup["contract"]["id"], PO)
    )
    resp = api.exercise_option_order(
        option_id, {"expected_contract_version": contract["version"]}, PO
    )
    return validate_success(resp)


def test_option_escalation_below_tier1_quantity(api):
    """PRD section 3.2: "A flat volume discount is then selected from the
    exercised `quantity`: no discount when the quantity is fewer than 5 buses,
    a 2 percent discount when the quantity is at least 5 but fewer than 20,
    and a 5 percent discount when the quantity is 20 or more."

    Design: Corner/calculations/option_escalation_tier_boundary_qty4_vs_qty5
    """
    setup, option_id = _active_contract_with_option(api, quantity=4)
    option = _exercise(api, setup, option_id)
    # 50000000 * 1.031**1 = 51550000, no discount at quantity 4.
    assert option["exercised_unit_price_cents"] == 51550000


def test_option_escalation_at_tier1_quantity(api):
    """PRD section 3.2: "A flat volume discount is then selected from the
    exercised `quantity`: no discount when the quantity is fewer than 5 buses,
    a 2 percent discount when the quantity is at least 5 but fewer than 20,
    and a 5 percent discount when the quantity is 20 or more."

    Design: Corner/calculations/option_escalation_tier_boundary_qty4_vs_qty5
    """
    setup, option_id = _active_contract_with_option(api, quantity=5)
    option = _exercise(api, setup, option_id)
    # 51550000 * 0.98 = 50519000 at quantity 5 (tier boundary inclusive).
    assert option["exercised_unit_price_cents"] == 50519000


def test_certificate_threshold_defaults_to_70(api):
    """PRD section 3.6: "A `ComplianceOfficer` issues a certificate for a bus
    in `ENGINEERED`, `IN_PRODUCTION`, or `BUILT` status, supplying the
    certificate's `variant` — exactly one of `COST_BASED` or
    `COMPONENT_COUNT` — the `issued_by` user id of the issuing officer, and
    optionally a `threshold_pct`, which defaults to 70 when not supplied."

    Design: Corner/calculations/domestic_content_constants_threshold_default
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    bus = create_engineered_bus(
        setup["contract"]["id"], setup["configuration"]["id"]
    )
    resp = api.issue_certificate(
        bus["id"], create_certificate_payload(variant="COST_BASED"), CO
    )
    cert = validate_success(resp, expected_status=201)
    assert cert["threshold_pct"] == 70
    # The single kit component is domestic, so COST_BASED yields 100.0.
    assert cert["domestic_content_pct"] == 100.0


def test_kit_completeness_counts_verified_only(api):
    """PRD section 3.4: "A parts kit's `completeness_pct` is the percentage of
    its required `component_ids` whose component currently has
    `supplier_doc_status` equal to `VERIFIED`: one hundred times the count of
    verified required components divided by the total count of required
    components, rounded half-up to one decimal place, and defined as 100.0
    when the kit's component list is empty."

    Design: Corner/calculations/kit_completeness_partial_and_input_set
    """
    # The two-component configuration is frozen before activation (PRD section
    # 3.3 allows submit-review only while the contract is DRAFT or AWARDED);
    # the extra AXLE component is not PROPULSION, so the pre-award audit still
    # completes while it stays undocumented.
    first = create_component(name="Engine", category="PROPULSION")
    extra = create_component(name="Axle", category="AXLE",
                             unit_cost_cents=300000, is_domestic=True)
    from test_helpers import setup_active_contract_with_config
    submit_and_verify_component(first["id"])
    setup = setup_active_contract_with_config(
        contract_overrides={"base_quantity": 1},
        config_components=[first, extra],
        verify_components=False,
    )
    cfg = setup["configuration"]
    bus = create_engineered_bus(setup["contract"]["id"], cfg["id"])
    # Submit but do not verify the second component: SUBMITTED does not count.
    from test_helpers import make_supplier_rep_headers
    get_success_data(
        api.submit_supplier_docs(extra["id"], make_supplier_rep_headers("sup-1")),
    )

    resp = api.list_bus_parts_kits(bus["id"], PP)
    kits, _meta = validate_paginated(resp)
    assert len(kits) == 1
    assert kits[0]["completeness_pct"] == 50.0, (
        "one VERIFIED of two required components must compute 50.0, got "
        f"{kits[0]['completeness_pct']}"
    )
    assert kits[0]["status"] == "STAGING"


def test_warranty_tier_boundary_day180_full_coverage(api):
    """PRD section 3.9: "The calculation first determines the bus's fleet-age
    tier from the number of days between the bus's `delivered_at` and the
    decision date: a bus whose age is at most 180 days is covered in full, a
    bus whose age is more than 180 days but at most 365 days is covered at
    half, and a bus older than 365 days has no coverage. The boundary is
    inclusive at the tier edge: exactly 180 days still earns full coverage,
    and the 181st day drops to half."

    Design: Corner/calculations/warranty_approval_age_tier_boundary
    """
    setup = setup_accepted_bus(
        component_overrides={"unit_cost_cents": 50000},
    )
    component = setup["components"][0]
    get_success_data(
        api.create_parts_stock(
            create_parts_stock_payload(
                setup["agency"]["id"], component["id"], quantity=50
            ),
            WA,
        ),
    )
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            setup["bus"]["id"], component["id"], defect_code="ALT_A",
            claimed_amount_cents=200000,
        ),
        WA,
    )
    claim = get_success_data(resp)
    # Delivered at the epoch 2026-09-01; decide at day 180 = 2027-02-28.
    get_success_data(
        api.set_clock({"to_iso8601": "2027-02-28T00:00:00Z"}, ADMIN),
    )
    wa1 = make_warranty_admin_headers("wa-1")
    get_success_data(api.start_review_claim(claim["id"], wa1))
    resp = api.approve_claim(claim["id"], wa1)
    claim = validate_success(resp)
    assert claim["approved_amount_cents"] == 200000, (
        "age exactly 180 days earns full coverage; got "
        f"{claim['approved_amount_cents']}"
    )


def test_warranty_tier_boundary_day181_half_coverage(api):
    """PRD section 3.9: "The boundary is inclusive at the tier edge: exactly
    180 days still earns full coverage, and the 181st day drops to half."

    Design: Corner/calculations/warranty_approval_age_tier_boundary
    """
    setup = setup_accepted_bus(
        component_overrides={"unit_cost_cents": 50000},
    )
    component = setup["components"][0]
    get_success_data(
        api.create_parts_stock(
            create_parts_stock_payload(
                setup["agency"]["id"], component["id"], quantity=50
            ),
            WA,
        ),
    )
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            setup["bus"]["id"], component["id"], defect_code="ALT_B",
            claimed_amount_cents=200000,
        ),
        WA,
    )
    claim = get_success_data(resp)
    # Day 181 after the epoch delivery.
    get_success_data(
        api.set_clock({"to_iso8601": "2027-03-01T00:00:00Z"}, ADMIN),
    )
    wa1 = make_warranty_admin_headers("wa-1")
    get_success_data(api.start_review_claim(claim["id"], wa1))
    resp = api.approve_claim(claim["id"], wa1)
    claim = validate_success(resp)
    assert claim["approved_amount_cents"] == 100000, (
        "age 181 days drops coverage to half; got "
        f"{claim['approved_amount_cents']}"
    )
