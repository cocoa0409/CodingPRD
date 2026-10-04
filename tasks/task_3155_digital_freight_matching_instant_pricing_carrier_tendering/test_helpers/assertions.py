"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)

from .types import (
    STATUS_RANK,
)


def _assert_common(data: dict, *, version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_money(value, field):
    assert isinstance(value, int), f"{field} must be an integer count of cents"


# --------------------------------------------------------------------------
# Entity assertions
# --------------------------------------------------------------------------
def assert_shipper(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert len(data["billing_state_code"]) == 2
    assert isinstance(data["payment_terms_days"], int)
    assert isinstance(data["credit_limit_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["credit_available_cents"] == data["credit_limit_cents"] - data["credit_used_cents"]
    assert data["load_credits_available"] == (
        data["load_credit_limit"] - data["load_credits_committed"]
    )
    assert isinstance(data["blocked_carrier_ids"], list)
    assert isinstance(data["breached_pickup_count"], int)


def assert_carrier(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["operating_authority_status"] in ("NONE", "PENDING", "ACTIVE", "REVOKED")
    assert data["status"] in (
        "PENDING", "AUTHORITY_VERIFIED", "INSURANCE_ON_FILE", "VERIFIED", "SUSPENDED",
    )
    assert isinstance(data["equipment_types"], list)
    assert 0.0 <= data["operational_risk_score"] <= 100.0
    assert isinstance(data["claims_clawback_count"], int)


def assert_equipment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["carrier_id"])
    assert data["equipment_type"] in ("DRY_VAN", "REEFER", "FLATBED")
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "IN_SHOP")
    assert isinstance(data["unit_number"], str) and len(data["unit_number"]) > 0


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["dock_capacity"], int) and data["dock_capacity"] >= 1
    assert data["status"] in ("ACTIVE", "CLOSED")
    assert isinstance(data["docks_committed_today"], int)
    assert isinstance(data["detention_rate_per_hour_cents"], int)


def assert_lane_contract(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED")
    assert data["equipment_type"] in ("DRY_VAN", "REEFER", "FLATBED")
    assert isinstance(data["contract_carrier_ids"], list)
    assert isinstance(data["committed_weekly_volume"], int)


def assert_load(data: dict):
    _assert_common(data)
    assert data["lane_key"] == (
        f"{data['lane_key'].split('>')[0]}>{data['lane_key'].split('>')[1]}"
    ), "lane_key must be '<ORIGIN>><DEST>'"
    assert len(data["lane_key"]) == 5, "lane_key is a five-character key"
    assert data["pricing_mode"] in ("SPOT", "CONTRACT")
    assert data["market_band"] in ("OPEN", "BALANCED", "TIGHT")
    assert data["equipment_type"] in ("DRY_VAN", "REEFER", "FLATBED")
    assert data["commodity"] in (
        "GENERAL", "TEMPERATURE_CONTROLLED", "HAZMAT", "HIGH_VALUE",
    )
    assert data["status"] in (
        "DRAFT", "POSTED", "UNCOVERED", "BOOKED", "IN_TRANSIT", "DELIVERED",
        "INVOICED", "PAID", "CANCELLED", "VOIDED",
    )
    assert isinstance(data["pickup_breach_flag"], bool)
    assert data["projected_delay_minutes"] >= 0
    assert isinstance(data["accessorial_total_cents"], int)
    assert isinstance(data["reprice_count"], int)
    assert isinstance(data["repost_count"], int)


def assert_rate_quote(data: dict):
    _assert_common(data)
    assert data["quote_kind"] in ("INITIAL", "REPRICED")
    assert data["status"] in (
        "ACTIVE", "VIEWED", "DECLINED", "ACCEPTED", "SUPERSEDED", "EXPIRED",
    )
    assert isinstance(data["base_rate_cents"], int)
    assert isinstance(data["min_rate_cents"], int)
    assert isinstance(data["viewed_carrier_ids"], list)
    assert isinstance(data["declined_carrier_ids"], list)
    assert is_iso8601_timestamp(data["acceptance_deadline"])
    assert data["effective_miles"] >= 50.0


def assert_booking(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING_APPOINTMENT", "IN_TRANSIT", "DELIVERED", "SETTLED", "CANCELLED",
    )
    assert isinstance(data["agreed_rate_cents"], int)
    assert isinstance(data["contract_lane_draw"], bool)
    assert isinstance(data["quick_pay_elected"], bool)
    assert is_iso8601_timestamp(data["booked_at"])


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["slot_kind"] in ("PICKUP", "DELIVERY")
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "COMPLETED", "MISSED", "CANCELLED",
    )
    assert isinstance(data["dock_position"], int)
    assert data["window_end"] > data["window_start"]


def assert_detention_event(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED", "WAIVED")
    assert data["dwell_minutes"] >= 0
    assert data["billable_detention_minutes"] >= 0
    assert isinstance(data["detention_charge_cents"], int)


def assert_tracking_ping(data: dict):
    """Append-only record: id and created_at only, no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "TrackingPing must not carry updated_at"
    assert "version" not in data, "TrackingPing must not carry version"
    assert STATUS_RANK[data["reported_status"]] == data["status_rank"]
    assert isinstance(data["sequence"], int)
    assert is_iso8601_timestamp(data["recorded_at"])


def assert_status_event(data: dict):
    """Append-only record: id and created_at only, no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "StatusEvent must not carry updated_at"
    assert "version" not in data, "StatusEvent must not carry version"
    assert data["source"] in ("DRIVER_APP", "SHIPPER_PORTAL", "PLATFORM")
    assert is_iso8601_timestamp(data["occurred_at"])


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DENIED",
        "ESCALATED", "SETTLED",
    )
    assert data["filed_by_role"] in ("SHIPPER", "CARRIER")
    assert data["claimed_amount_cents"] > 0
    assert isinstance(data["review_rounds"], int)
    assert isinstance(data["escalated"], bool)


def assert_settlement(data: dict):
    _assert_common(data)
    assert data["settlement_status"] in (
        "ACCRUED", "READY", "PAID", "CLAWED_BACK", "REVERSED",
    )
    for field in (
        "line_haul_cents", "accessorial_cents", "claims_deduction_cents",
        "gross_payable_cents", "quick_pay_discount_cents", "net_payable_cents",
    ):
        assert isinstance(data[field], int)


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_shipper_credit_invariants(data: dict):
    assert data["credit_limit_cents"] - data["credit_used_cents"] == data["credit_available_cents"]
    assert data["load_credit_limit"] - data["load_credits_committed"] == (
        data["load_credits_available"]
    )


def assert_carrier_risk_invariants(data: dict):
    assert 0.0 <= data["operational_risk_score"] <= 100.0, "risk score is clamped to [0, 100]"


def assert_settlement_arithmetic(data: dict):
    """The pinned evaluation order: gross before discount, net struck last."""
    assert data["gross_payable_cents"] == (
        data["line_haul_cents"] + data["accessorial_cents"] - data["claims_deduction_cents"]
    ), "gross is line haul plus accessorials minus the claim deduction"
    assert data["net_payable_cents"] == (
        data["gross_payable_cents"] - data["quick_pay_discount_cents"]
    ), "net is the gross minus the quick-pay discount"
    assert_cost_precision(data["net_payable_cents"])


def assert_settlement_reverses(forward: dict, reversal: dict):
    """A compensating row negates its forward row figure for figure."""
    for field in (
        "line_haul_cents", "accessorial_cents", "claims_deduction_cents",
        "quick_pay_discount_cents", "gross_payable_cents", "net_payable_cents",
    ):
        assert reversal[field] == -forward[field], (
            f"{field} of the compensating row must be the exact negation of the forward row"
        )
    assert reversal["reversal_of_settlement_id"] == forward["id"]
    assert reversal["settlement_status"] in ("ACCRUED", "REVERSED")
    assert forward["settlement_status"] == "REVERSED"