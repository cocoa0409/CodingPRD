"""Request-shape validation (the ERR_INVALID_REQUEST rung).

Every field is checked for presence, JSON type, enum domain and length or
range before any existence, ownership, concurrency or business rule is
considered.
"""
from flask import request

from db import parse_instant
from errors import invalid


def body():
    """Parse the JSON body; an absent body behaves as an empty object."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return Body({})
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        invalid("Request body is not valid JSON.")
    if data is None:
        return Body({})
    if not isinstance(data, dict):
        invalid("Request body must be a JSON object.")
    return Body(data)


class Body(object):
    def __init__(self, data):
        self.data = data

    def raw(self, key):
        return self.data.get(key)

    def present(self, key):
        return key in self.data and self.data[key] is not None

    def supplied(self, key):
        return key in self.data

    # ------------------------------------------------------------------ core
    def _fetch(self, key, required, default):
        if key not in self.data or self.data[key] is None:
            if required:
                invalid("%s is required." % key)
            return (False, default)
        return (True, self.data[key])

    def string(
        self,
        key,
        required=True,
        default=None,
        min_len=None,
        max_len=None,
        choices=None,
        contains=None,
    ):
        found, value = self._fetch(key, required, default)
        if not found:
            return value
        if not isinstance(value, str):
            invalid("%s must be a string." % key)
        if min_len is not None and len(value) < min_len:
            invalid("%s must be at least %d characters long." % (key, min_len))
        if max_len is not None and len(value) > max_len:
            invalid("%s must be at most %d characters long." % (key, max_len))
        if choices is not None and value not in choices:
            invalid("%s must be one of %s." % (key, ", ".join(choices)))
        if contains is not None and contains not in value:
            invalid("%s must contain %r." % (key, contains))
        return value

    def integer(self, key, required=True, default=None, minimum=None, maximum=None):
        found, value = self._fetch(key, required, default)
        if not found:
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            invalid("%s must be an integer." % key)
        if minimum is not None and value < minimum:
            invalid("%s must be >= %d." % (key, minimum))
        if maximum is not None and value > maximum:
            invalid("%s must be <= %d." % (key, maximum))
        return value

    def boolean(self, key, required=True, default=None):
        found, value = self._fetch(key, required, default)
        if not found:
            return value
        if not isinstance(value, bool):
            invalid("%s must be a boolean." % key)
        return value

    def instant(self, key, required=True, default=None):
        found, value = self._fetch(key, required, default)
        if not found:
            return value
        if not isinstance(value, str):
            invalid("%s must be an ISO 8601 UTC timestamp string." % key)
        parsed = parse_instant(value)
        if parsed is None:
            invalid("%s must be a valid ISO 8601 UTC timestamp." % key)
        return parsed

    def string_array(
        self,
        key,
        required=True,
        default=None,
        min_items=None,
        max_items=None,
        unique=False,
        item_min_len=None,
        item_max_len=None,
    ):
        found, value = self._fetch(key, required, default)
        if not found:
            return value
        if not isinstance(value, list):
            invalid("%s must be an array." % key)
        for item in value:
            if not isinstance(item, str):
                invalid("%s must contain only strings." % key)
            if item_min_len is not None and len(item) < item_min_len:
                invalid("%s entries must be at least %d characters." % (key, item_min_len))
            if item_max_len is not None and len(item) > item_max_len:
                invalid("%s entries must be at most %d characters." % (key, item_max_len))
        if min_items is not None and len(value) < min_items:
            invalid("%s must contain at least %d entries." % (key, min_items))
        if max_items is not None and len(value) > max_items:
            invalid("%s must contain at most %d entries." % (key, max_items))
        if unique and len(set(value)) != len(value):
            invalid("%s entries must be unique." % key)
        return value

    def object_array(
        self, key, required=True, default=None, min_items=None, max_items=None
    ):
        found, value = self._fetch(key, required, default)
        if not found:
            return value
        if not isinstance(value, list):
            invalid("%s must be an array." % key)
        for item in value:
            if not isinstance(item, dict):
                invalid("%s must contain only objects." % key)
        if min_items is not None and len(value) < min_items:
            invalid("%s must contain at least %d entries." % (key, min_items))
        if max_items is not None and len(value) > max_items:
            invalid("%s must contain at most %d entries." % (key, max_items))
        return value
