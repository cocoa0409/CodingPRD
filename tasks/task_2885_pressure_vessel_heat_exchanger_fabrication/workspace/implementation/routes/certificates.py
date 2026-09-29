"""Certificate of Authorization, shop audits and renewals (PRD 3.1)."""

from flask import Blueprint

import db
import validation
from errors import fail
from middleware import ALL_ROLES, guard
from routes import common
from services import calc, derive

bp = Blueprint("certificates", __name__)

SCOPE_CODES = ("U", "U2", "S", "R")
AUDIT_TYPES = ("INTERNAL_QMS", "JOINT_REVIEW", "TRIENNIAL_RENEWAL")
SEVERITIES = ("MAJOR", "MINOR", "OBSERVATION")


@bp.post("/certificates")
@guard(["ShopAdmin"])
def create_certificate(ctx):
    body = validation.body()
    cert_number = validation.string_field(body, "cert_number")
    scope_codes = validation.string_array_field(body, "scope_codes", non_empty=True,
                                                distinct=True, allowed=SCOPE_CODES)
    issued_on = validation.date_field(body, "issued_on")
    expires_on = validation.date_field(body, "expires_on")
    if expires_on <= issued_on:
        fail("ERR_INVALID_REQUEST", "Field 'expires_on' must fall strictly after 'issued_on'.")

    for certificate in db.all_of("certificates"):
        if certificate["cert_number"] == cert_number:
            fail("ERR_DUPLICATE_CERT_NUMBER",
                 "Certificate number '%s' already exists." % cert_number)

    record = db.insert("certificates", {
        "cert_number": cert_number,
        "scope_codes": scope_codes,
        "issued_on": db.iso_date(issued_on),
        "expires_on": db.iso_date(expires_on),
        "status": "ACTIVE",
        "open_major_findings_count": 0,
        "open_minor_findings_count": 0,
        "renewal_count": 0,
        "last_audit_closed_on": None,
        "stamping_authorized": True,
    })
    record["status"] = derive.certificate_status(record)
    record["stamping_authorized"] = derive.certificate_authorized(record)
    return common.created("certificates", record)


@bp.get("/certificates/<certificate_id>")
@guard(ALL_ROLES)
def get_certificate(ctx, certificate_id):
    return common.one("certificates", common.must_exist("certificates", certificate_id))


@bp.get("/certificates")
@guard(ALL_ROLES)
def list_certificates(ctx):
    return common.listing("certificates", ["status", "cert_number"],
                          {"status": derive.certificate_status})


@bp.post("/certificates/<certificate_id>/renewals")
@guard(["ShopAdmin"])
def renew_certificate(ctx, certificate_id):
    body = validation.body()
    expected_version = validation.int_field(body, "expected_certificate_version")
    renewal_audit_id = validation.string_field(body, "renewal_audit_id")
    new_expires_on = validation.date_field(body, "new_expires_on")

    certificate = common.must_exist("certificates", certificate_id)
    audit = db.get("audits", renewal_audit_id)
    if audit is None:
        fail("ERR_AUDIT_NOT_FOUND", "No such audit: %s." % renewal_audit_id)

    if expected_version != certificate["version"]:
        fail("ERR_STALE_CERTIFICATE_VERSION",
             "The certificate has moved on since version %s." % expected_version)

    status = derive.certificate_status(certificate)
    if status not in ("PROBATION", "SUSPENDED", "EXPIRED"):
        fail("ERR_INVALID_CERTIFICATE_STATE",
             "Renewal is not declared out of %s." % status)

    if (audit["certificate_id"] != certificate_id
            or audit["status"] != "CLOSED"
            or not audit["satisfactory"]):
        fail("ERR_RENEWAL_AUDIT_NOT_SATISFACTORY",
             "The renewal audit must be a satisfactory closed audit of this certificate.")

    if status in ("PROBATION", "EXPIRED") and new_expires_on <= db.clock_today():
        fail("ERR_INVALID_CERTIFICATE_STATE",
             "Field 'new_expires_on' must fall strictly after the current logical UTC date.")

    changes = {
        "expires_on": db.iso_date(new_expires_on),
        "open_major_findings_count": 0,
        "open_minor_findings_count": 0,
        "renewal_count": certificate["renewal_count"] + 1,
    }
    for key, value in changes.items():
        certificate[key] = value
    certificate["status"] = derive.certificate_status(certificate)
    certificate["stamping_authorized"] = derive.certificate_authorized(certificate)
    db.touch(certificate)

    derive.sync_certificate_reports(certificate)
    return common.one("certificates", certificate)


@bp.post("/shop-audits")
@guard(["ShopAdmin"])
def create_audit(ctx):
    body = validation.body()
    certificate_id = validation.string_field(body, "certificate_id")
    audit_type = validation.enum_field(body, "audit_type", AUDIT_TYPES)
    scheduled_date = validation.date_field(body, "scheduled_date")

    if db.get("certificates", certificate_id) is None:
        fail("ERR_CERTIFICATE_NOT_FOUND", "No such certificate: %s." % certificate_id)

    record = db.insert("audits", {
        "certificate_id": certificate_id,
        "audit_type": audit_type,
        "scheduled_date": db.iso_date(scheduled_date),
        "closed_on": None,
        "findings": [],
        "major_finding_count": 0,
        "minor_finding_count": 0,
        "satisfactory": False,
        "status": "SCHEDULED",
    })
    return common.created("audits", record)


@bp.get("/shop-audits/<audit_id>")
@guard(ALL_ROLES)
def get_audit(ctx, audit_id):
    return common.one("audits", common.must_exist("audits", audit_id))


@bp.get("/shop-audits")
@guard(ALL_ROLES)
def list_audits(ctx):
    return common.listing("audits", ["certificate_id", "status", "audit_type"])


@bp.post("/shop-audits/<audit_id>/close")
@guard(["ShopAdmin"])
def close_audit(ctx, audit_id):
    body = validation.body()
    closed_on = validation.date_field(body, "closed_on")
    findings = validation.object_array_field(body, "findings")
    normalised = []
    for entry in findings:
        finding_code = validation.string_field(entry, "finding_code")
        severity = validation.enum_field(entry, "severity", SEVERITIES)
        clause_reference = validation.string_field(entry, "clause_reference")
        normalised.append({
            "finding_code": finding_code,
            "severity": severity,
            "clause_reference": clause_reference,
        })

    audit = common.must_exist("audits", audit_id)
    if audit["status"] != "SCHEDULED":
        fail("ERR_INVALID_AUDIT_STATE", "Only a SCHEDULED audit may be closed.")
    if closed_on < calc.parse_date(audit["scheduled_date"]):
        fail("ERR_INVALID_AUDIT_STATE",
             "Field 'closed_on' must be on or after 'scheduled_date'.")

    major = len([f for f in normalised if f["severity"] == "MAJOR"])
    minor = len([f for f in normalised if f["severity"] == "MINOR"])
    db.mutate(audit, {
        "closed_on": db.iso_date(closed_on),
        "findings": normalised,
        "major_finding_count": major,
        "minor_finding_count": minor,
        "satisfactory": major == 0 and minor <= 5,
        "status": "CLOSED",
    })

    certificate = db.get("certificates", audit["certificate_id"])
    if certificate is not None:
        certificate["open_major_findings_count"] += major
        certificate["open_minor_findings_count"] += minor
        certificate["last_audit_closed_on"] = derive.last_audit_closed_on(certificate["id"])
        certificate["status"] = derive.certificate_status(certificate)
        certificate["stamping_authorized"] = derive.certificate_authorized(certificate)
        db.touch(certificate)
        derive.sync_certificate_reports(certificate)

    return common.one("audits", audit)
