"""Numeric rules: the carton rounding waterfall, allocation hold-back, boundaries."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_site_coordinator_headers,
    make_product,
    make_program,
    make_site,
    make_batch,
    register_carton,
    release_batch,
    certify_site,
    open_window,
    setup_entitled_site,
    submit_order,
    anchor_delivered_carton,
    get_entitlement,
    get_order,
    current_window_version_for_order,
)


def _accept(order_id, window_version, cartons):
    return api_client.accept_site_order(
        order_id,
        {"accepted_cartons": cartons, "deliver_at": "2026-09-01T06:00:00Z",
         "expected_allocation_window_version": window_version},
        TEST_USERS["distribution_planner_headers"])


def test_additive_seven_bucket_waterfall_produces_the_carton_need(api):
    """PRD §3.3: "The seven contributions are summed, and that sum is divided by the
    carton's `doses_per_carton` and rounded up to a whole carton by an exact integer
    ceiling division that never uses floating point; the result is the order's
    `rounded_from_doses`, the cartons implied by the dose requirement before any
    uplift."

    PRD §3.3: "The governing minimum is the larger of the program's
    `min_order_cartons` and the presentation's `min_order_cartons`, and the order's
    `min_order_shortfall_cartons` is the amount by which `rounded_from_doses` falls
    short of that governing minimum".

    Design: Difficulty/combinatorial_formula/additive_seven_bucket_waterfall_carton_need
    """
    ctx = setup_entitled_site()
    order = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                         requested_cartons=2, requested_doses=1000)

    res = _accept(order["id"], current_window_version_for_order(order["id"]), 2)
    accepted = validate_success(res, 200)
    assert accepted["rounded_from_doses"] == 1, "the seven buckets sum to 390 doses"
    assert accepted["min_order_shortfall_cartons"] == 1
    assert accepted["accepted_cartons"] == 2
    assert accepted["accepted_doses"] == 2340
    assert accepted["materialization_variance_doses"] == 1340
    assert get_entitlement(ctx["entitlement"]["id"])["available_cartons"] == 8


def test_waterfall_truncation_is_not_a_plain_ceiling_of_the_dose_need(api):
    """PRD §3.3: "Every division truncates to a whole number. No bucket has a floor,
    so a later bucket may receive less than its nominal ceiling while the earlier
    buckets keep their full allocation".

    PRD §3.3: "Bucket one contributes four cartons for each complete group of forty
    doses in `requested_doses`."

    Design: Difficulty/combinatorial_formula/additive_seven_bucket_waterfall_carton_need
    """
    ctx = setup_entitled_site()
    order = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                         requested_cartons=3, requested_doses=3000)

    res = _accept(order["id"], current_window_version_for_order(order["id"]), 3)
    accepted = validate_success(res, 200)
    # The seven buckets sum to 1692 doses, which rounds up to 2 cartons, not the
    # 3 cartons a plain ceiling of 3000 / 1170 would give.
    assert accepted["rounded_from_doses"] == 2
    assert accepted["min_order_shortfall_cartons"] == 0
    assert accepted["accepted_cartons"] == 3
    assert accepted["accepted_doses"] == 3510
    assert accepted["materialization_variance_doses"] == 510


def test_holdback_rounding_and_pack_ceiling_on_rejection(api):
    """PRD §3.2: "The reservable amount is the rate multiplied by
    `reservable_carton_pct`, and the rule is: when that product is an exact whole
    number it is rounded down to itself, while any fractional product is rounded up.
    So a reservable percentage of one half applied to a rate of five gives two and a
    half, which rounds up to three, whereas the same percentage applied to a rate of
    four gives exactly two, which stays two."

    PRD §3.2: "For every program in segment 0, `computed_cartons` is the rate minus
    the reservable amount."

    Design: Difficulty/combinatorial_formula/holdback_rounding_and_pack_ceiling_on_rejection
    """
    ctx = setup_entitled_site()
    assert ctx["entitlement"]["computed_cartons"] == 10

    oh_program = make_program(jurisdiction_code="OH", regulatory_body="Ohio Department of Health",
                              fixed_weekly_cartons=5, weekly_allocation_cap_cartons=5,
                              segment_rule="STOP", adjudication_sla_hours=24,
                              quarantine_on_review=False)
    _, ents_oh = open_window(ctx["batch"]["id"], oh_program["id"])
    assert ents_oh[0]["computed_cartons"] == 2, "5 * 0.5 = 2.5 rounds up to 3, so 5 - 3 = 2"

    order = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                         requested_cartons=3, requested_doses=1000)
    first = _accept(order["id"], current_window_version_for_order(order["id"]), 3)
    assert first.status_code < 400, first.text

    second = _accept(order["id"], current_window_version_for_order(order["id"]), 1)
    accepted = validate_success(second, 200)
    assert accepted["accepted_cartons"] == 1
    assert accepted["rejected_cartons"] == 2
    assert get_entitlement(ctx["entitlement"]["id"])["available_cartons"] == 7


def test_zero_dose_order_uses_the_carton_only_variant(api):
    """PRD §3.3: "When `requested_doses` is zero but `requested_cartons` is at least
    one, the clinic has ordered in cartons and declared no dose requirement:
    `rounded_from_doses` stays zero, `min_order_shortfall_cartons` becomes the
    governing minimum itself".

    Design: Difficulty/boundary_precision_check/zero_dose_order_uses_the_carton_only_variant
    """
    ctx = setup_entitled_site()
    order = submit_order(ctx["entitlement"]["id"], ctx["site"]["id"],
                         requested_cartons=1, requested_doses=0)
    assert get_order(order["id"])["rounded_from_doses"] == 0

    res = _accept(order["id"], current_window_version_for_order(order["id"]), 2)
    accepted = validate_success(res, 200)
    assert accepted["min_order_shortfall_cartons"] == 2
    assert accepted["accepted_cartons"] == 2
    assert accepted["accepted_doses"] == 2340
    assert accepted["materialization_variance_doses"] == 2340


def test_destination_capacity_exact_boundary_is_inclusive(api):
    """PRD §3.3: "that the site's capacity at the requested `deliver_at` can hold the
    accepted cartons for the required entry type (otherwise
    `ERR_SITE_CAPACITY_INSUFFICIENT`)".

    PRD §3.3: "the carton capacity of each equipment class it owns, in
    `ultra_cold_capacity_cartons` and `refrigerated_capacity_cartons`".

    Design: Difficulty/boundary_precision_check/destination_capacity_exact_boundary_is_inclusive
    """
    ctx = setup_entitled_site()
    small = make_site(ctx["program"]["id"], site_code="MI-RIV-02",
                      site_name="Riverside Field Unit", ultra_cold_capacity_cartons=1,
                      refrigerated_capacity_cartons=1, expected_weekly_doses=600)
    certify_site(small["id"], certificate_number="CERT-MI-0002")

    order = submit_order(ctx["entitlement"]["id"], small["id"],
                         requested_cartons=1, requested_doses=0)
    at_ceiling = _accept(order["id"], current_window_version_for_order(order["id"]), 1)
    assert at_ceiling.status_code < 400, at_ceiling.text
    assert get_success_data(at_ceiling)["accepted_cartons"] == 1

    order2 = submit_order(ctx["entitlement"]["id"], small["id"],
                          requested_cartons=1, requested_doses=0)
    over = _accept(order2["id"], current_window_version_for_order(order2["id"]), 1)
    validate_error(over, "ERR_SITE_CAPACITY_INSUFFICIENT", expected_status=422)

    site_after = get_success_data(api.get_storage_site(
        small["id"], TEST_USERS["distribution_planner_headers"]))
    assert site_after["ultra_cold_capacity_cartons"] == 1
    assert site_after["inventory_status"] == "OPEN"


def test_wastage_rate_and_standing_tier_precision(api):
    """PRD §3.9: "It then derives `lapsed_carton_count` as the cartons released by
    lapses inside the accounting window ending at `as_of`, and `lapsed_carton_rate`
    as `lapsed_carton_count` divided by the program's `released_cartons_to_date`,
    rounded half up to four decimal places and zero when the denominator is zero."

    PRD §3.9: "a lapsed carton rate of exactly one quarter is tier two. The tier maps
    onto the program's `standing_status`: tier zero is `OPEN`, tier one is
    `RESTRICTED`, and tier two is `FROZEN`."

    Design: Corner/calculations/wastage_rate_and_standing_tier_precision
    """
    from test_helpers import setup_lapsed_program, get_program, add_lapsed_periods

    product, program, batch, win, ent = setup_lapsed_program()
    assert ent["computed_cartons"] == 10

    res = api.assess_program_standing(
        program["id"], {"as_of": "2026-09-04T00:00:00Z", "propagation_mode": "IMMEDIATE"},
        TEST_USERS["cold_chain_reviewer_headers"])
    standing = validate_success(res, 201)

    assert standing["lapsed_carton_rate"] == 1.0
    assert standing["lapsed_carton_count"] == 10
    assert standing["lapsed_period_count"] == 0
    # PRD §3.9: "A score of at most twenty is tier zero. Otherwise a program with at
    # least three lapsed periods, or a lapsed carton rate of at least one quarter, is
    # tier two". A program with no reporting period at all counts as zero lapsed
    # periods, so the weighted score here is min(10, 1 window) + 2 * 1 entitlement = 3,
    # which is tier zero: the rate alone cannot lift the tier.
    assert standing["risk_tier"] == 0
    assert get_program(program["id"])["standing_status"] == "OPEN"

    lapses = get_success_data(api.list_shipping_window_lapses(
        TEST_USERS["distribution_planner_headers"]))
    assert len(lapses) == 1
    assert lapses[0]["lapsed_cartons"] == 10

    # Once four unsubmitted reporting periods have closed the score passes twenty, and
    # the same lapsed carton rate of 1.0 then binds at tier two.
    add_lapsed_periods(program["id"], count=4)
    second = validate_success(api.assess_program_standing(
        program["id"], {"as_of": "2026-09-04T00:00:00Z", "propagation_mode": "IMMEDIATE"},
        TEST_USERS["cold_chain_reviewer_headers"]), 201)
    assert second["lapsed_period_count"] == 4
    assert second["risk_tier"] == 2
    assert get_program(program["id"])["standing_status"] == "FROZEN"


def test_split_and_lapsed_doses_reconcile_before_submission(api):
    """PRD §3.9: "Submitting the period is a `RegulatoryAffairsOfficer` act moving it
    from `OPEN` to `SUBMITTED`, and it is refused while three things remain
    outstanding: any excursion reported inside the period is not adjudicated, which
    surfaces as `ERR_PENDING_ADJUDICATIONS_IN_PERIOD`; any shipping-window lapse
    inside the period is not dose-reconciled, which surfaces as
    `ERR_PENDING_LAPSE_RECONCILIATION`".

    PRD §3.2: "The lapse's `doses_undelivered` is its `lapsed_cartons` multiplied by
    the batch presentation's doses per carton".

    Design: Corner/calculations/split_and_lapsed_doses_reconcile_before_submission
    """
    from test_helpers import make_reporting_period

    ctx = setup_entitled_site()
    period = make_reporting_period(ctx["program"]["id"],
                                   period_start="2026-09-01T00:00:00Z",
                                   period_end="2026-09-15T00:00:00Z")
    api_client.set_clock({"current_utc": "2026-09-04T00:00:00Z"},
                         TEST_USERS["platform_admin_headers"])
    closed = validate_success(api.close_allocation_window(
        ctx["window"]["id"], TEST_USERS["distribution_planner_headers"]), 200)
    assert closed["status"] == "CLOSED"

    res = api.submit_reporting_period(period["id"], TEST_USERS["regulatory_affairs_headers"])
    validate_error(res, "ERR_PENDING_LAPSE_RECONCILIATION", expected_status=422)

    lapses = get_success_data(api.list_shipping_window_lapses(
        TEST_USERS["distribution_planner_headers"]))
    assert len(lapses) == 1
    assert lapses[0]["dose_reconciliation_status"] == "PENDING"
    assert lapses[0]["lapsed_cartons"] == 10
    assert lapses[0]["doses_undelivered"] == 11700