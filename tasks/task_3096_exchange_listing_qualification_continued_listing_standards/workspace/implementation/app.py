"""Exchange Listing Standards API — Flask entry point."""
import os
from datetime import timedelta

from flask import Flask, request

from core import (ApiError, Ctx, error_response, fmt_dt, get_action_any,
                  get_action_on_issuer, get_appeal_any, get_appeal_on_issuer,
                  get_application_any, get_application_on_issuer,
                  get_deficiency_any, get_deficiency_on_issuer, get_fee_any,
                  get_fee_on_issuer, get_issuer, get_listing_any,
                  get_listing_on_issuer, get_plan_any, get_plan_on_issuer,
                  get_record_any, get_record_on_issuer, get_review,
                  get_snapshot_any, get_snapshot_on_issuer, make_common,
                  make_immutable, new_id, now_dt, now_str, ok_list, ok_object,
                  paginate, parse_dt, require_enum, require_fields,
                  require_int, require_role, require_str, enforce_ownership,
                  set_clock, sort_created, store, touch)
from services import (APPEAL_WINDOW_DAYS, CURE_DAYS, compute_fee,
                      create_compliance_record, effect_reverse_split,
                      evaluate_continued_standards, evaluate_entry_standards,
                      execute_delisting, run_monitor, validate_governance,
                      TIERS)

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def _api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _not_found(e):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(405)
def _method_not_allowed(e):
    return error_response(ApiError("ERR_NOT_FOUND", "Method not allowed", 404))


@app.errorhandler(Exception)
def _unhandled(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INVALID_REQUEST", str(e), 400))


# ================================================================ clock
@app.post("/_clock/set_current_utc")
def clock_set():
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    current_utc = ctx.body.get("current_utc")
    if not isinstance(current_utc, str) or not current_utc:
        raise ApiError("ERR_INVALID_REQUEST", "current_utc required", 400)
    set_clock(current_utc)
    return ok_object({"current_utc": now_str()})


# ================================================================ issuers
@app.post("/issuers")
def create_issuer():
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    require_fields(ctx.body, ["legal_name", "ticker_symbol"])
    legal_name = require_str(ctx.body, "legal_name")
    ticker = require_str(ctx.body, "ticker_symbol")
    for i in store.issuers.values():
        if i["ticker_symbol"] == ticker:
            raise ApiError("ERR_INVALID_REQUEST",
                           "ticker_symbol already in use", 400)
    issuer = make_common({
        "legal_name": legal_name,
        "ticker_symbol": ticker,
        "status": "PRE_LISTING",
    })
    store.issuers[issuer["id"]] = issuer
    return ok_object(issuer, 201)


@app.get("/issuers")
def list_issuers():
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil", "FinanceOfficer"])
    items = list(store.issuers.values())
    status = request.args.get("status")
    if status:
        items = [i for i in items if i["status"] == status]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/issuers/<issuer_id>")
def get_issuer_route(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil", "FinanceOfficer"])
    enforce_ownership(ctx, issuer_id)
    return ok_object(get_issuer(issuer_id))


# ================================================================ applications
APP_INT_FIELDS = [
    "stockholders_equity_cents", "market_value_listed_securities_cents",
    "market_value_unrestricted_publicly_held_cents", "total_revenue_cents",
    "income_from_continuing_operations_cents", "bid_price_cents",
    "publicly_held_shares", "unrestricted_publicly_held_shares",
    "round_lot_holders", "total_shareholders", "market_makers",
    "operating_history_months",
]


@app.post("/issuers/<issuer_id>/listing-applications")
def create_application(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["IssuerOfficer"])
    enforce_ownership(ctx, issuer_id)
    issuer = get_issuer(issuer_id)
    b = ctx.body
    require_fields(b, ["target_tier", "board_directors", "audit_committee",
                       "compensation_committee"] + APP_INT_FIELDS)
    target_tier = require_enum(b, "target_tier", TIERS)
    for f in APP_INT_FIELDS:
        require_int(b, f, minimum=0)
    for arr in ("board_directors", "audit_committee", "compensation_committee"):
        if not isinstance(b[arr], list):
            raise ApiError("ERR_INVALID_REQUEST", f"{arr} must be an array", 400)
    is_transfer = b.get("is_transfer_from_exchange", False)
    if not isinstance(is_transfer, bool):
        raise ApiError("ERR_INVALID_REQUEST",
                       "is_transfer_from_exchange must be boolean", 400)
    readmission = b.get("readmission", False)
    if readmission is True:
        kind = "READMISSION"
    else:
        kind = b.get("application_kind", "INITIAL")
    if kind not in ("INITIAL", "TRANSFER", "TIER_TRANSFER", "READMISSION"):
        raise ApiError("ERR_INVALID_REQUEST", "Invalid application_kind", 400)
    if kind == "READMISSION":
        barred = issuer["status"] != "DELISTED" or any(
            a for a in store.applications.values()
            if a["issuer_id"] == issuer_id and a["readmission_rejected"])
        if barred:
            raise ApiError("ERR_READMISSION_BARRED",
                           "Readmission not permitted for this issuer", 422)
    application = make_common({
        "issuer_id": issuer_id,
        "target_tier": target_tier,
        "is_transfer_from_exchange": is_transfer,
        "application_kind": kind,
        "readmission_rejected": False,
        "board_directors": b["board_directors"],
        "audit_committee": b["audit_committee"],
        "compensation_committee": b["compensation_committee"],
        "stockholders_equity_cents": b["stockholders_equity_cents"],
        "market_value_listed_securities_cents": b["market_value_listed_securities_cents"],
        "market_value_unrestricted_publicly_held_cents": b["market_value_unrestricted_publicly_held_cents"],
        "total_revenue_cents": b["total_revenue_cents"],
        "income_from_continuing_operations_cents": b["income_from_continuing_operations_cents"],
        "bid_price_cents": b["bid_price_cents"],
        "publicly_held_shares": b["publicly_held_shares"],
        "unrestricted_publicly_held_shares": b["unrestricted_publicly_held_shares"],
        "round_lot_holders": b["round_lot_holders"],
        "total_shareholders": b["total_shareholders"],
        "market_makers": b["market_makers"],
        "operating_history_months": b["operating_history_months"],
        "evaluated_standards": [],
        "status": "DRAFT",
    })
    store.applications[application["id"]] = application
    return ok_object(application, 201)


@app.get("/issuers/<issuer_id>/listing-applications")
def list_applications(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    items = [a for a in store.applications.values()
             if a["issuer_id"] == issuer_id]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/listing-applications")
def list_applications_index():
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    items = list(store.applications.values())
    issuer_id = request.args.get("issuer_id")
    if issuer_id:
        items = [a for a in items if a["issuer_id"] == issuer_id]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/listing-applications/<application_id>")
def get_application_index(application_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    return ok_object(get_application_any(application_id))


@app.get("/issuers/<issuer_id>/listing-applications/<application_id>")
def get_application_route(issuer_id, application_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    return ok_object(get_application_on_issuer(issuer_id, application_id))


@app.post("/issuers/<issuer_id>/listing-applications/<application_id>/submit")
def submit_application(issuer_id, application_id):
    ctx = Ctx()
    require_role(ctx, ["IssuerOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    application = get_application_on_issuer(issuer_id, application_id)
    if application["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "Application is not DRAFT", 409)
    if any(a for a in store.applications.values()
           if a["issuer_id"] == issuer_id and a["status"] == "SUBMITTED"
           and a["id"] != application_id):
        raise ApiError("ERR_MULTIPLE_PENDING_APPLICATIONS",
                       "Issuer already has a SUBMITTED application", 409)
    if (application["application_kind"] == "TRANSFER"
            and not application["is_transfer_from_exchange"]):
        raise ApiError("ERR_INVALID_REQUEST",
                       "TRANSFER requires is_transfer_from_exchange", 400)
    validate_governance(application)
    results, any_passed = evaluate_entry_standards(application)
    application["evaluated_standards"] = results
    if any_passed:
        application["status"] = "SUBMITTED"
    else:
        application["status"] = "REJECTED"
        if application["application_kind"] == "READMISSION":
            application["readmission_rejected"] = True
    touch(application)
    return ok_object(application)


@app.post("/issuers/<issuer_id>/listing-applications/<application_id>/approve")
def approve_application(issuer_id, application_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    issuer = get_issuer(issuer_id)
    application = get_application_on_issuer(issuer_id, application_id)
    if application["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Application is not SUBMITTED", 409)
    if not any(s.get("passed") for s in application["evaluated_standards"]):
        raise ApiError("ERR_NO_STANDARD_MET",
                       "No evaluated standard passed", 422)
    listing = None
    if application["application_kind"] == "TIER_TRANSFER":
        listing = next((l for l in store.listings.values()
                        if l["issuer_id"] == issuer_id
                        and l["status"] == "ACTIVE"), None)
        if listing is None:
            raise ApiError("ERR_TIER_TRANSFER_TARGET_INVALID",
                           "Issuer has no ACTIVE listing", 422)
        if TIERS.index(application["target_tier"]) <= TIERS.index(listing["tier"]):
            raise ApiError("ERR_TIER_TRANSFER_TARGET_INVALID",
                           "Target tier must be strictly lower", 422)
        ok = evaluate_continued_standards(
            application["target_tier"],
            application["market_value_listed_securities_cents"],
            application["market_value_unrestricted_publicly_held_cents"],
            application["round_lot_holders"])
        if not ok:
            raise ApiError("ERR_NO_STANDARD_MET",
                           "Continued standards of target tier not met", 422)
    expected = ctx.body.get("expected_issuer_version")
    if expected is not None and expected != issuer["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_issuer_version does not match", 412)

    application["status"] = "APPROVED"
    touch(application)
    touch(issuer)  # increments issuer version
    if application["application_kind"] in ("INITIAL", "TRANSFER", "READMISSION"):
        listing = make_common({
            "issuer_id": issuer_id,
            "application_id": application_id,
            "tier": application["target_tier"],
            "status": "ACTIVE",
            "suspended_at": None,
            "delisted_at": None,
        })
        store.listings[listing["id"]] = listing
        issuer["status"] = "LISTED"
        fee = make_common({
            "issuer_id": issuer_id,
            "fee_kind": "ENTRY",
            "tier": application["target_tier"],
            "assessment_year": now_dt().year,
            "shares_outstanding": application["unrestricted_publicly_held_shares"],
            "amount_cents": compute_fee(
                "ENTRY", application["target_tier"],
                application["unrestricted_publicly_held_shares"]),
            "delisted_mid_year": False,
            "status": "PENDING",
        })
        store.fees[fee["id"]] = fee
        fee["status"] = "INVOICED"
        touch(fee)
    else:  # TIER_TRANSFER
        listing["tier"] = application["target_tier"]
        touch(listing)
    return ok_object(application)


@app.post("/issuers/<issuer_id>/listing-applications/<application_id>/reject")
def reject_application(issuer_id, application_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    get_issuer(issuer_id)
    application = get_application_on_issuer(issuer_id, application_id)
    if application["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Application is not SUBMITTED", 409)
    application["status"] = "REJECTED"
    if application["application_kind"] == "READMISSION":
        application["readmission_rejected"] = True
    touch(application)
    return ok_object(application)


# ================================================================ listings
@app.get("/issuers/<issuer_id>/listings")
def list_listings(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil", "FinanceOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    items = [l for l in store.listings.values() if l["issuer_id"] == issuer_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/listings")
def list_listings_index():
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil", "FinanceOfficer"])
    items = list(store.listings.values())
    for key in ("issuer_id", "application_id", "status", "tier"):
        v = request.args.get(key)
        if v:
            items = [l for l in items if l.get(key) == v]
    if ctx.role == "IssuerOfficer":
        items = [l for l in items if l["issuer_id"] == ctx.user_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/listings/<listing_id>")
def get_listing_index(listing_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil", "FinanceOfficer"])
    listing = get_listing_any(listing_id)
    if ctx.role == "IssuerOfficer" and listing["issuer_id"] != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH",
                       "IssuerOfficer may only view own listings", 403)
    return ok_object(listing)


@app.get("/issuers/<issuer_id>/listings/<listing_id>")
def get_listing_route(issuer_id, listing_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil", "FinanceOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    return ok_object(get_listing_on_issuer(issuer_id, listing_id))


@app.post("/issuers/<issuer_id>/listings/<listing_id>/execute-delisting")
def execute_delisting_route(issuer_id, listing_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    get_issuer(issuer_id)
    listing = get_listing_on_issuer(issuer_id, listing_id)
    if listing["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Listing is not ACTIVE", 409)
    # find a deficiency that authorizes execution
    candidates = [d for d in store.deficiencies.values()
                  if d["issuer_id"] == issuer_id]
    allowed = False
    blocked = False
    now = now_dt()
    for d in candidates:
        appeals = [a for a in store.appeals.values()
                   if a["deficiency_id"] == d["id"]]
        appeal = appeals[0] if appeals else None
        if appeal and appeal["status"] in ("PANEL_REVIEWING", "COUNCIL_REVIEWING"):
            blocked = True
            continue
        if d["status"] == "STAFF_DELIST_DETERMINED" and appeal is None:
            if d["staff_determined_at"] and now > parse_dt(d["staff_determined_at"]) + timedelta(days=APPEAL_WINDOW_DAYS):
                allowed = True
        elif d["status"] == "DELIST_UPHELD" and appeal is not None \
                and appeal["status"] in ("PANEL_AFFIRMED", "COUNCIL_AFFIRMED"):
            allowed = True
    if blocked and not allowed:
        raise ApiError("ERR_DELISTING_BLOCKED",
                       "An appeal is under review", 422)
    if not allowed:
        raise ApiError("ERR_DELISTING_BLOCKED",
                       "Delisting is not final for this listing", 422)
    execute_delisting(listing)
    return ok_object(listing)


# ================================================================ snapshots
@app.post("/issuers/<issuer_id>/market-data-snapshots")
def create_snapshot(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    get_issuer(issuer_id)
    b = ctx.body
    require_fields(b, ["trade_date", "closing_bid_cents",
                       "market_value_publicly_held_cents",
                       "market_value_listed_securities_cents",
                       "round_lot_holders", "total_shareholders"])
    trade_date = require_str(b, "trade_date")
    for f in ("closing_bid_cents", "market_value_publicly_held_cents",
              "market_value_listed_securities_cents", "round_lot_holders",
              "total_shareholders"):
        require_int(b, f, minimum=0)
    clock_date = now_dt().date().isoformat()
    if trade_date != clock_date:
        raise ApiError("ERR_SNAPSHOT_DATE_MISMATCH",
                       "trade_date must equal the logical clock date", 422)
    if any(s for s in store.snapshots.values()
           if s["issuer_id"] == issuer_id and s["trade_date"] == trade_date):
        raise ApiError("ERR_SNAPSHOT_DATE_MISMATCH",
                       "Snapshot already exists for this trade_date", 422)
    snap = make_immutable({
        "issuer_id": issuer_id,
        "trade_date": trade_date,
        "closing_bid_cents": b["closing_bid_cents"],
        "market_value_publicly_held_cents": b["market_value_publicly_held_cents"],
        "market_value_listed_securities_cents": b["market_value_listed_securities_cents"],
        "round_lot_holders": b["round_lot_holders"],
        "total_shareholders": b["total_shareholders"],
    })
    store.snapshots[snap["id"]] = snap
    return ok_object(snap, 201)


@app.get("/issuers/<issuer_id>/market-data-snapshots")
def list_snapshots(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil", "FinanceOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    items = [s for s in store.snapshots.values() if s["issuer_id"] == issuer_id]
    items.sort(key=lambda s: s["trade_date"], reverse=True)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/issuers/<issuer_id>/market-data-snapshots/<snapshot_id>")
def get_snapshot_route(issuer_id, snapshot_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil", "FinanceOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    return ok_object(get_snapshot_on_issuer(issuer_id, snapshot_id))


@app.get("/market-data-snapshots")
def list_snapshots_index():
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    items = list(store.snapshots.values())
    issuer_id = request.args.get("issuer_id")
    if issuer_id:
        items = [s for s in items if s["issuer_id"] == issuer_id]
    trade_date = request.args.get("trade_date")
    if trade_date:
        items = [s for s in items if s["trade_date"] == trade_date]
    items.sort(key=lambda s: s["trade_date"], reverse=True)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/market-data-snapshots/<snapshot_id>")
def get_snapshot_index(snapshot_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    return ok_object(get_snapshot_any(snapshot_id))


# ================================================================ deficiency monitor
@app.post("/issuers/<issuer_id>/deficiency-monitor/run")
def run_monitor_route(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    issuer = get_issuer(issuer_id)
    created, regained = run_monitor(issuer)
    return ok_object({"deficiencies_created": created,
                      "deficiencies_regained": regained})


@app.get("/issuers/<issuer_id>/deficiencies")
def list_deficiencies(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    items = [d for d in store.deficiencies.values()
             if d["issuer_id"] == issuer_id]
    status = request.args.get("status")
    if status:
        items = [d for d in items if d["status"] == status]
    sc = request.args.get("standard_code")
    if sc:
        items = [d for d in items if d["standard_code"] == sc]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/deficiencies")
def list_deficiencies_index():
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "HearingsOfficer", "ListingsCouncil"])
    items = list(store.deficiencies.values())
    for key in ("issuer_id", "status", "standard_code"):
        v = request.args.get(key)
        if v:
            items = [d for d in items if d.get(key) == v]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/deficiencies/<deficiency_id>")
def get_deficiency_index(deficiency_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "HearingsOfficer", "ListingsCouncil"])
    return ok_object(get_deficiency_any(deficiency_id))


@app.get("/deficiencies/<deficiency_id>/compliance-records")
def list_records_for_deficiency(deficiency_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil", "FinanceOfficer"])
    d = get_deficiency_any(deficiency_id)
    enforce_ownership(ctx, d["issuer_id"])
    items = [r for r in store.compliance_records.values()
             if r["deficiency_id"] == deficiency_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/deficiencies/<deficiency_id>/compliance-plans")
def list_plans_for_deficiency(deficiency_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer"])
    d = get_deficiency_any(deficiency_id)
    enforce_ownership(ctx, d["issuer_id"])
    items = [p for p in store.plans.values()
             if p["deficiency_id"] == deficiency_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/deficiencies/<deficiency_id>/appeals")
def list_appeals_for_deficiency(deficiency_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil"])
    d = get_deficiency_any(deficiency_id)
    enforce_ownership(ctx, d["issuer_id"])
    items = [a for a in store.appeals.values()
             if a["deficiency_id"] == deficiency_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/issuers/<issuer_id>/deficiencies/<deficiency_id>")
def get_deficiency_route(issuer_id, deficiency_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    return ok_object(get_deficiency_on_issuer(issuer_id, deficiency_id))


@app.post("/issuers/<issuer_id>/deficiencies/<deficiency_id>/staff-determine-delisting")
def staff_determine(issuer_id, deficiency_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    get_issuer(issuer_id)
    d = get_deficiency_on_issuer(issuer_id, deficiency_id)
    now = now_dt()
    if d["status"] == "OPEN":
        if now <= parse_dt(d["compliance_due_at"]):
            raise ApiError("ERR_CURE_PERIOD_ACTIVE",
                           "Cure period has not lapsed", 422)
    elif d["status"] == "PLAN_SUBMITTED":
        plan = next((p for p in store.plans.values()
                     if p["deficiency_id"] == deficiency_id), None)
        plan_rejected = plan is not None and plan["status"] == "REJECTED"
        if not plan_rejected and now <= parse_dt(d["compliance_due_at"]):
            raise ApiError("ERR_CURE_PERIOD_ACTIVE",
                           "Cure period has not lapsed and plan not rejected",
                           422)
    else:
        raise ApiError("ERR_INVALID_STATE",
                       "Deficiency is not OPEN or PLAN_SUBMITTED", 409)
    d["status"] = "STAFF_DELIST_DETERMINED"
    d["staff_determined_at"] = now_str()
    touch(d)
    return ok_object(d)


# ================================================================ compliance records
@app.get("/issuers/<issuer_id>/compliance-records")
def list_records(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil", "FinanceOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    items = [r for r in store.compliance_records.values()
             if r["issuer_id"] == issuer_id]
    def_id = request.args.get("deficiency_id")
    if def_id:
        items = [r for r in items if r["deficiency_id"] == def_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/issuers/<issuer_id>/compliance-records/<record_id>")
def get_record_route(issuer_id, record_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil", "FinanceOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    return ok_object(get_record_on_issuer(issuer_id, record_id))


@app.get("/compliance-records")
def list_records_index():
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "FinanceOfficer"])
    items = list(store.compliance_records.values())
    issuer_id = request.args.get("issuer_id")
    if issuer_id:
        items = [r for r in items if r["issuer_id"] == issuer_id]
    method = request.args.get("method")
    if method:
        items = [r for r in items if r["method"] == method]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/compliance-records/<record_id>")
def get_record_index(record_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "FinanceOfficer"])
    return ok_object(get_record_any(record_id))


# ================================================================ compliance plans
@app.post("/issuers/<issuer_id>/compliance-plans")
def create_plan(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["IssuerOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    b = ctx.body
    require_fields(b, ["deficiency_id", "plan_text", "plan_kind"])
    deficiency_id = require_str(b, "deficiency_id")
    require_str(b, "plan_text")
    plan_kind = require_enum(b, "plan_kind", ["CURE_IN_PLACE", "TIER_TRANSFER"])
    d = get_deficiency_on_issuer(issuer_id, deficiency_id)
    if d["status"] != "OPEN":
        raise ApiError("ERR_PLAN_NOT_ALLOWED",
                       "Deficiency is not OPEN", 422)
    if now_dt() >= parse_dt(d["compliance_due_at"]):
        raise ApiError("ERR_PLAN_NOT_ALLOWED",
                       "Cure period has lapsed", 422)
    if any(p for p in store.plans.values()
           if p["deficiency_id"] == deficiency_id):
        raise ApiError("ERR_PLAN_NOT_ALLOWED",
                       "A plan already exists for this deficiency", 422)
    proposed = b.get("proposed_target_tier")
    if plan_kind == "TIER_TRANSFER":
        if proposed is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "proposed_target_tier required for TIER_TRANSFER",
                           400)
        if proposed not in TIERS:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Invalid proposed_target_tier", 400)
        if TIERS.index(proposed) <= TIERS.index(d["tier_at_detection"]):
            raise ApiError("ERR_TIER_TRANSFER_TARGET_INVALID",
                           "proposed_target_tier must be strictly lower", 422)
    plan = make_common({
        "issuer_id": issuer_id,
        "deficiency_id": deficiency_id,
        "plan_text": b["plan_text"],
        "plan_kind": plan_kind,
        "proposed_target_tier": proposed,
        "status": "PENDING_REVIEW",
        "review_decision_reason": None,
        "filed_by": ctx.user_id,
    })
    store.plans[plan["id"]] = plan
    d["status"] = "PLAN_SUBMITTED"
    touch(d)
    return ok_object(plan, 201)


@app.get("/issuers/<issuer_id>/compliance-plans")
def list_plans(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    items = [p for p in store.plans.values() if p["issuer_id"] == issuer_id]
    def_id = request.args.get("deficiency_id")
    if def_id:
        items = [p for p in items if p["deficiency_id"] == def_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/issuers/<issuer_id>/compliance-plans/<plan_id>")
def get_plan_route(issuer_id, plan_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    return ok_object(get_plan_on_issuer(issuer_id, plan_id))


@app.get("/compliance-plans")
def list_plans_index():
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    items = list(store.plans.values())
    issuer_id = request.args.get("issuer_id")
    if issuer_id:
        items = [p for p in items if p["issuer_id"] == issuer_id]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/compliance-plans/<plan_id>")
def get_plan_index(plan_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    return ok_object(get_plan_any(plan_id))


@app.post("/issuers/<issuer_id>/compliance-plans/<plan_id>/review")
def review_plan(issuer_id, plan_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    get_issuer(issuer_id)
    plan = get_plan_on_issuer(issuer_id, plan_id)
    b = ctx.body
    require_fields(b, ["decision", "review_decision_reason"])
    decision = require_enum(b, "decision", ["APPROVE", "REJECT"])
    if plan["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_PLAN_UNDER_REVIEW",
                       "Plan has already been decided", 409)
    d = get_deficiency_on_issuer(issuer_id, plan["deficiency_id"])
    if d["status"] != "PLAN_SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Deficiency is not PLAN_SUBMITTED", 409)
    if plan.get("filed_by") == ctx.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Plan filer may not review the plan", 403)
    if decision == "APPROVE" and plan["plan_kind"] == "TIER_TRANSFER":
        listing = next((l for l in store.listings.values()
                        if l["issuer_id"] == issuer_id
                        and l["status"] == "ACTIVE"), None)
        if listing is None or \
                TIERS.index(plan["proposed_target_tier"]) <= TIERS.index(listing["tier"]):
            raise ApiError("ERR_TIER_TRANSFER_TARGET_INVALID",
                           "proposed_target_tier must be strictly lower than "
                           "the listing's current tier", 422)
        snap = None
        snaps = [s for s in store.snapshots.values()
                 if s["issuer_id"] == issuer_id]
        if snaps:
            snap = max(snaps, key=lambda s: s["trade_date"])
        if snap is None:
            raise ApiError("ERR_TIER_TRANSFER_TARGET_INVALID",
                           "No market data snapshot available", 422)
        ok = evaluate_continued_standards(
            plan["proposed_target_tier"],
            snap["market_value_listed_securities_cents"],
            snap["market_value_publicly_held_cents"],
            snap["round_lot_holders"])
        if not ok:
            raise ApiError("ERR_TIER_TRANSFER_TARGET_INVALID",
                           "Continued standards of proposed tier not met", 422)
    plan["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    plan["review_decision_reason"] = b["review_decision_reason"]
    touch(plan)
    if decision == "APPROVE":
        method = "TIER_TRANSFER" if plan["plan_kind"] == "TIER_TRANSFER" \
            else "PLAN_APPROVED"
        d["status"] = "REGAINED"
        d["still_open"] = False
        d["closed_at"] = now_str()
        touch(d)
        create_compliance_record(issuer_id, d["id"], method, 0)
        if plan["plan_kind"] == "TIER_TRANSFER":
            listing = next((l for l in store.listings.values()
                            if l["issuer_id"] == issuer_id
                            and l["status"] == "ACTIVE"), None)
            if listing is not None:
                listing["tier"] = plan["proposed_target_tier"]
                touch(listing)
    return ok_object(plan)


# ================================================================ hearings reviews
@app.post("/hearings-reviews")
def create_review():
    ctx = Ctx()
    require_role(ctx, ["HearingsOfficer"])
    b = ctx.body
    require_fields(b, ["issuer_id", "panel_name"])
    issuer_id = require_str(b, "issuer_id")
    require_str(b, "panel_name")
    get_issuer(issuer_id)
    review = make_common({
        "issuer_id": issuer_id,
        "panel_name": b["panel_name"],
        "status": "OPEN",
    })
    store.reviews[review["id"]] = review
    return ok_object(review, 201)


@app.get("/hearings-reviews")
def list_reviews():
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil"])
    items = list(store.reviews.values())
    issuer_id = request.args.get("issuer_id")
    if issuer_id:
        items = [r for r in items if r["issuer_id"] == issuer_id]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    if ctx.role == "IssuerOfficer":
        items = [r for r in items if r["issuer_id"] == ctx.user_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/hearings-reviews/<review_id>")
def get_review_route(review_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil"])
    review = get_review(review_id)
    if ctx.role == "IssuerOfficer" and review["issuer_id"] != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH",
                       "IssuerOfficer may only view own issuer's panels", 403)
    return ok_object(review)


@app.post("/hearings-reviews/<review_id>/close")
def close_review(review_id):
    ctx = Ctx()
    require_role(ctx, ["HearingsOfficer"])
    review = get_review(review_id)
    if review["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Panel is not OPEN", 409)
    review["status"] = "CLOSED"
    touch(review)
    return ok_object(review)


@app.get("/issuers/<issuer_id>/hearings-reviews")
def list_reviews_for_issuer(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    items = [r for r in store.reviews.values() if r["issuer_id"] == issuer_id]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/hearings-reviews/<review_id>/appeals")
def list_appeals_for_review(review_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil"])
    review = get_review(review_id)
    if ctx.role == "IssuerOfficer" and review["issuer_id"] != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH",
                       "IssuerOfficer may only view own issuer's panels", 403)
    items = [a for a in store.appeals.values() if a["review_id"] == review_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


# ================================================================ appeals
@app.post("/issuers/<issuer_id>/appeals")
def create_appeal(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["IssuerOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    b = ctx.body
    require_fields(b, ["deficiency_id", "review_id"])
    deficiency_id = require_str(b, "deficiency_id")
    review_id = require_str(b, "review_id")
    d = get_deficiency_on_issuer(issuer_id, deficiency_id)
    review = get_review(review_id)
    if review["status"] != "OPEN":
        raise ApiError("ERR_HEARING_NOT_OPEN",
                       "HearingsReview is not OPEN", 422)
    if d["status"] != "STAFF_DELIST_DETERMINED":
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED",
                       "Deficiency is not STAFF_DELIST_DETERMINED", 422)
    if any(a for a in store.appeals.values()
           if a["deficiency_id"] == deficiency_id):
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED",
                       "An appeal already exists for this deficiency", 422)
    if now_dt() > parse_dt(d["staff_determined_at"]) + timedelta(days=APPEAL_WINDOW_DAYS):
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED",
                       "Appeal window has closed", 422)
    appeal = make_common({
        "issuer_id": issuer_id,
        "deficiency_id": deficiency_id,
        "review_id": review_id,
        "filed_at": now_str(),
        "decided_by": None,
        "status": "FILED",
        "filed_by": ctx.user_id,
    })
    store.appeals[appeal["id"]] = appeal
    d["status"] = "PANEL_REVIEW"
    touch(d)
    return ok_object(appeal, 201)


@app.get("/issuers/<issuer_id>/appeals")
def list_appeals(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    items = [a for a in store.appeals.values() if a["issuer_id"] == issuer_id]
    def_id = request.args.get("deficiency_id")
    if def_id:
        items = [a for a in items if a["deficiency_id"] == def_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/issuers/<issuer_id>/appeals/<appeal_id>")
def get_appeal_route(issuer_id, appeal_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    return ok_object(get_appeal_on_issuer(issuer_id, appeal_id))


@app.get("/appeals")
def list_appeals_index():
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "HearingsOfficer", "ListingsCouncil"])
    items = list(store.appeals.values())
    for key in ("issuer_id", "review_id", "status"):
        v = request.args.get(key)
        if v:
            items = [a for a in items if a.get(key) == v]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/appeals/<appeal_id>")
def get_appeal_index(appeal_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "HearingsOfficer", "ListingsCouncil"])
    return ok_object(get_appeal_any(appeal_id))


def _reverse_deficiency(d):
    """Close d as DELIST_REVERSED and open a fresh deficiency row."""
    d["status"] = "DELIST_REVERSED"
    d["closed_at"] = now_str()
    touch(d)
    now = now_dt()
    new_d = make_common({
        "issuer_id": d["issuer_id"],
        "standard_code": d["standard_code"],
        "tier_at_detection": d["tier_at_detection"],
        "consecutive_days_failed": d["consecutive_days_failed"],
        "detected_at": now_str(),
        "compliance_due_at": fmt_dt(now + timedelta(days=CURE_DAYS)),
        "staff_determined_at": None,
        "still_open": True,
        "status": "OPEN",
        "closed_at": None,
    })
    store.deficiencies[new_d["id"]] = new_d


@app.post("/issuers/<issuer_id>/appeals/<appeal_id>/panel-review")
def panel_review(issuer_id, appeal_id):
    ctx = Ctx()
    require_role(ctx, ["HearingsOfficer"])
    get_issuer(issuer_id)
    appeal = get_appeal_on_issuer(issuer_id, appeal_id)
    if appeal["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", "Appeal is not FILED", 409)
    review = get_review(appeal["review_id"])
    if review["status"] != "OPEN":
        raise ApiError("ERR_HEARING_NOT_OPEN",
                       "HearingsReview is not OPEN", 422)
    appeal["status"] = "PANEL_REVIEWING"
    touch(appeal)
    d = store.deficiencies.get(appeal["deficiency_id"])
    if d is not None and d["status"] == "STAFF_DELIST_DETERMINED":
        d["status"] = "PANEL_REVIEW"
        touch(d)
    return ok_object(appeal)


@app.post("/issuers/<issuer_id>/appeals/<appeal_id>/panel-decision")
def panel_decision(issuer_id, appeal_id):
    ctx = Ctx()
    require_role(ctx, ["HearingsOfficer"])
    get_issuer(issuer_id)
    appeal = get_appeal_on_issuer(issuer_id, appeal_id)
    decision = require_enum(ctx.body, "decision", ["AFFIRM", "REVERSE"])
    if appeal["status"] != "PANEL_REVIEWING":
        raise ApiError("ERR_INVALID_STATE",
                       "Appeal is not PANEL_REVIEWING", 409)
    if appeal.get("filed_by") == ctx.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Appeal filer may not decide the appeal", 403)
    d = store.deficiencies.get(appeal["deficiency_id"])
    if decision == "AFFIRM":
        appeal["status"] = "PANEL_AFFIRMED"
        appeal["decided_by"] = "PANEL"
        touch(appeal)
        if d is not None and d["status"] == "PANEL_REVIEW":
            d["status"] = "DELIST_UPHELD"
            d["closed_at"] = now_str()
            touch(d)
    else:
        appeal["status"] = "PANEL_REVERSED"
        appeal["decided_by"] = "PANEL"
        touch(appeal)
        if d is not None and d["status"] == "PANEL_REVIEW":
            _reverse_deficiency(d)
    return ok_object(appeal)


@app.post("/issuers/<issuer_id>/appeals/<appeal_id>/council-review")
def council_review(issuer_id, appeal_id):
    ctx = Ctx()
    require_role(ctx, ["ListingsCouncil"])
    get_issuer(issuer_id)
    appeal = get_appeal_on_issuer(issuer_id, appeal_id)
    if appeal["status"] not in ("PANEL_AFFIRMED", "PANEL_REVERSED"):
        raise ApiError("ERR_COUNCIL_REVIEW_NOT_AVAILABLE",
                       "Council review requires PANEL_AFFIRMED or "
                       "PANEL_REVERSED", 422)
    appeal["status"] = "COUNCIL_REVIEWING"
    touch(appeal)
    return ok_object(appeal)


@app.post("/issuers/<issuer_id>/appeals/<appeal_id>/council-decision")
def council_decision(issuer_id, appeal_id):
    ctx = Ctx()
    require_role(ctx, ["ListingsCouncil"])
    get_issuer(issuer_id)
    appeal = get_appeal_on_issuer(issuer_id, appeal_id)
    decision = require_enum(ctx.body, "decision", ["AFFIRM", "REVERSE"])
    if appeal["status"] != "COUNCIL_REVIEWING":
        raise ApiError("ERR_INVALID_STATE",
                       "Appeal is not COUNCIL_REVIEWING", 409)
    if appeal.get("filed_by") == ctx.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Appeal filer may not decide the appeal", 403)
    d = store.deficiencies.get(appeal["deficiency_id"])
    if decision == "AFFIRM":
        appeal["status"] = "COUNCIL_AFFIRMED"
        appeal["decided_by"] = "COUNCIL"
        touch(appeal)
        if d is not None and d["status"] == "PANEL_REVIEW":
            d["status"] = "DELIST_UPHELD"
            d["closed_at"] = now_str()
            touch(d)
    else:
        appeal["status"] = "COUNCIL_REVERSED"
        appeal["decided_by"] = "COUNCIL"
        touch(appeal)
        # PRD §3.7: council REVERSE "transitions the deficiency to
        # DELIST_REVERSED with the same new-OPEN-deficiency side effect as a
        # panel reversal" — unconditional, even after a panel AFFIRM closed
        # the deficiency as DELIST_UPHELD.
        if d is not None and d["status"] in ("PANEL_REVIEW", "DELIST_UPHELD"):
            _reverse_deficiency(d)
    return ok_object(appeal)


# ================================================================ fee assessments
@app.post("/issuers/<issuer_id>/fee-assessments/run-annual-fees")
def run_annual_fees(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["FinanceOfficer"])
    issuer = get_issuer(issuer_id)
    b = ctx.body
    require_fields(b, ["shares_outstanding"])
    shares = require_int(b, "shares_outstanding", minimum=0)
    listing = next((l for l in store.listings.values()
                    if l["issuer_id"] == issuer_id
                    and l["status"] == "ACTIVE"), None)
    clock_year = now_dt().year
    already = any(f for f in store.fees.values()
                  if f["issuer_id"] == issuer_id and f["fee_kind"] == "ANNUAL"
                  and f["assessment_year"] == clock_year)
    if issuer["status"] != "LISTED" or listing is None or already or shares < 1:
        raise ApiError("ERR_FEE_ALREADY_ASSESSED",
                       "Annual fee cannot be assessed", 409)
    expected = b.get("expected_issuer_version")
    if expected is not None and expected != issuer["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_issuer_version does not match", 412)
    fee = make_common({
        "issuer_id": issuer_id,
        "fee_kind": "ANNUAL",
        "tier": listing["tier"],
        "assessment_year": clock_year,
        "shares_outstanding": shares,
        "amount_cents": compute_fee("ANNUAL", listing["tier"], shares),
        "delisted_mid_year": False,
        "status": "PENDING",
    })
    store.fees[fee["id"]] = fee
    fee["status"] = "INVOICED"
    touch(fee)
    touch(issuer)  # increments issuer version
    return ok_object(fee, 201)


@app.get("/issuers/<issuer_id>/fee-assessments")
def list_fees(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "FinanceOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    items = [f for f in store.fees.values() if f["issuer_id"] == issuer_id]
    for key in ("fee_kind", "status"):
        v = request.args.get(key)
        if v:
            items = [f for f in items if f.get(key) == v]
    year = request.args.get("assessment_year")
    if year:
        try:
            y = int(year)
            items = [f for f in items if f["assessment_year"] == y]
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST",
                           "assessment_year must be an integer", 400)
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/issuers/<issuer_id>/fee-assessments/<fee_id>")
def get_fee_route(issuer_id, fee_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "FinanceOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    return ok_object(get_fee_on_issuer(issuer_id, fee_id))


@app.get("/fee-assessments")
def list_fees_index():
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "FinanceOfficer"])
    items = list(store.fees.values())
    for key in ("issuer_id", "fee_kind", "status"):
        v = request.args.get(key)
        if v:
            items = [f for f in items if f.get(key) == v]
    year = request.args.get("assessment_year")
    if year:
        try:
            y = int(year)
            items = [f for f in items if f["assessment_year"] == y]
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST",
                           "assessment_year must be an integer", 400)
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/fee-assessments/<fee_id>")
def get_fee_index(fee_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "FinanceOfficer"])
    return ok_object(get_fee_any(fee_id))


@app.post("/issuers/<issuer_id>/fee-assessments/<fee_id>/mark-paid")
def mark_paid(issuer_id, fee_id):
    ctx = Ctx()
    require_role(ctx, ["FinanceOfficer"])
    get_issuer(issuer_id)
    fee = get_fee_on_issuer(issuer_id, fee_id)
    if fee["status"] != "INVOICED":
        raise ApiError("ERR_INVALID_STATE", "Fee is not INVOICED", 409)
    fee["status"] = "PAID"
    touch(fee)
    return ok_object(fee)


@app.post("/issuers/<issuer_id>/fee-assessments/<fee_id>/waive")
def waive_fee(issuer_id, fee_id):
    ctx = Ctx()
    require_role(ctx, ["FinanceOfficer"])
    get_issuer(issuer_id)
    fee = get_fee_on_issuer(issuer_id, fee_id)
    if fee["status"] != "INVOICED":
        raise ApiError("ERR_INVALID_STATE", "Fee is not INVOICED", 409)
    fee["status"] = "WAIVED"
    touch(fee)
    return ok_object(fee)


# ================================================================ corporate actions
@app.post("/issuers/<issuer_id>/corporate-actions")
def create_action(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["IssuerOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    b = ctx.body
    require_fields(b, ["action_type", "split_ratio_denominator"])
    action_type = require_enum(b, "action_type", ["REVERSE_SPLIT"])
    denom = require_int(b, "split_ratio_denominator", minimum=2)
    action = make_common({
        "issuer_id": issuer_id,
        "action_type": action_type,
        "split_ratio_denominator": denom,
        "announced_at": now_str(),
        "status": "SUBMITTED",
    })
    store.actions[action["id"]] = action
    return ok_object(action, 201)


@app.get("/issuers/<issuer_id>/corporate-actions")
def list_actions(issuer_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil", "FinanceOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    items = [a for a in store.actions.values() if a["issuer_id"] == issuer_id]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/issuers/<issuer_id>/corporate-actions/<action_id>")
def get_action_route(issuer_id, action_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst", "IssuerOfficer", "HearingsOfficer",
                       "ListingsCouncil", "FinanceOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    return ok_object(get_action_on_issuer(issuer_id, action_id))


@app.get("/corporate-actions")
def list_actions_index():
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    items = list(store.actions.values())
    issuer_id = request.args.get("issuer_id")
    if issuer_id:
        items = [a for a in items if a["issuer_id"] == issuer_id]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@app.get("/corporate-actions/<action_id>")
def get_action_index(action_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    return ok_object(get_action_any(action_id))


@app.post("/issuers/<issuer_id>/corporate-actions/<action_id>/effect")
def effect_action(issuer_id, action_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    issuer = get_issuer(issuer_id)
    action = get_action_on_issuer(issuer_id, action_id)
    if action["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Action is not SUBMITTED", 409)
    effect_reverse_split(issuer, action)
    return ok_object(action)


@app.post("/issuers/<issuer_id>/corporate-actions/<action_id>/reject")
def reject_action(issuer_id, action_id):
    ctx = Ctx()
    require_role(ctx, ["ListingAnalyst"])
    get_issuer(issuer_id)
    action = get_action_on_issuer(issuer_id, action_id)
    if action["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Action is not SUBMITTED", 409)
    action["status"] = "REJECTED"
    touch(action)
    return ok_object(action)


@app.post("/issuers/<issuer_id>/corporate-actions/<action_id>/cancel")
def cancel_action(issuer_id, action_id):
    ctx = Ctx()
    require_role(ctx, ["IssuerOfficer"])
    enforce_ownership(ctx, issuer_id)
    get_issuer(issuer_id)
    action = get_action_on_issuer(issuer_id, action_id)
    if action["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Action is not SUBMITTED", 409)
    action["status"] = "CANCELLED"
    touch(action)
    return ok_object(action)


# ================================================================ boot
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
