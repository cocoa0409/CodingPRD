"""Auth middleware and request-validation helpers (PRD §2.1, §2.8, §2.9)."""
from __future__ import annotations

import functools

from flask import request

from errors import fail
from store import get
from util import is_int, now, parse_ts

ROLES = {"OpsAdmin", "ComplianceOfficer", "Clinician", "Patient", "PayrollService", "Anonymous"}

ENTITY_BACKED = {"Clinician": "clinicians", "PatientClient": "patients"}


def identity():
    """Resolve the acting identity once per request."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise fail("ERR_UNAUTHENTICATED")
    if not role or role not in ROLES:
        raise fail("ERR_UNAUTHENTICATED")
    return {"id": user_id, "role": role}


def require_roles(*allowed):
    """Enforce auth (priority 1), endpoint permission (priority 2) and, for
    entity-backed roles, that X-User-ID resolves to an existing instance."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            ident = identity()
            if ident["role"] not in allowed:
                raise fail("ERR_UNAUTHORIZED")
            if ident["role"] == "Clinician":
                if get("clinicians", ident["id"]) is None:
                    raise fail("ERR_UNAUTHORIZED")
            elif ident["role"] == "Patient":
                if get("patients", ident["id"]) is None:
                    raise fail("ERR_UNAUTHORIZED")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


_BODY_UNSET = object()


class Body:
    """Validated request body accessor with the ERR_INVALID_REQUEST shape (PRD §2.9)."""

    def __init__(self, payload):
        self.payload = payload if isinstance(payload, dict) else {}
        self.consumed = set()

    @staticmethod
    def read():
        raw = request.get_json(silent=True)
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
        return Body(raw)

    def _mark(self, name):
        self.consumed.add(name)

    def finish(self):
        for key in self.payload:
            if key not in self.consumed:
                raise fail("ERR_INVALID_REQUEST", f"Unknown field '{key}'.")

    def raw(self, name):
        self._mark(name)
        return self.payload.get(name, _BODY_UNSET)

    def has(self, name):
        value = self.raw(name)
        return value is not _BODY_UNSET and value is not None

    def string(self, name, required=True, allow_empty=False):
        value = self.raw(name)
        if value is _BODY_UNSET or value is None:
            if required:
                raise fail("ERR_INVALID_REQUEST", f"Field '{name}' is required.")
            return None
        if not isinstance(value, str):
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must be a string.")
        if not allow_empty and value.strip() == "":
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must not be empty.")
        return value

    def optional_string(self, name):
        value = self.raw(name)
        if value is _BODY_UNSET or value is None:
            return None
        if not isinstance(value, str):
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must be a string.")
        return value

    def integer(self, name, required=True, minimum=None, maximum=None):
        value = self.raw(name)
        if value is _BODY_UNSET or value is None:
            if required:
                raise fail("ERR_INVALID_REQUEST", f"Field '{name}' is required.")
            return None
        if not is_int(value):
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must be an integer.")
        if minimum is not None and value < minimum:
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must be at least {minimum}.")
        if maximum is not None and value > maximum:
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must not exceed {maximum}.")
        return value

    def number(self, name, required=True, minimum=None, maximum=None):
        value = self.raw(name)
        if value is _BODY_UNSET or value is None:
            if required:
                raise fail("ERR_INVALID_REQUEST", f"Field '{name}' is required.")
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must be a number.")
        value = float(value)
        if minimum is not None and value < minimum:
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must be at least {minimum}.")
        if maximum is not None and value > maximum:
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must not exceed {maximum}.")
        return value

    def boolean(self, name, required=True):
        value = self.raw(name)
        if value is _BODY_UNSET or value is None:
            if required:
                raise fail("ERR_INVALID_REQUEST", f"Field '{name}' is required.")
            return None
        if not isinstance(value, bool):
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must be a boolean.")
        return value

    def enum(self, name, allowed, required=True):
        value = self.string(name, required=required)
        if value is None:
            return None
        if value not in allowed:
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must be one of {sorted(allowed)}.")
        return value

    def string_list(self, name, required=True, allow_empty=True):
        value = self.raw(name)
        if value is _BODY_UNSET or value is None:
            if required:
                raise fail("ERR_INVALID_REQUEST", f"Field '{name}' is required.")
            return None
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must be an array of strings.")
        if not allow_empty and not value:
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must not be empty.")
        return list(value)

    def blocks(self, name, required=True):
        value = self.raw(name)
        if value is _BODY_UNSET or value is None:
            if required:
                raise fail("ERR_INVALID_REQUEST", f"Field '{name}' is required.")
            return []
        if not isinstance(value, list):
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must be an array.")
        out = []
        for block in value:
            if not isinstance(block, dict):
                raise fail("ERR_INVALID_REQUEST", "Each availability block must be an object.")
            for key in block:
                if key not in ("weekday", "start_minute", "end_minute"):
                    raise fail("ERR_INVALID_REQUEST", f"Unknown field '{key}' in availability block.")
            weekday = block.get("weekday")
            start = block.get("start_minute")
            end = block.get("end_minute")
            if not is_int(weekday) or not 0 <= weekday <= 6:
                raise fail("ERR_INVALID_REQUEST", "availability weekday must be 0-6.")
            if not is_int(start) or not 0 <= start <= 1439:
                raise fail("ERR_INVALID_REQUEST", "start_minute must be 0-1439.")
            if not is_int(end) or not 1 <= end <= 1440:
                raise fail("ERR_INVALID_REQUEST", "end_minute must be 1-1440.")
            out.append({"weekday": weekday, "start_minute": start, "end_minute": end})
        return out

    def instant(self, name, required=True):
        value = self.raw(name)
        if value is _BODY_UNSET or value is None:
            if required:
                raise fail("ERR_INVALID_REQUEST", f"Field '{name}' is required.")
            return None
        parsed = parse_ts(value)
        if parsed is None:
            raise fail("ERR_INVALID_REQUEST", f"Field '{name}' must be an ISO 8601 instant.")
        return parsed

    def version(self, name):
        return self.integer(name, required=True, minimum=1)

    def optional_version(self, name):
        return self.integer(name, required=False, minimum=1)


def query_params():
    return request.args


def qstr(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def qenum(name, allowed):
    value = qstr(name)
    if value is None:
        return None
    if value not in allowed:
        raise fail("ERR_INVALID_REQUEST", f"Query parameter '{name}' must be one of {sorted(allowed)}.")
    return value


def qbool(name):
    value = qstr(name)
    if value is None:
        return None
    if value.lower() in ("true", "1"):
        return True
    if value.lower() in ("false", "0"):
        return False
    raise fail("ERR_INVALID_REQUEST", f"Query parameter '{name}' must be a boolean.")


def clock_stamp():
    return now()