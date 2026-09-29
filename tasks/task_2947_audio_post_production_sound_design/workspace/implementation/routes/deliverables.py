"""Deliverables, QC rounds and delivery (PRD §3.7, §3.8)."""

from flask import Blueprint

import calc
import clock
import derive
import middleware
import response
import serialize
import validation as V
from db import db, new_record, newest_first, touch
from errors import ApiError

bp = Blueprint("deliverables", __name__)


@bp.post("/deliverables")
def create_deliverable():
    user_id, _role = middleware.actor("PostSupervisor")
    payload = V.body()
    project = middleware.body_ref(payload, "project_id", db.projects)
    spec = middleware.body_ref(payload, "platform_spec_id", db.platform_specs)
    package = middleware.body_ref(payload, "stem_package_id", db.stem_packages)
    booking = middleware.body_ref(payload, "mix_booking_id", db.mix_bookings)
    expected = V.v_int(payload, "expected_project_version")
    V.v_string(payload, "project_id", minlen=1)
    V.v_string(payload, "platform_spec_id", minlen=1)
    V.v_string(payload, "stem_package_id", minlen=1)
    V.v_string(payload, "mix_booking_id", minlen=1)

    if expected != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION")
    middleware.gate_posture(project, "deliverable_create")
    middleware.gate_archived(project)
    middleware.gate_picture_locked(project)
    if package["status"] != "CONFORMED":
        raise ApiError("ERR_STEM_NOT_CONFORMED")
    if project["unlicensed_usage_count"] >= 1:
        raise ApiError("ERR_UNLICENSED_MATERIAL_PRESENT")
    if spec["platform"] != booking["platform"]:
        raise ApiError("ERR_SPEC_PLATFORM_MISMATCH")
    if package["project_id"] != project["id"] or booking["project_id"] != project["id"]:
        raise ApiError("ERR_CROSS_PROJECT_REFERENCE")

    for old in derive.deliverables_of(project["id"]):
        if old["platform_spec_id"] != spec["id"]:
            continue
        if old["status"] not in derive.OPEN_DELIVERABLE_STATUSES:
            continue
        old["status"] = "SUPERSEDED"
        touch(old)

    record = new_record()
    record.update({
        "project_id": project["id"],
        "platform_spec_id": spec["id"],
        "stem_package_id": package["id"],
        "mix_booking_id": booking["id"],
        "status": "PREPARED",
        "measured_integrated_lufs": None,
        "measured_true_peak_dbtp": None,
        "me_stems_present": None,
        "deviation_lu": None,
        "remediation_round": 0,
        "qc_rejection_codes": [],
        "prepared_by_user_id": user_id,
        "delivery_reference": None,
        "delivered_at_utc": None,
        "invalidation_reason": None,
        "_submitted_by_user_id": None,
    })
    db.deliverables[record["id"]] = record

    derive.recompute_project(project)
    derive.touch_project(project)
    return response.object_response(serialize.deliverable(record), 201)


@bp.get("/deliverables/<deliverable_id>")
def read_deliverable(deliverable_id):
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "Mixer",
                     "QcOperator", "ClientReviewer")
    record = middleware.path_deliverable(deliverable_id)
    return response.object_response(serialize.deliverable(record))


@bp.get("/deliverables")
def list_deliverables():
    middleware.actor("FacilityAdmin", "PostSupervisor", "SoundEditor", "Mixer", "QcOperator")
    limit, offset = V.pagination()
    filters = [
        ("project_id", "project_id"),
        ("platform_spec_id", "platform_spec_id"),
        ("stem_package_id", "stem_package_id"),
        ("mix_booking_id", "mix_booking_id"),
        ("status", "status"),
    ]
    records = list(db.deliverables.values())
    for param, field in filters:
        value = V.query_filter(param)
        if value is not None:
            records = [r for r in records if r[field] == value]
    records = newest_first(records)
    window, total = response.paginate(records, limit, offset)
    return response.list_response([serialize.deliverable(r) for r in window],
                                  limit, offset, total)


@bp.post("/deliverables/<deliverable_id>/qc-submit")
def qc_submit(deliverable_id):
    """PRD §3.7: PREPARED|REMEDIATION -> QC_SUBMITTED."""
    user_id, _role = middleware.actor("QcOperator")
    deliverable = middleware.path_deliverable(deliverable_id)
    payload = V.body()
    measured_lufs = V.v_decimal(payload, "measured_integrated_lufs",
                                minv="-40.00", maxv="0.00")
    measured_peak = V.v_decimal(payload, "measured_true_peak_dbtp",
                                minv="-20.00", maxv="0.00")
    me_stems_present = V.v_bool(payload, "me_stems_present")
    project = db.projects.get(deliverable["project_id"])
    middleware.gate_posture(project, "qc_submit")
    middleware.gate_archived(project)
    if deliverable["status"] not in ("PREPARED", "REMEDIATION"):
        raise ApiError("ERR_INVALID_STATE")
    package = db.stem_packages.get(deliverable["stem_package_id"])
    if package["status"] != "CONFORMED":
        raise ApiError("ERR_STEM_NOT_CONFORMED")
    booking = db.mix_bookings.get(deliverable["mix_booking_id"])
    if booking["status"] != "COMPLETED":
        raise ApiError("ERR_BOOKING_NOT_COMPLETED")
    if user_id == deliverable["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    spec = db.platform_specs.get(deliverable["platform_spec_id"])
    deliverable["status"] = "QC_SUBMITTED"
    deliverable["measured_integrated_lufs"] = measured_lufs
    deliverable["measured_true_peak_dbtp"] = measured_peak
    deliverable["me_stems_present"] = me_stems_present
    deliverable["deviation_lu"] = calc.deviation_lu(measured_lufs, spec["target_lufs"])
    deliverable["_submitted_by_user_id"] = user_id
    touch(deliverable)
    return response.object_response(serialize.deliverable(deliverable))


@bp.post("/deliverables/<deliverable_id>/qc-evaluate")
def qc_evaluate(deliverable_id):
    """PRD §3.7/§4: the one action endpoint that answers 201, returning the new
    immutable QcReport."""
    user_id, _role = middleware.actor("QcOperator")
    deliverable = middleware.path_deliverable(deliverable_id)
    project = db.projects.get(deliverable["project_id"])
    middleware.gate_posture(project, "qc_evaluate")
    middleware.gate_archived(project)
    if deliverable["status"] != "QC_SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    if user_id == deliverable["_submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    spec = db.platform_specs.get(deliverable["platform_spec_id"])
    deviation, codes = calc.qc_rejection_codes(
        deliverable["measured_integrated_lufs"],
        deliverable["measured_true_peak_dbtp"],
        deliverable["me_stems_present"],
        spec,
    )
    report = new_record(versioned=False)
    report.update({
        "deliverable_id": deliverable["id"],
        "round": deliverable["remediation_round"],
        "verdict": "PASS" if len(codes) == 0 else "FAIL",
        "rejection_codes": list(codes),
        "measured_integrated_lufs": deliverable["measured_integrated_lufs"],
        "measured_true_peak_dbtp": deliverable["measured_true_peak_dbtp"],
        "target_lufs": spec["target_lufs"],
        "deviation_lu": deviation,
        "submitted_by_user_id": deliverable["_submitted_by_user_id"],
        "evaluated_by_user_id": user_id,
        "evaluated_at_utc": clock.now(),
    })
    db.qc_reports[report["id"]] = report

    deliverable["deviation_lu"] = deviation
    if len(codes) == 0:
        deliverable["status"] = "QC_PASSED"
        deliverable["qc_rejection_codes"] = []
    else:
        deliverable["status"] = "QC_REJECTED"
        deliverable["qc_rejection_codes"] = list(codes)
    touch(deliverable)
    return response.object_response(serialize.qc_report(report), 201)


@bp.get("/deliverables/<deliverable_id>/qc-reports")
def list_qc_reports(deliverable_id):
    middleware.actor("FacilityAdmin", "PostSupervisor", "QcOperator", "ClientReviewer")
    deliverable = middleware.path_deliverable(deliverable_id)
    limit, offset = V.pagination()
    records = [r for r in db.qc_reports.values()
               if r["deliverable_id"] == deliverable["id"]]
    # PRD §2.3: QC reports are ordered by round ASC then created_at ASC.
    records = sorted(records, key=lambda r: (r["round"], r["created_at"], r["_seq"]))
    window, total = response.paginate(records, limit, offset)
    return response.list_response([serialize.qc_report(r) for r in window],
                                  limit, offset, total)


@bp.post("/deliverables/<deliverable_id>/remediate")
def remediate(deliverable_id):
    """PRD §3.7: QC_REJECTED -> REMEDIATION while rounds remain."""
    middleware.actor("PostSupervisor")
    deliverable = middleware.path_deliverable(deliverable_id)
    payload = V.body()
    V.v_string(payload, "remediation_note", required=False, minlen=0, maxlen=2000)
    project = db.projects.get(deliverable["project_id"])
    middleware.gate_posture(project, "remediate")
    middleware.gate_archived(project)
    if deliverable["status"] != "QC_REJECTED":
        raise ApiError("ERR_INVALID_STATE")
    spec = db.platform_specs.get(deliverable["platform_spec_id"])
    if deliverable["remediation_round"] >= spec["max_remediation_rounds"]:
        raise ApiError("ERR_REMEDIATION_LIMIT_EXCEEDED")

    deliverable["status"] = "REMEDIATION"
    deliverable["remediation_round"] = deliverable["remediation_round"] + 1
    deliverable["qc_rejection_codes"] = []
    touch(deliverable)
    return response.object_response(serialize.deliverable(deliverable))


@bp.post("/deliverables/<deliverable_id>/deliver")
def deliver(deliverable_id):
    """PRD §3.8: QC_PASSED -> DELIVERED."""
    middleware.actor("PostSupervisor")
    deliverable = middleware.path_deliverable(deliverable_id)
    payload = V.body()
    reference = V.v_string(payload, "delivery_reference", minlen=1, maxlen=200)
    project = db.projects.get(deliverable["project_id"])
    middleware.gate_posture(project, "deliver")
    middleware.gate_archived(project)
    if deliverable["status"] != "QC_PASSED":
        raise ApiError("ERR_INVALID_STATE")
    package = db.stem_packages.get(deliverable["stem_package_id"])
    if package["status"] != "CONFORMED":
        raise ApiError("ERR_STEM_NOT_CONFORMED")
    if project["license_risk_score_audit"] >= calc.RISK_BLOCK_THRESHOLD:
        raise ApiError("ERR_LICENSE_RISK_TOO_HIGH")

    deliverable["status"] = "DELIVERED"
    deliverable["delivery_reference"] = reference
    deliverable["delivered_at_utc"] = clock.now()
    touch(deliverable)
    derive.advance_pipeline(project, "QC", "DELIVERED")
    derive.recompute_project(project)
    derive.touch_project(project)
    return response.object_response(serialize.deliverable(deliverable))
