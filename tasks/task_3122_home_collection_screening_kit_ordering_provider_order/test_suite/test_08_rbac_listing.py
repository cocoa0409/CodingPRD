"""RBAC denials and list-envelope pagination."""
from test_helpers import (
    TEST_USERS,
    create_order,
    create_patient,
    create_provider,
    setup_kit_shipped,
    setup_pending_order,
    setup_processing,
    validate_error,
    validate_paginated,
    ApiErrorId,
)

PA = TEST_USERS["program_admin_headers"]
FA = TEST_USERS["fulfillment_agent_headers"]
LT = TEST_USERS["lab_technician_headers"]
NAV = TEST_USERS["navigator_headers"]


def test_lab_technician_cannot_confirm_eligibility(api):
    """PRD §4: "POST /screening/orders/{orderId}/eligibility/confirm |
    Confirm eligibility screening passed | ProgramAdmin".
    PRD §2.1: "Once the headers are present, the role is matched against the
    endpoint's authorization list; a role that is not permitted on that
    endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/lab_technician_cannot_confirm_eligibility
    """
    ctx = setup_pending_order()
    resp = api.confirm_eligibility(ctx["order"]["id"], LT)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_fulfillment_agent_cannot_result_specimen(api):
    """PRD §4: "POST /screening/specimens/{specimenId}/result | Finalize the
    screening result and deliver to the ordering provider | LabTechnician".
    PRD §2.1: "Once the headers are present, the role is matched against the
    endpoint's authorization list; a role that is not permitted on that
    endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/fulfillment_agent_cannot_result_specimen
    """
    ctx = setup_processing()
    api.record_adequacy(ctx["specimen"]["id"], {"adequacy": "ADEQUATE"}, LT)
    resp = api.result_specimen(ctx["specimen"]["id"], {"outcome": "NEGATIVE"}, FA)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_navigator_cannot_dispatch_reminders(api):
    """PRD §4: "POST /screening/orders/{orderId}/reminders/dispatch |
    Dispatch all due reminders for the order | ProgramAdmin".
    PRD §2.1: "Once the headers are present, the role is matched against the
    endpoint's authorization list; a role that is not permitted on that
    endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/navigator_cannot_dispatch_reminders
    """
    ctx = setup_kit_shipped()
    resp = api.dispatch_reminders(ctx["order"]["id"], NAV)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_list_orders_pagination_envelope(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit`,
    `offset`, `total_count`, and `has_more`, where `total_count` is the total
    number of matching records and `has_more` indicates whether further
    records exist beyond the returned window."
    PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."

    Design: Corner/endpoints/list_orders_pagination_envelope
    """
    p1 = create_patient(external_ref="p-ls1")
    p2 = create_patient(external_ref="p-ls2")
    provider = create_provider()
    create_order(p1, provider)
    create_order(p2, provider)

    resp = api.list_orders(PA, params={"limit": 1, "offset": 0})
    body = resp.json()
    assert resp.status_code == 200
    assert body["meta"].get("api_request_id")
    assert body["response_type"] == "array"
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
