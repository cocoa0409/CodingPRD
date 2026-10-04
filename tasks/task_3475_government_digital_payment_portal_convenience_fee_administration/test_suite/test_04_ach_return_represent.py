"""ACH return / re-presentment cycle: cyclic funds states, auto-created debit
batches, representment count boundary, 30-day window, zero net drift."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    ach_return,
    api_client,
    assert_transaction,
    close_batch,
    get_batch,
    get_transaction,
    list_batches,
    make_agency_admin_headers,
    open_batch,
    re_present,
    set_clock,
    setup_returned_echeck,
    validate_error,
)

PA = TEST_USERS["platform_admin_headers"]
AA_LEAD = make_agency_admin_headers("aa-lead")


def _parse(ts):
    from datetime import datetime
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    raise AssertionError(f"unparseable timestamp {ts!r}")


class TestReturnRepresentCycle:
    def test_ach_return_clears_batch_and_represent_recomputes_value_date(self, api):
        """PRD §3.6: "The transaction moves to `RETURNED`, its `returned_at`
        is stamped from the logical clock, and its `current_batch_id` is
        cleared to null."
        PRD §3.6: "A successful re-presentment moves the transaction to
        `RE_PRESENTED`, sets `representment_count` to 1, and recomputes
        `value_date` as the current clock's calendar date plus the two-day
        `ECHECK` lag".

        Design: Difficulty/non_linear_state_machine/transaction_ach_return_represent_cycle
        """
        ctx = setup_returned_echeck()  # settled 09-12 batch, returned at 2026-09-15
        txn = ctx["transaction"]
        assert txn["funds_status"] == "RETURNED"
        assert txn["current_batch_id"] is None
        assert txn["representment_count"] == 0
        assert _parse(txn["returned_at"]) == _parse("2026-09-15T00:00:00Z")
        # the return auto-created an OPEN batch stamped with the clock date, carrying the debit
        auto = ctx["batches"][1]
        assert auto["status"] == "OPEN"
        assert auto["business_date"] == "2026-09-15"
        assert auto["return_debits_cents"] == 50000

        rep = re_present(txn["id"])
        assert rep["funds_status"] == "RE_PRESENTED"
        assert rep["representment_count"] == 1
        assert rep["value_date"] == "2026-09-17"  # 09-15 plus the two-day ECHECK lag

    def test_return_represent_cycle_resettles_in_later_batch(self, api):
        """PRD §3.6: "from there a later batch close sweeps it back to
        `SETTLED` under the same membership predicate."

        Design: Difficulty/non_linear_state_machine/transaction_ach_return_represent_cycle
        """
        ctx = setup_returned_echeck()
        txn = re_present(ctx["transaction"]["id"])
        auto = ctx["batches"][1]
        # closing the 09-15 auto batch sweeps nothing: value_date 09-17 is after its business_date
        closed_auto = close_batch(auto["id"])
        assert closed_auto["member_count"] == 0
        assert closed_auto["deposit_cents"] == -50000, "the return debit stands alone"
        batch2 = open_batch(ctx["agency"]["id"], "2026-09-17")
        closed2 = close_batch(batch2["id"])
        assert closed2["member_count"] == 1
        final = get_transaction(txn["id"])
        assert final["funds_status"] == "SETTLED"
        assert final["current_batch_id"] == batch2["id"]


class TestRepresentmentCountBoundary:
    def test_first_represent_allowed_at_count_zero(self, api):
        """PRD §3.6: "The agency may re-present a `RETURNED` transaction
        exactly once. The attempt — an `AgencyAdmin` operation — requires
        `representment_count` still at zero, otherwise
        `ERR_REPRESENTMENT_EXHAUSTED`".

        Design: Difficulty/boundary_precision_check/representment_count_zero_allowed_one_exhausted
        """
        ctx = setup_returned_echeck()
        rep = re_present(ctx["transaction"]["id"])
        assert rep["funds_status"] == "RE_PRESENTED"
        assert rep["representment_count"] == 1

    def test_second_represent_rejected_exhausted(self, api):
        """PRD §3.6: "A return recorded against a `RE_PRESENTED` transaction
        runs the same cascade, and because its `representment_count` stays at
        1, no further re-presentment is possible."

        Design: Difficulty/boundary_precision_check/representment_count_zero_allowed_one_exhausted
        """
        ctx = setup_returned_echeck()
        rep = re_present(ctx["transaction"]["id"])
        returned_again = ach_return(rep["id"])  # RE_PRESENTED -> RETURNED, count stays 1
        assert returned_again["funds_status"] == "RETURNED"
        assert returned_again["representment_count"] == 1
        resp = api_client.re_present_transaction(rep["id"], AA_LEAD)
        validate_error(resp, ApiErrorId.ERR_REPRESENTMENT_EXHAUSTED)
        final = get_transaction(rep["id"])
        assert final["funds_status"] == "RETURNED"
        assert final["representment_count"] == 1


class TestNetRemittanceZeroDrift:
    def _full_cycle(self):
        ctx = setup_returned_echeck()
        rep = re_present(ctx["transaction"]["id"])
        auto = ctx["batches"][1]
        closed_auto = close_batch(auto["id"])
        batch3 = open_batch(ctx["agency"]["id"], "2026-09-17")
        closed3 = close_batch(batch3["id"])
        return ctx, rep, closed_auto, closed3

    def test_net_remittance_zero_drift_across_return_cycle(self, api):
        """PRD §3.5: "`deposit_cents` as `gross_amount_cents` minus
        `refund_debits_cents` minus `return_debits_cents` minus
        `chargeback_debits_cents`, which may be negative".

        Design: Difficulty/compensating_invariant/net_remittance_return_represent_zero_drift
        """
        ctx, rep, closed_auto, closed3 = self._full_cycle()
        batch1 = get_batch(ctx["batch"]["id"])
        assert batch1["deposit_cents"] == 50000, "original settle"
        assert closed_auto["deposit_cents"] == -50000, "empty close carrying only the return debit"
        assert closed_auto["return_debits_cents"] == 50000
        assert closed3["deposit_cents"] == 50000, "re-presented settle"
        assert (
            batch1["deposit_cents"] + closed_auto["deposit_cents"] + closed3["deposit_cents"]
            == 50000
        ), "the compensating return/re-present pair nets to exactly one settlement"

    def test_represented_transaction_settles_again_with_zero_drift(self, api):
        """PRD §3.6: "The withheld convenience fee is not returned to the
        payer and is not clawed back from the self-funding pool."

        Design: Difficulty/compensating_invariant/net_remittance_return_represent_zero_drift
        """
        ctx, rep, closed_auto, closed3 = self._full_cycle()
        final = get_transaction(rep["id"])
        assert_transaction(final)
        assert final["funds_status"] == "SETTLED"
        assert final["current_batch_id"] == closed3["id"]
        assert final["representment_count"] == 1
        assert final["amount_cents"] == 50000
        # fees_withheld stayed with the portal in the settling batches; no fee clawback batch exists
        assert closed3["fees_withheld_cents"] == 150


class TestRepresentmentWindow:
    def test_representment_window_closed_after_thirty_days(self, api):
        """PRD §3.6: "The attempt — an `AgencyAdmin` operation — requires
        `representment_count` still at zero, otherwise
        `ERR_REPRESENTMENT_EXHAUSTED`, and a logical clock no later than thirty
        days after `returned_at`, otherwise `ERR_REPRESENTMENT_WINDOW_CLOSED`."

        Design: Corner/errors/err_representment_window_closed
        """
        ctx = setup_returned_echeck()  # returned at 2026-09-15
        set_clock("2026-10-16T00:00:00Z")  # 31 days later
        resp = api_client.re_present_transaction(ctx["transaction"]["id"], AA_LEAD)
        validate_error(resp, ApiErrorId.ERR_REPRESENTMENT_WINDOW_CLOSED)
        final = get_transaction(ctx["transaction"]["id"])
        assert final["funds_status"] == "RETURNED"
        assert final["representment_count"] == 0
