"""Raw fish sourcing, parasite destruction and the cold chain -- PRD 3.6."""

from flask import Blueprint

import db
from core import (LOCK, dec, iso_instant, parse_instant, whole_hours_between)
from errors import ApiError
from middleware import (ROLE_FRANCHISE_CHEF, ROLE_FRANCHISOR_OPS,
                        ROLE_QUALITY_AUDITOR, authorize, body, req_enum,
                        req_instant, req_num, req_str, strictly_ordered)
from response import created, ok
from routes.base import (chef_or_404, fish_lot_or_404, fk_lookup, filters,
                         kiosk_or_404, paginate)
from services import calc, domain

bp = Blueprint("fish", __name__)

SPECIES = ("TUNA_YELLOWFIN", "SALMON_ATLANTIC", "HAMACHI", "SHRIMP_COOKED")
HARVEST_METHODS = ("WILD", "AQUACULTURE_EXEMPT")
DESTRUCTION_METHODS = ("FREEZE_MINUS20_7DAYS", "FREEZE_MINUS35_15HRS",
                       "FREEZE_MINUS35_THEN_MINUS20_24HRS")


def _scope_lot(actor, lot):
    if not actor.is_chef:
        return
    chef = db.chefs.get(actor.user_id)
    if chef is None or chef["assigned_kiosk_id"] != lot["kiosk_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")


@bp.post("/fish-lots")
def receive_lot():
    actor = authorize(ROLE_FRANCHISE_CHEF)
    payload = body()
    chef = db.chefs.get(actor.user_id)
    if chef is None or chef["assigned_kiosk_id"] != payload.get("kiosk_id"):
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    kiosk = fk_lookup(payload, "kiosk_id", kiosk_or_404)
    req_str(payload, "kiosk_id")
    species = req_enum(payload, "species", SPECIES)
    supplier_code = req_str(payload, "supplier_code")
    harvest_method = req_enum(payload, "harvest_method", HARVEST_METHODS)
    net_weight_kg = req_num(payload, "net_weight_kg", exclusive_minimum=0)
    received_at = req_instant(payload, "received_at")
    receiving_temp_c = req_num(payload, "receiving_temp_c")

    required = calc.parasite_destruction_required(species, harvest_method)
    with LOCK:
        row = db.new_row(db.fish_lots, {
            "kiosk_id": kiosk["id"],
            "species": species,
            "supplier_code": supplier_code,
            "harvest_method": harvest_method,
            "net_weight_kg": float(net_weight_kg),
            "received_at": iso_instant(received_at),
            "receiving_temp_c": float(receiving_temp_c),
            "status": "RECEIVED",
            "parasite_destruction_required": required,
            "destruction_method": None,
            "freeze_start_at": None,
            "freeze_end_at": None,
            "freeze_min_temp_c": None,
            "freeze_effective_hours": None,
            "parasite_destruction_compliant": not required,
            "attested_by_chef_id": None,
            "cold_chain_breach_minutes": 0,
            "allocated_kg": 0.0,
            "remaining_kg": float(net_weight_kg),
            "quarantine_reason": None,
        })
    return created(db.public(row))


@bp.get("/fish-lots/<lot_id>")
def get_lot(lot_id):
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_FRANCHISE_CHEF, ROLE_QUALITY_AUDITOR)
    lot = fish_lot_or_404(lot_id)
    _scope_lot(actor, lot)
    return ok(db.public(lot))


@bp.get("/fish-lots")
def list_lots():
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_FRANCHISE_CHEF, ROLE_QUALITY_AUDITOR)
    rows = list(db.fish_lots.values())
    if actor.is_chef:
        chef = db.chefs.get(actor.user_id)
        assigned = chef["assigned_kiosk_id"] if chef else None
        rows = [r for r in rows if r["kiosk_id"] == assigned]
    rows = filters(rows, {
        "kiosk_id": "kiosk_id",
        "attested_by_chef_id": "attested_by_chef_id",
        "species": "species",
        "status": "status",
    })
    return paginate(rows)


@bp.post("/fish-lots/<lot_id>/parasite-destruction")
def parasite_destruction(lot_id):
    actor = authorize(ROLE_FRANCHISE_CHEF)
    lot = fish_lot_or_404(lot_id)
    _scope_lot(actor, lot)
    payload = body()
    attesting = fk_lookup(payload, "attested_by_chef_id", chef_or_404)
    method = req_enum(payload, "destruction_method", DESTRUCTION_METHODS)
    freeze_start_at = req_instant(payload, "freeze_start_at")
    freeze_end_at = req_instant(payload, "freeze_end_at")
    freeze_min_temp_c = req_num(payload, "freeze_min_temp_c")
    req_str(payload, "attested_by_chef_id")
    strictly_ordered("freeze_start_at", freeze_start_at,
                     "freeze_end_at", freeze_end_at)

    with LOCK:
        if lot["status"] not in ("RECEIVED", "QUARANTINED"):
            raise ApiError("ERR_FISH_LOT_INVALID_STATE")
        effective_hours = whole_hours_between(freeze_start_at, freeze_end_at)
        compliant = calc.parasite_destruction_compliant(
            method, freeze_min_temp_c, effective_hours)
        if not lot["parasite_destruction_required"]:
            compliant = True
        db.apply_changes(lot, {
            "destruction_method": method,
            "freeze_start_at": iso_instant(freeze_start_at),
            "freeze_end_at": iso_instant(freeze_end_at),
            "freeze_min_temp_c": float(freeze_min_temp_c),
            "freeze_effective_hours": float(effective_hours),
            "parasite_destruction_compliant": compliant,
            "attested_by_chef_id": attesting["id"],
        })
    return ok(db.public(lot))


@bp.post("/fish-lots/<lot_id>/cold-chain-readings")
def append_reading(lot_id):
    actor = authorize(ROLE_FRANCHISE_CHEF, ROLE_QUALITY_AUDITOR)
    lot = fish_lot_or_404(lot_id)
    _scope_lot(actor, lot)
    payload = body()
    recorded_at = req_instant(payload, "recorded_at")
    temp_c = req_num(payload, "temp_c")

    with LOCK:
        if lot["status"] == "DESTROYED":
            raise ApiError("ERR_FISH_LOT_INVALID_STATE")
        reading = db.new_row(db.cold_chain_readings, {
            "fish_lot_id": lot["id"],
            "recorded_at": iso_instant(recorded_at),
            "temp_c": float(temp_c),
            "interval_minutes_from_previous": None,
            "breach_minutes_attributed": 0,
            "lot_breach_minutes_after": 0,
        }, versioned=False)
        total = domain.recompute_cold_chain(lot)
        db.apply_changes(lot, {"cold_chain_breach_minutes": total})

        if (total > calc.QUARANTINE_BREACH_MINUTES
                and lot["status"] in ("RECEIVED", "RELEASED")):
            was_released = lot["status"] == "RELEASED"
            lot["status"] = "QUARANTINED"
            lot["quarantine_reason"] = "COLD_CHAIN_BREACH"
            db.touch(lot)
            if was_released:
                for pack in domain.pack_lots_of_fish_lot(lot["id"]):
                    if pack["status"] in domain.LIVE_PACK_STATES:
                        domain.discard_pack_lot(pack, "TEMP_ABUSE")
            kiosk = db.kiosks.get(lot["kiosk_id"])
            if kiosk is not None:
                domain.rederive_kiosk(kiosk)
    return created(db.public(reading))


@bp.get("/fish-lots/<lot_id>/cold-chain-readings")
def list_readings(lot_id):
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_FRANCHISE_CHEF, ROLE_QUALITY_AUDITOR)
    lot = fish_lot_or_404(lot_id)
    _scope_lot(actor, lot)
    # PRD 2.11: "Both lists are paginated and ordered as §2.3 requires; the
    # reading list, being ordered by `created_at` ascending, is also in
    # `recorded_at` ascending order because readings may only be appended forward
    # in time." The stored order is therefore §2.3's created_at ascending; the
    # recorded_at ordering used to *process* the series (PRD 3.6) is separate.
    return paginate(domain.readings_of_fish_lot(lot["id"]))


@bp.post("/fish-lots/<lot_id>/release")
def release_lot(lot_id):
    authorize(ROLE_QUALITY_AUDITOR)
    lot = fish_lot_or_404(lot_id)
    payload = body()
    rationale = payload.get("release_rationale")
    with LOCK:
        if lot["status"] not in ("RECEIVED", "QUARANTINED"):
            raise ApiError("ERR_FISH_LOT_INVALID_STATE")
        if lot["parasite_destruction_required"] \
                and not lot["parasite_destruction_compliant"]:
            raise ApiError("ERR_PARASITE_DESTRUCTION_INCOMPLETE")
        if lot["status"] == "QUARANTINED":
            if not isinstance(rationale, str) or not rationale.strip():
                raise ApiError("ERR_COLD_CHAIN_BREACH_BLOCKS_RELEASE")
        elif lot["cold_chain_breach_minutes"] > calc.QUARANTINE_BREACH_MINUTES:
            raise ApiError("ERR_COLD_CHAIN_BREACH_BLOCKS_RELEASE")

        lot["status"] = "RELEASED"
        lot["quarantine_reason"] = None
        db.touch(lot)
        domain.refresh_fish_mass(lot)
        # PRD 3.3 counts "six points for each of the kiosk's fish lots *currently*
        # `QUARANTINED` with `quarantine_reason` `COLD_CHAIN_BREACH`", so clearing
        # the quarantine changes a risk input and the kiosk re-derives.
        kiosk = db.kiosks.get(lot["kiosk_id"])
        if kiosk is not None:
            domain.rederive_kiosk(kiosk)
    return ok(db.public(lot))


@bp.post("/fish-lots/<lot_id>/destroy")
def destroy_lot(lot_id):
    authorize(ROLE_QUALITY_AUDITOR)
    lot = fish_lot_or_404(lot_id)
    payload = body()
    req_str(payload, "destruction_rationale")
    with LOCK:
        if lot["status"] not in ("RECEIVED", "QUARANTINED"):
            raise ApiError("ERR_FISH_LOT_INVALID_STATE")
        lot["status"] = "DESTROYED"
        lot["remaining_kg"] = 0.0
        db.touch(lot)
        # A destroyed lot is no longer "currently `QUARANTINED`" (PRD 3.3), so the
        # kiosk's risk total loses those six points.
        kiosk = db.kiosks.get(lot["kiosk_id"])
        if kiosk is not None:
            domain.rederive_kiosk(kiosk)
    return ok(db.public(lot))
