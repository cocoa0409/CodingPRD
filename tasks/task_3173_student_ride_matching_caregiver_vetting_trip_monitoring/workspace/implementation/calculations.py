"""Business calculations.

Every rule here is transcribed from SCAFFOLD.yaml section 1.3 (Calculation
Rules Table) and the matching prose in PRD section 3.
"""

import math
import unicodedata
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import db
from clock import clock_date, now_utc, parse_date

# --- Constants (SCAFFOLD section 1.3 `constants`) ---------------------------

CAREGIVER_EXPERIENCE_MIN_MONTHS = 12
SEAT_CAPACITY_MAX = 10
VEHICLE_CLASS_SEAT_CAP = {"SEDAN": 4, "SUV": 6, "WHEELCHAIR_VAN": 8}

QUOTE_DISCREPANCY_DISCOUNT = Decimal("0.25")
FINAL_LOCKED_DISCOUNT = Decimal("0.5")
CREDIT_APPLY_PCT = Decimal("0.5")
OVERDUE_THRESHOLD_CENTS = 500000

ACADEMIC_TERM_OPEN_DATE = date(2026, 8, 15)

PROGRAM_WEIGHT = {
    "FOSTER_CARE": Decimal("3.0"),
    "HOMELESS_MCKINNEY_VENTO": Decimal("3.0"),
    "SPECIAL_EDUCATION": Decimal("2.0"),
    "GENERAL": Decimal("1.0"),
}
LATE_DISPATCH_DISCOUNT = Decimal("0.5")
NORMAL_MULTIPLIER = Decimal("1.0")
PENALTY_MULTIPLIER = Decimal("1.5")
GRADE_HIGH_MIN = Decimal("8.0")
GRADE_MEDIUM_MIN = Decimal("4.0")

WAIT_BLOCK_MINUTES = 12
WAIT_BLOCK_MAX = 5
WAIT_TIME_MIN_BLOCKS = 2

STRIKE_MEDIUM_MIN = 1
STRIKE_HIGH_MIN = 3
BREACH_MEDIUM_MIN = 2
DRIVER_SUSPENSION_STRIKE_THRESHOLD = 3

CATEGORY_WEIGHT = {
    "NO_SHOW_UNVERIFIED": Decimal("1.0"),
    "DRIVER_MISCONDUCT": Decimal("2.0"),
    "VEHICLE_UNSAFE": Decimal("2.0"),
    "HANDOFF_DISPUTE": Decimal("1.5"),
    "STUDENT_DISTRESS": Decimal("1.0"),
}
SEVERITY_WEIGHT = {"LOW": Decimal("1.0"), "MEDIUM": Decimal("2.0"), "HIGH": Decimal("3.0")}
BASE_SCORE = Decimal("25")
STRIKE_MULTIPLIER = Decimal("0.5")
OPEN_MULTIPLIER = Decimal("1.2")

PIN_LENGTH = 6
PROXIMITY_FACTOR = Decimal("1.1")
SUPPLY_STAFFED_RATIO = Decimal("0.8")
SERIES_OVERLAP_BUFFER_MINUTES = 0
AVAILABILITY_BUFFER_MINUTES = 20

NON_TERMINAL_TRIP_STATES = (
    "SCHEDULED",
    "DRIVER_EN_ROUTE",
    "AWAITING_STUDENT",
    "STUDENT_ONBOARD",
    "IN_TRANSIT",
)
IN_PROGRESS_TRIP_STATES = ("AWAITING_STUDENT", "STUDENT_ONBOARD", "IN_TRANSIT")


def round_half_up(value):
    """Round to an integer cent half up; never bank-round."""
    if isinstance(value, float):
        value = Decimal(str(value))
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_decimal(value, places):
    quant = Decimal(1).scaleb(-places)
    if isinstance(value, float):
        value = Decimal(str(value))
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def _as_dec(value):
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


# --- Derived aggregate counts (SCAFFOLD section 1.3) ------------------------

def rider_active_request_count(rider_id):
    """RideRequests in SUBMITTED or APPROVED only; trip rows never contribute."""
    return sum(
        1
        for rr in db.all_of("ride_requests")
        if rr["rider_id"] == rider_id and rr["status"] in ("SUBMITTED", "APPROVED")
    )


def district_trips_scheduled_total(district_id):
    """Every Trip whose trip_state is not CANCELLED."""
    return sum(
        1
        for t in db.all_of("trips")
        if t["district_id"] == district_id and t["trip_state"] != "CANCELLED"
    )


def driver_strike_count(driver_id):
    """At-fault adjudications plus LOCKED absence trips for the driver."""
    adjudicated = sum(
        1
        for inc in db.all_of("safety_incidents")
        if inc["driver_id"] == driver_id and inc["adjudication"] == "DRIVER_AT_FAULT"
    )
    locked_absences = sum(
        1
        for t in db.all_of("trips")
        if t["driver_id"] == driver_id
        and t["exception_code"] in ("RIDER_NOT_PRESENT", "RIDER_REFUSED_BOARDING")
        and t["safety_state"] == "LOCKED"
    )
    return adjudicated + locked_absences


def non_terminal_trip_count(driver_id):
    return sum(
        1
        for t in db.all_of("trips")
        if t["driver_id"] == driver_id and t["trip_state"] in NON_TERMINAL_TRIP_STATES
    )


# --- Driver qualification (2.4) ---------------------------------------------

def driver_approved_seat_count(driver):
    """approved_seat_count - see calculations.driver_approved_seat_count."""
    checks = [c for c in db.all_of("background_checks") if c["driver_id"] == driver["id"]]
    inspections = [i for i in db.all_of("vehicle_inspections") if i["driver_id"] == driver["id"]]
    today = clock_date()

    cleared = [c for c in checks if c["result"] == "CLEARED"]
    not_failed = [c for c in checks if c["result"] != "FAILED"]
    passed = [i for i in inspections if i["result"] == "PASSED"]

    if driver["status"] not in ("INSPECTION", "ACTIVE", "SUSPENDED"):
        return 0
    if driver["caregiver_experience_months"] < CAREGIVER_EXPERIENCE_MIN_MONTHS:
        return 0
    if len(cleared) < len(not_failed):
        return 0
    if any(parse_date(c["expires_on"]) <= today for c in checks):
        return 0
    if any(i["result"] == "FAILED" for i in inspections):
        return 0
    if not passed:
        return 0
    if any(parse_date(i["expires_on"]) <= today for i in inspections):
        return 0
    max_passed_seats = max(int(i["seat_count"]) for i in passed)
    if max_passed_seats < non_terminal_trip_count(driver["id"]):
        return 0

    result = min(int(driver["seat_capacity"]), max_passed_seats)
    return min(result, SEAT_CAPACITY_MAX)


def driver_compliance_expiry(driver):
    """compliance_expires_at - see calculations.driver_compliance_expiry."""
    checks = [c for c in db.all_of("background_checks") if c["driver_id"] == driver["id"]]
    inspections = [i for i in db.all_of("vehicle_inspections") if i["driver_id"] == driver["id"]]

    if driver["status"] in ("PENDING", "INACTIVE"):
        return None
    if any(c["result"] != "CLEARED" for c in checks):
        return None

    cleared = [c for c in checks if c["result"] == "CLEARED"]
    if not cleared:
        return None
    # The rule folds the driver's CLEARED FINGERPRINT_* rows into the min. The
    # scaffold and PRD are silent on a driver whose only clearances are of other
    # types (e.g. a COUNTY_COURT-only packet, which the qualification pipeline
    # explicitly admits), and neither documents a variant for that case. The
    # cleared-check set as a whole is used instead, so a driver who cleared the
    # documented pipeline always carries a coverage instant rather than dropping
    # silently out of the dispatch roster.
    fingerprints = [c for c in cleared if c["check_type"].startswith("FINGERPRINT_")]
    fingerprint_expiry = min(parse_date(c["expires_on"]) for c in (fingerprints or cleared))

    passed = [i for i in inspections if i["result"] == "PASSED"]
    if not passed:
        return None
    inspection_expiry = max(parse_date(i["expires_on"]) for i in passed)
    return min(fingerprint_expiry, inspection_expiry)


def recompute_driver(driver):
    """Re-propagate the two derived driver values and the strike count."""
    driver["approved_seat_count"] = driver_approved_seat_count(driver)
    expiry = driver_compliance_expiry(driver)
    driver["compliance_expires_at"] = expiry.strftime("%Y-%m-%d") if expiry else None
    driver["incident_strike_count"] = driver_strike_count(driver["id"])
    return driver


def recompute_rider(rider):
    rider["active_ride_request_count"] = rider_active_request_count(rider["id"])
    return rider


def recompute_district(district):
    district["trips_scheduled_total"] = district_trips_scheduled_total(district["id"])
    return district


# --- Trip pricing (2.8 / 3.10) ----------------------------------------------

def covering_contract(district_id):
    for c in db.all_of("contracts"):
        if c["district_id"] == district_id and c["status"] == "ACTIVE":
            return c
    return None


def trip_billable_ride_units(trip):
    """Locked in at completion: 0 unless COMPLETED, 2 with both legs passed."""
    if trip["trip_state"] != "COMPLETED":
        return 0
    handoffs = [h for h in db.all_of("handoffs") if h["trip_id"] == trip["id"]]
    pickup_passed = any(h["leg"] == "PICKUP" and h["result"] == "PASSED" for h in handoffs)
    dropoff_passed = any(h["leg"] == "DROPOFF" and h["result"] == "PASSED" for h in handoffs)
    return 2 if (pickup_passed and dropoff_passed) else 1


def trip_charge_provisional_cents(trip, contract=None):
    """Quote variant: priced from planned_miles, ignores the floor."""
    if contract is None:
        contract = covering_contract(trip["district_id"])
    if contract is None:
        return 0
    ride_component = round_half_up(_as_dec(trip["billable_ride_units"]) * contract["per_ride_rate_cents"])
    mile_component = round_half_up(_as_dec(trip["planned_miles"]) * contract["per_mile_rate_cents"])
    charge = ride_component + mile_component
    if trip["safety_state"] == "DISCREPANCY":
        charge = charge - round_half_up(Decimal(charge) * QUOTE_DISCREPANCY_DISCOUNT)
    elif trip["safety_state"] == "LOCKED":
        charge = 0
    return int(charge)


def trip_charge_final_cents(trip, contract=None):
    """Settlement variant: priced from billable_miles, floor applied last."""
    if contract is None:
        contract = covering_contract(trip["district_id"])
    if contract is None:
        return 0
    ride_component = round_half_up(_as_dec(trip["billable_ride_units"]) * contract["per_ride_rate_cents"])
    mile_component = round_half_up(_as_dec(trip["billable_miles"]) * contract["per_mile_rate_cents"])
    charge = ride_component + mile_component
    if trip["safety_state"] == "DISCREPANCY":
        charge = charge - round_half_up(Decimal(charge) * QUOTE_DISCREPANCY_DISCOUNT)
    elif trip["safety_state"] == "LOCKED":
        charge = round_half_up(Decimal(charge) * (1 - FINAL_LOCKED_DISCOUNT))
    return int(max(Decimal(charge), Decimal(contract["minimum_billable_cents"])))


def billing_period_key(scheduled_date, billing_period):
    """Period key derived from scheduled_date under the contract's billing_period."""
    if billing_period == "WEEKLY":
        iso_year, iso_week, _ = scheduled_date.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if billing_period == "SEMI_MONTHLY":
        half = "A" if scheduled_date.day <= 15 else "B"
        return f"{scheduled_date.year}-{scheduled_date.month:02d}-{half}"
    if billing_period == "MONTHLY":
        return f"{scheduled_date.year}-{scheduled_date.month:02d}"
    return None


# --- Handoff authorisation (3.8) --------------------------------------------

def _norm_name(value):
    if value is None:
        return ""
    return unicodedata.normalize("NFC", str(value)).strip().casefold()


def handoff_verification_authorization(leg, expected_party, verified_party_name,
                                       verification_method, verification_code, rider):
    adult_names = {_norm_name(a.get("name")) for a in (rider.get("authorized_adults") or [])}
    verified = _norm_name(verified_party_name)

    if leg == "PICKUP":
        if expected_party == "AUTHORIZED_ADULT":
            return verified in adult_names
        if expected_party == "PLACEMENT_WORKER":
            return verification_method == "PHYSICAL_SIGNATURE"
        return False  # SCHOOL_STAFF is never a valid releasing party at pickup

    # DROPOFF
    if verified == _norm_name(rider.get("school_name")):
        return True
    if verified in adult_names:
        if verification_method == "PIN":
            code = verification_code if verification_code is not None else ""
            return len(code) == PIN_LENGTH and code.isalnum()
        return True
    return False


# --- Recurring series allocation (3.5) --------------------------------------

def _school_day_window(rr):
    """[max(series_effective_from, clock date), series_through_date] inclusive."""
    start = parse_date(rr["series_effective_from"])
    end = parse_date(rr["series_through_date"])
    today = clock_date()
    if today > start:
        start = today
    return start, end


def recurring_allocation_count(rr):
    if not rr.get("is_recurring"):
        return 0
    if not rr.get("series_effective_from") or not rr.get("series_through_date"):
        return 0
    start, end = _school_day_window(rr)
    if start > end:
        return 0

    district = db.get("districts", rr["district_id"])
    district_excluded = set(district.get("no_school_dates") or []) if district else set()
    series_excluded = set(rr.get("series_no_school_dates") or [])
    excluded = district_excluded | series_excluded
    days = set(rr.get("days_of_week") or [])

    suppressed = set()
    for t in db.all_of("trips"):
        if t["ride_request_id"] == rr["id"] and t["trip_state"] != "CANCELLED":
            suppressed.add(t["scheduled_date"])

    count = 0
    cursor = start
    while cursor <= end:
        iso = cursor.strftime("%Y-%m-%d")
        if (iso not in excluded
                and cursor.isoweekday() in days
                and iso not in suppressed
                and cursor >= ACADEMIC_TERM_OPEN_DATE):
            count += 1
        cursor += timedelta(days=1)
    return count


def recurring_allocation_dates(rr):
    """The same included-date set, materialised as ISO date strings."""
    if not rr.get("is_recurring"):
        return []
    if not rr.get("series_effective_from") or not rr.get("series_through_date"):
        return []
    start, end = _school_day_window(rr)
    if start > end:
        return []

    district = db.get("districts", rr["district_id"])
    district_excluded = set(district.get("no_school_dates") or []) if district else set()
    series_excluded = set(rr.get("series_no_school_dates") or [])
    excluded = district_excluded | series_excluded
    days = set(rr.get("days_of_week") or [])

    suppressed = set()
    for t in db.all_of("trips"):
        if t["ride_request_id"] == rr["id"] and t["trip_state"] != "CANCELLED":
            suppressed.add(t["scheduled_date"])

    out = []
    cursor = start
    while cursor <= end:
        iso = cursor.strftime("%Y-%m-%d")
        if (iso not in excluded
                and cursor.isoweekday() in days
                and iso not in suppressed
                and cursor >= ACADEMIC_TERM_OPEN_DATE):
            out.append(iso)
        cursor += timedelta(days=1)
    return out


# --- Driver selection (3.6) -------------------------------------------------

def driver_covers_date(driver, d):
    """calculations.supply_planning_definition.covered(d, date)."""
    if driver["status"] != "ACTIVE":
        return False
    if driver["caregiver_experience_months"] < CAREGIVER_EXPERIENCE_MIN_MONTHS:
        return False
    expiry = driver.get("compliance_expires_at")
    if not expiry or parse_date(expiry) <= d:
        return False
    inspections = [i for i in db.all_of("vehicle_inspections") if i["driver_id"] == driver["id"]]
    return any(i["result"] == "PASSED" and parse_date(i["expires_on"]) > d for i in inspections)


def coverable_seats(driver, d):
    """calculations.supply_planning_definition.coverable_seats(d, date)."""
    if not driver_covers_date(driver, d):
        return int(driver["seat_capacity"])
    return max(int(driver.get("approved_seat_count") or 0), 1)


def _specialty_ok(driver, specialty):
    if specialty == "CAREGIVER_REQUIRED":
        return driver["caregiver_experience_months"] >= CAREGIVER_EXPERIENCE_MIN_MONTHS
    if specialty == "WHEELCHAIR":
        return driver["vehicle_class"] == "WHEELCHAIR_VAN"
    return True


def driver_eligible(driver, rr, d):
    """The full eligibility filter, re-checked at accept time as well."""
    if driver["status"] != "ACTIVE":
        return False
    if int(driver.get("approved_seat_count") or 0) < 1:
        return False
    if driver["caregiver_experience_months"] < CAREGIVER_EXPERIENCE_MIN_MONTHS:
        return False
    expiry = driver.get("compliance_expires_at")
    if not expiry or parse_date(expiry) <= d:
        return False
    return _specialty_ok(driver, rr.get("required_specialty", "NONE"))


def _driver_has_seat_on_date(driver, d, exclude_trip_id=None):
    """0 when the driver has no other trip whose window overlaps the date."""
    for t in db.all_of("trips"):
        if t["id"] == exclude_trip_id:
            continue
        if t["driver_id"] != driver["id"]:
            continue
        if t["scheduled_date"] != d.strftime("%Y-%m-%d"):
            continue
        if t["trip_state"] in ("COMPLETED", "CANCELLED"):
            continue
        return 1
    return 0


def dispatch_rank(rr, d, exclude_trip_id=None):
    """calculations.recurring_dispatch_rank - base then widened fallback.

    Returns the selected Driver dict or None when both passes are empty.
    Ties break on driver.created_at ascending; driver.id is never consulted.
    """
    rider = db.get("riders", rr["rider_id"])
    spi = int(rider.get("spi_level") or 1)

    base = [drv for drv in db.all_of("drivers") if driver_eligible(drv, rr, d)]
    if base:
        base.sort(key=lambda drv: (
            _driver_has_seat_on_date(drv, d, exclude_trip_id),
            int(drv.get("incident_strike_count") or 0),
            spi,
            drv["created_at"],
        ))
        return base[0]

    # vetted_provider_fallback: widen the seat requirement to >= 0 and add a
    # fourth key, compliance_expires_at DESC.
    widened = [
        drv for drv in db.all_of("drivers")
        if drv["status"] == "ACTIVE"
        and drv["caregiver_experience_months"] >= CAREGIVER_EXPERIENCE_MIN_MONTHS
        and drv.get("compliance_expires_at")
        and parse_date(drv["compliance_expires_at"]) > d
        and _specialty_ok(drv, rr.get("required_specialty", "NONE"))
    ]
    if not widened:
        return None
    widened.sort(key=lambda drv: (
        _driver_has_seat_on_date(drv, d, exclude_trip_id),
        int(drv.get("incident_strike_count") or 0),
        spi,
        _neg_date_sort(drv.get("compliance_expires_at")),
        drv["created_at"],
    ))
    return widened[0]


def _neg_date_sort(value):
    """Sort helper: descending by date, expressed as a negative ordinal."""
    if not value:
        return 0
    return -parse_date(value).toordinal()


def weighted_score(driver, rr, d, exclude_trip_id=None):
    """The dispatcher's optional numeric ordering (weighted_score variant)."""
    rider = db.get("riders", rr["rider_id"])
    spi = int(rider.get("spi_level") or 1)
    return (1000 * _driver_has_seat_on_date(driver, d, exclude_trip_id)
            + 10 * int(driver.get("incident_strike_count") or 0)
            + spi)


# --- Wait time (3.8) --------------------------------------------------------

def wait_time_block_units(trip):
    """Step decay in twelve-minute blocks; only meaningful in AWAITING_STUDENT."""
    if trip.get("trip_state") != "AWAITING_STUDENT":
        return 0
    arrived_at = trip.get("arrived_at")
    if not arrived_at:
        return 0
    from clock import parse_dt

    elapsed = (now_utc() - parse_dt(arrived_at)).total_seconds()
    elapsed_minutes = math.floor(elapsed / 60.0)
    if elapsed_minutes < 0:
        blocks = 0
    elif elapsed_minutes <= WAIT_BLOCK_MINUTES:
        blocks = 1
    else:
        blocks = 1 + (elapsed_minutes - WAIT_BLOCK_MINUTES) // WAIT_BLOCK_MINUTES
    return min(blocks, WAIT_BLOCK_MAX)


# --- Absence grading (3.8) --------------------------------------------------

def weight_for(program_type, program_weight_flat=False):
    if program_weight_flat:
        return Decimal("1.0")
    return PROGRAM_WEIGHT.get(program_type, Decimal("1.0"))


def student_absence_grade_points(trip, rider, program_weight_flat=False):
    """The (points, grade) pair behind calculations.student_absence_grade."""
    weight = weight_for(rider["program_type"], program_weight_flat)
    blocked = max(1, wait_time_block_units(trip))
    points = weight * Decimal(blocked) * (Decimal(1) + Decimal("0.5") * Decimal(int(rider.get("spi_level") or 1)))

    if trip.get("driver_id") is None:
        multiplier = LATE_DISPATCH_DISCOUNT
    elif trip.get("window_end_at") and now_utc() <= _window_end_instant(trip):
        multiplier = NORMAL_MULTIPLIER
    else:
        multiplier = PENALTY_MULTIPLIER

    points = points * multiplier
    # 1 rounding point, round_half_up to one decimal place, before grading.
    points = round_half_up_decimal(points, 1)
    if points >= GRADE_HIGH_MIN:
        grade = "HIGH"
    elif points >= GRADE_MEDIUM_MIN:
        grade = "MEDIUM"
    else:
        grade = "LOW"
    return points, grade


def student_absence_grade(trip, rider):
    return student_absence_grade_points(trip, rider)[1]


def _window_end_instant(trip):
    from clock import parse_dt

    return parse_dt(trip["window_end_at"])


# --- Alert severity (3.9) ---------------------------------------------------

def trip_alert_severity(alert, trip, district, driver):
    """calculations.trip_alert_severity - returns (severity, notify_caregiver,
    notify_school, notify_support_center)."""
    breach_count = sum(
        1
        for gc in db.all_of("geofence_checks")
        if gc["trip_id"] == alert["trip_id"] and gc["inside"] is False
    )
    strikes = int((driver or {}).get("incident_strike_count") or 0)

    alert_type = alert["alert_type"]
    if alert_type in ("HANDOFF_DISPUTE", "STUDENT_ABSENT"):
        base = "HIGH"
    else:  # GEOFENCE_BREACH and TRIP_DELAY both start LOW
        base = "LOW"

    if breach_count >= BREACH_MEDIUM_MIN:
        base = "MEDIUM"
    if strikes >= STRIKE_HIGH_MIN:
        base = "HIGH"
    elif strikes >= STRIKE_MEDIUM_MIN and base == "LOW":
        base = "MEDIUM"

    # Coordination rule: a trip already carrying an unresolved HIGH alert never
    # raises a second HIGH alert.
    if base == "HIGH":
        for other in db.all_of("trip_alerts"):
            if (other["trip_id"] == alert["trip_id"] and other["id"] != alert["id"]
                    and other["severity"] == "HIGH" and other["status"] == "OPEN"):
                base = "MEDIUM"
                break

    severity = base
    notify_caregiver = severity in ("MEDIUM", "HIGH")
    notify_school = alert_type in ("HANDOFF_DISPUTE", "STUDENT_ABSENT") or severity == "HIGH"
    enabled = bool((district or {}).get("support_center_alert_enabled", True))
    notify_support_center = (
        (severity == "HIGH" and (enabled or strikes >= STRIKE_HIGH_MIN))
        or (notify_school and alert_type == "HANDOFF_DISPUTE")
    )
    return severity, notify_caregiver, notify_school, notify_support_center


# --- Incident impact score (3.9) --------------------------------------------

def safety_incident_impact_score(incident, driver, resolved_only=False):
    category_weight = CATEGORY_WEIGHT.get(incident["category"], Decimal("1.0"))
    severity_weight = SEVERITY_WEIGHT.get(incident["severity"], Decimal("1.0"))
    strikes = int((driver or {}).get("incident_strike_count") or 0)
    open_multiplier = Decimal("1.0") if (resolved_only or incident["status"] == "RESOLVED") else OPEN_MULTIPLIER
    raw = (BASE_SCORE
           * category_weight
           * severity_weight
           * (Decimal(1) + STRIKE_MULTIPLIER * Decimal(strikes))
           * open_multiplier)
    score = round_half_up(raw)
    return max(0, min(100, score))


# --- Geofence containment (3.9) ---------------------------------------------

EARTH_RADIUS_MILES = Decimal("3958.7613")


def haversine_miles(lat1, lon1, lat2, lon2):
    lat1 = math.radians(float(lat1))
    lon1 = math.radians(float(lon1))
    lat2 = math.radians(float(lat2))
    lon2 = math.radians(float(lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return float(EARTH_RADIUS_MILES) * c


def geofence_containment(observed_lat, observed_lon, fence):
    """Full containment test; boundary inclusive at exactly radius_miles."""
    distance = haversine_miles(observed_lat, observed_lon, fence["center_lat"], fence["center_lon"])
    distance = round(distance, 3)
    radius = round(float(fence["radius_miles"]), 3)
    return distance <= radius


def proximity_containment(observed_lat, observed_lon, fence):
    """The companion proximity probe: STRICT less-than at radius * 1.1."""
    distance = haversine_miles(observed_lat, observed_lon, fence["center_lat"], fence["center_lon"])
    distance = round(distance, 3)
    radius = round(float(fence["radius_miles"]), 3) * float(PROXIMITY_FACTOR)
    return distance < round(radius, 3)


# --- Interval geometry (2.6) ------------------------------------------------

def half_open_overlap(start_a, end_a, start_b, end_b):
    """A driver interval [start, end) overlapping another; zero-minute gap allowed."""
    return start_a < end_b and start_b < end_a


def closed_overlap(start_a, end_a, start_b, end_b):
    """A rider interval [start, end] touching another; touching is a collision."""
    return start_a <= end_b and start_b <= end_a


# --- Supply plan aggregation (3.7) ------------------------------------------

def supply_plan(district_id, horizon_start, horizon_end, seated_demand_only=False):
    district = db.get("districts", district_id)
    drivers = [d for d in db.all_of("drivers")]

    per_date = {}
    shift_capacity = {}
    seats_committed = {}
    deficit = {}
    ratio = {}
    understaffed = []
    deficit_dates = []
    alerts_sent_total = 0

    cursor = horizon_start
    while cursor <= horizon_end:
        iso = cursor.strftime("%Y-%m-%d")
        covered = [d for d in drivers if driver_covers_date(d, cursor)]
        capacity = sum(coverable_seats(d, cursor) for d in covered)

        committed = 0
        for t in db.all_of("trips"):
            if t["district_id"] != district_id or t["scheduled_date"] != iso:
                continue
            if t["trip_state"] in ("COMPLETED", "CANCELLED"):
                continue
            if seated_demand_only and not t.get("driver_id"):
                continue
            committed += 1

        seat_deficit = max(0, committed - capacity)
        supply_ratio = None if capacity == 0 else float(
            round_half_up_decimal(Decimal(committed) / Decimal(capacity), 4)
        )
        sent = sum(1 for d in covered if int(d.get("incident_strike_count") or 0) >= 1)
        alerts_sent_total += sent

        shift_capacity[iso] = capacity
        seats_committed[iso] = committed
        deficit[iso] = seat_deficit
        ratio[iso] = supply_ratio
        if supply_ratio is not None and supply_ratio < float(SUPPLY_STAFFED_RATIO):
            understaffed.append(iso)
        if seat_deficit > 0:
            deficit_dates.append(iso)
        per_date[iso] = {
            "date": iso,
            "shift_capacity_on_date": capacity,
            "seats_committed_on_date": committed,
            "seat_deficit": seat_deficit,
            "supply_ratio": supply_ratio,
            "alerts_sent": sent,
        }
        cursor += timedelta(days=1)

    return {
        "district_id": district_id,
        "horizon_start": horizon_start.strftime("%Y-%m-%d"),
        "horizon_end": horizon_end.strftime("%Y-%m-%d"),
        "bell_schedule_start": (district or {}).get("bell_schedule_start"),
        "per_date": per_date,
        "shift_capacity_on_date": shift_capacity,
        "seats_committed_on_date": seats_committed,
        "seat_deficit": deficit,
        "supply_ratio": ratio,
        "underdogs_placeholder": None,
        "understaffed_dates": understaffed,
        "seat_deficit_dates": deficit_dates,
        "alerts_sent": alerts_sent_total,
    }


# --- Casualty cascades -------------------------------------------------------

def cancel_unstarted_trips_for_driver(driver_id, lock_posture=True, clear_claimed=False):
    """Cancel every SCHEDULED / DRIVER_EN_ROUTE trip for a driver."""
    cancelled = []
    for t in db.all_of("trips"):
        if t["driver_id"] != driver_id:
            continue
        if t["trip_state"] not in ("SCHEDULED", "DRIVER_EN_ROUTE"):
            continue
        t["trip_state"] = "CANCELLED"
        t["driver_id"] = None
        t["candidate_driver_id"] = None
        if clear_claimed:
            t["claimed_by_user_id"] = None
            t["accepted_at"] = None
        if lock_posture:
            t["safety_state"] = "LOCKED"
        db.bump_version(t)
        cancelled.append(t)
    for t in cancelled:
        district = db.get("districts", t["district_id"])
        if district:
            recompute_district(district)
    return cancelled


def maybe_suspend_driver(driver):
    """The ACTIVE -> SUSPENDED cascade once strikes reach the threshold."""
    if int(driver.get("incident_strike_count") or 0) < DRIVER_SUSPENSION_STRIKE_THRESHOLD:
        return False
    if driver["status"] != "ACTIVE":
        return False
    driver["status"] = "SUSPENDED"
    db.bump_version(driver)
    cancel_unstarted_trips_for_driver(driver["id"], lock_posture=True, clear_claimed=True)
    return True


def maybe_reactivate_driver(driver):
    """The compensating action: below threshold and suspended returns to ACTIVE."""
    if (int(driver.get("incident_strike_count") or 0) < DRIVER_SUSPENSION_STRIKE_THRESHOLD
            and driver["status"] == "SUSPENDED"):
        driver["status"] = "ACTIVE"
        db.bump_version(driver)
        return True
    return False


def expire_overdue_contracts(district):
    """Automatic contract expiry that runs during a billing run."""
    today = clock_date()
    changed = False
    for c in db.all_of("contracts"):
        if c["district_id"] != district["id"]:
            continue
        if c["status"] == "ACTIVE" and parse_date(c["through_date"]) < today:
            c["status"] = "EXPIRED"
            db.bump_version(c)
            district["account_status"] = "SUSPENDED"
            changed = True
    return changed