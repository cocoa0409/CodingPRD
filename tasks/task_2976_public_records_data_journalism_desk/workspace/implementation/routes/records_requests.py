"""RecordsRequest endpoints (PRD sections 3.2, 3.3 and 3.4)."""
from flask import Blueprint

import clock
import db
import response
import validation as v
from errors import ApiError
from middleware import ALL_ROLES, ROLE_RECORDS_COORDINATOR, authenticate
from services import calculations, daycalc, ledger

bp = Blueprint("records_requests", __name__)

REQUESTED_FORMATS = ("CSV", "XLSX", "PDF_SCAN", "FIXED_WIDTH", "API_JSON")
DENIAL_REASON_CODES = ("EXEMPT_PRIVACY", "EXEMPT_DELIBERATIVE",
                       "EXEMPT_LAW_ENFORCEMENT", "NO_RECORDS", "FEE_UNPAID")
DECISION_OUTCOMES = ("RELEASED_FULL", "RELEASED_PARTIAL", "DENIED")
SUPERSEDABLE_STATUSES = ("DRAFT", "AWAITING_AGENCY_RESPONSE", "CLARIFICATION_REQUESTED")
WITHDRAWABLE_STATUSES = ("DRAFT", "AWAITING_AGENCY_RESPONSE",
                         "CLARIFICATION_REQUESTED", "APPEAL_FILED")
MAX_CLARIFICATION_ROUNDS = 3


def _invalid_state(current):
    return ApiError(
        "ERR_INVALID_REQUEST_STATE",
        "The operation is not declared from status %s." % current,
    )


@bp.post("/records-requests")
def create_records_request():
    user_id, _ = authenticate([ROLE_RECORDS_COORDINATOR])
    payload = v.body()
    # Rung 5 -- body schema
    desk_id = v.field_string(payload, "desk_id", min_len=1, non_blank=True)
    agency_id = v.field_string(payload, "agency_id", min_len=1, non_blank=True)
    subject_summary = v.field_string(payload, "subject_summary", min_len=1, max_len=400,
                                     non_blank=True)
    requested_format = v.field_enum(payload, "requested_format", REQUESTED_FORMATS)
    estimated_page_count = v.field_int(payload, "estimated_page_count", minimum=0, maximum=1000000)
    waiver_requested = v.field_bool(payload, "waiver_requested")
    public_interest_score = v.field_int(payload, "public_interest_score", minimum=0, maximum=100)
    expected_desk_version = v.field_int(payload, "expected_desk_version")
    supersedes_request_id = v.field_string(payload, "supersedes_request_id", min_len=1,
                                           non_blank=True, optional=True, default=None,
                                           nullable=True)
    # Rung 6 -- reference resolution in declared field order
    desk = db.get_desk(desk_id)
    db.get_agency(agency_id)
    target = None
    if supersedes_request_id is not None:
        target = db.get_request(supersedes_request_id)
    # Rung 9 -- optimistic concurrency on the desk
    if expected_desk_version != desk["version"]:
        raise ApiError(
            "ERR_STALE_DESK_VERSION",
            "expected_desk_version %s does not match the desk's current version %s."
            % (expected_desk_version, desk["version"]),
        )
    # Rung 11 -- supersede target must be live and belong to the same desk
    if target is not None:
        if target["desk_id"] != desk_id or target["status"] not in SUPERSEDABLE_STATUSES:
            raise ApiError(
                "ERR_SUPERSEDE_TARGET_NOT_ACTIVE",
                "The supersede target is not a live request on this desk.",
            )
    request_row = db.insert("records_requests", {
        "desk_id": desk_id,
        "agency_id": agency_id,
        "supersedes_request_id": supersedes_request_id,
        "requester_user_id": user_id,
        "subject_summary": subject_summary,
        "requested_format": requested_format,
        "estimated_page_count": estimated_page_count,
        "waiver_requested": waiver_requested,
        "public_interest_score": public_interest_score,
        "status": "DRAFT",
        "submitted_at": None,
        "clarification_round_count": 0,
        "clarification_opened_at": None,
        "tolled_days_total": 0,
        "due_at_strict": None,
        "due_at_tolled": None,
        "search_hours": None,
        "billed_page_count": None,
        "search_fee_cents": None,
        "duplication_fee_cents": None,
        "gross_fee_cents": None,
        "waiver_pct": None,
        "waiver_amount_cents": None,
        "net_fee_cents": None,
        "fee_committed_cents": 0,
        "fee_determined_at": None,
        "denial_reason_code": None,
    })
    desk["open_request_count"] = desk["open_request_count"] + 1
    if target is not None:
        target["status"] = "WITHDRAWN"
        if target["fee_committed_cents"]:
            ledger.release(desk, target["fee_committed_cents"])
        target["fee_committed_cents"] = 0
        desk["open_request_count"] = desk["open_request_count"] - 1
        db.touch(target)
    db.touch(desk)
    return response.created_response(db.serialize(request_row))


@bp.get("/records-requests/<request_id>")
def get_records_request(request_id):
    authenticate(ALL_ROLES)
    return response.object_response(db.serialize(db.get_request(request_id)))


@bp.get("/records-requests")
def list_records_requests():
    authenticate(ALL_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(db.ordered("records_requests"),
                           ["desk_id", "agency_id", "supersedes_request_id", "status"])
    window = rows[offset:offset + limit]
    return response.array_response(db.serialize_all(window), limit, offset, len(rows))


@bp.post("/records-requests/<request_id>/submit")
def submit(request_id):
    authenticate([ROLE_RECORDS_COORDINATOR])
    request_row = db.get_request(request_id)
    if request_row["status"] != "DRAFT":
        raise _invalid_state(request_row["status"])
    agency = db.find("agencies", request_row["agency_id"])
    now = clock.now()
    request_row["status"] = "AWAITING_AGENCY_RESPONSE"
    request_row["submitted_at"] = clock.iso(now)
    request_row["due_at_strict"] = daycalc.strict_due_at(now, agency)
    request_row["due_at_tolled"] = daycalc.tolled_due_at(now, agency,
                                                        request_row["tolled_days_total"])
    db.touch(request_row)
    return response.object_response(db.serialize(request_row))


@bp.post("/records-requests/<request_id>/fee-determination")
def fee_determination(request_id):
    authenticate([ROLE_RECORDS_COORDINATOR])
    request_row = db.get_request(request_id)
    payload = v.body()
    search_hours = v.field_number(payload, "search_hours", minimum=0)
    billed_page_count = v.field_int(payload, "billed_page_count", minimum=0)
    # Rung 10 -- state
    if request_row["status"] != "AWAITING_AGENCY_RESPONSE":
        raise _invalid_state(request_row["status"])
    # Rung 12 -- at most once per request
    if request_row["fee_determined_at"] is not None:
        raise ApiError("ERR_FEE_ALREADY_DETERMINED",
                       "A fee determination has already been recorded for this request.")
    agency = db.find("agencies", request_row["agency_id"])
    desk = db.find("desks", request_row["desk_id"])
    fees = calculations.compute_fee_determination(
        agency, request_row["waiver_requested"], request_row["public_interest_score"],
        search_hours, billed_page_count,
    )
    # Rung 38 -- nothing at all is written when the commit is unaffordable
    ledger.check_commit(desk, fees["net_fee_cents"])
    ledger.commit(desk, fees["net_fee_cents"])
    request_row["search_hours"] = search_hours
    request_row["billed_page_count"] = billed_page_count
    request_row.update(fees)
    request_row["fee_committed_cents"] = fees["net_fee_cents"]
    request_row["fee_determined_at"] = clock.now_iso()
    db.touch(request_row)
    db.touch(desk)
    return response.object_response(db.serialize(request_row))


@bp.post("/records-requests/<request_id>/clarification-request")
def clarification_request(request_id):
    authenticate([ROLE_RECORDS_COORDINATOR])
    request_row = db.get_request(request_id)
    payload = v.body()
    v.field_text(payload, "question_text")
    if request_row["status"] != "AWAITING_AGENCY_RESPONSE":
        raise _invalid_state(request_row["status"])
    agency = db.find("agencies", request_row["agency_id"])
    # Rung 15 then rung 16
    if not agency["tolling_allowed"]:
        raise ApiError("ERR_TOLLING_NOT_PERMITTED",
                       "The agency's statute does not permit tolling a clarification round.")
    if request_row["clarification_round_count"] >= MAX_CLARIFICATION_ROUNDS:
        raise ApiError("ERR_CLARIFICATION_LIMIT_REACHED",
                       "Three clarification rounds is the ceiling on any single request.")
    request_row["status"] = "CLARIFICATION_REQUESTED"
    request_row["clarification_opened_at"] = clock.now_iso()
    request_row["clarification_round_count"] = request_row["clarification_round_count"] + 1
    db.touch(request_row)
    return response.object_response(db.serialize(request_row))


@bp.post("/records-requests/<request_id>/clarification-response")
def clarification_response(request_id):
    authenticate([ROLE_RECORDS_COORDINATOR])
    request_row = db.get_request(request_id)
    payload = v.body()
    v.field_text(payload, "answer_text")
    if request_row["status"] != "CLARIFICATION_REQUESTED":
        raise _invalid_state(request_row["status"])
    agency = db.find("agencies", request_row["agency_id"])
    accrual = daycalc.tolling_days_for_span(
        clock.instant_of(request_row["clarification_opened_at"]),
        clock.now(),
        agency["deadline_basis"],
        agency.get("holiday_dates") or [],
    )
    request_row["status"] = "AWAITING_AGENCY_RESPONSE"
    request_row["tolled_days_total"] = request_row["tolled_days_total"] + accrual
    request_row["due_at_tolled"] = daycalc.tolled_due_at(
        clock.instant_of(request_row["submitted_at"]), agency, request_row["tolled_days_total"]
    )
    request_row["clarification_opened_at"] = None
    db.touch(request_row)
    return response.object_response(db.serialize(request_row))


@bp.post("/records-requests/<request_id>/agency-decision")
def agency_decision(request_id):
    authenticate([ROLE_RECORDS_COORDINATOR])
    request_row = db.get_request(request_id)
    payload = v.body()
    outcome = v.field_enum(payload, "outcome", DECISION_OUTCOMES)
    denial_reason_code = v.field_enum(payload, "denial_reason_code", DENIAL_REASON_CODES,
                                      optional=True, default=None, nullable=True)
    if outcome == "DENIED" and denial_reason_code is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "denial_reason_code is required when the outcome is DENIED.")
    if request_row["status"] != "AWAITING_AGENCY_RESPONSE":
        raise _invalid_state(request_row["status"])
    desk = db.find("desks", request_row["desk_id"])
    committed = request_row["fee_committed_cents"]
    if outcome == "RELEASED_FULL":
        request_row["status"] = "RELEASED"
        if committed:
            ledger.settle(desk, committed)
        request_row["fee_committed_cents"] = 0
        desk["open_request_count"] = desk["open_request_count"] - 1
    elif outcome == "RELEASED_PARTIAL":
        request_row["status"] = "PARTIALLY_RELEASED"
        if committed:
            ledger.settle(desk, committed)
        request_row["fee_committed_cents"] = 0
    else:
        request_row["status"] = "DENIED"
        if committed:
            ledger.release(desk, committed)
        request_row["fee_committed_cents"] = 0
        request_row["denial_reason_code"] = denial_reason_code
    db.touch(request_row)
    db.touch(desk)
    return response.object_response(db.serialize(request_row))


@bp.post("/records-requests/<request_id>/withdrawal")
def withdrawal(request_id):
    authenticate([ROLE_RECORDS_COORDINATOR])
    request_row = db.get_request(request_id)
    payload = v.body()
    v.field_text(payload, "reason")
    status = request_row["status"]
    if status not in WITHDRAWABLE_STATUSES:
        raise _invalid_state(status)
    desk = db.find("desks", request_row["desk_id"])
    committed = request_row["fee_committed_cents"]
    if status in ("AWAITING_AGENCY_RESPONSE", "CLARIFICATION_REQUESTED", "APPEAL_FILED"):
        if committed:
            ledger.release(desk, committed)
        request_row["fee_committed_cents"] = 0
    if status == "CLARIFICATION_REQUESTED":
        request_row["clarification_opened_at"] = None
    request_row["status"] = "WITHDRAWN"
    if status == "APPEAL_FILED":
        # Hops two and three: the filed appeal is withdrawn and its filing fee refunded
        for appeal in db.appeals_of_request(request_row["id"]):
            if appeal["status"] != "FILED":
                continue
            appeal["status"] = "WITHDRAWN"
            ledger.release(desk, appeal["filing_fee_cents"])
            desk["open_appeal_count"] = desk["open_appeal_count"] - 1
            db.touch(appeal)
    desk["open_request_count"] = desk["open_request_count"] - 1
    db.touch(request_row)
    db.touch(desk)
    return response.object_response(db.serialize(request_row))
