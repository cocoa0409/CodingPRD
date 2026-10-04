"""Market partner agreement tests: closed-interval overlap, expiry sweep,
and the two override variants on identical posted data."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_partner,
    create_active_market_group_with_restaurants,
    create_and_activate_agreement,
    create_open_period,
    post_line_item,
    compute_period,
    finalize_period,
    setup_active_contract,
    set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
HR = TEST_USERS["hr_recruiter_headers"]
CONTROLLER = TEST_USERS["corporate_controller_headers"]


def test_agreement_closed_interval_touching_endpoints_collide(api):
    """PRD §3.2: "Second, coverage must be unique: no other agreement in DRAFT
    or ACTIVE for the same market group may have a coverage interval that
    intersects this agreement's interval — intersection is evaluated with both
    intervals treated as closed, inclusive at both ends — or the activation is
    rejected with ERR_OVERRIDE_COVERAGE_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/agreement_closed_interval_touching_endpoints_collide
    """
    set_clock("2026-09-01T00:00:00Z")
    group, _ = create_active_market_group_with_restaurants(num_restaurants=1)
    p2 = create_partner(full_name="Kim Voss", email="kv@x.com", role_in_program="MARKET_PARTNER")
    p3 = create_partner(full_name="Lee Park", email="lp@x.com", role_in_program="MARKET_PARTNER")
    create_and_activate_agreement(
        group["id"],
        partner_id=p2["id"],
        coverage_start_date="2027-01-01",
        coverage_end_date="2027-07-01",
        override_pct=5,
        basis="PER_RESTAURANT_POSITIVE",
    )
    from test_helpers import create_agreement_payload

    # agB touches the ACTIVE agreement's inclusive end date 2027-07-01; agC
    # starts one calendar day later and is disjoint. agB is TERMINATED after
    # its rejection so it no longer participates in coverage-uniqueness when
    # agC activates (the gate only considers DRAFT/ACTIVE agreements).
    agB = validate_success(
        api.create_agreement(
            create_agreement_payload(
                partner_id=p3["id"],
                market_group_id=group["id"],
                coverage_start_date="2027-07-01",
                coverage_end_date="2027-12-31",
                override_pct=4,
                basis="NET_GROUP_BASIS",
            ),
            CONTROLLER,
        ),
        expected_status=201,
    )
    resp_b = api.activate_agreement(agB["id"], CONTROLLER)
    validate_error(resp_b, ApiErrorId.ERR_OVERRIDE_COVERAGE_OVERLAP)
    agB_now = validate_success(api.get_agreement(agB["id"], CONTROLLER))
    assert agB_now["status"] == "DRAFT"
    agB_term = validate_success(api.terminate_agreement(agB["id"], CONTROLLER))
    assert agB_term["status"] == "TERMINATED"

    agC = validate_success(
        api.create_agreement(
            create_agreement_payload(
                partner_id=p3["id"],
                market_group_id=group["id"],
                coverage_start_date="2027-07-02",
                coverage_end_date="2027-12-31",
                override_pct=4,
                basis="NET_GROUP_BASIS",
            ),
            CONTROLLER,
        ),
        expected_status=201,
    )
    agC_now = validate_success(api.activate_agreement(agC["id"], CONTROLLER))
    assert agC_now["status"] == "ACTIVE"


def test_agreement_non_overlapping_intervals_activate(api):
    """PRD §3.2: "Second, coverage must be unique: no other agreement in DRAFT
    or ACTIVE for the same market group may have a coverage interval that
    intersects this agreement's interval — intersection is evaluated with both
    intervals treated as closed, inclusive at both ends — or the activation is
    rejected with ERR_OVERRIDE_COVERAGE_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/agreement_closed_interval_touching_endpoints_collide
    """
    set_clock("2026-09-01T00:00:00Z")
    group, _ = create_active_market_group_with_restaurants(num_restaurants=1)
    p2 = create_partner(full_name="Kim Voss", email="kv@x.com", role_in_program="MARKET_PARTNER")
    p3 = create_partner(full_name="Lee Park", email="lp@x.com", role_in_program="MARKET_PARTNER")
    create_and_activate_agreement(
        group["id"],
        partner_id=p2["id"],
        coverage_start_date="2027-01-01",
        coverage_end_date="2027-06-30",
    )
    from test_helpers import create_agreement_payload

    disjoint = validate_success(
        api.create_agreement(
            create_agreement_payload(
                partner_id=p3["id"],
                market_group_id=group["id"],
                coverage_start_date="2027-07-01",
                coverage_end_date="2027-12-31",
            ),
            CONTROLLER,
        ),
        expected_status=201,
    )
    # Disjoint closed intervals: both may be ACTIVE on the same group.
    activated = validate_success(api.activate_agreement(disjoint["id"], CONTROLLER))
    assert activated["status"] == "ACTIVE"


def test_scheduled_sweep_agreement_expiry(api):
    """PRD §3.2: "The clock sweep moves an `ACTIVE` agreement to `EXPIRED` once
    the logical clock's date passes the `coverage_end_date`."
    PRD §3.2: "The coverage window is a **closed** interval — inclusive at both
    ends — and `coverage_end_date` must be on or after `coverage_start_date`."

    Design: Corner/cross_cutting_layers/scheduled_sweep_agreement_expiry
    """
    set_clock("2026-09-01T00:00:00Z")
    group, _ = create_active_market_group_with_restaurants(num_restaurants=1)
    _, agreement = create_and_activate_agreement(
        group["id"],
        coverage_start_date="2027-01-01",
        coverage_end_date="2027-12-31",
        override_pct=5,
        basis="PER_RESTAURANT_POSITIVE",
    )
    set_clock("2027-12-31T00:00:00Z")
    fetched = validate_success(api.get_agreement(agreement["id"], CONTROLLER))
    assert fetched["status"] == "ACTIVE"
    set_clock("2028-01-01T00:00:00Z")
    fetched = validate_success(api.get_agreement(agreement["id"], CONTROLLER))
    assert fetched["status"] == "EXPIRED"


def _finalize_restaurant_period(api, restaurant_id, start, end, clock_at):
    period = create_open_period(restaurant_id, start, end)
    set_clock(clock_at)
    post_line_item(period["id"], "REVENUE", 9000000, "FINALIZED")
    post_line_item(period["id"], "COST_OF_GOODS", 3000000, "FINALIZED")
    compute_period(period["id"])
    return finalize_period(period["id"])


def test_override_net_group_basis_variant(api):
    """PRD §3.8: "Under NET_GROUP_BASIS, the restaurant's attributable share
    of group profit is the period's final_distributable_profit_cents divided
    by the group restaurant count — the number of restaurants in the group
    whose status is ACTIVE at finalize time — and the override is the
    agreement's override_pct percentage of that attributable share, rounded
    half-up to integer cents and floored at zero."

    Design: Difficulty/dual_variant_calc/override_net_group_basis_vs_per_restaurant_positive
    """
    set_clock("2026-09-01T00:00:00Z")
    group, restaurants = create_active_market_group_with_restaurants(num_restaurants=2)
    setup_active_contract(restaurant_id=restaurants[0]["id"])
    create_and_activate_agreement(
        group["id"],
        coverage_start_date="2027-01-01",
        coverage_end_date="2027-12-31",
        override_pct=5,
        basis="NET_GROUP_BASIS",
    )
    finalized = _finalize_restaurant_period(
        api, restaurants[0]["id"], "2027-02-01", "2027-03-01", "2027-02-15T00:00:00Z"
    )
    assert finalized["final_distributable_profit_cents"] == 6000000
    assert finalized["market_override_cents"] == 150000  # 5% of 6000000/2


def test_override_per_restaurant_positive_variant(api):
    """PRD §3.8: "Under PER_RESTAURANT_POSITIVE, the override is the
    override_pct percentage of this restaurant's own positive profit — the
    final distributable profit floored at zero — rounded half-up. The two
    variants diverge whenever the group has more than one active restaurant or
    the restaurant's profit is negative."

    Design: Difficulty/dual_variant_calc/override_net_group_basis_vs_per_restaurant_positive
    """
    set_clock("2026-09-01T00:00:00Z")
    group, restaurants = create_active_market_group_with_restaurants(num_restaurants=2)
    setup_active_contract(restaurant_id=restaurants[0]["id"])
    create_and_activate_agreement(
        group["id"],
        coverage_start_date="2027-01-01",
        coverage_end_date="2027-12-31",
        override_pct=5,
        basis="PER_RESTAURANT_POSITIVE",
    )
    finalized = _finalize_restaurant_period(
        api, restaurants[0]["id"], "2027-02-01", "2027-03-01", "2027-02-15T00:00:00Z"
    )
    assert finalized["final_distributable_profit_cents"] == 6000000
    assert finalized["market_override_cents"] == 300000  # 5% of max(0, 6000000)
