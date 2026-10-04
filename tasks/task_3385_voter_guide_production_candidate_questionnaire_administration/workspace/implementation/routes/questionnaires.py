"""Questionnaire routes (PRD 3.3): create/read/amend/issue/close/pin."""
from flask import Blueprint

import helpers
import serialize
import shape
import shells
from authz import (CHAPTER_COORDINATOR, LEAGUE_ADMIN, QUESTIONNAIRE_EDITOR,
                   check_active_current, require_roles)
from errors import (close_before_deadline, contest_kind_mismatch,
                    cycle_not_open, duplicate_questionnaire, invalid_request,
                    invalid_state, stale_version)
from helpers import base_entity, touch
from respond import listing, success
from store import store

bp = Blueprint("questionnaires", __name__)

QUESTION_FIELDS = {"position_index", "prompt_text", "word_limit_override"}


def s_questions(b, name="questions", required=True):
    questions = shape.s_list(b, name, required=required)
    if questions is None:
        return None
    seen = set()
    out = []
    for item in questions:
        if not isinstance(item, dict):
            raise invalid_request("Each question must be an object")
        shape.no_extra(item, QUESTION_FIELDS)
        position_index = shape.s_int(item, "position_index")
        prompt_text = shape.s_str(item, "prompt_text")
        override = shape.s_int(item, "word_limit_override", required=False,
                               minimum=1)
        if position_index in seen:
            raise invalid_request("Question position_index values must be unique")
        seen.add(position_index)
        out.append({
            "position_index": position_index,
            "prompt_text": prompt_text,
            "word_limit_override": override,
        })
    return out


@bp.post("/contests/<cid>/questionnaire")
def create_questionnaire(cid):
    uid, role, volunteer = require_roles(QUESTIONNAIRE_EDITOR)
    b = shape.body()
    shape.no_extra(b, {"due_at", "questions"})
    due_at = shape.s_instant(b, "due_at")
    questions = s_questions(b)
    contest = helpers.get_contest(cid)
    cycle = helpers.cycle_of_contest(contest)
    if cycle["status"] != "OPEN":
        raise cycle_not_open()
    if contest["status"] != "QUESTIONNAIRE_PHASE":
        raise invalid_state("The contest is not in QUESTIONNAIRE_PHASE")
    check_active_current(volunteer)
    if helpers.questionnaire_of_contest(contest["id"]) is not None:
        raise duplicate_questionnaire()
    if contest["kind"] != "CANDIDATE_RACE":
        raise contest_kind_mismatch(
            "Only a CANDIDATE_RACE contest carries a questionnaire")
    q = base_entity()
    q.update({
        "contest_id": contest["id"],
        "due_at": due_at,
        "questions": questions,
        "status": "DRAFT",
    })
    store.questionnaires[q["id"]] = q
    return success(serialize.questionnaire_json(q), status=201)


@bp.get("/contests/<cid>/questionnaire")
def read_contest_questionnaire(cid):
    require_roles(LEAGUE_ADMIN, CHAPTER_COORDINATOR, QUESTIONNAIRE_EDITOR)
    contest = helpers.get_contest(cid)
    q = helpers.questionnaire_of_contest(contest["id"])
    rows = [] if q is None else [serialize.questionnaire_json(q)]
    limit, offset = shape.pagination_params()
    return listing(rows, limit, offset, len(rows))


@bp.get("/questionnaires/<qid>")
def read_questionnaire(qid):
    require_roles(LEAGUE_ADMIN, CHAPTER_COORDINATOR, QUESTIONNAIRE_EDITOR)
    return success(serialize.questionnaire_json(helpers.get_questionnaire(qid)))


@bp.post("/questionnaires/<qid>/amend")
def amend_questionnaire(qid):
    uid, role, volunteer = require_roles(QUESTIONNAIRE_EDITOR)
    b = shape.body()
    shape.no_extra(b, {"expected_questionnaire_version", "due_at", "questions"})
    expected = shape.s_int(b, "expected_questionnaire_version")
    due_at = shape.s_instant(b, "due_at", required=False)
    questions = s_questions(b, required=False)
    q = helpers.get_questionnaire(qid)
    if q["status"] not in ("DRAFT", "ISSUED"):
        raise invalid_state("Only a DRAFT or ISSUED questionnaire may be amended")
    if expected != q["version"]:
        raise stale_version()
    check_active_current(volunteer)
    if due_at is not None:
        q["due_at"] = due_at
    if questions is not None:
        q["questions"] = questions
    touch(q)
    # Extending the deadline beyond the current logical time re-invites every
    # NONRESPONSE_MARKED shell (PRD 3.3).
    if q["status"] == "ISSUED" and due_at is not None and due_at > store.clock:
        for shell in helpers.shells_of_questionnaire(q["id"]):
            if shell["status"] == "NONRESPONSE_MARKED":
                shell["status"] = "INVITED"
                touch(shell)
    return success(serialize.questionnaire_json(q))


@bp.post("/questionnaires/<qid>/issue")
def issue_questionnaire(qid):
    uid, role, volunteer = require_roles(QUESTIONNAIRE_EDITOR)
    b = shape.body()
    shape.no_extra(b, set())
    q = helpers.get_questionnaire(qid)
    if len(q["questions"]) == 0:
        raise invalid_request("Cannot issue a questionnaire with no questions")
    if q["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT questionnaire may be issued")
    contest = store.contests[q["contest_id"]]
    if contest["status"] != "QUESTIONNAIRE_PHASE":
        raise invalid_state("The contest is not in QUESTIONNAIRE_PHASE")
    check_active_current(volunteer)
    for filing in helpers.filings_of_contest(contest["id"]):
        if (filing["status"] == "VERIFIED"
                and helpers.shell_of(q["id"], filing["id"]) is None):
            shells.create_shell(q, filing)
    q["status"] = "ISSUED"
    touch(q)
    return success(serialize.questionnaire_json(q))


@bp.post("/questionnaires/<qid>/close")
def close_questionnaire(qid):
    uid, role, volunteer = require_roles(QUESTIONNAIRE_EDITOR)
    b = shape.body()
    shape.no_extra(b, set())
    q = helpers.get_questionnaire(qid)
    if q["status"] != "ISSUED":
        raise invalid_state("Only an ISSUED questionnaire may be closed")
    check_active_current(volunteer)
    if not store.clock > q["due_at"]:
        raise close_before_deadline()
    q["status"] = "CLOSED"
    touch(q)
    return success(serialize.questionnaire_json(q))


@bp.post("/questionnaires/<qid>/pin")
def pin_questionnaire(qid):
    uid, role, volunteer = require_roles(QUESTIONNAIRE_EDITOR)
    b = shape.body()
    shape.no_extra(b, set())
    q = helpers.get_questionnaire(qid)
    if q["status"] != "CLOSED":
        raise invalid_state("Only a CLOSED questionnaire may be pinned")
    check_active_current(volunteer)
    q["status"] = "PINNED"
    touch(q)
    return success(serialize.questionnaire_json(q))
