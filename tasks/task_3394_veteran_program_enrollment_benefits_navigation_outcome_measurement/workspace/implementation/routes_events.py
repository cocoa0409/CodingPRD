"""Routes: community events and event registrations (seating, travel awards,
waitlist promotion)."""
from flask import Blueprint, request

import db
import services
from constants import ACCOMMODATIONS
from errors import ApiError
from middleware import authenticate, require_role
from response import ok_object, ok_list
from validation import (
    get_body, req_str, req_enum, req_int, opt_int, req_dt, opt_enum_list,
    pagination_params,
)

bp = Blueprint("events", __name__)


@bp.post("/veteran-services/community-events")
def create_community_event():
    uid, role = authenticate()
    body = get_body()
    name = req_str(body, "name")
    starts_at = req_dt(body, "starts_at")
    ends_at = req_dt(body, "ends_at")
    if not ends_at > starts_at:
        raise ApiError("ERR_INVALID_REQUEST",
                       "ends_at must be strictly after starts_at", 400)
    capacity = req_int(body, "capacity", minimum=1)
    seat_count = req_int(body, "accessibility_seat_count", minimum=0)
    if seat_count > capacity:
        raise ApiError("ERR_INVALID_REQUEST",
                       "accessibility_seat_count must not exceed capacity", 400)
    travel_budget_cents = req_int(body, "travel_budget_cents", minimum=0)
    require_role(role, ["EventCoordinator"])
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "name": name, "starts_at": starts_at, "ends_at": ends_at,
        "capacity": capacity, "accessibility_seat_count": seat_count,
        "travel_budget_cents": travel_budget_cents,
        "registered_count": 0, "accessibility_seats_used": 0,
        "travel_budget_remaining_cents": travel_budget_cents,
        "_next_queue_position": 1,
    }
    services.stamp_new(rec)
    db.STORE["community_events"][rec["id"]] = rec
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/community-events")
def list_community_events():
    uid, role = authenticate()
    limit, offset = pagination_params()
    require_role(role, ["EventCoordinator", "IntakeCoordinator", "ProgramMember"])
    items = sorted(db.STORE["community_events"].values(),
                   key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([services.serialize(e) for e in page], limit, offset, total)


@bp.post("/veteran-services/event-registrations")
def create_event_registration():
    uid, role = authenticate()
    body = get_body()
    member_id = req_str(body, "member_id")
    community_event_id = req_str(body, "community_event_id")
    accommodation_needs = opt_enum_list(body, "accommodation_needs", ACCOMMODATIONS,
                                        default=[])
    travel_request_cents = opt_int(body, "travel_request_cents", default=0, minimum=0)
    require_role(role, ["EventCoordinator", "IntakeCoordinator"])
    # Existence: body FKs in declared input order
    member = db.STORE["members"].get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "member does not exist", 404)
    event = db.STORE["community_events"].get(community_event_id)
    if event is None:
        raise ApiError("ERR_EVENT_NOT_FOUND", "community event does not exist", 404)
    # Priority 12: half-open schedule overlap against the member's live registrations
    if services.event_schedule_conflict(member_id, event):
        raise ApiError("ERR_EVENT_SCHEDULE_CONFLICT",
                       "the event interval conflicts with an existing registration", 409)
    queue_position = event["_next_queue_position"]
    event["_next_queue_position"] = queue_position + 1
    needs_accessibility = len(accommodation_needs) > 0
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "member_id": member_id, "community_event_id": community_event_id,
        "accommodation_needs": accommodation_needs,
        "travel_request_cents": travel_request_cents,
        "travel_award_cents": 0,
        "queue_position": queue_position,
        "status": None,
    }
    services.stamp_new(rec)
    # calculations.registration_seating (capacity boundary is inclusive-full)
    if (event["registered_count"] < event["capacity"]
            and (not needs_accessibility
                 or event["accessibility_seats_used"] < event["accessibility_seat_count"])):
        rec["status"] = "CONFIRMED"
        event["registered_count"] += 1
        if needs_accessibility:
            event["accessibility_seats_used"] += 1
        award = services.travel_award_amount(travel_request_cents, event)
        rec["travel_award_cents"] = award
        event["travel_budget_remaining_cents"] -= award
        services.bump(event)
    else:
        rec["status"] = "WAITLISTED"  # waitlisted rows hold no award
    db.STORE["event_registrations"][rec["id"]] = rec
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/event-registrations")
def list_event_registrations():
    uid, role = authenticate()
    limit, offset = pagination_params()
    require_role(role, ["EventCoordinator", "IntakeCoordinator"])
    member_id = request.args.get("member_id")
    community_event_id = request.args.get("community_event_id")
    status = request.args.get("status")
    items = [r for r in db.STORE["event_registrations"].values()
             if (member_id is None or r["member_id"] == member_id)
             and (community_event_id is None or r["community_event_id"] == community_event_id)
             and (status is None or r["status"] == status)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([services.serialize(r) for r in page], limit, offset, total)


@bp.get("/veteran-services/event-registrations/<registration_id>")
def get_event_registration(registration_id):
    uid, role = authenticate()
    require_role(role, ["EventCoordinator", "IntakeCoordinator"])
    rec = db.STORE["event_registrations"].get(registration_id)
    if rec is None:
        raise ApiError("ERR_REGISTRATION_NOT_FOUND", "event registration does not exist", 404)
    return ok_object(services.serialize(rec))


@bp.post("/veteran-services/event-registrations/<registration_id>/transition")
def transition_event_registration(registration_id):
    uid, role = authenticate()
    body = get_body()
    action = req_enum(body, "action", ("CANCEL", "ATTEND"))
    require_role(role, ["EventCoordinator", "IntakeCoordinator"])
    reg = db.STORE["event_registrations"].get(registration_id)
    if reg is None:
        raise ApiError("ERR_REGISTRATION_NOT_FOUND", "event registration does not exist", 404)
    if action == "ATTEND":
        # Priority 7 then priority 11 (event must have started)
        if reg["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE", "registration is not CONFIRMED", 409)
        event = db.STORE["community_events"].get(reg["community_event_id"])
        if db.now() < event["starts_at"]:
            raise ApiError("ERR_EVENT_NOT_STARTED", "the event has not started", 422)
        reg["status"] = "ATTENDED"
        services.bump(reg)
        return ok_object(services.serialize(reg))
    # CANCEL
    if reg["status"] not in ("CONFIRMED", "WAITLISTED"):
        raise ApiError("ERR_INVALID_STATE",
                       "registration cannot be cancelled from its current state", 409)
    was_confirmed = reg["status"] == "CONFIRMED"
    reg["status"] = "CANCELLED"
    services.bump(reg)
    if was_confirmed:
        event = db.STORE["community_events"].get(reg["community_event_id"])
        event["registered_count"] -= 1
        if reg["accommodation_needs"]:
            event["accessibility_seats_used"] -= 1
        event["travel_budget_remaining_cents"] += reg["travel_award_cents"]
        # calculations.waitlist_promotion: exactly one, smallest queue_position
        # whose accommodation needs fit the now-available seats
        candidates = [r for r in db.STORE["event_registrations"].values()
                      if r["community_event_id"] == event["id"]
                      and r["status"] == "WAITLISTED"
                      and (not r["accommodation_needs"]
                           or event["accessibility_seats_used"] < event["accessibility_seat_count"])]
        candidates.sort(key=lambda r: r["queue_position"])
        if candidates:
            target = candidates[0]
            target["status"] = "CONFIRMED"
            event["registered_count"] += 1
            if target["accommodation_needs"]:
                event["accessibility_seats_used"] += 1
            award = services.travel_award_amount(target["travel_request_cents"], event)
            target["travel_award_cents"] = award
            event["travel_budget_remaining_cents"] -= award
            services.bump(target)
        services.bump(event)
    return ok_object(services.serialize(reg))
