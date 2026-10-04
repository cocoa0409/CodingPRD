"""Invoice ageing, the two compensating exits from OVERDUE, and the partner ledger.

An OVERDUE invoice can leave through either payment or void, and both exits
restore the partner's derived receivable picture (PRD §2.10, §3.7).
"""
from test_helpers import (
    assert_invoice,
    invoice_payment_payload,
    read_partner,
    setup_invoiced_placement,
    setup_overdue_invoice,
    staff_headers,
    validate_success,
)

PLACEMENT_FEE = 136339


def test_overdue_invoice_voided_restores_partner_credit_standing(api):
    """PRD §3.7: "an `ISSUED` or `OVERDUE` invoice moves to `VOID`, and the partner's
    `outstanding_balance_cents`, `billed_cents` and `oldest_open_due_date` are
    recomputed with the voided invoice excluded from every aggregate"
    PRD §2.10: "The `credit_hold` flag is true exactly when the partner carries an
    invoice at status `OVERDUE` whose `due_date` is strictly before the logical-clock
    date; it is cleared as soon as that condition stops holding, which happens when
    the invoice is paid or voided."

    Design: Difficulty/non_linear_state_machine/invoice_overdue_dual_recovery_edges
    """
    scenario = setup_overdue_invoice()
    assert scenario.invoice["status"] == "OVERDUE", scenario.invoice["status"]
    assert scenario.partner["credit_hold"] is True, scenario.partner["credit_hold"]

    data = validate_success(
        api.void_invoice(
            scenario.invoice["id"], staff_headers(),
            {"reason": "Invoice raised against the wrong placement"},
        ),
        200,
    )
    assert data["status"] == "VOID", data["status"]
    assert_invoice(data)

    partner = read_partner(scenario.partner["id"])
    assert partner["outstanding_balance_cents"] == 0, partner["outstanding_balance_cents"]
    assert partner["credit_hold"] is False, partner["credit_hold"]


def test_overdue_invoice_paid_clears_credit_hold_and_collects(api):
    """PRD §3.7: "An `ISSUED` or `OVERDUE` invoice moves to `PAID`, `paid_on` is
    recorded, and the partner's `on_time_payment_ratio`, `collected_cents`,
    `collection_ratio` and `outstanding_balance_cents` are all recomputed."
    PRD §2.10: "The partner's `credit_hold` is cleared once no other invoice of that
    partner remains `OVERDUE`"

    The other exit from OVERDUE leaves the same receivable at zero but records
    the money as collected rather than erasing the invoice.

    Design: Difficulty/non_linear_state_machine/invoice_overdue_dual_recovery_edges
    """
    scenario = setup_overdue_invoice()
    assert scenario.invoice["total_amount_cents"] == PLACEMENT_FEE, scenario.invoice

    data = validate_success(
        api.pay_invoice(
            scenario.invoice["id"],
            invoice_payment_payload(amount_paid_cents=PLACEMENT_FEE, paid_on="2027-02-03"),
            staff_headers(),
        ),
        200,
    )
    assert data["status"] == "PAID", data["status"]
    assert data["amount_paid_cents"] == PLACEMENT_FEE, data["amount_paid_cents"]

    partner = read_partner(scenario.partner["id"])
    assert partner["outstanding_balance_cents"] == 0, partner["outstanding_balance_cents"]
    assert partner["collected_cents"] == PLACEMENT_FEE, partner["collected_cents"]
    assert partner["credit_hold"] is False, partner["credit_hold"]


def test_partner_outstanding_balance_restored_by_invoice_void(api):
    """PRD §3.7: "`outstanding_balance_cents` is the sum of `total_amount_cents` over
    the partner's `ISSUED` and `OVERDUE` invoices"
    PRD §2.10: "it is cleared as soon as that condition stops holding, which happens
    when the invoice is paid or voided"

    The conserved quantity is the money owed to the program: issuing the invoice
    raised the partner's outstanding balance by the placement fee, and voiding
    that same invoice returns it to the pre-invoice value.

    Design: Difficulty/compensating_invariant/partner_outstanding_balance_restored_by_invoice_void
    """
    scenario = setup_invoiced_placement()
    outstanding_before = 0
    assert scenario.invoice["status"] == "ISSUED", scenario.invoice["status"]
    assert scenario.partner["outstanding_balance_cents"] == PLACEMENT_FEE, (
        scenario.partner["outstanding_balance_cents"]
    )

    validate_success(
        api.void_invoice(
            scenario.invoice["id"], staff_headers(),
            {"reason": "Placement fee re-negotiated before collection"},
        ),
        200,
    )

    partner = read_partner(scenario.partner["id"])
    assert partner["outstanding_balance_cents"] == outstanding_before, (
        f"expected the pre-invoice balance {outstanding_before}, "
        f"got {partner['outstanding_balance_cents']}"
    )


def test_voided_invoice_contributes_to_no_partner_aggregate(api):
    """PRD §2.10: "A `VOID` invoice enters none of these aggregates."
    PRD §2.10: "The `oldest_open_due_date` is the earliest `due_date` among the
    `ISSUED` and `OVERDUE` invoices, and is null when the partner has none open."

    Design: Difficulty/compensating_invariant/partner_outstanding_balance_restored_by_invoice_void
    """
    scenario = setup_invoiced_placement()

    validate_success(
        api.void_invoice(
            scenario.invoice["id"], staff_headers(),
            {"reason": "Raised against a placement that was re-scoped"},
        ),
        200,
    )

    partner = read_partner(scenario.partner["id"])
    assert partner["billed_cents"] == 0, partner["billed_cents"]
    assert partner["outstanding_balance_cents"] == 0, partner["outstanding_balance_cents"]
    assert partner["oldest_open_due_date"] is None, partner["oldest_open_due_date"]
