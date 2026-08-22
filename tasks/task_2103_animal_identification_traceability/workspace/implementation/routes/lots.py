"""Tag lot issuance, voiding and device application (PRD 3.3 / 3.4)."""
from flask import Blueprint

import calc
import derive
import shape
from authz import (PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL, SUPPLIER_REP,
                   require_owner, require_roles)
from db import base_record, store, touch
from errors import conflict, invalid_request, invalid_state, stale_version, unprocessable
from respond import success
from routes._common import (lot_or_404, page, premises_or_404, supplier_or_404)
from serialize import public

bp = Blueprint("lots", __name__)

SPECIES = ("BOVINE", "OVINE", "CAPRINE", "CERVID")


def ain_in_lot(ain, lot, supplier):
    if ain[:3] != supplier["aid_prefix"]:
        return False
    serial = int(ain[3:])
    return lot["serial_start"] <= serial <= lot["serial_end"]


@bp.post("/tag-lots")
def create_lot():
    uid, role = require_roles(SUPPLIER_REP)
    body = shape.body()
    supplier_id = shape.s_str(body, "supplier_id")
    premises_id = shape.s_str(body, "premises_id")
    serial_start = shape.s_int(body, "serial_start", minimum=shape.SERIAL_MIN,
                               maximum=shape.SERIAL_MAX)
    serial_end = shape.s_int(body, "serial_end", minimum=shape.SERIAL_MIN,
                             maximum=shape.SERIAL_MAX)
    expected_version = shape.s_int(body, "expected_supplier_version")
    if serial_end < serial_start:
        raise invalid_request("serial_end may not be lower than serial_start")
    # Band 5 - body FK existence, left to right.
    supplier = supplier_or_404(supplier_id)
    premises = premises_or_404(premises_id)
    # Band 6 - a supplier rep issues only against its own supplier record.
    require_owner(uid == supplier["id"])
    # Band 9 - optimistic concurrency on the parent supplier.
    if expected_version != supplier["version"]:
        raise stale_version("expected_supplier_version does not match the supplier version")
    # Band 11 - cross-entity state gates.
    if supplier["status"] != "APPROVED":
        raise conflict("ERR_SUPPLIER_NOT_APPROVED", "The device supplier is not APPROVED")
    if premises["registration_status"] != "ACTIVE":
        raise conflict("ERR_PREMISES_NOT_ACTIVE", "The premises registration is not ACTIVE")
    # Band 15 - serial ranges may abut but never intersect.
    for lot in store.tag_lots.values():
        if lot["supplier_id"] != supplier["id"] or lot["status"] == "VOIDED":
            continue
        if serial_start <= lot["serial_end"] and lot["serial_start"] <= serial_end:
            raise conflict("ERR_SERIAL_RANGE_OVERLAP",
                           "The serial interval intersects an existing lot of this supplier")
    quantity = serial_end - serial_start + 1
    # Band 16 - capacity/quota, read against pre-request supplier state.
    if quantity > supplier["issuance_cap"]:
        raise conflict("ERR_ISSUANCE_CAP_EXCEEDED",
                       "The requested quantity exceeds the supplier's issuance cap")

    fee_cents, discount_pct, surcharge_cents = calc.issuance_fee(quantity,
                                                                 supplier["probation"])
    rec = base_record()
    rec.update({
        "supplier_id": supplier["id"],
        "premises_id": premises["id"],
        "serial_start": serial_start,
        "serial_end": serial_end,
        "quantity": quantity,
        "status": "ISSUED",
        "applied_count": 0,
        "retired_count": 0,
        "replaced_count": 0,
        "voided_count": 0,
        "unapplied_count": quantity,
        "fee_cents": fee_cents,
        "discount_pct_applied": discount_pct,
        "surcharge_cents": surcharge_cents,
    })
    store.tag_lots[rec["id"]] = rec
    derive.recompute_supplier(supplier, bump_version=True)
    return success(public(rec), status=201)


@bp.get("/tag-lots/<lot_id>")
def read_lot(lot_id):
    require_roles(SUPPLIER_REP, PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL)
    return success(public(lot_or_404(lot_id)))


@bp.get("/tag-lots")
def list_lots():
    require_roles(SUPPLIER_REP, PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL)
    limit, offset = shape.pagination_params()
    rows = list(store.tag_lots.values())
    for field in ("supplier_id", "premises_id", "status"):
        value = shape.q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return page(rows, limit, offset)


@bp.post("/tag-lots/<lot_id>/void")
def void_lot(lot_id):
    require_roles(PROGRAM_ADMIN)
    lot = lot_or_404(lot_id)
    if lot["status"] != "ISSUED":
        raise invalid_state("Only an untouched ISSUED lot may be voided")
    lot["status"] = "VOIDED"
    touch(lot)
    supplier = store.suppliers.get(lot["supplier_id"])
    if supplier is not None:
        derive.recompute_supplier(supplier, bump_version=True)
    return success(public(lot))


@bp.post("/tag-lots/<lot_id>/apply-tag")
def apply_tag(lot_id):
    uid, role = require_roles(PRODUCER)
    body = shape.body()
    ain = shape.s_str(body, "ain", pattern=shape.AIN_RE)
    species = shape.s_enum(body, "species", SPECIES)
    birth_date = shape.s_date(body, "birth_date")
    birth_premises_id = shape.s_str(body, "birth_premises_id")
    lot = lot_or_404(lot_id)
    birth_premises = premises_or_404(birth_premises_id)
    # Band 6 - the lot belongs to the acting producer through its premises.
    lot_premises = store.premises.get(lot["premises_id"])
    require_owner(lot_premises is not None and lot_premises["producer_id"] == uid)
    # Band 10 - a lot forced out of circulation cannot supply an application.
    if lot["status"] in ("RECALLED", "VOIDED"):
        raise conflict("ERR_LOT_NOT_ISSUABLE",
                       "The tag lot is RECALLED or VOIDED and cannot supply an application")
    # Band 11 - cross-entity state gates.
    supplier = store.suppliers.get(lot["supplier_id"])
    if supplier is None or supplier["status"] != "APPROVED":
        raise conflict("ERR_SUPPLIER_NOT_APPROVED", "The device supplier is not APPROVED")
    if birth_premises["registration_status"] != "ACTIVE":
        raise conflict("ERR_PREMISES_NOT_ACTIVE", "The premises registration is not ACTIVE")
    if birth_premises["health_status"] == "QUARANTINED":
        raise conflict("ERR_PREMISES_UNDER_HOLD", "The premises is under quarantine")
    # Band 14 - referential coherence.
    if not ain_in_lot(ain, lot, supplier):
        raise unprocessable("ERR_AIN_OUT_OF_LOT_RANGE",
                            "The AIN prefix or serial does not belong to this lot")
    if lot_premises["producer_id"] != birth_premises["producer_id"]:
        raise unprocessable("ERR_LOT_PREMISES_MISMATCH",
                            "The lot's premises and the application premises belong to different producers")
    # Band 15 - AIN uniqueness.
    if any(t["ain"] == ain for t in store.tags.values()):
        raise conflict("ERR_DUPLICATE_AIN", "Another tag already carries this ain")
    # Band 16 - exhaustion, then premises capacity.
    if lot["unapplied_count"] == 0:
        raise conflict("ERR_LOT_EXHAUSTED", "The lot has no unapplied serial left")
    if birth_premises["animal_count"] + 1 > birth_premises["capacity"]:
        raise conflict("ERR_PREMISES_AT_CAPACITY",
                       "Admitting one more animal would exceed the premises capacity")

    now = store.now()
    animal = base_record()
    animal.update({
        "ain": ain,
        "species": species,
        "birth_date": birth_date,
        "birth_premises_id": birth_premises["id"],
        "current_premises_id": None,
        "lifecycle_status": "ACTIVE",
        "trace_status": "NORMAL",
        "sighting_count": 0,
        "last_sequence_no": 0,
    })
    store.animals[animal["id"]] = animal

    tag = base_record()
    tag.update({
        "tag_lot_id": lot["id"],
        "ain": ain,
        "animal_id": animal["id"],
        "replaces_tag_id": None,
        "device_status": "APPLIED",
        "applied_at": now,
        "retired_at": None,
        "tag_returned": None,
        "carcass_ref": None,
    })
    store.tags[tag["id"]] = tag

    derive.append_sighting(animal, birth_premises["id"], "TAG_APPLIED", now)
    # The animal is brand new: its projection is materialised at version 1.
    animal["current_premises_id"] = birth_premises["id"]
    animal["sighting_count"] = 1
    animal["last_sequence_no"] = 1

    derive.recompute_lot(lot)
    derive.recompute_premises_animal_count([birth_premises["id"]])
    return success(public(animal), status=201)
