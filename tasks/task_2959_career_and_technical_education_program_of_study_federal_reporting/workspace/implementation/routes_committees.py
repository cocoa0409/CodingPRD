"""Advisory committee, membership and meeting-minutes routes (PRD sec 3.3)."""
from flask import Blueprint

import calc
import resolve
import serialize
import services
import shape
from auth import endpoint, member_status, require_chair_binding
from envelope import created, listing, ok, page
from errors import ApiError
from store import (AGENDA_KINDS, MEMBER_STATUSES, MINUTES_STATUSES, SECTORS,
                   clock_date, db, fmt_date, fmt_instant, parse_date, parse_instant,
                   stamp_new, touch)

bp = Blueprint("committees", __name__)
DIRECTOR = ("CteDirector",)
CHAIR = ("CommitteeChair",)
READERS = ("CteDirector", "StateComplianceReviewer", "GrantFiscalOfficer",
           "CommitteeChair")
SEAT_PATTERN = r"[A-Z]{3}-\d{1,2}"


# ------------------------------------------------------------------ reads
@bp.get("/cte/advisory-committees/<committee_id>")
@endpoint(READERS)
def get_committee(committee_id):
    return ok(serialize.committee(resolve.committee(committee_id)))


@bp.get("/cte/advisory-committees/<committee_id>/members")
@endpoint(READERS)
def list_members(committee_id):
    limit, offset = shape.pagination()
    sector = shape.filter_enum("sector", SECTORS)
    status = shape.filter_enum("status", MEMBER_STATUSES)
    resolve.committee(committee_id)
    rows = [m for m in db.members.values() if m["committee_id"] == committee_id]
    if sector is not None:
        rows = [r for r in rows if r["sector"] == sector]
    if status is not None:
        rows = [r for r in rows if member_status(r) == status]
    rows.sort(key=lambda r: r["_seq"])
    window, total = page(rows, limit, offset)
    return listing([serialize.member(r) for r in window], limit, offset, total)


@bp.get("/cte/committee-members/<member_id>")
@endpoint(READERS)
def get_member(member_id):
    return ok(serialize.member(resolve.member(member_id)))


@bp.get("/cte/advisory-committees/<committee_id>/meetings")
@endpoint(READERS)
def list_meetings(committee_id):
    limit, offset = shape.pagination()
    agenda_kind = shape.filter_enum("agenda_kind", AGENDA_KINDS)
    minutes_status = shape.filter_enum("minutes_status", MINUTES_STATUSES)
    resolve.committee(committee_id)
    rows = [m for m in db.meetings.values() if m["committee_id"] == committee_id]
    if agenda_kind is not None:
        rows = [r for r in rows if r["agenda_kind"] == agenda_kind]
    if minutes_status is not None:
        rows = [r for r in rows if r["minutes_status"] == minutes_status]
    rows.sort(key=lambda r: (r["scheduled_for"], r["_seq"]), reverse=True)
    window, total = page(rows, limit, offset)
    return listing([serialize.meeting(r) for r in window], limit, offset, total)


@bp.get("/cte/committee-meetings/<meeting_id>")
@endpoint(READERS)
def get_meeting(meeting_id):
    return ok(serialize.meeting(resolve.meeting(meeting_id)))


# ------------------------------------------------------------------ chartering
@bp.post("/cte/programs-of-study/<pos_id>/advisory-committees")
@endpoint(DIRECTOR)
def charter_committee(pos_id):
    data = shape.body()
    name = shape.req_string(data, "name")
    quorum_min = shape.req_int(data, "quorum_min_members", minimum=3, maximum=15)
    employer_min = shape.req_int(data, "employer_seat_min", minimum=1, maximum=8)
    if employer_min > quorum_min:
        shape.bad("Field 'employer_seat_min' may not exceed 'quorum_min_members'.")
    expected = shape.req_int(data, "expected_program_of_study_version")
    program = resolve.program(pos_id)
    services.refresh_clna(program)
    if int(program["version"]) != int(expected):
        raise ApiError("ERR_STALE_PROGRAM_VERSION",
                       "The program of study is at version %s, not %s."
                       % (program["version"], expected))
    for existing in services.program_committees(pos_id):
        if existing["status"] != "DISSOLVED":
            existing["status"] = "DISSOLVED"
            touch(existing)
    committee = stamp_new({
        "pos_id": pos_id,
        "name": name,
        "quorum_min_members": quorum_min,
        "employer_seat_min": employer_min,
        "status": "FORMING",
        "active_member_count": 0,
        "employer_member_count": 0,
        "chair_member_id": None,
    })
    db.committees[committee["id"]] = committee
    touch(program)
    return created(serialize.committee(committee))


@bp.post("/cte/advisory-committees/<committee_id>/members")
@endpoint(DIRECTOR)
def seat_member(committee_id):
    data = shape.body()
    full_name = shape.req_string(data, "full_name")
    sector = shape.req_enum(data, "sector", SECTORS)
    seat_code = shape.req_string(data, "seat_code", min_len=5, max_len=6,
                                 pattern=SEAT_PATTERN)
    term_start = shape.req_date(data, "term_start_on")
    term_end = shape.req_date(data, "term_end_on")
    if term_end <= term_start:
        shape.bad("Field 'term_end_on' must be strictly after 'term_start_on'.")
    is_chair = shape.opt_bool(data, "is_chair", default=False)
    committee = resolve.committee(committee_id)

    for existing in db.members.values():
        if existing["committee_id"] != committee_id:
            continue
        if member_status(existing) != "ACTIVE":
            continue
        if existing["seat_code"] != seat_code:
            continue
        other_start = parse_date(existing["term_start_on"])
        other_end = parse_date(existing["term_end_on"])
        if other_start is None or other_end is None:
            continue
        if term_start < other_end and other_start < term_end:
            raise ApiError("ERR_SEAT_TERM_OVERLAP",
                           "Seat '%s' is already held over an overlapping term."
                           % seat_code)
    if is_chair:
        for existing in db.members.values():
            if existing["committee_id"] != committee_id:
                continue
            if existing["is_chair"] and member_status(existing) == "ACTIVE":
                raise ApiError("ERR_CHAIR_ALREADY_SEATED",
                               "This committee already has an ACTIVE chair.")

    member = stamp_new({
        "committee_id": committee_id,
        "full_name": full_name,
        "sector": sector,
        "seat_code": seat_code,
        "term_start_on": fmt_date(term_start),
        "term_end_on": fmt_date(term_end),
        "is_chair": is_chair,
    })
    db.members[member["id"]] = member
    services.maybe_activate_committee(committee)
    touch(committee)
    return created(serialize.member(member))


# ------------------------------------------------------------------ meetings
@bp.post("/cte/advisory-committees/<committee_id>/meetings")
@endpoint(CHAIR)
def schedule_meeting(committee_id):
    data = shape.body()
    agenda_kind = shape.req_enum(data, "agenda_kind", AGENDA_KINDS)
    scheduled_for = shape.req_instant(data, "scheduled_for")
    committee = resolve.committee(committee_id)
    require_chair_binding(committee_id)
    meeting = stamp_new({
        "committee_id": committee_id,
        "agenda_kind": agenda_kind,
        "scheduled_for": fmt_instant(scheduled_for),
        "held_at": None,
        "attendee_member_ids": [],
        "vote_yes": 0,
        "vote_no": 0,
        "minutes_url": None,
        "amendment_reason": None,
        "minutes_status": "SCHEDULED",
        "eligible_attendee_count": 0,
        "employer_attendee_count": 0,
        "quorum_met": False,
        "endorsement_passed": False,
    })
    db.meetings[meeting["id"]] = meeting
    touch(committee)
    return created(serialize.meeting(meeting))


@bp.post("/cte/committee-meetings/<meeting_id>/minutes")
@endpoint(CHAIR)
def file_minutes(meeting_id):
    data = shape.body()
    held_at = shape.req_instant(data, "held_at")
    attendees = shape.req_str_list(data, "attendee_member_ids")
    vote_yes = shape.req_int(data, "vote_yes", minimum=0)
    vote_no = shape.req_int(data, "vote_no", minimum=0)
    minutes_url = shape.req_string(data, "minutes_url")
    amendment_reason = shape.opt_string(data, "amendment_reason")

    meeting = resolve.meeting(meeting_id)
    scheduled_for = parse_instant(meeting["scheduled_for"])
    if scheduled_for is not None and held_at < scheduled_for:
        shape.bad("Field 'held_at' may not precede the meeting's 'scheduled_for'.")

    require_chair_binding(meeting["committee_id"])
    committee = db.committees.get(meeting["committee_id"])

    if amendment_reason is None:
        if meeting["minutes_status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_MEETING_STATE",
                           "minutes_status %s does not declare a transition to "
                           "FINALIZED." % meeting["minutes_status"])
        target = "FINALIZED"
    else:
        if meeting["minutes_status"] != "FINALIZED":
            raise ApiError("ERR_INVALID_MEETING_STATE",
                           "minutes_status %s does not declare a transition to "
                           "AMENDED." % meeting["minutes_status"])
        target = "AMENDED"

    held_on = held_at.date()
    eligible, employers = calc.eligible_attendance(meeting["committee_id"],
                                                   attendees, held_on)
    quorum_min = int(committee["quorum_min_members"])
    employer_min = int(committee["employer_seat_min"])
    if eligible < quorum_min:
        raise ApiError("ERR_QUORUM_NOT_MET",
                       "Eligible attendance %d is below quorum_min_members %d."
                       % (eligible, quorum_min))
    if employers < employer_min or 2 * employers < eligible:
        raise ApiError("ERR_EMPLOYER_SEAT_SHORTFALL",
                       "Employer representation is insufficient for quorum.")
    if vote_yes + vote_no > eligible:
        raise ApiError("ERR_VOTE_COUNT_EXCEEDS_ATTENDANCE",
                       "The vote tally exceeds the eligible attendance.")

    quorum_met = True
    endorsement_passed = (quorum_met and vote_yes > vote_no
                          and vote_yes + vote_no <= eligible)

    meeting["held_at"] = fmt_instant(held_at)
    meeting["attendee_member_ids"] = list(attendees)
    meeting["vote_yes"] = vote_yes
    meeting["vote_no"] = vote_no
    meeting["minutes_url"] = minutes_url
    meeting["eligible_attendee_count"] = eligible
    meeting["employer_attendee_count"] = employers
    meeting["quorum_met"] = quorum_met
    meeting["endorsement_passed"] = endorsement_passed
    meeting["minutes_status"] = target
    if amendment_reason is not None:
        meeting["amendment_reason"] = amendment_reason
    touch(meeting)

    if meeting["agenda_kind"] == "POS_ENDORSEMENT" and endorsement_passed:
        program = db.programs.get(committee["pos_id"])
        active = services.active_committee(committee["pos_id"])
        if (program is not None and active is not None
                and active["id"] == committee["id"]
                and program["approval_status"] == "SUBMITTED"):
            program["approval_status"] = "COMMITTEE_REVIEW"
            touch(program)
    return ok(serialize.meeting(meeting))
