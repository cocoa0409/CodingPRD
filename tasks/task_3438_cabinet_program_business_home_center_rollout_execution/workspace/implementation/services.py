"""Business logic: pricing, delivery weeks, credit exposure, capacity selection,
color match, damage settlement, supersede cascade, and auto-retirement."""
import math
from datetime import timedelta
from decimal import Decimal

from db import bump, new_entity, store
from errors import api_error
from util import (add_weeks, iso3, parse_dt, parse_week, round_half_up_cents,
                  week_of)

# ---- PRD-pinned constants (PRD section 3 / scaffold calculations) ----
TIER1_GROSS_CENTS = 500000          # 5 percent tier threshold, pre-discount gross
TIER2_GROSS_CENTS = 2000000         # 8 percent tier threshold, pre-discount gross
TIER1_PCT = Decimal("0.05")
TIER2_PCT = Decimal("0.08")
CHANNEL_MULTIPLIERS = {
    "STANDARD": Decimal("1.00"),
    "VOLUME": Decimal("0.95"),
    "NATIONAL": Decimal("0.90"),
}
PROGRAM_DISCOUNT_CAP = Decimal("0.5")
COLOR_MATCH_TOLERANCE = 2.0         # inclusive
EXPEDITE_OVERBOOK_DIVISOR = 10      # floor(capacity_units * 0.10) == capacity_units // 10
MAX_SLIP_WEEKS = 4
EXTENDED_CLASS_EXTRA_WEEKS = 2
REVISION_CAP = 3
ATTEMPT_CAP = 3
CLAIM_WINDOW_DAYS = 14              # inclusive
RESET_DEADLINE_DAYS = 45
DISPOSITION_DEADLINE_DAYS = 90
SETTLEMENT_CAP_MULT = Decimal("1.20")
EARLY_FULL_DAYS = 7
LATE_FACTOR = Decimal("0.8")
TRAVEL_BUFFER_MINUTES = 30

OPEN_ORDER_STATUSES = (
    "SUBMITTED", "ACKNOWLEDGED", "SCHEDULED",
    "IN_PRODUCTION", "MFG_COMPLETE", "SHIPPED",
)

PRICE_LOCK_BREAK_STATUSES = ("ACKNOWLEDGED", "SCHEDULED", "IN_PRODUCTION", "MFG_COMPLETE")


# ---- line / family resolution ----

def get_active_line(program_id):
    for line in store.lines.values():
        if line["program_id"] == program_id and line["status"] == "ACTIVE":
            return line
    return None


def family_map(line):
    return {f["family_code"]: f for f in line["families"]}


def priced_line_for(order):
    """The ProgramLine the order was priced against (submit / reprice / invoice)."""
    line_id = store.order_priced_line.get(order["id"])
    if line_id and line_id in store.lines:
        return store.lines[line_id]
    return get_active_line(order["program_id"])


# ---- order_pricing (scaffold 1.3, PRD 3.3) ----

def price_against_line(account, program, line, items):
    """Pinned tiered pricing. items: [{family_code, quantity}].

    Step order (pinned): per-unit channel price rounded half-up; gross from those
    units selects the tier; per-unit tier discount rounded half-up; per-unit
    program discount rounded half-up; multiply by qty; sum per-line totals.
    Returns (total_cents, [unit_net_cents per item])."""
    fmap = family_map(line)
    multiplier = CHANNEL_MULTIPLIERS[account["pricing_class"]]
    unit_channels = []
    gross = 0
    for item in items:
        fam = fmap.get(item["family_code"])
        if fam is None:
            raise api_error(
                "ERR_LINE_NOT_COVERED",
                "family_code {} is not covered by the program's ACTIVE line".format(
                    item["family_code"]))
        unit_channel = round_half_up_cents(Decimal(str(fam["standard_price_cents"])) * multiplier)
        unit_channels.append(unit_channel)
        gross += unit_channel * int(item["quantity"])
    if gross >= TIER2_GROSS_CENTS:
        tier = TIER2_PCT
    elif gross >= TIER1_GROSS_CENTS:
        tier = TIER1_PCT
    else:
        tier = Decimal("0")
    program_discount = Decimal(str(program["program_discount_pct"]))
    unit_nets = []
    total = 0
    for item, unit_channel in zip(items, unit_channels):
        tiered = round_half_up_cents(Decimal(unit_channel) * (Decimal("1") - tier))
        unit_net = round_half_up_cents(Decimal(tiered) * (Decimal("1") - program_discount))
        unit_nets.append(unit_net)
        total += unit_net * int(item["quantity"])
    return total, unit_nets


def price_items(account, program, items):
    """Price against the program's CURRENT ACTIVE line. Returns (total, unit_nets, line)."""
    line = get_active_line(program["id"])
    if line is None:
        raise api_error("ERR_NO_ACTIVE_LINE", "program has no ACTIVE line to price against")
    total, unit_nets = price_against_line(account, program, line, items)
    return total, unit_nets, line


# ---- delivery_week_estimation ----

def base_lead_extremes(line, family_codes):
    fmap = family_map(line)
    leads = [fmap[fc]["base_lead_weeks"] for fc in family_codes if fc in fmap]
    if not leads:
        return 0, 0
    return min(leads), max(leads)


def promised_delivery_week(account, max_lead):
    """channel_table variant: submit week + effective lead (PRD 3.3)."""
    extra = EXTENDED_CLASS_EXTRA_WEEKS if account["lead_time_class"] == "EXTENDED" else 0
    return add_weeks(week_of(store.clock), max_lead + extra)


# ---- order creation shared by POST /orders and design-job convert ----

def create_order_entity(account, program, lines, destination_type, store_code,
                        jobsite_address, requested_week, design_job_id):
    """lines: [{family_code, finish_code, quantity}]. Computes quoted pricing,
    promised week, per-line units; stores the order and returns a snapshot."""
    items = [{"family_code": li["family_code"], "quantity": li["quantity"]} for li in lines]
    total, unit_nets, priced_line = price_items(account, program, items)
    fmap = family_map(priced_line)
    _, max_lead = base_lead_extremes(priced_line, [i["family_code"] for i in items])
    order = new_entity()
    order_lines = []
    for src, unit_net in zip(lines, unit_nets):
        fam = fmap[src["family_code"]]
        order_lines.append({
            "family_code": src["family_code"],
            "finish_code": src["finish_code"],
            "quantity": src["quantity"],
            "unit_quoted_cents": unit_net,
            "unit_invoiced_cents": None,
            "finish_batch_id": None,
            "units": src["quantity"] * fam["complexity_units_per_cabinet"],
        })
    order.update({
        "account_id": account["id"],
        "program_id": program["id"],
        "design_job_id": design_job_id,
        "destination_type": destination_type,
        "store_code": store_code,
        "jobsite_address": jobsite_address,
        "requested_delivery_week": requested_week,
        "lines": order_lines,
        "status": "SUBMITTED",
        "payment_status": "UNINVOICED",
        "promised_delivery_week": promised_delivery_week(account, max_lead),
        "scheduled_week": None,
        "scheduled_delivery_week": None,
        "quoted_total_cents": total,
        "invoiced_total_cents": None,
        "price_lock": False,
        "repricing_required": False,
    })
    store.orders[order["id"]] = order
    store.order_priced_line[order["id"]] = priced_line["id"]
    return dict(order)


# ---- credit_exposure (PRD 2.8) ----

def recompute_credit(account_id):
    """Recompute open_exposure_cents (an Account mutation), then run the
    symmetric release of PRD 2.8: whenever a recompute finds the exposure at or
    below the limit, every order of that account sitting in CREDIT_HOLD flips
    back to UNINVOICED.

    Hold ENTRY is not a sweep: PRD 3.4 attaches CREDIT_HOLD to the order being
    acknowledged ("the order's payment_status becomes CREDIT_HOLD") when its
    inclusion pushes exposure strictly above the limit — see the ACKNOWLEDGED
    branch in routes_orders. Recomputes triggered by creation, cancellation,
    invoicing, payment, supersede repricing, or unsuspension only release."""
    account = store.accounts.get(account_id)
    if account is None:
        return
    exposure = 0
    for order in store.orders.values():
        if order["account_id"] != account_id or order["status"] == "CANCELLED":
            continue
        payment = order["payment_status"]
        if payment in ("UNINVOICED", "CREDIT_HOLD"):
            exposure += order.get("quoted_total_cents") or 0
        elif payment == "INVOICED":
            exposure += order.get("invoiced_total_cents") or 0
    account["open_exposure_cents"] = exposure
    bump(account)
    limit = account["credit_limit_cents"]
    for order in store.orders.values():
        if order["account_id"] != account_id or order["status"] == "CANCELLED":
            continue
        if order["payment_status"] == "CREDIT_HOLD" and exposure <= limit:
            order["payment_status"] = "UNINVOICED"
            bump(order)


# ---- capacity_slot_selection ----

def _slot_rank(slot):
    """week ASC, then plant_code ASC, then created_at ASC (never id)."""
    return (parse_week(slot["week"]), slot["plant_code"], slot["created_at"])


def select_slots_strict(family_demands, requested_week):
    """Strict variant (order scheduling). family_demands: {family_code: (needed, base_lead)}.
    Primary window [current_week, requested_week - base_lead]; slip window of up to
    MAX_SLIP_WEEKS beyond it; OPEN only; no overbook. All-or-nothing: raises
    ERR_NO_CAPACITY when any family finds no slot."""
    current = parse_week(week_of(store.clock))
    picks = {}
    for fam, (needed, base_lead) in family_demands.items():
        primary_end = parse_week(add_weeks(requested_week, -base_lead))
        slip_start = parse_week(add_weeks(requested_week, -base_lead + 1))
        slip_end = parse_week(add_weeks(requested_week, -base_lead + MAX_SLIP_WEEKS))

        def eligible(slot, lo, hi, fam=fam, needed=needed):
            week = parse_week(slot["week"])
            return (slot["family_code"] == fam
                    and slot["status"] == "OPEN"
                    and week >= current
                    and lo <= week <= hi
                    and slot["committed_units"] + needed <= slot["capacity_units"])

        candidates = [s for s in store.slots.values() if eligible(s, current, primary_end)]
        if not candidates:
            candidates = [s for s in store.slots.values() if eligible(s, slip_start, slip_end)]
        if not candidates:
            raise api_error("ERR_NO_CAPACITY",
                            "no eligible production slot for family {}".format(fam))
        candidates.sort(key=_slot_rank)
        picks[fam] = candidates[0]
    return picks


def select_slot_expedite(family_code, needed):
    """Expedite variant (replacement scheduling): window [current week, +1];
    OPEN or LOCKED; overbook up to floor(capacity * 0.10)."""
    current = parse_week(week_of(store.clock))
    end = parse_week(add_weeks(week_of(store.clock), 1))
    candidates = []
    for slot in store.slots.values():
        week = parse_week(slot["week"])
        if slot["family_code"] != family_code:
            continue
        if slot["status"] not in ("OPEN", "LOCKED"):
            continue
        if not (current <= week <= end):
            continue
        overbook = slot["capacity_units"] // EXPEDITE_OVERBOOK_DIVISOR
        if slot["committed_units"] + needed > slot["capacity_units"] + overbook:
            continue
        candidates.append(slot)
    if not candidates:
        raise api_error("ERR_NO_CAPACITY",
                        "no eligible expedite slot for family {}".format(family_code))
    candidates.sort(key=_slot_rank)
    return candidates[0]


def commit_slot(slot, units):
    slot["committed_units"] += units
    bump(slot)
    if slot["status"] == "OPEN" and slot["committed_units"] == slot["capacity_units"]:
        slot["status"] = "LOCKED"
        bump(slot)


def release_slot(slot, units):
    slot["committed_units"] -= units
    bump(slot)
    if slot["status"] == "LOCKED" and slot["committed_units"] < slot["capacity_units"]:
        slot["status"] = "OPEN"
        bump(slot)


# ---- color_match_delta_e ----

def color_delta_e(batch_a, batch_b):
    if batch_a["id"] == batch_b["id"]:
        return 0.0
    return math.sqrt(
        (float(batch_a["lab_l"]) - float(batch_b["lab_l"])) ** 2
        + (float(batch_a["lab_a"]) - float(batch_b["lab_a"])) ** 2
        + (float(batch_a["lab_b"]) - float(batch_b["lab_b"])) ** 2
    )


def check_color_match(new_batch, original_batch):
    """PASS iff deltaE <= 2.0 inclusive; identical batch passes trivially."""
    delta = color_delta_e(new_batch, original_batch)
    if delta > COLOR_MATCH_TOLERANCE:
        raise api_error("ERR_COLOR_MISMATCH",
                        "deltaE {:.6f} exceeds tolerance 2.0".format(delta))


def current_batch_for(finish_code):
    for batch in store.batches.values():
        if batch["finish_code"] == finish_code and batch["status"] == "CURRENT":
            return batch
    return None


# ---- damage_settlement (PRD 3.6) ----

def compute_settlement(claim):
    order = store.orders[claim["order_id"]]
    line_item = order["lines"][claim["line_index"]]
    unit = line_item.get("unit_invoiced_cents")
    if unit is None:
        unit = line_item.get("unit_quoted_cents") or 0
    standard_price = None
    candidates = []
    priced = priced_line_for(order)
    if priced is not None:
        candidates.append(priced)
    active = get_active_line(order["program_id"])
    if active is not None and all(active["id"] != c["id"] for c in candidates):
        candidates.append(active)
    for line in store.lines.values():
        if line["program_id"] == order["program_id"] and all(line["id"] != c["id"] for c in candidates):
            candidates.append(line)
    for line in candidates:
        fam = family_map(line).get(line_item["family_code"])
        if fam is not None:
            standard_price = fam["standard_price_cents"]
            break
    if standard_price is None:
        raise api_error("ERR_LINE_NOT_COVERED", "family no longer resolvable for settlement")
    qty = int(claim["claimed_qty"])
    base = min(
        qty * unit,
        round_half_up_cents(Decimal(qty) * Decimal(str(standard_price)) * SETTLEMENT_CAP_MULT),
    )
    shipment = store.shipments[claim["shipment_id"]]
    delivered = parse_dt(shipment["delivered_at"])
    age_days = int((store.clock - delivered).total_seconds() // 86400)
    factor = Decimal("1.0") if age_days <= EARLY_FULL_DAYS else LATE_FACTOR
    return round_half_up_cents(Decimal(base) * factor)


# ---- program transition: supersede cascade + auto retirement (PRD 3.7) ----

def supersede_cascade(program, old_line, new_line, disposition_qty):
    """ACTIVE program supersede: program -> TRANSITIONING with deadlines; old line
    -> SUNSETTING with disposition initialized; SUBMITTED orders repriced against
    the NEW line; in-flight price locks broken; RETAIL display resets created."""
    now = store.clock
    program["status"] = "TRANSITIONING"
    program["transition_started_at"] = iso3(now)
    program["display_reset_deadline"] = iso3(now + timedelta(days=RESET_DEADLINE_DAYS))
    program["disposition_deadline"] = iso3(now + timedelta(days=DISPOSITION_DEADLINE_DAYS))

    old_line["status"] = "SUNSETTING"
    old_line["original_disposition_qty"] = disposition_qty
    old_line["remaining_disposition_qty"] = disposition_qty
    bump(old_line)

    affected_accounts = set()
    for order in store.orders.values():
        if order["program_id"] != program["id"] or order["status"] != "SUBMITTED":
            continue
        account = store.accounts[order["account_id"]]
        items = [{"family_code": li["family_code"], "quantity": li["quantity"]}
                 for li in order["lines"]]
        total, unit_nets = price_against_line(account, program, new_line, items)
        order["quoted_total_cents"] = total
        for li, unit_net in zip(order["lines"], unit_nets):
            li["unit_quoted_cents"] = unit_net
        order["repricing_required"] = True
        store.order_priced_line[order["id"]] = new_line["id"]
        bump(order)
        affected_accounts.add(order["account_id"])
    for account_id in affected_accounts:
        recompute_credit(account_id)

    for order in store.orders.values():
        if (order["program_id"] == program["id"]
                and order["status"] in PRICE_LOCK_BREAK_STATUSES
                and order["payment_status"] in ("UNINVOICED", "CREDIT_HOLD")):
            order["price_lock"] = False
            bump(order)

    account = store.accounts[program["account_id"]]
    if account["channel"] == "RETAIL":
        for store_code in account["store_codes"]:
            reset = new_entity()
            reset.update({
                "program_id": program["id"],
                "line_id": old_line["id"],
                "store_code": store_code,
                "status": "PLANNED",
                "scheduled_date": None,
                "completed_at": None,
                "completed_late": False,
            })
            store.resets[reset["id"]] = reset


def maybe_retire_line(line):
    """Auto ProgramLine SUNSETTING -> RETIRED once remaining_disposition_qty == 0
    and every DisplayReset of the line is COMPLETE or WAIVED; then, when it was the
    program's last SUNSETTING line, auto Program TRANSITIONING -> ACTIVE."""
    if line["status"] != "SUNSETTING":
        return
    if line["remaining_disposition_qty"] != 0:
        return
    for reset in store.resets.values():
        if reset["line_id"] == line["id"] and reset["status"] not in ("COMPLETE", "WAIVED"):
            return
    line["status"] = "RETIRED"
    bump(line)
    program = store.programs[line["program_id"]]
    if program["status"] != "TRANSITIONING":
        return
    for other in store.lines.values():
        if other["program_id"] == program["id"] and other["status"] == "SUNSETTING":
            return
    program["status"] = "ACTIVE"
    program["transition_started_at"] = None
    program["display_reset_deadline"] = None
    program["disposition_deadline"] = None
    bump(program)
