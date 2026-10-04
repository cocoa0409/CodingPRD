"""Shared service primitives: row CRUD, derived recomputation, lookups.

Nothing here seeds state.  Every function either reads the store or mutates it
in response to a request; a freshly booted process has empty collections.
"""

from db import DB, R, add_days, add_months, iso, parse_dt
from errors import (ApiError, Err, already_terminal, invalid_state,
                    referenced)
from services import calc

TERMINAL_STATUSES = ("SHIPPED", "CANCELLED", "EXCHANGED", "DENIED",
                     "RESOLVED", "VOIDED", "CLOSED")

WARRANTY_IN_FORCE = ("ACTIVE", "CLAIM_OPEN", "REPAIR_IN_PROGRESS")


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------

def new_row(collection, **fields):
    """Create a row carrying the universal field set plus its own fields."""
    now = DB.now()
    row = {
        "id": DB.new_id(),
        "created_at": iso(now),
        "updated_at": iso(now),
        "version": 1,
        "_seq": DB.next_seq(),
    }
    row.update(fields)
    return DB.add(collection, row)


def touch(row):
    """Refresh updated_at on every mutation (PRD §2.8)."""
    row["updated_at"] = iso(DB.now())
    return row


def bump(row):
    """Refresh updated_at and increment version, where the rules assign it."""
    row["version"] = int(row.get("version") or 1) + 1
    row["updated_at"] = iso(DB.now())
    return row


def public(row):
    """Serialize a row: private bookkeeping keys are never exposed."""
    if row is None:
        return None
    return {key: value for key, value in row.items() if not key.startswith("_")}


def public_list(rows):
    return [public(row) for row in rows]


def all_rows(collection):
    rows = DB.all(collection)
    rows.sort(key=lambda row: (row.get("_seq") or 0))
    return rows


def fetch(collection, ident, error_id):
    row = DB.get(collection, ident)
    if row is None:
        raise ApiError(error_id)
    return row


def require_state(row, allowed, field="status"):
    """Priority 5 (409) then priority 22 (409) for terminal rows."""
    current = row.get(field)
    if current in TERMINAL_STATUSES:
        raise already_terminal("%s is already %s." % (field, current))
    if current not in allowed:
        raise invalid_state("%s is %s, not one of %s." % (field, current,
                                                          list(allowed)))
    return row


def lookup(collection, **filters):
    for row in DB.all(collection):
        if all(row.get(key) == value for key, value in filters.items()):
            return row
    return None


def referenced_or_404(row, what):
    if row is None:
        raise referenced("The referenced %s does not exist." % what)
    return row


# ---------------------------------------------------------------------------
# Assignment / Customer / Engineer derived state
# ---------------------------------------------------------------------------

def assignments_for_customer(customer_id):
    return [a for a in DB.all("assignments") if a["customer_id"] == customer_id]


def active_assignment(customer_id):
    rows = [a for a in assignments_for_customer(customer_id)
            if a["status"] == "ACTIVE"]
    return rows[0] if rows else None


def assignments_for_engineer(engineer_id):
    return [a for a in DB.all("assignments") if a["engineer_id"] == engineer_id]


def recompute_active_book_size(engineer_id):
    engineer = DB.get("engineers", engineer_id)
    if engineer is None:
        return
    count = len([a for a in assignments_for_engineer(engineer_id)
                 if a["status"] == "ACTIVE"])
    engineer["active_book_size"] = count
    touch(engineer)


def recompute_customer_mirror(customer_id):
    """assigned_engineer_id mirrors the engineer of the ACTIVE assignment."""
    customer = DB.get("customers", customer_id)
    if customer is None:
        return
    holder = active_assignment(customer_id)
    customer["assigned_engineer_id"] = holder["engineer_id"] if holder else None
    touch(customer)


def has_warranty_in_force(customer_id):
    return any(plan["customer_id"] == customer_id and plan["status"] in WARRANTY_IN_FORCE
               for plan in DB.all("warranty_plans"))


def recompute_entitlement(customer_id):
    """calculations.customer_tech_support_entitlement (PRD §3.7)."""
    customer = DB.get("customers", customer_id)
    if customer is None:
        return
    customer["tech_support_entitlement"] = calc.customer_tech_support_entitlement(
        has_active_assignment=active_assignment(customer_id) is not None,
        has_warranty_in_force=has_warranty_in_force(customer_id),
        purchased_instrument_count=int(customer.get("purchased_instrument_count") or 0),
    )
    touch(customer)


def _count_purchased_lines(customer_id):
    """QuoteLine rows of this customer's quotes whose instrument has shipped.

    PRD §2.8: "`purchased_instrument_count` on a customer counts the sold lines
    tied to that customer's quotes."  A line is *sold* once its serialized
    instrument has shipped (PRD §3.4 recomputes the count at shipment), so the
    count is over shipped units rather than over quote status.
    """
    count = 0
    for line in DB.all("quote_lines"):
        quote = DB.get("quotes", line["quote_id"])
        if quote is not None and quote["customer_id"] == customer_id \
                and line_is_shipped(line):
            count += 1
    return count


def recompute_purchased_instrument_count(customer_id):
    """Recompute the customer's purchased instrument count (PRD §2.8)."""
    customer = DB.get("customers", customer_id)
    if customer is None:
        return
    customer["purchased_instrument_count"] = _count_purchased_lines(customer_id)
    touch(customer)
    recompute_entitlement(customer_id)


def recompute_certified_family_count(engineer_id):
    """Distinct families among attempts marked certified and still in validity."""
    engineer = DB.get("engineers", engineer_id)
    if engineer is None:
        return
    now = iso(DB.now())
    families = set()
    for attempt in DB.all("certification_attempts"):
        if attempt["engineer_id"] != engineer_id or not attempt.get("certified"):
            continue
        expires_at = attempt.get("expires_at")
        if expires_at and expires_at <= now:
            continue
        families.add(attempt["product_family"])
    engineer["certified_family_count"] = len(families)
    touch(engineer)
    recompute_seniority(engineer_id)


def recompute_seniority(engineer_id):
    """engineer_seniority_tier: tier and commission cap together (PRD §3.9)."""
    engineer = DB.get("engineers", engineer_id)
    if engineer is None:
        return
    tier, cap = calc.engineer_seniority_tier(int(engineer.get("certified_family_count") or 0))
    engineer["seniority_tier"] = tier
    engineer["commission_cap_bps"] = cap
    touch(engineer)


def recompute_lifetime_commission(engineer_id):
    """Sum of finalized commission across this engineer's RESERVED, fully
    shipped quotes (PRD §3.3)."""
    engineer = DB.get("engineers", engineer_id)
    if engineer is None:
        return
    total = 0
    for quote in DB.all("quotes"):
        if quote["engineer_id"] != engineer_id:
            continue
        if quote["status"] != "RESERVED":
            continue
        lines = quote_lines(quote["id"])
        if not lines or not all(line_is_shipped(line) for line in lines):
            continue
        commission = quote_final_commission(quote, lines)
        if commission is None:
            continue
        total += commission
    engineer["lifetime_commission_cents"] = total
    touch(engineer)


# ---------------------------------------------------------------------------
# Coverage windows (§2.4)
# ---------------------------------------------------------------------------

def covered_overlap(customer_id, proposed_start, exclude_id=None):
    """True when [proposed_start, null) overlaps the half-open [assigned_at,
    ended_at) of an ENDED assignment on this book.

    Adjacency at an identical instant is permitted, so the comparison is
    strictly ``proposed_start < ended_at`` (PRD §2.4).  ``exclude_id`` skips the
    row being reopened, whose own ended interval would otherwise match itself.
    """
    for other in assignments_for_customer(customer_id):
        if other["id"] == exclude_id:
            continue
        if other["status"] != "ENDED":
            continue
        ended_at = parse_dt(other.get("_ended_at"))
        started_at = parse_dt(other.get("assigned_at"))
        if ended_at is None or started_at is None:
            continue
        if proposed_start < ended_at:
            return True
    return False


def end_assignment_row(assignment, now):
    assignment["status"] = "ENDED"
    assignment["_ended_at"] = iso(now)
    touch(assignment)


# ---------------------------------------------------------------------------
# Quote derived state
# ---------------------------------------------------------------------------

def quote_lines(quote_id):
    rows = [line for line in DB.all("quote_lines") if line["quote_id"] == quote_id]
    rows.sort(key=lambda row: row.get("_seq") or 0)
    return rows


def line_is_shipped(line):
    for unit in DB.all("instrument_units"):
        if unit["quote_line_id"] == line["id"] and unit["setup_status"] == "SHIPPED":
            return True
    return False


def recompute_quote_derived(quote):
    """gross_subtotal_cents, dependency_closure_size, bundle_ready (PRD §2.9)."""
    lines = quote_lines(quote["id"])
    quote["gross_subtotal_cents"] = sum(int(line["line_total_cents"]) for line in lines)
    quote["dependency_closure_size"] = calc.dependency_closure_size(lines)
    quote["bundle_ready"] = calc.bundle_ready(lines)
    touch(quote)
    return quote


def quote_final_commission(quote, lines=None):
    """Final variant of engineer_commission_cents against shipped line value."""
    lines = quote_lines(quote["id"]) if lines is None else lines
    gross = int(quote.get("gross_subtotal_cents") or 0)
    shipped_value = sum(int(line["line_total_cents"]) for line in lines
                        if line_is_shipped(line))
    assignment = active_assignment(quote["customer_id"])
    share_bps = _share_bps_for(quote, assignment)
    if share_bps is None:
        return None
    return calc.engineer_commission_cents(quote, gross, shipped_value, share_bps, "final")


def _share_bps_for(quote, assignment):
    """min(assignment.commission_share_bps, engineer.commission_cap_bps)."""
    engineer = DB.get("engineers", quote["engineer_id"])
    if engineer is None:
        return None
    requested = assignment["commission_share_bps"] if assignment is not None else 5000
    cap = int(engineer.get("commission_cap_bps") or 5000)
    return min(int(requested), cap)


def refresh_purchased_count(customer_id):
    """Recompute the customer's purchased_instrument_count unconditionally.

    The count sums QuoteLine rows of this customer's quotes whose instrument has
    shipped, so a shipment -- or a line being attached to a quote that has
    already shipped -- must refresh it (PRD §2.8).
    """
    recompute_purchased_instrument_count(customer_id)


def quote_provisional_commission(quote):
    lines = quote_lines(quote["id"])
    gross = int(quote.get("gross_subtotal_cents") or 0)
    assignment = active_assignment(quote["customer_id"])
    share_bps = _share_bps_for(quote, assignment)
    if share_bps is None:
        return 0
    return calc.engineer_commission_cents(quote, gross, 0, share_bps, "provisional")


def quote_commission_state(quote):
    """(cents, variant) currently stored for the summary read."""
    lines = quote_lines(quote["id"])
    if lines and all(line_is_shipped(line) for line in lines):
        final = quote_final_commission(quote, lines)
        if final is not None:
            return final, "final"
    stored = quote.get("_commission_cents")
    if stored is not None:
        return stored, quote.get("_commission_variant") or "provisional"
    return 0, None


# ---------------------------------------------------------------------------
# ServiceCenter slot ledger
# ---------------------------------------------------------------------------

def adjust_open_tickets(service_center_id, delta):
    """The slot ledger shared by claim routing and ticket escalation (§3.7)."""
    center = DB.get("service_centers", service_center_id)
    if center is None:
        return
    center["open_ticket_count"] = max(0, int(center.get("open_ticket_count") or 0) + delta)
    touch(center)


def has_free_slot(center):
    return int(center.get("open_ticket_count") or 0) < int(center.get("capacity_slots") or 0)


# ---------------------------------------------------------------------------
# Warranty
# ---------------------------------------------------------------------------

def claims_for_plan(plan_id):
    return [claim for claim in DB.all("warranty_claims")
            if claim["warranty_plan_id"] == plan_id]


def recompute_repair_rounds(plan):
    plan["remaining_repair_rounds"] = max(
        0, calc.MAX_REPAIR_ROUNDS - int(plan.get("repair_rounds_used") or 0))
    touch(plan)


def plan_product_family(plan):
    """The family of the covered instrument, read through its shipped line."""
    unit = DB.get("instrument_units", plan.get("instrument_unit_id"))
    if unit is None:
        return None
    line = DB.get("quote_lines", unit.get("quote_line_id"))
    if line is None:
        return None
    return line.get("product_family")


# ---------------------------------------------------------------------------
# Support tickets
# ---------------------------------------------------------------------------

def recompute_escalation_count(ticket):
    count = len([row for row in DB.all("escalation_ledger")
                 if row["support_ticket_id"] == ticket["id"]
                 and row["event_type"] == "SERVICE_DEPARTMENT_ESCALATION"])
    ticket["escalation_count"] = count
    touch(ticket)


def next_escalation_seq(ticket_id):
    highest = 0
    for row in DB.all("escalation_ledger"):
        if row["support_ticket_id"] == ticket_id:
            highest = max(highest, int(row.get("escalation_seq") or 0))
    return highest + 1


def append_ledger(ticket, service_center_id, event_type):
    seq = next_escalation_seq(ticket["id"])
    row = new_row(
        "escalation_ledger",
        support_ticket_id=ticket["id"],
        service_center_id=service_center_id,
        event_type=event_type,
        escalation_seq=seq,
        posted_at=iso(DB.now()),
    )
    return row


def recompute_required_entitlement(ticket):
    """EXTENDED when the customer holds a warranty in force, else BASIC."""
    ticket["required_entitlement"] = "EXTENDED" \
        if has_warranty_in_force(ticket["customer_id"]) else "BASIC"
    touch(ticket)


# ---------------------------------------------------------------------------
# Backorders
# ---------------------------------------------------------------------------

def recompute_backorder_deadline(backorder):
    opened = parse_dt(backorder.get("preorder_open_at"))
    if opened is not None:
        backorder["eta_deadline"] = iso(add_days(opened, calc.BACKORDER_WINDOW_DAYS))
    touch(backorder)


def allocation_siblings(backorder):
    """Eligible set for the waterfall: same product, status in the sweep set."""
    line = DB.get("quote_lines", backorder["quote_line_id"])
    if line is None:
        return [backorder]
    eligible = []
    for other in DB.all("backorders"):
        if other["status"] not in ("ALLOCATION_SWEEP", "PARTIALLY_FILLED",
                                   "BOARD_FILLED"):
            continue
        other_line = DB.get("quote_lines", other["quote_line_id"])
        if other_line is None:
            continue
        if other_line.get("product_id") == line.get("product_id"):
            eligible.append(other)
    if backorder not in eligible:
        eligible.append(backorder)
    return eligible


# ---------------------------------------------------------------------------
# Gear exchanges
# ---------------------------------------------------------------------------

def exchange_line_total(exchange):
    line = DB.get("quote_lines", exchange["quote_line_id"])
    return int(line["line_total_cents"]) if line is not None else 0


def exchange_account_tier(exchange):
    customer = DB.get("customers", exchange["customer_id"])
    return customer.get("account_tier") if customer is not None else "STANDARD"


def exchange_days_remaining(exchange):
    end = parse_dt(exchange.get("trial_end_date"))
    if end is None:
        return 0
    return calc.days_remaining(end, DB.now())


def compute_restocking_fee(exchange, variant):
    total = exchange_line_total(exchange)
    bps = calc.restocking_fee_bps(exchange["reason"], exchange_account_tier(exchange),
                                  exchange_days_remaining(exchange)) \
        if variant == "final" else calc.REASON_BPS.get(exchange["reason"], 0)
    exchange["restocking_fee_bps"] = bps
    exchange["restocking_fee_cents"] = calc.gear_exchange_restocking_fee(
        total, exchange["reason"], exchange_account_tier(exchange),
        exchange_days_remaining(exchange), variant)
    if variant == "final":
        exchange["refund_credit_cents"] = total - exchange["restocking_fee_cents"]
    touch(exchange)


# ---------------------------------------------------------------------------
# Certifications
# ---------------------------------------------------------------------------

def prior_attempt_count(engineer_id, product_family, exclude_id=None):
    count = 0
    for attempt in DB.all("certification_attempts"):
        if attempt["id"] == exclude_id:
            continue
        if attempt["engineer_id"] == engineer_id \
                and attempt["product_family"] == product_family:
            count += 1
    return count


def recompute_attempt_index(attempt):
    attempt["attempt_index"] = 1 + prior_attempt_count(
        attempt["engineer_id"], attempt["product_family"], attempt["id"])
    attempt["eligible_to_retake"] = int(attempt["attempt_index"]) < 3
    touch(attempt)


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------

def blend_measurements(unit, action_height_mm, relief_mm, intonation_offset_cents):
    unit["action_height_mm"] = action_height_mm
    unit["relief_mm"] = relief_mm
    unit["intonation_offset_cents"] = intonation_offset_cents


def recompute_inspection_verdict(unit, variant):
    unit["inspection_overall"] = calc.instrument_inspection_verdict(
        unit["action_height_mm"], unit["relief_mm"],
        unit["intonation_offset_cents"], variant)
    touch(unit)


def unit_quote(unit):
    line = DB.get("quote_lines", unit.get("quote_line_id"))
    if line is None:
        return None, None
    return line, DB.get("quotes", line["quote_id"])


def add_months_from(instant, months):
    return add_months(instant, months)