"""Depth probes on interval arithmetic, cross-entity gating, the priority pairs that
separate two error categories, the numeric thresholds, and the window-reopen cascade.
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
    fresh_table,
    grant_hold,
    grant_hold_at_later_clock,
    ledger_entries,
    read_party,
    read_reservation,
    schedule_ventilation_window,
    seatings_for,
    seat_booking,
    seed_seated_booking_with_finished_grill,
    set_clock,
    setup_floor,
    shows_for,
    submit_booking,
    sushi_event,
)
from test_helpers.test_users import make_chef_headers


class TestHalfOpenGrillInterval:

    def test_a_window_starting_at_the_vacate_instant_does_not_block_the_seating(self):
        """PRD §2.6: "Occupancy on a grill table is modelled as a half-open interval.
        A `TableSeating` row records `seated_at`, an `expected_vacate_at` derived by the
        turn-over rule in §3.4, and an `actual_vacated_at` that stays null while the row
        is `ACTIVE`. The interval the row occupies is `seated_at` up to but not including
        `expected_vacate_at`."
        PRD §3.4: "refused with `ERR_MAINTENANCE_CONFLICT` when the interval the seating
        would occupy overlaps a scheduled or active maintenance window on that table."
        PRD §3.4: "the `expected_vacate_at` is that start instant plus the tier's
        `turn_time_standard_minutes` when the booking's `celebration` is `NONE`."

        Design: Difficulty/resource_temporal_overlap/half_open_table_seating_intervals_abut_without_conflict
        """
        scenario = setup_floor(clock="2026-09-03T12:00:00Z",
                               tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        table_id = scenario["tables"][0]["id"]

        set_clock("2026-09-03T18:55:00Z")
        scenario["clock"] = "2026-09-03T18:55:00Z"
        # Seat a party of two on the four-seat table so a second party of two can
        # still be combined onto it — the shared-grill occupancy this test probes.
        reservation = create_booking(scenario, party["id"], "T4", party_size=2,
                                     scheduled_time="2026-09-03T18:55:00Z")
        submit_booking(reservation["id"])
        grant_hold(reservation["id"], table_id)
        seated = seat_booking(reservation["id"])
        assert seated["status"] == "SEATED"

        seating = seatings_for(reservation_id=reservation["id"])[0]
        # seated_at is stamped at the clock (§3.4); the turn-over rule anchors
        # expected_vacate_at on the scheduled_time: snapped to 18:55 then advanced
        # one bucket width to a 19:00 start, plus the T4 60-minute turn time.
        assert seating["seated_at"] == "2026-09-03T18:55:00Z"
        assert seating["expected_vacate_at"] == "2026-09-03T20:00:00Z"

        # A window opening exactly at the excluded endpoint abuts rather than overlaps.
        window = get_success_data(api_client.create_maintenance_window(
            {"venue_id": scenario["venue"]["id"], "table_id": table_id,
             "maintenance_kind": "GRILL_REBUILD",
             "planned_start_at": "2026-09-03T20:00:00Z",
             "planned_end_at": "2026-09-03T21:00:00Z"}, FM))
        assert window["status"] == "SCHEDULED"

        second = create_booking(scenario, party["id"], "T4", party_size=2,
                                scheduled_time="2026-09-03T18:55:00Z")
        submit_booking(second["id"])
        held = grant_hold(second["id"], table_id)
        assert held["status"] == "HELD"
        assert held["table_id"] == table_id

    def test_a_window_overlapping_the_interval_blocks_the_seating(self):
        """PRD §2.6: "The interval the row occupies is `seated_at` up to but not
        including `expected_vacate_at`."
        PRD §3.4: "refused with `ERR_MAINTENANCE_CONFLICT` when the interval the seating
        would occupy overlaps a scheduled or active maintenance window on that table."

        Design: Difficulty/resource_temporal_overlap/half_open_table_seating_intervals_abut_without_conflict
        """
        scenario = setup_floor(clock="2026-09-03T12:00:00Z",
                               tables=(("T4", 4), ("T4", 4)),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        table_id = scenario["tables"][0]["id"]

        second = create_booking(scenario, party["id"], "T4", party_size=2,
                                scheduled_time="2026-09-03T18:55:00Z")
        submit_booking(second["id"])
        grant_hold(second["id"], table_id)

        # The seating would occupy [19:00, 20:00); a window opening at 19:55 overlaps it.
        get_success_data(api_client.create_maintenance_window(
            {"venue_id": scenario["venue"]["id"], "table_id": table_id,
             "maintenance_kind": "GRILL_REBUILD",
             "planned_start_at": "2026-09-03T19:55:00Z",
             "planned_end_at": "2026-09-03T21:00:00Z"}, FM))

        response = api_client.seat_reservation(second["id"], HOST)
        validate_error(response, ApiErrorId.ERR_MAINTENANCE_CONFLICT)

        assert seatings_for(reservation_id=second["id"]) == []
        assert read_reservation(second["id"])["status"] == "HELD"

class TestClosedSushiCounterInterval:

    def _seated_with_sushi(self):
        scenario = setup_floor(clock="2026-09-03T19:00:00Z",
                               tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        seafood = book_hold_seat(scenario, party["id"], "T4",
                                 scenario["tables"][0]["id"], party_size=4)
        chef_id = seafood["reservation"]["chef_assignment_id"]
        return scenario, seafood, chef_id

    def test_a_second_plating_sharing_the_first_tickets_edge_instant_is_refused(self):
        """PRD §3.5: "its occupancy is a closed interval from `requested_at` through
        `requested_at` plus the five-minute dwell constant, with both endpoints
        included. Any plating whose interval touches an already-occupying ticket at any
        point, including a single shared instant, is rejected at the sushi-plate-late
        rule with `ERR_SUSHI_PLATE_LATE` (HTTP 409); a second plating at exactly the
        first ticket's `requested_at` plus five minutes is therefore rejected and must
        begin strictly later."

        Design: Difficulty/resource_temporal_overlap/closed_sushi_counter_intervals_touching_at_an_instant_conflict
        """
        scenario, seafood, chef_id = self._seated_with_sushi()
        first = fire_sushi_ticket(scenario, seafood["reservation"]["id"], chef_id=chef_id,
                                  item_code="CALIFORNIA-ROLL", quantity=2,
                                  requested_at="2026-09-03T19:05:00Z",
                                  unit_price_cents=1600)
        set_clock("2026-09-03T19:05:00Z")
        validate_success(sushi_event(first["id"], "ADVANCE", chef_id))
        validate_success(sushi_event(first["id"], "ADVANCE", chef_id))

        second = fire_sushi_ticket(scenario, seafood["reservation"]["id"], chef_id=chef_id,
                                   item_code="SALMON-NIGIRI", quantity=4,
                                   requested_at="2026-09-03T19:10:00Z",
                                   unit_price_cents=1200)
        validate_success(sushi_event(second["id"], "ADVANCE", chef_id))

        set_clock("2026-09-03T19:12:00Z")
        response = sushi_event(second["id"], "ADVANCE", chef_id)
        validate_error(response, ApiErrorId.ERR_SUSHI_PLATE_LATE)

        frozen = get_success_data(api_client.get_sushi_ticket(second["id"], FM))
        assert frozen["prep_phase"] == "ROLLED"
        assert frozen["requested_at"] == "2026-09-03T19:10:00Z"

    def test_voiding_the_occupying_ticket_releases_the_counter(self):
        """PRD §3.5: "Only `OPEN` tickets with `prep_phase` `PLATED` occupy the counter;
        a voided ticket releases its capacity immediately, and a restage rebuilds the
        interval rather than extending it."
        PRD §3.5: "a voided ticket is frozen at the phase it had reached, and its
        counter capacity is released immediately."

        Design: Difficulty/resource_temporal_overlap/closed_sushi_counter_intervals_touching_at_an_instant_conflict
        """
        scenario, seafood, chef_id = self._seated_with_sushi()
        first = fire_sushi_ticket(scenario, seafood["reservation"]["id"], chef_id=chef_id,
                                  item_code="CALIFORNIA-ROLL", quantity=2,
                                  requested_at="2026-09-03T19:05:00Z",
                                  unit_price_cents=1600)
        set_clock("2026-09-03T19:05:00Z")
        validate_success(sushi_event(first["id"], "ADVANCE", chef_id))
        validate_success(sushi_event(first["id"], "ADVANCE", chef_id))

        second = fire_sushi_ticket(scenario, seafood["reservation"]["id"], chef_id=chef_id,
                                   item_code="SALMON-NIGIRI", quantity=4,
                                   requested_at="2026-09-03T19:10:00Z",
                                   unit_price_cents=1200)
        validate_success(sushi_event(second["id"], "ADVANCE", chef_id))

        set_clock("2026-09-03T19:12:00Z")
        validate_success(sushi_event(first["id"], "VOID", chef_id))
        assert get_success_data(api_client.get_sushi_ticket(first["id"], FM))["status"] == "VOIDED"

        plated = validate_success(sushi_event(second["id"], "ADVANCE", chef_id))
        assert plated["prep_phase"] == "PLATED"


class TestReservationVenueDependency:

    def test_a_hold_grant_is_gated_by_the_venues_freeze_flag(self):
        """PRD §3.3: "The hold is also refused while the venue's `occupancy_freeze` is
        true, with `ERR_VENTILATION_FREEZE` (HTTP 409)."
        PRD §2.5: "While the venue is in `VENTILATION_HOLD`, the boolean
        `occupancy_freeze` is true, and while that boolean holds no seating episode may
        begin anywhere on the floor."

        Design: Difficulty/cross_entity_state_dependency/reservation_holds_only_while_venue_is_not_frozen
        """
        scenario = setup_floor(clock="2026-09-03T09:00:00Z",
                               tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        reservation = create_booking(scenario, party["id"], "T4", party_size=4,
                                     scheduled_time="2026-09-04T19:00:00Z")
        submit_booking(reservation["id"])

        window = schedule_ventilation_window(scenario, "2026-09-03T09:00:00Z",
                                            "2026-09-03T10:00:00Z")
        frozen_venue = get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))
        assert frozen_venue["occupancy_freeze"] is True

        request = api_client.grant_hold(
            reservation["id"],
            {"expected_table_version": fresh_table(scenario, scenario["tables"][0]["id"])["version"],
             "table_id": scenario["tables"][0]["id"]},
            HOST)
        validate_error(request, ApiErrorId.ERR_VENTILATION_FREEZE)

        assert read_reservation(reservation["id"])["status"] == "REQUESTED"

        validate_success(api_client.reopen_maintenance_window(window["id"], FM))
        thawed = get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))
        assert thawed["occupancy_freeze"] is False

        held = validate_success(api_client.grant_hold(
            reservation["id"],
            {"expected_table_version": fresh_table(scenario, scenario["tables"][0]["id"])["version"],
             "table_id": scenario["tables"][0]["id"]},
            HOST))
        assert held["status"] == "HELD"

    def test_the_booking_itself_is_untouched_while_the_venue_freezes(self):
        """PRD §3.7: "A ventilation service window that is accepted freezes the entire
        venue: the venue transitions into `VENTILATION_HOLD`."
        PRD §2.5: "A venue enters `VENTILATION_HOLD` and leaves it only through the
        acceptance and release of a ventilation service window."

        Design: Difficulty/cross_entity_state_dependency/reservation_holds_only_while_venue_is_not_frozen
        """
        scenario = setup_floor(clock="2026-09-03T09:00:00Z",
                               tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        reservation = create_booking(scenario, party["id"], "T4", party_size=4,
                                     scheduled_time="2026-09-04T19:00:00Z")
        submit_booking(reservation["id"])
        before = read_reservation(reservation["id"])

        schedule_ventilation_window(scenario, "2026-09-03T09:00:00Z",
                                   "2026-09-03T10:00:00Z")

        after = read_reservation(reservation["id"])
        assert after["status"] == "REQUESTED"
        assert after["hold_count"] == before["hold_count"] == 0
        assert after["table_id"] is None
        assert seatings_for(reservation_id=reservation["id"]) == []


class TestCelebrationStartDependency:

    def _birthday_after_grill(self):
        scenario = setup_floor(clock="2026-09-02T12:00:00Z",
                               tables=(("T6", 6),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="PLATINUM")
        seafood = seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T6", scenario["tables"][0]["id"], party_size=3,
            celebration="BIRTHDAY")
        return scenario, seafood

    def test_the_celebration_start_waits_on_the_chefs_clearing_state(self):
        """PRD §3.5: "a `CELEBRATION` start requires the assigned `ChefAssignment` to be
        `CLEARING` rather than still on station."
        PRD §3.5: "Starting a phase is refused with `ERR_SHOW_DEPENDENCY` (HTTP 409)
        when its prerequisite phase has not reached `FINISHED`."

        Design: Difficulty/cross_entity_state_dependency/show_start_waits_on_the_assigned_chefs_clearing_state
        """
        scenario, seafood = self._birthday_after_grill()
        chef_id = seafood["chef_id"]
        set_clock(seafood["last_instant"])

        dessert = shows_for(seafood["reservation"]["id"], "DESSERT")[0]
        validate_success(api_client.post_show_event(dessert["id"], "START",
                                                    make_chef_headers(chef_id)))
        celebration = shows_for(seafood["reservation"]["id"], "CELEBRATION")[0]
        assert celebration["status"] == "PLANNED"

        assert get_success_data(api_client.get_chef(chef_id, FM))["status"] == "ON_STATION"
        refused = api_client.post_show_event(celebration["id"], "START",
                                             make_chef_headers(chef_id))
        validate_error(refused, ApiErrorId.ERR_SHOW_DEPENDENCY)

        celebration_after = get_success_data(api_client.get_show(celebration["id"], FM))
        assert celebration_after["status"] == "PLANNED"

    def test_clearing_the_chef_lets_the_same_call_succeed(self):
        """PRD §3.1: "the `CLEAR_FINISH` event moves the row from `ON_STATION` to
        `CLEARING` and clears `current_table_id`."
        PRD §3.5: "a `CELEBRATION` start requires the assigned `ChefAssignment` to be
        `CLEARING` rather than still on station."

        Design: Difficulty/cross_entity_state_dependency/show_start_waits_on_the_assigned_chefs_clearing_state
        """
        scenario, seafood = self._birthday_after_grill()
        chef_id = seafood["chef_id"]
        set_clock(seafood["last_instant"])

        dessert = shows_for(seafood["reservation"]["id"], "DESSERT")[0]
        validate_success(api_client.post_show_event(dessert["id"], "START",
                                                    make_chef_headers(chef_id)))
        celebration = shows_for(seafood["reservation"]["id"], "CELEBRATION")[0]

        before = get_success_data(api_client.get_protein_ticket(
            seafood["protein_ticket_id"], FM))

        cleared = clear_chef(chef_id)
        assert cleared["status"] == "CLEARING"
        assert cleared["current_table_id"] is None

        started = validate_success(api_client.post_show_event(
            celebration["id"], "START", make_chef_headers(chef_id)))
        assert started["status"] == "STARTED"

        after = get_success_data(api_client.get_protein_ticket(
            seafood["protein_ticket_id"], FM))
        assert after["issued_grams"] == before["issued_grams"]
        assert float(after["cost_cents"]) == float(before["cost_cents"])


class TestPriorityPairStateVersusTemporal:

    def test_a_closed_booking_at_a_downtime_table_reports_the_state_error(self):
        """PRD §2.10: "Authentication is settled first, then permission, then existence,
        then whether the target is in a state from which the requested transition is
        declared (otherwise `ERR_INVALID_STATE`, HTTP 409), and only then the business
        rules."
        PRD §3.4: "The request is refused with `ERR_VENTILATION_FREEZE` while the venue
        is frozen; refused with `ERR_HOLD_WINDOW_CLOSED` (HTTP 409) when the clock has
        already reached or passed `hold_until`."
        PRD §3.4: "the interval the seating would occupy overlaps a scheduled or active
        maintenance window on that table" is the temporal family.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_a_closed_booking_at_a_scheduled_downtime_table
        """
        scenario = setup_floor(clock="2026-09-03T12:00:00Z",
                               tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        gold = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                            phone="212-555-0177")
        table_id = scenario["tables"][0]["id"]

        seafood = seed_seated_booking_with_finished_grill(
            scenario, gold["id"], "T4", table_id, party_size=4)
        reservation_id = seafood["reservation"]["id"]
        current = read_reservation(reservation_id)
        closed = validate_success(api_client.close_reservation(
            reservation_id,
            {"expected_reservation_version": current["version"], "credit_to_apply_cents": 0},
            HOST))
        assert closed["status"] == "CLOSED"
        assert closed["table_id"] == table_id

        window = get_success_data(api_client.create_maintenance_window(
            {"venue_id": scenario["venue"]["id"], "table_id": table_id,
             "maintenance_kind": "GRILL_REBUILD",
             "planned_start_at": "2026-09-03T11:00:00Z",
             "planned_end_at": "2026-09-05T09:00:00Z"}, FM))
        assert window["status"] == "SCHEDULED"

        response = api_client.seat_reservation(reservation_id, HOST)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        assert read_reservation(reservation_id)["status"] == "CLOSED"
        # Closing vacated the occupancy and drove the table from SEATED to TURNING;
        # the interval overlap against the window is never evaluated because the
        # state check fails first.
        assert fresh_table(scenario, table_id)["status"] == "TURNING"

    def test_a_held_booking_at_the_same_downtime_table_reports_the_temporal_error(self):
        """PRD §3.4: "refused with `ERR_MAINTENANCE_CONFLICT` when the interval the
        seating would occupy overlaps a scheduled or active maintenance window on that
        table."
        PRD §3.4: "The request is refused with `ERR_VENTILATION_FREEZE` while the venue
        is frozen."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_a_closed_booking_at_a_scheduled_downtime_table
        """
        scenario = setup_floor(clock="2026-09-03T12:00:00Z",
                               tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        plat = create_party(scenario, loyalty_tier="PLATINUM")
        table_id = scenario["tables"][0]["id"]

        held = create_booking(scenario, plat["id"], "T4", party_size=4,
                              scheduled_time="2026-09-03T12:00:00Z")
        submit_booking(held["id"])
        grant_hold(held["id"], table_id)
        assert read_reservation(held["id"])["status"] == "HELD"

        get_success_data(api_client.create_maintenance_window(
            {"venue_id": scenario["venue"]["id"], "table_id": table_id,
             "maintenance_kind": "GRILL_REBUILD",
             "planned_start_at": "2026-09-03T11:00:00Z",
             "planned_end_at": "2026-09-05T09:00:00Z"}, FM))

        response = api_client.seat_reservation(held["id"], HOST)
        validate_error(response, ApiErrorId.ERR_MAINTENANCE_CONFLICT)

        assert seatings_for(reservation_id=held["id"]) == []
        assert fresh_table(scenario, table_id)["status"] == "AVAILABLE"


class TestPriorityPairSafetyVersusReferential:

    def test_a_frozen_venue_beats_the_restricted_party(self):
        """PRD §2.10: "Within the business rules, a request that a workflow declares to
        be guarded by more than one rule is always reported against the highest-priority
        rule it violates."
        PRD §3.3: "The hold is also refused while the venue's `occupancy_freeze` is
        true, with `ERR_VENTILATION_FREEZE` (HTTP 409)."
        PRD §3.3: "refused with `ERR_HOLD_LIMIT_EXCEEDED`" — the party restriction is a
        separate referential guard.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_a_restricted_party_at_a_frozen_venue
        """
        scenario = setup_floor(clock="2026-09-03T02:00:00Z",
                               tables=(("T2", 2), ("T4", 4)),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        risk = create_party(scenario, loyalty_tier="NONE", name="Tomas Reyes",
                            phone="212-555-0128")
        other_table = scenario["tables"][1]["id"]

        # The third booking is drafted and SUBMITted while the party is still
        # ACTIVE — §3.2 rejects SUBMIT outright once the party is RESTRICTED, so the
        # frozen hold attempt below is what exercises the safety-vs-referential pair.
        third = create_booking(scenario, risk["id"], "T2", party_size=2,
                               scheduled_time="2026-09-03T19:00:00Z")
        submit_booking(third["id"])

        for slot, instant in ((0, "2026-09-02T19:00:00Z"), (1, "2026-09-02T20:00:00Z")):
            reservation = create_booking(scenario, risk["id"], "T2", party_size=2,
                                         scheduled_time=instant)
            submit_booking(reservation["id"])
            held = api_client.grant_hold(
                reservation["id"],
                {"expected_table_version": fresh_table(scenario, scenario["tables"][0]["id"])["version"],
                 "table_id": scenario["tables"][0]["id"]},
                HOST)
            assert held.status_code == 200, f"setup hold {slot} failed: {held.text}"
            if slot == 1:
                set_clock("2026-09-03T02:00:00Z")
            marked = api_client.post_reservation_event(reservation["id"], "MARK_NO_SHOW", HOST)
            assert marked.status_code == 200, f"setup no-show {slot} failed: {marked.text}"
            if slot == 1:
                set_clock("2026-09-03T02:00:00Z")

        assert read_party(risk["id"])["no_show_count"] == 2
        assert read_party(risk["id"])["status"] == "RESTRICTED"

        schedule_ventilation_window(scenario, "2026-09-03T09:00:00Z",
                                   "2026-09-03T11:00:00Z")
        assert get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))[
            "occupancy_freeze"] is True

        frozen_attempt = api_client.grant_hold(
            third["id"],
            {"expected_table_version": fresh_table(scenario, other_table)["version"],
             "table_id": other_table},
            HOST)
        validate_error(frozen_attempt, ApiErrorId.ERR_VENTILATION_FREEZE)

    def test_the_referential_error_surfaces_once_the_venue_is_thawed(self):
        """PRD §3.3: "The hold is also refused with `ERR_VENTILATION_FREEZE` (HTTP 409)
        while the venue's `occupancy_freeze` is true."
        PRD §3.2: "A party whose `status` has become `RESTRICTED` may not start or join a
        seating episode at all, and any attempt to submit, hold or seat such a party is
        rejected with `ERR_PARTY_RESTRICTED` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_a_restricted_party_at_a_frozen_venue
        """
        scenario = setup_floor(clock="2026-09-03T02:00:00Z",
                               tables=(("T2", 2),), chefs=(("Kenji Ito", "ZONE_A"),))
        risk = create_party(scenario, loyalty_tier="NONE", name="Tomas Reyes",
                            phone="212-555-0128")
        table_id = scenario["tables"][0]["id"]

        # Draft and SUBMIT the third booking while the party is still ACTIVE: the
        # SUBMIT gate rejects a RESTRICTED party, and this test targets the HOLD gate.
        third = create_booking(scenario, risk["id"], "T2", party_size=2,
                               scheduled_time="2026-09-03T19:00:00Z")
        submit_booking(third["id"])

        for instant in ("2026-09-02T19:00:00Z", "2026-09-02T20:00:00Z"):
            reservation = create_booking(scenario, risk["id"], "T2", party_size=2,
                                         scheduled_time=instant)
            submit_booking(reservation["id"])
            held = api_client.grant_hold(
                reservation["id"],
                {"expected_table_version": fresh_table(scenario, table_id)["version"],
                 "table_id": table_id},
                HOST)
            assert held.status_code == 200, f"setup hold failed: {held.text}"
            set_clock("2026-09-03T02:00:00Z")
            marked = api_client.post_reservation_event(reservation["id"], "MARK_NO_SHOW", HOST)
            assert marked.status_code == 200, f"setup no-show failed: {marked.text}"
            set_clock("2026-09-03T02:00:00Z")

        assert read_party(risk["id"])["status"] == "RESTRICTED"

        response = api_client.grant_hold(
            third["id"],
            {"expected_table_version": fresh_table(scenario, table_id)["version"],
             "table_id": table_id},
            HOST)
        validate_error(response, ApiErrorId.ERR_PARTY_RESTRICTED)

        assert seatings_for(reservation_id=third["id"]) == []


class TestTrueupBandBoundary:

    def test_a_thousand_cent_shortfall_is_inclusive_in_band_one(self):
        """PRD §3.6: "a shortfall of up to 1000 cents takes a factor of 0.50; a
        shortfall of up to 2000 cents takes a factor of 0.60."
        PRD §3.6: "The banded amount is then ceilinged once to the next whole multiple
        of 25 cents."

        Design: Difficulty/boundary_precision_check/trueup_band_boundary_at_exactly_one_thousand_cents_is_inclusive
        """
        scenario = setup_floor(clock=DEFAULT_CLOCK, tables=(("T2", 2),),
                               chefs=(("Kenji Ito", "ZONE_A"),),
                               tier_overrides={"T2": {"minimum_bill_cents": 7400}})
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")

        two_seat = seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T2", scenario["tables"][0]["id"], party_size=2)
        current = read_reservation(two_seat["reservation"]["id"])
        closed = validate_success(api_client.close_reservation(
            two_seat["reservation"]["id"],
            {"expected_reservation_version": current["version"], "credit_to_apply_cents": 0},
            HOST))

        assert closed["final_bill_cents"] == 6400
        assert scenario["tiers"]["T2"]["minimum_bill_cents"] - closed["final_bill_cents"] == 1000

        entries = ledger_entries(scenario["venue"]["id"],
                                 two_seat["reservation"]["id"], "TABLE_MINIMUM_TRUEUP")
        assert len(entries) == 1
        # Band 1 inclusive at exactly 1000: ceil(0.50 * 1000 / 25) * 25 == 500.
        assert entries[0]["amount_cents"] == 500

    def test_the_band_jumps_once_the_shortfall_leaves_the_one_thousand_cent_edge(self):
        """PRD §3.6: "a shortfall of up to 1000 cents takes a factor of 0.50; a
        shortfall of up to 2000 cents takes a factor of 0.60."
        PRD §2.7: "In the table-minimum true-up, the band factor is applied first and
        the ceiling is applied once to the band result."

        Design: Difficulty/boundary_precision_check/trueup_band_boundary_at_exactly_one_thousand_cents_is_inclusive
        """
        scenario = setup_floor(clock=DEFAULT_CLOCK, tables=(("T4", 4),),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")

        inner = seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T4", scenario["tables"][0]["id"], party_size=4)
        current = read_reservation(inner["reservation"]["id"])
        assert current["final_bill_cents"] == 12800
        assert scenario["tiers"]["T4"]["minimum_bill_cents"] - current["final_bill_cents"] == 1200

        closed = validate_success(api_client.close_reservation(
            inner["reservation"]["id"],
            {"expected_reservation_version": current["version"], "credit_to_apply_cents": 0},
            HOST))
        assert closed["status"] == "CLOSED"

        entries = ledger_entries(scenario["venue"]["id"],
                                 inner["reservation"]["id"], "TABLE_MINIMUM_TRUEUP")
        assert len(entries) == 1
        # Band 2: ceil(0.60 * 1200 / 25) * 25 == ceil(28.8) * 25 == 725.
        assert entries[0]["amount_cents"] == 725
        # The inner-holding booking settled at exactly half the 14000 minimum.
        assert entries[0]["amount_cents"] > 500


class TestHoldCountBoundary:

    def test_the_third_hold_is_granted_and_the_fourth_is_refused(self):
        """PRD §3.3: "The request must carry `expected_table_version` as described in
        §2.8 ... refused with `ERR_HOLD_LIMIT_EXCEEDED` (HTTP 409) once `hold_count` has
        already reached the cap of 3 holds in the current episode."
        PRD §3.3: "Once `hold_until` has passed and the window has closed, a `Host` may
        grant a fresh hold onto a different table; the booking stays `HELD`,
        `hold_count` advances by one, the previous table is released, and a new
        `hold_until` is set twenty minutes out."

        Design: Difficulty/boundary_precision_check/hold_count_boundary_third_hold_allowed_fourth_refused
        """
        scenario = setup_floor(clock=DEFAULT_CLOCK,
                               tables=(("T4", 4), ("T2", 2), ("T6", 6)),
                               chefs=())
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        reservation = create_booking(scenario, party["id"], "T4", party_size=4)
        submit_booking(reservation["id"])

        grant_hold(reservation["id"], scenario["tables"][0]["id"])
        advance_clock(DEFAULT_CLOCK, 25)
        grant_hold_at_later_clock(reservation["id"], scenario["tables"][2]["id"])
        advance_clock(DEFAULT_CLOCK, 50)

        third = validate_success(grant_hold_at_later_clock(
            reservation["id"], scenario["tables"][2]["id"]))
        assert third["hold_count"] == 3
        assert third["status"] == "HELD"

        # A re-park is only legal once the previous window has closed (§3.3), so the
        # clock is advanced past the third hold's hold_until before the fourth try.
        advance_clock(DEFAULT_CLOCK, 75)
        fourth = grant_hold_at_later_clock(reservation["id"], scenario["tables"][0]["id"])
        validate_error(fourth, ApiErrorId.ERR_HOLD_LIMIT_EXCEEDED)

        after = read_reservation(reservation["id"])
        assert after["hold_count"] == 3
        assert after["status"] == "HELD"

    def test_a_second_booking_for_the_same_party_still_starts_at_zero_holds(self):
        """PRD §3.3: "refused with `ERR_HOLD_LIMIT_EXCEEDED` (HTTP 409) once
        `hold_count` has already reached the cap of 3 holds in the current episode."
        PRD §3.2: "The booking begins in `DRAFT` with `hold_count` at 0."

        Design: Difficulty/boundary_precision_check/hold_count_boundary_third_hold_allowed_fourth_refused
        """
        scenario = setup_floor(clock=DEFAULT_CLOCK,
                               tables=(("T4", 4), ("T2", 2), ("T6", 6)),
                               chefs=())
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        first = create_booking(scenario, party["id"], "T4", party_size=4)
        submit_booking(first["id"])

        grant_hold(first["id"], scenario["tables"][0]["id"])
        advance_clock(DEFAULT_CLOCK, 25)
        grant_hold_at_later_clock(first["id"], scenario["tables"][2]["id"])
        advance_clock(DEFAULT_CLOCK, 50)
        grant_hold_at_later_clock(first["id"], scenario["tables"][2]["id"])
        assert read_reservation(first["id"])["hold_count"] == 3

        second = create_booking(scenario, party["id"], "T2", party_size=2,
                                scheduled_time="2026-09-03T20:00:00Z")
        submit_booking(second["id"])
        fresh = validate_success(grant_hold_at_later_clock(second["id"],
                                                           scenario["tables"][2]["id"]))
        assert fresh["hold_count"] == 1
        assert fresh["status"] == "HELD"


class TestWindowReopenCascade:

    def test_reopening_a_ventilation_window_restores_a_serviceable_floor(self):
        """PRD §3.7: "Reopening an `ACTIVE` window returns it to `SCHEDULED` and
        releases the venue from any freeze it caused and the table back to `AVAILABLE`."
        PRD §2.9: "it also cascades a follow-on `GRILL_REBUILD` window into existence
        against the same table" (the release undoes the freeze, not the companion row).

        Design: Difficulty/compensating_invariant/window_reopen_four_hop_cascade_back_to_a_serviceable_floor
        """
        scenario = setup_floor(clock="2026-09-03T09:30:00Z",
                               tables=(("T6", 6), ("T4", 4), ("T2", 2)), chefs=())
        # planned_start_at must sit within the maintenance late grace (30 min) of
        # the clock for the window to be acceptable (§3.7).
        window = schedule_ventilation_window(scenario, "2026-09-03T09:00:00Z",
                                            "2026-09-03T12:00:00Z")
        assert window["status"] == "ACTIVE"
        frozen = get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))
        assert frozen["status"] == "VENTILATION_HOLD"
        assert frozen["occupancy_freeze"] is True

        released = validate_success(api_client.reopen_maintenance_window(window["id"], FM))
        assert released["status"] == "SCHEDULED"

        thawed = get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))
        assert thawed["status"] == "ACTIVE"
        assert thawed["occupancy_freeze"] is False

        for table in scenario["tables"]:
            current = get_success_data(api_client.get_table(table["id"], FM))
            assert current["status"] == "AVAILABLE"
            assert current["maintenance_resume_at"] is None

    def test_reopening_an_already_scheduled_window_is_refused_rather_than_rerun(self):
        """PRD §3.7: "the reopen is refused with `ERR_INVALID_STATE` when the venue
        still holds a `SEATED` booking or holds another window that is `ACTIVE`."
        PRD §2.10: "then whether the target is in a state from which the requested
        transition is declared (otherwise `ERR_INVALID_STATE`, HTTP 409)."

        Design: Difficulty/compensating_invariant/window_reopen_four_hop_cascade_back_to_a_serviceable_floor
        """
        scenario = setup_floor(clock="2026-09-03T09:30:00Z",
                               tables=(("T6", 6), ("T4", 4), ("T2", 2)), chefs=())
        # planned_start_at must sit within the maintenance late grace (30 min) of
        # the clock for the window to be acceptable (§3.7).
        window = schedule_ventilation_window(scenario, "2026-09-03T09:00:00Z",
                                            "2026-09-03T12:00:00Z")
        validate_success(api_client.reopen_maintenance_window(window["id"], FM))

        response = api_client.reopen_maintenance_window(window["id"], FM)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        still = get_success_data(api_client.get_maintenance_window(window["id"], FM))
        assert still["status"] == "SCHEDULED"
        thawed = get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))
        assert thawed["status"] == "ACTIVE"
        assert thawed["occupancy_freeze"] is False