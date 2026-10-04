"""Compliance routes (PRD 3.8): court sealing/removal orders and their
retroactive apply/reverse cascades."""

from flask import Blueprint, request

from constants import ORDER_SCOPES, ORDER_STATUSES, ORDER_TARGET_STATUSES
from db import stamp_new, store
from errors import raise_err
from middleware import require_roles
from response import list_response, ok_object
from serializers import serialize_order
from services.compliance import apply_order, reverse_order
from util import get_body, opt_enum_query, opt_str, req_date, req_enum, req_str

bp = Blueprint("removal", __name__)

ORDER_READERS = ("ComplianceOfficer", "PlatformAdmin")


@bp.post("/legal-research/removal-orders")
@require_roles("ComplianceOfficer")
def create_order():
    body = get_body()
    document_id = req_str(body, "document_id")
    scope = req_enum(body, "scope", ORDER_SCOPES)
    effective_from = req_date(body, "effective_from")
    effective_until = req_date(body, "effective_until")
    reason = opt_str(body, "reason")
    if not (effective_from <= effective_until):
        raise_err("ERR_INVALID_REQUEST", "effective_from must be on or before effective_until")

    if document_id not in store.documents:
        raise_err("ERR_DOCUMENT_NOT_FOUND", "document %s does not exist" % document_id)

    # Closed-interval overlap among RECEIVED/APPLIED orders on the same
    # document: mere adjacency already counts as overlap.
    for other in store.orders.values():
        if other["document_id"] != document_id or other["status"] not in ("RECEIVED", "APPLIED"):
            continue
        if effective_from <= other["_effective_until"] and other["_effective_from"] <= effective_until:
            raise_err("ERR_REMOVAL_WINDOW_OVERLAP", "order window overlaps an existing order on the document")

    order = stamp_new({
        "document_id": document_id,
        "scope": scope,
        "effective_from": effective_from.isoformat(),
        "effective_until": effective_until.isoformat(),
        "_effective_from": effective_from,
        "_effective_until": effective_until,
        "reason": reason,
        "status": "RECEIVED",
    })
    store.orders[order["id"]] = order
    return ok_object(serialize_order(order), 201)


@bp.get("/legal-research/removal-orders")
@require_roles(*ORDER_READERS)
def list_orders():
    f_document = request.args.get("document_id")
    f_status = opt_enum_query("status", ORDER_STATUSES)

    rows = list(store.orders.values())
    if f_document is not None:
        rows = [o for o in rows if o["document_id"] == f_document]
    if f_status is not None:
        rows = [o for o in rows if o["status"] == f_status]
    return list_response(rows, serialize_order)


@bp.get("/legal-research/removal-orders/<order_id>")
@require_roles(*ORDER_READERS)
def get_order(order_id):
    order = store.orders.get(order_id)
    if order is None:
        raise_err("ERR_ORDER_NOT_FOUND", "removal order %s does not exist" % order_id)
    return ok_object(serialize_order(order))


@bp.post("/legal-research/removal-orders/<order_id>/transition")
@require_roles("ComplianceOfficer")
def transition_order(order_id):
    body = get_body()
    target = req_enum(body, "target_status", ORDER_TARGET_STATUSES)

    order = store.orders.get(order_id)
    if order is None:
        raise_err("ERR_ORDER_NOT_FOUND", "removal order %s does not exist" % order_id)

    if target == "APPLIED":
        if order["status"] != "RECEIVED":
            raise_err("ERR_INVALID_STATE", "order %s cannot be applied from %s" % (order_id, order["status"]))
        # An order may not be applied before its window opens.
        if store.clock.date() < order["_effective_from"]:
            raise_err("ERR_INVALID_STATE", "order %s is not yet effective" % order_id)
        doc = store.documents[order["document_id"]]
        if doc["visibility_status"] != "PUBLIC":
            raise_err("ERR_INVALID_STATE", "document %s is no longer public" % doc["id"])
        apply_order(order)
    else:  # REVERSED
        if order["status"] != "APPLIED":
            raise_err("ERR_INVALID_STATE", "order %s cannot be reversed from %s" % (order_id, order["status"]))
        reverse_order(order)

    return ok_object(serialize_order(order), 200)
