"""IRBProtocol endpoints: create, list, submit, decision, continuing-review."""
from datetime import timedelta

from flask import Blueprint

import store
from calc import IRB_MAX_APPROVAL_DAYS, MAX_TOTAL_BURDEN_MINUTES
from clock import parse_iso
from errors import raise_err
from serialize import irb_out
from services import protocols_of_study
from util import new_entity, ok_list, ok_obj, paginate, sort_created, touch
from validation import (ROLE_IRB_REVIEWER, ROLE_PRINCIPAL_INVESTIGATOR,
                        STAFF_ROLES, authenticate, authorize, check_schema,
                        get_json_body)

bp = Blueprint("irb", __name__)


def get_protocol_or_404(irb_id):
    proto = store.irb_protocols.get(irb_id)
    if proto is None:
        raise_err("ERR_NOT_FOUND", "IRB protocol not found")
    return proto


@bp.post("/evaluation/studies/<study_id>/irb-protocols")
def create_irb_protocol(study_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_PRINCIPAL_INVESTIGATOR])
    study = store.studies.get(study_id)
    if study is None:
        raise_err("ERR_NOT_FOUND", "Study not found")
    body = get_json_body()
    check_schema(body, {
        "title": ("str", True),
        "estimated_burden_minutes": ("int", True),
    })
    burden = body["estimated_burden_minutes"]
    if not 0 <= burden <= MAX_TOTAL_BURDEN_MINUTES:
        raise_err("ERR_INVALID_REQUEST",
                  "estimated_burden_minutes must be between 0 and %d"
                  % MAX_TOTAL_BURDEN_MINUTES)
    if study["status"] in ("TERMINATED", "COMPLETED"):
        raise_err("ERR_STUDY_INVALID_STATE",
                  "A terminated or completed study accepts no new protocols")
    proto = new_entity({
        "study_id": study_id,
        "title": body["title"],
        "estimated_burden_minutes": burden,
        "status": "DRAFT",
        "approval_start": None,
        "approval_end": None,
        "consent_form_version": 1,
        "submitted_by_id": None,
        "decided_by_id": None,
        "_mods_pending": False,
    })
    store.irb_protocols[proto["id"]] = proto
    return ok_obj(irb_out(proto), 201)


@bp.get("/evaluation/studies/<study_id>/irb-protocols")
def list_irb_protocols(study_id):
    _uid, role = authenticate()
    authorize(role, STAFF_ROLES)
    if study_id not in store.studies:
        raise_err("ERR_NOT_FOUND", "Study not found")
    items = sort_created(protocols_of_study(study_id))
    page, limit, offset, total = paginate(items)
    return ok_list([irb_out(p) for p in page], limit, offset, total)


@bp.post("/evaluation/irb-protocols/<irb_id>/submit")
def submit_irb_protocol(irb_id):
    uid, role = authenticate()
    authorize(role, [ROLE_PRINCIPAL_INVESTIGATOR])
    proto = get_protocol_or_404(irb_id)
    body = get_json_body()
    check_schema(body, {})
    if proto["status"] not in ("DRAFT", "MODIFICATIONS_REQUIRED", "EXPIRED"):
        raise_err("ERR_IRB_INVALID_STATE",
                  "Only a DRAFT, MODIFICATIONS_REQUIRED, or EXPIRED protocol "
                  "can be submitted")
    proto["status"] = "SUBMITTED"
    proto["submitted_by_id"] = uid
    touch(proto)
    return ok_obj(irb_out(proto))


@bp.post("/evaluation/irb-protocols/<irb_id>/decision")
def irb_decision(irb_id):
    uid, role = authenticate()
    authorize(role, [ROLE_IRB_REVIEWER])
    proto = get_protocol_or_404(irb_id)
    body = get_json_body()
    check_schema(body, {
        "decision": ("enum:APPROVED|MODIFICATIONS_REQUIRED", True),
        "approval_start": ("dt", False),
        "approval_end": ("dt", False),
    })
    start_dt = None
    end_dt = None
    if body["decision"] == "APPROVED":
        if body.get("approval_start") is None or body.get("approval_end") is None:
            raise_err("ERR_INVALID_REQUEST",
                      "approval_start and approval_end are required for an "
                      "APPROVED decision")
        start_dt = parse_iso(body["approval_start"])
        end_dt = parse_iso(body["approval_end"])
        if not end_dt > start_dt:
            raise_err("ERR_INVALID_REQUEST",
                      "approval_end must be after approval_start")
        if (end_dt - start_dt) > timedelta(days=IRB_MAX_APPROVAL_DAYS):
            raise_err("ERR_INVALID_REQUEST",
                      "Approval window must not exceed %d days"
                      % IRB_MAX_APPROVAL_DAYS)
    if proto["status"] != "SUBMITTED":
        raise_err("ERR_IRB_INVALID_STATE",
                  "Only a SUBMITTED protocol can receive a decision")
    if uid == proto["submitted_by_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "The deciding reviewer must differ from the submitter")
    if body["decision"] == "APPROVED":
        for other in protocols_of_study(proto["study_id"]):
            if other["id"] == proto["id"] or other["status"] != "APPROVED":
                continue
            # Half-open windows; touching endpoints (start == other end) pass.
            if start_dt < other["approval_end"] and \
                    other["approval_start"] < end_dt:
                raise_err("ERR_IRB_WINDOW_OVERLAP",
                          "Approval window overlaps another APPROVED protocol "
                          "window of this study")
        proto["approval_start"] = start_dt
        proto["approval_end"] = end_dt
        proto["status"] = "APPROVED"
        proto["decided_by_id"] = uid
        if proto["_mods_pending"]:
            proto["consent_form_version"] += 1
            proto["_mods_pending"] = False
    else:
        proto["status"] = "MODIFICATIONS_REQUIRED"
        proto["decided_by_id"] = uid
        proto["_mods_pending"] = True
    touch(proto)
    return ok_obj(irb_out(proto))


@bp.post("/evaluation/irb-protocols/<irb_id>/continuing-review")
def irb_continuing_review(irb_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_IRB_REVIEWER])
    proto = get_protocol_or_404(irb_id)
    body = get_json_body()
    check_schema(body, {"new_approval_end": ("dt", True)})
    new_end = parse_iso(body["new_approval_end"])
    if proto["status"] != "APPROVED":
        raise_err("ERR_IRB_INVALID_STATE",
                  "Only an APPROVED protocol can receive continuing review")
    if not new_end > proto["approval_end"]:
        raise_err("ERR_INVALID_REQUEST",
                  "new_approval_end must be strictly later than the current "
                  "approval_end")
    if new_end > proto["approval_start"] + timedelta(days=IRB_MAX_APPROVAL_DAYS):
        raise_err("ERR_INVALID_REQUEST",
                  "new_approval_end must be no later than %d days after the "
                  "original approval_start" % IRB_MAX_APPROVAL_DAYS)
    proto["approval_end"] = new_end
    touch(proto)
    return ok_obj(irb_out(proto))
