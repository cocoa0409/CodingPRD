"""PersonnelQualification endpoints (PRD §3.8, §4)."""

from decimal import Decimal

import flask

import db
import response
from errors import fail
from middleware import require
from services import cascades, common


def register_routes(app):

    @app.route("/accreditation/qualifications", methods=["POST"])
    @require(["AccreditationBody"])
    def create_qualification(principal):
        payload = common.body()
        common.require_fields(
            payload,
            ["facility_id", "person_name", "personnel_role", "credential_number",
             "ce_credit_hours", "required_ce_hours", "credential_expires_on"],
        )
        common.check_required_enum(payload, "personnel_role", "personnel_role")
        facility = common.get_facility(payload["facility_id"])

        credential_number = payload["credential_number"]
        if any(q["credential_number"] == credential_number for q in db.QUALIFICATIONS.values()):
            fail("ERR_CREDENTIAL_NUMBER_DUPLICATE", "credential_number is already registered")

        qualification = common.make_record(
            id=db.new_id(),
            facility_id=facility["id"],
            person_name=payload["person_name"],
            personnel_role=payload["personnel_role"],
            credential_number=credential_number,
            ce_credit_hours=Decimal(str(payload["ce_credit_hours"])),
            required_ce_hours=Decimal(str(payload["required_ce_hours"])),
            credential_expires_on=db.parse_ts(payload["credential_expires_on"]),
            credential_status="PENDING",
            qualification_verified_at=None,
            survey_count=0,
        )
        db.QUALIFICATIONS[qualification["id"]] = qualification
        common.recompute_roster_disposition(facility)
        return response.ok(common.serialize(qualification), 201)

    @app.route("/accreditation/qualifications", methods=["GET"])
    @require(["Any"])
    def list_qualifications(principal):
        rows = list(db.QUALIFICATIONS.values())
        for field in ("facility_id", "personnel_role", "credential_status"):
            wanted = flask.request.args.get(field)
            if wanted:
                rows = [r for r in rows if r.get(field) == wanted]
        rows.sort(key=lambda r: r["created_at"])
        page, meta = response.paginate(rows, flask.request.args)
        return response.ok(common.serialize_many(page), 200, meta)

    @app.route("/accreditation/qualifications/<qualification_id>", methods=["GET"])
    @require(["Any"])
    def read_qualification(principal, qualification_id):
        return response.ok(common.serialize(common.get_qualification(qualification_id)))

    @app.route("/accreditation/qualifications/<qualification_id>/verify", methods=["POST"])
    @require(["AccreditationBody"])
    def verify_qualification(principal, qualification_id):
        qualification = common.get_qualification(qualification_id)
        payload = common.body()
        common.require_fields(payload, ["verified_at"])

        if qualification["credential_status"] == "REVOKED":
            fail("ERR_ALREADY_TERMINAL", "the qualification has been revoked")
        if qualification["credential_status"] == "VERIFIED":
            fail("ERR_INVALID_STATE", "the qualification is already VERIFIED")

        if Decimal(str(qualification["ce_credit_hours"])) < Decimal(str(qualification["required_ce_hours"])):
            fail("ERR_CE_HOURS_SHORTFALL", "ce_credit_hours is below required_ce_hours")

        verified_at = db.parse_ts(payload["verified_at"])
        expires_on = db.parse_ts(qualification["credential_expires_on"])
        if not (expires_on is not None and expires_on > verified_at):
            fail("ERR_INVALID_REQUEST", "credential_expires_on must fall after verified_at")

        stamp = db.now()
        common.set_field(qualification, "credential_status", "VERIFIED", stamp)
        qualification["qualification_verified_at"] = verified_at
        facility = db.FACILITIES.get(qualification["facility_id"])
        if facility is not None:
            common.recompute_roster_disposition(facility)
        return response.ok(common.serialize(qualification))

    @app.route("/accreditation/qualifications/<qualification_id>/revoke", methods=["POST"])
    @require(["AccreditationBody"])
    def revoke_qualification(principal, qualification_id):
        qualification = common.get_qualification(qualification_id)
        leaving = qualification["credential_status"]

        if leaving == "REVOKED":
            fail("ERR_ALREADY_TERMINAL", "the qualification has already been revoked")

        facility = db.FACILITIES.get(qualification["facility_id"])
        if facility is not None and leaving == "VERIFIED":
            submitted = [
                s for s in common.facility_surveys(facility["id"])
                if s["physicist_qualification_id"] == qualification["id"]
                and s["survey_status"] == "SUBMITTED"
            ]
            if submitted:
                fail("ERR_INVALID_STATE", "a submitted survey must be adjudicated first")

        stamp = db.now()
        if leaving in ("PENDING", "LAPSED"):
            cascades.reject_qualification_surveys(
                qualification, ("SCHEDULED", "SUBMITTED", "CORRECTIVE_REQUIRED"), stamp
            )
            if facility is not None:
                cascades.expire_plans(facility, only_open=True, stamp=stamp)
        else:
            cascades.reject_qualification_surveys(
                qualification, ("SCHEDULED", "CORRECTIVE_REQUIRED"), stamp
            )

        common.set_field(qualification, "credential_status", "REVOKED", stamp)
        if facility is not None:
            common.recompute_rejected_survey_count(facility)
            common.recompute_roster_disposition(facility)
            for unit in common.facility_units(facility["id"]):
                common.recompute_deficiency_open_count(unit)
        return response.ok(common.serialize(qualification))