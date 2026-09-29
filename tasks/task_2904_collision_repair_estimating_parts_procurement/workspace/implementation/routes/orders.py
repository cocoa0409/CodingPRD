"""Intake, teardown, blueprint, estimate lock, total loss, QC, delivery, cycle time."""
from flask import Blueprint, request

import auth
import calc
import db
import guards
import response
import serialize
import validate
from db import store
from errors import raise_error
from validate import F

bp = Blueprint("orders", __name__)

ALL_ROLES = ("ShopAdmin", "Estimator", "PartsManager", "Technician", "QcInspector",
             "InsurerAdjuster", "Customer")
SEVERITIES = ("LIGHT", "MODERATE", "SEVERE")

ORDER_SPEC = [
    F("customer_id", "string", required=True),
    F("insurer_id", "string", required=True),
    F("claim_number", "string", required=True),
    F("vehicle_vin", "string", required=True),
    F("vehicle_model_year", "integer", required=True),
    F("vehicle_make_model", "string", required=True),
    F("initial_authorized_cents", "integer", required=True),
    F("deductible_cents", "integer", default=50000),
]


def _new_order_row(data):
    row = db.base_row()
    row.update({
        "customer_id": data["customer_id"],
        "insurer_id": data["insurer_id"],
        "claim_number": data["claim_number"],
        "vehicle_vin": data["vehicle_vin"],
        "vehicle_model_year": data["vehicle_model_year"],
        "vehicle_make_model": data["vehicle_make_model"],
        "initial_authorized_cents": data["initial_authorized_cents"],
        "deductible_cents": data["deductible_cents"],
        "checkin_at": db.now_iso(),
        "delivered_at": None,
        "stage": "INTAKE",
        "authorization_posture": "OPEN",
        "blueprint_by_user_id": None,
        "total_loss_note": None,
        "teardown_finding_count": 0,
        "refinish_hours_provisional": 0.0,
        "refinish_hours_final": 0.0,
        "approved_labor_hours": 0.0,
        "labor_subtotal_cents": 0,
        "parts_gross_cents": 0,
        "parts_discount_cents": 0,
        "parts_subtotal_cents": 0,
        "betterment_cents": 0,
        "supplies_fee_cents": 0,
        "pre_tax_total_cents": 0,
        "insurer_authorized_cents": 0,
        "customer_pay_cents": 0,
        "consent_state": "NONE",
        "consent_basis_cents": None,
        "consent_alternate_parts": False,
        "parts_ordered_gross_cents": 0,
        "parts_committed_cents": 0,
        "parts_return_credit_cents": 0,
        "parts_restocking_loss_cents": 0,
        "open_parts_delay_count": 0,
        "qc_inspection_count": 0,
    })
    return row


@bp.route("/repair-orders", methods=["POST"])
def create_repair_order():
    auth.authenticate(("ShopAdmin",))
    data = validate.body(ORDER_SPEC)
    validate.require(1980 <= data["vehicle_model_year"] <= 2100,
                     "vehicle_model_year must be between 1980 and 2100.")
    validate.require(data["initial_authorized_cents"] >= 0,
                     "initial_authorized_cents must be >= 0.")
    validate.require(data["deductible_cents"] >= 0, "deductible_cents must be >= 0.")
    if data["customer_id"] not in store.customers:
        raise_error("ERR_CUSTOMER_NOT_FOUND")
    if data["insurer_id"] not in store.insurers:
        raise_error("ERR_INSURER_NOT_FOUND")
    row = _new_order_row(data)
    store.repair_orders[row["id"]] = row
    return response.created(serialize.repair_order(row))


@bp.route("/repair-orders/<order_id>", methods=["GET"])
def read_repair_order(order_id):
    actor = auth.authenticate(ALL_ROLES)
    order = store.repair_orders.get(order_id)
    auth.own_order(actor, order)
    order = guards.find_order(order_id)
    return response.ok(serialize.repair_order(order))


@bp.route("/repair-orders", methods=["GET"])
def list_repair_orders():
    auth.authenticate(("ShopAdmin", "Estimator", "PartsManager"))
    stage = validate.enum_filter(request.args, "stage", guards.STAGES)
    limit, offset = response.read_pagination(request.args)
    customer_id = request.args.get("customer_id")
    insurer_id = request.args.get("insurer_id")
    if customer_id is not None and customer_id not in store.customers:
        raise_error("ERR_CUSTOMER_NOT_FOUND")
    if insurer_id is not None and insurer_id not in store.insurers:
        raise_error("ERR_INSURER_NOT_FOUND")
    rows = db.in_creation_order(list(store.repair_orders.values()))
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if insurer_id is not None:
        rows = [r for r in rows if r["insurer_id"] == insurer_id]
    if stage is not None:
        rows = [r for r in rows if r["stage"] == stage]
    return response.paginate(rows, limit, offset, serialize.repair_order)


# --- teardown --------------------------------------------------------------------------
FINDING_SPEC = [
    F("panel_code", "string", required=True),
    F("severity", "string", required=True, enum=SEVERITIES),
    F("requires_blend", "boolean", default=False),
    F("adas_component_touched", "boolean", default=False),
    F("structural", "boolean", default=False),
]


@bp.route("/repair-orders/<order_id>/teardown-findings", methods=["POST"])
def create_teardown_finding(order_id):
    auth.authenticate(("Estimator",))
    data = validate.body(FINDING_SPEC)
    order = guards.find_order(order_id)
    guards.not_terminal(order)

    bumper = calc.Bumper()
    if order["stage"] == "INTAKE":
        order["stage"] = "TEARDOWN"
    row = db.base_row(mutable=False)
    row.update({
        "repair_order_id": order["id"],
        "panel_code": data["panel_code"],
        "severity": data["severity"],
        "requires_blend": bool(data["requires_blend"]),
        "adas_component_touched": bool(data["adas_component_touched"]),
        "structural": bool(data["structural"]),
        "discovered_at_stage": order["stage"],
    })
    store.damage_lines[row["id"]] = row
    calc.recount_teardown_findings(order)
    bumper.add(order)
    bumper.flush()
    return response.created(serialize.damage_line(row))


@bp.route("/repair-orders/<order_id>/damage-lines", methods=["GET"])
def list_damage_lines(order_id):
    auth.authenticate(("ShopAdmin", "Estimator", "Technician"))
    limit, offset = response.read_pagination(request.args)
    order = guards.find_order(order_id)
    rows = calc.order_damage_lines(order["id"])
    return response.paginate(rows, limit, offset, serialize.damage_line)


@bp.route("/repair-orders/<order_id>/blueprint", methods=["POST"])
def publish_blueprint(order_id):
    actor = auth.authenticate(("Estimator",))
    validate.body([])
    order = guards.find_order(order_id)
    guards.not_terminal(order)
    guards.stage_in(order, ("INTAKE", "TEARDOWN"))

    findings = calc.order_damage_lines(order["id"])
    if any(f["adas_component_touched"] for f in findings):
        records = calc.order_procedure_records(order["id"])
        if not any(r["operation_scope"] == "ADAS" and r["requires_calibration"]
                   for r in records):
            raise_error("ERR_ADAS_PROCEDURE_RESEARCH_MISSING")
    if int(order["teardown_finding_count"] or 0) < 1:
        raise_error("ERR_NO_TEARDOWN_FINDINGS")

    bumper = calc.Bumper()
    order["stage"] = "BLUEPRINTED"
    order["blueprint_by_user_id"] = actor.user_id
    calc.refinish_allocation(order, "PROVISIONAL", bumper)
    calc.derive_posture(order)
    bumper.add(order)
    bumper.flush()
    return response.ok(serialize.repair_order(order))


@bp.route("/repair-orders/<order_id>/estimate/lock", methods=["POST"])
def lock_estimate(order_id):
    auth.authenticate(("Estimator",))
    validate.body([])
    order = guards.find_order(order_id)
    guards.not_terminal(order)
    guards.stage_in(order, ("BLUEPRINTED",))

    lines = calc.order_estimate_lines(order["id"])
    drafts = [l for l in lines if l["line_status"] == "DRAFT"]
    for line in drafts:
        if line["not_included_operation"] and not (line.get("justification_note") or ""):
            raise_error("ERR_NOT_INCLUDED_JUSTIFICATION_MISSING")
    if not drafts:
        raise_error("ERR_NO_ESTIMATE_LINES")

    bumper = calc.Bumper()
    for line in drafts:
        line["line_status"] = "APPROVED"
        bumper.add(line)
    order["stage"] = "ESTIMATE_LOCKED"
    calc.apply_non_refinish_hours(order, bumper)
    calc.refinish_allocation(order, "FINAL", bumper)
    calc.approved_hours_rollup(order)
    calc.estimate_totals(order, bumper)
    calc.derive_posture(order)
    bumper.add(order)
    bumper.flush()
    return response.ok(serialize.repair_order(order))


TOTAL_LOSS_SPEC = [F("total_loss_note", "string", required=True)]


@bp.route("/repair-orders/<order_id>/total-loss", methods=["POST"])
def declare_total_loss(order_id):
    auth.authenticate(("Estimator",))
    data = validate.body(TOTAL_LOSS_SPEC)
    order = guards.find_order(order_id)
    guards.not_terminal(order)
    guards.stage_in(order, ("BLUEPRINTED",))

    bumper = calc.Bumper()
    for line in calc.order_estimate_lines(order["id"]):
        if line["line_status"] in ("DRAFT", "PENDING_SUPPLEMENT"):
            line["line_status"] = "VOID"
            bumper.add(line)
    for parts_line in calc.order_parts_lines(order["id"]):
        if parts_line["procurement_status"] in ("PLANNED", "QUOTED", "COUNTERED",
                                               "PRICE_LOCKED"):
            parts_line["procurement_status"] = "VOID"
            parts_line["extended_price_cents"] = 0
            bumper.add(parts_line)

    order["stage"] = "TOTAL_LOSS"
    order["total_loss_note"] = data["total_loss_note"]
    calc.approved_hours_rollup(order)
    calc.commitment_ledger(order)
    calc.estimate_totals(order, bumper)
    calc.derive_posture(order)
    guards.release_assignments(order, ("SCHEDULED", "ACTIVE"), "CANCELLED", bumper)
    bumper.add(order)
    bumper.flush()
    return response.ok(serialize.repair_order(order))


# --- quality control, delivery, cycle time ---------------------------------------------
QC_SPEC = [
    F("checklist_passed", "boolean", required=True),
    F("post_scan_dtc_count", "integer", required=True),
    F("scan_report_ref", "string"),
]


@bp.route("/repair-orders/<order_id>/qc-inspections", methods=["POST"])
def create_qc_inspection(order_id):
    actor = auth.authenticate(("QcInspector",))
    order = store.repair_orders.get(order_id)
    auth.segregation(actor, order)
    data = validate.body(QC_SPEC)
    validate.require(data["post_scan_dtc_count"] >= 0,
                     "post_scan_dtc_count must be >= 0.")
    order = guards.find_order(order_id)
    guards.not_terminal(order)
    guards.stage_in(order, ("READY_FOR_QC",))

    records = calc.order_procedure_records(order["id"])
    for record in records:
        if record["requires_calibration"] and record["calibration_status"] != "PASSED":
            raise_error("ERR_CALIBRATION_NOT_VERIFIED")
    for record in records:
        if not record["adherence_documented"]:
            raise_error("ERR_PROCEDURE_ADHERENCE_MISSING")
    for parts_line in calc.order_parts_lines(order["id"]):
        if parts_line["procurement_status"] in ("ORDERED", "RECEIVED"):
            raise_error("ERR_PARTS_NOT_INSTALLED")

    bumper = calc.Bumper()
    passed = bool(data["checklist_passed"]) and int(data["post_scan_dtc_count"]) == 0
    sequence_number = int(order["qc_inspection_count"] or 0) + 1
    row = db.base_row()
    row.update({
        "repair_order_id": order["id"],
        "inspector_user_id": actor.user_id,
        "sequence_number": sequence_number,
        "checklist_passed": bool(data["checklist_passed"]),
        "post_scan_dtc_count": data["post_scan_dtc_count"],
        "scan_report_ref": data["scan_report_ref"],
        "result": "PASS" if passed else "FAIL",
        "failure_reason": None,
        "warranty_certificate_number": None,
        "warranty_expires_at": None,
    })
    if passed:
        row["warranty_certificate_number"] = "WC-%s-%d" % (order["claim_number"],
                                                           sequence_number)
        row["warranty_expires_at"] = db.iso(db.plus_days(db.now(), calc.WARRANTY_DAYS))
    else:
        row["failure_reason"] = "CHECKLIST" if not data["checklist_passed"] else "DTC_PRESENT"
        order["stage"] = "QC_FAILED"
    store.qc_inspections[row["id"]] = row
    calc.recount_qc_inspections(order)
    bumper.add(order)
    bumper.flush()
    return response.created(serialize.qc_inspection(row))


@bp.route("/repair-orders/<order_id>/qc-inspections", methods=["GET"])
def list_qc_inspections(order_id):
    actor = auth.authenticate(("ShopAdmin", "QcInspector", "InsurerAdjuster"))
    order = store.repair_orders.get(order_id)
    auth.own_order(actor, order)
    limit, offset = response.read_pagination(request.args)
    order = guards.find_order(order_id)
    rows = sorted(calc.order_qc_inspections(order["id"]),
                  key=lambda r: (r["sequence_number"], r["_seq"]))
    return response.paginate(rows, limit, offset, serialize.qc_inspection)


@bp.route("/repair-orders/<order_id>/cycle-time", methods=["GET"])
def read_cycle_time(order_id):
    auth.authenticate(("ShopAdmin", "Estimator"))
    order = guards.find_order(order_id)
    return response.ok(calc.cycle_time(order))


@bp.route("/repair-orders/<order_id>/deliver", methods=["POST"])
def deliver_vehicle(order_id):
    auth.authenticate(("ShopAdmin",))
    validate.body([])
    order = guards.find_order(order_id)
    guards.not_terminal(order)
    guards.stage_in(order, ("READY_FOR_QC",))
    guards.posture_open(order)

    latest = guards.latest_inspection(order)
    if latest is None or latest["result"] != "PASS":
        raise_error("ERR_QC_NOT_PASSED")
    if int(order["open_parts_delay_count"] or 0) != 0:
        raise_error("ERR_OPEN_PARTS_DELAY")

    bumper = calc.Bumper()
    order["stage"] = "DELIVERED"
    order["delivered_at"] = db.now_iso()
    guards.release_assignments(order, ("SCHEDULED", "ACTIVE"), "COMPLETED", bumper)
    bumper.add(order)
    bumper.flush()
    return response.ok(serialize.repair_order(order))
