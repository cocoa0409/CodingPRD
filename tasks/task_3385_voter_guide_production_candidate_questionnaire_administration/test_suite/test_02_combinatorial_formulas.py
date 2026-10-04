"""Difficulty queue: combinatorial_formula.

print_copy_allocation (tier waterfall with in-tier ordering) and
guide_page_estimate (pinned per-contest rounding order) are multi-input
formulas whose outcome is pinned by the PRD for specific input tuples.
"""
from test_helpers import (
    TWENTY_ONE_WORDS,
    assert_allocation_conservation,
    build_locked_candidate_contest,
    create_edition,
    fresh_league,
    get_edition,
    get_success_data,
    make_answer,
    make_channel_request,
    ready_edition,
    validate_success,
)


def _ready_edition_with_empty_locked_contest(api):
    sc = build_locked_candidate_contest(api, filings=())
    ctx = sc["ctx"]
    edition = create_edition(api, ctx)
    edition = ready_edition(api, ctx, edition["id"])
    return ctx, edition


def _allocation_by_channel(edition):
    return {a["channel_code"]: a for a in edition["allocations"]}


def test_tier_waterfall_serves_tier_one_before_tier_two(api):
    """PRD §3.6: "Allocation then proceeds as a waterfall: tiers are served
    in ascending order; within a tier, requests are ordered by `requested`
    descending, with ties broken by `channel_code` in ascending lexicographic
    order; and each channel receives the lesser of its `requested` count and
    the copies still remaining, which are then deducted from the run."

    Design: Difficulty/combinatorial_formula/print_allocation_tier_waterfall_tiebreak
    """
    ctx, edition = _ready_edition_with_empty_locked_contest(api)
    resp = api.distribute_edition(
        edition["id"],
        {
            "print_run_total": 1000,
            "channel_requests": [
                make_channel_request("ALPHA", 600, 1),
                make_channel_request("BETA", 600, 1),
                make_channel_request("GAMMA", 300, 2),
            ],
        },
        ctx["editor_h"],
    )
    data = validate_success(resp)
    assert data["status"] == "DISTRIBUTED"
    alloc = _allocation_by_channel(data)
    assert alloc["ALPHA"]["allocated"] == 600
    # 600 + 600 tie in tier 1: ALPHA sorts first, drains the run to 400.
    assert alloc["BETA"]["allocated"] == 400
    assert alloc["GAMMA"]["allocated"] == 0
    assert data["unallocated_copies"] == 0
    assert_allocation_conservation(data)


def test_tie_break_is_channel_code_not_request_order(api):
    """PRD §3.6: "ties broken by `channel_code` in ascending lexicographic
    order" — listing BETA before ALPHA in the payload cannot change who is
    served first.  PRD §3.6: "Distribution recomputes the cycle's
    `distributed_edition_count`."

    Design: Difficulty/combinatorial_formula/print_allocation_tier_waterfall_tiebreak
    """
    ctx, edition = _ready_edition_with_empty_locked_contest(api)
    resp = api.distribute_edition(
        edition["id"],
        {
            "print_run_total": 1000,
            "channel_requests": [
                make_channel_request("BETA", 600, 1),
                make_channel_request("GAMMA", 300, 2),
                make_channel_request("ALPHA", 600, 1),
            ],
        },
        ctx["editor_h"],
    )
    data = validate_success(resp)
    alloc = _allocation_by_channel(data)
    assert alloc["ALPHA"]["allocated"] == 600
    assert alloc["BETA"]["allocated"] == 400
    assert alloc["GAMMA"]["allocated"] == 0
    assert_allocation_conservation(data)
    cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], ctx["admin_h"]))
    assert cycle["distributed_edition_count"] == 1


def test_page_estimate_rounds_per_contest_then_sums(api):
    """PRD §3.6: "By way of illustration, two snapshot contests carrying
    twenty-one words each yield three columns and then two pages apiece —
    six pages in total once the two front-matter pages are added — whereas
    pooling the words across contests before rounding would yield five; the
    pinned, per-contest order is the specification."

    Design: Difficulty/combinatorial_formula/page_estimate_per_contest_roundup_then_sum
    """
    ctx = fresh_league(api)
    sc1 = build_locked_candidate_contest(
        api, ctx, filings=(("Ana One", "F-1"),),
        submissions={"F-1": [make_answer(1, TWENTY_ONE_WORDS)]},
    )
    sc2 = build_locked_candidate_contest(
        api, ctx, filings=(("Bob Two", "F-2"),),
        submissions={"F-2": [make_answer(1, TWENTY_ONE_WORDS)]},
    )
    edition = create_edition(api, ctx, channel="WEB")
    ready = ready_edition(api, ctx, edition["id"])
    assert ready["status"] == "READY"
    # Per contest: ceil(21/10) = 3 columns, ceil(3/2) = 2 pages; 2*2 + 2 = 6.
    assert ready["estimated_page_count"] == 6
    assert set(ready["snapshot_contest_ids"]) == {
        sc1["contest"]["id"], sc2["contest"]["id"],
    }


def test_page_estimate_single_contest_rounding(api):
    """PRD §3.6: "For each snapshot contest a word total is computed: for a
    candidate race, the sum, over the pinned questionnaire's `SUBMITTED`
    responses, of every answer's word count recomputed under the `STRICT`
    policy; for a ballot-measure contest, the `STRICT` word count of the
    measure's `explanation_text` plus the `word_count` of its `ACCEPTED`
    arguments."
    PRD §3.6: "Each contest's words are divided by ten and rounded up to
    whole columns; those columns are divided by two and rounded up to whole
    pages."

    Design: Difficulty/combinatorial_formula/page_estimate_per_contest_roundup_then_sum
    """
    ctx = fresh_league(api)
    sc = build_locked_candidate_contest(
        api, ctx, filings=(("Ana One", "F-1"),),
        submissions={"F-1": [make_answer(1, TWENTY_ONE_WORDS)]},
    )
    edition = create_edition(api, ctx, channel="WEB")
    ready = ready_edition(api, ctx, edition["id"])
    # One contest: ceil(21/10) = 3 columns, ceil(3/2) = 2 pages, + 2 front.
    assert ready["estimated_page_count"] == 4
    assert ready["snapshot_contest_ids"] == [sc["contest"]["id"]]
