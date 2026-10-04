"""Entity assertions and domain invariant checkers."""
import pytest

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)

_KNOWN_STATUSES = {
    "RegionHub": {"OPEN", "RESTRICTED", "SUSPENDED"},
    "Region": {"active", "consolidated"},
    "PrintSite": {"active", "closing", "closed"},
    "PrintMarket": {"active", "consolidation_planned", "transfer_in_progress", "withdrawn"},
    "PrintRoute": {"eligible", "committed", "orphaned"},
    "LatestEdition": {
        "in_production", "on_time_dispatch", "late_dispatch",
        "delivered_market", "reverted_to_digital",
    },
    "DeliveryContractor": {"active", "suspended", "terminated"},
    "DeliveryRoute": {"prepared", "contract_active", "suspended", "terminated"},
    "DeliveryStop": {"active", "paused", "terminated"},
    "SubscriberContract": {
        "active", "paused", "migrated", "churned_pending_retention", "churned",
    },
    "NewsroomPosition": {"open", "closed"},
    "NewsroomChange": {"proposed", "approved", "applied", "rejected"},
    "TitleClosure": {"announced", "notice_published", "suspended", "merged", "archived"},
    "RetentionAction": {"open", "accepted", "expired", "cancelled"},
}


def assert_standard_fields(data: dict) -> None:
    """Every resource in this API carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_status(data: dict, entity: str, expected=None) -> None:
    status = data.get("status")
    assert status in _KNOWN_STATUSES[entity], (
        f"{entity}.status must be one of {sorted(_KNOWN_STATUSES[entity])}, got {status!r}"
    )
    if expected is not None:
        allowed = expected if isinstance(expected, (list, tuple, set)) else [expected]
        assert status in allowed, f"Expected {entity}.status in {list(allowed)}, got {status!r}"


# ─── Per-entity structure assertions ─────────────────────────────────

def assert_region_hub(data: dict):
    assert_standard_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["total_newsroom_headcount"], int)
    assert data["press_posture"] in _KNOWN_STATUSES["RegionHub"]
    assert isinstance(data["legal_notice_block"], bool)
    assert isinstance(data["min_on_time_ratio_pct"], int)
    assert isinstance(data["max_print_tonnage_budget_cents"], int)
    assert isinstance(data["transfer_cost_ceiling_cents"], int)
    assert isinstance(data["unassigned_headcount"], int)


def assert_region(data: dict):
    assert_standard_fields(data)
    assert is_valid_uuid(data["region_hub_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert_status(data, "Region")
    assert isinstance(data["region_need_score"], (int, float))
    assert isinstance(data["guaranteed_headcount"], int)
    assert isinstance(data["allocated_newsroom_headcount"], int)
    assert isinstance(data["member_market_count"], int)


def assert_print_site(data: dict):
    assert_standard_fields(data)
    assert is_valid_uuid(data["print_site_hub_id"])
    assert isinstance(data["code"], str) and data["code"]
    assert_status(data, "PrintSite")
    assert data["allocation_method"] in ("PRIORITY", "PROPORTIONAL")
    assert data["capacity_copies"] == (
        data["press_units"] * data["shifts_per_night"] * 8 * data["copies_per_hour_per_press"]
    ), f"capacity_copies mismatch: {data['capacity_copies']}"
    assert data["allocated_copies"] >= 0
    assert data["capacity_remaining_copies"] >= 0
    assert isinstance(data["annualized_savings_cents"], (int, float))
    assert isinstance(data["realized_savings_cents"], (int, float))
    assert isinstance(data["savings_divergence_cents"], (int, float))


def assert_print_market(data: dict):
    assert_standard_fields(data)
    assert is_valid_uuid(data["region_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert_status(data, "PrintMarket")
    assert data["frequency_change_status"] in (
        "none", "proposed", "notices_dispatched", "applied", "rejected",
    )
    assert data["single_copy_market_rule"] in ("newsstand", "carrier")
    assert data["route_selection_status"] in ("current", "needs_reassignment")
    assert isinstance(data["delivery_boycott_active"], bool)
    assert isinstance(data["transfer_cost_disputed"], bool)
    assert 1 <= data["print_edition_per_week"] <= 7


def assert_print_route(data: dict):
    assert_standard_fields(data)
    assert is_valid_uuid(data["origin_print_site_id"])
    assert is_valid_uuid(data["destination_market_id"])
    assert_status(data, "PrintRoute")
    assert isinstance(data["is_direct_hop"], bool)
    assert data["distance_miles"] == pytest.approx(
        round(data["transit_minutes"] / 60 * 55, 2), abs=0.01
    ), f"distance_miles mismatch: {data['distance_miles']}"
    assert isinstance(data["route_transport_cost"], (int, float))
    assert isinstance(data["marginal_cost_per_copy_cents"], (int, float))


def assert_latest_edition(data: dict):
    assert_standard_fields(data)
    assert is_valid_uuid(data["print_market_id"])
    assert isinstance(data["slug"], str) and data["slug"]
    assert_status(data, "LatestEdition")
    assert data["allocated_print_run_copies"] >= 0
    assert data["minutes_late"] >= 0
    assert data["late_edition_penalty_cents"] >= 0
    assert isinstance(data["is_on_time"], bool)
    assert data["next_edition_slot_taken"] in (0, 1)
    assert isinstance(data["correction_open"], bool)


def assert_delivery_contractor(data: dict):
    assert_standard_fields(data)
    assert is_valid_uuid(data["contractor_hub_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["pay_basis"] in ("PER_STOP", "PER_COPY")
    assert_status(data, "DeliveryContractor")
    assert isinstance(data["net_60_available"], bool)
    assert data["min_stop_guarantee"] >= 1


def assert_delivery_route(data: dict):
    assert_standard_fields(data)
    assert is_valid_uuid(data["delivery_contractor_id"])
    assert is_valid_uuid(data["print_market_id"])
    assert_status(data, "DeliveryRoute")
    assert isinstance(data["route_night_cost"], (int, float))
    assert isinstance(data["cost_per_copy_cents"], (int, float))
    assert isinstance(data["base_cost_cents"], (int, float))
    assert data["copy_volume_tier_pct"] in (0.00, 0.05, 0.10, 0.15)
    assert data["contractor_status_factor"] in (0.85, 1.00)
    assert data["cost_per_copy_cents"] >= 0


def assert_delivery_stop(data: dict):
    assert_standard_fields(data)
    assert is_valid_uuid(data["delivery_route_id"])
    assert is_valid_uuid(data["print_market_id"])
    assert isinstance(data["stop_code"], str) and data["stop_code"]
    assert_status(data, "DeliveryStop")
    assert data["pause_window_days"] >= 0


def assert_subscriber(data: dict):
    assert_standard_fields(data)
    assert is_valid_uuid(data["delivery_stop_id"])
    assert isinstance(data["subscriber_ref"], str) and data["subscriber_ref"]
    assert_status(data, "SubscriberContract")
    assert data["offer_status"] in ("none", "offered", "accepted", "declined")
    assert data["delivery_status"] in ("none", "paused", "resumed", "terminated")
    assert data["offer_recommendation"] in ("PRINT_CREDIT", "DIGITAL_UPGRADE", "FULL_REFUND")
    assert isinstance(data["migration_credit_cents"], int)
    assert isinstance(data["churn_retention_credit_cents"], int)
    assert data["churn_retention_credit_cents"] <= 5000
    assert data["churn_retention_credit_cents"] >= 0


def assert_newsroom_position(data: dict):
    assert_standard_fields(data)
    assert is_valid_uuid(data["region_id"])
    assert_status(data, "NewsroomPosition")
    assert isinstance(data["allocated_headcount"], int)
    assert data["monthly_cost_cents"] >= 1


def assert_newsroom_change(data: dict):
    assert_standard_fields(data)
    assert is_valid_uuid(data["newsroom_position_id"])
    assert is_valid_uuid(data["to_region_id"])
    assert is_valid_uuid(data["from_region_id"])
    assert_status(data, "NewsroomChange")
    assert isinstance(data["requested_slots"], int) and data["requested_slots"] >= 1
    assert isinstance(data["allocated_slots"], int)
    assert isinstance(data["residual_headcount"], int)
    assert isinstance(data["severance_cost_cents"], (int, float))


def assert_title_closure(data: dict):
    assert_standard_fields(data)
    assert is_valid_uuid(data["title_hub_id"])
    assert isinstance(data["title_code"], str) and data["title_code"]
    assert_status(data, "TitleClosure")
    assert data["archive_retention_years"] >= 1


def assert_retention_action(data: dict):
    assert_standard_fields(data)
    assert is_valid_uuid(data["subscriber_contract_id"])
    assert_status(data, "RetentionAction")
    assert isinstance(data["cooling_off_expires_utc"], str)
    assert data["retention_credit_cents"] >= 0


# ─── Domain invariant checkers ───────────────────────────────────────

def assert_print_site_invariants(data: dict):
    """Invariants that must hold after any site mutation."""
    assert data["allocated_copies"] >= 0
    assert data["capacity_remaining_copies"] >= 0
    assert data["capacity_remaining_copies"] == data["capacity_copies"] - data["allocated_copies"]
    assert_cost_precision(data["annualized_savings_cents"], 2)
    assert_cost_precision(data["realized_savings_cents"], 2)
    assert_cost_precision(data["savings_divergence_cents"], 2)


def assert_market_ledger_invariants(data: dict):
    """The transfer ledger conservation the market's derived fields obey."""
    assert_cost_precision(data["print_site_transfer_cost_cents"], 2)
    assert_cost_precision(data["print_site_transfer_credit_cents"], 2)
    assert_cost_precision(data["net_print_site_transfer_cost_cents"], 2)
    assert data["net_print_site_transfer_cost_cents"] == pytest.approx(
        data["print_site_transfer_cost_cents"] + data["print_site_transfer_credit_cents"], abs=0.01
    ), "net transfer cost must equal cost + credit"
    if data["status"] == "withdrawn":
        assert data["net_print_site_transfer_cost_cents"] == pytest.approx(0.0, abs=0.01)


def assert_route_cost_invariants(data: dict):
    """The nightly cost recipe's order-pinned invariants."""
    assert data["cost_per_copy_cents"] >= 0
    if data.get("copies_carried_night", 0) == 0:
        assert data["cost_per_copy_cents"] == pytest.approx(0.0, abs=1e-9)
    if data["status"] == "terminated":
        assert data["contractor_status_factor"] == pytest.approx(0.85, abs=1e-9)


def assert_hub_ratio_invariants(data: dict):
    """The compliance read's own arithmetic."""
    assert data["counted_market_count"] >= 0
    assert data["on_time_market_count"] >= 0
    assert data["on_time_market_count"] <= data["counted_market_count"]
    if data["counted_market_count"] == 0:
        assert data["is_legal_notice_ratio_compliant"] is False
    else:
        expected = (
            data["on_time_market_count"] * 100
            >= data["min_on_time_ratio_pct"] * data["counted_market_count"]
        )
        assert data["is_legal_notice_ratio_compliant"] is expected
    assert data["legal_notice_block"] is (not data["is_legal_notice_ratio_compliant"])