"""When the harbor shuts: Cascade A, service interruptions and refund claims."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_refund_claim,
    assert_ride_credit_conservation,
    assert_service_interruption,
    board_trip,
    buy_ride_pass,
    claim_for_booking,
    claims_for_interruption,
    create_confirmed_booking,
    create_trip,
    decide_claim,
    declare_interruption,
    make_fare_auditor_headers,
    patch_service_day,
    request_booking,
    reserve_dock_slot,
    setup_harbor_world,
    suspend_day,
    validate_error,
    validate_paginated,
    validate_success,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
AUDITOR = TEST_USERS["fare_auditor_headers"]
AUDITOR_ALT = TEST_USERS["fare_auditor_alt_headers"]
RIDER = TEST_USERS["rider_headers"]
RIDER_BOB = TEST_USERS["rider_bob_headers"]


def test_boarding_a_sailing_the_cascade_cancelled_is_refused(api):
    """PRD §3.9: "The first link cancels the trip itself: `operational_status` moves
    `SCHEDULED → CANCELLED` or `BOARDING → CANCELLED`, `settlement_status` moves
    `UNSETTLED → VOID`, and `cancellation_reason` is stamped with the exact string
    `POSTURE_SUSPENDED`."
    PRD §3.7: "The trip must be `SCHEDULED`, else `ERR_TRIP_NOT_SCHEDULED`, and the
    day's `posture` must not be `SUSPENDED`, else `ERR_SERVICE_SUSPENDED`."

    Design: Corner/state_machines/board_a_trip_cancelled_by_the_posture_cascade_returns_trip_not_scheduled
    """
    world = setup_harbor_world()
    trip = create_trip(world)
    suspend_day(world["day_id"], manual_suspension=True)

    validate_error(
        api.board_trip(trip["id"], {"boarded_booking_ids": []}, world["master_headers"]),
        ApiErrorId.ERR_TRIP_NOT_SCHEDULED.value, 409,
    )

    cancelled = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert cancelled["operational_status"] == "CANCELLED"
    assert cancelled["settlement_status"] == "VOID"
    assert cancelled["boarded_pax"] == 0


def test_a_never_offered_booking_survives_the_cascade_untouched(api):
    """PRD §3.9: "A booking is eligible when its `status` is `INTERRUPTED`, when the
    trip it names sits on this operating day, and when no claim already exists for it
    — so declaring twice on the same day does not double-pay."
    PRD §3.9: "Bookings still in `REQUESTED`, never having been offered a trip, are
    not eligible and receive no claim at all."

    Design: Corner/state_machines/posture_cascade_leaves_a_never_offered_booking_in_requested
    """
    world = setup_harbor_world()
    trip = create_trip(world)
    booking = request_booking(world, "rider-ann", party_size=2)
    suspend_day(world["day_id"], manual_suspension=True)

    interruption = declare_interruption(world["day_id"], "WEATHER")

    assert_service_interruption(interruption)
    assert validate_success(
        api.get_trip(trip["id"], DISPATCHER)
    )["operational_status"] == "CANCELLED"
    untouched = validate_success(api.get_booking(booking["id"], RIDER))
    assert untouched["status"] == "REQUESTED"
    assert untouched["interrupted_from_status"] is None
    assert untouched["version"] == booking["version"]
    assert interruption["affected_booking_count"] == 0
    assert interruption["total_provisional_refund_cents"] == 0
    assert interruption["status"] == "DECLARED"
    _claims, meta = validate_paginated(
        api.list_refund_claims(AUDITOR, params={"booking_id": booking["id"]})
    )
    assert meta["total_count"] == 0


def _cash_claim_world():
    """One cash booking of 1450 cents, interrupted by a suspension and claimed."""
    world = setup_harbor_world(
        service_day={"service_date": "2026-09-13", "wind_knots": 10.0,
                     "wave_height_m": 0.30, "low_water_m": 2.10},
        clock="2026-09-13T13:00:00Z",
    )
    create_trip(world, scheduled_departure_utc="2026-09-13T14:00:00Z",
                scheduled_arrival_utc="2026-09-13T14:25:00Z")
    booking = create_confirmed_booking(world, "rider-bob", party_size=2,
                                       requested_date="2026-09-13")
    suspend_day(world["day_id"], manual_suspension=True)
    interruption = declare_interruption(world["day_id"], "WEATHER")
    claim = claim_for_booking(booking["id"])
    return world, booking, interruption, claim


def test_approving_a_claim_pays_the_buckets_and_resolves_the_interruption(api):
    """PRD §3.9: "An approval moves the claim `OPEN → APPROVED`, stamps
    `approver_user_id` with the acting user, and writes the two buckets onto the
    booking — `fare_refunded_cents` takes the claim's `cash_refund_cents` and
    `credit_refunded_cents` takes the claim's `credit_refund_cents` — incrementing
    both the claim's `version` and the booking's `version` by 1."
    PRD §3.9: "Disbursement then completes inside the very same request, moving the
    claim `APPROVED → PAID` and incrementing the claim's `version` by 1 again."
    PRD §3.9: "Once the interruption has at least one claim and no claim of that
    interruption remains `OPEN`, the interruption bubbles up `DECLARED → RESOLVED` and
    its `version` increments by 1."

    Design: Corner/state_machines/refund_claim_approval_pays_the_buckets_and_bubbles_the_interruption_to_resolved
    """
    _world, booking, interruption, claim = _cash_claim_world()

    paid = decide_claim(claim["id"], "APPROVE")

    assert_refund_claim(paid)
    assert paid["status"] == "PAID", (
        f"Disbursement completes inside the same request, got {paid['status']}"
    )
    assert paid["approver_user_id"] == "aud-1"
    assert paid["declarer_user_id"] == "disp-1"
    assert paid["entitlement_cents"] == 1450
    assert paid["cash_refund_cents"] == 1450
    assert paid["credit_refund_cents"] == 0
    assert paid["ride_restored"] is False

    refunded_booking = validate_success(api.get_booking(booking["id"], RIDER_BOB))
    assert refunded_booking["fare_refunded_cents"] == 1450
    assert refunded_booking["credit_refunded_cents"] == 0

    resolved = validate_success(
        api.get_service_day(interruption["service_day_id"], DISPATCHER)
    )
    assert resolved["posture"] == "SUSPENDED"
    interruptions, _meta = validate_paginated(
        api.list_interruptions(interruption["service_day_id"], DISPATCHER)
    )
    assert interruptions[0]["status"] == "RESOLVED", (
        f"No OPEN claim remains, so the interruption must bubble up, got "
        f"{interruptions[0]['status']}"
    )


def test_deciding_a_claim_that_is_already_paid_is_refused(api):
    """PRD §3.9: "The claim must be `OPEN`, else `ERR_REFUND_CLAIM_NOT_OPEN`, and the
    acting `X-User-ID` must differ from the claim's `declarer_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES`; approval additionally requires the owning
    interruption to still be `DECLARED`."
    PRD §3.9: "`PAID` and `DENIED` are both terminal."

    Design: Corner/errors/approving_a_claim_that_is_already_paid_returns_refund_claim_not_open
    """
    _world, booking, _interruption, claim = _cash_claim_world()
    decide_claim(claim["id"], "APPROVE")

    validate_error(api.approve_refund_claim(claim["id"], {"decision": "DENY"},
                                            AUDITOR_ALT),
                   ApiErrorId.ERR_REFUND_CLAIM_NOT_OPEN.value, 409)

    unchanged = validate_success(api.get_refund_claim(claim["id"], AUDITOR))
    assert unchanged["status"] == "PAID"
    assert unchanged["approver_user_id"] == "aud-1", (
        f"The refused decision must not restamp the approver, got "
        f"{unchanged['approver_user_id']}"
    )
    assert validate_success(
        api.get_booking(booking["id"], RIDER_BOB)
    )["fare_refunded_cents"] == 1450


def test_the_declaring_dispatcher_may_not_decide_the_claim(api):
    """PRD §2.1: "The `Dispatcher` who declares a service interruption may never be
    the `FareAuditor` who decides a claim that interruption created; the comparison is
    between the acting `X-User-ID` and the claim's `declarer_user_id`, and a match is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.9: "Each claim records `booking_id` and `service_interruption_id`, copies
    the interruption's declaring user into `declarer_user_id` as the
    segregation-of-duties comparand, leaves `approver_user_id` null, and starts in
    `OPEN`; the other three claim statuses are `APPROVED`, `PAID`, and `DENIED`."

    Design: Corner/rbac/the_dispatcher_who_declared_the_interruption_cannot_decide_its_refund_claim
    """
    _world, booking, _interruption, claim = _cash_claim_world()

    validate_error(
        api.approve_refund_claim(claim["id"], {"decision": "APPROVE"},
                                 make_fare_auditor_headers("disp-1")),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403,
    )

    paid = decide_claim(claim["id"], "APPROVE")
    assert paid["status"] == "PAID"
    assert paid["approver_user_id"] == "aud-1"
    assert validate_success(
        api.get_booking(booking["id"], RIDER_BOB)
    )["fare_refunded_cents"] == 1450


def test_entitlement_above_the_cash_ceiling_overflows_into_harbor_credit(api):
    """PRD §3.9: "Otherwise `ride_restored` is false and the entitlement flows through
    two ordered money buckets: `cash_refund_cents` takes the entitlement up to a cash
    ceiling of 5000 cents, taking whichever is smaller, and `credit_refund_cents`
    receives everything the cash bucket could not absorb, namely the entitlement less
    the cash bucket."
    PRD §3.9: "Once every claim is written, the interruption's
    `affected_booking_count` is set to the number of claims created and its
    `total_provisional_refund_cents` to the sum of `entitlement_cents` across them."

    Design: Corner/calculations/interruption_refund_caps_the_cash_bucket_at_5000_and_overflows_into_harbor_credit
    """
    world = setup_harbor_world(
        service_day={"service_date": "2026-09-13", "wind_knots": 10.0,
                     "wave_height_m": 0.30, "low_water_m": 2.10},
        clock="2026-09-13T13:00:00Z",
        extra_stops_on_dock_b=[{"name": "Outer Point", "zone_index": 4,
                                "charted_depth_m": 5.50}],
    )
    outer_stop = world["extra_stops"][0]
    create_trip(world, destination_stop_id=outer_stop["id"],
                scheduled_departure_utc="2026-09-13T14:00:00Z",
                scheduled_arrival_utc="2026-09-13T14:40:00Z")
    booking = create_confirmed_booking(world, "rider-ann", party_size=4,
                                       destination_stop_id=outer_stop["id"],
                                       requested_date="2026-09-13")
    suspend_day(world["day_id"], manual_suspension=True)

    interruption = declare_interruption(world["day_id"], "WEATHER")
    claims = claims_for_interruption(interruption["id"])

    assert booking["fare_quoted_cents"] == 5100, (
        f"(450 + 3 x 275) x 4 seats = 5100, got {booking['fare_quoted_cents']}"
    )
    assert booking["fare_charged_cents"] == 5100
    assert len(claims) == 1
    claim = claims[0]
    assert claim["entitlement_cents"] == 5100
    assert claim["cash_refund_cents"] == 5000, (
        f"The cash bucket is capped at 5000, got {claim['cash_refund_cents']}"
    )
    assert claim["credit_refund_cents"] == 100
    assert claim["ride_restored"] is False
    assert claim["status"] == "OPEN"
    assert interruption["total_provisional_refund_cents"] == 5100


def test_a_booking_interrupted_from_boarded_receives_half_the_fare(api):
    """PRD §3.9: "A booking interrupted from `BOARDED` — a rider who got part of the
    way — is entitled to a partial-leg share of 5000 basis points, that is half of its
    `fare_charged_cents`, multiplied out and rounded half up to whole cents."
    PRD §3.9: "When the trip was cancelled out of `BOARDING`, its `boarded_pax` is
    deliberately left at the value boarding gave it, so the audit trail of who was on
    board survives the cancellation."

    Design: Corner/calculations/a_booking_interrupted_from_boarded_receives_only_the_half_partial_leg_entitlement
    """
    world = setup_harbor_world(
        service_day={"service_date": "2026-09-13", "wind_knots": 10.0,
                     "wave_height_m": 0.30, "low_water_m": 2.10},
        clock="2026-09-13T13:00:00Z",
    )
    trip = create_trip(world, scheduled_departure_utc="2026-09-13T14:00:00Z",
                       scheduled_arrival_utc="2026-09-13T14:25:00Z")
    booking = create_confirmed_booking(world, "rider-bob", party_size=2,
                                       requested_date="2026-09-13")
    board_trip(world, trip["id"], [booking["id"]])
    suspend_day(world["day_id"], manual_suspension=True)

    interruption = declare_interruption(world["day_id"], "WEATHER")
    claim = claims_for_interruption(interruption["id"])[0]

    interrupted = validate_success(api.get_booking(booking["id"], RIDER_BOB))
    assert interrupted["interrupted_from_status"] == "BOARDED"
    assert interrupted["status"] == "INTERRUPTED"
    cancelled = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert cancelled["operational_status"] == "CANCELLED"
    assert cancelled["boarded_pax"] == 2, (
        f"The boarding audit trail survives cancellation, got {cancelled['boarded_pax']}"
    )
    assert claim["entitlement_cents"] == 725, (
        f"Half of 1450 cents is 725, got {claim['entitlement_cents']}"
    )
    assert claim["cash_refund_cents"] == 725
    assert claim["credit_refund_cents"] == 0


def test_every_cascade_effect_is_readable_as_soon_as_the_patch_returns(api):
    """PRD §2.10: "**Cascade A** is the suspension cascade. It fires when an operating
    day's `posture` is recomputed to `SUSPENDED`, and it works through every
    non-terminal trip on that day in ascending `scheduled_departure_utc`, ties broken
    by ascending `created_at`."
    PRD §3.9: "The second link voids the berths: every slot of that trip whose
    `status` is `RESERVED` moves `RESERVED → VOIDED` with `projected_fee_cents` and
    `landing_fee_cents` both 0, and where a provisional amount had already been posted
    it is subtracted back out of the dock's `accrued_fee_cents`."

    Design: Corner/consistency_model/every_cascade_effect_is_readable_immediately_after_the_patch_returns
    """
    world = setup_harbor_world()
    trip = create_trip(world)
    slot = reserve_dock_slot(trip["id"], world["dock_a_id"],
                             "2026-09-12T14:00:00Z", "2026-09-12T14:20:00Z")

    patched = patch_service_day(world["day_id"], manual_suspension=True)
    assert patched["posture"] == "SUSPENDED"

    cancelled = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert cancelled["operational_status"] == "CANCELLED"
    assert cancelled["settlement_status"] == "VOID"
    voided = validate_success(api.get_dock_slot(slot["id"], DISPATCHER))
    assert voided["status"] == "VOIDED"
    dock = validate_success(api.get_dock(world["dock_a_id"], DISPATCHER))
    assert dock["accrued_fee_cents"] == 0


def _suspension_cascade_world(rides_purchased=2, purchase_price_cents=4000,
                              party_size=2, with_slot=True):
    """A confirmed pass booking on a sailing whose day is about to be suspended."""
    world = setup_harbor_world(
        service_day={"service_date": "2026-09-13", "wind_knots": 10.0,
                     "wave_height_m": 0.30, "low_water_m": 2.10},
        clock="2026-09-13T08:00:00Z",
    )
    trip = create_trip(world, scheduled_departure_utc="2026-09-13T10:00:00Z",
                       scheduled_arrival_utc="2026-09-13T10:25:00Z")
    slot = None
    if with_slot:
        slot = reserve_dock_slot(trip["id"], world["dock_a_id"],
                                 "2026-09-13T10:00:00Z", "2026-09-13T10:20:00Z")
    ride_pass = buy_ride_pass("rider-ann", zone_tier="INNER",
                              rides_purchased=rides_purchased,
                              purchase_price_cents=purchase_price_cents,
                              valid_until="2026-12-31")
    booking = create_confirmed_booking(world, "rider-ann", party_size=party_size,
                                       ride_pass_id=ride_pass["id"],
                                       requested_date="2026-09-13")
    return world, trip, slot, ride_pass, booking


def test_suspension_cancels_the_sailing_and_voids_its_berth(api):
    """PRD §3.9: "The first link cancels the trip itself: `operational_status` moves
    `SCHEDULED → CANCELLED` or `BOARDING → CANCELLED`, `settlement_status` moves
    `UNSETTLED → VOID`, and `cancellation_reason` is stamped with the exact string
    `POSTURE_SUSPENDED`."
    PRD §3.9: "The second link voids the berths: every slot of that trip whose
    `status` is `RESERVED` moves `RESERVED → VOIDED` with `projected_fee_cents` and
    `landing_fee_cents` both 0, and where a provisional amount had already been posted
    it is subtracted back out of the dock's `accrued_fee_cents`."

    Design: Difficulty/transitive_cascade/suspension_cascade_day_to_trip_to_booking_to_ride_pass_depth_four
    """
    world, trip, slot, _ride_pass, _booking = _suspension_cascade_world()

    patched = patch_service_day(world["day_id"], wind_knots=40.0)
    assert patched["posture"] == "SUSPENDED"

    cancelled = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert cancelled["operational_status"] == "CANCELLED"
    assert cancelled["settlement_status"] == "VOID"
    assert cancelled["cancellation_reason"] == "POSTURE_SUSPENDED"
    assert cancelled["seats_committed"] == 0

    voided = validate_success(api.get_dock_slot(slot["id"], DISPATCHER))
    assert voided["status"] == "VOIDED"
    assert voided["projected_fee_cents"] == 0
    assert voided["landing_fee_cents"] == 0
    dock = validate_success(api.get_dock(world["dock_a_id"], DISPATCHER))
    assert dock["accrued_fee_cents"] == 0


def test_suspension_interrupts_the_booking_and_revives_its_exhausted_pass(api):
    """PRD §3.9: "In the same link, every booking on the trip whose `status` is
    `OFFERED`, `CONFIRMED`, or `BOARDED` is interrupted — `OFFERED → INTERRUPTED`,
    `CONFIRMED → INTERRUPTED`, or `BOARDED → INTERRUPTED` respectively; the status it
    held immediately beforehand is stamped into `interrupted_from_status`, which may
    therefore be `OFFERED`, `CONFIRMED`, or `BOARDED`; and the booking's `trip_id` is
    retained rather than cleared, because the claim lookup later needs it."
    PRD §3.9: "When an interrupted booking's `redemption_status` was `REDEEMED`, its
    pass gets `rides_remaining` increased by the booking's `party_size`, the booking's
    `redemption_status` becomes `RESTORED`, a pass sitting in `EXHAUSTED` returns
    `EXHAUSTED → ACTIVE`, and both the booking's `version` and the pass's `version`
    increment by 1."

    Design: Difficulty/transitive_cascade/suspension_cascade_day_to_trip_to_booking_to_ride_pass_depth_four
    """
    world, _trip, _slot, ride_pass, booking = _suspension_cascade_world()

    patch_service_day(world["day_id"], wind_knots=40.0)

    interrupted = validate_success(api.get_booking(booking["id"], RIDER))
    assert interrupted["status"] == "INTERRUPTED"
    assert interrupted["interrupted_from_status"] == "CONFIRMED"
    assert interrupted["redemption_status"] == "RESTORED"

    revived = validate_success(api.get_ride_pass(ride_pass["id"], RIDER))
    assert revived["rides_remaining"] == 2, (
        f"Both redeemed rides must come back, got {revived['rides_remaining']}"
    )
    assert revived["rides_consumed"] == 0, (
        f"A RESTORED booking is not consumed, got {revived['rides_consumed']}"
    )
    assert revived["status"] == "ACTIVE", (
        f"An EXHAUSTED pass returns to ACTIVE, got {revived['status']}"
    )


def _cash_booking_on_a_normal_day():
    """A confirmed 1450-cent cash booking on a day that is still operable."""
    world = setup_harbor_world(
        service_day={"service_date": "2026-09-13", "wind_knots": 10.0,
                     "wave_height_m": 0.30, "low_water_m": 2.10},
        clock="2026-09-13T08:00:00Z",
    )
    create_trip(world, scheduled_departure_utc="2026-09-13T10:00:00Z",
                scheduled_arrival_utc="2026-09-13T10:25:00Z")
    booking = create_confirmed_booking(world, "rider-bob", party_size=2,
                                       requested_date="2026-09-13")
    return world, booking


def test_declaring_an_interruption_on_an_operable_day_is_refused(api):
    """PRD §3.9: "The day's `posture` must be `SUSPENDED` at that moment, else the
    declaration is refused with `ERR_INTERRUPTION_NOT_DECLARABLE`."
    PRD §3.9: "Cancellation alone pays nobody."

    Design: Difficulty/cross_entity_state_dependency/interruption_declaration_requires_the_service_day_to_be_suspended_first
    """
    world, _booking = _cash_booking_on_a_normal_day()

    validate_error(api.create_interruption(world["day_id"], {"cause": "WEATHER"},
                                           DISPATCHER),
                   ApiErrorId.ERR_INTERRUPTION_NOT_DECLARABLE.value, 409)

    _interruptions, meta = validate_paginated(
        api.list_interruptions(world["day_id"], DISPATCHER)
    )
    assert meta["total_count"] == 0, (
        f"A refused declaration must not be persisted, got {meta['total_count']}"
    )


def test_the_same_declaration_succeeds_once_the_day_is_suspended(api):
    """PRD §3.9: "The interruption records `service_day_id` from the day addressed,
    stamps `declared_by_user_id` from the acting `X-User-ID`, and starts in
    `DECLARED`, the only other status being `RESOLVED`."
    PRD §3.9: "Once every claim is written, the interruption's
    `affected_booking_count` is set to the number of claims created and its
    `total_provisional_refund_cents` to the sum of `entitlement_cents` across them."

    Design: Difficulty/cross_entity_state_dependency/interruption_declaration_requires_the_service_day_to_be_suspended_first
    """
    world, booking = _cash_booking_on_a_normal_day()
    validate_error(api.create_interruption(world["day_id"], {"cause": "WEATHER"},
                                           DISPATCHER),
                   ApiErrorId.ERR_INTERRUPTION_NOT_DECLARABLE.value, 409)

    patched = patch_service_day(world["day_id"], wind_knots=40.0)
    assert patched["posture"] == "SUSPENDED"

    interruption = declare_interruption(world["day_id"], "WEATHER")

    interrupted = validate_success(api.get_booking(booking["id"], RIDER_BOB))
    assert interrupted["status"] == "INTERRUPTED"
    assert interrupted["fare_charged_cents"] == 1450
    assert interruption["status"] == "DECLARED"
    assert interruption["affected_booking_count"] == 1
    assert interruption["total_provisional_refund_cents"] == 1450
    assert interruption["declared_by_user_id"] == "disp-1"


def test_restored_rides_leave_the_pass_balance_whole(api):
    """PRD §2.9: "**Ride credits on a pass.** A pass's `rides_purchased` always equals
    its `rides_remaining` plus the sum of `party_size` over every booking that names
    that pass in `ride_pass_id` and whose `redemption_status` is `REDEEMED`."
    PRD §2.9: "A `RESTORED` booking must not be counted in that sum — counting it
    silently loses a ride."

    Design: Difficulty/compensating_invariant/ride_credit_conservation_survives_redeem_then_interruption_restore
    """
    world, _trip, _slot, ride_pass, _booking = _suspension_cascade_world(
        rides_purchased=5, purchase_price_cents=5000, party_size=2, with_slot=False
    )

    patched = patch_service_day(world["day_id"], manual_suspension=True)
    assert patched["posture"] == "SUSPENDED"

    restored = validate_success(api.get_ride_pass(ride_pass["id"], RIDER))
    assert restored["rides_purchased"] == 5
    assert restored["rides_remaining"] == 5, (
        f"The two redeemed rides must be handed back, got {restored['rides_remaining']}"
    )
    assert restored["rides_consumed"] == 0
    assert restored["status"] == "ACTIVE"
    assert_ride_credit_conservation(api, ride_pass["id"], RIDER)


def test_the_restoring_cascade_also_frees_the_seats_and_the_fare(api):
    """PRD §3.9: "When an interrupted booking's `redemption_status` was `REDEEMED`,
    its pass gets `rides_remaining` increased by the booking's `party_size`, the
    booking's `redemption_status` becomes `RESTORED`, a pass sitting in `EXHAUSTED`
    returns `EXHAUSTED → ACTIVE`, and both the booking's `version` and the pass's
    `version` increment by 1."
    PRD §3.9: "The trip's `seats_committed` is recomputed to 0 and its `version`
    increments by 1."

    Design: Difficulty/compensating_invariant/ride_credit_conservation_survives_redeem_then_interruption_restore
    """
    world, trip, _slot, _ride_pass, booking = _suspension_cascade_world(
        rides_purchased=5, purchase_price_cents=5000, party_size=2, with_slot=False
    )

    patch_service_day(world["day_id"], manual_suspension=True)

    interrupted = validate_success(api.get_booking(booking["id"], RIDER))
    assert interrupted["redemption_status"] == "RESTORED"
    assert interrupted["status"] == "INTERRUPTED"
    assert interrupted["fare_charged_cents"] == 0, (
        f"A pass booking is paid in kind, got {interrupted['fare_charged_cents']}"
    )
    cancelled = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert cancelled["seats_committed"] == 0
