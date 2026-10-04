"""CandidateResponse routes (PRD 3.4): submit, resubmit, list, sweep."""
from flask import Blueprint

import calc
import helpers
import serialize
import shape
from authz import (CANDIDATE, CHAPTER_COORDINATOR, LEAGUE_ADMIN,
                   QUESTIONNAIRE_EDITOR, check_active_current, require_roles)
from errors import (filing_not_verified, invalid_request, invalid_state,
                    not_found, questionnaire_not_accepting,
                    submission_window_closed)
from helpers import touch
from respond import listing, success
from store import store

bp = Blueprint("responses", __name__)

ANSWER_FIELDS = {"position_index", "text"}


def s_answers(b):
    answers = shape.s_list(b, "answers")
    out = []
    for item in answers:
        if not isinstance(item, dict):
            raise invalid_request("Each answer must be an object")
        shape.no_extra(item, ANSWER_FIELDS)
        out.append({
            "position_index": shape.s_int(item, "position_index"),
            "text": shape.s_str(item, "text"),
        })
    return out


def _declared_positions(questionnaire):
    return {qu["position_index"]: qu for qu in questionnaire["questions"]}


def check_coverage(questionnaire, answers):
    """Every declared position_index answered exactly once (PRD 3.4)."""
    declared = _declared_positions(questionnaire)
    seen = set()
    for answer in answers:
        pos = answer["position_index"]
        if pos in seen:
            raise invalid_request("Duplicate answer for position_index %s" % pos)
        if pos not in declared:
            raise invalid_request("Answer for undeclared position_index %s" % pos)
        seen.add(pos)
    if seen != set(declared):
        raise invalid_request("Answers must cover every declared position_index")


def _evaluate(questionnaire, contest, answers):
    """Word counts in answers order + the over-limit positions."""
    declared = _declared_positions(questionnaire)
    counts = []
    over = []
    for answer in answers:
        count = calc.word_count(answer["text"], contest["word_count_policy"])
        counts.append(count)
        question = declared[answer["position_index"]]
        limit = question["word_limit_override"]
        if limit is None:
            limit = contest["questionnaire_word_limit"]
        if count > limit:
            over.append(answer["position_index"])
    return counts, over


def _land(shell, questionnaire, answers, counts, over):
    """Shared landing logic for submit and resubmit (PRD 3.4)."""
    shell["answers"] = answers
    shell["per_answer_word_counts"] = counts
    if over:
        shell["status"] = "OVER_LIMIT_RETURNED"
        shell["over_limit_positions"] = over
    else:
        shell["status"] = "SUBMITTED"
        shell["submitted_at"] = store.clock
        shell["over_limit_positions"] = []
        touch(questionnaire)  # a fresh SUBMITTED advances Questionnaire.version
    touch(shell)


def _submission_gates(questionnaire, shell):
    """Bands 7/8/19 in ladder order (state beats temporal, PRD 2.7)."""
    if questionnaire["status"] != "ISSUED":
        raise questionnaire_not_accepting()
    filing = store.filings[shell["filing_id"]]
    if filing["status"] != "VERIFIED":
        raise filing_not_verified()
    if not store.clock <= questionnaire["due_at"]:
        raise submission_window_closed()


@bp.post("/questionnaires/<qid>/responses")
def submit_response(qid):
    uid, role, _ = require_roles(CANDIDATE)
    b = shape.body()
    shape.no_extra(b, {"answers"})
    answers = s_answers(b)
    questionnaire = helpers.get_questionnaire(qid)
    shell = helpers.shell_of(questionnaire["id"], uid)
    if shell is None:
        # Also what a candidate sees when probing another filing's slot.
        raise not_found("No response shell exists for this filing")
    check_coverage(questionnaire, answers)
    if shell["status"] not in ("INVITED", "WITHDRAWN_HIDDEN"):
        raise invalid_state("The shell does not accept an initial submission")
    _submission_gates(questionnaire, shell)
    contest = store.contests[questionnaire["contest_id"]]
    counts, over = _evaluate(questionnaire, contest, answers)
    _land(shell, questionnaire, answers, counts, over)
    return success(serialize.response_json(shell), status=201)


@bp.get("/questionnaires/<qid>/responses")
def list_responses(qid):
    require_roles(LEAGUE_ADMIN, CHAPTER_COORDINATOR, QUESTIONNAIRE_EDITOR)
    questionnaire = helpers.get_questionnaire(qid)
    limit, offset = shape.pagination_params()
    status_filter = shape.q("status")
    rows = helpers.shells_of_questionnaire(questionnaire["id"])
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    rows, total = helpers.page_of(rows, limit, offset)
    return listing([serialize.response_json(r) for r in rows],
                   limit, offset, total)


@bp.post("/responses/<rid>/resubmit")
def resubmit_response(rid):
    uid, role, _ = require_roles(CANDIDATE)
    b = shape.body()
    shape.no_extra(b, {"answers"})
    answers = s_answers(b)
    shell = helpers.get_response(rid)
    if shell["filing_id"] != uid:
        # Another filing's shell path surfaces as a missing shell (PRD 2.1).
        raise not_found("No response shell exists for this filing")
    questionnaire = store.questionnaires[shell["questionnaire_id"]]
    check_coverage(questionnaire, answers)
    # A withdrawn filing hides the shell (PRD 3.4); let it reach the
    # filing-verified gate so it surfaces as ERR_FILING_NOT_VERIFIED,
    # exactly as on the initial-submit path.
    if shell["status"] not in ("OVER_LIMIT_RETURNED", "WITHDRAWN_HIDDEN"):
        raise invalid_state("Only an OVER_LIMIT_RETURNED shell may be resubmitted")
    _submission_gates(questionnaire, shell)
    contest = store.contests[questionnaire["contest_id"]]
    counts, over = _evaluate(questionnaire, contest, answers)
    _land(shell, questionnaire, answers, counts, over)
    return success(serialize.response_json(shell))


@bp.post("/contests/<cid>/sweep-nonresponses")
def sweep_nonresponses(cid):
    uid, role, volunteer = require_roles(CHAPTER_COORDINATOR)
    b = shape.body()
    shape.no_extra(b, set())
    contest = helpers.get_contest(cid)
    questionnaire = helpers.questionnaire_of_contest(contest["id"])
    if (questionnaire is None or questionnaire["status"] != "ISSUED"
            or not store.clock > questionnaire["due_at"]):
        raise invalid_state(
            "The sweep is defined only for an ISSUED questionnaire past its deadline")
    check_active_current(volunteer)
    marked_nonresponse = 0
    marked_late = 0
    for shell in helpers.shells_of_questionnaire(questionnaire["id"]):
        if shell["status"] == "INVITED":
            shell["status"] = "NONRESPONSE_MARKED"
            touch(shell)
            marked_nonresponse += 1
        elif shell["status"] == "OVER_LIMIT_RETURNED":
            shell["status"] = "LATE_UNPUBLISHED"
            touch(shell)
            marked_late += 1
    return success({
        "marked_nonresponse_count": marked_nonresponse,
        "marked_late_count": marked_late,
    })
