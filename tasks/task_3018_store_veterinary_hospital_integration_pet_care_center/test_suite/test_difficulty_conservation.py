"""Compensating actions that credit a conserved quantity back.

Approving a claim records the risk points it removes, so the claim summary's two
risk figures agree even though the pet's score is unchanged by the approval. The
denial path is the action that actually lowers the pet's score. The cross-sell
claim covers the other ledger: a grant moves the store balance and its matching
redemption returns the balance to where it stood.
"""

import pytest

from test_helpers import (
    CROSS_SELL_CREDIT_RATE,
    create_cross_sell,
    deny_claim,
    fetch_store_cross_sells,
    get_success_data,
    read_pet,
    read_store,
    redeem_cross_sell,
    setup_authorized_prescription,
    setup_incident_under_review,
    approve_claim,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
PHARMACY = TEST_USERS["pharmacy_staff_headers"]


def test_approving_a_claim_records_the_compensating_risk_points(api):
    """The incident records the points it removes while the pet keeps them.

    PRD §3.6: "Approval then pays the claim in full — the `payout_amount_cents`
    becomes equal to the `claim_amount_cents` — and records the compensation on
    the risk side by setting `risk_points_lost` equal to the incident's
    `risk_points`."
    PRD §3.6: "Because the pet's `risk_score` is recomputed as the sum of
    `risk_points` over incidents that are not denied, an approval does not remove
    the incident's points from that sum"
    PRD §3.6: "The incident's `available_claimable_cents` — the claim amount less
    what has been paid — falls to zero on approval"

    Design: Difficulty/compensating_invariant/risk_points_conserved_across_report_begin_and_approval
    """
    world = setup_incident_under_review(
        api, severity="MODERATE", incident_type="PET_INJURY", claim_amount_cents=25000
    )
    incident = world["incident"]
    assert incident["risk_points"] == 25
    assert incident["risk_points_lost"] == 0
    assert read_pet(api, world["pet"]["id"])["risk_score"] == 25

    approved = approve_claim(api, world["store"]["id"], incident)
    assert approved["claim_status"] == "APPROVED"
    assert approved["risk_points_lost"] == approved["risk_points"] == 25
    assert approved["payout_amount_cents"] == 25000
    assert approved["available_claimable_cents"] == 0
    # The pet's score is a sum over non-DENIED incidents, so approval leaves it
    # where the report put it.
    assert read_pet(api, world["pet"]["id"])["risk_score"] == 25


def test_the_claim_summary_reports_the_conserved_pair_and_the_store_index(api):
    """The read exposes both risk figures and the store's own incident index.

    PRD §3.6: "which is the conservation identity the claim summary exposes"
    PRD §3.6: "the store's `incident_risk_index` is recomputed over the store's
    incidents that are still `UNREVIEWED` or `UNDER_REVIEW`."
    PRD §3.6: "The record's own `claim_status` begins `UNREVIEWED`, and its
    `payout_amount_cents`, `risk_points_lost` and `available_claimable_cents` all
    begin at zero."

    Design: Difficulty/compensating_invariant/risk_points_conserved_across_report_begin_and_approval
    """
    world = setup_incident_under_review(
        api, severity="MODERATE", incident_type="PET_INJURY", claim_amount_cents=25000
    )
    store_id = world["store"]["id"]
    incident = world["incident"]

    before = read_store(api, store_id)
    assert before["incident_risk_index"] == 25000

    approved = approve_claim(api, store_id, incident)
    summary = get_success_data(api.get_claim_summary(store_id, incident["id"], ADMIN))
    assert summary["claim_amount_cents"] == 25000
    assert summary["payout_amount_cents"] == 25000
    assert summary["risk_points"] == summary["risk_points_lost"] == 25
    assert summary["available_claimable_cents"] == 0
    # An approved claim is no longer UNREVIEWED or UNDER_REVIEW, so it drops out
    # of the store's incident index.
    assert read_store(api, store_id)["incident_risk_index"] == 0
    assert approved["claim_status"] == "APPROVED"


def test_denying_a_claim_removes_the_incidents_points_from_the_pet(api):
    """Denial is the action that actually falls the pet's risk score.

    PRD §3.6: "Denial is the action that actually removes risk from the pet,
    because a denied incident is excluded from the pet's `risk_score` sum
    entirely: denying recomputes the pet's score without the incident's points,
    leaves `payout_amount_cents` at zero and `available_claimable_cents`
    unchanged, and increments both the incident's and the pet's versions."
    PRD §2.9: "A pet's `risk_score` therefore never falls on its own: it falls
    only when a claim is denied"

    Design: Difficulty/compensating_invariant/risk_points_conserved_across_report_begin_and_approval
    """
    world = setup_incident_under_review(
        api, severity="SEVERE", incident_type="BITE", claim_amount_cents=25000
    )
    store_id = world["store"]["id"]
    incident = world["incident"]
    assert read_pet(api, world["pet"]["id"])["risk_score"] == 40

    denied = deny_claim(api, store_id, incident)
    assert denied["claim_status"] == "DENIED"
    assert denied["payout_amount_cents"] == 0
    assert denied["available_claimable_cents"] == 25000
    pet = read_pet(api, world["pet"]["id"])
    assert pet["risk_score"] == 0
    assert read_store(api, store_id)["incident_risk_index"] == 0


def test_granting_and_redeeming_a_cross_sell_leaves_the_store_balance_where_it_started(api):
    """The grant moves the store balance and the redemption puts it back.

    PRD §3.5: "its `credit_granted_cents` is that gross value multiplied by the
    cross-sell credit rate of 0.10, rounded half-up to two decimal places."
    PRD §2.9: "A store's `cross_sell_credit_balance_cents` equals the credit
    granted across all of that store's cross-sells whose status is `PENDING` or
    `REDEEMED`, minus the credit redeemed across all of that store's cross-sells
    whose status is `REDEEMED`."
    PRD §2.9: "a grant immediately followed by its redemption leaves the balance
    exactly where it stood before the grant"

    Design: Difficulty/compensating_invariant/cross_sell_credit_conserved_across_grant_and_redeem
    """
    world = setup_authorized_prescription(
        api, item_type="TREATMENT", unit_price_cents=3000, quantity=2
    )
    store_id = world["store"]["id"]
    pet = read_pet(api, world["pet"]["id"])
    authorization = world["prescription"]
    gross = authorization["price_at_authorization_cents"]

    before = read_store(api, store_id)
    cross_sell = create_cross_sell(api, store_id, authorization["id"], pet["id"], pet["version"])

    expected_credit = round(gross * CROSS_SELL_CREDIT_RATE, 2)
    assert cross_sell["gross_cents"] == gross
    assert cross_sell["credit_granted_cents"] == expected_credit
    granted_state = read_store(api, store_id)
    assert granted_state["cross_sell_credit_balance_cents"] == expected_credit

    redeem_cross_sell(api, store_id, cross_sell, expected_credit)
    after = read_store(api, store_id)
    assert after["cross_sell_credit_balance_cents"] == before["cross_sell_credit_balance_cents"] == 0


def test_the_cross_sell_ledger_identity_holds_over_the_stores_cross_sells(api):
    """The balance equals granted minus redeemed across the store's rows.

    PRD §2.9: "The cross-sell credit ledger is the first. A store's
    `cross_sell_credit_balance_cents` equals the credit granted across all of
    that store's cross-sells whose status is `PENDING` or `REDEEMED`, minus the
    credit redeemed across all of that store's cross-sells whose status is
    `REDEEMED`."
    PRD §3.5: "Redeeming the credit is a separate act carrying
    `expected_cross_sell_version` and a `credit_redeemed_cents` amount; it moves
    the cross-sell to `REDEEMED` and recomputes the store balance."

    Design: Difficulty/compensating_invariant/cross_sell_credit_conserved_across_grant_and_redeem
    """
    world = setup_authorized_prescription(
        api, item_type="TREATMENT", unit_price_cents=3000, quantity=2
    )
    store_id = world["store"]["id"]
    pet = read_pet(api, world["pet"]["id"])
    authorization = world["prescription"]

    first = create_cross_sell(api, store_id, authorization["id"], pet["id"], pet["version"])
    second = create_cross_sell(
        api, store_id, authorization["id"], pet["id"], pet["version"], sku="SKU-TEST-02"
    )
    redeem_cross_sell(api, store_id, second, second["credit_granted_cents"])

    store = read_store(api, store_id)
    rows = fetch_store_cross_sells(api, store_id)
    granted = sum(
        r["credit_granted_cents"] for r in rows if r["status"] in ("PENDING", "REDEEMED")
    )
    redeemed = sum(r["credit_redeemed_cents"] for r in rows if r["status"] == "REDEEMED")
    assert store["cross_sell_credit_balance_cents"] == pytest.approx(granted - redeemed, abs=0.01)
    assert store["cross_sell_credit_balance_cents"] == first["credit_granted_cents"]
    assert len(rows) == 2