"""Core services: serialization, calculations, cascades."""
import uuid
from datetime import timedelta

from db import store, _parse_iso, _fmt_iso
from errors import err

PLATFORM_PERIOD_DAYS = 30
THIRD_PARTY_PERIOD_DAYS = 31
GRACE_DAYS = 7
MAX_RENEWAL_FAILURES = 3
MAX_DISCOUNT_PCT = 60
MIN_PRICE_CENTS = 100

MATURITY_RANK = {"TV_Y": 0, "TV_G": 1, "TV_PG": 2, "TV_14": 3, "TV_MA": 4}

BOOKKEEPING = ("created_at", "updated_at", "version")


def new_id():
    return str(uuid.uuid4())


def _stamp(entity):
    now_iso = store.now_iso()
    entity["created_at"] = now_iso
    entity["updated_at"] = now_iso
    entity["version"] = 1


def touch(entity):
    entity["updated_at"] = store.now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def plan_out(p):
    return {
        "id": p["id"],
        "plan_code": p["plan_code"],
        "plan_kind": p["plan_kind"],
        "service_scope": p["service_scope"],
        "ad_tier": p["ad_tier"],
        "monthly_price_cents": p["monthly_price_cents"],
        "component_weights": p.get("component_weights"),
        "allow_app_store_billing": p["allow_app_store_billing"],
        "allow_distributor_billing": p["allow_distributor_billing"],
        "is_legacy": p.get("is_legacy", False),
        "created_at": p["created_at"],
    }


def account_out(a):
    return {
        "id": a["id"],
        "email": a["email"],
        "full_name": a["full_name"],
        "account_status": a["account_status"],
        "grandfathered_price_cents": a.get("grandfathered_price_cents"),
        "grandfathered_plan_code": a.get("grandfathered_plan_code"),
        "retention_redemption_count": retention_redemption_count(a["id"]),
        "account_credit_cents": a.get("account_credit_cents", 0),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def profile_out(p):
    return {
        "id": p["id"],
        "subscriber_account_id": p["subscriber_account_id"],
        "service": p["service"],
        "profile_status": p["profile_status"],
        "maturity_rating_cap": p["maturity_rating_cap"],
        "kids_mode": p["kids_mode"],
        "watchlist_count": p.get("watchlist_count", 0),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def watchlist_item_out(w):
    return {
        "id": w["id"],
        "service_profile_id": w["service_profile_id"],
        "title_id": w["title_id"],
        "title_maturity": w["title_maturity"],
        "created_at": w["created_at"],
    }


def billing_account_out(b):
    return {
        "id": b["id"],
        "subscriber_account_id": b["subscriber_account_id"],
        "biller_type": b["biller_type"],
        "biller_reference": b["biller_reference"],
        "billing_status": b["billing_status"],
        "period_start": _fmt_iso(b.get("period_start")) if b.get("period_start") else None,
        "period_end": _fmt_iso(b.get("period_end")) if b.get("period_end") else None,
        "consecutive_failure_count": b.get("consecutive_failure_count", 0),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def subscription_out(s):
    return {
        "id": s["id"],
        "subscriber_account_id": s["subscriber_account_id"],
        "billing_account_id": s["billing_account_id"],
        "plan_code": s["plan_code"],
        "lifecycle_status": s["lifecycle_status"],
        "billing_dimension": s["billing_dimension"],
        "price_cents": s.get("price_cents"),
        "retention_discount_cents": s.get("retention_discount_cents", 0),
        "migration_id": s.get("migration_id"),
        "pending_plan_code": s.get("pending_plan_code"),
        "cancel_effective_at": _fmt_iso(s.get("cancel_effective_at")) if s.get("cancel_effective_at") else None,
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def entitlement_out(e):
    return {
        "id": e["id"],
        "subscription_id": e["subscription_id"],
        "service_profile_id": e["service_profile_id"],
        "service": e["service"],
        "entitlement_status": e["entitlement_status"],
        "mismatch_flag": e.get("mismatch_flag", False),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def migration_out(m):
    return {
        "id": m["id"],
        "subscriber_account_id": m["subscriber_account_id"],
        "from_subscription_id": m["from_subscription_id"],
        "to_subscription_id": m.get("to_subscription_id"),
        "target_plan_code": m["target_plan_code"],
        "migration_status": m["migration_status"],
        "proration_credit_cents": m.get("proration_credit_cents"),
        "proration_method_used": m.get("proration_method_used"),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def offer_out(o):
    return {
        "id": o["id"],
        "offer_code": o["offer_code"],
        "discount_cents": o["discount_cents"],
        "duration_months": o["duration_months"],
        "max_redemptions_per_account": o["max_redemptions_per_account"],
        "eligible_biller_types": o["eligible_biller_types"],
        "eligible_plan_kinds": o["eligible_plan_kinds"],
        "offer_status": o.get("offer_status", "OPEN"),
        "created_at": o["created_at"],
    }


def redemption_out(r):
    return {
        "id": r["id"],
        "subscription_id": r["subscription_id"],
        "subscriber_account_id": r["subscriber_account_id"],
        "offer_code": r["offer_code"],
        "redemption_status": r["redemption_status"],
        "months_remaining": r["months_remaining"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def invoice_out(i):
    return {
        "id": i["id"],
        "billing_account_id": i["billing_account_id"],
        "subscription_id": i["subscription_id"],
        "invoice_status": i["invoice_status"],
        "invoice_kind": i["invoice_kind"],
        "gross_cents": i["gross_cents"],
        "credit_applied_cents": i["credit_applied_cents"],
        "net_cents": i["net_cents"],
        "period_start": _fmt_iso(i.get("period_start")) if i.get("period_start") else None,
        "period_end": _fmt_iso(i.get("period_end")) if i.get("period_end") else None,
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def allocation_out(a):
    return {
        "id": a["id"],
        "invoice_id": a["invoice_id"],
        "service": a["service"],
        "allocated_cents": a["allocated_cents"],
        "created_at": a["created_at"],
    }


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def retention_redemption_count(account_id):
    """Lifetime count of redemptions in ACTIVE or EXPIRED status."""
    n = 0
    for r in store.redemptions.values():
        if r["subscriber_account_id"] == account_id and r["redemption_status"] in ("ACTIVE", "EXPIRED"):
            n += 1
    return n


def base_price(subscription):
    """Grandfathered base or plan list price (integer cents)."""
    account = store.accounts[subscription["subscriber_account_id"]]
    plan = store.plans[subscription["plan_code"]]
    if (account.get("grandfathered_plan_code") == subscription["plan_code"]
            and account.get("grandfathered_price_cents") is not None):
        return account["grandfathered_price_cents"]
    return plan["monthly_price_cents"]


def recompute_price(subscription):
    """retention_effective_price: cap discount at 60% of base, floor price at 100."""
    base = base_price(subscription)
    active = 0
    for r in store.redemptions.values():
        if r["subscription_id"] == subscription["id"] and r["redemption_status"] == "ACTIVE":
            offer = store.offers[r["offer_code"]]
            active += offer["discount_cents"]
    cap = (base * MAX_DISCOUNT_PCT) // 100
    discount = min(active, cap)
    price = base - discount
    if price < MIN_PRICE_CENTS:
        discount = base - MIN_PRICE_CENTS
        price = MIN_PRICE_CENTS
    subscription["retention_discount_cents"] = discount
    subscription["price_cents"] = price


def reevaluate_mismatch(account_id):
    """tier_mismatch_resolution: compare the best ad_tier each LINKED profile
    receives from its ACTIVE entitlements; when the two profiles disagree, flag
    every ACTIVE entitlement serving the lower-tier (AD_SUPPORTED) profile."""
    rank = {"AD_SUPPORTED": 0, "AD_FREE": 1}
    profile_tier = {}   # profile_id -> best tier from ACTIVE entitlements
    profile_ents = {}   # profile_id -> [entitlement]
    for e in store.entitlements.values():
        sub = store.subscriptions.get(e["subscription_id"])
        if sub is None or sub["subscriber_account_id"] != account_id:
            continue
        if e["entitlement_status"] != "ACTIVE":
            continue
        profile = store.profiles.get(e["service_profile_id"])
        if profile is None or profile["profile_status"] != "LINKED":
            continue
        plan = store.plans[sub["plan_code"]]
        tier = plan["ad_tier"]
        prev = profile_tier.get(profile["id"])
        if prev is None or rank[tier] > rank[prev]:
            profile_tier[profile["id"]] = tier
        profile_ents.setdefault(profile["id"], []).append(e)
    flag_profiles = set()
    by_service = {}
    for pid, tier in profile_tier.items():
        by_service.setdefault(store.profiles[pid]["service"], []).append((pid, tier))
    if "DPLUS" in by_service and "HULU" in by_service:
        d_tiers = {t for _, t in by_service["DPLUS"]}
        h_tiers = {t for _, t in by_service["HULU"]}
        if len(d_tiers) == 1 and len(h_tiers) == 1:
            d = next(iter(d_tiers))
            h = next(iter(h_tiers))
            if d != h:
                lower_service = "DPLUS" if d == "AD_SUPPORTED" else "HULU"
                for pid, _ in by_service[lower_service]:
                    flag_profiles.add(pid)
    for pid, ents in profile_ents.items():
        new_flag = pid in flag_profiles
        for e in ents:
            if e.get("mismatch_flag", False) != new_flag:
                e["mismatch_flag"] = new_flag
                touch(e)


def profile_bubble(profile):
    """After entitlement changes: LINKED->SUSPENDED when zero ACTIVE entitlements,
    SUSPENDED->LINKED when >=1 ACTIVE entitlement."""
    active = sum(
        1 for e in store.entitlements.values()
        if e["service_profile_id"] == profile["id"] and e["entitlement_status"] == "ACTIVE"
    )
    if profile["profile_status"] == "LINKED" and active == 0:
        profile["profile_status"] = "SUSPENDED"
        touch(profile)
    elif profile["profile_status"] == "SUSPENDED" and active >= 1:
        profile["profile_status"] = "LINKED"
        touch(profile)


def ent_set_status(entitlement, status):
    if entitlement["entitlement_status"] != status:
        entitlement["entitlement_status"] = status
        touch(entitlement)


NON_TERMINAL_LIFECYCLES = ("PENDING_ENTITLEMENT", "ACTIVE", "PAST_DUE", "CANCEL_SCHEDULED")


def grandfather_lock(account, subscription):
    """Lock grandfathered price at first activation; re-lock after full churn
    (every prior subscription terminal)."""
    others_live = any(
        s["id"] != subscription["id"] and s["lifecycle_status"] in NON_TERMINAL_LIFECYCLES
        for s in store.subscriptions.values()
        if s["subscriber_account_id"] == account["id"]
    )
    if account.get("grandfathered_price_cents") is None or not others_live:
        plan = store.plans[subscription["plan_code"]]
        account["grandfathered_plan_code"] = subscription["plan_code"]
        account["grandfathered_price_cents"] = plan["monthly_price_cents"]
        touch(account)


def maybe_activate_subscription(subscription):
    """PENDING_ENTITLEMENT -> ACTIVE when no PROVISIONING entitlements remain and
    ACTIVE count equals plan scope size. Runs grandfather lock then reprices."""
    if subscription["lifecycle_status"] != "PENDING_ENTITLEMENT":
        return
    ents = [e for e in store.entitlements.values() if e["subscription_id"] == subscription["id"]]
    if any(e["entitlement_status"] == "PROVISIONING" for e in ents):
        return
    plan = store.plans[subscription["plan_code"]]
    active = sum(1 for e in ents if e["entitlement_status"] == "ACTIVE")
    if active != len(plan["service_scope"]):
        return
    subscription["lifecycle_status"] = "ACTIVE"
    touch(subscription)
    account = store.accounts[subscription["subscriber_account_id"]]
    grandfather_lock(account, subscription)
    recompute_price(subscription)


def provision_entitlements(subscription, profile_by_service):
    """Create one entitlement per service in plan scope and provision to ACTIVE."""
    plan = store.plans[subscription["plan_code"]]
    profiles_touched = []
    for service in plan["service_scope"]:
        profile = profile_by_service.get(service)
        ent = {
            "id": new_id(),
            "subscription_id": subscription["id"],
            "service_profile_id": profile["id"],
            "service": service,
            "entitlement_status": "PROVISIONING",
            "mismatch_flag": False,
        }
        _stamp(ent)
        store.entitlements[ent["id"]] = ent
        if profile["profile_status"] == "LINKED" and service in plan["service_scope"]:
            ent_set_status(ent, "ACTIVE")
            profiles_touched.append(profile)
    for p in profiles_touched:
        profile_bubble(p)
    reevaluate_mismatch(subscription["subscriber_account_id"])
    maybe_activate_subscription(subscription)


def period_days(billing_account):
    return PLATFORM_PERIOD_DAYS if billing_account["biller_type"] == "PLATFORM" else THIRD_PARTY_PERIOD_DAYS


def allocate_revenue(invoice):
    """revenue_allocation: weighted split, DPLUS row rounded half-up, HULU absorbs remainder."""
    subscription = store.subscriptions[invoice["subscription_id"]]
    plan = store.plans[subscription["plan_code"]]
    net = invoice["net_cents"]
    rows = []
    if plan["plan_kind"] == "STANDALONE":
        rows = [(plan["service_scope"][0], net)]
    else:
        weights = plan["component_weights"]
        # round half-up: floor(net*w + 0.5) for non-negative values
        dplus = int(net * float(weights["DPLUS"]) + 0.5)
        hulu = net - dplus
        rows = [("DPLUS", dplus), ("HULU", hulu)]
    for service, cents in rows:
        alloc = {
            "id": new_id(),
            "invoice_id": invoice["id"],
            "service": service,
            "allocated_cents": cents,
        }
        now_iso = store.now_iso()
        alloc["created_at"] = now_iso
        store.revenue_allocations[alloc["id"]] = alloc


def issue_invoice(billing_account, subscription, kind, gross, credit_applied, period_start, period_end, status="ISSUED"):
    net = gross - credit_applied
    inv = {
        "id": new_id(),
        "billing_account_id": billing_account["id"],
        "subscription_id": subscription["id"],
        "invoice_status": status,
        "invoice_kind": kind,
        "gross_cents": gross,
        "credit_applied_cents": credit_applied,
        "net_cents": net,
        "period_start": period_start,
        "period_end": period_end,
    }
    _stamp(inv)
    store.invoices[inv["id"]] = inv
    return inv


def mark_invoice_paid(invoice, advance_period=False):
    """ISSUED/FAILED -> PAID: allocate revenue, optionally advance period and
    decrement retention months."""
    invoice["invoice_status"] = "PAID"
    touch(invoice)
    allocate_revenue(invoice)
    if advance_period:
        billing = store.billing_accounts[invoice["billing_account_id"]]
        days = period_days(billing)
        billing["period_start"] = billing["period_end"]
        billing["period_end"] = billing["period_end"] + timedelta(days=days)
        touch(billing)
        subscription = store.subscriptions[invoice["subscription_id"]]
        for r in store.redemptions.values():
            if r["subscription_id"] == subscription["id"] and r["redemption_status"] == "ACTIVE":
                r["months_remaining"] -= 1
                if r["months_remaining"] <= 0:
                    r["redemption_status"] = "EXPIRED"
                touch(r)
        recompute_price(subscription)


def subscription_cascade_to_cancelled(subscription):
    """Finalize cancellation: revoke entitlements, void redemption, UNPAID."""
    profiles = set()
    for e in store.entitlements.values():
        if e["subscription_id"] == subscription["id"] and e["entitlement_status"] in ("ACTIVE", "SUSPENDED"):
            profiles.add(e["service_profile_id"])
            ent_set_status(e, "REVOKED")
    for pid in profiles:
        profile_bubble(store.profiles[pid])
    for r in store.redemptions.values():
        if r["subscription_id"] == subscription["id"] and r["redemption_status"] == "ACTIVE":
            r["redemption_status"] = "VOIDED"
            touch(r)
    subscription["billing_dimension"] = "UNPAID"
    subscription["lifecycle_status"] = "CANCELLED"
    touch(subscription)
    recompute_price(subscription)
    reevaluate_mismatch(subscription["subscriber_account_id"])
    void_open_migrations(subscription["id"])


def void_open_migrations(subscription_id):
    """Auto-void QUOTED migrations whose from-subscription left ACTIVE."""
    for m in store.migrations.values():
        if m["migration_status"] == "QUOTED" and m["from_subscription_id"] == subscription_id:
            sub = store.subscriptions[subscription_id]
            if sub["lifecycle_status"] != "ACTIVE":
                m["migration_status"] = "VOIDED"
                touch(m)


def fire_scheduled_cancellations():
    """On clock advance: finalize any CANCEL_SCHEDULED subscription whose
    cancel_effective_at has been reached."""
    now = store.now()
    for s in list(store.subscriptions.values()):
        if s["lifecycle_status"] == "CANCEL_SCHEDULED" and s.get("cancel_effective_at") is not None:
            if now >= s["cancel_effective_at"]:
                s["cancel_effective_at"] = None
                subscription_cascade_to_cancelled(s)


def renewal_failure_cascade(billing_account, subscription):
    """Failed renewal: PAST_DUE or HARD_FAILED depending on failure count."""
    billing_account["consecutive_failure_count"] = billing_account.get("consecutive_failure_count", 0) + 1
    if billing_account["consecutive_failure_count"] >= MAX_RENEWAL_FAILURES:
        billing_account["billing_status"] = "HARD_FAILED"
        touch(billing_account)
        subscription["cancel_effective_at"] = None
        subscription_cascade_to_cancelled(subscription)
    else:
        billing_account["billing_status"] = "PAST_DUE"
        touch(billing_account)
        subscription["billing_dimension"] = "GRACE"
        subscription["lifecycle_status"] = "PAST_DUE"
        touch(subscription)
        profiles = set()
        for e in store.entitlements.values():
            if e["subscription_id"] == subscription["id"] and e["entitlement_status"] == "ACTIVE":
                profiles.add(e["service_profile_id"])
                ent_set_status(e, "SUSPENDED")
        for pid in profiles:
            profile_bubble(store.profiles[pid])
        reevaluate_mismatch(subscription["subscriber_account_id"])
        void_open_migrations(subscription["id"])


def payment_recovery_cascade(billing_account, subscription):
    """Payment recovered: reset failure count, restore CURRENT/PAID_UP/ACTIVE,
    reactivate entitlements and profiles."""
    billing_account["consecutive_failure_count"] = 0
    billing_account["billing_status"] = "CURRENT"
    touch(billing_account)
    subscription["billing_dimension"] = "PAID_UP"
    subscription["lifecycle_status"] = "ACTIVE"
    touch(subscription)
    profiles = set()
    for e in store.entitlements.values():
        if e["subscription_id"] == subscription["id"] and e["entitlement_status"] == "SUSPENDED":
            profile = store.profiles[e["service_profile_id"]]
            if profile["profile_status"] != "UNLINKED":
                profiles.add(profile["id"])
                ent_set_status(e, "ACTIVE")
    for pid in profiles:
        profile_bubble(store.profiles[pid])
    recompute_price(subscription)
    reevaluate_mismatch(subscription["subscriber_account_id"])


def run_renewal(billing_account, outcome):
    """renewal_collection for due subscriptions, chronological by created_at.
    ACTIVE/PAID_UP subscriptions are collected for the next period;
    PAST_DUE/GRACE subscriptions are retried for the current period (success
    recovers and advances the period, failure increments toward HARD_FAILED).
    HARD_FAILED billing accounts cannot process renewals."""
    now = store.now()
    subs = [
        s for s in store.subscriptions.values()
        if s["billing_account_id"] == billing_account["id"]
        and ((s["lifecycle_status"] == "ACTIVE" and s["billing_dimension"] == "PAID_UP")
             or (s["lifecycle_status"] == "PAST_DUE" and s["billing_dimension"] == "GRACE"))
    ]
    subs.sort(key=lambda s: s["created_at"])
    last_invoice = None
    for sub in subs:
        account = store.accounts[sub["subscriber_account_id"]]
        gross = sub["price_cents"]
        credit_applied = min(account.get("account_credit_cents", 0), gross)
        net = gross - credit_applied
        account["account_credit_cents"] = account.get("account_credit_cents", 0) - credit_applied
        touch(account)
        inv = issue_invoice(
            billing_account, sub, "RENEWAL", gross, credit_applied,
            billing_account["period_start"], billing_account["period_end"],
        )
        last_invoice = inv
        if sub["lifecycle_status"] == "PAST_DUE":
            # Retry of the failed current period.
            if outcome == "SUCCEEDED":
                mark_invoice_paid(inv, advance_period=True)
                payment_recovery_cascade(billing_account, sub)
            else:
                inv["invoice_status"] = "FAILED"
                touch(inv)
                billing_account["consecutive_failure_count"] = billing_account.get("consecutive_failure_count", 0) + 1
                if billing_account["consecutive_failure_count"] >= MAX_RENEWAL_FAILURES:
                    billing_account["billing_status"] = "HARD_FAILED"
                    touch(billing_account)
                    sub["cancel_effective_at"] = None
                    subscription_cascade_to_cancelled(sub)
                else:
                    touch(billing_account)
        else:
            if outcome == "SUCCEEDED":
                mark_invoice_paid(inv, advance_period=True)
            else:
                inv["invoice_status"] = "FAILED"
                touch(inv)
                renewal_failure_cascade(billing_account, sub)
    return last_invoice
