"""Incentive program and stipend endpoints (PRD 3.8)."""
from flask import Blueprint, request

import constants as C
import domain
import errors as E
import serializers as ser
from response import ok, ok_list
from routes_certifications import _get_certification_or_404
from store import DB, new_id, stamp_new, touch
from validation import (auth_headers, require_role, body, req_field,
                        as_number, as_int, parse_dt_field, pagination_params,
                        paginate)

bp = Blueprint("incentives", __name__)


@bp.post("/incentive-programs")
def create_program():
    _, role = auth_headers()
    require_role(role, [C.ROLE_INCENTIVE_ADMIN])
    data = body()
    name = req_field(data, "name")
    sponsor_state = req_field(data, "sponsor_state")
    sponsor_district_code = data.get("sponsor_district_code")
    budget_total = as_int(req_field(data, "budget_total_cents"),
                          "budget_total_cents")
    if budget_total < 0:
        E.fail(E.ERR_INVALID_REQUEST, 400,
               "budget_total_cents must be at least 0")
    base_stipend = as_int(req_field(data, "base_stipend_cents"),
                          "base_stipend_cents")
    multiplier = as_number(data.get("early_bird_multiplier",
                                    C.DEFAULT_EARLY_BIRD_MULTIPLIER),
                           "early_bird_multiplier")
    deadline = data.get("early_bird_deadline")
    if deadline is not None:
        deadline = parse_dt_field(deadline, "early_bird_deadline")
    program = {
        "id": new_id(),
        "name": name,
        "sponsor_state": sponsor_state,
        "sponsor_district_code": sponsor_district_code,
        "budget_total_cents": budget_total,
        "base_stipend_cents": base_stipend,
        "early_bird_multiplier": multiplier,
        "early_bird_deadline": deadline,
    }
    stamp_new(program)
    DB.programs[program["id"]] = program
    return ok(ser.program(program), 201)


@bp.get("/incentive-programs/<program_id>")
def get_program(program_id):
    _, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE, C.ROLE_SCORING_ADMIN,
                        C.ROLE_BOARD_ADMIN, C.ROLE_INCENTIVE_ADMIN])
    program = DB.programs.get(program_id)
    if program is None:
        E.fail(E.ERR_PROGRAM_NOT_FOUND, 404,
               "Program not found: %s" % program_id)
    return ok(ser.program(program))


@bp.get("/incentive-programs/<program_id>/stipends")
def list_program_stipends(program_id):
    _, role = auth_headers()
    require_role(role, [C.ROLE_INCENTIVE_ADMIN, C.ROLE_BOARD_ADMIN])
    program = DB.programs.get(program_id)
    if program is None:
        E.fail(E.ERR_PROGRAM_NOT_FOUND, 404,
               "Program not found: %s" % program_id)
    limit, offset = pagination_params()
    items = [s for s in DB.stipends.values() if s["program_id"] == program_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, total = paginate(items, limit, offset)
    return ok_list([ser.stipend(s) for s in page], limit, offset, total)


@bp.get("/certifications/<certification_id>/stipends")
def list_certification_stipends(certification_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE, C.ROLE_INCENTIVE_ADMIN,
                        C.ROLE_BOARD_ADMIN])
    cert = _get_certification_or_404(certification_id)
    if role == C.ROLE_CANDIDATE and cert["candidate_id"] != uid:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Candidates may read stipends only for their own certification")
    limit, offset = pagination_params()
    items = [s for s in DB.stipends.values()
             if s["certification_id"] == cert["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, total = paginate(items, limit, offset)
    return ok_list([ser.stipend(s) for s in page], limit, offset, total)


@bp.post("/stipends/<stipend_id>/transition")
def transition_stipend(stipend_id):
    _, role = auth_headers()
    require_role(role, [C.ROLE_INCENTIVE_ADMIN])
    stipend = DB.stipends.get(stipend_id)
    if stipend is None:
        E.fail(E.ERR_STIPEND_NOT_FOUND, 404,
               "Stipend not found: %s" % stipend_id)
    data = body()
    target = req_field(data, "to")
    current = stipend["status"]
    if target == "APPROVED":
        if current != "PROPOSED":
            E.fail(E.ERR_STIPEND_NOT_TRANSITIONABLE, 409,
                   "Stipend in %s cannot be APPROVED" % current)
        remaining = domain.program_remaining(stipend["program_id"])
        if remaining < stipend["amount_cents"]:
            E.fail(E.ERR_PROGRAM_BUDGET_EXHAUSTED, 422,
                   "Program budget_remaining_cents does not cover the stipend")
        # The debit is implicit: budget_remaining_cents is derived from
        # APPROVED/PAID stipends (compensating invariant, PRD 3.8).
        stipend["status"] = "APPROVED"
    elif target == "PAID":
        if current != "APPROVED":
            E.fail(E.ERR_STIPEND_NOT_TRANSITIONABLE, 409,
                   "Stipend in %s cannot be PAID" % current)
        stipend["status"] = "PAID"
    elif target == "REVOKED":
        if current not in ("PROPOSED", "APPROVED"):
            E.fail(E.ERR_STIPEND_NOT_TRANSITIONABLE, 409,
                   "Stipend in %s cannot be REVOKED" % current)
        # PROPOSED never encumbered; revoking APPROVED credits the budget back
        # implicitly through the derived remaining (may reopen EXHAUSTED).
        stipend["status"] = "REVOKED"
    else:
        E.fail(E.ERR_STIPEND_NOT_TRANSITIONABLE, 409,
               "Unknown stipend transition target: %s" % target)
    touch(stipend)
    return ok(ser.stipend(stipend))
