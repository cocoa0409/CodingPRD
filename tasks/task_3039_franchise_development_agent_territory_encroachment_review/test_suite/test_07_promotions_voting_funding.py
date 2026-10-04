"""National promotions: quorum, funding tiers, activation capacity, disputes
(PRD §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    cast_for_ballots,
    create_funding_dispute_payload,
    create_promotion_payload,
    create_vote_payload,
    get_promotion,
    get_promotion_vote,
    make_franchisee_headers,
    set_clock,
    setup_active_promotion,
    setup_promotion_in_voting,
    setup_promotion_with_votes,
    setup_territory_with_stores,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_promotion_funding_tier_evaluation_order(api, franchisor_ops_headers):
    """PRD §3.7: "the funding allocation computes in pinned order:
    `participating_store_count` is the number of stores holding a live `FOR`
    ballot; the subsidy tier keys on that count — fifteen percent when at
    least twelve stores participate, ten percent for six through eleven, five
    percent otherwise; `store_share_cents` is the `base_cost_per_store_cents`
    reduced by the subsidy, rounded half up to whole cents; and
    `total_pool_cents` is the participating count multiplied by the per-store
    share."

    Design: Difficulty/combinatorial_formula/promotion_funding_tier_evaluation_order
    """
    ctx = setup_promotion_with_votes(6, ["FOR"] * 6)
    set_clock("2026-09-10T00:00:00Z")
    promo = validate_success(api.close_promotion_voting(ctx["promotion"]["id"], {},
                                                        franchisor_ops_headers), 200)
    assert promo["status"] == "APPROVED"
    assert promo["participating_store_count"] == 6
    assert promo["eligible_voter_count"] == 6
    # Mid tier (6 <= N <= 11): 200,000 x (1 - 0.10) = 180,000; pool = 6 x 180,000.
    assert promo["store_share_cents"] == 180_000
    assert promo["total_pool_cents"] == 1_080_000


def test_promotion_funding_tier_keys_on_live_for_count(api, franchisor_ops_headers):
    """PRD §3.7: "`participating_store_count` is the number of stores holding
    a live `FOR` ballot; the subsidy tier keys on that count — fifteen percent
    when at least twelve stores participate, ten percent for six through
    eleven, five percent otherwise"

    Design: Difficulty/combinatorial_formula/promotion_funding_tier_evaluation_order
    """
    # 6 stores, but only 4 live FOR ballots -> N=4 -> low tier (5%).
    ctx = setup_promotion_with_votes(6, ["FOR", "FOR", "FOR", "FOR", "AGAINST", "ABSTAIN"])
    set_clock("2026-09-10T00:00:00Z")
    promo = validate_success(api.close_promotion_voting(ctx["promotion"]["id"], {},
                                                        franchisor_ops_headers), 200)
    assert promo["status"] == "APPROVED"
    assert promo["participating_store_count"] == 4
    assert promo["store_share_cents"] == 190_000  # 200,000 x 0.95
    assert promo["total_pool_cents"] == 4 * 190_000


def test_quorum_exactly_two_thirds_passes(api, franchisor_ops_headers):
    """PRD §3.7: "the `FOR` tally multiplied by three must be at least twice
    the eligible voter count — exactly two-thirds approval passes — and the
    total ballots cast, doubled, must be at least the eligible voter count —
    half turnout."

    Design: Difficulty/boundary_precision_check/quorum_exactly_two_thirds_passes
    """
    # 6 eligible; 4 FOR + 1 AGAINST + 1 non-voter: 4*3=12 >= 2*6=12 (boundary).
    ctx = setup_promotion_with_votes(6, ["FOR", "FOR", "FOR", "FOR", "AGAINST"])
    set_clock("2026-09-10T00:00:00Z")
    promo = validate_success(api.close_promotion_voting(ctx["promotion"]["id"], {},
                                                        franchisor_ops_headers), 200)
    assert promo["status"] == "APPROVED"
    assert promo["votes_for"] == 4
    assert promo["eligible_voter_count"] == 6


def test_quorum_one_ballot_below_boundary_rejects(api, franchisor_ops_headers):
    """PRD §3.7: "When quorum fails, closing the vote without more is refused
    with `ERR_QUORUM_NOT_MET`; the operator may instead pass `force_reject`
    set to true, moving the promotion to terminal `REJECTED`."

    Design: Difficulty/boundary_precision_check/quorum_exactly_two_thirds_passes
    """
    # 6 eligible; 3 FOR + 2 AGAINST: 3*3=9 < 12, one ballot below the boundary.
    ctx = setup_promotion_with_votes(6, ["FOR", "FOR", "FOR", "AGAINST", "AGAINST"])
    set_clock("2026-09-10T00:00:00Z")
    promo = validate_success(
        api.close_promotion_voting(ctx["promotion"]["id"], {"force_reject": True},
                                   franchisor_ops_headers), 200)
    assert promo["status"] == "REJECTED"


def test_close_voting_without_quorum_returns_quorum_not_met(api, franchisor_ops_headers):
    """PRD §3.7: "When quorum fails, closing the vote without more is refused
    with `ERR_QUORUM_NOT_MET`"

    Design: Corner/errors/close_voting_without_quorum_returns_quorum_not_met
    """
    # 4 eligible stores, only 1 FOR ballot: turnout 1 of 4 fails half turnout.
    ctx = setup_promotion_with_votes(4, ["FOR"])
    set_clock("2026-09-10T00:00:00Z")
    resp = api.close_promotion_voting(ctx["promotion"]["id"], {}, franchisor_ops_headers)
    validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET, 422)
    promo = get_promotion(ctx["promotion"]["id"])
    assert promo["status"] == "VOTING"


def test_territory_promotion_capacity_overlap(api, franchisor_ops_headers):
    """PRD §3.7: "for every territory containing a participating store, fewer
    than two other `ACTIVE` promotions may overlap the campaign window — a
    third concurrent campaign in the same territory is refused with
    `ERR_PROMOTION_OVERLAP_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/territory_promotion_capacity_overlap
    """
    ctx = setup_territory_with_stores(store_count=2, agent_assigned=False)
    s1, s2 = ctx["stores"]
    o1, o2 = ctx["owners"]
    windows = [("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", "P1"),
               ("2026-10-15T00:00:00Z", "2026-11-15T00:00:00Z", "P2"),
               ("2026-10-20T00:00:00Z", "2026-11-20T00:00:00Z", "P3")]
    promos = []
    for active_start, active_end, name in windows:
        promo = setup_promotion_in_voting(
            name=name,
            voting_open="2026-09-01T00:00:00Z",
            voting_close="2026-09-05T00:00:00Z",
            active_start=active_start,
            active_end=active_end,
        )
        for store, owner in ((s1, o1), (s2, o2)):
            validate_success(
                api.cast_vote(promo["id"], create_vote_payload(store["id"], "FOR"),
                              make_franchisee_headers(owner["id"])), 201)
        promos.append(promo)
    set_clock("2026-09-05T00:00:00Z")
    for promo in promos:
        closed = validate_success(api.close_promotion_voting(promo["id"], {},
                                                             franchisor_ops_headers), 200)
        assert closed["status"] == "APPROVED"
    set_clock("2026-10-01T00:00:00Z")
    p1 = validate_success(api.activate_promotion(promos[0]["id"], franchisor_ops_headers), 200)
    set_clock("2026-10-15T00:00:00Z")
    p2 = validate_success(api.activate_promotion(promos[1]["id"], franchisor_ops_headers), 200)
    set_clock("2026-10-20T00:00:00Z")
    resp = api.activate_promotion(promos[2]["id"], franchisor_ops_headers)
    validate_error(resp, ApiErrorId.ERR_PROMOTION_OVERLAP_EXCEEDED, 422)
    assert get_promotion(p1["id"])["status"] == "ACTIVE"
    assert get_promotion(p2["id"])["status"] == "ACTIVE"
    assert get_promotion(promos[2]["id"])["status"] == "APPROVED"


def test_second_overlapping_promotion_in_territory_activates(api, franchisor_ops_headers):
    """PRD §3.7: "fewer than two other `ACTIVE` promotions may overlap the
    campaign window — a third concurrent campaign in the same territory is
    refused with `ERR_PROMOTION_OVERLAP_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/territory_promotion_capacity_overlap
    """
    ctx = setup_territory_with_stores(store_count=2, agent_assigned=False)
    s1, s2 = ctx["stores"]
    o1, o2 = ctx["owners"]
    promos = []
    for active_start, active_end, name in (
            ("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", "PA"),
            ("2026-10-15T00:00:00Z", "2026-11-15T00:00:00Z", "PB")):
        promo = setup_promotion_in_voting(
            name=name,
            voting_open="2026-09-01T00:00:00Z",
            voting_close="2026-09-05T00:00:00Z",
            active_start=active_start,
            active_end=active_end,
        )
        for store, owner in ((s1, o1), (s2, o2)):
            validate_success(
                api.cast_vote(promo["id"], create_vote_payload(store["id"], "FOR"),
                              make_franchisee_headers(owner["id"])), 201)
        promos.append(promo)
    set_clock("2026-09-05T00:00:00Z")
    for promo in promos:
        validate_success(api.close_promotion_voting(promo["id"], {}, franchisor_ops_headers), 200)
    set_clock("2026-10-01T00:00:00Z")
    validate_success(api.activate_promotion(promos[0]["id"], franchisor_ops_headers), 200)
    set_clock("2026-10-15T00:00:00Z")
    # One other ACTIVE promotion overlaps: fewer than two others -> allowed.
    second = validate_success(api.activate_promotion(promos[1]["id"], franchisor_ops_headers), 200)
    assert second["status"] == "ACTIVE"


def test_vote_tally_conservation_across_retract_and_recast(api, franchisor_ops_headers):
    """PRD §3.7: "A ballot may be retracted while voting remains open — the
    vote's `retracted` flag flips to true, and a retracted ballot never counts
    again. The promotion's `votes_for`, `votes_against`, and `votes_abstain`
    are live tallies of non-retracted ballots, recomputed on every cast and
    retract."

    Design: Difficulty/compensating_invariant/vote_tally_conservation_across_retract_and_recast
    """
    ctx = setup_territory_with_stores(store_count=1, agent_assigned=False)
    store, owner = ctx["stores"][0], ctx["owners"][0]
    promo = setup_promotion_in_voting(name="Tally")
    v1 = validate_success(
        api.cast_vote(promo["id"], create_vote_payload(store["id"], "FOR"),
                      make_franchisee_headers(owner["id"])), 201)
    retracted = validate_success(
        api.retract_vote(v1["id"], make_franchisee_headers(owner["id"])), 200)
    assert retracted["retracted"] is True
    v2 = validate_success(
        api.cast_vote(promo["id"], create_vote_payload(store["id"], "ABSTAIN"),
                      make_franchisee_headers(owner["id"])), 201)
    promo_after = get_promotion(promo["id"])
    assert promo_after["votes_for"] == 0
    assert promo_after["votes_against"] == 0
    assert promo_after["votes_abstain"] == 1
    live_total = promo_after["votes_for"] + promo_after["votes_against"] + promo_after["votes_abstain"]
    assert live_total == 1


def test_vote_retract_then_recast_leaves_single_live_ballot(api, franchisor_ops_headers):
    """PRD §3.7: "at most one live ballot exists per store and promotion: a
    second non-retracted ballot is refused with `ERR_ALREADY_VOTED`. A ballot
    may be retracted while voting remains open — the vote's `retracted` flag
    flips to true, and a retracted ballot never counts again."

    Design: Difficulty/compensating_invariant/vote_tally_conservation_across_retract_and_recast
    """
    ctx = setup_territory_with_stores(store_count=1, agent_assigned=False)
    store, owner = ctx["stores"][0], ctx["owners"][0]
    promo = setup_promotion_in_voting(name="Tally2")
    v1 = validate_success(
        api.cast_vote(promo["id"], create_vote_payload(store["id"], "FOR"),
                      make_franchisee_headers(owner["id"])), 201)
    validate_success(api.retract_vote(v1["id"], make_franchisee_headers(owner["id"])), 200)
    validate_success(
        api.cast_vote(promo["id"], create_vote_payload(store["id"], "ABSTAIN"),
                      make_franchisee_headers(owner["id"])), 201)
    rows, meta = validate_paginated(
        api.list_promotion_votes(promo["id"], franchisor_ops_headers))
    assert meta["total_count"] == 2
    assert sum(1 for row in rows if row["retracted"] is True) == 1
    assert get_promotion_vote(v1["id"])["retracted"] is True


def test_double_vote_same_store_same_promotion_conflict(api, franchisor_ops_headers):
    """PRD §3.7: "at most one live ballot exists per store and promotion: a
    second non-retracted ballot is refused with `ERR_ALREADY_VOTED`."

    Design: Corner/errors/double_vote_same_store_same_promotion_conflict
    """
    ctx = setup_territory_with_stores(store_count=1, agent_assigned=False)
    store, owner = ctx["stores"][0], ctx["owners"][0]
    promo = setup_promotion_in_voting(name="Dupe")
    owner_headers = make_franchisee_headers(owner["id"])
    v1 = validate_success(
        api.cast_vote(promo["id"], create_vote_payload(store["id"], "FOR"), owner_headers), 201)
    dup = api.cast_vote(promo["id"], create_vote_payload(store["id"], "AGAINST"), owner_headers)
    validate_error(dup, ApiErrorId.ERR_ALREADY_VOTED, 409)
    validate_success(api.retract_vote(v1["id"], owner_headers), 200)
    recast = api.cast_vote(promo["id"], create_vote_payload(store["id"], "AGAINST"), owner_headers)
    validate_success(recast, 201)
    assert get_promotion(promo["id"])["votes_against"] == 1


def test_vote_outside_window_returns_voting_closed(api, franchisor_ops_headers):
    """PRD §3.7: "the cast must fall inside the voting window (otherwise
    `ERR_VOTING_CLOSED`)"

    Design: Corner/validations/vote_outside_window_returns_voting_closed
    """
    ctx = setup_territory_with_stores(store_count=1, agent_assigned=False)
    store, owner = ctx["stores"][0], ctx["owners"][0]
    promo = create_promotion_via(api, franchisor_ops_headers,
                                 voting_open="2026-09-05T00:00:00Z",
                                 voting_close="2026-09-10T00:00:00Z")
    set_clock("2026-09-05T00:00:00Z")
    validate_success(api.open_promotion_voting(promo["id"], franchisor_ops_headers), 200)
    # Wind the clock back before voting_open: the window, not the status, gates.
    set_clock("2026-09-03T00:00:00Z")
    resp = api.cast_vote(promo["id"], create_vote_payload(store["id"], "FOR"),
                         make_franchisee_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_VOTING_CLOSED, 422)
    rows, meta = validate_paginated(api.list_promotion_votes(promo["id"], franchisor_ops_headers))
    assert meta["total_count"] == 0


def create_promotion_via(api, headers, **overrides):
    from test_helpers import create_promotion
    return create_promotion(**overrides)


def test_vote_create_with_out_of_enum_ballot_returns_invalid_request(api, franchisor_ops_headers):
    """PRD §3.7: "Each store's operator casts one ballot — `FOR`, `AGAINST`,
    or `ABSTAIN`"
    PRD §2.8: "(12) request shape — field presence, enum membership, numeric
    ranges"

    Design: Corner/entities/vote_create_with_out_of_enum_ballot_returns_invalid_request
    """
    ctx = setup_territory_with_stores(store_count=1, agent_assigned=False)
    store, owner = ctx["stores"][0], ctx["owners"][0]
    promo = setup_promotion_in_voting(name="EnumCheck")
    resp = api.cast_vote(promo["id"], create_vote_payload(store["id"], "MAYBE"),
                         make_franchisee_headers(owner["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
    rows, meta = validate_paginated(api.list_promotion_votes(promo["id"], franchisor_ops_headers))
    assert meta["total_count"] == 0


def test_dispute_amount_must_equal_computed_store_share(api, franchisor_ops_headers):
    """PRD §3.7: "the disputed amount must equal the promotion's computed
    `store_share_cents` exactly, otherwise `ERR_DISPUTE_AMOUNT_MISMATCH`."

    Design: Corner/validations/dispute_amount_must_equal_computed_store_share
    """
    ctx = setup_active_promotion(store_count=1, ballots=["FOR"])
    store, owner = ctx["stores"][0], ctx["owners"][0]
    promo = get_promotion(ctx["promotion"]["id"])
    assert promo["status"] == "ACTIVE"
    # N=1 -> low tier: 200,000 x (1 - 0.05) = 190,000.
    assert promo["store_share_cents"] == 190_000
    bad = api.create_funding_dispute(
        create_funding_dispute_payload(promo["id"], store["id"], 185_000, reason="too high"),
        make_franchisee_headers(owner["id"]),
    )
    validate_error(bad, ApiErrorId.ERR_DISPUTE_AMOUNT_MISMATCH, 422)
    good = api.create_funding_dispute(
        create_funding_dispute_payload(promo["id"], store["id"], 190_000, reason="correct share"),
        make_franchisee_headers(owner["id"]),
    )
    dispute = validate_success(good, 201)
    assert dispute["status"] == "OPEN"
