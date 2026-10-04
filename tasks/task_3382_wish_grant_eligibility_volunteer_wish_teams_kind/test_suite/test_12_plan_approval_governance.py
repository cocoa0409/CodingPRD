"""Plan approval governance: segregation of duties, the frozen-posture and
budget-cap rejections, abort terminal lockdown, and the state-vs-fiscal guard
order on approve.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    abort_plan,
    api_client,
    approve_plan,
    get_chapter,
    get_fulfillment_plan,
    get_wish,
    setup_frozen_chapter,
    setup_planning_wish,
    submit_plan,
    validate_error,
)

CHAPTER_DIRECTOR = TEST_USERS["chapter_director_headers"]          # dir-1
CHAPTER_DIRECTOR_ALT = TEST_USERS["chapter_director_alt_headers"]  # dir-2
NATIONAL_DIRECTOR = TEST_USERS["national_director_headers"]        # nat-1


def test_sod_plan_creator_cannot_approve():
    """PRD section 3.6: "segregation of duties forbids the plan's creator from
    approving it, comparing the plan's `created_by_user_id` to the approver's
    `X-User-ID` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403)"
    PRD section 2.1: "`ChapterDirector` approves and aborts plans and may also
    create them, subject to segregation of duties."

    Design: Corner/validations/sod_plan_creator_cannot_approve
    """
    ctx = setup_planning_wish(wish_type="RECEIVE_ITEM", cash_cost_cents=100000,
                              creator_headers=CHAPTER_DIRECTOR)
    plan = ctx["plan"]
    assert plan["created_by_user_id"] == "dir-1"
    submit_plan(plan["id"], headers=CHAPTER_DIRECTOR)

    own = api_client.approve_plan(plan["id"], CHAPTER_DIRECTOR)
    validate_error(own, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    other = approve_plan(plan["id"], approver_headers=CHAPTER_DIRECTOR_ALT)
    assert other["status"] == "APPROVED"
    assert other["approved_by_user_id"] == "dir-2"


def test_approve_rejected_when_chapter_frozen():
    """PRD section 2.9: "While a chapter is `FROZEN`, every plan approval is
    rejected with `ERR_CHAPTER_BUDGET_FROZEN` (HTTP 409)."

    Design: Corner/validations/approve_rejected_when_chapter_frozen
    """
    frozen = setup_frozen_chapter()  # committed 1900000 of 2000000 -> FROZEN
    chapter = frozen["chapter"]
    assert chapter["posture"] == "FROZEN"
    assert chapter["committed_cost_cents"] == 1900000

    ctx = setup_planning_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="a dollhouse",
        chapter=chapter, lead=frozen["lead"], second=frozen["second"],
        set_clock_first=False, zip_code="50077", child_full_name="Mara Chen",
        child_date_of_birth="2014-11-20", cash_cost_cents=100000,
        visit_start="2026-09-07T09:00:00Z", visit_end="2026-09-07T11:00:00Z")
    submit_plan(ctx["plan"]["id"])

    resp = api_client.approve_plan(ctx["plan"]["id"], CHAPTER_DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_CHAPTER_BUDGET_FROZEN)
    assert get_fulfillment_plan(ctx["plan"]["id"])["status"] == "PENDING_APPROVAL"
    assert get_chapter(chapter["id"])["committed_cost_cents"] == 1900000


def test_approve_rejected_when_budget_would_be_exceeded():
    """PRD section 2.9: "an approval that would push `committed_cost_cents` —
    including the pending plan's full total — above the chapter's
    `fiscal_year_budget_cents` is rejected with `ERR_CHAPTER_BUDGET_EXCEEDED`
    (HTTP 422)."

    Design: Corner/validations/approve_rejected_when_budget_would_be_exceeded
    """
    ctx = setup_planning_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="a gaming pc",
        chapter_overrides={"territory_zip_prefixes": ["300"],
                           "fiscal_year_budget_cents": 500000,
                           "target_avg_cost_per_wish_cents": 10000000},
        zip_code="30012", cash_cost_cents=600000)
    submit_plan(ctx["plan"]["id"])

    resp = api_client.approve_plan(ctx["plan"]["id"], CHAPTER_DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_CHAPTER_BUDGET_EXCEEDED)
    assert get_fulfillment_plan(ctx["plan"]["id"])["status"] == "PENDING_APPROVAL"


def test_plan_abort_terminal_lockdown():
    """PRD section 3.6: abort operates from `PENDING_APPROVAL` or `APPROVED`;
    a `CANCELLED` plan is in neither from-state, so a second abort fails the
    state check (`ERR_INVALID_PLAN_STATE`, HTTP 409).
    PRD section 3.6: "From `PENDING_APPROVAL`, aborting moves the plan to
    `CANCELLED`, releases its `RESERVED` lines to `RELEASED` and returns their
    quantities to the offers, recomputes `in_kind_value_cents` without the
    released lines, and leaves the wish in `PLANNING`."

    Design: Corner/state_machines/plan_abort_terminal_lockdown
    """
    ctx = setup_planning_wish(wish_type="RECEIVE_ITEM", cash_cost_cents=50000)
    plan = ctx["plan"]
    submit_plan(plan["id"])
    aborted = abort_plan(plan["id"])
    assert aborted["status"] == "CANCELLED"
    assert get_wish(ctx["wish"]["id"])["status"] == "PLANNING"

    again = api_client.abort_plan(plan["id"], {}, CHAPTER_DIRECTOR)
    validate_error(again, ApiErrorId.ERR_INVALID_PLAN_STATE)
    assert get_wish(ctx["wish"]["id"])["status"] == "PLANNING"


def _frozen_chapter_with_draft_plan():
    """A FROZEN chapter (committed 1900000 of 2000000) plus a third wish whose
    plan sits in DRAFT (never submitted)."""
    frozen = setup_frozen_chapter()
    ctx = setup_planning_wish(
        wish_type="RECEIVE_ITEM", captured_true_wish="a dollhouse",
        chapter=frozen["chapter"], lead=frozen["lead"],
        second=frozen["second"], set_clock_first=False, zip_code="50077",
        child_full_name="Mara Chen", child_date_of_birth="2014-11-20",
        cash_cost_cents=100000, visit_start="2026-09-07T09:00:00Z",
        visit_end="2026-09-07T11:00:00Z")
    return frozen, ctx


def test_approve_draft_plan_in_frozen_chapter_reports_state_error():
    """PRD section 3.6: "the plan must be `PENDING_APPROVAL`
    (`ERR_INVALID_PLAN_STATE`)" is the first approve guard, and "Because the
    fiscal rules sit after the state and duty checks, a frozen chapter
    surfaces the freeze error even when the budget cap would also be breached"
    — so a DRAFT plan in a FROZEN chapter surfaces the state error, not the
    freeze error.
    PRD section 2.8: "validations run in a fixed priority order and the
    earliest failure is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/approve_state_error_beats_budget_frozen
    """
    frozen, ctx = _frozen_chapter_with_draft_plan()
    assert frozen["chapter"]["posture"] == "FROZEN"

    resp = api_client.approve_plan(ctx["plan"]["id"], NATIONAL_DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_PLAN_STATE)
    assert get_fulfillment_plan(ctx["plan"]["id"])["status"] == "DRAFT", (
        "no side effects may fire when the state guard rejects the approval"
    )


def test_approve_draft_plan_in_frozen_chapter_leaves_ledgers_untouched():
    """PRD section 2.8: "Only after the envelope is sound do state-machine
    from-state checks run, in this entity order where several apply:
    volunteer, referral, wish, team, visit, plan, offer, clearance, then event
    — each surfacing its own `ERR_INVALID_*_STATE` code."
    PRD section 2.8: "The stale-version check (`ERR_STALE_VERSION`) follows
    the state checks, then segregation of duties, then medical-clearance
    validity for scheduling, then the temporal rules — team visit overlap,
    treatment blackout, and the urgent-case scheduling deadline — then
    donation expiry, and finally the remaining business constraints and
    fiscal rules described throughout §3."
    The rejected approval leaves the chapter commitment and the wish exactly
    as they were.

    Design: Difficulty/priority_pair_validation_conflict/approve_state_error_beats_budget_frozen
    """
    frozen, ctx = _frozen_chapter_with_draft_plan()
    chapter_id = frozen["chapter"]["id"]
    assert frozen["chapter"]["committed_cost_cents"] == 1900000

    resp = api_client.approve_plan(ctx["plan"]["id"], NATIONAL_DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_PLAN_STATE)

    chapter = get_chapter(chapter_id)
    assert chapter["committed_cost_cents"] == 1900000
    assert chapter["posture"] == "FROZEN"
    assert get_wish(ctx["wish"]["id"])["status"] == "PLANNING"
