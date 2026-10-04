"""Business logic: lazy status evaluation, computed projections, cascades,
and the pinned calculations of PRD SS3 / SCAFFOLD calculations table."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store
from store import db

# --- pinned constants -------------------------------------------------------
TERRITORY_COOLING_OFF_DAYS = 30
LATE_PULL_SUSPENSION_THRESHOLD = 3
LATE_PULL_WINDOW_DAYS = 30
TRAINING_MIN_CERTS = 2
CERT_VALIDITY_DAYS = 180
PERF_WINDOW_DAYS = 90
VISIT_SPACING_MINUTES = 30
CLEANING_WINDOW_HOURS = 24
PROMO_BRAND_SHARE = Decimal("0.6")
PROMO_FLOOR_PCT = Decimal("0.85")
TIER1_THRESHOLD_CENTS = 500000
TIER1_PCT = Decimal("0.08")
TIER2_THRESHOLD_CENTS = 200000
TIER2_PCT = Decimal("0.05")
TIER3_THRESHOLD_CENTS = 100000
TIER3_PCT = Decimal("0.02")
FREE_DELIVERY_THRESHOLD_CENTS = 100000
DELIVERY_FEE_CENTS = 1500
TIER_RANK = {"ELITE": 0, "PREFERRED": 1, "STANDARD": 2}
W_VISIT = Decimal("0.5")
W_PULL = Decimal("0.3")
W_FILL = Decimal("0.2")
CENT = Decimal("1")
SCORE_Q = Decimal("0.01")


def touch(record):
    """Every mutation refreshes updated_at and bumps version by exactly 1."""
    record["updated_at"] = store.now()
    record["version"] += 1


# ---------------------------------------------------------------------------
# lazy status evaluation (PRD SS2.5) — applied on any read or write
# ---------------------------------------------------------------------------

def lazy_territory(t):
    if t["status"] == "REVOKED" and t["revoked_at"] is not None:
        now = store.now()
        if now >= t["revoked_at"] + timedelta(days=TERRITORY_COOLING_OFF_DAYS):
            t["status"] = "OPEN"
            t["version"] += 1
            t["updated_at"] = now
    return t


def lazy_lot(lot):
    if (lot["status"] == "AVAILABLE" and lot["available_units"] == 0
            and lot["allocated_units"] == 0):
        lot["status"] = "EXHAUSTED"
    return lot


def lazy_cert(c):
    if c["status"] == "ACTIVE" and store.now() > c["expires_at"]:
        c["status"] = "EXPIRED"
    return c


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def order_lines(order_id):
    """Lines of an order in creation order."""
    return sorted(
        (l for l in db["order_lines"].values() if l["order_id"] == order_id),
        key=lambda l: l["_seq"],
    )


def affected_product_ids(incident):
    ids = set()
    for rid in incident["affected_run_ids"]:
        run = db["runs"].get(rid)
        if run is not None:
            ids.add(run["product_id"])
    return ids


# ---------------------------------------------------------------------------
# computed projections (recomputed on every read, never cached — PRD SS2.5)
# ---------------------------------------------------------------------------

def late_pulls_30d(account_id):
    now = store.now()
    lo = now - timedelta(days=LATE_PULL_WINDOW_DAYS)
    return sum(
        1 for l in db["logs"].values()
        if l["account_id"] == account_id and l["status"] == "PULLED_LATE"
        and l["pulled_at"] is not None and lo <= l["pulled_at"] <= now
    )


def training_compliant(account_id):
    """calculations.training_compliance_coverage: >= 2 ACTIVE unexpired certs
    with slicing_module_passed AND >= 2 with allergen_module_passed; one cert
    with both modules counts toward both tallies."""
    now = store.now()
    slicing = 0
    allergen = 0
    for c in db["certs"].values():
        if c["account_id"] != account_id:
            continue
        lazy_cert(c)
        if c["status"] != "ACTIVE" or now > c["expires_at"]:
            continue
        if c["slicing_module_passed"]:
            slicing += 1
        if c["allergen_module_passed"]:
            allergen += 1
    return slicing >= TRAINING_MIN_CERTS and allergen >= TRAINING_MIN_CERTS


def incident_scope(incident):
    """calculations.incident_scope_projection: distinct accounts on PENDING or
    CONFIRMED deliveries whose lines reference lots of the affected runs."""
    run_ids = set(incident["affected_run_ids"])
    lot_ids = {l["id"] for l in db["lots"].values() if l["production_run_id"] in run_ids}
    accounts = set()
    for d in db["deliveries"].values():
        if d["status"] not in ("PENDING", "CONFIRMED"):
            continue
        if any(line["lot_id"] in lot_ids for line in d["lines"]):
            accounts.add(d["account_id"])
    return len(accounts)


def performance_scores(distributor_id):
    """calculations.distributor_performance_score — returns (provisional, final)."""
    now = store.now()
    lo = now - timedelta(days=PERF_WINDOW_DAYS)
    visits = [
        v for v in db["visits"].values()
        if v["distributor_id"] == distributor_id and v["submitted_at"] is not None
        and lo <= v["submitted_at"] <= now and v["status"] in ("SUBMITTED", "VERIFIED")
    ]
    if visits:
        provisional = (Decimal(sum(v["score"] for v in visits)) / Decimal(len(visits))).quantize(
            SCORE_Q, rounding=ROUND_HALF_UP)
    else:
        provisional = Decimal("0.00")
    verified = [v for v in visits if v["status"] == "VERIFIED"]
    if verified:
        visit_component = Decimal(sum(v["score"] for v in verified)) / Decimal(len(verified))
    else:
        visit_component = Decimal(0)
    account_ids = {a["id"] for a in db["accounts"].values() if a["distributor_id"] == distributor_id}
    pulls = [
        l for l in db["logs"].values()
        if l["account_id"] in account_ids and l["pulled_at"] is not None
        and lo <= l["pulled_at"] <= now and l["status"] in ("PULLED_ON_TIME", "PULLED_LATE")
    ]
    if pulls:
        on_time = sum(1 for l in pulls if l["status"] == "PULLED_ON_TIME")
        pull_component = Decimal(100 * on_time) / Decimal(len(pulls))
    else:
        pull_component = Decimal(100)
    orders = [
        o for o in db["orders"].values()
        if o["distributor_id"] == distributor_id and lo <= o["created_at"] <= now
        and o["allocation_status"] in ("ALLOCATED", "PARTIAL", "SHORTED")
    ]
    requested = 0
    allocated = 0
    for o in orders:
        for l in order_lines(o["id"]):
            requested += l["qty_requested"]
            allocated += l["qty_allocated"]
    if requested > 0:
        fill_component = Decimal(100 * allocated) / Decimal(requested)
    else:
        fill_component = Decimal(100)
    final = (W_VISIT * visit_component + W_PULL * pull_component
             + W_FILL * fill_component).quantize(SCORE_Q, rounding=ROUND_HALF_UP)
    return float(provisional), float(final)


# ---------------------------------------------------------------------------
# order pricing (calculations.order_total_pricing — pinned evaluation order)
# ---------------------------------------------------------------------------

def price_order(order):
    lines = order_lines(order["id"])
    for l in lines:  # (1) line totals, integer cents, no rounding
        l["line_total_cents"] = l["qty_allocated"] * l["unit_price_cents"]
    merch = sum(l["line_total_cents"] for l in lines)  # (2)
    if merch >= TIER1_THRESHOLD_CENTS:  # (3) tier keyed on PRE-discount total
        tier = TIER1_PCT
    elif merch >= TIER2_THRESHOLD_CENTS:
        tier = TIER2_PCT
    elif merch >= TIER3_THRESHOLD_CENTS:
        tier = TIER3_PCT
    else:
        tier = Decimal(0)
    discount = int((Decimal(merch) * tier).quantize(CENT, rounding=ROUND_HALF_UP))  # (4)
    # (5) fee keyed on POST-discount total; never feeds back into the tier
    fee = 0 if (merch - discount) >= FREE_DELIVERY_THRESHOLD_CENTS else DELIVERY_FEE_CENTS
    order["merchandise_total_cents"] = merch
    order["discount_cents"] = discount
    order["delivery_fee_cents"] = fee
    order["total_cents"] = merch - discount + fee  # (6)


# ---------------------------------------------------------------------------
# weekly allocation waterfall (calculations.weekly_allocation_waterfall)
# ---------------------------------------------------------------------------

def allocate_week(delivery_week):
    orders = [o for o in db["orders"].values()
              if o["delivery_week"] == delivery_week and o["allocation_status"] == "PENDING"]

    def rank(o):
        d = db["distributors"].get(o["distributor_id"])
        tier = d["service_level_tier"] if d is not None else "STANDARD"
        return (TIER_RANK.get(tier, 2), o["created_at"], o["_seq"])

    orders.sort(key=rank)
    now = store.now()
    for order in orders:
        for line in order_lines(order["id"]):
            remaining = line["qty_requested"] - line["qty_allocated"]
            if remaining <= 0:
                continue
            pool = [l for l in db["lots"].values() if l["product_id"] == line["product_id"]]
            for l in pool:
                lazy_lot(l)
            pool = [l for l in pool
                    if l["status"] == "AVAILABLE" and l["expires_at"] > now
                    and l["available_units"] > 0]
            pool.sort(key=lambda l: (l["expires_at"], l["_seq"]))  # FEFO
            granted = 0
            for lot in pool:
                if remaining <= 0:
                    break
                take = min(remaining, lot["available_units"])
                lot["available_units"] -= take
                lot["allocated_units"] += take
                remaining -= take
                granted += take
            line["qty_allocated"] += granted
        lines = order_lines(order["id"])
        total_alloc = sum(l["qty_allocated"] for l in lines)
        if all(l["qty_allocated"] == l["qty_requested"] for l in lines):
            order["allocation_status"] = "ALLOCATED"
        elif total_alloc > 0:
            order["allocation_status"] = "PARTIAL"
        else:
            order["allocation_status"] = "SHORTED"
        if order["allocation_status"] == "SHORTED":
            # a SHORTED order has every money field written as zero (PRD SS3.3)
            for l in lines:
                l["line_total_cents"] = 0
            order["merchandise_total_cents"] = 0
            order["discount_cents"] = 0
            order["delivery_fee_cents"] = 0
            order["total_cents"] = 0
        else:
            price_order(order)
        touch(order)
    return orders


# ---------------------------------------------------------------------------
# cascades (PRD SS2.9 / SS3)
# ---------------------------------------------------------------------------

def release_order_allocations(order):
    """Release the order's allocated units back to availability in reverse
    first-expiry order: latest expires_at first, ties by latest created first."""
    for line in order_lines(order["id"]):
        remaining = line["qty_allocated"]
        if remaining <= 0:
            continue
        pool = [l for l in db["lots"].values()
                if l["product_id"] == line["product_id"] and l["allocated_units"] > 0]
        pool.sort(key=lambda l: (l["expires_at"], l["_seq"]), reverse=True)
        for lot in pool:
            if remaining <= 0:
                break
            take = min(remaining, lot["allocated_units"])
            lot["allocated_units"] -= take
            lot["available_units"] += take
            remaining -= take


def cancel_order(order):
    release_order_allocations(order)
    order["allocation_status"] = "CANCELLED"
    touch(order)


def cancel_open_visits(distributor_id):
    for v in db["visits"].values():
        if v["distributor_id"] == distributor_id and v["status"] in ("SCHEDULED", "REWORK"):
            v["status"] = "CANCELLED"
            touch(v)


def suspend_account(account):
    """APPROVED -> SUSPENDED with the full account-suspension cascade (SS3.2)."""
    now = store.now()
    account["approval_status"] = "SUSPENDED"
    touch(account)
    for a in db["authorizations"].values():
        if a["account_id"] == account["id"] and a["status"] == "AUTHORIZED":
            a["status"] = "SUSPENDED"
            a["suspension_source"] = "ACCOUNT_SUSPEND"
            touch(a)
    for l in db["logs"].values():
        if l["account_id"] == account["id"] and l["status"] == "OPEN":
            l["status"] = "FORCE_PULLED"
            l["pulled_at"] = now
            touch(l)


def reinstate_account(account):
    """SUSPENDED -> APPROVED; restores only ACCOUNT_SUSPEND-sourced auths."""
    account["approval_status"] = "APPROVED"
    touch(account)
    for a in db["authorizations"].values():
        if (a["account_id"] == account["id"] and a["status"] == "SUSPENDED"
                and a["suspension_source"] == "ACCOUNT_SUSPEND"):
            a["status"] = "AUTHORIZED"
            a["suspension_source"] = "NONE"
            touch(a)


def reject_delivery_effects(delivery):
    """PENDING -> REJECTED: goods return from delivered to the allocated pool
    per line; the order's fulfillment dimension becomes REJECTED."""
    for line in delivery["lines"]:
        lot = db["lots"][line["lot_id"]]
        lot["delivered_units"] -= line["qty"]
        lot["allocated_units"] += line["qty"]
    delivery["status"] = "REJECTED"
    touch(delivery)
    order = db["orders"].get(delivery["order_id"])
    if order is not None and order["fulfillment_status"] == "IN_TRANSIT":
        order["fulfillment_status"] = "REJECTED"
        touch(order)


# ---------------------------------------------------------------------------
# incident cascades (PRD SS3.8); idempotent on entities already in target state
# ---------------------------------------------------------------------------

def incident_confirm_recall(incident):
    now = store.now()
    plant = db["plants"].get(incident["plant_id"])
    if plant is not None and plant["status"] != "SHUTDOWN":
        plant["status"] = "SHUTDOWN"
        touch(plant)
    for r in db["runs"].values():
        if r["plant_id"] == incident["plant_id"] and r["status"] == "SCHEDULED":
            r["status"] = "CANCELLED"
            touch(r)
    run_ids = set(incident["affected_run_ids"])
    newly_quarantined = set()
    for lot in db["lots"].values():
        if lot["production_run_id"] in run_ids and lot["status"] == "AVAILABLE":
            lot["status"] = "QUARANTINED"
            newly_quarantined.add(lot["id"])
    # link 2: reject PENDING deliveries whose lines contain a newly quarantined lot
    for d in db["deliveries"].values():
        if d["status"] == "PENDING" and any(
                line["lot_id"] in newly_quarantined for line in d["lines"]):
            reject_delivery_effects(d)
    product_ids = affected_product_ids(incident)
    for a in db["authorizations"].values():
        if a["status"] == "AUTHORIZED" and a["product_id"] in product_ids:
            a["status"] = "SUSPENDED"
            a["suspension_source"] = "INCIDENT"
            touch(a)
    for p in db["promos"].values():
        if p["status"] == "AUTHORIZED" and p["product_id"] in product_ids:
            p["status"] = "SUSPENDED"
            touch(p)


def incident_resolve(incident, outcome):
    run_ids = set(incident["affected_run_ids"])
    product_ids = affected_product_ids(incident)
    if outcome == "CONFIRMED":
        for lot in db["lots"].values():
            if lot["production_run_id"] in run_ids and lot["status"] == "QUARANTINED":
                lot["status"] = "RECALLED"
        for a in db["authorizations"].values():
            if (a["status"] == "SUSPENDED" and a["suspension_source"] == "INCIDENT"
                    and a["product_id"] in product_ids):
                a["status"] = "REVOKED"
                touch(a)
        # plant stays SHUTDOWN
    else:  # FALSE_ALARM
        for lot in db["lots"].values():
            if lot["production_run_id"] in run_ids and lot["status"] == "QUARANTINED":
                lot["status"] = "AVAILABLE"
        for a in db["authorizations"].values():
            if (a["status"] == "SUSPENDED" and a["suspension_source"] == "INCIDENT"
                    and a["product_id"] in product_ids):
                a["status"] = "AUTHORIZED"
                a["suspension_source"] = "NONE"
                touch(a)
        for p in db["promos"].values():
            if p["status"] == "SUSPENDED" and p["product_id"] in product_ids:
                p["status"] = "AUTHORIZED"
                touch(p)
        plant = db["plants"].get(incident["plant_id"])
        if plant is not None and plant["status"] == "SHUTDOWN":
            plant["status"] = "ACTIVE"
            touch(plant)
    incident["resolution_outcome"] = outcome
