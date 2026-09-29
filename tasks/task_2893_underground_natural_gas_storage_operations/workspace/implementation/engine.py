"""Derived blocks, posture, curtailment sweeps, reconciliation and the eight calculations.

Every rule here traces to PRD sections 2.6 - 2.9 and 3.1 - 3.9.
"""
from datetime import timedelta
from decimal import Decimal

import config
import store
from utils import (D, add_days, hours_between, parse_date_string, q2, q3, q4, q6,
                   round_half_up, round_int, truncate)

ZERO = Decimal("0")

DERIVED_KEYS = (
    "max_working_gas_dth",
    "inventory_pct",
    "current_pressure_psig",
    "deliverability_tier",
    "wells_in_service_count",
    "max_withdrawal_rate_dth_per_day",
    "max_injection_rate_dth_per_day",
    "field_posture",
)


# ================================================================ ledger
def add_ledger(contract, entry_type, gas_day, volume_dth, amount_usd, origin_note):
    """Append one immutable ImbalanceLedgerEntry (PRD 3.7); carries only id + created_at."""
    entry = store.new_record(with_common=False)
    entry.update({
        "contract_id": contract["id"],
        "entry_type": entry_type,
        "gas_day": gas_day,
        "volume_dth": q3(volume_dth),
        "amount_usd": q2(amount_usd),
        "origin_note": origin_note,
    })
    return store.put("ImbalanceLedgerEntry", entry)


def today_str():
    return store.today().isoformat()


def gas_day_today_or_later(gas_day):
    return gas_day >= today_str()


# ================================================================ deliverability (2.7)
def _curve_points(field):
    return field["deliverability_curve"]


def evaluate_curve(field, inventory_pct):
    """Return (withdrawal_rate, injection_rate) as integers under the field's method."""
    points = _curve_points(field)
    pct = D(inventory_pct)
    if field["deliverability_method"] == "TIER_FLOOR":
        chosen = points[0]
        for point in points:
            if D(point["inventory_pct"]) <= pct:
                chosen = point
        return int(chosen["withdrawal_dth_per_day"]), int(chosen["injection_dth_per_day"])

    low = None
    high = None
    for point in points:
        if D(point["inventory_pct"]) <= pct:
            low = point
    for point in points:
        if D(point["inventory_pct"]) >= pct:
            high = point
            break
    if low is None:
        low = points[0]
    if high is None:
        high = points[-1]
    if low is high or D(low["inventory_pct"]) == D(high["inventory_pct"]):
        return int(low["withdrawal_dth_per_day"]), int(low["injection_dth_per_day"])
    span = D(high["inventory_pct"]) - D(low["inventory_pct"])
    fraction = (pct - D(low["inventory_pct"])) / span
    withdrawal = D(low["withdrawal_dth_per_day"]) + fraction * (
        D(high["withdrawal_dth_per_day"]) - D(low["withdrawal_dth_per_day"]))
    injection = D(low["injection_dth_per_day"]) + fraction * (
        D(high["injection_dth_per_day"]) - D(low["injection_dth_per_day"]))
    return round_int(withdrawal), round_int(injection)


def deliverability_tier(inventory_pct):
    pct = D(inventory_pct)
    if pct < config.TIER_2_FLOOR_PCT:
        return "TIER_1"
    if pct < config.TIER_3_FLOOR_PCT:
        return "TIER_2"
    if pct < config.TIER_4_FLOOR_PCT:
        return "TIER_3"
    return "TIER_4"


def recompute_derived(field):
    """Steps 1-7 of PRD 2.7, in the published order, followed by the 2.6 posture chain."""
    total = D(field["total_capacity_dth"])
    cushion = D(field["cushion_gas_dth"])
    max_working = total - cushion
    field["max_working_gas_dth"] = max_working

    inventory = D(field["working_gas_inventory_dth"])
    fraction = inventory / max_working if max_working != 0 else ZERO
    field["inventory_pct"] = q2(fraction * D(100))
    field["current_pressure_psig"] = round_int(
        D(field["base_pressure_psig"]) + fraction * D(field["pressure_span_psig"]))
    field["deliverability_tier"] = deliverability_tier(field["inventory_pct"])

    in_service = [
        w for w in store.wells_of_field(field["id"])
        if w["well_type"] == "INJECTION_WITHDRAWAL" and w["operational_state"] == "IN_SERVICE"
    ]
    field["wells_in_service_count"] = len(in_service)
    mechanical = sum(int(w["rated_rate_dth_per_day"]) for w in in_service)

    curve_withdrawal, curve_injection = evaluate_curve(field, field["inventory_pct"])
    field["max_withdrawal_rate_dth_per_day"] = min(curve_withdrawal, mechanical)
    field["max_injection_rate_dth_per_day"] = min(curve_injection, mechanical)

    field["field_posture"] = derive_posture(field)
    return field


def derive_posture(field):
    """PRD 2.6: an ordered chain where the first clause that holds decides."""
    if field["wells_in_service_count"] == 0:
        return "FROZEN"
    for event in store.events_of_field(field["id"]):
        if event["status"] in ("RESPONDING", "EVACUATION_ORDERED"):
            return "FROZEN"
    for well in store.wells_of_field(field["id"]):
        if well["integrity_state"] == "MIT_FAILED":
            return "RESTRICTED"
    ceiling = round_int(D(field["max_pressure_psig"]) * config.POSTURE_PRESSURE_PCT / D(100))
    if int(field["current_pressure_psig"]) > ceiling:
        return "RESTRICTED"
    return "OPEN"


def snapshot(field):
    return {key: field.get(key) for key in DERIVED_KEYS}


def refresh_field(field, force_touch=False):
    """Recompute the derived block; a changed value is a mutation (PRD 2.12)."""
    before = snapshot(field)
    recompute_derived(field)
    after = snapshot(field)
    if force_touch or before != after:
        store.touch(field)
    return before, after


# ================================================================ reconciliation (2.9)
def _scheduled_sums(contract):
    injection = 0
    withdrawal = 0
    for nomination in store.nominations_of_contract(contract["id"]):
        if nomination["status"] not in ("CONFIRMED", "CURTAILED"):
            continue
        volume = int(nomination["confirmed_volume_dth"])
        if nomination["direction"] == "INJECTION":
            injection += volume
        else:
            withdrawal += volume
    return injection, withdrawal


def _unsettled_imbalance(contract):
    through = contract["cash_out_through_date"]
    total = ZERO
    for entry in store.ledger_of_contract(contract["id"]):
        if entry["entry_type"] != "DAILY_IMBALANCE":
            continue
        gas_day = entry["gas_day"]
        if through is not None and gas_day is not None and gas_day <= through:
            continue
        total += D(entry["volume_dth"])
    return q3(total)


def reconcile_contract(contract, force_touch=False):
    """Recompute scheduled volumes and the unsettled imbalance from their sources."""
    before = (contract["scheduled_injection_dth"], contract["scheduled_withdrawal_dth"],
              contract["imbalance_dth"])
    injection, withdrawal = _scheduled_sums(contract)
    contract["scheduled_injection_dth"] = injection
    contract["scheduled_withdrawal_dth"] = withdrawal
    contract["imbalance_dth"] = _unsettled_imbalance(contract)
    after = (contract["scheduled_injection_dth"], contract["scheduled_withdrawal_dth"],
             contract["imbalance_dth"])
    if force_touch or before != after:
        store.touch(contract)
    return contract


def reconcile_shipper(shipper, cascade=True):
    """Recompute exposure and credit standing; the boundary suspends (PRD 2.9)."""
    total = ZERO
    for contract in store.contracts_of_shipper(shipper["id"]):
        for entry in store.ledger_of_contract(contract["id"]):
            if entry["entry_type"] in ("CASH_OUT", "CASH_OUT_REVERSAL"):
                total += D(entry["amount_usd"])
    outstanding = q2(total)
    prior_status = shipper["credit_status"]
    status = "SUSPENDED" if outstanding >= D(shipper["penalty_threshold_usd"]) else "GOOD"
    changed = (outstanding != D(shipper["outstanding_penalty_usd"])) or (status != prior_status)
    shipper["outstanding_penalty_usd"] = outstanding
    shipper["credit_status"] = status
    if changed:
        store.touch(shipper)
    if not cascade or status == prior_status:
        return shipper
    if status == "SUSPENDED":
        suspend_shipper_contracts(shipper)
    else:
        restore_shipper_contracts(shipper)
    return shipper


def suspend_shipper_contracts(shipper):
    """PRD 3.7: every ACTIVE contract suspends; unstarted nominations die; the rest curtail."""
    for contract in store.sorted_rows(store.contracts_of_shipper(shipper["id"])):
        if contract["status"] != "ACTIVE":
            continue
        contract["status"] = "SUSPENDED"
        store.touch(contract)
        for nomination in store.sorted_rows(store.nominations_of_contract(contract["id"])):
            if nomination["status"] in ("DRAFT", "SUBMITTED"):
                nomination["status"] = "REJECTED"
                store.touch(nomination)
    phase_a_credit(shipper)


def restore_shipper_contracts(shipper):
    """PRD 3.7: credit restoration returns SUSPENDED contracts to ACTIVE; schedules stay dead."""
    for contract in store.sorted_rows(store.contracts_of_shipper(shipper["id"])):
        if contract["status"] == "SUSPENDED":
            contract["status"] = "ACTIVE"
            store.touch(contract)


# ================================================================ curtailment (2.8)
def _eligible_for_sweep(nomination):
    if nomination["status"] != "CONFIRMED":
        return False
    if not gas_day_today_or_later(nomination["gas_day"]):
        return False
    if store.has_confirmed_ticket(nomination["id"]):
        return False
    return True


def curtail_nomination(nomination, origin_note):
    """Curtail in full, write the credit entry, reconcile and bump the owning contract."""
    prior_confirmed = int(nomination["confirmed_volume_dth"])
    nomination["confirmed_volume_dth"] = 0
    nomination["curtailed_volume_dth"] = int(nomination["nominated_volume_dth"])
    nomination["status"] = "CURTAILED"
    store.touch(nomination)
    contract = store.contracts[nomination["contract_id"]]
    add_ledger(contract, "CURTAILMENT_CREDIT", nomination["gas_day"],
               -D(prior_confirmed), ZERO, origin_note)
    reconcile_contract(contract, force_touch=True)
    return nomination


def phase_a_posture(field, posture, origin_note):
    """Phase A: FROZEN takes firm and interruptible alike, RESTRICTED only interruptible."""
    candidates = []
    for nomination in store.nominations_of_field(field["id"]):
        if not _eligible_for_sweep(nomination):
            continue
        contract = store.contracts[nomination["contract_id"]]
        if posture == "RESTRICTED" and contract["service_class"] != "INTERRUPTIBLE":
            continue
        candidates.append(nomination)
    for nomination in sorted(candidates, key=lambda n: (n["gas_day"], n["created_at"], n["_seq"])):
        curtail_nomination(nomination, origin_note)
    return candidates


def phase_a_credit(shipper):
    """Phase A in its credit-suspension form: every contract of the suspended shipper."""
    candidates = []
    for contract in store.contracts_of_shipper(shipper["id"]):
        for nomination in store.nominations_of_contract(contract["id"]):
            if _eligible_for_sweep(nomination):
                candidates.append(nomination)
    for nomination in sorted(candidates, key=lambda n: (n["gas_day"], n["created_at"], n["_seq"])):
        curtail_nomination(nomination, "credit suspension %s" % today_str())
    return candidates


def phase_a_season(field, new_season):
    """Phase A in its seasonal form: interruptible nominations against the new season."""
    candidates = []
    for nomination in store.nominations_of_field(field["id"]):
        if not _eligible_for_sweep(nomination):
            continue
        contract = store.contracts[nomination["contract_id"]]
        if contract["service_class"] != "INTERRUPTIBLE":
            continue
        if nomination["direction"] == new_season:
            continue
        candidates.append(nomination)
    for nomination in sorted(candidates, key=lambda n: (n["gas_day"], n["created_at"], n["_seq"])):
        curtail_nomination(nomination, "season turn %s" % today_str())
    return candidates


def _rate_for(field, direction):
    if direction == "INJECTION":
        return int(field["max_injection_rate_dth_per_day"])
    return int(field["max_withdrawal_rate_dth_per_day"])


def phase_b(field, before, after, origin_note):
    """Phase B: shed interruptible volume, newest first, until each gas day fits."""
    directions = []
    if int(after["max_injection_rate_dth_per_day"]) < int(before["max_injection_rate_dth_per_day"]):
        directions.append("INJECTION")
    if int(after["max_withdrawal_rate_dth_per_day"]) < int(before["max_withdrawal_rate_dth_per_day"]):
        directions.append("WITHDRAWAL")
    if not directions:
        return []
    swept = []
    field_nominations = store.nominations_of_field(field["id"])
    for direction in directions:
        rate = _rate_for(field, direction)
        gas_days = sorted({
            n["gas_day"] for n in field_nominations
            if n["direction"] == direction and n["status"] == "CONFIRMED"
            and gas_day_today_or_later(n["gas_day"])
        })
        for gas_day in gas_days:
            while True:
                day_rows = [
                    n for n in store.nominations_of_field(field["id"])
                    if n["direction"] == direction and n["gas_day"] == gas_day
                    and n["status"] == "CONFIRMED"
                ]
                total = sum(int(n["confirmed_volume_dth"]) for n in day_rows)
                if total <= rate:
                    break
                candidates = [
                    n for n in day_rows
                    if store.contracts[n["contract_id"]]["service_class"] == "INTERRUPTIBLE"
                    and not store.has_confirmed_ticket(n["id"])
                ]
                if not candidates:
                    break
                candidates.sort(key=lambda n: (
                    n["created_at"], n["_seq"]), reverse=True)
                newest = candidates[0]["created_at"]
                tied = [n for n in candidates if n["created_at"] == newest]
                if len(tied) > 1:
                    tied.sort(key=lambda n: store.contracts[n["contract_id"]]["contract_code"])
                    victim = tied[0]
                else:
                    victim = candidates[0]
                curtail_nomination(victim, origin_note)
                swept.append(victim)
    return swept


def run_sweeps(field, before, after, origin_note):
    """Phase A when the posture moved into RESTRICTED/FROZEN, otherwise phase B."""
    posture_before = before["field_posture"]
    posture_after = after["field_posture"]
    if posture_after in ("RESTRICTED", "FROZEN") and posture_after != posture_before:
        return phase_a_posture(field, posture_after, origin_note)
    return phase_b(field, before, after, origin_note)


# ================================================================ compressor fuel (3.3)
def utilization_band(ratio):
    value = D(ratio)
    if value < config.UTIL_MID_FLOOR:
        return "LOW"
    if value < config.UTIL_HIGH_FLOOR:
        return "MID"
    return "HIGH"


def run_booking_figures(unit, window_start, window_end, allocated_horsepower):
    duration = q4(hours_between(window_start, window_end))
    effective = q2(D(allocated_horsepower) * (Decimal("1") - D(unit["derate_factor"])))
    ratio = q6(effective / D(unit["rated_horsepower"]))
    return duration, effective, ratio, utilization_band(ratio)


_BAND_RATES = {
    "LOW": config.FUEL_RATE_LOW,
    "MID": config.FUEL_RATE_MID,
    "HIGH": config.FUEL_RATE_HIGH,
}


def compressor_fuel_burn(run):
    """Band rate x mode multiplier, clamped high then low, rounded to 2 dp (PRD 3.3)."""
    band_rate = _BAND_RATES[run["utilization_band"]]
    mode_multiplier = (config.FUEL_MODE_INJECTION if run["mode"] == "INJECTION"
                       else config.FUEL_MODE_WITHDRAWAL)
    raw = D(run["effective_horsepower"]) * D(run["duration_hours"]) * band_rate * mode_multiplier
    clamped = min(raw, config.MAX_FUEL_PER_RUN_DTH)
    clamped = max(config.MIN_FUEL_PER_RUN_DTH, clamped)
    return q2(clamped)


# ================================================================ ticket charges (3.6)
def ticket_charge_breakdown(actual_volume_dth, direction, contract):
    """The pinned six steps; the discount tier is read from the commodity charge alone."""
    actual = D(actual_volume_dth)
    fuel_retention = q3(actual * config.FUEL_RETENTION_PCT / D(100))
    if direction == "INJECTION":
        net_volume = q3(actual - fuel_retention)
    else:
        net_volume = q3(actual + fuel_retention)
    commodity_charge = q2(actual * D(contract["commodity_rate_usd_per_dth"]))
    if commodity_charge < config.DISCOUNT_TIER_1_USD:
        discount_pct = ZERO
    elif commodity_charge < config.DISCOUNT_TIER_2_USD:
        discount_pct = config.DISCOUNT_TIER_1_PCT
    else:
        discount_pct = config.DISCOUNT_TIER_2_PCT
    volume_discount = q2(commodity_charge * discount_pct / D(100))
    fuel_charge = q2(fuel_retention * D(contract["index_price_usd_per_dth"]))
    total_charge = q2(commodity_charge - volume_discount + fuel_charge)
    return {
        "fuel_retention_dth": fuel_retention,
        "net_volume_dth": net_volume,
        "commodity_charge_usd": commodity_charge,
        "volume_discount_usd": volume_discount,
        "fuel_charge_usd": fuel_charge,
        "total_charge_usd": total_charge,
    }


# ================================================================ allocation waterfall (3.5)
def nomination_confirm_waterfall(nomination, contract, field):
    direction = nomination["direction"]
    nominated = int(nomination["nominated_volume_dth"])
    field_ceiling = _rate_for(field, direction)

    if direction == "INJECTION":
        daily_right = D(contract["max_daily_injection_dth"])
        room = D(contract["max_storage_quantity_dth"]) - D(contract["inventory_balance_dth"])
    else:
        daily_right = D(contract["max_daily_withdrawal_dth"])
        room = D(contract["inventory_balance_dth"])
    bucket = truncate(min(D(nominated), daily_right, room))

    firm_sum = 0
    interruptible_sum = 0
    for other in store.nominations_of_field(field["id"]):
        if other["id"] == nomination["id"]:
            continue
        if other["gas_day"] != nomination["gas_day"] or other["direction"] != direction:
            continue
        if other["status"] not in ("CONFIRMED", "CURTAILED"):
            continue
        other_contract = store.contracts[other["contract_id"]]
        if other_contract["service_class"] == "FIRM":
            firm_sum += int(other["confirmed_volume_dth"])
        else:
            interruptible_sum += int(other["confirmed_volume_dth"])

    headroom = field_ceiling - firm_sum - interruptible_sum
    if contract["service_class"] == "INTERRUPTIBLE":
        share_cap = truncate(D(field_ceiling) * config.INTERRUPTIBLE_SHARE_PCT / D(100))
        headroom = min(headroom, share_cap - interruptible_sum)
    confirmed = max(0, min(bucket, headroom))
    return confirmed, nominated - confirmed


# ================================================================ cash-out (3.7)
def penalty_multiplier(percentage):
    value = D(percentage)
    if value <= config.PENALTY_BAND_1_PCT:
        return config.PENALTY_MULT_T1
    if value <= config.PENALTY_BAND_2_PCT:
        return config.PENALTY_MULT_T2
    return config.PENALTY_MULT_T3


def _tolerance(scheduled_volume):
    return q3(D(scheduled_volume) * config.IMBALANCE_TOLERANCE_PCT / D(100))


def _percentage(billable, scheduled_volume):
    scheduled = D(scheduled_volume)
    if scheduled == 0:
        return ZERO if D(billable) == 0 else config.PENALTY_BAND_2_PCT + D(1)
    return q4(D(billable) / scheduled * D(100))


def cash_out_scope(contract, period_start, period_end):
    """The in-scope DAILY_IMBALANCE entries: inside the period and after the settled date."""
    through = contract["cash_out_through_date"]
    rows = []
    for entry in store.ledger_of_contract(contract["id"]):
        if entry["entry_type"] != "DAILY_IMBALANCE" or entry["gas_day"] is None:
            continue
        if entry["gas_day"] < period_start or entry["gas_day"] > period_end:
            continue
        if through is not None and entry["gas_day"] <= through:
            continue
        rows.append(entry)
    return rows


def _scheduled_for_day(contract, gas_day):
    total = 0
    for nomination in store.nominations_of_contract(contract["id"]):
        if nomination["gas_day"] != gas_day or nomination["status"] == "SUPERSEDED":
            continue
        total += int(nomination["confirmed_volume_dth"])
    return total


def imbalance_cash_out(contract, entries):
    """MONTHLY_AGGREGATE nets the period then prices once; DAILY_RATCHET rounds per day."""
    days = sorted({entry["gas_day"] for entry in entries})
    day_imbalance = {}
    for entry in entries:
        day_imbalance[entry["gas_day"]] = day_imbalance.get(entry["gas_day"], ZERO) + D(
            entry["volume_dth"])
    index_price = D(contract["index_price_usd_per_dth"])

    if contract["cash_out_method"] == "MONTHLY_AGGREGATE":
        scheduled_total = sum(_scheduled_for_day(contract, day) for day in days)
        net = ZERO
        for day in days:
            net += day_imbalance[day]
        tolerance = _tolerance(scheduled_total)
        billable = abs(net) - tolerance
        if billable < 0:
            billable = ZERO
        percentage = _percentage(billable, scheduled_total)
        multiplier = penalty_multiplier(percentage)
        return q2(billable * index_price * multiplier)

    assessment = ZERO
    for day in days:
        scheduled = _scheduled_for_day(contract, day)
        tolerance = _tolerance(scheduled)
        billable = abs(day_imbalance[day]) - tolerance
        if billable < 0:
            billable = ZERO
        percentage = _percentage(billable, scheduled)
        multiplier = penalty_multiplier(percentage)
        assessment += q2(billable * index_price * multiplier)
    return q2(assessment)


# ================================================================ report variance (3.9)
def open_finding_count(field_id):
    return len([p for p in store.programs_of_field(field_id)
                if p["status"] in ("OPEN", "ESCALATED")])


def report_variance(field, measured_inventory_dth):
    book = q3(D(field["working_gas_inventory_dth"]))
    variance = q3(D(measured_inventory_dth) - book)
    if book == 0:
        variance_pct = ZERO if variance == 0 else q4(config.MAX_REPORT_VARIANCE_PCT + D(100))
    else:
        variance_pct = q4(abs(variance) / book * D(100))
    return book, variance, variance_pct


# ================================================================ scheduling conflicts
def mit_window_conflict(well_id, start, end, exclude_id=None):
    """Rung 24: each existing SCHEDULED window padded by MIT_BUFFER_HOURS on both sides."""
    buffer_delta = timedelta(hours=config.MIT_BUFFER_HOURS)
    for test in store.mits_of_well(well_id):
        if test["status"] != "SCHEDULED" or test["id"] == exclude_id:
            continue
        existing_start = test["scheduled_start_at"]
        existing_end = test["scheduled_end_at"]
        if start < existing_end + buffer_delta and existing_start < end + buffer_delta:
            return True
    return False


def horsepower_oversubscribed(unit, start, end, allocated):
    """Rung 25: the busiest instant inside the new half-open window must still fit."""
    rated = int(unit["rated_horsepower"])
    overlapping = [
        run for run in store.runs_of_unit(unit["id"])
        if run["status"] in ("SCHEDULED", "COMPLETED")
        and run["window_start_at"] < end and start < run["window_end_at"]
    ]
    instants = [start] + [run["window_start_at"] for run in overlapping
                          if run["window_start_at"] > start]
    peak = 0
    for instant in instants:
        concurrent = sum(
            int(run["allocated_horsepower"]) for run in overlapping
            if run["window_start_at"] <= instant < run["window_end_at"])
        peak = max(peak, concurrent)
    return peak + int(allocated) > rated
