# IngredientLot domain (PRD 3.2): receipt into QUARANTINE against an ACTIVE
# agreement with the 110% over-receipt tolerance, and QC release/reject.
from flask import Blueprint, request

import constants
from errors import err
from middleware import authenticate, authorize
from response import paginate, success
from services import (
    compute_final_unit_cost,
    compute_provisional_unit_cost,
    recompute_parity_for_isolate,
    reevaluate_agreement_completion,
)
from store import db, flush_dirty, make_entity, mark, public
from validation import Shape, body_json, get_dt, get_enum, get_int, get_num, get_str

bp = Blueprint("lots", __name__, url_prefix="/protein-ops/ingredient-lots")

ANY_ROLE = constants.ROLES


@bp.route("", methods=["POST"])
def create_lot():
    _user_id, role = authenticate()
    authorize(role, ["ProcurementManager"])

    body = body_json()
    shape = Shape()
    supplier_id = get_str(body, "supplier_id", shape)
    lot_code = get_str(body, "lot_code", shape)
    quantity_kg = get_int(body, "quantity_kg", shape, minv=1)
    received_raw, received_dt = get_dt(body, "received_at", shape)
    market_index_pct = get_num(body, "market_index_pct", shape)
    moisture_pct = get_num(body, "moisture_pct", shape)
    protein_content_pct = get_num(body, "protein_content_pct", shape)

    # Tier 3: body FK existence (declared input order — supplier_id first).
    supplier = None
    if supplier_id is not None:
        supplier = db["suppliers"].get(supplier_id)
        if supplier is None:
            raise err("ERR_NOT_FOUND", "supplier not found")

    if supplier is not None:
        # Tier 9: agreement must be ACTIVE.
        if supplier["agreement_status"] != "ACTIVE":
            raise err("ERR_AGREEMENT_NOT_ACTIVE", "supplier agreement is not ACTIVE")
        # Tier 10: cumulative non-REJECTED kg (incl. arriving) <= committed * 110%.
        if quantity_kg is not None:
            cumulative = sum(
                l["quantity_kg"]
                for l in db["lots"].values()
                if l["supplier_id"] == supplier["id"] and l["qc_status"] != "REJECTED"
            )
            if (cumulative + quantity_kg) * 100 > supplier["committed_volume_kg"] * constants.OVERRECEIPT_TOLERANCE_PCT:
                raise err("ERR_VOLUME_TOLERANCE_EXCEEDED", "cumulative lot volume exceeds 110% of committed_volume_kg")

    shape.raise_if_any()

    provisional = compute_provisional_unit_cost(supplier, market_index_pct)
    lot = make_entity(
        "lots",
        {
            "supplier_id": supplier_id,
            "lot_code": lot_code,
            "quantity_kg": quantity_kg,
            "remaining_kg": quantity_kg,
            "received_at": received_raw,
            "market_index_pct": market_index_pct,
            "moisture_pct": moisture_pct,
            "protein_content_pct": protein_content_pct,
            "provisional_unit_cost_cents": provisional,
            "final_unit_cost_cents": None,
            "qc_status": "QUARANTINE",
        },
    )
    lot["_dt"]["received_at"] = received_dt
    supplier["open_lot_count"] += 1
    mark(supplier)
    flush_dirty()
    return success(public(lot), "object", 201)


@bp.route("", methods=["GET"])
def list_lots():
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    items = list(db["lots"].values())
    for param in ("supplier_id", "qc_status"):
        value = request.args.get(param)
        if value is not None:
            items = [l for l in items if l.get(param) == value]
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    page, meta = paginate([public(l) for l in items], request.args)
    return success(page, "array", 200, pagination=meta)


@bp.route("/<lid>", methods=["GET"])
def get_lot(lid):
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    lot = db["lots"].get(lid)
    if lot is None:
        raise err("ERR_NOT_FOUND", "ingredient lot not found")
    return success(public(lot), "object", 200)


@bp.route("/<lid>/qc-decision", methods=["POST"])
def qc_decision(lid):
    _user_id, role = authenticate()
    authorize(role, ["QualityManager"])

    lot = db["lots"].get(lid)
    if lot is None:
        raise err("ERR_NOT_FOUND", "ingredient lot not found")

    # Tier 5: only QUARANTINE lots can be dispositioned (any decision).
    if lot["qc_status"] != "QUARANTINE":
        raise err("ERR_INVALID_STATE", "lot qc_status is %s" % lot["qc_status"])

    body = body_json()
    shape = Shape()
    decision = get_enum(body, "decision", ["RELEASED", "REJECTED"], shape)
    invoiced = get_int(body, "invoiced_unit_cost_cents", shape, required=False)
    freight = get_int(body, "actual_freight_cents_per_kg", shape, required=False)

    supplier = db["suppliers"].get(lot["supplier_id"])

    if decision == "RELEASED":
        # Tier 9: agreement must still be ACTIVE.
        if supplier is None or supplier["agreement_status"] != "ACTIVE":
            raise err("ERR_AGREEMENT_NOT_ACTIVE", "supplier agreement is not ACTIVE")
        # Tier 11: release requires the two commercial inputs.
        if invoiced is None:
            shape.add("invoiced_unit_cost_cents", "is required for RELEASED")
        if freight is None:
            shape.add("actual_freight_cents_per_kg", "is required for RELEASED")
        shape.raise_if_any()

        lot["final_unit_cost_cents"] = compute_final_unit_cost(supplier, invoiced, freight)
        lot["qc_status"] = "RELEASED"
        mark(lot)
        supplier["delivered_volume_kg"] += lot["quantity_kg"]
        mark(supplier)
        # Release keeps the lot open (open_lot_count unchanged); completion
        # re-evaluation can therefore not fire here, but the rule is invoked.
        reevaluate_agreement_completion(supplier)
        # Recompute price parity for ACTIVE products of the matching isolate.
        recompute_parity_for_isolate(supplier["isolate_type"])
    elif decision == "REJECTED":
        lot["qc_status"] = "REJECTED"
        mark(lot)
        if supplier is not None:
            supplier["open_lot_count"] -= 1
            mark(supplier)
    else:
        shape.raise_if_any()  # invalid/missing decision
        return  # unreachable

    flush_dirty()
    return success(public(lot), "object", 200)
