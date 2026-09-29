"""The two multi-hop cascades: the five-hop close on approval and the four-hop
unwind on refund. Every hop's precondition reads the field the hop before it
wrote, so none of them is a direct effect of the triggering request.
"""

from test_helpers import (
    answer_protest,
    assert_instant_equals,
    assert_ledger_balance_projection,
    decide_application,
    file_protest,
    ledger_rows,
    read_agreement,
    read_county,
    read_disclosure,
    read_license,
    read_listing,
    read_protest,
    set_clock,
    settle_escrow,
    setup_denied_agreement,
    setup_scenario,
)

DEPOSIT_CENTS = 2405001
PURCHASE_PRICE_CENTS = 18500010


def test_an_approval_from_protested_runs_all_five_closing_hops():
    """One decision call moves the application, license, listing, agreement and
    protest in a single chain.

    PRD: "An approval writes `decision` of `APPROVED` and `decided_at` of the
    current logical instant, then runs the five-hop closing cascade of section 2.8
    in full."

    PRD: "The license moves `IN_ESCROW → TRANSFERRED`; its
    `transferred_to_buyer_id` is set to the agreement's `buyer_id`, and its
    `last_transfer_price_cents` is overwritten with the agreement's
    `purchase_price_cents`, which is what makes the license a comparable for
    future comparable-sales valuations in its county and class."

    PRD: "Every protest on the application still `OPEN` or `RESPONDED` moves to
    `OVERRULED`."

    PRD: "The county's counters are recomputed: `escrow_committed_count` falls by
    one because the license left `IN_ESCROW`, while `quota_licenses_counted` is
    unchanged because a `TRANSFERRED` license still occupies its quota slot."

    The notice is posted on 2026-08-10 and one protest is filed and answered the
    same day, so the application sits in `PROTESTED` with a `RESPONDED` protest;
    the decision on 2026-09-10 is strictly past the 2026-09-09 posting end.

    Design: Difficulty/transitive_cascade/approved_decision_five_hop_close
    """
    scenario = setup_scenario(
        stage="application_posted",
        county_overrides={
            "quota_licenses_total": 100,
            "posting_period_days": 30,
            "protest_window_days": 15,
        },
        represents_buyer=True,
        deposit_by_buyer=True,
        application_fee=173250,
        post_notice_at="2026-08-10T00:00:00Z",
    )
    protest = file_protest(
        scenario["application_id"],
        protestant_name="Neighborhood Council",
        grounds="UNDUE_CONCENTRATION",
    )
    answer_protest(protest["id"], scenario["brokerage_id"], "resp-doc-1")

    set_clock("2026-09-10T00:00:00Z")
    decided = decide_application(
        scenario["application_id"], "APPROVED", decision_note="no adverse finding"
    )

    assert decided["status"] == "APPROVED"
    assert decided["decision"] == "APPROVED"
    assert_instant_equals(decided["decided_at"], "2026-09-10T00:00:00Z", "decided_at")

    license_row = read_license(scenario["license_id"])
    assert license_row["status"] == "TRANSFERRED"
    assert license_row["transferred_to_buyer_id"] == scenario["buyer_id"]
    assert license_row["last_transfer_price_cents"] == PURCHASE_PRICE_CENTS

    assert read_listing(scenario["listing_id"])["status"] == "SOLD"

    agreement = read_agreement(scenario["agreement_id"])
    assert agreement["agreement_status"] == "CLOSED"
    assert agreement["escrow_status"] == "HELD"
    assert agreement["escrow_balance_cents"] == DEPOSIT_CENTS

    assert read_protest(protest["id"])["status"] == "OVERRULED"

    county = read_county(scenario["county_id"])
    assert county["escrow_committed_count"] == 0
    assert county["quota_licenses_counted"] == 1


def test_the_closing_cascade_moves_no_money_of_its_own():
    """Approval leaves the ledger and the settlement buckets untouched.

    PRD: "The agreement moves `EXECUTED → CLOSED` while its `escrow_status`
    deliberately stays `HELD`, because approval does not move money."

    PRD: "Its `escrow_balance_cents` is 0, and `commission_mode`,
    `commission_total_cents`, `county_transfer_fee_cents`, `seller_net_cents`,
    `executed_at`, `settled_at` and `termination_reason` are all null."

    Design: Difficulty/transitive_cascade/approved_decision_five_hop_close
    """
    scenario = setup_scenario(
        stage="application_posted",
        county_overrides={
            "quota_licenses_total": 100,
            "posting_period_days": 30,
            "protest_window_days": 15,
        },
        represents_buyer=True,
        deposit_by_buyer=True,
        application_fee=173250,
        post_notice_at="2026-08-10T00:00:00Z",
    )
    set_clock("2026-09-10T00:00:00Z")
    decide_application(scenario["application_id"], "APPROVED")

    agreement = read_agreement(scenario["agreement_id"])
    assert agreement["escrow_status"] == "HELD"
    assert agreement["escrow_balance_cents"] == DEPOSIT_CENTS
    assert agreement["commission_total_cents"] is None
    assert agreement["county_transfer_fee_cents"] is None
    assert agreement["seller_net_cents"] is None
    assert agreement["settled_at"] is None

    rows = ledger_rows(scenario["agreement_id"])
    assert len(rows) == 1
    assert rows[0]["entry_type"] == "DEPOSIT"
    assert rows[0]["balance_after_cents"] == DEPOSIT_CENTS


def _denied_transfer():
    """A DENIED application over a still-held escrow, no protest ever filed."""
    return setup_denied_agreement(
        county_overrides={"quota_licenses_total": 100, "protest_window_days": 15},
        represents_buyer=True,
        deposit_by_buyer=True,
        application_fee=173250,
    )


def test_a_refund_unwinds_the_agreement_licence_and_listing_in_four_hops():
    """The compensating cascade puts every record back where it started.

    PRD: "Both the refund and the forfeiture drive `escrow_balance_cents` to 0,
    stamp `settled_at` with the current logical instant, advance the agreement's
    `version`, and then run the four-hop compensating cascade of section 2.8."

    PRD: "The contract dimension moves `EXECUTED → TERMINATED`, and
    `termination_reason` is written by the cascade rather than by a client: it
    reads `ESCROW_REFUNDED` after a refund and `ESCROW_FORFEITED` after a
    forfeiture."

    PRD: "Every agency disclosure on the agreement that is `PENDING_ACKS` or
    `FULLY_ACKED` moves to `VOID`."

    PRD: "Finally the listing returns `UNDER_CONTRACT → ACTIVE`, its
    `open_offer_count` is recomputed over whatever draft agreements remain on it,
    and its `version` advances — so a failed transfer puts the license back on the
    market rather than stranding it."

    With `safekeeping_expires_at` null the license takes the `ACTIVE` branch, and
    the sole draft offer on the listing has itself been terminated, so the
    recomputed open-offer count is zero.

    Design: Difficulty/transitive_cascade/refund_settlement_four_hop_unwind
    """
    scenario = _denied_transfer()
    refunded = settle_escrow(
        scenario["agreement_id"], "REFUND", memo="transfer denied"
    )

    assert refunded["escrow_status"] == "REFUNDED"
    assert refunded["escrow_balance_cents"] == 0
    assert refunded["agreement_status"] == "TERMINATED"
    assert refunded["termination_reason"] == "ESCROW_REFUNDED"

    license_row = read_license(scenario["license_id"])
    assert license_row["status"] == "ACTIVE"
    assert license_row["transferred_to_buyer_id"] is None

    listing = read_listing(scenario["listing_id"])
    assert listing["status"] == "ACTIVE"
    assert listing["open_offer_count"] == 0

    assert read_disclosure(scenario["disclosure_id"])["status"] == "VOID"

    county = read_county(scenario["county_id"])
    assert county["escrow_committed_count"] == 0
    assert county["quota_licenses_counted"] == 1


def test_a_refund_earns_no_commission_and_creates_no_comparable():
    """The unwind writes exactly one negative ledger row and no bucket figures.

    PRD: "It appends exactly one ledger row of `entry_type` `REFUND_BUYER` whose
    `amount_cents` is the negative of the whole held balance and whose
    `balance_after_cents` is 0."

    PRD: "The three settlement buckets — `county_transfer_fee_cents`,
    `commission_total_cents` and `seller_net_cents` — all stay null, because no
    commission is ever earned on a failed transfer."

    PRD: "No row is ever mutated or deleted, so the projection is a pure replay,
    and a `memo` on every row carries a human-readable label of the movement."

    A license that never transferred keeps a null `last_transfer_price_cents`, so
    a failed transfer never becomes a comparable for a future valuation.

    Design: Difficulty/transitive_cascade/refund_settlement_four_hop_unwind
    """
    scenario = _denied_transfer()
    settle_escrow(scenario["agreement_id"], "REFUND", memo="transfer denied")

    agreement = read_agreement(scenario["agreement_id"])
    assert agreement["commission_total_cents"] is None
    assert agreement["county_transfer_fee_cents"] is None
    assert agreement["seller_net_cents"] is None

    rows = ledger_rows(scenario["agreement_id"])
    assert len(rows) == 2
    assert [row["entry_type"] for row in rows] == ["DEPOSIT", "REFUND_BUYER"]
    assert rows[0]["amount_cents"] == DEPOSIT_CENTS
    assert rows[1]["amount_cents"] == -DEPOSIT_CENTS
    assert rows[1]["balance_after_cents"] == 0
    assert_ledger_balance_projection(rows)

    assert read_license(scenario["license_id"])["last_transfer_price_cents"] is None
