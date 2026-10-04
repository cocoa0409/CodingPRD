"""Repair order, procedure step, and part line endpoints."""
from flask import Blueprint, request

import calc
from calc import ADAS_MODEL_YEAR_THRESHOLD, MAX_REWORK
from db import db, serialize
from util import (ApiError, bump, get_json, iso_ms, now_logical, ok, paginate,
                  parse_dt, sort_by_created, new_common)
from routes.shops import require_roles, get_shop_or_404

bp = Blueprint("repairs", __name__)

ROLES_READ_ORDERS = {"NetworkAdmin", "NetworkAuditor", "ShopManager", "InsurerRep"}
PART_CLASSES = {"OE", "OE_SURPLUS", "AFTERMARKET", "RECYCLED", "REMANUFACTURED"}
STEP_TYPES = {"PRE_SCAN", "STRUCTURAL_MEASURE", "WELD_BOND", "POST_SCAN",
              "ADAS_CALIBRATION_STATIC", "ADAS_CALIBRATION_DYNAMIC"}
STEP_RESULTS = {"PASS", "FAIL", "NOT_APPLICABLE"}
EDITABLE_FOR_PARTS = {"ESTIMATE", "APPROVED", "IN_REPAIR"}
STEP_RECORDABLE_STATES = {"ESTIMATE", "IN_REPAIR", "QC", "REWORK", "CALIBRATION"}


def get_order_or_404(order_id):
    order = db.repair_orders.get(order_id)
    if not order:
        raise ApiError("ERR_NOT_FOUND", 404, "Repair order not found")
    return order


def _own_shop(order):
    if request.headers.get("X-User-Role") == "ShopManager" \
            and request.headers.get("X-User-ID") != order["shop_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "ShopManager may only act on their own shop's orders")


def _reassign_sequence(order_id):
    steps = [s for s in db.procedure_steps.values()
             if s["repair_order_id"] == order_id]
    steps.sort(key=lambda s: (s["performed_at"], s["created_at"], s["_seq"]))
    for i, s in enumerate(steps, start=1):
        if s.get("sequence_index") != i:
            s["sequence_index"] = i
            bump(s)


# ---------------------------------------------------------------------------
# Repair orders
# ---------------------------------------------------------------------------
@bp.post("/network/shops/<shop_id>/repair-orders")
def create_order(shop_id):
    require_roles("ShopManager")
    if request.headers.get("X-User-ID") != shop_id:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "ShopManager may only create orders for their own shop")
    shop = get_shop_or_404(shop_id)
    body = get_json()
    vin = body.get("vin")
    model_year = body.get("vehicle_model_year")
    estimate = body.get("estimate_total_cents")
    tech_id = body.get("assigned_technician_id")
    is_structural = body.get("is_structural", False)
    adas = body.get("adas_equipped")
    referral_id = body.get("referral_id")
    relation_id = body.get("insurer_relation_id")
    expected = body.get("expected_shop_version")

    # existence (body FKs)
    if not isinstance(tech_id, str) or tech_id not in db.technicians:
        raise ApiError("ERR_NOT_FOUND", 404, "Assigned technician not found")
    tech = db.technicians[tech_id]
    if referral_id is not None and referral_id not in db.referrals:
        raise ApiError("ERR_NOT_FOUND", 404, "Referral not found")
    if relation_id is not None and relation_id not in db.insurer_relations:
        raise ApiError("ERR_NOT_FOUND", 404, "Insurer relation not found")

    # OCC
    if not isinstance(expected, int) or expected != shop["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_shop_version does not match current shop version")

    # business: structural capability
    if not isinstance(is_structural, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "is_structural must be a boolean")
    if is_structural:
        if not shop.get("structural_capability") \
                or tech["tech_role"] != "STRUCTURAL" \
                or tech["status"] != "CURRENT" \
                or tech["shop_id"] != shop["id"]:
            raise ApiError("ERR_STRUCTURAL_CAPABILITY", 422,
                           "Structural repair requires shop capability and a CURRENT STRUCTURAL technician")
    if shop["certification_status"] not in ("CERTIFIED", "PROBATION"):
        raise ApiError("ERR_SHOP_NOT_CERTIFIED", 422,
                       "Shop posture forbids starting new repairs")

    # format checks
    if not isinstance(vin, str) or len(vin) != 17:
        raise ApiError("ERR_INVALID_REQUEST", 400, "vin must be 17 characters")
    if not isinstance(model_year, int) or isinstance(model_year, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "vehicle_model_year must be an integer")
    if not isinstance(estimate, int) or isinstance(estimate, bool) or estimate < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "estimate_total_cents must be an integer >= 0")
    if adas is not None and not isinstance(adas, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "adas_equipped must be a boolean")

    order = new_common()
    order.update({
        "shop_id": shop["id"],
        "referral_id": referral_id,
        "vin": vin,
        "vehicle_model_year": model_year,
        "adas_equipped": adas,
        "is_structural": is_structural,
        "insurer_relation_id": relation_id,
        "assigned_technician_id": tech_id,
        "status": "ESTIMATE",
        "estimate_total_cents": estimate,
        "oe_parts_ratio_by_cost": 0.0,
        "oe_parts_ratio_by_count": 0.0,
        "rework_count": 0,
        "completed_at": None,
        "_reserve_accrual": None,
        "_reserve_remaining": 0,
    })
    db.repair_orders[order["id"]] = order
    shop["lifetime_repair_count"] = shop.get("lifetime_repair_count", 0) + 1
    bump(shop)
    return ok(serialize(order), 201)


@bp.get("/network/shops/<shop_id>/repair-orders")
def list_shop_orders(shop_id):
    require_roles(*ROLES_READ_ORDERS)
    get_shop_or_404(shop_id)
    status = request.args.get("status")
    items = [o for o in db.repair_orders.values() if o["shop_id"] == shop_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(o) for o in page], 200, meta)


@bp.get("/network/repair-orders/<order_id>")
def get_order(order_id):
    require_roles(*ROLES_READ_ORDERS)
    return ok(serialize(get_order_or_404(order_id)))


@bp.post("/network/repair-orders/<order_id>/approve")
def approve_order(order_id):
    require_roles("ShopManager")
    order = get_order_or_404(order_id)
    _own_shop(order)
    if order["status"] != "ESTIMATE":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not in ESTIMATE")
    shop = db.shops.get(order["shop_id"])
    tech = db.technicians.get(order["assigned_technician_id"])
    # business safety: pre-scan rule
    has_pre_scan = any(
        s["repair_order_id"] == order["id"] and s["step_type"] == "PRE_SCAN"
        and s["status"] == "RECORDED" and s["result"] != "NOT_APPLICABLE"
        for s in db.procedure_steps.values())
    if not has_pre_scan:
        raise ApiError("ERR_PRE_SCAN_REQUIRED", 422,
                       "A PRE_SCAN step with result != NOT_APPLICABLE is required")
    # referential: structural capability / technician posture
    if not tech or tech["shop_id"] != order["shop_id"]:
        raise ApiError("ERR_STRUCTURAL_CAPABILITY", 422,
                       "Assigned technician must belong to the same shop")
    if order["is_structural"]:
        if not shop.get("structural_capability") \
                or tech["tech_role"] != "STRUCTURAL" \
                or tech["status"] != "CURRENT":
            raise ApiError("ERR_STRUCTURAL_CAPABILITY", 422,
                           "Structural repair requires shop capability and a CURRENT STRUCTURAL technician")
    else:
        if tech["status"] not in ("CURRENT", "PROVISIONAL"):
            raise ApiError("ERR_STRUCTURAL_CAPABILITY", 422,
                           "Assigned technician must be CURRENT or PROVISIONAL")
    # constraint: posture gate
    if shop["certification_status"] not in ("CERTIFIED", "PROBATION"):
        raise ApiError("ERR_SHOP_NOT_CERTIFIED", 422,
                       "Shop posture forbids approving repairs")
    order["status"] = "APPROVED"
    bump(order)
    return ok(serialize(order))


@bp.post("/network/repair-orders/<order_id>/start-repair")
def start_repair(order_id):
    require_roles("ShopManager")
    order = get_order_or_404(order_id)
    _own_shop(order)
    if order["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not APPROVED")
    if not any(l["repair_order_id"] == order["id"] and l["line_status"] == "ACTIVE"
               for l in db.part_lines.values()):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "At least one ACTIVE part line is required")
    order["status"] = "IN_REPAIR"
    bump(order)
    return ok(serialize(order))


@bp.post("/network/repair-orders/<order_id>/submit-qc")
def submit_qc(order_id):
    require_roles("ShopManager")
    order = get_order_or_404(order_id)
    _own_shop(order)
    if order["status"] not in ("IN_REPAIR", "REWORK"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Order must be IN_REPAIR or REWORK to submit to QC")
    order["status"] = "QC"
    bump(order)
    return ok(serialize(order))


@bp.post("/network/repair-orders/<order_id>/fail-qc")
def fail_qc(order_id):
    require_roles("ShopManager")
    order = get_order_or_404(order_id)
    _own_shop(order)
    if order["status"] != "QC":
        raise ApiError("ERR_INVALID_STATE", 409, "Order is not in QC")
    if order["rework_count"] >= MAX_REWORK:
        raise ApiError("ERR_MAX_REWORK", 422,
                       "Maximum rework loops (3) reached")
    order["rework_count"] += 1
    order["status"] = "REWORK"
    bump(order)
    return ok(serialize(order))


@bp.post("/network/repair-orders/<order_id>/pass-qc")
def pass_qc(order_id):
    require_roles("ShopManager")
    order = get_order_or_404(order_id)
    _own_shop(order)
    if order["status"] not in ("QC", "CALIBRATION"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Order must be in QC or CALIBRATION to pass QC")
    is_adas = calc.is_adas_equipped(order)
    if order["status"] == "QC":
        if is_adas:
            order["status"] = "CALIBRATION"
            bump(order)
            return ok(serialize(order))
        # non-ADAS: scan-after-parts chronology. A passing POST_SCAN must
        # exist whose performed_at is strictly later than every ACTIVE part
        # line's created_at.
        post_scans = [s for s in db.procedure_steps.values()
                      if s["repair_order_id"] == order["id"]
                      and s["step_type"] == "POST_SCAN"
                      and s["status"] == "RECORDED"
                      and s["result"] == "PASS"]
        active_lines = [l for l in db.part_lines.values()
                        if l["repair_order_id"] == order["id"]
                        and l["line_status"] == "ACTIVE"]
        ok_scan = any(
            all(s["performed_at"] > l["created_at"] for l in active_lines)
            for s in post_scans)
        if not ok_scan:
            raise ApiError("ERR_POST_SCAN_REQUIRED", 422,
                           "A passing POST_SCAN later than every ACTIVE part line is required")
        order["status"] = "COMPLETE"
        order["completed_at"] = iso_ms(now_logical())
        bump(order)
        return ok(serialize(order))
    # CALIBRATION -> COMPLETE: calibration-after-scan chronology
    calib_steps = [s for s in db.procedure_steps.values()
                   if s["repair_order_id"] == order["id"]
                   and s["step_type"] in ("ADAS_CALIBRATION_STATIC",
                                          "ADAS_CALIBRATION_DYNAMIC")
                   and s["status"] == "RECORDED"
                   and s["result"] == "PASS"]
    post_scans = [s for s in db.procedure_steps.values()
                  if s["repair_order_id"] == order["id"]
                  and s["step_type"] == "POST_SCAN"
                  and s["status"] == "RECORDED"]
    ok_calib = any(
        all(c["performed_at"] > s["performed_at"] for s in post_scans)
        for c in calib_steps)
    if not ok_calib:
        raise ApiError("ERR_CALIBRATION_SEQUENCE", 422,
                       "A passing ADAS calibration step after every POST_SCAN is required")
    order["status"] = "COMPLETE"
    order["completed_at"] = iso_ms(now_logical())
    bump(order)
    return ok(serialize(order))


@bp.post("/network/repair-orders/<order_id>/void")
def void_order(order_id):
    require_roles("ShopManager")
    order = get_order_or_404(order_id)
    _own_shop(order)
    get_json()  # optional reason; accepted but not persisted
    if order["status"] == "ESTIMATE":
        order["status"] = "VOIDED"
        bump(order)
        return ok(serialize(order))
    if order["status"] == "APPROVED":
        if any(s["repair_order_id"] == order["id"]
               and s["step_type"] == "WELD_BOND"
               and s["status"] == "RECORDED"
               for s in db.procedure_steps.values()):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Structural work has started; order cannot be voided")
        order["status"] = "VOIDED"
        bump(order)
        return ok(serialize(order))
    raise ApiError("ERR_INVALID_STATE", 409,
                   "Only ESTIMATE or APPROVED orders can be voided")


# ---------------------------------------------------------------------------
# Procedure steps
# ---------------------------------------------------------------------------
@bp.post("/network/repair-orders/<order_id>/procedure-steps")
def create_step(order_id):
    require_roles("ShopManager")
    order = get_order_or_404(order_id)
    _own_shop(order)
    if order["status"] not in STEP_RECORDABLE_STATES:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Steps may only be recorded while the order is active")
    body = get_json()
    step_type = body.get("step_type")
    tech_id = body.get("performed_by_technician_id")
    performed_at = body.get("performed_at")
    result = body.get("result")
    scan_uri = body.get("scan_report_uri")
    if not isinstance(tech_id, str) or tech_id not in db.technicians:
        raise ApiError("ERR_NOT_FOUND", 404, "Technician not found")
    if step_type not in STEP_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"step_type must be one of {sorted(STEP_TYPES)}")
    if result not in STEP_RESULTS:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "result must be PASS, FAIL, or NOT_APPLICABLE")
    performed = parse_dt(performed_at, "performed_at")
    if step_type in ("PRE_SCAN", "POST_SCAN") and result != "NOT_APPLICABLE":
        if not isinstance(scan_uri, str) or not scan_uri:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "scan_report_uri is required for scan steps with a result")
    # re-performing a step type voids the older RECORDED row of that type
    for s in db.procedure_steps.values():
        if s["repair_order_id"] == order["id"] and s["step_type"] == step_type \
                and s["status"] == "RECORDED":
            s["status"] = "VOIDED"
            bump(s)
    step = new_common()
    step.update({
        "repair_order_id": order["id"],
        "step_type": step_type,
        "performed_by_technician_id": tech_id,
        "performed_at": iso_ms(performed),
        "result": result,
        "scan_report_uri": scan_uri,
        "sequence_index": 0,
        "status": "RECORDED",
    })
    db.procedure_steps[step["id"]] = step
    _reassign_sequence(order["id"])
    return ok(serialize(step), 201)


@bp.get("/network/repair-orders/<order_id>/procedure-steps")
def list_steps(order_id):
    require_roles(*ROLES_READ_ORDERS)
    get_order_or_404(order_id)
    step_type = request.args.get("step_type")
    status = request.args.get("status")
    items = [s for s in db.procedure_steps.values()
             if s["repair_order_id"] == order_id]
    if step_type is not None:
        items = [s for s in items if s["step_type"] == step_type]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sorted(items, key=lambda s: (s.get("sequence_index", 0), s.get("_seq", 0)))
    page, meta = paginate(items)
    return ok([serialize(s) for s in page], 200, meta)


# ---------------------------------------------------------------------------
# Part line items
# ---------------------------------------------------------------------------
def _validate_part_line(body):
    part_number = body.get("part_number")
    part_class = body.get("part_class")
    unit_cost = body.get("unit_cost_cents")
    quantity = body.get("quantity")
    is_safety = body.get("is_safety_critical", False)
    justification = body.get("alternative_justification")
    if part_class not in PART_CLASSES:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"part_class must be one of {sorted(PART_CLASSES)}")
    # safety classification before documentation (safety precedes constraint)
    if is_safety and part_class not in ("OE", "OE_SURPLUS"):
        raise ApiError("ERR_SAFETY_PART_CLASS", 422,
                       "Safety-critical parts may only be OE or OE_SURPLUS")
    if part_class in ("AFTERMARKET", "RECYCLED", "REMANUFACTURED"):
        if not isinstance(justification, str) or not justification:
            raise ApiError("ERR_ALT_PART_UNDOCUMENTED", 422,
                           "Non-OE parts require an alternative_justification")
    if not isinstance(part_number, str) or not part_number:
        raise ApiError("ERR_INVALID_REQUEST", 400, "part_number is required")
    if not isinstance(unit_cost, int) or isinstance(unit_cost, bool) or unit_cost < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "unit_cost_cents must be an integer >= 0")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "quantity must be an integer >= 1")
    if not isinstance(is_safety, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "is_safety_critical must be a boolean")
    return part_number, part_class, unit_cost, quantity, is_safety, justification


@bp.post("/network/repair-orders/<order_id>/part-lines")
def create_part_line(order_id):
    require_roles("ShopManager")
    order = get_order_or_404(order_id)
    _own_shop(order)
    if order["status"] not in EDITABLE_FOR_PARTS:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Part lines may only be added while the order is editable")
    body = get_json()
    part_number, part_class, unit_cost, quantity, is_safety, justification = \
        _validate_part_line(body)
    line = new_common()
    # created_at (logical clock, per the common-field contract) participates
    # in the scan-after-parts chronology rule of §3.5.
    line.update({
        "repair_order_id": order["id"],
        "part_number": part_number,
        "part_class": part_class,
        "unit_cost_cents": unit_cost,
        "quantity": quantity,
        "is_safety_critical": is_safety,
        "alternative_justification": justification,
        "line_status": "ACTIVE",
    })
    db.part_lines[line["id"]] = line
    calc.recompute_oe_ratios(order)
    return ok(serialize(line), 201)


@bp.get("/network/repair-orders/<order_id>/part-lines")
def list_part_lines(order_id):
    require_roles(*ROLES_READ_ORDERS)
    get_order_or_404(order_id)
    line_status = request.args.get("line_status")
    items = [l for l in db.part_lines.values() if l["repair_order_id"] == order_id]
    if line_status is not None:
        items = [l for l in items if l["line_status"] == line_status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(l) for l in page], 200, meta)


@bp.delete("/network/repair-orders/<order_id>/part-lines/<line_id>")
def remove_part_line(order_id, line_id):
    require_roles("ShopManager")
    order = get_order_or_404(order_id)
    line = db.part_lines.get(line_id)
    if not line or line["repair_order_id"] != order["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Part line not found")
    _own_shop(order)
    if order["status"] not in ("ESTIMATE", "APPROVED", "IN_REPAIR"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Part lines may only be removed while the order is editable")
    if line["line_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Part line is not ACTIVE")
    line["line_status"] = "REMOVED"
    bump(line)
    calc.recompute_oe_ratios(order)
    return ok(serialize(line))
