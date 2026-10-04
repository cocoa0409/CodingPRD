"""Depth probes on the state machines and the cascades: the chef-rotation cycle, the
parallel dessert/celebration phases, the sushi restart cycle, the ventilation and
turn cascades, the no-show chain, and the compensating round trips.
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
    clear_chef,
    create_booking,
    create_party,
    fire_sushi_ticket,
    fresh_venue_version,
    grant_hold,
    ledger_entries,
    prepare_table_for_turn,
    read_party,
    read_reservation,
    rotate_suppress_chef,
    schedule_table_window,
    schedule_ventilation_window,
    seat_booking,
    seatings_for,
    seed_seated_booking_with_finished_grill,
    set_clock,
    setup_floor,
    shows_for,
    submit_booking,
    sushi_event,
)
from test_helpers.test_users import make_chef_headers

BIRTHDAY_CLOCK = "2026-09-02T12:00:00Z"


class TestChefRotationCycle:

    def test_clearing_chef_returns_to_on_station_with_a_freshly_assigned_position(self):
        """PRD §3.1: "From `CLEARING` the chef either clocks out with `CLOCK_OUT`,
        returning to `OFF_SHIFT` with `sequence_index` cleared, or is pushed back onto
        the line by a `FloorManager` using `ROTATE_SUPPRESS`, which returns the chef to
        `ON_STATION` with a freshly assigned `sequence_index` computed the same way as
        on clock-in."
        PRD §3.1: "On clock-in the chef's `sequence_index` is set to one more than the
        highest `sequence_index` among chefs at the venue already on station, or to 1
        when there are none."

        Design: Difficulty/non_linear_state_machine/chef_rotation_cyclic_clearing_return_to_on_station
        """
        scenario = setup_floor(tier_codes=(), tables=(), chefs=(("Kenji Ito", "ZONE_A"),
                                                               ("Ana Ruiz", "ZONE_B")))
        chef1, chef2 = scenario["chefs"]
        assert get_success_data(api_client.get_chef(chef1["id"], FM))["sequence_index"] == 1
        assert get_success_data(api_client.get_chef(chef2["id"], FM))["sequence_index"] == 2

        cleared = clear_chef(chef1["id"])
        assert cleared["status"] == "CLEARING"
        assert cleared["current_table_id"] is None

        still_on_station = [chef for chef in (chef1, chef2)
                            if get_success_data(api_client.get_chef(chef["id"], FM))["status"]
                            == "ON_STATION"]
        highest = max(get_success_data(api_client.get_chef(c["id"], FM))["sequence_index"]
                      for c in still_on_station)

        revived = rotate_suppress_chef(chef1["id"])
        assert revived["status"] == "ON_STATION"
        assert revived["sequence_index"] == highest + 1
        assert revived["sequence_index"] != 1
        assert revived["completed_show_count"] == 0

    def test_second_chef_is_refused_the_occupied_station_zone(self):
        """PRD §3.1: "the clock-in is refused with `ERR_STATION_OCCUPIED` (HTTP 409)
        when another chef at the same venue already holds the same `station_zone` while
        on station."
        PRD §2.5: "the floor will not put two chefs on station in the same zone at the
        same time."

        Design: Difficulty/non_linear_state_machine/chef_rotation_cyclic_clearing_return_to_on_station
        """
        scenario = setup_floor(tier_codes=(), tables=(),
                               chefs=(("Kenji Ito", "ZONE_A"),), clock_in=0)
        first = get_success_data(api_client.create_chef(
            {"venue_id": scenario["venue"]["id"], "chef_name": "Ana Ruiz",
             "station_zone": "ZONE_A"}, FM))

        version = fresh_venue_version(scenario)
        validate_success(api_client.post_chef_event(
            scenario["chefs"][0]["id"],
            {"event_type": "CLOCK_IN", "expected_venue_version": version},
            make_chef_headers(scenario["chefs"][0]["id"])))

        version2 = fresh_venue_version(scenario)
        response = api_client.post_chef_event(
            first["id"], {"event_type": "CLOCK_IN", "expected_venue_version": version2},
            make_chef_headers(first["id"]))
        validate_error(response, ApiErrorId.ERR_STATION_OCCUPIED)
        assert get_success_data(api_client.get_chef(first["id"], FM))["status"] == "OFF_SHIFT"


class TestParallelCoursePhases:

    def test_celebration_row_is_created_by_the_dessert_start_not_before(self):
        """PRD §3.5: "a `CELEBRATION` phase, which only ever comes into existence when a
        `DESSERT` phase starts on a booking whose `celebration` is not `NONE`."
        PRD §3.5: "A `DESSERT` start on a celebration booking additionally creates the
        `CELEBRATION` row at `PLANNED` if none exists yet."

        Design: Difficulty/non_linear_state_machine/show_parallel_dessert_and_celebration_phases_same_table
        """
        scenario = setup_floor(tables=(("T6", 6),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="PLATINUM")
        seafood = seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T6", scenario["tables"][0]["id"], party_size=3,
            celebration="BIRTHDAY")

        assert shows_for(seafood["reservation"]["id"], "CELEBRATION") == []

        chef_id = seafood["chef_id"]
        set_clock(seafood["last_instant"])
        dessert = shows_for(seafood["reservation"]["id"], "DESSERT")[0]
        validate_success(api_client.post_show_event(dessert["id"], "START",
                                                    make_chef_headers(chef_id)))

        celebration_rows = shows_for(seafood["reservation"]["id"], "CELEBRATION")
        assert len(celebration_rows) == 1
        assert celebration_rows[0]["status"] == "PLANNED"
        assert celebration_rows[0]["id"] != dessert["id"]

    def test_dessert_and_celebration_progress_independently_at_the_same_table(self):
        """PRD §3.5: "once that row is started, the dessert and celebration phases
        progress independently at the same table."
        PRD §3.5: "a phase may instead be driven to `SKIPPED` from either `PLANNED` or
        `STARTED`, and a skipped phase may be reinstated back to `PLANNED`."

        Design: Difficulty/non_linear_state_machine/show_parallel_dessert_and_celebration_phases_same_table
        """
        scenario = setup_floor(tables=(("T6", 6),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="PLATINUM")
        seafood = seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T6", scenario["tables"][0]["id"], party_size=3,
            celebration="BIRTHDAY")
        chef_id = seafood["chef_id"]

        # The GRILL show is finished, so the chef has left the grill: §3.5 requires
        # the assigned chef to be CLEARING before the CELEBRATION phase may start.
        clear_chef(chef_id)

        set_clock(seafood["last_instant"])
        dessert = shows_for(seafood["reservation"]["id"], "DESSERT")[0]
        validate_success(api_client.post_show_event(dessert["id"], "START",
                                                    make_chef_headers(chef_id)))
        celebration = shows_for(seafood["reservation"]["id"], "CELEBRATION")[0]

        started = validate_success(api_client.post_show_event(
            celebration["id"], "START", make_chef_headers(chef_id)))
        assert started["status"] == "STARTED"

        dessert_now = get_success_data(api_client.get_show(dessert["id"], FM))
        assert dessert_now["status"] == "STARTED"
        assert dessert_now["status"] != started["status"] or dessert_now["id"] != started["id"]

        skipped = validate_success(api_client.post_show_event(dessert["id"], "SKIP", FM))
        assert skipped["status"] == "SKIPPED"

        celebration_after = get_success_data(api_client.get_show(celebration["id"], FM))
        assert celebration_after["status"] == "STARTED"

        reinstated = validate_success(api_client.post_show_event(dessert["id"], "REINSTATE", FM))
        assert reinstated["status"] == "PLANNED"
        assert reinstated["actual_start_at"] is None
        assert read_reservation(seafood["reservation"]["id"])["status"] == "SEATED"


class TestSushiRestartCycle:

    def _seated_with_ticket(self):
        scenario = setup_floor(tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        seafood = book_hold_seat(scenario, party["id"], "T4",
                                 scenario["tables"][0]["id"], party_size=4)
        chef_id = seafood["reservation"]["chef_assignment_id"]
        return scenario, seafood, chef_id

    def test_a_late_plate_is_remade_from_raw_and_keeps_its_portion_count(self):
        """PRD §3.5: "The second step is additionally time-gated: it may only happen
        while the clock is no later than `requested_at` plus the sushi plate lateness
        constant of 8 minutes, after which the only legal move on a plated ticket is
        backwards to `RAW_CUT`."
        PRD §3.5: "a restart moves `PLATED` back to `RAW_CUT` and retains `quantity`,
        so the plate is remade from raw."

        Design: Difficulty/non_linear_state_machine/sushi_prep_phase_cyclic_restart_from_plated
        """
        scenario, seafood, chef_id = self._seated_with_ticket()
        ticket = fire_sushi_ticket(scenario, seafood["reservation"]["id"], chef_id=chef_id,
                                   item_code="SPICY-TUNA-ROLL", quantity=2,
                                   requested_at="2026-09-03T19:05:00Z",
                                   unit_price_cents=1800)

        set_clock("2026-09-03T19:05:00Z")
        validate_success(sushi_event(ticket["id"], "ADVANCE", chef_id))

        set_clock("2026-09-03T19:11:00Z")
        plated = validate_success(sushi_event(ticket["id"], "ADVANCE", chef_id))
        assert plated["prep_phase"] == "PLATED"

        set_clock("2026-09-03T19:14:00Z")
        restarted = validate_success(sushi_event(ticket["id"], "RESTART", chef_id))
        assert restarted["prep_phase"] == "RAW_CUT"
        assert restarted["quantity"] == 2
        assert restarted["status"] == "OPEN"

    def test_restart_releases_the_counter_for_a_second_ticket(self):
        """PRD §3.5: "Only `OPEN` tickets with `prep_phase` `PLATED` occupy the counter;
        a voided ticket releases its capacity immediately."
        PRD §3.5: "The second step is additionally time-gated: it may only happen while
        the clock is no later than `requested_at` plus the sushi plate lateness constant
        of 8 minutes."

        Design: Difficulty/non_linear_state_machine/sushi_prep_phase_cyclic_restart_from_plated
        """
        scenario, seafood, chef_id = self._seated_with_ticket()
        first = fire_sushi_ticket(scenario, seafood["reservation"]["id"], chef_id=chef_id,
                                  item_code="SPICY-TUNA-ROLL", quantity=2,
                                  requested_at="2026-09-03T19:05:00Z",
                                  unit_price_cents=1800)
        set_clock("2026-09-03T19:05:00Z")
        validate_success(sushi_event(first["id"], "ADVANCE", chef_id))
        set_clock("2026-09-03T19:11:00Z")
        validate_success(sushi_event(first["id"], "ADVANCE", chef_id))
        set_clock("2026-09-03T19:14:00Z")
        validate_success(sushi_event(first["id"], "RESTART", chef_id))

        second = fire_sushi_ticket(scenario, seafood["reservation"]["id"], chef_id=chef_id,
                                   item_code="SALMON-NIGIRI", quantity=4,
                                   requested_at="2026-09-03T19:10:00Z",
                                   unit_price_cents=1200)
        validate_success(sushi_event(second["id"], "ADVANCE", chef_id))
        plated = validate_success(sushi_event(second["id"], "ADVANCE", chef_id))
        assert plated["prep_phase"] == "PLATED"

        first_after = get_success_data(api_client.get_sushi_ticket(first["id"], FM))
        assert first_after["prep_phase"] == "RAW_CUT"


class TestVentilationCascade:

    def test_accepting_a_ventilation_window_unwinds_the_floor_five_hops_down(self):
        """PRD §3.7: "It cascades in five hops. First, the venue's `status` moves from
        `ACTIVE` to `VENTILATION_HOLD` and `occupancy_freeze` becomes true, which blocks
        every seating episode at the venue while it holds. Second, each grill table at
        the venue that is `AVAILABLE` or `SEATED` moves to `MAINTENANCE` with
        `maintenance_resume_at` set to the accepted window's `planned_end_at`. Third,
        because each of those tables has left the floor, each table drives its own
        occupancy rows from `ACTIVE` to `VACATED`. Fourth, each booking left with no
        remaining `ACTIVE` occupancy row moves to `ABANDONED`, with `hold_until` and
        `table_id` both cleared."

        Design: Difficulty/transitive_cascade/ventilation_hold_five_hop_cascade_to_party_credit
        """
        scenario = setup_floor(tables=(("T6", 6), ("T4", 4), ("T2", 2)),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        table_id = scenario["tables"][1]["id"]
        seafood = book_hold_seat(scenario, party["id"], "T4", table_id, party_size=4)

        window = schedule_ventilation_window(scenario, "2026-09-04T09:00:00Z",
                                             "2026-09-04T11:00:00Z")
        assert window["status"] == "ACTIVE"

        venue = get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))
        assert venue["status"] == "VENTILATION_HOLD"
        assert venue["occupancy_freeze"] is True

        for table in scenario["tables"]:
            current = get_success_data(api_client.get_table(table["id"], FM))
            assert current["status"] == "MAINTENANCE"
            assert current["maintenance_resume_at"] == "2026-09-04T11:00:00Z"
            assert current["guests_seated"] == 0

        seatings = seatings_for(table_id=table_id, status="VACATED")
        assert len(seatings) == 1
        assert seatings[0]["actual_vacated_at"] == DEFAULT_CLOCK

        abandoned = read_reservation(seafood["reservation"]["id"])
        assert abandoned["status"] == "ABANDONED"
        assert abandoned["table_id"] is None
        assert abandoned["hold_until"] is None

    def test_the_fifth_hop_credits_the_party_by_the_voided_charge(self):
        """PRD §3.7: "Fifth, each booking that has just been abandoned drives every
        `POSTED` `VenueLedgerEntry` for it to `VOIDED`, and each such void credits the
        party's `loyalty_credit_cents` by the entry's positive amount."
        PRD §3.9: "Its raw value is the tier's `base_rate_per_guest_cents` multiplied by
        the guests billed — the smaller of the party size and the cap of 3 — and divided
        by one more than the party size. The raw value is then ceilinged once, per
        booking and not per guest, to the next whole multiple of 25 cents."

        Design: Difficulty/transitive_cascade/ventilation_hold_five_hop_cascade_to_party_credit
        """
        scenario = setup_floor(tables=(("T6", 6), ("T4", 4), ("T2", 2)),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        credit_before = read_party(party["id"])["loyalty_credit_cents"]
        seafood = book_hold_seat(scenario, party["id"], "T4", scenario["tables"][1]["id"],
                                 party_size=4)
        reservation_id = seafood["reservation"]["id"]

        schedule_ventilation_window(scenario, "2026-09-04T09:00:00Z",
                                    "2026-09-04T11:00:00Z")

        entries = ledger_entries(scenario["venue"]["id"], reservation_id, "SEAT_SURCHARGE")
        assert len(entries) == 1
        assert entries[0]["status"] == "VOIDED"
        assert entries[0]["amount_cents"] == 1925

        credit_after = read_party(party["id"])["loyalty_credit_cents"]
        assert credit_after == credit_before + entries[0]["amount_cents"]
        assert credit_after > 0


class TestTurnCascade:

    def test_turning_a_table_vacates_its_occupancy_and_leaves_the_party_alone(self):
        """PRD §2.6: "`occupied_minutes` reports the whole number of minutes between
        `seated_at` and `actual_vacated_at` once the row is `VACATED`."
        PRD §3.8: "when a table turns and the recomputed total exceeds the turn-debt
        escalation threshold, every party at that venue whose `no_show_count` has
        reached 2 is moved to `RESTRICTED`."

        Design: Difficulty/transitive_cascade/turn_vacate_three_hop_cascade_to_party_restriction
        """
        scenario = setup_floor(clock="2026-09-03T12:10:00Z",
                               tables=(("T2", 2), ("T4", 4)),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario)
        table_id = scenario["tables"][0]["id"]

        set_clock("2026-09-03T11:00:00Z")
        scenario["clock"] = "2026-09-03T11:00:00Z"
        seafood = seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T2", table_id, party_size=2,
            scheduled_time="2026-09-03T11:00:00Z")

        prepare_table_for_turn(seafood)
        set_clock("2026-09-03T12:10:00Z")
        validate_success(api_client.post_table_event(table_id, {"event_type": "TURN"}, FM))

        seating = get_success_data(api_client.get_seating(seafood["seating_id"], FM))
        assert seating["status"] == "VACATED"
        assert seating["actual_vacated_at"] == "2026-09-03T12:10:00Z"
        assert seating["occupied_minutes"] == 70

        assert read_party(party["id"])["status"] == "ACTIVE"
        assert read_party(party["id"])["no_show_count"] == 0
        assert get_success_data(api_client.get_table(table_id, FM))["guests_seated"] == 0

    def test_the_shortfall_counter_only_moves_for_vacated_rows_that_ran_short(self):
        """PRD §3.8: "Whenever an occupancy row is vacated, its over- or under-run
        against the tier's turn-time standard is bucketed. The bucket index is the
        shortfall in whole minutes divided by the five-minute bucket width, floored."

        Design: Difficulty/transitive_cascade/turn_vacate_three_hop_cascade_to_party_restriction
        """
        scenario = setup_floor(clock="2026-09-03T12:10:00Z",
                               tables=(("T2", 2),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario)
        table_id = scenario["tables"][0]["id"]

        set_clock("2026-09-03T11:00:00Z")
        scenario["clock"] = "2026-09-03T11:00:00Z"
        seafood = seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T2", table_id, party_size=2,
            scheduled_time="2026-09-03T11:00:00Z")

        debt_before = get_success_data(api_client.get_venue(
            scenario["venue"]["id"], FM))["shortfall_turn_debt_minutes"]

        prepare_table_for_turn(seafood)
        set_clock("2026-09-03T12:10:00Z")
        validate_success(api_client.post_table_event(table_id, {"event_type": "TURN"}, FM))

        seating = get_success_data(api_client.get_seating(seafood["seating_id"], FM))
        standard = scenario["tiers"]["T2"]["turn_time_standard_minutes"]
        assert seating["occupied_minutes"] == 70
        assert seating["occupied_minutes"] > standard

        after = get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))
        assert after["shortfall_turn_debt_minutes"] == debt_before


class TestNoShowChain:

    def test_marking_a_seated_booking_no_show_is_refused_as_invalid_state(self):
        """PRD §3.8: "Marking a booking `NO_SHOW` from `REQUESTED` requires the clock to
        be past `scheduled_time` and is otherwise rejected with `ERR_INVALID_STATE`;
        marking it from `HELD` requires the clock to be past `scheduled_time` plus the
        no-show grace constant."

        Design: Difficulty/transitive_cascade/no_show_three_hop_cascade_to_reusable_credit
        """
        scenario = setup_floor(tables=(("T2", 2),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="SILVER", name="Marcus Bell",
                             phone="212-555-0164")
        reservation = create_booking(scenario, party["id"], "T2", party_size=2)
        submit_booking(reservation["id"])
        grant_hold(reservation["id"], scenario["tables"][0]["id"])
        seated = seat_booking(reservation["id"])
        assert seated["status"] == "SEATED"

        advance_clock(DEFAULT_CLOCK, 14 * 60)
        response = api_client.post_reservation_event(reservation["id"], "MARK_NO_SHOW", HOST)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        assert read_reservation(reservation["id"])["status"] == "SEATED"
        assert read_party(party["id"])["no_show_count"] == 0

    def test_no_show_on_a_held_booking_voids_the_posted_charge_and_credits_the_party(self):
        """PRD §3.8: "A `Host` posts the `MARK_NO_SHOW` event, the party's
        `no_show_count` advances by one, and the booking's `hold_until` and `table_id`
        are cleared" and "the booking's posted ledger entries are voided, each void
        crediting the party's `loyalty_credit_cents` by its positive amount."
        PRD §3.7: "The ledger entries voided by the abandonment cascade are restored to
        `POSTED`."

        Design: Difficulty/transitive_cascade/no_show_three_hop_cascade_to_reusable_credit
        """
        scenario = setup_floor(tables=(("T4", 4), ("T4", 4)),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="SILVER", name="Marcus Bell",
                             phone="212-555-0164")
        table_id = scenario["tables"][0]["id"]

        set_clock("2026-09-03T09:00:00Z")
        scenario["clock"] = "2026-09-03T09:00:00Z"
        seafood = book_hold_seat(scenario, party["id"], "T4", table_id, party_size=4,
                                 scheduled_time="2026-09-03T19:00:00Z")
        reservation_id = seafood["reservation"]["id"]

        window = schedule_ventilation_window(scenario, "2026-09-03T09:30:00Z",
                                            "2026-09-03T10:00:00Z")
        assert read_reservation(reservation_id)["status"] == "ABANDONED"

        validate_success(api_client.reopen_maintenance_window(window["id"], FM))
        reopened = validate_success(api_client.reopen_reservation(
            reservation_id, {"table_id": table_id}, HOST))
        assert reopened["status"] == "HELD"

        posted = ledger_entries(scenario["venue"]["id"], reservation_id, "SEAT_SURCHARGE")
        assert len(posted) == 1
        assert posted[0]["status"] == "POSTED"

        credit_before = read_party(party["id"])["loyalty_credit_cents"]
        set_clock("2026-09-04T02:00:00Z")
        marked = validate_success(api_client.post_reservation_event(
            reservation_id, "MARK_NO_SHOW", HOST))

        assert marked["status"] == "NO_SHOW"
        assert marked["hold_until"] is None
        assert marked["table_id"] is None
        assert read_party(party["id"])["no_show_count"] == 1

        voided = ledger_entries(scenario["venue"]["id"], reservation_id, "SEAT_SURCHARGE")
        assert len(voided) == 1
        assert voided[0]["status"] == "VOIDED"
        assert read_party(party["id"])["loyalty_credit_cents"] == (
            credit_before + voided[0]["amount_cents"])
        assert read_party(party["id"])["status"] == "ACTIVE"


class TestCompensatingRoundTrip:

    def test_abandon_then_reopen_conserves_the_party_credit_balance(self):
        """PRD §3.7: "The ledger entries voided by the abandonment cascade are restored
        to `POSTED` and the party's credit is reduced again by the same amount, but only
        for entries voided by the abandonment cascade."
        PRD §3.7: "Fifth, each booking that has just been abandoned drives every
        `POSTED` `VenueLedgerEntry` for it to `VOIDED`, and each such void credits the
        party's `loyalty_credit_cents` by the entry's positive amount."

        Design: Difficulty/compensating_invariant/abandon_then_reopen_keeps_venue_party_credit_debt_at_zero
        """
        scenario = setup_floor(tables=(("T4", 4), ("T2", 2)),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        table_id = scenario["tables"][0]["id"]
        seafood = book_hold_seat(scenario, party["id"], "T4", table_id, party_size=4)
        reservation_id = seafood["reservation"]["id"]

        credit_before = read_party(party["id"])["loyalty_credit_cents"]
        window = schedule_ventilation_window(scenario, "2026-09-03T09:00:00Z",
                                            "2026-09-03T10:00:00Z")
        credit_after_abandon = read_party(party["id"])["loyalty_credit_cents"]
        assert credit_after_abandon > credit_before

        validate_success(api_client.reopen_maintenance_window(window["id"], FM))
        validate_success(api_client.reopen_reservation(
            reservation_id, {"table_id": table_id}, HOST))

        assert read_party(party["id"])["loyalty_credit_cents"] == credit_before
        assert read_party(party["id"])["loyalty_credit_cents"] >= 0

    def test_the_charge_ends_posted_rather_than_deleted(self):
        """PRD §3.7: "The ledger entries voided by the abandonment cascade are restored
        to `POSTED` and the party's credit is reduced again by the same amount."
        PRD §3.7: "Voiding moves a `VenueLedgerEntry` from `POSTED` to `VOIDED` and
        credits the party's `loyalty_credit_cents` by its `amount_cents` when that
        amount is positive."

        Design: Difficulty/compensating_invariant/abandon_then_reopen_keeps_venue_party_credit_debt_at_zero
        """
        scenario = setup_floor(tables=(("T4", 4), ("T2", 2)),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        table_id = scenario["tables"][0]["id"]
        seafood = book_hold_seat(scenario, party["id"], "T4", table_id, party_size=4)
        reservation_id = seafood["reservation"]["id"]

        window = schedule_ventilation_window(scenario, "2026-09-03T09:00:00Z",
                                            "2026-09-03T10:00:00Z")
        voided = ledger_entries(scenario["venue"]["id"], reservation_id)
        assert len(voided) == 1
        assert voided[0]["status"] == "VOIDED"

        validate_success(api_client.reopen_maintenance_window(window["id"], FM))
        validate_success(api_client.reopen_reservation(
            reservation_id, {"table_id": table_id}, HOST))

        restored = ledger_entries(scenario["venue"]["id"], reservation_id)
        assert len(restored) == 1
        assert restored[0]["id"] == voided[0]["id"]
        assert restored[0]["status"] == "POSTED"
        assert restored[0]["amount_cents"] == voided[0]["amount_cents"]


class TestPerEpochFixedPoint:

    def test_a_second_epoch_on_an_unchanged_floor_drifts_by_zero(self):
        """PRD §2.9: "Because these derived figures are recomputed rather than
        accumulated, a venue whose inputs are unchanged between two consecutive epochs
        is charged exactly the same amount twice and drifts by zero."
        PRD §3.8: "Each time the batch epoch advances, the venue's `restaurant_charge_cents`
        is recomputed from scratch — never accumulated — as the billable guest count
        multiplied by a per-guest assignment fee of 299 cents."

        Design: Difficulty/compensating_invariant/run_ops_recompute_leaves_the_restaurant_charge_a_fixed_point
        """
        scenario = setup_floor(tables=(("T6", 6), ("T4", 4), ("T2", 2)), chefs=())
        venue_id = scenario["venue"]["id"]

        first = validate_success(api_client.run_ops(venue_id, FM))
        second = validate_success(api_client.run_ops(venue_id, FM))

        assert first["ops_epoch"] == 1
        assert second["ops_epoch"] == 2
        assert first["restaurant_charge_cents"] == second["restaurant_charge_cents"]
        assert second["restaurant_charge_cents"] == 12 * 299 * 0.90

    def test_the_read_side_report_is_not_accumulated_into_the_charge(self):
        """PRD §3.8: "The billable guest count is the sum, across the venue's grill
        tables, of the smaller of each table's `seat_capacity` and the assignable guest
        cap of 12."
        PRD §3.8: "The read-side venue cost report is computed differently and is never
        persisted."

        Design: Difficulty/compensating_invariant/run_ops_recompute_leaves_the_restaurant_charge_a_fixed_point
        """
        scenario = setup_floor(tables=(("T6", 6), ("T4", 4), ("T2", 2)), chefs=())
        venue_id = scenario["venue"]["id"]

        report = get_success_data(api_client.get_cost_report(venue_id, FM))
        assert report["billable_guest_count"] == 6 + 4 + 2

        first = get_success_data(api_client.run_ops(venue_id, FM))
        second = get_success_data(api_client.run_ops(venue_id, FM))
        assert second["restaurant_charge_cents"] == first["restaurant_charge_cents"]
        assert second["restaurant_charge_cents"] != first["restaurant_charge_cents"] * 2


class TestMaintenanceWindowCascade:

    def test_accepting_a_table_window_takes_the_table_out_and_cascades_a_rebuild(self):
        """PRD §3.7: "The accepted window drives its table into `MAINTENANCE` with
        `maintenance_resume_at` set to the window's `planned_end_at`."
        PRD §3.7: "A second `MaintenanceWindow` of kind `GRILL_REBUILD` is created
        `SCHEDULED` against the same `table_id`, beginning at the accepted window's
        `planned_end_at` and ending one grill-rebuild duration later."

        Design: Difficulty/compensating_invariant/resume_at_threshold_five_hop_cascade_to_hood_filter_reset
        """
        scenario = setup_floor(tier_codes=("T6",), tables=(("T6", 6),), chefs=(),
                               clock="2026-09-04T08:00:00Z")
        table_id = scenario["tables"][0]["id"]

        window = schedule_table_window(scenario, table_id,
                                       planned_start_at="2026-09-04T08:30:00Z",
                                       planned_end_at="2026-09-04T09:00:00Z",
                                       accept=True)
        assert window["status"] == "ACTIVE"

        table = get_success_data(api_client.get_table(table_id, FM))
        assert table["status"] == "MAINTENANCE"
        assert table["maintenance_resume_at"] == "2026-09-04T09:00:00Z"

        cascaded = get_success_data(api_client.list_maintenance_windows(
            FM, {"venue_id": scenario["venue"]["id"], "table_id": table_id,
                 "status": "SCHEDULED"}))
        assert len(cascaded) >= 1
        assert cascaded[0]["maintenance_kind"] == "GRILL_REBUILD"
        assert cascaded[0]["planned_start_at"] == "2026-09-04T09:00:00Z"

    def test_releasing_a_table_from_maintenance_clears_the_resume_and_resets_the_hood(self):
        """PRD §3.1: "A venue's grill table may also be released from maintenance early
        through a `FloorManager` action carrying `expected_venue_version`; the table
        returns to `AVAILABLE` with `maintenance_resume_at` cleared, the matching
        scheduled window is completed, and a grill-rebuild window additionally resets
        `hood_filter_life_index`."
        PRD §3.7: "a grill-rebuild window that completes resets the venue's
        `hood_filter_life_index` to 0."

        Design: Difficulty/compensating_invariant/resume_at_threshold_five_hop_cascade_to_hood_filter_reset
        """
        scenario = setup_floor(tier_codes=("T6", "T4"), tables=(("T4", 4), ("T6", 6)),
                               chefs=(("Kenji Ito", "ZONE_A"),),
                               clock="2026-09-04T08:00:00Z")
        repair_table = scenario["tables"][1]["id"]
        serving_table = scenario["tables"][0]["id"]

        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        set_clock("2026-09-03T19:00:00Z")
        scenario["clock"] = "2026-09-03T19:00:00Z"
        seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T4", serving_table, party_size=4)

        set_clock("2026-09-04T08:00:00Z")
        schedule_table_window(scenario, repair_table,
                              planned_start_at="2026-09-04T08:30:00Z",
                              planned_end_at="2026-09-04T09:00:00Z", accept=True)

        before = get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))
        assert before["hood_filter_life_index"] >= 1

        released = validate_success(api_client.maintenance_release(
            scenario["venue"]["id"], repair_table,
            {"expected_venue_version": before["version"]}, FM))
        assert released["status"] == "AVAILABLE"
        assert released["maintenance_resume_at"] is None

        after = get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))
        assert after["hood_filter_life_index"] == 0