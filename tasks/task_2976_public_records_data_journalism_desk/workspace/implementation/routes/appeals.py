"""Appeal endpoints (PRD section 3.5)."""
from flask import Blueprint

import clock
import db
import response
import validation as v
from errors import ApiError
from middleware import (ALL_ROLES, ROLE_LEGAL_COUNSEL, ROLE_RECORDS_COORDINATOR,
                        authenticate)
from services import cascades, daycalc, ledger

bp = Blueprint("appeals", __name__)

APPEAL_VENUES = ("INTERNAL", "OMBUDS", "COURT")
DECISION_OUTCOMES = ("GRANTED", "DENIED")


def _ripeness_basis(request_row):
    """Ripeness is judged from the parent request's status; the delay ground
    requires the logical clock to be strictly after due_at_tolled."""
    status = request_row["status"]
    if status == "DENIED":
        return "DENIED"
    if status == "PARTIALLY_RELEASED":
        return "PARTIAL_RELEASE"
    if status == "AWAITING_AGENCY_RESPONSE":
        due = clock.instant_of(request_row.get("due_at_tolled"))
        if due is not None and clock.now() > due:
            return "OVERDUE"
    return None


@bp.post("/appeals")
def create_appeal():
    user_id, _ = authenticate([ROLE_LEGAL_COUNSEL])
    payload = v.body()
    request_id = v.field_string(payload, "request_id", min_len=1, non_blank=True)
    venue = v.field_enum(payload, "venue", APPEAL_VENUES)
    grounds = v.field_string(payload, "grounds", min_len=1, max_len=2000, non_blank=True)
    filing_fee_cents = v.field_int(payload, "filing_fee_cents", minimum=0, maximum=2000000)
    request_row = db.get_request(request_id)
    # Rung 22 -- ripeness
    ripeness_basis = _ripeness_basis(request_row)
    if ripeness_basis is None:
        raise ApiError("ERR_APPEAL_NOT_RIPE",
                       "The parent request offers no declared ground for an appeal.")
    agency = db.find("agencies", request_row["agency_id"])
    # Rung 23 -- venue
    if venue != agency["appeal_venue"]:
        raise ApiError("ERR_APPEAL_VENUE_MISMATCH",
                       "The agency's statute routes appeals to %s." % agency["appeal_venue"])
    desk = db.find("desks", request_row["desk_id"])
    # Rung 38 -- affordability
    ledger.check_commit(desk, filing_fee_cents)
    now = clock.now()
    appeal = db.insert("appeals", {
        "request_id": request_id,
        "venue": venue,
        "grounds": grounds,
        "filing_fee_cents": filing_fee_cents,
        "filed_by_user_id": user_id,
        "filed_at": clock.iso(now),
        "ripeness_basis": ripeness_basis,
        "decision_due_at": daycalc.appeal_decision_due_at(now, agency),
        "status": "FILED",
        "decision_rationale": None,
    })
    request_row["status"] = "APPEAL_FILED"
    db.touch(request_row)
    ledger.commit(desk, filing_fee_cents)
    desk["open_appeal_count"] = desk["open_appeal_count"] + 1
    db.touch(desk)
    return response.created_response(db.serialize(appeal))


@bp.get("/appeals/<appeal_id>")
def get_appeal(appeal_id):
    authenticate(ALL_ROLES)
    return response.object_response(db.serialize(db.get_appeal(appeal_id)))


@bp.get("/appeals")
def list_appeals():
    authenticate(ALL_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(db.ordered("appeals"), ["request_id", "status"])
    window = rows[offset:offset + limit]
    return response.array_response(db.serialize_all(window), limit, offset, len(rows))


@bp.post("/appeals/<appeal_id>/decision")
def decide_appeal(appeal_id):
    authenticate([ROLE_RECORDS_COORDINATOR])
    appeal = db.get_appeal(appeal_id)
    payload = v.body()
    outcome = v.field_enum(payload, "outcome", DECISION_OUTCOMES)
    decision_rationale = v.field_text(payload, "decision_rationale")
    if appeal["status"] != "FILED":
        raise ApiError("ERR_INVALID_APPEAL_STATE",
                       "A decision is only declared against an appeal in FILED.")
    request_row = db.find("records_requests", appeal["request_id"])
    desk = db.find("desks", request_row["desk_id"])
    agency = db.find("agencies", request_row["agency_id"])

    appeal["status"] = outcome
    appeal["decision_rationale"] = decision_rationale
    db.touch(appeal)

    if outcome == "GRANTED":
        request_row["status"] = "AWAITING_AGENCY_RESPONSE"
        accrual = daycalc.tolling_days_for_span(
            clock.instant_of(appeal["filed_at"]), clock.now(),
            agency["deadline_basis"], agency.get("holiday_dates") or [],
        )
        request_row["tolled_days_total"] = request_row["tolled_days_total"] + accrual
        request_row["due_at_tolled"] = daycalc.tolled_due_at(
            clock.instant_of(request_row["submitted_at"]), agency,
            request_row["tolled_days_total"],
        )
        db.touch(request_row)
    else:
        request_row["status"] = "LITIGATION_AUTHORIZED"
        db.touch(request_row)
        cascades.litigation_authorized(desk, request_row)

    ledger.settle(desk, appeal["filing_fee_cents"])
    desk["open_appeal_count"] = desk["open_appeal_count"] - 1
    db.touch(desk)
    return response.object_response(db.serialize(appeal))
