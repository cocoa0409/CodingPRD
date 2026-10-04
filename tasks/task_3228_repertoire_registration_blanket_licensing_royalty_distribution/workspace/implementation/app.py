"""Flask app: Repertoire Licensing & Royalty API. All routes under /pro."""
import os
from datetime import date, timedelta

from flask import Flask, request

from store import (
    DB,
    CLOCK,
    ApiError,
    err,
    new_resource,
    touch,
    success_object,
    success_list,
    error_response,
    now_iso,
)
from helpers import (
    auth,
    require_role,
    get_json,
    parse_limit_offset,
    paginate,
    parse_iso_date,
    parse_iso_datetime,
    require_enum,
    require_int,
    require_str,
    clock_date,
)
import calcs

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(err("ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(err("ERR_NOT_FOUND", "Resource not found"))


# ---------------------------------------------------------------------------
# shared lookups
# ---------------------------------------------------------------------------


def get_or_404(collection, rid):
    r = DB[collection].get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", f"{collection} resource not found")
    return r


def expire_licenses_for_clock():
    """Expiry sweep: ACTIVE/DISPUTED licenses with expiry_date < clock date -> EXPIRED."""
    today = clock_date()
    for lic in DB["licenses"].values():
        if lic["status"] in ("ACTIVE", "DISPUTED"):
            if date.fromisoformat(lic["expiry_date"]) < today:
                lic["status"] = "EXPIRED"
                touch(lic)


def maybe_expire_license(lic):
    if lic["status"] in ("ACTIVE", "DISPUTED"):
        if date.fromisoformat(lic["expiry_date"]) < clock_date():
            lic["status"] = "EXPIRED"
            touch(lic)
    return lic


def recompute_work_aggregate(work):
    total = 0
    for c in DB["share_claims"].values():
        if c["work_id"] == work["id"] and c["status"] == "ACCEPTED":
            total += c["interest_share_bps"]
    work["aggregate_interest_bps"] = total
    return total


def work_has_disputed(work_id):
    return any(
        c["work_id"] == work_id and c["status"] == "DISPUTED"
        for c in DB["share_claims"].values()
    )


def settle_license_after_dispute(license_id, settled_fee):
    """DISPUTED -> ACTIVE (unless EXPIRED), update licensee blanket fee."""
    lic = DB["licenses"].get(license_id)
    if lic is None:
        return
    licensee = DB["licensees"].get(lic["licensee_id"])
    if lic["status"] == "DISPUTED":
        lic["status"] = "ACTIVE"
        touch(lic)
    if licensee is not None:
        if licensee["blanket_fee_cents"] != settled_fee:
            licensee["blanket_fee_cents"] = settled_fee
            licensee["settled_fee_cents"] = settled_fee
            touch(licensee)
        else:
            licensee["settled_fee_cents"] = settled_fee


# ---------------------------------------------------------------------------
# clock
# ---------------------------------------------------------------------------


@app.post("/pro/_clock/set_current_utc")
def set_clock():
    _, role = auth()
    require_role(role, {"ProSystemAdmin"})
    body = get_json()
    to = parse_iso_datetime(body.get("to_iso8601"), "to_iso8601")
    CLOCK.set(to)
    expire_licenses_for_clock()
    return success_object({})


# ---------------------------------------------------------------------------
# affiliates
# ---------------------------------------------------------------------------

AFFILIATE_STATUSES = {"ACTIVE", "SUSPENDED", "TERMINATED"}
PARTY_TYPES = {"SONGWRITER", "PUBLISHER"}


@app.post("/pro/affiliates")
def create_affiliate():
    _, role = auth()
    require_role(role, {"ProRegistrar"})
    body = get_json()
    legal_name = require_str(body.get("legal_name"), "legal_name")
    party_type = require_enum(body.get("party_type"), PARTY_TYPES, "party_type")
    code = require_str(body.get("affiliation_code"), "affiliation_code")
    for a in DB["affiliates"].values():
        if a["affiliation_code"] == code:
            raise err("ERR_VALIDATION", "affiliation_code must be unique")
    aff = new_resource(
        {
            "legal_name": legal_name,
            "party_type": party_type,
            "affiliation_code": code,
            "status": "ACTIVE",
            "royalty_balance_cents": 0,
            "total_paid_cents": 0,
        }
    )
    DB["affiliates"][aff["id"]] = aff
    return success_object(aff, 201)


@app.get("/pro/affiliates")
def list_affiliates():
    _, role = auth()
    require_role(
        role,
        {
            "ProRegistrar",
            "ProLicensingAdmin",
            "RoyaltyDistributor",
            "FinanceOfficer",
            "RateCourtOfficer",
        },
    )
    limit, offset = parse_limit_offset()
    items = list(DB["affiliates"].values())
    pt = request.args.get("party_type")
    if pt:
        items = [a for a in items if a["party_type"] == pt]
    st = request.args.get("status")
    if st:
        items = [a for a in items if a["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/affiliates/<rid>")
def get_affiliate(rid):
    user_id, role = auth()
    require_role(
        role, {"ProRegistrar", "RoyaltyDistributor", "FinanceOfficer", "Publisher", "Songwriter"}
    )
    aff = get_or_404("affiliates", rid)
    if role in ("Publisher", "Songwriter") and aff["id"] != user_id:
        raise err("ERR_FORBIDDEN", "Affiliates may only read their own record")
    return success_object(aff)


@app.patch("/pro/affiliates/<rid>")
def patch_affiliate(rid):
    _, role = auth()
    require_role(role, {"ProRegistrar"})
    aff = get_or_404("affiliates", rid)
    body = get_json()
    changed = False
    if "legal_name" in body:
        aff["legal_name"] = require_str(body["legal_name"], "legal_name")
        changed = True
    if "status" in body:
        aff["status"] = require_enum(body["status"], AFFILIATE_STATUSES, "status")
        changed = True
    if changed:
        touch(aff)
    return success_object(aff)


# ---------------------------------------------------------------------------
# works
# ---------------------------------------------------------------------------

WORK_STATUSES = {"REGISTERED", "IN_CONFLICT", "CONFIRMED", "WITHDRAWN"}


@app.post("/pro/works")
def create_work():
    user_id, role = auth()
    require_role(role, {"Publisher"})
    body = get_json()
    title = require_str(body.get("title"), "title")
    alt = body.get("alternate_titles", [])
    if alt is None:
        alt = []
    if not isinstance(alt, list) or any(not isinstance(t, str) for t in alt):
        raise err("ERR_VALIDATION", "alternate_titles must be a list of strings")
    reg_by = body.get("registered_by_affiliate_id")
    if not isinstance(reg_by, str) or not reg_by:
        raise err("ERR_VALIDATION", "registered_by_affiliate_id is required")
    aff = DB["affiliates"].get(reg_by)
    if aff is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "registered_by_affiliate_id does not exist")
    work = new_resource(
        {
            "title": title,
            "alternate_titles": list(alt),
            "registered_by_affiliate_id": reg_by,
            "status": "REGISTERED",
            "confirmed_at": None,
            "aggregate_interest_bps": 0,
        }
    )
    DB["works"][work["id"]] = work
    return success_object(work, 201)


@app.get("/pro/works")
def list_works():
    _, role = auth()
    require_role(role, {"ProRegistrar", "RoyaltyDistributor", "Publisher", "Songwriter"})
    limit, offset = parse_limit_offset()
    items = list(DB["works"].values())
    st = request.args.get("status")
    if st:
        items = [w for w in items if w["status"] == st]
    rb = request.args.get("registered_by_affiliate_id")
    if rb:
        items = [w for w in items if w["registered_by_affiliate_id"] == rb]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/works/<wid>")
def get_work(wid):
    _, role = auth()
    require_role(role, {"ProRegistrar", "RoyaltyDistributor", "Publisher", "Songwriter"})
    work = get_or_404("works", wid)
    return success_object(work)


@app.post("/pro/works/<wid>/confirm")
def confirm_work(wid):
    _, role = auth()
    require_role(role, {"ProRegistrar"})
    work = get_or_404("works", wid)
    if work["status"] != "REGISTERED":
        raise err("ERR_INVALID_STATE", "Work must be REGISTERED to confirm")
    if work["aggregate_interest_bps"] > 10000 or work_has_disputed(work["id"]):
        raise err(
            "ERR_WORK_SHARES_INCOMPLETE",
            "aggregate_interest_bps exceeds 10000 or DISPUTED claims remain",
        )
    has_accepted = any(
        c["work_id"] == work["id"] and c["status"] == "ACCEPTED"
        for c in DB["share_claims"].values()
    )
    if not has_accepted:
        raise err("ERR_WORK_SHARES_INCOMPLETE", "no ACCEPTED share claim exists")
    work["status"] = "CONFIRMED"
    work["confirmed_at"] = now_iso()
    touch(work)
    return success_object(work)


@app.post("/pro/works/<wid>/withdraw")
def withdraw_work(wid):
    user_id, role = auth()
    require_role(role, {"Publisher"})
    work = get_or_404("works", wid)
    # ownership (part of authorization)
    if work["registered_by_affiliate_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Only the registering publisher may withdraw the work")
    caller_aff = DB["affiliates"].get(user_id)
    if caller_aff is None or caller_aff["party_type"] != "PUBLISHER":
        raise err("ERR_FORBIDDEN", "Caller must be a PUBLISHER affiliate")
    # state check: only REGISTERED or IN_CONFLICT may withdraw
    if work["status"] not in ("REGISTERED", "IN_CONFLICT"):
        raise err("ERR_INVALID_STATE", "Work cannot be withdrawn from its current status")
    # no ACCEPTED performance references the work
    for e in DB["performances"].values():
        if e["work_id"] == work["id"] and e["status"] == "ACCEPTED":
            raise err("ERR_WORK_HAS_PERFORMANCES", "ACCEPTED performances reference the work")
    was_conflict = work["status"] == "IN_CONFLICT"
    work["status"] = "WITHDRAWN"
    for c in DB["share_claims"].values():
        if c["work_id"] == work["id"] and c["status"] != "REVOKED":
            c["status"] = "REVOKED"
            touch(c)
    if was_conflict:
        work["aggregate_interest_bps"] = 0
    else:
        recompute_work_aggregate(work)
    touch(work)
    return success_object(work)


@app.post("/pro/works/<wid>/resolve-conflict")
def resolve_conflict(wid):
    _, role = auth()
    require_role(role, {"ProRegistrar"})
    work = get_or_404("works", wid)
    if work["status"] != "IN_CONFLICT":
        raise err("ERR_INVALID_STATE", "Work is not IN_CONFLICT")
    body = get_json()
    # OCC
    expected = body.get("expected_work_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err("ERR_VALIDATION", "expected_work_version must be an integer")
        if expected != work["version"]:
            raise err("ERR_STALE_VERSION", "Work version has advanced")
    accept_ids = body.get("accept_claim_ids") or []
    revoke_ids = body.get("revoke_claim_ids") or []
    if not isinstance(accept_ids, list) or not isinstance(revoke_ids, list):
        raise err(
            "ERR_CONFLICT_RESOLUTION_INVALID", "accept/revoke lists must be arrays"
        )
    claims_of_work = [
        c for c in DB["share_claims"].values() if c["work_id"] == work["id"]
    ]
    disputed = {c["id"] for c in claims_of_work if c["status"] == "DISPUTED"}
    listed = set(accept_ids) | set(revoke_ids)
    both = set(accept_ids) & set(revoke_ids)
    # every listed id must belong to this work
    work_claim_ids = {c["id"] for c in claims_of_work}
    if not listed.issubset(work_claim_ids) or both:
        raise err(
            "ERR_CONFLICT_RESOLUTION_INVALID",
            "ids must belong to this work and appear in exactly one list",
        )
    # every DISPUTED claim must appear exactly once
    if disputed != listed:
        raise err(
            "ERR_CONFLICT_RESOLUTION_INVALID",
            "every DISPUTED claim must be disposed exactly once",
        )
    # apply disposition
    for cid in accept_ids:
        DB["share_claims"][cid]["status"] = "ACCEPTED"
        touch(DB["share_claims"][cid])
    for cid in revoke_ids:
        DB["share_claims"][cid]["status"] = "REVOKED"
        touch(DB["share_claims"][cid])
    agg = recompute_work_aggregate(work)
    if agg > 10000:
        # roll back
        for cid in accept_ids:
            DB["share_claims"][cid]["status"] = "DISPUTED"
            touch(DB["share_claims"][cid])
        for cid in revoke_ids:
            DB["share_claims"][cid]["status"] = "DISPUTED"
            touch(DB["share_claims"][cid])
        recompute_work_aggregate(work)
        raise err(
            "ERR_CONFLICT_RESOLUTION_INVALID",
            "post-resolution aggregate_interest_bps exceeds 10000",
        )
    work["status"] = "CONFIRMED"
    work["confirmed_at"] = now_iso()
    touch(work)
    return success_object(work)


# ---------------------------------------------------------------------------
# share claims
# ---------------------------------------------------------------------------

CLAIM_ROLES = {"WRITER", "PUBLISHER"}
CLAIM_STATUSES = {"SUBMITTED", "ACCEPTED", "DISPUTED", "REVOKED"}


@app.post("/pro/works/<wid>/share-claims")
def create_share_claim(wid):
    user_id, role = auth()
    require_role(role, {"Publisher", "Songwriter"})
    work = get_or_404("works", wid)
    body = get_json()
    affiliate_id = body.get("affiliate_id")
    if not isinstance(affiliate_id, str) or not affiliate_id:
        raise err("ERR_VALIDATION", "affiliate_id is required")
    aff = DB["affiliates"].get(affiliate_id)
    if aff is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "affiliate_id does not exist")
    claim_role = require_enum(body.get("role"), CLAIM_ROLES, "role")
    collection_bps = require_int(body.get("collection_share_bps"), "collection_share_bps")
    interest_bps = require_int(body.get("interest_share_bps"), "interest_share_bps")
    if not (1 <= collection_bps <= 10000) or not (1 <= interest_bps <= 10000):
        raise err("ERR_INVALID_SHARE", "share bps must be within 1..10000")
    # ownership: caller claims only own affiliate
    if affiliate_id != user_id:
        raise err("ERR_FORBIDDEN", "Callers may only assert claims for their own affiliate")
    # duplicate non-REVOKED claim for (work, affiliate, role)
    for c in DB["share_claims"].values():
        if (
            c["work_id"] == work["id"]
            and c["affiliate_id"] == affiliate_id
            and c["role"] == claim_role
            and c["status"] != "REVOKED"
        ):
            raise err(
                "ERR_INVALID_SHARE",
                "duplicate non-REVOKED claim for (work, affiliate, role)",
            )
    claim = new_resource(
        {
            "work_id": work["id"],
            "affiliate_id": affiliate_id,
            "role": claim_role,
            "collection_share_bps": collection_bps,
            "interest_share_bps": interest_bps,
            "status": "SUBMITTED",
        }
    )
    DB["share_claims"][claim["id"]] = claim
    # conflict check: simulate including this claim
    current_accepted = work["aggregate_interest_bps"]
    if current_accepted + interest_bps <= 10000:
        claim["status"] = "ACCEPTED"
        claim["updated_at"] = now_iso()
        recompute_work_aggregate(work)
        if work["status"] == "IN_CONFLICT" and not work_has_disputed(work["id"]):
            work["status"] = "REGISTERED"
        touch(work)
    else:
        claim["status"] = "DISPUTED"
        claim["updated_at"] = now_iso()
        if work["status"] == "REGISTERED":
            work["status"] = "IN_CONFLICT"
        touch(work)
    return success_object(claim, 201)


@app.get("/pro/works/<wid>/share-claims")
def list_work_claims(wid):
    _, role = auth()
    require_role(role, {"ProRegistrar", "RoyaltyDistributor", "Publisher", "Songwriter"})
    work = get_or_404("works", wid)
    limit, offset = parse_limit_offset()
    items = [c for c in DB["share_claims"].values() if c["work_id"] == work["id"]]
    st = request.args.get("status")
    if st:
        items = [c for c in items if c["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/share-claims")
def list_share_claims():
    _, role = auth()
    require_role(role, {"ProRegistrar", "RoyaltyDistributor"})
    limit, offset = parse_limit_offset()
    items = list(DB["share_claims"].values())
    wid = request.args.get("work_id")
    if wid:
        items = [c for c in items if c["work_id"] == wid]
    aid = request.args.get("affiliate_id")
    if aid:
        items = [c for c in items if c["affiliate_id"] == aid]
    st = request.args.get("status")
    if st:
        items = [c for c in items if c["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/affiliates/<aid>/share-claims")
def list_affiliate_claims(aid):
    _, role = auth()
    require_role(role, {"ProRegistrar", "RoyaltyDistributor", "Publisher", "Songwriter"})
    get_or_404("affiliates", aid)
    limit, offset = parse_limit_offset()
    items = [c for c in DB["share_claims"].values() if c["affiliate_id"] == aid]
    st = request.args.get("status")
    if st:
        items = [c for c in items if c["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.post("/pro/share-claims/<cid>/revoke")
def revoke_claim(cid):
    user_id, role = auth()
    require_role(role, {"Publisher", "Songwriter"})
    claim = get_or_404("share_claims", cid)
    if claim["status"] not in ("ACCEPTED", "SUBMITTED", "DISPUTED"):
        raise err("ERR_INVALID_STATE", "Claim cannot be revoked from its current status")
    if claim["affiliate_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Only the claim owner may revoke the claim")
    # locked by FINALIZED-or-later statement for the claim's work
    locked_works = set()
    for st in DB["statements"].values():
        if st["status"] in ("FINALIZED", "PAID", "ADJUSTED"):
            cyc = DB["cycles"].get(st["cycle_id"])
            if cyc is None:
                continue
            for e in DB["performances"].values():
                if (
                    e["cycle_id"] == cyc["id"]
                    and e["status"] in ("ACCEPTED", "VOIDED")
                    and e["work_id"] == claim["work_id"]
                ):
                    locked_works.add(claim["work_id"])
    if claim["work_id"] in locked_works:
        raise err(
            "ERR_CLAIM_LOCKED_BY_DISTRIBUTION",
            "a FINALIZED-or-later statement routed royalties on this claim",
        )
    claim["status"] = "REVOKED"
    touch(claim)
    work = DB["works"].get(claim["work_id"])
    if work is not None:
        recompute_work_aggregate(work)
        if (
            work["status"] == "IN_CONFLICT"
            and not work_has_disputed(work["id"])
            and work["aggregate_interest_bps"] <= 10000
        ):
            work["status"] = "REGISTERED"
        touch(work)
    return success_object(claim)


@app.post("/pro/share-claims/<cid>/dispute")
def dispute_claim(cid):
    user_id, role = auth()
    require_role(role, {"Publisher", "Songwriter"})
    claim = get_or_404("share_claims", cid)
    if claim["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Only an ACCEPTED claim can be disputed")
    if claim["affiliate_id"] == user_id:
        raise err("ERR_FORBIDDEN", "Cannot dispute your own claim")
    # caller must hold a non-REVOKED claim on the same work
    holds = any(
        c["work_id"] == claim["work_id"]
        and c["affiliate_id"] == user_id
        and c["status"] != "REVOKED"
        for c in DB["share_claims"].values()
    )
    if not holds:
        raise err(
            "ERR_FORBIDDEN", "Caller must hold a non-REVOKED claim on the same work"
        )
    claim["status"] = "DISPUTED"
    touch(claim)
    work = DB["works"].get(claim["work_id"])
    if work is not None:
        work["status"] = "IN_CONFLICT"
        recompute_work_aggregate(work)
        touch(work)
    return success_object(claim)


# ---------------------------------------------------------------------------
# licensees
# ---------------------------------------------------------------------------

LICENSEE_CATEGORIES = {"BROADCASTER", "DIGITAL_SERVICE", "VENUE"}


def compute_and_set_fee(licensee):
    engine_fee = calcs.fee_engine(
        licensee["category"],
        licensee["reported_revenue_cents"],
        licensee["usage_units"],
    )
    settled = licensee.get("settled_fee_cents")
    if settled is not None:
        licensee["blanket_fee_cents"] = max(engine_fee, settled)
    else:
        licensee["blanket_fee_cents"] = engine_fee


@app.post("/pro/licensees")
def create_licensee():
    _, role = auth()
    require_role(role, {"ProLicensingAdmin"})
    body = get_json()
    legal_name = require_str(body.get("legal_name"), "legal_name")
    category = require_enum(body.get("category"), LICENSEE_CATEGORIES, "category")
    revenue = require_int(body.get("reported_revenue_cents"), "reported_revenue_cents", min_value=0)
    usage = require_int(body.get("usage_units"), "usage_units", min_value=0)
    lic = new_resource(
        {
            "legal_name": legal_name,
            "category": category,
            "reported_revenue_cents": revenue,
            "usage_units": usage,
            "blanket_fee_cents": 0,
            "credit_standing": "GOOD",
            "settled_fee_cents": None,
        }
    )
    compute_and_set_fee(lic)
    DB["licensees"][lic["id"]] = lic
    return success_object(lic, 201)


@app.get("/pro/licensees")
def list_licensees():
    _, role = auth()
    require_role(
        role, {"ProLicensingAdmin", "FinanceOfficer", "RateCourtOfficer", "Licensee"}
    )
    limit, offset = parse_limit_offset()
    items = list(DB["licensees"].values())
    cat = request.args.get("category")
    if cat:
        items = [l for l in items if l["category"] == cat]
    cs = request.args.get("credit_standing")
    if cs:
        items = [l for l in items if l["credit_standing"] == cs]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/licensees/<lid>")
def get_licensee(lid):
    user_id, role = auth()
    require_role(role, {"ProLicensingAdmin", "FinanceOfficer", "Licensee"})
    lic = get_or_404("licensees", lid)
    if role == "Licensee" and lic["id"] != user_id:
        raise err("ERR_FORBIDDEN", "Licensees may only read their own record")
    return success_object(lic)


@app.patch("/pro/licensees/<lid>")
def patch_licensee(lid):
    user_id, role = auth()
    require_role(role, {"ProLicensingAdmin", "Licensee"})
    lic = get_or_404("licensees", lid)
    if role == "Licensee" and lic["id"] != user_id:
        raise err("ERR_FORBIDDEN", "Licensees may only update their own record")
    body = get_json()
    changed = False
    if "reported_revenue_cents" in body:
        lic["reported_revenue_cents"] = require_int(
            body["reported_revenue_cents"], "reported_revenue_cents", min_value=0
        )
        changed = True
    if "usage_units" in body:
        lic["usage_units"] = require_int(body["usage_units"], "usage_units", min_value=0)
        changed = True
    if changed:
        compute_and_set_fee(lic)
        touch(lic)
    return success_object(lic)


# ---------------------------------------------------------------------------
# licenses
# ---------------------------------------------------------------------------

LICENSE_STATUSES = {"ACTIVE", "DISPUTED", "SUSPENDED", "EXPIRED", "TERMINATED"}


@app.post("/pro/licensees/<lid>/licenses")
def issue_license(lid):
    _, role = auth()
    require_role(role, {"ProLicensingAdmin"})
    licensee = get_or_404("licensees", lid)
    body = get_json()
    # OCC
    expected = body.get("expected_licensee_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err("ERR_VALIDATION", "expected_licensee_version must be an integer")
        if expected != licensee["version"]:
            raise err("ERR_STALE_VERSION", "Licensee version has advanced")
    # delinquency gate
    if licensee["credit_standing"] != "GOOD":
        raise err("ERR_LICENSEE_DELINQUENT", "Licensee credit_standing is DELINQUENT")
    eff = body.get("effective_date")
    exp = body.get("expiry_date")
    eff_d = parse_iso_date(eff, "effective_date")
    exp_d = parse_iso_date(exp, "expiry_date")
    if eff_d >= exp_d:
        raise err("ERR_VALIDATION", "effective_date must be strictly earlier than expiry_date")
    lic = new_resource(
        {
            "licensee_id": licensee["id"],
            "category": licensee["category"],
            "effective_date": eff,
            "expiry_date": exp,
            "status": "ACTIVE",
            "fee_basis_cents": licensee["blanket_fee_cents"],
        }
    )
    DB["licenses"][lic["id"]] = lic
    touch(licensee)
    return success_object(lic, 201)


@app.get("/pro/licensees/<lid>/licenses")
def list_licensee_licenses(lid):
    user_id, role = auth()
    require_role(role, {"ProLicensingAdmin", "FinanceOfficer", "Licensee"})
    licensee = get_or_404("licensees", lid)
    if role == "Licensee" and licensee["id"] != user_id:
        raise err("ERR_FORBIDDEN", "Licensees may only read their own licenses")
    limit, offset = parse_limit_offset()
    items = [l for l in DB["licenses"].values() if l["licensee_id"] == lid]
    for l in items:
        maybe_expire_license(l)
    st = request.args.get("status")
    if st:
        items = [l for l in items if l["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/licenses")
def list_licenses():
    _, role = auth()
    require_role(role, {"ProLicensingAdmin", "RoyaltyDistributor", "FinanceOfficer"})
    limit, offset = parse_limit_offset()
    items = list(DB["licenses"].values())
    for l in items:
        maybe_expire_license(l)
    lid = request.args.get("licensee_id")
    if lid:
        items = [l for l in items if l["licensee_id"] == lid]
    st = request.args.get("status")
    if st:
        items = [l for l in items if l["status"] == st]
    cat = request.args.get("category")
    if cat:
        items = [l for l in items if l["category"] == cat]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/licenses/<lid>")
def get_license(lid):
    user_id, role = auth()
    require_role(role, {"ProLicensingAdmin", "FinanceOfficer", "Licensee"})
    lic = get_or_404("licenses", lid)
    if role == "Licensee" and lic["licensee_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Licensees may only read their own licenses")
    maybe_expire_license(lic)
    return success_object(lic)


@app.post("/pro/licenses/<lid>/suspend")
def suspend_license(lid):
    _, role = auth()
    require_role(role, {"ProLicensingAdmin"})
    lic = get_or_404("licenses", lid)
    maybe_expire_license(lic)
    if lic["status"] not in ("ACTIVE", "DISPUTED"):
        raise err("ERR_INVALID_STATE", "License cannot be suspended from its current status")
    licensee = DB["licensees"].get(lic["licensee_id"])
    if licensee is None or licensee["credit_standing"] != "DELINQUENT":
        raise err("ERR_INVALID_STATE", "Suspension requires licensee DELINQUENT")
    lic["status"] = "SUSPENDED"
    touch(lic)
    return success_object(lic)


@app.post("/pro/licenses/<lid>/reinstate")
def reinstate_license(lid):
    _, role = auth()
    require_role(role, {"ProLicensingAdmin"})
    lic = get_or_404("licenses", lid)
    maybe_expire_license(lic)
    if lic["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "License must be SUSPENDED to reinstate")
    licensee = DB["licensees"].get(lic["licensee_id"])
    if licensee is None or licensee["credit_standing"] != "GOOD":
        raise err("ERR_INVALID_STATE", "Reinstatement requires licensee GOOD standing")
    lic["status"] = "ACTIVE"
    touch(lic)
    return success_object(lic)


@app.post("/pro/licenses/<lid>/terminate")
def terminate_license(lid):
    _, role = auth()
    require_role(role, {"ProLicensingAdmin"})
    lic = get_or_404("licenses", lid)
    maybe_expire_license(lic)
    if lic["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "License cannot be terminated from its current status")
    if lic["status"] == "ACTIVE":
        # no open audit against the licensee
        for a in DB["audits"].values():
            if a["licensee_id"] == lic["licensee_id"] and a["status"] != "CLOSED":
                raise err("ERR_INVALID_STATE", "An audit against this licensee is not CLOSED")
    lic["status"] = "TERMINATED"
    touch(lic)
    return success_object(lic)


# ---------------------------------------------------------------------------
# disputes & rate court
# ---------------------------------------------------------------------------

DISPUTE_STATUSES = {"OPEN", "NEGOTIATION", "RATE_COURT", "SETTLED", "WITHDRAWN"}
LIVE_DISPUTE_STATUSES = {"OPEN", "NEGOTIATION", "RATE_COURT"}
CASE_STATUSES = {"FILED", "HEARING", "DECIDED", "DISMISSED"}


@app.post("/pro/licenses/<lid>/disputes")
def open_dispute(lid):
    user_id, role = auth()
    require_role(role, {"Licensee", "ProLicensingAdmin"})
    lic = get_or_404("licenses", lid)
    maybe_expire_license(lic)
    if role == "Licensee" and lic["licensee_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Licensees may only dispute their own licenses")
    for d in DB["disputes"].values():
        if d["license_id"] == lic["id"] and d["status"] in LIVE_DISPUTE_STATUSES:
            raise err("ERR_DISPUTE_ALREADY_OPEN", "A live dispute already exists for this license")
    if lic["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "License must be ACTIVE to open a dispute")
    body = get_json()
    opened_by = require_enum(body.get("opened_by_role"), {"LICENSEE", "PRO"}, "opened_by_role")
    disputed_fee = require_int(body.get("disputed_fee_cents"), "disputed_fee_cents", min_value=0)
    # role coherence: a Licensee caller opens LICENSEE disputes; admin opens PRO
    if role == "Licensee" and opened_by != "LICENSEE":
        raise err("ERR_FORBIDDEN", "Licensee callers must open LICENSEE disputes")
    if role == "ProLicensingAdmin" and opened_by != "PRO":
        raise err("ERR_FORBIDDEN", "ProLicensingAdmin callers must open PRO disputes")
    disp = new_resource(
        {
            "license_id": lic["id"],
            "opened_by_role": opened_by,
            "disputed_fee_cents": disputed_fee,
            "status": "OPEN",
            "settled_fee_cents": None,
            "negotiation_rounds": 0,
            "last_offer_cents": disputed_fee,
        }
    )
    DB["disputes"][disp["id"]] = disp
    lic["status"] = "DISPUTED"
    touch(lic)
    return success_object(disp, 201)


@app.get("/pro/licenses/<lid>/disputes")
def list_license_disputes(lid):
    user_id, role = auth()
    require_role(role, {"ProLicensingAdmin", "RateCourtOfficer", "Licensee"})
    lic = get_or_404("licenses", lid)
    if role == "Licensee" and lic["licensee_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Licensees may only read their own disputes")
    limit, offset = parse_limit_offset()
    items = [d for d in DB["disputes"].values() if d["license_id"] == lid]
    st = request.args.get("status")
    if st:
        items = [d for d in items if d["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/disputes")
def list_disputes():
    _, role = auth()
    require_role(role, {"ProLicensingAdmin", "RateCourtOfficer", "FinanceOfficer"})
    limit, offset = parse_limit_offset()
    items = list(DB["disputes"].values())
    lid = request.args.get("license_id")
    if lid:
        items = [d for d in items if d["license_id"] == lid]
    st = request.args.get("status")
    if st:
        items = [d for d in items if d["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/disputes/<did>")
def get_dispute(did):
    user_id, role = auth()
    require_role(role, {"ProLicensingAdmin", "RateCourtOfficer", "Licensee"})
    disp = get_or_404("disputes", did)
    if role == "Licensee":
        lic = DB["licenses"].get(disp["license_id"])
        if lic is None or lic["licensee_id"] != user_id:
            raise err("ERR_FORBIDDEN", "Licensees may only read their own disputes")
    return success_object(disp)


@app.post("/pro/disputes/<did>/negotiate")
def negotiate_dispute(did):
    user_id, role = auth()
    require_role(role, {"ProLicensingAdmin", "Licensee"})
    disp = get_or_404("disputes", did)
    if role == "Licensee":
        lic = DB["licenses"].get(disp["license_id"])
        if lic is None or lic["licensee_id"] != user_id:
            raise err("ERR_FORBIDDEN", "Licensees may only negotiate their own disputes")
    body = get_json()
    if disp["status"] == "OPEN":
        if role != "ProLicensingAdmin":
            raise err(
                "ERR_INVALID_STATE",
                "The first negotiation round from OPEN is opened by the licensing admin",
            )
        disp["status"] = "NEGOTIATION"
        disp["negotiation_rounds"] += 1
        counter = body.get("counter_fee_cents")
        if counter is not None:
            require_int(counter, "counter_fee_cents", min_value=0)
            disp["last_offer_cents"] = counter
        touch(disp)
        return success_object(disp)
    if disp["status"] == "NEGOTIATION":
        counter = require_int(body.get("counter_fee_cents"), "counter_fee_cents", min_value=0)
        if counter == disp.get("last_offer_cents"):
            raise err(
                "ERR_VALIDATION", "counter_fee_cents must differ from the last offered fee"
            )
        disp["last_offer_cents"] = counter
        disp["negotiation_rounds"] += 1
        touch(disp)
        return success_object(disp)
    raise err("ERR_INVALID_STATE", "Dispute is not in a negotiable state")


@app.post("/pro/disputes/<did>/settle")
def settle_dispute(did):
    _, role = auth()
    require_role(role, {"ProLicensingAdmin"})
    disp = get_or_404("disputes", did)
    if disp["status"] != "NEGOTIATION":
        raise err("ERR_INVALID_STATE", "Dispute must be NEGOTIATION to settle")
    body = get_json()
    agreed = require_int(body.get("agreed_fee_cents"), "agreed_fee_cents", min_value=0)
    disp["settled_fee_cents"] = agreed
    disp["status"] = "SETTLED"
    touch(disp)
    settle_license_after_dispute(disp["license_id"], agreed)
    return success_object(disp)


@app.post("/pro/disputes/<did>/escalate")
def escalate_dispute(did):
    user_id, role = auth()
    require_role(role, {"Licensee"})
    disp = get_or_404("disputes", did)
    lic = DB["licenses"].get(disp["license_id"])
    if lic is None or lic["licensee_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Licensees may only escalate their own disputes")
    if disp["status"] not in ("OPEN", "NEGOTIATION"):
        raise err("ERR_INVALID_STATE", "Dispute must be OPEN or NEGOTIATION to escalate")
    for c in DB["rate_court_cases"].values():
        if c["dispute_id"] == disp["id"] and c["status"] != "DISMISSED":
            raise err(
                "ERR_RATE_COURT_CASE_EXISTS",
                "A non-DISMISSED rate court case exists for this dispute",
            )
    case = new_resource(
        {
            "dispute_id": disp["id"],
            "status": "FILED",
            "adjudicated_fee_cents": None,
        }
    )
    DB["rate_court_cases"][case["id"]] = case
    disp["status"] = "RATE_COURT"
    touch(disp)
    return success_object(case, 201)


@app.post("/pro/disputes/<did>/withdraw")
def withdraw_dispute(did):
    user_id, role = auth()
    require_role(role, {"Licensee"})
    disp = get_or_404("disputes", did)
    lic = DB["licenses"].get(disp["license_id"])
    if disp["status"] not in ("OPEN", "NEGOTIATION"):
        raise err("ERR_INVALID_STATE", "Dispute cannot be withdrawn from its current status")
    if disp["opened_by_role"] != "LICENSEE":
        raise err("ERR_DISPUTE_NOT_WITHDRAWABLE", "Only licensee-opened disputes may be withdrawn")
    if lic is None or lic["licensee_id"] != user_id:
        raise err("ERR_DISPUTE_NOT_WITHDRAWABLE", "Only the owning licensee may withdraw")
    disp["status"] = "WITHDRAWN"
    touch(disp)
    if lic["status"] == "DISPUTED":
        lic["status"] = "ACTIVE"
        touch(lic)
    return success_object(disp)


@app.get("/pro/disputes/<did>/rate-court-cases")
def list_dispute_cases(did):
    user_id, role = auth()
    require_role(role, {"ProLicensingAdmin", "RateCourtOfficer", "Licensee"})
    disp = get_or_404("disputes", did)
    if role == "Licensee":
        lic = DB["licenses"].get(disp["license_id"])
        if lic is None or lic["licensee_id"] != user_id:
            raise err("ERR_FORBIDDEN", "Licensees may only read their own disputes")
    limit, offset = parse_limit_offset()
    items = [c for c in DB["rate_court_cases"].values() if c["dispute_id"] == did]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.post("/pro/rate-court-cases/<cid>/open-hearing")
def open_hearing(cid):
    _, role = auth()
    require_role(role, {"RateCourtOfficer"})
    case = get_or_404("rate_court_cases", cid)
    if case["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Case must be FILED to open a hearing")
    case["status"] = "HEARING"
    touch(case)
    return success_object(case)


@app.post("/pro/rate-court-cases/<cid>/decide")
def decide_case(cid):
    _, role = auth()
    require_role(role, {"RateCourtOfficer"})
    case = get_or_404("rate_court_cases", cid)
    if case["status"] != "HEARING":
        raise err("ERR_INVALID_STATE", "Case must be HEARING to decide")
    body = get_json()
    fee = require_int(body.get("adjudicated_fee_cents"), "adjudicated_fee_cents", min_value=0)
    case["adjudicated_fee_cents"] = fee
    case["status"] = "DECIDED"
    touch(case)
    disp = DB["disputes"].get(case["dispute_id"])
    if disp is not None and disp["status"] == "RATE_COURT":
        disp["settled_fee_cents"] = fee
        disp["status"] = "SETTLED"
        touch(disp)
        settle_license_after_dispute(disp["license_id"], fee)
    return success_object(case)


@app.post("/pro/rate-court-cases/<cid>/dismiss")
def dismiss_case(cid):
    _, role = auth()
    require_role(role, {"RateCourtOfficer"})
    case = get_or_404("rate_court_cases", cid)
    if case["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Case must be FILED to dismiss")
    case["status"] = "DISMISSED"
    touch(case)
    disp = DB["disputes"].get(case["dispute_id"])
    if disp is not None and disp["status"] == "RATE_COURT":
        disp["status"] = "NEGOTIATION"
        disp["negotiation_rounds"] += 1
        touch(disp)
    return success_object(case)


# ---------------------------------------------------------------------------
# performance ingestion
# ---------------------------------------------------------------------------

MEDIA = {"TERRESTRIAL_RADIO", "NETWORK_TV", "CABLE_TV", "DIGITAL_STREAMING", "LIVE_VENUE"}
DAYPARTS = {"PRIME", "DAY", "LATE_NIGHT", "OVERNIGHT"}
SOURCES = {"MONITORING", "CUE_SHEET", "DIGITAL_REPORT", "SAMPLE"}
PERF_STATUSES = {"ACCEPTED", "REJECTED", "VOIDED"}


def ingest_one(body, persist_rejected=False):
    """Validate + create a PerformanceEvent. Returns (event, error_id_or_None)."""
    try:
        work_id = body.get("work_id")
        license_id = body.get("license_id")
        if not isinstance(work_id, str) or not isinstance(license_id, str):
            raise err("ERR_VALIDATION", "work_id and license_id are required")
        perf_date_raw = body.get("performance_date")
        perf_date = parse_iso_date(perf_date_raw, "performance_date")
        medium = require_enum(body.get("medium"), MEDIA, "medium")
        daypart = require_enum(body.get("daypart"), DAYPARTS, "daypart")
        source = require_enum(body.get("source"), SOURCES, "source")
        play_count = require_int(body.get("play_count"), "play_count", min_value=1)
        frame_units = body.get("frame_units_reported")
        if source == "SAMPLE":
            frame_units = require_int(frame_units, "frame_units_reported", min_value=1)
        # FK existence
        work = DB["works"].get(work_id)
        if work is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "work_id does not exist")
        lic = DB["licenses"].get(license_id)
        if lic is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "license_id does not exist")
        maybe_expire_license(lic)
        # business referential checks
        if lic["status"] not in ("ACTIVE", "DISPUTED"):
            raise err("ERR_LICENSE_SUSPENDED", "License does not accept new performances")
        eff = date.fromisoformat(lic["effective_date"])
        exp = date.fromisoformat(lic["expiry_date"])
        if not (eff <= perf_date <= exp):
            raise err(
                "ERR_PERFORMANCE_OUTSIDE_LICENSE_WINDOW",
                "performance_date outside the license window",
            )
        if work["status"] != "CONFIRMED":
            raise err("ERR_WORK_NOT_CONFIRMED", "Work is not CONFIRMED")
        universe = calcs.sampled_universe(source, play_count, frame_units)
        credit_units = calcs.compute_credit_units(work_id, medium, daypart, universe)
        ev = new_resource(
            {
                "work_id": work_id,
                "license_id": license_id,
                "performance_date": perf_date_raw,
                "medium": medium,
                "daypart": daypart,
                "source": source,
                "play_count": play_count,
                "frame_units_reported": frame_units,
                "universe_estimated_plays": universe,
                "credit_units": credit_units,
                "cycle_id": None,
                "rejection_error_id": None,
                "status": "ACCEPTED",
            }
        )
        DB["performances"][ev["id"]] = ev
        return ev, None
    except ApiError as e:
        if not persist_rejected:
            raise
        ev = new_resource(
            {
                "work_id": body.get("work_id"),
                "license_id": body.get("license_id"),
                "performance_date": body.get("performance_date"),
                "medium": body.get("medium"),
                "daypart": body.get("daypart"),
                "source": body.get("source"),
                "play_count": body.get("play_count"),
                "frame_units_reported": body.get("frame_units_reported"),
                "universe_estimated_plays": 0,
                "credit_units": 0.0,
                "cycle_id": None,
                "rejection_error_id": e.error_id,
                "status": "REJECTED",
            }
        )
        DB["performances"][ev["id"]] = ev
        return ev, e.error_id


@app.post("/pro/performances")
def ingest_performance():
    _, role = auth()
    require_role(role, {"RoyaltyDistributor"})
    body = get_json()
    ev, _ = ingest_one(body, persist_rejected=False)
    return success_object(ev, 201)


@app.post("/pro/performances/bulk")
def ingest_performances_bulk():
    _, role = auth()
    require_role(role, {"RoyaltyDistributor"})
    body = get_json()
    events = body.get("events")
    if not isinstance(events, list):
        raise err("ERR_VALIDATION", "events must be a list")
    results = []
    for row in events:
        if not isinstance(row, dict):
            row = {}
        ev, _ = ingest_one(row, persist_rejected=True)
        results.append(ev)
    return success_list(results, len(results), len(results) if results else 10, 0)


@app.get("/pro/performances")
def list_performances():
    _, role = auth()
    require_role(role, {"RoyaltyDistributor", "FinanceOfficer", "ProLicensingAdmin"})
    limit, offset = parse_limit_offset()
    items = list(DB["performances"].values())
    for key in ("work_id", "license_id", "cycle_id", "status", "medium"):
        v = request.args.get(key)
        if v:
            items = [e for e in items if str(e.get(key)) == v]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/works/<wid>/performances")
def list_work_performances(wid):
    _, role = auth()
    require_role(role, {"RoyaltyDistributor", "Publisher", "Songwriter"})
    work = get_or_404("works", wid)
    limit, offset = parse_limit_offset()
    items = [e for e in DB["performances"].values() if e["work_id"] == wid]
    st = request.args.get("status")
    if st:
        items = [e for e in items if e["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/licenses/<lid>/performances")
def list_license_performances(lid):
    user_id, role = auth()
    require_role(role, {"RoyaltyDistributor", "Licensee", "ProLicensingAdmin"})
    lic = get_or_404("licenses", lid)
    if role == "Licensee" and lic["licensee_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Licensees may only read their own performances")
    limit, offset = parse_limit_offset()
    items = [e for e in DB["performances"].values() if e["license_id"] == lid]
    st = request.args.get("status")
    if st:
        items = [e for e in items if e["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.post("/pro/performances/<pid>/void")
def void_performance(pid):
    _, role = auth()
    require_role(role, {"RoyaltyDistributor"})
    ev = get_or_404("performances", pid)
    if ev["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Only ACCEPTED events can be voided")
    if ev["cycle_id"] is not None:
        cyc = DB["cycles"].get(ev["cycle_id"])
        if cyc is None or cyc["status"] != "COLLECTING":
            raise err(
                "ERR_INVALID_STATE",
                "Event is locked by a cycle that is no longer COLLECTING",
            )
    ev["status"] = "VOIDED"
    touch(ev)
    return success_object(ev)


@app.post("/pro/cycles/<cyc_id>/performances/capture")
def capture_performances(cyc_id):
    _, role = auth()
    require_role(role, {"RoyaltyDistributor"})
    cyc = get_or_404("cycles", cyc_id)
    if cyc["status"] != "COLLECTING":
        raise err("ERR_INVALID_STATE", "Cycle must be COLLECTING to capture performances")
    body = get_json()
    ids = body.get("performance_event_ids")
    if not isinstance(ids, list):
        raise err("ERR_VALIDATION", "performance_event_ids must be a list")
    period_start = date.fromisoformat(cyc["period_start"])
    period_end = date.fromisoformat(cyc["period_end"])
    events = []
    for eid in ids:
        ev = DB["performances"].get(eid)
        if ev is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "performance_event_id does not exist")
        if ev["status"] != "ACCEPTED":
            raise err("ERR_INVALID_STATE", "Only ACCEPTED events can be captured")
        if ev["cycle_id"] is not None and ev["cycle_id"] != cyc["id"]:
            raise err("ERR_INVALID_STATE", "Event is already captured into another cycle")
        pd = date.fromisoformat(ev["performance_date"])
        if not (period_start <= pd <= period_end):
            raise err("ERR_VALIDATION", "Event performance_date is outside the cycle period")
        events.append(ev)
    for ev in events:
        if ev["cycle_id"] != cyc["id"]:
            ev["cycle_id"] = cyc["id"]
            touch(ev)
    if events:
        touch(cyc)
    return success_list(events, len(events), len(events) if events else 10, 0)


@app.get("/pro/cycles/<cyc_id>/performances")
def list_cycle_performances(cyc_id):
    _, role = auth()
    require_role(role, {"RoyaltyDistributor", "FinanceOfficer"})
    cyc = get_or_404("cycles", cyc_id)
    limit, offset = parse_limit_offset()
    items = [e for e in DB["performances"].values() if e.get("cycle_id") == cyc_id]
    st = request.args.get("status")
    if st:
        items = [e for e in items if e["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


# ---------------------------------------------------------------------------
# distribution cycles
# ---------------------------------------------------------------------------

CYCLE_STATUSES = {"DRAFT", "COLLECTING", "CALCULATING", "DISTRIBUTED", "ADJUSTED"}


@app.post("/pro/cycles")
def create_cycle():
    _, role = auth()
    require_role(role, {"RoyaltyDistributor"})
    body = get_json()
    label = require_str(body.get("label"), "label")
    ps = body.get("period_start")
    pe = body.get("period_end")
    ps_d = parse_iso_date(ps, "period_start")
    pe_d = parse_iso_date(pe, "period_end")
    if ps_d > pe_d:
        raise err("ERR_VALIDATION", "period_start must be <= period_end")
    for c in DB["cycles"].values():
        if c["label"] == label:
            raise err("ERR_VALIDATION", "label must be unique")
    cyc = new_resource(
        {
            "label": label,
            "period_start": ps,
            "period_end": pe,
            "status": "DRAFT",
            "pool_amount_cents": None,
            "claims_open_until": None,
            "version_epoch": 0,
        }
    )
    DB["cycles"][cyc["id"]] = cyc
    return success_object(cyc, 201)


@app.get("/pro/cycles")
def list_cycles():
    _, role = auth()
    require_role(role, {"RoyaltyDistributor", "FinanceOfficer", "ProLicensingAdmin"})
    limit, offset = parse_limit_offset()
    items = list(DB["cycles"].values())
    st = request.args.get("status")
    if st:
        items = [c for c in items if c["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/cycles/<cyc_id>")
def get_cycle(cyc_id):
    _, role = auth()
    require_role(role, {"RoyaltyDistributor", "FinanceOfficer"})
    cyc = get_or_404("cycles", cyc_id)
    return success_object(cyc)


def _pool_for_cycle(cycle_id):
    for p in DB["pools"].values():
        if p["cycle_id"] == cycle_id:
            return p
    return None


@app.post("/pro/cycles/<cyc_id>/open")
def open_cycle(cyc_id):
    _, role = auth()
    require_role(role, {"RoyaltyDistributor"})
    cyc = get_or_404("cycles", cyc_id)
    if cyc["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Cycle must be DRAFT to open")
    ps_d = date.fromisoformat(cyc["period_start"])
    pe_d = date.fromisoformat(cyc["period_end"])
    if ps_d > pe_d:
        raise err("ERR_VALIDATION", "period_start must be <= period_end")
    cyc["status"] = "COLLECTING"
    touch(cyc)
    if _pool_for_cycle(cyc["id"]) is None:
        pool = new_resource(
            {"cycle_id": cyc["id"], "balance_cents": 0, "status": "OPEN"}
        )
        DB["pools"][pool["id"]] = pool
    return success_object(cyc)


@app.post("/pro/cycles/<cyc_id>/close-collection")
def close_collection(cyc_id):
    _, role = auth()
    require_role(role, {"RoyaltyDistributor"})
    cyc = get_or_404("cycles", cyc_id)
    if cyc["status"] != "COLLECTING":
        raise err("ERR_INVALID_STATE", "Cycle must be COLLECTING to close collection")
    body = get_json()
    expected = body.get("expected_cycle_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err("ERR_VALIDATION", "expected_cycle_version must be an integer")
        if expected != cyc["version"]:
            raise err("ERR_STALE_VERSION", "Cycle version has advanced")
    accepted = [
        e
        for e in DB["performances"].values()
        if e.get("cycle_id") == cyc["id"] and e["status"] == "ACCEPTED"
    ]
    if not accepted:
        raise err("ERR_CYCLE_NO_PERFORMANCES", "No ACCEPTED performances captured in the cycle")
    cyc["version_epoch"] = cyc.get("version_epoch", 0) + 1
    ps_d = date.fromisoformat(cyc["period_start"])
    pe_d = date.fromisoformat(cyc["period_end"])
    cyc["pool_amount_cents"] = calcs.compute_pool_amount(ps_d, pe_d)
    cyc["status"] = "CALCULATING"
    calcs.run_allocation(cyc)
    touch(cyc)
    return success_object(cyc)


@app.post("/pro/cycles/<cyc_id>/distribute")
def distribute_cycle(cyc_id):
    _, role = auth()
    require_role(role, {"RoyaltyDistributor"})
    cyc = get_or_404("cycles", cyc_id)
    if cyc["status"] != "CALCULATING":
        raise err("ERR_INVALID_STATE", "Cycle must be CALCULATING to distribute")
    epoch = cyc["version_epoch"]
    current = [
        s
        for s in DB["statements"].values()
        if s["cycle_id"] == cyc["id"] and s["epoch"] == epoch
    ]
    if any(s["status"] == "DRAFT" for s in current):
        raise err(
            "ERR_STATEMENTS_NOT_FINALIZED",
            "All current-epoch statements must be FINALIZED",
        )
    for s in current:
        if s["status"] == "FINALIZED":
            s["status"] = "PAID"
            touch(s)
            credit = s["net_amount_cents"] - s["unclaimed_amount_cents"]
            aff = DB["affiliates"].get(s["affiliate_id"])
            if aff is not None:
                aff["royalty_balance_cents"] = aff.get("royalty_balance_cents", 0) + credit
                aff["total_paid_cents"] = aff.get("total_paid_cents", 0) + credit
                touch(aff)
    if not cyc.get("claims_open_until"):
        pe_d = date.fromisoformat(cyc["period_end"])
        cyc["claims_open_until"] = (
            pe_d + timedelta(days=calcs.CLAIMS_WINDOW_DAYS)
        ).isoformat()
    cyc["status"] = "DISTRIBUTED"
    touch(cyc)
    return success_object(cyc)


@app.get("/pro/cycles/<cyc_id>/statements")
def list_cycle_statements(cyc_id):
    _, role = auth()
    require_role(role, {"RoyaltyDistributor", "FinanceOfficer"})
    cyc = get_or_404("cycles", cyc_id)
    limit, offset = parse_limit_offset()
    items = [s for s in DB["statements"].values() if s["cycle_id"] == cyc_id]
    st = request.args.get("status")
    if st:
        items = [s for s in items if s["status"] == st]
    ep = request.args.get("epoch")
    if ep is not None:
        try:
            ep_i = int(ep)
        except ValueError:
            raise err("ERR_VALIDATION", "epoch must be an integer")
        items = [s for s in items if s["epoch"] == ep_i]
    aid = request.args.get("affiliate_id")
    if aid:
        items = [s for s in items if s["affiliate_id"] == aid]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/cycles/<cyc_id>/pool")
def get_cycle_pool(cyc_id):
    _, role = auth()
    require_role(role, {"RoyaltyDistributor", "FinanceOfficer"})
    cyc = get_or_404("cycles", cyc_id)
    pool = _pool_for_cycle(cyc_id)
    if pool is None:
        raise err("ERR_NOT_FOUND", "Cycle has no unclaimed royalty pool")
    return success_object(pool)


# ---------------------------------------------------------------------------
# statements
# ---------------------------------------------------------------------------

STATEMENT_STATUSES = {"DRAFT", "FINALIZED", "PAID", "ADJUSTED"}


@app.get("/pro/statements")
def list_statements():
    _, role = auth()
    require_role(role, {"RoyaltyDistributor", "FinanceOfficer"})
    limit, offset = parse_limit_offset()
    items = list(DB["statements"].values())
    cid = request.args.get("cycle_id")
    if cid:
        items = [s for s in items if s["cycle_id"] == cid]
    aid = request.args.get("affiliate_id")
    if aid:
        items = [s for s in items if s["affiliate_id"] == aid]
    st = request.args.get("status")
    if st:
        items = [s for s in items if s["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/affiliates/<aid>/statements")
def list_affiliate_statements(aid):
    user_id, role = auth()
    require_role(role, {"RoyaltyDistributor", "FinanceOfficer", "Publisher", "Songwriter"})
    get_or_404("affiliates", aid)
    if role in ("Publisher", "Songwriter") and aid != user_id:
        raise err("ERR_FORBIDDEN", "Affiliates may only read their own statements")
    limit, offset = parse_limit_offset()
    items = [s for s in DB["statements"].values() if s["affiliate_id"] == aid]
    cid = request.args.get("cycle_id")
    if cid:
        items = [s for s in items if s["cycle_id"] == cid]
    st = request.args.get("status")
    if st:
        items = [s for s in items if s["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/statements/<sid>")
def get_statement(sid):
    _, role = auth()
    require_role(role, {"RoyaltyDistributor", "FinanceOfficer"})
    st = get_or_404("statements", sid)
    return success_object(st)


@app.post("/pro/statements/<sid>/finalize")
def finalize_statement(sid):
    _, role = auth()
    require_role(role, {"RoyaltyDistributor"})
    st = get_or_404("statements", sid)
    if st["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Statement must be DRAFT to finalize")
    cyc = DB["cycles"].get(st["cycle_id"])
    if cyc is None or cyc["status"] != "CALCULATING":
        raise err("ERR_INVALID_STATE", "Owning cycle must be CALCULATING")
    if st["epoch"] != cyc["version_epoch"]:
        raise err("ERR_INVALID_STATE", "Statement epoch is not the current cycle epoch")
    st["status"] = "FINALIZED"
    touch(st)
    return success_object(st)


# ---------------------------------------------------------------------------
# adjustments
# ---------------------------------------------------------------------------

ADJ_REASONS = {"LATE_CLAIM", "AUDIT_FINDING", "RATE_COURT_RETRO", "DATA_CORRECTION"}
ADJ_STATUSES = {"PENDING", "APPROVED", "REJECTED", "APPLIED"}


@app.post("/pro/statements/<sid>/adjustments")
def create_adjustment(sid):
    user_id, role = auth()
    require_role(role, {"RoyaltyDistributor", "FinanceOfficer", "Publisher", "Songwriter"})
    st = get_or_404("statements", sid)
    body = get_json()
    delta = require_int(body.get("delta_cents"), "delta_cents")
    reason = require_enum(body.get("reason"), ADJ_REASONS, "reason")
    audit_id = body.get("audit_id")
    if reason == "AUDIT_FINDING":
        if not audit_id or not isinstance(audit_id, str):
            raise err("ERR_VALIDATION", "audit_id is required when reason is AUDIT_FINDING")
        if DB["audits"].get(audit_id) is None:
            raise err("ERR_REFERENCE_NOT_FOUND", "audit_id does not exist")
    else:
        if audit_id is not None:
            raise err("ERR_VALIDATION", "audit_id is only allowed for AUDIT_FINDING")
    if role in ("Publisher", "Songwriter"):
        if st["affiliate_id"] != user_id:
            raise err("ERR_FORBIDDEN", "Affiliates may only file adjustments on their own statements")
        if reason != "LATE_CLAIM":
            raise err("ERR_FORBIDDEN", "Affiliates may only file LATE_CLAIM adjustments")
    if reason == "LATE_CLAIM":
        cyc = DB["cycles"].get(st["cycle_id"])
        if cyc is not None and cyc.get("claims_open_until"):
            if clock_date() > date.fromisoformat(cyc["claims_open_until"]):
                raise err("ERR_CLAIMS_WINDOW_CLOSED", "The claims window has closed")
    adj = new_resource(
        {
            "statement_id": st["id"],
            "affiliate_id": st["affiliate_id"],
            "delta_cents": delta,
            "reason": reason,
            "audit_id": audit_id,
            "status": "PENDING",
            "created_by_user_id": user_id,
        }
    )
    DB["adjustments"][adj["id"]] = adj
    return success_object(adj, 201)


@app.get("/pro/statements/<sid>/adjustments")
def list_statement_adjustments(sid):
    _, role = auth()
    require_role(role, {"RoyaltyDistributor", "FinanceOfficer"})
    get_or_404("statements", sid)
    limit, offset = parse_limit_offset()
    items = [a for a in DB["adjustments"].values() if a["statement_id"] == sid]
    st = request.args.get("status")
    if st:
        items = [a for a in items if a["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/adjustments")
def list_adjustments():
    _, role = auth()
    require_role(role, {"RoyaltyDistributor", "FinanceOfficer"})
    limit, offset = parse_limit_offset()
    items = list(DB["adjustments"].values())
    aid = request.args.get("affiliate_id")
    if aid:
        items = [a for a in items if a["affiliate_id"] == aid]
    au = request.args.get("audit_id")
    if au:
        items = [a for a in items if a.get("audit_id") == au]
    st = request.args.get("status")
    if st:
        items = [a for a in items if a["status"] == st]
    rs = request.args.get("reason")
    if rs:
        items = [a for a in items if a["reason"] == rs]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/adjustments/<aid>")
def get_adjustment(aid):
    _, role = auth()
    require_role(role, {"RoyaltyDistributor", "FinanceOfficer"})
    adj = get_or_404("adjustments", aid)
    return success_object(adj)


@app.post("/pro/adjustments/<aid>/approve")
def approve_adjustment(aid):
    user_id, role = auth()
    require_role(role, {"FinanceOfficer"})
    adj = get_or_404("adjustments", aid)
    if adj["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Adjustment must be PENDING to approve")
    if adj.get("created_by_user_id") == user_id:
        raise err(
            "ERR_SEGREGATION_OF_DUTIES",
            "Approver must differ from the adjustment creator",
        )
    if adj["reason"] == "LATE_CLAIM":
        st = DB["statements"].get(adj["statement_id"])
        cyc = DB["cycles"].get(st["cycle_id"]) if st else None
        if cyc is not None and cyc.get("claims_open_until"):
            if clock_date() > date.fromisoformat(cyc["claims_open_until"]):
                raise err("ERR_CLAIMS_WINDOW_CLOSED", "The claims window has closed")
        pool = _pool_for_cycle(st["cycle_id"]) if st else None
        balance = pool["balance_cents"] if pool else 0
        if adj["delta_cents"] > balance:
            raise err(
                "ERR_UNCLAIMED_POOL_INSUFFICIENT",
                "Claimed amount exceeds the cycle pool balance",
            )
    adj["status"] = "APPROVED"
    touch(adj)
    return success_object(adj)


@app.post("/pro/adjustments/<aid>/reject")
def reject_adjustment(aid):
    user_id, role = auth()
    require_role(role, {"FinanceOfficer"})
    adj = get_or_404("adjustments", aid)
    if adj["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Adjustment must be PENDING to reject")
    if adj.get("created_by_user_id") == user_id:
        raise err(
            "ERR_SEGREGATION_OF_DUTIES",
            "Rejecter must differ from the adjustment creator",
        )
    adj["status"] = "REJECTED"
    touch(adj)
    return success_object(adj)


@app.post("/pro/adjustments/<aid>/apply")
def apply_adjustment(aid):
    _, role = auth()
    require_role(role, {"FinanceOfficer"})
    adj = get_or_404("adjustments", aid)
    if adj["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Adjustment must be APPROVED to apply")
    st = DB["statements"].get(adj["statement_id"])
    aff = DB["affiliates"].get(adj["affiliate_id"])
    if aff is not None:
        aff["royalty_balance_cents"] = aff.get("royalty_balance_cents", 0) + adj["delta_cents"]
        touch(aff)
    if adj["reason"] == "LATE_CLAIM" and adj["delta_cents"] > 0 and st is not None:
        pool = _pool_for_cycle(st["cycle_id"])
        if pool is not None:
            pool["balance_cents"] = pool["balance_cents"] - adj["delta_cents"]
            touch(pool)
    if st is not None:
        st["status"] = "ADJUSTED"
        touch(st)
        cyc = DB["cycles"].get(st["cycle_id"])
        if cyc is not None and cyc["status"] == "DISTRIBUTED":
            cyc["status"] = "ADJUSTED"
            touch(cyc)
    adj["status"] = "APPLIED"
    touch(adj)
    return success_object(adj)


# ---------------------------------------------------------------------------
# audits
# ---------------------------------------------------------------------------

AUDIT_STATUSES = {"OPEN", "FINDINGS_FILED", "CLOSED"}


@app.post("/pro/licensees/<lid>/audits")
def create_audit(lid):
    _, role = auth()
    require_role(role, {"FinanceOfficer"})
    licensee = get_or_404("licensees", lid)
    body = get_json()
    sps = body.get("scope_period_start")
    spe = body.get("scope_period_end")
    sps_d = parse_iso_date(sps, "scope_period_start")
    spe_d = parse_iso_date(spe, "scope_period_end")
    if sps_d > spe_d:
        raise err("ERR_VALIDATION", "scope_period_start must be <= scope_period_end")
    if spe_d < clock_date() - timedelta(days=calcs.AUDIT_LOOKBACK_DAYS):
        raise err(
            "ERR_AUDIT_SCOPE_TOO_OLD",
            "scope_period_end is more than 1095 days before the clock date",
        )
    audit = new_resource(
        {
            "licensee_id": licensee["id"],
            "scope_period_start": sps,
            "scope_period_end": spe,
            "status": "OPEN",
            "findings_delta_cents": 0,
        }
    )
    DB["audits"][audit["id"]] = audit
    return success_object(audit, 201)


@app.get("/pro/licensees/<lid>/audits")
def list_licensee_audits(lid):
    user_id, role = auth()
    require_role(role, {"FinanceOfficer", "ProLicensingAdmin", "Licensee"})
    licensee = get_or_404("licensees", lid)
    if role == "Licensee" and licensee["id"] != user_id:
        raise err("ERR_FORBIDDEN", "Licensees may only read their own audits")
    limit, offset = parse_limit_offset()
    items = [a for a in DB["audits"].values() if a["licensee_id"] == lid]
    st = request.args.get("status")
    if st:
        items = [a for a in items if a["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/audits/<aid>")
def get_audit(aid):
    _, role = auth()
    require_role(role, {"FinanceOfficer"})
    audit = get_or_404("audits", aid)
    return success_object(audit)


@app.post("/pro/audits/<aid>/file-findings")
def file_findings(aid):
    _, role = auth()
    require_role(role, {"FinanceOfficer"})
    audit = get_or_404("audits", aid)
    if audit["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Audit must be OPEN to file findings")
    body = get_json()
    delta = require_int(body.get("findings_delta_cents"), "findings_delta_cents")
    audit["findings_delta_cents"] = delta
    audit["status"] = "FINDINGS_FILED"
    touch(audit)
    return success_object(audit)


@app.post("/pro/audits/<aid>/close")
def close_audit(aid):
    _, role = auth()
    require_role(role, {"FinanceOfficer"})
    audit = get_or_404("audits", aid)
    if audit["status"] != "FINDINGS_FILED":
        raise err("ERR_INVALID_STATE", "Audit must be FINDINGS_FILED to close")
    if audit["findings_delta_cents"] > 0:
        found = any(
            a.get("audit_id") == audit["id"]
            and a["reason"] == "AUDIT_FINDING"
            and a["status"] != "REJECTED"
            for a in DB["adjustments"].values()
        )
        if not found:
            raise err(
                "ERR_AUDIT_CLOSE_REQUIRES_ADJUSTMENT",
                "A non-REJECTED AUDIT_FINDING adjustment must exist before closing",
            )
    if audit["findings_delta_cents"] > calcs.LICENSEE_DELINQUENCY_THRESHOLD_CENTS:
        licensee = DB["licensees"].get(audit["licensee_id"])
        if licensee is not None:
            licensee["credit_standing"] = "DELINQUENT"
            touch(licensee)
    audit["status"] = "CLOSED"
    touch(audit)
    return success_object(audit)


# ---------------------------------------------------------------------------
# unclaimed pools
# ---------------------------------------------------------------------------

POOL_STATUSES = {"OPEN", "PARTIALLY_ESCHEATED", "ESCHEATED"}


@app.get("/pro/pools")
def list_pools():
    _, role = auth()
    require_role(role, {"FinanceOfficer", "RoyaltyDistributor"})
    limit, offset = parse_limit_offset()
    items = list(DB["pools"].values())
    cid = request.args.get("cycle_id")
    if cid:
        items = [p for p in items if p["cycle_id"] == cid]
    st = request.args.get("status")
    if st:
        items = [p for p in items if p["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list(page, total, limit, offset)


@app.get("/pro/pools/<pid>")
def get_pool(pid):
    _, role = auth()
    require_role(role, {"FinanceOfficer", "RoyaltyDistributor"})
    pool = get_or_404("pools", pid)
    return success_object(pool)


@app.post("/pro/pools/<pid>/escheat")
def escheat_pool(pid):
    _, role = auth()
    require_role(role, {"FinanceOfficer"})
    pool = get_or_404("pools", pid)
    if pool["status"] == "ESCHEATED":
        raise err("ERR_INVALID_STATE", "Pool is already ESCHEATED")
    body = get_json()
    amount = require_int(body.get("amount_cents"), "amount_cents")
    cyc = DB["cycles"].get(pool["cycle_id"])
    due_date = None
    if cyc is not None and cyc.get("claims_open_until"):
        due_date = date.fromisoformat(cyc["claims_open_until"]) + timedelta(
            days=calcs.ESCHEAT_GRACE_DAYS
        )
    if due_date is None or clock_date() <= due_date:
        raise err("ERR_ESCHEAT_NOT_YET_DUE", "The claims window plus grace period has not passed")
    if amount <= 0 or amount > pool["balance_cents"]:
        raise err("ERR_ESCHEAT_AMOUNT_INVALID", "amount_cents must be > 0 and <= pool balance")
    if amount == pool["balance_cents"]:
        pool["balance_cents"] = 0
        pool["status"] = "ESCHEATED"
    else:
        pool["balance_cents"] = pool["balance_cents"] - amount
        pool["status"] = "PARTIALLY_ESCHEATED"
    touch(pool)
    return success_object(pool)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
