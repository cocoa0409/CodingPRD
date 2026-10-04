"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def assert_chart(data: dict):
    _assert_common_fields(data, "Chart")
    assert isinstance(data["chart_code"], str) and data["chart_code"]
    assert data["chart_kind"] in ["SINGLES", "ALBUMS"]
    assert data["chart_scope"] in ["MAIN", "GENRE"]
    assert isinstance(data["recurrent_rule_id"], str)


def assert_methodology_version(data: dict):
    _assert_common_fields(data, "MethodologyVersion")
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED", "FROZEN"]
    for field in ("w_sales", "w_on_demand", "w_programmed", "w_airplay"):
        assert isinstance(data[field], (int, float)) and data[field] >= 0
    for field in ("paid_stream_divisor", "ad_stream_divisor", "prog_stream_divisor", "tea_rate"):
        assert isinstance(data[field], int) and data[field] >= 1


def assert_chart_week(data: dict):
    _assert_common_fields(data, "ChartWeek")
    assert data["status"] in ["OPEN", "LOCKED", "COMPUTED", "PUBLISHED"]
    assert isinstance(data["week_index"], int)
    assert is_iso8601_timestamp(data["opens_at"])
    assert is_iso8601_timestamp(data["closes_at"])
    assert is_iso8601_timestamp(data["reporting_cutoff"])
    assert isinstance(data["holiday_adjusted"], bool)


def assert_provider(data: dict):
    _assert_common_fields(data, "Provider")
    assert data["feed_kind"] in ["SALES", "STREAM_ON_DEMAND", "STREAM_PROGRAMMED", "AIRPLAY"]
    assert data["territory"] in ["DOMESTIC", "INTERNATIONAL"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_title(data: dict):
    _assert_common_fields(data, "TitleProduct")
    assert data["product_kind"] in ["TRACK", "ALBUM"]
    assert data["eligibility_posture"] in ["ELIGIBLE", "DISQUALIFIED"]
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0


def assert_label(data: dict):
    _assert_common_fields(data, "LabelAccount")
    assert data["account_status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["strike_count"], int) and data["strike_count"] >= 0


def assert_recurrent_rule(data: dict):
    _assert_common_fields(data, "RecurrentRule")
    for field in ("max_weeks", "min_rank", "reentry_min_rank"):
        assert isinstance(data[field], int) and data[field] >= 1


def assert_report(data: dict):
    _assert_common_fields(data, "ConsumptionReport")
    assert data["component_kind"] in [
        "SALES", "STREAM_ON_DEMAND_PAID", "STREAM_ON_DEMAND_AD",
        "STREAM_PROGRAMMED", "AIRPLAY",
    ]
    assert data["status"] in ["RECEIVED", "ACCEPTED", "QUARANTINED", "REJECTED", "EXCLUDED"]
    assert isinstance(data["quantity"], int) and data["quantity"] > 0


def assert_sale_batch(data: dict):
    _assert_common_fields(data, "SaleBatch")
    assert data["channel"] in ["D2C", "RETAIL", "TICKET_BUNDLE", "MERCH_BUNDLE"]
    assert data["review_status"] in ["CLEARED", "UNDER_REVIEW", "REJECTED"]
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["countable_units"], int) and data["countable_units"] >= 0


def assert_signal(data: dict):
    _assert_common_fields(data, "ManipulationSignal")
    assert data["signal_kind"] in ["ARTIFICIAL_STREAMING", "BULK_PURCHASE", "TICKET_BUNDLE_ABUSE"]
    assert data["status"] in ["OPEN", "DISMISSED", "ESCALATED"]


def assert_investigation(data: dict):
    _assert_common_fields(data, "Investigation")
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_chart_entry(data: dict):
    _assert_common_fields(data, "ChartEntry")
    assert data["entry_status"] in ["ACTIVE", "RECURRENT_REMOVED", "RE_ENTERED"]
    assert isinstance(data["points"], (int, float))
    assert isinstance(data["weeks_on_chart"], int)


def assert_dispute(data: dict):
    _assert_common_fields(data, "GenreDispute")
    assert data["status"] in [
        "FILED", "UNDER_REVIEW", "RESOLVED_UPHELD", "RESOLVED_RECLASSIFIED",
    ]


def assert_chart_freeze(data: dict):
    _assert_common_fields(data, "ChartFreeze")
    assert data["status"] in ["ACTIVE", "RESOLVED"]


def assert_points_precision(points, expected, entity_desc: str = "entry"):
    """Points are rounded to exactly 4 decimal places, round-half-up (PRD §2.6)."""
    assert points == round(expected, 4), (
        f"{entity_desc}.points expected {round(expected, 4)}, got {points}")
