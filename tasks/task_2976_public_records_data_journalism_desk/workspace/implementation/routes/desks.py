"""Desk and Agency endpoints (PRD section 3.1)."""
from flask import Blueprint

import db
import response
import validation as v
from errors import ApiError
from middleware import (ALL_ROLES, ROLE_LEGAL_COUNSEL, ROLE_MANAGING_EDITOR,
                        ROLE_RECORDS_COORDINATOR, authenticate)
from services import cascades, ledger

bp = Blueprint("desks", __name__)

SEVERITY_CODES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
DEADLINE_BASES = ("BUSINESS_DAYS", "CALENDAR_DAYS")
APPEAL_VENUES = ("INTERNAL", "OMBUDS", "COURT")

JURISDICTION_PATTERN = r"^[A-Z\-]{2,16}$"


@bp.post("/desks")
def create_desk():
    authenticate([ROLE_MANAGING_EDITOR])
    payload = v.body()
    name = v.field_string(payload, "name", min_len=1, max_len=120, non_blank=True)
    total = v.field_int(payload, "fee_budget_total_cents", minimum=0)
    retention = v.field_int(payload, "retention_policy_days", minimum=365, maximum=3650)
    desk = db.insert("desks", {
        "name": name,
        "fee_budget_total_cents": total,
        "fee_budget_available_cents": total,
        "fee_budget_committed_cents": 0,
        "fee_budget_spent_cents": 0,
        "retention_policy_days": retention,
        "open_request_count": 0,
        "open_appeal_count": 0,
        "litigation_exposure_count": 0,
        "source_exposure_incident_count": 0,
        "security_posture": ledger.POSTURE_OPEN,
    })
    return response.created_response(db.serialize(desk))


@bp.get("/desks/<desk_id>")
def get_desk(desk_id):
    authenticate(ALL_ROLES)
    desk = db.get_desk(desk_id)
    return response.object_response(db.serialize(desk))


@bp.post("/desks/<desk_id>/budget-adjustments")
def adjust_budget(desk_id):
    authenticate([ROLE_MANAGING_EDITOR])
    desk = db.get_desk(desk_id)
    payload = v.body()
    delta = v.field_int(payload, "delta_cents")
    v.field_text(payload, "reason")
    if desk[ledger.AVAILABLE] + delta < 0:
        raise ApiError(
            "ERR_FEE_BUDGET_EXCEEDED",
            "A negative adjustment of %d cents would drive the available column below zero." % delta,
        )
    ledger.adjust(desk, delta)
    db.touch(desk)
    return response.object_response(db.serialize(desk))


@bp.post("/desks/<desk_id>/source-exposure-incidents")
def record_source_exposure(desk_id):
    authenticate([ROLE_MANAGING_EDITOR, ROLE_LEGAL_COUNSEL])
    desk = db.get_desk(desk_id)
    payload = v.body()
    v.field_string(payload, "incident_summary", min_len=1, max_len=1000, non_blank=True)
    v.field_enum(payload, "severity_code", SEVERITY_CODES)
    cascades.source_exposure_incident(desk)
    return response.object_response(db.serialize(desk))


@bp.post("/agencies")
def create_agency():
    authenticate([ROLE_RECORDS_COORDINATOR, ROLE_MANAGING_EDITOR])
    payload = v.body()
    agency = {
        "name": v.field_string(payload, "name", min_len=1, max_len=160, non_blank=True),
        "jurisdiction_code": v.field_string(
            payload, "jurisdiction_code", min_len=2, max_len=16, non_blank=True,
            pattern=JURISDICTION_PATTERN,
            pattern_desc="must contain only uppercase letters and hyphens"),
        "statute_name": v.field_string(payload, "statute_name", min_len=1, max_len=80,
                                       non_blank=False),
        "initial_response_days": v.field_int(payload, "initial_response_days", minimum=1, maximum=60),
        "deadline_basis": v.field_enum(payload, "deadline_basis", DEADLINE_BASES),
        "tolling_allowed": v.field_bool(payload, "tolling_allowed"),
        "appeal_venue": v.field_enum(payload, "appeal_venue", APPEAL_VENUES),
        "appeal_decision_days": v.field_int(payload, "appeal_decision_days", minimum=1, maximum=90),
        "search_fee_cents_per_hour": v.field_int(payload, "search_fee_cents_per_hour",
                                                 minimum=0, maximum=50000),
        "page_fee_cents": v.field_int(payload, "page_fee_cents", minimum=0, maximum=1000),
        "max_waiver_cents": v.field_int(payload, "max_waiver_cents", minimum=0),
        "holiday_dates": v.field_date_list(payload, "holiday_dates", optional=True, default=[]),
    }
    # An agency carries no version: this profile is fixed for the life of the row.
    db.insert("agencies", agency, versioned=False)
    return response.created_response(db.serialize(agency))


@bp.get("/agencies/<agency_id>")
def get_agency(agency_id):
    authenticate(ALL_ROLES)
    agency = db.get_agency(agency_id)
    return response.object_response(db.serialize(agency))
