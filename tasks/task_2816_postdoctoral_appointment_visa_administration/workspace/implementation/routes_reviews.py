"""Reappointment review, grievance and exit-processing endpoints (PRD 3.8, 3.9)."""
from flask import Blueprint, request

import cascades
import serialize
from calc import (GRIEVANCE_WINDOW_DAYS, TOTAL_MONTHS_IN_RANK_CAP, notice_days_for_service,
                  term_months_between)
from envelope import paginated, success
from errors import ApiError
from guards import (ALL_ROLES, ROLE_MENTOR, ROLE_OFFICER, ROLE_POSTDOC, authenticate,
                    json_body, lookup, lookup_fk, need_enum, need_int, need_string)
from store import add_days, end_of_day_ms, new_record, sorted_records, store, touch

bp = Blueprint("reviews", __name__)

RECOMMENDATIONS = ("RENEW", "NON_RENEW")
GRIEVANCE_CATEGORIES = ("PROCEDURAL", "NOTICE_UNTIMELY", "RETALIATION")
GRIEVANCE_OUTCOMES = ("DENY", "SUSTAIN")


@bp.get("/reappointment-reviews")
def list_reappointment_reviews():
    authenticate(ALL_ROLES)
    items = list(store.reappointment_reviews.values())
    for field in ("appointment_id", "status"):
        value = request.args.get(field)
        if value is not None and value != "":
            items = [r for r in items if r[field] == value]
    return paginated(sorted_records(items), serialize.reappointment_review_out)


@bp.get("/reappointment-reviews/<record_id>")
def get_reappointment_review(record_id):
    authenticate(ALL_ROLES)
    return success(serialize.reappointment_review_out(lookup("reappointment_review", record_id)))


@bp.get("/reappointment-reviews/<record_id>/grievances")
def list_review_grievances(record_id):
    authenticate(ALL_ROLES)
    review = lookup("reappointment_review", record_id)
    items = [g for g in store.grievances.values()
             if g["reappointment_review_id"] == review["id"]]
    value = request.args.get("status")
    if value is not None and value != "":
        items = [g for g in items if g["status"] == value]
    return paginated(sorted_records(items), serialize.grievance_out)


@bp.post("/reappointment-reviews/<record_id>/recommendation")
def record_recommendation(record_id):
    user_id, _ = authenticate((ROLE_MENTOR,))
    review = lookup("reappointment_review", record_id)
    appointment = store.appointments.get(review["appointment_id"])
    # rule 4: ownership against the governing appointment's mentor.
    if appointment is None or user_id != appointment["mentor_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the appointment's mentor may record the recommendation.")
    body = json_body()
    recommendation = need_enum(body, "recommendation", RECOMMENDATIONS)
    note = need_string(body, "mentor_recommendation_note")
    if review["status"] != "OPENED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A review in %s accepts no recommendation." % review["status"])
    review["status"] = "RECOMMENDED_RENEW" if recommendation == "RENEW" \
        else "RECOMMENDED_NON_RENEW"
    review["recommendation"] = recommendation
    review["mentor_recommendation_note"] = note
    review["recommended_by_user_id"] = user_id
    touch(review)
    return success(serialize.reappointment_review_out(review))


@bp.post("/reappointment-reviews/<record_id>/finalize")
def finalize_review(record_id):
    user_id, _ = authenticate((ROLE_OFFICER,))
    review = lookup("reappointment_review", record_id)
    body = json_body()
    decision = need_enum(body, "decision", RECOMMENDATIONS)
    appointment = store.appointments.get(review["appointment_id"])
    # rule 6: the decision must agree with the recommendation and the appointment be ACTIVE.
    required_state = "RECOMMENDED_RENEW" if decision == "RENEW" else "RECOMMENDED_NON_RENEW"
    if review["status"] != required_state:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A %s decision is unavailable from %s." % (decision, review["status"]))
    if appointment is None or appointment["appointment_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Finalization requires an ACTIVE appointment.")

    issued_at = store.now()
    service_months = (appointment["months_in_rank_at_start"] or 0) + term_months_between(
        appointment["term_start_date"], issued_at.date())
    projection = None
    notice_days = None
    notice_deadline = None
    notice_timely = None
    required_end = None
    if decision == "NON_RENEW":
        notice_days = notice_days_for_service(service_months)
        notice_deadline = add_days(appointment["term_end_date"], -notice_days)
        notice_timely = issued_at.date() <= notice_deadline
        if not notice_timely:
            required_end = add_days(issued_at.date(), notice_days)
            projection = cascades.preview_term_and_money(appointment, required_end)
            # rule 15: the rank ceiling is re-tested against the extended term.
            if projection["cumulative"] > TOTAL_MONTHS_IN_RANK_CAP:
                raise ApiError("ERR_RANK_YEARS_EXCEEDED",
                               "The notice extension would breach the 60-month rank ceiling.")
    # rule 23: segregation of duties.
    if user_id == review["recommended_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The recommending mentor may not finalize this review.")
    # rule 31: the extension may not overdraw the award.
    if projection is not None and projection["available_balance"] < 0:
        raise ApiError("ERR_FUNDING_BUDGET_EXCEEDED",
                       "The notice extension would overdraw the award.")

    review["finalized_by_user_id"] = user_id
    review["decision"] = decision
    review["service_months_at_review"] = service_months

    if decision == "RENEW":
        review["status"] = "FINALIZED_RENEWED"
        touch(review)
        # CH-D: renewal re-opens research security.
        cascades.open_screening_cycle(appointment)
        appointment["compliance_status"] = "PENDING_REVIEW"
        touch(appointment)
        cascades.suspend_grants_for_compliance(appointment)
        return success(serialize.reappointment_review_out(review))

    review["status"] = "FINALIZED_NON_RENEWED"
    review["notice_issued_at"] = issued_at
    review["notice_days_required"] = notice_days
    review["notice_deadline_date"] = notice_deadline
    review["notice_timely"] = notice_timely
    review["pre_notice_term_end_date"] = appointment["term_end_date"]
    review["grievance_window_end"] = end_of_day_ms(
        add_days(issued_at.date(), GRIEVANCE_WINDOW_DAYS))
    if not notice_timely:
        review["term_extension_days"] = (required_end - appointment["term_end_date"]).days
        appointment["term_end_date"] = required_end
        cascades.recompute_term_and_money(appointment)
    touch(review)
    appointment["appointment_status"] = "NON_RENEWED"
    touch(appointment)
    cascades.post_rank_months(appointment)
    return success(serialize.reappointment_review_out(review))


@bp.post("/grievances")
def file_grievance():
    user_id, _ = authenticate((ROLE_POSTDOC,))
    body = json_body()
    # rule 3: body foreign keys in declaration order.
    review = lookup_fk(body, "reappointment_review_id", "reappointment_review")
    appointment = None
    if review is not None:
        appointment = store.appointments.get(review["appointment_id"])
        # rule 4: ownership.
        if appointment is None or user_id != appointment["postdoc_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER",
                           "Only the appointed scholar may file this grievance.")
    # rule 5: request shape.
    need_string(body, "reappointment_review_id")
    category = need_enum(body, "category", GRIEVANCE_CATEGORIES)
    narrative = need_string(body, "narrative")
    # rule 26: the grievance window.
    window_end = review["grievance_window_end"]
    if window_end is None or store.now() > window_end:
        raise ApiError("ERR_GRIEVANCE_WINDOW_CLOSED",
                       "The grievance window for this review is not open.")
    record = new_record()
    record.update({
        "reappointment_review_id": review["id"],
        "category": category,
        "narrative": narrative,
        "status": "FILED",
        "filed_at": store.now(),
        "filed_by_user_id": user_id,
        "resolution_note": None,
        "resolved_by_user_id": None,
    })
    store.grievances[record["id"]] = record
    return success(serialize.grievance_out(record), 201)


@bp.post("/grievances/<record_id>/resolution")
def resolve_grievance(record_id):
    user_id, _ = authenticate((ROLE_OFFICER,))
    grievance = lookup("grievance", record_id)
    body = json_body()
    outcome = need_enum(body, "outcome", GRIEVANCE_OUTCOMES)
    note = need_string(body, "resolution_note")
    if grievance["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A grievance in %s may not be resolved." % grievance["status"])
    review = store.reappointment_reviews.get(grievance["reappointment_review_id"])
    # rule 23: segregation of duties.
    if review is not None and user_id == review["finalized_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The finalizing officer may not resolve this grievance.")
    appointment = None
    if review is not None:
        appointment = store.appointments.get(review["appointment_id"])
    reinstating = (outcome == "SUSTAIN" and appointment is not None
                   and appointment["appointment_status"] == "NON_RENEWED")
    if reinstating and review["pre_notice_term_end_date"] is not None:
        projection = cascades.preview_term_and_money(
            appointment, review["pre_notice_term_end_date"])
        if projection["available_balance"] < 0:
            raise ApiError("ERR_FUNDING_BUDGET_EXCEEDED",
                           "The reinstatement would overdraw the award.")

    grievance["resolution_note"] = note
    grievance["resolved_by_user_id"] = user_id
    if outcome == "DENY":
        grievance["status"] = "RESOLVED_DENIED"
        touch(grievance)
        return success(serialize.grievance_out(grievance))

    grievance["status"] = "RESOLVED_SUSTAINED"
    touch(grievance)
    if review is not None:
        review["status"] = "FINALIZED_RENEWED"
        review["notice_issued_at"] = None
        review["notice_timely"] = None
        review["grievance_window_end"] = None
        touch(review)
    if reinstating:
        # CH-C: the three reversal steps run in this normative order.
        cascades.debit_rank_months(appointment)
        if review["pre_notice_term_end_date"] is not None:
            appointment["term_end_date"] = review["pre_notice_term_end_date"]
        review["term_extension_days"] = 0
        appointment["appointment_status"] = "ACTIVE"
        appointment["reinstated_count"] = (appointment["reinstated_count"] or 0) + 1
        cascades.recompute_term_and_money(appointment)
    return success(serialize.grievance_out(grievance))


@bp.post("/exit-records/<record_id>/ip-assignment")
def sign_ip_assignment(record_id):
    user_id, _ = authenticate((ROLE_POSTDOC,))
    exit_record = lookup("exit_record", record_id)
    appointment = store.appointments.get(exit_record["appointment_id"])
    # rule 4: ownership.
    if appointment is None or user_id != appointment["postdoc_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the appointed scholar may sign the assignment.")
    body = json_body()
    disclosure_count = need_int(body, "ip_disclosure_count", minimum=0)
    if exit_record["status"] != "INITIATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "An exit record in %s may not be signed." % exit_record["status"])
    exit_record["ip_assignment_signed_at"] = store.now()
    exit_record["ip_disclosure_count"] = disclosure_count
    exit_record["lab_access_cleared"] = cascades.lab_access_cleared(appointment["id"])
    exit_record["status"] = "IP_ASSIGNMENT_SIGNED"
    touch(exit_record)
    if exit_record["lab_access_cleared"]:
        cascades.close_exit_record(exit_record)
    return success(serialize.exit_record_out(exit_record))
