"""Record assertions and domain invariant checkers for the ground handling API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Shared helpers ───────────────────────────────────────────────────────

def as_number(value):
    """Coerce a JSON percentage/multiplier to float without weakening the check."""
    if isinstance(value, str):
        return float(value)
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"Expected a numeric value, got {value!r}")
    return float(value)


def assert_pct(actual, expected, label="percentage"):
    """Assert a two-decimal percentage equals the expected value."""
    value = as_number(actual)
    assert abs(value - expected) < 0.005, (
        f"Expected {label} {expected:.2f}, got {value}")


def assert_common_fields(data: dict, label: str = "record"):
    """Every record type carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID with no type prefix, got {data.get('id')!r}")
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, "
        f"got {data.get('version')!r}")


# ─── Per-record assertions ────────────────────────────────────────────────

def assert_station(data: dict):
    assert_common_fields(data, "station")
    assert data["status"] in ("PLANNED", "OPEN", "SUSPENDED", "CLOSED")
    assert data["season_code"] in ("SUMMER", "WINTER")
    assert data["oversight_posture"] in ("NORMAL", "ENHANCED", "RESTRICTED")
    assert isinstance(data["iata_code"], str) and len(data["iata_code"]) == 3
    assert data["iata_code"].isupper(), "iata_code is three uppercase letters"
    assert isinstance(data["otp_tolerance_minutes"], int)
    assert isinstance(data["gse_reposition_buffer_minutes"], int)
    assert isinstance(data["penalty_cap_cents"], int)
    assert isinstance(data["completed_turn_count"], int)
    assert isinstance(data["on_time_turn_count"], int)
    assert isinstance(data["open_critical_incident_count"], int)
    assert isinstance(data["open_major_incident_count"], int)


def assert_subcontractor(data: dict):
    assert_common_fields(data, "subcontractor")
    assert data["status"] in (
        "PENDING_VETTING", "APPROVED", "PROBATION", "SUSPENDED", "TERMINATED")
    assert data["tier"] in ("TIER_1", "TIER_2")
    assert isinstance(data["oversight_flag"], bool)
    for field in ("compliance_score", "audit_compliance_score"):
        value = as_number(data[field])
        assert 0.0 <= value <= 100.0, f"{field} out of range: {value}"


def assert_flight_bank(data: dict):
    assert_common_fields(data, "flight_bank")
    assert data["bank_status"] in ("DRAFT", "PUBLISHED", "LOCKED", "ARCHIVED")
    assert data["staffing_status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "REVISION_REQUIRED")
    assert data["season_code"] in ("SUMMER", "WINTER")
    assert isinstance(data["planned_headcount"], int)
    assert isinstance(data["required_headcount"], int)
    assert isinstance(data["turn_count"], int)
    as_number(data["staffing_coverage_pct"])


def assert_turn(data: dict):
    assert_common_fields(data, "turn")
    assert data["status"] in (
        "SCHEDULED", "RESOURCED", "IN_PROGRESS", "COMPLETED", "CANCELLED",
        "DISRUPTED")
    assert data["turn_type"] in (
        "TOWING_ONLY", "NARROWBODY_QUICK", "NARROWBODY_STANDARD", "FREIGHTER",
        "WIDEBODY")
    assert data["otp_result"] in ("PENDING", "ON_TIME", "DELAYED", "EXCLUDED")
    assert isinstance(data["required_agent_count"], int)
    assert isinstance(data["required_gse_count"], int)
    assert isinstance(data["assigned_agent_count"], int)
    assert isinstance(data["assigned_gse_count"], int)
    assert isinstance(data["scheduled_ground_minutes"], int)
    assert isinstance(data["billed"], bool)


def assert_agent(data: dict):
    assert_common_fields(data, "agent")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["employment_type"] in ("DIRECT", "SUBCONTRACTED")
    assert data["certification_posture"] in ("CURRENT", "EXPIRING", "LAPSED")
    assert isinstance(data["assigned_duty_minutes"], int)
    assert data["assigned_duty_minutes"] >= 0


def assert_certification(data: dict):
    assert_common_fields(data, "certification")
    assert data["status"] in ("VALID", "REVOKED")
    assert data["currency_state"] in ("CURRENT", "EXPIRING", "LAPSED", "REVOKED")
    assert data["cert_type"] in (
        "RAMP_SAFETY", "PUSHBACK", "BELT_LOADER", "GPU", "DEICING", "LOADMASTER")


def assert_gse_unit(data: dict):
    assert_common_fields(data, "gse_unit")
    assert data["status"] in (
        "AVAILABLE", "IN_MAINTENANCE", "QUARANTINED", "RETIRED")
    assert data["gse_type"] in (
        "PUSHBACK_TUG", "BELT_LOADER", "GPU", "DEICER", "STAIRS")
    assert isinstance(data["condition_score"], int)
    assert 0 <= data["condition_score"] <= 100
    assert isinstance(data["service_interval_cycles"], int)
    assert data["service_interval_cycles"] >= 1
    assert isinstance(data["cycles_since_service"], int)
    assert data["cycles_since_service"] >= 0
    assert isinstance(data["committed_occupation_minutes"], int)
    assert data["committed_occupation_minutes"] >= 0


def assert_turn_resource(data: dict):
    assert_common_fields(data, "turn_resource")
    assert data["resource_kind"] in ("AGENT", "GSE")
    assert data["status"] in ("RESERVED", "COMMITTED", "RELEASED", "CANCELLED")
    assert isinstance(data["occupied_minutes"], int)
    assert data["occupied_minutes"] >= 0
    if data["resource_kind"] == "AGENT":
        assert data["agent_id"], "an agent occupation carries agent_id"
        assert data["role_on_turn"] in (
            "LEAD", "RAMP", "LOADER", "PUSHBACK_OPERATOR", "DEICER")
    else:
        assert data["gse_unit_id"], "an equipment occupation resolves a gse_unit_id"


def assert_incident(data: dict):
    assert_common_fields(data, "incident")
    assert data["status"] in (
        "REPORTED", "UNDER_INVESTIGATION", "FINDINGS_ISSUED", "CLOSED", "REOPENED")
    assert data["incident_type"] in (
        "AIRCRAFT_DAMAGE", "GSE_DAMAGE", "PERSONAL_INJURY", "NEAR_MISS")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert isinstance(data["reopen_count"], int)
    assert 0 <= data["reopen_count"] <= 2


def assert_billing_period(data: dict):
    assert_common_fields(data, "billing_period")
    assert data["status"] in ("OPEN", "PENDING_APPROVAL", "APPROVED")
    assert data["rebate_tier"] in ("NONE", "TIER_A", "TIER_B")
    for field in ("line_count", "accrued_cents", "gross_total_cents",
                  "otp_penalty_cents", "damage_penalty_cents", "rebate_cents",
                  "net_total_cents", "reject_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_billing_line(data: dict):
    assert_common_fields(data, "billing_line")
    assert data["status"] in ("PROVISIONAL", "FINAL", "VOID")
    assert data["turn_type_snapshot"] in (
        "TOWING_ONLY", "NARROWBODY_QUICK", "NARROWBODY_STANDARD", "FREIGHTER",
        "WIDEBODY")
    assert data["ground_time_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    for field in ("base_rate_cents", "charged_ground_minutes", "excess_minutes",
                  "gross_amount_cents", "otp_penalty_cents",
                  "damage_penalty_cents", "rebate_alloc_cents",
                  "net_amount_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer number of cents"


def assert_instant(actual, expected_iso, label="timestamp"):
    """Assert a server-stamped instant equals the expected UTC instant.

    Compares instants, not renderings, so a trailing ".000" is neither
    required nor forbidden.
    """
    from datetime import datetime, timezone

    def parse(value):
        assert isinstance(value, str) and value, f"{label} must be a timestamp, got {value!r}"
        text = value.replace("Z", "+00:00")
        return datetime.fromisoformat(text).astimezone(timezone.utc)

    assert parse(actual) == parse(expected_iso), (
        f"Expected {label} {expected_iso}, got {actual}")


# ─── Domain invariants ────────────────────────────────────────────────────

def assert_line_net_identity(line: dict):
    """net = gross - otp penalty - damage penalty + rebate allocation."""
    expected = (line["gross_amount_cents"]
                - line["otp_penalty_cents"]
                - line["damage_penalty_cents"]
                + line["rebate_alloc_cents"])
    assert line["net_amount_cents"] == expected, (
        f"Line net {line['net_amount_cents']} should be {expected} "
        f"(gross {line['gross_amount_cents']}, otp {line['otp_penalty_cents']}, "
        f"damage {line['damage_penalty_cents']}, "
        f"rebate {line['rebate_alloc_cents']})")


def assert_period_ledger_identity(period: dict):
    """net_total = gross - penalties + rebate, and accrued_cents must equal it."""
    expected = (period["gross_total_cents"]
                - period["otp_penalty_cents"]
                - period["damage_penalty_cents"]
                + period["rebate_cents"])
    assert period["net_total_cents"] == expected, (
        f"Period net_total {period['net_total_cents']} should be {expected}")
    assert period["accrued_cents"] == period["net_total_cents"], (
        f"accrued_cents {period['accrued_cents']} must equal net_total_cents "
        f"{period['net_total_cents']}")


def assert_no_ledger_drift(before: int, after: int, label="ledger"):
    assert before == after, (
        f"{label} drifted: {before} before the forward action, {after} after "
        f"the compensating action")
