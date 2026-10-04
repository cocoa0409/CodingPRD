from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from db import STORE, logical_now

TIER_WEIGHT = {"FEDERAL": 3, "PREMIER": 2, "STANDARD": 1}
TIER_DISCOUNT = {"STANDARD": Decimal("0.00"), "PREMIER": Decimal("0.08"), "FEDERAL": Decimal("0.12")}
TIER_BUFFER_DAYS = {"FEDERAL": 2, "PREMIER": 1, "STANDARD": 0}
QTY_BULK_THRESHOLD = 50
ESTIMATE_PCT = Decimal("0.30")
GRADE_PCT = {"poor": Decimal("0.10"), "fair": Decimal("0.25"), "good": Decimal("0.45")}
SLA_HOURS = {"BASIC": 72, "NBD": 24, "ONSITE_4H": 4}


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------- compatibility ----------------

def rules_for_chassis(chassis_id):
    return [r for r in STORE.compat_rules.values() if r["chassis_model_id"] == chassis_id]


def check_compatibility(chassis_id, selections):
    """Return True when every rule for chassis passes over selections.
    selections: list of {component_id, qty}"""
    sel_qty = {}
    for s in selections:
        sel_qty[s["component_id"]] = sel_qty.get(s["component_id"], 0) + s["qty"]
    selected = set(sel_qty.keys())
    rules = rules_for_chassis(chassis_id)
    # ALLOWED membership: any subject component with an ALLOWED rule defines the
    # permitted set; every selected component that appears as an ALLOWED subject
    # scope must be a member. Components with no ALLOWED rule are unconstrained
    # unless at least one ALLOWED rule exists for the chassis, in which case the
    # chassis is restricted to the listed components.
    allowed_subjects = {r["component_id"] for r in rules if r["rule_type"] == "ALLOWED"}
    if allowed_subjects:
        for cid in selected:
            if cid not in allowed_subjects:
                return False
    for r in rules:
        rt = r["rule_type"]
        subj = r["component_id"]
        if rt == "REQUIRES":
            if subj in selected and r["other_component_id"] not in selected:
                return False
        elif rt == "EXCLUDES":
            if subj in selected and r["other_component_id"] in selected:
                return False
        elif rt == "MIN_QTY":
            if subj in selected and sel_qty.get(subj, 0) < (r["min_qty"] or 0):
                return False
    return True


# ---------------- lead time ----------------

def lead_time_days(configuration, variant):
    """variant: 'provisional' uses available_units; 'committed' uses stock_on_hand."""
    chassis = STORE.chassis_models.get(configuration["chassis_model_id"])
    build_days = (chassis["build_duration_hours"] // 24) if chassis else 0
    max_lead = 0
    # aggregate selected qty per component
    sel_qty = {}
    for s in configuration["component_selections"]:
        sel_qty[s["component_id"]] = sel_qty.get(s["component_id"], 0) + s["qty"]
    for cid, qty in sel_qty.items():
        comp = STORE.components.get(cid)
        if comp is None:
            continue
        if variant == "provisional":
            pool = comp["stock_on_hand"] - comp["reserved_units"]
        else:
            pool = comp["stock_on_hand"]
        if pool < qty:
            if comp["lead_time_days"] > max_lead:
                max_lead = comp["lead_time_days"]
    return max_lead + build_days


# ---------------- pricing ----------------

def unit_price_cents(configuration):
    chassis = STORE.chassis_models.get(configuration["chassis_model_id"])
    base = chassis["base_price_cents"] if chassis else 0
    total = base
    for s in configuration["component_selections"]:
        comp = STORE.components.get(s["component_id"])
        if comp is None:
            continue
        total += comp["price_cents"] * s["qty"]
    return total


def price_order(order, lines, account):
    """Round per line, then sum. Mutates lines' line_total_cents and returns
    (total_cents, discount_cents)."""
    discount_pct = TIER_DISCOUNT[account["account_tier"]]
    total = 0
    pre_total = 0
    for line in lines:
        cfg = STORE.configurations.get(line["configuration_id"])
        unit = unit_price_cents(cfg) if cfg else 0
        pre = unit * line["qty"]
        discounted = (Decimal(pre) * (Decimal(1) - discount_pct))
        line_total = round_half_up_cents(discounted)
        line["line_total_cents"] = line_total
        total += line_total
        pre_total += pre
    return total, pre_total - total


# ---------------- promised ship date ----------------

def promised_ship_date(order, lines, account, submitted_dt):
    max_committed = 0
    for line in lines:
        cfg = STORE.configurations.get(line["configuration_id"])
        if cfg is None:
            continue
        committed = lead_time_days(cfg, "committed")
        cfg["committed_lead_time_days"] = committed
        if committed > max_committed:
            max_committed = committed
    buffer_days = TIER_BUFFER_DAYS[account["account_tier"]]
    if any(l["qty"] >= QTY_BULK_THRESHOLD for l in lines):
        buffer_days += 3
    return submitted_dt + timedelta(days=max_committed + buffer_days)


# ---------------- build queue sequencing ----------------

def rescore_queue():
    """Recompute sequence_rank over all QUEUED/ALLOCATED jobs, rank 1 = highest score."""
    now = logical_now()
    candidates = [j for j in STORE.build_jobs.values() if j["status"] in ("QUEUED", "ALLOCATED")]
    scored = []
    for j in candidates:
        order = STORE.orders.get(j["order_id"])
        if order is None or not order.get("promised_ship_date"):
            days_until = 0.0
        else:
            from helpers import parse_iso8601
            psd = parse_iso8601(order["promised_ship_date"])
            days_until = (psd - now).total_seconds() / 86400.0
        line_count = sum(1 for l in STORE.order_lines.values() if l["order_id"] == j["order_id"])
        line_count = max(line_count, 1)
        account = STORE.accounts.get(order["account_id"]) if order else None
        tw = TIER_WEIGHT.get(account["account_tier"], 1) if account else 1
        score = 0.6 * days_until + 0.3 * (1.0 / line_count) + 0.1 * tw
        score = round(score, 4)
        scored.append((score, j["created_at"], j["id"], j))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    for rank, (_, _, _, job) in enumerate(scored, start=1):
        job["sequence_rank"] = rank


# ---------------- shortage / allocation ----------------

def required_components(configuration, job_qty):
    """Return list of (component, required_qty) for the job's effective selections."""
    sel = configuration["component_selections"]
    agg = {}
    for s in sel:
        agg[s["component_id"]] = agg.get(s["component_id"], 0) + s["qty"]
    out = []
    for cid, q in agg.items():
        comp = STORE.components.get(cid)
        if comp is not None:
            out.append((comp, q * job_qty))
    return out


# ---------------- entitlements expiry ----------------

def sweep_entitlement_expiry():
    """Move ACTIVE entitlements past their closed coverage_end to EXPIRED.
    Closed interval: active through the end instant itself; expires when clock passes it."""
    now = logical_now()
    from helpers import parse_iso8601
    from db import touch
    for e in STORE.entitlements.values():
        if e["status"] != "ACTIVE":
            continue
        end = parse_iso8601(e["coverage_end"])
        if now > end:
            e["status"] = "EXPIRED"
            if e.get("parts_stocking_required") and e.get("reserved_part_component_id"):
                comp = STORE.components.get(e["reserved_part_component_id"])
                if comp is not None:
                    comp["reserved_units"] -= 1
                    touch(comp)
            touch(e)
