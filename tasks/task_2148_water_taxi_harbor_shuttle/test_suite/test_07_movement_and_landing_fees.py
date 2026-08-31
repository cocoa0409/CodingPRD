"""Boarding, sailing and arrival — and the landing fees the movement posts."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_dock_fee_conservation,
    assert_trip,
    board_trip,
    complete_trip,
    create_confirmed_booking,
    create_trip,
    depart_trip,
    reserve_dock_slot,
    set_clock,
    setup_harbor_world,
    validate_error,
    validate_success,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
RIDER = TEST_USERS["rider_headers"]


def test_departing_a_sailing_that_never_opened_boarding_is_refused(api):
    """PRD §3.7: "The trip must be `BOARDING`, else `ERR_TRIP_NOT_BOARDING`."
    PRD §3.3: "A newly created trip is `SCHEDULED` on its movement axis and
    `UNSETTLED` on its money axis, with `seats_committed` at 0, `booked_pax` and
    `boarded_pax` at 0, `provisional_fee_cents` and `final_fee_cents` at 0,
    `actual_departure_utc` and `actual_arrival_utc` null, and `cancellation_reason`
    null."

    Design: Corner/state_machines/depart_directly_from_scheduled_returns_trip_not_boarding
    """
    world = setup_harbor_world()
    trip = create_trip(world)

    validate_error(api.depart_trip(trip["id"], world["master_headers"]),
                   ApiErrorId.ERR_TRIP_NOT_BOARDING.value, 409)

    refreshed = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert refreshed["operational_status"] == "SCHEDULED"
    assert refreshed["settlement_status"] == "UNSETTLED"
    assert refreshed["actual_departure_utc"] is None


def test_completing_an_already_completed_sailing_is_refused(api):
    """PRD §3.7: "The trip must be `DEPARTED`, else `ERR_TRIP_NOT_DEPARTED`, and the
    logical clock must read strictly later than `actual_departure_utc`, else
    `ERR_INVALID_TIME_WINDOW`."
    PRD §3.7: "The sum of those final amounts becomes the trip's `final_fee_cents`;
    the money axis moves `PROVISIONAL → FINAL` and the movement axis
    `DEPARTED → COMPLETED`; every booking on the trip still in `BOARDED` moves
    `BOARDED → COMPLETED` with its `version` incremented by 1; the master's
    `trips_mastered_count` increments by 1; each dock touched has its `version`
    incremented by 1; and the trip's `version` increments by 1."

    Design: Corner/state_machines/completing_an_already_completed_trip_returns_trip_not_departed
    """
    world = setup_harbor_world()
    trip = create_trip(world)
    slot = reserve_dock_slot(trip["id"], world["dock_a_id"],
                             "2026-09-12T14:00:00Z", "2026-09-12T14:20:00Z")
    board_trip(world, trip["id"], [])
    set_clock("2026-09-12T14:35:00Z")
    depart_trip(world, trip["id"])
    set_clock("2026-09-12T14:50:00Z")
    complete_trip(world, trip["id"])

    validate_error(api.complete_trip(trip["id"], world["master_headers"]),
                   ApiErrorId.ERR_TRIP_NOT_DEPARTED.value, 409)

    settled_slot = validate_success(api.get_dock_slot(slot["id"], DISPATCHER))
    assert settled_slot["landing_fee_cents"] == 1400, (
        f"35 berth minutes x 40 cents with no passengers = 1400, got "
        f"{settled_slot['landing_fee_cents']}"
    )
    assert settled_slot["status"] == "CONSUMED"
    dock = validate_success(api.get_dock(world["dock_a_id"], DISPATCHER))
    assert dock["accrued_fee_cents"] == 1400
    crew = validate_success(api.get_crew_member(world["crew_id"], DISPATCHER))
    assert crew["trips_mastered_count"] == 1, (
        f"Completion advances the master's counter exactly once, got "
        f"{crew['trips_mastered_count']}"
    )


def test_layover_slot_bills_no_passengers(api):
    """PRD §3.8: "The **passenger basis** is 0 for any slot whose `purpose` is
    `LAYOVER` — a layover occupies a berth but lands nobody."
    PRD §3.8: "The **gross charge** is the berth minutes multiplied by the dock's
    `berth_minute_rate_cents`, plus the passenger basis multiplied by the dock's
    `landing_fee_per_pax_cents`."

    Design: Corner/calculations/layover_slot_bills_zero_passengers_while_the_trip_carries_three
    """
    world = setup_harbor_world()
    trip = create_trip(world)
    slot = reserve_dock_slot(trip["id"], world["dock_a_id"],
                             "2026-09-12T14:00:00Z", "2026-09-12T14:20:00Z",
                             purpose="LAYOVER")
    booking = create_confirmed_booking(world, "rider-ann", party_size=3)
    board_trip(world, trip["id"], [booking["id"]])
    set_clock("2026-09-12T14:35:00Z")

    departed = depart_trip(world, trip["id"])

    assert departed["booked_pax"] == 3
    posted = validate_success(api.get_dock_slot(slot["id"], DISPATCHER))
    assert posted["pax_basis"] == 0, (
        f"A LAYOVER lands nobody, got pax_basis {posted['pax_basis']}"
    )
    assert posted["berth_minutes"] == 20
    assert posted["projected_fee_cents"] == 800, (
        f"20 berth minutes x 40 cents with a zero passenger basis = 800, got "
        f"{posted['projected_fee_cents']}"
    )
    assert departed["provisional_fee_cents"] == 800
    dock = validate_success(api.get_dock(world["dock_a_id"], DISPATCHER))
    assert dock["accrued_fee_cents"] == 800


def _boarding_world():
    """A sailing with one reserved landing slot and one confirmed three-seat booking."""
    world = setup_harbor_world(clock="2026-09-12T13:30:00Z")
    trip = create_trip(world)
    slot = reserve_dock_slot(trip["id"], world["dock_a_id"],
                             "2026-09-12T14:00:00Z", "2026-09-12T14:20:00Z")
    booking = create_confirmed_booking(world, "rider-ann", party_size=3)
    return world, trip, slot, booking


def test_boarding_advances_the_movement_axis_only(api):
    """PRD §3.7: "On success the trip's `boarded_pax` is set to that total, each named
    booking moves `CONFIRMED → BOARDED` with its `version` incremented by 1,
    `seats_committed` is recomputed — `BOARDED` bookings still count towards it — the
    trip moves `SCHEDULED → BOARDING`, and the trip's `version` increments by 1."
    PRD §3.7: "Nothing on the money axis moves: `settlement_status` remains
    `UNSETTLED`."

    Design: Difficulty/non_linear_state_machine/trip_boarding_moves_movement_axis_while_settlement_axis_stays_unsettled
    """
    world, trip, _slot, booking = _boarding_world()

    boarded = board_trip(world, trip["id"], [booking["id"]])

    assert_trip(boarded)
    assert boarded["operational_status"] == "BOARDING"
    assert boarded["settlement_status"] == "UNSETTLED", (
        f"Opening boarding posts no money, got {boarded['settlement_status']}"
    )
    assert boarded["boarded_pax"] == 3
    assert boarded["booked_pax"] == 0, (
        f"booked_pax is only snapshotted at departure, got {boarded['booked_pax']}"
    )
    assert boarded["provisional_fee_cents"] == 0


def test_boarding_posts_nothing_on_the_reserved_berth(api):
    """PRD §3.3: "They are written by different clauses of the same operations, and
    `UNSETTLED` persists across the `SCHEDULED → BOARDING` move because opening
    boarding posts no money at all."
    PRD §3.4: "A slot that survives both checks is written in `RESERVED` status with
    `projected_fee_cents`, `landing_fee_cents`, `pax_basis`, `berth_minutes`, and
    `rebate_bp` all at 0, and the dock's `version` increments by 1 — which is
    precisely why a client holding an older `expected_dock_version` is turned away on
    the next attempt."

    Design: Difficulty/non_linear_state_machine/trip_boarding_moves_movement_axis_while_settlement_axis_stays_unsettled
    """
    world, trip, slot, booking = _boarding_world()

    board_trip(world, trip["id"], [booking["id"]])

    still_reserved = validate_success(api.get_dock_slot(slot["id"], DISPATCHER))
    assert still_reserved["status"] == "RESERVED"
    assert still_reserved["projected_fee_cents"] == 0, (
        f"Boarding must post no provisional fee, got "
        f"{still_reserved['projected_fee_cents']}"
    )
    assert validate_success(api.get_booking(booking["id"], RIDER))["status"] == "BOARDED"
    assert validate_success(api.get_trip(trip["id"], DISPATCHER))["seats_committed"] == 3


def _provisional_versus_final_world():
    """Five seats committed, three of them boarded, departing 35 minutes into a
    20-minute berth window."""
    world = setup_harbor_world(
        dock_a={"shared_operator_count": 2},
        service_day={"service_date": "2026-09-12", "wind_knots": 10.0,
                     "wave_height_m": 0.30, "low_water_m": 2.10,
                     "event_name": "Harbor Bowl", "expected_attendance": 18000},
        clock="2026-09-12T13:00:00Z",
    )
    trip = create_trip(world)
    slot = reserve_dock_slot(trip["id"], world["dock_a_id"],
                             "2026-09-12T14:00:00Z", "2026-09-12T14:20:00Z")
    first = create_confirmed_booking(world, "rider-ann", party_size=3)
    create_confirmed_booking(world, "rider-bob", party_size=2)
    board_trip(world, trip["id"], [first["id"]])
    set_clock("2026-09-12T14:35:00Z")
    departed = depart_trip(world, trip["id"])
    return world, trip, slot, departed, first


def test_provisional_posting_bills_the_committed_seats_over_the_reserved_window(api):
    """PRD §3.8: "Otherwise it is the trip's `booked_pax` in the provisional variant
    and the trip's `boarded_pax` in the final variant."
    PRD §3.8: "The **berth minutes** in the provisional variant are the whole minutes
    between the slot's `start_utc` and its `end_utc`, any fractional minute discarded
    downward."
    PRD §3.7: "A successful departure stamps `actual_departure_utc` from the logical
    clock, snapshots `booked_pax` from the trip's current `seats_committed` — this
    snapshot is the provisional passenger basis — and posts a provisional landing fee
    on every berth slot of the trip that is still `RESERVED`."

    Design: Difficulty/dual_variant_calc/dock_landing_fee_provisional_versus_final_diverges_on_pax_and_minutes
    """
    world, _trip, slot, departed, _booking = _provisional_versus_final_world()

    assert departed["booked_pax"] == 5, (
        f"Both confirmed bookings count towards the provisional basis, got "
        f"{departed['booked_pax']}"
    )
    assert departed["provisional_fee_cents"] == 1400, (
        f"20 minutes x 40 cents + 5 pax x 120 cents = 1400, got "
        f"{departed['provisional_fee_cents']}"
    )
    assert departed["settlement_status"] == "PROVISIONAL"

    posted = validate_success(api.get_dock_slot(slot["id"], DISPATCHER))
    assert posted["pax_basis"] == 5
    assert posted["berth_minutes"] == 20
    assert posted["projected_fee_cents"] == 1400
    assert posted["landing_fee_cents"] == 0, (
        f"The final fee stays 0 until the trip completes, got "
        f"{posted['landing_fee_cents']}"
    )
    dock = validate_success(api.get_dock(world["dock_a_id"], DISPATCHER))
    assert dock["accrued_fee_cents"] == 1400


def test_final_posting_bills_the_boarded_pax_over_the_real_berth_occupancy(api):
    """PRD §3.8: "In the final variant they run from the slot's `start_utc` to the
    trip's real `actual_departure_utc`, again floored to whole minutes, and never
    below 0 — so a boat that sat at the berth past its reserved window bills more
    minutes than it reserved, while one that left before its window opened bills none."
    PRD §3.7: "On success `actual_arrival_utc` is stamped from the clock and Cascade B
    runs: for each still-`RESERVED` slot of the trip, the slot's
    `projected_fee_cents` is first subtracted back out of the dock's
    `accrued_fee_cents` and reset to 0, then the final fee is computed and written to
    `landing_fee_cents` and the slot moves `RESERVED → CONSUMED`."

    Design: Difficulty/dual_variant_calc/dock_landing_fee_provisional_versus_final_diverges_on_pax_and_minutes
    """
    world, trip, slot, departed, _booking = _provisional_versus_final_world()
    set_clock("2026-09-12T14:50:00Z")

    completed = complete_trip(world, trip["id"])

    assert completed["boarded_pax"] == 3
    assert completed["provisional_fee_cents"] == 1400
    assert completed["final_fee_cents"] == 1760, (
        f"35 minutes x 40 cents + 3 pax x 120 cents = 1760, got "
        f"{completed['final_fee_cents']}"
    )
    assert completed["settlement_status"] == "FINAL"

    settled = validate_success(api.get_dock_slot(slot["id"], DISPATCHER))
    assert settled["berth_minutes"] == 35
    assert settled["pax_basis"] == 3
    assert settled["projected_fee_cents"] == 0, (
        f"The provisional amount must be reversed and reset, got "
        f"{settled['projected_fee_cents']}"
    )
    assert settled["landing_fee_cents"] == 1760
    assert settled["status"] == "CONSUMED"
    dock = validate_success(api.get_dock(world["dock_a_id"], DISPATCHER))
    assert dock["accrued_fee_cents"] == 1760, (
        f"The reversal must leave only the final amount accrued, got "
        f"{dock['accrued_fee_cents']}"
    )


def _rebate_tier_world():
    """A high-tariff berth where the first departure lifts the accrual into tier one."""
    world = setup_harbor_world(
        dock_b={"name": "Deepwater Berth", "berth_count": 2, "min_turnaround_minutes": 0,
                "landing_fee_per_pax_cents": 0, "berth_minute_rate_cents": 5000,
                "monthly_fee_cap_cents": 100_000_000},
        stop2={"name": "Deepwater Stop", "zone_index": 3, "charted_depth_m": 6.00},
    )
    first_trip = create_trip(world, scheduled_departure_utc="2026-09-12T14:00:00Z",
                             scheduled_arrival_utc="2026-09-12T15:10:00Z")
    first_slot = reserve_dock_slot(first_trip["id"], world["dock_b_id"],
                                   "2026-09-12T14:00:00Z", "2026-09-12T15:00:00Z")
    second_trip = create_trip(world, scheduled_departure_utc="2026-09-12T16:00:00Z",
                              scheduled_arrival_utc="2026-09-12T16:30:00Z")
    second_slot = reserve_dock_slot(second_trip["id"], world["dock_b_id"],
                                    "2026-09-12T16:00:00Z", "2026-09-12T16:20:00Z")
    board_trip(world, first_trip["id"], [])
    set_clock("2026-09-12T15:05:00Z")
    depart_trip(world, first_trip["id"])
    board_trip(world, second_trip["id"], [])
    set_clock("2026-09-12T16:05:00Z")
    return world, first_trip, first_slot, second_trip, second_slot


def test_first_posting_on_an_empty_dock_earns_no_rebate(api):
    """PRD §3.8: "Third, select the rebate from that pre-posting accrual alone, never
    from the value this posting is about to produce: if the slot's `rebate_bp` has
    already been pre-locked to 10000 by a cap flip on this dock the rebate stays
    10000; otherwise it is 1500 basis points when the pre-posting accrual is at least
    500000 cents, 800 basis points when it is at least 200000 cents but below 500000,
    and 0 otherwise."
    PRD §3.8: "In the **provisional** variant the fee is written to the slot's
    `projected_fee_cents`, added to the dock's accrual, and that is the end of it:
    `monthly_fee_cap_cents` is deliberately not evaluated on a provisional posting, so
    a provisional posting can push the accrual past the cap without flipping anything."

    Design: Difficulty/combinatorial_formula/dock_rebate_tier_keyed_on_pre_posting_accrual_not_post_posting
    """
    world, _first_trip, first_slot, _second_trip, _second_slot = _rebate_tier_world()

    posted = validate_success(api.get_dock_slot(first_slot["id"], DISPATCHER))
    assert posted["rebate_bp"] == 0, (
        f"A pre-posting accrual of 0 earns no rebate, got {posted['rebate_bp']}"
    )
    assert posted["projected_fee_cents"] == 300000, (
        f"60 berth minutes x 5000 cents = 300000, got {posted['projected_fee_cents']}"
    )
    dock = validate_success(api.get_dock(world["dock_b_id"], DISPATCHER))
    assert dock["accrued_fee_cents"] == 300000


def test_second_posting_reads_its_rebate_tier_from_the_pre_posting_accrual(api):
    """PRD §3.8: "The rebate looks circular — the tier is keyed on the dock's accrual,
    and the accrual is grown by the very fee the tier helps compute — so the
    evaluation order is pinned and must be followed exactly."
    PRD §3.8: "Third, select the rebate from that pre-posting accrual alone, never
    from the value this posting is about to produce: if the slot's `rebate_bp` has
    already been pre-locked to 10000 by a cap flip on this dock the rebate stays
    10000; otherwise it is 1500 basis points when the pre-posting accrual is at least
    500000 cents, 800 basis points when it is at least 200000 cents but below 500000,
    and 0 otherwise."
    PRD §3.8: "Fourth, compute the fee: multiply the gross charge by the rebate basis
    points, divide by 10000, round half up to whole cents, and subtract that rebate
    amount from the gross charge — a pre-locked rebate of 10000 basis points therefore
    yields a fee of exactly 0."

    Design: Difficulty/combinatorial_formula/dock_rebate_tier_keyed_on_pre_posting_accrual_not_post_posting
    """
    world, _first_trip, _first_slot, second_trip, second_slot = _rebate_tier_world()

    depart_trip(world, second_trip["id"])

    posted = validate_success(api.get_dock_slot(second_slot["id"], DISPATCHER))
    assert posted["berth_minutes"] == 20
    assert posted["rebate_bp"] == 800, (
        f"A pre-posting accrual of 300000 selects the 800 bp tier, got "
        f"{posted['rebate_bp']}"
    )
    assert posted["projected_fee_cents"] == 92000, (
        f"100000 gross less an 8000 rebate = 92000, got {posted['projected_fee_cents']}"
    )
    dock = validate_success(api.get_dock(world["dock_b_id"], DISPATCHER))
    assert dock["accrued_fee_cents"] == 392000
    assert dock["fee_status"] == "ACCRUING", (
        f"The cap of 100000000 is nowhere near, got {dock['fee_status']}"
    )


def _cap_flip_world():
    """A 1500-cent monthly cap that the first completion is bound to breach, with a
    sibling berth still reserved on the same dock."""
    world = setup_harbor_world(
        dock_b={"name": "Cap Wharf", "berth_count": 2, "min_turnaround_minutes": 0,
                "landing_fee_per_pax_cents": 100, "berth_minute_rate_cents": 50,
                "monthly_fee_cap_cents": 1500},
        stop2={"name": "Cap Stop", "zone_index": 2, "charted_depth_m": 5.00},
    )
    first_trip = create_trip(world, scheduled_departure_utc="2026-09-12T14:00:00Z",
                             scheduled_arrival_utc="2026-09-12T14:30:00Z")
    first_slot = reserve_dock_slot(first_trip["id"], world["dock_b_id"],
                                   "2026-09-12T14:00:00Z", "2026-09-12T14:30:00Z")
    sibling_trip = create_trip(world, scheduled_departure_utc="2026-09-12T16:00:00Z",
                               scheduled_arrival_utc="2026-09-12T16:30:00Z")
    sibling_slot = reserve_dock_slot(sibling_trip["id"], world["dock_b_id"],
                                     "2026-09-12T16:00:00Z", "2026-09-12T16:30:00Z")
    booking = create_confirmed_booking(world, "rider-ann", party_size=3)
    board_trip(world, first_trip["id"], [booking["id"]])
    set_clock("2026-09-12T14:40:00Z")
    depart_trip(world, first_trip["id"])
    set_clock("2026-09-12T14:55:00Z")
    return world, first_trip, first_slot, sibling_slot, booking


def test_final_posting_is_trimmed_to_the_monthly_cap(api):
    """PRD §3.8: "In the **final** variant the fee is added to the accrual and the cap
    is then tested."
    PRD §3.8: "If the resulting `accrued_fee_cents` reaches or exceeds the dock's
    `monthly_fee_cap_cents`, the overflow — the amount by which the accrual overshot
    the cap — is trimmed off the fee, the accrual is pinned to exactly
    `monthly_fee_cap_cents`, and the dock's `fee_status` flips `ACCRUING → CAPPED`."

    Design: Difficulty/transitive_cascade/completion_cascade_slot_posting_to_dock_cap_flip_to_sibling_rebate_lock
    """
    world, first_trip, first_slot, _sibling_slot, _booking = _cap_flip_world()

    completed = complete_trip(world, first_trip["id"])

    assert completed["provisional_fee_cents"] == 1800, (
        f"30 minutes x 50 cents + 3 pax x 100 cents = 1800, got "
        f"{completed['provisional_fee_cents']}"
    )
    settled = validate_success(api.get_dock_slot(first_slot["id"], DISPATCHER))
    assert settled["status"] == "CONSUMED"
    assert settled["berth_minutes"] == 40
    assert settled["projected_fee_cents"] == 0
    assert settled["landing_fee_cents"] == 1500, (
        f"A 2300-cent final fee trimmed by the 800-cent overflow = 1500, got "
        f"{settled['landing_fee_cents']}"
    )
    assert completed["final_fee_cents"] == 1500


def test_the_cap_flip_pre_locks_the_rebate_on_sibling_reservations(api):
    """PRD §3.8: "Once a dock's `fee_status` has become `CAPPED`, every slot on that
    same dock still sitting in `RESERVED` has its `rebate_bp` pre-locked to 10000, so
    any later posting on those slots computes a fee of exactly 0 and the capped dock
    never accrues another cent."
    PRD §3.7: "The sum of those final amounts becomes the trip's `final_fee_cents`;
    the money axis moves `PROVISIONAL → FINAL` and the movement axis
    `DEPARTED → COMPLETED`; every booking on the trip still in `BOARDED` moves
    `BOARDED → COMPLETED` with its `version` incremented by 1; the master's
    `trips_mastered_count` increments by 1; each dock touched has its `version`
    incremented by 1; and the trip's `version` increments by 1."

    Design: Difficulty/transitive_cascade/completion_cascade_slot_posting_to_dock_cap_flip_to_sibling_rebate_lock
    """
    world, first_trip, _first_slot, sibling_slot, booking = _cap_flip_world()

    complete_trip(world, first_trip["id"])

    dock = validate_success(api.get_dock(world["dock_b_id"], DISPATCHER))
    assert dock["accrued_fee_cents"] == 1500, (
        f"The accrual is pinned to the cap, got {dock['accrued_fee_cents']}"
    )
    assert dock["fee_status"] == "CAPPED"

    sibling = validate_success(api.get_dock_slot(sibling_slot["id"], DISPATCHER))
    assert sibling["status"] == "RESERVED"
    assert sibling["rebate_bp"] == 10000, (
        f"The cap flip must pre-lock the sibling's rebate, got {sibling['rebate_bp']}"
    )
    assert validate_success(api.get_booking(booking["id"], RIDER))["status"] == "COMPLETED"
    crew = validate_success(api.get_crew_member(world["crew_id"], DISPATCHER))
    assert crew["trips_mastered_count"] == 1


def _two_departed_sailings_on_one_dock():
    """Both sailings have posted a provisional amount into Pier One's accrual, and
    neither has completed yet."""
    world = setup_harbor_world()
    first_trip = create_trip(world)
    first_slot = reserve_dock_slot(first_trip["id"], world["dock_a_id"],
                                   "2026-09-12T14:00:00Z", "2026-09-12T14:20:00Z")
    second_trip = create_trip(world, scheduled_departure_utc="2026-09-12T16:00:00Z",
                              scheduled_arrival_utc="2026-09-12T16:25:00Z")
    second_slot = reserve_dock_slot(second_trip["id"], world["dock_a_id"],
                                    "2026-09-12T16:00:00Z", "2026-09-12T16:30:00Z")
    booking = create_confirmed_booking(world, "rider-ann", party_size=3)
    board_trip(world, first_trip["id"], [booking["id"]])
    board_trip(world, second_trip["id"], [])
    set_clock("2026-09-12T14:35:00Z")
    depart_trip(world, first_trip["id"])
    set_clock("2026-09-12T16:35:00Z")
    depart_trip(world, second_trip["id"])
    set_clock("2026-09-12T16:40:00Z")
    return world, first_trip, first_slot, second_trip, second_slot


def test_completion_reverses_its_own_provisional_before_posting_the_final_fee(api):
    """PRD §2.9: "The forward action is a departure posting a provisional amount into
    the accrual; the compensating action is the completion subtracting exactly that
    provisional amount back out before the final amount is posted."
    PRD §3.8: "The rebate looks circular — the tier is keyed on the dock's accrual,
    and the accrual is grown by the very fee the tier helps compute — so the
    evaluation order is pinned and must be followed exactly."

    Design: Difficulty/compensating_invariant/dock_fee_conservation_requires_the_provisional_posting_to_be_reversed_on_completion
    """
    world, first_trip, first_slot, _second_trip, _second_slot = \
        _two_departed_sailings_on_one_dock()

    completed = complete_trip(world, first_trip["id"])

    settled = validate_success(api.get_dock_slot(first_slot["id"], DISPATCHER))
    assert settled["status"] == "CONSUMED"
    assert settled["landing_fee_cents"] == 1760, (
        f"35 minutes x 40 cents + 3 pax x 120 cents = 1760, got "
        f"{settled['landing_fee_cents']}"
    )
    assert settled["projected_fee_cents"] == 0
    assert completed["provisional_fee_cents"] == 1160, (
        f"20 minutes x 40 cents + 3 pax x 120 cents = 1160, got "
        f"{completed['provisional_fee_cents']}"
    )
    assert completed["final_fee_cents"] == 1760


def test_dock_accrual_equals_its_consumed_and_reserved_postings(api):
    """PRD §2.9: "A dock's `accrued_fee_cents` always equals the sum of
    `landing_fee_cents` over its slots in `CONSUMED` plus the sum of
    `projected_fee_cents` over its slots in `RESERVED`."
    PRD §2.9: "Skip the reversal and the accrual drifts by precisely the provisional
    figure."

    Design: Difficulty/compensating_invariant/dock_fee_conservation_requires_the_provisional_posting_to_be_reversed_on_completion
    """
    world, first_trip, first_slot, second_trip, second_slot = \
        _two_departed_sailings_on_one_dock()

    complete_trip(world, first_trip["id"])

    consumed = validate_success(api.get_dock_slot(first_slot["id"], DISPATCHER))
    reserved = validate_success(api.get_dock_slot(second_slot["id"], DISPATCHER))
    dock = validate_success(api.get_dock(world["dock_a_id"], DISPATCHER))

    assert reserved["status"] == "RESERVED"
    assert reserved["projected_fee_cents"] == 1200, (
        f"30 minutes x 40 cents with no passengers = 1200, got "
        f"{reserved['projected_fee_cents']}"
    )
    assert reserved["landing_fee_cents"] == 0
    assert dock["accrued_fee_cents"] == 2960, (
        f"1760 consumed + 1200 still reserved = 2960, got {dock['accrued_fee_cents']}"
    )
    assert dock["accrued_fee_cents"] == (consumed["landing_fee_cents"]
                                         + reserved["projected_fee_cents"])
    assert dock["fee_status"] == "ACCRUING"
    assert validate_success(
        api.get_trip(second_trip["id"], DISPATCHER)
    )["settlement_status"] == "PROVISIONAL"
    assert_dock_fee_conservation(api, world["dock_a_id"], DISPATCHER)
