"""The pricing and floor-charge rules: the contested-table settlement branch, the
seat surcharge's rounding and guest cap, the read-side cost report and the per-epoch
restaurant charge band.
"""
from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
)
from test_helpers.fixtures import (
    FM,
    HOST,
    book_hold_seat,
    create_booking,
    create_party,
    fire_sushi_ticket,
    ledger_entries,
    read_reservation,
    setup_floor,
    submit_booking,
    grant_hold,
)


class TestSettlementBranch:

    def test_settlement_case_b_shared_table_premium_from_a_within_table_sushi_ticket(self):
        """PRD §3.9: "The other-parties figure is the sum, over every booking in T, of
        that booking's tier rate multiplied by the smaller of its party size and the
        cap of 3, with the booking's own share removed when the booking is itself in T
        so that it is counted once and only once. The sushi figure is the sum of
        `quantity` times `unit_price_cents` over the booking's `OPEN` sushi tickets."
        PRD §3.9: "When the secured figure is smaller than P the base is the larger of
        the secured figure plus the sushi figure plus the other-parties figure, and P,
        floored at zero."

        Design: Corner/calculations/settlement_case_b_shared_table_premium_from_a_within_table_sushi_ticket
        """
        scenario = setup_floor(tables=(("T6", 6), ("T4", 4), ("T2", 2)),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="PLATINUM")

        reservation = create_booking(scenario, party["id"], "T6", party_size=6,
                                     celebration="NONE", invite_code="SHARE-9")
        submit_booking(reservation["id"])
        grant_hold(reservation["id"], scenario["tables"][0]["id"])
        seated = get_success_data(api_client.seat_reservation(reservation["id"], HOST))

        fire_sushi_ticket(scenario, reservation["id"],
                          chef_id=seated["chef_assignment_id"],
                          item_code="DRAGON-ROLL",
                          quantity=2, requested_at="2026-09-03T19:05:00Z",
                          unit_price_cents=1800)

        current = read_reservation(reservation["id"])
        closed = validate_success(api_client.close_reservation(
            reservation["id"],
            {"expected_reservation_version": current["version"], "credit_to_apply_cents": 0},
            HOST))

        assert closed["final_bill_cents"] == 19600
        assert closed["seat_surcharge_cents"] == 1375
        assert closed["check_cents"] == 19600 + 1375 + 0 + 0
        assert closed["status"] == "CLOSED"
        assert closed["seat_surcharge_cents"] == seated["seat_surcharge_cents"]
        assert ledger_entries(scenario["venue"]["id"], reservation["id"],
                              "TABLE_MINIMUM_TRUEUP") == []


class TestSeatSurcharge:

    def test_seat_surcharge_rounds_per_reservation_never_per_guest(self):
        """PRD §3.9: "Its raw value is the tier's `base_rate_per_guest_cents` multiplied
        by the guests billed — the smaller of the party size and the cap of 3 — and
        divided by one more than the party size. The raw value is then ceilinged once,
        per booking and not per guest, to the next whole multiple of 25 cents."
        PRD §3.9: "The seat surcharge is computed per booking and is charged to every
        booking regardless of `payment_mode` and regardless of `loyalty_tier`."

        Design: Corner/calculations/seat_surcharge_rounds_per_reservation_never_per_guest
        """
        scenario = setup_floor(tables=(("T6", 6), ("T6", 6)),
                               chefs=(("Kenji Ito", "ZONE_A"), ("Ana Ruiz", "ZONE_B")))
        gold = create_party(scenario, loyalty_tier="GOLD")
        plain = create_party(scenario, loyalty_tier="NONE", name="Rue Calloway",
                             phone="212-555-0111")

        gold_seat = book_hold_seat(scenario, gold["id"], "T6", scenario["tables"][0]["id"],
                                   party_size=4)
        plain_seat = book_hold_seat(scenario, plain["id"], "T6", scenario["tables"][1]["id"],
                                    party_size=4)

        assert gold_seat["reservation"]["seat_surcharge_cents"] == 1925
        assert plain_seat["reservation"]["seat_surcharge_cents"] == 1925

        entries = ledger_entries(scenario["venue"]["id"], gold_seat["reservation"]["id"],
                                 "SEAT_SURCHARGE")
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 1925
        assert entries[0]["status"] == "POSTED"

    def test_seat_surcharge_guest_cap_bites_at_three_not_two(self):
        """PRD §3.9: "the guests billed — the smaller of the party size and the cap of
        3 — and divided by one more than the party size. The raw value is then ceilinged
        once, per booking and not per guest, to the next whole multiple of 25 cents."

        Design: Corner/calculations/seat_surcharge_guest_cap_bites_at_three_not_two
        """
        scenario = setup_floor(tables=(("T6", 6), ("T6", 6)),
                               chefs=(("Kenji Ito", "ZONE_A"), ("Ana Ruiz", "ZONE_B")))
        party = create_party(scenario, loyalty_tier="GOLD")

        three = book_hold_seat(scenario, party["id"], "T6", scenario["tables"][0]["id"],
                               party_size=3)
        assert three["reservation"]["seat_surcharge_cents"] == 2400

        grown = get_success_data(api_client.change_party_size(
            three["reservation"]["id"], {"party_size": 4}, HOST))
        assert grown["seat_surcharge_cents"] == 1925

        two = book_hold_seat(scenario, party["id"], "T6", scenario["tables"][1]["id"],
                             party_size=2, scheduled_time="2026-09-03T20:00:00Z")
        assert two["reservation"]["seat_surcharge_cents"] == 2150


class TestRestaurantChargeBand:

    def test_restaurant_charge_multiplier_band_boundary_at_fifty(self):
        """PRD §3.8: "the venue's `restaurant_charge_cents` is recomputed from scratch —
        never accumulated — as the billable guest count multiplied by a per-guest
        assignment fee of 299 cents. The billable guest count is the sum, across the
        venue's grill tables, of the smaller of each table's `seat_capacity` and the
        assignable guest cap of 12."
        PRD §3.8: "A multiplier band is then applied: a billable count below 50 is
        `LOW` at 0.90, a count from 50 through 70 inclusive is `MEDIUM` at 1.00, and a
        count above 70 is `HIGH` at 1.20."

        Design: Corner/calculations/restaurant_charge_multiplier_band_boundary_at_fifty_and_seventy
        """
        scenario = setup_floor(tier_codes=("T6",),
                               tables=(("T6", 10), ("T6", 10), ("T6", 10), ("T6", 10)),
                               chefs=())
        venue_id = scenario["venue"]["id"]

        low = get_success_data(api_client.run_ops(venue_id, FM))
        assert low["restaurant_charge_cents"] == 40 * 299 * 0.90

        get_success_data(api_client.create_table(
            {"venue_id": venue_id, "tier_code": "T6", "seat_capacity": 10}, FM))
        boundary = get_success_data(api_client.run_ops(venue_id, FM))
        assert boundary["restaurant_charge_cents"] == 50 * 299 * 1.00
        assert boundary["ops_epoch"] == 2


class TestVenueCostReport:

    def test_venue_cost_report_ceiling_applied_once_to_the_sum(self):
        """PRD §3.8: "The read-side venue cost report is computed differently and is
        never persisted: it sums, across the venue's grill tables whose tier is one of
        `T2`, `T4`, `T6` or `T8`, the product of the tier's `base_rate_per_guest_cents`
        and its `protein_gram_standard`, and then ceilings that summed total once to the
        next whole multiple of 100 cents."
        PRD §2.7: "`venue_cost_report` ceilings its summed total once to the next whole
        multiple of 100 cents."

        Design: Corner/calculations/venue_cost_report_ceiling_applied_once_to_the_sum
        """
        scenario = setup_floor(tables=(("T6", 6), ("T4", 4), ("T2", 2)), chefs=())

        report = validate_success(api_client.get_cost_report(scenario["venue"]["id"], FM))
        assert report["billable_guest_count"] == 4 + 6 + 2
        assert report["venue_cost_cents"] == 2304000
        assert isinstance(report["venue_cost_cents"], int)
        assert report["venue_cost_cents"] % 100 == 0

    def test_venue_cost_report_read_matches_a_direct_recomputation(self):
        """PRD §3.8: "The read-side venue cost report is computed differently and is
        never persisted" and "Every table whose tier is `ACTIVE` is counted, regardless
        of the table's own status".
        PRD §2.4: "`version` is an integer that starts at its initial value and
        increments by exactly one on every mutation of the row."

        Design: Corner/endpoints/venue_cost_report_read_matches_a_direct_recomputation
        """
        scenario = setup_floor(tables=(("T6", 6), ("T4", 4), ("T2", 2)), chefs=())
        venue_id = scenario["venue"]["id"]

        after_ops = get_success_data(api_client.run_ops(venue_id, FM))
        # 12 billable guests is below 50, so the LOW band multiplier 0.90 applies.
        assert after_ops["restaurant_charge_cents"] == 12 * 299 * 0.90

        first = get_success_data(api_client.get_cost_report(venue_id, FM))
        second = get_success_data(api_client.get_cost_report(venue_id, FM))
        assert first["venue_cost_cents"] == second["venue_cost_cents"] == 2304000

        reread = get_success_data(api_client.get_venue(venue_id, FM))
        assert reread["version"] == after_ops["version"]
        assert reread["restaurant_charge_cents"] == 12 * 299 * 0.90
        assert reread["restaurant_charge_cents"] != first["venue_cost_cents"]