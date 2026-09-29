"""Call signing and attestation level assignment (PRD 3.6)."""
from flask import Blueprint

import auth
import calc
import envelope
import errors
import ser
import store
import valid
from store import db
from views_customer import load_customer
from views_number import VERIFIED_EVIDENCE, covering_assignment
from views_provider import load_provider

bp = Blueprint("attestations", __name__)

LEVELS = ("A", "B", "C")
READ_ROLES = (auth.REGULATOR, auth.COMPLIANCE_OFFICER, auth.FRAUD_ANALYST,
              auth.PROVIDER_ADMIN)


def load_attestation(attestation_id):
    row = db.attestations.get(attestation_id)
    if row is None:
        errors.fail(errors.ERR_ATTESTATION_NOT_FOUND,
                    "No call attestation with id %s" % attestation_id)
    return row


@bp.route("/rmd/call-attestations", methods=["POST"])
@auth.require(auth.PROVIDER_ADMIN)
def sign_call():
    data = valid.body()
    provider_id = valid.req_str(data, "provider_id")
    customer_id = valid.req_str(data, "customer_id")
    calling_number = valid.req_str(data, "calling_number")
    called_number = valid.req_str(data, "called_number")
    origination_time, raw_time = valid.req_dt(data, "origination_time")
    valid.check_e164(calling_number, called_number)
    provider = load_provider(provider_id)
    customer = load_customer(customer_id)
    auth.own_provider(provider_id)

    certificate_id = provider["active_certificate_id"]
    if certificate_id is None:
        errors.fail(errors.ERR_NO_ACTIVE_CERTIFICATE,
                    "The provider holds no ACTIVE signing certificate")
    if provider["auth_posture"] == "SIGNING_SUSPENDED":
        errors.fail(errors.ERR_SIGNING_SUSPENDED,
                    "The provider's auth_posture is SIGNING_SUSPENDED")
    if customer["kyc_state"] != "VERIFIED":
        errors.fail(errors.ERR_CUSTOMER_NOT_KYC_VERIFIED,
                    "The customer's kyc_state is not VERIFIED")
    if customer["origination_state"] != "ENABLED":
        errors.fail(errors.ERR_ORIGINATION_NOT_ENABLED,
                    "The customer's origination_state is not ENABLED")
    if customer["provider_id"] != provider_id:
        errors.fail(errors.ERR_CUSTOMER_PROVIDER_MISMATCH,
                    "The customer belongs to another provider")

    assignment = covering_assignment(customer_id, calling_number,
                                     origination_time)
    ownership_verified = bool(
        assignment is not None
        and assignment["ownership_evidence"] in VERIFIED_EVIDENCE)

    level, reason = calc.assign_attestation(
        provider["auth_posture"], customer["risk_tier"],
        customer["kyc_evidence_level"], ownership_verified)

    row = store.base_row(versioned=False)
    row.update({
        "provider_id": provider_id,
        "customer_id": customer_id,
        "certificate_id": certificate_id,
        "calling_number": calling_number,
        "called_number": called_number,
        "origination_time": origination_time,
        "attestation_level": level,
        "attestation_reason_code": reason,
        "ownership_verified": ownership_verified,
        "risk_tier_at_signing": customer["risk_tier"],
        "passport_identity_token": calc.passport_token(certificate_id, level),
    })
    store.remember_raw(row, "origination_time", raw_time)
    db.attestations[row["id"]] = row
    return envelope.created(ser.attestation(row))


@bp.route("/rmd/call-attestations/<attestation_id>", methods=["GET"])
@auth.require(*READ_ROLES)
def read_attestation(attestation_id):
    row = load_attestation(attestation_id)
    auth.own_provider(row["provider_id"])
    return envelope.ok(ser.attestation(row))


@bp.route("/rmd/call-attestations", methods=["GET"])
@auth.require(*READ_ROLES)
def list_attestations():
    limit, offset = envelope.pagination()
    provider_id = valid.arg_str("provider_id")
    customer_id = valid.arg_str("customer_id")
    certificate_id = valid.arg_str("certificate_id")
    level = valid.arg_enum("attestation_level", LEVELS)

    rows = auth.scope_rows(db.attestations.values(),
                           provider_of=lambda r: r["provider_id"])
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if certificate_id is not None:
        rows = [r for r in rows if r["certificate_id"] == certificate_id]
    if level is not None:
        rows = [r for r in rows if r["attestation_level"] == level]
    return envelope.collection(rows, ser.attestation, limit, offset)
