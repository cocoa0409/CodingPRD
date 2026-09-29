"""Cost models and cost change requests."""
from flask import Blueprint

import calculations as calc
import serializers as ser
from db import db, now
from domain import (
    claims_of_round,
    cost_models_of_item,
    get_change_request,
    get_cost_model,
    get_item,
    get_supplier,
    guard_program_open,
    new_row,
    program_of_item,
    refresh_landed_costs,
    specifications_of_item,
    touch,
)
from errors import fail
from listing import (
    CHANGE_STATUS_SET,
    COST_MODEL_STATUS_SET,
    ESCALATION_SET,
    SUBSTITUTION_SCOPE_SET,
    no_query,
    paginate,
)
from middleware import (
    ALL_ROLES,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_SOURCING_MANAGER,
    ROLE_SUPPLIER_USER,
    Field,
    authenticate,
    validate_body,
)
from response import object_response


bp = Blueprint("costs", __name__)


def _non_negative(required=False):
    return Field("integer", required=required, check=lambda v: v >= 0, detail="must not be negative")


@bp.post("/private-label/cost-models")
def create_cost_model():
    user_id, role = authenticate((ROLE_SUPPLIER_USER, ROLE_SOURCING_MANAGER))
    body = validate_body(
        {
            "item_id": Field("string", required=True),
            "supplier_id": Field("string", required=True),
            "ingredient_cost_cents_per_unit": _non_negative(True),
            "packaging_cost_cents_per_unit": _non_negative(True),
            "conversion_cost_cents_per_unit": _non_negative(True),
            "quoted_yield_pct": Field(
                "number",
                required=True,
                check=lambda v: 0.0 < v <= 100.0,
                detail="must be strictly greater than 0.0 and no more than 100.0",
            ),
            "freight_cents_per_pallet": _non_negative(True),
            "units_per_pallet": Field(
                "integer", required=True, check=lambda v: v > 0, detail="must be strictly greater than zero"
            ),
            "moq_units": Field(
                "integer", required=True, check=lambda v: v > 0, detail="must be strictly greater than zero"
            ),
            "tooling_cents": _non_negative(True),
        }
    )
    item = get_item(body["item_id"])
    supplier = get_supplier(body["supplier_id"])
    if role == ROLE_SUPPLIER_USER and user_id != supplier["id"]:
        fail("ERR_SUPPLIER_SCOPE_VIOLATION", "A SupplierUser may quote only for its own supplier.")
    guard_program_open(program_of_item(item))
    base = (
        body["ingredient_cost_cents_per_unit"]
        + body["packaging_cost_cents_per_unit"]
        + body["conversion_cost_cents_per_unit"]
    )
    row = new_row(
        {
            "item_id": item["id"],
            "supplier_id": supplier["id"],
            "ingredient_cost_cents_per_unit": body["ingredient_cost_cents_per_unit"],
            "packaging_cost_cents_per_unit": body["packaging_cost_cents_per_unit"],
            "conversion_cost_cents_per_unit": body["conversion_cost_cents_per_unit"],
            "effective_base_cents": base,
            "quoted_yield_pct": body["quoted_yield_pct"],
            "freight_cents_per_pallet": body["freight_cents_per_pallet"],
            "units_per_pallet": body["units_per_pallet"],
            "moq_units": body["moq_units"],
            "tooling_cents": body["tooling_cents"],
            "landed_unit_cost_cents_as_quoted": None,
            "landed_unit_cost_cents_audited": None,
            "open_change_request_count": 0,
            "status": "SUBMITTED",
        }
    )
    refresh_landed_costs(row)
    db.cost_models[row["id"]] = row
    return object_response(ser.cost_model_out(row), 201)


@bp.get("/private-label/cost-models/<cost_model_id>")
def read_cost_model(cost_model_id):
    authenticate(ALL_ROLES)
    no_query()
    return object_response(ser.cost_model_out(get_cost_model(cost_model_id)))


@bp.get("/private-label/cost-models")
def list_cost_models():
    authenticate(ALL_ROLES)
    return paginate(
        db.cost_models,
        {"item_id": "string", "supplier_id": "string", "status": COST_MODEL_STATUS_SET},
        ser.cost_model_out,
    )


@bp.post("/private-label/cost-models/<cost_model_id>/decision")
def cost_model_decision(cost_model_id):
    authenticate((ROLE_SOURCING_MANAGER, ROLE_PROGRAM_DIRECTOR))
    body = validate_body(
        {"decision": Field("string", required=True, enum=frozenset(("ACCEPT", "REJECT")))}
    )
    cost_model = get_cost_model(cost_model_id)
    item = get_item(cost_model["item_id"])
    guard_program_open(program_of_item(item))
    if cost_model["status"] != "SUBMITTED":
        fail("ERR_COST_MODEL_NOT_SUBMITTED")
    if body["decision"] == "REJECT":
        cost_model["status"] = "REJECTED"
        touch(cost_model)
        return object_response(ser.cost_model_out(cost_model))
    if item["development_status"] != "CONCEPT":
        fail("ERR_ITEM_STATE_INVALID")
    supplier = get_supplier(cost_model["supplier_id"])
    if supplier["qualification_status"] not in ("QUALIFIED", "CONDITIONAL"):
        fail("ERR_SUPPLIER_STATE_INVALID")
    cost_model["status"] = "ACCEPTED"
    touch(cost_model)
    for sibling in cost_models_of_item(item["id"]):
        if sibling["id"] != cost_model["id"] and sibling["status"] == "SUBMITTED":
            sibling["status"] = "SUPERSEDED"
            touch(sibling)
    item["supplier_id"] = supplier["id"]
    item["development_status"] = "SOURCED"
    touch(item)
    return object_response(ser.cost_model_out(cost_model))


# --------------------------------------------------------------------------
# cost change requests
# --------------------------------------------------------------------------
def _settle(row, cost_model):
    outputs = calc.cost_change_settlement(
        cost_model["effective_base_cents"],
        row["requested_ingredient_cost_cents_per_unit"],
        row["requested_packaging_cost_cents_per_unit"],
        row["requested_conversion_cost_cents_per_unit"],
    )
    row.update(outputs)


def _scope_guard(user_id, role, supplier_id):
    if role == ROLE_SUPPLIER_USER and user_id != supplier_id:
        fail("ERR_SUPPLIER_SCOPE_VIOLATION", "A SupplierUser may act only on its own supplier's records.")


@bp.post("/private-label/cost-change-requests")
def create_change_request():
    user_id, role = authenticate((ROLE_SUPPLIER_USER,))
    body = validate_body(
        {
            "item_id": Field("string", required=True),
            "cost_model_id": Field("string", required=True),
            "requested_ingredient_cost_cents_per_unit": _non_negative(True),
            "requested_packaging_cost_cents_per_unit": _non_negative(True),
            "requested_conversion_cost_cents_per_unit": _non_negative(True),
            "substitution_scope": Field("string", required=True, enum=SUBSTITUTION_SCOPE_SET),
            "substitution_material_desc": Field("string"),
            "expected_cost_model_version": Field("integer", required=True),
        }
    )
    item = get_item(body["item_id"])
    cost_model = get_cost_model(body["cost_model_id"])
    _scope_guard(user_id, role, cost_model["supplier_id"])
    if body["expected_cost_model_version"] != cost_model["version"]:
        fail("ERR_STALE_COST_MODEL_VERSION")
    guard_program_open(program_of_item(item))
    if cost_model["status"] != "ACCEPTED" or cost_model["item_id"] != item["id"]:
        fail("ERR_COST_MODEL_NOT_ACCEPTED")
    if cost_model["open_change_request_count"] != 0:
        fail("ERR_OPEN_CHANGE_REQUEST_EXISTS")
    desc = body.get("substitution_material_desc")
    if body["substitution_scope"] != "NONE" and not desc:
        fail("ERR_SUBSTITUTION_DESC_REQUIRED")
    row = new_row(
        {
            "item_id": item["id"],
            "cost_model_id": cost_model["id"],
            "requested_ingredient_cost_cents_per_unit": body["requested_ingredient_cost_cents_per_unit"],
            "requested_packaging_cost_cents_per_unit": body["requested_packaging_cost_cents_per_unit"],
            "requested_conversion_cost_cents_per_unit": body["requested_conversion_cost_cents_per_unit"],
            "substitution_scope": body["substitution_scope"],
            "substitution_material_desc": desc if desc is not None else None,
            "counter_base_cents": None,
            "round_number": 1,
            "decided_by_user_id": None,
            "status": "SUBMITTED",
        }
    )
    _settle(row, cost_model)
    db.cost_change_requests[row["id"]] = row
    cost_model["open_change_request_count"] += 1
    touch(cost_model)
    return object_response(ser.change_request_out(row), 201)


@bp.get("/private-label/cost-change-requests/<cost_change_request_id>")
def read_change_request(cost_change_request_id):
    authenticate(ALL_ROLES)
    no_query()
    return object_response(ser.change_request_out(get_change_request(cost_change_request_id)))


@bp.get("/private-label/cost-change-requests")
def list_change_requests():
    authenticate(ALL_ROLES)
    return paginate(
        db.cost_change_requests,
        {
            "item_id": "string",
            "cost_model_id": "string",
            "escalation_tier": ESCALATION_SET,
            "substitution_scope": SUBSTITUTION_SCOPE_SET,
            "status": CHANGE_STATUS_SET,
        },
        ser.change_request_out,
    )


@bp.post("/private-label/cost-change-requests/<cost_change_request_id>/counter")
def counter_change_request(cost_change_request_id):
    authenticate((ROLE_SOURCING_MANAGER, ROLE_PROGRAM_DIRECTOR))
    body = validate_body({"counter_base_cents": _non_negative(True)})
    row = get_change_request(cost_change_request_id)
    guard_program_open(program_of_item(get_item(row["item_id"])))
    if row["status"] != "SUBMITTED":
        fail("ERR_CHANGE_REQUEST_STATE_INVALID")
    row["counter_base_cents"] = body["counter_base_cents"]
    row["status"] = "COUNTERED"
    touch(row)
    return object_response(ser.change_request_out(row))


@bp.post("/private-label/cost-change-requests/<cost_change_request_id>/revise")
def revise_change_request(cost_change_request_id):
    user_id, role = authenticate((ROLE_SUPPLIER_USER,))
    body = validate_body(
        {
            "requested_ingredient_cost_cents_per_unit": _non_negative(True),
            "requested_packaging_cost_cents_per_unit": _non_negative(True),
            "requested_conversion_cost_cents_per_unit": _non_negative(True),
            "substitution_scope": Field("string", enum=SUBSTITUTION_SCOPE_SET),
            "substitution_material_desc": Field("string"),
        }
    )
    row = get_change_request(cost_change_request_id)
    cost_model = get_cost_model(row["cost_model_id"])
    _scope_guard(user_id, role, cost_model["supplier_id"])
    guard_program_open(program_of_item(get_item(row["item_id"])))
    if row["status"] != "COUNTERED":
        fail("ERR_CHANGE_REQUEST_STATE_INVALID")
    supplied = body["_supplied"]
    scope = body["substitution_scope"] if "substitution_scope" in supplied else row["substitution_scope"]
    desc = (
        body["substitution_material_desc"]
        if "substitution_material_desc" in supplied
        else row["substitution_material_desc"]
    )
    if scope != "NONE" and not desc:
        fail("ERR_SUBSTITUTION_DESC_REQUIRED")
    if row["round_number"] >= calc.MAX_NEGOTIATION_ROUNDS:
        fail("ERR_NEGOTIATION_ROUND_LIMIT")
    row["requested_ingredient_cost_cents_per_unit"] = body["requested_ingredient_cost_cents_per_unit"]
    row["requested_packaging_cost_cents_per_unit"] = body["requested_packaging_cost_cents_per_unit"]
    row["requested_conversion_cost_cents_per_unit"] = body["requested_conversion_cost_cents_per_unit"]
    row["substitution_scope"] = scope
    row["substitution_material_desc"] = desc
    row["round_number"] += 1
    row["status"] = "SUBMITTED"
    _settle(row, cost_model)
    touch(row)
    return object_response(ser.change_request_out(row))


@bp.post("/private-label/cost-change-requests/<cost_change_request_id>/withdraw")
def withdraw_change_request(cost_change_request_id):
    user_id, role = authenticate((ROLE_SUPPLIER_USER,))
    validate_body({})
    row = get_change_request(cost_change_request_id)
    cost_model = get_cost_model(row["cost_model_id"])
    _scope_guard(user_id, role, cost_model["supplier_id"])
    guard_program_open(program_of_item(get_item(row["item_id"])))
    if row["status"] not in ("SUBMITTED", "COUNTERED"):
        fail("ERR_CHANGE_REQUEST_STATE_INVALID")
    row["status"] = "WITHDRAWN"
    touch(row)
    cost_model["open_change_request_count"] -= 1
    touch(cost_model)
    return object_response(ser.change_request_out(row))


def _accept_cascade(row, cost_model, item):
    """Five conditional hops (PRD 3.9)."""
    # hop one: the cost model's base moves and both landed variants are redone
    cost_model["effective_base_cents"] += row["net_increase_cents"]
    refresh_landed_costs(cost_model)
    touch(cost_model)
    # hop two: the locked specification pinning this cost model is superseded
    specs = [
        spec
        for spec in specifications_of_item(item["id"])
        if spec["status"] == "LOCKED" and spec["pinned_cost_model_id"] == cost_model["id"]
    ]
    if not specs:
        return
    spec = specs[0]
    spec["status"] = "SUPERSEDE_PENDING"
    touch(spec)
    # hop three: an INGREDIENT substitution invalidates the pinned panel
    if row["substitution_scope"] != "INGREDIENT":
        return
    artwork_round = db.artwork_rounds.get(spec["pinned_artwork_round_id"])
    if artwork_round is None or artwork_round["nutrition_status"] != "VALID":
        return
    artwork_round["nutrition_status"] = "INVALIDATED"
    touch(artwork_round)
    # hop four: nutrition-dependent approved claims on that round are rescinded
    rescinded = 0
    for claim in claims_of_round(artwork_round["id"]):
        if claim["status"] == "APPROVED" and claim["depends_on_nutrition"]:
            claim["status"] = "RESCINDED"
            touch(claim)
            rescinded += 1
    if rescinded == 0:
        return
    # hop five: a launched item falls back to relaunch pending
    if item["development_status"] == "LAUNCHED":
        item["development_status"] = "RELAUNCH_PENDING"
        touch(item)


@bp.post("/private-label/cost-change-requests/<cost_change_request_id>/decision")
def decide_change_request(cost_change_request_id):
    user_id, role = authenticate((ROLE_SOURCING_MANAGER, ROLE_PROGRAM_DIRECTOR))
    body = validate_body(
        {"decision": Field("string", required=True, enum=frozenset(("ACCEPT", "REJECT")))}
    )
    row = get_change_request(cost_change_request_id)
    cost_model = get_cost_model(row["cost_model_id"])
    item = get_item(row["item_id"])
    guard_program_open(program_of_item(item))
    if row["status"] != "SUBMITTED":
        fail("ERR_CHANGE_REQUEST_STATE_INVALID")
    if row["escalation_tier"] != "T1" and role != ROLE_PROGRAM_DIRECTOR:
        fail("ERR_ESCALATION_ROLE_INSUFFICIENT")
    row["decided_by_user_id"] = user_id
    cost_model["open_change_request_count"] -= 1
    if body["decision"] == "REJECT":
        row["status"] = "REJECTED"
        touch(row)
        touch(cost_model)
        return object_response(ser.change_request_out(row))
    row["status"] = "ACCEPTED"
    touch(row)
    _accept_cascade(row, cost_model, item)
    return object_response(ser.change_request_out(row))
