"""Flat single-get + filtered-list routes (PRD §2.5 reverse reachability).
Every child entity is reachable by id and filterable by any foreign key it
carries, independent of the nested hierarchy."""

from flask import Blueprint, request

import db
from domain import (
    sorted_rows, ser_cell_lot, ser_inspection, ser_bom, ser_pack,
    ser_weld_record, ser_firmware, ser_approval, ser_flash_record,
    ser_dossier, ser_location, ser_placement, ser_shipment, ser_link,
    ser_rma, ser_recall,
)
from errors import (
    err_lot_not_found, err_bom_not_found, err_pack_not_found,
    err_weld_record_not_found, err_firmware_not_found, err_dossier_not_found,
    err_location_not_found, err_placement_not_found, err_shipment_not_found,
    err_rma_not_found, err_recall_not_found, err_not_found,
)
from middleware import require_roles
from response import success_object, success_list

bp = Blueprint("flat", __name__)

# path-prefix -> (collection, serializer, not-found constructor, filter fields)
FLAT_RESOURCES = {
    "cell-lots": (db.cell_lots, ser_cell_lot, err_lot_not_found, ("program_id",)),
    "cell-inspection-records": (
        db.inspections, ser_inspection, err_not_found, ("cell_lot_id", "program_id"),
    ),
    "pack-boms": (db.boms, ser_bom, err_bom_not_found, ("program_id", "cell_lot_id")),
    "battery-packs": (
        db.packs, ser_pack, err_pack_not_found,
        ("program_id", "bom_id", "cell_lot_id", "bms_firmware_id",
         "dossier_id", "storage_location_id", "active_recall_id"),
    ),
    "welding-parameter-records": (
        db.weld_records, ser_weld_record, err_weld_record_not_found,
        ("battery_pack_id", "program_id"),
    ),
    "bms-firmwares": (
        db.firmwares, ser_firmware, err_firmware_not_found,
        ("program_id", "approval_record_id"),
    ),
    "firmware-approvals": (
        db.approvals, ser_approval, err_not_found, ("bms_firmware_id", "program_id"),
    ),
    "bms-flash-records": (
        db.flash_records, ser_flash_record, err_not_found,
        ("battery_pack_id", "bms_firmware_id", "program_id"),
    ),
    "safety-test-dossiers": (
        db.dossiers, ser_dossier, err_dossier_not_found,
        ("battery_pack_id", "program_id"),
    ),
    "storage-locations": (
        db.locations, ser_location, err_location_not_found, ("program_id",),
    ),
    "storage-placements": (
        db.placements, ser_placement, err_placement_not_found,
        ("storage_location_id", "battery_pack_id", "program_id"),
    ),
    "transport-shipments": (
        db.shipments, ser_shipment, err_shipment_not_found, ("program_id",),
    ),
    "shipment-pack-links": (
        db.links, ser_link, err_not_found,
        ("transport_shipment_id", "battery_pack_id", "program_id"),
    ),
    "return-authorizations": (
        db.rmas, ser_rma, err_rma_not_found, ("program_id", "battery_pack_id"),
    ),
    "recall-campaigns": (
        db.recalls, ser_recall, err_recall_not_found,
        ("program_id", "scope_lot_id", "scope_bom_id"),
    ),
}


def _register(prefix, collection, serializer, not_found, filters):
    single_rule = "/%s/<rid>" % prefix
    list_rule = "/%s" % prefix

    def get_one(actor, rid, _c=collection, _s=serializer, _nf=not_found):
        row = _c.get(rid)
        if row is None:
            raise _nf()
        return success_object(_s(row))

    def get_list(actor, _c=collection, _s=serializer, _f=filters):
        rows = list(_c.values())
        for f in _f:
            v = request.args.get(f)
            if v is not None:
                rows = [r for r in rows if r.get(f) == v]
        return success_list(sorted_rows(rows), _s)

    bp.add_url_rule(
        single_rule,
        "flat_get_" + prefix,
        require_roles()(get_one),
        methods=["GET"],
    )
    bp.add_url_rule(
        list_rule,
        "flat_list_" + prefix,
        require_roles()(get_list),
        methods=["GET"],
    )


for _prefix, (_coll, _ser, _nf, _filters) in FLAT_RESOURCES.items():
    _register(_prefix, _coll, _ser, _nf, _filters)
