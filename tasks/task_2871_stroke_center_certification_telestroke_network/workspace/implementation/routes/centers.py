"""Stroke facility registry (PRD 3.1)."""
from flask import Blueprint

import db
import response as resp
from constants import CERTIFICATION_STATUSES, EMS_POSTURES, FACILITY_TYPES, READINESS_COMPONENTS, READINESS_RESULTS
from errors import fail
from middleware import (
    Field,
    STATE_CODE_PATTERN,
    apply_filters,
    authenticate,
    load_path,
    pagination,
    read_body,
)
from services import derive

bp = Blueprint("centers", __name__)

CREATE_SPEC = [
    Field("name", "str", min_len=1, max_len=120),
    Field("facility_type", "str", enum=FACILITY_TYPES),
    Field("state_code", "str", pattern=STATE_CODE_PATTERN),
    Field("ems_region_code", "str", min_len=1, max_len=16),
]

PATCH_SPEC = [
    Field("name", "str", required=False, min_len=1, max_len=120),
    Field("ems_region_code", "str", required=False, min_len=1, max_len=16),
]

ATTESTATION_SPEC = [
    Field("component", "str", enum=READINESS_COMPONENTS),
    Field("result", "str", enum=READINESS_RESULTS),
    Field("note", "str", required=False),
]

SUSPEND_SPEC = [Field("suspension_reason", "str", min_len=1)]


@bp.route("/stroke-centers", methods=["POST"])
def create_center():
    authenticate(("ProgramCoordinator",))
    body = read_body(CREATE_SPEC)
    record = {
        "name": body["name"],
        "facility_type": body["facility_type"],
        "state_code": body["state_code"],
        "ems_region_code": body["ems_region_code"],
        "certification_status": "PROVISIONAL",
        "ct_scanner_ready": True,
        "video_cart_ready": True,
        "equipment_readiness_posture": "READY",
        "open_case_count": 0,
        "ems_routing_posture": "ROUTINE",
        "public_dtn_compliance_pct": None,
        "public_report_published_at": None,
        "suspension_reason": None,
        "consecutive_denied_report_count": 0,
    }
    db.insert("centers", record)
    derive.recompute_equipment_posture(record)
    derive.settle_center(record)
    return resp.object_response(record, 201)


@bp.route("/stroke-centers/<record_id>", methods=["GET"])
def read_center(record_id):
    authenticate("any")
    record = load_path("centers", record_id)
    return resp.object_response(record)


@bp.route("/stroke-centers", methods=["GET"])
def list_centers():
    authenticate("any")
    limit, offset = pagination()
    records = apply_filters(db.all_of("centers"), {
        "facility_type": "facility_type",
        "certification_status": "certification_status",
        "ems_region_code": "ems_region_code",
        "ems_routing_posture": "ems_routing_posture",
    })
    return resp.list_response(records, limit, offset)


@bp.route("/stroke-centers/<record_id>", methods=["PATCH"])
def update_center(record_id):
    authenticate(("ProgramCoordinator",))
    record = load_path("centers", record_id)
    body = read_body(PATCH_SPEC)
    if body["name"] is not None:
        record["name"] = body["name"]
    if body["ems_region_code"] is not None:
        record["ems_region_code"] = body["ems_region_code"]
    db.touch(record)
    return resp.object_response(record)


@bp.route("/stroke-centers/<record_id>/readiness-attestations", methods=["POST"])
def attest_readiness(record_id):
    authenticate(("ProgramCoordinator",))
    record = load_path("centers", record_id)
    body = read_body(ATTESTATION_SPEC)
    flag = "ct_scanner_ready" if body["component"] == "CT_SCANNER" else "video_cart_ready"
    record[flag] = body["result"] == "PASS"
    db.touch(record)
    derive.recompute_equipment_posture(record)
    derive.recompute_ems_posture(record)
    return resp.object_response(record)


@bp.route("/stroke-centers/<record_id>/suspend", methods=["POST"])
def suspend_center(record_id):
    authenticate(("CertificationReviewer",))
    record = load_path("centers", record_id)
    body = read_body(SUSPEND_SPEC)
    if record["certification_status"] not in ("PROVISIONAL", "CERTIFIED", "CONDITIONAL"):
        fail("ERR_INVALID_CENTER_STATE",
             "A facility in %s cannot be suspended." % record["certification_status"])
    derive.suspend_center_cascade(record, body["suspension_reason"])
    return resp.object_response(record)
