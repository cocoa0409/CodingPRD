"""Haul pay in both its variants, the certification cascade and the rehaul selector."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    build_network,
    certify_ticket,
    create_haul_route,
    create_mill,
    create_mill_contract,
    deliver_load,
    dispatch_load,
    depart_load,
    arrive_load,
    load_at_mill,
    read_delivery_ticket,
    read_load,
    read_mill_contract,
    read_tract,
    reject_ticket,
    rehaul_children,
    set_clock,
    validate_error,
    validate_success,
    write_ticket,
)


class TestProvisionalVersusFinalPay:
    def test_dispatch_books_the_provisional_figure_off_the_woods_estimate(self, api):
        """PRD §3.6: "A per-ton-mile rate is selected from the **whole** route distance
        — an average-rate selection, not a marginal waterfall: 26 cents per ton-mile
        when `distance_miles` is 30 or less, 22 cents when it is more than 30 but no
        more than 70, and 19 cents beyond 70."
        PRD §3.6: "At dispatch that machinery runs in its **provisional** form: the
        tonnage is the woods estimate `estimated_net_tons`, taken before any defect
        deduction; the wait is zero so demurrage is always zero; and no regrade penalty
        ever applies, because nothing has been scaled. The result is written to
        `provisional_haul_pay_cents` and is **never revised**, not even after
        certification."

        Design: Difficulty/dual_variant_calc/provisional_dispatch_pay_versus_final_certified_pay_on_one_load
        """
        scn = build_network()

        load = dispatch_load(scn, estimated_net_tons=26.50)

        assert load["rate_cents_per_ton_mile"] == 22
        assert load["provisional_haul_pay_cents"] == 32_590

    def test_certification_writes_a_different_final_figure_off_the_scaled_tonnage(
        self, api
    ):
        """PRD §3.8: "The final form of the haul-pay calculation differs from the
        provisional form of §3.6 in exactly three inputs, and in nothing else. The
        tonnage is the ticket's `net_tons`, scaled *after* the defect deduction, rather
        than the woods estimate."
        PRD §3.8: "The wait is real: `wait_minutes` is the elapsed time from the load's
        `arrived_at` to the ticket's `certified_at`, expressed in seconds, divided by
        60 and rounded **down** to a whole number of minutes; the free window of 45
        minutes and the 150-cents-per-minute rate then apply as described."
        PRD §3.7: "The defect deduction is that net weight multiplied by
        `defect_deduction_pct`, rounded half-up to whole **pounds**, stored as
        `defect_deducted_lbs`. The payable weight is the net weight less the rounded
        deduction, stored as `payable_lbs`. Only that integer pound figure is then
        divided by 2,000 pounds per ton and rounded half-up to two decimal places,
        giving `net_tons` — the scaled tonnage that every downstream money figure uses.
        Converting to tons first and deducting afterwards is a different answer and is
        forbidden."

        Design: Difficulty/dual_variant_calc/provisional_dispatch_pay_versus_final_certified_pay_on_one_load
        """
        scn = build_network()
        load = dispatch_load(scn, estimated_net_tons=26.50)
        depart_load(scn, load["id"])
        set_clock("2026-08-03T15:10:00Z")
        arrive_load(scn, load["id"])
        set_clock("2026-08-03T16:00:00Z")
        ticket = write_ticket(
            scn, load["id"], gross_weight_lbs=90000, defect_deduction_pct=0.04
        )

        certify_ticket(scn, ticket["id"])

        ticket_row = read_delivery_ticket(ticket["id"])
        assert ticket_row["net_weight_lbs"] == 59_000
        assert ticket_row["defect_deducted_lbs"] == 2_360
        assert ticket_row["payable_lbs"] == 56_640
        assert ticket_row["net_tons"] == pytest.approx(28.32, abs=0.005)

        load_row = read_load(load["id"])
        assert load_row["provisional_haul_pay_cents"] == 32_590
        assert load_row["rate_cents_per_ton_mile"] == 22
        assert load_row["wait_minutes"] == 50
        assert load_row["line_haul_cents"] == 32_398
        assert load_row["fuel_surcharge_cents"] == 2_430
        assert load_row["demurrage_cents"] == 750
        assert load_row["incentive_cents"] == 0
        assert load_row["regrade_adjustment_cents"] == 0
        assert load_row["final_haul_pay_cents"] == 35_578
        assert (
            load_row["final_haul_pay_cents"] != load_row["provisional_haul_pay_cents"]
        ), "the two variants are deliberately different numbers, both retained"


class TestHaulPayComponents:
    def test_the_rate_band_is_selected_from_the_whole_route_distance(self, api):
        """PRD §3.6: "A per-ton-mile rate is selected from the **whole** route distance
        — an average-rate selection, not a marginal waterfall: 26 cents per ton-mile
        when `distance_miles` is 30 or less, 22 cents when it is more than 30 but no
        more than 70, and 19 cents beyond 70."
        PRD §3.6: "The line-haul component is the tonnage multiplied by that rate
        multiplied by the route distance, rounded half-up to whole cents."

        Design: Corner/calculations/rate_band_boundary_makes_a_thirty_one_mile_haul_cheaper_than_a_thirty_mile_haul
        """
        scn = build_network(route={"distance_miles": 30})
        route_31 = create_haul_route(
            scn["tract_id"], scn["mill_a_id"], distance_miles=31
        )

        load_30 = dispatch_load(
            scn,
            estimated_net_tons=26.5,
            scheduled_depart_at="2026-08-03T08:00:00Z",
            scheduled_arrive_at="2026-08-03T10:00:00Z",
        )
        load_31 = dispatch_load(
            scn,
            route_id=route_31["id"],
            estimated_net_tons=26.5,
            scheduled_depart_at="2026-08-04T08:00:00Z",
            scheduled_arrive_at="2026-08-04T10:00:00Z",
        )

        assert load_30["rate_cents_per_ton_mile"] == 26
        assert load_30["provisional_haul_pay_cents"] == 22_220
        assert load_31["rate_cents_per_ton_mile"] == 22
        assert load_31["provisional_haul_pay_cents"] == 19_428
        assert (
            load_31["provisional_haul_pay_cents"]
            < load_30["provisional_haul_pay_cents"]
        )

    def test_demurrage_starts_only_past_the_forty_five_minute_free_window(self, api):
        """PRD §3.6: "Demurrage is the wait beyond a free window of 45 minutes, charged
        at 150 cents for each minute of excess, with no negative result."
        PRD §3.8: "The wait is real: `wait_minutes` is the elapsed time from the load's
        `arrived_at` to the ticket's `certified_at`, expressed in seconds, divided by
        60 and rounded **down** to a whole number of minutes; the free window of 45
        minutes and the 150-cents-per-minute rate then apply as described."

        Design: Corner/calculations/demurrage_free_wait_window_boundary_at_forty_five_minutes
        """
        scn = build_network()

        free = dispatch_load(
            scn,
            estimated_net_tons=26.5,
            scheduled_depart_at="2026-08-03T08:00:00Z",
            scheduled_arrive_at="2026-08-03T10:00:00Z",
        )
        depart_load(scn, free["id"])
        set_clock("2026-08-03T10:00:00Z")
        arrive_load(scn, free["id"])
        set_clock("2026-08-03T10:45:00Z")
        free_ticket = write_ticket(
            scn, free["id"], gross_weight_lbs=90000, defect_deduction_pct=0.04
        )
        certify_ticket(scn, free_ticket["id"])

        charged = dispatch_load(
            scn,
            estimated_net_tons=26.5,
            scheduled_depart_at="2026-08-04T08:00:00Z",
            scheduled_arrive_at="2026-08-04T10:00:00Z",
        )
        depart_load(scn, charged["id"])
        set_clock("2026-08-04T10:00:00Z")
        arrive_load(scn, charged["id"])
        set_clock("2026-08-04T10:46:00Z")
        charged_ticket = write_ticket(
            scn, charged["id"], gross_weight_lbs=90000, defect_deduction_pct=0.04
        )
        certify_ticket(scn, charged_ticket["id"])

        free_row = read_load(free["id"])
        assert free_row["wait_minutes"] == 45
        assert free_row["demurrage_cents"] == 0
        assert free_row["final_haul_pay_cents"] == 34_828

        charged_row = read_load(charged["id"])
        assert charged_row["wait_minutes"] == 46
        assert charged_row["demurrage_cents"] == 150
        assert charged_row["final_haul_pay_cents"] == 34_978

        assert read_mill_contract(scn["mc_a_id"])["delivered_tons"] == pytest.approx(
            56.64, abs=0.005
        )

    def test_a_mill_regrade_subtracts_five_percent_of_the_line_haul(self, api):
        """PRD §3.6: "A regrade penalty of 5 percent of the line-haul figure, rounded
        half-up to whole cents, is subtracted when the mill regraded the wood."
        PRD §3.8: "And the regrade penalty applies exactly when the ticket's
        `scaled_grade` differs from the load's `declared_grade`."

        Design: Corner/calculations/regrade_penalty_applies_when_the_mill_downgrades_the_scaled_grade
        """
        scn = build_network()
        load = load_at_mill(scn, estimated_net_tons=26.5)
        ticket = write_ticket(
            scn,
            load["id"],
            gross_weight_lbs=90000,
            defect_deduction_pct=0.04,
            scaled_grade="SAWLOG_2",
        )

        certify_ticket(scn, ticket["id"])

        assert read_delivery_ticket(ticket["id"])["scaled_grade"] == "SAWLOG_2"
        load_row = read_load(load["id"])
        assert load_row["declared_grade"] == "SAWLOG_1"
        assert load_row["line_haul_cents"] == 32_398
        assert load_row["regrade_adjustment_cents"] == 1_620
        assert load_row["final_haul_pay_cents"] == 33_208
        assert load_row["provisional_haul_pay_cents"] == 32_590

    def test_the_volume_incentive_keys_on_the_subtotal_not_the_payable_figure(
        self, api
    ):
        """PRD §3.6: "The three are added to a subtotal, and a volume incentive is
        applied to that subtotal: 4 percent when the subtotal is at least 120,000
        cents, otherwise 2 percent when the subtotal is at least 60,000 cents,
        otherwise nothing; the incentive is rounded half-up to whole cents."
        PRD §3.6: "The incentive tier is keyed on the subtotal of line haul, fuel and
        demurrage — never on the payable figure — so this is a single pass, not a
        fixed-point solve."

        Design: Corner/calculations/volume_incentive_tier_engages_once_the_subtotal_reaches_sixty_thousand_cents
        """
        scn = build_network(route={"distance_miles": 120})
        load = load_at_mill(
            scn,
            estimated_net_tons=30.0,
            scheduled_depart_at="2026-08-03T08:00:00Z",
            scheduled_arrive_at="2026-08-03T14:00:00Z",
        )
        ticket = write_ticket(
            scn, load["id"], gross_weight_lbs=91000, defect_deduction_pct=0.0
        )

        certify_ticket(scn, ticket["id"])

        load_row = read_load(load["id"])
        assert load_row["rate_cents_per_ton_mile"] == 19
        assert load_row["line_haul_cents"] == 68_400
        assert load_row["fuel_surcharge_cents"] == 5_130
        assert load_row["incentive_cents"] == 1_471
        assert load_row["final_haul_pay_cents"] == 75_001
        assert read_delivery_ticket(ticket["id"])["net_tons"] == pytest.approx(
            30.00, abs=0.005
        )


class TestCertificationCascade:
    def test_certifying_delivers_the_load_and_accrues_it_on_the_money_axis(self, api):
        """PRD §3.8: "Hop one: the ticket's `ticket_status` becomes `CERTIFIED`,
        `certified_at` is stamped with the logical clock, and `certified_by_user_id`
        records the certifying scaler."
        PRD §3.8: "Hop two: because the ticket was certified, the load advances
        `AT_MILL → DELIVERED`; its `wait_minutes`, `rate_cents_per_ton_mile`,
        `line_haul_cents`, `fuel_surcharge_cents`, `demurrage_cents`,
        `incentive_cents`, `regrade_adjustment_cents` and `final_haul_pay_cents` are
        all written from the **final** form of the haul-pay calculation; its
        `settlement_event_on` is set to the certification date; and on the independent
        money axis its `settlement_status` moves `UNSETTLED → ACCRUED`."

        Design: Difficulty/transitive_cascade/certification_cascade_ticket_load_contract_to_filled
        """
        scn = build_network(contract={"quota_tons": 28.0})
        load = load_at_mill(scn, estimated_net_tons=26.5)
        ticket = write_ticket(
            scn, load["id"], gross_weight_lbs=90000, defect_deduction_pct=0.04
        )

        certify_ticket(scn, ticket["id"])

        ticket_row = read_delivery_ticket(ticket["id"])
        assert ticket_row["ticket_status"] == "CERTIFIED"
        assert ticket_row["net_tons"] == pytest.approx(28.32, abs=0.005)
        assert ticket_row["certified_by_user_id"] == scn["mill_a_id"]

        load_row = read_load(load["id"])
        assert load_row["dispatch_status"] == "DELIVERED"
        assert load_row["settlement_status"] == "ACCRUED"
        assert load_row["wait_minutes"] == 0
        assert load_row["final_haul_pay_cents"] == 34_828

    def test_the_delivery_swaps_reserved_tons_for_delivered_tons_and_fills_the_contract(
        self, api
    ):
        """PRD §3.8: "Hop three: because the load became `DELIVERED`, its mill contract
        loses the load's `estimated_net_tons` from `reserved_tons`, gains the ticket's
        `net_tons` in `delivered_tons`, and recomputes `available_tons`; the tract's
        `produced_tons` is recomputed the same way. Hop four: because the recomputed
        `available_tons` fell to zero or below, a contract still `OPEN` moves
        `OPEN → FILLED`."

        Design: Difficulty/transitive_cascade/certification_cascade_ticket_load_contract_to_filled
        """
        scn = build_network(contract={"quota_tons": 28.0})
        load = load_at_mill(scn, estimated_net_tons=26.5)
        ticket = write_ticket(
            scn, load["id"], gross_weight_lbs=90000, defect_deduction_pct=0.04
        )

        certify_ticket(scn, ticket["id"])

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["reserved_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["delivered_tons"] == pytest.approx(28.32, abs=0.005)
        assert contract["available_tons"] == pytest.approx(-0.32, abs=0.005)
        assert contract["status"] == "FILLED"
        assert read_tract(scn["tract_id"])["produced_tons"] == pytest.approx(
            28.32, abs=0.005
        )

    def test_certifying_past_the_overrun_ceiling_is_refused(self, api):
        """PRD §3.8: "**Certifying** the ticket carries one further precondition, the
        overrun gate: the contract's `delivered_tons` *after* adding this ticket's
        `net_tons` must not exceed the committed `quota_tons` multiplied by one plus
        the contract's `overrun_tolerance_pct`, that ceiling itself rounded half-up to
        two decimal places. Exceeding it is refused with
        `ERR_OVERRUN_TOLERANCE_EXCEEDED`."

        Design: Corner/validations/certifying_past_the_overrun_tolerance_is_rejected
        """
        scn = build_network(
            contract={"quota_tons": 30.0}, truck={"axle_config": "SEVEN_AXLE"}
        )
        load = load_at_mill(scn, estimated_net_tons=30.0)
        ticket = write_ticket(
            scn, load["id"], gross_weight_lbs=95000, defect_deduction_pct=0.0
        )
        assert ticket["net_tons"] == pytest.approx(32.00, abs=0.005)

        response = api.certify_delivery_ticket(ticket["id"], scn["scaler_headers"])
        validate_error(response, ApiErrorId.ERR_OVERRUN_TOLERANCE_EXCEEDED.value, 422)

        assert read_delivery_ticket(ticket["id"])["ticket_status"] == "DRAFT"
        load_row = read_load(load["id"])
        assert load_row["dispatch_status"] == "AT_MILL"
        assert load_row.get("final_haul_pay_cents") is None

        contract = read_mill_contract(scn["mc_a_id"])
        assert contract["delivered_tons"] == pytest.approx(0.00, abs=0.005)
        assert contract["reserved_tons"] == pytest.approx(30.00, abs=0.005)
        assert contract["status"] == "FILLED"

    def test_a_rejected_ticket_can_never_be_certified_afterwards(self, api):
        """PRD §3.8: "A ticket sitting in `DRAFT` has exactly two futures, and both are
        the scaler's to choose. In either case the ticket must still be `DRAFT` —
        otherwise `ERR_INVALID_TICKET_STATE` — its load must still be `AT_MILL`, and
        the caller's `X-User-ID` must equal the ticket's `mill_id`."
        PRD §3.8: "When no candidate survives the filter, the original load's
        `rehaul_status` becomes `NO_ALTERNATE`, its `settlement_event_on` is set to its
        `rejected_on`, and its `settlement_status` moves `UNSETTLED → ACCRUED` so that
        a reject deduction can accrue against the carrier at settlement time."

        Design: Corner/state_machines/certifying_a_rejected_ticket_returns_invalid_ticket_state
        """
        scn = build_network()
        load = load_at_mill(scn, estimated_net_tons=26.5)
        ticket = write_ticket(
            scn, load["id"], gross_weight_lbs=88000, defect_deduction_pct=0.02
        )
        reject_ticket(scn, ticket["id"], reject_reason="EXCESS_DEFECT")

        response = api.certify_delivery_ticket(ticket["id"], scn["scaler_headers"])
        validate_error(response, ApiErrorId.ERR_INVALID_TICKET_STATE.value, 409)

        ticket_row = read_delivery_ticket(ticket["id"])
        assert ticket_row["ticket_status"] == "REJECTED"
        assert ticket_row["reject_reason"] == "EXCESS_DEFECT"

        load_row = read_load(load["id"])
        assert load_row["dispatch_status"] == "REJECTED"
        assert load_row["rehaul_status"] == "NO_ALTERNATE"
        assert load_row["settlement_status"] == "ACCRUED"
        assert load_row.get("final_haul_pay_cents") is None
        assert read_mill_contract(scn["mc_a_id"])["reserved_tons"] == pytest.approx(
            0.00, abs=0.005
        )


class TestRehaulSelector:
    def test_the_selector_maximises_net_yield_rather_than_the_mill_price(self, api):
        """PRD §3.8: "Among candidates, the winner is the one maximising net yield in
        whole cents, where net yield is the contract's `base_rate_cents_per_ton`
        multiplied by the ticket's `net_tons` and rounded half-up to whole cents — the
        revenue term is the only term that rounds — less the route's `distance_miles`
        multiplied by 85 cents of cost per mile."
        PRD §3.8: "When a winner exists, the original load's `rehaul_status` becomes
        `REHAULED`, its `settlement_event_on` stays null, and no reject deduction ever
        accrues against it."

        Design: Corner/cross_cutting_complexity_layers/rehaul_selector_prefers_net_yield_over_the_higher_base_rate
        """
        scn = build_network()
        mill_b = create_mill(name="Basin Mill B")
        contract_b = create_mill_contract(
            mill_b["id"], quota_tons=200, base_rate_cents_per_ton=4400
        )
        route_b = create_haul_route(scn["tract_id"], mill_b["id"], distance_miles=40)
        mill_c = create_mill(name="Divide Mill C")
        contract_c = create_mill_contract(
            mill_c["id"], quota_tons=200, base_rate_cents_per_ton=4600
        )
        create_haul_route(scn["tract_id"], mill_c["id"], distance_miles=130)

        load = load_at_mill(scn, estimated_net_tons=26.5)
        ticket = write_ticket(
            scn, load["id"], gross_weight_lbs=90000, defect_deduction_pct=0.04
        )
        reject_ticket(scn, ticket["id"], reject_reason="CONTAMINATION")

        original = read_load(load["id"])
        assert original["dispatch_status"] == "REJECTED"
        assert original["rehaul_status"] == "REHAULED"
        assert original["settlement_status"] == "UNSETTLED"
        assert original.get("settlement_event_on") is None

        children = rehaul_children(load["id"])
        assert len(children) == 1
        rehaul = children[0]
        assert rehaul["mill_contract_id"] == contract_b["id"]
        assert rehaul["mill_contract_id"] != contract_c["id"]
        assert rehaul["haul_route_id"] == route_b["id"]
        assert rehaul["estimated_net_tons"] == pytest.approx(28.32, abs=0.005)
        assert rehaul["provisional_haul_pay_cents"] == 26_791
        assert rehaul["dispatch_status"] == "DISPATCHED"
        assert rehaul["declared_grade"] == "SAWLOG_1"
        assert_instant_equals(
            rehaul["scheduled_depart_at"], "2026-08-01T00:00:00Z", "scheduled_depart_at"
        )
        assert_instant_equals(
            rehaul["scheduled_arrive_at"], "2026-08-01T00:54:00Z", "scheduled_arrive_at"
        )

        assert read_mill_contract(contract_b["id"])["reserved_tons"] == pytest.approx(
            28.32, abs=0.005
        )
        assert read_mill_contract(contract_c["id"])["reserved_tons"] == pytest.approx(
            0.00, abs=0.005
        )
        rejecting = read_mill_contract(scn["mc_a_id"])
        assert rejecting["reserved_tons"] == pytest.approx(0.00, abs=0.005)
        assert rejecting["available_tons"] == pytest.approx(500.00, abs=0.005)

    def test_a_tie_on_net_yield_and_distance_falls_back_to_the_earlier_contract(
        self, api
    ):
        """PRD §3.8: "Ties are broken in this order: the candidate with the smaller
        `distance_miles` wins, and if that is still tied, the candidate contract with
        the earlier `created_at` wins. No ranking, tie-break or ordering rule anywhere
        in this system consults an `id`."

        Design: Corner/cross_cutting_complexity_layers/rehaul_selector_tie_break_uses_created_at_and_never_the_row_id
        """
        scn = build_network()
        mill_b = create_mill(name="Basin Mill B")
        contract_b = create_mill_contract(
            mill_b["id"], quota_tons=200, base_rate_cents_per_ton=4400
        )
        create_haul_route(scn["tract_id"], mill_b["id"], distance_miles=40)
        mill_c = create_mill(name="Divide Mill C")
        contract_c = create_mill_contract(
            mill_c["id"], quota_tons=200, base_rate_cents_per_ton=4400
        )
        create_haul_route(scn["tract_id"], mill_c["id"], distance_miles=40)

        load = load_at_mill(scn, estimated_net_tons=26.5)
        ticket = write_ticket(
            scn, load["id"], gross_weight_lbs=90000, defect_deduction_pct=0.04
        )
        reject_ticket(scn, ticket["id"], reject_reason="SPECIES_MISMATCH")

        assert read_load(load["id"])["rehaul_status"] == "REHAULED"

        children = rehaul_children(load["id"])
        assert len(children) == 1
        rehaul = children[0]
        assert rehaul["mill_contract_id"] == contract_b["id"]
        assert rehaul["mill_contract_id"] != contract_c["id"]
        assert rehaul["estimated_net_tons"] == pytest.approx(28.32, abs=0.005)

        assert read_mill_contract(contract_b["id"])["reserved_tons"] == pytest.approx(
            28.32, abs=0.005
        )
        assert read_mill_contract(contract_c["id"])["reserved_tons"] == pytest.approx(
            0.00, abs=0.005
        )
