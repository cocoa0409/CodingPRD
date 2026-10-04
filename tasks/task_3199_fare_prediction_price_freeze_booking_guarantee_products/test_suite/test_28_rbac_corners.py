"""Breadth coverage for segregation of duties across the role model."""

from test_helpers import (
    TEST_USERS,
    api_client,
    api_client,
    create_freeze_in_state,
    create_itinerary,
    create_route,
    get_success_data,
    observe,
    publish_curve,
    read_hedging_position,
    read_route,
    set_clock,
    validate_error,
)


def test_the_claims_desk_cannot_file_a_claim_and_the_traveler_cannot_review_one():
    """PRD §3.5: "A `Traveler` files a claim against their own `FROZEN` freeze."
    PRD §3.5: "A claims adjuster moves a `FILED` claim into `UNDER_REVIEW`".
    PRD §5: "`ERR_FORBIDDEN_FOR_ACTOR` | 403 Forbidden".

    Design: Corner/rbac/corner_claims_adjuster_cannot_file_a_guarantee_claim
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 14000, seats_left=4)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)

    adjuster_filing = api_client.file_claim(
        {"freeze_id": freeze["id"], "market_price_cents": 16500},
        TEST_USERS["adjuster_ingrid_headers"])
    validate_error(adjuster_filing, "ERR_FORBIDDEN_FOR_ACTOR", expected_status=403)

    filed = get_success_data(
        api_client.file_claim({"freeze_id": freeze["id"], "market_price_cents": 16500},
                              TEST_USERS["traveler_headers"])
    )
    assert filed["claim_status"] == "FILED"

    traveler_review = api_client.review_claim(filed["id"],
                                              {"review_note": "adjuster review"},
                                              TEST_USERS["traveler_headers"])
    validate_error(traveler_review, "ERR_FORBIDDEN_FOR_ACTOR", expected_status=403)


def test_the_hedging_desk_and_the_claims_desk_cannot_act_on_each_others_work():
    """PRD §3.9: "A `RiskAnalyst` remarks an `OPEN` position by supplying a
    `projected_day_cost_cents`". PRD §3.5: "A claims adjuster moves a `FILED`
    claim into `UNDER_REVIEW`, which stamps `approver_user_id` with the acting
    identity".

    Design: Corner/rbac/corner_risk_analyst_cannot_touch_a_claim_and_adjuster_cannot_mark_a_hedge
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    position = get_success_data(
        api_client.open_hedging_position(
            {"route_id": route["id"], "coverage_date": "2026-09-15T00:00:00Z",
             "hedge_price_cents": 9000, "contract_quantity_cents": 500000,
             "expected_route_version": route["version"]},
            TEST_USERS["risk_analyst_headers"])
    )
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 14000, seats_left=4)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    claim = get_success_data(
        api_client.file_claim({"freeze_id": freeze["id"], "market_price_cents": 16500},
                              TEST_USERS["traveler_headers"])
    )

    hedge_review = api_client.review_claim(claim["id"], {"review_note": "hedge desk attempt"},
                                           TEST_USERS["risk_analyst_headers"])
    validate_error(hedge_review, "ERR_FORBIDDEN_FOR_ACTOR", expected_status=403)

    adjuster_mark = api_client.mark_hedging_position(
        position["id"], {"projected_day_cost_cents": 11000},
        TEST_USERS["adjuster_ingrid_headers"])
    validate_error(adjuster_mark, "ERR_FORBIDDEN_FOR_ACTOR", expected_status=403)
    assert read_hedging_position(position["id"])["status"] == "OPEN", (
        "the refused mark left the position untouched"
    )


def test_a_traveler_may_not_present_another_travelers_identity():
    """PRD §2.1: "A `Traveler` may only act on itineraries whose
    `traveler_user_id` equals their presented `X-User-ID`". PRD §2.6:
    "Ownership is enforced for exactly two parties."

    Design: Corner/rbac/corner_traveler_role_cannot_supply_another_travelers_identity
    """
    set_clock()
    route = create_route()
    itinerary = create_itinerary(route["id"], "tv-mara")
    impostor = api_client.book_itinerary(itinerary["id"], {},
                                         TEST_USERS["traveler_impostor_headers"])
    validate_error(impostor, "ERR_FORBIDDEN_FOR_ACTOR", expected_status=403)
    assert get_success_data(api_client.get_itinerary(itinerary["id"],
                                                     TEST_USERS["traveler_headers"])
                            )["travel_status"] == "PLANNED"


def test_the_owner_books_the_itinerary_successfully():
    """PRD §3.10: "Success sets `travel_status` to the terminal value `BOOKED`,
    records `listed_fare_cents` as the route's `base_fare_cents` at the booking
    instant, and decrements the route's `seats_left` by 1."

    Design: Corner/rbac/corner_traveler_role_cannot_supply_another_travelers_identity
    """
    set_clock()
    route = create_route()
    itinerary = create_itinerary(route["id"], "tv-mara")
    before = read_route(route["id"])["seats_left"]
    booked = get_success_data(api_client.book_itinerary(itinerary["id"], {},
                                                        TEST_USERS["traveler_headers"]))
    assert booked["travel_status"] == "BOOKED"
    assert booked["listed_fare_cents"] == route["base_fare_cents"]
    assert read_route(route["id"])["seats_left"] == before - 1


def test_a_protected_cancellation_cannot_be_exercised_twice():
    """PRD §3.8: "must not have already exercised a cancellation, or the attempt
    fails with `ERR_CANCELLATION_ALREADY_EXERCISED`." PRD §3.8: "Success moves
    the product to `CANCELLED_PROTECTED` with `cancelled_by_member` true".

    Design: Corner/errors/corner_sod_violation_and_invalid_state_are_both_triggerable
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    headers = TEST_USERS["traveler_headers"]
    protection = get_success_data(
        api_client.quote_protection(
            {"itinerary_id": itinerary["id"], "product_type": "CANCELLATION",
             "cancellation_disruption_probability": 0.70, "disclosure_version": 1,
             "disclosure_acknowledged": True},
            headers)
    )
    get_success_data(
        api_client.activate_protection(protection["id"],
                                       {"expected_protection_version": protection["version"]},
                                       headers)
    )
    exercised = get_success_data(
        api_client.cancel_protected(protection["id"],
                                    {"acknowledge_minimum_disruption": True}, headers)
    )
    assert exercised["lifecycle_status"] == "CANCELLED_PROTECTED"
    assert exercised["cancelled_by_member"] is True

    replay = api_client.cancel_protected(protection["id"],
                                         {"acknowledge_minimum_disruption": True}, headers)
    validate_error(replay, "ERR_CANCELLATION_ALREADY_EXERCISED", expected_status=409)


def test_a_second_change_settlement_beyond_the_day_balance_is_refused():
    """PRD §2.6: "A change settlement that would consume more days than the
    product has remaining fails with `ERR_INSUFFICIENT_BONUS_DAYS`". PRD §2.5:
    "The referential, constraint, disclosure and schema-existence family closes
    the order".

    Design: Corner/errors/corner_sod_violation_and_invalid_state_are_both_triggerable
    """
    set_clock()
    route = create_route(origin_airport="ORD", destination_airport="LHR",
                         flight_number="HA707", region="MIDWEST", base_fare_cents=13200,
                         peak_price_day_index=0, seats_left=6,
                         fare_band_cents=[9000, 12000, 15000, 17000, 19000])
    publish_curve(route["id"], each_day_prices_cents=[9000, 9000, 9000, 9000, 9000],
                  seats_left_at_each_day=[6, 6, 6, 6, 6])
    itinerary = create_itinerary(route["id"], "tv-otis", departure_date="2026-12-01T00:00:00Z")
    headers = TEST_USERS["traveler_otis_headers"]
    protection = get_success_data(
        api_client.quote_protection(
            {"itinerary_id": itinerary["id"], "product_type": "CHANGE",
             "cancellation_disruption_probability": 0.70, "disclosure_version": 1,
             "disclosure_acknowledged": True},
            headers)
    )
    get_success_data(
        api_client.activate_protection(protection["id"],
                                       {"expected_protection_version": protection["version"]},
                                       headers)
    )
    # A twelve-day shift consumes eight days against a two-day entitlement, so
    # the settlement overruns the balance.
    change_event = get_success_data(
        api_client.file_change_event(
            {"protection_id": protection["id"], "new_departure_date": "2026-12-13T00:00:00Z",
             "gap_direction": "ORIGIN_DIRECTION"},
            headers)
    )
    option = get_success_data(
        api_client.offer_option(
            {"change_event_id": change_event["id"], "departure_date": "2026-12-13T00:00:00Z",
             "option_fare_cents": 13200},
            headers)
    )
    get_success_data(api_client.select_option(change_event["id"], {"option_id": option["id"]},
                                              headers))
    get_success_data(api_client.accept_option(option["id"], {}, headers))

    res = api_client.settle_change_event(change_event["id"], {}, headers)
    validate_error(res, "ERR_INSUFFICIENT_BONUS_DAYS")


def test_the_claim_desk_review_right_is_not_shared_with_the_hedging_desk():
    """PRD §3.5: "A claims adjuster moves a `FILED` claim into `UNDER_REVIEW`,
    which stamps `approver_user_id` with the acting identity". PRD §5:
    "`ERR_FORBIDDEN_FOR_ACTOR` | 403 Forbidden".

    Design: Corner/errors/corner_sod_violation_and_invalid_state_are_both_triggerable
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
    refused = api_client.review_claim(claim["id"], {"review_note": "wrong desk"},
                                      TEST_USERS["risk_analyst_headers"])
    validate_error(refused, "ERR_FORBIDDEN_FOR_ACTOR", expected_status=403)

    reviewed = get_success_data(
        api_client.review_claim(claim["id"], {"review_note": "adjuster review"},
                                TEST_USERS["adjuster_ingrid_headers"])
    )
    assert reviewed["claim_status"] == "UNDER_REVIEW"


def test_the_platform_operator_moves_the_posture_but_holds_no_claim_authority():
    """PRD §2.1: "for `PlatformAdmin`, who owns route configuration, postures
    and the logical clock". PRD §1: "the identity that files a claim, the
    identity that approves it, and the identity that settles it may not collapse
    into one person."

    Design: Corner/rbac/corner_platform_admin_holds_route_and_clock_authority_only
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

    surged = get_success_data(
        api_client.transition_route_posture(
            route["id"],
            {"to_posture": "SURGE", "posture_reason_code": "DEMAND_PEAK",
             "expected_route_version": route["version"]},
            TEST_USERS["admin_headers"])
    )
    assert surged["posture"] == "SURGE"

    admin_approval = api_client.approve_claim(claim["id"], {"approval_note": "admin short-cut"},
                                              TEST_USERS["admin_headers"])
    validate_error(admin_approval, "ERR_FORBIDDEN_FOR_ACTOR", expected_status=403)
    refreshed_claim = get_success_data(api_client.get_claim(claim["id"],
                                                            TEST_USERS["admin_headers"]))
    assert refreshed_claim["claim_status"] == "FILED", (
        "the operator holds no claim authority"
    )
