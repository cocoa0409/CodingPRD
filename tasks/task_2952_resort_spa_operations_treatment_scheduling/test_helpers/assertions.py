"""Domain-specific assertion helpers."""

import re

from prd_bench_local_runner.testing import is_valid_uuid, validate_paginated

from .constants import CANON_FINAL_ROW, CANON_PROVISIONAL_ROW

_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def canonical_instant(value: str) -> str:
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits so
    that a comparison never fails on sub-second width alone.

    PRD §2.5 requires three fractional digits on server-minted timestamps, while
    PRD §2.4 spells the clock's startup default as `2026-08-01T00:00:00Z`; both
    spellings denote the same instant.
    """
    assert isinstance(value, str), f"expected an instant string, got {value!r}"
    m = _INSTANT_RE.match(value)
    assert m, f"not an ISO 8601 UTC instant: {value!r}"
    head = value[:19]
    frac = m.group(1) or ".0"
    millis = (frac[1:] + "000")[:3]
    return f"{head}.{millis}Z"


def assert_same_instant(actual: str, expected: str, label: str = "instant") -> None:
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}")


def assert_iso_instant(value: str, label: str = "field") -> None:
    """PRD §2.5: an ISO 8601 UTC instant with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _INSTANT_RE.match(value), f"{label} is not an ISO 8601 UTC instant: {value!r}"


def assert_calendar_date(value: str, label: str = "field") -> None:
    """PRD §2.5: date-only fields must be a valid `YYYY-MM-DD` calendar date."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert _DATE_RE.match(value), f"{label} is not a YYYY-MM-DD date: {value!r}"


def assert_integer_cents(value, label: str = "money field") -> None:
    """PRD §2.6: "All monetary amounts in this system are integers denominated in
    cents; no money field is ever a decimal or a string.\""""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {type(value).__name__} "
        f"{value!r}")


def assert_common_fields(entity: dict, label: str = "resource") -> None:
    """PRD §2.5: `id` UUID, `created_at`, `updated_at` and `version` starting at 1."""
    assert is_valid_uuid(entity["id"]), f"{label}.id must be a bare UUID: {entity['id']!r}"
    assert "_" not in entity["id"], f"{label}.id must carry no type prefix"
    assert_iso_instant(entity["created_at"], f"{label}.created_at")
    assert_iso_instant(entity["updated_at"], f"{label}.updated_at")
    assert isinstance(entity["version"], int), f"{label}.version must be an int"
    assert entity["version"] >= 1, f"{label}.version starts at 1"


def assert_audit_row_fields(row: dict, label: str = "audit row") -> None:
    """PRD §2.5: write-once audit rows "carry only `id` and `created_at` — both
    `updated_at` and `version` are absent from them\""""
    assert is_valid_uuid(row["id"]), f"{label}.id must be a bare UUID"
    assert_iso_instant(row["created_at"], f"{label}.created_at")
    assert "updated_at" not in row, f"{label} must not expose updated_at"
    assert "version" not in row, f"{label} must not expose version"


def assert_percent_2dp(value, label: str = "percentage") -> None:
    """PRD §2.6: "Both `utilization_pct` and `attach_rate_pct` are decimals
    carrying exactly two decimal places\""""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}")
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most two decimal places, got {value!r}")


def assert_ce_hours(value, label: str = "hours") -> None:
    """PRD §2.6: "hours are decimals with at most one decimal place\""""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}")
    assert round(float(value), 1) == float(value), (
        f"{label} must carry at most one decimal place, got {value!r}")


def assert_clearance(appointment: dict, clearance_status: str, reason=None) -> None:
    """PRD §2.10: "`clearance_block_reason` is null whenever `clearance_status`
    is `PENDING` or `CLEARED`.\""""
    assert appointment["clearance_status"] == clearance_status, (
        f"expected clearance_status {clearance_status}, "
        f"got {appointment['clearance_status']}")
    assert appointment["clearance_block_reason"] == reason, (
        f"expected clearance_block_reason {reason!r}, "
        f"got {appointment['clearance_block_reason']!r}")
    if clearance_status in ("PENDING", "CLEARED"):
        assert appointment["clearance_block_reason"] is None, (
            "clearance_block_reason must be null when clearance is PENDING or CLEARED")


def assert_state_pair(appointment: dict, schedule_status: str, clearance_status: str,
                      reason=None) -> None:
    """PRD §2.10: "it is the pair that decides which transitions are legal.\""""
    assert appointment["schedule_status"] == schedule_status, (
        f"expected schedule_status {schedule_status}, "
        f"got {appointment['schedule_status']}")
    assert_clearance(appointment, clearance_status, reason)


def assert_settlement_row(row: dict, expected: dict, label: str = "settlement row") -> None:
    """Compare every computed money field of a settlement row against a
    pre-computed expectation, and check each is an integer number of cents."""
    for field, value in expected.items():
        assert field in row, f"{label} is missing {field}"
        if field.endswith("_cents") or field == "service_charge_bp":
            assert_integer_cents(row[field], f"{label}.{field}")
        assert row[field] == value, (
            f"{label}.{field}: expected {value}, got {row[field]}")


def assert_canonical_provisional_row(row: dict) -> None:
    assert row["variant"] == "PROVISIONAL", f"expected PROVISIONAL, got {row['variant']}"
    assert_settlement_row(row, CANON_PROVISIONAL_ROW, "provisional row")


def assert_canonical_final_row(row: dict) -> None:
    assert row["variant"] == "FINAL", f"expected FINAL, got {row['variant']}"
    assert_settlement_row(row, CANON_FINAL_ROW, "final row")


def assert_pool_conserved(row: dict) -> None:
    """PRD §3.9: "the three buckets sum to `distributable_pool_cents` to the cent
    regardless of how the two roundings fell.\""""
    total = (row["therapist_share_cents"] + row["support_pool_cents"]
             + row["house_share_cents"])
    assert total == row["distributable_pool_cents"], (
        f"therapist {row['therapist_share_cents']} + support "
        f"{row['support_pool_cents']} + house {row['house_share_cents']} = {total}, "
        f"must equal distributable_pool_cents {row['distributable_pool_cents']}")


def assert_folio_rows(rows, expected, label: str = "folio") -> None:
    """Compare a folio listing against a list of (kind, amount_cents) pairs, in
    order. PRD §2.11 postings are listed "in ascending `posted_at` order"."""
    actual = [(r["kind"], r["amount_cents"]) for r in rows]
    assert actual == list(expected), f"{label}: expected {list(expected)}, got {actual}"
    for row in rows:
        assert_integer_cents(row["amount_cents"], f"{label} amount_cents")
        assert row["appointment_id"] is not None, (
            "PRD §2.11: appointment_id is never null on a folio posting")


def assert_folio_contents(rows, expected, label: str = "folio") -> None:
    """Compare a folio listing against a multiset of (kind, amount_cents) pairs.

    Used where two postings share the same `posted_at` instant, so the PRD does
    not uniquely derive their relative order.
    """
    actual = sorted((r["kind"], r["amount_cents"]) for r in rows)
    assert actual == sorted(expected), (
        f"{label}: expected postings {sorted(expected)}, got {actual}")
    for row in rows:
        assert_integer_cents(row["amount_cents"], f"{label} amount_cents")


def assert_balance_equals_posting_sum(guest: dict, rows) -> None:
    """PRD §2.11: `folio_balance_cents` "is recomputed as the exact sum of
    `amount_cents` over every posting whose `guest_id` is that guest.\""""
    total = sum(r["amount_cents"] for r in rows)
    assert guest["folio_balance_cents"] == total, (
        f"folio_balance_cents {guest['folio_balance_cents']} must equal the exact "
        f"sum of posting amounts {total}")


def assert_ledgers(room: dict, therapist: dict, room_minutes: int,
                   therapist_minutes: int) -> None:
    """PRD §2.12 minute ledgers: room includes turnover, therapist excludes it."""
    assert room["booked_minutes_total"] == room_minutes, (
        f"room booked_minutes_total: expected {room_minutes}, "
        f"got {room['booked_minutes_total']}")
    assert therapist["assigned_minutes_total"] == therapist_minutes, (
        f"therapist assigned_minutes_total: expected {therapist_minutes}, "
        f"got {therapist['assigned_minutes_total']}")


def assert_list_count(response, expected_count: int, label: str = "list") -> list:
    """Validate a paginated list response and assert its total_count."""
    data, meta = validate_paginated(response)
    assert meta["total_count"] == expected_count, (
        f"{label}: expected total_count {expected_count}, got {meta['total_count']}")
    return data


def assert_error_envelope(response, expected_error_id: str) -> dict:
    """PRD §2.2: an error envelope's `meta` "contains only `api_request_id` and
    `api_request_timestamp`\"."""
    body = response.json()
    assert set(body.keys()) == {"meta", "response_type", "data"}, (
        f"error envelope keys must be exactly meta/response_type/data, "
        f"got {sorted(body.keys())}")
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only api_request_id and api_request_timestamp, "
        f"got {sorted(body['meta'].keys())}")
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}")
    assert_iso_instant(body["meta"]["api_request_timestamp"], "api_request_timestamp")
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"error data must carry only error_id and message, "
        f"got {sorted(body['data'].keys())}")
    assert body["data"]["error_id"] == expected_error_id, (
        f"expected error_id {expected_error_id}, got {body['data']['error_id']}")
    assert body["data"]["message"].strip(), "message must be non-empty"
    return body["data"]
