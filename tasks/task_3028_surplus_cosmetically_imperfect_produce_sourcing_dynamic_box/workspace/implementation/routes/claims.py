"""Quality claims (§3.3)."""

from flask import Blueprint

import common
import envelope
import params
import store
from common import ApiError
from routes import helpers
from services import claims as claims_svc

bp = Blueprint("claims", __name__)


@bp.post("/produce/box-orders/<order_id>/quality-claims")
def create(order_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN))
    order = helpers.fetch_order(order_id)
    if actor["role"] == common.ROLE_CUSTOMER and order["customer_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only file a claim on its own order.")
    payload = params.body()
    params.missing(payload, ["box_build_item_id", "reason_code", "photo_url",
                             "requested_credit_cents"])
    params.check_enum("reason_code", payload.get("reason_code"),
                      common.CLAIM_REASON_CODES)

    item = helpers.fetch_item(payload["box_build_item_id"])
    if item["box_order_id"] != order["id"]:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "The build item does not belong to the order.")
    lot = helpers.fetch_lot(item["supply_lot_id"])

    # Rung 13: photo evidence is a shape rule.
    if not evidence_extension_ok(payload.get("photo_url")):
        raise ApiError("ERR_CLAIM_EVIDENCE_REQUIRED", 422,
                       "photo_url must end in an accepted image extension.")

    row = store.new_row({
        "box_order_id": order["id"],
        "box_build_item_id": item["id"],
        "supply_lot_id": lot["id"],
        "reason_code": payload["reason_code"],
        "photo_url": payload["photo_url"],
        "requested_credit_cents": params.as_int("requested_credit_cents",
                                                payload["requested_credit_cents"]),
        "credited_cents": 0,
        "status": "IN_REVIEW",
        "outcome": None,
        "cited_lot_quality_status": lot["quality_status"],
        "_supplier_id": lot["supplier_id"],
        "_upheld": False,
    })
    store.QUALITY_CLAIMS[row["id"]] = row
    from services import centers

    center = store.FULFILLMENT_CENTERS.get(order["fulfillment_center_id"])
    if center is not None:
        centers.refresh_claim_count(center)
    return envelope.object_response(store.serialise(row), 201)


def evidence_extension_ok(photo_url):
    if not isinstance(photo_url, str):
        return False
    path = photo_url.split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith(common.PHOTO_EXTENSIONS)


@bp.get("/produce/box-orders/<order_id>/quality-claims")
def list_for_order(order_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_CUSTOMER, common.ROLE_PLATFORM_ADMIN,
                          common.ROLE_FULFILLMENT_OPERATOR))
    order = helpers.fetch_order(order_id)
    if actor["role"] == common.ROLE_CUSTOMER and order["customer_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Customer may only read its own orders.")
    rows = store.of(store.QUALITY_CLAIMS, box_order_id=order_id)
    rows = params.query_filter(rows, "status")
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/quality-claims")
def list_all():
    actor = helpers.actor()
    helpers.admin(actor)
    rows = list(store.QUALITY_CLAIMS.values())
    rows = params.query_filter(rows, "status")
    rows = params.query_filter(rows, "outcome")
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.post("/produce/quality-claims/<claim_id>/review")
def review(claim_id):
    actor = helpers.actor()
    helpers.admin(actor)
    claim = helpers.fetch_claim(claim_id)
    payload = params.body()
    params.missing(payload, ["outcome"])
    params.check_enum("outcome", payload.get("outcome"), common.CLAIM_OUTCOMES)
    helpers.require_version(payload, "expected_claim_version", claim, "QualityClaim")
    claims_svc.review(claim, payload["outcome"])
    return envelope.object_response(store.serialise(claim))


@bp.post("/produce/quality-claims/<claim_id>/reopen")
def reopen(claim_id):
    actor = helpers.actor()
    helpers.admin(actor)
    claim = helpers.fetch_claim(claim_id)
    claims_svc.reopen(claim)
    return envelope.object_response(store.serialise(claim))