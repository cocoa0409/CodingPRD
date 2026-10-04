# LabelVersion domain (PRD 3.4): drafts nested under a product, the claim
# gates at SUBMITTED, and the OCC-guarded APPROVED transition that supersedes
# the prior approved label and bumps product.version.
from decimal import Decimal

from flask import Blueprint, request

import clock
import constants
from errors import err
from middleware import authenticate, authorize
from response import paginate, success
from store import db, flush_dirty, make_entity, mark, public
from validation import Shape, body_json, get_enum, get_int, get_list, get_num, get_str

bp = Blueprint("labels", __name__, url_prefix="/protein-ops")
bp_nested = Blueprint("labels_nested", __name__, url_prefix="/protein-ops/products")

ANY_ROLE = constants.ROLES
LABEL_STATES = ["DRAFT", "SUBMITTED", "APPROVED", "SUPERSEDED"]
LABEL_TRANSITIONS = {
    ("DRAFT", "SUBMITTED"),
    ("SUBMITTED", "DRAFT"),
    ("SUBMITTED", "APPROVED"),
}


@bp_nested.route("/<product_id>/label-versions", methods=["POST"])
def create_label(product_id):
    _user_id, role = authenticate()
    authorize(role, ["ProductManager"])

    # Tier 3: nested path identifier resolves first (PRD 2.9).
    product = db["products"].get(product_id)
    if product is None:
        raise err("ERR_NOT_FOUND", "product not found")

    # Tier 5: label work happens while the product is DEVELOPMENT/PILOT/ACTIVE.
    if product["status"] not in ("DEVELOPMENT", "PILOT", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "product status %s does not admit label drafts" % product["status"])

    body = body_json()
    shape = Shape()
    version_number = get_int(body, "version_number", shape)
    protein_g = get_num(body, "protein_g", shape)
    fat_g = get_num(body, "fat_g", shape)
    sodium_mg = get_num(body, "sodium_mg", shape)
    claims = get_list(body, "claims", shape, item_choices=constants.CLAIM_TYPES)
    ingredient_statement = get_str(body, "ingredient_statement", shape, non_empty=True)

    # Tier 8: (product_id, version_number) unique within the product.
    if version_number is not None:
        for existing in db["labels"].values():
            if existing["product_id"] == product_id and existing["version_number"] == version_number:
                raise err("ERR_UNIQUE_CONSTRAINT", "(product_id, version_number) already exists")
    shape.raise_if_any()

    label = make_entity(
        "labels",
        {
            "product_id": product_id,
            "version_number": version_number,
            "protein_g": protein_g,
            "fat_g": fat_g,
            "sodium_mg": sodium_mg,
            "claims": claims,
            "ingredient_statement": ingredient_statement,
            "status": "DRAFT",
        },
    )
    return success(public(label), "object", 201)


@bp.route("/label-versions", methods=["GET"])
def list_labels():
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    items = list(db["labels"].values())
    for param in ("product_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [l for l in items if l.get(param) == value]
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    page, meta = paginate([public(l) for l in items], request.args)
    return success(page, "array", 200, pagination=meta)


@bp.route("/label-versions/<lid>", methods=["GET"])
def get_label(lid):
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    label = db["labels"].get(lid)
    if label is None:
        raise err("ERR_NOT_FOUND", "label version not found")
    return success(public(label), "object", 200)


@bp.route("/label-versions/<lid>/transitions", methods=["POST"])
def label_transition(lid):
    _user_id, role = authenticate()
    authorize(role, ["ProductManager"])

    label = db["labels"].get(lid)
    if label is None:
        raise err("ERR_NOT_FOUND", "label version not found")
    product = db["products"][label["product_id"]]

    body = body_json()
    shape = Shape()
    target = get_enum(body, "target_status", LABEL_STATES, shape)
    expected_product_version = get_int(body, "expected_product_version", shape, required=False)

    # Tier 4 OCC (PRD 2.7): only when target is APPROVED and the field is
    # supplied — a mismatch is stale regardless of the label's own state.
    if target == "APPROVED" and expected_product_version is not None:
        if expected_product_version != product["version"]:
            raise err("ERR_STALE_PRODUCT_VERSION", "expected_product_version does not match product version")

    # Tier 5: the requested transition must exist from the current state.
    if target is not None and (label["status"], target) not in LABEL_TRANSITIONS:
        raise err("ERR_INVALID_STATE", "no label transition %s -> %s" % (label["status"], target))

    # Tier 6 compliance: claim gates on SUBMITTED (DRAFT -> SUBMITTED).
    if target == "SUBMITTED":
        claims = label["claims"] or []
        if "HIGH_PROTEIN" in claims and not (Decimal(str(label["protein_g"])) >= Decimal(constants.CLAIM_HIGH_PROTEIN_MIN_PROTEIN_G)):
            raise err("ERR_LABEL_CLAIM_UNSUPPORTED", "HIGH_PROTEIN requires protein_g >= 20")
        if "LOW_SATURATED_FAT" in claims and not (Decimal(str(label["fat_g"])) <= Decimal(constants.CLAIM_LOW_SAT_FAT_MAX_FAT_G)):
            raise err("ERR_LABEL_CLAIM_UNSUPPORTED", "LOW_SATURATED_FAT requires fat_g <= 3")

    # Tier 11: APPROVED requires expected_product_version; SUBMITTED requires a
    # non-empty ingredient statement.
    if target == "APPROVED" and expected_product_version is None:
        shape.add("expected_product_version", "is required when target_status is APPROVED")
    if target == "SUBMITTED" and not label["ingredient_statement"]:
        shape.add("ingredient_statement", "must be non-empty")
    shape.raise_if_any()

    if target == "APPROVED":
        # Supersede the previously APPROVED sibling(s); advance product.version.
        for sibling in db["labels"].values():
            if sibling["product_id"] == product["id"] and sibling["status"] == "APPROVED" and sibling["id"] != label["id"]:
                sibling["status"] = "SUPERSEDED"
                mark(sibling)
        product["version"] += 1  # OCC advance — exactly +1
        product["updated_at"] = clock.now_ms()
    label["status"] = target
    mark(label)
    flush_dirty()
    return success(public(label), "object", 200)
