"""Reconciliation and funding are two unrelated dimensions on one settlement row."""
from test_helpers import (
    clawback_batch,
    clear_variance,
    create_batch,
    fund_batch,
    read_batch,
    read_custody_account,
    read_partner,
    reconcile_batch,
    setup_live_partner,
)


def _sable_live():
    return setup_live_partner(
        partner_overrides={
            "legal_name": "Sable Cards Inc",
            "business_model": "CARD_ISSUING",
            "funding_stage": "SERIES_B_PLUS",
            "months_runway": 30,
            "disclosed_complaints_per_10k": 3.00,
            "end_user_account_count": 6000,
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


class TestIndependentDimensions:
    def test_funding_dimension_walks_twice_while_reconciliation_stays_matched(self):
        """The `funding_status` dimension advances `UNFUNDED → FUNDED` and then `FUNDED →
        CLAWED_BACK`. Neither dimension constrains the other except for exactly one gate: funding
        requires the reconciliation dimension to have left `UNRECONCILED`.

        Design: Difficulty/non_linear_state_machine/settlement_batch_two_dimensions_advance_independently_on_one_row
        """
        ctx = _sable_live()
        partner_id = ctx["partner"]["id"]
        created = create_batch(
            partner_id,
            window_start="2026-07-01T00:00:00Z",
            window_end="2026-07-15T00:00:00Z",
            gross_settlement_cents=8_000_000,
            interchange_cents=120_000,
            returns_cents=45_000,
            partner_reported_net_cents=8_000_000,
        )
        assert created["reconciliation_status"] == "UNRECONCILED"
        assert created["funding_status"] == "UNFUNDED"

        matched = reconcile_batch(created["id"], 8_000_000)
        assert matched["reconciliation_status"] == "MATCHED"
        assert matched["funding_status"] == "UNFUNDED"

        funded = fund_batch(created["id"], funding_reference="WIRE-S-A")
        assert funded["reconciliation_status"] == "MATCHED"
        assert funded["funding_status"] == "FUNDED"
        assert funded["net_to_partner_cents"] == 7_614_000

        reversed_batch = clawback_batch(created["id"], clawback_reason="DUPLICATE_FUNDING")
        assert reversed_batch["funding_status"] == "CLAWED_BACK"
        assert reversed_batch["reconciliation_status"] == "MATCHED", (
            "two funding-dimension moves must leave the reconciliation dimension where it was"
        )
        assert reversed_batch["variance_cents"] == 0

        final = read_batch(created["id"])
        assert final["net_to_partner_cents"] == 7_614_000, (
            "the payout figure is retained as the historical record of what was paid"
        )
        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 20_000_000
        assert read_custody_account(ctx["reserve"]["id"])["balance_cents"] == 1_250_000
        assert read_partner(partner_id)["cumulative_paid_out_cents"] == 0

    def test_reconciliation_dimension_walks_twice_while_funding_stays_unfunded(self):
        """The `reconciliation_status` dimension advances `UNRECONCILED → MATCHED` or
        `UNRECONCILED → VARIANCE_OPEN`, and then `VARIANCE_OPEN → VARIANCE_CLEARED`.

        Design: Difficulty/non_linear_state_machine/settlement_batch_two_dimensions_advance_independently_on_one_row
        """
        ctx = _sable_live()
        partner_id = ctx["partner"]["id"]
        created = create_batch(
            partner_id,
            window_start="2026-07-15T00:00:00Z",
            window_end="2026-07-29T00:00:00Z",
            gross_settlement_cents=4_000_000,
            interchange_cents=0,
            returns_cents=0,
            partner_reported_net_cents=4_000_000,
        )
        opened = reconcile_batch(created["id"], 4_010_000)
        assert opened["reconciliation_status"] == "VARIANCE_OPEN"
        assert opened["funding_status"] == "UNFUNDED"
        assert opened["variance_cents"] == 10_000

        cleared = clear_variance(created["id"], 10_000, root_cause_note="unbooked interchange")
        assert cleared["reconciliation_status"] == "VARIANCE_CLEARED"
        assert cleared["funding_status"] == "UNFUNDED", (
            "two reconciliation-dimension moves must leave the funding dimension where it was"
        )
        assert cleared["variance_adjustment_cents"] == 10_000
        assert cleared["settlement_base_cents"] == 4_010_000

        funded = fund_batch(created["id"], funding_reference="WIRE-S-B")
        assert funded["reconciliation_status"] == "VARIANCE_CLEARED"
        assert funded["funding_status"] == "FUNDED"
        assert funded["bank_fee_bps_applied"] == 45
        assert funded["bank_fee_cents"] == 43_000
        assert funded["reserve_funding_cents"] == 200_500
        assert funded["net_to_partner_cents"] == 3_766_500

        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 15_990_000
        assert read_custody_account(ctx["reserve"]["id"])["balance_cents"] == 1_407_500
        partner = read_partner(partner_id)
        assert partner["cumulative_paid_out_cents"] == 3_766_500
        assert partner["cumulative_bank_fee_cents"] == 43_000
        assert partner["unreconciled_variance_cents"] == 0
        assert partner["required_reserve_cents"] == 799_500
        assert partner["reserve_shortfall_cents"] == 0
