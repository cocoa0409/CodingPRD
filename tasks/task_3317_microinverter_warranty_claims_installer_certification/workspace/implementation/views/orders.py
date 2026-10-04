"""Replacement order routes: manual creation, shipping, field installation,
cancellation and reactivation (PRD 3.7)."""

import db
import shapes
from approval import as_instant, as_int, as_str, body
from auth import (
    ROLE_INSTALLER,
    ROLE_PLATFORM_ADMIN,
    acting_installer,
    get_order,
    get_unit,
    require,
)
from errors import fail
from respond import ok, ok_list, paginate
from services import common
from services import orders as order_service

ORDER_MODELS = ("IQ7", "IQ8", "IQ8HC")


def create_order():
    """Manual replacement order; OCC-guarded against the target unit."""
    data = body()
    unit_id = as_str(data, "unit_id")
    replacement_model_code = as_str(data, "replacement_model_code")
    if replacement_model_code not in ORDER_MODELS:
        fail("ERR_INVALID_REQUEST_BODY",
             "field `replacement_model_code` must be one of %s"
             % ", ".join(ORDER_MODELS))
    expected_unit_version = as_int(data, "expected_unit_version")
    claim_id = as_str(data, "claim_id", required_=False)

    unit = db.DB.units.get(unit_id)
    if unit is None:
        fail("ERR_RESOURCE_NOT_FOUND", "unit %s does not exist" % unit_id)

    if expected_unit_version != int(unit.get("version", 0)):
        fail("ERR_STALE_UNIT_VERSION")

    if claim_id is not None and db.DB.claims.get(claim_id) is None:
        fail("ERR_RESOURCE_NOT_FOUND", "claim %s does not exist" % claim_id)

    compatibility_class = order_service.classify(
        unit.get("model_code"), replacement_model_code)
    if compatibility_class == "INCOMPATIBLE":
        fail("ERR_INCOMPATIBLE_REPLACEMENT")

    order_service.require_chargeable(unit["id"], claim_id, None, allow_sourceless=True)

    order = order_service.new_order(
        unit, replacement_model_code, compatibility_class, "PENDING_DISPATCH",
        claim_id=claim_id)

    common.set_many(unit, {"version": int(unit.get("version", 0)) + 1})
    common.recompute_unit(unit)
    return ok(shapes.replacement_order(order), 201)


def list_orders():
    from flask import request

    unit_id = request.args.get("unit_id")
    claim_id = request.args.get("claim_id")
    campaign_id = request.args.get("campaign_id")
    status = request.args.get("status")

    rows = list(db.DB.replacement_orders.values())
    if unit_id:
        rows = [o for o in rows if o.get("unit_id") == unit_id]
    if claim_id:
        rows = [o for o in rows if o.get("claim_id") == claim_id]
    if campaign_id:
        rows = [o for o in rows if o.get("campaign_id") == campaign_id]
    if status:
        rows = [o for o in rows if o.get("status") == status]
    rows = db.by_created_at(rows)
    window, meta = paginate(rows, request.args)
    return ok_list([shapes.replacement_order(o) for o in window], pagination=meta)


def read_order(order_id):
    order = get_order(order_id)
    return ok(shapes.replacement_order(order))


def dispatch_order(order_id):
    order = get_order(order_id)
    if order.get("status") != "PENDING_DISPATCH":
        fail("ERR_INVALID_STATE", "only a PENDING_DISPATCH order can be dispatched")
    order["status"] = "DISPATCHED"
    order["dispatched_at"] = common.now_iso()
    return ok(shapes.replacement_order(order))


def install_order(order_id):
    """Field installation: the order, the unit, and any source claim cascade."""
    data = body()
    replacement_serial_number = as_str(data, "replacement_serial_number")
    installed_at = as_instant(data, "installed_at")

    order = get_order(order_id)
    if order.get("status") != "DISPATCHED":
        fail("ERR_INVALID_STATE", "only a DISPATCHED order can be installed")

    unit = get_unit(order["unit_id"])
    system_id = unit.get("system_id")

    acting = acting_installer()
    if acting is None:
        fail("ERR_RESOURCE_NOT_FOUND", "the acting installer does not exist")
    common.require_commissioning_enabled(acting)

    if replacement_serial_number in order_service.serials_on_system(system_id):
        fail("ERR_REPLACEMENT_SERIAL_CONFLICT")

    order_service.install_order(order, replacement_serial_number, installed_at)

    common.recompute_unit(unit)
    if system_id:
        system = db.DB.systems.get(system_id)
        if system is not None:
            common.recompute_system(system)
            common.recompute_units_of_system(system_id)
    return ok(shapes.replacement_order(order))


def cancel_order(order_id):
    order = get_order(order_id)
    if order.get("status") not in ("PENDING_DISPATCH", "DISPATCHED"):
        fail("ERR_INVALID_STATE",
             "only a PENDING_DISPATCH or DISPATCHED order can be canceled")
    order["status"] = "CANCELED"
    if order.get("campaign_id"):
        campaign = db.DB.campaigns.get(order["campaign_id"])
        if campaign is not None:
            order_service.recompute_campaign_counts(campaign)
    unit = db.DB.units.get(order.get("unit_id"))
    if unit is not None:
        common.recompute_unit(unit)
    return ok(shapes.replacement_order(order))


def reactivate_order(order_id):
    order = get_order(order_id)
    if order.get("status") != "CANCELED":
        fail("ERR_INVALID_STATE", "only a CANCELED order can be reactivated")

    claim_ok = False
    if order.get("claim_id"):
        claim = db.DB.claims.get(order["claim_id"])
        claim_ok = claim is not None and claim.get("status") in (
            "APPROVED", "DISPATCHED", "REOPENED")

    campaign_ok = False
    if order.get("campaign_id"):
        campaign = db.DB.campaigns.get(order["campaign_id"])
        campaign_ok = campaign is not None and campaign.get("status") in (
            "DRAFT", "DISPATCHING", "CANCELED")

    if not claim_ok and not campaign_ok:
        fail("ERR_INVALID_STATE", "the order's source no longer admits reactivation")

    order["status"] = "PENDING_DISPATCH"
    order["dispatched_at"] = None
    order["installed_at"] = None
    if order.get("campaign_id"):
        campaign = db.DB.campaigns.get(order["campaign_id"])
        if campaign is not None:
            order_service.recompute_campaign_counts(campaign)
    unit = db.DB.units.get(order.get("unit_id"))
    if unit is not None:
        common.recompute_unit(unit)
    return ok(shapes.replacement_order(order))


def register(app):
    app.add_url_rule("/warranty/replacement-orders", "create_order",
                     require(ROLE_PLATFORM_ADMIN)(create_order), methods=["POST"])
    app.add_url_rule("/warranty/replacement-orders", "list_orders",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER)(list_orders),
                     methods=["GET"])
    app.add_url_rule("/warranty/replacement-orders/<order_id>", "read_order",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER)(read_order),
                     methods=["GET"])
    app.add_url_rule("/warranty/replacement-orders/<order_id>/dispatch", "dispatch_order",
                     require(ROLE_PLATFORM_ADMIN)(dispatch_order), methods=["POST"])
    app.add_url_rule("/warranty/replacement-orders/<order_id>/install", "install_order",
                     require(ROLE_INSTALLER)(install_order), methods=["POST"])
    app.add_url_rule("/warranty/replacement-orders/<order_id>/cancel", "cancel_order",
                     require(ROLE_PLATFORM_ADMIN)(cancel_order), methods=["POST"])
    app.add_url_rule("/warranty/replacement-orders/<order_id>/reactivate", "reactivate_order",
                     require(ROLE_PLATFORM_ADMIN)(reactivate_order), methods=["POST"])