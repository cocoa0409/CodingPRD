"""Payout ledger compensating invariants (queue A): process-due debit paired
with the fail compensation, and write-off decoupling."""

from test_helpers import (
    ADMIN,
    read_brand,
    set_clock,
    shipped_invoice_scenario,
    validate_success,
)


def test_fail_after_process_due_restores_balance_exactly(api):
    """PRD §3.10: "A payout in `PROCESSING` is then either completed, moving
    `PROCESSING → PAID`, or failed, moving `PROCESSING → SCHEDULED` with a
    compensating credit of `net_cents` to the brand's balance that exactly
    undoes the earlier debit, so the next batch run retries the payout
    cleanly."
    PRD §2.10: "Shipping an order credits the ledger by the payout's net
    amount; processing a due payout debits the ledger by the same amount, and
    the debit is recorded even when it would drive the balance negative"

    Design: Difficulty/compensating_invariant/payout_fail_compensates_balance
    """
    (retailer, _, brand, order, invoice, payout
     ) = shipped_invoice_scenario(api, unit_price_cents=20000, qty=5,
                                  brand_kwargs={"payout_delay_days": 7})
    # Opening marketplace order: commission 2500 bps on 100000 -> net 75000.
    assert payout["net_cents"] == 75000
    assert read_brand(api, brand["id"])["payout_balance_cents"] == 75000

    set_clock(api, "2026-09-08T00:00:00Z")  # scheduled_date reached
    validate_success(api.process_due_payouts(ADMIN))
    assert read_brand(api, brand["id"])["payout_balance_cents"] == 0

    failed = validate_success(api.fail_payout(payout["id"], ADMIN))
    assert failed["status"] == "SCHEDULED"
    assert read_brand(api, brand["id"])["payout_balance_cents"] == 75000, (
        "the fail compensation must exactly undo the process-due debit"
    )


def test_complete_after_process_due_settles_payout(api):
    """PRD §3.10: "A payout in `PROCESSING` is then either completed, moving
    `PROCESSING → PAID`, or failed, moving `PROCESSING → SCHEDULED` with a
    compensating credit of `net_cents` to the brand's balance that exactly
    undoes the earlier debit, so the next batch run retries the payout
    cleanly."

    Design: Difficulty/compensating_invariant/payout_fail_compensates_balance
    """
    (retailer, _, brand, order, invoice, payout
     ) = shipped_invoice_scenario(api, unit_price_cents=20000, qty=5,
                                  brand_kwargs={"payout_delay_days": 7})
    set_clock(api, "2026-09-08T00:00:00Z")
    validate_success(api.process_due_payouts(ADMIN))

    completed = validate_success(api.complete_payout(payout["id"], ADMIN))
    assert completed["status"] == "PAID"
    assert read_brand(api, brand["id"])["payout_balance_cents"] == 0


def test_write_off_never_claws_back_brand_payout(api):
    """PRD §3.9: "Critically, a write-off never claws back the brand's payout:
    collection risk on net-60 terms is the platform's, and the brand's
    `payout_balance_cents` is not debited."

    Design: Difficulty/compensating_invariant/write_off_preserves_brand_payout
    """
    (retailer, _, brand, order, invoice, payout
     ) = shipped_invoice_scenario(api, unit_price_cents=20000, qty=10,
                                  brand_kwargs={"payout_delay_days": 7})
    # Opening marketplace: 200000 gross, 2500 bps -> net 150000.
    assert payout["net_cents"] == 150000

    # Process and complete the payout before the invoice even falls due.
    set_clock(api, "2026-09-08T00:00:00Z")
    validate_success(api.process_due_payouts(ADMIN))
    validate_success(api.complete_payout(payout["id"], ADMIN))
    assert read_brand(api, brand["id"])["payout_balance_cents"] == 0

    # Age the invoice to due+35d and write it off.
    set_clock(api, "2026-12-05T00:00:00Z")
    written = validate_success(api.write_off_invoice(invoice["id"], ADMIN))
    assert written["status"] == "WRITTEN_OFF"
    assert read_brand(api, brand["id"])["payout_balance_cents"] == 0, (
        "write-off must not move the brand's payout ledger"
    )


def test_unpaid_invoice_write_off_still_leaves_payout_untouched(api):
    """PRD §3.9: "Critically, a write-off never claws back the brand's payout:
    collection risk on net-60 terms is the platform's, and the brand's
    `payout_balance_cents` is not debited."
    PRD §2.10: "Because the payout schedule is fixed at shipment time and never
    revisited, retailer payment behavior — late, partial, or never — has no
    effect on what the brand is owed or when."

    Design: Difficulty/compensating_invariant/write_off_preserves_brand_payout
    """
    (retailer, _, brand, order, invoice, payout
     ) = shipped_invoice_scenario(api, unit_price_cents=20000, qty=10,
                                  brand_kwargs={"payout_delay_days": 7})
    # No payment at all; payout still SCHEDULED (scheduled 2026-09-08), so the
    # accrued 150000 remains on the ledger at write-off time.
    set_clock(api, "2026-12-05T00:00:00Z")
    written = validate_success(api.write_off_invoice(invoice["id"], ADMIN))
    assert written["status"] == "WRITTEN_OFF"
    assert read_brand(api, brand["id"])["payout_balance_cents"] == 150000, (
        "the unprocessed accrual must survive the invoice write-off untouched"
    )
