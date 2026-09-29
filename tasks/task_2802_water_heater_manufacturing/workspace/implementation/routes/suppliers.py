"""Supplier qualification and incoming component control (PRD 3.1)."""

from flask import Blueprint

import db
import response
import serializers
import validation
from db import make_row, ordered, touch
from errors import ApiError
from middleware import actor_id, is_supplier_rep
from middleware import endpoint
from services import calc
from services.core import cascade_supplier_disqualification, require_unique, resolve, rows

bp = Blueprint("suppliers", __name__)

COMPONENT_CATEGORIES = (
    "GAS_VALVE",
    "THERMOSTAT",
    "TP_RELIEF_VALVE",
    "ANODE",
    "COMPRESSOR",
    "ECO_SWITCH",
)
QUALIFICATION_STATUSES = ("PENDING", "QUALIFIED", "CONDITIONAL", "DISQUALIFIED")
LOT_STATUSES = ("QUARANTINED", "RELEASED", "BLOCKED", "REJECTED", "CONSUMED")

READ_ROLES = [
    "SupplierQualityManager",
    "QualityInspector",
    "PlantAdmin",
    "PlantOperator",
    "SupplierRep",
]
LIST_ROLES = ["SupplierQualityManager", "QualityInspector", "PlantAdmin", "PlantOperator"]
LOT_READ_ROLES = [
    "SupplierQualityManager",
    "QualityInspector",
    "PlantOperator",
    "PlantAdmin",
    "SupplierRep",
]


# --------------------------------------------------------------------------
# Suppliers
# --------------------------------------------------------------------------

@bp.post("/suppliers")
@endpoint(["SupplierQualityManager"])
def create_supplier():
    body = validation.json_body()
    name = validation.string(body, "name", max_length=120)
    category = validation.enum(body, "component_category", COMPONENT_CATEGORIES)
    audit_score = validation.number(body, "audit_score", minimum=0, maximum=100)
    defect_ppm = validation.integer(body, "defect_ppm", minimum=0)
    open_capa_count = validation.integer(body, "open_capa_count", minimum=0)

    row = make_row(
        {
            "name": name,
            "component_category": category,
            "audit_score": audit_score,
            "defect_ppm": defect_ppm,
            "open_capa_count": open_capa_count,
            "qualification_score": None,
            "qualification_status": "PENDING",
            "qualified_until": None,
            "disqualification_reason_code": None,
        }
    )
    db.db.suppliers[row["id"]] = row
    return response.created(serializers.supplier(row))


@bp.get("/suppliers/<sid>")
@endpoint(READ_ROLES)
def read_supplier(sid):
    row = resolve("supplier", sid)
    if is_supplier_rep() and row["id"] != actor_id():
        raise ApiError("ERR_SUPPLIER_SCOPE_VIOLATION")
    return response.ok(serializers.supplier(row))


@bp.get("/suppliers")
@endpoint(LIST_ROLES)
def list_suppliers():
    status = validation.query_enum("qualification_status", QUALIFICATION_STATUSES)
    category = validation.query_enum("component_category", COMPONENT_CATEGORIES)
    result = rows("supplier")
    if status is not None:
        result = [r for r in result if r["qualification_status"] == status]
    if category is not None:
        result = [r for r in result if r["component_category"] == category]
    return response.paginate(ordered(result), serializers.supplier)


@bp.post("/suppliers/<sid>/qualify")
@endpoint(["SupplierQualityManager"])
def qualify_supplier(sid):
    supplier = resolve("supplier", sid)
    body = validation.json_body()
    audit_score = validation.number(body, "audit_score", minimum=0, maximum=100)
    defect_ppm = validation.integer(body, "defect_ppm", minimum=0)
    open_capa_count = validation.integer(body, "open_capa_count", minimum=0)
    qualified_until = validation.timestamp(body, "qualified_until")
    if qualified_until <= db.db.now():
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'qualified_until' must be strictly after the current logical clock.",
        )

    # Ladder position 8: only PENDING, QUALIFIED and CONDITIONAL declare a scoring move.
    if supplier["qualification_status"] not in ("PENDING", "QUALIFIED", "CONDITIONAL"):
        raise ApiError("ERR_INVALID_SUPPLIER_STATE")

    # Ladder position 28: the score floor.
    score = calc.supplier_qualification_score(audit_score, defect_ppm, open_capa_count)
    band = calc.supplier_band(score)
    if band is None:
        raise ApiError("ERR_SUPPLIER_SCORE_BELOW_FLOOR")

    # There is deliberately no self-transition on either band.
    if band == supplier["qualification_status"]:
        raise ApiError("ERR_INVALID_SUPPLIER_STATE")

    # Ladder position 33: containment must be cleared on the way out of PENDING.
    if supplier["qualification_status"] == "PENDING":
        if serializers.blocked_lot_count(supplier["id"]) != 0:
            raise ApiError("ERR_BLOCKED_LOTS_REMAIN")

    supplier["audit_score"] = audit_score
    supplier["defect_ppm"] = defect_ppm
    supplier["open_capa_count"] = open_capa_count
    supplier["qualification_score"] = score
    supplier["qualified_until"] = qualified_until
    supplier["qualification_status"] = band
    supplier["disqualification_reason_code"] = None
    touch(supplier)
    return response.ok(serializers.supplier(supplier))


@bp.post("/suppliers/<sid>/disqualify")
@endpoint(["SupplierQualityManager"])
def disqualify_supplier(sid):
    supplier = resolve("supplier", sid)
    body = validation.json_body()
    reason_code = validation.string(body, "reason_code")

    if supplier["qualification_status"] not in ("QUALIFIED", "CONDITIONAL"):
        raise ApiError("ERR_INVALID_SUPPLIER_STATE")

    supplier["qualification_status"] = "DISQUALIFIED"
    supplier["disqualification_reason_code"] = reason_code
    supplier["qualified_until"] = None
    touch(supplier)
    cascade_supplier_disqualification(supplier)
    return response.ok(serializers.supplier(supplier))


@bp.post("/suppliers/<sid>/requalify")
@endpoint(["SupplierQualityManager"])
def requalify_supplier(sid):
    supplier = resolve("supplier", sid)
    body = validation.json_body()
    validation.string(body, "reason_code")

    if supplier["qualification_status"] != "DISQUALIFIED":
        raise ApiError("ERR_INVALID_SUPPLIER_STATE")

    supplier["qualification_status"] = "PENDING"
    supplier["disqualification_reason_code"] = None
    supplier["qualification_score"] = None
    touch(supplier)
    return response.ok(serializers.supplier(supplier))


# --------------------------------------------------------------------------
# Component lots
# --------------------------------------------------------------------------

@bp.post("/component-lots")
@endpoint(["SupplierQualityManager", "QualityInspector"])
def create_component_lot():
    body = validation.json_body()
    supplier_id = validation.string(body, "supplier_id")
    part_number = validation.string(body, "part_number", max_length=40)
    category = validation.enum(body, "category", COMPONENT_CATEGORIES)
    quantity = validation.integer(body, "quantity", minimum=1)
    coc = validation.boolean(body, "certificate_of_conformance", required=False, default=False)

    supplier = resolve("supplier", supplier_id)
    require_unique(
        "component_lot",
        "part_number",
        part_number,
        scope=("supplier_id", supplier["id"]),
    )

    row = make_row(
        {
            "supplier_id": supplier["id"],
            "part_number": part_number,
            "category": category,
            "quantity": quantity,
            "certificate_of_conformance": coc,
            "status": "QUARANTINED",
            "reject_reason_code": None,
        }
    )
    db.db.component_lots[row["id"]] = row
    return response.created(serializers.component_lot(row))


@bp.get("/component-lots/<lid>")
@endpoint(LOT_READ_ROLES)
def read_component_lot(lid):
    lot = resolve("component_lot", lid)
    if is_supplier_rep() and lot["supplier_id"] != actor_id():
        raise ApiError("ERR_SUPPLIER_SCOPE_VIOLATION")
    return response.ok(serializers.component_lot(lot))


@bp.get("/component-lots")
@endpoint(LOT_READ_ROLES)
def list_component_lots():
    supplier_filter = validation.query_string("supplier_id")
    category = validation.query_enum("category", COMPONENT_CATEGORIES)
    status = validation.query_enum("status", LOT_STATUSES)

    if is_supplier_rep():
        if supplier_filter is not None and supplier_filter != actor_id():
            raise ApiError("ERR_SUPPLIER_SCOPE_VIOLATION")
        supplier_filter = actor_id()

    result = rows("component_lot")
    if supplier_filter is not None:
        result = [r for r in result if r["supplier_id"] == supplier_filter]
    if category is not None:
        result = [r for r in result if r["category"] == category]
    if status is not None:
        result = [r for r in result if r["status"] == status]
    return response.paginate(ordered(result), serializers.component_lot)


@bp.post("/component-lots/<lid>/release")
@endpoint(["QualityInspector"])
def release_component_lot(lid):
    lot = resolve("component_lot", lid)
    if lot["status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_COMPONENT_LOT_STATE")
    if not lot["certificate_of_conformance"]:
        raise ApiError(
            "ERR_INVALID_COMPONENT_LOT_STATE",
            "The lot carries no signed certificate of conformance.",
        )
    supplier = db.db.suppliers[lot["supplier_id"]]
    if supplier["qualification_status"] not in ("QUALIFIED", "CONDITIONAL"):
        raise ApiError("ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED")
    qualified_until = supplier.get("qualified_until")
    if qualified_until is None or qualified_until < db.db.now():
        raise ApiError("ERR_QUALIFICATION_EXPIRED")

    lot["status"] = "RELEASED"
    lot["reject_reason_code"] = None
    touch(lot)
    return response.ok(serializers.component_lot(lot))


@bp.post("/component-lots/<lid>/reject")
@endpoint(["QualityInspector"])
def reject_component_lot(lid):
    lot = resolve("component_lot", lid)
    body = validation.json_body()
    reason_code = validation.string(body, "reason_code")

    if lot["status"] not in ("QUARANTINED", "BLOCKED"):
        raise ApiError("ERR_INVALID_COMPONENT_LOT_STATE")

    was_blocked = lot["status"] == "BLOCKED"
    lot["status"] = "REJECTED"
    lot["reject_reason_code"] = reason_code
    touch(lot)
    if was_blocked:
        # Clearing containment recomputes the supplier's blocked_lot_count.
        supplier = db.db.suppliers.get(lot["supplier_id"])
        if supplier is not None:
            touch(supplier)
    return response.ok(serializers.component_lot(lot))


@bp.post("/component-lots/<lid>/unblock")
@endpoint(["SupplierQualityManager"])
def unblock_component_lot(lid):
    lot = resolve("component_lot", lid)
    if lot["status"] != "BLOCKED":
        raise ApiError("ERR_INVALID_COMPONENT_LOT_STATE")
    supplier = db.db.suppliers[lot["supplier_id"]]
    if supplier["qualification_status"] == "DISQUALIFIED":
        raise ApiError("ERR_COMPONENT_SUPPLIER_NOT_QUALIFIED")
    # The expiry check runs only for a QUALIFIED or CONDITIONAL supplier.
    if supplier["qualification_status"] in ("QUALIFIED", "CONDITIONAL"):
        qualified_until = supplier.get("qualified_until")
        if qualified_until is None or qualified_until < db.db.now():
            raise ApiError("ERR_QUALIFICATION_EXPIRED")

    lot["status"] = "RELEASED"
    lot["reject_reason_code"] = None
    touch(lot)
    return response.ok(serializers.component_lot(lot))
