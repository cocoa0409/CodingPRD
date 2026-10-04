"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_tour(data: dict):
    _assert_common(data, "Tour")
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ["PLANNING", "ROUTING", "ON_ROAD", "WRAP", "CLOSED"]
    assert isinstance(data["home_base_city"], str)
    assert is_iso8601_timestamp(data["season_start_on"])
    assert is_iso8601_timestamp(data["season_end_on"])
    assert isinstance(data["market_cooldown_days"], int)
    assert isinstance(data["royalty_reserve_pct"], (int, float))
    assert isinstance(data["total_gross_cents"], int)
    assert isinstance(data["total_settlement_due_cents"], int)
    assert isinstance(data["open_engagement_count"], int)


def assert_venue(data: dict):
    _assert_common(data, "Venue")
    assert data["status"] in ["ACTIVE", "INACTIVE"]
    assert data["union_rule_set"] in ["IATSE", "TEAMSTERS", "NON_UNION"]
    assert isinstance(data["capacity_seats"], int)
    assert isinstance(data["load_in_dock_doors"], int)
    assert isinstance(data["default_rent_cents"], int)
    assert isinstance(data["percentage_share_pct"], (int, float))


def assert_rigging_point(data: dict):
    _assert_common(data, "RiggingPoint")
    assert data["status"] in ["AVAILABLE", "OUT_OF_SERVICE"]
    assert isinstance(data["max_static_load_kg"], int)
    assert isinstance(data["max_dynamic_load_kg"], int)
    assert isinstance(data["engineering_review_required"], bool)


def assert_date_avail(data: dict):
    _assert_common(data, "DateAvail")
    assert data["status"] in ["OPEN", "HELD", "BOOKED", "RELEASED"]
    assert is_iso8601_timestamp(data["opens_at"])
    assert is_iso8601_timestamp(data["closes_at"])
    assert isinstance(data["priority_rank"], int)


def assert_engagement(data: dict):
    _assert_common(data, "Engagement")
    assert data["status"] in [
        "HOLD",
        "CONFIRMED",
        "IN_LOAD",
        "SHOW_READY",
        "IN_PERFORMANCE",
        "SETTLED",
        "CANCELLED",
    ]
    assert data["deal_type"] in ["FLAT_RENT", "PERCENTAGE"]
    assert isinstance(data["agreed_rent_cents"], int)
    assert is_iso8601_timestamp(data["load_in_at"])
    assert is_iso8601_timestamp(data["first_show_at"])
    assert is_iso8601_timestamp(data["load_out_at"])
    assert is_iso8601_timestamp(data["hold_expires_at"])
    assert isinstance(data["market_overlap_flag"], bool)


def assert_rigging_plan(data: dict):
    _assert_common(data, "RiggingPlan")
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"]
    assert isinstance(data["revision_no"], int)


def assert_rigging_allocation(data: dict):
    _assert_common(data, "RiggingAllocation")
    assert isinstance(data["static_load_kg"], int)
    assert isinstance(data["dynamic_load_kg"], int)


def assert_labor_call(data: dict):
    _assert_common(data, "LaborCall")
    assert data["status"] in ["DRAFT", "POSTED", "FILLED", "SETTLED", "CANCELLED"]
    assert data["department"] in [
        "RIGGERS",
        "LOADERS",
        "WARDROBE",
        "ANIMAL_HANDLERS",
        "ELECTRICS",
    ]
    assert isinstance(data["headcount"], int)
    assert isinstance(data["hourly_rate_cents"], int)


def assert_truck_move(data: dict):
    _assert_common(data, "TruckMove")
    assert data["status"] in ["SCHEDULED", "DISPATCHED", "ARRIVED", "CANCELLED"]
    assert data["cargo_kind"] in ["VEHICLES", "ANIMALS", "PROPS", "RIGGING", "WARDROBE"]
    assert isinstance(data["truck_count"], int)
    assert isinstance(data["dock_doors_needed"], int)


def assert_ticket_scale(data: dict):
    _assert_common(data, "TicketScale")
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["seats_allocated"], int)
    assert isinstance(data["seats_sold"], int)
    assert isinstance(data["is_family_pack"], bool)
    assert isinstance(data["is_group_sales_only"], bool)
    assert isinstance(data["min_group_size"], int)


def assert_settlement(data: dict):
    _assert_common(data, "Settlement")
    assert data["status"] in ["OPEN", "RECONCILED", "PAID", "DISPUTED"]
    assert isinstance(data["gross_ticket_cents"], int)
    assert isinstance(data["venue_share_cents"], int)
    assert isinstance(data["royalty_withheld_cents"], int)
    assert isinstance(data["labor_total_cents"], int)
    assert isinstance(data["promoter_net_cents"], int)


def assert_license_agreement(data: dict):
    _assert_common(data, "LicenseAgreement")
    assert data["status"] in ["DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"]
    assert isinstance(data["royalty_pct"], (int, float))
    assert isinstance(data["minimum_guarantee_cents"], int)


def assert_safety_inspection(data: dict):
    _assert_common(data, "SafetyInspection")
    assert data["status"] in ["SCHEDULED", "PASSED", "FAILED", "WAIVED"]
    assert data["inspection_kind"] in [
        "RIGGING",
        "PYRO",
        "ANIMAL",
        "VEHICLE_STUNT",
        "ELECTRICAL",
    ]
    assert is_iso8601_timestamp(data["scheduled_at"])


def assert_settlement_waterfall_invariants(data: dict):
    """promoter_net == gross - venue_share - royalty - labor; no zero clamp."""
    assert data["promoter_net_cents"] == (
        data["gross_ticket_cents"]
        - data["venue_share_cents"]
        - data["royalty_withheld_cents"]
        - data["labor_total_cents"]
    ), "Settlement waterfall invariant violated"
