"""State-machine lifecycle tests: preconditions, terminal lockdown,
pause/resume cycles, time-driven transitions, and revision loops."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_incident_payload,
    create_invoice_payload,
    create_service_level_payload,
    create_surge_window_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    activate_contract,
    answer_call,
    complete_call,
    create_contract,
    create_draft_service_level,
    get_call,
    get_contract,
    get_invoice,
    get_invoice_line,
    get_surge_window,
    list_cure_periods,
    list_invoice_lines,
    make_agent_headers,
    prepare_invoice,
    register_call,
    route_call,
    set_clock,
    setup_breach_invoice,
    setup_completed_call,
    setup_routable,
    staff_to_target,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["ops_manager_headers"]
SUP = TEST_USERS["supervisor_headers"]
SEC = TEST_USERS["security_officer_headers"]
BILL = TEST_USERS["billing_analyst_headers"]


def test_contract_activate_without_effective_sl_fails():
    """PRD §3.1: "From `DRAFT`, an `OpsManager` may activate the contract by
    requesting `to_status` of `ACTIVE`, which requires that at least one of
    its service levels has already reached `EFFECTIVE`, and increments the
    contract's `version` by 1."
    PRD §2.5: "If the requested target is not reachable from the current state
    — including re-firing a transition that has already happened, or any
    request against a resource already in a terminal state — the request is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/contract_activate_without_effective_sl_fails
    """
    contract = create_contract()
    create_draft_service_level(contract["id"], metric="ASA", target=30)
    resp = api_client.transition_contract(contract["id"], {"to_status": "ACTIVE"}, OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_contract(contract["id"])
    assert after["status"] == "DRAFT"
    assert after["version"] == 1


def test_invalid_from_transition_on_terminal_call():
    """PRD §3.4: "`COMPLETED` and `ABANDONED` are the terminal states."
    PRD §2.5: "If the requested target is not reachable from the current state
    — including re-firing a transition that has already happened, or any
    request against a resource already in a terminal state — the request is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/invalid_from_transition_on_terminal_call
    """
    ctx = setup_completed_call()
    call = ctx["call"]
    version_before = call["version"]
    resp = api_client.transition_call(call["id"], {"to_status": "ABANDONED"}, SUP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_call(call["id"])
    assert after["status"] == "COMPLETED"
    assert after["version"] == version_before


def test_queue_pause_resume_cycle_restores_routing():
    """PRD §3.3: "Requesting `to_status` of `PAUSED` from `OPEN` removes the
    queue from routing eligibility unconditionally; requesting `OPEN` from
    `PAUSED` restores it."
    PRD §3.3: "If no eligible queue exists even after the fallback, the route
    attempt fails with `ERR_NO_ELIGIBLE_QUEUE` (HTTP 409)."

    Design: Corner/state_machines/queue_pause_resume_cycle_restores_routing
    """
    ctx = setup_routable()
    queue = ctx["queue"]
    call = register_call(ctx["contract"]["id"])

    validate_success(
        api_client.transition_queue(queue["id"], {"to_status": "PAUSED"}, OPS)
    )
    resp = api_client.transition_call(call["id"], {"to_status": "ASSIGNED"}, SUP)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_QUEUE)

    validate_success(
        api_client.transition_queue(queue["id"], {"to_status": "OPEN"}, OPS)
    )
    routed = validate_success(
        api_client.transition_call(call["id"], {"to_status": "ASSIGNED"}, SUP)
    )
    assert routed["assigned_via"] == "PRIMARY"
    assert routed["queue_id"] == queue["id"]
    assert routed["agent_id"] == ctx["agent"]["id"]
    assert routed["route_depth"] == 1


def test_surge_auto_activation_and_cancel_after_activation():
    """PRD §2.4: "Every clock-set fires the system's time-driven
    auto-transitions: surge windows whose start has been reached move from
    `DECLARED` to `ACTIVE`".
    PRD §3.7: "an `OpsManager` may request `to_status` of `CANCELLED` from
    `DECLARED` while the logical clock is still strictly before `starts_on`;
    once the clock has reached the start, cancellation is no longer a defined
    transition and fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/surge_auto_activation_and_cancel_after_activation
    """
    ctx = setup_routable()
    window = validate_success(
        api_client.create_surge_window(
            create_surge_window_payload(
                ctx["contract"]["id"],
                starts_on="2026-09-15T00:00:00Z",
                ends_on="2026-09-30T00:00:00Z",
                expected_volume_factor=1.5,
            ),
            OPS,
        ),
        201,
    )
    set_clock("2026-09-15T00:00:00Z")
    after = get_surge_window(window["id"])
    assert after["status"] == "ACTIVE"

    resp = api_client.transition_surge_window(
        window["id"], {"to_status": "CANCELLED"}, OPS
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_surge_window(window["id"])["status"] == "ACTIVE"


def test_incident_reopen_loop_preserves_reported_at():
    """PRD §3.8: "from `RESOLVED`, an incident may be reopened to `OPEN` — and
    when it is, the reporting-sla timestamps are deliberately not reset;
    `reported_at` is immutable for the life of the incident."

    Design: Corner/state_machines/incident_reopen_loop_preserves_reported_at
    """
    ctx = setup_routable()
    set_clock("2026-09-05T12:00:00Z")
    incident = validate_success(
        api_client.create_incident(
            create_incident_payload(
                ctx["contract"]["id"],
                occurred_at="2026-09-04T12:00:00Z",
                description="agent exposed PII on a call",
            ),
            SEC,
        ),
        201,
    )
    reported_at = incident["reported_at"]
    validate_success(
        api_client.transition_incident(incident["id"], {"to_status": "CONTAINED"}, SEC)
    )
    resolved = validate_success(
        api_client.transition_incident(incident["id"], {"to_status": "RESOLVED"}, SEC)
    )
    version_at_resolved = resolved["version"]
    reopened = validate_success(
        api_client.transition_incident(incident["id"], {"to_status": "OPEN"}, SEC)
    )
    assert reopened["status"] == "OPEN"
    assert reopened["reported_at"] == reported_at == "2026-09-05T12:00:00.000Z"
    assert reopened["version"] > version_at_resolved


def test_cure_period_auto_forfeit_at_deadline():
    """PRD §3.11: "A cure period that is still `PENDING` when the logical
    clock passes its `deadline` is automatically forfeited: it moves to
    `FORFEIT` on the next clock-set, the withholding stands, and the
    contract's `cure_periods_used` is incremented by 1."
    PRD §3.11: "Payment is only possible inside the cure window — after the
    deadline, or on a cure period no longer `PENDING`, the attempt is rejected
    with `ERR_CURE_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/state_machines/cure_period_auto_forfeit_at_deadline
    """
    # One call answered in 40s against an ASA target of 30: miss 10s,
    # ratio 1/3 >= 0.15 -> tier 0.40 -> raw withheld 0.40 * 54000 = 21600.
    ctx = setup_breach_invoice(answer_seconds=40)
    line = ctx["line"]
    assert line["compliant"] is False
    assert line["withheld_cents"] == 21600
    assert len(ctx["cure_periods"]) == 1
    cure = ctx["cure_periods"][0]
    assert cure["status"] == "PENDING"

    # The cure was opened at the prepare instant (2026-09-05T09:00:40Z);
    # deadline = opened_at + 72h -> advance just past it.
    set_clock("2026-09-08T09:00:41Z")
    cures = list_cure_periods(line["id"])
    assert cures[0]["status"] == "FORFEIT"

    resp = api_client.pay_cure_remedy(cure["id"], BILL)
    validate_error(resp, ApiErrorId.ERR_CURE_WINDOW_CLOSED)

    contract = get_contract(ctx["contract"]["id"])
    assert contract["cure_periods_used"] == 1
    assert contract["withheld_cents_cum"] == 21600


def test_invoice_revision_loop_restores_draft_and_recomputes():
    """PRD §3.12: "Rejection is the revision loop: an `OpsManager` may move a
    `SUBMITTED` invoice to `REJECTED`, and a `BillingAnalyst` may return a
    `REJECTED` invoice to `DRAFT`. The lines are not discarded on rejection or
    revision — the next recompute refreshes them against current measurements
    and caps, using the official variant of §3.9."
    PRD §3.9: "An empty set — a month with no answered calls — yields a
    `measured_value` of 0, which is compliant for `ASA`."

    Design: Difficulty/non_linear_state_machine/invoice_revision_loop_restores_draft_and_recomputes
    """
    ctx = setup_routable()
    # Staff the program to its baseline target so the staffing-shortfall
    # override of PRD §3.9 does not force the line non-compliant.
    staff_to_target(ctx["course"]["id"])
    invoice = validate_success(
        api_client.create_invoice(
            create_invoice_payload(ctx["contract"]["id"]), BILL
        ),
        201,
    )
    invoice = prepare_invoice(invoice["id"])
    validate_success(
        api_client.transition_invoice(invoice["id"], {"to_status": "SUBMITTED"}, BILL)
    )
    validate_success(
        api_client.transition_invoice(invoice["id"], {"to_status": "REJECTED"}, OPS)
    )
    back = validate_success(
        api_client.transition_invoice(invoice["id"], {"to_status": "DRAFT"}, BILL)
    )
    assert back["status"] == "DRAFT"

    lines = list_invoice_lines(invoice["id"])
    assert len(lines) == 1, "lines are retained through the revision loop"

    recomputed = validate_success(api_client.recompute_invoice(invoice["id"], BILL))
    line = list_invoice_lines(invoice["id"])[0]
    assert line["measured_value"] == 0
    assert line["compliant"] is True
    assert line["withheld_cents"] == 0

    resubmitted = validate_success(
        api_client.transition_invoice(invoice["id"], {"to_status": "SUBMITTED"}, BILL)
    )
    assert resubmitted["status"] == "SUBMITTED"


def test_invoice_revision_loop_rejects_prepare_while_submitted():
    """PRD §3.9: "Preparation — the capability that turns a shell into a
    measured bill — is available only while the invoice is `DRAFT`."
    PRD §2.5: "If the requested target is not reachable from the current state
    — including re-firing a transition that has already happened, or any
    request against a resource already in a terminal state — the request is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/invoice_revision_loop_restores_draft_and_recomputes
    """
    ctx = setup_routable()
    invoice = validate_success(
        api_client.create_invoice(
            create_invoice_payload(ctx["contract"]["id"]), BILL
        ),
        201,
    )
    prepare_invoice(invoice["id"])
    validate_success(
        api_client.transition_invoice(invoice["id"], {"to_status": "SUBMITTED"}, BILL)
    )
    resp = api_client.prepare_invoice(invoice["id"], BILL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_invoice(invoice["id"])["status"] == "SUBMITTED"
