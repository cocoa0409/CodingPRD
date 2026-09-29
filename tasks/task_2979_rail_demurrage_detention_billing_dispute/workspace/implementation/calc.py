"""Every calculation PRD §3 specifies.

  * §3.3 electing the clock basis
  * §3.5 counting chargeable days (provisional / final variants) and the two
         storage clocks
  * §3.6 the tier ladder, the per-day rate vector and bunching re-laddering
  * §3.7 the average-agreement credit ceiling (FLOOR)
  * §3.8 the adjudication timeline and per-line dispute credit (ROUND_HALF_UP)

All money is integer cents; nothing here touches a float amount.
"""

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from clockcal import (MS_PER_DAY, MS_PER_HOUR, add_days, add_hours, date_of,
                      dates_between, eod, is_business, is_eligible,
                      nth_business, nth_eligible, whole_ms)

# --------------------------------------------------------------------------
# money helpers
# --------------------------------------------------------------------------

def round_half_up_cents(cents, fraction):
    """cents * fraction, rounded half up to a whole cent."""
    value = Decimal(int(cents)) * Decimal(str(fraction))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_cents(cents, fraction):
    """cents * fraction, truncated (FLOOR) to a whole cent."""
    value = Decimal(int(cents)) * Decimal(str(fraction))
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(numerator, denominator):
    if numerator <= 0:
        return 0
    return -((-numerator) // denominator)


# --------------------------------------------------------------------------
# §3.3 notice history and the election of the clock basis
# --------------------------------------------------------------------------

_QUALIFYING_NOTICE = ("SENT", "DELIVERED", "ACKNOWLEDGED")


def notification_sent_at(notes):
    """sent_at of the FIRST notification whose delivery_status is SENT,
    DELIVERED or ACKNOWLEDGED, by sent_at ASC then created_at ASC."""
    eligible = [n for n in notes if n["delivery_status"] in _QUALIFYING_NOTICE]
    if not eligible:
        return None
    eligible.sort(key=lambda n: (n["sent_at"], n["created_at"], n["_seq"]))
    return eligible[0]["sent_at"]


def notification_acknowledged_at(notes):
    """acknowledged_at of whichever notification was most recently moved to
    ACKNOWLEDGED."""
    acked = [n for n in notes if n["delivery_status"] == "ACKNOWLEDGED"]
    if not acked:
        return None
    acked.sort(key=lambda n: n.get("_ack_seq", 0))
    return acked[-1]["acknowledged_at"]


def pick_acknowledgeable(notes):
    """The notification with delivery_status SENT or DELIVERED and the greatest
    sent_at, tie-broken by the greatest created_at."""
    candidates = [n for n in notes if n["delivery_status"] in ("SENT", "DELIVERED")]
    if not candidates:
        return None
    candidates.sort(key=lambda n: (n["sent_at"], n["created_at"], n["_seq"]))
    return candidates[-1]


def free_days_for(ownership, tariff):
    """§3.3 step 3.  PRIVATE_ASSIGNED takes the RAILROAD allowance - a
    different predicate from the rate-ladder one in §3.6."""
    if ownership == "PRIVATE":
        return tariff["free_time_hours_private"] // 24
    return tariff["free_time_hours_railroad"] // 24


def expiry_of(instant, free_days, weekend_excluded):
    """§3.3 step 4: the last millisecond of the free_days-th eligible date
    after the date of `instant`."""
    if instant is None:
        return None
    target = nth_eligible(date_of(instant), free_days, weekend_excluded)
    return eod(target)


def resolve_clock(cycle, customer, tariff, car, notes):
    """§3.3 - returns (clock_basis, clock_start_at, free_days,
    free_time_expires_at)."""
    cp = cycle.get("constructive_placement_at")
    ap = cycle.get("actual_placement_at")
    weekend_excluded = tariff["weekend_excluded"]
    free_days = free_days_for(car["ownership"], tariff)

    # STEP 1 - when the notice became legally effective.
    if customer["notification_method"] == "FAX":
        neff = notification_acknowledged_at(notes)
    else:
        ns = notification_sent_at(notes)
        neff = None if ns is None else add_hours(ns, tariff["notification_grace_hours"])

    # STEP 2 - the constructive start.
    if neff is None or cp is None:
        cstart = None
    else:
        cstart = cp if cp >= neff else neff

    # STEP 5 - elect the basis.
    if ap is None:
        if cstart is None:
            return "NONE", None, free_days, None
        return "CONSTRUCTIVE", cstart, free_days, expiry_of(cstart, free_days, weekend_excluded)
    if cstart is None:
        return "ACTUAL", ap, free_days, expiry_of(ap, free_days, weekend_excluded)
    cexp = expiry_of(cstart, free_days, weekend_excluded)
    if ap <= cexp:
        # Spotted inside the constructive free time: a fresh clock is earned.
        return "ACTUAL", ap, free_days, expiry_of(ap, free_days, weekend_excluded)
    # The railroad blew through the free time; the constructive clock stands.
    return "CONSTRUCTIVE", cstart, free_days, cexp


# --------------------------------------------------------------------------
# §3.5 chargeable and early-release day counts
# --------------------------------------------------------------------------

def count_chargeable_days(expiry, reference, release_day_charged, weekend_excluded):
    if expiry is None or reference is None:
        return 0
    first = add_days(date_of(expiry), 1)
    last = date_of(reference)
    if last < first:
        return 0
    total = 0
    for d in dates_between(first, last):
        if not is_eligible(d, weekend_excluded):
            continue
        if d < last:
            total += 1
        elif release_day_charged:
            total += 1
    return total


def count_early_release_days(expiry, reference, weekend_excluded):
    """Eligible dates strictly after the reference date and up to and including
    the expiry date."""
    if expiry is None or reference is None:
        return 0
    first = add_days(date_of(reference), 1)
    last = date_of(expiry)
    if last < first:
        return 0
    return sum(1 for d in dates_between(first, last)
               if is_eligible(d, weekend_excluded))


def release_day_is_chargeable(released_at, gate_close_hour):
    """The release date counts exactly when the time of day is at or after
    gate_close_hour:00:00.000."""
    t = released_at
    return (t.hour, t.minute, t.second, t.microsecond) >= (gate_close_hour, 0, 0, 0)


# --------------------------------------------------------------------------
# §3.5 the two storage clocks
# --------------------------------------------------------------------------

def storage_days(cycle, facility):
    arrival = cycle.get("constructive_placement_at")
    released = cycle.get("released_at")
    if arrival is None or released is None:
        return 0
    free_hours = facility["storage_free_hours"]
    if facility["storage_clock_mode"] == "HOURLY_FROM_ARRIVAL":
        dwell_ms = whole_ms(released - arrival)
        billable_ms = dwell_ms - free_hours * MS_PER_HOUR
        if billable_ms < 0:
            billable_ms = 0
        return ceil_int(billable_ms, MS_PER_DAY)
    # CALENDAR_DAY_MIDNIGHT
    first = add_days(date_of(arrival), free_hours // 24)
    last = date_of(released)
    if last < first:
        return 0
    operates_weekends = facility["operates_weekends"]
    return sum(1 for d in dates_between(first, last)
               if operates_weekends or is_business(d))


def storage_basis(facility):
    if facility["storage_clock_mode"] == "HOURLY_FROM_ARRIVAL":
        return "STORAGE_HOURLY"
    return "STORAGE_CALENDAR"


# --------------------------------------------------------------------------
# §3.6 the tier ladder
# --------------------------------------------------------------------------

def rate_ladder(ownership, tariff):
    """RAILROAD_OWNED rides the railroad ladder; PRIVATE and PRIVATE_ASSIGNED
    alike ride the private one."""
    if ownership == "RAILROAD_OWNED":
        return (tariff["tier1_rate_cents_railroad"],
                tariff["tier2_rate_cents_railroad"],
                tariff["tier3_rate_cents_railroad"])
    return (tariff["tier1_rate_cents_private"],
            tariff["tier2_rate_cents_private"],
            tariff["tier3_rate_cents_private"])


def apportion_days(billable_days, n1, n2):
    t1 = min(billable_days, n1)
    t2 = min(max(billable_days - n1, 0), n2)
    t3 = max(billable_days - n1 - n2, 0)
    return t1, t2, t3


def tiered_gross_cents(billable_days, ownership, tariff):
    r1, r2, r3 = rate_ladder(ownership, tariff)
    t1, t2, t3 = apportion_days(billable_days, tariff["tier1_day_count"],
                                tariff["tier2_day_count"])
    return t1 * r1 + t2 * r2 + t3 * r3


def rate_of_day_vector(billable_days, ownership, tariff):
    """The per-day rate vector §3.7's credit waterfall needs."""
    r1, r2, r3 = rate_ladder(ownership, tariff)
    n1 = tariff["tier1_day_count"]
    n2 = tariff["tier2_day_count"]
    out = []
    for k in range(1, billable_days + 1):
        if k <= n1:
            out.append(r1)
        elif k <= n1 + n2:
            out.append(r2)
        else:
            out.append(r3)
    return out


def billable_days_of(chargeable_days, bunching_exempt_days):
    return max(0, chargeable_days - bunching_exempt_days)


# --------------------------------------------------------------------------
# §3.8 the adjudication timeline
# --------------------------------------------------------------------------

GROUNDS_MULTIPLIER = {
    "RAILROAD_CAUSED_DELAY": "1.00",
    "BUNCHING": "1.25",
    "NOTIFICATION_FAILURE": "0.75",
    "RATE_UNREASONABLE": "1.50",
    "CLOCK_BASIS_ERROR": "1.00",
}

EVIDENCE_WEIGHT_POINTS = {
    "SWITCH_LIST": 3,
    "GATE_LOG": 3,
    "EMAIL_NOTICE": 1,
    "TRACK_EMBARGO_NOTICE": 4,
    "WEIGHT_CERTIFICATE": 2,
}

APPEAL_MULTIPLIER = "0.50"
INFO_REQUEST_DAYS = 10
MIN_ADJUDICATION_DAYS = 5
WEIGHT_CREDIT_CAP_DAYS = 5
DISPUTE_WINDOW_DAYS = 30
COMPLAINT_RESPONSE_DAYS = 15


def _ceil_days(base, multiplier):
    value = Decimal(int(base)) * Decimal(multiplier)
    return int(value.to_integral_value(rounding="ROUND_CEILING"))


def adjudication_days(round_number, base, grounds, evidence_weight):
    if round_number == 1:
        gross_days = _ceil_days(base, GROUNDS_MULTIPLIER[grounds])
        credit = min(WEIGHT_CREDIT_CAP_DAYS, evidence_weight // 2)
        return max(MIN_ADJUDICATION_DAYS, gross_days - credit)
    return max(MIN_ADJUDICATION_DAYS, _ceil_days(base, APPEAL_MULTIPLIER))


def adjudication_due_at(from_date, days):
    return eod(nth_business(from_date, days))
