"""Domain assertion helpers.

The generic envelope, pagination and error checks come from the shared runner
validators; everything here layers the PRD's own rules on top of them — the
common bookkeeping fields of §2.4, the instant rendering of §2.5, the integer
cents rule of §2.7, the conserved quantities of §2.10 and the nightly-run report
shape of §3.9.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant
from .constants import (
    LEDGER_COMMON_FIELDS,
    NIGHTLY_RUN_ID_LISTS,
    VERSIONED_COMMON_FIELDS,
)
from .types import Resource

# ── Identifiers, instants and dates (PRD §2.4, §2.5) ──


def assert_uuid(value: Any, label: str = "id") -> None:
    """Ids are UUIDs "carrying no prefix and no embedded meaning" (PRD §2.4)."""
    assert isinstance(value, str), f"{label} must be a string, got {type(value).__name__}"
    assert is_valid_uuid(value), f"{label} must be a UUID, got {value!r}"
    assert "_" not in value, f"{label} must carry no prefix, got {value!r}"


def assert_instant_format(value: Any, label: str = "timestamp") -> None:
    """An instant is UTC ISO 8601 with exactly three fractional-second digits."""
    assert isinstance(value, str), f"{label} must be a string, got {type(value).__name__}"
    assert is_iso8601_timestamp(value), f"{label} is not ISO 8601: {value!r}"
    assert value.endswith("Z"), f"{label} must be a UTC instant ending in Z: {value!r}"
    assert "." in value, f"{label} must carry fractional seconds: {value!r}"
    fraction = value.rsplit(".", 1)[1][:-1]
    assert len(fraction) == 3, (
        f"{label} must render exactly three fractional-second digits, got {value!r}"
    )


def assert_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Compare two instants at millisecond granularity."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label} expected {expected!r}, got {actual!r}"
    )


def assert_date_only(value: Any, label: str = "date") -> None:
    """A calendar date is a bare ``YYYY-MM-DD`` with no time part (PRD §2.5)."""
    assert isinstance(value, str), f"{label} must be a string, got {type(value).__name__}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{label} must be a bare calendar date, got {value!r}"
    )
    assert "T" not in value and "Z" not in value, (
        f"{label} must carry no time-of-day part, got {value!r}"
    )
    year, month, day = value.split("-")
    assert year.isdigit() and month.isdigit() and day.isdigit(), (
        f"{label} must be numeric, got {value!r}"
    )


def assert_cents(value: Any, label: str = "amount") -> None:
    """Money is "an integer number of cents" and never a decimal (PRD §2.7)."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r} ({type(value).__name__})"
    )


def assert_optional_cents(value: Any, label: str = "amount") -> None:
    if value is not None:
        assert_cents(value, label)


# ── Common bookkeeping fields (PRD §2.4) ──


def assert_common_fields(resource: Resource, expected_version: Optional[int] = None) -> None:
    """Every persisted record carries id, created_at, updated_at and version."""
    for field in VERSIONED_COMMON_FIELDS:
        assert field in resource, f"missing common field {field!r}"
    assert_uuid(resource["id"])
    assert_instant_format(resource["created_at"], "created_at")
    assert_instant_format(resource["updated_at"], "updated_at")
    assert isinstance(resource["version"], int) and not isinstance(resource["version"], bool), (
        f"version must be an integer, got {resource['version']!r}"
    )
    assert resource["version"] >= 1, f"version starts at 1, got {resource['version']}"
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"version expected {expected_version}, got {resource['version']}"
        )


def assert_created_resource(resource: Resource) -> None:
    """A freshly created record is at version 1 with equal timestamps."""
    assert_common_fields(resource, expected_version=1)
    assert canonical_instant(resource["created_at"]) == canonical_instant(resource["updated_at"]), (
        "a newly created record must have created_at equal to updated_at, got "
        f"{resource['created_at']!r} and {resource['updated_at']!r}"
    )


def assert_ledger_common_fields(entry: Resource) -> None:
    """A ledger entry "carries only id and created_at" (PRD §2.4)."""
    for field in LEDGER_COMMON_FIELDS:
        assert field in entry, f"ledger entry missing common field {field!r}"
    assert_uuid(entry["id"])
    assert_instant_format(entry["created_at"], "created_at")
    assert "updated_at" not in entry, "a ledger entry carries no updated_at"
    assert "version" not in entry, "a ledger entry carries no version"


def assert_version_bumped(after: Resource, before: Resource, by: int = 1) -> None:
    """An accepted mutation raises version by exactly one (PRD §2.4)."""
    assert after["version"] == before["version"] + by, (
        f"version expected {before['version'] + by}, got {after['version']}"
    )


def assert_unchanged(after: Resource, before: Resource, fields: Iterable[str]) -> None:
    for field in fields:
        assert after.get(field) == before.get(field), (
            f"{field} was expected to be untouched: {before.get(field)!r} -> {after.get(field)!r}"
        )


def assert_fields(resource: Resource, expected: Dict[str, Any]) -> None:
    """Assert an exact value for each named field."""
    for field, value in expected.items():
        assert field in resource, f"missing field {field!r}"
        assert resource[field] == value, (
            f"{field} expected {value!r}, got {resource[field]!r}"
        )


def assert_field_set(resource: Resource, expected_fields: Sequence[str]) -> None:
    """Assert that every named field is present (value unconstrained)."""
    missing = [field for field in expected_fields if field not in resource]
    assert not missing, f"missing fields: {missing}"


def assert_nulls(resource: Resource, fields: Iterable[str]) -> None:
    for field in fields:
        assert field in resource, f"missing field {field!r}"
        assert resource[field] is None, f"{field} expected null, got {resource[field]!r}"


# ── Envelope and list shape (PRD §2.2, §2.3) ──


def assert_object_envelope(response, expected_status: int = 200) -> Resource:
    """A single-resource response: response_type ``object`` and no list meta keys.

    ``expected_status`` is 200 for reads and settlements and 201 for the nine
    endpoints that bring a new resource into existence (PRD §4).
    """
    body = response.json()
    assert body.get("response_type") == "object", (
        f"response_type expected 'object', got {body.get('response_type')!r}"
    )
    meta = body.get("meta", {})
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key not in meta or meta[key] is None, (
            f"a single-resource response omits meta.{key}, got {meta.get(key)!r}"
        )
    return validate_success(response, expected_status)


def assert_request_meta(response) -> Dict[str, Any]:
    """Every response carries an api_request_id and an api_request_timestamp."""
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str), "meta.api_request_id must be a string"
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must be prefixed 'req_', got {meta['api_request_id']!r}"
    )
    assert_instant_format(meta["api_request_timestamp"], "meta.api_request_timestamp")
    return meta


def assert_list_envelope(response, expected_total: Optional[int] = None):
    """A collection read: response_type ``array`` plus all four pagination keys."""
    body = response.json()
    assert body.get("response_type") == "array", (
        f"response_type expected 'array', got {body.get('response_type')!r}"
    )
    rows, meta = validate_paginated(response)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"total_count expected {expected_total}, got {meta['total_count']}"
        )
    return rows, meta


def assert_created_at_ascending(rows: List[Resource]) -> None:
    """Every collection is returned in ascending created_at order (PRD §2.3)."""
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"rows are not in ascending created_at order: {stamps}"


def assert_ids_in_order(rows: List[Resource], expected_ids: Sequence[str]) -> None:
    assert [row["id"] for row in rows] == list(expected_ids), (
        f"ids expected {list(expected_ids)}, got {[row['id'] for row in rows]}"
    )


def assert_contains_id(rows: List[Resource], resource_id: str) -> None:
    assert any(row["id"] == resource_id for row in rows), (
        f"{resource_id} is absent from the returned page"
    )


def assert_excludes_id(rows: List[Resource], resource_id: str) -> None:
    assert all(row["id"] != resource_id for row in rows), (
        f"{resource_id} was not expected in the returned page"
    )


# ── Refusals (PRD §2.8, §5) ──


def assert_refused(response, error_id: str, status: Optional[int] = None) -> Resource:
    """Assert a refusal by identifier, cross-checking the catalogued status."""
    return validate_error(response, error_id, status)


def assert_error_shape(response) -> Resource:
    """An error body carries error_id and message under response_type 'error'."""
    body = response.json()
    assert body.get("response_type") == "error", (
        f"response_type expected 'error', got {body.get('response_type')!r}"
    )
    data = body["data"]
    assert isinstance(data.get("error_id"), str) and data["error_id"], "error_id must be a string"
    assert isinstance(data.get("message"), str) and data["message"], "message must be a string"
    return data


# ── Ledger and conserved quantities (PRD §2.10) ──


def sum_signed(entries: List[Resource]) -> int:
    return sum(entry["amount_cents"] for entry in entries)


def assert_benefit_conserved(entries: List[Resource], expected_used: int) -> None:
    """Signed BENEFIT amounts for one enrollment equal its annual usage."""
    benefit = [entry for entry in entries if entry.get("ledger_kind") == "BENEFIT"]
    assert sum_signed(benefit) == expected_used, (
        f"signed BENEFIT total expected {expected_used}, got {sum_signed(benefit)}"
    )


def assert_ledger_amounts(entries: List[Resource], expected: Sequence[int]) -> None:
    assert [entry["amount_cents"] for entry in entries] == list(expected), (
        f"ledger amounts expected {list(expected)}, got {[e['amount_cents'] for e in entries]}"
    )


def entries_of_type(entries: List[Resource], entry_type: str) -> List[Resource]:
    return [entry for entry in entries if entry.get("entry_type") == entry_type]


# ── Nightly run report (PRD §3.9) ──


def assert_nightly_report_shape(report: Resource) -> None:
    """The report carries ``ran_at`` and all eleven identifier lists."""
    assert "ran_at" in report, "the nightly report must carry ran_at"
    assert_instant_format(report["ran_at"], "ran_at")
    for key in NIGHTLY_RUN_ID_LISTS:
        assert key in report, f"the nightly report must carry {key}"
        assert isinstance(report[key], list), f"{key} must be a list, got {report[key]!r}"
        for value in report[key]:
            assert_uuid(value, f"{key} entry")


def assert_nightly_lists_empty(report: Resource, except_for: Sequence[str] = ()) -> None:
    """Assert that every identifier list is empty apart from those named."""
    for key in NIGHTLY_RUN_ID_LISTS:
        if key in except_for:
            continue
        assert report[key] == [], f"{key} expected empty, got {report[key]!r}"


def assert_nightly_names(report: Resource, key: str, expected_ids: Sequence[str]) -> None:
    assert sorted(report[key]) == sorted(expected_ids), (
        f"{key} expected {sorted(expected_ids)}, got {sorted(report[key])}"
    )


# ── Mail-drop summary (PRD §3.2) ──


def assert_drop_summary_shape(summary: Resource) -> None:
    for field in (
        "campaign_id",
        "status",
        "mailed_count",
        "suppressed_count",
        "suppressed_by_reason",
        "mailed_premises_ids",
    ):
        assert field in summary, f"the drop summary must carry {field}"
    assert isinstance(summary["mailed_count"], int), "mailed_count must be an integer"
    assert isinstance(summary["suppressed_count"], int), "suppressed_count must be an integer"
    assert isinstance(summary["suppressed_by_reason"], dict), (
        "suppressed_by_reason must be a mapping of reason to count"
    )
    assert isinstance(summary["mailed_premises_ids"], list), "mailed_premises_ids must be a list"


def assert_drop_counts_agree(summary: Resource) -> None:
    """mailed_count must agree with the list of premises it names."""
    assert summary["mailed_count"] == len(summary["mailed_premises_ids"]), (
        f"mailed_count {summary['mailed_count']} disagrees with "
        f"{len(summary['mailed_premises_ids'])} named premises"
    )
    assert summary["suppressed_count"] == sum(summary["suppressed_by_reason"].values()), (
        f"suppressed_count {summary['suppressed_count']} disagrees with the reason breakdown "
        f"{summary['suppressed_by_reason']}"
    )


__all__ = [
    "assert_benefit_conserved",
    "assert_cents",
    "assert_common_fields",
    "assert_contains_id",
    "assert_created_at_ascending",
    "assert_created_resource",
    "assert_date_only",
    "assert_drop_counts_agree",
    "assert_drop_summary_shape",
    "assert_error_shape",
    "assert_excludes_id",
    "assert_field_set",
    "assert_fields",
    "assert_ids_in_order",
    "assert_instant",
    "assert_instant_format",
    "assert_ledger_amounts",
    "assert_ledger_common_fields",
    "assert_list_envelope",
    "assert_nightly_lists_empty",
    "assert_nightly_names",
    "assert_nightly_report_shape",
    "assert_nulls",
    "assert_object_envelope",
    "assert_optional_cents",
    "assert_refused",
    "assert_request_meta",
    "assert_unchanged",
    "assert_uuid",
    "assert_version_bumped",
    "entries_of_type",
    "sum_signed",
]
