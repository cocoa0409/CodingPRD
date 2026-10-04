"""Routes: clock, sellers, buyers, certification programs, listings, inspection reports."""
from flask import Blueprint, request

import errors
import middleware as mw
import response as resp
import services as svc
from db import store, _parse_iso, fmt_iso
from helpers import (body, new_id, stamp_new, touch, pagination_args, paginate,
                     req_str, req_int, opt_bool, req_enum)

bp = Blueprint("core", __name__)


# ---------------- Clock ----------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin")
    data = body()
    to_iso = data.get("to_iso8601")
    if not isinstance(to_iso, str) or not to_iso.strip():
        raise errors.validation("to_iso8601 is required")
    try:
        store.clock = _parse_iso(to_iso)
    except (ValueError, TypeError):
        raise errors.validation("to_iso8601 must be a valid ISO 8601 timestamp")
    svc.run_sweeps()
    return resp.ok({"current_utc": fmt_iso(store.clock)})


# ---------------- Sellers ----------------

@bp.post("/sellers")
def create_seller():
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin")
    data = body()
    seller = stamp_new({
        "id": new_id(),
        "legal_name": req_str(data, "legal_name"),
        "seller_state": req_str(data, "seller_state"),
        "seller_type": req_enum(data, "seller_type", {"INDIVIDUAL", "LLC", "TRUST"}),
        "listed_count": 0,
        "bulk_discount_bps": 0,
    })
    store.sellers[seller["id"]] = seller
    return resp.created(seller)


@bp.get("/sellers/<sid>")
def get_seller(sid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller")
    seller = store.sellers.get(sid)
    if not seller:
        raise errors.not_found("Seller not found")
    if ctx.role == "Seller" and ctx.user_id != sid:
        raise errors.forbidden()
    return resp.ok(seller)


# ---------------- Buyers ----------------

@bp.post("/buyers")
def create_buyer():
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin")
    data = body()
    buyer = stamp_new({
        "id": new_id(),
        "legal_name": req_str(data, "legal_name"),
        "buyer_state": req_str(data, "buyer_state"),
        "entity_type": req_enum(data, "entity_type", {"INDIVIDUAL", "LLC", "TRUST"}),
        "proof_of_funds_cents": req_int(data, "proof_of_funds_cents"),
        "accredited": opt_bool(data, "accredited", False),
    })
    if buyer["proof_of_funds_cents"] < 0:
        raise errors.validation("proof_of_funds_cents must be >= 0")
    store.buyers[buyer["id"]] = buyer
    return resp.created(buyer)


# ---------------- Certification programs ----------------

@bp.post("/certification-programs")
def create_program():
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin")
    data = body()
    name = req_str(data, "name")
    if any(p["name"] == name for p in store.programs.values()):
        raise errors.validation("name must be unique")
    min_score = req_int(data, "min_inspection_score")
    if min_score < 0 or min_score > 100:
        raise errors.validation("min_inspection_score must be 0-100")
    cap = req_int(data, "guarantee_months_cap")
    if cap < 0:
        raise errors.validation("guarantee_months_cap must be >= 0")
    prog = stamp_new({
        "id": new_id(),
        "name": name,
        "min_inspection_score": min_score,
        "min_title_grade": req_enum(data, "min_title_grade", {"A", "B", "C"}),
        "requires_lease_disclosure": opt_bool(data, "requires_lease_disclosure", False),
        "guarantee_months_cap": cap,
        "active": opt_bool(data, "active", True),
    })
    store.programs[prog["id"]] = prog
    return resp.created(prog)


# ---------------- Listings ----------------

@bp.post("/listings")
def create_listing():
    ctx = mw.get_ctx()
    mw.require_role(ctx, "Seller")
    data = body()
    seller_id = req_str(data, "seller_id")
    # ownership: a seller drafting into another seller's portfolio -> 403
    if ctx.user_id != seller_id:
        raise errors.forbidden()
    if seller_id not in store.sellers:
        raise errors.not_found("Seller not found")
    asking = req_int(data, "asking_price_cents")
    if asking <= 0:
        raise errors.validation("asking_price_cents must be > 0")
    kind = req_enum(data, "listing_kind", {"SINGLE", "PORTFOLIO"})
    bulk = data.get("bulk_price_cents")
    if kind == "PORTFOLIO":
        if isinstance(bulk, bool) or not isinstance(bulk, int) or bulk <= 0:
            raise errors.validation("PORTFOLIO listing requires positive bulk_price_cents")
    elif bulk is not None:
        if isinstance(bulk, bool) or not isinstance(bulk, int) or bulk <= 0:
            raise errors.validation("bulk_price_cents must be a positive integer")
    prog_id = data.get("certification_program_id")
    if prog_id is not None:
        if not isinstance(prog_id, str) or prog_id not in store.programs:
            raise errors.validation("certification_program_id does not reference an existing program")
    listing = stamp_new({
        "id": new_id(),
        "seller_id": seller_id,
        "address_line": req_str(data, "address_line"),
        "listing_state": req_str(data, "listing_state"),
        "asking_price_cents": asking,
        "status": "DRAFT",
        "listing_kind": kind,
        "bulk_price_cents": bulk,
        "certification_program_id": prog_id,
        "certified_at": None,
        "seller_asks_confidential": opt_bool(data, "seller_asks_confidential", False),
    })
    store.listings[listing["id"]] = listing
    svc.recompute_seller(seller_id)
    return resp.created(listing)


@bp.get("/listings")
def list_listings():
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller", "Buyer", "CertificationReviewer")
    limit, offset = pagination_args()
    items = list(store.listings.values())
    for key in ("seller_id", "certification_program_id", "status", "listing_state"):
        v = request.args.get(key)
        if v is not None:
            items = [l for l in items if str(l.get(key)) == v]
    page, total = paginate(items, limit, offset)
    return resp.listing_ok(page, limit, offset, total)


@bp.get("/listings/<lid>")
def get_listing(lid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller", "Buyer", "CertificationReviewer")
    listing = store.listings.get(lid)
    if not listing:
        raise errors.not_found("Listing not found")
    return resp.ok(listing)


_GRADE_ORDER = {"A": 0, "B": 1, "C": 2}


@bp.post("/listings/<lid>/transition")
def listing_transition(lid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "Seller", "CertificationReviewer")
    data = body()
    action = data.get("action")
    # role-per-action (priority 2 before existence/state)
    if action in ("SUBMIT", "PUBLISH", "WITHDRAW"):
        mw.require_role(ctx, "Seller")
    elif action in ("BEGIN_REVIEW", "CERTIFY"):
        mw.require_role(ctx, "CertificationReviewer")
    else:
        mw.require_role(ctx, "Seller", "CertificationReviewer")
    listing = store.listings.get(lid)
    if not listing:
        raise errors.not_found("Listing not found")
    cur = listing["status"]

    if action == "SUBMIT":
        if cur != "DRAFT":
            raise errors.invalid_state(f"SUBMIT not defined from {cur}")
        mw.require_owner(ctx, listing["seller_id"])
        if listing["listing_kind"] == "PORTFOLIO":
            bulk = listing.get("bulk_price_cents")
            if not isinstance(bulk, int) or bulk <= 0:
                raise errors.validation("PORTFOLIO requires bulk_price_cents > 0 to submit")
        listing["status"] = "SUBMITTED"
        touch(listing)
        svc.recompute_seller(listing["seller_id"])
    elif action == "BEGIN_REVIEW":
        if cur != "SUBMITTED":
            raise errors.invalid_state(f"BEGIN_REVIEW not defined from {cur}")
        verified = any(r["listing_id"] == lid and r["status"] == "VERIFIED"
                       for r in store.reports.values())
        if not verified:
            raise errors.precondition("At least one VERIFIED inspection report is required")
        listing["status"] = "IN_REVIEW"
        touch(listing)
    elif action == "CERTIFY":
        if cur != "IN_REVIEW":
            raise errors.invalid_state(f"CERTIFY not defined from {cur}")
        prog_id = listing.get("certification_program_id")
        prog = store.programs.get(prog_id) if prog_id else None
        latest = svc.latest_verified_report(lid)
        # temporal check (priority 9) before cross-entity preconditions (10)
        if latest is not None:
            insp = _parse_iso(latest["inspection_date"])
            age_days = (store.clock - insp).days
            if age_days > svc.INSPECTION_MAX_AGE_DAYS:
                raise errors.expired("Latest verified inspection is older than INSPECTION_MAX_AGE_DAYS")
        if prog is None or not prog.get("active", False):
            raise errors.precondition("certification_program_id must be set and program active")
        if latest is None:
            raise errors.precondition("A VERIFIED inspection report is required")
        if latest["overall_score"] < prog["min_inspection_score"]:
            raise errors.precondition("overall_score below program minimum")
        if _GRADE_ORDER[latest["title_grade"]] > _GRADE_ORDER[prog["min_title_grade"]]:
            raise errors.precondition("title_grade below program minimum")
        if prog.get("requires_lease_disclosure"):
            ok_lease = any(
                l["listing_id"] == lid and l["disclosure_status"] == "DISCLOSED" and l["status"] == "ACTIVE"
                for l in store.leases.values())
            if not ok_lease:
                raise errors.precondition("A DISCLOSED ACTIVE lease is required")
        listing["status"] = "CERTIFIED"
        listing["certified_at"] = fmt_iso(store.clock)
        touch(listing)
    elif action == "PUBLISH":
        if cur != "CERTIFIED":
            raise errors.invalid_state(f"PUBLISH not defined from {cur}")
        mw.require_owner(ctx, listing["seller_id"])
        listing["status"] = "LISTED"
        touch(listing)
    elif action == "WITHDRAW":
        if cur not in ("IN_REVIEW", "LISTED", "OFFER_PENDING"):
            raise errors.invalid_state(f"WITHDRAW not defined from {cur}")
        mw.require_owner(ctx, listing["seller_id"])
        if cur in ("LISTED", "OFFER_PENDING"):
            accepted = any(o["listing_id"] == lid and o["status"] == "ACCEPTED"
                           for o in store.offers.values())
            if accepted:
                raise errors.precondition("Cannot withdraw: an offer is ACCEPTED")
        listing["status"] = "WITHDRAWN"
        touch(listing)
        if cur in ("LISTED", "OFFER_PENDING"):
            svc.listing_withdraw_cascade(listing)
        else:
            svc.recompute_seller(listing["seller_id"])
    else:
        raise errors.invalid_state(f"Unknown or inapplicable action {action!r}")
    return resp.ok(listing)


# ---------------- Inspection reports ----------------

@bp.post("/listings/<lid>/inspection-reports")
def create_report(lid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "Seller")
    listing = store.listings.get(lid)
    if not listing:
        raise errors.not_found("Listing not found")
    data = body()
    for f in ("overall_score", "roof_score", "systems_score"):
        v = req_int(data, f)
        if v < 0 or v > 100:
            raise errors.validation(f"{f} must be 0-100")
    defects = data.get("disclosed_defects")
    if not isinstance(defects, list):
        raise errors.validation("disclosed_defects must be an array")
    for d in defects:
        if not isinstance(d, dict) or "code" not in d or "description" not in d:
            raise errors.validation("disclosed_defects entries must carry code, severity, description")
        if d.get("severity") not in ("LOW", "MEDIUM", "HIGH"):
            raise errors.validation("severity must be LOW, MEDIUM or HIGH")
    report = stamp_new({
        "id": new_id(),
        "listing_id": lid,
        "inspector_name": req_str(data, "inspector_name"),
        "inspection_date": req_str(data, "inspection_date"),
        "overall_score": data["overall_score"],
        "roof_score": data["roof_score"],
        "systems_score": data["systems_score"],
        "disclosed_defects": defects,
        "title_grade": req_enum(data, "title_grade", {"A", "B", "C"}),
        "submitted_by_seller_id": None,
        "status": "DRAFT",
    })
    store.reports[report["id"]] = report
    return resp.created(report)


@bp.get("/listings/<lid>/inspection-reports")
def list_reports(lid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller", "Buyer", "CertificationReviewer")
    if lid not in store.listings:
        raise errors.not_found("Listing not found")
    limit, offset = pagination_args()
    items = [r for r in store.reports.values() if r["listing_id"] == lid]
    page, total = paginate(items, limit, offset)
    return resp.listing_ok(page, limit, offset, total)


@bp.post("/inspection-reports/<rid>/transition")
def report_transition(rid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "Seller", "CertificationReviewer")
    data = body()
    action = data.get("action")
    if action in ("SUBMIT", "REVISE"):
        mw.require_role(ctx, "Seller")
    elif action in ("VERIFY", "REJECT"):
        mw.require_role(ctx, "CertificationReviewer")
    report = store.reports.get(rid)
    if not report:
        raise errors.not_found("Inspection report not found")
    cur = report["status"]
    listing = store.listings[report["listing_id"]]

    if action == "SUBMIT":
        if cur != "DRAFT":
            raise errors.invalid_state(f"SUBMIT not defined from {cur}")
        if listing["status"] not in ("DRAFT", "SUBMITTED", "IN_REVIEW"):
            raise errors.precondition("Listing must be in DRAFT, SUBMITTED or IN_REVIEW")
        report["submitted_by_seller_id"] = ctx.user_id
        report["status"] = "SUBMITTED"
        touch(report)
    elif action == "VERIFY":
        if cur != "SUBMITTED":
            raise errors.invalid_state(f"VERIFY not defined from {cur}")
        if ctx.user_id == report.get("submitted_by_seller_id"):
            raise errors.segregation("Verifier must differ from submitting seller")
        report["status"] = "VERIFIED"
        touch(report)
    elif action == "REJECT":
        if cur != "SUBMITTED":
            raise errors.invalid_state(f"REJECT not defined from {cur}")
        report["status"] = "REJECTED"
        touch(report)
    elif action == "REVISE":
        if cur != "REJECTED":
            raise errors.invalid_state(f"REVISE not defined from {cur}")
        report["status"] = "DRAFT"
        touch(report)
    else:
        raise errors.invalid_state(f"Unknown or inapplicable action {action!r}")
    return resp.ok(report)
