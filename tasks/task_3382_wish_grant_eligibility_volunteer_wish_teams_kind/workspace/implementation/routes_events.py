"""WishEvent scheduling (clearance / blackout / RAPID SLA guards) and
completion (the grant cascade)."""

from datetime import timedelta

from flask import Blueprint, request

from auth import require_roles
from cascade import lines_of_plan, consume_offer, approved_plan_of_wish
from db import STORE, now, new_entity, touch
from errors import ApiError
from resp import ok, created, list_resp
from serialize import ser_event
from util import (
    body_json, req_str, req_date, parse_date, pagination, paginate, bad,
)

bp = Blueprint("events", __name__)

RAPID_SLA_DAYS = 14


@bp.post("/wish-grant/wish-events")
@require_roles("WishCoordinator")
def create_event():
    body = body_json()
    wish_id = req_str(body, "wish_id")
    start = req_date(body, "event_start_date")
    end = req_date(body, "event_end_date")
    if end < start:
        bad("event_end_date must be >= event_start_date")

    wish = STORE["wishes"].get(wish_id)
    if wish is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Wish not found")
    if wish["status"] != "READY_TO_SCHEDULE":
        raise ApiError(
            "ERR_INVALID_WISH_STATE", 409,
            "Wish %s does not accept event scheduling" % wish["status"],
        )

    if wish["wish_type"] == "TRAVEL":
        covered = any(
            c["wish_id"] == wish["id"]
            and c["status"] in ("CLEARED", "CONDITIONAL")
            and c["valid_until"] is not None
            and c["valid_until"] >= end
            for c in STORE["clearances"].values()
        )
        if not covered:
            raise ApiError(
                "ERR_MEDICAL_CLEARANCE_INVALID", 422,
                "TRAVEL scheduling needs a CLEARED/CONDITIONAL clearance "
                "covering event_end_date",
            )

    child = STORE["children"][wish["child_id"]]
    for w in child["treatment_windows"]:
        ws = parse_date(w["start_date"], "start_date")
        we = parse_date(w["end_date"], "end_date")
        # Closed intervals: touching boundaries conflict.
        if start <= we and ws <= end:
            raise ApiError(
                "ERR_TREATMENT_BLACKOUT_CONFLICT", 409,
                "Event window intersects a treatment window",
            )

    if wish["urgency"] == "RAPID":
        deadline = wish["determined_at"].date() + timedelta(days=RAPID_SLA_DAYS)
        if start > deadline:
            raise ApiError(
                "ERR_URGENT_SLA_VIOLATION", 422,
                "RAPID wish must start by %s" % deadline.isoformat(),
            )

    ev = new_entity(
        wish_id=wish["id"],
        event_start_date=start,
        event_end_date=end,
        status="SCHEDULED",
        completed_at=None,
    )
    STORE["events"][ev["id"]] = ev
    wish["status"] = "SCHEDULED"
    touch(wish)
    return created(ser_event(ev))


@bp.get("/wish-grant/wishes/<wid>/wish-events")
@require_roles("WishCoordinator", "ChapterDirector", "MedicalProvider")
def list_events(wid):
    wish = STORE["wishes"].get(wid)
    if wish is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Wish not found")
    limit, offset = pagination()
    items = sorted(STORE["events"].values(), key=lambda e: e["created_at"])
    items = [e for e in items if e["wish_id"] == wid]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, total, has_more = paginate(items, limit, offset)
    return list_resp([ser_event(e) for e in page], total, limit, offset, has_more)


@bp.post("/wish-grant/wish-events/<eid>/complete")
@require_roles("WishCoordinator")
def complete_event(eid):
    ev = STORE["events"].get(eid)
    if ev is None:
        raise ApiError("ERR_NOT_FOUND", 404, "WishEvent not found")
    body_json(required=False)
    if ev["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_EVENT_STATE", 409,
            "Event is not SCHEDULED",
        )
    wish = STORE["wishes"][ev["wish_id"]]
    if wish["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_WISH_STATE", 409,
            "Wish is not SCHEDULED",
        )

    ts = now()
    ev["status"] = "COMPLETED"
    ev["completed_at"] = ts
    touch(ev)

    wish["status"] = "GRANTED"
    wish["granted_at"] = ts
    touch(wish)

    plan = approved_plan_of_wish(wish["id"])
    if plan is not None:
        plan["status"] = "COMPLETED"
        touch(plan)
        for l in lines_of_plan(plan["id"]):
            if l["status"] == "COMMITTED":
                l["status"] = "CONSUMED"
                touch(l)
                offer = STORE["offers"].get(l["donation_offer_id"])
                if offer is not None:
                    consume_offer(offer, l["quantity"])

    chapter = STORE["chapters"].get(wish["chapter_id"])
    if chapter is not None:
        touch(chapter)

    return ok(ser_event(ev))
