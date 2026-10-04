"""Entity assertions and domain invariant checkers."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_ISO_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$"
)


def canonical_iso(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant to exactly three fractional digits.

    The PRD stamps instants as UTC timestamps with three fractional digits; a
    comparison between ``...:00Z`` and ``...:00.000Z`` is a formatting
    difference, not a behavioural one, so timestamp comparisons run through
    this canonicaliser.
    """
    if not isinstance(value, str):
        return value
    match = _ISO_RE.match(value.strip())
    if not match:
        return value
    base, frac, _tz = match.groups()
    frac = (frac or "")[:3].ljust(3, "0")
    return f"{base}.{frac}Z"


def same_instant(left: Optional[str], right: Optional[str]) -> bool:
    """True when two ISO-8601 instants denote the same moment."""
    return canonical_iso(left) == canonical_iso(right)


def _assert_common(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_veteran(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4
    assert data["service_category"] in ("REGULAR_MILITARY", "RESERVES_NATIONAL_GUARD")
    assert data["character_of_discharge"] in (
        "HONORABLE", "GENERAL", "OTHER_THAN_HONORABLE", "BAD_CONDUCT", "DISHONORABLE",
    )
    assert isinstance(data["receives_disability_compensation"], bool)
    assert isinstance(data["is_surviving_spouse"], bool)
    assert isinstance(data["total_qualifying_service_days"], int)
    assert isinstance(data["has_issued_coe"], bool)
    assert isinstance(data["charged_loan_count"], int)


def assert_service_period(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data.get("veteran_id", ""))
    assert data["branch"] in ("ARMY", "NAVY", "AIR_FORCE", "MARINES", "COAST_GUARD", "SPACE_FORCE")
    assert data["discharge_character"] in (
        "HONORABLE", "GENERAL", "OTHER_THAN_HONORABLE", "BAD_CONDUCT", "DISHONORABLE",
    )
    assert isinstance(data["qualifying_days"], int) and data["qualifying_days"] >= 0


def assert_coe(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "DENIED", "RECONSIDERATION", "ISSUED")
    assert data["entitlement_code"] in (
        "ERA_WWII", "ERA_KOREA", "ERA_VIETNAM", "ERA_PEACETIME",
        "ERA_GULF", "RESTORED", "UNREIMBURSED_SURVIVING_SPOUSE",
    )
    assert isinstance(data["reconsideration_count"], int)


def assert_entitlement_account(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["basic_entitlement_cents"] == 3_600_000
    assert data["county_limit_cents"] == 76_655_000
    for field in ("total_charged_cents", "total_restored_cents",
                  "remaining_base_cents", "remaining_with_bonus_cents"):
        assert isinstance(data[field], int), f"{field} must be int cents"
        assert data[field] >= 0, f"{field} must be >= 0"


def assert_loan(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data.get("veteran_id", ""))
    assert is_valid_uuid(data.get("coe_id", ""))
    assert data["purpose"] in ("PURCHASE", "IRRRL", "CASH_OUT_REFINANCE")
    assert data["property_region"] in ("NORTHEAST", "MIDWEST", "SOUTH", "WEST")
    assert data["underwriting_status"] in ("SUBMITTED", "APPROVED", "DENIED")
    assert data["closing_status"] in ("NOT_CLOSED", "CLOSED", "PAID_IN_FULL")
    assert data["loan_use"] in ("FIRST_USE", "SUBSEQUENT_USE")
    assert data["rate_type"] in ("FIXED", "ARM")
    assert isinstance(data["loan_amount_cents"], int)
    assert data["loan_amount_cents"] == data["purchase_price_cents"] - data["down_payment_cents"]


def assert_funding_fee_assessment(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert isinstance(data["exempt"], bool)
    assert data["status"] in ("ASSESSED", "COLLECTED", "REFUNDED")
    for field in ("assessed_fee_cents", "collected_cents", "refunded_cents"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_appraiser(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["region"] in ("NORTHEAST", "MIDWEST", "SOUTH", "WEST")
    assert isinstance(data["max_open_assignments"], int)
    assert isinstance(data["open_assignment_count"], int)
    assert isinstance(data["active"], bool)


def assert_appraisal(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["status"] in (
        "REQUESTED", "ASSIGNED", "REPAIRS_REQUIRED", "VALUE_ISSUED", "CANCELLED",
    )
    assert isinstance(data["report_round"], int)


def assert_repair_requirement(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["status"] in ("OPEN", "COMPLETED", "VERIFIED", "WAIVED")
    assert isinstance(data["required_for_clearance"], bool)


def assert_occupancy_certificate(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["status"] in ("CERTIFIED", "SATISFIED", "EXCEPTED", "VIOLATED")
    assert data["exception_type"] in ("NONE", "DEPLOYMENT")


def assert_deployment_exception(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert is_valid_uuid(data.get("veteran_id", ""))


def assert_underwriting_decision(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["outcome"] in ("APPROVED", "DENIED")
    assert data["region"] in ("NORTHEAST", "MIDWEST", "SOUTH", "WEST")
    assert isinstance(data["dti_only_pass"], bool)
    assert isinstance(data["other_obligations_monthly_cents"], int)
    assert isinstance(data["residual_income_cents"], int)
    assert isinstance(data["residual_required_cents"], int)


def assert_assumption_request(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "APPROVED")
    assert isinstance(data["buyer_is_veteran"], bool)
    assert isinstance(data["substitute_entitlement"], bool)


def assert_refinance_request(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "SUPERSEDED", "APPROVED", "REJECTED")
    assert data["refinance_type"] in ("IRRRL", "CASH_OUT")
    assert data["new_rate_type"] in ("FIXED", "ARM")


def assert_restoration_request(data: Dict[str, Any]) -> None:
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "GRANTED")
    assert data["restoration_type"] in ("SALE_PAYOFF", "REFINANCE_PAYOFF", "ONE_TIME_RESTORATION")


def assert_audit_event(data: Dict[str, Any]) -> None:
    # Append-only: id + created_at only; updated_at / version must be absent.
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "AuditEvent must not carry updated_at"
    assert "version" not in data, "AuditEvent must not carry version"
    assert isinstance(data["entity_type"], str)
    assert isinstance(data["entity_id"], str)
    assert isinstance(data["action"], str)
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_user_id"], str)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_entitlement_invariants(account: Dict[str, Any]) -> None:
    """remaining_* = max(0, capacity - (charged - restored)); capacity constants fixed."""
    in_use = account["total_charged_cents"] - account["total_restored_cents"]
    assert account["remaining_base_cents"] == max(0, 3_600_000 - in_use)
    assert account["remaining_with_bonus_cents"] == max(0, 76_655_000 // 4 - in_use)
