"""Safety incidents: intake, hold, evidence, decision, appeal and the projections."""

from flask import Blueprint, request

from db import STORE, add_days, now
from calculations import (appeal_track, evidence_scores, investigation_scope_ratio,
                          proposed_decision, regulator_report_required,
                          category_tier, evidence_tier)
from errors import ApiError, ERR_INCIDENT_NOT_FOUND, ERR_INVALID_STATE, ERR_RESOURCE_NOT_FOUND
from middleware import (assert_version_matches, body, require_version, route, touch)
from response import created, read_pagination, success, success_list
from serializers import evidence as serialize_evidence
from serializers import render_mapping
from serializers import incident as serialize_incident
from serializers import regulator_report as serialize_report
from services import decision as decision_service
from services import incident as incident_service

bp = Blueprint("incidents", __name__)

_READ_ROLES = ("PlatformAdmin", "SafetyInvestigator", "SafetyOperationsLead",
               "SafetyAppealReviewer")


def get_incident(incident_id):
    incident = STORE.incidents.get(incident_id)
    if incident is None:
        raise ApiError(*ERR_INCIDENT_NOT_FOUND,
                       message="No such incident: %s" % incident_id)
    return incident


@bp.route("/safety/incidents", methods=["POST"])
@route("Rider", "Driver", "SafetyInvestigator")
def file_incident(ident):
    incident = incident_service.file_incident(body())
    return created(serialize_incident(incident))


@bp.route("/safety/incidents", methods=["GET"])
@route(*_READ_ROLES)
def list_incidents(ident):
    limit, offset = read_pagination(request.args)
    items = list(STORE.incidents.values())

    def keep(incident):
        for field in ("account_id", "referenced_trip_id", "severity", "incident_status"):
            wanted = request.args.get(field)
            if wanted is not None and incident.get(field) != wanted:
                return False
        return True

    items = [i for i in items if keep(i)]
    items.sort(key=lambda i: (i.get("created_at"), i.get("id") or ""))
    return success_list([serialize_incident(i) for i in items], limit, offset)


@bp.route("/safety/incidents/summary", methods=["GET"])
@route("PlatformAdmin", "SafetyOperationsLead", "SafetyInvestigator", "RegulatorLiaison")
def incident_summary(ident):
    """The region-level safety summary over every incident the caller can see."""
    limit, offset = read_pagination(request.args)
    region = request.args.get("home_region_code")

    incidents = list(STORE.incidents.values())
    if region is not None:
        incidents = [i for i in incidents
                     if (STORE.accounts.get(i.get("account_id")) or {}).get(
                         "home_region_code") == region]

    region_keys = sorted({
        (STORE.accounts.get(i.get("account_id")) or {}).get("home_region_code")
        for i in incidents
        if (STORE.accounts.get(i.get("account_id")) or {}).get("home_region_code")})
    newest = None
    for incident in incidents:
        created = incident.get("created_at")
        if created is not None and (newest is None or created > newest):
            newest = created

    payload = {
        "region_count": len(region_keys),
        "incident_count": len(incidents),
        "decided_count": len([i for i in incidents
                              if i.get("incident_status") in ("DECIDED", "APPEAL_UPHELD",
                                                              "APPEAL_OVERTURNED")]),
        "mandatory_reportable_count": len([i for i in incidents
                                           if regulator_report_required(i)]),
        "monetary_placeholder_count": 0,
        "newest_incident_created_at": newest,
    }
    return success(render_mapping(payload))


@bp.route("/safety/incidents/<incident_id>", methods=["GET"])
@route(*_READ_ROLES)
def get_one_incident(ident, incident_id):
    return success(serialize_incident(get_incident(incident_id)))


@bp.route("/safety/incidents/<incident_id>/severity", methods=["PATCH"])
@route("SafetyInvestigator")
def patch_severity(ident, incident_id):
    incident = get_incident(incident_id)
    if incident.get("incident_status") != "OPEN":
        raise ApiError(*ERR_INVALID_STATE,
                       message="Aggravator codes may only be revised before any interim "
                               "hold exists.")
    payload = body()
    updated = incident_service.rederive_severity(incident, payload.get("aggravator_codes"))
    return success(serialize_incident(updated))


@bp.route("/safety/incidents/<incident_id>/hold", methods=["POST"])
@route("SafetyInvestigator")
def hold(ident, incident_id):
    incident = get_incident(incident_id)
    updated = incident_service.place_hold(incident)
    return success(serialize_incident(updated))


@bp.route("/safety/incidents/<incident_id>/hold/release", methods=["POST"])
@route("SafetyInvestigator")
def hold_release(ident, incident_id):
    incident = get_incident(incident_id)
    updated = incident_service.release_hold(incident)
    return success(serialize_incident(updated))


@bp.route("/safety/incidents/<incident_id>/withdraw", methods=["POST"])
@route("SafetyOperationsLead")
def withdraw(ident, incident_id):
    incident = get_incident(incident_id)
    updated = incident_service.withdraw(incident)
    return success(serialize_incident(updated))


@bp.route("/safety/incidents/<incident_id>/evidence", methods=["POST"])
@route("SafetyInvestigator")
def gather_evidence(ident, incident_id):
    incident = get_incident(incident_id)
    evidence = incident_service.gather_evidence(incident, body())
    return created(serialize_evidence(evidence))


@bp.route("/safety/incidents/<incident_id>/evidence", methods=["GET"])
@route(*_READ_ROLES)
def list_evidence(ident, incident_id):
    get_incident(incident_id)
    limit, offset = read_pagination(request.args)
    items = [e for e in STORE.evidence.values() if e.get("incident_id") == incident_id]
    wanted = request.args.get("evidence_status")
    if wanted is not None:
        items = [e for e in items if e.get("evidence_status") == wanted]
    items.sort(key=lambda e: (e.get("recorded_at"), e.get("created_at"), e.get("id") or ""))
    return success_list([serialize_evidence(e) for e in items], limit, offset)


@bp.route("/safety/incidents/<incident_id>/evidence/accept", methods=["POST"])
@route("SafetyInvestigator")
def accept_evidence(ident, incident_id):
    incident = get_incident(incident_id)
    payload = body()
    updated = incident_service.accept_evidence(
        incident, payload.get("evidence_id"), bool(payload.get("accepted")))
    return success(serialize_incident(updated))


@bp.route("/safety/incidents/<incident_id>/evidence-score", methods=["GET"])
@route("PlatformAdmin", "SafetyInvestigator", "SafetyOperationsLead")
def evidence_score(ident, incident_id):
    get_incident(incident_id)
    scores = evidence_scores(incident_id)
    return success({
        "incident_id": incident_id,
        "evidence_score": scores["evidence_score"],
        "support_score": scores["support_score"],
        "distinct_evidence_source_count": scores["distinct_evidence_source_count"],
        "applied_evidence_cap": scores["applied_evidence_cap"],
        "confidence_ratio": scores["confidence_ratio"],
        "dispositive_promotable": scores["dispositive_promotable"],
    })


@bp.route("/safety/incidents/<incident_id>/decision-criteria", methods=["GET"])
@route("PlatformAdmin", "SafetyInvestigator", "SafetyOperationsLead")
def decision_criteria(ident, incident_id):
    incident = get_incident(incident_id)
    return success(render_mapping({
        "incident_id": incident_id,
        "category_tier": category_tier(incident),
        "evidence_tier": evidence_tier(incident),
        "proposed_decision": proposed_decision(incident),
        "scope_ratio": investigation_scope_ratio(incident),
        "regulator_report_required": regulator_report_required(incident),
    }))


@bp.route("/safety/incidents/<incident_id>/decision", methods=["POST"])
@route("SafetyInvestigator")
def commit_decision(ident, incident_id):
    incident = get_incident(incident_id)
    payload = body()
    require_version(payload, "expected_incident_version")
    account = STORE.accounts.get(incident.get("account_id"))
    if account is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND, message="No such account.")

    assert_version_matches(payload, "expected_incident_version", incident, "SafetyIncident")
    decision_service.decision_guards(account, incident)

    updated = decision_service.commit_decision(account, incident, payload, ident.user_id)
    return success(serialize_incident(updated))


@bp.route("/safety/incidents/<incident_id>/appeals", methods=["POST"])
@route("SafetyAppealReviewer")
def file_appeal(ident, incident_id):
    incident = get_incident(incident_id)
    updated = decision_service.file_appeal(incident)
    return created(serialize_incident(updated))


@bp.route("/safety/incidents/<incident_id>/appeals/outcome", methods=["POST"])
@route("SafetyAppealReviewer")
def appeal_outcome(ident, incident_id):
    incident = get_incident(incident_id)
    payload = body()
    require_version(payload, "expected_incident_version")
    assert_version_matches(payload, "expected_incident_version", incident, "SafetyIncident")
    updated = decision_service.commit_appeal_outcome(incident, payload, ident.user_id)
    return success(serialize_incident(updated))


@bp.route("/safety/incidents/<incident_id>/appeals/eligibility", methods=["GET"])
@route("SafetyAppealReviewer", "SafetyOperationsLead", "PlatformAdmin")
def appeal_eligibility(ident, incident_id):
    incident = get_incident(incident_id)
    track, _ = appeal_track(incident)
    action = STORE.action_for_incident(incident_id)
    return success(render_mapping({
        "incident_id": incident_id,
        "appealable": (incident.get("incident_status") == "DECIDED"
                       and incident.get("decision_category") == "DEACTIVATED"),
        "appeal_track": track,
        "review_due_at": decision_service.review_due_at(incident),
        "appeal_deadline_at": (action or {}).get("appeal_deadline_at"),
        "prior_incident_count_at_intake": incident.get("prior_incident_count_at_intake"),
    }))


@bp.route("/safety/incidents/<incident_id>/regulator-reports", methods=["GET"])
@route("PlatformAdmin", "RegulatorLiaison", "SafetyOperationsLead", "SafetyInvestigator")
def list_incident_reports(ident, incident_id):
    get_incident(incident_id)
    limit, offset = read_pagination(request.args)
    items = STORE.reports_for_incident(incident_id)
    items.sort(key=lambda r: (r.get("created_at"), r.get("id") or ""))
    return success_list([serialize_report(r) for r in items], limit, offset)