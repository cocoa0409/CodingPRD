"""Depth tests for compensating invariants: the per-applicant upfront ledger
(paid == held + refunded + forfeited) across withdrawal and disqualification,
and per-product block supply (available + live licenses == supply_per_area)
across grant and payment-deadline cancellation."""
from test_helpers import (
    GRANT_DAY_ISO,
    UPFRONT_10M_UNITS,
    UPFRONT_12_5M_UNITS,
    ApplicantReviewAction,
    assert_upfront_ledger_conserved,
    begin_quiet_period,
    close_round,
    complete_assignment,
    create_open_auction,
    file_assignment_bid,
    get_applicant,
    get_auction,
    get_supply_entry,
    list_licenses,
    pay_upfront,
    place_bid,
    qualify_applicant,
    register_applicant,
    review_applicant,
    set_clock,
    setup_clock_active_auction,
    start_clock,
    withdraw_applicant,
)

LIVE_LICENSE_STATES = {"PENDING_PAYMENT", "ACTIVE", "RENEWAL_REVIEW"}


def test_upfront_ledger_conserved_across_refund_forfeit(api):
    """PRD §3.2: "The ledger is conservative at every step, so
    `upfront_paid_cents` always equals the sum of `upfront_held_cents`,
    `upfront_refunded_cents`, and `upfront_forfeited_cents`."
    PRD §3.3: "Withdrawal moves the applicant to `WITHDRAWN` and refunds the
    held deposit exactly as rejection does."
    PRD §3.3: "The applicant's entire held deposit is then forfeit —
    `upfront_held_cents` moves into `upfront_forfeited_cents` — and the
    auction's `forfeited_deposits_cents` grows by the forfeited amount."

    Design: Difficulty/compensating_invariant/upfront_ledger_conserved_across_refund_forfeit
    """
    ctx = create_open_auction(area_codes=("PEA001",), block_categories=("CATEGORY_A",))
    auction = ctx["auction"]

    w = register_applicant(auction["id"], legal_name="W Withdrawer")
    w = pay_upfront(w["id"], UPFRONT_12_5M_UNITS)
    k = register_applicant(auction["id"], legal_name="K Colluder")
    k = pay_upfront(k["id"], UPFRONT_10M_UNITS)

    # Compensating action 1: withdrawal while APPLICATION_OPEN moves
    # held -> refunded.
    withdraw_applicant(w["id"])

    # Compensating action 2: disqualification during CLOCK_ACTIVE moves
    # held -> forfeited.
    k = qualify_applicant(k["id"])
    begin_quiet_period(auction["id"], auction["application_deadline"])
    start_clock(auction["id"])
    review_applicant(k["id"], ApplicantReviewAction.DISQUALIFY)

    w_after = get_applicant(w["id"])
    assert w_after["status"] == "WITHDRAWN"
    assert w_after["upfront_paid_cents"] == UPFRONT_12_5M_UNITS
    assert w_after["upfront_held_cents"] == 0
    assert w_after["upfront_refunded_cents"] == UPFRONT_12_5M_UNITS
    assert w_after["upfront_forfeited_cents"] == 0
    assert_upfront_ledger_conserved(w_after)

    k_after = get_applicant(k["id"])
    assert k_after["status"] == "DISQUALIFIED"
    assert k_after["upfront_paid_cents"] == UPFRONT_10M_UNITS
    assert k_after["upfront_held_cents"] == 0
    assert k_after["upfront_refunded_cents"] == 0
    assert k_after["upfront_forfeited_cents"] == UPFRONT_10M_UNITS
    assert_upfront_ledger_conserved(k_after)

    assert get_auction(auction["id"])["forfeited_deposits_cents"] == UPFRONT_10M_UNITS


def test_block_supply_conserved_across_grant_and_termination(api):
    """PRD §3.4: "It initializes the auction's `available_supply`, an array of
    (`area_code`, `category`, `available`) entries in which every product's
    `available` starts at the block's `supply_per_area`."
    PRD §3.6: "Completion also marks every winner's assignment bid
    `SUBMITTED → APPLIED` — `APPLIED` is terminal for the assignment bid —
    decrements each product's `available_supply` entry by the number of
    licenses created in it, and moves the auction to `CLOSED`, its terminal
    state."
    PRD §3.6: "Completion mints one license per won unit, in
    `PENDING_PAYMENT` status."
    PRD §3.7: "If the logical clock advances past a license's
    `payment_deadline` while it is still `PENDING_PAYMENT`, the deadline
    sweep cancels it, and the cancellation cascades in two hops: first, the
    holder's remaining held deposit is forfeit — the holder applicant's
    `upfront_held_cents` moves into its `upfront_forfeited_cents`; second,
    that forfeiture itself adds the forfeited amount to the auction's
    `forfeited_deposits_cents`. The product's `available_supply` entry then
    increases by 1, returning the spectrum to inventory."
    PRD §3.6: "Each license's `payment_deadline` is set to the logical
    instant of its creation plus 30 days".

    Design: Difficulty/compensating_invariant/block_supply_conserved_across_grant_and_termination
    """
    ctx = setup_clock_active_auction(
        area_codes=("PEA002",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[{"legal_name": "Winner One LLC"}],
    )
    w1 = ctx["applicants"][0]
    auction_id = ctx["auction"]["id"]

    def live_license_count():
        return sum(
            1
            for lic in list_licenses(auction_id=auction_id)
            if lic["status"] in LIVE_LICENSE_STATES
        )

    # At START_CLOCK the product starts at supply_per_area == 2.
    a0 = get_auction(auction_id)
    assert get_supply_entry(a0, "PEA002", "CATEGORY_A")["available"] == 2
    assert get_supply_entry(a0, "PEA002", "CATEGORY_A")["available"] + live_license_count() == 2

    # Winning qty 2 mints two PENDING_PAYMENT licenses: supply 2 -> 0.
    r1 = ctx["round"]
    place_bid(r1["id"], w1["id"], "PEA002", "CATEGORY_A", 2)
    close_round(r1["id"])
    file_assignment_bid(auction_id, w1["id"], "PEA002", "CATEGORY_A", 0)
    complete_assignment(auction_id)

    # 2026-10-01 is before the payment deadline: nothing cancels yet.
    set_clock(GRANT_DAY_ISO)
    lics = list_licenses(auction_id=auction_id)
    assert len(lics) == 2
    for lic in lics:
        assert lic["status"] == "PENDING_PAYMENT"
        # Created while the clock read 2026-09-16 -> deadline +30 days.
        assert lic["payment_deadline"] == "2026-10-16T00:00:00Z"
    a1 = get_auction(auction_id)
    assert get_supply_entry(a1, "PEA002", "CATEGORY_A")["available"] == 0
    assert get_supply_entry(a1, "PEA002", "CATEGORY_A")["available"] + live_license_count() == 2

    # 2026-11-01 is past the 2026-10-16 deadline: the sweep cancels both
    # licenses and the compensating cancellations return supply 0 -> 2.
    set_clock("2026-11-01T00:00:00Z")
    a2 = get_auction(auction_id)
    assert get_supply_entry(a2, "PEA002", "CATEGORY_A")["available"] == 2
    assert get_supply_entry(a2, "PEA002", "CATEGORY_A")["available"] + live_license_count() == 2
    assert a2["forfeited_deposits_cents"] == UPFRONT_10M_UNITS

    for lic in list_licenses(auction_id=auction_id):
        assert lic["status"] == "CANCELLED"
    w1_after = get_applicant(w1["id"])
    assert w1_after["upfront_held_cents"] == 0
    assert w1_after["upfront_forfeited_cents"] == UPFRONT_10M_UNITS
    assert_upfront_ledger_conserved(w1_after)
