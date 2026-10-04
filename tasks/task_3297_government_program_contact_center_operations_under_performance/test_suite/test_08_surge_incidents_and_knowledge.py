"""Surge-window effects on money and staffing, incident reporting SLA,
knowledge retraining, terminal-state guards, and the conditional OCC field
on the unified transition surface."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_incident_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    BILL,
    OPS,
    SEC,
    SUP,
    answer_call,
    certify_agent,
    complete_call,
    create_agent,
    create_article,
    create_contract,
    create_course,
    create_draft_service_level,
    create_invoice,
    create_queue,
    create_review,
    create_surge_window,
    get_call,
    get_contract,
    get_invoice,
    get_surge_window,
    list_certifications,
    list_coaching_plans,
    list_invoice_lines,
    prepare_invoice,
    publish_article,
    register_call,
    route_call,
    set_clock,
    setup_routable,
    transition_review,
)

BILL_H = TEST_USERS["billing_analyst_headers"]
OPS_H = TEST_USERS["ops_manager_headers"]
SUP_H = TEST_USERS["supervisor_headers"]
SEC_H = TEST_USERS["security_officer_headers"]


def _certified_contract(agency, program_code="MEDICAID"):
    """ACTIVE contract + EFFECTIVE ASA SL + one certified agent (no queue
    needed for measurement/staffing tests)."""
    ctx = setup_routable(metric="ASA", target=30, agency_name=agency,
                         program_code=program_code)
    return ctx


def test_surge_window_multiplier_changes_staffing_target_and_gross():
    """PRD §3.7: "The surge multiplier used by money and staffing math — the
    same selector everywhere — is: the `expected_volume_factor` of the
    `ACTIVE` window for the contract and program at the instant in question;
    if none is active, that of the most recently `EXPIRED` window by
    `ends_on`, with ties broken by the latest `created_at`; if no window
    exists at all, 1.0."
    PRD §3.9: "The `staffing_target` is the baseline staffing of 10 multiplied
    by the surge multiplier for the program at period end — the selector of
    §3.7 — rounded up to the next integer. The surge multiplier affects the
    target only, never the actual."

    Design: Difficulty/cross_entity_state_dependency/surge_window_multiplier_changes_staffing_target_and_gross
    """
    # Distinct program codes per contract: certifications and staffing are
    # program-scoped (PRD §3.9), so two contracts sharing a program would
    # count each other's certified agents in gross.
    ctx_a = _certified_contract("Agency A", program_code="MEDICAID")
    win_a = create_surge_window(
        ctx_a["contract"]["id"],
        surge_type="PUBLIC_EVENT",
        starts_on="2026-09-15T00:00:00Z",
        ends_on="2026-09-30T00:00:00Z",
        expected_volume_factor=1.5,
    )

    ctx_b = _certified_contract("Agency B", program_code="SNAP")
    win_b = create_surge_window(
        ctx_b["contract"]["id"],
        program_code="SNAP",
        surge_type="PUBLIC_EVENT",
        starts_on="2026-09-16T00:00:00Z",
        ends_on="2026-09-30T00:00:00Z",
        expected_volume_factor=1.5,
    )
    validate_success(
        api_client.transition_surge_window(win_b["id"], {"to_status": "CANCELLED"}, OPS)
    )

    set_clock("2026-09-20T00:00:00Z")
    assert get_surge_window(win_a["id"])["status"] == "ACTIVE"

    inv_a = prepare_invoice(create_invoice(ctx_a["contract"]["id"])["id"])
    inv_b = prepare_invoice(create_invoice(ctx_b["contract"]["id"])["id"])

    assert inv_a["gross_cents"] == 56000, "50000 + round_half_up(4000 * 1.5)"
    assert inv_b["gross_cents"] == 54000, "cancelled window: multiplier 1.0"

    line_a = list_invoice_lines(inv_a["id"])[0]
    line_b = list_invoice_lines(inv_b["id"])[0]
    assert line_a["staffing_target"] == 15, "ceil(10 * 1.5)"
    assert line_b["staffing_target"] == 10, "ceil(10 * 1.0)"
    assert line_a["staffing_actual"] == 1
    assert line_b["staffing_actual"] == 1
    assert line_a["compliant"] is False
    assert line_b["compliant"] is False


def test_cancelled_window_contributes_no_multiplier():
    """PRD §3.7: "The surge multiplier used by money and staffing math — the
    same selector everywhere — is: the `expected_volume_factor` of the
    `ACTIVE` window for the contract and program at the instant in question;
    if none is active, that of the most recently `EXPIRED` window by
    `ends_on`, with ties broken by the latest `created_at`; if no window
    exists at all, 1.0."
    PRD §3.9: "Each such certification contributes the fixed per-agent monthly
    rate of 4000 cents, scaled by the program's surge multiplier clamped so it
    never falls below 1.0."

    Design: Difficulty/cross_entity_state_dependency/surge_window_multiplier_changes_staffing_target_and_gross
    """
    ctx = _certified_contract("Cancel Agency")
    win = create_surge_window(
        ctx["contract"]["id"],
        starts_on="2026-09-16T00:00:00Z",
        ends_on="2026-09-30T00:00:00Z",
        expected_volume_factor=1.5,
    )
    validate_success(
        api_client.transition_surge_window(win["id"], {"to_status": "CANCELLED"}, OPS)
    )
    set_clock("2026-09-20T00:00:00Z")
    invoice = prepare_invoice(create_invoice(ctx["contract"]["id"])["id"])
    assert invoice["gross_cents"] == 54000
    line = list_invoice_lines(invoice["id"])[0]
    assert line["staffing_target"] == 10


def test_reporting_sla_breach_boundary():
    """PRD §3.8: "For a `CRITICAL` incident, the reporting delay is the
    whole-second difference between `reported_at` and `occurred_at` divided by
    3600 to yield hours; when that delay is strictly greater than 24 hours,
    the incident reads back with `sla_breached` true. Late reporting never
    blocks creation — the incident is created regardless, and the breach flag
    is derived on every read rather than stored."

    Design: Corner/calculations/reporting_sla_breach_boundary
    """
    ctx = setup_routable()
    contract_id = ctx["contract"]["id"]

    set_clock("2026-09-02T00:00:00Z")
    inc_24h = validate_success(
        api_client.create_incident(
            create_incident_payload(
                contract_id, severity="CRITICAL", category="SECURITY",
                occurred_at="2026-09-01T00:00:00Z", description="exactly 24h",
            ),
            SEC_H,
        ),
        201,
    )
    set_clock("2026-09-02T00:00:01Z")
    inc_24h1s = validate_success(
        api_client.create_incident(
            create_incident_payload(
                contract_id, severity="CRITICAL", category="SECURITY",
                occurred_at="2026-09-01T00:00:00Z", description="24h plus 1s",
            ),
            SEC_H,
        ),
        201,
    )
    inc_low = validate_success(
        api_client.create_incident(
            create_incident_payload(
                contract_id, severity="LOW", category="DATA_QUALITY",
                occurred_at="2026-08-01T00:00:00Z",
                description="low severity long delay",
            ),
            SEC_H,
        ),
        201,
    )

    read_1 = validate_success(api_client.get_incident(inc_24h["id"], SEC_H))
    assert read_1["sla_breached"] is False, "exactly 24h is not strictly > 24"
    read_2 = validate_success(api_client.get_incident(inc_24h1s["id"], SEC_H))
    assert read_2["sla_breached"] is True
    read_3 = validate_success(api_client.get_incident(inc_low["id"], SEC_H))
    assert read_3["sla_breached"] is False, "LOW severity never breaches"


def test_call_route_blocked_when_contract_closed():
    """PRD §3.4: "Routing is requested by a `Supervisor` with `to_status` of
    `ASSIGNED`. Two preconditions gate it: the contract must be `ACTIVE`, and
    the selectors of §3.3 must find both an eligible queue and a certified
    available agent on it."
    PRD §2.5: "If the requested target is not reachable from the current state
    — including re-firing a transition that has already happened, or any
    request against a resource already in a terminal state — the request is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/call_route_blocked_when_contract_closed
    """
    ctx = setup_routable()
    contract_id = ctx["contract"]["id"]
    queue_id = ctx["queue"]["id"]
    validate_success(
        api_client.transition_queue(queue_id, {"to_status": "CLOSED"}, OPS)
    )
    validate_success(
        api_client.transition_contract(contract_id, {"to_status": "CLOSED"}, OPS)
    )
    assert get_contract(contract_id)["status"] == "CLOSED"

    call = register_call(contract_id, enqueued_at="2026-09-05T09:00:00Z")
    resp = api_client.transition_call(call["id"], {"to_status": "ASSIGNED"}, SUP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_call(call["id"])["status"] == "WAITING"
    assert get_call(call["id"])["queue_id"] is None


def test_closed_contract_rejects_routing_even_with_open_queue_elsewhere():
    """PRD §3.4: "Routing is requested by a `Supervisor` with `to_status` of
    `ASSIGNED`. Two preconditions gate it: the contract must be `ACTIVE`, and
    the selectors of §3.3 must find both an eligible queue and a certified
    available agent on it."
    PRD §3.1: "From `ACTIVE`, closure is permitted only when three fiscal
    gates all pass: no queue of the contract is `OPEN`, no invoice of the
    contract is in `DRAFT`, `SUBMITTED`, or `APPROVED`, and no incident of the
    contract is in `OPEN`, `CONTAINED`, or `RESOLVED`."

    Design: Difficulty/cross_entity_state_dependency/call_route_blocked_when_contract_closed
    """
    ctx = setup_routable()
    contract_id = ctx["contract"]["id"]
    # A PAUSED queue does not block closure; the contract closes cleanly.
    validate_success(
        api_client.transition_queue(ctx["queue"]["id"], {"to_status": "PAUSED"}, OPS)
    )
    validate_success(
        api_client.transition_queue(ctx["queue"]["id"], {"to_status": "CLOSED"}, OPS)
    )
    validate_success(
        api_client.transition_contract(contract_id, {"to_status": "CLOSED"}, OPS)
    )
    call = register_call(contract_id, enqueued_at="2026-09-05T09:00:00Z")
    resp = api_client.transition_call(call["id"], {"to_status": "ASSIGNED"}, SUP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_retrain_completion_revalidates_invalidated_certification():
    """PRD §3.2: "when the course has a `knowledge_article_id` set, completion
    is the retraining path: every certification of that same agent for that
    same program whose `invalidated_by_article_id` equals the linked article
    is re-validated — its `invalidated_at` and `invalidated_by_article_id` are
    both reset to null."
    PRD §3.6: "The way back is the retraining path of §3.2 — completing a
    course linked to the published article re-validates exactly the
    certifications that article invalidated."

    Design: Corner/endpoints/retrain_completion_revalidates_invalidated_certification
    """
    ctx = setup_routable()
    contract_id = ctx["contract"]["id"]
    agent_id = ctx["agent"]["id"]

    article = create_article(effective_at="2026-09-10T00:00:00Z")
    set_clock("2026-09-10T00:00:00Z")
    publish_article(article["id"])

    certs = list_certifications({"agent_id": agent_id})
    assert any(c["invalidated_at"] is not None for c in certs)

    linked = create_course(knowledge_article_id=article["id"])
    unlinked = create_course()

    certify_agent(agent_id, unlinked["id"], valid_until="2027-06-01T00:00:00Z")
    certs = list_certifications({"agent_id": agent_id})
    still_invalid = [
        c for c in certs if c.get("invalidated_by_article_id") == article["id"]
    ]
    assert len(still_invalid) == 1, "unlinked course leaves the invalidation standing"

    certify_agent(agent_id, linked["id"], valid_until="2027-06-01T00:00:00Z")
    certs = list_certifications({"agent_id": agent_id})
    revalidated = [
        c for c in certs if c["training_course_id"] == ctx["course"]["id"]
    ]
    assert len(revalidated) == 1
    assert revalidated[0]["invalidated_at"] is None
    assert revalidated[0]["invalidated_by_article_id"] is None

    call = register_call(contract_id, enqueued_at="2026-09-10T08:00:00Z")
    routed = route_call(call["id"])
    assert routed["assigned_via"] == "PRIMARY"
    assert routed["agent_id"] == agent_id


def test_retrain_unlinked_course_leaves_invalidation_standing():
    """PRD §3.2: "when the course has a `knowledge_article_id` set, completion
    is the retraining path: every certification of that same agent for that
    same program whose `invalidated_by_article_id` equals the linked article
    is re-validated — its `invalidated_at` and `invalidated_by_article_id` are
    both reset to null."

    Design: Corner/endpoints/retrain_completion_revalidates_invalidated_certification
    """
    ctx = setup_routable()
    agent_id = ctx["agent"]["id"]
    article = create_article(effective_at="2026-09-10T00:00:00Z")
    set_clock("2026-09-10T00:00:00Z")
    publish_article(article["id"])

    unlinked = create_course()
    certify_agent(agent_id, unlinked["id"], valid_until="2027-06-01T00:00:00Z")
    certs = list_certifications({"agent_id": agent_id})
    invalid = [c for c in certs if c.get("invalidated_by_article_id") == article["id"]]
    assert len(invalid) == 1
    assert invalid[0]["invalidated_at"] is not None


def test_cascade_side_effect_chain_full_path():
    """PRD §3.6: "Agents left holding no remaining standing certification for
    that program are not deactivated, but they become unroutable for it".
    PRD §3.6: "The way back is the retraining path of §3.2 — completing a
    course linked to the published article re-validates exactly the
    certifications that article invalidated."
    PRD §3.3: "If no eligible queue exists even after the fallback, the route
    attempt fails with `ERR_NO_ELIGIBLE_QUEUE` (HTTP 409)."

    Design: Corner/cross_cutting_layers/cascade_side_effect_chain_full_path
    """
    ctx = setup_routable()
    contract_id = ctx["contract"]["id"]
    agent_id = ctx["agent"]["id"]

    call = register_call(contract_id, enqueued_at="2026-09-10T08:00:00Z")
    article = create_article(effective_at="2026-09-10T00:00:00Z")
    set_clock("2026-09-10T00:00:00Z")
    publish_article(article["id"])

    blocked = api_client.transition_call(call["id"], {"to_status": "ASSIGNED"}, SUP)
    validate_error(blocked, ApiErrorId.ERR_NO_ELIGIBLE_QUEUE)

    linked = create_course(knowledge_article_id=article["id"])
    certify_agent(agent_id, linked["id"], valid_until="2027-06-01T00:00:00Z")

    routed = route_call(call["id"])
    assert routed["assigned_via"] == "PRIMARY"
    assert routed["agent_id"] == agent_id
    assert routed["route_depth"] == 1


def test_threshold_trigger_auto_coach_dedup_window():
    """PRD §3.5: "When a final review's `total_score` is below the auto-coach
    threshold of 70, and the agent named by the reviewed call's
    `handled_by_agent_id` has no CoachingPlan in `OPEN` or `ESCALATED`, and no
    `AUTO_QUALITY` CoachingPlan already exists for that agent with a
    `created_at` within the trailing seven days up to now, the system creates
    a new CoachingPlan for that agent with `trigger` of `AUTO_QUALITY`, a
    `due_date` fourteen days after now, and `status` `OPEN`."

    Design: Corner/cross_cutting_layers/threshold_trigger_auto_coach_dedup_window
    """
    ctx = setup_routable()
    agent_id = ctx["agent"]["id"]
    calls = []
    for i in range(3):
        call = register_call(
            ctx["contract"]["id"],
            enqueued_at=f"2026-09-05T09:0{i}:00Z",
        )
        call = route_call(call["id"])
        call = answer_call(call, agent_id)
        call = complete_call(call, agent_id)
        calls.append(call)

    r1 = create_review(calls[0]["id"], accuracy_score=60, compliance_score=60)
    r2 = create_review(calls[1]["id"], accuracy_score=61, compliance_score=61)
    r3 = create_review(calls[2]["id"], accuracy_score=62, compliance_score=62)

    set_clock("2026-09-05T12:00:00Z")
    transition_review(r1["id"], "ACCEPTED", TEST_USERS["quality_analyst_headers"])
    plans = list_coaching_plans({"agent_id": agent_id, "trigger": "AUTO_QUALITY"})
    assert len(plans) == 1

    set_clock("2026-09-11T12:00:00Z")
    transition_review(r2["id"], "ACCEPTED", TEST_USERS["quality_analyst_headers"])
    plans = list_coaching_plans({"agent_id": agent_id, "trigger": "AUTO_QUALITY"})
    assert len(plans) == 1, "first plan still OPEN 6 days later: no new plan"

    plan_id = plans[0]["id"]
    validate_success(
        api_client.transition_coaching_plan(plan_id, {"to_status": "COMPLETED"}, SUP)
    )
    set_clock("2026-09-13T12:00:00Z")
    transition_review(r3["id"], "ACCEPTED", TEST_USERS["quality_analyst_headers"])
    plans = list_coaching_plans({"agent_id": agent_id, "trigger": "AUTO_QUALITY"})
    assert len(plans) == 2, (
        "8 days after the first plan's creation the dedup window has lapsed"
    )


def test_remaining_error_stubs():
    """PRD §3.2: "An `OpsManager` may deactivate an `ACTIVE` agent only when
    the agent is not the `agent_id` of any call in `ASSIGNED` or `ANSWERED`;
    attempting otherwise is rejected with `ERR_AGENT_HAS_LIVE_CALLS`
    (HTTP 409)."
    PRD §3.3: "any call whose `queue_id` is this queue and whose status is
    `WAITING`, `ASSIGNED`, or `ANSWERED` blocks closure with
    `ERR_QUEUE_NOT_EMPTY` (HTTP 409)."
    PRD §2.5: "If the requested target is not reachable from the current state
    — including re-firing a transition that has already happened, or any
    request against a resource already in a terminal state — the request is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/errors/remaining_error_stubs
    """
    ctx = setup_routable()
    agent_id = ctx["agent"]["id"]
    call = register_call(ctx["contract"]["id"], enqueued_at="2026-09-05T09:00:00Z")
    call = route_call(call["id"])
    assert call["status"] == "ASSIGNED"

    resp1 = api_client.transition_agent(agent_id, {"to_status": "INACTIVE"}, OPS)
    validate_error(resp1, ApiErrorId.ERR_AGENT_HAS_LIVE_CALLS)

    resp2 = api_client.transition_queue(
        ctx["queue"]["id"], {"to_status": "CLOSED"}, OPS
    )
    validate_error(resp2, ApiErrorId.ERR_QUEUE_NOT_EMPTY)

    resp3 = api_client.transition_call(call["id"], {"to_status": "ASSIGNED"}, SUP)
    validate_error(resp3, ApiErrorId.ERR_INVALID_STATE)
