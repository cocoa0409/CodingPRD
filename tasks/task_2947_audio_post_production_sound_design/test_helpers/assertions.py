"""Domain assertions layered on top of the generic envelope validators."""

import re
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_valid_uuid

from .api_client import canonical_instant
from .constants import (
    DECIMAL_TOLERANCE,
    ENVELOPE_TIMESTAMP_PATTERN,
    INSTANT_PATTERN,
    REJECTION_CODE_ORDER,
)

# --------------------------------------------------------------------------
# Identity and instant shapes
# --------------------------------------------------------------------------


def assert_identity_fields(entity: dict) -> None:
    """A resource carrying the full identity set: id, timestamps and version."""
    assert is_valid_uuid(entity["id"]), f"id must be a bare UUID string, got {entity['id']!r}"
    assert "_" not in entity["id"], "id must carry no type prefix"
    assert_domain_instant(entity["created_at"])
    assert_domain_instant(entity["updated_at"])
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"


def assert_immutable_record(entity: dict) -> None:
    """An immutable record: id and created_at only, no updated_at, no version."""
    assert is_valid_uuid(entity["id"]), f"id must be a bare UUID string, got {entity['id']!r}"
    assert_domain_instant(entity["created_at"])
    assert "updated_at" not in entity, "an immutable record exposes no updated_at"
    assert "version" not in entity, "an immutable record exposes no version"


def assert_domain_instant(value) -> None:
    """Whole-second ISO-8601 UTC with a trailing Z, no fractional seconds."""
    assert isinstance(value, str), f"expected an instant string, got {value!r}"
    assert re.match(INSTANT_PATTERN, value), (
        f"expected whole-second ISO-8601 UTC with a trailing Z, got {value!r}"
    )


def assert_envelope_timestamp(value) -> None:
    """The envelope's own timestamp keeps three fractional digits."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    assert re.match(ENVELOPE_TIMESTAMP_PATTERN, value), (
        f"expected an ISO-8601 UTC timestamp with three fractional digits, got {value!r}"
    )


def assert_instants_equal(actual, expected) -> None:
    """Compare two instants after normalising both to whole-second UTC."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"expected instant {expected!r}, got {actual!r}"
    )


def assert_envelope(body: dict, expected_response_type: str) -> None:
    """The success envelope carries a request id, a timestamp and a response type."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_envelope_timestamp(meta["api_request_timestamp"])
    assert body["response_type"] == expected_response_type


def assert_error_envelope_meta(body: dict) -> None:
    """The error envelope's meta carries only the request id and timestamp."""
    meta = body["meta"]
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only api_request_id and api_request_timestamp, got {sorted(meta)}"
    )


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------


def assert_cents(value) -> None:
    """Every field whose name ends in _cents is an integer count of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"monetary amounts are integer cents, got {value!r}"
    )


def assert_decimal(actual, expected) -> None:
    """A decimal quantity carried to two places."""
    assert actual == pytest.approx(expected, abs=DECIMAL_TOLERANCE), (
        f"expected {expected}, got {actual}"
    )


def assert_two_decimal_places(value) -> None:
    """A decimal quantity must not carry more than two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"expected a number, got {value!r}"
    )
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"expected at most two decimal places, got {value!r}"
    )


# --------------------------------------------------------------------------
# Project ledgers
# --------------------------------------------------------------------------


def assert_hour_ledger_identity(source: dict) -> None:
    """reserved + consumed + available must equal authorized after every mutation."""
    total = (
        source["stage_hours_reserved"]
        + source["stage_hours_consumed"]
        + source["stage_hours_available"]
    )
    assert total == pytest.approx(source["stage_hours_authorized"], abs=DECIMAL_TOLERANCE), (
        "stage_hours_reserved + stage_hours_consumed + stage_hours_available must equal "
        f"stage_hours_authorized; got {total} against {source['stage_hours_authorized']}"
    )


def assert_hour_ledger(project: dict, reserved, consumed, available) -> None:
    assert_decimal(project["stage_hours_reserved"], reserved)
    assert_decimal(project["stage_hours_consumed"], consumed)
    assert_decimal(project["stage_hours_available"], available)
    assert_hour_ledger_identity(project)


def assert_billing_chain(ledger: dict) -> None:
    """The pinned roll-up intermediates must agree with each other."""
    components = (
        ledger["stage_cost_subtotal_cents"]
        + ledger["adr_cost_cents"]
        + ledger["conform_fee_total_cents"]
        + ledger["license_fee_accrued_cents"]
    )
    assert ledger["pre_discount_total_cents"] == components, (
        "pre_discount_total_cents must be the sum of the four component ledgers"
    )
    assert (
        ledger["discounted_base_cents"]
        == ledger["pre_discount_total_cents"] - ledger["volume_discount_cents"]
    ), "discounted_base_cents must be pre_discount_total_cents minus volume_discount_cents"
    assert (
        ledger["billing_total_cents"]
        == ledger["discounted_base_cents"] + ledger["rush_surcharge_cents"]
    ), "billing_total_cents must be discounted_base_cents plus rush_surcharge_cents"


def assert_project_at_rest(project: dict, stage_hours_authorized=40.00) -> None:
    """A freshly created project's ledgers are all empty."""
    assert_decimal(project["stage_hours_authorized"], stage_hours_authorized)
    assert_decimal(project["stage_hours_reserved"], 0.00)
    assert_decimal(project["stage_hours_consumed"], 0.00)
    assert_decimal(project["stage_hours_available"], stage_hours_authorized)
    assert project["stage_cost_subtotal_cents"] == 0
    assert project["adr_cost_cents"] == 0
    assert project["license_fee_accrued_cents"] == 0
    assert project["billing_total_cents"] == 0
    assert_decimal(project["license_risk_score_intake"], 0.00)
    assert_decimal(project["license_risk_score_audit"], 0.00)
    assert project["unlicensed_usage_count"] == 0
    assert project["stale_stem_count"] == 0
    assert project["conformed_stem_count"] == 0


# --------------------------------------------------------------------------
# QC
# --------------------------------------------------------------------------


def assert_rejection_code_order(codes) -> None:
    """Codes are always emitted in the one fixed order."""
    positions = [REJECTION_CODE_ORDER.index(code) for code in codes]
    assert positions == sorted(positions), (
        "rejection codes must be ordered LOUDNESS_OUT_OF_TOLERANCE, TRUE_PEAK_EXCEEDED, "
        f"ME_STEMS_MISSING; got {codes}"
    )


def assert_qc_report_snapshot(report: dict, deliverable: dict, target_lufs) -> None:
    """A report snapshots the measurements and the target it was judged against."""
    assert_immutable_record(report)
    assert report["deliverable_id"] == deliverable["id"]
    assert_decimal(report["measured_integrated_lufs"], deliverable["measured_integrated_lufs"])
    assert_decimal(report["measured_true_peak_dbtp"], deliverable["measured_true_peak_dbtp"])
    assert_decimal(report["target_lufs"], target_lufs)
    assert_domain_instant(report["evaluated_at_utc"])
    assert_rejection_code_order(report["rejection_codes"])


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


def _as_epoch(instant: str) -> float:
    parsed = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def assert_created_at_descending(records) -> None:
    """Newest first."""
    stamps = [_as_epoch(record["created_at"]) for record in records]
    assert stamps == sorted(stamps, reverse=True), (
        f"records must be ordered by created_at descending; got {[r['created_at'] for r in records]}"
    )


def assert_created_at_ascending(records) -> None:
    stamps = [_as_epoch(record["created_at"]) for record in records]
    assert stamps == sorted(stamps), (
        f"records must be ordered by created_at ascending; got {[r['created_at'] for r in records]}"
    )


def assert_ordered_by(records, *keys) -> None:
    """Records must be ordered ascending by the given keys in sequence."""
    observed = [tuple(record[key] for key in keys) for record in records]
    assert observed == sorted(observed), (
        f"records must be ordered ascending by {keys}; got {observed}"
    )


def assert_unpaginated_list(data) -> None:
    """A plain list payload, whatever its envelope pagination fields say."""
    assert isinstance(data, list), f"expected a list payload, got {type(data).__name__}"
