"""Lease units: delivery, service life, turnover returns, remarketing."""
from datetime import timedelta

from flask import Blueprint

import calculations as calc
import clock
import helpers
from helpers import as_enum, as_int, as_str, auth, body, fail, ok, req, require_role, identity_entity
import storage
from storage import STORES, new_record, public, touch

bp = Blueprint("units", __name__)

CONDITION_GRADES = ("A", "B", "C", "D")
READ_ROLES = ("CorporateAdmin", "DistributorManager", "CourseManager")
ACTIVE_PIPELINE = ("ORDERED", "DELIVERED", "IN_SERVICE", "RETURN_REQUESTED")

_TRANSITIONS = {
    ("ORDERED", "DELIVERED"): "DistributorManager",
    ("DELIVERED", "IN_SERVICE"): "CourseManager",
    ("IN_SERVICE", "RETURN_REQUESTED"): "CourseManager",
    ("RETURN_REQUESTED", "RETURNED"): "DistributorManager",
    ("RETURNED", "REMARKET_LISTED"): "DistributorManager",
    ("REMARKET_LISTED", "RESERVED"): "CourseManager",
    ("RESERVED", "SOLD"): "CourseManager",
    ("REMARKET_LISTED", "RETIRED"): "DistributorManager",
}


@bp.get("/units/<uid>")
def get_unit(uid):
    role, caller = auth()
    require_role(role, READ_ROLES)
    u = helpers.get_or_404("units", uid, "unit")
    return ok(public(u))


@bp.get("/units")
def list_units():
    role, caller = auth()
    require_role(role, READ_ROLES)
    recs = helpers.apply_filters(list(STORES["units"].values()), {
        "lease_id": "lease_id",
        "model_id": "model_id",
        "status": "status",
        "reserved_by_course_id": "reserved_by_course_id",
    })
    # Documented exception: units sort by unit_seq ascending.
    recs = sorted(recs, key=lambda r: (r["unit_seq"], r["created_at"], r["_seq"]))
    return helpers.paginate(recs)


def _check_c1_closure(lease):
    """Cascade C1 links 1->2->3: when a return leaves every unit of the lease
    outside the active pipeline states, a TURNOVER_IN_PROGRESS lease closes and
    its course steps from ACTIVE_LEASE back to IN_RENEWAL."""
    if lease["status"] != "TURNOVER_IN_PROGRESS":
        return
    units = [u for u in STORES["units"].values() if u["lease_id"] == lease["id"]]
    if all(u["status"] not in ACTIVE_PIPELINE for u in units):
        lease["status"] = "CLOSED"
        touch(lease)
        course = STORES["courses"][lease["course_id"]]
        if course["status"] == "ACTIVE_LEASE":
            course["status"] = "IN_RENEWAL"
            touch(course)


@bp.post("/units/<uid>/transition")
def transition_unit(uid):
    role, caller = auth()
    require_role(role, READ_ROLES)
    if role in ("DistributorManager", "CourseManager"):
        identity_entity(role, caller)
    u = helpers.get_or_404("units", uid, "unit")
    lease = STORES["leases"][u["lease_id"]]
    # Fixed owner FK for distributor actions (priority 3).
    if role == "DistributorManager" and lease["distributor_id"] != caller:
        fail("ERR_FORBIDDEN_OWNERSHIP", "unit's lease belongs to another distributor")
    b = body()
    to = as_str(req(b, "to"), "to")
    serial = None
    hours_used = None
    grade = None
    if to == "DELIVERED":
        serial = as_str(req(b, "serial_number"), "serial_number")
    elif to == "RETURNED":
        hours_used = as_int(req(b, "hours_used"), "hours_used")
        if hours_used < 0:
            fail("ERR_INVALID_REQUEST", "hours_used must be >= 0")
        grade = as_enum(req(b, "condition_grade"), "condition_grade", CONDITION_GRADES)
    key = (u["status"], to)
    if key not in _TRANSITIONS:
        fail("ERR_INVALID_STATE", "unit cannot move from " + u["status"] + " to " + str(to))
    if role != _TRANSITIONS[key]:
        fail("ERR_UNAUTHORIZED", "role " + role + " may not drive unit to " + to)
    # Course-side ownership varies per transition (PRD 2.1 priority 3).
    if role == "CourseManager" and to in ("IN_SERVICE", "RETURN_REQUESTED"):
        if lease["course_id"] != caller:
            fail("ERR_FORBIDDEN_OWNERSHIP", "unit's lease belongs to another course")
    if role == "CourseManager" and to == "SOLD":
        if u["reserved_by_course_id"] != caller:
            fail("ERR_FORBIDDEN_OWNERSHIP", "unit is reserved by another course")

    if key == ("ORDERED", "DELIVERED"):
        if lease["status"] not in ("APPROVED", "ACTIVE"):
            fail("ERR_INVALID_STATE", "owning lease is not APPROVED or ACTIVE")
        for other in STORES["units"].values():
            if (other["id"] != u["id"] and other["model_id"] == u["model_id"]
                    and other["serial_number"] is not None and other["serial_number"] == serial):
                fail("ERR_DUPLICATE_SERIAL", "serial_number already used for this model")
        u["serial_number"] = serial
        u["delivered_at"] = clock.stamp()

    elif key == ("RETURN_REQUESTED", "RETURNED"):
        u["hours_used"] = hours_used
        u["condition_grade"] = grade
        u["returned_at"] = clock.stamp()

    elif key == ("RETURNED", "REMARKET_LISTED"):
        model = STORES["models"][u["model_id"]]
        ask, floor = calc.remarketing_listing(model, u["condition_grade"])
        u["asking_price_cents"] = ask
        u["floor_price_cents"] = floor

    elif key == ("REMARKET_LISTED", "RESERVED"):
        u["reserved_by_course_id"] = caller
        expires = clock.now() + timedelta(days=calc.RESERVATION_HOLD_DAYS)
        u["_res_expires_dt"] = expires
        u["reservation_expires_at"] = expires.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (expires.microsecond // 1000)

    elif key == ("RESERVED", "SOLD"):
        u["sale_price_cents"] = u["asking_price_cents"]

    u["status"] = to
    touch(u)
    if key == ("RETURN_REQUESTED", "RETURNED"):
        _check_c1_closure(lease)
    return ok(public(u))
