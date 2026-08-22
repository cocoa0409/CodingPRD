"""Complaint intake, triage and adjudication (PRD section 3.8)."""
from flask import Blueprint, request

import db
from body import Body
from errors import invalid_state, raise_err
from gates import (P_BODY, P_BODY_FK, P_BOOKING_PERMIT_MISMATCH,
                   P_COMPLAINT_RESOLVED, P_PATH, P_SOD_ADJUDICATE, P_STATE,
                   resolve, resolve_body_fk, run_gates)
from listing import listing
from middleware import PERMIT_OFFICER, RESIDENT, require_roles
from response import ok_object
from services import calc, domain
from services.serializers import serialize
from utils import new_entity, touch

bp = Blueprint("complaints", __name__, url_prefix="/busking")

CATEGORIES = {"NOISE", "OBSTRUCTION", "CONDUCT", "UNPERMITTED_AMPLIFICATION"}
SEVERITIES = {"MINOR", "MODERATE", "MAJOR"}
ROUTES = {"DIRECT", "MEDIATION"}
OUTCOMES = {"UPHELD", "DISMISSED"}
RESOLVED = ("UPHELD", "DISMISSED")


@bp.post("/complaints")
def create_complaint():
    require_roles([RESIDENT, PERMIT_OFFICER])
    raw = request.get_json(silent=True) or {}
    body = Body(raw)
    ctx = {}

    def check_fks():
        # Input-list order: permit_id, category, description, booking_id.
        ctx["permit"] = resolve_body_fk("permits", raw, "permit_id")
        ctx["booking"] = resolve_body_fk("bookings", raw, "booking_id")

    def check_body():
        ctx["fields"] = {
            "permit_id": body.req_id("permit_id"),
            "booking_id": body.opt_id("booking_id"),
            "category": body.req_enum("category", CATEGORIES),
            "description": body.req_str("description"),
            "route": None,
            "severity": None,
            "status": "OPEN",
            "triaged_by_user_id": None,
            "adjudicated_by_user_id": None,
            "upheld_at": None,
            "conduct_deduction": 0,
        }

    def check_booking_permit():
        if ctx["booking"] is not None and ctx["booking"]["permit_id"] != ctx["permit"]["id"]:
            raise_err("ERR_BOOKING_PERMIT_MISMATCH",
                      "The named session belongs to a different permit")

    run_gates([
        (P_BODY_FK, check_fks),
        (P_BODY, check_body),
        (P_BOOKING_PERMIT_MISMATCH, check_booking_permit),
    ])
    return ok_object(serialize(new_entity("complaints", ctx["fields"])), status=201)


@bp.get("/complaints/<complaint_id>")
def read_complaint(complaint_id):
    require_roles([PERMIT_OFFICER])
    ctx = {}
    run_gates([(P_PATH, lambda: ctx.update(complaint=resolve("complaints", complaint_id)))])
    return ok_object(serialize(ctx["complaint"]))


@bp.get("/complaints")
def list_complaints():
    require_roles([PERMIT_OFFICER])
    return listing("complaints", ["permit_id", "booking_id", "status", "severity"],
                   request.args)


@bp.post("/complaints/<complaint_id>/triage")
def triage_complaint(complaint_id):
    user_id, _role = require_roles([PERMIT_OFFICER])
    body = Body(request.get_json(silent=True))
    ctx = {}

    def check_body():
        ctx["severity"] = body.req_enum("severity", SEVERITIES)
        ctx["route"] = body.req_enum("route", ROUTES)

    def check_resolved():
        if ctx["complaint"]["status"] in RESOLVED:
            raise_err("ERR_COMPLAINT_ALREADY_RESOLVED", "This complaint is already resolved")

    def check_state():
        if ctx["complaint"]["status"] != "OPEN":
            invalid_state("Only an OPEN complaint can be triaged")

    run_gates([
        (P_PATH, lambda: ctx.update(complaint=resolve("complaints", complaint_id))),
        (P_BODY, check_body),
        (P_COMPLAINT_RESOLVED, check_resolved),
        (P_STATE, check_state),
    ])

    complaint = ctx["complaint"]
    complaint["severity"] = ctx["severity"]
    complaint["route"] = ctx["route"]
    complaint["status"] = "TRIAGED" if ctx["route"] == "DIRECT" else "MEDIATION"
    complaint["triaged_by_user_id"] = user_id
    touch(complaint)
    return ok_object(serialize(complaint))


@bp.post("/complaints/<complaint_id>/adjudicate")
def adjudicate_complaint(complaint_id):
    user_id, _role = require_roles([PERMIT_OFFICER])
    body = Body(request.get_json(silent=True))
    ctx = {}

    def check_body():
        ctx["outcome"] = body.req_enum("outcome", OUTCOMES)
        ctx["note"] = body.opt_str("resolution_note")

    def check_resolved():
        if ctx["complaint"]["status"] in RESOLVED:
            raise_err("ERR_COMPLAINT_ALREADY_RESOLVED", "This complaint is already resolved")

    def check_state():
        if ctx["complaint"]["status"] not in ("TRIAGED", "MEDIATION"):
            invalid_state("Only a triaged complaint can be adjudicated")

    def check_segregation():
        if ctx["complaint"]["triaged_by_user_id"] == user_id:
            raise_err("ERR_SEGREGATION_OF_DUTIES",
                      "The triaging officer may not adjudicate this complaint")

    run_gates([
        (P_PATH, lambda: ctx.update(complaint=resolve("complaints", complaint_id))),
        (P_BODY, check_body),
        (P_COMPLAINT_RESOLVED, check_resolved),
        (P_STATE, check_state),
        (P_SOD_ADJUDICATE, check_segregation),
    ])

    complaint = ctx["complaint"]
    complaint["adjudicated_by_user_id"] = user_id
    if ctx["outcome"] == "DISMISSED":
        complaint["status"] = "DISMISSED"
        touch(complaint)
        return ok_object(serialize(complaint))

    complaint["conduct_deduction"] = calc.upheld_deduction(
        complaint["severity"], complaint["route"])
    complaint["upheld_at"] = db.now()
    complaint["status"] = "UPHELD"
    touch(complaint)

    permit = db.get("permits", complaint["permit_id"])
    performer = domain.performer_of(permit) if permit else None
    if performer is not None:
        domain.rescore_performer(performer)
    return ok_object(serialize(complaint))
