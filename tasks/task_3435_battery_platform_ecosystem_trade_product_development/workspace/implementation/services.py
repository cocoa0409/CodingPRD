"""Business logic: derived fields, calculations, selections, and cascades.

All "computed" entity fields are derived at read time from source data so a
value can never go stale; the version bumps the PRD pins to recomputation
triggers are applied explicitly at those triggers.
"""
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import db
from constants import (
    ASSET_LIMITS,
    DAYS_PER_MONTH,
    GEN_GAP_EFFICIENCY_CAP,
    GEN_GAP_EFFICIENCY_STEP,
    LEGACY_CHARGE_DERATE,
    MIN_EFFICIENCY,
)
from errors import fail

INF = datetime.max.replace(tzinfo=timezone.utc)


# ----------------------------------------------------------------- entities
def make_entity(fields):
    now = db.clock_now()
    e = dict(fields)
    e["id"] = db.new_id()
    e["created_at"] = now
    e["updated_at"] = now
    e["version"] = 1
    e["_seq"] = db.next_seq()
    return e


def bump(e):
    """Every mutation of a resource increments its version by exactly 1."""
    e["version"] += 1
    e["updated_at"] = db.clock_now()


# ---------------------------------------------------------------- platforms
def platform_current_generation(platform_id):
    gens = [
        p["pack_generation"]
        for p in db.STORE["packs"].values()
        if p["platform_id"] == platform_id and p["certification_status"] == "CERTIFIED"
    ]
    return max(gens) if gens else 0


def apply_sunset_transitions():
    """Clock-driven ACTIVE -> SUNSETTING -> RETIRED; both legs may fire on one set."""
    now = db.clock_now()
    for p in db.STORE["platforms"].values():
        if (
            p["status"] == "ACTIVE"
            and p.get("sunset_announce_date") is not None
            and now >= p["sunset_announce_date"]
        ):
            p["status"] = "SUNSETTING"
            bump(p)
        if (
            p["status"] == "SUNSETTING"
            and p.get("sunset_date") is not None
            and now >= p["sunset_date"]
        ):
            p["status"] = "RETIRED"
            bump(p)


def add_calendar_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29 -> Feb 28
        return d.replace(year=d.year + years, day=28)


# -------------------------------------------------------------------- tools
def regulatory_packs(tool):
    out = []
    for p in db.STORE["packs"].values():
        if p["platform_id"] != tool["platform_id"]:
            continue
        if not (tool["min_pack_generation"] <= p["pack_generation"] <= tool["max_pack_generation"]):
            continue
        if p["certification_status"] != "CERTIFIED" or p["safety_hold"]:
            continue
        out.append(p)
    return out


def runtime_estimate(tool, pack):
    gap = pack["pack_generation"] - tool["min_pack_generation"]
    eff = Decimal("1.0") - GEN_GAP_EFFICIENCY_STEP * min(gap, GEN_GAP_EFFICIENCY_CAP)
    if eff < MIN_EFFICIENCY:
        eff = MIN_EFFICIENCY
    rt = (
        Decimal(str(pack["rated_capacity_wh"]))
        * eff
        / Decimal(str(tool["avg_power_draw_w"]))
        * Decimal(60)
    ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(rt)


def tool_regulatory_count(tool):
    return len(regulatory_packs(tool))


def tool_best_runtime(tool):
    packs = regulatory_packs(tool)
    if not packs:
        return None
    return max(runtime_estimate(tool, p) for p in packs)


def adopted_count(tool_id, kind):
    return sum(
        1
        for i in db.STORE["insights"].values()
        if i["tool_model_id"] == tool_id and i["kind"] == kind and i["status"] == "ADOPTED"
    )


# ------------------------------------------------------------------ accounts
def account_asset_limit(account):
    return ASSET_LIMITS[account["tier"]]


def account_active_count(account_id):
    return sum(
        1
        for a in db.STORE["assets"].values()
        if a["account_id"] == account_id
        and a["status"] != "DECOMMISSIONED"
        and not a["is_replacement_unit"]
    )


# ------------------------------------------------------------------ partners
def partner_active_allocation(partner_id):
    return sum(
        l["allocation_qty"]
        for l in db.STORE["listings"].values()
        if l["channel_partner_id"] == partner_id and l["status"] == "ACTIVE"
    )


def partner_has_suspended(partner_id):
    return any(
        l["channel_partner_id"] == partner_id and l["status"] == "SUSPENDED"
        for l in db.STORE["listings"].values()
    )


# ------------------------------------------------------------------ warranty
def booked_count(center_id, service_date):
    return sum(
        1
        for c in db.STORE["claims"].values()
        if c["service_center_id"] == center_id
        and c["service_date"] == service_date
        and c["adjudication_status"] in ("SUBMITTED", "APPROVED")
        and c["fulfillment_status"] in ("NONE", "AWAITING_UNIT")
    )


def select_service_center(claim_type, service_date):
    needed = "TOOL_REPAIR" if claim_type == "TOOL_REPAIR" else "BATTERY_SERVICE"
    eligible = []
    for c in db.STORE["centers"].values():
        if needed not in c["capabilities"]:
            continue
        bc = booked_count(c["id"], service_date)
        if bc < c["daily_capacity"]:
            eligible.append((bc, c["created_at"], c["_seq"], c))
    if not eligible:
        fail("ERR_NO_SERVICE_CAPACITY", "No eligible service center has free capacity")
    eligible.sort(key=lambda t: (t[0], t[1], t[2]))  # least booked, earliest created
    return eligible[0][3]


def warranty_compute(claim):
    asset = db.STORE["assets"][claim["tracked_asset_id"]]
    if claim["claim_type"] == "TOOL_REPAIR":
        age_basis = "ACTIVATION"
        basis_ts = asset["first_paired_at"]
        subject = db.STORE["tools"][asset["tool_model_id"]]
    else:
        age_basis = "MANUFACTURE"
        basis_ts = asset["manufactured_at"]
        subject = db.STORE["packs"][asset["battery_pack_id"]]
    age_days = (db.clock_now() - basis_ts).days  # whole-day floor
    if age_days <= subject["free_replacement_days"]:
        coverage = "FREE"
    elif age_days <= subject["warranty_days"]:
        coverage = "PRORATED"
    else:
        coverage = "OUT_OF_WARRANTY"
    if coverage == "FREE":
        credit = subject["replacement_price_cents"]
    elif coverage == "PRORATED":
        months = subject["warranty_days"] // DAYS_PER_MONTH
        rate = int(
            (Decimal(subject["replacement_price_cents"]) / Decimal(months)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        remaining_full_months = (subject["warranty_days"] - age_days) // DAYS_PER_MONTH
        credit = rate * remaining_full_months
    else:
        credit = 0
    return {
        "age_basis": age_basis,
        "age_days": age_days,
        "coverage": coverage,
        "credit_cents": credit,
    }


# ------------------------------------------------------------------ chargers
def charge_estimate_fields(pack, charger):
    rate = Decimal(str(min(charger["max_charge_rate_w"], pack["max_charge_rate_w"])))
    if charger["charger_generation"] < pack["pack_generation"]:
        rate = (rate * LEGACY_CHARGE_DERATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    minutes = int(
        (Decimal(str(pack["rated_capacity_wh"])) / rate * Decimal(60)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return {"charger_compatible": True, "charge_estimate_minutes": minutes}


# ------------------------------------------------------------------ cascades
def _suspend_active_pack_listings(pack_id):
    partners = set()
    for l in db.STORE["listings"].values():
        if l.get("battery_pack_id") == pack_id and l["status"] == "ACTIVE":
            l["status"] = "SUSPENDED"
            l["requires_relist_ack"] = True
            bump(l)
            partners.add(l["channel_partner_id"])
    for pid in partners:
        bump(db.STORE["partners"][pid])


def _end_active_listings(field, product_id):
    for l in db.STORE["listings"].values():
        if l.get(field) == product_id and l["status"] == "ACTIVE":
            l["status"] = "ENDED"
            bump(l)


def end_tool_listings(tool_id):
    """LAUNCHED -> DISCONTINUED cascade: end the tool's ACTIVE listings."""
    _end_active_listings("tool_model_id", tool_id)


def counterfeit_confirm_cascade(pack):
    pack["safety_hold"] = True
    bump(pack)
    _suspend_active_pack_listings(pack["id"])


def bulletin_cascade(b):
    if b["severity"] == "ADVISORY":
        return
    if b["battery_pack_ids"]:
        targets = [db.STORE["packs"][pid] for pid in b["battery_pack_ids"]]
    else:
        targets = [p for p in db.STORE["packs"].values() if p["platform_id"] == b["platform_id"]]
    if b["severity"] == "URGENT":
        for pack in targets:
            _suspend_active_pack_listings(pack["id"])
        return
    # RECALL
    partners = set()
    for pack in targets:
        if pack["certification_status"] != "CERTIFIED":
            continue
        pack["certification_status"] = "RECALLED"
        bump(pack)
        for l in db.STORE["listings"].values():
            if l.get("battery_pack_id") == pack["id"] and l["status"] == "ACTIVE":
                l["status"] = "ENDED"
                bump(l)
                partners.add(l["channel_partner_id"])
        platform = db.STORE["platforms"][pack["platform_id"]]
        bump(platform)  # current_generation recompute trigger (derived at read)
    for pid in partners:
        bump(db.STORE["partners"][pid])


def supersede_prior_listing(partner_id, product_field, product_id, new_listing):
    for l in db.STORE["listings"].values():
        if (
            l["channel_partner_id"] == partner_id
            and l.get(product_field) == product_id
            and l["status"] != "ENDED"
            and l["id"] != new_listing["id"]
        ):
            l["status"] = "ENDED"
            l["superseded_by_listing_id"] = new_listing["id"]
            bump(l)
