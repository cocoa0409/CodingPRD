"""Member stations, projections, standings and the fee schedules/assessments."""
import re

from flask import Blueprint, request

from core import base, config as C
from core.base import new_record, public, touch
from core.errors import ApiError, bad_request, invalid_state, not_found
from core.middleware import (
    check_station_ownership, route, station_for,
)
from core.response import array_response, object_response
from core.store import STORE
from services import fees, governance, scoring

bp = Blueprint("stations", __name__)

REGIONS = ["REGION_NORTHEAST", "REGION_SOUTH", "REGION_MIDWEST", "REGION_WEST"]
ELIGIBILITY_STATES = [
    "APPLICANT", "UNDER_REVIEW", "DEFICIENT", "REMEDIATION_SUBMITTED",
    "ELIGIBLE", "PROBATION", "SUSPENDED", "WITHDRAWN",
]
CALL_SIGN_RE = r"^[A-Z]{3,4}$"
SCHEDULE_CODE_RE = r"^FY[0-9]{4}[A-Z]$"


def station_or_404(station_id):
    station = STORE.member_stations.get(station_id)
    if station is None:
        raise not_found("member station")
    return station


def station_view(store, station):
    """A station as read back: its projection-derived fields are mirrored."""
    data = public(station)
    data["dues_vote_eligible"] = bool(governance.projection_eligible(station))
    return data


def _register_station(body):
    call_sign = base.as_text(body.get("call_sign"), "call_sign", pattern=CALL_SIGN_RE)
    for existing in STORE.member_stations.values():
        if existing.get("call_sign") == call_sign:
            raise ApiError("ERR_CALL_SIGN_TAKEN")
    licensee = base.as_text(body.get("licensee_name"), "licensee_name")
    state_code = base.as_text(body.get("state_code"), "state_code")
    if len(state_code) != 2 or state_code != state_code.upper() or not state_code.isalpha():
        raise bad_request("state_code must be exactly two uppercase letters")
    rank = base.as_int(body.get("dma_market_rank"), "dma_market_rank", low=1, high=210)
    households = base.as_cents(body.get("dma_households"), "dma_households")
    coverage = base.as_cents(body.get("coverage_population"), "coverage_population")
    full_time = base.as_cents(body.get("full_time_staff_count"), "full_time_staff_count")
    newsroom = base.as_cents(body.get("newsroom_staff_count"), "newsroom_staff_count")
    revenue = base.as_cents(
        body.get("annual_local_revenue_cents"), "annual_local_revenue_cents"
    )
    region = base.as_enum(body.get("board_seat_region"), REGIONS, "board_seat_region")

    station = new_record(
        "MemberStation",
        call_sign=call_sign,
        licensee_name=licensee,
        state_code=state_code,
        dma_market_rank=rank,
        dma_households=households,
        coverage_population=coverage,
        full_time_staff_count=full_time,
        newsroom_staff_count=newsroom,
        annual_local_revenue_cents=revenue,
        board_seat_region=region,
        operations_score=0.0,
        membership_class="CLASS_D",
        eligibility_status="APPLICANT",
        dues_arrears_cents=0,
        contribution_credit_cents=0,
        applied_relief_cents=0,
        dues_vote_eligible=False,
        eligible_from=None,
        last_review_at=None,
    )
    STORE.put("member_stations", station)
    scoring.recompute_station_derived(station)
    governance.upsert_projection(STORE, station)
    return station


def _patch_station(station, body):
    if "call_sign" in body and body.get("call_sign") is not None:
        call_sign = base.as_text(body.get("call_sign"), "call_sign", pattern=CALL_SIGN_RE)
        for other in STORE.member_stations.values():
            if other["id"] != station["id"] and other.get("call_sign") == call_sign:
                raise ApiError("ERR_CALL_SIGN_TAKEN")
        station["call_sign"] = call_sign
    for field, low in (
        ("dma_households", 0),
        ("coverage_population", 0),
        ("full_time_staff_count", 0),
        ("newsroom_staff_count", 0),
        ("annual_local_revenue_cents", 0),
        ("dma_market_rank", 1),
    ):
        if field in body and body.get(field) is not None:
            high = 210 if field == "dma_market_rank" else None
            station[field] = base.as_int(body.get(field), field, low=low, high=high)
    if "board_seat_region" in body and body.get("board_seat_region") is not None:
        station["board_seat_region"] = base.as_enum(
            body.get("board_seat_region"), REGIONS, "board_seat_region"
        )
    scoring.recompute_station_derived(station)
    touch(station)
    return station


@bp.route("/network/member-stations", methods=["POST"])
@route("/network/member-stations", "POST")
def create_member_station():
    body = base.get_body(request.get_json(silent=True))
    station = _register_station(body)
    return object_response(station_view(STORE, station), 201)


@bp.route("/network/member-stations", methods=["GET"])
@route("/network/member-stations", "GET")
def list_member_stations():
    args = request.args
    recs = STORE.all("member_stations")
    filters = {
        "eligibility_status": base.scalar_arg(args, "eligibility_status"),
        "membership_class": base.scalar_arg(args, "membership_class"),
        "board_seat_region": base.scalar_arg(args, "board_seat_region"),
        "call_sign": base.scalar_arg(args, "call_sign"),
    }
    for key, want in filters.items():
        if want is not None:
            recs = [r for r in recs if r.get(key) == want]
    page, meta = base.paginate(recs, args)
    return array_response([station_view(STORE, r) for r in page], meta)


@bp.route("/network/member-stations/<sid>", methods=["GET"])
@route("/network/member-stations/<sid>", "GET")
def read_member_station(sid):
    station = station_or_404(sid)
    return object_response(station_view(STORE, station))


@bp.route("/network/member-stations/<sid>", methods=["PATCH"])
@route("/network/member-stations/<sid>", "PATCH")
def patch_member_station(sid):
    station = station_or_404(sid)
    body = base.get_body(request.get_json(silent=True))
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, station["id"])
    _patch_station(station, body)
    return object_response(station_view(STORE, station))


@bp.route("/network/member-stations/<sid>/submit-eligibility", methods=["POST"])
@route("/network/member-stations/<sid>/submit-eligibility", "POST")
def submit_eligibility(sid):
    station = station_or_404(sid)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, station["id"])
    status = station.get("eligibility_status")
    if status == "WITHDRAWN":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status == "APPLICANT":
        if C.parse_dt(station.get("created_at")) is None:
            pass
        if not station.get("call_sign"):
            raise invalid_state("the station has no call sign")
        if station.get("dma_market_rank") is None:
            raise invalid_state("the station has no DMA market rank")
        if int(station.get("annual_local_revenue_cents") or 0) < 0:
            raise invalid_state("the station carries a negative revenue")
        station["eligibility_status"] = "UNDER_REVIEW"
    elif status == "REMEDIATION_SUBMITTED":
        station["eligibility_status"] = "UNDER_REVIEW"
    else:
        raise invalid_state("the station is not in a state that admits a submission")
    scoring.recompute_station_derived(station)
    governance.upsert_projection(STORE, station)
    touch(station)
    return object_response(station_view(STORE, station))


@bp.route("/network/member-stations/<sid>/record-deficiency", methods=["POST"])
@route("/network/member-stations/<sid>/record-deficiency", "POST")
def record_deficiency(sid):
    station = station_or_404(sid)
    if station.get("eligibility_status") == "WITHDRAWN":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if station.get("eligibility_status") != "UNDER_REVIEW":
        raise invalid_state("the station is not under review")
    body = base.get_body(request.get_json(silent=True))
    factors = body.get("deficiency_factors")
    if factors is None:
        factors = []
    if not isinstance(factors, list):
        raise bad_request("deficiency_factors must be a list")
    newsroom = int(station.get("newsroom_staff_count") or 0)
    full_time = int(station.get("full_time_staff_count") or 0)
    coverage = int(station.get("coverage_population") or 0)
    if not (newsroom < 2 or full_time < 3 or coverage < 50000):
        raise invalid_state("the station satisfies every deficiency threshold")
    station["eligibility_status"] = "DEFICIENT"
    station["_deficiency_factors"] = factors
    touch(station)
    data = station_view(STORE, station)
    data["deficiency_factors"] = factors
    return object_response(data)


@bp.route("/network/member-stations/<sid>/remediation", methods=["POST"])
@route("/network/member-stations/<sid>/remediation", "POST")
def submit_remediation(sid):
    station = station_or_404(sid)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, station["id"])
    if station.get("eligibility_status") == "WITHDRAWN":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if station.get("eligibility_status") != "DEFICIENT":
        raise invalid_state("the station is not deficient")
    body = base.get_body(request.get_json(silent=True))
    factors = body.get("remediated_factors")
    if not isinstance(factors, list) or len(factors) == 0:
        raise bad_request("remediated_factors must be a non-empty list")
    station["eligibility_status"] = "REMEDIATION_SUBMITTED"
    station["_remediated_factors"] = factors
    touch(station)
    data = station_view(STORE, station)
    data["remediated_factors"] = factors
    return object_response(data)


@bp.route("/network/member-stations/<sid>/approve-eligibility", methods=["POST"])
@route("/network/member-stations/<sid>/approve-eligibility", "POST")
def approve_eligibility(sid):
    station = station_or_404(sid)
    status = station.get("eligibility_status")
    if status == "WITHDRAWN":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("UNDER_REVIEW", "REMEDIATION_SUBMITTED"):
        raise invalid_state("the station is not in review")
    if status == "UNDER_REVIEW":
        if int(station.get("coverage_population") or 0) < 50000:
            raise invalid_state("coverage_population is below 50000")
        if int(station.get("full_time_staff_count") or 0) < 3:
            raise invalid_state("full_time_staff_count is below 3")
        if int(station.get("newsroom_staff_count") or 0) < 2:
            raise invalid_state("newsroom_staff_count is below 2")
    station["eligibility_status"] = "ELIGIBLE"
    station["eligible_from"] = C.iso(C.now())
    station["last_review_at"] = C.iso(C.now())
    scoring.recompute_station_derived(station)
    schedule = fees.resolve_schedule(STORE, station)
    if schedule is not None:
        fees.new_assessment(STORE, station, schedule, C.now().year, "INITIAL")
    governance.upsert_projection(STORE, station)
    touch(station)
    return object_response(station_view(STORE, station))


@bp.route("/network/member-stations/<sid>/probation", methods=["POST"])
@route("/network/member-stations/<sid>/probation", "POST")
def place_on_probation(sid):
    station = station_or_404(sid)
    if station.get("eligibility_status") == "WITHDRAWN":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if station.get("eligibility_status") != "ELIGIBLE":
        raise invalid_state("the station is not eligible")
    body = base.get_body(request.get_json(silent=True))
    base.as_text(body.get("reason_code"), "reason_code")
    station["eligibility_status"] = "PROBATION"
    for window in STORE.windows.values():
        if window.get("station_id") != station["id"]:
            continue
        if window.get("clearance_status") in ("BROADCAST", "MISSED", "VIOLATED"):
            continue
        window["clearance_status"] = "VIOLATED"
        window["rejection_reason"] = "PROBATION"
        from services import carriage
        carriage.accrue(window, "VIOLATED")
        carriage.refresh_window_flags(STORE, window)
        touch(window)
        carriage.refresh_agreement_from_windows(STORE, window.get("parent_agreement_id"))
    governance.upsert_projection(STORE, station)
    touch(station)
    return object_response(station_view(STORE, station))


@bp.route("/network/member-stations/<sid>/restore-eligibility", methods=["POST"])
@route("/network/member-stations/<sid>/restore-eligibility", "POST")
def restore_eligibility(sid):
    station = station_or_404(sid)
    if station.get("eligibility_status") != "PROBATION":
        raise invalid_state("the station is not on probation")
    score = C.round2(C.d(station.get("operations_score") or 0))
    if score < C.d("55.00"):
        raise invalid_state("the station's operations score has not recovered")
    station["eligibility_status"] = "ELIGIBLE"
    governance.upsert_projection(STORE, station)
    touch(station)
    return object_response(station_view(STORE, station))


@bp.route("/network/member-stations/<sid>/suspend", methods=["POST"])
@route("/network/member-stations/<sid>/suspend", "POST")
def suspend_station(sid):
    station = station_or_404(sid)
    status = station.get("eligibility_status")
    if status == "WITHDRAWN":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("ELIGIBLE", "PROBATION"):
        raise invalid_state("the station cannot be suspended from its current state")
    body = base.get_body(request.get_json(silent=True))
    reason = base.as_text(body.get("suspension_reason"), "suspension_reason")
    if status == "PROBATION":
        if int(station.get("dues_arrears_cents") or 0) <= 0:
            raise invalid_state("the station carries no dues arrears")
    station["eligibility_status"] = "SUSPENDED"
    station["_suspension_reason"] = reason
    governance.upsert_projection(STORE, station)
    governance.recompute_quorum_denominators(STORE)
    touch(station)
    return object_response(station_view(STORE, station))


@bp.route("/network/member-stations/<sid>/reinstate", methods=["POST"])
@route("/network/member-stations/<sid>/reinstate", "POST")
def reinstate_station(sid):
    station = station_or_404(sid)
    if station.get("eligibility_status") == "WITHDRAWN":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if station.get("eligibility_status") != "SUSPENDED":
        raise invalid_state("the station is not suspended")
    if int(station.get("dues_arrears_cents") or 0) != 0:
        raise invalid_state("the station still carries dues arrears")
    station["eligibility_status"] = "UNDER_REVIEW"
    governance.upsert_projection(STORE, station)
    touch(station)
    return object_response(station_view(STORE, station))


@bp.route("/network/member-stations/<sid>/withdraw", methods=["POST"])
@route("/network/member-stations/<sid>/withdraw", "POST")
def withdraw_station(sid):
    station = station_or_404(sid)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, station["id"])
    status = station.get("eligibility_status")
    if status == "WITHDRAWN":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("APPLICANT", "DEFICIENT"):
        raise invalid_state("the station cannot be withdrawn from its current state")
    station["eligibility_status"] = "WITHDRAWN"
    station["eligible_from"] = None
    governance.upsert_projection(STORE, station)
    touch(station)
    return object_response(station_view(STORE, station))


@bp.route("/network/member-stations/<sid>/apply-contribution-credit", methods=["POST"])
@route("/network/member-stations/<sid>/apply-contribution-credit", "POST")
def apply_contribution_credit(sid):
    station = station_or_404(sid)
    role = request.headers.get("X-User-Role")
    ident = request.headers.get("X-User-ID")
    check_station_ownership(role, ident, station["id"])
    body = base.get_body(request.get_json(silent=True))
    credit = base.as_cents(body.get("credit_cents"), "credit_cents")
    balance = int(station.get("contribution_credit_cents") or 0)
    if credit > balance:
        raise invalid_state("the station's credit balance is smaller than the request")
    station["contribution_credit_cents"] = balance - credit
    station["applied_relief_cents"] = int(station.get("applied_relief_cents") or 0) + credit
    station["dues_arrears_cents"] = int(station.get("dues_arrears_cents") or 0) - credit
    touch(station)
    return object_response(station_view(STORE, station))


@bp.route("/network/member-stations/<sid>/cost-efficiency-match", methods=["POST"])
@route("/network/member-stations/<sid>/cost-efficiency-match", "POST")
def cost_efficiency_match(sid):
    requester = station_or_404(sid)
    body = base.get_body(request.get_json(silent=True))
    base.as_cents(body.get("match_budget_cents"), "match_budget_cents")
    requesting_id = body.get("requesting_station_id")
    if requesting_id is None:
        requesting_id = requester["id"]
    station_or_404(requesting_id)
    candidate = governance.cost_efficiency_candidate(STORE, requesting_id)
    selected = STORE.member_stations.get(candidate["id"])
    budget = int(selected.get("matched_budget_cents") or 0)
    budget = max(0, budget - scoring.MATCH_BUDGET_PER_STATION_CENTS)
    selected["matched_budget_cents"] = budget
    touch(selected)
    data = station_view(STORE, selected)
    data["matched_budget_cents"] = budget
    return object_response(data)


@bp.route("/network/member-station-standings", methods=["GET"])
@route("/network/member-station-standings", "GET")
def member_station_standings():
    args = request.args
    rows = governance.standings_rows(STORE)
    items = []
    for station, rank in rows:
        data = station_view(STORE, station)
        data["standings_rank"] = rank
        items.append(data)
    limit = base.as_int(args.get("limit"), "limit", low=1, high=100, required=False)
    if limit is None:
        limit = 10
    offset = base.as_int(args.get("offset"), "offset", low=0, required=False)
    if offset is None:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return array_response(page, meta)


@bp.route("/network/member-stations/<sid>/assessments", methods=["GET"])
@route("/network/member-stations/<sid>/assessments", "GET")
def station_assessments(sid):
    station_or_404(sid)
    args = request.args
    recs = [a for a in STORE.assessments.values() if a.get("station_id") == sid]
    status = base.scalar_arg(args, "assessment_status")
    if status is not None:
        recs = [a for a in recs if a.get("assessment_status") == status]
    page, meta = base.paginate(recs, args)
    return array_response([public(a) for a in page], meta)


# --- fee schedules -----------------------------------------------------------
@bp.route("/network/programming-fee-schedules", methods=["POST"])
@route("/network/programming-fee-schedules", "POST")
def create_schedule():
    body = base.get_body(request.get_json(silent=True))
    code = base.as_text(body.get("schedule_code"), "schedule_code", pattern=SCHEDULE_CODE_RE)
    fiscal_year = base.as_int(body.get("fiscal_year"), "fiscal_year", low=2024, high=2100)
    base_fee = base.as_cents(body.get("base_fee_cents"), "base_fee_cents")
    rate = base.as_int(body.get("revenue_rate_bps"), "revenue_rate_bps", low=0)
    t1 = base.as_int(body.get("market_tier_1_max_rank"), "market_tier_1_max_rank", low=1, required=False)
    t2 = base.as_int(body.get("market_tier_2_max_rank"), "market_tier_2_max_rank", low=1, required=False)
    t3 = base.as_int(body.get("market_tier_3_max_rank"), "market_tier_3_max_rank", low=1, required=False)
    t1 = 25 if t1 is None else t1
    t2 = 75 if t2 is None else t2
    t3 = 150 if t3 is None else t3
    if not (t2 > t1 and t3 > t2):
        raise bad_request("the market tier ladder must increase monotonically")
    multiplier = base.as_int(
        body.get("market_size_multiplier_bps"), "market_size_multiplier_bps", low=10000
    )
    minimum = base.as_cents(body.get("minimum_fee_cents"), "minimum_fee_cents")
    maximum = base.as_cents(body.get("maximum_fee_cents"), "maximum_fee_cents")
    if maximum <= minimum:
        raise bad_request("maximum_fee_cents must exceed minimum_fee_cents")
    adjustment = base.as_int(
        body.get("annual_adjustment_bps"), "annual_adjustment_bps", low=-2000, required=False
    )
    adjustment = 0 if adjustment is None else adjustment
    rounding = base.as_enum(
        body.get("rounding_mode"), ["ROUND_PER_COMPONENT_THEN_SUM"],
        "rounding_mode", required=False,
    )
    rounding = rounding or "ROUND_PER_COMPONENT_THEN_SUM"
    effective_from = base.as_instant(body.get("effective_from"), "effective_from")
    effective_to = base.as_instant(body.get("effective_to"), "effective_to")
    if C.parse_dt(effective_to) <= C.parse_dt(effective_from):
        raise bad_request("effective_to must be after effective_from")
    schedule = new_record(
        "ProgrammingFeeSchedule",
        common=False,
        schedule_code=code,
        fiscal_year=fiscal_year,
        base_fee_cents=base_fee,
        revenue_rate_bps=rate,
        market_tier_1_max_rank=t1,
        market_tier_2_max_rank=t2,
        market_tier_3_max_rank=t3,
        market_size_multiplier_bps=multiplier,
        minimum_fee_cents=minimum,
        maximum_fee_cents=maximum,
        annual_adjustment_bps=adjustment,
        rounding_mode=rounding,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    STORE.put("schedules", schedule)
    return object_response(public(schedule), 201)


@bp.route("/network/programming-fee-schedules", methods=["GET"])
@route("/network/programming-fee-schedules", "GET")
def list_schedules():
    args = request.args
    recs = STORE.all("schedules")
    fiscal_year = base.scalar_arg(args, "fiscal_year", "int")
    if fiscal_year is not None:
        recs = [s for s in recs if s.get("fiscal_year") == fiscal_year]
    page, meta = base.paginate(recs, args)
    return array_response([public(s) for s in page], meta)


@bp.route("/network/programming-fee-schedules/<fid>", methods=["GET"])
@route("/network/programming-fee-schedules/<fid>", "GET")
def read_schedule(fid):
    schedule = STORE.schedules.get(fid)
    if schedule is None:
        raise not_found("programming fee schedule")
    return object_response(public(schedule))


def _preview_assessment(station, schedule, assessment_id=None):
    data = {
        "id": assessment_id or C.new_id(),
        "station_id": station["id"],
        "schedule_id": schedule["id"],
        "fiscal_year": schedule.get("fiscal_year"),
        "assessment_status": "INITIAL",
        "provisional_fee_cents": fees.provisional_fee_cents(station, schedule),
        "final_fee_cents": 0,
        "drive_deduction_cents": fees.station_drive_deduction(
            STORE, station, schedule.get("fiscal_year")
        ),
        "allocated_dues_cents": 0,
        "total_pot_cents": 0,
    }
    data["final_fee_cents"] = fees.final_adjusted_fee_cents(
        station, schedule, data["provisional_fee_cents"]
    )
    data["membership_class"] = station.get("membership_class")
    data["dma_market_rank"] = station.get("dma_market_rank")
    data["fee_tier"] = fees.fee_tier(station.get("dma_market_rank"), schedule)
    data["net_charge_cents"] = data["final_fee_cents"] - data["drive_deduction_cents"]
    return data


@bp.route("/network/programming-fee-schedules/<fid>/preview", methods=["GET"])
@route("/network/programming-fee-schedules/<fid>/preview", "GET")
def preview_schedule_fee(fid):
    schedule = STORE.schedules.get(fid)
    if schedule is None:
        raise not_found("programming fee schedule")
    args = request.args
    station_id = args.get("station_id") or base.get_body(request.get_json(silent=True)).get("station_id")
    station = station_or_404(station_id)
    return object_response(_preview_assessment(station, schedule))


# --- assessments -------------------------------------------------------------
@bp.route("/network/programming-fee-assessments", methods=["GET"])
@route("/network/programming-fee-assessments", "GET")
def list_assessments():
    args = request.args
    recs = STORE.all("assessments")
    for field, cast in (
        ("station_id", None), ("schedule_id", None),
        ("fiscal_year", "int"), ("assessment_status", None),
    ):
        want = base.scalar_arg(args, field, cast)
        if want is not None:
            recs = [r for r in recs if r.get(field) == want]
    page, meta = base.paginate(recs, args)
    return array_response([public(a) for a in page], meta)


@bp.route("/network/programming-fee-assessments/<aid>", methods=["GET"])
@route("/network/programming-fee-assessments/<aid>", "GET")
def read_assessment(aid):
    assessment = STORE.assessments.get(aid)
    if assessment is None:
        raise not_found("programming fee assessment")
    return object_response(public(assessment))


@bp.route("/network/programming-fee-assessments/<aid>/finalize", methods=["POST"])
@route("/network/programming-fee-assessments/<aid>/finalize", "POST")
def finalize_assessment(aid):
    assessment = STORE.assessments.get(aid)
    if assessment is None:
        raise not_found("programming fee assessment")
    station = station_or_404(assessment.get("station_id"))
    body = base.get_body(request.get_json(silent=True))
    expected = base.as_int(
        body.get("expected_station_version"), "expected_station_version", required=False
    )
    if expected is None:
        raise bad_request("expected_station_version is required")
    if expected != int(station.get("version") or 0):
        raise ApiError("ERR_STALE_STATION_VERSION")
    if assessment.get("assessment_status") == "SUPERSEDED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if assessment.get("assessment_status") != "INITIAL":
        raise invalid_state("the assessment is not in an initial state")
    fees.compute_assessment(STORE, assessment, station)
    net = int(assessment.get("final_fee_cents") or 0) - int(
        assessment.get("drive_deduction_cents") or 0
    )
    station["dues_arrears_cents"] = int(station.get("dues_arrears_cents") or 0) + net
    assessment["assessment_status"] = "FINALIZED"
    touch(station)
    touch(assessment)
    governance.upsert_projection(STORE, station)
    return object_response(public(assessment))


@bp.route("/network/programming-fee-assessments/<aid>/allocate-pool", methods=["POST"])
@route("/network/programming-fee-assessments/<aid>/allocate-pool", "POST")
def allocate_pool(aid):
    anchor = STORE.assessments.get(aid)
    if anchor is None:
        raise not_found("programming fee assessment")
    body = base.get_body(request.get_json(silent=True))
    pot = base.as_cents(body.get("total_pot_cents"), "total_pot_cents")
    fiscal_year = anchor.get("fiscal_year")
    batch = [
        a for a in STORE.assessments.values() if a.get("fiscal_year") == fiscal_year
    ]
    batch.sort(key=lambda a: a.get("created_at") or "")
    allocated = governance.allocate_pool(STORE, batch, pot, fiscal_year)
    return object_response([public(a) for a in allocated])