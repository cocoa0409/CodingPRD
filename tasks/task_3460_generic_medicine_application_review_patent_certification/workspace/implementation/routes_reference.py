"""Reference products, listed patents, protected indications (PRD 3.1-3.2)."""
from flask import Blueprint, request

from auth import ALL_ROLES, auth, own_reference_product, require_role
from clock import today
from envelope import sort_default, success_list, success_object
from errors import fail
from serialize import patent, protection, reference_product
from state import STORE, create_entity, get
from validate import (
    body,
    opt_bool,
    opt_str,
    req_date,
    req_enum,
    req_str,
    req_str_list,
)

bp = Blueprint("reference", __name__)

PATENT_TYPES = ("DRUG_SUBSTANCE", "DRUG_PRODUCT", "METHOD_OF_USE")


@bp.post("/generic-drug-review/reference-products")
def create_reference_product():
    _uid, role = auth()
    require_role(role, ["ProgramAdmin"])
    b = body()
    brand_name = req_str(b, "brand_name")
    active_ingredient = req_str(b, "active_ingredient")
    strength = req_str(b, "strength")
    dosage_form = req_str(b, "dosage_form")
    rld_approval_date = req_date(b, "rld_approval_date")
    is_nce = opt_bool(b, "is_new_chemical_entity", False)
    indication_codes = req_str_list(b, "indication_codes")
    patent_owner_user_id = req_str(b, "patent_owner_user_id")
    ent = create_entity("reference_products", {
        "brand_name": brand_name,
        "active_ingredient": active_ingredient,
        "strength": strength,
        "dosage_form": dosage_form,
        "rld_approval_date": rld_approval_date.isoformat(),
        "is_new_chemical_entity": is_nce,
        "indication_codes": indication_codes,
        "patent_owner_user_id": patent_owner_user_id,
    })
    return success_object(reference_product(ent), 201)


@bp.get("/generic-drug-review/reference-products/<rp_id>")
def get_reference_product(rp_id):
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    ent = get("reference_products", rp_id)
    if ent is None:
        fail("ERR_REFERENCE_PRODUCT_NOT_FOUND", "Reference product id does not exist")
    return success_object(reference_product(ent))


@bp.post("/generic-drug-review/reference-products/<rp_id>/listed-patents")
def create_patent(rp_id):
    uid, role = auth()
    require_role(role, ["InnovatorSponsor"])
    rp = get("reference_products", rp_id)
    if rp is None:
        fail("ERR_REFERENCE_PRODUCT_NOT_FOUND", "Reference product id does not exist")
    own_reference_product(uid, rp)
    b = body()
    patent_number = req_str(b, "patent_number")
    patent_type = req_enum(b, "patent_type", PATENT_TYPES)
    expiry_date = req_date(b, "expiry_date")
    use_code = opt_str(b, "use_code", None)
    # use_code is required exactly when the type is METHOD_OF_USE.
    if patent_type == "METHOD_OF_USE":
        if use_code is None:
            fail("ERR_INVALID_REQUEST",
                 "use_code is required when patent_type is METHOD_OF_USE")
    elif use_code is not None:
        fail("ERR_INVALID_REQUEST",
             "use_code must be null unless patent_type is METHOD_OF_USE")
    status = "EXPIRED" if expiry_date < today() else "LISTED"
    ent = create_entity("patents", {
        "reference_product_id": rp_id,
        "patent_number": patent_number,
        "patent_type": patent_type,
        "use_code": use_code,
        "expiry_date": expiry_date.isoformat(),
        "status": status,
    })
    return success_object(patent(ent), 201)


@bp.get("/generic-drug-review/reference-products/<rp_id>/listed-patents")
def list_patents(rp_id):
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    if get("reference_products", rp_id) is None:
        fail("ERR_REFERENCE_PRODUCT_NOT_FOUND", "Reference product id does not exist")
    items = [p for p in STORE["patents"].values()
             if p["reference_product_id"] == rp_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return success_list([patent(p) for p in sort_default(items)])


@bp.post("/generic-drug-review/reference-products/<rp_id>/protected-indications")
def create_protection(rp_id):
    _uid, role = auth()
    require_role(role, ["ProgramAdmin"])
    rp = get("reference_products", rp_id)
    if rp is None:
        fail("ERR_REFERENCE_PRODUCT_NOT_FOUND", "Reference product id does not exist")
    b = body()
    indication_code = req_str(b, "indication_code")
    effective_from = req_date(b, "effective_from")
    protected_until = req_date(b, "protected_until")
    if protected_until < effective_from:
        fail("ERR_INVALID_REQUEST",
             "protected_until must be on or after effective_from")
    new_status = "EXPIRED" if protected_until < today() else "ACTIVE"
    # Priority 13: closed-interval overlap against existing ACTIVE windows of
    # the same (product, code); adjacency counts as conflict; EXPIRED windows
    # never block. A window born EXPIRED is not ACTIVE and cannot conflict.
    if new_status == "ACTIVE":
        for w in STORE["protections"].values():
            if (w["reference_product_id"] != rp_id
                    or w["indication_code"] != indication_code
                    or w["status"] != "ACTIVE"):
                continue
            if (effective_from <= req_date_value(w["protected_until"])
                    and req_date_value(w["effective_from"]) <= protected_until):
                fail("ERR_INDICATION_WINDOW_OVERLAP",
                     "Protection window overlaps or abuts an ACTIVE window "
                     "for this indication_code")
    # Priority 21: the code must be one of the product's approved indications.
    if indication_code not in rp["indication_codes"]:
        fail("ERR_INDICATION_NOT_ON_REFERENCE_PRODUCT",
             "indication_code is not a member of the reference product's "
             "indication_codes")
    ent = create_entity("protections", {
        "reference_product_id": rp_id,
        "indication_code": indication_code,
        "effective_from": effective_from.isoformat(),
        "protected_until": protected_until.isoformat(),
        "status": new_status,
    })
    return success_object(protection(ent), 201)


@bp.get("/generic-drug-review/reference-products/<rp_id>/protected-indications")
def list_protections(rp_id):
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    if get("reference_products", rp_id) is None:
        fail("ERR_REFERENCE_PRODUCT_NOT_FOUND", "Reference product id does not exist")
    items = [w for w in STORE["protections"].values()
             if w["reference_product_id"] == rp_id]
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return success_list([protection(w) for w in sort_default(items)])


def req_date_value(s):
    """Stored windows are well-formed already; parse without shape errors."""
    from clock import parse_date
    return parse_date(s)
