"""Labor lines: creation under the estimate or under a supplement, reads and lists."""
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

bp = Blueprint("estimate_lines", __name__)

LABOR_TYPES = calc.LABOR_TYPES
PAY_TYPES = ("INSURER", "CUSTOMER")
LINE_STATUSES = ("DRAFT", "PENDING_SUPPLEMENT", "APPROVED", "REJECTED", "VOID")

LINE_SPEC = [
    F("damage_line_id", "string", nullable=True),
    F("operation_code", "string", required=True),
    F("labor_type", "string", required=True, enum=LABOR_TYPES),
    F("guide_hours", "number", required=True),
    F("supplement_id", "string", nullable=True),
    F("not_included_operation", "boolean", default=False),
    F("justification_note", "string"),
    F("is_blend", "boolean", default=False),
    F("is_adjacent_panel", "boolean", default=False),
    F("two_stage", "boolean", default=False),
    F("pay_type", "string", enum=PAY_TYPES, default="INSURER"),
]

# stage order used only to decide whether the estimate is still open (PRD 3.4)
_STAGE_INDEX = dict((stage, index) for index, stage in enumerate(guards.STAGES))


def _past_blueprinted(order):
    return _STAGE_INDEX[order["stage"]] > _STAGE_INDEX["BLUEPRINTED"]


@bp.route("/repair-orders/<order_id>/estimate-lines", methods=["POST"])
def create_estimate_line(order_id):
    auth.authenticate(("Estimator",))
    data = validate.body(LINE_SPEC)
    validate.require(float(data["guide_hours"]) > 0, "guide_hours must be > 0.")
    validate.require(validate.at_most_one_decimal(data["guide_hours"]),
                     "guide_hours carries at most one decimal place.")
    order = guards.find_order(order_id)

    damage_line_id = data.get("damage_line_id")
    if damage_line_id is not None:
        finding = store.damage_lines.get(damage_line_id)
        if finding is None or finding["repair_order_id"] != order["id"]:
            raise_error("ERR_DAMAGE_LINE_NOT_FOUND")
    supplement_id = data.get("supplement_id")
    supplement = None
    if supplement_id is not None:
        supplement = store.supplements.get(supplement_id)
        if supplement is None or supplement["repair_order_id"] != order["id"]:
            raise_error("ERR_SUPPLEMENT_NOT_FOUND")

    guards.not_terminal(order)

    if _past_blueprinted(order):
        if supplement is None or supplement["status"] not in ("SUBMITTED", "INFO_REQUESTED"):
            raise_error("ERR_SUPPLEMENT_REQUIRED")

    bumper = calc.Bumper()
    row = db.base_row()
    row.update({
        "repair_order_id": order["id"],
        "damage_line_id": damage_line_id,
        "supplement_id": supplement_id,
        "operation_code": data["operation_code"],
        "labor_type": data["labor_type"],
        "guide_hours": data["guide_hours"],
        "not_included_operation": bool(data["not_included_operation"]),
        "justification_note": data["justification_note"],
        "is_blend": bool(data["is_blend"]),
        "is_adjacent_panel": bool(data["is_adjacent_panel"]),
        "two_stage": bool(data["two_stage"]),
        "pay_type": data["pay_type"],
        "allocated_hours": None,
        "effective_rate_cents": None,
        "line_amount_cents": None,
        "line_status": "PENDING_SUPPLEMENT" if supplement_id is not None else "DRAFT",
    })
    store.estimate_lines[row["id"]] = row
    calc.derive_posture(order)
    bumper.add(order)
    bumper.flush()
    return response.created(serialize.estimate_line(row))


@bp.route("/estimate-lines/<line_id>", methods=["GET"])
def read_estimate_line(line_id):
    actor = auth.authenticate(("Estimator", "PartsManager", "InsurerAdjuster"))
    line = store.estimate_lines.get(line_id)
    if line is not None:
        auth.own_order(actor, store.repair_orders.get(line["repair_order_id"]))
    if line is None:
        raise_error("ERR_ESTIMATE_LINE_NOT_FOUND")
    return response.ok(serialize.estimate_line(line))


@bp.route("/estimate-lines", methods=["GET"])
def list_estimate_lines():
    actor = auth.authenticate(("Estimator", "PartsManager", "InsurerAdjuster"))
    order_id = request.args.get("repair_order_id")
    if order_id is not None and actor.entity_backed:
        auth.own_order(actor, store.repair_orders.get(order_id))
    line_status = validate.enum_filter(request.args, "line_status", LINE_STATUSES)
    limit, offset = response.read_pagination(request.args)

    damage_line_id = request.args.get("damage_line_id")
    if damage_line_id is not None and damage_line_id not in store.damage_lines:
        raise_error("ERR_DAMAGE_LINE_NOT_FOUND")
    supplement_id = request.args.get("supplement_id")
    if supplement_id is not None and supplement_id not in store.supplements:
        raise_error("ERR_SUPPLEMENT_NOT_FOUND")

    rows = db.in_creation_order(list(store.estimate_lines.values()))
    if order_id is not None:
        rows = [r for r in rows if r["repair_order_id"] == order_id]
    if damage_line_id is not None:
        rows = [r for r in rows if r["damage_line_id"] == damage_line_id]
    if supplement_id is not None:
        rows = [r for r in rows if r["supplement_id"] == supplement_id]
    if line_status is not None:
        rows = [r for r in rows if r["line_status"] == line_status]
    if actor.entity_backed:
        rows = [r for r in rows
                if auth.owns(actor, store.repair_orders.get(r["repair_order_id"]))]
    return response.paginate(rows, limit, offset, serialize.estimate_line)
