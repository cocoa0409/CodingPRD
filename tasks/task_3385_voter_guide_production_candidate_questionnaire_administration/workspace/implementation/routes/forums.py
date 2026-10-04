"""Forum + ForumQuestion routes (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint

import authz
import calc
import helpers
import serialize
import shape
from authz import (CHAPTER_COORDINATOR, FORUM_MODERATOR, LEAGUE_ADMIN,
                   PUBLIC_USER, QUESTIONNAIRE_EDITOR, check_active_current,
                   require_roles)
from errors import (advocacy_separation, attestation_lapsed,
                    contest_kind_mismatch, cycle_not_open,
                    forum_not_concluded, forum_quorum_not_met,
                    forum_time_overlap, invalid_request, invalid_state,
                    moderator_buffer_violation, moderator_not_qualified,
                    question_cap_reached, sod_moderator_own_question,
                    unauthorized_role, volunteer_suspended)
from helpers import base_entity, touch
from respond import listing, success
from store import store

bp = Blueprint("forums", __name__)

QUESTION_SOURCES = ("PUBLIC_SUBMISSION", "MODERATOR_AUTHORED")
FORUM_TRANSITIONS = {
    ("PLANNED", "CONFIRMED"),
    ("CONFIRMED", "HELD"),
    ("PLANNED", "CANCELLED"),
    ("CONFIRMED", "CANCELLED"),
}
MODERATOR_BUFFER = timedelta(hours=24)
QUESTION_CAP = 5


@bp.post("/contests/<cid>/forums")
def create_forum(cid):
    uid, role, volunteer = require_roles(CHAPTER_COORDINATOR)
    b = shape.body()
    shape.no_extra(b, {"scheduled_start", "scheduled_end",
                       "moderator_volunteer_id"})
    scheduled_start = shape.s_instant(b, "scheduled_start")
    scheduled_end = shape.s_instant(b, "scheduled_end")
    moderator_id = shape.s_str(b, "moderator_volunteer_id")
    if not scheduled_start < scheduled_end:
        raise invalid_request(
            "scheduled_start must be strictly before scheduled_end")
    contest = helpers.get_contest(cid)
    cycle = helpers.cycle_of_contest(contest)
    if cycle["status"] != "OPEN":
        raise cycle_not_open()
    if contest["status"] not in ("QUESTIONNAIRE_PHASE", "GUIDE_READY"):
        raise invalid_state(
            "Forums are scheduled in QUESTIONNAIRE_PHASE or GUIDE_READY")
    check_active_current(volunteer)
    moderator = store.volunteers.get(moderator_id)
    if moderator is not None:
        if moderator["status"] == "SUSPENDED":
            raise volunteer_suspended("The referenced moderator is SUSPENDED")
        if not authz.attestation_current(moderator):
            raise attestation_lapsed("The referenced moderator is LAPSED")
        if moderator["advocacy_flag"]:
            raise advocacy_separation(
                "An advocacy-flagged volunteer may not moderate a forum")
    if moderator is None or "MODERATOR" not in moderator["roles"]:
        raise moderator_not_qualified()
    # Half-open interval [start, end) overlap within the jurisdiction;
    # adjacency (end == start) is allowed (PRD 3.7).
    jurisdiction = helpers.jurisdiction_of_contest(contest)
    for other_contest in helpers.contests_of_jurisdiction(jurisdiction["id"]):
        for other in helpers.forums_of_contest(other_contest["id"]):
            if other["status"] not in ("PLANNED", "CONFIRMED"):
                continue
            if (scheduled_start < other["scheduled_end"]
                    and other["scheduled_start"] < scheduled_end):
                raise forum_time_overlap()
    # One moderator's commitments are buffered by 24h measured end-to-start;
    # exactly 24h is allowed.
    for other in store.forums.values():
        if (other["moderator_volunteer_id"] != moderator_id
                or other["status"] not in ("PLANNED", "CONFIRMED")):
            continue
        if scheduled_start >= other["scheduled_end"]:
            gap = scheduled_start - other["scheduled_end"]
        elif other["scheduled_start"] >= scheduled_end:
            gap = other["scheduled_start"] - scheduled_end
        else:
            gap = timedelta(0)  # overlapping: less than 24h by definition
        if gap < MODERATOR_BUFFER:
            raise moderator_buffer_violation()
    if contest["kind"] != "CANDIDATE_RACE":
        raise contest_kind_mismatch(
            "Only a CANDIDATE_RACE contest carries forums")
    forum = base_entity()
    forum.update({
        "contest_id": contest["id"],
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "moderator_volunteer_id": moderator_id,
        "status": "PLANNED",
        "eligible_candidate_count": serialize.verified_candidate_count(contest),
        "minutes_text": None,
    })
    store.forums[forum["id"]] = forum
    return success(serialize.forum_json(forum), status=201)


@bp.get("/contests/<cid>/forums")
def list_forums(cid):
    require_roles(LEAGUE_ADMIN, CHAPTER_COORDINATOR, QUESTIONNAIRE_EDITOR,
                  FORUM_MODERATOR)
    contest = helpers.get_contest(cid)
    limit, offset = shape.pagination_params()
    rows, total = helpers.page_of(
        helpers.forums_of_contest(contest["id"]), limit, offset)
    return listing([serialize.forum_json(f) for f in rows],
                   limit, offset, total)


@bp.get("/forums/<fid>")
def read_forum(fid):
    require_roles(LEAGUE_ADMIN, CHAPTER_COORDINATOR, FORUM_MODERATOR)
    return success(serialize.forum_json(helpers.get_forum(fid)))


@bp.post("/forums/<fid>/transitions")
def transition_forum(fid):
    uid, role, volunteer = require_roles(FORUM_MODERATOR)
    b = shape.body()
    shape.no_extra(b, {"to", "minutes_text"})
    to = shape.s_str(b, "to")
    minutes_text = shape.s_str(b, "minutes_text", required=False)
    forum = helpers.get_forum(fid)
    if uid != forum["moderator_volunteer_id"]:
        raise unauthorized_role("Only the assigned moderator drives the forum")
    if to == "HELD" and (minutes_text is None or minutes_text == ""):
        raise invalid_request(
            "minutes_text is required when marking a forum HELD")
    if (forum["status"], to) not in FORUM_TRANSITIONS:
        raise invalid_state("Cannot move a %s forum to %s"
                            % (forum["status"], to))
    check_active_current(volunteer)
    if to == "CONFIRMED":
        contest = store.contests[forum["contest_id"]]
        forum["eligible_candidate_count"] = \
            serialize.verified_candidate_count(contest)
        if forum["eligible_candidate_count"] < calc.FORUM_QUORUM:
            raise forum_quorum_not_met()
    elif to == "HELD":
        if not store.clock >= forum["scheduled_end"]:
            raise forum_not_concluded()
        forum["minutes_text"] = minutes_text
    forum["status"] = to
    touch(forum)
    return success(serialize.forum_json(forum))


@bp.post("/forums/<fid>/questions")
def submit_question(fid):
    uid, role, volunteer = require_roles(PUBLIC_USER, FORUM_MODERATOR)
    b = shape.body()
    shape.no_extra(b, {"question_text", "source"})
    question_text = shape.s_str(b, "question_text")
    source = shape.s_enum(b, "source", QUESTION_SOURCES)
    forum = helpers.get_forum(fid)
    if role == PUBLIC_USER:
        if source != "PUBLIC_SUBMISSION":
            raise unauthorized_role(
                "A PublicUser may only submit PUBLIC_SUBMISSION questions")
        author_id = None
    else:
        if uid != forum["moderator_volunteer_id"]:
            raise unauthorized_role(
                "Only the assigned moderator may submit to this forum")
        author_id = uid if source == "MODERATOR_AUTHORED" else None
    if forum["status"] not in ("PLANNED", "CONFIRMED"):
        raise invalid_state("The forum is not accepting questions")
    if role == FORUM_MODERATOR:
        check_active_current(volunteer)
    question = base_entity()
    question.update({
        "forum_id": forum["id"],
        "question_text": question_text,
        "source": source,
        "author_volunteer_id": author_id,
        "status": "SUBMITTED",
    })
    store.questions[question["id"]] = question
    return success(serialize.question_json(question), status=201)


@bp.get("/forums/<fid>/questions")
def list_questions(fid):
    require_roles(LEAGUE_ADMIN, CHAPTER_COORDINATOR, FORUM_MODERATOR,
                  PUBLIC_USER)
    forum = helpers.get_forum(fid)
    limit, offset = shape.pagination_params()
    status_filter = shape.q("status")
    rows = helpers.questions_of_forum(forum["id"])
    if status_filter is not None:
        rows = [q for q in rows if q["status"] == status_filter]
    rows, total = helpers.page_of(rows, limit, offset)
    return listing([serialize.question_json(q) for q in rows],
                   limit, offset, total)


def _curation_checks(qid):
    """Shared select/reject ladder: role, path, ownership, state, battery."""
    uid, role, volunteer = require_roles(FORUM_MODERATOR)
    b = shape.body()
    shape.no_extra(b, set())
    question = helpers.get_question(qid)
    forum = store.forums[question["forum_id"]]
    if uid != forum["moderator_volunteer_id"]:
        raise unauthorized_role("Only the assigned moderator curates questions")
    if question["status"] != "SUBMITTED" or forum["status"] != "CONFIRMED":
        raise invalid_state(
            "Questions are curated on a CONFIRMED forum while SUBMITTED")
    check_active_current(volunteer)
    return uid, question, forum


@bp.post("/forum-questions/<qid>/select")
def select_question(qid):
    uid, question, forum = _curation_checks(qid)
    if (question["source"] == "MODERATOR_AUTHORED"
            and question["author_volunteer_id"] == uid):
        raise sod_moderator_own_question()
    selected = sum(1 for q in helpers.questions_of_forum(forum["id"])
                   if q["status"] == "SELECTED")
    if selected >= QUESTION_CAP:
        raise question_cap_reached()
    question["status"] = "SELECTED"
    touch(question)
    return success(serialize.question_json(question))


@bp.post("/forum-questions/<qid>/reject")
def reject_question(qid):
    uid, question, forum = _curation_checks(qid)
    question["status"] = "REJECTED"
    touch(question)
    return success(serialize.question_json(question))
