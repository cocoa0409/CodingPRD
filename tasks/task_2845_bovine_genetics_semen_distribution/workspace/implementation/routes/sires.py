"""Bulls: registration, pedigree, acquisition and the collection cycle."""

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

bp = Blueprint("sires", __name__)


@bp.post("/sires")
def create_sire():
    values = validate.parse([
        F("registration_code", "string", required=True, min_len=1, max_len=32),
        F("breed", "enum", required=True, enum=config.BREEDS),
        F("birth_date", "date", required=True),
        F("sire_id", "id", default=None),
        F("dam_sire_id", "id", default=None),
        F("acquisition_cost_cents", "integer", required=True, min=0),
    ])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR)
    resolve.optional("sires", values["sire_id"])
    resolve.optional("sires", values["dam_sire_id"])
    for existing in store.DB["sires"].values():
        if existing["registration_code"] == values["registration_code"]:
            fail("ERR_DUPLICATE_CODE",
                 "Registration code '%s' is already registered." % values["registration_code"])
    rec = store.new_record("sires", {
        "registration_code": values["registration_code"],
        "breed": values["breed"],
        "birth_date": values["birth_date"],
        "sire_id": values["sire_id"],
        "dam_sire_id": values["dam_sire_id"],
        "acquisition_cost_cents": values["acquisition_cost_cents"],
        "contract_price_cents": None,
        "acquisition_status": "PROSPECT",
        "collection_status": "NOT_HOUSED",
        "housing_facility_id": None,
        "isolation_ends_at": None,
        "isolation_days_applied": None,
        "suspension_reason": None,
        "published_production_index": 0.00,
        "published_health_index": 0.00,
        "published_composite_index": 0.00,
        "published_evaluation_effective_at": None,
        "progeny_daughter_count": 0,
        "pedigree_depth": calc.pedigree_depth(values["sire_id"], values["dam_sire_id"]),
        "retirement_reason": None,
    })
    return envelope.created(serializers.sire(rec))


@bp.get("/sires/<sire_id>")
def read_sire(sire_id):
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_FACILITY_MANAGER,
                      config.ROLE_STAFF_VET, config.ROLE_LAB_TECH,
                      config.ROLE_EXPORT_COORD, config.ROLE_BREEDING_ADVISOR)
    rec = resolve.need("sires", sire_id)
    return envelope.ok(serializers.sire(rec))


@bp.get("/sires")
def list_sires():
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_FACILITY_MANAGER,
                      config.ROLE_STAFF_VET, config.ROLE_EXPORT_COORD,
                      config.ROLE_BREEDING_ADVISOR)
    limit, offset = validate.pagination()
    breed = validate.qenum("breed", config.BREEDS)
    acquisition_status = validate.qenum("acquisition_status", config.ACQUISITION_STATUSES)
    collection_status = validate.qenum("collection_status", config.COLLECTION_STATUSES)
    housing_facility_id = validate.qstr("housing_facility_id")
    parent_id = validate.qstr("sire_id")
    dam_sire_id = validate.qstr("dam_sire_id")
    items = []
    for rec in store.rows("sires"):
        if breed is not None and rec["breed"] != breed:
            continue
        if acquisition_status is not None and rec["acquisition_status"] != acquisition_status:
            continue
        if collection_status is not None and rec["collection_status"] != collection_status:
            continue
        if housing_facility_id is not None and rec["housing_facility_id"] != housing_facility_id:
            continue
        if parent_id is not None and rec["sire_id"] != parent_id:
            continue
        if dam_sire_id is not None and rec["dam_sire_id"] != dam_sire_id:
            continue
        items.append(rec)
    return envelope.listing(items, limit, offset, serializers.sire)


@bp.post("/sires/<sire_id>/contract")
def contract_sire(sire_id):
    values = validate.parse([F("contract_price_cents", "integer", required=True, min=0)])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("sires", sire_id)
    if rec["acquisition_status"] != "PROSPECT":
        fail("ERR_SIRE_ACQUISITION_STATE", "Contracting requires acquisition_status PROSPECT.")
    rec["acquisition_status"] = "CONTRACTED"
    rec["contract_price_cents"] = values["contract_price_cents"]
    store.touch(rec)
    return envelope.ok(serializers.sire(rec))


@bp.post("/sires/<sire_id>/house")
def house_sire(sire_id):
    values = validate.parse([
        F("facility_id", "id", required=True),
        F("isolation_days", "integer", required=True, min=0),
    ])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_FACILITY_MANAGER)
    auth.require_facility_scope(values["facility_id"])
    rec = resolve.need("sires", sire_id)
    facility = resolve.need("facilities", values["facility_id"])
    if rec["acquisition_status"] != "CONTRACTED":
        fail("ERR_SIRE_ACQUISITION_STATE", "Housing requires acquisition_status CONTRACTED.")
    if rec["collection_status"] != "NOT_HOUSED":
        fail("ERR_SIRE_COLLECTION_STATE", "Housing requires collection_status NOT_HOUSED.")
    if facility["approval_status"] != "APPROVED":
        fail("ERR_FACILITY_SUSPENDED", "A suspended facility cannot house a bull.")
    if serializers.resident_sire_count(facility["id"]) + 1 > int(facility["housing_capacity"]):
        fail("ERR_FACILITY_AT_CAPACITY", "The facility has no residency room left.")
    rec["acquisition_status"] = "RESIDENT"
    rec["collection_status"] = "ISOLATION"
    rec["housing_facility_id"] = facility["id"]
    rec["isolation_days_applied"] = values["isolation_days"]
    rec["isolation_ends_at"] = store.iso(store.plus_days(store.clock(), values["isolation_days"]))
    store.touch(rec)
    return envelope.ok(serializers.sire(rec))


@bp.post("/sires/<sire_id>/collection-clearance")
def clear_sire_for_collection(sire_id):
    validate.parse([F("clearance_note", "string", default=None)])
    auth.require_role(config.ROLE_STAFF_VET)
    rec = resolve.need("sires", sire_id)
    if rec["collection_status"] != "ISOLATION":
        fail("ERR_SIRE_COLLECTION_STATE", "Clearance requires collection_status ISOLATION.")
    ends_at = store.dt_of(rec["isolation_ends_at"]) if rec["isolation_ends_at"] else None
    if ends_at is not None and store.clock() < ends_at:
        fail("ERR_ISOLATION_INCOMPLETE", "The isolation period has not been served.")
    if not calc.health_current(rec["id"]):
        fail("ERR_HEALTH_TESTS_NOT_CURRENT", "The four base required assays are not current.")
    rec["collection_status"] = "ELIGIBLE"
    rec["suspension_reason"] = None
    store.touch(rec)
    return envelope.ok(serializers.sire(rec))


@bp.post("/sires/<sire_id>/collection-status")
def set_sire_collection_status(sire_id):
    values = validate.parse([
        F("collection_status", "enum", required=True, enum=config.COLLECTION_STATUSES),
        F("suspension_reason", "string", default=None),
    ])
    auth.require_role(config.ROLE_STAFF_VET, config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("sires", sire_id)
    target = values["collection_status"]
    current = rec["collection_status"]
    if current == "WITHDRAWN":
        fail("ERR_SIRE_COLLECTION_STATE", "WITHDRAWN is terminal on the collection dimension.")
    if target == "SUSPENDED":
        if current != "ELIGIBLE":
            fail("ERR_SIRE_COLLECTION_STATE", "Suspension requires collection_status ELIGIBLE.")
        cascades.suspend_sire(rec, config.SUSP_MANUAL, config.CANCEL_SIRE_SUSPENDED, "at_or_after")
    elif target == "ELIGIBLE":
        if current != "SUSPENDED":
            fail("ERR_SIRE_COLLECTION_STATE", "Reinstatement requires collection_status SUSPENDED.")
        if rec["acquisition_status"] != "RESIDENT":
            fail("ERR_SIRE_ACQUISITION_STATE", "Reinstatement requires acquisition_status RESIDENT.")
        facility = store.get("facilities", rec["housing_facility_id"])
        if facility is None or facility["approval_status"] != "APPROVED":
            fail("ERR_FACILITY_SUSPENDED", "The housing facility is not APPROVED.")
        if not calc.health_current(rec["id"]):
            fail("ERR_HEALTH_TESTS_NOT_CURRENT", "The four base required assays are not current.")
        rec["collection_status"] = "ELIGIBLE"
        rec["suspension_reason"] = None
        store.touch(rec)
    elif target == "WITHDRAWN":
        rec["collection_status"] = "WITHDRAWN"
        store.touch(rec)
    else:
        fail("ERR_SIRE_COLLECTION_STATE",
             "The collection dimension does not permit a move to %s." % target)
    return envelope.ok(serializers.sire(rec))


@bp.post("/sires/<sire_id>/retire")
def retire_sire(sire_id):
    values = validate.parse([F("retirement_reason", "string", required=True)])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("sires", sire_id)
    if rec["acquisition_status"] != "RESIDENT":
        fail("ERR_SIRE_ACQUISITION_STATE", "Retirement requires acquisition_status RESIDENT.")
    rec["acquisition_status"] = "RETIRED"
    rec["collection_status"] = "WITHDRAWN"
    rec["retirement_reason"] = values["retirement_reason"]
    store.touch(rec)
    # Every SCHEDULED booking of this bull is voided, with no time filter.
    cascades.void_bookings(rec["id"], config.CANCEL_SIRE_SUSPENDED, "all")
    return envelope.ok(serializers.sire(rec))


@bp.post("/sires/<sire_id>/pedigree")
def correct_pedigree(sire_id):
    values = validate.parse([
        F("sire_id", "id", default=None),
        F("dam_sire_id", "id", default=None),
    ])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("sires", sire_id)
    resolve.optional("sires", values["sire_id"])
    resolve.optional("sires", values["dam_sire_id"])
    new_sire_id = values["sire_id"] if validate.was_supplied(values, "sire_id") else rec["sire_id"]
    new_dam_sire_id = (values["dam_sire_id"] if validate.was_supplied(values, "dam_sire_id")
                       else rec["dam_sire_id"])
    if calc.would_cycle(rec["id"], new_sire_id, new_dam_sire_id):
        fail("ERR_PEDIGREE_CYCLE", "The amendment would close a cycle in the pedigree graph.")
    rec["sire_id"] = new_sire_id
    rec["dam_sire_id"] = new_dam_sire_id
    rec["pedigree_depth"] = calc.pedigree_depth(new_sire_id, new_dam_sire_id)
    store.touch(rec)
    return envelope.ok(serializers.sire(rec))
