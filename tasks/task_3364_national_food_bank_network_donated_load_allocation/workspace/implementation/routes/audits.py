"""Member standards audits: creation, completion and the posture cascade."""

from flask import Blueprint

import auth
import envelope
import serializers
import store
from errors import (
    ERR_AUDIT_NOT_FOUND,
    ERR_AUDIT_NOT_IN_PROGRESS,
    ERR_AUDIT_SCORE_OUT_OF_RANGE,
    ERR_MEMBER_NOT_FOUND,
    ERR_MEMBER_SUSPENDED,
    ERR_SEGREGATION_OF_DUTIES,
    fail,
)
from services import audit as audit_svc
from services import members as member_svc

bp = Blueprint("audits", __name__)

AUDIT_TYPES = ("STORAGE", "DISTRIBUTION", "REPORTING", "COMPREHENSIVE")


def _component(data, key):
    value = auth.req_int(data, key)
    if value < 0 or value > 100:
        fail(ERR_AUDIT_SCORE_OUT_OF_RANGE,
             "%s must be an integer between 0 and 100" % key)
    return value


@bp.route("/network/audits", methods=["POST"])
def create_audit():
    user_id, _role = auth.require_roles("NetworkAdmin")
    data = auth.json_body()

    member_id = auth.req_str(data, "member_id")
    audit_type = auth.req_enum(data, "audit_type", AUDIT_TYPES)
    storage_score = _component(data, "storage_score")
    distribution_score = _component(data, "distribution_score")
    reporting_score = _component(data, "reporting_score")

    member = store.members.get(member_id)
    if member is None:
        fail(ERR_MEMBER_NOT_FOUND, "no member food bank matches id %s" % member_id)
    if member["certification_status"] == "SUSPENDED":
        fail(ERR_MEMBER_SUSPENDED, "a suspended member may not be audited")

    weighted = audit_svc.weighted_score(
        member, audit_type, storage_score, distribution_score, reporting_score)

    audit = store.new_record(
        member_id=member["id"],
        audit_type=audit_type,
        storage_score=storage_score,
        distribution_score=distribution_score,
        reporting_score=reporting_score,
        weighted_score=weighted,
        opened_by_user_id=user_id,
        audit_status="IN_PROGRESS",
    )
    store.insert("audits", audit)
    return envelope.ok_object(serializers.audit(audit), 201)


@bp.route("/network/audits/<audit_id>/complete", methods=["POST"])
def complete_audit(audit_id):
    user_id, _role = auth.require_roles("NetworkAuditor")
    audit = store.audits.get(audit_id)
    if audit is None:
        fail(ERR_AUDIT_NOT_FOUND, "no member audit matches id %s" % audit_id)
    if audit["opened_by_user_id"] == user_id:
        fail(ERR_SEGREGATION_OF_DUTIES,
             "the operator completing an audit must differ from the operator who opened it")
    if audit["audit_status"] != "IN_PROGRESS":
        fail(ERR_AUDIT_NOT_IN_PROGRESS, "the audit is not IN_PROGRESS")

    member = store.members.get(audit["member_id"])
    weighted = audit_svc.weighted_score(
        member, audit["audit_type"], audit["storage_score"],
        audit["distribution_score"], audit["reporting_score"])
    audit["weighted_score"] = weighted
    passed = audit_svc.passes(weighted)
    audit["audit_status"] = "PASSED" if passed else "FAILED"
    store.touch(audit)

    member["audit_score"] = audit_svc.floor_score(weighted)
    status = member["certification_status"]
    if not passed and status == "CERTIFIED":
        member_svc.set_posture(member, "PROBATION")
    elif not passed and status == "PROBATION":
        member_svc.set_posture(member, "SUSPENDED")
    else:
        store.touch(member)

    return envelope.ok_object(serializers.audit(audit))
