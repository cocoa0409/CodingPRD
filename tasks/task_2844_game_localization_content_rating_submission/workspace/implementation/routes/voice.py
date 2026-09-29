"""Booth, talent, contract and recording-session endpoints (PRD SS3.4, SS3.5)."""
from datetime import timedelta

from flask import Blueprint

from constants import (
    ALL_ROLES,
    LANGUAGE_CODES,
    MARKET_CODES,
    MEDIA_SCOPES,
    ROLE_LOCALIZATION_PRODUCER,
    ROLE_TALENT_AGENT,
    SESSION_ACTIVE_STATUSES,
)
from db import base_row, db, fetch, insert, rows, touch
from derive import (
    by_created,
    cancel_scheduled_sessions,
    cancel_session_cascade,
    contract_committed_fee,
    contract_sessions,
    expire_contract_if_lapsed,
    recompute_booth,
    recompute_contract_ledger,
    recompute_plan_cost,
    talent_reserved_minutes_on_date,
    voice_recorded_line_count,
)
from errors import ApiError
from middleware import endpoint, require_talent_ownership, user_id
from response import created, ok, paginated
from routehelp import arg, bool_arg, match_all
from serialize import (
    booth_out,
    nk_booth,
    nk_talent_contract,
    nk_voice_session,
    nk_voice_talent,
    talent_contract_out,
    voice_session_out,
    voice_talent_out,
)
from validation import (
    bad,
    json_body,
    opt_bool,
    opt_int,
    req_enum,
    req_enum_list,
    req_id,
    req_instant,
    req_int,
    req_str,
)

bp = Blueprint("voice", __name__)

PRODUCERS = [ROLE_LOCALIZATION_PRODUCER]
AGENT_OR_PRODUCER = [ROLE_TALENT_AGENT, ROLE_LOCALIZATION_PRODUCER]


# ------------------------------------------------------------------- booths
@bp.route("/booths", methods=["POST"])
@endpoint(PRODUCERS)
def create_booth():
    body = json_body()
    booth_code = req_str(body, "booth_code", 1, 24)
    studio_city = req_str(body, "studio_city", 1, 60)
    turnaround = opt_int(body, "turnaround_buffer_minutes", 0, 240, 30)

    row = base_row()
    row.update({
        "booth_code": booth_code,
        "studio_city": studio_city,
        "turnaround_buffer_minutes": turnaround,
        "reserved_minutes_total": 0,
    })
    insert("booths", row)
    return created(booth_out(row))


@bp.route("/booths/<recording_booth_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_booth(recording_booth_id):
    return ok(booth_out(fetch("booths", recording_booth_id)))


@bp.route("/booths", methods=["GET"])
@endpoint(ALL_ROLES)
def list_booths():
    pairs = [("studio_city", arg("studio_city"))]
    items = [b for b in rows("booths") if match_all(b, pairs)]
    return paginated(items, booth_out, nk_booth)


# ------------------------------------------------------------- voice talents
@bp.route("/voice-talents", methods=["POST"])
@endpoint(PRODUCERS)
def create_voice_talent():
    body = json_body()
    talent_name = req_str(body, "talent_name", 1, 80)
    language_code = req_enum(body, "language_code", LANGUAGE_CODES)
    union_flag = opt_bool(body, "union_flag", False)
    max_daily = opt_int(body, "max_daily_recording_minutes", 1, 720, 240)

    row = base_row()
    row.update({
        "talent_name": talent_name,
        "language_code": language_code,
        "union_flag": union_flag,
        "max_daily_recording_minutes": max_daily,
    })
    insert("voice_talents", row)
    return created(voice_talent_out(row))


@bp.route("/voice-talents/<voice_talent_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_voice_talent(voice_talent_id):
    return ok(voice_talent_out(fetch("voice_talents", voice_talent_id)))


@bp.route("/voice-talents", methods=["GET"])
@endpoint(ALL_ROLES)
def list_voice_talents():
    pairs = [
        ("language_code", arg("language_code")),
        ("union_flag", bool_arg("union_flag")),
    ]
    items = [v for v in rows("voice_talents") if match_all(v, pairs)]
    return paginated(items, voice_talent_out, nk_voice_talent)


# ---------------------------------------------------------- talent contracts
@bp.route("/talent-contracts", methods=["POST"])
@endpoint(PRODUCERS)
def create_talent_contract():
    body = json_body()
    voice_talent_id = req_id(body, "voice_talent_id")
    title_id = req_id(body, "title_id")
    territory_scope = req_enum_list(body, "territory_scope", MARKET_CODES, non_empty=True)
    media_scope = req_enum(body, "media_scope", MEDIA_SCOPES)
    buyout_fee_cents = req_int(body, "buyout_fee_cents", 0)
    per_line_rate_cents = req_int(body, "per_line_rate_cents", 0)
    rights_start_utc = req_instant(body, "rights_start_utc")
    rights_end_utc = req_instant(body, "rights_end_utc")
    if rights_start_utc >= rights_end_utc:
        bad("rights_start_utc must be strictly before rights_end_utc")
    expected_version = req_int(body, "expected_voice_talent_version", 0)

    # rung 5 -- body foreign keys in entity field-declaration order
    talent = fetch("voice_talents", voice_talent_id)
    fetch("titles", title_id)

    # rung 9 -- optimistic concurrency
    if expected_version != talent["version"]:
        raise ApiError("ERR_STALE_TALENT_VERSION")

    row = base_row()
    row.update({
        "voice_talent_id": voice_talent_id,
        "title_id": title_id,
        "territory_scope": list(territory_scope),
        "media_scope": media_scope,
        "buyout_fee_cents": buyout_fee_cents,
        "per_line_rate_cents": per_line_rate_cents,
        "rights_start_utc": rights_start_utc,
        "rights_end_utc": rights_end_utc,
        "status": "DRAFT",
        "signed_at_utc": None,
        "committed_fee_cents": 0,
    })

    # a new contract for the same (talent, title) pair supersedes the signed one
    for existing in by_created(rows("talent_contracts")):
        if (
            existing["voice_talent_id"] == voice_talent_id
            and existing["title_id"] == title_id
            and existing["status"] == "SIGNED"
        ):
            existing["status"] = "TERMINATED"
            touch(existing)

    insert("talent_contracts", row)
    touch(talent)
    return created(talent_contract_out(row))


@bp.route("/talent-contracts/<talent_contract_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_talent_contract(talent_contract_id):
    return ok(talent_contract_out(fetch("talent_contracts", talent_contract_id)))


@bp.route("/talent-contracts", methods=["GET"])
@endpoint(ALL_ROLES)
def list_talent_contracts():
    pairs = [
        ("voice_talent_id", arg("voice_talent_id")),
        ("title_id", arg("title_id")),
        ("status", arg("status")),
        ("media_scope", arg("media_scope")),
    ]
    items = [c for c in rows("talent_contracts") if match_all(c, pairs)]
    return paginated(items, talent_contract_out, nk_talent_contract)


@bp.route("/talent-contracts/<talent_contract_id>/sign", methods=["POST"])
@endpoint(AGENT_OR_PRODUCER)
def sign_talent_contract(talent_contract_id):
    contract = fetch("talent_contracts", talent_contract_id)
    require_talent_ownership(contract["voice_talent_id"])
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_NOT_DRAFT")
    if db.now() >= contract["rights_end_utc"]:
        raise ApiError(
            "ERR_CONTRACT_RIGHTS_WINDOW_EXCEEDED",
            "The logical clock has reached the end of the rights window",
        )

    contract["status"] = "SIGNED"
    contract["signed_at_utc"] = db.now()
    contract["committed_fee_cents"] = contract["buyout_fee_cents"]
    touch(contract)
    return ok(talent_contract_out(contract))


@bp.route("/talent-contracts/<talent_contract_id>/terminate", methods=["POST"])
@endpoint(PRODUCERS)
def terminate_talent_contract(talent_contract_id):
    contract = fetch("talent_contracts", talent_contract_id)
    if contract["status"] != "SIGNED":
        raise ApiError("ERR_CONTRACT_NOT_DRAFT")

    affected_plans = cancel_scheduled_sessions(contract_sessions(contract["id"]))
    contract["status"] = "TERMINATED"
    touch(contract)
    recompute_contract_ledger(contract)
    for plan in affected_plans:
        recompute_plan_cost(plan)
    return ok(talent_contract_out(contract))


# ------------------------------------------------------------ voice sessions
@bp.route("/voice-sessions", methods=["POST"])
@endpoint(PRODUCERS)
def create_voice_session():
    body = json_body()
    market_plan_id = req_id(body, "market_plan_id")
    voice_talent_id = req_id(body, "voice_talent_id")
    recording_booth_id = req_id(body, "recording_booth_id")
    talent_contract_id = req_id(body, "talent_contract_id")
    start_utc = req_instant(body, "start_utc")
    end_utc = req_instant(body, "end_utc")
    if end_utc <= start_utc:
        bad("end_utc must be strictly after start_utc")
    planned_line_count = req_int(body, "planned_line_count", 1)

    # rung 5 -- body foreign keys in entity field-declaration order
    plan = fetch("market_plans", market_plan_id)
    talent = fetch("voice_talents", voice_talent_id)
    booth = fetch("booths", recording_booth_id)
    contract = fetch("talent_contracts", talent_contract_id)

    # rung 6 -- cross-parent coherence
    if (
        contract["voice_talent_id"] != voice_talent_id
        or contract["title_id"] != plan["title_id"]
    ):
        raise ApiError("ERR_CROSS_PARENT_MISMATCH")

    # lazy expiry always precedes the referencing request's own preconditions
    expire_contract_if_lapsed(contract)

    # cross-entity state preconditions
    if contract["status"] != "SIGNED":
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET", "The talent contract must be SIGNED"
        )
    if plan["status"] != "IN_LOCALIZATION":
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "The market plan must be IN_LOCALIZATION",
        )

    # rights coverage
    if plan["market_code"] not in contract["territory_scope"]:
        raise ApiError("ERR_CONTRACT_TERRITORY_NOT_COVERED")
    if contract["media_scope"] == "IN_GAME_ONLY" and plan["scope_tier"] == "FULL_CULTURAL":
        raise ApiError("ERR_CONTRACT_TERRITORY_NOT_COVERED")

    # rights window
    if start_utc < contract["rights_start_utc"] or end_utc > contract["rights_end_utc"]:
        raise ApiError("ERR_CONTRACT_RIGHTS_WINDOW_EXCEEDED")

    # single UTC calendar date containment
    if start_utc.date() != end_utc.date():
        raise ApiError("ERR_SESSION_SPANS_TWO_DATES")

    duration_minutes = int((end_utc - start_utc).total_seconds() // 60)
    buffer_minutes = booth["turnaround_buffer_minutes"]
    occupied_end_utc = end_utc + timedelta(minutes=buffer_minutes)

    # booth geometry -- half-open [start_utc, occupied_end_utc) intersection
    for other in booth_sessions_live(recording_booth_id):
        if start_utc < other["occupied_end_utc"] and other["start_utc"] < occupied_end_utc:
            raise ApiError("ERR_BOOTH_WINDOW_CONFLICT")

    # aggregate talent capacity on the start date
    reserved = talent_reserved_minutes_on_date(voice_talent_id, start_utc.date())
    if reserved + duration_minutes > talent["max_daily_recording_minutes"]:
        raise ApiError("ERR_TALENT_DAILY_CAPACITY_EXCEEDED")

    row = base_row()
    row.update({
        "market_plan_id": market_plan_id,
        "voice_talent_id": voice_talent_id,
        "recording_booth_id": recording_booth_id,
        "talent_contract_id": talent_contract_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "duration_minutes": duration_minutes,
        "occupied_end_utc": occupied_end_utc,
        "planned_line_count": planned_line_count,
        "recorded_line_count": None,
        "status": "SCHEDULED",
        "line_fee_cents": 0,
    })
    insert("voice_sessions", row)
    recompute_booth(booth)
    return created(voice_session_out(row))


def booth_sessions_live(recording_booth_id):
    from derive import booth_sessions
    return [
        s for s in booth_sessions(recording_booth_id)
        if s["status"] in SESSION_ACTIVE_STATUSES
    ]


@bp.route("/voice-sessions/<voice_session_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_voice_session(voice_session_id):
    return ok(voice_session_out(fetch("voice_sessions", voice_session_id)))


@bp.route("/voice-sessions", methods=["GET"])
@endpoint(ALL_ROLES)
def list_voice_sessions():
    pairs = [
        ("market_plan_id", arg("market_plan_id")),
        ("voice_talent_id", arg("voice_talent_id")),
        ("recording_booth_id", arg("recording_booth_id")),
        ("talent_contract_id", arg("talent_contract_id")),
        ("status", arg("status")),
    ]
    items = [s for s in rows("voice_sessions") if match_all(s, pairs)]
    return paginated(items, voice_session_out, nk_voice_session)


@bp.route("/voice-sessions/<voice_session_id>/start", methods=["POST"])
@endpoint(AGENT_OR_PRODUCER)
def start_voice_session(voice_session_id):
    session = fetch("voice_sessions", voice_session_id)
    require_talent_ownership(session["voice_talent_id"])
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_STATE_INVALID")

    contract = fetch("talent_contracts", session["talent_contract_id"])
    expire_contract_if_lapsed(contract)
    if contract["status"] != "SIGNED":
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET", "The talent contract must be SIGNED"
        )
    now = db.now()
    if now < contract["rights_start_utc"] or now >= contract["rights_end_utc"]:
        raise ApiError("ERR_CONTRACT_RIGHTS_WINDOW_EXCEEDED")
    if now < session["start_utc"]:
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "The logical clock has not reached the session start",
        )
    plan = fetch("market_plans", session["market_plan_id"])
    if plan["status"] != "IN_LOCALIZATION":
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "The market plan must be IN_LOCALIZATION",
        )

    session["status"] = "IN_PROGRESS"
    touch(session)
    return ok(voice_session_out(session))


@bp.route("/voice-sessions/<voice_session_id>/complete", methods=["POST"])
@endpoint(AGENT_OR_PRODUCER)
def complete_voice_session(voice_session_id):
    body = json_body()
    recorded = req_int(body, "recorded_line_count", 0)
    session = fetch("voice_sessions", voice_session_id)
    if recorded > session["planned_line_count"]:
        bad("recorded_line_count may not exceed planned_line_count")
    require_talent_ownership(session["voice_talent_id"])
    if session["status"] != "IN_PROGRESS":
        raise ApiError("ERR_SESSION_STATE_INVALID")

    contract = fetch("talent_contracts", session["talent_contract_id"])
    plan = fetch("market_plans", session["market_plan_id"])

    session["recorded_line_count"] = recorded
    session["status"] = "RECORDED"
    session["line_fee_cents"] = recorded * contract["per_line_rate_cents"]
    touch(session)

    contract["committed_fee_cents"] = contract_committed_fee(contract)
    touch(contract)

    plan["voice_recorded_line_count"] = voice_recorded_line_count(plan)
    touch(plan)
    recompute_plan_cost(plan)
    return ok(voice_session_out(session))


@bp.route("/voice-sessions/<voice_session_id>/cancel", methods=["POST"])
@endpoint(PRODUCERS)
def cancel_voice_session(voice_session_id):
    session = fetch("voice_sessions", voice_session_id)
    if session["status"] == "CANCELLED":
        raise ApiError("ERR_SESSION_STATE_INVALID")
    plan = fetch("market_plans", session["market_plan_id"])
    if plan["status"] == "RELEASE_READY":
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "Sessions cannot be cancelled once the market plan is RELEASE_READY",
        )

    cancel_session_cascade(session)
    return ok(voice_session_out(session))
