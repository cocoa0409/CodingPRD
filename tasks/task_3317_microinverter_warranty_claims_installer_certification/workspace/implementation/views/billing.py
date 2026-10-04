"""Billing corrections, billed-replacement entitlements, homeowner share links,
and the logical clock (PRD 3.4, 3.7, 3.9 and 2.7)."""

import re
from datetime import datetime, timedelta, timezone

import db
import shapes
from approval import as_int, as_str, body
from auth import ROLE_HOMEOWNER, ROLE_PLATFORM_ADMIN, get_system, get_unit, require
from errors import fail
from respond import CLOCK, add_months, iso, ok, ok_list, paginate, parse_iso
from services import common
from services import orders as order_service

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")



def _parse_period_month(value):
    if not isinstance(value, str) or not MONTH_RE.match(value):
        fail("ERR_INVALID_REQUEST_BODY", "field `period_month` must be a YYYY-MM string")
    year, month = value.split("-")
    return int(year), int(month)


def _metering_fee_at(system, at):
    """The metering posture evaluated at an arbitrary instant."""
    age_months = common.system_age_months(system, at)
    age_factor = common.age_factor_for_months(age_months)
    per_unit_rate_cents = common.money(
        common.dec(common.METERING_BASE_RATE_CENTS) * age_factor)
    active_units = len([u for u in db.all_units_of_system(system["id"])
                        if u.get("commissioning_state") == "COMMISSIONED"])
    if system.get("warranty_status") != "ACTIVE":
        return 0
    if age_months <= common.METERING_FREE_MONTHS:
        return 0
    return per_unit_rate_cents * active_units


def create_billing_correction():
    data = body()
    system_id = as_str(data, "system_id")
    period_month = as_str(data, "period_month")
    corrected = as_int(data, "corrected_metering_fee_cents", minimum=0)

    system = db.DB.systems.get(system_id)
    if system is None:
        fail("ERR_RESOURCE_NOT_FOUND", "system %s does not exist" % system_id)

    year, month = _parse_period_month(period_month)
    current = CLOCK.now()
    current_year, current_month = current.year, current.month

    # The corrected month must be strictly before the current calendar month.
    if (year, month) >= (current_year, current_month):
        fail("ERR_CORRECTION_PERIOD_CLOSED")

    period_start = datetime(year, month, 1, tzinfo=timezone.utc)
    original = _metering_fee_at(system, period_start)
    current_charge = _metering_fee_at(system, current)

    if current_charge == 0:
        variance_bps = 0 if corrected == 0 else common.RECONCILIATION_TOLERANCE_BPS + 1
    else:
        variance = (common.dec(corrected) - common.dec(current_charge)) \
            / common.dec(current_charge)
        variance_bps = common.bps(variance * common.dec(10000))

    if abs(variance_bps) > common.RECONCILIATION_TOLERANCE_BPS:
        fail("ERR_RECONCILIATION_TOLERANCE_EXCEEDED")

    record = {
        "id": common.new_id(),
        "created_at": common.now_iso(),
        "system_id": system_id,
        "period_month": period_month,
        "original_metering_fee_cents": original,
        "corrected_metering_fee_cents": corrected,
        "current_month_charge_cents": current_charge,
        "variance_bps": variance_bps,
        "watermarked_total_cents": corrected,
    }
    db.DB.billing_corrections[record["id"]] = record
    return ok(shapes.billing_correction(record))


def create_entitlement():
    data = body()
    unit_id = as_str(data, "unit_id")
    entitlement_kind = as_str(data, "entitlement_kind")
    effective_from = data.get("effective_from")
    if effective_from is None:
        fail("ERR_INVALID_REQUEST_BODY", "missing required field `effective_from`")
    from approval import as_instant
    effective_from_dt = as_instant(data, "effective_from")

    unit = db.DB.units.get(unit_id)
    if unit is None:
        fail("ERR_RESOURCE_NOT_FOUND", "unit %s does not exist" % unit_id)

    window_start = effective_from_dt
    window_end = add_months(effective_from_dt, common.ENTITLEMENT_MONTHS)

    # Half-open intervals: a window ending exactly where the next begins does
    # not overlap it.
    for existing in db.entitlements_of_unit(unit_id):
        other_start = parse_iso(existing["effective_from"])
        other_end = add_months(other_start, common.ENTITLEMENT_MONTHS)
        if window_start < other_end and other_start < window_end:
            fail("ERR_ENTITLEMENT_WINDOW_OVERLAP")

    entitlement = {
        "id": common.new_id(),
        "created_at": common.now_iso(),
        "unit_id": unit_id,
        "entitlement_kind": entitlement_kind,
        "effective_from": iso(effective_from_dt),
        "status": "ACTIVE",
        "reservation_order_id": None,
    }
    db.DB.entitlements[entitlement["id"]] = entitlement

    # Recording the entitlement reserves a replacement position: an order with
    # neither a claim nor a campaign is created and linked to the reservation so
    # the position is counted exactly once even after that order is installed.
    order = order_service.new_order(
        unit, unit.get("model_code"), "IDENTICAL", "PENDING_DISPATCH")
    entitlement["reservation_order_id"] = order["id"]
    common.set_many(unit, {
        "replacement_count": int(unit.get("replacement_count", 0)) + 1,
    })
    common.recompute_unit(unit)
    return ok(shapes.billing_entitlement(entitlement), 201)


def list_entitlements():
    from flask import request

    unit_id = request.args.get("unit_id")
    rows = list(db.DB.entitlements.values())
    if unit_id:
        rows = [e for e in rows if e.get("unit_id") == unit_id]
    rows = db.by_created_at(rows)
    window, meta = paginate(rows, request.args)
    return ok_list([shapes.billing_entitlement(e) for e in window], pagination=meta)


def create_share_link():
    data = body()
    system_id = as_str(data, "system_id")
    expires_at = data.get("expires_at")
    if expires_at is None:
        fail("ERR_INVALID_REQUEST_BODY", "missing required field `expires_at`")
    from approval import as_instant
    expires_at_dt = as_instant(data, "expires_at")

    system = db.DB.systems.get(system_id)
    if system is None:
        fail("ERR_RESOURCE_NOT_FOUND", "system %s does not exist" % system_id)

    link = {
        "id": common.new_id(),
        "created_at": common.now_iso(),
        "system_id": system_id,
        "expires_at": iso(expires_at_dt),
        "scope": system_id,
    }
    db.DB.share_links[link["id"]] = link
    return ok(shapes.share_link(link), 201)


def set_clock():
    data = body()
    to_iso8601 = as_str(data, "to_iso8601")
    from approval import as_instant
    instant = as_instant(data, "to_iso8601")
    CLOCK.set(iso(instant))
    return ok({})


def register(app):
    app.add_url_rule("/warranty/billing-corrections", "create_billing_correction",
                     require(ROLE_PLATFORM_ADMIN)(create_billing_correction),
                     methods=["POST"])
    app.add_url_rule("/warranty/billing-entitlements", "create_entitlement",
                     require(ROLE_PLATFORM_ADMIN)(create_entitlement), methods=["POST"])
    app.add_url_rule("/warranty/billing-entitlements", "list_entitlements",
                     require(ROLE_PLATFORM_ADMIN)(list_entitlements), methods=["GET"])
    app.add_url_rule("/warranty/share-links", "create_share_link",
                     require(ROLE_HOMEOWNER)(create_share_link), methods=["POST"])
    app.add_url_rule("/_clock/set_current_utc", "set_clock",
                     require(ROLE_PLATFORM_ADMIN)(set_clock), methods=["POST"])