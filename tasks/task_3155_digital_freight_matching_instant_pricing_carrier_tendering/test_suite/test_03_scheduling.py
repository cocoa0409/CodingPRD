"""Dock selection, the capacity guard and the two interval geometries."""
from test_helpers import (
    api_client as api,
    make_carrier_headers,
    make_platform_admin_headers,
    make_shipper_headers,
    read_facility,
    iso3,
    setup_board,
    setup_dock_buffer_scenario,
    setup_dock_capacity_scenario,
    setup_dock_selector_scenario,
    setup_equipment_window_scenario,
    set_clock,
)


def _booking_payload(board, entry, equipment_id):
    return {
        "load_id": entry["load"]["id"],
        "carrier_id": board["carrier_id"],
        "rate_quote_id": entry["quote"]["id"],
        "equipment_id": equipment_id,
        "expected_load_version": entry["load"]["version"],
    }


def _appointments(shipper_id, load_id):
    return api.list_load_appointments(
        load_id, make_shipper_headers(shipper_id)).json()["data"]


class TestDockSelector:
    """The selector's ranking expression is dock_position ascending."""

    def test_selector_takes_the_lowest_free_position_and_reuses_it(self):
        """PRD section 3.5: "When more than one survives, the lowest-numbered one
        is chosen — positions are unique by construction, so no tie-break key is
        needed."

        Design: Corner/cross_cutting_complexity_layers/dock_selector_always_takes_the_lowest_free_position
        """
        board = setup_dock_selector_scenario()
        slots = board["slot_loads"]
        unit = board["equipment"][0]["id"]
        first = api.create_booking(_booking_payload(board, slots[0], unit),
                                   make_carrier_headers(board["carrier_id"]))
        assert first.status_code == 201, first.text
        second = api.create_booking(_booking_payload(board, slots[1], unit),
                                    make_carrier_headers(board["carrier_id"]))
        assert second.status_code == 201, second.text
        third = api.create_booking(_booking_payload(board, slots[2], unit),
                                   make_carrier_headers(board["carrier_id"]))
        assert third.status_code == 201, third.text

        assert _appointments(board["shipper_id"], slots[0]["load"]["id"])[0]["dock_position"] == 1
        assert _appointments(board["shipper_id"], slots[1]["load"]["id"])[0]["dock_position"] == 2
        assert _appointments(board["shipper_id"], slots[2]["load"]["id"])[0]["dock_position"] == 1

        facility = read_facility(board["origin_facility_id"])
        assert facility["docks_committed_today"] == 3


class TestDockCapacityGuard:
    """The guard trips at equality, not only above it."""

    def test_booking_is_refused_once_the_committed_count_reaches_capacity(self):
        """PRD section 2.11: "A slot cannot be placed when the committed count has
        already reached the capacity — the guard trips at equality, not only above
        it — and the attempt is refused with `ERR_DOCK_CAPACITY_EXCEEDED` (HTTP
        409)."

        Design: Difficulty/boundary_precision_check/dock_capacity_guard_rejects_at_exactly_capacity_not_past_it
        """
        board = setup_dock_capacity_scenario(dock_capacity=3, load_count=4)
        slots = board["capacity_loads"]
        unit = board["equipment"][0]["id"]
        for entry in slots[:3]:
            response = api.create_booking(_booking_payload(board, entry, unit),
                                          make_carrier_headers(board["carrier_id"]))
            assert response.status_code == 201, response.text

        facility = read_facility(board["origin_facility_id"])
        assert facility["docks_committed_today"] == 3
        assert facility["dock_capacity"] == 3

        rejected = api.create_booking(_booking_payload(board, slots[3], unit),
                                      make_carrier_headers(board["carrier_id"]))
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["data"]["error_id"] == "ERR_DOCK_CAPACITY_EXCEEDED"

        spare = api.get_load(slots[3]["load"]["id"],
                             make_shipper_headers(board["shipper_id"])).json()["data"]
        assert spare["status"] == "POSTED"
        assert spare["carrier_id"] is None

    def test_restoring_a_cancelled_slot_on_a_full_day_is_refused(self):
        """PRD section 3.5: "A slot can be restored only while the same capacity
        guard still passes."

        Design: Difficulty/boundary_precision_check/dock_capacity_guard_rejects_at_exactly_capacity_not_past_it
        """
        board = setup_dock_capacity_scenario(dock_capacity=3, load_count=4)
        slots = board["capacity_loads"]
        unit = board["equipment"][0]["id"]
        for entry in slots[:3]:
            api.create_booking(_booking_payload(board, entry, unit),
                               make_carrier_headers(board["carrier_id"]))

        appointment = _appointments(board["shipper_id"], slots[2]["load"]["id"])[0]
        cancelled = api.cancel_appointment(appointment["id"],
                                           make_carrier_headers(board["carrier_id"]))
        assert cancelled.status_code == 200, cancelled.text

        _fill_last_position(board, slots, unit)

        facility = read_facility(board["origin_facility_id"])
        assert facility["docks_committed_today"] == 3
        restore = api.restore_appointment(appointment["id"],
                                          make_carrier_headers(board["carrier_id"]))
        assert restore.status_code == 409, restore.text
        assert restore.json()["data"]["error_id"] == "ERR_DOCK_CAPACITY_EXCEEDED"

        still = api.get_appointment(
            appointment["id"], make_carrier_headers(board["carrier_id"])).json()["data"]
        assert still["status"] == "CANCELLED"


def _fill_last_position(board, slots, unit):
    """Use the spare load to take the position the cancellation freed."""
    response = api.create_booking(_booking_payload(board, slots[3], unit),
                                  make_carrier_headers(board["carrier_id"]))
    assert response.status_code == 201, response.text


class TestDockBuffer:
    """Docks are expanded by 120 minutes on both sides."""

    def test_three_hour_gap_collides_once_the_window_is_buffered(self):
        """PRD section 3.7: "Only after the equipment check passes does the dock
        selector hunt for a free position, and its failure surfaces as
        `ERR_APPOINTMENT_OVERLAP` (HTTP 409)."
        PRD section 2.11: "Equipment is checked with no buffer at all and half-open windows:
        a new booking window that begins at exactly the previous booking
        window's end on the same unit is considered adjacent, not
        overlapping, and is accepted; overlapping one is refused with
        `ERR_EQUIPMENT_WINDOW_CONFLICT` (HTTP 409). Docks are checked
        with a two-hour buffer applied to both sides of the requested
        window: a slot that clears the equipment test with nothing to
        spare can still collide once the requested window is widened by
        120 minutes in each direction."

        Design: Difficulty/resource_temporal_overlap/dock_window_expands_both_sides_by_two_hours_so_a_free_dock_still_rejects_a_three_hour_gap
        """
        board = setup_dock_buffer_scenario(dock_capacity=1)
        entry = board["buffer_loads"]["gap3"]
        rejected = api.create_booking(_booking_payload(board, entry, board["equipment"][0]["id"]),
                                      make_carrier_headers(board["carrier_id"]))
        assert rejected.status_code == 409, rejected.text
        # The three-hour gap and the full day are both true here; the PRD names
        # both refusals but not their precedence.
        assert rejected.json()["data"]["error_id"] in (
            "ERR_APPOINTMENT_OVERLAP", "ERR_DOCK_CAPACITY_EXCEEDED")

        load = api.get_load(entry["load"]["id"],
                            make_shipper_headers(board["shipper_id"])).json()["data"]
        assert load["status"] == "POSTED"
        assert load["carrier_id"] is None

    def test_five_hour_gap_is_accepted_and_takes_the_lowest_position(self):
        """PRD section 3.5: "It considers the requested window widened by 120
        minutes on each side and finds every position between one and the
        facility's capacity that has no `SCHEDULED` or `IN_PROGRESS` slot
        overlapping that widened window."

        Design: Difficulty/resource_temporal_overlap/dock_window_expands_both_sides_by_two_hours_so_a_free_dock_still_rejects_a_three_hour_gap
        """
        board = setup_dock_buffer_scenario(dock_capacity=2)
        entry = board["buffer_loads"]["gap5"]
        accepted = api.create_booking(_booking_payload(board, entry, board["equipment"][0]["id"]),
                                      make_carrier_headers(board["carrier_id"]))
        assert accepted.status_code == 201, accepted.text

        appointment = _appointments(board["shipper_id"], entry["load"]["id"])[0]
        assert appointment["dock_position"] == 1

        facility = read_facility(board["origin_facility_id"])
        assert facility["docks_committed_today"] == 2


class TestEquipmentWindow:
    """Equipment windows use no buffer at all and half-open semantics."""

    def test_adjacent_window_is_accepted_and_one_minute_of_overlap_is_not(self):
        """PRD section 2.11: "Equipment is checked with no buffer at all and
        half-open windows: a new booking window that begins at exactly the previous
        booking window's end on the same unit is considered adjacent, not
        overlapping, and is accepted; overlapping one is refused with
        `ERR_EQUIPMENT_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/equipment_window_accepts_adjacent_but_rejects_one_minute_of_overlap
        """
        board = setup_equipment_window_scenario()
        slots = board["window_loads"]
        unit = board["equipment"][0]["id"]

        first = api.create_booking(_booking_payload(board, slots[0], unit),
                                   make_carrier_headers(board["carrier_id"]))
        assert first.status_code == 201, first.text
        adjacent = api.create_booking(_booking_payload(board, slots[1], unit),
                                      make_carrier_headers(board["carrier_id"]))
        assert adjacent.status_code == 201, (
            f"an exactly adjacent window must be accepted, got {adjacent.text}")

        assert adjacent.json()["data"]["booking_window_start"] == iso3("2026-10-05T12:00:00Z")
        assert first.json()["data"]["booking_window_end"] == iso3("2026-10-05T12:00:00Z")

        overlapping = api.create_booking(_booking_payload(board, slots[2], unit),
                                         make_carrier_headers(board["carrier_id"]))
        assert overlapping.status_code == 409, overlapping.text
        assert overlapping.json()["data"]["error_id"] == "ERR_EQUIPMENT_WINDOW_CONFLICT"

    def test_a_window_cleared_by_the_failed_attempt_still_books(self):
        """PRD section 2.11: "a slot that clears the equipment test with nothing to
        spare can still collide once the requested window is widened by 120 minutes
        in each direction."

        Design: Difficulty/resource_temporal_overlap/equipment_window_accepts_adjacent_but_rejects_one_minute_of_overlap
        """
        board = setup_equipment_window_scenario()
        slots = board["window_loads"]
        unit = board["equipment"][0]["id"]
        api.create_booking(_booking_payload(board, slots[0], unit),
                           make_carrier_headers(board["carrier_id"]))
        api.create_booking(_booking_payload(board, slots[1], unit),
                           make_carrier_headers(board["carrier_id"]))
        failed = api.create_booking(_booking_payload(board, slots[2], unit),
                                    make_carrier_headers(board["carrier_id"]))
        assert failed.status_code == 409

        recovered = api.create_booking(_booking_payload(board, slots[3], unit),
                                       make_carrier_headers(board["carrier_id"]))
        assert recovered.status_code == 201, (
            f"the unit was never taken by the failed attempt, got {recovered.text}")
        equipment = api.get_equipment(
            unit, make_carrier_headers(board["carrier_id"])).json()["data"]
        assert equipment["status"] == "ASSIGNED"


class TestRescheduleDirection:
    """A reschedule can only bring an appointment forward."""

    def test_reschedule_to_the_same_instant_is_refused_but_earlier_succeeds(self):
        """PRD section 3.5: "The requested `window_start` must be strictly before
        the slot's current `window_start` — a reschedule can only bring an
        appointment forward, never push it back — or the answer is
        `ERR_RESCHEDULE_ONLY_EARLIER` (HTTP 409)."

        Design: Corner/errors/rescheduling_later_or_at_the_same_instant_returns_reschedule_only_earlier
        """
        board = setup_board(units=1)
        set_clock("2026-10-05T00:00:00Z")
        load = _booked_slot_load(board)
        appointment = _appointments(board["shipper_id"], load["id"])[0]
        assert appointment["window_start"] == iso3("2026-10-05T08:00:00Z")

        same = api.reschedule_appointment(
            appointment["id"],
            {"window_start": "2026-10-05T08:00:00Z", "window_end": "2026-10-05T12:00:00Z"},
            make_carrier_headers(board["carrier_id"]))
        assert same.status_code == 409, same.text
        assert same.json()["data"]["error_id"] == "ERR_RESCHEDULE_ONLY_EARLIER"

        earlier = api.reschedule_appointment(
            appointment["id"],
            {"window_start": "2026-10-05T06:00:00Z", "window_end": "2026-10-05T07:00:00Z"},
            make_carrier_headers(board["carrier_id"]))
        assert earlier.status_code == 200, earlier.text
        assert earlier.json()["data"]["status"] == "IN_PROGRESS"
        assert earlier.json()["data"]["window_start"] == iso3("2026-10-05T06:00:00Z")

        detention = api.list_load_detention_events(
            load["id"], make_shipper_headers(board["shipper_id"])).json()["data"]
        assert len(detention) == 1
        assert detention[0]["status"] == "OPEN"


def _booked_slot_load(board):
    created = api.create_load(
        {
            "shipper_id": board["shipper_id"],
            "origin_facility_id": board["origin_facility_id"],
            "destination_facility_id": board["destination_facility_id"],
            "pricing_mode": "SPOT",
            "equipment_type": "DRY_VAN",
            "commodity": "GENERAL",
            "weight_lbs": 40000,
            "declared_cargo_value_cents": 5000000,
            "distance_miles": 900,
            "pickup_window_start": "2026-10-05T08:00:00Z",
            "pickup_window_end": "2026-10-05T12:00:00Z",
            "delivery_deadline": "2026-10-07T18:00:00Z",
            "market_band": "BALANCED",
        },
        make_shipper_headers(board["shipper_id"]),
    )
    assert created.status_code == 201, created.text
    load_id = created.json()["data"]["id"]
    posted = api.post_load(load_id, make_shipper_headers(board["shipper_id"])).json()["data"]
    quote = api.list_load_rate_quotes(
        load_id, make_shipper_headers(board["shipper_id"])).json()["data"][-1]
    booked = api.create_booking(
        {
            "load_id": load_id,
            "carrier_id": board["carrier_id"],
            "rate_quote_id": quote["id"],
            "equipment_id": board["equipment"][0]["id"],
            "expected_load_version": posted["version"],
        },
        make_carrier_headers(board["carrier_id"]),
    )
    assert booked.status_code == 201, booked.text
    return api.get_load(load_id, make_shipper_headers(board["shipper_id"])).json()["data"]