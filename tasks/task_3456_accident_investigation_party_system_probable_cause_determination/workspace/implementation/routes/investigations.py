"""Investigations: reads, phase advancement, reopen, docket release (PRD 3.5).

GET  /investigations                              all roles
GET  /investigations/{id}                         all roles
POST /investigations/{id}/advance-phase           IIC
POST /investigations/{id}/reopen-factual          IIC
POST /investigations/{id}/release-docket          DocketOfficer
"""

from flask import Blueprint, request

import clock
import db
import domain
from auth import get_context, require_iic, require_roles
from constants import INVESTIGATION_PHASES, ROLES
from envelope import ok_list, ok_object, paginate, parse_pagination
from errors import api_error
from serializers import investigation_public
from validate import get_body, req_enum

bp = Blueprint("investigations", __name__)


@bp.route("/investigations", methods=["GET"])
def list_investigations():
    _user_id, role = get_context()
    require_roles(role, ROLES)
    limit, offset = parse_pagination(request.args)
    items = db.all_of("investigations")
    accident_case_id = request.args.get("accident_case_id")
    if accident_case_id is not None:
        items = [i for i in items if i["accident_case_id"] == accident_case_id]
    phase = request.args.get("phase")
    if phase is not None:
        items = [i for i in items if i["phase"] == phase]
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list(
        [investigation_public(i) for i in page], limit, offset, total
    )


@bp.route("/investigations/<investigation_id>", methods=["GET"])
def get_investigation(investigation_id):
    _user_id, role = get_context()
    require_roles(role, ROLES)
    investigation = domain.get_investigation(investigation_id)
    return ok_object(investigation_public(investigation), status=200)


def _groups_of(investigation):
    return [
        g
        for g in db.all_of("groups")
        if g["investigation_id"] == investigation["id"]
    ]


@bp.route("/investigations/<investigation_id>/advance-phase", methods=["POST"])
def advance_phase(investigation_id):
    user_id, role = get_context()
    require_roles(role, ("IIC",))
    investigation = domain.get_investigation(investigation_id)
    require_iic(user_id, investigation)
    body = get_body()
    to_phase = req_enum(body, "to_phase", INVESTIGATION_PHASES)

    current = investigation["phase"]
    groups = _groups_of(investigation)

    if current == "GO_TEAM_ASSEMBLED" and to_phase == "ON_SCENE":
        if not any(g["status"] == "ACTIVE" for g in groups):
            raise api_error(
                "ERR_PHASE_GATE_UNSATISFIED",
                "at least one investigative group must be ACTIVE to move "
                "ON_SCENE",
            )
    elif current == "ON_SCENE" and to_phase == "FACTUAL":
        for group in groups:
            if group["status"] == "ACTIVE" and group["seated_count"] < 1:
                raise api_error(
                    "ERR_PHASE_GATE_UNSATISFIED",
                    "every ACTIVE group must hold at least one SEATED seat "
                    "before the FACTUAL phase",
                )
    elif current == "FACTUAL" and to_phase == "ANALYSIS":
        if investigation["docket_status"] != "OPEN":
            raise api_error(
                "ERR_DOCKET_NOT_OPEN",
                "the public docket must be OPEN before analysis begins",
            )
        for group in groups:
            if group["status"] not in ("COMPLETE", "DISBANDED"):
                raise api_error(
                    "ERR_PHASE_GATE_UNSATISFIED",
                    "every group must be COMPLETE or DISBANDED before analysis",
                )
    elif current == "ANALYSIS" and to_phase == "BOARD_REVIEW":
        meetings = [
            m
            for m in db.store["board_meetings"].values()
            if m["investigation_id"] == investigation["id"]
        ]
        for meeting in meetings:
            domain.refresh_meeting(meeting)
        if not any(m["status"] == "SCHEDULED" for m in meetings):
            raise api_error(
                "ERR_PHASE_GATE_UNSATISFIED",
                "at least one effectively SCHEDULED board meeting is required "
                "to move to BOARD_REVIEW",
            )
    else:
        raise api_error(
            "ERR_INVESTIGATION_PHASE_INVALID",
            "phase hop %s -> %s is not in the declared order"
            % (current, to_phase),
        )

    investigation["phase"] = to_phase
    db.touch(investigation)
    return ok_object(investigation_public(investigation), status=200)


@bp.route("/investigations/<investigation_id>/reopen-factual", methods=["POST"])
def reopen_factual(investigation_id):
    user_id, role = get_context()
    require_roles(role, ("IIC",))
    investigation = domain.get_investigation(investigation_id)
    require_iic(user_id, investigation)

    if investigation["phase"] != "ANALYSIS":
        raise api_error(
            "ERR_INVESTIGATION_PHASE_INVALID",
            "reopen-factual requires the investigation to be in ANALYSIS",
        )

    for group in _groups_of(investigation):
        if group["status"] == "COMPLETE":
            group["status"] = "ACTIVE"
            db.touch(group)
    investigation["phase"] = "FACTUAL"
    domain.recompute_docket_pct(investigation)
    db.touch(investigation)
    return ok_object(investigation_public(investigation), status=200)


@bp.route("/investigations/<investigation_id>/release-docket", methods=["POST"])
def release_docket(investigation_id):
    _user_id, role = get_context()
    require_roles(role, ("DocketOfficer",))
    investigation = domain.get_investigation(investigation_id)

    if investigation["phase"] != "FACTUAL":
        raise api_error(
            "ERR_INVESTIGATION_PHASE_INVALID",
            "the docket may only be released during the FACTUAL phase",
        )
    if investigation["docket_status"] != "SEALED":
        raise api_error(
            "ERR_DOCKET_STATE_INVALID",
            "the docket must still be SEALED to be released",
        )

    # Recorder-safety gate (pipeline stage 6): no session window may still be
    # open against the logical clock.
    recorders = [
        r
        for r in db.store["recorders"].values()
        if r["investigation_id"] == investigation["id"]
    ]
    now = clock.clock_dt()
    for recorder in recorders:
        domain.refresh_recorder(recorder)
        for session in recorder["readout_sessions"]:
            end = clock.parse_iso(session["window_end_utc"])
            if now is not None and end is not None and end > now:
                raise api_error(
                    "ERR_RECORDER_READOUT_INCOMPLETE",
                    "a readout session on recorder %s is still within its "
                    "window" % recorder["id"],
                )

    # Completeness gate (pipeline stage 7): every group COMPLETE with a
    # VERIFIED or DOCKETED report.
    groups = _groups_of(investigation)
    for group in groups:
        satisfied = group["status"] == "COMPLETE" and any(
            rep["status"] in ("VERIFIED", "DOCKETED")
            for rep in group["factual_reports"]
        )
        if not satisfied:
            raise api_error(
                "ERR_DOCKET_INCOMPLETE",
                "every group must be COMPLETE and hold a VERIFIED or "
                "DOCKETED factual report before docket release",
            )

    for group in groups:
        changed = False
        for report in group["factual_reports"]:
            if report["status"] == "VERIFIED":
                report["status"] = "DOCKETED"
                changed = True
        if changed:
            db.touch(group)
    for recorder in recorders:
        if recorder["status"] == "READOUT_COMPLETE":
            recorder["status"] = "RELEASED"
            db.touch(recorder)

    investigation["docket_status"] = "OPEN"
    domain.recompute_docket_pct(investigation)
    db.touch(investigation)
    return ok_object(investigation_public(investigation), status=200)
