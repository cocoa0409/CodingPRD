"""BeefDelivery routes: schedule, ship, confirm-receiving, reject-receiving."""

from flask import Blueprint, request

import db
import services.calculations as calc
import services.domain as domain
from errors import (
    ERR_COLD_CHAIN_VIOLATION,
    ERR_DELIVERY_INVALID_STATE,
    ERR_SUPPLIER_AUDIT_STALE,
    ERR_SUPPLIER_NOT_APPROVED,
    conflict,
    invalid_request,
    unprocessable,
)
from middleware import require_roles
from response import success_list, success_object
from util import (
    base_entity,
    get_json_body,
    paginate,
    parse_datetime,
    req_field,
    req_number,
    req_string,
    touch,
)

bp = Blueprint("beef_deliveries", __name__)


@bp.route("/beef-deliveries", methods=["POST"])
def create_beef_delivery():
    require_roles("CommissaryPlanner")
    body = get_json_body()
    # Shape (tier 6).
    commissary_id = req_string(body, "commissary_id")
    supplier_id = req_string(body, "supplier_id")
    shipped_at = parse_datetime(req_field(body, "shipped_at"), "shipped_at")
    raw_beef_lbs = req_number(body, "raw_beef_lbs")
    transit_temp_celsius = req_number(body, "transit_temp_celsius")
    # Body FK existence (tier 5).
    commissary = domain.get_commissary(commissary_id)
    supplier = domain.get_supplier(supplier_id)
    # Dedicated processing (tier 12): delivery supplier must be the commissary's own.
    from errors import linkage
    if supplier["id"] != commissary["supplier_id"]:
        raise linkage("supplier_id must equal the commissary's dedicated supplier")
    d = base_entity()
    d.update({
        "commissary_id": commissary["id"],
        "supplier_id": supplier["id"],
        "shipped_at": shipped_at,
        "raw_beef_lbs": raw_beef_lbs,
        "transit_temp_celsius": transit_temp_celsius,
        "status": "SCHEDULED",
    })
    db.beef_deliveries[d["id"]] = d
    return success_object(domain.ser_beef_delivery(d), 201)


@bp.route("/commissaries/<cid>/beef-deliveries", methods=["GET"])
def list_commissary_beef_deliveries(cid):
    require_roles("CommissaryPlanner", "SupplyChainDirector")
    c = domain.get_commissary(cid)
    items = [d for d in db.beef_deliveries.values() if d["commissary_id"] == c["id"]]
    sid = request.args.get("supplier_id")
    if sid is not None:
        items = [d for d in items if d["supplier_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_beef_delivery(d) for d in page], limit, offset, total)


@bp.route("/beef-deliveries/<did>", methods=["GET"])
def get_beef_delivery(did):
    require_roles("CommissaryPlanner", "SupplyChainDirector")
    return success_object(domain.ser_beef_delivery(domain.get_beef_delivery(did)))


@bp.route("/beef-deliveries", methods=["GET"])
def list_beef_deliveries():
    require_roles("CommissaryPlanner", "SupplyChainDirector")
    items = list(db.beef_deliveries.values())
    sid = request.args.get("supplier_id")
    if sid is not None:
        items = [d for d in items if d["supplier_id"] == sid]
    cid = request.args.get("commissary_id")
    if cid is not None:
        items = [d for d in items if d["commissary_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_beef_delivery(d) for d in page], limit, offset, total)


def _freshness_check(supplier):
    """Tier 10: audit freshness (inclusive boundary)."""
    if not calc.supplier_audit_fresh(supplier):
        raise unprocessable(ERR_SUPPLIER_AUDIT_STALE, "Latest PASS audit is stale")


def _approved_check(supplier):
    """Tier 11: supplier must be APPROVED."""
    if supplier["status"] != "APPROVED":
        raise unprocessable(ERR_SUPPLIER_NOT_APPROVED, "Supplier is not APPROVED")


@bp.route("/beef-deliveries/<did>/ship", methods=["POST"])
def ship_beef_delivery(did):
    require_roles("CommissaryPlanner")
    d = domain.get_beef_delivery(did)
    if d["status"] != "SCHEDULED":
        raise conflict(ERR_DELIVERY_INVALID_STATE, "Delivery must be SCHEDULED to ship")
    supplier = domain.get_supplier(d["supplier_id"])
    _freshness_check(supplier)
    _approved_check(supplier)
    d["status"] = "IN_TRANSIT"
    touch(d)
    return success_object(domain.ser_beef_delivery(d))


@bp.route("/beef-deliveries/<did>/confirm-receiving", methods=["POST"])
def confirm_receiving(did):
    require_roles("CommissaryPlanner")
    d = domain.get_beef_delivery(did)
    if d["status"] != "IN_TRANSIT":
        raise conflict(ERR_DELIVERY_INVALID_STATE, "Delivery must be IN_TRANSIT to confirm receipt")
    # Cold chain (tier 9): strictly greater than 4.0 violates.
    if d["transit_temp_celsius"] > calc.COLD_CHAIN_MAX_C:
        raise unprocessable(ERR_COLD_CHAIN_VIOLATION, "Transit temperature exceeds the cold-chain limit")
    supplier = domain.get_supplier(d["supplier_id"])
    _freshness_check(supplier)
    _approved_check(supplier)
    d["status"] = "RECEIVED"
    touch(d)
    commissary = db.commissaries.get(d["commissary_id"])
    if commissary is not None:
        commissary["raw_beef_lbs_on_hand"] += d["raw_beef_lbs"]
        touch(commissary)
    return success_object(domain.ser_beef_delivery(d))


@bp.route("/beef-deliveries/<did>/reject-receiving", methods=["POST"])
def reject_receiving(did):
    require_roles("CommissaryPlanner")
    d = domain.get_beef_delivery(did)
    if d["status"] not in ("SCHEDULED", "IN_TRANSIT"):
        raise conflict(ERR_DELIVERY_INVALID_STATE, "Delivery must be SCHEDULED or IN_TRANSIT to reject")
    d["status"] = "REJECTED"
    touch(d)
    return success_object(domain.ser_beef_delivery(d))
