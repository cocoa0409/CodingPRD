"""Commitments and replacement transactions routes."""
from flask import Blueprint, request

from db import db
from middleware import require_roles, require_any
from response import success_object, success_list
from util import (base_entity, touch, dec, q2, require_fields, is_number, get_body,
                  strip_internal, paginate, sort_created)
from errors import (err_not_found, err_invalid_request, err_invalid_state,
                    err_ownership, err_owner_suspended, err_stale_version,
                    err_replacement_exceeds, err_replacement_not_deliverable,
                    err_default_threshold)

bp = Blueprint("commitments", __name__)


def _serialize(c):
    return strip_internal(c)


def _serialize_repl(r):
    return strip_internal(r)


@bp.route("/capacity-market/commitments", methods=["GET"])
def list_commitments():
    require_any()
    items = list(db.commitments.values())
    for key in ("resource_id", "delivery_year_id", "offer_id", "status"):
        v = request.args.get(key)
        if v:
            items = [c for c in items if c.get(key) == v]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize(c) for c in page], limit, offset, total)


@bp.route("/capacity-market/commitments/<cid>", methods=["GET"])
def get_commitment(cid):
    require_any()
    c = db.commitments.get(cid)
    if c is None:
        raise err_not_found("commitment not found")
    return success_object(_serialize(c))


@bp.route("/capacity-market/commitments/<cid>/default", methods=["POST"])
def default_commitment(cid):
    require_roles("MarketAdmin")
    c = db.commitments.get(cid)
    if c is None:
        raise err_not_found("commitment not found")
    if c["status"] != "ACTIVE":
        raise err_invalid_state("commitment is not ACTIVE")
    finalized = [a for a in db.assessments.values()
                 if a["commitment_id"] == cid and a["status"] == "FINALIZED"]
    if not (dec(c["cumulative_performance_score"]) < dec("0.40") and len(finalized) >= 2):
        raise err_default_threshold()
    c["status"] = "DEFAULTED"
    touch(c)
    resource = db.resources.get(c["resource_id"])
    if resource is not None:
        resource["must_offer"] = False
        touch(resource)
    return success_object(_serialize(c))


# ------------- Replacement transactions -------------

def _zone_ancestors(zone_id):
    """Set of zone ids including zone_id and all its ancestors."""
    ids = set()
    cur = db.zones.get(zone_id)
    while cur is not None:
        ids.add(cur["id"])
        pid = cur.get("parent_zone_id")
        cur = db.zones.get(pid) if pid else None
    return ids


def _zone_descendants(zone_id):
    ids = set()
    stack = [zone_id]
    while stack:
        zid = stack.pop()
        if zid in ids:
            continue
        ids.add(zid)
        for z in db.zones.values():
            if z.get("parent_zone_id") == zid:
                stack.append(z["id"])
    return ids


@bp.route("/capacity-market/replacement-transactions", methods=["POST"])
def create_replacement():
    user_id, role = require_roles("ResourceOwner")
    body = get_body()
    require_fields(body, ["commitment_id", "replacement_resource_id", "replacement_mw",
                          "price_per_mw_day", "expected_commitment_version"])
    commitment = db.commitments.get(body["commitment_id"])
    if commitment is None:
        raise err_not_found("commitment not found")
    repl_resource = db.resources.get(body["replacement_resource_id"])
    if repl_resource is None:
        raise err_not_found("replacement resource not found")

    expected = body["expected_commitment_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_commitment_version must be an integer")
    # OCC first
    if expected != commitment["version"]:
        raise err_stale_version()
    # state gate
    if commitment["status"] != "ACTIVE":
        raise err_invalid_state("commitment is not ACTIVE")
    # ownership: acting owner must own the original commitment's resource
    orig_resource = db.resources.get(commitment["resource_id"])
    if orig_resource is None:
        raise err_not_found("resource not found")
    if user_id != orig_resource["owner_id"]:
        raise err_ownership()
    orig_owner = db.owners.get(orig_resource["owner_id"])
    if orig_owner and orig_owner["status"] == "SUSPENDED":
        raise err_owner_suspended()

    replacement_mw = body["replacement_mw"]
    price = body["price_per_mw_day"]
    if not is_number(replacement_mw) or dec(replacement_mw) <= 0:
        raise err_replacement_exceeds("replacement_mw must be > 0")
    if dec(replacement_mw) > dec(commitment["committed_mw"]):
        raise err_replacement_exceeds()
    if not is_number(price) or dec(price) < 0:
        raise err_invalid_request("price_per_mw_day must be >= 0")

    # deliverability
    if repl_resource["id"] == commitment["resource_id"]:
        raise err_replacement_not_deliverable("replacement resource must differ from the commitment's resource")
    if repl_resource["status"] != "ACCREDITED":
        raise err_replacement_not_deliverable("replacement resource is not ACCREDITED")
    # accredited for the commitment's delivery year
    has_effective = any(
        a["resource_id"] == repl_resource["id"]
        and a["delivery_year_id"] == commitment["delivery_year_id"]
        and a["status"] == "EFFECTIVE"
        for a in db.accreditations.values()
    )
    if not has_effective:
        raise err_replacement_not_deliverable("replacement resource not accredited for the delivery year")
    # headroom: accredited_ucap_mw - ACTIVE committed MW in same delivery year
    active_committed = dec(0)
    for c in db.commitments.values():
        if (c["resource_id"] == repl_resource["id"]
                and c["delivery_year_id"] == commitment["delivery_year_id"]
                and c["status"] == "ACTIVE"):
            active_committed += dec(c["committed_mw"])
    headroom = dec(repl_resource["accredited_ucap_mw"]) - active_committed
    if headroom < dec(replacement_mw):
        raise err_replacement_not_deliverable("insufficient accredited headroom")
    # zone deliverability: same zone or ancestor/descendant LDA
    orig_zone_id = orig_resource["zone_id"]
    repl_zone_id = repl_resource["zone_id"]
    if not (repl_zone_id in _zone_ancestors(orig_zone_id)
            or repl_zone_id in _zone_descendants(orig_zone_id)):
        raise err_replacement_not_deliverable("replacement zone is not deliverable")

    tx = base_entity()
    tx.update({
        "commitment_id": commitment["id"],
        "replacement_resource_id": repl_resource["id"],
        "replacement_mw": dec(replacement_mw),
        "price_per_mw_day": dec(price),
        "expected_commitment_version": expected,
        "status": "PENDING",
    })
    db.replacements[tx["id"]] = tx
    commitment["status"] = "REPLACEMENT_PENDING"
    touch(commitment)
    return success_object(_serialize_repl(tx), 201)


@bp.route("/capacity-market/replacement-transactions", methods=["GET"])
def list_replacements():
    require_any()
    items = list(db.replacements.values())
    for key in ("commitment_id", "replacement_resource_id", "status"):
        v = request.args.get(key)
        if v:
            items = [r for r in items if r.get(key) == v]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize_repl(r) for r in page], limit, offset, total)


@bp.route("/capacity-market/replacement-transactions/<txid>", methods=["GET"])
def get_replacement(txid):
    require_any()
    tx = db.replacements.get(txid)
    if tx is None:
        raise err_not_found("replacement transaction not found")
    return success_object(_serialize_repl(tx))


@bp.route("/capacity-market/replacement-transactions/<txid>/approve", methods=["POST"])
def approve_replacement(txid):
    require_roles("MarketAdmin")
    tx = db.replacements.get(txid)
    if tx is None:
        raise err_not_found("replacement transaction not found")
    if tx["status"] != "PENDING":
        raise err_invalid_state("replacement transaction is not PENDING")
    commitment = db.commitments.get(tx["commitment_id"])
    if commitment is None:
        raise err_not_found("commitment not found")

    tx["status"] = "APPROVED"
    touch(tx)
    commitment["status"] = "ACTIVE"
    commitment["committed_mw"] = dec(commitment["committed_mw"]) - dec(tx["replacement_mw"])
    commitment["daily_revenue_dollars"] = q2(dec(commitment["committed_mw"])
                                             * dec(commitment["clearing_price_per_mw_day"]))
    touch(commitment)

    newc = base_entity()
    newc.update({
        "resource_id": tx["replacement_resource_id"],
        "offer_id": commitment["offer_id"],
        "delivery_year_id": commitment["delivery_year_id"],
        "committed_mw": dec(tx["replacement_mw"]),
        "clearing_price_per_mw_day": commitment["clearing_price_per_mw_day"],
        "daily_revenue_dollars": q2(dec(tx["replacement_mw"])
                                    * dec(commitment["clearing_price_per_mw_day"])),
        "status": "ACTIVE",
        "cumulative_performance_score": dec(0),
    })
    db.commitments[newc["id"]] = newc
    return success_object(_serialize_repl(tx))


@bp.route("/capacity-market/replacement-transactions/<txid>/reject", methods=["POST"])
def reject_replacement(txid):
    require_roles("MarketAdmin")
    tx = db.replacements.get(txid)
    if tx is None:
        raise err_not_found("replacement transaction not found")
    if tx["status"] != "PENDING":
        raise err_invalid_state("replacement transaction is not PENDING")
    commitment = db.commitments.get(tx["commitment_id"])
    if commitment is None:
        raise err_not_found("commitment not found")
    tx["status"] = "REJECTED"
    touch(tx)
    commitment["status"] = "ACTIVE"
    touch(commitment)
    return success_object(_serialize_repl(tx))
