"""Authentication, the peer-role authorisation model, ownership and not-found codes."""

import pytest

from test_helpers import (
    ADVERTISING_SALES,
    ARTISTIC_ADMIN,
    BOX_OFFICE,
    NO_AUTH_HEADERS,
    ORCHESTRA_MANAGER,
    ApiErrorId,
    add_engagement,
    build_on_sale_world,
    build_world,
    create_contract,
    create_musician,
    create_patron,
    create_service,
    create_venue,
    current_concert_version,
    inventory_for,
    make_guest_artist_headers,
    make_headers,
    make_musician_headers,
    make_patron_headers,
    read_concert,
    read_contract,
    read_engagement,
    read_patron,
    read_service,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_SEASON = "00000000-0000-4000-8000-000000000001"
UNKNOWN_VENUE = "00000000-0000-4000-8000-000000000002"
UNKNOWN_SECTION = "00000000-0000-4000-8000-000000000003"
UNKNOWN_CONCERT = "00000000-0000-4000-8000-000000000004"
UNKNOWN_CONTRACT = "00000000-0000-4000-8000-000000000005"
UNKNOWN_MUSICIAN = "00000000-0000-4000-8000-000000000006"
UNKNOWN_SERVICE = "00000000-0000-4000-8000-000000000007"
UNKNOWN_ENGAGEMENT = "00000000-0000-4000-8000-000000000008"
UNKNOWN_PATRON = "00000000-0000-4000-8000-000000000009"
UNKNOWN_SUBSCRIPTION = "00000000-0000-4000-8000-00000000000a"
UNKNOWN_ORDER = "00000000-0000-4000-8000-00000000000b"
UNKNOWN_BOOKING = "00000000-0000-4000-8000-00000000000c"


@pytest.mark.parametrize(
    "headers,label",
    [
        (NO_AUTH_HEADERS, "no identity headers at all"),
        ({"X-User-Role": "ArtisticAdmin", "Content-Type": "application/json"},
         "X-User-ID omitted"),
        ({"X-User-ID": "someone", "Content-Type": "application/json"},
         "X-User-Role omitted"),
        (make_headers("Auditor", "someone"), "an undeclared role name"),
    ],
)
def test_requests_without_a_declared_identity_are_unauthenticated(api, headers, label):
    """PRD 2.1: "A request that omits either header, or that presents an
    `X-User-Role` value which is not one of those seven strings, is rejected with
    `ERR_UNAUTHENTICATED`."
    PRD 2.6: "**Authentication.** `X-User-Role` and `X-User-ID` are both present
    and `X-User-Role` is one of the seven declared roles, else
    `ERR_UNAUTHENTICATED` with HTTP 401. This applies to every endpoint."

    Design: Corner/rbac/rbac_missing_auth_headers_returns_unauthenticated
    """
    response = api.get_season(UNKNOWN_SEASON, headers)
    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert error["error_id"] != ApiErrorId.ERR_SEASON_NOT_FOUND.value, (
        f"authentication ({label}) outranks path existence"
    )


def test_patron_may_not_create_a_concert(api):
    """PRD 2.1: "A request whose role is well-formed but is not listed among the
    roles authorised for the endpoint being called is rejected with
    `ERR_UNAUTHORIZED`."
    PRD 2.1: "`ArtisticAdmin` owns seasons, halls, seating sections, concerts,
    programming decisions, guest artist offers, cancellations and substitutions."

    Design: Corner/rbac/patron_cannot_create_concert_returns_unauthorized
    """
    set_clock("2026-09-01T00:00:00Z")
    world = build_world(clock=None, with_union=False, concert_count=0,
                        program_indexes=[])
    patron = create_patron(full_name="Noel Vance", email="noel-rbac@patron.test")

    response = api.create_concert(
        {
            "season_id": world.season["id"],
            "venue_id": world.venue["id"],
            "title": "Patron Concert",
            "performance_start_utc": "2026-11-05T19:30:00Z",
            "performance_end_utc": "2026-11-05T21:30:00Z",
            "program_minutes": 100,
        },
        make_patron_headers(patron["id"]),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    _, meta = validate_paginated(
        api.list_concerts(ARTISTIC_ADMIN, params={"season_id": world.season["id"]})
    )
    assert meta["total_count"] == 0


def test_artistic_admin_may_not_add_a_musician(api):
    """PRD 2.1: "The seven roles are peers rather than a hierarchy — each owns a
    different family of resources."
    PRD 2.1: "`OrchestraManager` owns the musician roster, the collective
    bargaining agreement, rehearsal services and the engagements booked onto them."

    Design: Corner/rbac/artistic_admin_cannot_add_musician_returns_unauthorized
    """
    set_clock("2026-09-01T00:00:00Z")
    response = api.create_musician(
        {"full_name": "Pia Solberg", "instrument": "VIOLIN"}, ARTISTIC_ADMIN
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_musician_may_not_decline_another_players_engagement(api):
    """PRD 3.3: "Only the `Musician` whose `X-User-ID` equals the engagement's
    `musician_id` may do so; anyone else is refused with `ERR_NOT_RESOURCE_OWNER`."
    PRD 2.1: "When `X-User-Role` is `Musician`, `X-User-ID` is the `id` of the
    acting `Musician` record; ownership checks on an engagement compare the
    engagement's `musician_id` to `X-User-ID`."

    Design: Corner/rbac/musician_cannot_decline_another_musicians_engagement
    """
    world = build_world()
    booked = create_musician(full_name="Pia Solberg", instrument="VIOLIN")
    other = create_musician(full_name="Tomas Reiner", instrument="CELLO")
    service = create_service(world.concert["id"], world.venue["id"])
    engagement = add_engagement(service["id"], booked["id"])

    response = api.decline_engagement(
        engagement["id"], make_musician_headers(other["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    assert read_engagement(engagement["id"])["status"] == "CONFIRMED"
    assert read_service(service["id"])["confirmed_engagement_count"] == 1


def test_guest_artist_may_not_counter_a_contract_that_is_not_their_own(api):
    """PRD 2.1: "When `X-User-Role` is `GuestArtist`, the contract row itself is the
    identity: `X-User-ID` is the `id` of the acting `GuestArtistContract`, and
    ownership checks compare the target contract's own `id` to `X-User-ID`."
    PRD 3.2: "Only a `GuestArtist` whose `X-User-ID` equals the contract's own `id`
    may do this — anyone else is refused with `ERR_NOT_RESOURCE_OWNER` — and a
    contract that is not in `OFFERED` is refused with `ERR_CONTRACT_NOT_NEGOTIABLE`."

    Design: Corner/rbac/guest_artist_cannot_counter_another_contract
    """
    world = build_world()
    soloist = create_contract(world.concert["id"], artist_name="Mira Halvorsen",
                              role_type="SOLOIST", offered_fee_cents=800000)
    conductor = create_contract(world.concert["id"], artist_name="Yuri Panek",
                                role_type="CONDUCTOR", offered_fee_cents=600000)

    response = api.counter_guest_contract(
        soloist["id"], 1500000, make_guest_artist_headers(conductor["id"])
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    assert read_contract(soloist["id"])["status"] == "OFFERED"
    assert read_contract(soloist["id"])["countered_fee_cents"] is None
    assert read_contract(conductor["id"])["status"] == "OFFERED"


def test_patron_may_not_order_tickets_for_another_patron(api):
    """PRD 2.1: "When `X-User-Role` is `Patron`, `X-User-ID` is the `id` of the
    acting `Patron` record; ownership checks on any resource that references a
    patron compare that resource's `patron_id` to `X-User-ID`."
    PRD 2.1: "Whenever an entity-backed role acts on a resource whose owning
    identifier differs from `X-User-ID`, the request is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/patron_cannot_order_tickets_for_another_patron
    """
    world = build_on_sale_world()
    buyer = create_patron(full_name="Noel Vance", email="noel-own@patron.test")
    impostor = create_patron(full_name="Iris Lund", email="iris-own@patron.test")

    response = api.create_ticket_order(
        {
            "concert_id": world.concert["id"],
            "patron_id": buyer["id"],
            "seat_section_id": world.section["id"],
            "seat_count": 1,
            "expected_concert_version": current_concert_version(world.concert["id"]),
        },
        make_patron_headers(impostor["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    element = inventory_for(read_concert(world.concert["id"]), world.section["id"])
    assert element["held_count"] == 0

    _, meta = validate_paginated(
        api.list_ticket_orders(BOX_OFFICE, params={"patron_id": buyer["id"]})
    )
    assert meta["total_count"] == 0


def test_patron_may_hold_and_pay_their_own_ticket_order(api):
    """PRD 2.1: "`Patron` is a subscriber or single-ticket buyer acting for themself."
    PRD 3.7: "`amount_paid_cents` is set to the full `amount_due_cents` regardless
    of how it was funded, and the patron's `lifetime_cash_in_cents` grows only by
    the cash portion — `amount_due_cents` less `credit_applied_cents` — which is
    exactly what keeps the identity of §2.10 balanced."

    Design: Corner/rbac/patron_may_create_and_pay_own_ticket_order
    """
    world = build_on_sale_world()
    patron = create_patron(full_name="Noel Vance", email="noel-self@patron.test")
    headers = make_patron_headers(patron["id"])

    version = validate_success(api.get_concert(world.concert["id"], headers))["version"]
    order = validate_success(
        api.create_ticket_order(
            {
                "concert_id": world.concert["id"],
                "patron_id": patron["id"],
                "seat_section_id": world.section["id"],
                "seat_count": 1,
                "expected_concert_version": version,
            },
            headers,
        ),
        201,
    )
    paid = validate_success(
        api.pay_ticket_order(order["id"], headers, use_credit=False)
    )

    assert paid["status"] == "PAID"
    assert paid["amount_paid_cents"] == 8100
    assert paid["credit_applied_cents"] == 0
    assert read_patron(patron["id"])["lifetime_cash_in_cents"] == 8100

    element = inventory_for(read_concert(world.concert["id"]), world.section["id"])
    assert element["sold_count"] == 1


def test_unknown_ids_on_catalogue_reads_report_their_own_not_found_code(api):
    """PRD 2.6: "Every resource named in the URL path exists, validated left to
    right, so the leftmost unresolvable identifier is the one reported. Depending
    on which identifier failed, the response is `ERR_SEASON_NOT_FOUND`,
    `ERR_VENUE_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_CONCERT_NOT_FOUND`,
    `ERR_CONTRACT_NOT_FOUND`, `ERR_MUSICIAN_NOT_FOUND`, `ERR_SERVICE_NOT_FOUND`,
    `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_PATRON_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_TICKET_ORDER_NOT_FOUND` or
    `ERR_AD_BOOKING_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/unknown_id_on_catalogue_reads_returns_entity_specific_not_found
    """
    set_clock("2026-09-01T00:00:00Z")

    cases = [
        (api.get_season(UNKNOWN_SEASON, ARTISTIC_ADMIN),
         ApiErrorId.ERR_SEASON_NOT_FOUND.value),
        (api.get_venue(UNKNOWN_VENUE, ARTISTIC_ADMIN),
         ApiErrorId.ERR_VENUE_NOT_FOUND.value),
        (api.get_section(UNKNOWN_SECTION, ARTISTIC_ADMIN),
         ApiErrorId.ERR_SECTION_NOT_FOUND.value),
        (api.get_concert(UNKNOWN_CONCERT, ARTISTIC_ADMIN),
         ApiErrorId.ERR_CONCERT_NOT_FOUND.value),
        (api.get_guest_contract(UNKNOWN_CONTRACT, ARTISTIC_ADMIN),
         ApiErrorId.ERR_CONTRACT_NOT_FOUND.value),
        (api.get_musician(UNKNOWN_MUSICIAN, ORCHESTRA_MANAGER),
         ApiErrorId.ERR_MUSICIAN_NOT_FOUND.value),
    ]
    for response, expected in cases:
        error = validate_error(response, expected, 404)
        assert response.json()["response_type"] == "error"
        assert error["message"].strip(), "every error carries a human-readable message"


def test_unknown_ids_on_transaction_reads_report_their_own_not_found_code(api):
    """PRD 2.6: "Every resource named in the URL path exists, validated left to
    right, so the leftmost unresolvable identifier is the one reported. Depending
    on which identifier failed, the response is `ERR_SEASON_NOT_FOUND`,
    `ERR_VENUE_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_CONCERT_NOT_FOUND`,
    `ERR_CONTRACT_NOT_FOUND`, `ERR_MUSICIAN_NOT_FOUND`, `ERR_SERVICE_NOT_FOUND`,
    `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_PATRON_NOT_FOUND`,
    `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_TICKET_ORDER_NOT_FOUND` or
    `ERR_AD_BOOKING_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/unknown_id_on_transaction_reads_returns_entity_specific_not_found
    """
    set_clock("2026-09-01T00:00:00Z", BOX_OFFICE)

    cases = [
        (api.get_rehearsal(UNKNOWN_SERVICE, ORCHESTRA_MANAGER),
         ApiErrorId.ERR_SERVICE_NOT_FOUND.value),
        (api.get_engagement(UNKNOWN_ENGAGEMENT, ORCHESTRA_MANAGER),
         ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND.value),
        (api.get_patron(UNKNOWN_PATRON, BOX_OFFICE),
         ApiErrorId.ERR_PATRON_NOT_FOUND.value),
        (api.get_subscription(UNKNOWN_SUBSCRIPTION, BOX_OFFICE),
         ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND.value),
        (api.get_ticket_order(UNKNOWN_ORDER, BOX_OFFICE),
         ApiErrorId.ERR_TICKET_ORDER_NOT_FOUND.value),
        (api.get_ad_booking(UNKNOWN_BOOKING, ADVERTISING_SALES),
         ApiErrorId.ERR_AD_BOOKING_NOT_FOUND.value),
    ]
    for response, expected in cases:
        validate_error(response, expected, 404)


def test_unresolvable_body_foreign_key_reports_the_referenced_entity(api):
    """PRD 2.6: "Every foreign key supplied in the request body resolves to an
    existing row — `season_id`, `venue_id`, `concert_id`, `seat_section_id`,
    `patron_id`, `musician_id`, `contract_id`, and every element of `concert_ids`.
    The applicable error is `ERR_SEASON_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`,
    `ERR_CONCERT_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_PATRON_NOT_FOUND`,
    `ERR_MUSICIAN_NOT_FOUND` or `ERR_CONTRACT_NOT_FOUND`, with HTTP 404."

    Design: Corner/errors/create_concert_with_unknown_season_returns_season_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    venue = create_venue(name="Grand Hall")

    response = api.create_concert(
        {
            "season_id": "00000000-0000-4000-8000-0000000000ff",
            "venue_id": venue["id"],
            "title": "Ghost",
            "performance_start_utc": "2026-11-05T19:30:00Z",
            "performance_end_utc": "2026-11-05T21:30:00Z",
            "program_minutes": 100,
        },
        ARTISTIC_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_SEASON_NOT_FOUND.value, 404)
