"""Materials, the bill-of-materials tree, supplier data collection and the lab
pipeline (PRD 3.3, 3.4 and 3.5)."""
from flask import Blueprint

import db
import response
import validate
from errors import fail
from middleware import guard, action_role
from util import D
from routes.common import list_endpoint
from services import calc, cascade

bp = Blueprint("materials", __name__)

MATERIAL_CLASSES = ("RAW_MATERIAL", "PACKAGING", "MANUFACTURING_AID")
MAX_BOM_DEPTH = 4
READ_ROLES = ("ComplianceAnalyst", "ToxicologyReviewer", "RegulatoryCounsel",
              "RegistryAdmin", "SupplierPortalUser")

DISCLOSURE_TRIGGERS = ("REQUEST", "RECORD_RESPONSE", "MARK_REFUSED", "VERIFY")
DISCLOSURE_ROLES = {
    "REQUEST": ("ComplianceAnalyst",),
    "RECORD_RESPONSE": ("ComplianceAnalyst", "SupplierPortalUser"),
    "MARK_REFUSED": ("ComplianceAnalyst",),
    "VERIFY": ("ComplianceAnalyst",),
}
DISCLOSURE_LEGAL = {
    "REQUEST": ("NOT_REQUESTED", "REFUSED", "INCOMPLETE"),
    "RECORD_RESPONSE": ("REQUESTED",),
    "MARK_REFUSED": ("REQUESTED",),
    "VERIFY": ("RECEIVED",),
}

LAB_TRIGGERS = ("REQUEST_TEST", "REPORT_RESULT", "VERIFY", "DISPUTE")
LAB_ROLES = {
    "REQUEST_TEST": ("ComplianceAnalyst",),
    "REPORT_RESULT": ("ComplianceAnalyst",),
    "VERIFY": ("ToxicologyReviewer",),
    "DISPUTE": ("ToxicologyReviewer",),
}
LAB_LEGAL = {
    "REQUEST_TEST": ("DECLARED", "DISPUTED"),
    "REPORT_RESULT": ("TEST_REQUESTED",),
    "VERIFY": ("TEST_REPORTED",),
    "DISPUTE": ("TEST_REPORTED",),
}


def _own_material(who, material):
    """A SupplierPortalUser acts only on the materials it ships."""
    if who.role == "SupplierPortalUser" and who.user_id != material.get("supplier_id"):
        fail("ERR_UNAUTHORIZED", "a supplier may act only on its own materials")


def _check_tree(material, parent):
    """Cycle and depth ceiling, both ERR_MATERIAL_CYCLE (ladder layer 7)."""
    if parent is None:
        return 0
    if material is not None:
        if parent["id"] == material["id"]:
            fail("ERR_MATERIAL_CYCLE", "a material may not be its own parent")
        for node in calc.descendants(material):
            if node["id"] == parent["id"]:
                fail("ERR_MATERIAL_CYCLE", "the named parent is already a descendant")
    new_depth = int(parent.get("bom_depth") or 0) + 1
    if new_depth > MAX_BOM_DEPTH:
        fail("ERR_MATERIAL_CYCLE", "bom_depth may not exceed %d" % MAX_BOM_DEPTH)
    if material is not None:
        current = int(material.get("bom_depth") or 0)
        for node in calc.descendants(material):
            if new_depth + (int(node.get("bom_depth") or 0) - current) > MAX_BOM_DEPTH:
                fail("ERR_MATERIAL_CYCLE", "a descendant would exceed the depth ceiling")
    return new_depth


def _apply_depth(material, new_depth):
    current = int(material.get("bom_depth") or 0)
    shift = new_depth - current
    material["bom_depth"] = new_depth
    if shift:
        for node in calc.descendants(material):
            node["bom_depth"] = int(node.get("bom_depth") or 0) + shift


@bp.route("/materials", methods=["POST"])
@guard("ComplianceAnalyst")
def create_material(who):
    body = validate.body_json()
    code = validate.v_str(body, "material_code", required=True, minlen=1, maxlen=40)
    material_class = validate.v_enum(body, "material_class", MATERIAL_CLASSES, required=True)
    validate.v_str(body, "supplier_id", required=True)
    parent_id = validate.v_str(body, "parent_material_id")
    fraction = validate.v_num(body, "parent_mass_fraction")
    claim = validate.v_bool(body, "naturally_occurring_claim", default=False)
    if parent_id is not None and fraction is None:
        fail("ERR_INVALID_REQUEST",
             "parent_mass_fraction is required when parent_material_id is supplied")
    if parent_id is None and fraction is not None:
        fail("ERR_INVALID_REQUEST",
             "parent_mass_fraction may be supplied only with parent_material_id")
    validate.v_fractions(body)
    supplier = validate.fk("suppliers", body, "supplier_id", required=True)
    parent = validate.fk("materials", body, "parent_material_id")
    for existing in db.rows("materials"):
        if existing["material_code"] == code:
            fail("ERR_DUPLICATE_RESOURCE", "material_code is already in use")
    validate.v_writable(body, ("material_code", "material_class", "supplier_id",
                               "parent_material_id", "parent_mass_fraction",
                               "naturally_occurring_claim"))
    depth = _check_tree(None, parent)
    row = db.insert("materials", {
        "material_code": code,
        "material_class": material_class,
        "supplier_id": supplier["id"],
        "parent_material_id": parent["id"] if parent else None,
        "parent_mass_fraction": fraction,
        "bom_depth": depth,
        "disclosure_status": "NOT_REQUESTED",
        "data_request_sent_at": None,
        "data_received_at": None,
        "naturally_occurring_claim": claim,
    })
    cascade.material_data_changed(row)
    return response.created(db.serialize("materials", row))


@bp.route("/materials/<material_id>", methods=["PATCH"])
@guard("ComplianceAnalyst")
def update_material(who, material_id):
    body = validate.body_json()
    parent_id = validate.v_str(body, "parent_material_id")
    fraction = validate.v_num(body, "parent_mass_fraction")
    claim = validate.v_bool(body, "naturally_occurring_claim")
    validate.v_fractions(body)
    material = validate.must_exist("materials", material_id, "material")
    parent = validate.fk("materials", body, "parent_material_id")
    components = [c for c in db.rows("product_components")
                  if c["material_id"] == material["id"]]
    if components and all(c["status"] == "SUPERSEDED" for c in components):
        fail("ERR_ENTITY_IMMUTABLE",
             "this material is reachable only through superseded components")
    validate.v_writable(body, ("parent_material_id", "parent_mass_fraction",
                               "naturally_occurring_claim"))
    # A re-parent changes which products reach this material, so the products
    # that reached it through the *old* parent chain must be recomputed too:
    # they lose the whole moved subtree from their roll-up.
    reached_before = calc.products_reaching(material)
    if parent is not None:
        if fraction is None and material.get("parent_mass_fraction") is None:
            fail("ERR_INVALID_REQUEST",
                 "parent_mass_fraction is required when parent_material_id is supplied")
        depth = _check_tree(material, parent)
        material["parent_material_id"] = parent["id"]
        if fraction is not None:
            material["parent_mass_fraction"] = fraction
        _apply_depth(material, depth)
    elif fraction is not None:
        if material.get("parent_material_id") is None:
            fail("ERR_INVALID_REQUEST",
                 "parent_mass_fraction may be supplied only with parent_material_id")
        material["parent_mass_fraction"] = fraction
    if claim is not None:
        material["naturally_occurring_claim"] = claim
    db.touch(material)
    affected = list(reached_before)
    for product in calc.products_reaching(material):
        if product not in affected:
            affected.append(product)
    for product in affected:
        cascade.product_data_changed(product)
    return response.ok(db.serialize("materials", material))


@bp.route("/materials/<material_id>/disclosure", methods=["POST"])
@guard("ComplianceAnalyst", "SupplierPortalUser")
def disclosure(who, material_id):
    body = validate.body_json()
    action = validate.v_action(body, DISCLOSURE_TRIGGERS)
    action_role(action, DISCLOSURE_ROLES, who.role)
    completeness = None
    if action == "RECORD_RESPONSE":
        completeness = validate.v_enum(body, "response_completeness",
                                      ("COMPLETE", "INCOMPLETE"), required=True)
    claim = validate.v_bool(body, "naturally_occurring_claim")
    material = validate.must_exist("materials", material_id, "material")
    _own_material(who, material)
    if material["disclosure_status"] not in DISCLOSURE_LEGAL[action]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "%s is not a declared transition out of %s"
             % (action, material["disclosure_status"]))
    validate.v_writable(body, ("action", "response_completeness",
                               "naturally_occurring_claim"))
    if action == "REQUEST":
        material["disclosure_status"] = "REQUESTED"
        material["data_request_sent_at"] = db.now()
    elif action == "RECORD_RESPONSE":
        material["disclosure_status"] = "RECEIVED" if completeness == "COMPLETE" else "INCOMPLETE"
        material["data_received_at"] = db.now()
    elif action == "MARK_REFUSED":
        material["disclosure_status"] = "REFUSED"
    else:
        material["disclosure_status"] = "VERIFIED"
    if claim is not None:
        material["naturally_occurring_claim"] = claim
    db.touch(material)
    cascade.material_data_changed(material)
    return response.ok(db.serialize("materials", material))


@bp.route("/materials/<material_id>/chemicals", methods=["POST"])
@guard("ComplianceAnalyst", "SupplierPortalUser")
def declare_chemical(who, material_id):
    body = validate.body_json()
    validate.v_str(body, "chemical_id", required=True)
    concentration = validate.v_num(body, "declared_concentration_ppm", required=True)
    validate.v_domain(body)
    material = validate.must_exist("materials", material_id, "material")
    _own_material(who, material)
    chemical = validate.fk("listed_chemicals", body, "chemical_id", required=True)
    for link in db.rows("material_chemicals"):
        if link["material_id"] == material["id"] and link["chemical_id"] == chemical["id"]:
            fail("ERR_DUPLICATE_RESOURCE",
                 "this chemical is already declared on this material")
    if chemical["status"] == "WITHDRAWN":
        fail("ERR_PARENT_STATE_FORBIDS_WRITE",
             "a link may not be created against a withdrawn chemical")
    validate.v_writable(body, ("chemical_id", "declared_concentration_ppm"))
    row = db.insert("material_chemicals", {
        "material_id": material["id"],
        "chemical_id": chemical["id"],
        "declared_concentration_ppm": concentration,
        "measurement_basis": "SUPPLIER_DECLARED",
        "status": "DECLARED",
        "lab_name": None,
        "lab_result_ppm": None,
        "lab_loq_ppm": None,
        "lab_reported_at": None,
        "dispute_note": None,
    })
    cascade.material_data_changed(material)
    return response.created(db.serialize("material_chemicals", row))


@bp.route("/material-chemicals/<material_chemical_id>/transitions", methods=["POST"])
@guard("ComplianceAnalyst", "ToxicologyReviewer")
def transition_link(who, material_chemical_id):
    body = validate.body_json()
    action = validate.v_action(body, LAB_TRIGGERS)
    action_role(action, LAB_ROLES, who.role)
    lab_name = None
    lab_result = None
    lab_loq = None
    note = None
    if action == "REPORT_RESULT":
        lab_name = validate.v_str(body, "lab_name", required=True, minlen=1)
        lab_result = validate.v_num(body, "lab_result_ppm", required=True)
        lab_loq = validate.v_num(body, "lab_loq_ppm", required=True)
        validate.v_domain(body)
    if action == "DISPUTE":
        note = validate.v_str(body, "dispute_note", required=True, minlen=1)
    link = validate.must_exist("material_chemicals", material_chemical_id, "material_chemical")
    if link["status"] not in LAB_LEGAL[action]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "%s is not a declared transition out of %s" % (action, link["status"]))
    material = db.get("materials", link["material_id"])
    if action == "VERIFY" and material is not None and \
            material.get("disclosure_status") not in ("RECEIVED", "VERIFIED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "a measured value may be verified only once the supplier has answered")
    validate.v_writable(body, ("action", "lab_name", "lab_result_ppm", "lab_loq_ppm",
                               "dispute_note"))
    if action == "REQUEST_TEST":
        link["status"] = "TEST_REQUESTED"
        db.touch(link)
    elif action == "REPORT_RESULT":
        link["status"] = "TEST_REPORTED"
        link["lab_name"] = lab_name
        link["lab_result_ppm"] = lab_result
        link["lab_loq_ppm"] = lab_loq
        link["lab_reported_at"] = db.now()
        link["measurement_basis"] = "LAB_TESTED"
        db.touch(link)
        cascade.material_data_changed(material)
    elif action == "VERIFY":
        link["status"] = "VERIFIED"
        db.touch(link)
        cascade.material_data_changed(material)
    else:
        link["status"] = "DISPUTED"
        link["dispute_note"] = note
        link["measurement_basis"] = "SUPPLIER_DECLARED"
        link["lab_name"] = None
        link["lab_result_ppm"] = None
        link["lab_loq_ppm"] = None
        link["lab_reported_at"] = None
        db.touch(link)
        cascade.material_data_changed(material)
    return response.ok(db.serialize("material_chemicals", link))


@bp.route("/materials/<material_id>", methods=["GET"])
@guard(*READ_ROLES)
def read_material(who, material_id):
    material = validate.must_exist("materials", material_id, "material")
    _own_material(who, material)
    return response.ok(db.serialize("materials", material))


@bp.route("/materials", methods=["GET"])
@guard(*READ_ROLES)
def list_materials(who):
    return list_endpoint("materials", {
        "supplier_id": "supplier_id",
        "parent_material_id": "parent_material_id",
        "material_class": "material_class",
        "disclosure_status": "disclosure_status",
    })


@bp.route("/material-chemicals/<material_chemical_id>", methods=["GET"])
@guard(*READ_ROLES)
def read_link(who, material_chemical_id):
    link = validate.must_exist("material_chemicals", material_chemical_id, "material_chemical")
    material = db.get("materials", link["material_id"])
    if material is not None:
        _own_material(who, material)
    return response.ok(db.serialize("material_chemicals", link))


@bp.route("/material-chemicals", methods=["GET"])
@guard(*READ_ROLES)
def list_links(who):
    return list_endpoint("material_chemicals", {
        "material_id": "material_id",
        "chemical_id": "chemical_id",
        "status": "status",
        "measurement_basis": "measurement_basis",
    })
