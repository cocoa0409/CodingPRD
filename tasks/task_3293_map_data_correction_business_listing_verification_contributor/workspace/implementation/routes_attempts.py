"""VerificationAttempt endpoints."""
import random
from datetime import timedelta
from flask import Blueprint, request

import clock
import domain
import store
from errors import raise_err
from response import envelope, require_roles, body, paginate
from services_listings import create_grant, suspend_listing
from validation import require_fields, require_enum, get_or_404

bp = Blueprint("attempts", __name__)

METHODS = {"POSTCARD", "PHONE", "VIDEO", "RECORDS"}
READ_ROLES = {"PlatformAdmin", "BusinessOwner", "Moderator", "PolicyAnalyst"}


@bp.post("/v1/verification-attempts")
def create_attempt():
    role, uid = require_roles({"BusinessOwner"})
    data = body()
    require_fields(data, ["listing_id", "method"])
    l = store.listings.get(data["listing_id"])
    if l is None:
        raise_err("ERR_NOT_FOUND", "listing not found")
    method = require_enum(data, "method", METHODS)
    if l["status"] not in ("CLAIM_PENDING", "REVERIFY_REQUIRED"):
        raise_err("ERR_LISTING_NOT_VERIFIABLE", "listing not verifiable")
    if l.get("owner_contributor_id") != uid:
        raise_err("ERR_NOT_LISTING_OWNER", "only the listing owner may verify")

    now = clock.now()
    # cooldown: most recent FAILED attempt updated < 72h ago
    failed = [a for a in store.attempts.values()
              if a["listing_id"] == l["id"] and a["status"] == "FAILED"]
    if failed:
        last = max(failed, key=lambda a: (a["updated_at"], a["id"]))
        if now < clock.parse(last["updated_at"]) + timedelta(hours=72):
            raise_err("ERR_VERIFICATION_COOLDOWN", "within 72h of last failure")
    # 30-day cap
    cutoff = now - timedelta(days=30)
    attempts_30d = sum(1 for a in store.attempts.values()
                       if a["listing_id"] == l["id"]
                       and clock.parse(a["created_at"]) >= cutoff)
    if attempts_30d >= 5:
        raise_err("ERR_TOO_MANY_ATTEMPTS", "too many attempts in 30 days")

    code = "%06d" % random.randint(0, 999999)
    rec = {
        "id": domain.new_id(),
        "listing_id": l["id"],
        "method": method,
        "status": "ISSUED",
        "code": code,
        "attempts_used": 0,
        "max_attempts": 3,
        "issued_at": clock.iso(now),
        "expires_at": clock.iso(now + timedelta(days=14)),
        "failure_reason": None,
        "created_at": clock.iso(now),
        "updated_at": clock.iso(now),
        "version": 1,
    }
    store.attempts[rec["id"]] = rec
    return envelope(domain.attempt_view(rec), status=201)


@bp.get("/v1/verification-attempts")
def list_attempts():
    require_roles(READ_ROLES)
    items = list(store.attempts.values())
    for f in ("listing_id", "status", "method"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    page, pg = paginate(items, request.args)
    return envelope([domain.attempt_view(a) for a in page],
                    response_type="array", pagination=pg)


@bp.get("/v1/verification-attempts/<aid>")
def get_attempt(aid):
    require_roles(READ_ROLES)
    a = get_or_404(store.attempts, aid)
    return envelope(domain.attempt_view(a))


@bp.post("/v1/verification-attempts/<aid>/submit-code")
def submit_code(aid):
    role, uid = require_roles({"BusinessOwner"})
    a = get_or_404(store.attempts, aid)
    l = store.listings.get(a["listing_id"])
    data = body()
    require_fields(data, ["code"])
    if a["status"] not in ("ISSUED", "CODE_SUBMITTED"):
        raise_err("ERR_INVALID_STATE", "attempt not submittable")
    if l is None or l.get("owner_contributor_id") != uid:
        raise_err("ERR_NOT_LISTING_OWNER", "only the listing owner may submit")
    now = clock.now()
    if now >= clock.parse(a["expires_at"]):
        raise_err("ERR_ATTEMPT_EXPIRED", "attempt expired")
    if l["status"] not in ("CLAIM_PENDING", "REVERIFY_REQUIRED"):
        raise_err("ERR_LISTING_NOT_VERIFIABLE", "listing not verifiable")
    if a["attempts_used"] >= a["max_attempts"]:
        raise_err("ERR_ATTEMPTS_EXHAUSTED", "no attempts remaining")

    a["attempts_used"] += 1
    if data["code"] == a["code"]:
        a["status"] = "VERIFIED"
        domain.touch(a)
        # listing cascade
        l["status"] = "VERIFIED"
        l["verification_method"] = a["method"]
        l["verified_at"] = clock.iso(now)
        l["reverify_due_at"] = clock.iso(now + timedelta(days=365))
        domain.recompute_listing(l)
        domain.touch(l)
        # owner grant
        owner = store.contributors.get(l["owner_contributor_id"])
        if owner is not None:
            create_grant(owner["id"], "VERIFICATION_ASSIST", a["id"], 10, 1.0)
            domain.recompute_contributor(owner, demote=True)
        return envelope(domain.attempt_view(a))

    # wrong code
    if a["attempts_used"] >= a["max_attempts"]:
        a["status"] = "FAILED"
        a["failure_reason"] = "WRONG_CODE"
        domain.touch(a)
        owner = store.contributors.get(l.get("owner_contributor_id"))
        if owner is not None:
            domain.recompute_contributor(owner, demote=False)
            if owner["failed_verification_count"] >= 5 \
                    and l["status"] in ("CLAIM_PENDING", "VERIFIED", "REVERIFY_REQUIRED"):
                suspend_listing(l, "FAKE_ADDRESS",
                                "auto-suspension after 5 failed verifications",
                                "system")
        return envelope(domain.attempt_view(a))
    a["status"] = "CODE_SUBMITTED"
    domain.touch(a)
    return envelope(domain.attempt_view(a))


@bp.post("/v1/verification-attempts/<aid>/cancel")
def cancel_attempt(aid):
    role, uid = require_roles({"BusinessOwner"})
    a = get_or_404(store.attempts, aid)
    l = store.listings.get(a["listing_id"])
    if l is None or l.get("owner_contributor_id") != uid:
        raise_err("ERR_NOT_LISTING_OWNER", "only the listing owner may cancel")
    if a["status"] != "ISSUED":
        raise_err("ERR_INVALID_STATE", "only ISSUED attempts can be cancelled")
    a["status"] = "CANCELLED"
    domain.touch(a)
    return envelope(domain.attempt_view(a))
