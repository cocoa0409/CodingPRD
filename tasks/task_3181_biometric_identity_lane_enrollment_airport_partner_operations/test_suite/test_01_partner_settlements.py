"""Partner settlements: airport fee vs venue payout variants, evaluation order,
provisional-vs-finalized freeze, and settlement lifecycle."""
from test_helpers import (
    ApiErrorId,
    create_active_agreement,
    create_agreement,
    create_agreement_settlement,
    create_airport,
    create_venue,
    create_venue_payout_settlement,
    set_clock,
    setup_airport_with_active_agreement,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OPS, PM, VENUE


class TestAirportVsVenueVariantDiverge:
    def test_airport_formula_applies_minimum_after_two_rounded_shares(self, api):
        """PRD §3.9: "First the subscription share: `attributable_mrr_cents` multiplied by the
        agreement's `subscription_share_rate`, rounded half up to two decimal places.
        Second the revenue share: `verification_revenue_cents` multiplied by the
        agreement's `rev_share_rate`, likewise rounded half up to two decimal places.
        Third, the variable fee is the sum of the two rounded shares. Fourth and
        last, the monthly minimum guarantee applies: `fee_cents` is the greater of
        the agreement's `monthly_minimum_cents` and the variable fee."

        With subscription_share_rate 0.02 on MRR 450000 -> 9000 and rev_share_rate
        0.12 on REV 1000000 -> 120000, the variable fee 129000 beats the 25000 floor.

        Design: Difficulty/dual_variant_calc/settlement_fee_airport_formula_vs_venue_formula_diverge
        """
        airport, agreement = setup_airport_with_active_agreement(
            "DFW", rev_share_rate=0.12, subscription_share_rate=0.02,
            monthly_minimum_cents=25000, federal_integration=True,
        )
        settlement = create_agreement_settlement(
            agreement,
            period_start="2026-09-01", period_end="2026-10-01",
            attributable_mrr_cents=450000, verification_revenue_cents=1000000,
        )
        assert settlement["calculation_variant"] == "AIRPORT"
        assert settlement["fee_cents"] == 129000, (
            f"variable fee max(25000, 9000 + 120000) = 129000, got {settlement['fee_cents']}"
        )

    def test_venue_variant_differs_from_airport_on_identical_revenue(self, api):
        """PRD §3.9: "Settlements reconcile what a partner is owed for a period, and come in
        two variants that deliberately produce different fees for identical period
        revenue inputs."
        PRD §3.9: "The venue variant is created by a `VenueOps` operator against a
        venue — its `venue_id` is set while `agreement_id` stays unset" and "The
        settlement records `calculation_variant` of `VENUE`."

        Design: Difficulty/dual_variant_calc/settlement_fee_airport_formula_vs_venue_formula_diverge
        """
        airport, agreement = setup_airport_with_active_agreement(
            "DFW", rev_share_rate=0.12, subscription_share_rate=0.02,
            monthly_minimum_cents=25000, federal_integration=True,
        )
        venue = create_venue(
            name="Stadium A", venue_type="STADIUM", city="Dallas", state_code="TX",
            access_rule_mode="AGE_18_PLUS",
        )
        air = create_agreement_settlement(
            agreement,
            period_start="2026-09-01", period_end="2026-10-01",
            attributable_mrr_cents=450000, verification_revenue_cents=1000000,
        )
        ven = create_venue_payout_settlement(
            venue,
            period_start="2026-09-01", period_end="2026-10-01",
            verification_revenue_cents=1000000, events_count=3,
            venue_capacity_seats=8000,
        )
        assert air["calculation_variant"] == "AIRPORT"
        assert ven["calculation_variant"] == "VENUE"
        assert ven.get("venue_id") == venue["id"]
        assert air["fee_cents"] != ven["fee_cents"], (
            "identical verification revenue must price differently across variants"
        )


class TestDraftProvisionalVsFinalizedFrozen:
    def test_draft_fee_at_minimum_floor_then_finalize_freezes(self, api):
        """PRD §3.9: "While a settlement is in `DRAFT`, its `fee_cents` recomputes from
        current inputs on every read. A `PartnerManager` finalizes a draft — moving
        it to `FINALIZED` — once its `period_end` is on or before the current
        logical date — finalizing a period that has not ended fails with
        `ERR_PERIOD_NOT_ENDED` — and finalization freezes `fee_cents` at its
        computed value; later corrections to the inputs require a new settlement."

        With subscription_share 0.02 on MRR 10000 -> 200 and rev share 0, the
        30000 minimum wins and stays frozen after finalize.

        Design: Difficulty/dual_variant_calc/settlement_draft_provisional_recomputes_vs_finalized_frozen
        """
        airport, agreement = setup_airport_with_active_agreement(
            "PDX", rev_share_rate=0.12, subscription_share_rate=0.02,
            monthly_minimum_cents=30000, federal_integration=False,
        )
        settlement = create_agreement_settlement(
            agreement,
            period_start="2026-09-01", period_end="2026-10-01",
            attributable_mrr_cents=10000, verification_revenue_cents=0,
        )
        assert settlement["fee_cents"] == 30000, (
            f"floor 30000 beats variable 200, got {settlement['fee_cents']}"
        )
        assert settlement["status"] == "DRAFT"
        set_clock("2026-10-02T00:00:00Z")
        finalized = validate_success(api.finalize_settlement(settlement["id"], PM))
        assert finalized["status"] == "FINALIZED"
        assert finalized["fee_cents"] == 30000, "finalize freezes fee_cents"

    def test_finalize_then_mark_paid_and_terminal_lockdown(self, api):
        """PRD §3.9: "A `FINALIZED` settlement is then marked paid, reaching the terminal
        `PAID` state."
        PRD §2.8: "then state legality (`ERR_INVALID_STATE`)" — a second finalize on a
        PAID settlement has no such transition.

        Design: Difficulty/dual_variant_calc/settlement_draft_provisional_recomputes_vs_finalized_frozen
        """
        airport, agreement = setup_airport_with_active_agreement(
            "PDX", rev_share_rate=0.12, subscription_share_rate=0.02,
            monthly_minimum_cents=30000, federal_integration=False,
        )
        settlement = create_agreement_settlement(
            agreement,
            period_start="2026-09-01", period_end="2026-10-01",
            attributable_mrr_cents=10000, verification_revenue_cents=0,
        )
        set_clock("2026-10-02T00:00:00Z")
        finalized = validate_success(api.finalize_settlement(settlement["id"], PM))
        assert finalized["status"] == "FINALIZED"
        paid = validate_success(api.mark_settlement_paid(settlement["id"], PM))
        assert paid["status"] == "PAID"
        resp = api.finalize_settlement(settlement["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEvaluationOrderAcrossAgreements:
    def test_variable_wins_over_floor_for_bwi(self, api):
        """PRD §3.9: "First the subscription share: `attributable_mrr_cents` multiplied by the
        agreement's `subscription_share_rate`, rounded half up to two decimal places.
        Second the revenue share: `verification_revenue_cents` multiplied by the
        agreement's `rev_share_rate`, likewise rounded half up to two decimal places.
        Third, the variable fee is the sum of the two rounded shares. Fourth and
        last, the monthly minimum guarantee applies: `fee_cents` is the greater of
        the agreement's `monthly_minimum_cents` and the variable fee."

        BWI: variable 9000 + 120000 = 129000 beats floor 25000.

        Design: Difficulty/combinatorial_formula/airport_fee_minimum_applied_after_two_rounded_shares
        """
        airport, agreement = setup_airport_with_active_agreement(
            "BWI", rev_share_rate=0.12, subscription_share_rate=0.02,
            monthly_minimum_cents=25000, federal_integration=False,
        )
        settlement = create_agreement_settlement(
            agreement,
            period_start="2026-09-01", period_end="2026-10-01",
            attributable_mrr_cents=450000, verification_revenue_cents=1000000,
        )
        assert settlement["fee_cents"] == 129000

    def test_floor_wins_over_variable_for_dca(self, api):
        """PRD §3.9: "Fourth and last, the monthly minimum guarantee applies: `fee_cents` is
        the greater of the agreement's `monthly_minimum_cents` and the variable fee.
        Rounding each share before taking the maximum is required; rounding after the
        maximum is a forbidden variant."

        DCA: variable 200 + 120000 = 120200 beats floor 30000; a small-MRR twin
        (subscription share 200, revenue share 0) floors at 30000 — both read
        against the same formula proves the max is applied last.

        Design: Difficulty/combinatorial_formula/airport_fee_minimum_applied_after_two_rounded_shares
        """
        airport, agreement = setup_airport_with_active_agreement(
            "DCA", rev_share_rate=0.12, subscription_share_rate=0.02,
            monthly_minimum_cents=30000, federal_integration=False,
        )
        big_rev = create_agreement_settlement(
            agreement,
            period_start="2026-09-01", period_end="2026-10-01",
            attributable_mrr_cents=10000, verification_revenue_cents=1000000,
        )
        assert big_rev["fee_cents"] == 120200, (
            f"variable 200 + 120000 = 120200 beats floor 30000, got {big_rev['fee_cents']}"
        )
        small_rev = create_agreement_settlement(
            agreement,
            period_start="2026-10-01", period_end="2026-11-01",
            attributable_mrr_cents=10000, verification_revenue_cents=0,
        )
        assert small_rev["fee_cents"] == 30000, (
            f"variable 200 + 0 = 200 loses to floor 30000, got {small_rev['fee_cents']}"
        )


class TestSettlementInitialState:
    def test_settlement_born_draft_and_cannot_skip_to_paid(self, api):
        """PRD §3.9: "Both variants are born `DRAFT`." and "A `FINALIZED` settlement is then
        marked paid, reaching the terminal `PAID` state."
        PRD §2.8: "then state legality (`ERR_INVALID_STATE`)" — DRAFT has no mark-paid
        transition.

        Design: Corner/state_machines/settlement_initial_state_draft
        """
        airport, agreement = setup_airport_with_active_agreement(
            "OKC", rev_share_rate=0.10, subscription_share_rate=0.02,
            monthly_minimum_cents=10000, federal_integration=False,
        )
        settlement = create_agreement_settlement(
            agreement,
            period_start="2026-09-01", period_end="2026-10-01",
            attributable_mrr_cents=500000, verification_revenue_cents=500000,
        )
        assert settlement["status"] == "DRAFT"
        resp = api.mark_settlement_paid(settlement["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
