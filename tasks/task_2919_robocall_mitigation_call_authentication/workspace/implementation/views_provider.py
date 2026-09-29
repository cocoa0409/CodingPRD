"""Provider registration and the provider register (PRD 3.1)."""
from flask import Blueprint

import auth
import envelope
import errors
import ser
import store
import valid
from store import db

bp = Blueprint("providers", __name__)

PROVIDER_TYPES = ("FACILITIES_BASED", "NON_FACILITIES_RESELLER", "GATEWAY")
FILING_STATUSES = ("UNFILED", "PARTIAL", "COMPLETE")
POSTURES = ("FULL_ATTESTATION", "GATEWAY_LIMITED", "SIGNING_SUSPENDED")

READ_ROLES = (auth.REGULATOR, auth.POLICY_ADMINISTRATOR,
              auth.COMPLIANCE_OFFICER, auth.KYC_ANALYST, auth.FRAUD_ANALYST,
              auth.PROVIDER_ADMIN)
LIST_ROLES = (auth.REGULATOR, auth.POLICY_ADMINISTRATOR,
              auth.COMPLIANCE_OFFICER, auth.KYC_ANALYST, auth.FRAUD_ANALYST)


def load_provider(provider_id):
    row = db.providers.get(provider_id)
    if row is None:
        errors.fail(errors.ERR_PROVIDER_NOT_FOUND,
                    "No provider with id %s" % provider_id)
    return row


@bp.route("/rmd/providers", methods=["POST"])
@auth.require(auth.REGULATOR)
def register_provider():
    data = valid.body()
    legal_name = valid.req_str(data, "legal_name")
    provider_type = valid.req_enum(data, "provider_type", PROVIDER_TYPES)

    row = store.base_row()
    row.update({
        "legal_name": legal_name,
        "provider_type": provider_type,
        "rmd_filing_status": "UNFILED",
        "auth_posture": "SIGNING_SUSPENDED",
        "active_certificate_id": None,
        "penalty_points": 0,
        "overdue_traceback_count": 0,
        "open_notice_count": 0,
        "active_assigned_number_count": 0,
        "outstanding_forfeiture_cents": 0,
        "blocking_false_positive_rate": 0.0,
        "sweep_index": 0,
    })
    db.providers[row["id"]] = row
    return envelope.created(ser.provider(row))


@bp.route("/rmd/providers/<provider_id>", methods=["GET"])
@auth.require(*READ_ROLES)
def read_provider(provider_id):
    row = load_provider(provider_id)
    auth.own_provider(row["id"])
    return envelope.ok(ser.provider(row))


@bp.route("/rmd/providers", methods=["GET"])
@auth.require(*LIST_ROLES)
def list_providers():
    limit, offset = envelope.pagination()
    provider_type = valid.arg_enum("provider_type", PROVIDER_TYPES)
    posture = valid.arg_enum("auth_posture", POSTURES)
    filing = valid.arg_enum("rmd_filing_status", FILING_STATUSES)

    rows = list(db.providers.values())
    if provider_type is not None:
        rows = [r for r in rows if r["provider_type"] == provider_type]
    if posture is not None:
        rows = [r for r in rows if r["auth_posture"] == posture]
    if filing is not None:
        rows = [r for r in rows if r["rmd_filing_status"] == filing]
    return envelope.collection(rows, ser.provider, limit, offset)
