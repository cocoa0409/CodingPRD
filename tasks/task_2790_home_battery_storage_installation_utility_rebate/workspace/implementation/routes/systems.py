"""Battery systems: design, lock, install, commission, warranty and expansion."""

from flask import Blueprint, request

import cascades
import shape
import store
from calc import bank_capacity, commissioning_verdict
from common import (
    INVERTER_FAMILY,
    INVERTER_MODELS,
    MODEL_CATALOG,
    MODEL_CODES,
    TEST_TYPES,
    WARRANTY_REGISTRATION_GRACE_DAYS,
    dec,
    plus_days,
    version_ge,
)
from envelope import collection, created, ok
from errors import ApiError, invalid
from rules import (
    clock_at_or_before,
    clock_before,
    require_capacity,
    require_certified,
    require_load_calc_approved,
)
from security import guard, path_ref, ref

bp = Blueprint("systems", __name__)

READ_ROLES = (
    "CertifiedInstaller",
    "Homeowner",
    "AuthorityHavingJurisdiction",
    "UtilityInterconnectionReviewer",
    "RebateAdministrator",
    "ManufacturerWarrantyAgent",
)


def permit_of(system):
    for permit in store.rows("permits"):
        if permit["battery_system_id"] == system["id"]:
            return permit
    raise ApiError("ERR_PERMIT_NOT_FOUND", "The system has no permit.")


def build_state(system, allowed):
    if system["build_status"] not in allowed:
        raise ApiError(
            "ERR_SYSTEM_BUILD_STATE_INVALID",
            "Build status %s does not declare this transition." % system["build_status"],
        )


def grid_state(system, allowed):
    if system["grid_status"] not in allowed:
        raise ApiError(
            "ERR_SYSTEM_GRID_STATE_INVALID",
            "Grid status %s does not declare this transition." % system["grid_status"],
        )


# --------------------------------------------------------------------------- #
# Create / read / list
# --------------------------------------------------------------------------- #

@bp.route("/battery-systems", methods=["POST"])
@guard("CertifiedInstaller")
def create_system(actor):
    payload = shape.body()
    site_id = payload.fk("site_id")
    ref("site", site_id)
    installer_id = payload.fk("installer_id")
    installer = ref("installer", installer_id)
    calculation_id = payload.fk("load_calculation_id")
    calculation = ref("load_calculation", calculation_id)

    model_code = payload.enum("model_code", MODEL_CODES)
    unit_count = payload.integer("unit_count", minimum=1)
    inverter_model = payload.enum("inverter_model", INVERTER_MODELS)
    firmware_version = payload.firmware("firmware_version")
    installed_cost_cents = payload.integer("installed_cost_cents", exclusive_min=True)

    require_certified(installer, model_code)
    require_load_calc_approved(calculation, site_id)
    usable_kwh, continuous_kw = bank_capacity(model_code, unit_count)
    require_capacity(continuous_kw, calculation)

    record = store.insert(
        "battery_systems",
        {
            "site_id": site_id,
            "installer_id": installer_id,
            "load_calculation_id": calculation_id,
            "model_code": model_code,
            "unit_count": unit_count,
            "inverter_model": inverter_model,
            "firmware_version": firmware_version,
            "installed_cost_cents": installed_cost_cents,
            "usable_kwh": usable_kwh,
            "continuous_kw": continuous_kw,
            "build_status": "DESIGN_DRAFT",
            "grid_status": "NOT_APPLIED",
            "warranty_status": "UNREGISTERED",
            "verified_capacity_kwh": None,
            "commissioned_at": None,
            "warranty_deadline_at": None,
            "warranty_registered_at": None,
            "warranty_coverage_years": None,
            "serial_numbers": None,
            "expands_system_id": None,
        },
    )
    return created(store.view(record))


@bp.route("/battery-systems/<system_id>", methods=["GET"])
@guard(*READ_ROLES)
def read_system(actor, system_id):
    record = path_ref(actor, "battery_system", system_id)
    return ok(store.view(record))


@bp.route("/battery-systems", methods=["GET"])
@guard(*READ_ROLES)
def list_systems(actor):
    records = store.where(
        "battery_systems",
        site_id=request.args.get("site_id"),
        installer_id=request.args.get("installer_id"),
        load_calculation_id=request.args.get("load_calculation_id"),
        expands_system_id=request.args.get("expands_system_id"),
        build_status=request.args.get("build_status"),
        grid_status=request.args.get("grid_status"),
    )
    return collection(records)


# --------------------------------------------------------------------------- #
# Build lifecycle
# --------------------------------------------------------------------------- #

@bp.route("/battery-systems/<system_id>/lock-design", methods=["POST"])
@guard("CertifiedInstaller")
def lock_design(actor, system_id):
    system = path_ref(actor, "battery_system", system_id)
    build_state(system, ("DESIGN_DRAFT",))
    installer = store.get("installers", system["installer_id"])
    calculation = store.get("load_calculations", system["load_calculation_id"])
    require_certified(installer, system["model_code"])
    require_load_calc_approved(calculation, system["site_id"])
    require_capacity(system["continuous_kw"], calculation)
    system["build_status"] = "DESIGN_LOCKED"
    store.touch(system)
    return ok(store.view(system))


@bp.route("/battery-systems/<system_id>/mark-installed", methods=["POST"])
@guard("CertifiedInstaller")
def mark_installed(actor, system_id):
    system = path_ref(actor, "battery_system", system_id)
    build_state(system, ("DESIGN_LOCKED",))
    permit = permit_of(system)
    if permit["status"] not in ("ISSUED", "INSPECTION_FAILED", "INSPECTION_PASSED"):
        raise ApiError(
            "ERR_PERMIT_STATE_INVALID",
            "Permit status %s is not enough to mark the bank installed." % permit["status"],
        )
    if permit["expires_on"] is None or not clock_before(permit["expires_on"]):
        raise ApiError("ERR_PERMIT_EXPIRED", "The permit validity window has lapsed.")
    grid_state(system, ("APPROVED_TO_INSTALL",))
    system["build_status"] = "INSTALLED"
    store.touch(system)
    return ok(store.view(system))


@bp.route("/battery-systems/<system_id>/commission", methods=["POST"])
@guard("CertifiedInstaller")
def commission(actor, system_id):
    system = path_ref(actor, "battery_system", system_id)
    build_state(system, ("INSTALLED",))

    recorded = {}
    for test in store.rows("tests"):
        if test["battery_system_id"] != system["id"]:
            continue
        if test["status"] != "RECORDED":
            continue
        recorded[test["test_type"]] = test
    if len(recorded) < len(TEST_TYPES) or any(kind not in recorded for kind in TEST_TYPES):
        raise ApiError(
            "ERR_COMMISSIONING_TESTS_INCOMPLETE",
            "All four commissioning tests must be recorded before commissioning.",
        )
    if recorded["BACKUP_TRANSITION"]["result"] != "PASS":
        raise ApiError(
            "ERR_BACKUP_TRANSITION_NOT_VERIFIED",
            "The backup transition test did not pass.",
        )
    for kind in TEST_TYPES:
        if recorded[kind]["result"] != "PASS":
            raise ApiError(
                "ERR_COMMISSIONING_TEST_FAILED",
                "Commissioning test %s did not pass." % kind,
            )

    permit = permit_of(system)
    if permit["expires_on"] is None or not clock_before(permit["expires_on"]):
        raise ApiError("ERR_PERMIT_EXPIRED", "The permit validity window has lapsed.")

    commissioned_at = store.now()
    system["build_status"] = "COMMISSIONED"
    system["commissioned_at"] = commissioned_at
    system["warranty_deadline_at"] = plus_days(
        commissioned_at, WARRANTY_REGISTRATION_GRACE_DAYS
    )
    system["verified_capacity_kwh"] = recorded["CAPACITY_DISCHARGE"]["delivered_kwh"]
    store.touch(system)

    installer = store.get("installers", system["installer_id"])
    if installer is not None:
        installer["commissioned_system_count"] += 1
        store.touch(installer)

    cascades.cascade_b(system)
    return ok(store.view(system))


@bp.route("/battery-systems/<system_id>/register-warranty", methods=["POST"])
@guard("CertifiedInstaller")
def register_warranty(actor, system_id):
    system = path_ref(actor, "battery_system", system_id)
    payload = shape.body()
    coverage_years = payload.integer("coverage_years", minimum=1)
    serial_numbers = payload.str_list("serial_numbers")
    if len(serial_numbers) != system["unit_count"]:
        raise invalid(
            "'serial_numbers' must contain exactly %d entries." % system["unit_count"]
        )

    build_state(system, ("COMMISSIONED",))

    registered_at = store.now()
    system["warranty_registered_at"] = registered_at
    system["warranty_coverage_years"] = coverage_years
    system["serial_numbers"] = serial_numbers
    deadline = system["warranty_deadline_at"]
    # The deadline boundary is inclusive: landing exactly on it is on time.
    on_time = deadline is None or clock_at_or_before(deadline)
    if on_time:
        system["warranty_status"] = "ACTIVE"
        store.touch(system)
    else:
        system["warranty_status"] = "VOID"
        store.touch(system)
        installer = store.get("installers", system["installer_id"])
        if installer is not None:
            installer["late_warranty_registration_count"] += 1
            store.touch(installer)
    return ok(store.view(system))


@bp.route("/battery-systems/<system_id>/expansions", methods=["POST"])
@guard("CertifiedInstaller")
def create_expansion(actor, system_id):
    base = path_ref(actor, "battery_system", system_id)
    payload = shape.body()
    additional_unit_count = payload.integer("additional_unit_count", minimum=1)
    inverter_model = payload.enum("inverter_model", INVERTER_MODELS)
    firmware_version = payload.firmware("firmware_version")
    installed_cost_cents = payload.integer("installed_cost_cents", exclusive_min=True)
    expected_version = payload.integer("expected_battery_system_version", minimum=0)

    build_state(base, ("COMMISSIONED",))
    grid_state(base, ("PTO_GRANTED",))

    if expected_version != base["version"]:
        raise ApiError(
            "ERR_STALE_SYSTEM_VERSION",
            "The battery system has version %d." % base["version"],
        )

    installer = store.get("installers", base["installer_id"])
    calculation = store.get("load_calculations", base["load_calculation_id"])
    require_certified(installer, base["model_code"])
    require_load_calc_approved(calculation, base["site_id"])

    spec = MODEL_CATALOG[base["model_code"]]
    if INVERTER_FAMILY[inverter_model] != INVERTER_FAMILY[base["inverter_model"]]:
        raise ApiError(
            "ERR_INVERTER_INCOMPATIBLE",
            "The inverter belongs to a different gateway family than the base bank.",
        )
    if not version_ge(firmware_version, base["firmware_version"]) or not version_ge(
        firmware_version, spec["min_firmware"]
    ):
        raise ApiError("ERR_FIRMWARE_TOO_OLD", "The supplied firmware is too old.")
    new_unit_count = base["unit_count"] + additional_unit_count
    if new_unit_count > spec["max_units"]:
        raise ApiError(
            "ERR_UNIT_LIMIT_EXCEEDED",
            "Model %s permits at most %d units." % (base["model_code"], spec["max_units"]),
        )
    usable_kwh, continuous_kw = bank_capacity(base["model_code"], new_unit_count)
    require_capacity(continuous_kw, calculation)

    record = store.insert(
        "battery_systems",
        {
            "site_id": base["site_id"],
            "installer_id": base["installer_id"],
            "load_calculation_id": base["load_calculation_id"],
            "model_code": base["model_code"],
            "unit_count": new_unit_count,
            "inverter_model": inverter_model,
            "firmware_version": firmware_version,
            "installed_cost_cents": base["installed_cost_cents"] + installed_cost_cents,
            "usable_kwh": usable_kwh,
            "continuous_kw": continuous_kw,
            "build_status": "DESIGN_DRAFT",
            "grid_status": "NOT_APPLIED",
            "warranty_status": "UNREGISTERED",
            "verified_capacity_kwh": None,
            "commissioned_at": None,
            "warranty_deadline_at": None,
            "warranty_registered_at": None,
            "warranty_coverage_years": None,
            "serial_numbers": None,
            "expands_system_id": base["id"],
        },
    )
    cascades.cascade_c(base)
    return created(store.view(record))
