"""Campus support: cohort meetings with the 15-minute mentor buffer rule, and
the internship career program (PRD 3.8)."""

from datetime import timedelta

from constants import INTERNSHIP_TRANSITIONS, MEETING_KINDS, MENTOR_BUFFER_MINUTES
from core import add, store, touch
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INTERNSHIP_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MENTOR_SCHEDULE_CONFLICT,
    ERR_NOT_FOUND,
    ERR_SCHOLAR_NOT_ELIGIBLE,
)
from flask import Blueprint, request
from response import ok
from serialize import pub
from validate import (
    apply_page,
    auth,
    body,
    lookup,
    page_args,
    req_date,
    req_dt,
    req_enum,
    req_str,
    require_role,
)

bp_campus = Blueprint("campus", __name__)


@bp_campus.post("/api/cohort-meetings")
def create_meeting():
    uid, role = auth()
    data = body()
    cohort_id = req_str(data, "cohort_id")
    kind = req_enum(data, "kind", MEETING_KINDS)
    starts = req_dt(data, "starts_at")
    ends = req_dt(data, "ends_at")
    scholar_id = data.get("scholar_id")
    if kind == "INDIVIDUAL":
        if scholar_id is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "scholar_id is required for INDIVIDUAL meetings",
            )
        if not isinstance(scholar_id, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, "scholar_id must be a string")
    elif scholar_id is not None:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "scholar_id must be absent for COHORT meetings"
        )
    if ends <= starts:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "ends_at must be strictly after starts_at"
        )
    require_role(role, ["FacultyMentor"])
    cohort = lookup(store.cohorts, cohort_id)
    # Tier 4 ownership: the caller must be the cohort's own mentor.
    if cohort["mentor_id"] != uid:
        raise ApiError(
            ERR_FORBIDDEN, 403, "A mentor logs meetings only for its own cohorts"
        )
    # Tier 6: a supplied scholar_id must exist and belong to this cohort.
    if kind == "INDIVIDUAL":
        scholar = store.scholars.get(scholar_id)
        if scholar is None or scholar["cohort_id"] != cohort_id:
            raise ApiError(
                ERR_NOT_FOUND, 404, "scholar_id does not name a scholar of this cohort"
            )
    # Tier 8: the cohort must be MATRICULATED.
    if cohort["status"] != "MATRICULATED":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Meetings require a MATRICULATED cohort"
        )
    # Tier 10(g): 15-minute buffer rule across the mentor's existing meetings.
    buf = timedelta(minutes=MENTOR_BUFFER_MINUTES)
    for m in store.meetings.values():
        mc = store.cohorts.get(m["cohort_id"])
        if mc is None or mc["mentor_id"] != uid:
            continue
        if starts < m["ends_at"] + buf and m["starts_at"] < ends + buf:
            raise ApiError(
                ERR_MENTOR_SCHEDULE_CONFLICT,
                422,
                "Meeting conflicts with an existing meeting of this mentor",
            )
    mtg = add(
        store.meetings,
        {
            "cohort_id": cohort_id,
            "kind": kind,
            "scholar_id": scholar_id if kind == "INDIVIDUAL" else None,
            "starts_at": starts,
            "ends_at": ends,
        },
    )
    touch(cohort)  # meetings_held_count rose by one
    return ok(pub(mtg), 201)


@bp_campus.get("/api/cohorts/<cid>/meetings")
def list_meetings(cid):
    auth()
    limit, offset = page_args()
    lookup(store.cohorts, cid)
    items = [m for m in store.meetings.values() if m["cohort_id"] == cid]
    kind = request.args.get("kind")
    if kind is not None:
        items = [m for m in items if m["kind"] == kind]
    items.sort(key=lambda e: e["_seq"])
    page, meta = apply_page(items, limit, offset)
    return ok([pub(m) for m in page], 200, meta)


@bp_campus.post("/api/internships")
def create_internship():
    _uid, role = auth()
    data = body()
    scholar_id = req_str(data, "scholar_id")
    employer = req_str(data, "employer_name")
    starts_on = req_date(data, "starts_on")
    ends_on = req_date(data, "ends_on")
    if ends_on < starts_on:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "ends_on must be on or after starts_on"
        )
    require_role(role, ["CareerDirector", "ProgramAdmin"])
    scholar = lookup(store.scholars, scholar_id)
    # Tier 8: eligibility gate at proposal time.
    if scholar["enrollment_status"] not in ("MATRICULATED", "RETAINED") or (
        scholar["standing"] != "GOOD_STANDING"
    ):
        raise ApiError(
            ERR_SCHOLAR_NOT_ELIGIBLE,
            409,
            "Scholar must be MATRICULATED or RETAINED and in GOOD_STANDING",
        )
    # Tier 10(h): inclusive-interval overlap vs PROPOSED/CONFIRMED internships
    # of the same scholar; sharing a boundary date is a conflict. TERMINATED
    # and COMPLETED internships no longer occupy the calendar.
    for i in store.internships.values():
        if i["scholar_id"] != scholar_id or i["status"] not in ("PROPOSED", "CONFIRMED"):
            continue
        if starts_on <= i["ends_on"] and i["starts_on"] <= ends_on:
            raise ApiError(
                ERR_INTERNSHIP_OVERLAP,
                422,
                "Internship overlaps an existing internship of this scholar",
            )
    it = add(
        store.internships,
        {
            "scholar_id": scholar_id,
            "employer_name": employer,
            "starts_on": starts_on,
            "ends_on": ends_on,
            "status": "PROPOSED",
        },
    )
    return ok(pub(it), 201)


@bp_campus.post("/api/internships/<iid>/transition")
def transition_internship(iid):
    _uid, role = auth()
    data = body()
    to_status = req_enum(data, "to_status", ["PROPOSED", "CONFIRMED", "COMPLETED", "TERMINATED"])
    require_role(role, ["CareerDirector", "ProgramAdmin"])
    it = lookup(store.internships, iid)
    cur = it["status"]
    if to_status not in INTERNSHIP_TRANSITIONS.get(cur, []):
        raise ApiError(
            ERR_INVALID_STATE,
            409,
            "Internship %s -> %s is not a declared transition" % (cur, to_status),
        )
    if to_status == "CONFIRMED":
        # Standing is re-checked at confirm time (PRD 3.8).
        scholar = store.scholars[it["scholar_id"]]
        if scholar["standing"] != "GOOD_STANDING":
            raise ApiError(
                ERR_SCHOLAR_NOT_ELIGIBLE,
                409,
                "Scholar is no longer in GOOD_STANDING",
            )
    it["status"] = to_status
    touch(it)
    return ok(pub(it), 200)
