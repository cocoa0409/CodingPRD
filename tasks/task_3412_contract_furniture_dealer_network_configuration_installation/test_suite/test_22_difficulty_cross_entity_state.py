"""Difficulty rule: cross_entity_state_dependency — order submit reads the
configuration's state, phase reserve reads the parent order's state, and
punch filing reads the phase's install dimension (PRD §3.5, §3.6, §3.8)."""

from test_helpers import (
    ApiErrorId,
    acknowledge_order,
    create_configuration,
    create_order,
    create_phase,
    file_punch,
    get_order,
    lock_configuration,
    make_dealer_headers,
    make_end_user_headers,
    make_punch_ticket_payload,
    make_reserve_slot_payload,
    make_submit_payload,
    reserve_slot,
    setup_dealer_world,
    setup_phase_in_progress,
    setup_scheduled_phase,
    setup_submitted_order,
    submit_order,
    validate_error,
    validate_paginated,
)


def test_submit_rejected_while_spec_draft(api):
    """PRD §3.5: "the referenced configuration must be `LOCKED` (else
    `ERR_SPEC_NOT_LOCKED`)" — a DRAFT (never locked) spec rejects the
    order's DRAFT → SUBMITTED transition.

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_configuration_locked
    """
    ctx = setup_dealer_world(api)
    spec = create_configuration(api, ctx["dealer"]["id"], name="Chairs")
    assert spec["status"] == "DRAFT"
    order = create_order(
        api, ctx["agreement"]["id"], spec["id"], ctx["dealer"]["id"]
    )

    resp = api.submit_project_order(
        order["id"], make_submit_payload(order["version"]),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SPEC_NOT_LOCKED)
    assert get_order(
        api, order["id"], make_dealer_headers(ctx["dealer"]["id"])
    )["status"] == "DRAFT"


def test_submit_succeeds_once_spec_locked(api):
    """PRD §3.5: "the referenced configuration must be `LOCKED` (else
    `ERR_SPEC_NOT_LOCKED`)" — locking the same spec afterwards lets the
    identical submit succeed; the failed attempt never bumped the order's
    version, so the same `expected_order_version` still matches.

    Design: Difficulty/cross_entity_state_dependency/order_submit_requires_configuration_locked
    """
    ctx = setup_dealer_world(api)
    spec = create_configuration(api, ctx["dealer"]["id"], name="Chairs")
    order = create_order(
        api, ctx["agreement"]["id"], spec["id"], ctx["dealer"]["id"]
    )
    first = api.submit_project_order(
        order["id"], make_submit_payload(order["version"]),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(first, ApiErrorId.ERR_SPEC_NOT_LOCKED)

    lock_configuration(api, spec, ctx["dealer"]["id"])
    submitted = submit_order(api, order, ctx["dealer"]["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["version"] == order["version"] + 1


def test_reserve_rejected_while_order_submitted(api):
    """PRD §3.6: "the phase's order must be `ACKNOWLEDGED` (else
    `ERR_ORDER_NOT_ACKNOWLEDGED`)" — a phase of a merely SUBMITTED order
    (phase creation is allowed while the order is "in `DRAFT`, `SUBMITTED`,
    or `ACKNOWLEDGED`") cannot reserve a manufacturing slot.

    Design: Difficulty/cross_entity_state_dependency/phase_reserve_requires_order_acknowledged
    """
    ctx = setup_submitted_order(api)
    assert ctx["order"]["status"] == "SUBMITTED"
    phase = create_phase(api, ctx["order"]["id"], ctx["dealer"]["id"])

    resp = api.reserve_slot(
        phase["id"], make_reserve_slot_payload(),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ACKNOWLEDGED)

    phases, _meta = validate_paginated(
        api.list_phases(
            ctx["order"]["id"], make_dealer_headers(ctx["dealer"]["id"])
        )
    )
    assert phases[0]["logistics_status"] == "PLANNED"


def test_reserve_succeeds_once_order_acknowledged(api):
    """PRD §3.6: "the phase's order must be `ACKNOWLEDGED`" — after
    acknowledgment the same reserve moves the phase `PLANNED → SCHEDULED`.

    Design: Difficulty/cross_entity_state_dependency/phase_reserve_requires_order_acknowledged
    """
    ctx = setup_submitted_order(api)
    phase = create_phase(api, ctx["order"]["id"], ctx["dealer"]["id"])
    acknowledge_order(api, ctx["order"]["id"])

    scheduled = reserve_slot(api, phase["id"], ctx["dealer"]["id"])
    assert scheduled["logistics_status"] == "SCHEDULED"


def test_punch_rejected_before_install_starts(api):
    """PRD §3.8: "Filing requires the phase's `install_status` to be
    `IN_PROGRESS` — a ticket against a phase in any other state is rejected
    with `ERR_INVALID_STATE`." The phase is SCHEDULED (manufacturing
    reserved) but NOT_STARTED on the install dimension.

    Design: Difficulty/cross_entity_state_dependency/punch_create_requires_install_in_progress
    """
    ctx = setup_scheduled_phase(api)
    assert ctx["phase"]["logistics_status"] == "SCHEDULED"
    assert ctx["phase"]["install_status"] == "NOT_STARTED"

    resp = api.create_punch_ticket(
        make_punch_ticket_payload(
            ctx["phase"]["id"], severity="MINOR",
            description="Scuff on base trim",
        ),
        make_end_user_headers(ctx["end_user"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_punch_accepted_once_install_in_progress(api):
    """PRD §3.8: "Filing requires the phase's `install_status` to be
    `IN_PROGRESS`" — after start-install drives the install dimension to
    IN_PROGRESS, the same filing succeeds and "A new ticket is `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/punch_create_requires_install_in_progress
    """
    ctx = setup_phase_in_progress(api)
    ticket = file_punch(
        api, ctx["phase"]["id"],
        make_end_user_headers(ctx["end_user"]["id"]),
        severity="MINOR", description="Scuff on base trim",
    )
    assert ticket["status"] == "OPEN"
    assert ticket["installation_phase_id"] == ctx["phase"]["id"]
