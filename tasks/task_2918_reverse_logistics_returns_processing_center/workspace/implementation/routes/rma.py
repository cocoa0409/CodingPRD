"""Return authorizations and their declared lines."""

from flask import Blueprint

import aggregates
import constants as K
import db
import middleware as mw
import query
import refs
import response
import serialize
import services
import shapes
from errors import ApiError

bp = Blueprint("rma", __name__)


def _check_expiry_window(order_placed_at, expires_at):
    """Priority 41 — expiry strictly in the future, placement no later than now."""
    now = db.now()
    if expires_at <= now:
        raise ApiError("ERR_RMA_EXPIRES_IN_PAST")
    if order_placed_at > now:
        raise ApiError("ERR_RMA_EXPIRES_IN_PAST", "Field 'order_placed_at' is in the future.")


@bp.post("/return-authorizations")
def create_rma():
    user_id, role = mw.require("CenterAdmin", "ClientRep")
    peek = response.raw_body_json()
    mw.scope_peek(role, user_id, peek.get("client_id"))
    body = response.body_json()
    client_id = shapes.req_id(body, "client_id")
    order_reference = shapes.req_str(body, "order_reference")
    customer_reference = shapes.req_str(body, "customer_reference")
    order_placed_at = shapes.req_instant(body, "order_placed_at")
    expires_at = shapes.req_instant(body, "expires_at")
    client = services.must_client(client_id)
    mw.scope(role, user_id, client["id"])
    services.require_active(client)
    _check_expiry_window(order_placed_at, expires_at)
    row = {
        "id": db.new_id(),
        "client_id": client_id,
        "order_reference": order_reference,
        "customer_reference": customer_reference,
        "order_placed_at": db.fmt_instant(order_placed_at),
        "expires_at": db.fmt_instant(expires_at),
        "supersedes_rma_id": None,
        "status": "DRAFT",
        "issued_at": None,
    }
    db.stamp_new(row)
    db.insert("rmas", row)
    return response.created(serialize.rma(row))


@bp.get("/return-authorizations/<rma_id>")
def get_rma(rma_id):
    user_id, role = mw.require(
        "CenterAdmin",
        "ReceivingClerk",
        "GradingInspector",
        "DispositionSupervisor",
        "RefundAnalyst",
        "ClientRep",
    )
    rma = db.get("rmas", rma_id)
    if rma is not None:
        mw.scope(role, user_id, rma["client_id"])
    rma = services.must_rma(rma_id)
    return response.ok(serialize.rma(rma))


@bp.get("/return-authorizations")
def list_rmas():
    user_id, role = mw.require(
        "CenterAdmin", "ReceivingClerk", "DispositionSupervisor", "RefundAnalyst", "ClientRep"
    )
    client_id = query.arg("client_id")
    if client_id is not None:
        services.must_client(client_id)
    if role == mw.CLIENT_REP:
        client_id = user_id
    rows = db.sorted_rows(db.all_rows("rmas"))
    rows = query.eq(rows, "client_id", client_id)
    rows = query.eq(rows, "status", query.arg("status"))
    rows = query.eq(rows, "customer_reference", query.arg("customer_reference"))
    rows = query.eq(rows, "supersedes_rma_id", query.arg("supersedes_rma_id"))
    return response.paginate(rows, serialize.rma)


@bp.post("/return-authorizations/<rma_id>/lines")
def declare_line(rma_id):
    user_id, role = mw.require("CenterAdmin", "ClientRep")
    pending = db.get("rmas", rma_id)
    if pending is not None:
        mw.scope(role, user_id, pending["client_id"])
    body = response.body_json()
    catalog_item_id = shapes.req_id(body, "catalog_item_id")
    authorized_quantity = shapes.req_int(body, "authorized_quantity", 1, 999)
    reason_code = shapes.req_enum(body, "reason_code", K.REASON_CODES)
    declared_serial = shapes.opt_str(body, "declared_serial")
    item = services.must_item(catalog_item_id)
    rma = services.must_rma(rma_id)
    mw.scope(role, user_id, item["client_id"])
    if item["client_id"] != rma["client_id"]:
        raise ApiError("ERR_LINE_RMA_MISMATCH")
    client = services.must_client(rma["client_id"])
    services.require_active(client)
    if rma["status"] != "DRAFT":
        raise ApiError("ERR_RMA_INVALID_STATE")
    if item["serialized"] and not declared_serial:
        raise ApiError("ERR_SERIAL_REQUIRED")
    row = {
        "id": db.new_id(),
        "rma_id": rma["id"],
        "catalog_item_id": catalog_item_id,
        "authorized_quantity": authorized_quantity,
        "reason_code": reason_code,
        "declared_serial": declared_serial,
    }
    db.stamp_new(row, versioned=False)
    db.insert("rma_lines", row)
    return response.created(serialize.rma_line(row))


@bp.get("/return-authorization-lines/<rma_line_id>")
def get_rma_line(rma_line_id):
    user_id, role = mw.require(
        "CenterAdmin", "ReceivingClerk", "GradingInspector", "DispositionSupervisor", "ClientRep"
    )
    rma_line = db.get("rma_lines", rma_line_id)
    if rma_line is not None:
        mw.scope(role, user_id, refs.client_id_of_rma_line(rma_line))
    rma_line = services.must_rma_line(rma_line_id)
    return response.ok(serialize.rma_line(rma_line))


@bp.get("/return-authorization-lines")
def list_rma_lines():
    user_id, role = mw.require(
        "CenterAdmin", "ReceivingClerk", "GradingInspector", "DispositionSupervisor", "ClientRep"
    )
    catalog_item_id = query.arg("catalog_item_id")
    if catalog_item_id is not None:
        services.must_item(catalog_item_id)
    rma_id = query.arg("rma_id")
    if rma_id is not None:
        services.must_rma(rma_id)
    rows = db.sorted_rows(db.all_rows("rma_lines"))
    if role == mw.CLIENT_REP:
        rows = [r for r in rows if refs.client_id_of_rma_line(r) == user_id]
    rows = query.eq(rows, "rma_id", rma_id)
    rows = query.eq(rows, "catalog_item_id", catalog_item_id)
    rows = query.eq(rows, "reason_code", query.arg("reason_code"))
    return response.paginate(rows, serialize.rma_line)


@bp.post("/return-authorizations/<rma_id>/issue")
def issue_rma(rma_id):
    user_id, role = mw.require("CenterAdmin", "ClientRep")
    pending = db.get("rmas", rma_id)
    if pending is not None:
        mw.scope(role, user_id, pending["client_id"])
    response.body_json()
    rma = services.must_rma(rma_id)
    client = services.must_client(rma["client_id"])
    services.require_active(client)
    if rma["status"] != "DRAFT":
        raise ApiError("ERR_RMA_INVALID_STATE")
    if not refs.rma_lines_of(rma):
        raise ApiError("ERR_RMA_NO_LINES")
    expires_at = db.parse_instant(rma["expires_at"])
    if expires_at is None or expires_at <= db.now():
        raise ApiError("ERR_RMA_EXPIRES_IN_PAST")
    rma["status"] = "ISSUED"
    rma["issued_at"] = db.now_str()
    db.touch(rma)
    return response.ok(serialize.rma(rma))


@bp.post("/return-authorizations/<rma_id>/void")
def void_rma(rma_id):
    mw.require("CenterAdmin")
    body = response.body_json()
    shapes.opt_str(body, "void_reason")
    rma = services.must_rma(rma_id)
    if rma["status"] not in ("ISSUED", "PARTIALLY_RECEIVED"):
        raise ApiError("ERR_RMA_INVALID_STATE")
    rma["status"] = "VOID"
    db.touch(rma)
    aggregates.void_shrink_consequence(rma, "authorization voided")
    return response.ok(serialize.rma(rma))


@bp.post("/return-authorizations/<rma_id>/reissue")
def reissue_rma(rma_id):
    user_id, role = mw.require("CenterAdmin", "ClientRep")
    pending = db.get("rmas", rma_id)
    if pending is not None:
        mw.scope(role, user_id, pending["client_id"])
    body = response.body_json()
    expected_rma_version = shapes.req_int(body, "expected_rma_version")
    expires_at = shapes.req_instant(body, "expires_at")
    rma = services.must_rma(rma_id)
    # §3.2: "Once an authorization is EXPIRED, any attempt to receive against it
    # or reissue it fails with ERR_RMA_EXPIRED" — the expiry answer outranks the
    # generic state answer on this endpoint.
    if rma["status"] not in ("ISSUED", "EXPIRED"):
        raise ApiError("ERR_RMA_INVALID_STATE")
    if rma["status"] == "EXPIRED":
        raise ApiError("ERR_RMA_EXPIRED")
    stored_expiry = db.parse_instant(rma["expires_at"])
    if stored_expiry is not None and stored_expiry <= db.now():
        raise ApiError("ERR_RMA_EXPIRED")
    if refs.receipts_of(rma):
        raise ApiError("ERR_RMA_ALREADY_RECEIVING")
    if expected_rma_version != rma["version"]:
        raise ApiError("ERR_STALE_RMA_VERSION")
    _check_expiry_window(db.parse_instant(rma["order_placed_at"]), expires_at)

    rma["status"] = "SUPERSEDED"
    db.touch(rma)

    replacement = {
        "id": db.new_id(),
        "client_id": rma["client_id"],
        "order_reference": rma["order_reference"],
        "customer_reference": rma["customer_reference"],
        "order_placed_at": rma["order_placed_at"],
        "expires_at": db.fmt_instant(expires_at),
        "supersedes_rma_id": rma["id"],
        "status": "ISSUED",
        "issued_at": db.now_str(),
    }
    db.stamp_new(replacement)
    db.insert("rmas", replacement)
    for source_line in refs.rma_lines_of(rma):
        copy = {
            "id": db.new_id(),
            "rma_id": replacement["id"],
            "catalog_item_id": source_line["catalog_item_id"],
            "authorized_quantity": source_line["authorized_quantity"],
            "reason_code": source_line["reason_code"],
            "declared_serial": source_line["declared_serial"],
        }
        db.stamp_new(copy, versioned=False)
        db.insert("rma_lines", copy)
    return response.created(serialize.rma(replacement))
