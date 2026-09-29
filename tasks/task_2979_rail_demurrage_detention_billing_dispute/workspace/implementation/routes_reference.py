"""The logical clock and the four reference collections of PRD §3.1:
consignees, tariff rule sets, facilities and rail cars.
"""

import re

from flask import Blueprint, request

import guards
import schema
from auth import (ROLE_ADJUDICATOR, ROLE_BILLING, ROLE_CUSTOMER, ROLE_RAILROAD,
                  ROLE_REGULATOR, authenticate)
from clockcal import fmt_instant
from derive import (agreement_json, claim_json, customer_json, facility_json,
                    rail_car_json, tariff_json)
from envelope import listing, ok
from errors import fail
from store import base_record, db, touch

bp = Blueprint("reference", __name__)

FACILITY_CODE_RE = re.compile(r"^.{1,16}$", re.S)

NOTIFICATION_METHODS = ("EDI", "EMAIL", "FAX")
FACILITY_KINDS = ("INDUSTRY_TRACK", "RAIL_YARD", "INTERMODAL_TERMINAL")
STORAGE_MODES = ("CALENDAR_DAY_MIDNIGHT", "HOURLY_FROM_ARRIVAL")
ACCESS_MODES = ("OPEN", "GATE_CONTROLLED", "EMBARGOED")
OWNERSHIPS = ("RAILROAD_OWNED", "PRIVATE", "PRIVATE_ASSIGNED")
OWNERSHIP_SCOPES = ("RAILROAD_OWNED", "PRIVATE", "ANY")

ALL_ROLES = (ROLE_CUSTOMER, ROLE_RAILROAD, ROLE_ADJUDICATOR, ROLE_REGULATOR,
             ROLE_BILLING)


# --------------------------------------------------------------------------
# the test-driving logical clock (PRD §2.4 / §3.9)
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(ROLE_BILLING)
    data = schema.body()
    moment = schema.req_instant(data, "to_iso8601")
    with db.lock:
        db.clock = moment
        return ok({"current_utc": fmt_instant(db.clock)})


# --------------------------------------------------------------------------
# consignees
# --------------------------------------------------------------------------

@bp.post("/customers")
def create_customer():
    authenticate(ROLE_BILLING)
    data = schema.body()
    code = schema.req_str(data, "customer_code", 1, 16, schema.CUSTOMER_CODE_RE)
    name = schema.req_str(data, "name", 1)
    station = schema.req_str(data, "serving_station_code", 1, 8)
    method = schema.opt_enum(data, "notification_method", NOTIFICATION_METHODS, "EDI")
    capacity = schema.opt_int(data, "normal_daily_placement_capacity", 0, None, None, 2)
    with db.lock:
        schema.unique_or_fail(db.customers, "customer_code", code)
        rec = base_record("customer")
        rec.update({
            "customer_code": code,
            "name": name,
            "serving_station_code": station,
            "notification_method": method,
            "normal_daily_placement_capacity": capacity,
            "status": "ACTIVE",
            "billing_posture": "CURRENT",
            "credit_hold_reason": None,
        })
        db.customers[rec["id"]] = rec
        return ok(customer_json(rec), 201)


@bp.get("/customers/<cid>")
def get_customer(cid):
    authenticate(*ALL_ROLES)
    with db.lock:
        rec = guards.customer(cid)
        # A Customer record is not part of the ownership chain PRD §2.1
        # declares, so no ERR_NOT_RESOURCE_OWNER applies to reading one.
        return ok(customer_json(rec))


@bp.post("/customers/<cid>/credit-hold")
def credit_hold(cid):
    authenticate(ROLE_BILLING)
    with db.lock:
        rec = guards.customer(cid)
        data = schema.body()
        on_hold = schema.req_bool(data, "on_hold")
        reason = schema.req_str(data, "reason", 1)
        if on_hold:
            rec["billing_posture"] = "CREDIT_HOLD"
            rec["credit_hold_reason"] = reason
        else:
            rec["billing_posture"] = "CURRENT"
            rec["credit_hold_reason"] = None
        touch(rec)
        return ok(customer_json(rec))


@bp.get("/customers/<cid>/average-agreements")
def list_customer_agreements(cid):
    actor = authenticate(ROLE_CUSTOMER, ROLE_BILLING)
    with db.lock:
        guards.customer(cid)
        status = request.args.get("status")
        rows = [a for a in db.ordered("agreements") if a["customer_id"] == cid]
        if status is not None:
            rows = [a for a in rows if a["status"] == status]
        if actor.is_customer and cid != actor.user_id:
            # List endpoints narrow silently rather than refusing (PRD §2.1).
            rows = []
        return listing(rows, agreement_json)


@bp.get("/customers/<cid>/bunching-claims")
def list_customer_claims(cid):
    actor = authenticate(ROLE_CUSTOMER, ROLE_ADJUDICATOR, ROLE_BILLING)
    with db.lock:
        guards.customer(cid)
        status = request.args.get("status")
        rows = [c for c in db.ordered("claims") if c["customer_id"] == cid]
        if status is not None:
            rows = [c for c in rows if c["status"] == status]
        if actor.is_customer and cid != actor.user_id:
            rows = []
        return listing(rows, claim_json)


# --------------------------------------------------------------------------
# tariff rule sets
# --------------------------------------------------------------------------

@bp.post("/tariff-rule-sets")
def create_tariff():
    authenticate(ROLE_REGULATOR)
    data = schema.body()
    rec_fields = {
        "tariff_code": schema.req_str(data, "tariff_code", 1, 16),
        "car_ownership_scope": schema.opt_enum(
            data, "car_ownership_scope", OWNERSHIP_SCOPES, "ANY"),
        "free_time_hours_railroad": schema.opt_int(
            data, "free_time_hours_railroad", 0, 240, 24, 48),
        "free_time_hours_private": schema.opt_int(
            data, "free_time_hours_private", 0, 240, 24, 24),
        "tier1_day_count": schema.opt_int(data, "tier1_day_count", 0, None, None, 2),
        "tier1_rate_cents_railroad": schema.opt_int(
            data, "tier1_rate_cents_railroad", 0, None, None, 12550),
        "tier1_rate_cents_private": schema.opt_int(
            data, "tier1_rate_cents_private", 0, None, None, 8150),
        "tier2_day_count": schema.opt_int(data, "tier2_day_count", 0, None, None, 3),
        "tier2_rate_cents_railroad": schema.opt_int(
            data, "tier2_rate_cents_railroad", 0, None, None, 22450),
        "tier2_rate_cents_private": schema.opt_int(
            data, "tier2_rate_cents_private", 0, None, None, 14950),
        "tier3_rate_cents_railroad": schema.opt_int(
            data, "tier3_rate_cents_railroad", 0, None, None, 35050),
        "tier3_rate_cents_private": schema.opt_int(
            data, "tier3_rate_cents_private", 0, None, None, 24050),
        "weekend_excluded": schema.opt_bool(data, "weekend_excluded", False),
        "notification_grace_hours": schema.opt_int(
            data, "notification_grace_hours", 0, 48, None, 4),
        "adjudication_days_base": schema.opt_int(
            data, "adjudication_days_base", 5, 90, None, 20),
    }
    with db.lock:
        rec = base_record("tariff")
        rec.update(rec_fields)
        # A rule set is born DRAFT; sibling rule sets deliberately share a
        # tariff_code, so the code is not unique across the collection.
        rec["status"] = "DRAFT"
        rec["challenge_count"] = 0
        db.tariffs[rec["id"]] = rec
        return ok(tariff_json(rec), 201)


@bp.get("/tariff-rule-sets/<tid>")
def get_tariff(tid):
    authenticate(*ALL_ROLES)
    with db.lock:
        return ok(tariff_json(guards.tariff(tid)))


@bp.post("/tariff-rule-sets/<tid>/publish")
def publish_tariff(tid):
    authenticate(ROLE_REGULATOR)
    with db.lock:
        rec = guards.tariff(tid)
        if rec["status"] != "DRAFT":
            fail("ERR_TARIFF_INVALID_STATE",
                 "Only a DRAFT rule set can be published.")
        rec["status"] = "PUBLISHED"
        touch(rec)
        # Publication supersedes the incumbent sharing this tariff_code.
        for other in db.tariffs.values():
            if (other["id"] != rec["id"]
                    and other["tariff_code"] == rec["tariff_code"]
                    and other["status"] == "PUBLISHED"):
                other["status"] = "SUPERSEDED"
                touch(other)
        return ok(tariff_json(rec))


# --------------------------------------------------------------------------
# facilities
# --------------------------------------------------------------------------

@bp.post("/facilities")
def create_facility():
    authenticate(ROLE_BILLING)
    data = schema.body()
    code = schema.req_str(data, "facility_code", 1, 16)
    rec_fields = {
        "facility_code": code,
        "kind": schema.opt_enum(data, "kind", FACILITY_KINDS, "INDUSTRY_TRACK"),
        "storage_clock_mode": schema.opt_enum(
            data, "storage_clock_mode", STORAGE_MODES, "CALENDAR_DAY_MIDNIGHT"),
        "gate_open_hour": schema.opt_int(data, "gate_open_hour", 0, 23, None, 7),
        "gate_close_hour": schema.opt_int(data, "gate_close_hour", 0, 23, None, 16),
        "car_spot_capacity": schema.opt_int(
            data, "car_spot_capacity", 1, None, None, 3),
        "switch_buffer_minutes": schema.opt_int(
            data, "switch_buffer_minutes", 0, None, None, 120),
        "storage_free_hours": schema.opt_int(
            data, "storage_free_hours", 0, 240, 24, 48),
        "storage_daily_rate_cents": schema.opt_int(
            data, "storage_daily_rate_cents", 0, None, None, 9000),
        "operates_weekends": schema.opt_bool(data, "operates_weekends", False),
    }
    with db.lock:
        schema.unique_or_fail(db.facilities, "facility_code", code)
        rec = base_record("facility")
        rec.update(rec_fields)
        rec["access_mode"] = "OPEN"
        rec["access_mode_reason"] = None
        db.facilities[rec["id"]] = rec
        return ok(facility_json(rec), 201)


@bp.post("/facilities/<fid>/access-mode")
def set_access_mode(fid):
    authenticate(ROLE_RAILROAD)
    with db.lock:
        rec = guards.facility(fid)
        data = schema.body()
        mode = schema.req_enum(data, "access_mode", ACCESS_MODES)
        reason = schema.req_str(data, "reason", 1)
        rec["access_mode"] = mode
        rec["access_mode_reason"] = reason
        touch(rec)
        return ok(facility_json(rec))


# --------------------------------------------------------------------------
# rail cars
# --------------------------------------------------------------------------

@bp.post("/rail-cars")
def create_rail_car():
    authenticate(ROLE_RAILROAD)
    data = schema.body()
    mark = schema.req_str(data, "car_mark", 1, 16)
    ownership = schema.req_enum(data, "ownership", OWNERSHIPS)
    car_type = schema.opt_str(data, "car_type", 1, None, None, "BOXCAR")
    tons = schema.opt_int(data, "capacity_tons", 1, 200, None, 100)
    with db.lock:
        schema.unique_or_fail(db.rail_cars, "car_mark", mark)
        rec = base_record("rail_car")
        rec.update({
            "car_mark": mark,
            "ownership": ownership,
            "car_type": car_type,
            "capacity_tons": tons,
        })
        db.rail_cars[rec["id"]] = rec
        return ok(rail_car_json(rec), 201)


@bp.get("/rail-cars/<rid>")
def get_rail_car(rid):
    authenticate(ROLE_CUSTOMER, ROLE_RAILROAD, ROLE_BILLING)
    with db.lock:
        return ok(rail_car_json(guards.rail_car(rid)))
