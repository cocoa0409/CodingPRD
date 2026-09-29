"""ESY eligibility determinations (PRD section 3.2)."""
from flask import Blueprint, g

from auth import (CASE_MANAGER, COMPLIANCE_OFFICER, PARENT_GUARDIAN,
                  PROGRAM_COORDINATOR, SPED_DIRECTOR, endpoint,
                  guard_owned_record)
from calcs import MIN_PROBE_DOMAINS, regression_recoupment_analysis
from envelope import created, ok
from errors import ApiError
from resolve import body_ref, path_ref
from serialize import public
from store import db, new_record, touch
from validate import bad, body, opt_str, req_enum, req_school_year, req_str

bp = Blueprint("determinations", __name__)

ANALYSIS_VARIANTS = ("PROBE_BASED", "TEAM_JUDGMENT")
SKILL_DOMAINS = ("READING_FLUENCY", "MATH_COMPUTATION", "EXPRESSIVE_LANGUAGE",
                 "SELF_REGULATION", "ADAPTIVE_SKILLS")
PARENT_RESPONSES = ("AGREE", "OBJECT", "WITHDRAW")
READ_ROLES = (CASE_MANAGER, PROGRAM_COORDINATOR, SPED_DIRECTOR,
              COMPLIANCE_OFFICER, PARENT_GUARDIAN)


def _number(probe, key, low, high):
    if key not in probe or probe[key] is None:
        raise bad("skill_probes[].%s is required." % key)
    value = probe[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("skill_probes[].%s must be a number." % key)
    if value < low or value > high:
        raise bad("skill_probes[].%s must be between %s and %s." % (key, low, high))
    return value


def _integer(probe, key, low, high):
    if key not in probe or probe[key] is None:
        raise bad("skill_probes[].%s is required." % key)
    value = probe[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("skill_probes[].%s must be an integer." % key)
    if value < low or value > high:
        raise bad("skill_probes[].%s must be between %d and %d." % (key, low, high))
    return value


def validate_probes(raw):
    """PRD 3.2: 1..8 probes, array order pinned, pre_break_mastery_pct > 0."""
    if not isinstance(raw, list):
        raise bad("skill_probes must be an array.")
    if len(raw) < 1 or len(raw) > 8:
        raise bad("skill_probes must hold between 1 and 8 entries.")
    probes = []
    for probe in raw:
        if not isinstance(probe, dict):
            raise bad("Each skill_probes entry must be an object.")
        domain = req_enum(probe, "skill_domain", SKILL_DOMAINS)
        pre = _number(probe, "pre_break_mastery_pct", 0, 100)
        post = _number(probe, "post_break_mastery_pct", 0, 100)
        days = _integer(probe, "recoupment_days_observed", 0, 120)
        trials = _integer(probe, "trials_count", 0, 50)
        if pre <= 0:
            raise bad("skill_probes[].pre_break_mastery_pct must be greater than 0.")
        probes.append({
            "skill_domain": domain,
            "pre_break_mastery_pct": pre,
            "post_break_mastery_pct": post,
            "recoupment_days_observed": days,
            "trials_count": trials,
        })
    return probes


@bp.post("/esy/eligibility-determinations")
@endpoint((CASE_MANAGER,))
def create_determination():
    data = body()
    student = body_ref(data, "student_id", "student")
    student_id = req_str(data, "student_id", 1, None)
    school_year = req_school_year(data, "school_year")
    variant = req_enum(data, "analysis_variant", ANALYSIS_VARIANTS)
    if "skill_probes" not in data or data["skill_probes"] is None:
        raise bad("skill_probes is required.")
    probes = validate_probes(data["skill_probes"])
    if student is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND")

    determination = new_record("EligibilityDetermination", {
        "student_id": student_id,
        "school_year": school_year,
        "analysis_variant": variant,
        "skill_probes": probes,
        "status": "DRAFT",
        "max_regression_pct": 0,
        "max_recoupment_days": 0,
        "criteria_met_count": 0,
        "data_sufficiency": "SUFFICIENT",
        "eligibility_recommendation": "PENDING_DATA",
        "objection_round_count": 0,
        "analyzed_by_user_id": None,
        "finalized_by_user_id": None,
        "parent_comment": None,
    })
    db.determinations[determination["id"]] = determination
    return created(public(determination))


@bp.get("/esy/eligibility-determinations/<determination_id>")
@endpoint(READ_ROLES)
def get_determination(determination_id):
    determination = path_ref("determination", determination_id)
    guard_owned_record(determination)
    return ok(public(determination))


@bp.post("/esy/eligibility-determinations/<determination_id>/analyze")
@endpoint((CASE_MANAGER,))
def analyze_determination(determination_id):
    determination = path_ref("determination", determination_id)
    data = body()
    replacement = None
    if "skill_probes" in data and data["skill_probes"] is not None:
        replacement = validate_probes(data["skill_probes"])

    if determination["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    probes = replacement if replacement is not None else determination["skill_probes"]
    if len(probes) < MIN_PROBE_DOMAINS:
        raise ApiError("ERR_INSUFFICIENT_PROBE_DATA")

    if replacement is not None:
        determination["skill_probes"] = replacement

    outcome = regression_recoupment_analysis(determination["analysis_variant"], probes)
    determination.update(outcome)
    determination["analyzed_by_user_id"] = g.user_id
    determination["status"] = "PARENT_REVIEW"
    touch(determination)
    return ok(public(determination))


@bp.post("/esy/eligibility-determinations/<determination_id>/parent-response")
@endpoint((PARENT_GUARDIAN,))
def determination_parent_response(determination_id):
    determination = path_ref("determination", determination_id)
    guard_owned_record(determination)
    data = body()
    response = req_enum(data, "response", PARENT_RESPONSES)
    comment = opt_str(data, "parent_comment", 0, 500)

    if determination["status"] != "PARENT_REVIEW":
        raise ApiError("ERR_INVALID_STATE")

    determination["parent_comment"] = comment
    if response == "AGREE":
        determination["status"] = "PARENT_AGREED"
    elif response == "WITHDRAW":
        determination["status"] = "WITHDRAWN"
    else:
        determination["status"] = "DRAFT"
        determination["objection_round_count"] += 1
        determination["analyzed_by_user_id"] = None
    touch(determination)
    return ok(public(determination))


@bp.post("/esy/eligibility-determinations/<determination_id>/finalize")
@endpoint((SPED_DIRECTOR,))
def finalize_determination(determination_id):
    determination = path_ref("determination", determination_id)
    if determination["status"] != "PARENT_AGREED":
        raise ApiError("ERR_INVALID_STATE")
    if determination["analyzed_by_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    determination["finalized_by_user_id"] = g.user_id
    determination["status"] = "FINALIZED"
    student = db.students.get(determination["student_id"])
    if student is not None:
        student["esy_eligibility_status"] = determination["eligibility_recommendation"]
        touch(student)
    touch(determination)
    return ok(public(determination))
