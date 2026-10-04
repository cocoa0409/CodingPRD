"""Diagnostic session gates: ticket state/type/machine, the one-open-session
lock, and close ownership."""

from test_helpers import (
    ApiErrorId,
    activate_plan,
    add_machine,
    close_session,
    create_plan,
    grant_ticket,
    open_session,
    provision_modem_success,
    read_session,
    read_ticket,
    request_dealer_ticket,
    setup_connected_machine,
    setup_delivery_awaiting_consent,
    setup_open_session,
    validate_error,
    validate_paginated,
    validate_success,
)


def _add_connected_machine(ctx, api, serial, imei):
    """Second machine on the context org/dealer carried to posture CONNECTED
    (PROVISIONED modem + ACTIVE plan). Sessions need posture, not activation."""
    machine = add_machine(ctx, api, serial_number=serial, modem_imei=imei)
    provision_modem_success(ctx, api, machine["id"])
    plan = create_plan(ctx, api, machine["id"])
    activate_plan(ctx, api, plan["id"])
    return machine


def test_session_close_twice_rejected(api):
    """PRD section 3.5: "An explicit close records the reported `fault_found`
    flag, stamps `closed_at`, and sets `closed_reason` `COMPLETED`. ... `CLOSED`
    is terminal." A second close is a transition that does not exist and fails
    with `ERR_INVALID_STATE_TRANSITION` (PRD section 2.10 step 6).

    Design: Corner/state_machines/session_close_twice_rejected
    """
    ctx = setup_open_session(api)
    session_id = ctx["session"]["id"]
    close_session(api, session_id, ctx["dealer_headers"], fault_found=False)

    response = api.close_diagnostic_session(
        session_id, {"fault_found": True}, headers=ctx["dealer_headers"]
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    session = read_session(ctx, api, session_id)
    assert session["status"] == "CLOSED"
    assert session["closed_reason"] == "COMPLETED"
    assert session["fault_found"] is False


def test_ticket_type_mismatch_rejected_for_sessions(api):
    """PRD section 3.5: "The ticket must be a `REMOTE_DIAGNOSTIC` ticket
    (`ERR_TICKET_TYPE_MISMATCH`)" — a granted `SOFTWARE_UPDATE` ticket cannot
    open a diagnostic session and is not consumed by the attempt.

    Design: Corner/validations/ticket_type_mismatch_rejected_for_sessions
    """
    ctx = setup_delivery_awaiting_consent(api)
    ticket_id = ctx["ticket_id"]
    grant_ticket(ctx, api, ticket_id)

    response = api.create_diagnostic_session(
        {"machine_id": ctx["machine"]["id"], "consent_ticket_id": ticket_id},
        headers=ctx["dealer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_TICKET_TYPE_MISMATCH)

    ticket = read_ticket(ctx, api, ticket_id)
    assert ticket["status"] == "GRANTED"
    rows, _meta = validate_paginated(
        api.list_diagnostic_sessions(
            headers=ctx["grower_headers"],
            params={"machine_id": ctx["machine"]["id"]},
        )
    )
    assert len(rows) == 0


def test_ticket_machine_mismatch_alone_rejected(api):
    """PRD section 3.5: "its machine must equal the requested `machine_id`
    (`ERR_TICKET_MACHINE_MISMATCH`)" — a granted, unexpired diagnostic ticket
    for machine A cannot open a session on machine B.

    Design: Corner/validations/ticket_machine_mismatch_alone_rejected
    """
    ctx = setup_connected_machine(api)
    machine_b = _add_connected_machine(ctx, api, "SN-0002", "IMEI-0002")
    ticket = request_dealer_ticket(ctx, api, ctx["machine"]["id"])
    grant_ticket(ctx, api, ticket["id"])

    response = api.create_diagnostic_session(
        {"machine_id": machine_b["id"], "consent_ticket_id": ticket["id"]},
        headers=ctx["dealer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_TICKET_MACHINE_MISMATCH)
    ticket = read_ticket(ctx, api, ticket["id"])
    assert ticket["status"] == "GRANTED"


def test_session_create_consumed_ticket_beats_machine_mismatch(api):
    """PRD section 2.10 step 6: "For a consent ticket that is already
    `CONSUMED`, the consumed-state rejection wins over any referential mismatch
    the same request might also carry." — a ticket already consumed on machine
    A, presented for machine B, fails with `ERR_CONSENT_ALREADY_CONSUMED`, not
    `ERR_TICKET_MACHINE_MISMATCH`.

    Design: Difficulty/priority_pair_validation_conflict/session_create_consumed_ticket_beats_machine_mismatch
    """
    ctx = setup_connected_machine(api)
    machine_b = _add_connected_machine(ctx, api, "SN-0002", "IMEI-0002")
    ticket = request_dealer_ticket(ctx, api, ctx["machine"]["id"])
    grant_ticket(ctx, api, ticket["id"])
    open_session(ctx, api, ctx["machine"]["id"], ticket["id"])

    response = api.create_diagnostic_session(
        {"machine_id": machine_b["id"], "consent_ticket_id": ticket["id"]},
        headers=ctx["dealer_headers"],
    )
    error = validate_error(response, ApiErrorId.ERR_CONSENT_ALREADY_CONSUMED)
    assert error["error_id"] != "ERR_TICKET_MACHINE_MISMATCH"


def test_consumed_ticket_rejection_mutates_nothing(api):
    """PRD section 2.7: "Consent is consumed exactly once. A `GRANTED` ticket
    becomes `CONSUMED` the moment a diagnostic session opens with it" — after
    the winning `ERR_CONSENT_ALREADY_CONSUMED` rejection (PRD section 2.10 step
    6), the ticket remains `CONSUMED` and no second session exists.

    Design: Difficulty/priority_pair_validation_conflict/session_create_consumed_ticket_beats_machine_mismatch
    """
    ctx = setup_connected_machine(api)
    machine_b = _add_connected_machine(ctx, api, "SN-0002", "IMEI-0002")
    ticket = request_dealer_ticket(ctx, api, ctx["machine"]["id"])
    grant_ticket(ctx, api, ticket["id"])
    session = open_session(ctx, api, ctx["machine"]["id"], ticket["id"])

    response = api.create_diagnostic_session(
        {"machine_id": machine_b["id"], "consent_ticket_id": ticket["id"]},
        headers=ctx["dealer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CONSENT_ALREADY_CONSUMED)

    ticket = read_ticket(ctx, api, ticket["id"])
    assert ticket["status"] == "CONSUMED"
    assert ticket["bound_session_id"] == session["id"]
    rows, _meta = validate_paginated(
        api.list_diagnostic_sessions(
            headers=ctx["grower_headers"], params={"machine_id": machine_b["id"]}
        )
    )
    assert len(rows) == 0


def test_second_open_session_on_same_machine_rejected(api):
    """PRD section 3.5: "at most one session per machine may be `OPEN` at a
    time — a second open attempt is `ERR_MACHINE_SESSION_ACTIVE`, though a new
    session may open immediately after the previous one closes."

    Design: Difficulty/resource_temporal_overlap/diagnostic_session_exclusive_machine_lock_half_open
    """
    ctx = setup_open_session(api)
    ticket2 = request_dealer_ticket(ctx, api, ctx["machine"]["id"])
    grant_ticket(ctx, api, ticket2["id"])

    response = api.create_diagnostic_session(
        {"machine_id": ctx["machine"]["id"],
         "consent_ticket_id": ticket2["id"]},
        headers=ctx["dealer_headers"],
    )
    validate_error(response, ApiErrorId.ERR_MACHINE_SESSION_ACTIVE)

    ticket2 = read_ticket(ctx, api, ticket2["id"])
    assert ticket2["status"] == "GRANTED"


def test_session_opens_immediately_after_previous_closes(api):
    """PRD section 3.5: "at most one session per machine may be `OPEN` at a
    time — a second open attempt is `ERR_MACHINE_SESSION_ACTIVE`, though a new
    session may open immediately after the previous one closes." The follow-up
    dealer session tiers as `EXTENDED` ("dealer sessions get
    `diagnostic_detail_level` `EXTENDED`, independent sessions get `BASIC`")
    and consumes its ticket.

    Design: Difficulty/resource_temporal_overlap/diagnostic_session_exclusive_machine_lock_half_open
    """
    ctx = setup_open_session(api)
    ticket2 = request_dealer_ticket(ctx, api, ctx["machine"]["id"])
    grant_ticket(ctx, api, ticket2["id"])

    close_session(api, ctx["session"]["id"], ctx["dealer_headers"],
                  fault_found=True)
    session2 = open_session(ctx, api, ctx["machine"]["id"], ticket2["id"])
    assert session2["status"] == "OPEN"
    assert session2["technician_kind"] == "DEALER"
    assert session2["diagnostic_detail_level"] == "EXTENDED"

    ticket2 = read_ticket(ctx, api, ticket2["id"])
    assert ticket2["status"] == "CONSUMED"
    assert ticket2["bound_session_id"] == session2["id"]
