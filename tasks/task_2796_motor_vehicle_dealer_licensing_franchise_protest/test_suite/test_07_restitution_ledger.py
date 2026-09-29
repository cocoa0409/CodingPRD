"""The restitution ledger: a conserved quantity that a partial payment moves
across an equality, that an overpayment may not break, and that settling in
full drives to zero without retiring a single point.
"""
from prd_bench_local_runner.testing import validate_error
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_dealer_ledger_matches,
    assert_restitution_ledger_conserved,
)
from test_helpers.test_users import make_dealer_headers


def _capped_odometer_sanction():
    """A licensed dealership sanctioned on 2026-09-05 for an odometer
    misrepresentation with an alleged loss of 1,800,000 cents.

    The restitution cap binds at 1,500,000 cents before the penalty is computed,
    so the loss-linked five percent is five percent of the capped figure.
    """
    ctx = fx.setup_licensed_dealer()
    fx.set_clock("2026-09-05T00:00:00Z")
    ctx["complaint"] = fx.sanction_complaint(
        ctx["dealer"]["id"], "PROBATION", 1800000, "ODOMETER_MISREPRESENTATION",
        findings_code="ODOMETER_ROLLBACK_CONFIRMED")
    return ctx


class TestPartialPaymentConservesTheLedger:
    def test_the_capped_order_opens_the_ledger_at_the_full_balance(self, api):
        """PRD 3.9: "`restitution_ordered_cents` is the consumer's
        `alleged_loss_cents` capped at 1,500,000 cents (fifteen thousand
        dollars)." PRD 3.9: "Note the ordering: the restitution cap binds before
        the penalty is computed, so a capped loss also caps the loss-linked half
        of the penalty, and both caps apply after the addition." The base for an
        odometer misrepresentation is 200,000 cents, so the penalty is 200000 +
        75000 = 275000, and PRD 3.9 leaves the balance untouched:
        "`restitution_due_on` is set to 30 days after the resolution date and
        `restitution_paid_cents` is left at 0."

        Design: Difficulty/compensating_invariant/restitution_ledger_conserved_after_payment
        """
        ctx = _capped_odometer_sanction()
        complaint = ctx["complaint"]

        assert complaint["status"] == "SANCTIONED"
        assert complaint["restitution_ordered_cents"] == 1500000
        assert complaint["civil_penalty_cents"] == 275000
        assert complaint["restitution_paid_cents"] == 0
        assert complaint["restitution_due_on"] == "2026-10-05"
        assert_restitution_ledger_conserved(complaint)

        dealer = fx.read_dealer(ctx["dealer"]["id"])
        assert dealer["restitution_outstanding_cents"] == 1500000
        assert_dealer_ledger_matches(dealer, [complaint])

    def test_a_partial_payment_moves_value_without_changing_the_sum(self, api):
        """PRD 3.9: "A payment that leaves a balance outstanding keeps the
        complaint in `SANCTIONED`, increases `restitution_paid_cents` by the
        amount paid and decreases the dealership's
        `restitution_outstanding_cents` by exactly that same amount, conserving
        the ledger invariant of §2.11." PRD 2.11 states the invariant itself: "A
        payment moves value from one side of the invariant to the other and never
        changes the sum". 600000 paid leaves 900000 outstanding, and the two still
        sum to the 1500000 ordered.

        Design: Difficulty/compensating_invariant/restitution_ledger_conserved_after_payment
        """
        ctx = _capped_odometer_sanction()
        complaint = ctx["complaint"]

        paid = fx.pay_restitution(complaint["id"], ctx["dealer"]["id"], 600000)

        assert paid["status"] == "SANCTIONED"
        assert paid["restitution_paid_cents"] == 600000
        assert paid["restitution_ordered_cents"] == 1500000

        dealer = fx.read_dealer(ctx["dealer"]["id"])
        assert dealer["restitution_outstanding_cents"] == 900000
        assert (paid["restitution_ordered_cents"]
                == paid["restitution_paid_cents"]
                + dealer["restitution_outstanding_cents"])
        assert_dealer_ledger_matches(dealer, [paid])


class TestOverpaymentAndSettlement:
    def test_an_overpayment_of_one_cent_is_refused_rather_than_clipped(self, api):
        """PRD 3.9: "A payment that would push `restitution_paid_cents` above
        `restitution_ordered_cents` is refused outright with
        `ERR_RESTITUTION_OVERPAYMENT` rather than being clipped to the balance."
        PRD 2.11 gives the reason: "An overpayment is refused outright rather than
        clipped to the balance, precisely so the invariant cannot be broken."
        Against a 900000-cent balance a tender of 900001 must leave both sides of
        the ledger exactly where the earlier partial payment left them.

        Design: Difficulty/compensating_invariant/restitution_ledger_conserved_after_payment
        """
        ctx = _capped_odometer_sanction()
        complaint = ctx["complaint"]
        fx.pay_restitution(complaint["id"], ctx["dealer"]["id"], 600000)

        response = api_client.pay_restitution(
            complaint["id"], f.restitution_payment_payload(900001),
            make_dealer_headers(ctx["dealer"]["id"]))
        validate_error(response, ApiErrorId.ERR_RESTITUTION_OVERPAYMENT.value,
                       expected_status=422)

        after = fx.read_complaint(complaint["id"])
        dealer = fx.read_dealer(ctx["dealer"]["id"])
        assert after["restitution_paid_cents"] == 600000
        assert after["status"] == "SANCTIONED"
        assert dealer["restitution_outstanding_cents"] == 900000
        assert_dealer_ledger_matches(dealer, [after])

    def test_settling_the_balance_closes_the_complaint_but_keeps_the_points(self, api):
        """PRD 3.9: "A payment that settles the balance exactly moves the
        complaint `SANCTIONED → CLOSED_SATISFIED`, sets `restitution_paid_cents`
        equal to `restitution_ordered_cents`, stamps `resolved_at` with the clock
        instant, and recomputes the dealership's `restitution_outstanding_cents`
        so that this complaint's contribution drops to 0." PRD 3.9 keeps the
        points where they were: "Settling restitution does not retire the points
        it carried — a `CLOSED_SATISFIED` complaint keeps contributing until it
        ages out."

        Design: Difficulty/compensating_invariant/restitution_ledger_conserved_after_payment
        """
        ctx = _capped_odometer_sanction()
        complaint = ctx["complaint"]
        fx.pay_restitution(complaint["id"], ctx["dealer"]["id"], 600000)

        settled = fx.pay_restitution(complaint["id"], ctx["dealer"]["id"], 900000)

        assert settled["status"] == "CLOSED_SATISFIED"
        assert settled["restitution_paid_cents"] == 1500000
        assert settled["restitution_paid_cents"] == settled["restitution_ordered_cents"]
        assert settled["resolved_at"] is not None
        assert_restitution_ledger_conserved(settled)

        dealer = fx.read_dealer(ctx["dealer"]["id"])
        assert dealer["restitution_outstanding_cents"] == 0
        assert dealer["disciplinary_points"] == 6
        assert dealer["license_status"] == "LICENSED"
        assert dealer["suspension_reason"] == "NONE"
        assert_dealer_ledger_matches(dealer, [settled])
