"""Entity assertions, instant helpers and domain invariant checkers.

All timestamp comparisons go through canonical_instant(), so a server that renders
"2026-08-01T00:00:00Z" and one that renders "2026-08-01T00:00:00.000Z" both compare
equal — sub-second width is not a contract difference the PRD pins for equality.
"""
import calendar
import math
import re
from datetime import datetime, timedelta, timezone

import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

_PERIOD_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


# ─── Instant helpers ──────────────────────────────────────────────────────

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant (with or without fractional digits)."""
    assert isinstance(value, str) and value, f"Not an instant: {value!r}"
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def format_instant(moment: datetime) -> str:
    """Render an instant as an ISO 8601 UTC instant with exactly three fractional digits."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{moment.microsecond // 1000:03d}Z"
    )


def canonical_instant(value: str) -> str:
    """Normalise an instant to millisecond precision for equality comparison."""
    return format_instant(parse_instant(value))


def assert_instant_equals(actual: str, expected: str, label: str = "instant") -> None:
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def iso_add_days(value: str, days: int) -> str:
    """Advance an instant by a whole number of calendar days."""
    return format_instant(parse_instant(value) + timedelta(days=days))


def iso_add_months(value: str, months: int) -> str:
    """Advance an instant by whole months, clamping the day to the target month's length."""
    moment = parse_instant(value)
    total = moment.month - 1 + months
    year = moment.year + total // 12
    month = total % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return format_instant(moment.replace(year=year, month=month, day=day))


def whole_days_between(start: str, end: str) -> int:
    """Whole days from `start` to `end`, taken toward negative infinity."""
    delta = parse_instant(end) - parse_instant(start)
    return math.floor(delta.total_seconds() / 86400.0)


def period_of(value: str) -> str:
    """The YYYY-MM period an instant falls in."""
    moment = parse_instant(value)
    return f"{moment.year:04d}-{moment.month:02d}"


# ─── Generic field assertions ─────────────────────────────────────────────

def assert_money(value, label="amount") -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {type(value).__name__}: {value!r}"
    )
    assert_cost_precision(float(value))


def assert_identity_and_audit_fields(data: dict, entity: str = "resource") -> None:
    """Every minted resource carries a UUID `id` and an ISO 8601 `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC instant: {data.get('created_at')!r}"
    )


def assert_versioned_fields(data: dict, entity: str = "resource") -> None:
    """Resources other than published index readings also carry updated_at and version."""
    assert_identity_and_audit_fields(data, entity)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC instant: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


# ─── Per-entity assertions ────────────────────────────────────────────────

def assert_project(data: dict) -> None:
    assert_versioned_fields(data, "Project")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 200
    assert isinstance(data["contract_number"], str) and 1 <= len(data["contract_number"]) <= 40
    assert isinstance(data["owner_name"], str)
    assert is_iso8601_timestamp(data["schedule_data_date"])
    for money_field in (
        "escalation_contingency_budget",
        "estimated_total_cost",
        "committed_total_cost",
        "buyout_variance",
        "bought_out_variance",
        "escalation_contingency_committed",
        "escalation_contingency_remaining",
        "change_order_recovered_amount",
    ):
        assert money_field in data, f"Project must report {money_field}"
        assert_money(data[money_field], f"Project.{money_field}")
    assert data["escalation_contingency_budget"] > 0


def assert_material_package(data: dict) -> None:
    assert_versioned_fields(data, "MaterialPackage")
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["scope_code"], str) and 1 <= len(data["scope_code"]) <= 40
    assert data["commodity_index_code"] in (
        "PPI_STEEL_MILL",
        "PPI_COPPER_WIRE",
        "PPI_LUMBER",
        "PPI_CEMENT",
        "PPI_SWITCHGEAR",
    )
    assert_money(data["estimated_cost"], "MaterialPackage.estimated_cost")
    assert_money(data["baseline_estimated_cost"], "MaterialPackage.baseline_estimated_cost")
    assert is_iso8601_timestamp(data["required_onsite_date"])
    for day_field in (
        "fabrication_duration_days",
        "baseline_fabrication_duration_days",
        "delivery_transit_days",
        "submittal_review_days",
        "lead_time_days",
        "float_days",
        "open_quote_count",
    ):
        assert isinstance(data[day_field], int), f"MaterialPackage.{day_field} must be an integer"
    assert isinstance(data["is_long_lead"], bool)
    assert is_iso8601_timestamp(data["release_for_fabrication_date"])
    assert data["rff_risk_band"] in ("ON_TRACK", "AT_RISK", "CRITICAL")
    assert data["status"] in (
        "IDENTIFIED",
        "SOURCING",
        "BOUGHT_OUT",
        "SOURCING_STALLED",
        "CLOSED",
    )
    assert_package_schedule_invariants(data)


def assert_package_schedule_invariants(data: dict) -> None:
    """The release-for-fabrication derivation the PRD pins on every package read."""
    expected_lead = (
        data["fabrication_duration_days"]
        + data["delivery_transit_days"]
        + data["submittal_review_days"]
    )
    assert data["lead_time_days"] == expected_lead, (
        f"lead_time_days should be {expected_lead}, got {data['lead_time_days']}"
    )
    expected_release = iso_add_days(data["required_onsite_date"], -data["lead_time_days"])
    assert_instant_equals(
        data["release_for_fabrication_date"], expected_release, "release_for_fabrication_date"
    )
    expected_long_lead = (
        data["fabrication_duration_days"] + data["delivery_transit_days"]
    ) >= 90
    assert data["is_long_lead"] is expected_long_lead, (
        f"is_long_lead should be {expected_long_lead} for fabrication "
        f"{data['fabrication_duration_days']} + transit {data['delivery_transit_days']}"
    )
    assert_rff_risk_band(data["float_days"], data["rff_risk_band"])


def assert_rff_risk_band(float_days: int, band: str) -> None:
    if float_days <= 0:
        expected = "CRITICAL"
    elif float_days <= 14:
        expected = "AT_RISK"
    else:
        expected = "ON_TRACK"
    assert band == expected, (
        f"rff_risk_band should be {expected} at float_days {float_days}, got {band}"
    )


def assert_supplier(data: dict) -> None:
    assert_versioned_fields(data, "Supplier")
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 200
    assert re.fullmatch(r"[A-Z]{2}", data["country_of_origin"]), (
        f"country_of_origin must be two uppercase letters, got {data['country_of_origin']!r}"
    )
    assert data["is_domestic"] is (data["country_of_origin"] == "US")
    assert 0 <= data["declared_tariff_rate_pct"] <= 100
    assert isinstance(data["open_disruption_count"], int)
    assert_money(data["exposure_score_snapshot"], "Supplier.exposure_score_snapshot")
    assert 0 <= data["exposure_score_snapshot"] <= 100
    assert data["exposure_band_snapshot"] in ("LOW", "ELEVATED", "HIGH")
    assert_exposure_band(data["exposure_score_snapshot"], data["exposure_band_snapshot"])
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_exposure_band(score: float, band: str) -> None:
    if score >= 60:
        expected = "HIGH"
    elif score >= 30:
        expected = "ELEVATED"
    else:
        expected = "LOW"
    assert band == expected, f"exposure band should be {expected} at score {score}, got {band}"


def assert_quote(data: dict) -> None:
    assert_versioned_fields(data, "Quote")
    assert is_valid_uuid(data["material_package_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert_money(data["base_price"], "Quote.base_price")
    assert data["base_price"] > 0
    assert is_iso8601_timestamp(data["received_at"])
    assert isinstance(data["price_hold_days"], int) and 1 <= data["price_hold_days"] <= 120
    assert is_iso8601_timestamp(data["expires_at"])
    assert_instant_equals(
        data["expires_at"],
        iso_add_days(data["received_at"], data["price_hold_days"]),
        "Quote.expires_at",
    )
    assert data["status"] in ("OPEN", "EXPIRED", "SUPERSEDED", "CONVERTED")


def assert_escalation_agreement(data: dict) -> None:
    assert_versioned_fields(data, "EscalationAgreement")
    assert is_valid_uuid(data["quote_id"])
    assert data["index_code"] in (
        "PPI_STEEL_MILL",
        "PPI_COPPER_WIRE",
        "PPI_LUMBER",
        "PPI_CEMENT",
        "PPI_SWITCHGEAR",
    )
    assert _PERIOD_RE.match(data["baseline_index_period"]), (
        f"baseline_index_period must be YYYY-MM, got {data['baseline_index_period']!r}"
    )
    assert 0 <= data["deadband_pct"] <= 20
    assert 0 < data["cap_pct"] <= 25
    assert 0 <= data["contractor_share_pct"] <= 100
    assert is_iso8601_timestamp(data["price_hold_through"])
    assert isinstance(data["round_number"], int) and data["round_number"] >= 0
    assert data["status"] in ("DRAFT", "PROPOSED", "COUNTERED", "EXECUTED", "LAPSED")


def assert_index_reading(data: dict) -> None:
    """A published reading is append-only: id + created_at, no updated_at, no version."""
    assert_identity_and_audit_fields(data, "IndexReading")
    assert "updated_at" not in data, "A published index reading carries no updated_at field"
    assert "version" not in data, "A published index reading carries no version field"
    assert data["index_code"] in (
        "PPI_STEEL_MILL",
        "PPI_COPPER_WIRE",
        "PPI_LUMBER",
        "PPI_CEMENT",
        "PPI_SWITCHGEAR",
    )
    assert _PERIOD_RE.match(data["period"]), f"period must be YYYY-MM, got {data['period']!r}"
    assert_money(data["value"], "IndexReading.value")
    assert data["value"] > 0
    assert is_iso8601_timestamp(data["published_at"])


def assert_purchase_commitment(data: dict) -> None:
    assert_versioned_fields(data, "PurchaseCommitment")
    assert is_valid_uuid(data["quote_id"])
    assert is_valid_uuid(data["material_package_id"])
    assert isinstance(data["po_number"], str) and 1 <= len(data["po_number"]) <= 40
    assert_money(data["committed_base_cost"], "PurchaseCommitment.committed_base_cost")
    assert isinstance(data["is_early_buyout"], bool)
    assert data["requires_storage_arrangement"] == data["is_early_buyout"], (
        "requires_storage_arrangement always equals is_early_buyout"
    )
    assert data["commitment_status"] in (
        "PENDING",
        "COMMITTED",
        "CLOSED",
        "CANCELLED",
        "VOIDED",
    )
    assert data["delivery_posture"] in (
        "SCHEDULED",
        "RELEASED_FOR_FAB",
        "FABRICATING",
        "STORED_OFFSITE",
        "STORAGE_NONCOMPLIANT",
        "DELIVERED",
    )
    assert data["escalation_variant"] in ("NONE", "PROVISIONAL", "FINAL")
    assert_money(data["escalation_accrued"], "PurchaseCommitment.escalation_accrued")
    assert data["escalation_accrued"] >= 0, "escalation_accrued is never negative"
    if data["escalation_variant"] == "NONE":
        assert data["escalation_accrued"] == 0, (
            "escalation_accrued is 0 while escalation_variant is NONE"
        )
        assert data["escalation_index_period"] is None
    else:
        assert _PERIOD_RE.match(data["escalation_index_period"] or ""), (
            f"escalation_index_period must be YYYY-MM once escalation is recognized, "
            f"got {data['escalation_index_period']!r}"
        )


def assert_storage_arrangement(data: dict) -> None:
    assert_versioned_fields(data, "OffsiteStorageArrangement")
    assert is_valid_uuid(data["purchase_commitment_id"])
    assert isinstance(data["warehouse_name"], str) and 1 <= len(data["warehouse_name"]) <= 120
    assert_money(data["stored_value"], "OffsiteStorageArrangement.stored_value")
    assert data["stored_value"] > 0
    assert 0 < data["monthly_storage_rate_pct"] <= 5
    assert is_iso8601_timestamp(data["stored_from"])
    assert is_iso8601_timestamp(data["planned_release_date"])
    assert parse_instant(data["planned_release_date"]) > parse_instant(data["stored_from"])
    assert data["documentation_status"] in ("INCOMPLETE", "COMPLETE")
    assert isinstance(data["verified_doc_type_count"], int)
    assert 0 <= data["verified_doc_type_count"] <= 3
    assert (data["documentation_status"] == "COMPLETE") == (
        data["verified_doc_type_count"] == 3
    ), "documentation_status is COMPLETE exactly when verified_doc_type_count is 3"
    assert_money(data["carrying_cost_accrued"], "OffsiteStorageArrangement.carrying_cost_accrued")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "RELEASED")


def assert_storage_document(data: dict) -> None:
    assert_versioned_fields(data, "StorageDocument")
    assert is_valid_uuid(data["storage_arrangement_id"])
    assert data["doc_type"] in (
        "BAILMENT_AGREEMENT",
        "INSURANCE_CERTIFICATE",
        "LIEN_WAIVER",
        "INVENTORY_TAG_PHOTO",
    )
    assert isinstance(data["reference_number"], str) and 1 <= len(data["reference_number"]) <= 60
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert parse_instant(data["expires_at"]) > parse_instant(data["effective_date"])
    assert_money(data["coverage_amount"], "StorageDocument.coverage_amount")
    assert isinstance(data["verified"], bool)
    assert isinstance(data["revoked"], bool)


def assert_substitution_request(data: dict) -> None:
    assert_versioned_fields(data, "SubstitutionRequest")
    assert is_valid_uuid(data["material_package_id"])
    assert is_valid_uuid(data["proposed_supplier_id"])
    assert data["driver"] in ("VALUE_ENGINEERING", "DISRUPTION_CONTINGENCY", "AVAILABILITY")
    assert isinstance(data["proposed_product"], str) and 1 <= len(data["proposed_product"]) <= 200
    assert_money(data["cost_delta"], "SubstitutionRequest.cost_delta")
    assert abs(data["cost_delta"]) <= 5000000
    assert isinstance(data["schedule_delta_days"], int)
    assert -180 <= data["schedule_delta_days"] <= 180
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert_money(data["applied_cost_delta"], "SubstitutionRequest.applied_cost_delta")
    assert isinstance(data["applied_schedule_delta_days"], int)
    assert data["status"] in (
        "SUBMITTED",
        "APPROVED",
        "APPROVED_AS_NOTED",
        "REJECTED",
        "REVISION_REQUESTED",
        "RESCINDED",
    )


def assert_change_order_request(data: dict) -> None:
    assert_versioned_fields(data, "ChangeOrderRequest")
    assert is_valid_uuid(data["purchase_commitment_id"])
    assert_money(data["claimed_amount"], "ChangeOrderRequest.claimed_amount")
    assert data["claimed_amount"] > 0
    assert isinstance(data["narrative"], str) and 1 <= len(data["narrative"]) <= 2000
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    assert_money(data["gross_documented_amount"], "ChangeOrderRequest.gross_documented_amount")
    assert data["admin_fee_pct"] in (5.0, 3.5, 2.0), (
        f"admin_fee_pct must be one of the three declared tiers, got {data['admin_fee_pct']}"
    )
    assert_money(data["admin_fee_amount"], "ChangeOrderRequest.admin_fee_amount")
    assert_money(data["substantiated_amount"], "ChangeOrderRequest.substantiated_amount")
    assert data["status"] in ("PREPARED", "SUBMITTED", "OWNER_APPROVED", "OWNER_REJECTED")
    assert_substantiation_arithmetic(data)


def assert_substantiation_arithmetic(data: dict) -> None:
    """The five pinned substantiation steps of PRD §3.9."""
    gross = data["gross_documented_amount"]
    if gross < 10000.00:
        expected_pct = 5.0
    elif gross < 50000.00:
        expected_pct = 3.5
    else:
        expected_pct = 2.0
    assert data["admin_fee_pct"] == pytest.approx(expected_pct), (
        f"admin_fee_pct should be {expected_pct} for a gross of {gross}, "
        f"got {data['admin_fee_pct']}"
    )
    expected_fee = round_half_up(gross * expected_pct / 100.0, 2)
    assert data["admin_fee_amount"] == pytest.approx(expected_fee, abs=0.005), (
        f"admin_fee_amount should be {expected_fee}, got {data['admin_fee_amount']}"
    )
    running_total = round_half_up(gross + expected_fee, 2)
    expected_substantiated = min(running_total, data["claimed_amount"])
    assert data["substantiated_amount"] == pytest.approx(expected_substantiated, abs=0.005), (
        f"substantiated_amount should be {expected_substantiated}, "
        f"got {data['substantiated_amount']}"
    )


def assert_disruption_event(data: dict) -> None:
    assert_versioned_fields(data, "DisruptionEvent")
    assert is_valid_uuid(data["supplier_id"])
    assert data["event_type"] in (
        "TARIFF_IMPOSED",
        "PLANT_SHUTDOWN",
        "PORT_CONGESTION",
        "FORCE_MAJEURE",
    )
    assert 0 <= data["tariff_rate_pct"] <= 100
    assert is_iso8601_timestamp(data["effective_date"])
    assert isinstance(data["description"], str) and 1 <= len(data["description"]) <= 500
    assert data["status"] in ("OPEN", "MITIGATED")


def assert_clock_state(data: dict) -> None:
    assert is_iso8601_timestamp(data["current_utc"])
    for list_field in (
        "expired_quote_ids",
        "lapsed_agreement_ids",
        "voided_commitment_ids",
        "stalled_package_ids",
    ):
        assert isinstance(data[list_field], list), f"clock response must carry {list_field}"


# ─── Arithmetic helpers used by expected-value assertions ─────────────────

def round_half_up(value: float, places: int = 2) -> float:
    """Round half up, the discipline the PRD pins for every money figure."""
    from decimal import ROUND_HALF_UP, Decimal

    quant = Decimal(1).scaleb(-places)
    return float(Decimal(repr(float(value))).quantize(quant, rounding=ROUND_HALF_UP))


def expected_escalation_accrued(
    committed_base_cost: float,
    baseline_index_value: float,
    current_index_value: float,
    deadband_pct: float,
    cap_pct: float,
    contractor_share_pct: float,
) -> float:
    """The four-step escalation chain with exactly one intermediate rounding."""
    movement = round_half_up(
        (current_index_value - baseline_index_value) / baseline_index_value * 100.0, 4
    )
    eligible = max(0.0, movement - deadband_pct)
    capped = min(eligible, cap_pct)
    shared = capped * (1.0 - contractor_share_pct / 100.0)
    return round_half_up(committed_base_cost * shared / 100.0, 2)


def expected_monthly_carrying_charge(
    stored_value: float, monthly_storage_rate_pct: float
) -> float:
    """Per-month charge: each component rounded to 2 dp BEFORE they are added."""
    storage = round_half_up(stored_value * monthly_storage_rate_pct / 100.0, 2)
    insurance = round_half_up(stored_value * 0.0175 / 100.0, 2)
    return round_half_up(storage + insurance, 2)


def expected_carrying_cost(
    stored_value: float, monthly_storage_rate_pct: float, whole_months: int
) -> float:
    per_month = expected_monthly_carrying_charge(stored_value, monthly_storage_rate_pct)
    return round_half_up(per_month * whole_months, 2)


def whole_months_between(stored_from: str, evaluated_at: str) -> int:
    """Whole elapsed months from `stored_from` to `evaluated_at`, day-of-month clamped."""
    target = parse_instant(evaluated_at)
    months = 0
    while True:
        step = parse_instant(iso_add_months(stored_from, months + 1))
        if step <= target:
            months += 1
        else:
            return months
