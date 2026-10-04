"""Entity assertions and domain invariant checkers for the Cookie Program API."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert isinstance(data, dict), f"{entity} payload must be an object"
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def assert_cookie_season(data: dict):
    _assert_common(data, "CookieSeason")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in [
        "DRAFT", "OPEN", "SELLING", "RECONCILIATION", "CLOSED", "CANCELLED",
    ]
    assert is_iso8601_timestamp(data["ordering_opens_at"])
    assert is_iso8601_timestamp(data["ordering_closes_at"])
    assert isinstance(data["initial_commit_units"], int)
    assert isinstance(data["pending_commit_units"], int)
    assert isinstance(data["purchased_units"], int)
    assert isinstance(data["remaining_units"], int)
    att = data.get("forecast_attainment_pct")
    assert att is None or isinstance(att, (int, float))


def assert_troop(data: dict):
    _assert_common(data, "Troop")
    assert isinstance(data["troop_number"], str) and len(data["troop_number"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["service_unit"], str)


def assert_cookie_product(data: dict):
    _assert_common(data, "CookieProduct")
    assert is_valid_uuid(data["season_id"])
    assert isinstance(data["variety_code"], str) and len(data["variety_code"]) > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 1
    assert isinstance(data["troop_proceeds_cents"], int)
    assert 0 < data["troop_proceeds_cents"] < data["unit_price_cents"]
    assert isinstance(data["allergen_tags"], list)
    for tag in data["allergen_tags"]:
        assert tag in ["PEANUT", "TREE_NUT", "MILK", "EGG", "WHEAT", "SOY", "SESAME"]
    assert isinstance(data["packages_per_case"], int) and data["packages_per_case"] >= 1


def assert_troop_account(data: dict):
    _assert_common(data, "TroopAccount")
    assert is_valid_uuid(data["troop_id"])
    assert is_valid_uuid(data["season_id"])
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["proceeds_accrued_cents"], int)
    assert isinstance(data["uncollected_amount_cents"], int)
    assert isinstance(data["deposit_cents"], int)


def assert_cookie_order(data: dict):
    _assert_common(data, "CookieOrder")
    assert is_valid_uuid(data["season_id"])
    assert is_valid_uuid(data["troop_id"])
    assert data["kind"] in ["INITIAL", "REPLENISHMENT"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "CONFIRMED", "FULFILLED", "REJECTED"]
    assert isinstance(data["total_units"], int)


def assert_cookie_order_line(data: dict):
    _assert_common(data, "CookieOrderLine")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["package_qty"], int) and data["package_qty"] >= 1


def assert_distribution_site(data: dict):
    _assert_common(data, "DistributionSite")
    assert is_valid_uuid(data["season_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["address"], str)
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] >= 1
    assert isinstance(data["received_units"], int)
    assert isinstance(data["hold_units"], int)
    assert isinstance(data["available_units"], int)
    assert data["posture"] in ["DRAFT", "RECEIVING", "FULL", "FROZEN"]


def assert_baker_purchase_order(data: dict):
    _assert_common(data, "BakerPurchaseOrder")
    assert is_valid_uuid(data["season_id"])
    assert isinstance(data["baker_name"], str) and len(data["baker_name"]) > 0
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert is_valid_uuid(data["delivery_site_id"])
    assert data["status"] in [
        "DRAFT", "ORDERED", "PARTIALLY_DELIVERED", "DELIVERED", "CANCELLED",
    ]
    assert isinstance(data["delivered_qty"], int) and data["delivered_qty"] >= 0


def assert_inventory_transfer(data: dict):
    _assert_common(data, "InventoryTransfer")
    assert is_valid_uuid(data["season_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["package_qty"], int) and data["package_qty"] >= 1
    assert data["status"] in [
        "REQUESTED", "SHIPPER_SIGNED", "RECEIVER_SIGNED",
        "COMPLETED", "DECLINED", "CANCELLED",
    ]


def assert_booth_location(data: dict):
    _assert_common(data, "BoothLocation")
    assert is_valid_uuid(data["season_id"])
    assert isinstance(data["host_business_name"], str)
    assert isinstance(data["host_permission_granted"], bool)
    assert isinstance(data["blackout_dates"], list)


def assert_booth_slot(data: dict):
    _assert_common(data, "BoothSlot")
    assert is_valid_uuid(data["location_id"])
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["capacity_troops"], int) and data["capacity_troops"] >= 1


def assert_booth_request(data: dict):
    _assert_common(data, "BoothRequest")
    assert is_valid_uuid(data["slot_id"])
    assert is_valid_uuid(data["troop_id"])
    assert data["mode"] in ["LOTTERY", "FIRST_COME"]
    assert data["status"] in ["PENDING", "APPROVED", "DENIED", "CANCELLED"]


def assert_digital_order(data: dict):
    _assert_common(data, "DigitalOrder")
    assert is_valid_uuid(data["season_id"])
    assert is_valid_uuid(data["troop_id"])
    assert data["fulfillment_type"] in ["SHIPPED", "IN_PERSON"]
    assert data["payment_status"] in ["PENDING", "PAID", "UNCOLLECTED", "REFUNDED"]
    assert data["fulfillment_status"] in ["OPEN", "DELIVERED", "CANCELLED"]
    assert isinstance(data["donation_units"], int) and data["donation_units"] >= 0
    assert isinstance(data["total_amount_cents"], int)


def assert_participant_agreement(data: dict):
    _assert_common(data, "ParticipantAgreement")
    assert is_valid_uuid(data["troop_id"])
    assert is_valid_uuid(data["season_id"])
    assert isinstance(data["participant_name"], str)
    assert isinstance(data["parent_name"], str)
    assert isinstance(data["signed_responsibility"], bool)
    assert isinstance(data["assigned_packages"], int) and data["assigned_packages"] >= 0
    assert isinstance(data["paid_amount_cents"], int) and data["paid_amount_cents"] >= 0
    assert isinstance(data["outstanding_cents"], int) and data["outstanding_cents"] >= 0
    assert data["incentive_tier"] in ["NONE", "BRONZE", "SILVER", "GOLD"]
    assert data["status"] in ["PENDING", "PAID", "DISPUTED", "FORFEITED"]


def assert_recall_notice(data: dict):
    _assert_common(data, "RecallNotice")
    assert is_valid_uuid(data["season_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["reason"], str) and len(data["reason"]) > 0
    assert is_iso8601_timestamp(data["effective_at"])
    assert data["status"] in ["DRAFT", "ACTIVE", "LIFTED"]
