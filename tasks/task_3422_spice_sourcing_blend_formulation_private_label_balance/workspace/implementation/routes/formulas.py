"""BlendFormula + FormulaLine routes (PRD 3.3), including the masked supplier
view (PRD 2.10) and the activate/supersede cascade."""
from flask import Blueprint, g, request

from errors import ApiError
from helpers import (ALLERGEN_PROFILES, SPICE_CODES, D, F, filter_enum,
                     invalid_state, new_entity, not_found, paged, pub,
                     require_roles, respond, touch, validate_body,
                     validation_error)
from state import DB

bp = Blueprint("formulas", __name__)

FORMULA_STATUSES = ["DRAFT", "ACTIVE", "RETIRED"]
PROPORTION_SUM_TARGET = D("100.0")
PROPORTION_SUM_EPSILON = D("0.01")
MASKED_CODE_PREFIX = "CMP-"


def _letter(n):
    """0 -> A, 1 -> B, ... 25 -> Z, 26 -> AA (creation order within a formula)."""
    s = ""
    n += 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


@bp.post("/spice/formulas")
@require_roles("FlavorScientist")
def create_formula():
    data = validate_body({
        "product_code": F("str", required=True),
        "name": F("str", required=True),
        "brand_type": F("enum", enum=["BRANDED", "PRIVATE_LABEL"], required=True),
        "target_flavor_units": F("num", required=True),
        "flavor_tolerance_pct": F("num", default=D("2.0")),
        "max_moisture_pct": F("num", default=D("10.0")),
        "supersedes_formula_id": F("str", nullable=True, default=None),
    })
    if data["target_flavor_units"] <= 0:
        validation_error("target_flavor_units must be > 0")
    sup = None
    if data["supersedes_formula_id"] is not None:
        sup = DB.formulas.get(data["supersedes_formula_id"])
        if sup is None:
            not_found("supersedes_formula_id does not resolve")
        if sup["product_code"] != data["product_code"]:
            validation_error("supersedes_formula_id references a formula with a "
                             "different product_code")
    duplicate = any(
        f["product_code"] == data["product_code"] and f["status"] in ("DRAFT", "ACTIVE")
        for f in DB.formulas.values())
    if duplicate and sup is None:
        raise ApiError("ERR_DUPLICATE_PRODUCT_CODE", 409,
                       "product_code already held by a DRAFT or ACTIVE formula")
    formula = new_entity({
        "product_code": data["product_code"],
        "name": data["name"],
        "brand_type": data["brand_type"],
        "target_flavor_units": data["target_flavor_units"],
        "flavor_tolerance_pct": data["flavor_tolerance_pct"],
        "max_moisture_pct": data["max_moisture_pct"],
        "status": "DRAFT",
        "revision": (sup["revision"] + 1) if sup else 1,
        "supersedes_formula_id": data["supersedes_formula_id"],
    })
    DB.formulas[formula["id"]] = formula
    return respond(pub(formula), 201)


@bp.get("/spice/formulas/<formula_id>")
@require_roles("FlavorScientist", "ProductionScheduler")
def get_formula(formula_id):
    formula = DB.formulas.get(formula_id)
    if formula is None:
        not_found("formula not found")
    return respond(pub(formula))


@bp.get("/spice/formulas")
@require_roles("FlavorScientist", "ProductionScheduler")
def list_formulas():
    status = filter_enum("status", FORMULA_STATUSES)
    brand_type = filter_enum("brand_type", ["BRANDED", "PRIVATE_LABEL"])
    product_code = request.args.get("product_code")
    supersedes_formula_id = request.args.get("supersedes_formula_id")
    items = []
    for f in DB.formulas.values():
        if status is not None and f["status"] != status:
            continue
        if brand_type is not None and f["brand_type"] != brand_type:
            continue
        if product_code is not None and f["product_code"] != product_code:
            continue
        if supersedes_formula_id is not None and f["supersedes_formula_id"] != supersedes_formula_id:
            continue
        items.append(f)
    data, meta = paged(items)
    return respond(data, page=meta)


@bp.post("/spice/formulas/<formula_id>/lines")
@require_roles("FlavorScientist")
def add_line(formula_id):
    data = validate_body({
        "spice_code": F("enum", enum=SPICE_CODES, required=True),
        "target_proportion_pct": F("num", required=True),
        "allergen_profile": F("enum", enum=ALLERGEN_PROFILES, required=True),
        "organic_required": F("bool", default=False),
        "min_lot_flavor_units": F("num", required=True),
    })
    if not (D(0) < data["target_proportion_pct"] <= D(100)):
        validation_error("target_proportion_pct must be > 0 and <= 100")
    if data["min_lot_flavor_units"] < 0:
        validation_error("min_lot_flavor_units must be >= 0")
    formula = DB.formulas.get(formula_id)
    if formula is None:
        not_found("formula not found")
    if formula["status"] != "DRAFT":
        invalid_state("Lines may only be added to a DRAFT formula")
    n = sum(1 for l in DB.formula_lines.values() if l["formula_id"] == formula_id)
    line = new_entity({
        "formula_id": formula_id,
        "masked_component_code": MASKED_CODE_PREFIX + _letter(n),
        "spice_code": data["spice_code"],
        "target_proportion_pct": data["target_proportion_pct"],
        "allergen_profile": data["allergen_profile"],
        "organic_required": data["organic_required"],
        "min_lot_flavor_units": data["min_lot_flavor_units"],
    })
    DB.formula_lines[line["id"]] = line
    return respond(pub(line), 201)


@bp.get("/spice/formulas/<formula_id>/lines")
@require_roles("FlavorScientist", "SupplierRep")
def list_lines(formula_id):
    formula = DB.formulas.get(formula_id)
    if formula is None:
        not_found("formula not found")
    lines = [l for l in DB.formula_lines.values() if l["formula_id"] == formula_id]
    items, meta = paged(lines)
    if g.user_role == "SupplierRep":
        # Masked view (PRD 2.10): true spice code and proportion are hidden.
        for it in items:
            it["spice_code"] = None
            it["target_proportion_pct"] = None
    return respond(items, page=meta)


@bp.post("/spice/formulas/<formula_id>/activate")
@require_roles("FlavorScientist")
def activate_formula(formula_id):
    formula = DB.formulas.get(formula_id)
    if formula is None:
        not_found("formula not found")
    if formula["status"] != "DRAFT":
        invalid_state("Only a DRAFT formula can be activated")
    total = sum((l["target_proportion_pct"] for l in DB.formula_lines.values()
                 if l["formula_id"] == formula_id), D(0))
    if abs(total - PROPORTION_SUM_TARGET) > PROPORTION_SUM_EPSILON:
        raise ApiError("ERR_PROPORTION_SUM_INVALID", 422,
                       "Line proportions sum to %s, not within 0.01 of 100.0" % total)
    formula["status"] = "ACTIVE"
    touch(formula)
    # Supersede cascade: every OTHER ACTIVE formula with the same product_code retires.
    for other in DB.formulas.values():
        if (other["id"] != formula_id
                and other["product_code"] == formula["product_code"]
                and other["status"] == "ACTIVE"):
            other["status"] = "RETIRED"
            touch(other)
    return respond(pub(formula))
