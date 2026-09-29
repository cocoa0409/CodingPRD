"""Registration endpoints and the exemption analysis (PRD 3.5)."""
from flask import Blueprint

import calc
import store
import validation as v
from auth import (OFFICER, PRO_ADMIN, REGULATOR, VERIFIER, endpoint, must,
                  new_row, require_producer_owner, touch)
from envelope import ok_entity, ok_list
from errors import fail
from routes.common import enum_filter, listing, str_filter

bp = Blueprint("registrations", __name__)

BLOCKING_REGISTRATION_STATUSES = ("DRAFT", "SUBMITTED", "ACTIVE", "SUSPENDED")
TERMINABLE_MEMBERSHIPS = ("PENDING", "ACTIVE", "PROBATION")


def terminate_memberships(registration, reason):
    for membership in calc.memberships_of(registration["id"]):
        if membership["status"] in TERMINABLE_MEMBERSHIPS:
            membership["status"] = "TERMINATED"
            membership["decision_reason"] = reason
            touch(membership)


@bp.post("/epr/registrations")
@endpoint([OFFICER])
def create_registration():
    body = v.body()
    producer_id = v.req_str(body, "producer_id")
    program_id = v.req_str(body, "state_program_id")
    producer = must("producers", producer_id)
    program = must("state_programs", program_id)
    require_producer_owner(producer_id)
    if producer["status"] != "OBLIGATION_DETERMINED":
        fail("ERR_OBLIGATION_NOT_DETERMINED")
    for existing in store.values("registrations"):
        if (
            existing["producer_id"] == producer_id
            and existing["state_program_id"] == program["id"]
            and existing["status"] in BLOCKING_REGISTRATION_STATUSES
        ):
            fail("ERR_DUPLICATE_REGISTRATION")
    row = new_row(
        "registrations",
        {
            "producer_id": producer_id,
            "state_program_id": program["id"],
            "status": "DRAFT",
            "exemption_status": "UNDETERMINED",
            "exemption_basis_applied": "NONE",
            "assessed_group_revenue_usd": 0,
            "assessed_group_weight_kg": calc.ZERO_KG,
            "reported_weight_kg_ytd": calc.ZERO_KG,
            "compliance_posture": "UNDETERMINED",
            "suspension_reason": None,
            "submitted_at": None,
        },
    )
    return ok_entity(row, 201)


@bp.get("/epr/registrations/<rid>")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN, VERIFIER])
def get_registration(rid):
    return ok_entity(must("registrations", rid))


@bp.get("/epr/registrations")
@endpoint([REGULATOR, OFFICER, PRO_ADMIN, VERIFIER])
def list_registrations():
    producer_id = str_filter("producer_id")
    program_id = str_filter("state_program_id")
    status = enum_filter("status", v.REGISTRATION_STATUSES)
    exemption = enum_filter("exemption_status", v.EXEMPTION_STATUSES)
    posture = enum_filter("compliance_posture", v.COMPLIANCE_POSTURES)
    rows = store.values("registrations")
    if producer_id is not None:
        rows = [r for r in rows if r["producer_id"] == producer_id]
    if program_id is not None:
        rows = [r for r in rows if r["state_program_id"] == program_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if exemption is not None:
        rows = [r for r in rows if r["exemption_status"] == exemption]
    if posture is not None:
        rows = [r for r in rows if r["compliance_posture"] == posture]
    window, limit, offset, total = listing(rows)
    return ok_list(window, limit, offset, total)


@bp.post("/epr/registrations/<rid>/submit")
@endpoint([OFFICER])
def submit_registration(rid):
    registration = must("registrations", rid)
    require_producer_owner(registration["producer_id"])
    if registration["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "The registration is not in DRAFT.")
    producer = store.get("producers", registration["producer_id"])
    program = store.get("state_programs", registration["state_program_id"])
    if producer["status"] != "OBLIGATION_DETERMINED":
        fail("ERR_OBLIGATION_NOT_DETERMINED")
    if producer["determination_stale"]:
        fail("ERR_DETERMINATION_STALE")
    if producer["obligated_party_role"] == "NOT_OBLIGATED":
        fail("ERR_PRODUCER_NOT_OBLIGATED")
    if store.clock() > program["_registration_deadline"]:
        fail("ERR_REGISTRATION_DEADLINE_PASSED")
    registration["status"] = "SUBMITTED"
    calc.run_exemption(registration, producer, program)
    registration["submitted_at"] = store.fmt_instant(store.clock())
    touch(registration)
    calc.set_posture(registration)
    return ok_entity(registration)


@bp.post("/epr/registrations/<rid>/decide")
@endpoint([REGULATOR])
def decide_registration(rid):
    body = v.body()
    decision = v.req_enum(body, "decision", ["ACCEPT", "REJECT"])
    reason = v.opt_str(body, "reason", allow_empty=False)
    if decision == "REJECT" and reason is None:
        fail("ERR_INVALID_REQUEST", "Field 'reason' is required for a rejection.")
    registration = must("registrations", rid)
    if registration["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "The registration is not in SUBMITTED.")
    if decision == "ACCEPT":
        registration["status"] = "ACTIVE"
        touch(registration)
        calc.set_posture(registration)
    else:
        registration["status"] = "REJECTED"
        touch(registration)
        calc.set_posture(registration)
        terminate_memberships(registration, "REGISTRATION_REJECTED")
    return ok_entity(registration)


@bp.post("/epr/registrations/<rid>/suspend")
@endpoint([REGULATOR])
def suspend_registration(rid):
    body = v.body()
    reason = v.req_str(body, "suspension_reason")
    registration = must("registrations", rid)
    if registration["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "The registration is not ACTIVE.")
    registration["status"] = "SUSPENDED"
    registration["suspension_reason"] = reason
    touch(registration)
    for report in calc.reports_of(registration["id"]):
        if report["submission_status"] == "DRAFT":
            report["submission_status"] = "BLOCKED"
            touch(report)
    calc.set_posture(registration)
    return ok_entity(registration)


@bp.post("/epr/registrations/<rid>/reinstate")
@endpoint([REGULATOR])
def reinstate_registration(rid):
    registration = must("registrations", rid)
    if registration["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", "The registration is not SUSPENDED.")
    producer = store.get("producers", registration["producer_id"])
    if producer["status"] != "OBLIGATION_DETERMINED" or producer["determination_stale"]:
        fail("ERR_DETERMINATION_STALE")
    registration["status"] = "ACTIVE"
    registration["suspension_reason"] = None
    touch(registration)
    for report in calc.reports_of(registration["id"]):
        if report["submission_status"] == "BLOCKED":
            report["submission_status"] = "DRAFT"
            touch(report)
    calc.set_posture(registration)
    return ok_entity(registration)


@bp.post("/epr/registrations/<rid>/withdraw")
@endpoint([OFFICER])
def withdraw_registration(rid):
    body = v.body()
    v.req_str(body, "reason")
    registration = must("registrations", rid)
    require_producer_owner(registration["producer_id"])
    if registration["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "The registration is not ACTIVE.")
    for report in calc.reports_of(registration["id"]):
        if report["submission_status"] in (
            "DRAFT",
            "SUBMITTED",
            "UNDER_VERIFICATION",
            "CORRECTION_REQUIRED",
        ):
            fail("ERR_REGISTRATION_HAS_OPEN_REPORTS")
    registration["status"] = "WITHDRAWN"
    touch(registration)
    calc.set_posture(registration)
    terminate_memberships(registration, "REGISTRATION_WITHDRAWN")
    return ok_entity(registration)
