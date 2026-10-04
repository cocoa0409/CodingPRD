"""International road transport security records — PRD §3.12, endpoints 136-143."""

import db
import core
import services
from core import ApiError, now_iso
from response import ok, page_of
from http_util import pagination, must_get, get_or_none, body
from routes._common import route
from models import create

CLASSIFICATIONS = ("NORMAL", "SENSITIVE", "HIGH_CONSEQUENCE")


def register(app):

    @route(app, "/api/security-records", ["POST"], ["ComplianceOfficer"])
    def create_record():
        raw = body()
        allowed = {"security_code", "origin_terminal_id", "destination_terminal_id",
                   "security_classification", "clearance_required",
                   "high_consequence_clearance", "convention_status", "consignor_code"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        for key in ("security_code", "origin_terminal_id", "security_classification",
                    "convention_status", "consignor_code"):
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        origin = get_or_none("Terminal", raw["origin_terminal_id"])
        if origin is None:
            raise ApiError("ERR_TERMINAL_NOT_FOUND")
        destination_id = raw.get("destination_terminal_id")
        if destination_id is not None:
            if get_or_none("Terminal", destination_id) is None:
                raise ApiError("ERR_TERMINAL_NOT_FOUND")
        if raw["security_classification"] not in CLASSIFICATIONS:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown security_classification.")
        if raw["convention_status"] not in CLASSIFICATIONS:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown convention_status.")
        _assert_unique_security_code(raw["security_code"])
        row = create("SecurityRecord", {
            "security_code": raw["security_code"],
            "origin_terminal_id": origin["id"],
            "destination_terminal_id": destination_id,
            "security_classification": raw["security_classification"],
            "clearance_required": bool(raw.get("clearance_required", False)),
            "high_consequence_clearance": bool(raw.get("high_consequence_clearance", False)),
            "convention_status": raw["convention_status"],
            "consignor_code": raw["consignor_code"],
            "outbound_lane_code": None,
        })
        row["record_status"] = "PENDING"
        _recompute_status(row)
        return ok(row, 201)

    @route(app, "/api/security-records", ["GET"], ["Any"])
    def list_records():
        limit, offset = pagination()
        return page_of(db.sort_created(db.all_rows("security_records")), limit, offset)

    @route(app, "/api/security-records/<rid>", ["GET"], ["Any"])
    def get_record(rid):
        return ok(must_get("SecurityRecord", rid))

    @route(app, "/api/security-records/<rid>/consignor-roll", ["POST"],
           ["ComplianceOfficer"])
    def consignor_roll(rid):
        """§3.12: rolling the consignor copies the record's own security_code into
        the consignor_code field."""
        row = must_get("SecurityRecord", rid)
        raw = body()
        _reject_unknown(raw)
        services.mark(row, "consignor_code", row.get("security_code"))
        services.flush(row)
        _recompute_status(row)
        return ok(row)

    @route(app, "/api/security-records/<rid>/route", ["POST"], ["ComplianceOfficer"])
    def route_record(rid):
        """§3.12: routing requires the client's expected_security_record_version to
        match the record's current version — a mismatch is refused with
        ERR_STALE_VERSION at HTTP 412."""
        row = must_get("SecurityRecord", rid)
        raw = body()
        allowed = {"destination_terminal_id", "expected_security_record_version"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if "destination_terminal_id" not in raw or "expected_security_record_version" not in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "destination_terminal_id and expected_security_record_version are required.")
        if raw["expected_security_record_version"] is not None:
            if int(raw["expected_security_record_version"]) != int(row.get("version", 1)):
                raise ApiError("ERR_STALE_VERSION",
                               "The security record version has advanced since it was read.")
        terminal = get_or_none("Terminal", raw["destination_terminal_id"])
        if terminal is None:
            raise ApiError("ERR_TERMINAL_NOT_FOUND")
        services.mark(row, "destination_terminal_id", terminal["id"])
        db.touch(row, now_iso())
        _recompute_status(row)
        return ok(row)

    @route(app, "/api/security-records/<rid>/clamp", ["POST"], ["ComplianceOfficer"])
    def clamp_record(rid):
        """§3.12: clamping sets convention_status to HIGH_CONSEQUENCE."""
        row = must_get("SecurityRecord", rid)
        raw = body()
        _reject_unknown(raw)
        services.mark(row, "convention_status", "HIGH_CONSEQUENCE")
        services.flush(row)
        _recompute_status(row)
        return ok(row)

    @route(app, "/api/security-records/<rid>/outbound-vessel-roll", ["POST"],
           ["ComplianceOfficer"])
    def outbound_roll(rid):
        """§3.12: assigns the supplied outbound_lane_code — a field that is null
        until the record is routed."""
        row = must_get("SecurityRecord", rid)
        raw = body()
        for key in raw:
            if key != "outbound_lane_code":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if "outbound_lane_code" not in raw:
            raise ApiError("ERR_INVALID_REQUEST", "outbound_lane_code is required.")
        services.mark(row, "outbound_lane_code", raw["outbound_lane_code"])
        services.flush(row)
        _recompute_status(row)
        return ok(row)

    @route(app, "/api/security-records/<rid>/reporting", ["POST"], ["ComplianceOfficer"])
    def reporting(rid):
        row = must_get("SecurityRecord", rid)
        raw = body()
        for key in raw:
            if key != "convention_status":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if "convention_status" not in raw:
            raise ApiError("ERR_INVALID_REQUEST", "convention_status is required.")
        if raw["convention_status"] not in CLASSIFICATIONS:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown convention_status.")
        services.mark(row, "convention_status", raw["convention_status"])
        services.flush(row)
        _recompute_status(row)
        return ok(row)


def _recompute_status(row):
    """§3.12: the record_status walks PENDING → ACTIVE → REPORTING → CLOSED, and
    convention_status is clamped to NORMAL while the record is in transit and to
    HIGH_CONSEQUENCE once the high-consequence clearance lands."""
    if row.get("high_consequence_clearance"):
        services.mark(row, "convention_status", "HIGH_CONSEQUENCE")
    if row.get("destination_terminal_id") is None:
        services.mark(row, "record_status", "PENDING")
    elif row.get("outbound_lane_code"):
        services.mark(row, "record_status", "REPORTING")
    else:
        services.mark(row, "record_status", "ACTIVE")
    services.flush(row)
    return row


def _reject_unknown(raw):
    for key in raw:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' is not declared for this endpoint." % key)


def _assert_unique_security_code(code):
    for r in db.all_rows("security_records"):
        if r.get("security_code") == code:
            raise ApiError("ERR_INVALID_REQUEST",
                           "The security code is already registered.")