"""Finished-goods lots: opening, dispensing, release and the availability axis
(PRD 3.3 and 3.5)."""

from flask import Blueprint

import calc
import lookup
import recompute
import serialize
from errors import ApiError
from store import add_months, create_row, db, now_clock, rows, touch
from response import created_response, list_response, object_response
from validation import (ALL_ROLES, ALLOCATION_STATUSES, Body, COMPONENT_STATUSES,
                        DISPOSITION_STATUSES, DISTRIBUTION_STATUSES,
                        MATERIAL_TYPES, REAGENT_DECISIONS, SHELF_LIFE_BASES,
                        authenticate_and_authorize, enum_filter, json_body,
                        pagination, paginate, str_filter)

bp = Blueprint("reagent_lots", __name__)


@bp.post("/reagent-lots")
def create_reagent_lot():
    authenticate_and_authorize(("ProductionOperator",))
    body = Body(json_body())
    spec_id = body.req_str("product_specification_id")
    lot_code = body.req_str("lot_code")
    planned_units = body.req_int("planned_units", gt=0)

    # Rung 45 - body foreign keys.
    lookup.product_specification(spec_id)

    # Rung 70 - the pair is unique.
    for existing in rows(db.reagent_lots):
        if existing["product_specification_id"] == spec_id and \
                existing["lot_code"] == lot_code:
            raise ApiError("ERR_DUPLICATE_LOT_CODE",
                           "lot_code '%s' already exists for this product." % lot_code)

    row = create_row(db.reagent_lots, {
        "product_specification_id": spec_id,
        "lot_code": lot_code,
        "planned_units": planned_units,
        "filled_units": 0,
        "available_units": 0,
        "allocated_units": 0,
        "shipped_units": 0,
        "quarantined_units": 0,
        "disposition_status": "PLANNED",
        "distribution_status": "WITHHELD",
        "fill_completed_at": None,
        "assigned_shelf_life_months": None,
        "shelf_life_basis": None,
        "shelf_life_basis_study_id": None,
        "expiry_date": None,
        "release_bias_max_pct": None,
        "release_bias_sum_pct": None,
        "em_excursion_count": 0,
        "bioburden_cfu_per_ml": None,
        "bridging_required": False,
        "released_by_user_id": None,
        "released_at": None,
    })
    return created_response(serialize.reagent_lot(row))


@bp.get("/reagent-lots/<lot_id>")
def read_reagent_lot(lot_id):
    authenticate_and_authorize(ALL_ROLES)
    row = lookup.reagent_lot(lot_id)
    return object_response(serialize.reagent_lot(row))


@bp.get("/reagent-lots")
def list_reagent_lots():
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    spec_id = str_filter("product_specification_id")
    disposition_status = enum_filter("disposition_status", DISPOSITION_STATUSES)
    distribution_status = enum_filter("distribution_status", DISTRIBUTION_STATUSES)
    study_id = str_filter("shelf_life_basis_study_id")
    lot_code = str_filter("lot_code")
    items = rows(db.reagent_lots)
    if spec_id is not None:
        items = [r for r in items if r["product_specification_id"] == spec_id]
    if disposition_status is not None:
        items = [r for r in items if r["disposition_status"] == disposition_status]
    if distribution_status is not None:
        items = [r for r in items if r["distribution_status"] == distribution_status]
    if study_id is not None:
        items = [r for r in items if r["shelf_life_basis_study_id"] == study_id]
    if lot_code is not None:
        items = [r for r in items if r["lot_code"] == lot_code]
    page = paginate(items, limit, offset)
    return list_response([serialize.reagent_lot(r) for r in page],
                         limit, offset, len(items))


@bp.post("/reagent-lots/<lot_id>/components")
def dispense_component(lot_id):
    authenticate_and_authorize(("ProductionOperator",))
    body = Body(json_body())
    material_lot_id = body.req_str("material_lot_id")
    component_role = body.req_enum("component_role", MATERIAL_TYPES)
    quantity_used = body.req_number("quantity_used", gt=0)
    expected_version = body.req_int("expected_reagent_lot_version")

    lot = lookup.reagent_lot(lot_id)

    # Rung 45 - body foreign keys.
    material_lot = lookup.material_lot(material_lot_id)

    # Rung 60 - dispensing is only available while the lot is PLANNED.
    if lot["disposition_status"] != "PLANNED":
        raise ApiError("ERR_REAGENT_LOT_STATE_INVALID",
                       "A lot in %s no longer accepts components."
                       % lot["disposition_status"])

    # Rung 65 - optimistic concurrency on the parent aggregate.
    if expected_version != lot["version"]:
        raise ApiError("ERR_STALE_REAGENT_LOT_VERSION")

    material_spec = db.material_specifications[material_lot["material_specification_id"]]
    product = db.product_specifications[lot["product_specification_id"]]

    # Rung 75 - qualification.
    if material_lot["qualification_status"] != "QUALIFIED":
        raise ApiError("ERR_MATERIAL_NOT_QUALIFIED")

    # Rung 76 - expiry; an instant equal to the clock is already expired.
    if not material_lot["expiry_date"] > now_clock():
        raise ApiError("ERR_MATERIAL_EXPIRED")

    # Rung 78 - sufficiency; inclusive equality is fine.
    if quantity_used > calc.dec(material_lot["available_quantity_units"]):
        raise ApiError("ERR_INSUFFICIENT_MATERIAL")

    # Rung 123 - the structural check sits last.
    if component_role != material_spec["material_type"] or \
            material_spec["material_code"] not in product["required_material_codes"]:
        raise ApiError("ERR_COMPONENT_ROLE_NOT_IN_BOM")

    component = create_row(db.lot_components, {
        "reagent_lot_id": lot["id"],
        "material_lot_id": material_lot["id"],
        "component_role": component_role,
        "quantity_used": quantity_used,
        "status": "CONSUMED",
        "material_code_snapshot": material_spec["material_code"],
        "vendor_lot_code_snapshot": material_lot["vendor_lot_code"],
    })

    recompute.material_lot_quantities(material_lot)
    touch(material_lot)
    recompute.reagent_lot_bridging_required(lot)
    touch(lot)
    return created_response(serialize.lot_component(component))


@bp.get("/reagent-lots/<lot_id>/components")
def list_components(lot_id):
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", COMPONENT_STATUSES)
    component_role = enum_filter("component_role", MATERIAL_TYPES)
    lot = lookup.reagent_lot(lot_id)
    items = [c for c in rows(db.lot_components) if c["reagent_lot_id"] == lot["id"]]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if component_role is not None:
        items = [c for c in items if c["component_role"] == component_role]
    page = paginate(items, limit, offset)
    return list_response([serialize.lot_component(c) for c in page],
                         limit, offset, len(items))


@bp.get("/reagent-lots/<lot_id>/allocations")
def list_lot_allocations(lot_id):
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    status = enum_filter("status", ALLOCATION_STATUSES)
    lot = lookup.reagent_lot(lot_id)
    items = calc.allocation_rows(reagent_lot_id=lot["id"])
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page = paginate(items, limit, offset)
    return list_response([serialize.allocation(a) for a in page],
                         limit, offset, len(items))


def _release_gates(lot, product, shelf_life_basis):
    """The release gates of PRD 3.5, evaluated in the pinned ladder order."""
    # Rung 80 - environmental conformance.
    for run in calc.lot_runs(lot["id"]):
        if run["environmental_state"] == "DISQUALIFIED":
            raise ApiError("ERR_ENVIRONMENTAL_NONCONFORMANCE")

    # Rung 82 - release test completeness.
    if not calc.release_tests_all_pass(product, lot["id"]):
        raise ApiError("ERR_RELEASE_TESTS_INCOMPLETE")

    # Rung 84 - reference bias, inclusive.
    maximum = lot["release_bias_max_pct"]
    if maximum is not None and \
            calc.dec(maximum) > calc.dec(product["max_reference_bias_pct"]):
        raise ApiError("ERR_REFERENCE_BIAS_EXCEEDED")

    # Rung 86 - bill-of-materials completeness.
    consumed = calc.lot_components(lot["id"], "CONSUMED")
    snapshots = set(c["material_code_snapshot"] for c in consumed)
    for code in product["required_material_codes"]:
        if code not in snapshots:
            raise ApiError("ERR_BOM_INCOMPLETE")

    # Rung 88 - bridging evidence.
    if lot["bridging_required"]:
        approved = [s for s in rows(db.bridging_studies)
                    if s["candidate_lot_id"] == lot["id"] and s["status"] == "APPROVED"]
        if not approved:
            raise ApiError("ERR_BRIDGING_REQUIRED")

    # Rung 90 - stability evidence.
    study = None
    if shelf_life_basis in ("REAL_TIME", "ACCELERATED"):
        candidates = [s for s in rows(db.stability_studies)
                      if s["product_specification_id"] == product["id"]
                      and s["study_type"] == shelf_life_basis
                      and s["status"] == "COMPLETE"
                      and s["established_shelf_life_months"] is not None]
        if not candidates:
            raise ApiError("ERR_STABILITY_DATA_MISSING")
        candidates.sort(key=lambda s: (-s["established_shelf_life_months"],
                                       s["created_at"], s["_seq"]))
        study = candidates[0]

    # Rung 130 - product clearance, deliberately below every quality gate.
    if product["clearance_status"] != "CLEARED":
        raise ApiError("ERR_PRODUCT_NOT_CLEARED")
    return study


@bp.post("/reagent-lots/<lot_id>/disposition")
def disposition_reagent_lot(lot_id):
    user_id, _role = authenticate_and_authorize(("QAReleaser",))
    body = Body(json_body())
    decision = body.req_enum("decision", REAGENT_DECISIONS)
    body.opt_str("reason")
    shelf_life_basis = body.opt_enum("shelf_life_basis", SHELF_LIFE_BASES, "CLAIM")
    lot = lookup.reagent_lot(lot_id)
    product = db.product_specifications[lot["product_specification_id"]]

    # Rung 50 - segregation of duties against every release measurement.
    for record in calc.reagent_results(lot["id"]):
        if record["performed_by_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The analyst who generated the release data may not "
                           "sign it off.")

    # Rung 60 - state precondition on the quality axis.
    if lot["disposition_status"] != "UNDER_RELEASE_TEST":
        raise ApiError("ERR_REAGENT_LOT_STATE_INVALID",
                       "A lot in %s cannot be dispositioned."
                       % lot["disposition_status"])

    clock = now_clock()
    if decision == "REJECT":
        lot["disposition_status"] = "REJECTED"
        recompute.reagent_lot_units(lot)
        lot["available_units"] = 0
        touch(lot)
        return object_response(serialize.reagent_lot(lot))

    study = _release_gates(lot, product, shelf_life_basis)

    # Hop 1 - the quality axis and the pinned shelf life.
    lot["disposition_status"] = "RELEASED"
    lot["released_by_user_id"] = user_id
    lot["released_at"] = clock
    lot["shelf_life_basis"] = shelf_life_basis
    if shelf_life_basis == "CLAIM":
        lot["assigned_shelf_life_months"] = product["shelf_life_months_claim"]
        lot["shelf_life_basis_study_id"] = None
    else:
        lot["assigned_shelf_life_months"] = study["established_shelf_life_months"]
        lot["shelf_life_basis_study_id"] = study["id"]
    if lot["fill_completed_at"] is not None:
        lot["expiry_date"] = add_months(lot["fill_completed_at"],
                                        lot["assigned_shelf_life_months"])

    # Hop 2 - the availability axis follows automatically.
    if lot["distribution_status"] == "WITHHELD":
        lot["distribution_status"] = "AVAILABLE"
    touch(lot)
    return object_response(serialize.reagent_lot(lot))


@bp.post("/reagent-lots/<lot_id>/distribution-status")
def move_distribution_status(lot_id):
    authenticate_and_authorize(("QAReleaser",))
    body = Body(json_body())
    target = body.req_enum("distribution_status", DISTRIBUTION_STATUSES)
    body.opt_str("reason")
    lot = lookup.reagent_lot(lot_id)
    current = lot["distribution_status"]

    # Rung 60 - state precondition on the availability axis.
    if target == "AVAILABLE":
        if current not in ("WITHHELD", "BLOCKED") or \
                lot["disposition_status"] != "RELEASED":
            raise ApiError("ERR_REAGENT_LOT_STATE_INVALID",
                           "The lot cannot be made AVAILABLE from %s/%s."
                           % (lot["disposition_status"], current))
    elif target == "BLOCKED":
        if current != "AVAILABLE":
            raise ApiError("ERR_REAGENT_LOT_STATE_INVALID",
                           "Only an AVAILABLE lot can be BLOCKED.")
    else:
        raise ApiError("ERR_REAGENT_LOT_STATE_INVALID",
                       "No transition into WITHHELD exists.")

    lot["distribution_status"] = target
    touch(lot)
    return object_response(serialize.reagent_lot(lot))
