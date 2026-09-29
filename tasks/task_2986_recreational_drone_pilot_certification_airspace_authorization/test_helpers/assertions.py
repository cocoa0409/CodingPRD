"""Per-entity shape assertions, instant helpers and domain invariant checkers."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_valid_uuid, validate_paginated

from .constants import (
    BLOCKING_FINDING_CODES_SORTED,
    MIN_COMMERCIAL_COVERAGE_CENTS,
)

# ---------------------------------------------------------------------------
# Instant helpers
#
# Every stored datetime is a whole-second ISO 8601 UTC instant with a literal `Z`
# suffix and no fractional part. The helpers below parse and re-emit exactly that
# form so an expected instant can be computed inside a test.
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def format_instant(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_instant(value: Optional[str]) -> Optional[str]:
    """Reduce an instant to the canonical whole-second `...Z` form for comparison."""
    if value is None:
        return None
    return format_instant(parse_instant(value))


def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def shift_days(value: str, days: int) -> str:
    return format_instant(parse_instant(value) + timedelta(days=days))


def shift_minutes(value: str, minutes: int) -> str:
    return format_instant(parse_instant(value) + timedelta(minutes=minutes))


def shift_hours(value: str, hours: int) -> str:
    return format_instant(parse_instant(value) + timedelta(hours=hours))


def add_calendar_months(value: str, months: int) -> str:
    """Advance by whole calendar months, clamping the day down to the target month's last day."""
    moment = parse_instant(value)
    total = (moment.year * 12 + (moment.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    if month == 12:
        next_month_start = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month_start = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    last_day = (next_month_start - timedelta(days=1)).day
    day = min(moment.day, last_day)
    return format_instant(moment.replace(year=year, month=month, day=day))


def round_half_up(value: Decimal) -> int:
    """Round a cent quantity to a whole number of cents, halves away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def multiply_cents(amount_cents: int, factor: str) -> int:
    """Multiply a cent figure by a rate and round half-up at the multiplication."""
    return round_half_up(Decimal(amount_cents) * Decimal(factor))


def round_one_decimal(value: Decimal) -> float:
    return float(Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Envelope / identity helpers
# ---------------------------------------------------------------------------


def assert_identity_fields(entity: Dict[str, Any], label: str = "entity") -> None:
    """`id` is a UUID with no type prefix, and `created_at` is an instant."""
    assert is_valid_uuid(entity.get("id")), f"{label}.id must be a UUID, got {entity.get('id')!r}"
    assert isinstance(entity.get("created_at"), str), f"{label}.created_at must be a string"
    parse_instant(entity["created_at"])


def assert_versioned_entity(entity: Dict[str, Any], label: str = "entity") -> None:
    """Identity plus the `updated_at` and `version` almost every resource carries."""
    assert_identity_fields(entity, label)
    assert isinstance(entity.get("updated_at"), str), f"{label}.updated_at must be a string"
    parse_instant(entity["updated_at"])
    assert isinstance(entity.get("version"), int), f"{label}.version must be an integer"
    assert entity["version"] >= 1, f"{label}.version starts at 1"


def assert_no_version_fields(entity: Dict[str, Any], label: str = "entity") -> None:
    """An immutable record carries neither `updated_at` nor `version` in its representation."""
    assert "updated_at" not in entity, f"{label} must not carry updated_at"
    assert "version" not in entity, f"{label} must not carry version"


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------


def assert_pilot(pilot: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_versioned_entity(pilot, "pilot")
    for key in (
        "full_name",
        "email",
        "operator_category",
        "status",
        "currency_basis",
        "risk_score",
        "knowledge_attempt_count",
        "open_waiver_count",
    ):
        assert key in pilot, f"pilot must expose {key}"
    assert isinstance(pilot["risk_score"], int)
    assert 0 <= pilot["risk_score"] <= 100, "risk_score is clamped to 0..100"
    assert isinstance(pilot["knowledge_attempt_count"], int)
    assert isinstance(pilot["open_waiver_count"], int)
    _check_expected(pilot, expected, "pilot")
    return pilot


def assert_knowledge_test(test: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_versioned_entity(test, "knowledge_test")
    for key in ("pilot_id", "test_code", "scheduled_at", "attempt_number", "status"):
        assert key in test, f"knowledge_test must expose {key}"
    assert isinstance(test["attempt_number"], int)
    _check_expected(test, expected, "knowledge_test")
    return test


def assert_certification(certification: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_versioned_entity(certification, "certification")
    for key in (
        "pilot_id",
        "originating_test_id",
        "certificate_number",
        "category",
        "status",
        "issued_at",
        "expires_at",
    ):
        assert key in certification, f"certification must expose {key}"
    number = certification["certificate_number"]
    assert isinstance(number, str) and number.startswith("CERT-"), (
        f"certificate_number must start with the literal prefix CERT-, got {number!r}"
    )
    assert len(number) == len("CERT-") + 6 and number[5:].isdigit(), (
        f"certificate_number must be CERT- followed by a six-digit zero-padded sequence, got {number!r}"
    )
    _check_expected(certification, expected, "certification")
    return certification


def assert_aircraft(aircraft: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_versioned_entity(aircraft, "aircraft")
    for key in (
        "owner_pilot_id",
        "model",
        "serial_number",
        "takeoff_weight_g",
        "max_altitude_ft",
        "remote_id_required",
        "registration_status",
    ):
        assert key in aircraft, f"aircraft must expose {key}"
    assert isinstance(aircraft["remote_id_required"], bool)
    assert isinstance(aircraft["takeoff_weight_g"], int)
    assert isinstance(aircraft["max_altitude_ft"], int)
    _check_expected(aircraft, expected, "aircraft")
    return aircraft


def assert_module(module: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_versioned_entity(module, "remote_id_module")
    for key in (
        "aircraft_id",
        "module_serial",
        "broadcast_protocol",
        "firmware_version",
        "status",
    ):
        assert key in module, f"remote_id_module must expose {key}"
    assert module["broadcast_protocol"] in ("WIFI_NAN", "BLUETOOTH_LE"), (
        f"broadcast_protocol must be WIFI_NAN or BLUETOOTH_LE, got {module['broadcast_protocol']!r}"
    )
    _check_expected(module, expected, "remote_id_module")
    return module


def assert_zone(zone: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_versioned_entity(zone, "airspace_zone")
    for key in (
        "designator",
        "class_code",
        "class_ceiling_ft",
        "requires_authorization",
        "max_concurrent_authorizations",
        "structure_relief_eligible",
        "reserved_slot_count",
    ):
        assert key in zone, f"airspace_zone must expose {key}"
    assert zone["class_code"] in ("B", "C", "D", "E", "G")
    assert isinstance(zone["reserved_slot_count"], int)
    assert zone["reserved_slot_count"] >= 0, "reserved_slot_count is never negative"
    assert isinstance(zone["structure_relief_eligible"], bool)
    _check_expected(zone, expected, "airspace_zone")
    return zone


def assert_tfr(tfr: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_versioned_entity(tfr, "tfr")
    for key in (
        "zone_id",
        "reason",
        "effective_from",
        "effective_until",
        "max_permitted_altitude_ft",
        "status",
        "published_by_user_id",
    ):
        assert key in tfr, f"tfr must expose {key}"
    _check_expected(tfr, expected, "tfr")
    return tfr


def assert_authorization(authorization: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_versioned_entity(authorization, "authorization")
    for key in (
        "pilot_id",
        "aircraft_id",
        "zone_id",
        "requested_ceiling_ft",
        "granted_ceiling_ft",
        "window_start",
        "window_end",
        "status",
        "approved_by_user_id",
        "decided_at",
        "denial_reason",
    ):
        assert key in authorization, f"authorization must expose {key}"
    _check_expected(authorization, expected, "authorization")
    return authorization


def assert_waiver(waiver: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_versioned_entity(waiver, "waiver")
    for key in (
        "pilot_id",
        "aircraft_id",
        "waiver_type",
        "requested_ceiling_ft",
        "operation_description",
        "status",
        "revision_round",
        "granted_ceiling_ft",
        "valid_until",
    ):
        assert key in waiver, f"waiver must expose {key}"
    assert isinstance(waiver["revision_round"], int)
    _check_expected(waiver, expected, "waiver")
    return waiver


def assert_safety_case(case: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_versioned_entity(case, "safety_case")
    for key in (
        "waiver_id",
        "mitigation_summary",
        "ground_risk_class",
        "air_risk_class",
        "contingency_procedures",
        "sail_level",
        "review_status",
    ):
        assert key in case, f"safety_case must expose {key}"
    assert isinstance(case["sail_level"], int)
    assert 1 <= case["sail_level"] <= 6, "sail_level is an integer from 1 to 6 inclusive"
    _check_expected(case, expected, "safety_case")
    return case


def assert_policy(policy: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_versioned_entity(policy, "policy")
    for key in (
        "pilot_id",
        "insurer_name",
        "policy_number",
        "coverage_limit_cents",
        "deductible_cents",
        "effective_from",
        "effective_until",
        "indemnification_clause_accepted",
        "coverage_status",
        "open_reserved_cents_total",
        "settled_cents_total",
        "remaining_coverage_cents",
    ):
        assert key in policy, f"policy must expose {key}"
    for money in (
        "coverage_limit_cents",
        "deductible_cents",
        "open_reserved_cents_total",
        "settled_cents_total",
        "remaining_coverage_cents",
    ):
        value = policy[money]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"policy.{money} must be a whole number of cents as an integer, got {value!r}"
        )
        assert value >= 0, f"policy.{money} must be non-negative, got {value}"
    _check_expected(policy, expected, "policy")
    return policy


def assert_flight(flight: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_versioned_entity(flight, "flight")
    for key in (
        "pilot_id",
        "aircraft_id",
        "zone_id",
        "operation_category",
        "planned_start",
        "planned_end",
        "planned_max_altitude_ft",
        "launch_latitude",
        "launch_longitude",
        "over_people",
        "night_operation",
        "beyond_visual_line_of_sight",
        "status",
        "investigation_status",
        "logged_minutes",
        "altitude_exceedance",
    ):
        assert key in flight, f"flight must expose {key}"
    assert isinstance(flight["logged_minutes"], int)
    assert isinstance(flight["altitude_exceedance"], bool)
    _check_expected(flight, expected, "flight")
    return flight


def assert_preflight_check(check: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    """A pre-flight check is immutable: only `id` and `created_at`, no version fields."""
    assert_identity_fields(check, "preflight_check")
    assert_no_version_fields(check, "preflight_check")
    for key in (
        "flight_id",
        "checked_at",
        "result",
        "blocking_findings",
        "active_tfr_ids",
        "acknowledged_tfr_ids",
        "airspace_class_code",
        "effective_ceiling_ft",
    ):
        assert key in check, f"preflight_check must expose {key}"
    findings = check["blocking_findings"]
    assert isinstance(findings, list), "blocking_findings must be an array"
    assert findings == sorted(findings), (
        f"blocking_findings must be sorted ascending by code, got {findings}"
    )
    assert len(findings) == len(set(findings)), "blocking_findings must contain no duplicates"
    for code in findings:
        assert code in BLOCKING_FINDING_CODES_SORTED, f"unexpected finding code {code!r}"
    expected_result = "PASSED" if not findings else "FAILED"
    assert check["result"] == expected_result, (
        f"result must be PASSED exactly when blocking_findings is empty; "
        f"got {check['result']!r} with findings {findings}"
    )
    assert isinstance(check["active_tfr_ids"], list)
    assert isinstance(check["acknowledged_tfr_ids"], list)
    assert isinstance(check["effective_ceiling_ft"], int)
    _check_expected(check, expected, "preflight_check")
    return check


def assert_accident_report(report: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    assert_versioned_entity(report, "accident_report")
    for key in (
        "flight_id",
        "policy_id",
        "occurred_at",
        "injury_level",
        "reported_property_damage_cents",
        "narrative",
        "status",
        "remediation_round",
        "reserved_cents",
        "settlement_cents",
    ):
        assert key in report, f"accident_report must expose {key}"
    for money in ("reported_property_damage_cents", "reserved_cents"):
        value = report[money]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"accident_report.{money} must be an integer number of cents, got {value!r}"
        )
        assert value >= 0, f"accident_report.{money} must be non-negative"
    if report["settlement_cents"] is not None:
        assert isinstance(report["settlement_cents"], int)
        assert report["settlement_cents"] >= 0
    assert isinstance(report["remediation_round"], int)
    _check_expected(report, expected, "accident_report")
    return report


def assert_currency_projection(projection: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    for key in (
        "projected_expires_at",
        "basis_applied",
        "base_expiry",
        "recency_expiry",
        "days_remaining",
        "lapse_due",
    ):
        assert key in projection, f"currency projection must expose {key}"
    assert isinstance(projection["days_remaining"], int)
    assert isinstance(projection["lapse_due"], bool)
    assert projection["basis_applied"] in ("RECREATIONAL_BASIS", "COMMERCIAL_BASIS")
    _check_expected(projection, expected, "currency_projection")
    return projection


def assert_flight_summary(summary: Dict[str, Any], **expected: Any) -> Dict[str, Any]:
    for key in (
        "completed_flight_count",
        "total_logged_minutes",
        "max_altitude_reached_ft",
        "incident_flight_count",
        "exceedance_flight_count",
        "average_duration_minutes",
        "window_start",
        "window_end",
    ):
        assert key in summary, f"flight summary must expose {key}"
    for count in (
        "completed_flight_count",
        "total_logged_minutes",
        "max_altitude_reached_ft",
        "incident_flight_count",
        "exceedance_flight_count",
    ):
        assert isinstance(summary[count], int), f"{count} must be an integer"
        assert summary[count] is not None, f"{count} is never null"
    assert summary["average_duration_minutes"] is not None, (
        "average_duration_minutes is never null"
    )
    assert isinstance(summary["average_duration_minutes"], (int, float))
    _check_expected(summary, expected, "flight_summary")
    return summary


def _check_expected(entity: Dict[str, Any], expected: Dict[str, Any], label: str) -> None:
    for key, want in expected.items():
        assert key in entity, f"{label} is missing {key}"
        got = entity[key]
        if isinstance(want, str) and key.endswith(
            (
                "_at",
                "_until",
                "_from",
                "_start",
                "_end",
            )
        ):
            assert_instant_equals(got, want, f"{label}.{key}")
        else:
            assert got == want, f"{label}.{key}: expected {want!r}, got {got!r}"


# ---------------------------------------------------------------------------
# List ordering
# ---------------------------------------------------------------------------


def assert_created_at_ascending(records: List[Dict[str, Any]], label: str = "list") -> None:
    stamps = [parse_instant(r["created_at"]) for r in records]
    assert stamps == sorted(stamps), f"{label} must be ordered by created_at ascending"


def assert_created_at_descending(records: List[Dict[str, Any]], label: str = "list") -> None:
    stamps = [parse_instant(r["created_at"]) for r in records]
    assert stamps == sorted(stamps, reverse=True), (
        f"{label} must be ordered by created_at descending"
    )


def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_limit: int,
    expected_offset: int,
    expected_total: int,
) -> None:
    assert meta["limit"] == expected_limit, f"meta.limit: expected {expected_limit}, got {meta['limit']}"
    assert meta["offset"] == expected_offset, (
        f"meta.offset: expected {expected_offset}, got {meta['offset']}"
    )
    assert meta["total_count"] == expected_total, (
        f"meta.total_count is the size of the full filtered set before the window; "
        f"expected {expected_total}, got {meta['total_count']}"
    )
    expected_has_more = expected_offset + expected_limit < expected_total
    assert meta["has_more"] is expected_has_more, (
        f"meta.has_more must be true exactly when records remain beyond the window; "
        f"expected {expected_has_more}, got {meta['has_more']}"
    )


def paginated_ids(response) -> List[str]:
    records, _ = validate_paginated(response)
    return [r["id"] for r in records]


# ---------------------------------------------------------------------------
# Conserved quantities
# ---------------------------------------------------------------------------

SLOT_HOLDING_STATUSES = ("APPROVED", "ACTIVE")
OPEN_REPORT_STATUSES = ("FILED", "INVESTIGATING", "REMEDIATION_REQUIRED")


def assert_zone_slot_conservation(api, zone_id: str, headers: Dict[str, str]) -> Dict[str, Any]:
    """`reserved_slot_count` equals the count of that zone's APPROVED or ACTIVE authorizations."""
    zone = _data(api.get_zone(zone_id, headers=headers))
    records, meta = validate_paginated(
        api.list_authorizations(params={"zone_id": zone_id, "limit": 100}, headers=headers)
    )
    holding = [r for r in records if r["status"] in SLOT_HOLDING_STATUSES]
    assert zone["reserved_slot_count"] == len(holding), (
        f"reserved_slot_count must equal the number of APPROVED or ACTIVE authorizations on the "
        f"zone; zone reports {zone['reserved_slot_count']} but "
        f"{len(holding)} authorizations hold a slot "
        f"(statuses seen: {[r['status'] for r in records]})"
    )
    assert zone["reserved_slot_count"] >= 0, "reserved_slot_count is never negative"
    return zone


def assert_coverage_ledger_conservation(
    api, policy_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    """`coverage_limit_cents` equals remaining + open reserved + settled, with zero drift."""
    policy = _data(api.get_policy(policy_id, headers=headers))
    total = (
        policy["remaining_coverage_cents"]
        + policy["open_reserved_cents_total"]
        + policy["settled_cents_total"]
    )
    assert policy["coverage_limit_cents"] == total, (
        f"coverage_limit_cents must equal remaining + open reserved + settled; "
        f"limit {policy['coverage_limit_cents']} != "
        f"{policy['remaining_coverage_cents']} + {policy['open_reserved_cents_total']} + "
        f"{policy['settled_cents_total']}"
    )
    records, _ = validate_paginated(
        api.list_accident_reports(params={"policy_id": policy_id, "limit": 100}, headers=headers)
    )
    open_reserved = sum(r["reserved_cents"] for r in records if r["status"] in OPEN_REPORT_STATUSES)
    settled = sum(
        (r["settlement_cents"] or 0) for r in records if r["status"] == "CLOSED"
    )
    assert policy["open_reserved_cents_total"] == open_reserved, (
        f"open_reserved_cents_total must be the sum of reserved_cents over the policy's FILED, "
        f"INVESTIGATING and REMEDIATION_REQUIRED reports; expected {open_reserved}, got "
        f"{policy['open_reserved_cents_total']}"
    )
    assert policy["settled_cents_total"] == settled, (
        f"settled_cents_total must be the sum of settlement_cents over the policy's CLOSED "
        f"reports; expected {settled}, got {policy['settled_cents_total']}"
    )
    return policy


def expected_coverage_status(policy: Dict[str, Any]) -> str:
    """The status an ACTIVE/INSUFFICIENT policy should carry given its remaining cover."""
    return (
        "INSUFFICIENT"
        if policy["remaining_coverage_cents"] < MIN_COMMERCIAL_COVERAGE_CENTS
        else "ACTIVE"
    )


def _data(response) -> Dict[str, Any]:
    """Unwrap the success envelope exactly once."""
    assert 200 <= response.status_code < 300, (
        f"expected a success response, got {response.status_code}: {response.text}"
    )
    return response.json()["data"]
