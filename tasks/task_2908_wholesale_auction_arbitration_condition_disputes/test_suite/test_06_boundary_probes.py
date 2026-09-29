"""Boundary probes: the rounded time axis, the integer mileage axis, and the two
scorecard thresholds that fight each other at their own boundaries."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_policy_action,
    assert_unpaginated_meta,
    validate_unpaginated,
)
from test_helpers.constants import MECHANICAL_POLICY, TITLE_BRANDED_POLICY
from test_helpers.factories import (
    case_payload,
    create_buyer,
    create_case,
    create_evidence,
    create_policy,
    create_sale,
    create_seller,
    decide_case,
    open_review,
    seller_response,
    set_clock,
)
from test_helpers.test_users import admin_headers, buyer_rep_headers

BOUNDARY_EXACT = "2026-08-03T00:00:00.000Z"
BOUNDARY_PLUS_ONE_SECOND = "2026-08-03T00:00:01.000Z"
BOUNDARY_PLUS_FOUR_SECONDS = "2026-08-03T00:00:04.000Z"
BOUNDARY_SALES = [
    {"announced_odometer_miles": 84000},
    {"announced_odometer_miles": 84000},
    {"announced_odometer_miles": 84000},
]


def _three_probe_world(api):
    """Three sales sharing one 48-hour boundary at 2026-08-03T00:00:00Z, with no
    inspection anywhere so the effective window is exactly 48 hours."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, MECHANICAL_POLICY)
    sales = [
        create_sale(api, seller["id"], buyer["id"], light_channel="YELLOW", **overrides)
        for overrides in BOUNDARY_SALES
    ]
    set_clock(api, BOUNDARY_EXACT)
    return {"seller": seller, "buyer": buyer, "sales": sales}


def _probe(api, buyer_id, sale_id, complaint):
    return api.create_case(
        case_payload(
            sale_id,
            defect_class="MECHANICAL",
            claim_amount_cents=100000,
            odometer_at_claim=84100,
            complaint_text=complaint,
        ),
        buyer_rep_headers(buyer_id),
    )


def test_the_window_is_inclusive_and_one_second_past_it_still_rounds_to_forty_eight(api):
    """Filing exactly on the boundary is admitted because the comparison is <=,
    and filing one second later is also admitted because 1/3600 of an hour rounds
    half up to 0.000 at three decimals.

    PRD: "First, `hours_elapsed_at_claim` is the difference between
    `claimed_at_utc` — the logical-clock instant the claim is filed — and the
    sale's `hammer_time_utc`, taken in seconds, divided by 3600, and rounded half
    up to three decimal places."

    Design: Difficulty/boundary_precision_check/window_boundary_three_way_at_48h_plus_1s_and_plus_4s
    """
    world = _three_probe_world(api)
    buyer_id = world["buyer"]["id"]

    at_boundary = validate_success(
        _probe(api, buyer_id, world["sales"][0]["id"], "Filed exactly on the boundary"),
        201,
    )
    assert at_boundary["hours_elapsed_at_claim"] == 48.0
    assert at_boundary["effective_window_hours"] == 48
    assert at_boundary["psi_extension_applied_hours"] == 0
    assert at_boundary["window_eligible"] is True

    set_clock(api, BOUNDARY_PLUS_ONE_SECOND)
    plus_one = validate_success(
        _probe(api, buyer_id, world["sales"][1]["id"], "Filed one second past"), 201
    )
    assert plus_one["hours_elapsed_at_claim"] == 48.0
    assert plus_one["window_eligible"] is True

    for case_id in (at_boundary["id"], plus_one["id"]):
        case = validate_success(api.get_case(case_id, admin_headers()), 200)
        assert case["status"] == "SUBMITTED"
        assert case["hours_elapsed_at_claim"] == 48.0


def test_four_seconds_past_the_boundary_rounds_to_forty_eight_point_zero_zero_one(api):
    """The third probe rounds to 48.001, exceeds 48, and is barred; the two
    admitted probes are the only claims the buyer's counters ever see.

    PRD: "When the time axis fails, intake is refused with
    `ERR_ARBITRATION_WINDOW_EXPIRED`."

    Design: Difficulty/boundary_precision_check/window_boundary_three_way_at_48h_plus_1s_and_plus_4s
    """
    world = _three_probe_world(api)
    buyer_id = world["buyer"]["id"]

    _probe(api, buyer_id, world["sales"][0]["id"], "Filed exactly on the boundary")
    set_clock(api, BOUNDARY_PLUS_ONE_SECOND)
    _probe(api, buyer_id, world["sales"][1]["id"], "Filed one second past")
    set_clock(api, BOUNDARY_PLUS_FOUR_SECONDS)

    response = _probe(
        api, buyer_id, world["sales"][2]["id"], "Filed four seconds past the boundary"
    )
    validate_error(response, ApiErrorId.ERR_ARBITRATION_WINDOW_EXPIRED.value)
    assert response.status_code == 409

    cases, _ = validate_paginated(
        api.list_cases(admin_headers(), params={"sale_id": world["sales"][2]["id"]})
    )
    assert cases == []

    barred_sale = validate_success(
        api.get_sale(world["sales"][2]["id"], admin_headers()), 200
    )
    assert barred_sale["arbitration_status"] == "NONE"

    buyer = validate_success(api.get_buyer(buyer_id, admin_headers()), 200)
    assert buyer["lifetime_claim_count"] == 2
    assert buyer["open_claim_count"] == 2


# --- The sample-size floor against the block threshold ------------------------

SELLER_A_SALES = [
    {"sale_price_cents": 1450000, "announced_odometer_miles": 84000, "light_channel": "RED"},
    {"sale_price_cents": 900000, "announced_odometer_miles": 61000, "light_channel": "GREEN"},
    {"sale_price_cents": 1100000, "announced_odometer_miles": 52000, "light_channel": "GREEN"},
]
SELLER_B_SALES = [
    {"sale_price_cents": 1200000, "announced_odometer_miles": 70000, "light_channel": "RED"},
    {"sale_price_cents": 800000, "announced_odometer_miles": 45000, "light_channel": "GREEN"},
    {"sale_price_cents": 1000000, "announced_odometer_miles": 38000, "light_channel": "GREEN"},
    {"sale_price_cents": 700000, "announced_odometer_miles": 91000, "light_channel": "YELLOW"},
]


def _branded_case_in_review(api, sale, seller_id, buyer_id, odometer, complaint):
    case = create_case(
        api,
        sale["id"],
        buyer_id,
        defect_class="TITLE_BRANDED",
        claim_amount_cents=150000,
        odometer_at_claim=odometer,
        complaint_text=complaint,
    )
    create_evidence(api, case["id"], buyer_id, evidence_type="TITLE_DOCUMENT")
    create_evidence(
        api, case["id"], buyer_id, evidence_type="THIRD_PARTY_VERIFICATION"
    )
    open_review(api, case["id"])
    seller_response(
        api, case["id"], seller_id, "DISPUTE", note="Title was clean when consigned"
    )
    return case


def _two_consignor_world(api):
    """Consignor A with three in-window sales and consignor B with four, each
    carrying one disputed TITLE_BRANDED claim ready for a ruling."""
    seller_a = create_seller(api)
    seller_b = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, TITLE_BRANDED_POLICY)
    sales_a = [
        create_sale(api, seller_a["id"], buyer["id"], **overrides)
        for overrides in SELLER_A_SALES
    ]
    sales_b = [
        create_sale(api, seller_b["id"], buyer["id"], **overrides)
        for overrides in SELLER_B_SALES
    ]
    case_a = _branded_case_in_review(
        api, sales_a[0], seller_a["id"], buyer["id"], 84000, "Title came back branded salvage"
    )
    case_b = _branded_case_in_review(
        api, sales_b[0], seller_b["id"], buyer["id"], 70000, "Title came back branded flood"
    )
    return {
        "seller_a": seller_a,
        "seller_b": seller_b,
        "buyer": buyer,
        "sales_a": sales_a,
        "sales_b": sales_b,
        "case_a": case_a,
        "case_b": case_b,
    }


def test_three_in_window_sales_hold_a_thirty_three_percent_rate_below_the_floor(api):
    """Consignor A ends at 3333 bps — far above the block threshold — yet stays in
    GOOD_STANDING with no policy action and no holds, because 3 in-window sales
    are one short of the four the tier rule requires.

    PRD: "if `rolling_window_sales_count` is below 4 the tier is
    `GOOD_STANDING`, because a rate computed from a handful of sales says nothing:
    a consignor with 3 in-window sales and 1 upheld claim shows a rate of 3333
    basis points and still stays in `GOOD_STANDING`."

    Design: Difficulty/boundary_precision_check/min_scorecard_sales_boundary_gates_a_higher_rate_than_the_block_threshold
    """
    world = _two_consignor_world(api)
    seller_a_id = world["seller_a"]["id"]

    decision = decide_case(
        api,
        world["case_a"]["id"],
        "UNWIND",
        fault_party="SELLER",
        rationale="Branded title confirmed by the DMV record",
    )
    assert decision["outcome"] == "UNWIND"
    assert decision["allowance_cents"] == 0

    case = validate_success(api.get_case(world["case_a"]["id"], admin_headers()), 200)
    assert case["status"] == "UNWOUND"

    scorecard = validate_success(api.get_seller_scorecard(seller_a_id, admin_headers()), 200)
    assert scorecard["rolling_window_sales_count"] == 3
    assert scorecard["rolling_window_upheld_count"] == 1
    assert scorecard["rolling_arbitration_rate_bps"] == 3333
    assert scorecard["policy_tier"] == "GOOD_STANDING"

    seller = validate_success(api.get_seller(seller_a_id, admin_headers()), 200)
    assert seller["policy_tier"] == "GOOD_STANDING"
    assert seller["blocked_at_utc"] is None

    actions, actions_meta = validate_unpaginated(
        api.list_seller_policy_actions(seller_a_id, admin_headers())
    )
    assert_unpaginated_meta(actions_meta, 0)
    assert actions == []

    for sale in world["sales_a"][1:]:
        row = validate_success(api.get_sale(sale["id"], admin_headers()), 200)
        assert row["settlement_hold"] is False


def test_a_rate_of_exactly_twenty_five_hundred_bps_on_four_sales_blocks_the_consignor(api):
    """Consignor B lands on the threshold itself and is blocked, proving the tier
    comparison is inclusive; the block holds the three undisputed sales and skips
    the claimed one.

    PRD: "Otherwise the tier is `BLOCKED` when the rolling rate is at least 2500
    basis points, `PROBATION` when it is at least 1500, `WATCH` when it is at
    least 800, and `GOOD_STANDING` below that."

    Design: Difficulty/boundary_precision_check/min_scorecard_sales_boundary_gates_a_higher_rate_than_the_block_threshold
    """
    world = _two_consignor_world(api)
    seller_b_id = world["seller_b"]["id"]

    decide_case(
        api,
        world["case_b"]["id"],
        "UNWIND",
        fault_party="SELLER",
        rationale="Branded title confirmed by the DMV record",
    )

    scorecard = validate_success(api.get_seller_scorecard(seller_b_id, admin_headers()), 200)
    assert scorecard["rolling_window_sales_count"] == 4
    assert scorecard["rolling_window_upheld_count"] == 1
    assert scorecard["rolling_arbitration_rate_bps"] == 2500
    assert scorecard["policy_tier"] == "BLOCKED"

    actions, actions_meta = validate_unpaginated(
        api.list_seller_policy_actions(seller_b_id, admin_headers())
    )
    assert_unpaginated_meta(actions_meta, 1)
    assert_policy_action(
        actions[0],
        action_type="BLOCK",
        from_tier="GOOD_STANDING",
        to_tier="BLOCKED",
        rolling_rate_bps=2500,
        triggered_by_case_id=world["case_b"]["id"],
    )

    for sale in world["sales_b"][1:]:
        row = validate_success(api.get_sale(sale["id"], admin_headers()), 200)
        assert row["settlement_hold"] is True

    claimed = validate_success(api.get_sale(world["sales_b"][0]["id"], admin_headers()), 200)
    assert claimed["settlement_hold"] is False


def test_a_null_window_is_unlimited_and_neither_unwind_reverses_unreleased_proceeds(api):
    """Both branded claims are eligible under a null window, and because both
    sales were still UNSETTLED neither unwind posts any sale-level rows.

    PRD: "Fourth, `effective_window_hours` is null when the policy's
    `window_hours` is null, and otherwise the policy's `window_hours` plus
    `psi_extension_applied_hours`."

    Design: Difficulty/boundary_precision_check/min_scorecard_sales_boundary_gates_a_higher_rate_than_the_block_threshold
    """
    world = _two_consignor_world(api)

    case_a = validate_success(api.get_case(world["case_a"]["id"], admin_headers()), 200)
    assert case_a["effective_window_hours"] is None
    assert case_a["window_eligible"] is True

    decide_case(api, world["case_a"]["id"], "UNWIND", fault_party="SELLER")
    decide_case(api, world["case_b"]["id"], "UNWIND", fault_party="SELLER")

    for sale_id in (world["sales_a"][0]["id"], world["sales_b"][0]["id"]):
        entries, meta = validate_unpaginated(
            api.list_sale_ledger_entries(sale_id, admin_headers())
        )
        assert_unpaginated_meta(meta, 0)
        assert entries == []
        sale = validate_success(api.get_sale(sale_id, admin_headers()), 200)
        assert sale["settlement_status"] == "REVERSED"


# --- The integer mileage axis -------------------------------------------------


def _mileage_probe_world(api):
    """Two sales at the default clock, so elapsed time is 0.0 on both probes and
    only the mileage axis can ever be the reason for a rejection."""
    seller = create_seller(api)
    buyer = create_buyer(api)
    create_policy(api, MECHANICAL_POLICY)
    at_limit = create_sale(
        api,
        seller["id"],
        buyer["id"],
        announced_odometer_miles=84000,
        light_channel="YELLOW",
    )
    over_limit = create_sale(
        api,
        seller["id"],
        buyer["id"],
        sale_price_cents=900000,
        announced_odometer_miles=61000,
        light_channel="YELLOW",
    )
    return {
        "seller": seller,
        "buyer": buyer,
        "at_limit": at_limit,
        "over_limit": over_limit,
    }


def test_driving_exactly_to_the_mileage_limit_is_admitted(api):
    """250 miles against a limit of 250 is inclusive, and the time axis is wide
    open at 0.0 hours.

    PRD: "The mileage axis passes when the policy's `mileage_limit` is null, and
    otherwise when `miles_driven_at_claim` is less than or equal to
    `mileage_limit`; a claim exactly on the limit is still eligible."

    Design: Difficulty/boundary_precision_check/mileage_limit_inclusive_at_250_and_barred_at_251
    """
    world = _mileage_probe_world(api)

    case = create_case(
        api,
        world["at_limit"]["id"],
        world["buyer"]["id"],
        defect_class="MECHANICAL",
        claim_amount_cents=100000,
        odometer_at_claim=84250,
        complaint_text="Driven exactly to the mileage limit",
    )

    assert case["miles_driven_at_claim"] == 250
    assert case["hours_elapsed_at_claim"] == 0.0
    assert case["window_eligible"] is True

    observed = validate_success(api.get_case(case["id"], admin_headers()), 200)
    assert observed["miles_driven_at_claim"] == 250
    assert observed["effective_window_hours"] == 48

    sale = validate_success(api.get_sale(world["at_limit"]["id"], admin_headers()), 200)
    assert sale["arbitration_status"] == "ACTIVE"
    assert sale["open_case_count"] == 1


def test_one_mile_past_the_limit_is_barred_on_the_mileage_axis_alone(api):
    """251 miles is refused as a mileage failure, not as a window failure, since
    the claim is filed at hour 0 of a 48-hour window.

    PRD: "When the time axis passes but the mileage axis fails, intake is refused
    with `ERR_MILEAGE_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/mileage_limit_inclusive_at_250_and_barred_at_251
    """
    world = _mileage_probe_world(api)
    buyer_id = world["buyer"]["id"]
    create_case(
        api,
        world["at_limit"]["id"],
        buyer_id,
        defect_class="MECHANICAL",
        claim_amount_cents=100000,
        odometer_at_claim=84250,
    )

    response = api.create_case(
        case_payload(
            world["over_limit"]["id"],
            defect_class="MECHANICAL",
            claim_amount_cents=100000,
            odometer_at_claim=61251,
            complaint_text="Driven one mile past the limit",
        ),
        buyer_rep_headers(buyer_id),
    )

    error = validate_error(response, ApiErrorId.ERR_MILEAGE_LIMIT_EXCEEDED.value)
    assert response.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_ARBITRATION_WINDOW_EXPIRED.value

    cases, _ = validate_paginated(
        api.list_cases(admin_headers(), params={"sale_id": world["over_limit"]["id"]})
    )
    assert cases == []

    barred = validate_success(api.get_sale(world["over_limit"]["id"], admin_headers()), 200)
    assert barred["arbitration_status"] == "NONE"
    assert barred["open_case_count"] == 0

    buyer = validate_success(api.get_buyer(buyer_id, admin_headers()), 200)
    assert buyer["open_claim_count"] == 1
    assert buyer["lifetime_claim_count"] == 1
