"""Immediate consistency: mutations are visible on the very next read."""
from test_helpers import (
    get_success_data,
    make_finance_officer_headers,
    setup_committed_batch,
    validate_success,
)


class TestImmediateConsistency:
    def test_finalize_response_immediately_reflects_all_mutations(self, api):
        """PRD §2.9: "when a batch finalizes or reverses, the abolished totals
        and every drawn campaign's balances move together in the same atomic
        step."
        PRD §3.6: "Meanwhile each drawn campaign converts its reservation into
        spend — `committed_cents` decreases by the allocation and `spent_cents`
        increases by the same — and the portfolio's `abolished_face_value_cents`
        increases by the batch's `total_abolished_cents`."

        Design: Corner/consistency_model/finalize_response_immediately_reflects_all_mutations
        """
        ctx = setup_committed_batch()
        batch = ctx["batch"]
        fin = make_finance_officer_headers()
        resp = api.finalize_abolishment_batch(batch["id"], fin)
        finalized = validate_success(resp, 200)
        assert finalized["status"] == "FINALIZED"
        # Immediately after, with no waiting, every mutation is visible.
        a1 = get_success_data(
            api.get_account(ctx["accounts"][0]["id"], fin)
        )
        assert a1["lifecycle_status"] == "ABOLISHED"
        campaign = get_success_data(
            api.get_donor_campaign(ctx["campaign"]["id"], fin)
        )
        assert campaign["spent_cents"] == 1550000
        assert campaign["committed_cents"] == 0
        portfolio = get_success_data(
            api.get_portfolio(ctx["portfolio"]["id"], fin)
        )
        assert portfolio["abolished_face_value_cents"] == 1550000
