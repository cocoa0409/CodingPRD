"""Membership endpoints (PRD 3.6)."""
from flask import Blueprint

import calc
import store
import validation as v
from auth import (OFFICER, PRO_ADMIN, REGULATOR, endpoint, must, new_row,
                  require_producer_owner, require_pro_owner, touch)
from envelope import ok_entity, ok_list
from errors import fail
from routes.common import enum_filter, listing, str_filter

bp = Blueprint("memberships", __name__)


@bp.post("/epr/memberships")
@endpoint([OFFICER])
def create_membership():
    body = v.body()
    registration_id = v.req_str(body, "registration_id")
    pro_id = v.req_str(body, "pro_id")
    schedule_id = v.req_str(body, "fee_schedule_id")
    expected = v.req_int(body, "expected_registration_version")
    registration = must("registrations", registration_id)
    pro = must("pros", pro_id)
    schedule = must("fee_schedules", schedule_id)
    require_producer_owner(registration["producer_id"])
    if schedule["status"] != "PUBLISHED":
        fail("ERR_FEE_SCHEDULE_NOT_PUBLISHED")
    if expected != int(registration["version"]):
        fail("ERR_STALE_REGISTRATION_VERSION")
    producer = store.get("producers", registration["producer_id"])
    if producer["determination_stale"]:
        fail("ERR_DETERMINATION_STALE")
    if schedule["pro_id"] != pro["id"]:
        fail("ERR_FEE_SCHEDULE_PRO_MISMATCH")
    if schedule["state_program_id"] != registration["state_program_id"]:
        fail("ERR_FEE_SCHEDULE_PROGRAM_MISMATCH")
    row = new_row(
        "memberships",
        {
            "registration_id": registration["id"],
            "pro_id": pro["id"],
            "fee_schedule_id": schedule["id"],
            "status": "PENDING",
            "membership_fee_cents": 0,
            "fee_payment_status": "OUTSTANDING",
            "fee_schedule_version_pinned": None,
            "decision_reason": None,
        },
    )
    for other in calc.memberships_of(registration["id"]):
        if other["id"] == row["id"]:
            continue
        if other["status"] in ("ACTIVE", "PROBATION"):
            other["status"] = "TERMINATED"
            other["decision_reason"] = "SUPERSEDED_BY_NEW_MEMBERSHIP"
            touch(other)
    touch(registration)
    calc.set_posture(registration)
    return ok_entity(row, 201)


@bp.get("/epr/memberships/<mid>")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN])
def get_membership(mid):
    return ok_entity(must("memberships", mid))


@bp.get("/epr/memberships")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN])
def list_memberships():
    registration_id = str_filter("registration_id")
    pro_id = str_filter("pro_id")
    schedule_id = str_filter("fee_schedule_id")
    status = enum_filter("status", v.MEMBERSHIP_STATUSES)
    payment = enum_filter("fee_payment_status", v.PAYMENT_STATUSES)
    rows = store.values("memberships")
    if registration_id is not None:
        rows = [r for r in rows if r["registration_id"] == registration_id]
    if pro_id is not None:
        rows = [r for r in rows if r["pro_id"] == pro_id]
    if schedule_id is not None:
        rows = [r for r in rows if r["fee_schedule_id"] == schedule_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if payment is not None:
        rows = [r for r in rows if r["fee_payment_status"] == payment]
    window, limit, offset, total = listing(rows)
    return ok_list(window, limit, offset, total)


@bp.post("/epr/memberships/<mid>/decide")
@endpoint([PRO_ADMIN])
def decide_membership(mid):
    body = v.body()
    decision = v.req_enum(body, "decision", ["APPROVE", "REJECT"])
    reason = v.opt_str(body, "reason", allow_empty=False)
    if decision == "REJECT" and reason is None:
        fail("ERR_INVALID_REQUEST", "Field 'reason' is required for a rejection.")
    membership = must("memberships", mid)
    require_pro_owner(membership["pro_id"])
    if membership["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "The membership is not PENDING.")
    registration = store.get("registrations", membership["registration_id"])
    schedule = store.get("fee_schedules", membership["fee_schedule_id"])
    if decision == "APPROVE":
        if schedule["status"] != "PUBLISHED":
            fail("ERR_FEE_SCHEDULE_NOT_PUBLISHED")
        if registration["status"] not in ("SUBMITTED", "ACTIVE"):
            fail("ERR_INVALID_STATE", "The registration cannot take on a membership.")
        producer = store.get("producers", registration["producer_id"])
        membership["status"] = "ACTIVE"
        membership["membership_fee_cents"] = calc.membership_fee(producer, schedule)
        membership["fee_payment_status"] = "OUTSTANDING"
        membership["fee_schedule_version_pinned"] = int(schedule["version"])
    else:
        membership["status"] = "REJECTED"
        membership["decision_reason"] = reason
    touch(membership)
    touch(registration)
    calc.set_posture(registration)
    return ok_entity(membership)


@bp.post("/epr/memberships/<mid>/record-fee-payment")
@endpoint([PRO_ADMIN])
def record_fee_payment(mid):
    body = v.body()
    amount = v.req_int(body, "amount_cents", minimum=0)
    membership = must("memberships", mid)
    require_pro_owner(membership["pro_id"])
    if membership["status"] not in ("ACTIVE", "PROBATION"):
        fail("ERR_MEMBERSHIP_NOT_ACTIVE")
    if amount != int(membership["membership_fee_cents"]):
        fail("ERR_MEMBERSHIP_FEE_AMOUNT_MISMATCH")
    membership["fee_payment_status"] = "PAID"
    touch(membership)
    return ok_entity(membership)
