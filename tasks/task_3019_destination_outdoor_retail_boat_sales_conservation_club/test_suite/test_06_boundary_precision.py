"""Depth tests: boundary-precision checks on different metrics and endpoints."""
from test_helpers import (
    ATTRACTION_HOST,
    ApiErrorId,
    CLUB_CARD_SPECIALIST,
    PLATFORM_ADMIN,
    create_member,
    create_point_event,
    create_store,
    get_success_data,
    set_clock,
    setup_waiver_venue,
    request_session,
    validate_error,
    validate_success,
)


# ===========================================================================
# club_tier_threshold_inclusive_boundary  (queue A / boundary_precision_check)
# ===========================================================================

def _member_with_empty_ledger(api):
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_bd@x.com",
                           full_name="Bo Dune")
    return store, member


def test_the_silver_threshold_is_inclusive_and_gold_lands_exactly_on_twenty_five_thousand(api):
    """PRD §2.8.1: "It reads the member's `points_lifetime_earned` and compares
    it against three thresholds with inclusive lower bounds: lifetime of at
    least sixty thousand points reads `PATRON`, otherwise at least twenty-five
    thousand reads `GOLD`, otherwise at least eight thousand reads `SILVER`, and
    anything lower reads `BASE`."
    PRD §2.8.1: "The comparison is inclusive, so exactly twenty-five thousand
    lifetime points is `GOLD` and twenty-four thousand nine hundred ninety-nine
    is `SILVER`."

    Design: Difficulty/boundary_precision_check/club_tier_threshold_inclusive_boundary
    """
    store, member = _member_with_empty_ledger(api)

    create_point_event(api, store["id"], member["id"], event_kind="AWARD",
                       points_delta=8000)
    at_silver = get_success_data(api.get_member(member["id"], PLATFORM_ADMIN), 200)
    assert at_silver["points_lifetime_earned"] == 8000
    assert at_silver["club_tier"] == "SILVER", (
        "the 8000 lower bound is inclusive, so exactly 8000 reads SILVER; got "
        f"{at_silver['club_tier']}"
    )

    create_point_event(api, store["id"], member["id"], event_kind="AWARD",
                       points_delta=16999)
    just_below = get_success_data(api.get_member(member["id"], PLATFORM_ADMIN), 200)
    assert just_below["points_lifetime_earned"] == 24999
    assert just_below["club_tier"] == "SILVER", (
        f"the threshold-minus-one case stays SILVER; got {just_below['club_tier']}"
    )

    create_point_event(api, store["id"], member["id"], event_kind="AWARD",
                       points_delta=1)
    at_gold = get_success_data(api.get_member(member["id"], PLATFORM_ADMIN), 200)
    assert at_gold["points_lifetime_earned"] == 25000
    assert at_gold["club_tier"] == "GOLD", (
        "the precisely-boundary case is inclusive, so 25000 reads GOLD; got "
        f"{at_gold['club_tier']}"
    )


def test_the_gold_retention_floor_is_subtracted_from_the_boundary_balance(api):
    """PRD §2.8.1: "the floor is zero points at `BASE`, five hundred at
    `SILVER`, fifteen hundred at `GOLD` and four thousand at `PATRON`."
    PRD §2.8.1: "`redeemable_points` is then computed as the member's
    `points_balance` minus a tier retention floor, clamped at zero."

    Design: Difficulty/boundary_precision_check/club_tier_threshold_inclusive_boundary
    """
    store, member = _member_with_empty_ledger(api)
    create_point_event(api, store["id"], member["id"], event_kind="AWARD",
                       points_delta=8000)
    create_point_event(api, store["id"], member["id"], event_kind="AWARD",
                       points_delta=16999)
    create_point_event(api, store["id"], member["id"], event_kind="AWARD",
                       points_delta=1)

    at_gold = get_success_data(api.get_member(member["id"], PLATFORM_ADMIN), 200)
    assert at_gold["club_tier"] == "GOLD"
    assert at_gold["points_balance"] == 25000
    assert at_gold["redeemable_points"] == 23500, (
        "25000 balance minus the GOLD retention floor of 1500; got "
        f"{at_gold['redeemable_points']}"
    )


# ===========================================================================
# lane_and_party_size_boundaries_on_two_endpoints  (queue A / boundary_precision_check)
# ===========================================================================

def test_a_party_of_four_at_lane_twelve_is_admitted_and_the_lane_ceiling_is_inclusive(api):
    """PRD §3.1: "Lane discipline applies to the staffed venues: an
    `ARCHERY_LANE` session may claim a `lane_no` no higher than twelve, and a
    `SIMULATOR` session may claim no higher than six."
    Design: Difficulty/boundary_precision_check/lane_and_party_size_boundaries_on_two_endpoints
    """
    store, attraction, member, waiver = setup_waiver_venue(api)

    response = request_session(api, store["id"], attraction["id"], member["id"],
                               session_kind="ARCHERY_LANE", party_size=4, lane_no=12,
                               waiver_id=waiver["id"],
                               slot_start_utc="2026-11-01T10:00:00Z",
                               slot_end_utc="2026-11-01T11:00:00Z")
    session = validate_success(response, 201)
    assert session["status"] == "CONFIRMED", (
        f"lane 12 sits inside the inclusive 12 limit; got {session['status']}"
    )
    assert session["lane_no"] == 12, "the lane upper bound is inclusive"
    assert session["dwell_charge_minutes"] >= 1, (
        "a confirmed session is charged dwell minutes; got "
        f"{session['dwell_charge_minutes']}"
    )


def test_lane_thirteen_is_refused_even_though_the_party_is_small(api):
    """PRD §3.1: "a lane number that exceeds its venue's ceiling is rejected
    with `ERR_LANE_CAPACITY_EXCEEDED` (HTTP 422) rather than silently clamped."

    Design: Difficulty/boundary_precision_check/lane_and_party_size_boundaries_on_two_endpoints
    """
    store, attraction, member, waiver = setup_waiver_venue(api)

    response = request_session(api, store["id"], attraction["id"], member["id"],
                               session_kind="ARCHERY_LANE", party_size=5, lane_no=13,
                               waiver_id=waiver["id"],
                               slot_start_utc="2026-11-02T10:00:00Z",
                               slot_end_utc="2026-11-02T11:00:00Z")
    validate_error(response, ApiErrorId.ERR_LANE_CAPACITY_EXCEEDED, 422)


def test_the_venue_capacity_boundary_is_a_distinct_metric_from_the_lane_boundary(api):
    """PRD §3.1: "Capacity shortfalls that are not waitlistable — a fresh request when the venue is already over its cap through its other committed sessions, or a confirmation attempt made while the store is"
    PRD §2.11: "a confirmation attempt made while the store is"

    Design: Difficulty/boundary_precision_check/lane_and_party_size_boundaries_on_two_endpoints
    """
    store, attraction, member, waiver = setup_waiver_venue(api, capacity_units=12)

    # The venue holds twelve guests, so a party of twelve confirms, and a party
    # of thirteen colliding on that same slot is an aggregate breach the store
    # reports as ERR_SESSION_OVERLAP (PRD §3.1). The lane ceiling is a separate
    # metric on the same endpoint and refuses lane thirteen outright.
    first = request_session(api, store["id"], attraction["id"], member["id"],
                            session_kind="ARCHERY_LANE", party_size=12, lane_no=12,
                            waiver_id=waiver["id"],
                            slot_start_utc="2026-11-03T10:00:00Z",
                            slot_end_utc="2026-11-03T11:00:00Z")
    session = validate_success(first, 201)
    assert session["status"] == "CONFIRMED", (
        f"twelve guests fit the twelve-unit venue; got {session['status']}"
    )
    venue = get_success_data(api.get_attraction(attraction["id"], ATTRACTION_HOST), 200)
    assert venue["in_use_units"] == 12

    response = request_session(api, store["id"], attraction["id"], member["id"],
                               session_kind="ARCHERY_LANE", party_size=13, lane_no=12,
                               waiver_id=waiver["id"],
                               slot_start_utc="2026-11-03T10:00:00Z",
                               slot_end_utc="2026-11-03T11:00:00Z")
    validate_error(response, ApiErrorId.ERR_SESSION_OVERLAP, 409)

    # A party of twelve fits the venue but lane thirteen is past the ceiling, so
    # the lane boundary is what refuses it.
    lane_response = request_session(api, store["id"], attraction["id"], member["id"],
                                    session_kind="ARCHERY_LANE", party_size=12,
                                    lane_no=13, waiver_id=waiver["id"],
                                    slot_start_utc="2026-11-04T10:00:00Z",
                                    slot_end_utc="2026-11-04T11:00:00Z")
    validate_error(lane_response, ApiErrorId.ERR_LANE_CAPACITY_EXCEEDED, 422)