"""Identity-fraud adjudication and external (exchange) identity matching."""

from decimal import Decimal

from flask import Blueprint, g

from core import (
    ALL_ROLES, SCORED_ATTRIBUTES, authenticate, base_entity, created, err,
    field_bool, field_enum, field_id, field_map, field_string, get_body, ok,
    ok_list, paginate, query_filter, store, touch,
)
import domain
import scoring
import serializers
from routes_config import active_rule_set

bp = Blueprint("fraud", __name__)

TRIGGER_KINDS = ["BIOMETRIC_CONFLICT", "INSURANCE_CONFLICT", "BOTH", "MANUAL"]


def _investigation_or_404(investigation_id):
    row = store.investigations.get(investigation_id)
    if row is None:
        raise err("ERR_INVESTIGATION_NOT_FOUND",
                  "No fraud investigation with id %s" % investigation_id)
    return row


# --------------------------------------------------------------------------
# Fraud investigations
# --------------------------------------------------------------------------
@bp.post("/mpi/fraud-investigations")
def create_investigation():
    authenticate(["PrivacyOfficer"])
    body = get_body()
    record_id = field_id(body, "record_id", required=True)
    pair_id = field_id(body, "pair_id")
    trigger_kind = field_enum(body, "trigger_kind", TRIGGER_KINDS, required=True)
    note = field_string(body, "note")

    record = store.records.get(record_id)                                # rank 8
    if record is None:
        raise err("ERR_RECORD_NOT_FOUND", "No patient record with id %s" % record_id)
    if pair_id is not None and pair_id not in store.pairs:               # rank 9
        raise err("ERR_PAIR_NOT_FOUND", "No candidate pair with id %s" % pair_id)

    row = domain.open_investigation(record, pair_id, trigger_kind, "OFFICER",
                                    g.user_id, note)
    return created(serializers.investigation(row))


@bp.get("/mpi/fraud-investigations/<investigation_id>")
def get_investigation(investigation_id):
    authenticate(ALL_ROLES)
    return ok(serializers.investigation(_investigation_or_404(investigation_id)))


@bp.get("/mpi/fraud-investigations")
def list_investigations():
    authenticate(ALL_ROLES)
    rows = sorted(store.investigations.values(), key=lambda i: (i["created_at"], i["_seq"]))
    for key in ("record_id", "pair_id", "state", "trigger_kind"):
        rows = query_filter(rows, key)
    window, page = paginate(rows)
    return ok_list([serializers.investigation(i) for i in window], page)


@bp.post("/mpi/fraud-investigations/<investigation_id>/substantiate")
def substantiate(investigation_id):
    authenticate(["PrivacyOfficer"])
    body = get_body()
    finding_note = field_string(body, "finding_note", required=True)
    row = _investigation_or_404(investigation_id)                        # rank 14
    if row["state"] != "OPEN":                                           # rank 31
        raise err("ERR_INVESTIGATION_INVALID_STATE",
                  "Investigation %s is in state %s" % (investigation_id, row["state"]))
    row["state"] = "SUBSTANTIATED"
    row["finding_note"] = finding_note
    touch(row)
    record = store.records.get(row["record_id"])
    if record is not None:
        domain.reconcile_integrity(record)
        row["risk_score"] = scoring.compute_risk_score(row)
        domain.escalate_pairs_for_record(record["id"])
    return ok(serializers.investigation(row))


@bp.post("/mpi/fraud-investigations/<investigation_id>/unsubstantiate")
def unsubstantiate(investigation_id):
    authenticate(["PrivacyOfficer"])
    body = get_body()
    finding_note = field_string(body, "finding_note", required=True)
    row = _investigation_or_404(investigation_id)                        # rank 14
    if row["state"] != "OPEN":                                           # rank 31
        raise err("ERR_INVESTIGATION_INVALID_STATE",
                  "Investigation %s is in state %s" % (investigation_id, row["state"]))
    row["state"] = "UNSUBSTANTIATED"
    row["finding_note"] = finding_note
    touch(row)
    record = store.records.get(row["record_id"])
    if record is not None:
        domain.reconcile_integrity(record)
        if record["integrity_state"] == "CLEAR":
            domain.deescalate_pairs_for_record(record["id"])
    return ok(serializers.investigation(row))


@bp.post("/mpi/fraud-investigations/<investigation_id>/refer")
def refer(investigation_id):
    authenticate(["PrivacyOfficer"])
    body = get_body()
    reference = field_string(body, "referral_reference", required=True)
    row = _investigation_or_404(investigation_id)                        # rank 14
    if row["state"] != "SUBSTANTIATED":                                  # rank 31
        raise err("ERR_INVESTIGATION_INVALID_STATE",
                  "Investigation %s is in state %s" % (investigation_id, row["state"]))
    row["state"] = "REFERRED_LAW_ENFORCEMENT"
    row["referral_reference"] = reference
    touch(row)
    record = store.records.get(row["record_id"])
    if record is not None:
        domain.reconcile_integrity(record)
    return ok(serializers.investigation(row))


# --------------------------------------------------------------------------
# External match requests
# --------------------------------------------------------------------------
EXTERNAL_KEYS = ["last_name", "first_name", "dob", "sex", "ssn_last4", "postal_code", "phone"]


@bp.post("/mpi/external-match-requests")
def create_external_match():
    authenticate(["IdentityAnalyst"])
    body = get_body()
    record_id = field_id(body, "record_id", required=True)
    partner_code = field_string(body, "exchange_partner_code", required=True)
    consent = field_bool(body, "consent_on_file", required=True)
    demographics = field_map(body, "external_demographics", required=True)

    record = store.records.get(record_id)                                # rank 8
    if record is None:
        raise err("ERR_RECORD_NOT_FOUND", "No patient record with id %s" % record_id)
    if domain.under_fraud_hold(record):                                  # rank 21
        raise err("ERR_RECORD_UNDER_FRAUD_HOLD",
                  "Patient record %s is under a fraud hold" % record_id)
    if record["integrity_state"] == "REMEDIATION_PENDING":               # rank 22
        raise err("ERR_RECORD_REMEDIATION_PENDING",
                  "Patient record %s has a remediation pending" % record_id)
    if not consent:                                                      # rank 23
        raise err("ERR_EXCHANGE_CONSENT_MISSING",
                  "consent_on_file must be true to submit an external match request")
    if record["identity_state"] != "ACTIVE":                             # rank 25
        raise err("ERR_RECORD_NOT_ACTIVE", "Patient record %s is not ACTIVE" % record_id)

    partner = {key: demographics.get(key) for key in EXTERNAL_KEYS}
    partner["biometric_template_hash"] = None
    partner["insurance_member_id"] = None

    rule_set = active_rule_set()
    if rule_set is not None:
        outcome = scoring.score(scoring.record_attrs(record), partner, rule_set, "TOLERANT")
        external_score = outcome["match_score"]
        matched = external_score >= rule_set["auto_link_threshold"]
    else:
        external_score = Decimal("0.00")
        matched = False

    row = base_entity()
    row.update({
        "record_id": record_id,
        "exchange_partner_code": partner_code,
        "consent_on_file": consent,
        "external_demographics": dict(demographics),
        "external_score": external_score,
        "state": "SUBMITTED",
    })
    store.external_matches[row["id"]] = row
    row["state"] = "MATCHED" if matched else "NO_MATCH"
    touch(row)
    return created(serializers.external_match(row))


@bp.get("/mpi/external-match-requests/<request_id>")
def get_external_match(request_id):
    authenticate(ALL_ROLES)
    row = store.external_matches.get(request_id)
    if row is None:
        raise err("ERR_RECORD_NOT_FOUND", "No external match request with id %s" % request_id)
    return ok(serializers.external_match(row))


@bp.get("/mpi/external-match-requests")
def list_external_matches():
    authenticate(ALL_ROLES)
    rows = sorted(store.external_matches.values(), key=lambda r: (r["created_at"], r["_seq"]))
    for key in ("record_id", "state", "exchange_partner_code"):
        rows = query_filter(rows, key)
    window, page = paginate(rows)
    return ok_list([serializers.external_match(r) for r in window], page)
