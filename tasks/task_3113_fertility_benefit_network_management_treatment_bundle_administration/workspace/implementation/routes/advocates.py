"""Care advocates (PRD 3.2)."""

from flask import request

from body import body, require, require_int, require_dt
from bp import api
from db import db
from errors import APIError
from helpers import recompute_advocate
from listing import apply_filters, ordered, paginate
from lookups import care_advocate
from middleware import resolve_actor
from response import ok, created
from serializers import serialize


@api.route("/care-advocates", methods=["POST"])
def create_care_advocate():
    resolve_actor()
    data = body()
    full_name = require(data, "full_name")
    states_licensed = require(data, "states_licensed")
    specializations = require(data, "specializations")
    caseload_limit = require_int(data, "caseload_limit")
    credentials_expire_on = require_dt(data, "credentials_expire_on")

    if not isinstance(states_licensed, list) or not isinstance(specializations, list):
        raise APIError("ERR_INVALID_REQUEST", "states_licensed and specializations must be arrays.")

    row = db.common()
    row.update({
        "_collection": "care_advocates",
        "full_name": full_name,
        "states_licensed": states_licensed,
        "specializations": specializations,
        "caseload_limit": caseload_limit,
        "credentials_expire_on": credentials_expire_on,
        "current_caseload": 0,
        "assignments_completed": 0,
        "advocate_status": "ACTIVE",
    })
    db.add(row)
    recompute_advocate(db, row)
    return created(serialize("care_advocates", row))


@api.route("/care-advocates/<advocate_id>", methods=["GET"])
def get_care_advocate(advocate_id):
    resolve_actor()
    row = care_advocate(advocate_id)
    # The derived posture is re-read against the current clock on every read.
    recompute_advocate(db, row)
    return ok(serialize("care_advocates", row))


@api.route("/care-advocates", methods=["GET"])
def list_care_advocates():
    resolve_actor()
    # Derive every posture against the current clock before filtering.
    for advocate in db.all("care_advocates"):
        recompute_advocate(db, advocate)
    rows = ordered(db.all("care_advocates"))
    rows = apply_filters(rows, {"advocate_status": "advocate_status"})

    state_code = request.args.get("state_code")
    if state_code is not None:
        rows = [r for r in rows if state_code in (r.get("states_licensed") or [])]
    specialization = request.args.get("specialization")
    if specialization is not None:
        rows = [r for r in rows if specialization in (r.get("specializations") or [])]
    member_id = request.args.get("member_id")
    if member_id is not None:
        # Candidates for that member: licensed in their state, specialised in
        # their required track, and not INACTIVE.
        member = db.find("members", member_id)
        if member is None:
            rows = []
        else:
            rows = [
                r for r in rows
                if member["state_code"] in (r.get("states_licensed") or [])
                and member["required_track"] in (r.get("specializations") or [])
                and r["advocate_status"] in ("ACTIVE", "AT_CAPACITY")
            ]
    return paginate(rows, "care_advocates")