"""Appointment lifecycle endpoints (PRD 3.2, 3.3, 3.7) and the reverse-lookup reads."""
from decimal import Decimal

from flask import Blueprint, request

import cascades
import serialize
from calc import (MAX_TERM_MONTHS, MIN_TERM_MONTHS, TOTAL_MONTHS_IN_RANK_CAP,
                  ABSOLUTE_STIPEND_FLOOR_USD, benefits_package, effective_floor,
                  encumbrance, encumbered_total, eligible_visa_categories,
                  months_in_rank_at_start, overlap_days, salary_floor,
                  select_visa_category, term_months_between)
from envelope import paginated, success
from errors import ApiError
from guards import (ALL_ROLES, ROLE_HR, ROLE_OFFICER, ROLE_POSTDOC, authenticate, bad,
                    json_body, lookup, lookup_fk, need_amount, need_date, need_enum,
                    need_int, need_string, opt_enum)
from store import new_record, q2, sorted_records, store, touch

bp = Blueprint("appointments", __name__)

TITLE_CLASSIFICATIONS = ("POSTDOC_FELLOW", "POSTDOC_SCHOLAR_EMPLOYEE", "POSTDOC_ASSOCIATE")
EMPLOYMENT_CLASSES = ("EMPLOYEE", "FELLOWSHIP")
WITHDRAW_REASONS = ("VISA_DENIED", "VISA_DELAY_TERM_TOO_SHORT", "CANDIDATE_DECLINED",
                    "FUNDING_LOST")
PROCESSING_TRACKS = ("STANDARD", "PREMIUM")
EXIT_REASONS = ("TERM_COMPLETION", "NON_RENEWAL", "RESIGNATION", "COMPLIANCE_TERMINATION")
TERM_OVERLAP_STATUSES = ("OFFER_ISSUED", "OFFER_ACCEPTED", "ACTIVE")
FELLOWSHIP_FUNDING_TYPES = ("EXTERNAL_FELLOWSHIP", "INSTITUTIONAL_FELLOWSHIP")
EMPLOYEE_FUNDING_TYPES = ("FEDERAL_GRANT", "FOUNDATION_GRANT")


@bp.post("/appointments")
def draft_appointment():
    user_id, _ = authenticate((ROLE_OFFICER,))
    body = json_body()
    # rule 3: body foreign keys in declaration order.
    postdoc = lookup_fk(body, "postdoc_id", "postdoc")
    mentor = lookup_fk(body, "mentor_id", "mentor")
    funding_source = lookup_fk(body, "funding_source_id", "funding_source")
    predecessor = lookup_fk(body, "predecessor_appointment_id", "appointment")
    # rule 5: request shape.
    need_string(body, "postdoc_id")
    need_string(body, "mentor_id")
    need_string(body, "funding_source_id")
    title_classification = need_enum(body, "title_classification", TITLE_CLASSIFICATIONS)
    employment_class = need_enum(body, "employment_class", EMPLOYMENT_CLASSES)
    term_start = need_date(body, "term_start_date")
    term_end = need_date(body, "term_end_date")
    if term_end <= term_start:
        bad("term_end_date must be strictly after term_start_date.")
    salary = need_amount(body, "annual_salary_usd", positive=True)
    if postdoc is None or mentor is None or funding_source is None:
        bad("postdoc_id, mentor_id and funding_source_id are required.")

    record = new_record()
    record.update({
        "postdoc_id": postdoc["id"],
        "mentor_id": mentor["id"],
        "funding_source_id": funding_source["id"],
        "predecessor_appointment_id": predecessor["id"] if predecessor is not None else None,
        "title_classification": title_classification,
        "employment_class": employment_class,
        "term_start_date": term_start,
        "term_end_date": term_end,
        "annual_salary_usd": q2(salary),
        "appointment_status": "DRAFT",
        "compliance_status": "PENDING_REVIEW",
        "prepared_by_user_id": user_id,
        "term_months": 0,
        "months_in_rank_at_start": 0,
        "cumulative_months_in_rank_at_end": 0,
        "salary_floor_usd": Decimal("0.00"),
        "salary_exception_floor_usd": None,
        "salary_exception_approved_by_user_id": None,
        "benefits_package": "NONE",
        "fringe_rate": None,
        "encumbrance_usd": Decimal("0.00"),
        "withdraw_reason": None,
        "reinstated_count": 0,
    })

    # rule 12: class-to-award pairing.
    funding_type = funding_source["funding_type"]
    if employment_class == "FELLOWSHIP" and funding_type not in FELLOWSHIP_FUNDING_TYPES:
        raise ApiError("ERR_FUNDING_CLASS_MISMATCH",
                       "A FELLOWSHIP appointment requires a fellowship award.")
    if employment_class == "EMPLOYEE" and funding_type not in EMPLOYEE_FUNDING_TYPES:
        raise ApiError("ERR_FUNDING_CLASS_MISMATCH",
                       "An EMPLOYEE appointment requires a grant award.")
    # rule 13: title-to-class pairing.
    if title_classification in ("POSTDOC_SCHOLAR_EMPLOYEE", "POSTDOC_ASSOCIATE") \
            and employment_class != "EMPLOYEE":
        raise ApiError("ERR_TITLE_CLASS_MISMATCH",
                       "%s requires employment_class EMPLOYEE." % title_classification)
    if title_classification == "POSTDOC_FELLOW" and employment_class != "FELLOWSHIP":
        raise ApiError("ERR_TITLE_CLASS_MISMATCH",
                       "POSTDOC_FELLOW requires employment_class FELLOWSHIP.")
    # rule 14: mentor training currency.
    if mentor["mentor_training_valid_through"] < term_start:
        raise ApiError("ERR_MENTOR_TRAINING_LAPSED",
                       "The mentor's training lapses before the term starts.")
    # rank quantities are needed by rules 15 and 16 and by the salary floor.
    cascades.recompute_rank_figures(record)
    if record["cumulative_months_in_rank_at_end"] > TOTAL_MONTHS_IN_RANK_CAP:
        raise ApiError("ERR_RANK_YEARS_EXCEEDED",
                       "cumulative_months_in_rank_at_end may not exceed 60 months.")
    if record["term_months"] < MIN_TERM_MONTHS or record["term_months"] > MAX_TERM_MONTHS:
        raise ApiError("ERR_TERM_LENGTH_INVALID",
                       "term_months must lie between 12 and 36 months inclusive.")
    # rule 25: term overlap with the scholar's other held appointments.
    for other in store.appointments.values():
        if other["postdoc_id"] != postdoc["id"]:
            continue
        if other["appointment_status"] not in TERM_OVERLAP_STATUSES:
            continue
        if term_start <= other["term_end_date"] and other["term_start_date"] <= term_end:
            raise ApiError("ERR_APPOINTMENT_TERM_OVERLAP",
                           "The term overlaps another held appointment of this scholar.")

    record["salary_floor_usd"] = salary_floor(
        record, funding_source, record["months_in_rank_at_start"])
    record["benefits_package"] = benefits_package(record, funding_source)
    store.appointments[record["id"]] = record
    return success(serialize.appointment_out(record), 201)


@bp.get("/appointments")
def list_appointments():
    authenticate(ALL_ROLES)
    items = list(store.appointments.values())
    for field in ("postdoc_id", "mentor_id", "funding_source_id",
                  "predecessor_appointment_id", "appointment_status", "compliance_status"):
        value = request.args.get(field)
        if value is not None and value != "":
            items = [a for a in items if a.get(field) == value]
    return paginated(sorted_records(items), serialize.appointment_out)


@bp.get("/appointments/<record_id>")
def get_appointment(record_id):
    authenticate(ALL_ROLES)
    return success(serialize.appointment_out(lookup("appointment", record_id)))


@bp.post("/appointments/<record_id>/salary-exception")
def approve_salary_exception(record_id):
    user_id, _ = authenticate((ROLE_HR,))
    appointment = lookup("appointment", record_id)
    body = json_body()
    expected_version = need_int(body, "expected_appointment_version")
    exception_floor = need_amount(body, "exception_floor_usd")
    need_string(body, "justification")
    # rule 7: optimistic concurrency.
    if expected_version != appointment["version"]:
        raise ApiError("ERR_STALE_APPOINTMENT_VERSION",
                       "The appointment has been modified since it was read.")
    # rule 23: segregation of duties.
    if user_id == appointment["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The preparing officer may not approve the salary exception.")
    # rule 36: exception floor bounds.
    floor = q2(exception_floor)
    if floor < ABSOLUTE_STIPEND_FLOOR_USD or floor >= q2(appointment["salary_floor_usd"]):
        raise ApiError("ERR_EXCEPTION_FLOOR_INVALID",
                       "exception_floor_usd must be at least 54000.00 and below the "
                       "computed salary floor.")
    appointment["salary_exception_floor_usd"] = floor
    appointment["salary_exception_approved_by_user_id"] = user_id
    touch(appointment)
    return success(serialize.appointment_out(appointment))


@bp.post("/appointments/<record_id>/issue-offer")
def issue_offer(record_id):
    authenticate((ROLE_OFFICER,))
    appointment = lookup("appointment", record_id)
    json_body()
    if appointment["appointment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a DRAFT appointment may have an offer issued.")
    postdoc = cascades.appointment_postdoc(appointment)
    mentor = cascades.appointment_mentor(appointment)
    funding_source = cascades.appointment_funding(appointment)
    # rule 11: funding posture.
    if funding_source["verification_status"] != "VERIFIED" \
            or appointment["term_start_date"] < funding_source["award_start_date"]:
        raise ApiError("ERR_FUNDING_NOT_VERIFIED",
                       "The award is not verified for this term start date.")
    # rule 29: mentor load.
    if mentor["active_postdoc_count"] >= mentor["max_concurrent_postdocs"]:
        raise ApiError("ERR_MENTOR_LOAD_EXCEEDED",
                       "The mentor is already at the concurrent-postdoc ceiling.")
    # rule 30: salary floor, measured against the freshly computed policy floor.
    at_start = months_in_rank_at_start(appointment, postdoc)
    months = term_months_between(appointment["term_start_date"], appointment["term_end_date"])
    floor = salary_floor(appointment, funding_source, at_start)
    probe = dict(appointment)
    probe["salary_floor_usd"] = floor
    if q2(appointment["annual_salary_usd"]) < q2(effective_floor(probe)):
        raise ApiError("ERR_SALARY_BELOW_FLOOR",
                       "annual_salary_usd is below the effective salary floor.")
    # rule 35: the term must share a day with the award window.
    if overlap_days(appointment, funding_source) <= 0:
        raise ApiError("ERR_AWARD_TERM_NO_OVERLAP",
                       "The term and the award window share no day.")
    probe["term_months"] = months
    rate, amount = encumbrance(probe, funding_source)
    # rule 31: award budget authority.
    if q2(encumbered_total(funding_source["id"]) + amount) > q2(funding_source["annual_budget_usd"]):
        raise ApiError("ERR_FUNDING_BUDGET_EXCEEDED",
                       "The encumbrance would exceed the award's budget authority.")

    appointment["salary_floor_usd"] = floor
    appointment["term_months"] = months
    appointment["months_in_rank_at_start"] = at_start
    appointment["cumulative_months_in_rank_at_end"] = at_start + months
    appointment["benefits_package"] = benefits_package(appointment, funding_source)
    appointment["fringe_rate"] = rate
    appointment["encumbrance_usd"] = amount
    appointment["appointment_status"] = "OFFER_ISSUED"
    touch(appointment)
    cascades.refresh_funding_ledger(funding_source)
    cascades.open_screening_cycle(appointment)
    for doc_type, flag in (("MENTORING_PLAN", "requires_mentoring_plan"),
                           ("IDP", "requires_idp")):
        if funding_source[flag]:
            document = new_record()
            document.update({
                "appointment_id": appointment["id"],
                "doc_type": doc_type,
                "status": "DRAFT",
                "content_summary": None,
                "postdoc_acknowledged": False,
                "revision_round": 0,
                "submitted_by_user_id": None,
                "approved_at": None,
            })
            store.development_documents[document["id"]] = document
    return success(serialize.appointment_out(appointment))


@bp.post("/appointments/<record_id>/accept-offer")
def accept_offer(record_id):
    user_id, _ = authenticate((ROLE_POSTDOC,))
    appointment = lookup("appointment", record_id)
    if user_id != appointment["postdoc_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the appointed scholar may accept this offer.")
    body = json_body()
    track = opt_enum(body, "processing_track", PROCESSING_TRACKS, "STANDARD")
    if appointment["appointment_status"] != "OFFER_ISSUED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an OFFER_ISSUED appointment may be accepted.")
    postdoc = cascades.appointment_postdoc(appointment)
    category = None
    if postdoc["requires_sponsorship"]:
        category = select_visa_category(appointment, postdoc)
        if category is None:
            raise ApiError("ERR_NO_ELIGIBLE_VISA_CATEGORY",
                           "No visa category is available for this scholar and term.")
        if track == "PREMIUM" and category not in ("H1B", "O1"):
            raise ApiError("ERR_PREMIUM_TRACK_UNAVAILABLE",
                           "Premium processing is unavailable for %s." % category)
    appointment["appointment_status"] = "OFFER_ACCEPTED"
    touch(appointment)
    if category is not None:
        case = new_record()
        case.update({
            "appointment_id": appointment["id"],
            "visa_category": category,
            "processing_track": track,
            "status": "DOCS_PENDING",
            "filed_at": None,
            "rfe_round_count": 0,
            "projection_variant": None,
            "projected_decision_date": None,
            "earliest_lawful_start_date": None,
            "decided_at": None,
        })
        store.visa_cases[case["id"]] = case
    return success(serialize.appointment_out(appointment))


@bp.post("/appointments/<record_id>/activate")
def activate_appointment(record_id):
    authenticate((ROLE_OFFICER,))
    appointment = lookup("appointment", record_id)
    json_body()
    # rule 6: both dimensions must offer the transition.
    if appointment["appointment_status"] != "OFFER_ACCEPTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only an OFFER_ACCEPTED appointment may be activated.")
    if appointment["compliance_status"] not in ("CLEARED", "RESTRICTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "An appointment in %s offers no activation transition."
                       % appointment["compliance_status"])
    postdoc = cascades.appointment_postdoc(appointment)
    mentor = cascades.appointment_mentor(appointment)
    # rule 14: mentor training currency.
    if mentor["mentor_training_valid_through"] < appointment["term_start_date"]:
        raise ApiError("ERR_MENTOR_TRAINING_LAPSED",
                       "The mentor's training lapses before the term starts.")
    # rule 16: term length after any visa-driven deferral.
    if appointment["term_months"] < MIN_TERM_MONTHS or appointment["term_months"] > MAX_TERM_MONTHS:
        raise ApiError("ERR_TERM_LENGTH_INVALID",
                       "term_months must lie between 12 and 36 months inclusive.")
    # rule 20: funder document completeness.
    for document in cascades.appointment_documents(appointment["id"]):
        if document["status"] != "APPROVED":
            raise ApiError("ERR_DEVELOPMENT_DOCS_INCOMPLETE",
                           "Every development document must be APPROVED before activation.")
    if postdoc["requires_sponsorship"]:
        case = cascades.latest_visa_case(appointment["id"])
        # rule 22: visa approval.
        if case is None or case["status"] != "APPROVED":
            raise ApiError("ERR_VISA_NOT_APPROVED",
                           "The latest visa case has not been approved.")
        # rule 24: lawful start.
        if case["earliest_lawful_start_date"] is not None \
                and appointment["term_start_date"] < case["earliest_lawful_start_date"]:
            raise ApiError("ERR_START_BEFORE_LAWFUL_DATE",
                           "term_start_date precedes the earliest lawful start date.")
    # rule 29: mentor load.
    if mentor["active_postdoc_count"] >= mentor["max_concurrent_postdocs"]:
        raise ApiError("ERR_MENTOR_LOAD_EXCEEDED",
                       "The mentor is already at the concurrent-postdoc ceiling.")

    appointment["appointment_status"] = "ACTIVE"
    touch(appointment)
    if postdoc["status"] == "PROSPECTIVE":
        postdoc["status"] = "ACTIVE"
        touch(postdoc)
    mentor["active_postdoc_count"] = (mentor["active_postdoc_count"] or 0) + 1
    touch(mentor)
    return success(serialize.appointment_out(appointment))


@bp.post("/appointments/<record_id>/withdraw")
def withdraw_appointment(record_id):
    authenticate((ROLE_OFFICER,))
    appointment = lookup("appointment", record_id)
    body = json_body()
    reason = need_enum(body, "withdraw_reason", WITHDRAW_REASONS)
    if appointment["appointment_status"] not in ("DRAFT", "OFFER_ISSUED", "OFFER_ACCEPTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "An appointment in %s may not be withdrawn."
                       % appointment["appointment_status"])
    cascades.withdraw_appointment(appointment, reason)
    return success(serialize.appointment_out(appointment))


@bp.get("/appointments/<record_id>/visa-cases")
def list_appointment_visa_cases(record_id):
    authenticate(ALL_ROLES)
    appointment = lookup("appointment", record_id)
    cases = cascades.appointment_visa_cases(appointment["id"])
    return paginated(sorted_records(cases), serialize.visa_case_out)


@bp.get("/appointments/<record_id>/development-documents")
def list_appointment_documents(record_id):
    authenticate(ALL_ROLES)
    appointment = lookup("appointment", record_id)
    documents = cascades.appointment_documents(appointment["id"])
    for field in ("doc_type", "status"):
        value = request.args.get(field)
        if value is not None and value != "":
            documents = [d for d in documents if d[field] == value]
    return paginated(sorted_records(documents), serialize.development_document_out)


@bp.get("/appointments/<record_id>/export-control-reviews")
def list_appointment_reviews(record_id):
    authenticate(ALL_ROLES)
    appointment = lookup("appointment", record_id)
    reviews = cascades.appointment_reviews(appointment["id"])
    value = request.args.get("status")
    if value is not None and value != "":
        reviews = [r for r in reviews if r["status"] == value]
    reviews.sort(key=lambda r: (r["cycle_index"], r["_seq"]))
    return paginated(reviews, serialize.export_control_review_out)


@bp.get("/appointments/<record_id>/exit-record")
def list_appointment_exit_record(record_id):
    authenticate(ALL_ROLES)
    appointment = lookup("appointment", record_id)
    records = cascades.appointment_exit_records(appointment["id"])
    return paginated(sorted_records(records), serialize.exit_record_out)


@bp.post("/appointments/<record_id>/reappointment-reviews")
def open_reappointment_review(record_id):
    authenticate((ROLE_OFFICER,))
    appointment = lookup("appointment", record_id)
    json_body()
    highest = 0
    for review in cascades.appointment_reappointment_reviews(appointment["id"]):
        if review["status"] not in ("FINALIZED_RENEWED", "FINALIZED_NON_RENEWED"):
            raise ApiError("ERR_REVIEW_ALREADY_OPEN",
                           "A reappointment review is already open for this appointment.")
        if review["review_cycle"] > highest:
            highest = review["review_cycle"]
    record = new_record()
    record.update({
        "appointment_id": appointment["id"],
        "review_cycle": highest + 1,
        "status": "OPENED",
        "recommendation": None,
        "mentor_recommendation_note": None,
        "recommended_by_user_id": None,
        "decision": None,
        "finalized_by_user_id": None,
        "service_months_at_review": None,
        "notice_days_required": None,
        "notice_deadline_date": None,
        "notice_issued_at": None,
        "notice_timely": None,
        "term_extension_days": 0,
        "pre_notice_term_end_date": None,
        "grievance_window_end": None,
    })
    store.reappointment_reviews[record["id"]] = record
    return success(serialize.reappointment_review_out(record), 201)


@bp.post("/appointments/<record_id>/exit")
def initiate_exit(record_id):
    authenticate((ROLE_OFFICER,))
    appointment = lookup("appointment", record_id)
    body = json_body()
    exit_reason = need_enum(body, "exit_reason", EXIT_REASONS)
    if cascades.appointment_exit_records(appointment["id"]):
        raise ApiError("ERR_EXIT_ALREADY_INITIATED",
                       "An exit record already exists for this appointment.")
    record = cascades.create_exit_record(appointment, exit_reason)
    cascades.revoke_grants_for_exit(appointment)
    return success(serialize.exit_record_out(record), 201)
