"""Request-shape validation (PRD 2.4 / precedence step 5). Every failure raises
ERR_INVALID_REQUEST with HTTP 400."""

from decimal import Decimal, InvalidOperation

from flask import request

from common import dec, firmware_well_formed, normalize_iso, parse_iso
from errors import invalid


def body():
    """The request's JSON object, or an empty object when no body was sent."""
    data = request.get_json(silent=True)
    if data is None:
        return Payload({})
    if not isinstance(data, dict):
        raise invalid("Request body must be a JSON object.")
    return Payload(data)


class Payload(object):
    def __init__(self, data):
        self.data = data

    # -- presence ---------------------------------------------------------- #

    def has(self, key):
        return key in self.data and self.data[key] is not None

    def present(self, key):
        return key in self.data

    def raw(self, key, default=None):
        value = self.data.get(key, default)
        return default if value is None else value

    def _required(self, key):
        if key not in self.data or self.data[key] is None:
            raise invalid("Field '%s' is required." % key)
        return self.data[key]

    # -- strings ----------------------------------------------------------- #

    def str_(self, key, required=True, default=None, max_len=None, allow_empty=False):
        if not self.has(key):
            if required:
                self._required(key)
            return default
        value = self.data[key]
        if not isinstance(value, str):
            raise invalid("Field '%s' must be a string." % key)
        if not allow_empty and value.strip() == "":
            raise invalid("Field '%s' must be a non-empty string." % key)
        if max_len is not None and len(value) > max_len:
            raise invalid("Field '%s' must be at most %d characters." % (key, max_len))
        return value

    def enum(self, key, values, required=True, default=None):
        if not self.has(key):
            if required:
                self._required(key)
            return default
        value = self.data[key]
        if not isinstance(value, str) or value not in values:
            raise invalid("Field '%s' must be one of %s." % (key, ", ".join(values)))
        return value

    def firmware(self, key, required=True, default=None):
        if not self.has(key):
            if required:
                self._required(key)
            return default
        value = self.data[key]
        if not firmware_well_formed(value):
            raise invalid("Field '%s' must be three dot-separated integers." % key)
        return value.strip()

    def iso(self, key, required=True, default=None):
        if not self.has(key):
            if required:
                self._required(key)
            return default
        value = self.data[key]
        if not isinstance(value, str) or parse_iso(value) is None:
            raise invalid("Field '%s' must be an ISO 8601 UTC instant." % key)
        return normalize_iso(value)

    # -- numbers ----------------------------------------------------------- #

    def _number(self, key):
        value = self.data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise invalid("Field '%s' must be a number." % key)
        try:
            return dec(value)
        except (InvalidOperation, ValueError):
            raise invalid("Field '%s' must be a number." % key)

    def number(
        self,
        key,
        required=True,
        default=None,
        minimum=Decimal(0),
        exclusive_min=False,
        maximum=None,
    ):
        if not self.has(key):
            if required:
                self._required(key)
            return default
        value = self._number(key)
        if minimum is not None:
            if exclusive_min and value <= minimum:
                raise invalid("Field '%s' must be greater than %s." % (key, minimum))
            if not exclusive_min and value < minimum:
                raise invalid("Field '%s' must not be less than %s." % (key, minimum))
        if maximum is not None and value > maximum:
            raise invalid("Field '%s' must not be greater than %s." % (key, maximum))
        return value

    def integer(
        self,
        key,
        required=True,
        default=None,
        minimum=0,
        exclusive_min=False,
        maximum=None,
        choices=None,
    ):
        if not self.has(key):
            if required:
                self._required(key)
            return default
        value = self.data[key]
        if isinstance(value, bool) or not isinstance(value, int):
            if isinstance(value, float) and float(value).is_integer():
                value = int(value)
            else:
                raise invalid("Field '%s' must be an integer." % key)
        if choices is not None and value not in choices:
            raise invalid(
                "Field '%s' must be one of %s."
                % (key, ", ".join(str(choice) for choice in choices))
            )
        if minimum is not None:
            if exclusive_min and value <= minimum:
                raise invalid("Field '%s' must be greater than %d." % (key, minimum))
            if not exclusive_min and value < minimum:
                raise invalid("Field '%s' must not be less than %d." % (key, minimum))
        if maximum is not None and value > maximum:
            raise invalid("Field '%s' must not be greater than %d." % (key, maximum))
        return value

    def boolean(self, key, required=True, default=None):
        if not self.has(key):
            if required:
                self._required(key)
            return default
        value = self.data[key]
        if not isinstance(value, bool):
            raise invalid("Field '%s' must be a boolean." % key)
        return value

    # -- lists ------------------------------------------------------------- #

    def list_(self, key, required=True, default=None):
        if not self.has(key):
            if required:
                self._required(key)
            return default
        value = self.data[key]
        if not isinstance(value, list):
            raise invalid("Field '%s' must be an array." % key)
        return value

    def str_list(self, key, required=True, default=None, values=None):
        items = self.list_(key, required=required, default=None)
        if items is None:
            return default
        out = []
        for item in items:
            if not isinstance(item, str) or item.strip() == "":
                raise invalid("Field '%s' must be an array of non-empty strings." % key)
            if values is not None and item not in values:
                raise invalid(
                    "Field '%s' may only contain %s." % (key, ", ".join(values))
                )
            out.append(item)
        return out

    def fk(self, key, required=True):
        """A foreign-key string. Missing/blank is a shape problem, not a 404."""
        if not self.has(key):
            if required:
                self._required(key)
            return None
        value = self.data[key]
        if not isinstance(value, str) or value.strip() == "":
            raise invalid("Field '%s' must be a resource id string." % key)
        return value


def circuits(payload, key="essential_circuits", required=False):
    """Validate the ordered essential-circuit list."""
    items = payload.list_(key, required=required, default=None)
    if items is None:
        return None
    out = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise invalid("Each essential circuit must be an object.")
        label = item.get("label")
        if not isinstance(label, str) or label.strip() == "":
            raise invalid("Essential circuit %d requires a non-empty 'label'." % index)
        load = item.get("load_kw")
        if isinstance(load, bool) or not isinstance(load, (int, float)):
            raise invalid("Essential circuit %d requires a numeric 'load_kw'." % index)
        if dec(load) < 0:
            raise invalid("Essential circuit %d has a negative 'load_kw'." % index)
        has_motor = item.get("has_motor")
        if has_motor is None:
            has_motor = False
        if not isinstance(has_motor, bool):
            raise invalid("Essential circuit %d requires a boolean 'has_motor'." % index)
        out.append({"label": label, "load_kw": dec(load), "has_motor": has_motor})
    return out


def window(payload):
    """A half-open [window_start, window_end) pair, end strictly after start."""
    start = payload.iso("window_start")
    end = payload.iso("window_end")
    if parse_iso(end) <= parse_iso(start):
        raise invalid("'window_end' must be strictly after 'window_start'.")
    return start, end
