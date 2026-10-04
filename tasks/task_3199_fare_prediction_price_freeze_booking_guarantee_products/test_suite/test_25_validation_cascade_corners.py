"""Breadth coverage for the ordered validation cascade."""

from test_helpers import (
    TEST_USERS,
    api_client,
    build_user_headers,
    create_freeze_in_state,
    create_itinerary,
    create_route,
    get_success_data,
    observe,
    publish_curve,
    read_freeze,
    read_itinerary,
    read_route,
    set_clock,
    validate_error,
)


def test_a_request_with_no_valid_actor_context_is_refused_before_the_lookup():
    """PRD §2.1: "A request missing either header, carrying a malformed value,
    or naming a role that the system does not declare is rejected with
    `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400)." PRD §2.5:
    "Authentication is resolved first: identity and role validity (which
    produces `ERR_MISSING_OR_INVALID_CONTEXT_HEADER`), then role entitlement and
    entity-backed identity (which produces `ERR_FORBIDDEN_FOR_ACTOR`)."

    Design: Corner/validations/corner_missing_context_header_is_rejected_before_anything_else
    """
    set_clock()
    res = api_client.get_route("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                               {"X-User-ID": "ghost", "X-User-Role": "GhostRole"})
    error = validate_error(res, "ERR_MISSING_OR_INVALID_CONTEXT_HEADER", expected_status=400)
    assert error["message"].strip()


def test_the_context_header_check_outranks_the_existence_check():
    """PRD §2.5: "First, a request that violates a low-priority rule and a
    high-priority rule reports the high-priority one, so a malformed-body error
    never masks an authorization failure".

    Design: Corner/validations/corner_missing_context_header_is_rejected_before_anything_else
    """
    set_clock()
    # The route does not exist either, yet the context error is what surfaces.
    res = api_client.get_route("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", {})
    body = res.json()
    assert body["data"]["error_id"] == "ERR_MISSING_OR_INVALID_CONTEXT_HEADER"
    assert body["data"]["error_id"] != "ERR_ROUTE_NOT_FOUND", (
        "no route lookup is performed before the actor context is validated"
    )


def test_an_undeclared_role_is_refused_at_priority_two():
    """PRD §2.1: "When the role is valid but the role is not entitled to the
    operation being attempted, or the presented identity is not the entity it
    claims to be, the request is rejected with `ERR_FORBIDDEN_FOR_ACTOR` (HTTP
    403)."

    Design: Corner/validations/corner_role_not_permitted_is_rejected_at_priority_two
    """
    set_clock()
    route = create_route()
    itinerary = create_itinerary(route["id"], "tv-mara")
    res = api_client.create_observation(
        {"route_id": route["id"], "itinerary_id": itinerary["id"], "fare_cents": 9000,
         "seats_left": 9},
        TEST_USERS["traveler_headers"])
    validate_error(res, "ERR_FORBIDDEN_FOR_ACTOR", expected_status=403)
    assert read_itinerary(itinerary["id"])["observed_fares_cents"] == [], (
        "the refusal mutated nothing"
    )


def test_the_same_call_succeeds_for_the_entitled_role():
    """PRD §2.6: "A `Traveler` may act on an itinerary only when its
    `traveler_user_id` equals the presented `X-User-ID`, and may withdraw only
    claims attached to such an itinerary; anyone else attempting these
    operations is rejected with `ERR_FORBIDDEN_FOR_ACTOR`."

    Design: Corner/validations/corner_role_not_permitted_is_rejected_at_priority_two
    """
    set_clock()
    route = create_route()
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 9000, seats_left=9)
    assert read_itinerary(itinerary["id"])["observed_fares_cents"] == [9000], (
        "the entitled role's identical call is accepted"
    )


def test_a_state_error_outranks_the_trailing_payload_completeness_check():
    """PRD §2.5: "Only then are state gates consulted: whether the target
    resource sits in a state the requested transition can leave
    (`ERR_INVALID_STATE`)". PRD §2.5: "The referential, constraint, disclosure
    and schema-existence family closes the order: `ERR_PRODUCT_TYPE_MISMATCH`,
    `ERR_HEDGE_DUPLICATE_COVERAGE`, `ERR_DUPLICATE_SEQUENCE_INDEX`,
    `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` and `ERR_PRICE_FIELD_MISSING`."

    Design: Corner/validations/corner_state_precondition_outranks_the_trailing_payload_completeness_check
    """
    set_clock()
    route = create_route()
    itinerary = create_itinerary(route["id"], "tv-mara")
    get_success_data(api_client.book_itinerary(itinerary["id"], {},
                                               TEST_USERS["traveler_headers"]))

    # The body carries a valid deposit bound and a current parent version, and
    # omits only the disclosure fields; the state gate still reports first (PRD
    # §2.5: the state gate outranks the disclosure gate).
    res = api_client.open_freeze(
        itinerary["id"],
        {"deposit_cents": 500, "expected_itinerary_version":
         read_itinerary(itinerary["id"])["version"]},
        TEST_USERS["traveler_headers"])
    validate_error(res, "ERR_INVALID_STATE")
    assert read_itinerary(itinerary["id"])["travel_status"] == "BOOKED"


def test_the_disclosure_acknowledgement_gate_is_enforced_before_schema_checks():
    """PRD §2.7: "A request to quote a protection product or to open a freeze
    must cite a `disclosure_version` equal to the route's current value and must
    carry an acknowledgment at `disclosure_acknowledged`; if the cited version is
    stale, or the `disclosure_acknowledged` flag is not set, the request is
    rejected with `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` (HTTP 422)."

    Design: Corner/validations/corner_disclosure_gate_precedes_the_exposure_cap
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    get_success_data(api_client.update_route(
        route["id"], {"disclosure_headline": "v2 with the optional-product notice"},
        TEST_USERS["admin_headers"]))

    res = api_client.open_freeze(
        itinerary["id"],
        {"deposit_cents": 250, "disclosure_version": 1, "disclosure_acknowledged": False,
         "expected_itinerary_version": itinerary["version"]},
        TEST_USERS["traveler_headers"])
    validate_error(res, "ERR_DISCLOSURE_NOT_ACKNOWLEDGED", expected_status=422)
    assert read_route(route["id"])["disclosure_version"] == 2


def test_a_retry_citing_the_current_disclosure_version_succeeds():
    """PRD §3.1: "A change to the `disclosure_headline` increments the route's
    disclosure version, which means a buyer who has been staring at a cached
    quote must fetch the new version before a freeze or a protection quote will
    be accepted."

    Design: Corner/validations/corner_disclosure_gate_precedes_the_exposure_cap
    """
    set_clock()
    route = create_route()
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    get_success_data(api_client.update_route(
        route["id"], {"disclosure_headline": "v2 with the optional-product notice"},
        TEST_USERS["admin_headers"]))
    refreshed_route = read_route(route["id"])
    refreshed_itinerary = read_itinerary(itinerary["id"])

    accepted = get_success_data(
        api_client.open_freeze(
            itinerary["id"],
            {"deposit_cents": 250, "disclosure_version": refreshed_route["disclosure_version"],
             "disclosure_acknowledged": True,
             "expected_itinerary_version": refreshed_itinerary["version"]},
            TEST_USERS["traveler_headers"])
    )
    assert accepted["status"] == "DRAFT"
