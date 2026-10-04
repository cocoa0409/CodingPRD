"""Software license endpoints: create, reads, status lifecycle, credit grants,
billing close with the pinned evaluation order (samples -> tier -> gross ->
expiry -> offset -> net)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from auth import require_ownership, require_roles
from calc import (
    CREDIT_EXPIRY_DAYS,
    CREDIT_OFFSET_MAX_PCT,
    CREDIT_VALUE_CENTS,
    SAMPLE_RATE_CENTS,
    billing_window,
    sample_tier,
)
from envelope import ok, ok_list, sort_items
from errors import ApiError, not_found
from serializers import license_json
from store import DB, new_id, now, stamp_new, touch
from timeutil import date_str, parse_date_to_dt
from validate import f_enum, f_int, f_str, get_body, kit_by_code

bp = Blueprint("licenses", __name__)


def _ledger_seq(lic):
    lic["_ledger_seq"] = lic.get("_ledger_seq", 0) + 1
    return lic["_ledger_seq"]


def _grant_remainings(lic):
    """Replay the ledger to compute each grant's unconsumed balance.

    CONSUMPTION and OFFSET entries consume oldest grants first (FIFO by ledger
    order); EXPIRY entries always hit their own grant via _ref.
    """
    grants = []
    for e in lic["credit_ledger"]:
        if e["entry_type"] in ("GRANT", "PURCHASE"):
            grants.append({"gid": e["_gid"], "granted_on": e["granted_on"], "remaining": e["credits"]})
    by_gid = {g["gid"]: g for g in grants}
    for e in lic["credit_ledger"]:
        if e["entry_type"] in ("CONSUMPTION", "OFFSET"):
            need = -e["credits"]
            for g in grants:
                if need <= 0:
                    break
                take = min(g["remaining"], need)
                g["remaining"] -= take
                need -= take
        elif e["entry_type"] == "EXPIRY":
            g = by_gid.get(e.get("_ref"))
            if g is not None:
                g["remaining"] = max(0, g["remaining"] + e["credits"])
    return by_gid


@bp.post("/genomics/software-licenses")
def create_license():
    require_roles("FinanceAdmin")
    body = get_body()
    account_id = f_str(body, "account_id")
    lic = {
        "id": new_id(),
        "account_id": account_id,
        "license_state": "DRAFT",
        "activated_at": None,
        "pinned_sample_rate_cents": None,
        "credit_ledger": [],
        "samples_this_period": 0,
        "period_index": 1,
        "_ledger_seq": 0,
    }
    stamp_new(lic)
    DB["licenses"][lic["id"]] = lic
    return ok(license_json(lic), 201)


@bp.get("/genomics/software-licenses/<license_id>")
def get_license(license_id):
    uid, role = require_roles("FinanceAdmin", "LabOperator")
    lic = DB["licenses"].get(license_id)
    if lic is None:
        raise not_found("SoftwareLicense not found")
    if role == "LabOperator":
        require_ownership(lic["account_id"] == uid)
    return ok(license_json(lic))


@bp.get("/genomics/software-licenses")
def list_licenses():
    require_roles("FinanceAdmin")
    items = list(DB["licenses"].values())
    account_id = request.args.get("account_id")
    license_state = request.args.get("license_state")
    if account_id is not None:
        items = [l for l in items if l["account_id"] == account_id]
    if license_state is not None:
        items = [l for l in items if l["license_state"] == license_state]
    return ok_list([license_json(l) for l in sort_items(items)])


@bp.post("/genomics/software-licenses/<license_id>/status")
def license_status(license_id):
    require_roles("FinanceAdmin")
    lic = DB["licenses"].get(license_id)
    if lic is None:
        raise not_found("SoftwareLicense not found")
    body = get_body()
    action = f_enum(body, "action", ["ACTIVATE", "SUSPEND", "REINSTATE"])
    state = lic["license_state"]
    if action == "ACTIVATE":
        if state != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409, "ACTIVATE requires license_state DRAFT")
        lic["activated_at"] = now()
        lic["pinned_sample_rate_cents"] = dict(SAMPLE_RATE_CENTS)
        lic["license_state"] = "ACTIVE"
    elif action == "SUSPEND":
        if state != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "SUSPEND requires license_state ACTIVE")
        lic["license_state"] = "SUSPENDED"
    else:  # REINSTATE
        if state != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE", 409, "REINSTATE requires license_state SUSPENDED")
        lic["license_state"] = "ACTIVE"
    touch(lic)
    return ok(license_json(lic))


@bp.post("/genomics/software-licenses/<license_id>/credit-grants")
def credit_grant(license_id):
    require_roles("FinanceAdmin")
    lic = DB["licenses"].get(license_id)
    if lic is None:
        raise not_found("SoftwareLicense not found")
    body = get_body()
    credits = f_int(body, "credits", min_v=1)
    grant_type = f_enum(body, "grant_type", ["GRANT", "PURCHASE"])
    granted_on_raw = body.get("granted_on")
    if granted_on_raw is None:
        granted_on = date_str(now())
    else:
        granted_dt = parse_date_to_dt(granted_on_raw)
        if granted_dt is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "granted_on must be an ISO date")
        granted_on = date_str(granted_dt)
    if lic["license_state"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE", 409, "License must be ACTIVE for credit grants")
    lic["credit_ledger"].append(
        {
            "entry_type": grant_type,
            "credits": credits,
            "granted_on": granted_on,
            "created_at": now(),
            "_gid": _ledger_seq(lic),
        }
    )
    touch(lic)
    return ok(license_json(lic), 201)


@bp.post("/genomics/software-licenses/<license_id>/billing-close")
def billing_close(license_id):
    require_roles("FinanceAdmin")
    lic = DB["licenses"].get(license_id)
    if lic is None:
        raise not_found("SoftwareLicense not found")
    get_body()  # tolerate an optional empty body
    if lic["license_state"] != "ACTIVE":
        raise ApiError("ERR_LICENSE_NOT_ACTIVE", 409, "License must be ACTIVE for billing-close")
    t = now()
    period_start, period_end = billing_window(lic)
    # Step 1: billable samples from actual run records in the open window.
    billable_samples = sum(
        r["samples_count"]
        for r in DB["runs"].values()
        if r["license_id"] == lic["id"]
        and r["outcome"] in ("SUCCESS", "PARTIAL")
        and period_start <= r["run_at"] < period_end
    )
    # Step 2/3: tier then gross at the pinned average rate.
    tier = sample_tier(billable_samples)
    gross_cents = billable_samples * lic["pinned_sample_rate_cents"][tier]
    # Step 4: credit expiry BEFORE offset — grants older than 365 days that are
    # not yet consumed get an EXPIRY entry for their remaining balance.
    remainings = _grant_remainings(lic)
    expiry_plan = []
    for e in lic["credit_ledger"]:
        if e["entry_type"] not in ("GRANT", "PURCHASE"):
            continue
        g = remainings[e["_gid"]]
        granted_dt = parse_date_to_dt(e["granted_on"])
        if granted_dt is not None and g["remaining"] > 0 and (t - granted_dt) > timedelta(
            days=CREDIT_EXPIRY_DAYS
        ):
            expiry_plan.append((e["_gid"], g["remaining"]))
    expired_credits = 0
    for gid, remaining in expiry_plan:
        lic["credit_ledger"].append(
            {
                "entry_type": "EXPIRY",
                "credits": -remaining,
                "created_at": t,
                "_gid": _ledger_seq(lic),
                "_ref": gid,
            }
        )
        expired_credits += remaining
    balance = sum(e["credits"] for e in lic["credit_ledger"])
    # Step 5: offset — whole-credit floor of half the gross at 100 cents/credit.
    offset_cap = int((Decimal(gross_cents) * CREDIT_OFFSET_MAX_PCT) // CREDIT_VALUE_CENTS)
    offset_credits = max(0, min(balance, offset_cap))
    offset_cents = offset_credits * CREDIT_VALUE_CENTS
    if offset_credits > 0:
        lic["credit_ledger"].append(
            {
                "entry_type": "OFFSET",
                "credits": -offset_credits,
                "created_at": t,
                "_gid": _ledger_seq(lic),
            }
        )
    # Step 6: net.
    net_cents = gross_cents - offset_cents
    credits_balance = sum(e["credits"] for e in lic["credit_ledger"])
    # Provisional figures from the account's SUBMITTED/FROZEN forecasts.
    provisional_samples = 0
    for f in DB["forecasts"].values():
        if f["account_id"] != lic["account_id"]:
            continue
        if f["forecast_state"] not in ("SUBMITTED", "FROZEN"):
            continue
        for ln in f["lines"]:
            week_end = ln["week_start"] + timedelta(days=7)
            if ln["week_start"] < period_end and week_end > period_start:
                kit = kit_by_code(ln["kit_code"])
                if kit is not None:
                    provisional_samples += ln["quantity"] * kit["samples_per_kit"]
    provisional_tier = sample_tier(provisional_samples)
    provisional_gross_cents = provisional_samples * lic["pinned_sample_rate_cents"][provisional_tier]
    lic["samples_this_period"] = 0
    lic["period_index"] += 1
    touch(lic)
    return ok(
        {
            "billable_samples": billable_samples,
            "tier": tier,
            "gross_cents": gross_cents,
            "expired_credits": expired_credits,
            "offset_credits": offset_credits,
            "offset_cents": offset_cents,
            "net_cents": net_cents,
            "credits_balance": credits_balance,
            "provisional_samples": provisional_samples,
            "provisional_gross_cents": provisional_gross_cents,
        }
    )
