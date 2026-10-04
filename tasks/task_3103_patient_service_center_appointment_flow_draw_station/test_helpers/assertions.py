"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_version_incremented,
)


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID string"
    assert data["id"] != "", "id must be non-empty"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["id"])
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_service_center(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert len(data["state_code"]) == 2
    assert isinstance(data["timezone_offset_minutes"], int)
    assert isinstance(data["station_count"], int) and data["station_count"] >= 1
    assert isinstance(data["slot_minutes"], int) and data["slot_minutes"] >= 1
    assert isinstance(data["open_local_minutes"], int)
    assert isinstance(data["close_local_minutes"], int)
    assert data["close_local_minutes"] > data["open_local_minutes"]
    assert isinstance(data["pediatric_capable"], bool)
    assert isinstance(data["draw_hold_minutes"], int)
    assert isinstance(data["ops_run_index"], int) and data["ops_run_index"] >= 0
    assert isinstance(data["staffed_minutes_available"], int)


def assert_patient(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_iso8601_timestamp(data["birth_date"])
    assert isinstance(data["mrn"], str) and len(data["mrn"]) > 0


def assert_phlebotomist(data: dict):
    _common(data)
    assert is_valid_uuid(data["service_center_id"])
    assert data["credential"] in ["PBT", "PBT_PEDIATRIC", "RN"]
    assert data["status"] in ["ON_DUTY", "OFF_DUTY"]
    assert isinstance(data["shift_start_local_minutes"], int)
    assert isinstance(data["shift_end_local_minutes"], int)
    assert data["shift_end_local_minutes"] > data["shift_start_local_minutes"]
    assert data["max_concurrent_attempts_referral"] == 2


def assert_test_order(data: dict):
    _common(data)
    assert data["status"] in ["RECEIVED", "SCHEDULED", "IN_PROGRESS", "COLLECTED", "CANCELLED"]
    assert data["necessity_status"] in ["PASS", "FAIL", "PENDING"]
    assert data["insurance_status"] in [
        "UNVERIFIED", "ELIGIBLE", "INELIGIBLE", "EXPIRED", "NOT_COVERED"
    ]
    assert data["collection_mode"] in [
        "SELF_SERVICE", "STANDARD", "PEDIATRIC", "DIFFICULT_DRAW"
    ]
    assert data["test_panel"] in [
        "CMP", "CBC", "LIPID", "A1C", "TSH", "PT_INR", "FERRITIN", "HCG_QUAL",
        "LACTATE", "GTT"
    ]
    assert isinstance(data["patient_is_pediatric"], bool)
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["patient_responsibility_cents"], int)
    assert isinstance(data["prepay_collected_cents"], int)
    assert isinstance(data["balance_remaining_cents"], int)
    assert data["balance_remaining_cents"] >= 0


def assert_insurance_plan(data: dict):
    _common(data)
    assert data["plan_type"] == "HMO"
    assert data["status"] in ["ACTIVE", "TERMINATED"]
    assert isinstance(data["copay_cents"], int)
    assert isinstance(data["allowed_amount_cents"], int)
    assert isinstance(data["coinsurance_pct"], (int, float))
    assert isinstance(data["prior_paid_pct"], (int, float))


def assert_appointment(data: dict):
    _common(data)
    assert data["draw_state"] in [
        "SCHEDULED", "CHECKED_IN", "STAFF_PENDING", "IN_DRAW", "ATTEMPT_LIMIT_REACHED",
        "DRAWN", "RESCHEDULED", "NO_SHOW"
    ]
    assert data["queue_state"] in [
        "NONE", "WAITING", "CALLED", "AT_STATION", "COMPLETED", "ABANDONED"
    ]
    assert data["source"] in ["BOOKED", "WALK_IN"]
    assert isinstance(data["slot_span"], int) and data["slot_span"] >= 1
    assert is_iso8601_timestamp(data["scheduled_start_utc"])
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    assert isinstance(data["complexity_score"], int)


def assert_tube_requirement(data: dict):
    _common(data)
    assert data["tube_code"] in [
        "EDTA_LAVENDER", "SST_GOLD", "SODIUM_CITRATE_BLUE",
        "SODIUM_FLUORIDE_GRAY", "SODIUM_HEPARIN_GREEN"
    ]
    assert isinstance(data["min_volume_ml"], (int, float))
    assert 0 < data["min_volume_ml"] <= data["required_volume_ml"]
    assert isinstance(data["order_of_draw"], int)
    assert isinstance(data["stability_minutes"], int) and data["stability_minutes"] > 0
    assert isinstance(data["is_recollection_eligible"], bool)


def assert_courier_run(data: dict):
    _common(data)
    assert data["status"] in ["PLANNED", "DISPATCHED", "IN_TRANSIT", "DELIVERED", "CANCELLED"]
    assert data["direction"] in ["OUTBOUND", "INBOUND"]
    assert is_iso8601_timestamp(data["dispatch_utc"])
    assert is_iso8601_timestamp(data["cutoff_utc"])
    assert isinstance(data["committed_specimen_count"], int)
    assert data["committed_specimen_count"] >= 0


def assert_specimen(data: dict):
    _common(data)
    assert data["status"] in [
        "UNASSIGNED", "ASSIGNED", "IN_TRANSIT", "RECEIVED", "COMPROMISED",
        "REJECTED", "RECOLLECTED"
    ]
    assert data["tube_code"] in [
        "EDTA_LAVENDER", "SST_GOLD", "SODIUM_CITRATE_BLUE",
        "SODIUM_FLUORIDE_GRAY", "SODIUM_HEPARIN_GREEN"
    ]
    assert isinstance(data["volume_ml"], (int, float))
    assert isinstance(data["order_of_draw"], int)
    assert is_iso8601_timestamp(data["collected_utc"])
    assert isinstance(data["day_rejection_index"], int) and data["day_rejection_index"] >= 0
    assert isinstance(data["rejection_waived"], bool)
    assert isinstance(data["tests_covered"], list)


def assert_responsibility_estimate(data: dict):
    _common(data)
    assert data["variant"] in [
        "PROVISIONAL_ELIGIBLE", "SELF_PAY_LIST", "ATTENDED_COLLECTED"
    ]
    assert isinstance(data["copay_component_cents"], int)
    assert isinstance(data["coinsurance_component_cents"], int)
    assert isinstance(data["deductible_component_cents"], int)
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["net_patient_cents"], int)


# ─── Domain invariant checkers ────────────────────────────────────────────────

def assert_order_invariants(data: dict):
    """Invariants that must hold on any read of a TestOrder."""
    assert data["balance_remaining_cents"] == max(
        0, data["patient_responsibility_cents"] - data["prepay_collected_cents"]
    ), "balance_remaining_cents must be the floored leftover of responsibility over collected"
    assert data["patient_responsibility_cents"] >= 0
    assert data["prepay_collected_cents"] >= 0
    assert data["self_pay_discount_cents"] == (
        data["self_pay_rate_cents"] - data["patient_responsibility_cents"]
    ) or data["self_pay_discount_cents"] >= 0


def assert_estimate_invariants(data: dict):
    """net = gross - discount for every estimate branch."""
    assert data["net_patient_cents"] == data["gross_cents"] - data["discount_cents"], (
        "estimate net must be gross minus discount"
    )


def assert_courier_invariants(data: dict):
    assert data["committed_specimen_count"] >= 0
    assert data["status"] in ["PLANNED", "DISPATCHED", "IN_TRANSIT", "DELIVERED", "CANCELLED"]


def assert_wait_band_consistent(wait_minutes: int, band: str):
    """The published band must agree with the published minutes."""
    if wait_minutes <= 10:
        assert band == "IMMEDIATE", f"{wait_minutes} should be IMMEDIATE, got {band}"
    elif wait_minutes <= 30:
        assert band == "WITHIN_WINDOW", f"{wait_minutes} should be WITHIN_WINDOW, got {band}"
    else:
        assert band == "EXTENDED", f"{wait_minutes} should be EXTENDED, got {band}"


def assert_draw_order_spec_ascending(spec):
    """draw_order_spec lists tubes by order_of_draw ascending."""
    ranks = []
    for row in spec:
        if isinstance(row, dict):
            ranks.append(row["order_of_draw"])
        else:
            ranks.append(row)
    assert ranks == sorted(ranks), f"draw_order_spec not ascending: {ranks}"