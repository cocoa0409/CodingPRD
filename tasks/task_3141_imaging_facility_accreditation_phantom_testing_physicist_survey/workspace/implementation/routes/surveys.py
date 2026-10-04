"""PhysicistSurvey endpoints (PRD §3.5, §4)."""

from decimal import Decimal

import flask

import db
import response
from errors import fail
from middleware import require
from services import calculations, common


def _effective_performed(survey):
    return survey.get("performed_at") or survey.get("scheduled_at")


def _window_conflict(facility_id, candidate_at):
    """[candidate, candidate + 1 day) disjoint from every non-REJECTED survey,
    and candidate at or after the stored instant of every such survey."""
    candidate = db.parse_ts(candidate_at)
    candidate_end = db.add_days(candidate, 1)
    for other in common.facility_surveys(facility_id):
        if other["survey_status"] == "REJECTED":
            continue
        stored = _effective_performed(other)
        if stored is None:
            continue
        stored = db.parse_ts(stored)
        stored_end = db.add_days(stored, 1)
        if candidate < stored_end and stored < candidate_end:
            return True
        if candidate < stored:
            return True
    return False


def _acting_survey_owned_by_principal(principal, survey):
    if principal.role == "MedicalPhysicist" and survey["physicist_qualification_id"] != principal.user_id:
        fail("ERR_UNAUTHORIZED", "the acting physicist is not the survey's signatory")


def _signatory(survey):
    return db.QUALIFICATIONS.get(survey["physicist_qualification_id"])


def register_routes(app):

    @app.route("/accreditation/physicist-surveys", methods=["POST"])
    @require(["MedicalPhysicist"])
    def schedule_survey(principal):
        payload = common.body()
        common.require_fields(
            payload,
            ["facility_id", "physicist_qualification_id", "survey_type",
             "scheduled_at", "reference_entrance_dose_mgy"],
        )
        common.check_required_enum(payload, "survey_type", "survey_type")
        facility = common.get_facility(payload["facility_id"])

        qualification_id = payload["physicist_qualification_id"]
        qualification = db.QUALIFICATIONS.get(qualification_id)
        if qualification is None:
            fail("ERR_SURVEY_NOT_FOUND", "the named physicist qualification does not resolve")

        unit_id = payload.get("unit_id")
        if unit_id is not None:
            common.get_unit(unit_id, facility["id"])

        if _window_conflict(facility["id"], payload["scheduled_at"]):
            fail("ERR_SURVEY_WINDOW_CONFLICT", "the survey window overlaps an existing survey")

        survey = common.make_record(
            id=db.new_id(),
            facility_id=facility["id"],
            physicist_qualification_id=qualification_id,
            survey_type=payload["survey_type"],
            scheduled_at=db.as_ts(payload["scheduled_at"]),
            performed_at=None,
            reference_entrance_dose_mgy=Decimal(str(payload["reference_entrance_dose_mgy"])),
            measured_entrance_dose_mgy=None,
            shielding_verdict=None,
            dose_deviation_pct=None,
            survey_status="SCHEDULED",
            rejection_code="NONE",
            unit_id=unit_id,
        )
        db.SURVEYS[survey["id"]] = survey
        return response.ok(common.serialize(survey), 201)

    @app.route("/accreditation/physicist-surveys", methods=["GET"])
    @require(["Any"])
    def list_surveys(principal):
        rows = list(db.SURVEYS.values())
        for field in ("facility_id", "physicist_qualification_id", "unit_id", "survey_status"):
            wanted = flask.request.args.get(field)
            if wanted:
                rows = [r for r in rows if r.get(field) == wanted]
        rows.sort(key=lambda r: r["created_at"])
        page, meta = response.paginate(rows, flask.request.args)
        return response.ok(common.serialize_many(page), 200, meta)

    @app.route("/accreditation/physicist-surveys/<survey_id>", methods=["GET"])
    @require(["Any"])
    def read_survey(principal, survey_id):
        return response.ok(common.serialize(common.get_survey(survey_id)))

    @app.route("/accreditation/physicist-surveys/<survey_id>/submit", methods=["POST"])
    @require(["MedicalPhysicist"])
    def submit_survey(principal, survey_id):
        survey = common.get_survey(survey_id)
        _acting_survey_owned_by_principal(principal, survey)
        payload = common.body()
        common.require_fields(payload, ["performed_at", "measured_entrance_dose_mgy", "shielding_verdict"])
        common.check_required_enum(payload, "shielding_verdict", "shielding_verdict")

        if survey["survey_status"] in ("ACCEPTED", "REJECTED"):
            fail("ERR_ALREADY_TERMINAL", "the survey has already reached a terminal state")
        if survey["survey_status"] != "SCHEDULED":
            fail("ERR_INVALID_STATE", "the survey is not SCHEDULED")

        qualification = _signatory(survey)
        facility = db.FACILITIES.get(survey["facility_id"])

        if qualification is not None and qualification["credential_status"] == "REVOKED":
            fail("ERR_CREDENTIAL_REVOKED", "the acting physicist's credential has been revoked")
        if facility is not None:
            common.recompute_roster_disposition(facility)
            if facility["roster_disposition"] == "HALT":
                fail("ERR_ROSTER_INELIGIBLE", "the facility's roster disposition is HALT")

        performed_at = db.parse_ts(payload["performed_at"])
        cycle = common.current_cycle(facility) if facility is not None else None
        if cycle is not None:
            if performed_at < db.parse_ts(cycle["cycle_started_at"]):
                fail("ERR_INVALID_STATE", "performed_at precedes the current cycle")
        if qualification is not None:
            expires_on = db.parse_ts(qualification["credential_expires_on"])
            if expires_on is not None and not performed_at < expires_on:
                fail("ERR_INVALID_STATE", "performed_at is not before the credential expiry")

        survey["performed_at"] = db.as_ts(payload["performed_at"])
        survey["measured_entrance_dose_mgy"] = Decimal(str(payload["measured_entrance_dose_mgy"]))
        survey["shielding_verdict"] = payload["shielding_verdict"]
        deviation = calculations.survey_dose_deviation(
            survey["reference_entrance_dose_mgy"], survey["measured_entrance_dose_mgy"]
        )
        survey["dose_deviation_pct"] = deviation

        stamp = db.now()
        if qualification is not None and qualification["credential_status"] == "LAPSED":
            common.set_field(survey, "survey_status", "REJECTED", stamp)
            survey["rejection_code"] = "CREDENTIAL_LAPSED"
            if facility is not None:
                facility["registry_credit_cents"] = facility["registry_credit_cents"] + 100000
                common.recompute_rejected_survey_count(facility)
                common.touch(facility, stamp)
            return response.ok(common.serialize(survey))

        common.set_field(survey, "survey_status", "SUBMITTED", stamp)
        return response.ok(common.serialize(survey))

    @app.route("/accreditation/physicist-surveys/<survey_id>/accept", methods=["POST"])
    @require(["AccreditationBody"])
    def accept_survey(principal, survey_id):
        survey = common.get_survey(survey_id)

        if survey["survey_status"] in ("ACCEPTED", "REJECTED"):
            fail("ERR_ALREADY_TERMINAL", "the survey has already reached a terminal state")
        if survey["survey_status"] not in ("SUBMITTED", "RESUBMITTED"):
            fail("ERR_INVALID_STATE", "the survey is not SUBMITTED or RESUBMITTED")

        facility = db.FACILITIES.get(survey["facility_id"])
        qualification = _signatory(survey)
        deviation = Decimal(str(survey["dose_deviation_pct"])) if survey["dose_deviation_pct"] is not None else Decimal("0")

        if facility is not None and common.clinical_role_qualifications_unverified(facility["id"]):
            fail("ERR_QUALIFICATION_UNVERIFIED", "a clinical-role qualification is not VERIFIED")

        stamp = db.now()
        if survey["shielding_verdict"] == "PASS" and abs(deviation) <= calculations.ABSOLUTE_DEVIATION_LIMIT_PCT:
            common.set_field(survey, "survey_status", "ACCEPTED", stamp)
            _apply_acceptance(survey, facility, qualification, deviation, stamp)
            return response.ok(common.serialize(survey))

        common.set_field(survey, "survey_status", "CORRECTIVE_REQUIRED", stamp)
        survey["rejection_code"] = (
            "DOSE_OUT_OF_RANGE"
            if abs(deviation) > calculations.ABSOLUTE_DEVIATION_LIMIT_PCT
            else "SHIELDING_FAILED"
        )
        if facility is not None:
            # a corrective-required survey never promotes a facility
            facility["accreditation_currency"] = "PROVISIONAL"
            common.touch(facility, stamp)
        return response.ok(common.serialize(survey))

    @app.route("/accreditation/physicist-surveys/<survey_id>/reject", methods=["POST"])
    @require(["AccreditationBody"])
    def reject_survey(principal, survey_id):
        survey = common.get_survey(survey_id)

        if survey["survey_status"] in ("ACCEPTED", "REJECTED"):
            fail("ERR_ALREADY_TERMINAL", "the survey has already reached a terminal state")
        if survey["survey_status"] == "SUBMITTED":
            pass
        elif survey["survey_status"] == "CORRECTIVE_REQUIRED":
            deviation = Decimal(str(survey["dose_deviation_pct"])) if survey["dose_deviation_pct"] is not None else Decimal("0")
            if not (survey["shielding_verdict"] == "FAIL"
                    or abs(deviation) > calculations.ABSOLUTE_DEVIATION_LIMIT_PCT):
                fail("ERR_INVALID_STATE", "the survey is no longer rejectable")
        else:
            fail("ERR_INVALID_STATE", "the survey is not SUBMITTED or CORRECTIVE_REQUIRED")

        facility = db.FACILITIES.get(survey["facility_id"])
        deviation = Decimal(str(survey["dose_deviation_pct"])) if survey["dose_deviation_pct"] is not None else Decimal("0")
        was_corrective = survey["survey_status"] == "CORRECTIVE_REQUIRED"

        stamp = db.now()
        common.set_field(survey, "survey_status", "REJECTED", stamp)
        survey["rejection_code"] = (
            "DOSE_OUT_OF_RANGE"
            if abs(deviation) > calculations.ABSOLUTE_DEVIATION_LIMIT_PCT
            else "SHIELDING_FAILED"
        )
        if facility is not None:
            facility["registry_credit_cents"] = facility["registry_credit_cents"] + 100000
            common.recompute_rejected_survey_count(facility)
            if was_corrective:
                facility["accreditation_currency"] = "PROVISIONAL"
            common.touch(facility, stamp)
        return response.ok(common.serialize(survey))

    @app.route("/accreditation/physicist-surveys/<survey_id>/resubmit", methods=["POST"])
    @require(["MedicalPhysicist"])
    def resubmit_survey(principal, survey_id):
        survey = common.get_survey(survey_id)
        _acting_survey_owned_by_principal(principal, survey)
        payload = common.body()
        common.require_fields(payload, ["measured_entrance_dose_mgy", "shielding_verdict"])
        common.check_required_enum(payload, "shielding_verdict", "shielding_verdict")

        if survey["survey_status"] in ("ACCEPTED", "REJECTED"):
            fail("ERR_ALREADY_TERMINAL", "the survey has already reached a terminal state")
        if survey["survey_status"] != "CORRECTIVE_REQUIRED":
            fail("ERR_INVALID_STATE", "the survey is not CORRECTIVE_REQUIRED")

        qualification = _signatory(survey)
        facility = db.FACILITIES.get(survey["facility_id"])

        if qualification is not None and qualification["credential_status"] == "REVOKED":
            fail("ERR_CREDENTIAL_REVOKED", "the acting physicist's credential has been revoked")
        if facility is not None:
            common.recompute_roster_disposition(facility)
            if facility["roster_disposition"] == "HALT":
                fail("ERR_ROSTER_INELIGIBLE", "the facility's roster disposition is HALT")

        if payload["shielding_verdict"] != "PASS":
            fail("ERR_SHIELDING_FAILED", "shielding_verdict must be PASS")

        measured = Decimal(str(payload["measured_entrance_dose_mgy"]))
        deviation = calculations.survey_dose_deviation(survey["reference_entrance_dose_mgy"], measured)
        if abs(deviation) > calculations.ABSOLUTE_DEVIATION_LIMIT_PCT:
            fail("ERR_SHIELDING_FAILED", "the recomputed dose deviation exceeds the limit")

        if facility is not None and facility["registry_credit_cents"] < 100000:
            fail("ERR_INSUFFICIENT_REGISTRY_CREDIT", "registry credit does not cover the resubmission fee")

        stamp = db.now()
        if facility is not None:
            facility["registry_credit_cents"] = facility["registry_credit_cents"] - 100000
            common.touch(facility, stamp)
        survey["measured_entrance_dose_mgy"] = measured
        survey["shielding_verdict"] = "PASS"
        survey["dose_deviation_pct"] = deviation
        survey["rejection_code"] = "NONE"
        common.set_field(survey, "survey_status", "RESUBMITTED", stamp)
        return response.ok(common.serialize(survey))


def _apply_acceptance(survey, facility, qualification, deviation, stamp):
    if qualification is not None:
        common.recompute_survey_count(qualification)
        common.touch(qualification, stamp)
        if abs(deviation) <= Decimal("8.0"):
            qualification["credential_status"] = "VERIFIED"
            common.touch(qualification, stamp)

    unit_id = survey.get("unit_id")
    if unit_id is not None:
        for item in common.unit_equipment(unit_id):
            item["performance_verdict"] = "PASS"
            common.touch(item, stamp)
        unit = db.MODALITY_UNITS.get(unit_id)
        if unit is not None:
            unit["last_survey_at"] = survey["performed_at"]
            common.touch(unit, stamp)
    elif facility is not None:
        for unit in common.facility_units(facility["id"]):
            unit["last_survey_at"] = survey["performed_at"]
            common.touch(unit, stamp)

    if facility is not None:
        facility["rejected_survey_count"] = 0
        facility["accreditation_currency"] = "CURRENT"
        common.touch(facility, stamp)