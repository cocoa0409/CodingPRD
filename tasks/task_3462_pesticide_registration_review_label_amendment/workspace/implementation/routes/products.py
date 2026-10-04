"""Products: shell creation, catalogue reads, reinstatement, sub-resources."""
from flask import Blueprint, request

import constants
from auth import require_auth, require_role
from db import new_row, store, touch
from envelope import ok, ok_list
from errors import err
from validate import as_enum, as_str, paginate, parse_body, reject_unknown

bp = Blueprint("products", __name__)


def get_product_or_404(product_id):
    product = store["products"].get(product_id)
    if product is None:
        err("ERR_PRODUCT_NOT_FOUND", "Product %s does not exist." % product_id)
    return product


@bp.post("/products")
def create_product():
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRANT_REPRESENTATIVE])
    data = parse_body()
    reject_unknown(data, ["product_name", "active_ingredient_id", "formulation_type"])
    product_name = as_str(data, "product_name", required=True)
    active_ingredient_id = as_str(data, "active_ingredient_id", required=True)
    formulation_type = as_enum(
        data, "formulation_type", constants.FORMULATION_TYPES, required=True
    )

    if active_ingredient_id not in store["active_ingredients"]:
        err("ERR_NOT_FOUND", "Active ingredient %s does not exist." % active_ingredient_id)

    row = new_row()
    row.update(
        {
            "product_name": product_name,
            "active_ingredient_id": active_ingredient_id,
            "registrant_ref": caller["user_id"],
            "formulation_type": formulation_type,
            "classification": "GENERAL_USE",
            "status": "UNREGISTERED",
            "signal_word": None,
            "epa_registration_number": None,
        }
    )
    store["products"][row["id"]] = row
    return ok(row, status=201)


@bp.get("/products")
def list_products():
    require_auth()
    rows = list(store["products"].values())
    for key in ("active_ingredient_id", "registrant_ref", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.get("/products/<product_id>")
def get_product(product_id):
    require_auth()
    return ok(get_product_or_404(product_id))


@bp.post("/products/<product_id>/reinstate")
def reinstate_product(product_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRATION_REVIEWER])
    data = parse_body()
    reject_unknown(data, [])
    product = get_product_or_404(product_id)

    if product["status"] != "SUSPENDED":
        err("ERR_PRODUCT_NOT_SUSPENDED", "Product is not SUSPENDED.")

    for proc in product_rows_of("proceedings", product["id"]):
        if proc["status"] == "EFFECTIVE":
            err(
                "ERR_REINSTATEMENT_BLOCKED",
                "An EFFECTIVE proceeding of the product blocks reinstatement.",
            )
    case_ids = {c["id"] for c in product_rows_of("review_cases", product["id"])}
    for dci in store["dcis"].values():
        if dci["review_case_id"] in case_ids and dci["status"] in (
            "ISSUED",
            "RESPONDED",
            "DEFICIENT",
            "DELINQUENT",
        ):
            err(
                "ERR_REINSTATEMENT_BLOCKED",
                "An outstanding or delinquent data call-in blocks reinstatement.",
            )

    open_cases = [
        c
        for c in product_rows_of("review_cases", product["id"])
        if c["status"] in ("OPEN", "DCI_PENDING", "UNDER_REVIEW")
    ]
    product["status"] = "UNDER_REVIEW" if open_cases else "REGISTERED"
    touch(product)
    return ok(product)


def product_rows_of(collection, product_id):
    return [r for r in store[collection].values() if r.get("product_id") == product_id]


def _sub_list(product_id, collection, filter_keys):
    require_auth()
    get_product_or_404(product_id)
    rows = product_rows_of(collection, product_id)
    for key in filter_keys:
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.get("/products/<product_id>/use-sites")
def list_product_use_sites(product_id):
    return _sub_list(product_id, "use_sites", ["status"])


@bp.get("/products/<product_id>/tolerances")
def list_product_tolerances(product_id):
    return _sub_list(product_id, "tolerances", ["status"])


@bp.get("/products/<product_id>/endangered-species-bulletins")
def list_product_bulletins(product_id):
    return _sub_list(product_id, "bulletins", ["county_fips", "status"])


@bp.get("/products/<product_id>/registration-review-cases")
def list_product_review_cases(product_id):
    return _sub_list(product_id, "review_cases", ["status"])
