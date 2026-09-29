"""Compensatory awards and the negotiation dimension (PRD section 3.7)."""
from flask import Blueprint, g, request

from auth import (CASE_MANAGER, COMPLIANCE_OFFICER, PARENT_GUARDIAN,
                  PROGRAM_COORDINATOR, SPED_DIRECTOR, endpoint, is_guardian)
from calcs import (DELIVERY_WINDOW_DAYS, MAX_DISPUTE_ROUNDS,
                   MIN_AWARDABLE_MINUTES, compensatory_award_minutes,
                   proposal_band)
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from ledgers import apply_lazy_lapse, recompute_student_ledger
from resolve import body_ref, path_ref
from serialize import due_process_packet, many, public
from store import add_days, creation_order, db, new_record, today, touch
from validate import body, req_enum, req_int, req_str

bp = Blueprint("awards", __name__)

VARIANTS = ("MINUTE_FOR_MINUTE", "QUALITATIVE_BENEFIT")
RESPONSES = ("AGREE", "DISPUTE", "DECLINE")
TERMINAL_NEGOTIATION = ("DECLINED", "CLOSED")
STAFF_READ_ROLES = (CASE_MANAGER, PROGRAM_COORDINATOR, SPED_DIRECTOR,
                    COMPLIANCE_OFFICER)


def award_for_request(award_id):
    """PRD 2.7 check 3 outranks path resolution for the guardian-visible read."""
    candidate = db.awards.get(award_id)
    if candidate is not None and is_guardian() and candidate["student_id"] != g.user_id:
        raise ApiError("ERR_NOT_STUDENT_GUARDIAN")
    return path_ref("award", award_id)


@bp.post("/esy/compensatory-awards")
@endpoint((CASE_MANAGER,))
def create_award():
    data = body()
    body_ref(data, "student_id", "student")
    body_ref(data, "source_program_id", "program")

    student_id = req_str(data, "student_id", 1, None)
    source_program_id = req_str(data, "source_program_id", 1, None)
    variant = req_enum(data, "calculation_variant", VARIANTS)

    # PRD 2.7: check 25 (no compensable minutes) masks check 30 (duplicate).
    figures = compensatory_award_minutes(student_id, source_program_id, variant)
    if figures["computed_minutes"] < MIN_AWARDABLE_MINUTES:
        raise ApiError("ERR_NO_COMPENSABLE_MINUTES")

    for existing in db.awards.values():
        if (existing["student_id"] == student_id
                and existing["source_program_id"] == source_program_id
                and existing["negotiation_status"] not in TERMINAL_NEGOTIATION):
            raise ApiError("ERR_DUPLICATE_AWARD")

    award = new_record("CompensatoryAward", {
        "student_id": student_id,
        "source_program_id": source_program_id,
        "calculation_variant": variant,
        "computed_minutes": figures["computed_minutes"],
        "proposed_minutes": None,
        "agreed_minutes": None,
        "delivered_minutes": 0,
        "scheduled_minutes": 0,
        "remaining_owed_minutes": 0,
        "forfeited_minutes": 0,
        "negotiation_status": "DRAFT",
        "delivery_status": "NOT_STARTED",
        "dispute_round_count": 0,
        "parent_no_show_count": 0,
        "delivery_deadline_date": None,
        "severity_factor": figures["severity_factor"],
        "verified_missed_log_count": figures["verified_missed_log_count"],
        "excluded_log_count": figures["excluded_log_count"],
        "authored_by_user_id": None,
        "resolved_by_user_id": None,
    })
    db.awards[award["id"]] = award
    return created(public(award))


@bp.get("/esy/compensatory-awards")
@endpoint(STAFF_READ_ROLES)
def list_awards():
    rows = list(db.awards.values())
    for key in ("student_id", "source_program_id", "negotiation_status"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    page, page_meta = paginate(creation_order(rows))
    return ok_list(many(page), page_meta)


@bp.get("/esy/compensatory-awards/<award_id>")
@endpoint(STAFF_READ_ROLES + (PARENT_GUARDIAN,))
def get_award(award_id):
    award = award_for_request(award_id)
    apply_lazy_lapse(award)
    return ok(public(award))


@bp.post("/esy/compensatory-awards/<award_id>/propose")
@endpoint((CASE_MANAGER,))
def propose_award(award_id):
    award = path_ref("award", award_id)
    apply_lazy_lapse(award)
    data = body()
    proposed = req_int(data, "proposed_minutes", 0, None)

    if award["negotiation_status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE")

    # PRD 3.7: the award's arithmetic is refreshed before the band is applied.
    figures = compensatory_award_minutes(award["student_id"],
                                        award["source_program_id"],
                                        award["calculation_variant"])
    low, high = proposal_band(figures["computed_minutes"])
    if proposed < low or proposed > high:
        raise ApiError("ERR_PROPOSAL_OUT_OF_RANGE")

    award["computed_minutes"] = figures["computed_minutes"]
    award["severity_factor"] = figures["severity_factor"]
    award["verified_missed_log_count"] = figures["verified_missed_log_count"]
    award["excluded_log_count"] = figures["excluded_log_count"]
    award["proposed_minutes"] = proposed
    award["authored_by_user_id"] = g.user_id
    award["negotiation_status"] = "PARENT_REVIEW"
    touch(award)
    return ok(public(award))


@bp.post("/esy/compensatory-awards/<award_id>/parent-response")
@endpoint((PARENT_GUARDIAN,))
def award_parent_response(award_id):
    award = award_for_request(award_id)
    apply_lazy_lapse(award)
    data = body()
    response = req_enum(data, "response", RESPONSES)

    if award["negotiation_status"] != "PARENT_REVIEW":
        raise ApiError("ERR_INVALID_STATE")

    student = db.students.get(award["student_id"])
    if response == "AGREE":
        award["agreed_minutes"] = award["proposed_minutes"]
        award["negotiation_status"] = "AGREED"
        award["delivery_deadline_date"] = add_days(today(),
                                                  DELIVERY_WINDOW_DAYS).isoformat()
        award["remaining_owed_minutes"] = max(
            0, (award["agreed_minutes"] or 0) - award["delivered_minutes"]
            - award["forfeited_minutes"])
        touch(award)
        if student is not None:
            recompute_student_ledger(student)
    elif response == "DECLINE":
        award["negotiation_status"] = "DECLINED"
        touch(award)
    else:
        award["dispute_round_count"] += 1
        if award["dispute_round_count"] >= MAX_DISPUTE_ROUNDS:
            award["negotiation_status"] = "MEDIATION"
        else:
            award["negotiation_status"] = "DISPUTED"
        touch(award)
    return ok(public(award))


@bp.post("/esy/compensatory-awards/<award_id>/resolve-dispute")
@endpoint((SPED_DIRECTOR,))
def resolve_award_dispute(award_id):
    award = path_ref("award", award_id)
    apply_lazy_lapse(award)
    data = body()
    arbitrated = req_int(data, "arbitrated_minutes", 0, None)

    if award["negotiation_status"] not in ("DISPUTED", "MEDIATION"):
        raise ApiError("ERR_INVALID_STATE")

    student = db.students.get(award["student_id"])
    if student is not None and student["stay_put_active"]:
        raise ApiError("ERR_STAY_PUT_BLOCKED")
    if award.get("authored_by_user_id") == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    low, high = proposal_band(award["computed_minutes"])
    if arbitrated < low or arbitrated > high:
        raise ApiError("ERR_PROPOSAL_OUT_OF_RANGE")

    award["agreed_minutes"] = arbitrated
    award["resolved_by_user_id"] = g.user_id
    award["delivery_deadline_date"] = add_days(today(),
                                              DELIVERY_WINDOW_DAYS).isoformat()
    award["negotiation_status"] = "AGREED"
    award["remaining_owed_minutes"] = max(
        0, arbitrated - award["delivered_minutes"] - award["forfeited_minutes"])
    touch(award)
    if student is not None:
        recompute_student_ledger(student)
    return ok(public(award))


@bp.get("/esy/compensatory-awards/<award_id>/due-process-packet")
@endpoint((SPED_DIRECTOR, COMPLIANCE_OFFICER))
def award_due_process_packet(award_id):
    award = path_ref("award", award_id)
    apply_lazy_lapse(award)
    open_count = sum(1 for r in db.records.values()
                     if r["student_id"] == award["student_id"] and r["status"] == "OPEN")
    return ok(due_process_packet(award, open_count))
