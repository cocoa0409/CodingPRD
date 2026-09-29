"""The product catalogue and the bill of materials (PRD 3.3)."""
from flask import Blueprint

import db
import response
import validate
from errors import fail
from middleware import guard
from routes.common import list_endpoint
from services import calc, cascade, posture

bp = Blueprint("products", __name__)

CATEGORIES = ("CONSUMER_GOOD", "FOOD", "DIETARY_SUPPLEMENT", "FURNITURE", "VEHICLE_PART")
CHANNELS = ("RETAIL", "CATALOG", "INTERNET")
OCCUPANCY_TYPES = ("NONE", "ENCLOSED_PARKING_FACILITY", "AMUSEMENT_PARK", "PETROLEUM_REFINERY")
PRODUCT_TRIGGERS = ("MARKET", "DISCONTINUE")
PRODUCT_LEGAL = {"MARKET": ("DEVELOPMENT",), "DISCONTINUE": ("DEVELOPMENT", "MARKETED")}
COMPONENT_TRIGGERS = ("REMOVE",)
READ_ROLES = ("ComplianceAnalyst", "ToxicologyReviewer", "RegulatoryCounsel",
              "LabelingSpecialist", "RegistryAdmin")
COMPONENT_READ_ROLES = ("ComplianceAnalyst", "ToxicologyReviewer", "RegulatoryCounsel",
                        "RegistryAdmin")
UPDATE_FIELDS = ("product_name", "product_category", "occupancy_type",
                 "distribution_channels", "label_area_sq_in", "annual_units")


def _freeze_check(product):
    if product.get("compliance_posture") == "ENFORCEMENT_HOLD":
        fail("ERR_ENFORCEMENT_HOLD_FREEZE",
             "the bill of materials is frozen while the product is on enforcement hold")


@bp.route("/products", methods=["POST"])
@guard("RegistryAdmin")
def create_product(who):
    body = validate.body_json()
    sku = validate.v_str(body, "sku", required=True, minlen=1, maxlen=40)
    name = validate.v_str(body, "product_name", required=True, minlen=1, maxlen=160)
    category = validate.v_enum(body, "product_category", CATEGORIES, required=True)
    if "distribution_channels" not in body or body["distribution_channels"] is None:
        fail("ERR_INVALID_REQUEST", "distribution_channels is required")
    label_area = validate.v_num(body, "label_area_sq_in", required=True)
    annual_units = validate.v_int(body, "annual_units", required=True)
    occupancy = validate.v_enum(body, "occupancy_type", OCCUPANCY_TYPES, default="NONE")
    validate.v_domain(body)
    channels = validate.v_channels(body, "distribution_channels", required=True, values=CHANNELS)
    for existing in db.rows("products"):
        if existing["sku"] == sku:
            fail("ERR_DUPLICATE_RESOURCE", "sku is already in use")
    validate.v_writable(body, ("sku",) + UPDATE_FIELDS)
    row = db.insert("products", {
        "sku": sku,
        "product_name": name,
        "product_category": category,
        "occupancy_type": occupancy,
        "distribution_channels": channels,
        "label_area_sq_in": label_area,
        "annual_units": annual_units,
        "lifecycle_state": "DEVELOPMENT",
        "compliance_posture": "EXPOSURE_UNKNOWN",
        "open_notice_count": 0,
        "accrued_penalty_cents": 0,
        "total_listed_chemical_load_ug": 0,
    })
    return response.created(db.serialize("products", row))


@bp.route("/products/<product_id>", methods=["PATCH"])
@guard("RegistryAdmin")
def update_product(who, product_id):
    body = validate.body_json()
    name = validate.v_str(body, "product_name", minlen=1, maxlen=160)
    category = validate.v_enum(body, "product_category", CATEGORIES)
    occupancy = validate.v_enum(body, "occupancy_type", OCCUPANCY_TYPES)
    label_area = validate.v_num(body, "label_area_sq_in")
    annual_units = validate.v_int(body, "annual_units")
    validate.v_domain(body)
    channels = validate.v_channels(body, "distribution_channels", values=CHANNELS)
    product = validate.must_exist("products", product_id, "product")
    if product["lifecycle_state"] == "DISCONTINUED":
        fail("ERR_ENTITY_IMMUTABLE", "a discontinued product is immutable")
    validate.v_writable(body, UPDATE_FIELDS)
    if name is not None:
        product["product_name"] = name
    if category is not None:
        product["product_category"] = category
    if occupancy is not None:
        product["occupancy_type"] = occupancy
    if label_area is not None:
        product["label_area_sq_in"] = label_area
    if annual_units is not None:
        product["annual_units"] = annual_units
    if channels is not None:
        product["distribution_channels"] = channels
    db.touch(product)
    posture.recompute_posture(product)
    return response.ok(db.serialize("products", product))


@bp.route("/products/<product_id>/transitions", methods=["POST"])
@guard("RegistryAdmin")
def transition_product(who, product_id):
    body = validate.body_json()
    action = validate.v_action(body, PRODUCT_TRIGGERS)
    product = validate.must_exist("products", product_id, "product")
    if product["lifecycle_state"] not in PRODUCT_LEGAL[action]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "%s is not a declared transition out of %s" % (action, product["lifecycle_state"]))
    validate.v_writable(body, ("action",))
    if action == "MARKET":
        if product.get("compliance_posture") in ("ENFORCEMENT_HOLD", "EXPOSURE_UNKNOWN"):
            fail("ERR_PRODUCT_ON_ENFORCEMENT_HOLD",
                 "a product may go to market only once its exposure picture is settled")
        product["lifecycle_state"] = "MARKETED"
    else:
        product["lifecycle_state"] = "DISCONTINUED"
    db.touch(product)
    return response.ok(db.serialize("products", product))


@bp.route("/products/<product_id>/components", methods=["POST"])
@guard("ComplianceAnalyst")
def create_component(who, product_id):
    body = validate.body_json()
    validate.v_str(body, "material_id", required=True)
    quantity = validate.v_num(body, "quantity_grams_per_unit", required=True)
    contact = validate.v_num(body, "contact_factor", required=True)
    supersedes_id = validate.v_str(body, "supersedes_component_id")
    validate.v_domain(body)
    validate.v_fractions(body)
    product = validate.must_exist("products", product_id, "product")
    material = validate.fk("materials", body, "material_id", required=True)
    superseded = None
    if supersedes_id is not None:
        superseded = validate.must_exist("product_components", supersedes_id,
                                         "supersedes_component_id")
        if superseded["product_id"] != product["id"]:
            fail("ERR_NOT_FOUND", "supersedes_component_id belongs to another product")
    for component in calc.components_of(product["id"]):
        if component["status"] != "ACTIVE" or component["material_id"] != material["id"]:
            continue
        if superseded is not None and component["id"] == superseded["id"]:
            continue
        fail("ERR_DUPLICATE_RESOURCE", "this material is already an active component")
    if superseded is not None and superseded["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "the superseded component is not currently ACTIVE")
    if product["lifecycle_state"] == "DISCONTINUED":
        fail("ERR_PARENT_STATE_FORBIDS_WRITE",
             "a component may not be added to a discontinued product")
    validate.v_writable(body, ("material_id", "quantity_grams_per_unit", "contact_factor",
                               "supersedes_component_id"))
    _freeze_check(product)
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        db.touch(superseded)
    row = db.insert("product_components", {
        "product_id": product["id"],
        "material_id": material["id"],
        "quantity_grams_per_unit": quantity,
        "contact_factor": contact,
        "status": "ACTIVE",
    })
    db.touch(product)
    cascade.product_data_changed(product)
    return response.created(db.serialize("product_components", row))


@bp.route("/product-components/<component_id>", methods=["PATCH"])
@guard("ComplianceAnalyst")
def update_component(who, component_id):
    body = validate.body_json()
    quantity = validate.v_num(body, "quantity_grams_per_unit")
    contact = validate.v_num(body, "contact_factor")
    validate.v_domain(body)
    validate.v_fractions(body)
    component = validate.must_exist("product_components", component_id, "component")
    product = db.get("products", component["product_id"])
    if component["status"] in ("REMOVED", "SUPERSEDED"):
        fail("ERR_ENTITY_IMMUTABLE", "a %s component is immutable" % component["status"])
    validate.v_writable(body, ("quantity_grams_per_unit", "contact_factor"))
    _freeze_check(product)
    if quantity is not None:
        component["quantity_grams_per_unit"] = quantity
    if contact is not None:
        component["contact_factor"] = contact
    db.touch(component)
    db.touch(product)
    cascade.product_data_changed(product)
    return response.ok(db.serialize("product_components", component))


@bp.route("/product-components/<component_id>/transitions", methods=["POST"])
@guard("ComplianceAnalyst")
def transition_component(who, component_id):
    body = validate.body_json()
    action = validate.v_action(body, COMPONENT_TRIGGERS)
    component = validate.must_exist("product_components", component_id, "component")
    product = db.get("products", component["product_id"])
    if component["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "REMOVE is not a declared transition out of %s" % component["status"])
    if product is not None and product["lifecycle_state"] == "DISCONTINUED":
        fail("ERR_PARENT_STATE_FORBIDS_WRITE",
             "a component may not be removed from a discontinued product")
    validate.v_writable(body, ("action",))
    _freeze_check(product)
    component["status"] = "REMOVED"
    db.touch(component)
    db.touch(product)
    cascade.product_data_changed(product)
    return response.ok(db.serialize("product_components", component))


@bp.route("/products/<product_id>", methods=["GET"])
@guard(*READ_ROLES)
def read_product(who, product_id):
    product = validate.must_exist("products", product_id, "product")
    return response.ok(db.serialize("products", product))


@bp.route("/products", methods=["GET"])
@guard(*READ_ROLES)
def list_products(who):
    return list_endpoint("products", {
        "lifecycle_state": "lifecycle_state",
        "compliance_posture": "compliance_posture",
        "product_category": "product_category",
    })


@bp.route("/product-components/<component_id>", methods=["GET"])
@guard(*COMPONENT_READ_ROLES)
def read_component(who, component_id):
    component = validate.must_exist("product_components", component_id, "component")
    return response.ok(db.serialize("product_components", component))


@bp.route("/product-components", methods=["GET"])
@guard(*COMPONENT_READ_ROLES)
def list_components(who):
    return list_endpoint("product_components", {
        "product_id": "product_id",
        "material_id": "material_id",
        "status": "status",
    })
