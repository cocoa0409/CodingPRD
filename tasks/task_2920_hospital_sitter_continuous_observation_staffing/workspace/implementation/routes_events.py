"""Safety events, the two review branches, closure and the logical clock
(PRD 3.8 and 3.3)."""
from flask import Blueprint

import calc
import serializers as S
import services as SVC
from db import (
    ESCALATING_EVENT_KINDS,
    EVENT_KINDS,
    HARM_EVENT_KINDS,
    RESOLUTIONS,
    base_entity,
    db,
    iso,
    parse_instant,
    touch,
)
from errors import fail
from response import object_response
from validation import (
    authenticate,
    body_json,
    raw_opt_str,
    req_enum,
    req_str,
    req_str_array,
)

bp = Blueprint("events", __name__)

OFFICER_ROLES = ("SafetyOfficer", "SystemAdmin")


def _event_or_404(event_id):
    event = db.events.get(event_id)
    if event is None:
        fail("ERR_SAFETY_EVENT_NOT_FOUND")
    return event


# ---------------------------------------------------------------------------
# POST /observation/safety-events
# ---------------------------------------------------------------------------
@bp.post("/observation/safety-events")
def report_event():
    # Reserved to the two observer roles: there is no administrative substitute.
    caller = authenticate(("Sitter", "RemoteObserver"))
    body = body_json()
    order_id = req_str(body, "order_id")
    event_kind = req_enum(body, "event_kind", EVENT_KINDS)
    narrative = req_str(body, "narrative", 1, 1000)
    assignment_id = raw_opt_str(body, "assignment_id")
    order = db.orders.get(order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND")
    assignment = None
    if assignment_id is not None:
        assignment = db.assignments.get(assignment_id)
        if assignment is None:
            fail("ERR_ASSIGNMENT_NOT_FOUND")
    reporter = SVC.caller_staff(caller)
    if assignment is not None:
        SVC.require_owner(caller, assignment["staff_id"])
    event = base_entity()
    event.update({
        "order_id": order["id"],
        "assignment_id": assignment["id"] if assignment is not None else None,
        "event_kind": event_kind,
        "narrative": narrative,
        "reported_by_staff_id": reporter["id"] if reporter is not None else caller.user_id,
        "status": "REPORTED",
        "response_actions": None,
        "review_opened_by_user_id": None,
        "review_findings": None,
        "closed_by_user_id": None,
        "resolution": None,
        "occurred_at": db.clock,
    })
    db.events[event["id"]] = event
    # An attempt or an aggression escalates the order; the modality is untouched.
    if event_kind in ESCALATING_EVENT_KINDS and order["status"] in ("ACTIVE", "REASSESSMENT_DUE"):
        order["status"] = "ESCALATED"
        touch(order)
    return object_response(S.event_json(event), 201)


# ---------------------------------------------------------------------------
# POST /observation/safety-events/{id}/escalate-response
# ---------------------------------------------------------------------------
@bp.post("/observation/safety-events/<event_id>/escalate-response")
def escalate_response(event_id):
    authenticate(OFFICER_ROLES)
    body = body_json()
    response_actions = req_str_array(body, "response_actions")
    event = _event_or_404(event_id)
    if event["status"] != "REPORTED":
        fail("ERR_INVALID_EVENT_STATE", "The escalation response is only recorded from REPORTED.")
    if event["event_kind"] not in ESCALATING_EVENT_KINDS:
        fail("ERR_INVALID_EVENT_STATE",
             "This branch is reserved to elopement-attempt and aggression events.")
    # Deliberately inert: review_opened_by_user_id stays null and nothing outside
    # the event itself is mutated.
    event["status"] = "ESCALATED_RESPONSE"
    event["response_actions"] = response_actions
    touch(event)
    return object_response(S.event_json(event))


# ---------------------------------------------------------------------------
# POST /observation/safety-events/{id}/open-incident-review
# ---------------------------------------------------------------------------
@bp.post("/observation/safety-events/<event_id>/open-incident-review")
def open_incident_review(event_id):
    caller = authenticate(OFFICER_ROLES)
    body_json()
    event = _event_or_404(event_id)
    if event["status"] != "REPORTED":
        fail("ERR_INVALID_EVENT_STATE", "An incident review is only opened from REPORTED.")
    if event["event_kind"] not in HARM_EVENT_KINDS:
        fail("ERR_INVALID_EVENT_STATE",
             "This branch is reserved to fall-with-injury and self-harm events.")
    event["status"] = "INCIDENT_REVIEW"
    event["review_opened_by_user_id"] = caller.user_id
    touch(event)
    order = db.orders.get(event["order_id"])
    if order is not None:
        order["required_modality"] = "ONE_TO_ONE_SITTER"
        SVC.release_active_feeds_of_order(order["id"], "MODALITY_FORCED_TO_SITTER")
        SVC.recompute_score_and_interval(
            order, "ROLLING_EVENT_WEIGHTED", rebase_last_reassessed=False
        )
        touch(order)
    # Strictly AFTER the four cascade hops, so SUSPENDED wins over any AVAILABLE
    # that the console-idling hop may have written for the same observer.
    if event["assignment_id"] is not None:
        assignment = db.assignments.get(event["assignment_id"])
        if assignment is not None:
            watcher = db.staff.get(assignment["staff_id"])
            if watcher is not None:
                watcher["status"] = "SUSPENDED"
                watcher["suspension_reason"] = "INCIDENT_REVIEW_OPENED"
                touch(watcher)
    return object_response(S.event_json(event))


# ---------------------------------------------------------------------------
# POST /observation/safety-events/{id}/close
# ---------------------------------------------------------------------------
@bp.post("/observation/safety-events/<event_id>/close")
def close_event(event_id):
    caller = authenticate(OFFICER_ROLES)
    body = body_json()
    resolution = req_enum(body, "resolution", RESOLUTIONS)
    review_findings = raw_opt_str(body, "review_findings")
    event = _event_or_404(event_id)
    if event["status"] not in ("ESCALATED_RESPONSE", "INCIDENT_REVIEW"):
        fail("ERR_INVALID_EVENT_STATE",
             "An event is only closed from ESCALATED_RESPONSE or INCIDENT_REVIEW.")
    # Vacuous on the escalation-response branch, where the field is null.
    if event["review_opened_by_user_id"] is not None and (
        caller.user_id == event["review_opened_by_user_id"]
    ):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The officer who opened the review may not close the event.")
    incident_branch = event["status"] == "INCIDENT_REVIEW"
    if incident_branch and (review_findings is None or review_findings == ""):
        fail("ERR_REVIEW_FINDINGS_REQUIRED",
             "review_findings is mandatory on the incident-review branch.")
    event["status"] = "CLOSED"
    event["resolution"] = resolution
    event["closed_by_user_id"] = caller.user_id
    if incident_branch:
        event["review_findings"] = review_findings
    touch(event)
    order = db.orders.get(event["order_id"])
    if order is not None:
        if order["status"] == "ESCALATED":
            others_open = [
                e
                for e in calc.events_of_order(order["id"])
                if e["id"] != event["id"] and e["status"] != "CLOSED"
            ]
            if not others_open:
                order["status"] = "ACTIVE"
        SVC.recompute_score_and_interval(
            order, "ROLLING_EVENT_WEIGHTED", rebase_last_reassessed=False
        )
        if resolution == "MODALITY_ESCALATED":
            order["required_modality"] = "ONE_TO_ONE_SITTER"
            SVC.release_active_feeds_of_order(order["id"], "MODALITY_FORCED_TO_SITTER")
        touch(order)
    return object_response(S.event_json(event))


# ---------------------------------------------------------------------------
# POST /observation/_clock/set_current_utc
# ---------------------------------------------------------------------------
@bp.post("/observation/_clock/set_current_utc")
def set_clock():
    authenticate(("SystemAdmin",))
    body = body_json()
    if "current_utc" not in body or body["current_utc"] is None:
        fail("ERR_INVALID_REQUEST", "Field 'current_utc' is required.")
    parsed = parse_instant(body["current_utc"])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field 'current_utc' must be a parseable ISO-8601 instant.")
    if parsed < db.clock:
        fail("ERR_INVALID_REQUEST", "The logical clock may not be rewound.")
    db.clock = parsed
    marked, lapsed = SVC.run_reassessment_sweep()
    return object_response({
        "current_utc": iso(db.clock),
        "orders_marked_reassessment_due": marked,
        "orders_lapsed": lapsed,
    })
