"""Single requests that offend two numbered rules at once."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_freeze_in_state,
    create_itinerary,
    create_route,
    get_success_data,
    observe,
    publish_curve,
    read_claim,
    read_freeze,
    read_route,
    set_clock,
    validate_error,
)


def _route_parked_restricted_near_its_cap():
    """A route whose exposure ceiling is already consumed, then moved RESTRICTED.

    The freeze is left in HELD with an observation behind it, so its capped
    impact is non-zero and the exposure cap would bind on the next activation
    were the posture gate skipped.
    """
    route = create_route(max_guarantee_exposure_cents=1)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 14000, seats_left=4)
    freeze = create_freeze_in_state(itinerary["id"], "HELD", deposit_cents=250)
    route = read_route(route["id"])
    get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "RESTRICTED", "posture_reason_code": "REGIONAL_POOL_BREACH",
             "expected_route_version": route["version"]},
            TEST_USERS["admin_headers"])
    )
    return read_route(route["id"]), itinerary, freeze


def test_restricted_posture_outranks_the_exposure_cap_on_activation():
    """PRD §2.5: "The fiscal and safety gates occupy the middle of the order.
    The route risk profile gate — a claim whose freeze carries a
    `capped_impact_cents` larger than the route's `available_exposure_cents` —
    produces `ERR_ROUTE_EXPOSURE_PROFILE`; the custody backing gate produces
    `ERR_CUSTODY_INSUFFICIENT`; the regulatory posture gate, which requires a
    route to be `ACTIVE` or `SURGE`, produces `ERR_ROUTE_RESTRICTED`; and the
    per-route exposure cap produces `ERR_GUARANTEE_EXPOSURE_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_regulatory_posture_over_exposure_cap
    """
    set_clock()
    route, itinerary, freeze = _route_parked_restricted_near_its_cap()
    assert route["posture"] == "RESTRICTED"
    pending = read_freeze(freeze["id"])
    assert pending["capped_impact_cents"] > route["available_exposure_cents"], (
        "the exposure cap would bind if the posture gate did not fire first"
    )

    res = api_client.activate_freeze(
        freeze["id"], {"expected_freeze_version": pending["version"]},
        TEST_USERS["traveler_headers"]
    )
    validate_error(res, "ERR_ROUTE_RESTRICTED")


def test_a_request_violating_two_rules_reports_the_higher_precedence_one():
    """PRD §2.5: "a request that violates a low-priority rule and a
    high-priority rule reports the high-priority one, so a malformed-body error
    never masks an authorization failure and an exposure breach never masks a
    segregation breach."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_regulatory_posture_over_exposure_cap
    """
    set_clock()
    route, itinerary, freeze = _route_parked_restricted_near_its_cap()
    pending = read_freeze(freeze["id"])

    res = api_client.activate_freeze(
        freeze["id"], {"expected_freeze_version": pending["version"]},
        TEST_USERS["traveler_headers"]
    )
    body = res.json()
    assert body["data"]["error_id"] != "ERR_GUARANTEE_EXPOSURE_EXCEEDED", (
        "the exposure breach must not mask the higher-precedence posture gate"
    )
    unchanged = read_freeze(freeze["id"])
    assert unchanged["status"] == "HELD", "the refused activation mutated nothing"


def test_segregation_violation_outranks_the_route_exposure_profile_gate():
    """PRD §2.5: "The segregation audit comes next and outranks every state
    check: a claim approval, review or settlement attempted by the claim's own
    filer, or by the adjuster who already approved it, fails with
    `ERR_SOD_VIOLATION` before state is even examined."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_sod_over_route_exposure_profile
    """
    set_clock()
    route = create_route(max_guarantee_exposure_cents=1)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 14000, seats_left=4)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    claim = get_success_data(
        api_client.file_claim({"freeze_id": freeze["id"], "market_price_cents": 16500},
                              TEST_USERS["traveler_headers"])
    )
    # An entitled adjuster whose identity is the claim's own filer: the
    # segregation audit fires before the route profile gate is consulted.
    adjusted = get_success_data(
        api_client.review_claim(claim["id"], {"review_note": "first pass"},
                                TEST_USERS["adjuster_ingrid_headers"])
    )
    res = api_client.settle_claim(claim["id"], {"expected_claim_version": adjusted["version"]},
                                  TEST_USERS["adjuster_ingrid_headers"])
    validate_error(res, "ERR_SOD_VIOLATION")


def test_the_refused_settlement_leaves_the_claim_unreviewed_and_unpaid():
    """PRD §2.1: "A claim that has no recorded approver does not trip this rule;
    it is caught instead by the state check described in §2.6, which fails with
    `ERR_INVALID_STATE` (HTTP 409)." PRD §3.5: "A filing creates the claim in
    `FILED` with `filer_user_id` set to the acting `X-User-ID`,
    `approver_user_id` left null, and `audit_ready` false."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_sod_over_route_exposure_profile
    """
    set_clock()
    route = create_route(max_guarantee_exposure_cents=1)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 14000, seats_left=4)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    claim = get_success_data(
        api_client.file_claim({"freeze_id": freeze["id"], "market_price_cents": 16500},
                              TEST_USERS["traveler_headers"])
    )
    assert claim["claim_status"] == "FILED"
    assert claim["approver_user_id"] is None
    assert claim["audit_ready"] is False, (
        "the audit gate requires a recorded approver distinct from filer and settler"
    )

    api_client.settle_claim(claim["id"], {"expected_claim_version": claim["version"]},
                            TEST_USERS["traveler_headers"])
    unchanged = read_claim(claim["id"])
    assert unchanged["claim_status"] == "FILED", "no payout was disbursed by the refused call"
    assert read_freeze(freeze["id"])["status"] == "CLAIM_PENDING"
