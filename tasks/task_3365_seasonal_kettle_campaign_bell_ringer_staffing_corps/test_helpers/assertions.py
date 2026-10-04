"""Entity assertions and domain invariant checkers."""
import datetime

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_same_instant(actual: str, expected: str, message: str = "") -> None:
    """Compare two instants semantically, not as strings.

    PRD §2.5 pins the *format* of the server-managed `created_at` and
    `updated_at` to "exactly three fractional digits", and §2.2 does the same
    for `api_request_timestamp`. The PRD states no format for the instant a
    caller supplies (`occurred_at`, `placement_starts_on`, ...) when it is
    echoed back, so an implementation may return the same instant in either
    `...:00Z` or `...:00.000Z` form; this helper asserts the instant is
    preserved without pinning an unstated string format.
    """
    def _parse(value):
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(text)

    assert _parse(actual) == _parse(expected), (
        f"{message}expected the instant {expected}, got {actual}"
    )

# Status vocabularies (PRD §2.6, §3.1 - §3.9)
UNIT_TYPES = ["CORPS", "DIVISION", "AREA_COMMAND", "TERRITORY"]
CAMPAIGN_STATUSES = ["PLANNING", "ACTIVE", "CLOSED"]
PERMISSION_STATUSES = ["PENDING", "APPROVED", "DENIED", "EXPIRED", "REVOKED"]
LOCATION_STATUSES = ["DRAFT", "ACTIVE", "SUSPENDED", "CLOSED"]
SCREENING_STATUSES = ["NOT_STARTED", "PENDING", "CLEARED", "FAILED", "EXPIRED"]
ENGAGEMENT_STATUSES = ["ACTIVE", "SUSPENDED", "SEPARATED"]
SHIFT_STATUSES = ["SCHEDULED", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW"]
DEPOSIT_STATUSES = ["SUBMITTED", "VERIFIED", "VARIANCE_HOLD", "DEPOSITED", "RECONCILED"]
ATTRIBUTION_STATUSES = ["RECEIVED", "UNATTRIBUTED", "ATTRIBUTED", "REVERSED"]
ELIGIBILITY_STATUSES = ["SUBMITTED", "SCREENING", "ELIGIBLE", "INELIGIBLE", "WAITLISTED",
                        "APPROVED", "DISTRIBUTION_SCHEDULED", "DISTRIBUTED", "NO_SHOW"]
PROGRAM_STATUSES = ["PLANNED", "ACTIVE", "SUSPENDED", "COMPLETED"]
DEPLOYMENT_STATUSES = ["REQUESTED", "APPROVED", "STAGED", "DEPLOYED", "DEMOBILIZED",
                       "DENIED", "CANCELLED"]
REALLOCATION_STATUSES = ["PROPOSED", "APPROVED", "APPLIED", "REJECTED"]


def _assert_common_fields(data: dict):
    """PRD §2.5: every top-level resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"


def assert_unit(data: dict):
    _assert_common_fields(data)
    assert data["unit_type"] in UNIT_TYPES
    assert isinstance(data["territory_code"], str) and len(data["territory_code"]) == 2
    assert isinstance(data["canteen_pool_size"], int)
    assert isinstance(data["committed_canteen_count"], int)
    assert isinstance(data["oversight_level"], int)


def assert_campaign(data: dict):
    _assert_common_fields(data)
    assert data["status"] in CAMPAIGN_STATUSES
    assert isinstance(data["goal_cents"], int)
    assert isinstance(data["labor_budget_cents"], int)
    assert isinstance(data["total_raised_cents"], int)
    assert isinstance(data["labor_committed_cents"], int)


def assert_host_site(data: dict):
    _assert_common_fields(data)
    assert data["permission_status"] in PERMISSION_STATUSES
    assert data["exclusivity_scope"] in ["EXCLUSIVE", "NON_EXCLUSIVE"]
    assert isinstance(data["max_kettles"], int)
    assert isinstance(data["active_kettle_count"], int)


def assert_kettle_location(data: dict):
    _assert_common_fields(data)
    assert data["status"] in LOCATION_STATUSES
    assert data["placement"] in ["INDOOR", "OUTDOOR", "DRIVE_THROUGH"]
    assert isinstance(data["daily_required_minutes"], int)
    assert isinstance(data["covered_minutes"], int)
    assert isinstance(data["location_total_cents"], int)


def assert_bell_ringer(data: dict):
    _assert_common_fields(data)
    assert data["screening_status"] in SCREENING_STATUSES
    assert data["engagement_status"] in ENGAGEMENT_STATUSES
    assert data["ringer_type"] in ["VOLUNTEER", "PAID_SEASONAL"]
    assert 0 <= data["reliability_score"] <= 100, "reliability_score is clamped to 0..100"
    assert isinstance(data["scheduled_hours"], (int, float))


def assert_shift(data: dict):
    _assert_common_fields(data)
    assert data["status"] in SHIFT_STATUSES
    assert data["shift_kind"] in ["REGULAR", "RELIEF", "DOUBLE"]
    assert isinstance(data["break_minutes"], int)


def assert_kettle_collection(data: dict):
    _assert_common_fields(data)
    assert data["deposit_status"] in DEPOSIT_STATUSES
    assert isinstance(data["counted_total_cents"], int)
    assert isinstance(data["handling_fee_cents"], int)
    assert isinstance(data["variance_cents"], int)


def assert_digital_giving(data: dict):
    _assert_common_fields(data)
    assert data["attribution_status"] in ATTRIBUTION_STATUSES
    assert data["channel"] in ["QR", "SMS", "TERMINAL", "ONLINE"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["attributed_cents"], int)


def assert_assistance_program(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "OPEN", "CLOSED"]
    assert data["program_type"] in ["TOY", "FOOD", "COAT", "HYGIENE"]
    assert isinstance(data["household_cap"], int)
    assert isinstance(data["accepted_application_count"], int)


def assert_assistance_application(data: dict):
    _assert_common_fields(data)
    assert data["eligibility_status"] in ELIGIBILITY_STATUSES
    assert data["distribution_status"] in ["NOT_SCHEDULED", "SCHEDULED", "COMPLETED", "NO_SHOW"]
    assert 0 <= data["provisional_score"] <= 100
    assert 0 <= data["eligibility_score"] <= 100


def assert_corps_program(data: dict):
    _assert_common_fields(data)
    assert data["status"] in PROGRAM_STATUSES
    assert data["category"] in ["YOUTH", "SENIOR", "WORSHIP", "COMMUNITY"]
    assert isinstance(data["enrolled_count"], int)
    assert isinstance(data["waitlist_count"], int)


def assert_disaster_deployment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in DEPLOYMENT_STATUSES
    assert data["incident_command_level"] in ["TYPE_1", "TYPE_2", "TYPE_3", "TYPE_4", "TYPE_5"]
    assert isinstance(data["assigned_canteen_count"], int)
    assert isinstance(data["deployment_cost_cents"], int)


def assert_reallocation_decision(data: dict):
    _assert_common_fields(data)
    assert data["status"] in REALLOCATION_STATUSES
    assert isinstance(data["moved_hours"], (int, float))
    assert isinstance(data["expected_lift_cents"], int)


# --- Domain invariants ---------------------------------------------------
def assert_location_performance_shape(data: dict):
    """The performance read exposes the nine figures listed in PRD §3.9."""
    for field in ("location_id", "location_total_cents", "covered_minutes", "covered_hours",
                  "cents_per_hour", "performance_index", "performance_tier", "coverage_pct",
                  "understaffed"):
        assert field in data, f"performance read must expose {field}"
    assert data["performance_tier"] in ["UNRATED", "BRONZE", "SILVER", "GOLD", "PLATINUM"]
    assert isinstance(data["understaffed"], bool)
    assert data["covered_hours"] >= 0
    assert data["cents_per_hour"] >= 0
    assert 0 <= data["coverage_pct"]


def assert_campaign_total_invariant(summary: dict):
    """PRD §3.9: total_raised_cents is the sum of the two components."""
    assert summary["total_raised_cents"] == (
        summary["collections_counted_cents"] + summary["digital_attributed_cents"]
    ), "campaign total must equal counted collections plus attributed digital gifts"


def assert_counted_total_invariant(collection: dict):
    """PRD §3.4: counted_total_cents is the sum of the three teller counts."""
    assert collection["counted_total_cents"] == (
        collection["coin_cents"] + collection["currency_cents"] + collection["check_cents"]
    ), "counted_total_cents must equal coin + currency + check"


def assert_non_negative_assistance_income(application: dict):
    """PRD §3.6: the per-member asset deduction floors adjusted income at zero."""
    assert application["verified_income_cents"] >= 0
    assert application["annual_income_cents"] >= 0
