"""Domain assertions for the aviation underwriting API.

These sit on top of the framework's generic envelope validators and add the
entity-shape, envelope-detail and ledger assertions this API needs.
"""

import re

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import canonical_instant
from .constants import POLICY_NUMBER_PREFIX
from .types import JsonDict, ResponseType, TxnType

# ----------------------------------------------------------------------
# Envelope
# ----------------------------------------------------------------------
REQUEST_ID_PATTERN = re.compile(r"^req_[A-Za-z0-9]+$")
META_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
PAGINATION_KEYS = ("limit", "offset", "total_count", "has_more")


def validate_unpaginated(response: requests.Response, expected_status: int = 200) -> JsonDict:
    """Validate a single-resource success response and return its data object.

    A single-resource response declares a `response_type` of "object" and carries
    the resource itself in `data`; the pagination members of `meta` belong to
    list responses only.
    """
    data = validate_success(response, expected_status=expected_status)
    body = response.json()
    assert body["response_type"] == ResponseType.OBJECT, (
        f"single-resource response must declare response_type 'object', "
        f"got '{body['response_type']}'"
    )
    assert isinstance(data, dict), f"data of an object response must be a mapping, got {type(data)}"
    return data


def validate_list(response: requests.Response) -> tuple:
    """Validate a collection response and return its rows and meta object."""
    rows, meta = validate_paginated(response)
    body = response.json()
    assert body["response_type"] == ResponseType.ARRAY, (
        f"collection response must declare response_type 'array', "
        f"got '{body['response_type']}'"
    )
    assert isinstance(rows, list), "data of an array response must be a list"
    return rows, meta


def assert_request_meta(response: requests.Response) -> JsonDict:
    """Assert the server-generated members of `meta` on any response."""
    meta = response.json()["meta"]
    assert REQUEST_ID_PATTERN.match(meta["api_request_id"]), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert META_TIMESTAMP_PATTERN.match(meta["api_request_timestamp"]), (
        "api_request_timestamp must be an ISO 8601 UTC timestamp with three "
        f"fractional digits, got {meta['api_request_timestamp']!r}"
    )
    return meta


def assert_error_meta_has_no_pagination(response: requests.Response) -> None:
    """An error response's `meta` carries only the request id and timestamp."""
    meta = response.json()["meta"]
    for key in PAGINATION_KEYS:
        assert key not in meta, f"error meta must not carry pagination member '{key}'"


# ----------------------------------------------------------------------
# Common resource properties
# ----------------------------------------------------------------------
def assert_common_fields(entity: JsonDict, expected_version: int = None) -> None:
    """Assert the four common properties of a mutable resource."""
    assert is_valid_uuid(entity["id"]), f"id must be a bare UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at must be an ISO 8601 timestamp, got {entity['created_at']!r}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at must be an ISO 8601 timestamp, got {entity['updated_at']!r}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_immutable_common_fields(entity: JsonDict) -> None:
    """Assert the two common properties of an immutable resource.

    An immutable resource carries an `id` and a `created_at` and nothing else
    from the common set: it has no `updated_at` and no `version`.
    """
    assert is_valid_uuid(entity["id"]), f"id must be a bare UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at must be an ISO 8601 timestamp, got {entity['created_at']!r}"
    )
    assert "updated_at" not in entity, "an immutable resource carries no updated_at"
    assert "version" not in entity, "an immutable resource carries no version"


def assert_instants_equal(actual: str, expected: str, label: str = "instant") -> None:
    """Compare two ISO-8601 instants irrespective of sub-second spelling."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_fields_present(entity: JsonDict, field_names) -> None:
    missing = [name for name in field_names if name not in entity]
    assert not missing, f"response is missing declared fields: {missing}"


def assert_field_values(entity: JsonDict, **expected) -> None:
    for name, value in expected.items():
        assert entity[name] == value, (
            f"{name}: expected {value!r}, got {entity.get(name)!r}"
        )


# ----------------------------------------------------------------------
# Declared field sets, one per resource
# ----------------------------------------------------------------------
OPERATOR_FIELDS = (
    "legal_name",
    "operator_type",
    "aoc_number",
    "home_base_icao",
    "policy_count",
)
AIRCRAFT_FIELDS = (
    "registration_mark",
    "aircraft_class",
    "manufacture_year",
    "hull_new_value_cents",
    "seat_count",
    "max_takeoff_weight_kg",
    "current_depreciated_value_cents",
)
PILOT_FIELDS = (
    "pilot_name",
    "license_type",
    "total_logged_hours",
    "hours_on_type",
    "instrument_rated",
    "last_training_completed_at",
    "medical_expires_at",
    "verified_total_hours",
    "verified_hours_on_type",
    "verified_at",
    "qualification_score_logged",
    "qualification_score_verified",
    "rating_band_logged",
    "rating_band_verified",
)
POLICY_FIELDS = (
    "operator_id",
    "policy_number",
    "policy_type",
    "status",
    "effective_from",
    "effective_to",
    "term_days",
    "territorial_limit_code",
    "permitted_use_classes",
    "base_hull_rate_ppm",
    "hull_deductible_ppm",
    "liability_limit_cents",
    "hull_aggregate_limit_cents",
    "premises_liability_extension",
    "product_liability_extension",
    "automatic_acquisition_enabled",
    "acquisition_reporting_days",
    "war_risk_required",
    "total_hull_sum_insured_cents",
    "written_premium_cents",
    "outstanding_reserve_cents",
    "paid_hull_cents",
    "live_schedule_count",
)
SCHEDULE_FIELDS = (
    "policy_id",
    "aircraft_id",
    "named_pilot_id",
    "use_class",
    "agreed_value_cents",
    "effective_from",
    "effective_to",
    "coverage_status",
    "warranty_status",
    "warranty_basis",
    "warranted_min_total_hours",
    "warranted_min_hours_on_type",
    "rated_pilot_band",
    "rate_ppm",
    "hull_premium_cents",
    "acquisition_source",
    "reported_declaration_id",
    "warranty_breach_reason",
)
ENDORSEMENT_FIELDS = (
    "policy_id",
    "endorsement_type",
    "status",
    "effective_date",
    "target_schedule_id",
    "aircraft_id",
    "named_pilot_id",
    "new_agreed_value_cents",
    "new_use_class",
    "territory_code",
    "exposure_member_count",
    "per_seat_limit_cents",
    "quote_round",
    "quoted_premium_delta_cents",
    "premium_delta_cents",
    "quoted_by_user_id",
    "referral_reason",
    "void_reason",
)
WAR_MARKET_FIELDS = (
    "market_name",
    "aggregate_line_cents",
    "perils_offered",
    "committed_line_cents",
    "available_line_cents",
)
WAR_PLACEMENT_FIELDS = (
    "policy_id",
    "market_id",
    "war_hull_line_cents",
    "perils_scope",
    "coverage_from",
    "coverage_to",
    "status",
    "premium_cents",
    "cancellation_reason",
)
CLAIM_FIELDS = (
    "policy_id",
    "schedule_id",
    "loss_date",
    "loss_type",
    "loss_description",
    "adjustment_status",
    "salvage_status",
    "cooperation_status",
    "investigator_reference",
    "reserve_cents",
    "ctl_ratio_ppm",
    "ctl_flag",
    "assessment_count",
    "settlement_basis",
    "settlement_amount_cents",
    "deductible_applied_cents",
    "salvage_proceeds_cents",
    "coverage_decided_by_user_id",
    "denial_reason",
)
DAMAGE_ASSESSMENT_FIELDS = (
    "claim_id",
    "repair_cost_estimate_cents",
    "assessor_reference",
    "assessed_at",
    "ctl_ratio_ppm",
    "verdict",
)
PREMIUM_TRANSACTION_FIELDS = (
    "policy_id",
    "endorsement_id",
    "txn_type",
    "amount_cents",
    "effective_date",
    "basis",
    "memo",
)
FLEET_DECLARATION_FIELDS = (
    "policy_id",
    "period_from",
    "period_to",
    "status",
    "declared_count",
    "declared_premium_cents",
    "late_flag",
    "late_loading_cents",
    "reported_schedule_ids",
    "rejection_reason",
)


# ----------------------------------------------------------------------
# Per-resource shape assertions
# ----------------------------------------------------------------------
def assert_operator_shape(entity: JsonDict) -> None:
    assert_common_fields(entity)
    assert_fields_present(entity, OPERATOR_FIELDS)


def assert_aircraft_shape(entity: JsonDict) -> None:
    assert_common_fields(entity)
    assert_fields_present(entity, AIRCRAFT_FIELDS)


def assert_pilot_shape(entity: JsonDict) -> None:
    assert_common_fields(entity)
    assert_fields_present(entity, PILOT_FIELDS)


def assert_policy_shape(entity: JsonDict) -> None:
    assert_common_fields(entity)
    assert_fields_present(entity, POLICY_FIELDS)
    assert_policy_number_format(entity["policy_number"])


def assert_schedule_shape(entity: JsonDict) -> None:
    assert_common_fields(entity)
    assert_fields_present(entity, SCHEDULE_FIELDS)


def assert_endorsement_shape(entity: JsonDict) -> None:
    assert_common_fields(entity)
    assert_fields_present(entity, ENDORSEMENT_FIELDS)


def assert_war_market_shape(entity: JsonDict) -> None:
    assert_common_fields(entity)
    assert_fields_present(entity, WAR_MARKET_FIELDS)


def assert_war_placement_shape(entity: JsonDict) -> None:
    assert_common_fields(entity)
    assert_fields_present(entity, WAR_PLACEMENT_FIELDS)


def assert_claim_shape(entity: JsonDict) -> None:
    assert_common_fields(entity)
    assert_fields_present(entity, CLAIM_FIELDS)


def assert_damage_assessment_shape(entity: JsonDict) -> None:
    """A damage assessment is immutable, so it carries no version."""
    assert_immutable_common_fields(entity)
    assert_fields_present(entity, DAMAGE_ASSESSMENT_FIELDS)


def assert_premium_transaction_shape(entity: JsonDict) -> None:
    """A ledger row is immutable, so it carries no version."""
    assert_immutable_common_fields(entity)
    assert_fields_present(entity, PREMIUM_TRANSACTION_FIELDS)


def assert_fleet_declaration_shape(entity: JsonDict) -> None:
    assert_common_fields(entity)
    assert_fields_present(entity, FLEET_DECLARATION_FIELDS)


def assert_policy_number_format(policy_number: str) -> None:
    """A policy number is the fixed prefix followed by six zero-padded digits."""
    assert isinstance(policy_number, str), "policy_number must be a string"
    assert policy_number.startswith(POLICY_NUMBER_PREFIX), (
        f"policy_number must start with {POLICY_NUMBER_PREFIX!r}, got {policy_number!r}"
    )
    suffix = policy_number[len(POLICY_NUMBER_PREFIX):]
    assert len(suffix) == 6 and suffix.isdigit(), (
        f"policy_number must carry six zero-padded digits, got {policy_number!r}"
    )


# ----------------------------------------------------------------------
# The premium ledger
# ----------------------------------------------------------------------
def rows_of_type(rows, txn_type: str) -> list:
    """Every ledger row of one transaction type, in the order supplied."""
    return [row for row in rows if row["txn_type"] == txn_type]


def assert_ledger_row(
    row: JsonDict,
    txn_type: str = None,
    amount_cents: int = None,
    basis: str = None,
    endorsement_id: str = None,
    effective_date: str = None,
    policy_id: str = None,
) -> None:
    """Assert the members of one ledger row that a test cares about."""
    assert_premium_transaction_shape(row)
    if txn_type is not None:
        assert row["txn_type"] == txn_type, (
            f"txn_type: expected {txn_type}, got {row['txn_type']}"
        )
    if amount_cents is not None:
        assert row["amount_cents"] == amount_cents, (
            f"amount_cents: expected {amount_cents}, got {row['amount_cents']}"
        )
    if basis is not None:
        assert row["basis"] == basis, f"basis: expected {basis}, got {row['basis']}"
    if endorsement_id is not None:
        assert row["endorsement_id"] == endorsement_id, (
            f"endorsement_id: expected {endorsement_id}, got {row['endorsement_id']}"
        )
    if effective_date is not None:
        assert_instants_equal(row["effective_date"], effective_date, "effective_date")
    if policy_id is not None:
        assert row["policy_id"] == policy_id, (
            f"policy_id: expected {policy_id}, got {row['policy_id']}"
        )


def assert_ledger_txn_types(rows, expected_types) -> None:
    """Assert the exact sequence of transaction types on the ledger."""
    actual = [row["txn_type"] for row in rows]
    assert actual == list(expected_types), (
        f"ledger sequence: expected {list(expected_types)}, got {actual}"
    )


def assert_no_ledger_row_of_type(rows, txn_type: str) -> None:
    matches = rows_of_type(rows, txn_type)
    assert not matches, (
        f"expected no {txn_type} row, found {len(matches)}: "
        f"{[row['amount_cents'] for row in matches]}"
    )


def assert_no_zero_amount_rows(rows) -> None:
    """A ledger row is never written with a zero amount."""
    zeros = [row for row in rows if row["amount_cents"] == 0]
    assert not zeros, f"the ledger must never carry a zero amount row, found {len(zeros)}"


def ledger_signed_sum(rows) -> int:
    """The signed sum of every ledger row supplied."""
    return sum(row["amount_cents"] for row in rows)


def assert_ordered_by_created_at(rows) -> None:
    """Assert a collection came back in created_at ascending order."""
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at ascending order: {stamps}"


def assert_ids_in_order(rows, expected_ids) -> None:
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"expected ids in order {list(expected_ids)}, got {actual}"
    )


__all__ = [name for name in dir() if not name.startswith("_")]
