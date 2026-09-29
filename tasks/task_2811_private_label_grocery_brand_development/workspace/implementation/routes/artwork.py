"""Artwork rounds, the printed nutrition panel and label claims."""
from flask import Blueprint

import calculations as calc
import serializers as ser
from db import db
from domain import (
    claims_of_round,
    get_artwork_round,
    get_claim,
    get_item,
    guard_program_open,
    new_row,
    program_of_item,
    rounds_of_item,
    touch,
)
from errors import fail
from listing import (
    ARTWORK_STATUS_SET,
    CLAIM_STATUS_SET,
    CLAIM_TYPE_SET,
    NUTRITION_STATUS_SET,
    no_query,
    paginate,
)
from middleware import (
    ALL_ROLES,
    ROLE_PACKAGING_DESIGNER,
    ROLE_REGULATORY_REVIEWER,
    Field,
    authenticate,
    validate_body,
)
from response import object_response


bp = Blueprint("artwork", __name__)

DECLARED_FIELDS = (
    "declared_calories",
    "declared_fat_g",
    "declared_satfat_g",
    "declared_carb_g",
    "declared_fiber_g",
    "declared_sugars_g",
    "declared_added_sugars_g",
    "declared_protein_g",
    "declared_sodium_mg",
)
DESIGNABLE = ("DRAFT", "CHANGES_REQUESTED")


def _positive_serving(required):
    return Field(
        "number",
        required=required,
        check=lambda v: v > 0.0,
        detail="must be strictly greater than 0.0",
    )


def _nutrient(required):
    return Field(
        "number", required=required, check=lambda v: v >= 0.0, detail="must not be negative"
    )


def _panel_schema(required):
    schema = {
        "serving_size_g": _positive_serving(required),
        "servings_per_container": _positive_serving(required),
    }
    for name in calc.NUTRIENT_INPUTS:
        schema[name] = _nutrient(required)
    return schema


@bp.post("/private-label/artwork-rounds")
def create_artwork_round():
    user_id, _role = authenticate((ROLE_PACKAGING_DESIGNER,))
    schema = {"item_id": Field("string", required=True)}
    schema.update(_panel_schema(True))
    body = validate_body(schema)
    item = get_item(body["item_id"])
    guard_program_open(program_of_item(item))
    row = new_row(
        {
            "item_id": item["id"],
            "round_number": len(rounds_of_item(item["id"])) + 1,
            "designer_user_id": user_id,
            "reviewer_user_id": None,
            "nutrition_status": "NOT_GENERATED",
            "status": "DRAFT",
        }
    )
    row["serving_size_g"] = body["serving_size_g"]
    row["servings_per_container"] = body["servings_per_container"]
    for name in calc.NUTRIENT_INPUTS:
        row[name] = body[name]
    for name in DECLARED_FIELDS:
        row[name] = None
    db.artwork_rounds[row["id"]] = row
    return object_response(ser.artwork_round_out(row), 201)


@bp.get("/private-label/artwork-rounds/<artwork_round_id>")
def read_artwork_round(artwork_round_id):
    authenticate(ALL_ROLES)
    no_query()
    return object_response(ser.artwork_round_out(get_artwork_round(artwork_round_id)))


@bp.get("/private-label/artwork-rounds")
def list_artwork_rounds():
    authenticate(ALL_ROLES)
    return paginate(
        db.artwork_rounds,
        {
            "item_id": "string",
            "status": ARTWORK_STATUS_SET,
            "nutrition_status": NUTRITION_STATUS_SET,
        },
        ser.artwork_round_out,
    )


@bp.post("/private-label/artwork-rounds/<artwork_round_id>/nutrition-panel")
def generate_panel(artwork_round_id):
    authenticate((ROLE_PACKAGING_DESIGNER,))
    body = validate_body(_panel_schema(False))
    row = get_artwork_round(artwork_round_id)
    guard_program_open(program_of_item(get_item(row["item_id"])))
    if row["status"] not in DESIGNABLE:
        fail("ERR_ARTWORK_STATE_INVALID")
    for name in ("serving_size_g", "servings_per_container") + calc.NUTRIENT_INPUTS:
        if name in body["_supplied"]:
            row[name] = body[name]
    row.update(calc.nutrition_panel(row))
    row["nutrition_status"] = "VALID"
    touch(row)
    return object_response(ser.artwork_round_out(row))


@bp.post("/private-label/artwork-rounds/<artwork_round_id>/submit")
def submit_artwork_round(artwork_round_id):
    authenticate((ROLE_PACKAGING_DESIGNER,))
    validate_body({})
    row = get_artwork_round(artwork_round_id)
    guard_program_open(program_of_item(get_item(row["item_id"])))
    if row["status"] not in DESIGNABLE:
        fail("ERR_ARTWORK_STATE_INVALID")
    if row["nutrition_status"] != "VALID":
        fail("ERR_NUTRITION_PANEL_INVALID")
    if not claims_of_round(row["id"]):
        fail("ERR_UNAPPROVED_CLAIM_PRESENT", "A round must carry at least one label claim.")
    row["status"] = "IN_REVIEW"
    touch(row)
    return object_response(ser.artwork_round_out(row))


@bp.post("/private-label/artwork-rounds/<artwork_round_id>/review")
def review_artwork_round(artwork_round_id):
    user_id, _role = authenticate((ROLE_REGULATORY_REVIEWER,))
    body = validate_body(
        {
            "decision": Field(
                "string", required=True, enum=frozenset(("APPROVE", "REQUEST_CHANGES"))
            )
        }
    )
    row = get_artwork_round(artwork_round_id)
    item = get_item(row["item_id"])
    guard_program_open(program_of_item(item))
    if row["status"] != "IN_REVIEW":
        fail("ERR_ARTWORK_STATE_INVALID")
    if body["decision"] == "REQUEST_CHANGES":
        row["status"] = "CHANGES_REQUESTED"
        row["reviewer_user_id"] = user_id
        touch(row)
        return object_response(ser.artwork_round_out(row))
    if row["nutrition_status"] != "VALID":
        fail("ERR_NUTRITION_PANEL_INVALID")
    claims = claims_of_round(row["id"])
    if not claims or any(claim["status"] != "APPROVED" for claim in claims):
        fail("ERR_UNAPPROVED_CLAIM_PRESENT")
    if item["development_status"] != "BENCHMARKED":
        fail("ERR_ITEM_STATE_INVALID")
    row["status"] = "APPROVED"
    row["reviewer_user_id"] = user_id
    touch(row)
    for sibling in rounds_of_item(item["id"]):
        if sibling["id"] != row["id"] and sibling["status"] == "APPROVED":
            sibling["status"] = "SUPERSEDED"
            touch(sibling)
    item["development_status"] = "PACKAGING_APPROVED"
    touch(item)
    return object_response(ser.artwork_round_out(row))


# --------------------------------------------------------------------------
# label claims
# --------------------------------------------------------------------------
NUTRITION_DEPENDENT = frozenset(("NUTRIENT_CONTENT", "HEALTH"))
SUBSTANTIATION_REQUIRED = frozenset(("HEALTH", "ORGANIC"))


@bp.post("/private-label/label-claims")
def create_claim():
    user_id, _role = authenticate((ROLE_PACKAGING_DESIGNER, ROLE_REGULATORY_REVIEWER))
    body = validate_body(
        {
            "artwork_round_id": Field("string", required=True),
            "claim_text": Field("string", required=True),
            "claim_type": Field("string", required=True, enum=CLAIM_TYPE_SET),
            "substantiation_ref": Field("string"),
        }
    )
    artwork_round = get_artwork_round(body["artwork_round_id"])
    guard_program_open(program_of_item(get_item(artwork_round["item_id"])))
    if artwork_round["status"] not in DESIGNABLE:
        fail("ERR_ARTWORK_STATE_INVALID")
    reference = body.get("substantiation_ref")
    if body["claim_type"] in SUBSTANTIATION_REQUIRED and not reference:
        fail("ERR_SUBSTANTIATION_REQUIRED")
    row = new_row(
        {
            "artwork_round_id": artwork_round["id"],
            "claim_text": body["claim_text"],
            "claim_type": body["claim_type"],
            "substantiation_ref": reference if reference is not None else None,
            "depends_on_nutrition": body["claim_type"] in NUTRITION_DEPENDENT,
            "submitted_by_user_id": user_id,
            "reviewed_by_user_id": None,
            "rationale": None,
            "status": "PENDING",
        }
    )
    db.label_claims[row["id"]] = row
    return object_response(ser.label_claim_out(row), 201)


@bp.get("/private-label/label-claims/<label_claim_id>")
def read_claim(label_claim_id):
    authenticate(ALL_ROLES)
    no_query()
    return object_response(ser.label_claim_out(get_claim(label_claim_id)))


@bp.get("/private-label/label-claims")
def list_claims():
    authenticate(ALL_ROLES)
    return paginate(
        db.label_claims,
        {"artwork_round_id": "string", "claim_type": CLAIM_TYPE_SET, "status": CLAIM_STATUS_SET},
        ser.label_claim_out,
    )


@bp.post("/private-label/label-claims/<label_claim_id>/review")
def review_claim(label_claim_id):
    user_id, _role = authenticate((ROLE_REGULATORY_REVIEWER,))
    body = validate_body(
        {
            "decision": Field("string", required=True, enum=frozenset(("APPROVE", "REJECT"))),
            "rationale": Field("string"),
        }
    )
    row = get_claim(label_claim_id)
    artwork_round = get_artwork_round(row["artwork_round_id"])
    if row["submitted_by_user_id"] == user_id:
        fail("ERR_CLAIM_SELF_REVIEW", "A claim may not be reviewed by the user who drafted it.")
    guard_program_open(program_of_item(get_item(artwork_round["item_id"])))
    if row["status"] != "PENDING":
        fail("ERR_CLAIM_NOT_PENDING")
    if body["decision"] == "APPROVE" and artwork_round["status"] not in (
        "DRAFT",
        "IN_REVIEW",
        "CHANGES_REQUESTED",
    ):
        fail("ERR_ARTWORK_STATE_INVALID")
    row["status"] = "APPROVED" if body["decision"] == "APPROVE" else "REJECTED"
    row["reviewed_by_user_id"] = user_id
    if "rationale" in body["_supplied"]:
        row["rationale"] = body["rationale"]
    touch(row)
    return object_response(ser.label_claim_out(row))
