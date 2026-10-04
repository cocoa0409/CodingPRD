"""Boundary precision on three distinct metrics: money (landed cost vs the
fixed cost target), count (shelf facings vs category capacity), and score
(momentum vs the selection threshold). Equality is inclusive on all three.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_quote,
    advance_line_review_to_decided,
    assert_footprint_conservation,
    commit_slot,
    create_line_review,
    create_manufacturer,
    create_partner,
    create_quote,
    create_slot,
    create_trend,
    evaluate_quote,
    open_line_review,
    read_cost_quote,
    read_partner,
    read_planogram_slot,
    read_product,
    setup_launch_ready_product,
    setup_sourcing_product,
    transition_trend,
    validate_error,
    validate_paginated,
)

_SCOUT = TEST_USERS["trend_scout_headers"]
_SOURCING = TEST_USERS["sourcing_lead_headers"]
_PLANNER = TEST_USERS["retail_planner_headers"]


def _setup_two_manufacturers():
    ctx = setup_sourcing_product()
    ctx["manufacturer2"] = create_manufacturer(
        name="SecondSource Labs", capabilities=["EYES"], base_lead_time_weeks=6
    )
    return ctx


def test_landed_cost_one_cent_over_target_rejects(api):
    """PRD §3.5: "the quote's `landed_provisional_cents` must not exceed the
    parent concept's `target_unit_cost_cents`, with equality allowed, else
    `ERR_COST_TARGET_EXCEEDED`"
    Price point 1000 -> target 260. The quote computes 224 + 10 + 4 +
    round(228*0.10)=23 == 261 — one cent over — and its acceptance is
    rejected.

    Design: Difficulty/boundary_precision_check/landed_cost_exactly_at_target_accepts_one_cent_over_rejects
    """
    ctx = _setup_two_manufacturers()

    quote_hi = create_quote(
        ctx["product"]["id"], ctx["manufacturer2"]["id"], unit_cost_cents=224
    )
    assert quote_hi["landed_provisional_cents"] == 261
    evaluate_quote(quote_hi["id"])

    response = api.patch_cost_quote(quote_hi["id"], {"status": "ACCEPTED"}, _SOURCING)

    validate_error(response, ApiErrorId.ERR_COST_TARGET_EXCEEDED.value)
    assert read_cost_quote(quote_hi["id"])["status"] == "UNDER_EVALUATION"
    assert read_product(ctx["product"]["id"])["status"] == "SOURCING"


def test_landed_cost_exactly_at_target_accepts_and_supersedes_sibling(api):
    """PRD §3.5: "the quote's `landed_provisional_cents` must not exceed the
    parent concept's `target_unit_cost_cents`, with equality allowed, else
    `ERR_COST_TARGET_EXCEEDED`"
    PRD §3.5: "Acceptance stamps `accepted_at`, pins `pinned_formula_version`
    to the approved project's `formula_version`, consumes one quarterly
    production slot, and supersedes every other quote for the same product
    still in `SUBMITTED` or `UNDER_EVALUATION`."
    The 260-cent quote (223 + 10 + 4 + round(227*0.10)=23) accepts at exactly
    the target; the rejected 261-cent sibling, still UNDER_EVALUATION, is
    superseded by the acceptance.

    Design: Difficulty/boundary_precision_check/landed_cost_exactly_at_target_accepts_one_cent_over_rejects
    """
    ctx = _setup_two_manufacturers()
    quote_hi = create_quote(
        ctx["product"]["id"], ctx["manufacturer2"]["id"], unit_cost_cents=224
    )
    evaluate_quote(quote_hi["id"])
    validate_error(
        api.patch_cost_quote(quote_hi["id"], {"status": "ACCEPTED"}, _SOURCING),
        ApiErrorId.ERR_COST_TARGET_EXCEEDED.value,
    )

    quote_eq = create_quote(
        ctx["product"]["id"], ctx["manufacturer"]["id"], unit_cost_cents=223
    )
    assert quote_eq["landed_provisional_cents"] == 260

    accepted = accept_quote(quote_eq["id"])
    assert accepted["status"] == "ACCEPTED"
    assert read_cost_quote(quote_hi["id"])["status"] == "SUPERSEDED"
    assert read_product(ctx["product"]["id"])["status"] == "SOURCING"


def _setup_six_face_scenario():
    ctx = setup_launch_ready_product()
    ctx["partner"] = create_partner(
        name="SixFace", banner_code="SF", category_capacities={"EYES": 6}
    )
    ctx["line_review"] = create_line_review(ctx["partner"]["id"])
    ctx["line_review"] = open_line_review(ctx["line_review"]["id"])
    ctx["s1"] = create_slot(
        ctx["line_review"]["id"], ctx["product"]["id"],
        position_code="EYES-A1", facings=4,
    )
    ctx["s2"] = create_slot(
        ctx["line_review"]["id"], ctx["product"]["id"],
        position_code="EYES-A2", facings=2,
    )
    ctx["s3"] = create_slot(
        ctx["line_review"]["id"], ctx["product"]["id"],
        position_code="EYES-A3", facings=1,
    )
    ctx["line_review"] = advance_line_review_to_decided(ctx["line_review"]["id"])
    return ctx


def test_facings_commit_up_to_exact_capacity_then_reject(api):
    """PRD §3.7: "Committing is capacity-checked: the category's currently
    committed facings plus the slot's `facings` must not exceed the partner's
    configured capacity for that category, with equality allowed, else
    `ERR_CAPACITY_EXCEEDED`."
    EYES capacity 6: 4 commits, then 4+2 == 6 commits (equality), then 6+1 > 6
    rejects.

    Design: Difficulty/boundary_precision_check/facings_exactly_at_capacity_commits_one_over_rejects
    """
    ctx = _setup_six_face_scenario()

    assert commit_slot(ctx["s1"]["id"])["status"] == "COMMITTED"
    assert commit_slot(ctx["s2"]["id"])["status"] == "COMMITTED"

    response = api.patch_planogram_slot(ctx["s3"]["id"], {"status": "COMMITTED"}, _PLANNER)

    validate_error(response, ApiErrorId.ERR_CAPACITY_EXCEEDED.value)
    assert read_planogram_slot(ctx["s3"]["id"])["status"] == "PROPOSED"


def test_facings_at_capacity_leave_zero_available(api):
    """PRD §2.9: "For each category, `committed_facings` is the sum of
    `facings` over that partner's planogram slots in `COMMITTED` or `ACTIVE`
    status — slots in `PROPOSED`, `WITHDRAWN`, `RELEASED`, or `VACATED` never
    count — and `available_facings` is the capacity minus the committed
    amount, never negative."
    At exactly-committed capacity the partner reads committed 6 / available 0
    and footprint conservation holds.

    Design: Difficulty/boundary_precision_check/facings_exactly_at_capacity_commits_one_over_rejects
    """
    ctx = _setup_six_face_scenario()
    commit_slot(ctx["s1"]["id"])
    commit_slot(ctx["s2"]["id"])
    validate_error(
        api.patch_planogram_slot(ctx["s3"]["id"], {"status": "COMMITTED"}, _PLANNER),
        ApiErrorId.ERR_CAPACITY_EXCEEDED.value,
    )

    partner = read_partner(ctx["partner"]["id"])

    assert partner["committed_facings"]["EYES"] == 6
    assert partner["available_facings"]["EYES"] == 0
    assert_footprint_conservation(partner)


def test_trend_scoring_exactly_70_selects(api):
    """PRD §3.1: "a scout may move an `EVALUATING` signal to `SELECTED` only
    when its `momentum_score` is at least seventy, and an attempt below that
    threshold is rejected with `ERR_TREND_SCORE_BELOW_THRESHOLD`."
    0.5*80 + 0.3*50 + 0.2*75 == 70.0 — the inclusive threshold selects.

    Design: Difficulty/boundary_precision_check/trend_score_exactly_at_threshold_selects
    """
    trend = create_trend()

    evaluated = transition_trend(trend["id"], "EVALUATING")
    assert evaluated["momentum_score"] == pytest.approx(70.0)

    selected = transition_trend(trend["id"], "SELECTED")
    assert selected["status"] == "SELECTED"


def test_trend_scoring_69_7_rejects_selection(api):
    """PRD §3.1: "The momentum score is then the sum of the velocity component
    weighted one half, the growth component weighted three tenths, and the
    signal component weighted one fifth, each scaled by one hundred, rounded
    half up to one decimal place."
    PRD §3.1: "a scout may move an `EVALUATING` signal to `SELECTED` only when
    its `momentum_score` is at least seventy, and an attempt below that
    threshold is rejected with `ERR_TREND_SCORE_BELOW_THRESHOLD`."
    Growth 0.98 -> 0.3*49 == 14.7, total 40.0 + 14.7 + 15.0 == 69.7 < 70.

    Design: Difficulty/boundary_precision_check/trend_score_exactly_at_threshold_selects
    """
    trend = create_trend(engagement_growth_pct=0.98, category="LIPS")

    evaluated = transition_trend(trend["id"], "EVALUATING")
    assert evaluated["momentum_score"] == pytest.approx(69.7)

    response = api.patch_trend_signal(trend["id"], {"status": "SELECTED"}, _SCOUT)

    validate_error(response, ApiErrorId.ERR_TREND_SCORE_BELOW_THRESHOLD.value)
    rows, meta = validate_paginated(
        api.list_trend_signals(headers=_SCOUT, params={"status": "EVALUATING"})
    )
    assert [row["id"] for row in rows] == [trend["id"]]
    assert rows[0]["momentum_score"] == pytest.approx(69.7)
