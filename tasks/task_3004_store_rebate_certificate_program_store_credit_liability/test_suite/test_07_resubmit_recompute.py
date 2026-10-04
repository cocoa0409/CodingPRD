"""Resubmission recomputes the provisional award with returns invisible."""
from test_helpers import (
    validate_success,
    set_clock,
    cash_line, process_return,
    submit_receipt, reject_submission, resubmit_submission,
    setup_store_with_program, setup_account_with_receipt,
)
from test_helpers.test_users import TEST_USERS

GUEST = TEST_USERS["guest_service_headers"]


class TestResubmitRecompute:

    def test_resubmit_recomputes_provisional_with_returns_invisible(self, api):
        """PRD §3.5: "Each resubmission increments `resubmit_count` by 1,
        refreshes `submitted_at` to the current logical clock, clears the
        `rejection_reason`, and recomputes the provisional award."
        PRD §3.5: "The provisional variant — computed on submission creation
        and on each resubmit — skips the minimum-quantity check, ignores
        returns, and stores its result in `provisional_award_cents`."
        PRD §3.5: "The provisional variant computes this with returns
        invisible — `returned_quantity` treated as 0 — because returns
        cannot be known at submission time."

        Design: Corner/endpoints/submission_resubmit_refreshes_provisional_after_return
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-EP2"},
            items=[{"sku": "AAA", "rebate_pct": 0.11}],
        )
        store = base["store"]
        ctx = setup_account_with_receipt(store, owner_name="Ann")
        submission = submit_receipt(
            store["id"], ctx["receipt"]["id"], ctx["account"]
        )
        assert submission["provisional_award_cents"] == 1100
        submission = reject_submission(
            store["id"], submission["id"], reason="illegible"
        )
        assert submission["rejection_reason"] == "illegible"

        # full return of the only unit — invisible to the provisional variant
        process_return(store["id"], ctx["receipt"]["id"],
                       [{"line_number": 1, "quantity": 1}])

        resubmitted = resubmit_submission(
            store["id"], submission["id"], ctx["account"]
        )
        assert resubmitted["status"] == "UNDER_REVIEW"
        assert resubmitted["resubmit_count"] == 1
        assert resubmitted["rejection_reason"] is None, (
            "resubmit clears the rejection_reason"
        )
        assert resubmitted["provisional_award_cents"] == 1100, (
            f"the provisional variant treats returned_quantity as 0, so the "
            f"intervening full return does not change the figure; got "
            f"{resubmitted['provisional_award_cents']}"
        )
