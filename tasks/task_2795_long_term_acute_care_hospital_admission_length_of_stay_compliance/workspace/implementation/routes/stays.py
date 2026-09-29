"""Stays: reads, discharge, recombination, interruptions and interdisciplinary notes."""

from datetime import timedelta

from flask import Blueprint

import auth
import calc
import lookup
import serialize
import validate
from clock import now
from envelope import array_response, object_response
from errors import ApiError
from services import cascade, shares
from store import db, new_row, sorted_rows, touch

bp = Blueprint("stays", __name__)

CO = auth.ROLE_COMPLIANCE_OFFICER
IC = auth.ROLE_INTAKE_COORDINATOR
URN = auth.ROLE_UR_NURSE
AP = auth.ROLE_ATTENDING_PHYSICIAN
RIA = auth.ROLE_REVENUE_ANALYST

CLINICAL_STATUSES = ("ADMITTED", "INTERRUPTED", "DISCHARGED", "RECOMBINED")
PAYMENT_REVIEW_STATUSES = ("PENDING", "PRICED", "FINALIZED")
CLIENT_DISPOSITIONS = ("HOME", "HOME_HEALTH", "SNF", "IRF", "ACUTE_TRANSFER", "EXPIRED")
DESTINATIONS = ("ACUTE_CARE", "IRF", "SNF", "HOME")
DISCIPLINES = ("PHYSICIAN", "NURSING", "RESPIRATORY_THERAPY", "CASE_MANAGEMENT",
               "NUTRITION", "PT_OT")
INTERRUPTION_STATUSES = ("OPEN", "RETURNED", "EXPIRED")


def stay_period(stay):
    return db.periods.get(stay["cost_reporting_period_id"])


def require_open_period(stay):
    """PRD 2.7 / 3.9: a CLOSED period refuses every further mutation on its stays."""
    period = stay_period(stay)
    if period is not None and period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_CLOSED", "The stay's cost reporting period is CLOSED.")
    return period


def has_open_interruption(stay_id):
    for row in lookup.stay_interruptions(stay_id):
        if row["status"] == "OPEN":
            return True
    return False


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #

@bp.route("/stays/<stay_id>", methods=["GET"])
def get_stay(stay_id):
    auth.require_role(*auth.ALL_ROLES)
    return object_response(serialize.stay(lookup.stay(stay_id)))


@bp.route("/stays", methods=["GET"])
def list_stays():
    auth.require_role(IC, CO, RIA, URN)
    limit, offset = validate.pagination()
    patient_id = validate.query_str("patient_id")
    referral_id = validate.query_str("referral_id")
    period_id = validate.query_str("cost_reporting_period_id")
    parent_id = validate.query_str("interrupted_parent_stay_id")
    clinical_status = validate.query_enum("clinical_status", CLINICAL_STATUSES)
    payment_review_status = validate.query_enum("payment_review_status", PAYMENT_REVIEW_STATUSES)

    rows = list(db.stays.values())
    if patient_id is not None:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if referral_id is not None:
        rows = [r for r in rows if r["referral_id"] == referral_id]
    if period_id is not None:
        rows = [r for r in rows if r["cost_reporting_period_id"] == period_id]
    if parent_id is not None:
        rows = [r for r in rows if r["interrupted_parent_stay_id"] == parent_id]
    if clinical_status is not None:
        rows = [r for r in rows if r["clinical_status"] == clinical_status]
    if payment_review_status is not None:
        rows = [r for r in rows if r["payment_review_status"] == payment_review_status]

    rows = sorted_rows(rows)
    page = lookup.page(rows, limit, offset)
    return array_response([serialize.stay(r) for r in page], limit, offset, len(rows))


# --------------------------------------------------------------------------- #
# discharge
# --------------------------------------------------------------------------- #

@bp.route("/stays/<stay_id>/discharge", methods=["POST"])
def discharge_stay(stay_id):
    body = validate.get_body()
    disposition = validate.req_enum(body, "discharge_disposition", CLIENT_DISPOSITIONS)
    estimated_cost_cents = validate.req_int(body, "estimated_cost_cents", minimum=0)
    auth.require_role(URN)
    stay = lookup.stay(stay_id)

    if stay["clinical_status"] != "ADMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only an ADMITTED stay may be discharged.")
    if has_open_interruption(stay["id"]):
        raise ApiError("ERR_INVALID_STATE",
                       "The stay still has an OPEN interruption event.")
    require_open_period(stay)

    plan = lookup.stay_weaning_plan(stay["id"])
    if plan is not None and plan["status"] in ("SBT_TRIAL", "PROGRESSING", "REGRESSED"):
        raise ApiError("ERR_WEANING_PLAN_OPEN",
                       "The stay's ventilator weaning plan is still open.")

    cascade.run_discharge(stay, now(), disposition, estimated_cost_cents, auth.acting_user_id())
    return object_response(serialize.stay(stay))


# --------------------------------------------------------------------------- #
# recombination
# --------------------------------------------------------------------------- #

@bp.route("/stays/<stay_id>/recombine", methods=["POST"])
def recombine_stay(stay_id):
    body = validate.get_body()
    parent_id = validate.req_str(body, "interrupted_parent_stay_id", 1, None)
    auth.require_role(CO)
    child = lookup.stay(stay_id)
    parent = lookup.stay(parent_id)

    if child["clinical_status"] != "ADMITTED" or child["payment_review_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an ADMITTED, PENDING stay may be folded into an earlier stay.")
    if has_open_interruption(child["id"]):
        raise ApiError("ERR_INVALID_STATE",
                       "The stay still has an OPEN interruption event.")
    period = require_open_period(child)

    if parent["id"] == child["id"] \
            or parent["patient_id"] != child["patient_id"] \
            or parent["clinical_status"] != "DISCHARGED" \
            or parent["cost_reporting_period_id"] != child["cost_reporting_period_id"] \
            or parent["discharged_at"] is None \
            or calc.day_count(parent["discharged_at"], child["admitted_at"]) > calc.RECOMBINATION_WINDOW_DAYS \
            or child["admitted_at"] < parent["discharged_at"]:
        raise ApiError("ERR_RECOMBINATION_WINDOW_EXCEEDED",
                       "The named parent stay is not a valid recombination target.")

    # ---- the child ---- #
    child["clinical_status"] = "RECOMBINED"
    child["interrupted_parent_stay_id"] = parent["id"]
    child["counts_toward_admission_threshold"] = False
    touch(child)

    referral = db.referrals[child["referral_id"]]
    hospital = db.hospitals[referral["referring_hospital_id"]]
    if period is not None:
        period["total_admissions"] = period["total_admissions"] - 1
        touch(period)
    hospital_version = hospital["version"]
    hospital["admissions_in_period"] = hospital["admissions_in_period"] - 1

    # ---- the parent ---- #
    parent["carried_los_days"] = calc.day_count(parent["admitted_at"], parent["discharged_at"])
    parent["resumed_at"] = child["admitted_at"]
    parent["clinical_status"] = "ADMITTED"
    parent["discharged_at"] = None
    parent["discharge_disposition"] = None
    parent["payment_review_status"] = "PENDING"
    parent["discharge_payment_pct"] = None
    cascade.unwind_stay_money(parent, stay_period(parent))
    touch(parent)

    if period is not None:
        shares.recompute_all_shares(period)
    if hospital["version"] == hospital_version:
        touch(hospital)

    return object_response(serialize.stay(child))


# --------------------------------------------------------------------------- #
# interruptions of stay
# --------------------------------------------------------------------------- #

@bp.route("/stays/<stay_id>/interrupt", methods=["POST"])
def interrupt_stay(stay_id):
    body = validate.get_body()
    destination = validate.req_enum(body, "destination", DESTINATIONS)
    left_at = validate.opt_datetime(body, "left_at")
    auth.require_role(URN)
    stay = lookup.stay(stay_id)

    if stay["clinical_status"] != "ADMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only an ADMITTED stay may be interrupted.")
    require_open_period(stay)

    instant = now()
    if left_at is None:
        left_at = instant

    if left_at < stay["admitted_at"] or (stay["resumed_at"] is not None
                                        and left_at < stay["resumed_at"]):
        raise ApiError("ERR_INTERRUPTION_BEFORE_ADMISSION",
                       "left_at precedes the stay's admission or resumption instant.")
    if left_at > instant:
        raise ApiError("ERR_ADMISSION_IN_FUTURE",
                       "left_at is after the current logical instant.")

    buffer_delta = timedelta(hours=calc.INTERRUPTION_BUFFER_HOURS)
    for earlier in lookup.stay_interruptions(stay["id"]):
        end = earlier["returned_at"] if earlier["returned_at"] is not None else earlier["left_at"]
        if end is None:
            continue
        if left_at - end <= buffer_delta:
            raise ApiError("ERR_INTERRUPTION_BUFFER_VIOLATION",
                           "A new interruption must clear every earlier one by at least 24 hours.")

    if stay["interruption_count"] >= calc.MAX_INTERRUPTIONS_PER_STAY:
        raise ApiError("ERR_INTERRUPTION_LIMIT_EXCEEDED",
                       "The stay already carries three interruption events.")

    event = new_row("interruptions")
    event.update({
        "stay_id": stay["id"],
        "destination": destination,
        "left_at": left_at,
        "returned_at": None,
        "window_days": calc.INTERRUPTION_WINDOW_DAYS[destination],
        "interruption_days": None,
        "within_window": None,
        "status": "OPEN",
    })
    db.interruptions[event["id"]] = event

    stay["clinical_status"] = "INTERRUPTED"
    stay["interruption_count"] = stay["interruption_count"] + 1
    touch(stay)

    return object_response(serialize.interruption(event), 201)


@bp.route("/stays/<stay_id>/interruptions", methods=["GET"])
def list_stay_interruptions(stay_id):
    auth.require_role(URN, CO, RIA, IC)
    stay = lookup.stay(stay_id)
    limit, offset = validate.pagination()
    status = validate.query_enum("status", INTERRUPTION_STATUSES)

    rows = lookup.stay_interruptions(stay["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_rows(rows)
    page = lookup.page(rows, limit, offset)
    return array_response([serialize.interruption(r) for r in page], limit, offset, len(rows))


@bp.route("/interruptions/<interruption_id>/return", methods=["POST"])
def return_interruption(interruption_id):
    validate.get_body()
    auth.require_role(URN)
    event = lookup.interruption(interruption_id)

    if event["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN interruption may be returned.")
    stay = db.stays[event["stay_id"]]
    require_open_period(stay)

    instant = now()
    if instant < event["left_at"]:
        raise ApiError("ERR_VALIDATION",
                       "The current logical instant precedes the interruption's left_at.")

    interruption_days = calc.day_count(event["left_at"], instant)
    within_window = interruption_days <= event["window_days"]
    event["returned_at"] = instant
    event["interruption_days"] = interruption_days
    event["within_window"] = within_window

    if within_window:
        event["status"] = "RETURNED"
        touch(event)
        stay["interruption_days_total"] = stay["interruption_days_total"] + interruption_days
        stay["clinical_status"] = "ADMITTED"
        touch(stay)
    else:
        event["status"] = "EXPIRED"
        touch(event)
        cascade.run_discharge(stay, event["left_at"], "INTERRUPTION_EXPIRED", None,
                              auth.acting_user_id())

    return object_response(serialize.interruption(event))


# --------------------------------------------------------------------------- #
# interdisciplinary notes
# --------------------------------------------------------------------------- #

@bp.route("/stays/<stay_id>/idt-notes", methods=["POST"])
def create_idt_note(stay_id):
    body = validate.get_body()
    discipline = validate.req_enum(body, "discipline", DISCIPLINES)
    note_text = validate.req_str(body, "note_text", 1, 2000)
    goals_documented = validate.opt_bool(body, "goals_documented", False)
    auth.require_role(URN, AP)
    stay = lookup.stay(stay_id)
    require_open_period(stay)

    documented_at = now()
    row = new_row("idt_notes")
    row.update({
        "stay_id": stay["id"],
        "discipline": discipline,
        "note_text": note_text,
        "goals_documented": goals_documented,
        "documented_at": documented_at,
        "week_index": calc.day_count(stay["admitted_at"], documented_at) // 7,
    })
    db.idt_notes[row["id"]] = row
    return object_response(serialize.idt_note(row), 201)


@bp.route("/stays/<stay_id>/idt-notes", methods=["GET"])
def list_idt_notes(stay_id):
    auth.require_role(URN, AP, CO, RIA, IC)
    stay = lookup.stay(stay_id)
    limit, offset = validate.pagination()
    discipline = validate.query_enum("discipline", DISCIPLINES)

    rows = lookup.stay_notes(stay["id"])
    if discipline is not None:
        rows = [r for r in rows if r["discipline"] == discipline]
    rows = sorted_rows(rows)
    page = lookup.page(rows, limit, offset)
    return array_response([serialize.idt_note(r) for r in page], limit, offset, len(rows))
