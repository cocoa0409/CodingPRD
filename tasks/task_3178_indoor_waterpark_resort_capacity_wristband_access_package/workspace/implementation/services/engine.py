"""Calculations, state cascades and clock-driven expiry."""

from datetime import timedelta
from decimal import Decimal

import db as _db
import errors
from db import (
    HOLD_EXPIRY_ISO,
    date_from_service_date,
    iso_from_dt,
    parse_iso,
    round_half_up,
    service_date_of,
)

from services import common


# --------------------------------------------------------------------------
# Calculations (PRD 2.8 / 3.1 / 3.5 / 3.9)
# --------------------------------------------------------------------------

def nights_between(arrival_date, departure_date):
    start = date_from_service_date(arrival_date)
    end = date_from_service_date(departure_date)
    return int(round((end - start).total_seconds() // 86400))


def package_terms(room_type, nights, guest_count):
    """Returns (underwritten_total, surcharge, total_cents, withheld_cents).

    PRD 3.1: the withheld figure is the arcade half plus the room subtotal with
    no surcharge, and "the two fields therefore differ by exactly the
    surcharge", so the authorised figure is the withheld figure plus the
    surcharge once.
    """
    base_rate = room_type["base_rate_cents"]
    room_subtotal = base_rate * nights
    included_arcade = base_rate * 2 * nights
    at_par_or_below = guest_count <= room_type["max_occupancy"] - 2
    if at_par_or_below:
        surcharge = 0
    else:
        surcharge = (guest_count // 4) * common.ROOM_FEE_ACTUATION_CENTS
    underwritten_total = included_arcade + room_subtotal
    total_cents = underwritten_total + surcharge
    withheld_cents = included_arcade + room_subtotal
    return (
        round_half_up(underwritten_total),
        round_half_up(surcharge),
        round_half_up(total_cents),
        round_half_up(withheld_cents),
    )


def day_pass_price(units_requested):
    per_unit = units_requested * common.DAY_PASS_BASE_CENTS
    excess = max(units_requested - common.DAY_PASS_VOLUME_THRESHOLD_UNITS, 0)
    blocks = excess // common.DAY_PASS_VOLUME_BLOCK_UNITS
    return round_half_up(per_unit + blocks * common.DAY_PASS_VOLUME_BLOCK_CENTS)


def activity_rate(session, attendees):
    multiplier = common.ACTIVITY_TIER_UNIT_MULTIPLIER.get(session.get("tier_code"), 0)
    tier_units = attendees * multiplier
    subtotal = session["base_price_cents"] * tier_units
    if attendees < 10:
        discount = 0
    else:
        discount = (attendees // 5) * common.ACTIVITY_BULK_DISCOUNT_CENTS
    return round_half_up(subtotal - discount)


def activity_refund(session, attendees):
    refundable = attendees  # attendees have no joined_at instant yet
    gross = Decimal(refundable) * Decimal(session["base_price_cents"]) * \
        Decimal(str(common.ACTIVITY_REFUND_RATE))
    return round_half_up(gross)


def arcade_credit_accrual(resort, reservation):
    return round_half_up(
        resort["arcade_credit_rate_cents_per_unit"] *
        reservation["waterpark_included_units"]
    )


def refresh_opt_in(session, resort_id):
    denominator = common.opt_in_denominator(resort_id)
    capacity = session["capacity_units"]
    if denominator > 0:
        strict = round_half_up(Decimal(capacity) / Decimal(denominator), 4)
    else:
        strict = None
    inclusive = round_half_up(
        Decimal(capacity) / Decimal(denominator + capacity), 4
    )
    ratio = strict
    session["opt_in_ratio"] = ratio
    session["opt_in_ratio_strict"] = strict
    session["opt_in_ratio_inclusive"] = inclusive
    if strict is None or strict >= common.OPT_IN_RATIO_THRESHOLD:
        session["opt_in_gate"] = "ADMIT"
    else:
        session["opt_in_gate"] = "HOLD"


# --------------------------------------------------------------------------
# Wristband bookkeeping
# --------------------------------------------------------------------------

def grants_for_band(wristband_id):
    return [
        g for g in _db.store().arcade_credit_grants.values()
        if g.get("wristband_id") == wristband_id
    ]


def recompute_arcade(wristband):
    """PRD 3.4: drawn is the sum of SUCCEEDED grants; remaining is the ceiling
    minus drawn, floored at 0.  A revoked or re-issued band's ceiling is set to
    0 by its own transition, but the grants already drawn remain observable.
    """
    spent = 0
    for grant in grants_for_band(wristband["id"]):
        if grant.get("grant_status") == "SUCCEEDED":
            spent += grant.get("amount_cents") or 0
    wristband["arcade_credit_spent_cents"] = spent
    remaining = wristband["arcade_credit_limit_cents"] - spent
    wristband["arcade_credit_remaining_cents"] = max(remaining, 0)
    return wristband


def decline_grants_for_band(wristband_id, reason):
    for grant in grants_for_band(wristband_id):
        if grant.get("grant_status") == "SUCCEEDED":
            grant["grant_status"] = "DECLINED"
            grant["decline_reason"] = reason


def revoke_band(band, reason=None, decline_reason="WRISTBAND_REVOKED"):
    band["wristband_status"] = "REVOKED"
    band["access_status"] = "DENIED"
    band["room_charge_enabled"] = False
    band["arcade_credit_limit_cents"] = 0
    band["access_denied_reason"] = reason
    common.touch(band)
    if decline_reason:
        decline_grants_for_band(band["id"], decline_reason)
    recompute_arcade(band)


def mark_expired(band, reason):
    band["wristband_status"] = "EXPIRED"
    band["access_status"] = "DENIED"
    band["access_denied_reason"] = reason
    common.touch(band)


def reservation_guest_bands(reservation_id):
    return [
        b for b in _db.store().wristbands.values()
        if b.get("holder_type") == "RESERVATION_GUEST"
        and b.get("reservation_id") == reservation_id
    ]


# --------------------------------------------------------------------------
# Reservation expiry (PRD 2.6)
# --------------------------------------------------------------------------

def reservation_is_expired(reservation, resort_id):
    if not common.reservation_is_non_terminal(reservation):
        return False
    current = common.current_service_date(resort_id)
    return reservation.get("departure_date") is not None and \
        current > reservation.get("departure_date")


def reservation_is_in_service(reservation, resort_id):
    """True while the booking's logical clock sits inside its stay window."""
    current = common.current_service_date(resort_id)
    arrival = reservation.get("arrival_date")
    departure = reservation.get("departure_date")
    if arrival is None or departure is None:
        return False
    return arrival <= current < departure


def expire_reservation(reservation):
    reservation["booking_status"] = "CANCELLED"
    reservation["stay_status"] = "DEPARTED"
    reservation["reserved_units"] = 0
    common.touch(reservation)


def expire_reservation_bands(reservation):
    current = common.current_service_date(reservation["resort_id"])
    for band in reservation_guest_bands(reservation["id"]):
        if band.get("wristband_status") in ("ISSUED", "ACTIVE"):
            if current > (band.get("valid_on_service_date") or ""):
                mark_expired(band, "SERVICE_DATE_EXPIRED")


def expire_reservations_for_clock(resort_id):
    for reservation in list(_db.store().reservations.values()):
        if reservation.get("resort_id") != resort_id:
            continue
        if reservation_is_expired(reservation, resort_id):
            expire_reservation_bands(reservation)
            expire_reservation(reservation)


# --------------------------------------------------------------------------
# Clock-driven expiry of the other resources
# --------------------------------------------------------------------------

def expire_wristbands_for_clock(resort_id):
    current = common.current_service_date(resort_id)
    for band in list(_db.store().wristbands.values()):
        if band.get("resort_id") != resort_id:
            continue
        if band.get("wristband_status") != "ACTIVE":
            continue
        valid = band.get("valid_on_service_date")
        if valid is None:
            continue
        day_after = (date_from_service_date(valid) + timedelta(days=1)).strftime("%Y-%m-%d")
        if day_after < current:
            mark_expired(band, "SERVICE_DATE_EXPIRED")


def expire_day_passes_for_clock(resort_id):
    current = common.current_service_date(resort_id)
    for day_pass in list(_db.store().day_passes.values()):
        if day_pass.get("resort_id") != resort_id:
            continue
        if day_pass.get("day_pass_status") != "RESERVED":
            continue
        if (day_pass.get("service_date") or "") < current:
            day_pass["day_pass_status"] = "EXPIRED"
            common.touch(day_pass)


def expire_cabana_holds_for_clock(resort_id):
    now = common.current_utc(resort_id)
    for booking in list(_db.store().cabana_bookings.values()):
        if booking.get("resort_id") != resort_id:
            continue
        if booking.get("cabana_booking_status") not in ("HELD", "BOOKED"):
            continue
        expiry = parse_iso(booking.get("hold_expires_at"))
        if expiry is None or expiry > now:
            continue
        booking["cabana_booking_status"] = "EXPIRED"
        common.touch(booking)
        cabana = common.get("cabana", booking.get("cabana_id"))
        if cabana is not None:
            cabana["cabana_status"] = "AVAILABLE"
            common.touch(cabana)


# --------------------------------------------------------------------------
# Group bookkeeping
# --------------------------------------------------------------------------

def recompute_group_reserved(group_booking):
    group_booking["group_reserved_units"] = common.group_reserved_units(group_booking["id"])
    return group_booking["group_reserved_units"]


def cabana_bookings_for_group(group_booking_id):
    return [
        b for b in _db.store().cabana_bookings.values()
        if b.get("group_booking_id") == group_booking_id
    ]


def group_has_live_cabana_booking(group_booking_id):
    for booking in cabana_bookings_for_group(group_booking_id):
        if booking.get("cabana_booking_status") in ("HELD", "BOOKED"):
            return True
    return False


def members_for_group(group_booking_id):
    return [
        m for m in _db.store().group_members.values()
        if m.get("group_booking_id") == group_booking_id
    ]


# --------------------------------------------------------------------------
# Attraction side of wristband revocation (PRD 3.3)
# --------------------------------------------------------------------------

def refresh_attractions_after_band_change(resort_id):
    common.recompute_attractions_for_resort(resort_id)