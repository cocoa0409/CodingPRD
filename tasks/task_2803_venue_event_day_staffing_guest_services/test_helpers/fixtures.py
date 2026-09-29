"""Composite builders that assemble preconditions through the public API only.

The harness restarts the service before every test, so each test begins against
an empty store and must build everything it needs from scratch.  Each builder
below performs one or a few calls, asserts the call succeeded, and returns the
created resource so a test can keep asserting on it.

Actor discipline: every builder uses the single role the endpoint table names for
that endpoint, and a worker action is always sent with headers built from the id
of the worker record being acted for.
"""

from typing import Any, Dict, List, Optional

import pytest

from . import factories as f
from .api_client import ApiClient
from .assertions import created, ok
from .test_users import (
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    SUPERVISOR_HEADERS,
    make_staff_member_headers,
)


# ------------------------------------------------------------------ tier 0: client


@pytest.fixture
def client() -> ApiClient:
    """A client pointed at the service under test."""
    return ApiClient()


# ------------------------------------------------------------------ tier 1: clock


def set_clock(client: ApiClient, instant: str, headers: Optional[Dict] = None) -> str:
    """Pin the logical clock to an explicit UTC instant."""
    response = client.set_clock(instant, headers or DIRECTOR_HEADERS)
    ok(response)
    return instant


# ------------------------------------------------------------------ tier 2: single rows


def create_event(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return created(client.create_event(f.event_payload(**overrides), DIRECTOR_HEADERS))


def read_event(client: ApiClient, event_id: str, headers: Optional[Dict] = None):
    return ok(client.get_event(event_id, headers or DIRECTOR_HEADERS))


def event_version(client: ApiClient, event_id: str) -> int:
    return read_event(client, event_id)["version"]


def patch_event(client: ApiClient, event_id: str, **fields: Any) -> Dict[str, Any]:
    return ok(client.update_event(event_id, dict(fields), DIRECTOR_HEADERS))


def create_position_type(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return created(
        client.create_position_type(f.position_type_payload(**overrides), COORDINATOR_HEADERS)
    )


def create_usher(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return created(client.create_position_type(f.usher_payload(**overrides), COORDINATOR_HEADERS))


def create_ticket_taker(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return created(
        client.create_position_type(f.ticket_taker_payload(**overrides), COORDINATOR_HEADERS)
    )


def create_elevator_operator(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return created(
        client.create_position_type(
            f.elevator_operator_payload(**overrides), COORDINATOR_HEADERS
        )
    )


def create_guest_services_rep(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return created(
        client.create_position_type(
            f.guest_services_rep_payload(**overrides), COORDINATOR_HEADERS
        )
    )


def create_plan(
    client: ApiClient, event_id: str, plan_variant: str = "FORECAST_BASED", **overrides: Any
) -> Dict[str, Any]:
    return created(
        client.create_staffing_plan(
            f.staffing_plan_payload(event_id, plan_variant, **overrides), COORDINATOR_HEADERS
        )
    )


def read_plan(client: ApiClient, plan_id: str) -> Dict[str, Any]:
    return ok(client.get_staffing_plan(plan_id, COORDINATOR_HEADERS))


def create_slot(
    client: ApiClient, plan_id: str, position_type_id: str, **overrides: Any
) -> Dict[str, Any]:
    return created(
        client.create_position_slot(
            f.position_slot_payload(plan_id, position_type_id, **overrides),
            COORDINATOR_HEADERS,
        )
    )


def read_slot(client: ApiClient, slot_id: str, headers: Optional[Dict] = None):
    return ok(client.get_position_slot(slot_id, headers or COORDINATOR_HEADERS))


def create_member(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return created(
        client.create_staff_member(f.staff_member_payload(**overrides), COORDINATOR_HEADERS)
    )


def read_member(client: ApiClient, member_id: str, headers: Optional[Dict] = None):
    return ok(client.get_staff_member(member_id, headers or COORDINATOR_HEADERS))


def change_member_status(
    client: ApiClient, member_id: str, target_status: str, reason: str
) -> Dict[str, Any]:
    return ok(
        client.staff_member_status_change(
            member_id, f.status_change_payload(target_status, reason), COORDINATOR_HEADERS
        )
    )


def create_certification(
    client: ApiClient, member_id: str, cert_type: str, **overrides: Any
) -> Dict[str, Any]:
    return created(
        client.create_certification(
            f.certification_payload(member_id, cert_type, **overrides), COORDINATOR_HEADERS
        )
    )


def certify(client: ApiClient, member_id: str, *cert_types: str) -> List[Dict[str, Any]]:
    """Record every named credential for one worker."""
    return [create_certification(client, member_id, cert_type) for cert_type in cert_types]


def create_bid(client: ApiClient, member_id: str, slot_id: str) -> Dict[str, Any]:
    """The worker files their own bid, as themselves."""
    return created(
        client.create_shift_bid(
            f.shift_bid_payload(member_id, slot_id), make_staff_member_headers(member_id)
        )
    )


def read_bid(client: ApiClient, bid_id: str) -> Dict[str, Any]:
    return ok(client.get_shift_bid(bid_id, COORDINATOR_HEADERS))


def create_assignment(client: ApiClient, slot_id: str, member_id: str) -> Dict[str, Any]:
    return created(
        client.create_staff_assignment(
            f.staff_assignment_payload(slot_id, member_id), COORDINATOR_HEADERS
        )
    )


def read_assignment(client: ApiClient, assignment_id: str, headers: Optional[Dict] = None):
    return ok(client.get_staff_assignment(assignment_id, headers or COORDINATOR_HEADERS))


def attendance(
    client: ApiClient,
    assignment_id: str,
    action: str,
    at: Optional[str] = None,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Record one attendance action, optionally pinning the clock first."""
    if at is not None:
        set_clock(client, at)
    return ok(
        client.record_attendance(
            assignment_id, f.attendance_payload(action), headers or COORDINATOR_HEADERS
        )
    )


def create_issue(client: ApiClient, event_id: str, **overrides: Any) -> Dict[str, Any]:
    return created(
        client.create_guest_issue(f.guest_issue_payload(event_id, **overrides), SUPERVISOR_HEADERS)
    )


def read_issue(client: ApiClient, issue_id: str, headers: Optional[Dict] = None):
    return ok(client.get_guest_issue(issue_id, headers or SUPERVISOR_HEADERS))


def assign_issue(
    client: ApiClient, issue_id: str, member_id: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    return ok(
        client.assign_guest_issue(
            issue_id, f.issue_assign_payload(member_id), headers or SUPERVISOR_HEADERS
        )
    )


def resolve_issue(
    client: ApiClient,
    issue_id: str,
    resolution_type: str,
    headers: Optional[Dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return ok(
        client.resolve_guest_issue(
            issue_id,
            f.issue_resolve_payload(resolution_type, **overrides),
            headers or SUPERVISOR_HEADERS,
        )
    )


def file_refund(
    client: ApiClient, issue_id: str, cents: int, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    return ok(
        client.file_refund_request(
            issue_id, f.refund_request_payload(cents), headers or SUPERVISOR_HEADERS
        )
    )


def decide_refund(
    client: ApiClient, issue_id: str, decision: str, headers: Optional[Dict] = None
) -> Dict[str, Any]:
    return ok(
        client.file_refund_decision(
            issue_id, f.refund_decision_payload(decision), headers or SUPERVISOR_HEADERS
        )
    )


def create_resource(client: ApiClient, event_id: str, **overrides: Any) -> Dict[str, Any]:
    return created(
        client.create_accessibility_resource(
            f.accessibility_resource_payload(event_id, **overrides), SUPERVISOR_HEADERS
        )
    )


def read_resource(client: ApiClient, resource_id: str) -> Dict[str, Any]:
    return ok(client.get_accessibility_resource(resource_id, SUPERVISOR_HEADERS))


def set_resource_status(client: ApiClient, resource_id: str, status: str) -> Dict[str, Any]:
    return ok(
        client.update_accessibility_resource(
            resource_id, {"status": status}, SUPERVISOR_HEADERS
        )
    )


def create_booking(client: ApiClient, resource_id: str, **overrides: Any) -> Dict[str, Any]:
    return created(
        client.create_accessibility_request(
            f.accessibility_request_payload(resource_id, **overrides), SUPERVISOR_HEADERS
        )
    )


def transition_booking(
    client: ApiClient, request_id: str, target_status: str, **overrides: Any
) -> Dict[str, Any]:
    return ok(
        client.transition_accessibility_request(
            request_id,
            f.access_transition_payload(target_status, **overrides),
            SUPERVISOR_HEADERS,
        )
    )


def create_satisfaction_response(
    client: ApiClient, event_id: str, zone_code: str, score: int, **overrides: Any
) -> Dict[str, Any]:
    return created(
        client.create_satisfaction_response(
            f.satisfaction_response_payload(event_id, zone_code, score, **overrides),
            SUPERVISOR_HEADERS,
        )
    )


# ------------------------------------------------------------------ tier 3: lifecycle


def activate_plan(
    client: ApiClient,
    plan_id: str,
    event_id: str,
    expected_event_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Activate a DRAFT plan, reading the event version fresh unless told otherwise."""
    version = (
        expected_event_version
        if expected_event_version is not None
        else event_version(client, event_id)
    )
    return ok(
        client.activate_staffing_plan(
            plan_id, f.plan_activate_payload(expected_event_version=version), COORDINATOR_HEADERS
        )
    )


def advance_event(
    client: ApiClient,
    event_id: str,
    target_status: str,
    expected_event_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Drive the event lifecycle one step.

    The lifecycle write is not version-guarded — activation is the only guarded
    write — so `expected_event_version` is sent only when a caller asks for it.
    """
    payload = (
        f.event_lifecycle_payload(target_status)
        if expected_event_version is None
        else f.event_lifecycle_payload(
            target_status, expected_event_version=expected_event_version
        )
    )
    return ok(client.event_lifecycle(event_id, payload, DIRECTOR_HEADERS))


def run_payout(client: ApiClient, event_id: str, phase: str) -> Dict[str, Any]:
    return ok(client.event_payout_run(event_id, f.payout_run_payload(phase), DIRECTOR_HEADERS))


def run_bid_award(client: ApiClient, slot_id: str) -> Dict[str, Any]:
    return ok(client.run_bid_award(slot_id, COORDINATOR_HEADERS))


def award_bid(client: ApiClient, bid_id: str) -> Dict[str, Any]:
    return ok(client.award_shift_bid(bid_id, COORDINATOR_HEADERS))


def withdraw_bid(client: ApiClient, bid_id: str, member_id: str) -> Dict[str, Any]:
    return ok(client.withdraw_shift_bid(bid_id, make_staff_member_headers(member_id)))


def auto_fill(client: ApiClient, request_id: str) -> Dict[str, Any]:
    return ok(client.auto_fill_backfill_request(request_id, COORDINATOR_HEADERS))


def backfill_requests_for_assignment(
    client: ApiClient, triggering_assignment_id: str
) -> List[Dict[str, Any]]:
    response = client.list_backfill_requests(
        COORDINATOR_HEADERS, {"triggering_assignment_id": triggering_assignment_id}
    )
    items, _meta = _page(response)
    return items


def backfill_requests_for_slot(client: ApiClient, slot_id: str) -> List[Dict[str, Any]]:
    response = client.list_backfill_requests(
        COORDINATOR_HEADERS, {"position_slot_id": slot_id}
    )
    items, _meta = _page(response)
    return items


def _page(response):
    from .assertions import page

    return page(response)


# ------------------------------------------------------------------ tier 4: scenes


def event_with_active_plan(
    client: ApiClient,
    *,
    position_type_payload: Optional[Dict[str, Any]] = None,
    slot_overrides: Optional[Dict[str, Any]] = None,
    plan_variant: str = "FORECAST_BASED",
    **event_overrides: Any,
) -> Dict[str, Any]:
    """Event in PLANNED with one ACTIVE plan carrying one shift block.

    Returns a context dict with the event, position type, plan and slot as read
    back after activation.
    """
    event = create_event(client, **event_overrides)
    if position_type_payload is None:
        position_type = create_ticket_taker(client)
    else:
        position_type = created(
            client.create_position_type(position_type_payload, COORDINATOR_HEADERS)
        )
    plan = create_plan(client, event["id"], plan_variant)
    slot = create_slot(client, plan["id"], position_type["id"], **(slot_overrides or {}))
    plan = activate_plan(client, plan["id"], event["id"])
    return {
        "event": read_event(client, event["id"]),
        "position_type": position_type,
        "plan": plan,
        "slot": read_slot(client, slot["id"]),
    }


def event_in_progress_with_slot(
    client: ApiClient, **kwargs: Any
) -> Dict[str, Any]:
    """The scene above, driven on to IN_PROGRESS so attendance may be recorded."""
    context = event_with_active_plan(client, **kwargs)
    event = advance_event(client, context["event"]["id"], "IN_PROGRESS")
    context["event"] = event
    context["plan"] = read_plan(client, context["plan"]["id"])
    context["slot"] = read_slot(client, context["slot"]["id"])
    return context


def pooled_member(
    client: ApiClient, *certifications: str, **overrides: Any
) -> Dict[str, Any]:
    """A worker enrolled in the backfill pool, holding the named credentials."""
    overrides.setdefault("in_backfill_pool", True)
    member = create_member(client, **overrides)
    certify(client, member["id"], *certifications)
    return read_member(client, member["id"])


def certified_member(
    client: ApiClient, *certifications: str, **overrides: Any
) -> Dict[str, Any]:
    member = create_member(client, **overrides)
    certify(client, member["id"], *certifications)
    return read_member(client, member["id"])


def completed_assignment(
    client: ApiClient,
    *,
    check_in_at: str,
    check_out_at: str,
    slot_overrides: Optional[Dict[str, Any]] = None,
    member_overrides: Optional[Dict[str, Any]] = None,
    position_type_payload: Optional[Dict[str, Any]] = None,
    **event_overrides: Any,
) -> Dict[str, Any]:
    """One worker checked in and out of one block on an IN_PROGRESS event."""
    context = event_in_progress_with_slot(
        client,
        position_type_payload=position_type_payload,
        slot_overrides=slot_overrides,
        **event_overrides,
    )
    member = create_member(client, **(member_overrides or {}))
    assignment = create_assignment(client, context["slot"]["id"], member["id"])
    attendance(client, assignment["id"], "CHECK_IN", at=check_in_at)
    assignment = attendance(client, assignment["id"], "CHECK_OUT", at=check_out_at)
    context["member"] = read_member(client, member["id"])
    context["assignment"] = assignment
    context["slot"] = read_slot(client, context["slot"]["id"])
    return context


def issue_in_progress(
    client: ApiClient,
    event_id: str,
    *,
    responder_certifications: tuple = ("CODE_OF_CONDUCT",),
    member_overrides: Optional[Dict[str, Any]] = None,
    **issue_overrides: Any,
) -> Dict[str, Any]:
    """A filed issue handed to an active credentialled responder."""
    issue = create_issue(client, event_id, **issue_overrides)
    responder = certified_member(client, *responder_certifications, **(member_overrides or {}))
    issue = assign_issue(client, issue["id"], responder["id"])
    return {"issue": issue, "responder": responder}
