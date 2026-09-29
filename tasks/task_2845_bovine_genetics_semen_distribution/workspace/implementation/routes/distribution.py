"""The distributor network: partners, tanks and consignments (PRD 3.8)."""

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
from validate import F, COUNTRY_CODE_RE

bp = Blueprint("distribution", __name__)


# ------------------------------------------------------------ distributors ----
@bp.post("/distributors")
def create_distributor():
    values = validate.parse([
        F("name", "string", required=True, min_len=1),
        F("country_code", "string", required=True, pattern=COUNTRY_CODE_RE),
        F("credit_limit_cents", "integer", required=True, min=0),
        F("consignment_enabled", "boolean", default=None),
    ])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR)
    enabled = values["consignment_enabled"]
    rec = store.new_record("distributors", {
        "name": values["name"],
        "country_code": values["country_code"],
        "credit_limit_cents": values["credit_limit_cents"],
        "consignment_enabled": True if enabled is None else enabled,
    })
    return envelope.created(serializers.distributor(rec))


@bp.get("/distributors/<distributor_id>")
def read_distributor(distributor_id):
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_DISTRIBUTOR,
                      config.ROLE_BREEDING_ADVISOR)
    rec = resolve.need("distributors", distributor_id)
    return envelope.ok(serializers.distributor(rec))


# -------------------------------------------------------------------- tanks ----
@bp.post("/tanks")
def create_tank():
    values = validate.parse([
        F("distributor_id", "id", required=True),
        F("serial", "string", required=True, min_len=1, max_len=32),
        F("capacity_straws", "integer", required=True, min=1),
        F("service_interval_days", "integer", default=None, min=1),
        F("assigned_technician_name", "string", default=None),
        F("technician_cert_expiry_at", "datetime", default=None),
        F("initial_fill_pct", "number", default=None, min=0, max=100),
    ])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_DISTRIBUTOR)
    auth.require_distributor_scope(values["distributor_id"])
    distributor = resolve.need("distributors", values["distributor_id"])
    for existing in store.DB["tanks"].values():
        if existing["serial"] == values["serial"]:
            fail("ERR_DUPLICATE_CODE", "Tank serial '%s' is already registered." % values["serial"])
    interval = values["service_interval_days"]
    fill = values["initial_fill_pct"]
    rec = store.new_record("tanks", {
        "serial": values["serial"],
        "distributor_id": distributor["id"],
        "capacity_straws": values["capacity_straws"],
        "service_interval_days": (config.DEFAULT_SERVICE_INTERVAL_DAYS
                                  if interval is None else interval),
        "assigned_technician_name": values["assigned_technician_name"],
        "technician_cert_expiry_at": store.iso(values["technician_cert_expiry_at"]),
        "last_service_at": store.clock_iso(),
        "last_service_fill_pct": (float(config.DEFAULT_INITIAL_FILL_PCT)
                                  if fill is None else fill),
        "service_count": 0,
    })
    return envelope.created(serializers.tank(rec))


@bp.get("/tanks/<tank_id>")
def read_tank(tank_id):
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_DISTRIBUTOR)
    rec = resolve.need("tanks", tank_id)
    auth.require_distributor_scope(rec["distributor_id"])
    return envelope.ok(serializers.tank(rec))


@bp.get("/tanks")
def list_tanks():
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_DISTRIBUTOR)
    limit, offset = validate.pagination()
    distributor_id = validate.qstr("distributor_id")
    tank_status = validate.qenum("tank_status", config.TANK_STATUSES)
    items = []
    for rec in store.rows("tanks"):
        if distributor_id is not None and rec["distributor_id"] != distributor_id:
            continue
        if tank_status is not None:
            _level, _due, status = calc.tank_derived(rec)
            if status != tank_status:
                continue
        items.append(rec)
    return envelope.listing(items, limit, offset, serializers.tank)


@bp.post("/tanks/<tank_id>/ln2-service")
def service_tank(tank_id):
    values = validate.parse([F("fill_pct", "number", required=True, min=0, max=100)])
    auth.require_role(config.ROLE_DISTRIBUTOR, config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("tanks", tank_id)
    auth.require_distributor_scope(rec["distributor_id"])
    level, _due, _status = calc.tank_derived(rec)
    if not calc.D(values["fill_pct"]) > level:
        fail("ERR_VALIDATION",
             "fill_pct must be strictly greater than the tank's current ln2_level_pct.")
    rec["last_service_at"] = store.clock_iso()
    rec["last_service_fill_pct"] = values["fill_pct"]
    rec["service_count"] = int(rec["service_count"]) + 1
    store.touch(rec)
    return envelope.ok(serializers.tank(rec))


# ---------------------------------------------------- consignment transfers ----
def _cert_covers(certificate, lot):
    return (certificate is not None
            and certificate["status"] == "ISSUED"
            and certificate["sire_id"] == lot["sire_id"]
            and certificate["straw_lot_id"] == lot["id"])


@bp.get("/consignment-transfers/<transfer_id>")
def read_transfer(transfer_id):
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_DISTRIBUTOR,
                      config.ROLE_EXPORT_COORD)
    rec = resolve.need("consignment_transfers", transfer_id)
    auth.require_distributor_scope(rec["distributor_id"])
    return envelope.ok(serializers.consignment_transfer(rec))


@bp.get("/consignment-transfers")
def list_transfers():
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_DISTRIBUTOR,
                      config.ROLE_EXPORT_COORD)
    limit, offset = validate.pagination()
    filters = {
        "straw_lot_id": validate.qstr("straw_lot_id"),
        "distributor_id": validate.qstr("distributor_id"),
        "tank_id": validate.qstr("tank_id"),
        "export_certificate_id": validate.qstr("export_certificate_id"),
        "status": validate.qenum("status", config.TRANSFER_STATUSES),
    }
    items = []
    for rec in store.rows("consignment_transfers"):
        if any(want is not None and rec[key] != want for key, want in filters.items()):
            continue
        items.append(rec)
    return envelope.listing(items, limit, offset, serializers.consignment_transfer)


@bp.post("/consignment-transfers/<transfer_id>/approve")
def approve_transfer(transfer_id):
    values = validate.parse([F("approval_note", "string", default=None)])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("consignment_transfers", transfer_id)
    if rec["status"] != "REQUESTED":
        fail("ERR_TRANSFER_STATE", "Approval requires status REQUESTED.")
    lot = store.get("straw_lots", rec["straw_lot_id"])
    if lot["distribution_status"] != "RELEASED":
        fail("ERR_LOT_NOT_RELEASED", "The lot is no longer RELEASED.")
    if not calc.health_current(lot["sire_id"]):
        fail("ERR_HEALTH_TESTS_NOT_CURRENT",
             "The bull behind this lot lacks current health across all four base assays.")
    distributor = store.get("distributors", rec["distributor_id"])
    if not distributor["consignment_enabled"]:
        fail("ERR_CONSIGNMENT_DISABLED", "Consignment is disabled for this distributor.")
    tank = store.get("tanks", rec["tank_id"])
    on_hand = calc.tank_straws_on_hand(tank["id"])
    if on_hand + int(rec["doses"]) > int(tank["capacity_straws"]):
        fail("ERR_TANK_CAPACITY_EXCEEDED", "The destination tank has insufficient room.")
    if int(lot["doses_available"]) < int(rec["doses"]):
        fail("ERR_INSUFFICIENT_DOSES", "The lot no longer holds that many available doses.")
    if rec["export_certificate_id"] is not None:
        certificate = store.get("export_certificates", rec["export_certificate_id"])
        if not _cert_covers(certificate, lot):
            fail("ERR_CERTIFICATE_NOT_APPLICABLE",
                 "The cited certificate no longer covers this shipment.")
    exposure = calc.distributor_exposure(distributor["id"])
    projected = (exposure["consignment_value_cents"] + exposure["outstanding_balance_cents"]
                 + int(rec["doses"]) * int(lot["unit_book_value_cents"]))
    if projected > int(distributor["credit_limit_cents"]):
        fail("ERR_CREDIT_LIMIT_EXCEEDED",
             "The projected exposure exceeds the distributor's credit limit.")
    lot["doses_available"] = int(lot["doses_available"]) - int(rec["doses"])
    lot["doses_reserved"] = int(lot["doses_reserved"]) + int(rec["doses"])
    store.touch(lot)
    rec["status"] = "APPROVED"
    rec["approved_by_user_id"] = auth.user_id()
    if values["approval_note"] is not None:
        rec["approval_note"] = values["approval_note"]
    store.touch(rec)
    return envelope.ok(serializers.consignment_transfer(rec))


@bp.post("/consignment-transfers/<transfer_id>/reject")
def reject_transfer(transfer_id):
    values = validate.parse([F("rejection_reason", "string", required=True, min_len=1)])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("consignment_transfers", transfer_id)
    if rec["status"] != "REQUESTED":
        fail("ERR_TRANSFER_STATE", "Refusal requires status REQUESTED.")
    rec["status"] = "REJECTED"
    rec["rejection_reason"] = values["rejection_reason"]
    store.touch(rec)
    return envelope.ok(serializers.consignment_transfer(rec))


@bp.post("/consignment-transfers/<transfer_id>/dispatch")
def dispatch_transfer(transfer_id):
    values = validate.parse([F("dispatch_note", "string", default=None)])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("consignment_transfers", transfer_id)
    if rec["status"] != "APPROVED":
        fail("ERR_TRANSFER_STATE", "Dispatch requires status APPROVED.")
    tank = store.get("tanks", rec["tank_id"])
    _level, _due, tank_status = calc.tank_derived(tank)
    if tank_status != "IN_SERVICE":
        fail("ERR_TANK_OUT_OF_SERVICE", "The destination tank is %s." % tank_status)
    distributor = store.get("distributors", rec["distributor_id"])
    if distributor["country_code"] != config.PLANT_COUNTRY_CODE:
        certificate = store.get("export_certificates", rec["export_certificate_id"]) \
            if rec["export_certificate_id"] is not None else None
        if (certificate is None or certificate["status"] != "ISSUED"
                or certificate["straw_lot_id"] != rec["straw_lot_id"]
                or certificate["destination_country_code"] != distributor["country_code"]):
            fail("ERR_CERTIFICATE_NOT_APPLICABLE",
                 "A cross-border dispatch requires an ISSUED certificate for %s."
                 % distributor["country_code"])
    on_hand = calc.tank_straws_on_hand(tank["id"])
    if on_hand + int(rec["doses"]) > int(tank["capacity_straws"]):
        fail("ERR_TANK_CAPACITY_EXCEEDED", "The destination tank would be overfilled.")
    rec["tank_service_count_at_dispatch"] = int(tank["service_count"])
    rec["status"] = "IN_TRANSIT"
    if values["dispatch_note"] is not None:
        rec["dispatch_note"] = values["dispatch_note"]
    store.touch(rec)
    return envelope.ok(serializers.consignment_transfer(rec))


@bp.post("/consignment-transfers/<transfer_id>/receive")
def receive_transfer(transfer_id):
    values = validate.parse([F("receipt_note", "string", default=None)])
    auth.require_role(config.ROLE_DISTRIBUTOR)
    rec = resolve.need("consignment_transfers", transfer_id)
    auth.require_distributor_scope(rec["distributor_id"])
    if rec["status"] != "IN_TRANSIT":
        fail("ERR_TRANSFER_STATE", "Receipt requires status IN_TRANSIT.")
    tank = store.get("tanks", rec["tank_id"])
    _level, _due, tank_status = calc.tank_derived(tank)
    if tank_status == "OUT_OF_SERVICE":
        # PRD 3.8: an OUT_OF_SERVICE tank "can then receive nothing at all".
        fail("ERR_TANK_OUT_OF_SERVICE", "The destination tank is OUT_OF_SERVICE.")
    lot = store.get("straw_lots", rec["straw_lot_id"])
    lot["doses_reserved"] = int(lot["doses_reserved"]) - int(rec["doses"])
    lot["doses_consigned"] = int(lot["doses_consigned"]) + int(rec["doses"])
    store.touch(lot)
    rec["status"] = "RECEIVED"
    rec["received_at"] = store.clock_iso()
    if values["receipt_note"] is not None:
        rec["receipt_note"] = values["receipt_note"]
    store.touch(rec)
    return envelope.ok(serializers.consignment_transfer(rec))


@bp.post("/consignment-transfers/<transfer_id>/report-usage")
def report_usage(transfer_id):
    values = validate.parse([
        F("doses_used", "integer", required=True, min=0),
        F("doses_returned", "integer", default=None, min=0),
    ])
    auth.require_role(config.ROLE_DISTRIBUTOR)
    rec = resolve.need("consignment_transfers", transfer_id)
    auth.require_distributor_scope(rec["distributor_id"])
    if rec["status"] != "RECEIVED":
        fail("ERR_TRANSFER_STATE", "Reconciliation requires status RECEIVED.")
    used = int(values["doses_used"])
    returned = 0 if values["doses_returned"] is None else int(values["doses_returned"])
    if used + returned != int(rec["doses"]):
        fail("ERR_INSUFFICIENT_DOSES",
             "doses_used plus doses_returned must equal the consignment's doses.")
    lot = store.get("straw_lots", rec["straw_lot_id"])
    lot["doses_consigned"] = int(lot["doses_consigned"]) - int(rec["doses"])
    lot["doses_used"] = int(lot["doses_used"]) + used
    lot["doses_available"] = int(lot["doses_available"]) + returned
    tank = store.get("tanks", rec["tank_id"])
    figures = calc.settlement(rec, tank, used)
    rec["doses_used"] = used
    rec["doses_returned"] = returned
    rec["status"] = "RECONCILED"
    rec.update(figures)
    store.touch(rec)
    store.touch(lot)
    cascades.maybe_deplete(lot)
    return envelope.ok(serializers.consignment_transfer(rec))


@bp.post("/consignment-transfers/<transfer_id>/return")
def return_transfer(transfer_id):
    values = validate.parse([F("return_reason", "string", required=True, min_len=1)])
    auth.require_role(config.ROLE_DISTRIBUTOR, config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("consignment_transfers", transfer_id)
    auth.require_distributor_scope(rec["distributor_id"])
    if rec["status"] != "RECEIVED":
        fail("ERR_TRANSFER_STATE", "A return requires status RECEIVED.")
    if int(rec["doses_used"]) != 0:
        fail("ERR_TRANSFER_STATE",
             "A consignment with reported insemination must be reconciled instead.")
    lot = store.get("straw_lots", rec["straw_lot_id"])
    lot["doses_consigned"] = int(lot["doses_consigned"]) - int(rec["doses"])
    lot["doses_available"] = int(lot["doses_available"]) + int(rec["doses"])
    store.touch(lot)
    rec["doses_returned"] = int(rec["doses"])
    rec["status"] = "RETURNED"
    rec["return_reason"] = values["return_reason"]
    store.touch(rec)
    return envelope.ok(serializers.consignment_transfer(rec))
