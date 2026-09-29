"""Protests, the hearing docket, market studies and the good-cause standard.

PRD sections 3.5, 3.6 and 3.7.
"""

from datetime import timedelta

from flask import Blueprint, request

import calc
import cascade
import db
import derive
import enums
import response
import serializers
import validation as v
from errors import ApiError
from middleware import guard, require_dealer_owner, require_manufacturer_owner

bp = Blueprint("protests", __name__)

READ_ROLES = ["BoardAdmin", "HearingClerk", "LicensingAnalyst", "Dealer", "Manufacturer"]
LOG_READ_ROLES = ["BoardAdmin", "HearingClerk", "Dealer", "Manufacturer"]
ANALYSIS_READ_ROLES = ["BoardAdmin", "HearingClerk", "Dealer", "Manufacturer"]

PROTESTABLE_FILING_STATES = ("NOTICE_SERVED", "PROTEST_PENDING")
DUPLICATE_PROTEST_STATES = ("FILED", "SCHEDULED", "HEARD", "SUSTAINED", "DENIED", "APPEALED")
TENDER_STATES = ("FILED", "SCHEDULED")
HEARING_WINDOW_OPENS_DAYS = 30
HEARING_WINDOW_CLOSES_DAYS = 180
EVIDENCE_DEADLINE_DAYS_BEFORE = 7
APPEAL_WINDOW_DAYS = 30
LOST_STANDING_STATES = ("SUSPENDED", "EXPIRED", "REVOKED", "CANCELLED")


def _find(record_id):
    record = db.get("protest", record_id)
    if record is None:
        raise ApiError("ERR_PROTEST_NOT_FOUND", "No such protest")
    return record


def _filing_of(protest):
    return db.get("franchise_filing", protest["franchise_filing_id"])


def _manufacturer_of(protest):
    filing = _filing_of(protest)
    return None if filing is None else db.get("manufacturer", filing["manufacturer_id"])


def _refresh_filing_protest_count(filing):
    if filing is None:
        return
    derive.set_counter(filing, "active_protest_count", derive.active_protest_count(filing["id"]))
    db.touch(filing)


@bp.post("/protests")
def create_protest():
    caller = guard(["Dealer"])
    peeked = v.peek_body()
    if isinstance(peeked.get("protestant_dealer_id"), str):
        require_dealer_owner(caller, peeked["protestant_dealer_id"])

    body = v.read_body()
    franchise_filing_id = v.req_string(body, "franchise_filing_id", 1, 100)
    protestant_dealer_id = v.req_string(body, "protestant_dealer_id", 1, 100)
    grounds_code = v.req_enum(body, "grounds_code", enums.GROUNDS_CODES)
    expected_version = v.req_int(body, "expected_franchise_filing_version", 1)

    filing = db.get("franchise_filing", franchise_filing_id)
    if filing is None:
        raise ApiError("ERR_FILING_NOT_FOUND", "No such franchise filing")
    dealer = db.get("dealer", protestant_dealer_id)
    if dealer is None:
        raise ApiError("ERR_DEALER_NOT_FOUND", "No such dealership")

    if expected_version != filing["version"]:
        raise ApiError("ERR_STALE_FILING_VERSION", "The filing has moved since it was read")
    if filing["status"] not in PROTESTABLE_FILING_STATES:
        raise ApiError("ERR_INVALID_FILING_STATE", "A filing in %s is not open to protest" % filing["status"])
    if dealer["license_status"] != "LICENSED":
        raise ApiError("ERR_DEALER_LICENSE_NOT_ACTIVE", "Only a LICENSED dealership may protest")

    if dealer["line_make"] != filing["line_make"]:
        raise ApiError("ERR_LINE_MAKE_MISMATCH", "The protestant does not carry the filing's line make")

    distance = None
    if filing["filing_type"] == "TERMINATION":
        if dealer["id"] != filing.get("affected_dealer_id"):
            raise ApiError("ERR_NOT_INCUMBENT_DEALER", "Only the terminated dealership may protest")
    else:
        if dealer["id"] == filing.get("affected_dealer_id"):
            raise ApiError("ERR_NOT_INCUMBENT_DEALER", "The affected dealership is not the incumbent here")
        if dealer["franchise_status"] not in ("FRANCHISED", "TERMINATION_PENDING"):
            raise ApiError("ERR_NOT_INCUMBENT_DEALER", "The protestant holds no franchise in the market")
        distance = calc.planar_distance_km(
            filing["site_x_km"], filing["site_y_km"], dealer["site_x_km"], dealer["site_y_km"]
        )
        if distance > calc.RELEVANT_MARKET_RADIUS_KM:
            raise ApiError("ERR_OUTSIDE_RELEVANT_MARKET", "The proposed site lies outside the relevant market")

    reference_date = db.today()
    if filing.get("protest_window_ends_on") is not None and reference_date > filing["protest_window_ends_on"]:
        raise ApiError("ERR_PROTEST_WINDOW_CLOSED", "The 30-day protest window has closed")

    for existing in db.where("protest", franchise_filing_id=filing["id"]):
        if existing["protestant_dealer_id"] == dealer["id"] and existing["status"] in DUPLICATE_PROTEST_STATES:
            raise ApiError("ERR_DUPLICATE_PROTEST", "The protestant already holds a live protest on this filing")

    record = db.insert("protest", {
        "franchise_filing_id": filing["id"],
        "protestant_dealer_id": dealer["id"],
        "hearing_room_id": None,
        "status": "FILED",
        "grounds_code": grounds_code,
        "filed_on": reference_date,
        "distance_to_site_km": distance,
        "hearing_start_at": None,
        "hearing_end_at": None,
        "hearing_session_count": None,
        "evidence_deadline_at": None,
        "accepted_evidence_pages": 0,
        "late_evidence_count": 0,
        "good_cause_score": None,
        "good_cause_threshold": calc.good_cause_threshold(filing["filing_type"]),
        "decided_on": None,
        "findings_note": None,
        "assessment_total_cents": None,
        "protestant_share_cents": None,
        "manufacturer_share_cents": None,
        "appeal_filed_on": None,
        "appellant_party": None,
        "court_docket_number": None,
    })

    if filing["status"] == "NOTICE_SERVED":
        filing["status"] = "PROTEST_PENDING"
    _refresh_filing_protest_count(filing)
    derive.recompute_all()
    return response.object_response(serializers.protest(record), 201)


@bp.post("/protests/<record_id>/schedule")
def schedule_protest(record_id):
    guard(["HearingClerk"])
    body = v.read_body()
    hearing_room_id = v.req_string(body, "hearing_room_id", 1, 100)
    hearing_start_at = v.req_instant(body, "hearing_start_at")
    hearing_end_at = v.req_instant(body, "hearing_end_at")
    hearing_session_count = v.req_int(body, "hearing_session_count", 1, 3)
    expected_version = v.req_int(body, "expected_hearing_room_version", 1)

    protest = _find(record_id)
    room = db.get("hearing_room", hearing_room_id)
    if room is None:
        raise ApiError("ERR_HEARING_ROOM_NOT_FOUND", "No such hearing room")
    if expected_version != room["version"]:
        raise ApiError("ERR_STALE_ROOM_VERSION", "The room's booking sheet has moved since it was read")
    if protest["status"] != "FILED":
        raise ApiError("ERR_INVALID_PROTEST_STATE", "Only a FILED protest may be docketed")

    window_opens = protest["filed_on"] + calc._timedelta(HEARING_WINDOW_OPENS_DAYS)
    window_closes = protest["filed_on"] + calc._timedelta(HEARING_WINDOW_CLOSES_DAYS)
    start_date = hearing_start_at.date()
    if start_date < window_opens or start_date > window_closes:
        raise ApiError("ERR_HEARING_OUTSIDE_WINDOW", "The hearing falls outside the statutory window")
    if not (hearing_end_at > hearing_start_at):
        raise ApiError("ERR_HEARING_OUTSIDE_WINDOW", "hearing_end_at must be strictly later than hearing_start_at")

    buffer_delta = timedelta(minutes=room["buffer_minutes"])
    same_day = 0
    for other in db.where("protest", hearing_room_id=room["id"]):
        if other["id"] == protest["id"] or not derive.holds_slot(other):
            continue
        if hearing_start_at < other["hearing_end_at"] + buffer_delta and (
            other["hearing_start_at"] < hearing_end_at + buffer_delta
        ):
            raise ApiError("ERR_HEARING_ROOM_CONFLICT", "The requested interval collides with a booked hearing")
        if other["hearing_start_at"].date() == start_date:
            same_day += 1
    if same_day >= room["max_hearings_per_day"]:
        raise ApiError("ERR_ROOM_DAY_CAPACITY_EXCEEDED", "The room has no capacity left on that date")

    protest["hearing_room_id"] = room["id"]
    protest["hearing_start_at"] = hearing_start_at
    protest["hearing_end_at"] = hearing_end_at
    protest["hearing_session_count"] = hearing_session_count
    protest["evidence_deadline_at"] = hearing_start_at - timedelta(days=EVIDENCE_DEADLINE_DAYS_BEFORE)
    protest["status"] = "SCHEDULED"
    db.touch(protest)

    derive.set_counter(room, "booked_hearing_count", derive.booked_hearing_count(room["id"]))
    db.touch(room)

    derive.recompute_all()
    return response.object_response(serializers.protest(protest), 200)


def _require_protest_party(caller, protest):
    """Stage-3 ownership on a nested tender (PRD 2.1)."""
    if caller.role == "Dealer":
        require_dealer_owner(caller, protest["protestant_dealer_id"])
        return "PROTESTANT"
    filing = _filing_of(protest)
    require_manufacturer_owner(caller, None if filing is None else filing["manufacturer_id"])
    return "MANUFACTURER"


@bp.post("/protests/<record_id>/market-studies")
def tender_market_study(record_id):
    caller = guard(["Dealer", "Manufacturer"])
    protest = _find(record_id)
    actual_party = _require_protest_party(caller, protest)

    body = v.read_body()
    submitted_by_party = v.req_enum(body, "submitted_by_party", enums.PARTIES)
    basis = v.req_enum(body, "basis", enums.STUDY_BASES)
    total_market_registrations = v.req_int(body, "total_market_registrations", 0)
    line_make_registrations = v.req_int(body, "line_make_registrations", 0)
    permanency_investment_cents = v.req_int(body, "permanency_investment_cents", 0)
    consumer_access_drive_minutes = v.req_int(body, "consumer_access_drive_minutes", 0, 600)
    market_growth_pct = v.req_decimal(body, "market_growth_pct", -50, 100, 2)
    statewide_share = v.opt_decimal(body, "statewide_line_make_share_pct", 0, 100, 2)
    comparable_shares = v.opt_list(body, "comparable_market_shares_pct", 0, 200)

    if line_make_registrations > total_market_registrations:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "line_make_registrations may not exceed total_market_registrations",
        )
    if comparable_shares is not None:
        parsed = []
        for index, raw in enumerate(comparable_shares):
            parsed.append(
                v._decimal_value(raw, "comparable_market_shares_pct[%d]" % index, 0, 100, 2, None)
            )
        comparable_shares = parsed
    if basis == "STATEWIDE_AVERAGE" and statewide_share is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "statewide_line_make_share_pct is required on a STATEWIDE_AVERAGE study",
        )
    if basis == "COMPARABLE_MARKET" and not comparable_shares:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "comparable_market_shares_pct must be present and non-empty on a COMPARABLE_MARKET study",
        )

    if protest["status"] not in TENDER_STATES:
        raise ApiError("ERR_INVALID_PROTEST_STATE", "The protest no longer admits tenders")
    if submitted_by_party != actual_party:
        raise ApiError("ERR_STUDY_PARTY_MISMATCH", "The declared party is not the caller's side of the protest")

    actual_pct, is_probative = calc.actual_penetration(total_market_registrations, line_make_registrations)
    expected_pct = calc.expected_penetration(basis, statewide_share, comparable_shares)
    record = db.insert("market_study", {
        "protest_id": protest["id"],
        "submitted_by_party": submitted_by_party,
        "basis": basis,
        "total_market_registrations": total_market_registrations,
        "line_make_registrations": line_make_registrations,
        "statewide_line_make_share_pct": statewide_share,
        "comparable_market_shares_pct": comparable_shares,
        "permanency_investment_cents": permanency_investment_cents,
        "consumer_access_drive_minutes": consumer_access_drive_minutes,
        "market_growth_pct": market_growth_pct,
        "actual_penetration_pct": actual_pct,
        "expected_penetration_pct": expected_pct,
        "shortfall_pts": calc.shortfall_points(expected_pct, actual_pct),
        "is_probative": is_probative,
    }, versioned=False)
    derive.recompute_all()
    return response.object_response(serializers.market_study(record), 201)


@bp.get("/protests/<record_id>/market-studies")
def list_market_studies(record_id):
    guard(LOG_READ_ROLES)
    protest = _find(record_id)
    submitted_by_party = v.query_enum("submitted_by_party", enums.PARTIES)
    limit, offset = response.read_pagination(request.args)
    rows = [
        row for row in db.ordered("market_study")
        if row["protest_id"] == protest["id"]
        and (submitted_by_party is None or row["submitted_by_party"] == submitted_by_party)
    ]
    window, total = response.page(rows, limit, offset)
    return response.array_response(
        [serializers.market_study(row) for row in window], limit, offset, len(rows)
    )


@bp.post("/protests/<record_id>/evidence-submissions")
def tender_evidence(record_id):
    caller = guard(["Dealer", "Manufacturer"])
    protest = _find(record_id)
    actual_party = _require_protest_party(caller, protest)

    body = v.read_body()
    submitting_party = v.req_enum(body, "submitting_party", enums.PARTIES)
    exhibit_label = v.req_string(body, "exhibit_label", 1, 20)
    page_count = v.req_int(body, "page_count", 1, 5000)
    leave_granted = v.opt_bool(body, "leave_granted", default=False)

    if protest["status"] not in TENDER_STATES:
        raise ApiError("ERR_INVALID_PROTEST_STATE", "The protest no longer admits tenders")

    if actual_party == "PROTESTANT":
        protestant = db.get("dealer", protest["protestant_dealer_id"])
        if protestant is None or protestant["license_status"] != "LICENSED":
            raise ApiError("ERR_DEALER_LICENSE_NOT_ACTIVE", "A protestant tendering evidence must be LICENSED")
    if submitting_party != actual_party:
        raise ApiError("ERR_STUDY_PARTY_MISMATCH", "The declared party is not the caller's side of the protest")

    received_at = db.now()
    deadline = protest.get("evidence_deadline_at")
    hearing_start_at = protest.get("hearing_start_at")
    if deadline is None or received_at <= deadline:
        acceptance_status = "ACCEPTED"
        is_late = False
    elif leave_granted and hearing_start_at is not None and received_at < hearing_start_at:
        acceptance_status = "LATE_ACCEPTED"
        is_late = True
    else:
        raise ApiError("ERR_EVIDENCE_DEADLINE_PASSED", "The evidence cut-off has passed")

    for other in db.where("evidence_submission", protest_id=protest["id"]):
        if other["submitting_party"] == submitting_party and other["exhibit_label"] == exhibit_label:
            raise ApiError("ERR_DUPLICATE_EXHIBIT_LABEL", "That exhibit label is already marked by this party")

    record = db.insert("evidence_submission", {
        "protest_id": protest["id"],
        "submitting_party": submitting_party,
        "exhibit_label": exhibit_label,
        "page_count": page_count,
        "leave_granted": leave_granted,
        "received_at": received_at,
        "acceptance_status": acceptance_status,
        "is_late": is_late,
    }, versioned=False)
    derive.recompute_all()
    return response.object_response(serializers.evidence_submission(record), 201)


@bp.get("/protests/<record_id>/evidence-submissions")
def list_evidence(record_id):
    guard(LOG_READ_ROLES)
    protest = _find(record_id)
    submitting_party = v.query_enum("submitting_party", enums.PARTIES)
    limit, offset = response.read_pagination(request.args)
    rows = [
        row for row in db.ordered("evidence_submission")
        if row["protest_id"] == protest["id"]
        and (submitting_party is None or row["submitting_party"] == submitting_party)
    ]
    window, total = response.page(rows, limit, offset)
    return response.array_response(
        [serializers.evidence_submission(row) for row in window], limit, offset, len(rows)
    )


def _controlling_pair(protest):
    protestant = calc.controlling_study(derive.studies_for_protest(protest["id"], "PROTESTANT"))
    manufacturer = calc.controlling_study(derive.studies_for_protest(protest["id"], "MANUFACTURER"))
    return protestant, manufacturer


@bp.post("/protests/<record_id>/convene")
def convene_protest(record_id):
    guard(["HearingClerk"])
    protest = _find(record_id)
    v.read_body()

    if protest["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_PROTEST_STATE", "Only a SCHEDULED protest may be convened")
    if db.now() < protest["hearing_start_at"]:
        raise ApiError("ERR_HEARING_NOT_REACHED", "The hearing instant has not arrived")

    protestant = db.get("dealer", protest["protestant_dealer_id"])
    lost_standing = protestant is None or protestant["license_status"] in LOST_STANDING_STATES

    if not lost_standing:
        controlling_protestant, controlling_manufacturer = _controlling_pair(protest)
        if controlling_protestant is None:
            raise ApiError("ERR_NO_PROBATIVE_STUDY", "No probative protestant market study is on file")
        components = calc.good_cause_components(controlling_protestant, controlling_manufacturer)
        filing = _filing_of(protest)
        protest["good_cause_score"] = components["good_cause_score"]
        protest["good_cause_threshold"] = calc.good_cause_threshold(
            None if filing is None else filing["filing_type"]
        )
        protest["status"] = "HEARD"
        db.touch(protest)
    else:
        protest["status"] = "DISMISSED"
        db.touch(protest)
        cascade.release_docket(protest)
        filing = _filing_of(protest)
        cascade.resolve_filing_when_quiet(filing)
        _refresh_filing_protest_count(filing)

    derive.recompute_all()
    return response.object_response(serializers.protest(protest), 200)


@bp.post("/protests/<record_id>/decision")
def decide_protest(record_id):
    guard(["BoardAdmin"])
    body = v.read_body()
    outcome = v.req_enum(body, "outcome", enums.PROTEST_OUTCOMES)
    findings_note = v.opt_string(body, "findings_note", 1, 2000)

    protest = _find(record_id)
    if protest["status"] != "HEARD":
        raise ApiError("ERR_INVALID_PROTEST_STATE", "Only a HEARD protest may be decided")

    score = protest.get("good_cause_score")
    threshold = protest.get("good_cause_threshold")
    if outcome == "SUSTAINED":
        if score is None or threshold is None or score < threshold:
            raise ApiError("ERR_GOOD_CAUSE_NOT_ESTABLISHED", "The good-cause standard is not met")

    total = calc.hearing_cost_assessment(
        protest["hearing_session_count"], protest["accepted_evidence_pages"], protest["late_evidence_count"]
    )
    prevailing = "PROTESTANT" if outcome == "SUSTAINED" else "MANUFACTURER"
    protestant_share, manufacturer_share = calc.assessment_split(total, prevailing)

    protest["decided_on"] = db.today()
    if findings_note is not None:
        protest["findings_note"] = findings_note
    protest["assessment_total_cents"] = total
    protest["protestant_share_cents"] = protestant_share
    protest["manufacturer_share_cents"] = manufacturer_share
    protest["status"] = outcome
    db.touch(protest)

    filing = _filing_of(protest)
    if outcome == "SUSTAINED":
        others_live = False
        if filing is not None:
            for other in derive.protests_for_filing(filing["id"]):
                if other["id"] == protest["id"]:
                    continue
                if other["status"] not in ("WITHDRAWN", "DISMISSED"):
                    others_live = True
        if filing is not None and not others_live and filing["status"] == "PROTEST_PENDING":
            filing["status"] = "BARRED"
            db.touch(filing)
            if filing["filing_type"] == "TERMINATION":
                dealer = db.get("dealer", filing.get("affected_dealer_id"))
                if dealer is not None and dealer["franchise_status"] == "TERMINATION_PENDING":
                    dealer["franchise_status"] = "FRANCHISED"
                    db.touch(dealer)
    else:
        cascade.resolve_filing_when_quiet(filing)
    _refresh_filing_protest_count(filing)

    derive.recompute_all()
    return response.object_response(serializers.protest(protest), 200)


@bp.post("/protests/<record_id>/appeal")
def appeal_protest(record_id):
    caller = guard(["Dealer", "Manufacturer"])
    protest = _find(record_id)
    appellant_party = _require_protest_party(caller, protest)

    body = v.read_body()
    court_docket_number = v.req_string(body, "court_docket_number", 1, 100)

    if protest["status"] not in ("SUSTAINED", "DENIED"):
        raise ApiError("ERR_INVALID_PROTEST_STATE", "Only a decided protest may be appealed")
    reference_date = db.today()
    if reference_date > protest["decided_on"] + calc._timedelta(APPEAL_WINDOW_DAYS):
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED", "The 30-day appeal window has closed")

    protest["status"] = "APPEALED"
    protest["appeal_filed_on"] = reference_date
    protest["appellant_party"] = appellant_party
    protest["court_docket_number"] = court_docket_number
    db.touch(protest)
    _refresh_filing_protest_count(_filing_of(protest))

    derive.recompute_all()
    return response.object_response(serializers.protest(protest), 200)


@bp.get("/protests/<record_id>/good-cause-analysis")
def good_cause_analysis(record_id):
    guard(ANALYSIS_READ_ROLES)
    protest = _find(record_id)
    filing = _filing_of(protest)
    threshold = calc.good_cause_threshold(None if filing is None else filing["filing_type"])
    controlling_protestant, controlling_manufacturer = _controlling_pair(protest)

    if controlling_protestant is None:
        data = {
            "controlling_protestant_study_id": None,
            "controlling_manufacturer_study_id": (
                None if controlling_manufacturer is None else controlling_manufacturer["id"]
            ),
            "net_shortfall_pts": None,
            "inadequacy_component": None,
            "investment_component": None,
            "access_component": None,
            "growth_component": None,
            "good_cause_score": None,
            "good_cause_threshold": calc.as_number(threshold),
            "good_cause_established": False,
        }
        return response.object_response(data, 200)

    components = calc.good_cause_components(controlling_protestant, controlling_manufacturer)
    data = {
        "controlling_protestant_study_id": controlling_protestant["id"],
        "controlling_manufacturer_study_id": (
            None if controlling_manufacturer is None else controlling_manufacturer["id"]
        ),
        "net_shortfall_pts": calc.as_number(components["net_shortfall_pts"]),
        "inadequacy_component": calc.as_number(components["inadequacy_component"]),
        "investment_component": calc.as_number(components["investment_component"]),
        "access_component": calc.as_number(components["access_component"]),
        "growth_component": calc.as_number(components["growth_component"]),
        "good_cause_score": calc.as_number(components["good_cause_score"]),
        "good_cause_threshold": calc.as_number(threshold),
        "good_cause_established": components["good_cause_score"] >= threshold,
    }
    return response.object_response(data, 200)


@bp.get("/protests/<record_id>")
def read_protest(record_id):
    guard(READ_ROLES)
    return response.object_response(serializers.protest(_find(record_id)), 200)


@bp.get("/protests")
def list_protests():
    guard(READ_ROLES)
    franchise_filing_id = v.query_string("franchise_filing_id")
    protestant_dealer_id = v.query_string("protestant_dealer_id")
    hearing_room_id = v.query_string("hearing_room_id")
    status = v.query_enum("status", enums.PROTEST_STATUSES)
    limit, offset = response.read_pagination(request.args)
    rows = [
        row for row in db.ordered("protest")
        if (franchise_filing_id is None or row["franchise_filing_id"] == franchise_filing_id)
        and (protestant_dealer_id is None or row["protestant_dealer_id"] == protestant_dealer_id)
        and (hearing_room_id is None or row["hearing_room_id"] == hearing_room_id)
        and (status is None or row["status"] == status)
    ]
    window, total = response.page(rows, limit, offset)
    return response.array_response(
        [serializers.protest(row) for row in window], limit, offset, len(rows)
    )
