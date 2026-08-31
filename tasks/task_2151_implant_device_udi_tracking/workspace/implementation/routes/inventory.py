"""Lots, serialized device units, the quarantine gate and stock removal."""
from flask import Blueprint

import serialize
from auth import ALL_ROLES, CIRC_CLINICIAN, INVENTORY_LEAD, RECEIVING_TECH, actor, endpoint
from derive import (
    detach_reservation,
    lot_unit_conservation,
    recompute_catalog_available,
    set_billing,
    set_custody,
    vendor_open_consignment_liability,
)
from envelope import array_response, object_response
from errors import ApiError
from graph import catalog_of_lot, units_of_catalog, units_of_lot, vendor_of_catalog
from resolve import maybe, must
from store import base_record, clock_iso, db, ordered, touch
from validation import (
    apply_page,
    body,
    filter_enum,
    filter_value,
    opt_str,
    pagination,
    req_date_str,
    req_int,
    req_str,
)

bp = Blueprint("inventory", __name__)

CUSTODY_STATES = (
    "QUARANTINED",
    "AVAILABLE",
    "RESERVED",
    "IMPLANTED",
    "EXPLANTED",
    "RECALL_HOLD",
    "EXPIRED",
    "WASTED",
    "RETURNED_TO_VENDOR",
    "DISPOSED",
)
BILLING_STATES = (
    "NOT_BILLABLE",
    "BILLABLE",
    "INVOICED",
    "RECONCILED",
    "CREDIT_PENDING",
    "CREDITED",
)
LOT_STATES = ("QUARANTINE", "AVAILABLE", "RECALLED", "EXPIRED", "DEPLETED")


# --------------------------------------------------------------------- lots
@bp.route("/udi/lots", methods=["POST"])
@endpoint([RECEIVING_TECH])
def create_lot():
    data = body()
    catalog_item_id = req_str(data, "catalog_item_id")
    lot_number = req_str(data, "lot_number")
    expiration_date = req_date_str(data, "expiration_date")

    item = must("catalog_item_id", catalog_item_id)

    for existing in db.lots.values():
        if existing["catalog_item_id"] == item["id"] and existing["lot_number"] == lot_number:
            raise ApiError("ERR_DUPLICATE_LOT_NUMBER", "lot_number already exists for this item.")

    record = base_record()
    record.update(
        {
            "catalog_item_id": item["id"],
            "lot_number": lot_number,
            "expiration_date": expiration_date,
            "status": "QUARANTINE",
            "received_at_utc": clock_iso(),
            "received_by_user_id": actor(),
            "released_by_user_id": None,
            "received_qty": 0,
            "on_hand_qty": 0,
            "consumed_qty": 0,
        }
    )
    db.lots[record["id"]] = record
    return object_response(serialize.lot(record), 201)


@bp.route("/udi/lots/<lot_id>/device-units", methods=["POST"])
@endpoint([RECEIVING_TECH])
def create_device_unit(lot_id):
    data = body()
    udi_serial = req_str(data, "udi_serial")
    acquisition_cost_cents = req_int(data, "acquisition_cost_cents", 1)
    expected_lot_version = req_int(data, "expected_lot_version")
    agreement_id = opt_str(data, "consignment_agreement_id")
    replaced_unit_id = opt_str(data, "replaced_unit_id")

    lot = must("lot_id", lot_id)                                    # step 4
    agreement = maybe("consignment_agreement_id", agreement_id)     # step 5
    maybe("replaced_unit_id", replaced_unit_id)

    if expected_lot_version != lot["version"]:                      # step 7
        raise ApiError("ERR_STALE_LOT_VERSION", "expected_lot_version does not match the lot.")

    if lot["status"] != "QUARANTINE":                               # step 8
        raise ApiError(
            "ERR_INVALID_LIFECYCLE_STATE", "Units may only be added while the lot is in QUARANTINE."
        )

    if agreement is not None and agreement["status"] != "ACTIVE":   # step 17
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", "The consignment agreement is not ACTIVE.")

    item = catalog_of_lot(lot)                                      # step 19
    for existing in units_of_catalog(item["id"]):
        if existing["udi_serial"] == udi_serial:
            raise ApiError(
                "ERR_DUPLICATE_UDI_SERIAL", "udi_serial already exists for this catalog item."
            )

    record = base_record()
    record.update(
        {
            "lot_id": lot["id"],
            "consignment_agreement_id": agreement["id"] if agreement else None,
            "vendor_invoice_id": None,
            "reserved_case_id": None,
            "replaced_unit_id": replaced_unit_id,
            "udi_serial": udi_serial,
            "udi_di_snapshot": item["device_identifier"],
            "custody_state": "QUARANTINED",
            "billing_state": "NOT_BILLABLE",
            "ownership": "CONSIGNED" if agreement else "OWNED",
            "acquisition_cost_cents": acquisition_cost_cents,
            "contract_price_cents": None,
            "price_list_version_at_billing": None,
            "implanted_at_utc": None,
            "expired_at_utc": None,
        }
    )
    db.device_units[record["id"]] = record
    lot_unit_conservation(lot)
    return object_response(serialize.device_unit(record), 201)


@bp.route("/udi/lots/<lot_id>/release", methods=["POST"])
@endpoint([RECEIVING_TECH, INVENTORY_LEAD])
def release_lot(lot_id):
    lot = must("lot_id", lot_id)

    if lot["status"] != "QUARANTINE":                               # step 8
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE", "Only a QUARANTINE lot can be released.")
    if lot.get("received_qty", 0) < 1:
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE", "An empty lot has nothing to inspect.")

    if actor() == lot.get("received_by_user_id"):                   # step 9
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The receiver of a lot may not release it from quarantine."
        )

    lot["status"] = "AVAILABLE"
    lot["released_by_user_id"] = actor()
    touch(lot)

    for unit in units_of_lot(lot["id"]):
        if unit["custody_state"] == "QUARANTINED":
            set_custody(unit, "AVAILABLE")
            agreement = (
                db.agreements.get(unit["consignment_agreement_id"])
                if unit.get("consignment_agreement_id")
                else None
            )
            if (
                unit["ownership"] == "CONSIGNED"
                and agreement is not None
                and agreement["status"] == "ACTIVE"
                and agreement["billing_trigger"] == "ON_RECEIPT"
                and unit["billing_state"] == "NOT_BILLABLE"
            ):
                unit["contract_price_cents"] = unit["acquisition_cost_cents"]
                unit["price_list_version_at_billing"] = agreement["price_list_version"]
                set_billing(unit, "BILLABLE")

    lot_unit_conservation(lot)
    recompute_catalog_available(catalog_of_lot(lot))
    vendor_open_consignment_liability(vendor_of_catalog(catalog_of_lot(lot)))
    return object_response(serialize.lot(lot))


@bp.route("/udi/lots/<lot_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_lot(lot_id):
    return object_response(serialize.lot(must("lot_id", lot_id)))


@bp.route("/udi/lots", methods=["GET"])
@endpoint(ALL_ROLES)
def list_lots():
    limit, offset = pagination()
    catalog_item_id = filter_value("catalog_item_id")
    status = filter_enum("status", LOT_STATES)
    rows = []
    for row in db.lots.values():
        if catalog_item_id is not None and row["catalog_item_id"] != catalog_item_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    page, total = apply_page(ordered(rows), limit, offset)
    return array_response([serialize.lot(r) for r in page], limit, offset, total)


# ------------------------------------------------------------- device units
@bp.route("/udi/device-units/<device_unit_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_device_unit(device_unit_id):
    return object_response(serialize.device_unit(must("device_unit_id", device_unit_id)))


@bp.route("/udi/device-units", methods=["GET"])
@endpoint(ALL_ROLES)
def list_device_units():
    limit, offset = pagination()
    filters = {
        "lot_id": filter_value("lot_id"),
        "consignment_agreement_id": filter_value("consignment_agreement_id"),
        "vendor_invoice_id": filter_value("vendor_invoice_id"),
        "reserved_case_id": filter_value("reserved_case_id"),
        "replaced_unit_id": filter_value("replaced_unit_id"),
    }
    custody_state = filter_enum("custody_state", CUSTODY_STATES)
    billing_state = filter_enum("billing_state", BILLING_STATES)

    rows = []
    for row in db.device_units.values():
        skip = False
        for key, value in filters.items():
            if value is not None and row.get(key) != value:
                skip = True
                break
        if skip:
            continue
        if custody_state is not None and row["custody_state"] != custody_state:
            continue
        if billing_state is not None and row["billing_state"] != billing_state:
            continue
        rows.append(row)
    page, total = apply_page(ordered(rows), limit, offset)
    return array_response([serialize.device_unit(r) for r in page], limit, offset, total)


@bp.route("/udi/device-units/<device_unit_id>/release-reservation", methods=["POST"])
@endpoint([INVENTORY_LEAD, CIRC_CLINICIAN])
def release_reservation(device_unit_id):
    unit = must("device_unit_id", device_unit_id)

    if unit.get("reserved_case_id") is None or unit["custody_state"] != "RESERVED":
        raise ApiError("ERR_INVALID_UNIT_STATE", "The unit is not reserved.")

    case = db.cases.get(unit["reserved_case_id"])
    if case is not None and case["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_CASE_STATE", "The reserving case is no longer open.")

    detach_reservation(unit, blocked=False)
    set_custody(unit, "AVAILABLE")
    if case is not None:
        from derive import case_close_readiness

        case_close_readiness(case)
    return object_response(serialize.device_unit(unit))


@bp.route("/udi/device-units/<device_unit_id>/waste", methods=["POST"])
@endpoint([CIRC_CLINICIAN])
def waste_device_unit(device_unit_id):
    unit = must("device_unit_id", device_unit_id)

    if unit["custody_state"] not in ("AVAILABLE", "RESERVED"):
        raise ApiError("ERR_INVALID_UNIT_STATE", "Only AVAILABLE or RESERVED units can be wasted.")

    detach_reservation(unit, blocked=False)
    set_custody(unit, "WASTED")
    return object_response(serialize.device_unit(unit))
