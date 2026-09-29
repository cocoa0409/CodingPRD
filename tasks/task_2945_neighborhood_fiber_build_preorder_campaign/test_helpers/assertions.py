"""Entity assertions, instant comparison helpers and domain invariant checks."""

from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

# --- Instant handling --------------------------------------------------------
# Timestamps are ISO 8601 UTC values with three fractional digits. Tests compare
# instants by their absolute value, so a response that writes
# "2026-10-12T11:00:00.000Z" satisfies an expectation of "2026-10-12T11:00:00Z".


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into an aware datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_instant(value: str) -> str:
    """Normalise an instant to a fixed millisecond-precision UTC rendering."""
    moment = parse_instant(value)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "instant"):
    """Assert two ISO 8601 instants denote the same moment."""
    assert actual is not None, f"{label} must not be null, expected {expected}"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_instant_is_null(actual, label: str = "instant"):
    assert actual is None, f"{label} must be null, got {actual!r}"


def assert_millisecond_precision(value: str, label: str = "timestamp"):
    """Assert the rendering carries exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert "." in value, f"{label} must carry three fractional digits, got {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"{label} must carry exactly three fractional digits, got {value!r}"
    )


# --- Envelope helpers --------------------------------------------------------
def assert_envelope_meta(response):
    """Every response carries meta.api_request_id and meta.api_request_timestamp."""
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
        "meta.api_request_id must be a non-empty string"
    )
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must be prefixed 'req_', got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        "meta.api_request_timestamp must be an ISO 8601 timestamp"
    )
    return meta


def assert_response_type(response, expected: str):
    body = response.json()
    assert body.get("response_type") == expected, (
        f"expected response_type {expected!r}, got {body.get('response_type')!r}"
    )


def validate_unpaginated(response, expected_status: int = 200):
    """Validate an array-shaped response that carries no pagination contract.

    Used only for the two run endpoints, whose arrays are pinned by the run
    itself rather than by client-supplied limit and offset.
    """
    assert response.status_code == expected_status, (
        f"expected {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("response_type") == "array", (
        f"expected response_type 'array', got {body.get('response_type')!r}"
    )
    assert isinstance(body.get("data"), list), "data must be a list"
    return body["data"], body["meta"]


def assert_page(response, total_count=None, limit=None, offset=None, has_more=None,
                row_count=None):
    """Validate a paginated list and cross-check the reported page metadata."""
    rows, meta = validate_paginated(response)
    if row_count is not None:
        assert len(rows) == row_count, (
            f"expected {row_count} rows on the page, got {len(rows)}"
        )
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"expected total_count {total_count}, got {meta['total_count']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )
    return rows, meta


def assert_total_count(response, expected: int):
    """Assert only the reported total_count of a paginated list."""
    _rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected, (
        f"expected total_count {expected}, got {meta['total_count']}"
    )
    return meta["total_count"]


def assert_error_body(response, expected_error_id: str):
    """Assert an error envelope carries the expected id and a non-empty message."""
    body = response.json()
    assert body["response_type"] == "error", (
        f"expected response_type 'error', got {body.get('response_type')!r}"
    )
    data = body["data"]
    assert data["error_id"] == expected_error_id, (
        f"expected error_id {expected_error_id}, got {data.get('error_id')}"
    )
    assert isinstance(data.get("message"), str) and data["message"].strip(), (
        "error data.message must be a non-empty string"
    )
    meta = body["meta"]
    assert set(meta.keys()) >= {"api_request_id", "api_request_timestamp"}, (
        "error meta must carry api_request_id and api_request_timestamp"
    )
    return data


# --- Percentage handling -----------------------------------------------------
def assert_pct(actual, expected, label: str = "percentage"):
    """Compare a two-decimal percentage by its rounded value."""
    assert actual is not None, f"{label} must not be null, expected {expected}"
    assert round(float(actual) + 1e-9, 2) == round(float(expected) + 1e-9, 2), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_two_decimal_places(actual, label: str = "percentage"):
    """Assert a percentage carries no more than two decimal places of value."""
    assert actual is not None, f"{label} must not be null"
    assert abs(float(actual) - round(float(actual), 2)) < 1e-9, (
        f"{label} must be expressed to two decimal places, got {actual}"
    )


def assert_cents(actual, expected, label: str = "amount"):
    """Money is an integer number of cents, never a string and never a float."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_is_integer_cents(actual, label: str = "amount"):
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )


# --- Common entity shape -----------------------------------------------------
def assert_versioned_common_fields(data: dict, entity_label: str = "entity"):
    """A versioned entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a UUID string, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 instant"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be an ISO 8601 instant"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer that starts at 1"
    )


def assert_campaign(data: dict):
    assert_versioned_common_fields(data, "Campaign")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["city"], str) and 1 <= len(data["city"]) <= 80
    assert is_iso8601_timestamp(data["prereg_window_open_at"])
    assert is_iso8601_timestamp(data["prereg_window_close_at"])
    assert parse_instant(data["prereg_window_close_at"]) > parse_instant(
        data["prereg_window_open_at"]
    ), "prereg_window_close_at must be strictly after prereg_window_open_at"
    assert 0.01 <= float(data["default_threshold_pct"]) <= 100.00
    assert_is_integer_cents(data["deposit_amount_cents"], "Campaign.deposit_amount_cents")
    assert data["deposit_amount_cents"] >= 0
    assert 0 <= data["max_deadline_extensions"] <= 5
    assert 1 <= data["extension_grant_days"] <= 90
    assert 1 <= data["claim_filing_window_days"] <= 365
    assert 1 <= data["restoration_sla_days"] <= 60
    assert 0.00 <= float(data["late_filing_factor"]) <= 1.00
    assert isinstance(data["zone_count"], int) and data["zone_count"] >= 0


def assert_build_zone(data: dict):
    assert_versioned_common_fields(data, "BuildZone")
    assert is_valid_uuid(data["campaign_id"])
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["zone_code"], str) and 1 <= len(data["zone_code"]) <= 16
    assert data["household_count"] >= 1, "household_count must be at least 1"
    assert 0.01 <= float(data["threshold_pct"]) <= 100.00
    assert isinstance(data["required_permit_types"], list)
    assert len(data["required_permit_types"]) >= 1
    assert len(set(data["required_permit_types"])) == len(data["required_permit_types"])
    for permit_type in data["required_permit_types"]:
        assert permit_type in ("ROW", "TRAFFIC_CONTROL", "ENVIRONMENTAL")
    assert 1 <= data["max_concurrent_bury_ops"] <= 10
    assert data["campaign_status"] in (
        "PREREG_OPEN",
        "PREREG_EXTENDED",
        "QUALIFIED",
        "NOT_QUALIFIED",
    )
    assert data["construction_status"] in (
        "NOT_STARTED",
        "SEQUENCED",
        "IN_CONSTRUCTION",
        "SUSPENDED",
        "SERVICE_READY",
    )
    assert is_iso8601_timestamp(data["prereg_deadline_at"])
    assert data["extension_count"] >= 0
    assert data["cumulative_extension_days"] >= 0
    assert data["readiness_posture"] in (
        "BLOCKED",
        "PERMIT_PENDING",
        "POLE_PENDING",
        "SUSPENDED",
        "READY",
    )
    if data["construction_status"] != "SUSPENDED":
        assert data["suspension_reason"] is None, (
            "suspension_reason is null whenever construction_status is not SUSPENDED"
        )
    else:
        assert data["suspension_reason"] in ("MANUAL", "POLE_DENIED", "PERMIT_EXPIRED")
    assert_is_integer_cents(data["make_ready_cost_cents"], "BuildZone.make_ready_cost_cents")
    assert data["outstanding_restoration_count"] >= 0
    assert_two_decimal_places(data["prereg_rate_pct"], "BuildZone.prereg_rate_pct")
    assert data["provisional_qualifying_count"] >= 0


def assert_service_address(data: dict):
    assert_versioned_common_fields(data, "ServiceAddress")
    assert is_valid_uuid(data["build_zone_id"])
    assert isinstance(data["street_address"], str)
    assert 1 <= len(data["street_address"]) <= 160
    assert data["dwelling_type"] in ("SINGLE_FAMILY", "MDU")
    if data["dwelling_type"] == "SINGLE_FAMILY":
        assert data["unit_count"] == 1, "a SINGLE_FAMILY address holds exactly 1 unit"
    else:
        assert data["unit_count"] >= 2, "an MDU address holds at least 2 units"
    assert data["distance_to_node_m"] >= 0
    assert data["serviceability"] in (
        "UNDETERMINED",
        "SERVICEABLE",
        "CONDITIONAL_MDU",
        "NOT_SERVICEABLE",
    )
    assert data["exception_status"] in ("NONE", "REQUESTED", "GRANTED", "DENIED")
    assert isinstance(data["counts_toward_threshold"], bool)
    if data["serviceability"] == "NOT_SERVICEABLE":
        assert data["not_serviceable_reason"] in (
            "NO_ROW_ACCESS",
            "EXCESSIVE_DISTANCE",
            "MDU_AGREEMENT_UNAVAILABLE",
            "BUILD_NOT_QUALIFIED",
        )
    else:
        assert data["not_serviceable_reason"] is None


def assert_account(data: dict):
    assert_versioned_common_fields(data, "Account")
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert "@" in data["email"], "email must contain an at sign"
    assert isinstance(data["phone"], str) and 1 <= len(data["phone"]) <= 32
    assert data["account_type"] in ("RESIDENT", "PROPERTY_OWNER", "BUSINESS")
    assert_is_integer_cents(data["deposit_held_cents"], "Account.deposit_held_cents")
    assert_is_integer_cents(data["credit_balance_cents"], "Account.credit_balance_cents")


def assert_mdu_agreement(data: dict):
    assert_versioned_common_fields(data, "MduOwnerAgreement")
    assert is_valid_uuid(data["service_address_id"])
    assert is_valid_uuid(data["owner_account_id"])
    assert_is_integer_cents(data["access_fee_cents"], "MduOwnerAgreement.access_fee_cents")
    assert data["access_fee_cents"] >= 0
    assert 0 <= data["max_counter_rounds"] <= 5
    assert data["counter_round"] >= 0
    assert data["offer_round"] >= 0
    assert data["status"] in (
        "DRAFT",
        "SENT",
        "COUNTERED",
        "SIGNED",
        "DECLINED",
        "EXPIRED",
    )
    assert is_iso8601_timestamp(data["expires_at"])
    if data["status"] != "SIGNED":
        assert data["signed_at"] is None


def assert_permit_application(data: dict):
    assert_versioned_common_fields(data, "PermitApplication")
    assert is_valid_uuid(data["build_zone_id"])
    assert data["permit_type"] in ("ROW", "TRAFFIC_CONTROL", "ENVIRONMENTAL")
    assert 1 <= data["valid_days"] <= 730
    assert 0 <= data["max_resubmissions"] <= 5
    assert data["submission_round"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "EXPIRED")


def assert_pole_attachment_request(data: dict):
    assert_versioned_common_fields(data, "PoleAttachmentRequest")
    assert is_valid_uuid(data["build_zone_id"])
    assert isinstance(data["utility_owner"], str)
    assert 1 <= len(data["utility_owner"]) <= 120
    assert data["pole_count"] >= 1
    assert data["status"] in ("REQUESTED", "SURVEYED", "ACCEPTED", "ATTACHED", "DENIED")
    assert_is_integer_cents(
        data["make_ready_cost_cents"], "PoleAttachmentRequest.make_ready_cost_cents"
    )
    if data["status"] == "DENIED":
        assert data["denial_reason"] in (
            "INSUFFICIENT_CLEARANCE",
            "SAFETY_VIOLATION",
            "CAPACITY_FULL",
        )


def assert_preorder(data: dict):
    assert_versioned_common_fields(data, "Preorder")
    assert is_valid_uuid(data["build_zone_id"])
    assert is_valid_uuid(data["service_address_id"])
    assert is_valid_uuid(data["account_id"])
    assert data["plan_tier"] in ("BASIC_300", "GIGABIT_1000", "MULTIGIG_2000")
    assert data["preorder_status"] in (
        "PENDING",
        "QUALIFIED",
        "CONVERTED",
        "CANCELLED",
        "LAPSED",
    )
    assert data["deposit_status"] in ("HELD", "REFUNDED", "APPLIED", "FORFEITED")
    assert_is_integer_cents(data["deposit_amount_cents"], "Preorder.deposit_amount_cents")
    if data["drop_method"] is not None:
        assert data["drop_method"] in ("BURY", "AERIAL")


def assert_install_crew(data: dict):
    assert_versioned_common_fields(data, "InstallCrew")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    assert data["crew_type"] in ("BURY", "AERIAL", "RESTORATION")
    assert 0 <= data["travel_buffer_minutes"] <= 240
    assert 60 <= data["daily_capacity_minutes"] <= 1440
    assert data["booked_minutes_total"] >= 0
    assert data["scheduled_appointment_count"] >= 0


def assert_install_appointment(data: dict):
    assert_versioned_common_fields(data, "InstallAppointment")
    assert is_valid_uuid(data["preorder_id"])
    assert is_valid_uuid(data["crew_id"])
    assert data["appointment_type"] in (
        "DROP_BURY",
        "AERIAL_DROP",
        "RESTORATION_FOLLOWUP",
    )
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])
    assert parse_instant(data["window_end_at"]) > parse_instant(data["window_start_at"])
    assert data["occupied_minutes"] >= 30
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert isinstance(data["restoration_required"], bool)
    if data["cancellation_reason"] is not None:
        assert data["cancellation_reason"] in (
            "SUBSCRIBER_REQUEST",
            "CREW_UNAVAILABLE",
            "ZONE_SUSPENDED",
        )


def assert_damage_claim(data: dict):
    assert_versioned_common_fields(data, "DamageClaim")
    assert is_valid_uuid(data["install_appointment_id"])
    assert is_valid_uuid(data["service_address_id"])
    assert is_valid_uuid(data["claimant_account_id"])
    assert data["damage_type"] in ("LAWN", "IRRIGATION", "DRIVEWAY", "UTILITY_LINE")
    assert data["claimed_amount_cents"] >= 1
    assert data["status"] in ("FILED", "UNDER_ASSESSMENT", "PAID", "DENIED")
    assert is_iso8601_timestamp(data["filed_at"])
    assert 0 <= data["max_appeals"] <= 3
    assert data["appeal_count"] >= 0
    if data["assessment_variant"] is not None:
        assert data["assessment_variant"] in (
            "STANDARD_SCHEDULE",
            "LATE_FILING_SCHEDULE",
        )


def assert_fallback_option(data: dict):
    assert_versioned_common_fields(data, "FallbackOption")
    assert is_valid_uuid(data["campaign_id"])
    assert data["technology"] in ("FIXED_WIRELESS", "DSL_PARTNER", "SATELLITE_PARTNER")
    assert data["min_downstream_mbps"] >= 1
    assert_is_integer_cents(
        data["monthly_price_cents"], "FallbackOption.monthly_price_cents"
    )
    assert data["max_serviceable_distance_m"] >= 0
    assert data["priority_rank"] >= 1
    assert isinstance(data["supports_mdu"], bool)
    assert data["option_status"] in ("ENABLED", "DISABLED")


def assert_fallback_offer(data: dict):
    assert_versioned_common_fields(data, "FallbackOffer")
    assert is_valid_uuid(data["service_address_id"])
    assert is_valid_uuid(data["fallback_option_id"])
    assert is_valid_uuid(data["account_id"])
    assert data["technology"] in (
        "FIXED_WIRELESS",
        "DSL_PARTNER",
        "SATELLITE_PARTNER",
    )
    assert data["min_downstream_mbps"] >= 1
    assert_is_integer_cents(
        data["monthly_price_cents"], "FallbackOffer.monthly_price_cents"
    )
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "EXPIRED")
    assert is_iso8601_timestamp(data["offered_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert parse_instant(data["expires_at"]) > parse_instant(data["offered_at"])


def assert_ledger_entry(data: dict):
    """A ledger entry is append-only: it carries no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), "LedgerEntry.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "LedgerEntry.created_at must be an ISO 8601 instant"
    )
    assert "version" not in data, (
        "LedgerEntry carries no version — it is append-only and never mutated"
    )
    assert "updated_at" not in data, (
        "LedgerEntry carries no updated_at — it is append-only and never mutated"
    )
    assert is_valid_uuid(data["account_id"])
    assert data["entry_type"] in (
        "DEPOSIT_HELD",
        "DEPOSIT_REFUNDED",
        "DEPOSIT_APPLIED",
        "DEPOSIT_FORFEITED",
        "CLAIM_PAYOUT",
    )
    assert_is_integer_cents(data["amount_cents"], "LedgerEntry.amount_cents")
    assert is_iso8601_timestamp(data["occurred_at"])
    references = [data.get("preorder_id"), data.get("damage_claim_id")]
    assert sum(1 for ref in references if ref is not None) == 1, (
        "a ledger entry references exactly one of preorder_id or damage_claim_id"
    )


# --- Domain invariants -------------------------------------------------------
def assert_deposit_stream_balances(entries, expected_net: int):
    """Sum a ledger stream's deposit entries and compare with the held balance."""
    deposit_types = (
        "DEPOSIT_HELD",
        "DEPOSIT_REFUNDED",
        "DEPOSIT_APPLIED",
        "DEPOSIT_FORFEITED",
    )
    total = sum(
        entry["amount_cents"] for entry in entries if entry["entry_type"] in deposit_types
    )
    assert total == expected_net, (
        f"deposit stream should net to {expected_net} cents, got {total}"
    )
    return total


def assert_shares_sum_to_pool(shares, pool_total: int):
    """Make-ready shares are integer arithmetic and sum to the pool exactly."""
    for share in shares:
        assert_is_integer_cents(share, "make_ready_share_cents")
    assert sum(shares) == pool_total, (
        f"the shares must sum to {pool_total} cents with zero residue, "
        f"got {sum(shares)} from {shares}"
    )


def assert_crew_load(data: dict, booked_minutes_total: int, scheduled_appointment_count: int):
    assert data["booked_minutes_total"] == booked_minutes_total, (
        f"expected booked_minutes_total {booked_minutes_total}, "
        f"got {data['booked_minutes_total']}"
    )
    assert data["scheduled_appointment_count"] == scheduled_appointment_count, (
        f"expected scheduled_appointment_count {scheduled_appointment_count}, "
        f"got {data['scheduled_appointment_count']}"
    )
