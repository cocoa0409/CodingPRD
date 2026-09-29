"""Visa case endpoints (PRD 3.4)."""
from flask import Blueprint

import cascades
import serialize
from calc import MIN_TERM_MONTHS, RFE_ROUND_LIMIT, VISA_ACTIVATION_LEAD_DAYS, project_dates
from envelope import success
from errors import ApiError
from guards import ROLE_ADVISOR, authenticate, json_body, lookup, need_enum, opt_enum, opt_string
from store import add_days, store, touch

bp = Blueprint("visa", __name__)

PROCESSING_TRACKS = ("STANDARD", "PREMIUM")
ADJUDICATION_OUTCOMES = ("APPROVED", "DENIED", "RFE")
PREMIUM_CATEGORIES = ("H1B", "O1")


@bp.post("/visa-cases/<record_id>/submit-petition")
def submit_petition(record_id):
    authenticate((ROLE_ADVISOR,))
    case = lookup("visa_case", record_id)
    body = json_body()
    track = opt_enum(body, "processing_track", PROCESSING_TRACKS, None)
    appointment = store.appointments.get(case["appointment_id"])
    # rule 6: both the case and the governing appointment must offer the transition.
    if case["status"] not in ("DOCS_PENDING", "RFE_RECEIVED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A case in %s may not be filed." % case["status"])
    if appointment is None or appointment["appointment_status"] != "OFFER_ACCEPTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The petition may only be filed while the appointment is OFFER_ACCEPTED.")
    effective_track = track if track is not None else case["processing_track"]
    # rule 17: premium processing availability.
    if effective_track == "PREMIUM" and case["visa_category"] not in PREMIUM_CATEGORIES:
        raise ApiError("ERR_PREMIUM_TRACK_UNAVAILABLE",
                       "Premium processing is unavailable for %s." % case["visa_category"])
    refiling = case["status"] == "RFE_RECEIVED"
    # rule 18: request-for-evidence rounds.
    if refiling and case["rfe_round_count"] >= RFE_ROUND_LIMIT:
        raise ApiError("ERR_RFE_ROUND_LIMIT_REACHED",
                       "The case has exhausted its request-for-evidence rounds.")

    if track is not None:
        case["processing_track"] = track
    if refiling:
        case["rfe_round_count"] = case["rfe_round_count"] + 1
        variant = "POST_RFE_REFILING"
    else:
        variant = "INITIAL_FILING"
    case["filed_at"] = store.now()
    case["projection_variant"] = variant
    projected, lawful = project_dates(case, variant)
    case["projected_decision_date"] = projected
    case["earliest_lawful_start_date"] = lawful
    case["status"] = "SUBMITTED"
    touch(case)
    return success(serialize.visa_case_out(case))


@bp.post("/visa-cases/<record_id>/adjudication")
def record_adjudication(record_id):
    authenticate((ROLE_ADVISOR,))
    case = lookup("visa_case", record_id)
    body = json_body()
    outcome = need_enum(body, "outcome", ADJUDICATION_OUTCOMES)
    opt_string(body, "decision_note")
    if case["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A case in %s may not be adjudicated." % case["status"])
    if outcome == "RFE" and case["rfe_round_count"] >= RFE_ROUND_LIMIT:
        raise ApiError("ERR_RFE_ROUND_LIMIT_REACHED",
                       "The case has exhausted its request-for-evidence rounds.")
    appointment = store.appointments.get(case["appointment_id"])

    if outcome == "RFE":
        case["status"] = "RFE_RECEIVED"
        touch(case)
        return success(serialize.visa_case_out(case))

    case["decided_at"] = store.now()
    if outcome == "DENIED":
        case["status"] = "DENIED"
        touch(case)
        if appointment is not None and appointment["appointment_status"] == "OFFER_ACCEPTED":
            cascades.withdraw_appointment(appointment, "VISA_DENIED")
        return success(serialize.visa_case_out(case))

    # CH-B: the realized decision replaces the projection.
    case["status"] = "APPROVED"
    case["earliest_lawful_start_date"] = add_days(
        case["decided_at"].date(), VISA_ACTIVATION_LEAD_DAYS)
    touch(case)
    if appointment is not None \
            and case["earliest_lawful_start_date"] > appointment["term_start_date"]:
        appointment["term_start_date"] = case["earliest_lawful_start_date"]
        cascades.recompute_term_and_money(appointment)
        if appointment["term_months"] < MIN_TERM_MONTHS \
                and appointment["appointment_status"] == "OFFER_ACCEPTED":
            cascades.withdraw_appointment(appointment, "VISA_DELAY_TERM_TOO_SHORT")
    return success(serialize.visa_case_out(case))
