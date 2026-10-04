"""Cross-entity dependencies: a child's transition gated by another entity."""
import pytest

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


def test_freeze_activation_is_refused_while_the_route_is_restricted():
    """PRD §3.3: "Activation requires the itinerary to be `PLANNED` or
    `WATCHING`, requires the route to be `ACTIVE` or `SURGE`, and requires the
    freeze to be in `DRAFT`; a `RESTRICTED` or `CLOSED` route admits no new
    freeze, and the attempt is refused with `ERR_ROUTE_RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_freeze_activation_depends_on_route_posture
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    freeze = create_freeze_in_state(itinerary["id"], "DRAFT", deposit_cents=250)
    route = read_route(route["id"])
    get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "RESTRICTED", "posture_reason_code": "REGIONAL_POOL_BREACH",
             "expected_route_version": route["version"]},
            TEST_USERS["admin_headers"])
    )

    res = api_client.activate_freeze(freeze["id"], {"expected_freeze_version": freeze["version"]},
                                     TEST_USERS["traveler_headers"])
    validate_error(res, "ERR_ROUTE_RESTRICTED")
    assert read_freeze(freeze["id"])["status"] == "DRAFT"


def test_the_same_activation_succeeds_once_the_route_moves_to_surge():
    """PRD §3.3: "The reachable operator transitions are `ACTIVE → SURGE`,
    `ACTIVE → RESTRICTED`, `SURGE → RESTRICTED`, `SURGE → ACTIVE`, and any of
    `ACTIVE`, `SURGE` or `RESTRICTED` into the terminal `CLOSED`".

    Design: Difficulty/cross_entity_state_dependency/cross_entity_freeze_activation_depends_on_route_posture
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    freeze = create_freeze_in_state(itinerary["id"], "DRAFT", deposit_cents=250)

    route = read_route(route["id"])
    get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "SURGE", "posture_reason_code": "DEMAND_PEAK",
             "expected_route_version": route["version"]},
            TEST_USERS["admin_headers"])
    )
    activated = get_success_data(
        api_client.activate_freeze(freeze["id"], {"expected_freeze_version": freeze["version"]},
                                   TEST_USERS["traveler_headers"])
    )
    assert activated["status"] == "HELD", (
        "the dependency is on the route's posture, not on the freeze itself"
    )
    assert read_route(route["id"])["posture"] == "SURGE"


def test_activation_re_pins_the_manifest_from_the_live_base_fare():
    """PRD §3.3: "Activation is the step that puts the freeze in flight, and it
    re-pins the manifest rather than reusing the draft-time value ... the
    manifest fare is re-pinned from the live route base fare at the activation
    instant, with `cap_cents` recomputed from the new manifest".

    Design: Difficulty/cross_entity_state_dependency/cross_entity_freeze_activation_depends_on_route_posture
    """
    set_clock()
    route = create_route(base_fare_cents=8900)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    freeze = create_freeze_in_state(itinerary["id"], "DRAFT", deposit_cents=250)
    assert read_freeze(freeze["id"])["manifest_fare_cents"] == 8900

    get_success_data(api_client.update_route(route["id"], {"base_fare_cents": 9100},
                                             TEST_USERS["admin_headers"]))
    activated = get_success_data(
        api_client.activate_freeze(freeze["id"], {"expected_freeze_version": freeze["version"]},
                                   TEST_USERS["traveler_headers"])
    )
    assert activated["manifest_fare_cents"] == 9100, (
        "the manifest is re-based at the moment the freeze becomes real"
    )
    assert activated["cap_cents"] == pytest.approx(12740.00, abs=0.01), (
        "the cap is recomputed from the new manifest"
    )


def test_settlement_is_refused_while_the_claim_has_not_been_approved():
    """PRD §2.5: "The segregation audit comes next and outranks every state
    check ... Only then are state gates consulted: whether the target resource
    sits in a state the requested transition can leave (`ERR_INVALID_STATE`)".
    PRD §3.5: "Settlement is the point of no return, and it is gated by the full
    ordered validation cascade described in §2.5".

    Design: Difficulty/cross_entity_state_dependency/cross_entity_freeze_claim_depends_on_approved_claim
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 14000, seats_left=4)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    claim = get_success_data(
        api_client.file_claim({"freeze_id": freeze["id"], "market_price_cents": 16500},
                              TEST_USERS["traveler_headers"])
    )

    # The claim is still FILED: its freeze may not be closed ahead of it.
    res = api_client.settle_claim(claim["id"], {"expected_claim_version": claim["version"]},
                                  TEST_USERS["adjuster_rosa_headers"])
    validate_error(res, "ERR_INVALID_STATE")
    assert read_freeze(freeze["id"])["status"] == "CLAIM_PENDING", (
        "the freeze only reaches CLAIMED once its claim is settled"
    )


def test_an_adjuster_may_not_approve_the_claim_it_reviewed():
    """PRD §3.5: "Both routes enforce the segregation gate, and an adjuster who
    filed the claim itself is refused with `ERR_SOD_VIOLATION`." PRD §2.1: "The
    acting identity for an approval, a review or a settlement must differ from
    the claim's `filer_user_id`, and must also differ from its
    `approver_user_id` once one has been recorded."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_freeze_claim_depends_on_approved_claim
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 14000, seats_left=4)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    claim = get_success_data(
        api_client.file_claim({"freeze_id": freeze["id"], "market_price_cents": 16500},
                              TEST_USERS["traveler_headers"])
    )
    reviewed = get_success_data(
        api_client.review_claim(claim["id"], {"review_note": "first-pass review"},
                                TEST_USERS["adjuster_ingrid_headers"])
    )
    assert reviewed["approver_user_id"] == "ca-ingrid"

    res = api_client.approve_claim(claim["id"], {"approval_note": "self-approval attempt"},
                                   TEST_USERS["adjuster_ingrid_headers"])
    validate_error(res, "ERR_SOD_VIOLATION")


def test_a_second_adjuster_approves_and_a_third_settles():
    """PRD §3.5: "The audit gate requires the claim's recorded
    `approver_user_id` to be set and to differ both from the `filer_user_id` and
    from the identity attempting the settlement — the adjuster who approved a
    claim may not also pay it."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_freeze_claim_depends_on_approved_claim
    """
    set_clock()
    route = create_route(max_guarantee_exposure_cents=500000)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 14000, seats_left=4)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    # The route's war chest starts at 0, so the exposure book is funded through
    # the declared ledger before the claim is settled: PRD §3.5's profile gate
    # requires the freeze's capped impact to fit inside `available_exposure_cents`.
    get_success_data(
        api_client.create_payment(
            {"itinerary_id": itinerary["id"], "payment_kind": "MEMBERSHIP_2",
             "amount_cents": 20000, "capture": True},
            TEST_USERS["ops_headers"])
    )
    # The filing's payout is the smaller of the market overshoot's capped impact
    # and the freeze's guarantee ceiling. A market price inside the freeze's
    # absorption cap overshoots by the same amount the freeze's own arrival
    # observation did, so the payout equals the freeze's capped impact and the
    # approval conformity test holds.
    claim = get_success_data(
        api_client.file_claim({"freeze_id": freeze["id"], "market_price_cents": 14000},
                              TEST_USERS["traveler_headers"])
    )
    assert claim["payout_cents"] == 6120
    assert read_freeze(freeze["id"])["capped_impact_cents"] == 6120
    get_success_data(api_client.review_claim(claim["id"], {"review_note": "first-pass review"},
                                             TEST_USERS["adjuster_ingrid_headers"]))
    approved = get_success_data(
        api_client.approve_claim(claim["id"], {"approval_note": "second adjuster"},
                                 TEST_USERS["adjuster_pavel_headers"])
    )
    assert approved["claim_status"] == "APPROVED"
    assert approved["approver_user_id"] == "ca-pavel"

    settled = get_success_data(
        api_client.settle_claim(claim["id"], {"expected_claim_version": approved["version"]},
                                TEST_USERS["adjuster_rosa_headers"])
    )
    assert settled["claim_status"] == "SETTLED_WITH_PURCHASE"
    assert read_freeze(freeze["id"])["status"] == "CLAIMED", (
        "the freeze reaches CLAIMED only at settlement, never earlier"
    )
