"""Suppliers, warranties and the indemnity backstop (PRD 3.2)."""
from flask import Blueprint

import db
import response
import validate
from errors import fail
from middleware import guard
from routes.common import list_endpoint
from services import money

bp = Blueprint("suppliers", __name__)

SCOPES = ("ALL_MATERIALS", "RAW_MATERIAL_ONLY", "PACKAGING_ONLY")
TRIGGERS = ("EXECUTE_WARRANTY", "REVOKE_WARRANTY")
LEGAL = {"EXECUTE_WARRANTY": ("NONE",), "REVOKE_WARRANTY": ("ACTIVE",)}
CREATE_FIELDS = ("legal_name", "contact_email", "warranty_scope",
                 "pass_through_warning_obligation", "indemnity_cap_cents",
                 "warranty_effective_from", "warranty_effective_to")
WARRANTY_LIVE_NOTICE_STATUSES = ("UNDER_EVALUATION", "SETTLEMENT_NEGOTIATION")


@bp.route("/suppliers", methods=["POST"])
@guard("ComplianceAnalyst")
def create_supplier(who):
    body = validate.body_json()
    legal_name = validate.v_str(body, "legal_name", required=True, minlen=1, maxlen=160)
    contact_email = validate.v_str(body, "contact_email", required=True, minlen=1)
    if "@" not in contact_email:
        fail("ERR_INVALID_REQUEST", "contact_email must contain an at-sign")
    scope = validate.v_enum(body, "warranty_scope", SCOPES)
    pass_through = validate.v_bool(body, "pass_through_warning_obligation", default=False)
    cap = validate.v_int(body, "indemnity_cap_cents", default=0)
    window_from = validate.v_dt(body, "warranty_effective_from")
    window_to = validate.v_dt(body, "warranty_effective_to")
    validate.v_domain(body)
    validate.v_interval(window_from, window_to)
    for existing in db.rows("suppliers"):
        if existing["legal_name"] == legal_name:
            fail("ERR_DUPLICATE_RESOURCE", "legal_name is already registered")
    validate.v_writable(body, CREATE_FIELDS)
    row = db.insert("suppliers", {
        "legal_name": legal_name,
        "contact_email": contact_email,
        "warranty_status": "NONE",
        "warranty_scope": scope,
        "pass_through_warning_obligation": pass_through,
        "indemnity_cap_cents": cap,
        "warranty_effective_from": window_from,
        "warranty_effective_to": window_to,
    })
    return response.created(db.serialize("suppliers", row))


@bp.route("/suppliers/<supplier_id>/transitions", methods=["POST"])
@guard("RegulatoryCounsel")
def transition_supplier(who, supplier_id):
    body = validate.body_json()
    action = validate.v_action(body, TRIGGERS)
    supplier = validate.must_exist("suppliers", supplier_id, "supplier")
    if supplier["warranty_status"] not in LEGAL[action]:
        fail("ERR_INVALID_STATE_TRANSITION",
             "%s is not a declared transition out of %s" % (action, supplier["warranty_status"]))
    validate.v_writable(body, ("action",))
    if action == "EXECUTE_WARRANTY":
        if supplier.get("warranty_scope") is None or \
                supplier.get("warranty_effective_from") is None:
            fail("ERR_INVALID_REQUEST",
                 "warranty_scope and warranty_effective_from must be stored before execution")
        supplier["warranty_status"] = "ACTIVE"
        db.touch(supplier)
    else:
        for notice in db.rows("notices"):
            if notice["status"] in WARRANTY_LIVE_NOTICE_STATUSES and \
                    money.warranty_window_covers(supplier, notice["served_at"]):
                fail("ERR_WARRANTY_IN_USE",
                     "the warranty window still covers a live notice of violation")
        supplier["warranty_status"] = "REVOKED"
        if supplier.get("warranty_effective_to") is None:
            supplier["warranty_effective_to"] = db.now()
        db.touch(supplier)
    return response.ok(db.serialize("suppliers", supplier))


@bp.route("/suppliers/<supplier_id>", methods=["GET"])
@guard("ComplianceAnalyst", "RegulatoryCounsel", "RegistryAdmin", "SupplierPortalUser")
def read_supplier(who, supplier_id):
    supplier = validate.must_exist("suppliers", supplier_id, "supplier")
    if who.role == "SupplierPortalUser" and who.user_id != supplier["id"]:
        fail("ERR_UNAUTHORIZED", "a supplier may read only its own row")
    return response.ok(db.serialize("suppliers", supplier))
