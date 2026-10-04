from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from db import db, now_iso, get_clock, parse_iso
import errors as E


def touch(entity):
    """Refresh updated_at and bump version for mutable resources."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def system_fields():
    return {"id": None, "created_at": now_iso(), "updated_at": now_iso(), "version": 1}


def append_only_fields():
    return {"id": None, "created_at": now_iso()}


def D(value):
    """Decimal from number or string without float artifacts."""
    return Decimal(str(value))


def round_half_up_cents(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(dec):
    return dec.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def decimal_to_json(dec, places=4):
    """Serialize a Decimal as a float with exact decimal value (e.g. 100.25)."""
    return float(dec.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


# ---------------- calculation: concentrate_unit_price ----------------

TIER1_MIN = 25000
TIER2_MIN = 50000
TIER1_PCT = Decimal("0.02")
TIER2_PCT = Decimal("0.035")
MAX_DISCOUNT = Decimal("0.03")


def _tier_discount(quantity_gallons):
    if quantity_gallons < TIER1_MIN:
        tier = Decimal("0.00")
    elif quantity_gallons < TIER2_MIN:
        tier = TIER1_PCT
    else:
        tier = TIER2_PCT
    return min(MAX_DISCOUNT, tier)


def _price_from_index(base_price, selected_index, base_index, quantity_gallons):
    unit_raw = D(base_price) * (D(selected_index) / D(base_index))
    discount = _tier_discount(quantity_gallons)
    unit = round_half_up_4dp(unit_raw * (Decimal(1) - discount))
    amount_cents = round_half_up_cents(unit * quantity_gallons * 100)
    return unit, amount_cents


def provisional_price(product_line, agreement, quantity_gallons, delivery_quarter):
    indices = [i for i in db.price_indices.values()
               if i["brand_owner_id"] == product_line["brand_owner_id"]
               and i["quarter"] <= delivery_quarter]
    if indices:
        selected = max(indices, key=lambda i: i["quarter"])["index_value"]
    else:
        selected = agreement["concentrate_base_index"]
    return _price_from_index(product_line["concentrate_base_price_per_gallon"],
                             selected,
                             agreement["concentrate_base_index"],
                             quantity_gallons)


def final_price(product_line, agreement, quantity_gallons):
    indices = [i for i in db.price_indices.values()
               if i["brand_owner_id"] == product_line["brand_owner_id"]]
    if indices:
        mean = sum(D(i["index_value"]) for i in indices) / Decimal(len(indices))
        selected = round_half_up_4dp(mean)
    else:
        selected = D(agreement["concentrate_base_index"])
    return _price_from_index(product_line["concentrate_base_price_per_gallon"],
                             selected,
                             agreement["concentrate_base_index"],
                             quantity_gallons)


# ---------------- calculation: dsd_invoice_total ----------------

def compute_invoice_total(customer, lines):
    total = 0
    unit_cents = customer["bound_price_cents"]
    for line in lines:
        raw = D(unit_cents) * D(line["quantity_cases"]) * (Decimal(1) - D(line["discount_pct"]))
        total += round_half_up_cents(raw)
    return total


# ---------------- calculation: territory_transfer_valuation ----------------

BAND_THRESHOLD = 500_000_000
LOW_RATE = Decimal("0.04")
HIGH_RATE = Decimal("0.06")
EBITDA_MULTIPLE = 7


def compute_valuation(reported_ebitda_cents):
    rate = LOW_RATE if reported_ebitda_cents < BAND_THRESHOLD else HIGH_RATE
    reserve = round_half_up_cents(D(reported_ebitda_cents) * rate)
    normalized = reported_ebitda_cents - reserve
    return EBITDA_MULTIPLE * normalized


# ---------------- calculation: nca_price_band_check ----------------

def price_band_ok(local_price_cents, national_price_cents):
    dev = Fraction(abs(local_price_cents - national_price_cents), national_price_cents)
    return dev <= Fraction(5, 100)


# ---------------- calculation: innovation_min_volume_penalty ----------------

def compute_penalty(committed_cases, cases_sold):
    shortfall = committed_cases - cases_sold
    pct = Fraction(shortfall, committed_cases)
    if pct <= Fraction(10, 100):
        rate = 5
    elif pct <= Fraction(25, 100):
        rate = 12
    else:
        rate = 25
    return shortfall * rate


# ---------------- misc helpers ----------------

def clock_date():
    """Logical clock as a date (ISO date string portion)."""
    return get_clock()[:10]


def clock_dt():
    return parse_iso(get_clock())


def refresh_fountain_overdue(account):
    """maintenance_overdue = no maintenance visit within trailing 90 days of clock."""
    last = account.get("last_maintenance_at")
    if last is None:
        account["maintenance_overdue"] = True
        return
    from datetime import timedelta
    overdue = clock_dt() - parse_iso(last) > timedelta(days=90)
    account["maintenance_overdue"] = overdue


def reevaluate_time_gated():
    """Called after clock set: re-evaluate maintenance_overdue for all accounts."""
    for acc in db.fountain_accounts.values():
        refresh_fountain_overdue(acc)
