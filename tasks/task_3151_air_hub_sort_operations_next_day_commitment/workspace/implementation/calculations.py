"""Every derived quantity in the system (SCAFFOLD 1.3 / PRD 2.7, 3.x)."""

from decimal import Decimal, ROUND_HALF_UP

# --- pinned constants registry (calculations.hub_sort_constants) --------------
SERVICE_DOWNGRADE_LEAD_MINUTES = 30
COMMITMENT_GRACE_MINUTES = 60
SECONDARY_STAGE_BUDGET_MINUTES = 60
IRREGULAR_RESOLVE_BUDGET_MINUTES = 45
REROUTE_ASSURANCE_BUFFER_MINUTES = 360
NORMAL_REROUTE_BUFFER_MINUTES = 240
GROUND_DOWNGRADE_SLIP_MINUTES = 1440
BREACH_TOLERANCE_GRAMS = 25000
CONTAINER_FILL_TOLERANCE_GRAMS = 5000
SORT_BUDGET_GRAMS_CEILING = 350000
SORT_BUDGET_GRAMS_FLOOR = -20000
USE_IT_OR_LOSE_IT_TOLERANCE_GRAMS = 10000
DEFAULT_UNLOAD_BUDGET_MINUTES = 45

SECOND_DAY_SLIP_MINUTES = 1440
GROUND_SLIP_MINUTES = 2880

DIM_MINIMUM_GRAMS = 2000
RATE_ROUNDING_GRAMS = 100

CONGESTED_GRAMS_PER_WINDOW_MINUTE = 2000
LOCKDOWN_GRAMS_PER_WINDOW_MINUTE = 5000

LABOR_OVERRUN_VARIANCE_PCT = Decimal("0.15")
LABOR_UNDERSTAFF_VARIANCE_PCT = Decimal("0.10")

FEEDER_DEPART_TOLERANCE_PCT = Decimal("0.95")

MBG_NEXT_DAY_CENTS_PER_KG = 550
MBG_SECOND_DAY_CENTS_PER_KG = 300
MBG_GROUND_CENTS_PER_KG = 140
MBG_PERISHABLE_SURCHARGE_CENTS = 250
MBG_PROVISIONAL_PCT = Decimal("0.70")

CONCOURSE_MERGE_CREDIT_MINUTES = 4

GROUND_DOWNGRADE_EXTENSION_MINUTES = 1800

ATTRIBUTION = {
    "LATE_INBOUND": "CARRIER",
    "SORT_MISS": "CARRIER",
    "NO_SCAN": "CARRIER",
    "BAD_ADDRESS": "CUSTOMER",
    "REVENUE_PRORATE": "CUSTOMER",
    "WEATHER": "WEATHER_EVENT",
    "MECHANICAL": "MECHANICAL_EVENT",
}

SERVICE_LEVEL_RANKS = {"NEXT_DAY_AIR": 0, "SECOND_DAY_AIR": 1, "GROUND": 2}


def round_half_up(value, places=0):
    """Decimal ROUND_HALF_UP, never banker's rounding."""
    quant = Decimal(1).scaleb(-places)
    return int(Decimal(value).quantize(quant, rounding=ROUND_HALF_UP))


def rated_sort_weight(planned_weight_grams, dimension_weight_grams):
    raw = max(int(planned_weight_grams), int(dimension_weight_grams), DIM_MINIMUM_GRAMS)
    return round_half_up(Decimal(raw) / Decimal(RATE_ROUNDING_GRAMS)) * RATE_ROUNDING_GRAMS


def commitment_cutoff_minutes(service_level, hub):
    close = int(hub["sort_window_close_minutes"])
    if service_level == "NEXT_DAY_AIR":
        return close
    if service_level == "SECOND_DAY_AIR":
        return close + SECOND_DAY_SLIP_MINUTES
    return close + GROUND_SLIP_MINUTES


# --- hub volume, posture, cascade -------------------------------------------

def live_planned_package_total(store, hub_id):
    total = 0
    for pkg in store.all("packages"):
        if pkg.get("hub_id") != hub_id:
            continue
        if pkg.get("handling_status") in ("DIVERTED", "HOLD_AT_HUB"):
            continue
        if pkg.get("commitment_status") in ("VOIDED", "UPGRADED_HELD"):
            continue
        total += int(pkg.get("planned_weight_grams") or 0)
    return total


def sort_window_minutes(hub):
    return int(hub["sort_window_close_minutes"]) - int(hub["sort_window_open_minutes"])


def posture_from_volume(hub, live_total):
    window = sort_window_minutes(hub)
    congestion = window * CONGESTED_GRAMS_PER_WINDOW_MINUTE
    lockdown = window * LOCKDOWN_GRAMS_PER_WINDOW_MINUTE
    if live_total >= lockdown:
        return "LOCKDOWN"
    if live_total > congestion:
        return "CONGESTED"
    return "OPEN"


def clear_volume_override(hub):
    """A package mutation recomputes the total in the ordinary way."""
    hub.pop("_volume_override", None)


def recompute_hub(store, hub):
    """Recompute the live planning volume and the hub posture.

    GROUND_STOP is never produced here; it is only ever set explicitly.
    """
    override = hub.get("_volume_override")
    if override is None:
        live = live_planned_package_total(store, hub["id"])
    else:
        live = int(override)
    if hub.get("posture") == "GROUND_STOP":
        posture = "GROUND_STOP"
    elif hub.get("contingency_mode"):
        posture = "LOCKDOWN"
    else:
        posture = posture_from_volume(hub, live)
    hub["live_planned_package_total"] = live
    hub["posture"] = posture
    return hub


def recompute_hub_full(store, hub):
    """Hub volume + posture + every labour shift on the hub."""
    recompute_hub(store, hub)
    for shift in store.all("shifts"):
        if shift.get("hub_id") == hub["id"]:
            recompute_shift(store, hub, shift)
    return hub


# --- arrival bank ------------------------------------------------------------

def effective_sort_budget(store, hub, bank):
    if bank.get("status") in ("CLOSED", "ABANDONED"):
        return 0
    # PRD 3.2: the sum runs over every live aircraft, and UNLOADED is explicitly
    # one of the live statuses.  Only CLOSED/ABANDONED banks read zero outright;
    # a bank whose every aircraft is CANCELLED reads zero through the clamp below.
    aircraft = [ac for ac in store.all("aircraft") if ac.get("bank_id") == bank["id"]]
    start = bank.get("actual_start_minutes")
    if start is None:
        cap = DEFAULT_UNLOAD_BUDGET_MINUTES
    else:
        cap = min(DEFAULT_UNLOAD_BUDGET_MINUTES,
                  max(0, int(hub["sort_window_close_minutes"]) - int(start)))
    minutes = 0
    for ac in aircraft:
        if ac.get("status") not in ("SCHEDULED", "IN_FLIGHT", "LANDED", "UNLOADING", "UNLOADED"):
            continue
        actual = ac.get("actual_arrival_minutes")
        scheduled = ac.get("scheduled_arrival_minutes")
        slack = 0
        if actual is not None and scheduled is not None:
            slack = min(max(int(actual) - int(scheduled), 0), cap)
        ac["unload_slack_minutes"] = slack
        minutes += DEFAULT_UNLOAD_BUDGET_MINUTES - slack
    return max(0, minutes)


def recompute_bank(store, hub, bank):
    bank["effective_sort_budget_minutes"] = effective_sort_budget(store, hub, bank)
    return bank


# --- sort lanes --------------------------------------------------------------

def sort_lane_load(store, lane):
    total = 0
    for pkg in store.all("packages"):
        if pkg.get("assigned_lane_id") != lane["id"]:
            continue
        if pkg.get("sort_status") in ("PRIMARY_SORTED", "SECONDARY_SORTED"):
            total += int(pkg.get("rated_weight_grams") or 0)
    return total


def recompute_lane(store, lane):
    lane["lane_load_grams"] = sort_lane_load(store, lane)
    if lane.get("status") != "CLOSED":
        if lane["lane_load_grams"] >= int(lane["capacity_weight_grams"]):
            lane["status"] = "SATURATED"
        else:
            lane["status"] = "AVAILABLE"
    store.touch("lanes", lane)
    return lane


def concourse_width(store, hub_id, lane_kind):
    intervals = []
    for lane in store.all("lanes"):
        if lane.get("hub_id") != hub_id or lane.get("lane_kind") != lane_kind:
            continue
        if lane.get("status") == "CLOSED":
            continue
        intervals.append((int(lane["turnout_start_minutes"]), int(lane["turnout_end_minutes"])))
    intervals.sort(key=lambda iv: (iv[0], iv[1]))
    merged = 0
    for first, second in zip(intervals, intervals[1:]):
        if second[0] <= first[1]:
            merged += second[1] - first[1]
    return {
        "concourse_width_rating": merged * CONCOURSE_MERGE_CREDIT_MINUTES,
        "merged_minutes": merged,
        "lane_count": len(intervals),
    }


# --- load moves and buildups -------------------------------------------------

def move_members(store, move_id):
    out = []
    for pkg in store.all("packages"):
        if store.move_of(pkg["id"]) != move_id:
            continue
        if pkg.get("commitment_status") == "VOIDED":
            continue
        out.append(pkg)
    return out


def recompute_move(store, move):
    """Pinned order: tier from the raw value, display from the floored value."""
    members = move_members(store, move["id"])
    planned = sum(int(p.get("planned_weight_grams") or 0) for p in members)
    loaded = sum(int(p.get("planned_weight_grams") or 0)
                 for p in members if p.get("sort_status") == "LOADED")
    raw = int(move["weight_limit_grams"]) - planned
    if raw > 0:
        tier = "UNDER_CAPACITY"
    elif raw == 0:
        tier = "AT_CAPACITY"
    else:
        tier = "RESERVE_TIER"
    move["planned_weight_grams"] = planned
    move["loaded_weight_grams"] = loaded
    move["forward_capacity_grams"] = max(0, raw)
    move["load_plan_tier"] = tier
    move["_raw_forward_grams"] = raw
    return move


def buildup_tier(delta_grams):
    if delta_grams <= 0:
        return "UNDER_CAPACITY"
    if delta_grams <= BREACH_TOLERANCE_GRAMS:
        return "AT_CAPACITY"
    return "RESERVE_TIER"


def recompute_buildup(store, buildup):
    rated = 0
    hazardous = 0
    hazardous_load = False
    for pkg in store.all("packages"):
        if pkg.get("buildup_id") != buildup["id"]:
            continue
        if pkg.get("commitment_status") == "VOIDED":
            continue
        weight = int(pkg.get("rated_weight_grams") or 0)
        rated += weight
        if pkg.get("commodity_class") == "HAZMAT":
            hazardous += weight
            hazardous_load = True
    buildup["rated_weight_grams"] = rated
    buildup["hazardous_weight_grams"] = hazardous
    buildup["hazardous_load"] = hazardous_load
    delta = rated - int(buildup["container_limit_grams"])
    buildup["load_plan_tier"] = buildup_tier(delta)
    if delta > BREACH_TOLERANCE_GRAMS:
        if buildup.get("status") == "OPEN":
            buildup["status"] = "WEIGHT_BREACH"
    elif buildup.get("status") == "WEIGHT_BREACH":
        buildup["status"] = "OPEN"
    return buildup


def buildup_delta(buildup):
    return int(buildup.get("rated_weight_grams") or 0) - int(buildup["container_limit_grams"])


# --- ground feeders ----------------------------------------------------------

def feeder_staged_weight(store, feeder):
    total = 0
    for pkg in store.all("packages"):
        if pkg.get("staged_feeder_id") != feeder["id"]:
            continue
        if pkg.get("commitment_status") == "VOIDED":
            continue
        total += int(pkg.get("planned_weight_grams") or 0)
    return total


def recompute_feeder(store, feeder):
    feeder["staged_weight_grams"] = feeder_staged_weight(store, feeder)
    return feeder


def feeder_depart_ceiling(stage_capacity_grams):
    return int(Decimal(int(stage_capacity_grams)) * FEEDER_DEPART_TOLERANCE_PCT)


# --- labor shifts ------------------------------------------------------------

def shift_duration_minutes(shift):
    return (int(shift["end_minutes"]) - int(shift["start_minutes"]) + 1440) % 1440


def shift_contains(shift, minute):
    start = int(shift["start_minutes"])
    end = int(shift["end_minutes"])
    if start < end:
        return start <= minute < end
    if start > end:
        return minute >= start or minute < end
    return False


def volume_variance_pct(live_total, forecast_volume_grams):
    forecast = int(forecast_volume_grams or 0)
    if forecast == 0:
        return Decimal("0.0000")
    value = (Decimal(live_total) - Decimal(forecast)) / Decimal(forecast)
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def shift_capacity_grams(shift):
    duration = shift_duration_minutes(shift)
    return int(Decimal(int(shift["headcount"]))
               * Decimal(int(shift["productivity_grams_per_operator_hour"]))
               * (Decimal(duration) / Decimal(60)))


def staffing_posture_for(live_total, shift):
    variance = volume_variance_pct(live_total, shift["forecast_volume_grams"])
    capacity = shift_capacity_grams(shift)
    if live_total > capacity:
        return variance, "RED"
    if variance >= LABOR_OVERRUN_VARIANCE_PCT:
        return variance, "SATURATED"
    if abs(variance) < LABOR_UNDERSTAFF_VARIANCE_PCT:
        return variance, "GREEN"
    return variance, "AMBER"


def recompute_shift(store, hub, shift):
    live = live_planned_package_total(store, hub["id"])
    variance, posture = staffing_posture_for(live, shift)
    shift["volume_variance_pct"] = float(variance)
    shift["staffing_posture"] = posture
    if shift_contains(shift, store.minute()) and shift.get("status") not in ("CANCELLED", "COMPLETED"):
        shift["status"] = "OVERRUN" if posture == "SATURATED" else "SCHEDULED"
    return shift


def containing_shift(store, hub, minute):
    for shift in store.all("shifts"):
        if shift.get("hub_id") != hub["id"]:
            continue
        if shift.get("status") in ("CANCELLED", "COMPLETED"):
            continue
        if shift_contains(shift, minute):
            return shift
    return None


# --- service failures --------------------------------------------------------

def money_back_gross_cents(package, service_level):
    if service_level == "NEXT_DAY_AIR":
        rate = MBG_NEXT_DAY_CENTS_PER_KG
    elif service_level == "SECOND_DAY_AIR":
        rate = MBG_SECOND_DAY_CENTS_PER_KG
    else:
        rate = MBG_GROUND_CENTS_PER_KG
    gross = round_half_up(Decimal(int(package["planned_weight_grams"])) / Decimal(1000) * Decimal(rate))
    if package.get("commodity_class") == "PERISHABLE":
        gross += MBG_PERISHABLE_SURCHARGE_CENTS
    return gross


def money_back_refund(store, failure):
    if failure.get("attributed_role") != "CARRIER":
        return 0
    package = store.get("packages", failure.get("package_id"))
    if not package:
        return 0
    gross = money_back_gross_cents(package, package.get("service_level"))
    if failure.get("status") == "OPEN":
        return round_half_up(Decimal(gross) * MBG_PROVISIONAL_PCT)
    return gross


def refund_batch_total(store, hub_id):
    """Round EACH failure first, THEN sum — never sum then round once."""
    total = 0
    for failure in store.all("failures"):
        if failure.get("hub_id") != hub_id:
            continue
        if failure.get("attributed_role") != "CARRIER":
            continue
        total += money_back_refund(store, failure)
    return total


def refund_summary(store, hub_id):
    total = 0
    eligible = 0
    provisional = 0
    for failure in store.all("failures"):
        if failure.get("hub_id") != hub_id:
            continue
        if failure.get("attributed_role") != "CARRIER":
            continue
        eligible += 1
        if failure.get("status") == "OPEN":
            provisional += 1
        total += money_back_refund(store, failure)
    return {
        "batch_total_cents": total,
        "eligible_failure_count": eligible,
        "provisional_failure_count": provisional,
    }