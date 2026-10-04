"""System commissioning, coverage and monitoring reads (PRD 3.3, 3.4)."""

import db
import shapes
from approval import as_array, as_instant, as_str, body
from auth import (
    ROLE_HOMEOWNER,
    ROLE_INSTALLER,
    ROLE_MONITORING,
    ROLE_PLATFORM_ADMIN,
    get_design_project,
    get_system,
    require,
)
from errors import fail
from respond import ok, ok_list, paginate, pagination_meta, parse_iso
from services import common

UNIT_MODELS = ("IQ7", "IQ8", "IQ8HC", "IQ7X_DISCONTINUED")


def lot_allowed_for_installer(installer_id, lot):
    """The commissioning allow-list.

    A lot is assignable to any installer the manufacturer has issued it to; no
    declared endpoint withholds a lot, so the guard is the structural backstop
    described alongside the other referential checks.
    """
    withheld = db.DB.lot_allow_lists.get(("withheld", installer_id))
    if withheld and lot["id"] in withheld:
        return False
    return True


def parse_units_payload(entries):
    """Structural validation of the commissioning payload, entry by entry."""
    parsed = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST_BODY", "units[%d] must be an object" % index)
        serial_number = as_str(entry, "serial_number")
        model_code = as_str(entry, "model_code")
        if model_code not in UNIT_MODELS:
            fail("ERR_INVALID_REQUEST_BODY",
                 "units[%d].model_code must be one of %s" % (index, ", ".join(UNIT_MODELS)))
        installed_at = as_instant(entry, "installed_at")
        production_lot_code = as_str(entry, "production_lot_code")
        parsed.append({
            "serial_number": serial_number,
            "model_code": model_code,
            "installed_at": installed_at,
            "production_lot_code": production_lot_code,
        })
    return parsed


def windows_overlap(first_start, first_end, second_start, second_end):
    """Closed intervals overlap when neither ends before the other starts."""
    return first_start <= second_end and second_start <= first_end


def create_system():
    data = body()
    installer_id = as_str(data, "installer_id")
    design_project_id = as_str(data, "design_project_id")
    site_address = as_str(data, "site_address")
    site_postal_code = as_str(data, "site_postal_code")
    homeowner_name = as_str(data, "homeowner_name")
    homeowner_email = as_str(data, "homeowner_email")
    commissioned_at = as_instant(data, "commissioned_at")
    entries = as_array(data, "units")
    parsed_units = parse_units_payload(entries)

    # Body-referenced foreign keys resolve before any business gate.
    installer = db.DB.installers.get(installer_id)
    if installer is None:
        fail("ERR_RESOURCE_NOT_FOUND", "installer %s does not exist" % installer_id)
    project = db.DB.design_projects.get(design_project_id)
    if project is None:
        fail("ERR_RESOURCE_NOT_FOUND",
             "design project %s does not exist" % design_project_id)

    common.gate_certification(installer)

    if not common.commissioning_enabled_for(installer):
        fail("ERR_COMMISSIONING_NOT_ENABLED")
    if project.get("status") != "APPROVED":
        fail("ERR_DESIGN_NOT_APPROVED")
    if project.get("installer_id") != installer_id:
        fail("ERR_DESIGN_NOT_OWNED")

    seen_serials = set()
    for entry in parsed_units:
        serial_number = entry["serial_number"]
        if serial_number in seen_serials:
            fail("ERR_SERIAL_ALREADY_REGISTERED")
        seen_serials.add(serial_number)
    for existing in db.DB.units.values():
        if existing.get("serial_number") in seen_serials:
            fail("ERR_SERIAL_ALREADY_REGISTERED")

    lots_by_code = {}
    for entry in parsed_units:
        code = entry["production_lot_code"]
        if code in lots_by_code:
            continue
        lot = None
        for candidate in db.DB.production_lots.values():
            if candidate.get("lot_code") == code:
                lot = candidate
                break
        if lot is None:
            fail("ERR_LOT_NOT_FOUND")
        lots_by_code[code] = lot

    for lot in lots_by_code.values():
        if not lot_allowed_for_installer(installer_id, lot):
            fail("ERR_LOT_NOT_ASSIGNED")

    proposed_start = commissioned_at
    proposed_base_end = common.add_months(proposed_start, common.BASE_TERM_MONTHS)
    proposed_end = common.add_months(proposed_base_end, common.FULL_EXTENSION_MONTHS)
    for other in db.DB.systems.values():
        if other.get("site_address") != site_address:
            continue
        if other.get("warranty_status") not in ("ACTIVE", "TRANSFERRED"):
            continue
        other_window = other.get("coverage_window") or {}
        other_start = other_window.get("start_at")
        other_end = other_window.get("end_at")
        if not other_start or not other_end:
            continue
        if windows_overlap(proposed_start, proposed_end,
                           parse_iso(other_start), parse_iso(other_end)):
            fail("ERR_WARRANTY_WINDOW_OVERLAP")

    system = {
        "id": common.new_id(),
        "created_at": common.now_iso(),
        "updated_at": common.now_iso(),
        "version": 1,
        "installer_id": installer_id,
        "design_project_id": design_project_id,
        "site_address": site_address,
        "site_postal_code": site_postal_code,
        "homeowner_name": homeowner_name,
        "homeowner_email": homeowner_email,
        "commissioned_at": common.iso(commissioned_at),
        "warranty_start_at": common.iso(commissioned_at),
        "base_warranty_end_at": None,
        "extended_warranty_end_at": None,
        "warranty_status": "ACTIVE",
        "unit_count": 0,
        "replacement_ratio": 0.0,
        "coverage_window": None,
        "owner_change_count": 0,
    }
    db.DB.systems[system["id"]] = system

    for index, entry in enumerate(parsed_units):
        lot = lots_by_code[entry["production_lot_code"]]
        unit = {
            "id": common.new_id(),
            "created_at": common.now_iso(),
            "updated_at": common.now_iso(),
            "version": 1,
            "system_id": system["id"],
            "serial_number": entry["serial_number"],
            "model_code": entry["model_code"],
            "production_lot_id": lot["id"],
            "installed_at": common.iso(entry["installed_at"]),
            "commissioning_state": "COMMISSIONED",
            "monitored_status": "ONLINE",
            "last_performance_ratio": None,
            "underperformance_streak_hours": 0,
            "failed_at": None,
            "replacement_count": 0,
            "replacement_window_position": common.REPLACEMENT_LIMIT_PER_SYSTEM,
            "rma_eligible": False,
            "campaign_eligible": False,
            "retired_generation": entry["model_code"] == common.DISCONTINUED_MODEL,
            "direct_replacement_unsupported": False,
            "_commission_order": index,
        }
        db.DB.units[unit["id"]] = unit
        common.recompute_unit(unit)

    common.recompute_system(system)
    common.recompute_units_of_system(system["id"])
    for lot in lots_by_code.values():
        from services import lots as lot_service
        lot_service.evaluate_lot(lot)
    common.recompute_installer(installer)
    return ok(shapes.system_registration(system), 201)


def list_systems():
    from flask import request

    installer_id = request.args.get("installer_id")
    design_project_id = request.args.get("design_project_id")
    site_postal_code = request.args.get("site_postal_code")
    homeowner_email = request.args.get("homeowner_email")

    rows = list(db.DB.systems.values())
    if installer_id:
        rows = [s for s in rows if s.get("installer_id") == installer_id]
    if design_project_id:
        rows = [s for s in rows if s.get("design_project_id") == design_project_id]
    if site_postal_code:
        rows = [s for s in rows if s.get("site_postal_code") == site_postal_code]
    if homeowner_email:
        rows = [s for s in rows if s.get("homeowner_email") == homeowner_email]
    rows = db.by_created_at(rows)
    window, meta = paginate(rows, request.args)
    return ok_list([shapes.system_registration(s) for s in window], pagination=meta)


def read_system(system_id):
    system = get_system(system_id)
    common.recompute_system(system)
    return ok(shapes.system_registration(system))


def list_system_units(system_id):
    """The units of a system, in the order of the original commissioning payload.

    This nested read declares no pagination parameters, so it returns the whole
    collection rather than a default-sized window (PRD 2.3).
    """
    get_system(system_id)
    rows = sorted(db.all_units_of_system(system_id),
                  key=lambda u: u.get("_commission_order", 0))
    return ok_list([shapes.unit(u) for u in rows],
                   pagination=pagination_meta(len(rows), len(rows)))


def read_coverage(system_id):
    system = get_system(system_id)
    figures = common.coverage_figures(system)
    common.recompute_system(system)
    return ok(shapes.coverage(system, figures))


def metering_figures(system):
    """evaluate_metering_posture at the current instant (PRD 3.4)."""
    at = common.now()
    age_months = common.system_age_months(system, at)
    age_factor = common.age_factor_for_months(age_months)
    per_unit_rate_cents = common.money(common.dec(common.METERING_BASE_RATE_CENTS) * age_factor)
    active_units = len([u for u in db.all_units_of_system(system["id"])
                        if u.get("commissioning_state") == "COMMISSIONED"])
    failed_units = len([u for u in db.all_units_of_system(system["id"])
                        if u.get("monitored_status") == "FAILED"])

    if system.get("warranty_status") != "ACTIVE":
        metering_fee_cents = 0
    elif age_months <= common.METERING_FREE_MONTHS:
        metering_fee_cents = 0
    else:
        metering_fee_cents = per_unit_rate_cents * active_units

    return {
        "age_months": age_months,
        "active_units": active_units,
        "failed_units": failed_units,
        "per_unit_rate_cents": per_unit_rate_cents,
        "metering_fee_cents": metering_fee_cents,
    }


def read_monitoring_summary(system_id):
    system = get_system(system_id)
    common.recompute_system(system)
    figures = metering_figures(system)
    return ok(shapes.monitoring_summary(
        system, figures["age_months"], figures["active_units"],
        figures["failed_units"], figures["per_unit_rate_cents"],
        figures["metering_fee_cents"]))


def register(app):
    app.add_url_rule("/warranty/system-registrations", "create_system",
                     require(ROLE_INSTALLER)(create_system), methods=["POST"])
    app.add_url_rule("/warranty/system-registrations", "list_systems",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER, ROLE_HOMEOWNER)(list_systems),
                     methods=["GET"])
    app.add_url_rule("/warranty/system-registrations/<system_id>", "read_system",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER, ROLE_HOMEOWNER)(read_system),
                     methods=["GET"])
    app.add_url_rule("/warranty/system-registrations/<system_id>/units", "list_system_units",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER, ROLE_HOMEOWNER,
                             ROLE_MONITORING)(list_system_units), methods=["GET"])
    app.add_url_rule("/warranty/system-registrations/<system_id>/coverage", "read_coverage",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER, ROLE_HOMEOWNER)(read_coverage),
                     methods=["GET"])
    app.add_url_rule("/warranty/system-registrations/<system_id>/monitoring-summary",
                     "read_monitoring_summary",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER,
                             ROLE_MONITORING)(read_monitoring_summary), methods=["GET"])