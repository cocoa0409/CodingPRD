"""Support economics: SLA windows, deflection, the agent-second budget and escalations."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_subscriber_headers,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    create_case,
    create_subscriber,
    current_agreement_version,
    get_case,
    get_subscriber,
    get_summary,
    purchase_term,
    quote_term,
    set_clock,
    setup_activated_subscriber,
    setup_active_agreement,
    setup_agreement_with_offered_plan,
)


def test_assigning_a_case_books_the_topics_routing_estimate(api):
    """PRD §3.9: "A `SupportAgent`
    assigns an open case, moving it to `ASSIGNED` and booking the topic's routing estimate into
    `handling_seconds`".

    Design: Difficulty/transitive_cascade/subscriber_churn_shallow_cascade_closing_support_work
    """
    set_clock()
    setup = setup_activated_subscriber()
    case = create_case(setup["subscriber"]["id"], topic_code="PORT_STATUS")

    assigned = api.assign_case(case["id"], TEST_USERS["agent_headers"]).json()["data"]
    assert assigned["case_status"] == "ASSIGNED"
    assert assigned["handling_seconds"] == 120
    assert get_subscriber(setup["subscriber"]["id"])["support_seconds_used"] == 120


def test_self_service_inside_the_cooling_window_is_refused(api):
    """PRD §3.9: "It is admitted only once the case is at least 60 seconds
    old on the logical clock, and an attempt inside that cooling window is rejected with `ERR_SELF_SERVICE_TOO_EARLY`
    (HTTP 409)."

    Design: Corner/validations/self_service_before_the_grace_window_is_rejected
    """
    set_clock()
    setup = setup_activated_subscriber()
    case = create_case(setup["subscriber"]["id"], topic_code="PORT_STATUS")

    resp = api.resolve_self_service(
        case["id"], make_subscriber_headers(setup["subscriber"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_SELF_SERVICE_TOO_EARLY)
    assert get_case(case["id"])["case_status"] == "OPEN"
    assert get_subscriber(setup["subscriber"]["id"])["support_seconds_used"] == 0

    set_clock("2026-10-01T00:01:01Z")
    resolved = api.resolve_self_service(
        case["id"], make_subscriber_headers(setup["subscriber"]["id"])
    ).json()["data"]
    assert resolved["case_status"] == "RESOLVED_SELF_SERVICE"


def test_self_service_books_no_agent_seconds_and_counts_a_deflection(api):
    """PRD §3.9: "the
    resolution leaves `handling_seconds` at 0 and books nothing against the budget, and it increments the
    subscriber's `self_service_deflection_count` by 1."

    Design: Corner/calculations/support_outsourcing_budget_accounting
    """
    set_clock()
    setup = setup_activated_subscriber()
    case = create_case(setup["subscriber"]["id"], topic_code="PORT_STATUS")
    set_clock("2026-10-01T00:01:01Z")
    resolved = api.resolve_self_service(
        case["id"], make_subscriber_headers(setup["subscriber"]["id"])
    ).json()["data"]

    assert resolved["handling_seconds"] == 0
    subscriber = get_subscriber(setup["subscriber"]["id"])
    assert subscriber["self_service_deflection_count"] == 1
    assert subscriber["support_seconds_used"] == 0


def test_support_budget_exhaustion_returns_402(api):
    """PRD §3.9: "Any booking that would push
    the subscriber past their budget — an assignment, an escalation, or an agent resolution — is rejected with
    `ERR_SUPPORT_BUDGET_EXCEEDED` (HTTP 402)".

    Design: Corner/validations/support_budget_exhaustion_returns_402
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]

    # REFUND_REQUEST routing is 300s; two of them already approach the 600s budget.
    first = create_case(subscriber_id, topic_code="REFUND_REQUEST")
    api.assign_case(first["id"], TEST_USERS["agent_headers"])
    second_case = create_case(subscriber_id, topic_code="REFUND_REQUEST")
    api.assign_case(second_case["id"], TEST_USERS["agent_headers"])
    assert get_subscriber(subscriber_id)["support_seconds_used"] == 600

    third = create_case(subscriber_id, topic_code="REFUND_REQUEST")
    resp = api.assign_case(third["id"], TEST_USERS["agent_headers"])
    validate_error(resp, ApiErrorId.ERR_SUPPORT_BUDGET_EXCEEDED)
    assert resp.json()["data"]["error_id"] != "ERR_INVALID_STATE"
    assert get_case(third["id"])["case_status"] == "OPEN"
    assert get_case(third["id"])["handling_seconds"] == 0

    top_up = api.support_top_up(
        subscriber_id, TEST_USERS["agent_headers"], {"granted_seconds": 600}
    ).json()["data"]
    assert top_up["support_seconds_budget"] == 1200
    assert api.assign_case(third["id"], TEST_USERS["agent_headers"]).status_code == 200


def test_a_support_top_up_raises_the_budget(api):
    """PRD §3.9: "a `SupportAgent` raises
    the subscriber's `support_seconds_budget` by a `granted_seconds` amount on request".

    Design: Corner/calculations/support_outsourcing_budget_accounting
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]
    assert get_subscriber(subscriber_id)["support_seconds_budget"] == 600

    api.support_top_up(subscriber_id, TEST_USERS["agent_headers"], {"granted_seconds": 300})
    assert get_subscriber(subscriber_id)["support_seconds_budget"] == 900


def test_manual_escalation_needs_the_sla_window_to_have_elapsed(api):
    """PRD §3.9: "a `SupportAgent` escalates a case manually, which is admitted only when the current logical clock is
    at or after the case's `sla_due_at`".

    Design: Difficulty/resource_temporal_overlap/buffer_and_adjacency_on_the_support_sla_window
    """
    set_clock()
    setup = setup_activated_subscriber()
    case = create_case(setup["subscriber"]["id"], topic_code="PORT_STATUS")
    assert case["sla_due_at"].startswith("2026-10-01T04:00:00")

    set_clock("2026-10-01T03:59:59Z")
    resp = api.escalate_case(case["id"], TEST_USERS["agent_headers"])
    validate_error(resp, ApiErrorId.ERR_SLA_NOT_DUE)

    set_clock("2026-10-01T04:00:00Z")
    escalated = api.escalate_case(case["id"], TEST_USERS["agent_headers"]).json()["data"]
    assert escalated["case_status"] == "ESCALATED"
    assert escalated["escalation_reason"] == "SELF_SERVICE_FAILED"
    assert get_subscriber(setup["subscriber"]["id"])["support_seconds_used"] == 60


def test_escalation_seconds_add_to_the_routing_seconds_already_booked(api):
    """PRD §3.9: "a case that is assigned, then escalated, then resolved
    through an agent carries 120 plus 60 plus the reported agent seconds for a `PORT_STATUS` case".

    Design: Difficulty/resource_temporal_overlap/buffer_and_adjacency_on_the_support_sla_window
    """
    set_clock()
    setup = setup_activated_subscriber()
    case = create_case(setup["subscriber"]["id"], topic_code="PORT_STATUS")
    api.assign_case(case["id"], TEST_USERS["agent_headers"])
    assert get_case(case["id"])["handling_seconds"] == 120

    set_clock("2026-10-01T04:00:00Z")
    api.escalate_case(case["id"], TEST_USERS["agent_headers"])
    assert get_case(case["id"])["handling_seconds"] == 180
    assert get_subscriber(setup["subscriber"]["id"])["support_seconds_used"] == 180


def test_the_cycle_roll_escalates_cases_whose_sla_window_has_passed(api):
    """PRD §3.4: "every support case for the subscriber whose `sla_due_at` is at or before
    `closed_at` is escalated with `escalation_reason` set to `SLA_BREACH`".

    Design: Corner/state_machines/subscriber_grace_to_churned_on_cycle_roll_without_remedy
    """
    set_clock()
    setup = setup_activated_subscriber()
    case = create_case(setup["subscriber"]["id"], topic_code="PORT_STATUS")

    set_clock("2026-11-01T00:00:00Z")
    api.run_cycle(setup["subscriber"]["id"], TEST_USERS["planner_headers"])

    updated = get_case(case["id"])
    assert updated["escalation_reason"] == "SLA_BREACH"
    assert updated["case_status"] in ("ESCALATED", "CLOSED")


def test_case_read_with_unknown_id_returns_case_not_found(api):
    """PRD §2.9: "a missing support case
    `ERR_CASE_NOT_FOUND`".

    Design: Corner/validations/fulfillment_lookup_of_an_unknown_shipment_shape_returns_not_found
    """
    set_clock()
    resp = api.get_case(
        "00000000-0000-4000-8000-000000000000", TEST_USERS["planner_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND)


def test_closed_cases_still_count_toward_the_used_seconds(api):
    """PRD §3.9: "the used total is the
    sum of `handling_seconds` across every one of the subscriber's cases, including cases that are already
    `CLOSED`."

    Design: Corner/calculations/support_outsourcing_budget_accounting
    """
    set_clock()
    setup = setup_activated_subscriber()
    subscriber_id = setup["subscriber"]["id"]
    case = create_case(subscriber_id, topic_code="PORT_STATUS")
    api.assign_case(case["id"], TEST_USERS["agent_headers"])
    api.resolve_agent(case["id"], TEST_USERS["agent_headers"], {"agent_seconds": 30})

    resolved = get_case(case["id"])
    assert resolved["case_status"] == "RESOLVED_AGENT"
    assert resolved["handling_seconds"] == 150
    assert get_subscriber(subscriber_id)["support_seconds_used"] == 150

    set_clock("2026-11-01T00:00:00Z")
    api.run_cycle(subscriber_id, TEST_USERS["planner_headers"])
    assert get_case(case["id"])["case_status"] == "CLOSED"
    assert get_subscriber(subscriber_id)["support_seconds_used"] == 150