"""Entity assertions — structural shape checks on response payloads."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_film(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["title"], str)
    assert isinstance(data["director_name"], str)
    assert isinstance(data["principal_cast"], list)
    assert data["genre"] in ["DRAMA", "COMEDY", "HORROR", "DOCUMENTARY", "THRILLER"]
    assert isinstance(data["runtime_minutes"], int) and data["runtime_minutes"] > 0
    assert isinstance(data["production_budget_cents"], int)
    assert data["acquisition_status"] in [
        "SHOPPING", "UNDER_NEGOTIATION", "ACQUIRED", "PASSED",
    ]
    assert data["release_posture"] in [
        "PRE_ACQUISITION", "PREMIERE_LOCKED", "PLATFORM", "EXPANDING",
        "WIDE", "HOME_WINDOW", "ARCHIVED",
    ]
    assert data["awards_posture"] in [
        "INELIGIBLE", "ELIGIBLE", "CAMPAIGNING", "SUBMITTED", "CONCLUDED",
    ]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_territory(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["code"], str) and 2 <= len(data["code"]) <= 8
    assert data["code"].isupper()
    assert isinstance(data["name"], str)
    assert isinstance(data["is_home_ent_eligible"], bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_festival(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["prestige_tier"] in ["A_LIST", "B_LIST", "REGIONAL"]
    assert isinstance(data["default_review_embargo_hours"], int)
    assert is_iso8601_timestamp(data.get("start_date", ""))
    assert is_iso8601_timestamp(data.get("end_date", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_premiere_slot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["section"] in ["COMPETITION", "MIDNIGHT", "PREMIERES", "NEXT"]
    assert data["status"] in ["OPEN", "HELD", "BOOKED", "CANCELLED"]
    assert isinstance(data["cachet_score"], int) and data["cachet_score"] >= 0
    assert is_iso8601_timestamp(data.get("screening_starts_at", ""))
    assert is_iso8601_timestamp(data.get("screening_ends_at", ""))
    assert is_iso8601_timestamp(data.get("review_embargo_lifts_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_offer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in [
        "OPEN", "COUNTERED", "ACCEPTED", "REJECTED", "WITHDRAWN", "EXPIRED",
    ]
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["upfront_price_cents"], int)
    assert isinstance(data["requested_territory_codes"], list)
    assert isinstance(data["requested_windows"], list)
    assert is_iso8601_timestamp(data.get("expiry_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_deal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ["EXECUTED", "IN_RELEASE", "CLOSED_OUT", "RESCINDED"]
    assert isinstance(data["upfront_price_cents"], int)
    assert isinstance(data["pa_spent_theatrical_cents"], int)
    assert isinstance(data["pa_spent_awards_cents"], int)
    assert isinstance(data["pa_shortfall_cents"], int)
    assert data["pa_shortfall_cents"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_rights_grant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["territory_code"], str)
    assert data["window"] in ["THEATRICAL", "STREAMING", "HOME_ENT", "TV"]
    assert data["status"] in ["GRANTED", "LAPSED", "REVOKED"]
    assert is_iso8601_timestamp(data.get("window_starts_at", ""))
    assert is_iso8601_timestamp(data.get("window_ends_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_release_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["platform_strategy"] in ["LIMITED_4", "LIMITED_8", "WIDE_DIRECT"]
    assert data["status"] in ["DRAFT", "OPENED", "EXPANDING", "WIDE", "PULLED"]
    assert isinstance(data["current_screen_count"], int)
    assert isinstance(data["cumulative_gross_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_market_screening(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ["SCHEDULED", "REPORTED", "EXPANSION_TRIGGERED", "PULLED"]
    assert isinstance(data["weekend_index"], int) and data["weekend_index"] >= 1
    assert isinstance(data["screen_count"], int) and data["screen_count"] > 0
    assert isinstance(data["weekend_gross_cents"], int)
    assert isinstance(data["per_screen_avg_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_awards_campaign(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["awards_body"] in [
        "OSCARS", "GOLDEN_GLOBES", "INDEPENDENT_SPIRIT", "BAFTA",
    ]
    assert data["status"] in ["PLANNING", "ACTIVE", "SUBMITTED", "CONCLUDED"]
    assert isinstance(data["budget_total_cents"], int)
    assert isinstance(data["budget_screenings_cents"], int)
    assert isinstance(data["budget_mailers_cents"], int)
    assert isinstance(data["budget_publicity_cents"], int)
    assert isinstance(data["budget_remaining_cents"], int)
    assert data["budget_remaining_cents"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_campaign_spend(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["category"] in [
        "SCREENING", "GUILD_MAILER", "PUBLICITY", "TRAVEL", "EVENT",
    ]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["eligible_amount_cents"], int)
    assert data["eligible_amount_cents"] >= 0
    assert is_iso8601_timestamp(data.get("incurred_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_talent_obligation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["obligation_kind"] in [
        "TRAVEL", "PRESS_JUNKET", "SCREENING_QA", "AWARDS_SHOW", "PHOTO_SHOOT",
    ]
    assert data["status"] in [
        "REQUESTED", "CONFIRMED", "FULFILLED", "BREACHED", "WAIVED",
    ]
    assert isinstance(data["talent_name"], str)
    assert isinstance(data["city_code"], str)
    assert is_iso8601_timestamp(data.get("window_starts_at", ""))
    assert is_iso8601_timestamp(data.get("window_ends_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_statement(data: dict):
    """FilmmakerStatement carries only id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["basis"] in ["GROSS_RECEIPTS", "NET_PROFITS"]
    assert data["statement_status"] in ["ISSUED", "FINAL"]
    assert isinstance(data["gross_receipts_cents"], int)
    assert isinstance(data["distribution_fee_cents"], int)
    assert isinstance(data["recoupable_costs_cents"], int)
    assert isinstance(data["filmmaker_participation_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "statements must not carry updated_at"
    assert "version" not in data, "statements must not carry version"
