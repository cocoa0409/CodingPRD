"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data, *, with_version=True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def assert_talent(data: dict):
    _assert_common(data)
    assert isinstance(data.get("ring_name"), str) and data["ring_name"]
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert data.get("contractor_status") == "INDEPENDENT_CONTRACTOR"
    assert data.get("roster_tier") in ("DEVELOPMENTAL", "MAIN_ROSTER")
    assert data.get("availability_status") in ("ACTIVE", "INJURED", "SUSPENDED")
    assert isinstance(data.get("wellness_score"), (int, float))
    assert 0.0 <= float(data["wellness_score"]) <= 100.0
    assert data.get("booking_mode") in ("BOOKABLE", "LIMITED", "UNBOOKABLE")
    assert isinstance(data.get("likeness_granted"), bool)


def assert_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("talent_id", ""))
    assert isinstance(data.get("start_date"), str)
    assert isinstance(data.get("end_date"), str)
    assert isinstance(data.get("downside_guarantee_cents"), int)
    assert data["downside_guarantee_cents"] >= 0
    assert isinstance(data.get("royalty_rate_bp"), int)
    assert 0 <= data["royalty_rate_bp"] <= 5000
    assert isinstance(data.get("likeness_rights_granted"), bool)
    assert isinstance(data.get("min_appearances_per_quarter"), int)
    assert data["min_appearances_per_quarter"] >= 0
    assert data.get("status") in ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")


def assert_arena(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("city"), str) and data["city"]
    assert isinstance(data.get("country_code"), str) and len(data["country_code"]) == 2
    assert isinstance(data.get("capacity"), int) and data["capacity"] > 0
    assert isinstance(data.get("merch_booths"), int) and data["merch_booths"] >= 0
    assert isinstance(data.get("timezone"), str) and data["timezone"]


def assert_anchor(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("weekly_day_of_week"), int) and 1 <= data["weekly_day_of_week"] <= 7
    assert isinstance(data.get("territory_code"), str)
    assert isinstance(data.get("must_have_event_each_week"), bool)


def assert_event(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("event_type") in ("TELEVISION", "PREMIUM", "HOUSE_SHOW")
    assert is_valid_uuid(data.get("arena_id", ""))
    assert isinstance(data.get("event_date"), str)
    assert isinstance(data.get("start_time"), str)
    assert isinstance(data.get("end_time"), str)
    assert data.get("status") in ("SCHEDULED", "LOCKED", "COMPLETED", "CANCELLED")
    assert isinstance(data.get("roster_min_main"), int) and data["roster_min_main"] >= 0
    assert isinstance(data.get("roster_min_total"), int)
    assert data["roster_min_total"] >= data["roster_min_main"]


def assert_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("talent_id", ""))
    assert isinstance(data.get("segment_label"), str) and data["segment_label"]
    assert data.get("status") in ("BOOKED", "SCRATCHED", "FULFILLED", "NO_SHOW")


def assert_storyline(data: dict):
    _assert_common(data)
    assert isinstance(data.get("title"), str) and data["title"]
    assert data.get("status") in ("PLANNED", "ACTIVE", "SHELVED", "CONCLUDED")
    assert isinstance(data.get("gap_count"), int) and data["gap_count"] >= 0


def assert_chapter(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("storyline_id", ""))
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data.get("chapter_index"), int) and data["chapter_index"] >= 1
    assert data.get("status") in ("PLANNED", "COMPLETED", "MISSED")


def assert_streaming_partner(data: dict):
    _assert_common(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("partner_code"), str) and data["partner_code"]
    assert data.get("status") in ("ACTIVE", "SUSPENDED")


def assert_territory_right(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("partner_id", ""))
    assert isinstance(data.get("territory_code"), str)
    assert isinstance(data.get("window_start_date"), str)
    assert isinstance(data.get("window_end_date"), str)
    assert isinstance(data.get("exclusive"), bool)


def assert_distribution_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("partner_id", ""))
    assert isinstance(data.get("territory_code"), str)
    assert data.get("window_type") in ("LIVE", "REPLAY")
    assert isinstance(data.get("opens_at"), str)
    assert isinstance(data.get("closes_at"), str)
    assert data.get("status") in ("PROVISIONAL", "PUBLISHED", "REVOKED")


def assert_merch_sale(data: dict):
    """MerchSale is an immutable ledger entry: id + created_at only, no
    updated_at / version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "MerchSale must not expose updated_at"
    assert "version" not in data, "MerchSale must not expose version"
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("talent_id", ""))
    assert isinstance(data.get("quantity"), int) and data["quantity"] > 0
    assert isinstance(data.get("unit_price_cents"), int) and data["unit_price_cents"] >= 0
    assert isinstance(data.get("sold_at"), str)
    assert isinstance(data.get("royalty_cents"), int)


def assert_royalty_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("talent_id", ""))
    assert isinstance(data.get("period_start_date"), str)
    assert isinstance(data.get("period_end_date"), str)
    assert data.get("basis_mode") in ("PROVISIONAL", "FINAL")
    assert data.get("status") in ("OPEN", "FINALIZED")
    assert isinstance(data.get("total_sales_cents"), int)
    assert isinstance(data.get("total_royalty_cents"), int)


def assert_medical_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("talent_id", ""))
    assert data.get("severity") in ("MINOR", "MAJOR")
    assert isinstance(data.get("evaluation_ids"), list)
    assert "clearance_id" in data
    assert data.get("status") in ("OPEN", "CLEARED")


def assert_medical_evaluation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("medical_case_id", ""))
    assert isinstance(data.get("evaluator_id"), str) and data["evaluator_id"]
    assert isinstance(data.get("findings"), str)
    assert isinstance(data.get("recommends_clearance"), bool)


def assert_medical_clearance(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("medical_case_id", ""))
    assert isinstance(data.get("cleared_by"), str) and data["cleared_by"]
    assert is_iso8601_timestamp(data.get("cleared_at", ""))


def assert_visa_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("talent_id", ""))
    assert isinstance(data.get("country_code"), str) and len(data["country_code"]) == 2
    assert isinstance(data.get("required_by_date"), str)
    assert data.get("status") in ("DRAFT", "SUBMITTED", "GRANTED", "DENIED")


def assert_call_up_decision(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("talent_id", ""))
    assert isinstance(data.get("readiness_score"), int)
    assert 0 <= data["readiness_score"] <= 100
    assert data.get("decision") in ("PROMOTE", "DEFER")
    assert isinstance(data.get("decided_by"), str) and data["decided_by"]


def assert_wellness_invariants(data: dict):
    """Wellness score invariants that must hold after any operation (PRD §3.6)."""
    score = float(data["wellness_score"])
    assert 0.0 <= score <= 100.0, f"wellness_score {score} out of [0.00, 100.00]"
    # exactly two decimal places
    cents = round(score * 100)
    assert abs(score * 100 - cents) < 1e-9, "wellness_score must carry exactly 2 decimal places"
