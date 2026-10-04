"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity}.version must be an int >= 1"


def assert_studio(data: dict):
    _assert_common(data, "Studio")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["ad_budget_cents"], int)


def assert_season(data: dict):
    _assert_common(data, "Season")
    assert is_valid_uuid(data.get("studio_id", "")), "Season.studio_id must be a UUID"
    assert isinstance(data["year"], int)
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["required_title_count"], int)
    assert isinstance(data["max_shoot_days"], int)
    assert isinstance(data["booked_shoot_days"], int)
    assert isinstance(data["committed_title_count"], int)
    assert isinstance(data["premiered_title_count"], int)
    assert data["status"] in ["DRAFT", "LOCKED", "ARCHIVED"]


def assert_title(data: dict):
    _assert_common(data, "Title")
    assert is_valid_uuid(data.get("season_id", "")), "Title.season_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert data["genre"] in ["ROMANCE", "FAMILY", "MYSTERY", "COMEDY"]
    assert data["tone_rating"] in ["GENTLE", "WARM", "FESTIVE"]
    assert isinstance(data["content_flags"], list)
    assert isinstance(data["duration_minutes"], int)
    assert data["status"] in ["PITCHED", "APPROVED", "IN_PRODUCTION", "DELIVERED", "REJECTED", "CANCELLED"]
    assert "delivered_at" in data


def assert_talent(data: dict):
    _assert_common(data, "Talent")
    assert is_valid_uuid(data.get("studio_id", "")), "Talent.studio_id must be a UUID"
    assert isinstance(data["stage_name"], str) and data["stage_name"]
    assert isinstance(data["availability_windows"], list)


def assert_deal(data: dict):
    _assert_common(data, "TalentDeal")
    assert is_valid_uuid(data.get("talent_id", "")), "TalentDeal.talent_id must be a UUID"
    assert is_valid_uuid(data.get("season_id", "")), "TalentDeal.season_id must be a UUID"
    assert isinstance(data["picture_commitment"], int)
    assert isinstance(data["fulfilled_pictures"], int)
    assert data["status"] in ["ACTIVE", "FULFILLED", "BREACHED"]


def assert_casting(data: dict):
    _assert_common(data, "Casting")
    assert is_valid_uuid(data.get("title_id", "")), "Casting.title_id must be a UUID"
    assert is_valid_uuid(data.get("talent_id", "")), "Casting.talent_id must be a UUID"
    assert data["status"] in ["ATTACHED", "CONFIRMED", "RELEASED"]


def assert_location(data: dict):
    _assert_common(data, "Location")
    assert is_valid_uuid(data.get("studio_id", "")), "Location.studio_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["blackout_windows"], list)


def assert_production_slot(data: dict):
    _assert_common(data, "ProductionSlot")
    assert is_valid_uuid(data.get("title_id", "")), "ProductionSlot.title_id must be a UUID"
    assert is_valid_uuid(data.get("location_id", "")), "ProductionSlot.location_id must be a UUID"
    assert isinstance(data["shoot_days"], int)
    assert data["status"] in ["BOOKED", "WRAPPED", "CANCELLED"]


def assert_program_block(data: dict):
    _assert_common(data, "ProgramBlock")
    assert is_valid_uuid(data.get("season_id", "")), "ProgramBlock.season_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert data["premiere_cadence_days"] in [7, 14]
    assert isinstance(data["max_encores_per_title"], int)
    assert data["status"] in ["DRAFT", "PUBLISHED", "CLOSED"]


def assert_air_slot(data: dict):
    _assert_common(data, "AirSlot")
    assert is_valid_uuid(data.get("block_id", "")), "AirSlot.block_id must be a UUID"
    assert is_valid_uuid(data.get("title_id", "")), "AirSlot.title_id must be a UUID"
    assert data["kind"] in ["PREMIERE", "ENCORE"]
    assert data["status"] in ["PLANNED", "AIRED", "CANCELLED"]


def assert_sponsorship(data: dict):
    _assert_common(data, "Sponsorship")
    assert is_valid_uuid(data.get("season_id", "")), "Sponsorship.season_id must be a UUID"
    assert isinstance(data["advertiser"], str) and data["advertiser"]
    assert isinstance(data["season_cpm_cents"], int)
    assert isinstance(data["viewership_thousands"], int)
    assert isinstance(data["projected_cost_cents"], int)
    assert data["status"] in ["BOOKED", "RECONCILED", "CANCELLED"]


def assert_streaming_window(data: dict):
    _assert_common(data, "StreamingWindow")
    assert is_valid_uuid(data.get("season_id", "")), "StreamingWindow.season_id must be a UUID"
    assert is_valid_uuid(data.get("title_id", "")), "StreamingWindow.title_id must be a UUID"
    assert data["platform"] in ["OWN_STREAMER", "PARTNER_STREAMER"]
    assert data["status"] in ["SCHEDULED", "OPEN", "CLOSED"]


def assert_license_grant(data: dict):
    _assert_common(data, "LicenseGrant")
    assert is_valid_uuid(data.get("season_id", "")), "LicenseGrant.season_id must be a UUID"
    assert is_valid_uuid(data.get("title_id", "")), "LicenseGrant.title_id must be a UUID"
    assert data["category"] in ["MERCHANDISE", "PUBLISHING"]
    assert isinstance(data["licensee"], str) and data["licensee"]
    assert isinstance(data["reported_revenue_cents"], int)
    assert isinstance(data["provisional_royalty_cents"], int)
    assert data["status"] in ["REPORTED", "AUDITED"]
