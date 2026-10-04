"""Consent routes (PRD 3.2)."""

from flask import Blueprint, request

import db
import response as R
from middleware import authenticated
from services import common
from services import consent as consent_svc

bp = Blueprint("consents", __name__)

CONSENT_TYPES = ("SELF", "GUARDIAN_PRESENT", "GUARDIAN_NOTARIZED", "COURT_ORDER")
IDENTIFICATION_TYPES = ("GOVERNMENT_PHOTO_ID", "BIRTH_CERTIFICATE", "PASSPORT", "STATE_ID")


@bp.route("/consents", methods=["POST"])
@authenticated("IntakeAssociate")
def create_consent():
    data = common.body()
    customer = common.get_customer(common.require_str(data, "customer_id"))
    jurisdiction = common.get_jurisdiction(common.require_str(data, "jurisdiction_id"))
    consent_type = common.require_enum(data, "consent_type", CONSENT_TYPES)
    identification_type = common.require_enum(
        data, "identification_type", IDENTIFICATION_TYPES)
    masked = common.require_str(data, "identification_number_masked")
    signed_at = common.require_instant(data, "signed_at")

    record = consent_svc.capture_consent(
        customer, jurisdiction, consent_type, identification_type, masked, signed_at)
    return R.object_response(record, 201)


@bp.route("/consents", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_consents():
    limit, offset = common.pagination_params()
    rows = list(db.DB.consents.values())
    for arg, field in (("customer_id", "customer_id"),
                       ("jurisdiction_id", "jurisdiction_id")):
        requested = request.args.get(arg)
        if requested:
            rows = [row for row in rows if getattr(row, field) == requested]
    rows = common.sorted_rows(rows)
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/consents/<consent_id>", methods=["GET"])
@authenticated("AnyAuthenticated")
def get_consent(consent_id):
    return R.object_response(common.get_consent(consent_id))


@bp.route("/consents/<consent_id>/verify", methods=["POST"])
@authenticated("IntakeAssociate")
def verify_consent(consent_id):
    consent = common.get_consent(consent_id)
    consent_svc.verify_consent(consent)
    return R.object_response(consent)


@bp.route("/consents/<consent_id>/reject", methods=["POST"])
@authenticated("IntakeAssociate")
def reject_consent(consent_id):
    consent = common.get_consent(consent_id)
    data = common.body()
    reason_code = common.require_str(data, "reason_code")
    consent_svc.reject_consent(consent, reason_code)
    return R.object_response(consent)


@bp.route("/consents/<consent_id>/revoke", methods=["POST"])
@authenticated("ComplianceOfficer")
def revoke_consent(consent_id):
    consent = common.get_consent(consent_id)
    consent_svc.revoke_consent(consent)
    return R.object_response(consent)


@bp.route("/consents/<consent_id>/renew", methods=["POST"])
@authenticated("IntakeAssociate")
def renew_consent(consent_id):
    consent = common.get_consent(consent_id)
    consent_svc.renew_consent(consent)
    return R.object_response(consent)


@bp.route("/consents/<consent_id>/guardian-verification", methods=["POST"])
@authenticated("IntakeAssociate")
def guardian_verification(consent_id):
    consent = common.get_consent(consent_id)
    data = common.body()
    outcome = common.require_enum(data, "outcome", ("VERIFIED", "FAILED"))
    consent_svc.record_guardian_verification(consent, outcome)
    return R.object_response(consent)