"""Research-security screening and bench-access endpoints (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import cascades
import serialize
from calc import (RESTRICTED_MAX_BENCH_SEATS, country_risk, risk_score, screening_outcome,
                  screening_tier)
from envelope import paginated, success
from errors import ApiError
from guards import (ALL_ROLES, ROLE_EXPORT, ROLE_MENTOR, authenticate, bad, json_body,
                    lookup, lookup_fk, need_date, need_int, need_string, opt_bool)
from store import new_record, sorted_records, store, touch

bp = Blueprint("security", __name__)

INCUMBENT_STATUSES = ("PROVISIONED", "SUSPENDED")
RESTRICTED_FORBIDDEN_LEVELS = ("BSL2", "BSL3")


@bp.post("/export-control-reviews/<record_id>/decision")
def decide_screening(record_id):
    user_id, _ = authenticate((ROLE_EXPORT,))
    review = lookup("export_control_review", record_id)
    body = json_body()
    restricted_party_hit = opt_bool(body, "restricted_party_hit", False)
    controlled_technology_flag = opt_bool(body, "controlled_technology_flag", False)
    if review["status"] != "QUEUED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A screening cycle in %s may not be decided." % review["status"])
    appointment = store.appointments.get(review["appointment_id"])
    # rule 23: segregation of duties.
    if appointment is not None and user_id in (appointment["prepared_by_user_id"],
                                               appointment["mentor_id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The preparing officer and the mentor may not screen this appointment.")
    postdoc = cascades.appointment_postdoc(appointment)
    funding_source = cascades.appointment_funding(appointment)

    review["restricted_party_hit"] = restricted_party_hit
    review["controlled_technology_flag"] = controlled_technology_flag
    tier = screening_tier(review, postdoc)
    score = risk_score(review, appointment, postdoc, funding_source, tier)
    review["screening_tier"] = tier
    review["risk_score"] = score
    review["deemed_export_license_required"] = bool(
        controlled_technology_flag and country_risk(postdoc["citizenship_country"]) >= 3)
    review["reviewer_user_id"] = user_id
    review["decided_at"] = store.now()
    review["status"] = screening_outcome(review, score)
    touch(review)
    cascades.apply_compliance_outcome(appointment, review)
    return success(serialize.export_control_review_out(review))


def _effective_start(grant, buffer_days):
    return grant["access_start_date"] - timedelta(days=buffer_days)


def _capacity_exceeded(laboratory, incumbents, start, end, seats, buffer_days):
    """Per-calendar-day aggregate seat test over the requested effective interval."""
    intervals = []
    for incumbent in incumbents:
        intervals.append((_effective_start(incumbent, buffer_days),
                          incumbent["access_end_date"], incumbent["bench_seats"]))
    capacity = laboratory["bench_capacity"]
    day = start
    while day <= end:
        occupied = 0
        for interval_start, interval_end, interval_seats in intervals:
            if interval_start <= day <= interval_end:
                occupied += interval_seats
        if occupied + seats > capacity:
            return True
        day = day + timedelta(days=1)
    return False


@bp.post("/lab-access-grants")
def create_lab_access_grant():
    user_id, _ = authenticate((ROLE_MENTOR,))
    body = json_body()
    # rule 3: body foreign keys in declaration order.
    appointment = lookup_fk(body, "appointment_id", "appointment")
    laboratory = lookup_fk(body, "laboratory_id", "laboratory")
    # rule 4: ownership.
    if appointment is not None and user_id != appointment["mentor_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the appointment's mentor may request bench access.")
    # rule 5: request shape.
    need_string(body, "appointment_id")
    need_string(body, "laboratory_id")
    seats = need_int(body, "bench_seats", minimum=1, maximum=10)
    access_start = need_date(body, "access_start_date")
    access_end = need_date(body, "access_end_date")
    if access_end <= access_start:
        bad("access_end_date must be strictly after access_start_date.")
    expected_version = need_int(body, "expected_appointment_version")
    if appointment is None or laboratory is None:
        bad("appointment_id and laboratory_id are required.")
    # rule 7: optimistic concurrency against the appointment.
    if expected_version != appointment["version"]:
        raise ApiError("ERR_STALE_APPOINTMENT_VERSION",
                       "The appointment has been modified since it was read.")
    # rule 8: research-security admissibility.
    if appointment["compliance_status"] not in ("CLEARED", "RESTRICTED"):
        raise ApiError("ERR_EXPORT_CONTROL_BLOCKED",
                       "The appointment's compliance posture does not admit bench access.")
    # rule 9: restricted-posture limits.
    if appointment["compliance_status"] == "RESTRICTED":
        if laboratory["biosafety_level"] in RESTRICTED_FORBIDDEN_LEVELS \
                or seats > RESTRICTED_MAX_BENCH_SEATS:
            raise ApiError("ERR_COMPLIANCE_RESTRICTION_VIOLATED",
                           "A RESTRICTED appointment may take one seat in a BSL1 laboratory only.")
    # rule 10: laboratory availability.
    if laboratory["status"] != "OPEN":
        raise ApiError("ERR_LAB_CLOSED", "The laboratory is not open to new grants.")
    # rule 14: mentor training currency.
    mentor = cascades.appointment_mentor(appointment)
    if mentor is not None and mentor["mentor_training_valid_through"] < appointment["term_start_date"]:
        raise ApiError("ERR_MENTOR_TRAINING_LAPSED",
                       "The mentor's training lapses before the term starts.")

    buffer_days = laboratory["decontamination_buffer_days"] or 0
    incumbents = [g for g in cascades.laboratory_grants(laboratory["id"])
                  if g["status"] in INCUMBENT_STATUSES]
    requested = {"access_start_date": access_start, "access_end_date": access_end,
                 "bench_seats": seats}
    buffered_start = _effective_start(requested, buffer_days)
    if _capacity_exceeded(laboratory, incumbents, buffered_start, access_end, seats, buffer_days):
        # rules 27 and 28: the buffer is the cause only when the unbuffered windows fit.
        if _capacity_exceeded(laboratory, incumbents, access_start, access_end, seats, 0):
            raise ApiError("ERR_LAB_CAPACITY_EXCEEDED",
                           "The laboratory has no room on at least one day of the interval.")
        raise ApiError("ERR_LAB_BUFFER_CONFLICT",
                       "The decontamination buffer collides with an incumbent grant.")

    record = new_record()
    record.update({
        "appointment_id": appointment["id"],
        "laboratory_id": laboratory["id"],
        "bench_seats": seats,
        "access_start_date": access_start,
        "access_end_date": access_end,
        "status": "PROVISIONED",
        "suspension_reason": "NONE",
        "requested_by_user_id": user_id,
    })
    store.lab_access_grants[record["id"]] = record
    touch(appointment)
    return success(serialize.lab_access_grant_out(record), 201)


@bp.get("/lab-access-grants")
def list_lab_access_grants():
    authenticate(ALL_ROLES)
    items = list(store.lab_access_grants.values())
    for field in ("appointment_id", "laboratory_id", "status"):
        value = request.args.get(field)
        if value is not None and value != "":
            items = [g for g in items if g[field] == value]
    return paginated(sorted_records(items), serialize.lab_access_grant_out)


@bp.get("/lab-access-grants/<record_id>")
def get_lab_access_grant(record_id):
    authenticate(ALL_ROLES)
    return success(serialize.lab_access_grant_out(lookup("lab_access_grant", record_id)))
