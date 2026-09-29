"""Deposit valuation, expiry, occupancy capacity and the getaway pipeline."""

from datetime import datetime, timedelta

import calc
from store import (db, touch, parse_date, parse_instant, format_instant, format_date,
                   add_days, DEPOSIT_LIFETIME_DAYS, EXTENSION_DAYS_PER_MONTH,
                   OCCUPANCY_NIGHTS_PER_DEPOSIT, COUNTED_DEPOSIT_STATUSES)
from services import ledger, resorts as resort_service


# ---------------------------------------------------------------------------
# season calendar
# ---------------------------------------------------------------------------
def bands_of(resort_id):
    rows = [b for b in db.season_bands.values() if b["resort_id"] == resort_id]
    return sorted(rows, key=lambda b: (b["created_at"], b["_seq"]))


def band_for_date(resort_id, date_text):
    """The unique SeasonBand whose closed MM-DD interval contains this date."""
    month_day = date_text[5:10]
    for band in bands_of(resort_id):
        if band["start_month_day"] <= month_day <= band["end_month_day"]:
            return band
    return None


# ---------------------------------------------------------------------------
# derived deposit facts
# ---------------------------------------------------------------------------
def occupancy_end(check_in_date_text):
    return format_date(add_days(parse_date(check_in_date_text), OCCUPANCY_NIGHTS_PER_DEPOSIT))


def expires_at(check_in_date_text, extension_months):
    day = parse_date(check_in_date_text)
    baseline = datetime(day.year, day.month, day.day)
    total_days = DEPOSIT_LIFETIME_DAYS + EXTENSION_DAYS_PER_MONTH * extension_months
    return format_instant(baseline + timedelta(days=total_days))


def sync_remaining(deposit):
    deposit["remaining_power"] = max(0, deposit["awarded_power"] - deposit["restoration_haircut_power"])
    return deposit["remaining_power"]


def is_expired(deposit, moment):
    return parse_instant(deposit["expires_at"]) <= moment


def valuation_inputs(resort, unit_size, band_code, evaluated_date_text, as_of):
    lead = (parse_date(evaluated_date_text) - as_of.date()).days
    return {
        "unit_size_base": calc.UNIT_SIZE_BASE[unit_size],
        "season_multiplier": float(calc.SEASON_MULT[band_code]),
        "demand_multiplier": float(calc.demand_multiplier(resort["demand_index"])),
        "quality_bonus": calc.QUALITY_BONUS[resort["quality_rating"]],
        "lead_time_days": lead,
        "power": calc.trading_power(unit_size, band_code, resort["demand_index"],
                                   resort["quality_rating"], lead),
    }


def settlement_value(deposit, resort, as_of):
    """The at-settlement trading power this run would use for the deposit."""
    if deposit["settlement_power"] is not None:
        return deposit["settlement_power"]
    lead = (parse_date(deposit["check_in_date"]) - as_of.date()).days
    return calc.trading_power(deposit["unit_size"], deposit["season_band_code"],
                              resort["demand_index"], resort["quality_rating"], lead)


def freeze_settlement(deposit, resort, as_of):
    """Written once, by the first run that reserves or getaway-lists the deposit."""
    if deposit["settlement_power"] is None:
        deposit["settlement_power"] = settlement_value(deposit, resort, as_of)
        deposit["_settlement_as_of"] = format_instant(as_of)
    return deposit["settlement_power"]


# ---------------------------------------------------------------------------
# occupancy capacity (PRD 2.8)
# ---------------------------------------------------------------------------
def has_capacity(resort, unit_size, check_in_date_text):
    start = parse_date(check_in_date_text)
    new_days = set(add_days(start, offset) for offset in range(OCCUPANCY_NIGHTS_PER_DEPOSIT))
    per_day = {}
    for deposit in db.deposits.values():
        if deposit["resort_id"] != resort["id"] or deposit["unit_size"] != unit_size:
            continue
        if deposit["deposit_status"] not in COUNTED_DEPOSIT_STATUSES:
            continue
        other_start = parse_date(deposit["check_in_date"])
        for offset in range(OCCUPANCY_NIGHTS_PER_DEPOSIT):
            day = add_days(other_start, offset)
            if day in new_days:
                per_day[day] = per_day.get(day, 0) + 1
    capacity = resort["units_per_size"]
    for day in new_days:
        if per_day.get(day, 0) + 1 > capacity:
            return False
    return True


# ---------------------------------------------------------------------------
# power movements on the exchange pipeline
# ---------------------------------------------------------------------------
def expire_deposit(deposit, resort, owner):
    deposit["deposit_status"] = "EXPIRED"
    touch(deposit)
    ledger.debit_power_clamped(
        owner, "DEPOSIT_EXPIRY_FORFEIT", "DEPOSIT", deposit["id"],
        "Deposit expired; remaining trading power forfeited.", deposit["remaining_power"])
    resort_service.sync_inventory(resort)
    for offer in db.getaway_offers.values():
        if offer["deposit_id"] == deposit["id"] and offer["status"] == "LISTED":
            offer["status"] = "EXPIRED"
            touch(offer)


def withdraw_deposit(deposit, resort, owner):
    deposit["deposit_status"] = "WITHDRAWN"
    touch(deposit)
    ledger.debit_power_clamped(
        owner, "DEPOSIT_WITHDRAWAL_REVERSAL", "DEPOSIT", deposit["id"],
        "Deposit withdrawn; remaining trading power reversed.", deposit["remaining_power"])
    resort_service.sync_inventory(resort)


# ---------------------------------------------------------------------------
# the getaway pipeline
# ---------------------------------------------------------------------------
def list_on_getaway(deposit, resort, owner, as_of, run_id):
    """NOT_LISTED -> LISTED_GETAWAY: price the offer and forfeit the remaining power."""
    freeze_settlement(deposit, resort, as_of)
    days_to_check_in = (parse_date(deposit["check_in_date"]) - as_of.date()).days
    priced = calc.getaway_list_price(deposit["settlement_power"], resort["demand_index"],
                                     days_to_check_in)
    deposit["rental_status"] = "LISTED_GETAWAY"
    touch(deposit)
    offer = db.new_row({
        "deposit_id": deposit["id"],
        "created_by_run_id": run_id,
        "list_price_cents": priced["list_price_cents"],
        "urgency_discount_pct": priced["urgency_discount_pct"],
        "status": "LISTED",
        "booked_by_member_id": None,
        "booked_at": None,
    })
    db.getaway_offers[offer["id"]] = offer
    ledger.debit_power_clamped(
        owner, "GETAWAY_LISTING_FORFEIT", "DEPOSIT", deposit["id"],
        "Deposit listed on the getaway market; remaining trading power forfeited.",
        deposit["remaining_power"])
    return offer
