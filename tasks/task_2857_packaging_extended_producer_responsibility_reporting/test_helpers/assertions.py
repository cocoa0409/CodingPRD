"""Entity-shape assertions and domain invariant checkers.

Timestamps are compared through canonical_instant() so that an instant written
as `2026-10-01T00:00:00Z` and one written with the PRD's three fractional digits
compare equal; the PRD fixes the stored format but the tests are interested in
the instant, not in its sub-second width.
"""

import math
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    ADMIN_TIER_BREAK_CENTS,
    MEMBERSHIP_FREE_TONNAGE_KG,
    MEMBERSHIP_SURCHARGE_PER_1000KG_CENTS,
    NET_PCT_CEILING,
    NET_PCT_FLOOR,
    PCR_BONUS_CAP_PCT,
    PCR_BONUS_STEP_PCT,
    REUSE_BONUS_PCT,
)

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$"
)

WEIGHT_TOLERANCE = 0.0005
EXACT_CENTS_TOLERANCE = 0.00005


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to whole-second precision plus millis."""
    if value is None:
        return None
    match = _INSTANT_RE.match(value)
    assert match, f"Not an ISO 8601 UTC instant: {value!r}"
    year, month, day, hour, minute, second, frac, _zone = match.groups()
    millis = (frac or "0").ljust(3, "0")[:3]
    return f"{year}-{month}-{day}T{hour}:{minute}:{second}.{millis}Z"


def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Compare two instants irrespective of how many fractional digits they carry."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_common_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource carries id, created_at, updated_at and version (PRD 2.4)."""
    assert is_valid_uuid(entity["id"]), f"id must be a bare UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_stored_timestamp_precision(value: str) -> None:
    """The PRD renders instants in UTC with exactly three fractional digits."""
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", value), (
        f"expected an ISO 8601 UTC instant with three fractional digits, got {value!r}"
    )


def assert_weight(actual: Any, expected: float, label: str = "weight_kg") -> None:
    """Weights are carried at three decimal places."""
    assert actual == pytest.approx(expected, abs=WEIGHT_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_exact_cents(actual: Any, expected: float, label: str = "exact_cents") -> None:
    """Exact fee figures are carried at four decimal places."""
    assert actual == pytest.approx(expected, abs=EXACT_CENTS_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_cents(actual: Any, expected: int, label: str = "cents") -> None:
    """Whole-cent money is an integer, never a string."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer count of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def _match_expected(entity: Dict[str, Any], expected: Dict[str, Any], entity_label: str) -> None:
    for field, want in expected.items():
        assert field in entity, f"{entity_label} is missing {field!r}"
        got = entity[field]
        if isinstance(want, float):
            assert got == pytest.approx(want, abs=WEIGHT_TOLERANCE), (
                f"{entity_label}.{field}: expected {want}, got {got}"
            )
        else:
            assert got == want, f"{entity_label}.{field}: expected {want!r}, got {got!r}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_producer(producer: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(producer)
    for field in (
        "legal_name",
        "brand_owner_flag",
        "importer_of_record_flag",
        "domestic_licensor_flag",
        "annual_gross_revenue_usd",
        "contact_email",
        "status",
        "obligated_party_role",
        "annual_packaging_weight_kg",
        "determination_stale",
        "assessed_fee_balance_cents",
    ):
        assert field in producer, f"Producer is missing {field!r}"
    _match_expected(producer, expected, "Producer")


def assert_sku(sku: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(sku)
    for field in (
        "producer_id",
        "gtin",
        "name",
        "product_category",
        "units_sold_annual_estimate",
        "components",
        "unit_packaging_weight_grams",
        "status",
        "revision_count",
    ):
        assert field in sku, f"Sku is missing {field!r}"
    assert isinstance(sku["components"], list)
    _match_expected(sku, expected, "Sku")


def assert_state_program(program: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(program)
    for field in (
        "state_code",
        "obligation_basis",
        "eco_mod_policy",
        "fee_rounding_order",
        "small_producer_revenue_threshold_usd",
        "small_producer_tonnage_threshold_kg",
        "exempt_product_categories",
        "verification_required_threshold_kg",
        "registration_deadline",
    ):
        assert field in program, f"StateProgram is missing {field!r}"
    _match_expected(program, expected, "StateProgram")


def assert_reporting_period(period: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(period)
    for field in (
        "state_program_id",
        "period_label",
        "data_start",
        "data_end",
        "submission_open",
        "submission_deadline",
        "correction_window_days",
    ):
        assert field in period, f"ReportingPeriod is missing {field!r}"
    _match_expected(period, expected, "ReportingPeriod")


def assert_pro(pro: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(pro)
    for field in ("name", "contact_email"):
        assert field in pro, f"Pro is missing {field!r}"
    _match_expected(pro, expected, "Pro")


def assert_fee_schedule(schedule: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(schedule)
    for field in (
        "pro_id",
        "state_program_id",
        "effective_from",
        "effective_to",
        "membership_fee_cents",
        "admin_fee_bps_low",
        "admin_fee_bps_high",
        "material_rates",
        "status",
    ):
        assert field in schedule, f"FeeSchedule is missing {field!r}"
    assert isinstance(schedule["material_rates"], list)
    _match_expected(schedule, expected, "FeeSchedule")


def assert_registration(registration: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(registration)
    for field in (
        "producer_id",
        "state_program_id",
        "status",
        "exemption_status",
        "exemption_basis_applied",
        "assessed_group_revenue_usd",
        "assessed_group_weight_kg",
        "reported_weight_kg_ytd",
        "compliance_posture",
        "suspension_reason",
        "submitted_at",
    ):
        assert field in registration, f"Registration is missing {field!r}"
    _match_expected(registration, expected, "Registration")


def assert_membership(membership: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(membership)
    for field in (
        "registration_id",
        "pro_id",
        "fee_schedule_id",
        "status",
        "membership_fee_cents",
        "fee_payment_status",
        "fee_schedule_version_pinned",
        "decision_reason",
    ):
        assert field in membership, f"Membership is missing {field!r}"
    _match_expected(membership, expected, "Membership")


def assert_report(report: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(report)
    for field in (
        "registration_id",
        "reporting_period_id",
        "submission_status",
        "fee_status",
        "total_weight_kg",
        "fee_basis_weight_kg",
        "tier_basis_kg",
        "fee_subtotal_cents",
        "fee_variant_applied",
        "verification_required",
        "correction_round",
        "correction_due_at",
        "submitted_by_user_id",
        "line_count",
    ):
        assert field in report, f"PackagingReport is missing {field!r}"
    _match_expected(report, expected, "PackagingReport")


def assert_report_line(line: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(line)
    for field in (
        "packaging_report_id",
        "sku_id",
        "units_sold",
        "line_weight_kg",
        "fee_exempt",
        "line_fee_exact_cents",
        "line_fee_cents",
        "eco_mod_detail",
    ):
        assert field in line, f"ReportLine is missing {field!r}"
    assert isinstance(line["eco_mod_detail"], list)
    _match_expected(line, expected, "ReportLine")


def assert_engagement(engagement: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(engagement)
    for field in (
        "packaging_report_id",
        "verifier_user_id",
        "assigned_by_user_id",
        "fieldwork_start",
        "fieldwork_end",
        "status",
        "opinion",
        "findings_note",
        "round_index",
        "opinion_issued_at",
    ):
        assert field in engagement, f"VerificationEngagement is missing {field!r}"
    _match_expected(engagement, expected, "VerificationEngagement")


def assert_invoice(invoice: Dict[str, Any], **expected: Any) -> None:
    assert_common_fields(invoice)
    for field in (
        "packaging_report_id",
        "membership_id",
        "fee_subtotal_cents",
        "admin_fee_bps_applied",
        "admin_fee_cents",
        "total_cents",
        "status",
        "void_reason",
    ):
        assert field in invoice, f"Invoice is missing {field!r}"
    _match_expected(invoice, expected, "Invoice")


# ---------------------------------------------------------------------------
# Domain invariant helpers, each a direct transcription of a PRD formula
# ---------------------------------------------------------------------------
def round_half_up(value: float, places: int) -> float:
    """Round half up to the given number of decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def expected_surcharge_units(annual_packaging_weight_kg: float) -> int:
    """max(0, ceil((weight - 500) / 1000)) — PRD 3.6."""
    remainder = annual_packaging_weight_kg - MEMBERSHIP_FREE_TONNAGE_KG
    if remainder <= 0:
        return 0
    return int(math.ceil(remainder / 1000))


def expected_membership_fee_cents(
    schedule_membership_fee_cents: int, annual_packaging_weight_kg: float
) -> int:
    """The flat schedule fee plus fifty thousand cents per surcharge unit."""
    units = expected_surcharge_units(annual_packaging_weight_kg)
    return schedule_membership_fee_cents + units * MEMBERSHIP_SURCHARGE_PER_1000KG_CENTS


def expected_pcr_bonus_pct(pcr_content_pct: int) -> int:
    """floor(pcr / 10) * 5, capped at 25 — PRD 3.8."""
    return min(PCR_BONUS_CAP_PCT, (pcr_content_pct // 10) * PCR_BONUS_STEP_PCT)


def expected_net_pct(
    malus_pct: int, pcr_content_pct: int, is_reusable: bool, eco_mod_policy: str
) -> int:
    """The pinned eco-modulation order: bonuses, subtraction, clamp, then policy."""
    bonus = expected_pcr_bonus_pct(pcr_content_pct) + (REUSE_BONUS_PCT if is_reusable else 0)
    net = malus_pct - bonus
    net = max(NET_PCT_FLOOR, min(NET_PCT_CEILING, net))
    if eco_mod_policy == "DISCOUNT_ONLY" and net > 0:
        net = 0
    return net


def expected_admin_fee_cents(
    fee_subtotal_cents: int, admin_fee_bps_low: int, admin_fee_bps_high: int
) -> int:
    """The bracket is keyed on the subtotal against forty thousand cents — PRD 3.9."""
    bps = admin_fee_bps_low if fee_subtotal_cents < ADMIN_TIER_BREAK_CENTS else admin_fee_bps_high
    return int(round_half_up(fee_subtotal_cents * bps / 10000, 0))


def expected_admin_fee_bps(
    fee_subtotal_cents: int, admin_fee_bps_low: int, admin_fee_bps_high: int
) -> int:
    return admin_fee_bps_low if fee_subtotal_cents < ADMIN_TIER_BREAK_CENTS else admin_fee_bps_high


def assert_invoice_arithmetic(
    invoice: Dict[str, Any], admin_fee_bps_low: int, admin_fee_bps_high: int
) -> None:
    """The invoice's own three money fields must reconcile with each other."""
    subtotal = invoice["fee_subtotal_cents"]
    expected_bps = expected_admin_fee_bps(subtotal, admin_fee_bps_low, admin_fee_bps_high)
    assert invoice["admin_fee_bps_applied"] == expected_bps, (
        f"admin_fee_bps_applied: expected {expected_bps} for a subtotal of {subtotal}, "
        f"got {invoice['admin_fee_bps_applied']}"
    )
    expected_admin = expected_admin_fee_cents(subtotal, admin_fee_bps_low, admin_fee_bps_high)
    assert_cents(invoice["admin_fee_cents"], expected_admin, "admin_fee_cents")
    assert_cents(invoice["total_cents"], subtotal + expected_admin, "total_cents")


def assert_eco_mod_row(
    row: Dict[str, Any],
    material_type: Optional[str] = None,
    comp_weight_kg: Optional[float] = None,
    rate_cents_per_kg: Optional[int] = None,
    net_pct: Optional[int] = None,
) -> None:
    """One eco-modulation audit row of a priced report line."""
    if material_type is not None:
        assert row["material_type"] == material_type
    if comp_weight_kg is not None:
        assert_weight(row["comp_weight_kg"], comp_weight_kg, "comp_weight_kg")
    if rate_cents_per_kg is not None:
        assert row["rate_cents_per_kg"] == rate_cents_per_kg
    if net_pct is not None:
        assert row["net_pct"] == net_pct, (
            f"net_pct: expected {net_pct}, got {row['net_pct']}"
        )


def assert_report_line_totals_match_report(report: Dict[str, Any], lines: list) -> None:
    """total_weight_kg spans all lines; fee_basis_weight_kg only the non-exempt ones."""
    total = round_half_up(sum(line["line_weight_kg"] for line in lines), 3)
    basis = round_half_up(
        sum(line["line_weight_kg"] for line in lines if not line["fee_exempt"]), 3
    )
    assert_weight(report["total_weight_kg"], total, "total_weight_kg")
    assert_weight(report["fee_basis_weight_kg"], basis, "fee_basis_weight_kg")
    assert report["line_count"] == len(lines)


def assert_no_version_movement(before: Dict[str, Any], after: Dict[str, Any], label: str = "row") -> None:
    """A rejected or non-mutating call moves neither the version nor updated_at."""
    assert before["version"] == after["version"], (
        f"{label}.version moved from {before['version']} to {after['version']}"
    )
    assert_instant_equals(after["updated_at"], before["updated_at"], f"{label}.updated_at")
