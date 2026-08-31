"""Commercial orders, scheduled spots and settlement."""
from flask import Blueprint, g

import core
import domain
import pricing
import serializers as ser
from core import (add_days, body, db, fail, iso, need_date, need_enum, need_int,
                  need_string, now, ok, opt_bool, opt_id, opt_string, pagination,
                  paginate, parse_date, require, resolve, touch)
from domain import LIVE_ORDER_STATUSES, ACTIVE_SPOT_STATUSES

bp = Blueprint("orders", __name__)

READ_ROLES = core.ALL_ROLES


def _ref(payload, field, kind, refs):
    value = payload.get(field)
    if isinstance(value, str) and value.strip():
        refs.append((kind, value))
    return value


def _order_owner_guard(order_id):
    """Rung 1 ownership runs ahead of rung 3 existence whenever the order can
    actually be resolved; an unknown order falls through to the 404."""
    order = db.get("order", order_id)
    if order is not None:
        core.owner_check(order["advertiser_id"])
    return order


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@bp.post("/political-ads/orders")
def create_order():
    core.authenticate(["AdvertiserAgent"])
    payload = body()
    advertiser_ref = payload.get("advertiser_id")
    if isinstance(advertiser_ref, str) and advertiser_ref.strip():
        core.owner_check(advertiser_ref)
    refs = []
    _ref(payload, "station_id", "station", refs)
    _ref(payload, "election_id", "election", refs)
    _ref(payload, "advertiser_id", "advertiser", refs)
    _ref(payload, "rate_class_id", "rate_class", refs)
    resolve(refs)

    station_id = need_string(payload, "station_id")
    advertiser_id = need_string(payload, "advertiser_id")
    rate_class_id = need_string(payload, "rate_class_id")
    payment_terms = need_enum(payload, "payment_terms", pricing.PAYMENT_TERMS)
    if "sponsorship_disclosure_text" not in payload:
        fail("ERR_INVALID_REQUEST", "sponsorship_disclosure_text is required")
    disclosure_text = payload["sponsorship_disclosure_text"]
    if disclosure_text is not None and not isinstance(disclosure_text, str):
        fail("ERR_INVALID_REQUEST", "sponsorship_disclosure_text must be a string")
    disclosure_duration = need_int(payload, "disclosure_duration_seconds", minimum=0)
    election_id = opt_id(payload, "election_id")
    agency_placed = opt_bool(payload, "agency_placed", False)

    station = require("station", station_id)
    advertiser = require("advertiser", advertiser_id)
    rate_class = require("rate_class", rate_class_id)
    election = db.get("election", election_id) if election_id else None

    if rate_class["station_id"] != station["id"] or advertiser["station_id"] != station["id"]:
        fail("ERR_RATE_CLASS_STATION_MISMATCH", "referenced resources belong to another station")
    if election is not None and election["station_id"] != station["id"]:
        fail("ERR_RATE_CLASS_STATION_MISMATCH", "referenced election belongs to another station")

    order = db.insert("order", {
        "station_id": station["id"],
        "advertiser_id": advertiser["id"],
        "election_id": election_id,
        "rate_class_id": rate_class["id"],
        "payment_terms": payment_terms,
        "agency_placed": agency_placed,
        "sponsorship_disclosure_text": disclosure_text,
        "disclosure_duration_seconds": disclosure_duration,
        "disclosure_status": "MISSING",
        "status": "DRAFT",
        "payment_status": "UNBILLED",
        "spot_count": 0,
        "gross_charge_cents": 0,
        "agency_commission_cents": 0,
        "net_due_cents": 0,
        "rebate_total_cents": 0,
        "paid_cents": 0,
        "refunded_cents": 0,
        "accepted_at": None,
        "accepted_by_user_id": None,
        "payment_due_at": None,
        "first_air_at": None,
        "rejection_reason": None,
    })
    order["disclosure_status"] = pricing.disclosure_conformance(
        disclosure_text, disclosure_duration, advertiser["legal_name"])
    return ok(ser.serialize_order(order), 201)


@bp.get("/political-ads/orders/<order_id>")
def get_order(order_id):
    core.authenticate(READ_ROLES)
    order = require("order", order_id)
    return ok(ser.serialize_order(order))


@bp.get("/political-ads/orders")
def list_orders():
    core.authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = db.all("order")
    rows = core.filter_rows(rows, {
        "station_id": "station_id", "advertiser_id": "advertiser_id",
        "election_id": "election_id", "rate_class_id": "rate_class_id",
        "status": "status", "payment_status": "payment_status",
    })
    return paginate(rows, limit, offset, ser.serialize_order)


@bp.post("/political-ads/orders/<order_id>/spots")
def add_spot(order_id):
    core.authenticate(["AdvertiserAgent"])
    _order_owner_guard(order_id)
    order = require("order", order_id)
    payload = body()
    air_date = need_date(payload, "air_date")
    start_offset = need_int(payload, "start_offset_seconds", minimum=0, maximum=86399)
    duration = need_int(payload, "duration_seconds", choices=pricing.DURATIONS)
    program_code = need_string(payload, "program_code", allow_empty=True)

    if order["status"] != "DRAFT":
        fail("ERR_ORDER_NOT_DRAFT", "order has left DRAFT")

    rate_class = db.get("rate_class", order["rate_class_id"])
    if rate_class["status"] != "ACTIVE":
        fail("ERR_RATE_CLASS_WITHDRAWN", "rate class has been withdrawn")

    if air_date < core.clock_date_str():
        fail("ERR_SPOT_AIR_DATE_IN_PAST", "air_date is before the current broadcast date")

    station = db.get("station", order["station_id"])
    advertiser = db.get("advertiser", order["advertiser_id"])
    new_start = start_offset
    new_end = start_offset + duration

    # (i) inventory collision
    for other in db.all("spot"):
        if other["rate_class_id"] != rate_class["id"] or other["air_date"] != air_date:
            continue
        if other["status"] not in ACTIVE_SPOT_STATUSES:
            continue
        owner = db.get("order", other["order_id"])
        if owner is None or owner["status"] not in LIVE_ORDER_STATUSES:
            continue
        other_end = other["start_offset_seconds"] + other["duration_seconds"]
        if new_start < other_end and other["start_offset_seconds"] < new_end:
            fail("ERR_SPOT_SLOT_COLLISION", "spot overlaps an existing spot in this class")

    # (ii) candidate separation
    if order["election_id"] and advertiser is not None and advertiser["status"] == "CLASSIFIED_CANDIDATE":
        for other in db.all("spot"):
            if other["air_date"] != air_date or other["status"] not in ACTIVE_SPOT_STATUSES:
                continue
            owner = db.get("order", other["order_id"])
            if owner is None or owner["status"] not in LIVE_ORDER_STATUSES:
                continue
            if not owner["election_id"] or owner["election_id"] != order["election_id"]:
                continue
            if owner["advertiser_id"] == order["advertiser_id"]:
                continue
            other_advertiser = db.get("advertiser", owner["advertiser_id"])
            if other_advertiser is None or other_advertiser["status"] != "CLASSIFIED_CANDIDATE":
                continue
            other_start = other["start_offset_seconds"]
            other_end = other_start + other["duration_seconds"]
            gap = max(0, max(new_start, other_start) - min(new_end, other_end))
            if gap < pricing.CANDIDATE_SEPARATION_BUFFER_SECONDS:
                fail("ERR_CANDIDATE_SEPARATION_VIOLATION",
                     "spot sits too close to an opposing candidate's spot")

    # (iii) station daily cap
    day_seconds = 0
    for other in db.all("spot"):
        if other["air_date"] != air_date or other["status"] not in ACTIVE_SPOT_STATUSES:
            continue
        owner = db.get("order", other["order_id"])
        if owner is None or owner["status"] not in LIVE_ORDER_STATUSES:
            continue
        if owner["station_id"] != order["station_id"]:
            continue
        day_seconds += other["duration_seconds"]
    if day_seconds + duration > station["daily_political_seconds_cap"]:
        fail("ERR_STATION_DAILY_CAP_EXCEEDED", "station daily political seconds cap exceeded")

    spot = db.insert("spot", {
        "order_id": order["id"],
        "rate_class_id": rate_class["id"],
        "air_date": air_date,
        "start_offset_seconds": start_offset,
        "duration_seconds": duration,
        "program_code": program_code,
        "status": "SCHEDULED",
        "charged_rate_cents": 0,
        "unit_equivalent_rate_cents": 0,
        "luc_capped": False,
        "luc_cap_cents": None,
        "aired_at": None,
        "preemption_reason": None,
    })
    domain.reprice_order(order, skip_spot_ids=(spot["id"],))
    touch(order)
    return ok(ser.serialize_spot(spot), 201)


@bp.post("/political-ads/orders/<order_id>/submit")
def submit_order(order_id):
    core.authenticate(["AdvertiserAgent"])
    _order_owner_guard(order_id)
    order = require("order", order_id)
    if order["status"] != "DRAFT":
        fail("ERR_ORDER_NOT_DRAFT", "order has left DRAFT")
    advertiser = db.get("advertiser", order["advertiser_id"])
    graded = pricing.disclosure_conformance(
        order["sponsorship_disclosure_text"], order["disclosure_duration_seconds"],
        advertiser["legal_name"] if advertiser else None)
    if graded != "CONFORMING":
        fail("ERR_DISCLOSURE_NONCONFORMING", "sponsorship identification is %s" % graded)
    if order["spot_count"] < 1:
        fail("ERR_ORDER_HAS_NO_SPOTS", "order carries no spots")
    order["disclosure_status"] = graded
    order["status"] = "SUBMITTED"
    touch(order)
    return ok(ser.serialize_order(order))


@bp.post("/political-ads/orders/<order_id>/decision")
def decide_order(order_id):
    core.authenticate(["StationComplianceOfficer"])
    order = require("order", order_id)
    payload = body()
    decision = need_enum(payload, "decision", ["ACCEPT", "REJECT"])
    rejection_reason = opt_string(payload, "rejection_reason")
    if decision == "REJECT":
        rejection_reason = need_string(payload, "rejection_reason")

    if order["status"] != "SUBMITTED":
        fail("ERR_ORDER_NOT_SUBMITTED", "order is not SUBMITTED")

    station = db.get("station", order["station_id"])
    advertiser = db.get("advertiser", order["advertiser_id"])
    rate_class = db.get("rate_class", order["rate_class_id"])

    if decision == "REJECT":
        order["status"] = "REJECTED"
        order["rejection_reason"] = rejection_reason
        domain.cancel_scheduled_spots(order)
        domain.reprice_order(order)
        touch(order)
        return ok(ser.serialize_order(order))

    posture = ser.station_posture(station)
    if posture == "FROZEN":
        fail("ERR_STATION_POSTURE_FROZEN", "station compliance posture is FROZEN")
    if advertiser is None or advertiser["status"] not in ("CLASSIFIED_CANDIDATE", "CLASSIFIED_ISSUE"):
        fail("ERR_ADVERTISER_NOT_CLASSIFIED", "advertiser has no terminal classification")
    if advertiser["status"] == "CLASSIFIED_ISSUE" and posture == "RESTRICTED":
        fail("ERR_STATION_POSTURE_RESTRICTED", "station is RESTRICTED for issue advertising")
    if advertiser["status"] == "CLASSIFIED_CANDIDATE":
        text = order["sponsorship_disclosure_text"] or ""
        if pricing.AUTHORIZED_BY not in text:
            fail("ERR_DISCLOSURE_AUTHORIZATION_MISSING",
                 "candidate disclosure must carry an AUTHORIZED BY clause")
    if rate_class["status"] != "ACTIVE":
        fail("ERR_RATE_CLASS_WITHDRAWN", "rate class has been withdrawn")
    if advertiser["status"] == "CLASSIFIED_ISSUE" and order["payment_terms"] != "PREPAY":
        fail("ERR_PAYMENT_TERMS_NOT_PERMITTED", "issue advertisers must prepay")

    accepted_at = now()
    order["status"] = "ACCEPTED"
    order["accepted_at"] = iso(accepted_at)
    order["accepted_by_user_id"] = g.user_id
    if order["payment_status"] == "UNBILLED":
        order["payment_status"] = "INVOICED"

    if advertiser["status"] == "CLASSIFIED_CANDIDATE" and order["election_id"]:
        election = db.get("election", order["election_id"])
        if election is not None:
            determination = domain.create_determination(
                election, rate_class, "PROVISIONAL", exclude_order_id=order["id"])
            luc = determination["luc_cents"]
            for spot in domain.spots_of_order(order):
                if spot["status"] != "SCHEDULED":
                    continue
                if not (election["window_start_date"] <= spot["air_date"]
                        <= election["window_end_date"]):
                    continue
                capped = pricing.scaled_cap_cents(luc, spot["duration_seconds"])
                if capped < spot["charged_rate_cents"]:
                    spot["charged_rate_cents"] = capped
                    spot["unit_equivalent_rate_cents"] = pricing.unit_equivalent(
                        capped, spot["duration_seconds"])
                    spot["luc_cap_cents"] = luc
                    spot["luc_capped"] = True
                    touch(spot)

    domain.reprice_order(order)
    if order["payment_terms"] == "PREPAY":
        order["payment_due_at"] = iso(accepted_at)
    else:
        order["payment_due_at"] = iso(add_days(accepted_at, pricing.NET_TERM_DAYS))
    domain.create_file_entry(order, "ORDER_ACCEPTED")
    touch(order)
    return ok(ser.serialize_order(order))


@bp.post("/political-ads/orders/<order_id>/payments")
def record_payment(order_id):
    core.authenticate(["AdvertiserAgent"])
    _order_owner_guard(order_id)
    order = require("order", order_id)
    payload = body()
    direction = need_enum(payload, "direction", ["CHARGE", "REFUND"])
    amount = need_int(payload, "amount_cents", minimum=1)
    expected = need_int(payload, "expected_order_version")

    if expected != order["version"]:
        fail("ERR_STALE_ORDER_VERSION", "expected_order_version does not match")

    if direction == "CHARGE":
        if order["status"] not in ("ACCEPTED", "SUSPENDED", "RUNNING", "COMPLETED"):
            fail("ERR_ORDER_NOT_ACCEPTED", "order has not been accepted")
    else:
        if order["payment_status"] != "REFUND_DUE":
            fail("ERR_REFUND_NOT_DUE", "no refund is due on this order")

    if direction == "CHARGE":
        expected_amount = order["net_due_cents"] - order["paid_cents"] + order["refunded_cents"]
    else:
        expected_amount = order["paid_cents"] - order["refunded_cents"] - order["net_due_cents"]
    if amount != expected_amount:
        fail("ERR_PAYMENT_AMOUNT_MISMATCH", "amount_cents must equal %d" % expected_amount)

    if direction == "CHARGE":
        order["paid_cents"] += amount
        order["payment_status"] = "PAID"
    else:
        order["refunded_cents"] += amount
        order["payment_status"] = "REFUNDED"
    touch(order)
    return ok(ser.serialize_order(order))


@bp.post("/political-ads/orders/<order_id>/cancel")
def cancel_order(order_id):
    core.authenticate(["AdvertiserAgent", "StationComplianceOfficer"])
    _order_owner_guard(order_id)
    order = require("order", order_id)
    payload = body()
    reason = need_string(payload, "cancellation_reason", allow_empty=True)
    if order["status"] not in ("DRAFT", "SUBMITTED", "ACCEPTED", "SUSPENDED", "RUNNING"):
        fail("ERR_ORDER_TERMINAL", "order is already terminal")

    order["status"] = "CANCELLED"
    order["rejection_reason"] = reason
    domain.cancel_scheduled_spots(order)
    domain.reprice_order(order)
    domain.settle_after_reprice(order, "ORDER_CANCELLED")
    domain.release_eo_grants(order)
    touch(order)
    return ok(ser.serialize_order(order))


# ---------------------------------------------------------------------------
# Spots
# ---------------------------------------------------------------------------

@bp.get("/political-ads/spots/<spot_id>")
def get_spot(spot_id):
    core.authenticate(READ_ROLES)
    spot = require("spot", spot_id)
    return ok(ser.serialize_spot(spot))


@bp.get("/political-ads/spots")
def list_spots():
    core.authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = db.all("spot")
    rows = core.filter_rows(rows, {
        "order_id": "order_id", "rate_class_id": "rate_class_id",
        "status": "status", "air_date": "air_date",
    })
    return paginate(rows, limit, offset, ser.serialize_spot)


@bp.post("/political-ads/spots/<spot_id>/disposition")
def spot_disposition(spot_id):
    core.authenticate(["TrafficScheduler"])
    spot = require("spot", spot_id)
    payload = body()
    disposition = need_enum(payload, "disposition", ["AIRED", "PREEMPTED"])
    preemption_reason = opt_string(payload, "preemption_reason")
    if disposition == "PREEMPTED":
        preemption_reason = need_string(payload, "preemption_reason")

    order = db.get("order", spot["order_id"])
    if disposition == "AIRED":
        allowed = ("ACCEPTED", "RUNNING")
    else:
        allowed = ("ACCEPTED", "SUSPENDED", "RUNNING")
    if order["status"] not in allowed:
        fail("ERR_ORDER_NOT_ACCEPTED", "owning order is not in an airable state")
    if spot["status"] != "SCHEDULED":
        fail("ERR_SPOT_NOT_SCHEDULED", "spot has left SCHEDULED")

    rate_class = db.get("rate_class", spot["rate_class_id"])
    if disposition == "PREEMPTED" and not rate_class["preemptible"]:
        fail("ERR_RATE_CLASS_NOT_PREEMPTIBLE", "rate class is not preemptible")

    if disposition == "AIRED":
        if spot["air_date"] > core.clock_date_str():
            fail("ERR_SPOT_AIR_DATE_NOT_REACHED", "air_date has not been reached")
        if order["payment_terms"] == "PREPAY" and order["payment_status"] != "PAID":
            fail("ERR_ORDER_NOT_PAID", "prepay order is not paid in full")
        spot["status"] = "AIRED"
        spot["aired_at"] = iso(now())
        touch(spot)
        domain.advance_after_airing(order)
        domain.refresh_eo_fulfilled(order)
        return ok(ser.serialize_spot(spot))

    # PREEMPTED - four-hop cascade
    spot["status"] = "PREEMPTED"
    spot["charged_rate_cents"] = 0
    spot["unit_equivalent_rate_cents"] = 0
    spot["preemption_reason"] = preemption_reason
    touch(spot)
    domain.reprice_order(order, skip_spot_ids=(spot["id"],))
    domain.settle_after_reprice(order, "SPOT_PREEMPTED")
    touch(order)
    domain.create_file_entry(order, "RATE_ADJUSTMENT")
    domain.advance_after_preemption(order)
    return ok(ser.serialize_spot(spot))
