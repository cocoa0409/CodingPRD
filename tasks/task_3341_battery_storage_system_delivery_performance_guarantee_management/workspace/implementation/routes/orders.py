"""SparePartOrder routes: create/list/get/ship/deliver/install/cancel."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles, ALL_ROLES
from pagination import paginate
from response import success_object, success_list
from routes.ltsas import lazy_expire
from util import new_id, stamp_new, touch, req_string, req_nonneg_int

bp = Blueprint("orders", __name__)


def serialize_order(o):
    return dict(o)


def get_order_or_404(oid):
    o = store.orders.get(oid)
    if o is None:
        raise ApiError("ERR_NOT_FOUND", 404, "SparePartOrder not found")
    return o


@bp.route("/spare-part-orders", methods=["POST"])
@require_roles({"ServiceManager", "ServiceEngineer"})
def create_order():
    body = request.get_json(silent=True) or {}
    sa_id = body.get("service_agreement_id")
    if not isinstance(sa_id, str) or sa_id not in store.service_agreements:
        raise ApiError("ERR_LTSA_NOT_FOUND", 404,
                       "service_agreement_id does not reference an existing ServiceAgreement")
    sa = store.service_agreements[sa_id]
    claim_id = body.get("warranty_claim_id")
    if claim_id is not None:
        if not isinstance(claim_id, str) or claim_id not in store.claims:
            raise ApiError("ERR_CLAIM_NOT_FOUND", 404,
                           "warranty_claim_id does not reference an existing WarrantyClaim")
    part_description = req_string(body, "part_description")
    part_cost = req_nonneg_int(body, "part_cost_cents")

    # OCC on the agreement version (after existence, before business checks)
    expected = body.get("expected_service_agreement_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "expected_service_agreement_version must be an integer")
        if expected != sa["version"]:
            raise ApiError("ERR_STALE_LTSA_VERSION", 412,
                           "expected_service_agreement_version does not equal the ServiceAgreement's current version")

    lazy_expire(sa)
    if sa["status"] != "ACTIVE":
        raise ApiError("ERR_LTSA_NOT_ACTIVE", 409, "Ordering requires an ACTIVE LTSA")

    covered = False
    if sa["covers_spare_parts"]:
        if sa["credit_pool_cents"] - sa["credit_drawn_cents"] >= part_cost:
            covered = True
            sa["credit_drawn_cents"] += part_cost
        else:
            raise ApiError("ERR_CREDIT_POOL_EXHAUSTED", 402,
                           "Part cost exceeds remaining credit pool; no partial coverage")

    o = {
        "id": new_id(),
        "service_agreement_id": sa_id,
        "warranty_claim_id": claim_id,
        "part_description": part_description,
        "part_cost_cents": part_cost,
        "covered_by_credit": covered,
        "status": "ORDERED",
    }
    stamp_new(o)
    store.orders[o["id"]] = o
    touch(sa)
    return success_object(serialize_order(o), 201)


@bp.route("/spare-part-orders", methods=["GET"])
@require_roles(set(ALL_ROLES))
def list_orders():
    sa_id = request.args.get("service_agreement_id")
    claim_id = request.args.get("warranty_claim_id")
    items = [o for o in store.orders.values()
             if (sa_id is None or o["service_agreement_id"] == sa_id)
             and (claim_id is None or o.get("warranty_claim_id") == claim_id)]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_order(o) for o in page], limit, offset, total)


@bp.route("/spare-part-orders/<oid>", methods=["GET"])
@require_roles(set(ALL_ROLES))
def get_order(oid):
    return success_object(serialize_order(get_order_or_404(oid)))


@bp.route("/spare-part-orders/<oid>/ship", methods=["POST"])
@require_roles({"ServiceEngineer"})
def ship_order(oid):
    o = get_order_or_404(oid)
    if o["status"] != "ORDERED":
        raise ApiError("ERR_ORDER_NOT_ORDERED", 409, "Ship requires ORDERED")
    o["status"] = "SHIPPED"
    touch(o)
    return success_object(serialize_order(o))


@bp.route("/spare-part-orders/<oid>/deliver", methods=["POST"])
@require_roles({"ServiceEngineer"})
def deliver_order(oid):
    o = get_order_or_404(oid)
    if o["status"] != "SHIPPED":
        raise ApiError("ERR_ORDER_NOT_SHIPPED", 409, "Deliver requires SHIPPED")
    o["status"] = "DELIVERED"
    touch(o)
    return success_object(serialize_order(o))


@bp.route("/spare-part-orders/<oid>/install", methods=["POST"])
@require_roles({"ServiceEngineer"})
def install_order(oid):
    o = get_order_or_404(oid)
    if o["status"] != "DELIVERED":
        raise ApiError("ERR_ORDER_NOT_DELIVERED", 409, "Install requires DELIVERED")
    claim = None
    if o.get("warranty_claim_id"):
        claim = store.claims.get(o["warranty_claim_id"])
        if claim is None or claim["status"] != "APPROVED":
            raise ApiError("ERR_CLAIM_NOT_FULFILLABLE", 409,
                           "Install with a linked claim requires the claim APPROVED")
    o["status"] = "INSTALLED"
    touch(o)
    if claim is not None:
        claim["status"] = "FULFILLED"
        touch(claim)
    return success_object(serialize_order(o))


@bp.route("/spare-part-orders/<oid>/cancel", methods=["POST"])
@require_roles({"ServiceManager"})
def cancel_order(oid):
    o = get_order_or_404(oid)
    if o["status"] not in ("ORDERED", "SHIPPED"):
        raise ApiError("ERR_ORDER_NOT_CANCELLABLE", 409,
                       "Cancel requires ORDERED or SHIPPED")
    o["status"] = "CANCELLED"
    if o.get("covered_by_credit"):
        sa = store.service_agreements.get(o["service_agreement_id"])
        if sa is not None:
            sa["credit_drawn_cents"] -= o["part_cost_cents"]
            touch(sa)
    touch(o)
    return success_object(serialize_order(o))
