"""Vote reports: submission, review decisions, resubmission, and the
tabulation board (PRD §3.4, §3.5). Guard order follows PRD §2.9 exactly."""
from flask import Blueprint, request

from auth import require_roles, body
from clock import now as clock_now
from envelope import ok_object, paginate
from errors import raise_err
from loaders import (
    get_contest, get_county, get_report, get_stringer, get_event,
    require_posture, versioned_record, touch, event_of_report,
)
from serializers import report_json, contest_json
from services_rules import qc_check, active_assignment_for, feed_covers
from services_rollup import refresh_contest, compute_rollup, linked_counties
from services_delivery import fanout_vote_update
from store import db
from util import is_int, nonblank

bp = Blueprint("reports", __name__)

REPORT_READ_ROLES = (
    "ElectionOpsAdmin", "StringerCoordinator", "TabulationClerk",
    "DecisionAnalyst", "DecisionDeskChief", "RecountOfficer",
)
TABULATION_ROLES = (
    "ElectionOpsAdmin", "TabulationClerk", "DecisionAnalyst",
    "DecisionDeskChief", "RecountOfficer", "StringerCoordinator",
)
REPORT_STATUSES = ("RECEIVED", "FLAGGED", "ACCEPTED", "REJECTED", "VOIDED")


def _contest_of_report(report):
    return db["contests"][report["contest_id"]]


def _validate_candidate_votes(raw):
    """Payload shape (priority 16): non-empty array of {candidate_id, votes}
    with votes a non-negative integer."""
    if not isinstance(raw, list) or not raw:
        raise_err("ERR_INVALID_REQUEST", "candidate_votes must be a non-empty array")
    for e in raw:
        if not isinstance(e, dict) or not nonblank(e.get("candidate_id")):
            raise_err("ERR_INVALID_REQUEST", "candidate_votes entries need a candidate_id")
        if not is_int(e.get("votes")) or e["votes"] < 0:
            raise_err("ERR_INVALID_REQUEST", "votes must be a non-negative integer")
    return [{"candidate_id": e["candidate_id"], "votes": e["votes"]} for e in raw]


def _check_membership(contest, county_id, entries):
    """Priority 11: the report's county must be linked to the contest, and
    every candidate_votes entry must belong to the contest."""
    county = db["counties"].get(county_id)
    linked = county is not None and any(
        l["contest_id"] == contest["id"] and l["county_id"] == county_id
        for l in db["links"].values()
    )
    if not linked:
        raise_err("ERR_COUNTY_NOT_IN_CONTEST", "county_id is not linked to the contest")
    member_ids = {
        c["id"] for c in db["candidates"].values() if c["contest_id"] == contest["id"]
    }
    for e in entries:
        if e["candidate_id"] not in member_ids:
            raise_err(
                "ERR_CANDIDATE_NOT_IN_CONTEST",
                "candidate_votes entry references a candidate of another contest",
            )
    return county


def _check_occ(contest, data):
    """Priority 7 (PRD §2.7): expected_contest_version is a non-optional OCC
    field on this endpoint."""
    ev = data.get("expected_contest_version")
    if ev is None or not is_int(ev):
        raise_err("ERR_INVALID_REQUEST", "expected_contest_version is required")
    if ev != contest["version"]:
        raise_err(
            "ERR_STALE_VERSION",
            "expected_contest_version does not match the contest version",
        )


@bp.post("/contests/<rid>/vote-reports")
def create_vote_report(rid):
    uid, role = require_roles("Stringer", "FeedOperator")
    data = body()
    source = data.get("source")
    # Role/channel scoping (RBAC matrix): a Stringer files STRINGER reports,
    # a FeedOperator files FEED reports.
    if source in ("STRINGER", "FEED"):
        if role == "Stringer" and source != "STRINGER":
            raise_err("ERR_UNAUTHORIZED_ROLE", "Stringer role files STRINGER reports")
        if role == "FeedOperator" and source != "FEED":
            raise_err("ERR_UNAUTHORIZED_ROLE", "FeedOperator role files FEED reports")
    contest = get_contest(rid)
    event = get_event(contest["event_id"])
    require_posture(event, "LIVE", "TABULATION")  # priority 5
    _check_occ(contest, data)                     # priority 7

    raw_cv = data.get("candidate_votes")
    entries = [e for e in raw_cv if isinstance(e, dict)] if isinstance(raw_cv, list) else []
    county = _check_membership(contest, data.get("county_id"), entries)  # priority 11

    # Priority 12: collection authority, per channel.
    if source == "STRINGER":
        if active_assignment_for(uid, county["id"], event["id"]) is None:
            raise_err(
                "ERR_STRINGER_NOT_DEPLOYED",
                "No ACTIVE assignment covers this stringer, county and event",
            )
    elif source == "FEED":
        if feed_covers(event["id"], county["state_code"]) is None:
            raise_err(
                "ERR_FEED_COVERAGE_MISSING",
                "No feed source of the event covers the county's state",
            )
    else:
        raise_err("ERR_INVALID_REQUEST", "source must be STRINGER or FEED")

    # Priority 16: payload shape.
    if "precincts_reporting" not in data or not is_int(data.get("precincts_reporting")) \
            or data["precincts_reporting"] < 1:
        raise_err("ERR_INVALID_REQUEST", "precincts_reporting must be an integer >= 1")
    entries = _validate_candidate_votes(raw_cv)

    # Priority 18: precinct bound.
    if data["precincts_reporting"] > county["expected_precincts"]:
        raise_err(
            "ERR_PRECINCTS_EXCEED_EXPECTED",
            "precincts_reporting exceeds the county's expected_precincts",
        )

    reported_total, deviation, swing, flagged = qc_check(contest, county, entries)
    rec = versioned_record()
    rec.update({
        "contest_id": contest["id"],
        "county_id": county["id"],
        "source": source,
        "submitted_by_stringer_id": uid if source == "STRINGER" else None,
        "precincts_reporting": data["precincts_reporting"],
        "candidate_votes": entries,
        "reported_total": reported_total,
        "deviation_ratio": deviation,
        "swing_deviation": swing,
        "status": "FLAGGED" if flagged else "RECEIVED",
        "accepted_at": None,
    })
    db["reports"][rec["id"]] = rec

    # Side effects: contest version +1; first report moves AWAITING -> REPORTING.
    if contest["tabulation_status"] == "AWAITING":
        contest["tabulation_status"] = "REPORTING"
    touch(contest)
    return ok_object(report_json(rec), 201)


@bp.get("/contests/<rid>/vote-reports")
def list_reports_of_contest(rid):
    require_roles(*REPORT_READ_ROLES)
    contest = get_contest(rid)
    rows = [r for r in db["reports"].values() if r["contest_id"] == contest["id"]]
    status = request.args.get("status")
    if status is not None:
        if status not in REPORT_STATUSES:
            raise_err("ERR_INVALID_REQUEST", "status filter out of range")
        rows = [r for r in rows if r["status"] == status]
    county_id = request.args.get("county_id")
    if county_id is not None:
        rows = [r for r in rows if r["county_id"] == county_id]
    return paginate(rows, report_json)


@bp.get("/counties/<rid>/vote-reports")
def list_reports_of_county(rid):
    require_roles(*REPORT_READ_ROLES)
    county = get_county(rid)
    rows = [r for r in db["reports"].values() if r["county_id"] == county["id"]]
    status = request.args.get("status")
    if status is not None:
        if status not in REPORT_STATUSES:
            raise_err("ERR_INVALID_REQUEST", "status filter out of range")
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, report_json)


@bp.get("/stringers/<rid>/vote-reports")
def list_reports_of_stringer(rid):
    require_roles("StringerCoordinator", "ElectionOpsAdmin", "TabulationClerk")
    stringer = get_stringer(rid)
    rows = [
        r for r in db["reports"].values()
        if r["submitted_by_stringer_id"] == stringer["id"]
    ]
    return paginate(rows, report_json)


def _credit_stringer(report, kind):
    """ACCEPT/VOID reliability side effect on the authoring stringer."""
    sid = report["submitted_by_stringer_id"]
    if report["source"] != "STRINGER" or sid is None:
        return
    stringer = db["stringers"].get(sid)
    if stringer is None:
        return
    event_id = _contest_of_report(report)["event_id"]
    if kind == "accepted":
        stringer["accepted_report_count"] += 1
    else:
        stringer["voided_report_count"] += 1
    stringer["reliability_events"].append({"event_id": event_id, "kind": kind})
    touch(stringer)


@bp.post("/vote-reports/<rid>/review-decisions")
def review_decision(rid):
    require_roles("TabulationClerk")
    report = get_report(rid)
    data = body()
    decision = data.get("decision")
    if decision not in ("ACCEPT", "REJECT", "VOID"):
        raise_err("ERR_INVALID_REQUEST", "decision must be ACCEPT, REJECT or VOID")
    contest = _contest_of_report(report)
    event = get_event(contest["event_id"])

    if decision == "ACCEPT":
        # ACCEPT is the one review action admitted beyond tabulation
        # (PRD §2.5): LIVE, TABULATION and CERTIFICATION.
        require_posture(event, "LIVE", "TABULATION", "CERTIFICATION")
        if report["status"] not in ("RECEIVED", "FLAGGED"):
            raise_err("ERR_INVALID_STATE", "ACCEPT requires status RECEIVED or FLAGGED")
        report["status"] = "ACCEPTED"
        report["accepted_at"] = clock_now()
        touch(report)
        refresh_contest(contest, bump=True)
        fanout_vote_update(contest, db["counties"][report["county_id"]])
        _credit_stringer(report, "accepted")
    elif decision == "REJECT":
        if report["status"] not in ("RECEIVED", "FLAGGED"):
            raise_err("ERR_INVALID_STATE", "REJECT requires status RECEIVED or FLAGGED")
        report["status"] = "REJECTED"
        touch(report)
    else:  # VOID — the exact compensation of ACCEPT (PRD §3.4).
        if report["status"] != "ACCEPTED":
            raise_err("ERR_INVALID_STATE", "VOID requires status ACCEPTED")
        report["status"] = "VOIDED"
        report["accepted_at"] = None
        touch(report)
        refresh_contest(contest, bump=True)
        _credit_stringer(report, "voided")
    return ok_object(report_json(report))


@bp.post("/vote-reports/<rid>/resubmit")
def resubmit_report(rid):
    uid, role = require_roles("Stringer", "FeedOperator")
    report = get_report(rid)
    # Priority 3 + channel scoping: only the original author may resubmit a
    # STRINGER report; any FeedOperator may resubmit a FEED report.
    if role == "Stringer":
        if report["source"] != "STRINGER" or uid != report["submitted_by_stringer_id"]:
            raise_err(
                "ERR_UNAUTHORIZED_ROLE",
                "Only the original author may resubmit a STRINGER report",
            )
    else:
        if report["source"] != "FEED":
            raise_err(
                "ERR_UNAUTHORIZED_ROLE",
                "FeedOperator may only resubmit FEED reports",
            )
    contest = _contest_of_report(report)
    event = get_event(contest["event_id"])
    require_posture(event, "LIVE", "TABULATION")
    if report["status"] != "REJECTED":
        raise_err("ERR_INVALID_STATE", "Resubmit requires status REJECTED")
    data = body()

    raw_cv = data.get("candidate_votes")
    entries = [e for e in raw_cv if isinstance(e, dict)] if isinstance(raw_cv, list) else []
    member_ids = {
        c["id"] for c in db["candidates"].values() if c["contest_id"] == contest["id"]
    }
    for e in entries:
        cid = e.get("candidate_id")
        if cid is not None and cid not in member_ids:
            raise_err(
                "ERR_CANDIDATE_NOT_IN_CONTEST",
                "candidate_votes entry references a candidate of another contest",
            )

    if "precincts_reporting" not in data or not is_int(data.get("precincts_reporting")) \
            or data["precincts_reporting"] < 1:
        raise_err("ERR_INVALID_REQUEST", "precincts_reporting must be an integer >= 1")
    entries = _validate_candidate_votes(raw_cv)
    county = db["counties"][report["county_id"]]
    if data["precincts_reporting"] > county["expected_precincts"]:
        raise_err(
            "ERR_PRECINCTS_EXCEED_EXPECTED",
            "precincts_reporting exceeds the county's expected_precincts",
        )

    reported_total, deviation, swing, flagged = qc_check(contest, county, entries)
    report["precincts_reporting"] = data["precincts_reporting"]
    report["candidate_votes"] = entries
    report["reported_total"] = reported_total
    report["deviation_ratio"] = deviation
    report["swing_deviation"] = swing
    report["status"] = "FLAGGED" if flagged else "RECEIVED"
    touch(report)
    return ok_object(report_json(report))


@bp.get("/contests/<rid>/tabulation")
def tabulation_board(rid):
    require_roles(*TABULATION_ROLES)
    contest = get_contest(rid)
    r = compute_rollup(contest)
    refresh_contest(contest, bump=False)
    candidate_totals = [
        {
            "candidate_id": c["id"],
            "candidate_name": c["candidate_name"],
            "party": c["party"],
            "votes": votes,
            "rank": i + 1,
        }
        for i, (c, votes) in enumerate(r["candidate_totals"])
    ]
    expected_precincts_total = sum(
        c["expected_precincts"] for c in linked_counties(contest["id"])
    )
    return ok_object({
        "contest_id": contest["id"],
        "tabulation_status": contest["tabulation_status"],
        "call_status": contest["call_status"],
        "reported_precincts": r["reported_precincts"],
        "expected_precincts_total": expected_precincts_total,
        "candidate_totals": candidate_totals,
        "total_votes": r["total_votes"],
        "margin_pct": r["margin_pct"],
        "outstanding_estimate": r["outstanding_estimate"],
        "outstanding_detail": r["outstanding_detail"],
    })
