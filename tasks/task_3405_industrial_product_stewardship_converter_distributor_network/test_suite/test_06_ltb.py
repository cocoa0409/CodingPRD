"""Last-time-buy window, pool accounting, and LTB priority pairs (PRD §2.8, §3.6)."""
from test_helpers import (
    ApiErrorId,
    clearance_payload,
    create_agreement,
    create_distributor,
    create_jurisdiction,
    decide_clearance,
    discontinue_formulation,
    get_formulation,
    get_order,
    make_distributor_headers,
    order_payload,
    place_order,
    set_clock,
    setup_active_formulation,
    submit_clearance,
    advance_order,
    cancel_order,
    TEST_USERS,
    validate_error,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
CM = TEST_USERS["channel_manager_headers"]


def _setup_ltb_formulation(api, pool=1000):
    """ACTIVE formulation discontinued with the recipe LTB window, plus a
    distributor STANDARD agreement whose window covers December."""
    ctx = setup_active_formulation()
    dist = create_distributor()
    ag = create_agreement(ctx["formulation"]["id"], ctx["jurisdiction"]["id"],
                          distributor_id=dist["id"], tier="STANDARD",
                          base_price_cents=10000,
                          effective_from="2026-10-01T00:00:00Z",
                          effective_to="2027-06-01T00:00:00Z")
    discontinue_formulation(ctx["formulation"]["id"],
                            last_time_buy_deadline="2027-01-15T00:00:00Z",
                            last_ship_date="2027-03-01T00:00:00Z",
                            ltb_pool_quantity=pool)
    return ctx, dist, ag


def test_ltb_order_accepted_at_exact_deadline(api):
    """PRD §2.8: "Orders on a discontinued formulation are accepted while the
    logical clock is at or before `ltb_deadline`, and the order's
    `requested_ship_date` must be at or before `last_ship_date`."

    Design: Difficulty/boundary_precision_check/ltb_deadline_inclusive_at_exact_deadline
    """
    ctx, dist, ag = _setup_ltb_formulation(api)
    set_clock("2027-01-15T00:00:00Z")
    order = place_order(ag["id"], 10, distributor_id=dist["id"],
                        requested_ship_date="2027-02-01T00:00:00Z")
    assert order["is_ltb_order"] is True
    assert order["fulfillment_status"] == "PENDING"


def test_ltb_order_rejected_one_second_after_deadline(api):
    """PRD §3.6: "If the formulation is `DISCONTINUED`, the last-time-buy window
    governs: the clock must be at or before the formulation's `ltb_deadline`,
    and the `requested_ship_date` must be at or before its `last_ship_date`,
    else `ERR_LTB_WINDOW_CLOSED` (409)."

    Design: Difficulty/boundary_precision_check/ltb_deadline_inclusive_at_exact_deadline
    """
    ctx, dist, ag = _setup_ltb_formulation(api)
    set_clock("2027-01-15T00:00:01Z")
    resp = api.create_order(
        order_payload(ag["id"], quantity=10, requested_ship_date="2027-02-01T00:00:00Z",
                      expected_price_agreement_version=ag["version"],
                      distributor_id=dist["id"]),
        make_distributor_headers(dist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LTB_WINDOW_CLOSED)


def test_ltb_pool_exhaustion_blocks_over_allocation(api):
    """PRD §3.6: "for a last-time-buy order the formulation's
    `ltb_pool_remaining` must be at least the order's `quantity`, else
    `ERR_LTB_POOL_EXHAUSTED` (409); a successful allocation moves fulfillment to
    `ALLOCATED` and draws `quantity` units out of `ltb_pool_remaining`."

    Design: Difficulty/compensating_invariant/ltb_pool_allocate_cancel_conserves_units
    """
    ctx, dist, ag = _setup_ltb_formulation(api, pool=1000)
    set_clock("2026-12-01T00:00:00Z")
    o1 = place_order(ag["id"], 400, distributor_id=dist["id"],
                     requested_ship_date="2027-02-01T00:00:00Z")
    o2 = place_order(ag["id"], 600, distributor_id=dist["id"],
                     requested_ship_date="2027-02-01T00:00:00Z")
    o3 = place_order(ag["id"], 401, distributor_id=dist["id"],
                     requested_ship_date="2027-02-01T00:00:00Z")
    advance_order(o1["id"], distributor_id=dist["id"])
    advance_order(o2["id"], distributor_id=dist["id"])
    pool = get_formulation(ctx["formulation"]["id"])["ltb_pool_remaining"]
    assert pool == 0, "1000 - (400 + 600)"
    resp = api.advance_order(o3["id"], make_distributor_headers(dist["id"]))
    validate_error(resp, ApiErrorId.ERR_LTB_POOL_EXHAUSTED)
    assert get_order(o3["id"])["fulfillment_status"] == "PENDING"


def test_ltb_pool_cancel_releases_units_for_reuse(api):
    """PRD §3.6: "Cancelling an `ALLOCATED` order additionally compensates the
    pool: when the order is a last-time-buy order, its `quantity` is returned to
    the formulation's `ltb_pool_remaining`, preserving the invariant that the
    remaining pool always equals `ltb_pool_quantity` minus the quantities of
    orders still `ALLOCATED` or `SHIPPED`."

    Design: Difficulty/compensating_invariant/ltb_pool_allocate_cancel_conserves_units
    """
    ctx, dist, ag = _setup_ltb_formulation(api, pool=1000)
    set_clock("2026-12-01T00:00:00Z")
    o1 = place_order(ag["id"], 400, distributor_id=dist["id"],
                     requested_ship_date="2027-02-01T00:00:00Z")
    o2 = place_order(ag["id"], 600, distributor_id=dist["id"],
                     requested_ship_date="2027-02-01T00:00:00Z")
    o4 = place_order(ag["id"], 400, distributor_id=dist["id"],
                     requested_ship_date="2027-02-01T00:00:00Z")
    advance_order(o1["id"], distributor_id=dist["id"])
    advance_order(o2["id"], distributor_id=dist["id"])
    assert get_formulation(ctx["formulation"]["id"])["ltb_pool_remaining"] == 0
    cancel_order(o1["id"], distributor_id=dist["id"])
    assert get_formulation(ctx["formulation"]["id"])["ltb_pool_remaining"] == 400
    advance_order(o4["id"], distributor_id=dist["id"])
    assert get_formulation(ctx["formulation"]["id"])["ltb_pool_remaining"] == 0, (
        "invariant held at every probe: 1000 - (600 + 400)"
    )


def _setup_discontinued_with_us_agreement(api):
    """Formulation ACTIVE via DE, then DISCONTINUED (deadline 2027-01-15); a
    distributor agreement in US — a jurisdiction with no clearance for the pair;
    clock advanced one day past the deadline."""
    ctx = setup_active_formulation()
    jur_us = create_jurisdiction(code="US", name="United States",
                                 declaration_threshold_ppm=500,
                                 full_disclosure_threshold_ppm=5000)
    discontinue_formulation(ctx["formulation"]["id"],
                            last_time_buy_deadline="2027-01-15T00:00:00Z",
                            last_ship_date="2027-03-01T00:00:00Z",
                            ltb_pool_quantity=100)
    dist = create_distributor()
    ag_us = create_agreement(ctx["formulation"]["id"], jur_us["id"],
                             distributor_id=dist["id"], tier="STANDARD",
                             base_price_cents=5000,
                             effective_from="2026-10-01T00:00:00Z",
                             effective_to="2027-06-01T00:00:00Z")
    set_clock("2027-01-16T00:00:00Z")
    return ctx, jur_us, dist, ag_us


def test_missing_clearance_masks_closed_ltb_window(api):
    """PRD §2.9: "Every write request passes through a single ordered gauntlet
    of checks; when several checks would fail, the one with the lowest priority
    number wins and determines the error returned." — "cleared-clearance
    presence at order creation (11, `ERR_CLEARANCE_NOT_CLEARED`)" precedes "the
    last-time-buy window at order creation (14, `ERR_LTB_WINDOW_CLOSED`)".

    Design: Difficulty/priority_pair_validation_conflict/missing_clearance_beats_closed_ltb_window
    """
    ctx, jur_us, dist, ag_us = _setup_discontinued_with_us_agreement(api)
    resp = api.create_order(
        order_payload(ag_us["id"], quantity=5, requested_ship_date="2027-02-01T00:00:00Z",
                      expected_price_agreement_version=ag_us["version"],
                      distributor_id=dist["id"]),
        make_distributor_headers(dist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CLEARANCE_NOT_CLEARED)


def test_cleared_clearance_unmasks_closed_ltb_window(api):
    """PRD §3.6: "A `CLEARED` clearance must exist for the pair of the
    agreement's formulation and the agreement's jurisdiction, else
    `ERR_CLEARANCE_NOT_CLEARED` (409)." and "If the formulation is
    `DISCONTINUED`, the last-time-buy window governs: the clock must be at or
    before the formulation's `ltb_deadline`, and the `requested_ship_date` must
    be at or before its `last_ship_date`, else `ERR_LTB_WINDOW_CLOSED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/missing_clearance_beats_closed_ltb_window
    """
    ctx, jur_us, dist, ag_us = _setup_discontinued_with_us_agreement(api)
    headers = make_distributor_headers(dist["id"])
    blocked = api.create_order(
        order_payload(ag_us["id"], quantity=5, requested_ship_date="2027-02-01T00:00:00Z",
                      expected_price_agreement_version=ag_us["version"],
                      distributor_id=dist["id"]),
        headers,
    )
    validate_error(blocked, ApiErrorId.ERR_CLEARANCE_NOT_CLEARED)
    cl_us = submit_clearance(ctx["formulation"]["id"], jur_us["id"], "EXEMPT")
    decide_clearance(cl_us["id"], "CLEARED", decider="rm-1")
    retry = api.create_order(
        order_payload(ag_us["id"], quantity=5, requested_ship_date="2027-02-01T00:00:00Z",
                      expected_price_agreement_version=ag_us["version"],
                      distributor_id=dist["id"]),
        headers,
    )
    validate_error(retry, ApiErrorId.ERR_LTB_WINDOW_CLOSED)
