"""Lock scheduling, chamber posture and the transit-delay cascade."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    clear_chamber,
    create_lock,
    create_lock_reservation_payload,
    create_tow,
    depart_tow,
    enter_chamber,
    grant_lock_slot,
    make_lock_master_headers,
    make_towboat_dispatcher_headers,
    make_waterway_admin_headers,
    read_assignment,
    read_contract,
    read_lock,
    read_reservation,
    read_tow,
    request_lock_slot,
    set_lock_status,
    setup_grain_movement,
    setup_underway_tow_at_lock,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

DISPATCH = make_towboat_dispatcher_headers()
ADMIN = make_waterway_admin_headers()


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap / the buffered half-open chamber window
# ---------------------------------------------------------------------------
def _lock_with_a_granted_eight_oclock_slot():
    lock = create_lock(lock_name="Chain of Rocks", chamber_capacity_barges=9,
                       cycle_minutes=45, turnback_buffer_minutes=30)
    tows = [create_tow(towboat_name=name)
            for name in ("M/V Alpha", "M/V Bravo", "M/V Charlie")]
    first = request_lock_slot(lock["id"], tows[0]["id"], "2026-08-15T08:00:00Z")
    grant_lock_slot(first["id"], lock["id"])
    return lock, tows, first


def test_chamber_window_conflict_covers_the_turnback_buffer(api):
    """PRD §3.6: "The `occupied_until_at` is `scheduled_end_at` advanced by the
    chamber's `turnback_buffer_minutes`, and it is that buffered instant — not
    the end of locking — that marks the exclusive end of chamber occupation for
    conflict purposes."
    PRD §3.6: "Two reservations on the same chamber conflict when the first's
    `scheduled_start_at` falls strictly before the second's `occupied_until_at`
    **and** the second's `scheduled_start_at` falls strictly before the first's
    `occupied_until_at`."

    Design: Difficulty/resource_temporal_overlap/lock_chamber_pairwise_buffered_half_open_window_conflict
    """
    lock, tows, first = _lock_with_a_granted_eight_oclock_slot()
    assert first["cut_count"] == 1, "an empty tow still takes one cut"
    assert_same_instant(first["scheduled_end_at"], "2026-08-15T08:45:00Z",
                        "scheduled_end_at is one 45-minute cycle after the start")
    assert_same_instant(first["occupied_until_at"], "2026-08-15T09:15:00Z",
                        "occupied_until_at adds the 30-minute turnback buffer")

    validate_error(api.create_lock_reservation(
        create_lock_reservation_payload(
            lock["id"], tows[1]["id"], "2026-08-15T09:00:00Z",
            read_tow(tows[1]["id"])["version"]), DISPATCH),
        ApiErrorId.ERR_LOCK_WINDOW_CONFLICT.value)

    assert read_lock(lock["id"])["granted_reservation_count"] == 1, (
        "only the first slot is granted")
    assert read_tow(tows[1]["id"])["pending_lock_reservation_count"] == 0, (
        "the refused request books nothing")


def test_a_request_touching_the_exclusive_edge_is_admitted(api):
    """PRD §3.6: "Because the interval is half-open, touching endpoints do not
    conflict: a tow whose `scheduled_start_at` equals another's
    `occupied_until_at` may proceed."
    PRD §3.6: "The `scheduled_end_at` is `scheduled_start_at` advanced by
    `cut_count` multiplied by the chamber's `cycle_minutes` in minutes."

    Design: Difficulty/resource_temporal_overlap/lock_chamber_pairwise_buffered_half_open_window_conflict
    """
    lock, tows, _first = _lock_with_a_granted_eight_oclock_slot()

    admitted = validate_success(api.create_lock_reservation(
        create_lock_reservation_payload(
            lock["id"], tows[2]["id"], "2026-08-15T09:15:00Z",
            read_tow(tows[2]["id"])["version"]), DISPATCH), 201)
    assert admitted["status"] == "REQUESTED"
    assert_same_instant(admitted["scheduled_end_at"], "2026-08-15T10:00:00Z")
    assert_same_instant(admitted["occupied_until_at"], "2026-08-15T10:30:00Z")
    assert read_lock(lock["id"])["granted_reservation_count"] == 1


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade / the four-hop transit delay
# ---------------------------------------------------------------------------
def _tow_in_chamber_ready_to_clear():
    movement = setup_underway_tow_at_lock(
        requested_start_at="2026-08-14T14:00:00Z",
        loads=(1700,), tow_kwargs={"towboat_name": "M/V Cairo"})
    enter_chamber(movement["reservation_id"], "2026-08-14T14:00:00Z")
    return movement


def test_lockage_overrun_fixes_delay_minutes_and_flips_the_tow_to_delayed(api):
    """PRD §3.6: "On a clear, `delay_minutes` is the number of whole minutes by
    which `actual_end_at` exceeds `scheduled_end_at`, truncated toward zero and
    floored at 0 — a tow that clears early or on time accrues nothing."
    PRD §3.6: "Hop one always runs: the delay is added to the named tow's
    `accrued_delay_minutes`. The remaining hops run only if the tow stands in
    `UNDERWAY` and its `accrued_delay_minutes`, after that addition, has reached
    120 minutes — two full hours of accumulated delay."

    Design: Difficulty/transitive_cascade/lock_clearance_delay_cascades_through_tow_assignment_into_contract_laytime
    """
    movement = _tow_in_chamber_ready_to_clear()
    reservation = read_reservation(movement["reservation_id"])
    assert reservation["cut_count"] == 1
    assert_same_instant(reservation["scheduled_end_at"], "2026-08-14T14:45:00Z")
    assert_same_instant(reservation["occupied_until_at"], "2026-08-14T15:15:00Z")

    cleared = clear_chamber(movement["reservation_id"], "2026-08-14T17:30:00Z")
    assert cleared["status"] == "CLEARED"
    assert cleared["delay_minutes"] == 165, (
        f"17:30 overruns the 14:45 schedule by 165 whole minutes, "
        f"got {cleared['delay_minutes']}")

    tow = read_tow(movement["tow_id"])
    assert tow["accrued_delay_minutes"] == 165
    assert tow["status"] == "DELAYED", "165 minutes has reached the 120-minute threshold"
    assert read_lock(movement["lock_id"])["granted_reservation_count"] == 0
    assert tow["pending_lock_reservation_count"] == 0


def test_the_delay_walks_into_the_assignment_and_extends_contract_laytime(api):
    """PRD §3.6: "When that threshold is met the tow moves `UNDERWAY →
    DELAYED`, and hop two adds the same delay figure to the
    `delay_attributed_minutes` of every assignment on that tow standing in
    `LOADED`, processed in ascending `cut_position` order."
    PRD §3.6: "Hop four is the contractual remedy: any of those contracts whose
    `accrued_delay_minutes` has now reached 150 minutes — two and a half hours —
    and whose `delay_protection_applied` is still false has its `laytime_hours`
    increased by 12 additional free hours and its `delay_protection_applied` set
    to true."

    Design: Difficulty/transitive_cascade/lock_clearance_delay_cascades_through_tow_assignment_into_contract_laytime
    """
    movement = _tow_in_chamber_ready_to_clear()
    clear_chamber(movement["reservation_id"], "2026-08-14T17:30:00Z")

    assignment = read_assignment(movement["assignments"][0]["id"])
    assert assignment["delay_attributed_minutes"] == 165, (
        f"hop two writes the same figure onto the LOADED cut, "
        f"got {assignment['delay_attributed_minutes']}")

    contract = read_contract(movement["contract_id"])
    assert contract["accrued_delay_minutes"] == 165, (
        "hop three touches the named contract exactly once")
    assert contract["laytime_hours"] == 24, (
        f"12 free hours plus the 12-hour delay-protection extension, "
        f"got {contract['laytime_hours']}")
    assert contract["delay_protection_applied"] is True


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency / entering needs an UNDERWAY tow
# ---------------------------------------------------------------------------
def _sealed_tow_with_a_granted_slot():
    lock = create_lock(lock_name="Chain of Rocks", chamber_capacity_barges=9,
                       cycle_minutes=45, turnback_buffer_minutes=30)
    movement = setup_grain_movement(loads=(1700,), stage="SEALED")
    reservation = request_lock_slot(lock["id"], movement["tow_id"],
                                    "2026-08-14T14:00:00Z")
    grant_lock_slot(reservation["id"], lock["id"])
    movement["lock_id"] = lock["id"]
    movement["reservation_id"] = reservation["id"]
    return movement


def test_entering_the_chamber_from_a_merely_sealed_tow_is_refused(api):
    """PRD §3.6: "Entering the chamber is the dispatcher's move: it requires an
    `actual_start_at`, demands that the reservation stand in `GRANTED`, that the
    tow stand in `UNDERWAY` or `DELAYED`, and that the chamber not be `CLOSED`;
    it moves the reservation `GRANTED → IN_CHAMBER`, stamps `actual_start_at`,
    and increments `version`."

    Design: Difficulty/cross_entity_state_dependency/lock_chamber_entry_requires_tow_under_way_not_merely_sealed
    """
    movement = _sealed_tow_with_a_granted_slot()

    response = api.enter_chamber(
        movement["reservation_id"], {"actual_start_at": "2026-08-14T14:00:00Z"},
        DISPATCH)
    assert response.status_code == 409, (
        f"a state precondition failure answers 409, got {response.status_code}")
    validate_error_is_one_of(response, [
        ApiErrorId.ERR_TOW_INVALID_STATE.value,
        ApiErrorId.ERR_LOCK_RESERVATION_INVALID_STATE.value,
    ])

    reservation = read_reservation(movement["reservation_id"])
    assert reservation["status"] == "GRANTED", "the refused call moved nothing"
    assert reservation.get("actual_start_at") is None
    assert read_tow(movement["tow_id"])["status"] == "SEALED"


def test_entering_the_chamber_succeeds_once_the_tow_is_under_way(api):
    """PRD §3.6: "Entering the chamber is the dispatcher's move: it requires an
    `actual_start_at`, demands that the reservation stand in `GRANTED`, that the
    tow stand in `UNDERWAY` or `DELAYED`, and that the chamber not be `CLOSED`;
    it moves the reservation `GRANTED → IN_CHAMBER`, stamps `actual_start_at`,
    and increments `version`."
    PRD §3.7: "Every assignment on the tow standing in `CONFIRMED` advances to
    `LOADED`."

    Design: Difficulty/cross_entity_state_dependency/lock_chamber_entry_requires_tow_under_way_not_merely_sealed
    """
    movement = _sealed_tow_with_a_granted_slot()
    depart_tow(movement["tow_id"], "2026-08-14T12:00:00Z")

    assert read_tow(movement["tow_id"])["status"] == "UNDERWAY"
    assert read_assignment(movement["assignments"][0]["id"])["status"] == "LOADED"

    entered = validate_success(api.enter_chamber(
        movement["reservation_id"], {"actual_start_at": "2026-08-14T14:00:00Z"},
        DISPATCH))
    assert entered["status"] == "IN_CHAMBER"
    assert_same_instant(entered["actual_start_at"], "2026-08-14T14:00:00Z")


# ---------------------------------------------------------------------------
# Queue B — reservation lifecycle, chamber posture and listings
# ---------------------------------------------------------------------------
def test_reschedule_returns_a_granted_slot_to_the_queue(api):
    """PRD §3.6: "It requires a new `requested_start_at`, moves the reservation
    `GRANTED → REQUESTED`, re-pins `scheduled_start_at` to the new instant and
    recomputes both `scheduled_end_at` and `occupied_until_at` from the tow's
    *current* cut count — which may differ from the cut count the original slot
    was sized with."
    PRD §3.6: "The chamber's `granted_reservation_count` decrements by one and
    the reservation's `version` increments. The tow's
    `pending_lock_reservation_count` is unaffected, because the reservation is
    still pending."

    Design: Corner/state_machines/lock_reservation_reschedule_returns_a_granted_slot_to_the_queue
    """
    lock = create_lock(cycle_minutes=45, turnback_buffer_minutes=30)
    tow = create_tow(towboat_name="M/V Delta", horsepower=4000)
    reservation = request_lock_slot(lock["id"], tow["id"], "2026-08-15T08:00:00Z")
    grant_lock_slot(reservation["id"], lock["id"])
    assert read_lock(lock["id"])["granted_reservation_count"] == 1

    rescheduled = validate_success(api.reschedule_lock_reservation(
        reservation["id"], {"requested_start_at": "2026-08-15T11:00:00Z"},
        make_lock_master_headers(lock["id"])))
    assert rescheduled["status"] == "REQUESTED"
    assert_same_instant(rescheduled["scheduled_start_at"], "2026-08-15T11:00:00Z")
    assert_same_instant(rescheduled["scheduled_end_at"], "2026-08-15T11:45:00Z")
    assert_same_instant(rescheduled["occupied_until_at"], "2026-08-15T12:15:00Z")
    assert read_lock(lock["id"])["granted_reservation_count"] == 0
    assert read_tow(tow["id"])["pending_lock_reservation_count"] == 1


def test_clearing_a_reservation_that_never_entered_the_chamber_is_refused(api):
    """PRD §3.6: "Clearing the chamber requires an `actual_end_at` that is at or
    after `actual_start_at` — an earlier instant is refused with
    `ERR_UNLOAD_SEQUENCE_INVALID` — and moves the reservation `IN_CHAMBER →
    CLEARED`, which is terminal."
    PRD §3.6: "The reservation must stand in `REQUESTED`, or the call is refused
    with `ERR_LOCK_RESERVATION_INVALID_STATE`; the chamber must not be `CLOSED`;
    the tow must stand in `BUILDING`, `SEALED`, `UNDERWAY` or `DELAYED`; and the
    window must not conflict with any other `GRANTED` or `IN_CHAMBER`
    reservation on the chamber."

    Design: Corner/state_machines/clear_a_reservation_that_never_entered_the_chamber_returns_invalid_state
    """
    lock = create_lock()
    tow = create_tow(towboat_name="M/V Echo", horsepower=4000)
    reservation = request_lock_slot(lock["id"], tow["id"], "2026-08-15T08:00:00Z")

    validate_error(api.clear_chamber(
        reservation["id"], {"actual_end_at": "2026-08-15T09:00:00Z"}, DISPATCH),
        ApiErrorId.ERR_LOCK_RESERVATION_INVALID_STATE.value)

    stored = read_reservation(reservation["id"])
    assert stored["status"] == "REQUESTED"
    assert stored["delay_minutes"] == 0
    assert stored.get("actual_end_at") is None
    refreshed_tow = read_tow(tow["id"])
    assert refreshed_tow["accrued_delay_minutes"] == 0
    assert refreshed_tow["status"] == "BUILDING"


def test_closing_a_chamber_cancels_live_slots_and_charges_the_closure_delay(api):
    """PRD §3.6: "Closing a chamber cancels **every** reservation on it standing
    in `REQUESTED` or `GRANTED`, and charges each tow named by one of those
    cancelled reservations a flat closure delay of 240 minutes — four hours of
    lost transit."
    PRD §3.6: "When the tow is not `UNDERWAY` at the moment of the delay, only
    hop one runs and nothing downstream is disturbed."
    PRD §3.6: "A request against a chamber standing in `CLOSED` is refused with
    `ERR_LOCK_CLOSED`."

    Design: Corner/state_machines/lock_closure_cancels_live_slots_and_charges_the_closure_delay
    """
    lock = create_lock(cycle_minutes=45, turnback_buffer_minutes=30)
    first_tow = create_tow(towboat_name="M/V Foxtrot", horsepower=4000)
    second_tow = create_tow(towboat_name="M/V Golf", horsepower=4000)
    granted = request_lock_slot(lock["id"], first_tow["id"], "2026-08-15T08:00:00Z")
    grant_lock_slot(granted["id"], lock["id"])
    requested = request_lock_slot(lock["id"], second_tow["id"], "2026-08-15T12:00:00Z")

    closed = set_lock_status(lock["id"], "CLOSED")
    assert closed["status"] == "CLOSED"
    assert closed["granted_reservation_count"] == 0

    assert read_reservation(granted["id"])["status"] == "CANCELLED"
    assert read_reservation(requested["id"])["status"] == "CANCELLED"
    for tow_id in (first_tow["id"], second_tow["id"]):
        tow = read_tow(tow_id)
        assert tow["accrued_delay_minutes"] == 240, (
            f"each affected tow takes the flat closure delay, "
            f"got {tow['accrued_delay_minutes']}")
        assert tow["status"] == "BUILDING", (
            "the DELAYED flip only applies to a tow standing in UNDERWAY")
        assert tow["pending_lock_reservation_count"] == 0

    validate_error(api.create_lock_reservation(
        create_lock_reservation_payload(
            lock["id"], second_tow["id"], "2026-08-16T08:00:00Z",
            read_tow(second_tow["id"])["version"]), DISPATCH),
        ApiErrorId.ERR_LOCK_CLOSED.value)


def test_cut_count_rounds_up_for_a_tow_wider_than_the_chamber(api):
    """PRD §3.6: "The `cut_count` is the tow's `barge_count` divided by the
    chamber's `chamber_capacity_barges`, rounded up to a whole number, with a
    floor of one cut — a tow smaller than one chamber-load still takes one cut."
    PRD §3.6: "An optional `priority_class` declares the lockage priority as
    `PRIORITY`, `COMMERCIAL` or `RECREATIONAL`, defaulting to `COMMERCIAL` when
    omitted."

    Design: Corner/calculations/lock_cut_count_rounds_up_for_a_tow_wider_than_the_chamber
    """
    movement = setup_grain_movement(
        loads=(1700, 1650), contracted_tons=3400, stage="BUILDING",
        tow_kwargs={"towboat_name": "M/V India"})
    lock = create_lock(lock_name="Lock 27", river_mile=180.0,
                       chamber_capacity_barges=1, cycle_minutes=45,
                       turnback_buffer_minutes=30)

    reservation = request_lock_slot(
        lock["id"], movement["tow_id"], "2026-08-15T08:00:00Z",
        priority_class="PRIORITY")
    assert reservation["cut_count"] == 2, (
        f"two barges through a single-barge chamber need two cuts, "
        f"got {reservation['cut_count']}")
    assert_same_instant(reservation["scheduled_start_at"], "2026-08-15T08:00:00Z")
    assert_same_instant(reservation["scheduled_end_at"], "2026-08-15T09:30:00Z")
    assert_same_instant(reservation["occupied_until_at"], "2026-08-15T10:00:00Z")
    assert reservation["status"] == "REQUESTED"
    assert reservation["priority_class"] == "PRIORITY"
    assert read_tow(movement["tow_id"])["pending_lock_reservation_count"] == 1


def test_list_lock_reservations_by_lock_by_tow_and_by_status(api):
    """PRD §3.6: "Reservations may be listed narrowed by `lock_id`, by `tow_id`
    or by `status`."
    PRD §2.3: "Every filter parameter named in the endpoint table narrows the
    result set by exact match, and multiple filters combine conjunctively."

    Design: Corner/endpoints/list_lock_reservations_filtered_by_lock_and_by_status
    """
    first_lock = create_lock(lock_name="Chain of Rocks", cycle_minutes=45,
                             turnback_buffer_minutes=30)
    second_lock = create_lock(lock_name="Mel Price", river_mile=200.8,
                              cycle_minutes=60, turnback_buffer_minutes=20)
    first_tow = create_tow(towboat_name="M/V November", horsepower=4000)
    second_tow = create_tow(towboat_name="M/V Oscar", horsepower=4000)
    granted = request_lock_slot(first_lock["id"], first_tow["id"],
                                "2026-08-15T08:00:00Z")
    grant_lock_slot(granted["id"], first_lock["id"])
    requested = request_lock_slot(first_lock["id"], second_tow["id"],
                                  "2026-08-15T11:00:00Z")

    rows, meta = validate_paginated(api.list_lock_reservations(
        DISPATCH, params={"lock_id": first_lock["id"]}))
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {granted["id"], requested["id"]}

    _rows, meta = validate_paginated(api.list_lock_reservations(
        DISPATCH, params={"lock_id": second_lock["id"]}))
    assert meta["total_count"] == 0

    rows, meta = validate_paginated(api.list_lock_reservations(
        DISPATCH, params={"tow_id": second_tow["id"]}))
    assert meta["total_count"] == 1 and rows[0]["id"] == requested["id"]

    rows, meta = validate_paginated(api.list_lock_reservations(
        DISPATCH, params={"lock_id": first_lock["id"], "status": "GRANTED"}))
    assert meta["total_count"] == 1 and rows[0]["id"] == granted["id"]
    assert read_lock(first_lock["id"])["granted_reservation_count"] == 1
    assert read_lock(second_lock["id"])["granted_reservation_count"] == 0


def test_lock_version_increments_on_every_posture_change(api):
    """PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601
    UTC timestamp refreshed on every mutation of that row, and `version`, an
    integer that starts at 1 when the row is created and increments by exactly 1
    on every mutation of that row — including mutations that a cascade performs
    on the row rather than a direct call from a client."
    PRD §3.6: "From `OPEN` the chamber may move to `RESTRICTED` or to `CLOSED`;
    from `RESTRICTED` it may return to `OPEN`; from `CLOSED` it may return to
    `OPEN`."

    Design: Corner/cross_cutting_layers/lock_version_increments_on_every_mutation
    """
    lock = create_lock()
    assert lock["version"] == 1, "a freshly created chamber reads version 1"
    assert lock["status"] == "OPEN"

    restricted = set_lock_status(lock["id"], "RESTRICTED", ADMIN)
    assert restricted["status"] == "RESTRICTED"
    assert restricted["version"] == 2

    reopened = set_lock_status(lock["id"], "OPEN", ADMIN)
    assert reopened["status"] == "OPEN"
    assert reopened["version"] == 3


def test_second_lock_slot_with_a_stale_tow_version_is_refused(api):
    """PRD §2.8: "**Requesting a lock reservation** requires
    `expected_tow_version`, carrying the `version` of the tow named by `tow_id`
    as the dispatcher last read it."
    PRD §2.8: "If `expected_tow_version` does not equal the tow's current
    `version`, the request is rejected with `ERR_STALE_TOW_VERSION` (HTTP 412)."
    PRD §3.6: "On success the tow's `pending_lock_reservation_count` increments
    by one and the tow's `version` increments as well — which is precisely why a
    dispatcher booking a second slot must re-read the tow first."

    Design: Corner/cross_cutting_layers/second_lock_slot_with_stale_expected_tow_version_returns_412
    """
    first_lock = create_lock(lock_name="Chain of Rocks", cycle_minutes=45,
                             turnback_buffer_minutes=30)
    second_lock = create_lock(lock_name="Mel Price", river_mile=200.8,
                              cycle_minutes=60, turnback_buffer_minutes=20)
    tow = create_tow(towboat_name="M/V Sierra", horsepower=4000)
    observed_version = tow["version"]
    request_lock_slot(first_lock["id"], tow["id"], "2026-08-15T08:00:00Z",
                      expected_tow_version=observed_version)

    validate_error(api.create_lock_reservation(
        create_lock_reservation_payload(
            second_lock["id"], tow["id"], "2026-08-15T14:00:00Z", observed_version),
        DISPATCH),
        ApiErrorId.ERR_STALE_TOW_VERSION.value)

    assert read_tow(tow["id"])["pending_lock_reservation_count"] == 1
    _rows, meta = validate_paginated(api.list_lock_reservations(
        DISPATCH, params={"tow_id": tow["id"]}))
    assert meta["total_count"] == 1, "the refused request booked nothing"

    fresh = validate_success(api.create_lock_reservation(
        create_lock_reservation_payload(
            second_lock["id"], tow["id"], "2026-08-15T14:00:00Z",
            read_tow(tow["id"])["version"]), DISPATCH), 201)
    assert fresh["lock_id"] == second_lock["id"]
    assert_same_instant(fresh["scheduled_end_at"], "2026-08-15T15:00:00Z")
    assert read_tow(tow["id"])["pending_lock_reservation_count"] == 2
