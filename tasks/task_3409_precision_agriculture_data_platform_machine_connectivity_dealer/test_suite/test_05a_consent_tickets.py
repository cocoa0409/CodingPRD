"""Consent ticket creation, decision rules, right-to-repair gating, and TTL
expiry."""

from test_helpers import (
    ApiErrorId,
    INDEPENDENT_USER_ID,
    add_machine,
    create_consent_ticket_payload,
    grant_ticket,
    make_independent_technician_headers,
    read_ticket,
    request_dealer_ticket,
    same_instant,
    set_clock,
    setup_connected_machine,
    setup_org_dealer,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_consent_ticket_create_stamps_72h_expiry(api):
    """PRD section 2.7: "Every ticket is born `REQUESTED` with `expires_at`
    set exactly 72 hours after creation, and a clock advance that reaches
    `expires_at` flips a still-`REQUESTED` or `GRANTED` ticket to `EXPIRED`."

    Design: Corner/entities/consent_ticket_create_stamps_72h_expiry
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    ticket = request_dealer_ticket(ctx, api, machine["id"])
    assert ticket["status"] == "REQUESTED"
    assert ticket["granted_at"] is None
    assert same_instant(ticket["expires_at"], "2026-09-04T00:00:00Z")


def test_ticket_grant_twice_and_deny_after_grant_rejected(api):
    """PRD section 3.5: "Granting — a `GrowerManager` action requiring the
    organization to be `ACTIVE` (`ERR_ORG_SUSPENDED`) — moves `REQUESTED` →
    `GRANTED`, stamps `granted_at`" and "Denying moves `REQUESTED` → `DENIED`"
    — neither transition exists from `GRANTED`, so both a second grant and a
    late deny fail with `ERR_INVALID_STATE_TRANSITION` (PRD section 2.10 step
    6) and the original `granted_at` stands.

    Design: Corner/state_machines/ticket_grant_twice_and_deny_after_grant_rejected
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    ticket = request_dealer_ticket(ctx, api, machine["id"])
    granted = grant_ticket(ctx, api, ticket["id"])
    first_granted_at = granted["granted_at"]

    response = api.grant_consent_ticket(ticket["id"], headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    response = api.deny_consent_ticket(ticket["id"], headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    ticket = read_ticket(ctx, api, ticket["id"])
    assert ticket["status"] == "GRANTED"
    assert same_instant(ticket["granted_at"], first_granted_at)


def test_rtr_gate_blocks_independent_but_not_dealer(api):
    """PRD section 3.5: "An `IndependentTechnician` may request only where the
    target organization has `right_to_repair_enabled`; where it does not, the
    request is refused with `ERR_RTR_NOT_ENABLED` (HTTP 403)." Dealer requests
    carry no such gate.

    Design: Corner/validations/rtr_gate_blocks_independent_but_not_dealer
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)

    payload = create_consent_ticket_payload(
        ctx["org"]["id"], machine["id"], INDEPENDENT_USER_ID,
        ticket_type="REMOTE_DIAGNOSTIC",
    )
    response = api.create_consent_ticket(
        payload, headers=make_independent_technician_headers(INDEPENDENT_USER_ID)
    )
    validate_error(response, ApiErrorId.ERR_RTR_NOT_ENABLED)

    dealer_payload = create_consent_ticket_payload(
        ctx["org"]["id"], machine["id"], ctx["dealer"]["id"],
        ticket_type="REMOTE_DIAGNOSTIC",
    )
    response = api.create_consent_ticket(
        dealer_payload, headers=ctx["dealer_headers"]
    )
    ticket = validate_success(response, 201)
    assert ticket["status"] == "REQUESTED"


def test_consent_ticket_granted_until_exactly_expiry(api):
    """PRD section 2.4: "All of these comparisons use at-or-after semantics:
    reaching the boundary exactly is enough to expire." A ticket created and
    granted at 2026-09-01T00:00:00Z expires at 2026-09-04T00:00:00Z
    (`CONSENT_TTL_HOURS` 72): one second before it is still `GRANTED`; at the
    boundary the sweep flips it to `EXPIRED`.

    Design: Difficulty/boundary_precision_check/consent_ticket_expires_exactly_at_ttl
    """
    ctx = setup_connected_machine(api)
    ticket = request_dealer_ticket(ctx, api, ctx["machine"]["id"])
    grant_ticket(ctx, api, ticket["id"])

    set_clock(api, "2026-09-03T23:59:59Z")
    ticket = read_ticket(ctx, api, ticket["id"])
    assert ticket["status"] == "GRANTED"

    set_clock(api, "2026-09-04T00:00:00Z")
    ticket = read_ticket(ctx, api, ticket["id"])
    assert ticket["status"] == "EXPIRED"


def test_expired_consent_ticket_rejected_for_session(api):
    """PRD section 3.5: "The ticket must be `GRANTED`: any other state is a
    state error — ... `ERR_CONSENT_EXPIRED` for a ticket the clock has
    expired." and PRD section 2.4: "Consent tickets still in `REQUESTED` or
    `GRANTED` whose expiry has been reached transition to `EXPIRED`."

    Design: Difficulty/boundary_precision_check/consent_ticket_expires_exactly_at_ttl
    """
    ctx = setup_connected_machine(api)
    ticket = request_dealer_ticket(ctx, api, ctx["machine"]["id"])
    grant_ticket(ctx, api, ticket["id"])

    set_clock(api, "2026-09-04T00:00:00Z")
    response = api.create_diagnostic_session(
        {"machine_id": ctx["machine"]["id"], "consent_ticket_id": ticket["id"]},
        headers=ctx["dealer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CONSENT_EXPIRED)
    ticket = read_ticket(ctx, api, ticket["id"])
    assert ticket["status"] == "EXPIRED"


def test_session_create_with_requested_ticket_rejected(api):
    """PRD section 3.5: "The ticket must be `GRANTED`: any other state is a
    state error — `ERR_INVALID_STATE_TRANSITION` for a ticket still
    `REQUESTED` or otherwise wrong-state".

    Design: Difficulty/cross_entity_state_dependency/session_create_gated_by_ticket_state
    """
    ctx = setup_connected_machine(api)
    ticket = request_dealer_ticket(ctx, api, ctx["machine"]["id"])

    response = api.create_diagnostic_session(
        {"machine_id": ctx["machine"]["id"], "consent_ticket_id": ticket["id"]},
        headers=ctx["dealer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_failed_session_create_consumes_nothing(api):
    """PRD section 2.7: "Consent is consumed exactly once. A `GRANTED` ticket
    becomes `CONSUMED` the moment a diagnostic session opens with it" — a
    session open rejected because the ticket was never granted persists no
    session and leaves the ticket `REQUESTED`.

    Design: Difficulty/cross_entity_state_dependency/session_create_gated_by_ticket_state
    """
    ctx = setup_connected_machine(api)
    ticket = request_dealer_ticket(ctx, api, ctx["machine"]["id"])

    response = api.create_diagnostic_session(
        {"machine_id": ctx["machine"]["id"], "consent_ticket_id": ticket["id"]},
        headers=ctx["dealer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    rows, _meta = validate_paginated(
        api.list_diagnostic_sessions(
            headers=ctx["grower_headers"],
            params={"machine_id": ctx["machine"]["id"]},
        )
    )
    assert len(rows) == 0
    ticket = read_ticket(ctx, api, ticket["id"])
    assert ticket["status"] == "REQUESTED"
