"""Executing an approved early release: the four-hop cascade and funds conservation."""

from test_helpers import (
    TEST_USERS,
    assert_account_balances,
    decide_override_review,
    open_case,
    read_account,
    read_case,
    read_check_hold,
    settle_item,
    setup_approved_review,
    setup_submitted_review,
    validate_success,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]


def _submitted_review_with_open_mule_case(**overrides):
    """Submitted full-amount review plus an OPENED MULE case on the same account."""
    scenario = setup_submitted_review(**overrides)
    case = open_case(scenario["account_id"], "MULE")
    scenario.update({"case": case, "case_id": case["id"]})
    return scenario


# ===========================================================================
# The four-hop execution cascade
# ===========================================================================
def test_execution_moves_the_review_the_hold_and_the_account_balances(api, analyst_headers):
    """PRD §3.4: "- **Hop 1.** The review transitions `APPROVED → EXECUTED` and
    `executed_at` is stamped from the logical clock."
    PRD §3.4: "- **Hop 2.** Because the review executed, the referenced hold's
    `held_amount_cents` is reduced by `requested_release_cents`. If that reduction
    brings it to exactly 0, the hold transitions `ACTIVE → OVERRIDDEN` with
    `released_at` stamped."
    PRD §3.4: "- **Hop 3.** Because that hold's `held_amount_cents` changed, the
    owning account's `available_balance_cents` rises by `requested_release_cents`
    and its `held_amount_cents` is recomputed. `ledger_balance_cents` is unchanged
    — early release moves money between the held and available buckets, it does not
    create any."

    Design: Difficulty/transitive_cascade/override_execute_cascades_review_then_hold_then_account_then_fraud_case
    """
    scenario = _submitted_review_with_open_mule_case(
        legal_name="Teodora Vasquez", tin_last4="5150", kyc_tier="TIER_2", watchlist_hit=False
    )
    decide_override_review(scenario["review_id"], "APPROVE", "Within delegated authority")

    executed = validate_success(
        api.execute_override_review(scenario["review_id"], SUPERVISOR)
    )
    assert executed["status"] == "EXECUTED", "Hop 1 moves the review APPROVED -> EXECUTED"

    hold = read_check_hold(scenario["hold_id"], analyst_headers)
    assert hold["status"] == "OVERRIDDEN", "Hop 2 empties the hold, so it leaves ACTIVE"
    assert hold["held_amount_cents"] == 0

    account = read_account(scenario["account_id"], analyst_headers)
    assert_account_balances(account, ledger=30000, available=30000, held=0)


def test_execution_recomputes_the_open_fraud_cases_exposure(api, analyst_headers):
    """PRD §3.7: "Its `exposure_at_risk_cents` is computed at once from the primary
    account's `held_amount_cents`, and the primary account transitions
    `ACTIVE → RESTRICTED`."
    PRD §3.4: "- **Hop 4.** Because the account's held total changed, every fraud
    case in `OPENED` or `INVESTIGATING` status whose primary account is this
    account, or whose `cycle_account_ids` contains it, has
    `exposure_at_risk_cents` recomputed."
    PRD §2.9: "The first is depositor funds: `available_balance_cents` plus
    `held_amount_cents` equals `ledger_balance_cents` at all times."

    Design: Difficulty/transitive_cascade/override_execute_cascades_review_then_hold_then_account_then_fraud_case
    """
    scenario = _submitted_review_with_open_mule_case(
        legal_name="Teodora Vasquez", tin_last4="5150", kyc_tier="TIER_2", watchlist_hit=False
    )
    assert scenario["case"]["exposure_at_risk_cents"] == 7500, (
        "The case is opened against an account holding 7500 cents"
    )

    decide_override_review(scenario["review_id"], "APPROVE", "Within delegated authority")
    validate_success(api.execute_override_review(scenario["review_id"], SUPERVISOR))

    case = read_case(scenario["case_id"], analyst_headers)
    assert case["exposure_at_risk_cents"] == 0, (
        f"The release emptied the account's held total, so the case exposure falls to 0, "
        f"got {case['exposure_at_risk_cents']}"
    )

    account = read_account(scenario["account_id"], analyst_headers)
    assert (
        account["available_balance_cents"] + account["held_amount_cents"]
        == account["ledger_balance_cents"]
    )


# ===========================================================================
# Partial release: the hold stays ACTIVE with a smaller balance
# ===========================================================================
def test_partial_release_leaves_the_hold_active_with_a_reduced_amount(api, analyst_headers):
    """PRD §3.4: "- **Hop 2.** Because the review executed, the referenced hold's
    `held_amount_cents` is reduced by `requested_release_cents`. If that reduction
    brings it to exactly 0, the hold transitions `ACTIVE → OVERRIDDEN` with
    `released_at` stamped. If the requested amount was strictly less than the
    hold's balance, the hold stays `ACTIVE` with a smaller `held_amount_cents`, and
    its `hold_type` and `hold_release_at` are left untouched."
    PRD §3.4: "- **Hop 3.** Because that hold's `held_amount_cents` changed, the
    owning account's `available_balance_cents` rises by `requested_release_cents`
    and its `held_amount_cents` is recomputed."

    Design: Corner/state_machines/partial_override_release_leaves_the_hold_active_with_a_reduced_amount
    """
    scenario = setup_approved_review(
        requested_release_cents=3000,
        legal_name="Partial Release Depositor", tin_last4="0015",
    )

    executed = validate_success(
        api.execute_override_review(scenario["review_id"], SUPERVISOR)
    )
    assert executed["status"] == "EXECUTED"

    hold = read_check_hold(scenario["hold_id"], analyst_headers)
    assert hold["status"] == "ACTIVE", "3000 is strictly less than 7500, so the hold survives"
    assert hold["held_amount_cents"] == 4500
    assert hold["released_at"] is None

    account = read_account(scenario["account_id"], analyst_headers)
    assert_account_balances(account, ledger=30000, available=25500, held=4500)


# ===========================================================================
# The compensating sequence: deposit, early release, return
# ===========================================================================
def test_early_release_only_shifts_money_between_the_held_and_available_buckets(
    api, analyst_headers
):
    """PRD §2.9: "The first is depositor funds: `available_balance_cents` plus
    `held_amount_cents` equals `ledger_balance_cents` at all times. This must hold
    as a postcondition of every operation that touches balances — taking a deposit,
    settling an item, executing an early release, booking a charge-off, and
    reversing a charge-off."
    PRD §3.4: "- **Hop 3.** Because that hold's `held_amount_cents` changed, the
    owning account's `available_balance_cents` rises by `requested_release_cents`
    and its `held_amount_cents` is recomputed. `ledger_balance_cents` is unchanged
    — early release moves money between the held and available buckets, it does not
    create any."

    Design: Difficulty/compensating_invariant/deposit_then_override_release_then_return_restores_depositor_ledger_exactly
    """
    scenario = setup_approved_review(
        legal_name="Lachlan Whitcombe", tin_last4="1919", kyc_tier="TIER_2", watchlist_hit=False
    )
    before = read_account(scenario["account_id"], analyst_headers)
    assert_account_balances(before, ledger=30000, available=22500, held=7500)

    validate_success(api.execute_override_review(scenario["review_id"], SUPERVISOR))

    mid = read_account(scenario["account_id"], analyst_headers)
    assert_account_balances(mid, ledger=30000, available=30000, held=0)


def test_deposit_release_then_return_restores_the_pre_deposit_ledger_exactly(api, analyst_headers):
    """PRD §2.9: "It follows that a compensating sequence returns the ledger to
    where it started: taking a deposit, executing an early release against its
    hold, and then settling that item as returned leaves `ledger_balance_cents` at
    exactly its pre-deposit value."
    PRD §3.3: "A **returned** item transitions `PENDING → RETURNED` and records its
    `return_reason`. Every hold on that item still in `ACTIVE` transitions
    `ACTIVE → CHARGED_BACK` with `released_at` stamped. The depositing account's
    `ledger_balance_cents` falls by the item's `amount_cents`, and its
    `available_balance_cents` falls by the item's `amount_cents` less the total
    `held_amount_cents` of the holds just charged back — which is exactly the
    portion the depositor could already spend, and which may drive
    `available_balance_cents` negative when an early release has already been
    executed against that hold."

    Design: Difficulty/compensating_invariant/deposit_then_override_release_then_return_restores_depositor_ledger_exactly
    """
    scenario = setup_approved_review(
        legal_name="Lachlan Whitcombe", tin_last4="1919", kyc_tier="TIER_2", watchlist_hit=False
    )
    validate_success(api.execute_override_review(scenario["review_id"], SUPERVISOR))

    settled = settle_item(scenario["item_id"], "RETURNED", "UNCOLLECTED_FUNDS")
    assert settled["status"] == "RETURNED"
    assert settled["return_reason"] == "UNCOLLECTED_FUNDS"

    final = read_account(scenario["account_id"], analyst_headers)
    assert_account_balances(final, ledger=0, available=0, held=0)

    hold = read_check_hold(scenario["hold_id"], analyst_headers)
    assert hold["status"] == "OVERRIDDEN", (
        "The hold had already left ACTIVE, so the return does not charge it back"
    )
    assert hold["held_amount_cents"] == 0
