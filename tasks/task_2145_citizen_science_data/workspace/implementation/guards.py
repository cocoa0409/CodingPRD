"""The request admission ladder (PRD 2.7): auth, existence, payload shape, FKs."""
from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation

from flask import request

import clock
import db
from errors import ApiError

ROLES = ("ProgramAdmin", "Volunteer", "Expert", "ResearchPartner")

ENTITY_BACKED = {
    "Volunteer": (lambda: db.volunteers),
    "Expert": (lambda: db.experts),
    "ResearchPartner": (lambda: db.partners),
}


# --------------------------------------------------------------------------
# priorities 1-3
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return {"id": user_id, "role": role}


# --------------------------------------------------------------------------
# priority 5
# --------------------------------------------------------------------------
def resolve_actor(actor):
    """Return the backing row for an entity-backed role, or None for admin."""
    role = actor["role"]
    if role not in ENTITY_BACKED:
        return None
    row = ENTITY_BACKED[role]().get(actor["id"])
    if row is None:
        raise ApiError("ERR_ACTOR_NOT_FOUND")
    return row


# --------------------------------------------------------------------------
# priority 4 / 7 — existence lookups
# --------------------------------------------------------------------------
def _lookup(coll, key, error_id):
    row = coll.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def get_protocol(pid):
    return _lookup(db.protocols, pid, "ERR_PROTOCOL_NOT_FOUND")


def get_volunteer(pid):
    return _lookup(db.volunteers, pid, "ERR_VOLUNTEER_NOT_FOUND")


def get_expert(pid):
    return _lookup(db.experts, pid, "ERR_EXPERT_NOT_FOUND")


def get_certification(pid):
    return _lookup(db.certifications, pid, "ERR_CERTIFICATION_NOT_FOUND")


def get_campaign(pid):
    return _lookup(db.campaigns, pid, "ERR_CAMPAIGN_NOT_FOUND")


def get_site(pid):
    return _lookup(db.sites, pid, "ERR_SITE_NOT_FOUND")


def get_observation(pid):
    return _lookup(db.observations, pid, "ERR_OBSERVATION_NOT_FOUND")


def get_equipment(pid):
    return _lookup(db.equipment, pid, "ERR_EQUIPMENT_NOT_FOUND")


def get_loan(pid):
    return _lookup(db.loans, pid, "ERR_LOAN_NOT_FOUND")


def get_publication(pid):
    return _lookup(db.publications, pid, "ERR_PUBLICATION_NOT_FOUND")


def get_partner(pid):
    return _lookup(db.partners, pid, "ERR_PARTNER_NOT_FOUND")


def get_grant(pid):
    return _lookup(db.grants, pid, "ERR_GRANT_NOT_FOUND")


def get_award(pid):
    return _lookup(db.awards, pid, "ERR_AWARD_NOT_FOUND")


# --------------------------------------------------------------------------
# datetime / date parsing
# --------------------------------------------------------------------------
def parse_datetime(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


# --------------------------------------------------------------------------
# priority 6 — payload shape
# --------------------------------------------------------------------------
def _bad():
    raise ApiError("ERR_INVALID_REQUEST")


def raw_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        _bad()
    if not isinstance(body, dict):
        _bad()
    return body


def validate_body(spec):
    """spec: list of field descriptors.  Returns a dict of coerced values."""
    body = raw_body()
    out = {}
    for f in spec:
        name = f["name"]
        present = name in body and body[name] is not None
        if not present:
            if f.get("required"):
                _bad()
            if "default" in f:
                out[name] = f["default"]
            continue
        out[name] = _coerce(body[name], f)
    return out


def _coerce(value, f):
    kind = f["type"]
    if kind == "string":
        if not isinstance(value, str):
            _bad()
        if not f.get("allow_empty") and not value.strip():
            _bad()
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad()
        _range(value, f)
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad()
        try:
            dec = Decimal(str(value))
        except InvalidOperation:
            _bad()
        _range(dec, f)
        return dec
    if kind == "enum":
        if not isinstance(value, str) or value not in f["values"]:
            _bad()
        return value
    if kind == "datetime":
        parsed = parse_datetime(value)
        if parsed is None:
            _bad()
        return parsed
    if kind == "date":
        parsed = parse_date(value)
        if parsed is None:
            _bad()
        return parsed
    if kind == "id":
        if not isinstance(value, str) or not value.strip():
            _bad()
        return value
    _bad()


def _range(value, f):
    if "min" in f and value < f["min"]:
        _bad()
    if "max" in f and value > f["max"]:
        _bad()
    if "gt" in f and not value > f["gt"]:
        _bad()


# --------------------------------------------------------------------------
# pagination + filtering
# --------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            _bad()
        if limit < 1 or limit > 100:
            _bad()
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            _bad()
        if offset < 0:
            _bad()
    return limit, offset


def apply_filters(rows, names):
    args = request.args
    out = rows
    for name in names:
        if name not in args:
            continue
        wanted = args.get(name)
        out = [r for r in out if _matches(r.get(name), wanted)]
    return out


def _matches(actual, wanted):
    if actual is None:
        return False
    if isinstance(actual, bool):
        return str(actual).lower() == str(wanted).lower()
    if isinstance(actual, int):
        try:
            return actual == int(str(wanted).strip())
        except (TypeError, ValueError):
            return False
    return str(actual) == str(wanted)


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, limit, offset, total


# --------------------------------------------------------------------------
# priority 48 — uniqueness helpers
# --------------------------------------------------------------------------
def require_unique(coll, field, value, scope_field=None, scope_value=None):
    for row in coll.values():
        if row.get(field) != value:
            continue
        if scope_field is not None and row.get(scope_field) != scope_value:
            continue
        raise ApiError("ERR_DUPLICATE_KEY")
