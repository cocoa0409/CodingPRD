"""Routes: property managers, management referrals, guarantees, disputes."""
from datetime import timedelta

from flask import Blueprint, request

import errors
import middleware as mw
import response as resp
import services as svc
from db import store, _parse_iso, fmt_iso
from helpers import (body, new_id, stamp_new, touch, pagination_args, paginate,
                     req_str, req_int, opt_bool, req_enum)

bp = Blueprint("closing", __name__)


# ---------------- Property managers ----------------

@bp.post("/property-managers")
def create_pm():
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin")
    data = body()
    markets = data.get("markets")
    if not isinstance(markets, list) or not all(isinstance(m, str) for m in markets):
        raise errors.validation("markets must be an array of state codes")
    onb = req_int(data, "onboarding_fee_bps")
    if onb < 0 or onb > 2000:
        raise errors.validation("onboarding_fee_bps must be 0-2000")
    mf = req_int(data, "monthly_fee_bps")
    if mf < 0 or mf > 3000:
        raise errors.validation("monthly_fee_bps must be 0-3000")
    pm = stamp_new({
        "id": new_id(),
        "company_name": req_str(data, "company_name"),
        "markets": markets,
        "onboarding_fee_bps": onb,
        "monthly_fee_bps": mf,
        "active": opt_bool(data, "active", True),
    })
    store.pms[pm["id"]] = pm
    return resp.created(pm)


# ---------------- Management referrals ----------------

@bp.post("/listings/<lid>/management-referrals")
def create_referral(lid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller")
    listing = store.listings.get(lid)
    if not listing:
        raise errors.not_found("Listing not found")
    if ctx.role == "Seller" and ctx.user_id != listing["seller_id"]:
        raise errors.forbidden()
    data = body()
    pm_id = req_str(data, "property_manager_id")
    if pm_id not in store.pms:
        raise errors.not_found("PropertyManager not found")
    ref = stamp_new({
        "id": new_id(),
        "listing_id": lid,
        "property_manager_id": pm_id,
        "status": "REFERRED",
        "onboarding_fee_cents": None,
        "lease_continuity_confirmed": False,
    })
    store.referrals[ref["id"]] = ref
    return resp.created(ref)


@bp.get("/management-referrals")
def list_referrals():
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller", "Buyer", "PropertyManager")
    limit, offset = pagination_args()
    items = list(store.referrals.values())
    for key in ("listing_id", "property_manager_id"):
        v = request.args.get(key)
        if v is not None:
            items = [r for r in items if r.get(key) == v]
    page, total = paginate(items, limit, offset)
    return resp.listing_ok(page, limit, offset, total)


@bp.get("/management-referrals/<rid>")
def get_referral(rid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller", "Buyer", "PropertyManager")
    ref = store.referrals.get(rid)
    if not ref:
        raise errors.not_found("ManagementReferral not found")
    return resp.ok(ref)


@bp.post("/management-referrals/<rid>/transition")
def referral_transition(rid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PropertyManager")
    data = body()
    action = data.get("action")
    ref = store.referrals.get(rid)
    if not ref:
        raise errors.not_found("ManagementReferral not found")
    mw.require_owner(ctx, ref["property_manager_id"])
    cur = ref["status"]
    pm = store.pms[ref["property_manager_id"]]
    listing = store.listings[ref["listing_id"]]

    if action == "ACCEPT":
        if cur != "REFERRED":
            raise errors.invalid_state(f"ACCEPT not defined from {cur}")
        if not pm.get("active"):
            raise errors.precondition("PropertyManager is not active")
        if listing["listing_state"] not in pm.get("markets", []):
            raise errors.precondition("Listing state not in PropertyManager markets")
        ref["status"] = "ACCEPTED"
        touch(ref)
    elif action == "DECLINE":
        if cur != "REFERRED":
            raise errors.invalid_state(f"DECLINE not defined from {cur}")
        ref["status"] = "DECLINED"
        touch(ref)
    else:
        raise errors.invalid_state(f"Unknown or inapplicable action {action!r}")
    return resp.ok(ref)


# ---------------- Guarantees ----------------

@bp.post("/listings/<lid>/guarantees")
def create_guarantee(lid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin")
    listing = store.listings.get(lid)
    if not listing:
        raise errors.not_found("Listing not found")
    data = body()
    kind = req_enum(data, "guarantee_kind", {"VACANCY", "LEASE_UP"})
    months = req_int(data, "coverage_months")
    if months < 1:
        raise errors.validation("coverage_months must be >= 1")
    prog = store.programs.get(listing.get("certification_program_id"))
    cap = prog["guarantee_months_cap"] if prog else 0
    if months > cap:
        raise errors.validation("coverage_months exceeds program guarantee_months_cap")
    if listing["status"] not in ("CERTIFIED", "LISTED"):
        raise errors.precondition("Guarantee issuable only on CERTIFIED or LISTED listings")
    g = stamp_new({
        "id": new_id(),
        "listing_id": lid,
        "guarantee_kind": kind,
        "coverage_months": months,
        "status": "ISSUED",
        "claim_amount_cents": None,
        "claimed_at": None,
    })
    store.guarantees[g["id"]] = g
    return resp.created(g)


@bp.get("/listings/<lid>/guarantees")
def list_guarantees(lid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller", "Buyer", "ClaimsAdjuster")
    if lid not in store.listings:
        raise errors.not_found("Listing not found")
    limit, offset = pagination_args()
    items = [g for g in store.guarantees.values() if g["listing_id"] == lid]
    page, total = paginate(items, limit, offset)
    return resp.listing_ok(page, limit, offset, total)


@bp.post("/guarantees/<gid>/transition")
def guarantee_transition(gid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "Buyer", "ClaimsAdjuster")
    data = body()
    action = data.get("action")
    if action == "CLAIM":
        mw.require_role(ctx, "Buyer")
    elif action in ("PAY", "DENY"):
        mw.require_role(ctx, "ClaimsAdjuster")
    g = store.guarantees.get(gid)
    if not g:
        raise errors.not_found("Guarantee not found")
    cur = g["status"]

    if action == "CLAIM":
        if cur != "ACTIVE":
            raise errors.invalid_state(f"CLAIM not defined from {cur}")
        listing = store.listings[g["listing_id"]]
        # claimant must own the ACCEPTED offer for the listing
        accepted = [o for o in store.offers.values()
                    if o["listing_id"] == listing["id"] and o["status"] == "ACCEPTED"]
        if not accepted or accepted[0]["buyer_id"] != ctx.user_id:
            raise errors.forbidden("Only the buyer of the accepted offer may claim")
        # temporal: claim window = coverage_months * 30 days from SOLD timestamp
        sold_at = _parse_iso(listing["sold_at"])
        window_end = sold_at + timedelta(days=g["coverage_months"] * svc.DAYS_PER_MONTH)
        if store.clock > window_end:
            raise errors.expired("Claim window has passed")
        # kind-specific claim conditions
        lease_ids = {l["id"] for l in store.leases.values() if l["listing_id"] == listing["id"]}
        if not lease_ids:
            # no lease history exists at all to price the claim
            raise errors.not_claimable("No lease history exists to price the claim")
        if g["guarantee_kind"] == "VACANCY":
            active_or_assigned = any(
                l["listing_id"] == listing["id"] and l["status"] in ("ACTIVE", "ASSIGNED")
                for l in store.leases.values())
            if active_or_assigned:
                raise errors.not_claimable("A lease is still ACTIVE or ASSIGNED")
        else:  # LEASE_UP
            qualifying = False
            for p in store.payments.values():
                if p["lease_id"] not in lease_ids:
                    continue
                due = _parse_iso(p["due_date"])
                if sold_at <= due <= store.clock and (p.get("paid_date") is None or p.get("late")):
                    qualifying = True
                    break
            if not qualifying:
                raise errors.not_claimable("No qualifying unpaid/late payment record in window")
        amount = svc.compute_claim_amount(g, listing)
        g["status"] = "CLAIMED"
        g["claimed_at"] = fmt_iso(store.clock)
        g["claim_amount_cents"] = amount
        touch(g)
    elif action == "PAY":
        if cur != "CLAIMED":
            raise errors.invalid_state(f"PAY not defined from {cur}")
        g["status"] = "PAID"
        touch(g)
    elif action == "DENY":
        if cur != "CLAIMED":
            raise errors.invalid_state(f"DENY not defined from {cur}")
        g["status"] = "VOID"
        touch(g)
    else:
        raise errors.invalid_state(f"Unknown or inapplicable action {action!r}")
    return resp.ok(g)


# ---------------- Disputes ----------------

@bp.post("/listings/<lid>/disputes")
def create_dispute(lid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "Buyer", "Seller")
    listing = store.listings.get(lid)
    if not listing:
        raise errors.not_found("Listing not found")
    data = body()
    opened_by = req_enum(data, "opened_by", {"BUYER", "SELLER"})
    condition_code = req_str(data, "condition_code")
    remedy = req_int(data, "remedy_cents")
    if remedy < 0:
        raise errors.validation("remedy_cents must be >= 0")
    if listing["status"] != "SOLD":
        raise errors.precondition("Disputes open only on SOLD listings")
    dispute = stamp_new({
        "id": new_id(),
        "listing_id": lid,
        "opened_by": opened_by,
        "opener_user_id": ctx.user_id,
        "condition_code": condition_code,
        "status": "OPENED",
        "remedy_cents": remedy,
    })
    store.disputes[dispute["id"]] = dispute
    return resp.created(dispute)


@bp.get("/listings/<lid>/disputes")
def list_disputes(lid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller", "Buyer", "ClaimsAdjuster")
    if lid not in store.listings:
        raise errors.not_found("Listing not found")
    limit, offset = pagination_args()
    items = [d for d in store.disputes.values() if d["listing_id"] == lid]
    page, total = paginate(items, limit, offset)
    return resp.listing_ok(page, limit, offset, total)


@bp.post("/disputes/<did>/transition")
def dispute_transition(did):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "ClaimsAdjuster", "Buyer", "Seller")
    data = body()
    action = data.get("action")
    if action in ("START_EVIDENCE", "RESOLVE_BUYER", "RESOLVE_SELLER"):
        mw.require_role(ctx, "ClaimsAdjuster")
    elif action == "WITHDRAW":
        mw.require_role(ctx, "Buyer", "Seller")
    dispute = store.disputes.get(did)
    if not dispute:
        raise errors.not_found("Dispute not found")
    cur = dispute["status"]

    if action == "START_EVIDENCE":
        if cur != "OPENED":
            raise errors.invalid_state(f"START_EVIDENCE not defined from {cur}")
        latest = svc.latest_verified_report(dispute["listing_id"])
        codes = {d.get("code") for d in (latest or {}).get("disclosed_defects", [])} if latest else set()
        if dispute["condition_code"] not in codes:
            raise errors.undisclosed_condition()
        dispute["status"] = "EVIDENCE"
        touch(dispute)
    elif action in ("RESOLVE_BUYER", "RESOLVE_SELLER"):
        if cur != "EVIDENCE":
            raise errors.invalid_state(f"{action} not defined from {cur}")
        if ctx.user_id == dispute["opener_user_id"]:
            raise errors.segregation("Resolver must differ from the opener")
        dispute["status"] = action.replace("RESOLVE_", "RESOLVED_")
        touch(dispute)
        if action == "RESOLVE_BUYER":
            listing = store.listings[dispute["listing_id"]]
            latest = svc.latest_verified_report(dispute["listing_id"])
            codes = {d.get("code") for d in (latest or {}).get("disclosed_defects", [])} if latest else set()
            if dispute["condition_code"] in codes:
                for g in store.guarantees.values():
                    if g["listing_id"] == listing["id"] and g["status"] == "ACTIVE":
                        g["status"] = "CLAIMED"
                        g["claimed_at"] = fmt_iso(store.clock)
                        g["claim_amount_cents"] = svc.compute_claim_amount(g, listing)
                        touch(g)
                        break
    elif action == "WITHDRAW":
        if cur not in ("OPENED", "EVIDENCE"):
            raise errors.invalid_state(f"WITHDRAW not defined from {cur}")
        if ctx.user_id != dispute["opener_user_id"]:
            raise errors.forbidden("Only the opener may withdraw the dispute")
        dispute["status"] = "WITHDRAWN"
        touch(dispute)
    else:
        raise errors.invalid_state(f"Unknown or inapplicable action {action!r}")
    return resp.ok(dispute)
