"""Talent endpoints."""
from flask import Blueprint

import db
import services as svc
from errors import err, parse_pagination, paginate
from middleware import (authenticate, require_role, get_json_body, req_str,
                        opt_int, opt_str)
from response import envelope, envelope_list

bp = Blueprint("talents", __name__)


def talent_public(t):
    return {k: t[k] for k in (
        "id", "stage_name", "legal_name", "email", "status",
        "personal_rate_cents", "business_rate_cents", "advertising_rate_cents",
        "turnaround_hours", "availability", "commission_tier",
        "trailing_gmv_cents", "pending_balance_cents", "paid_out_balance_cents",
        "availability_pause_count_30d", "identity_document_ref",
        "identity_submitted_at", "suggestion_seed_at",
        "suggested_personal_rate_cents",
        "created_at", "updated_at", "version")}


def taxdoc_public(d):
    return {k: d[k] for k in (
        "id", "talent_id", "doc_type", "tax_id_last4", "status",
        "submitted_at", "created_at", "updated_at", "version")}


def payout_public(p):
    return {k: p[k] for k in (
        "id", "talent_id", "status", "total_cents", "period_start",
        "period_end", "paid_at", "created_at", "updated_at", "version")}


def payout_line_public(l):
    return {k: l[k] for k in (
        "id", "talent_id", "order_id", "kind", "amount_cents",
        "settlement_status", "payout_id", "created_at", "updated_at",
        "version")}


def _get_talent(talent_id):
    t = db.talents.get(talent_id)
    if t is None:
        raise err("ERR_NOT_FOUND", "talent %s not found" % talent_id)
    return t


def _require_talent_owner(talent, user_id):
    if user_id != talent["id"]:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "X-User-ID does not match the talent id")


@bp.post("/marketplace/talents")
def create_talent():
    _uid, role = authenticate()
    require_role(role, ["Talent"])
    body = get_json_body()
    stage_name = req_str(body, "stage_name", min_len=1, max_len=80)
    legal_name = req_str(body, "legal_name")
    email = req_str(body, "email")
    identity_document_ref = req_str(body, "identity_document_ref")
    if not identity_document_ref:
        raise err("ERR_INVALID_REQUEST", "identity_document_ref must be non-empty")

    for t in db.talents.values():
        if t["stage_name"].lower() == stage_name.lower() or \
           t["email"].lower() == email.lower():
            raise err("ERR_DUPLICATE_UNIQUE_FIELD",
                      "stage_name or email already registered")

    talent = svc.make_record(db.talents, {
        "stage_name": stage_name,
        "legal_name": legal_name,
        "email": email,
        "status": "PENDING_VERIFICATION",
        "personal_rate_cents": None,
        "business_rate_cents": None,
        "advertising_rate_cents": None,
        "turnaround_hours": None,
        "availability": "BOOKABLE",
        "commission_tier": "STANDARD",
        "trailing_gmv_cents": 0,
        "pending_balance_cents": 0,
        "paid_out_balance_cents": 0,
        "availability_pause_count_30d": 0,
        "identity_document_ref": identity_document_ref,
        "identity_submitted_at": None,
        "suggestion_seed_at": None,
        "suggested_personal_rate_cents": None,
    })
    return envelope(talent_public(talent), "object", 201)


@bp.get("/marketplace/talents/<tid>")
def get_talent(tid):
    _uid, role = authenticate()
    require_role(role, ["Talent", "Buyer", "PlatformAdmin", "Moderator"])
    talent = _get_talent(tid)
    return envelope(talent_public(talent), "object", 200)


@bp.get("/marketplace/talents")
def list_talents():
    _uid, role = authenticate()
    require_role(role, ["Talent", "Buyer", "PlatformAdmin", "Moderator"])
    from flask import request
    limit, offset = parse_pagination(request.args)
    status_f = request.args.get("status")
    avail_f = request.args.get("availability")
    items = [t for t in db.talents.values()
             if (status_f is None or t["status"] == status_f)
             and (avail_f is None or t["availability"] == avail_f)]
    page, total, has_more = paginate(items, limit, offset)
    return envelope_list([talent_public(t) for t in page],
                         limit, offset, total, has_more)


@bp.post("/marketplace/talents/<tid>/identity/submit")
def identity_submit(tid):
    user_id, role = authenticate()
    require_role(role, ["Talent"])
    talent = _get_talent(tid)
    body = get_json_body()
    doc_ref = req_str(body, "identity_document_ref")
    if not doc_ref:
        raise err("ERR_INVALID_REQUEST", "identity_document_ref must be non-empty")
    if talent["status"] != "PENDING_VERIFICATION":
        raise err("ERR_INVALID_STATE",
                  "identity submit requires PENDING_VERIFICATION status")
    _require_talent_owner(talent, user_id)
    talent["identity_document_ref"] = doc_ref
    talent["identity_submitted_at"] = db.iso(db.clock_now())
    talent["status"] = "ID_VERIFIED"
    svc.touch(talent)
    return envelope(talent_public(talent), "object", 200)


@bp.post("/marketplace/talents/<tid>/rates")
def set_rates(tid):
    user_id, role = authenticate()
    require_role(role, ["Talent"])
    talent = _get_talent(tid)
    body = get_json_body()
    personal = opt_int(body, "personal_rate_cents")
    business = opt_int(body, "business_rate_cents")
    advertising = opt_int(body, "advertising_rate_cents")
    turnaround = svc.check_turnaround(body.get("turnaround_hours"))
    expected = opt_int(body, "expected_talent_version")

    # OCC check (priority 6) runs before business rules
    if expected is not None and expected != talent["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_talent_version does not match current version")
    _require_talent_owner(talent, user_id)

    svc.validate_rates(talent, personal, business, advertising)

    talent["personal_rate_cents"] = personal
    talent["business_rate_cents"] = business
    talent["advertising_rate_cents"] = advertising
    talent["turnaround_hours"] = turnaround
    # The trailing 365-day window rolls with the logical clock (PRD §3.5), so
    # a talent write re-derives the windowed sum and recomputes the tier.
    svc.refresh_gmv(talent)
    svc.touch(talent)
    return envelope(talent_public(talent), "object", 200)


@bp.post("/marketplace/talents/<tid>/pause")
def pause_talent(tid):
    user_id, role = authenticate()
    require_role(role, ["Talent"])
    talent = _get_talent(tid)
    get_json_body(required=False)
    if talent["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "pause requires ACTIVE status")
    _require_talent_owner(talent, user_id)
    if talent["availability_pause_count_30d"] >= 3:
        raise err("ERR_PAUSE_RATE_LIMIT",
                  "4th availability pause within trailing 30 days is rejected")
    talent["status"] = "PAUSED"
    talent["availability"] = "PAUSED_AVAILABILITY"
    talent["availability_pause_count_30d"] += 1
    svc.touch(talent)
    return envelope(talent_public(talent), "object", 200)


@bp.post("/marketplace/talents/<tid>/resume")
def resume_talent(tid):
    user_id, role = authenticate()
    require_role(role, ["Talent"])
    talent = _get_talent(tid)
    get_json_body(required=False)
    if talent["status"] != "PAUSED":
        raise err("ERR_INVALID_STATE", "resume requires PAUSED status")
    _require_talent_owner(talent, user_id)
    talent["status"] = "ACTIVE"
    talent["availability"] = "BOOKABLE"
    svc.touch(talent)
    return envelope(talent_public(talent), "object", 200)


@bp.get("/marketplace/talents/<tid>/pricing-suggestion")
def get_pricing_suggestion(tid):
    user_id, role = authenticate()
    require_role(role, ["Talent", "PlatformAdmin"])
    talent = _get_talent(tid)
    if role == "Talent":
        _require_talent_owner(talent, user_id)
    if svc.suggestion_stale_24h(talent):
        if talent["personal_rate_cents"] is None:
            raise err("ERR_INVALID_STATE",
                      "pricing suggestion requires a personal rate to be set")
        svc.compute_suggestion(talent)
    return envelope(talent_public(talent), "object", 200)


@bp.post("/marketplace/talents/<tid>/tax-documents")
def submit_taxdoc(tid):
    user_id, role = authenticate()
    require_role(role, ["Talent"])
    talent = _get_talent(tid)
    body = get_json_body()
    from middleware import req_enum, req_tax_id_last4
    doc_type = req_enum(body, "doc_type", {"W9", "W8BEN"})
    tax_id_last4 = req_tax_id_last4(body)
    _require_talent_owner(talent, user_id)
    doc = svc.make_record(db.tax_documents, {
        "talent_id": talent["id"],
        "doc_type": doc_type,
        "tax_id_last4": tax_id_last4,
        "status": "SUBMITTED",
        "submitted_at": db.iso(db.clock_now()),
    })
    return envelope(taxdoc_public(doc), "object", 201)


@bp.get("/marketplace/talents/<tid>/tax-documents")
def list_taxdocs(tid):
    user_id, role = authenticate()
    require_role(role, ["Talent", "PlatformAdmin"])
    talent = _get_talent(tid)
    if role == "Talent":
        _require_talent_owner(talent, user_id)
    from flask import request
    limit, offset = parse_pagination(request.args)
    status_f = request.args.get("status")
    items = [d for d in db.tax_documents.values()
             if d["talent_id"] == tid and (status_f is None or d["status"] == status_f)]
    page, total, has_more = paginate(items, limit, offset)
    return envelope_list([taxdoc_public(d) for d in page],
                         limit, offset, total, has_more)


@bp.get("/marketplace/talents/<tid>/payouts")
def list_talent_payouts(tid):
    user_id, role = authenticate()
    require_role(role, ["Talent", "PlatformAdmin"])
    talent = _get_talent(tid)
    if role == "Talent":
        _require_talent_owner(talent, user_id)
    from flask import request
    limit, offset = parse_pagination(request.args)
    status_f = request.args.get("status")
    items = [p for p in db.payouts.values()
             if p["talent_id"] == tid and (status_f is None or p["status"] == status_f)]
    page, total, has_more = paginate(items, limit, offset)
    return envelope_list([payout_public(p) for p in page],
                         limit, offset, total, has_more)


@bp.get("/marketplace/talents/<tid>/payout-lines")
def list_talent_payout_lines(tid):
    user_id, role = authenticate()
    require_role(role, ["Talent", "PlatformAdmin"])
    talent = _get_talent(tid)
    if role == "Talent":
        _require_talent_owner(talent, user_id)
    from flask import request
    limit, offset = parse_pagination(request.args)
    ss = request.args.get("settlement_status")
    items = [l for l in db.payout_lines.values()
             if l["talent_id"] == tid and (ss is None or l["settlement_status"] == ss)]
    page, total, has_more = paginate(items, limit, offset)
    return envelope_list([payout_line_public(l) for l in page],
                         limit, offset, total, has_more)
