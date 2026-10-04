"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_store(data):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["party_room_count"], int) and data["party_room_count"] >= 1


def assert_customer(data):
    assert_common_fields(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]


def assert_staff_member(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a valid UUID"
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["role_title"] in ["ASSOCIATE", "PARTY_HOST", "MANAGER"]


def assert_station(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a valid UUID"
    assert data["station_type"] in ["SELECT", "STUFF", "SOUND", "BATHE", "DRESS"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_plush_model(data):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["is_licensed"], bool)
    assert isinstance(data["required_stuffing_grams"], int) and data["required_stuffing_grams"] > 0
    assert isinstance(data["sound_chip_compatible"], bool)


def assert_consumable(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a valid UUID"
    assert data["consumable_type"] in ["STUFFING_FIBER", "SOUND_CHIP"]
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["initial_qty"], int) and data["initial_qty"] >= 0


def assert_collection_drop(data):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data.get("plush_model_id", "")), "plush_model_id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("drop_start", "")), "drop_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("drop_end", "")), "drop_end must be ISO 8601"
    assert isinstance(data["per_customer_limit"], int) and data["per_customer_limit"] >= 1
    assert isinstance(data["total_units"], int) and data["total_units"] >= 1
    assert isinstance(data["units_claimed"], int)
    assert 0 <= data["units_claimed"] <= data["total_units"]


def assert_workshop_session(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a valid UUID"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a valid UUID"
    assert is_valid_uuid(data.get("plush_model_id", "")), "plush_model_id must be a valid UUID"
    assert data["origin_type"] in ["WALK_IN", "PARTY", "BUILD_SHIP"]
    assert isinstance(data["stuffing_grams_used"], int) and data["stuffing_grams_used"] >= 0
    assert isinstance(data["sound_chip_used"], bool)
    assert isinstance(data["total_price_cents"], int) and data["total_price_cents"] >= 0
    assert is_iso8601_timestamp(data.get("started_at", "")), "started_at must be ISO 8601"
    assert data["status"] in [
        "SELECT", "SELECTED", "STUFFED", "SOUNDED", "BATHED", "DRESSED", "PAID", "ABANDONED",
    ]


def assert_stuffed_animal(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a valid UUID"
    assert is_valid_uuid(data.get("plush_model_id", "")), "plush_model_id must be a valid UUID"
    assert is_valid_uuid(data.get("origin_workshop_session_id", "")), (
        "origin_workshop_session_id must be a valid UUID"
    )
    assert data["status"] in ["IN_PROGRESS", "COMPLETED", "LOST_REPORTED", "RECOVERED"]


def assert_party_reservation(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a valid UUID"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("party_start", "")), "party_start must be ISO 8601"
    assert data["duration_minutes"] == 120
    assert isinstance(data["guest_count"], int) and 6 <= data["guest_count"] <= 20
    assert data["package_tier"] in ["BASIC", "CELEBRATION", "ULTIMATE"]
    assert data["staffing_mode"] in ["STAFF_HOSTED", "SELF_GUIDED"]
    assert isinstance(data["deposit_amount_cents"], int)
    assert isinstance(data["paid_amount_cents"], int)
    assert isinstance(data["final_amount_due_cents"], int)
    assert data["status"] in ["QUOTED", "DEPOSIT_PAID", "CONFIRMED", "COMPLETED", "CANCELLED"]


def assert_party_guest(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("party_reservation_id", "")), (
        "party_reservation_id must be a valid UUID"
    )
    assert isinstance(data["guest_name"], str) and data["guest_name"]
    assert data["status"] in ["INVITED", "CONFIRMED", "ATTENDED", "NO_SHOW", "CANCELLED"]


def assert_appointment_block(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a valid UUID"
    assert is_valid_uuid(data.get("party_reservation_id", "")), (
        "party_reservation_id must be a valid UUID"
    )
    assert is_iso8601_timestamp(data.get("block_start", "")), "block_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("block_end", "")), "block_end must be ISO 8601"
    assert data["status"] in ["ACTIVE", "RELEASED"]


def assert_build_ship_order(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a valid UUID"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a valid UUID"
    assert is_valid_uuid(data.get("plush_model_id", "")), "plush_model_id must be a valid UUID"
    assert isinstance(data["sound_chip_requested"], bool)
    assert isinstance(data["recipient_name"], str) and data["recipient_name"]
    assert data["status"] in [
        "PLACED", "IN_ASSEMBLY", "READY_FOR_PICKUP", "HANDED_TO_CARRIER", "CANCELLED",
    ]


def assert_gift_card(data):
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0
    assert isinstance(data["initial_balance_cents"], int) and data["initial_balance_cents"] > 0
    assert data["status"] in ["ACTIVE", "EXHAUSTED", "DISABLED"]


def assert_registry(data):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a valid UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["linked_animal_ids"], list)
    assert isinstance(data["linked_gift_card_ids"], list)


def assert_consumable_invariant(data, initial_plus_restocks, consumed_minus_restored):
    """on_hand_qty == initial + restocks - consumed + restored (PRD §3.1)."""
    assert data["on_hand_qty"] == initial_plus_restocks - consumed_minus_restored, (
        f"ledger invariant violated: on_hand_qty {data['on_hand_qty']} != "
        f"{initial_plus_restocks} - {consumed_minus_restored}"
    )
