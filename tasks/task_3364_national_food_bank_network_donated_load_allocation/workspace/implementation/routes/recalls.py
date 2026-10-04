"""Product recalls, tracing, resolution and the recall hold list."""

from flask import Blueprint, request

import auth
import clock
import envelope
import serializers
import store
from errors import (
    ERR_AGREEMENT_NOT_FOUND,
    ERR_CATEGORY_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_RECALL_NOT_FOUND,
    ERR_RECALL_NOT_TRACING,
    fail,
)
from services import recalls as recall_svc

bp = Blueprint("recalls", __name__)

PRODUCT_CATEGORIES = ("DRY_GOODS", "PRODUCE", "DAIRY", "FROZEN_PROTEIN", "BAKERY")


def get_recall_or_404(recall_id):
    recall = store.recalls.get(recall_id)
    if recall is None:
        fail(ERR_RECALL_NOT_FOUND, "no product recall matches id %s" % recall_id)
    return recall


@bp.route("/network/recalls", methods=["POST"])
def create_recall():
    auth.require_roles("NetworkAdmin")
    data = auth.json_body()

    agreement_id = auth.req_str(data, "donor_agreement_id")
    lot_code = auth.req_str(data, "lot_code")
    category = auth.req_enum(data, "product_category", PRODUCT_CATEGORIES)
    affected_lbs = auth.req_int(data, "affected_lbs")
    if affected_lbs < 0:
        fail(ERR_INVALID_REQUEST, "affected_lbs must be zero or greater")
    scope = auth.opt_str(data, "scope")

    agreement = store.agreements.get(agreement_id)
    if agreement is None:
        fail(ERR_AGREEMENT_NOT_FOUND,
             "no donor agreement matches id %s" % agreement_id)
    if agreement["product_category"] != category:
        fail(ERR_CATEGORY_MISMATCH,
             "the recall category must equal the agreement's product category")

    reopened = any(r["donor_agreement_id"] == agreement["id"] and r["lot_code"] == lot_code
                   for r in store.recalls.values())

    recall = store.new_record(
        donor_agreement_id=agreement["id"],
        lot_code=lot_code,
        product_category=category,
        affected_lbs=affected_lbs,
        recall_status="REOPENED" if reopened else "OPEN",
        traced_load_count=0,
        held_lbs=0,
        opened_at=clock.now(),
        scope=scope,
    )
    store.insert("recalls", recall)
    return envelope.ok_object(serializers.recall(recall), 201)


@bp.route("/network/recalls/<recall_id>/trace", methods=["POST"])
def trace_recall(recall_id):
    auth.require_roles("NetworkAdmin")
    data = request.get_json(silent=True)
    scope = None
    if data is not None:
        if not isinstance(data, dict):
            fail(ERR_INVALID_REQUEST, "the request body must be a JSON object")
        scope = auth.opt_str(data, "scope")

    recall = get_recall_or_404(recall_id)
    if recall["recall_status"] not in ("OPEN", "REOPENED"):
        fail(ERR_RECALL_NOT_TRACING,
             "only a recall in OPEN or REOPENED may be traced")

    if scope is None:
        scope = recall.get("scope")
    recall_svc.trace(recall, scope)
    return envelope.ok_object(serializers.recall(recall))


@bp.route("/network/recalls/<recall_id>/resolve", methods=["POST"])
def resolve_recall(recall_id):
    auth.require_roles("NetworkAdmin")
    recall = get_recall_or_404(recall_id)
    if recall["recall_status"] != "TRACING":
        fail(ERR_RECALL_NOT_TRACING, "only a recall in TRACING may be resolved")
    if int(recall["held_lbs"]) <= 0 and int(recall["traced_load_count"]) != 0:
        fail(ERR_RECALL_NOT_TRACING,
             "a trace that matched product but holds none cannot be resolved")

    recall_svc.resolve(recall)
    return envelope.ok_object(serializers.recall(recall))


@bp.route("/network/recall-holds", methods=["GET"])
def list_recall_holds():
    auth.require_roles("NetworkAdmin", "MemberFoodBank")
    rows = store.ordered(store.holds.values())
    recall_id = request.args.get("recall_id")
    if recall_id:
        rows = [h for h in rows if h["recall_id"] == recall_id]
    load_id = request.args.get("load_id")
    if load_id:
        rows = [h for h in rows if h["load_id"] == load_id]
    status_filter = request.args.get("hold_status")
    if status_filter:
        rows = [h for h in rows if h["hold_status"] == status_filter]
    page, limit, offset, total = auth.paginate(rows)
    return envelope.ok_array([serializers.hold(h) for h in page], limit, offset, total)


@bp.route("/network/recall-holds/<hold_id>", methods=["GET"])
def read_recall_hold(hold_id):
    auth.require_roles("NetworkAdmin", "MemberFoodBank")
    hold = store.holds.get(hold_id)
    if hold is None:
        fail(ERR_RECALL_NOT_FOUND, "no recall hold matches id %s" % hold_id)
    return envelope.ok_object(serializers.hold(hold))
