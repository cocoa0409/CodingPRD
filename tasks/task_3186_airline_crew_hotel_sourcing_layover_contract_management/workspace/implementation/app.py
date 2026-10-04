"""Airline Crew Hotel Sourcing API -- Flask entry point.

Validation order per PRD 2.10 / scaffold 1.4:
  1. auth (ERR_UNAUTHENTICATED 401)
  2. role authorization (ERR_FORBIDDEN 403)
  3. existence, path ids then body FKs left-to-right (ERR_NOT_FOUND 404)
  -- for the two OCC endpoints, expected_*_version is checked here
     (ERR_STALE_VERSION 412) so a stale write is rejected rather than
     silently overwriting state that legitimately advanced (PRD 2.9) --
  4. state-machine legality (ERR_INVALID_STATE 409)
  5.. endpoint business rules in scaffold priority order
  last. request shape (ERR_INVALID_REQUEST 400)
"""
import os
from datetime import timedelta

from flask import Flask, request

import db
import services as svc
from errors import ApiError, err
from response import error_response, paginate, success_obj

app = Flask(__name__)

ROLES = {
    "PlatformAdmin",
    "SourcingManager",
    "CrewOps",
    "FinanceAnalyst",
    "CrewAuditor",
    "HotelVendorRep",
}

ALL = sorted(ROLES)


# ---------------------------------------------------------------------------
# Request plumbing
# ---------------------------------------------------------------------------

@app.before_request
def _settle():
    with db.LOCK:
        db.settle_lazy()


@app.errorhandler(ApiError)
def _api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _not_found(e):
    return error_response(err("ERR_NOT_FOUND", "resource not found"))


@app.errorhandler(405)
def _method_not_allowed(e):
    return error_response(err("ERR_NOT_FOUND", "resource not found"))


@app.errorhandler(Exception)
def _unhandled(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(err("ERR_INVALID_REQUEST", "invalid request"))


def auth(*allowed):
    """Priority 1-2: authenticate the role header, then authorize the role."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "missing or unrecognized X-User-Role")
    if allowed and role not in allowed:
        raise err("ERR_FORBIDDEN", "role %s not permitted for this endpoint" % role)
    return role


def caller_id():
    return request.headers.get("X-User-ID")


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


# --- field validators (priority 17: ERR_INVALID_REQUEST) -------------------

def _bad(field, why):
    raise err("ERR_INVALID_REQUEST", "%s: %s" % (field, why))


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        _bad(field, "required non-empty string")
    return v


def opt_str(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def req_int(data, field, lo=None, hi=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "required integer")
    if lo is not None and v < lo:
        _bad(field, "must be >= %s" % lo)
    if hi is not None and v > hi:
        _bad(field, "must be <= %s" % hi)
    return v


def req_number(data, field, lo=None, hi=None, lo_exclusive=False):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(field, "required number")
    if lo is not None:
        if lo_exclusive and not v > lo:
            _bad(field, "must be > %s" % lo)
        if not lo_exclusive and v < lo:
            _bad(field, "must be >= %s" % lo)
    if hi is not None and v > hi:
        _bad(field, "must be <= %s" % hi)
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        _bad(field, "required boolean")
    return v


def opt_bool(data, field, default=False):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        _bad(field, "must be a boolean")
    return v


def req_enum(data, field, values):
    v = data.get(field)
    if v not in values:
        _bad(field, "must be one of %s" % "|".join(sorted(values)))
    return v


def req_dt(data, field):
    v = data.get(field)
    if v is None:
        _bad(field, "required ISO8601 datetime")
    return db.parse_dt(v, field)


def opt_date_list(data, field):
    v = data.get(field)
    if v is None:
        return []
    if not isinstance(v, list):
        _bad(field, "must be an array of YYYY-MM-DD dates")
    for item in v:
        if not db.is_valid_date_str(item):
            _bad(field, "entries must be YYYY-MM-DD dates")
    return list(v)


def opt_str_list(data, field):
    v = data.get(field)
    if v is None:
        return []
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _bad(field, "must be an array of strings")
    return list(v)


# --- list filter helper ------------------------------------------------------

def _norm_stay_date(raw):
    """stay_date is a UTC calendar date (PRD 3.6); normalize any input form to
    the YYYY-MM-DD date portion so filters and equality checks compare dates."""
    try:
        return db.parse_dt(raw, "stay_date").date().isoformat()
    except ApiError:
        return raw


def list_endpoint(store, filters):
    """filters: list of (query_param, record_field) equality filters."""
    records = []
    for rec in store.values():
        ok = True
        for param, field in filters:
            raw = request.args.get(param)
            if raw is None:
                continue
            val = rec.get(field)
            if field == "stay_date":
                val = _norm_stay_date(str(val))
                raw = _norm_stay_date(raw)
            if str(val) != raw:
                ok = False
                break
        if ok:
            records.append(rec)
    return paginate(records, request.args)


# ===========================================================================
# Logical clock
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth("PlatformAdmin")
    data = body()
    target = req_dt(data, "to_iso8601")
    with db.LOCK:
        db.set_clock(target)
        db.settle_lazy()
        return success_obj({"current_utc": db.iso(db.CLOCK)})


# ===========================================================================
# Stations
# ===========================================================================

@app.route("/stations", methods=["POST"])
def create_station():
    auth("PlatformAdmin")
    data = body()
    rec = db.stamp_new(
        {
            "code": req_str(data, "code"),
            "name": req_str(data, "name"),
            "timezone": req_str(data, "timezone"),
            "min_rest_hours": req_int(data, "min_rest_hours", 1, 24),
            "transport_time_minutes": req_int(data, "transport_time_minutes", 5, 180),
            "room_availability_commitment": req_int(data, "room_availability_commitment", 0),
        }
    )
    # PRD 2.5: station code is unique across all stations.
    for existing in db.stations.values():
        if existing["code"] == rec["code"]:
            raise err("ERR_INVALID_REQUEST",
                      "station code %s already exists" % rec["code"], 400)
    db.stations[rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@app.route("/stations", methods=["GET"])
def list_stations():
    auth(*ALL)
    return list_endpoint(db.stations, [])


@app.route("/stations/<sid>", methods=["GET"])
def get_station(sid):
    auth(*ALL)
    return success_obj(db.public(svc.get_or_404(db.stations, sid, "station")))


# ===========================================================================
# Union agreements
# ===========================================================================

UNION_GET_ROLES = ("PlatformAdmin", "SourcingManager", "CrewOps", "FinanceAnalyst", "CrewAuditor")


@app.route("/union-agreements", methods=["POST"])
def create_union_agreement():
    auth("PlatformAdmin")
    data = body()
    rec = db.stamp_new(
        {
            "name": req_str(data, "name"),
            "crew_type": req_enum(data, "crew_type", ("PILOT", "FLIGHT_ATTENDANT")),
            "min_rest_hours": req_int(data, "min_rest_hours", 8, 24),
            "quiet_room_required": req_bool(data, "quiet_room_required"),
            "min_room_standard": req_enum(data, "min_room_standard", ("STANDARD", "PREMIUM", "SUITE")),
            "blackout_protection_required": req_bool(data, "blackout_protection_required"),
            "max_invoice_variance_pct": req_number(data, "max_invoice_variance_pct", 0, 100, lo_exclusive=True),
        }
    )
    db.union_agreements[rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@app.route("/union-agreements", methods=["GET"])
def list_union_agreements():
    auth(*UNION_GET_ROLES)
    return list_endpoint(db.union_agreements, [("crew_type", "crew_type")])


@app.route("/union-agreements/<uid>", methods=["GET"])
def get_union_agreement(uid):
    auth(*UNION_GET_ROLES)
    return success_obj(db.public(svc.get_or_404(db.union_agreements, uid, "union agreement")))


# ===========================================================================
# Hotel vendors
# ===========================================================================


@app.route("/hotel-vendors", methods=["POST"])
def create_vendor():
    auth("PlatformAdmin")
    data = body()
    rec = db.stamp_new(
        {
            "name": req_str(data, "name"),
            "contact_email": req_str(data, "contact_email"),
            "status": "ACTIVE",
            "security_certified": req_bool(data, "security_certified"),
            "quiet_rooms_count": req_int(data, "quiet_rooms_count", 0),
        }
    )
    db.vendors[rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@app.route("/hotel-vendors", methods=["GET"])
def list_vendors():
    auth(*ALL)
    return list_endpoint(db.vendors, [("status", "status")])


@app.route("/hotel-vendors/<vid>", methods=["GET"])
def get_vendor(vid):
    auth(*ALL)
    return success_obj(db.public(svc.get_or_404(db.vendors, vid, "hotel vendor")))


# ===========================================================================
# RFP cycles
# ===========================================================================

RFP_GET_ROLES = ("PlatformAdmin", "SourcingManager", "CrewOps", "FinanceAnalyst", "HotelVendorRep")


def _get_cycle(cid):
    return svc.get_or_404(db.rfp_cycles, cid, "rfp cycle")


@app.route("/rfp-cycles", methods=["POST"])
def create_rfp_cycle():
    auth("SourcingManager")
    data = body()
    station_id = data.get("station_id")
    if station_id is not None and not isinstance(station_id, str):
        _bad("station_id", "must be a string")
    if station_id is None:
        _bad("station_id", "required")
    station = db.stations.get(station_id)
    if station is None:
        raise err("ERR_NOT_FOUND", "station not found: %s" % station_id)
    rec = db.stamp_new(
        {
            "station_id": station_id,
            "title": req_str(data, "title"),
            "status": "DRAFT",
            "response_deadline": db.iso(req_dt(data, "response_deadline")),
            "target_room_count": req_int(data, "target_room_count", 1),
            "budget_cap_cents": req_int(data, "budget_cap_cents", 1),
            "negotiation_round": 0,
        }
    )
    rec["_response_deadline"] = db.parse_dt(rec["response_deadline"], "response_deadline")
    db.rfp_cycles[rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@app.route("/rfp-cycles", methods=["GET"])
def list_rfp_cycles():
    auth(*RFP_GET_ROLES)
    return list_endpoint(db.rfp_cycles, [("station_id", "station_id"), ("status", "status")])


@app.route("/rfp-cycles/<cid>", methods=["GET"])
def get_rfp_cycle(cid):
    auth(*RFP_GET_ROLES)
    return success_obj(db.public(_get_cycle(cid)))


@app.route("/rfp-cycles/<cid>/open", methods=["POST"])
def open_rfp_cycle(cid):
    auth("SourcingManager")
    with db.LOCK:
        cycle = _get_cycle(cid)
        if cycle["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "cycle is %s, cannot open" % cycle["status"])
        if not (cycle["_response_deadline"] > db.CLOCK):
            raise err("ERR_DEADLINE_PASSED", "response_deadline has passed; cycle cannot open")
        cycle["status"] = "OPEN"
        db.touch(cycle)
        return success_obj(db.public(cycle))


@app.route("/rfp-cycles/<cid>/close", methods=["POST"])
def close_rfp_cycle(cid):
    auth("SourcingManager")
    with db.LOCK:
        cycle = _get_cycle(cid)
        if cycle["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "cycle is %s, cannot close" % cycle["status"])
        cycle["status"] = "EVALUATION"
        db.touch(cycle)
        for p in db.rfp_proposals.values():
            if p["rfp_cycle_id"] == cycle["id"] and p["status"] == "SUBMITTED":
                p["status"] = "UNDER_REVIEW"
                db.touch(p)
        return success_obj(db.public(cycle))


@app.route("/rfp-cycles/<cid>/open-negotiation", methods=["POST"])
def open_negotiation(cid):
    auth("SourcingManager")
    with db.LOCK:
        cycle = _get_cycle(cid)
        if cycle["status"] == "EVALUATION":
            has_shortlisted = any(
                p["rfp_cycle_id"] == cycle["id"] and p["status"] == "SHORTLISTED"
                for p in db.rfp_proposals.values()
            )
            if not has_shortlisted:
                raise err(
                    "ERR_INVALID_STATE",
                    "no SHORTLISTED proposal; negotiation cannot open",
                )
            cycle["status"] = "NEGOTIATION"
            cycle["negotiation_round"] += 1
            db.touch(cycle)
        elif cycle["status"] == "NEGOTIATION":
            cycle["status"] = "EVALUATION"
            db.touch(cycle)
        else:
            raise err(
                "ERR_INVALID_STATE",
                "cycle is %s, open-negotiation not available" % cycle["status"],
            )
        return success_obj(db.public(cycle))


@app.route("/rfp-cycles/<cid>/award", methods=["POST"])
def award_rfp_cycle(cid):
    auth("SourcingManager")
    data = body()
    with db.LOCK:
        cycle = _get_cycle(cid)
        # existence: body FK proposal_id resolves left-to-right
        proposal_id = data.get("proposal_id")
        if proposal_id is not None and not isinstance(proposal_id, str):
            _bad("proposal_id", "must be a string")
        proposal = db.rfp_proposals.get(proposal_id) if proposal_id else None
        if proposal is None or proposal["rfp_cycle_id"] != cycle["id"]:
            raise err("ERR_NOT_FOUND", "proposal not found in this cycle: %s" % proposal_id)
        # OCC: stale reads are rejected before any state/business evaluation
        expected = data.get("expected_cycle_version")
        if expected is not None:
            if isinstance(expected, bool) or not isinstance(expected, int):
                _bad("expected_cycle_version", "must be an integer")
            if expected != cycle["version"]:
                raise err(
                    "ERR_STALE_VERSION",
                    "cycle version is %d, expected %d" % (cycle["version"], expected),
                )
        # state legality
        if cycle["status"] != "NEGOTIATION":
            raise err("ERR_INVALID_STATE", "cycle is %s, cannot award" % cycle["status"])
        if proposal["status"] != "SHORTLISTED":
            raise err("ERR_INVALID_STATE", "proposal is %s, cannot award" % proposal["status"])
        # business gates (union before budget) on raw payload fields
        quiet = data.get("quiet_room_standard")
        if quiet in ("BASIC", "ENHANCED", "PREMIUM"):
            svc.check_union_compliance(quiet, data.get("blackout_protection"))
        if isinstance(data.get("room_block_size"), int) and not isinstance(
            data.get("room_block_size"), bool
        ):
            if isinstance(data.get("start_date"), str) and isinstance(data.get("end_date"), str):
                start_dt = db.parse_dt(data["start_date"], "start_date")
                end_dt = db.parse_dt(data["end_date"], "end_date")
                if end_dt > start_dt and data["room_block_size"] >= 1:
                    value = svc.contract_value_cents(
                        proposal["current_rate_cents"],
                        data["room_block_size"],
                        start_dt,
                        end_dt,
                    )
                    if value > cycle["budget_cap_cents"]:
                        raise err(
                            "ERR_BUDGET_EXCEEDED",
                            "contract value %d exceeds budget cap %d"
                            % (value, cycle["budget_cap_cents"]),
                        )
        # request shape (priority 17)
        room_block_size = req_int(data, "room_block_size", 1)
        start_dt = req_dt(data, "start_date")
        end_dt = req_dt(data, "end_date")
        if not (end_dt > start_dt):
            _bad("end_date", "must be after start_date")
        late_cancel_hours = req_int(data, "late_cancel_hours", 0)
        quiet = req_enum(data, "quiet_room_standard", ("BASIC", "ENHANCED", "PREMIUM"))
        security_requirements = opt_str_list(data, "security_requirements")
        blackout_dates = opt_date_list(data, "blackout_dates")
        blackout_protection = opt_bool(data, "blackout_protection", False)

        total_value = svc.contract_value_cents(
            proposal["current_rate_cents"], room_block_size, start_dt, end_dt
        )
        contract = db.stamp_new(
            {
                "rfp_cycle_id": cycle["id"],
                "station_id": cycle["station_id"],
                "vendor_id": proposal["vendor_id"],
                "proposal_id": proposal["id"],
                "status": "DRAFT",
                "room_block_size": room_block_size,
                "negotiated_rate_cents": proposal["current_rate_cents"],
                "start_date": db.iso(start_dt),
                "end_date": db.iso(end_dt),
                "late_cancel_hours": late_cancel_hours,
                "quiet_room_standard": quiet,
                "security_requirements": security_requirements,
                "blackout_dates": blackout_dates,
                "blackout_protection": blackout_protection,
                "remediation_deadline": None,
                "total_contract_value_cents": total_value,
            }
        )
        contract["_start_date"] = start_dt
        contract["_end_date"] = end_dt
        db.contracts[contract["id"]] = contract

        proposal["status"] = "ACCEPTED"
        db.touch(proposal)
        for p in db.rfp_proposals.values():
            if (
                p["rfp_cycle_id"] == cycle["id"]
                and p["id"] != proposal["id"]
                and p["status"] in ("SUBMITTED", "UNDER_REVIEW", "SHORTLISTED")
            ):
                p["status"] = "REJECTED"
                db.touch(p)
        cycle["status"] = "AWARDED"
        db.touch(cycle)
        return success_obj(db.public(contract), 201)


@app.route("/rfp-cycles/<cid>/cancel", methods=["POST"])
def cancel_rfp_cycle(cid):
    auth("SourcingManager")
    with db.LOCK:
        cycle = _get_cycle(cid)
        if cycle["status"] not in ("DRAFT", "OPEN", "EVALUATION", "NEGOTIATION"):
            raise err("ERR_INVALID_STATE", "cycle is %s, cannot cancel" % cycle["status"])
        cycle["status"] = "CANCELLED"
        db.touch(cycle)
        for p in db.rfp_proposals.values():
            if p["rfp_cycle_id"] == cycle["id"] and p["status"] in (
                "SUBMITTED",
                "UNDER_REVIEW",
                "SHORTLISTED",
            ):
                p["status"] = "REJECTED"
                db.touch(p)
        return success_obj(db.public(cycle))


# ===========================================================================
# RFP proposals
# ===========================================================================

PROPOSAL_GET_ROLES = ("PlatformAdmin", "SourcingManager", "FinanceAnalyst", "HotelVendorRep")


def _get_proposal(pid):
    return svc.get_or_404(db.rfp_proposals, pid, "rfp proposal")


@app.route("/rfp-cycles/<cid>/proposals", methods=["POST"])
def submit_proposal(cid):
    auth("HotelVendorRep")
    data = body()
    with db.LOCK:
        cycle = _get_cycle(cid)
        vendor_id = data.get("vendor_id")
        if vendor_id is not None and not isinstance(vendor_id, str):
            _bad("vendor_id", "must be a string")
        if vendor_id is None:
            _bad("vendor_id", "required")
        vendor = db.vendors.get(vendor_id)
        if vendor is None:
            raise err("ERR_NOT_FOUND", "hotel vendor not found: %s" % vendor_id)
        if cycle["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "cycle is %s, not accepting proposals" % cycle["status"])
        if db.CLOCK > cycle["_response_deadline"]:
            raise err("ERR_DEADLINE_PASSED", "response_deadline has passed")
        offered_room_count = req_int(data, "offered_room_count", 1)
        offered_rate_cents = req_int(data, "offered_rate_cents", 0)
        quiet_room_commitment = req_int(data, "quiet_room_commitment", 0)
        blackout_dates = opt_date_list(data, "blackout_dates")
        rec = db.stamp_new(
            {
                "rfp_cycle_id": cycle["id"],
                "vendor_id": vendor_id,
                "offered_room_count": offered_room_count,
                "offered_rate_cents": offered_rate_cents,
                "current_rate_cents": offered_rate_cents,
                "status": "SUBMITTED",
                "quiet_room_commitment": quiet_room_commitment,
                "blackout_dates": blackout_dates,
            }
        )
        db.rfp_proposals[rec["id"]] = rec
        return success_obj(db.public(rec), 201)


@app.route("/rfp-proposals", methods=["GET"])
def list_proposals():
    auth(*PROPOSAL_GET_ROLES)
    return list_endpoint(
        db.rfp_proposals,
        [("rfp_cycle_id", "rfp_cycle_id"), ("vendor_id", "vendor_id"), ("status", "status")],
    )


@app.route("/rfp-proposals/<pid>", methods=["GET"])
def get_proposal(pid):
    auth(*PROPOSAL_GET_ROLES)
    return success_obj(db.public(_get_proposal(pid)))


@app.route("/rfp-proposals/<pid>/shortlist", methods=["POST"])
def shortlist_proposal(pid):
    auth("SourcingManager")
    with db.LOCK:
        p = _get_proposal(pid)
        cycle = db.rfp_cycles.get(p["rfp_cycle_id"])
        if p["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "proposal is %s, cannot shortlist" % p["status"])
        if cycle is None or cycle["status"] != "EVALUATION":
            raise err("ERR_INVALID_STATE", "parent cycle is not in EVALUATION")
        p["status"] = "SHORTLISTED"
        db.touch(p)
        return success_obj(db.public(p))


@app.route("/rfp-proposals/<pid>/reject", methods=["POST"])
def reject_proposal(pid):
    auth("SourcingManager")
    with db.LOCK:
        p = _get_proposal(pid)
        if p["status"] not in ("UNDER_REVIEW", "SHORTLISTED"):
            raise err("ERR_INVALID_STATE", "proposal is %s, cannot reject" % p["status"])
        p["status"] = "REJECTED"
        db.touch(p)
        return success_obj(db.public(p))


@app.route("/rfp-proposals/<pid>/withdraw", methods=["POST"])
def withdraw_proposal(pid):
    auth("HotelVendorRep")
    with db.LOCK:
        p = _get_proposal(pid)
        # entity-backed ownership: X-User-ID must equal the proposal's vendor_id
        if caller_id() != p["vendor_id"]:
            raise err("ERR_FORBIDDEN", "only the owning vendor's representative may withdraw")
        if p["status"] not in ("SUBMITTED", "UNDER_REVIEW", "SHORTLISTED"):
            raise err("ERR_INVALID_STATE", "proposal is %s, cannot withdraw" % p["status"])
        p["status"] = "WITHDRAWN"
        db.touch(p)
        return success_obj(db.public(p))


@app.route("/rfp-proposals/<pid>/counter-offer", methods=["POST"])
def counter_offer_proposal(pid):
    auth("SourcingManager")
    data = body()
    with db.LOCK:
        p = _get_proposal(pid)
        cycle = db.rfp_cycles.get(p["rfp_cycle_id"])
        if p["status"] != "SHORTLISTED" or cycle is None or cycle["status"] != "NEGOTIATION":
            raise err("ERR_NOT_NEGOTIABLE", "proposal not SHORTLISTED or cycle not in NEGOTIATION")
        new_rate = req_int(data, "new_rate_cents", 0)
        p["current_rate_cents"] = new_rate
        db.touch(p)
        return success_obj(db.public(p))


# ===========================================================================
# Contracts
# ===========================================================================


def _get_contract(cid):
    return svc.get_or_404(db.contracts, cid, "contract")


@app.route("/contracts", methods=["GET"])
def list_contracts():
    auth(*ALL)
    return list_endpoint(
        db.contracts,
        [
            ("station_id", "station_id"),
            ("vendor_id", "vendor_id"),
            ("status", "status"),
            ("rfp_cycle_id", "rfp_cycle_id"),
            ("proposal_id", "proposal_id"),
        ],
    )


@app.route("/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    auth(*ALL)
    return success_obj(db.public(_get_contract(cid)))


@app.route("/contracts/<cid>/activate", methods=["POST"])
def activate_contract(cid):
    auth("SourcingManager")
    with db.LOCK:
        contract = _get_contract(cid)
        if contract["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "contract is %s, cannot activate" % contract["status"])
        # union compliance gate (priority 6)
        svc.check_union_compliance(contract["quiet_room_standard"], contract["blackout_protection"])
        # vendor gate (priority 7)
        vendor = db.vendors.get(contract["vendor_id"])
        if vendor is None or vendor["status"] != "ACTIVE":
            raise err("ERR_VENDOR_INACTIVE", "contract vendor is not ACTIVE")
        # date ordering precondition
        if not (contract["_start_date"] <= contract["_end_date"]):
            raise err("ERR_INVALID_REQUEST", "start_date must be on or before end_date")
        contract["status"] = "ACTIVE"
        db.touch(contract)
        return success_obj(db.public(contract))


@app.route("/contracts/<cid>/remediate", methods=["POST"])
def remediate_contract(cid):
    auth("SourcingManager")
    with db.LOCK:
        contract = _get_contract(cid)
        if contract["status"] != "SUSPENDED":
            raise err("ERR_INVALID_STATE", "contract is %s, cannot remediate" % contract["status"])
        blocking = any(
            a["contract_id"] == contract["id"]
            and a["severity"] == "CRITICAL"
            and a["status"] in ("OPEN", "IN_PROGRESS")
            for a in db.audits.values()
        )
        if blocking:
            raise err(
                "ERR_INVALID_STATE",
                "an open CRITICAL audit remains against this contract",
            )
        contract["status"] = "ACTIVE"
        contract["remediation_deadline"] = None
        db.touch(contract)
        return success_obj(db.public(contract))


@app.route("/contracts/<cid>/terminate", methods=["POST"])
def terminate_contract(cid):
    auth("SourcingManager")
    with db.LOCK:
        contract = _get_contract(cid)
        if contract["status"] not in ("ACTIVE", "SUSPENDED"):
            raise err("ERR_INVALID_STATE", "contract is %s, cannot terminate" % contract["status"])
        if contract["status"] == "ACTIVE":
            strikes = sum(
                1
                for f in db.feedback.values()
                if f["contract_id"] == contract["id"] and f["rating"] <= 2
            )
            if strikes < 3:
                raise err(
                    "ERR_TERMINATION_THRESHOLD",
                    "three-strike rule requires >= 3 low-rated feedback rows (have %d)" % strikes,
                )
        svc.terminate_contract(contract)
        return success_obj(db.public(contract))


# ===========================================================================
# Layover requirements
# ===========================================================================

LAYOVER_GET_ROLES = ("PlatformAdmin", "SourcingManager", "CrewOps", "FinanceAnalyst", "CrewAuditor")


def _get_layover(lid):
    return svc.get_or_404(db.layovers, lid, "layover requirement")


@app.route("/layover-requirements", methods=["POST"])
def create_layover():
    auth("CrewOps")
    data = body()
    station_id = data.get("station_id")
    if station_id is not None and not isinstance(station_id, str):
        _bad("station_id", "must be a string")
    if station_id is None:
        _bad("station_id", "required")
    station = db.stations.get(station_id)
    if station is None:
        raise err("ERR_NOT_FOUND", "station not found: %s" % station_id)
    crew_type = req_enum(data, "crew_type", ("PILOT", "FLIGHT_ATTENDANT"))
    crew_count = req_int(data, "crew_count", 1)
    arrival = req_dt(data, "arrival_time")
    departure = req_dt(data, "departure_time")
    if not (departure > arrival):
        _bad("departure_time", "must be after arrival_time")
    required_rest_hours = req_int(data, "required_rest_hours", 1)
    is_irregular_ops = opt_bool(data, "is_irregular_ops", False)
    rec = db.stamp_new(
        {
            "station_id": station_id,
            "crew_type": crew_type,
            "crew_count": crew_count,
            "arrival_time": db.iso(arrival),
            "departure_time": db.iso(departure),
            "required_rest_hours": required_rest_hours,
            "status": "PLANNED",
            "is_irregular_ops": is_irregular_ops,
            "rest_compliant": False,
        }
    )
    rec["_arrival_time"] = arrival
    rec["_departure_time"] = departure
    rec["rest_compliant"] = svc.compute_rest_compliant(rec)
    db.layovers[rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@app.route("/layover-requirements", methods=["GET"])
def list_layovers():
    auth(*LAYOVER_GET_ROLES)
    return list_endpoint(
        db.layovers,
        [("station_id", "station_id"), ("status", "status"), ("crew_type", "crew_type")],
    )


@app.route("/layover-requirements/<lid>", methods=["GET"])
def get_layover(lid):
    auth(*LAYOVER_GET_ROLES)
    return success_obj(db.public(_get_layover(lid)))


@app.route("/layover-requirements/<lid>/book", methods=["POST"])
def book_layover(lid):
    auth("CrewOps")
    data = body()
    with db.LOCK:
        lay = _get_layover(lid)
        # existence: body FK contract_id
        contract_id = data.get("contract_id")
        if contract_id is not None and not isinstance(contract_id, str):
            _bad("contract_id", "must be a string")
        contract = db.contracts.get(contract_id) if contract_id else None
        if contract is None:
            raise err("ERR_NOT_FOUND", "contract not found: %s" % contract_id)
        # OCC before any business evaluation (PRD 2.9 / 3.6)
        expected = data.get("expected_layover_version")
        if expected is not None:
            if isinstance(expected, bool) or not isinstance(expected, int):
                _bad("expected_layover_version", "must be an integer")
            if expected != lay["version"]:
                raise err(
                    "ERR_STALE_VERSION",
                    "layover version is %d, expected %d" % (lay["version"], expected),
                )
        # state legality
        if lay["status"] != "PLANNED":
            raise err("ERR_INVALID_STATE", "layover is %s, cannot book" % lay["status"])
        if contract["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "contract is %s, cannot book against it" % contract["status"])
        if contract["station_id"] != lay["station_id"]:
            raise err(
                "ERR_INVALID_REQUEST",
                "contract station does not match layover station",
            )
        # business gauntlet in priority order
        if lay["rest_compliant"] is not True:
            raise err("ERR_REST_VIOLATION", "layover is not rest-compliant")
        stay_raw = data.get("stay_date")
        # PRD 3.6: stay_date is a UTC calendar date; compare against
        # blackout_dates (YYYY-MM-DD) by date portion.
        stay_date_str = _norm_stay_date(stay_raw) if isinstance(stay_raw, str) else stay_raw
        is_blackout = isinstance(stay_date_str, str) and stay_date_str in contract["blackout_dates"]
        if is_blackout and contract["blackout_protection"] is not True:
            raise err("ERR_BLACKOUT_DATE", "stay_date is a blackout date without protection")
        if is_blackout:
            brc = data.get("blackout_rate_cents")
            if isinstance(brc, bool) or not isinstance(brc, int) or brc < 0:
                raise err(
                    "ERR_BLACKOUT_DATE",
                    "blackout_rate_cents is required (>= 0) for a protected blackout date",
                )
        occupied = any(
            a["layover_requirement_id"] == lay["id"] and a["status"] in ("HELD", "CONFIRMED")
            for a in db.allocations.values()
        )
        if occupied:
            raise err("ERR_LAYOVER_ALREADY_BOOKED", "layover already has a HELD or CONFIRMED allocation")
        # shape: stay_date
        if stay_raw is None:
            _bad("stay_date", "required")
        if isinstance(stay_raw, str) and db.is_valid_date_str(stay_raw):
            stay_dt = db.date_str_to_dt(stay_raw)
            stay_out = stay_raw
        else:
            stay_dt = db.parse_dt(stay_raw, "stay_date")
            stay_out = db.iso(stay_dt)
        confirmed_same_date = sum(
            1
            for a in db.allocations.values()
            if a["contract_id"] == contract["id"]
            and a["status"] == "CONFIRMED"
            and a["stay_date"] == stay_out
        )
        if confirmed_same_date >= contract["room_block_size"]:
            raise err(
                "ERR_ROOM_BLOCK_EXHAUSTED",
                "contract room block exhausted for %s" % stay_out,
            )
        nightly_rate = (
            data["blackout_rate_cents"] if is_blackout else contract["negotiated_rate_cents"]
        )
        alloc = db.stamp_new(
            {
                "layover_requirement_id": lay["id"],
                "contract_id": contract["id"],
                "vendor_id": None,
                "kind": "CONTRACTED",
                "status": "HELD",
                "rooms_held": lay["crew_count"],
                "nightly_rate_cents": nightly_rate,
                "blackout_rate_cents": data.get("blackout_rate_cents"),
                "stay_date": stay_out,
                "distressed_cost_cents": None,
            }
        )
        alloc["_stay_date"] = stay_dt
        alloc["_late_cancel"] = False
        db.allocations[alloc["id"]] = alloc
        lay["status"] = "CONFIRMED"
        db.touch(lay)
        return success_obj(db.public(alloc), 201)


@app.route("/layover-requirements/<lid>/distressed-book", methods=["POST"])
def distressed_book_layover(lid):
    auth("CrewOps")
    data = body()
    with db.LOCK:
        lay = _get_layover(lid)
        vendor_id = data.get("vendor_id")
        if vendor_id is not None and not isinstance(vendor_id, str):
            _bad("vendor_id", "must be a string")
        if vendor_id is None:
            _bad("vendor_id", "required")
        vendor = db.vendors.get(vendor_id)
        if vendor is None:
            raise err("ERR_NOT_FOUND", "hotel vendor not found: %s" % vendor_id)
        if lay["status"] != "SURGED":
            raise err("ERR_INVALID_STATE", "layover is %s, cannot distressed-book" % lay["status"])
        if vendor["status"] != "ACTIVE":
            raise err("ERR_VENDOR_INACTIVE", "vendor is not ACTIVE")
        rate_cents = req_int(data, "rate_cents", 0)
        stay_dt = lay["_arrival_time"]
        alloc = db.stamp_new(
            {
                "layover_requirement_id": lay["id"],
                "contract_id": None,
                "vendor_id": vendor_id,
                "kind": "DISTRESSED",
                "status": "HELD",
                "rooms_held": lay["crew_count"],
                "nightly_rate_cents": rate_cents,
                "blackout_rate_cents": None,
                "stay_date": db.iso(stay_dt),
                "distressed_cost_cents": None,
            }
        )
        alloc["_stay_date"] = stay_dt
        alloc["_late_cancel"] = False
        db.allocations[alloc["id"]] = alloc
        lay["status"] = "CONFIRMED"
        db.touch(lay)
        return success_obj(db.public(alloc), 201)


@app.route("/layover-requirements/<lid>/cancel", methods=["POST"])
def cancel_layover(lid):
    auth("CrewOps")
    with db.LOCK:
        lay = _get_layover(lid)
        if lay["status"] not in ("PLANNED", "CONFIRMED", "SURGED"):
            raise err("ERR_INVALID_STATE", "layover is %s, cannot cancel" % lay["status"])
        for a in db.allocations.values():
            if a["layover_requirement_id"] == lay["id"] and a["status"] in ("HELD", "CONFIRMED"):
                a["status"] = "CANCELLED"
                svc.mark_cancellation_chargeability(a)
                db.touch(a)
        for t in db.transport_trips.values():
            if t["layover_requirement_id"] == lay["id"] and t["status"] == "SCHEDULED":
                t["status"] = "CANCELLED"
                db.touch(t)
        lay["status"] = "CANCELLED"
        db.touch(lay)
        return success_obj(db.public(lay))


@app.route("/layover-requirements/<lid>/transport-trips", methods=["POST"])
def schedule_transport_trip(lid):
    auth("CrewOps")
    data = body()
    with db.LOCK:
        lay = _get_layover(lid)
        direction = data.get("direction")
        if direction not in ("AIRPORT_TO_HOTEL", "HOTEL_TO_AIRPORT"):
            if direction is None:
                _bad("direction", "required")
            _bad("direction", "must be AIRPORT_TO_HOTEL or HOTEL_TO_AIRPORT")
        if lay["status"] != "CONFIRMED":
            raise err(
                "ERR_INVALID_STATE",
                "layover is %s, transport can only be scheduled when CONFIRMED" % lay["status"],
            )
        vehicle_capacity = req_int(data, "vehicle_capacity", 1)
        pickup_dt = svc.compute_pickup_time(lay, direction)
        for t in db.transport_trips.values():
            if (
                t["layover_requirement_id"] == lay["id"]
                and t["direction"] == direction
                and t["status"] != "CANCELLED"
                and t["_pickup_time"] == pickup_dt
            ):
                raise err(
                    "ERR_PICKUP_CONFLICT",
                    "a trip with the same pickup_time already exists for this layover and direction",
                )
        contract_id = None
        for a in db.allocations.values():
            if (
                a["layover_requirement_id"] == lay["id"]
                and a["kind"] == "CONTRACTED"
                and a["status"] in ("HELD", "CONFIRMED")
            ):
                contract_id = a["contract_id"]
                break
        rec = db.stamp_new(
            {
                "layover_requirement_id": lay["id"],
                "contract_id": contract_id,
                "direction": direction,
                "pickup_time": db.iso(pickup_dt),
                "status": "SCHEDULED",
                "vehicle_capacity": vehicle_capacity,
            }
        )
        rec["_pickup_time"] = pickup_dt
        db.transport_trips[rec["id"]] = rec
        return success_obj(db.public(rec), 201)


# ===========================================================================
# Room allocations
# ===========================================================================


def _get_allocation(aid):
    return svc.get_or_404(db.allocations, aid, "room allocation")


@app.route("/allocations", methods=["GET"])
def list_allocations():
    auth(*ALL)
    return list_endpoint(
        db.allocations,
        [
            ("layover_requirement_id", "layover_requirement_id"),
            ("contract_id", "contract_id"),
            ("vendor_id", "vendor_id"),
            ("status", "status"),
            ("kind", "kind"),
            ("stay_date", "stay_date"),
        ],
    )


@app.route("/allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    auth(*ALL)
    return success_obj(db.public(_get_allocation(aid)))


@app.route("/allocations/<aid>/confirm", methods=["POST"])
def confirm_allocation(aid):
    auth("CrewOps")
    with db.LOCK:
        a = _get_allocation(aid)
        if a["status"] != "HELD":
            raise err("ERR_INVALID_STATE", "allocation is %s, cannot confirm" % a["status"])
        lay = db.layovers.get(a["layover_requirement_id"])
        if lay is None or lay["status"] != "CONFIRMED":
            raise err("ERR_INVALID_STATE", "allocation's layover is not CONFIRMED")
        if a["kind"] == "DISTRESSED":
            a["distressed_cost_cents"] = svc.compute_distressed_cost(a)
        a["status"] = "CONFIRMED"
        db.touch(a)
        return success_obj(db.public(a))


@app.route("/allocations/<aid>/check-in", methods=["POST"])
def check_in_allocation(aid):
    auth("HotelVendorRep")
    with db.LOCK:
        a = _get_allocation(aid)
        if a["status"] != "CONFIRMED":
            raise err("ERR_INVALID_STATE", "allocation is %s, cannot check in" % a["status"])
        if a["_stay_date"].date() > db.CLOCK.date():
            raise err("ERR_INVALID_STATE", "cannot check in before the stay date")
        a["status"] = "CHECKED_IN"
        db.touch(a)
        lay = db.layovers.get(a["layover_requirement_id"])
        if lay is not None and lay["status"] == "CONFIRMED":
            lay["status"] = "COMPLETED"
            db.touch(lay)
        return success_obj(db.public(a))


@app.route("/allocations/<aid>/no-show", methods=["POST"])
def no_show_allocation(aid):
    auth("CrewOps")
    with db.LOCK:
        a = _get_allocation(aid)
        if a["status"] != "CONFIRMED":
            raise err("ERR_INVALID_STATE", "allocation is %s, cannot mark no-show" % a["status"])
        if not (db.CLOCK.date() > a["_stay_date"].date()):
            raise err("ERR_INVALID_STATE", "no-show is only allowed after the stay date")
        a["status"] = "NO_SHOW"
        db.touch(a)
        return success_obj(db.public(a))


@app.route("/allocations/<aid>/release", methods=["POST"])
def release_allocation(aid):
    auth("CrewOps")
    with db.LOCK:
        a = _get_allocation(aid)
        if a["status"] != "HELD":
            raise err("ERR_INVALID_STATE", "allocation is %s, cannot release" % a["status"])
        a["status"] = "RELEASED"
        db.touch(a)
        lay = db.layovers.get(a["layover_requirement_id"])
        if lay is not None and lay["status"] == "CONFIRMED":
            lay["status"] = "SURGED"
            db.touch(lay)
        return success_obj(db.public(a))


# ===========================================================================
# Transport trips
# ===========================================================================

TRIP_GET_ROLES = ("PlatformAdmin", "SourcingManager", "CrewOps", "CrewAuditor")


def _get_trip(tid):
    return svc.get_or_404(db.transport_trips, tid, "transport trip")


@app.route("/transport-trips", methods=["GET"])
def list_trips():
    auth(*TRIP_GET_ROLES)
    return list_endpoint(
        db.transport_trips,
        [
            ("layover_requirement_id", "layover_requirement_id"),
            ("contract_id", "contract_id"),
            ("status", "status"),
            ("direction", "direction"),
        ],
    )


@app.route("/transport-trips/<tid>", methods=["GET"])
def get_trip(tid):
    auth(*TRIP_GET_ROLES)
    return success_obj(db.public(_get_trip(tid)))


@app.route("/transport-trips/<tid>/dispatch", methods=["POST"])
def dispatch_trip(tid):
    auth("CrewOps")
    with db.LOCK:
        t = _get_trip(tid)
        if t["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "trip is %s, cannot dispatch" % t["status"])
        lay = db.layovers.get(t["layover_requirement_id"])
        if lay is None or lay["status"] != "CONFIRMED":
            raise err("ERR_INVALID_STATE", "trip's layover is not CONFIRMED")
        t["status"] = "DISPATCHED"
        db.touch(t)
        return success_obj(db.public(t))


@app.route("/transport-trips/<tid>/complete", methods=["POST"])
def complete_trip(tid):
    auth("CrewOps")
    with db.LOCK:
        t = _get_trip(tid)
        if t["status"] != "DISPATCHED":
            raise err("ERR_INVALID_STATE", "trip is %s, cannot complete" % t["status"])
        t["status"] = "COMPLETED"
        db.touch(t)
        return success_obj(db.public(t))


# ===========================================================================
# Crew feedback
# ===========================================================================

FEEDBACK_GET_ROLES = ("PlatformAdmin", "SourcingManager", "CrewOps", "CrewAuditor")


@app.route("/crew-feedback", methods=["POST"])
def create_feedback():
    auth("CrewOps")
    data = body()
    contract_id = data.get("contract_id")
    if contract_id is not None and not isinstance(contract_id, str):
        _bad("contract_id", "must be a string")
    if contract_id is None:
        _bad("contract_id", "required")
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise err("ERR_NOT_FOUND", "contract not found: %s" % contract_id)
    layover_id = data.get("layover_requirement_id")
    if layover_id is not None and not isinstance(layover_id, str):
        _bad("layover_requirement_id", "must be a string")
    if layover_id is None:
        _bad("layover_requirement_id", "required")
    lay = db.layovers.get(layover_id)
    if lay is None:
        raise err("ERR_NOT_FOUND", "layover requirement not found: %s" % layover_id)
    rec = db.stamp_new(
        {
            "contract_id": contract_id,
            "layover_requirement_id": layover_id,
            "crew_type": req_enum(data, "crew_type", ("PILOT", "FLIGHT_ATTENDANT")),
            "rating": req_int(data, "rating", 1, 5),
            "category": req_enum(
                data, "category", ("NOISE", "SECURITY", "CLEANLINESS", "TRANSPORT", "OTHER")
            ),
            "comment": opt_str(data, "comment", ""),
        },
        common=False,  # feedback rows carry only id + created_at (PRD 2.7)
    )
    db.feedback[rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@app.route("/crew-feedback", methods=["GET"])
def list_feedback():
    auth(*FEEDBACK_GET_ROLES)
    return list_endpoint(
        db.feedback,
        [
            ("contract_id", "contract_id"),
            ("layover_requirement_id", "layover_requirement_id"),
            ("rating", "rating"),
        ],
    )


@app.route("/crew-feedback/<fid>", methods=["GET"])
def get_feedback(fid):
    auth(*FEEDBACK_GET_ROLES)
    return success_obj(db.public(svc.get_or_404(db.feedback, fid, "crew feedback")))


# ===========================================================================
# Audits
# ===========================================================================

AUDIT_GET_ROLES = ("PlatformAdmin", "SourcingManager", "CrewAuditor")


def _get_audit(aid):
    return svc.get_or_404(db.audits, aid, "audit")


@app.route("/audits", methods=["POST"])
def create_audit():
    auth("CrewAuditor")
    data = body()
    with db.LOCK:
        contract_id = data.get("contract_id")
        if contract_id is not None and not isinstance(contract_id, str):
            _bad("contract_id", "must be a string")
        if contract_id is None:
            _bad("contract_id", "required")
        contract = db.contracts.get(contract_id)
        if contract is None:
            raise err("ERR_NOT_FOUND", "contract not found: %s" % contract_id)
        severity = req_enum(data, "severity", ("MINOR", "MAJOR", "CRITICAL"))
        rec = db.stamp_new(
            {
                "contract_id": contract_id,
                "auditor_id": req_str(data, "auditor_id"),
                "status": "OPEN",
                "severity": severity,
                "findings": req_str(data, "findings"),
                "opened_at": db.now_iso(),
            }
        )
        db.audits[rec["id"]] = rec
        if severity == "CRITICAL" and contract["status"] == "ACTIVE":
            svc.suspend_contract(contract)
        return success_obj(db.public(rec), 201)


@app.route("/audits", methods=["GET"])
def list_audits():
    auth(*AUDIT_GET_ROLES)
    return list_endpoint(
        db.audits,
        [("contract_id", "contract_id"), ("status", "status"), ("severity", "severity")],
    )


@app.route("/audits/<aid>", methods=["GET"])
def get_audit(aid):
    auth(*AUDIT_GET_ROLES)
    return success_obj(db.public(_get_audit(aid)))


@app.route("/audits/<aid>/start", methods=["POST"])
def start_audit(aid):
    auth("CrewAuditor")
    with db.LOCK:
        a = _get_audit(aid)
        if a["status"] != "OPEN":
            raise err("ERR_INVALID_STATE", "audit is %s, cannot start" % a["status"])
        a["status"] = "IN_PROGRESS"
        db.touch(a)
        return success_obj(db.public(a))


@app.route("/audits/<aid>/close", methods=["POST"])
def close_audit(aid):
    auth("CrewAuditor")
    data = body()
    with db.LOCK:
        a = _get_audit(aid)
        if a["status"] != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE", "audit is %s, cannot close" % a["status"])
        outcome = data.get("outcome")
        if outcome not in ("PASS", "FAIL"):
            _bad("outcome", "must be PASS or FAIL")
        a["status"] = "CLOSED_PASS" if outcome == "PASS" else "CLOSED_FAIL"
        db.touch(a)
        if outcome == "FAIL":
            contract = db.contracts.get(a["contract_id"])
            if contract is not None and contract["status"] in ("ACTIVE", "SUSPENDED"):
                svc.terminate_contract(contract)
        return success_obj(db.public(a))


# ===========================================================================
# Invoices
# ===========================================================================

INVOICE_GET_ROLES = ("PlatformAdmin", "SourcingManager", "FinanceAnalyst", "HotelVendorRep")


def _get_invoice(iid):
    return svc.get_or_404(db.invoices, iid, "invoice")


@app.route("/invoices", methods=["POST"])
def create_invoice():
    auth("HotelVendorRep")
    data = body()
    contract_id = data.get("contract_id")
    if contract_id is not None and not isinstance(contract_id, str):
        _bad("contract_id", "must be a string")
    if contract_id is None:
        _bad("contract_id", "required")
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise err("ERR_NOT_FOUND", "contract not found: %s" % contract_id)
    start = req_dt(data, "billing_period_start")
    end = req_dt(data, "billing_period_end")
    if not (end >= start):
        _bad("billing_period_end", "must be on or after billing_period_start")
    rec = db.stamp_new(
        {
            "contract_id": contract_id,
            "billing_period_start": db.iso(start),
            "billing_period_end": db.iso(end),
            "status": "RECEIVED",
            "billed_room_nights": req_int(data, "billed_room_nights", 0),
            "billed_amount_cents": req_int(data, "billed_amount_cents", 0),
            "reconciled_room_nights": None,
            "reconciled_amount_cents": None,
            "variance_pct": None,
        }
    )
    rec["_billing_period_start"] = start
    rec["_billing_period_end"] = end
    db.invoices[rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@app.route("/invoices", methods=["GET"])
def list_invoices():
    auth(*INVOICE_GET_ROLES)
    return list_endpoint(db.invoices, [("contract_id", "contract_id"), ("status", "status")])


@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    auth(*INVOICE_GET_ROLES)
    return success_obj(db.public(_get_invoice(iid)))


@app.route("/invoices/<iid>/reconcile", methods=["POST"])
def reconcile_invoice(iid):
    auth("FinanceAnalyst")
    with db.LOCK:
        inv = _get_invoice(iid)
        if inv["status"] != "RECEIVED":
            raise err("ERR_INVALID_STATE", "invoice is %s, cannot reconcile" % inv["status"])
        svc.reconcile_invoice(inv)
        inv["status"] = "RECONCILED"
        db.touch(inv)
        return success_obj(db.public(inv))


@app.route("/invoices/<iid>/approve", methods=["POST"])
def approve_invoice(iid):
    auth("FinanceAnalyst")
    with db.LOCK:
        inv = _get_invoice(iid)
        if inv["status"] != "RECONCILED":
            raise err("ERR_INVALID_STATE", "invoice is %s, cannot approve" % inv["status"])
        # fiscal gate: variance must be within every union agreement's cap
        for ua in db.union_agreements.values():
            if inv["variance_pct"] is not None and inv["variance_pct"] > ua["max_invoice_variance_pct"]:
                raise err(
                    "ERR_INVOICE_VARIANCE_EXCEEDED",
                    "variance %s exceeds union cap %s"
                    % (inv["variance_pct"], ua["max_invoice_variance_pct"]),
                )
        inv["status"] = "APPROVED"
        db.touch(inv)
        return success_obj(db.public(inv))


@app.route("/invoices/<iid>/dispute", methods=["POST"])
def dispute_invoice(iid):
    auth("FinanceAnalyst")
    with db.LOCK:
        inv = _get_invoice(iid)
        if inv["status"] not in ("RECONCILED", "APPROVED"):
            raise err("ERR_INVALID_STATE", "invoice is %s, cannot dispute" % inv["status"])
        inv["status"] = "DISPUTED"
        db.touch(inv)
        return success_obj(db.public(inv))


@app.route("/invoices/<iid>/re-reconcile", methods=["POST"])
def re_reconcile_invoice(iid):
    auth("FinanceAnalyst")
    with db.LOCK:
        inv = _get_invoice(iid)
        if inv["status"] != "DISPUTED":
            raise err("ERR_INVALID_STATE", "invoice is %s, cannot re-reconcile" % inv["status"])
        svc.reconcile_invoice(inv)
        inv["status"] = "RECONCILED"
        db.touch(inv)
        return success_obj(db.public(inv))


@app.route("/invoices/<iid>/mark-paid", methods=["POST"])
def mark_paid_invoice(iid):
    auth("FinanceAnalyst")
    with db.LOCK:
        inv = _get_invoice(iid)
        if inv["status"] != "APPROVED":
            raise err("ERR_INVALID_STATE", "invoice is %s, cannot mark paid" % inv["status"])
        inv["status"] = "PAID"
        db.touch(inv)
        return success_obj(db.public(inv))


@app.route("/invoices/<iid>/reject", methods=["POST"])
def reject_invoice(iid):
    auth("FinanceAnalyst")
    with db.LOCK:
        inv = _get_invoice(iid)
        if inv["status"] != "RECEIVED":
            raise err("ERR_INVALID_STATE", "invoice is %s, cannot reject" % inv["status"])
        inv["status"] = "REJECTED"
        db.touch(inv)
        return success_obj(db.public(inv))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
