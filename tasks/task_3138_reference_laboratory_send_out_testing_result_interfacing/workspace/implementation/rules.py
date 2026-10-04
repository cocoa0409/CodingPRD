"""Calculation rules, derived-field reconciliation and cascade helpers.

Every rule here traces to a sentence in PRD section 2 or section 3 (and its
structured twin SCAFFOLD section 1.3). Money is Decimal throughout; the caching
of derived values on the row is presentation only, never a stored truth.
"""

import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_DOWN

import db
from db import parse_dt, iso, hours_between

# ---------------------------------------------------------------------------
# constants pinned by SCAFFOLD section 1.3
# ---------------------------------------------------------------------------

TIER_RATE_THROUGH_2 = Decimal("1.00")
TIER_RATE_3_TO_5 = Decimal("0.85")
TIER_RATE_6_PLUS = Decimal("0.72")

TIER_TAT_FACTOR = {
    "STANDARD": Decimal("1.0"),
    "RUSH": Decimal("0.5"),
    "CRITICAL": Decimal("0.25"),
}
TIER_SURCHARGE_RATE = {
    "STANDARD": Decimal("0.00"),
    "RUSH": Decimal("0.15"),
    "CRITICAL": Decimal("0.40"),
}
RUSH_TAT_THRESHOLD_HOURS = Decimal("24")
CEILING_MULTIPLIER = Decimal("4")
LATE_CREDIT_RATE_PER_HOUR = Decimal("0.015")

BASE_RETRY_MINUTES = 5
MAX_RETRY_MINUTES = 60
RETRY_COUNT_LIMIT = 5

UTILIZATION_BAND_PER_MONTH = 4
WINDOW_DAYS = 30

CENT = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")

# line_status values that make a line "live" for TAT and reportable-count purposes
REPORTABLE_LINE_STATES = frozenset(
    {"PENDING", "IN_PROGRESS", "INTERIM", "FINAL", "REPEAT_REQUIRED"}
)
# PRD section 3.6: rows in {PENDING, IN_PROGRESS, INTERIM} contribute base_tat_hours
LIVE_TAT_LINE_STATES = frozenset({"PENDING", "IN_PROGRESS", "INTERIM"})

# interface_status ranking, highest wins (PRD section 3.1)
INTERFACE_BUILD_RANK = {
    "NOT_BUILT": 0,
    "IN_BUILD": 1,
    "CERTIFIED": 2,
    "SUPERSEDED": 2,
    "RETIRED": 3,
    "DRAFT": 0,
}


def dec(value):
    """Decimal from an int/float/Decimal/str without a float round-trip loss."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def round_half_up(value, places=2):
    """Money rounding: exactly two decimal places, round-half-up."""
    quant = CENT if places == 2 else Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def num(value):
    """Present a Decimal as a JSON number; ints stay ints."""
    if value is None:
        return None
    d = dec(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d.normalize())


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------

def catalog_entry_of(line):
    return db.get("test_catalog_entries", line.get("test_catalog_entry_id"))


def order_of_line(line):
    return db.get("send_out_orders", line.get("send_out_order_id"))


def lines_of_order(order_id):
    rows = [l for l in db.all_rows("order_test_lines") if l["send_out_order_id"] == order_id]
    return sorted(rows, key=lambda l: (l.get("line_sequence") or 0, l.get("created_at") or ""))


def live_lines_of_order(order_id):
    """The order's lines that count toward TAT, pricing and utilisation."""
    return [l for l in lines_of_order(order_id) if l.get("line_status") in REPORTABLE_LINE_STATES]


def orders_of_specimen(specimen_id):
    """Every requisitioning order that references this specimen.

    A specimen may legitimately carry more than one order (a reflex order is
    spawned against the same specimen, and a client may requisition twice), so
    specimen-level bubbles must reach all of them rather than assuming one.
    """
    rows = [
        o for o in db.all_rows("send_out_orders") if o.get("specimen_id") == specimen_id
    ]
    rows.sort(key=lambda o: (o.get("created_at") or "", o["id"]))
    return rows


def order_of_specimen(specimen_id):
    """The earliest requisitioning order that references this specimen."""
    rows = orders_of_specimen(specimen_id)
    return rows[0] if rows else None


def lines_of_specimen(specimen_id):
    rows = [
        l
        for l in db.all_rows("order_test_lines")
        if (order_of_line(l) or {}).get("specimen_id") == specimen_id
        and l.get("line_status") != "CANCELLED"
    ]
    return rows


def ordered_catalog_entries_of_specimen(specimen_id):
    """Catalog entries ordered against a specimen.

    A derived aliquot tube carries no order lines of its own, so it inherits its
    parent specimen's test set — the same way it inherits the parent's condition
    and transport temperature — which is what makes the child's remaining
    stability well defined.
    """
    seen = {}
    for line in lines_of_specimen(specimen_id):
        entry = catalog_entry_of(line)
        if entry is not None:
            seen[entry["id"]] = entry
    if seen:
        return list(seen.values())
    specimen = db.get("specimens", specimen_id)
    parent_id = (specimen or {}).get("aliquot_parent_id")
    if parent_id and parent_id != specimen_id:
        return ordered_catalog_entries_of_specimen(parent_id)
    return []


def orders_of_client(client_id):
    return [
        o for o in db.all_rows("send_out_orders") if o.get("client_laboratory_id") == client_id
    ]


def lines_of_client(client_id):
    order_ids = {o["id"] for o in orders_of_client(client_id)}
    return [
        l for l in db.all_rows("order_test_lines") if l.get("send_out_order_id") in order_ids
    ]


# ---------------------------------------------------------------------------
# specimen stability (PRD section 2.5 / 3.3)
# ---------------------------------------------------------------------------

def binding_window_hours(specimen):
    """MIN stability window over every catalog entry ordered against the specimen."""
    temperature = specimen.get("transport_temperature")
    field = {
        "AMBIENT": "stability_hours_ambient",
        "REFRIGERATED": "stability_hours_refrigerated",
        "FROZEN": "stability_hours_frozen",
    }.get(temperature)
    entries = ordered_catalog_entries_of_specimen(specimen["id"])
    windows = []
    for entry in entries:
        if field is None:
            continue
        raw = entry.get(field)
        if raw is not None:
            windows.append(dec(raw))
    if not windows:
        return None
    return min(windows)


def remaining_stability_hours(specimen):
    """binding_window_hours - elapsed hours at the logical clock.

    Never stored, never clamped: the value may legitimately be negative. It is
    computed to four decimal places and rounded half-down.
    """
    window = binding_window_hours(specimen)
    if window is None:
        # A specimen with no ordered test has no binding window to draw down, and
        # the field the PRD describes is always a number: it "is derived on every
        # read ... it may legitimately be negative". Report zero rather than a
        # null so every read of a Specimen carries a numeric value.
        return Decimal("0")
    collected = parse_dt(specimen.get("collection_at"))
    if collected is None:
        return None
    elapsed = dec(hours_between(collected, db.now()))
    value = (window - elapsed).quantize(FOUR_PLACES, rounding=ROUND_HALF_DOWN)
    return value


def total_aliquot_volume_ml(specimen):
    total = Decimal("0")
    for child in db.all_rows("specimens"):
        if child.get("aliquot_parent_id") == specimen["id"]:
            total += dec(child.get("aliquot_volume_ml"))
    return total.quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# result flagging (PRD section 3.7)
# ---------------------------------------------------------------------------

def compute_result_flag(line):
    """Derived on read in the pinned order: critical low, critical high, low, high."""
    value = line.get("result_value")
    entry = catalog_entry_of(line)
    if value is None or entry is None:
        return None
    v = dec(value)
    crit_low = entry.get("critical_value_low")
    crit_high = entry.get("critical_value_high")
    ref_low = entry.get("reference_low")
    ref_high = entry.get("reference_high")
    if crit_low is not None and v < dec(crit_low):
        return "CRITICAL_LOW"
    if crit_high is not None and v > dec(crit_high):
        return "CRITICAL_HIGH"
    if ref_low is not None and v < dec(ref_low):
        return "LOW"
    if ref_high is not None and v > dec(ref_high):
        return "HIGH"
    return "NORMAL"


# ---------------------------------------------------------------------------
# volume-tier per-line pricing (PRD section 3.10)
# ---------------------------------------------------------------------------

def reportable_count(order_id, test_catalog_entry_id):
    """STEP 1: same order, same test, line_status in the reportable set."""
    return sum(
        1
        for l in db.all_rows("order_test_lines")
        if l["send_out_order_id"] == order_id
        and l.get("test_catalog_entry_id") == test_catalog_entry_id
        and l.get("line_status") in REPORTABLE_LINE_STATES
    )


def volume_tier_price(line):
    """STEP 1-5 of volume_tier_price, in the pinned evaluation order."""
    order_id = line["send_out_order_id"]
    entry = catalog_entry_of(line)
    if entry is None:
        return Decimal("0")
    count = reportable_count(order_id, line.get("test_catalog_entry_id"))
    if count <= 2:
        rate = TIER_RATE_THROUGH_2
    elif count <= 5:
        rate = TIER_RATE_3_TO_5
    else:
        rate = TIER_RATE_6_PLUS
    contracted = entry.get("client_price_cents")
    contracted = dec(entry.get("list_price_cents")) if contracted is None else dec(contracted)
    discounted = round_half_up(contracted * rate, 2)
    floor = dec(entry.get("floor_price_cents"))
    return max(discounted, floor)


# ---------------------------------------------------------------------------
# order price reconciliation (PRD section 3.10)
# ---------------------------------------------------------------------------

def provisional_charge_cents(order):
    """Variant provisional: sum of catalogue list prices, no discount, no surcharge."""
    total = Decimal("0")
    for line in live_lines_of_order(order["id"]):
        entry = catalog_entry_of(line)
        if entry is not None:
            total += dec(entry.get("list_price_cents"))
    return round_half_up(total, 2)


def order_final_charge_cents(order):
    """Variant final: tiered line charges, rush surcharge, clamped to floor/ceiling."""
    lines = live_lines_of_order(order["id"])
    base = Decimal("0")
    order_floor = Decimal("0")
    list_sum = Decimal("0")
    for line in lines:
        base += dec(line.get("billed_cents"))
        entry = catalog_entry_of(line)
        if entry is not None:
            order_floor += dec(entry.get("floor_price_cents"))
            list_sum += dec(entry.get("list_price_cents"))
    rate = TIER_SURCHARGE_RATE.get(order.get("rush_tier") or "STANDARD", Decimal("0.00"))
    surcharge = round_half_up(base * rate, 2)
    raw = base + surcharge
    ceiling = CEILING_MULTIPLIER * list_sum
    return min(max(raw, order_floor), ceiling)


def price_lines(order):
    """Write billed_cents on every live line, then the two order-level variants."""
    for line in live_lines_of_order(order["id"]):
        line["billed_cents"] = num(volume_tier_price(line))
    order["order_final_charge_cents"] = num(order_final_charge_cents(order))
    order["charge_variance_cents"] = num(
        dec(order["order_final_charge_cents"]) - dec(order.get("provisional_charge_cents"))
    )
    return order


# ---------------------------------------------------------------------------
# turnaround credit (PRD section 3.10)
# ---------------------------------------------------------------------------

def compute_turnaround_credit(order, released_at):
    """Round per line first, then sum: the pinned rounding order."""
    hours = overrun_hours_for(order, released_at)
    total = Decimal("0")
    for line in lines_of_order(order["id"]):
        if line.get("line_status") != "FINAL":
            continue
        if hours == 0:
            credit = Decimal("0.00")
        else:
            credit = round_half_up(
                dec(line.get("billed_cents")) * dec(hours) * LATE_CREDIT_RATE_PER_HOUR, 2
            )
        line["tat_credit_cents"] = num(credit)
        total += credit
    await_total = round_half_up(total, 2)
    order["tat_credit_cents"] = num(await_total)
    return await_total


def overrun_hours_for(order, released_at):
    expected = parse_dt(order.get("expected_result_at"))
    if released_at is None or expected is None:
        return 0
    diff = hours_between(expected, released_at)
    if diff <= 0:
        return 0
    return int(math.ceil(diff))


# ---------------------------------------------------------------------------
# rush tier / expected result (PRD section 3.6)
# ---------------------------------------------------------------------------

def classify_rush_tier(priority, base_tat_hours):
    """Candidate -> first pass -> at most one escalation -> freeze."""
    preliminary = dec(base_tat_hours)
    if priority == "STAT":
        candidate = "CRITICAL"
    else:  # TIMED and ROUTINE
        candidate = "STANDARD"
    first_pass = preliminary * TIER_TAT_FACTOR[candidate]
    if candidate == "STANDARD" and first_pass < RUSH_TAT_THRESHOLD_HOURS:
        tier = "RUSH"
        effective = preliminary * TIER_TAT_FACTOR["RUSH"]
    else:
        tier = candidate
        effective = first_pass
    return tier, round_half_up(effective, 2)


def order_base_tat_hours(order):
    """Max base_tat_hours over the order's live lines; None when none are live."""
    values = []
    for line in lines_of_order(order["id"]):
        if line.get("line_status") not in LIVE_TAT_LINE_STATES:
            continue
        entry = catalog_entry_of(line)
        if entry is not None and entry.get("base_tat_hours") is not None:
            values.append(dec(entry.get("base_tat_hours")))
    if not values:
        return None
    return max(values)


def settle_rush_tier(order):
    """Compute rush_tier, effective_tat_hours and expected_result_at once."""
    base = order_base_tat_hours(order)
    if base is None:
        return
    tier, effective = classify_rush_tier(order.get("priority"), base)
    order["rush_tier"] = tier
    order["base_tat_hours"] = num(base)
    order["effective_tat_hours"] = num(effective)
    specimen = db.get("specimens", order.get("specimen_id"))
    received = parse_dt(specimen.get("received_at")) if specimen else None
    if received is not None:
        from datetime import timedelta

        order["expected_result_at"] = iso(received + timedelta(hours=float(effective)))


def stability_deadline(order):
    """received_at plus the minimum remaining stability across the order's live lines."""
    specimen = db.get("specimens", order.get("specimen_id"))
    if specimen is None:
        return None
    received = parse_dt(specimen.get("received_at"))
    if received is None:
        return None
    window = binding_window_hours(specimen)
    if window is None:
        return None
    from datetime import timedelta

    return iso(received + timedelta(hours=float(window)))


# ---------------------------------------------------------------------------
# retry backoff (PRD section 2.8)
# ---------------------------------------------------------------------------

def next_retry_offset_minutes(retry_count):
    """min(BASE * 2^retry_count, CAP); retry_count is already incremented."""
    raw = BASE_RETRY_MINUTES * (2 ** int(retry_count))
    return min(raw, MAX_RETRY_MINUTES)


# ---------------------------------------------------------------------------
# catalogue currency (PRD section 2.8)
# ---------------------------------------------------------------------------

def catalog_currency_ok(client_laboratory_id, entry):
    """PUBLISHED and no certified order-carrying build older than the entry's edit."""
    if entry is None or entry.get("status") != "PUBLISHED":
        return False
    edited = parse_dt(entry.get("updated_at"))
    if edited is None:
        return True
    for build in db.all_rows("interface_builds"):
        if build.get("client_laboratory_id") != client_laboratory_id:
            continue
        if not build.get("order_interface_enabled"):
            continue
        if build.get("status") != "CERTIFIED":
            continue
        certified = parse_dt(build.get("certified_at"))
        if certified is None:
            continue
        if certified < edited:
            return False
    return True


def stale_order_carrying_build_count(client_laboratory_id, entry):
    edited = parse_dt(entry.get("updated_at"))
    if edited is None:
        return 0
    count = 0
    for build in db.all_rows("interface_builds"):
        if build.get("client_laboratory_id") != client_laboratory_id:
            continue
        if not build.get("order_interface_enabled"):
            continue
        if build.get("status") != "CERTIFIED":
            continue
        certified = parse_dt(build.get("certified_at"))
        if certified is not None and certified < edited:
            count += 1
    return count


# ---------------------------------------------------------------------------
# derived client reconciliation (PRD section 2.9 / 3.5)
# ---------------------------------------------------------------------------

def routed_amount_cents(order):
    """CLIENT arrangement routes the final charge; PATIENT/PAYER route zero."""
    client = db.get("client_laboratories", order.get("client_laboratory_id"))
    arrangement = (client or {}).get("billing_arrangement") or "CLIENT"
    if arrangement != "CLIENT":
        return Decimal("0")
    return dec(order.get("order_final_charge_cents"))


def recompute_outstanding_balance(client):
    """Routed outstanding balance.

    The routed amount of a BILLED order is its final charge for a CLIENT
    arrangement and zero for PATIENT/PAYER. A settlement applied to the ledger
    (PRD section 3.1) is money received against that balance, and the settlement
    is recorded on the ledger by growing its voided total; the credit is netted
    off here so that a settled client's balance falls at or below its credit
    limit and the posture can revert, which is the only thing that makes the
    credit-hold revert leg reachable.
    """
    total = Decimal("0")
    for order in orders_of_client(client["id"]):
        if order.get("billing_status") == "BILLED":
            total += routed_amount_cents(order)
    if (client.get("billing_arrangement") or "CLIENT") == "CLIENT":
        total -= dec(client.get("_settlement_credit_cents") or 0)
    client["outstanding_balance_cents"] = num(round_half_up(total, 2))
    return total


def recompute_interface_status(client):
    """Derived on every write from the highest-status InterfaceBuild of the client."""
    best = None
    for build in db.all_rows("interface_builds"):
        if build.get("client_laboratory_id") != client["id"]:
            continue
        rank = INTERFACE_BUILD_RANK.get(build.get("status"), 0)
        if best is None or rank > best[0]:
            best = (rank, build.get("status"))
    client["interface_status"] = best[1] if best is not None else "NOT_BUILT"
    return client["interface_status"]


def recompute_utilization(client):
    """Forward and settled variants, plus the derived flag."""
    forward = 0
    settled = 0
    window_start = db.now() - _days(WINDOW_DAYS)
    for line in lines_of_client(client["id"]):
        status = line.get("line_status")
        order = order_of_line(line)
        if order is None:
            continue
        if status in REPORTABLE_LINE_STATES:
            requested = parse_dt(order.get("client_requested_at"))
            if requested is not None and requested > window_start:
                forward += 1
        if status == "FINAL":
            released = parse_dt(line.get("result_released_at"))
            if released is not None and released <= db.now() and released > window_start:
                settled += 1
    client["forward_utilization_score"] = forward
    client["settled_utilization_score"] = settled
    client["utilization_flag"] = settled > UTILIZATION_BAND_PER_MONTH
    return forward, settled


def recompute_billable_line_count(client):
    count = sum(
        1
        for line in lines_of_client(client["id"])
        if line.get("line_status") in ("INTERIM", "FINAL")
    )
    client["billable_line_count"] = count
    return count


def recompute_client_derived(client):
    """Refresh every derived counter the client carries. Does not bump version."""
    recompute_interface_status(client)
    recompute_outstanding_balance(client)
    recompute_billable_line_count(client)
    recompute_utilization(client)
    return client


def recompute_ledger(ledger):
    ledger["net_billed_cents"] = num(
        round_half_up(dec(ledger.get("billed_cents")) - dec(ledger.get("voided_cents")), 2)
    )
    return ledger


def _days(n):
    from datetime import timedelta

    return timedelta(days=n)