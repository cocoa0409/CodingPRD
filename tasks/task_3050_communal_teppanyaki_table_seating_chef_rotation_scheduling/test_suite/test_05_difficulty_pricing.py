"""Depth probes on the pricing and cost rules: the two settlement variants, the two
protein-cost variants, the occupancy-window variant, and the two pinned evaluation
orders (true-up band-then-ceiling, credit cap read before applied).
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
    grant_hold,
    ledger_entries,
    mint_party_credit,
    perform_grill_phase,
    perform_sushi_phase,
    read_party,
    read_reservation,
    seed_seated_booking_with_finished_grill,
    set_clock,
    setup_floor,
    shift_instant,
    start_show,
    submit_booking,
)
from test_helpers.test_users import make_chef_headers

CLOCK = "2026-09-02T12:00:00Z"


class TestSettlementVariantGap:

    def test_birthday_quote_and_final_bill_differ_by_the_celebration_fee(self):
        """PRD §3.2: "a provisional quote is stamped into `quote_final_cents`
        immediately. That provisional figure is the quote variant of the settlement
        rule, in which the celebration fee term is dropped."
        PRD §3.9: "The only difference between them is the celebration term: the quote
        drops it, so a celebration booking quotes strictly lower than the final bill of
        the same inputs."

        Design: Difficulty/dual_variant_calc/settlement_quote_vs_final_celebration_fee_gap
        """
        scenario = setup_floor(clock=CLOCK, tables=(("T6", 6),),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="PLATINUM")

        reservation = create_booking(scenario, party["id"], "T6", party_size=3,
                                     celebration="BIRTHDAY")
        submitted = submit_booking(reservation["id"])
        assert submitted["quote_final_cents"] == 9600

        grant_hold(reservation["id"], scenario["tables"][0]["id"], scenario)

        seafood = book_hold_seat(scenario, party["id"], "T6",
                                 scenario["tables"][0]["id"],
                                 party_size=3, celebration="BIRTHDAY")
        chef_id = seafood["reservation"]["chef_assignment_id"]
        perform_sushi_phase(seafood["sushi_show_id"], CLOCK, chef_id)
        _, finished_grill = perform_grill_phase(seafood["grill_show_id"], CLOCK, chef_id)

        assert finished_grill["final_bill_cents"] == 10500
        assert finished_grill["quote_final_cents"] == 9600
        assert finished_grill["final_bill_cents"] - finished_grill["quote_final_cents"] == 900

    def test_quote_slot_is_not_re_read_as_the_bill_before_the_grill_finishes(self):
        """PRD §3.9: "The quote variant runs while the booking is `DRAFT`, `REQUESTED`
        or `HELD` and writes `quote_final_cents`; the final variant runs when a `GRILL`
        phase finishes, when an occupancy vacates, or when the booking closes."
        PRD §3.2: "the booking is priced as the smaller of the tier's capacity-derived
        ceiling and the party's entitlement."

        Design: Difficulty/dual_variant_calc/settlement_quote_vs_final_celebration_fee_gap
        """
        scenario = setup_floor(clock=CLOCK, tables=(("T6", 6),),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="PLATINUM")

        seafood = book_hold_seat(scenario, party["id"], "T6",
                                 scenario["tables"][0]["id"],
                                 party_size=3, celebration="BIRTHDAY")
        seated = seafood["reservation"]
        assert seated["quote_final_cents"] == 9600
        assert seated["final_bill_cents"] == 0

        chef_id = seated["chef_assignment_id"]
        perform_sushi_phase(seafood["sushi_show_id"], CLOCK, chef_id)

        set_clock(shift_instant(CLOCK, 3))
        started = start_show(seafood["grill_show_id"], chef_id)
        assert started["final_bill_cents"] == 0

        reread = read_reservation(seafood["reservation"]["id"])
        assert reread["quote_final_cents"] == 9600
        assert reread["final_bill_cents"] == 0
        assert reread["final_bill_cents"] != reread["quote_final_cents"]


class TestProteinCostVariants:

    def test_three_guest_grill_start_posts_the_ticket_and_the_persisted_rollup(self):
        """PRD §3.5: "It issues protein: a `ProteinTicket` row is created carrying
        `standard_grams`, `issued_grams` and the status `POSTED`, with its `show_id`
        pointing at the phase."
        PRD §3.8: "a `cost_cents` computed as the issued grams multiplied by a pinned
        cost of 4.0 cents per gram and rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/protein_cost_posted_vs_settled_control_allowance_gap
        """
        scenario = setup_floor(clock=CLOCK, tables=(("T6", 6),),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="PLATINUM")

        seafood = book_hold_seat(scenario, party["id"], "T6",
                                 scenario["tables"][0]["id"], party_size=3,
                                 celebration="NONE")
        chef_id = seafood["reservation"]["chef_assignment_id"]
        perform_sushi_phase(seafood["sushi_show_id"], CLOCK, chef_id)

        set_clock(shift_instant(CLOCK, 3))
        started = start_show(seafood["grill_show_id"], chef_id)
        ticket_id = started["protein_ticket_id"]

        ticket = get_success_data(api_client.get_protein_ticket(ticket_id, FM))
        assert ticket["standard_grams"] == 720
        assert ticket["issued_grams"] == 540
        assert ticket["variance_grams"] == -180
        assert float(ticket["cost_cents"]) == 2160.0

        venue = get_success_data(api_client.get_venue(scenario["venue"]["id"], FM))
        assert float(venue["protein_cost_cents"]) == 2160.0

    def test_control_allowance_is_five_percent_of_the_rollup_and_is_never_persisted(self):
        """PRD §3.8: "`protein_cost_cents` is the sum of that per-ticket cost across
        every ticket at the venue whose status is `POSTED`."
        PRD §3.8: "a control allowance computed as five percent of the cost, which is
        never persisted into `protein_cost_cents`."

        Design: Difficulty/dual_variant_calc/protein_cost_posted_vs_settled_control_allowance_gap
        """
        scenario = setup_floor(clock=CLOCK, tables=(("T6", 6),),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="PLATINUM")

        seafood = book_hold_seat(scenario, party["id"], "T6",
                                 scenario["tables"][0]["id"], party_size=3,
                                 celebration="NONE")
        chef_id = seafood["reservation"]["chef_assignment_id"]
        perform_sushi_phase(seafood["sushi_show_id"], CLOCK, chef_id)

        set_clock(shift_instant(CLOCK, 3))
        start_show(seafood["grill_show_id"], chef_id)

        venue_id = scenario["venue"]["id"]
        persisted = float(get_success_data(api_client.get_venue(venue_id, FM))["protein_cost_cents"])
        assert persisted == 2160.0

        report = get_success_data(api_client.get_protein_cost_report(venue_id, FM))
        assert float(report["protein_cost_cents"]) == 2160.0
        assert float(report["control_allowance_cents"]) == 108.0
        assert report["control_allowance_cents"] > 0

        after_read = get_success_data(api_client.get_venue(venue_id, FM))
        assert float(after_read["protein_cost_cents"]) == 2160.0

    def test_the_variant_split_is_stable_before_any_variance_adjustment(self):
        """PRD §3.5: "The `standard_grams` for a grill phase is the sum of `guest_count`
        across the `ACTIVE` `TableSeating` rows at the show's table ... multiplied by the
        tier's `protein_gram_standard`."
        PRD §3.8: "`protein_cost_cents` is the sum of that per-ticket cost across every
        ticket at the venue whose status is `POSTED`."
        PRD §3.8: "a control allowance computed as five percent of the cost, which is
        never persisted into `protein_cost_cents`."

        Design: Difficulty/dual_variant_calc/protein_cost_role_variant_on_the_documented_control_report
        """
        scenario = setup_floor(clock=CLOCK, tables=(("T6", 6),),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")

        seafood = book_hold_seat(scenario, party["id"], "T6",
                                 scenario["tables"][0]["id"], party_size=4,
                                 celebration="NONE")
        chef_id = seafood["reservation"]["chef_assignment_id"]
        perform_sushi_phase(seafood["sushi_show_id"], CLOCK, chef_id)

        set_clock(shift_instant(CLOCK, 3))
        started = start_show(seafood["grill_show_id"], chef_id)
        ticket_id = started["protein_ticket_id"]
        venue_id = scenario["venue"]["id"]

        ticket = get_success_data(api_client.get_protein_ticket(ticket_id, FM))
        assert ticket["standard_grams"] == 960
        assert ticket["issued_grams"] == 720
        assert float(ticket["cost_cents"]) == 2880.0

        persisted = get_success_data(api_client.get_venue(venue_id, FM))
        assert float(persisted["protein_cost_cents"]) == 2880.0

        report = get_success_data(api_client.get_protein_cost_report(venue_id, FM))
        assert float(report["control_allowance_cents"]) == 144.0
        assert float(report["protein_cost_cents"]) == 2880.0

    def test_the_split_stays_stable_across_a_variance_adjustment(self):
        """PRD §3.5: "An accepted adjustment adds `delta_grams` to `issued_grams`,
        recomputes `variance_grams`, recomputes the ticket's `cost_cents`, and refreshes
        both the venue rollup and the chef's issued pounds."
        PRD §3.8: "a control allowance computed as five percent of the cost, which is
        never persisted into `protein_cost_cents`."

        Design: Difficulty/dual_variant_calc/protein_cost_role_variant_on_the_documented_control_report
        """
        scenario = setup_floor(clock=CLOCK, tables=(("T6", 6),),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")

        seafood = book_hold_seat(scenario, party["id"], "T6",
                                 scenario["tables"][0]["id"], party_size=4,
                                 celebration="NONE")
        chef_id = seafood["reservation"]["chef_assignment_id"]
        perform_sushi_phase(seafood["sushi_show_id"], CLOCK, chef_id)

        set_clock(shift_instant(CLOCK, 3))
        started = start_show(seafood["grill_show_id"], chef_id)
        ticket_id = started["protein_ticket_id"]
        venue_id = scenario["venue"]["id"]

        adjusted = validate_success(api_client.adjust_protein_variance(
            ticket_id, 20, make_chef_headers(chef_id)))
        assert adjusted["issued_grams"] == 740
        assert adjusted["variance_grams"] == -220
        assert float(adjusted["cost_cents"]) == 2960.0

        after = get_success_data(api_client.get_protein_cost_report(venue_id, FM))
        assert float(after["control_allowance_cents"]) == 148.0
        assert float(after["protein_cost_cents"]) == 2960.0

        persisted = get_success_data(api_client.get_venue(venue_id, FM))
        assert float(persisted["protein_cost_cents"]) == 2960.0
        assert float(persisted["protein_cost_cents"]) != 2960.0 + 148.0


class TestCreditCapEvaluationOrder:

    def _close_with_credit(self, credit_to_apply_cents):
        scenario = setup_floor(clock=CLOCK, tables=(("T6", 6), ("T4", 4)),
                               chefs=(("Kenji Ito", "ZONE_A"), ("Ana Ruiz", "ZONE_B")))
        # §3.6: credit is the party's OWN reusable balance (granted when a posted
        # charge is voided back to it). Minting and consuming use the same party; the
        # minted booking closes so it no longer forms a combination set with the
        # booking under test.
        gold = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                            phone="212-555-0177")
        mint = mint_party_credit(scenario, gold["id"], "T4",
                                 scenario["tables"][1]["id"], party_size=4)
        wallet_after_mint = mint[1]

        seated = seed_seated_booking_with_finished_grill(
            scenario, gold["id"], "T6", scenario["tables"][0]["id"], party_size=3)
        current = read_reservation(seated["reservation"]["id"])
        closed = validate_success(api_client.close_reservation(
            seated["reservation"]["id"],
            {"expected_reservation_version": current["version"],
             "credit_to_apply_cents": credit_to_apply_cents}, HOST))
        return scenario, gold, wallet_after_mint, closed

    def test_credit_cap_is_taken_from_the_pre_credit_check(self):
        """PRD §3.6: "`check_cents` is evaluated first with `credit_applied_cents` held
        at its stored value, then `credit_applied_cents` is recomputed as the smallest
        of the party's `loyalty_credit_cents`, the requested `credit_to_apply_cents`,
        and the credit cap."
        PRD §3.6: "An application exceeding the cap — the smaller of 2500 cents and
        twelve percent of the pre-credit check — is rejected with `ERR_CREDIT_OVER_CAP`
        (HTTP 422), the cap being floored to a whole cent and taken from the first
        evaluation of the check."

        Design: Difficulty/combinatorial_formula/credit_cap_read_before_then_applied_after
        """
        scenario, gold, wallet_after_mint, closed = self._close_with_credit(1620)

        assert closed["final_bill_cents"] == 9600
        assert closed["seat_surcharge_cents"] == 2400
        assert closed["credit_applied_cents"] == 1620
        assert closed["check_cents"] == 9600 + 2400 - 1620 + 1500
        assert closed["status"] == "CLOSED"

        wallet_now = read_party(gold["id"])["loyalty_credit_cents"]
        assert wallet_now == wallet_after_mint - 1620
        assert wallet_now >= 0

    def test_cap_is_not_re_derived_from_the_post_credit_check(self):
        """PRD §2.7: "In the credit application, `check_cents` is evaluated first with
        `credit_applied_cents` held at the reservation's stored value, and only then is
        `credit_applied_cents` recomputed, after which `check_cents` is re-evaluated
        exactly once. The cap term is defined over the first evaluation and is never
        re-derived from the second."

        Design: Difficulty/combinatorial_formula/credit_cap_read_before_then_applied_after
        """
        scenario, gold, wallet_after_mint, closed = self._close_with_credit(1620)

        first_evaluation = 9600 + 2400 + 1500
        assert closed["credit_applied_cents"] == 1620
        assert int(min(2500, 0.12 * first_evaluation)) == 1620
        assert int(min(2500, 0.12 * closed["check_cents"])) == 1425
        assert closed["credit_applied_cents"] != 1425
        assert closed["check_cents"] == first_evaluation - closed["credit_applied_cents"]


class TestOccupancyWindowVariant:

    def _two_occupancies(self, tier_code):
        scenario = setup_floor(clock="2026-09-03T19:00:00Z",
                               tables=((tier_code, 4), (tier_code, 4)),
                               chefs=(("Kenji Ito", "ZONE_A"), ("Ana Ruiz", "ZONE_B")))
        gold = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                            phone="212-555-0177")
        plat = create_party(scenario, loyalty_tier="PLATINUM")

        scenario["clock"] = "2026-09-03T19:00:00Z"
        plain = book_hold_seat(scenario, gold["id"], tier_code,
                               scenario["tables"][0]["id"], party_size=4,
                               celebration="NONE",
                               scheduled_time="2026-09-03T18:55:00Z")
        birthday = book_hold_seat(scenario, plat["id"], tier_code,
                                  scenario["tables"][1]["id"], party_size=4,
                                  celebration="BIRTHDAY",
                                  scheduled_time="2026-09-03T18:55:00Z")
        return scenario, plain, birthday

    def test_celebration_occupancy_uses_the_longer_turn_time_standard(self):
        """PRD §3.4: "the `expected_vacate_at` is that start instant plus the tier's
        `turn_time_standard_minutes` when the booking's `celebration` is `NONE`, and
        plus the tier's `turn_time_celebration_minutes` when it is not."
        PRD §2.6: "A `TableSeating` row records `seated_at`, an `expected_vacate_at`
        derived by the turn-over rule in §3.4."

        Design: Difficulty/dual_variant_calc/turn_over_window_standard_vs_celebration_tenure_variant
        """
        scenario, plain, birthday = self._two_occupancies("T4")

        plain_seating = get_success_data(api_client.get_seating(plain["seating_id"], FM))
        birthday_seating = get_success_data(api_client.get_seating(birthday["seating_id"], FM))

        assert plain_seating["seated_at"] == "2026-09-03T19:00:00Z"
        assert birthday_seating["seated_at"] == "2026-09-03T19:00:00Z"
        assert plain_seating["expected_vacate_at"] == shift_instant(
            plain_seating["seated_at"],
            scenario["tiers"]["T4"]["turn_time_standard_minutes"])
        assert birthday_seating["expected_vacate_at"] == shift_instant(
            birthday_seating["seated_at"],
            scenario["tiers"]["T4"]["turn_time_celebration_minutes"])

    def test_the_two_occupancy_windows_differ_by_exactly_the_turn_time_gap(self):
        """PRD §3.4: "the `expected_vacate_at` is that start instant plus the tier's
        `turn_time_standard_minutes` when the booking's `celebration` is `NONE`, and
        plus the tier's `turn_time_celebration_minutes` when it is not."
        PRD §2.6: "Occupancy on a grill table is modelled as a half-open interval."

        Design: Difficulty/dual_variant_calc/turn_over_window_standard_vs_celebration_tenure_variant
        """
        scenario, plain, birthday = self._two_occupancies("T4")

        plain_seating = get_success_data(api_client.get_seating(plain["seating_id"], FM))
        birthday_seating = get_success_data(api_client.get_seating(birthday["seating_id"], FM))

        tier = scenario["tiers"]["T4"]
        assert plain_seating["expected_vacate_at"] != birthday_seating["expected_vacate_at"]
        assert (tier["turn_time_celebration_minutes"] -
                tier["turn_time_standard_minutes"]) == 20
        assert plain_seating["seated_at"] == birthday_seating["seated_at"]


class TestTrueupBandThenCeilingOrder:

    def test_shortfall_band_is_applied_then_ceiled_once(self):
        """PRD §3.6: "The true-up works on the raw shortfall — the tier minimum less the
        final bill, floored at zero — and bands it: a zero shortfall yields a band of
        zero; a shortfall of up to 1000 cents takes a factor of 0.50; a shortfall of up
        to 2000 cents takes a factor of 0.60."
        PRD §2.7: "In the table-minimum true-up, the band factor is applied first and
        the ceiling is applied once to the band result."
        PRD §3.6: "For a 1200-cent shortfall the banded amount is 720 cents and the
        true-up is 725 cents."

        Design: Difficulty/combinatorial_formula/trueup_band_then_ceiling_order
        """
        scenario = setup_floor(clock=CLOCK, tables=(("T4", 4),),
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

        assert closed["final_bill_cents"] == 12800
        assert closed["check_cents"] == (closed["final_bill_cents"] +
                                         closed["seat_surcharge_cents"] -
                                         closed["credit_applied_cents"] + 725)

        entries = ledger_entries(scenario["venue"]["id"], seafood["reservation"]["id"],
                                 "TABLE_MINIMUM_TRUEUP")
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 725
        assert entries[0]["status"] == "POSTED"

    def test_per_guest_ceiling_sum_is_not_the_pinned_order(self):
        """PRD §3.6: "For a 1200-cent shortfall the banded amount is 720 cents and the
        true-up is 725 cents; ceiling each guest's share separately and summing would
        produce 800 and is explicitly wrong, and ceiling before applying the band factor
        is wrong as well."
        PRD §2.7: "`table_minimum_trueup` and `seat_surcharge` both ceiling their result
        to the next whole multiple of 25 cents."

        Design: Difficulty/combinatorial_formula/trueup_band_then_ceiling_order
        """
        scenario = setup_floor(clock=CLOCK, tables=(("T4", 4),),
                               chefs=(("Kenji Ito", "ZONE_A"),))
        party = create_party(scenario, loyalty_tier="GOLD", name="Owen Marsh",
                             phone="212-555-0177")

        seafood = seed_seated_booking_with_finished_grill(
            scenario, party["id"], "T4", scenario["tables"][0]["id"], party_size=4)

        current = read_reservation(seafood["reservation"]["id"])
        get_success_data(api_client.close_reservation(
            seafood["reservation"]["id"],
            {"expected_reservation_version": current["version"], "credit_to_apply_cents": 0},
            HOST))

        entries = ledger_entries(scenario["venue"]["id"], seafood["reservation"]["id"],
                                 "TABLE_MINIMUM_TRUEUP")
        amount = entries[0]["amount_cents"]

        assert amount == 725
        assert amount % 25 == 0
        assert amount != 800
