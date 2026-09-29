"""Export certification (PRD 3.7)."""

from flask import Blueprint

import auth
import calc
import config
import envelope
import resolve
import serializers
import store
import validate
from errors import fail
from validate import F

bp = Blueprint("certificates", __name__)


@bp.post("/export-certificates")
def draft_certificate():
    values = validate.parse([
        F("sire_id", "id", required=True),
        F("straw_lot_id", "id", required=True),
        F("country_requirement_id", "id", required=True),
    ])
    auth.require_role(config.ROLE_EXPORT_COORD)
    sire = resolve.need("sires", values["sire_id"])
    lot = resolve.need("straw_lots", values["straw_lot_id"])
    requirement = resolve.need("country_requirements", values["country_requirement_id"])
    if lot["sire_id"] != sire["id"]:
        fail("ERR_LOT_SIRE_MISMATCH", "The lot was not cut from the certificate's bull.")
    rec = store.new_record("export_certificates", {
        "sire_id": sire["id"],
        "straw_lot_id": lot["id"],
        "country_requirement_id": requirement["id"],
        "destination_country_code": requirement["country_code"],
        "status": "DRAFT",
        "submission_round": 0,
        "rejection_reason": None,
        "issued_by_user_id": None,
        "issued_at": None,
        "expires_at": None,
        "revocation_reason": None,
    })
    return envelope.created(serializers.export_certificate(rec))


@bp.get("/export-certificates/<certificate_id>")
def read_certificate(certificate_id):
    auth.require_role(config.ROLE_EXPORT_COORD, config.ROLE_PROGRAM_DIRECTOR,
                      config.ROLE_STAFF_VET, config.ROLE_DISTRIBUTOR)
    rec = resolve.need("export_certificates", certificate_id)
    return envelope.ok(serializers.export_certificate(rec))


@bp.get("/export-certificates")
def list_certificates():
    auth.require_role(config.ROLE_EXPORT_COORD, config.ROLE_PROGRAM_DIRECTOR,
                      config.ROLE_STAFF_VET, config.ROLE_DISTRIBUTOR)
    limit, offset = validate.pagination()
    sire_id = validate.qstr("sire_id")
    straw_lot_id = validate.qstr("straw_lot_id")
    country_requirement_id = validate.qstr("country_requirement_id")
    status = validate.qenum("status", config.CERT_STATUSES)
    items = []
    for rec in store.rows("export_certificates"):
        if sire_id is not None and rec["sire_id"] != sire_id:
            continue
        if straw_lot_id is not None and rec["straw_lot_id"] != straw_lot_id:
            continue
        if (country_requirement_id is not None
                and rec["country_requirement_id"] != country_requirement_id):
            continue
        if status is not None and rec["status"] != status:
            continue
        items.append(rec)
    return envelope.listing(items, limit, offset, serializers.export_certificate)


@bp.post("/export-certificates/<certificate_id>/submit")
def submit_certificate(certificate_id):
    validate.parse([F("submission_note", "string", default=None)])
    auth.require_role(config.ROLE_EXPORT_COORD)
    rec = resolve.need("export_certificates", certificate_id)
    if rec["status"] not in ("DRAFT", "REJECTED"):
        fail("ERR_CERTIFICATE_STATE", "Submission requires a DRAFT or REJECTED certificate.")
    if int(rec["submission_round"]) >= config.MAX_SUBMISSION_ROUNDS:
        fail("ERR_RESUBMISSION_LIMIT", "A certificate may enter SUBMITTED at most three times.")
    sire = store.get("sires", rec["sire_id"])
    lot = store.get("straw_lots", rec["straw_lot_id"])
    requirement = store.get("country_requirements", rec["country_requirement_id"])
    facility = store.get("facilities", sire["housing_facility_id"]) if sire else None
    if facility is None or facility["approval_status"] != "APPROVED":
        fail("ERR_FACILITY_SUSPENDED", "The bull's housing facility is not APPROVED.")
    if rec["destination_country_code"] not in list(facility["approved_export_countries"]):
        fail("ERR_DESTINATION_NOT_APPROVED",
             "The facility is not approved to export to %s." % rec["destination_country_code"])
    if lot["product_line"] == "SEXED" and not requirement["sexed_semen_allowed"]:
        fail("ERR_PRODUCT_NOT_PERMITTED", "The destination does not permit sorted semen.")
    if lot["product_line"] == "EMBRYO" and not requirement["embryo_allowed"]:
        fail("ERR_PRODUCT_NOT_PERMITTED", "The destination does not permit embryos.")
    served = sire["isolation_days_applied"]
    if served is None or int(served) < int(requirement["min_isolation_days"]):
        fail("ERR_ISOLATION_TOO_SHORT", "The quarantine served is shorter than the destination requires.")
    rec["status"] = "SUBMITTED"
    rec["submission_round"] = int(rec["submission_round"]) + 1
    rec["rejection_reason"] = None
    store.touch(rec)
    return envelope.ok(serializers.export_certificate(rec))


@bp.post("/export-certificates/<certificate_id>/issue")
def issue_certificate(certificate_id):
    validate.parse([F("issue_note", "string", default=None)])
    auth.require_role(config.ROLE_STAFF_VET)
    user = auth.require_user_id()
    rec = resolve.need("export_certificates", certificate_id)
    if rec["status"] != "SUBMITTED":
        fail("ERR_CERTIFICATE_STATE", "Only a SUBMITTED certificate may be signed.")
    lot = store.get("straw_lots", rec["straw_lot_id"])
    if lot is None or lot["distribution_status"] != "RELEASED":
        fail("ERR_LOT_NOT_RELEASED", "The covered lot is not RELEASED.")
    # Segregation of duties: the signer may not have resulted any of this
    # bull's assays.
    for test in store.DB["health_tests"].values():
        if test["sire_id"] == rec["sire_id"] and test["recorded_by_user_id"] == user:
            fail("ERR_CERTIFIER_TESTED_SIRE",
                 "A veterinarian who resulted this bull's assays may not sign his paperwork.")
    requirement = store.get("country_requirements", rec["country_requirement_id"])
    chosen = calc.pick_country_tests(rec["sire_id"], requirement)
    if chosen is None:
        fail("ERR_COUNTRY_TEST_MISSING",
             "A required destination assay has no satisfying NEGATIVE test.")
    expires_at = None
    for test in chosen.values():
        valid_until = test["valid_until"]
        if expires_at is None or store.dt_of(valid_until) < store.dt_of(expires_at):
            expires_at = valid_until
    rec["status"] = "ISSUED"
    rec["issued_by_user_id"] = user
    rec["issued_at"] = store.clock_iso()
    rec["expires_at"] = expires_at
    store.touch(rec)
    return envelope.ok(serializers.export_certificate(rec))


@bp.post("/export-certificates/<certificate_id>/reject")
def reject_certificate(certificate_id):
    values = validate.parse([F("rejection_reason", "string", required=True)])
    auth.require_role(config.ROLE_STAFF_VET, config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("export_certificates", certificate_id)
    if rec["status"] != "SUBMITTED":
        fail("ERR_CERTIFICATE_STATE", "Only a SUBMITTED certificate may be refused.")
    rec["status"] = "REJECTED"
    rec["rejection_reason"] = values["rejection_reason"]
    store.touch(rec)
    return envelope.ok(serializers.export_certificate(rec))


@bp.post("/export-certificates/<certificate_id>/revoke")
def revoke_certificate(certificate_id):
    values = validate.parse([F("revocation_reason", "string", required=True)])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR, config.ROLE_STAFF_VET)
    rec = resolve.need("export_certificates", certificate_id)
    if rec["status"] != "ISSUED":
        fail("ERR_CERTIFICATE_STATE", "Only an ISSUED certificate may be revoked.")
    rec["status"] = "REVOKED"
    rec["revocation_reason"] = values["revocation_reason"]
    store.touch(rec)
    return envelope.ok(serializers.export_certificate(rec))
