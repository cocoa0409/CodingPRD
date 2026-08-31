"""Entity assertions and domain invariant checkers."""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AdaptationStatus,
    CastingStatus,
    ContentRating,
    CutStatus,
    MixJobStatus,
    OrderStatus,
    PaymentDimension,
    PriorityTier,
    QualityReviewStatus,
    RetakeItemStatus,
    SessionStatus,
    StemLayout,
    StudioStatus,
    TalentPaymentStatus,
    UnionStatus,
    UsageVariant,
    VoiceTalentStatus,
)


def _members(enum_cls):
    return [m.value for m in enum_cls]


def assert_common_fields(data: dict, entity_name: str):
    """The four common properties every resource carries."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer of at least 1, got "
        f"{data.get('version')!r}"
    )


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating both 'Z' and an offset."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    normalised = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalised)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected_iso: str, label: str = "instant"):
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected the instant {expected_iso}, got {actual}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_title(data: dict):
    assert_common_fields(data, "Title")
    assert isinstance(data["title_code"], str) and data["title_code"]
    assert isinstance(data["source_language"], str) and data["source_language"]
    assert isinstance(data["runtime_seconds"], int) and data["runtime_seconds"] >= 1
    assert data["content_rating"] in _members(ContentRating)
    assert isinstance(data["cut_count"], int) and data["cut_count"] >= 0


def assert_cut(data: dict):
    assert_common_fields(data, "Cut")
    assert is_valid_uuid(data["title_id"])
    assert isinstance(data["cut_code"], str) and data["cut_code"]
    assert isinstance(data["loop_count"], int) and data["loop_count"] >= 1
    assert isinstance(data["runtime_seconds"], int) and data["runtime_seconds"] >= 1
    assert isinstance(data["conform_delta_seconds"], int)
    assert isinstance(data["lineage_depth"], int) and 0 <= data["lineage_depth"] <= 3
    assert isinstance(data["derived_cut_count"], int) and data["derived_cut_count"] >= 0
    assert data["status"] in _members(CutStatus)


def assert_character(data: dict):
    assert_common_fields(data, "Character")
    assert is_valid_uuid(data["title_id"])
    assert isinstance(data["character_code"], str) and data["character_code"]
    assert isinstance(data["loop_count"], int) and data["loop_count"] >= 0
    assert isinstance(data["screen_time_seconds"], int) and data["screen_time_seconds"] >= 0
    assert isinstance(data["is_principal"], bool)


def assert_platform_spec(data: dict):
    assert_common_fields(data, "PlatformSpec")
    assert isinstance(data["platform_code"], str) and data["platform_code"]
    assert -40.0 <= float(data["loudness_target_lufs"]) <= 0.0
    assert data["stem_layout"] in _members(StemLayout)
    assert isinstance(data["max_lipsync_deviation_ms"], int)
    assert data["max_lipsync_deviation_ms"] >= 1
    assert 0.0 <= float(data["min_fidelity_score"]) <= 1.0
    assert 0.0 <= float(data["qc_pass_threshold"]) <= 1.0
    assert isinstance(data["metadata_fields_required"], list)


def assert_voice_talent(data: dict):
    assert_common_fields(data, "VoiceTalent")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["language_code"], str) and data["language_code"]
    assert data["union_status"] in _members(UnionStatus)
    assert isinstance(data["base_rate_cents_per_hour"], int)
    assert data["base_rate_cents_per_hour"] >= 1
    assert isinstance(data["licensed_territories"], list) and data["licensed_territories"]
    assert isinstance(data["max_daily_recorded_minutes"], int)
    assert data["status"] in _members(VoiceTalentStatus)
    assert isinstance(data["held_minutes"], int) and data["held_minutes"] >= 0
    assert isinstance(data["recorded_minutes"], int) and data["recorded_minutes"] >= 0


def assert_studio(data: dict):
    assert_common_fields(data, "Studio")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 1
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert isinstance(data["daily_capacity_minutes"], int)
    assert isinstance(data["booked_minutes"], int) and data["booked_minutes"] >= 0
    assert data["status"] in _members(StudioStatus)


def assert_localization_order(data: dict):
    assert_common_fields(data, "LocalizationOrder")
    assert is_valid_uuid(data["cut_id"])
    assert is_valid_uuid(data["platform_spec_id"])
    assert isinstance(data["target_language"], str) and data["target_language"]
    assert data["priority_tier"] in _members(PriorityTier)
    assert isinstance(data["budget_cap_cents"], int) and data["budget_cap_cents"] >= 0
    assert data["status"] in _members(OrderStatus)
    assert_order_money_conserved(data)
    assert isinstance(data["retake_cycles"], int) and data["retake_cycles"] >= 0


def assert_order_money_conserved(order: dict):
    """gross_accrued_cents == committed_cents + released_cents (PRD 2.9)."""
    committed = order["committed_cents"]
    released = order["released_cents"]
    gross = order["gross_accrued_cents"]
    for name, value in (
        ("committed_cents", committed),
        ("released_cents", released),
        ("gross_accrued_cents", gross),
    ):
        assert isinstance(value, int), f"{name} must be a whole-cent integer"
    assert gross == committed + released, (
        "money conservation broken: gross_accrued_cents "
        f"{gross} != committed_cents {committed} + released_cents {released}"
    )


def assert_script_adaptation(data: dict):
    assert_common_fields(data, "ScriptAdaptation")
    assert is_valid_uuid(data["order_id"])
    assert data["status"] in _members(AdaptationStatus)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 1
    assert isinstance(data["declared_loop_count"], int)
    assert isinstance(data["measured_sync_deviation_ms_total"], int)
    assert isinstance(data["lines_over_deviation"], int)


def assert_casting_assignment(data: dict):
    assert_common_fields(data, "CastingAssignment")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["character_id"])
    assert is_valid_uuid(data["talent_id"])
    assert data["casting_status"] in _members(CastingStatus)
    assert data["payment_status"] in _members(PaymentDimension)
    assert data["usage_variant"] in _members(UsageVariant)
    assert isinstance(data["agreed_rate_cents_per_hour"], int)
    assert isinstance(data["recorded_minutes"], int) and data["recorded_minutes"] >= 0
    assert isinstance(data["retake_minutes"], int) and data["retake_minutes"] >= 0


def assert_recording_session(data: dict):
    assert_common_fields(data, "RecordingSession")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["studio_id"])
    assert is_valid_uuid(data["casting_assignment_id"])
    assert data["status"] in _members(SessionStatus)
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 0
    assert isinstance(data["is_retake"], bool)
    assert isinstance(data["session_cost_cents"], int)


def assert_mix_job(data: dict):
    assert_common_fields(data, "MixJob")
    assert is_valid_uuid(data["order_id"])
    assert data["status"] in _members(MixJobStatus)
    assert data["stem_layout"] in _members(StemLayout)
    assert isinstance(data["me_stem_present"], bool)
    assert isinstance(data["mix_round"], int) and data["mix_round"] >= 1


def assert_quality_review(data: dict):
    assert_common_fields(data, "QualityReview")
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["mix_job_id"])
    assert data["status"] in _members(QualityReviewStatus)
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["sampled_loop_count"], int)
    assert isinstance(data["defect_count"], int)


def assert_retake_item(data: dict):
    assert_common_fields(data, "RetakeItem")
    assert is_valid_uuid(data["quality_review_id"])
    assert is_valid_uuid(data["casting_assignment_id"])
    assert isinstance(data["loop_ref"], str) and data["loop_ref"]
    assert data["status"] in _members(RetakeItemStatus)
    assert isinstance(data["estimated_minutes"], int) and data["estimated_minutes"] >= 0


def assert_talent_payment(data: dict):
    assert_common_fields(data, "TalentPayment")
    assert is_valid_uuid(data["casting_assignment_id"])
    assert is_valid_uuid(data["talent_id"])
    assert data["variant"] in _members(UsageVariant)
    assert isinstance(data["territory_scope"], list) and data["territory_scope"]
    assert data["status"] in _members(TalentPaymentStatus)
    for field in ("base_fee_cents", "usage_fee_cents", "total_fee_cents"):
        assert isinstance(data[field], int), f"{field} must be a whole-cent integer"
    assert data["total_fee_cents"] == data["base_fee_cents"] + data["usage_fee_cents"], (
        "total_fee_cents must be base_fee_cents plus usage_fee_cents"
    )


def assert_invoice_shape(data: dict):
    """The computed invoice read reports the order id alongside all six figures."""
    for field in (
        "order_id",
        "recorded_subtotal_cents",
        "rush_surcharge_cents",
        "pre_discount_total_cents",
        "volume_discount_pct",
        "volume_discount_cents",
        "invoice_total_cents",
    ):
        assert field in data, f"invoice read must report {field}"
    assert (
        data["pre_discount_total_cents"]
        == data["recorded_subtotal_cents"] + data["rush_surcharge_cents"]
    )
    assert (
        data["invoice_total_cents"]
        == data["pre_discount_total_cents"] - data["volume_discount_cents"]
    )
