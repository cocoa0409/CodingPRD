"""The nine pinned calculations of PRD sections 2.6, 2.9, 3.4, 3.6, 3.7 and 3.9."""
from decimal import Decimal, ROUND_HALF_UP

import db
from db import store

# --- constants (PRD 2.10 / 3.4 / 3.6 / 3.7) --------------------------------------------
SHOP_RATE_CENTS = {
    "BODY": 6500,
    "FRAME": 8500,
    "REFINISH": 6000,
    "MECHANICAL": 12500,
    "ALUMINUM_BODY": 9500,
}
LABOR_TYPES = ("BODY", "FRAME", "REFINISH", "MECHANICAL", "ALUMINUM_BODY")

OVERLAP_DEDUCTION_HOURS = Decimal("0.4")
BLEND_FACTOR = Decimal("0.5")
CLEARCOAT_ADDER_HOURS = Decimal("0.3")

SUPPLIES_RATE = Decimal("0.04")
SUPPLIES_CAP_CENTS = 25000
PARTS_TIER_1_FLOOR_CENTS = 100000
PARTS_TIER_2_FLOOR_CENTS = 500000
BETTERMENT_PCT = Decimal("0.2")

ROLLING_WINDOW_SIZE = 3
WEIGHT_ON_TIME = Decimal("0.6")
WEIGHT_NO_RETURN = Decimal("0.25")
WEIGHT_FIRST_ROUND = Decimal("0.15")
NEW_VENDOR_DEFAULT_SCORE = 50
VENDOR_SCORE_FLOOR = 40

CONSENT_THRESHOLD_CENTS = 50000
WARRANTY_DAYS = 365


# --- rounding discipline (PRD 2.6) -----------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_cents(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_hours(value):
    q = dec(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(q)


def round_whole(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- version bumping, once per row per request (PRD 2.4 / 2.9) -------------------------
class Bumper(object):
    """Collects the rows a request mutated so each one's version moves exactly once."""

    def __init__(self):
        self.rows = []

    def add(self, row):
        if row is None:
            return
        for existing in self.rows:
            if existing is row:
                return
        self.rows.append(row)

    def flush(self):
        for row in self.rows:
            db.touch(row)
        self.rows = []


# --- row traversal helpers -------------------------------------------------------------
def children(table, key, value):
    rows = [r for r in table.values() if r.get(key) == value]
    return db.in_creation_order(rows)


def order_estimate_lines(order_id):
    return children(store.estimate_lines, "repair_order_id", order_id)


def order_parts_lines(order_id):
    line_ids = set(e["id"] for e in store.estimate_lines.values()
                   if e.get("repair_order_id") == order_id)
    rows = [p for p in store.parts_lines.values() if p.get("estimate_line_id") in line_ids]
    return db.in_creation_order(rows)


def order_supplements(order_id):
    return children(store.supplements, "repair_order_id", order_id)


def order_procedure_records(order_id):
    return children(store.procedure_records, "repair_order_id", order_id)


def order_assignments(order_id):
    return children(store.stage_assignments, "repair_order_id", order_id)


def order_delay_events(order_id):
    return children(store.parts_delay_events, "repair_order_id", order_id)


def order_qc_inspections(order_id):
    return children(store.qc_inspections, "repair_order_id", order_id)


def order_damage_lines(order_id):
    return children(store.damage_lines, "repair_order_id", order_id)


def parts_line_order(parts_line):
    """Resolve PartsLine -> EstimateLine -> RepairOrder."""
    line = store.estimate_lines.get(parts_line.get("estimate_line_id"))
    if line is None:
        return None
    return store.repair_orders.get(line.get("repair_order_id"))


def parts_line_estimate_line(parts_line):
    return store.estimate_lines.get(parts_line.get("estimate_line_id"))


# --- calculation 1: refinish_labor_allocation (PRD 3.4) --------------------------------
def refinish_allocation(order, variant, bumper=None):
    lines = order_estimate_lines(order["id"])
    refinish = [l for l in lines if l["labor_type"] == "REFINISH"]
    if variant == "PROVISIONAL":
        wanted = [l for l in refinish if l["line_status"] == "DRAFT"]
        total = Decimal("0")
        for line in wanted:
            total += dec(round_hours(line["guide_hours"]))
        order["refinish_hours_provisional"] = round_hours(total)
        return

    wanted = [l for l in refinish if l["line_status"] == "APPROVED"]
    if not wanted:
        order["refinish_hours_final"] = 0.0
        return
    ranked = sorted(
        wanted,
        key=lambda l: (-dec(l["guide_hours"]), l["created_at"], l["operation_code"], l["_seq"]),
    )
    total = Decimal("0")
    for index, line in enumerate(ranked):
        guide = dec(line["guide_hours"])
        if index == 0:
            hours = guide + (CLEARCOAT_ADDER_HOURS if line.get("two_stage") else Decimal("0"))
        elif line.get("is_blend"):
            hours = guide * BLEND_FACTOR
        elif line.get("is_adjacent_panel"):
            hours = guide - OVERLAP_DEDUCTION_HOURS
        else:
            hours = guide
        allocated = round_hours(hours)
        if allocated < 0:
            allocated = 0.0
        if line.get("allocated_hours") != allocated and bumper is not None:
            bumper.add(line)
        line["allocated_hours"] = allocated
        total += dec(allocated)
    order["refinish_hours_final"] = round_hours(total)


def apply_non_refinish_hours(order, bumper=None):
    """Non-refinish approved lines take their guide_hours verbatim (PRD 3.4)."""
    for line in order_estimate_lines(order["id"]):
        if line["labor_type"] == "REFINISH":
            continue
        if line["line_status"] != "APPROVED":
            continue
        allocated = round_hours(line["guide_hours"])
        if line.get("allocated_hours") != allocated and bumper is not None:
            bumper.add(line)
        line["allocated_hours"] = allocated


# --- calculation 2: approved_labor_hours_rollup (PRD 3.4) ------------------------------
def approved_hours_rollup(order):
    total = Decimal("0")
    for line in order_estimate_lines(order["id"]):
        if line["line_status"] == "APPROVED" and line.get("allocated_hours") is not None:
            total += dec(line["allocated_hours"])
    order["approved_labor_hours"] = round_hours(total)


# --- calculation 3: parts_line_extended_price (PRD 3.5) --------------------------------
def parts_unit_extended(parts_line, vendor):
    unit_price = parts_line.get("unit_price_cents")
    if unit_price is None:
        return None
    discount = dec(vendor.get("discount_pct", 0))
    unit = round_cents(dec(unit_price) * (Decimal("1") - discount))
    if parts_line["part_type"] == "RECONDITIONED":
        unit += int(vendor.get("core_charge_cents", 0))
    return unit


def parts_extended_price(parts_line):
    unit = parts_line.get("unit_extended_cents")
    if unit is None:
        return 0
    surviving = int(parts_line["qty"]) - int(parts_line.get("returned_qty", 0) or 0)
    if surviving < 0:
        surviving = 0
    return unit * surviving


def restocking_fee(parts_line, vendor, return_qty, return_reason):
    if return_reason != "UNUSED":
        return 0
    unit = parts_line.get("unit_extended_cents") or 0
    pct = dec(vendor.get("restocking_fee_pct", 0.2))
    return round_cents(dec(unit) * dec(return_qty) * pct)


# --- calculation 4: estimate_totals, the eight steps (PRD 3.4) -------------------------
TOTALS_PARTS_PROCUREMENT = ("PRICE_LOCKED", "ORDERED", "RECEIVED", "INSTALLED")
TOTALS_PARTS_AUTHORIZATION = ("INSURER_ALLOWED", "CUSTOMER_CONSENTED")


def totals_parts_input_set(order_id):
    rows = []
    for line in order_parts_lines(order_id):
        if line["authorization_status"] not in TOTALS_PARTS_AUTHORIZATION:
            continue
        if line["procurement_status"] not in TOTALS_PARTS_PROCUREMENT:
            continue
        rows.append(line)
    return rows


def estimate_totals(order, bumper=None):
    insurer = store.insurers.get(order["insurer_id"]) or {}
    ceilings = insurer.get("rate_ceiling_cents") or {}

    # step 1: labor
    labor_subtotal = 0
    for line in order_estimate_lines(order["id"]):
        if line["line_status"] != "APPROVED":
            continue
        posted = SHOP_RATE_CENTS[line["labor_type"]]
        ceiling = ceilings.get(line["labor_type"])
        rate = posted if ceiling is None else min(posted, int(ceiling))
        hours = line.get("allocated_hours")
        if hours is None:
            hours = round_hours(line["guide_hours"])
        amount = round_cents(dec(hours) * dec(rate))
        if bumper is not None and (line.get("effective_rate_cents") != rate
                                  or line.get("line_amount_cents") != amount):
            bumper.add(line)
        line["effective_rate_cents"] = rate
        line["line_amount_cents"] = amount
        labor_subtotal += amount
    order["labor_subtotal_cents"] = labor_subtotal

    # step 2: parts gross
    parts_input = totals_parts_input_set(order["id"])
    parts_gross = sum(int(p.get("extended_price_cents") or 0) for p in parts_input)
    order["parts_gross_cents"] = parts_gross

    # step 3: volume rebate on an average rate
    if parts_gross < PARTS_TIER_1_FLOOR_CENTS:
        pct = Decimal("0")
    elif parts_gross < PARTS_TIER_2_FLOOR_CENTS:
        pct = Decimal("0.03")
    else:
        pct = Decimal("0.05")
    parts_discount = round_cents(dec(parts_gross) * pct)
    order["parts_discount_cents"] = parts_discount
    order["parts_subtotal_cents"] = parts_gross - parts_discount

    # step 4: betterment
    betterment = 0
    for line in parts_input:
        if not line.get("oem_upgrade"):
            continue
        unit = int(line.get("unit_extended_cents") or 0)
        betterment += round_cents(dec(unit) * dec(line["qty"]) * BETTERMENT_PCT)
    order["betterment_cents"] = betterment

    # step 5: paint and materials, capped
    supplies = round_cents(dec(labor_subtotal) * SUPPLIES_RATE)
    order["supplies_fee_cents"] = min(supplies, SUPPLIES_CAP_CENTS)

    # step 6: pre-tax total
    pre_tax = labor_subtotal + order["supplies_fee_cents"] + order["parts_subtotal_cents"]
    order["pre_tax_total_cents"] = pre_tax

    # step 7: insurer authorization
    ceiling_total = int(order["initial_authorized_cents"])
    for supplement in order_supplements(order["id"]):
        if supplement["status"] in ("APPROVED", "PARTIAL"):
            ceiling_total += int(supplement.get("approved_amount_cents") or 0)
    authorized = pre_tax - int(order["deductible_cents"]) - betterment
    if authorized > ceiling_total:
        authorized = ceiling_total
    if authorized < 0:
        authorized = 0
    order["insurer_authorized_cents"] = authorized

    # step 8: the customer's share
    order["customer_pay_cents"] = pre_tax - authorized


# --- calculation 5: vendor_fulfillment_score (PRD 3.6) ---------------------------------
def vendor_score(vendor):
    closed = [p for p in store.parts_lines.values()
              if p.get("vendor_id") == vendor["id"] and p.get("received_at") is not None]
    closed.sort(key=lambda p: (-(p.get("vendor_order_seq") or 0), p["_seq"]))

    def score_over(window):
        if not window:
            return NEW_VENDOR_DEFAULT_SCORE
        size = Decimal(len(window))
        on_time = Decimal(sum(1 for p in window if p.get("on_time") is True)) / size
        no_return = Decimal(sum(1 for p in window if int(p.get("returned_qty") or 0) == 0)) / size
        first_round = Decimal(sum(1 for p in window if int(p.get("quote_round") or 0) <= 1)) / size
        raw = Decimal(100) * (WEIGHT_ON_TIME * on_time
                              + WEIGHT_NO_RETURN * no_return
                              + WEIGHT_FIRST_ROUND * first_round)
        return round_whole(raw)

    vendor["fulfillment_score_rolling"] = score_over(closed[:ROLLING_WINDOW_SIZE])
    vendor["fulfillment_score_lifetime"] = score_over(closed)


# --- calculation 6: parts_commitment_ledger (PRD 2.9 / 3.6) ---------------------------
LEDGER_COMMITTED_STATES = ("ORDERED", "RECEIVED", "INSTALLED")


def commitment_ledger(order):
    committed = 0
    credit = 0
    loss = 0
    for line in order_parts_lines(order["id"]):
        unit = int(line.get("unit_extended_cents") or 0)
        returned = int(line.get("returned_qty") or 0)
        if line["procurement_status"] in LEDGER_COMMITTED_STATES:
            committed += unit * (int(line["qty"]) - returned)
        if returned > 0:
            fee = int(line.get("restocking_fee_cents") or 0)
            credit += unit * returned - fee
            loss += fee
    order["parts_committed_cents"] = committed
    order["parts_return_credit_cents"] = credit
    order["parts_restocking_loss_cents"] = loss


# --- calculation 7: stall_occupancy_rollup (PRD 2.9 / 3.8) ----------------------------
def stall_rollup(stall, bumper=None):
    total = 0
    for assignment in store.stage_assignments.values():
        if assignment.get("stall_id") != stall["id"]:
            continue
        if assignment["status"] in ("SCHEDULED", "ACTIVE"):
            total += int(assignment.get("occupied_minutes") or 0)
    if stall.get("booked_minutes") != total and bumper is not None:
        bumper.add(stall)
    stall["booked_minutes"] = total


def bay_rollup(bay, bumper=None):
    total = 0
    for record in store.procedure_records.values():
        if record.get("bay_id") == bay["id"] and record.get("calibration_status") == "SCHEDULED":
            total += 1
    if bay.get("scheduled_window_count") != total and bumper is not None:
        bumper.add(bay)
    bay["scheduled_window_count"] = total


# --- pure roll-up counters on the order (PRD 2.9) -------------------------------------
def recount_teardown_findings(order):
    order["teardown_finding_count"] = len(order_damage_lines(order["id"]))


def recount_open_delays(order):
    order["open_parts_delay_count"] = sum(
        1 for e in order_delay_events(order["id"]) if e.get("closed_at") is None)


def recount_qc_inspections(order):
    order["qc_inspection_count"] = len(order_qc_inspections(order["id"]))


# --- calculation 8: authorization_posture_derivation (PRD 3.7) ------------------------
def derive_posture(order):
    customer_pay = int(order.get("customer_pay_cents") or 0)
    basis = order.get("consent_basis_cents")
    consent_gap = customer_pay >= CONSENT_THRESHOLD_CENTS and (
        order.get("consent_state") != "CONSENTED"
        or basis is None
        or int(basis) < customer_pay
    )
    parts = [p for p in order_parts_lines(order["id"]) if p["procurement_status"] != "VOID"]
    pending_alternate = any(p["authorization_status"] == "PENDING_CONSENT" for p in parts)
    supplement_open = any(s["status"] in ("SUBMITTED", "INFO_REQUESTED")
                          for s in order_supplements(order["id"]))

    # stale-consent compensation, applied before the posture is chosen
    if order.get("consent_state") == "CONSENTED" and basis is not None and int(basis) < customer_pay:
        order["consent_state"] = "NONE"
        order["consent_basis_cents"] = None
        order["consent_alternate_parts"] = False

    if consent_gap or pending_alternate:
        order["authorization_posture"] = "CONSENT_REQUIRED"
    elif supplement_open:
        order["authorization_posture"] = "SUPPLEMENT_PENDING"
    else:
        order["authorization_posture"] = "OPEN"


# --- calculation 9: cycle_time_metrics (PRD 3.9) --------------------------------------
def _floor_minutes(start, end):
    return db.floor_minutes(start, end)


def cycle_time(order):
    window_start = db.parse_iso(order["checkin_at"])
    if order.get("delivered_at"):
        window_end = db.parse_iso(order["delivered_at"])
    else:
        window_end = db.now()

    gross = _floor_minutes(window_start, window_end)

    raw = []
    for supplement in order_supplements(order["id"]):
        start = db.parse_iso(supplement.get("submitted_at"))
        if start is None:
            continue
        end_iso = supplement.get("decided_at")
        end = db.parse_iso(end_iso) if end_iso else window_end
        raw.append((start, end, end_iso is None, "supplement"))
    for event in order_delay_events(order["id"]):
        start = db.parse_iso(event.get("opened_at"))
        if start is None:
            continue
        end_iso = event.get("closed_at")
        end = db.parse_iso(end_iso) if end_iso else window_end
        raw.append((start, end, end_iso is None, "delay"))

    raw = [iv for iv in raw if iv[1] > iv[0]]
    open_interval_count = sum(1 for iv in raw if iv[2])

    def clamp(start, end):
        low = start if start > window_start else window_start
        high = end if end < window_end else window_end
        return low, high

    supplement_wait = 0
    parts_delay = 0
    clamped = []
    for start, end, _is_open, kind in raw:
        low, high = clamp(start, end)
        minutes = _floor_minutes(low, high) if high > low else 0
        if kind == "supplement":
            supplement_wait += minutes
        else:
            parts_delay += minutes
        if high > low:
            clamped.append([low, high])

    merged = []
    for interval in sorted(clamped, key=lambda x: (x[0], x[1])):
        if merged and interval[0] <= merged[-1][1]:
            if interval[1] > merged[-1][1]:
                merged[-1][1] = interval[1]
        else:
            merged.append([interval[0], interval[1]])
    excluded = sum(_floor_minutes(a, b) for a, b in merged)

    net = gross - excluded
    if net < 0:
        net = 0
    return {
        "gross_minutes": gross,
        "net_touch_minutes": net,
        "excluded_minutes": excluded,
        "supplement_wait_minutes": supplement_wait,
        "parts_delay_minutes": parts_delay,
        "open_interval_count": open_interval_count,
    }
