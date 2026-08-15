"""Distortion reports, inspections, traveler sign-offs (nested routes)."""

from flask import Blueprint

from db import db
from errors import (
    ApiError, ERR_INSUFFICIENT_PERMISSIONS, ERR_INVALID_DISPOSITION,
    ERR_INVALID_NDT_METHOD, ERR_NDT_VENDOR_INVALID, ERR_NDT_VENDOR_SLOT_CONFLICT,
    ERR_INSPECTION_TOO_EARLY, ERR_SEGREGATION_OF_DUTIES, ERR_TRAVELER_INCOMPLETE,
    invalid_request, invalid_state,
)
from helpers import (
    json_body, require_fields, parse_number, parse_datetime, paginate,
    NDT_METHODS, DISPOSITIONS, STEP_CODES, INSPECTION_RESULTS,
)
from middleware import require_roles, require_any
from response import success_object, success_list
from serializers import distortion_report_out, inspection_out, sign_off_out
from services import (
    stamp_new, mutate, get_shop, get_weldment, get_joint, get_report,
    get_inspection, joints_of_weldment, derive_posture_open_restricted,
    check_frozen_gate, cancel_weldment_cascade, joint_welder_ids,
    apply_inspection_pass,
)

bp = Blueprint("quality", __name__)

STEP_ROLE_MAP = {
    "FIT_UP": {"WeldLead"},
    "WELD_OUT": {"WeldLead"},
    "VT": {"QualityInspector", "CWI"},
    "NDT": {"QualityInspector", "CWI"},
    "FINAL": {"CWI"},
}


# ---------------------------------------------------------------------------
# Distortion reports
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops/<shop_id>/weldments/<weldment_id>/distortion-reports", methods=["POST"])
@require_roles("QualityInspector")
def create_distortion_report(user_id, role, shop_id, weldment_id):
    shop = get_shop(shop_id)
    wm = get_weldment(shop_id, weldment_id)
    body = json_body()
    require_fields(body, ["joint_id", "measured_deviation_mm", "tolerance_mm"])
    joint = db.joints.get(body["joint_id"])
    if joint is None or joint["weldment_id"] != wm["id"]:
        from errors import not_found
        raise not_found("Joint")
    report = stamp_new({
        "shop_id": shop["id"],
        "weldment_id": wm["id"],
        "joint_id": joint["id"],
        "measured_deviation_mm": parse_number(body["measured_deviation_mm"], "measured_deviation_mm"),
        "tolerance_mm": parse_number(body["tolerance_mm"], "tolerance_mm"),
        "reported_by_user_id": user_id,
        "reported_at_utc": shop["current_utc"],
        "disposition": "PENDING",
    })
    db.distortion_reports[report["id"]] = report
    wm["distortion_count"] += 1
    # posture: FROZEN gate (from OPEN) else OPEN -> RESTRICTED derivation
    frozen = check_frozen_gate(wm)
    if not frozen:
        derive_posture_open_restricted(wm, touch=False)
    mutate(wm)  # one version bump per request (count changed, posture maybe)
    return success_object(distortion_report_out(report), status=201)


@bp.route("/weld-shop/shops/<shop_id>/weldments/<weldment_id>/distortion-reports", methods=["GET"])
@require_any
def list_distortion_reports(user_id, role, shop_id, weldment_id):
    get_shop(shop_id)
    wm = get_weldment(shop_id, weldment_id)
    records = [r for r in db.distortion_reports.values() if r["weldment_id"] == wm["id"]]
    page, limit, offset, total = paginate(records)
    return success_list([distortion_report_out(r) for r in page], limit, offset, total)


@bp.route("/weld-shop/shops/<shop_id>/distortion-reports/<report_id>/disposition", methods=["POST"])
@require_roles("QCManager")
def disposition_report(user_id, role, shop_id, report_id):
    get_shop(shop_id)
    report = get_report(shop_id, report_id)
    body = json_body()
    require_fields(body, ["disposition"])
    if body["disposition"] not in DISPOSITIONS:
        raise ApiError(ERR_INVALID_DISPOSITION, 422,
                       "Disposition must be REWORK, USE_AS_IS, or SCRAP")
    if report["disposition"] != "PENDING":
        raise invalid_state("Distortion report is not PENDING")
    report["disposition"] = body["disposition"]
    wm = db.weldments.get(report["weldment_id"])
    if wm is not None:
        if body["disposition"] == "SCRAP":
            # scrapping the distorted work cancels the parent weldment
            if wm["posture"] != "CANCELLED":
                cancel_weldment_cascade(wm)
        else:
            # disposition is a weldment-level mutation event (drives ship OCC);
            # posture recompute rides along with a single version bump
            derive_posture_open_restricted(wm, touch=False)
            mutate(wm)
    return success_object(distortion_report_out(report))


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------

def _slot_conflict(vendor, start, end):
    """Half-open [start, end) overlap: existing.start < new.end and
    existing.end > new.start; end == new.start does NOT conflict."""
    overlapping = sum(
        1
        for ins in db.inspections.values()
        if ins["vendor_id"] == vendor["id"]
        and ins["result"] is None
        and ins["scheduled_start_utc"] < end
        and ins["scheduled_end_utc"] > start
    )
    return overlapping >= vendor["hourly_capacity"]


def _apply_result(shop, joint, inspection, result, result_code, recorder_id):
    """Apply a PASS/FAIL to a scheduled-or-new inspection (shared by create
    with inline result and by record-result)."""
    now = shop["current_utc"]
    inspection["result"] = result
    inspection["result_code"] = result_code
    inspection["resulted_at_utc"] = now
    wm = db.weldments.get(joint["weldment_id"])
    if result == "PASS":
        old_status = joint["inspection_status"]
        apply_inspection_pass(joint, inspection)
        if joint["inspection_status"] != old_status:
            mutate(joint)
    else:
        # FAIL: only UT/RT failures drive the NDT_FAILED transition
        if inspection["method"] in ("UT", "RT"):
            joint["inspection_status"] = "NDT_FAILED"
            joint["repair_cycle_count"] += 1
            joint["_last_ndt_failed_at"] = now
            if joint["repair_cycle_count"] > 2:
                joint["fabrication_status"] = "CANCELLED"
            mutate(joint)
            if wm is not None:
                check_frozen_gate(wm)
    # a recorded joint result is a weldment-level mutation event (drives OCC)
    if wm is not None:
        mutate(wm)


@bp.route("/weld-shop/shops/<shop_id>/joints/<joint_id>/inspections", methods=["POST"])
@require_roles("CWI")
def create_inspection(user_id, role, shop_id, joint_id):
    shop = get_shop(shop_id)
    joint = get_joint(shop_id, joint_id)
    body = json_body()
    require_fields(body, ["method", "scheduled_start_utc", "scheduled_end_utc"])
    method = body["method"]
    vendor_id = body.get("vendor_id")
    # method discipline: VT in-house (vendor null); UT/RT require a vendor
    if method not in NDT_METHODS:
        raise ApiError(ERR_INVALID_NDT_METHOD, 422, "Method must be VT, UT, or RT")
    if method == "VT" and vendor_id is not None:
        raise ApiError(ERR_INVALID_NDT_METHOD, 422,
                       "VT is performed in-house; vendor_id must be null")
    if method in ("UT", "RT") and vendor_id is None:
        raise ApiError(ERR_INVALID_NDT_METHOD, 422,
                       "UT/RT inspections must name a vendor")
    start = parse_datetime(body["scheduled_start_utc"], "scheduled_start_utc")
    end = parse_datetime(body["scheduled_end_utc"], "scheduled_end_utc")
    if not (end > start):
        raise invalid_request("scheduled_end_utc must be strictly after scheduled_start_utc")
    result = body.get("result")
    result_code = body.get("result_code")
    if result is not None and result not in INSPECTION_RESULTS:
        raise invalid_request("result must be PASS or FAIL")

    vendor = None
    if method == "VT":
        if result is not None:
            # immediate VT result recording
            if joint["inspection_status"] != "READY_FOR_VT":
                raise invalid_state("Joint inspection_status must be READY_FOR_VT")
            if result == "PASS" and user_id in joint_welder_ids(joint["id"]):
                raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                               "VT inspector must not be a welder on this joint")
    else:
        # UT/RT scheduling gates
        if joint["inspection_status"] != "VT_PASSED":
            raise invalid_state("Joint inspection_status must be VT_PASSED to schedule NDT")
        vendor = db.ndt_vendors.get(vendor_id)
        if (
            vendor is None
            or vendor["shop_id"] != shop["id"]
            or vendor["status"] != "ACTIVE"
            or method not in vendor["supported_methods"]
        ):
            raise ApiError(ERR_NDT_VENDOR_INVALID, 422,
                           "Vendor missing, not ACTIVE, or method not supported")
        if _slot_conflict(vendor, start, end):
            raise ApiError(ERR_NDT_VENDOR_SLOT_CONFLICT, 409,
                           "Vendor slot capacity exceeded for overlapping interval")
        if result is not None and shop["current_utc"] < end:
            raise ApiError(ERR_INSPECTION_TOO_EARLY, 422,
                           "Cannot record result before scheduled_end_utc")

    inspection = stamp_new({
        "shop_id": shop["id"],
        "joint_id": joint["id"],
        "method": method,
        "inspector_user_id": user_id,
        "scheduled_start_utc": start,
        "scheduled_end_utc": end,
        "vendor_id": vendor_id,
        "result": None,
        "result_code": None,
        "resulted_at_utc": None,
        "hold_point_released": False,
    })
    db.inspections[inspection["id"]] = inspection

    if method in ("UT", "RT"):
        joint["inspection_status"] = "NDT_IN_PROGRESS"
        mutate(joint)

    if result is not None:
        _apply_result(shop, joint, inspection, result, result_code, user_id)

    return success_object(inspection_out(inspection), status=201)


@bp.route("/weld-shop/shops/<shop_id>/joints/<joint_id>/inspections", methods=["GET"])
@require_any
def list_inspections(user_id, role, shop_id, joint_id):
    get_shop(shop_id)
    joint = get_joint(shop_id, joint_id)
    records = [i for i in db.inspections.values() if i["joint_id"] == joint["id"]]
    page, limit, offset, total = paginate(records)
    return success_list([inspection_out(i) for i in page], limit, offset, total)


@bp.route("/weld-shop/shops/<shop_id>/inspections/<inspection_id>", methods=["GET"])
@require_any
def get_inspection_route(user_id, role, shop_id, inspection_id):
    get_shop(shop_id)
    return success_object(inspection_out(get_inspection(shop_id, inspection_id)))


@bp.route("/weld-shop/shops/<shop_id>/inspections/<inspection_id>/record-result", methods=["POST"])
@require_roles("CWI")
def record_result(user_id, role, shop_id, inspection_id):
    shop = get_shop(shop_id)
    inspection = get_inspection(shop_id, inspection_id)
    body = json_body()
    require_fields(body, ["result"])
    if body["result"] not in INSPECTION_RESULTS:
        raise invalid_request("result must be PASS or FAIL")
    result = body["result"]
    result_code = body.get("result_code")
    if inspection["result"] is not None:
        raise invalid_state("Inspection result is already recorded")
    joint = db.joints.get(inspection["joint_id"])
    if joint is None:
        from errors import not_found
        raise not_found("Joint")
    # lifecycle: UT/RT results require NDT_IN_PROGRESS; VT results require READY_FOR_VT
    if inspection["method"] in ("UT", "RT"):
        if joint["inspection_status"] != "NDT_IN_PROGRESS":
            raise invalid_state("Joint is not NDT_IN_PROGRESS")
    else:
        if joint["inspection_status"] != "READY_FOR_VT":
            raise invalid_state("Joint inspection_status must be READY_FOR_VT")
        if result == "PASS" and user_id in joint_welder_ids(joint["id"]):
            raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                           "VT inspector must not be a welder on this joint")
    if shop["current_utc"] < inspection["scheduled_end_utc"]:
        raise ApiError(ERR_INSPECTION_TOO_EARLY, 422,
                       "Cannot record result before scheduled_end_utc")
    _apply_result(shop, joint, inspection, result, result_code, user_id)
    return success_object(inspection_out(inspection))


# ---------------------------------------------------------------------------
# Traveler sign-offs
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops/<shop_id>/weldments/<weldment_id>/traveler-sign-offs", methods=["POST"])
@require_roles("CWI", "WeldLead", "QualityInspector")
def create_sign_off(user_id, role, shop_id, weldment_id):
    shop = get_shop(shop_id)
    wm = get_weldment(shop_id, weldment_id)
    body = json_body()
    require_fields(body, ["step_code"])
    step = body["step_code"]
    if step not in STEP_CODES:
        raise invalid_request("step_code must be one of FIT_UP, WELD_OUT, VT, NDT, FINAL")
    if role not in STEP_ROLE_MAP[step]:
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, 403,
                       "Role lacks authority to sign this traveler step")
    if step == "FINAL":
        existing = {
            s["step_code"] for s in db.sign_offs.values() if s["weldment_id"] == wm["id"]
        }
        if not {"FIT_UP", "WELD_OUT", "VT", "NDT"} <= existing:
            raise ApiError(ERR_TRAVELER_INCOMPLETE, 409,
                           "One or more required traveler steps missing")
    sign_off = stamp_new({
        "shop_id": shop["id"],
        "weldment_id": wm["id"],
        "step_code": step,
        "signed_by_user_id": user_id,
        "signed_at_utc": shop["current_utc"],
        "notes": body.get("notes"),
    })
    db.sign_offs[sign_off["id"]] = sign_off
    return success_object(sign_off_out(sign_off), status=201)


@bp.route("/weld-shop/shops/<shop_id>/weldments/<weldment_id>/traveler-sign-offs", methods=["GET"])
@require_any
def list_sign_offs(user_id, role, shop_id, weldment_id):
    get_shop(shop_id)
    wm = get_weldment(shop_id, weldment_id)
    records = [s for s in db.sign_offs.values() if s["weldment_id"] == wm["id"]]
    page, limit, offset, total = paginate(records)
    return success_list([sign_off_out(s) for s in page], limit, offset, total)
