"""Domain assertion helpers.

These operate on the already-unwrapped ``data`` payload returned by
``validate_success`` / ``get_success_data`` — never on the whole envelope, so a
caller must not unwrap twice.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_instant
from .constants import SEVERITY_ORDER


# --- Generic shape -----------------------------------------------------------
def assert_common_fields(entity: Dict[str, Any]) -> None:
    """id / created_at / updated_at / version, per PRD 2.4."""
    assert is_valid_uuid(entity["id"]), f"id must be a bare UUID: {entity['id']!r}"
    assert not entity["id"].startswith(("est_", "prac_", "id_")), (
        "id must carry no type prefix"
    )
    assert_timestamp_format(entity["created_at"])
    assert_timestamp_format(entity["updated_at"])
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1


def assert_immutable_fields(entity: Dict[str, Any]) -> None:
    """The four immutable record types carry only id and created_at (PRD 2.4)."""
    assert is_valid_uuid(entity["id"]), f"id must be a bare UUID: {entity['id']!r}"
    assert_timestamp_format(entity["created_at"])
    assert "updated_at" not in entity, "immutable records carry no updated_at"
    assert "version" not in entity, "immutable records carry no version"


def assert_instant(value: Any) -> None:
    """An ISO 8601 UTC instant with exactly three fractional digits."""
    assert isinstance(value, str), f"expected an instant string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 instant: {value!r}"


def assert_calendar_date(value: Any) -> None:
    """A ``*_on`` field: an ISO 8601 UTC calendar date."""
    assert isinstance(value, str), f"expected a date string, got {value!r}"
    assert len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"not an ISO 8601 calendar date: {value!r}"
    )


def assert_instants_equal(actual: Any, expected: Any, label: str = "instant") -> None:
    """Compare two instants after normalising fractional-digit width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_points(value: Any, expected: float, label: str = "points") -> None:
    """A two-decimal point quantity (PRD 2.7)."""
    assert value is not None, f"{label} must not be null"
    assert abs(float(value) - expected) < 1e-9, (
        f"{label}: expected {expected}, got {value}"
    )


def assert_cents(value: Any, expected: int, label: str = "cents") -> None:
    """A whole-cent monetary quantity (PRD 2.7)."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )
    assert value == expected, f"{label}: expected {expected}, got {value}"


def assert_two_decimal_points(value: Any, label: str = "points") -> None:
    assert value is not None, f"{label} must not be null"
    rounded = round(float(value) + 1e-12, 2)
    assert abs(float(value) - rounded) < 1e-9, (
        f"{label} must carry at most two decimal places, got {value}"
    )


# --- Entity-specific shape ---------------------------------------------------
def assert_establishment_shape(est: Dict[str, Any]) -> None:
    assert_common_fields(est)
    for field in (
        "legal_name",
        "establishment_type",
        "county_code",
        "station_capacity",
        "station_count",
        "license_status",
        "compliance_posture",
        "demerit_balance",
        "open_critical_citation_count",
        "outstanding_fine_total_cents",
        "delinquent_fine_total_cents",
        "foot_spa_biofilm_current",
        "last_finalized_inspection_at",
    ):
        assert field in est, f"establishment missing {field}"
    assert isinstance(est["station_count"], int)
    assert isinstance(est["foot_spa_biofilm_current"], bool)
    assert_two_decimal_points(est["demerit_balance"], "demerit_balance")


def assert_fresh_establishment(est: Dict[str, Any]) -> None:
    """PRD 3.1: the opening state of a freshly registered facility."""
    assert est["license_status"] == "PENDING_INSPECTION"
    assert est["compliance_posture"] == "CLEAR"
    assert est["station_count"] == 0
    assert_points(est["demerit_balance"], 0.00, "demerit_balance")
    assert est["open_critical_citation_count"] == 0
    assert_cents(est["outstanding_fine_total_cents"], 0, "outstanding_fine_total_cents")
    assert_cents(est["delinquent_fine_total_cents"], 0, "delinquent_fine_total_cents")
    assert est["foot_spa_biofilm_current"] is True
    assert est["last_finalized_inspection_at"] is None


def assert_practitioner_shape(prac: Dict[str, Any]) -> None:
    assert_common_fields(prac)
    for field in (
        "full_name",
        "license_type",
        "school_id",
        "license_status",
        "license_expires_on",
        "credited_hours_school",
        "credited_hours_apprentice",
        "credited_hours_total",
        "required_clock_hours_effective",
        "exam_eligible",
        "sanction_points",
        "suspension_cause_points",
    ):
        assert field in prac, f"practitioner missing {field}"
    assert isinstance(prac["exam_eligible"], bool)


def assert_fresh_practitioner(prac: Dict[str, Any]) -> None:
    """PRD 3.2: the opening state of a newly enrolled candidate."""
    assert prac["license_status"] == "STUDENT"
    assert_points(prac["credited_hours_school"], 0.00, "credited_hours_school")
    assert_points(prac["credited_hours_apprentice"], 0.00, "credited_hours_apprentice")
    assert_points(prac["credited_hours_total"], 0.00, "credited_hours_total")
    assert prac["exam_eligible"] is False
    assert_points(prac["sanction_points"], 0.00, "sanction_points")
    assert prac["license_expires_on"] is None
    assert prac["suspension_cause_points"] is None


def assert_workstation_shape(station: Dict[str, Any]) -> None:
    assert_common_fields(station)
    for field in (
        "establishment_id",
        "station_number",
        "station_type",
        "posted_practitioner_id",
        "posting_status",
        "last_biofilm_cycle_at",
    ):
        assert field in station, f"workstation missing {field}"
    assert station["posting_status"] in (
        "MISSING_POSTING",
        "STALE_POSTING",
        "COMPLIANT",
    )


def assert_booth_rental_shape(rental: Dict[str, Any]) -> None:
    assert_common_fields(rental)
    for field in (
        "workstation_id",
        "practitioner_id",
        "rental_type",
        "term_start_at",
        "term_end_at",
        "monthly_rent_cents",
        "status",
        "terminated_at",
    ):
        assert field in rental, f"booth rental missing {field}"
    assert isinstance(rental["monthly_rent_cents"], int)


def assert_inspection_shape(insp: Dict[str, Any]) -> None:
    assert_common_fields(insp)
    for field in (
        "establishment_id",
        "inspection_type",
        "reinspection_of_id",
        "inspector_user_id",
        "complaint_reference",
        "window_start_at",
        "window_end_at",
        "status",
        "hazard_state",
        "started_at",
        "submitted_at",
        "finalized_at",
        "finding_count",
        "provisional_adjusted_score",
        "final_adjusted_score",
        "provisional_outcome",
        "final_outcome",
        "demerit_balance_before_finalize",
        "citation_count",
    ):
        assert field in insp, f"inspection missing {field}"


def assert_fresh_inspection(insp: Dict[str, Any]) -> None:
    """PRD 3.5: the opening state of a newly scheduled inspection."""
    assert insp["status"] == "SCHEDULED"
    assert insp["hazard_state"] == "NONE"
    assert insp["finding_count"] == 0
    assert insp["citation_count"] == 0
    for field in (
        "started_at",
        "submitted_at",
        "finalized_at",
        "demerit_balance_before_finalize",
        "provisional_adjusted_score",
        "final_adjusted_score",
        "provisional_outcome",
        "final_outcome",
    ):
        assert insp[field] is None, f"{field} must open null, got {insp[field]!r}"


def assert_finding_shape(finding: Dict[str, Any]) -> None:
    assert_common_fields(finding)
    for field in (
        "inspection_id",
        "violation_code_id",
        "attributed_practitioner_id",
        "workstation_id",
        "observed_count",
        "corrected_on_site",
        "severity",
        "repeat_factor_provisional",
        "repeat_factor_final",
        "provisional_points",
        "final_points",
        "declared_hazard",
        "note",
    ):
        assert field in finding, f"finding missing {field}"
    assert isinstance(finding["declared_hazard"], bool)


def assert_fresh_finding(finding: Dict[str, Any], severity: str) -> None:
    """PRD 3.5: severity frozen from the code, scoring fields still null."""
    assert finding["severity"] == severity
    assert finding["declared_hazard"] is False
    for field in (
        "repeat_factor_provisional",
        "repeat_factor_final",
        "provisional_points",
        "final_points",
    ):
        assert finding[field] is None, f"{field} must open null, got {finding[field]!r}"


def assert_citation_shape(citation: Dict[str, Any]) -> None:
    assert_common_fields(citation)
    for field in (
        "inspection_id",
        "subject_type",
        "subject_practitioner_id",
        "citation_number",
        "max_finding_severity",
        "demerit_tier_multiplier",
        "assessed_fine_cents",
        "administrative_fee_cents",
        "total_due_cents",
        "outstanding_fine_cents",
        "status",
        "issued_at",
        "due_at",
        "contest_deadline_at",
        "hearing_round_count",
    ):
        assert field in citation, f"citation missing {field}"
    assert isinstance(citation["citation_number"], str)
    assert citation["citation_number"].strip() != ""
    for money in (
        "assessed_fine_cents",
        "administrative_fee_cents",
        "total_due_cents",
        "outstanding_fine_cents",
    ):
        assert isinstance(citation[money], int), f"{money} must be whole cents"


def assert_fine_breakdown(
    citation: Dict[str, Any],
    assessed_fine_cents: int,
    administrative_fee_cents: int,
    total_due_cents: int,
    outstanding_fine_cents: Optional[int] = None,
) -> None:
    """PRD 3.7: the pinned fee evaluation order."""
    assert_cents(citation["assessed_fine_cents"], assessed_fine_cents, "assessed_fine_cents")
    assert_cents(
        citation["administrative_fee_cents"],
        administrative_fee_cents,
        "administrative_fee_cents",
    )
    assert_cents(citation["total_due_cents"], total_due_cents, "total_due_cents")
    assert citation["total_due_cents"] == (
        citation["assessed_fine_cents"] + citation["administrative_fee_cents"]
    ), "total_due_cents must be assessed + fee"
    if outstanding_fine_cents is not None:
        assert_cents(
            citation["outstanding_fine_cents"],
            outstanding_fine_cents,
            "outstanding_fine_cents",
        )


def assert_hearing_shape(hearing: Dict[str, Any]) -> None:
    assert_common_fields(hearing)
    for field in (
        "citation_id",
        "presiding_officer_user_id",
        "scheduled_at",
        "status",
        "decision",
        "amended_fine_cents",
        "rationale",
        "round_index",
        "decided_at",
    ):
        assert field in hearing, f"hearing missing {field}"


def assert_sanitation_log_shape(log: Dict[str, Any]) -> None:
    assert_immutable_fields(log)
    for field in (
        "workstation_id",
        "log_type",
        "performed_at",
        "contact_minutes",
        "disinfectant_epa_reg_number",
        "implement_batch_count",
        "occupancy_end_at",
    ):
        assert field in log, f"sanitation log missing {field}"


def assert_infection_incident_shape(incident: Dict[str, Any]) -> None:
    assert_common_fields(incident)
    for field in (
        "establishment_id",
        "suspected_practitioner_id",
        "case_count",
        "onset_date",
        "narrative",
        "status",
        "reported_at",
        "notification_deadline_at",
        "notified_at",
        "health_authority_reference",
        "findings_summary",
    ):
        assert field in incident, f"infection incident missing {field}"


def assert_ledger_entry_shape(entry: Dict[str, Any]) -> None:
    """PRD 2.5: exactly one magnitude field populated, links by quantity."""
    assert_immutable_fields(entry)
    for field in (
        "ledger_type",
        "entry_reason",
        "delta_cents",
        "delta_points",
        "citation_id",
        "establishment_id",
        "practitioner_id",
        "inspection_id",
        "occurred_at",
    ):
        assert field in entry, f"ledger entry missing {field}"
    if entry["ledger_type"] == "FINE_CENTS":
        assert isinstance(entry["delta_cents"], int), "FINE_CENTS needs delta_cents"
        assert entry["delta_points"] is None, "FINE_CENTS must leave delta_points null"
        assert entry["citation_id"] is not None, "FINE_CENTS carries citation_id"
        assert entry["establishment_id"] is None
        assert entry["practitioner_id"] is None
    elif entry["ledger_type"] == "DEMERIT_POINTS":
        assert entry["delta_cents"] is None, "DEMERIT_POINTS must leave delta_cents null"
        assert entry["delta_points"] is not None
        assert entry["establishment_id"] is not None
        assert entry["practitioner_id"] is None
    elif entry["ledger_type"] == "SANCTION_POINTS":
        assert entry["delta_cents"] is None
        assert entry["delta_points"] is not None
        assert entry["practitioner_id"] is not None
        assert entry["establishment_id"] is None
        assert entry["citation_id"] is None
        assert entry["inspection_id"] is None
    else:  # pragma: no cover - guards a bad enum value
        raise AssertionError(f"unknown ledger_type {entry['ledger_type']!r}")


# --- Ordering and aggregation ------------------------------------------------
def assert_sorted_desc(rows: List[Dict[str, Any]], key: str) -> None:
    values = [row[key] for row in rows]
    assert values == sorted(values, reverse=True), f"{key} must be descending: {values}"


def assert_sorted_asc(rows: List[Dict[str, Any]], key: str) -> None:
    values = [row[key] for row in rows]
    assert values == sorted(values), f"{key} must be ascending: {values}"


def assert_ledger_sum(entries: List[Dict[str, Any]], field: str, expected: float) -> None:
    total = sum(entry[field] or 0 for entry in entries)
    assert abs(float(total) - float(expected)) < 1e-9, (
        f"ledger {field} sums to {total}, expected {expected}"
    )


def max_severity(severities: List[str]) -> Optional[str]:
    """PRD 3.7 total order over severity bands."""
    if not severities:
        return None
    return max(severities, key=SEVERITY_ORDER.index)
