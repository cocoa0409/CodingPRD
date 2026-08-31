"""Political file entries, equal-opportunity requests, determinations,
rebates and FCC complaints."""
from flask import Blueprint, g

import core
import domain
import pricing
import serializers as ser
from core import (add_days, add_hours, body, db, fail, iso, need_enum,
                  need_string, now, ok, opt_string, pagination, paginate,
                  parse_iso, require, resolve, touch, touch_station_once)

bp = Blueprint("compliance", __name__)

READ_ROLES = core.ALL_ROLES


def _ref(payload, field, kind, refs):
    value = payload.get(field)
    if isinstance(value, str) and value.strip():
        refs.append((kind, value))
    return value


# ---------------------------------------------------------------------------
# Political file entries
# ---------------------------------------------------------------------------

@bp.get("/political-ads/file-entries/<entry_id>")
def get_file_entry(entry_id):
    core.authenticate(READ_ROLES)
    entry = require("file_entry", entry_id)
    return ok(ser.serialize_file_entry(entry))


@bp.get("/political-ads/file-entries")
def list_file_entries():
    core.authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = db.all("file_entry")
    rows = core.filter_rows(rows, {
        "station_id": "station_id", "order_id": "order_id",
        "event_type": "event_type", "posting_status": "posting_status",
    })
    return paginate(rows, limit, offset, ser.serialize_file_entry)


@bp.post("/political-ads/file-entries/<entry_id>/post")
def post_file_entry(entry_id):
    core.authenticate(["StationComplianceOfficer"])
    entry = require("file_entry", entry_id)
    payload = body()
    url = need_string(payload, "public_file_url", allow_empty=True)
    if entry["posting_status"] not in ("PENDING", "OVERDUE"):
        fail("ERR_FILE_ENTRY_ALREADY_POSTED", "entry has already been posted")

    clock = now()
    due = parse_iso(entry["due_at"])
    was_overdue = entry["posting_status"] == "OVERDUE"
    if was_overdue:
        outcome = "LATE_POSTED"
    elif due is not None and clock <= due:
        outcome = "POSTED"
    else:
        outcome = "LATE_POSTED"
    entry["posting_status"] = outcome
    entry["posted_at"] = iso(clock)
    entry["public_file_url"] = url
    if due is not None and clock > due:
        entry["late_by_seconds"] = int((clock - due).total_seconds())
    else:
        entry["late_by_seconds"] = 0
    touch(entry)
    touch_station_once(db.get("station", entry["station_id"]))
    return ok(ser.serialize_file_entry(entry))


# ---------------------------------------------------------------------------
# Equal-opportunity requests
# ---------------------------------------------------------------------------

@bp.post("/political-ads/eo-requests")
def create_eo_request():
    core.authenticate(["AdvertiserAgent"])
    payload = body()
    requester_ref = payload.get("requesting_advertiser_id")
    if isinstance(requester_ref, str) and requester_ref.strip():
        core.owner_check(requester_ref)
    refs = []
    _ref(payload, "station_id", "station", refs)
    _ref(payload, "requesting_advertiser_id", "advertiser", refs)
    _ref(payload, "trigger_order_id", "order", refs)
    resolve(refs)

    station_id = need_string(payload, "station_id")
    requester_id = need_string(payload, "requesting_advertiser_id")
    trigger_order_id = need_string(payload, "trigger_order_id")
    station = require("station", station_id)
    requester = require("advertiser", requester_id)
    trigger_order = require("order", trigger_order_id)

    if requester["status"] != "CLASSIFIED_CANDIDATE":
        fail("ERR_ADVERTISER_NOT_QUALIFIED_CANDIDATE",
             "requesting advertiser is not a legally qualified candidate")

    opponent = db.get("advertiser", trigger_order["advertiser_id"])
    if (trigger_order["advertiser_id"] == requester["id"]
            or opponent is None
            or opponent["status"] != "CLASSIFIED_CANDIDATE"
            or not trigger_order["election_id"]
            or trigger_order["election_id"] != requester["election_id"]):
        fail("ERR_EO_NOT_OPPOSING_CANDIDATE",
             "trigger order is not an opposing candidate's use in the same election")

    if trigger_order["status"] not in ("RUNNING", "COMPLETED"):
        fail("ERR_EO_TRIGGER_ORDER_NOT_AIRED", "trigger order has not aired a first use")

    first_air = parse_iso(trigger_order["first_air_at"])
    received_at = now()
    if first_air is None or received_at > add_days(first_air, pricing.EO_REQUEST_WINDOW_DAYS):
        fail("ERR_EO_REQUEST_WINDOW_CLOSED", "equal-opportunity request window has closed")

    eo = db.insert("eo_request", {
        "station_id": station["id"],
        "election_id": trigger_order["election_id"],
        "requesting_advertiser_id": requester["id"],
        "trigger_order_id": trigger_order["id"],
        "granted_order_id": None,
        "received_at": iso(received_at),
        "response_due_at": iso(add_hours(received_at, pricing.EO_RESPONSE_DEADLINE_HOURS)),
        "status": "RECEIVED",
        "owed_units": 0,
        "fulfilled_units": 0,
        "parity_basis_applied": None,
        "denial_reason": None,
        "responded_at": None,
    })
    return ok(ser.serialize_eo_request(eo), 201)


@bp.get("/political-ads/eo-requests/<eo_id>")
def get_eo_request(eo_id):
    core.authenticate(READ_ROLES)
    eo = require("eo_request", eo_id)
    return ok(ser.serialize_eo_request(eo))


@bp.get("/political-ads/eo-requests")
def list_eo_requests():
    core.authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = db.all("eo_request")
    rows = core.filter_rows(rows, {
        "station_id": "station_id", "election_id": "election_id",
        "requesting_advertiser_id": "requesting_advertiser_id",
        "trigger_order_id": "trigger_order_id",
        "granted_order_id": "granted_order_id", "status": "status",
    })
    return paginate(rows, limit, offset, ser.serialize_eo_request)


@bp.post("/political-ads/eo-requests/<eo_id>/respond")
def respond_eo_request(eo_id):
    core.authenticate(["StationComplianceOfficer"])
    payload = body()
    refs = []
    _ref(payload, "granted_order_id", "order", refs)
    refs.append(("eo_request", eo_id))
    resolve(refs)
    eo = require("eo_request", eo_id)

    decision = need_enum(payload, "decision", ["GRANT", "DENY"])
    granted_order_id = None
    denial_reason = None
    if decision == "GRANT":
        granted_order_id = need_string(payload, "granted_order_id")
    else:
        denial_reason = need_string(payload, "denial_reason")

    if eo["status"] != "RECEIVED":
        fail("ERR_EO_REQUEST_NOT_OPEN", "request is not open")

    clock = now()
    due = parse_iso(eo["response_due_at"])
    if due is not None and clock > due:
        fail("ERR_EO_RESPONSE_DEADLINE_PASSED", "response deadline has passed")

    station = db.get("station", eo["station_id"])
    trigger_order = db.get("order", eo["trigger_order_id"])

    if decision == "GRANT":
        granted_order = require("order", granted_order_id)
        if (granted_order["advertiser_id"] != eo["requesting_advertiser_id"]
                or granted_order["status"] != "ACCEPTED"
                or granted_order["election_id"] != eo["election_id"]
                or (trigger_order is not None
                    and granted_order["rate_class_id"] != trigger_order["rate_class_id"])):
            fail("ERR_INVALID_REQUEST", "granted_order_id does not satisfy the grant conditions")
        eo["status"] = "GRANTED"
        eo["owed_units"] = domain.equal_opportunity_owed_units(station, trigger_order)
        eo["parity_basis_applied"] = station["eo_parity_basis"]
        eo["granted_order_id"] = granted_order["id"]
        eo["responded_at"] = iso(clock)
        eo["fulfilled_units"] = 0
        touch(eo)
        domain.create_file_entry(granted_order, "EQUAL_OPPORTUNITY_RESPONSE")
        return ok(ser.serialize_eo_request(eo))

    eo["status"] = "DENIED"
    eo["denial_reason"] = denial_reason
    eo["responded_at"] = iso(clock)
    touch(eo)
    domain.create_file_entry(trigger_order, "EQUAL_OPPORTUNITY_RESPONSE")
    return ok(ser.serialize_eo_request(eo))


# ---------------------------------------------------------------------------
# Determinations and rebates (reads)
# ---------------------------------------------------------------------------

@bp.get("/political-ads/luc-determinations/<det_id>")
def get_determination(det_id):
    core.authenticate(READ_ROLES)
    det = require("luc_determination", det_id)
    return ok(ser.serialize_luc_determination(det))


@bp.get("/political-ads/luc-determinations")
def list_determinations():
    core.authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = db.all("luc_determination")
    rows = core.filter_rows(rows, {
        "station_id": "station_id", "election_id": "election_id",
        "rate_class_id": "rate_class_id", "basis_spot_id": "basis_spot_id",
        "variant": "variant", "status": "status",
    })
    return paginate(rows, limit, offset, ser.serialize_luc_determination)


@bp.get("/political-ads/rebates/<rebate_id>")
def get_rebate(rebate_id):
    core.authenticate(READ_ROLES)
    rebate = require("rebate", rebate_id)
    return ok(ser.serialize_rebate(rebate))


@bp.get("/political-ads/rebates")
def list_rebates():
    core.authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = db.all("rebate")
    rows = core.filter_rows(rows, {
        "order_id": "order_id", "luc_determination_id": "luc_determination_id",
        "reason": "reason",
    })
    return paginate(rows, limit, offset, ser.serialize_rebate)


# ---------------------------------------------------------------------------
# FCC complaints
# ---------------------------------------------------------------------------

ALLEGATION_CODES = ["LUC_OVERCHARGE", "FILE_TIMELINESS", "EQUAL_OPPORTUNITY_DENIED",
                    "DISCLOSURE_DEFECT"]
REMEDY_CODES = ["CURED", "PENDING_CURE", "NO_VIOLATION"]


@bp.post("/political-ads/complaints")
def create_complaint():
    core.authenticate(["PublicComplainant"])
    payload = body()
    refs = []
    _ref(payload, "station_id", "station", refs)
    _ref(payload, "order_id", "order", refs)
    resolve(refs)

    station_id = need_string(payload, "station_id")
    complainant_name = need_string(payload, "complainant_name", allow_empty=True)
    allegation_code = need_enum(payload, "allegation_code", ALLEGATION_CODES)
    narrative = need_string(payload, "narrative", allow_empty=True)
    order_id = core.opt_id(payload, "order_id")
    station = require("station", station_id)
    if order_id:
        require("order", order_id)

    filed_at = now()
    complaint = db.insert("complaint", {
        "station_id": station["id"],
        "order_id": order_id,
        "complainant_name": complainant_name,
        "allegation_code": allegation_code,
        "narrative": narrative,
        "filed_at": iso(filed_at),
        "response_due_at": iso(add_hours(filed_at, pricing.COMPLAINT_RESPONSE_DEADLINE_HOURS)),
        "status": "OPEN",
        "remedy_code": None,
        "cure_due_at": None,
        "responded_at": None,
        "response_text": None,
        "late_response": False,
        "responded_by_user_id": None,
    })
    touch_station_once(station)
    return ok(ser.serialize_complaint(complaint), 201)


@bp.get("/political-ads/complaints/<complaint_id>")
def get_complaint(complaint_id):
    core.authenticate(READ_ROLES)
    complaint = require("complaint", complaint_id)
    return ok(ser.serialize_complaint(complaint))


@bp.get("/political-ads/complaints")
def list_complaints():
    core.authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = db.all("complaint")
    rows = core.filter_rows(rows, {
        "station_id": "station_id", "order_id": "order_id",
        "allegation_code": "allegation_code", "status": "status",
    })
    return paginate(rows, limit, offset, ser.serialize_complaint)


@bp.post("/political-ads/complaints/<complaint_id>/respond")
def respond_complaint(complaint_id):
    core.authenticate(["StationComplianceOfficer"])
    existing = db.get("complaint", complaint_id)
    if existing is not None and existing["order_id"]:
        named_order = db.get("order", existing["order_id"])
        if (named_order is not None
                and named_order["accepted_by_user_id"] is not None
                and named_order["accepted_by_user_id"] == g.user_id):
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "the officer who accepted the order may not answer the complaint")
    complaint = require("complaint", complaint_id)
    payload = body()
    response_text = need_string(payload, "response_text", allow_empty=True)
    remedy_code = need_enum(payload, "remedy_code", REMEDY_CODES)

    if complaint["status"] not in ("OPEN", "REOPENED"):
        fail("ERR_COMPLAINT_NOT_OPEN", "complaint is not open")

    clock = now()
    complaint["status"] = "RESPONDED"
    complaint["response_text"] = response_text
    complaint["remedy_code"] = remedy_code
    complaint["responded_at"] = iso(clock)
    complaint["responded_by_user_id"] = g.user_id
    due = parse_iso(complaint["response_due_at"])
    complaint["late_response"] = bool(due is not None and clock > due)
    if remedy_code == "PENDING_CURE":
        complaint["cure_due_at"] = iso(add_hours(clock, pricing.CURE_PERIOD_HOURS))
    else:
        complaint["cure_due_at"] = None
    touch(complaint)
    touch_station_once(db.get("station", complaint["station_id"]))
    return ok(ser.serialize_complaint(complaint))
