"""Allocating a corporate pool and recalling it, cent for cent.

Two eligible operators with weights 2 and 1 split 100000 cents into 66667 and 33333 after
the one-cent remainder waterfall. The recall must reproduce that same uneven split exactly,
or the pool comes back short.
"""

from test_helpers import (
    allocate_corporate_account,
    assert_corporate_pool_conserved,
    create_corporate_account,
    create_member,
    fund_corporate_account,
    read_corporate_account,
    read_franchisee,
    recall_corporate_allocation,
    setup_two_franchise_clubs,
    sign_active_agreement,
)


def _funded_account_across_two_operators() -> dict:
    """Three enrolled memberships — two at the first operator's club, one at the second's —
    and a pool of 100000 cents waiting to be distributed."""
    setup = setup_two_franchise_clubs(
        first={
            "legal_name": "Copperfield Fitness LLC",
            "contact_email": "ops@copperfieldfit.example",
            "club_name": "Copperfield Club",
            "national_account_eligible": True,
        },
        second={
            "legal_name": "Silverbrook Fitness LLC",
            "contact_email": "ops@silverbrookfit.example",
            "club_name": "Silverbrook Club",
            "center_lat": 36.0,
            "center_lng": -120.0,
            "national_account_eligible": True,
        },
    )
    account = create_corporate_account(
        name="Atlas Logistics National Account",
        corporate_credit_pct=0.045,
        allocation_method="USAGE_SHARE",
    )
    first_club = setup["first"]["club"]["id"]
    second_club = setup["second"]["club"]["id"]
    agreements = []
    for club_id, full_name, email in [
        (first_club, "Yusuf Adeyemi", "yusuf.adeyemi@example.com"),
        (first_club, "Liv Andersen", "liv.andersen@example.com"),
        (second_club, "Ravi Sundaram", "ravi.sundaram@example.com"),
    ]:
        member = create_member(club_id, full_name=full_name, email=email)
        agreements.append(
            sign_active_agreement(
                member["id"],
                club_id,
                setup["plan_template"]["id"],
                multi_club_access=False,
                corporate_account_id=account["id"],
            )
        )
    setup["account"] = fund_corporate_account(account["id"], 100000)
    setup["agreements"] = agreements
    return setup


def _account_after_allocation() -> dict:
    setup = _funded_account_across_two_operators()
    setup["allocation"] = allocate_corporate_account(
        setup["account"]["id"], note="August subsidy distribution"
    )
    return setup


def test_enrolment_credits_each_membership_and_funding_fills_the_pool():
    """The 4.5 percent credit is rounded on its own to 203 cents, so each enrolled membership
    is priced at 4297, and the wire adds 100000 cents to both pool figures.

    PRD 3.8: "Funding wires subsidy money in: a funding call carries an `amount_cents` that
    increases both `pool_balance_cents` and `lifetime_funded_cents` by that amount and
    increments the account's `version`."

    Design: Difficulty/compensating_invariant/corporate_allocate_then_recall_conserves_lifetime_funded_total
    """
    setup = _funded_account_across_two_operators()

    for agreement in setup["agreements"]:
        assert agreement["corporate_credit_cents"] == 203
        assert agreement["effective_monthly_dues_cents"] == 4297
    account = read_corporate_account(setup["account"]["id"])
    assert account["pool_balance_cents"] == 100000
    assert account["allocated_cents"] == 0
    assert account["lifetime_funded_cents"] == 100000
    assert account["enrolled_agreement_count"] == 3


def test_the_remainder_waterfall_splits_the_pool_two_to_one_without_losing_a_cent():
    """Base shares of 66666 and 33333 leave one cent over, which goes to the heavier weight,
    so the two shares sum to the pool exactly.

    PRD 3.8: "That remainder is then distributed one cent at a time, in a fully deterministic
    order: eligible franchisees are sorted by descending weight, with ascending `created_at`
    breaking ties, and the first however-many franchisees in that order each receive one extra
    cent."

    Design: Difficulty/compensating_invariant/corporate_allocate_then_recall_conserves_lifetime_funded_total
    """
    setup = _account_after_allocation()

    heavier = read_franchisee(setup["first"]["franchisee"]["id"])
    lighter = read_franchisee(setup["second"]["franchisee"]["id"])
    assert heavier["corporate_allocation_cents"] == 66667
    assert lighter["corporate_allocation_cents"] == 33333
    assert heavier["corporate_allocation_cents"] + lighter["corporate_allocation_cents"] == 100000


def test_allocation_empties_the_pool_and_leaves_the_lifetime_total_alone():
    """The whole undistributed pool moves into `allocated_cents`, and the monotonic lifetime
    figure does not move at all.

    PRD 2.8: "Second, corporate account funding: for every `CorporateAccount`,
    `pool_balance_cents` plus `allocated_cents` always equals `lifetime_funded_cents`, where
    `lifetime_funded_cents` is monotonic and never decreases."

    Design: Difficulty/compensating_invariant/corporate_allocate_then_recall_conserves_lifetime_funded_total
    """
    setup = _account_after_allocation()

    account = read_corporate_account(setup["account"]["id"])
    assert account["pool_balance_cents"] == 0
    assert account["allocated_cents"] == 100000
    assert account["lifetime_funded_cents"] == 100000
    assert_corporate_pool_conserved(account)


def test_the_recall_re_derives_the_uneven_shares_and_zeroes_both_operators():
    """The inverse recomputes the same 66667 and 33333 it paid out, so neither operator is left
    holding a cent.

    PRD 3.8: "The allocation is recomputed to derive the precise share each franchisee
    received, every affected franchisee's `corporate_allocation_cents` is decreased by exactly
    that share, `pool_balance_cents` increases by `allocated_cents`, `allocated_cents` returns
    to 0, and the account's `version` increments — restoring `pool_balance_cents` plus
    `allocated_cents` to equal `lifetime_funded_cents`."

    Design: Difficulty/compensating_invariant/corporate_allocate_then_recall_conserves_lifetime_funded_total
    """
    setup = _account_after_allocation()
    recall_corporate_allocation(
        setup["account"]["id"], reason="Corporate customer restated its August headcount"
    )

    assert read_franchisee(setup["first"]["franchisee"]["id"])["corporate_allocation_cents"] == 0
    assert read_franchisee(setup["second"]["franchisee"]["id"])["corporate_allocation_cents"] == 0
    account = read_corporate_account(setup["account"]["id"])
    assert account["allocated_cents"] == 0
    assert account["pool_balance_cents"] == 100000
    assert account["lifetime_funded_cents"] == 100000
    assert_corporate_pool_conserved(account)


def test_the_round_trip_never_touches_the_membership_count_or_the_account_status():
    """Enrolment is a count of memberships rather than money, so a full allocate-and-recall
    cycle leaves it and the account's standing exactly as they were.

    PRD 3.8: "The account is created `ACTIVE` with `pool_balance_cents`, `allocated_cents`,
    `lifetime_funded_cents` and `enrolled_agreement_count` all at 0."

    Design: Difficulty/compensating_invariant/corporate_allocate_then_recall_conserves_lifetime_funded_total
    """
    setup = _account_after_allocation()
    recall_corporate_allocation(setup["account"]["id"])

    account = read_corporate_account(setup["account"]["id"])
    assert account["enrolled_agreement_count"] == 3
    assert account["status"] == "ACTIVE"
    assert account["corporate_credit_pct"] == 0.045
    assert account["allocation_method"] == "USAGE_SHARE"
