"""Certificate acquisition, activation, renewal and revocation (PRD 3.2)."""
from flask import Blueprint

import auth
import derive
import envelope
import errors
import ser
import store
import valid
from store import db, touch
from views_provider import load_provider

bp = Blueprint("certificates", __name__)

STATUSES = ("REQUESTED", "ISSUED", "ACTIVE", "SUPERSEDED", "REVOKED",
            "EXPIRED")
REVOCATION_REASONS = ("KEY_COMPROMISE", "SPC_WITHDRAWN", "REGULATOR_ORDER")

READ_ROLES = (auth.REGULATOR, auth.POLICY_ADMINISTRATOR,
              auth.COMPLIANCE_OFFICER, auth.PROVIDER_ADMIN)


def load_certificate(certificate_id):
    row = db.certificates.get(certificate_id)
    if row is None:
        errors.fail(errors.ERR_CERTIFICATE_NOT_FOUND,
                    "No certificate with id %s" % certificate_id)
    return row


def _bad_state(message):
    errors.fail(errors.ERR_CERTIFICATE_STATE_INVALID, message)


def _new_certificate(provider_id, spc_token, fingerprint, not_before,
                     raw_before, not_after, raw_after):
    row = store.base_row()
    row.update({
        "provider_id": provider_id,
        "spc_token": spc_token,
        "public_key_fingerprint": fingerprint,
        "not_before": not_before,
        "not_after": not_after,
        "status": "REQUESTED",
        "issued_at": None,
        "activated_at": None,
        "revoked_at": None,
        "revocation_reason": None,
        "predecessor_certificate_id": None,
        "renewal_generation": 1,
    })
    store.remember_raw(row, "not_before", raw_before)
    store.remember_raw(row, "not_after", raw_after)
    return row


@bp.route("/rmd/certificates", methods=["POST"])
@auth.require(auth.POLICY_ADMINISTRATOR)
def request_certificate():
    data = valid.body()
    provider_id = valid.req_str(data, "provider_id")
    spc_token = valid.req_str(data, "spc_token")
    fingerprint = valid.req_str(data, "public_key_fingerprint")
    not_before, raw_before = valid.req_dt(data, "not_before")
    not_after, raw_after = valid.req_dt(data, "not_after")
    valid.check_interval(not_before, not_after)
    load_provider(provider_id)

    row = _new_certificate(provider_id, spc_token, fingerprint, not_before,
                           raw_before, not_after, raw_after)
    db.certificates[row["id"]] = row
    return envelope.created(ser.certificate(row))


@bp.route("/rmd/certificates/<certificate_id>/issue", methods=["POST"])
@auth.require(auth.POLICY_ADMINISTRATOR)
def issue_certificate(certificate_id):
    row = load_certificate(certificate_id)
    now = db.now()
    if row["status"] != "REQUESTED":
        _bad_state("Only a REQUESTED certificate can be issued")
    if not row["not_after"] > now:
        _bad_state("The certificate validity interval has already lapsed")
    row["status"] = "ISSUED"
    row["issued_at"] = now
    touch(row)
    return envelope.ok(ser.certificate(row))


@bp.route("/rmd/certificates/<certificate_id>/activate", methods=["POST"])
@auth.require(auth.PROVIDER_ADMIN)
def activate_certificate(certificate_id):
    row = load_certificate(certificate_id)
    auth.own_provider(row["provider_id"])
    now = db.now()
    if row["status"] != "ISSUED":
        _bad_state("Only an ISSUED certificate can be activated")
    if now < row["not_before"] or now > row["not_after"]:
        _bad_state("The current logical clock is outside the validity interval")
    if derive.active_certificate_id(row["provider_id"]) is not None:
        _bad_state("The provider already holds an ACTIVE certificate")
    row["status"] = "ACTIVE"
    row["activated_at"] = now
    touch(row)
    derive.recompute_provider_by_id(row["provider_id"])
    return envelope.ok(ser.certificate(row))


@bp.route("/rmd/certificates/<certificate_id>/renew", methods=["POST"])
@auth.require(auth.POLICY_ADMINISTRATOR)
def renew_certificate(certificate_id):
    data = valid.body()
    spc_token = valid.req_str(data, "spc_token")
    fingerprint = valid.req_str(data, "public_key_fingerprint")
    not_before, raw_before = valid.req_dt(data, "not_before")
    not_after, raw_after = valid.req_dt(data, "not_after")
    valid.check_interval(not_before, not_after)
    predecessor = load_certificate(certificate_id)
    if predecessor["status"] != "ACTIVE":
        _bad_state("Only an ACTIVE certificate can be renewed")

    successor = _new_certificate(
        predecessor["provider_id"], spc_token, fingerprint, not_before,
        raw_before, not_after, raw_after)
    successor["status"] = "ISSUED"
    successor["issued_at"] = db.now()
    successor["predecessor_certificate_id"] = predecessor["id"]
    successor["renewal_generation"] = predecessor["renewal_generation"] + 1
    db.certificates[successor["id"]] = successor

    predecessor["status"] = "SUPERSEDED"
    touch(predecessor)
    derive.recompute_provider_by_id(predecessor["provider_id"])
    return envelope.created(ser.certificate(successor))


@bp.route("/rmd/certificates/<certificate_id>/revoke", methods=["POST"])
@auth.require(auth.POLICY_ADMINISTRATOR)
def revoke_certificate(certificate_id):
    data = valid.body()
    reason = valid.req_enum(data, "revocation_reason", REVOCATION_REASONS)
    row = load_certificate(certificate_id)
    if row["status"] not in ("REQUESTED", "ISSUED", "ACTIVE"):
        _bad_state("A terminal certificate cannot be revoked")
    row["status"] = "REVOKED"
    row["revoked_at"] = db.now()
    row["revocation_reason"] = reason
    touch(row)
    derive.recompute_provider_by_id(row["provider_id"])
    return envelope.ok(ser.certificate(row))


@bp.route("/rmd/certificates/<certificate_id>", methods=["GET"])
@auth.require(*READ_ROLES)
def read_certificate(certificate_id):
    row = load_certificate(certificate_id)
    auth.own_provider(row["provider_id"])
    return envelope.ok(ser.certificate(row))


@bp.route("/rmd/certificates", methods=["GET"])
@auth.require(*READ_ROLES)
def list_certificates():
    limit, offset = envelope.pagination()
    provider_id = valid.arg_str("provider_id")
    predecessor_id = valid.arg_str("predecessor_certificate_id")
    status = valid.arg_enum("status", STATUSES)

    rows = auth.scope_rows(db.certificates.values(),
                           provider_of=lambda r: r["provider_id"])
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if predecessor_id is not None:
        rows = [r for r in rows
                if r["predecessor_certificate_id"] == predecessor_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.collection(rows, ser.certificate, limit, offset)
