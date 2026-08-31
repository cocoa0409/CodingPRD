"""Member enrolment, reads and the membership state machine (PRD §3.2)."""
from flask import Blueprint

import calc
import serialize
from cascades import (
    member_suspend_cascade, restore_cascade_credentials, revoke_all_credentials,
    suspend_active_credentials,
)
from core import (
    ADMIN, READ_ROLES, authenticate, body, db, end_of_day, fail, is_str, lookup,
    new_common, now, ok, ordered, paginate, parse_date, present, qfilter, touch,
)
from ladder import (
    assert_not_terminal, assert_transition, assert_version, require_action,
    require_str, require_version_field,
)

bp = Blueprint("member", __name__)

MEMBER_TRANSITIONS = {
    "PLACE_ON_PROBATION": ("ACTIVE",),
    "REINSTATE": ("PROBATION", "SUSPENDED"),
    "SUSPEND": ("ACTIVE", "PROBATION"),
    "EXPIRE": ("ACTIVE", "PROBATION"),
    "RENEW": ("EXPIRED",),
    "TERMINATE": ("ACTIVE", "PROBATION", "SUSPENDED", "EXPIRED"),
}
EVENT_TYPES = ("RENEW", "PLACE_ON_PROBATION", "SUSPEND", "REINSTATE", "EXPIRE", "TERMINATE")


@bp.post("/members")
def create_member():
    authenticate([ADMIN])
    payload = body()
    # Rung 4 — body foreign keys, in declared input order.
    association = None
    if present(payload, "association_id"):
        association = lookup("associations", payload["association_id"])
    # Rung 5 — request shape.
    if association is None:
        fail("ERR_INVALID_REQUEST", "association_id is required.")
    require_str(payload, "full_name")
    require_str(payload, "email")
    require_str(payload, "dues_paid_through")
    paid_through = parse_date(payload["dues_paid_through"])
    if paid_through is None:
        fail("ERR_INVALID_REQUEST", "dues_paid_through must be an ISO date (YYYY-MM-DD).")

    rec = new_common()
    rec.update({
        "association_id": association["id"],
        "full_name": payload["full_name"],
        "email": payload["email"],
        "dues_paid_through": payload["dues_paid_through"],
        # PENDING is resolved inside the creating request; version stays 1.
        "membership_status": "ACTIVE" if end_of_day(paid_through) > now() else "EXPIRED",
    })
    db.members[rec["id"]] = rec
    return ok(serialize.member(rec), 201)


@bp.get("/members/<member_id>")
def read_member(member_id):
    authenticate(READ_ROLES)
    return ok(serialize.member(lookup("members", member_id)))


@bp.get("/members")
def list_members():
    authenticate(READ_ROLES)
    rows = ordered(db.members)
    rows = qfilter(rows, "association_id")
    rows = qfilter(rows, "membership_status")
    return paginate(rows, serialize.member)


@bp.post("/members/<member_id>/membership-events")
def membership_event(member_id):
    role = authenticate([ADMIN])[1]
    member = lookup("members", member_id)
    payload = body()

    # Rung 5 — request shape.
    event_type = require_action(payload, EVENT_TYPES, field="event_type")
    expected = require_version_field(payload, "expected_member_version")
    if present(payload, "reason") and not is_str(payload["reason"]):
        fail("ERR_INVALID_REQUEST", "reason must be a string.")
    paid_through = None
    if event_type == "RENEW":
        require_str(payload, "paid_through_date")
        paid_through = parse_date(payload["paid_through_date"])
        if paid_through is None:
            fail("ERR_INVALID_REQUEST", "paid_through_date must be an ISO date (YYYY-MM-DD).")

    # Rung 8 — optimistic concurrency.
    assert_version(expected, member)

    # Rungs 9 and 11 — terminal states admit no declared transition.
    assert_not_terminal("member", member["membership_status"])
    assert_transition(member["membership_status"], MEMBER_TRANSITIONS, event_type)

    if event_type == "TERMINATE":
        holding = any(
            lb.get("assigned_member_id") == member_id
            and lb["status"] in ("ASSIGNED", "PLACED", "MISSING")
            for lb in db.lockboxes.values()
        )
        if holding:
            fail("ERR_INVALID_STATE", "The member still holds association hardware.")
    if event_type == "RENEW" and not (end_of_day(paid_through) > now()):
        fail("ERR_INVALID_REQUEST", "paid_through_date must be later than the current clock.")

    if event_type == "PLACE_ON_PROBATION":
        member["membership_status"] = "PROBATION"
    elif event_type == "REINSTATE":
        was_suspended = member["membership_status"] == "SUSPENDED"
        member["membership_status"] = "ACTIVE"
        if was_suspended:
            restore_cascade_credentials(member_id)
    elif event_type == "SUSPEND":
        member["membership_status"] = "SUSPENDED"
        member_suspend_cascade(member)
    elif event_type == "EXPIRE":
        member["membership_status"] = "EXPIRED"
        suspend_active_credentials(member_id)
    elif event_type == "RENEW":
        member["dues_paid_through"] = payload["paid_through_date"]
        member["membership_status"] = "ACTIVE"
        restore_cascade_credentials(member_id)
    elif event_type == "TERMINATE":
        member["membership_status"] = "TERMINATED"
        revoke_all_credentials(member_id)

    touch(member)
    return ok(serialize.member(member))
