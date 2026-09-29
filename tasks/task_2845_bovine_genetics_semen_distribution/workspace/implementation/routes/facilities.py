"""Collection facilities and destination rule sets (PRD 3.4, 3.7)."""

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

bp = Blueprint("facilities", __name__)


@bp.post("/facilities")
def create_facility():
    values = validate.parse([
        F("code", "string", required=True, min_len=1, max_len=32),
        F("country_code", "string", required=True, pattern=COUNTRY_CODE_RE),
        F("housing_capacity", "integer", required=True, min=1),
        F("bench_capacity", "integer", required=True, min=1),
        F("approved_export_countries", "array", default=None, item_kind="string",
          pattern=COUNTRY_CODE_RE),
    ])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR)
    for existing in store.DB["facilities"].values():
        if existing["code"] == values["code"]:
            fail("ERR_DUPLICATE_CODE", "Facility code '%s' is already registered." % values["code"])
    rec = store.new_record("facilities", {
        "code": values["code"],
        "country_code": values["country_code"],
        "housing_capacity": values["housing_capacity"],
        "bench_capacity": values["bench_capacity"],
        "approved_export_countries": values["approved_export_countries"] or [],
        "approval_status": "APPROVED",
        "suspension_reason": None,
    })
    return envelope.created(serializers.facility(rec))


@bp.get("/facilities/<facility_id>")
def read_facility(facility_id):
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_FACILITY_MANAGER,
                      config.ROLE_STAFF_VET, config.ROLE_EXPORT_COORD)
    rec = resolve.need("facilities", facility_id)
    return envelope.ok(serializers.facility(rec))


@bp.post("/facilities/<facility_id>/approval-status")
def set_facility_approval_status(facility_id):
    values = validate.parse([
        F("approval_status", "enum", required=True, enum=config.FACILITY_STATUSES),
        F("suspension_reason", "string", default=None),
    ])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR)
    auth.require_facility_scope(facility_id)
    rec = resolve.need("facilities", facility_id)
    target = values["approval_status"]
    if rec["approval_status"] == target:
        fail("ERR_FACILITY_SUSPENDED", "The facility is already %s." % target)
    if target == "SUSPENDED":
        rec["approval_status"] = "SUSPENDED"
        rec["suspension_reason"] = values["suspension_reason"]
        store.touch(rec)
        # Two-hop cascade: eligible residents are suspended, and their future
        # SCHEDULED bookings are voided as a consequence of that suspension.
        for sire in store.rows("sires"):
            if sire["housing_facility_id"] != facility_id:
                continue
            if sire["collection_status"] != "ELIGIBLE":
                continue
            cascades.suspend_sire(sire, config.SUSP_FACILITY,
                                  config.CANCEL_FACILITY_SUSPENDED, "at_or_after")
    else:
        rec["approval_status"] = "APPROVED"
        rec["suspension_reason"] = None
        store.touch(rec)
    return envelope.ok(serializers.facility(rec))


@bp.post("/country-requirements")
def create_country_requirement():
    values = validate.parse([
        F("country_code", "string", required=True, pattern=COUNTRY_CODE_RE),
        F("required_test_types", "array", required=True, non_empty=True,
          item_kind="string", item_enum=config.TEST_TYPES),
        F("max_test_age_days", "integer", required=True, min=1),
        F("min_isolation_days", "integer", required=True, min=0),
        F("sexed_semen_allowed", "boolean", required=True),
        F("embryo_allowed", "boolean", required=True),
    ])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_EXPORT_COORD)
    for existing in store.DB["country_requirements"].values():
        if existing["country_code"] == values["country_code"]:
            fail("ERR_DUPLICATE_CODE",
                 "A rule set for '%s' is already on file." % values["country_code"])
    rec = store.new_record("country_requirements", {
        "country_code": values["country_code"],
        "required_test_types": values["required_test_types"],
        "max_test_age_days": values["max_test_age_days"],
        "min_isolation_days": values["min_isolation_days"],
        "sexed_semen_allowed": values["sexed_semen_allowed"],
        "embryo_allowed": values["embryo_allowed"],
    })
    return envelope.created(serializers.country_requirement(rec))


@bp.get("/country-requirements/<requirement_id>")
def read_country_requirement(requirement_id):
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_EXPORT_COORD,
                      config.ROLE_STAFF_VET)
    rec = resolve.need("country_requirements", requirement_id)
    return envelope.ok(serializers.country_requirement(rec))


@bp.get("/inventory-valuation")
def read_inventory_valuation():
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_LAB_TECH)
    return envelope.ok(calc.plant_inventory())
