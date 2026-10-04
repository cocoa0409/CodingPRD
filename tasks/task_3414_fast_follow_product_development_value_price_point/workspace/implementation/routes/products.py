"""Products (PRD 3.3): commercialize a SELECTED concept; gated lifecycle
FORMULATION -> SOURCING -> COMPLIANCE_GATE -> LAUNCH_READY with a cyclic
reformulation loop and a kill path; parallel packaging_status dimension.
LAUNCHED and DISCONTINUED are cascade-only.
"""
from flask import Blueprint

from core.auth import authenticate, require_role
from core.constants import ROLE_PRODUCT_MANAGER
from core.envelope import pub, success_object
from core.errors import err, not_found
from core.pagination import list_response
from core.store import new_record, store, touch
from core.validate import get_body, opt_str, req_enum, req_str
from services import calc, cascade

bp = Blueprint("products", __name__)

STATUSES = (
    "FORMULATION",
    "SOURCING",
    "COMPLIANCE_GATE",
    "LAUNCH_READY",
    "LAUNCHED",
    "DISCONTINUED",
    "KILLED",
)
PACK_STATUSES = ("PACK_SOURCING", "PACK_READY")


@bp.post("/products")
def create_product():
    _, role = authenticate()
    require_role(role, ROLE_PRODUCT_MANAGER)
    body = get_body()
    concept_id = req_str(body, "concept_id")
    sku_name = req_str(body, "sku_name")
    tooling_code = opt_str(body, "tooling_code")
    concept = store.concepts.get(concept_id)
    if concept is None:
        raise not_found("ERR_CONCEPT_NOT_FOUND", "concept not found")
    if concept["status"] != "SELECTED":
        raise err(
            "ERR_CONCEPT_NOT_SELECTED", "the parent concept is not in SELECTED status"
        )
    rec = new_record(
        {
            "concept_id": concept_id,
            "sku_name": sku_name,
            "tooling_code": tooling_code,
            "status": "FORMULATION",
            "packaging_status": "PACK_SOURCING",
            "tooling_reuse": False,
            "packaging_lead_weeks": None,
            "successor_product_id": None,
            "launched_at": None,
        }
    )
    # Tooling reuse is computed once at creation (calculations.packaging_lead_time).
    rec["tooling_reuse"] = calc.detect_tooling_reuse(
        tooling_code, rec["created_at"], store.products.values()
    )
    rec["packaging_lead_weeks"] = calc.packaging_lead_weeks(rec["tooling_reuse"])
    store.products[rec["id"]] = rec
    # A successful creation moves the concept SELECTED -> IN_DEVELOPMENT.
    concept["status"] = "IN_DEVELOPMENT"
    touch(concept)
    return success_object(pub(rec), code=201)


@bp.get("/products")
def list_products():
    authenticate()
    return list_response(
        store.products.values(),
        {
            "concept_id": "concept_id",
            "successor_product_id": "successor_product_id",
            "status": "status",
            "tooling_code": "tooling_code",
        },
        pub,
    )


@bp.get("/products/<rid>")
def get_product(rid):
    authenticate()
    rec = store.products.get(rid)
    if rec is None:
        raise not_found("ERR_PRODUCT_NOT_FOUND", "product not found")
    return success_object(pub(rec))


def _has_approved_formula(product_id):
    return any(
        p["product_id"] == product_id and p["status"] == "APPROVED"
        for p in store.formula_projects.values()
    )


def _has_accepted_quote(product_id):
    return any(
        q["product_id"] == product_id and q["status"] == "ACCEPTED"
        for q in store.cost_quotes.values()
    )


@bp.patch("/products/<rid>")
def patch_product(rid):
    _, role = authenticate()
    require_role(role, ROLE_PRODUCT_MANAGER)
    body = get_body()
    target_status = None
    if "status" in body and body["status"] is not None:
        target_status = req_enum(body, "status", STATUSES)
    target_pack = None
    if "packaging_status" in body and body["packaging_status"] is not None:
        target_pack = req_enum(body, "packaging_status", PACK_STATUSES)
    rec = store.products.get(rid)
    if rec is None:
        raise not_found("ERR_PRODUCT_NOT_FOUND", "product not found")
    if target_status is None and target_pack is None:
        return success_object(pub(rec))

    # Validate both dimensions against the current record before mutating: a
    # failed combined update (e.g. packaging plus a status whose gate rejects)
    # leaves the record untouched and the version unbumped.
    new_pack = rec["packaging_status"]
    if target_pack is not None:
        # The parallel packaging dimension is applied first; it only moves
        # PACK_SOURCING -> PACK_READY and never back.
        if rec["packaging_status"] == "PACK_SOURCING" and target_pack == "PACK_READY":
            new_pack = "PACK_READY"
        else:
            raise err(
                "ERR_INVALID_STATE",
                "cannot transition packaging_status from %s to %s"
                % (rec["packaging_status"], target_pack),
            )

    new_status = rec["status"]
    run_reformulate = False
    run_kill = False
    if target_status is not None:
        current = rec["status"]
        if target_status == "SOURCING" and current == "FORMULATION":
            if not _has_approved_formula(rec["id"]):
                raise err(
                    "ERR_FORMULA_NOT_APPROVED",
                    "no APPROVED formula project exists for this product",
                )
            new_status = "SOURCING"
        elif target_status == "COMPLIANCE_GATE" and current == "SOURCING":
            if not _has_accepted_quote(rec["id"]):
                raise err(
                    "ERR_QUOTE_NOT_ACCEPTED",
                    "no ACCEPTED cost quote exists for this product",
                )
            new_status = "COMPLIANCE_GATE"
        elif target_status == "LAUNCH_READY" and current == "COMPLIANCE_GATE":
            if new_pack != "PACK_READY":
                raise err(
                    "ERR_INVALID_STATE",
                    "packaging_status must be PACK_READY before LAUNCH_READY",
                )
            if not cascade.dossier_compliant(rec["id"]):
                raise err(
                    "ERR_COMPLIANCE_GATE_FAILED",
                    "the product's compliance dossier is not fully compliant",
                )
            new_status = "LAUNCH_READY"
        elif target_status == "FORMULATION" and current in ("SOURCING", "COMPLIANCE_GATE"):
            new_status = "FORMULATION"
            run_reformulate = True
        elif target_status == "KILLED" and current in (
            "FORMULATION",
            "SOURCING",
            "COMPLIANCE_GATE",
        ):
            new_status = "KILLED"
            run_kill = True
        else:
            raise err(
                "ERR_INVALID_STATE",
                "cannot transition a product from %s to %s" % (current, target_status),
            )

    changed = False
    if new_pack != rec["packaging_status"]:
        rec["packaging_status"] = new_pack
        changed = True
    if new_status != rec["status"]:
        rec["status"] = new_status
        changed = True
        if run_reformulate:
            cascade.reformulate_product(rec)
        elif run_kill:
            cascade.kill_product(rec)

    if changed:
        touch(rec)
    return success_object(pub(rec))
