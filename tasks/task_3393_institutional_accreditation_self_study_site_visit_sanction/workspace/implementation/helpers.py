"""Shared request/entity helpers: validation, pagination, entity lifecycle.

Global validation order implemented across the routes (PRD §2.8):
  (1) authentication -> (2) role permission / entity-backed ownership
  -> (3) path existence, left to right -> (4) payload well-formedness
  (ERR_VALIDATION) and OCC -> (5) state-machine checks -> (6) business rules
  in the scaffold's priority order.
"""
from flask import request

import constants as C
from db import STORE
from errors import ERR_VALIDATION, raise_err


# --- Entity lifecycle -----------------------------------------------------------
def new_entity(fields):
    now = STORE.now_iso()
    entity = dict(fields)
    entity["id"] = STORE.new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = STORE.next_seq()
    return entity


def touch(entity):
    """Every stored-state write refreshes updated_at and advances version (§2.5)."""
    entity["updated_at"] = STORE.now_iso()
    entity["version"] += 1


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def fetch_or_404(table, entity_id, error_spec):
    entity = table.get(entity_id)
    if entity is None:
        raise_err(error_spec, "No resource with id %s" % entity_id)
    return entity


# --- Request body ---------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_VALIDATION, "Request body must be a JSON object")
    return body


def _fail(msg):
    raise_err(ERR_VALIDATION, msg)


def req_string(body, field):
    value = body.get(field)
    if not isinstance(value, str) or value == "":
        _fail("Field '%s' is required and must be a non-empty string" % field)
    return value


def opt_string(body, field):
    if field not in body or body[field] is None:
        return None
    value = body[field]
    if not isinstance(value, str):
        _fail("Field '%s' must be a string" % field)
    return value


def req_enum(body, field, allowed):
    value = body.get(field)
    if value not in allowed:
        _fail("Field '%s' must be one of %s" % (field, allowed))
    return value


def opt_enum(body, field, allowed):
    if field not in body or body[field] is None:
        return None
    return req_enum(body, field, allowed)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def req_int(body, field, minimum=None):
    value = body.get(field)
    if not _is_int(value):
        _fail("Field '%s' is required and must be an integer" % field)
    if minimum is not None and value < minimum:
        _fail("Field '%s' must be >= %s" % (field, minimum))
    return value


def opt_int(body, field, minimum=None):
    if field not in body or body[field] is None:
        return None
    return req_int(body, field, minimum)


def req_number(body, field, minimum=None, maximum=None):
    value = body.get(field)
    if not _is_number(value):
        _fail("Field '%s' is required and must be a number" % field)
    if minimum is not None and value < minimum:
        _fail("Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        _fail("Field '%s' must be <= %s" % (field, maximum))
    return value


def opt_number(body, field, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return None
    return req_number(body, field, minimum, maximum)


def req_bool(body, field):
    value = body.get(field)
    if not isinstance(value, bool):
        _fail("Field '%s' is required and must be a boolean" % field)
    return value


def opt_bool(body, field):
    if field not in body or body[field] is None:
        return None
    return req_bool(body, field)


def req_list(body, field):
    value = body.get(field)
    if not isinstance(value, list):
        _fail("Field '%s' is required and must be an array" % field)
    return value


def opt_list(body, field):
    if field not in body or body[field] is None:
        return None
    return req_list(body, field)


def req_enum_list(body, field, allowed, non_empty=False):
    value = req_list(body, field)
    if non_empty and len(value) == 0:
        _fail("Field '%s' must be a non-empty array" % field)
    for item in value:
        if item not in allowed:
            _fail("Field '%s' must contain only members of %s" % (field, allowed))
    return value


def req_string_list(body, field):
    value = req_list(body, field)
    for item in value:
        if not isinstance(item, str):
            _fail("Field '%s' must contain only strings" % field)
    return value


# --- Pagination (PRD §2.3) -------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = C.PAGE_DEFAULT_LIMIT
    offset = C.PAGE_DEFAULT_OFFSET
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            _fail("limit must be an integer")
        if limit < C.PAGE_MIN_LIMIT or limit > C.PAGE_MAX_LIMIT:
            _fail("limit must be between 1 and 100")
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            _fail("offset must be an integer")
        if offset < 0:
            _fail("offset must be >= 0")
    return limit, offset


def paginate(items):
    """items: pre-filtered list. Sorts by creation ascending, then pages."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(e) for e in page], total, limit, offset


# --- Shared business helpers ------------------------------------------------------
def reviewer_assignment_count(reviewer_id):
    """current_assignment_count: PENDING/ACCEPTED, ACTIVE, team not DISBANDED."""
    count = 0
    for a in STORE.team_assignments.values():
        if a["reviewer_id"] != reviewer_id:
            continue
        if a["response"] not in ("PENDING", "ACCEPTED") or a["status"] != "ACTIVE":
            continue
        team = STORE.review_teams.get(a["review_team_id"])
        if team is None or team["status"] == "DISBANDED":
            continue
        count += 1
    return count


def freeze_substantive_changes(institution_id):
    """Sanction imposition freeze: in-flight SUBMITTED requests -> DEFERRED (§2.11)."""
    for req in STORE.substantive_change_requests.values():
        if req["institution_id"] == institution_id and req["status"] == "SUBMITTED":
            req["status"] = "DEFERRED"
            req["decision_notes"] = "frozen by sanction"
            touch(req)
