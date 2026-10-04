"""Agency onboarding and lifecycle (PRD section 3.1)."""
from flask import Blueprint

import clock
import envelope
import helpers
import serialize
import store
from auth import caller
from errors import invalid_state, raise_err
from validate import as_enum, as_str, body, req_field

bp = Blueprint("agencies", __name__)

FEE_MODELS = {"CONVENIENCE_FEE", "ABSORBED"}


@bp.route("/portal/agencies", methods=["POST"])
def create_agency():
    caller({"PlatformAdmin"})
    data = body()
    legal_name = as_str(req_field(data, "legal_name"), "legal_name")
    agency_type = as_enum(req_field(data, "agency_type"), "agency_type", {"STATE", "LOCAL"})
    default_fee_model = as_enum(
        req_field(data, "default_fee_model"), "default_fee_model", FEE_MODELS
    )
    now = clock.now()
    rec = {
        "id": store.new_id(),
        "legal_name": legal_name,
        "agency_type": agency_type,
        "default_fee_model": default_fee_model,
        "status": "ONBOARDING",
        "activated_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "created_seq": store.next_seq(),
    }
    store.agencies[rec["id"]] = rec
    return envelope.obj(serialize.agency(rec), 201)


@bp.route("/portal/agencies/<rid>", methods=["GET"])
def get_agency(rid):
    caller({"PlatformAdmin", "AgencyAdmin", "TreasuryOfficer", "ComplianceAuditor"})
    return envelope.obj(serialize.agency(helpers.get_agency(rid)))


@bp.route("/portal/agencies/<rid>/activate", methods=["POST"])
def activate_agency(rid):
    caller({"PlatformAdmin"})
    rec = helpers.get_agency(rid)
    # priority 5: state permission
    if rec["status"] not in ("ONBOARDING", "SUSPENDED"):
        invalid_state("Agency in status %s cannot be activated" % rec["status"])
    # priority 6: compliance and statutory gates (account first, then attestation)
    if not any(
        acc["agency_id"] == rid and acc["status"] == "VERIFIED"
        for acc in store.accounts.values()
    ):
        raise_err(
            "ERR_NO_VERIFIED_ACCOUNT",
            409,
            "Agency holds no VERIFIED settlement account",
        )
    if not helpers.pci_current(rid):
        raise_err(
            "ERR_COMPLIANCE_LAPSED",
            409,
            "Agency lacks a CURRENT PCI_DSS_AOC attestation at the logical clock",
        )
    rec["status"] = "ACTIVE"
    rec["activated_at"] = clock.now()
    helpers.touch(rec)
    return envelope.obj(serialize.agency(rec))


@bp.route("/portal/agencies/<rid>/suspend", methods=["POST"])
def suspend_agency(rid):
    caller({"PlatformAdmin"})
    rec = helpers.get_agency(rid)
    if rec["status"] != "ACTIVE":
        invalid_state("Only an ACTIVE agency can be suspended")
    rec["status"] = "SUSPENDED"
    helpers.touch(rec)
    # Cascade link 1: ACTIVE services -> DEACTIVATED; link 2: their OPEN
    # quotes -> VOIDED. In-flight transactions are unaffected. Deactivated
    # services are NOT restored by a later reactivation.
    for svc in store.services.values():
        if svc["agency_id"] == rid and svc["status"] == "ACTIVE":
            helpers.deactivate_service(svc)
    return envelope.obj(serialize.agency(rec))


@bp.route("/portal/agencies/<rid>/offboard", methods=["POST"])
def offboard_agency(rid):
    caller({"PlatformAdmin"})
    rec = helpers.get_agency(rid)
    if rec["status"] != "ACTIVE":
        invalid_state("Only an ACTIVE agency can be offboarded")
    # priority 11: zero unsettled exposure required
    for txn in store.transactions.values():
        if txn["agency_id"] == rid and txn["funds_status"] in (
            "AUTHORIZED",
            "CAPTURED",
            "RE_PRESENTED",
        ):
            raise_err(
                "ERR_OFFBOARD_BLOCKED",
                409,
                "Agency carries an unsettled transaction",
            )
    for b in store.batches.values():
        if b["agency_id"] == rid and b["status"] in (
            "OPEN",
            "CLOSED",
            "SUBMITTED",
            "CONFIRMED",
            "EXCEPTION",
        ):
            raise_err(
                "ERR_OFFBOARD_BLOCKED",
                409,
                "Agency carries an unfinished settlement batch",
            )
    rec["status"] = "OFFBOARDED"
    helpers.touch(rec)
    for svc in store.services.values():
        if svc["agency_id"] == rid and svc["status"] != "DEACTIVATED":
            helpers.deactivate_service(svc)
    return envelope.obj(serialize.agency(rec))
