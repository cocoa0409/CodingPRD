"""Logical clock, structures and the licensed field force (PRD 2.5, 3.1, 3.2)."""

from flask import Blueprint

import calc
import validate as v
from auth import ROLES, authenticate
from clock import clock
from common import apply_filters, get_inspector, get_property
from envelope import created, fmt_instant, listing, ok
from errors import ApiError
from ledger import recompute_property_ledger
from serialize import inspector_out, property_out
from store import by_created, db, new_row, touch

bp = Blueprint("core", __name__)

ALL = ROLES
NO_OWNER = ("ComplianceOfficer", "BranchManager", "FieldInspector", "Applicator",
            "ClaimsAdjudicator")


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("ComplianceOfficer",))
    payload = v.body()
    instant = v.get_instant(payload, "current_utc")
    clock.set(instant)
    return ok({"current_utc": fmt_instant(clock.now())})


@bp.get("/_clock/current")
def read_clock():
    # The single endpoint exempt from the header requirement (PRD 2.5).
    return ok({"current_utc": fmt_instant(clock.now())})


# --------------------------------------------------------------------------
# structures
# --------------------------------------------------------------------------

@bp.post("/properties")
def create_property():
    authenticate(("ComplianceOfficer",))
    payload = v.body()
    row = new_row({
        "address_line1": v.get_string(payload, "address_line1", min_len=1, max_len=120),
        "state_code": v.get_enum(payload, "state_code", calc.STATE_CODES),
        "construction_type": v.get_enum(payload, "construction_type", calc.CONSTRUCTION_TYPES),
        "square_footage": v.get_int(payload, "square_footage", minimum=200, maximum=12000),
        "linear_footage": v.get_int(payload, "linear_footage", minimum=20, maximum=2000),
        "year_built": v.get_int(payload, "year_built", minimum=1850, maximum=2026),
        "crawl_clearance_inches": v.get_int(payload, "crawl_clearance_inches", required=False,
                                            default=None, minimum=0, maximum=60),
        "has_attached_structures": v.get_bool(payload, "has_attached_structures",
                                              required=False, default=False),
        "total_conducive_condition_count": 0,
        "waived_conducive_condition_count": 0,
        "open_conducive_condition_count": 0,
        "active_infestation_on_record": False,
    })
    db.properties[row["id"]] = row
    return created(property_out(row))


@bp.get("/properties/<pid>")
def read_property(pid):
    authenticate(ALL)
    return ok(property_out(get_property(pid)))


@bp.get("/properties")
def list_properties():
    authenticate(ALL)
    rows = apply_filters(by_created(list(db.properties.values())), {
        "state_code": v.query_str("state_code"),
        "construction_type": v.query_str("construction_type"),
    })
    return listing(rows, property_out)


# --------------------------------------------------------------------------
# inspectors
# --------------------------------------------------------------------------

@bp.post("/inspectors")
def create_inspector():
    authenticate(("ComplianceOfficer",))
    payload = v.body()
    row = new_row({
        "full_name": v.get_string(payload, "full_name", min_len=1, max_len=80),
        "license_number": v.get_string(payload, "license_number",
                                       pattern=v.LICENSE_NUMBER_RE),
        "license_state": v.get_enum(payload, "license_state", calc.STATE_CODES),
        "license_categories": v.get_enum_array(payload, "license_categories",
                                               calc.LICENSE_CATEGORIES,
                                               min_items=1, max_items=3),
        "license_expires_on": v.get_date(payload, "license_expires_on"),
        "fumigation_endorsement": v.get_bool(payload, "fumigation_endorsement",
                                             required=False, default=False),
        "ce_credits": v.get_int(payload, "ce_credits", required=False, default=0,
                                minimum=0, maximum=99),
        "status": "ACTIVE",
    })
    db.inspectors[row["id"]] = row
    return created(inspector_out(row))


@bp.get("/inspectors/<iid>")
def read_inspector(iid):
    authenticate(ALL)
    return ok(inspector_out(get_inspector(iid)))


@bp.get("/inspectors")
def list_inspectors():
    authenticate(NO_OWNER)
    rows = apply_filters(by_created(list(db.inspectors.values())), {
        "status": v.query_str("status"),
        "license_state": v.query_str("license_state"),
    })
    return listing(rows, inspector_out)


@bp.post("/inspectors/<iid>/license-status")
def license_status(iid):
    authenticate(("ComplianceOfficer",))
    inspector = get_inspector(iid)
    payload = v.body()
    wanted = v.get_enum(payload, "status", calc.INSPECTOR_STATUSES)
    expires_on = v.get_date(payload, "license_expires_on", required=False, default=None)
    credits = v.get_int(payload, "ce_credits", required=False, default=None,
                        minimum=0, maximum=99)

    current = inspector["status"]
    declared = {("ACTIVE", "SUSPENDED"), ("ACTIVE", "EXPIRED"),
                ("SUSPENDED", "ACTIVE"), ("EXPIRED", "ACTIVE")}
    if (current, wanted) not in declared:
        raise ApiError("ERR_INVALID_INSPECTOR_STATE", 409,
                       "%s -> %s is not a declared licence transition" % (current, wanted))

    if current == "SUSPENDED" and wanted == "ACTIVE":
        if inspector["license_expires_on"] < clock.today():
            raise ApiError("ERR_LICENSE_EXPIRED", 409,
                           "a suspension cannot be lifted on an expired credential")
    elif current == "EXPIRED" and wanted == "ACTIVE":
        effective = credits if credits is not None else inspector["ce_credits"]
        if expires_on is None or expires_on <= clock.today():
            raise ApiError("ERR_LICENSE_REINSTATEMENT_UNMET", 422,
                           "reinstatement requires a license_expires_on after the clock date")
        if effective < calc.CE_CREDITS_REQUIRED:
            raise ApiError("ERR_LICENSE_REINSTATEMENT_UNMET", 422,
                           "reinstatement requires at least %d continuing-education credits"
                           % calc.CE_CREDITS_REQUIRED)
        inspector["license_expires_on"] = expires_on
        if credits is not None:
            inspector["ce_credits"] = credits

    inspector["status"] = wanted
    touch(inspector)
    return ok(inspector_out(inspector))
