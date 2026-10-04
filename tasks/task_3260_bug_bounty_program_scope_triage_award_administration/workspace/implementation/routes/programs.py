"""Program endpoints: create, read, patch (OCC), activate, pause, close."""
from flask import Blueprint, request

import clock
import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_PROGRAM_NOT_ACTIVE, ERR_SCOPE_VERSION_REQUIRED, ERR_POOL_EXHAUSTED,
    ERR_BLACKOUT_OVERLAP, ERR_STALE_VERSION,
)
from helpers import (
    base_entity, touch, get_body, require_fields, reject_unknown_fields,
)
from middleware import require_roles
from response import success_object
from serializers import program_out
from services import cascades

bp = Blueprint("programs", __name__)

CREATE_FIELDS = {
    "name", "visibility", "min_reputation", "response_sla_hours",
    "resolution_sla_days", "disclosure_window_days", "first_report_bonus_pct",
    "retest_award_cents", "bonus_cap_cents", "exposure_modifier",
    "bounty_pool_cents", "blackout_windows",
}

PATCH_FIELDS = CREATE_FIELDS | {"expected_program_version"}


def _get_program(pid):
    p = db.programs.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, f"Program {pid} not found")
    return p


def _validate_blackouts(windows):
    """Closed intervals, pairwise non-overlapping with >= 3600s gap."""
    if not isinstance(windows, list):
        raise_err(ERR_INVALID_REQUEST, "blackout_windows must be an array")
    parsed = []
    for w in windows:
        if not isinstance(w, dict) or "starts_at" not in w or "ends_at" not in w:
            raise_err(ERR_INVALID_REQUEST, "blackout window requires starts_at and ends_at")
        try:
            s = clock.parse_iso(w["starts_at"])
            e = clock.parse_iso(w["ends_at"])
        except Exception:
            raise_err(ERR_INVALID_REQUEST, "blackout window timestamps malformed")
        if e < s:
            raise_err(ERR_INVALID_REQUEST, "blackout window ends_at before starts_at")
        parsed.append((s, e))
    parsed.sort()
    for i in range(1, len(parsed)):
        gap = (parsed[i][0] - parsed[i - 1][1]).total_seconds()
        # closed intervals: starts_at == prior ends_at means overlap (gap 0);
        # need strictly more than 3600s separation... spec: "at least 3600
        # seconds between any two" -> gap >= 3600 after the prior window ends.
        if gap < 3600:
            raise_err(
                ERR_BLACKOUT_OVERLAP,
                "Blackout windows overlap or are separated by less than 3600 seconds",
            )
    return parsed


def _scope_version_effective(program_id, now):
    for v in db.scope_versions.values():
        if v["program_id"] != program_id:
            continue
        ef = clock.parse_iso(v["effective_from"])
        et = v.get("effective_to")
        if ef <= now and (et is None or now < clock.parse_iso(et)):
            return v
    return None


@bp.route("/api/programs", methods=["POST"])
def create_program():
    require_roles({"PlatformAdmin"})
    body = get_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    require_fields(
        body,
        ["name", "bounty_pool_cents", "min_reputation", "response_sla_hours",
         "resolution_sla_days", "disclosure_window_days"],
    )
    visibility = body.get("visibility", "PUBLIC")
    if visibility not in ("PUBLIC", "PRIVATE"):
        raise_err(ERR_INVALID_REQUEST, "visibility must be PUBLIC or PRIVATE")
    if "blackout_windows" in body:
        _validate_blackouts(body["blackout_windows"])
    p = base_entity()
    p.update(
        {
            "name": body["name"],
            "visibility": visibility,
            "status": "DRAFT",
            "min_reputation": body["min_reputation"],
            "response_sla_hours": body["response_sla_hours"],
            "resolution_sla_days": body["resolution_sla_days"],
            "disclosure_window_days": body["disclosure_window_days"],
            "first_report_bonus_pct": body.get("first_report_bonus_pct", 0.10),
            "retest_award_cents": body.get("retest_award_cents", 50000),
            "bonus_cap_cents": body.get("bonus_cap_cents", 100000),
            "exposure_modifier": body.get("exposure_modifier", 1.0),
            "bounty_pool_cents": body["bounty_pool_cents"],
            "bounty_reserved_cents": 0,
            "bounty_paid_cents": 0,
            "total_withheld_cents": 0,
            "blackout_windows": body.get("blackout_windows", []),
        }
    )
    db.programs[p["id"]] = p
    return success_object(program_out(p), 201)


@bp.route("/api/programs/<program_id>", methods=["GET"])
def read_program(program_id):
    require_roles({"PlatformAdmin", "ProgramAdmin", "Triager", "Researcher"})
    p = _get_program(program_id)
    return success_object(program_out(p))


@bp.route("/api/programs/<program_id>", methods=["PATCH"])
def patch_program(program_id):
    require_roles({"ProgramAdmin"})
    p = _get_program(program_id)
    body = get_body()
    reject_unknown_fields(body, PATCH_FIELDS)
    if "expected_program_version" not in body or body["expected_program_version"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: expected_program_version")
    if p["status"] == "CLOSED":
        raise_err(ERR_INVALID_STATE, "CLOSED program rejects all mutations")
    # validate blackout overlap before OCC? Validation order: temporal windows
    # priority 13 covers both ERR_BLACKOUT_OVERLAP and ERR_STALE_VERSION; the
    # OCC mismatch surfaces as ERR_STALE_VERSION. Check OCC first per §2.7.
    if body["expected_program_version"] != p["version"]:
        raise_err(ERR_STALE_VERSION, "Program version mismatch")
    if "blackout_windows" in body:
        _validate_blackouts(body["blackout_windows"])
    if "visibility" in body:
        raise_err(ERR_INVALID_REQUEST, "Unknown or read-only field: visibility")
    if "bounty_pool_cents" in body:
        new_pool = body["bounty_pool_cents"]
        if not isinstance(new_pool, int) or isinstance(new_pool, bool):
            raise_err(ERR_INVALID_REQUEST, "bounty_pool_cents must be an integer")
        if new_pool < p["bounty_reserved_cents"] + p["bounty_paid_cents"]:
            raise_err(
                ERR_POOL_EXHAUSTED,
                "bounty_pool_cents may not drop below reserved + paid",
            )
    for f in (
        "name", "bounty_pool_cents", "min_reputation", "response_sla_hours",
        "resolution_sla_days", "disclosure_window_days", "first_report_bonus_pct",
        "retest_award_cents", "bonus_cap_cents", "exposure_modifier",
        "blackout_windows",
    ):
        if f in body:
            p[f] = body[f]
    touch(p)
    return success_object(program_out(p))


@bp.route("/api/programs/<program_id>/activate", methods=["POST"])
def activate_program(program_id):
    require_roles({"ProgramAdmin"})
    p = _get_program(program_id)
    if p["status"] not in ("DRAFT", "PAUSED"):
        raise_err(ERR_INVALID_STATE, f"Cannot activate program in {p['status']}")
    if _scope_version_effective(program_id, clock.now()) is None:
        raise_err(ERR_SCOPE_VERSION_REQUIRED, "No scope version effective at current time")
    p["status"] = "ACTIVE"
    touch(p)
    return success_object(program_out(p))


@bp.route("/api/programs/<program_id>/pause", methods=["POST"])
def pause_program(program_id):
    require_roles({"ProgramAdmin"})
    p = _get_program(program_id)
    if p["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"Cannot pause program in {p['status']}")
    p["status"] = "PAUSED"
    touch(p)
    return success_object(program_out(p))


@bp.route("/api/programs/<program_id>/close", methods=["POST"])
def close_program(program_id):
    require_roles({"ProgramAdmin"})
    p = _get_program(program_id)
    if p["status"] == "CLOSED":
        raise_err(ERR_INVALID_STATE, "Program already CLOSED")
    for rep in db.reports.values():
        if rep["program_id"] == program_id and rep["status"] in (
            "NEW", "TRIAGED", "NEEDS_INFO", "VALIDATED",
        ):
            raise_err(ERR_INVALID_STATE, "Program has in-flight reports")
    for a in db.awards.values():
        rep = db.reports.get(a["report_id"])
        if rep and rep["program_id"] == program_id and a["status"] in (
            "PROPOSED", "APPROVED", "BLOCKED",
        ):
            raise_err(ERR_INVALID_STATE, "Program has in-flight awards")
    p["status"] = "CLOSED"
    touch(p)
    cascades.decline_pending_invitations_for_program(program_id)
    return success_object(program_out(p))
