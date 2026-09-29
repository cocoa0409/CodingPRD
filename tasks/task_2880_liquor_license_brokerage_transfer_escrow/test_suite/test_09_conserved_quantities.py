"""Two conserved quantities across the settle-and-compensate pair.

One is money in cents, the other an integer occupancy count. Both must land
exactly where they started, so each is observed before, during and after the
proceeding rather than only at the end.
"""

from test_helpers import (
    accept_review,
    assert_instant_equals,
    assert_ledger_balance_projection,
    assert_ledger_entry_types,
    assert_ledger_sums_to_balance,
    assert_settlement_buckets_null,
    decide_application,
    execute_agreement,
    file_application,
    ledger_rows,
    post_notice,
    read_agreement,
    read_county,
    read_disclosure,
    read_license,
    read_listing,
    set_clock,
    settle_escrow,
    setup_closed_agreement,
    setup_denied_agreement,
    setup_scenario,
)

DEPOSIT_CENTS = 2405001
COUNTY_FEE_CENTS = 277500
COMMISSION_CENTS = 1063750
SELLER_NET_CENTS = 1063751


def _closed_dual_agency_transfer():
    """An APPROVED transfer holding exactly 2405001 cents, brokered on both sides."""
    return setup_closed_agreement(
        county_overrides={
            "quota_licenses_total": 100,
            "transfer_fee_bps": 150,
            "protest_window_days": 15,
        },
        brokerage_overrides={
            "commission_rate_bps": 575,
            "dual_agency_policy": "ALLOWED_WITH_DISCLOSURE",
        },
        represents_buyer=True,
        deposit_by_buyer=True,
        application_fee=173250,
    )


def test_release_ledger_sums_to_zero_and_creates_no_cash():
    """+2405001, -277500, -1063750, -1063751: the four signed rows cancel exactly.

    PRD: "The sum of `amount_cents` over an agreement's ledger rows always equals
    that agreement's `escrow_balance_cents`, and equals zero after any settlement
    of any kind."

    PRD: "On success the three bucket figures are written to the agreement and
    three ledger rows are appended **in this pinned order**:
    `RELEASE_COUNTY_FEE`, then `RELEASE_COMMISSION`, then `RELEASE_SELLER`. Each
    carries a negative `amount_cents` and a `balance_after_cents` lower than the
    row before it, so the balance walks down to zero across the three rows."

    PRD: "The waterfall then takes the county fee as bucket one, the commission
    total as bucket two, and leaves `seller_net_cents` as bucket three: the escrow
    balance held at settlement time, less the county fee, less the commission
    total."

    Design: Difficulty/compensating_invariant/escrow_cash_conservation_across_release
    """
    scenario = _closed_dual_agency_transfer()
    settled = settle_escrow(scenario["agreement_id"], "RELEASE", memo="close out")

    assert settled["commission_mode"] == "DUAL_AGENCY"
    assert settled["county_transfer_fee_cents"] == COUNTY_FEE_CENTS
    assert settled["commission_total_cents"] == COMMISSION_CENTS
    assert settled["seller_net_cents"] == SELLER_NET_CENTS
    assert (
        settled["county_transfer_fee_cents"]
        + settled["commission_total_cents"]
        + settled["seller_net_cents"]
        == DEPOSIT_CENTS
    ), "the three buckets must exhaust the deposit exactly"

    rows = ledger_rows(scenario["agreement_id"])
    assert len(rows) == 4
    assert_ledger_entry_types(
        rows,
        ["DEPOSIT", "RELEASE_COUNTY_FEE", "RELEASE_COMMISSION", "RELEASE_SELLER"],
    )
    assert [row["amount_cents"] for row in rows] == [
        DEPOSIT_CENTS,
        -COUNTY_FEE_CENTS,
        -COMMISSION_CENTS,
        -SELLER_NET_CENTS,
    ]
    assert sum(row["amount_cents"] for row in rows) == 0
    assert_ledger_sums_to_balance(rows, settled)


def test_escrow_balance_tracks_the_last_ledger_row_at_every_step():
    """2405001 with one row, 0 with four - the projection never drifts.

    PRD: "Funding appends one ledger row with `entry_type` of `DEPOSIT`, an
    `amount_cents` equal to the positive deposit amount, a `balance_after_cents`
    equal to that same amount, a `memo` carrying the supplied `deposit_reference`,
    and an `occurred_at` of the current logical instant."

    PRD: "The agreement's `escrow_balance_cents` is recomputed to 0, `settled_at`
    is stamped with the current logical instant, and the agreement's `version`
    advances by one."

    PRD: "The sum of `amount_cents` over an agreement's ledger rows always equals
    that agreement's `escrow_balance_cents`, and equals zero after any settlement
    of any kind."

    Design: Difficulty/compensating_invariant/escrow_cash_conservation_across_release
    """
    scenario = _closed_dual_agency_transfer()

    held = read_agreement(scenario["agreement_id"])
    assert held["escrow_status"] == "HELD"
    assert held["escrow_balance_cents"] == DEPOSIT_CENTS
    before = ledger_rows(scenario["agreement_id"])
    assert len(before) == 1
    assert before[0]["balance_after_cents"] == held["escrow_balance_cents"]
    assert_ledger_balance_projection(before)

    settled = settle_escrow(scenario["agreement_id"], "RELEASE", memo="close out")
    assert settled["escrow_status"] == "RELEASED"
    assert settled["escrow_balance_cents"] == 0
    assert_instant_equals(settled["settled_at"], "2026-09-10T00:00:00Z", "settled_at")
    assert settled["version"] == held["version"] + 1

    after = ledger_rows(scenario["agreement_id"])
    assert [row["balance_after_cents"] for row in after] == [
        DEPOSIT_CENTS,
        2127501,
        SELLER_NET_CENTS,
        0,
    ]
    assert after[-1]["balance_after_cents"] == settled["escrow_balance_cents"]
    assert_ledger_balance_projection(after)


def _occupancy_county_overrides():
    return {"quota_licenses_total": 100, "protest_window_days": 15}


def test_escrow_occupancy_returns_to_zero_after_the_refund():
    """0 before execution, 1 while IN_ESCROW, 0 again once the deposit goes back.

    PRD: "Funding touches no county counter whatsoever: the license does not become
    `IN_ESCROW` until execution, so `escrow_committed_count` is unchanged by money
    arriving."

    PRD: "The county's counters are recomputed, so `escrow_committed_count` rises
    by one for a counted license, and the county's `version` advances."

    PRD: "A county's `escrow_committed_count` rises by exactly one when a license
    enters escrow and falls by exactly one when it leaves, so a failed transfer
    returns the county to the count it had before the agreement was executed."

    Design: Difficulty/compensating_invariant/county_escrow_occupancy_conservation_across_refund
    """
    scenario = setup_scenario(
        stage="escrow_held",
        county_overrides=_occupancy_county_overrides(),
        deposit_by_buyer=True,
    )

    funded_county = read_county(scenario["county_id"])
    assert funded_county["escrow_committed_count"] == 0
    assert read_agreement(scenario["agreement_id"])["escrow_balance_cents"] == (
        DEPOSIT_CENTS
    )

    execute_agreement(scenario["agreement_id"], scenario["brokerage_id"])
    committed_county = read_county(scenario["county_id"])
    assert committed_county["escrow_committed_count"] == 1
    assert read_license(scenario["license_id"])["status"] == "IN_ESCROW"

    application = file_application(
        scenario["agreement_id"], 173250, scenario["brokerage_id"]
    )
    accept_review(application["id"])
    set_clock("2026-08-10T00:00:00Z")
    post_notice(application["id"])
    set_clock("2026-09-10T00:00:00Z")
    decided = decide_application(application["id"], "DENIED")
    assert decided["decision"] == "DENIED"

    settled = settle_escrow(scenario["agreement_id"], "REFUND", memo="denied")
    assert settled["escrow_status"] == "REFUNDED"

    released_county = read_county(scenario["county_id"])
    assert released_county["escrow_committed_count"] == 0, (
        "the compensation must restore the occupancy count exactly, with no drift"
    )
    assert released_county["version"] > committed_county["version"]


def test_quota_counted_stays_flat_while_occupancy_unwinds():
    """The licence never leaves the quota, so 1 counted and 99 available throughout.

    PRD: "A county's `quota_licenses_counted` is untouched by the entire
    proceeding, because a license that has been transferred still occupies its
    quota slot — a transfer never frees capacity, which is why the approval cascade
    leaves the counted figure flat while the escrow-committed figure falls."

    PRD: "`quota_available` is `quota_licenses_total` minus that count, floored at
    zero so it is never negative."

    PRD: "It appends exactly one ledger row of `entry_type` `REFUND_BUYER` whose
    `amount_cents` is the negative of the whole held balance and whose
    `balance_after_cents` is 0."

    Design: Difficulty/compensating_invariant/county_escrow_occupancy_conservation_across_refund
    """
    scenario = setup_denied_agreement(
        county_overrides=_occupancy_county_overrides(),
        deposit_by_buyer=True,
        application_fee=173250,
    )

    in_escrow = read_county(scenario["county_id"])
    assert in_escrow["quota_licenses_counted"] == 1
    assert in_escrow["quota_available"] == 99
    assert in_escrow["escrow_committed_count"] == 1

    settled = settle_escrow(scenario["agreement_id"], "REFUND", memo="denied")
    assert settled["escrow_balance_cents"] == 0
    assert settled["agreement_status"] == "TERMINATED"
    assert_settlement_buckets_null(settled)

    unwound = read_county(scenario["county_id"])
    assert unwound["quota_licenses_counted"] == 1
    assert unwound["quota_available"] == 99
    assert unwound["escrow_committed_count"] == 0

    license_row = read_license(scenario["license_id"])
    assert license_row["status"] == "ACTIVE"
    assert license_row["transferred_to_buyer_id"] is None
    assert read_listing(scenario["listing_id"])["status"] == "ACTIVE"
    assert read_disclosure(scenario["disclosure"]["id"])["status"] == "VOID"

    rows = ledger_rows(scenario["agreement_id"])
    assert_ledger_entry_types(rows, ["DEPOSIT", "REFUND_BUYER"])
    assert rows[-1]["amount_cents"] == -DEPOSIT_CENTS
    assert rows[-1]["balance_after_cents"] == 0
