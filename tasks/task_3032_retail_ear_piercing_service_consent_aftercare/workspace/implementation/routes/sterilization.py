"""Sterilization cycle and cartridge lot routes (PRD 2.7)."""

from flask import Blueprint, request

import db
import errors as E
import response as R
from middleware import authenticated
from services import common
from services import sterilization as steril_svc
from calculations import cartridge_lot_availability as calc_cartridge_lot_availability

bp = Blueprint("sterilization", __name__)


# =============================================================================
# Sterilization cycles
# =============================================================================
@bp.route("/sterilization-cycles", methods=["POST"])
@authenticated("SterilizationTechnician")
def create_cycle():
    data = common.body()
    store = common.get_store(common.require_str(data, "store_location_id"))
    autoclave_unit_id = common.require_str(data, "autoclave_unit_id")
    start_at = common.require_instant(data, "cycle_start_at")
    end_at = common.require_instant(data, "cycle_end_at")

    steril_svc.validate_autoclave_window(autoclave_unit_id, start_at, end_at)

    cycle = db.SterilizationCycle()
    cycle.store_location_id = store.id
    cycle.autoclave_unit_id = autoclave_unit_id
    cycle.protocol_code = common.require_str(data, "protocol_code")
    cycle.cycle_start_at = db.fmt_instant(start_at)
    cycle.cycle_end_at = db.fmt_instant(end_at)
    cycle.temperature_celsius = common.optional_number(data, "temperature_celsius")
    cycle.quarantine_scope_units = 0
    cycle.status = "IN_PROGRESS"
    db.DB.cycles[cycle.id] = cycle
    return R.object_response(cycle, 201)


@bp.route("/sterilization-cycles", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_cycles():
    limit, offset = common.pagination_params()
    rows = list(db.DB.cycles.values())
    requested = request.args.get("store_location_id")
    if requested:
        rows = [c for c in rows if c.store_location_id == requested]
    rows = common.sorted_rows(rows)
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/sterilization-cycles/<cycle_id>", methods=["GET"])
@authenticated("AnyAuthenticated")
def get_cycle(cycle_id):
    return R.object_response(common.get_cycle(cycle_id))


@bp.route("/sterilization-cycles/<cycle_id>/complete", methods=["POST"])
@authenticated("SterilizationTechnician")
def complete_cycle(cycle_id):
    cycle = common.get_cycle(cycle_id)
    data = common.body()
    temperature = common.optional_number(data, "temperature_celsius")
    if temperature is None:
        temperature = cycle.temperature_celsius
    if temperature is None:
        E.fail(E.ERR_INVALID_REQUEST, "temperature_celsius is required")
    passed = data.get("biological_indicator_passed",
                      cycle.biological_indicator_passed)
    if not isinstance(passed, bool):
        E.fail(E.ERR_INVALID_REQUEST, "biological_indicator_passed must be a boolean")
    steril_svc.complete_cycle(cycle, float(temperature), passed)
    return R.object_response(cycle)


@bp.route("/sterilization-cycles/<cycle_id>/quarantine", methods=["POST"])
@authenticated("ComplianceOfficer")
def quarantine_cycle(cycle_id):
    cycle = common.get_cycle(cycle_id)
    steril_svc.quarantine_cycle(cycle)
    return R.object_response(cycle)


@bp.route("/sterilization-cycles/<cycle_id>/release", methods=["POST"])
@authenticated("ComplianceOfficer")
def release_cycle(cycle_id):
    cycle = common.get_cycle(cycle_id)
    steril_svc.release_cycle(cycle)
    return R.object_response(cycle)


@bp.route("/sterilization-cycles/<cycle_id>/recall", methods=["POST"])
@authenticated("ComplianceOfficer")
def recall_cycle(cycle_id):
    cycle = common.get_cycle(cycle_id)
    steril_svc.recall_cycle(cycle)
    return R.object_response(cycle)


# =============================================================================
# Cartridge lots
# =============================================================================
@bp.route("/cartridge-lots", methods=["POST"])
@authenticated("StoreManager")
def create_lot():
    data = common.body()
    store = common.get_store(common.require_str(data, "store_location_id"))
    common.check_expected_version(data, "expected_store_version", store)
    cycle = common.get_cycle(common.require_str(data, "sterilization_cycle_id"))

    lot = db.CartridgeLot()
    lot.store_location_id = store.id
    lot.sterilization_cycle_id = cycle.id
    lot.lot_number = common.require_str(data, "lot_number")
    lot.site_type = common.require_enum(data, "site_type", db.ALLOWED_SITES)
    lot.units_received = common.require_int(data, "units_received")
    lot.expiration_date = db.fmt_instant(common.require_instant(data, "expiration_date"))
    # units_available is derived by cartridge_lot_availability:
    # units_received - units_consumed - units_quarantined, floored at 0.
    lot.units_consumed = 0
    lot.units_quarantined = 0
    lot.units_available = calc_cartridge_lot_availability(lot)
    lot.status = "AVAILABLE"
    db.DB.lots[lot.id] = lot

    if cycle.status in ("FAILED", "QUARANTINED"):
        # A lot bound to a failed or quarantined cycle is held back in full.
        lot.status = "QUARANTINED"
        lot.units_quarantined = lot.units_available
        lot.units_available = 0
    lot.touch()

    # Registering a cartridge lot increments the target store's version once,
    # covering the posture recomputation that follows it (PRD 2.5).
    with db.atomic_mutation(store):
        common.recompute_store_posture(store)
    return R.object_response(lot, 201)


@bp.route("/cartridge-lots", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_lots():
    limit, offset = common.pagination_params()
    rows = list(db.DB.lots.values())
    for arg, field in (("store_location_id", "store_location_id"),
                       ("sterilization_cycle_id", "sterilization_cycle_id"),
                       ("site_type", "site_type")):
        requested = request.args.get(arg)
        if requested:
            rows = [row for row in rows if getattr(row, field) == requested]
    rows = common.sorted_rows(rows)
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/cartridge-lots/<lot_id>", methods=["GET"])
@authenticated("AnyAuthenticated")
def get_lot(lot_id):
    return R.object_response(common.get_lot(lot_id))


@bp.route("/cartridge-lots/<lot_id>/discard", methods=["POST"])
@authenticated("ComplianceOfficer")
def discard_lot(lot_id):
    lot = common.get_lot(lot_id)
    if lot.status not in ("AVAILABLE", "QUARANTINED"):
        E.fail(E.ERR_INVALID_STATE, "Lot is not AVAILABLE or QUARANTINED")

    expiration = db.parse_instant(lot.expiration_date)
    expired = expiration is not None and expiration <= db.DB.clock

    if lot.status == "AVAILABLE":
        if not expired:
            E.fail(E.ERR_INVALID_STATE,
                   "An AVAILABLE lot may only be discarded once expired")
    else:
        cycle = db.DB.cycles.get(lot.sterilization_cycle_id)
        retests_exhausted = (cycle is not None and cycle.status == "FAILED"
                             and _practical_retests_exhausted(lot))
        if not (expired or retests_exhausted):
            E.fail(E.ERR_INVALID_STATE,
                   "A QUARANTINED lot may only be discarded once expired or "
                   "when its bound cycle is FAILED with all retests exhausted")

    lot.status = "DISCARDED"
    lot.units_available = 0
    lot.touch()
    return R.object_response(lot)


def _practical_retests_exhausted(lot):
    piercers = {s.piercer_id for s in db.DB.sessions.values()
                if s.cartridge_lot_id == lot.id}
    for piercer_id in piercers:
        rows = [c for c in db.DB.certifications.values()
                if c.piercer_id == piercer_id and c.attempted_practical_count >= 3]
        if rows:
            return True
    return False