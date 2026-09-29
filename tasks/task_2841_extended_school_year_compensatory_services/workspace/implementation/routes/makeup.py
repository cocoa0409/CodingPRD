"""Makeup sessions and the delivery dimension (PRD section 3.8)."""
from flask import Blueprint, g, request

from auth import (CASE_MANAGER, COMPLIANCE_OFFICER, PROGRAM_COORDINATOR,
                  RELATED_SERVICE_PROVIDER, SPED_DIRECTOR, endpoint,
                  is_provider_role)
from calcs import DEADLINE_EXTENSION_DAYS, fund_charge_waterfall, refresh_available
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from ledgers import (allocation_for_charge, apply_no_show_forfeiture,
                     close_negotiation_if_delivery_terminal,
                     recompute_award_ledger, recompute_student_ledger,
                     reopen_negotiation_if_delivery_active)
from resolve import body_ref, path_ref
from serialize import many, public
from store import add_days, db, new_record, now_iso, today, touch
from validate import (body, d, minutes_of, opt_str, req_date, req_enum, req_int,
                      req_str, req_time)

bp = Blueprint("makeup", __name__)

OUTCOMES = ("DELIVERED", "NO_SHOW_PARENT", "CANCELLED_DISTRICT", "VOIDED")
READ_ROLES = (CASE_MANAGER, PROGRAM_COORDINATOR, SPED_DIRECTOR,
              COMPLIANCE_OFFICER, RELATED_SERVICE_PROVIDER)


def advance_delivery_dimension(award, delivered=False):
    """PRD 3.8: the delivery dimension moves only as a consequence of outcomes."""
    remaining = award["remaining_owed_minutes"]
    status = award["delivery_status"]
    if remaining == 0 and status in ("SCHEDULING", "IN_PROGRESS"):
        award["delivery_status"] = "FULFILLED"
    elif delivered and remaining > 0 and status == "SCHEDULING":
        award["delivery_status"] = "IN_PROGRESS"


@bp.post("/esy/makeup-sessions")
@endpoint((CASE_MANAGER, PROGRAM_COORDINATOR))
def create_makeup_session():
    data = body()
    # PRD 2.6 body order: provider_id, then award_id, then supersedes_session_id.
    provider = body_ref(data, "provider_id", "provider")
    award = body_ref(data, "award_id", "award")
    superseded = body_ref(data, "supersedes_session_id", "session")

    award_id = req_str(data, "award_id", 1, None)
    provider_id = req_str(data, "provider_id", 1, None)
    session_date = req_date(data, "session_date")
    start_time = req_time(data, "start_time")
    end_time = req_time(data, "end_time")
    if minutes_of(end_time) <= minutes_of(start_time):
        raise ApiError("ERR_INVALID_REQUEST")
    minutes_planned = req_int(data, "minutes_planned", 1, 480)
    expected_version = req_int(data, "expected_award_version", 0, None)
    supersedes_id = data.get("supersedes_session_id")
    if supersedes_id is not None and not isinstance(supersedes_id, str):
        raise ApiError("ERR_INVALID_REQUEST")

    if award["negotiation_status"] != "AGREED":
        raise ApiError("ERR_INVALID_STATE")
    if award["delivery_status"] == "LAPSED":
        raise ApiError("ERR_INVALID_STATE")
    if superseded is not None and superseded["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    if expected_version != award["version"]:
        raise ApiError("ERR_STALE_AWARD_VERSION")

    if d(provider["credential_expires_on"]) < d(session_date):
        raise ApiError("ERR_PROVIDER_CREDENTIAL_EXPIRED")
    if provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ACTIVE")

    deadline = award.get("delivery_deadline_date")
    if d(session_date) < today() or (deadline and d(session_date) > d(deadline)):
        raise ApiError("ERR_MAKEUP_OUTSIDE_WINDOW")

    # PRD 3.8: the superseded session's minutes leave the pool before the test.
    scheduled_after = sum(
        s["minutes_planned"] for s in db.sessions.values()
        if s["award_id"] == award["id"] and s["status"] == "SCHEDULED"
        and (superseded is None or s["id"] != superseded["id"]))
    if scheduled_after + minutes_planned > award["remaining_owed_minutes"]:
        raise ApiError("ERR_OVERBOOKED_MAKEUP_MINUTES")

    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        touch(superseded)

    session = new_record("MakeupSession", {
        "award_id": award_id,
        "provider_id": provider_id,
        "supersedes_session_id": supersedes_id,
        "session_date": session_date,
        "start_time": start_time,
        "end_time": end_time,
        "minutes_planned": minutes_planned,
        "minutes_delivered": 0,
        "status": "SCHEDULED",
        "charge_cents": 0,
        "charged_fund_source": None,
        "charged_budget_code": None,
        "outcome_note": None,
    })
    db.sessions[session["id"]] = session

    recompute_award_ledger(award, bump=False)
    if award["delivery_status"] == "NOT_STARTED":
        award["delivery_status"] = "SCHEDULING"
    touch(award)
    return created(public(session))


@bp.get("/esy/makeup-sessions")
@endpoint(READ_ROLES)
def list_makeup_sessions():
    rows = list(db.sessions.values())
    for key in ("award_id", "provider_id", "supersedes_session_id", "status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    rows = sorted(rows, key=lambda r: (r["session_date"], r["created_at"], r["_seq"]))
    page, page_meta = paginate(rows)
    return ok_list(many(page), page_meta)


@bp.get("/esy/makeup-sessions/<session_id>")
@endpoint(READ_ROLES)
def get_makeup_session(session_id):
    return ok(public(path_ref("session", session_id)))


def _auto_resolve_mediation_records(student):
    """PRD 3.8 / 3.9: a fully paid debt closes the student's OPEN mediations."""
    if student is None or student["outstanding_owed_minutes"] != 0:
        return
    for record in db.records.values():
        if (record["student_id"] == student["id"] and record["status"] == "OPEN"
                and record["record_type"] == "MEDIATION_AGREEMENT"):
            record["status"] = "RESOLVED"
            record["resolution_note"] = "OWED_MINUTES_SATISFIED"
            record["resolved_at"] = now_iso()
            record["stay_put_active"] = False
            touch(record)


@bp.post("/esy/makeup-sessions/<session_id>/log-outcome")
@endpoint((RELATED_SERVICE_PROVIDER, COMPLIANCE_OFFICER))
def log_makeup_outcome(session_id):
    # PRD 2.7 check 4 outranks path resolution for the acting provider.
    if is_provider_role():
        candidate = db.sessions.get(session_id)
        if candidate is not None and candidate["provider_id"] != g.user_id:
            raise ApiError("ERR_NOT_ASSIGNED_PROVIDER")
    session = path_ref("session", session_id)
    data = body()
    outcome = req_enum(data, "outcome", OUTCOMES)

    # Voiding a delivered session is a ComplianceOfficer act; the three
    # provider-reported outcomes belong to the RelatedServiceProvider.
    if outcome == "VOIDED":
        if g.role != COMPLIANCE_OFFICER:
            raise ApiError("ERR_ROLE_NOT_PERMITTED")
    elif g.role != RELATED_SERVICE_PROVIDER:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")

    note = opt_str(data, "outcome_note", 1, None)
    minutes_delivered = None
    if outcome == "DELIVERED":
        minutes_delivered = req_int(data, "minutes_delivered", 1,
                                    session["minutes_planned"])

    if outcome == "VOIDED":
        if session["status"] != "DELIVERED":
            raise ApiError("ERR_INVALID_STATE")
    elif session["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    award = db.awards.get(session["award_id"])
    student = db.students.get(award["student_id"]) if award is not None else None

    if outcome == "DELIVERED":
        if (award is None or award["negotiation_status"] not in ("AGREED", "CLOSED")
                or award["delivery_status"] == "LAPSED"):
            raise ApiError("ERR_INVALID_STATE")
        provider = db.providers.get(session["provider_id"])
        charge = fund_charge_waterfall(award["source_program_id"],
                                       provider["rate_cents_per_minute"],
                                       minutes_delivered, compensatory=True)
        allocation = charge["allocation"]
        allocation["expended_amount_cents"] += charge["total_charge_cents"]
        allocation["compensatory_expended_cents"] += charge["total_charge_cents"]
        refresh_available(allocation)
        touch(allocation)

        session["minutes_delivered"] = minutes_delivered
        session["status"] = "DELIVERED"
        session["charge_cents"] = charge["total_charge_cents"]
        session["charged_fund_source"] = allocation["fund_source"]
        session["charged_budget_code"] = allocation["budget_code"]
        if note is not None:
            session["outcome_note"] = note
        touch(session)

        recompute_award_ledger(award, bump=False)
        advance_delivery_dimension(award, delivered=True)
        touch(award)
        if student is not None:
            recompute_student_ledger(student)
        if close_negotiation_if_delivery_terminal(award) and student is not None:
            recompute_student_ledger(student)
        _auto_resolve_mediation_records(student)

    elif outcome == "NO_SHOW_PARENT":
        session["status"] = "NO_SHOW_PARENT"
        if note is not None:
            session["outcome_note"] = note
        touch(session)

        recompute_award_ledger(award, bump=False)
        forfeited = apply_no_show_forfeiture(award, session)
        advance_delivery_dimension(award)
        touch(award)
        if forfeited and student is not None:
            recompute_student_ledger(student)
        if close_negotiation_if_delivery_terminal(award) and student is not None:
            recompute_student_ledger(student)

    elif outcome == "CANCELLED_DISTRICT":
        session["status"] = "CANCELLED_DISTRICT"
        if note is not None:
            session["outcome_note"] = note
        touch(session)

        recompute_award_ledger(award, bump=False)
        # PRD 3.8: the district's own failure buys the family more time.
        if award.get("delivery_deadline_date"):
            award["delivery_deadline_date"] = add_days(
                d(award["delivery_deadline_date"]), DEADLINE_EXTENSION_DAYS).isoformat()
        advance_delivery_dimension(award)
        touch(award)

    else:  # VOIDED
        allocation = allocation_for_charge(award["source_program_id"] if award else None,
                                          session.get("charged_fund_source"),
                                          session.get("charged_budget_code"))
        if allocation is not None and session["charge_cents"]:
            allocation["expended_amount_cents"] -= session["charge_cents"]
            allocation["compensatory_expended_cents"] -= session["charge_cents"]
            refresh_available(allocation)
            touch(allocation)

        session["status"] = "VOIDED"
        if note is not None:
            session["outcome_note"] = note
        touch(session)

        recompute_award_ledger(award, bump=False)
        if (award["delivery_status"] == "FULFILLED"
                and award["remaining_owed_minutes"] > 0):
            award["delivery_status"] = "IN_PROGRESS"
        advance_delivery_dimension(award)
        touch(award)
        reopen_negotiation_if_delivery_active(award)
        if student is not None:
            recompute_student_ledger(student)

    return ok(public(session))
