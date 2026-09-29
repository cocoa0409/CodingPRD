"""Session scheduling, documentation of delivery, and voids."""
import datetime

from flask import Blueprint, g, request

import domain as D
from auth import STAFF_READ, endpoint, require_owner
from envelope import paginate, single
from errors import fail
from helpers import get_authorization, get_visit, ser_visit
from services import compute, money
from store import (db, flush, new_row, now, now_iso, ordered, parse_instant,
                   pd, set_field, set_fields)
from validate import (Field, parse_body, v_enum, v_id, v_instant, v_int,
                      v_str)

bp = Blueprint("visits", __name__)

SCHEDULE_ROLES = ["ProgramAdmin", "ServiceCoordinator"]


def _minutes(start, end):
    return int((end - start).total_seconds() // 60)


def _on_boundary(moment):
    return (moment.minute % D.MINUTES_PER_UNIT == 0
            and moment.second == 0 and moment.microsecond == 0)


@bp.route("/ei/service-visits", methods=["POST"])
@endpoint(SCHEDULE_ROLES)
def create_visit():
    payload = parse_body([
        Field("provider_authorization_id", v_id()),
        Field("scheduled_start", v_instant()),
        Field("scheduled_end", v_instant()),
        Field("setting_code", v_enum(D.SETTING_CODES)),
        Field("makeup_for_visit_id", v_id(), required=False),
    ])
    authorization = get_authorization(payload["provider_authorization_id"])
    target = None
    if payload["makeup_for_visit_id"] is not None:
        target = get_visit(payload["makeup_for_visit_id"])
    if authorization["status"] != "ACTIVE":
        fail("ERR_AUTHORIZATION_NOT_ACTIVE",
             "Sessions may only be scheduled against an ACTIVE authorization.")
    line = compute.line_of_auth(authorization)
    if target is not None:
        target_line = compute.line_of_visit(target)
        if (target["visit_status"] != "CANCELLED_PROVIDER"
                or line is None or target_line is None
                or target_line["id"] != line["id"]):
            fail("ERR_MAKEUP_TARGET_INVALID",
                 "A makeup session must repair a provider cancellation on the "
                 "same service line.")
        for other in ordered(db.visits):
            if (other["makeup_for_visit_id"] == target["id"]
                    and other["visit_status"] not in ("VOIDED",
                                                      "CANCELLED_PROGRAM")):
                fail("ERR_MAKEUP_ALREADY_SCHEDULED",
                     "That cancellation is already being made up.")
    start = parse_instant(payload["scheduled_start"])
    end = parse_instant(payload["scheduled_end"])
    _assert_no_conflict(authorization, payload["setting_code"], start, end)
    minutes = _minutes(start, end)
    if (minutes <= 0 or minutes % D.MINUTES_PER_UNIT != 0
            or minutes > D.MAX_VISIT_MINUTES
            or not _on_boundary(start) or not _on_boundary(end)):
        fail("ERR_INVALID_VISIT_DURATION",
             "A session must run a positive whole number of 15-minute units, "
             "at most 240 minutes, on 15-minute boundaries.")
    if target is not None:
        target_start = parse_instant(target["scheduled_start"])
        deadline = target_start.date() + datetime.timedelta(
            days=D.MAKEUP_WINDOW_DAYS)
        if start.date() > deadline:
            fail("ERR_MAKEUP_WINDOW_EXPIRED",
                 "A makeup session must be scheduled within 30 days of the "
                 "cancelled session.")
    window_start = pd(authorization["start_date"])
    window_end = pd(authorization["end_date"])
    if start.date() < window_start or start.date() > window_end:
        fail("ERR_VISIT_OUTSIDE_AUTHORIZATION_WINDOW",
             "The session falls outside the authorization's window.")
    units = minutes // D.MINUTES_PER_UNIT
    if units > (authorization["units_remaining"] or 0):
        fail("ERR_UNITS_EXCEED_AUTHORIZATION",
             "Only %s units remain on the "
             "authorization." % (authorization["units_remaining"] or 0))
    visit = new_row({
        "provider_authorization_id": authorization["id"],
        "makeup_for_visit_id": payload["makeup_for_visit_id"],
        "scheduled_start": payload["scheduled_start"],
        "scheduled_end": payload["scheduled_end"],
        "scheduled_units": units,
        "setting_code": payload["setting_code"],
        "actual_units": None,
        "actual_start": None,
        "actual_end": None,
        "session_note": None,
        "documented_by_user_id": None,
        "documented_at_utc": None,
        "visit_status": "SCHEDULED",
        "billing_status": "PENDING",
        "family_share_cents": None,
        "void_reason_code": None,
        "_cost_share_id": None,
    })
    db.visits[visit["id"]] = visit
    flush()
    return single(ser_visit(visit), 201)


def _assert_no_conflict(authorization, setting_code, start, end):
    buffer_minutes = datetime.timedelta(minutes=D.CROSS_SETTING_BUFFER_MINUTES)
    zero = datetime.timedelta(0)
    for other in ordered(db.visits):
        if other["visit_status"] not in ("SCHEDULED", "DELIVERED"):
            continue
        other_auth = compute.auth_of_visit(other)
        if other_auth is None:
            continue
        if other_auth["provider_id"] != authorization["provider_id"]:
            continue
        other_start = parse_instant(other["scheduled_start"])
        other_end = parse_instant(other["scheduled_end"])
        if other_start is None or other_end is None:
            continue
        pad = zero if other["setting_code"] == setting_code else buffer_minutes
        if start < other_end + pad and other_start < end + pad:
            fail("ERR_PROVIDER_SCHEDULE_CONFLICT",
                 "The provider already has a session covering that interval.")


@bp.route("/ei/service-visits/<visit_id>", methods=["GET"])
@endpoint(STAFF_READ)
def read_visit(visit_id):
    return single(ser_visit(get_visit(visit_id)))


@bp.route("/ei/service-visits", methods=["GET"])
@endpoint(STAFF_READ)
def list_visits():
    rows = ordered(db.visits)
    authorization_id = request.args.get("provider_authorization_id")
    makeup_for_visit_id = request.args.get("makeup_for_visit_id")
    visit_status = request.args.get("visit_status")
    billing_status = request.args.get("billing_status")
    if authorization_id is not None:
        rows = [r for r in rows
                if r["provider_authorization_id"] == authorization_id]
    if makeup_for_visit_id is not None:
        rows = [r for r in rows
                if r["makeup_for_visit_id"] == makeup_for_visit_id]
    if visit_status is not None:
        rows = [r for r in rows if r["visit_status"] == visit_status]
    if billing_status is not None:
        rows = [r for r in rows if r["billing_status"] == billing_status]
    return paginate(rows, ser_visit)


@bp.route("/ei/service-visits/<visit_id>/document", methods=["POST"])
@endpoint(["Provider"])
def document_visit(visit_id):
    payload = parse_body([
        Field("visit_status", v_enum(D.VISIT_DOCUMENT_OUTCOMES)),
        Field("actual_units", v_int(), required=False),
        Field("actual_start", v_instant(), required=False),
        Field("actual_end", v_instant(), required=False),
        Field("session_note", v_str(1), required=False),
    ])
    visit = get_visit(visit_id)
    authorization = compute.auth_of_visit(visit)
    require_owner(authorization["provider_id"] if authorization else None)
    if visit["visit_status"] != "SCHEDULED":
        fail("ERR_VISIT_NOT_SCHEDULED",
             "Only a SCHEDULED session may be documented.")
    if payload["visit_status"] == "DELIVERED" and payload["actual_units"] is None:
        fail("ERR_INVALID_REQUEST",
             "Field 'actual_units' is required for a delivered session.")
    start = parse_instant(visit["scheduled_start"])
    if start is not None and start > now():
        fail("ERR_VISIT_NOT_YET_OCCURRED",
             "The session has not begun relative to the logical clock.")
    line = compute.line_of_auth(authorization)
    referral = compute.referral_of_line(line) if line else None
    if payload["visit_status"] == "DELIVERED":
        units = payload["actual_units"]
        if units > (authorization["units_remaining"] or 0):
            fail("ERR_UNITS_EXCEED_AUTHORIZATION",
                 "Only %s units remain on the "
                 "authorization." % (authorization["units_remaining"] or 0))
        if units < 1 or units > (visit["scheduled_units"] or 0):
            fail("ERR_ACTUAL_UNITS_EXCEED_SCHEDULED",
                 "actual_units must be between 1 and the session's "
                 "scheduled_units.")
        _record_delivery(visit, authorization, line, referral, payload)
    else:
        _record_non_delivery(visit, line, referral, payload)
    flush()
    return single(ser_visit(visit))


def _record_delivery(visit, authorization, line, referral, payload):
    units = payload["actual_units"]
    set_fields(visit, {
        "visit_status": "DELIVERED",
        "actual_units": units,
        "actual_start": payload["actual_start"],
        "actual_end": payload["actual_end"],
        "session_note": payload["session_note"],
        "documented_by_user_id": g.user_id,
        "documented_at_utc": now_iso(),
    })
    set_field(authorization, "units_consumed",
              (authorization["units_consumed"] or 0) + units)
    compute.recompute_auth_units(authorization)
    if line is not None:
        compute.recompute_line_pool(line)
        if line["status"] == "AUTHORIZED":
            set_field(line, "status", "IN_DELIVERY")
    if authorization["units_consumed"] == authorization["authorized_units"]:
        if authorization["status"] == "ACTIVE":
            set_field(authorization, "status", "EXHAUSTED")
            compute.recompute_provider_count(
                db.providers.get(authorization["provider_id"]))
    if line is not None:
        compute.recompute_makeup(line)
        _maybe_complete_line(line)
        if referral is not None:
            compute.recompute_service_gap(referral)
    share, billing, cost_share = 0, "EXEMPT", None
    if line is not None and referral is not None:
        share, billing, cost_share = money.compute_visit_share(
            visit, authorization, line, referral)
    set_fields(visit, {
        "billing_status": billing,
        "family_share_cents": share,
        "_cost_share_id": cost_share["id"] if cost_share else None,
    })
    if share:
        money.apply_charge(cost_share, share)
        money.assert_ledger(cost_share)


def _maybe_complete_line(line):
    if line["status"] != "IN_DELIVERY":
        return
    if (line["units_delivered"] or 0) < (line["planned_units_total"] or 0):
        return
    if (line["makeup_owed_units"] or 0) != 0:
        return
    set_field(line, "status", "COMPLETED")
    for other in compute.line_authorizations(line["id"]):
        if other["status"] == "ACTIVE":
            set_field(other, "status", "EXHAUSTED")
            compute.recompute_provider_count(db.providers.get(other["provider_id"]))


def _record_non_delivery(visit, line, referral, payload):
    set_fields(visit, {
        "visit_status": payload["visit_status"],
        "actual_units": 0,
        "billing_status": "CANCELLED_NO_CHARGE",
        "family_share_cents": 0,
        "documented_by_user_id": g.user_id,
        "documented_at_utc": now_iso(),
    })
    if line is not None:
        compute.recompute_makeup(line)
        if referral is not None:
            compute.recompute_service_gap(referral)


@bp.route("/ei/service-visits/<visit_id>/void", methods=["POST"])
@endpoint(["ProgramAdmin"])
def void_visit(visit_id):
    payload = parse_body([
        Field("void_reason_code", v_enum(D.VOID_REASONS)),
    ])
    visit = get_visit(visit_id)
    if visit["visit_status"] != "DELIVERED":
        fail("ERR_VISIT_NOT_VOIDABLE",
             "Only a DELIVERED session may be voided.")
    share = visit["family_share_cents"] or 0
    cost_share = db.cost_shares.get(visit.get("_cost_share_id"))
    if cost_share is not None and share:
        if (cost_share["family_balance_cents"] or 0) - share < 0:
            fail("ERR_LEDGER_WOULD_UNBALANCE",
                 "Voiding this session would drive the family balance below "
                 "zero.")
    authorization = compute.auth_of_visit(visit)
    line = compute.line_of_auth(authorization) if authorization else None
    referral = compute.referral_of_line(line) if line else None
    units = visit["actual_units"] or 0
    set_fields(visit, {
        "visit_status": "VOIDED",
        "billing_status": "REVERSED",
        "void_reason_code": payload["void_reason_code"],
    })
    if authorization is not None:
        set_field(authorization, "units_consumed",
                  (authorization["units_consumed"] or 0) - units)
        compute.recompute_auth_units(authorization)
        if authorization["status"] == "EXHAUSTED" and units > 0:
            window_end = pd(authorization["end_date"])
            if window_end is not None and window_end >= now().date():
                set_field(authorization, "status", "ACTIVE")
        compute.recompute_provider_count(
            db.providers.get(authorization["provider_id"]))
    if cost_share is not None and share:
        money.reverse_charge(cost_share, share)
        money.assert_ledger(cost_share)
    if line is not None:
        compute.recompute_line_pool(line)
        compute.recompute_makeup(line)
        if referral is not None:
            compute.recompute_service_gap(referral)
    flush()
    return single(ser_visit(visit))
