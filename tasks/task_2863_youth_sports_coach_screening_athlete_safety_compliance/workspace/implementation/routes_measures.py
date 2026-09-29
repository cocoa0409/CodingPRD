"""Interim measures: reads, the lift compensation and permanent conversion."""

from flask import Blueprint, g, request

import auth
import clock
import derive
import envelope
import ops
import pagelib
import serialize
import store
import validate
from errors import fail

bp = Blueprint("measures", __name__)

MEASURE_STATUSES = ("ACTIVE", "LIFTED", "PERMANENT")


@bp.get("/interim-measures")
@auth.endpoint("NgbAdmin", "SafeSportOfficer", "ComplianceAuditor", "ClubAdministrator")
def list_measures():
    args = request.args
    validate.query_enum(args, "status", MEASURE_STATUSES)
    rows = [m for m in store.INTERIM_MEASURES.values()
            if pagelib.match(m, args, "case_id")
            and pagelib.match(m, args, "member_id")
            and pagelib.match(m, args, "status")]
    return pagelib.page(store.ordered(rows), serialize.interim_measure, args)


@bp.get("/interim-measures/<interim_measure_id>")
@auth.endpoint("NgbAdmin", "SafeSportOfficer", "ComplianceAuditor", "ClubAdministrator")
def read_measure(interim_measure_id):
    row = auth.interim_measure(interim_measure_id)
    auth.scope_measure(row)
    return envelope.ok(serialize.interim_measure(row))


@bp.post("/interim-measures/<interim_measure_id>/lift")
@auth.endpoint("SafeSportOfficer")
def lift_measure(interim_measure_id):
    row = auth.interim_measure(interim_measure_id)
    data = validate.body(auth.payload(), {"reason": validate.string(min_len=1, max_len=1000)})
    case = store.CASES.get(row["case_id"])
    member = store.MEMBERS[row["member_id"]]
    if row["status"] != "ACTIVE":
        fail("ERR_INTERIM_MEASURE_INVALID_STATE", "only an ACTIVE measure may be lifted")
    if case is None or case["status"] not in ("INTAKE_REVIEW", "ROUTED"):
        fail("ERR_CASE_INVALID_STATE", "the case is closed")

    row["status"] = "LIFTED"
    row["lifted_at"] = clock.now()
    row["lift_reason"] = data["reason"]
    store.bump(row)
    ops.restore_after_release(member)
    store.bump(member)
    derive.recompute_all()
    return envelope.ok(serialize.interim_measure(row))


@bp.post("/interim-measures/<interim_measure_id>/convert-permanent")
@auth.endpoint("SafeSportOfficer")
def convert_measure(interim_measure_id):
    row = auth.interim_measure(interim_measure_id)
    data = validate.body(auth.payload(), {"rationale": validate.string(min_len=1, max_len=4000)})
    case = store.CASES.get(row["case_id"])
    member = store.MEMBERS[row["member_id"]]
    if row["status"] != "ACTIVE":
        fail("ERR_INTERIM_MEASURE_INVALID_STATE", "only an ACTIVE measure may be converted")
    if case is None or case["status"] != "ROUTED":
        fail("ERR_CASE_INVALID_STATE", "the case must be ROUTED to convert a measure")
    if g.user_id == row["imposed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the officer who imposed a measure may not make it permanent")

    row["status"] = "PERMANENT"
    row["permanence"] = "PERMANENT"
    row["converted_by_user_id"] = g.user_id
    row["rationale"] = data["rationale"]
    store.bump(row)
    ops.revoke_member(member, "PERMANENT_MEASURE")
    store.bump(member)
    derive.recompute_all()
    return envelope.ok(serialize.interim_measure(row))
