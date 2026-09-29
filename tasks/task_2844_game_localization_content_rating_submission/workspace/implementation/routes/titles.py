"""Title endpoints (PRD SS3.1)."""
import re

from flask import Blueprint

from constants import (
    ALL_ROLES,
    RELEASE_MODES,
    ROLE_LOCALIZATION_PRODUCER,
    SOURCE_LANGUAGES,
)
from db import base_row, db, fetch, insert, rows, touch
from derive import by_created, recompute_plan_required, refresh_title, title_keys, title_plans
from errors import ApiError
from middleware import endpoint
from response import created, ok, paginated
from routehelp import arg, match_all
from serialize import nk_title, title_out
from validation import bad, json_body, opt_enum, req_instant, req_str

bp = Blueprint("titles", __name__)

TITLE_CODE_RE = re.compile(r"^[A-Z0-9-]{3,16}$")

PRODUCERS = [ROLE_LOCALIZATION_PRODUCER]


@bp.route("/titles", methods=["POST"])
@endpoint(PRODUCERS)
def create_title():
    body = json_body()
    title_code = req_str(body, "title_code", 3, 16)
    if not TITLE_CODE_RE.match(title_code):
        bad("title_code must match ^[A-Z0-9-]{3,16}$")
    name = req_str(body, "name", 1, 120)
    source_language = opt_enum(body, "source_language", SOURCE_LANGUAGES, "EN", nullable=False)
    target_release_utc = req_instant(body, "target_release_utc")
    release_mode = opt_enum(body, "release_mode", RELEASE_MODES, "SIMULTANEOUS", nullable=False)
    if target_release_utc <= db.now():
        bad("target_release_utc must be strictly after the current logical clock")

    if any(t["title_code"] == title_code for t in rows("titles")):
        raise ApiError("ERR_DUPLICATE_TITLE_CODE")

    row = base_row()
    row.update({
        "title_code": title_code,
        "name": name,
        "source_language": source_language,
        "target_release_utc": target_release_utc,
        "release_mode": release_mode,
        "localization_state": "PLANNING",
        "string_lock": False,
        "extracted_key_count": 0,
        "market_plan_count": 0,
        "ready_market_count": 0,
        "release_gate_state": "OPEN",
    })
    insert("titles", row)
    return created(title_out(row))


@bp.route("/titles/<title_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_title(title_id):
    return ok(title_out(fetch("titles", title_id)))


@bp.route("/titles", methods=["GET"])
@endpoint(ALL_ROLES)
def list_titles():
    pairs = [
        ("localization_state", arg("localization_state")),
        ("release_mode", arg("release_mode")),
        ("release_gate_state", arg("release_gate_state")),
    ]
    items = [t for t in rows("titles") if match_all(t, pairs)]
    return paginated(items, title_out, nk_title)


@bp.route("/titles/<title_id>/lock-strings", methods=["POST"])
@endpoint(PRODUCERS)
def lock_strings(title_id):
    title = fetch("titles", title_id)

    # rung 11 -- own-state precondition
    if title["localization_state"] != "PLANNING":
        raise ApiError("ERR_TITLE_STRINGS_ALREADY_LOCKED")

    # rung 12 -- structural preconditions
    extracted = [k for k in title_keys(title["id"]) if k["status"] == "EXTRACTED"]
    if not extracted:
        raise ApiError(
            "ERR_PREREQUISITE_STATE_NOT_MET",
            "The title must own at least one EXTRACTED string key",
        )
    for key in extracted:
        if key["ui_surface"] == "LEGAL" and key["context_note"] is None:
            raise ApiError(
                "ERR_PREREQUISITE_STATE_NOT_MET",
                "Every EXTRACTED LEGAL string key must carry a context_note",
            )

    # downward cascade: freeze every extracted key
    for key in by_created(extracted):
        key["status"] = "LOCKED"
        touch(key)

    title["localization_state"] = "STRINGS_LOCKED"
    title["string_lock"] = True
    touch(title)

    for plan in by_created(title_plans(title["id"])):
        recompute_plan_required(plan)

    refresh_title(title)
    return ok(title_out(title))
