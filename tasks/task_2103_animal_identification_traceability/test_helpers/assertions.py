"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

UUID_KEYS = ("id",)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing Z and optional
    fractional digits."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, field: str = "timestamp"):
    """Compare two ISO 8601 UTC instants by value rather than by rendering."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{field} must be {expected}, got {actual}"
    )


# --------------------------------------------------------------------------
# Common resource properties
# --------------------------------------------------------------------------
def assert_common_fields(data: dict):
    """Mutable records carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_bare_uuid(value: str):
    assert is_valid_uuid(value), f"expected a UUID with no type prefix, got {value!r}"


def assert_millisecond_timestamp(value: str, field: str = "timestamp"):
    """ISO 8601 UTC rendered with exactly three fractional digits."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field} must be ISO 8601, got {value!r}"
    assert value.endswith("Z"), f"{field} must be a UTC instant ending in Z, got {value!r}"
    assert len(value) == 24 and value[19] == ".", (
        f"{field} must carry three fractional digits, got {value!r}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_producer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert "@" in data["contact_email"], "contact_email must contain an @ character"
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["privacy_level"] in ("STANDARD", "RESTRICTED")
    assert data["enrollment_status"] in ("NOT_ENROLLED", "ENROLLED", "LAPSED")
    assert isinstance(data["enrolled_head_count"], int)
    assert data["incentive_tier"] in ("TIER_0", "TIER_1", "TIER_2", "TIER_3")
    assert isinstance(data["on_time_movement_pct"], (int, float))
    assert isinstance(data["incentive_balance_cents"], int)
    assert isinstance(data["lifetime_clawback_cents"], int)


def assert_premises(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["producer_id"])
    assert isinstance(data["pin"], str) and len(data["pin"]) == 7
    assert data["operation_type"] in ("COW_CALF", "FEEDLOT", "MARKET", "HARVEST_FACILITY")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["registration_status"] in ("PENDING_REVIEW", "ACTIVE", "SUSPENDED")
    assert data["health_status"] in ("CLEAR", "UNDER_INVESTIGATION", "QUARANTINED")
    assert isinstance(data["animal_count"], int) and data["animal_count"] >= 0
    assert isinstance(data["pending_hold_count"], int) and data["pending_hold_count"] >= 0


def assert_device_supplier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["supplier_code"], str) and len(data["supplier_code"]) == 4
    assert isinstance(data["aid_prefix"], str) and len(data["aid_prefix"]) == 3
    assert data["status"] in ("PENDING_REVIEW", "APPROVED", "SUSPENDED", "REVOKED")
    assert isinstance(data["defect_report_count"], int)
    assert isinstance(data["issued_tag_count"], int)
    assert isinstance(data["retired_tag_count"], int)
    assert isinstance(data["retired_returned_count"], int)
    assert isinstance(data["conformance_score"], (int, float))
    assert 0.00 <= data["conformance_score"] <= 100.00, "conformance_score is clamped to [0, 100]"
    assert isinstance(data["probation"], bool)
    assert isinstance(data["issuance_cap"], int)


def assert_tag_lot(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["supplier_id"])
    assert is_valid_uuid(data["premises_id"])
    assert isinstance(data["serial_start"], int)
    assert isinstance(data["serial_end"], int)
    assert data["serial_end"] >= data["serial_start"]
    assert data["quantity"] == data["serial_end"] - data["serial_start"] + 1
    assert data["status"] in ("ISSUED", "ACTIVE", "DEPLETED", "RECALLED", "VOIDED")
    assert isinstance(data["fee_cents"], int), "fee_cents is whole cents"
    assert isinstance(data["surcharge_cents"], int), "surcharge_cents is whole cents"
    assert_tag_lot_partition(data)


def assert_tag_lot_partition(lot: dict):
    """quantity always equals the sum of the five device-count buckets."""
    total = (
        lot["unapplied_count"]
        + lot["applied_count"]
        + lot["retired_count"]
        + lot["replaced_count"]
        + lot["voided_count"]
    )
    assert lot["quantity"] == total, (
        "quantity must equal unapplied + applied + retired + replaced + voided; "
        f"got quantity={lot['quantity']} but the buckets sum to {total}"
    )


def assert_tag(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["tag_lot_id"])
    assert isinstance(data["ain"], str) and len(data["ain"]) == 15 and data["ain"].isdigit()
    assert data["device_status"] in ("APPLIED", "RETIRED", "REPLACED", "VOIDED")
    assert is_iso8601_timestamp(data["applied_at"])


def assert_animal(data: dict):
    assert_common_fields(data)
    assert isinstance(data["ain"], str) and len(data["ain"]) == 15
    assert data["species"] in ("BOVINE", "OVINE", "CAPRINE", "CERVID")
    assert isinstance(data["birth_date"], str) and len(data["birth_date"]) == 10
    assert is_valid_uuid(data["birth_premises_id"])
    assert data["lifecycle_status"] in ("ACTIVE", "IN_TRANSIT", "HARVESTED", "VOIDED")
    assert data["trace_status"] in ("NORMAL", "TRACE_HIT", "CLEARED")
    assert isinstance(data["sighting_count"], int) and data["sighting_count"] >= 0
    assert isinstance(data["last_sequence_no"], int) and data["last_sequence_no"] >= 1


def assert_sighting(data: dict):
    """A sighting is immutable: it carries id and created_at but no updated_at
    and no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "an immutable sighting carries no updated_at field"
    assert "version" not in data, "an immutable sighting carries no version field"
    assert is_valid_uuid(data["animal_id"])
    assert is_valid_uuid(data["premises_id"])
    assert data["sighting_type"] in ("TAG_APPLIED", "DEPARTURE", "ARRIVAL", "HARVEST")
    assert is_iso8601_timestamp(data["observed_at"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["reversed"], bool)


def assert_movement_event(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["animal_id"])
    assert is_valid_uuid(data["origin_premises_id"])
    assert is_valid_uuid(data["destination_premises_id"])
    assert is_iso8601_timestamp(data["departed_at"])
    assert is_iso8601_timestamp(data["reported_at"])
    assert isinstance(data["interstate"], bool)
    assert data["status"] in ("REPORTED", "RECEIVED", "DISPUTED", "VOIDED")
    assert isinstance(data["reporting_lag_hours"], (int, float))
    assert isinstance(data["on_time"], bool)
    assert isinstance(data["correction_count"], int)


def assert_trace_request(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["index_animal_id"])
    assert data["pathogen_class"] in ("DIRECT_CONTACT", "ENVIRONMENTAL")
    assert data["direction"] in ("BACKWARD", "FORWARD", "BOTH")
    assert 1 <= data["lookback_days"] <= 365
    assert 1 <= data["max_hops"] <= 5
    assert data["status"] in ("SUBMITTED", "RUNNING", "COMPLETED", "CANCELLED")
    assert isinstance(data["hits"], list)
    assert data["hit_count"] == len(data["hits"]), "hit_count is the length of hits"
    assert isinstance(data["premises_touched_count"], int)
    assert isinstance(data["hops_total"], int)
    assert isinstance(data["hops_unreachable"], int)
    assert is_iso8601_timestamp(data["opened_at"])


def assert_trace_hit(hit: dict):
    assert is_valid_uuid(hit["animal_id"])
    assert is_valid_uuid(hit["premises_id"])
    assert isinstance(hit["hop_depth"], int) and hit["hop_depth"] >= 1
    assert is_iso8601_timestamp(hit["first_contact_at"])
    assert isinstance(hit["responded"], bool)
    assert isinstance(hit["resolved"], bool)


def assert_hold_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["premises_id"])
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_until"])
    assert data["status"] in ("PROPOSED", "ACTIVE", "UNDER_APPEAL", "RELEASED")
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]
    assert isinstance(data["appeal_count"], int) and 0 <= data["appeal_count"] <= 2


def assert_reconciliation_run(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["premises_id"])
    assert isinstance(data["period_start"], str) and len(data["period_start"]) == 10
    assert isinstance(data["period_end"], str) and len(data["period_end"]) == 10
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "VARIANCE_FLAGGED", "SUPERSEDED",
    )
    if data.get("basis") is not None:
        assert data["basis"] in ("AS_ISSUED", "AS_SIGHTED")


def assert_incentive_award(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["producer_id"])
    assert isinstance(data["head_count_snapshot"], int)
    assert isinstance(data["tier_factor"], (int, float))
    assert isinstance(data["compliance_multiplier"], (int, float))
    assert isinstance(data["line_items"], list)
    assert isinstance(data["awarded_cents"], int), "awarded_cents is whole cents"
    assert isinstance(data["clawback_cents"], int), "clawback_cents is whole cents"
    assert data["status"] in ("ACCRUED", "PAID", "CLAWED_BACK")
    assert_award_lines_sum_to_total(data)


def assert_award_lines_sum_to_total(award: dict):
    """awarded_cents is the plain sum of the rounded per-premises line amounts."""
    line_total = sum(line["line_cents"] for line in award["line_items"])
    assert award["awarded_cents"] == line_total, (
        "awarded_cents must be the plain sum of line_items[].line_cents; "
        f"got {award['awarded_cents']} against a line sum of {line_total}"
    )
    for line in award["line_items"]:
        assert isinstance(line["line_cents"], int), "each line_cents is whole cents"
        assert isinstance(line["animal_count"], int)


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_whole_cents(value, field: str = "amount"):
    assert isinstance(value, int), f"{field} must be an integer number of cents, got {value!r}"


def assert_two_decimal_places(value, field: str = "value"):
    assert isinstance(value, (int, float)), f"{field} must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"{field} must be rounded to two decimal places, got {value!r}"
    )


def assert_envelope_meta(body: dict):
    """Every success envelope carries a req_-prefixed request id and a timestamp."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert_millisecond_timestamp(meta["api_request_timestamp"], "meta.api_request_timestamp")


def assert_sequence_numbers_ascending(rows: list):
    numbers = [row["sequence_no"] for row in rows]
    assert numbers == sorted(numbers), f"rows must be ordered by sequence_no ASC, got {numbers}"
