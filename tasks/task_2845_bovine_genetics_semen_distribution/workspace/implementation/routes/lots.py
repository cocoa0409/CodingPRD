"""Straw processing, the dose ledger and consignment requests (PRD 3.5, 3.8)."""

from flask import Blueprint

import auth
import calc
import cascades
import config
import envelope
import resolve
import serializers
import store
import validate
from errors import fail
from validate import F

bp = Blueprint("lots", __name__)


def origin_facility(lot):
    """The facility that hosted the booking behind this lot's ejaculate."""
    ejaculate = store.get("ejaculates", lot["ejaculate_id"])
    if ejaculate is None:
        return None
    booking = store.get("collection_bookings", ejaculate["booking_id"])
    if booking is None:
        return None
    return store.get("facilities", booking["facility_id"])


@bp.post("/ejaculates/<ejaculate_id>/straw-lots")
def create_straw_lot(ejaculate_id):
    values = validate.parse([
        F("product_line", "enum", required=True, enum=config.PRODUCT_LINES),
        F("straw_count", "integer", required=True, min=1),
        F("processing_cost_cents", "integer", required=True, min=1),
        F("sexing_purity_pct", "number", default=None, min=0, max=100),
    ])
    auth.require_role(config.ROLE_LAB_TECH)
    ejaculate = resolve.need("ejaculates", ejaculate_id)
    if ejaculate["qc_status"] != "ACCEPTED":
        fail("ERR_EJACULATE_STATE", "Straw processing requires an ACCEPTED ejaculate.")
    # The dose ceiling is aggregate across every lot cut from this ejaculate.
    already = 0
    for lot in store.DB["straw_lots"].values():
        if lot["ejaculate_id"] == ejaculate["id"]:
            already += int(lot["straw_count"])
    if already + int(values["straw_count"]) > int(ejaculate["total_doses_theoretical"]):
        fail("ERR_DOSE_CAP_EXCEEDED",
             "The aggregate straw count would exceed the ejaculate's theoretical dose ceiling.")
    purity = values["sexing_purity_pct"]
    if values["product_line"] == "SEXED":
        if purity is None or calc.D(purity) < calc.D("50.0") or calc.D(purity) > calc.D("99.9"):
            fail("ERR_PRODUCT_LINE_FIELDS", "A SEXED lot requires sexing_purity_pct in 50.0-99.9.")
    elif purity is not None:
        fail("ERR_PRODUCT_LINE_FIELDS",
             "sexing_purity_pct must be omitted on a CONVENTIONAL or EMBRYO lot.")
    rec = store.new_record("straw_lots", {
        "ejaculate_id": ejaculate["id"],
        "sire_id": ejaculate["sire_id"],
        "product_line": values["product_line"],
        "straw_count": values["straw_count"],
        "sexing_purity_pct": purity,
        "processing_cost_cents": values["processing_cost_cents"],
        "distribution_status": "QUARANTINE",
        "doses_available": values["straw_count"],
        "doses_reserved": 0,
        "doses_consigned": 0,
        "doses_used": 0,
        "doses_destroyed": 0,
        "unit_book_value_cents": calc.lot_standard_unit_value(
            values["processing_cost_cents"], values["straw_count"]),
        "valuation_basis": "STANDARD_COST",
        "pre_revaluation_unit_value_cents": None,
        "_pre_revaluation_basis": None,
        "released_by_user_id": None,
        "rejected_reason": None,
        "release_note": None,
    })
    return envelope.created(serializers.straw_lot(rec))


@bp.get("/straw-lots/<lot_id>")
def read_straw_lot(lot_id):
    auth.require_role(config.ROLE_LAB_TECH, config.ROLE_PROGRAM_DIRECTOR,
                      config.ROLE_EXPORT_COORD, config.ROLE_DISTRIBUTOR,
                      config.ROLE_BREEDING_ADVISOR)
    rec = resolve.need("straw_lots", lot_id)
    return envelope.ok(serializers.straw_lot(rec))


@bp.get("/straw-lots")
def list_straw_lots():
    auth.require_role(config.ROLE_LAB_TECH, config.ROLE_PROGRAM_DIRECTOR,
                      config.ROLE_EXPORT_COORD, config.ROLE_DISTRIBUTOR,
                      config.ROLE_BREEDING_ADVISOR)
    limit, offset = validate.pagination()
    sire_id = validate.qstr("sire_id")
    ejaculate_id = validate.qstr("ejaculate_id")
    product_line = validate.qenum("product_line", config.PRODUCT_LINES)
    distribution_status = validate.qenum("distribution_status", config.LOT_STATUSES)
    items = []
    for rec in store.rows("straw_lots"):
        if sire_id is not None and rec["sire_id"] != sire_id:
            continue
        if ejaculate_id is not None and rec["ejaculate_id"] != ejaculate_id:
            continue
        if product_line is not None and rec["product_line"] != product_line:
            continue
        if distribution_status is not None and rec["distribution_status"] != distribution_status:
            continue
        items.append(rec)
    return envelope.listing(items, limit, offset, serializers.straw_lot)


@bp.post("/straw-lots/<lot_id>/release")
def release_straw_lot(lot_id):
    values = validate.parse([F("release_note", "string", default=None)])
    auth.require_role(config.ROLE_LAB_TECH)
    user = auth.require_user_id()
    rec = resolve.need("straw_lots", lot_id)
    if rec["distribution_status"] != "QUARANTINE":
        fail("ERR_LOT_STATE", "Release requires distribution_status QUARANTINE.")
    ejaculate = store.get("ejaculates", rec["ejaculate_id"])
    if ejaculate is not None and ejaculate["evaluated_by_user_id"] == user:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The releaser may not be the technician who judged the parent ejaculate.")
    rec["distribution_status"] = "RELEASED"
    rec["released_by_user_id"] = user
    rec["release_note"] = values["release_note"]
    store.touch(rec)
    return envelope.ok(serializers.straw_lot(rec))


@bp.post("/straw-lots/<lot_id>/reject")
def reject_straw_lot(lot_id):
    values = validate.parse([F("rejected_reason", "string", required=True)])
    auth.require_role(config.ROLE_LAB_TECH)
    rec = resolve.need("straw_lots", lot_id)
    if rec["distribution_status"] != "QUARANTINE":
        fail("ERR_LOT_STATE", "Condemnation requires distribution_status QUARANTINE.")
    rec["doses_destroyed"] = int(rec["doses_destroyed"]) + int(rec["doses_available"])
    rec["doses_available"] = 0
    rec["distribution_status"] = "REJECTED"
    rec["rejected_reason"] = values["rejected_reason"]
    store.touch(rec)
    cascades.revoke_certificates_for_lot(rec["id"], config.REVOKE_LOT_REJECTED)
    return envelope.ok(serializers.straw_lot(rec))


@bp.post("/straw-lots/<lot_id>/consignment-transfers")
def request_consignment(lot_id):
    values = validate.parse([
        F("distributor_id", "id", required=True),
        F("tank_id", "id", required=True),
        F("doses", "integer", required=True, min=1),
        F("unit_price_cents", "integer", required=True, min=1),
        F("export_certificate_id", "id", default=None),
        F("expected_straw_lot_version", "integer", required=True),
    ])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_DISTRIBUTOR)
    auth.require_distributor_scope(values["distributor_id"])
    lot = resolve.need("straw_lots", lot_id)
    distributor = resolve.need("distributors", values["distributor_id"])
    tank = resolve.need("tanks", values["tank_id"])
    certificate = resolve.optional("export_certificates", values["export_certificate_id"])
    # Band 5 -- version pinning, before any state precondition.
    if int(values["expected_straw_lot_version"]) != int(lot["version"]):
        fail("ERR_STALE_STRAW_LOT_VERSION",
             "expected_straw_lot_version does not match the lot's current version.")
    if lot["distribution_status"] != "RELEASED":
        fail("ERR_LOT_NOT_RELEASED", "Only a RELEASED lot may be consigned.")
    if tank["distributor_id"] != distributor["id"]:
        fail("ERR_TANK_NOT_OWNED_BY_DISTRIBUTOR",
             "The destination tank belongs to another distributor.")
    if int(values["doses"]) > int(lot["doses_available"]):
        fail("ERR_INSUFFICIENT_DOSES", "The lot does not hold that many available doses.")
    cross_border = distributor["country_code"] != config.PLANT_COUNTRY_CODE
    if cross_border or certificate is not None:
        if (certificate is None or certificate["sire_id"] != lot["sire_id"]
                or certificate["straw_lot_id"] != lot["id"]
                or certificate["status"] != "ISSUED"):
            fail("ERR_CERTIFICATE_NOT_APPLICABLE",
                 "An ISSUED certificate covering this bull and lot is required.")
    destination = (certificate["destination_country_code"] if certificate is not None
                   else distributor["country_code"])
    if destination != config.PLANT_COUNTRY_CODE:
        facility = origin_facility(lot)
        approved = list(facility["approved_export_countries"]) if facility is not None else []
        if destination not in approved:
            fail("ERR_DESTINATION_NOT_APPROVED",
                 "The lot's origin facility is not approved to export to %s." % destination)
    rec = store.new_record("consignment_transfers", {
        "straw_lot_id": lot["id"],
        "distributor_id": distributor["id"],
        "tank_id": tank["id"],
        "export_certificate_id": certificate["id"] if certificate is not None else None,
        "doses": values["doses"],
        "unit_price_cents": values["unit_price_cents"],
        "status": "REQUESTED",
        "approved_by_user_id": None,
        "rejection_reason": None,
        "tank_service_count_at_dispatch": None,
        "doses_used": 0,
        "doses_returned": 0,
        "gross_cents": None,
        "service_fee_cents": None,
        "rebate_cents": None,
        "settlement_total_cents": None,
        "received_at": None,
    })
    return envelope.created(serializers.consignment_transfer(rec))
