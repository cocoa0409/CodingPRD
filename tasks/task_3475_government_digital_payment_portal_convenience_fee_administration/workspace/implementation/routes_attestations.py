"""Compliance attestations (PRD section 3.1). status is computed against the
logical clock on every read, never stored."""
from flask import Blueprint, request

import clock
import envelope
import helpers
import serialize
import store
from auth import caller
from validate import as_enum, as_instant, as_str, body, req_field

bp = Blueprint("attestations", __name__)

ATTESTATION_TYPES = {"PCI_DSS_AOC", "PENETRATION_TEST", "INTEGRATION_REVIEW"}


@bp.route("/portal/attestations", methods=["POST"])
def create_attestation():
    caller({"ComplianceAuditor"})
    data = body()
    agency_id = as_str(req_field(data, "agency_id"), "agency_id")
    attestation_type = as_enum(
        req_field(data, "attestation_type"), "attestation_type", ATTESTATION_TYPES
    )
    issued_at, issued_raw = as_instant(req_field(data, "issued_at"), "issued_at")
    expires_at, expires_raw = as_instant(req_field(data, "expires_at"), "expires_at")
    # priority 3: body foreign key
    helpers.get_agency(agency_id)
    rec = {
        "id": store.new_id(),
        "agency_id": agency_id,
        "attestation_type": attestation_type,
        "issued_at": issued_at,
        "issued_at_raw": issued_raw,
        "expires_at": expires_at,
        "expires_at_raw": expires_raw,
        "created_at": clock.now(),
        "created_seq": store.next_seq(),
    }
    store.attestations[rec["id"]] = rec
    return envelope.obj(serialize.attestation(rec), 201)


@bp.route("/portal/agencies/<rid>/attestations", methods=["GET"])
def list_attestations(rid):
    caller({"PlatformAdmin", "AgencyAdmin", "ComplianceAuditor"})
    helpers.get_agency(rid)
    items = [a for a in store.attestations.values() if a["agency_id"] == rid]
    items.sort(key=lambda a: (a["created_at"], a["created_seq"]))
    return envelope.page([serialize.attestation(a) for a in items], request.args)
