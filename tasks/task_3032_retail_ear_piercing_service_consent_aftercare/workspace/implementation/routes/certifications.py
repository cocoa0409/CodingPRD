"""Certification routes (PRD 3.9)."""

from flask import Blueprint, request

import db
import response as R
from middleware import authenticated, acting_user_id
from services import common
from services import certifications as cert_svc

bp = Blueprint("certifications", __name__)


@bp.route("/certifications", methods=["POST"])
@authenticated("ComplianceOfficer")
def create_certification():
    data = common.body()
    piercer = common.get_piercer(common.require_str(data, "piercer_id"))
    common.check_expected_version(data, "expected_piercer_version", piercer)

    level = common.require_enum(
        data, "certification_level",
        ("APPRENTICE", "STANDARD", "SENIOR", "INSTRUCTOR"))
    protocol_code = common.require_str(data, "sterilization_protocol_code")
    issued_at = common.require_instant(data, "issued_at")
    expires_at = common.require_instant(data, "expires_at")

    record = cert_svc.issue_certification(
        piercer, level, protocol_code, issued_at, expires_at)
    return R.object_response(record, 201)


@bp.route("/certifications", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_certifications():
    limit, offset = common.pagination_params()
    rows = list(db.DB.certifications.values())
    requested = request.args.get("piercer_id")
    if requested:
        rows = [c for c in rows if c.piercer_id == requested]
    rows = common.sorted_rows(rows)
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/certifications/<certification_id>", methods=["GET"])
@authenticated("AnyAuthenticated")
def get_certification(certification_id):
    return R.object_response(common.get_certification(certification_id))


@bp.route("/certifications/<certification_id>/recertify", methods=["POST"])
@authenticated("Piercer")
def recertify(certification_id):
    record = common.get_certification(certification_id)
    data = common.body()
    passed = common.require_bool(data, "practical_assessment_passed")
    cert_svc.recertify(record, acting_user_id(), passed)
    return R.object_response(record)


@bp.route("/certifications/<certification_id>/revoke", methods=["POST"])
@authenticated("ComplianceOfficer")
def revoke(certification_id):
    record = common.get_certification(certification_id)
    data = common.body()
    reason_code = common.require_str(data, "reason_code")
    cert_svc.revoke_certification(record, reason_code)
    return R.object_response(record)