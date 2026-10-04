"""Quality scoring: total_score single-rounding, dispute lifecycle branches,
the auto-coaching cascade threshold, and open-plan conservation."""
from test_helpers import (
    TEST_USERS,
    api_client,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    QA,
    SUP,
    answer_call,
    complete_call,
    create_agent,
    create_review,
    get_review,
    list_coaching_plans,
    make_agent_headers,
    register_call,
    route_call,
    set_clock,
    setup_completed_call,
    setup_routable,
    transition_review,
)
from test_helpers.fixtures import certify_agent as certify  # noqa: F401

QA_H = TEST_USERS["quality_analyst_headers"]
SUP_H = TEST_USERS["supervisor_headers"]


def test_quality_total_score_single_rounding_boundary():
    """PRD §3.5: "The review's `total_score` is computed immediately as the
    round-half-up of the accuracy weight times the accuracy score plus the
    compliance weight times the compliance score, computed at full precision
    and rounded exactly once to an integer."
    PRD §2.7: "the weighted sum is rounded exactly once at full precision —
    rounding the two weighted components separately and then summing is a
    rejected alternative, because at exact half-point boundaries the results
    diverge, and a half always rounds up, never to even."

    Design: Difficulty/combinatorial_formula/quality_total_score_single_rounding
    """
    ctx = setup_completed_call()
    r1 = create_review(
        ctx["call"]["id"], accuracy_score=55, compliance_score=62,
        accuracy_weight=0.3,
    )
    assert r1["total_score"] == 60, "0.3*55 + 0.7*62 = 59.9, single round-half-up"
    r2 = create_review(
        ctx["call"]["id"], accuracy_score=55, compliance_score=63,
        accuracy_weight=0.3,
    )
    assert r2["total_score"] == 61, "0.3*55 + 0.7*63 = 60.6, single round-half-up"


def test_quality_total_score_half_point_rounds_up_not_to_even():
    """PRD §2.7: "the weighted sum is rounded exactly once at full precision —
    rounding the two weighted components separately and then summing is a
    rejected alternative, because at exact half-point boundaries the results
    diverge, and a half always rounds up, never to even."

    Design: Difficulty/combinatorial_formula/quality_total_score_single_rounding
    """
    ctx = setup_completed_call()
    # 0.5*61 + 0.5*62 = 61.5 -> 62 (half rounds up, never to even).
    review = create_review(
        ctx["call"]["id"], accuracy_score=61, compliance_score=62
    )
    assert review["total_score"] == 62


def test_quality_review_dispute_cycle_overturned_excludes_from_qa():
    """PRD §3.5: "`to_status` of `OVERTURNED` voids it — the review is
    excluded from `QA_AVG` aggregation and from coaching triggers, and `final`
    stays false. `ACCEPTED`, `UPHELD`, and `OVERTURNED` are all terminal".
    PRD §2.5: "If the requested target is not reachable from the current state
    — including re-firing a transition that has already happened, or any
    request against a resource already in a terminal state — the request is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/quality_review_dispute_cycle_overturned_excludes_from_qa
    """
    ctx = setup_completed_call()
    review = create_review(
        ctx["call"]["id"], accuracy_score=65, compliance_score=65
    )
    transition_review(
        review["id"], "DISPUTED", make_agent_headers(ctx["agent"]["id"])
    )
    overturned = transition_review(review["id"], "OVERTURNED", QA_H)
    assert overturned["status"] == "OVERTURNED"
    assert overturned["final"] is False

    plans = list_coaching_plans({"agent_id": ctx["agent"]["id"]})
    assert len(plans) == 0, "OVERTURNED fires no coaching cascade"

    resp = api_client.transition_quality_review(
        review["id"], {"to_status": "ACCEPTED"}, QA_H
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_dispute_then_upheld_sets_final_and_confirms_score():
    """PRD §3.5: "`to_status` of `UPHELD` confirms the score, sets `final` to
    true, and fires the identical auto-coaching cascade as acceptance".
    PRD §3.5: "Dispute, requested with `to_status` of `DISPUTED`, is the
    reviewed agent's prerogative: the acting `X-User-ID` must equal the
    `handled_by_agent_id` of the reviewed call".

    Design: Difficulty/non_linear_state_machine/quality_review_dispute_cycle_overturned_excludes_from_qa
    """
    ctx = setup_completed_call()
    review = create_review(
        ctx["call"]["id"], accuracy_score=90, compliance_score=90
    )
    disputed = transition_review(
        review["id"], "DISPUTED", make_agent_headers(ctx["agent"]["id"])
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["final"] is False
    upheld = transition_review(review["id"], "UPHELD", QA_H)
    assert upheld["status"] == "UPHELD"
    assert upheld["final"] is True
    # Score 90 >= 70: the auto-coaching cascade does not fire.
    assert list_coaching_plans({"agent_id": ctx["agent"]["id"]}) == []


def test_coaching_plan_auto_triggered_on_low_final_score():
    """PRD §3.5: "When a final review's `total_score` is below the auto-coach
    threshold of 70, and the agent named by the reviewed call's
    `handled_by_agent_id` has no CoachingPlan in `OPEN` or `ESCALATED`, and no
    `AUTO_QUALITY` CoachingPlan already exists for that agent with a
    `created_at` within the trailing seven days up to now, the system creates
    a new CoachingPlan for that agent with `trigger` of `AUTO_QUALITY`, a
    `due_date` fourteen days after now, and `status` `OPEN`."

    Design: Corner/state_machines/coaching_plan_auto_triggered_on_low_final_score
    """
    ctx = setup_routable()
    agent_b = create_agent(full_name="Agent Two")
    certify(agent_b["id"], ctx["course"]["id"])

    def completed_call(enqueued_at, agent_id):
        call = register_call(ctx["contract"]["id"], enqueued_at=enqueued_at)
        call = route_call(call["id"])
        call = answer_call(call, agent_id)
        call = complete_call(call, agent_id)
        return call

    call_a = completed_call("2026-09-05T09:00:00Z", ctx["agent"]["id"])
    call_b = completed_call("2026-09-05T09:01:00Z", agent_b["id"])

    review_a = create_review(call_a["id"], accuracy_score=69, compliance_score=69)
    review_b = create_review(call_b["id"], accuracy_score=70, compliance_score=70)

    set_clock("2026-09-05T12:00:00Z")
    transition_review(review_a["id"], "ACCEPTED", QA_H)
    transition_review(review_b["id"], "ACCEPTED", QA_H)

    plans_a = list_coaching_plans({"agent_id": ctx["agent"]["id"]})
    assert len(plans_a) == 1
    assert plans_a[0]["trigger"] == "AUTO_QUALITY"
    assert plans_a[0]["status"] == "OPEN"
    assert plans_a[0]["due_date"] == "2026-09-19T12:00:00.000Z"

    plans_b = list_coaching_plans({"agent_id": agent_b["id"]})
    assert len(plans_b) == 0, "70 is not below the threshold of 70"


def test_coaching_plan_auto_triggered_exactly_at_threshold_creates_none():
    """PRD §3.5: "When a final review's `total_score` is below the auto-coach
    threshold of 70, and the agent named by the reviewed call's
    `handled_by_agent_id` has no CoachingPlan in `OPEN` or `ESCALATED`, and no
    `AUTO_QUALITY` CoachingPlan already exists for that agent with a
    `created_at` within the trailing seven days up to now, the system creates
    a new CoachingPlan for that agent with `trigger` of `AUTO_QUALITY`, a
    `due_date` fourteen days after now, and `status` `OPEN`."

    Design: Corner/state_machines/coaching_plan_auto_triggered_on_low_final_score
    """
    ctx = setup_completed_call()
    review = create_review(ctx["call"]["id"], accuracy_score=70, compliance_score=70)
    transition_review(review["id"], "ACCEPTED", QA_H)
    assert list_coaching_plans({"agent_id": ctx["agent"]["id"]}) == []


def test_duplicate_open_plan_rejected():
    """PRD §3.5: "At most one plan per agent may be open at any time: creating
    any plan — manual or automatic — for an agent who already has a plan in
    `OPEN` or `ESCALATED` is rejected with `ERR_DUPLICATE_PLAN` (HTTP 409)."

    Design: Corner/state_machines/duplicate_open_plan_rejected
    """
    agent = create_agent()
    first = validate_success(
        api_client.create_coaching_plan(
            {"agent_id": agent["id"], "due_date": "2026-10-01T00:00:00Z"}, SUP_H
        ),
        201,
    )
    dup = api_client.create_coaching_plan(
        {"agent_id": agent["id"], "due_date": "2026-10-02T00:00:00Z"}, SUP_H
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_PLAN)

    validate_success(
        api_client.transition_coaching_plan(
            first["id"], {"to_status": "ESCALATED"}, SUP_H
        )
    )
    dup2 = api_client.create_coaching_plan(
        {"agent_id": agent["id"], "due_date": "2026-10-02T00:00:00Z"}, SUP_H
    )
    validate_error(dup2, ApiErrorId.ERR_DUPLICATE_PLAN)

    plans = list_coaching_plans({"agent_id": agent["id"]})
    assert len(plans) == 1


def test_dispute_cycle_conserves_open_plan_count():
    """PRD §3.5: "When a final review's `total_score` is below the auto-coach
    threshold of 70, and the agent named by the reviewed call's
    `handled_by_agent_id` has no CoachingPlan in `OPEN` or `ESCALATED`, and no
    `AUTO_QUALITY` CoachingPlan already exists for that agent with a
    `created_at` within the trailing seven days up to now, the system creates
    a new CoachingPlan for that agent".
    PRD §3.5: "`to_status` of `OVERTURNED` voids it — the review is excluded
    from `QA_AVG` aggregation and from coaching triggers, and `final` stays
    false."
    PRD §3.5: "From `OPEN`, a `Supervisor` may drive a plan to `COMPLETED`, to
    `ESCALATED`, or to `CANCELLED`".

    Design: Difficulty/compensating_invariant/dispute_cycle_conserves_open_plan_count
    """
    ctx = setup_routable()
    agent_id = ctx["agent"]["id"]
    calls = []
    for i in range(3):
        call = register_call(
            ctx["contract"]["id"], enqueued_at=f"2026-09-05T09:0{i}:00Z"
        )
        call = route_call(call["id"])
        call = answer_call(call, agent_id)
        call = complete_call(call, agent_id)
        calls.append(call)

    r1 = create_review(calls[0]["id"], accuracy_score=60, compliance_score=60)
    r2 = create_review(calls[1]["id"], accuracy_score=62, compliance_score=62)
    r3 = create_review(calls[2]["id"], accuracy_score=64, compliance_score=64)

    transition_review(r1["id"], "ACCEPTED", QA_H)
    plans = list_coaching_plans({"agent_id": agent_id})
    open_plans = [p for p in plans if p["status"] in ("OPEN", "ESCALATED")]
    assert len(open_plans) == 1
    assert open_plans[0]["trigger"] == "AUTO_QUALITY"

    transition_review(r2["id"], "ACCEPTED", QA_H)
    plans = list_coaching_plans({"agent_id": agent_id})
    open_plans = [p for p in plans if p["status"] in ("OPEN", "ESCALATED")]
    assert len(open_plans) == 1, "second accept dedups against the OPEN plan"

    transition_review(r3["id"], "DISPUTED", make_agent_headers(agent_id))
    transition_review(r3["id"], "OVERTURNED", QA_H)
    plans = list_coaching_plans({"agent_id": agent_id})
    open_plans = [p for p in plans if p["status"] in ("OPEN", "ESCALATED")]
    assert len(open_plans) == 1, "OVERTURNED changes the plan count by 0"

    validate_success(
        api_client.transition_coaching_plan(
            open_plans[0]["id"], {"to_status": "CANCELLED"}, SUP_H
        )
    )
    plans = list_coaching_plans({"agent_id": agent_id, "status": "OPEN"})
    assert len(plans) == 0


def test_second_low_accept_within_seven_days_creates_no_new_plan():
    """PRD §3.5: "no `AUTO_QUALITY` CoachingPlan already exists for that agent
    with a `created_at` within the trailing seven days up to now".

    Design: Difficulty/compensating_invariant/dispute_cycle_conserves_open_plan_count
    """
    ctx = setup_routable()
    agent_id = ctx["agent"]["id"]
    calls = []
    for i in range(2):
        call = register_call(
            ctx["contract"]["id"], enqueued_at=f"2026-09-05T09:0{i}:00Z"
        )
        call = route_call(call["id"])
        call = answer_call(call, agent_id)
        call = complete_call(call, agent_id)
        calls.append(call)
    r1 = create_review(calls[0]["id"], accuracy_score=60, compliance_score=60)
    r2 = create_review(calls[1]["id"], accuracy_score=61, compliance_score=61)

    transition_review(r1["id"], "ACCEPTED", QA_H)
    first_plan = list_coaching_plans({"agent_id": agent_id})[0]
    # Complete the OPEN plan so only the 7-day dedup window can suppress the
    # next cascade, then accept the second review six days after the first.
    validate_success(
        api_client.transition_coaching_plan(
            first_plan["id"], {"to_status": "COMPLETED"}, SUP_H
        )
    )
    set_clock("2026-09-07T00:00:00Z")
    transition_review(r2["id"], "ACCEPTED", QA_H)
    plans = list_coaching_plans({"agent_id": agent_id})
    assert len(plans) == 1, (
        "a second AUTO_QUALITY plan inside the trailing seven days is suppressed"
    )
