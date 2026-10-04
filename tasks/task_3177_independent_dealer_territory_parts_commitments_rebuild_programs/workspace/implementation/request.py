"""Request parsing: declared shapes, unknown-field detection and type coercion.

Any body that does not parse into the declared shape, carries an undeclared
field, omits a required field or holds a value outside its declared type or
enum is refused with ``ERR_INVALID_REQUEST`` at HTTP 400 — earlier than any
rung of the validation ladder.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from errors import ApiError, E_INVALID_REQUEST

PRODUCT_FAMILIES = ["EXCAVATION", "EARTHMOVING", "COMPACTION", "POWER_SYSTEMS", "LIFT_TRUCK"]

# field name -> declared scalar kind; "?" marks an optional field when it
# appears in an endpoint's input list.
COMMON_FIELDS = {
    "id": "string",
    "created_at": "datetime",
    "updated_at": "datetime",
    "version": "integer",
    "status": "string",
}


class Request:
    """A parsed request: path parameters plus a validated JSON body/query."""

    def __init__(self, method: str, path_params: dict, body: dict, query: dict, headers):
        self.method = method
        self.path_params = path_params
        self.body = body
        self.query = query
        self.headers = headers

    def has(self, name: str) -> bool:
        return name in self.body

    def raw(self, name: str, default=None):
        return self.body.get(name, default)

    # -- typed accessors ---------------------------------------------------
    def string(self, name: str, required: bool = True, default=None) -> str:
        return self._coerce(name, "string", required, default)

    def integer(self, name: str, required: bool = True, default=None):
        return self._coerce(name, "integer", required, default)

    def number(self, name: str, required: bool = True, default=None):
        return self._coerce(name, "number", required, default)

    def boolean(self, name: str, required: bool = True, default=None) -> bool:
        return self._coerce(name, "boolean", required, default)

    def datetime(self, name: str, required: bool = True, default=None) -> datetime:
        return self._coerce(name, "datetime", required, default)

    def enum(self, name: str, members, required: bool = True, default=None) -> str:
        value = self._coerce(name, "string", required, default)
        if value is None:
            return None
        if value not in members:
            raise ApiError(E_INVALID_REQUEST, "field '%s' is not one of %s" % (name, ", ".join(members)))
        return value

    def _coerce(self, name: str, kind: str, required: bool, default):
        if name not in self.body:
            if required:
                raise ApiError(E_INVALID_REQUEST, "required field '%s' is missing" % name)
            return default
        value = self.body[name]
        if value is None:
            if required:
                raise ApiError(E_INVALID_REQUEST, "required field '%s' is null" % name)
            return default
        try:
            if kind == "string":
                if not isinstance(value, str):
                    raise ValueError
                return value
            if kind == "integer":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError
                return int(value)
            if kind == "number":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError
                return float(value)
            if kind == "boolean":
                if not isinstance(value, bool):
                    raise ValueError
                return bool(value)
            if kind == "datetime":
                return parse_iso8601(value)
            if kind == "object":
                if not isinstance(value, dict):
                    raise ValueError
                return value
        except (ValueError, TypeError):
            raise ApiError(E_INVALID_REQUEST, "field '%s' is not of the declared type %s" % (name, kind))
        raise ApiError(E_INVALID_REQUEST, "field '%s' is not of the declared type %s" % (name, kind))


def parse_iso8601(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_body() -> dict:
    """Read and JSON-decode the request body; absent body means an empty object."""
    from flask import request as flask_request

    raw = flask_request.get_data(cache=False, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise ApiError(E_INVALID_REQUEST, "the request body is not well-formed JSON")
    if not isinstance(value, dict):
        raise ApiError(E_INVALID_REQUEST, "the request body must be a JSON object")
    return value


def check_declared(body: dict, declared, optional_marks: bool = True) -> None:
    """Reject unknown fields and missing required fields.

    ``declared`` is the endpoint's own input list; names ending in ``?`` are
    optional, everything else is required.
    """
    allowed = set()
    required = set()
    for entry in declared:
        name = entry
        if optional_marks and name.endswith("?"):
            name = name[:-1]
        else:
            required.add(name)
        allowed.add(name)
    always = _always_allowed()
    for key in body:
        if key not in allowed and key not in always:
            raise ApiError(E_INVALID_REQUEST, "unknown field '%s'" % key)
    for name in required:
        if name in always:
            # §2.5.1: the version preconditions reject only a supplied value;
            # when the field is omitted the check is skipped entirely.
            continue
        if name not in body:
            raise ApiError(E_INVALID_REQUEST, "required field '%s' is missing" % name)


def _always_allowed():
    # The optimistic-concurrency preconditions are declared on the three create
    # endpoints that carry them; they are tolerated everywhere so a caller may
    # supply them without tripping unknown-field detection.
    return {
        "expected_dealer_version",
        "expected_dealeragreement_version",
        "expected_rebuildclaim_version",
    }


# Declared scalar type per field name, used to refuse a value that falls
# outside its declared type before any rung of the validation ladder runs.
FIELD_TYPES = {
    "legal_name": "string",
    "home_state_code": "string",
    "territory_code": "string",
    "dealer_id": "string",
    "agreement_id": "string",
    "commitment_id": "string",
    "order_id": "string",
    "machine_serial": "string",
    "trade_in_serial": "string",
    "technician_name": "string",
    "financing_approval_reference": "string",
    "circumstance_note": "string",
    "remedy_plan": "string",
    "ordered_ref": "string",
    "bundle_support_plan": "string",
    "origin_rebuild_id": "string",
    "credential_code": ("enum", ["DEALER_MASTER", "DEALER_CERTIFIED"]),
    "exclusivity_level": ("enum", ["EXCLUSIVE", "SHARED"]),
    "certified_rebuild_spec_code": ("enum", ["CAT_CERTIFIED_1", "CAT_CERTIFIED_2", "CAT_CERTIFIED_3"]),
    "plan_tier": ("enum", ["BASIC", "PLUS", "PREMIUM"]),
    "restriction_scope": ("enum", ["HOURS_SPENT", "METER_RUNNING", "FULL_STOP"]),
    # ``kind`` is declared twice across the surface: as an observation weight
    # and as a service-order kind.  The union is checked here; the owning
    # handler narrows it to the declared member set.
    "kind": ("enum", ["MACHINE", "LIGHT", "EMERGENCY_FILL", "RESTRICTION", "SLA_AUDIT"]),
    "product_family": ("enum", PRODUCT_FAMILIES),
    "start_at": "datetime",
    "end_at": "datetime",
    "period_start": "datetime",
    "period_end": "datetime",
    "requested_at": "datetime",
    "enrolled_at": "datetime",
    "registered_at": "datetime",
    "recorded_at": "datetime",
    "certified_at": "datetime",
    "core_returned_at": "datetime",
    "to_iso8601": "datetime",
    "performance_plan_share_pct": "number",
    "machine_population_slope": "number",
    "emergency_stocking_target_pct": "number",
    "emergency_fill_window_hours": "number",
    "client_meter_hours": "number",
    "rebuild_labor_hours": "number",
    "meter_hours": "number",
    "sla_hours": "number",
    "trade_in_weight_lb": "integer",
    "trade_in_appraised_value_cents": "integer",
    "remarketed_price_cents": "integer",
    "machine_population_units": "integer",
    "planned_annual_units": "integer",
    "requested_units": "integer",
    "core_units": "integer",
    "machine_operating_weight_lb": "integer",
    "core_purchase_value_cents": "integer",
    "rebuild_labor_rate_cents": "integer",
    "list_price_cents": "integer",
    "observed_machine_units": "integer",
    "territory_machine_units": "integer",
    "credit_settlement_cents": "integer",
    "actual_territory_machine_units": "integer",
    "territory_market_machine_units": "integer",
    "sampled_service_orders": "integer",
    "met_sla_service_orders": "integer",
    "expected_dealer_version": "integer",
    "expected_dealeragreement_version": "integer",
    "expected_rebuildclaim_version": "integer",
    "emergency": "boolean",
    "core_return_required": "boolean",
    "orderable_ref_enabled": "boolean",
}


def validate_types(body: dict) -> None:
    """Refuse any supplied value that falls outside its declared type."""
    for name, value in body.items():
        if value is None:
            continue
        declared = FIELD_TYPES.get(name)
        if declared is None:
            continue
        if isinstance(declared, tuple) and declared[0] == "enum":
            members = declared[1]
            if not isinstance(value, str) or value not in members:
                raise ApiError(E_INVALID_REQUEST, "field '%s' is not one of %s" % (name, ", ".join(members)))
            continue
        try:
            if declared == "string":
                if not isinstance(value, str):
                    raise ValueError
            elif declared == "integer":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError
            elif declared == "number":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError
            elif declared == "boolean":
                if not isinstance(value, bool):
                    raise ValueError
            elif declared == "datetime":
                parse_iso8601(value)
        except (ValueError, TypeError):
            raise ApiError(E_INVALID_REQUEST, "field '%s' is not of the declared type %s" % (name, declared))