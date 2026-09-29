"""String key endpoints (PRD SS3.1)."""
from flask import Blueprint

from constants import ALL_ROLES, ROLE_LOCALIZATION_PRODUCER, UI_SURFACES
from db import base_row, fetch, insert, rows, touch
from derive import refresh_title
from errors import ApiError
from middleware import endpoint
from response import created, ok, paginated
from routehelp import arg, match_all
from serialize import nk_string_key, string_key_out
from validation import json_body, opt_bool, opt_int, opt_str, present, req_enum, req_id, req_int, req_str

bp = Blueprint("string_keys", __name__)

PRODUCERS = [ROLE_LOCALIZATION_PRODUCER]


@bp.route("/string-keys", methods=["POST"])
@endpoint(PRODUCERS)
def create_string_key():
    body = json_body()
    title_id = req_id(body, "title_id")
    key_name = req_str(body, "key_name", 1, 80)
    source_text = req_str(body, "source_text", 1, 2000)
    source_char_count = req_int(body, "source_char_count", 1)
    ui_surface = req_enum(body, "ui_surface", UI_SURFACES)
    display_char_limit = req_int(body, "display_char_limit", 1)
    tm_match_pct = req_int(body, "tm_match_pct", 0, 100)
    context_note = opt_str(body, "context_note", 1, 500)

    title = fetch("titles", title_id)

    if any(
        k["title_id"] == title_id and k["key_name"] == key_name
        for k in rows("string_keys")
    ):
        raise ApiError("ERR_DUPLICATE_STRING_KEY")

    row = base_row()
    row.update({
        "title_id": title_id,
        "key_name": key_name,
        "source_text": source_text,
        "source_char_count": source_char_count,
        "ui_surface": ui_surface,
        "display_char_limit": display_char_limit,
        "tm_match_pct": tm_match_pct,
        "context_note": context_note,
        "status": "EXTRACTED",
    })
    insert("string_keys", row)
    refresh_title(title)
    return created(string_key_out(row))


@bp.route("/string-keys/<string_key_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_string_key(string_key_id):
    return ok(string_key_out(fetch("string_keys", string_key_id)))


@bp.route("/string-keys", methods=["GET"])
@endpoint(ALL_ROLES)
def list_string_keys():
    pairs = [
        ("title_id", arg("title_id")),
        ("ui_surface", arg("ui_surface")),
        ("status", arg("status")),
    ]
    items = [k for k in rows("string_keys") if match_all(k, pairs)]
    return paginated(items, string_key_out, nk_string_key)


@bp.route("/string-keys/<string_key_id>", methods=["PATCH"])
@endpoint(PRODUCERS)
def amend_string_key(string_key_id):
    body = json_body()
    has_note = present(body, "context_note")
    context_note = opt_str(body, "context_note", 1, 500) if has_note else None
    tm_match_pct = opt_int(body, "tm_match_pct", 0, 100)
    retire = opt_bool(body, "retire", False)

    key = fetch("string_keys", string_key_id)

    # rung 11 -- amendments are only accepted while the key is EXTRACTED
    if key["status"] != "EXTRACTED":
        raise ApiError("ERR_STRING_KEY_LOCKED")

    changed = False
    if has_note and key["context_note"] != context_note:
        key["context_note"] = context_note
        changed = True
    if tm_match_pct is not None and key["tm_match_pct"] != tm_match_pct:
        key["tm_match_pct"] = tm_match_pct
        changed = True
    if retire:
        key["status"] = "RETIRED"
        changed = True

    if changed:
        touch(key)
        title = fetch("titles", key["title_id"])
        refresh_title(title)
    return ok(string_key_out(key))
