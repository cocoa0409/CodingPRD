"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_production(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["production_type"] in ["ORIGINAL", "RESIDENCY", "CORPORATE"]
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["is_haptic_capable"], bool)
    assert data["status"] in ["DRAFT", "ACTIVE", "DARK", "RETIRED"]
    assert isinstance(data["gain_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_asset(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["production_id"], str)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["capture_format"] in ["WRAP_16K", "WRAP_8K"]
    assert isinstance(data["storage_gb"], int)
    assert data["status"] in ["CAPTURED", "RENDERING", "QC", "QC_FAILED", "APPROVED", "ARCHIVED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_render_batch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["OPEN", "RENDERING", "SETTLING", "SETTLED", "FAILED"]
    assert data["dispatch_mode"] in ["STANDARD", "RUSH"]
    assert isinstance(data["submitted_asset_count"], int)
    assert isinstance(data["failed_asset_count"], int)
    assert isinstance(data["submitted_asset_ids"], list)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_show(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["production_id"], str)
    assert data["show_format"] in ["FILM", "CONCERT", "CORPORATE"]
    assert isinstance(data["length_minutes"], int)
    assert data["status"] in ["TENTATIVE", "REHEARSAL", "CONFIRMED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["show_id"], str)
    assert data["zone"] in ["MAIN", "RING", "APEX"]
    assert isinstance(data["seats"], int) and data["seats"] >= 1
    assert data["seat_kind"] in ["STANDARD", "WHEELCHAIR", "COMPANION"]
    assert data["status"] in ["HELD", "CONFIRMED", "CANCELLED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_venue_system(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["kind"] in ["AUDIO_BEAM", "HAPTIC", "ENV_FX"]
    assert data["status"] in ["ONLINE", "MAINTENANCE", "DEGRADED", "OFFLINE"]
    assert isinstance(data["consecutive_failed_windows"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_maintenance_window(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["venue_system_id"], str)
    assert isinstance(data["buffer_minutes"], int)
    assert data["status"] in ["SCHEDULED", "ACTIVE", "COMPLETED", "FAILED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_sponsor(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["brand_tier"] in ["STANDARD", "PREMIUM"]
    assert isinstance(data["active_campaign_count"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_campaign(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["sponsor_id"], str)
    assert isinstance(data["exterior_slots"], int) and data["exterior_slots"] >= 1
    assert isinstance(data["spot_seconds"], int)
    assert isinstance(data["contracted_impressions"], int)
    assert isinstance(data["delivered_impressions"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_settlement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["show_id"], str)
    assert data["status"] == "FINAL"
    for field in ("gross_cents", "refunds_cents", "net_cents", "sponsor_payout_cents", "venue_retain_cents"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
