"""Domain assertions for the dispensing API.

These wrap the framework validators with the shapes the contract pins: the
response envelope, the common identity fields, the two encounter dimensions,
the shelf posture, the clinic posture and the money fields.
"""

import re
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant
from .api_errors import ERROR_HTTP_STATUS
from .constants import (
    REQUEST_ID_PREFIX,
    RESPONSE_TYPE_ARRAY,
    RESPONSE_TYPE_ERROR,
    RESPONSE_TYPE_OBJECT,
)

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def assert_envelope(response, expected_response_type: str) -> Dict[str, Any]:
    """Check the three top-level envelope keys and the request metadata."""
    body = response.json()
    assert "meta" in body, "response is missing the meta block: {}".format(body)
    assert "response_type" in body, "response is missing response_type: {}".format(body)
    assert "data" in body, "response is missing data: {}".format(body)
    assert body["response_type"] == expected_response_type, (
        "expected response_type {} but got {}".format(expected_response_type, body["response_type"])
    )
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str), "api_request_id must be a string"
    assert meta["api_request_id"].startswith(REQUEST_ID_PREFIX), (
        "api_request_id must start with {}: {}".format(REQUEST_ID_PREFIX, meta["api_request_id"])
    )
    assert_instant(meta.get("api_request_timestamp"), "meta.api_request_timestamp")
    return body


def assert_object_envelope(response) -> Dict[str, Any]:
    return assert_envelope(response, RESPONSE_TYPE_OBJECT)


def assert_array_envelope(response) -> Dict[str, Any]:
    return assert_envelope(response, RESPONSE_TYPE_ARRAY)


def assert_error_envelope(response) -> Dict[str, Any]:
    body = assert_envelope(response, RESPONSE_TYPE_ERROR)
    data = body["data"]
    assert "error_id" in data, "error payload is missing error_id: {}".format(data)
    assert isinstance(data.get("message"), str) and data["message"], (
        "error payload must carry a non-empty message: {}".format(data)
    )
    return body


def assert_list_meta(
    response,
    expected_total: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
):
    """Check a paginated read's rows and its pagination metadata."""
    rows, meta = validate_paginated(response)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            "expected total_count {} but got {}".format(expected_total, meta["total_count"])
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            "expected has_more {} but got {}".format(expected_has_more, meta["has_more"])
        )
    return rows, meta


# ---------------------------------------------------------------------------
# Identity and time
# ---------------------------------------------------------------------------
def assert_instant(value: Any, label: str = "instant") -> None:
    assert isinstance(value, str), "{} must be a string, got {!r}".format(label, value)
    assert _TS_RE.match(value), (
        "{} must be an ISO-8601 UTC instant with exactly three fractional digits, got {!r}".format(
            label, value
        )
    )


def assert_calendar_date(value: Any, label: str = "date") -> None:
    assert isinstance(value, str) and _DATE_RE.match(value), (
        "{} must be a plain calendar date, got {!r}".format(label, value)
    )


def assert_identity_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every entity but the coverage verification carries all four fields."""
    assert is_valid_uuid(entity.get("id")), "id must be a UUID, got {!r}".format(entity.get("id"))
    assert_instant(entity.get("created_at"), "created_at")
    assert_instant(entity.get("updated_at"), "updated_at")
    assert isinstance(entity.get("version"), int), "version must be an integer"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            "expected version {} but got {}".format(expected_version, entity["version"])
        )


def assert_append_only_identity(entity: Dict[str, Any]) -> None:
    """The coverage verification carries only `id` and `created_at`."""
    assert is_valid_uuid(entity.get("id")), "id must be a UUID"
    assert_instant(entity.get("created_at"), "created_at")
    assert "version" not in entity, "an append-only record must not carry a version"
    assert "updated_at" not in entity, "an append-only record must not carry updated_at"


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    assert canonical_instant(actual) == canonical_instant(expected), (
        "expected {} to be {} but got {}".format(label, expected, actual)
    )


def assert_version_is(entity: Dict[str, Any], expected: int, label: str = "entity") -> None:
    assert entity.get("version") == expected, (
        "expected {} version {} but got {}".format(label, expected, entity.get("version"))
    )


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
def error_id_of(response) -> Any:
    """The identifier an error response reports, read out of the envelope's data."""
    return response.json().get("data", {}).get("error_id")


def assert_error(response, expected_error_id: str, expected_status: Optional[int] = None):
    """Assert the identifier and the status the contract pins to it."""
    status = expected_status or ERROR_HTTP_STATUS[expected_error_id]
    data = validate_error(response, expected_error_id, status)
    assert_error_envelope(response)
    return data


# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------
def assert_encounter_states(
    encounter: Dict[str, Any],
    clinical_status: Optional[str] = None,
    financial_status: Optional[str] = None,
) -> None:
    """The two dimensions advance independently, so each is checked on its own."""
    if clinical_status is not None:
        assert encounter.get("clinical_status") == clinical_status, (
            "expected clinical_status {} but got {}".format(
                clinical_status, encounter.get("clinical_status")
            )
        )
    if financial_status is not None:
        assert encounter.get("financial_status") == financial_status, (
            "expected financial_status {} but got {}".format(
                financial_status, encounter.get("financial_status")
            )
        )


def assert_compliance_hold(
    encounter: Dict[str, Any], held: bool, reason: Optional[str] = None
) -> None:
    assert encounter.get("compliance_hold") is held, (
        "expected compliance_hold {} but got {}".format(held, encounter.get("compliance_hold"))
    )
    assert encounter.get("hold_reason") == reason, (
        "expected hold_reason {!r} but got {!r}".format(reason, encounter.get("hold_reason"))
    )


def assert_money(entity: Dict[str, Any], field: str, expected: int) -> None:
    value = entity.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        "{} must be an integer count of cents, got {!r}".format(field, value)
    )
    assert value == expected, "expected {} to be {} cents but got {}".format(field, expected, value)


def assert_money_fields(entity: Dict[str, Any], **expected: int) -> None:
    for field, amount in expected.items():
        assert_money(entity, field, amount)


def assert_responsibility(
    encounter: Dict[str, Any],
    patient_responsibility_cents: Optional[int] = None,
    billable_amount_cents: Optional[int] = None,
    responsibility_variant: Optional[str] = None,
) -> None:
    if patient_responsibility_cents is not None:
        assert_money(encounter, "patient_responsibility_cents", patient_responsibility_cents)
    if billable_amount_cents is not None:
        assert_money(encounter, "billable_amount_cents", billable_amount_cents)
    if responsibility_variant is not None:
        assert encounter.get("responsibility_variant") == responsibility_variant, (
            "expected responsibility_variant {} but got {}".format(
                responsibility_variant, encounter.get("responsibility_variant")
            )
        )


# ---------------------------------------------------------------------------
# Shelves and clinics
# ---------------------------------------------------------------------------
def assert_shelf(
    shelf: Dict[str, Any],
    on_hand_qty: Optional[int] = None,
    reserved_qty: Optional[int] = None,
    available_qty: Optional[int] = None,
    stock_posture: Optional[str] = None,
    lifetime_received_qty: Optional[int] = None,
    version: Optional[int] = None,
) -> None:
    checks = {
        "on_hand_qty": on_hand_qty,
        "reserved_qty": reserved_qty,
        "available_qty": available_qty,
        "stock_posture": stock_posture,
        "lifetime_received_qty": lifetime_received_qty,
        "version": version,
    }
    for field, expected in checks.items():
        if expected is None:
            continue
        assert shelf.get(field) == expected, (
            "expected shelf {} to be {} but got {}".format(field, expected, shelf.get(field))
        )


def assert_clinic_posture(
    clinic: Dict[str, Any],
    dispensing_status: Optional[str] = None,
    stockout_par_level_count: Optional[int] = None,
) -> None:
    if dispensing_status is not None:
        assert clinic.get("dispensing_status") == dispensing_status, (
            "expected dispensing_status {} but got {}".format(
                dispensing_status, clinic.get("dispensing_status")
            )
        )
    if stockout_par_level_count is not None:
        assert clinic.get("stockout_par_level_count") == stockout_par_level_count, (
            "expected stockout_par_level_count {} but got {}".format(
                stockout_par_level_count, clinic.get("stockout_par_level_count")
            )
        )


def assert_unit_ledger_balances(summary: Dict[str, Any]) -> None:
    """The clinic ledger identity: everything accounted equals everything received."""
    assert summary["units_accounted_total"] == summary["units_received_total"], (
        "units_accounted_total {} must equal units_received_total {}".format(
            summary["units_accounted_total"], summary["units_received_total"]
        )
    )


def assert_fields_unchanged(before: Dict[str, Any], after: Dict[str, Any], *fields: str) -> None:
    """A rejected request must leave the named fields exactly as they were."""
    for field in fields:
        assert before.get(field) == after.get(field), (
            "field {} changed from {!r} to {!r} across a rejected request".format(
                field, before.get(field), after.get(field)
            )
        )
