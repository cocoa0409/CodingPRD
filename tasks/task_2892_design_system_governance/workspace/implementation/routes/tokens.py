"""Token sets, design tokens, alias resolution (PRD 3.2)."""

from flask import Blueprint

import calc
import errors
from auth import DESIGN_SYSTEM_LEAD, SYSTEM_ADMIN, require_roles
from entities import get_token, get_token_set, token_json, token_set_json
from errors import fail
from responses import created, ok
from routes.common import respond_list
from store import sort_created_asc, store
from validation import (body, opt_enum, opt_string, pagination, present,
                        query_enum, query_string, req_enum, req_int, req_string)

bp = Blueprint("tokens", __name__, url_prefix="/design-system")

BRANDS = ("BASE", "BRAND_A", "BRAND_B")
SET_MODES = ("LIGHT", "DARK")
TOKEN_MODES = ("LIGHT", "DARK", "ANY")
CATEGORIES = ("COLOR", "TYPOGRAPHY", "SPACING")


# --------------------------------------------------------------------------
# token sets
# --------------------------------------------------------------------------
@bp.post("/token-sets")
@require_roles(SYSTEM_ADMIN, DESIGN_SYSTEM_LEAD)
def create_token_set():
    payload = body()
    name = req_string(payload, "name", 1, 120)
    slug = req_string(payload, "slug", 1, 120)
    default_brand = opt_enum(payload, "default_brand", BRANDS, "BASE")
    default_mode = opt_enum(payload, "default_mode", SET_MODES, "LIGHT")

    for existing in store.token_sets.values():
        if existing["slug"] == slug:
            fail(errors.ERR_UNIQUENESS_CONFLICT,
                 "A token set with slug '%s' already exists." % slug)

    row = store.new_row()
    row.update({
        "name": name,
        "slug": slug,
        "default_brand": default_brand,
        "default_mode": default_mode,
        "token_count": 0,
        "max_alias_depth": 0,
    })
    store.token_sets[row["id"]] = row
    return created(token_set_json(row))


@bp.get("/token-sets")
@require_roles()
def list_token_sets():
    limit, offset = pagination()
    rows = sort_created_asc(list(store.token_sets.values()))
    return respond_list(rows, token_set_json, limit, offset)


@bp.get("/token-sets/<token_set_id>")
@require_roles()
def read_token_set(token_set_id):
    return ok(token_set_json(get_token_set(token_set_id)))


@bp.get("/token-sets/<token_set_id>/resolved-tokens")
@require_roles()
def resolved_tokens(token_set_id):
    brand = query_enum("brand", BRANDS)
    mode = query_enum("mode", SET_MODES)
    token_set = get_token_set(token_set_id)
    brand = brand or token_set["default_brand"]
    mode = mode or token_set["default_mode"]
    entries = calc.resolve_layers(token_set["id"], brand, mode)
    return ok({
        "token_set_id": token_set["id"],
        "brand": brand,
        "mode": mode,
        "max_alias_depth": token_set["max_alias_depth"],
        "resolved_count": len(entries),
        "resolved": entries,
    })


# --------------------------------------------------------------------------
# design tokens
# --------------------------------------------------------------------------
def _leaf_or_alias(payload):
    raw_value = opt_string(payload, "raw_value", 1, None, allow_null=True)
    alias_of = opt_string(payload, "alias_of_token_id", 1, 200, allow_null=True)
    if (raw_value is None) == (alias_of is None):
        fail(errors.ERR_INVALID_REQUEST,
             "Exactly one of 'raw_value' and 'alias_of_token_id' must be non-null.")
    return raw_value, alias_of


def _name_conflict(token_set_id, name, brand, mode, exclude_id=None):
    for tok in calc.set_tokens(token_set_id):
        if tok["id"] == exclude_id:
            continue
        if (tok["name"] == name and tok["brand"] == brand and tok["mode"] == mode):
            fail(errors.ERR_TOKEN_NAME_CONFLICT,
                 "A token already exists at these coordinates.")


@bp.post("/tokens")
@require_roles(DESIGN_SYSTEM_LEAD)
def create_token():
    payload = body()
    token_set_id = req_string(payload, "token_set_id", 1, 200)
    name = req_string(payload, "name", 1, 200)
    category = req_enum(payload, "category", CATEGORIES)
    expected_version = req_int(payload, "expected_token_set_version", minimum=0)
    brand = opt_enum(payload, "brand", BRANDS, "BASE")
    mode = opt_enum(payload, "mode", TOKEN_MODES, "ANY")
    raw_value, alias_of = _leaf_or_alias(payload)

    token_set = get_token_set(token_set_id)
    target = None
    if alias_of is not None:
        target = store.tokens.get(alias_of)
        if target is not None and target["token_set_id"] != token_set["id"]:
            fail(errors.ERR_INVALID_REQUEST,
                 "An alias target must live in the same token set.")
        if target is None:
            fail(errors.ERR_TOKEN_NOT_FOUND,
                 "Design token '%s' does not exist." % alias_of)

    if expected_version != token_set["version"]:
        fail(errors.ERR_STALE_TOKEN_SET_VERSION,
             "The token set has moved on; expected version %s." % token_set["version"])

    row = store.new_row()
    row.update({
        "token_set_id": token_set["id"],
        "name": name,
        "category": category,
        "brand": brand,
        "mode": mode,
        "raw_value": raw_value,
        "alias_of_token_id": alias_of,
        "alias_depth": 0,
        "resolved_value": None,
    })

    calc.check_alias_cycles(token_set["id"], extra=row)
    _name_conflict(token_set["id"], name, brand, mode)
    calc.check_alias_depth(token_set["id"], extra=row)

    store.tokens[row["id"]] = row
    calc.recompute_token_set(token_set)
    store.touch(token_set)
    return created(token_json(row))


@bp.put("/tokens/<token_id>")
@require_roles(DESIGN_SYSTEM_LEAD)
def repoint_token(token_id):
    payload = body()
    expected_version = req_int(payload, "expected_token_set_version", minimum=0)
    raw_value, alias_of = _leaf_or_alias(payload)

    token = get_token(token_id)
    token_set = store.token_sets[token["token_set_id"]]

    if alias_of is not None:
        target = store.tokens.get(alias_of)
        if target is not None and target["token_set_id"] != token_set["id"]:
            fail(errors.ERR_INVALID_REQUEST,
                 "An alias target must live in the same token set.")
        if target is None:
            fail(errors.ERR_TOKEN_NOT_FOUND,
                 "Design token '%s' does not exist." % alias_of)

    if expected_version != token_set["version"]:
        fail(errors.ERR_STALE_TOKEN_SET_VERSION,
             "The token set has moved on; expected version %s." % token_set["version"])

    override = {"id": token["id"], "raw_value": raw_value,
                "alias_of_token_id": alias_of}
    calc.check_alias_cycles(token_set["id"], override=override)
    calc.check_alias_depth(token_set["id"], override=override)

    token["raw_value"] = raw_value
    token["alias_of_token_id"] = alias_of
    changed, resolved = calc.recompute_token_set(token_set)

    for other_id in changed:
        if other_id == token["id"]:
            continue
        store.touch(store.tokens[other_id], bump=False)
    store.touch(token)
    store.touch(token_set)
    return ok(token_json(token))


@bp.get("/tokens")
@require_roles()
def list_tokens():
    limit, offset = pagination()
    token_set_id = query_string("token_set_id")
    alias_of_token_id = query_string("alias_of_token_id")
    category = query_enum("category", CATEGORIES)
    brand = query_enum("brand", BRANDS)
    mode = query_enum("mode", TOKEN_MODES)

    rows = list(store.tokens.values())
    if token_set_id is not None:
        rows = [t for t in rows if t["token_set_id"] == token_set_id]
    if alias_of_token_id is not None:
        rows = [t for t in rows if t["alias_of_token_id"] == alias_of_token_id]
    if category is not None:
        rows = [t for t in rows if t["category"] == category]
    if brand is not None:
        rows = [t for t in rows if t["brand"] == brand]
    if mode is not None:
        rows = [t for t in rows if t["mode"] == mode]
    return respond_list(sort_created_asc(rows), token_json, limit, offset)


@bp.get("/tokens/<token_id>")
@require_roles()
def read_token(token_id):
    return ok(token_json(get_token(token_id)))
