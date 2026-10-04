"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

QUARTET_ENTITIES = [
    "Branch",
    "MembershipPlan",
    "Campaign",
    "PricebookTask",
    "Technician",
    "Appointment",
    "PricebookOverrideRequest",
    "MembershipAgreement",
    "MembershipVisit",
    "CallRecord",
]


def assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_branch(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"], "name must be non-empty"
    assert len(data["postal_code"]) == 5, "postal_code must be five digits"
    assert data["daily_dispatch_capacity_hours"] > 0
    assert data["capacity_consumed_hours"] >= 0
    assert isinstance(data["membership_count_active"], int)


def assert_membership_plan(data: dict):
    assert_common_fields(data)
    assert data["annual_price_cents"] > 0
    assert data["included_service_visit_count"] >= 1
    assert data["maintenance_visit_interval_days"] >= 1
    assert 0 <= data["included_labor_discount_pct"] <= 1
    assert data["status"] in ["DRAFT", "PUBLISHED", "RETIRED"]


def assert_campaign(data: dict):
    assert_common_fields(data)
    assert data["channel"] in ["SEARCH", "YARD_SIGN", "REFERRAL", "DIRECT_MAIL", "ORGANIC"]
    assert data["spend_cents"] >= 0


def assert_pricebook_task(data: dict):
    assert_common_fields(data)
    assert data["code"] == data["code"].upper()
    assert data["category"] in ["HVAC", "PLUMBING", "ELECTRICAL", "APPLIANCE", "GENERAL"]
    assert data["estimated_hours"] > 0
    assert data["flat_rate_cents"] >= 0
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in ["DRAFT", "PUBLISHED", "RETIRED"]


def assert_technician(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert len(data["postal_code"]) == 5
    assert isinstance(data["skill_codes"], list)
    assert len(data["shift_segments"]) >= 1
    assert data["daily_capacity_hours"] > 0
    assert data["status"] in ["AVAILABLE", "ON_SHIFT", "ON_JOB", "OFF_SHIFT"]
    assert data["performance_status"] in ["CLEAR", "COACHING", "PROBATION"]
    assert isinstance(data["sales_coaching_strike_count"], int)
    assert isinstance(data["scheduled_hours"], (int, float))
    assert isinstance(data["dispatched_hours"], (int, float))


def assert_appointment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "DISPATCHED", "COMPLETED", "CANCELLED"]
    assert data["dispatch_status"] in ["UNASSIGNED", "DISPATCHED", "IN_SERVICE", "RELEASED"]
    assert data["pricing_status"] in [
        "NOT_QUOTED",
        "AUTO_QUOTED",
        "OVERRIDE_PENDING",
        "QUOTE_APPROVED",
        "QUOTE_REJECTED",
    ]
    assert isinstance(data["quoted_price_cents"], int)
    assert isinstance(data["authorization_required"], bool)
    assert isinstance(data["labor_base_cents"], int)
    assert isinstance(data["sold_price_cents"], int)
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])


def assert_appointment_line(data: dict):
    # Append-only row: only id and created_at, never updated_at or version.
    assert is_valid_uuid(data.get("id", "")), "line id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "line created_at must be ISO 8601"
    assert "updated_at" not in data or data["updated_at"] is None
    assert "version" not in data or data["version"] is None
    assert data["status"] in ["PROPOSED", "SOLD", "DECLINED"]
    assert data["option_tier"] in [None, "GOOD", "BETTER", "BEST"]
    assert isinstance(data["flat_rate_cents"], int)
    assert isinstance(data["sold_price_cents"], int)


def assert_revenue_ledger_entry(data: dict):
    # Append-only row: only id and created_at.
    assert is_valid_uuid(data.get("id", ""))
    assert data["entry_type"] in ["ACCRUAL", "REVERSAL"]
    assert isinstance(data["amount_cents"], int)
    if data["entry_type"] == "ACCRUAL":
        assert data["amount_cents"] >= 0, "an accrual is a positive addition"
    else:
        assert data["amount_cents"] <= 0, "a reversal negates the accrual"


def assert_override_request(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED"]
    assert data["requested_price_cents"] > 0
    assert isinstance(data["max_approved_price_cents"], int)


def assert_membership_agreement(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PENDING_PAYMENT", "ACTIVE", "OVERDUE", "CANCELLED"]
    assert data["term_months"] in [12, 24]
    assert len(data["homeowner_postal_code"]) == 5
    assert isinstance(data["collected_amount_cents"], int)
    assert isinstance(data["revenue_recognized_cents"], int)
    assert isinstance(data["unearned_revenue_balance_cents"], int)


def assert_membership_visit(data: dict):
    assert_common_fields(data)
    assert data["sequence_number"] >= 1
    assert data["status"] in ["SCHEDULED", "COMPLETED", "MISSED"]
    assert isinstance(data["deferred_revenue_cents"], int)


def assert_call_record(data: dict):
    assert_common_fields(data)
    assert data["coaching_status"] in ["UNREVIEWED", "COACHING_ASSIGNED", "REVIEWED"]
    assert data["duration_seconds"] >= 0
    assert isinstance(data["recording_uri"], str) and data["recording_uri"]


# ------------------------------------------------------------- invariants
def assert_branch_capacity_invariant(branch: dict):
    assert branch["capacity_consumed_hours"] >= 0
    assert branch["daily_dispatch_capacity_hours"] > 0


def assert_ledger_conservation(pre_total: int, post_total: int):
    """After an accrual and its paired reversal the total returns to its value."""
    assert post_total == pre_total, (
        f"ledger total must return to {pre_total} after the compensating pair, got {post_total}"
    )


def assert_capacity_conservation(pre_hours: float, post_hours: float, tol: float = 0.01):
    assert abs(post_hours - pre_hours) <= tol, (
        f"hours must return to {pre_hours} after the paired operations, got {post_hours}"
    )


def assert_hours_2dp(value: float):
    assert round(float(value), 2) == float(value), f"{value} is not held at two decimal places"


def assert_load_trace(trace: list, expected: list):
    assert trace == expected, f"expected trace {expected}, got {trace}"