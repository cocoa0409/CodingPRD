# Product domain (PRD 3.4): self-referential reformulation generations and the
# lifecycle DEVELOPMENT -> PILOT -> ACTIVE -> SUNSET -> DISCONTINUED.
from flask import Blueprint, request

import constants
from errors import err
from middleware import authenticate, authorize
from response import paginate, success
from services import compute_parity_trio
from store import db, flush_dirty, make_entity, mark, public
from validation import Shape, body_json, get_enum, get_int, get_str

bp = Blueprint("products", __name__, url_prefix="/protein-ops/products")

ANY_ROLE = constants.ROLES
PRODUCT_STATES = ["DEVELOPMENT", "PILOT", "ACTIVE", "SUNSET", "DISCONTINUED"]
LIFECYCLE_TRANSITIONS = {
    ("DEVELOPMENT", "PILOT"),
    ("PILOT", "ACTIVE"),
    ("ACTIVE", "SUNSET"),
    ("SUNSET", "DISCONTINUED"),
}


@bp.route("", methods=["POST"])
def create_product():
    _user_id, role = authenticate()
    authorize(role, ["ProductManager"])

    body = body_json()
    shape = Shape()
    product_code = get_str(body, "product_code", shape, non_empty=True)
    generation_number = get_int(body, "generation_number", shape, minv=1)
    isolate_type = get_enum(body, "isolate_type", constants.ISOLATE_TYPES, shape)
    supersedes_product_id = get_str(body, "supersedes_product_id", shape, required=False)

    # Tier 3: body FK existence (supersedes_product_id, when supplied).
    if supersedes_product_id is not None and supersedes_product_id not in db["products"]:
        raise err("ERR_NOT_FOUND", "supersedes_product_id does not reference a product")

    # Tier 8: uniqueness of product_code.
    if product_code is not None:
        for existing in db["products"].values():
            if existing["product_code"] == product_code:
                raise err("ERR_UNIQUE_CONSTRAINT", "product_code already exists")
    shape.raise_if_any()

    product = make_entity(
        "products",
        {
            "product_code": product_code,
            "generation_number": generation_number,
            "supersedes_product_id": supersedes_product_id,
            "isolate_type": isolate_type,
            "status": "DEVELOPMENT",
            "unit_cost_per_kg_cents": None,
            "price_parity_index": None,
            "parity_goal_met": None,
        },
    )
    return success(public(product), "object", 201)


@bp.route("", methods=["GET"])
def list_products():
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    items = list(db["products"].values())
    for param in ("supersedes_product_id", "status", "isolate_type"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p.get(param) == value]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, meta = paginate([public(p) for p in items], request.args)
    return success(page, "array", 200, pagination=meta)


@bp.route("/<pid>", methods=["GET"])
def get_product(pid):
    _user_id, role = authenticate()
    authorize(role, ANY_ROLE)

    product = db["products"].get(pid)
    if product is None:
        raise err("ERR_NOT_FOUND", "product not found")
    return success(public(product), "object", 200)


@bp.route("/<pid>/lifecycle-transitions", methods=["POST"])
def lifecycle_transition(pid):
    _user_id, role = authenticate()
    authorize(role, ["ProductManager"])

    product = db["products"].get(pid)
    if product is None:
        raise err("ERR_NOT_FOUND", "product not found")

    body = body_json()
    shape = Shape()
    target = get_enum(body, "target_state", PRODUCT_STATES, shape)
    if target is not None and (product["status"], target) not in LIFECYCLE_TRANSITIONS:
        raise err("ERR_INVALID_STATE", "no lifecycle transition %s -> %s" % (product["status"], target))
    shape.raise_if_any()

    if target == "ACTIVE":
        # Activation gate: at least one APPROVED label version on the product.
        has_approved = any(
            l["product_id"] == product["id"] and l["status"] == "APPROVED"
            for l in db["labels"].values()
        )
        if not has_approved:
            raise err("ERR_LABEL_NOT_APPROVED", "product has no APPROVED label version")
        # Cost-and-parity trio (null when no eligible released isolate exists).
        unit, index, goal = compute_parity_trio(product["isolate_type"])
        product["unit_cost_per_kg_cents"] = unit
        product["price_parity_index"] = index
        product["parity_goal_met"] = goal
        # Auto-sunset the superseded generation when still PILOT or ACTIVE.
        supersedes_id = product["supersedes_product_id"]
        if supersedes_id is not None:
            prior = db["products"].get(supersedes_id)
            if prior is not None and prior["status"] in ("PILOT", "ACTIVE"):
                prior["status"] = "SUNSET"
                mark(prior)

    product["status"] = target
    mark(product)
    flush_dirty()
    return success(public(product), "object", 200)
