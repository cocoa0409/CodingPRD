"""The reserve floor's three-way maximum, the posture multiplier and the
contractual ceiling; the sponsor-bank fee tier and the shortfall carry."""
from test_helpers import (
    clear_variance,
    create_batch,
    fund_batch,
    read_custody_account,
    read_partner,
    reconcile_batch,
    seed_end_user_balance,
    seed_reserve_balance,
    setup_contracted_partner,
    setup_live_partner,
)


def _kestrel_walk():
    """A contracted partner with a deliberately small contractual ceiling."""
    return setup_contracted_partner(
        partner_overrides={
            "legal_name": "Kestrel PayFac Inc",
            "business_model": "PAYMENT_FACILITATION",
            "funding_stage": "SERIES_A",
            "months_runway": 18,
            "disclosed_complaints_per_10k": 6.00,
            "end_user_account_count": 2000,
        },
        agreement_overrides={
            "max_end_user_balance_cents": 1_000_000,
            "reserve_requirement_bps": 500,
            "concentration_cap_pct": 60.00,
            "monthly_growth_cap_pct": 25.00,
            "termination_triggers": ["RESERVE_SHORTFALL", "VOLUNTARY"],
        },
    )


class TestRequiredReserveWalk:
    def test_each_of_the_three_reserve_floors_wins_in_turn(self):
        """The third is a flat absolute floor of 250,000 cents — two thousand five hundred
        dollars — which applies to every contracted partner no matter how small. The largest of
        the three is taken as the base.

        Design: Difficulty/combinatorial_formula/required_reserve_three_way_max_multiplier_and_ceiling_walk
        """
        ctx = _kestrel_walk()
        partner_id = ctx["partner"]["id"]

        # (a) fbo balance 0 and no trailing volume: only the absolute floor is left standing.
        step_a = read_partner(partner_id)
        assert step_a["required_reserve_cents"] == 250_000, step_a["required_reserve_cents"]
        assert step_a["reserve_shortfall_cents"] == 250_000, step_a["reserve_shortfall_cents"]
        assert step_a["oversight_posture"] == "HEIGHTENED", step_a["oversight_posture"]

        # (b) the end-user balance times the contractual bps now dominates.
        seed_end_user_balance(partner_id, ctx["fbo"], 12_345_679)
        step_b = read_partner(partner_id)
        assert step_b["required_reserve_cents"] == 771_603, (
            f"floor(12345679*500/10000) is 617283, then floor(617283*1.25) is 771603, got "
            f"{step_b['required_reserve_cents']}"
        )
        assert step_b["reserve_shortfall_cents"] == 771_603
        assert step_b["oversight_posture"] == "HEIGHTENED"

        # (e) a trailing settlement window at 150 bps overtakes the end-user branch.
        seed_reserve_balance(partner_id, ctx["reserve"], 771_603)
        seed_end_user_balance(partner_id, ctx["fbo"], 1)
        batch = create_batch(
            partner_id,
            window_start="2026-07-01T00:00:00Z",
            window_end="2026-07-15T00:00:00Z",
            gross_settlement_cents=60_000_000,
            interchange_cents=0,
            returns_cents=0,
            partner_reported_net_cents=60_000_000,
        )
        reconcile_batch(batch["id"], 60_000_000)
        seed_end_user_balance(partner_id, ctx["fbo"], 1)
        step_e = read_partner(partner_id)
        assert step_e["required_reserve_cents"] == 900_000, (
            f"floor(60000000*150/10000) is 900000, above the end-user branch, got "
            f"{step_e['required_reserve_cents']}"
        )
        assert step_e["reserve_shortfall_cents"] == 128_397, step_e["reserve_shortfall_cents"]
        assert step_e["oversight_posture"] == "HEIGHTENED"

    def test_posture_multiplier_floors_before_the_contractual_ceiling_binds(self):
        """The base is then multiplied by a posture multiplier and the product floored to whole
        cents: 1.00 at `OPEN`, 1.25 at `HEIGHTENED`, 1.50 at `RESTRICTED` and 2.00 at `FROZEN`.
        `required_reserve_cents` is the smaller of that scaled figure and the agreement's
        `max_end_user_balance_cents` — the contractual ceiling wins.

        Design: Difficulty/combinatorial_formula/required_reserve_three_way_max_multiplier_and_ceiling_walk
        """
        ctx = _kestrel_walk()
        partner_id = ctx["partner"]["id"]

        seed_end_user_balance(partner_id, ctx["fbo"], 12_345_679)
        seed_reserve_balance(partner_id, ctx["reserve"], 771_603)
        step_c = read_partner(partner_id)
        assert step_c["required_reserve_cents"] == 771_603
        assert step_c["reserve_shortfall_cents"] == 0, "a fully funded reserve reports no shortfall"
        assert step_c["oversight_posture"] == "OPEN", step_c["oversight_posture"]

        # A one-cent credit LOWERS the requirement, because the pass reads the posture
        # as it stood persisted before the pass and the multiplier has dropped to 1.00.
        seed_end_user_balance(partner_id, ctx["fbo"], 1)
        step_d = read_partner(partner_id)
        assert step_d["required_reserve_cents"] == 617_284, (
            f"floor(12345680*500/10000) at multiplier 1.00 is 617284, got "
            f"{step_d['required_reserve_cents']}"
        )
        assert step_d["reserve_shortfall_cents"] == 0
        assert step_d["oversight_posture"] == "OPEN"

        batch = create_batch(
            partner_id,
            window_start="2026-07-01T00:00:00Z",
            window_end="2026-07-15T00:00:00Z",
            gross_settlement_cents=60_000_000,
            interchange_cents=0,
            returns_cents=0,
            partner_reported_net_cents=60_000_000,
        )
        reconcile_batch(batch["id"], 60_000_000)
        seed_end_user_balance(partner_id, ctx["fbo"], 1)
        seed_end_user_balance(partner_id, ctx["fbo"], 1)
        step_f = read_partner(partner_id)
        assert step_f["required_reserve_cents"] == 1_000_000, (
            f"floor(900000*1.25) is 1125000 but the ceiling of 1000000 wins, got "
            f"{step_f['required_reserve_cents']}"
        )
        assert step_f["reserve_shortfall_cents"] == 228_397, step_f["reserve_shortfall_cents"]
        assert step_f["oversight_posture"] == "HEIGHTENED"
        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 12_345_682
        assert read_custody_account(ctx["reserve"]["id"])["balance_cents"] == 771_603


def _halcyon_live():
    return setup_live_partner(
        partner_overrides={
            "legal_name": "Halcyon PayFac Inc",
            "business_model": "PAYMENT_FACILITATION",
            "funding_stage": "SERIES_B_PLUS",
            "months_runway": 36,
            "disclosed_complaints_per_10k": 3.00,
            "end_user_account_count": 8000,
        },
        agreement_overrides={
            "reserve_requirement_bps": 500,
            "max_end_user_balance_cents": 500_000_000,
            "concentration_cap_pct": 60.00,
            "termination_triggers": ["RESERVE_SHORTFALL", "VOLUNTARY"],
        },
        fbo_balance_cents=20_000_000,
        reserve_balance_cents=1_250_000,
    )


class TestBankFeeTierAndShortfallCarry:
    def test_fee_tier_reads_gross_volume_and_not_the_amount_actually_paid_out(self):
        """First, the sponsor-bank fee tier is selected **on gross volume, before any deduction**,
        and the selected rate is flat across the whole gross rather than marginal. From 10,000,000
        cents up to but not including 100,000,000 cents (one million dollars) the rate is 32 basis
        points.

        Design: Difficulty/combinatorial_formula/bank_fee_tier_pinned_to_gross_before_any_deduction_and_shortfall_carry
        """
        ctx = _halcyon_live()
        partner_id = ctx["partner"]["id"]
        batch = create_batch(
            partner_id,
            window_start="2026-07-01T00:00:00Z",
            window_end="2026-07-15T00:00:00Z",
            gross_settlement_cents=10_000_000,
            interchange_cents=0,
            returns_cents=0,
            partner_reported_net_cents=10_000_000,
        )
        reconcile_batch(batch["id"], 10_000_000)
        funded = fund_batch(batch["id"], funding_reference="WIRE-H1")

        assert funded["bank_fee_bps_applied"] == 32, (
            "gross exactly at the tier floor takes 32 bps, not the 45 bps that keying the "
            f"tier on the resulting payout would give, got {funded['bank_fee_bps_applied']}"
        )
        assert funded["bank_fee_cents"] == 57_000, funded["bank_fee_cents"]
        assert funded["settlement_base_cents"] == 10_000_000
        assert funded["reserve_funding_cents"] == 500_000
        assert funded["net_to_partner_cents"] == 9_443_000, (
            f"keying the tier on the payout would have produced 9430000, got "
            f"{funded['net_to_partner_cents']}"
        )
        assert funded["shortfall_carry_cents"] == 0
        assert read_partner(partner_id)["cumulative_bank_fee_cents"] == 57_000

    def test_a_base_fee_larger_than_the_settlement_base_floors_the_payout_and_carries_the_residue(self):
        """Second, `bank_fee_cents` is a flat base fee of 25,000 cents — two hundred and fifty
        dollars per batch — plus `gross_settlement_cents` multiplied by `bank_fee_bps_applied`,
        divided by 10000 and floored to whole cents. Sixth, `shortfall_carry_cents` captures the
        magnitude the reserve must absorb when the fees and reserve routing outran the base: it is
        the amount by which the raw payout fell below zero, expressed as a positive number.

        Design: Difficulty/combinatorial_formula/bank_fee_tier_pinned_to_gross_before_any_deduction_and_shortfall_carry
        """
        ctx = _halcyon_live()
        partner_id = ctx["partner"]["id"]
        first = create_batch(
            partner_id,
            window_start="2026-07-01T00:00:00Z",
            window_end="2026-07-15T00:00:00Z",
            gross_settlement_cents=10_000_000,
            interchange_cents=0,
            returns_cents=0,
            partner_reported_net_cents=10_000_000,
        )
        reconcile_batch(first["id"], 10_000_000)
        fund_batch(first["id"], funding_reference="WIRE-H1")

        tiny = create_batch(
            partner_id,
            window_start="2026-07-15T00:00:00Z",
            window_end="2026-07-29T00:00:00Z",
            gross_settlement_cents=20_000,
            interchange_cents=0,
            returns_cents=0,
            partner_reported_net_cents=20_000,
        )
        reconcile_batch(tiny["id"], 20_000)
        funded = fund_batch(tiny["id"], funding_reference="WIRE-H2")

        assert funded["bank_fee_bps_applied"] == 45, funded["bank_fee_bps_applied"]
        assert funded["bank_fee_cents"] == 25_090, (
            f"floor(20000*45/10000) is 90 and the 25000 base fee is added after, got "
            f"{funded['bank_fee_cents']}"
        )
        assert funded["settlement_base_cents"] == 20_000
        assert funded["reserve_funding_cents"] == 1_000
        assert funded["net_to_partner_cents"] == 0, "the payout is floored at zero"
        assert funded["shortfall_carry_cents"] == 6_090, funded["shortfall_carry_cents"]
        assert funded["funding_status"] == "FUNDED"

        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 9_980_000
        assert read_custody_account(ctx["reserve"]["id"])["balance_cents"] == 1_675_000
        partner = read_partner(partner_id)
        assert partner["cumulative_paid_out_cents"] == 9_443_000
        assert partner["cumulative_bank_fee_cents"] == 82_090
        assert partner["required_reserve_cents"] == 499_000
        assert partner["reserve_shortfall_cents"] == 0
        assert partner["oversight_posture"] == "OPEN"


def _vector_live():
    return setup_live_partner(
        partner_overrides={
            "legal_name": "Vector Cards Inc",
            "business_model": "CARD_ISSUING",
            "funding_stage": "SERIES_B_PLUS",
            "months_runway": 30,
            "disclosed_complaints_per_10k": 4.00,
            "end_user_account_count": 5000,
        },
        agreement_overrides={
            "kyc_owner": "BANK",
            "dispute_owner": "BANK",
            "marketing_owner": "PARTNER",
            "oversight_rights_level": "FULL_ACCESS",
            "audit_access_notice_days": 5,
            "termination_triggers": ["RESERVE_SHORTFALL", "VOLUNTARY"],
            "concentration_cap_pct": 60.00,
            "reserve_requirement_bps": 500,
            "max_end_user_balance_cents": 500_000_000,
        },
        fbo_balance_cents=20_000_000,
        reserve_balance_cents=1_250_000,
    )


def _open_window(partner_id, window_start, window_end):
    return create_batch(
        partner_id,
        window_start=window_start,
        window_end=window_end,
        gross_settlement_cents=8_000_000,
        interchange_cents=120_000,
        returns_cents=45_000,
        partner_reported_net_cents=8_000_000,
    )


class TestReserveFundingBasis:
    def test_a_matched_batch_routes_reserve_off_gross_and_ignores_interchange_and_returns(self):
        """For a batch that is `MATCHED`, the basis is `gross_settlement_cents` alone, ignoring
        interchange, returns and adjustments: the reserve funding is that gross multiplied by
        `reserve_requirement_bps`, divided by 10000 and floored to whole cents.

        Design: Difficulty/dual_variant_calc/settlement_reserve_basis_gross_versus_net_variant
        """
        ctx = _vector_live()
        partner_id = ctx["partner"]["id"]
        batch = _open_window(partner_id, "2026-07-01T00:00:00Z", "2026-07-15T00:00:00Z")
        reconciled = reconcile_batch(batch["id"], 8_000_000)
        assert reconciled["reconciliation_status"] == "MATCHED"
        funded = fund_batch(batch["id"], funding_reference="WIRE-A-0001")

        assert funded["bank_fee_bps_applied"] == 45
        assert funded["bank_fee_cents"] == 61_000
        assert funded["settlement_base_cents"] == 8_075_000
        assert funded["reserve_funding_cents"] == 400_000, (
            f"floor(8000000*500/10000) off gross alone, not off the base of 8075000, got "
            f"{funded['reserve_funding_cents']}"
        )
        assert funded["net_to_partner_cents"] == 7_614_000, funded["net_to_partner_cents"]
        assert funded["shortfall_carry_cents"] == 0

    def test_a_cleared_variance_moves_the_reserve_basis_onto_the_settlement_base(self):
        """For a batch that is `VARIANCE_CLEARED`, the basis is `settlement_base_cents` instead,
        multiplied by the same `reserve_requirement_bps`, divided by 10000 and floored to whole
        cents. The consequence is that two batches with identical gross, interchange and returns
        figures produce a different `reserve_funding_cents` and a different `net_to_partner_cents`
        purely because one of them passed through a cleared variance.

        Design: Difficulty/dual_variant_calc/settlement_reserve_basis_gross_versus_net_variant
        """
        ctx = _vector_live()
        partner_id = ctx["partner"]["id"]

        matched = _open_window(partner_id, "2026-07-01T00:00:00Z", "2026-07-15T00:00:00Z")
        reconcile_batch(matched["id"], 8_000_000)

        cleared = _open_window(partner_id, "2026-07-15T00:00:00Z", "2026-07-29T00:00:00Z")
        opened = reconcile_batch(cleared["id"], 8_030_000)
        assert opened["reconciliation_status"] == "VARIANCE_OPEN"
        settled = clear_variance(
            cleared["id"], 30_000, root_cause_note="late interchange posting"
        )
        assert settled["reconciliation_status"] == "VARIANCE_CLEARED"

        funded_matched = fund_batch(matched["id"], funding_reference="WIRE-A-0001")
        funded_cleared = fund_batch(cleared["id"], funding_reference="WIRE-B-0002")

        assert funded_cleared["bank_fee_bps_applied"] == 45
        assert funded_cleared["bank_fee_cents"] == 61_000, "the fee is untouched by the correction"
        assert funded_cleared["settlement_base_cents"] == 8_105_000
        assert funded_cleared["reserve_funding_cents"] == 405_250, (
            f"floor(8105000*500/10000) off the corrected base, got "
            f"{funded_cleared['reserve_funding_cents']}"
        )
        assert funded_cleared["net_to_partner_cents"] == 7_638_750
        assert (
            funded_cleared["reserve_funding_cents"] - funded_matched["reserve_funding_cents"]
            == 5_250
        ), "identical gross, interchange and returns still route different reserve amounts"

        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 3_820_000
        assert read_custody_account(ctx["reserve"]["id"])["balance_cents"] == 1_933_250
        partner = read_partner(partner_id)
        assert partner["cumulative_paid_out_cents"] == 15_252_750
        assert partner["cumulative_bank_fee_cents"] == 122_000
        assert partner["required_reserve_cents"] == 250_000
        assert partner["reserve_shortfall_cents"] == 0
        assert partner["unreconciled_variance_cents"] == 0
        assert partner["oversight_posture"] == "OPEN"
