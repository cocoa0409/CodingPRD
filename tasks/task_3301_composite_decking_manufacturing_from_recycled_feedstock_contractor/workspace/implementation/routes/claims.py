"""Warranty claims and claim samples."""
from datetime import date
from flask import Blueprint

import db as dbmod
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_CLAIM_OUT_OF_WARRANTY, ERR_FADE_COOLDOWN,
                    ERR_VERDICT_BLOCKS_APPROVAL, ERR_NO_SUPPORT_STOCK)
from middleware import require_roles
from services import calcs
from services.lookup import get_path, get_body_ref
from util import body, ok_object, ok_list, req_str, new_resource, touch, logical_now_iso

bp = Blueprint("claims", __name__)

CATEGORIES = ("FADING", "STAINING", "STRUCTURAL")
VERDICTS = ("CONFIRMS_DEFECT", "CONTRADICTS_CLAIM", "INCONCLUSIVE")
ADJUDICATIONS = ("REPLACEMENT", "CREDIT", "REPAIR")


@bp.post("/decking/warranty-claims")
@require_roles("Contractor", "ClaimsAdjuster")
def create_claim():
    data = body()
    reg = get_body_ref("install_registrations", data.get("install_registration_id"),
                       "install_registration_id")
    cat = req_str(data, "category")
    if cat not in CATEGORIES:
        raise_err(ERR_INVALID_REQUEST, f"category must be one of {CATEGORIES}")
    filed_date = data.get("filed_date")
    if filed_date is not None:
        if not isinstance(filed_date, str):
            raise_err(ERR_INVALID_REQUEST, "filed_date must be a date string")
        try:
            date.fromisoformat(filed_date)
        except ValueError:
            raise_err(ERR_INVALID_REQUEST, "filed_date must be a date string")
    claim = new_resource({
        "install_registration_id": reg["id"],
        "category": cat,
        "filed_at": logical_now_iso(),
        "filed_date": filed_date,
        "status": "FILED",
        "adjudication": None,
        "credit_amount_cents": None,
        "denial_reason": None,
    })
    dbmod.db.warranty_claims[claim["id"]] = claim
    return ok_object(dict(claim), status=201)


@bp.get("/decking/warranty-claims/<cid>")
@require_roles("ClaimsAdjuster", "Contractor", "ProgramAdmin")
def get_claim(cid):
    return ok_object(dict(get_path("warranty_claims", cid)))


@bp.get("/decking/install-registrations/<rid>/warranty-claims")
@require_roles("ClaimsAdjuster", "Contractor")
def registration_claims(rid):
    get_path("install_registrations", rid)
    items = [c for c in dbmod.db.warranty_claims.values() if c["install_registration_id"] == rid]
    return ok_list([dict(c) for c in items])


@bp.post("/decking/warranty-claims/<cid>/request-sample")
@require_roles("ClaimsAdjuster")
def request_sample(cid):
    claim = get_path("warranty_claims", cid)
    if claim["status"] != "FILED":
        raise_err(ERR_INVALID_STATE, f"claim is {claim['status']}")
    reg = dbmod.db.install_registrations[claim["install_registration_id"]]
    install_date = date.fromisoformat(reg["install_date"])
    filed_date = date.fromisoformat(claim.get("filed_date") or claim["filed_at"][:10])
    age_days = (filed_date - install_date).days
    if age_days > reg["warranty_years"] * 365:
        raise_err(ERR_CLAIM_OUT_OF_WARRANTY, "claim filed beyond warranty_years")
    if claim["category"] == "STAINING":
        if age_days > calcs.STAIN_MAX_YEARS * 365:
            raise_err(ERR_CLAIM_OUT_OF_WARRANTY, "stain coverage capped at 5 years")
    if claim["category"] == "FADING":
        lot = dbmod.db.board_lots.get(reg.get("board_lot_id"))
        line = dbmod.db.product_lines.get(reg["product_line_id"])
        frm = dbmod.db.formulations.get(line["formulation_id"]) if line else None
        if lot is not None and frm is not None \
                and lot["formulation_revision"] < frm["active_revision"] \
                and age_days < calcs.FADE_COOLDOWN_DAYS:
            raise_err(ERR_FADE_COOLDOWN,
                      "fade claim on legacy-revision boards before 180 days")
    claim["status"] = "SAMPLE_REQUESTED"
    touch(claim)
    sample = new_resource({
        "warranty_claim_id": claim["id"],
        "received_at": None,
        "lab_verdict": None,
        "status": "AWAITING",
    })
    dbmod.db.claim_samples[sample["id"]] = sample
    return ok_object(dict(claim))


@bp.post("/decking/warranty-claims/<cid>/adjudicate")
@require_roles("ClaimsAdjuster")
def adjudicate(cid):
    claim = get_path("warranty_claims", cid)
    if claim["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, f"claim is {claim['status']}")
    data = body()
    decision = data.get("decision")
    if decision not in ("approve", "deny", "APPROVE", "DENY"):
        raise_err(ERR_INVALID_REQUEST, "decision must be approve or deny")
    decision = decision.lower()
    if decision == "deny":
        reason = data.get("denial_reason")
        if not isinstance(reason, str) or not reason:
            raise_err(ERR_INVALID_REQUEST, "denial_reason is required for denial")
        claim["status"] = "DENIED"
        claim["denial_reason"] = reason
        touch(claim)
        return ok_object(dict(claim))
    # approve
    samples = [s for s in dbmod.db.claim_samples.values() if s["warranty_claim_id"] == cid]
    verdict = None
    for s in samples:
        if s["status"] == "REVIEWED":
            verdict = s["lab_verdict"]
    if verdict != "CONFIRMS_DEFECT":
        raise_err(ERR_VERDICT_BLOCKS_APPROVAL, "approve attempted without CONFIRMS_DEFECT verdict")
    adj = data.get("adjudication")
    if adj not in ADJUDICATIONS:
        raise_err(ERR_INVALID_REQUEST, f"adjudication must be one of {ADJUDICATIONS}")
    reg = dbmod.db.install_registrations[claim["install_registration_id"]]
    claim["adjudication"] = adj
    if adj == "CREDIT":
        credit = calcs.claim_credit_cents(reg, claim)
        claim["credit_amount_cents"] = credit
        dealer = dbmod.db.dealers[reg["dealer_id"]]
        dealer["outstanding_cents"] -= credit
        touch(dealer)
    elif adj == "REPLACEMENT":
        line_id = reg["product_line_id"]
        lots = [l for l in dbmod.db.board_lots.values()
                if l["product_line_id"] == line_id and l["disposition"] == "AVAILABLE"
                and l["support_tagged"]]
        if not lots:
            raise_err(ERR_NO_SUPPORT_STOCK, "replacement approved with no available support lot")
        lots.sort(key=lambda l: (l["produced_at"], l["created_at"], l["id"]))
        lot = lots[0]
        lot["disposition"] = "CONSUMED_BY_CLAIM"
        touch(lot)
    claim["status"] = "APPROVED"
    touch(claim)
    return ok_object(dict(claim))


@bp.get("/decking/warranty-claims/<cid>/samples")
@require_roles("ClaimsAdjuster")
def claim_samples(cid):
    get_path("warranty_claims", cid)
    items = [s for s in dbmod.db.claim_samples.values() if s["warranty_claim_id"] == cid]
    return ok_list([dict(s) for s in items])


@bp.get("/decking/claim-samples/<sid>")
@require_roles("ClaimsAdjuster")
def get_sample(sid):
    return ok_object(dict(get_path("claim_samples", sid)))


@bp.post("/decking/claim-samples/<sid>/receive")
@require_roles("ClaimsAdjuster")
def receive_sample(sid):
    s = get_path("claim_samples", sid)
    if s["status"] != "AWAITING":
        raise_err(ERR_INVALID_STATE, f"sample is {s['status']}")
    s["status"] = "RECEIVED"
    s["received_at"] = logical_now_iso()
    touch(s)
    return ok_object(dict(s))


@bp.post("/decking/claim-samples/<sid>/review")
@require_roles("ClaimsAdjuster")
def review_sample(sid):
    s = get_path("claim_samples", sid)
    if s["status"] != "RECEIVED":
        raise_err(ERR_INVALID_STATE, f"sample is {s['status']}")
    data = body()
    verdict = data.get("lab_verdict")
    if verdict not in VERDICTS:
        raise_err(ERR_INVALID_REQUEST, f"lab_verdict must be one of {VERDICTS}")
    s["lab_verdict"] = verdict
    s["status"] = "REVIEWED"
    touch(s)
    claim = dbmod.db.warranty_claims[s["warranty_claim_id"]]
    if claim["status"] == "SAMPLE_REQUESTED":
        claim["status"] = "UNDER_REVIEW"
        touch(claim)
    return ok_object(dict(s))
