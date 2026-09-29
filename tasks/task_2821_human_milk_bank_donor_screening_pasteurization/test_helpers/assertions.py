"""Shape assertions, domain invariant checks and independent recalculations.

The `expected_*` helpers re-derive the PRD's arithmetic from its own stated
inputs so a test can compare the service's answer against a second, independent
computation instead of a hand-copied number. Every one of them works in
`Decimal` so that "round half up" means exactly that and never inherits a
binary-floating-point artefact.

Instant comparisons go through `assert_instant_equals`, which compares the two
values as points in time. The API stamps clock instants with three fractional
digits while a test drives the clock with a whole-second literal, and those two
spellings denote the same instant.
"""

import math
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as C
from .types import (
    ComponentStatus,
    DonationStatus,
    LotReleaseStatus,
    PatientType,
    ProgramStatus,
)

_INSTANT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Rounding and instants
# ---------------------------------------------------------------------------
def round_half_up(value: Any, places: int = 0) -> Decimal:
    """Round away from zero on an exact half, which is the bank's only method."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value: Any) -> int:
    """Round half up to a whole cent and return it as an integer."""
    return int(round_half_up(value, 0))


def parse_instant(value: str) -> datetime:
    match = _INSTANT_RE.match(value)
    assert match, f"{value!r} is not an ISO 8601 UTC instant"
    micros = (match.group(5) or "").ljust(6, "0")
    return datetime(
        *(int(part) for part in match.group(1).split("-")),
        int(match.group(2)),
        int(match.group(3)),
        int(match.group(4)),
        int(micros),
    )


def parse_date(value: str) -> date:
    assert _DATE_RE.match(value), f"{value!r} is not a YYYY-MM-DD date"
    return date(*(int(part) for part in value.split("-")))


def add_days(iso_date: str, days: int) -> str:
    """Exact calendar addition, so leap days count."""
    return (parse_date(iso_date) + timedelta(days=days)).isoformat()


def days_between(earlier: str, later: str) -> int:
    return (parse_date(later) - parse_date(earlier)).days


def date_part(instant: str) -> str:
    return parse_instant(instant).date().isoformat()


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "instant") -> None:
    """Compare two instants as points in time rather than as strings."""
    assert actual is not None, f"{label} should be stamped, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label} should be {expected}, got {actual}"
    )


def assert_audit_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """The four-field audit set carried by the nine versioned resources."""
    assert is_valid_uuid(entity["id"]), f"id should be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int) and entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"version should be {expected_version}, got {entity['version']}"
        )


def assert_event_record(entity: Dict[str, Any]) -> None:
    """An immutable-by-design record exposes id and created_at and no version."""
    assert is_valid_uuid(entity["id"]), f"id should be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert "version" not in entity, "an event record exposes no version"
    assert "updated_at" not in entity, "an event record exposes no updated_at"


def assert_money(entity: Dict[str, Any], field: str, expected: Optional[int]) -> None:
    """A monetary field is an integer number of whole cents, never a string."""
    actual = entity.get(field)
    if expected is None:
        assert actual is None, f"{field} should be null, got {actual!r}"
        return
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{field} should be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{field} should be {expected} cents, got {actual}"


# ---------------------------------------------------------------------------
# Risk scoring (PRD 3.1)
# ---------------------------------------------------------------------------
def alcohol_points(units_per_week: int) -> int:
    if units_per_week == 0:
        return C.ALCOHOL_TIER_ZERO_POINTS
    if units_per_week <= 3:
        return C.ALCOHOL_TIER_LOW_POINTS
    if units_per_week <= 7:
        return C.ALCOHOL_TIER_MID_POINTS
    return C.ALCOHOL_TIER_HIGH_POINTS


def expected_base_risk_points(
    medication_flag_count: int = 0,
    travel_risk_flag: bool = False,
    tobacco_use: bool = False,
    alcohol_units_per_week: int = 0,
    months_postpartum: int = 0,
) -> int:
    postpartum_term = min(
        C.POSTPARTUM_TERM_CAP,
        max(0, months_postpartum - C.POSTPARTUM_FREE_MONTHS) * C.POSTPARTUM_POINTS_PER_MONTH,
    )
    return (
        medication_flag_count * C.POINTS_PER_FLAGGED_MEDICATION
        + (C.POINTS_TRAVEL_RISK if travel_risk_flag else 0)
        + (C.POINTS_TOBACCO_USE if tobacco_use else 0)
        + alcohol_points(alcohol_units_per_week)
        + postpartum_term
    )


def expected_screening_score(
    base_risk_points: int,
    has_unexpired_non_reactive_panel: bool,
    temporary_deferral_count: int,
) -> int:
    """The pessimistic variant: a flat pending-serology penalty and undiscounted
    deferral history, capped at 100."""
    total = base_risk_points
    if not has_unexpired_non_reactive_panel:
        total += C.PENDING_SEROLOGY_PENALTY
    total += temporary_deferral_count * C.POINTS_PER_TEMPORARY_DEFERRAL
    return min(C.RISK_SCORE_CAP, total)


def expected_surveillance_score(
    base_risk_points: int, deferral_ages_in_days: Sequence[int] = ()
) -> int:
    """The time-discounted variant: no serology penalty, each deferral halved
    every 180 days, summed at full precision and rounded half up once."""
    contribution = Decimal(0)
    for age in deferral_ages_in_days:
        factor = Decimal(0.5) ** (Decimal(age) / Decimal(C.DEFERRAL_DECAY_HALF_LIFE_DAYS))
        contribution += Decimal(C.POINTS_PER_TEMPORARY_DEFERRAL) * factor
    total = int(round_half_up(Decimal(base_risk_points) + contribution, 0))
    return min(C.RISK_SCORE_CAP, total)


def expected_triage_status(screening_score: int) -> str:
    if screening_score <= C.TRIAGE_ACCEPTED_MAX:
        return "ACCEPTED"
    if screening_score <= C.TRIAGE_INFO_REQUESTED_MAX:
        return "INFO_REQUESTED"
    return "AUTO_DEFERRED"


# ---------------------------------------------------------------------------
# Courier reimbursement (PRD 3.4)
# ---------------------------------------------------------------------------
def excursion_penalty_rate(excursion_minutes: int) -> Decimal:
    uncapped = Decimal(str(C.PENALTY_RATE_PER_EXCURSION_MINUTE)) * Decimal(excursion_minutes)
    return min(Decimal(str(C.MAX_PENALTY_RATE)), uncapped)


def expected_reimbursement_cents(
    zone_code: str,
    container_count: int,
    uses_dry_ice: bool,
    excursion_minutes: int = 0,
) -> int:
    """The shared skeleton: per-container share, dry ice, handling, penalty, then
    round half up per container and only afterwards multiply by the count."""
    share = Decimal(C.ZONE_BASE_CENTS[zone_code]) / Decimal(container_count)
    if uses_dry_ice:
        share *= Decimal(str(C.DRY_ICE_MULTIPLIER))
    share += Decimal(C.PER_CONTAINER_HANDLING_CENTS)
    share *= Decimal(1) - excursion_penalty_rate(excursion_minutes)
    per_container = round_half_up(share, 0)
    return int(per_container * container_count)


def expected_unrounded_total_cents(
    zone_code: str,
    container_count: int,
    uses_dry_ice: bool,
    excursion_minutes: int = 0,
) -> int:
    """The wrong answer: sum the unrounded per-container amounts and round once
    at the end. Kept so a test can assert the bank does not report it."""
    share = Decimal(C.ZONE_BASE_CENTS[zone_code]) / Decimal(container_count)
    if uses_dry_ice:
        share *= Decimal(str(C.DRY_ICE_MULTIPLIER))
    share += Decimal(C.PER_CONTAINER_HANDLING_CENTS)
    share *= Decimal(1) - excursion_penalty_rate(excursion_minutes)
    return int(round_half_up(share * Decimal(container_count), 0))


def expected_receive_status(excursion_minutes: int, arrival_max_temp_celsius: float) -> str:
    if (
        arrival_max_temp_celsius > C.REJECT_TEMP_CELSIUS
        or excursion_minutes > C.REJECT_EXCURSION_MINUTES
    ):
        return "REJECTED"
    if (
        arrival_max_temp_celsius > C.QUARANTINE_TEMP_CELSIUS
        or excursion_minutes > C.QUARANTINE_EXCURSION_MINUTES
    ):
        return "QUARANTINED"
    return "ACCEPTED"


def expected_credited_cents(status: str, final_cents: int) -> int:
    if status == "ACCEPTED":
        return final_cents
    if status == "QUARANTINED":
        return cents(Decimal(final_cents) * Decimal(str(C.QUARANTINE_CREDIT_FRACTION)))
    return 0


# ---------------------------------------------------------------------------
# Pool nutrition (PRD 3.5)
# ---------------------------------------------------------------------------
def expected_projected_kcal(components: Iterable[Tuple[int, Any]]) -> Optional[float]:
    """Volume-weighted average density over `(allocated_volume_ml, kcal_per_oz)`
    pairs, summed exactly and rounded half up to two places at the single final
    division."""
    pairs = list(components)
    if not pairs:
        return None
    total_volume = sum(volume for volume, _ in pairs)
    if total_volume == 0:
        return None
    weighted = sum(Decimal(volume) * Decimal(str(kcal)) for volume, kcal in pairs)
    return float(round_half_up(weighted / Decimal(total_volume), 2))


def is_balanced(distinct_donor_count: int, projected_kcal: Optional[float], total_volume_ml: int) -> bool:
    if projected_kcal is None:
        return False
    return (
        distinct_donor_count >= C.POOL_MIN_DISTINCT_DONORS
        and Decimal(str(C.POOL_KCAL_MIN))
        <= Decimal(str(projected_kcal))
        <= Decimal(str(C.POOL_KCAL_MAX))
        and C.POOL_VOLUME_MIN <= total_volume_ml <= C.POOL_VOLUME_MAX
    )


# ---------------------------------------------------------------------------
# Thermal verification (PRD 3.6)
# ---------------------------------------------------------------------------
def reading_qualifies(celsius: float) -> bool:
    return (
        Decimal(str(C.HOLD_BAND_LOW_CELSIUS))
        <= Decimal(str(celsius))
        <= Decimal(str(C.HOLD_BAND_HIGH_CELSIUS))
    )


def expected_longest_hold_seconds(samples: Sequence[Tuple[int, float]]) -> int:
    """Walk the curve in ascending offset order carrying the open segment start
    and the best hold so far, restarting the segment across any gap of more than
    ten minutes."""
    ordered = sorted(samples, key=lambda pair: pair[0])
    segment_start: Optional[int] = None
    longest = 0
    previous_offset: Optional[int] = None
    for offset, celsius in ordered:
        if not reading_qualifies(celsius):
            segment_start = None
        elif segment_start is None:
            segment_start = offset
        elif previous_offset is not None and offset - previous_offset > C.MAX_MONITORING_GAP_SECONDS:
            segment_start = offset
        else:
            longest = max(longest, offset - segment_start)
        previous_offset = offset
    return longest


def expected_thermal_status(samples: Sequence[Tuple[int, float]]) -> str:
    return (
        "PASSED"
        if expected_longest_hold_seconds(samples) >= C.THERMAL_PASS_HOLD_SECONDS
        else "FAILED"
    )


def expected_culture_status(cfu_per_ml: int) -> str:
    return "FAILED" if cfu_per_ml >= C.CULTURE_FAIL_CFU_PER_ML else "PASSED"


def expected_release_eligibility(thermal_status: str, culture_status: str) -> str:
    return "ELIGIBLE" if thermal_status == "PASSED" and culture_status == "PASSED" else "BLOCKED"


def occupied_interval_end(scheduled_start_at: str, cycle_minutes: int) -> datetime:
    """The half-open interval ends cycle plus fifteen minutes after the start."""
    return parse_instant(scheduled_start_at) + timedelta(
        minutes=cycle_minutes + C.CLEANING_BUFFER_MINUTES
    )


# ---------------------------------------------------------------------------
# Lot identity and shelf life (PRD 3.7)
# ---------------------------------------------------------------------------
def expected_lot_code(pasteurization_date: str, pool_sequence: int, lot_sequence: int) -> str:
    return (
        f"{pasteurization_date.replace('-', '')}"
        f"-{pool_sequence:03d}"
        f"-{lot_sequence:02d}"
    )


def expected_expiration_date(
    completed_at: str,
    earliest_expressed_on: str,
    earliest_received_date: str,
) -> str:
    ceilings = [
        add_days(date_part(completed_at), C.PASTEURIZATION_SHELF_DAYS),
        add_days(earliest_expressed_on, C.RAW_AGE_SHELF_DAYS),
        add_days(earliest_received_date, C.RECEIPT_SHELF_DAYS),
    ]
    return min(ceilings)


# ---------------------------------------------------------------------------
# Nine-step pricing (PRD 3.9)
# ---------------------------------------------------------------------------
def expected_billable_units(volume_ml: int) -> int:
    return math.ceil(volume_ml / C.BILLABLE_UNIT_ML)


def expected_tier_discount_pct(prior_cumulative_ml: int) -> float:
    if prior_cumulative_ml < C.TIER_BREAK_LOW_ML:
        return C.TIER_DISCOUNT_NONE
    if prior_cumulative_ml < C.TIER_BREAK_HIGH_ML:
        return C.TIER_DISCOUNT_MID
    return C.TIER_DISCOUNT_HIGH


def expected_gross_fee_cents(
    volume_ml: int, prior_cumulative_ml: int, patient_type: str
) -> int:
    units = expected_billable_units(volume_ml)
    tier = Decimal(str(expected_tier_discount_pct(prior_cumulative_ml)))
    base = Decimal(units * C.CENTS_PER_BILLABLE_UNIT)
    handling = Decimal(
        C.OUTPATIENT_HANDLING_CENTS if patient_type == PatientType.OUTPATIENT else 0
    )
    return cents((base + handling) * (Decimal(1) - tier))


def expected_subsidy_cents(
    gross_fee_cents_value: int,
    coverage_pct: float,
    headroom_cents: int,
) -> int:
    uncapped = cents(Decimal(gross_fee_cents_value) * Decimal(str(coverage_pct)))
    return min(uncapped, headroom_cents)


def expected_uncapped_subsidy_cents(gross_fee_cents_value: int, coverage_pct: float) -> int:
    return cents(Decimal(gross_fee_cents_value) * Decimal(str(coverage_pct)))


def expected_priority_tier(patient_type: str, clinical_acuity: str) -> int:
    if patient_type == PatientType.OUTPATIENT:
        return C.PRIORITY_TIER_OUTPATIENT
    return (
        C.PRIORITY_TIER_NICU_CRITICAL
        if clinical_acuity == "CRITICAL"
        else C.PRIORITY_TIER_NICU_STANDARD
    )


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------
def assert_donor(donor: Dict[str, Any], **expected: Any) -> None:
    assert_audit_fields(donor, expected.pop("version", None))
    for field in (
        "donor_code",
        "full_name",
        "email",
        "zone_code",
        "status",
        "screening_risk_score",
        "surveillance_risk_score",
        "reimbursement_balance_cents",
        "lifetime_accepted_volume_ml",
        "temporary_deferral_count",
    ):
        assert field in donor, f"a donor read should expose {field}"
    assert isinstance(donor["reimbursement_balance_cents"], int)
    assert 0 <= donor["screening_risk_score"] <= C.RISK_SCORE_CAP
    assert 0 <= donor["surveillance_risk_score"] <= C.RISK_SCORE_CAP
    assert donor["screening_risk_score"] >= donor["surveillance_risk_score"], (
        "the pessimistic screening score is never lower than the surveillance score"
    )
    _match(donor, expected, "donor")


def assert_shipment(shipment: Dict[str, Any], **expected: Any) -> None:
    assert_audit_fields(shipment, expected.pop("version", None))
    assert isinstance(shipment["estimated_reimbursement_cents"], int)
    _match(shipment, expected, "shipment")


def assert_donation(donation: Dict[str, Any], **expected: Any) -> None:
    assert_audit_fields(donation, expected.pop("version", None))
    assert donation["remaining_ml"] >= 0, "remaining_ml never goes below 0"
    assert donation["remaining_ml"] <= donation["volume_ml"]
    _match(donation, expected, "donation")


def assert_pool(pool: Dict[str, Any], **expected: Any) -> None:
    assert_audit_fields(pool, expected.pop("version", None))
    assert pool["distinct_donor_count"] <= C.POOL_DONOR_CAP
    _match(pool, expected, "pool")


def assert_pool_component(component: Dict[str, Any], **expected: Any) -> None:
    assert_event_record(component)
    _match(component, expected, "pool component")


def assert_run(run: Dict[str, Any], **expected: Any) -> None:
    assert_audit_fields(run, expected.pop("version", None))
    assert run["release_eligibility"] == expected_release_eligibility(
        run["thermal_status"], run["culture_status"]
    ), "release_eligibility is the derived verdict over the thermal and culture dimensions"
    _match(run, expected, "run")


def assert_reading(reading: Dict[str, Any], **expected: Any) -> None:
    assert_event_record(reading)
    assert reading["qualifies"] is reading_qualifies(reading["celsius"])
    _match(reading, expected, "temperature reading")


def assert_milk_lot(lot: Dict[str, Any], **expected: Any) -> None:
    assert_audit_fields(lot, expected.pop("version", None))
    assert lot["available_ml"] == lot["total_volume_ml"] - lot["dispensed_ml"], (
        "available_ml is total_volume_ml less dispensed_ml"
    )
    assert lot["total_volume_ml"] == lot["bottle_count"] * lot["bottle_volume_ml"]
    _match(lot, expected, "milk lot")


def assert_subsidy_program(program: Dict[str, Any], **expected: Any) -> None:
    assert_audit_fields(program, expected.pop("version", None))
    expected_status = (
        ProgramStatus.OPEN
        if program["consumed_cents"] < program["annual_cap_cents"]
        else ProgramStatus.EXHAUSTED
    )
    assert program["status"] == expected_status, (
        "a program is OPEN while consumed_cents is strictly below the cap"
    )
    _match(program, expected, "subsidy program")


def assert_prescription(prescription: Dict[str, Any], **expected: Any) -> None:
    assert_audit_fields(prescription, expected.pop("version", None))
    assert (
        prescription["remaining_ml"]
        == prescription["prescribed_ml"] - prescription["cumulative_dispensed_ml"]
    ), "remaining_ml is prescribed_ml less cumulative_dispensed_ml"
    assert prescription["priority_tier"] == expected_priority_tier(
        prescription["patient_type"], prescription["clinical_acuity"]
    )
    _match(prescription, expected, "prescription")


def assert_dispense(dispense: Dict[str, Any], **expected: Any) -> None:
    assert_audit_fields(dispense, expected.pop("version", None))
    assert (
        dispense["gross_fee_cents"] == dispense["subsidy_cents"] + dispense["payer_due_cents"]
    ), "gross_fee_cents equals subsidy_cents plus payer_due_cents after every fill"
    for field in ("gross_fee_cents", "subsidy_cents", "payer_due_cents"):
        assert isinstance(dispense[field], int) and not isinstance(dispense[field], bool), (
            f"{field} is an integer number of whole cents"
        )
    _match(dispense, expected, "dispense")


def assert_deferral_event(event: Dict[str, Any], **expected: Any) -> None:
    assert_event_record(event)
    _match(event, expected, "deferral event")


def assert_recall_counters(
    event: Dict[str, Any],
    recalled_donation_count: int = 0,
    quarantined_pool_count: int = 0,
    recalled_lot_count: int = 0,
    recalled_dispense_count: int = 0,
    reversed_subsidy_cents: int = 0,
) -> None:
    """All five cascade counters stamped on a deferral event."""
    assert event["recalled_donation_count"] == recalled_donation_count
    assert event["quarantined_pool_count"] == quarantined_pool_count
    assert event["recalled_lot_count"] == recalled_lot_count
    assert event["recalled_dispense_count"] == recalled_dispense_count
    assert event["reversed_subsidy_cents"] == reversed_subsidy_cents


def _match(entity: Dict[str, Any], expected: Dict[str, Any], label: str) -> None:
    for field, wanted in expected.items():
        actual = entity.get(field, "<<absent>>")
        if isinstance(wanted, float) and isinstance(actual, (int, float)):
            assert abs(actual - wanted) < 0.005, (
                f"{label}.{field} should be {wanted}, got {actual}"
            )
        else:
            assert actual == wanted, f"{label}.{field} should be {wanted!r}, got {actual!r}"


# ---------------------------------------------------------------------------
# Cross-entity invariants
# ---------------------------------------------------------------------------
def assert_volume_conservation(donations: List[Dict[str, Any]], components: List[Dict[str, Any]]) -> None:
    """A donation's remaining_ml is its volume_ml less the sum of
    allocated_volume_ml across its non-VOIDED components."""
    for donation in donations:
        drawn = sum(
            component["allocated_volume_ml"]
            for component in components
            if component["donation_id"] == donation["id"]
            and component["status"] != ComponentStatus.VOIDED
        )
        if donation["status"] not in (DonationStatus.DISCARDED, DonationStatus.RECALLED):
            assert donation["remaining_ml"] == donation["volume_ml"] - drawn, (
                f"donation {donation.get('container_label')} should hold "
                f"{donation['volume_ml'] - drawn} ml, reports {donation['remaining_ml']}"
            )


def assert_bank_available_ml(lots: List[Dict[str, Any]], expected_total: int) -> None:
    """The bank-wide neonatal reserve reads available_ml across RELEASED lots."""
    total = sum(
        lot["available_ml"] for lot in lots if lot["release_status"] == LotReleaseStatus.RELEASED
    )
    assert total == expected_total, (
        f"available volume across RELEASED lots should be {expected_total}, got {total}"
    )


def assert_ordered_by(rows: List[Dict[str, Any]], field: str, descending: bool = False) -> None:
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, f"rows should be ordered by {field}: {values}"
