"""Treatment plans, pesticide records, closeout and station installation (PRD 3.5, 3.6)."""

from flask import Blueprint

import calc
import validate as v
from auth import ROLES, authenticate, not_owner
from clock import clock, plus_days
from common import (apply_filters, get_inspection, get_inspector, get_plan,
                    get_property, require_category, require_graphed,
                    require_license_active, require_license_unexpired)
from envelope import created, listing, ok
from errors import ApiError, invalid_request, invalid_state
from serialize import plan_out, record_out, station_out
from store import (by_created, by_seq, db, new_row, plans_of, records_of,
                   stations_of, touch)

bp = Blueprint("plan", __name__)

ALL = ROLES
STATION_READERS = ("ComplianceOfficer", "BranchManager", "FieldInspector",
                   "Applicator", "PropertyOwner")
RECORD_READERS = ("ComplianceOfficer", "BranchManager", "Applicator", "FieldInspector")


@bp.post("/treatment-plans")
def create_plan():
    authenticate(("BranchManager",))
    payload = v.body()

    property_id = v.get_string(payload, "property_id")
    inspection_id = v.get_string(payload, "inspection_id")
    applicator_id = v.get_string(payload, "applicator_id")
    method = v.get_enum(payload, "method", calc.METHODS)
    product = v.get_enum(payload, "chemical_product_code", calc.PRODUCTS)
    permit = v.get_string(payload, "fumigation_permit_number", required=False,
                          default=None, pattern=v.FUM_PERMIT_RE)
    fum_start = v.get_instant(payload, "fumigation_start_at", required=False, default=None)
    fum_reentry = v.get_instant(payload, "fumigation_reentry_at", required=False, default=None)

    # The fumigation trio is required exactly for FUMIGATION; PRD 3.5 pins every
    # failure of that pairing at ERR_INVALID_REQUEST rather than 422.
    if method == "FUMIGATION":
        if permit is None:
            raise invalid_request("fumigation_permit_number is required for a FUMIGATION plan")
        if fum_start is None:
            raise invalid_request("fumigation_start_at is required for a FUMIGATION plan")
        if fum_reentry is None:
            raise invalid_request("fumigation_reentry_at is required for a FUMIGATION plan")
        if fum_reentry <= fum_start:
            raise invalid_request(
                "fumigation_reentry_at must be strictly after fumigation_start_at")
    else:
        if permit is not None or fum_start is not None or fum_reentry is not None:
            raise invalid_request(
                "fumigation fields are only permitted on a FUMIGATION plan")

    prop = get_property(property_id)
    inspection = get_inspection(inspection_id)
    get_inspector(applicator_id)

    if method not in calc.METHOD_BY_CONSTRUCTION[prop["construction_type"]]:
        raise ApiError("ERR_METHOD_NOT_PERMITTED", 422,
                       "%s is not permitted on %s construction"
                       % (method, prop["construction_type"]))
    if inspection["property_id"] != prop["id"]:
        raise ApiError("ERR_PROPERTY_MISMATCH", 422,
                       "the justifying graph belongs to another structure")
    if product not in calc.PRODUCT_BY_METHOD[method]:
        raise ApiError("ERR_PRODUCT_METHOD_INCOMPATIBLE", 422,
                       "%s may not be loaded into a %s plan" % (product, method))

    row = new_row({
        "property_id": prop["id"],
        "inspection_id": inspection["id"],
        "applicator_id": applicator_id,
        "method": method,
        "chemical_product_code": product,
        "fumigation_permit_number": permit,
        "fumigation_start_at": fum_start,
        "fumigation_reentry_at": fum_reentry,
        "status": "PROPOSED",
        "target_gallons": calc.r2(calc.target_gallons(method, prop)),
        "target_station_count": calc.target_station_count(method, prop),
        "quoted_price_usd": calc.quoted_price(method, prop, inspection),
        "gallons_applied_total": calc.ZERO,
        "escalated_station_count": 0,
        "retreat_required": False,
        "completed_at": None,
    })
    db.plans[row["id"]] = row

    for other in plans_of(prop["id"]):
        if other["id"] != row["id"] and other["status"] == "PROPOSED":
            other["status"] = "ABANDONED"
            touch(other)

    return created(plan_out(row))


@bp.get("/treatment-plans/<pid>")
def read_plan(pid):
    authenticate(ALL)
    return ok(plan_out(get_plan(pid)))


@bp.get("/treatment-plans")
def list_plans():
    authenticate(ALL)
    rows = apply_filters(by_created(list(db.plans.values())), {
        "property_id": v.query_str("property_id"),
        "inspection_id": v.query_str("inspection_id"),
        "applicator_id": v.query_str("applicator_id"),
        "status": v.query_str("status"),
        "method": v.query_str("method"),
    })
    return listing(rows, plan_out)


@bp.post("/treatment-plans/<pid>/approve")
def approve_plan(pid):
    authenticate(("BranchManager",))
    plan = get_plan(pid)
    if plan["status"] != "PROPOSED":
        raise invalid_state("TreatmentPlan", "only a PROPOSED plan may be approved")
    inspection = get_inspection(plan["inspection_id"])
    require_graphed(inspection)
    applicator = get_inspector(plan["applicator_id"])
    require_license_active(applicator)
    require_license_unexpired(applicator)
    plan["status"] = "APPROVED"
    touch(plan)
    return ok(plan_out(plan))


@bp.post("/treatment-plans/<pid>/abandon")
def abandon_plan(pid):
    authenticate(("BranchManager",))
    plan = get_plan(pid)
    if plan["status"] != "APPROVED":
        raise invalid_state("TreatmentPlan", "only an APPROVED plan may be abandoned")
    today = clock.today()
    for record in records_of(plan["id"]):
        if record["retention_until"] >= today:
            raise ApiError("ERR_RETENTION_LOCK_ACTIVE", 409,
                           "a pesticide record is still inside its state retention period")
    plan["status"] = "ABANDONED"
    touch(plan)
    return ok(plan_out(plan))


@bp.post("/treatment-plans/<pid>/applications")
def create_application(pid):
    user_id, _role = authenticate(("Applicator",))
    plan = get_plan(pid)
    if plan["applicator_id"] != user_id:
        raise not_owner("only the plan's own applicator may discharge chemical")

    payload = v.body()
    epa = v.get_string(payload, "product_epa_number", pattern=v.EPA_RE)
    gallons = v.get_money(payload, "gallons_applied", minimum="0.10", maximum="2000.00")
    concentration = v.get_money(payload, "concentration_pct", minimum="0.01", maximum="5.00")
    expected = v.get_int(payload, "expected_treatment_plan_version")

    if expected != plan["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_treatment_plan_version %d does not match the plan's %d"
                       % (expected, plan["version"]))
    if plan["status"] != "APPROVED":
        raise invalid_state("TreatmentPlan",
                            "chemical may only be recorded against an APPROVED plan")

    applicator = get_inspector(plan["applicator_id"])
    prop = get_property(plan["property_id"])
    require_license_active(applicator)
    require_license_unexpired(applicator)
    if applicator["license_state"] != prop["state_code"]:
        raise ApiError("ERR_LICENSE_STATE_MISMATCH", 422,
                       "licence issued by %s may not discharge in %s"
                       % (applicator["license_state"], prop["state_code"]))
    if plan["method"] == "FUMIGATION":
        require_category(applicator, "FUMIGATION_CERTIFIED")
        if not applicator["fumigation_endorsement"]:
            raise ApiError("ERR_CATEGORY_NOT_LICENSED", 422,
                           "the fumigation endorsement flag is not set on this licence")
    else:
        require_category(applicator, "TERMITE_APPLICATOR")

    applied_at = clock.now()
    if plan["method"] == "FUMIGATION" and applied_at < plan["fumigation_start_at"]:
        raise ApiError("ERR_APPLICATION_BEFORE_PERMIT_WINDOW", 422,
                       "fumigant may not be recorded before the permitted start instant")

    years = calc.RETENTION_YEARS[prop["state_code"]]
    row = new_row({
        "treatment_plan_id": plan["id"],
        "applicator_license_number": applicator["license_number"],
        "applicator_license_state": applicator["license_state"],
        "state_code": prop["state_code"],
        "product_epa_number": epa,
        "gallons_applied": calc.r2(gallons),
        "concentration_pct": calc.r2(concentration),
        "applied_at": applied_at,
        "retention_until": plus_days(applied_at.date(), years * 365),
    }, versioned=False)
    db.records[row["id"]] = row

    plan["gallons_applied_total"] = calc.r2(plan["gallons_applied_total"] + gallons)
    touch(plan)

    return created(record_out(row))


@bp.get("/treatment-plans/<pid>/applications")
def list_applications(pid):
    authenticate(RECORD_READERS)
    plan = get_plan(pid)
    return listing(by_seq(records_of(plan["id"])), record_out)


@bp.post("/treatment-plans/<pid>/complete")
def complete_plan(pid):
    authenticate(("Applicator",))
    plan = get_plan(pid)
    if plan["status"] != "APPROVED":
        raise invalid_state("TreatmentPlan", "only an APPROVED plan may be completed")

    now = clock.now()
    if plan["method"] == "LIQUID_BARRIER":
        if plan["gallons_applied_total"] < plan["target_gallons"]:
            raise invalid_state("TreatmentPlan",
                                "gallons_applied_total has not reached target_gallons")
    elif plan["method"] == "BAIT_STATION":
        if len(records_of(plan["id"])) == 0:
            raise invalid_state("TreatmentPlan",
                                "a BAIT_STATION plan needs at least one application record")
    elif plan["method"] == "FUMIGATION":
        if now < plan["fumigation_reentry_at"]:
            raise invalid_state("TreatmentPlan",
                                "the structure has not reached its re-entry instant")

    plan["status"] = "COMPLETED"
    plan["completed_at"] = now
    touch(plan)

    if plan["method"] == "BAIT_STATION":
        due = plus_days(now, calc.STATION_INTERVAL_DAYS["INSTALLED"])
        for index in range(1, plan["target_station_count"] + 1):
            station = new_row({
                "treatment_plan_id": plan["id"],
                "station_index": index,
                "grid_ref": calc.station_grid_ref(index),
                "status": "INSTALLED",
                "consecutive_activity_count": 0,
                "last_serviced_at": now,
                "next_due_at": due,
                "service_count": 0,
                "matrix_replacement_count": 0,
            })
            db.stations[station["id"]] = station

    return ok(plan_out(plan))


@bp.get("/treatment-plans/<pid>/bait-stations")
def list_plan_stations(pid):
    authenticate(STATION_READERS)
    plan = get_plan(pid)
    rows = apply_filters(stations_of(plan["id"]), {"status": v.query_str("status")})
    return listing(rows, station_out)
