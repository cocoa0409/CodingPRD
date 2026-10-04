"""Compliance dossiers (PRD 3.6): one per product; four independent state
dimensions (ingredient / claim / certification / registration), each advanced
exactly one step per review call. Cert CERTIFIED stamps cert_expires_at;
DENIED (and lazy LAPSED) fire the product-reversion cascade.
"""
from flask import Blueprint

from core.auth import authenticate, require_role
from core.constants import ROLE_COMPLIANCE_OFFICER
from core.envelope import pub, success_object
from core.errors import bad_request, err, not_found
from core.pagination import list_response
from core.store import new_record, store, touch
from core.validate import get_body, opt_str, opt_str_list, req_enum, req_str
from services import cascade

bp = Blueprint("compliance", __name__)

DIMENSIONS = ("INGREDIENT", "CLAIM", "CERTIFICATION", "REGISTRATION")
OUTCOMES = {
    "INGREDIENT": ("CLEARED", "BLOCKED"),
    "CLAIM": ("SUBSTANTIATED", "BLOCKED"),
    "CERTIFICATION": ("APPLIED", "AUDITING", "CERTIFIED", "DENIED"),
    "REGISTRATION": ("FILED", "REGISTERED", "REJECTED"),
}


def _pub_dossier(rec):
    data = pub(rec)
    data["compliant"] = (
        rec["ingredient_status"] == "CLEARED"
        and rec["claim_status"] == "SUBSTANTIATED"
        and rec["cert_status"] == "CERTIFIED"
        and rec["registration_status"] == "REGISTERED"
    )
    return data


@bp.post("/compliance-dossiers")
def create_dossier():
    _, role = authenticate()
    require_role(role, ROLE_COMPLIANCE_OFFICER)
    body = get_body()
    product_id = req_str(body, "product_id")
    if product_id not in store.products:
        raise not_found("ERR_PRODUCT_NOT_FOUND", "product not found")
    for existing in store.dossiers.values():
        if existing["product_id"] == product_id:
            raise err(
                "ERR_DOSSIER_ALREADY_EXISTS",
                "a compliance dossier already exists for this product",
            )
    rec = new_record(
        {
            "product_id": product_id,
            "ingredient_status": "PENDING",
            "blocked_ingredients": [],
            "claim_status": "PENDING",
            "cert_status": "NOT_APPLIED",
            "cert_expires_at": None,
            "registration_status": "UNFILED",
        }
    )
    store.dossiers[rec["id"]] = rec
    return success_object(_pub_dossier(rec), code=201)


@bp.get("/compliance-dossiers")
def list_dossiers():
    authenticate()
    for dossier in store.dossiers.values():
        cascade.eval_cert_lapse(dossier)
    return list_response(
        store.dossiers.values(),
        {"product_id": "product_id", "cert_status": "cert_status"},
        _pub_dossier,
    )


@bp.get("/compliance-dossiers/<rid>")
def get_dossier(rid):
    authenticate()
    rec = store.dossiers.get(rid)
    if rec is None:
        raise not_found("ERR_DOSSIER_NOT_FOUND", "compliance dossier not found")
    cascade.eval_cert_lapse(rec)
    return success_object(_pub_dossier(rec))


@bp.post("/compliance-dossiers/<rid>/reviews")
def post_review(rid):
    _, role = authenticate()
    require_role(role, ROLE_COMPLIANCE_OFFICER)
    body = get_body()
    dimension = req_enum(body, "dimension", DIMENSIONS)
    outcome = req_enum(body, "outcome", OUTCOMES[dimension])
    blocked_items = opt_str_list(body, "blocked_items")
    opt_str(body, "notes")  # accepted, informational
    rec = store.dossiers.get(rid)
    if rec is None:
        raise not_found("ERR_DOSSIER_NOT_FOUND", "compliance dossier not found")
    # Writing the dossier evaluates the lazy certification lapse first.
    cascade.eval_cert_lapse(rec)

    if dimension == "INGREDIENT":
        current = rec["ingredient_status"]
        if outcome == "CLEARED" and current in ("PENDING", "BLOCKED"):
            rec["ingredient_status"] = "CLEARED"
            rec["blocked_ingredients"] = []
        elif outcome == "BLOCKED" and current in ("PENDING", "BLOCKED"):
            rec["ingredient_status"] = "BLOCKED"
            rec["blocked_ingredients"] = list(blocked_items or [])
        else:
            raise err(
                "ERR_INVALID_STATE",
                "cannot apply INGREDIENT outcome %s from %s" % (outcome, current),
            )
    elif dimension == "CLAIM":
        current = rec["claim_status"]
        if outcome == "SUBSTANTIATED" and current in ("PENDING", "BLOCKED"):
            rec["claim_status"] = "SUBSTANTIATED"
        elif outcome == "BLOCKED" and current in ("PENDING", "BLOCKED"):
            rec["claim_status"] = "BLOCKED"
        else:
            raise err(
                "ERR_INVALID_STATE",
                "cannot apply CLAIM outcome %s from %s" % (outcome, current),
            )
    elif dimension == "CERTIFICATION":
        current = rec["cert_status"]
        if outcome == "APPLIED" and current == "NOT_APPLIED":
            rec["cert_status"] = "APPLIED"
        elif outcome == "AUDITING" and current == "APPLIED":
            rec["cert_status"] = "AUDITING"
        elif outcome == "CERTIFIED" and current == "AUDITING":
            cascade.certify(rec)
        elif outcome == "DENIED" and current == "AUDITING":
            rec["cert_status"] = "DENIED"
            cascade.cert_reversion_cascade(rec)
        else:
            raise err(
                "ERR_INVALID_STATE",
                "cannot apply CERTIFICATION outcome %s from %s" % (outcome, current),
            )
    else:  # REGISTRATION
        current = rec["registration_status"]
        if outcome == "FILED" and current == "UNFILED":
            rec["registration_status"] = "FILED"
        elif outcome == "REGISTERED" and current in ("FILED", "REJECTED"):
            rec["registration_status"] = "REGISTERED"
        elif outcome == "REJECTED" and current == "FILED":
            rec["registration_status"] = "REJECTED"
        else:
            raise err(
                "ERR_INVALID_STATE",
                "cannot apply REGISTRATION outcome %s from %s" % (outcome, current),
            )
    touch(rec)
    return success_object(_pub_dossier(rec))
