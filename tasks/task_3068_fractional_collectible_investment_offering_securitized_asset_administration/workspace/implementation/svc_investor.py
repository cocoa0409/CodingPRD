"""Investor onboarding, suitability screening, subscriptions (§2.8, §3.4, §3.5)."""
from envelope import ApiError, invalid_request, invalid_state, not_found, forbidden
from catalog import (SUITABILITY_DAYS, RESCISSION_WINDOW_DAYS,
                     ACCREDITED_INCOME_CENTS, ACCREDITED_NET_WORTH_CENTS)
from store import DB, parse_dt, to_ms, add_days
from models import make_investor, make_subscription, refresh_overview, insert_index
from svc_common import (body, require, as_int, enum_value, check_enum_optional,
                        recompute_offering_shares, recompute_offering_cash,
                        refund_subscription)
import views


# ---------------------------------------------------------------------------
# Investor
# ---------------------------------------------------------------------------

def register_investor():
    data = body()
    require(data, ["email", "legal_name", "password", "citizenship_country_code",
                   "residency_country_code", "birth_date", "annual_income_cents",
                   "net_worth_cents"])
    row = make_investor(data)
    return views.investor(row), 201


def get_investor(investor_id, actor):
    row = DB.investors.get(investor_id)
    if row is None:
        raise not_found("Investor %s does not exist." % investor_id)
    if actor.role == "Investor" and actor.user_id != investor_id:
        raise forbidden("An investor may only read its own record.")
    return views.investor(row)


def list_investors(query, actor):
    rows = DB.ordered("investors")
    status = query.get("suitability_status")
    if status:
        rows = [r for r in rows if r["suitability_status"] == status]
    if actor.role == "Investor":
        rows = [r for r in rows if r["id"] == actor.user_id]
    return rows


def refresh_expiry(investor):
    """An APPROVED investor whose expiry instant has passed reads EXPIRED."""
    if investor["suitability_status"] != "APPROVED":
        return investor
    expires = parse_dt(investor.get("suitability_expires_at"))
    if expires is not None and parse_dt(DB.now()) > expires:
        investor["suitability_status"] = "EXPIRED"
        investor["updated_at"] = to_ms(DB.now())
        investor["version"] = int(investor.get("version") or 1) + 1
    return investor


def approve_investor(investor, accredited=False):
    now = to_ms(DB.now())
    investor["suitability_status"] = "APPROVED"
    investor["suitability_verified_at"] = now
    investor["suitability_expires_at"] = add_days(now, SUITABILITY_DAYS)
    if accredited:
        investor["is_accredited"] = True
    investor["updated_at"] = now
    investor["version"] = int(investor.get("version") or 1) + 1
    return investor


def revoke_suitability(investor_id):
    investor = DB.investors.get(investor_id)
    if investor is None:
        raise not_found("Investor %s does not exist." % investor_id)
    data = body()
    require(data, ["reason"])
    if investor["suitability_status"] != "APPROVED":
        raise invalid_state("Only an approved investor's suitability may be revoked.")
    now = to_ms(DB.now())
    investor["suitability_status"] = "REVOKED"
    investor["updated_at"] = now
    investor["version"] = int(investor.get("version") or 1) + 1
    affected = set()
    for sub in DB.subscriptions.values():
        if sub["investor_id"] == investor_id and sub["status"] in ("RECEIVED", "SUBSCRIBED"):
            sub["status"] = "REJECTED"
            refund_subscription(sub)
            sub["updated_at"] = now
            sub["version"] = int(sub.get("version") or 1) + 1
            affected.add(sub["offering_id"])
    for offering_id in affected:
        offering = DB.offerings.get(offering_id)
        if offering is None:
            continue
        offering["updated_at"] = now
        offering["version"] = int(offering["version"]) + 1
        recompute_offering_shares(offering)
        recompute_offering_cash(offering)
    return views.investor(investor)


# ---------------------------------------------------------------------------
# eligibility screen
# ---------------------------------------------------------------------------

def jurisdiction_override(investor):
    return (investor.get("citizenship_country_code") == "US"
            and investor.get("residency_country_code") == "US")


def implicit_screen(investor):
    """The fixed internal order: jurisdiction override, then age, then residence."""
    if jurisdiction_override(investor):
        raise ApiError("ERR_OFFERING_NOT_AVAILABLE_IN_JURISDICTION",
                       "The investor is a US citizen and US resident; this offering "
                       "is not offered in its own jurisdiction.")
    birth = parse_dt(investor.get("birth_date"))
    now = parse_dt(DB.now())
    if birth is None or (now - birth).days < 18 * 365.25:
        raise ApiError("ERR_INVESTOR_INELIGIBLE",
                       "The investor has not reached the age of 18 at the current "
                       "clock instant.")
    if investor.get("residency_country_code") != "US":
        raise ApiError("ERR_INVESTOR_INELIGIBLE",
                       "The investor is not resident in the United States.")
    return True


def accredited_ok(investor):
    return (int(investor.get("annual_income_cents") or 0) >= ACCREDITED_INCOME_CENTS
            or int(investor.get("net_worth_cents") or 0) >= ACCREDITED_NET_WORTH_CENTS)


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

def submit_subscription(actor):
    data = body()
    require(data, ["offering_id", "investor_id", "requested_shares"])
    as_int(data, "requested_shares", minimum=1)

    # priority 2 — investor eligibility screening (body-driven when named)
    named = data.get("screened")
    investor = DB.investors.get(data.get("investor_id"))
    if named is None:
        if investor is not None:
            implicit_screen(investor)

    offering = DB.offerings.get(data.get("offering_id"))
    if offering is None:
        raise not_found("Offering %s does not exist." % data.get("offering_id"))
    if investor is None:
        raise not_found("Investor %s does not exist." % data.get("investor_id"))

    # priority 4 — jurisdiction override (only when the explicit guard did not fire)
    if named is None and jurisdiction_override(investor):
        raise ApiError("ERR_OFFERING_NOT_AVAILABLE_IN_JURISDICTION",
                       "The investor is a US citizen and US resident.")
    if named is None and investor.get("residency_country_code") != "US":
        raise ApiError("ERR_INVESTOR_INELIGIBLE", "The investor is not US resident.")

    if actor.role == "Investor" and actor.user_id != investor["id"]:
        raise forbidden("An investor may only subscribe as itself.")

    if offering["status"] not in ("DRAFT", "QUALIFICATION_FILED", "ALLOCATED"):
        raise invalid_state("The offering takes no further subscriptions.")

    from calc import share_cap
    cap = share_cap(offering["total_shares"], offering["registration_cap_pct"])
    baseline = sum(int(s.get("accepted_shares") or 0) for s in DB.subscriptions.values()
                   if s["offering_id"] == offering["id"]
                   and s["investor_id"] == investor["id"])
    if max(0, cap - baseline) <= 0:
        raise ApiError("ERR_OFFERING_FULL",
                       "The investor already holds the offering's registration cap.")

    row = make_subscription(offering, data)
    offering["updated_at"] = row["created_at"]
    offering["version"] = int(offering["version"]) + 1
    recompute_offering_shares(offering)
    return views.subscription(row), 201


def get_subscription(sub_id, actor):
    row = DB.subscriptions.get(sub_id)
    if row is None:
        raise not_found("Subscription %s does not exist." % sub_id)
    if actor.role == "Investor" and actor.user_id != row["investor_id"]:
        raise forbidden("An investor may only read its own subscription.")
    return views.subscription(row)


def list_subscriptions(query, actor):
    rows = DB.ordered("subscriptions")
    offering_id = query.get("offering_id")
    if offering_id:
        rows = [r for r in rows if r["offering_id"] == offering_id]
    investor_id = query.get("investor_id")
    if investor_id:
        rows = [r for r in rows if r["investor_id"] == investor_id]
    if actor.role == "Investor":
        rows = [r for r in rows if r["investor_id"] == actor.user_id]
    status = query.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


def screen_subscription(sub_id):
    sub = DB.subscriptions.get(sub_id)
    if sub is None:
        raise not_found("Subscription %s does not exist." % sub_id)
    data = body()
    require(data, ["outcome"])
    outcome = enum_value(data, "outcome", "screen_outcome")
    offering = DB.offerings.get(sub["offering_id"])
    if offering is None:
        raise not_found("Offering does not exist.")
    investor = DB.investors.get(sub["investor_id"])
    if investor is None:
        raise not_found("Investor does not exist.")
    if sub["status"] != "RECEIVED":
        raise invalid_state("Only a RECEIVED subscription can be screened.")

    if outcome == "DISPUTED":
        now = to_ms(DB.now())
        sub["status"] = "REJECTED"
        refund_subscription(sub)
        sub["updated_at"] = now
        sub["version"] = int(sub.get("version") or 1) + 1
        offering["updated_at"] = now
        offering["version"] = int(offering["version"]) + 1
        recompute_offering_shares(offering)
        recompute_offering_cash(offering)
        return views.subscription(sub)

    # VERIFIED
    if offering["status"] not in ("DRAFT", "QUALIFICATION_FILED", "ALLOCATED"):
        raise invalid_state("The offering takes no new money.")
    if investor["suitability_status"] not in ("PENDING", "APPROVED"):
        raise invalid_state("The investor's suitability is not PENDING or APPROVED.")
    if offering["exemption_type"] == "EXEMPT_REG_D" and not accredited_ok(investor):
        raise invalid_state("The investor does not meet the accredited-investor threshold.")
    if jurisdiction_override(investor):
        raise ApiError("ERR_OFFERING_NOT_AVAILABLE_IN_JURISDICTION",
                       "The investor is a US citizen and US resident.")

    now = to_ms(DB.now())
    approve_investor(investor, accredited=(offering["exemption_type"] == "EXEMPT_REG_D"))
    sub["status"] = "SUBSCRIBED"
    sub["updated_at"] = now
    sub["version"] = int(sub.get("version") or 1) + 1
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    recompute_offering_shares(offering)
    return views.subscription(sub)


def collect_funds(sub_id):
    sub = DB.subscriptions.get(sub_id)
    if sub is None:
        raise not_found("Subscription %s does not exist." % sub_id)
    data = body()
    require(data, ["amount_cents"])
    amount = as_int(data, "amount_cents", minimum=0)
    offering = DB.offerings.get(sub["offering_id"])
    if offering is None:
        raise not_found("Offering does not exist.")
    if sub["status"] not in ("RECEIVED", "SUITABILITY_SCREENED", "SUBSCRIBED",
                             "REALLOCATED", "WAITLISTED"):
        raise invalid_state("The subscription cannot take further funds.")
    account = next(iter(DB.platform_accounts.values()), None)
    if account is not None:
        if int(account["balance_cents"]) + int(amount) < 0:
            raise ApiError("ERR_ACCOUNT_UNDERFUNDED",
                           "The collection would take the account below zero.")
        from svc_sale import credit_platform_account
        credit_platform_account(amount)
    now = to_ms(DB.now())
    sub["collected_subscription_cents"] = (
        int(sub.get("collected_subscription_cents") or 0) + int(amount))
    sub["updated_at"] = now
    sub["version"] = int(sub.get("version") or 1) + 1
    offering["cash_ledger_cents"] = int(offering.get("cash_ledger_cents") or 0) + int(amount)
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    recompute_offering_cash(offering)
    return views.subscription(sub)


def withdraw_subscription(sub_id, actor):
    sub = DB.subscriptions.get(sub_id)
    if sub is None:
        raise not_found("Subscription %s does not exist." % sub_id)
    if actor.role == "Investor" and actor.user_id != sub["investor_id"]:
        raise forbidden("An investor may only rescind its own subscription.")
    offering = DB.offerings.get(sub["offering_id"])
    if offering is None:
        raise not_found("Offering does not exist.")
    if sub["status"] not in ("SUBSCRIBED", "REALLOCATED"):
        raise invalid_state("The subscription is not in a rescindable state.")
    if offering["status"] not in ("DRAFT", "QUALIFICATION_FILED"):
        raise invalid_state("The offering is not open for rescission.")
    filed = parse_dt(offering.get("circular_filed_at"))
    if filed is not None:
        window_end = add_days(filed, RESCISSION_WINDOW_DAYS)
        if parse_dt(DB.now()) > parse_dt(window_end):
            raise invalid_state("The rescission window has closed.")
    now = to_ms(DB.now())
    sub["status"] = "WITHDRAWN"
    refund_subscription(sub)
    sub["updated_at"] = now
    sub["version"] = int(sub.get("version") or 1) + 1
    offering["updated_at"] = now
    offering["version"] = int(offering["version"]) + 1
    recompute_offering_shares(offering)
    recompute_offering_cash(offering)
    return views.subscription(sub)