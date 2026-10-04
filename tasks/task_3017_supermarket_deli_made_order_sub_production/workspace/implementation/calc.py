"""Calculation rules (SCAFFOLD Table 3 / PRD 3.3, 3.4, 3.5, 3.6, 3.7).

Each function mirrors one scaffold calculation, preserving the pinned rounding
point: components are never pre-rounded unless the rule names that step.
"""
import math
from decimal import Decimal

from util import (
    dt_add_hours, dt_add_minutes, dt_minutes_between, parse_dt, rhu, rhu_int,
    to_dec,
)

# ---------------------------------------------------------------- constants --
RETAIL_LABOR_LOAD_CENTS = 45
SLICER_CUTS_PER_FEE_UNIT = 20
FEE_PER_CUT_UNIT_CENTS = 6
WASTE_RECOVERY_RATE = Decimal("0.70")
NET_MARKDOWN_RATE = Decimal("0.50")

HALF_LB_UNIT = Decimal("0.5")

BREAD_WASTE_FACTOR = Decimal("0.12")
UNITS_PER_CASE = 12
SETTLEMENT_UPLIFT_CAP = Decimal("0.35")
DEGRADED_SHORT_RATIO = Decimal("0.5")

BASE_INDEX = 100
CERT_WEIGHT = 12
FISCAL_WEIGHT = 6
SLICER_WEIGHT = 4
PROTECTION_FLOOR = 0
PROTECTION_RESTRICTED_AT_OR_BELOW = 30

TIMED_MULTIPLIER = 3
CUTS_PER_BATCH_DIVISOR = 5

MINUTES_PER_REQUIRED_BATCH = 12
MINUTES_PER_HALF_LB = 1

TIER_1_RATE_CENTS = 1800
TIER_2_RATE_CENTS = 1650
TIER_3_RATE_CENTS = 1500
TIER_2_MIN = 3
TIER_2_MAX = 6
RUSH_LIMIT_HOURS = 24
RUSH_FEE_CENTS = 2600
CERTIFIED_ADJUSTMENT_PCT = Decimal("-0.05")

DISCOUNTED_BASE_RATE = Decimal("0.70")
PRIOR_TIER_RATE = Decimal("0.30")
TIER_1_MAX_EXCLUSIVE_CENTS = 5000
TIER_2_MAX_EXCLUSIVE_CENTS = 15000
FEE_TIER_1_CENTS = 0
FEE_TIER_2_CENTS = 250
FEE_TIER_3_CENTS = 600

GRACE_WINDOW_HOURS = 72


# ------------------------------------------------------- certification facts --
def cert_is_active(cert, clock):
    """ACTIVE and expires_at strictly after the clock."""
    return (cert["status"] == "ACTIVE"
            and parse_dt(cert["expires_at"]) > parse_dt(clock))


def has_active_cert(certs, associate_id, cert_type, clock, store_id=None,
                    deli_item_id=None, for_grace=False):
    for cert in certs:
        if cert["associate_id"] != associate_id:
            continue
        if store_id is not None and cert["store_id"] != store_id:
            continue
        if cert["cert_type"] != cert_type:
            continue
        if for_grace:
            if cert["status"] != "ACTIVE":
                continue
        elif not cert_is_active(cert, clock):
            continue
        if deli_item_id is not None and cert["deli_item_id"] not in (None, deli_item_id):
            continue
        return True
    return False


def active_certification_count(certs, associate_id, clock):
    return sum(1 for c in certs if c["associate_id"] == associate_id
               and cert_is_active(c, clock))


def grace_reminder(cert, clock):
    if cert["status"] != "ACTIVE":
        return False
    expires = parse_dt(cert["expires_at"])
    now = parse_dt(clock)
    if expires <= now:
        return False
    return (expires - now).total_seconds() <= GRACE_WINDOW_HOURS * 3600


def certified_slicer_operator_count(associates, certs, store_id, clock):
    """Associates in the store ACTIVE and holding >=1 live SLICER_OPERATION cert."""
    total = 0
    for assoc in associates:
        if assoc["store_id"] != store_id or assoc["status"] != "ACTIVE":
            continue
        if has_active_cert(certs, assoc["id"], "SLICER_OPERATION", clock):
            total += 1
    return total


# ------------------------------------------------------------- batch costing --
def cuts_for_weight(produced_lbs):
    return int(math.ceil(float(to_dec(produced_lbs)) / CUTS_PER_BATCH_DIVISOR))


def batch_case_yield_cost(batch, item, slicer):
    """Dual-variant case yield cost.

    PRD §3.3: ``provisional`` is the Operating variant. ``final`` is the
    WASTE_LEDGER variant, reported once a VERIFIED waste record exists; it "adds
    two further terms to the same base", i.e. to the provisional figure itself —
    the verified handling fees and the net markdown recovery. Both figures are
    therefore computed off one shared base, and verification adds only those two
    terms rather than re-deriving the base from a changed `discard_lbs`.
    """
    produced = to_dec(batch["produced_lbs"])
    unit_cost = to_dec(item["unit_cost_cents"])
    lb_cost = produced * unit_cost
    if batch["production_status"] == "ON_LINE":
        lb_cost += RETAIL_LABOR_LOAD_CENTS
    if slicer is not None:
        fee_units = int(to_dec(slicer["cuts_since_sanitation"]) // SLICER_CUTS_PER_FEE_UNIT)
        lb_cost += fee_units * FEE_PER_CUT_UNIT_CENTS

    recovery = WASTE_RECOVERY_RATE * to_dec(batch["discard_lbs"]) * unit_cost
    provisional = rhu_int(lb_cost - recovery)

    verified_fees = sum(
        w["handling_fee_cents"] for w in batch["_verified_waste"]
    )
    markdown_net = (NET_MARKDOWN_RATE * to_dec(item["retail_price_per_lb_cents"])
                    * to_dec(batch["markdown_sold_lbs"]))
    final = provisional + rhu_int(verified_fees) + rhu_int(markdown_net)
    return provisional, final


# ----------------------------------------------------------- ticket pricing ---
def sub_ticket_line_total(ticket, item, item_lookup, uplift_pct):
    """Round each line to whole cents, then sum (pinned rounding order).

    PRD §3.4 prices each line from "the ordered item's
    `retail_price_per_lb_cents`"; a line's ordered item is the `deli_item_id` it
    names, so two lines naming different items are priced independently.
    """
    grouped = {}
    order = []
    for line in ticket["lines"]:
        key = line["line_sequence_number"]
        if key not in grouped:
            grouped[key] = [Decimal(0), line["deli_item_id"]]
            order.append(key)
        grouped[key][0] += to_dec(line["half_lb_units"])
    total = 0
    for key in order:
        units, line_item_id = grouped[key]
        line_item = item_lookup.get(line_item_id) if item_lookup else None
        if line_item is None:
            line_item = item
        price = to_dec(line_item["retail_price_per_lb_cents"])
        line_extent_lbs = units * HALF_LB_UNIT
        line_cost = rhu_int(line_extent_lbs * price)
        line_promo = rhu_int(to_dec(line_cost) * to_dec(uplift_pct))
        total += line_cost - line_promo
    return total


def batch_codes_for_lines(ticket, item_lookup):
    """Distinct production batches the ticket's lines require.

    A line's batch is the batch planned for the same item; when several exist
    the oldest is the one the line is drawn from.
    """
    codes = set()
    for line in ticket["lines"]:
        item_id = line["deli_item_id"]
        for code in item_lookup.get(item_id, []):
            codes.add(code)
            break
    return len(codes)


def promised_time_sla(ticket, item_lookup, clock):
    batches = batch_codes_for_lines(ticket, item_lookup)
    units = int(math.ceil(float(to_dec(ticket["weight_lbs"]) / HALF_LB_UNIT)))
    prep = MINUTES_PER_REQUIRED_BATCH * batches + units * MINUTES_PER_HALF_LB
    return dt_add_minutes(clock, prep), prep


def lateness_minutes(completed_at, promised_at):
    if completed_at is None or promised_at is None:
        return 0
    minutes = int(dt_minutes_between(completed_at, promised_at))
    return max(0, minutes)


# ------------------------------------------------------------ promotions ------
def promo_bread_demand(promotion, settled=False):
    baseline = to_dec(promotion["trailing_baseline_units"])
    uplift = to_dec(promotion["forecast_uplift_pct"])
    if settled:
        uplift = min(uplift, SETTLEMENT_UPLIFT_CAP)
    forecast_units = rhu_int(baseline * (1 + uplift))
    bread_units = forecast_units + rhu_int(to_dec(forecast_units) * BREAD_WASTE_FACTOR)
    cases = int(math.ceil(bread_units / UNITS_PER_CASE)) if bread_units > 0 else 0
    return cases * UNITS_PER_CASE


def bread_forecast_coverage(order, tickets):
    reserved = sum(
        1 for t in tickets
        if t["store_id"] == order["store_id"]
        and t["bread_deli_item_id"] == order["bread_deli_item_id"]
        and t["status"] in ("TICKETED", "IN_PROGRESS")
    )
    units_short = (max(0, order["required_units"] - order["committed_units"])
                   + max(0, reserved - order["committed_units"]))
    degraded = units_short > 0
    return reserved, units_short, degraded


# ------------------------------------------------------------ indices ---------
def diffusion_index(store, associates, certs, waste_records, slicers, clock):
    cert_expired_count = 0
    for assoc in associates:
        if assoc["store_id"] != store["id"] or assoc["status"] != "ACTIVE":
            continue
        if not has_active_cert(certs, assoc["id"], "SLICER_OPERATION", clock):
            cert_expired_count += 1
    fiscal_backlog_count = sum(
        1 for w in waste_records
        if w["store_id"] == store["id"]
        and w["status"] in ("DRAFT", "MARKED_DOWN", "DISCARDED")
    )
    slicer_due_count = sum(
        1 for s in slicers
        if s["store_id"] == store["id"] and s["sanitation_status"] == "NEEDS_SANITATION"
    )
    protection = (BASE_INDEX
                  - CERT_WEIGHT * cert_expired_count
                  - FISCAL_WEIGHT * fiscal_backlog_count
                  - SLICER_WEIGHT * slicer_due_count)
    protection = max(protection, PROTECTION_FLOOR)
    return protection, BASE_INDEX - protection


def store_deli_posture(store, protection_index):
    """First firing predicate decides both posture and reason token."""
    if store["certified_slicer_operator_count"] == 0 or store["haccp_safety_flag"]:
        return "HALT", "CERTIFICATION_TRIGGERED"
    if store["posture_gate_flag"]:
        return "HALT", "POSTURE_GATE_TRIGGERED"
    over_capacity = to_dec(store["case_on_hand_lbs"]) > to_dec(store["deli_case_capacity_lbs"])
    revoked = protection_index <= PROTECTION_RESTRICTED_AT_OR_BELOW
    no_file = store["active_price_file_id"] is None
    if over_capacity or revoked or no_file:
        if over_capacity:
            reason = "INVENTORY_TRIGGERED"
        elif revoked:
            reason = "REVOCATION_TRIGGERED"
        else:
            reason = "NO_ACTIVE_PRICE_FILE"
        return "RESTRICTED", reason
    return "OPEN", "OK"


# ----------------------------------------------------------- hold windows -----
def hold_window_state(batch, item, clock):
    """PENDING | HOLDING | MARKDOWN_WINDOW | EXPIRED, evaluated half-open."""
    now = parse_dt(clock)
    produced = parse_dt(batch["produced_at"])
    case_life = item["case_life_minutes"]
    markdown_window = item["markdown_window_minutes"]
    expiry = parse_dt(dt_add_minutes(batch["produced_at"], case_life))
    if now < produced:
        return "PENDING"
    if now < parse_dt(dt_add_minutes(batch["produced_at"], case_life - markdown_window)):
        return "HOLDING"
    if now < expiry:
        return "MARKDOWN_WINDOW"
    return "EXPIRED"


def markdown_window_open(batch, item, clock):
    """Legal only inside the half-open markdown window itself.

    PRD 3.1: a markdown requested before the window opens fails just as one at
    or after the hold expiry does, so the pre-window HOLDING state is not
    eligible.
    """
    return hold_window_state(batch, item, clock) == "MARKDOWN_WINDOW"


def hold_window_closed(batch, item, clock):
    return hold_window_state(batch, item, clock) == "EXPIRED"


# ------------------------------------------------------------- sanitation -----
def sanitation_cycle_due(slicer, cycle_type):
    if cycle_type == "ROUTINE":
        return slicer["cuts_since_sanitation"] >= slicer["sanitation_cycle_limit"]
    if cycle_type == "TIMED":
        return slicer["in_use_minutes"] >= slicer["sanitation_cycle_limit"] * TIMED_MULTIPLIER
    return True


# --------------------------------------------------------------- price files --
def resolve_active_price_file(price_files, store_id, clock):
    now = parse_dt(clock)
    candidates = [
        f for f in price_files
        if f["store_id"] == store_id
        and f["status"] == "ACTIVE"
        and parse_dt(f["effective_from"]) <= now < parse_dt(f["effective_to"])
    ]
    if not candidates:
        return None
    # effective_from DESC, activated_at DESC, created_at ASC.
    candidates.sort(key=lambda f: (parse_dt(f["effective_from"]),
                                   parse_dt(f["activated_at"] or f["created_at"]),
                                   -parse_dt(f["created_at"]).timestamp()),
                    reverse=True)
    return candidates[0]


def price_files_overlap(a, b):
    """Half-open overlap between two intervals."""
    return (parse_dt(a["effective_from"]) < parse_dt(b["effective_to"])
            and parse_dt(b["effective_from"]) < parse_dt(a["effective_to"]))


# ------------------------------------------------------------ sub queue -------
def sub_queue_order(tickets, store_id):
    eligible = [
        t for t in tickets
        if t["store_id"] == store_id
        and t["status"] in ("TICKETED", "IN_PROGRESS")
        and t["bread_status"] == "QUEUED"
    ]
    eligible.sort(key=lambda t: (parse_dt(t["promised_at"]), t["creation_sequence"]))
    return eligible


# ---------------------------------------------------------------- catering ----
def truncate_to_quarter_hour(iso):
    dt = parse_dt(iso)
    return dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)


def pickup_bucket_key(pickup_window_start):
    from util import fmt_dt
    staged = parse_dt(pickup_window_start) - __import__("datetime").timedelta(minutes=10)
    return fmt_dt(truncate_to_quarter_hour(fmt_dt(staged)))


def catering_platter_quote(order, planner_certified):
    count = order["platter_count"]
    if count < TIER_2_MIN:
        rate = TIER_1_RATE_CENTS
    elif count <= TIER_2_MAX:
        rate = TIER_2_RATE_CENTS
    else:
        rate = TIER_3_RATE_CENTS

    if order["lead_time_hours"] < RUSH_LIMIT_HOURS and planner_certified:
        adjustment = CERTIFIED_ADJUSTMENT_PCT
    else:
        adjustment = Decimal("0")

    base_total = count * rate
    service_fee = rhu_int(to_dec(base_total) * adjustment)
    rush = RUSH_FEE_CENTS if order["lead_time_hours"] < RUSH_LIMIT_HOURS else 0
    return base_total + service_fee + rush


def bucket_headcount(catering_orders, key, exclude_id=None):
    total = 0
    for order in catering_orders:
        if order["id"] == exclude_id:
            continue
        if order["pickup_bucket_key"] != key:
            continue
        if order["status"] in ("CONFIRMED", "IN_PRODUCTION", "READY"):
            total += order["headcount"]
    return total


# ------------------------------------------------------------- waste ledger ---
def waste_liability(waste, item, prior_liability_cents):
    value_cents = rhu_int(to_dec(waste["discard_lbs"]) * to_dec(item["unit_cost_cents"]))
    discounted_base = rhu_int(DISCOUNTED_BASE_RATE * to_dec(value_cents)
                              + PRIOR_TIER_RATE * to_dec(prior_liability_cents))
    if discounted_base < TIER_1_MAX_EXCLUSIVE_CENTS:
        fee = FEE_TIER_1_CENTS
    elif discounted_base < TIER_2_MAX_EXCLUSIVE_CENTS:
        fee = FEE_TIER_2_CENTS
    else:
        fee = FEE_TIER_3_CENTS
    return value_cents, fee, value_cents + fee


def store_waste_liability(waste_records, store_id, clock):
    """Total and verified totals; created_at == clock is excluded."""
    now = parse_dt(clock)
    total = 0
    verified = 0
    for w in waste_records:
        if w["store_id"] != store_id:
            continue
        if w["status"] not in ("DISCARDED", "VERIFIED"):
            continue
        if w["reason"] == "UNCLAIMED_PLATTER":
            continue
        if not (parse_dt(w["created_at"]) < now):
            continue
        total += w["total_liability_cents"]
        if w["status"] == "VERIFIED":
            verified += w["total_liability_cents"]
    return total, verified


def label_total_price(net_weight_lbs, unit_price_cents):
    return rhu_int(to_dec(net_weight_lbs) * to_dec(unit_price_cents))