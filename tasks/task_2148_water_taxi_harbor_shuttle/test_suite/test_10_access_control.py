"""Authentication, role remits, ownership and the domain-specific not-found codes."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_crew_member,
    board_trip,
    create_dock_payload,
    create_inspection_payload,
    create_offered_booking,
    create_trip,
    create_trip_payload,
    make_vessel_master_headers,
    setup_harbor_world,
    validate_error,
    validate_paginated,
    validate_success,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
RIDER = TEST_USERS["rider_headers"]
RIDER_BOB = TEST_USERS["rider_bob_headers"]
AUDITOR = TEST_USERS["fare_auditor_headers"]
INSPECTOR = TEST_USERS["marine_inspector_headers"]

NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def test_roles_are_confined_to_their_own_remit(api):
    """PRD §2.1: "Once the acting role is known, it is matched against the roles
    authorised for the endpoint in §4; a role acting outside its remit is rejected
    with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.8: "**Role authorisation.** The acting role appears in the endpoint's
    authorised list in §4 — otherwise `ERR_FORBIDDEN_ROLE` (403)."

    Design: Corner/rbac/rider_cannot_create_a_trip_and_dispatcher_cannot_depart_one
    """
    world = setup_harbor_world()
    trip = create_trip(world)
    board_trip(world, trip["id"], [])

    validate_error(
        api.create_trip(
            create_trip_payload(world["day_id"], world["vessel_id"], world["crew_id"],
                                world["stop1_id"], world["stop2_id"],
                                scheduled_departure_utc="2026-09-12T18:00:00Z",
                                scheduled_arrival_utc="2026-09-12T18:25:00Z"),
            RIDER),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403,
    )
    validate_error(api.depart_trip(trip["id"], DISPATCHER),
                   ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    refreshed = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert refreshed["operational_status"] == "BOARDING", (
        f"The refused departure must not move the trip, got "
        f"{refreshed['operational_status']}"
    )
    _trips, meta = validate_paginated(
        api.list_trips(DISPATCHER, params={"service_day_id": world["day_id"]})
    )
    assert meta["total_count"] == 1


def test_only_the_trips_own_master_may_open_boarding(api):
    """PRD §2.1: "When `X-User-Role` is `VesselMaster`, `X-User-ID` is the `id` of the
    acting `CrewMember`; ownership checks on any resource that references a
    `CrewMember` compare the resource's foreign-key field to `X-User-ID`, which in
    practice means a boarding, departure or completion request is honoured only when
    `X-User-ID` equals the trip's `master_crew_id`."
    PRD §2.1: "Any ownership mismatch, whether on a rider resource or on a master's
    trip, yields `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/a_crew_member_who_is_not_the_trip_master_cannot_board_it
    """
    world = setup_harbor_world()
    trip = create_trip(world)
    other_master = add_crew_member(name="L. Vance", endorsement_class="MASTER_100T")

    validate_error(
        api.board_trip(trip["id"], {"boarded_booking_ids": []},
                       make_vessel_master_headers(other_master["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403,
    )

    assert validate_success(
        api.get_trip(trip["id"], DISPATCHER)
    )["operational_status"] == "SCHEDULED"
    assert validate_success(
        api.get_crew_member(other_master["id"], DISPATCHER)
    )["trips_mastered_count"] == 0


def test_a_rider_cannot_decline_another_riders_booking(api):
    """PRD §3.6: "Declining is the cycle edge, and only the booking's owner may
    decline."
    PRD §2.8: "**Ownership.** For rider-owned resources the acting `X-User-ID` equals
    the booking's or pass's `rider_user_id`; for master actions it equals the trip's
    `master_crew_id` — otherwise `ERR_NOT_RESOURCE_OWNER` (403)."

    Design: Corner/rbac/a_rider_cannot_decline_a_booking_owned_by_another_rider
    """
    world = setup_harbor_world()
    create_trip(world)
    booking = create_offered_booking(world, "rider-ann", party_size=1)

    validate_error(api.decline_booking(booking["id"], RIDER_BOB),
                   ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    untouched = validate_success(api.get_booking(booking["id"], RIDER))
    assert untouched["status"] == "OFFERED"
    assert untouched["offer_round"] == 0
    assert untouched["declined_trip_ids"] == []


def test_a_request_without_auth_headers_is_rejected(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, declaring the capacity in which they are acting."
    PRD §2.1: "If either header is missing or empty, or if `X-User-Role` is not one of
    the six recognised role names, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/create_dock_with_missing_auth_headers_returns_unauthenticated
    """
    response = api.create_dock(
        create_dock_payload(name="Headerless", berth_count=1,
                            landing_fee_per_pax_cents=100, berth_minute_rate_cents=30,
                            monthly_fee_cap_cents=500_000),
        NO_AUTH_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_each_unknown_id_answers_its_own_domain_not_found_code(api):
    """PRD §2.8: "**Path resolution.** Every id embedded in the URL path resolves to
    an existing row, validated left to right, so an outer id that does not resolve is
    reported before any inner id is looked at."
    PRD §2.8: "The error is the one belonging to the missing resource type:
    `ERR_DOCK_NOT_FOUND`, `ERR_VESSEL_NOT_FOUND`, `ERR_SERVICE_DAY_NOT_FOUND`,
    `ERR_TRIP_NOT_FOUND`, `ERR_DOCK_SLOT_NOT_FOUND`, `ERR_RIDE_PASS_NOT_FOUND`,
    `ERR_BOOKING_NOT_FOUND`, `ERR_REFUND_CLAIM_NOT_FOUND`, or `ERR_CREW_NOT_FOUND`,
    each HTTP 404."

    Design: Corner/errors/unknown_ids_on_read_and_action_endpoints_answer_their_own_domain_not_found_codes
    """
    validate_error(
        api.dispatch_booking("00000000-0000-4000-8000-000000000001", DISPATCHER),
        ApiErrorId.ERR_BOOKING_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_ride_pass("00000000-0000-4000-8000-000000000002", RIDER),
        ApiErrorId.ERR_RIDE_PASS_NOT_FOUND.value, 404,
    )
    validate_error(
        api.get_dock_slot("00000000-0000-4000-8000-000000000003", DISPATCHER),
        ApiErrorId.ERR_DOCK_SLOT_NOT_FOUND.value, 404,
    )
    validate_error(
        api.approve_refund_claim("00000000-0000-4000-8000-000000000004",
                                 {"decision": "APPROVE"}, AUDITOR),
        ApiErrorId.ERR_REFUND_CLAIM_NOT_FOUND.value, 404,
    )
    validate_error(
        api.create_inspection("00000000-0000-4000-8000-000000000005",
                              create_inspection_payload(), INSPECTOR),
        ApiErrorId.ERR_VESSEL_NOT_FOUND.value, 404,
    )
