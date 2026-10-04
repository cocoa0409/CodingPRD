"""Request body / query-parameter validation.

Errors surface as ERR_INVALID_REQUEST (400), the single code the PRD assigns to
a missing required body field, an enum value outside its declared set, and an
integer outside its declared range (PRD §2.4, §2.12).
"""

import json

from flask import request

from errors import ERR_INVALID_REQUEST, fail

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Declared enum sets (PRD §2.4, §3.2 - §3.8).
ENVIRONMENT_TYPES = ("PRODUCTION", "FULL_COPY", "PARTIAL", "DEVELOPER")
RELEASE_SCHEDULE_MODES = ("MANUAL_FIXED", "FLAG_ONLY")
PARTITIONS = ("FULL", "ACCOUNT_PARTIAL")
PRINCIPAL_TYPES = ("PROFILE", "PERMISSION_SET")
LEDGER_KINDS = ("DATA", "FILE")
LEDGER_STATUSES = ("LIVE", "ARCHIVED")
AUDIT_FINDINGS = ("REVOKE", "RETAIN")


class Body:
    """Thin wrapper over the parsed JSON body of the current request."""

    def __init__(self, raw=None):
        if raw is None:
            raw = request.get_json(silent=True)
            if raw is None:
                # Tolerate a body that was not sent with a JSON content type.
                raw = _raw_json()
        self.raw = raw if isinstance(raw, dict) else {}

    def has(self, key):
        return key in self.raw and self.raw[key] is not None

    def value(self, key):
        return self.raw.get(key)


def _raw_json():
    try:
        raw = request.get_data(as_text=True)
    except Exception:
        return None
    if not raw or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def invalid(message):
    fail(ERR_INVALID_REQUEST, message)


def body():
    return Body()


def require_string(b, key, allow_empty=False):
    if not b.has(key):
        invalid("Field '%s' is required." % key)
    value = b.value(key)
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        invalid("Field '%s' must be non-empty." % key)
    return value


def optional_string(b, key, default=None, allow_empty=True):
    if not b.has(key):
        return default
    value = b.value(key)
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        invalid("Field '%s' must be non-empty." % key)
    return value


def require_enum(b, key, allowed):
    value = require_string(b, key)
    if value not in allowed:
        invalid("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def optional_enum(b, key, allowed, default=None):
    if not b.has(key):
        return default
    value = b.value(key)
    if value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        invalid("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def require_int(b, key, min_value=None, max_value=None):
    if not b.has(key):
        invalid("Field '%s' is required." % key)
    return _check_int(b.value(key), key, min_value, max_value)


def optional_int(b, key, min_value=None, max_value=None, default=None):
    if not b.has(key):
        return default
    value = b.value(key)
    if value is None:
        return default
    return _check_int(value, key, min_value, max_value)


def _check_int(value, key, min_value, max_value):
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field '%s' must be an integer." % key)
    if min_value is not None and value < min_value:
        invalid("Field '%s' must be at least %d." % (key, min_value))
    if max_value is not None and value > max_value:
        invalid("Field '%s' must be at most %d." % (key, max_value))
    return value


def optional_list(b, key, default=None):
    if not b.has(key):
        return list(default) if default else []
    value = b.value(key)
    if value is None:
        return list(default) if default else []
    if not isinstance(value, list):
        invalid("Field '%s' must be an array." % key)
    return value


def parse_component_list(raw):
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            invalid("Each component_list entry must be an object.")
        name = item.get("component")
        if not isinstance(name, str) or name.strip() == "":
            invalid("Each component_list entry requires a non-empty 'component'.")
        tag = item.get("version_tag")
        if isinstance(tag, bool) or not isinstance(tag, int):
            invalid("Each component_list entry requires an integer 'version_tag'.")
        entries.append({"component": name, "version_tag": tag})
    return entries


def parse_component_dependencies(raw):
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            invalid("Each component_dependencies entry must be an object.")
        name = item.get("component")
        if not isinstance(name, str) or name.strip() == "":
            invalid("Each component_dependencies entry requires a non-empty 'component'.")
        requires = item.get("requires", [])
        if requires is None:
            requires = []
        if not isinstance(requires, list) or any(not isinstance(r, str) for r in requires):
            invalid("The 'requires' list of a dependency entry must be an array of strings.")
        min_version = item.get("min_version", 0)
        if isinstance(min_version, bool) or not isinstance(min_version, int):
            invalid("A dependency entry's 'min_version' must be an integer.")
        entries.append(
            {"component": name, "requires": list(requires), "min_version": min_version}
        )
    return entries


def parse_callout_graph(raw):
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            invalid("Each callout_graph entry must be an object.")
        node = item.get("node")
        if not isinstance(node, str) or node.strip() == "":
            invalid("Each callout_graph entry requires a non-empty 'node'.")
        calls = item.get("calls", [])
        if calls is None:
            calls = []
        if not isinstance(calls, list) or any(not isinstance(c, str) for c in calls):
            invalid("The 'calls' list of a callout_graph entry must be an array of strings.")
        entries.append({"node": node, "calls": list(calls)})
    return entries


def component_digests_of(component_list):
    return {entry["component"]: entry["version_tag"] for entry in component_list}


def pagination_args():
    """Read limit/offset, defaulting and clamping per PRD §2.3."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = DEFAULT_LIMIT if limit_raw is None else int(limit_raw)
    except (TypeError, ValueError):
        invalid("Query parameter 'limit' must be an integer.")
    try:
        offset = DEFAULT_OFFSET if offset_raw is None else int(offset_raw)
    except (TypeError, ValueError):
        invalid("Query parameter 'offset' must be an integer.")
    limit = max(MIN_LIMIT, min(MAX_LIMIT, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset: offset + limit], total