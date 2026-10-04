"""PartRequisition: demand a part on an APPROVED workscope, and run the
sourcing selector (with the ContractManager-only lead-time override)."""
from flask import Blueprint

from authz import require_roles
from calc import select_sourcing_class
from envelope import success
from errors import api_err
from routes_visits import visit_engine
from routes_workscopes import get_workscope_or_404
from serialize import requisition_json
from storage import DB, new_id, next_seq, now, touch
from validate import as_datetime, as_enum, as_int, as_number, as_str, body, req_field

bp = Blueprint("parts", __name__)

SOURCING_CLASSES = {"NEW", "REPAIRED", "USM"}


def _requisition_agreement(requisition):
    workscope = DB["workscopes"][requisition["workscope_id"]]
    visit = DB["visits"][workscope["shop_visit_id"]]
    engine = visit_engine(visit)
    return DB["agreements"].get(engine["agreement_id"])


@bp.route("/api/workscopes/<workscope_id>/part-requisitions", methods=["POST"])
def create_requisition(workscope_id):
    require_roles("ShopPlanner")
    workscope = get_workscope_or_404(workscope_id)
    data = body()
    part_number = as_str(req_field(data, "part_number"), "part_number")
    quantity = as_int(req_field(data, "quantity"), "quantity")
    if quantity <= 0:
        raise api_err("ERR_INVALID_REQUEST", "quantity must be a positive integer")
    list_price = as_number(req_field(data, "list_price_usd"), "list_price_usd")
    if list_price <= 0:
        raise api_err("ERR_INVALID_REQUEST", "list_price_usd must be > 0")
    requested_class = as_enum(
        req_field(data, "requested_class"), "requested_class", SOURCING_CLASSES)
    required_by = as_datetime(req_field(data, "required_by_date"), "required_by_date")
    if workscope["status"] != "APPROVED":
        raise api_err("ERR_WORKSCOPE_NOT_APPROVED", "workscope is not APPROVED")
    ts = now()
    requisition = {
        "id": new_id(), "workscope_id": workscope_id, "part_number": part_number,
        "quantity": quantity, "list_price_usd": list_price,
        "requested_class": requested_class, "required_by_date": required_by,
        "sourced_class": None, "unit_cost_usd": None, "status": "REQUESTED",
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    DB["requisitions"][requisition["id"]] = requisition
    return success(requisition_json(requisition), 201)


@bp.route("/api/part-requisitions/<requisition_id>/source", methods=["POST"])
def source_requisition(requisition_id):
    uid, role = require_roles("ShopPlanner", "ContractManager")
    requisition = DB["requisitions"].get(requisition_id)
    if requisition is None:
        raise api_err("ERR_REQUISITION_NOT_FOUND", "part requisition does not exist")
    data = body()
    override = data.get("override", False)
    if not isinstance(override, bool):
        raise api_err("ERR_INVALID_REQUEST", "override must be a boolean")
    if override and role != "ContractManager":
        raise api_err("ERR_FORBIDDEN", "override is permitted only to a ContractManager")
    if requisition["status"] not in ("REQUESTED", "ESCALATED"):
        raise api_err("ERR_INVALID_STATE", "requisition is not REQUESTED or ESCALATED")
    agreement = _requisition_agreement(requisition)
    chosen, unit_cost = select_sourcing_class(requisition, agreement, override)
    if chosen is None:
        # No eligible class: REQUESTED -> ESCALATED, then reject.
        if requisition["status"] == "REQUESTED":
            requisition["status"] = "ESCALATED"
            touch(requisition)
        raise api_err("ERR_NO_ELIGIBLE_SOURCING_CLASS",
                      "no sourcing class passes the allowed list and lead-time eligibility")
    requisition["sourced_class"] = chosen
    requisition["unit_cost_usd"] = unit_cost
    requisition["status"] = "SOURCED"
    touch(requisition)
    return success(requisition_json(requisition), 200)
