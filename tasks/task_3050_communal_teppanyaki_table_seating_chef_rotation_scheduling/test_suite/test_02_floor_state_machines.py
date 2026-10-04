"""Floor state machines: the transitions a table, a chef, a booking, an occupancy
and a show phase may and may not take, and the side effects a seating fires.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    DEFAULT_CLOCK,
    FM,
    HOST,
    advance_clock,
    book_hold_seat,
    create_booking,
    create_party,
    fresh_table,
    grant_hold,
    ledger_entries,
    minimal_floor,
    prepare_table_for_turn,
    read_reservation,
    seatings_for,
    seed_seated_booking_with_finished_grill,
    setup_floor,
    shows_for,
    submit_booking,
)


class TestTableStateMachine:

    def test_grill_table_release_from_available_is_rejected_as_invalid_state(self):
        """PRD §3.1: "Two guards apply to leaving `TURNING`: the table may only
        return to `AVAILABLE` when its `guests_seated` has fallen to zero and no show
        phase at that table still carries the status `PLANNED` or `STARTED`."
        PRD §2.10: "then whether the target is in a state from which the requested
        transition is declared (otherwise `ERR_INVALID_STATE`, HTTP 409), and only
        then the business rules."

        Design: Corner/state_machines/grill_table_release_from_available_is_rejected_as_invalid_state
        """
        scenario = setup_floor(tier_codes=(), tables=(("T6", 6),), chefs=())
        table = scenario["tables"][0]
        before = fresh_table(scenario, table["id"])

        response = api_client.post_table_event(table["id"], {"event_type": "TURN_RELEASE"}, FM)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        after = fresh_table(scenario, table["id"])
        assert after["status"] == "AVAILABLE"
        assert after["version"] == before["version"]


class TestChefStateMachine:

    def test_chef_assignment_starts_off_shift_with_no_sequence_index(self):
        """PRD §3.1: "A `FloorManager` also adds chefs to the venue's rotation roster:
        a `ChefAssignment` is created with its `venue_id`, `chef_name` and
        `station_zone`, and starts `OFF_SHIFT` with no `sequence_index` and no
        `current_table_id`."

        Design: Corner/state_machines/chef_assignment_starts_off_shift_with_no_sequence_index
        """
        scenario = minimal_floor()
        response = api_client.create_chef(
            {"venue_id": scenario["venue"]["id"], "chef_name": "Mei Tanaka",
             "station_zone": "ZONE_C"}, FM)
        data = validate_success(response, expected_status=201)

        assert data["status"] == "OFF_SHIFT"
        assert data["sequence_index"] is None
        assert data["current_table_id"] is None
        assert data["completed_show_count"] == 0
        assert data["minutes_since_show"] == 0
        assert float(data["pounds_protein_issued"]) == 0


class TestReservationTerminalState:

    def test_closing_again_from_closed_is_rejected_as_invalid_state(self):
        """PRD §3.8: "`NO_SHOW` and `CLOSED` are the booking's terminal statuses."
        PRD §3.6: "Closing the check is the terminal act of a seated visit. The booking
        moves from `SEATED` to `CLOSED`."

        Design: Corner/state_machines/closing_again_from_closed_is_rejected_as_invalid_state
        """
        scenario = setup_floor(tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        seafood = seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T4", scenario["tables"][0]["id"], party_size=4)

        current = read_reservation(seafood["reservation"]["id"])
        closed = get_success_data(api_client.close_reservation(
            seafood["reservation"]["id"],
            {"expected_reservation_version": current["version"], "credit_to_apply_cents": 0},
            HOST))
        assert closed["status"] == "CLOSED"

        response = api_client.close_reservation(
            seafood["reservation"]["id"],
            {"expected_reservation_version": closed["version"], "credit_to_apply_cents": 0},
            HOST)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        reread = read_reservation(seafood["reservation"]["id"])
        assert reread["status"] == "CLOSED"
        assert reread["version"] == closed["version"]
        trueups = ledger_entries(scenario["venue"]["id"], seafood["reservation"]["id"],
                                 "TABLE_MINIMUM_TRUEUP")
        assert len(trueups) <= 1


class TestSeatingStateMachine:

    def test_seating_extend_from_a_vacated_occupancy_is_rejected_as_invalid_state(self):
        """PRD §3.4: "A `FloorManager` may extend a running occupancy by supplying
        `extension_minutes`, which advances `expected_vacate_at` by that many
        minutes."
        PRD §2.6: "`status` on the row is either `ACTIVE` or `VACATED`, beginning at
        `ACTIVE`."

        Design: Corner/state_machines/seating_extend_from_a_vacated_occupancy_is_rejected_as_invalid_state
        """
        scenario = setup_floor(tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario)
        seafood = seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T4", scenario["tables"][0]["id"], party_size=4)

        prepare_table_for_turn(seafood)
        get_success_data(api_client.post_table_event(
            scenario["tables"][0]["id"], {"event_type": "TURN"}, FM))

        vacated = get_success_data(api_client.get_seating(seafood["seating_id"], FM))
        assert vacated["status"] == "VACATED"

        response = api_client.extend_seating(seafood["seating_id"], 15, FM)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        after = get_success_data(api_client.get_seating(seafood["seating_id"], FM))
        assert after["expected_vacate_at"] == vacated["expected_vacate_at"]


class TestShowStateMachine:

    def test_skipping_a_show_twice_is_rejected_as_invalid_state(self):
        """PRD §3.5: "a phase may instead be driven to `SKIPPED` from either `PLANNED`
        or `STARTED`, and a skipped phase may be reinstated back to `PLANNED`."
        PRD §3.5: "Reinstate, the reverse move from `SKIPPED` back to `PLANNED`, clears
        `actual_start_at` and is only legal while the booking is `HELD` or `SEATED`."

        Design: Corner/state_machines/skipping_a_show_twice_is_rejected_as_invalid_state
        """
        scenario = setup_floor(tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario)
        seafood = book_hold_seat(scenario, party["id"], "T4", scenario["tables"][0]["id"],
                                 party_size=4)

        first = validate_success(api_client.post_show_event(
            seafood["sushi_show_id"], "SKIP", FM))
        assert first["status"] == "SKIPPED"

        response = api_client.post_show_event(seafood["sushi_show_id"], "SKIP", FM)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        reread = validate_success(api_client.get_show(seafood["sushi_show_id"], FM))
        assert reread["status"] == "SKIPPED"

        reinstated = validate_success(api_client.post_show_event(
            seafood["sushi_show_id"], "REINSTATE", FM))
        assert reinstated["status"] == "PLANNED"
        assert reinstated["actual_start_at"] is None


class TestSeatingSideEffects:

    def test_seating_side_effect_execution_posts_a_surcharge_and_plans_the_courses(self):
        """PRD §3.4: "A `TableSeating` row is opened `ACTIVE` with its `guest_count`,
        `seated_at` at the clock and its `expected_vacate_at` computed by the turn-over
        rule below; `guests_seated` is recomputed and `last_seated_at` is stamped;
        `pending_turn` is set true the instant the recomputed `guests_seated` equals
        the table's `seat_capacity`; three `ShowPerformance` rows are planned for the
        booking at `course_phase` `SUSHI`, `GRILL` and `DESSERT`, all `PLANNED` ...
        a seat surcharge is posted into the booking's `seat_surcharge_cents` and a
        `VenueLedgerEntry` of kind `SEAT_SURCHARGE` is written `POSTED`."

        Design: Corner/state_machines/seating_side_effect_execution_posts_a_surcharge_and_plans_the_courses
        """
        scenario = setup_floor(tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario)
        table_id = scenario["tables"][0]["id"]
        seafood = book_hold_seat(scenario, party["id"], "T4", table_id, party_size=4)

        seatings = seatings_for(reservation_id=seafood["reservation"]["id"])
        assert len(seatings) == 1
        assert seatings[0]["status"] == "ACTIVE"
        assert seatings[0]["guest_count"] == 4
        assert seatings[0]["seated_at"] == DEFAULT_CLOCK

        entries = ledger_entries(scenario["venue"]["id"], seafood["reservation"]["id"],
                                 "SEAT_SURCHARGE")
        assert len(entries) == 1
        assert entries[0]["status"] == "POSTED"
        assert entries[0]["entry_kind"] == "SEAT_SURCHARGE"
        assert entries[0]["amount_cents"] == seafood["reservation"]["seat_surcharge_cents"]
        assert entries[0]["amount_cents"] == 1925

        shows = shows_for(seafood["reservation"]["id"])
        assert len(shows) == 3
        assert {show["course_phase"] for show in shows} == {"SUSHI", "GRILL", "DESSERT"}
        assert all(show["status"] == "PLANNED" for show in shows)

        table = fresh_table(scenario, table_id)
        assert table["guests_seated"] == 4
        assert table["last_seated_at"] == DEFAULT_CLOCK

        reservation = seafood["reservation"]
        assert reservation["current_seating_id"]
        assert reservation["current_sushi_show_id"]
        assert reservation["current_grill_show_id"]

        chef = get_success_data(api_client.get_chef(reservation["chef_assignment_id"], FM))
        assert chef["current_table_id"] == table_id


class TestTableActionEndpoint:

    def test_table_seat_action_endpoint_enforces_its_state_preconditions(self):
        """PRD §3.4: "Seating is the transition from `HELD` to `SEATED`, and it is the
        densest moment in the workflow."
        PRD §3.1: "Grill tables move through four floor states: `AVAILABLE`, `SEATED`,
        `TURNING` and `MAINTENANCE`. A table becomes `SEATED` when the first guests
        arrive at it."

        Design: Corner/endpoints/table_seat_action_endpoint_enforces_its_state_preconditions
        """
        scenario = setup_floor(tier_codes=(), tables=(("T6", 6),), chefs=())
        table = scenario["tables"][0]

        response = api_client.post_table_event(table["id"], {"event_type": "SEAT"}, FM)
        assert response.status_code >= 400, \
            f"a SEAT with no reservation to seat must be refused: {response.status_code}"

        after = fresh_table(scenario, table["id"])
        assert after["status"] == "AVAILABLE"
        assert seatings_for(table_id=table["id"]) == []


class TestRunOpsSweep:

    def test_run_ops_bulk_release_reports_partial_state_per_venue(self):
        """PRD §3.3: "When the batch epoch runs, any booking still `HELD` whose
        `hold_until` has passed moves back to `REQUESTED`, `hold_until` and `table_id`
        are both cleared, and the released grill table returns to `AVAILABLE` unless it
        still carries another `ACTIVE` seating."
        PRD §2.5: "`ops_epoch` is a separate counter, starting at 0, that advances by
        exactly one each time the venue's batch epoch is run."

        Design: Corner/endpoints/run_ops_bulk_release_reports_partial_state_per_venue
        """
        scenario = setup_floor(tables=(("T4", 4), ("T2", 2)), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario)

        expiring = create_booking(scenario, party["id"], "T4", party_size=4)
        submit_booking(expiring["id"])
        grant_hold(expiring["id"], scenario["tables"][0]["id"])

        advance_clock(DEFAULT_CLOCK, 30)

        fresh = create_booking(scenario, party["id"], "T2", party_size=2,
                               scheduled_time="2026-09-03T20:00:00Z")
        submit_booking(fresh["id"])
        grant_hold(fresh["id"], scenario["tables"][1]["id"])

        epoch = get_success_data(api_client.run_ops(scenario["venue"]["id"], FM))
        assert epoch["ops_epoch"] == 1

        released = read_reservation(expiring["id"])
        assert released["status"] == "REQUESTED"
        assert released["hold_until"] is None
        assert released["table_id"] is None

        kept = read_reservation(fresh["id"])
        assert kept["status"] == "HELD"
        assert kept["hold_until"] == "2026-09-02T12:50:00Z"
        assert kept["table_id"] == scenario["tables"][1]["id"]


class TestConditionalSeating:

    def test_reservation_seat_is_conditionally_allowed_only_for_a_live_hold(self):
        """PRD §3.4: "refused with `ERR_HOLD_WINDOW_CLOSED` (HTTP 409) when the clock
        has already reached or passed `hold_until`, because an expired window is
        released rather than seated."
        PRD §3.3: "The request is refused with `ERR_VENTILATION_FREEZE` while the
        venue is frozen" (not applicable here) — the sweep then releases the stale hold.

        Design: Corner/endpoints/reservation_seat_is_conditionally_allowed_only_for_a_live_hold
        """
        scenario = setup_floor(tables=(("T2", 2),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario)
        reservation = create_booking(scenario, party["id"], "T2", party_size=2)
        submit_booking(reservation["id"])
        grant_hold(reservation["id"], scenario["tables"][0]["id"])

        advance_clock(DEFAULT_CLOCK, 21)
        response = api_client.seat_reservation(reservation["id"], HOST)
        validate_error(response, ApiErrorId.ERR_HOLD_WINDOW_CLOSED)

        get_success_data(api_client.run_ops(scenario["venue"]["id"], FM))

        response2 = api_client.seat_reservation(reservation["id"], HOST)
        validate_error(response2, ApiErrorId.ERR_INVALID_STATE)

        after = read_reservation(reservation["id"])
        assert after["hold_count"] == 1
        assert after["hold_until"] is None