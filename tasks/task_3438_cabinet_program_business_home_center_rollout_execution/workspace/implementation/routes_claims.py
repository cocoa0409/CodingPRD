"""DamageClaim and ReplacementOrder endpoints (PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from auth import get_body, require_roles
from db import bump, new_entity, store
from envelope import ok, paginate
from errors import api_error
from services import (CLAIM_WINDOW_DAYS, check_color_match, commit_slot,
                      compute_settlement, current_batch_for, release_slot,
                      select_slot_expedite)
from util import iso3, parse_dt

bp = Blueprint("claims", __name__)

CLAIM_FILE_ROLES = ("LogisticsCoordinator", "DealerRep", "RetailDesigner",
                    "ClaimsAdjuster")
CLAIM_READ_ROLES = ("ClaimsAdjuster", "LogisticsCoordinator", "DealerRep",
                    "RetailDesigner", "ProgramManager", "PlatformAdmin")
REPL_READ_ROLES = ("PlantScheduler", "LogisticsCoordinator", "ClaimsAdjuster",
                   "ProgramManager", "PlatformAdmin")

CLAIM_EDGES = {
    "FILED": {"UNDER_REVIEW", "DENIED"},
    "UNDER_REVIEW": {"APPROVED", "DENIED"},
}

REPL_ROLE_PINS = {
    "SCHEDULED": "PlantScheduler",
    "IN_PRODUCTION": "PlantScheduler",
    "CANCELLED": "PlantScheduler",
    "SHIPPED": "LogisticsCoordinator",
    "RECEIVED": "LogisticsCoordinator",
    "REMAKE": "LogisticsCoordinator",
}

REPL_EDGES = {
    "CREATED": {"SCHEDULED", "CANCELLED"},
    "SCHEDULED": {"IN_PRODUCTION", "CANCELLED"},
    "IN_PRODUCTION": {"SHIPPED"},
    "SHIPPED": {"RECEIVED"},
    "RECEIVED": {"REMAKE"},
    "REMAKE": {"SCHEDULED"},
}


def serialize_claim(claim):
    return dict(claim)


def serialize_repl(repl):
    return dict(repl)


@bp.route("/cabinet/claims", methods=["POST"])
def create_claim():
    uid, role = require_roles(*CLAIM_FILE_ROLES)
    body = get_body()
    shipment_id = body.get("shipment_id")
    order_id = body.get("order_id")
    if shipment_id is None or order_id is None:
        raise api_error("ERR_INVALID_REQUEST", "shipment_id and order_id are required")
    shipment = store.shipments.get(shipment_id)
    if shipment is None:
        raise api_error("ERR_NOT_FOUND", "shipment not found")
    order = store.orders.get(order_id)
    if order is None:
        raise api_error("ERR_NOT_FOUND", "order not found")
    # Ownership at intake: DealerRep files against their own account's orders;
    # RetailDesigner against orders whose design job they own.
    if role == "DealerRep" and order["account_id"] != uid:
        raise api_error("ERR_FORBIDDEN",
                        "DealerRep may only file claims for their own account's orders")
    if role == "RetailDesigner":
        design_job_id = order.get("design_job_id")
        job = store.design_jobs.get(design_job_id) if design_job_id else None
        if job is None or job["designer_user_id"] != uid:
            raise api_error("ERR_FORBIDDEN",
                            "RetailDesigner may only file claims for orders whose "
                            "design job they own")
    if shipment["status"] != "DELIVERED":
        raise api_error("ERR_SHIPMENT_NOT_DELIVERED",
                        "claims may only be filed against DELIVERED shipments")
    account = store.accounts[order["account_id"]]
    if account["status"] != "ACTIVE":
        raise api_error("ERR_ACCOUNT_NOT_ACTIVE", "account is not ACTIVE")
    if order_id != shipment["order_id"]:
        raise api_error("ERR_INVALID_REQUEST",
                        "order_id must equal the shipment's order_id")
    line_index = body.get("line_index")
    if (isinstance(line_index, bool) or not isinstance(line_index, int)
            or line_index < 0 or line_index >= len(order["lines"])):
        raise api_error("ERR_INVALID_REQUEST",
                        "line_index must be a 0-based index into the order's lines")
    claimed_qty = body.get("claimed_qty")
    if isinstance(claimed_qty, bool) or not isinstance(claimed_qty, int) or claimed_qty <= 0:
        raise api_error("ERR_INVALID_REQUEST", "claimed_qty must be a positive integer")
    delivered = parse_dt(shipment["delivered_at"])
    if store.clock > delivered + timedelta(days=CLAIM_WINDOW_DAYS):
        raise api_error("ERR_CLAIM_WINDOW_EXPIRED",
                        "claims must be filed within 14 days of delivery (inclusive)")
    aggregate = 0
    for other in store.claims.values():
        if (other["shipment_id"] == shipment_id
                and other["line_index"] == line_index
                and other["status"] != "DENIED"):
            aggregate += other["claimed_qty"]
    if aggregate + claimed_qty > order["lines"][line_index]["quantity"]:
        raise api_error("ERR_CLAIM_QUANTITY_EXCEEDED",
                        "aggregate claimed_qty over non-DENIED claims would exceed "
                        "the shipped line quantity")
    claim = new_entity()
    claim.update({
        "shipment_id": shipment_id,
        "order_id": order_id,
        "line_index": line_index,
        "claimed_qty": claimed_qty,
        "filed_by_user_id": uid,
        "filed_at": iso3(store.clock),
        "status": "FILED",
        "resolution": None,
        "settlement_cents": None,
        "decided_by_user_id": None,
    })
    store.claims[claim["id"]] = claim
    return ok(serialize_claim(claim), 201)


@bp.route("/cabinet/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    require_roles(*CLAIM_READ_ROLES)
    claim = store.claims.get(claim_id)
    if claim is None:
        raise api_error("ERR_NOT_FOUND", "damage claim not found")
    return ok(serialize_claim(claim))


@bp.route("/cabinet/claims", methods=["GET"])
def list_claims():
    require_roles(*CLAIM_READ_ROLES)
    shipment_id = request.args.get("shipment_id")
    order_id = request.args.get("order_id")
    status = request.args.get("status")
    items = [c for c in store.claims.values()
             if (shipment_id is None or c["shipment_id"] == shipment_id)
             and (order_id is None or c["order_id"] == order_id)
             and (status is None or c["status"] == status)]
    items = sorted(items, key=lambda c: c["created_at"])
    page, meta = paginate([serialize_claim(c) for c in items])
    return ok(page, 200, meta)


@bp.route("/cabinet/claims/<claim_id>/transition", methods=["POST"])
def transition_claim(claim_id):
    uid, _ = require_roles("ClaimsAdjuster")
    claim = store.claims.get(claim_id)
    if claim is None:
        raise api_error("ERR_NOT_FOUND", "damage claim not found")
    body = get_body()
    to_status = body.get("to_status")
    if to_status is None:
        raise api_error("ERR_INVALID_REQUEST", "to_status is required")
    # Segregation of duties (stage 2): the decider may never be the filer.
    if to_status in ("APPROVED", "DENIED") and uid == claim["filed_by_user_id"]:
        raise api_error("ERR_SEGREGATION_OF_DUTIES",
                        "the decider may not be the claim's filer")
    current = claim["status"]
    if to_status not in CLAIM_EDGES.get(current, set()):
        raise api_error("ERR_INVALID_STATE",
                        "cannot move claim from {} to {}".format(current, to_status))

    if to_status == "UNDER_REVIEW":
        claim["status"] = "UNDER_REVIEW"
        bump(claim)
        return ok(serialize_claim(claim))

    if to_status == "DENIED":
        claim["decided_by_user_id"] = uid
        claim["status"] = "DENIED"
        bump(claim)
        return ok(serialize_claim(claim))

    # APPROVED
    resolution = body.get("resolution")
    if resolution is None:
        raise api_error("ERR_INVALID_REQUEST",
                        "resolution is required when approving a claim")
    if resolution not in ("REPLACEMENT", "CREDIT"):
        raise api_error("ERR_INVALID_REQUEST",
                        "resolution must be REPLACEMENT or CREDIT")
    order = store.orders[claim["order_id"]]
    line_item = order["lines"][claim["line_index"]]
    if resolution == "REPLACEMENT":
        batch = current_batch_for(line_item["finish_code"])
        if batch is None:
            raise api_error("ERR_NO_CURRENT_BATCH",
                            "no CURRENT finish batch for {}".format(
                                line_item["finish_code"]))
        claim["settlement_cents"] = 0
        repl = new_entity()
        repl.update({
            "damage_claim_id": claim["id"],
            "order_id": order["id"],
            "line_index": claim["line_index"],
            "quantity": claim["claimed_qty"],
            "finish_batch_id": batch["id"],
            "original_finish_batch_id": line_item.get("finish_batch_id"),
            "status": "CREATED",
            "scheduled_week": None,
        })
        store.replacements[repl["id"]] = repl
    else:
        claim["settlement_cents"] = compute_settlement(claim)
    claim["resolution"] = resolution
    claim["decided_by_user_id"] = uid
    claim["status"] = "APPROVED"
    bump(claim)
    return ok(serialize_claim(claim))


@bp.route("/cabinet/replacement-orders/<repl_id>", methods=["GET"])
def get_replacement(repl_id):
    require_roles(*REPL_READ_ROLES)
    repl = store.replacements.get(repl_id)
    if repl is None:
        raise api_error("ERR_NOT_FOUND", "replacement order not found")
    return ok(serialize_repl(repl))


@bp.route("/cabinet/replacement-orders", methods=["GET"])
def list_replacements():
    require_roles(*REPL_READ_ROLES)
    damage_claim_id = request.args.get("damage_claim_id")
    finish_batch_id = request.args.get("finish_batch_id")
    original_finish_batch_id = request.args.get("original_finish_batch_id")
    order_id = request.args.get("order_id")
    status = request.args.get("status")
    items = [r for r in store.replacements.values()
             if (damage_claim_id is None or r["damage_claim_id"] == damage_claim_id)
             and (finish_batch_id is None or r["finish_batch_id"] == finish_batch_id)
             and (original_finish_batch_id is None
                  or r["original_finish_batch_id"] == original_finish_batch_id)
             and (order_id is None or r["order_id"] == order_id)
             and (status is None or r["status"] == status)]
    items = sorted(items, key=lambda r: r["created_at"])
    page, meta = paginate([serialize_repl(r) for r in items])
    return ok(page, 200, meta)


@bp.route("/cabinet/replacement-orders/<repl_id>/transition", methods=["POST"])
def transition_replacement(repl_id):
    _, role = require_roles("PlantScheduler", "LogisticsCoordinator")
    repl = store.replacements.get(repl_id)
    if repl is None:
        raise api_error("ERR_NOT_FOUND", "replacement order not found")
    body = get_body()
    to_status = body.get("to_status")
    if to_status is None:
        raise api_error("ERR_INVALID_REQUEST", "to_status is required")
    if to_status in REPL_ROLE_PINS and role != REPL_ROLE_PINS[to_status]:
        raise api_error("ERR_FORBIDDEN",
                        "role {} may not drive the {} transition".format(role, to_status))
    current = repl["status"]
    if to_status not in REPL_EDGES.get(current, set()):
        raise api_error("ERR_INVALID_STATE",
                        "cannot move replacement from {} to {}".format(current, to_status))

    if to_status == "SCHEDULED":
        order = store.orders[repl["order_id"]]
        line_item = order["lines"][repl["line_index"]]
        finish_code = line_item["finish_code"]
        complexity = line_item["units"] // line_item["quantity"]
        needed = repl["quantity"] * complexity
        if current == "CREATED":
            new_batch = store.batches.get(repl["finish_batch_id"])
            if new_batch is None:
                raise api_error("ERR_NO_CURRENT_BATCH",
                                "no finish batch pinned on the replacement")
        else:
            # REMAKE re-scheduling: re-evaluate against the CURRENT batch now.
            new_batch = current_batch_for(finish_code)
            if new_batch is None:
                raise api_error("ERR_NO_CURRENT_BATCH",
                                "no CURRENT finish batch for {}".format(finish_code))
            repl["finish_batch_id"] = new_batch["id"]
        original_batch = store.batches.get(repl["original_finish_batch_id"])
        if original_batch is None:
            raise api_error("ERR_NO_CURRENT_BATCH",
                            "the original pinned batch no longer exists")
        check_color_match(new_batch, original_batch)
        slot = select_slot_expedite(line_item["family_code"], needed)
        commit_slot(slot, needed)
        store.repl_slot_picks[repl["id"]] = (slot["id"], needed)
        repl["scheduled_week"] = slot["week"]
        repl["status"] = "SCHEDULED"
        bump(repl)
        return ok(serialize_repl(repl))

    if to_status == "CANCELLED":
        if current == "SCHEDULED":
            pick = store.repl_slot_picks.pop(repl["id"], None)
            if pick is not None:
                slot = store.slots.get(pick[0])
                if slot is not None:
                    release_slot(slot, pick[1])
        repl["status"] = "CANCELLED"
        bump(repl)
        return ok(serialize_repl(repl))

    # IN_PRODUCTION / SHIPPED / RECEIVED / REMAKE: status advance only.
    repl["status"] = to_status
    bump(repl)
    return ok(serialize_repl(repl))
