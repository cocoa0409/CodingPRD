"""Difficulty queue A: combinatorial formulas (adoption health, escalation)."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_paginated,
    admin_of,
    approver_as,
    create_feature_train,
    create_tenant,
    enroll,
    get_train,
    initiate,
    set_clock,
    setup_active_definition,
)


def _health(tenant_id: str, admin: dict) -> dict:
    return get_success_data(api_client.get_adoption_health(tenant_id, admin))


def test_adoption_health_premium_late_penalty(api):
    """PRD §3.7: "It starts from a base of 100 and subtracts 5 for each adoption
    in `ENROLLED` or `TESTING_PASSED` and 15 for each adoption in `DEFERRED`."
    PRD §3.7: "for each feature on a train currently `OPT_IN_OPEN` that remains
    `ENROLLED` when the logical clock has passed the point three quarters of
    the way through the effective opt-in window, subtract 10. The effective
    window is the train's window length in whole days plus a 14-day extension
    when the tenant's `service_level_tier` is `PREMIUM`".

    Window 2026-09-01 -> 2026-10-17 is 46 days; PREMIUM effective window is
    46 + 14 = 60 days; three quarters is 45 days; the late point is
    2026-10-16T00:00:00Z. At 2026-10-17 the train is still OPT_IN_OPEN (its end
    is an inclusive boundary) and the clock is past the late point.

    Design: Difficulty/combinatorial_formula/adoption_health_tier_window_penalty
    """
    tenant = create_tenant("T-CF1", service_level_tier="PREMIUM")
    admin = admin_of(tenant)
    train = create_feature_train(
        "F2026-R1", "2026-09-01T00:00:00Z", "2026-10-17T00:00:00Z",
        "2026-11-01T00:00:00Z",
    )
    set_clock("2026-09-02T00:00:00Z")  # train window opens
    assert get_train(train["id"])["status"] == "OPT_IN_OPEN"
    adoption = enroll(tenant["id"], train["id"], "F1", admin)
    assert adoption["status"] == "ENROLLED"

    set_clock("2026-10-17T00:00:00Z")  # past the late point; window still open
    assert get_train(train["id"])["status"] == "OPT_IN_OPEN"

    health = _health(tenant["id"], admin)
    assert health["enrolled_count"] == 1
    assert health["deferred_count"] == 0
    assert health["late_count"] == 1
    # 100 - 5 (ENROLLED) - 10 (late) = 85
    assert health["score"] == 85, f"expected score 85, got {health['score']}"


def test_adoption_health_not_late_at_exact_threshold(api):
    """PRD §3.7: "for each feature on a train currently `OPT_IN_OPEN` that
    remains `ENROLLED` when the logical clock has passed the point three
    quarters of the way through the effective opt-in window, subtract 10."
    At exactly the three-quarters point the clock has not passed it, so no
    late-enrollment penalty applies: 100 - 5 (ENROLLED) = 95.

    Design: Difficulty/combinatorial_formula/adoption_health_tier_window_penalty
    """
    tenant = create_tenant("T-CF1B", service_level_tier="PREMIUM")
    admin = admin_of(tenant)
    train = create_feature_train(
        "F2026-R1", "2026-09-01T00:00:00Z", "2026-10-17T00:00:00Z",
        "2026-11-01T00:00:00Z",
    )
    set_clock("2026-09-02T00:00:00Z")
    enroll(tenant["id"], train["id"], "F1", admin)

    # Exactly start + 45 days = the three-quarters point of the 60-day
    # effective window: not yet "passed".
    set_clock("2026-10-16T00:00:00Z")
    assert get_train(train["id"])["status"] == "OPT_IN_OPEN"

    health = _health(tenant["id"], admin)
    assert health["enrolled_count"] == 1
    assert health["late_count"] == 0
    assert health["score"] == 95, f"expected score 95, got {health['score']}"


def _setup_return_cycle():
    """Definition with step 1 APPROVAL and step 2 APPROVAL returning to step 1;
    escalation_after_hours 24."""
    return setup_active_definition(
        "T-CF2",
        steps=[{"order": 1}, {"order": 2, "return_target": 1}],
        definition_overrides={"escalation_after_hours": 24},
    )


def test_escalation_per_step_clock_reset_by_return(api):
    """PRD §3.6: "Each step's pending window is computed from that step's own
    advance timestamp, with per-step rounding to whole hours, half-up on the
    minute remainder, applied before comparison; instance-level age divided by
    the escalation window and floored is not the rule and yields different
    counts after a return resets a step's clock."
    PRD §3.6: "Escalation fires only when the clock is strictly past that
    deadline — an exact tie is not yet escalated."

    Step 1 is re-pended by a RETURN at 2026-09-02T02:00, so its due instant is
    2026-09-03T02:00. At 01:29 the instance is 25h old (the rejected
    instance-age rule would escalate) yet no escalation may fire; at 02:29 one
    escalation must have fired.

    Design: Difficulty/combinatorial_formula/escalation_per_step_rounding_vs_instance_floor
    """
    ctx = _setup_return_cycle()
    tid, admin = ctx["tenant"]["id"], ctx["admin"]
    approver = approver_as(ctx["approver"]["id"])

    set_clock("2026-09-02T00:30:00Z")
    inst = initiate(ctx)  # step 1 pends at 00:30
    iid = inst["id"]

    set_clock("2026-09-02T01:00:00Z")
    get_success_data(api_client.approve_step(tid, iid, 1, {}, approver))

    set_clock("2026-09-02T02:00:00Z")
    get_success_data(
        api_client.return_step(tid, iid, 2, {"comment": "revise"}, approver)
    )  # step 1 re-pends at 02:00

    set_clock("2026-09-03T01:29:00Z")  # 23h29m into step 1's own window
    inst = get_success_data(api_client.get_transaction(tid, iid, admin))
    assert inst["escalation_count"] == 0, (
        "per-step rule: 23h29m < 24h after the RETURN reset, so no escalation; "
        f"an instance-age rule would already count one (got "
        f"{inst['escalation_count']})"
    )

    set_clock("2026-09-03T02:29:00Z")  # 24h29m into step 1's own window
    inst = get_success_data(api_client.get_transaction(tid, iid, admin))
    assert inst["escalation_count"] == 1, (
        f"exactly one escalation must have fired, got {inst['escalation_count']}"
    )
    events, meta = validate_paginated(
        api_client.list_events(tid, iid, admin, params={"action": "ESCALATE"})
    )
    assert meta["total_count"] == 1
    assert events[0]["step_order"] == 1
    assert events[0]["actor_worker_id"] is None, (
        "system actions record no actor_worker_id"
    )


def test_escalation_exact_tie_not_escalated(api):
    """PRD §3.6: "The escalation sweep examines each pending step and compares
    the logical clock against the `occurred_at` of the `ADVANCE` event that
    made that step pending plus the definition's `escalation_after_hours`.
    Escalation fires only when the clock is strictly past that deadline — an
    exact tie is not yet escalated."

    Design: Difficulty/combinatorial_formula/escalation_per_step_rounding_vs_instance_floor
    """
    ctx = setup_active_definition(
        "T-CF2B", steps=[{"order": 1}],
        definition_overrides={"escalation_after_hours": 24},
    )
    tid, admin = ctx["tenant"]["id"], ctx["admin"]

    set_clock("2026-09-02T00:30:00Z")
    inst = initiate(ctx)  # step 1 pends at 00:30; due 2026-09-03T00:30
    iid = inst["id"]

    set_clock("2026-09-03T00:30:00Z")  # exact tie
    inst = get_success_data(api_client.get_transaction(tid, iid, admin))
    assert inst["escalation_count"] == 0, "an exact tie is not yet escalated"

    set_clock("2026-09-03T00:31:00Z")  # strictly past
    inst = get_success_data(api_client.get_transaction(tid, iid, admin))
    assert inst["escalation_count"] == 1
