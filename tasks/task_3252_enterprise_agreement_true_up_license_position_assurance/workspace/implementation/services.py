"""Business calculations: price levels, license position, true-up pricing,
benefit accrual, cloud waterfall, step-up, shortfall, expiry sweeps."""
import datetime
import math
from decimal import Decimal, ROUND_HALF_UP

import db

PRICE_MULTIPLIERS = {"A": Decimal("1.00"), "B": Decimal("0.95"),
                     "C": Decimal("0.90"), "D": Decimal("0.85")}
MIN_CORES_PER_HOST = 16
MIN_CORES_PER_VM = 8
BENEFIT_TTL_DAYS = 365


def price_level_for(count):
    if count < 250:
        return "A"
    if count < 2400:
        return "B"
    if count < 6000:
        return "C"
    return "D"


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def adjusted_unit_price(product, price_level):
    return round_half_up_cents(Decimal(product["annual_unit_price_cents"]) * PRICE_MULTIPLIERS[price_level])


def org_of_agreement(agreement):
    return db.organizations.get(agreement["organization_id"])


def current_unit_price_for(agreement, product):
    org = org_of_agreement(agreement)
    return adjusted_unit_price(product, org["price_level"])


# ------------------------- license position -------------------------

def core_count_normalization(dep):
    normalized_physical = math.ceil(dep["physical_cores_per_server"] * dep["core_factor"])
    host_demand = max(MIN_CORES_PER_HOST, normalized_physical)
    if dep.get("vm_count", 0) == 0:
        return host_demand
    if dep.get("licensing_mode") == "PER_HOST":
        return host_demand
    # PER_VM
    return min(host_demand, dep["vm_count"] * max(MIN_CORES_PER_VM, dep.get("vcores_per_vm", 0)))


def scope_of_model(license_model):
    return {"PER_USER": "USER", "PER_DEVICE": "DEVICE", "PER_SERVER_CORE": "SERVER"}[license_model]


def compute_position_lines(agreement_id):
    """Return list of per-product position line dicts."""
    today = db.today()
    deps = [d for d in db.deployments.values()
            if d["agreement_id"] == agreement_id and not d.get("retired", False)
            and db.parse_date(d["deployment_date"]) <= today]
    product_ids = []
    for d in deps:
        if d["product_id"] not in product_ids:
            product_ids.append(d["product_id"])
    lines = []
    for pid in product_ids:
        product = db.products[pid]
        pdeps = [d for d in deps if d["product_id"] == pid]
        if product["license_model"] == "PER_USER":
            required = sum(d["user_count"] for d in pdeps)
        elif product["license_model"] == "PER_DEVICE":
            required = sum(d["device_count"] for d in pdeps)
        else:
            required = sum(core_count_normalization(d) for d in pdeps)
        entitled = sum(e["quantity"] for e in db.entitlements.values()
                       if e["agreement_id"] == agreement_id and e["product_id"] == pid)
        lines.append({
            "product_id": pid,
            "scope": scope_of_model(product["license_model"]),
            "required_licenses": required,
            "entitled_quantity": entitled,
            "net_position": entitled - required,
        })
    return lines


# ------------------------- true-up pricing -------------------------

def trueup_line_total(growth_quantity, unit_price_cents, months_growth, pricing_variant):
    base = growth_quantity * unit_price_cents
    if pricing_variant == "FULL_YEAR_RETROACTIVE":
        return base
    # ANNIVERSARY_PRORATION
    return round_half_up_cents(Decimal(base) * Decimal(12 - months_growth + 1) / Decimal(12))


def recompute_report_total(report):
    total = 0
    for line in db.trueup_lines.values():
        if line["report_id"] == report["id"]:
            total += line["total_amount_cents"]
    report["total_amount_cents"] = total


# ------------------------- benefit accrual -------------------------

def accrue_benefits(agreement_id, settled_total_cents):
    grants = []
    if settled_total_cents < 50_000_000:
        vouchers, incidents = 0, 0
    elif settled_total_cents < 200_000_000:
        vouchers, incidents = 5, 1
    else:
        vouchers, incidents = 10, 2
    upgrade_rights = 1 if settled_total_cents >= 500_000_000 else 0
    expires = (db.today() + datetime.timedelta(days=BENEFIT_TTL_DAYS)).isoformat()
    for benefit_type, qty in (("TRAINING_VOUCHER", vouchers),
                              ("SUPPORT_INCIDENT", incidents),
                              ("UPGRADE_RIGHT", upgrade_rights)):
        if qty > 0:
            g = {
                "agreement_id": agreement_id,
                "benefit_type": benefit_type,
                "quantity_granted": qty,
                "quantity_remaining": qty,
                "expires_on": expires,
                "status": "ACTIVE",
            }
            from helpers import stamp_new
            stamp_new(g, with_version=True)
            db.benefit_grants[g["id"]] = g
            grants.append(g)
    return grants


# ------------------------- sweeps -------------------------

def sweep_expired_grants(agreement_id):
    from helpers import touch
    today = db.today()
    for g in db.benefit_grants.values():
        if g["agreement_id"] == agreement_id and g["status"] == "ACTIVE":
            if db.parse_date(g["expires_on"]) < today:
                g["status"] = "EXPIRED"
                touch(g)


def terminal_sweep(agreement_id):
    """Agreement -> NON_RENEWED or EXPIRED: ACTIVE grants FORFEITED, ACTIVE commitments EXPIRED."""
    from helpers import touch
    for g in db.benefit_grants.values():
        if g["agreement_id"] == agreement_id and g["status"] == "ACTIVE":
            g["status"] = "FORFEITED"
            touch(g)
    for c in db.commitments.values():
        if c["agreement_id"] == agreement_id and c["status"] == "ACTIVE":
            c["status"] = "EXPIRED"
            touch(c)
