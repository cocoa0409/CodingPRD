"""Beneficial reuse agreements and ash shipments."""
from flask import Blueprint

import calc
import common
import derive
import envelope
import shape
import store
from errors import ApiError
from guards import authenticate, require_license_active
from routes_units import CODE_RE

bp = Blueprint("reuse", __name__)

AGREEMENT_SPEC = {
    "unit_id": {"t": "id", "req": True},
    "agreement_code": {"t": "str", "req": True, "min": 3, "max": 20,
                       "re": CODE_RE},
    "product_type": {"t": "enum", "req": True,
                     "vals": ("CONCRETE_POZZOLAN", "WALLBOARD",
                              "STRUCTURAL_FILL", "ROADBASE")},
    "offtaker_name": {"t": "str", "req": True, "min": 1, "max": 120},
    "committed_tons": {"t": "int", "req": True, "min": 1},
    "commitment_start_on": {"t": "date", "req": True},
    "commitment_end_on": {"t": "date", "req": True},
    "loi_percent": {"t": "num", "req": True, "min": 0, "max": 100, "dp": 2},
    "retained_325_percent": {"t": "num", "req": True, "min": 0, "max": 100,
                             "dp": 2},
    "oxide_sum_percent": {"t": "num", "req": True, "min": 0, "max": 100, "dp": 2},
    "market_price_usd_cents_per_ton": {"t": "int", "req": True, "min": 0},
    "haul_distance_miles": {"t": "int", "req": True, "min": 0},
}


@bp.post("/ccr/reuse-agreements")
def create_agreement():
    authenticate(("UtilityAdmin",))
    data = shape.read_body(AGREEMENT_SPEC)
    shape.require_order(data["commitment_start_on"], data["commitment_end_on"],
                        "commitment_start_on", "commitment_end_on")
    unit = common.get_unit(data["unit_id"])
    common.unique_code(store.reuse_agreements, "agreement_code",
                       data["agreement_code"])
    common.unit_not_care_complete(unit)
    record = dict(data)
    meets, score = calc.ash_quality_and_reuse_score(record)
    record["meets_astm_c618_class_f"] = meets
    record["qualification_score"] = score
    record["status"] = "DRAFT"
    record["shipped_tons_total"] = 0
    record["qualified_by"] = None
    record["qualified_on"] = None
    record["activated_on"] = None
    record["suspended_on"] = None
    store.stamp_new(record)
    store.reuse_agreements[record["id"]] = record
    return envelope.created(derive.agreement(record))


QUALIFY_SPEC = {"qualified_on": {"t": "date", "req": True}}


@bp.post("/ccr/reuse-agreements/<agreement_id>/qualify")
def qualify_agreement(agreement_id):
    actor = authenticate(("ProfessionalEngineer",))
    data = shape.read_body(QUALIFY_SPEC)
    agreement = common.get_agreement(agreement_id)
    unit = common.get_unit(agreement["unit_id"])
    require_license_active(actor)
    common.unit_not_care_complete(unit)
    if agreement["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "Only a DRAFT agreement may be qualified.")
    common.not_frozen(unit)
    meets, score = calc.ash_quality_and_reuse_score(agreement)
    agreement["meets_astm_c618_class_f"] = meets
    agreement["qualification_score"] = score
    if not meets:
        raise ApiError("ERR_ASH_QUALITY_FAILS_SPEC",
                       "The ash does not meet ASTM C618 Class F.")
    derive.refresh_unit(unit)
    exposure = calc.reuse_commitment_exposure(agreement)
    if exposure > unit["ash_in_place_tons"]:
        raise ApiError("ERR_REUSE_COMMITMENT_OVERLAP",
                       "The overlapping reuse commitments exceed the ash on site.")
    agreement["qualified_on"] = data["qualified_on"]
    agreement["qualified_by"] = actor.user_id
    agreement["status"] = ("QUALIFIED"
                           if score >= calc.MARKET_READY_SCORE_MIN
                           else "DISQUALIFIED")
    store.touch(agreement)
    return envelope.ok(derive.agreement(agreement))


ACTIVATE_SPEC = {"activated_on": {"t": "date", "req": True}}


@bp.post("/ccr/reuse-agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    authenticate(("UtilityAdmin",))
    data = shape.read_body(ACTIVATE_SPEC)
    agreement = common.get_agreement(agreement_id)
    unit = common.get_unit(agreement["unit_id"])
    common.unit_not_care_complete(unit)
    if agreement["status"] != "QUALIFIED":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "Only a QUALIFIED agreement may be activated.")
    common.not_frozen(unit)
    common.not_restricted(unit)
    agreement["status"] = "ACTIVE"
    agreement["activated_on"] = data["activated_on"]
    store.touch(agreement)
    return envelope.ok(derive.agreement(agreement))


SHIPMENT_SPEC = {
    "agreement_id": {"t": "id", "req": True},
    "shipment_code": {"t": "str", "req": True, "min": 3, "max": 20, "re": CODE_RE},
    "tons": {"t": "int", "req": True, "min": 1},
    "shipped_on": {"t": "date", "req": True},
    "expected_unit_version": {"t": "int", "req": True, "min": 0},
}


@bp.post("/ccr/reuse-shipments")
def create_shipment():
    authenticate(("UtilityAdmin",))
    data = shape.read_body(SHIPMENT_SPEC)
    agreement = common.get_agreement(data["agreement_id"])
    unit = common.get_unit(agreement["unit_id"])
    common.no_future_date(data["shipped_on"])
    common.unique_code(store.reuse_shipments, "shipment_code",
                       data["shipment_code"], "agreement_id", agreement["id"])
    if data["expected_unit_version"] != unit["version"]:
        raise ApiError("ERR_STALE_UNIT_VERSION",
                       "The disposal unit has been modified by another writer.")
    common.unit_not_care_complete(unit)
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "Only an ACTIVE agreement may ship ash.")
    common.not_frozen(unit)
    common.not_restricted(unit)
    if not (agreement["commitment_start_on"] <= data["shipped_on"]
            <= agreement["commitment_end_on"]):
        raise ApiError("ERR_SHIPMENT_OUTSIDE_COMMITMENT_WINDOW",
                       "shipped_on falls outside the commitment window.")
    shipped_total = calc.agreement_shipped_tons(agreement["id"])
    if shipped_total + data["tons"] > agreement["committed_tons"]:
        raise ApiError("ERR_COMMITTED_TONS_EXCEEDED",
                       "The shipment exceeds the agreement's committed tons.")
    derive.refresh_unit(unit)
    if data["tons"] > unit["ash_in_place_tons"]:
        raise ApiError("ERR_ASH_TONS_EXCEED_INVENTORY",
                       "The shipment exceeds the unit's ash inventory.")
    record = {
        "agreement_id": agreement["id"],
        "shipment_code": data["shipment_code"],
        "tons": data["tons"],
        "shipped_on": data["shipped_on"],
        "status": "SHIPPED",
        "returned_on": None,
        "return_reason": None,
    }
    store.stamp_new(record)
    store.reuse_shipments[record["id"]] = record
    calc.ash_in_place_balance(unit)
    if agreement["shipped_tons_total"] >= agreement["committed_tons"]:
        agreement["status"] = "COMPLETED"
    store.touch(agreement)
    store.touch(unit)
    common.settle(unit)
    return envelope.created(derive.shipment(record))


RETURN_SPEC = {
    "returned_on": {"t": "date", "req": True},
    "return_reason": {"t": "str", "req": True, "min": 1},
    "expected_unit_version": {"t": "int", "req": True, "min": 0},
}


@bp.post("/ccr/reuse-shipments/<shipment_id>/return")
def return_shipment(shipment_id):
    authenticate(("UtilityAdmin",))
    data = shape.read_body(RETURN_SPEC)
    shipment = common.get_shipment(shipment_id)
    agreement = common.get_agreement(shipment["agreement_id"])
    unit = common.get_unit(agreement["unit_id"])
    if data["expected_unit_version"] != unit["version"]:
        raise ApiError("ERR_STALE_UNIT_VERSION",
                       "The disposal unit has been modified by another writer.")
    common.unit_not_care_complete(unit)
    if agreement["status"] not in ("ACTIVE", "COMPLETED"):
        raise ApiError("ERR_INVALID_AGREEMENT_STATE",
                       "The agreement does not accept a shipment return.")
    if shipment["status"] != "SHIPPED":
        raise ApiError("ERR_INVALID_SHIPMENT_STATE",
                       "Only a SHIPPED shipment may be returned.")
    shipment["status"] = "RETURNED"
    shipment["returned_on"] = data["returned_on"]
    shipment["return_reason"] = data["return_reason"]
    store.touch(shipment)
    calc.ash_in_place_balance(unit)
    if (agreement["status"] == "COMPLETED"
            and agreement["shipped_tons_total"] < agreement["committed_tons"]):
        agreement["status"] = "ACTIVE"
    store.touch(agreement)
    store.touch(unit)
    common.settle(unit)
    return envelope.ok(derive.shipment(shipment))
