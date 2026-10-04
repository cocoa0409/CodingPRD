"""Chapter fiscal boundaries: the exact freeze threshold, the strict
greater-than escalation projection, the blended vs cash-only averages, and
approve/abort conservation of the commitment ledger.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    abort_plan,
    api_client,
    approve_plan,
    assert_chapter_fiscal,
    create_chapter,
    create_volunteer_pair,
    get_chapter,
    get_fulfillment_plan,
    get_wish,
    set_clock,
    setup_approved_wish,
    setup_chapter_with_granted_wish,
    setup_granted_wish,
    setup_planning_wish,
    submit_plan,
    validate_error,
)

CHAPTER_DIRECTOR = TEST_USERS["chapter_director_headers"]
NATIONAL_DIRECTOR = TEST_USERS["national_director_headers"]


def _chapter_with_history_and_pending_plan(plan_cash_cents):
    """Chapter (budget 5000000, target 800000) with one granted cash-only
    600000 wish, plus a second wish whose cash-only plan is submitted."""
    base = setup_chapter_with_granted_wish(granted_cash_cents=600000)
    ctx = setup_planning_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="a shopping spree",
        prognosis_months=12, chapter=base["chapter"], zip_code="80044",
        child_full_name="Theo Alvarez", child_date_of_birth="2015-06-15",
        cash_cost_cents=plan_cash_cents, lead=base["lead"],
        second=base["second"], set_clock_first=False,
        visit_start="2026-09-06T09:00:00Z", visit_end="2026-09-06T11:00:00Z")
    submit_plan(ctx["plan"]["id"])
    return base["chapter"], ctx


def test_escalation_not_triggered_at_exact_target():
    """PRD section 2.9: "compares against the chapter's
    `target_avg_cost_per_wish_cents` with a strict greater-than — a projection
    landing exactly on the target does not escalate."
    Granted history (1 wish, 600000) plus a 999999 plan projects
    round-half-up(1599999 / 2) == 800000, exactly the target.

    Design: Corner/calculations/escalation_not_triggered_at_exact_target
    """
    chapter, ctx = _chapter_with_history_and_pending_plan(999999)
    approved = approve_plan(ctx["plan"]["id"], CHAPTER_DIRECTOR)
    assert approved["status"] == "APPROVED"
    assert approved["escalation_required"] is False, (
        "a projection equal to the target must not escalate"
    )
    assert get_chapter(chapter["id"])["committed_cost_cents"] == 999999


def test_chapter_posture_freeze_at_exact_threshold():
    """PRD section 2.9: "it is `FROZEN` whenever `committed_cost_cents`
    reaches or exceeds the freeze threshold — the chapter's
    `fiscal_year_budget_cents` multiplied by 95 percent and rounded down to
    whole cents — and `OPEN` below it. Equality freezes: a commitment landing
    exactly on the threshold closes the chapter."
    Budget 5000000 -> threshold 4750000: 4749999 stays OPEN, 4750000 FROZEN.

    Design: Corner/calculations/chapter_posture_freeze_at_exact_threshold
    """
    set_clock()
    chapter = create_chapter(name="Gulf Chapter", territory_zip_prefixes=["800"],
                             fiscal_year_budget_cents=5000000,
                             target_avg_cost_per_wish_cents=800000)
    lead, second = create_volunteer_pair(chapter["id"])
    setup_approved_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="a big trip fund",
        chapter=chapter, lead=lead, second=second, set_clock_first=False,
        zip_code="80012",
        cash_cost_cents=4749999, approver_headers=NATIONAL_DIRECTOR)
    mid = get_chapter(chapter["id"])
    assert_chapter_fiscal(mid, committed_cost_cents=4749999, posture="OPEN")

    ctx2 = setup_planning_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="a sticker",
        chapter=chapter, lead=lead, second=second, set_clock_first=False,
        zip_code="80044", child_full_name="Theo Alvarez",
        child_date_of_birth="2015-06-15", cash_cost_cents=1,
        visit_start="2026-09-06T09:00:00Z", visit_end="2026-09-06T11:00:00Z")
    submit_plan(ctx2["plan"]["id"])
    approve_plan(ctx2["plan"]["id"], CHAPTER_DIRECTOR)

    final = get_chapter(chapter["id"])
    assert_chapter_fiscal(final, committed_cost_cents=4750000, posture="FROZEN")


def test_escalation_projection_rejects_chapter_director():
    """PRD section 2.9: "When the projection exceeds the target, the plan's
    `escalation_required` flag is set and only a `NationalDirector` may
    approve it; a `ChapterDirector` attempting the same approval is rejected
    with `ERR_COST_ESCALATION_REQUIRED` (HTTP 422)."
    Granted history (1 wish, 600000) plus a 1000001 plan projects
    round-half-up(1600001 / 2) == 800001 > 800000.

    Design: Difficulty/combinatorial_formula/escalation_average_includes_pending_plan
    """
    _, ctx = _chapter_with_history_and_pending_plan(1000001)
    resp = api_client.approve_plan(ctx["plan"]["id"], CHAPTER_DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_COST_ESCALATION_REQUIRED)
    assert get_fulfillment_plan(ctx["plan"]["id"])["status"] == "PENDING_APPROVAL"


def test_escalation_projection_allows_national_director():
    """PRD section 2.9: "it takes the chapter's pre-approval granted totals,
    adds the pending plan's `total_cost_cents` to the numerator exactly once,
    adds exactly one to the granted count in the denominator, divides, rounds
    half-up to integer cents" — the NationalDirector approval then commits the
    plan's full total.

    Design: Difficulty/combinatorial_formula/escalation_average_includes_pending_plan
    """
    chapter, ctx = _chapter_with_history_and_pending_plan(1000001)
    rejected = api_client.approve_plan(ctx["plan"]["id"], CHAPTER_DIRECTOR)
    validate_error(rejected, ApiErrorId.ERR_COST_ESCALATION_REQUIRED)

    approved = approve_plan(ctx["plan"]["id"], NATIONAL_DIRECTOR)
    assert approved["status"] == "APPROVED"
    assert approved["escalation_required"] is True
    assert get_chapter(chapter["id"])["committed_cost_cents"] == 1000001


def test_chapter_granted_totals_split_blended_and_cash():
    """PRD section 3.8: "`granted_wish_count` rises by one,
    `granted_cost_total_cents` rises by the plan's `total_cost_cents`,
    `granted_cash_total_cents` rises by the plan's `cash_cost_cents`"
    A granted plan of cash 10000 plus one 12000-cent in-kind line books
    22000 blended and 10000 cash.

    Design: Difficulty/dual_variant_calc/chapter_cost_per_wish_blended_vs_cash_only
    """
    ctx = setup_granted_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="a big toy firetruck",
        cash_cost_cents=10000,
        offer_specs=[{"partner_name": "ToyWorld", "category": "RETAILER",
                      "description": "toy firetruck", "quantity_total": 10,
                      "unit_retail_cents": 12000, "quantity": 1}])
    chapter = get_chapter(ctx["chapter"]["id"])
    assert_chapter_fiscal(
        chapter,
        granted_wish_count=1,
        granted_cost_total_cents=22000,
        granted_cash_total_cents=10000,
    )


def test_chapter_averages_diverge_with_in_kind():
    """PRD section 2.9: "The blended variant, `avg_cost_blended_cents`,
    divides the granted plans' total value — cash plus in-kind fair market
    value — by the granted wish count, rounding half-up to integer cents. The
    cash-only variant, `avg_cost_cash_cents`, divides only the cash portions
    of those same plans by the same count; for identical grant data involving
    any in-kind lines, the cash-only figure is strictly lower than the blended
    figure."

    Design: Difficulty/dual_variant_calc/chapter_cost_per_wish_blended_vs_cash_only
    """
    ctx = setup_granted_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="a big toy firetruck",
        cash_cost_cents=10000,
        offer_specs=[{"partner_name": "ToyWorld", "category": "RETAILER",
                      "description": "toy firetruck", "quantity_total": 10,
                      "unit_retail_cents": 12000, "quantity": 1}])
    chapter = get_chapter(ctx["chapter"]["id"])
    assert chapter["avg_cost_blended_cents"] == 22000
    assert chapter["avg_cost_cash_cents"] == 10000
    assert chapter["avg_cost_cash_cents"] < chapter["avg_cost_blended_cents"]


def test_committed_rises_exactly_on_approve():
    """PRD section 3.6: "the chapter's `committed_cost_cents` rises by the
    plan's total with `posture` recomputed and the chapter's `version`
    incremented"
    PRD section 2.9: "Each chapter tracks `committed_cost_cents`, the sum of
    `total_cost_cents` over its approved fulfillment plans"

    Design: Difficulty/compensating_invariant/chapter_committed_approve_abort_conservation
    """
    ctx = setup_planning_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="two toy trucks",
        cash_cost_cents=100000,
        offer_specs=[{"quantity_total": 10, "unit_retail_cents": 12000,
                      "quantity": 2}])
    chapter_id = ctx["chapter"]["id"]
    assert get_chapter(chapter_id)["committed_cost_cents"] == 0

    submit_plan(ctx["plan"]["id"])
    approve_plan(ctx["plan"]["id"])
    after = get_chapter(chapter_id)
    assert after["committed_cost_cents"] == 124000, (
        f"100000 cash + 2 x 12000 in-kind == 124000, got "
        f"{after['committed_cost_cents']}"
    )


def test_committed_restored_exactly_on_abort():
    """PRD section 3.6: "the chapter's `committed_cost_cents` falls by the
    plan's total with `posture` recomputed" — approve paired with abort
    conserves the chapter commitment with no drift, and "the wish reverts
    from `PLAN_APPROVED` or `READY_TO_SCHEDULE` back to `PLANNING`".

    Design: Difficulty/compensating_invariant/chapter_committed_approve_abort_conservation
    """
    ctx = setup_planning_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="two toy trucks",
        cash_cost_cents=100000,
        offer_specs=[{"quantity_total": 10, "unit_retail_cents": 12000,
                      "quantity": 2}])
    chapter_id = ctx["chapter"]["id"]
    submit_plan(ctx["plan"]["id"])
    approve_plan(ctx["plan"]["id"])
    assert get_chapter(chapter_id)["committed_cost_cents"] == 124000

    abort_plan(ctx["plan"]["id"], reason="replanning")
    restored = get_chapter(chapter_id)
    assert_chapter_fiscal(restored, committed_cost_cents=0, posture="OPEN")
    assert get_wish(ctx["wish"]["id"])["status"] == "PLANNING"
