"""Transaction fee settlement: the marginal tier schedule and the chargeable ceiling.

The chargeable basis is variant-neutral and is clamped to the monthly ceiling before the
tier schedule runs; the reserve that separates the two billing modes is applied to the
tiered amount afterwards.
"""
from test_helpers import (
    set_clock,
    create_clinic,
    post_fee_entry,
    reload_fee_entry,
    reverse_fee_entry,
    make_participant_admin_headers,
    api_client,
    get_success_data,
    apply_tiers,
    SENDER_SCHEDULE,
)


def test_chargeable_total_is_clamped_to_the_ceiling_before_tiering(api):
    """PRD §3.7: "The basis total is the sum of `transaction_count` over those rows, clamped
    to a ceiling of 7500."
    PRD §3.7: "because the total is never presented to the tier function above 7500, every
    count at or above the ceiling settles at exactly the fee for 7500, and the ceiling
    absorbs the top `VOLUME` tier."

    Design: Difficulty/combinatorial_formula/transaction_fee_settlement_clamp_before_tiering
    """
    set_clock()
    clinic = create_clinic(volume_billing_mode="MONTHLY")

    entry_hi = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT", transaction_count=7825
    )
    assert entry_hi["fee_tier"] == "VOLUME"
    assert entry_hi["fee_cents"] == 60100
    # The unclamped schedule would have produced 1800*12 + 5825*7 == 62375: the standard
    # band is 200 wide-free-bound..2000, so only 1800 counts sit in it.
    unclamped_hi = apply_tiers(7825, SENDER_SCHEDULE["default"])
    assert unclamped_hi == 62375
    assert entry_hi["fee_cents"] != unclamped_hi

    entry_over = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT", transaction_count=8000
    )
    assert entry_over["transaction_count"] == 8000
    assert entry_over["fee_cents"] == 60100

    refreshed = reload_fee_entry(entry_hi["id"])
    assert refreshed["transaction_count"] == 7825
    assert refreshed["fee_cents"] == 60100


def test_reversing_a_clamped_charge_conserves_the_month_net_and_the_cell_count(api):
    """PRD §2.7: "a charge followed by its compensating row leaves the quantity exactly where
    it began — the positive `fee_cents` of the charge and the negative `fee_cents` of the
    compensation cancel."
    PRD §2.7: "It too is independent of status, and the negative `transaction_count` carried
    by a compensating row cancels its charge back to the pre-charge value."

    Design: Difficulty/combinatorial_formula/transaction_fee_settlement_clamp_before_tiering
    """
    set_clock()
    clinic = create_clinic(volume_billing_mode="MONTHLY")

    entry_hi = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT", transaction_count=7825
    )
    entry_mid = post_fee_entry(
        clinic["id"], transaction_type="NEW_RX", direction="SENT", transaction_count=500
    )
    assert entry_mid["fee_cents"] == 3600, "300*12 + 0*7 for the 500-count cell"

    charged_net = reload_fee_entry(entry_mid["id"])["period_net_total_cents"]
    assert charged_net == 60100 + 3600
    count_before = 7825 + 500

    compensation = reverse_fee_entry(entry_hi["id"], clinic["id"])
    assert compensation["entry_type"] == "MANUAL_REVERSAL"
    assert compensation["fee_cents"] == -60100
    assert compensation["transaction_count"] == -7825

    source = reload_fee_entry(entry_hi["id"])
    assert source["status"] == "REVERSED"
    assert source["reversal_entry_id"] == compensation["id"]
    # The month's net money returns to the 3600 cents the surviving charge contributes.
    assert source["period_net_total_cents"] == 3600
    assert source["fee_cents"] + compensation["fee_cents"] == 0

    cell_rows = get_success_data(
        api_client.list_transaction_fees(
            make_participant_admin_headers(clinic["id"]),
            {"participant_id": clinic["id"], "month_key": "2026-09",
             "transaction_type": "NEW_RX", "direction": "SENT"},
        )
    )
    # The cell's net transaction count is its chargeable volume less the reversed
    # charge, because the compensating row carries the negation of the charge it
    # compensates — so the pair cancels and the surviving charge stands alone.
    assert sum(row["transaction_count"] for row in cell_rows) == entry_mid["transaction_count"]

    # The compensating row is excluded from the chargeable basis, so the cell's chargeable
    # volume is unchanged by the reversal.
    anchor_rows = [row for row in cell_rows if row["reversal_of_entry_id"] is None]
    assert sum(row["transaction_count"] for row in anchor_rows) == count_before