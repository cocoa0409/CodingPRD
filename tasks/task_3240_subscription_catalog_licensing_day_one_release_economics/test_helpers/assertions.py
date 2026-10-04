"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

FULL_FIELD_SET = ("id", "created_at", "updated_at", "version")
LIGHT_FIELD_SET = ("id", "created_at")


def _require(data: dict, key: str):
    assert key in data, f"expected field '{key}' on the resource, got keys {sorted(data)}"
    return data[key]


def assert_common_fields(data: dict):
    """The eleven resources that carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer starting at 1"


def assert_light_fields(data: dict):
    """Region and EngagementEvent carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Region and EngagementEvent carry no version field"
    assert "updated_at" not in data, "Region and EngagementEvent carry no updated_at field"


def assert_publisher(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["home_region_code"], str) and data["home_region_code"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["deal_count"], int) and data["deal_count"] >= 0
    assert isinstance(data["lifetime_licensing_cost_cents"], (int, float))
    assert data["lifetime_licensing_cost_cents"] >= 0


def assert_title(data: dict):
    assert_common_fields(data)
    assert isinstance(data["publisher_id"], str) and data["publisher_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["platform_set"], list) and data["platform_set"]
    assert set(data["platform_set"]) <= {"CONSOLE", "PC", "CLOUD"}
    assert isinstance(data["day_one_eligible"], bool)
    assert isinstance(data["list_price_cents"], (int, float)) and data["list_price_cents"] >= 0
    assert isinstance(data["unit_sales_30d"], int) and data["unit_sales_30d"] >= 0
    assert isinstance(data["weighted_engagement_score"], (int, float))
    assert data["status"] in ["DRAFT", "RELEASED", "RETIRED"]


def assert_region(data: dict):
    assert_light_fields(data)
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["currency_code"], str) and data["currency_code"]
    assert isinstance(data["price_multiplier"], (int, float)) and data["price_multiplier"] > 0
    assert isinstance(data["availability_ceiling_titles"], int)
    assert data["availability_ceiling_titles"] >= 1
    assert data["catalog_tier_floor"] in ["ESSENTIAL", "PREMIUM", "ULTIMATE"]
    assert data["capacity_status"] in ["WITHIN_CAPACITY", "OVER_CAPACITY"]


def assert_subscription_tier(data: dict):
    assert_common_fields(data)
    assert data["tier_code"] in ["ESSENTIAL", "PREMIUM", "ULTIMATE"]
    assert isinstance(data["monthly_price_cents"], (int, float))
    assert data["monthly_price_cents"] >= 0
    for flag in ("console_access", "pc_access", "cloud_access", "online_play_bundle"):
        assert isinstance(data[flag], bool), f"{flag} must be a boolean"
    assert 0 <= data["member_discount_pct"] <= 0.4
    assert isinstance(data["discount_retention_days"], int)
    assert data["discount_retention_days"] >= 0
    assert isinstance(data["annual_prepay_credit_ratio"], (int, float))
    assert data["annual_prepay_credit_ratio"] >= 0
    assert isinstance(data["current_subscriber_count"], int)


def assert_licensing_deal(data: dict):
    assert_common_fields(data)
    assert isinstance(data["publisher_id"], str) and data["publisher_id"]
    assert isinstance(data["title_id"], str) and data["title_id"]
    assert data["compensation_model"] in ["FIXED", "ENGAGEMENT", "HYBRID"]
    assert data["status"] in ["DRAFT", "SIGNED", "LIVE", "EXPIRING", "COMPLETED"]
    assert is_iso8601_timestamp(data["term_start_date"])
    assert is_iso8601_timestamp(data["term_end_date"])
    assert isinstance(data["compensation_floor_cents"], (int, float))


def assert_catalog_entry(data: dict):
    assert_common_fields(data)
    assert isinstance(data["title_id"], str) and data["title_id"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["tiers"], list) and data["tiers"]
    assert set(data["tiers"]) <= {"ESSENTIAL", "PREMIUM", "ULTIMATE"}
    assert data["release_class"] in ["DAY_ONE", "BACK_CATALOG", "CATALOG_ADD"]
    assert 0 <= data["popularity_index_cents"] <= 10000
    assert data["status"] in ["PLANNED", "ADDED", "REMOVING", "DELISTED"]
    assert isinstance(data["subscriber_impact_count"], int)


def assert_catalog_maintenance(data: dict):
    assert_common_fields(data)
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert is_iso8601_timestamp(data["maintenance_start"])
    assert is_iso8601_timestamp(data["maintenance_end"])
    assert 0 <= data["capacity_reduction_pct"] <= 1
    assert data["status"] in ["SCHEDULED", "ACTIVE", "COMPLETED"]


def assert_subscriber(data: dict):
    assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["display_name"], str)
    assert isinstance(data["home_region_code"], str) and data["home_region_code"]
    assert data["status"] == "ACTIVE"
    assert isinstance(data["wallet_credit_cents"], int)


def assert_subscription(data: dict):
    assert_common_fields(data)
    assert isinstance(data["subscriber_id"], str) and data["subscriber_id"]
    assert data["tier_code"] in ["ESSENTIAL", "PREMIUM", "ULTIMATE"]
    assert data["billing_period"] in ["MONTHLY", "ANNUAL"]
    assert isinstance(data["unpaid_months"], int) and data["unpaid_months"] >= 0
    assert isinstance(data["monthly_bill_cents"], (int, float))
    assert data["billing_status"] in ["PENDING", "PAID", "FAILED"]
    assert data["lifecycle_status"] in ["ACTIVE", "GRACE", "CANCELLED"]
    if data["lifecycle_status"] == "CANCELLED":
        assert data.get("cancellation_reason") == "USER_INITIATED"


def assert_entitlement(data: dict):
    assert_common_fields(data)
    assert isinstance(data["subscription_id"], str) and data["subscription_id"]
    assert isinstance(data["title_id"], str) and data["title_id"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["access_channels"], list)
    assert set(data["access_channels"]) <= {"CONSOLE", "PC", "CLOUD", "ONLINE_PLAY"}
    assert data["status"] in ["ACTIVE", "GRACE", "REVOKED"]


def assert_engagement_event(data: dict):
    assert_light_fields(data)
    assert isinstance(data["subscription_id"], str) and data["subscription_id"]
    assert isinstance(data["title_id"], str) and data["title_id"]
    assert data["channel"] in ["CONSOLE", "PC", "CLOUD", "ONLINE_PLAY"]
    assert isinstance(data["normalized_hours"], (int, float))


def assert_purchase(data: dict):
    assert_common_fields(data)
    assert isinstance(data["subscriber_id"], str) and data["subscriber_id"]
    assert isinstance(data["title_id"], str) and data["title_id"]
    assert isinstance(data["entry_id"], str) and data["entry_id"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert 0 <= data["discount_pct_applied"] <= 0.4
    assert isinstance(data["list_price_cents_per_unit"], (int, float))
    assert isinstance(data["total_charged_cents"], (int, float))
    assert isinstance(data["unit_sales_credit_cents"], (int, float))
    assert data["status"] in ["COMPLETED", "REFUNDED"]
    if data["status"] == "COMPLETED":
        assert data["wallet_restored_cents"] == 0, \
            "wallet_restored_cents is zero for every row that is still COMPLETED"


def assert_availability_projection(data: dict):
    assert_common_fields(data)
    assert isinstance(data["title_id"], str) and data["title_id"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["release_class"] in ["DAY_ONE", "BACK_CATALOG", "CATALOG_ADD"]
    assert data["decision"] in ["APPROVE_DAY_ONE", "HOLD_FOR_CATALOG", "REJECT_DAY_ONE"]
    assert data["status"] in ["DRAFT", "FINALIZED"]
    assert isinstance(data["projected_subscription_value_cents"], (int, float))
    assert isinstance(data["projected_cannibalized_unit_sales_cents"], (int, float))
    assert isinstance(data["projected_net_value_cents"], (int, float))


# --- Domain invariant checkers -------------------------------------------

def assert_region_capacity_invariants(data: dict):
    """capacity_deficit_slots is required minus usable; status follows the strict >."""
    required = data["capacity_required_slots"]
    usable = data["capacity_usable_slots"]
    assert abs(data["capacity_deficit_slots"] - (required - usable)) < 0.01, \
        "capacity_deficit_slots must equal required minus usable"
    if required > usable:
        assert data["capacity_status"] == "OVER_CAPACITY"
    else:
        assert data["capacity_status"] == "WITHIN_CAPACITY"
    assert data["capacity_utilization_pct"] >= 0


def assert_projection_decision_ladder(data: dict, day_one_eligible: bool):
    """The decision ladder, evaluated strictly in order."""
    net = data["projected_net_value_cents"]
    if (net >= 0 and day_one_eligible and data["release_class"] == "DAY_ONE"):
        expected = "APPROVE_DAY_ONE"
    elif net >= -50000:
        expected = "HOLD_FOR_CATALOG"
    else:
        expected = "REJECT_DAY_ONE"
    assert data["decision"] == expected, \
        f"expected decision {expected} for net {net}, got {data['decision']}"


def assert_subscriber_wallet_conservation(subscriber: dict, completed_purchases: list):
    """wallet_credit_cents + retained wallet_applied_cents is the conserved quantity."""
    retained = sum(p["wallet_applied_cents"] for p in completed_purchases)
    return subscriber["wallet_credit_cents"] + retained