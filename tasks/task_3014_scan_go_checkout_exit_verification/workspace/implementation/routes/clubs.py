"""Club endpoints."""

from flask import Blueprint

from db import STORE, new_entity, touch
from errors import ApiError, ERR_INVALID_REQUEST, ERR_STALE_VERSION
from logic import get_club, is_int, run_closeout, serialize
from middleware import get_context, get_body, require_role, require_fields
from response import success

bp = Blueprint("clubs", __name__)

VERIFICATION_MODES = {"RECEIPT_CODE", "CV_ARCH", "BOTH"}
POSTURES = {"ONLINE", "DEGRADED", "OFFLINE_FALLBACK"}

CLUB_DEFAULTS = {
    "scan_go_enabled": True,
    "allow_offline_payment": False,
    "lp_unscanned_threshold": 2,
    "lp_suspend_strikes": 3,
    "staging_slot_capacity": 2,
    "receipt_code_ttl_minutes": 30,
    "intercept_ttl_minutes": 10,
}


def _validate_minutes(body, creating):
    if creating or "open_minute" in body:
        om = body.get("open_minute")
        if not is_int(om) or om < 0 or om > 1439:
            raise ApiError(ERR_INVALID_REQUEST, "open_minute must be an integer in [0, 1439].", 400)
    if creating or "early_shopping_start_minute" in body:
        esm = body.get("early_shopping_start_minute")
        if not is_int(esm) or esm < 0 or esm > 1439:
            raise ApiError(ERR_INVALID_REQUEST,
                           "early_shopping_start_minute must be an integer in [0, 1439].", 400)


def _validate_positive_int(body, field, default=None):
    v = body.get(field, default)
    if v is None or not is_int(v) or v < 1:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an integer >= 1.", 400)
    return v


@bp.post("/clubs")
def create_club():
    _, role = get_context()
    require_role(role, ["PlatformAdmin"])
    body = get_body()
    require_fields(body, ["name", "open_minute", "early_shopping_start_minute",
                          "exit_verification_mode"])
    if not isinstance(body["name"], str) or not body["name"]:
        raise ApiError(ERR_INVALID_REQUEST, "name must be a non-empty string.", 400)
    _validate_minutes(body, creating=True)
    if body["exit_verification_mode"] not in VERIFICATION_MODES:
        raise ApiError(ERR_INVALID_REQUEST,
                       "exit_verification_mode must be RECEIPT_CODE, CV_ARCH, or BOTH.", 400)
    if body["early_shopping_start_minute"] >= body["open_minute"]:
        raise ApiError(ERR_INVALID_REQUEST,
                       "early_shopping_start_minute must be strictly earlier than open_minute.", 400)

    club = new_entity()
    club.update({
        "name": body["name"],
        "open_minute": body["open_minute"],
        "early_shopping_start_minute": body["early_shopping_start_minute"],
        "exit_verification_mode": body["exit_verification_mode"],
        "scan_go_enabled": body.get("scan_go_enabled", CLUB_DEFAULTS["scan_go_enabled"]),
        "allow_offline_payment": body.get("allow_offline_payment", CLUB_DEFAULTS["allow_offline_payment"]),
        "lp_unscanned_threshold": _validate_positive_int(body, "lp_unscanned_threshold", 2),
        "lp_suspend_strikes": _validate_positive_int(body, "lp_suspend_strikes", 3),
        "staging_slot_capacity": _validate_positive_int(body, "staging_slot_capacity", 2),
        "receipt_code_ttl_minutes": _validate_positive_int(body, "receipt_code_ttl_minutes", 30),
        "intercept_ttl_minutes": _validate_positive_int(body, "intercept_ttl_minutes", 10),
        "connectivity_posture": "ONLINE",
    })
    if not isinstance(club["scan_go_enabled"], bool) or not isinstance(club["allow_offline_payment"], bool):
        raise ApiError(ERR_INVALID_REQUEST, "Boolean flags must be booleans.", 400)
    STORE.clubs[club["id"]] = club
    return success(serialize(club), status=201)


@bp.get("/clubs/<club_id>")
def get_club_route(club_id):
    get_context()
    return success(serialize(get_club(club_id)))


@bp.patch("/clubs/<club_id>")
def patch_club(club_id):
    _, role = get_context()
    require_role(role, ["ClubManager"])
    club = get_club(club_id)
    body = get_body()
    require_fields(body, ["expected_club_version"])
    if not is_int(body["expected_club_version"]):
        raise ApiError(ERR_INVALID_REQUEST, "expected_club_version must be an integer.", 400)
    if body["expected_club_version"] != club["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_club_version does not match the club's current version.", 412)

    if "open_minute" in body or "early_shopping_start_minute" in body:
        _validate_minutes(body, creating=False)
        new_open = body.get("open_minute", club["open_minute"])
        new_early = body.get("early_shopping_start_minute", club["early_shopping_start_minute"])
        if new_early >= new_open:
            raise ApiError(ERR_INVALID_REQUEST,
                           "early_shopping_start_minute must be strictly earlier than open_minute.", 400)
    if "exit_verification_mode" in body and body["exit_verification_mode"] not in VERIFICATION_MODES:
        raise ApiError(ERR_INVALID_REQUEST,
                       "exit_verification_mode must be RECEIPT_CODE, CV_ARCH, or BOTH.", 400)

    for f in ("open_minute", "early_shopping_start_minute", "exit_verification_mode"):
        if f in body:
            club[f] = body[f]
    for f in ("scan_go_enabled", "allow_offline_payment"):
        if f in body:
            if not isinstance(body[f], bool):
                raise ApiError(ERR_INVALID_REQUEST, f"{f} must be a boolean.", 400)
            club[f] = body[f]
    for f in ("lp_unscanned_threshold", "lp_suspend_strikes", "staging_slot_capacity",
              "receipt_code_ttl_minutes", "intercept_ttl_minutes"):
        if f in body:
            club[f] = _validate_positive_int(body, f)
    touch(club)
    return success(serialize(club))


@bp.post("/clubs/<club_id>/connectivity")
def set_connectivity(club_id):
    _, role = get_context()
    require_role(role, ["ClubManager"])
    club = get_club(club_id)
    body = get_body()
    require_fields(body, ["posture"])
    posture = body["posture"]
    if posture not in POSTURES:
        raise ApiError(ERR_INVALID_REQUEST,
                       "posture must be ONLINE, DEGRADED, or OFFLINE_FALLBACK.", 400)

    club["connectivity_posture"] = posture
    touch(club)

    if posture == "OFFLINE_FALLBACK":
        # Pause OPEN/REVIEW_HOLD sessions; expire their PENDING intercepts and
        # remove those lines; recompute provisional totals.
        from logic import deny_intercept, recompute_session
        for session in STORE.sessions.values():
            if session["club_id"] != club["id"]:
                continue
            if session["status"] not in ("OPEN", "REVIEW_HOLD"):
                continue
            was_hold = session["status"] == "REVIEW_HOLD"
            session["status"] = "OFFLINE_PAUSED"
            if was_hold:
                for intercept in list(STORE.intercepts.values()):
                    if intercept["session_id"] == session["id"] and intercept["status"] == "PENDING":
                        deny_intercept(intercept, "EXPIRED")
                session["status"] = "OFFLINE_PAUSED"
                recompute_session(session)
            touch(session)
    else:
        # ONLINE or DEGRADED: OFFLINE_PAUSED sessions resume to OPEN.
        for session in STORE.sessions.values():
            if session["club_id"] == club["id"] and session["status"] == "OFFLINE_PAUSED":
                session["status"] = "OPEN"
                touch(session)
    return success(serialize(club))


@bp.post("/clubs/<club_id>/run-closeout")
def closeout(club_id):
    _, role = get_context()
    require_role(role, ["ClubManager"])
    club = get_club(club_id)
    run_closeout(club)
    return success(serialize(club))
