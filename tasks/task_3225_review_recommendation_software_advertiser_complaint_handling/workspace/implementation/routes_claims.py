"""Routes: page claims (submit, verify, approve, reject, list, get)."""
import secrets
from datetime import timedelta
from flask import Blueprint, request

from db import store
from errors import not_found, err
from middleware import require_roles
from response import ok, ok_list, paginate
from services import (
    stamp_common, touch, get_body, req_str, req_enum, pub,
    VERIFY_TTL_D,
)
from routes_pages import get_page

bp = Blueprint("claims", __name__)

CLAIM_ROLES = ("PlatformOps", "SupportAdmin", "BusinessOwner")


def get_claim(claim_id):
    c = store.claims.get(claim_id)
    if c is None:
        raise not_found("page claim not found")
    return c


@bp.post("/platform/business-pages/<pageId>/claims")
@require_roles("BusinessOwner")
def create_claim(pageId, _actor_id, _actor_role):
    page = get_page(pageId)
    body = get_body()
    kind = req_enum(body, "kind", ("CLAIM", "TRANSFER"))
    evidence_text = req_str(body, "evidence_text")
    # admissibility
    if page["status"] != "ACTIVE":
        raise err("ERR_CLAIM_CONFLICT", "page is not ACTIVE")
    if kind == "CLAIM" and page["claimed_by_user_id"] is not None:
        raise err("ERR_CLAIM_CONFLICT", "page is already claimed")
    if kind == "TRANSFER" and (page["claimed_by_user_id"] is None
                               or page["claimed_by_user_id"] == _actor_id):
        raise err("ERR_CLAIM_CONFLICT",
                  "TRANSFER requires the page claimed by someone other than claimant")
    for c in store.claims.values():
        if c["page_id"] == pageId and c["status"] in ("SUBMITTED", "VERIFIED"):
            raise err("ERR_CLAIM_CONFLICT", "an open claim already exists on the page")
    claim = stamp_common({
        "page_id": pageId,
        "claimant_user_id": _actor_id,
        "kind": kind,
        "evidence_text": evidence_text,
        "verification_code": secrets.token_hex(4),  # 8 hex chars
        "decided_by_admin_id": None,
        "status": "SUBMITTED",
    })
    claim["_created_dt"] = store.now
    store.claims[claim["id"]] = claim
    return ok(pub(claim), status=201)


@bp.get("/platform/page-claims")
@require_roles(*CLAIM_ROLES)
def list_claims(_actor_id, _actor_role):
    items = list(store.claims.values())
    for f in ("page_id", "claimant_user_id"):
        v = request.args.get(f)
        if v is not None:
            items = [c for c in items if c.get(f) == v]
    items, limit, offset, total = paginate([pub(c) for c in items], request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/page-claims/<claimId>")
@require_roles(*CLAIM_ROLES)
def get_one_claim(claimId, _actor_id, _actor_role):
    return ok(pub(get_claim(claimId)))


@bp.post("/platform/page-claims/<claimId>/verify")
@require_roles("BusinessOwner")
def verify_claim(claimId, _actor_id, _actor_role):
    claim = get_claim(claimId)
    body = get_body()
    code = body.get("verification_code")
    if not isinstance(code, str):
        raise err("ERR_INVALID_REQUEST", "verification_code is required")
    if claim["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "claim is not SUBMITTED")
    if claim["claimant_user_id"] != _actor_id:
        raise err("ERR_FORBIDDEN", "only the claimant may verify this claim")
    if (store.now > claim["_created_dt"] + timedelta(days=VERIFY_TTL_D)
            or code != claim["verification_code"]):
        raise err("ERR_VERIFICATION_EXPIRED",
                  "verification window expired or code mismatch")
    claim["status"] = "VERIFIED"
    touch(claim)
    return ok(pub(claim))


@bp.post("/platform/page-claims/<claimId>/approve")
@require_roles("SupportAdmin")
def approve_claim(claimId, _actor_id, _actor_role):
    claim = get_claim(claimId)
    body = get_body()
    epv = body.get("expected_page_version")
    if not isinstance(epv, int) or isinstance(epv, bool):
        raise err("ERR_INVALID_REQUEST", "expected_page_version is required")
    if claim["status"] != "VERIFIED":
        raise err("ERR_INVALID_STATE", "claim is not VERIFIED")
    page = store.pages[claim["page_id"]]
    # OCC
    if epv != page["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_page_version does not match current version")
    # re-check kind-aware admissibility
    if page["status"] != "ACTIVE":
        raise err("ERR_CLAIM_CONFLICT", "page is not ACTIVE")
    if claim["kind"] == "CLAIM" and page["claimed_by_user_id"] is not None:
        raise err("ERR_CLAIM_CONFLICT", "page is already claimed")
    if claim["kind"] == "TRANSFER" and (page["claimed_by_user_id"] is None
                                        or page["claimed_by_user_id"] == claim["claimant_user_id"]):
        raise err("ERR_CLAIM_CONFLICT",
                  "TRANSFER requires the page claimed by someone other than claimant")
    prior_owner = page["claimed_by_user_id"]
    claim["status"] = "APPROVED"
    claim["decided_by_admin_id"] = _actor_id
    touch(claim)
    page["claimed_by_user_id"] = claim["claimant_user_id"]
    touch(page)
    if claim["kind"] == "TRANSFER":
        # ad account reassign + suspend
        if page.get("ad_account_id"):
            acct = store.ad_accounts.get(page["ad_account_id"])
            if acct is not None:
                acct["owner_user_id"] = claim["claimant_user_id"]
                if acct["status"] != "CLOSED":
                    acct["status"] = "SUSPENDED"
                    for camp in store.campaigns.values():
                        if camp["ad_account_id"] == acct["id"] and camp["status"] == "ACTIVE":
                            camp["status"] = "PAUSED"
                            touch(camp)
                touch(acct)
        # prior owner's OPEN/UNDER_REVIEW complaints on this page -> REJECTED
        for comp in store.complaints.values():
            if (comp["page_id"] == page["id"]
                    and comp["filer_user_id"] == prior_owner
                    and comp["status"] in ("OPEN", "UNDER_REVIEW")):
                comp["status"] = "REJECTED"
                touch(comp)
    return ok(pub(claim))


@bp.post("/platform/page-claims/<claimId>/reject")
@require_roles("SupportAdmin")
def reject_claim(claimId, _actor_id, _actor_role):
    claim = get_claim(claimId)
    if claim["status"] != "VERIFIED":
        raise err("ERR_INVALID_STATE", "claim is not VERIFIED")
    claim["status"] = "REJECTED"
    claim["decided_by_admin_id"] = _actor_id
    touch(claim)
    return ok(pub(claim))
