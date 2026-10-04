"""Breadth coverage for the immediate-consistency model."""
from test_helpers import (
    buy_title,
    create_buyer,
    create_released_title,
    read_title,
)


def test_immediate_consistency_on_purchase():
    """PRD §1: "The system is built around an immediate-consistency model:
    every mutation that changes money, review scores, or abuse posture
    recomputes its derived values before the response returns, and several
    write paths are guarded by optimistic concurrency so that a client acting
    on a stale snapshot of a title is turned away rather than allowed to
    overwrite work it never saw."

    Design: Corner/consistency_model/immediate_consistency_on_purchase
    """
    developer, title = create_released_title(base_price_usd_cents=1000)
    buyer = create_buyer()

    purchase = buy_title(buyer, title)
    # The creation response already carries the computed split and USD snapshot.
    assert purchase["gross_price_cents"] == 1000
    assert purchase["platform_fee_cents"] == 300  # round_half_up(1000 * 0.30)
    assert purchase["developer_share_cents"] == 700
    assert purchase["usd_recognized_cents"] == 1000

    # A same-instant read of the title already shows the ledger credit.
    title_read = read_title(title["id"], developer)
    assert title_read["lifetime_recognized_revenue_usd_cents"] == 1000
    assert title_read["current_tier"] == 1
