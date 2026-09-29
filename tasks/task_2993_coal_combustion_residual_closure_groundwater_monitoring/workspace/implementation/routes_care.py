"""Post-closure cap inspections and the public operating record."""
from flask import Blueprint

import calc
import common
import derive
import envelope
import shape
import store
from errors import ApiError
from guards import authenticate, require_discipline, require_license_active
from shape import SHA256_RE, URI_RE

bp = Blueprint("care", __name__)

INSPECTION_SPEC = {
    "unit_id": {"t": "id", "req": True},
    "inspected_on": {"t": "date", "req": True},
    "erosion_severity": {"t": "enum", "req": True, "vals": ("NONE", "MINOR", "MAJOR")},
    "settlement_inches": {"t": "num", "req": True, "min": 0, "dp": 2},
    "vegetation_cover_pct": {"t": "num", "req": True, "min": 0, "max": 100, "dp": 2},
    "note": {"t": "str", "min": 1, "max": 500},
}


@bp.post("/ccr/cap-inspections")
def create_inspection():
    actor = authenticate(("ProfessionalEngineer",))
    data = shape.read_body(INSPECTION_SPEC)
    unit = common.get_unit(data["unit_id"])
    common.no_future_date(data["inspected_on"])
    require_license_active(actor)
    require_discipline(actor, common.D_CLOSURE_WORK)
    common.unit_state(unit, ("POST_CLOSURE_CARE",))
    record = dict(data)
    record["inspecting_professional_id"] = actor.user_id
    verdict, criteria = calc.cap_inspection_verdict(record)
    record["verdict"] = verdict
    record["deficient_criteria"] = criteria
    store.stamp_new(record, versioned=False)
    store.cap_inspections[record["id"]] = record
    if verdict == "DEFICIENT":
        unit["cap_integrity_state"] = "DEFICIENT"
        unit["cap_repair_due_date"] = store.add_days(
            data["inspected_on"], calc.CAP_REPAIR_WINDOW_DAYS)
        program = calc.unit_program(unit["id"])
        if program is not None and program["sampling_frequency"] != "QUARTERLY":
            program["sampling_frequency"] = "QUARTERLY"
            store.touch(program)
            derive.refresh_program(program)
    else:
        unit["cap_integrity_state"] = "ADEQUATE"
        unit["cap_repair_due_date"] = None
    store.touch(unit)
    common.settle(unit)
    return envelope.created(derive.inspection(record))


POSTING_SPEC = {
    "unit_id": {"t": "id", "req": True},
    "posting_type": {"t": "enum", "req": True,
                     "vals": ("ANNUAL_GW_REPORT", "STABILITY_ASSESSMENT",
                              "CLOSURE_PLAN", "SSI_NOTIFICATION",
                              "EXTENSION_DEMONSTRATION")},
    "posted_on": {"t": "date", "req": True},
    "document_uri": {"t": "str", "req": True, "min": 8, "max": 300, "re": URI_RE},
    "document_sha256": {"t": "str", "req": True, "min": 64, "max": 64,
                        "re": SHA256_RE},
    "community_meeting_held_on": {"t": "date"},
}


@bp.post("/ccr/public-postings")
def create_posting():
    actor = authenticate(("ComplianceOfficer",))
    data = shape.read_body(POSTING_SPEC)
    if not data["document_uri"].startswith("https://"):
        raise shape.bad("document_uri must start with https://.")
    shape.require_order(data["community_meeting_held_on"], data["posted_on"],
                        "community_meeting_held_on", "posted_on")
    unit = common.get_unit(data["unit_id"])
    common.no_future_date(data["posted_on"], data["community_meeting_held_on"])
    common.unit_not_care_complete(unit)
    record = dict(data)
    record["posted_by_user_id"] = actor.user_id
    record["status"] = "POSTED"
    record["withdrawn_on"] = None
    record["withdrawal_reason"] = None
    record["satisfied_obligation"] = False
    record["days_late"] = 0
    store.stamp_new(record)
    store.public_postings[record["id"]] = record
    calc.refresh_postings(unit)
    common.settle(unit)
    return envelope.created(derive.posting(record))


WITHDRAW_SPEC = {
    "withdrawn_on": {"t": "date", "req": True},
    "withdrawal_reason": {"t": "str", "req": True, "min": 1},
}


@bp.post("/ccr/public-postings/<posting_id>/withdraw")
def withdraw_posting(posting_id):
    authenticate(("ComplianceOfficer",))
    data = shape.read_body(WITHDRAW_SPEC)
    posting = common.get_posting(posting_id)
    unit = common.get_unit(posting["unit_id"])
    common.unit_not_care_complete(unit)
    if posting["status"] != "POSTED":
        raise ApiError("ERR_INVALID_POSTING_STATE",
                       "Only a POSTED document may be withdrawn.")
    posting["status"] = "WITHDRAWN"
    posting["withdrawn_on"] = data["withdrawn_on"]
    posting["withdrawal_reason"] = data["withdrawal_reason"]
    posting["satisfied_obligation"] = False
    store.touch(posting)
    calc.refresh_postings(unit)
    common.settle(unit)
    return envelope.ok(derive.posting(posting))
