"""Serializers, calculations, cascades, and logical-clock time-based re-evaluation."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from middleware import touch

# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def serialize_developer(d):
    recompute_lifetime_gross(d["id"])
    return {
        "id": d["id"],
        "company_name": d["company_name"],
        "contact_email": d["contact_email"],
        "payout_currency": d["payout_currency"],
        "status": d["status"],
        "lifetime_gross_cents": d["lifetime_gross_cents"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def tier_for_gross(g):
    if g <= 100000000:
        return "T0"
    if g <= 1000000000:
        return "T1"
    return "T2"


def serialize_app(a):
    dev = db.developers.get(a["developer_id"])
    gross = dev["lifetime_gross_cents"] if dev else 0
    return {
        "id": a["id"],
        "developer_id": a["developer_id"],
        "name": a["name"],
        "status": a["status"],
        "listing_status": a["listing_status"],
        "category": a["category"],
        "submitted_at": a["submitted_at"],
        "revenue_share_tier": tier_for_gross(gross),
        "performance_state": a["performance_state"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_version(v):
    return {
        "id": v["id"],
        "app_id": v["app_id"],
        "semver": v["semver"],
        "status": v["status"],
        "review_round": v["review_round"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def serialize_scope(s):
    return {
        "id": s["id"],
        "code": s["code"],
        "risk_level": s["risk_level"],
        "created_at": s["created_at"],
    }


def serialize_scope_request(sr):
    return {
        "id": sr["id"],
        "app_version_id": sr["app_version_id"],
        "scope_code": sr["scope_code"],
        "justification": sr["justification"],
        "status": sr["status"],
        "denied_reason": sr["denied_reason"],
        "created_at": sr["created_at"],
        "updated_at": sr["updated_at"],
        "version": sr["version"],
    }


def serialize_review_window(w):
    return {
        "id": w["id"],
        "app_version_id": w["app_version_id"],
        "reviewer_id": w["reviewer_id"],
        "starts_at": w["starts_at"],
        "ends_at": w["ends_at"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def serialize_merchant(m):
    return {
        "id": m["id"],
        "shop_domain": m["shop_domain"],
        "plan_tier": m["plan_tier"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_installation(i):
    return {
        "id": i["id"],
        "app_id": i["app_id"],
        "merchant_id": i["merchant_id"],
        "status": i["status"],
        "installed_at": i["installed_at"],
        "uninstalled_at": i["uninstalled_at"],
        "data_deletion_deadline": i["data_deletion_deadline"],
        "data_deletion_confirmed_at": i["data_deletion_confirmed_at"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def serialize_consent_record(cr):
    return {
        "id": cr["id"],
        "installation_id": cr["installation_id"],
        "scope_code": cr["scope_code"],
        "status": cr["status"],
        "granted_at": cr["granted_at"],
        "revoked_at": cr["revoked_at"],
        "created_at": cr["created_at"],
        "updated_at": cr["updated_at"],
        "version": cr["version"],
    }


def serialize_webhook(w):
    return {
        "id": w["id"],
        "installation_id": w["installation_id"],
        "topic": w["topic"],
        "endpoint_url": w["endpoint_url"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def serialize_charge(c):
    return {
        "id": c["id"],
        "installation_id": c["installation_id"],
        "billing_cycle": c["billing_cycle"],
        "charge_type": c["charge_type"],
        "status": c["status"],
        "base_amount_cents": c["base_amount_cents"],
        "discount_code": c["discount_code"],
        "discount_amount_cents": c["discount_amount_cents"],
        "final_amount_cents": c["final_amount_cents"],
        "platform_share_cents": c["platform_share_cents"],
        "developer_net_cents": c["developer_net_cents"],
        "description": c["description"],
        "capped_at": c["capped_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_invoice(inv):
    return {
        "id": inv["id"],
        "merchant_id": inv["merchant_id"],
        "cycle": inv["cycle"],
        "status": inv["status"],
        "total_cents": inv["total_cents"],
        "issued_at": inv["issued_at"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


def serialize_ledger_entry(le):
    return {
        "id": le["id"],
        "developer_id": le["developer_id"],
        "charge_id": le["charge_id"],
        "entry_type": le["entry_type"],
        "amount_cents": le["amount_cents"],
        "entry_variant": le["entry_variant"],
        "cycle": le["cycle"],
        "created_at": le["created_at"],
        "updated_at": le["updated_at"],
        "version": le["version"],
    }


def serialize_sample(s):
    return {
        "id": s["id"],
        "installation_id": s["installation_id"],
        "storefront_load_ms": s["storefront_load_ms"],
        "sampled_at": s["sampled_at"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_strike(s):
    return {
        "id": s["id"],
        "app_id": s["app_id"],
        "reason": s["reason"],
        "status": s["status"],
        "strike_start": s["strike_start"],
        "strike_ends_at": s["strike_ends_at"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_ticket(t):
    return {
        "id": t["id"],
        "app_id": t["app_id"],
        "merchant_id": t["merchant_id"],
        "severity": t["severity"],
        "sla_hours": t["sla_hours"],
        "status": t["status"],
        "opened_at": t["opened_at"],
        "first_response_at": t["first_response_at"],
        "resolved_at": t.get("resolved_at"),
        "sla_breached": t["sla_breached"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def round_half_up(value):
    """Round a Decimal/float to the nearest integer, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


SHARE_RATES = {"T0": Decimal("0"), "T1": Decimal("0.15"), "T2": Decimal("0.20")}


def compute_share(final_amount_cents, tier):
    rate = SHARE_RATES[tier]
    share = round_half_up(Decimal(final_amount_cents) * rate)
    return share, final_amount_cents - share


def developer_id_of_app(app_id):
    app = db.apps.get(app_id)
    return app["developer_id"] if app else None


def developer_id_of_installation(installation_id):
    inst = db.installations.get(installation_id)
    if not inst:
        return None
    return developer_id_of_app(inst["app_id"])


def recompute_lifetime_gross(developer_id):
    """lifetime_gross_cents = sum of final_amount_cents over the developer's
    charges with status INVOICED or SETTLED."""
    dev = db.developers.get(developer_id)
    if not dev:
        return
    total = 0
    for c in db.charges.values():
        if c["status"] in ("INVOICED", "SETTLED"):
            if developer_id_of_installation(c["installation_id"]) == developer_id:
                total += c["final_amount_cents"]
    dev["lifetime_gross_cents"] = total


def recompute_invoice_total(invoice):
    total = 0
    for c in db.charges.values():
        if c["billing_cycle"] != invoice["cycle"] or c["status"] != "INVOICED":
            continue
        inst = db.installations.get(c["installation_id"])
        if inst and inst["merchant_id"] == invoice["merchant_id"]:
            total += c["final_amount_cents"]
    invoice["total_cents"] = total


def open_strike(app_id, reason):
    from middleware import new_entity
    now = db.clock.now()
    s = new_entity()
    s.update({
        "app_id": app_id,
        "reason": reason,
        "status": "ACTIVE",
        "strike_start": db.fmt_dt(now),
        "strike_ends_at": db.fmt_dt(now + timedelta(days=30)),
    })
    db.strikes[s["id"]] = s
    return s


def active_unexpired_strikes(app_id, reasons=None):
    now = db.clock.now()
    out = []
    for s in db.strikes.values():
        if s["app_id"] != app_id or s["status"] != "ACTIVE":
            continue
        if db.parse_dt(s["strike_ends_at"]) <= now:
            continue
        if reasons is not None and s["reason"] not in reasons:
            continue
        out.append(s)
    return out


def sla_breached(ticket):
    now = db.clock.now()
    opened = db.parse_dt(ticket["opened_at"])
    sla = timedelta(hours=ticket["sla_hours"])
    fr = ticket.get("first_response_at")
    if fr is None:
        return (now - opened) > sla
    return (db.parse_dt(fr) - opened) > sla


def search_score(app):
    """Weighted ranking score per PRD §3.4."""
    W = {
        "PRODUCTIVITY": (1, 2, 3),
        "MARKETING": (2, 2, 1),
        "FULFILLMENT": (3, 1, 1),
        "ANALYTICS": (2, 1, 2),
        "FINANCE": (2, 3, 0),
    }
    w1, w2, w3 = W[app["category"]]
    now = db.clock.now()
    # quality
    n_strikes = len([s for s in db.strikes.values()
                     if s["app_id"] == app["id"] and s["status"] == "ACTIVE"])
    quality = max(0, 10 - n_strikes)
    # install velocity
    cutoff = now - timedelta(days=30)
    velocity = 0
    for inst in db.installations.values():
        if inst["app_id"] != app["id"] or not inst["installed_at"]:
            continue
        if db.parse_dt(inst["installed_at"]) >= cutoff:
            velocity += 1
    velocity = min(velocity, 10)
    # recency: any version with a published_at within last 30 days
    recency = 0
    for v in db.versions.values():
        if v["app_id"] != app["id"]:
            continue
        pub = v.get("published_at")
        if pub and db.parse_dt(pub) >= cutoff:
            recency = 5
            break
    return w1 * quality + w2 * velocity + w3 * recency


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def finalize_charge_share(charge, gross_override=None):
    """Finalize platform_share_cents / developer_net_cents at INVOICED time
    using the app's tier in force right now. `gross_override` lets the issue
    action evaluate the tier against the lifetime gross that includes the
    batch of charges being invoiced in the same step (PRD §2.12 defines
    lifetime gross over INVOICED-or-SETTLED charges, and §3.6 pins the share
    to the tier in force at the moment the charge is invoiced)."""
    inst = db.installations.get(charge["installation_id"])
    dev = db.developers.get(developer_id_of_app(inst["app_id"])) if inst else None
    gross = gross_override if gross_override is not None else (
        dev["lifetime_gross_cents"] if dev else 0)
    tier = tier_for_gross(gross)
    share, net = compute_share(charge["final_amount_cents"], tier)
    charge["platform_share_cents"] = share
    charge["developer_net_cents"] = net


def append_ledger(developer_id, charge_id, entry_type, amount_cents, variant, cycle):
    from middleware import new_entity
    le = new_entity()
    le.update({
        "developer_id": developer_id,
        "charge_id": charge_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "entry_variant": variant,
        "cycle": cycle,
    })
    db.ledger_entries[le["id"]] = le
    return le


def run_time_cascades():
    """Re-evaluate every time-based cascade on logical-clock advance
    (PRD §2.10): strike expiry, deletion-deadline enforcement."""
    now = db.clock.now()
    # Strike expiry
    for s in db.strikes.values():
        if s["status"] == "ACTIVE" and db.parse_dt(s["strike_ends_at"]) <= now:
            s["status"] = "EXPIRED"
            touch(s)
    # Deletion deadline enforcement
    for inst in db.installations.values():
        if inst["status"] == "UNINSTALLING" and inst["data_deletion_confirmed_at"] is None:
            deadline = db.parse_dt(inst["data_deletion_deadline"])
            if now > deadline:
                inst["status"] = "UNINSTALLED"
                touch(inst)
                for w in db.webhooks.values():
                    if w["installation_id"] == inst["id"] and w["status"] != "DISABLED":
                        w["status"] = "DISABLED"
                        touch(w)
                open_strike(inst["app_id"], "DATA_DELETION_OVERDUE")
