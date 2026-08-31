"""Entity assertions and domain invariant checkers."""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_PASTURE_STATUSES = ["DRAFT", "AVAILABLE", "CLOSED"]
_POSTURES = ["OPEN", "RESTRICTED", "DESTOCK_ORDERED", "CLOSED"]
_LIFECYCLE = [
    "DRAFT", "PENDING_SIGNATURE", "SUSPENDED", "ACTIVE",
    "EARLY_REMOVAL_PENDING", "COMPLETED", "TERMINATED",
]
_BILLING = ["UNBILLED", "SETTLEMENT_ISSUED", "SETTLED"]
_LOT_STATUSES = [
    "SCHEDULED", "RECEIVING_HELD", "ON_FEED",
    "REMOVAL_SCHEDULED", "WEIGHED_OUT", "CLOSED",
]
_TREATMENT_STATUSES = ["RECORDED", "APPROVED", "DISPUTED", "VOIDED"]
_DEATH_STATUSES = ["REPORTED", "CONFIRMED", "REJECTED", "VOIDED"]
_TICKET_STATUSES = ["OPEN", "ASSIGNED_GRAZIER", "ASSIGNED_OWNER", "REPAIRED", "BILLED"]
_SETTLEMENT_STATUSES = ["DRAFT", "ISSUED", "DISPUTED", "ADJUDICATED", "FINAL", "VOID"]


# ---------------------------------------------------------------- time helpers
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant supplied by the API into an aware datetime."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected_iso: str, label: str = "timestamp") -> None:
    """Assert two ISO 8601 instants denote the same moment, ignoring formatting."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected {label} {expected_iso}, got {actual}"
    )


def assert_same_calendar_date(actual: str, expected_date: str, label: str = "date") -> None:
    """Assert a returned date (with or without a time part) is the expected day."""
    assert isinstance(actual, str) and actual, f"Expected a date for {label}, got {actual!r}"
    assert actual[:10] == expected_date[:10], (
        f"Expected {label} {expected_date}, got {actual}"
    )


# ------------------------------------------------------------- common envelopes
def assert_living_resource(data: dict, label: str) -> None:
    """id + created_at + updated_at + version, as PRD section 2.4 requires."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def assert_append_only_row(data: dict, label: str) -> None:
    """Append-only ledger rows carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


# --------------------------------------------------------------------- entities
def assert_grazier(data: dict) -> None:
    assert_living_resource(data, "Grazier")
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["liability_carrier"], str)


def assert_cattle_owner(data: dict) -> None:
    assert_living_resource(data, "CattleOwner")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["brand_registration"], str)
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["open_settlement_balance_cents"], int)
    assert data["credit_status"] in ["GOOD_STANDING", "DELINQUENT"]


def assert_range_consultant(data: dict) -> None:
    assert_living_resource(data, "RangeConsultant")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["certification_number"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2


def assert_pasture(data: dict) -> None:
    assert_living_resource(data, "Pasture")
    assert is_valid_uuid(data.get("grazier_id", "")), "Pasture.grazier_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert float(data["acres"]) > 0, "Pasture.acres must be greater than 0"
    assert data["forage_type"] in [
        "NATIVE_RANGE", "IMPROVED_PASTURE", "COOL_SEASON_MIX", "WARM_SEASON_MIX",
    ]
    assert data["water_source_type"] in ["WELL", "CREEK", "PIPELINE", "POND"]
    assert data["fence_class"] in ["CLASS_A", "CLASS_B", "CLASS_C"]
    assert data["operational_status"] in _PASTURE_STATUSES
    assert data["grazing_posture"] in _POSTURES
    assert isinstance(data["drought_destock_flag"], bool)
    assert_pasture_invariants(data)


def assert_pasture_invariants(data: dict) -> None:
    """Derived aggregates hanging off a pasture must stay internally consistent."""
    assert data["rated_head_days"] >= 0
    assert float(data["rated_aum"]) >= 0
    assert data["committed_head_days"] >= 0
    assert data["stocked_head_count"] >= 0
    assert data["open_critical_ticket_count"] >= 0
    rated = data["rated_head_days"]
    expected_util = 0 if rated == 0 else round(
        data["committed_head_days"] / rated * 100 + 1e-9, 2
    )
    assert abs(float(data["capacity_utilization_pct"]) - expected_util) < 0.011, (
        "Pasture.capacity_utilization_pct must be committed_head_days / rated_head_days "
        f"* 100 rounded to two places; got {data['capacity_utilization_pct']} for "
        f"{data['committed_head_days']}/{rated}"
    )


def assert_capacity_assessment(data: dict) -> None:
    assert_append_only_row(data, "CapacityAssessment")
    assert is_valid_uuid(data.get("pasture_id", ""))
    assert is_valid_uuid(data.get("assessor_id", ""))
    assert data["method"] in ["DRY_MATTER", "STOCKING_HISTORY"]
    assert 0 < float(data["utilization_pct"]) <= 60
    assert data["rated_head_days"] >= 0
    assert float(data["rated_aum"]) >= 0


def assert_drought_reading(data: dict) -> None:
    assert_append_only_row(data, "DroughtReading")
    assert is_valid_uuid(data.get("pasture_id", ""))
    assert 0 <= int(data["drought_index"]) <= 5
    assert 0 <= float(data["forage_remaining_pct"]) <= 100
    assert isinstance(data["consecutive_severe_count"], int)
    assert isinstance(data["triggered_destock"], bool)


def assert_grazing_contract(data: dict) -> None:
    assert_living_resource(data, "GrazingContract")
    assert is_valid_uuid(data.get("grazier_id", ""))
    assert is_valid_uuid(data.get("cattle_owner_id", ""))
    assert is_valid_uuid(data.get("pasture_id", ""))
    assert data["billing_mode"] in ["PER_HEAD_PER_DAY", "PER_POUND_OF_GAIN"]
    assert int(data["rate_cents"]) > 0
    assert 0 <= float(data["shrink_pct"]) <= 10
    assert 0 <= float(data["out_shrink_pct"]) <= 10
    assert int(data["head_count_committed"]) > 0
    assert int(data["head_value_cents"]) > 0
    assert int(data["min_days"]) >= 0
    assert 0 <= int(data["treatment_cost_split_pct"]) <= 100
    assert data["water_responsibility"] in ["GRAZIER", "OWNER", "SHARED"]
    assert data["fence_responsibility"] in ["GRAZIER", "OWNER", "SHARED"]
    assert data["death_loss_terms"] in ["OWNER_BEARS_ALL", "GRAZIER_SHARE_ABOVE_THRESHOLD"]
    assert data["lifecycle_status"] in _LIFECYCLE
    assert data["billing_status"] in _BILLING
    assert int(data["committed_head_days"]) >= 0


def assert_cattle_lot(data: dict) -> None:
    assert_living_resource(data, "CattleLot")
    assert is_valid_uuid(data.get("contract_id", ""))
    assert int(data["scheduled_head_count"]) > 0
    assert data["status"] in _LOT_STATUSES
    assert int(data["head_count_received"]) >= 0
    assert int(data["confirmed_death_head"]) >= 0
    assert int(data["days_on_feed"]) >= 0


def assert_weight_event(data: dict) -> None:
    assert_append_only_row(data, "WeightEvent")
    assert is_valid_uuid(data.get("lot_id", ""))
    assert data["event_type"] in ["IN", "INTERIM", "OUT"]
    assert float(data["gross_weight_lbs"]) > 0
    assert int(data["head_count"]) > 0
    assert isinstance(data["scale_ticket_ref"], str)
    assert float(data["shrunk_weight_lbs"]) == int(data["shrunk_weight_lbs"]), (
        "WeightEvent.shrunk_weight_lbs must be a whole number of pounds"
    )


def assert_health_treatment(data: dict) -> None:
    assert_living_resource(data, "HealthTreatment")
    assert is_valid_uuid(data.get("lot_id", ""))
    assert data["classification"] in [
        "ROUTINE_PROTOCOL", "THERAPEUTIC", "PREVENTIVE_EMERGENCY",
    ]
    assert data["status"] in _TREATMENT_STATUSES
    assert int(data["head_treated"]) > 0
    assert int(data["drug_cost_cents"]) >= 0
    assert int(data["labor_cost_cents"]) >= 0
    assert int(data["withdrawal_days"]) >= 0
    assert_treatment_split_invariants(data)


def assert_treatment_split_invariants(data: dict) -> None:
    """total = drug + labor, and the grazier absorbs the residual cent."""
    assert data["total_cost_cents"] == data["drug_cost_cents"] + data["labor_cost_cents"], (
        "HealthTreatment.total_cost_cents must be drug_cost_cents + labor_cost_cents"
    )
    assert data["grazier_share_cents"] == data["total_cost_cents"] - data["owner_share_cents"], (
        "HealthTreatment.grazier_share_cents must be the total less the owner's share"
    )


def assert_death_loss_report(data: dict) -> None:
    assert_living_resource(data, "DeathLossReport")
    assert is_valid_uuid(data.get("lot_id", ""))
    assert data["cause"] in [
        "DISEASE", "PREDATOR", "WEATHER", "INFRASTRUCTURE_FAILURE", "UNKNOWN",
    ]
    assert data["status"] in _DEATH_STATUSES
    assert int(data["head_lost"]) > 0
    assert int(data["owner_liable_head"]) >= 0
    assert int(data["grazier_liable_head"]) >= 0
    assert int(data["credit_cents"]) >= 0
    if data["status"] == "CONFIRMED":
        assert data["owner_liable_head"] + data["grazier_liable_head"] == data["head_lost"], (
            "A confirmed report must split its head_lost between the two parties"
        )


def assert_infrastructure_ticket(data: dict) -> None:
    assert_living_resource(data, "InfrastructureTicket")
    assert is_valid_uuid(data.get("pasture_id", ""))
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data["asset_type"] in ["WATER", "FENCE"]
    assert data["severity"] in ["CRITICAL", "MAJOR", "MINOR"]
    assert data["status"] in _TICKET_STATUSES
    assert isinstance(data["description"], str)


def assert_settlement(data: dict) -> None:
    assert_living_resource(data, "Settlement")
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert data["status"] in _SETTLEMENT_STATUSES
    assert data["gain_method"] in [
        "PROVISIONAL_PRORATED", "FINAL_ADJUDICATED", "SPLIT_MIDPOINT",
    ]
    assert isinstance(data["dispute_round"], int) and data["dispute_round"] >= 0
    assert_settlement_waterfall(data)


def assert_settlement_waterfall(data: dict) -> None:
    """The waterfall identities the PRD pins in its strict evaluation order."""
    expected_subtotal = (
        data["base_charge_cents"]
        + data["treatment_charge_cents"]
        + data["infrastructure_charge_cents"]
        - data["death_loss_credit_cents"]
    )
    assert data["subtotal_cents"] == expected_subtotal, (
        "Settlement.subtotal_cents must be base + treatment + infrastructure - death credit; "
        f"got {data['subtotal_cents']}, expected {expected_subtotal}"
    )
    expected_total = (
        data["subtotal_cents"]
        + data["early_removal_adjustment_cents"]
        - data["volume_rebate_cents"]
    )
    assert data["total_due_cents"] == expected_total, (
        "Settlement.total_due_cents must be subtotal + early-removal adjustment - rebate; "
        f"got {data['total_due_cents']}, expected {expected_total}"
    )


def assert_money_is_integer_cents(value, label: str = "amount") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer count of cents, got {value!r}"
    )


def assert_whole_pounds(value, label: str = "weight") -> None:
    assert float(value) == int(float(value)), (
        f"{label} must be a whole number of pounds, got {value!r}"
    )
