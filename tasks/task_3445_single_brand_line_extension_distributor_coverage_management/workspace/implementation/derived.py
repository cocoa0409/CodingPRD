"""Computed fields, cascades and calculation rules (PRD §3, scaffold §1.3)."""
from datetime import timedelta

from core import (
    STORE, now, touch, parse_datetime, round_half_up_cents, pct_of,
    trailing_window_months,
)


def secs(dt):
    return dt.replace(microsecond=0)


def dt_field(entity, field):
    v = entity.get(field)
    if v is None:
        return None
    return parse_datetime(v)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def brand_of_line(line):
    return STORE["brands"].get(line["brand_id"])


def lines_of_brand(brand_id):
    return [l for l in STORE["product_lines"].values() if l["brand_id"] == brand_id]


# ---------------------------------------------------------------------------
# Brand protection posture (scaffold: brand_protection_posture)
# ---------------------------------------------------------------------------
def compute_posture(brand):
    open_cases = [
        c for c in STORE["cases"].values()
        if c["brand_id"] == brand["id"] and c["status"] in ("REPORTED", "ACTION_TAKEN")
    ]
    severity_sum = sum(c["severity"] for c in open_cases)
    any_five = any(c["severity"] == 5 for c in open_cases)
    line_ids = {l["id"] for l in lines_of_brand(brand["id"])}
    form_ids = {
        f["id"] for f in STORE["formulations"].values()
        if f["product_line_id"] in line_ids
    }
    cutoff = secs(now() - timedelta(days=180))
    breach_count = 0
    for g in STORE["grants"].values():
        if g["formulation_id"] in form_ids and g["revoked_for_cause"] and g["revoked_at"]:
            if secs(parse_datetime(g["revoked_at"])) >= cutoff:
                breach_count += 1
    if breach_count >= 2 or any_five or severity_sum >= 10:
        return "CRITICAL"
    if breach_count == 1 or severity_sum >= 6:
        return "ELEVATED"
    return "NORMAL"


def suspend_live_promotions_of_brand(brand_id):
    line_ids = {l["id"] for l in lines_of_brand(brand_id)}
    for p in STORE["promotions"].values():
        if p["product_line_id"] in line_ids and p["status"] == "LIVE":
            p["status"] = "SUSPENDED"
            touch(p)


def recompute_posture(brand):
    new = compute_posture(brand)
    if new != brand["protection_posture"]:
        brand["protection_posture"] = new
        touch(brand)
    # Invariant: while CRITICAL, no LIVE promotion of the brand remains live.
    if brand["protection_posture"] == "CRITICAL":
        suspend_live_promotions_of_brand(brand["id"])


# ---------------------------------------------------------------------------
# Brand equity: dilution cost + consumption (line_dilution_cost,
# brand_equity_consumption)
# ---------------------------------------------------------------------------
def live_dilution_cost(line):
    if line["is_core"]:
        return 0
    brand_lines = lines_of_brand(line["brand_id"])
    baseline_systems = set()
    for other in brand_lines:
        if other["id"] == line["id"] or other["status"] != "LAUNCHED":
            continue
        for pack in STORE["packs"].values():
            if pack["product_line_id"] == other["id"] and pack["status"] != "RETIRED":
                baseline_systems.add(pack["delivery_system"])
    novelty = False
    for pack in STORE["packs"].values():
        if (
            pack["product_line_id"] == line["id"]
            and pack["status"] != "RETIRED"
            and pack["delivery_system"] not in baseline_systems
        ):
            novelty = True
            break
    cost = 400 + 150 * (len(line["target_channels"]) - 1) + (200 if novelty else 0)
    return min(cost, 1000)


def line_dilution_repr(line):
    frozen = line.get("_frozen_cost_bps")
    if frozen is not None:
        return frozen
    return live_dilution_cost(line)


def recompute_brand_equity(brand):
    consumed = 0
    for line in lines_of_brand(brand["id"]):
        frozen = line.get("_frozen_cost_bps")
        if line["status"] in ("PILOT", "LAUNCHED"):
            consumed += frozen or 0
        elif line["status"] == "DISCONTINUED" and frozen is not None:
            consumed += frozen // 2
    share = max(0, 10000 - consumed)
    if consumed != brand["dilution_consumed_bps"] or share != brand["core_identity_share_bps"]:
        brand["dilution_consumed_bps"] = consumed
        brand["core_identity_share_bps"] = share
        touch(brand)


# ---------------------------------------------------------------------------
# Genericization risk
# ---------------------------------------------------------------------------
def recompute_genericization(brand):
    line_ids = {l["id"] for l in lines_of_brand(brand["id"])}
    pub = ver = 0
    for u in STORE["use_cases"].values():
        if u["product_line_id"] not in line_ids or not u["generic_use_flag"]:
            continue
        if u["status"] == "PUBLISHED":
            pub += 1
        elif u["status"] == "VERIFIED":
            ver += 1
    risk = min(10000, 100 * pub + 50 * ver)
    if risk != brand["genericization_risk_bps"]:
        brand["genericization_risk_bps"] = risk
        touch(brand)


# ---------------------------------------------------------------------------
# Trade secret: disclosed components + formulation coverage
# ---------------------------------------------------------------------------
def recompute_disclosed_count(mfr):
    pairs = set()
    for g in STORE["grants"].values():
        if g["manufacturer_id"] == mfr["id"] and g["status"] in ("GRANTED", "ACTIVE"):
            for code in g["component_scope"]:
                pairs.add((g["formulation_id"], code))
    count = len(pairs)
    if count != mfr["disclosed_component_count"]:
        mfr["disclosed_component_count"] = count
        touch(mfr)


def reeval_formulation_coverage(form):
    if form["status"] not in ("SEALED", "COMPARTMENTALIZED"):
        return
    covered = set()
    for g in STORE["grants"].values():
        if g["formulation_id"] == form["id"] and g["status"] == "ACTIVE":
            covered.update(g["component_scope"])
    complete = all(c in covered for c in form["component_codes"])
    target = "COMPARTMENTALIZED" if complete else "SEALED"
    if form["status"] != target:
        form["status"] = target
        touch(form)


# ---------------------------------------------------------------------------
# Distributor suspension / termination machinery (strike system)
# ---------------------------------------------------------------------------
def terminate_distributor(d):
    d["status"] = "TERMINATED"
    touch(d)
    for a in STORE["assignments"].values():
        if a["distributor_id"] != d["id"]:
            continue
        if a["status"] == "PROPOSED":
            a["status"] = "WITHDRAWN"
            touch(a)
        elif a["status"] in ("ACTIVE", "SUSPENDED"):
            a["status"] = "TERMINATED"
            touch(a)


def suspend_distributor(d):
    """Fire the strike: increments count; the third strike terminates instead."""
    new_count = d["suspension_count"] + 1
    if new_count >= 3:
        d["suspension_count"] = 3
        terminate_distributor(d)
        return
    d["suspension_count"] = new_count
    d["status"] = "SUSPENDED"
    touch(d)
    for a in STORE["assignments"].values():
        if a["distributor_id"] == d["id"] and a["status"] == "ACTIVE":
            a["status"] = "SUSPENDED"
            touch(a)


# ---------------------------------------------------------------------------
# Coverage attainment (dual variant) + tier + SANCTION cascade
# ---------------------------------------------------------------------------
def in_scope_assignments(distributor_id):
    return [
        a for a in STORE["assignments"].values()
        if a["distributor_id"] == distributor_id and a["status"] in ("ACTIVE", "SUSPENDED")
    ]


def window_net_units(distributor_id):
    """Trailing-3-completed-month total net units over in-scope assignments."""
    window = set(trailing_window_months(3))
    scope_ids = {a["id"] for a in in_scope_assignments(distributor_id)}
    total = 0
    for r in STORE["reports"].values():
        if r["coverage_assignment_id"] in scope_ids and r["period_month"] in window:
            total += r["net_units"]
    return total


def recompute_attainment(d):
    scope = in_scope_assignments(d["id"])
    if not scope:
        return  # fields and tier left untouched
    window = trailing_window_months(3)
    window_set = set(window)
    scope_ids = {a["id"] for a in scope}
    month_net = {m: 0 for m in window}
    total_net = 0
    for r in STORE["reports"].values():
        if r["coverage_assignment_id"] in scope_ids and r["period_month"] in window_set:
            month_net[r["period_month"]] += r["net_units"]
            total_net += r["net_units"]
    quota_3m = sum(a["annual_quota_units"] // 4 for a in scope)
    quota_annual = sum(a["annual_quota_units"] for a in scope)
    actual = 0 if quota_3m == 0 else round_half_up_cents(10000 * total_net, quota_3m)
    best_month = max(month_net.values()) if month_net else 0
    projected = (
        0 if quota_annual == 0 else round_half_up_cents(10000 * best_month * 12, quota_annual)
    )
    if actual >= 12000:
        tier = "GOLD"
    elif actual >= 10000:
        tier = "STANDARD"
    elif actual >= 9000:
        tier = "WATCH"
    else:
        tier = "SANCTION"
    changed = (
        d["attainment_actual_bps"] != actual
        or d["attainment_projected_bps"] != projected
        or d["quota_compliance_tier"] != tier
    )
    d["attainment_actual_bps"] = actual
    d["attainment_projected_bps"] = projected
    d["quota_compliance_tier"] = tier
    if changed:
        touch(d)
    if tier == "SANCTION" and d["status"] == "APPROVED":
        suspend_distributor(d)


# ---------------------------------------------------------------------------
# Rebate preview
# ---------------------------------------------------------------------------
def rebate_for(distributor, reference_unit_price_cents):
    tier = distributor["quota_compliance_tier"]
    if tier is None:
        rebate_bps = 0
    else:
        base = {"GOLD": 300, "STANDARD": 200, "WATCH": 100, "SANCTION": 0}[tier]
        bonus = 25 if "MASS" in distributor["channels_served"] else 0
        rebate_bps = min(base + bonus, 350)
    net = window_net_units(distributor["id"])
    estimate = round_half_up_cents(net * reference_unit_price_cents * rebate_bps, 10000)
    return rebate_bps, net, estimate


# ---------------------------------------------------------------------------
# Price resolution (price_resolution)
# ---------------------------------------------------------------------------
def resolve_price_list(pack_format_id, channel, at):
    """Winning non-SUPERSEDED list covering `at`, or None."""
    at_s = secs(at)
    cands = []
    for pl in STORE["price_lists"].values():
        if pl["pack_format_id"] != pack_format_id or pl["channel"] != channel:
            continue
        if pl["status"] == "SUPERSEDED":
            continue
        ef = secs(parse_datetime(pl["effective_from"]))
        et = secs(parse_datetime(pl["effective_to"]))
        if ef <= at_s < et:
            cands.append(pl)
    if not cands:
        return None
    # greatest effective_from wins; tie -> earliest created_at
    cands.sort(key=lambda pl: (secs(parse_datetime(pl["effective_from"])), ), reverse=True)
    best_from = secs(parse_datetime(cands[0]["effective_from"]))
    tied = [pl for pl in cands if secs(parse_datetime(pl["effective_from"])) == best_from]
    tied.sort(key=lambda pl: (pl["created_at"], pl["_seq"]))
    return tied[0]
