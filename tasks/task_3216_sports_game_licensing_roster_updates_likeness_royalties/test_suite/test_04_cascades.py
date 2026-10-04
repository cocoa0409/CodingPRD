"""Difficulty queue A, rule 4: transitive_cascade — both instances."""
from test_helpers import (
    ADMIN,
    FINANCE,
    RIGHTS,
    create_funded_wallet,
    get_success_data,
    setup_cascade_scenario,
    validate_error,
    validate_error_is_one_of,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import TEST_USERS

LIVEOPS_HEADERS = TEST_USERS["liveops_manager_headers"]


class TestAgreementSuspendCascade:
    def test_suspend_cascades_to_grants_and_drops(self, api):
        """PRD §3.1: "Suspending an ACTIVE agreement moves it to SUSPENDED and
        triggers a broad cascade described in §3.2 and §3.4: every GRANTED
        likeness grant under the agreement moves to SUSPENDED with
        suspended_reason set to AGREEMENT_SUSPENDED, every RELEASED content
        drop whose featured athlete has thereby lost all granted coverage
        moves to HELD."

        Design: Difficulty/transitive_cascade/agreement_suspend_cascades_grants_drops_held_royalty
        """
        ctx = setup_cascade_scenario(royalty_share_bps=1000)
        get_success_data(api_client.suspend_agreement(ctx["agreement"]["id"], ADMIN))

        grant = get_success_data(api_client.get_likeness_grant(ctx["grant"]["id"], RIGHTS))
        assert grant["grant_status"] == "SUSPENDED"
        assert grant["suspended_reason"] == "AGREEMENT_SUSPENDED"

        drop = get_success_data(api_client.get_content_drop(ctx["drop"]["id"], LIVEOPS_HEADERS))
        assert drop["drop_status"] == "HELD"

    def test_suspend_cascade_increases_held_royalty(self, api):
        """PRD §3.1: "held_royalty_cents on the open royalty statement increases
        by the held-attribution amount computed in §3.8." PRD §3.8: "the held
        amount for each suspended grant is computed against the statement's
        current accrued_royalty_cents snapshot multiplied by the grant's
        royalty_share_bps and divided by ten thousand, rounded half-up to
        integer cents."

        Design: Difficulty/transitive_cascade/agreement_suspend_cascades_grants_drops_held_royalty
        """
        ctx = setup_cascade_scenario(
            royalty_share_bps=1000, gross_sales_cents=1000000,
            returns_cents=100000,
        )
        # PROVISIONAL accrual: base 900000 at 1000bps = 90000
        get_success_data(api_client.suspend_agreement(ctx["agreement"]["id"], ADMIN))
        statement = get_success_data(
            api_client.get_royalty_statement(ctx["statement"]["id"], FINANCE)
        )
        assert statement["held_royalty_cents"] == 9000, (
            f"round_half_up(90000 * 1000/10000) = 9000; "
            f"got {statement['held_royalty_cents']}"
        )
        assert statement["accrued_royalty_cents"] == 90000, (
            "the accrual snapshot must not be recomputed by the hold"
        )


class TestGrantRevokeCascade:
    def test_revoke_moves_held_drop_to_canceled(self, api):
        """PRD §3.2: "Revocation is terminal and one-way: only a SUSPENDED grant
        may be moved to REVOKED, the athlete drops to INELIGIBLE if no other
        grant remains, and drops held for this athlete move to CANCELED rather
        than back to RELEASED."

        Design: Difficulty/transitive_cascade/grant_revoke_cancels_held_drop_blocks_purchase
        """
        ctx = setup_cascade_scenario(royalty_share_bps=500, with_statement=False)
        get_success_data(
            api_client.suspend_likeness_grant(
                ctx["grant"]["id"], {"suspended_reason": "GRIEVANCE_FILED"}, RIGHTS
            )
        )
        revoked = get_success_data(api_client.revoke_likeness_grant(ctx["grant"]["id"], RIGHTS))
        assert revoked["grant_status"] == "REVOKED"

        drop = get_success_data(api_client.get_content_drop(ctx["drop"]["id"], LIVEOPS_HEADERS))
        assert drop["drop_status"] == "CANCELED", (
            f"revoke must cancel the held drop, not release it; "
            f"got {drop['drop_status']}"
        )

    def test_purchase_blocked_after_revoke_and_wallet_untouched(self, api):
        """PRD §3.4: "Purchasing a drop ... the target drop must be RELEASED,
        the wallet must be OPEN, and the balance must cover price_vc."

        Design: Difficulty/transitive_cascade/grant_revoke_cancels_held_drop_blocks_purchase
        """
        ctx = setup_cascade_scenario(royalty_share_bps=500, with_statement=False,
                                     drop_price_vc=250)
        wallet = create_funded_wallet(ctx["season"]["id"], 500, owner_tag="buyer-1")
        get_success_data(
            api_client.suspend_likeness_grant(
                ctx["grant"]["id"], {"suspended_reason": "GRIEVANCE_FILED"}, RIGHTS
            )
        )
        get_success_data(api_client.revoke_likeness_grant(ctx["grant"]["id"], RIGHTS))

        resp = api_client.purchase_content_drop(
            ctx["drop"]["id"], {"wallet_id": wallet["id"]}, LIVEOPS_HEADERS
        )
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_REFERENCE_STATE.value],
        )
        wallet_after = get_success_data(api_client.get_wallet(wallet["id"], LIVEOPS_HEADERS))
        assert wallet_after["vc_balance"] == 500, (
            f"a rejected purchase must not debit; got {wallet_after['vc_balance']}"
        )
