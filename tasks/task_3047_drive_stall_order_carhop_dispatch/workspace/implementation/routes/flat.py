"""Flat alias reads and flat filtered lists (PRD 2.9)."""
from flask import request

from db import db
from errors import not_found, invalid_request
from middleware import require_auth, pagination_params, sort_by_created
from response import success_object, success_array
import serializers as ser
from . import flat_bp


def _get_or_404(store, rid, label):
    rec = store.get(rid)
    if rec is None:
        not_found("{} not found".format(label))
    return rec


def _list(records, serializer, filters):
    for key, val in filters.items():
        if val is not None:
            records = [r for r in records if r.get(key) == val]
    records = sort_by_created(records)
    limit, offset = pagination_params()
    total = len(records)
    page = records[offset : offset + limit]
    return success_array([serializer(r) for r in page], limit, offset, total)


# --- Flat alias reads ---

@flat_bp.route("/locations/stalls/<id>", methods=["GET"])
def flat_get_stall(id):
    require_auth(["ShiftManager", "Carhop", "KitchenStaff", "PlatformAdmin", "Customer"])
    return success_object(ser.stall(_get_or_404(db.stalls, id, "Stall")))


@flat_bp.route("/locations/carhops/<id>", methods=["GET"])
def flat_get_carhop(id):
    require_auth(["ShiftManager", "Carhop", "PlatformAdmin"])
    return success_object(ser.carhop(_get_or_404(db.carhops, id, "Carhop")))


@flat_bp.route("/locations/orders/<id>", methods=["GET"])
def flat_get_order(id):
    require_auth(["Customer", "ShiftManager", "Carhop", "KitchenStaff", "PlatformAdmin"])
    return success_object(ser.order(_get_or_404(db.orders, id, "Order")))


@flat_bp.route("/locations/offers/<id>", methods=["GET"])
def flat_get_offer(id):
    require_auth(["ShiftManager", "PlatformAdmin", "Customer"])
    return success_object(ser.offer(_get_or_404(db.offers, id, "Offer")))


@flat_bp.route("/locations/service-targets/<id>", methods=["GET"])
def flat_get_service_target(id):
    require_auth(["ShiftManager", "PlatformAdmin"])
    return success_object(
        ser.service_target_profile(
            _get_or_404(db.service_target_profiles, id, "ServiceTargetProfile")
        )
    )


@flat_bp.route("/locations/delivery-runs/<id>", methods=["GET"])
def flat_get_run(id):
    require_auth(["ShiftManager", "Carhop", "PlatformAdmin"])
    return success_object(ser.delivery_run(_get_or_404(db.delivery_runs, id, "DeliveryRun")))


@flat_bp.route("/locations/tip-records/<id>", methods=["GET"])
def flat_get_tip(id):
    require_auth(["ShiftManager", "Carhop", "PlatformAdmin"])
    return success_object(ser.tip_record(_get_or_404(db.tip_records, id, "TipRecord")))


@flat_bp.route("/locations/order-lines/<id>", methods=["GET"])
def flat_get_line(id):
    require_auth(["Customer", "ShiftManager", "Carhop", "KitchenStaff", "PlatformAdmin"])
    return success_object(ser.order_line(_get_or_404(db.order_lines, id, "OrderLine")))


@flat_bp.route("/locations/faults/<id>", methods=["GET"])
def flat_get_fault(id):
    require_auth(["Carhop", "ShiftManager", "PlatformAdmin"])
    return success_object(
        ser.equipment_fault(_get_or_404(db.equipment_faults, id, "EquipmentFault"))
    )


# --- Flat filtered lists ---

@flat_bp.route("/locations/stalls", methods=["GET"])
def flat_list_stalls():
    require_auth(["ShiftManager", "Carhop", "KitchenStaff", "PlatformAdmin", "Customer"])
    filters = {
        k: request.args.get(k)
        for k in ("location_id", "current_order_id", "status", "kind")
    }
    return _list(list(db.stalls.values()), ser.stall, filters)


@flat_bp.route("/locations/carhops", methods=["GET"])
def flat_list_carhops():
    require_auth(["ShiftManager", "Carhop", "PlatformAdmin"])
    filters = {k: request.args.get(k) for k in ("location_id", "zone")}
    on_shift_raw = request.args.get("on_shift")
    records = list(db.carhops.values())
    if on_shift_raw is not None:
        if on_shift_raw not in ("true", "false"):
            invalid_request("on_shift must be true or false")
        want = on_shift_raw == "true"
        records = [c for c in records if c["on_shift"] == want]
    return _list(records, ser.carhop, filters)


@flat_bp.route("/locations/orders", methods=["GET"])
def flat_list_orders():
    require_auth(["ShiftManager", "Carhop", "KitchenStaff", "PlatformAdmin"])
    filters = {
        k: request.args.get(k)
        for k in (
            "location_id",
            "stall_id",
            "customer_id",
            "delivery_run_id",
            "status",
            "channel",
            "payment_status",
        )
    }
    return _list(list(db.orders.values()), ser.order, filters)


@flat_bp.route("/locations/offers", methods=["GET"])
def flat_list_offers():
    require_auth(["ShiftManager", "PlatformAdmin", "Customer"])
    filters = {k: request.args.get(k) for k in ("location_id", "status", "kind")}
    return _list(list(db.offers.values()), ser.offer, filters)


@flat_bp.route("/locations/service-targets", methods=["GET"])
def flat_list_service_targets():
    require_auth(["ShiftManager", "PlatformAdmin"])
    filters = {k: request.args.get(k) for k in ("location_id", "channel", "status")}
    return _list(list(db.service_target_profiles.values()), ser.service_target_profile, filters)


@flat_bp.route("/locations/delivery-runs", methods=["GET"])
def flat_list_runs():
    require_auth(["ShiftManager", "Carhop", "PlatformAdmin"])
    filters = {k: request.args.get(k) for k in ("location_id", "carhop_id", "status")}
    return _list(list(db.delivery_runs.values()), ser.delivery_run, filters)


@flat_bp.route("/locations/tip-records", methods=["GET"])
def flat_list_tips():
    require_auth(["ShiftManager", "Carhop", "PlatformAdmin"])
    filters = {k: request.args.get(k) for k in ("order_id", "carhop_id", "status")}
    return _list(list(db.tip_records.values()), ser.tip_record, filters)


@flat_bp.route("/locations/order-lines", methods=["GET"])
def flat_list_lines():
    require_auth(["Customer", "ShiftManager", "Carhop", "KitchenStaff", "PlatformAdmin"])
    filters = {k: request.args.get(k) for k in ("order_id", "menu_item_id")}
    return _list(list(db.order_lines.values()), ser.order_line, filters)


@flat_bp.route("/locations/faults", methods=["GET"])
def flat_list_faults():
    require_auth(["Carhop", "ShiftManager", "PlatformAdmin"])
    filters = {k: request.args.get(k) for k in ("stall_id", "status")}
    return _list(list(db.equipment_faults.values()), ser.equipment_fault, filters)
