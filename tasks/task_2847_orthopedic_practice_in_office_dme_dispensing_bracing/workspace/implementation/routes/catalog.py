"""Suppliers, the standards attestation cascade, and device products."""
from flask import Blueprint

from common import (authorize, body_json, enum_arg, need_bool, need_date,
                    need_enum, need_int, need_str, opt_bool, opt_date, opt_enum,
                    paginate, respond_list, respond_object)
from store import (ACCREDITATION_BODIES, PRODUCT_CATEGORIES, SPECIALTIES,
                   SUPERVISION_LEVELS, db, insert, lookup, product_json,
                   sort_created, stamp, supplier_json, touch)

bp = Blueprint("catalog", __name__)

SUPPLIER_READ_ROLES = ["PracticeAdmin", "ComplianceOfficer", "InventoryManager"]


@bp.post("/dme/suppliers")
def create_supplier():
    authorize(["PracticeAdmin"])
    body = body_json()
    name = need_str(body, "name", 1, 120)
    accreditation_body = need_enum(body, "accreditation_body", ACCREDITATION_BODIES)
    accreditation_expires_on = need_date(body, "accreditation_expires_on")
    promised = need_int(body, "promised_turnaround_days", 1)
    attested = opt_bool(body, "dmepos_standards_attested", False)
    custom_fab_capable = opt_bool(body, "custom_fab_capable", False)
    quality_hold = opt_bool(body, "quality_hold", False)
    row = stamp({
        "name": name,
        "accreditation_body": accreditation_body,
        "accreditation_expires_on": accreditation_expires_on,
        "dmepos_standards_attested": attested,
        "custom_fab_capable": custom_fab_capable,
        "quality_hold": quality_hold,
        "promised_turnaround_days": promised,
        "turnaround_score": 100,
        "accepted_fab_order_count": 0,
    })
    insert("suppliers", row)
    return respond_object(supplier_json(row), 201)


@bp.get("/dme/suppliers/<supplier_id>")
def get_supplier(supplier_id):
    authorize(SUPPLIER_READ_ROLES)
    row = lookup("suppliers", supplier_id, "ERR_SUPPLIER_NOT_FOUND")
    return respond_object(supplier_json(row), 200)


@bp.post("/dme/suppliers/<supplier_id>/standards-attestation")
def standards_attestation(supplier_id):
    authorize(["ComplianceOfficer"])
    body = body_json()
    attested = need_bool(body, "dmepos_standards_attested")
    quality_hold = need_bool(body, "quality_hold")
    accreditation_expires_on = opt_date(body, "accreditation_expires_on")
    supplier = lookup("suppliers", supplier_id, "ERR_SUPPLIER_NOT_FOUND")

    supplier["dmepos_standards_attested"] = attested
    supplier["quality_hold"] = quality_hold
    if accreditation_expires_on is not None:
        supplier["accreditation_expires_on"] = accreditation_expires_on
    touch(supplier)

    orders = sort_created([r for r in db["fab_orders"].values()
                           if r["supplier_id"] == supplier["id"]])
    if quality_hold:
        for order in orders:
            if order["status"] not in ("SUBMITTED", "IN_FABRICATION",
                                       "ADJUSTMENT_REQUESTED"):
                continue
            order["status"] = "SUPPLIER_HOLD"
            touch(order)
            encounter = db["encounters"].get(order["encounter_id"])
            if encounter is not None:
                encounter["compliance_hold"] = True
                encounter["hold_reason"] = "SUPPLIER_QUALITY_HOLD"
                touch(encounter)
    elif attested:
        for order in orders:
            if order["status"] != "SUPPLIER_HOLD":
                continue
            order["status"] = "IN_FABRICATION"
            touch(order)
            encounter = db["encounters"].get(order["encounter_id"])
            if encounter is not None and encounter["hold_reason"] == "SUPPLIER_QUALITY_HOLD":
                encounter["compliance_hold"] = False
                encounter["hold_reason"] = None
                touch(encounter)
    return respond_object(supplier_json(supplier), 200)


@bp.post("/dme/products")
def create_product():
    authorize(["PracticeAdmin", "InventoryManager"])
    body = body_json()
    supplier_id = need_str(body, "supplier_id")
    hcpcs_code = need_str(body, "hcpcs_code", 1, 8)
    description = need_str(body, "description", 1, 200)
    category = need_enum(body, "category", PRODUCT_CATEGORIES)
    specialty = need_enum(body, "specialty", SPECIALTIES)
    group = need_str(body, "same_or_similar_group", 1, 40, upper=True)
    lifetime = need_int(body, "reasonable_useful_lifetime_months", 1)
    allowed_amount_cents = need_int(body, "allowed_amount_cents", 0)
    cash_price_cents = need_int(body, "cash_price_cents", 0)
    unit_cost_cents = need_int(body, "unit_cost_cents", 0)
    requires_prior_auth = opt_bool(body, "requires_prior_auth", False)
    supervision = opt_enum(body, "ioas_supervision_required", SUPERVISION_LEVELS,
                           "GENERAL")
    supplier = lookup("suppliers", supplier_id, "ERR_SUPPLIER_NOT_FOUND")
    row = stamp({
        "supplier_id": supplier["id"],
        "hcpcs_code": hcpcs_code,
        "description": description,
        "category": category,
        "specialty": specialty,
        "same_or_similar_group": group,
        "reasonable_useful_lifetime_months": lifetime,
        "allowed_amount_cents": allowed_amount_cents,
        "cash_price_cents": cash_price_cents,
        "unit_cost_cents": unit_cost_cents,
        "requires_prior_auth": requires_prior_auth,
        "ioas_supervision_required": supervision,
    })
    insert("products", row)
    return respond_object(product_json(row), 201)


@bp.get("/dme/products/<product_id>")
def get_product(product_id):
    authorize(["PracticeAdmin", "InventoryManager", "InsuranceCoordinator",
               "DmeFitter"])
    row = lookup("products", product_id, "ERR_PRODUCT_NOT_FOUND")
    return respond_object(product_json(row), 200)


@bp.get("/dme/suppliers/<supplier_id>/products")
def list_supplier_products(supplier_id):
    authorize(["PracticeAdmin", "InventoryManager"])
    supplier = lookup("suppliers", supplier_id, "ERR_SUPPLIER_NOT_FOUND")
    category = enum_arg("category", PRODUCT_CATEGORIES)
    rows = [r for r in db["products"].values() if r["supplier_id"] == supplier["id"]]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    page, pagination = paginate(sort_created(rows))
    return respond_list([product_json(r) for r in page], pagination, 200)
