"""Cases, the two-algorithm severity assessment, the informal pathway, notices
and the transcript-notation dimension (PRD 3.4, 3.5, 3.6 and 3.10).
"""

from flask import Blueprint, request

import calc
import cascades
from db import S, new_row, next_case_number, touch
from errors import fail
from lookup import (case_or_404, filter_rows, notification_or_404, offering_or_404,
                    report_or_404, student_or_404)
from middleware import (ROLE_APPEALS_DEAN, ROLE_FACULTY_REPORTER, ROLE_INTEGRITY_OFFICER,
                        ROLE_PANEL_CHAIR, ROLE_REGISTRAR_OFFICER, ROLE_STUDENT,
                        auth, require_owner)
from response import created, ok, ok_list, pagination
from serializers import case_json, notification_json, sanction_json
from shapes import Field, query_enum, validate
from util import D0, fmt_dt, num

bp = Blueprint("cases", __name__)

PATHWAYS = ("INFORMAL", "FORMAL")
FINDINGS = ("UNDETERMINED", "RESPONSIBLE", "NOT_RESPONSIBLE")

OPEN_CASE_FIELDS = [Field("report_id", "string")]

LEGACY_FIELDS = [
    Field("report_id", "string"),
    Field("decided_at", "datetime"),
    Field("responsibility_finding", "enum", values=FINDINGS),
    Field("imposed_ladder_rank", "integer", minimum=1, maximum=8),
    Field("completed_at", "datetime"),
]

PATHWAY_FIELDS = [Field("pathway", "enum", values=PATHWAYS)]

DISMISS_FIELDS = [Field("dismiss_reason", "string", min_len=1, max_len=500)]

INFORMAL_RESOLUTION_FIELDS = [
    Field("expected_case_version", "integer"),
    Field("proposed_ladder_rank", "integer", minimum=1, maximum=8),
    Field("kind", "enum", values=calc.SANCTION_KINDS),
    Field("effective_from", "datetime"),
    Field("grade_component_code", "string", required=False),
]

INFORMAL_RESPONSE_FIELDS = [Field("response", "enum", values=("ACCEPT", "DECLINE"))]

EXPUNGEMENT_REQUEST_FIELDS = [Field("request_statement", "string", min_len=1, max_len=4000)]

EXPUNGEMENT_DECISION_FIELDS = [
    Field("decision", "enum", values=("GRANT", "DENY")),
    Field("decision_reason", "string", required=False, min_len=1, max_len=500),
]

# Only ALLEGATION_NOTICE may be created through the endpoint; every other kind
# is raised as a side effect of another operation (PRD 3.5).
NOTICE_FIELDS = [
    Field("kind", "enum", values=("ALLEGATION_NOTICE",)),
    Field("response_window_days", "integer", required=False, minimum=1),
]


def new_case(**fields):
    """A case row carrying every documented default (PRD 3.4)."""
    row = new_row(
        report_id=None,
        student_id=None,
        offering_id=None,
        case_number=None,
        origin="OFFICE_INTAKE",
        pathway="UNASSIGNED",
        adjudication_status="INTAKE_REVIEW",
        notation_status="NOT_APPLICABLE",
        responsibility_finding="UNDETERMINED",
        finding_basis="NONE",
        hearing_round=0,
        overturned=False,
        decided_at=None,
        evidence_strength_score=D0,
        baseline_course_grade_pct=D0,
        cross_course_pattern_points=0,
        prior_upheld_count_at_assessment=0,
        prior_escalation_points=0,
        provisional_severity_index=D0,
        severity_index=D0,
        recommended_ladder_rank=1,
        informal_severity_index=D0,
        informal_recommended_ladder_rank=1,
        panel_severity_recommendation=None,
        pre_appeal_adjudication_status=None,
        dismiss_reason=None,
        expungement_eligible_at=None,
        notified_at=None,
    )
    row.update(fields)
    row["case_number"] = next_case_number()
    return row


def fk_filter(param, resolver):
    raw = request.args.get(param)
    if raw is not None and raw != "":
        resolver(raw)


# ---------------------------------------------------------------- opening

@bp.route("/integrity/cases", methods=["POST"])
def open_case():
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(OPEN_CASE_FIELDS)
    report = report_or_404(body["report_id"])
    if report["status"] != "ACCEPTED":
        fail("ERR_REPORT_STATE_INVALID", "Only an ACCEPTED report may be opened as a case.")
    if calc.case_for_report(report["id"]) is not None:
        fail("ERR_CASE_ALREADY_OPENED", "A case already exists for this report.")
    offering = offering_or_404(report["offering_id"])
    if not calc.component_scores_join_ok(offering, report["component_scores"]):
        fail("ERR_COMPONENT_SCORES_INCOMPLETE",
             "The report's component_scores no longer join to the offering gradebook.")
    case = new_case(
        report_id=report["id"],
        student_id=report["student_id"],
        offering_id=report["offering_id"],
        origin="OFFICE_INTAKE",
        evidence_strength_score=report["evidence_strength_score"],
        baseline_course_grade_pct=calc.course_grade_pct(
            offering, calc.component_scores_map(report)),
    )
    S.cases[case["id"]] = case
    # The full assessment runs at opening; the row is still at version 1.
    calc.apply_assessment(case)
    return created(case_json(case))


@bp.route("/integrity/cases/legacy-import", methods=["POST"])
def legacy_import():
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(LEGACY_FIELDS)
    if body["decided_at"] > S.clock:
        fail("ERR_INVALID_REQUEST", "decided_at may not be after the current logical clock.")
    if body["completed_at"] < body["decided_at"]:
        fail("ERR_INVALID_REQUEST", "completed_at may not precede decided_at.")
    report = report_or_404(body["report_id"])
    if report["status"] != "DRAFT":
        fail("ERR_REPORT_STATE_INVALID",
             "A legacy import must name a report that is still in DRAFT.")
    if calc.case_for_report(report["id"]) is not None:
        fail("ERR_CASE_ALREADY_OPENED", "A case already exists for this report.")
    case = new_case(
        report_id=report["id"],
        student_id=report["student_id"],
        offering_id=report["offering_id"],
        origin="LEGACY_IMPORT",
        pathway="FORMAL",
        adjudication_status="CLOSED",
        notation_status="NOT_APPLICABLE",
        responsibility_finding=body["responsibility_finding"],
        finding_basis="LEGACY",
        overturned=False,
        decided_at=body["decided_at"],
        evidence_strength_score=D0,
    )
    S.cases[case["id"]] = case
    rank = body["imposed_ladder_rank"]
    sanction = new_row(
        case_id=case["id"],
        replaces_sanction_id=None,
        kind=calc.sanction_kind_for_rank(rank),
        ladder_rank=rank,
        grade_component_code=None,
        effective_from=body["decided_at"],
        status="COMPLETED",
        origin="OFFICE_PROPOSAL",
        baseline_course_grade_pct=D0,
        adjusted_course_grade_pct=D0,
        grade_penalty_delta_pct=D0,
        imposed_at=body["decided_at"],
        completed_at=body["completed_at"],
        vacated_reason=None,
    )
    S.sanctions[sanction["id"]] = sanction
    return created(case_json(case))


@bp.route("/integrity/cases", methods=["GET"])
def list_cases():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_REGISTRAR_OFFICER, ROLE_APPEALS_DEAN])
    limit, offset = pagination()
    fk_filter("report_id", report_or_404)
    fk_filter("student_id", student_or_404)
    fk_filter("offering_id", offering_or_404)
    rows = filter_rows(S.cases, {
        "report_id": "report_id",
        "student_id": "student_id",
        "offering_id": "offering_id",
        "adjudication_status": "adjudication_status",
        "notation_status": "notation_status",
        "pathway": "pathway",
    })
    return ok_list(rows, case_json, limit, offset)


@bp.route("/integrity/cases/<row_id>", methods=["GET"])
def read_case(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_FACULTY_REPORTER, ROLE_PANEL_CHAIR, ROLE_STUDENT,
          ROLE_APPEALS_DEAN, ROLE_REGISTRAR_OFFICER])
    return ok(case_json(case_or_404(row_id)))


# ---------------------------------------------------------------- pathway

@bp.route("/integrity/cases/<row_id>/pathway", methods=["POST"])
def choose_pathway(row_id):
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(PATHWAY_FIELDS)
    case = case_or_404(row_id)
    if case["adjudication_status"] not in ("INTAKE_REVIEW", "NOTIFIED"):
        fail("ERR_CASE_STATE_INVALID",
             "The pathway may only be chosen while the case is in INTAKE_REVIEW or NOTIFIED.")
    if case["pathway"] != "UNASSIGNED":
        fail("ERR_CASE_PATHWAY_ALREADY_SET", "The case pathway has already been set.")
    if body["pathway"] == "INFORMAL" and case["recommended_ladder_rank"] > calc.INFORMAL_MAX_RANK:
        fail("ERR_INFORMAL_PATHWAY_NOT_PERMITTED",
             "The informal pathway is barred once the recommended ladder rank exceeds 3.")
    case["pathway"] = body["pathway"]
    touch(case)
    return ok(case_json(case))


# ---------------------------------------------------- the severity assessment

@bp.route("/integrity/cases/<row_id>/severity-assessment", methods=["GET"])
def severity_assessment(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_FACULTY_REPORTER, ROLE_APPEALS_DEAN])
    # PRD 2.6: the parent identifier is resolved before anything nested.
    case = case_or_404(row_id)
    basis = query_enum("pathway_basis", ("FORMAL", "INFORMAL"), "FORMAL")
    # The read re-runs the assessment and persists the recomputed fields; it is
    # not a write, so the case's version and updated_at are left alone.
    assessment = calc.apply_assessment(case)
    informal_permitted = assessment["recommended_ladder_rank"] <= calc.INFORMAL_MAX_RANK
    if basis == "INFORMAL":
        index = assessment["informal_severity_index"]
        rank = assessment["informal_recommended_ladder_rank"]
        band_min, band_max = 1, rank
        pattern_points = 0
        escalation = 0
        provisional = index
        tier = calc.tier_rank(index)
    else:
        index = assessment["severity_index"]
        rank = assessment["recommended_ladder_rank"]
        band_min, band_max = calc.office_band(rank)
        pattern_points = assessment["cross_course_pattern_points"]
        escalation = assessment["prior_escalation_points"]
        provisional = assessment["provisional_severity_index"]
        tier = assessment["tier_rank"]
    return ok({
        "case_id": case["id"],
        "pathway_basis": basis,
        "evidence_strength_score": num(case["evidence_strength_score"]),
        "base_points": assessment["base_points"],
        "evidence_contribution": num(assessment["evidence_contribution"]),
        "cross_course_pattern_points": pattern_points,
        "distinct_other_course_codes": assessment["distinct_other_course_codes"],
        "prior_upheld_count_at_assessment": assessment["prior_upheld_count_at_assessment"],
        "provisional_severity_index": num(provisional),
        "prior_escalation_points": escalation,
        "severity_index": num(index),
        "tier_rank": tier,
        "panel_severity_recommendation": case["panel_severity_recommendation"],
        "recommended_ladder_rank": rank,
        "recommended_kind": calc.sanction_kind_for_rank(rank),
        "permitted_band_min": band_min,
        "permitted_band_max": band_max,
        "required_panel_size": calc.required_panel_size(rank),
        "attorney_advisor_permitted": rank >= calc.ATTORNEY_ADVISOR_MIN_RANK,
        "informal_pathway_permitted": informal_permitted,
    })


# ---------------------------------------------------------------- dismissal

@bp.route("/integrity/cases/<row_id>/dismiss", methods=["POST"])
def dismiss_case(row_id):
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(DISMISS_FIELDS)
    case = case_or_404(row_id)
    if case["adjudication_status"] not in ("INTAKE_REVIEW", "NOTIFIED", "FORMAL_REFERRED"):
        fail("ERR_CASE_STATE_INVALID", "This case can no longer be dismissed.")
    cascades.vacate_sanctions(case["id"], ("PROPOSED", "ACCEPTED"), "CASE_DISMISSED")
    case["dismiss_reason"] = body["dismiss_reason"]
    case["adjudication_status"] = "DISMISSED"
    touch(case)
    return ok(case_json(case))


# -------------------------------------------------------- informal pathway

@bp.route("/integrity/cases/<row_id>/informal-resolution", methods=["POST"])
def informal_resolution(row_id):
    actor = auth([ROLE_FACULTY_REPORTER])
    known = S.cases.get(row_id)
    if known is not None:
        report = calc.report_of_case(known)
        require_owner(actor, report["reporter_id"] if report else None)
    body = validate(INFORMAL_RESOLUTION_FIELDS)
    case = case_or_404(row_id)
    if case["adjudication_status"] != "NOTIFIED":
        fail("ERR_CASE_STATE_INVALID",
             "An informal resolution may only be proposed on a case in NOTIFIED.")
    if case["pathway"] != "INFORMAL":
        fail("ERR_CASE_PATHWAY_NOT_SET",
             "The case is not on the INFORMAL pathway.")
    if body["expected_case_version"] != case["version"]:
        fail("ERR_STALE_CASE_VERSION",
             "expected_case_version does not match the case's current version.")
    if case["recommended_ladder_rank"] > calc.INFORMAL_MAX_RANK:
        fail("ERR_INFORMAL_PATHWAY_NOT_PERMITTED",
             "The informal pathway is barred once the recommended ladder rank exceeds 3.")
    code = body["grade_component_code"]
    offering = calc.offering_of_case(case)
    declared = [component["code"] for component in offering["grade_components"]] \
        if offering else []
    if code is not None and code not in declared:
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
    rank = body["proposed_ladder_rank"]
    band_min, band_max = calc.informal_band(case)
    if rank > band_max:
        fail("ERR_SANCTION_ABOVE_LADDER_BAND",
             "proposed_ladder_rank sits above the permitted informal band.")
    if kind != calc.sanction_kind_for_rank(rank):
        fail("ERR_SANCTION_KIND_RANK_MISMATCH",
             "kind is not the kind that proposed_ladder_rank maps to.")
    superseded_id = cascades.supersede_proposed(case["id"])
    sanction = new_row(
        case_id=case["id"],
        replaces_sanction_id=superseded_id,
        kind=kind,
        ladder_rank=rank,
        grade_component_code=code,
        effective_from=body["effective_from"],
        status="PROPOSED",
        origin="INFORMAL_PROPOSAL",
        baseline_course_grade_pct=D0,
        adjusted_course_grade_pct=D0,
        grade_penalty_delta_pct=D0,
        imposed_at=None,
        completed_at=None,
        vacated_reason=None,
    )
    S.sanctions[sanction["id"]] = sanction
    case["adjudication_status"] = "INFORMAL_PROPOSED"
    touch(case)
    return created(sanction_json(sanction))


@bp.route("/integrity/cases/<row_id>/informal-response", methods=["POST"])
def informal_response(row_id):
    actor = auth([ROLE_STUDENT])
    known = S.cases.get(row_id)
    if known is not None:
        require_owner(actor, known["student_id"])
    body = validate(INFORMAL_RESPONSE_FIELDS)
    case = case_or_404(row_id)
    if case["adjudication_status"] != "INFORMAL_PROPOSED":
        fail("ERR_CASE_STATE_INVALID",
             "There is no informal proposal outstanding on this case.")
    if body["response"] == "ACCEPT":
        for sanction in calc.sanctions_of_case(case["id"]):
            if sanction["status"] == "PROPOSED":
                sanction["status"] = "ACCEPTED"
                touch(sanction)
        case["responsibility_finding"] = "RESPONSIBLE"
        case["finding_basis"] = "ADMISSION"
        case["decided_at"] = S.clock
        case["adjudication_status"] = "INFORMAL_ACCEPTED"
    else:
        for sanction in calc.sanctions_of_case(case["id"]):
            if sanction["status"] == "PROPOSED":
                sanction["status"] = "DECLINED"
                touch(sanction)
        case["pathway"] = "FORMAL"
        # The informal cap no longer applies, so the formal algorithm runs afresh.
        calc.apply_assessment(case)
        case["adjudication_status"] = "FORMAL_REFERRED"
    touch(case)
    return ok(case_json(case))


# ------------------------------------------------- transcript notation (3.10)

@bp.route("/integrity/cases/<row_id>/notation/post", methods=["POST"])
def post_notation(row_id):
    auth([ROLE_REGISTRAR_OFFICER])
    # PRD 2.6: the parent identifier is resolved before anything nested.
    case = case_or_404(row_id)
    if case["notation_status"] != "PENDING_POSTING":
        fail("ERR_NOTATION_STATE_INVALID",
             "Only a case whose notation is PENDING_POSTING may be posted.")
    case["notation_status"] = "POSTED"
    # Null while the governing sanction is not yet COMPLETED.
    case["expungement_eligible_at"] = calc.expungement_eligible_at(case)
    touch(case)
    return ok(case_json(case))


@bp.route("/integrity/cases/<row_id>/notation/expungement-request", methods=["POST"])
def request_expungement(row_id):
    actor = auth([ROLE_STUDENT])
    known = S.cases.get(row_id)
    if known is not None:
        require_owner(actor, known["student_id"])
    validate(EXPUNGEMENT_REQUEST_FIELDS)
    case = case_or_404(row_id)
    if case["notation_status"] not in ("POSTED", "EXPUNGEMENT_DENIED"):
        fail("ERR_NOTATION_STATE_INVALID",
             "Expungement may only be requested on a POSTED or EXPUNGEMENT_DENIED notation.")
    governing = calc.governing_sanction(case["id"])
    # The too-early check runs first, so an incomplete rank-8 sanction reports it.
    if governing is None or governing["status"] != "COMPLETED":
        fail("ERR_EXPUNGEMENT_TOO_EARLY",
             "The governing sanction has not been completed yet.")
    if calc.ELIGIBILITY_DAYS.get(governing["ladder_rank"]) is None:
        fail("ERR_NOTATION_NOT_EXPUNGEABLE",
             "A notation arising from an expulsion recommendation is permanent.")
    eligible_at = calc.expungement_eligible_at(case)
    case["expungement_eligible_at"] = eligible_at
    if eligible_at is None or S.clock < eligible_at:
        fail("ERR_EXPUNGEMENT_TOO_EARLY", "The expungement waiting period has not elapsed.")
    case["notation_status"] = "EXPUNGEMENT_REQUESTED"
    case["notation_request_statement"] = None
    touch(case)
    return ok(case_json(case))


@bp.route("/integrity/cases/<row_id>/notation/expungement-decision", methods=["POST"])
def decide_expungement(row_id):
    auth([ROLE_REGISTRAR_OFFICER])
    body = validate(EXPUNGEMENT_DECISION_FIELDS)
    if body["decision"] == "DENY" and body["decision_reason"] is None:
        fail("ERR_INVALID_REQUEST", "decision_reason is required on a denial.")
    case = case_or_404(row_id)
    if case["notation_status"] != "EXPUNGEMENT_REQUESTED":
        fail("ERR_NOTATION_STATE_INVALID",
             "Only a notation in EXPUNGEMENT_REQUESTED may be decided.")
    if body["decision"] == "GRANT":
        case["notation_status"] = "EXPUNGED"
    else:
        case["notation_status"] = "EXPUNGEMENT_DENIED"
        case["notation_decision_reason"] = body["decision_reason"]
    touch(case)
    return ok(case_json(case))


# ---------------------------------------------------------------- notices

@bp.route("/integrity/cases/<row_id>/notifications", methods=["POST"])
def send_notice(row_id):
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(NOTICE_FIELDS)
    case = case_or_404(row_id)
    if case["adjudication_status"] != "INTAKE_REVIEW":
        fail("ERR_CASE_STATE_INVALID",
             "An allegation notice may only be sent while the case is in INTAKE_REVIEW.")
    if calc.allegation_notice(case["id"]) is not None:
        fail("ERR_CASE_STATE_INVALID", "This case already carries an allegation notice.")
    days = body["response_window_days"]
    if days is None:
        days = calc.RESPONSE_WINDOW_DEFAULT_DAYS
    if days < calc.RESPONSE_WINDOW_MIN_DAYS or days > calc.RESPONSE_WINDOW_MAX_DAYS:
        fail("ERR_RESPONSE_WINDOW_OUT_OF_RANGE",
             "response_window_days must run from 5 to 30 days inclusive.")
    notice = cascades.create_notice(case["id"], body["kind"], days)
    case["notified_at"] = notice["sent_at"]
    case["adjudication_status"] = "NOTIFIED"
    touch(case)
    return created(notification_json(notice))


@bp.route("/integrity/cases/<row_id>/notifications", methods=["GET"])
def list_case_notices(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_STUDENT, ROLE_PANEL_CHAIR, ROLE_APPEALS_DEAN])
    # PRD 2.6: the parent identifier is resolved before anything nested.
    case = case_or_404(row_id)
    limit, offset = pagination()
    rows = calc.notifications_of_case(case["id"])
    return ok_list(rows, notification_json, limit, offset)


@bp.route("/integrity/notifications", methods=["GET"])
def list_notices():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_APPEALS_DEAN])
    limit, offset = pagination()
    fk_filter("case_id", case_or_404)
    rows = filter_rows(S.notifications, {"case_id": "case_id", "kind": "kind"})
    raw = request.args.get("acknowledged")
    if raw is not None:
        wanted = raw.strip().lower()
        if wanted in ("true", "1"):
            rows = [row for row in rows if row["acknowledged_at"] is not None]
        elif wanted in ("false", "0"):
            rows = [row for row in rows if row["acknowledged_at"] is None]
        else:
            rows = []
    return ok_list(rows, notification_json, limit, offset)


@bp.route("/integrity/notifications/<row_id>", methods=["GET"])
def read_notice(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_STUDENT, ROLE_PANEL_CHAIR, ROLE_APPEALS_DEAN])
    return ok(notification_json(notification_or_404(row_id)))


@bp.route("/integrity/notifications/<row_id>/acknowledge", methods=["POST"])
def acknowledge_notice(row_id):
    actor = auth([ROLE_STUDENT])
    known = S.notifications.get(row_id)
    if known is not None:
        case = S.cases.get(known["case_id"])
        require_owner(actor, case["student_id"] if case else None)
    notice = notification_or_404(row_id)
    if notice["acknowledged_at"] is not None:
        fail("ERR_NOTIFICATION_ALREADY_ACKNOWLEDGED",
             "This notification has already been acknowledged.")
    notice["acknowledged_at"] = S.clock
    touch(notice)
    return ok(notification_json(notice))
