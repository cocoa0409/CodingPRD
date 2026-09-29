"""Entity assertions and domain invariant checkers for the PRD's resources."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant

_MUTABLE_COMMON = ("id", "created_at", "updated_at", "version")


def _assert_common_mutable(data: Dict[str, Any], label: str) -> None:
    """id + created_at + updated_at + version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def assert_instant_equals(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Compare two ISO 8601 UTC instants without depending on sub-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_program(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "Program")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["fiscal_year"], int)
    assert data["qualification_metric"] in ("NET_REVENUE_CENTS", "UNITS_SOLD", "MARGIN_CENTS")
    assert data["status"] in (
        "DESIGN", "SOURCING", "CONTRACTED", "REGISTRATION_OPEN",
        "ONSITE", "RECONCILED", "CLOSED", "CANCELLED",
    )
    assert data["gross_up_policy"] in ("NONE", "FLAT_SUPPLEMENTAL", "FULL_GROSS_UP")
    assert isinstance(data["gross_up_policy_locked"], bool)
    assert data["budget_posture"] in ("OK", "WATCH", "OVERCOMMITTED")
    for field in (
        "budget_total_cents", "per_person_cost_basis_cents", "committed_budget_cents",
        "budget_headroom_cents", "cancellation_exposure_cents", "reported_award_total_cents",
        "qualified_count", "travelled_count",
    ):
        assert isinstance(data[field], int), f"Program.{field} must be an integer, got {data[field]!r}"


def assert_award_tier(data: Dict[str, Any]) -> None:
    """An award tier is immutable: no `updated_at`, no `version` (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "AwardTier.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), "AwardTier.created_at must be ISO 8601"
    assert "updated_at" not in data, "AwardTier must not carry updated_at"
    assert "version" not in data, "AwardTier must not carry version"
    assert isinstance(data["tier_code"], str) and data["tier_code"]
    assert isinstance(data["tier_rank"], int) and data["tier_rank"] >= 1
    for field in (
        "qualification_threshold", "budget_per_qualifier_cents",
        "guest_allowance", "upgrade_allowance_cents", "service_load_bp",
    ):
        assert isinstance(data[field], int), f"AwardTier.{field} must be an integer"
    assert data["air_cabin_class"] in ("ECONOMY", "PREMIUM_ECONOMY", "BUSINESS")


def assert_qualifier(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "Qualifier")
    assert data["award_status"] in (
        "PENDING_REVIEW", "QUALIFIED", "DISQUALIFIED", "NOTIFIED",
        "REGISTERED", "TRAVELLED", "WITHDRAWN",
    )
    assert data["tax_status"] in ("NOT_APPLICABLE", "PENDING_REPORT", "REPORTED", "VOIDED")
    for field in ("baseline_metric", "actual_metric", "guest_count",
                  "committed_cost_cents", "taxable_award_cents"):
        assert isinstance(data[field], int), f"Qualifier.{field} must be an integer"


def assert_destination(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "Destination")
    assert data["status"] in ("CANDIDATE", "SHORTLISTED", "SELECTED", "REJECTED")
    assert data["inspection_status"] in ("NOT_INSPECTED", "INSPECTED")
    assert isinstance(data["per_person_cost_cents"], int)
    assert isinstance(data["risk_score"], int)
    assert len(data["country_code"]) == 2
    assert len(data["air_gateway_code"]) == 3


def assert_supplier_contract(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "SupplierContract")
    assert data["status"] in ("DRAFT", "PROPOSED", "COUNTERED", "EXECUTED", "WITHDRAWN")
    assert data["supplier_kind"] in ("HOTEL", "DMC", "AIR_CONSOLIDATOR")
    assert data["force_majeure_clause"] in ("NONE", "STANDARD", "EXPANDED")
    assert data["exposure_basis"] in ("ATTRITION_BASIS", "DEPOSIT_FORFEITURE_BASIS")
    assert data["attrition_posture"] in ("CLEAR", "AT_RISK")
    for field in (
        "round_count", "room_block_count", "contracted_nights", "nightly_rate_cents",
        "attrition_allowance_bp", "room_nights_blocked", "room_nights_confirmed",
        "room_nights_available",
    ):
        assert isinstance(data[field], int), f"SupplierContract.{field} must be an integer"


def assert_deposit_milestone(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "DepositMilestone")
    assert data["status"] in ("SCHEDULED", "PAID", "FORFEITED", "REFUNDED", "CANCELLED")
    assert isinstance(data["requires_finance_review"], bool)
    for field in ("sequence", "amount_cents", "refundable_bp"):
        assert isinstance(data[field], int), f"DepositMilestone.{field} must be an integer"


def assert_registration(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "Registration")
    assert data["registration_kind"] in ("WINNER", "GUEST")
    assert data["attendance_status"] in (
        "INVITED", "ACCEPTED", "DECLINED", "CONFIRMED", "CANCELLED", "TRAVELLED",
    )
    assert data["air_status"] in (
        "NOT_REQUESTED", "REQUESTED", "TICKETED", "CHANGE_PENDING", "VOIDED",
    )
    assert isinstance(data["waiver_on_file"], bool)
    for field in (
        "rooms", "room_nights", "air_deviation_pre_days", "air_deviation_post_days",
        "air_base_fare_cents", "air_upgrade_cost_cents", "air_deviation_fee_cents",
        "air_change_count", "air_change_fee_total_cents", "cost_cents",
    ):
        assert isinstance(data[field], int), f"Registration.{field} must be an integer"


def assert_onsite_activity(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "OnsiteActivity")
    assert data["status"] in ("OPEN", "CLOSED", "CANCELLED")
    assert data["risk_level"] in ("LOW", "MEDIUM", "HIGH")
    for field in ("capacity", "booked_count", "waitlist_count"):
        assert isinstance(data[field], int), f"OnsiteActivity.{field} must be an integer"


def assert_activity_signup(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "ActivitySignup")
    assert data["status"] in ("BOOKED", "WAITLISTED", "CANCELLED")


def assert_tax_award_report(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "TaxAwardReport")
    assert data["status"] in ("DRAFT", "FILED", "VOIDED")
    assert data["gross_up_method"] in ("NONE", "FLAT_SUPPLEMENTAL", "FULL_GROSS_UP")
    for field in ("tax_year", "award_value_cents", "combined_rate_bp",
                  "gross_up_cents", "reported_value_cents"):
        assert isinstance(data[field], int), f"TaxAwardReport.{field} must be an integer"


# ─── Domain invariants (PRD §2.10) ───────────────────────────────────────────

def assert_budget_conserved(program: Dict[str, Any]) -> None:
    """committed_budget_cents + budget_headroom_cents == budget_total_cents."""
    assert (
        program["committed_budget_cents"] + program["budget_headroom_cents"]
        == program["budget_total_cents"]
    ), (
        "Budget identity broken: committed "
        f"{program['committed_budget_cents']} + headroom {program['budget_headroom_cents']} "
        f"!= total {program['budget_total_cents']}"
    )


def assert_room_nights_conserved(contract: Dict[str, Any]) -> None:
    """room_nights_blocked == room_nights_confirmed + room_nights_available."""
    assert (
        contract["room_nights_confirmed"] + contract["room_nights_available"]
        == contract["room_nights_blocked"]
    ), (
        "Room-night identity broken: confirmed "
        f"{contract['room_nights_confirmed']} + available {contract['room_nights_available']} "
        f"!= blocked {contract['room_nights_blocked']}"
    )


def assert_reported_value_identity(report: Dict[str, Any]) -> None:
    """reported_value_cents == award_value_cents + gross_up_cents (PRD §3.9)."""
    assert report["reported_value_cents"] == report["award_value_cents"] + report["gross_up_cents"], (
        f"reported_value_cents {report['reported_value_cents']} != award_value_cents "
        f"{report['award_value_cents']} + gross_up_cents {report['gross_up_cents']}"
    )


def assert_signup_counters(activity: Dict[str, Any], booked: int, waitlisted: int) -> None:
    assert activity["booked_count"] == booked, (
        f"Expected booked_count {booked}, got {activity['booked_count']}"
    )
    assert activity["waitlist_count"] == waitlisted, (
        f"Expected waitlist_count {waitlisted}, got {activity['waitlist_count']}"
    )


def assert_version_is(data: Dict[str, Any], expected: int, label: str = "row") -> None:
    assert data["version"] == expected, (
        f"{label}.version expected {expected}, got {data['version']}"
    )
