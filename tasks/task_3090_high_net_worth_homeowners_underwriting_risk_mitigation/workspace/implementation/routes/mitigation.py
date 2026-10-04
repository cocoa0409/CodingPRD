"""Mitigation requirements and risk-consulting visits (PRD §3.3)."""

from decimal import Decimal

from datetime import timedelta

from flask import Blueprint

import calc
import db
import reqs
from clock import add_days, fmt_dt, parse_dt, whole_days_ago
from errors import err
from middleware import authorize
from response import array, ok, paginate
from serialize import render, render_list
from services import core

bp = Blueprint("mitigation", __name__)

REQUIREMENT_CODES = ("DEFENSIBLE_SPACE", "FIRE_RESISTANT_ROOF", "EMBER_VENT_SCREEN",
                     "EXTERIOR_IRRIGATION", "FULL_MITIGATION_PROGRAM")
BAND_AWARDED = ("CLEARED", "PARTIAL")
REQUIREMENT_SOURCES = ("UNDERWRITING", "RISK_CONSULTANT", "DEFENSE_FOLLOW_UP")
MITIGATION_READERS = ("Underwriter", "AgencyProducer", "ClaimsAdjuster", "RiskConsultant",
                      "PlatformAdmin")
CONSULTATION_READERS = ("Underwriter", "AgencyProducer", "ClaimsAdjuster", "RiskConsultant",
                        "PlatformAdmin")


def common_fields():
    now = fmt_dt(db.now())
    return {"id": db.new_id(), "created_at": now, "updated_at": now, "version": 1}


# --------------------------------------------------------------------------
# mitigation requirements
# --------------------------------------------------------------------------
@bp.route("/hnw/properties/<property_id>/mitigation-requirements", methods=["POST"])
def create_requirement(property_id):
    authorize(("RiskConsultant", "Underwriter"))
    prop = core.get(db.PROPERTIES, property_id, "Property")
    data = reqs.body()
    requirement = core.impose_requirement(
        prop,
        reqs.enum(data, "requirement_code", REQUIREMENT_CODES),
        reqs.enum(data, "band_awarded", BAND_AWARDED),
        reqs.enum(data, "source", REQUIREMENT_SOURCES),
        parse_dt(reqs.require(data, "due_on")),
    )
    if requirement["due_on"] is None:
        raise err("ERR_INVALID_REQUEST", "due_on must be an ISO 8601 instant.")
    return ok(render(requirement), status=201)


@bp.route("/hnw/properties/<property_id>/mitigation-requirements", methods=["GET"])
def list_requirements(property_id):
    authorize(MITIGATION_READERS)
    core.get(db.PROPERTIES, property_id, "Property")
    limit, offset = reqs.pagination()
    rows = [r for r in db.MITIGATION_REQUIREMENTS.values() if r["property_id"] == property_id]
    for field in ("status", "requirement_code", "source"):
        value = reqs.query(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)


@bp.route("/hnw/mitigation-requirements/<requirement_id>/verify", methods=["POST"])
def verify_requirement(requirement_id):
    authorize(("RiskConsultant",))
    requirement = core.get(db.MITIGATION_REQUIREMENTS, requirement_id, "MitigationRequirement")
    data = reqs.body()
    # A verification attempted after due_on is refused on the temporal basis,
    # which outranks the state check so an already-lapsed row still reports the
    # lapse rather than a bare state rejection (PRD §3.3).
    if requirement["due_on"] is not None and db.now() > requirement["due_on"]:
        raise err("ERR_MITIGATION_LAPSED",
                  "The requirement's due_on has already passed.")
    if requirement["status"] != "IMPOSED":
        raise err("ERR_INVALID_STATE",
                  "Only an IMPOSED requirement may be verified.")
    supplied = reqs.integer(data, "verification_count", default=None)
    # Compare-and-set on the verification count.
    if supplied is not None and supplied != requirement["verification_count"]:
        raise err("ERR_INVALID_STATE",
                  "The supplied verification_count no longer matches the stored count.")
    verified_band = reqs.enum(data, "verified_band", BAND_AWARDED)
    requirement["band_awarded"] = verified_band
    requirement["status"] = "VERIFIED"
    requirement["verified_on"] = fmt_dt(db.now())
    requirement["verification_count"] = requirement["verification_count"] + 1
    core.touch(requirement)
    property_id = requirement["property_id"]
    prop = core.recompute_property(property_id)
    if requirement["verification_count"] >= 2:
        core.record_managed_risk_event(requirement, "REPEAT_INSPECTION_NOTICE")
    if prop["base_posture"] == "MITIGATION_REQUIRED":
        prop["base_posture"] = _derive_base_posture(property_id)
        core.touch(prop)
    core.stamp_posture_if_changed(prop)
    return ok(render(requirement))


def _derive_base_posture(property_id):
    """The gate after a verification (PRD §3.5): the guarantee-ratio test still
    governs the result, so a property whose latest approved appraisal no longer
    satisfies the 1.50 ratio is DECLINED even after the last requirement clears.
    """
    approved = [a for a in db.APPRAISALS.values()
                if a["property_id"] == property_id and a["status"] == "APPROVED"]
    latest = core.latest_valuation_row(property_id)
    prop = db.PROPERTIES.get(property_id)
    if approved and latest is not None and prop is not None:
        if (Decimal(latest["dwelling_cost_cents"]) * calc.GUARANTEE_RATIO
                < Decimal(prop["dwelling_replacement_cost_cents"])):
            return "DECLINED"
    rows = [r for r in db.MITIGATION_REQUIREMENTS.values() if r["property_id"] == property_id]
    if any(r["status"] == "IMPOSED" for r in rows):
        return "MITIGATION_REQUIRED"
    # No open requirement remains.  If the dwelling's mitigation outcome is
    # FAILED (the last requirement lapsed or was waived) the gate closes for
    # good; otherwise the property is writable again on the strength of the
    # approval that carried it to UNDERWRITABLE in the first place.
    if calc.mitigation_band(property_id) == "FAILED":
        return "DECLINED"
    return "UNDERWRITABLE"


@bp.route("/hnw/mitigation-requirements/<requirement_id>/waive", methods=["POST"])
def waive_requirement(requirement_id):
    authorize(("Underwriter",))
    requirement = core.get(db.MITIGATION_REQUIREMENTS, requirement_id, "MitigationRequirement")
    if requirement["status"] != "IMPOSED":
        raise err("ERR_INVALID_STATE", "Only an IMPOSED requirement may be waived.")
    data = reqs.body()
    reqs.string(data, "reason", required=True)
    requirement["status"] = "WAIVED"
    core.touch(requirement)
    prop = core.recompute_property(requirement["property_id"])
    if core._all_requirements_closed(requirement["property_id"]) and prop["base_posture"] == "MITIGATION_REQUIRED":
        prop["base_posture"] = "DECLINED"
        prop["posture"] = "WRITE_FROZEN"
        core.touch(prop)
        core.push_draft_or_submitted_to_declined(requirement["property_id"])
    return ok(render(requirement))


@bp.route("/hnw/mitigation-requirements/<requirement_id>/reopen", methods=["POST"])
def reopen_requirement(requirement_id):
    authorize(("RiskConsultant",))
    requirement = core.get(db.MITIGATION_REQUIREMENTS, requirement_id, "MitigationRequirement")
    if requirement["status"] != "VERIFIED":
        raise err("ERR_INVALID_STATE", "Only a VERIFIED requirement may be reopened.")
    data = reqs.body()
    requirement["due_on"] = parse_dt(reqs.require(data, "due_on"))
    if requirement["due_on"] is None:
        raise err("ERR_INVALID_REQUEST", "due_on must be an ISO 8601 instant.")
    requirement["status"] = "IMPOSED"
    requirement["verified_on"] = None
    # verification_count is monotone and never decremented.
    core.touch(requirement)
    prop = core.recompute_property(requirement["property_id"])
    if prop["base_posture"] == "UNDERWRITABLE":
        prop["base_posture"] = "MITIGATION_REQUIRED"
        core.touch(prop)
    core.stamp_posture_if_changed(prop)
    return ok(render(requirement))


# --------------------------------------------------------------------------
# risk consultations
# --------------------------------------------------------------------------
@bp.route("/hnw/properties/<property_id>/risk-consultations", methods=["POST"])
def create_consultation(property_id):
    authorize(("AgencyProducer", "RiskConsultant"))
    prop = core.get(db.PROPERTIES, property_id, "Property")
    data = reqs.body()
    consultant_user_id = reqs.string(data, "consultant_user_id", required=True)
    scheduled_for = parse_dt(reqs.require(data, "scheduled_for"))
    duration = reqs.integer(data, "duration_minutes", required=True, minimum=0, strict_min=True)
    if scheduled_for is None:
        raise err("ERR_INVALID_REQUEST", "scheduled_for must be an ISO 8601 instant.")
    end = scheduled_for + timedelta(minutes=duration)
    for other in db.RISK_CONSULTATIONS.values():
        if other["consultant_user_id"] != consultant_user_id:
            continue
        if other["status"] == "CANCELLED":
            continue
        other_start = other["scheduled_for"]
        other_end = other_start + timedelta(minutes=other["duration_minutes"])
        # Half-open [start, end): touching endpoints are adjacent, not overlapping.
        if scheduled_for < other_end and other_start < end:
            raise err("ERR_CONSULTATION_SLOT_CONFLICT",
                      "The consultant already holds an overlapping appointment.")
    record = common_fields()
    record.update({
        "property_id": prop["id"],
        "consultant_user_id": consultant_user_id,
        "scheduled_for": scheduled_for,
        "duration_minutes": duration,
        "status": "SCHEDULED",
        "completed_at": None,
        "report_issued_at": None,
    })
    db.RISK_CONSULTATIONS[record["id"]] = record
    return ok(render(record), status=201)


@bp.route("/hnw/properties/<property_id>/risk-consultations", methods=["GET"])
def list_consultations(property_id):
    authorize(CONSULTATION_READERS)
    core.get(db.PROPERTIES, property_id, "Property")
    limit, offset = reqs.pagination()
    rows = [c for c in db.RISK_CONSULTATIONS.values() if c["property_id"] == property_id]
    status = reqs.query("status")
    if status:
        rows = [c for c in rows if c["status"] == status]
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)


@bp.route("/hnw/risk-consultations/<consultation_id>/complete", methods=["POST"])
def complete_consultation(consultation_id):
    authorize(("RiskConsultant",))
    consultation = core.get(db.RISK_CONSULTATIONS, consultation_id, "RiskConsultation")
    if consultation["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Only a SCHEDULED visit may be completed.")
    if db.now() < consultation["scheduled_for"]:
        raise err("ERR_INVALID_STATE", "The logical clock has not reached scheduled_for.")
    consultation["status"] = "COMPLETED"
    consultation["completed_at"] = fmt_dt(db.now())
    core.touch(consultation)
    return ok(render(consultation))


@bp.route("/hnw/risk-consultations/<consultation_id>/cancel", methods=["POST"])
def cancel_consultation(consultation_id):
    authorize(("AgencyProducer",))
    consultation = core.get(db.RISK_CONSULTATIONS, consultation_id, "RiskConsultation")
    if consultation["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Only a SCHEDULED visit may be cancelled.")
    if not db.now() < consultation["scheduled_for"]:
        raise err("ERR_INVALID_STATE", "The clock has already reached scheduled_for.")
    consultation["status"] = "CANCELLED"
    core.touch(consultation)
    return ok(render(consultation))


@bp.route("/hnw/risk-consultations/<consultation_id>/revisit", methods=["POST"])
def revisit_consultation(consultation_id):
    authorize(("RiskConsultant",))
    consultation = core.get(db.RISK_CONSULTATIONS, consultation_id, "RiskConsultation")
    if consultation["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "Only a COMPLETED visit may be recycled.")
    if consultation["report_issued_at"] is None:
        raise err("ERR_INVALID_STATE", "The visit produced no report to recycle.")
    data = reqs.body()
    scheduled_for = parse_dt(data.get("scheduled_for"))
    if scheduled_for is not None:
        consultation["scheduled_for"] = scheduled_for
    consultation["status"] = "SCHEDULED"
    consultation["completed_at"] = None
    consultation["report_issued_at"] = None
    core.touch(consultation)
    return ok(render(consultation))


@bp.route("/hnw/risk-consultations/<consultation_id>/report", methods=["POST"])
def issue_report(consultation_id):
    authorize(("RiskConsultant",))
    consultation = core.get(db.RISK_CONSULTATIONS, consultation_id, "RiskConsultation")
    data = reqs.body()
    prop = core.get(db.PROPERTIES, consultation["property_id"], "Property")
    requirement = core.impose_requirement(
        prop,
        reqs.enum(data, "requirement_code", REQUIREMENT_CODES),
        reqs.enum(data, "band_awarded", BAND_AWARDED),
        "RISK_CONSULTANT",
        parse_dt(reqs.require(data, "due_on")),
    )
    consultation["report_issued_at"] = fmt_dt(db.now())
    core.touch(consultation)
    result = {
        "consultation_id": consultation["id"],
        "mitigation_requirement_id": requirement["id"],
    }
    return ok(result)