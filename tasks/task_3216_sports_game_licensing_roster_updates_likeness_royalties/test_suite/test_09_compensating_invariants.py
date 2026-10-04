"""Difficulty queue A, rule 9: compensating_invariant — both instances."""
from test_helpers import (
    FINANCE,
    assert_wallet_invariants,
    create_active_agreement,
    create_eligible_athlete,
    create_finalized_statement,
    create_funded_wallet,
    create_live_season,
    create_released_drop,
    get_success_data,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

LIVEOPS = TEST_USERS["liveops_manager_headers"]


class TestWalletSpendPlusRefundRestoresBalance:
    def _setup_wallet_and_drop(self, api, price_vc=300):
        agreement = create_active_agreement()
        athlete, _ = create_eligible_athlete(agreement["id"])
        season = create_live_season(agreement["id"], athlete["id"])
        drop = create_released_drop(season["id"], drop_kind="VANITY",
                                    drop_label="Emote Pack", price_vc=price_vc)
        wallet = create_funded_wallet(season["id"], 1000, owner_tag="spender")
        return drop, wallet

    def test_spend_then_refund_restores_exact_balance(self, api):
        """PRD §3.4: "a SPEND_DROP debit paired with a REFUND credit of equal
        amount_vc restores the prior balance exactly."

        Design: Difficulty/compensating_invariant/wallet_spend_plus_refund_restores_balance
        """
        drop, wallet = self._setup_wallet_and_drop(api)
        get_success_data(
            api_client.purchase_content_drop(drop["id"], {"wallet_id": wallet["id"]},
                                             LIVEOPS)
        )
        mid = get_success_data(api_client.get_wallet(wallet["id"], LIVEOPS))
        assert mid["vc_balance"] == 700, f"1000 - 300 = 700; got {mid['vc_balance']}"

        get_success_data(
            api_client.post_ledger_entry(
                wallet["id"],
                {"direction": "CREDIT", "amount_vc": 300, "reason_code": "REFUND",
                 "reference_id": drop["id"]},
                FINANCE,
            )
        )
        end = get_success_data(api_client.get_wallet(wallet["id"], LIVEOPS))
        assert end["vc_balance"] == 1000, (
            f"the compensating pair must restore 1000 exactly; got {end['vc_balance']}"
        )

    def test_ledger_is_append_only_throughout(self, api):
        """PRD §2.5: "WalletLedgerEntry is an append-only posting with no
        in-place mutation, so it carries only id and created_at." PRD §3.4:
        "A wallet's balance is never stored as a mutable counter — it is
        recomputed from the ledger: the sum of CREDIT amounts minus the sum of
        DEBIT amounts across all POSTED entries."

        Design: Difficulty/compensating_invariant/wallet_spend_plus_refund_restores_balance
        """
        drop, wallet = self._setup_wallet_and_drop(api)
        get_success_data(
            api_client.purchase_content_drop(drop["id"], {"wallet_id": wallet["id"]},
                                             LIVEOPS)
        )
        get_success_data(
            api_client.post_ledger_entry(
                wallet["id"],
                {"direction": "CREDIT", "amount_vc": 300, "reason_code": "REFUND",
                 "reference_id": drop["id"]},
                FINANCE,
            )
        )
        entries, meta = validate_paginated(
            api_client.list_ledger_entries(wallet["id"], LIVEOPS)
        )
        assert meta["total_count"] == 3
        reasons = [(e["direction"], e["amount_vc"], e["reason_code"]) for e in entries]
        assert ("CREDIT", 1000, "GRANT") in reasons
        assert ("DEBIT", 300, "SPEND_DROP") in reasons
        assert ("CREDIT", 300, "REFUND") in reasons
        assert all(e["entry_status"] == "POSTED" for e in entries)

        wallet_after = get_success_data(api_client.get_wallet(wallet["id"], LIVEOPS))
        assert_wallet_invariants(wallet_after, entries)


class TestFinalizeThenPayLeavesOutstandingConserved:
    def test_finalize_raises_outstanding_by_final_accrual(self, api):
        """PRD §3.7: "finalization increases the agreement's
        outstanding_royalty_cents by the final accrual minus
        held_royalty_cents."

        Design: Difficulty/compensating_invariant/statement_finalize_then_pay_leaves_outstanding_conserved
        """
        agreement = create_active_agreement(mg_recoupable=False)
        before = get_success_data(api_client.get_agreement(agreement["id"], FINANCE))
        assert before["outstanding_royalty_cents"] == 0

        statement = create_finalized_statement(
            agreement["id"], gross_sales_cents=500000, returns_cents=0,
            pending_sales_cents=0,
        )
        after = get_success_data(api_client.get_agreement(agreement["id"], FINANCE))
        assert statement["accrued_royalty_cents"] == 50000
        assert after["outstanding_royalty_cents"] == 50000, (
            f"finalize must add the accrual to outstanding; "
            f"got {after['outstanding_royalty_cents']}"
        )

    def test_pay_returns_outstanding_to_pre_finalize_value(self, api):
        """PRD §3.7: "The conserved quantity across finalize, pay, and audit
        settle is that outstanding_royalty_cents always equals the sum, across
        statements in FINALIZED, DISPUTED, or PAID, of accrued minus held minus
        paid; a finalize followed later by a pay of the same statement leaves
        the outstanding balance unchanged relative to before the finalize."

        Design: Difficulty/compensating_invariant/statement_finalize_then_pay_leaves_outstanding_conserved
        """
        agreement = create_active_agreement(mg_recoupable=False)
        statement = create_finalized_statement(
            agreement["id"], gross_sales_cents=500000, returns_cents=0,
            pending_sales_cents=0,
        )
        paid = get_success_data(api_client.pay_statement(statement["id"], FINANCE))
        assert paid["statement_status"] == "PAID"
        assert paid["paid_royalty_cents"] == 50000

        after = get_success_data(api_client.get_agreement(agreement["id"], FINANCE))
        assert after["outstanding_royalty_cents"] == 0, (
            f"finalize(+50000) then pay(-50000) must conserve the initial 0; "
            f"got {after['outstanding_royalty_cents']}"
        )
