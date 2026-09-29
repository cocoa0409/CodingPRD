"""Sanction proposal, the imposition cascade, completion and appeals
(PRD 3.8 and 3.9).
"""

from flask import Blueprint, request

import calc
import cascades
from db import S, new_row, touch
from errors import fail
from lookup import appeal_or_404, case_or_404, filter_rows, sanction_or_404
from middleware import (ROLE_APPEALS_DEAN, ROLE_FACULTY_REPORTER, ROLE_INTEGRITY_OFFICER,
                        ROLE_REGISTRAR_OFFICER, ROLE_STUDENT, auth, require_owner)
from response import created, ok, ok_list, pagination
from serializers import appeal_json, sanction_json
from shapes import Field, peek, validate
from util import D0, add_days

bp = Blueprint("sanctions", __name__)

GROUNDS = ("PROCEDURE", "EVIDENCE", "SANCTION_SEVERITY")
OUTCOMES = ("UPHELD_ORIGINAL", "SANCTION_REDUCED", "REMANDED", "OVERTURNED")
FINDING_STATES = ("DECIDED", "INFORMAL_ACCEPTED", "SANCTION_IMPOSED")
LIVE_SANCTION_STATES = ("PROPOSED", "ACCEPTED", "IMPOSED")

SANCTION_FIELDS = [
    Field("case_id", "string"),
    Field("expected_case_version", "integer"),
    Field("kind", "enum", values=calc.SANCTION_KINDS),
    Field("ladder_rank", "integer", minimum=1, maximum=8),
    Field("effective_from", "datetime"),
    Field("grade_component_code", "string", required=False),
]

APPEAL_FIELDS = [
    Field("case_id", "string"),
    Field("grounds", "enum", values=GROUNDS),
    Field("statement", "string", min_len=20, max_len=4000),
]

SCREEN_FIELDS = [
    Field("decision", "enum", values=("ACCEPT_FOR_REVIEW", "DENY_NO_GROUNDS")),
    Field("decision_reason", "string", required=False, min_len=1, max_len=500),
]

DECIDE_FIELDS = [
    Field("outcome", "enum", values=OUTCOMES),
    Field("decision_reason", "string", min_len=1, max_len=500),
    Field("reduced_ladder_rank", "integer", required=False, minimum=1, maximum=8),
]


def fk_filter(param, resolver):
    raw = request.args.get(param)
    if raw is not None and raw != "":
        resolver(raw)


def gradebook_codes(case):
    offering = calc.offering_of_case(case)
    if offering is None:
        return []
    return [component["code"] for component in offering["grade_components"]]


# ---------------------------------------------------------------- proposals

@bp.route("/integrity/sanctions", methods=["POST"])
def propose_sanction():
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(SANCTION_FIELDS)
    case = case_or_404(body["case_id"])
    if case["adjudication_status"] != "DECIDED":
        fail("ERR_CASE_STATE_INVALID",
             "A formal sanction may only be proposed on a case in DECIDED.")
    if body["expected_case_version"] != case["version"]:
        fail("ERR_STALE_CASE_VERSION",
             "expected_case_version does not match the case's current version.")
    code = body["grade_component_code"]
    if code is not None and code not in gradebook_codes(case):
        fail("ERR_GRADE_COMPONENT_NOT_FOUND",
             "grade_component_code names no code in the case's offering gradebook.")
    kind = body["kind"]
    if kind == "GRADE_PENALTY_ASSIGNMENT" and code is None:
        fail("ERR_GRADE_COMPONENT_REQUIRED",
             "grade_component_code is required for an assignment grade penalty.")
    if kind != "GRADE_PENALTY_ASSIGNMENT" and code is not None:
        fail("ERR_GRADE_COMPONENT_REQUIRED",
             "grade_component_code is forbidden for every kind other than "
             "GRADE_PENALTY_ASSIGNMENT.")
    if case["decided_at"] is not None and body["effective_from"] < case["decided_at"]:
        fail("ERR_SANCTION_EFFECTIVE_BEFORE_DECISION",
             "effective_from may not precede the case's decided_at.")
    rank = body["ladder_rank"]
    band_min, band_max = calc.office_band(case["recommended_ladder_rank"])
    if rank > band_max:
        fail("ERR_SANCTION_ABOVE_LADDER_BAND",
             "ladder_rank sits above the permitted office band.")
    if rank < band_min:
        fail("ERR_SANCTION_BELOW_LADDER_BAND",
             "ladder_rank sits below the permitted office band.")
    if kind != calc.sanction_kind_for_rank(rank):
        fail("ERR_SANCTION_KIND_RANK_MISMATCH", "kind is not the kind that ladder_rank maps to.")
    superseded_id = cascades.supersede_proposed(case["id"])
    row = new_row(
        case_id=case["id"],
        replaces_sanction_id=superseded_id,
        kind=kind,
        ladder_rank=rank,
        grade_component_code=code,
        effective_from=body["effective_from"],
        status="PROPOSED",
        origin="OFFICE_PROPOSAL",
        baseline_course_grade_pct=D0,
        adjusted_course_grade_pct=D0,
        grade_penalty_delta_pct=D0,
        imposed_at=None,
        completed_at=None,
        vacated_reason=None,
    )
    S.sanctions[row["id"]] = row
    touch(case)
    return created(sanction_json(row))


@bp.route("/integrity/sanctions", methods=["GET"])
def list_sanctions():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_STUDENT, ROLE_REGISTRAR_OFFICER, ROLE_APPEALS_DEAN])
    limit, offset = pagination()
    fk_filter("case_id", case_or_404)
    fk_filter("replaces_sanction_id", sanction_or_404)
    rows = filter_rows(S.sanctions, {
        "case_id": "case_id",
        "status": "status",
        "kind": "kind",
        "replaces_sanction_id": "replaces_sanction_id",
    })
    return ok_list(rows, sanction_json, limit, offset)


@bp.route("/integrity/sanctions/<row_id>", methods=["GET"])
def read_sanction(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_STUDENT, ROLE_REGISTRAR_OFFICER, ROLE_APPEALS_DEAN,
          ROLE_FACULTY_REPORTER])
    return ok(sanction_json(sanction_or_404(row_id)))


@bp.route("/integrity/sanctions/<row_id>/impose", methods=["POST"])
def impose_sanction(row_id):
    auth([ROLE_INTEGRITY_OFFICER])
    sanction = sanction_or_404(row_id)
    case = S.cases.get(sanction["case_id"])
    status = case["adjudication_status"] if case is not None else None
    # Rank 13 (case state) outranks rank 19 (sanction state).
    if status not in ("DECIDED", "INFORMAL_ACCEPTED"):
        fail("ERR_CASE_STATE_INVALID",
             "A sanction may only be imposed on a case in DECIDED or INFORMAL_ACCEPTED.")
    if status == "DECIDED" and case["responsibility_finding"] != "RESPONSIBLE":
        fail("ERR_CASE_STATE_INVALID",
             "The formal route requires a responsibility_finding of RESPONSIBLE.")
    expected = "PROPOSED" if status == "DECIDED" else "ACCEPTED"
    if sanction["status"] != expected:
        fail("ERR_SANCTION_STATE_INVALID",
             "The sanction must be %s to be imposed on a case in %s." % (expected, status))
    if sanction["kind"] in calc.GRADE_PENALTY_KINDS:
        offering = calc.offering_of_case(case)
        report = calc.report_of_case(case)
        joined = offering is not None and report is not None and \
            calc.component_scores_join_ok(offering, report["component_scores"])
        if not joined:
            fail("ERR_COMPONENT_SCORES_INCOMPLETE",
                 "The report's component_scores no longer join to the offering gradebook.")
    if case["decided_at"] is not None and sanction["effective_from"] < case["decided_at"]:
        fail("ERR_SANCTION_EFFECTIVE_BEFORE_DECISION",
             "effective_from may not precede the case's decided_at.")
    cascades.impose_cascade(sanction, case)
    return ok(sanction_json(sanction))


@bp.route("/integrity/sanctions/<row_id>/complete", methods=["POST"])
def complete_sanction(row_id):
    auth([ROLE_INTEGRITY_OFFICER])
    sanction = sanction_or_404(row_id)
    case = S.cases.get(sanction["case_id"])
    # Rank 13 (case state) outranks rank 19 (sanction state).
    for appeal in calc.appeals_of_case(sanction["case_id"]):
        if appeal["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            fail("ERR_CASE_STATE_INVALID",
                 "An appeal of this case is still open.")
    if sanction["status"] != "IMPOSED":
        fail("ERR_SANCTION_STATE_INVALID", "Only an IMPOSED sanction may be completed.")
    sanction["status"] = "COMPLETED"
    sanction["completed_at"] = S.clock
    touch(sanction)
    if case is not None:
        if case["notation_status"] == "POSTED":
            case["expungement_eligible_at"] = calc.expungement_eligible_at(case)
        case["adjudication_status"] = "CLOSED"
        touch(case)
        cascades.recompute_department_of_case(case)
    return ok(sanction_json(sanction))


# ---------------------------------------------------------------- appeals

@bp.route("/integrity/appeals", methods=["POST"])
def file_appeal():
    actor = auth([ROLE_STUDENT])
    hinted = peek("case_id")
    known = S.cases.get(hinted) if isinstance(hinted, str) else None
    if known is not None:
        require_owner(actor, known["student_id"])
    body = validate(APPEAL_FIELDS)
    case = case_or_404(body["case_id"])
    if case["adjudication_status"] not in FINDING_STATES:
        fail("ERR_CASE_STATE_INVALID",
             "The case has not reached a finding, so it may not be appealed.")
    deadline = add_days(case["decided_at"], calc.APPEAL_WINDOW_DAYS) \
        if case["decided_at"] is not None else None
    if deadline is None or S.clock > deadline:
        fail("ERR_APPEAL_WINDOW_CLOSED", "The ten-day appeal window has closed.")
    existing = calc.appeals_of_case(case["id"])
    for appeal in existing:
        if appeal["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            fail("ERR_APPEAL_ALREADY_FILED", "An appeal of this case is already open.")
    if len(existing) >= calc.APPEAL_MAX_PER_CASE:
        fail("ERR_APPEAL_ALREADY_FILED", "This case has already had two appeals.")
    row = new_row(
        case_id=case["id"],
        grounds=body["grounds"],
        statement=body["statement"],
        filed_at=S.clock,
        status="SUBMITTED",
        hearing_round_at_filing=case["hearing_round"],
        reduced_ladder_rank=None,
        decision_reason=None,
        decided_at=None,
    )
    S.appeals[row["id"]] = row
    return created(appeal_json(row))


@bp.route("/integrity/appeals", methods=["GET"])
def list_appeals():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_APPEALS_DEAN, ROLE_STUDENT])
    limit, offset = pagination()
    fk_filter("case_id", case_or_404)
    rows = filter_rows(S.appeals, {
        "case_id": "case_id",
        "status": "status",
        "grounds": "grounds",
    })
    return ok_list(rows, appeal_json, limit, offset)


@bp.route("/integrity/appeals/<row_id>", methods=["GET"])
def read_appeal(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_APPEALS_DEAN, ROLE_STUDENT])
    return ok(appeal_json(appeal_or_404(row_id)))


@bp.route("/integrity/cases/<row_id>/appeals", methods=["GET"])
def list_case_appeals(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_APPEALS_DEAN, ROLE_STUDENT])
    # PRD 2.6: the parent case is resolved before anything nested.
    case = case_or_404(row_id)
    limit, offset = pagination()
    rows = calc.appeals_of_case(case["id"])
    return ok_list(rows, appeal_json, limit, offset)


@bp.route("/integrity/appeals/<row_id>/screen", methods=["POST"])
def screen_appeal(row_id):
    auth([ROLE_APPEALS_DEAN])
    body = validate(SCREEN_FIELDS)
    if body["decision"] == "DENY_NO_GROUNDS" and body["decision_reason"] is None:
        fail("ERR_INVALID_REQUEST", "decision_reason is required on a denial.")
    appeal = appeal_or_404(row_id)
    case = S.cases.get(appeal["case_id"])
    status = case["adjudication_status"] if case is not None else None
    # Rank 13 (case state) outranks rank 20 (appeal state).
    if status not in FINDING_STATES:
        fail("ERR_CASE_STATE_INVALID",
             "The case is no longer in a state from which an appeal may be screened.")
    if appeal["status"] != "SUBMITTED":
        fail("ERR_APPEAL_STATE_INVALID", "Only a SUBMITTED appeal may be screened.")
    if case["pathway"] == "INFORMAL" and status == "INFORMAL_ACCEPTED" \
            and appeal["grounds"] != "PROCEDURE":
        fail("ERR_INFORMAL_RESOLUTION_NOT_APPEALABLE",
             "An accepted informal resolution may only be appealed on PROCEDURE.")
    if body["decision"] == "ACCEPT_FOR_REVIEW":
        appeal["status"] = "UNDER_REVIEW"
        touch(appeal)
        case["pre_appeal_adjudication_status"] = status
        case["adjudication_status"] = "APPEAL_UNDER_REVIEW"
        touch(case)
    else:
        appeal["status"] = "DENIED_NO_GROUNDS"
        appeal["decision_reason"] = body["decision_reason"]
        appeal["decided_at"] = S.clock
        touch(appeal)
        # The case is deliberately left untouched: review was never reached.
        cascades.create_notice(appeal["case_id"], "APPEAL_OUTCOME_NOTICE")
    return ok(appeal_json(appeal))


def clear_notation_on_relief(case, expunge_when_posted=True):
    """A notation that never posted becomes NOT_APPLICABLE; a posted one is
    EXPUNGED (PRD 3.9)."""
    if case["notation_status"] == "PENDING_POSTING":
        case["notation_status"] = "NOT_APPLICABLE"
    elif case["notation_status"] == "POSTED" and expunge_when_posted:
        case["notation_status"] = "EXPUNGED"


@bp.route("/integrity/appeals/<row_id>/decide", methods=["POST"])
def decide_appeal(row_id):
    auth([ROLE_APPEALS_DEAN])
    body = validate(DECIDE_FIELDS)
    outcome = body["outcome"]
    reduced = body["reduced_ladder_rank"]
    if outcome == "SANCTION_REDUCED" and reduced is None:
        fail("ERR_INVALID_REQUEST",
             "reduced_ladder_rank is required when the outcome is SANCTION_REDUCED.")
    if outcome != "SANCTION_REDUCED" and reduced is not None:
        fail("ERR_INVALID_REQUEST",
             "reduced_ladder_rank is forbidden unless the outcome is SANCTION_REDUCED.")
    appeal = appeal_or_404(row_id)
    case = S.cases.get(appeal["case_id"])
    # Rank 15 (pathway) outranks rank 20 (appeal state).
    if outcome == "REMANDED" and case is not None and case["pathway"] != "FORMAL":
        fail("ERR_CASE_PATHWAY_NOT_SET", "Only a FORMAL case may be remanded.")
    if appeal["status"] != "UNDER_REVIEW":
        fail("ERR_APPEAL_STATE_INVALID", "Only an UNDER_REVIEW appeal may be decided.")
    grounds = appeal["grounds"]
    if outcome == "SANCTION_REDUCED" and grounds != "SANCTION_SEVERITY":
        fail("ERR_APPEAL_GROUNDS_MISMATCH",
             "A reduction requires grounds of SANCTION_SEVERITY.")
    if outcome in ("REMANDED", "OVERTURNED") and grounds not in ("PROCEDURE", "EVIDENCE"):
        fail("ERR_APPEAL_GROUNDS_MISMATCH",
             "A remand or an overturn requires grounds of PROCEDURE or EVIDENCE.")
    governing = calc.governing_sanction(appeal["case_id"])
    if outcome == "SANCTION_REDUCED":
        if governing is None or reduced < 1 or reduced >= governing["ladder_rank"]:
            fail("ERR_REDUCED_RANK_INVALID",
                 "reduced_ladder_rank must be at least 1 and strictly below the "
                 "governing sanction's ladder_rank.")
    if outcome == "REMANDED" and case["hearing_round"] > calc.REMAND_MAX_HEARING_ROUND:
        fail("ERR_REMAND_LIMIT_REACHED", "This case has already been remanded once.")

    appeal["status"] = outcome
    appeal["decision_reason"] = body["decision_reason"]
    appeal["decided_at"] = S.clock
    if outcome == "SANCTION_REDUCED":
        appeal["reduced_ladder_rank"] = reduced
    touch(appeal)

    if outcome == "UPHELD_ORIGINAL":
        # No sanction and no severity field moves.
        case["adjudication_status"] = case["pre_appeal_adjudication_status"]
        case["pre_appeal_adjudication_status"] = None
        touch(case)
    elif outcome == "SANCTION_REDUCED":
        was_imposed = governing["status"] == "IMPOSED"
        governing["status"] = "VACATED"
        governing["vacated_reason"] = "APPEAL_REDUCED"
        touch(governing)
        replacement = new_row(
            case_id=case["id"],
            replaces_sanction_id=governing["id"],
            kind=calc.sanction_kind_for_rank(reduced),
            ladder_rank=reduced,
            grade_component_code=None,
            effective_from=governing["effective_from"],
            status="IMPOSED" if was_imposed else "PROPOSED",
            origin="APPEAL_REDUCTION",
            baseline_course_grade_pct=D0,
            adjusted_course_grade_pct=D0,
            grade_penalty_delta_pct=D0,
            imposed_at=S.clock if was_imposed else None,
            completed_at=None,
            vacated_reason=None,
        )
        S.sanctions[replacement["id"]] = replacement
        # The student's points and standing are derived from the ledger above.
        if reduced < calc.NOTATION_MIN_RANK:
            clear_notation_on_relief(case)
        case["adjudication_status"] = case["pre_appeal_adjudication_status"]
        case["pre_appeal_adjudication_status"] = None
        touch(case)
    elif outcome == "REMANDED":
        cascades.vacate_sanctions(case["id"], LIVE_SANCTION_STATES, "APPEAL_REMANDED")
        case["responsibility_finding"] = "UNDETERMINED"
        case["finding_basis"] = "NONE"
        case["panel_severity_recommendation"] = None
        case["decided_at"] = None
        # With a null panel recommendation the rank falls back to the tier rank.
        calc.apply_assessment(case)
        if case["notation_status"] == "PENDING_POSTING":
            case["notation_status"] = "NOT_APPLICABLE"
        cascades.create_notice(case["id"], "REHEARING_NOTICE")
        case["pre_appeal_adjudication_status"] = None
        case["adjudication_status"] = "FORMAL_REFERRED"
        touch(case)
    else:
        # Hop two.
        case["overturned"] = True
        case["responsibility_finding"] = "NOT_RESPONSIBLE"
        case["finding_basis"] = "APPEAL"
        case["adjudication_status"] = "CLOSED"
        case["pre_appeal_adjudication_status"] = None
        clear_notation_on_relief(case)
        cascades.vacate_sanctions(case["id"], LIVE_SANCTION_STATES, "APPEAL_OVERTURNED")
        touch(case)
        # Hop three -- every student roll-up and the department's open_case_count
        # are derived from the rows just written.
        cascades.recompute_department_of_case(case)
        # Hop four -- the student's other open cases.
        cascades.reassess_siblings(case["student_id"], case["id"], notify=False)

    cascades.create_notice(appeal["case_id"], "APPEAL_OUTCOME_NOTICE")
    return ok(appeal_json(appeal))
