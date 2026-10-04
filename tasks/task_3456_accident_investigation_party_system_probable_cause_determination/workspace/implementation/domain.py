"""Shared domain helpers: entity resolution, lazy state evaluation, recomputes.

Lazy evaluation (PRD 2.4): readout sessions become COMPLETE once the logical
clock reaches window_end_utc; a recorder becomes READOUT_COMPLETE once at
least one session exists and every session has ended; a board meeting becomes
IN_SESSION once the clock reaches window_start_utc. These flips are read-time
evaluations and never bump version/updated_at.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from constants import ROOM_TURNAROUND_BUFFER_MINUTES
from errors import api_error


# ---------------------------------------------------------------------------
# Existence resolution (404 family, section 2.6)
# ---------------------------------------------------------------------------

def get_case(case_id):
    entity = db.store["accident_cases"].get(case_id)
    if entity is None:
        raise api_error(
            "ERR_ACCIDENT_CASE_NOT_FOUND",
            "accident case %s does not exist" % case_id,
        )
    return entity


def get_investigation(investigation_id):
    entity = db.store["investigations"].get(investigation_id)
    if entity is None:
        raise api_error(
            "ERR_INVESTIGATION_NOT_FOUND",
            "investigation %s does not exist" % investigation_id,
        )
    return entity


def get_organization(organization_id):
    entity = db.store["party_organizations"].get(organization_id)
    if entity is None:
        raise api_error(
            "ERR_PARTY_ORGANIZATION_NOT_FOUND",
            "party organization %s does not exist" % organization_id,
        )
    return entity


def get_designation(designation_id):
    entity = db.store["party_designations"].get(designation_id)
    if entity is None:
        raise api_error(
            "ERR_PARTY_DESIGNATION_NOT_FOUND",
            "party designation %s does not exist" % designation_id,
        )
    return entity


def get_group(group_id):
    entity = db.store["groups"].get(group_id)
    if entity is None:
        raise api_error(
            "ERR_GROUP_NOT_FOUND", "investigative group %s does not exist" % group_id
        )
    return entity


def get_recorder(recorder_id):
    entity = db.store["recorders"].get(recorder_id)
    if entity is None:
        raise api_error(
            "ERR_RECORDER_NOT_FOUND",
            "recorder package %s does not exist" % recorder_id,
        )
    return entity


def get_recommendation(recommendation_id):
    entity = db.store["safety_recommendations"].get(recommendation_id)
    if entity is None:
        raise api_error(
            "ERR_SAFETY_RECOMMENDATION_NOT_FOUND",
            "safety recommendation %s does not exist" % recommendation_id,
        )
    return entity


def get_meeting(meeting_id):
    entity = db.store["board_meetings"].get(meeting_id)
    if entity is None:
        raise api_error(
            "ERR_BOARD_MEETING_NOT_FOUND",
            "board meeting %s does not exist" % meeting_id,
        )
    return entity


def find_decision(case, decision_id):
    for decision in case["launch_decisions"]:
        if decision["decision_id"] == decision_id:
            return decision
    raise api_error(
        "ERR_LAUNCH_DECISION_NOT_FOUND",
        "launch decision %s does not exist within case %s"
        % (decision_id, case["id"]),
    )


def find_seat(designation, seat_id):
    for seat in designation["group_seats"]:
        if seat["seat_id"] == seat_id:
            return seat
    raise api_error(
        "ERR_SEAT_NOT_FOUND",
        "seat %s does not exist within designation %s"
        % (seat_id, designation["id"]),
    )


def find_report(group, report_id):
    for report in group["factual_reports"]:
        if report["report_id"] == report_id:
            return report
    raise api_error(
        "ERR_FACTUAL_REPORT_NOT_FOUND",
        "factual report %s does not exist within group %s"
        % (report_id, group["id"]),
    )


# ---------------------------------------------------------------------------
# Lazy state evaluation (section 2.4) — never bumps version/updated_at
# ---------------------------------------------------------------------------

def refresh_session(session):
    if session["status"] != "SCHEDULED":
        return
    now = clock.clock_dt()
    end = clock.parse_iso(session["window_end_utc"])
    if now is not None and end is not None and end <= now:
        session["status"] = "COMPLETE"


def refresh_recorder(recorder):
    for session in recorder["readout_sessions"]:
        refresh_session(session)
    sessions = recorder["readout_sessions"]
    if (
        recorder["status"] == "IN_READOUT"
        and sessions
        and all(s["status"] == "COMPLETE" for s in sessions)
    ):
        recorder["status"] = "READOUT_COMPLETE"


def refresh_meeting(meeting):
    if meeting["status"] != "SCHEDULED":
        return
    now = clock.clock_dt()
    start = clock.parse_iso(meeting["window_start_utc"])
    if now is not None and start is not None and start <= now:
        meeting["status"] = "IN_SESSION"


# ---------------------------------------------------------------------------
# Recomputations (calculations table)
# ---------------------------------------------------------------------------

def recompute_seated_count(group):
    """SEATED seats referencing this group across all designations of the
    group's investigation (calculations.seated_count)."""
    count = 0
    for designation in db.store["party_designations"].values():
        if designation["investigation_id"] != group["investigation_id"]:
            continue
        for seat in designation["group_seats"]:
            if seat["group_id"] == group["id"] and seat["status"] == "SEATED":
                count += 1
    if count != group["seated_count"]:
        group["seated_count"] = count
        db.touch(group)
    return count


def recompute_docket_pct(investigation):
    """Two-pass docket completeness (calculations.docket_completeness_pct).

    Pass 1 reads each group's STORED status; satisfied(g) is COMPLETE with at
    least one VERIFIED or DOCKETED report. Pass 2 divides by the count of
    ACTIVE+COMPLETE groups (DISBANDED excluded), half-up to a whole percent.
    """
    groups = [
        g for g in db.store["groups"].values()
        if g["investigation_id"] == investigation["id"]
    ]
    total = sum(1 for g in groups if g["status"] in ("ACTIVE", "COMPLETE"))
    satisfied = 0
    for g in groups:
        if g["status"] != "COMPLETE":
            continue
        if any(r["status"] in ("VERIFIED", "DOCKETED") for r in g["factual_reports"]):
            satisfied += 1
    if total == 0:
        pct = 0
    else:
        pct = int(
            (Decimal(100 * satisfied) / Decimal(total)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    if pct != investigation["docket_completeness_pct"]:
        investigation["docket_completeness_pct"] = pct
        db.touch(investigation)
    return pct


def recompute_vote_tallies(meeting):
    meeting["adopt_count"] = sum(
        1 for v in meeting["member_votes"] if v["position"] == "ADOPT"
    )
    meeting["reject_count"] = sum(
        1 for v in meeting["member_votes"] if v["position"] == "REJECT"
    )
    meeting["abstain_count"] = sum(
        1 for v in meeting["member_votes"] if v["position"] == "ABSTAIN"
    )


def dissenting_members(meeting):
    """REJECT voters, cast_at ascending, ties broken by append order."""

    def _cast_key(vote):
        parsed = clock.parse_iso(vote.get("cast_at"))
        if parsed is None:
            return datetime.max.replace(tzinfo=timezone.utc)
        return parsed

    rejects = [v for v in meeting["member_votes"] if v["position"] == "REJECT"]
    rejects.sort(key=_cast_key)  # stable sort: ties keep append order
    return [v["member_user_id"] for v in rejects]


def windows_overlap(start_a, end_a, start_b, end_b):
    """Half-open [start, end) overlap: touching endpoints do not overlap."""
    return start_a < end_b and start_b < end_a


def meeting_buffer_window(meeting):
    """A meeting occupies [start, end + 60-minute turnaround buffer)."""
    start = clock.parse_iso(meeting["window_start_utc"])
    end = clock.parse_iso(meeting["window_end_utc"])
    if start is None or end is None:
        return None, None
    return start, end + timedelta(minutes=ROOM_TURNAROUND_BUFFER_MINUTES)
