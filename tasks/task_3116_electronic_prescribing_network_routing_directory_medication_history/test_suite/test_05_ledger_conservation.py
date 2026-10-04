"""The append-only fee ledger's two conserved quantities.

Money and counts are conserved independently across a charge-and-compensate pair, and the
second conserved quantity also holds when a repeated report lands on the same billing cell.
"""
from test_helpers import (
    set_clock,
    create_clinic,
    post_fee_entry,
    reload_fee_entry,
    reverse_fee_entry,
)


def test_reversal_returns_the_participant_month_net_to_its_pre_charge_value(api):
    """PRD §2.7: "The first is `period_net_total_cents`, the sum of `fee_cents` over every
    `TransactionFeeEntry` row sharing the same participant and `month_key`."
    PRD §2.7: "For the same reason a row marked `REVERSED` keeps its own `fee_cents` and
    remains inside the total; the marker records that a compensating row exists, not that the
    original was erased."

    Design: Difficulty/compensating_invariant/fee_entry_reversal_preserves_net_fee_cents
    """
    set_clock()
    clinic = create_clinic(volume_billing_mode="MONTHLY")

    entry_small = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT", transaction_count=500
    )
    assert entry_small["fee_cents"] == 3600
    net_after_first = entry_small["period_net_total_cents"]
    assert net_after_first == 3600

    entry_big = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT", transaction_count=2000
    )
    assert entry_big["fee_cents"] == 21600
    assert entry_big["period_net_total_cents"] == 25200

    compensation = reverse_fee_entry(entry_big["id"], clinic["id"])
    assert compensation["fee_cents"] == -21600
    assert compensation["transaction_count"] == -2000

    small_after = reload_fee_entry(entry_small["id"])
    assert small_after["period_net_total_cents"] == net_after_first, (
        "the forward-and-compensating pair leaves the month's net money unchanged"
    )

    big_after = reload_fee_entry(entry_big["id"])
    assert big_after["status"] == "REVERSED"
    assert big_after["fee_cents"] == 21600
    assert big_after["period_net_total_cents"] == small_after["period_net_total_cents"]


def test_chargeable_volume_is_untouched_by_a_reversal(api):
    """PRD §3.7: "The basis total is the sum of `transaction_count` over those rows, clamped
    to a ceiling of 7500."
    PRD §3.7: "Compensating `MANUAL_REVERSAL` rows are excluded precisely because they carry a
    `reversal_of_entry_id`, so a reversal never changes chargeable volume."

    Design: Difficulty/compensating_invariant/fee_entry_reversal_preserves_net_fee_cents
    """
    set_clock()
    clinic = create_clinic(volume_billing_mode="MONTHLY")

    entry_small = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT", transaction_count=500
    )
    entry_big = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT", transaction_count=2000
    )
    anchor_total_before = reload_fee_entry(entry_small["id"])
    assert anchor_total_before["transaction_count"] == 500

    reverse_fee_entry(entry_big["id"], clinic["id"])

    # The cell's chargeable basis is unchanged because the compensating row is excluded.
    reloaded = reload_fee_entry(entry_big["id"])
    assert reloaded["reversal_of_entry_id"] is None
    assert reloaded["transaction_count"] == 2000
    assert reloaded["status"] == "REVERSED"