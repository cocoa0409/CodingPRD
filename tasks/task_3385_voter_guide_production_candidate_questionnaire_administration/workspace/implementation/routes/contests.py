"""Contest routes incl. the OCC-gated lifecycle (PRD 3.2, 2.6)."""
from flask import Blueprint

import helpers
import serialize
import shape
from authz import (CHAPTER_COORDINATOR, FORUM_MODERATOR, LEAGUE_ADMIN,
                   QUESTIONNAIRE_EDITOR, check_active_current, require_roles)
from errors import (cycle_not_open, filing_still_open, invalid_request,
                    invalid_state, neutrality_review_outstanding,
                    questionnaire_not_pinned, stale_version)
from helpers import base_entity, touch
from respond import listing, success
from store import store

bp = Blueprint("contests", __name__)

CONTEST_KINDS = ("CANDIDATE_RACE", "BALLOT_MEASURE")
WORD_COUNT_POLICIES = ("STRICT", "LENIENT")

# User-driven transitions only; GUIDE_READY/LOCKED -> QUESTIONNAIRE_PHASE is
# reserved for the incident cascade and LOCKED is otherwise terminal.
CONTEST_TRANSITIONS = {
    ("FILING_OPEN", "QUESTIONNAIRE_PHASE"),
    ("QUESTIONNAIRE_PHASE", "GUIDE_READY"),
    ("GUIDE_READY", "LOCKED"),
}


@bp.post("/jurisdictions/<jid>/contests")
def create_contest(jid):
    uid, role, volunteer = require_roles(CHAPTER_COORDINATOR)
    b = shape.body()
    shape.no_extra(b, {"kind", "office_name", "seat_count", "vote_for_count",
                       "filing_deadline", "questionnaire_word_limit",
                       "word_count_policy"})
    kind = shape.s_enum(b, "kind", CONTEST_KINDS)
    office_name = b.get("office_name")
    if kind == "CANDIDATE_RACE":
        if office_name is None:
            raise invalid_request("Field 'office_name' is required")
        if not isinstance(office_name, str):
            raise invalid_request("Field 'office_name' must be a string")
    else:
        if office_name is not None:
            raise invalid_request(
                "Field 'office_name' must be omitted for a BALLOT_MEASURE contest")
        office_name = None
    seat_count = shape.s_int(b, "seat_count", required=False, minimum=1)
    vote_for_count = shape.s_int(b, "vote_for_count", required=False, minimum=1)
    filing_deadline = shape.s_instant(b, "filing_deadline")
    word_limit = shape.s_int(b, "questionnaire_word_limit", required=False,
                             minimum=1)
    policy = shape.s_enum(b, "word_count_policy", WORD_COUNT_POLICIES,
                          required=False)
    jurisdiction = helpers.get_jurisdiction(jid)
    cycle = store.cycles[jurisdiction["cycle_id"]]
    if cycle["status"] != "OPEN":
        raise cycle_not_open()
    check_active_current(volunteer)
    contest = base_entity()
    contest.update({
        "jurisdiction_id": jurisdiction["id"],
        "kind": kind,
        "office_name": office_name,
        "seat_count": 1 if seat_count is None else seat_count,
        "vote_for_count": 1 if vote_for_count is None else vote_for_count,
        "filing_deadline": filing_deadline,
        "questionnaire_word_limit": 100 if word_limit is None else word_limit,
        "word_count_policy": "STRICT" if policy is None else policy,
        "status": "FILING_OPEN",
    })
    store.contests[contest["id"]] = contest
    return success(serialize.contest_json(contest), status=201)


@bp.get("/jurisdictions/<jid>/contests")
def list_contests(jid):
    require_roles(LEAGUE_ADMIN, CHAPTER_COORDINATOR, QUESTIONNAIRE_EDITOR,
                  FORUM_MODERATOR)
    jurisdiction = helpers.get_jurisdiction(jid)
    limit, offset = shape.pagination_params()
    rows, total = helpers.page_of(
        helpers.contests_of_jurisdiction(jurisdiction["id"]), limit, offset)
    return listing([serialize.contest_json(c) for c in rows],
                   limit, offset, total)


@bp.get("/contests/<cid>")
def read_contest(cid):
    require_roles(LEAGUE_ADMIN, CHAPTER_COORDINATOR, QUESTIONNAIRE_EDITOR)
    return success(serialize.contest_json(helpers.get_contest(cid)))


@bp.post("/contests/<cid>/transitions")
def transition_contest(cid):
    uid, role, volunteer = require_roles(CHAPTER_COORDINATOR)
    b = shape.body()
    shape.no_extra(b, {"to", "expected_contest_version"})
    to = shape.s_str(b, "to")
    expected = shape.s_int(b, "expected_contest_version")
    contest = helpers.get_contest(cid)
    cycle = helpers.cycle_of_contest(contest)
    if to == "QUESTIONNAIRE_PHASE" and cycle["status"] != "OPEN":
        raise cycle_not_open()
    if (contest["status"], to) not in CONTEST_TRANSITIONS:
        raise invalid_state("Cannot move a %s contest to %s"
                            % (contest["status"], to))
    if expected != contest["version"]:
        raise stale_version()
    check_active_current(volunteer)
    if to == "QUESTIONNAIRE_PHASE":
        if not store.clock > contest["filing_deadline"]:
            raise filing_still_open(
                "The filing window is still open at the filing_deadline")
    elif to == "GUIDE_READY":
        if contest["kind"] == "CANDIDATE_RACE":
            q = helpers.questionnaire_of_contest(contest["id"])
            if q is None or q["status"] != "PINNED":
                raise questionnaire_not_pinned()
        else:
            m = helpers.measure_of_contest(contest["id"])
            if m is None or m["status"] != "APPROVED_FOR_GUIDE":
                raise neutrality_review_outstanding(
                    "The contest's measure is not APPROVED_FOR_GUIDE")
    contest["status"] = to
    touch(contest)
    return success(serialize.contest_json(contest))
