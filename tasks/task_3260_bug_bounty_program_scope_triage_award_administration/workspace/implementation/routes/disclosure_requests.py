"""Disclosure request endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_FORBIDDEN, ERR_NEGOTIATION_EXHAUSTED, ERR_REPORT_NOT_RESOLVED,
    ERR_DISCLOSURE_TOO_EARLY, ERR_BLACKOUT_ACTIVE,
)
from helpers import (
    base_entity, touch, get_body, require_fields, reject_unknown_fields,
    parse_pagination,
)
from middleware import require_roles, check_researcher_owner
from response import success_object, success_list
from serializers import disclosure_out

bp = Blueprint("disclosure_requests", __name__)

CREATE_FIELDS = {"report_id", "proposed_publish_at"}
RESPOND_FIELDS = {"decision", "agreed_publish_at", "note"}
DECISIONS = {"COUNTER", "AGREE", "DENY", "PUBLISH"}


def _get_dr(did):
    d = db.disclosure_requests.get(did)
    if d is None:
        raise_err(ERR_NOT_FOUND, f"DisclosureRequest {did} not found")
    return d


@bp.route("/api/disclosure-requests", methods=["POST"])
def create_disclosure_request():
    user_id, role = require_roles({"Researcher"})
    body = get_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    require_fields(body, ["report_id", "proposed_publish_at"])
    report = db.reports.get(body["report_id"])
    if report is None:
        raise_err(ERR_NOT_FOUND, f"Report {body['report_id']} not found")
    check_researcher_owner(user_id, role, report["researcher_id"])
    try:
        proposed = clock.parse_iso(body["proposed_publish_at"])
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "proposed_publish_at malformed")
    d = base_entity()
    d.update(
        {
            "report_id": report["id"],
            "researcher_id": report["researcher_id"],
            "status": "REQUESTED",
            "proposed_publish_at": clock.iso(proposed),
            "agreed_publish_at": None,
            "negotiation_round": 0,
        }
    )
    db.disclosure_requests[d["id"]] = d
    return success_object(disclosure_out(d), 201)


@bp.route("/api/disclosure-requests/<disclosure_request_id>", methods=["GET"])
def read_disclosure_request(disclosure_request_id):
    require_roles({"PlatformAdmin", "ProgramAdmin", "Triager", "Researcher"})
    return success_object(disclosure_out(_get_dr(disclosure_request_id)))


@bp.route("/api/disclosure-requests", methods=["GET"])
def list_disclosure_requests():
    require_roles({"PlatformAdmin", "ProgramAdmin", "Triager", "Researcher"})
    limit, offset = parse_pagination(request.args)
    items = list(db.disclosure_requests.values())
    for f in ("report_id", "researcher_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [d for d in items if str(d.get(f)) == val]
    items.sort(key=lambda d: d["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([disclosure_out(d) for d in page], limit, offset, total)


@bp.route("/api/disclosure-requests/<disclosure_request_id>/respond", methods=["POST"])
def respond_disclosure_request(disclosure_request_id):
    user_id, role = require_roles({"Researcher", "ProgramAdmin"})
    d = _get_dr(disclosure_request_id)
    body = get_body()
    reject_unknown_fields(body, RESPOND_FIELDS)
    require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in DECISIONS:
        raise_err(ERR_INVALID_REQUEST, "Invalid decision")
    # ownership: Researcher acts only on own disclosure requests
    if role == "Researcher" and user_id != d["researcher_id"]:
        raise_err(ERR_FORBIDDEN, "Researcher may only act on own disclosure requests")
    # DENY and PUBLISH are ProgramAdmin-only
    if decision in ("DENY", "PUBLISH") and role != "ProgramAdmin":
        raise_err(ERR_FORBIDDEN, "Only ProgramAdmin may DENY or PUBLISH")

    st = d["status"]
    if decision == "COUNTER":
        if st not in ("REQUESTED", "UNDER_NEGOTIATION"):
            raise_err(ERR_INVALID_STATE, f"Cannot COUNTER disclosure in {st}")
        if d["negotiation_round"] >= 3:
            raise_err(ERR_NEGOTIATION_EXHAUSTED, "Negotiation rounds exhausted")
        d["negotiation_round"] += 1
        d["status"] = "UNDER_NEGOTIATION"
        if body.get("agreed_publish_at") is not None:
            try:
                d["proposed_publish_at"] = clock.iso(
                    clock.parse_iso(body["agreed_publish_at"])
                )
            except Exception:
                raise_err(ERR_INVALID_REQUEST, "agreed_publish_at malformed")
    elif decision == "AGREE":
        if st not in ("REQUESTED", "UNDER_NEGOTIATION"):
            raise_err(ERR_INVALID_STATE, f"Cannot AGREE disclosure in {st}")
        if body.get("agreed_publish_at") is not None:
            try:
                d["agreed_publish_at"] = clock.iso(
                    clock.parse_iso(body["agreed_publish_at"])
                )
            except Exception:
                raise_err(ERR_INVALID_REQUEST, "agreed_publish_at malformed")
        else:
            d["agreed_publish_at"] = d["proposed_publish_at"]
        d["status"] = "AGREED"
    elif decision == "DENY":
        if st not in ("REQUESTED", "UNDER_NEGOTIATION"):
            raise_err(ERR_INVALID_STATE, f"Cannot DENY disclosure in {st}")
        d["status"] = "DENIED"
    elif decision == "PUBLISH":
        if st != "AGREED":
            raise_err(ERR_INVALID_STATE, f"Cannot PUBLISH disclosure in {st}")
        report = db.reports[d["report_id"]]
        if report["status"] != "RESOLVED":
            raise_err(ERR_REPORT_NOT_RESOLVED, "Report is not RESOLVED")
        program = db.programs[report["program_id"]]
        now = clock.now()
        agreed = clock.parse_iso(d["agreed_publish_at"])
        window_end = clock.parse_iso(report["resolved_at"]) + timedelta(
            days=program["disclosure_window_days"]
        )
        if now < agreed or now < window_end:
            raise_err(ERR_DISCLOSURE_TOO_EARLY, "Disclosure window has not elapsed")
        for w in program.get("blackout_windows", []):
            s = clock.parse_iso(w["starts_at"])
            e = clock.parse_iso(w["ends_at"])
            if s <= now <= e:
                raise_err(ERR_BLACKOUT_ACTIVE, "Publication forbidden during blackout")
        d["status"] = "PUBLISHED"
    touch(d)
    return success_object(disclosure_out(d))
