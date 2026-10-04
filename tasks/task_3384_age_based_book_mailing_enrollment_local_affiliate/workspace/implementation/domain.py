"""Calendar-month arithmetic, derived fields and serializers."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db

BANDS = ("INFANT", "TODDLER", "TWO", "THREE", "FOUR")
ACTIVE_CHILD_STATES = ("ACTIVE", "UNDELIVERABLE_HOLD")

PRESS_MONTHLY_CAPACITY = 400000
HANDLING_CENTS_PER_BOOK = 35
RETURN_AUTO_UNENROLL_THRESHOLD = 2


# --------------------------------------------------------------------------
# Month math (calendar-month arithmetic; YYYY-MM strings compare lexically)
# --------------------------------------------------------------------------

def month_add(month, n):
    y = int(month[0:4])
    m = int(month[5:7])
    idx = y * 12 + (m - 1) + n
    return "%04d-%02d" % (idx // 12, idx % 12 + 1)


def month_first_day(month):
    return datetime(int(month[0:4]), int(month[5:7]), 1, tzinfo=timezone.utc)


def age_months(birth, month):
    """Whole months between birth date and reference month; day ignored."""
    return (int(month[0:4]) * 12 + int(month[5:7])) - (birth.year * 12 + birth.month)


def band_for_age(age):
    if age < 0 or age >= 60:
        return None
    return BANDS[age // 12]


def round_half_up_ratio(num, den):
    return int((Decimal(num) / Decimal(den)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Derived fields (reconciled against the live store)
# --------------------------------------------------------------------------

def agreement_covers_month(agr, month):
    return (
        agr["status"] == "ACTIVE"
        and agr["_from"] <= month_first_day(month)
        and agr["_to"] >= month_first_day(month_add(month, 1))
    )


def operative_for_month(affiliate_id, month):
    for a in db.agreements.values():
        if a["affiliate_id"] == affiliate_id and agreement_covers_month(a, month):
            return True
    return False


def enrolled_count(affiliate_id):
    n = 0
    for c in db.children.values():
        if c["affiliate_id"] == affiliate_id and c["enrollment_status"] in ACTIVE_CHILD_STATES:
            n += 1
    return n


def stock_on_hand(title_id):
    total = 0
    for po in db.print_orders.values():
        if po["status"] != "CONFIRMED":
            continue
        sel = db.selections.get(po["selection_id"])
        if sel and sel["title_id"] == title_id:
            total += po["quantity"]
    for it in db.items.values():
        sel = db.selections.get(it["selection_id"])
        if sel and sel["title_id"] == title_id:
            total -= 1
    return total


def confirmed_order_for_selection(selection_id):
    for po in db.print_orders.values():
        if po["selection_id"] == selection_id and po["status"] == "CONFIRMED":
            return po
    return None


# --------------------------------------------------------------------------
# Serializers (strip internal "_" keys, attach computed fields)
# --------------------------------------------------------------------------

def pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ser_state_program(r):
    return pub(r)


def ser_affiliate(r):
    out = pub(r)
    out["operative"] = operative_for_month(r["id"], db.logical_month())
    out["enrolled_count"] = enrolled_count(r["id"])
    return out


def ser_agreement(r):
    return pub(r)


def ser_population_stat(r):
    return pub(r)


def ser_child(r):
    return pub(r)


def ser_address_change(r):
    return pub(r)


def ser_title(r):
    out = pub(r)
    out["stock_on_hand"] = stock_on_hand(r["id"])
    return out


def ser_selection(r):
    return pub(r)


def ser_print_order(r):
    return pub(r)


def ser_wave(r):
    return pub(r)


def ser_item(r):
    out = pub(r)
    out["billable"] = r["status"] in ("MAILED", "DELIVERED")
    return out


def ser_invoice(r):
    return pub(r)
