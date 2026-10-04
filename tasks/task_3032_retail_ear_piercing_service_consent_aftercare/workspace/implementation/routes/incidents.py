"""Incident and healing-outcome routes (PRD 3.6, 3.7)."""

from flask import Blueprint, request

import db
import errors as E
import response as R
from middleware import authenticated
from services import common
from services import incidents as incident_svc
from services import outcomes as outcome_svc

bp = Blueprint("incidents", __name__)


# =============================================================================
# Incidents
# =============================================================================
@bp.route("/incidents", methods=["POST"])
@authenticated("ComplianceOfficer")
def create_incident():
    data = common.body()
    session = common.get_session(common.require_str(data, "session_id"))
    common.check_expected_version(data, "expected_session_version", session)

    reported_at = common.require_instant(data, "reported_at")
    severity = common.require_enum(
        data, "severity", ("MINOR", "MODERATE", "SEVERE", "MEDICAL_EMERGENCY"))
    reaction_codes = common.validated_list(data, "reaction_codes",
                                           db.ALLOWED_REACTIONS, optional=True)

    incident = incident_svc.file_incident(session, reported_at, severity, reaction_codes)
    return R.object_response(incident, 201)


@bp.route("/incidents", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_incidents():
    limit, offset = common.pagination_params()
    rows = list(db.DB.incidents.values())
    requested_session = request.args.get("session_id")
    if requested_session:
        rows = [i for i in rows if i.session_id == requested_session]
    requested_store = request.args.get("store_location_id")
    if requested_store:
        from calculations import store_incident_rows
        reachable = {i.id for i in store_incident_rows(db.DB, requested_store)}
        rows = [i for i in rows if i.id in reachable]
    rows = common.sorted_rows(rows)
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/incidents/<incident_id>", methods=["GET"])
@authenticated("AnyAuthenticated")
def get_incident(incident_id):
    return R.object_response(common.get_incident(incident_id))


@bp.route("/incidents/<incident_id>/triage", methods=["POST"])
@authenticated("ComplianceOfficer")
def triage(incident_id):
    incident = common.get_incident(incident_id)
    incident_svc.triage(incident)
    return R.object_response(incident)


@bp.route("/incidents/<incident_id>/escalate", methods=["POST"])
@authenticated("ComplianceOfficer")
def escalate(incident_id):
    incident = common.get_incident(incident_id)
    incident_svc.escalate(incident)
    return R.object_response(incident)


@bp.route("/incidents/<incident_id>/resolve", methods=["POST"])
@authenticated("ComplianceOfficer")
def resolve(incident_id):
    incident = common.get_incident(incident_id)
    data = common.body()
    incident_svc.resolve(incident, data.get("resolution_note"))
    return R.object_response(incident)


@bp.route("/incidents/<incident_id>/issue-refund", methods=["POST"])
@authenticated("StoreManager")
def issue_refund(incident_id):
    incident = common.get_incident(incident_id)
    data = common.body()
    common.require_str(data, "refund_destination")
    requested = data.get("requested_refund_cents")
    if requested is not None:
        if isinstance(requested, bool) or not isinstance(requested, int):
            E.fail(E.ERR_INVALID_REQUEST,
                   "requested_refund_cents must be an integer")
        incident_svc.requested_refund_allowed(incident, requested)
    incident_svc.issue_refund(incident)
    return R.object_response(incident)


@bp.route("/incidents/<incident_id>/reopen", methods=["POST"])
@authenticated("ComplianceOfficer")
def reopen(incident_id):
    incident = common.get_incident(incident_id)
    data = common.body()
    reopen_reason = common.require_str(data, "reopen_reason")
    incident_svc.reopen(incident, reopen_reason)
    return R.object_response(incident)


# =============================================================================
# Healing outcomes
# =============================================================================
@bp.route("/healing-outcomes", methods=["POST"])
@authenticated("Piercer")
def create_outcome():
    data = common.body()
    session = common.get_session(common.require_str(data, "session_id"))
    common.check_expected_version(data, "expected_session_version", session)
    assessed_at = common.require_instant(data, "assessed_at")

    outcome = outcome_svc.create_outcome(session, assessed_at)
    return R.object_response(outcome, 201)


@bp.route("/healing-outcomes", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_outcomes():
    limit, offset = common.pagination_params()
    rows = list(db.DB.outcomes.values())
    requested = request.args.get("session_id")
    if requested:
        rows = [o for o in rows if o.session_id == requested]
    rows = common.sorted_rows(rows)
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/healing-outcomes/<outcome_id>", methods=["GET"])
@authenticated("AnyAuthenticated")
def get_outcome(outcome_id):
    return R.object_response(common.get_outcome(outcome_id))


@bp.route("/healing-outcomes/<outcome_id>/downgrade", methods=["POST"])
@authenticated("Piercer")
def downgrade_outcome(outcome_id):
    outcome = common.get_outcome(outcome_id)
    data = common.body()
    sites = common.validated_list(data, "downgraded_sites", db.ALLOWED_SITES)
    outcome_svc.downgrade(outcome, sites)
    return R.object_response(outcome)


@bp.route("/healing-outcomes/<outcome_id>/claim-re-pierce", methods=["POST"])
@authenticated("Piercer")
def claim_re_pierce(outcome_id):
    outcome = common.get_outcome(outcome_id)
    outcome_svc.claim_re_pierce(outcome)
    return R.object_response(outcome)


@bp.route("/healing-outcomes/<outcome_id>/close", methods=["POST"])
@authenticated("ComplianceOfficer")
def close_outcome(outcome_id):
    outcome = common.get_outcome(outcome_id)
    outcome_svc.close(outcome)
    return R.object_response(outcome)