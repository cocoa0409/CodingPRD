"""Stations, elections, advertisers, rate classes, determinations, clock."""
from datetime import timedelta

from flask import Blueprint, g, request

import core
import domain
import pricing
import serializers as ser
from core import (add_days, body, db, fail, iso, need_date, need_enum, need_int,
                  need_string, now, ok, opt_bool, opt_enum, opt_id, opt_int,
                  opt_string, pagination, paginate, parse_date, parse_iso,
                  require, resolve, touch)

bp = Blueprint("admin", __name__)

READ_ROLES = core.ALL_ROLES


def _ref(payload, field, kind, refs):
    """Collect a body reference for the fixed-order existence pass; only when
    supplied as a non-empty string (shape defects are rung 4, not rung 3)."""
    value = payload.get(field)
    if isinstance(value, str) and value.strip():
        refs.append((kind, value))
    return value


# ---------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------

@bp.post("/political-ads/stations")
def create_station():
    core.authenticate(["PlatformAdmin"])
    payload = body()
    call_sign = need_string(payload, "call_sign")
    licensee_name = need_string(payload, "licensee_name", allow_empty=True)
    market_code = need_string(payload, "market_code", allow_empty=True)
    deadline_hours = opt_int(payload, "political_file_posting_deadline_hours", 24, minimum=1)
    seconds_cap = opt_int(payload, "daily_political_seconds_cap", 300, minimum=30)
    parity = opt_enum(payload, "eo_parity_basis", pricing.EO_PARITY_BASES, "SPOT_COUNT")
    for existing in db.tables["station"].values():
        if existing["call_sign"] == call_sign:
            fail("ERR_INVALID_REQUEST", "call_sign must be unique across all stations")
    station = db.insert("station", {
        "call_sign": call_sign,
        "licensee_name": licensee_name,
        "market_code": market_code,
        "political_file_posting_deadline_hours": deadline_hours,
        "daily_political_seconds_cap": seconds_cap,
        "eo_parity_basis": parity,
        "last_sweep_at": None,
    })
    return ok(ser.serialize_station(station), 201)


@bp.get("/political-ads/stations/<station_id>")
def get_station(station_id):
    core.authenticate(READ_ROLES)
    station = require("station", station_id)
    return ok(ser.serialize_station(station))


@bp.post("/political-ads/stations/<station_id>/audit-sweep")
def audit_sweep(station_id):
    core.authenticate(["PlatformAdmin"])
    station = require("station", station_id)
    clock = now()

    # step 1 - sweep the public file
    entries = [e for e in db.all("file_entry")
               if e["station_id"] == station["id"] and e["posting_status"] == "PENDING"]
    for entry in entries:
        due = parse_iso(entry["due_at"])
        if due is not None and clock > due:
            entry["posting_status"] = "OVERDUE"
            touch(entry)

    # step 2 - expire stale equal-opportunity requests
    requests_ = [r for r in db.all("eo_request")
                 if r["station_id"] == station["id"] and r["status"] == "RECEIVED"]
    for eo in requests_:
        due = parse_iso(eo["response_due_at"])
        if due is not None and clock > due:
            eo["status"] = "EXPIRED"
            touch(eo)

    # step 3 - settle complaints
    complaints = [c for c in db.all("complaint")
                  if c["station_id"] == station["id"] and c["status"] == "RESPONDED"]
    for complaint in complaints:
        if complaint["remedy_code"] == "PENDING_CURE":
            cure_due = parse_iso(complaint["cure_due_at"])
            if cure_due is not None and clock >= cure_due:
                complaint["status"] = "REOPENED"
                touch(complaint)
        elif complaint["remedy_code"] in ("CURED", "NO_VIOLATION"):
            complaint["status"] = "CLOSED"
            touch(complaint)

    # step 4 - recompute posture from what the first three steps left behind
    posture = ser.station_posture(station)

    # step 5 - freeze live business
    if posture == "FROZEN":
        for order in domain.orders_of_station(station["id"]):
            if order["status"] == "ACCEPTED" and order["payment_status"] != "PAID":
                order["status"] = "SUSPENDED"
                touch(order)

    # step 6 - return leg
    if posture == "OPEN":
        for order in domain.orders_of_station(station["id"]):
            if order["status"] == "SUSPENDED":
                order["status"] = "ACCEPTED"
                touch(order)

    station["last_sweep_at"] = iso(clock)
    touch(station)
    marked = getattr(g, "_stations_touched", None)
    if marked is None:
        marked = set()
        g._stations_touched = marked
    marked.add(station["id"])
    return ok(ser.serialize_station(station))


# ---------------------------------------------------------------------------
# Elections
# ---------------------------------------------------------------------------

@bp.post("/political-ads/elections")
def create_election():
    core.authenticate(["PlatformAdmin"])
    payload = body()
    refs = []
    _ref(payload, "station_id", "station", refs)
    resolve(refs)
    station_id = need_string(payload, "station_id")
    office_sought = need_string(payload, "office_sought", allow_empty=True)
    election_type = need_enum(payload, "election_type", pricing.ELECTION_TYPES)
    election_date = need_date(payload, "election_date")
    station = require("station", station_id)
    window_days = pricing.LUC_WINDOW_DAYS[election_type]
    start = parse_date(election_date) - timedelta(days=window_days)
    election = db.insert("election", {
        "station_id": station["id"],
        "office_sought": office_sought,
        "election_type": election_type,
        "election_date": election_date,
        "luc_window_days": window_days,
        "window_start_date": start.isoformat(),
        "window_end_date": election_date,
    })
    return ok(ser.serialize_election(election), 201)


@bp.get("/political-ads/elections/<election_id>")
def get_election(election_id):
    core.authenticate(READ_ROLES)
    election = require("election", election_id)
    return ok(ser.serialize_election(election))


@bp.get("/political-ads/elections")
def list_elections():
    core.authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = db.all("election")
    rows = core.filter_rows(rows, {"station_id": "station_id", "election_type": "election_type"})
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if ser.election_status(r) == status]
    return paginate(rows, limit, offset, ser.serialize_election)


@bp.post("/political-ads/elections/<election_id>/luc-determinations")
def create_luc_determination(election_id):
    core.authenticate(["StationComplianceOfficer"])
    payload = body()
    refs = [("election", election_id)]
    _ref(payload, "rate_class_id", "rate_class", refs)
    resolve(refs)
    election = require("election", election_id)
    rate_class_id = need_string(payload, "rate_class_id")
    variant = need_enum(payload, "variant", ["PROVISIONAL", "FINAL"])
    expected = need_int(payload, "expected_election_version")
    if expected != election["version"]:
        fail("ERR_STALE_ELECTION_VERSION", "expected_election_version does not match")
    rate_class = require("rate_class", rate_class_id)
    determination = domain.create_determination(election, rate_class, variant)
    if variant == "FINAL":
        domain.final_reprice(determination)
    touch(election)
    return ok(ser.serialize_luc_determination(determination), 201)


# ---------------------------------------------------------------------------
# Advertisers
# ---------------------------------------------------------------------------

@bp.post("/political-ads/advertisers")
def create_advertiser():
    core.authenticate(["StationComplianceOfficer", "PlatformAdmin"])
    payload = body()
    refs = []
    _ref(payload, "station_id", "station", refs)
    _ref(payload, "election_id", "election", refs)
    resolve(refs)
    station_id = need_string(payload, "station_id")
    legal_name = need_string(payload, "legal_name", allow_empty=True)
    requested_class = need_enum(payload, "requested_class", pricing.REQUESTED_CLASSES)
    election_id = opt_id(payload, "election_id")
    candidate_name = opt_string(payload, "candidate_name")
    office_sought = opt_string(payload, "office_sought")
    evidence = opt_string(payload, "qualification_evidence_ref")
    station = require("station", station_id)
    advertiser = db.insert("advertiser", {
        "station_id": station["id"],
        "election_id": election_id,
        "legal_name": legal_name,
        "requested_class": requested_class,
        "candidate_name": candidate_name,
        "office_sought": office_sought,
        "qualification_evidence_ref": evidence,
        "status": "SUBMITTED",
        "review_round": 0,
        "classified_by_user_id": None,
        "classification_reason": None,
    })
    return ok(ser.serialize_advertiser(advertiser), 201)


@bp.get("/political-ads/advertisers/<advertiser_id>")
def get_advertiser(advertiser_id):
    core.authenticate(READ_ROLES)
    advertiser = require("advertiser", advertiser_id)
    return ok(ser.serialize_advertiser(advertiser))


@bp.get("/political-ads/advertisers")
def list_advertisers():
    core.authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = db.all("advertiser")
    rows = core.filter_rows(rows, {
        "station_id": "station_id", "election_id": "election_id", "status": "status",
    })
    return paginate(rows, limit, offset, ser.serialize_advertiser)


@bp.post("/political-ads/advertisers/<advertiser_id>/review")
def review_advertiser(advertiser_id):
    core.authenticate(["StationComplianceOfficer"])
    advertiser = require("advertiser", advertiser_id)
    if advertiser["status"] not in ("SUBMITTED", "INFO_REQUESTED"):
        fail("ERR_ADVERTISER_NOT_IN_REVIEW", "advertiser is not open for review")
    advertiser["status"] = "UNDER_REVIEW"
    touch(advertiser)
    return ok(ser.serialize_advertiser(advertiser))


@bp.post("/political-ads/advertisers/<advertiser_id>/decision")
def decide_advertiser(advertiser_id):
    core.authenticate(["StationComplianceOfficer"])
    advertiser = require("advertiser", advertiser_id)
    payload = body()
    decision = need_enum(payload, "decision",
                         ["REQUEST_INFO", "CLASSIFY_CANDIDATE", "CLASSIFY_ISSUE", "REJECT"])
    reason = opt_string(payload, "reason")
    if advertiser["status"] != "UNDER_REVIEW":
        fail("ERR_ADVERTISER_NOT_IN_REVIEW", "advertiser is not under review")

    if decision == "REQUEST_INFO":
        if advertiser["review_round"] < pricing.MAX_REVIEW_ROUNDS:
            advertiser["review_round"] += 1
            advertiser["status"] = "INFO_REQUESTED"
        else:
            advertiser["status"] = "CLASSIFICATION_REJECTED"
            advertiser["classification_reason"] = "MAX_REVIEW_ROUNDS_EXCEEDED"
            advertiser["classified_by_user_id"] = g.user_id
    elif decision == "CLASSIFY_CANDIDATE":
        if advertiser["requested_class"] != "CANDIDATE":
            fail("ERR_INVALID_REQUEST", "advertiser did not request candidate classification")
        if not advertiser["election_id"]:
            fail("ERR_INVALID_REQUEST", "advertiser is not bound to an election")
        evidence = advertiser["qualification_evidence_ref"]
        if not isinstance(evidence, str) or not evidence.strip():
            fail("ERR_INVALID_REQUEST", "qualification_evidence_ref is required")
        advertiser["status"] = "CLASSIFIED_CANDIDATE"
        advertiser["classified_by_user_id"] = g.user_id
        advertiser["classification_reason"] = reason if reason is not None else "LEGALLY_QUALIFIED"
    elif decision == "CLASSIFY_ISSUE":
        advertiser["status"] = "CLASSIFIED_ISSUE"
        advertiser["classified_by_user_id"] = g.user_id
        if reason is not None:
            advertiser["classification_reason"] = reason
    else:
        advertiser["status"] = "CLASSIFICATION_REJECTED"
        advertiser["classified_by_user_id"] = g.user_id
        if reason is not None:
            advertiser["classification_reason"] = reason
    touch(advertiser)
    return ok(ser.serialize_advertiser(advertiser))


# ---------------------------------------------------------------------------
# Rate classes
# ---------------------------------------------------------------------------

@bp.post("/political-ads/rate-classes")
def create_rate_class():
    core.authenticate(["PlatformAdmin"])
    payload = body()
    refs = []
    _ref(payload, "station_id", "station", refs)
    resolve(refs)
    station_id = need_string(payload, "station_id")
    class_code = need_string(payload, "class_code", allow_empty=True)
    daypart = need_enum(payload, "daypart", pricing.DAYPARTS)
    preemptible = core.need_bool(payload, "preemptible")
    posted_rate = need_int(payload, "posted_rate_cents", minimum=1)
    priority = opt_int(payload, "preemption_priority", 0)
    if preemptible:
        if priority < 1 or priority > 5:
            fail("ERR_INVALID_REQUEST",
                 "preemption_priority must be within [1, 5] for a preemptible class")
    else:
        if priority != 0:
            fail("ERR_INVALID_REQUEST",
                 "preemption_priority must be 0 for a fixed class")
    station = require("station", station_id)
    rate_class = db.insert("rate_class", {
        "station_id": station["id"],
        "class_code": class_code,
        "daypart": daypart,
        "preemptible": preemptible,
        "preemption_priority": priority,
        "posted_rate_cents": posted_rate,
        "status": "ACTIVE",
    })
    return ok(ser.serialize_rate_class(rate_class), 201)


@bp.get("/political-ads/rate-classes/<rate_class_id>")
def get_rate_class(rate_class_id):
    core.authenticate(READ_ROLES)
    rate_class = require("rate_class", rate_class_id)
    return ok(ser.serialize_rate_class(rate_class))


@bp.get("/political-ads/rate-classes")
def list_rate_classes():
    core.authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = db.all("rate_class")
    rows = core.filter_rows(rows, {
        "station_id": "station_id", "daypart": "daypart", "status": "status",
    })
    return paginate(rows, limit, offset, ser.serialize_rate_class)


@bp.post("/political-ads/rate-classes/<rate_class_id>/withdraw")
def withdraw_rate_class(rate_class_id):
    core.authenticate(["PlatformAdmin"])
    rate_class = require("rate_class", rate_class_id)
    rate_class["status"] = "WITHDRAWN"
    touch(rate_class)
    return ok(ser.serialize_rate_class(rate_class))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    core.authenticate(["PlatformAdmin"])
    payload = body()
    raw = need_string(payload, "to_iso8601", allow_empty=True)
    parsed = parse_iso(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 UTC timestamp")
    core.set_clock(parsed)
    return ok({"current_utc": iso(core.now())})
