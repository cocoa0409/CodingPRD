"""Business-logic services: derived quantities, proration, cascades, money."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import fail
from util import touch

FEED_GAS_RATIO = Decimal("1.10")
LOADING_RATE = 240000
BERTH_ALLOWANCE_HOURS = 4
NOR_GRACE_HOURS = 6
CONNECTION_ALLOWANCE_HOURS = 2
FLOOR_MIN_MMBTU = 5000
HANDLING_FEE_PCT = Decimal("0.02")
PIPELINE_TARIFF = Decimal("0.35")
BERTH_CHANGEOVER_BUFFER_HOURS = 2


def D(v):
    return Decimal(str(v))


def money2(v):
    """Decimal -> 2dp half-up, returned as float for JSON."""
    return float(D(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def hours2(v):
    return float(D(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def dec2(v):
    return D(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def feed_gas_requirement(quantity_mmbtu):
    return math.ceil(D(quantity_mmbtu) * FEED_GAS_RATIO)


def invoice_amount(quantity, fee, multiplier, index_price):
    return money2(D(quantity) * (D(fee) + D(multiplier) * D(index_price)))


# ---- lookups / ownership ----

def spa_of_adp(adp):
    return db.spas.get(adp["spa_id"])


def adp_of_slot(slot):
    return db.adps.get(slot["adp_id"])


def spa_of_slot(slot):
    adp = adp_of_slot(slot)
    return spa_of_adp(adp) if adp else None


def owning_customer_id_of_slot(slot):
    spa = spa_of_slot(slot)
    return spa["customer_id"] if spa else None


def owning_customer_id_of_call(call):
    slot = db.cargo_slots.get(call["cargo_slot_id"])
    return owning_customer_id_of_slot(slot) if slot else None


def owning_customer_id_of_statement(stmt):
    call = db.vessel_calls.get(stmt["vessel_call_id"])
    return owning_customer_id_of_call(call) if call else None


def check_customer_owner(user_id, owner_customer_id):
    if user_id != owner_customer_id:
        fail("ERR_FORBIDDEN", "CustomerRep identity does not match the owning customer")


# ---- SPA lazy expiry ----

def apply_spa_expiry(spa):
    """Lazy EXPIRED transition when the logical clock passes contract end."""
    if spa["status"] == "DELIVERIES_COMMENCED":
        end_year = spa["contract_year_start"] + spa["term_years"]
        from datetime import datetime, timezone
        end_instant = datetime(end_year, 1, 1, tzinfo=timezone.utc)
        if db.get_clock() >= end_instant:
            spa["status"] = "EXPIRED"
            touch(spa)


# ---- ADP quantity recompute ----

def recompute_adp_quantities(adp):
    """Recompute scheduled/cancelled/unallocated; bumps version (a mutation)."""
    spa = spa_of_adp(adp)
    slots = [s for s in db.cargo_slots.values() if s["adp_id"] == adp["id"]]
    scheduled = sum(s["quantity_mmbtu"] for s in slots if s["lift_status"] != "CANCELLED")
    cancelled = sum(s["quantity_mmbtu"] for s in slots if s["lift_status"] == "CANCELLED")
    adp["scheduled_quantity_mmbtu"] = scheduled
    adp["cancelled_quantity_mmbtu"] = cancelled
    adp["unallocated_quantity_mmbtu"] = spa["annual_contract_quantity_mmbtu"] - scheduled - cancelled
    touch(adp)


def recompute_adp_quantities_quiet(adp):
    """Recompute fields without a version bump (used at creation)."""
    spa = spa_of_adp(adp)
    slots = [s for s in db.cargo_slots.values() if s["adp_id"] == adp["id"]]
    scheduled = sum(s["quantity_mmbtu"] for s in slots if s["lift_status"] != "CANCELLED")
    cancelled = sum(s["quantity_mmbtu"] for s in slots if s["lift_status"] == "CANCELLED")
    adp["scheduled_quantity_mmbtu"] = scheduled
    adp["cancelled_quantity_mmbtu"] = cancelled
    adp["unallocated_quantity_mmbtu"] = spa["annual_contract_quantity_mmbtu"] - scheduled - cancelled


# ---- Schedule totals ----

def recompute_schedule_totals(sched):
    noms = [n for n in db.nominations.values() if n["pipeline_day_schedule_id"] == sched["id"]]
    sched["total_nominated_mmbtu"] = sum(n["nominated_mmbtu"] for n in noms)
    sched["total_confirmed_mmbtu"] = sum(
        n["confirmed_mmbtu"] for n in noms if n["status"] in ("CONFIRMED", "RECONCILED"))
    sched["total_cut_mmbtu"] = sum(
        n["nominated_mmbtu"] for n in noms if n["status"] == "CUT") + sum(
        n["cut_mmbtu"] for n in noms if n["status"] in ("CONFIRMED", "RECONCILED"))


# ---- Proration waterfall ----

def prorate(sched):
    """Run prorata_nomination_scaling over the schedule's non-CUT nominations.
    On close: operates over SUBMITTED nominations. On re-run (cancellation):
    operates over SUBMITTED + CONFIRMED + RECONCILED? No — remaining non-CUT.
    Confirmed/reconciled nominations keep... re-proration re-allocates.
    Per spec: 're-run prorata over the schedule's remaining non-CUT nominations'.
    """
    noms = [n for n in db.nominations.values()
            if n["pipeline_day_schedule_id"] == sched["id"] and n["status"] != "CUT"]
    noms.sort(key=lambda n: (n["created_at"], n["id"]))
    total = sum(n["nominated_mmbtu"] for n in noms)
    capacity = sched["capacity_mmbtu"]
    if not noms:
        return
    if total <= capacity:
        for n in noms:
            n["confirmed_mmbtu"] = n["nominated_mmbtu"]
            n["cut_mmbtu"] = 0
            if n["status"] == "SUBMITTED":
                n["status"] = "CONFIRMED"
                touch(n)
        return
    factor = Decimal(capacity) / Decimal(total)
    bases = {}
    fracs = []
    for n in noms:
        nom = n["nominated_mmbtu"]
        exact = Decimal(nom) * factor
        floored = int(exact)  # floor for positive values
        # PRD §3.6: the floor of 5,000 MMBTU is a guaranteed minimum — "a floor
        # of 5,000 MMBTU applied as the lesser of the nomination's volume and
        # the floor itself" raises the pro-rata term when the term falls below
        # the floor; the base is then the smallest of (nominated, that floored
        # minimum, the floored pro-rata term) taken as
        # min(nom, max(min(nom, FLOOR), floored_term)).
        base = min(nom, max(min(nom, FLOOR_MIN_MMBTU), floored))
        bases[n["id"]] = base
        # Remainder distribution ranks by "the largest fractional part of
        # their nominated-times-factor product" — the raw product's fraction.
        fracs.append((exact - int(exact), n))
    remainder = capacity - sum(bases.values())
    # largest fractional part first; ties by created_at ASC (noms pre-sorted).
    # One MMBTU at a time down the ranked list; "no nomination may receive
    # more than it nominated" caps each award. Loop the list if a single pass
    # cannot absorb the remainder (all ranked, cap permitting).
    fracs.sort(key=lambda t: (-t[0], t[1]["created_at"], t[1]["id"]))
    idx = 0
    while remainder > 0 and any(
        bases[n["id"]] < n["nominated_mmbtu"] for _, n in fracs
    ):
        _, n = fracs[idx % len(fracs)]
        if bases[n["id"]] < n["nominated_mmbtu"]:
            bases[n["id"]] += 1
            remainder -= 1
        idx += 1
    for n in noms:
        conf = bases[n["id"]]
        n["confirmed_mmbtu"] = conf
        n["cut_mmbtu"] = n["nominated_mmbtu"] - conf
        if conf == 0:
            n["status"] = "CUT"
        elif n["status"] == "SUBMITTED":
            n["status"] = "CONFIRMED"
        touch(n)


# ---- Berth window overlap ----

def berth_window_conflict(berth_id, start, end, exclude_call_id=None):
    """Half-open windows with 2h changeover buffer against ACCEPTED-or-later calls."""
    buf = timedelta(hours=BERTH_CHANGEOVER_BUFFER_HOURS)
    for call in db.vessel_calls.values():
        if call["id"] == exclude_call_id:
            continue
        if call.get("berth_id") != berth_id:
            continue
        if call["status"] not in ("ACCEPTED", "NOR_TENDERED", "BERTHED", "DEPARTED"):
            continue
        cs = call["_window_start_dt"]
        ce = call["_window_end_dt"]
        # buffered: [cs - buf, ce + buf)
        if start < ce + buf and end > cs - buf:
            return True
    return False
