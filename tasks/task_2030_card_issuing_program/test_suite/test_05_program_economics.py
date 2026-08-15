"""Program monthly economics: provisional vs final variants (difficulty:
dual_variant_calc on the program domain), and the three-input qualification
tier nonlinearity (difficulty: combinatorial_formula)."""
from test_helpers import (
    TEST_USERS,
    assert_program_economics,
    create_approved_auth,
    create_in_production_batch,
    create_vendor,
    get_success_data,
    set_clock,
    setup_active_card_scenario,
    validate_success,
)

FC = TEST_USERS["finance_controller_headers"]


class TestProgramEconomicsDualVariant:
    def test_economics_provisional_includes_in_flight_batch_accrual(self, api):
        """PRD §3.6: "the `PROVISIONAL` variant — the default when the requested
        month is the current month — counts settlements only up to the clock and
        adds a forward-looking accrual for batches still `SUBMITTED` or
        `IN_PRODUCTION`, valued at requested count multiplied by unit cost".

        Design: Difficulty/dual_variant_calc/program_economics_provisional_vs_final_on_program_domain
        """
        from test_helpers import create_program_with_bin_and_publish
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish(
            "P-MC-2", product_class="CONSUMER_PREPAID", network="MASTERCARD",
            daily_spend_cap_cents=5_000_000, bin_prefix="511111",
        )
        vendor = create_vendor(
            "VEND-A", capability_flags=["EMV_CHIP"], daily_capacity_cards=5000,
            supported_networks=["MASTERCARD"],
        )
        create_in_production_batch(
            prog["id"], vendor["id"],
            scheduled_for_utc_date="2026-08-15",
            requested_card_count=1000,
            unit_cost_cents=200,
        )
        resp = api.get_program_economics(prog["id"], "2026-08", FC, variant="PROVISIONAL")
        econ = validate_success(resp)
        assert_program_economics(econ)
        assert econ["production_cost_cents"] == 200000, (
            f"PROVISIONAL must accrue requested*unit_cost = 1000*200 = 200000 for the "
            f"IN_PRODUCTION batch, got {econ['production_cost_cents']}"
        )

    def test_economics_final_excludes_in_flight_batch(self, api):
        """PRD §3.6: "the `FINAL` variant — the default when the requested month
        is before the current month — counts only shipped-or-delivered batches
        at fulfilled counts and campaigns completed in-window".

        Design: Difficulty/dual_variant_calc/program_economics_provisional_vs_final_on_program_domain
        """
        from test_helpers import create_program_with_bin_and_publish
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish(
            "P-MC-2B", product_class="CONSUMER_PREPAID", network="MASTERCARD",
            daily_spend_cap_cents=5_000_000, bin_prefix="511112",
        )
        vendor = create_vendor(
            "VEND-B", capability_flags=["EMV_CHIP"], daily_capacity_cards=5000,
            supported_networks=["MASTERCARD"],
        )
        create_in_production_batch(
            prog["id"], vendor["id"],
            scheduled_for_utc_date="2026-08-15",
            requested_card_count=1000,
            unit_cost_cents=200,
        )
        resp = api.get_program_economics(prog["id"], "2026-08", FC, variant="FINAL")
        econ = validate_success(resp)
        assert_program_economics(econ)
        assert econ["production_cost_cents"] == 0, (
            f"FINAL must exclude the IN_PRODUCTION batch (fulfilled-only), got "
            f"{econ['production_cost_cents']}"
        )


class TestQualificationTierNonlinearity:
    def test_blocked_mcc_overrides_timing_and_chip(self, api):
        """PRD §3.6: "If the settlement's `mcc` appears on the network's blocked
        list — `7995` and `6012` for `VISA`, `7995` alone for `MASTERCARD`, and
        empty lists for `STAR` and `PULSE` — the tier is `NON_QUALIFIED`."

        The blocked-mcc clause fires first regardless of timing or chip
        capability: here elapsed=100s (within 24h) and the card is EMV-capable,
        yet the tier must be NON_QUALIFIED.

        Design: Difficulty/combinatorial_formula/qualification_tier_three_input_nonlinear
        """
        sc = setup_active_card_scenario(
            "P-VISA-3",
            product_class="DEBIT_CONSUMER",
            network="VISA",
            program_daily_cap_cents=10_000_000,
            account_daily_cap_cents=1_000_000,
            fund_cents=1_000_000,
            bin_prefix="422222",
        )
        auth = create_approved_auth(sc["card"]["id"], amount_cents=10000, mcc="7995")
        set_clock("2026-08-01T00:01:40Z")  # +100s — well within 24h
        resp = api.settle_authorization(auth["id"], 10000, FC)
        settlement = validate_success(resp, expected_status=201)
        assert settlement["qualification_tier"] == "NON_QUALIFIED", (
            f"Blocked mcc must override fast settlement and EMV capability; got "
            f"{settlement['qualification_tier']}"
        )

    def test_elapsed_over_48h_yields_non_qualified(self, api):
        """PRD §3.6: "Otherwise, if the gap between `authorized_at` and
        `settled_at` exceeds 172,800 seconds (48 hours), the tier is
        `NON_QUALIFIED`; the boundary is exclusive, so a gap of exactly 172,800
        seconds falls through to the next test."

        Design: Difficulty/combinatorial_formula/qualification_tier_three_input_nonlinear
        """
        sc = setup_active_card_scenario(
            "P-VISA-3C",
            product_class="DEBIT_CONSUMER",
            network="VISA",
            program_daily_cap_cents=10_000_000,
            account_daily_cap_cents=1_000_000,
            fund_cents=1_000_000,
            bin_prefix="422224",
        )
        # Auth at a pinned instant, then settle 200000s later (> 172800).
        set_clock("2026-08-10T00:00:00Z")
        auth = create_approved_auth(sc["card"]["id"], amount_cents=10000, mcc="5411")
        set_clock("2026-08-12T07:33:20Z")  # +200000s
        resp = api.settle_authorization(auth["id"], 10000, FC)
        settlement = validate_success(resp, expected_status=201)
        assert settlement["qualification_tier"] == "NON_QUALIFIED", (
            f"Elapsed 200000s > 172800s must yield NON_QUALIFIED, got "
            f"{settlement['qualification_tier']}"
        )

    def test_elapsed_between_24h_and_48h_with_chip_yields_mid_qualified(self, api):
        """PRD §3.6: "Otherwise, when the gap is at most 86,400 seconds (24
        hours, inclusive) and the card is EMV capable, the tier is `QUALIFIED`.
        Every remaining case is `MID_QUALIFIED`."

        Design: Difficulty/combinatorial_formula/qualification_tier_three_input_nonlinear
        """
        sc = setup_active_card_scenario(
            "P-VISA-3D",
            product_class="DEBIT_CONSUMER",
            network="VISA",
            program_daily_cap_cents=10_000_000,
            account_daily_cap_cents=1_000_000,
            fund_cents=1_000_000,
            bin_prefix="422225",
        )
        set_clock("2026-08-10T00:00:00Z")
        auth = create_approved_auth(sc["card"]["id"], amount_cents=10000, mcc="5411")
        # +100000s: >86400, <=172800 → falls through to MID_QUALIFIED.
        set_clock("2026-08-11T03:46:40Z")
        resp = api.settle_authorization(auth["id"], 10000, FC)
        settlement = validate_success(resp, expected_status=201)
        assert settlement["qualification_tier"] == "MID_QUALIFIED", (
            f"Elapsed 100000s with EMV-capable card must be MID_QUALIFIED, got "
            f"{settlement['qualification_tier']}"
        )
