"""Endpoint mechanics: conditional transition dispatch, prepare/submit
preconditions, filtered pagination, and immediate read-after-write
consistency."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_invoice_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    BILL,
    OPS,
    SUP,
    abandon_call,
    activate_contract,
    activate_service_level,
    create_draft_service_level,
    create_invoice,
    create_queue,
    get_call,
    list_invoice_lines,
    prepare_invoice,
    register_call,
    route_call,
    set_clock,
    setup_active_contract,
    setup_routable,
)

BILL_H = TEST_USERS["billing_analyst_headers"]
OPS_H = TEST_USERS["ops_manager_headers"]
SUP_H = TEST_USERS["supervisor_headers"]


def test_transition_dispatch_is_conditional_action():
    """PRD §2.8: "The `expected_contract_version` field is required on those
    two transitions when, and only when, the requested `to_status` is
    `EFFECTIVE` (for a service level) or `APPROVED` (for an invoice); requests
    targeting any other `to_status` on those same endpoints do not carry the
    field, and no other endpoint in the system takes a version field at all."
    PRD §2.5: "If the requested target is not reachable from the current state
    — including re-firing a transition that has already happened, or any
    request against a resource already in a terminal state — the request is
    rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.3: "Closure, requested with `to_status` of `CLOSED` from either
    `OPEN` or `PAUSED`, is terminal".

    Design: Corner/endpoints/transition_dispatch_is_conditional_action
    """
    ctx = setup_routable()
    queue_id = ctx["queue"]["id"]
    validate_success(
        api_client.transition_queue(queue_id, {"to_status": "CLOSED"}, OPS_H)
    )
    resp = api_client.transition_queue(queue_id, {"to_status": "PAUSED"}, OPS_H)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    invoice = create_invoice(ctx["contract"]["id"])
    prepare_invoice(invoice["id"])
    submitted = validate_success(
        api_client.transition_invoice(invoice["id"], {"to_status": "SUBMITTED"}, BILL_H)
    )
    assert submitted["status"] == "SUBMITTED"

    missing_occ = api_client.transition_invoice(
        invoice["id"], {"to_status": "APPROVED"}, OPS_H
    )
    validate_error(missing_occ, ApiErrorId.ERR_INVALID_REQUEST)


def test_approve_without_expected_version_rejected_but_submit_not():
    """PRD §2.8: "The `expected_contract_version` field is required on those
    two transitions when, and only when, the requested `to_status` is
    `EFFECTIVE` (for a service level) or `APPROVED` (for an invoice); requests
    targeting any other `to_status` on those same endpoints do not carry the
    field".

    Design: Corner/endpoints/transition_dispatch_is_conditional_action
    """
    ctx = setup_routable()
    invoice = create_invoice(ctx["contract"]["id"])
    prepare_invoice(invoice["id"])
    # SUBMITTED carries no version field and succeeds.
    ok = validate_success(
        api_client.transition_invoice(invoice["id"], {"to_status": "SUBMITTED"}, BILL_H)
    )
    assert ok["status"] == "SUBMITTED"
    # APPROVED without the field is a request-shape failure.
    bad = api_client.transition_invoice(
        invoice["id"], {"to_status": "APPROVED"}, OPS_H
    )
    validate_error(bad, ApiErrorId.ERR_INVALID_REQUEST)


def test_prepare_is_idempotent_per_state_and_submit_requires_lines():
    """PRD §3.12: "An invoice moves to `SUBMITTED` when a `BillingAnalyst`
    requests `to_status` of `SUBMITTED`, provided at least one invoice line
    exists for it."
    PRD §3.1: "At any time `t`, the binding service level for a contract,
    program, and metric triple is the one in `EFFECTIVE` whose
    `effective_from` is at or before `t`".
    PRD §3.9: "Each such certification contributes the fixed per-agent monthly
    rate of 4000 cents ... and the fixed monthly base fee of 50000 cents is
    added to produce `gross_cents`."

    Design: Corner/endpoints/prepare_is_idempotent_per_state_and_submit_requires_lines
    """
    # Advance the clock to the service level's effective_from so activation
    # is legal; the measurement window for period 2026-09 is the half-open
    # interval [2026-08-01, 2026-09-01), so a service level effective at
    # 2026-10-01 lies outside the window and binds nothing.
    set_clock("2026-10-01T00:00:00Z")
    ctx = setup_active_contract(
        metric="ASA", target=30, effective_from="2026-10-01T00:00:00Z"
    )
    # The service level's effective_from (2026-10-01) is after the 2026-08
    # period end, so no service level binds for the August invoice.
    invoice = create_invoice(ctx["contract"]["id"], period="2026-08")
    prepared = prepare_invoice(invoice["id"])
    lines = list_invoice_lines(invoice["id"])
    assert len(lines) == 0
    assert prepared["gross_cents"] == 50000, "base fee only with zero lines"

    resp = api_client.transition_invoice(
        invoice["id"], {"to_status": "SUBMITTED"}, BILL_H
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    # Preparation remains available while the invoice is DRAFT.
    reprepared = prepare_invoice(invoice["id"])
    assert reprepared["status"] == "DRAFT"
    assert len(list_invoice_lines(invoice["id"])) == 0


def test_pagination_envelope_on_calls():
    """PRD §2.3: "List endpoints accept two query parameters. The `limit`
    parameter caps the number of items returned; it defaults to 10, with a
    minimum of 1 and a maximum of 100. The `offset` parameter states how many
    items to skip and defaults to 0. ... Paginated list responses carry
    `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of
    the response envelope."
    PRD §3.4: "The call collection can be filtered by `contract_id`,
    `program_code`, `status`, `queue_id`, `agent_id`, and
    `handled_by_agent_id`."

    Design: Corner/cross_cutting_layers/pagination_envelope_on_calls
    """
    ctx = setup_routable()
    contract_id = ctx["contract"]["id"]
    c1 = register_call(contract_id, enqueued_at="2026-09-05T09:00:00Z")
    c2 = register_call(contract_id, enqueued_at="2026-09-05T09:01:00Z")
    c3 = register_call(contract_id, enqueued_at="2026-09-05T09:02:00Z")
    route_call(c2["id"])
    abandon_call(c3["id"])

    page1, meta1 = validate_paginated(
        api_client.list_calls(
            SUP_H, params={"contract_id": contract_id, "limit": 1, "offset": 0}
        )
    )
    assert len(page1) == 1
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 1
    assert meta1["offset"] == 0

    page3, meta3 = validate_paginated(
        api_client.list_calls(
            SUP_H, params={"contract_id": contract_id, "limit": 1, "offset": 2}
        )
    )
    assert len(page3) == 1
    assert meta3["has_more"] is False

    filtered, meta_f = validate_paginated(
        api_client.list_calls(
            SUP_H, params={"contract_id": contract_id, "status": "ABANDONED"}
        )
    )
    assert len(filtered) == 1
    assert filtered[0]["id"] == c3["id"]
    assert meta_f["total_count"] == 1


def test_immediate_consistency_after_transition():
    """PRD §3.4: "A successful route writes `queue_id`, `agent_id`,
    `assigned_via`, and `route_depth` in one stroke and increments the call's
    `version` by 1."
    PRD §3.3: "the queue with the earliest `created_at` wins, and the call is
    marked `assigned_via` of `PRIMARY` with `route_depth` of 1."

    Design: Corner/consistency_model/immediate_consistency_after_transition
    """
    ctx = setup_routable()
    call = register_call(ctx["contract"]["id"], enqueued_at="2026-09-05T09:00:00Z")
    routed = validate_success(
        api_client.transition_call(call["id"], {"to_status": "ASSIGNED"}, SUP_H)
    )
    assert routed["status"] == "ASSIGNED"
    assert routed["queue_id"] == ctx["queue"]["id"]
    assert routed["agent_id"] == ctx["agent"]["id"]
    assert routed["route_depth"] == 1
    assert routed["assigned_via"] == "PRIMARY"
    assert routed["version"] == 2

    read_back = validate_success(api_client.get_call(call["id"], SUP_H))
    assert read_back["status"] == routed["status"]
    assert read_back["queue_id"] == routed["queue_id"]
    assert read_back["agent_id"] == routed["agent_id"]
    assert read_back["route_depth"] == routed["route_depth"]
    assert read_back["assigned_via"] == routed["assigned_via"]
    assert read_back["version"] == routed["version"]
    assert read_back["updated_at"] == routed["updated_at"]
