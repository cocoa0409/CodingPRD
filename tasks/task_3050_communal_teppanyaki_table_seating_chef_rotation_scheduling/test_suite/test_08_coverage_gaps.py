"""The remaining breadth claims: the protein rollup's input set, the shared-grill
portion standard, an occupancy extension, the venue-level concurrency guard, and the
immediate-consistency and refusal behaviour of the settle-and-abandon paths.
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
    book_hold_seat,
    create_party,
    fresh_venue_version,
    ledger_entries,
    read_party,
    perform_grill_phase,
    perform_sushi_phase,
    read_reservation,
    schedule_ventilation_window,
    seatings_for,
    seed_seated_booking_with_finished_grill,
    setup_floor,
    shift_instant,
)
from test_helpers.test_users import make_chef_headers


class TestProteinRollupInputSet:

    def test_voiding_a_ticket_drops_it_from_the_venue_rollup(self):
        """PRD §3.8: "`protein_cost_cents` is the sum of that per-ticket cost across
        every ticket at the venue whose status is `POSTED`; voided tickets are excluded
        from the rollup and from the chef's `pounds_protein_issued`, which is the sum of
        issued grams across the chef's posted tickets divided by 453.6."
        PRD §3.5: "the venue rollup and the chef's issued pounds are recomputed excluding
        it."

        Design: Corner/calculations/protein_cost_input_set_excludes_voided_tickets
        """
        scenario = setup_floor(clock=DEFAULT_CLOCK,
                               tables=(("T6", 6), ("T4", 4), ("T2", 2)),
                               chefs=(("Kenji Ito", "ZONE_A"), ("Ana Ruiz", "ZONE_B")))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")

        first = seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T6", scenario["tables"][0]["id"], party_size=4)
        second = seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T4", scenario["tables"][1]["id"], party_size=4)
        venue_id = scenario["venue"]["id"]

        first_ticket = get_success_data(api_client.get_protein_ticket(
            first["protein_ticket_id"], FM))
        second_ticket = get_success_data(api_client.get_protein_ticket(
            second["protein_ticket_id"], FM))
        assert first_ticket["standard_grams"] == 960
        assert first_ticket["issued_grams"] == 720
        assert float(first_ticket["cost_cents"]) == 2880.0
        assert second_ticket["issued_grams"] == 720
        assert float(second_ticket["cost_cents"]) == 2880.0

        both = get_success_data(api_client.get_venue(venue_id, FM))
        assert float(both["protein_cost_cents"]) == 5760.0

        validate_success(api_client.post_protein_event(
            second["protein_ticket_id"], "VOID", make_chef_headers(second["chef_id"])))

        after = get_success_data(api_client.get_venue(venue_id, FM))
        assert float(after["protein_cost_cents"]) == 2880.0

        first_after = get_success_data(api_client.get_protein_ticket(
            first["protein_ticket_id"], FM))
        assert float(first_after["cost_cents"]) == 2880.0
        assert first_after["status"] == "POSTED"


class TestSharedGrillPortionStandard:

    def test_the_portion_standard_sums_every_active_occupancy_at_the_table(self):
        """PRD §3.5: "The `standard_grams` for a grill phase is the sum of `guest_count`
        across the `ACTIVE` `TableSeating` rows at the show's table — which may be more
        than one row when separate parties share the grill — multiplied by the tier's
        `protein_gram_standard`."
        PRD §3.5: "The `issued_grams` actually staged is that standard less one quarter
        of it, computed by dividing the standard by one port per guest and then by a
        guest-port share divisor of four and discarding the remainder with floor
        division."
        PRD §3.5: "`variance_grams` is `issued_grams` minus `standard_grams`, signed, so
        a shortfall is negative."

        Design: Corner/cross_cutting_complexity_layers/protein_issued_falls_below_the_standard_as_guest_count_rises
        """
        scenario = setup_floor(clock=DEFAULT_CLOCK, tables=(("T6", 6),),
                               chefs=(("Kenji Ito", "ZONE_A"), ("Ana Ruiz", "ZONE_B")))
        gold = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                            phone="212-555-0177")
        plat = create_party(scenario, loyalty_tier="PLATINUM")
        table_id = scenario["tables"][0]["id"]

        small = book_hold_seat(scenario, gold["id"], "T6", table_id, party_size=2)
        book_hold_seat(scenario, plat["id"], "T6", table_id, party_size=4)
        assert get_success_data(api_client.get_table(table_id, FM))["guests_seated"] == 6

        chef_id = small["reservation"]["chef_assignment_id"]
        perform_sushi_phase(small["sushi_show_id"], DEFAULT_CLOCK, chef_id)
        started, _ = perform_grill_phase(small["grill_show_id"], DEFAULT_CLOCK, chef_id)

        ticket = get_success_data(api_client.get_protein_ticket(
            started["protein_ticket_id"], FM))
        assert ticket["standard_grams"] == 6 * 240
        assert ticket["issued_grams"] == 1440 - (1440 // 4)
        assert ticket["issued_grams"] == ticket["standard_grams"] - (
            ticket["standard_grams"] // 4)
        assert ticket["variance_grams"] == ticket["issued_grams"] - ticket["standard_grams"]
        assert float(ticket["cost_cents"]) == ticket["issued_grams"] * 4.0

        rollup = get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))
        assert float(rollup["protein_cost_cents"]) == float(ticket["cost_cents"])

    def test_the_shortfall_stays_a_quarter_of_the_standard_as_the_table_grows(self):
        """PRD §3.5: "The `issued_grams` actually staged is that standard less one
        quarter of it, computed by dividing the standard by one port per guest and then
        by a guest-port share divisor of four and discarding the remainder with floor
        division."
        PRD §3.5: "the kitchen holds back one port's share in every four."

        Design: Corner/cross_cutting_complexity_layers/protein_issued_falls_below_the_standard_as_guest_count_rises
        """
        scenario = setup_floor(clock=DEFAULT_CLOCK,
                               tables=(("T6", 6), ("T6", 6)),
                               chefs=(("Kenji Ito", "ZONE_A"), ("Ana Ruiz", "ZONE_B")))
        gold = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                            phone="212-555-0177")

        three = seed_seated_booking_with_finished_grill(
            scenario, gold["id"], "T6", scenario["tables"][0]["id"], party_size=3)
        four = seed_seated_booking_with_finished_grill(
            scenario, gold["id"], "T6", scenario["tables"][1]["id"], party_size=4)

        small = get_success_data(api_client.get_protein_ticket(
            three["protein_ticket_id"], FM))
        big = get_success_data(api_client.get_protein_ticket(
            four["protein_ticket_id"], FM))

        assert small["standard_grams"] == 720
        assert small["issued_grams"] == 540
        assert big["standard_grams"] == 960
        assert big["issued_grams"] == 720
        assert small["variance_grams"] == -180
        assert big["variance_grams"] == -240
        assert small["issued_grams"] == 3 * small["standard_grams"] // 4
        assert big["issued_grams"] == 3 * big["standard_grams"] // 4


class TestOccupancyExtension:

    def test_extending_an_active_occupancy_moves_its_vacate_instant_only(self):
        """PRD §3.4: "A `FloorManager` may extend a running occupancy by supplying
        `extension_minutes`, which advances `expected_vacate_at` by that many minutes."
        PRD §3.8: "The account is recomputed from the closed occupancy rows on every
        write."

        Design: Corner/cross_cutting_complexity_layers/extending_a_seating_pushes_the_occupancy_past_its_tier_standard
        """
        scenario = setup_floor(clock="2026-09-03T12:00:00Z",
                               tables=(("T2", 2),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario)
        table_id = scenario["tables"][0]["id"]
        seafood = book_hold_seat(scenario, party["id"], "T2", table_id, party_size=2,
                                 scheduled_time="2026-09-03T12:00:00Z")

        before = get_success_data(api_client.get_seating(seafood["seating_id"], FM))
        assert before["status"] == "ACTIVE"
        assert before["occupied_minutes"] == 0

        debt_before = get_success_data(api_client.get_venue(
            scenario["venue"]["id"], FM))["shortfall_turn_debt_minutes"]

        extended = validate_success(api_client.extend_seating(
            seafood["seating_id"], 20, FM))
        assert extended["seated_at"] == before["seated_at"]
        assert extended["expected_vacate_at"] == shift_instant(
            before["expected_vacate_at"], 20)
        assert extended["status"] == "ACTIVE"

        debt_after = get_success_data(api_client.get_venue(
            scenario["venue"]["id"], FM))["shortfall_turn_debt_minutes"]
        assert debt_after == debt_before

    def test_a_vacated_row_is_the_only_thing_that_moves_the_shortfall_counter(self):
        """PRD §3.8: "Whenever an occupancy row is vacated, its over- or under-run
        against the tier's turn-time standard is bucketed."
        PRD §3.8: "The account is recomputed from the closed occupancy rows on every
        write and is never permitted to exceed the per-reservation turn-debt cap
        multiplied by the count of closed bookings at the venue."

        Design: Corner/cross_cutting_complexity_layers/extending_a_seating_pushes_the_occupancy_past_its_tier_standard
        """
        scenario = setup_floor(clock="2026-09-03T12:00:00Z",
                               tables=(("T2", 2),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario)
        table_id = scenario["tables"][0]["id"]
        seafood = book_hold_seat(scenario, party["id"], "T2", table_id, party_size=2,
                                 scheduled_time="2026-09-03T12:00:00Z")

        venue_id = scenario["venue"]["id"]
        assert get_success_data(api_client.get_venue(venue_id, FM))[
            "shortfall_turn_debt_minutes"] == 0
        assert seatings_for(table_id=table_id, status="VACATED") == []

        validate_success(api_client.extend_seating(seafood["seating_id"], 20, FM))
        assert get_success_data(api_client.get_venue(venue_id, FM))[
            "shortfall_turn_debt_minutes"] == 0


class TestVenueVersionGuard:

    def test_a_stale_venue_version_refuses_the_clock_in_and_a_fresh_one_succeeds(self):
        """PRD §2.8: "Posting a chef event — the clock-in family — requires
        `expected_venue_version`, the client's last-observed `version` of the `Venue`. A
        chef clocking in against a venue whose version has advanced is rejected with
        `ERR_STALE_VERSION` at HTTP 412, because the rotation pointer the client
        computed its rotation position from is stale."

        Design: Corner/cross_cutting_complexity_layers/clicking_in_with_a_stale_venue_version_returns_stale_version
        """
        scenario = setup_floor(tier_codes=(), tables=(),
                               chefs=(("Kenji Ito", "ZONE_A"), ("Ana Ruiz", "ZONE_B")),
                               clock_in=0)
        chef_id = scenario["chefs"][0]["id"]

        stale = fresh_venue_version(scenario)
        bumped = get_success_data(api_client.run_ops(scenario["venue"]["id"], FM))
        assert bumped["version"] != stale

        response = api_client.post_chef_event(
            chef_id, {"event_type": "CLOCK_IN", "expected_venue_version": stale},
            make_chef_headers(chef_id))
        validate_error(response, ApiErrorId.ERR_STALE_VERSION)

        after_reject = get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))
        assert after_reject["version"] == bumped["version"]
        assert get_success_data(api_client.get_chef(chef_id, FM))["status"] == "OFF_SHIFT"

        retried = validate_success(api_client.post_chef_event(
            chef_id, {"event_type": "CLOCK_IN", "expected_venue_version": bumped["version"]},
            make_chef_headers(chef_id)))
        assert retried["status"] == "ON_STATION"

    def test_the_rejected_clock_in_leaves_the_rotation_untouched(self):
        """PRD §2.8: "each rejects a mismatch with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.1: "On clock-in the chef's `sequence_index` is set to one more than the
        highest `sequence_index` among chefs at the venue already on station, or to 1
        when there are none."

        Design: Corner/cross_cutting_complexity_layers/clicking_in_with_a_stale_venue_version_returns_stale_version
        """
        scenario = setup_floor(tier_codes=(), tables=(),
                               chefs=(("Kenji Ito", "ZONE_A"),), clock_in=0)
        chef_id = scenario["chefs"][0]["id"]
        version = fresh_venue_version(scenario)

        response = api_client.post_chef_event(
            chef_id, {"event_type": "CLOCK_IN", "expected_venue_version": version - 1},
            make_chef_headers(chef_id))
        validate_error(response, ApiErrorId.ERR_STALE_VERSION)

        chef = get_success_data(api_client.get_chef(chef_id, FM))
        assert chef["status"] == "OFF_SHIFT"
        assert chef["sequence_index"] is None
        assert fresh_venue_version(scenario) == version


class TestImmediateConsistency:

    def test_the_close_response_carries_the_settled_check_immediately(self):
        """PRD §3.6: "The check is settled in a pinned order: `final_bill_cents` is
        computed by the final variant of the settlement rule, `check_cents` is evaluated
        first with `credit_applied_cents` held at its stored value, then
        `credit_applied_cents` is recomputed as the smallest of the party's
        `loyalty_credit_cents`, the requested `credit_to_apply_cents`, and the credit
        cap, and `check_cents` is re-evaluated exactly once."
        PRD §3.6: "If the settled `final_bill_cents` falls below the tier's
        `minimum_bill_cents`, a table-minimum true-up is posted."

        Design: Corner/consistency_model/close_response_carries_the_settled_check_in_the_same_request
        """
        scenario = setup_floor(clock=DEFAULT_CLOCK, tables=(("T4", 4),),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        seafood = seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T4", scenario["tables"][0]["id"], party_size=4)

        current = read_reservation(seafood["reservation"]["id"])
        closed = validate_success(api_client.close_reservation(
            seafood["reservation"]["id"],
            {"expected_reservation_version": current["version"], "credit_to_apply_cents": 0},
            HOST))
        assert closed["status"] == "CLOSED"
        assert closed["final_bill_cents"] == 12800
        # T4 party_size 4 surcharge = ceil(3200 * min(4,3) / 5) to a whole 25 == 1925.
        assert closed["seat_surcharge_cents"] == 1925
        assert closed["check_cents"] == 12800 + 1925 + 725

        reread = read_reservation(seafood["reservation"]["id"])
        assert reread["check_cents"] == closed["check_cents"]
        assert reread["status"] == closed["status"]
        assert reread["final_bill_cents"] == closed["final_bill_cents"]

        entries = ledger_entries(scenario["venue"]["id"],
                                 seafood["reservation"]["id"], "TABLE_MINIMUM_TRUEUP")
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 725


class TestRefusedReopenLeavesNoPartialState:

    def test_a_refused_reopen_leaves_the_booking_abandoned_and_the_ledger_voided(self):
        """PRD §3.7: "Reopening it moves `ABANDONED` back to `HELD`, with a fresh
        `table_id` and a fresh `hold_until` set exactly as on a first hold; it requires
        the venue to be `ACTIVE`, requires `hold_count` to still be under the cap of 3,
        and requires a table that satisfies every condition a first hold would."
        PRD §3.7: "Fifth, each booking that has just been abandoned drives every
        `POSTED` `VenueLedgerEntry` for it to `VOIDED`, and each such void credits the
        party's `loyalty_credit_cents` by the entry's positive amount."

        Design: Corner/consistency_model/abandon_and_reopen_leave_no_partial_state_if_the_reopen_is_refused
        """
        scenario = setup_floor(clock=DEFAULT_CLOCK,
                               tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        seafood = book_hold_seat(scenario, party["id"], "T4",
                                 scenario["tables"][0]["id"], party_size=4)
        reservation_id = seafood["reservation"]["id"]

        schedule_ventilation_window(scenario, "2026-09-03T09:00:00Z",
                                   "2026-09-03T10:00:00Z")
        assert read_reservation(reservation_id)["status"] == "ABANDONED"

        credit_after_abandon = read_party(party["id"])["loyalty_credit_cents"]
        voided = ledger_entries(scenario["venue"]["id"], reservation_id)
        assert len(voided) == 1
        assert voided[0]["status"] == "VOIDED"

        response = api_client.reopen_reservation(reservation_id, {}, HOST)
        validate_error(response, ApiErrorId.ERR_VENTILATION_FREEZE)

        after = read_reservation(reservation_id)
        assert after["status"] == "ABANDONED"
        assert after["table_id"] is None
        assert after["hold_until"] is None
        assert read_party(party["id"])["loyalty_credit_cents"] == credit_after_abandon

    def test_a_second_refused_reopen_changes_nothing_more(self):
        """PRD §3.7: "Reopening it moves `ABANDONED` back to `HELD`, with a fresh `table_id`
        and a fresh `hold_until` set exactly as on a first hold; it requires the venue to
        be `ACTIVE`, requires `hold_count` to still be under the cap of 3, and requires a
        table that satisfies every condition a first hold would."
        PRD §3.7: "The ledger entries voided by the abandonment cascade are restored to
        `POSTED` and the party's credit is reduced again by the same amount, but only for
        entries voided by the abandonment cascade — an entry voided by an explicit void
        stays `VOIDED` through a reopen."

        Design: Corner/consistency_model/abandon_and_reopen_leave_no_partial_state_if_the_reopen_is_refused
        """
        scenario = setup_floor(clock=DEFAULT_CLOCK,
                               tables=(("T4", 4),), chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")
        seafood = book_hold_seat(scenario, party["id"], "T4",
                                 scenario["tables"][0]["id"], party_size=4)
        reservation_id = seafood["reservation"]["id"]
        schedule_ventilation_window(scenario, "2026-09-03T09:00:00Z",
                                   "2026-09-03T10:00:00Z")

        validate_error(api_client.reopen_reservation(reservation_id, {}, HOST),
                       ApiErrorId.ERR_VENTILATION_FREEZE)
        first = read_reservation(reservation_id)
        first_credit = read_party(party["id"])["loyalty_credit_cents"]

        validate_error(api_client.reopen_reservation(reservation_id, {}, HOST),
                       ApiErrorId.ERR_VENTILATION_FREEZE)
        second = read_reservation(reservation_id)

        assert second["status"] == first["status"] == "ABANDONED"
        assert second["version"] == first["version"]
        assert read_party(party["id"])["loyalty_credit_cents"] == first_credit
        still_voided = ledger_entries(scenario["venue"]["id"], reservation_id)
        assert all(entry["status"] == "VOIDED" for entry in still_voided)