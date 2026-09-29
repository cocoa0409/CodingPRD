"""The write side of PRD §2.9: every cascade the narrative names.

Nothing here is incremental.  Each function rebuilds its target from the live
source rows, which is what keeps the invoice money invariant of §2.6 true
across voids, appeals and forfeitures alike.
"""

from decimal import ROUND_FLOOR, Decimal

from calc import (count_chargeable_days, count_early_release_days,
                  rate_of_day_vector, release_day_is_chargeable, resolve_clock,
                  storage_basis, storage_days, tiered_gross_cents)
from clockcal import month_key
from derive import (charge_of_cycle, cycles_of_customer, live_charges_of_invoice,
                    notifications_of_cycle)
from store import db, touch

# --------------------------------------------------------------------------
# parents of a cycle
# --------------------------------------------------------------------------

def parents_of(cycle):
    return (db.customers[cycle["customer_id"]],
            db.tariffs[cycle["tariff_rule_set_id"]],
            db.facilities[cycle["facility_id"]],
            db.rail_cars[cycle["rail_car_id"]])


# --------------------------------------------------------------------------
# §3.3 the clock-basis election, re-run after each of its five events
# --------------------------------------------------------------------------

def run_election(cycle):
    customer, tariff, _facility, car = parents_of(cycle)
    notes = notifications_of_cycle(cycle["id"])
    basis, start, free_days, expiry = resolve_clock(
        cycle, customer, tariff, car, notes)
    cycle["clock_basis"] = basis
    cycle["clock_start_at"] = start
    cycle["free_days"] = free_days
    cycle["free_time_expires_at"] = expiry


# --------------------------------------------------------------------------
# §3.5 / §3.6 charge recomputation
# --------------------------------------------------------------------------

def recompute_charge(cycle, charge, final=False):
    """A full recomputation: chargeable_days first, then billable_days and the
    tiered (or flat storage) gross."""
    _customer, tariff, facility, car = parents_of(cycle)

    if charge["charge_kind"] == "STORAGE":
        charge["computation_basis"] = storage_basis(facility)
        days = storage_days(cycle, facility) if final else 0
        charge["chargeable_days"] = days
        billable = max(0, days - charge["bunching_exempt_days"])
        charge["gross_amount_cents"] = billable * facility["storage_daily_rate_cents"]
        return charge

    basis = cycle["clock_basis"]
    charge["computation_basis"] = None if basis == "NONE" else basis
    expiry = cycle["free_time_expires_at"]
    if final:
        reference = cycle["released_at"]
        release_day_charged = (
            reference is not None
            and release_day_is_chargeable(reference, facility["gate_close_hour"]))
    else:
        # The provisional variant reads the logical clock and never charges the
        # reference date, because today is still running.
        reference = db.now()
        release_day_charged = False
    days = count_chargeable_days(expiry, reference, release_day_charged,
                                 tariff["weekend_excluded"])
    charge["chargeable_days"] = days
    reprice_charge(cycle, charge)
    return charge


def reprice_charge(cycle, charge):
    """Re-walk the ladder from tier one for the surviving days (§3.6)."""
    _customer, tariff, facility, car = parents_of(cycle)
    billable = max(0, charge["chargeable_days"] - charge["bunching_exempt_days"])
    if charge["charge_kind"] == "STORAGE":
        charge["gross_amount_cents"] = billable * facility["storage_daily_rate_cents"]
    else:
        charge["gross_amount_cents"] = tiered_gross_cents(
            billable, car["ownership"], tariff)
    return charge


def day_rate_vector(cycle, charge):
    billable = max(0, charge["chargeable_days"] - charge["bunching_exempt_days"])
    _customer, tariff, facility, car = parents_of(cycle)
    if charge["charge_kind"] == "STORAGE":
        return [facility["storage_daily_rate_cents"]] * billable
    return rate_of_day_vector(billable, car["ownership"], tariff)


def finalize_cycle_days(cycle, charge):
    """Release freezes the cycle's own two day counts."""
    _customer, tariff, _facility, _car = parents_of(cycle)
    cycle["chargeable_days"] = charge["chargeable_days"]
    cycle["early_release_days"] = count_early_release_days(
        cycle["free_time_expires_at"], cycle["released_at"],
        tariff["weekend_excluded"])


# --------------------------------------------------------------------------
# §3.7 the invoice rollup.  The projection in derive.py recomputes the three
# totals on every read, so the cascade's job is only to bump the version.
# --------------------------------------------------------------------------

def rederive_invoice(invoice, bump_version=True):
    if bump_version:
        touch(invoice)
    return invoice


# --------------------------------------------------------------------------
# §3.7 the average-agreement day ledger
# --------------------------------------------------------------------------

def released_in_month(cycle, month):
    released = cycle.get("released_at")
    return (released is not None
            and cycle["movement_status"] != "VOIDED"
            and month_key(released) == month)


def rebuild_agreement_days(agreement):
    """Rebuilt from scratch, never by increment, so a voided cycle silently
    disappears from both sides of the ledger."""
    month = agreement["agreement_month"]
    customer_id = agreement["customer_id"]
    earned = 0
    incurred = 0
    for cycle in cycles_of_customer(customer_id):
        if not released_in_month(cycle, month):
            continue
        earned += cycle["early_release_days"]
        charge = charge_of_cycle(cycle["id"])
        if charge is not None and charge["status"] in ("FINAL", "ADJUSTED"):
            # The debit side reads chargeable_days and not billable_days, so a
            # bunching exemption reduces the money without reducing the debit.
            incurred += charge["chargeable_days"]
    agreement["credit_days_earned"] = earned
    agreement["debit_days_incurred"] = incurred
    agreement["net_days"] = earned - incurred
    return agreement


def open_agreement_for_release(cycle):
    released = cycle.get("released_at")
    if released is None:
        return None
    month = month_key(released)
    for ag in db.agreements.values():
        if (ag["customer_id"] == cycle["customer_id"]
                and ag["status"] == "OPEN"
                and ag["agreement_month"] == month):
            return ag
    return None


def open_agreement_of_customer(customer_id):
    for ag in db.agreements.values():
        if ag["customer_id"] == customer_id and ag["status"] == "OPEN":
            return ag
    return None


# --------------------------------------------------------------------------
# §3.7 the average-agreement credit, computed at invoice issue in eight steps
# --------------------------------------------------------------------------

def _floor_cap(month_gross, ratio):
    """Step six: the contractual ceiling uses FLOOR and never rounding, so a
    gross of 47551 at 0.30 gives the same 14265 cents as a gross of 47550."""
    value = Decimal(int(month_gross)) * Decimal(str(ratio))
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def apply_agreement_credit(invoice):
    """Steps one through seven.  Returns the credit landed, in cents."""
    lines = live_charges_of_invoice(invoice["id"])

    # STEP 1 - the month's gross over the live attached lines.
    month_gross = sum(ch["gross_amount_cents"] for ch in lines)

    # STEP 2 - the agreement, keyed on the billing period's own month.
    month = month_key(invoice["billing_period_start"])
    agreement = None
    for ag in db.agreements.values():
        if (ag["customer_id"] == invoice["customer_id"]
                and ag["status"] == "OPEN"
                and ag["agreement_month"] == month):
            agreement = ag
            break
    if agreement is None:
        invoice["agreement_credit_cents"] = 0
        return 0

    # STEP 3 - rebuild the day ledger from scratch.
    rebuild_agreement_days(agreement)

    # STEP 4 - credit days can only be spent against days actually owed.
    spendable = min(agreement["credit_days_earned"],
                    agreement["debit_days_incurred"])
    if spendable <= 0:
        agreement["agreement_credit_cents"] = 0
        invoice["agreement_credit_cents"] = 0
        return 0

    # STEP 5 - one entry per billable day, most expensive day first.  Sorting
    # descending by rate rather than ascending by day position is what makes
    # the credit larger than a naive first-day-first waterfall.
    entries = []
    for charge in lines:
        cycle = db.cycles[charge["placement_cycle_id"]]
        for position, rate in enumerate(day_rate_vector(cycle, charge), start=1):
            entries.append((-rate, charge["created_at"], position, rate, charge))
    entries.sort(key=lambda e: (e[0], e[1], e[2]))
    taken = entries[:spendable]
    uncapped = sum(e[3] for e in taken)

    # STEP 6 / 7 - the floored ceiling, then land the credit line by line.
    cap = _floor_cap(month_gross, agreement["credit_cap_ratio"])
    credit = uncapped if uncapped < cap else cap
    if credit < 0:
        credit = 0

    remaining = credit
    for entry in taken:
        if remaining <= 0:
            break
        rate = entry[3]
        charge = entry[4]
        landed = rate if rate < remaining else remaining
        charge["credit_applied_cents"] += landed
        charge["_agreement_credit_cents"] = (
            charge.get("_agreement_credit_cents", 0) + landed)
        charge["_agreement_id"] = agreement["id"]
        remaining -= landed

    # §3 does not declare a version increment on the agreement at issue time,
    # so its ledger is refreshed without touching its version counter.
    agreement["agreement_credit_cents"] = credit
    invoice["agreement_credit_cents"] = credit
    return credit


def reverse_agreement_credit(agreement):
    """Forfeiture is a full unwind, not a flag: every cent this agreement
    landed comes back off the lines and off the invoices that carried it."""
    touched_invoices = set()
    for charge in db.charges.values():
        if charge.get("_agreement_id") != agreement["id"]:
            continue
        landed = charge.get("_agreement_credit_cents", 0)
        if landed <= 0:
            continue
        applied = charge["credit_applied_cents"] - landed
        charge["credit_applied_cents"] = applied if applied > 0 else 0
        charge["_agreement_credit_cents"] = 0
        if charge["invoice_id"] is not None:
            touched_invoices.add(charge["invoice_id"])
    for invoice_id in touched_invoices:
        invoice = db.invoices.get(invoice_id)
        if invoice is not None:
            invoice["agreement_credit_cents"] = 0
            touch(invoice)
    agreement["agreement_credit_cents"] = 0
    return touched_invoices
