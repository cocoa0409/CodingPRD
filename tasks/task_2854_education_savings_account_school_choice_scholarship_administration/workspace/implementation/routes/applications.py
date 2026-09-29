"""Applications, eligibility determinations, acceptance and withdrawal."""
from flask import Blueprint

import calc
import cascades
import lookups
from envelope import list_response, object_response, public, touch
from errors import fail
from store import new_id, store
from validators import (APPLICATION_STATUSES, CATEGORY_FLAGS, INCOME_BANDS,
                        PRIOR_ENROLLMENTS, authenticate, body, paginate,
                        q_enum, q_str, v_bool, v_enum, v_flag_list, v_str)

bp = Blueprint("applications", __name__)

READ_ROLES = ("ProgramAdmin", "EligibilityOfficer", "ComplianceOfficer",
              "AppealsOfficer", "Guardian")
LIVE_APPLICATION_EXCLUDED = ("WITHDRAWN", "DENIED_FINAL", "EXPIRED")
ENROLLED_STATUSES = ("AWARD_OFFERED", "ACCEPTED", "COMPLETED")


def _window_is_open(py):
    now = store.now()
    return (py["status"] == "WINDOW_OPEN"
            and py["window_open_at"] <= now < py["window_close_at"])


def _terms_intersect(a_start, a_end, b_start, b_end):
    """Both intervals are fully inclusive plain dates."""
    return a_start <= b_end and b_start <= a_end


@bp.post("/applications")
def create_application():
    user_id, _role = authenticate("Guardian")
    payload = body()
    program_year_id = v_str(payload, "program_year_id")
    student_id = v_str(payload, "student_id")
    claimed_income_band = v_enum(payload, "claimed_income_band", INCOME_BANDS)
    claimed_category_flags = v_flag_list(payload, "claimed_category_flags",
                                         CATEGORY_FLAGS, required=False,
                                         default=[])
    is_renewal = v_bool(payload, "is_renewal", required=False, default=False)

    py = lookups.program_year(program_year_id)
    student = lookups.student(student_id)

    if not _window_is_open(py):
        fail("ERR_APPLICATION_WINDOW_CLOSED",
             "the submission window for this program year is not open")

    for other in sorted(store.applications.values(), key=lambda a: a["_seq"]):
        if other["student_id"] != student_id:
            continue
        if other["program_year_id"] == program_year_id:
            continue
        if other["status"] not in ENROLLED_STATUSES:
            continue
        other_py = store.program_years.get(other["program_year_id"])
        if other_py is None:
            continue
        if _terms_intersect(py["term_start_date"], py["term_end_date"],
                            other_py["term_start_date"], other_py["term_end_date"]):
            fail("ERR_OVERLAPPING_ENROLLMENT_PERIOD",
                 "the student already holds an enrolment whose term overlaps")

    for other in store.applications.values():
        if (other["student_id"] == student_id
                and other["program_year_id"] == program_year_id
                and other["status"] not in LIVE_APPLICATION_EXCLUDED):
            fail("ERR_DUPLICATE_APPLICATION",
                 "the student already has a live application for this year")

    if student["residency_state"] != py["residency_state"]:
        fail("ERR_RESIDENCY_NOT_ELIGIBLE",
             "student residency does not match the program year")

    created_at = store.next_created_at()
    record = {
        "id": new_id(),
        "program_year_id": program_year_id,
        "student_id": student_id,
        "status": "DRAFT",
        "is_renewal": is_renewal,
        "claimed_income_band": claimed_income_band,
        "claimed_category_flags": list(claimed_category_flags or []),
        "provisional_award_cents": 0,
        "verified_income_band": None,
        "verified_category_flags": [],
        "annual_award_cents": 0,
        "final_award_cents": 0,
        "priority_tier": 0,
        "priority_score": 0,
        "waitlist_position": None,
        "submitted_at": None,
        "acceptance_deadline_at": None,
        "appeal_round_count": 0,
        "created_at": created_at,
        "updated_at": created_at,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.applications[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/applications/<aid>")
def read_application(aid):
    authenticate(*READ_ROLES)
    return object_response(public(lookups.application(aid)))


@bp.get("/applications")
def list_applications():
    authenticate(*READ_ROLES)
    program_year_id = q_str("program_year_id")
    student_id = q_str("student_id")
    status = q_enum("status", APPLICATION_STATUSES)
    rows = sorted(store.applications.values(), key=lambda a: a["_seq"])
    if program_year_id:
        rows = [a for a in rows if a["program_year_id"] == program_year_id]
    if student_id:
        rows = [a for a in rows if a["student_id"] == student_id]
    if status:
        rows = [a for a in rows if a["status"] == status]
    page, meta = paginate(rows)
    return list_response([public(a) for a in page], meta)


@bp.post("/applications/<aid>/submit")
def submit_application(aid):
    user_id, _role = authenticate("Guardian")
    app = lookups.application(aid)
    if app["student_id"] != user_id:
        fail("ERR_NOT_ACCOUNT_HOLDER",
             "only the guardian of this student may submit the application")
    py = store.program_years[app["program_year_id"]]
    if not _window_is_open(py):
        fail("ERR_APPLICATION_WINDOW_CLOSED",
             "the submission window for this program year is not open")
    if app["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a DRAFT application may be submitted")

    app["status"] = "SUBMITTED"
    app["submitted_at"] = store.now()
    app["provisional_award_cents"] = calc.annual_award_amount(
        py["base_award_cents"], app["claimed_income_band"],
        app["claimed_category_flags"],
    )
    touch(app)
    return object_response(public(app))


def _sibling_committed(app, student):
    for other in store.applications.values():
        if other["id"] == app["id"]:
            continue
        if other["program_year_id"] != app["program_year_id"]:
            continue
        if other["status"] not in ("AWARD_OFFERED", "ACCEPTED"):
            continue
        other_student = store.students.get(other["student_id"])
        if other_student is None:
            continue
        if other_student["household_id"] == student["household_id"]:
            return True
    return False


@bp.post("/applications/<aid>/eligibility-determinations")
def record_determination(aid):
    user_id, _role = authenticate("EligibilityOfficer")
    payload = body()
    residency_check = v_enum(payload, "residency_check", ("PASS", "FAIL"))
    prior_enrollment_check = v_enum(payload, "prior_enrollment_check",
                                    ("PASS", "FAIL"))
    verified_income_band = v_enum(payload, "verified_income_band", INCOME_BANDS)
    verified_prior_enrollment = v_enum(payload, "verified_prior_enrollment",
                                       PRIOR_ENROLLMENTS)
    verified_category_flags = v_flag_list(payload, "verified_category_flags",
                                          CATEGORY_FLAGS)
    app = lookups.application(aid)
    py = store.program_years[app["program_year_id"]]
    if py["status"] not in ("WINDOW_OPEN", "AWARDING"):
        fail("ERR_PROGRAM_YEAR_NOT_ACTIVE",
             "determinations require the year to be WINDOW_OPEN or AWARDING")
    if app["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a SUBMITTED application may be adjudicated")

    flags = list(verified_category_flags or [])
    income_or_category = verified_income_band in ("BAND_A", "BAND_B") or bool(flags)
    eligible = (residency_check == "PASS" and prior_enrollment_check == "PASS"
                and income_or_category)

    if eligible:
        outcome = "ELIGIBLE"
        denial_reason_code = None
    else:
        outcome = "INELIGIBLE"
        if residency_check == "FAIL":
            denial_reason_code = "RESIDENCY"
        elif prior_enrollment_check == "FAIL":
            denial_reason_code = "PRIOR_ENROLLMENT"
        else:
            denial_reason_code = "INCOME_OR_CATEGORY"

    if eligible:
        student = store.students[app["student_id"]]
        tier = calc.priority_tier(
            app["is_renewal"], student["has_enrolled_sibling"],
            _sibling_committed(app, student), verified_prior_enrollment,
            verified_income_band, flags,
        )
        score = calc.priority_score(verified_income_band, flags, tier)
        award = calc.annual_award_amount(py["base_award_cents"],
                                        verified_income_band, flags)
    else:
        tier = 0
        score = 0
        award = 0

    round_number = len(lookups.determinations_of_application(aid)) + 1
    row = {
        "id": new_id(),
        "application_id": aid,
        "decided_by_user_id": user_id,
        "residency_check": residency_check,
        "prior_enrollment_check": prior_enrollment_check,
        "verified_income_band": verified_income_band,
        "verified_prior_enrollment": verified_prior_enrollment,
        "verified_category_flags": flags,
        "outcome": outcome,
        "denial_reason_code": denial_reason_code,
        "priority_tier": tier,
        "priority_score": score,
        "annual_award_cents": award,
        "round_number": round_number,
        "created_at": store.next_created_at(),
        "_seq": store.next_seq(),
    }
    store.eligibility_determinations[row["id"]] = row

    if eligible:
        app["status"] = "ELIGIBLE"
        app["verified_income_band"] = verified_income_band
        app["verified_category_flags"] = list(flags)
        app["priority_tier"] = tier
        app["priority_score"] = score
        app["annual_award_cents"] = award
    else:
        app["status"] = "DENIED"
    touch(app)
    return object_response(public(row), 201)


@bp.get("/applications/<aid>/eligibility-determinations")
def list_determinations(aid):
    authenticate(*READ_ROLES)
    lookups.application(aid)
    rows = lookups.determinations_of_application(aid)
    page, meta = paginate(rows)
    return list_response([public(r) for r in page], meta)


@bp.post("/applications/<aid>/accept-award")
def accept_award(aid):
    user_id, _role = authenticate("Guardian")
    app = lookups.application(aid)
    if app["student_id"] != user_id:
        fail("ERR_NOT_ACCOUNT_HOLDER",
             "only the guardian of this student may accept the award")
    py = store.program_years[app["program_year_id"]]
    if py["status"] != "ACTIVE":
        fail("ERR_PROGRAM_YEAR_NOT_ACTIVE",
             "award acceptance requires an ACTIVE program year")
    if app["status"] != "AWARD_OFFERED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an AWARD_OFFERED application may be accepted")
    deadline = app.get("acceptance_deadline_at")
    if not deadline or store.now() >= deadline:
        fail("ERR_INVALID_STATE_TRANSITION", "the acceptance deadline has passed")
    if py["current_quarter"] > 3:
        fail("ERR_INVALID_STATE_TRANSITION",
             "the program year has no fundable quarters left")

    quarters_remaining = 4 - py["current_quarter"]
    final_award = calc.prorated_award_cents(app["annual_award_cents"],
                                           quarters_remaining)
    app["status"] = "ACCEPTED"
    app["final_award_cents"] = final_award
    touch(app)

    created_at = store.next_created_at()
    account = {
        "id": new_id(),
        "application_id": app["id"],
        "program_year_id": py["id"],
        "status": "ACTIVE",
        "final_award_cents": final_award,
        "quarters_remaining_at_award": quarters_remaining,
        "rollover_in_cents": 0,
        "balance_cents": 0,
        "encumbered_cents": 0,
        "lifetime_disbursed_cents": 0,
        "lifetime_admin_fee_cents": 0,
        "lifetime_spent_cents": 0,
        "lifetime_clawed_back_cents": 0,
        "forfeited_cents": 0,
        "rolled_out_cents": 0,
        "rollover_carried_cents": 0,
        "disbursement_count": 0,
        "suspension_reason": None,
        "created_at": created_at,
        "updated_at": created_at,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.accounts[account["id"]] = account

    if app["is_renewal"]:
        review = None
        for candidate in sorted(store.renewal_reviews.values(),
                               key=lambda r: r["_seq"]):
            if candidate.get("renewed_application_id") == app["id"]:
                review = candidate
                break
        if review is not None:
            prior = store.accounts.get(review["account_id"])
            if prior is not None and prior["status"] == "ACTIVE":
                carried = prior["rollover_carried_cents"]
                prior["status"] = "CLOSED"
                prior["rolled_out_cents"] += carried
                prior["balance_cents"] -= carried
                account["rollover_in_cents"] = carried
                touch(prior)

    return object_response({
        "application_id": app["id"],
        "application_status": app["status"],
        "account_id": account["id"],
        "annual_award_cents": app["annual_award_cents"],
        "final_award_cents": final_award,
        "quarters_remaining_at_award": quarters_remaining,
    })


@bp.post("/applications/<aid>/withdraw")
def withdraw_application(aid):
    user_id, _role = authenticate("Guardian")
    app = lookups.application(aid)
    if app["student_id"] != user_id:
        fail("ERR_NOT_ACCOUNT_HOLDER",
             "only the guardian of this student may withdraw the award")
    if app["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only an ACCEPTED application may be withdrawn")

    py = store.program_years[app["program_year_id"]]
    app["status"] = "WITHDRAWN"
    touch(app)

    account = lookups.account_of_application(app["id"])
    if account is not None and account["status"] != "CLOSED":
        cascades.close_account(account)

    cascades.recount_seats(py)
    promoted = cascades.promote_from_waitlist(py)

    return object_response({
        "application_id": app["id"],
        "application_status": app["status"],
        "account_id": account["id"] if account is not None else None,
        "account_status": account["status"] if account is not None else None,
        "seats_committed": py["seats_committed"],
        "seats_available": py["seats_available"],
        "promoted_application_id": promoted,
    })
