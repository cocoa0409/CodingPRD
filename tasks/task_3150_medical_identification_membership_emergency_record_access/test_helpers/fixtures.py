"""Composite setup helpers for the medical identification API tests.

Every helper builds its preconditions from scratch via the API (each test runs
against a freshly restarted server with an empty database). Setup calls use the
lenient get_success_data() so failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import ApiClient, api_client
from .constants import CLOCK_DEFAULT_UTC
from .factories import (
    create_contact_payload,
    create_directive_payload,
    create_dispute_payload,
    create_member_payload,
    create_order_payload,
    create_product_payload,
    create_record_item_payload,
    create_responder_payload,
)
from .test_users import (
    TEST_USERS,
    make_guardian_headers,
    make_member_headers,
    make_responder_headers,
)


def _admin():
    return TEST_USERS["platform_admin_headers"]


def _verifier():
    return TEST_USERS["record_verifier_headers"]


def _hotline():
    return TEST_USERS["hotline_operator_headers"]


def _fulfillment():
    return TEST_USERS["fulfillment_agent_headers"]


def _ok(response, context: str):
    data = get_success_data(response)
    assert response.status_code < 300, f"Setup failed ({context}): {response.status_code} {response.text}"
    return data


# --- Clock ---------------------------------------------------------------------


def set_clock(current_utc: str = CLOCK_DEFAULT_UTC, api: ApiClient = None):
    """Set the server logical clock (admin-only test-driving endpoint)."""
    api = api or api_client
    return _ok(api.set_clock({"current_utc": current_utc}, _admin()), "set_clock")


# --- Member hierarchy ------------------------------------------------------------


def enroll_member(tier="STANDARD", dob="1990-01-01", api: ApiClient = None, **overrides):
    """Enroll a member via PlatformAdmin. Returns the member payload."""
    api = api or api_client
    payload = create_member_payload(membership_tier=tier, date_of_birth=dob, **overrides)
    return _ok(api.create_member(payload, _admin()), "create_member")


def get_member(member_id, api: ApiClient = None):
    api = api or api_client
    return _ok(api.get_member(member_id, make_member_headers(member_id)), "get_member")


def attach_guardian(dependent_id, guardian_id, relation_label="guardian", api: ApiClient = None):
    """Attach an ACTIVE GuardianLink (admin). Returns the link payload."""
    api = api or api_client
    return _ok(
        api.create_guardian_link(
            dependent_id,
            {"guardian_member_id": guardian_id, "relation_label": relation_label},
            _admin(),
        ),
        "create_guardian_link",
    )


def setup_guardian_pair(api: ApiClient = None, dependent_dob="2015-01-01", dependent_tier="STANDARD"):
    """Adult guardian + dependent member + ACTIVE GuardianLink.
    Returns (guardian, dependent, link)."""
    api = api or api_client
    guardian = enroll_member(tier="STANDARD", dob="1970-01-01", api=api)
    dependent = enroll_member(tier=dependent_tier, dob=dependent_dob, api=api)
    link = attach_guardian(dependent["id"], guardian["id"], api=api)
    return guardian, dependent, link


# --- Record items and verification --------------------------------------------------


def add_record_item(member_id, actor_headers=None, api: ApiClient = None, **overrides):
    """Capture a record item. Defaults to the member acting on their own record."""
    api = api or api_client
    headers = actor_headers or make_member_headers(member_id)
    return _ok(api.create_record_item(member_id, create_record_item_payload(**overrides), headers), "create_record_item")


def list_item_tickets(member_id, item_id, api: ApiClient = None):
    api = api or api_client
    resp = api.list_item_tickets(member_id, item_id, _verifier())
    data, _meta = validate_paginated(resp)
    return data


def open_ticket_for_item(member_id, item_id, api: ApiClient = None):
    """Return the currently OPEN verification ticket for an item."""
    tickets = list_item_tickets(member_id, item_id, api=api)
    open_tickets = [t for t in tickets if t["status"] == "OPEN"]
    assert open_tickets, f"Setup failed: no OPEN ticket for item {item_id}"
    return open_tickets[0]


def resolve_ticket(ticket_id, decision, note="reviewed", api: ApiClient = None):
    api = api or api_client
    return _ok(
        api.resolve_verification_ticket(ticket_id, {"decision": decision, "decision_note": note}, _verifier()),
        f"resolve_ticket({decision})",
    )


def approve_item(member_id, item_id, api: ApiClient = None):
    """Approve the item's open ticket, moving it to VERIFIED. Returns the ticket."""
    api = api or api_client
    ticket = open_ticket_for_item(member_id, item_id, api=api)
    resolve_ticket(ticket["id"], "APPROVE", api=api)
    return ticket


def reject_item(member_id, item_id, api: ApiClient = None):
    """Reject the item's open ticket, moving it to REJECTED. Returns the ticket."""
    api = api or api_client
    ticket = open_ticket_for_item(member_id, item_id, api=api)
    resolve_ticket(ticket["id"], "REJECT", api=api)
    return ticket


def add_verified_item(member_id, actor_headers=None, api: ApiClient = None, **overrides):
    """Capture + approve a record item. Returns the VERIFIED item."""
    api = api or api_client
    item = add_record_item(member_id, actor_headers=actor_headers, api=api, **overrides)
    approve_item(member_id, item["id"], api=api)
    return _ok(api.get_record_item(member_id, item["id"], make_member_headers(member_id)), "get_record_item")


def setup_member_with_verified_cognitive_condition(api: ApiClient = None, **member_overrides):
    """ACTIVE member with a VERIFIED COGNITIVE condition (has_cognitive_condition true).
    Returns (member, item)."""
    api = api or api_client
    set_clock(api=api)
    member = enroll_member(api=api, **member_overrides)
    item = add_verified_item(
        member["id"],
        api=api,
        item_kind="CONDITION",
        condition_kind="COGNITIVE",
        label="Dementia",
        detail="wander risk",
        severity="HIGH",
        provider_document_ref="doc-cog",
    )
    return get_member(member["id"], api=api), item


# --- Contacts / directives ------------------------------------------------------------


def add_contact(member_id, actor_headers=None, api: ApiClient = None, **overrides):
    api = api or api_client
    headers = actor_headers or make_member_headers(member_id)
    return _ok(api.create_contact(member_id, create_contact_payload(**overrides), headers), "create_contact")


def add_directive(member_id, actor_headers=None, api: ApiClient = None, **overrides):
    api = api or api_client
    headers = actor_headers or make_member_headers(member_id)
    return _ok(api.create_directive(member_id, create_directive_payload(**overrides), headers), "create_directive")


# --- Products and orders -----------------------------------------------------------------


def add_product(api: ApiClient = None, **overrides):
    api = api or api_client
    return _ok(api.create_product(create_product_payload(**overrides), _admin()), "create_product")


def place_order(member_id, product_id, actor_headers=None, api: ApiClient = None, **overrides):
    api = api or api_client
    headers = actor_headers or make_member_headers(member_id)
    return _ok(
        api.create_order(member_id, create_order_payload(product_id, **overrides), headers),
        "create_order",
    )


def confirm_order(member_id, order_id, actor_headers=None, api: ApiClient = None):
    """Confirm an order with the member's current version (OCC). Returns the CONFIRMED order."""
    api = api or api_client
    headers = actor_headers or make_member_headers(member_id)
    member = _ok(api.get_member(member_id, headers), "get_member(pre-confirm)")
    return _ok(
        api.confirm_order(member_id, order_id, {"expected_member_version": member["version"]}, headers),
        "confirm_order",
    )


def place_and_confirm_order(member_id, product_id, actor_headers=None, api: ApiClient = None, **overrides):
    """Create + confirm a MANUAL order. Returns the CONFIRMED order."""
    api = api or api_client
    order = place_order(member_id, product_id, actor_headers=actor_headers, api=api, **overrides)
    return confirm_order(member_id, order["id"], actor_headers=actor_headers, api=api)


def ship_order_full_lifecycle(member_id, product_id, api: ApiClient = None, **overrides):
    """Create + confirm + engrave + ship. Returns the SHIPPED order."""
    api = api or api_client
    order = place_and_confirm_order(member_id, product_id, api=api, **overrides)
    _ok(api.engrave_order(member_id, order["id"], _fulfillment()), "engrave_order")
    return _ok(api.ship_order(member_id, order["id"], _fulfillment()), "ship_order")


# --- Responders and access events ---------------------------------------------------------


def add_responder(api: ApiClient = None, **overrides):
    api = api or api_client
    return _ok(api.create_responder(create_responder_payload(**overrides), _admin()), "create_responder")


def grant_access(responder, member, api: ApiClient = None, lookup_method="IDENTIFIER", **overrides):
    """Perform a granted emergency access. Returns the AccessEvent payload."""
    api = api or api_client
    payload = {
        "credential_code": responder["credential_code"],
        "identifier_code": member["identifier_code"],
        "lookup_method": lookup_method,
    }
    payload.update(overrides)
    headers = (
        _hotline()
        if lookup_method == "HOTLINE"
        else make_responder_headers(responder["id"])
    )
    return _ok(api.create_access_event(payload, headers), "create_access_event")


# --- Disputes ---------------------------------------------------------------------------------


def open_dispute(member_id, item_id, actor_headers=None, api: ApiClient = None, **overrides):
    api = api or api_client
    headers = actor_headers or make_member_headers(member_id)
    return _ok(
        api.create_dispute(member_id, create_dispute_payload(item_id, **overrides), headers),
        "create_dispute",
    )


# --- Reminders ----------------------------------------------------------------------------------


def list_member_reminders(member_id, api: ApiClient = None, params=None):
    api = api or api_client
    resp = api.list_member_reminders(member_id, _admin(), params=params)
    data, _meta = validate_paginated(resp)
    return data
