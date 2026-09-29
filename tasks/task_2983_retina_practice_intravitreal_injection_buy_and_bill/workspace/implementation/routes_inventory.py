"""Drug lots, vials, exposure reads and the expiration sweep. PRD 3.5."""
from flask import Blueprint, request

import core
from core import (
    DB,
    Field,
    READ_ROLES,
    ROLE_ADMIN,
    ROLE_BILLING,
    ROLE_COMPLIANCE,
    ROLE_TECH,
    base_row,
    created,
    fail,
    get_body,
    get_drug,
    get_lot,
    get_vial,
    iso3,
    listing,
    ok,
    pagination,
    query_filters,
    touch,
    validate,
)
from domain import (
    carrying_exposure_cents,
    lot_exposure,
    lot_vials,
    open_recall_for_lot,
    recompute_lot_counters,
)
from core import whole_days

bp = Blueprint("inventory", __name__)

LOT_STATUSES = ["AVAILABLE", "QUARANTINED", "RECALLED", "EXPIRED"]
VIAL_STATUSES = [
    "IN_STOCK",
    "RESERVED",
    "ADMINISTERED",
    "QUARANTINED",
    "RETURNED",
    "EXPIRED",
]
EXPOSURE_BASES = ["CARRYING", "EXPIRATION"]


# -------------------------------------------------------------------- receipt
@bp.post("/drug-lots")
@core.api([ROLE_TECH])
def create_drug_lot():
    body = get_body()
    values = validate(
        body,
        [
            Field("drug_id", "id", required=True),
            Field("lot_number", "string", required=True, minlen=3, maxlen=24),
            Field("expiration_date", "datetime", required=True),
            Field("received_date", "datetime", required=True),
            Field("unit_acquisition_cost_cents", "integer", required=True, minimum=0),
            Field("vials_received", "integer", required=True, minimum=1, maximum=500),
        ],
    )
    get_drug(values["drug_id"])
    for row in DB.lots.values():
        if row["drug_id"] == values["drug_id"] and row["lot_number"] == values["lot_number"]:
            fail("ERR_DUPLICATE_LOT_NUMBER", "lot_number already received for this drug")

    lot = base_row()
    lot.update(
        {
            "drug_id": values["drug_id"],
            "lot_number": values["lot_number"],
            "expiration_date": values["expiration_date"],
            "received_date": values["received_date"],
            "unit_acquisition_cost_cents": values["unit_acquisition_cost_cents"],
            "vials_received": values["vials_received"],
            "vials_on_hand": values["vials_received"],
            "vials_reserved": 0,
            "vials_administered": 0,
            "vials_quarantined": 0,
            "vials_returned": 0,
            "vials_expired": 0,
            "status": "AVAILABLE",
            "quarantine_reason": None,
            "carrying_cost_accrued_cents": 0,
            "last_swept_at": None,
            "related_endophthalmitis_count": 0,
        }
    )
    DB.lots[lot["id"]] = lot

    for index in range(1, values["vials_received"] + 1):
        vial = base_row()
        vial.update(
            {
                "drug_lot_id": lot["id"],
                "serial_number": "%s-%03d" % (values["lot_number"], index),
                "status": "IN_STOCK",
                "reserved_for_encounter_id": None,
                "reserved_at": None,
                "administered_at": None,
            }
        )
        DB.vials[vial["id"]] = vial
    return created(lot)


@bp.get("/drug-lots/<lid>")
@core.api(READ_ROLES)
def read_drug_lot(lid):
    return ok(get_lot(lid))


@bp.get("/drug-lots")
@core.api(READ_ROLES)
def list_drug_lots():
    limit, offset = pagination()
    filters = query_filters(
        {
            "drug_id": ("drug_id", "string"),
            "lot_number": ("lot_number", "string"),
            "status": ("status", "enum", LOT_STATUSES),
            "expiration_date": ("expiration_date", "datetime"),
        }
    )
    return listing(DB.lots.values(), filters, limit, offset)


# ------------------------------------------------------------------- exposure
@bp.get("/drug-lots/<lid>/exposure")
@core.api([ROLE_ADMIN, ROLE_TECH, ROLE_BILLING])
def read_lot_exposure(lid):
    supplied = {}
    if "basis" in request.args:
        supplied["basis"] = request.args.get("basis")
    basis = validate(supplied, [Field("basis", "enum", required=True, values=EXPOSURE_BASES)])[
        "basis"
    ]
    lot = get_lot(lid)
    return ok(lot_exposure(lot, basis))


# ------------------------------------------------------------------ quarantine
@bp.post("/drug-lots/<lid>/quarantine")
@core.api([ROLE_TECH])
def quarantine_lot(lid):
    body = get_body()
    values = validate(body, [Field("quarantine_reason", "string", required=True, minlen=1)])
    lot = get_lot(lid)
    if lot["status"] != "AVAILABLE":
        fail("ERR_LOT_STATE_INVALID", "only an AVAILABLE lot may be quarantined")
    lot["status"] = "QUARANTINED"
    lot["quarantine_reason"] = values["quarantine_reason"]
    touch(lot)
    for vial in lot_vials(lot["id"]):
        if vial["status"] == "IN_STOCK":
            vial["status"] = "QUARANTINED"
            touch(vial)
    recompute_lot_counters(lot)
    return ok(lot)


@bp.post("/drug-lots/<lid>/release")
@core.api([ROLE_COMPLIANCE])
def release_lot(lid):
    get_body()
    lot = get_lot(lid)
    if lot["status"] != "QUARANTINED":
        fail("ERR_LOT_STATE_INVALID", "only a QUARANTINED lot may be released")
    if open_recall_for_lot(lot["id"]) is not None:
        fail("ERR_RECALL_ALREADY_OPEN", "an open recall blocks release of this lot")
    if not lot["expiration_date"] > DB.clock:
        fail("ERR_LOT_STATE_INVALID", "an expired lot may not be released")
    lot["status"] = "AVAILABLE"
    lot["quarantine_reason"] = None
    touch(lot)
    for vial in lot_vials(lot["id"]):
        if vial["status"] == "QUARANTINED" and vial["reserved_for_encounter_id"] is None:
            vial["status"] = "IN_STOCK"
            touch(vial)
    recompute_lot_counters(lot)
    return ok(lot)


# ---------------------------------------------------------------------- sweep
@bp.post("/inventory/expiration-sweep")
@core.api([ROLE_TECH])
def expiration_sweep():
    get_body()
    lots_swept = 0
    lots_expired = 0
    vials_expired = 0
    total = 0
    from core import ordered

    for lot in ordered(DB.lots.values()):
        lots_swept += 1
        days_held = whole_days(lot["received_date"], DB.clock)
        accrued = carrying_exposure_cents(lot, days_held)
        lot["carrying_cost_accrued_cents"] = accrued
        lot["last_swept_at"] = DB.clock
        touch(lot)
        if lot["status"] == "AVAILABLE" and lot["expiration_date"] <= DB.clock:
            lot["status"] = "EXPIRED"
            for vial in lot_vials(lot["id"]):
                if vial["status"] == "IN_STOCK":
                    vial["status"] = "EXPIRED"
                    vials_expired += 1
                    touch(vial)
            recompute_lot_counters(lot)
            touch(lot)
            lots_expired += 1
        total += int(lot["carrying_cost_accrued_cents"])

    return ok(
        {
            "lots_swept": lots_swept,
            "lots_expired": lots_expired,
            "vials_expired": vials_expired,
            "carrying_cost_accrued_cents_total": total,
            "swept_at": iso3(DB.clock),
        }
    )


# ---------------------------------------------------------------------- vials
@bp.get("/vials/<vid>")
@core.api(READ_ROLES)
def read_vial(vid):
    return ok(get_vial(vid))


@bp.get("/vials")
@core.api(READ_ROLES)
def list_vials():
    limit, offset = pagination()
    filters = query_filters(
        {
            "drug_lot_id": ("drug_lot_id", "string"),
            "serial_number": ("serial_number", "string"),
            "reserved_for_encounter_id": ("reserved_for_encounter_id", "string"),
            "status": ("status", "enum", VIAL_STATUSES),
        }
    )
    return listing(DB.vials.values(), filters, limit, offset)
