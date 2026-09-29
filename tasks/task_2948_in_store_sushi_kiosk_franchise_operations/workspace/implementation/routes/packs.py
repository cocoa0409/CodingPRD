"""Retail pack lots: build, markdown, discard and void -- PRD 3.7."""

from datetime import timedelta

from flask import Blueprint

import db
from core import (LOCK, dec, floor_int, iso_instant, logical_now, parse_instant,
                  round_half_up, whole_minutes_between)
from errors import ApiError
from middleware import (ROLE_FRANCHISE_CHEF, ROLE_FRANCHISOR_OPS,
                        ROLE_HOST_STORE_MANAGER, ROLE_QUALITY_AUDITOR, authorize,
                        body, req_enum, req_instant, req_int, req_str)
from response import created, ok
from routes.base import (batch_or_404, fish_lot_or_404, fk_lookup, filters,
                         pack_lot_or_404, paginate)
from services import calc, domain

bp = Blueprint("packs", __name__)

PACKABLE_BATCH_STATES = ("APPROVED", "VARIANCE_APPROVED")


def _scope_lot(actor, lot):
    kiosk = domain.kiosk_of_pack_lot(lot)
    if actor.is_chef:
        chef = db.chefs.get(actor.user_id)
        if (chef is None or kiosk is None
                or chef["assigned_kiosk_id"] != kiosk["id"]):
            raise ApiError("ERR_OWNERSHIP_MISMATCH")
    elif actor.is_manager:
        store = domain.store_of_kiosk(kiosk) if kiosk is not None else None
        if store is None or store["id"] != actor.user_id:
            raise ApiError("ERR_OWNERSHIP_MISMATCH")


@bp.post("/pack-lots")
def build_pack_lot():
    actor = authorize(ROLE_FRANCHISE_CHEF)
    payload = body()
    batch = fk_lookup(payload, "rice_batch_id", batch_or_404)
    fish = fk_lookup(payload, "fish_lot_id", fish_lot_or_404)
    if batch is not None:
        chef = db.chefs.get(actor.user_id)
        source_kiosk = domain.kiosk_of_batch(batch)
        if (chef is None or source_kiosk is None
                or chef["assigned_kiosk_id"] != source_kiosk["id"]):
            raise ApiError("ERR_OWNERSHIP_MISMATCH")

    req_str(payload, "rice_batch_id")
    req_str(payload, "fish_lot_id")
    sku_code = req_str(payload, "sku_code")
    pack_count = req_int(payload, "pack_count", exclusive_minimum=0)
    list_price_cents = req_int(payload, "list_price_cents", exclusive_minimum=0)
    produced_at = req_instant(payload, "produced_at")

    with LOCK:
        # Safety outranks referential coherence (PRD 2.6): the source
        # dispositions are checked before the cross-kiosk comparison.
        if batch["status"] not in PACKABLE_BATCH_STATES:
            raise ApiError("ERR_RICE_BATCH_NOT_APPROVED")
        if fish["status"] != "RELEASED":
            raise ApiError("ERR_FISH_LOT_NOT_RELEASED")
        kiosk = domain.kiosk_of_batch(batch)
        if kiosk is not None and kiosk["sanitation_posture"] == "LOCKDOWN":
            raise ApiError("ERR_KIOSK_POSTURE_LOCKDOWN")
        if kiosk is None or fish["kiosk_id"] != kiosk["id"]:
            raise ApiError("ERR_CROSS_KIOSK_REFERENCE")
        if pack_count > batch["max_pack_yield"]:
            raise ApiError("ERR_RICE_YIELD_EXCEEDED")

        plan = domain.plan_of_batch(batch)
        if (domain.live_packs_of_plan(plan["id"]) + pack_count
                > plan["planned_pack_count"]):
            raise ApiError("ERR_PACK_CAP_EXCEEDED")
        if (domain.live_packs_of_kiosk(kiosk["id"]) + pack_count
                > kiosk["daily_pack_cap"]):
            raise ApiError("ERR_PACK_CAP_EXCEEDED")

        store = domain.store_of_kiosk(kiosk)
        attested = store["attested_case_linear_ft"] or 0
        case_capacity = floor_int(dec(attested) * calc.PACKS_PER_LINEAR_FT)
        if (domain.live_packs_of_store(store["id"]) + pack_count
                > case_capacity):
            raise ApiError("ERR_CASE_CAPACITY_EXCEEDED")

        consumed = round_half_up(dec(pack_count) * calc.FISH_KG_PER_PACK, 3)
        if consumed > dec(fish["remaining_kg"]):
            raise ApiError("ERR_INSUFFICIENT_FISH_INVENTORY")

        row = db.new_row(db.pack_lots, {
            "rice_batch_id": batch["id"],
            "fish_lot_id": fish["id"],
            "sku_code": sku_code,
            "pack_count": pack_count,
            "list_price_cents": list_price_cents,
            "produced_at": iso_instant(produced_at),
            "shelf_expiry_at": iso_instant(
                produced_at + timedelta(minutes=calc.SHELF_LIFE_MINUTES)),
            "status": "ON_SHELF",
            "markdown_price_cents": None,
            "advisory_markdown_price_cents": None,
            "markdown_variant_applied": None,
            "consumed_fish_kg": float(consumed),
            "sold_count": 0,
            "discarded_count": 0,
            "unsold_count": pack_count,
            "void_reason": None,
        })

        batch["status"] = "CONSUMED"
        db.touch(batch)
        domain.refresh_fish_mass(fish)
        domain.refresh_plan_actual(plan)
    return created(db.public(row))


@bp.get("/pack-lots/<lot_id>")
def get_pack_lot(lot_id):
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER,
                      ROLE_FRANCHISE_CHEF, ROLE_QUALITY_AUDITOR)
    lot = pack_lot_or_404(lot_id)
    _scope_lot(actor, lot)
    return ok(db.public(lot))


@bp.get("/pack-lots")
def list_pack_lots():
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER,
                      ROLE_FRANCHISE_CHEF, ROLE_QUALITY_AUDITOR)
    rows = list(db.pack_lots.values())
    if actor.is_chef:
        chef = db.chefs.get(actor.user_id)
        assigned = chef["assigned_kiosk_id"] if chef else None
        rows = [r for r in rows
                if (domain.kiosk_of_pack_lot(r) or {}).get("id") == assigned]
    elif actor.is_manager:
        rows = [r for r in rows
                if (domain.store_of_kiosk(domain.kiosk_of_pack_lot(r))
                    or {}).get("id") == actor.user_id]
    rows = filters(rows, {
        "rice_batch_id": "rice_batch_id",
        "fish_lot_id": "fish_lot_id",
        "sku_code": "sku_code",
        "status": "status",
    })
    return paginate(rows)


@bp.post("/pack-lots/<lot_id>/markdown")
def markdown_pack_lot(lot_id):
    actor = authorize(ROLE_FRANCHISE_CHEF)
    lot = pack_lot_or_404(lot_id)
    _scope_lot(actor, lot)
    with LOCK:
        if lot["status"] != "ON_SHELF" or lot["unsold_count"] <= 0:
            raise ApiError("ERR_PACK_LOT_INVALID_STATE")
        expiry = parse_instant(lot["shelf_expiry_at"])
        now = logical_now()
        if now >= expiry:
            raise ApiError("ERR_PACK_SHELF_LIFE_EXPIRED")
        remaining = whole_minutes_between(now, expiry)
        remaining = max(0, min(calc.SHELF_LIFE_MINUTES, remaining))
        agreement = domain.agreement_of_pack_lot(lot)
        policy = agreement["markdown_policy"] if agreement else "FLAT_STEP"
        prices = calc.pack_markdown_price(lot["list_price_cents"], remaining,
                                          policy)
        lot["markdown_price_cents"] = prices["markdown_price_cents"]
        lot["advisory_markdown_price_cents"] = \
            prices["advisory_markdown_price_cents"]
        lot["markdown_variant_applied"] = prices["markdown_variant_applied"]
        lot["status"] = "MARKED_DOWN"
        db.touch(lot)
    return ok(db.public(lot))


@bp.post("/pack-lots/<lot_id>/discard")
def discard_pack_lot_route(lot_id):
    actor = authorize(ROLE_FRANCHISE_CHEF, ROLE_QUALITY_AUDITOR)
    lot = pack_lot_or_404(lot_id)
    _scope_lot(actor, lot)
    payload = body()
    reason = req_enum(payload, "reason", calc.DISCARD_REASONS)
    with LOCK:
        if lot["status"] not in domain.LIVE_PACK_STATES or lot["unsold_count"] <= 0:
            raise ApiError("ERR_PACK_LOT_INVALID_STATE")
        domain.discard_pack_lot(lot, reason)
    return ok(db.public(lot))


@bp.get("/pack-lots/<lot_id>/discard-events")
def list_discard_events(lot_id):
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER,
                      ROLE_QUALITY_AUDITOR)
    lot = pack_lot_or_404(lot_id)
    _scope_lot(actor, lot)
    rows = [e for e in db.discard_events.values()
            if e["pack_lot_id"] == lot["id"]]
    rows = filters(rows, {"reason": "reason"})
    return paginate(rows)


@bp.post("/pack-lots/<lot_id>/void")
def void_pack_lot_route(lot_id):
    authorize(ROLE_FRANCHISOR_OPS)
    lot = pack_lot_or_404(lot_id)
    payload = body()
    reason = req_str(payload, "void_reason")
    with LOCK:
        if lot["status"] != "ON_SHELF" or lot["sold_count"] != 0:
            raise ApiError("ERR_PACK_LOT_INVALID_STATE")
        domain.void_pack_lot(lot, reason)
    return ok(db.public(lot))
