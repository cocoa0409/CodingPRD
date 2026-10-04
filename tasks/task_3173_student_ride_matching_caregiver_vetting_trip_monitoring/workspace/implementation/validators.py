"""Body parsing / enum / field validation helpers.

An unrecognised enum member, an unknown field, a missing required field or a
malformed body is ERR_INVALID_REQUEST (HTTP 400) per SCAFFOLD section 1.6.
"""

from decimal import Decimal, InvalidOperation

from errors import ERR_INVALID_REQUEST, ApiError
from flask import request

ENUMS = {
    "program_type": ["FOSTER_CARE", "HOMELESS_MCKINNEY_VENTO", "SPECIAL_EDUCATION", "GENERAL"],
    "vehicle_class": ["SEDAN", "SUV", "WHEELCHAIR_VAN"],
    "child_seat_type": ["NONE", "BOOSTER", "HARNESS", "INTEGRATED"],
    "check_type": ["FINGERPRINT_FBI", "FINGERPRINT_STATE", "COUNTY_COURT", "SEX_OFFENDER_REGISTRY"],
    "billing_period": ["WEEKLY", "SEMI_MONTHLY", "MONTHLY"],
    "trip_type": ["AM_SCHOOL", "PM_SCHOOL", "MIDDAY", "ACTIVITY"],
    "required_specialty": ["NONE", "CAREGIVER_REQUIRED", "WHEELCHAIR"],
    "leg": ["PICKUP", "DROPOFF"],
    "expected_party": ["SCHOOL_STAFF", "AUTHORIZED_ADULT", "PLACEMENT_WORKER"],
    "verification_method": ["PHOTO_ID", "PIN", "PHYSICAL_SIGNATURE"],
    "category": [
        "NO_SHOW_UNVERIFIED",
        "DRIVER_MISCONDUCT",
        "VEHICLE_UNSAFE",
        "HANDOFF_DISPUTE",
        "STUDENT_DISTRESS",
    ],
    "severity": ["LOW", "MEDIUM", "HIGH"],
}


def body(payload=None):
    """Parse the JSON request body; a malformed body is ERR_INVALID_REQUEST."""
    if payload is not None:
        return payload
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise ApiError(ERR_INVALID_REQUEST, "The request body is not valid JSON.")
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "The request body must be a JSON object.")
    return data


def reject_unknown(data, allowed):
    for key in data:
        if key not in allowed:
            raise ApiError(ERR_INVALID_REQUEST, f"Unknown field: {key}.")


def enum_value(field, value, allow_none_constraint=False):
    allowed = ENUMS[field]
    if value is None and allow_none_constraint:
        return None
    if value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"{field} must be one of {', '.join(allowed)}.",
        )
    return value


def required(data, field):
    if field not in data or data[field] is None or data[field] == "":
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is required.")
    return data[field]


def as_string(data, field, required_field=True, default=None):
    if field not in data or data[field] is None:
        if required_field:
            raise ApiError(ERR_INVALID_REQUEST, f"{field} is required.")
        return default
    value = data[field]
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a string.")
    if value == "" and required_field:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is required.")
    return value


def as_int(data, field, default=None, minimum=None, maximum=None, required_field=False):
    if field not in data or data[field] is None:
        if required_field:
            raise ApiError(ERR_INVALID_REQUEST, f"{field} is required.")
        return default
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        else:
            raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an integer.")
    if minimum is not None and value < minimum:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be at most {maximum}.")
    return value


def as_number(data, field, default=None, required_field=False):
    if field not in data or data[field] is None:
        if required_field:
            raise ApiError(ERR_INVALID_REQUEST, f"{field} is required.")
        return default
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a number.")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a number.")


def as_bool(data, field, default=None, required_field=False):
    if field not in data or data[field] is None:
        if required_field:
            raise ApiError(ERR_INVALID_REQUEST, f"{field} is required.")
        return default
    value = data[field]
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a boolean.")
    return value


def as_array(data, field, default=None, required_field=False):
    if field not in data or data[field] is None:
        if required_field:
            raise ApiError(ERR_INVALID_REQUEST, f"{field} is required.")
        return default
    value = data[field]
    if not isinstance(value, list):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an array.")
    return value


def as_iso_dt(data, field, required_field=True, default=None):
    from clock import parse_dt

    if field not in data or data[field] is None:
        if required_field:
            raise ApiError(ERR_INVALID_REQUEST, f"{field} is required.")
        return default
    try:
        return parse_dt(data[field])
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 timestamp.")


def as_iso_date(data, field, required_field=True, default=None):
    from clock import parse_date

    if field not in data or data[field] is None:
        if required_field:
            raise ApiError(ERR_INVALID_REQUEST, f"{field} is required.")
        return default
    try:
        return parse_date(data[field])
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 date (YYYY-MM-DD).")


def as_iso_date_string(data, field, required_field=True, default=None):
    value = as_iso_date(data, field, required_field=required_field, default=None)
    if value is None:
        return default
    return value.strftime("%Y-%m-%d")