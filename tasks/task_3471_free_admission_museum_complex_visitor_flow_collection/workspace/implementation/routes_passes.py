"""Timed entry passes (PRD 3.1): reserve, list, read, cancel, admit."""

from flask import Blueprint

import constants
import db
import serializers
import util
from envelope import listing, success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("timed_entry_passes", __name__)

PASS_CREATE_ROLES = ["Public", "Member", "VisitorServices"]
PASS_READ_ROLES = ["PlatformAdmin", "VisitorServices", "SecurityScreener", "Member", "Public"]
ACTIVE_PASS_STATUSES = ("RESERVED", "ADMITTED")


@bp.post("/campus/museums/<mid>/timed-entry-passes")
def create_pass(mid):
    uid, role = auth()
    require_role(role, PASS_CREATE_ROLES)
    museum = get_or_404("museums", mid, "Museum")  # (3) path existence
    b = util.body()
    # (4) body FK existence: holder_member_id, when provided, must exist
    holder_member_id = b.get("holder_member_id")
    if holder_member_id is not None:
        get_or_404("members", holder_member_id, "Member")
    # (9) request shape
    visitor_name = util.req_str(b, "visitor_name")
    visit_date = util.req_date(b, "visit_date")
    entry_quarter_hour = util.req_int(b, "entry_quarter_hour", minimum=0, maximum=29)
    # Museum static gate (PRD 3.1 narrative order: flag before closure/quotas)
    if not museum["requires_timed_pass"]:
        fail("ERR_TIMED_PASS_NOT_USED_HERE", "This museum does not use timed entry passes")
    # (10) duplicate pass: one non-terminal pass per (museum, visitor_name, visit_date)
    for p in db.STORE["timed_entry_passes"].values():
        if (
            p["museum_id"] == museum["id"]
            and p["visitor_name"] == visitor_name
            and p["visit_date"] == visit_date
            and p["status"] in ACTIVE_PASS_STATUSES
        ):
            fail("ERR_DUPLICATE_PASS", "Visitor already holds a pass for this museum and date")
    # (13) closure dates
    if visit_date in museum["closed_dates"]:
        fail("ERR_MUSEUM_CLOSED_ON_DATE", "Museum is closed on the requested visit date")
    # (16) capacities: slot quota first, then daily quota
    slot_used = sum(
        1
        for p in db.STORE["timed_entry_passes"].values()
        if p["museum_id"] == museum["id"]
        and p["visit_date"] == visit_date
        and p["entry_quarter_hour"] == entry_quarter_hour
        and p["status"] in ACTIVE_PASS_STATUSES
    )
    if slot_used >= museum["quarter_hour_pass_quota"]:
        fail("ERR_SLOT_QUOTA_EXHAUSTED", "The requested entry slot is full")
    daily_used = sum(
        1
        for p in db.STORE["timed_entry_passes"].values()
        if p["museum_id"] == museum["id"]
        and p["visit_date"] == visit_date
        and p["status"] in ACTIVE_PASS_STATUSES
    )
    if daily_used >= museum["daily_pass_quota"]:
        fail("ERR_DAILY_QUOTA_EXHAUSTED", "The museum's daily pass quota is exhausted")
    p = db.new_entity(
        {
            "museum_id": museum["id"],
            "visitor_name": visitor_name,
            "holder_member_id": holder_member_id,
            "visit_date": visit_date,
            "entry_quarter_hour": entry_quarter_hour,
            "status": "RESERVED",
            "admitted_slot": None,
            "created_by_user_id": uid,
        }
    )
    db.STORE["timed_entry_passes"][p["id"]] = p
    return success(serializers.timed_entry_pass(p), 201)


@bp.get("/campus/timed-entry-passes")
def list_passes():
    _uid, role = auth()
    require_role(role, PASS_READ_ROLES)
    limit, offset = util.pagination()
    f_museum = util.request.args.get("museum_id")
    f_date = util.request.args.get("visit_date")
    f_member = util.request.args.get("holder_member_id")
    rows = []
    for p in db.all_sorted("timed_entry_passes"):
        if f_museum is not None and p["museum_id"] != f_museum:
            continue
        if f_date is not None and p["visit_date"] != f_date:
            continue
        if f_member is not None and p["holder_member_id"] != f_member:
            continue
        rows.append(p)
    page = rows[offset : offset + limit]
    return listing([serializers.timed_entry_pass(p) for p in page], limit, offset, len(rows))


@bp.get("/campus/timed-entry-passes/<pid>")
def get_pass(pid):
    _uid, role = auth()
    require_role(role, PASS_READ_ROLES)
    p = get_or_404("timed_entry_passes", pid, "TimedEntryPass")
    return success(serializers.timed_entry_pass(p))


@bp.post("/campus/timed-entry-passes/<pid>/cancel")
def cancel_pass(pid):
    uid, role = auth()
    require_role(role, PASS_CREATE_ROLES)
    p = get_or_404("timed_entry_passes", pid, "TimedEntryPass")
    # Ownership (PRD 2.1): Public cancels only own passes; Member only as holder;
    # VisitorServices may cancel any.
    if role == "Public" and p["created_by_user_id"] != uid:
        fail("ERR_UNAUTHORIZED_ROLE", "Public callers may cancel only their own passes")
    if role == "Member" and p["holder_member_id"] != uid:
        fail("ERR_UNAUTHORIZED_ROLE", "Member callers may cancel only passes they hold")
    # (5) transition legality
    if p["status"] != "RESERVED":
        fail("ERR_INVALID_STATE", "Only a RESERVED pass can be cancelled")
    p["status"] = "CANCELLED"
    db.touch(p)
    return success(serializers.timed_entry_pass(p))


@bp.post("/campus/timed-entry-passes/<pid>/admit")
def admit_pass(pid):
    _uid, role = auth()
    require_role(role, ["SecurityScreener"])
    p = get_or_404("timed_entry_passes", pid, "TimedEntryPass")
    # (5) transition legality
    if p["status"] != "RESERVED":
        fail("ERR_INVALID_STATE", "Only a RESERVED pass can be admitted")
    museum = db.STORE["museums"].get(p["museum_id"])
    # (13) closure (unreachable in practice: the close-day cascade expires all
    # RESERVED passes on the closed date) -- wired per the error catalog.
    if museum is not None and p["visit_date"] in museum["closed_dates"]:
        fail("ERR_MUSEUM_CLOSED_ON_DATE", "Museum is closed on the pass's visit date")
    # (15) visit-day temporal rule: the pass admits only on its visit date and
    # only while the current slot is within entry_quarter_hour + 2. Any failure
    # of this comparison flips the pass to EXPIRED (lazy expiry).
    slot = db.current_slot_index()
    if p["visit_date"] != db.today_str() or slot > p["entry_quarter_hour"] + constants.ADMIT_GRACE_SLOTS:
        p["status"] = "EXPIRED"
        db.touch(p)
        fail("ERR_PASS_EXPIRED", "The admission grace window has passed for this pass")
    # (16) screening throughput: equality with the rate means full
    admitted_here = sum(
        1
        for q in db.STORE["timed_entry_passes"].values()
        if q["museum_id"] == p["museum_id"]
        and q["visit_date"] == db.today_str()
        and q["status"] == "ADMITTED"
        and q["admitted_slot"] == slot
    )
    if museum is not None and admitted_here >= museum["screening_rate_per_quarter_hour"]:
        fail("ERR_SCREENING_THROUGHPUT_FULL", "Screening throughput for the current slot is full")
    p["status"] = "ADMITTED"
    p["admitted_slot"] = slot
    db.touch(p)
    return success(serializers.timed_entry_pass(p))
