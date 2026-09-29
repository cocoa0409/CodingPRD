"""Clawback is the exact compensating action: every conserved settlement term
returns to its pre-funding value."""
from test_helpers import (
    batch_ledger_entries,
    clawback_batch,
    conserved_settlement_cents,
    create_batch,
    fund_batch,
    read_batch,
    read_custody_account,
    read_partner,
    reconcile_batch,
    setup_live_partner,
)

PRE_FUNDING_CONSERVED_CENTS = 21_250_000


def _funded_batch():
    ctx = setup_live_partner(
        partner_overrides={
            "legal_name": "Marlin Cards Inc",
            "business_model": "CARD_ISSUING",
            "funding_stage": "SERIES_B_PLUS",
            "months_runway": 30,
            "disclosed_complaints_per_10k": 2.00,
            "end_user_account_count": 5000,
        },
        agreement_overrides={
            "reserve_requirement_bps": 500,
            "max_end_user_balance_cents": 500_000_000,
        },
        fbo_balance_cents=20_000_000,
        reserve_balance_cents=1_250_000,
    )
    partner_id = ctx["partner"]["id"]
    before = read_partner(partner_id)
    assert before["cumulative_paid_out_cents"] == 0
    assert before["cumulative_bank_fee_cents"] == 0
    assert before["reserve_shortfall_cents"] == 0
    assert before["oversight_posture"] == "OPEN"
    assert (
        conserved_settlement_cents(before, ctx["fbo"], ctx["reserve"])
        == PRE_FUNDING_CONSERVED_CENTS
    )

    batch = create_batch(
        partner_id,
        window_start="2026-07-01T00:00:00Z",
        window_end="2026-07-15T00:00:00Z",
        gross_settlement_cents=8_000_000,
        interchange_cents=120_000,
        returns_cents=45_000,
        partner_reported_net_cents=8_000_000,
    )
    reconciled = reconcile_batch(batch["id"], 8_000_000)
    assert reconciled["reconciliation_status"] == "MATCHED"
    assert reconciled["variance_cents"] == 0
    ctx["batch"] = fund_batch(batch["id"], funding_reference="WIRE-M-1")
    return ctx


class TestClawbackConservation:
    def test_clawback_returns_all_four_conserved_terms_to_their_pre_funding_values(self):
        """Because clawback restores each of the four conserved terms of §2.11 individually, the
        end-user balance, the reserve balance, the cumulative payout and the cumulative fee all
        return to precisely the values they held before the funding.

        Design: Difficulty/compensating_invariant/clawback_restores_every_conserved_settlement_term_to_its_pre_funding_value
        """
        ctx = _funded_batch()
        partner_id = ctx["partner"]["id"]
        funded = ctx["batch"]
        assert funded["bank_fee_bps_applied"] == 45
        assert funded["bank_fee_cents"] == 61_000
        assert funded["settlement_base_cents"] == 8_075_000
        assert funded["reserve_funding_cents"] == 400_000
        assert funded["net_to_partner_cents"] == 7_614_000

        assert read_custody_account(ctx["fbo"]["id"])["balance_cents"] == 11_925_000
        assert read_custody_account(ctx["reserve"]["id"])["balance_cents"] == 1_589_000
        mid = read_partner(partner_id)
        assert mid["cumulative_paid_out_cents"] == 7_614_000
        assert mid["cumulative_bank_fee_cents"] == 61_000

        reversed_batch = clawback_batch(funded["id"], clawback_reason="DUPLICATE_FUNDING")
        assert reversed_batch["funding_status"] == "CLAWED_BACK"

        fbo = read_custody_account(ctx["fbo"]["id"])
        reserve = read_custody_account(ctx["reserve"]["id"])
        after = read_partner(partner_id)
        assert fbo["balance_cents"] == 20_000_000, "the end-user balance is restored exactly"
        assert reserve["balance_cents"] == 1_250_000, "the reserve balance is restored exactly"
        assert after["cumulative_paid_out_cents"] == 0
        assert after["cumulative_bank_fee_cents"] == 0
        assert (
            conserved_settlement_cents(after, fbo, reserve) == PRE_FUNDING_CONSERVED_CENTS
        ), conserved_settlement_cents(after, fbo, reserve)
        assert after["required_reserve_cents"] == 1_000_000, after["required_reserve_cents"]
        assert after["reserve_shortfall_cents"] == 0
        assert after["oversight_posture"] == "OPEN"

    def test_each_clawback_leg_names_the_funding_leg_it_reverses(self):
        """For every leg the funding wrote, one `CLAWBACK` ledger entry is created whose
        `amount_cents` is the negation of the entry it reverses and whose `reversal_of_entry_id` names
        that entry's id. The batch advances `FUNDED → CLAWED_BACK`, and `funded_at`,
        `bank_fee_cents`, `bank_fee_bps_applied`, `reserve_funding_cents` and `net_to_partner_cents`
        are all left untouched as the historical record of what was paid.

        Design: Difficulty/compensating_invariant/clawback_restores_every_conserved_settlement_term_to_its_pre_funding_value
        """
        ctx = _funded_batch()
        partner_id = ctx["partner"]["id"]
        batch_id = ctx["batch"]["id"]
        funding_legs = {
            entry["id"]: entry for entry in batch_ledger_entries(partner_id, batch_id)
        }
        assert len(funding_legs) == 3, sorted(e["entry_type"] for e in funding_legs.values())

        clawback_batch(batch_id, clawback_reason="DUPLICATE_FUNDING")

        reversals = [
            entry
            for entry in batch_ledger_entries(partner_id, batch_id)
            if entry["entry_type"] == "CLAWBACK"
        ]
        assert len(reversals) == 3, [e["entry_type"] for e in reversals]
        reversed_ids = set()
        for entry in reversals:
            target_id = entry["reversal_of_entry_id"]
            assert target_id in funding_legs, target_id
            assert entry["amount_cents"] == -funding_legs[target_id]["amount_cents"], (
                f"a reversal carries the negation of the entry it reverses, got "
                f"{entry['amount_cents']} against {funding_legs[target_id]['amount_cents']}"
            )
            assert entry["settlement_batch_id"] == batch_id
            reversed_ids.add(target_id)
        assert len(reversed_ids) == 3, "each funding leg is reversed exactly once"

        history = read_batch(batch_id)
        assert history["funding_status"] == "CLAWED_BACK"
        assert history["reconciliation_status"] == "MATCHED", (
            "the reconciliation dimension is untouched by the reversal"
        )
        assert history["net_to_partner_cents"] == 7_614_000
        assert history["bank_fee_cents"] == 61_000
        assert history["bank_fee_bps_applied"] == 45
        assert history["reserve_funding_cents"] == 400_000
        assert history["funded_at"] is not None
