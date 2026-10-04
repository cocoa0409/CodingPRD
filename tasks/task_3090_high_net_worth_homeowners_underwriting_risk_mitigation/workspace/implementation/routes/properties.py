"""Dwellings, appraisals and the valuation ledger (PRD §3.1, §3.5)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import db
import reqs
from clock import fmt_dt, parse_dt
from errors import err
from middleware import authorize, require_agency_of_record
from response import array, ok, paginate
from serialize import render, render_list
from services import core

bp = Blueprint("properties", __name__)

PROPERTY_READERS = ("Underwriter", "AgencyProducer", "ClaimsAdjuster", "RiskConsultant",
                    "PlatformAdmin", "ComplianceReporter")
APPRAISAL_READERS = ("Underwriter", "AgencyProducer", "ClaimsAdjuster", "PlatformAdmin",
                     "ComplianceReporter", "RiskConsultant")
BASE_POSTURES = ("PENDING_APPRAISAL", "MITIGATION_REQUIRED", "UNDERWRITABLE", "DECLINED")
POSTURES = ("WRITE_FROZEN", "REFERRAL_REQUIRED", "WRITE_ELIGIBLE")
VALUATION_METHODS = ("SITE_MEASURED", "DESKTOP_ESTIMATE", "DRIVE_BY")
REVIEW_KINDS = ("FULL_APPRAISAL", "VALUATION_PROVISION")


def common_fields():
    now = fmt_dt(db.now())
    return {"id": db.new_id(), "created_at": now, "updated_at": now, "version": 1}


def _paginate(rows, limit, offset):
    return paginate(rows, limit, offset)


# --------------------------------------------------------------------------
# properties
# --------------------------------------------------------------------------
@bp.route("/hnw/properties", methods=["POST"])
def create_property():
    authorize(("Underwriter",))
    data = reqs.body()
    zone = core.get(db.ZONES, reqs.string(data, "risk_zone_id", required=True), "RiskZone")
    core.get(db.AGENCIES, reqs.string(data, "agency_id", required=True), "Agency")
    record = common_fields()
    record.update({
        "risk_zone_id": zone["id"],
        "agency_id": data["agency_id"],
        "address_line": reqs.string(data, "address_line", required=True),
        "grid_risk_block": reqs.string(data, "grid_risk_block", default="UNGROUPED"),
        "dwelling_replacement_cost_cents": 0,
        "contents_replacement_cost_cents": 0,
        "scheduled_valuation_cents": 0,
        "appraised_at": None,
        "total_insured_value_cents": 0,
        "mitigation_band": "UNVERIFIED",
        "base_posture": "PENDING_APPRAISAL",
        "posture": "WRITE_FROZEN",
        "defense_in_progress": False,
        "non_renewal_ground_activated": False,
    })
    record["posture"] = core.derive_posture(record)
    db.PROPERTIES[record["id"]] = record
    return ok(render(record), status=201)


@bp.route("/hnw/properties", methods=["GET"])
def list_properties():
    authorize(PROPERTY_READERS)
    limit, offset = reqs.pagination()
    rows = list(db.PROPERTIES.values())
    for field in ("risk_zone_id", "agency_id", "base_posture", "posture", "grid_risk_block"):
        value = reqs.query(field)
        if value:
            rows = [p for p in rows if p.get(field) == value]
    rows = reqs.sorted_by_created(rows)
    page, meta = _paginate(rows, limit, offset)
    return array(render_list(page), meta)


@bp.route("/hnw/properties/<property_id>", methods=["GET"])
def read_property(property_id):
    authorize(PROPERTY_READERS)
    prop = core.get(db.PROPERTIES, property_id, "Property")
    return ok(render(prop))


@bp.route("/hnw/properties/<property_id>/posture-eval", methods=["POST"])
def posture_eval(property_id):
    authorize(("Underwriter",))
    prop = core.get(db.PROPERTIES, property_id, "Property")
    if prop["base_posture"] == "DECLINED":
        raise err("ERR_INVALID_STATE",
                  "DECLINED is terminal for a property; it must be reopened first.")
    data = reqs.body()
    expected = reqs.integer(data, "expected_property_version", required=True)
    if expected != prop["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_property_version does not match the current Property.version.")
    _evaluate_gate(prop)
    return ok(render(prop))


def _evaluate_gate(prop):
    """The ordered gate (PRD §3.5).  Guarantee-ratio test runs FIRST."""
    property_id = prop["id"]
    approved = [a for a in db.APPRAISALS.values()
                if a["property_id"] == property_id and a["status"] == "APPROVED"]
    if not approved:
        raise err("ERR_INVALID_STATE",
                  "The property has no approved appraisal to evaluate.")
    latest = core.latest_valuation_row(property_id)
    if latest is None:
        raise err("ERR_INVALID_STATE",
                  "The property has no appraised valuation to evaluate.")
    current_rc = prop["dwelling_replacement_cost_cents"]
    # The 1.50 guarantee ratio: the carried valuation must still cover the
    # dwelling valuation that now stands on the books.
    ratio_ok = (Decimal(latest["dwelling_cost_cents"]) * calc.GUARANTEE_RATIO
                >= Decimal(current_rc))
    if not ratio_ok:
        prop["appraised_at"] = latest["appraised_on"]
        prop["base_posture"] = "DECLINED"
        prop["posture"] = "WRITE_FROZEN"
        core.touch(prop)
        core.push_draft_or_submitted_to_declined(property_id)
        return prop
    if not any(a["valuation_method"] == "SITE_MEASURED" for a in approved):
        raise err("ERR_INVALID_STATE",
                  "No approved appraisal was produced by a site measurement.")
    prop["base_posture"] = "UNDERWRITABLE"
    prop["appraised_at"] = latest["appraised_on"]
    core.touch(prop)
    zone = db.ZONES.get(prop["risk_zone_id"])
    band = calc.mitigation_band(property_id)
    if (band != "CLEARED" and zone is not None
            and zone["exposure_band"] == "EXTREME"
            and zone["wildland_urban_interface_band"] in ("WITHIN_WUI", "ADJACENT_WUI")):
        _impose_requirement(prop, "DEFENSIBLE_SPACE", "PARTIAL", "UNDERWRITING",
                            latest["appraised_on"], auto=True)
    core.recompute_property(property_id)
    return prop


def _impose_requirement(prop, requirement_code, band_awarded, source, due_on, auto=False):
    """Auto-imposition spawns the lifecycle the requirement endpoint owns."""
    return core.attach_requirement(prop, requirement_code, band_awarded, source, due_on)


@bp.route("/hnw/properties/<property_id>/reopen", methods=["POST"])
def reopen_property(property_id):
    authorize(("Underwriter",))
    prop = core.get(db.PROPERTIES, property_id, "Property")
    reqs.body()
    if prop["base_posture"] != "DECLINED":
        raise err("ERR_INVALID_STATE", "Only a DECLINED property may be reopened.")
    zone = db.ZONES.get(prop["risk_zone_id"])
    if zone is not None and Decimal(str(zone["mitigated_loss_multiplier"])) > Decimal("1.00"):
        raise err("ERR_BRANCH_CAPITAL_INSUFFICIENT",
                  "The branch of record has not been capitalised.")
    prop["base_posture"] = _derive_base_posture(prop)
    core.touch(prop)
    core.recompute_property(property_id)
    return ok(render(prop))


def _derive_base_posture(prop):
    property_id = prop["id"]
    approved = [a for a in db.APPRAISALS.values()
                if a["property_id"] == property_id and a["status"] == "APPROVED"]
    # PRD §3.5: funding the gate needs an APPROVED row and a SITE_MEASURED one.
    if not approved:
        return "PENDING_APPRAISAL"
    if not any(a["valuation_method"] == "SITE_MEASURED" for a in approved):
        return "PENDING_APPRAISAL"
    if not core.approved_appraisals_in_currency(property_id):
        return "PENDING_APPRAISAL"
    if any(r["status"] == "IMPOSED" for r in db.MITIGATION_REQUIREMENTS.values()
           if r["property_id"] == property_id):
        return "MITIGATION_REQUIRED"
    return "UNDERWRITABLE"


# --------------------------------------------------------------------------
# appraisals
# --------------------------------------------------------------------------
@bp.route("/hnw/properties/<property_id>/appraisals", methods=["POST"])
def create_appraisal(property_id):
    authorize(("Underwriter",))
    prop = core.get(db.PROPERTIES, property_id, "Property")
    data = reqs.body()
    record = common_fields()
    record.update({
        "property_id": prop["id"],
        "appraiser_name": reqs.string(data, "appraiser_name", required=True),
        "valuation_method": reqs.enum(data, "valuation_method", VALUATION_METHODS),
        "appraised_on": parse_dt(reqs.require(data, "appraised_on")),
        "dwelling_cost_cents": reqs.integer(data, "dwelling_cost_cents", required=True,
                                            minimum=0, strict_min=True),
        "contents_cost_cents": reqs.integer(data, "contents_cost_cents", default=0, minimum=0),
        "valuation_confidence_pct": reqs.number(data, "valuation_confidence_pct",
                                                required=True, minimum=0, strict_min=True,
                                                maximum=100),
        "percent_complete": Decimal("0.00"),
        "status": "PENDING_REVIEW",
        "review_kind": reqs.enum(data, "review_kind", REVIEW_KINDS,
                                 default="VALUATION_PROVISION", required=False),
    })
    if record["appraised_on"] is None:
        raise err("ERR_INVALID_REQUEST", "appraised_on must be an ISO 8601 instant.")
    db.APPRAISALS[record["id"]] = record
    return ok(render(record), status=201)


@bp.route("/hnw/properties/<property_id>/appraisals", methods=["GET"])
def list_property_appraisals(property_id):
    authorize(APPRAISAL_READERS)
    core.get(db.PROPERTIES, property_id, "Property")
    limit, offset = reqs.pagination()
    rows = [a for a in db.APPRAISALS.values() if a["property_id"] == property_id]
    status = reqs.query("status")
    method = reqs.query("valuation_method")
    if status:
        rows = [a for a in rows if a["status"] == status]
    if method:
        rows = [a for a in rows if a["valuation_method"] == method]
    rows = reqs.sorted_by_created(rows)
    page, meta = _paginate(rows, limit, offset)
    return array(render_list(page), meta)


@bp.route("/hnw/appraisals/<appraisal_id>", methods=["GET"])
def read_appraisal(appraisal_id):
    authorize(APPRAISAL_READERS)
    appraisal = core.get(db.APPRAISALS, appraisal_id, "Appraisal")
    return ok(render(appraisal))


def _transition_appraisal(appraisal_id, from_states, to_state, actor_roles):
    authorize(actor_roles)
    appraisal = core.get(db.APPRAISALS, appraisal_id, "Appraisal")
    if appraisal["status"] not in from_states:
        raise err("ERR_INVALID_STATE",
                  "Appraisal is not in a state from which this transition is declared.")
    appraisal["status"] = to_state
    core.touch(appraisal)
    return appraisal


@bp.route("/hnw/appraisals/<appraisal_id>/review", methods=["POST"])
def review_appraisal(appraisal_id):
    _transition_appraisal(appraisal_id, ("PENDING_REVIEW",), "REVIEWED", ("Underwriter",))
    return ok(render(db.APPRAISALS[appraisal_id]))


@bp.route("/hnw/appraisals/<appraisal_id>/approve", methods=["POST"])
def approve_appraisal(appraisal_id):
    authorize(("Underwriter",))
    appraisal = core.get(db.APPRAISALS, appraisal_id, "Appraisal")
    _require_state(appraisal, ("REVIEWED",))
    if appraisal["valuation_method"] != "SITE_MEASURED":
        raise err("ERR_APPRAISAL_METHOD_INVALID",
                  "Only a SITE_MEASURED appraisal may be approved outright.")
    _apply_approval(appraisal)
    return ok(render(appraisal))


@bp.route("/hnw/appraisals/<appraisal_id>/provision", methods=["POST"])
def provision_appraisal(appraisal_id):
    authorize(("Underwriter",))
    appraisal = core.get(db.APPRAISALS, appraisal_id, "Appraisal")
    _require_state(appraisal, ("REVIEWED",))
    prior = [a for a in db.APPRAISALS.values()
             if a["property_id"] == appraisal["property_id"]
             and a["status"] in ("APPROVED", "SUPERSEDED") and a["id"] != appraisal["id"]]
    if not prior:
        raise err("ERR_APPRAISAL_PROVISION_BASELINE",
                  "No prior approved or superseded appraisal exists as a baseline.")
    best = max(a["dwelling_cost_cents"] for a in prior)
    if Decimal(best) < calc.PROVISION_BASELINE_MULTIPLE * Decimal(appraisal["dwelling_cost_cents"]):
        raise err("ERR_APPRAISAL_PROVISION_BASELINE",
                  "The superseded baseline is below 1.25x the provision value.")
    _apply_approval(appraisal)
    return ok(render(appraisal))


def _apply_approval(appraisal):
    appraisal["percent_complete"] = Decimal("1.00")
    appraisal["status"] = "APPROVED"
    core.touch(appraisal)
    core.recompute_property(appraisal["property_id"])


def _require_state(record, states):
    if record["status"] not in states:
        raise err("ERR_INVALID_STATE",
                  "The resource is not in a state from which this transition is declared.")


def _require_no_valuation_in_flight(property_id):
    """The property never carries two valuations in flight (PRD §3.1)."""
    for appraisal in db.APPRAISALS.values():
        if appraisal["property_id"] != property_id:
            continue
        if appraisal["status"] in ("PENDING_REVIEW", "REVIEWED"):
            raise err("ERR_INVALID_STATE",
                      "Another appraisal of this property is in flight.")


@bp.route("/hnw/appraisals/<appraisal_id>/reject", methods=["POST"])
def reject_appraisal(appraisal_id):
    data = reqs.body()
    appraisal = _transition_appraisal(appraisal_id, ("PENDING_REVIEW", "REVIEWED"),
                                      "REJECTED", ("Underwriter",))
    if data.get("reason") is not None:
        reqs.string(data, "reason")
    core.recompute_property(appraisal["property_id"])
    return ok(render(appraisal))


@bp.route("/hnw/appraisals/<appraisal_id>/supersede", methods=["POST"])
def supersede_appraisal(appraisal_id):
    authorize(("Underwriter",))
    appraisal = core.get(db.APPRAISALS, appraisal_id, "Appraisal")
    _require_state(appraisal, ("REVIEWED",))
    if appraisal["valuation_method"] not in ("DESKTOP_ESTIMATE", "DRIVE_BY"):
        raise err("ERR_INVALID_STATE",
                  "Only a desktop estimate or a drive-by may be superseded.")
    appraisal["status"] = "SUPERSEDED"
    appraisal["percent_complete"] = Decimal("1.00")
    core.touch(appraisal)
    core.recompute_property(appraisal["property_id"])
    return ok(render(appraisal))


@bp.route("/hnw/appraisals/<appraisal_id>/withdraw", methods=["POST"])
def withdraw_appraisal(appraisal_id):
    authorize(("AgencyProducer",))
    appraisal = core.get(db.APPRAISALS, appraisal_id, "Appraisal")
    _require_state(appraisal, ("REVIEWED",))
    for enrollment in db.ENROLLMENTS.values():
        if enrollment["property_id"] == appraisal["property_id"] and enrollment["status"] in ("APPROVED", "ATTACHED"):
            raise err("ERR_INVALID_STATE",
                      "An enrollment of this property is APPROVED or ATTACHED.")
    appraisal["status"] = "WITHDRAWN"
    core.touch(appraisal)
    core.recompute_property(appraisal["property_id"])
    return ok(render(appraisal))


@bp.route("/hnw/properties/<property_id>/valuation/reappraise", methods=["POST"])
def reappraise(property_id):
    authorize(("Underwriter",))
    prop = core.get(db.PROPERTIES, property_id, "Property")
    data = reqs.body()
    target = core.get(db.APPRAISALS,
                      reqs.string(data, "appraisal_id", required=True), "Appraisal")
    if target["property_id"] != property_id:
        raise err("ERR_NOT_FOUND", "The appraisal does not belong to this property.")
    _require_state(target, ("APPROVED",))
    _require_no_valuation_in_flight(property_id)
    target["status"] = "REVIEWED"
    target["percent_complete"] = Decimal("0.00")
    core.touch(target)
    core.recompute_property(property_id)
    return ok(render(target))