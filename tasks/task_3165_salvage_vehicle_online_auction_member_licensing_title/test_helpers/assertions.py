"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

VALID_YARD_STATUSES = ["ACTIVE", "CLOSED"]
VALID_SELLER_STATUSES = ["ACTIVE", "SUSPENDED"]
VALID_SELLER_TYPES = ["INSURER", "DEALER", "FLEET"]
VALID_FEE_SCHEDULES = ["STANDARD", "VOLUME"]
VALID_MEMBER_STATUSES = ["ACTIVE", "SUSPENDED"]
VALID_MEMBER_TIERS = ["BASIC", "PREMIER", "BUSINESS"]
VALID_LICENSE_TYPES = ["DEALER", "DISMANTLER", "SALVAGE_BROKER"]
VALID_LICENSE_STATUSES = ["ACTIVE", "REVOKED"]
VALID_LOT_TYPES = ["STANDARD", "DEALER_ONLY", "DISMANTLER_ONLY", "EXPORT_ONLY"]
VALID_SALE_TYPES = ["PURE", "MINIMUM_BID", "ON_APPROVAL"]
VALID_PRIMARY_DAMAGE = ["FRONT", "REAR", "SIDE", "TOP", "MECHANICAL", "FLOOD", "FIRE", "NONE"]
VALID_RUN_AND_DRIVE = ["RUN_AND_DRIVE", "STARTS", "STATIONARY", "UNKNOWN"]
VALID_TITLE_BRANDS = ["NONE", "REBUILT"]
VALID_VEHICLE_STATUSES = [
    "ASSIGNED", "AWAITING_CONDITION", "SALE_READY", "LISTED", "LIVE",
    "SOLD", "ON_APPROVAL_PENDING", "RELEASED", "LOADED_OUT", "CANCELLED",
]
VALID_TITLE_TYPES = [
    "CLEAN", "SALVAGE", "REBUILT", "NON_REPAIRABLE", "PARTS_ONLY",
    "CERTIFICATE_OF_DESTRUCTION",
]
VALID_TRANSFERABILITY = ["TRANSFERABLE", "EXPORT_ONLY", "NON_TRANSFERABLE"]
VALID_TITLE_STATUSES = ["PENDING", "RECEIVED", "TRANSFERRED"]
VALID_AUCTION_STATUSES = ["SCHEDULED", "LIVE", "COMPLETED"]
VALID_AUCTION_ITEM_STATUSES = ["QUEUED", "LIVE", "CLOSED", "CANCELLED"]
VALID_BID_TYPES = ["PRELIM", "LIVE"]
VALID_SALE_STATUSES = ["PENDING_APPROVAL", "AWAITING_PAYMENT", "PAID", "CANCELLED"]
VALID_GATE_PASS_STATUSES = ["ISSUED", "CHECKED_IN", "COMPLETED", "EXPIRED"]
VALID_SETTLEMENT_STATUSES = ["DRAFT", "FINALIZED", "PAID"]
VALID_EXPORT_DOC_TYPES = ["BILL_OF_LADING", "EXPORT_DECLARATION", "CUSTOMS_MANIFEST"]
VALID_EXPORT_DOC_STATUSES = ["SUBMITTED", "VERIFIED", "REJECTED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_yard(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["daily_storage_rate_cents"], int) and data["daily_storage_rate_cents"] > 0
    assert isinstance(data["free_storage_days"], int) and data["free_storage_days"] >= 0
    assert data["status"] in VALID_YARD_STATUSES


def assert_seller(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["seller_type"] in VALID_SELLER_TYPES
    assert data["fee_schedule"] in VALID_FEE_SCHEDULES
    assert data["status"] in VALID_SELLER_STATUSES


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["home_state"], str) and len(data["home_state"]) == 2
    assert data["tier"] in VALID_MEMBER_TIERS
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert data["status"] in VALID_MEMBER_STATUSES


def assert_license(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["license_type"] in VALID_LICENSE_TYPES
    assert isinstance(data["expires_on"], str) and len(data["expires_on"]) == 10
    assert data["status"] in VALID_LICENSE_STATUSES


def assert_vehicle(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("seller_id", "")), "seller_id must be a UUID"
    assert is_valid_uuid(data.get("yard_id", "")), "yard_id must be a UUID"
    assert isinstance(data["vin"], str) and len(data["vin"]) == 17
    assert isinstance(data["year"], int)
    assert isinstance(data["make"], str) and isinstance(data["model"], str)
    assert data["lot_type"] in VALID_LOT_TYPES
    assert isinstance(data["reserve_price_cents"], int) and data["reserve_price_cents"] >= 0
    assert data["sale_type"] in VALID_SALE_TYPES
    assert isinstance(data["damage_codes"], list)
    assert data["primary_damage"] in VALID_PRIMARY_DAMAGE
    assert data["run_and_drive_status"] in VALID_RUN_AND_DRIVE
    assert isinstance(data["image_ids"], list)
    assert isinstance(data["image_count"], int) and data["image_count"] >= 0
    assert isinstance(data["odometer_reading"], int) and data["odometer_reading"] >= 0
    assert data["title_brand"] in VALID_TITLE_BRANDS
    assert is_iso8601_timestamp(data.get("assigned_at", "")), "assigned_at must be ISO 8601"
    assert data["status"] in VALID_VEHICLE_STATUSES


def assert_title_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("vehicle_id", "")), "vehicle_id must be a UUID"
    assert isinstance(data["jurisdiction_state"], str) and len(data["jurisdiction_state"]) == 2
    assert data["title_type"] in VALID_TITLE_TYPES
    assert is_iso8601_timestamp(data.get("received_at", "")), "received_at must be ISO 8601"
    assert data["transferability"] in VALID_TRANSFERABILITY
    assert isinstance(data["late"], bool)
    assert data["status"] in VALID_TITLE_STATUSES


def assert_auction(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_iso8601_timestamp(data.get("scheduled_start", "")), "scheduled_start must be ISO 8601"
    assert data["status"] in VALID_AUCTION_STATUSES
    assert isinstance(data["current_sequence_number"], int) and data["current_sequence_number"] >= 0


def assert_auction_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("auction_id", "")), "auction_id must be a UUID"
    assert is_valid_uuid(data.get("vehicle_id", "")), "vehicle_id must be a UUID"
    assert data["sequence_number"] is None or isinstance(data["sequence_number"], int)
    assert isinstance(data["prelim_high_bid_cents"], int) and data["prelim_high_bid_cents"] >= 0
    assert isinstance(data["high_bid_cents"], int) and data["high_bid_cents"] >= 0
    assert isinstance(data["reserve_met"], bool)
    assert data["status"] in VALID_AUCTION_ITEM_STATUSES


def assert_bid(data: dict):
    # Immutable event row: id + created_at only; no updated_at, no version.
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Bid must not carry version"
    assert "updated_at" not in data, "Bid must not carry updated_at"
    assert is_valid_uuid(data.get("auction_item_id", "")), "auction_item_id must be a UUID"
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["bid_type"] in VALID_BID_TYPES
    assert isinstance(data["is_winning"], bool)
    assert is_iso8601_timestamp(data.get("placed_at", "")), "placed_at must be ISO 8601"


def assert_sale(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("vehicle_id", "")), "vehicle_id must be a UUID"
    assert is_valid_uuid(data.get("auction_item_id", "")), "auction_item_id must be a UUID"
    assert is_valid_uuid(data.get("winner_member_id", "")), "winner_member_id must be a UUID"
    assert isinstance(data["winning_bid_cents"], int) and data["winning_bid_cents"] > 0
    assert isinstance(data["buyer_fee_cents"], int) and data["buyer_fee_cents"] >= 0
    assert data["status"] in VALID_SALE_STATUSES


def assert_gate_pass(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sale_id", "")), "sale_id must be a UUID"
    assert is_iso8601_timestamp(data.get("slot_start", "")), "slot_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("slot_end", "")), "slot_end must be ISO 8601"
    assert data["status"] in VALID_GATE_PASS_STATUSES
    assert isinstance(data["storage_fee_cents"], int) and data["storage_fee_cents"] >= 0


def assert_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sale_id", "")), "sale_id must be a UUID"
    assert is_valid_uuid(data.get("seller_id", "")), "seller_id must be a UUID"
    assert isinstance(data["gross_proceeds_cents"], int)
    assert isinstance(data["seller_fee_cents"], int)
    assert isinstance(data["storage_recovery_cents"], int)
    assert isinstance(data["title_late_penalty_cents"], int)
    assert isinstance(data["net_proceeds_cents"], int)
    assert data["status"] in VALID_SETTLEMENT_STATUSES


def assert_settlement_invariants(data: dict):
    """Domain invariants that must hold on every settlement (PRD §3.6)."""
    assert data["net_proceeds_cents"] == (
        data["gross_proceeds_cents"]
        - data["seller_fee_cents"]
        - data["storage_recovery_cents"]
        - data["title_late_penalty_cents"]
    ), "net_proceeds must equal gross - seller_fee - storage_recovery - title_late_penalty"


def assert_export_document(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sale_id", "")), "sale_id must be a UUID"
    assert data["document_type"] in VALID_EXPORT_DOC_TYPES
    assert isinstance(data["destination_country"], str) and len(data["destination_country"]) == 2
    assert data["status"] in VALID_EXPORT_DOC_STATUSES
