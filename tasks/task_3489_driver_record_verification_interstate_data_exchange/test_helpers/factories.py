"""Payload factories — one per input-bearing endpoint — plus clock arithmetic.

Every factory supplies PRD-shaped defaults and accepts ``**overrides`` so a
test controls exactly the fields its rule mentions. No factory reads the host
wall clock: every date helper anchors to an explicit logical-clock value
(``clock`` argument, defaulting to the PRD's startup instant). A test that
moved the clock passes the instant it set.
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .constants import (
    CONVICTION_POINTS_MIN,
    DEFAULT_CERT_WINDOW_END,
    DEFAULT_CERT_WINDOW_START,
    DEFAULT_CLOCK_DATE,
    DEFAULT_CLOCK_ISO,
)
from .types import (
    CertificationStatus,
    CheckType,
    ConvictionSeverity,
    FeeTier,
    LawfulStatusBasis,
    LicenseClass,
    SystemName,
)


# ── Clock-anchored date arithmetic ───────────────────────────────────────────

def date_plus_days(iso_date: str, days: int) -> str:
    """The ISO date ``days`` after ``iso_date`` (YYYY-MM-DD in, same out)."""
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def date_minus_days(iso_date: str, days: int) -> str:
    """The ISO date ``days`` before ``iso_date`` (YYYY-MM-DD in, same out)."""
    return (date.fromisoformat(iso_date) - timedelta(days=days)).isoformat()


def instant_plus_days(iso_instant: str, days: int) -> str:
    """The ISO 8601 UTC instant ``days`` after ``iso_instant`` (Z-suffixed)."""
    instant = datetime.fromisoformat(iso_instant.replace("Z", "+00:00"))
    shifted = instant + timedelta(days=days)
    return shifted.strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_date_of(clock_iso: str = DEFAULT_CLOCK_ISO) -> str:
    """The calendar date (YYYY-MM-DD) of a logical-clock instant."""
    return clock_iso[:10]


def conviction_dates_for(
    days_before_posting: int,
    clock_iso: str = DEFAULT_CLOCK_ISO,
    offense_gap_days: int = 10,
) -> Tuple[str, str]:
    """(offense_date, conviction_date) for a conviction whose posting lands on
    the clock's current date. ``days_before_posting`` drives ``is_late``:
    exactly 30 is timely, 31 or more is late."""
    posted_date = clock_date_of(clock_iso)
    conviction_date = date_minus_days(posted_date, days_before_posting)
    offense_date = date_minus_days(conviction_date, offense_gap_days)
    return offense_date, conviction_date


def expected_dq_window(clock_iso: str, duration_days: int) -> Tuple[str, str]:
    """(start_date, end_date) of an automatic disqualification created while
    the logical clock reads ``clock_iso``: start is the clock's date, end is
    start plus the duration (closed interval)."""
    start = clock_date_of(clock_iso)
    return start, date_plus_days(start, duration_days)


# ── Logical clock ────────────────────────────────────────────────────────────

def clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ── Jurisdictions, participations, certifications ────────────────────────────

def jurisdiction_payload(
    code: str = "AA",
    name: str = "State A",
    fee_tier: str = FeeTier.TIER_1.value,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"code": code, "name": name, "fee_tier": fee_tier}
    payload.update(overrides)
    return payload


def membership_transition_payload(status: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"status": status}
    payload.update(overrides)
    return payload


def participation_payload(
    jurisdiction_id: str,
    system: str = SystemName.POINTER_NETWORK.value,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"jurisdiction_id": jurisdiction_id, "system": system}
    payload.update(overrides)
    return payload


def certification_payload(
    participation_id: str,
    window_start: str = DEFAULT_CERT_WINDOW_START,
    window_end: str = DEFAULT_CERT_WINDOW_END,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "participation_id": participation_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def certification_completion_payload(
    result: str = CertificationStatus.PASSED.value,
    score: Optional[int] = 95,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"result": result}
    if score is not None:
        payload["score"] = score
    payload.update(overrides)
    return payload


# ── Drivers, records, convictions, disqualifications ─────────────────────────

def driver_payload(
    full_name: str = "Test Driver",
    date_of_birth: str = "1990-01-01",
    ssn_last4_hash: str = "h0000",
    lawful_status_basis: str = LawfulStatusBasis.US_CITIZEN.value,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "ssn_last4_hash": ssn_last4_hash,
        "lawful_status_basis": lawful_status_basis,
    }
    payload.update(overrides)
    return payload


def driver_record_payload(
    driver_id: str,
    expected_driver_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "driver_id": driver_id,
        "expected_driver_version": expected_driver_version,
    }
    payload.update(overrides)
    return payload


def conviction_payload(
    record_id: str,
    offense_date: Optional[str] = None,
    conviction_date: Optional[str] = None,
    severity: str = ConvictionSeverity.NON_CMV.value,
    points: int = CONVICTION_POINTS_MIN + 1,
    clock_iso: str = DEFAULT_CLOCK_ISO,
    **overrides: Any,
) -> Dict[str, Any]:
    """Conviction payload. Dates default to a timely posting against the given
    logical-clock instant (well inside the 30-day deadline and the points
    window); pass explicit dates whenever the scenario moved the clock or
    probes a deadline/window boundary."""
    if offense_date is None or conviction_date is None:
        default_offense, default_conviction = conviction_dates_for(11, clock_iso)
        offense_date = offense_date or default_offense
        conviction_date = conviction_date or default_conviction
    payload = {
        "record_id": record_id,
        "offense_date": offense_date,
        "conviction_date": conviction_date,
        "severity": severity,
        "points": points,
    }
    payload.update(overrides)
    return payload


def disqualification_payload(
    record_id: str,
    start_date: str = date_plus_days(DEFAULT_CLOCK_DATE, 9),
    end_date: str = date_plus_days(DEFAULT_CLOCK_DATE, 19),
    **overrides: Any,
) -> Dict[str, Any]:
    """Manual judicial disqualification payload with explicit closed-interval
    dates (defaults lie just after the startup instant)."""
    payload = {
        "record_id": record_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    payload.update(overrides)
    return payload


# ── Licenses and transfers ───────────────────────────────────────────────────

def license_payload(
    driver_id: str,
    license_class: str = LicenseClass.STANDARD.value,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"driver_id": driver_id, "license_class": license_class}
    payload.update(overrides)
    return payload


def verification_result_payload(
    check_type: str = CheckType.SSN.value,
    result: str = "VERIFIED",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"check_type": check_type, "result": result}
    payload.update(overrides)
    return payload


def license_transfer_payload(
    driver_id: str,
    prior_license_id: str,
    expected_driver_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "driver_id": driver_id,
        "prior_license_id": prior_license_id,
        "expected_driver_version": expected_driver_version,
    }
    payload.update(overrides)
    return payload


def contest_payload(reason: str = "DATA_MISMATCH", **overrides: Any) -> Dict[str, Any]:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


# ── Vehicle titles and title transfers ───────────────────────────────────────

def vehicle_title_payload(
    vin: str = "1HGCM82633A004352",
    brands: Optional[Sequence[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Vehicle title payload; ``brands=None`` omits the field entirely so the
    server-side default (empty set) applies."""
    payload: Dict[str, Any] = {"vin": vin}
    if brands is not None:
        payload["brands"] = list(brands)
    payload.update(overrides)
    return payload


def title_transfer_payload(
    vehicle_title_id: str,
    disclosed_brands: Optional[Sequence[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "vehicle_title_id": vehicle_title_id,
        "disclosed_brands": list(disclosed_brands) if disclosed_brands is not None else [],
    }
    payload.update(overrides)
    return payload


# ── Fee invoices ─────────────────────────────────────────────────────────────

def fee_invoice_payload(
    jurisdiction_id: str,
    fiscal_year: int = 2027,
    projected_volume: int = 8000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "fiscal_year": fiscal_year,
        "projected_volume": projected_volume,
    }
    payload.update(overrides)
    return payload


def dispute_payload(reason: str = "VOLUME_OVERSTATED", **overrides: Any) -> Dict[str, Any]:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def reissue_payload(projected_volume: int, **overrides: Any) -> Dict[str, Any]:
    payload = {"projected_volume": projected_volume}
    payload.update(overrides)
    return payload


def settle_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def finalize_audit_payload(
    actual_volume_quarters: Optional[Sequence[int]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "actual_volume_quarters": (
            list(actual_volume_quarters) if actual_volume_quarters is not None else [0, 0, 0, 0]
        )
    }
    payload.update(overrides)
    return payload
