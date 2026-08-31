"""Calculation rules — PRD sections 2.6, 3.2, 3.3, 3.4, 3.5, 3.6, 3.8, 3.9."""

from decimal import Decimal, ROUND_HALF_UP

from store import store, parse_date, parse_instant

# ---- constants ------------------------------------------------------------
WIND_SUSPEND_KT = Decimal("35.0")
WAVE_SUSPEND_M = Decimal("2.50")
WIND_RESTRICT_KT = Decimal("22.0")
WAVE_RESTRICT_M = Decimal("1.20")
LOW_WATER_RESTRICT_M = Decimal("1.80")

SURGE_ELEVATED_FLOOR = 15000
SURGE_PEAK_FLOOR = 30000
SURGE_MULTIPLIER_BP = {"NONE": 10000, "ELEVATED": 12500, "PEAK": 15000}
PLANNED_EXTRA_VESSELS = {"NONE": 0, "ELEVATED": 1, "PEAK": 2}

CAPACITY_DERATE_CLEARANCE_M = Decimal("0.60")
CREW_LIMITED_CAP = 24
SURGE_STANDING_BONUS = 12
POSTURE_FACTOR_PCT = {"NORMAL": 100, "RESTRICTED": 70, "SUSPENDED": 0}

ZONE_BASE_CENTS = 450
ZONE_STEP_CENTS = 275
MODE_MULT_BP = {"ON_DEMAND": 14000, "SCHEDULED": 10000}

REBATE_TIER1_FLOOR_CENTS = 200000
REBATE_TIER2_FLOOR_CENTS = 500000
REBATE_TIER1_BP = 800
REBATE_TIER2_BP = 1500

RETAIL_PER_RIDE_CENTS = {"INNER": 1100, "OUTER": 1800, "ALL_ZONE": 2600}
ZONE_TIER_SPAN = {"INNER": 1, "OUTER": 3, "ALL_ZONE": None}

PARTIAL_LEG_SHARE_BP = 5000
CASH_REFUND_CAP_CENTS = 5000

MAX_OFFER_ROUNDS = 3
MAX_DEFICIENCIES_RESTRICTED = 2
MIN_UNDER_KEEL_CLEARANCE_M = Decimal("0.30")
ANNUAL_INSPECTION_VALID_DAYS = 365

ENDORSEMENT_RANK = {"MASTER_25T": 1, "MASTER_100T": 2}


# ---- primitives -----------------------------------------------------------

def dec(value):
    return Decimal(str(value))


def round_half_up_cents(value):
    """Round a Decimal quantity to a whole cent, half away from zero upward."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def apply_bp(amount_cents, rate_bp):
    """round_half_up(amount * rate_bp / 10000) in whole cents."""
    return round_half_up_cents(Decimal(amount_cents) * Decimal(rate_bp) / Decimal(10000))


# ---- ServiceDay -----------------------------------------------------------

def derive_posture(day):
    if day.get("manual_suspension"):
        return "SUSPENDED"
    wind = dec(day["wind_knots"])
    wave = dec(day["wave_height_m"])
    water = dec(day["low_water_m"])
    if wind >= WIND_SUSPEND_KT:
        return "SUSPENDED"
    if wave >= WAVE_SUSPEND_M:
        return "SUSPENDED"
    if wind >= WIND_RESTRICT_KT:
        return "RESTRICTED"
    if wave >= WAVE_RESTRICT_M:
        return "RESTRICTED"
    if water < LOW_WATER_RESTRICT_M:
        return "RESTRICTED"
    return "NORMAL"


def derive_surge(day):
    if day.get("event_name") is None:
        tier = "NONE"
    elif day.get("expected_attendance", 0) >= SURGE_PEAK_FLOOR:
        tier = "PEAK"
    elif day.get("expected_attendance", 0) >= SURGE_ELEVATED_FLOOR:
        tier = "ELEVATED"
    else:
        tier = "NONE"
    return tier, SURGE_MULTIPLIER_BP[tier], PLANNED_EXTRA_VESSELS[tier]


def recompute_day_derived(day):
    day["posture"] = derive_posture(day)
    tier, mult, extra = derive_surge(day)
    day["surge_tier"] = tier
    day["surge_multiplier_bp"] = mult
    day["planned_extra_vessels"] = extra
    return day


def day_by_date(service_date_str):
    for row in store.service_days.values():
        if row["service_date"] == service_date_str:
            return row
    return None


# ---- Vessel ---------------------------------------------------------------

def latest_annual_inspection(vessel_id):
    rows = [r for r in store.inspections.values()
            if r["vessel_id"] == vessel_id and r["inspection_type"] == "ANNUAL"]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["performed_on"], r["_seq"]), reverse=True)
    return rows[0]


def vessel_service_state(vessel):
    latest = latest_annual_inspection(vessel["id"])
    if latest is not None and latest["result"] == "FAIL":
        return "OUT_OF_SERVICE"
    start = vessel.get("layup_start_date")
    end = vessel.get("layup_end_date")
    if start is not None and end is not None:
        today = store.clock_date()
        start_d = parse_date(start)
        end_d = parse_date(end)
        if start_d is not None and end_d is not None and start_d <= today <= end_d:
            return "LAID_UP"
    return "IN_SERVICE"


def vessel_annual_expires_on(vessel):
    latest = latest_annual_inspection(vessel["id"])
    return latest["expires_on"] if latest is not None else None


# ---- Trip capacity --------------------------------------------------------

def under_keel_clearance(day, vessel):
    return round_half_up_2(dec(day["low_water_m"]) - dec(vessel["draft_m"]))


def trip_effective_capacity(trip):
    vessel = store.vessels.get(trip["vessel_id"])
    crew = store.crew.get(trip["master_crew_id"])
    day = store.service_days.get(trip["service_day_id"])
    if vessel is None or crew is None or day is None:
        return 0
    seat_capacity = vessel["seat_capacity"]
    factor = POSTURE_FACTOR_PCT[day["posture"]]
    posture_cap = (seat_capacity * factor) // 100
    clearance = under_keel_clearance(day, vessel)
    tide_cap = seat_capacity // 2 if clearance < CAPACITY_DERATE_CLEARANCE_M else seat_capacity
    crew_cap = seat_capacity if crew["endorsement_class"] == "MASTER_100T" else CREW_LIMITED_CAP
    core = min(posture_cap, tide_cap, crew_cap)
    if (day["posture"] == "NORMAL"
            and day.get("event_name") is not None
            and day.get("expected_attendance", 0) >= SURGE_ELEVATED_FLOOR):
        bonus = SURGE_STANDING_BONUS
    else:
        bonus = 0
    return min(core + bonus, seat_capacity + SURGE_STANDING_BONUS)


def recompute_seats_committed(trip):
    total = 0
    for booking in store.bookings.values():
        if booking["trip_id"] == trip["id"] and booking["status"] in ("CONFIRMED", "BOARDED"):
            total += booking["party_size"]
    trip["seats_committed"] = total
    return total


# ---- Fares and passes -----------------------------------------------------

def zone_span(origin_stop, destination_stop):
    return abs(destination_stop["zone_index"] - origin_stop["zone_index"])


def pass_covers_span(zone_tier, span):
    limit = ZONE_TIER_SPAN[zone_tier]
    return True if limit is None else span <= limit


def booking_fare_quote(origin_stop, destination_stop, day, service_mode, party_size):
    span = zone_span(origin_stop, destination_stop)
    base_cents = ZONE_BASE_CENTS + span * ZONE_STEP_CENTS
    per_seat_after_mode = apply_bp(base_cents, MODE_MULT_BP[service_mode])
    per_seat_after_surge = apply_bp(per_seat_after_mode, day["surge_multiplier_bp"])
    return per_seat_after_surge * party_size


def rides_consumed(ride_pass):
    total = 0
    for booking in store.bookings.values():
        if booking.get("ride_pass_id") == ride_pass["id"] and booking["redemption_status"] == "REDEEMED":
            total += booking["party_size"]
    return total


def ride_pass_residual_value(ride_pass, settlement_basis):
    if settlement_basis == "PRO_RATA":
        unit = round_half_up_cents(
            Decimal(ride_pass["purchase_price_cents"]) / Decimal(ride_pass["rides_purchased"]))
        return ride_pass["rides_remaining"] * unit
    consumed = rides_consumed(ride_pass)
    retail = RETAIL_PER_RIDE_CENTS[ride_pass["zone_tier"]]
    return max(0, ride_pass["purchase_price_cents"] - consumed * retail)


# ---- Berth occupancy ------------------------------------------------------

def dock_berth_conflict(dock, start_dt, end_dt):
    """Occupancy count against the buffered windows of RESERVED/CONSUMED slots."""
    buffer_seconds = dock["min_turnaround_minutes"] * 60
    occupied = 0
    for slot in store.dock_slots.values():
        if slot["dock_id"] != dock["id"]:
            continue
        if slot["status"] not in ("RESERVED", "CONSUMED"):
            continue
        existing_start = slot["_start_dt"]
        existing_end = slot["_end_dt"]
        if start_dt.timestamp() < existing_end.timestamp() + buffer_seconds and \
                existing_start.timestamp() < end_dt.timestamp() + buffer_seconds:
            occupied += 1
    return occupied >= dock["berth_count"]


# ---- Layup overlap --------------------------------------------------------

def vessel_layup_conflict(vessel, departure_dt, arrival_dt):
    start = vessel.get("layup_start_date")
    end = vessel.get("layup_end_date")
    if start is None or end is None:
        return False
    start_d = parse_date(start)
    end_d = parse_date(end)
    if start_d is None or end_d is None:
        return False
    return departure_dt.date() <= end_d and arrival_dt.date() >= start_d


# ---- Dispatch selector ----------------------------------------------------

def dispatch_candidates(booking):
    day = day_by_date(booking["requested_date"])
    if day is None:
        return []
    if day["posture"] not in ("NORMAL", "RESTRICTED"):
        return []
    now = store.clock_now()
    declined = set(booking.get("declined_trip_ids") or [])
    candidates = []
    for trip in store.trips.values():
        if trip["service_day_id"] != day["id"]:
            continue
        if trip["operational_status"] != "SCHEDULED":
            continue
        if trip["service_mode"] != booking["service_mode"]:
            continue
        if trip["origin_stop_id"] != booking["origin_stop_id"]:
            continue
        if trip["destination_stop_id"] != booking["destination_stop_id"]:
            continue
        if trip["id"] in declined:
            continue
        if trip["_departure_dt"] < now:
            continue
        remaining = trip_effective_capacity(trip) - trip["seats_committed"]
        if remaining < booking["party_size"]:
            continue
        candidates.append((trip, remaining))
    candidates.sort(key=lambda item: (item[0]["_departure_dt"], -item[1], item[0]["_seq"]))
    return [item[0] for item in candidates]
