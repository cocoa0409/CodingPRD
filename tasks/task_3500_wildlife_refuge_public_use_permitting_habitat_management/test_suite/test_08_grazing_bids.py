"""Cooperative grazing: bidding rules, the selector policy (eligibility,
rank score, created_at tie-break), the empty-pool fallback, and offering
terminal lockdown.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    setup_grazing_offering, setup_awarded_agreement,
    place_bid, close_and_select, find_agreement_by_winning_bid,
    create_bid_payload, make_cooperator_headers,
    advance_clock,
)

RM = TEST_USERS["refuge_manager_headers"]


def _bids_by_ref(offering_id):
    data, _ = validate_paginated(api_client.list_bids(
        offering_id, RM, params={"limit": 100}))
    return {b["cooperator_ref"]: b for b in data}


def test_duplicate_bid_rejected(api):
    """PRD §3.7: "Each cooperator may hold at most one `SUBMITTED` bid per
    offering; a second open bid from the same cooperator is rejected with
    `ERR_DUPLICATE_BID`."

    Design: Corner/validations/duplicate_bid_rejected
    """
    ctx = setup_grazing_offering()
    offering = ctx["offering"]
    place_bid(offering["id"], cooperator_ref="coop-1",
              rate_cents_per_aum=2000, stewardship_rating=7)
    resp = api_client.create_bid(
        offering["id"],
        create_bid_payload(cooperator_ref="coop-1", rate_cents_per_aum=1500,
                           stewardship_rating=8),
        make_cooperator_headers("coop-1"))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BID)


def test_bid_after_application_deadline_rejected(api):
    """PRD §3.7: "A bid submitted after the clock has passed the offering's
    `application_deadline` is rejected with `ERR_WINDOW_IN_PAST`."

    Design: Corner/validations/bid_after_application_deadline_rejected
    """
    ctx = setup_grazing_offering()
    assert ctx["offering"]["application_deadline"] == "2026-10-01"
    advance_clock("2026-10-02T00:00:00Z")
    resp = api_client.create_bid(
        ctx["offering"]["id"],
        create_bid_payload(cooperator_ref="coop-1", rate_cents_per_aum=2000,
                           stewardship_rating=7),
        make_cooperator_headers("coop-1"))
    validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)


def test_bid_selection_tie_breaks_by_earliest_created_at(api):
    """PRD §3.7: "Each eligible bid is ranked by a rank score — its
    `stewardship_rating` multiplied by 1000, minus its `rate_cents_per_aum` —
    and the highest score wins; ties are broken toward the bid with the
    earliest `created_at`, and random identifiers never participate in the
    selection."

    Design: Corner/calculations/bid_selection_tie_breaks_by_earliest_created_at
    """
    ctx = setup_grazing_offering()
    offering = ctx["offering"]
    place_bid(offering["id"], cooperator_ref="coop-early",
              rate_cents_per_aum=2000, stewardship_rating=7)
    advance_clock("2026-09-22T00:00:00Z")
    place_bid(offering["id"], cooperator_ref="coop-late",
              rate_cents_per_aum=1000, stewardship_rating=6)
    result = close_and_select(offering["id"])
    assert result["status"] == "AWARDED"
    bids = _bids_by_ref(offering["id"])
    assert bids["coop-early"]["status"] == "WINNING", (
        "equal rank_score 5000: the bid created on 2026-09-21 must beat the "
        "identical-score bid created on 2026-09-22")
    assert bids["coop-late"]["status"] == "REJECTED"


def test_bid_below_min_stewardship_excluded_despite_better_price(api):
    """PRD §3.7: "The eligible pool is exactly the offering's bids still in
    `SUBMITTED` whose `stewardship_rating` is at least the offering's
    `min_stewardship_rating`."

    Design: Corner/calculations/bid_below_min_stewardship_excluded_despite_better_price
    """
    ctx = setup_grazing_offering()
    offering = ctx["offering"]
    place_bid(offering["id"], cooperator_ref="coop-low",
              rate_cents_per_aum=1, stewardship_rating=4)
    winning = place_bid(offering["id"], cooperator_ref="coop-ok",
                        rate_cents_per_aum=9000, stewardship_rating=5)
    close_and_select(offering["id"])
    agreement = find_agreement_by_winning_bid(winning["id"])
    assert agreement["cooperator_ref"] == "coop-ok", (
        "the eligible rating-5 bid must win and its cooperator must own the "
        "created agreement")
    bids = _bids_by_ref(offering["id"])
    assert bids["coop-ok"]["status"] == "WINNING"
    assert bids["coop-low"]["status"] == "REJECTED", (
        "a rating-4 bid below min_stewardship 5 is excluded from the pool "
        "despite the far better price")


def test_offering_empty_eligible_pool_expires(api):
    """PRD §3.7: "When the eligible pool is empty — no bids at all, or every
    bid below the stewardship floor — there is no winner: the offering moves
    to `EXPIRED`, every `SUBMITTED` bid moves to `REJECTED`, and no agreement
    is created."

    Design: Corner/calculations/offering_empty_eligible_pool_expires
    """
    ctx = setup_grazing_offering(min_stewardship_rating=10)
    offering = ctx["offering"]
    place_bid(offering["id"], cooperator_ref="coop-weak",
              rate_cents_per_aum=500, stewardship_rating=3)
    result = close_and_select(offering["id"])
    assert result["status"] == "EXPIRED", (
        "an empty eligible pool expires the offering (a success outcome, "
        "not an error)")
    bids = _bids_by_ref(offering["id"])
    assert bids["coop-weak"]["status"] == "REJECTED"
    data, meta = validate_paginated(api_client.list_agreements(
        RM, params={"management_unit_id": ctx["unit"]["id"]}))
    assert meta["total_count"] == 0, (
        f"no agreement may be created on an expired offering, "
        f"got total_count {meta['total_count']}")


def test_offering_close_twice_rejected(api):
    """PRD §3.7: "`AWARDED` and `EXPIRED` are both terminal for the offering,
    and `WINNING` and `REJECTED` are both terminal for its bids."
    PRD §2.6: "5. **State preconditions** — the invoked transition's
    from-state holds; terminal states reject every transition
    (`ERR_INVALID_STATE`, 409)."

    Design: Corner/state_machines/offering_close_twice_rejected
    """
    ctx = setup_awarded_agreement()
    awarded = validate_success(api_client.get_grazing_offering(
        ctx["offering"]["id"], RM))
    assert awarded["status"] == "AWARDED", (
        "the first close-and-select must leave the offering AWARDED")
    resp = api_client.close_and_select_offering(ctx["offering"]["id"], RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
