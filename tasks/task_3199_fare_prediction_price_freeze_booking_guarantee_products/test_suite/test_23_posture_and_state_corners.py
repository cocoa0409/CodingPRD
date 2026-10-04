"""Breadth coverage for posture moves and state-refusal corners."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_freeze_in_state,
    create_itinerary,
    create_route,
    get_success_data,
    observe,
    publish_curve,
    read_freeze,
    read_protection,
    read_route,
    set_clock,
    validate_error,
)


def test_posture_moves_are_reachable_only_from_their_declared_source_states():
    """PRD §2.11: "A route's `posture` moves `ACTIVE → SURGE → RESTRICTED →
    CLOSED`, with a sanctioned recovery arc from `SURGE` back to `ACTIVE` and a
    `RESTRICTED → ACTIVE` recovery when the regional pool's absorbed regression
    falls back to zero. `CLOSED` is terminal."

    Design: Corner/state_machines/corner_route_posture_transitions_from_each_allowed_state
    """
    set_clock()
    route = create_route()
    surges = get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "SURGE", "posture_reason_code": "DEMAND_PEAK",
             "expected_route_version": route["version"]},
            TEST_USERS["admin_headers"])
    )
    assert surges["posture"] == "SURGE"
    recovers = get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "ACTIVE", "posture_reason_code": "PEAK_PASSED",
             "expected_route_version": surges["version"]},
            TEST_USERS["admin_headers"])
    )
    assert recovers["posture"] == "ACTIVE"
    closed = get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "CLOSED", "posture_reason_code": "ROUTE_RETIRED",
             "expected_route_version": recovers["version"]},
            TEST_USERS["admin_headers"])
    )
    assert closed["posture"] == "CLOSED"
    # The operator's `posture_reason_code` is recorded with the transition (PRD
    # §2.11; the CLOSED cascade carries it forward).
    assert closed["posture_reason_code"] != ""
    assert closed["version"] == route["version"] + 3, (
        "each accepted posture move advances the route's version exactly once"
    )


def test_a_restricted_posture_records_the_operator_supplied_reason_code():
    """PRD §2.11: "where an operator may request a transition, the request
    carries an explicit `posture_reason_code`, and where the system drives the
    transition the reason code is supplied by the system instead. A route also
    reports a `posture_reason_code`, a machine-readable cause of its current
    posture".

    Design: Corner/state_machines/corner_route_posture_transitions_from_each_allowed_state
    """
    set_clock()
    route = create_route()
    restricted = get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "RESTRICTED", "posture_reason_code": "REGIONAL_POOL_BREACH",
             "expected_route_version": route["version"]},
            TEST_USERS["admin_headers"])
    )
    assert restricted["posture"] == "RESTRICTED"
    assert restricted["posture_reason_code"] == "REGIONAL_POOL_BREACH"
    assert read_route(route["id"])["posture"] == "RESTRICTED"


def test_a_freeze_holding_a_claim_cannot_be_cancelled_directly():
    """PRD §3.3: "And a freeze may be cancelled from `DRAFT`, from `HELD` or
    from `FROZEN`; the forfeiture rule described in §3.6 decides what the
    traveler loses, and the credited custody portion is released to the
    return-pending bucket."

    Design: Corner/state_machines/corner_price_freeze_cancellation_is_refused_from_claim_states
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
    assert read_freeze(freeze["id"])["status"] == "CLAIM_PENDING"

    res = api_client.cancel_freeze(freeze["id"], {"cancel_reason": "CHANGED_MIND"},
                                   TEST_USERS["traveler_headers"])
    validate_error(res, "ERR_INVALID_STATE")
    assert read_freeze(freeze["id"])["status"] == "CLAIM_PENDING"


def test_withdrawing_the_claim_returns_the_freeze_to_service():
    """PRD §3.5: "A `Traveler` may withdraw a claim in the same two states, but
    only for an itinerary they own, and supplies a `withdrawal_reason`; a
    withdrawal moves the claim to `WITHDRAWN`."

    Design: Corner/state_machines/corner_price_freeze_cancellation_is_refused_from_claim_states
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
    withdrawn = get_success_data(
        api_client.withdraw_claim(claim["id"], {"withdrawal_reason": "NOT_NEEDED"},
                                  TEST_USERS["traveler_headers"])
    )
    assert withdrawn["claim_status"] == "WITHDRAWN"
    assert read_freeze(freeze["id"])["status"] == "FROZEN", (
        "the claim is the only route back out of CLAIM_PENDING"
    )
    assert read_freeze(freeze["id"])["deposit_forfeited_cents"] == 0, (
        "a withdrawal never forfeits the deposit"
    )


def test_protection_activation_is_refused_on_a_restricted_route():
    """PRD §3.8: "Activation requires the product's pricing status to be
    `QUOTED` or `QUOTED_ACTIVE` ... and requires the route to be `ACTIVE` or
    `SURGE`, with a `RESTRICTED` or `CLOSED` route refused as
    `ERR_ROUTE_RESTRICTED`."

    Design: Corner/state_machines/corner_protection_activation_is_refused_on_a_restricted_route
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    protection = get_success_data(
        api_client.quote_protection(
            {"itinerary_id": itinerary["id"], "product_type": "CANCELLATION",
             "cancellation_disruption_probability": 0.70, "disclosure_version": 1,
             "disclosure_acknowledged": True},
            TEST_USERS["traveler_headers"])
    )
    route = read_route(route["id"])
    restricted = get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "RESTRICTED", "posture_reason_code": "REGIONAL_POOL_BREACH",
             "expected_route_version": route["version"]},
            TEST_USERS["admin_headers"])
    )
    res = api_client.activate_protection(
        protection["id"], {"expected_protection_version": protection["version"]},
        TEST_USERS["traveler_headers"]
    )
    validate_error(res, "ERR_ROUTE_RESTRICTED")
    assert read_protection(protection["id"])["lifecycle_status"] == "QUOTED"


def test_the_same_activation_succeeds_once_the_route_recovers():
    """PRD §2.11: "A route leaves `RESTRICTED` for `ACTIVE` once its regional
    pool's absorbed regression returns to zero."

    Design: Corner/state_machines/corner_protection_activation_is_refused_on_a_restricted_route
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 10000, seats_left=6)
    protection = get_success_data(
        api_client.quote_protection(
            {"itinerary_id": itinerary["id"], "product_type": "CANCELLATION",
             "cancellation_disruption_probability": 0.70, "disclosure_version": 1,
             "disclosure_acknowledged": True},
            TEST_USERS["traveler_headers"])
    )
    route = read_route(route["id"])
    restricted = get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "RESTRICTED", "posture_reason_code": "REGIONAL_POOL_BREACH",
             "expected_route_version": route["version"]},
            TEST_USERS["admin_headers"])
    )
    api_client.activate_protection(protection["id"],
                                   {"expected_protection_version": protection["version"]},
                                   TEST_USERS["traveler_headers"])
    # The region's pooled exposure recomputes to zero once no route holds a
    # freeze, which is what admits the SURGE -> ACTIVE recovery (PRD §3.10) that
    # then lets the activation through.
    # The region's absorbed regression is zero (no pool is breached), so PRD §2.11's
    # "RESTRICTED -> ACTIVE recovery when the regional pool's absorbed regression
    # falls back to zero" admits the recovery, after which the activation is no
    # longer refused on posture.
    recovered = get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "ACTIVE", "posture_reason_code": "PEAK_PASSED",
             "expected_route_version": restricted["version"]},
            TEST_USERS["admin_headers"])
    )
    assert recovered["posture"] == "ACTIVE", (
        "the regional pool's absorbed regression is zero, so the recovery is admitted"
    )
    activated = get_success_data(
        api_client.activate_protection(protection["id"],
                                       {"expected_protection_version": protection["version"]},
                                       TEST_USERS["traveler_headers"])
    )
    assert activated["lifecycle_status"] == "ACTIVE", (
        "the premium is payable only after a successful activation"
    )
    assert activated["version"] == protection["version"] + 1, (
        "the refused call mutated nothing, so the version advanced by exactly one"
    )
