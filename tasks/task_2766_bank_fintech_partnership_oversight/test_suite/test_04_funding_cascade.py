"""Funding a batch drains custody, which moves the reserve floor onto another
branch, which opens a shortfall, which escalates posture and stops the next wire."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_batch,
    fund_batch,
    read_batch,
    read_custody_account,
    read_partner,
    reconcile_batch,
    seed_end_user_balance,
    setup_live_partner,
    validate_error,
)
from test_helpers.fixtures import PO


def _halyard_live():
    """reserve_requirement_bps is deliberately tiny so the end-user branch of the
    reserve floor is not the binding term at funding time."""
    return setup_live_partner(
        partner_overrides={
            "legal_name": "Halyard Pay LLC",
            "business_model": "PAYMENT_FACILITATION",
            "funding_stage": "SERIES_B_PLUS",
            "months_runway": 30,
            "disclosed_complaints_per_10k": 1.00,
            "end_user_account_count": 5000,
        },
        agreement_overrides={
            "reserve_requirement_bps": 10,
            "max_end_user_balance_cents": 500_000_000,
            "monthly_growth_cap_pct": 50.00,
            "concentration_cap_pct": 90.00,
            "termination_triggers": ["RESERVE_SHORTFALL"],
        },
        fbo_balance_cents=20_000_000,
        reserve_balance_cents=312_500,
    )


def _two_matched_batches(partner_id):
    first = create_batch(
        partner_id,
        window_start="2026-07-01T00:00:00Z",
        window_end="2026-07-15T00:00:00Z",
        gross_settlement_cents=20_000_000,
        interchange_cents=0,
        returns_cents=0,
        partner_reported_net_cents=20_000_000,
    )
    reconcile_batch(first["id"], 20_000_000)
    second = create_batch(
        partner_id,
        window_start="2026-07-15T00:00:00Z",
        window_end="2026-07-29T00:00:00Z",
        gross_settlement_cents=1_000_000,
        interchange_cents=0,
        returns_cents=0,
        partner_reported_net_cents=1_000_000,
    )
    reconcile_batch(second["id"], 1_000_000)
    return first, second


class TestFundingCascade:
    def test_draining_custody_moves_the_reserve_floor_onto_the_trailing_volume_branch(self):
        """The second is the partner's trailing settlement volume multiplied by 150 basis points,
        divided by 10000 and floored to whole cents. The changed balances recompute the partner's
        `required_reserve_cents`, `reserve_shortfall_cents` and `concentration_ratio_pct`; the
        recomputed shortfall re-derives `oversight_posture`.

        Design: Difficulty/transitive_cascade/fund_cascade_flips_reserve_basis_then_posture_then_blocks_the_next_funding
        """
        ctx = _halyard_live()
        partner_id = ctx["partner"]["id"]
        before = read_partner(partner_id)
        assert before["reserve_shortfall_cents"] == 0
        assert before["oversight_posture"] == "OPEN"

        first, _second = _two_matched_batches(partner_id)
        funded = fund_batch(first["id"], funding_reference="WIRE-H-A")
        assert funded["bank_fee_bps_applied"] == 32
        assert funded["bank_fee_cents"] == 89_000
        assert funded["settlement_base_cents"] == 20_000_000
        assert funded["reserve_funding_cents"] == 20_000
        assert funded["net_to_partner_cents"] == 19_891_000

        fbo = read_custody_account(ctx["fbo"]["id"])
        assert fbo["balance_cents"] == 0, "the debit leg carries the whole settlement base"
        assert fbo["status"] == "ACTIVE", "an escalation to HEIGHTENED does not freeze custody"
        assert read_custody_account(ctx["reserve"]["id"])["balance_cents"] == 243_500

        after = read_partner(partner_id)
        assert after["required_reserve_cents"] == 315_000, (
            "the end-user branch collapsed to zero so the trailing-volume branch now binds: both "
            "batches are MATCHED and both windows end inside the trailing ninety days, so "
            f"floor(21000000*150/10000) is the floor, got {after['required_reserve_cents']}"
        )
        assert after["reserve_shortfall_cents"] == 71_500, after["reserve_shortfall_cents"]
        assert after["oversight_posture"] == "HEIGHTENED"
        assert after["cumulative_paid_out_cents"] == 19_891_000
        assert after["cumulative_bank_fee_cents"] == 89_000

    def test_the_shortfall_the_first_wire_opened_refuses_the_second_wire(self):
        """And the partner's `reserve_shortfall_cents` must be exactly 0 — a partner short of
        reserve does not get paid, and the refusal is `ERR_RESERVE_SHORTFALL_BLOCKS_FUNDING`, which
        is the one condition in this system reported as HTTP 402.

        Design: Difficulty/transitive_cascade/fund_cascade_flips_reserve_basis_then_posture_then_blocks_the_next_funding
        """
        ctx = _halyard_live()
        partner_id = ctx["partner"]["id"]
        first, second = _two_matched_batches(partner_id)
        fund_batch(first["id"], funding_reference="WIRE-H-A")
        assert read_partner(partner_id)["reserve_shortfall_cents"] == 71_500

        # The first wire drained the end-user account, and no-negative-custody outranks reserve
        # adequacy, so the end-user side is topped up to exactly the second batch's base first.
        # That leaves the reserve shortfall as the only remaining reason to refuse the wire.
        seed_end_user_balance(partner_id, ctx["fbo"], 1_000_000)
        topped_up = read_partner(partner_id)
        assert topped_up["reserve_shortfall_cents"] > 0, topped_up["reserve_shortfall_cents"]
        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 1_000_000

        response = api_client.fund_settlement_batch(
            second["id"], {"funding_reference": "WIRE-H-B"}, PO
        )
        validate_error(response, ApiErrorId.ERR_RESERVE_SHORTFALL_BLOCKS_FUNDING, 402)

        unpaid = read_batch(second["id"])
        assert unpaid["funding_status"] == "UNFUNDED"
        assert unpaid["reconciliation_status"] == "MATCHED", (
            "the refusal touched only the funding dimension"
        )
        assert unpaid["net_to_partner_cents"] == 0
        assert read_partner(partner_id)["cumulative_paid_out_cents"] == 19_891_000
