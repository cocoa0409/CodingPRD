"""Debtor examinations and duces-tecum subpoenas (PRD 3.4)."""

from flask import request

from domain import (
    EXAM_COOLING_HOURS,
    EXAM_SERVICE_LOOKBACK_DAYS,
    MAX_CONTINUANCES,
    SUBPOENA_LEAD_DAYS,
    add_days,
    by_seq,
    debtor_of_judgment,
    get_exam,
    get_judgment,
    guard_judgment_alive,
    invalid_state,
    refresh_preliminary,
    to_date,
)
from errors import ApiError
from store import bump, new_row, store
from validators import (
    ENUM_EXAM_OUTCOME,
    ENUM_RECIPIENT_TYPE,
    check_enum,
    json_body,
    pagination,
    parse_instant,
    present,
    require_date,
    require_instant,
    require_string,
)
from web import endpoint, make_list

from .helpers import apply_filter, serialize

READ_ROLES = ("CaseManager", "EnforcementOfficer", "ComplianceOfficer")


def _debtor_id_for_exam(exam):
    judgment = store.judgments.get(exam["judgment_id"])
    return judgment["debtor_id"] if judgment else None


def _check_cooling(debtor_id, candidate, exclude_exam_id=None):
    """rung 23 - at least 2,880 hours from every other live exam on the debtor."""
    for other in by_seq(list(store.debtor_examinations.values())):
        if exclude_exam_id is not None and other["id"] == exclude_exam_id:
            continue
        if other["status"] not in ("SCHEDULED", "SERVED"):
            continue
        if _debtor_id_for_exam(other) != debtor_id:
            continue
        other_at = parse_instant(other["scheduled_at"])
        if other_at is None:
            continue
        delta_hours = abs((candidate - other_at).total_seconds()) / 3600.0
        if delta_hours < EXAM_COOLING_HOURS:
            raise ApiError("ERR_EXAM_COOLING_PERIOD",
                           "The examination is too close to another live examination on this debtor.")


def register(app):
    # ---- POST /debtor-examinations ---------------------------------------
    @endpoint(app, "/debtor-examinations", "POST", ("CaseManager",), 201)
    def create_exam(ctx):
        body = json_body()
        judgment = get_judgment(body.get("judgment_id")) if present(body, "judgment_id") else None
        judgment_id = require_string(body, "judgment_id")
        scheduled_at = require_instant(body, "scheduled_at")
        guard_judgment_alive(judgment)
        _check_cooling(judgment["debtor_id"], scheduled_at)
        row = new_row({
            "judgment_id": judgment_id,
            "scheduled_at": body["scheduled_at"],
            "status": "SCHEDULED",
            "served_on": None,
            "continuance_count": 0,
            "outcome_recorded_on": None,
            "subpoena_status": "NOT_ISSUED",
            "subpoena_recipient_type": None,
            "subpoena_recipient_name": None,
            "subpoena_service_deadline_on": add_days(scheduled_at.date(), -SUBPOENA_LEAD_DAYS).isoformat(),
        })
        store.debtor_examinations[row["id"]] = row
        return serialize(row)

    # ---- GET /debtor-examinations ----------------------------------------
    @endpoint(app, "/debtor-examinations", "GET", READ_ROLES, 200)
    def list_exams(ctx):
        limit, offset = pagination(request.args)
        rows = by_seq(list(store.debtor_examinations.values()))
        rows = apply_filter(rows, request.args, "judgment_id")
        rows = apply_filter(rows, request.args, "status")
        rows = apply_filter(rows, request.args, "subpoena_status")
        return make_list(rows, limit, offset, serialize)

    # ---- GET /debtor-examinations/{examination_id} -----------------------
    @endpoint(app, "/debtor-examinations/<examination_id>", "GET", READ_ROLES, 200)
    def read_exam(ctx, examination_id):
        return serialize(get_exam(examination_id))

    # ---- POST /debtor-examinations/{id}/subpoena -------------------------
    @endpoint(app, "/debtor-examinations/<examination_id>/subpoena", "POST", ("CaseManager",), 200)
    def issue_subpoena(ctx, examination_id):
        exam = get_exam(examination_id)
        body = json_body()
        require_string(body, "recipient_type")
        recipient_name = require_string(body, "recipient_name")
        recipient_type = check_enum(body, "recipient_type", ENUM_RECIPIENT_TYPE)
        if exam["subpoena_status"] != "NOT_ISSUED" or exam["status"] != "SCHEDULED":
            invalid_state("The subpoena may only be issued on a SCHEDULED examination that has none.")
        judgment = store.judgments.get(exam["judgment_id"])
        guard_judgment_alive(judgment)
        # rung 25 - the subpoena must be issued on or before its service deadline
        if store.clock_date() > to_date(exam["subpoena_service_deadline_on"]):
            raise ApiError("ERR_SUBPOENA_DEADLINE_PASSED", "The subpoena service deadline has passed.")
        exam["subpoena_status"] = "ISSUED"
        exam["subpoena_recipient_type"] = recipient_type
        exam["subpoena_recipient_name"] = recipient_name
        bump(exam)
        return serialize(exam)

    # ---- POST /debtor-examinations/{id}/serve ----------------------------
    @endpoint(app, "/debtor-examinations/<examination_id>/serve", "POST", ("CaseManager",), 200)
    def serve_exam(ctx, examination_id):
        exam = get_exam(examination_id)
        body = json_body()
        served_on = require_date(body, "served_on")
        clock_date = store.clock_date()
        if served_on < add_days(clock_date, -EXAM_SERVICE_LOOKBACK_DAYS) or served_on > clock_date:
            raise ApiError("ERR_INVALID_REQUEST",
                           "served_on must fall within the 30 days ending on the current clock date.")
        if exam["status"] != "SCHEDULED":
            invalid_state("Only a SCHEDULED examination may be served.")
        judgment = store.judgments.get(exam["judgment_id"])
        guard_judgment_alive(judgment)
        debtor = debtor_of_judgment(judgment)
        # rung 30 - one cannot serve someone nobody can find
        if debtor is None or debtor["locate_status"] != "LOCATED":
            raise ApiError("ERR_DEBTOR_NOT_LOCATED", "The debtor is not located.")
        exam["status"] = "SERVED"
        exam["served_on"] = served_on.isoformat()
        if exam["subpoena_status"] == "ISSUED":
            exam["subpoena_status"] = "SERVED"
        bump(exam)
        return serialize(exam)

    # ---- POST /debtor-examinations/{id}/record-outcome -------------------
    @endpoint(app, "/debtor-examinations/<examination_id>/record-outcome", "POST",
              ("CaseManager",), 200)
    def record_outcome(ctx, examination_id):
        exam = get_exam(examination_id)
        body = json_body()
        outcome_raw = require_string(body, "outcome")
        new_scheduled_at = None
        if outcome_raw == "CONTINUED":
            new_scheduled_at = require_instant(body, "new_scheduled_at")
        outcome = check_enum(body, "outcome", ENUM_EXAM_OUTCOME)
        if exam["status"] != "SERVED":
            invalid_state("Only a SERVED examination may have its outcome recorded.")
        judgment = store.judgments.get(exam["judgment_id"])
        guard_judgment_alive(judgment)

        if outcome == "CONTINUED":
            _check_cooling(judgment["debtor_id"], new_scheduled_at, exclude_exam_id=exam["id"])
            # rung 36 - at most two continuances
            if exam["continuance_count"] >= MAX_CONTINUANCES:
                raise ApiError("ERR_CONTINUANCE_LIMIT", "This examination has no continuances left.")
            exam["status"] = "SCHEDULED"
            exam["scheduled_at"] = body["new_scheduled_at"]
            exam["continuance_count"] += 1
            exam["served_on"] = None
            exam["subpoena_service_deadline_on"] = add_days(
                new_scheduled_at.date(), -SUBPOENA_LEAD_DAYS).isoformat()
            bump(exam)
            return serialize(exam)

        exam["status"] = outcome
        exam["outcome_recorded_on"] = store.clock_date().isoformat()
        bump(exam)
        if outcome == "NO_SHOW":
            debtor = debtor_of_judgment(judgment)
            if debtor is not None:
                debtor["no_show_count"] += 1
                refresh_preliminary(debtor)
                bump(debtor)
        return serialize(exam)
