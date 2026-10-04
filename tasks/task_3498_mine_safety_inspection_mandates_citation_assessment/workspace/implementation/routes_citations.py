"""Citation issuance, abatement axis, and penalty assessment endpoints (PRD 3.4)."""
from datetime import timedelta

from flask import Blueprint, g, request

import clock
import services_ido
import services_penalty
import store
from constants import (
    ABATEMENT_BASE_DAYS,
    AUTO_IDO_HAZARD_DESCRIPTION,
    BUSINESS_READ_ROLES,
    CITATION_KINDS,
    CONTEST_WINDOW_DAYS,
    GRAVITY_LIKELIHOODS,
    GRAVITY_SEVERITIES,
    NEGLIGENCE_LEVELS,
    ROLE_INSPECTOR,
    ROLE_MSHA_ADMIN,
    ROLE_OPERATOR_REP,
)
from envelope import list_response, ok_object
from errors import (
    ApiError,
    ERR_ABATEMENT_EXTENSION_EXHAUSTED,
    ERR_ABATEMENT_WINDOW_PASSED,
    ERR_FINALIZE_WINDOW_ACTIVE,
    ERR_INSPECTOR_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_OPERATOR_MISMATCH,
    ERR_SOD_VERIFY_SELF,
)
from serialize import citation as ser_citation, penalty_assessment as ser_assessment
from validate import ensure_empty_body, get_or_404, parse_body, require_roles

bp = Blueprint("citations", __name__, url_prefix="/msha")


def _owning_mine(citation):
    return store.mines.get(citation["mine_id"])


def _assert_operator_owns(citation):
    mine = _owning_mine(citation)
    if mine is None or g.uid != mine["operator_id"]:
        raise ApiError(
            ERR_OPERATOR_MISMATCH,
            "X-User-ID must be the operator of the cited mine",
        )


@bp.route("/citations", methods=["POST"])
def create_citation():
    require_roles(ROLE_INSPECTOR)
    body = parse_body({
        "inspection_id": ("str", True),
        "mine_id": ("str", True),
        "standard_code": ("str", True),
        "kind": ("enum", True, CITATION_KINDS),
        "negligence": ("enum", True, NEGLIGENCE_LEVELS),
        "gravity_likelihood": ("enum", True, GRAVITY_LIKELIHOODS),
        "gravity_severity": ("enum", True, GRAVITY_SEVERITIES),
        "persons_affected": ("int", True, 1),
        "significant_and_substantial": ("bool", True),
        "repeat_violation": ("bool", True),
    })
    inspection = get_or_404(store.inspections, body["inspection_id"], "inspection")
    mine = get_or_404(store.mines, body["mine_id"], "mine")
    # Cross-field request coherence (400 class), evaluated after existence and
    # before ownership/state per the section 2.5 cascade.
    if inspection["mine_id"] != mine["id"]:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "mine_id must be the mine of the named inspection",
        )
    if g.uid != inspection["inspector_id"]:
        raise ApiError(
            ERR_INSPECTOR_MISMATCH,
            "only the assigned inspector may issue citations during an inspection",
        )
    if inspection["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, "citations may be issued only during an IN_PROGRESS inspection")
    issued_at = clock.now()
    base_days = ABATEMENT_BASE_DAYS[body["gravity_severity"]]
    draft = {
        "inspection_id": inspection["id"],
        "mine_id": mine["id"],
        "issued_by_inspector_id": g.uid,
        "standard_code": body["standard_code"],
        "kind": body["kind"],
        "negligence": body["negligence"],
        "gravity_likelihood": body["gravity_likelihood"],
        "gravity_severity": body["gravity_severity"],
        "persons_affected": body["persons_affected"],
        "significant_and_substantial": body["significant_and_substantial"],
        "repeat_violation": body["repeat_violation"],
        "issued_at": issued_at,
    }
    points_total = services_penalty.compute_points_total(draft)
    draft.update({
        "abatement_base_days": base_days,
        "abatement_deadline": issued_at + timedelta(days=base_days),
        "abatement_extended": False,
        "abated_at": None,
        "verified_at": None,
        "verified_by_inspector_id": None,
        "abatement_status": "OPEN",
        "contest_status": "UNCONTESTED",
        "system_issued": False,
    })
    citation = store.new_entity(store.citations, draft)
    services_penalty.create_assessment(citation, points_total)
    # POV_FINAL escalation: a newly issued S&S citation auto-creates an IDO and
    # fires the halt-and-suspend cascade (PRD 3.5).
    if mine["pov_status"] == "POV_FINAL" and citation["significant_and_substantial"]:
        services_ido.create_ido(mine, AUTO_IDO_HAZARD_DESCRIPTION, inspection["id"], g.uid)
    return ok_object(ser_citation(citation), 201)


@bp.route("/citations/<citationId>", methods=["GET"])
def get_citation(citationId):
    require_roles(*BUSINESS_READ_ROLES)
    return ok_object(ser_citation(get_or_404(store.citations, citationId, "citation")))


@bp.route("/citations", methods=["GET"])
def list_citations():
    require_roles(*BUSINESS_READ_ROLES)
    items = list(store.citations.values())
    for param in (
        "mine_id",
        "inspection_id",
        "issued_by_inspector_id",
        "verified_by_inspector_id",
        "abatement_status",
        "contest_status",
    ):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c.get(param) is not None and c[param] == value]
    ss_filter = request.args.get("significant_and_substantial")
    if ss_filter is not None:
        if ss_filter == "true":
            flag = True
        elif ss_filter == "false":
            flag = False
        else:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "significant_and_substantial filter must be 'true' or 'false'",
            )
        items = [c for c in items if c["significant_and_substantial"] == flag]
    return list_response(items, ser_citation)


@bp.route("/citations/<citationId>/abate", methods=["POST"])
def abate_citation(citationId):
    require_roles(ROLE_OPERATOR_REP)
    parse_body({"abatement_note": ("str", True)})
    citation = get_or_404(store.citations, citationId, "citation")
    _assert_operator_owns(citation)
    if citation["abatement_status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, "abatement requires abatement_status OPEN")
    citation["abatement_status"] = "ABATED"
    citation["abated_at"] = clock.now()
    store.touch(citation)
    return ok_object(ser_citation(citation))


@bp.route("/citations/<citationId>/verify-abatement", methods=["POST"])
def verify_citation_abatement(citationId):
    require_roles(ROLE_INSPECTOR)
    parse_body({"verification_note": ("str", True)})
    citation = get_or_404(store.citations, citationId, "citation")
    # Segregation of duties: verifier must differ from the issuer (tier 6
    # precedes the tier 7 state check).
    if g.uid == citation["issued_by_inspector_id"]:
        raise ApiError(
            ERR_SOD_VERIFY_SELF,
            "the issuing inspector cannot verify abatement of this citation",
        )
    if citation["abatement_status"] != "ABATED":
        raise ApiError(ERR_INVALID_STATE, "verification requires abatement_status ABATED")
    citation["abatement_status"] = "VERIFIED"
    citation["verified_at"] = clock.now()
    citation["verified_by_inspector_id"] = g.uid
    store.touch(citation)
    return ok_object(ser_citation(citation))


@bp.route("/citations/<citationId>/extend-abatement", methods=["POST"])
def extend_citation_abatement(citationId):
    require_roles(ROLE_OPERATOR_REP)
    parse_body({"justification": ("str", True)})
    citation = get_or_404(store.citations, citationId, "citation")
    _assert_operator_owns(citation)
    # Tier 10 single-extension rule outranks the tier 11 window rule.
    if citation["abatement_extended"] or citation["abatement_status"] != "OPEN":
        raise ApiError(
            ERR_ABATEMENT_EXTENSION_EXHAUSTED,
            "the single permitted extension is exhausted or the citation is no longer OPEN",
        )
    if clock.now() >= citation["abatement_deadline"]:
        raise ApiError(
            ERR_ABATEMENT_WINDOW_PASSED,
            "the extension window closes at the current abatement_deadline",
        )
    extra_days = (citation["abatement_base_days"] + 1) // 2
    citation["abatement_deadline"] = citation["abatement_deadline"] + timedelta(days=extra_days)
    citation["abatement_extended"] = True
    store.touch(citation)
    return ok_object(ser_citation(citation))


@bp.route("/citations/<citationId>/penalty-assessments", methods=["GET"])
def list_citation_assessments(citationId):
    require_roles(*BUSINESS_READ_ROLES)
    get_or_404(store.citations, citationId, "citation")
    items = [a for a in store.assessments.values() if a["citation_id"] == citationId]
    return list_response(items, ser_assessment)


@bp.route("/penalty-assessments/<assessmentId>/finalize", methods=["POST"])
def finalize_assessment(assessmentId):
    require_roles(ROLE_MSHA_ADMIN)
    ensure_empty_body()
    assessment = get_or_404(store.assessments, assessmentId, "penalty assessment")
    citation = store.citations.get(assessment["citation_id"])
    # Tier 7 state preconditions precede the tier 11 window check.
    if assessment["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, "only a PROPOSED assessment can be finalized")
    if citation["contest_status"] != "UNCONTESTED":
        raise ApiError(ERR_INVALID_STATE, "a citation under contest blocks finalization")
    deadline = citation["issued_at"] + timedelta(days=CONTEST_WINDOW_DAYS)
    if clock.now() <= deadline:
        raise ApiError(
            ERR_FINALIZE_WINDOW_ACTIVE,
            "the contest window must have fully lapsed before finalization",
        )
    services_penalty.apply_final_variant(assessment, citation)
    store.touch(assessment)
    return ok_object(ser_assessment(assessment))
