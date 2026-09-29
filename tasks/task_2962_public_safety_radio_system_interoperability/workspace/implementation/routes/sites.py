"""Radio site registry and coverage engineering."""
from decimal import Decimal

from flask import Blueprint

import common
import compute
import db
import enums
import response
import serialize
import validate
from errors import ApiError
from validate import RF_ENGINEER, SYSTEM_ADMIN

bp = Blueprint("sites", __name__, url_prefix=common.PREFIX)


@bp.post("/sites")
def create_site():
    validate.authenticate([SYSTEM_ADMIN])
    body = validate.get_body()
    site_code = validate.req_str(body, "site_code", 3, 12, r"^[A-Z0-9\-]+$")
    name = validate.req_str(body, "name", 1, 120)
    capacity = validate.req_int(body, "channel_capacity", 2, 30)
    backup = validate.req_enum(body, "backup_power_type", enums.BACKUP_POWER_TYPES)
    battery = validate.opt_int(body, "battery_runtime_minutes", 0, 2880, 240)
    fuel = validate.opt_decimal(body, "generator_fuel_hours", 0, 96, 2, Decimal("0"))
    standard = validate.opt_enum(body, "migration_standard", enums.MIGRATION_STANDARDS, "P25_PHASE1")
    for existing in db.store.sites.values():
        if existing["site_code"] == site_code:
            raise ApiError("ERR_DUPLICATE_TALKGROUP_ID", "site_code is already registered.")
    row = db.base_row({
        "site_code": site_code,
        "name": name,
        "channel_capacity": capacity,
        "backup_power_type": backup,
        "battery_runtime_minutes": battery,
        "generator_fuel_hours": fuel,
        "covered_test_points": 0,
        "total_test_points": 0,
        "coverage_reliability_pct": Decimal("0.0"),
        "coverage_derate_tier": "NONE",
        "coverage_class": "UNRATED",
        "status": "IN_SERVICE",
        "capacity_mode": "NORMAL",
        "busy_talkpaths": 0,
        "peak_talkpaths": 0,
        "granted_request_count": 0,
        "busied_request_count": 0,
        "grade_of_service_pct": Decimal("100.0"),
        "migration_standard": standard,
    })
    db.store.sites[row["id"]] = row
    return response.ok(serialize.site(row), 201)


@bp.get("/sites")
def list_sites():
    validate.authenticate(common.ANY_ROLE)
    filters = (
        ("status", validate.filter_enum("status", enums.SITE_STATUSES)),
        ("coverage_class", validate.filter_enum("coverage_class", enums.COVERAGE_CLASSES)),
        ("capacity_mode", validate.filter_enum("capacity_mode", enums.CAPACITY_MODES)),
    )
    return common.list_endpoint("sites", serialize.site, filters)


@bp.get("/sites/<site_id>")
def read_site(site_id):
    validate.authenticate(common.ANY_ROLE)
    site = validate.lookup("sites", site_id)
    return response.ok(serialize.site(site))


@bp.patch("/sites/<site_id>/coverage")
def submit_coverage(site_id):
    validate.authenticate([RF_ENGINEER])
    site = validate.lookup("sites", site_id)
    body = validate.get_body()
    covered = validate.req_int(body, "covered_test_points", 0)
    total = validate.req_int(body, "total_test_points", 0)
    if covered > total:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "covered_test_points may not exceed total_test_points.",
        )
    common.check_occ(site, "expected_site_version", body)
    site["covered_test_points"] = covered
    site["total_test_points"] = total
    compute.recompute_coverage(site)
    db.touch(site)
    return response.ok(serialize.site(site))
