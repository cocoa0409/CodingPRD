"""Shape and invariant assertions.

Envelope convention: the functions in this module are the only place a response
body is opened. ``validate_success``, ``validate_paginated`` and
``validate_error`` come from the framework and already return the inner ``data``
member, so nothing here unwraps a second time.
"""

import re
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

from prd_bench_local_runner.testing import validate_success

from .constants import (
    BLOCK_FULL_UTILIZATION_BPS,
    CANDIDACY_EVALUATION_FIELDS,
    DOSE_STATES_COUNTED_IN_LEDGER,
    HLD_SHELF_LIFE_HOURS,
)

_CREATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

PAGINATION_META_FIELDS = ("limit", "offset", "total_count", "has_more")


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def validate_unpaginated(
    response: requests.Response, expected_status: int = 200
) -> Any:
    """Validate a success envelope that carries no pagination metadata.

    PRD 2.3 restricts ``limit``, ``offset``, ``total_count`` and ``has_more`` to
    list endpoints; a single-resource read, an action response, a projection such
    as the candidacy evaluation, and the clock setter must all omit them. This is
    the counterpart to the framework's ``validate_paginated`` and returns the
    inner ``data`` member exactly once.
    """
    data = validate_success(response, expected_status)
    meta = response.json()["meta"]
    for field in PAGINATION_META_FIELDS:
        assert field not in meta, (
            "a response that is not a list must omit meta.{0}, got {1!r}".format(
                field, meta.get(field)
            )
        )
    return data


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    """Assert the four pagination fields of PRD 2.3 exactly."""
    assert meta["limit"] == limit, "limit: expected {0}, got {1}".format(limit, meta["limit"])
    assert meta["offset"] == offset, "offset: expected {0}, got {1}".format(
        offset, meta["offset"]
    )
    assert meta["total_count"] == total_count, "total_count: expected {0}, got {1}".format(
        total_count, meta["total_count"]
    )
    assert meta["has_more"] is has_more, "has_more: expected {0}, got {1}".format(
        has_more, meta["has_more"]
    )


def assert_request_meta(response: requests.Response) -> None:
    """Assert the two correlation fields every envelope carries (PRD 2.2)."""
    meta = response.json()["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        "api_request_id must start with 'req_', got {0!r}".format(meta["api_request_id"])
    )
    assert_created_at_format(meta["api_request_timestamp"])


# ---------------------------------------------------------------------------
# Scalar format helpers
# ---------------------------------------------------------------------------
def assert_created_at_format(value: str) -> None:
    """PRD 2.4: an ISO 8601 UTC instant with exactly three fractional digits."""
    assert isinstance(value, str), "expected a timestamp string, got {0!r}".format(value)
    assert _CREATED_AT_RE.match(value), (
        "expected an ISO 8601 UTC instant with exactly three fractional digits, "
        "got {0!r}".format(value)
    )


def assert_calendar_date(value: str) -> None:
    """PRD 2.5: a calendar date carries no time of day."""
    assert isinstance(value, str), "expected a date string, got {0!r}".format(value)
    assert _DATE_RE.match(value), "expected YYYY-MM-DD, got {0!r}".format(value)


def assert_plain_uuid(value: str) -> None:
    """PRD 2.4: an identifier is a plain UUID string with no prefix."""
    assert isinstance(value, str), "expected a UUID string, got {0!r}".format(value)
    assert _UUID_RE.match(value), "expected a plain UUID, got {0!r}".format(value)


def parse_instant(value: str) -> datetime:
    """Parse any ISO 8601 UTC instant the service may emit."""
    assert isinstance(value, str), "expected an instant string, got {0!r}".format(value)
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def assert_instant_equals(actual: Any, expected: str) -> None:
    """Compare two instants by the moment they denote, not by their spelling."""
    assert actual is not None, "expected instant {0!r}, got null".format(expected)
    assert parse_instant(actual) == parse_instant(expected), (
        "expected instant {0!r}, got {1!r}".format(expected, actual)
    )


def assert_money_cents(value: Any) -> None:
    """PRD 2.6: money is an integer number of cents, never a string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        "money must be an integer number of cents, got {0!r}".format(value)
    )


def assert_volume_ml(actual: Any, expected: float) -> None:
    """PRD 2.6: a volume carries exactly two decimals."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        "expected a numeric volume, got {0!r}".format(actual)
    )
    assert quantise_ml(actual) == quantise_ml(expected), (
        "expected volume {0:.2f} mL, got {1!r}".format(expected, actual)
    )


def quantise_ml(value: float) -> Decimal:
    """Round a millilitre figure to the two decimals PRD 2.6 declares."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_half_up(value: Decimal) -> int:
    """PRD 2.6: a fractional cent rounds half up to the nearest whole cent."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def assert_fields(data: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Assert a batch of exact field values with one readable message each."""
    for field, want in expected.items():
        assert field in data, "field {0!r} is absent from {1!r}".format(field, sorted(data))
        got = data[field]
        if isinstance(want, bool) or want is None:
            assert got is want, "{0}: expected {1!r}, got {2!r}".format(field, want, got)
        else:
            assert got == want, "{0}: expected {1!r}, got {2!r}".format(field, want, got)


def assert_absent(data: Dict[str, Any], fields: Iterable[str]) -> None:
    """Assert that none of ``fields`` appears in a resource body."""
    for field in fields:
        assert field not in data, "field {0!r} must not be present".format(field)


# ---------------------------------------------------------------------------
# Common resource shape (PRD 2.4)
# ---------------------------------------------------------------------------
def assert_mutable_resource(data: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Assert the identity and mutation trio carried by twelve resources."""
    assert_plain_uuid(data["id"])
    assert_created_at_format(data["created_at"])
    assert_created_at_format(data["updated_at"])
    assert isinstance(data["version"], int) and not isinstance(data["version"], bool)
    assert data["version"] >= 1, "version starts at 1, got {0!r}".format(data["version"])
    if expected_version is not None:
        assert data["version"] == expected_version, (
            "version: expected {0}, got {1}".format(expected_version, data["version"])
        )


def assert_immutable_resource(data: Dict[str, Any]) -> None:
    """Assert the shape of a resource that carries no ``updated_at`` or ``version``."""
    assert_plain_uuid(data["id"])
    assert_created_at_format(data["created_at"])
    assert_absent(data, ("updated_at", "version"))


# ---------------------------------------------------------------------------
# Per-resource shape assertions
# ---------------------------------------------------------------------------
def assert_payer_policy(data: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_resource(data)
    for field in (
        "payer_name",
        "plan_code",
        "requires_prior_auth",
        "min_medical_management_days",
        "requires_ct_within_months",
        "min_documented_criteria",
        "max_balloon_devices",
        "covered_pct_bps",
        "allergy_serum_covered",
        "observation_floor_minutes",
        "device_trial_days",
        "restock_fee_bps",
        "restock_fee_floor_cents",
        "auth_validity_days",
        "appliance_covered",
    ):
        assert field in data, "payer policy is missing {0!r}".format(field)
    assert_money_cents(data["restock_fee_floor_cents"])
    assert_fields(data, expected)


def assert_patient(data: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_resource(data)
    for field in (
        "payer_policy_id",
        "mrn",
        "full_name",
        "date_of_birth",
        "age_months",
        "antihistamine_last_dose_at",
        "epinephrine_on_file",
        "dermatographism",
        "prior_systemic_reaction_count",
        "sensitized_antigen_count",
        "risk_score",
        "risk_score_variant",
        "supervision_tier",
        "immunotherapy_escalation_step",
        "immunotherapy_status",
        "last_dose_administered_at",
    ):
        assert field in data, "patient is missing {0!r}".format(field)
    assert_calendar_date(data["date_of_birth"])
    assert 0 <= data["risk_score"] <= 100, (
        "risk_score is clamped to 0..100, got {0!r}".format(data["risk_score"])
    )
    assert_fields(data, expected)


def assert_allergy_test_order(data: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_resource(data)
    for field in (
        "patient_id",
        "panel_code",
        "method",
        "status",
        "antigen_count",
        "billed_units",
        "practice_charge_cents",
        "patient_responsibility_cents",
        "observation_required_minutes",
        "ordered_by_user_id",
        "administered_by_user_id",
        "administered_at",
        "positive_antigen_count",
        "worst_systemic_grade",
        "abort_reason",
    ):
        assert field in data, "allergy test order is missing {0!r}".format(field)
    assert_money_cents(data["practice_charge_cents"])
    assert_money_cents(data["patient_responsibility_cents"])
    assert_fields(data, expected)


def assert_reaction_event(data: Dict[str, Any], **expected: Any) -> None:
    assert_immutable_resource(data)
    for field in (
        "allergy_test_order_id",
        "immunotherapy_dose_id",
        "systemic_grade",
        "local_wheal_mm",
        "onset_minutes",
        "epinephrine_given",
        "recorded_by_user_id",
        "occurred_at",
    ):
        assert field in data, "reaction event is missing {0!r}".format(field)
    parents = [data["allergy_test_order_id"], data["immunotherapy_dose_id"]]
    assert len([p for p in parents if p is not None]) == 1, (
        "a reaction event resolves to exactly one parent, got {0!r}".format(parents)
    )
    assert_fields(data, expected)


def assert_immunotherapy_vial(data: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_resource(data)
    for field in (
        "patient_id",
        "supply_lot_id",
        "dilution_code",
        "label_text",
        "volume_ml_initial",
        "volume_ml_remaining",
        "volume_ml_dispensed_total",
        "volume_ml_wasted",
        "expires_at",
        "status",
        "mixed_by_user_id",
        "verified_by_user_id",
        "requires_supervised_administration",
        "discard_reason",
    ):
        assert field in data, "immunotherapy vial is missing {0!r}".format(field)
    assert_vial_volume_ledger(data)
    assert_fields(data, expected)


def assert_immunotherapy_dose(data: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_resource(data)
    for field in (
        "immunotherapy_vial_id",
        "escalation_step_at_dose",
        "volume_ml",
        "observation_required_minutes",
        "administered_at",
        "administered_by_user_id",
        "supervising_user_id",
        "observation_cleared_at",
        "status",
        "reaction_grade",
        "gap_days_at_dose",
    ):
        assert field in data, "immunotherapy dose is missing {0!r}".format(field)
    assert_fields(data, expected)


def assert_sinuplasty_case(data: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_resource(data)
    for field in (
        "patient_id",
        "laterality",
        "sinuses",
        "planned_device_count",
        "ct_study_date",
        "documented_therapies",
        "documented_criteria_codes",
        "evaluation_variant",
        "criteria_met_count",
        "contiguous_management_days",
        "cumulative_management_days",
        "candidacy_status",
        "status",
        "revision_round",
        "submitted_by_user_id",
        "pinned_policy_version",
        "authorized_device_count",
        "auth_expires_at",
        "payer_reference",
        "documented_by_user_id",
    ):
        assert field in data, "sinuplasty case is missing {0!r}".format(field)
    assert_fields(data, expected)


def assert_diagnostic_study(data: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_resource(data)
    for field in (
        "patient_id",
        "study_type",
        "status",
        "pta_db_hl",
        "word_recognition_pct",
        "ahi",
        "recommendation",
        "performed_at",
        "performed_by_user_id",
        "interpreted_by_user_id",
        "superseded_dispense_count",
    ):
        assert field in data, "diagnostic study is missing {0!r}".format(field)
    assert_fields(data, expected)


def assert_device_dispense(data: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_resource(data)
    for field in (
        "diagnostic_study_id",
        "supply_lot_id",
        "device_type",
        "device_serial",
        "ear",
        "price_cents",
        "dispensed_at",
        "trial_end_at",
        "fit_status",
        "billing_status",
        "adjustment_count",
        "days_used",
        "refund_variant",
        "restock_fee_cents",
        "refund_cents",
        "dispensed_by_user_id",
        "settled_by_user_id",
    ):
        assert field in data, "device dispense is missing {0!r}".format(field)
    assert_money_cents(data["price_cents"])
    assert_money_cents(data["restock_fee_cents"])
    assert_money_cents(data["refund_cents"])
    assert_fields(data, expected)


def assert_endoscope(data: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_resource(data)
    for field in (
        "serial_number",
        "model",
        "status",
        "cycle_count",
        "last_reprocessed_at",
        "hld_expires_at",
        "mec_test_due",
        "consecutive_mec_failures",
        "reprocessing_started_by_user_id",
        "last_used_by_user_id",
    ):
        assert field in data, "endoscope is missing {0!r}".format(field)
    assert_fields(data, expected)


def assert_supply_lot(data: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_resource(data)
    for field in (
        "item_type",
        "lot_number",
        "quantity_received",
        "quantity_on_hand",
        "quantity_reserved",
        "quantity_consumed",
        "quantity_wasted",
        "available_quantity",
        "expires_at",
        "status",
    ):
        assert field in data, "supply lot is missing {0!r}".format(field)
    assert_lot_quantity_ledger(data)
    assert_fields(data, expected)


def assert_surgery_center_block(data: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_resource(data)
    for field in (
        "center_name",
        "block_start_at",
        "block_end_at",
        "max_concurrent_cases",
        "overnight_capable",
        "booked_case_count",
        "booked_minutes",
        "capacity_minutes",
        "utilization_bps",
        "status",
    ):
        assert field in data, "surgery-center block is missing {0!r}".format(field)
    assert_block_utilization(data)
    assert_fields(data, expected)


def assert_procedure_booking(data: Dict[str, Any], **expected: Any) -> None:
    assert_mutable_resource(data)
    for field in (
        "patient_id",
        "sinuplasty_case_id",
        "endoscope_asset_id",
        "surgery_center_block_id",
        "supply_lot_id",
        "procedure_type",
        "venue",
        "start_at",
        "end_at",
        "duration_minutes",
        "physician_user_id",
        "planned_device_count",
        "devices_used_count",
        "overnight_observation_required",
        "requires_physician_presence",
        "attending_physician_user_id",
        "scope_reassignment_required",
        "supply_shortfall_flag",
        "status",
        "cancel_reason",
    ):
        assert field in data, "procedure booking is missing {0!r}".format(field)
    assert_fields(data, expected)


def assert_candidacy_evaluation(data: Dict[str, Any], **expected: Any) -> None:
    """PRD 3.6: the projection carries exactly nine fields and nothing else."""
    assert set(data) == set(CANDIDACY_EVALUATION_FIELDS), (
        "the candidacy evaluation carries exactly nine fields; expected {0!r}, "
        "got {1!r}".format(sorted(CANDIDACY_EVALUATION_FIELDS), sorted(data))
    )
    assert_fields(data, expected)


# ---------------------------------------------------------------------------
# Conserved ledgers and derived aggregates (PRD 2.10, 3.9)
# ---------------------------------------------------------------------------
def assert_vial_volume_ledger(vial: Dict[str, Any]) -> None:
    """PRD 2.10: initial == remaining + dispensed_total + wasted, always."""
    total = (
        quantise_ml(vial["volume_ml_remaining"])
        + quantise_ml(vial["volume_ml_dispensed_total"])
        + quantise_ml(vial["volume_ml_wasted"])
    )
    assert quantise_ml(vial["volume_ml_initial"]) == total, (
        "vial ledger broken: initial {0} != remaining {1} + dispensed {2} + wasted "
        "{3}".format(
            vial["volume_ml_initial"],
            vial["volume_ml_remaining"],
            vial["volume_ml_dispensed_total"],
            vial["volume_ml_wasted"],
        )
    )


def assert_lot_quantity_ledger(lot: Dict[str, Any]) -> None:
    """PRD 2.10: received == on_hand + consumed + wasted, and availability never
    falls below zero."""
    total = lot["quantity_on_hand"] + lot["quantity_consumed"] + lot["quantity_wasted"]
    assert lot["quantity_received"] == total, (
        "lot ledger broken: received {0} != on_hand {1} + consumed {2} + wasted "
        "{3}".format(
            lot["quantity_received"],
            lot["quantity_on_hand"],
            lot["quantity_consumed"],
            lot["quantity_wasted"],
        )
    )
    assert lot["available_quantity"] == lot["quantity_on_hand"] - lot["quantity_reserved"], (
        "available_quantity must be on_hand {0} minus reserved {1}, got {2}".format(
            lot["quantity_on_hand"], lot["quantity_reserved"], lot["available_quantity"]
        )
    )
    assert lot["available_quantity"] >= 0, (
        "available_quantity may never be negative, got {0}".format(lot["available_quantity"])
    )


def assert_block_utilization(block: Dict[str, Any]) -> None:
    """PRD 3.9: utilization is booked minutes over capacity minutes in basis
    points, rounded half up, and zero when capacity is zero."""
    capacity = block["capacity_minutes"]
    if capacity == 0:
        expected = 0
    else:
        expected = round_half_up(
            Decimal(block["booked_minutes"]) * Decimal(BLOCK_FULL_UTILIZATION_BPS)
            / Decimal(capacity)
        )
    assert block["utilization_bps"] == expected, (
        "utilization_bps: expected {0} from {1} booked over {2} capacity, got "
        "{3}".format(expected, block["booked_minutes"], capacity, block["utilization_bps"])
    )


def assert_hld_window(scope: Dict[str, Any]) -> None:
    """PRD 3.8: ``hld_expires_at`` sits one hundred sixty-eight hours after the
    last reprocessing instant."""
    if scope["last_reprocessed_at"] is None:
        assert scope["hld_expires_at"] is None, (
            "a scope with no reprocessing instant carries no shelf-life expiry"
        )
        return
    expected = parse_instant(scope["last_reprocessed_at"]) + timedelta(
        hours=HLD_SHELF_LIFE_HOURS
    )
    assert parse_instant(scope["hld_expires_at"]) == expected, (
        "hld_expires_at: expected {0}, got {1}".format(
            expected.isoformat(), scope["hld_expires_at"]
        )
    )


def assert_dose_volumes_sum_to_dispensed(
    doses: List[Dict[str, Any]], vial: Dict[str, Any]
) -> None:
    """PRD 2.10: dispensed_total is the sum of the volumes of the doses in
    ADMINISTERED, CLEARED or REACTION_HELD; a voided dose is excluded."""
    total = Decimal("0.00")
    for dose in doses:
        if dose["status"] in DOSE_STATES_COUNTED_IN_LEDGER:
            total += quantise_ml(dose["volume_ml"])
    assert quantise_ml(vial["volume_ml_dispensed_total"]) == total, (
        "volume_ml_dispensed_total: expected {0}, got {1}".format(
            total, vial["volume_ml_dispensed_total"]
        )
    )


def ids_in_order(rows: List[Dict[str, Any]]) -> List[str]:
    """The identifiers of a list page, in the order the service returned them."""
    return [row["id"] for row in rows]


def assert_ascending_created_at(rows: List[Dict[str, Any]]) -> None:
    """PRD 2.3: every list is ordered by ``created_at`` ascending."""
    stamps = [parse_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "a list page must be ordered by created_at ascending"


def sum_of(rows: List[Dict[str, Any]], field: str) -> int:
    """Total an integer field across a list page."""
    return sum(row[field] for row in rows)


def find_by_id(rows: List[Dict[str, Any]], row_id: str) -> Dict[str, Any]:
    """Pick one row out of a list page by identifier."""
    for row in rows:
        if row["id"] == row_id:
            return row
    raise AssertionError("row {0!r} is absent from the page".format(row_id))


def split_page(page: Tuple[List[Dict[str, Any]], Dict[str, Any]]) -> Tuple[
    List[Dict[str, Any]], Dict[str, Any]
]:
    """Readability shim over the framework's ``(rows, meta)`` pair."""
    rows, meta = page
    return rows, meta
