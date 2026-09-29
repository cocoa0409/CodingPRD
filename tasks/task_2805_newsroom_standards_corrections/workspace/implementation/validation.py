"""Request-body parsing and shape validation.

The precedence ladder in PRD 2.12 puts request-body identifier resolution
(step 7) BEFORE body shape validation (step 8), so parsing is split into
three phases: raw parse, id resolution, then full shape validation.
"""

import json

from flask import request

from errors import ApiError
from store import parse_iso

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

ROLE_TITLES = ["REPORTER", "STANDARDS_EDITOR", "EXECUTIVE_EDITOR"]
DISCIPLINES = ["LEGAL", "STANDARDS"]
MODULE_CODES = ["SOURCING", "CORRECTIONS", "LEGAL_RISK", "ANONYMOUS_SOURCING", "PLAGIARISM"]
SOURCE_CATEGORIES = ["GOVERNMENT", "CORPORATE", "VICTIM", "WHISTLEBLOWER", "LAW_ENFORCEMENT"]
HARM_RISKS = ["LOW", "ELEVATED", "SEVERE"]
VERDICTS = ["PASS", "CHANGES_REQUIRED", "BLOCK"]
SUBMITTER_TYPES = ["READER", "SUBJECT", "INTERNAL"]
ERROR_CATEGORIES = ["FACTUAL", "QUOTE", "NUMERIC", "IDENTIFICATION", "CONTEXT"]
OUTCOME_TYPES = ["CORRECTION", "CLARIFICATION", "UPDATE", "EDITORS_NOTE", "NO_ACTION"]
ALLEGATION_TYPES = ["PLAGIARISM", "FABRICATION", "UNDISCLOSED_COI"]
SEVERITIES = ["MINOR", "SERIOUS", "EGREGIOUS"]
DISPOSITIONS = ["SUSTAINED", "UNFOUNDED"]
APPEAL_OUTCOMES = ["UPHELD", "OVERTURNED"]
DISCLOSURE_TYPES = ["FINANCIAL", "FAMILIAL", "POLITICAL", "EMPLOYMENT"]
REVIEW_OUTCOMES = ["ACKNOWLEDGE", "IMPOSE_RESTRICTION", "REJECT"]
ACTIVITY_TYPES = ["SPEAKING", "BOOK", "CONSULTING", "BOARD_SERVICE"]
DECISIONS = ["APPROVE", "DENY"]

# ---------------------------------------------------------------------------
# Field descriptors
# ---------------------------------------------------------------------------


def s(required=False, min_len=1, max_len=None, default=None, contains=None):
    return {"kind": "string", "required": required, "min_len": min_len,
            "max_len": max_len, "default": default, "contains": contains}


def i(required=False, minimum=None, maximum=None, default=None):
    return {"kind": "int", "required": required, "min": minimum, "max": maximum,
            "default": default}


def b(required=False, default=None):
    return {"kind": "bool", "required": required, "default": default}


def e(choices, required=False, default=None):
    return {"kind": "enum", "choices": choices, "required": required, "default": default}


def dt(required=False):
    return {"kind": "datetime", "required": required, "default": None}


def enum_array(choices, required=False, default=None, distinct=True, non_empty=True):
    return {"kind": "enum_array", "choices": choices, "required": required,
            "default": default, "distinct": distinct, "non_empty": non_empty}


def str_array(required=False, default=None, non_empty=False):
    return {"kind": "str_array", "required": required, "default": default,
            "non_empty": non_empty}


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def read_raw_body():
    """Parse the JSON body into a dict.  Absent/empty body is an empty dict."""
    data = request.get_data(cache=True)
    if data is None or len(data.strip()) == 0:
        return {}
    try:
        parsed = json.loads(data.decode("utf-8"))
    except Exception:
        _bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        _bad("Request body must be a JSON object.")
    return parsed


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validate_body(raw, spec):
    """Full body shape validation (PRD 2.12 step 8)."""
    for key in raw.keys():
        if key not in spec:
            _bad("Unknown field '%s'." % key)

    out = {}
    for name, rule in spec.items():
        present = name in raw
        value = raw.get(name)
        if not present or value is None:
            if rule.get("required"):
                _bad("Field '%s' is required." % name)
            default = rule.get("default")
            out[name] = list(default) if isinstance(default, list) else default
            continue

        kind = rule["kind"]
        if kind == "string":
            if not isinstance(value, str):
                _bad("Field '%s' must be a string." % name)
            if rule.get("min_len") is not None and len(value) < rule["min_len"]:
                _bad("Field '%s' is shorter than its minimum length." % name)
            if rule.get("max_len") is not None and len(value) > rule["max_len"]:
                _bad("Field '%s' is longer than its maximum length." % name)
            if rule.get("contains") and rule["contains"] not in value:
                _bad("Field '%s' must contain '%s'." % (name, rule["contains"]))
            out[name] = value
        elif kind == "int":
            if not _is_int(value):
                _bad("Field '%s' must be an integer." % name)
            if rule.get("min") is not None and value < rule["min"]:
                _bad("Field '%s' is below its minimum." % name)
            if rule.get("max") is not None and value > rule["max"]:
                _bad("Field '%s' is above its maximum." % name)
            out[name] = value
        elif kind == "bool":
            if not isinstance(value, bool):
                _bad("Field '%s' must be a boolean." % name)
            out[name] = value
        elif kind == "enum":
            if not isinstance(value, str) or value not in rule["choices"]:
                _bad("Field '%s' is not a recognized value." % name)
            out[name] = value
        elif kind == "datetime":
            if not isinstance(value, str):
                _bad("Field '%s' must be an ISO 8601 string." % name)
            parsed = parse_iso(value)
            if parsed is None:
                _bad("Field '%s' is not a parseable ISO 8601 instant." % name)
            out[name] = parsed
        elif kind == "enum_array":
            if not isinstance(value, list):
                _bad("Field '%s' must be an array." % name)
            if rule.get("non_empty") and len(value) == 0:
                _bad("Field '%s' must be a non-empty array." % name)
            for member in value:
                if not isinstance(member, str) or member not in rule["choices"]:
                    _bad("Field '%s' contains an unrecognized member." % name)
            if rule.get("distinct") and len(set(value)) != len(value):
                _bad("Field '%s' contains repeated members." % name)
            out[name] = list(value)
        elif kind == "str_array":
            if not isinstance(value, list):
                _bad("Field '%s' must be an array." % name)
            if rule.get("non_empty") and len(value) == 0:
                _bad("Field '%s' must be a non-empty array." % name)
            for member in value:
                if not isinstance(member, str) or len(member) == 0:
                    _bad("Field '%s' must contain non-empty strings." % name)
            out[name] = list(value)
        else:  # pragma: no cover
            _bad("Field '%s' cannot be validated." % name)
    return out


# ---------------------------------------------------------------------------
# Body identifier resolution (PRD 2.12 step 7)
# ---------------------------------------------------------------------------

# Fixed evaluation order, matching SCAFFOLD 1.4 priority 7.
BODY_ID_ORDER = [
    ("newsroom_id", "newsrooms", "ERR_NEWSROOM_NOT_FOUND"),
    ("lead_journalist_id", "journalists", "ERR_JOURNALIST_NOT_FOUND"),
    ("journalist_id", "journalists", "ERR_JOURNALIST_NOT_FOUND"),
    ("story_id", "stories", "ERR_STORY_NOT_FOUND"),
    ("review_id", "reviews", "ERR_REVIEW_NOT_FOUND"),
    ("reviewer_id", "reviewers", "ERR_REVIEWER_NOT_FOUND"),
]


def resolve_body_ids(raw, keys):
    """Resolve every id named in `keys` that is actually present as a string.

    Missing or wrongly typed ids are left to the shape validator (step 8).
    """
    from store import db
    resolved = {}
    for field, collection, error_id in BODY_ID_ORDER:
        if field not in keys:
            continue
        value = raw.get(field)
        if value is None or not isinstance(value, str):
            continue
        record = getattr(db, collection).get(value)
        if record is None:
            raise ApiError(error_id, "%s '%s' does not resolve." % (field, value))
        resolved[field] = record
    return resolved
