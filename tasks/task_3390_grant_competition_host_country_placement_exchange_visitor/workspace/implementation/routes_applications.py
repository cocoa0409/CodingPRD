"""Application endpoints: create, read, list, OCC-guarded patch, lifecycle
transitions (SUBMIT/WITHDRAW/DECLINE/DECIDE), and review scores.

Validation ordering follows PRD 2.7: auth(1) -> role/family(2) -> path
existence(3) -> OCC(4) -> ownership(5) -> state(6) -> temporal(8) ->
business constraints(9) -> referential phase(10) -> fiscal gate(11).
"""

from decimal import Decimal

from flask import Blueprint, request

import domain
import envelope
import serialize
from auth import auth, require_roles, check_owner
from constants import (
    ROLE_APPLICANT,
    ROLE_CAMPUS_REVIEWER,
    ROLE_NATIONAL_REVIEWER,
    ROLE_HOST_COMMISSION,
    READ_ROLES,
    CAMPUS_QUORUM,
    NATIONAL_QUORUM,
    RECOMMEND_SCORE_THRESHOLD,
    MIN_AVG_FEASIBILITY,
    LANGUAGE_GATE_PROFICIENT,
    LANGUAGE_GATE_BASIC,
    ACTIVE_APPLICATION_STATES,
)
from errors import ApiError
from store import STORE, stamp_new, bump, now, now_iso, new_id, next_seq
from timeutil import parse_iso
from validate import (
    body,
    check_unknown,
    req,
    as_str,
    as_text,
    as_int,
    as_bool,
    as_dt,
    as_score,
    as_version,
    pagination,
    page_slice,
    V,
)

bp = Blueprint("applications", __name__)

APPLICANT_ACTIONS = ("SUBMIT", "WITHDRAW", "DECLINE")
REVIEWER_ROLES = (ROLE_CAMPUS_REVIEWER, ROLE_NATIONAL_REVIEWER, ROLE_HOST_COMMISSION)
TRANSITION_ROLES = (ROLE_APPLICANT,) + REVIEWER_ROLES
SCORE_READ_ROLES = (
    "PlatformAdmin",
    "ProgramOfficer",
    "HostCommission",
    "NationalReviewer",
    "CampusReviewer",
)

# DECIDE stage binding and per-stage outcome vocabularies (PRD 3.3).
STAGE_BY_ROLE = {
    ROLE_CAMPUS_REVIEWER: "CAMPUS_REVIEW",
    ROLE_NATIONAL_REVIEWER: "NATIONAL_SCREENING",
    ROLE_HOST_COMMISSION: "HOST_REVIEW",
}
OUTCOME_VOCAB = {
    "CAMPUS_REVIEW": ("ENDORSE", "REJECT"),
    "NATIONAL_SCREENING": ("RECOMMEND", "REJECT"),
    "HOST_REVIEW": ("SELECT", "ALTERNATE", "REJECT"),
}


# ---------------------------------------------------------------------------
# Create / read / list / patch
# ---------------------------------------------------------------------------

@bp.post("/exchange/applications")
def create_application():
    user, role = auth()
    require_roles(role, [ROLE_APPLICANT])
    payload = body()
    # Priority 5 ownership is evaluated as soon as the owning id is visible.
    if "applicant_id" in payload and payload["applicant_id"] is not None:
        if payload["applicant_id"] != user:
            raise ApiError(
                "ERR_NOT_RESOURCE_OWNER", 403, "applicant_id must equal the caller's X-User-ID"
            )
    check_unknown(
        payload,
        {
            "applicant_id",
            "cycle_id",
            "country_program_id",
            "project_title",
            "project_summary",
            "proposed_duration_months",
            "dependents_count",
            "is_follow_on",
        },
    )
    applicant_id = as_str(req(payload, "applicant_id"), "applicant_id")
    cycle_id = as_str(req(payload, "cycle_id"), "cycle_id")
    program_id = as_str(req(payload, "country_program_id"), "country_program_id")
    title = as_str(req(payload, "project_title"), "project_title")
    summary = as_text(req(payload, "project_summary"), "project_summary")
    duration = as_int(req(payload, "proposed_duration_months"), "proposed_duration_months")
    dependents = as_int(payload.get("dependents_count", 0), "dependents_count")
    if dependents < 0:
        raise V("Field dependents_count must be >= 0")
    follow_on = payload.get("is_follow_on", False)
    as_bool(follow_on, "is_follow_on")

    applicant = STORE.applicants.get(applicant_id)
    cycle = STORE.cycles.get(cycle_id)
    program = STORE.programs.get(program_id)
    if applicant is None or cycle is None or program is None:
        raise V("Malformed cross-reference: applicant, cycle, and country program must exist")
    if program["cycle_id"] != cycle_id:
        raise V("country_program_id does not belong to the addressed cycle")
    if duration < program["min_duration_months"] or duration > program["max_duration_months"]:
        raise ApiError(
            "ERR_DURATION_OUT_OF_RANGE",
            422,
            "proposed_duration_months is outside the country program bounds",
        )
    if follow_on and domain.latest_follow_on_eligible(applicant_id) != "ELIGIBLE":
        raise ApiError(
            "ERR_FOLLOW_ON_INELIGIBLE",
            409,
            "No AlumniProfile or latest profile is not follow-on eligible",
        )
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409, "Applications may only be created while the cycle is OPEN")

    application = {
        "applicant_id": applicant_id,
        "cycle_id": cycle_id,
        "country_program_id": program_id,
        "project_title": title,
        "project_summary": summary,
        "proposed_duration_months": duration,
        "dependents_count": dependents,
        "is_follow_on": follow_on,
        "status": "DRAFT",
        "submitted_at": None,
        "recommend_seq": None,
        "national_weighted_score": None,
        "placement_rounds_used": 0,
    }
    stamp_new(application)
    STORE.applications[application["id"]] = application
    return envelope.ok(serialize.application_out(application), 201)


@bp.get("/exchange/applications/<aid>")
def get_application(aid):
    user, role = auth()
    require_roles(role, READ_ROLES)
    application = STORE.applications.get(aid)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "No application with the given id")
    check_owner(role, user, application["applicant_id"])
    return envelope.ok(serialize.application_out(application))


@bp.get("/exchange/applications")
def list_applications():
    user, role = auth()
    require_roles(role, READ_ROLES)
    limit, offset = pagination()
    items = list(STORE.applications.values())
    # An Applicant-role listing is confined to the caller's own records.
    if role == ROLE_APPLICANT:
        items = [a for a in items if a["applicant_id"] == user]
    for field in ("cycle_id", "country_program_id", "applicant_id", "status"):
        wanted = request.args.get(field)
        if wanted is not None:
            items = [a for a in items if a.get(field) == wanted]
    page, total = page_slice(items, limit, offset)
    return envelope.ok_list([serialize.application_out(a) for a in page], total, limit, offset)


@bp.patch("/exchange/applications/<aid>")
def patch_application(aid):
    user, role = auth()
    require_roles(role, [ROLE_APPLICANT])
    application = STORE.applications.get(aid)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "No application with the given id")
    payload = body()
    # Priority 4: optimistic concurrency on Application.version.
    if "expected_application_version" not in payload or payload["expected_application_version"] is None:
        raise V("Missing required field: expected_application_version")
    expected = as_version(payload["expected_application_version"])
    if expected != application["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_application_version does not match the application's current version",
        )
    # Priority 5: ownership.
    check_owner(role, user, application["applicant_id"])
    # Priority 6: only a DRAFT application may be edited.
    if application["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DRAFT application can be updated")
    # Priority 9: structural validation.
    check_unknown(
        payload,
        {
            "project_title",
            "project_summary",
            "proposed_duration_months",
            "dependents_count",
            "expected_application_version",
        },
    )
    if "project_title" in payload:
        application["project_title"] = as_str(payload["project_title"], "project_title")
    if "project_summary" in payload:
        application["project_summary"] = as_text(payload["project_summary"], "project_summary")
    if "proposed_duration_months" in payload:
        application["proposed_duration_months"] = as_int(
            payload["proposed_duration_months"], "proposed_duration_months"
        )
    if "dependents_count" in payload:
        deps = as_int(payload["dependents_count"], "dependents_count")
        if deps < 0:
            raise V("Field dependents_count must be >= 0")
        application["dependents_count"] = deps
    bump(application)
    return envelope.ok(serialize.application_out(application))


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------

@bp.post("/exchange/applications/<aid>/transition")
def application_transition(aid):
    user, role = auth()
    require_roles(role, TRANSITION_ROLES)
    payload = body()
    action = payload.get("action")
    # Priority 2: action-family role binding (only evaluable for known actions).
    if isinstance(action, str):
        if action in APPLICANT_ACTIONS:
            if role != ROLE_APPLICANT:
                raise ApiError("ERR_UNAUTHORIZED", 403, "Action %s is an Applicant action" % action)
        elif action == "DECIDE":
            if role not in REVIEWER_ROLES:
                raise ApiError("ERR_UNAUTHORIZED", 403, "DECIDE belongs to the reviewer family")

    # Priority 3: path existence precedes every other domain check (PRD 2.9).
    application = STORE.applications.get(aid)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "No application with the given id")
    check_owner(role, user, application["applicant_id"])

    if action is None:
        raise V("Missing required field: action")
    if not isinstance(action, str):
        raise V("Field action must be a string")
    check_unknown(payload, {"action", "outcome", "rationale"})
    if action == "SUBMIT":
        return _submit(application)
    if action == "WITHDRAW":
        return _withdraw(application)
    if action == "DECLINE":
        return _decline(application)
    if action == "DECIDE":
        return _decide(application, role, payload)
    # Unknown action: a validation error, not a state error (PRD 2.7 p6).
    raise V("Unknown action for application transition: %r" % action)


def _submit(application):
    if application["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DRAFT application can be submitted")
    cycle = STORE.cycles[application["cycle_id"]]
    program = STORE.programs[application["country_program_id"]]
    applicant = STORE.applicants[application["applicant_id"]]
    # Priority 8: inclusive deadline.
    if now() > parse_iso(cycle["application_deadline"]):
        raise ApiError("ERR_DEADLINE_PASSED", 409, "The cycle application deadline has passed")
    # Priority 9: duration bounds.
    duration = application["proposed_duration_months"]
    if duration < program["min_duration_months"] or duration > program["max_duration_months"]:
        raise ApiError(
            "ERR_DURATION_OUT_OF_RANGE", 422, "proposed_duration_months is outside the program bounds"
        )
    # Priority 9: one submitted-or-later non-terminal application per applicant per cycle.
    for other in STORE.applications.values():
        if (
            other["id"] != application["id"]
            and other["applicant_id"] == application["applicant_id"]
            and other["cycle_id"] == application["cycle_id"]
            and other["status"] in ACTIVE_APPLICATION_STATES
        ):
            raise ApiError(
                "ERR_DUPLICATE_APPLICATION",
                409,
                "Applicant already holds a submitted-or-later application in this cycle",
            )
    # Priority 9: follow-on eligibility re-verified at submission.
    if application["is_follow_on"]:
        if domain.latest_follow_on_eligible(application["applicant_id"]) != "ELIGIBLE":
            raise ApiError(
                "ERR_FOLLOW_ON_INELIGIBLE",
                409,
                "Latest alumni profile is not follow-on eligible",
            )
    # Priority 10: cycle must be OPEN.
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409, "Submission requires the cycle to be OPEN")
    # Fork on applicant type.
    application["status"] = (
        "CAMPUS_REVIEW" if applicant["applicant_type"] == "ENROLLED_STUDENT" else "NATIONAL_SCREENING"
    )
    application["submitted_at"] = now_iso()
    bump(application)
    return envelope.ok(serialize.application_out(application))


def _withdraw(application):
    if application["status"] not in (
        "DRAFT",
        "CAMPUS_REVIEW",
        "NATIONAL_SCREENING",
        "HOST_REVIEW",
        "ALTERNATE",
    ):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Application cannot be withdrawn from its current state"
        )
    application["status"] = "WITHDRAWN"
    bump(application)
    return envelope.ok(serialize.application_out(application))


def _decline(application):
    if application["status"] not in ("SELECTED", "PLACEMENT"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Application cannot be declined from its current state"
        )
    domain.decline_application(application)
    return envelope.ok(serialize.application_out(application))


def _require_cycle_phase(cycle, allowed):
    if cycle["status"] not in allowed:
        raise ApiError(
            "ERR_CYCLE_PHASE_FORBIDS", 409, "Cycle phase does not permit this decision"
        )


def _decide(application, role, payload):
    # Priority 6: the reviewer-stage binding is enforced with the state
    # machine -- a DECIDE from a reviewer whose stage does not match the
    # application's current state is an invalid transition, not an authz error.
    stage_status = STAGE_BY_ROLE[role]
    if application["status"] != stage_status:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Application is not in this reviewer's stage",
        )
    outcome = payload.get("outcome")
    if outcome is None:
        raise V("Missing required field: outcome")
    # Priority 9: the outcome must belong to the current stage's vocabulary.
    if outcome not in OUTCOME_VOCAB[stage_status]:
        raise ApiError(
            "ERR_INVALID_OUTCOME", 400, "Outcome is not valid for the application's current stage"
        )
    cycle = STORE.cycles[application["cycle_id"]]

    if stage_status == "CAMPUS_REVIEW":
        if outcome == "ENDORSE":
            count = sum(
                1
                for s in STORE.scores.values()
                if s["application_id"] == application["id"] and s["stage"] == "CAMPUS"
            )
            if count < CAMPUS_QUORUM:
                raise ApiError("ERR_SCORE_QUORUM_NOT_MET", 409, "Campus score quorum not met")
            _require_cycle_phase(cycle, ("OPEN", "CLOSED", "SCREENING"))
            application["status"] = "NATIONAL_SCREENING"
        else:  # REJECT
            _require_cycle_phase(cycle, ("OPEN", "CLOSED", "SCREENING"))
            application["status"] = "NOT_SELECTED"

    elif stage_status == "NATIONAL_SCREENING":
        if outcome == "RECOMMEND":
            if len(domain.national_scores(application["id"])) < NATIONAL_QUORUM:
                raise ApiError("ERR_SCORE_QUORUM_NOT_MET", 409, "National score quorum not met")
            avg_f, _, avg_l, weighted = domain.national_averages(application["id"])
            if weighted < Decimal(RECOMMEND_SCORE_THRESHOLD) or avg_f < Decimal(MIN_AVG_FEASIBILITY):
                raise ApiError(
                    "ERR_SCORE_BELOW_THRESHOLD",
                    409,
                    "Weighted score or feasibility average below the recommendation threshold",
                )
            program = STORE.programs[application["country_program_id"]]
            requirement = program["language_requirement"]
            if requirement == "PROFICIENT" and avg_l < Decimal(LANGUAGE_GATE_PROFICIENT):
                raise ApiError(
                    "ERR_LANGUAGE_CRITERION_UNMET", 409, "Country language gate not satisfied"
                )
            if requirement == "BASIC" and avg_l < Decimal(LANGUAGE_GATE_BASIC):
                raise ApiError(
                    "ERR_LANGUAGE_CRITERION_UNMET", 409, "Country language gate not satisfied"
                )
            _require_cycle_phase(cycle, ("OPEN", "CLOSED", "SCREENING"))
            application["national_weighted_score"] = float(weighted)
            application["recommend_seq"] = 1 + max(
                (
                    a["recommend_seq"]
                    for a in STORE.applications.values()
                    if a["country_program_id"] == application["country_program_id"]
                    and a["recommend_seq"] is not None
                ),
                default=0,
            )
            application["status"] = "HOST_REVIEW"
        else:  # REJECT
            _require_cycle_phase(cycle, ("OPEN", "CLOSED", "SCREENING"))
            application["status"] = "NOT_SELECTED"

    else:  # HOST_REVIEW
        if outcome == "SELECT":
            _require_cycle_phase(cycle, ("CLOSED", "SCREENING"))
            program = STORE.programs[application["country_program_id"]]
            # Priority 11: the fiscal gate fires after every other check.
            if domain.slots_remaining(program) < 1:
                raise ApiError(
                    "ERR_COUNTRY_QUOTA_EXHAUSTED", 409, "No slots remaining for this country program"
                )
            application["status"] = "SELECTED"
            bump(application)
            domain.create_provisional_grant(application)
            return envelope.ok(serialize.application_out(application))
        if outcome == "ALTERNATE":
            _require_cycle_phase(cycle, ("CLOSED", "SCREENING"))
            application["status"] = "ALTERNATE"
        else:  # REJECT
            _require_cycle_phase(cycle, ("CLOSED", "SCREENING"))
            application["status"] = "NOT_SELECTED"

    bump(application)
    return envelope.ok(serialize.application_out(application))


# ---------------------------------------------------------------------------
# Review scores
# ---------------------------------------------------------------------------

@bp.post("/exchange/applications/<aid>/scores")
def post_score(aid):
    user, role = auth()
    require_roles(role, [ROLE_CAMPUS_REVIEWER, ROLE_NATIONAL_REVIEWER])
    application = STORE.applications.get(aid)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "No application with the given id")
    # Priority 2 stage binding: CampusReviewer only during CAMPUS_REVIEW,
    # NationalReviewer only during NATIONAL_SCREENING.
    if role == ROLE_CAMPUS_REVIEWER and application["status"] != "CAMPUS_REVIEW":
        raise ApiError(
            "ERR_UNAUTHORIZED", 403, "CampusReviewer may score only during CAMPUS_REVIEW"
        )
    if role == ROLE_NATIONAL_REVIEWER and application["status"] != "NATIONAL_SCREENING":
        raise ApiError(
            "ERR_UNAUTHORIZED", 403, "NationalReviewer may score only during NATIONAL_SCREENING"
        )
    stage = "CAMPUS" if application["status"] == "CAMPUS_REVIEW" else "NATIONAL"
    payload = body()
    check_unknown(payload, {"feasibility_score", "country_fit_score", "language_score", "comment"})
    feasibility = as_score(req(payload, "feasibility_score"), "feasibility_score")
    country_fit = as_score(req(payload, "country_fit_score"), "country_fit_score")
    language = as_score(req(payload, "language_score"), "language_score")
    comment = payload.get("comment")
    if comment is not None:
        comment = as_text(comment, "comment")
    # One score per (application, stage, reviewer).
    for s in STORE.scores.values():
        if (
            s["application_id"] == aid
            and s["stage"] == stage
            and s["reviewer_id"] == user
        ):
            raise ApiError(
                "ERR_DUPLICATE_SCORE",
                409,
                "This reviewer already scored this application at this stage",
            )
    score = {
        "application_id": aid,
        "stage": stage,
        "reviewer_id": user,
        "feasibility_score": feasibility,
        "country_fit_score": country_fit,
        "language_score": language,
        "comment": comment,
    }
    # ReviewScore is exempt from the common-fields convention: id + created_at only.
    score["id"] = new_id()
    score["created_at"] = now_iso()
    score["_seq"] = next_seq()
    STORE.scores[score["id"]] = score
    # When the national quorum is reached, the weighted score is computed and stored.
    domain.maybe_store_weighted(application)
    return envelope.ok(serialize.score_out(score), 201)


@bp.get("/exchange/applications/<aid>/scores")
def list_scores(aid):
    _, role = auth()
    require_roles(role, SCORE_READ_ROLES)
    application = STORE.applications.get(aid)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "No application with the given id")
    limit, offset = pagination()
    items = [s for s in STORE.scores.values() if s["application_id"] == aid]
    page, total = page_slice(items, limit, offset)
    return envelope.ok_list([serialize.score_out(s) for s in page], total, limit, offset)
