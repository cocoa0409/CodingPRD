"""Cycle-bounded and externally gated state machines (PRD §3.8, §3.10)."""
from test_helpers import (
    ApiErrorId,
    commission_review,
    create_draft_plan_with_basics,
    file_testimony,
    get_plan,
    get_success_data,
    open_plan_for_comment,
    register_intervenor,
    set_clock,
    setup_plan_under_review,
    submit_plan_for_review,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_AUG_01, CLOCK_AUG_31, CLOCK_NOV_01, CLOCK_OCT_01, CLOCK_DEFAULT
from test_helpers.fixtures import PLANNER
from test_helpers.test_users import make_intervener_headers


def test_plan_review_reopen_third_reopen_rejected(api):
    """PRD §3.8: "While `reopen_count` is below the hard cap of two, the planner may
    reopen a plan sitting in `REJECTED`; a reopen attempted when the count has already
    reached two is rejected with `ERR_PLAN_REOPEN_LIMIT` (HTTP 422), and reopening a
    plan in any status other than `REJECTED` is `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/resource_plan_review_reopen_cycle_bounded
    """
    set_clock(CLOCK_AUG_01)
    plan, _portfolio = create_draft_plan_with_basics(plan_name="IRP Cycle")
    plan_id = plan["id"]

    # Round 1: open 2026-08-01, window closes 2026-08-31.
    open_plan_for_comment(plan_id)
    set_clock(CLOCK_AUG_31)
    submit_plan_for_review(plan_id)
    commission_review(plan_id, "REJECT")
    resp = api.reopen_plan(plan_id, PLANNER)
    validate_success(resp)

    # Round 2: reopens 2026-08-31 (window to 2026-09-30).
    open_plan_for_comment(plan_id)
    set_clock(CLOCK_OCT_01)
    submit_plan_for_review(plan_id)
    commission_review(plan_id, "REJECT")
    resp = api.reopen_plan(plan_id, PLANNER)
    validate_success(resp)

    # Round 3: submitted_on must stay on or before Sept 1 of the cycle year.
    set_clock(CLOCK_DEFAULT)
    open_plan_for_comment(plan_id)
    set_clock(CLOCK_NOV_01)
    submit_plan_for_review(plan_id)
    commission_review(plan_id, "REJECT")

    # The third reopen exceeds the hard cap of two.
    resp = api.reopen_plan(plan_id, PLANNER)
    validate_error(resp, ApiErrorId.ERR_PLAN_REOPEN_LIMIT)

    plan_after = get_plan(plan_id)
    assert plan_after["reopen_count"] == 2
    assert plan_after["status"] == "REJECTED"


def test_plan_review_reopen_cycle_first_two_reopens_succeed(api):
    """PRD §3.8: "While `reopen_count` is below the hard cap of two, the planner may
    reopen a plan sitting in `REJECTED`; a reopen attempted when the count has already
    reached two is rejected with `ERR_PLAN_REOPEN_LIMIT` (HTTP 422), and reopening a
    plan in any status other than `REJECTED` is `ERR_INVALID_STATE`."
    PRD §3.8: "The transition `REJECTED → DRAFT` increments `reopen_count` by 1,
    unfreezes every portfolio (`FROZEN → DRAFT`, each portfolio's `version` bumping),
    unlocks every forecast row, clears `preferred_portfolio_id`, `approved_snapshot_id`,
    both comment-window dates, and `submitted_on`, and bumps the plan's `version` —
    returning the plan to a fully editable state for another pass through the cycle."

    Design: Difficulty/non_linear_state_machine/resource_plan_review_reopen_cycle_bounded
    """
    set_clock(CLOCK_AUG_01)
    plan, _portfolio = create_draft_plan_with_basics(plan_name="IRP Cycle2")
    plan_id = plan["id"]

    open_plan_for_comment(plan_id)
    set_clock(CLOCK_AUG_31)
    submit_plan_for_review(plan_id)
    commission_review(plan_id, "REJECT")
    first = validate_success(api.reopen_plan(plan_id, PLANNER))
    assert first["status"] == "DRAFT"
    assert first["reopen_count"] == 1

    open_plan_for_comment(plan_id)
    set_clock(CLOCK_OCT_01)
    submit_plan_for_review(plan_id)
    commission_review(plan_id, "REJECT")
    second = validate_success(api.reopen_plan(plan_id, PLANNER))
    assert second["status"] == "DRAFT"
    assert second["reopen_count"] == 2


def test_testimony_withdraw_refile_cycle_preserves_volume(api):
    """PRD §3.10: "Its owner — and only its owner, with ownership mismatches rejected
    as `ERR_FORBIDDEN` — may withdraw it (`FILED → WITHDRAWN`) and later refile it
    (`WITHDRAWN → FILED`), each gated on the plan still being `UNDER_REVIEW` and each
    bumping the testimony's `version`; refiled testimony keeps its original
    `volume_no`, which is never reassigned."

    Design: Difficulty/non_linear_state_machine/testimony_withdraw_refile_cycle
    """
    intervenor = register_intervenor(legal_name="Citizens Utility Board")
    plan, _portfolio = setup_plan_under_review(plan_name="IRP Testi")
    headers = make_intervener_headers(intervenor["id"])

    testimony = file_testimony(plan["id"], intervenor["id"],
                               body="The electrification adder is understated.")
    assert testimony["volume_no"] == 1
    assert testimony["version"] == 1

    withdrawn = validate_success(api.withdraw_testimony(testimony["id"], headers))
    assert withdrawn["status"] == "WITHDRAWN"

    refiled = validate_success(api.refile_testimony(testimony["id"], headers))
    assert refiled["status"] == "FILED"
    assert refiled["volume_no"] == testimony["volume_no"] == 1
    assert refiled["version"] == 3


def test_testimony_withdraw_refile_cycle_is_repeatable(api):
    """PRD §3.10: "Its owner — and only its owner, with ownership mismatches rejected
    as `ERR_FORBIDDEN` — may withdraw it (`FILED → WITHDRAWN`) and later refile it
    (`WITHDRAWN → FILED`), each gated on the plan still being `UNDER_REVIEW` and each
    bumping the testimony's `version`; refiled testimony keeps its original
    `volume_no`, which is never reassigned."

    Design: Difficulty/non_linear_state_machine/testimony_withdraw_refile_cycle
    """
    intervenor = register_intervenor(legal_name="Cycle Intervenor")
    plan, _portfolio = setup_plan_under_review(plan_name="IRP Testi2")
    headers = make_intervener_headers(intervenor["id"])

    testimony = file_testimony(plan["id"], intervenor["id"])

    # The FILED -> WITHDRAWN -> FILED loop is not bounded by a counter: it repeats
    # while the plan stays UNDER_REVIEW, always keeping the original volume number.
    for expected_version in (2, 3, 4, 5):
        if expected_version % 2 == 0:
            data = validate_success(api.withdraw_testimony(testimony["id"], headers))
            assert data["status"] == "WITHDRAWN"
        else:
            data = validate_success(api.refile_testimony(testimony["id"], headers))
            assert data["status"] == "FILED"
        assert data["version"] == expected_version
        assert data["volume_no"] == 1
