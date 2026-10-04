from decimal import Decimal

from flask import Blueprint

from db import store, new_id, next_seq, now_iso, parse_date, clock_date, touch
from errors import ApiError, bad_request, not_found, invalid_state
from middleware import (auth, body, need, need_str, need_date, need_enum,
                        is_num, not_owner)
from response import ok
from serialize import hour_entry_json
import services as svc

bp = Blueprint("hours", __name__)

CATEGORIES = {"DIRECT_SERVICE", "TRAINING", "FUNDRAISING"}
DECISIONS = {"VERIFY", "REJECT", "VOID"}
QUANTUM = Decimal("0.25")


def _validate_hours(v):
    if not is_num(v):
        bad_request("hours must be a number")
    d = Decimal(str(v))
    if d <= 0 or d > svc.DAILY_HOUR_CAP:
        bad_request("hours must be > 0 and <= 12")
    if (d / QUANTUM) != (d / QUANTUM).to_integral_value():
        bad_request("hours must be an exact multiple of 0.25")
    return v


@bp.route("/corps/hour-entries", methods=["POST"])
def create_hour_entry():
    uid, role = auth(["CorpsMember"])
    data = body()
    # Priority 3 ownership: corps_member_id must equal X-User-ID.
    corps_member_id = data.get("corps_member_id")
    if isinstance(corps_member_id, str) and corps_member_id and corps_member_id != uid:
        not_owner("corps_member_id must equal X-User-ID")
    corps_member_id = need_str(data, "corps_member_id")
    if corps_member_id != uid:
        not_owner("corps_member_id must equal X-User-ID")
    service_date = need_date(data, "service_date")
    hours = _validate_hours(need(data, "hours"))
    category = need_enum(data, "category", CATEGORIES)
    description = data.get("description", "")
    if not isinstance(description, str):
        bad_request("description must be a string")
    m = store.members.get(corps_member_id)
    if m is None:
        not_found("CorpsMember not found")
    site = svc.site_of_member(m)
    sd = parse_date(service_date)
    if site is not None and sd < parse_date(site["service_year_start"]):
        raise ApiError("ERR_SERVICE_DATE_INVALID", 422,
                       "service_date predates the site service year")
    if sd > clock_date():
        raise ApiError("ERR_SERVICE_DATE_INVALID", 422,
                       "service_date is after the logical clock date")
    if m["service_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409,
                       "Member service_status is not ACTIVE")
    e = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
        "corps_member_id": corps_member_id,
        "service_date": service_date,
        "hours": hours,
        "category": category,
        "description": description,
        "status": "PENDING",
        "review_reason": None,
        "reviewed_by": None,
    }
    store.hour_entries[e["id"]] = e
    return ok(hour_entry_json(e), 201)


@bp.route("/corps/hour-entries/<entry_id>/review", methods=["POST"])
def review_hour_entry(entry_id):
    uid, role = auth(["ProgramManager"])
    data = body()
    decision = need(data, "decision")
    if decision not in DECISIONS:
        bad_request("decision must be VERIFY, REJECT or VOID")
    reason = data.get("reason")
    if decision in ("REJECT", "VOID"):
        if reason is None or not isinstance(reason, str) or not reason.strip():
            bad_request("reason is required for REJECT and VOID")
    elif reason is not None and not isinstance(reason, str):
        bad_request("reason must be a string")
    e = store.hour_entries.get(entry_id)
    if e is None:
        not_found("ServiceHourEntry not found")
    m = store.members.get(e["corps_member_id"])

    if decision == "VERIFY":
        if e["status"] != "PENDING":
            invalid_state("Only a PENDING entry can be verified")
        if (clock_date() - parse_date(e["service_date"])).days > 30:
            raise ApiError("ERR_VERIFICATION_WINDOW_EXPIRED", 422,
                           "Entry is older than the 30-day verification window")
        same_day = Decimal("0")
        for other in svc.entries_of_member(e["corps_member_id"]):
            if other["service_date"] == e["service_date"] \
                    and other["status"] in ("PENDING", "VERIFIED"):
                same_day += Decimal(str(other["hours"]))
        if same_day > svc.DAILY_HOUR_CAP:
            raise ApiError("ERR_DAILY_HOUR_CAP_EXCEEDED", 422,
                           "Same-day PENDING+VERIFIED hours would exceed 12.0")
        if e["category"] == "FUNDRAISING" and not svc.fundraising_cap_ok(m, e["hours"]):
            raise ApiError("ERR_FUNDRAISING_CAP_EXCEEDED", 422,
                           "Fundraising cap would be exceeded")
        e["status"] = "VERIFIED"
        e["reviewed_by"] = uid
        touch(m)
    elif decision == "REJECT":
        if e["status"] != "PENDING":
            invalid_state("Only a PENDING entry can be rejected")
        e["status"] = "REJECTED"
        e["review_reason"] = reason
        e["reviewed_by"] = uid
    else:  # VOID
        if e["status"] != "VERIFIED":
            invalid_state("Only a VERIFIED entry can be voided")
        e["status"] = "VOIDED"
        e["review_reason"] = reason
        touch(m)
    return ok(hour_entry_json(e), 200)
